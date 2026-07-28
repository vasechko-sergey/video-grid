"""Track the primary subject → route.json (spec §6.1)."""
import argparse, json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from scripts.lib import appearance, ffbin, proc
from scripts.lib import hero as hero_lib
from scripts.lib.footage import Cast
from scripts.lib.models import (HERO_KINDS, HERO_RULES, INTENTS, RoutePoint, TrackMeta,
                                TrackSpec, route_to_json)

# Ultralytics resolves bare model NAMES (auto-download on first use); an absolute
# path would NOT auto-download (landmine, design §12). setup.sh redirects the
# weight cache into models/.
MODEL = "yolo11n-seg.pt"

AMBIG_MARGIN = 0.8      # §6.1a margin rule: top-2 within ~20% ⇒ ambiguous ⇒ stop-and-report.
                        # One spelling, two readers (_pick_hero, _descriptor_track).

# --- ID-switch stitching (§6.1a) -------------------------------------------------
# ByteTrack drops a subject through an occlusion — spray, a passing lip, a frame the
# detector misses — and re-acquires it under a NEW id. The route is built from ONE id,
# so a switch truncates it, and reframe then holds the last crop position for the whole
# remainder: measured on a 9.14s drone ride, the hero track ended at 3.04s and the crop
# sat frozen for the other 6.10s while the rider carried on to the frame edge. That is
# not the frame gap the smoother bridges — it is 67% of the shot left uncomposed.
#
# The thresholds below are deliberately tight, because stitching too eagerly fails far
# worse than not stitching: splicing a STRANGER onto the hero's route teleports the crop
# mid-shot and reads as a cut. A candidate must resume within a blink, from about where
# the hero left off, at about the size the hero had.
STITCH_MAX_GAP_S = 0.40      # a re-acquisition later than this is not a blink
STITCH_MAX_OVERLAP_S = 0.50  # ...and a handover may also OVERLAP: ByteTrack routinely
                             # confirms the new id BEFORE it drops the old one, so the
                             # same rider reads as tid 1 over frames 0..182 and tid 66
                             # over 180..547 — a gap of -2. Measured overlaps run from 2
                             # to 29 frames on the same shot, so this is generous rather
                             # than tight: an overlapping pair is judged on where the two
                             # tracks sit ON THE FRAMES THEY SHARE (see _joinable), which
                             # is far stronger evidence than the length of the overlap.
STITCH_MIN_FRAMES = 5        # below this a "track" is detector noise, not a subject
STITCH_SPEED_SLACK = 3.0     # travel allowed = the hero's own mean speed x gap x this
STITCH_MIN_JUMP_FRAC = 0.02  # ...but never less than 2% of frame width (a slow hero)
STITCH_AREA_RATIO = 2.5      # apparent size may not change by more than this factor


def ensure_model(model_path: str = MODEL) -> None:
    """Materialize the weights ONCE, before any concurrent tracking starts.

    Ultralytics auto-downloads a bare model NAME on first use (see MODEL), so N
    workers starting on a cold cache would each begin the same download into the
    same path — concurrent writers to one file, silent corruption rather than a
    raise (design §12). Constructing the model here IS the fix: it performs the
    download, and every worker afterwards finds the file already on disk.
    Idempotent and cheap once warm. Callers that fan out over episodes MUST call
    this first (scripts/edl_to_reel.py).
    """
    # lazy import: heavy optional dep (ultralytics/torch), mirrors _iter_detections
    from ultralytics import YOLO
    YOLO(model_path)


def available() -> bool:
    """True iff the primary tracker's heavy deps import. The rung-1 gate in
    process_episode: an absent ultralytics/torch falls to the degradation ladder
    (design 2026-07-21 §2.1) instead of raising a traceback inside build_route on
    attempt 1. Mirrors flow.available()."""
    try:
        import ultralytics  # noqa: F401  — lazy: the whole point is to not require it
        return True
    except ImportError:
        return False


_Det = tuple[int, float, float, float, float]
_Frame = tuple[int, list[_Det]]


def _probe_meta(src: str) -> tuple[float, int, int]:
    """fps + dims from the source — never trust a caller-supplied default (4K/59.94 footage is the norm)."""
    r = proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=width,height,avg_frame_rate",
                  "-of", "json", src], text=True)
    s = json.loads(r.stdout)["streams"][0]
    num, den = s["avg_frame_rate"].split("/")
    den = float(den) or 1.0
    fps = float(num) / den
    if fps <= 0:
        raise ValueError(f"{src}: probed fps is {fps} — corrupt/streamed source? re-encode it first")
    return fps, int(s["width"]), int(s["height"])


def _iter_detections(src: str, model_path: str = MODEL) -> Iterator[tuple[int, Any]]:
    """Yield (frame_index, ultralytics_result) using YOLO+ByteTrack.

    Yields the whole result, not just .boxes: a cast-name hero pin needs the seg
    masks + frame pixels to build a per-track appearance descriptor (§6.1a). The
    masks are only READ on that path — every other pin costs nothing extra.
    Isolated for testability; res.boxes expose .xywh, .id, .cls like ultralytics.
    """
    # lazy import: heavy optional dep (ultralytics/torch)
    from ultralytics import YOLO
    model = YOLO(model_path)
    # imgsz=960: detect on downscaled frames (~10x faster on 4K); ultralytics
    # rescales box coords back to source resolution itself.
    for i, res in enumerate(model.track(src, stream=True, persist=True,
                                        classes=[0], tracker="bytetrack.yaml",
                                        imgsz=960, verbose=False)):
        yield i, res


def _seed_track(per_frame: list[_Frame], seed: tuple[float, ...], first_n: int = 5) -> int | None:
    """Track id with max IoU vs the seed bbox (centre-format) over first frames.

    The manifest's hero-pin (spec §5.10): resolves "which person" explicitly.
    """
    sx, sy, sw, sh = seed
    sl, st = sx - sw / 2, sy - sh / 2
    best, best_iou = None, 0.0
    for _, dets in per_frame[:first_n]:
        for tid, x, y, w, h in dets:
            l, t = x - w / 2, y - h / 2
            ix = max(0.0, min(sl + sw, l + w) - max(sl, l))
            iy = max(0.0, min(st + sh, t + h) - max(st, t))
            inter = ix * iy
            union = sw * sh + w * h - inter
            if union > 0 and inter / union > best_iou:
                best, best_iou = tid, inter / union
    return best


def _segments(per_frame: list[_Frame]) -> dict[int, dict]:
    """Per track id: first/last frame index, the bbox at each end, and every frame's
    x — `at` is what lets two OVERLAPPING segments be compared where they coexist."""
    segs: dict[int, dict] = {}
    for idx, dets in per_frame:
        for tid, x, y, w, h in dets:
            s = segs.get(tid)
            if s is None:
                segs[tid] = {"first": idx, "last": idx, "n": 1,
                             "head": (x, y, w, h), "tail": (x, y, w, h), "at": {idx: x}}
            else:
                s["last"] = idx
                s["n"] += 1
                s["tail"] = (x, y, w, h)
                s["at"][idx] = x
    return segs


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _joinable(a: dict, b: dict, gap: int, speed: float, src_w: int) -> bool:
    """Is segment `b` the same subject as `a`, resuming `gap` frames later (or, for a
    negative gap, `-gap` frames before `a` ends)?

    Two regimes, because they have different evidence available:

    OVERLAP — the tracks coexist on real frames, so ask the question directly: how far
    apart are they WHERE THEY BOTH EXIST? The same rider handed between two ids sits a
    few px apart on every shared frame; two different surfers stay apart on all of them.
    That is strictly better evidence than any endpoint comparison, so it is used alone —
    in particular the box-area gate is skipped, because a dying track's last boxes are
    degrading (that degradation is usually WHY it died) and comparing them against a
    fresh track's first boxes reads a healthy handover as a size change. Measured: a
    detector box collapsing 104x207 -> 70x116 through spray, 3px away, is one rider.

    GAP — nothing coexists, so fall back to the endpoints: the jump must fit the hero's
    own speed, and the box must be in the same size class (the distant-bystander guard).
    """
    shared = sorted(set(a["at"]) & set(b["at"]))
    reach = max(STITCH_MIN_JUMP_FRAC * src_w, speed * max(1, abs(gap)) * STITCH_SPEED_SLACK)
    if shared:
        return _median([abs(a["at"][i] - b["at"][i]) for i in shared]) <= reach
    ax, _ay, aw, ah = a["tail"]
    bx, _by, bw, bh = b["head"]
    if abs(bx - ax) > reach:
        return False
    area_a, area_b = aw * ah, bw * bh
    if area_a <= 0 or area_b <= 0:
        return False
    ratio = area_b / area_a
    return 1 / STITCH_AREA_RATIO <= ratio <= STITCH_AREA_RATIO


def stitch_ids(per_frame: list[_Frame], hero_id: int | None, fps: float,
               src_w: int | None, feats: dict[int, dict] | None = None) -> set[int]:
    """The hero id plus every id that is the SAME SUBJECT re-acquired after an
    ID switch — see the STITCH_* block for why this exists and why it is strict.

    Chains forward and backward from the hero, one hop at a time, so a subject
    dropped twice is followed twice; each candidate is judged against the segment
    it would attach to, never against the original hero, because a real subject
    drifts across a shot. A None hero (nobody picked) stitches nothing: there is
    no anchor, and guessing one here would resurrect exactly the largest-in-frame
    fallback build_route refuses below.
    """
    if hero_id is None:
        return set()
    if src_w is None:
        # build_route skips the probe when the caller supplies fps, and the reach
        # test is stated as a fraction of frame width. Without the width there is no
        # scale to judge a jump against, so DON'T stitch — an unstitched route is a
        # frozen crop the report shows, a mis-stitched one is a stranger nobody sees.
        return {hero_id}
    segs = _segments(per_frame)
    if hero_id not in segs:
        return {hero_id}
    speed = (feats or {}).get(hero_id, {}).get("speed") or 0.0
    max_gap = max(1, round(STITCH_MAX_GAP_S * fps))
    max_overlap = max(1, round(STITCH_MAX_OVERLAP_S * fps))
    chosen = {hero_id}
    for forward in (True, False):
        cur = segs[hero_id]
        while True:
            cands = []
            for tid, s in segs.items():
                if tid in chosen or s["n"] < STITCH_MIN_FRAMES:
                    continue
                gap = (s["first"] - cur["last"]) if forward else (cur["first"] - s["last"])
                if not -max_overlap <= gap <= max_gap:
                    continue
                # A candidate must EXTEND the coverage, not sit inside it. Without this
                # the overlap tolerance would absorb a SHORT track shadowed near cur's
                # tail (forward) or head (backward): its gap is a small negative one
                # inside the overlap window, and on the frames it shares with cur it can
                # be close enough to pass _joinable — but it adds no new coverage, so
                # stitching it would splice a bystander into the middle of the route.
                if (s["last"] <= cur["last"]) if forward else (s["first"] >= cur["first"]):
                    continue
                a, b = (cur, s) if forward else (s, cur)
                # `a` always precedes `b` in TIME, so the reach test reads the same
                # way in both directions: tail-of-earlier vs head-of-later.
                if _joinable(a, b, gap, speed, src_w):
                    cands.append((abs(gap), tid, s))
            if not cands:
                break
            _d, tid, seg = min(cands)        # nearest in time; ties on the lower id
            chosen.add(tid)
            cur = seg
    return chosen


def _rule_track(feats: dict[int, dict], rule: str) -> int | None:
    """Track id chosen by a mechanical §5.10 rule pin. Ties break on the lowest
    track id so a re-run is deterministic.

    A rule makes no claim about identity — the human said "largest", so largest
    wins — which is why, unlike _descriptor_track and _pick_hero, this never
    reports ambiguity.

    An empty feats is an honest "unmatched" — nobody to pick — and returns None.
    A rule with no branch here is not: hero.resolve() and HeroPin both gate `rule`
    against HERO_RULES, so one that reaches this point can only come from a caller
    that bypassed them, and it raises. Answering it with leftmost instead would let
    a typo'd pin silently select a different VALID rule — the same silent
    substitution this slice exists to delete. The raise is keyed to the branches
    actually implemented, not to HERO_RULES membership, so growing that vocab
    without adding a rung here fails loud instead of falling through to leftmost.
    """
    if not feats:
        return None
    if rule == "largest":
        return min(feats, key=lambda tid: (-feats[tid]["area"], tid))
    if rule == "leftmost":
        return min(feats, key=lambda tid: (feats[tid]["x0"], tid))
    raise ValueError(f"_rule_track: rule {rule!r} has no branch here — the §5.10 rule pins "
                     f"are {list(HERO_RULES)}. hero.resolve()/HeroPin gate the rule before "
                     f"it reaches here, so an unrecognised one means a caller bypassed them "
                     f"(build the pin with hero.resolve()); a rule newly added to HERO_RULES "
                     f"means this function still needs its branch.")


def _id_track(feats: dict[int, dict], track_id: int) -> int | None:
    """Track id pinned explicitly (§5.10). Absent from this segment ⇒ unmatched."""
    return track_id if track_id in feats else None


def _track_crops(res: object, boxes: list[object],
                 crops: dict[int, tuple[float, list[float]]]) -> None:
    """Accumulate the highest-confidence crop DESCRIPTOR per track id, in place.

    Mirrors intake._people_timeline: one crop_and_mask per confidence improvement
    (≈ once per track), never once per frame. crop_and_mask carries the two
    landmines — ultralytics' orig_img is BGR, and the mask is in model space and
    must be resized to source dims — and returns (None, None) for a mocked result
    with no pixels, which is how every track test drives this.
    """
    for j, b in enumerate(boxes):
        if getattr(b, "id", None) is None:
            continue
        tid = int(b.id[0])
        conf = float(b.conf[0]) if getattr(b, "conf", None) is not None else 1.0
        if conf <= crops.get(tid, (-1.0,))[0]:
            continue
        crop_rgb, mask = appearance.crop_and_mask(res, j, b)
        if crop_rgb is not None:
            crops[tid] = (conf, appearance.build_descriptor(crop_rgb, mask))


def _descriptor_track(descs: dict[int, list[float]],
                      pin: tuple[float, ...]) -> tuple[int | None, bool]:
    """Track id whose appearance descriptor is closest to the pinned cast member's
    (§6.1a layer 2: a cast name makes descriptor similarity outrank kinematics).

    Returns (hero_id, ambiguous). Nobody within CAST_MATCH ⇒ (None, False) — the
    pinned person is not in this episode. The margin rule is expressed on DISTANCE
    (d1 >= AMBIG_MARGIN * d2 ⇒ ambiguous: the best match is not meaningfully closer
    than the runner-up), not on a similarity ratio, because lower-is-better here —
    a similarity transform pushes both terms to ~1.0 whenever both matches are
    good and would call every clean match ambiguous. Two people in similar
    clothing is §6.1a's mode 1, the failure a colour histogram is most exposed to.

    An exact tie (d1 == d2, including a perfect 0.0 double-match) is therefore
    ambiguous, not confident: identical distances mean a colour histogram cannot
    separate those two tracks at all, which is precisely when a human must look.
    """
    if not descs:
        return None, False
    ref = list(pin)                    # loop-invariant: one list, not one per track
    ranked = sorted(((appearance.descriptor_dist(d, ref), tid)
                     for tid, d in descs.items()))
    d1, hero_id = ranked[0]
    if d1 > appearance.CAST_MATCH:
        return None, False
    ambiguous = len(ranked) > 1 and d1 >= AMBIG_MARGIN * ranked[1][0]
    return hero_id, ambiguous


def _track_features(per_frame: list[_Frame], src_w: int | None = None,
                    src_h: int | None = None) -> dict[int, dict]:
    """Per-track: frame count, first→last displacement, mean bbox area,
    mean speed (px/frame), border share (spec §6.1a candidate discriminators).
    """
    feats = {}
    for _, dets in per_frame:
        for tid, x, y, w, h in dets:
            f = feats.setdefault(tid, {"n": 0, "x0": x, "x1": x, "area": 0.0,
                                        "_prev_x": None, "_speed_sum": 0.0,
                                        "_speed_n": 0, "_border_n": 0})
            f["n"] += 1
            f["x1"] = x
            f["area"] += w * h
            if f["_prev_x"] is not None:
                f["_speed_sum"] += abs(x - f["_prev_x"])
                f["_speed_n"] += 1
            f["_prev_x"] = x
            if src_w is not None and src_h is not None:
                l, t = x - w / 2, y - h / 2
                r, b = x + w / 2, y + h / 2
                margin_x, margin_y = 0.02 * src_w, 0.02 * src_h
                if (l <= margin_x or r >= src_w - margin_x
                        or t <= margin_y or b >= src_h - margin_y):
                    f["_border_n"] += 1
    for f in feats.values():
        f["disp"] = abs(f["x1"] - f["x0"])
        f["area"] /= max(1, f["n"])
        f["speed"] = f["_speed_sum"] / f["_speed_n"] if f["_speed_n"] else 0.0
        f["border"] = (f["_border_n"] / f["n"]) if (src_w is not None
                                                      and src_h is not None) else None
        for k in ("_prev_x", "_speed_sum", "_speed_n", "_border_n"):
            del f[k]
    return feats


def _pick_hero(feats: dict[int, dict], intent: str) -> tuple[int | None, bool]:
    """Intent-conditioned scoring (spec §6.1a) — NOT most-frames: the subject
    of an action shot crosses the frame in seconds while a bystander stands in
    frame the whole clip, so raw frame count is biased the wrong way.

    intent: "action" (motion dominates) | "static" (size + duration dominate).
    Returns (hero_id, ambiguous) — ambiguous when top-2 scores within 20%.

    An empty feats is an honest "unmatched" — nobody to pick — and returns None.
    An intent with no branch here is not: TrackSpec.__post_init__ gates intent
    against INTENTS, so one that reaches this point can only come from a caller
    that bypassed it, and it raises. Scoring it as static instead would let a
    typo'd intent silently select a different VALID mode — a wrong-but-plausible
    hero, delivered with no signal. The raise is keyed to the branches actually
    implemented, not to INTENTS membership, so growing that vocab without adding
    a rung here fails loud instead of falling through to static.
    """
    if not feats:
        return None, False
    mx = {k: (max(f[k] for f in feats.values()) or 1.0)
          for k in ("disp", "n", "area")}
    if intent == "action":
        wd, wn, wa = 2.0, 0.5, 0.3
    elif intent == "static":
        wd, wn, wa = 0.0, 1.0, 1.0
    else:
        raise ValueError(f"_pick_hero: intent {intent!r} has no branch here — the §6.1a "
                         f"scoring modes are {list(INTENTS)}. TrackSpec.__post_init__ gates "
                         f"intent before it reaches here, so an unrecognised one means a "
                         f"caller bypassed it (build the spec with TrackSpec); an intent "
                         f"newly added to INTENTS means this function still needs its branch.")

    def score(f: dict) -> float:
        return (wd * f["disp"] / mx["disp"] + wn * f["n"] / mx["n"]
                + wa * f["area"] / mx["area"])

    ranked = sorted(feats.items(), key=lambda kv: score(kv[1]), reverse=True)
    ambiguous = (len(ranked) > 1
                 and score(ranked[1][1]) >= AMBIG_MARGIN * score(ranked[0][1]))
    return ranked[0][0], ambiguous


def build_route(spec: TrackSpec, out: str | Path) -> list[RoutePoint]:
    """Track the hero subject → list[RoutePoint] + a TrackMeta sidecar (spec §6.1).

    spec: a TrackSpec (scripts/lib/models.py) — carries src/model/pin/intent/fps
    so the orchestrator can pass a manifest-derived intent instead of always
    "action" (#1), and a RESOLVED HeroPin (hero.resolve()) instead of a raw
    manifest value (§5.10) — never a tuple/str/int.
    """
    fps, src_w, src_h = spec.fps, None, None
    if fps is None:
        # never trust a caller-supplied default (4K/59.94 footage is the norm) —
        # a wrong fps silently desyncs route t, the crop expression's time axis
        fps, src_w, src_h = _probe_meta(spec.src)

    per_frame, crops = [], {}
    for idx, res in _iter_detections(spec.src, model_path=spec.model):
        boxes = list(res.boxes) if getattr(res, "boxes", None) is not None else []
        dets = []
        for b in boxes:
            if b.id is None:
                # unconfirmed ByteTrack detection (normal in first frames /
                # after occlusion) — do NOT fabricate a shared tid=-1 track,
                # it would merge unrelated people into one fake "hero"
                continue
            x, y, w, h = [float(v) for v in b.xywh[0]]
            tid = int(b.id[0])
            dets.append((tid, x, y, w, h))
        per_frame.append((idx, dets))
        # crop descriptors are only useful for a cast-name pin (§6.1a layer 2);
        # every other pin kind leaves `crops` empty at zero extra cost
        if spec.pin is not None and spec.pin.kind == "cast":
            _track_crops(res, boxes, crops)

    feats = _track_features(per_frame, src_w=src_w, src_h=src_h)
    # hero priority (§5.10): a pin decides, or intent-conditioned scoring does.
    # A pin that matches NOTHING does NOT fall through to scoring — that silent
    # substitution is the §6.1a bug this replaces. It reports pin_matched=False,
    # the route comes out empty, and orchestration raises hero-unmatched.
    hero_id, ambiguous, pin_matched = None, False, None
    if spec.pin is None:
        hero_id, ambiguous = _pick_hero(feats, spec.intent)
    elif spec.pin.kind == "bbox":
        hero_id = _seed_track(per_frame, spec.pin.bbox)
    elif spec.pin.kind == "rule":
        hero_id = _rule_track(feats, spec.pin.rule)
    elif spec.pin.kind == "track":
        hero_id = _id_track(feats, spec.pin.track_id)
    elif spec.pin.kind == "cast":
        hero_id, ambiguous = _descriptor_track({t: d for t, (_c, d) in crops.items()},
                                               spec.pin.descriptor)
    else:
        # HeroPin.kind is gated to HERO_KINDS at construction, so this branch is
        # reachable only if HERO_KINDS grows a kind with no matching rung here —
        # the same shape of bug _rule_track already refuses to paper over for an
        # unrecognised rule (silently answering with a DIFFERENT valid rung is
        # the exact substitution this slice deletes). Raise instead of quietly
        # treating an unrecognised kind as "cast".
        raise ValueError(f"build_route: HeroPin.kind {spec.pin.kind!r} has no dispatch rung "
                         f"here — the implemented pin kinds are 'bbox'/'rule'/'track'/'cast'. "
                         f"HeroPin gates kind against HERO_KINDS ({list(HERO_KINDS)}) before it "
                         f"reaches here, so this means HERO_KINDS grew a kind this dispatch "
                         f"still needs a branch for.")
    if spec.pin is not None:
        pin_matched = hero_id is not None
    # sidecar meta: the orchestrator reads `ambiguous` to fire the §4.1
    # stop-and-report (margin rule) with both candidates' crops, and reads
    # `pin_matched` to fire hero-unmatched when a pin matched nobody
    meta = TrackMeta(hero=hero_id, ambiguous=ambiguous, intent=spec.intent,
                     features={str(k): {kk: f[kk] for kk in
                                        ("n", "disp", "area", "speed", "border")}
                               for k, f in feats.items()},
                     pin_matched=pin_matched)
    Path(out).with_suffix(".meta.json").write_text(json.dumps(meta.to_dict()))

    route = []
    for idx, dets in per_frame:
        # hero only — NO largest-in-frame fallback: it would splice strangers'
        # coordinates into the route (false teleports for the continuity check);
        # a frame gap is fine, smoothing bridges it
        pick = next((d for d in dets if d[0] == hero_id), None)
        if pick:
            _, x, y, w, h = pick
            route.append(RoutePoint(t=idx / fps, x=x, y=y, w=w, h=h))
    route_to_json(route, out)
    return route


def _parse_seed(text: str) -> list[float]:
    """--seed 'x,y,w,h' → the raw bbox hero.resolve() turns into a HeroPin.

    Its own function so main()'s pin chain can test `is not None` like every other
    rung. `--seed ''` — an unset variable in a wrapper script, `--seed "$SEED"` — is
    falsy, and under a truthiness test it fell through every rung to raw=None, so
    resolve(None) returned "no pin" and a PINNED run silently became a scored one:
    this slice's own thesis, one level down. Refusing it inline was not enough
    either, because that hands a human float()'s bare "could not convert string to
    float: ''", which names neither the flag they typed nor the shape it wants.

    Length is deliberately NOT checked here: hero.resolve owns that rejection and
    words it ("got 2"). This parses, and nothing more.
    """
    try:
        return [float(p) for p in text.split(",")]      # float() strips its own whitespace
    except ValueError:
        raise ValueError(f"--seed {text!r} is not a bbox — pass four comma-separated numbers "
                         f"'x,y,w,h' (centre-format, in source px), e.g. "
                         f"--seed '900,540,220,480'") from None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--fps", type=float, default=None,
                    help="override probed fps (default: probe the source — "
                         "never trust a caller-supplied default)")
    ap.add_argument("--model", default=MODEL,
                    help="yolo11n-seg.pt (default) / yolo11s-seg.pt / "
                         "yolo11m-seg.pt for small/far subjects")
    # The four pin flags are four SPELLINGS of one pin, so at most one may be
    # given: the raw chain below resolves them by PRECEDENCE, and ungrouped that
    # makes `--rule largest --track-id 3` silently honour the rule and drop the
    # id — a human asking for one pin and quietly getting another, which is the
    # exact silent substitution this slice deletes everywhere else. The group
    # turns that tiebreak into an argparse error. --cast-json stays OUT of it: it
    # is not a pin, it is the registry --cast-name resolves against.
    pin = ap.add_mutually_exclusive_group()
    pin.add_argument("--seed", default=None,
                     help="hero pin: first-frame centre bbox 'x,y,w,h' in source px")
    pin.add_argument("--rule", default=None, choices=list(HERO_RULES),
                     help="hero pin: a mechanical rule (§5.10)")
    pin.add_argument("--track-id", type=int, default=None, help="hero pin: an explicit track id")
    pin.add_argument("--cast-name", default=None, help="hero pin: a name from --cast-json")
    ap.add_argument("--cast-json", default=None, help="cast.json — required with --cast-name")
    ap.add_argument("--intent", default="action", choices=["action", "static"],
                    help="hero scoring mode (spec §6.1a)")
    a = ap.parse_args()
    # the group guarantees at most one is set, so this reads "whichever pin was
    # given" (or None for no pin at all) — it is not a tiebreak. Each rung tests
    # PRESENCE, not truth, and that is what makes the claim above true: --seed '' and
    # --track-id 0 are both falsy and both real input, so a truthiness test reads
    # them as "no pin" and silently drops a pin the human gave. --rule is the one
    # rung argparse already covers — `choices` makes an empty value impossible.
    raw = (_parse_seed(a.seed) if a.seed is not None else
           a.rule if a.rule else
           a.track_id if a.track_id is not None else
           a.cast_name)
    cast = Cast.from_json(a.cast_json) if a.cast_json else None
    spec = TrackSpec(src=a.src, model=a.model, pin=hero_lib.resolve(raw, cast),
                     intent=a.intent, fps=a.fps)
    build_route(spec, a.out)


if __name__ == "__main__":
    main()
