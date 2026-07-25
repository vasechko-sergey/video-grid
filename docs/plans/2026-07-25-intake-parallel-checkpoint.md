# Intake — parallel scan + resumable per-clip checkpoint — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `scripts/intake.py`'s one sequential clip loop into a parallel,
per-clip-checkpointed Phase 1 plus a cheap deterministic Phase 2, so a long scan
resumes from cache and one bad clip is quarantined rather than losing the batch.

**Architecture:** A new `scripts/lib/intake_cache.py` owns the checkpoint format
(atomic per-clip store/load, keyed on file identity + params + a version). The
per-clip CV work becomes a worker `_process_clip` returning an internal
`ClipResult`. The driver loads cache hits in the main thread, runs the misses in a
`ThreadPoolExecutor`, quarantines failures, then assembles the global output
(`cull` + cast) in a fixed `sorted(paths)` order — so `FOOTAGE.json` is
byte-identical at any `jobs` and any cache hit/miss mix.

**Tech Stack:** Python 3.13, stdlib `concurrent.futures`/`threading`, `imagehash`,
Pillow, existing `scripts.track.ensure_model`, `scripts.lib.footage`,
`scripts.lib.appearance`. Tests: pytest (`pythonpath = .`, `integration` marker),
real ffmpeg via `scripts.lib.ffbin`.

**Design spec:** [docs/specs/2026-07-25-intake-parallel-checkpoint-design.md](../specs/2026-07-25-intake-parallel-checkpoint-design.md)

**Conventions:** run everything with `.venv/bin/python -m pytest ...`. Scripts are
modules (`pythonpath = .`). Commit messages end with the trailer
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Do NOT push. Branch off
`main` first: `git checkout -b feat/intake-parallel-checkpoint`.

**Out of scope (design §11):** the window band `_split_span` (#3, its own slice);
caching CV intermediates; measuring intake's own jobs knee; a GPU cap. This plan
does NOT touch `carve_windows`, `_split_span`, `score_window`, or `cull`'s body.

---

## Task 0: `intake_cache` — the checkpoint module

**Files:**
- Create: `scripts/lib/intake_cache.py`
- Test: `tests/lib/test_intake_cache.py`

The module owns two internal shapes and the atomic store/load. `ClipResult` and
`CastEntry` are plain dataclasses (worker→cache→driver internals, not on-disk
contracts a foreign tool reads — design §8), so no `from_dict` gate. The on-disk
`clip.json` embeds `FootageClip.to_dict()`, which already round-trips.

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/test_intake_cache.py`:

```python
import json
import numpy as np
from PIL import Image

import pytest

from scripts.lib import intake_cache
from scripts.lib.intake_cache import CastEntry, ClipResult
from scripts.lib.footage import DESCRIPTOR_LEN, FootageClip, FootageWindow


def _desc(*head):
    return list(head) + [0.0] * (DESCRIPTOR_LEN - len(head))


def _clip(name="a.mp4"):
    w = FootageWindow(start=0.0, dur=2.0, shot_type="medium", people=1,
                      motion=0.4, shake=0.0, score=0.9)
    return FootageClip(source=name, dur=8.0, res=(1920, 1080), fps=30.0,
                       scene_cuts=[4.0], windows=[w])


def _result(name="a.mp4"):
    red = np.zeros((8, 8, 3), "uint8"); red[:, :, 0] = 255
    entry = CastEntry(source=name, tid=1, conf=0.9, descriptor=_desc(0.5, 0.5), crop_rgb=red)
    return ClipResult(clip=_clip(name), phashes=["8f3c2a1b0d4e5f60"], cast=[entry])


def _src(tmp_path, name="a.mp4", data=b"x"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_store_then_load_round_trips(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    stored = intake_cache.store(str(out), str(src), 3.0, _result())
    loaded = intake_cache.load(str(out), str(src), 3.0)
    assert loaded is not None
    assert loaded.clip.to_dict() == _clip().to_dict()
    assert loaded.phashes == ["8f3c2a1b0d4e5f60"]
    assert loaded.cast[0].source == "a.mp4" and loaded.cast[0].tid == 1
    assert loaded.cast[0].descriptor == _desc(0.5, 0.5)
    # cached-form carries the crop as a PNG path, not an array
    assert stored.cast[0].crop == loaded.cast[0].crop and loaded.cast[0].crop_rgb is None
    assert Image.open(loaded.cast[0].crop).size == (8, 8)


def test_load_is_none_when_absent(tmp_path):
    assert intake_cache.load(str(tmp_path / "out"), str(_src(tmp_path)), 3.0) is None


def test_load_is_none_on_changed_mtime(tmp_path):
    import os, time
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result())
    os.utime(src, ns=(0, 0))                       # different mtime_ns
    assert intake_cache.load(str(out), str(src), 3.0) is None


def test_load_is_none_on_changed_sample_fps(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result())
    assert intake_cache.load(str(out), str(src), 4.0) is None


def test_load_is_none_on_changed_model(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result(), model="m1")
    assert intake_cache.load(str(out), str(src), 3.0, model="m2") is None


def test_load_is_none_on_bumped_version(tmp_path, monkeypatch):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result())
    monkeypatch.setattr(intake_cache, "CACHE_VERSION", intake_cache.CACHE_VERSION + 1)
    assert intake_cache.load(str(out), str(src), 3.0) is None


def test_crops_without_clip_json_is_a_miss(tmp_path):
    # the commit marker is clip.json; a crash mid-write leaves crops but no json
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result())
    (out / ".intake_cache" / "a.mp4" / "clip.json").unlink()
    assert intake_cache.load(str(out), str(src), 3.0) is None


def test_corrupt_clip_json_is_a_miss_not_a_crash(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result())
    (out / ".intake_cache" / "a.mp4" / "clip.json").write_text("{ not json")
    assert intake_cache.load(str(out), str(src), 3.0) is None


def test_crop_png_round_trips_red(tmp_path):
    out, src = tmp_path / "out", _src(tmp_path)
    intake_cache.store(str(out), str(src), 3.0, _result())
    loaded = intake_cache.load(str(out), str(src), 3.0)
    px = np.asarray(Image.open(loaded.cast[0].crop))
    assert px[0, 0, 0] == 255 and px[0, 0, 1] == 0     # still red
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_intake_cache.py -q`
Expected: FAIL — `ModuleNotFoundError: scripts.lib.intake_cache`.

- [ ] **Step 3: Implement `scripts/lib/intake_cache.py`**

```python
"""Footage-intake checkpoint (design docs/specs/2026-07-25-intake-parallel-checkpoint-design.md §3).

Persists one clip's CV result so a long scan resumes instead of restarting, and
so a bad clip can be quarantined without losing the batch. `ClipResult`/`CastEntry`
are internal shapes (worker → cache → driver), NOT on-disk contracts a foreign
tool reads, so they are plain dataclasses without a from_dict gate — the on-disk
clip.json embeds FootageClip.to_dict(), which already round-trips. numpy is not
imported: the crop arrives as an ndarray whose .astype method is all `store` needs.
"""
import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from PIL import Image

from scripts.lib.footage import FootageClip
from scripts.track import MODEL

# Bump when Phase-1 logic changes shape (carve/score/descriptor/phash-point): it
# invalidates every cached clip in one move, so a re-run recomputes rather than
# trusting a result the new code would not produce. The #3 window-band slice bumps
# this. An all-or-nothing version beats a per-field logic hash nobody can audit.
CACHE_VERSION = 1


@dataclass
class CastEntry:
    """One surfaced track. Two forms: the worker builds it with a live `crop_rgb`
    array; `store` writes that array as a PNG and returns the cached form carrying
    `crop` (the on-disk path) instead. Phase 2 only ever sees the cached form."""
    source: str
    tid: int
    conf: float
    descriptor: list
    crop: str | None = None
    crop_rgb: object | None = None


@dataclass
class ClipResult:
    clip: FootageClip
    phashes: list = field(default_factory=list)   # hex strings, parallel to clip.windows
    cast: list = field(default_factory=list)       # list[CastEntry]


def clip_key(path: str, sample_fps: float, model: str = MODEL) -> dict:
    """Everything that changes a ClipResult. A mismatch on load → recompute."""
    st = os.stat(path)
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns,
            "sample_fps": float(sample_fps), "model": model, "version": CACHE_VERSION}


def _dir(out_dir: str, path: str) -> Path:
    # keyed on the file NAME (not stem): a.mp4 and a.mov must not collide
    return Path(out_dir) / ".intake_cache" / Path(path).name


def store(out_dir: str, path: str, sample_fps: float, result: ClipResult,
          model: str = MODEL) -> ClipResult:
    """Write the crop PNGs, then commit clip.json atomically (os.replace), and
    return the result in cached form (crop_rgb arrays replaced by their PNG paths)
    so a just-scanned clip and a loaded one present one shape to Phase 2 (§2/§3)."""
    d = _dir(out_dir, path)
    crops = d / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    cached = []
    for e in result.cast:
        png = crops / f"t{e.tid}.png"
        Image.fromarray(e.crop_rgb.astype("uint8")).save(png)
        cached.append(replace(e, crop=str(png), crop_rgb=None))
    payload = {"key": clip_key(path, sample_fps, model),
               "clip": result.clip.to_dict(),
               "phashes": list(result.phashes),
               "cast": [{"source": e.source, "tid": e.tid, "conf": e.conf,
                         "descriptor": e.descriptor, "crop": e.crop} for e in cached]}
    tmp = d / "clip.json.tmp"
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, d / "clip.json")               # atomic commit; presence == committed
    return ClipResult(clip=result.clip, phashes=list(result.phashes), cast=cached)


def load(out_dir: str, path: str, sample_fps: float,
         model: str = MODEL) -> ClipResult | None:
    """Return the cached-form ClipResult on a key match, else None. Absent, stale,
    truncated, or corrupt all read as a miss — never a crash."""
    f = _dir(out_dir, path) / "clip.json"
    try:
        payload = json.loads(f.read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if payload.get("key") != clip_key(path, sample_fps, model):
        return None
    clip = FootageClip.from_dict(payload["clip"])
    cast = [CastEntry(source=c["source"], tid=c["tid"], conf=c["conf"],
                      descriptor=c["descriptor"], crop=c["crop"]) for c in payload["cast"]]
    return ClipResult(clip=clip, phashes=payload["phashes"], cast=cast)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_intake_cache.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/intake_cache.py tests/lib/test_intake_cache.py
git commit -m "feat: intake_cache — atomic per-clip checkpoint store/load"
```

> **As-built (post-review, follow-up commit):** code review hardened the module beyond
> the block above — the committed code is the source of truth. Changes: `model` is a
> **required** parameter of `clip_key`/`store`/`load` (the `from scripts.track import
> MODEL` default was dropped — a lib must not import a driver; the driver supplies
> `track.MODEL`); `load` catches `KeyError`/`TypeError`/`ValueError` and guards
> `isinstance(payload, dict)` so a wrong-shape payload or a since-removed source file
> reads as a miss, never a crash; crop PNGs are written via `.tmp` + `os.replace`
> (`format="PNG"`) like `clip.json`; `descriptor`/`phashes`/`cast` are precisely typed;
> two tests added (non-dict JSON → miss, source-file-removed → miss). Tasks 3–4 below
> already pass `MODEL` to `store`/`load`.

---

## Task 1: `_process_clip` worker + Phase-2 assembly + cast refactor

Restructure `intake()` so the per-clip CV is a worker returning `ClipResult`, the
global tail assembles from `ClipResult`s in `sorted(paths)` order, and
`surface_crops`/`save_cast_candidates` consume precomputed `CastEntry`s. Still
**sequential**, no pool, no cache — the existing driver test proves the output did
not change (byte-identical extraction). `cull`'s body is untouched; only its
caller's `phash_of` closure changes (now reads worker phashes, not ffmpeg).

**Files:**
- Modify: `scripts/intake.py`
- Test: `tests/lib/test_intake.py`

- [ ] **Step 1: Write the failing worker test + update the cast/driver tests**

Add to `tests/lib/test_intake.py` (new test):

```python
def test_process_clip_returns_clip_phashes_and_cast(monkeypatch):
    from scripts.lib.footage import DESCRIPTOR_LEN
    red = np.zeros((8, 8, 3), "uint8"); red[:, :, 0] = 255
    monkeypatch.setattr(intake.assembly, "probe_stream",
                        lambda s: types.SimpleNamespace(w=1920, h=1080, fps=6.0))
    monkeypatch.setattr(intake.assembly, "probe_duration", lambda s: 8.0)
    monkeypatch.setattr(intake, "scene_bounds", lambda s: [])
    tl = [(float(i), 1, (500, 500, 300, 300)) for i in range(9)]
    monkeypatch.setattr(intake, "_people_timeline",
                        lambda s, fps, res, sample_fps=intake.SAMPLE_FPS:
                        (tl, {1: (0.9, red, np.ones((8, 8), "uint8"))}))
    monkeypatch.setattr(intake, "shake_by_window",
                        lambda clip, spans, fps, res, dur: [0.0 for _ in spans])
    monkeypatch.setattr(intake, "_phash_at",
                        lambda clip, t: imagehash.average_hash(_Img.new("L", (8, 8), 0)))
    res = intake._process_clip("/foot/a.mp4", intake.SAMPLE_FPS)
    assert res.clip.source == "a.mp4" and res.clip.windows
    assert len(res.phashes) == len(res.clip.windows)
    assert all(isinstance(h, str) for h in res.phashes)     # hex, cache-serializable
    assert len(res.cast) == 1
    assert res.cast[0].source == "a.mp4" and res.cast[0].tid == 1
    assert len(res.cast[0].descriptor) == DESCRIPTOR_LEN
    assert res.cast[0].crop_rgb is red                       # worker-form array
```

Replace `test_surface_crops_dedups_identities` (currently lines ~184-190) with the
precomputed-entry shape:

```python
def test_surface_crops_dedups_identities():
    from scripts.lib.intake_cache import CastEntry
    red = np.zeros((8, 8, 3), "uint8"); red[:, :, 0] = 255
    blue = np.zeros((8, 8, 3), "uint8"); blue[:, :, 2] = 255
    dr = appearance.build_descriptor(red, np.ones((8, 8), "uint8"))
    db = appearance.build_descriptor(blue, np.ones((8, 8), "uint8"))
    entries = [CastEntry("a.mp4", 1, 0.9, dr, crop_rgb=red),
               CastEntry("a.mp4", 2, 0.8, list(dr), crop_rgb=red.copy()),
               CastEntry("b.mp4", 3, 0.7, db, crop_rgb=blue)]
    picked = intake.surface_crops(entries, top_n=8)
    assert len(picked) == 2                            # the two reds collapse to one identity
```

Replace `test_save_cast_candidates_saves_and_manifests` (currently lines ~192-201):

```python
def test_save_cast_candidates_saves_and_manifests(tmp_path):
    from scripts.lib.intake_cache import CastEntry
    red = np.zeros((8, 8, 3), "uint8"); red[:, :, 0] = 255
    blue = np.zeros((8, 8, 3), "uint8"); blue[:, :, 2] = 255
    dr = appearance.build_descriptor(red, np.ones((8, 8), "uint8"))
    db = appearance.build_descriptor(blue, np.ones((8, 8), "uint8"))
    entries = [CastEntry("a.mp4", 1, 0.9, dr, crop_rgb=red),
               CastEntry("b.mp4", 1, 0.8, db, crop_rgb=blue)]
    manifest = intake.save_cast_candidates(entries, str(tmp_path))
    assert len(manifest) == 2
    assert (tmp_path / "cast_candidates.json").exists()
    assert (tmp_path / "cast_crops" / "candidate_0.png").exists()
    assert manifest[0]["source"] in {"a.mp4", "b.mp4"} and "descriptor" in manifest[0]
```

Add an `ensure_model` stub to the existing `test_intake_builds_footage_and_writes`
(the new driver calls it). Insert as the first line of the test body:

```python
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
```

- [ ] **Step 2: Run to verify the new/changed tests fail**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -q`
Expected: FAIL — `_process_clip` missing; `surface_crops`/`save_cast_candidates`
still expect the old dict shape.

- [ ] **Step 3: Implement in `scripts/intake.py`**

Add imports near the top (after the existing `import argparse, json, statistics, tempfile`):

```python
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
```

Change the track import line
`from scripts.track import MODEL` to:

```python
from scripts.track import MODEL, ensure_model
```

Add `intake_cache` to the lib import line
(`from scripts.lib import assembly, footage, vidstab`):

```python
from scripts.lib import assembly, footage, intake_cache, vidstab
from scripts.lib.intake_cache import CastEntry, ClipResult
```

Add the worker (place it just above `def intake(`):

```python
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
```

Replace `surface_crops` (currently ~lines 205-220) with the precomputed-entry form:

```python
def surface_crops(entries: list, top_n: int = 8) -> list:
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
```

Replace `save_cast_candidates` (currently ~lines 223-240):

```python
def save_cast_candidates(entries: list, out_dir: str, top_n: int = 8) -> list[dict]:
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
```

Replace the body of `intake()` (currently ~lines 287-314) with the sequential
worker-delegating form (pool + cache come in later tasks):

```python
def intake(footage_root: str, out_dir: str, sample_fps: float = SAMPLE_FPS) -> footage.Footage:
    root = Path(footage_root)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = sorted(p for p in root.iterdir() if p.suffix.lower() in _VIDEO_EXTS)
    ensure_model(MODEL)                                # weights-race landmine (§4), before any worker
    results = {p: _process_clip(str(p), sample_fps) for p in paths}
    ok = [results[p] for p in paths if p in results]
    result = footage.Footage(clips=[r.clip for r in ok])
    phash_by = {(r.clip.source, w.start, w.dur): imagehash.hex_to_hash(h)
                for r in ok for w, h in zip(r.clip.windows, r.phashes)}
    cull(result.clips, phash_of=lambda c, w: phash_by[(c.source, w.start, w.dur)])
    (out / "FOOTAGE.json").write_text(json.dumps(result.to_dict(), indent=2))
    (out / "FOOTAGE.md").write_text(result.to_markdown())
    save_cast_candidates([e for r in ok for e in r.cast], str(out))
    return result
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -q`
Expected: PASS (all — the new worker test, the two rewritten cast tests, and the
existing driver test that proves the extraction did not change the output).

- [ ] **Step 5: Commit**

```bash
git add scripts/intake.py tests/lib/test_intake.py
git commit -m "refactor: intake into a _process_clip worker + Phase-2 assembly"
```

---

## Task 2: parallel pool + `ensure_model` order + `jobs` validation + `--jobs`

Wrap the misses in a `ThreadPoolExecutor`, validate `jobs`, and expose `--jobs`.
No cache yet (every clip a miss). `ensure_model` already lands before the pool
(Task 1); this task pins its ordering and the concurrency.

**Files:**
- Modify: `scripts/intake.py`
- Test: `tests/lib/test_intake.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/lib/test_intake.py`:

```python
import threading


def _two_clip_root(tmp_path):
    root = tmp_path / "footage"; root.mkdir()
    (root / "a.mp4").write_bytes(b"x")
    (root / "b.mp4").write_bytes(b"y")
    return root


def _stub_cache(monkeypatch):
    # isolate the pool tests from the real filesystem cache
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    monkeypatch.setattr(intake.intake_cache, "load", lambda *a, **k: None)
    monkeypatch.setattr(intake.intake_cache, "store", lambda o, p, s, r, **k: r)


def _fake_result(name):
    from scripts.lib.footage import FootageClip
    return intake.ClipResult(clip=FootageClip(source=name, dur=1.0, res=(2, 2), fps=1.0,
                                              windows=[]), phashes=[], cast=[])


@pytest.mark.parametrize("bad", [0, -1, True, "3", 3.0])
def test_jobs_validation_rejects(tmp_path, bad):
    root = _two_clip_root(tmp_path)
    with pytest.raises(ValueError, match="jobs"):
        intake.intake(str(root), str(tmp_path / "out"), jobs=bad)


def test_ensure_model_runs_before_any_worker(monkeypatch, tmp_path):
    root = _two_clip_root(tmp_path)
    monkeypatch.setattr(intake.intake_cache, "load", lambda *a, **k: None)
    monkeypatch.setattr(intake.intake_cache, "store", lambda o, p, s, r, **k: r)
    seen = []
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: seen.append("ensure"))
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS:
                        (seen.append("pe"), _fake_result(intake.Path(path).name))[1])
    intake.intake(str(root), str(tmp_path / "out"), jobs=2)
    assert seen[0] == "ensure" and seen.count("ensure") == 1 and "pe" in seen


def test_pool_reaches_the_cap_and_never_exceeds_it(monkeypatch, tmp_path):
    root = tmp_path / "footage"; root.mkdir()
    for i in range(4):
        (root / f"c{i}.mp4").write_bytes(b"x")
    _stub_cache(monkeypatch)
    jobs = 2
    live = {"n": 0, "peak": 0}
    lock = threading.Lock()
    barrier = threading.Barrier(jobs, timeout=10)

    def fake_pe(path, sf=intake.SAMPLE_FPS):
        with lock:
            live["n"] += 1; live["peak"] = max(live["peak"], live["n"])
        barrier.wait()                       # forces `jobs` workers to co-exist; times out if serial
        with lock:
            live["n"] -= 1
        return _fake_result(intake.Path(path).name)

    monkeypatch.setattr(intake, "_process_clip", fake_pe)
    intake.intake(str(root), str(tmp_path / "out"), jobs=jobs)
    assert live["peak"] == jobs              # reached (barrier) and never exceeded


def test_output_is_byte_identical_across_jobs(monkeypatch, tmp_path):
    root = _two_clip_root(tmp_path)
    _stub_cache(monkeypatch)
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS: _fake_result(intake.Path(path).name))
    intake.intake(str(root), str(tmp_path / "o1"), jobs=1)
    intake.intake(str(root), str(tmp_path / "o3"), jobs=3)
    assert (tmp_path / "o1" / "FOOTAGE.json").read_text() == (tmp_path / "o3" / "FOOTAGE.json").read_text()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -k "jobs or ensure_model_runs or pool_reaches or byte_identical_across_jobs" -q`
Expected: FAIL — `intake()` has no `jobs` parameter yet (`TypeError`).

- [ ] **Step 3: Implement in `scripts/intake.py`**

Add the constant just below the other tuning constants (after `_VIDEO_EXTS`):

```python
DEFAULT_JOBS = 3          # cap-3's measured knee (design 2026-07-18 §2); see design §7 —
                          # not re-measured for full-clip passes; --jobs tunes on tight memory
```

Replace the `intake()` signature and its scan section (the `paths = ...` through
`results = {...}` lines from Task 1) with:

```python
def intake(footage_root: str, out_dir: str, sample_fps: float = SAMPLE_FPS, *,
           jobs: int = DEFAULT_JOBS) -> footage.Footage:
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 1:
        raise ValueError(f"intake: jobs must be an integer >= 1, got {jobs!r} — "
                         f"default {DEFAULT_JOBS} is a reasonable knee; lower it on a "
                         f"memory-constrained box, raise it only with a GPU")
    root = Path(footage_root)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = sorted(p for p in root.iterdir() if p.suffix.lower() in _VIDEO_EXTS)
    ensure_model(MODEL)                                # weights-race landmine (§4), before the pool
    results: dict = {}
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {p: ex.submit(_process_clip, str(p), sample_fps) for p in paths}
    for p in paths:
        results[p] = futs[p].result()
```

(The `ok = [...]` assembly block and everything after it from Task 1 stays
unchanged.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -q`
Expected: PASS (all).

- [ ] **Step 5: Add the `--jobs` CLI + commit**

In `main()`, add after the `--sample-fps` argument:

```python
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                    help="parallel clip workers (default %(default)s)")
```

and thread it into the call:

```python
    f = intake(a.footage_root, a.out_dir, a.sample_fps, jobs=a.jobs)
```

```bash
git add scripts/intake.py tests/lib/test_intake.py
git commit -m "feat: intake runs clips in a bounded thread pool (--jobs, default 3)"
```

---

## Task 3: cache wiring — load-before-submit, store-after, `--fresh`, resume

Load cache hits in the main thread (only misses reach the pool), store each
miss's result after it completes, and add `--fresh` to bypass the cache.

**Files:**
- Modify: `scripts/intake.py`
- Test: `tests/lib/test_intake.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/lib/test_intake.py`:

```python
def test_only_cache_misses_reach_the_pool(monkeypatch, tmp_path):
    root = _two_clip_root(tmp_path); out = tmp_path / "out"
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    submitted = []
    real_pe = intake._process_clip
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS:
                        (submitted.append(intake.Path(path).name),
                         _fake_result(intake.Path(path).name))[1])
    intake.intake(str(root), str(out))                 # first run: both are misses
    assert sorted(submitted) == ["a.mp4", "b.mp4"]
    submitted.clear()
    intake.intake(str(root), str(out))                 # second run: both cached
    assert submitted == []                             # nothing re-submitted
    submitted.clear()
    import shutil as _sh
    _sh.rmtree(out / ".intake_cache" / "b.mp4")        # invalidate just b
    intake.intake(str(root), str(out))
    assert submitted == ["b.mp4"]                       # only the miss reruns


def test_fresh_bypasses_the_cache(monkeypatch, tmp_path):
    root = _two_clip_root(tmp_path); out = tmp_path / "out"
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    submitted = []
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS:
                        (submitted.append(intake.Path(path).name),
                         _fake_result(intake.Path(path).name))[1])
    intake.intake(str(root), str(out))
    submitted.clear()
    intake.intake(str(root), str(out), fresh=True)     # ignore the populated cache
    assert sorted(submitted) == ["a.mp4", "b.mp4"]


def test_output_is_byte_identical_fresh_vs_cached(monkeypatch, tmp_path):
    root = _two_clip_root(tmp_path); out = tmp_path / "out"
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS: _fake_result(intake.Path(path).name))
    intake.intake(str(root), str(out))
    a = (out / "FOOTAGE.json").read_text()
    intake.intake(str(root), str(out))                 # all cache hits
    b = (out / "FOOTAGE.json").read_text()
    assert a == b
```

Note `_fake_result` (Task 2) has empty windows/cast, so `store` writes an empty
crops dir and a phash-less clip.json — the round-trip through `intake_cache` is
real here, which is what makes the resume assertions meaningful.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -k "cache_misses or fresh" -q`
Expected: FAIL — `intake()` has no `fresh` parameter; the second run re-submits.

- [ ] **Step 3: Implement in `scripts/intake.py`**

Change the signature to add `fresh`, and replace the scan section (the
`paths = ...` through the `for p in paths: results[p] = futs[p].result()` block
from Task 2) with the load/miss/store form:

```python
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
    results: dict = {}
    misses: list = []
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
```

(The `ok = [...]` assembly block and everything after it stay unchanged.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -q`
Expected: PASS (all).

- [ ] **Step 5: Add the `--fresh` CLI + commit**

In `main()`, add after `--jobs`:

```python
    ap.add_argument("--fresh", action="store_true",
                    help="ignore the .intake_cache and rescan every clip")
```

and thread it in:

```python
    f = intake(a.footage_root, a.out_dir, a.sample_fps, jobs=a.jobs, fresh=a.fresh)
```

```bash
git add scripts/intake.py tests/lib/test_intake.py
git commit -m "feat: intake resumes from a per-clip cache (--fresh to rescan)"
```

---

## Task 4: quarantine a bad clip + the report

A worker exception is caught in the join loop, recorded, and the scan continues;
the failures land in `intake_report.json`, a `## Failed clips` section of
`FOOTAGE.md`, and a loud stderr line. Exit 0. A quarantined clip wrote no
`clip.json`, so a re-run retries exactly it (design §5).

**Files:**
- Modify: `scripts/intake.py`
- Test: `tests/lib/test_intake.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/lib/test_intake.py`:

```python
def test_a_bad_clip_is_quarantined_not_fatal(monkeypatch, tmp_path):
    root = _two_clip_root(tmp_path); out = tmp_path / "out"
    _stub_cache(monkeypatch)

    def flaky(path, sf=intake.SAMPLE_FPS):
        name = intake.Path(path).name
        if name == "b.mp4":
            raise RuntimeError("corrupt moov atom")
        return _fake_result(name)

    monkeypatch.setattr(intake, "_process_clip", flaky)
    result = intake.intake(str(root), str(out))        # does NOT raise
    assert [c.source for c in result.clips] == ["a.mp4"]        # good clip survives
    report = json.loads((out / "intake_report.json").read_text())
    assert report["failed"] == [{"source": "b.mp4", "error": "corrupt moov atom"}]
    assert "## Failed clips" in (out / "FOOTAGE.md").read_text()
    assert (out / "FOOTAGE.json").exists()             # a valid artifact was produced
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -k quarantined -q`
Expected: FAIL — the exception propagates out of `futs[p].result()` and crashes
`intake()`.

- [ ] **Step 3: Implement in `scripts/intake.py`**

Replace the store loop (`for p in misses: results[p] = intake_cache.store(...)` from
Task 3) with the quarantining form:

```python
    failed: list = []
    for p in misses:
        try:
            results[p] = intake_cache.store(str(out), str(p), sample_fps, futs[p].result(), MODEL)
        except Exception as e:                         # quarantine (§5): name it, keep going
            failed.append({"source": p.name, "error": str(e)})
            print(f"intake: ⚠ {p.name} failed — {e}", file=sys.stderr)
```

Replace the output-writing tail (the `(out / "FOOTAGE.json") ...` through the
`save_cast_candidates(...)` and `return result` lines) with:

```python
    ok = [results[p] for p in paths if p in results]
    result = footage.Footage(clips=[r.clip for r in ok])
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
    (out / "intake_report.json").write_text(json.dumps(
        {"scanned": len(misses) - len(failed), "cached": len(results) - (len(misses) - len(failed)),
         "failed": failed}, indent=2))
    if failed:
        print(f"intake: ⚠ {len(failed)} clip(s) failed — see {out / 'intake_report.json'}",
              file=sys.stderr)
    return result
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add scripts/intake.py tests/lib/test_intake.py
git commit -m "feat: intake quarantines a bad clip and reports it (intake_report.json)"
```

---

## Task 5: integration — resume from cache on real bytes

The existing golden must stay green (it now hits `ensure_model`, so stub it), and a
new test proves that a second run on real bytes recomputes nothing and yields
byte-identical output.

**Files:**
- Modify: `tests/integration/test_intake.py`

- [ ] **Step 1: Add the `ensure_model` stub to both existing tests + write the resume test**

In `tests/integration/test_intake.py`, add this line to the body of BOTH
`test_intake_wiring_on_real_bytes` and `test_intake_real_vidstab_shake`, right after
their `monkeypatch.setattr(intake, "_iter_seg", ...)` line:

```python
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
```

Add the new test at the end of the file:

```python
def test_intake_resumes_from_cache_byte_identical(monkeypatch, tmp_path, sample_clip):
    # real ffprobe + PySceneDetect + phash on run 1; run 2 must touch NO clip CV
    root = tmp_path / "footage"; root.mkdir()
    shutil.copy(sample_clip, root / "clip.mp4")
    monkeypatch.setattr(intake, "_iter_seg", lambda src, **k: iter(enumerate(_fake_frames(90))))
    monkeypatch.setattr(intake, "shake_by_window",
                        lambda clip, spans, fps, res, dur: [0.0 for _ in spans])
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    out = tmp_path / "out"
    intake.intake(str(root), str(out))
    first = (out / "FOOTAGE.json").read_text()
    assert (out / ".intake_cache" / "clip.mp4" / "clip.json").exists()

    monkeypatch.setattr(intake, "_process_clip",
                        lambda *a, **k: pytest.fail("resume recomputed a cached clip"))
    intake.intake(str(root), str(out))                 # must be all cache hits → no CV
    assert (out / "FOOTAGE.json").read_text() == first
```

- [ ] **Step 2: Run to verify the resume test drives the cache**

Run: `.venv/bin/python -m pytest tests/integration/test_intake.py -q`
Expected: PASS (3 tests; the vidstab one skips if libvidstab is absent). If the
resume test FAILS at `pytest.fail("resume recomputed...")`, the cache is not being
consulted — a real regression, not a test bug.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_intake.py
git commit -m "test: intake resumes from cache byte-identical on real bytes"
```

---

## Task 6: docs sync

**Files:**
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`,
  `docs/specs/2026-07-12-footage-intake-design.md`

- [ ] **Step 1: `CLAUDE.md` — two registry rows**

In the Quick Reference table, add after the existing footage-intake plan row (the
`2026-07-12-footage-intake.md` line):

```markdown
| Intake parallel+checkpoint design | [2026-07-25-intake-parallel-checkpoint-design.md](docs/specs/2026-07-25-intake-parallel-checkpoint-design.md) | Slice B (#4/#5): `intake()` → parallel checkpointed Phase 1 + cheap deterministic Phase 2; `lib/intake_cache.py` atomic per-clip store/load (key = size/mtime/sample_fps/model/`CACHE_VERSION`); `--jobs`/`--fresh`; **byte-identical at any jobs & cache mix**; bad clip quarantined to `intake_report.json`. #3 window band deferred. |
| Intake parallel+checkpoint plan | [2026-07-25-intake-parallel-checkpoint.md](docs/plans/2026-07-25-intake-parallel-checkpoint.md) | Tasks 0–6: `intake_cache` module, `_process_clip` worker + Phase-2 assembly + cast refactor, the pool + `ensure_model`, cache wiring + resume, quarantine + report, integration resume proof, docs. |
```

- [ ] **Step 2: `docs/build-status.md` — a Done entry + date**

Change the top `_Last updated: 2026-07-24._` to `_Last updated: 2026-07-25._`, and
add this as the FIRST bullet under `## Done`:

```markdown
- **Intake parallel scan + resumable checkpoint DONE (2026-07-25)** — plan
  `docs/plans/2026-07-25-intake-parallel-checkpoint.md`, Tasks 0–6 (slice B, #4/#5).
  `intake()` split into a parallel checkpointed Phase 1 (`_process_clip` worker in a
  `ThreadPoolExecutor`, `--jobs` default 3, `ensure_model` before the pool) and a
  cheap deterministic Phase 2 (cull + cast in `sorted(paths)` order). New
  `scripts/lib/intake_cache.py`: atomic per-clip store/load keyed on
  size/mtime/sample_fps/model/`CACHE_VERSION`; `--fresh` bypasses it. Output is
  byte-identical at any `jobs` and any cache hit/miss mix. A bad clip is quarantined
  to `intake_report.json` + a `## Failed clips` section (exit 0); a re-run retries
  exactly the failed clips. #3 window band deferred to its own slice.
```

- [ ] **Step 3: `docs/pipeline-map.md` — annotate stage 5.2**

Replace the stage-5.2 row of the first table (currently the line beginning
`| 5.2  | footage-intake | \`FOOTAGE.json\`+\`.md\` | ✅ |`) with:

```markdown
| 5.2  | footage-intake | `FOOTAGE.json`+`.md` | ✅ | `intake.py`: probe + PySceneDetect + YOLO11-seg + vidstabdetect → sub-scene carve → score → phash cull → `FOOTAGE.json`/`.md` + `cast.json` (SP2); **parallel + resumable** (`--jobs`, per-clip `.intake_cache`, `--fresh`; bad clip → `intake_report.json`) since 2026-07-25 | — |
```

- [ ] **Step 4: `docs/specs/2026-07-12-footage-intake-design.md` — a superseded-in-part note**

Add this note immediately under the design's title/status header:

```markdown
> **Driver superseded in part (2026-07-25):** `intake()` now runs clips in a
> bounded thread pool with a resumable per-clip checkpoint and quarantines a bad
> clip — see [2026-07-25-intake-parallel-checkpoint-design.md](2026-07-25-intake-parallel-checkpoint-design.md).
> The CV units (probe/scene/YOLO/vidstab/carve/score/cull/cast) are unchanged; the
> window band (`_split_span`, #3) is a separate deferred slice.
```

- [ ] **Step 5: Verify the whole suite is green**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — the prior slice's baseline plus this slice's new tests, integration
vidstab test skipping only if libvidstab is absent.

- [ ] **Step 6: Commit**

```bash
git add docs/ CLAUDE.md
git commit -m "docs: register the intake parallel+checkpoint slice; sync build-status, pipeline-map"
```

---

## Self-review notes (checked against the spec)

- **§2 worker** → Task 1 (`_process_clip`, phash + descriptor in the worker).
- **§3 cache** → Task 0 (`intake_cache`: layout, atomic commit, key, corrupt→miss);
  `--fresh` → Task 3.
- **§4 pool / ensure_model / byte-identical invariant** → Task 2 (pool, order,
  jobs≡output) + Task 3 (fresh≡cached output).
- **§5 quarantine + report + retry-only-failed** → Task 4 (quarantine, report) +
  Task 3's resume test (a missing cache entry re-submits exactly that clip).
- **§6 refactor** → Task 1 (`cull` body untouched; `surface_crops`/`save_cast`
  precomputed entries).
- **§7 jobs/memory** → Task 2 (`DEFAULT_JOBS`, validation, `--jobs`).
- **§9 testing** → cache battery (Task 0), driver unit incl. barrier (Tasks 2–4),
  integration resume (Task 5).
- **Type consistency:** `ClipResult`/`CastEntry` defined in Task 0, imported and
  used identically in Tasks 1–4; `store(out, path, sample_fps, result, model=)` and
  `load(out, path, sample_fps, model=)` signatures match every call site;
  `phash_by` keyed `(source, start, dur)` consistently in Tasks 1 and 4.
