"""footage-intake (stage 5.2): scan raw clips → scored candidate windows + cast
registry (design docs/specs/2026-07-12-footage-intake-design.md).

Mechanical CV: probe + PySceneDetect + one YOLO11-seg pass + vidstabdetect +
sub-scene carve + score + phash cull. The interactive hero-naming lives in the
footage-intake SKILL — Python cannot ask a human — this module only surfaces
crops and embeds them (512-d OSNet via lib/reid, design 2026-08-04).
"""
import argparse, json, statistics, tempfile
import shutil
import sys
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

import imagehash
from PIL import Image

from scripts import check_reel                    # reuse _hamming for cull dedup
from scripts.lib import assembly, carve, footage, intake_cache, reid, runlayout, vidstab
from scripts.lib.appearance import crop_bbox
from scripts.lib.intake_cache import CastEntry, ClipResult
from scripts.track import MODEL, ensure_model       # reuse the tracker's model choice

SAMPLE_FPS = 3.0
PROXY_LONG_SIDE = 960                             # analysis runs on a proxy downscaled to this long side (design 2026-08-01)
W_PRESENT, W_MOTION, W_STABLE = 0.44, 0.28, 0.28   # sum to 1. First cuts calibrated on ONE drone
                                                   # shoot (design 2026-08-06-intake-motion-scoring
                                                   # §8.1) — the SHAKY_CLIP precedent below.
CLIP_POOL_MIN = 5        # a clip with fewer windows has no distribution to rank inside, so its
                         # motion falls back to the pool. 10 of 99 clips in the tuning pool were
                         # in that state; first cut (design §4.1).
DYNAMIC_RANK = 0.5       # motion rank at or above which a window is DESCRIBED "dynamic". A rank,
                         # not an absolute value, because every comparison here is pool-relative.
DEDUP_DIST = 8                             # phash Hamming below which two windows are duplicates
BEST_FLOOR = 0.50        # `score` is a PERCENTILE now (design §4.2), so this is the top-half cut,
                         # not an absolute quality bar. The VALUE is deliberately unchanged: the
                         # meaning change is the fix, and inventing a new number on one shoot is
                         # what §8.1 warns against. As an absolute bar it passed 99.6% of a real
                         # 1565-window pool — i.e. it was inert.
SHAKY_CLIP = 0.02                                 # shake (fraction of frame width) above which a clip is shaky — tune on real footage.
                                                  # Its INPUT changed on 2026-07-20: the detect pass moved from the binary's default
                                                  # shakiness=5 to vidstab.DETECT_ARGS' 8, so recorded shake values shifted. The
                                                  # threshold is deliberately NOT re-tuned to compensate — no real footage has been
                                                  # through this pipeline, so any new value would be invented (design §5).
CLUSTER_COS = 0.30       # cosine cut for "same identity" in surfacing (design §5). A FIRST CUT
                         # calibratable on the real cache — no footage exists to tune it.
MAX_CAST = 15            # adaptive cap on surfaced identities; excess is dropped WITH a log (no silent cap)
_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi"}
DEFAULT_JOBS = 2          # 3 parallel full-clip passes pin every P-core (3x libx264 proxy
                          # alone is ~400s of CPU) and thermally throttle a laptop; 2 is the
                          # sustainable default. --jobs raises it on a cooled/desktop box or
                          # lowers it on tight memory (cap-3's knee was design 2026-07-18 §2).


def carve_windows(scene_cuts: list[float],
                  timeline: list[tuple[float, int, tuple[float, float, float, float] | None, list[int],
                                       dict[int, tuple[float, float, float, float]]]],
                  mags: list[float], fps: float, dur: float,
                  band: tuple[float, float] = carve.DEFAULT_BAND) -> list[tuple[float, float]]:
    """scene_cuts ∪ presence-transitions bound the raw spans; each span is carved on
    its activity curve by carve.units_for_span (design 2026-07-25-intake-activity-units
    §4). A span with people uses 2-D bbox displacement; a people-less span uses the
    resampled vidstab magnitudes. The subject curve is now identity-consistent (design
    2026-08-06-intake-motion-scoring §3.3): it used to be built from the primary bbox's
    centre, so in a crowd it tracked which person was largest and moved WINDOW
    BOUNDARIES on that artifact. A single shot shorter than the band's floor stays one
    whole window; a clip shredded into many too-short spans yields NO windows (empty is valid)."""
    bounds = {0.0, float(dur)}
    for t in scene_cuts:
        if 0.0 < t < dur:
            bounds.add(float(t))
    prev = None
    for row in timeline:
        t, n = row[0], row[1]
        present = n > 0
        if prev is not None and present != prev and 0.0 < t < dur:
            bounds.add(float(t))
        prev = present
    edges = sorted(bounds)
    raw = list(zip(edges, edges[1:]))
    spans: list[tuple[float, float]] = []
    for a, b in raw:
        samples = [row for row in timeline if a <= row[0] < b]
        times = [row[0] for row in samples] or [a]
        if any(row[1] > 0 for row in samples):
            curve = carve.subject_curve([row[4] for row in samples])
        else:
            curve = carve.camera_curve(mags, fps, times)
        spans.extend(carve.units_for_span(a, b, times, curve, band[0], band[1]))
    if not spans and len(raw) == 1:          # a single short shot (dur < the band's floor) — keep the whole clip
        a, b = raw[0]
        spans = [(round(a, 3), round(b - a, 3))]
    return spans


def _percentile_rank(values: list[float]) -> list[float]:
    """Each value's position in its own pool, on [0, 1], aligned to the input order.
    Ties share the mid-rank of their group, so equal inputs always get equal outputs
    — the property that lets a structurally constant factor shift every window
    equally instead of ordering them arbitrarily (design §4.2). A single value ranks
    0.5: it is neither above nor below anything."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.5]
    order = sorted(range(n), key=lambda i: values[i])
    out = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        r = ((i + j) / 2) / (n - 1)
        for k in range(i, j + 1):
            out[order[k]] = r
        i = j + 1
    return out


def _separated(vec: list[float]) -> int:
    """How many windows a blend term told apart: the pool size minus its largest tie
    group. A term whose every window shares one value separated NOTHING — it shifts
    the blend by a constant, which the final `_percentile_rank` then makes invisible
    to the ordering (design 2026-09-10 §4).

    Measured on the RANKED vector the blend consumes, not the raw input: that is
    what the ordering was actually built from. `motion` ranks per-clip above
    CLIP_POOL_MIN, so two clips can land a window on the same rank by coincidence
    (every clip's top window ranks 1.0) — its count is exact for the blend and a
    LOWER BOUND on what the raw measurement distinguished (§4.1). That asymmetry is
    safe in the direction that matters: a coincidence can only merge two values,
    never split one, so an inert term cannot be inflated into looking useful.
    """
    if not vec:
        return 0
    return len(vec) - max(Counter(vec).values())


def score_pool(clips: list[footage.FootageClip]) -> dict:
    """Fill every window's `score` and `description` from the WHOLE pool — Phase 2
    (design 2026-08-06-intake-motion-scoring §4). Mutates in place, like cull.

    Not computable in Phase 1, and that is the point: a per-clip worker cannot see
    a pool, and the absolute blend it used to compute could not rank. Three of its
    four terms were near-constant on real footage (`present` constant BY
    CONSTRUCTION, `_dur_fit` an exact zero for the 76% of windows carve emits at
    the band's floor, `stability` compressed 2-14x below its own divisor), leaving `score`
    ~ 0.61 + 0.25*motion — and the motion term saturated (§1.1/§1.2).

    Each factor is scaled on the scale its question deserves: `motion` by rank
    WITHIN ITS OWN CLIP ("the active moment of this shot"), falling back to the pool
    below CLIP_POOL_MIN windows; `shake` by rank across the pool (steadiness is a
    camera property, so a within-clip comparison asks nothing); `present` by rank
    across the pool too — "does this window hold the subject" is a whole-shoot
    comparison, and a pool where nobody is present then ties at a constant instead
    of contributing a uniform zero that still outweighs two ranks (design
    2026-09-10 §3). It was absolute until 2026-09-10, which summed a raw fraction
    against two percentiles: on the only real pool that was harmless because the
    term was near-constant, and it separated 3 windows of 1508 (§0.1). The blend is
    then ranked across the pool, so `score` IS a percentile — which makes a
    constant factor unable to distort the ordering, restores BEST_FLOOR's meaning,
    and makes saturation unrepresentable.

    Deterministic in the order of `clips`, which intake() has already re-sorted into
    `paths` order — so output stays byte-identical at any --jobs and cache mix
    (intake-parallel §2).

    Returns the separation report `Footage.scoring` carries: how many windows each
    term told apart, so a weight that bought nothing on this pool is visible instead
    of implied by its size."""
    windows = [w for c in clips for w in c.windows]
    if not windows:
        return {"windows": 0, "separated": {t: 0 for t in footage.SCORE_TERMS}}
    motion_fit = _percentile_rank([w.motion for w in windows])
    at = 0
    for c in clips:                      # a big enough clip ranks its own windows in place
        n = len(c.windows)
        if n >= CLIP_POOL_MIN:
            motion_fit[at:at + n] = _percentile_rank([w.motion for w in c.windows])
        at += n
    stability = _percentile_rank([-w.shake for w in windows])
    presence = _percentile_rank([w.present for w in windows])
    blend = [W_PRESENT * p + W_MOTION * m + W_STABLE * s
             for p, m, s in zip(presence, motion_fit, stability)]
    for w, sc, m in zip(windows, _percentile_rank(blend), motion_fit):
        w.score = round(sc, 3)
        w.description = _describe(w.people, w.shot_type, m)
    return {"windows": len(windows),
            "separated": {"present": _separated(presence),
                          "motion": _separated(motion_fit),
                          "shake": _separated(stability)}}


def _describe(people: int, shot: str, motion_rank: float) -> str:
    """The human line in FOOTAGE.md. `motion_rank` is the window's motion PERCENTILE
    in its comparison pool, not a raw fraction — the dynamic/calm call is a
    comparison, and a comparison needs the pool assembled, so it cannot be made by
    a per-clip worker (design §4.5). That pool is the whole intake pool only below
    `CLIP_POOL_MIN` windows; at or above it, `motion_rank` is CLIP-relative (design
    §8.8), not pool-relative — `_describe` does not need to know which, since
    `score_pool` has already resolved the rank either way before calling here."""
    who = "no people" if people == 0 else ("1 person" if people == 1 else f"{people} people")
    dyn = "dynamic" if motion_rank >= DYNAMIC_RANK else "calm"
    return f"{who}, {shot}, {dyn}"


def _windowed_shake(mags: list[float], windows: list[tuple[float, float]], fps: float, w: int) -> list[float]:
    out = []
    for a, d in windows:
        f0, f1 = int(a * fps), int((a + d) * fps)
        out.append(vidstab.mean_shake(mags[f0:f1], w))   # fraction of frame width
    return out


def _iter_seg(src: str, model_path: str = MODEL) -> Iterator[tuple[int, object]]:
    """Mirror track.py's YOLO+ByteTrack config. Yields (frame_index,
    ultralytics_result); the seg model's masks are no longer read (the cast crop is
    the raw bbox now, design 2026-08-04), only the boxes and their confidences."""
    from ultralytics import YOLO           # lazy import: heavy optional dep (ultralytics/torch)
    model = YOLO(model_path)
    for i, res in enumerate(model.track(src, stream=True, persist=True, classes=[0],
                                        tracker="bytetrack.yaml", imgsz=960, verbose=False)):
        yield i, res


def _people_timeline(src: str, fps: float, res: tuple[int, int],
                     sample_fps: float = SAMPLE_FPS) -> tuple[list, dict, dict]:
    """One seg pass → (timeline, best_by_track, presence_by_track).
    timeline: [(t, people, primary_bbox, track_ids, boxes_by_tid)] sampled at ~SAMPLE_FPS.
    primary = largest bbox (what shot size is measured from); boxes_by_tid = {tid: (cx,cy,w,h)}
    for that sample, the only shape motion can be differenced on (design
    2026-08-06-intake-motion-scoring §3.1). An untracked detection counts toward
    `people` but cannot appear in boxes_by_tid — it has no identity to follow.
    best: {tid: (conf, t, bbox_xywh)} — timestamp + PROXY box of each track's
    highest-confidence detection (the cast pass re-crops that moment from the
    ORIGINAL, unmasked — design 2026-08-04 §4.1). presence: {tid: seconds on screen}
    (sampled-frame count × step, the surfacing rank — design §4.1). Cheap: records a
    REF (a float + four numbers) per track, updated on confidence improvement — not
    per frame."""
    step = max(1, round(fps / sample_fps))
    timeline, best, seen = [], {}, {}            # best: tid -> (conf, t, bbox_xywh)
    for i, r in _iter_seg(src):
        boxes = list(r.boxes) if getattr(r, "boxes", None) is not None else []
        for b in boxes:
            tid = int(b.id[0]) if getattr(b, "id", None) is not None else None
            conf = float(b.conf[0]) if getattr(b, "conf", None) is not None else 1.0
            if tid is not None and conf > best.get(tid, (-1.0,))[0]:
                best[tid] = (conf, i / fps, tuple(float(v) for v in b.xywh[0]))
        if i % step:
            continue
        bbs = [tuple(float(v) for v in b.xywh[0]) for b in boxes]
        primary = max(bbs, key=lambda bb: bb[2] * bb[3]) if bbs else None
        by_tid = {int(b.id[0]): tuple(float(v) for v in b.xywh[0])
                  for b in boxes if getattr(b, "id", None) is not None}
        tids = sorted(by_tid)
        for tid in tids:
            seen[tid] = seen.get(tid, 0) + 1
        timeline.append((i / fps, len(bbs), primary, tids, by_tid))
    presence = {tid: n * (step / fps) for tid, n in seen.items()}
    return timeline, best, presence


def cull(clips: list, phash_of: object) -> None:
    """Rank all windows by score; a window whose phash Hamming distance to an
    already-kept higher-scored window is < DEDUP_DIST is a duplicate (compare by
    IMAGE, never by filename — several windows of one clip are legitimate). Mark
    best on dedup survivors with score >= BEST_FLOOR. Mutates FootageWindow.best.
    phash_of(clip, window) -> imagehash.ImageHash (injected; the driver closes it
    over footage_root)."""
    ranked = sorted(((c, w) for c in clips for w in c.windows),
                    key=lambda cw: cw[1].score, reverse=True)
    kept: list = []
    for c, w in ranked:
        h = phash_of(c, w)
        dup = any(check_reel._hamming(h, kh) < DEDUP_DIST for kh in kept)
        w.best = (not dup) and w.score >= BEST_FLOOR
        if not dup:
            kept.append(h)


def _centroid(descs: list[list[float]]) -> list[float]:
    import numpy as np
    m = np.asarray(descs, dtype="float64").mean(axis=0)
    n = float(np.linalg.norm(m)) or 1.0
    return (m / n).tolist()


def _crop_area(e: CastEntry) -> int:
    """Pixel area of a member's crop, in either CastEntry form: the live array's
    shape, or the cached PNG's header (Image.open reads the header, not the pixels).
    A member carrying neither answers 0 and so never wins, rather than raising —
    save_cast_candidates is where a crop-less entry is refused, at the point it would
    have to write one."""
    if e.crop_rgb is not None:
        h, w = e.crop_rgb.shape[:2]
        return int(w) * int(h)
    if e.crop:
        try:
            with Image.open(e.crop) as im:
                w, h = im.size
        except (OSError, ValueError):
            return 0
        return int(w) * int(h)
    return 0


def _largest(members: list[CastEntry]) -> CastEntry:
    """The member whose crop carries the most pixels — the one a HUMAN can name.

    Deliberately NOT the medoid this replaced. The medoid is the member closest to the
    cluster's embedding centroid, and identity-centrality is not legibility: measured
    over the 2026-06 run's 15 candidates, presence and crop area are ANTI-correlated
    (Spearman -0.486). The person with 479 s on screen was surfaced as a 16x19 crop —
    304 pixels — while the one with 32 s got 535x373, because a long presence averages
    over many distances and its centroid lands on a middling, usually distant, view
    (design §0.4).

    max() returns the first maximum, so a tie goes to the earlier member and the pick
    is deterministic."""
    return max(members, key=_crop_area)


def surface_crops(entries: list[CastEntry], max_cast: int = MAX_CAST) -> list[CastEntry]:
    """Cluster ALL tracks' embeddings into real identities (agglomerative, average
    linkage, cosine, cut at CLUSTER_COS), one CastEntry per cluster: descriptor =
    centroid (mean, re-L2-normed), representative crop = the LARGEST member's (design
    2026-09-08 §5 — the medoid picked for embedding centrality, which is
    anti-correlated with legibility), presence = sum over members. Ranked by presence
    (design §4.1); capped at max_cast with a logged drop — never a silent cap."""
    if not entries:
        return []
    if len(entries) == 1:
        labels = [1]
    else:
        import numpy as np
        from scipy.cluster.hierarchy import fcluster, linkage
        from scipy.spatial.distance import pdist
        Z = linkage(pdist(np.asarray([e.descriptor for e in entries], "float64"),
                          metric="cosine"), method="average")
        labels = fcluster(Z, t=CLUSTER_COS, criterion="distance").tolist()
    groups: dict[int, list[CastEntry]] = {}
    for e, lab in zip(entries, labels):
        groups.setdefault(int(lab), []).append(e)
    picked: list[CastEntry] = []
    for members in groups.values():
        cent = _centroid([m.descriptor for m in members])
        rep = _largest(members)
        picked.append(replace(rep, descriptor=cent,
                              presence=float(sum(m.presence for m in members))))
    picked.sort(key=lambda e: e.presence, reverse=True)
    if len(picked) > max_cast:
        print(f"cast surfacing: {len(picked)} identities clustered, keeping the top "
              f"{max_cast} by presence (dropped {len(picked) - max_cast})", file=sys.stderr)
        picked = picked[:max_cast]
    return picked


def save_cast_candidates(entries: list[CastEntry], out_dir: str, max_cast: int = MAX_CAST) -> list[dict]:
    """Surface up to max_cast distinct identities across ALL footage (clustered and
    ranked by presence — design §4.1), persist their crop PNGs under
    out_dir/cast_crops/candidate_{i}.png, and write cast_candidates.json — the
    footage-intake SKILL shows these to the human to name (§4/§5). A cached entry
    carries its crop as an on-disk PNG (copied); a fresh one carries the live array
    (written). Empty footage → empty manifest, still written."""
    picked = surface_crops(entries, max_cast)
    crop_dir = Path(out_dir) / "cast_crops"
    if picked:
        crop_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    for i, e in enumerate(picked):
        dest = str(crop_dir / f"candidate_{i}.png")
        if e.crop is not None:
            shutil.copy(e.crop, dest)
        elif e.crop_rgb is not None:
            Image.fromarray(e.crop_rgb.astype("uint8")).save(dest)
        else:
            # The refusal _crop_area's own comment promises: a crop-less entry is
            # caught HERE, at the point it would otherwise have to write one, not
            # left to reach Image.fromarray(None.astype(...)) as a bare AttributeError.
            raise ValueError(
                f"save_cast_candidates: entry source={e.source!r} tid={e.tid} carries "
                f"neither `crop` nor `crop_rgb` — a candidate with no crop cannot be "
                f"shown to a human to name")
        # Read back from the file the human will actually open, not from the entry:
        # crop_px is what makes "too small to name" a reported state instead of an
        # invisible one (design §5/§7.3). Nothing here creates pixels — if a person
        # was only ever 13px tall, the largest member is still 13px.
        with Image.open(dest) as im:
            crop_w, crop_h = im.size
        manifest.append({"id": i, "source": e.source, "conf": round(float(e.conf), 3),
                         "presence": round(float(e.presence), 2),
                         "crop": dest, "crop_px": [crop_w, crop_h],
                         "descriptor": e.descriptor})
    (Path(out_dir) / "cast_candidates.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def write_cast(named: list[tuple[str, str, list[float], list[str]]], out_dir: str) -> footage.Cast:
    """named: [(name, notes, descriptor, ref_crops)] — descriptors already computed by
    surface_crops and persisted in cast_candidates.json; the SKILL maps names onto them.
    Writes cast.json (§4/§5)."""
    members = [footage.CastMember(name=n, descriptor=list(desc), notes=notes, ref_crops=list(refs))
               for (n, notes, desc, refs) in named]
    cast = footage.Cast(members=members)
    (Path(out_dir) / "cast.json").write_text(json.dumps(cast.to_dict(), indent=2))
    return cast


def scene_bounds(src: str) -> list[float]:
    """PySceneDetect ContentDetector → scene boundary timestamps (seconds). A
    continuous take returns [] (handled by carving)."""
    from scenedetect import detect, ContentDetector   # lazy import: heavy optional dep (scenedetect/opencv)
    scenes = detect(src, ContentDetector())
    return [s[0].get_seconds() for s in scenes[1:]]      # boundaries = each scene's start bar the first


def _build_window(span: tuple[float, float], timeline: list, shake: float, res: tuple[int, int]) -> footage.FootageWindow:
    """Measurements only: `score` and `description` are pool-relative and belong to
    Phase 2 (design 2026-08-06-intake-motion-scoring §4.5), so they keep their
    defaults here."""
    a, d = span
    b = a + d
    samples = [row for row in timeline if a <= row[0] < b]
    people = max((row[1] for row in samples), default=0)
    present = (sum(1 for row in samples if row[1] > 0) / len(samples)) if samples else 0.0
    boxes = [row[2] for row in samples if row[2] is not None]
    primary = max(boxes, key=lambda bb: bb[2] * bb[3]) if boxes else None
    motion = _motion(samples, res)
    w, h = res
    sw = (primary[2] / w) if primary is not None and w else 0.0
    sh = (primary[3] / h) if primary is not None and h else 0.0
    shot = footage.shot_type(sw, sh)
    track_ids = sorted({tid for row in samples for tid in row[3]})
    return footage.FootageWindow(start=round(a, 3), dur=round(d, 3), shot_type=shot,
                                 people=people,
                                 # 4dp, matching shake: the 3dp store dated from the deleted MOTION_GAIN
                                 # era when motion spanned [0, 1]; widening it again later costs another
                                 # CACHE_VERSION bump + full re-scan, since motion is Phase-1 output.
                                 motion=round(motion, 4), shake=round(shake, 4),
                                 track_ids=track_ids, subject_w=round(sw, 4),
                                 subject_h=round(sh, 4), present=round(present, 3))


def _motion(samples: list, res: tuple[int, int]) -> float:
    """Mean per-sample identity-consistent displacement, as a fraction of the
    ANALYSIS width (design 2026-08-06-intake-motion-scoring §3.3). Fewer than two
    samples → 0.0.

    No gain: the reported number is the measurement. The deleted MOTION_GAIN
    existed only to stretch this fraction onto [0, 1] so a fixed triangular
    preference could be applied to it, and scoring is a rank now (§3.4) — a rank
    has no scale to choose and no ceiling to saturate against. Expect values ~10x
    smaller than before the change."""
    if len(samples) < 2:
        return 0.0
    w = res[0] or 1
    disps = [carve.track_displacements(samples[i - 1][4], samples[i][4])
             for i in range(1, len(samples))]
    return float(min(1.0, (sum(disps) / len(disps)) / w))


def _process_clip(path: str, sample_fps: float = SAMPLE_FPS, embed_cast: bool = True,
                  band: tuple[float, float] = carve.DEFAULT_BAND) -> ClipResult:
    """One clip's CV (Phase 1, design §2): probe → build a decode-once analysis
    proxy → scene → YOLO seg → vidstab → carve → score, all on the PROXY, plus the
    two facts Phase 2 needs pre-computed so it stays pure — each window's midpoint
    phash (hex, cache-serializable) and each track's 512-d re-ID embedding. Cast crop
    PIXELS come from the ORIGINAL (assembly.frames_rgb + crop_bbox), never the proxy:
    analysis is downscaled, delivery-space crops stay full-res (design 2026-08-01
    §5). Raises on a bad clip; the driver quarantines it. Calls its CV collaborators
    by module name so tests that monkeypatch them still intercept.

    embed_cast=False (reID not installed, design 2026-08-04 §6) skips ONLY the cast
    embedding — windows, scoring and phashes still compute, cast comes back empty —
    so an absent optional dep degrades the cast surface, never the whole scan."""
    info = assembly.probe_stream(path)
    dur = assembly.probe_duration(path)
    res = (info.w, info.h)                                       # ORIGINAL — stored on FootageClip
    with tempfile.TemporaryDirectory() as d:
        proxy = str(Path(d) / "proxy.mp4")
        made = assembly.make_proxy(path, proxy, PROXY_LONG_SIDE)
        src = proxy if made else path                           # analyse the proxy when one was written
        pres = _proxy_dims(res, PROXY_LONG_SIDE) if made else res   # the space the analysis pixels live in
        cuts = scene_bounds(src)
        timeline, best, presence = _people_timeline(src, info.fps, pres, sample_fps)
        vidstab.require()
        mags = vidstab.detect(src, str(Path(d) / "t.trf"), dur)
        spans = carve_windows(cuts, timeline, mags, info.fps, dur, band=band)
        shakes = _windowed_shake(mags, spans, info.fps, pres[0])    # divide by the PROXY width
        windows = [_build_window(sp, timeline, sh, pres) for sp, sh in zip(spans, shakes)]
        mids = [w.start + w.dur / 2 for w in windows]
        phashes = [str(imagehash.phash(Image.fromarray(f)))
                   for f in assembly.frames_rgb(src, mids, info.fps)]
        cast = (_cast_from_original(path, best, res, pres, info.fps, presence)  # crops from the ORIGINAL
                if embed_cast else [])                                          # reID absent → no cast embed (§6)
    med = statistics.median([w.shake for w in windows]) if windows else 0.0
    name = Path(path).name
    clip = footage.FootageClip(source=name, dur=dur, res=res, fps=info.fps,
                               shaky=med > SHAKY_CLIP, scene_cuts=cuts, windows=windows)
    return ClipResult(clip=clip, phashes=phashes, cast=cast)


def _proxy_dims(res: tuple[int, int], long_side: int) -> tuple[int, int]:
    """The proxy's (w, h) for a source of `res`: long side == long_side, aspect
    kept, even dims (make_proxy's yuv420p needs them). Mirrors make_proxy's scale
    filter so measurement helpers divide by the SAME space the analysis ran in and
    the cast-crop scale (res/pres) is exact (design 2026-08-01 §5)."""
    w, h = res
    if max(w, h) <= long_side:
        return res
    if w >= h:
        return long_side, round(h * long_side / w / 2) * 2
    return round(w * long_side / h / 2) * 2, long_side


def _cast_from_original(path: str, best: dict, res: tuple[int, int],
                        pres: tuple[int, int], fps: float,
                        presence: dict | None = None) -> list[CastEntry]:
    """Re-crop each track's best moment from the ORIGINAL-res frame (unmasked —
    design 2026-08-04 §4.1/§10; the proxy box scales up by res/pres) and embed the
    batch via reid.embed (512-d OSNet). All best-frames are grabbed via
    assembly.frames_rgb (design 2026-08-02) — one decode per chunk of ≤60 frames
    (one decode for the common case) — rather than one output-seek per track. A box
    that yields an empty crop is dropped. Each entry carries its track's presence
    (on-screen seconds), the surfacing rank."""
    presence = presence or {}
    scale = res[0] / pres[0]                                     # proxy→original
    items = list(best.items())
    frames = assembly.frames_rgb(path, [t for _, (_, t, _) in items], fps)
    keep, crops = [], []
    for (tid, (conf, t, box)), frame in zip(items, frames):
        crop = crop_bbox(frame, box, scale=scale)
        if crop is not None:
            keep.append((tid, conf, crop))
            crops.append(crop)
    embs = reid.embed(crops)
    return [CastEntry(source=Path(path).name, tid=tid, conf=conf,
                      descriptor=emb, presence=float(presence.get(tid, 0.0)), crop_rgb=crop)
            for (tid, conf, crop), emb in zip(keep, embs)]


def intake(footage_root: str, out_dir: str, sample_fps: float = SAMPLE_FPS, *,
           jobs: int = DEFAULT_JOBS, fresh: bool = False,
           band: tuple[float, float] = carve.DEFAULT_BAND) -> footage.Footage:
    """Scan footage_root into scored FootageWindows + a cast registry, writing
    FOOTAGE.json/.md (+ cast_candidates.json) under out_dir. `band` sets the
    (win_min, win_max) a NEW clip is carved with (carve.units_for_span, design
    2026-09-03 §3).

    `band` is part of intake_cache's key, so the returned Footage.band is a
    guarantee, not merely a request: a clip already cached under a DIFFERENT
    band is a cache MISS and re-carves under this call's band, rather than
    silently keeping the boundaries it was scanned with. fresh=True (CLI:
    --fresh) still forces a full re-scan for other reasons, but is no longer
    needed to pick up a band change.
    """
    # Above ensure_model, so the refusal costs no YOLO weights fetch: a run dir equal
    # to the footage root puts this scan's own outputs into the listing the NEXT scan
    # reads (§0). The mkdir below it is NOT the reason — with out_dir equal to the
    # footage root that directory already exists and exist_ok=True does nothing; the
    # mutation battery is what corrected this comment's first version.
    runlayout.refuse_output_in_footage(footage_root, out_dir, "intake's out_dir")
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 1:
        raise ValueError(f"intake: jobs must be an integer >= 1, got {jobs!r} — "
                         f"default {DEFAULT_JOBS} is a reasonable knee; lower it on a "
                         f"memory-constrained box, raise it only with a GPU")
    if not (isinstance(band, (tuple, list)) and len(band) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in band)
            and 0 < band[0] <= band[1]):
        raise ValueError(f"intake: band must be (win_min, win_max) seconds with "
                         f"0 < win_min <= win_max, got {band!r}")
    band = (float(band[0]), float(band[1]))
    root = Path(footage_root)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = sorted(p for p in root.iterdir() if p.suffix.lower() in _VIDEO_EXTS)
    ensure_model(MODEL)                                # weights-race landmine (§4), before the pool
    # reID is ADVISORY (design 2026-08-04 §6): the producer WARNS and continues. When
    # torchreid is installed, warm its OSNet weights once before the pool (the same
    # concurrent-writer landmine ensure_model closes for YOLO); when it is not, the
    # scan still produces windows/scoring/phashes — only the cast embed is skipped
    # (embed_cast=False → cast_candidates.json empty). reid_model rides into the cache
    # key so a scan run WITHOUT reID never masquerades as one run WITH it.
    reid_ok = reid.available()
    reid_model = reid.MODEL if reid_ok else ""
    if reid_ok:
        reid.ensure_model()
    else:
        print("WARNING: torchreid not installed — cast surfacing skipped (windows & scoring "
              "still produced; cast_candidates.json will be empty). Install it with "
              "`bash setup.sh`, then re-run intake with --fresh to build the cast.",
              file=sys.stderr)
    results: dict[Path, ClipResult] = {}
    misses: list[Path] = []
    for p in paths:
        hit = None if fresh else intake_cache.load(str(out), str(p), sample_fps, MODEL,
                                                   PROXY_LONG_SIDE, reid_model=reid_model,
                                                   band=band)
        if hit is not None:
            results[p] = hit
        else:
            misses.append(p)
    print(f"intake: {len(results)} cached, {len(misses)} to scan", file=sys.stderr)
    failed: list[dict[str, str]] = []
    # Store each clip AS its worker finishes (as_completed), not after the whole pool
    # drains: store() returns the crop_rgb-free cached form AND futs.pop drops the
    # completed future — whose cached .result() would otherwise pin the worker's
    # crop_rgb-bearing ClipResult for the rest of the scan — so live crop arrays never
    # pile past ~jobs clips (a full-batch pile swaps a big 4K folder). The pop is
    # load-bearing, not tidiness: without it store()'s freeing is undone by fut._result.
    # Progress is visible and a crash resumes per clip. results fills in completion
    # order; `ok` below re-sorts by `paths`, so output stays byte-identical to any
    # jobs/cache mix (the design invariant). as_completed iterates its own copy, so
    # mutating futs here is safe.
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(_process_clip, str(p), sample_fps, embed_cast=reid_ok,
                          band=band): p for p in misses}
        for fut in as_completed(futs):
            p = futs.pop(fut)                          # free the future so its result can GC
            try:
                results[p] = intake_cache.store(str(out), str(p), sample_fps,
                                                fut.result(), MODEL, PROXY_LONG_SIDE,
                                                reid_model=reid_model, band=band)
                print(f"intake: ✓ {p.name}", file=sys.stderr)
            except Exception as e:                     # quarantine (§5): name it, keep going
                failed.append({"source": p.name, "error": str(e)})
                print(f"intake: ⚠ {p.name} failed — {e}", file=sys.stderr)
    ok = [results[p] for p in paths if p in results]
    clips = [r.clip for r in ok]
    # Score BEFORE constructing Footage so `scoring` passes __post_init__ rather than
    # being assigned onto a built object (design 2026-09-10 §4.2).
    scoring = score_pool(clips)       # Phase 2: pool-relative score + description (design §4.5)
    result = footage.Footage(clips=clips, band=band, scoring=scoring)
    phash_by = {(r.clip.source, w.start, w.dur): imagehash.hex_to_hash(h)
                for r in ok for w, h in zip(r.clip.windows, r.phashes)}
    cull(result.clips, phash_of=lambda c, w: phash_by[(c.source, w.start, w.dur)])
    (out / "FOOTAGE.json").write_text(json.dumps(result.to_dict(), indent=2))
    md = result.to_markdown()
    if failed:
        md += f"\n## Failed clips ({len(failed)})\n\n"
        md += "\n".join(f"- {f['source']}: {f['error']}" for f in failed) + "\n"
    (out / "FOOTAGE.md").write_text(md)
    save_cast_candidates([e for r in ok for e in r.cast], str(out))
    scanned = len(misses) - len(failed)                # successful misses; the rest of results are cache hits
    (out / "intake_report.json").write_text(json.dumps(
        {"scanned": scanned, "cached": len(results) - scanned, "failed": failed}, indent=2))
    if failed:
        print(f"intake: ⚠ {len(failed)} clip(s) failed — see {out / 'intake_report.json'}",
              file=sys.stderr)
    return result


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="footage-intake (5.2): scan clips → FOOTAGE.json/.md")
    ap.add_argument("footage_root")
    ap.add_argument("out_dir")
    ap.add_argument("--sample-fps", type=float, default=SAMPLE_FPS)
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                    help="parallel clip workers (default %(default)s)")
    ap.add_argument("--fresh", action="store_true",
                    help="ignore the .intake_cache and rescan every clip")
    ap.add_argument("--win-min", type=float, default=carve.DEFAULT_BAND[0],
                    help="shortest carved window, seconds (default %(default)s). "
                         "Part of the cache key: a changed value is a cache "
                         "MISS, so every clip re-carves under the new band — "
                         "never a silent stale return")
    ap.add_argument("--win-max", type=float, default=carve.DEFAULT_BAND[1],
                    help="longest carved window, seconds (default %(default)s). "
                         "edit_plan can JOIN adjacent windows, so this is not a "
                         "ceiling on episode length. Same cache-key behaviour "
                         "as --win-min: a changed value re-carves rather than "
                         "serving a stale hit")
    return ap


def main(argv: list[str] | None = None) -> None:
    a = build_parser().parse_args(argv)
    f = intake(a.footage_root, a.out_dir, a.sample_fps, jobs=a.jobs, fresh=a.fresh,
               band=(a.win_min, a.win_max))
    print(f"{len(f.clips)} clips, {sum(len(c.windows) for c in f.clips)} windows → {a.out_dir}")


if __name__ == "__main__":
    main()
