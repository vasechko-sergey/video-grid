"""Track the primary subject → route.json (spec §6.1)."""
import argparse, json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from scripts.lib import appearance, proc
from scripts.lib import hero as hero_lib
from scripts.lib.footage import Cast
from scripts.lib.models import (HERO_KINDS, HERO_RULES, HeroPin, RoutePoint, TrackMeta,
                                TrackSpec, route_to_json)

# Ultralytics resolves bare model NAMES (auto-download on first use); an absolute
# path would NOT auto-download (landmine, design §12). setup.sh redirects the
# weight cache into models/.
MODEL = "yolo11n-seg.pt"

AMBIG_MARGIN = 0.8      # §6.1a margin rule: top-2 within ~20% ⇒ ambiguous ⇒ stop-and-report.
                        # One spelling, two readers (_pick_hero, _descriptor_track).

_Det = tuple[int, float, float, float, float]
_Frame = tuple[int, list[_Det]]


def _probe_meta(src: str) -> tuple[float, int, int]:
    """fps + dims from the source — never trust a caller-supplied default (4K/59.94 footage is the norm)."""
    r = proc.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
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
    """
    if not feats:
        return None, False
    mx = {k: (max(f[k] for f in feats.values()) or 1.0)
          for k in ("disp", "n", "area")}
    wd, wn, wa = (2.0, 0.5, 0.3) if intent == "action" else (0.0, 1.0, 1.0)

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
    manifest value (§5.10) — never a tuple/str/int, and never seed_bbox.
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--fps", type=float, default=None,
                    help="override probed fps (default: probe the source — "
                         "never trust a caller-supplied default)")
    ap.add_argument("--model", default=MODEL,
                    help="yolo11n-seg.pt (default) / yolo11s-seg.pt / "
                         "yolo11m-seg.pt for small/far subjects")
    ap.add_argument("--seed", default=None,
                    help="hero pin: first-frame centre bbox 'x,y,w,h' in source px")
    ap.add_argument("--rule", default=None, choices=list(HERO_RULES),
                    help="hero pin: a mechanical rule (§5.10)")
    ap.add_argument("--track-id", type=int, default=None, help="hero pin: an explicit track id")
    ap.add_argument("--cast-name", default=None, help="hero pin: a name from --cast-json")
    ap.add_argument("--cast-json", default=None, help="cast.json — required with --cast-name")
    ap.add_argument("--intent", default="action", choices=["action", "static"],
                    help="hero scoring mode (spec §6.1a)")
    a = ap.parse_args()
    raw = ([float(v) for v in a.seed.split(",")] if a.seed else
           a.rule if a.rule else
           a.track_id if a.track_id is not None else
           a.cast_name)
    cast = Cast.from_json(a.cast_json) if a.cast_json else None
    spec = TrackSpec(src=a.src, model=a.model, pin=hero_lib.resolve(raw, cast),
                     intent=a.intent, fps=a.fps)
    build_route(spec, a.out)
