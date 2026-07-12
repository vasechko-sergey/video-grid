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


def shot_type(bbox, res: tuple[int, int]) -> str:
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


def carve_windows(scene_cuts: list[float], timeline: list, dur: float) -> list[tuple[float, float]]:
    """scene_cuts ∪ presence-transitions, length-capped into [WIN_MIN, WIN_MAX].
    timeline: sorted [(t, people, primary_bbox)]. Scenes alone do NOT split a long
    single take (MVI_3739 = 1 ride → 3 windows), so carve within a scene by
    people-presence + length. A clip shorter than WIN_MIN yields ONE window
    (never zero)."""
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
    spans: list[tuple[float, float]] = []
    for a, b in zip(edges, edges[1:]):
        spans.extend(_split_span(a, b))
    if not spans:
        spans = [(0.0, float(dur))]
    return spans


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
    if not lines or not lines[0].startswith("VID.STAB"):
        raise ValueError("vidstabdetect .trf has an unrecognized header — libvidstab version mismatch? "
                         "cannot trust the shake estimate (run `bash setup.sh --with-vidstab`)")
    mags: list[float] = []
    for line in lines[1:]:
        if not line.startswith("Frame"):
            continue
        lms = _LM_RE.findall(line)
        if lms:
            vecs = sorted((int(x) ** 2 + int(y) ** 2) ** 0.5 for x, y in lms)
            mags.append(vecs[len(vecs) // 2])          # median localmotion magnitude
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
