"""footage-intake (stage 5.2): scan raw clips → scored candidate windows + cast
registry (design docs/specs/2026-07-12-footage-intake-design.md).

Mechanical CV: probe + PySceneDetect + one YOLO11-seg pass + vidstabdetect +
sub-scene carve + score + phash cull. The interactive hero-naming lives in the
footage-intake SKILL — Python cannot ask a human — this module only surfaces
crops and builds descriptors.
"""
import argparse, json, re, statistics, tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from scripts import check_reel                    # reuse _phash_bits / _hamming for cull
from scripts.lib import assembly, footage, proc
from scripts.track import MODEL                    # reuse the tracker's model choice

SAMPLE_FPS = 3.0
WIN_MIN, WIN_MAX, WIN_TARGET = 1.2, 4.0, 2.5      # seconds — the episode length band
W_PRESENT, W_MOTION, W_STABLE, W_DUR = 0.40, 0.25, 0.25, 0.10
MOTION_GAIN = 10.0                                # scales mean per-sample centre displacement to [0,1]
MOTION_PEAK = 0.35                                # motion value scored highest (triangular)
DEDUP_DIST = 8                                    # phash Hamming below which two windows are duplicates
BEST_FLOOR = 0.50
SHAKY_CLIP = 0.02                                 # shake (fraction of frame width) above which a clip is shaky — tune on real footage
CLOSE_AREA, MEDIUM_AREA = 0.30, 0.08
CAST_DEDUP = 0.30                                 # L1 descriptor distance below which two tracks are the same identity
_HIST_BINS = 8
_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi"}


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


def _require_vidstab() -> None:
    """Intake is the repo's first runtime vidstab consumer — fail loud with the remedy."""
    r = proc.run(["ffmpeg", "-hide_banner", "-filters"])
    if b"vidstabdetect" not in r.stdout:
        raise ValueError("footage-intake needs a vidstab-enabled ffmpeg (vidstabdetect filter missing) — "
                         "run `bash setup.sh --with-vidstab`")


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


_LM_RE = re.compile(r"\(LM\s+(-?\d+)\s+(-?\d+)")


def _parse_trf(text: str) -> list[float]:
    """Per-frame shake magnitude (median localmotion vector length, px) from a
    libvidstab VID.STAB transforms file. Fail loud on an unrecognized header —
    never a silent shake=0 (the format is libvidstab-version dependent)."""
    lines = text.splitlines()
    if not lines:
        raise ValueError("vidstabdetect produced an empty .trf (no transforms) — the analysis "
                         "failed; check the clip is readable")
    if not lines[0].startswith("VID.STAB"):
        raise ValueError("vidstabdetect .trf has an unrecognized header — libvidstab version mismatch? "
                         "cannot trust the shake estimate (run `bash setup.sh --with-vidstab`)")
    mags: list[float] = []
    for line in lines[1:]:
        if not line.startswith("Frame"):
            continue
        lms = _LM_RE.findall(line)
        if lms:
            vecs = sorted((int(x) ** 2 + int(y) ** 2) ** 0.5 for x, y in lms)
            mags.append(vecs[len(vecs) // 2])          # upper-median localmotion magnitude (vecs[len//2])
        else:
            mags.append(0.0)
    return mags


def _windowed_shake(mags: list[float], windows: list[tuple[float, float]], fps: float, w: int) -> list[float]:
    out = []
    for a, d in windows:
        f0, f1 = int(a * fps), int((a + d) * fps)
        seg = mags[f0:f1] or [0.0]
        out.append((sum(seg) / len(seg)) / (w or 1))   # fraction of frame width
    return out


def shake_by_window(clip: str, windows: list[tuple[float, float]], fps: float, res: tuple[int, int]) -> list[float]:
    """vidstabdetect once per clip → per-frame magnitudes → averaged per window,
    normalized by frame width. No per-window cutting → no -ss seek landmine."""
    _require_vidstab()
    with tempfile.TemporaryDirectory() as d:
        trf = str(Path(d) / "t.trf")
        proc.run(["ffmpeg", "-y", "-i", clip, "-vf", f"vidstabdetect=result={trf}", "-f", "null", "-"])
        mags = _parse_trf(Path(trf).read_text())
    return _windowed_shake(mags, windows, fps, res[0])


def _iter_seg(src: str, model_path: str = MODEL):
    """Mirror track.py's YOLO+ByteTrack config but keep masks (track omits them
    for speed). Yields (frame_index, ultralytics_result)."""
    from ultralytics import YOLO
    model = YOLO(model_path)
    for i, res in enumerate(model.track(src, stream=True, persist=True, classes=[0],
                                        tracker="bytetrack.yaml", imgsz=960, verbose=False)):
        yield i, res


def _people_timeline(src: str, fps: float, res: tuple[int, int]):
    """One seg pass → (timeline, crops_by_track).
    timeline: [(t, people, primary_bbox)] sampled at ~SAMPLE_FPS (primary = largest bbox).
    crops_by_track: {tid: (conf, crop_rgb, mask)} best crop per track id, for the cast pass."""
    step = max(1, round(fps / SAMPLE_FPS))
    timeline, crops = [], {}
    for i, r in _iter_seg(src):
        boxes = list(r.boxes) if getattr(r, "boxes", None) is not None else []
        for j, b in enumerate(boxes):
            tid = int(b.id[0]) if getattr(b, "id", None) is not None else None
            conf = float(b.conf[0]) if getattr(b, "conf", None) is not None else 1.0
            if tid is not None and conf > crops.get(tid, (-1.0,))[0]:
                crop_rgb, mask = _crop_and_mask(r, j, b)
                if crop_rgb is not None:
                    crops[tid] = (conf, crop_rgb, mask)
        if i % step:
            continue
        bbs = [tuple(float(v) for v in b.xywh[0]) for b in boxes]
        primary = max(bbs, key=lambda bb: bb[2] * bb[3]) if bbs else None
        timeline.append((i / fps, len(bbs), primary))
    return timeline, crops


def _crop_and_mask(res, idx: int, box):
    """Extract the box's crop (RGB) + seg mask from an ultralytics result. Returns
    (None, None) when the frame image or masks are unavailable (mocked tests)."""
    img = getattr(res, "orig_img", None)
    if img is None:
        return None, None
    arr = np.asarray(img)[..., ::-1]                       # ultralytics orig_img is BGR → RGB
    x, y, w, h = (float(v) for v in box.xywh[0])
    l, t, r_, b_ = int(x - w / 2), int(y - h / 2), int(x + w / 2), int(y + h / 2)
    l, t = max(0, l), max(0, t)
    crop = arr[t:b_, l:r_]
    mask = None
    masks = getattr(res, "masks", None)
    if masks is not None and getattr(masks, "data", None) is not None:
        m = np.asarray(masks.data[idx])                    # (H, W) in model space
        m = np.asarray(Image.fromarray((m * 255).astype("uint8")).resize((arr.shape[1], arr.shape[0])))
        mask = m[t:b_, l:r_]
    return (crop if crop.size else None), mask


def _phash_at(clip: str, t: float):
    return check_reel._phash_bits(clip, t)             # reuse the reel-variety phash


def cull(clips: list, phash_of) -> None:
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


def build_descriptor(crop_rgb, mask) -> list[float]:
    """L1-normalized color histogram over the segmentation-mask pixels only
    (clothing/gear — background removed; §6.1a). numpy + Pillow, no cv2."""
    px = crop_rgb[mask > 0] if mask is not None else crop_rgb.reshape(-1, 3)
    if px.size == 0:
        px = crop_rgb.reshape(-1, 3)
    hist: list[float] = []
    for c in range(3):
        h, _ = np.histogram(px[:, c], bins=_HIST_BINS, range=(0, 255))
        hist.extend(h.tolist())
    total = float(sum(hist)) or 1.0
    return [v / total for v in hist]


def _descriptor_dist(a: list[float], b: list[float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b))


def surface_crops(crops_by_track: dict, top_n: int = 8) -> list:
    """Cluster retained per-track crops by descriptor similarity → top_n distinct
    identities (highest confidence first). Returns [(tid, conf, crop_rgb, mask, descriptor)]."""
    items = []
    for tid, (conf, crop_rgb, mask) in crops_by_track.items():
        if crop_rgb is None:
            continue
        items.append((tid, conf, crop_rgb, mask, build_descriptor(crop_rgb, mask)))
    items.sort(key=lambda it: it[1], reverse=True)
    picked: list = []
    for it in items:
        if all(_descriptor_dist(it[4], p[4]) > CAST_DEDUP for p in picked):
            picked.append(it)
        if len(picked) >= top_n:
            break
    return picked


def write_cast(named: list, out_dir: str):
    """named: [(name, notes, [(crop_rgb, mask), ...])]. Averages 1–3 reference
    descriptors, saves ref crop PNGs under out_dir/cast_crops/, writes cast.json."""
    crop_dir = Path(out_dir) / "cast_crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    members = []
    for name, notes, refs in named:
        descs, paths = [], []
        for j, (crop_rgb, mask) in enumerate(refs[:3]):
            descs.append(build_descriptor(crop_rgb, mask))
            p = str(crop_dir / f"{name}_{j}.png")
            Image.fromarray(crop_rgb.astype("uint8")).save(p)
            paths.append(p)
        avg = [sum(col) / len(descs) for col in zip(*descs)]
        members.append(footage.CastMember(name=name, descriptor=avg, notes=notes, ref_crops=paths))
    cast = footage.Cast(members=members)
    (Path(out_dir) / "cast.json").write_text(json.dumps(cast.to_dict(), indent=2))
    return cast
