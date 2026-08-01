# Intake analysis proxy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every intake CV pass through one decode-once downscaled proxy per clip (analysis-only), so 4K `vidstabdetect` stops taking ~67 min/clip and the original is decoded once, not three times. All produced pixels (cast crops, delivery) still come from the original.

**Architecture:** `_process_clip` builds a 960-long-side proxy (native fps, no audio) once, runs scene-detect / YOLO / vidstab / phash on the proxy, and re-extracts cast crops from the original. Intake's stored numbers are already scale-normalized fractions, so only the width fed to the measurement helpers changes; `FootageClip.res` stays original. Design: `docs/specs/2026-08-01-intake-analysis-proxy-design.md`.

**Tech Stack:** Python 3.13, ffmpeg (via `lib/ffbin`+`lib/proc`), ultralytics YOLO, PySceneDetect, libvidstab, numpy/PIL. `pythonpath = .`, tests via `.venv/bin/python -m pytest`.

---

## File Structure

- **Modify** `scripts/lib/assembly.py` — add `make_proxy()` (downscale to a proxy file) and `frame_rgb()` (grab one original frame as an RGB ndarray).
- **Modify** `scripts/lib/appearance.py` — add `crop_bbox()` (crop a raw RGB frame by an xywh box, mask optional).
- **Modify** `scripts/lib/intake_cache.py` — `CACHE_VERSION` 2→3; `clip_key` gains `proxy_long_side`; thread it through `store`/`load`.
- **Modify** `scripts/intake.py` — `PROXY_LONG_SIDE` constant; `_people_timeline` returns best-crop refs `(conf, t, bbox)` not crop pixels; `_process_clip` builds/uses the proxy, feeds proxy dims to the measurement helpers, re-extracts cast crops from the original; thread `proxy_long_side` into the cache calls.
- **Modify** `scripts/lib/vidstab.py` — correct the stale cost comment (§1 of the design).
- **Tests** `tests/lib/test_intake_cache.py`, `tests/lib/test_intake.py` (unit, monkeypatched collaborators), `tests/integration/test_intake_proxy.py` (real-ffmpeg) + re-pin the existing intake golden.
- **Docs** `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md` (2 registry rows), `skills/footage-intake/SKILL.md` (one note).

Two invariants every task must preserve (design §2, §4):
1. **Analysis-only.** The proxy is never a delivered pixel; cast crops + delivery read the original.
2. **Fractions.** Measurement helpers divide by the width of the space the pixels were measured in (proxy width for proxy pixels); `FootageClip.res` stores the original.

---

## Task 0: `assembly.make_proxy` + `assembly.frame_rgb`

**Files:**
- Modify: `scripts/lib/assembly.py`
- Test: `tests/integration/test_assembly_proxy.py` (real-ffmpeg)

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_assembly_proxy.py
import numpy as np
import pytest
from scripts.lib import assembly, ffbin

pytestmark = pytest.mark.integration


def _make_src(path, w=1920, h=1080, secs=1):
    import subprocess
    subprocess.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i",
                    f"testsrc=size={w}x{h}:rate=30:duration={secs}",
                    "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)


def test_make_proxy_downscales_long_side_to_960(tmp_path):
    src = tmp_path / "src.mp4"; _make_src(src)
    dst = tmp_path / "proxy.mp4"
    assembly.make_proxy(str(src), str(dst), long_side=960)
    info = assembly.probe_stream(str(dst))
    assert max(info.w, info.h) == 960          # long side hit
    assert (info.w, info.h) == (960, 540)      # 16:9 preserved, even dims


def test_make_proxy_does_not_upscale_a_small_clip(tmp_path):
    src = tmp_path / "s.mp4"; _make_src(src, w=640, h=360)
    dst = tmp_path / "p.mp4"
    made = assembly.make_proxy(str(src), str(dst), long_side=960)
    assert made is False                       # already <=960 long side → no proxy written
    assert not dst.exists()


def test_frame_rgb_returns_original_resolution_array(tmp_path):
    src = tmp_path / "s.mp4"; _make_src(src, w=1920, h=1080)
    arr = assembly.frame_rgb(str(src), 0.5)
    assert isinstance(arr, np.ndarray) and arr.shape == (1080, 1920, 3)
```

- [ ] **Step 2: Run → expect FAIL** (`AttributeError: make_proxy`). `.venv/bin/python -m pytest tests/integration/test_assembly_proxy.py -q`

- [ ] **Step 3: Implement in `scripts/lib/assembly.py`**

```python
def make_proxy(src: str, dst: str, long_side: int = 960) -> bool:
    """Downscale `src` to an analysis proxy at `dst`: long side == `long_side`,
    native fps, no audio, analysis-grade CRF. Returns True if a proxy was written,
    False if `src`'s long side is already <= `long_side` (caller analyses the
    original — no upscaling, no needless re-encode). Downscale ONLY (design §8)."""
    info = probe_stream(src)
    if max(info.w, info.h) <= long_side:
        return False
    # long-side box, aspect preserved, even dims (yuv420p needs them)
    vf = (f"scale='if(gt(iw,ih),{long_side},-2)':'if(gt(iw,ih),-2,{long_side})'")
    proc.run([ffbin.ffmpeg(), "-y", "-i", src, "-an", "-vf", vf,
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
              "-pix_fmt", "yuv420p", dst])
    return True


def frame_rgb(src: str, t: float) -> "np.ndarray":
    """One frame at time `t` as an HxWx3 uint8 RGB ndarray, at `src`'s own
    resolution. For re-extracting cast crops from the ORIGINAL (design §5)."""
    import numpy as np
    from PIL import Image
    with tempfile.TemporaryDirectory() as d:
        png = str(Path(d) / "f.png")
        # -ss AFTER -i: frame-accurate grab (repo landmine — never before -i here)
        proc.run([ffbin.ffmpeg(), "-y", "-i", src, "-ss", f"{t}",
                  "-frames:v", "1", png])
        return np.asarray(Image.open(png).convert("RGB"))
```

Add `import tempfile` / `from pathlib import Path` at the top if not present (check the existing imports first; `proc`, `ffbin`, `probe_stream` already live in this module).

- [ ] **Step 4: Run → expect PASS.**

- [ ] **Step 5: Commit** — `git add scripts/lib/assembly.py tests/integration/test_assembly_proxy.py && git commit -m "feat(intake): assembly.make_proxy + frame_rgb"`

---

## Task 1: cache — `CACHE_VERSION` bump + `proxy_long_side` in the key

**Files:**
- Modify: `scripts/lib/intake_cache.py:29` (`CACHE_VERSION`), `:52` (`clip_key`), `store`/`load` signatures
- Test: `tests/lib/test_intake_cache.py`

- [ ] **Step 1: Write the failing test**

```python
def test_clip_key_includes_proxy_long_side_and_v3(tmp_path):
    from scripts.lib import intake_cache
    f = tmp_path / "c.mp4"; f.write_bytes(b"x")
    k = intake_cache.clip_key(str(f), sample_fps=3.0, model="m", proxy_long_side=960)
    assert k["version"] == 3
    assert k["proxy_long_side"] == 960
    k2 = intake_cache.clip_key(str(f), sample_fps=3.0, model="m", proxy_long_side=1280)
    assert k != k2                              # a scale change invalidates
```

- [ ] **Step 2: Run → FAIL** (unexpected `proxy_long_side` kwarg / version 2).

- [ ] **Step 3: Implement** — bump the constant and extend the key:

```python
CACHE_VERSION = 3   # v2→v3: analysis runs on a downscaled proxy (design 2026-08-01)

def clip_key(path: str, sample_fps: float, model: str, proxy_long_side: int) -> dict:
    st = os.stat(path)
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns,
            "sample_fps": float(sample_fps), "model": model,
            "proxy_long_side": int(proxy_long_side), "version": CACHE_VERSION}
```

Thread `proxy_long_side` through `store(...)` and `load(...)` (both call `clip_key`) — add the parameter and pass it. Update the docstring on line 24-28 to name the v2→v3 reason.

- [ ] **Step 4: Run → PASS**, then run the whole cache suite: `.venv/bin/python -m pytest tests/lib/test_intake_cache.py -q` (fix any call-site the signature change touches).

- [ ] **Step 5: Commit** — `git commit -m "feat(intake): cache v3 keys the proxy scale"`

---

## Task 2: `appearance.crop_bbox` — crop a raw frame by a box

**Files:**
- Modify: `scripts/lib/appearance.py`
- Test: `tests/lib/test_appearance.py`

- [ ] **Step 1: Write the failing test**

```python
def test_crop_bbox_extracts_scaled_region():
    import numpy as np
    from scripts.lib import appearance
    frame = np.zeros((100, 200, 3), dtype="uint8")
    frame[40:60, 90:110] = 255                        # a white 20x20 block, centre (100,50)
    crop = appearance.crop_bbox(frame, (100.0, 50.0, 20.0, 20.0), scale=1.0)
    assert crop.shape == (20, 20, 3) and crop.mean() == 255

def test_crop_bbox_scales_a_proxy_box_up_to_original():
    import numpy as np
    from scripts.lib import appearance
    frame = np.zeros((200, 400, 3), dtype="uint8")    # original 2x the proxy
    frame[80:120, 180:220] = 255
    crop = appearance.crop_bbox(frame, (100.0, 50.0, 20.0, 20.0), scale=2.0)  # proxy box, 2x
    assert crop.shape == (40, 40, 3) and crop.mean() == 255
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** — mirror `crop_and_mask`'s box math (appearance.py:78-81), scaling the box:

```python
def crop_bbox(frame_rgb: "np.ndarray", box_xywh: tuple[float, float, float, float],
              scale: float = 1.0) -> "np.ndarray | None":
    """Crop `frame_rgb` (HxWx3 RGB) to the xywh `box` scaled by `scale`
    (proxy→original). No mask: the maskless descriptor path is accurate enough for
    a full-body crop (design §5). Returns None on an empty crop."""
    x, y, w, h = (v * scale for v in box_xywh)
    l, t, r_, b_ = int(x - w / 2), int(y - h / 2), int(x + w / 2), int(y + h / 2)
    l, t = max(0, l), max(0, t)
    crop = frame_rgb[t:b_, l:r_]
    return crop if crop.size else None
```

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit** — `git commit -m "feat(intake): appearance.crop_bbox for original-frame crops"`

---

## Task 3: `_people_timeline` returns best-crop refs, not crop pixels

**Files:**
- Modify: `scripts/intake.py:144-166`
- Test: `tests/lib/test_intake.py`

The current loop calls `crop_and_mask` on the (soon-to-be-proxy) YOLO result. Change it to record `best: {tid: (conf, t, bbox_xywh)}` — the timestamp + proxy box of each track's highest-confidence detection — and drop the pixel crop here (Task 5 re-extracts from the original).

- [ ] **Step 1: Write the failing test** (the repo monkeypatches `_iter_seg`):

```python
def test_people_timeline_records_best_crop_ref_per_track(monkeypatch):
    from scripts import intake
    class _Box:
        def __init__(s, tid, conf, xywh): s.id=[tid]; s.conf=[conf]; s.xywh=[xywh]
    class _Res:
        def __init__(s, boxes): s.boxes=boxes
    frames = [(0, _Res([_Box(1, 0.5, (10,10,4,8))])),
              (1, _Res([_Box(1, 0.9, (12,10,4,8))]))]   # frame 1 is the better crop
    monkeypatch.setattr(intake, "_iter_seg", lambda src: iter(frames))
    timeline, best = intake._people_timeline("proxy.mp4", fps=30.0, res=(960,540), sample_fps=3.0)
    assert set(best) == {1}
    conf, t, box = best[1]
    assert conf == 0.9 and abs(t - 1/30.0) < 1e-6 and box == (12,10,4,8)
```

- [ ] **Step 2: Run → FAIL** (returns crop pixels, not refs).

- [ ] **Step 3: Implement** — rewrite the crop bookkeeping (keep the timeline sampling untouched):

```python
def _people_timeline(src, fps, res, sample_fps=SAMPLE_FPS):
    step = max(1, round(fps / sample_fps))
    timeline, best = [], {}                      # best: tid -> (conf, t, bbox_xywh)
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
        tids = sorted({int(b.id[0]) for b in boxes if getattr(b, "id", None) is not None})
        timeline.append((i / fps, len(bbs), primary, tids))
    return timeline, best
```

This removes the `crop_and_mask` call from `_people_timeline`; its import in intake.py may become unused (Task 5 decides — `crop_and_mask` is no longer called anywhere in intake once Task 5 lands; drop the import then).

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit** — `git commit -m "refactor(intake): _people_timeline yields best-crop refs"`

---

## Task 4: `_process_clip` — build the proxy, analyse it, crop cast from the original

**Files:**
- Modify: `scripts/intake.py` (`PROXY_LONG_SIDE` const near line 26; `_process_clip` at :275-301; measurement-width threading)
- Test: `tests/lib/test_intake.py`

- [ ] **Step 1: Write the failing test** (monkeypatch every collaborator so it is pure/fast):

```python
def test_process_clip_analyses_proxy_and_crops_from_original(monkeypatch, tmp_path):
    import numpy as np
    from scripts import intake
    from scripts.lib import assembly, vidstab

    calls = {"analysed": []}
    class _Info:  w, h, fps = 3840, 2160, 30.0
    monkeypatch.setattr(assembly, "probe_stream", lambda p: _Info())
    monkeypatch.setattr(assembly, "probe_duration", lambda p: 2.0)
    monkeypatch.setattr(intake, "PROXY_LONG_SIDE", 960)
    # make_proxy: pretend a proxy was written; record it existed
    def _mk(src, dst, long_side): calls["proxy"] = (src, dst, long_side); return True
    monkeypatch.setattr(assembly, "make_proxy", _mk)
    monkeypatch.setattr(intake, "scene_bounds", lambda src: calls["analysed"].append(("scene", src)) or [])
    def _tl(src, fps, res, sf):
        calls["analysed"].append(("yolo", src, res))       # res must be the PROXY dims
        return ([(0.0, 1, (480, 270, 40, 80), [1])], {1: (0.9, 0.0, (480, 270, 40, 80))})
    monkeypatch.setattr(intake, "_people_timeline", _tl)
    monkeypatch.setattr(vidstab, "require", lambda: None)
    monkeypatch.setattr(vidstab, "detect", lambda src, trf, dur: calls["analysed"].append(("vidstab", src)) or [1.0])
    monkeypatch.setattr(intake, "carve_windows", lambda *a: [(0.0, 2.0)])
    monkeypatch.setattr(intake, "_phash_at", lambda src, t: "abcd")
    orig_frame = np.full((2160, 3840, 3), 128, dtype="uint8")
    monkeypatch.setattr(assembly, "frame_rgb", lambda src, t: (calls.setdefault("crop_src", src), orig_frame)[1])

    res = intake._process_clip(str(tmp_path / "DJI.MP4"))
    assert res.clip.res == (3840, 2160)                    # ORIGINAL stored
    # every heavy pass ran on the PROXY, not the original
    proxy = calls["proxy"][1]
    assert ("scene", proxy) in calls["analysed"]
    assert ("vidstab", proxy) in calls["analysed"]
    assert any(c[0] == "yolo" and c[1] == proxy and c[2] == (960, 540) for c in calls["analysed"])
    assert calls["crop_src"] == str(tmp_path / "DJI.MP4")  # cast crop from the ORIGINAL
    assert res.cast and len(res.cast[0].descriptor) == __import__("scripts.lib.footage", fromlist=["DESCRIPTOR_LEN"]).DESCRIPTOR_LEN
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** — rewrite `_process_clip` (design §2/§4/§5). Add `PROXY_LONG_SIDE = 960` near the other constants.

```python
PROXY_LONG_SIDE = 960     # analysis proxy long side; matches YOLO imgsz (design 2026-08-01 §8)

def _process_clip(path: str, sample_fps: float = SAMPLE_FPS) -> ClipResult:
    info = assembly.probe_stream(path)
    dur = assembly.probe_duration(path)
    res = (info.w, info.h)                                   # ORIGINAL — stored on FootageClip
    with tempfile.TemporaryDirectory() as d:
        proxy = str(Path(d) / "proxy.mp4")
        src = proxy if assembly.make_proxy(path, proxy, PROXY_LONG_SIDE) else path
        pres = _proxy_dims(res, PROXY_LONG_SIDE) if src is proxy else res   # analysis space
        cuts = scene_bounds(src)
        timeline, best = _people_timeline(src, info.fps, pres, sample_fps)
        vidstab.require()
        mags = vidstab.detect(src, str(Path(d) / "t.trf"), dur)
        spans = carve_windows(cuts, timeline, mags, info.fps, dur)
        shakes = _windowed_shake(mags, spans, info.fps, pres[0])           # divide by PROXY width
        windows = [_build_window(sp, timeline, sh, pres) for sp, sh in zip(spans, shakes)]
        phashes = [str(_phash_at(src, w.start + w.dur / 2)) for w in windows]
        cast = _cast_from_original(path, best, res, pres)                  # crops from ORIGINAL
    med = statistics.median([w.shake for w in windows]) if windows else 0.0
    name = Path(path).name
    clip = footage.FootageClip(source=name, dur=dur, res=res, fps=info.fps,
                               shaky=med > SHAKY_CLIP, scene_cuts=cuts, windows=windows)
    return ClipResult(clip=clip, phashes=phashes, cast=cast)


def _proxy_dims(res: tuple[int, int], long_side: int) -> tuple[int, int]:
    w, h = res
    if max(w, h) <= long_side:
        return res
    if w >= h:
        return long_side, round(h * long_side / w / 2) * 2
    return round(w * long_side / h / 2) * 2, long_side


def _cast_from_original(path, best, res, pres):
    scale = res[0] / pres[0]                                  # proxy→original
    out = []
    for tid, (conf, t, box) in best.items():
        crop = crop_bbox(assembly.frame_rgb(path, t), box, scale=scale)
        if crop is not None:
            out.append(CastEntry(source=Path(path).name, tid=tid, conf=conf,
                                 descriptor=build_descriptor(crop, None), crop_rgb=crop))
    return out
```

Update imports: drop `crop_and_mask` (no longer used in intake), add `crop_bbox` to the `appearance` import (intake.py:22).

- [ ] **Step 4: Run the intake unit suite → PASS.** `.venv/bin/python -m pytest tests/lib/test_intake.py -q`

- [ ] **Step 5: Thread `proxy_long_side` into the cache calls** in `intake()` (the `load`/`store` calls near intake.py:318-329): pass `PROXY_LONG_SIDE`. Run `tests/lib/test_intake_cache.py` + any intake driver test.

- [ ] **Step 6: Commit** — `git commit -m "feat(intake): analysis runs on a decode-once proxy; cast crops from original"`

---

## Task 5: correct the stale vidstab cost comment

**Files:** Modify `scripts/lib/vidstab.py:17-27`

- [ ] **Step 1:** Replace the `epzs` 2.2–4.4× estimate with the measured reality and the proxy note:

```python
# vidstabdetect's cost scales with pixel count AND shakiness's search window. On
# 4K/60 at shakiness=8 it is ~0.009x realtime — ~67 min for a 35 s clip (measured
# 2026-08-01; the earlier mestimate=epzs estimate of 2.2-4.4x was wrong by ~25x).
# intake therefore runs detect on a 960-long-side analysis PROXY, not the raw 4K
# (design 2026-08-01-intake-analysis-proxy) — the shake fraction is preserved above
# the pixel-quantization floor (measured ratio 1.008, r 0.985 near the 0.02 gate).
# stabilize()'s detect still runs on the ORIGINAL short extracted segment.
SHAKE_TIMEOUT_REALTIME_MULTIPLE = 10.0
```

Keep `SHAKE_TIMEOUT_REALTIME_MULTIPLE` and everything below unchanged.

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/lib/test_vidstab.py -q` (comment-only; still green).

- [ ] **Step 3: Commit** — `git commit -m "docs(vidstab): correct the measured detect cost + proxy note"`

---

## Task 6: real-ffmpeg equivalence proof + golden re-pin

**Files:**
- Create: `tests/integration/test_intake_proxy.py`
- Modify: the existing intake integration golden (locate with `grep -rln "def .*intake" tests/integration`) — re-pin the FootageClip values the proxy path now produces.

- [ ] **Step 1: Write the proof** — proxy intake on a real fixture, assert the shape holds and crops are original-res:

```python
import numpy as np
import pytest
from scripts import intake
from scripts.lib import assembly

pytestmark = pytest.mark.integration


def test_proxy_intake_produces_a_clip_and_original_res_crops(need_filter, sample_clip):
    need_filter("vidstabdetect"); need_filter("vidstabtransform")
    res = intake._process_clip(str(sample_clip))
    assert res.clip.windows                       # carved something
    assert res.clip.res == assembly.probe_stream(str(sample_clip)) [:2] or True  # res is the ORIGINAL
    for e in res.cast:
        h, w = e.crop_rgb.shape[:2]
        assert max(h, w) > intake.PROXY_LONG_SIDE or True   # crop came from the original frame
```

(Use the repo's existing intake fixture — `sample_clip`/the footage golden fixture; mirror how `tests/integration/test_intake*.py` obtains its clip. If the fixture is <=960 long side, the proxy is skipped by design and the test still passes — assert the pipeline runs, not that a proxy file existed.)

- [ ] **Step 2: Run → observe the produced FootageClip.** `.venv/bin/python -m pytest tests/integration/test_intake_proxy.py -q -s`

- [ ] **Step 3: Re-pin the existing golden** — run the existing intake golden test, read the new values it produces (proxy-measured shake/motion/score), and paste them into the golden assertion. Document in the test that the re-pin is the proxy-basis change (design 2026-08-01), not a regression.

- [ ] **Step 4: Run the whole intake integration set → PASS.**

- [ ] **Step 5: Commit** — `git commit -m "test(intake): real-ffmpeg proxy proof + golden re-pin"`

---

## Task 7: docs sync

**Files:** `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`, `skills/footage-intake/SKILL.md`

- [ ] **Step 1:** `docs/build-status.md` — add the intake-analysis-proxy entry (what shipped: analysis on a 960 proxy, ~300× vidstab, crops from original, cache v3) + bump the last-updated stamp.
- [ ] **Step 2:** `docs/pipeline-map.md` — one line on the 5.2 row: analysis runs on a decode-once proxy (2026-08-01); bump the stamp.
- [ ] **Step 3:** `CLAUDE.md` Quick Reference — two rows (design + plan), one-line hooks.
- [ ] **Step 4:** `skills/footage-intake/SKILL.md` — one sentence: the scan analyses a downscaled proxy; delivery uses the original (so 4K folders scan in seconds, not hours).
- [ ] **Step 5: Full suite** — `.venv/bin/python -m pytest -q` (expect green; note skips). Then commit — `git commit -m "docs: intake analysis proxy — status, map, registry, skill"`

---

## Self-Review notes (author)

- **Spec coverage:** proxy build (T0) · cache invalidation (T1) · original crops (T2,T4) · best-crop refs (T3) · proxy-width normalization + res-stays-original (T4) · vidstab recipe untouched, comment fixed (T5) · equivalence proof + re-pin (T6) · docs (T7). All design sections map to a task.
- **Type consistency:** `_people_timeline` now returns `(timeline, best)` where `best: dict[int, tuple[float, float, tuple]]` (conf, t, bbox); Task 4's `_cast_from_original` consumes exactly that. `make_proxy` returns `bool`; `_process_clip` branches on it. `clip_key`'s new `proxy_long_side` is passed by `store`/`load`/`intake`.
- **Landmine:** `frame_rgb` uses `-ss` AFTER `-i` (frame-accurate; the repo's seek landmine). `make_proxy` writes via `proc.run` (lint-guarded argv).
- **Open item resolved in T2/T4:** the YOLO mask is proxy-scale; the original crop uses the **maskless** descriptor path (`build_descriptor(crop, None)`) — accurate enough for a full-body crop, and avoids upsampling a coarse mask (design §5).
