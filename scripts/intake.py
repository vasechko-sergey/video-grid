"""footage-intake (stage 5.2): scan raw clips → scored candidate windows + cast
registry (design docs/specs/2026-07-12-footage-intake-design.md).

Mechanical CV: probe + PySceneDetect + one YOLO11-seg pass + vidstabdetect +
sub-scene carve + score + phash cull. The interactive hero-naming lives in the
footage-intake SKILL — Python cannot ask a human — this module only surfaces
crops and builds descriptors.
"""
import argparse, json, statistics, tempfile
import shutil
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import imagehash
from PIL import Image

from scripts import check_reel                    # reuse _phash_bits / _hamming for cull
from scripts.lib import assembly, footage, intake_cache, vidstab
from scripts.lib.appearance import build_descriptor, crop_and_mask, descriptor_dist
from scripts.lib.intake_cache import CastEntry, ClipResult
from scripts.track import MODEL, ensure_model       # reuse the tracker's model choice

SAMPLE_FPS = 3.0
WIN_MIN, WIN_MAX, WIN_TARGET = 1.2, 4.0, 2.5      # seconds — the episode length band
W_PRESENT, W_MOTION, W_STABLE, W_DUR = 0.40, 0.25, 0.25, 0.10
MOTION_GAIN = 10.0                                # scales mean per-sample centre displacement to [0,1]
MOTION_PEAK = 0.35                                # motion value scored highest (triangular)
DEDUP_DIST = 8                                    # phash Hamming below which two windows are duplicates
BEST_FLOOR = 0.50
SHAKY_CLIP = 0.02                                 # shake (fraction of frame width) above which a clip is shaky — tune on real footage.
                                                  # Its INPUT changed on 2026-07-20: the detect pass moved from the binary's default
                                                  # shakiness=5 to vidstab.DETECT_ARGS' 8, so recorded shake values shifted. The
                                                  # threshold is deliberately NOT re-tuned to compensate — no real footage has been
                                                  # through this pipeline, so any new value would be invented (design §5).
CLOSE_AREA, MEDIUM_AREA = 0.30, 0.08
CAST_DEDUP = 0.30                                 # L1 descriptor distance below which two tracks are the same identity
_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi"}
DEFAULT_JOBS = 3          # cap-3's measured knee (design 2026-07-18 §2); see design §7 —
                          # not re-measured for full-clip passes; --jobs tunes on tight memory


def shot_type(bbox: tuple[float, float, float, float] | None, res: tuple[int, int]) -> str:
    """close/medium/wide from the primary person's bbox area fraction. None → wide (scenery)."""
    if bbox is None:
        return "wide"
    _, _, bw, bh = bbox
    w, h = res
    area = (bw * bh) / float(w * h) if w and h else 0.0
    if area > CLOSE_AREA:
        return "close"
    if area >= MEDIUM_AREA:
        return "medium"
    return "wide"


def carve_windows(scene_cuts: list[float],
                  timeline: list[tuple[float, int, tuple[float, float, float, float] | None]],
                  dur: float) -> list[tuple[float, float]]:
    """scene_cuts ∪ presence-transitions, length-capped into [WIN_MIN, WIN_MAX].
    timeline: sorted [(t, people, primary_bbox)]. Scenes alone do NOT split a long
    single take (MVI_3739 = 1 ride → 3 windows), so carve within a scene by
    people-presence + length. A single shot shorter than WIN_MIN yields ONE
    window (the whole clip); a clip shredded into MANY too-short spans yields
    NO windows (empty is valid — the clip is still logged)."""
    bounds = {0.0, float(dur)}
    for t in scene_cuts:
        if 0.0 < t < dur:
            bounds.add(float(t))
    prev = None
    for t, n, _ in timeline:
        present = n > 0
        if prev is not None and present != prev and 0.0 < t < dur:
            bounds.add(float(t))
        prev = present
    edges = sorted(bounds)
    raw = list(zip(edges, edges[1:]))
    spans: list[tuple[float, float]] = []
    for a, b in raw:
        spans.extend(_split_span(a, b))
    if not spans and len(raw) == 1:          # a single short shot (dur < WIN_MIN) — keep the whole clip
        a, b = raw[0]
        spans = [(a, b - a)]
    return spans                             # many all-too-short spans → [] (clip logged, no usable moments)


def _split_span(a: float, b: float) -> list[tuple[float, float]]:
    length = b - a
    if length < WIN_MIN:
        return []
    if length <= WIN_MAX:
        return [(a, length)]
    n = max(1, round(length / WIN_TARGET))
    chunk = length / n
    return [(a + i * chunk, chunk) for i in range(n)]


def _motion_fit(m: float) -> float:
    """Triangular: 0 at static, 1 at MOTION_PEAK, decaying to 0 at chaotic (1.0)."""
    if m <= MOTION_PEAK:
        return m / MOTION_PEAK if MOTION_PEAK else 0.0
    return max(0.0, (1.0 - m) / (1.0 - MOTION_PEAK))


def _dur_fit(d: float) -> float:
    """1 at WIN_TARGET, falling toward WIN_MIN / WIN_MAX, 0 outside the band."""
    if d < WIN_MIN or d > WIN_MAX:
        return 0.0
    if d <= WIN_TARGET:
        return (d - WIN_MIN) / (WIN_TARGET - WIN_MIN)
    return (WIN_MAX - d) / (WIN_MAX - WIN_TARGET)


def score_window(present: float, motion: float, shake: float, dur: float) -> float:
    """Blend the four factors → [0, 1]. Pure math; each factor is tested in isolation."""
    stability = 1.0 - min(1.0, shake / SHAKY_CLIP)
    s = (W_PRESENT * present + W_MOTION * _motion_fit(motion)
         + W_STABLE * stability + W_DUR * _dur_fit(dur))
    return float(min(1.0, max(0.0, s)))


def _describe(people: int, shot: str, motion: float) -> str:
    who = "no people" if people == 0 else ("1 person" if people == 1 else f"{people} people")
    dyn = "dynamic" if motion >= MOTION_PEAK else "calm"
    return f"{who}, {shot}, {dyn}"


def _windowed_shake(mags: list[float], windows: list[tuple[float, float]], fps: float, w: int) -> list[float]:
    out = []
    for a, d in windows:
        f0, f1 = int(a * fps), int((a + d) * fps)
        out.append(vidstab.mean_shake(mags[f0:f1], w))   # fraction of frame width
    return out


def shake_by_window(clip: str, windows: list[tuple[float, float]], fps: float,
                    res: tuple[int, int], dur: float) -> list[float]:
    """vidstabdetect once per clip → per-frame magnitudes → averaged per window,
    normalized by frame width. No per-window cutting → no -ss seek landmine.

    `dur` (the clip's own length, already probed by the caller) scales the timeout
    `vidstab.detect` derives: this pass runs over the WHOLE raw clip, unlike
    everything else in this repo, so a flat default is not generous enough for a
    long take. The detect recipe, the timeout derivation and the .trf parsing all
    live in scripts/lib/vidstab.py, so every consumer of that module reports the
    same measurement (design 2026-07-20 §5).
    """
    vidstab.require()
    with tempfile.TemporaryDirectory() as d:
        mags = vidstab.detect(clip, str(Path(d) / "t.trf"), dur)
    return _windowed_shake(mags, windows, fps, res[0])


def _iter_seg(src: str, model_path: str = MODEL) -> Iterator[tuple[int, object]]:
    """Mirror track.py's YOLO+ByteTrack config but keep masks (track omits them
    for speed). Yields (frame_index, ultralytics_result)."""
    from ultralytics import YOLO           # lazy import: heavy optional dep (ultralytics/torch)
    model = YOLO(model_path)
    for i, res in enumerate(model.track(src, stream=True, persist=True, classes=[0],
                                        tracker="bytetrack.yaml", imgsz=960, verbose=False)):
        yield i, res


def _people_timeline(src: str, fps: float, res: tuple[int, int],
                     sample_fps: float = SAMPLE_FPS) -> tuple[list, dict]:
    """One seg pass → (timeline, crops_by_track).
    timeline: [(t, people, primary_bbox)] sampled at ~SAMPLE_FPS (primary = largest bbox).
    crops_by_track: {tid: (conf, crop_rgb, mask)} best crop per track id, for the cast pass."""
    step = max(1, round(fps / sample_fps))
    timeline, crops = [], {}
    for i, r in _iter_seg(src):
        boxes = list(r.boxes) if getattr(r, "boxes", None) is not None else []
        for j, b in enumerate(boxes):
            tid = int(b.id[0]) if getattr(b, "id", None) is not None else None
            conf = float(b.conf[0]) if getattr(b, "conf", None) is not None else 1.0
            if tid is not None and conf > crops.get(tid, (-1.0,))[0]:
                crop_rgb, mask = crop_and_mask(r, j, b)
                if crop_rgb is not None:
                    crops[tid] = (conf, crop_rgb, mask)
        if i % step:
            continue
        bbs = [tuple(float(v) for v in b.xywh[0]) for b in boxes]
        primary = max(bbs, key=lambda bb: bb[2] * bb[3]) if bbs else None
        timeline.append((i / fps, len(bbs), primary))
    return timeline, crops


def _phash_at(clip: str, t: float) -> imagehash.ImageHash:
    return check_reel._phash_bits(clip, t)             # reuse the reel-variety phash


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


def surface_crops(entries: list[CastEntry], top_n: int = 8) -> list[CastEntry]:
    """Cluster CastEntry list by descriptor similarity → top_n distinct identities
    (highest confidence first). Descriptors are precomputed by the worker (§6), so
    this no longer builds them. Returns the picked CastEntry subset."""
    items = sorted(entries, key=lambda e: e.conf, reverse=True)
    picked: list = []
    for e in items:
        if all(descriptor_dist(e.descriptor, p.descriptor) > CAST_DEDUP for p in picked):
            picked.append(e)
        if len(picked) >= top_n:
            break
    return picked


def save_cast_candidates(entries: list[CastEntry], out_dir: str, top_n: int = 8) -> list[dict]:
    """Surface the top-N distinct identities across ALL footage, persist their crop
    PNGs under out_dir/cast_crops/candidate_{i}.png, and write cast_candidates.json
    — the footage-intake SKILL shows these to the human to name (§4/§5). A cached
    entry carries its crop as an on-disk PNG (copied); a fresh one carries the live
    array (written). Empty footage → empty manifest, still written."""
    picked = surface_crops(entries, top_n)
    crop_dir = Path(out_dir) / "cast_crops"
    if picked:
        crop_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    for i, e in enumerate(picked):
        dest = str(crop_dir / f"candidate_{i}.png")
        if e.crop is not None:
            shutil.copy(e.crop, dest)
        else:
            Image.fromarray(e.crop_rgb.astype("uint8")).save(dest)
        manifest.append({"id": i, "source": e.source, "conf": round(float(e.conf), 3),
                         "crop": dest, "descriptor": e.descriptor})
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
    a, d = span
    b = a + d
    samples = [(t, n, bb) for (t, n, bb) in timeline if a <= t < b]
    people = max((n for _, n, _ in samples), default=0)
    present = (sum(1 for _, n, _ in samples if n > 0) / len(samples)) if samples else 0.0
    boxes = [bb for _, _, bb in samples if bb is not None]
    primary = max(boxes, key=lambda bb: bb[2] * bb[3]) if boxes else None
    motion = _motion(samples, res)
    shot = shot_type(primary, res)
    score = score_window(present, motion, shake, d)
    return footage.FootageWindow(start=round(a, 3), dur=round(d, 3), shot_type=shot,
                                 people=people, motion=round(motion, 3), shake=round(shake, 4),
                                 description=_describe(people, shot, motion), score=round(score, 3))


def _motion(samples: list, res: tuple[int, int]) -> float:
    centers = [(t, bb[0]) for (t, n, bb) in samples if bb is not None]
    if len(centers) < 2:
        return 0.0
    w = res[0] or 1
    disps = [abs(centers[i][1] - centers[i - 1][1]) / w for i in range(1, len(centers))]
    return float(min(1.0, (sum(disps) / len(disps)) * MOTION_GAIN))


def _process_clip(path: str, sample_fps: float = SAMPLE_FPS) -> ClipResult:
    """One clip's CV (Phase 1, design §2): probe → scene → YOLO seg → vidstab →
    carve → score, plus the two facts Phase 2 needs pre-computed so it stays pure —
    each window's midpoint phash (hex, cache-serializable) and each track's
    descriptor (built here, where the mask is in hand). Raises on a bad clip; the
    driver quarantines it. Calls its CV collaborators by module name so tests that
    monkeypatch them still intercept."""
    info = assembly.probe_stream(path)
    dur = assembly.probe_duration(path)
    res = (info.w, info.h)
    cuts = scene_bounds(path)
    timeline, crops = _people_timeline(path, info.fps, res, sample_fps)
    spans = carve_windows(cuts, timeline, dur)
    shakes = shake_by_window(path, spans, info.fps, res, dur)
    windows = [_build_window(sp, timeline, sh, res) for sp, sh in zip(spans, shakes)]
    med = statistics.median([w.shake for w in windows]) if windows else 0.0
    name = Path(path).name
    clip = footage.FootageClip(source=name, dur=dur, res=res, fps=info.fps,
                               shaky=med > SHAKY_CLIP, scene_cuts=cuts, windows=windows)
    phashes = [str(_phash_at(path, w.start + w.dur / 2)) for w in windows]
    cast = [CastEntry(source=name, tid=tid, conf=conf,
                      descriptor=build_descriptor(crop_rgb, mask), crop_rgb=crop_rgb)
            for tid, (conf, crop_rgb, mask) in crops.items() if crop_rgb is not None]
    return ClipResult(clip=clip, phashes=phashes, cast=cast)


def intake(footage_root: str, out_dir: str, sample_fps: float = SAMPLE_FPS, *,
           jobs: int = DEFAULT_JOBS, fresh: bool = False) -> footage.Footage:
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 1:
        raise ValueError(f"intake: jobs must be an integer >= 1, got {jobs!r} — "
                         f"default {DEFAULT_JOBS} is a reasonable knee; lower it on a "
                         f"memory-constrained box, raise it only with a GPU")
    root = Path(footage_root)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = sorted(p for p in root.iterdir() if p.suffix.lower() in _VIDEO_EXTS)
    ensure_model(MODEL)                                # weights-race landmine (§4), before the pool
    results: dict[Path, ClipResult] = {}
    misses: list[Path] = []
    for p in paths:
        hit = None if fresh else intake_cache.load(str(out), str(p), sample_fps, MODEL)
        if hit is not None:
            results[p] = hit
        else:
            misses.append(p)
    print(f"intake: {len(results)} cached, {len(misses)} to scan", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {p: ex.submit(_process_clip, str(p), sample_fps) for p in misses}
    for p in misses:
        results[p] = intake_cache.store(str(out), str(p), sample_fps, futs[p].result(), MODEL)
    ok = [results[p] for p in paths if p in results]
    result = footage.Footage(clips=[r.clip for r in ok])
    phash_by = {(r.clip.source, w.start, w.dur): imagehash.hex_to_hash(h)
                for r in ok for w, h in zip(r.clip.windows, r.phashes)}
    cull(result.clips, phash_of=lambda c, w: phash_by[(c.source, w.start, w.dur)])
    (out / "FOOTAGE.json").write_text(json.dumps(result.to_dict(), indent=2))
    (out / "FOOTAGE.md").write_text(result.to_markdown())
    save_cast_candidates([e for r in ok for e in r.cast], str(out))
    return result


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="footage-intake (5.2): scan clips → FOOTAGE.json/.md")
    ap.add_argument("footage_root")
    ap.add_argument("out_dir")
    ap.add_argument("--sample-fps", type=float, default=SAMPLE_FPS)
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                    help="parallel clip workers (default %(default)s)")
    ap.add_argument("--fresh", action="store_true",
                    help="ignore the .intake_cache and rescan every clip")
    a = ap.parse_args(argv)
    f = intake(a.footage_root, a.out_dir, a.sample_fps, jobs=a.jobs, fresh=a.fresh)
    print(f"{len(f.clips)} clips, {sum(len(c.windows) for c in f.clips)} windows → {a.out_dir}")


if __name__ == "__main__":
    main()
