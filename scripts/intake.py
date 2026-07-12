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
