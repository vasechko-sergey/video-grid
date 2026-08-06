# Intake frame-grab batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace intake's per-grab output-seek frame extraction (cast crops from the original, per-window phashes from the proxy) with one batched, frame-accurate `assembly.frames_rgb` decode per consumer.

**Architecture:** A new pure ffmpeg primitive `assembly.frames_rgb(src, times, fps)` selects exact frames (`select='eq(n,N)+...'`) in a single decode and returns arrays aligned to the input times. `_cast_from_original` and intake's phash both route through it; `frame_rgb` becomes a thin wrapper. `check_reel`/`storyboard` are untouched. Output shifts by ≤1 frame vs the old output-seek, so `CACHE_VERSION` bumps 4→5 and the real-ffmpeg intake golden is re-pinned.

**Tech Stack:** Python 3.13, ffmpeg (via `scripts/lib/ffbin` + `scripts/lib/proc`), numpy, Pillow, imagehash, pytest.

## Global Constraints

- Python is `.venv/bin/python` (3.13). Run tests with `.venv/bin/python -m pytest` (scripts run as modules; `pythonpath = .` is set in pytest config).
- **Do NOT run installers** (no brew/pip/uv/npm install, no `setup.sh`). The toolchain is already present.
- Fail-loud contract; imports at top of file; typed signatures (see `docs/coding-standards.md`).
- **Landmines (design §12):** `-ss` AFTER `-i` for re-encoded cuts; `lutrgb` is banned. This slice adds no `-ss` — `frames_rgb` uses `select`, and the lint already exempts a `-frames:v` still grab (`scripts/lib/lint.py:159`).
- Real pixel behavior is proven with real ffmpeg (`@pytest.mark.integration`), not mocks (see `docs/testing-guide.md`).
- Commit bodies end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. One committer at a time; committing subagents run synchronously.

---

### Task 0: `assembly.frames_rgb` primitive + `frame_rgb` wrapper

**Files:**
- Modify: `scripts/lib/assembly.py` (add `frames_rgb`; rewrite `frame_rgb` at lines 167-175 as a wrapper)
- Test: `tests/integration/test_assembly_proxy.py`

**Interfaces:**
- Produces: `assembly.frames_rgb(src: str, times: list[float], fps: float) -> list[np.ndarray]` — RGB `HxWx3 uint8`, one per input time, in input order, one decode. `assembly.frame_rgb(src: str, t: float) -> np.ndarray` — unchanged signature, now a wrapper.
- Consumes: `assembly.probe_stream(src).fps`, `ffbin.ffmpeg()`, `proc.run` (all already in `assembly.py`).

- [x] **Step 1: Write the failing tests**

Add to `tests/integration/test_assembly_proxy.py` (ensure the file imports `numpy as np`, `pytest`, `from PIL import Image`, and `from scripts.lib import assembly, ffbin, proc` — add any missing):

```python
def _gray_ramp_clip(tmp_path, n=10, fps=10):
    """A clip whose frame i is solid gray v=i*25 — distinct, 420-subsampling-robust."""
    src = tmp_path / "ramp"; src.mkdir()
    for i in range(n):
        v = i * 25
        Image.new("RGB", (64, 64), (v, v, v)).save(src / f"{i:03d}.png")
    clip = tmp_path / "ramp.mp4"
    proc.run([ffbin.ffmpeg(), "-y", "-framerate", str(fps), "-i", str(src / "%03d.png"),
              "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)])
    return str(clip)


@pytest.mark.integration
def test_frames_rgb_selects_exact_frames_in_input_order(tmp_path):
    clip = _gray_ramp_clip(tmp_path)
    # unsorted → frames 8, 2, 5 (gray ≈ 200, 50, 125); result stays in INPUT order
    frames = assembly.frames_rgb(clip, [0.8, 0.2, 0.5], 10.0)
    vals = [int(f.mean()) for f in frames]
    assert vals[0] > vals[2] > vals[1]                       # order preserved, not sorted
    assert abs(vals[0] - 200) < 15 and abs(vals[1] - 50) < 15 and abs(vals[2] - 125) < 15
    assert frames[0].ndim == 3 and frames[0].shape[2] == 3


@pytest.mark.integration
def test_frames_rgb_dedupes_and_empty(tmp_path):
    clip = _gray_ramp_clip(tmp_path, n=5)
    dup = assembly.frames_rgb(clip, [0.3, 0.3], 10.0)        # same frame twice
    assert len(dup) == 2 and np.array_equal(dup[0], dup[1])
    assert assembly.frames_rgb(clip, [], 10.0) == []         # no times → no decode
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_assembly_proxy.py -k frames_rgb -v`
Expected: FAIL with `AttributeError: module 'scripts.lib.assembly' has no attribute 'frames_rgb'`.

- [x] **Step 3: Implement `frames_rgb` and rewrite `frame_rgb`**

In `scripts/lib/assembly.py`, replace the current `frame_rgb` (lines 167-175) with:

```python
def frames_rgb(src: str, times: list[float], fps: float) -> list[np.ndarray]:
    """Every frame at `times` (seconds) as HxWx3 uint8 RGB arrays at `src`'s own
    resolution, in ONE decode. Frame number is round(t*fps); a select filter picks
    those exact frames in a single pass, so cost is one decode regardless of how many
    frames are asked — the O(1)-decode replacement for per-grab output seeks (design
    2026-08-02 §4). Returns a list aligned to `times`: same order and length,
    duplicate times share one decoded frame. Empty `times` → [] with no ffmpeg call.
    Uses select, never -ss, so the §12 seek landmine cannot apply."""
    if not times:
        return []
    nums = [round(t * fps) for t in times]
    uniq = sorted(set(nums))
    expr = "+".join(rf"eq(n\,{n})" for n in uniq)
    with tempfile.TemporaryDirectory() as d:
        # -vsync 0 keeps only the selected frames; image2 numbers them from 1 in
        # emission (ascending-n) order. No -ss: a select is not a cut.
        proc.run([ffbin.ffmpeg(), "-y", "-i", src, "-vf", f"select='{expr}'",
                  "-vsync", "0", "-frames:v", str(len(uniq)),
                  str(Path(d) / "f%05d.png")])
        pngs = sorted(Path(d).glob("f*.png"))
        frames = [np.asarray(Image.open(p).convert("RGB")) for p in pngs]
    if len(frames) != len(uniq):
        raise RuntimeError(
            f"frames_rgb: requested {len(uniq)} frames {uniq} but ffmpeg emitted "
            f"{len(frames)} — a frame number is past the stream end (a time >= "
            f"duration). times={times}")
    by_num = dict(zip(uniq, frames))
    return [by_num[n] for n in nums]


def frame_rgb(src: str, t: float) -> np.ndarray:
    """One frame at time `t` as an HxWx3 uint8 RGB ndarray, at `src`'s own
    resolution — a single-frame convenience over frames_rgb (probes fps to place the
    frame). For many frames call frames_rgb directly: it decodes once (design
    2026-08-02 §4). For re-extracting cast crops from the ORIGINAL (design §5)."""
    return frames_rgb(src, [t], probe_stream(src).fps)[0]
```

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_assembly_proxy.py -v`
Expected: PASS (the new `frames_rgb` tests and the existing `test_frame_rgb_returns_original_resolution_array`).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/assembly.py tests/integration/test_assembly_proxy.py
git commit -m "feat(assembly): frames_rgb — one-decode frame-accurate batch grab; frame_rgb wraps it"
```

---

### Task 1: `_cast_from_original` batches all cast grabs

**Files:**
- Modify: `scripts/intake.py` (`_cast_from_original` at lines 325-340; call site at line 304)
- Test: `tests/lib/test_intake.py` (repoint `frame_rgb` monkeypatches at lines 365, 408, 592, 604; add a batched-call assertion), `tests/integration/test_cast_pin.py` (line 174 monkeypatch + the `_cast_from_original` call)

**Interfaces:**
- Consumes: `assembly.frames_rgb(src, times, fps)` (Task 0).
- Produces: `_cast_from_original(path, best, res, pres, fps) -> list[CastEntry]` — now takes `fps` (originally 4 args; `fps` is new, last).

- [x] **Step 1: Update the cast tests to the batched interface (make them fail)**

In `tests/lib/test_intake.py`, repoint the four `frame_rgb` monkeypatches to `frames_rgb` (which returns a **list**, one array per requested time):

- Line ~365: `monkeypatch.setattr(intake.assembly, "frame_rgb", lambda s, t: orig)`
  → `monkeypatch.setattr(intake.assembly, "frames_rgb", lambda s, times, fps: [orig for _ in times])`
- Line ~408: `monkeypatch.setattr(assembly, "frame_rgb", lambda src, t: (calls.__setitem__("crop_src", src), orig_frame)[1])`
  → `monkeypatch.setattr(assembly, "frames_rgb", lambda src, times, fps: (calls.__setitem__("crop_src", src), [orig_frame for _ in times])[1])`
- Lines ~592 and ~604: `monkeypatch.setattr(intake.assembly, "frame_rgb", lambda path, t: frame)`
  → `monkeypatch.setattr(intake.assembly, "frames_rgb", lambda path, times, fps: [frame for _ in times])`

For the two tests that call `_cast_from_original` **directly** (the mask tests near lines 592/604 — `test_cast_from_original_removes_background_via_the_mask` and `test_cast_from_original_falls_back_to_maskless_when_no_mask`), add the new `fps` argument to the call, e.g. `intake._cast_from_original(path, best, res, pres, fps=30.0)` (value is irrelevant under the monkeypatch).

Add one new test asserting a single batched decode (place beside the other `_cast_from_original` tests):

```python
def test_cast_from_original_grabs_all_tracks_in_one_call(monkeypatch, tmp_path):
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    calls = {"n": 0, "times": None}
    def fake(src, times, fps):
        calls["n"] += 1; calls["times"] = list(times)
        return [frame for _ in times]
    monkeypatch.setattr(intake.assembly, "frames_rgb", fake)
    best = {1: (0.9, 1.0, (10.0, 10.0, 8.0, 8.0), None),
            2: (0.8, 2.0, (10.0, 10.0, 8.0, 8.0), None)}
    intake._cast_from_original("orig.mp4", best, res=(20, 20), pres=(20, 20), fps=30.0)
    assert calls["n"] == 1 and calls["times"] == [1.0, 2.0]   # ONE decode, both times
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -k cast -v`
Expected: FAIL — `_cast_from_original` still calls `assembly.frame_rgb` (the `frames_rgb` monkeypatch is not hit; the new arity test errors on the extra `fps` arg).

- [x] **Step 3: Rewrite `_cast_from_original` and its call site**

In `scripts/intake.py`, replace `_cast_from_original` (lines 325-340) with:

```python
def _cast_from_original(path: str, best: dict, res: tuple[int, int],
                        pres: tuple[int, int], fps: float) -> list[CastEntry]:
    """Re-crop each track's best moment from the ORIGINAL-res frame (the proxy box
    scales up by res/pres) and mask it with that track's proxy seg mask upsampled to
    the crop, so the descriptor is background-removed like delivery's (design §5a).
    All best-frames are grabbed in ONE decode (assembly.frames_rgb; design
    2026-08-02) rather than one output-seek per track. A track with no mask (mocked
    YOLO) falls back to the maskless path; a box that yields an empty crop is
    dropped."""
    scale = res[0] / pres[0]                                     # proxy→original
    items = list(best.items())
    frames = assembly.frames_rgb(path, [t for _, (_, t, _, _) in items], fps)
    out: list[CastEntry] = []
    for (tid, (conf, t, box, mask)), frame in zip(items, frames):
        crop = crop_bbox(frame, box, scale=scale)
        if crop is not None:
            m = upsample_mask(mask, crop.shape[:2]) if mask is not None else None
            out.append(CastEntry(source=Path(path).name, tid=tid, conf=conf,
                                 descriptor=build_descriptor(crop, m), crop_rgb=crop))
    return out
```

Change the call site (line 304) from `cast = _cast_from_original(path, best, res, pres)` to:

```python
        cast = _cast_from_original(path, best, res, pres, info.fps)   # crops from the ORIGINAL
```

- [x] **Step 4: Repoint the integration cast-pin test**

In `tests/integration/test_cast_pin.py` (line ~174), change:
`monkeypatch.setattr(intake.assembly, "frame_rgb", lambda path, t: rgb)`
→ `monkeypatch.setattr(intake.assembly, "frames_rgb", lambda path, times, fps: [rgb for _ in times])`
and update the call on the next lines to pass `fps` (any value, monkeypatched): `intake._cast_from_original("orig.mp4", best, res=(200, 200), pres=(200, 200), fps=30.0)`.

- [x] **Step 5: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -k cast tests/integration/test_cast_pin.py -v`
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add scripts/intake.py tests/lib/test_intake.py tests/integration/test_cast_pin.py
git commit -m "feat(intake): _cast_from_original grabs every track in one frames_rgb decode"
```

---

### Task 2: intake phash batches; delete `_phash_at`

**Files:**
- Modify: `scripts/intake.py` (phash line 303; delete `_phash_at` lines 173-175; import comment line 20)
- Test: `tests/lib/test_intake.py` (the `_process_clip` tests already exercise this once Task 1's `frames_rgb` monkeypatch is in place)

**Interfaces:**
- Consumes: `assembly.frames_rgb(src, times, fps)` (Task 0), `imagehash.phash`, `Image.fromarray` (both already imported in `intake.py`), `check_reel._hamming` (kept, used by `cull`).
- Produces: no new symbol; removes `intake._phash_at`.

- [x] **Step 1: Check `_phash_at` has no test references**

Run: `grep -rn "_phash_at" tests/ scripts/`
Expected: only `scripts/intake.py:303` (call) and `:173` (def). If a test references it, update that test to call `_process_clip` instead. (No production caller besides line 303.)

- [x] **Step 2: Batch the phash grab**

In `scripts/intake.py`, replace the phash line (303):

```python
        phashes = [str(_phash_at(src, w.start + w.dur / 2)) for w in windows]
```

with a single batched decode of all window midpoints from the proxy:

```python
        mids = [w.start + w.dur / 2 for w in windows]
        phashes = [str(imagehash.phash(Image.fromarray(f)))
                   for f in assembly.frames_rgb(src, mids, info.fps)]
```

- [x] **Step 3: Delete `_phash_at` and fix the import comment**

Remove `_phash_at` (lines 173-175):

```python
def _phash_at(clip: str, t: float) -> imagehash.ImageHash:
    return check_reel._phash_bits(clip, t)             # reuse the reel-variety phash
```

Update the `check_reel` import comment (line 20) — `_phash_bits` is no longer used by intake, `_hamming` still is (in `cull`, line 189):

```python
from scripts import check_reel                    # reuse _hamming for cull dedup
```

- [x] **Step 4: Run the intake unit suite**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -v`
Expected: PASS. The `_process_clip` tests route phash through the `frames_rgb` monkeypatch from Task 1 (`Image.fromarray` accepts the fake uint8 array those tests supply).

- [x] **Step 5: Commit**

```bash
git add scripts/intake.py
git commit -m "feat(intake): window phashes batch through frames_rgb; drop per-grab _phash_at"
```

---

### Task 3: `CACHE_VERSION` 4→5 + real-ffmpeg golden re-pin

**Files:**
- Modify: `scripts/lib/intake_cache.py` (line 34 + the version-comment sentence)
- Test: `tests/lib/test_intake_cache.py` (the version test), `tests/integration/test_intake.py` and `tests/integration/test_intake_proxy.py` (re-pin any real-decode phash/descriptor values that moved by ≤1 frame)

**Interfaces:**
- Consumes: nothing new.
- Produces: `intake_cache.CACHE_VERSION == 5`.

- [x] **Step 1: Bump the cache version test (make it fail)**

In `tests/lib/test_intake_cache.py`, find the version assertion (currently `== 4`, in a test named like `test_cache_version_is_four...` / `..._v4`) and change it to `5` (rename the test's `four`/`v4` to `five`/`v5` to match).

- [x] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_intake_cache.py -k version -v`
Expected: FAIL (`assert 4 == 5`).

- [x] **Step 3: Bump `CACHE_VERSION`**

In `scripts/lib/intake_cache.py` (line 34), change `CACHE_VERSION = 4` to `CACHE_VERSION = 5`. Update the adjacent version-history comment sentence to add: the 4→5 bump is the frame-grab batch (design 2026-08-02) — cast descriptors and window phashes shift by ≤1 frame because `frames_rgb` selects `round(t*fps)` where output-seek grabbed the first frame with `pts >= t`.

- [x] **Step 4: Re-pin the real-ffmpeg intake goldens**

Run the intake integration tests: `.venv/bin/python -m pytest tests/integration/test_intake.py tests/integration/test_intake_proxy.py -v`

For any assertion that fails on a **real-decode** phash hex or descriptor value (not a structural/shape assertion), update the pinned literal to the value the test now produces. These moved by ≤1 frame by design (§7). Do **not** loosen a structural assertion to hide a real regression — only re-pin exact value literals that shifted. If a test monkeypatches the frame grab (no real decode), it will not move; leave it.

- [x] **Step 5: Run to verify all pass**

Run: `.venv/bin/python -m pytest tests/lib/test_intake_cache.py tests/integration/test_intake.py tests/integration/test_intake_proxy.py -v`
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add scripts/lib/intake_cache.py tests/lib/test_intake_cache.py tests/integration/test_intake.py tests/integration/test_intake_proxy.py
git commit -m "feat(intake): CACHE_VERSION 4->5 for the frame-grab batch; re-pin real goldens"
```

---

### Task 4: docs sync, full suite, measurement re-run

**Files:**
- Modify: `CLAUDE.md` (Quick Reference registry — add the design + plan rows), `docs/build-status.md` (a "Done" bullet)
- No test file; the deliverable is a green whole suite + a recorded before/after.

**Interfaces:** none.

- [x] **Step 1: Add the registry rows to `CLAUDE.md`**

In the Quick Reference table, add two rows near the intake-analysis-proxy rows:

```markdown
| Intake frame-grab batch design | [2026-08-02-intake-frame-grab-batch-design.md](docs/specs/2026-08-02-intake-frame-grab-batch-design.md) | Profiling found the frame GRABS, not the transcode, dominate intake: `_cast_from_original` hung >480s (per-track output-seek 4K, cost linear in timestamp), phash 15s. New `assembly.frames_rgb(src, times, fps)` selects exact frames in ONE decode (O(1) decodes); cast + phash route through it, `check_reel`/`storyboard` untouched. Lint already exempts a `-frames:v` still grab; batch uses `select`, no `-ss`. ≤1-frame shift → `CACHE_VERSION` 4→5. YOLO floor + VideoToolbox transcode deferred. |
| Intake frame-grab batch plan | [2026-08-02-intake-frame-grab-batch.md](docs/plans/2026-08-02-intake-frame-grab-batch.md) | Tasks 0–4: `frames_rgb` + `frame_rgb` wrapper (real-ffmpeg), `_cast_from_original` one-decode batch, phash batch + `_phash_at` delete, `CACHE_VERSION` 4→5 + golden re-pin, docs sync + measurement re-run. |
```

- [x] **Step 2: Add the build-status bullet**

In `docs/build-status.md`, under the most recent "Done" grouping, add:

```markdown
- **Done (2026-08-02):** Intake frame-grab batch — `assembly.frames_rgb` selects
  exact frames in one decode; `_cast_from_original` (was O(N) output-seeks on the
  4K original, the >480s hotspot) and window phashes now O(1) decodes. `frame_rgb`
  wraps `frames_rgb`; `_phash_at` deleted; `check_reel`/`storyboard` untouched.
  `CACHE_VERSION` 4→5, real goldens re-pinned. Design/plan 2026-08-02.
```

- [x] **Step 3: Full suite green**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (bar pre-existing skips). Fix any fallout before committing.

- [x] **Step 4: Re-run the measurement (before/after evidence)**

Re-run the per-phase harness on the same drone clip used to justify the slice and record cast + phash wall-time:

Run: `.venv/bin/python /private/tmp/claude-501/-Users-serg-git-video-grid/22776fd7-f4d7-4fc5-83ee-630c6be93955/scratchpad/measure_intake.py`

Record the new `_cast_from_original` and `phash` phase times against the pre-fix baseline (cast >480s hung → expect ~one 4K decode; phash 15.3s → expect a few s) in the commit body. If the harness path is gone, a fresh `intake()` run on a folder holding that clip with wall timing is an acceptable substitute.

- [x] **Step 5: Commit**

```bash
git add CLAUDE.md docs/build-status.md
git commit -m "docs(intake): register frame-grab batch slice; record before/after timings"
```

---

## Notes for the implementer

- **`best` tuple shape** is `(conf, t, box, mask)` (4-tuple) — the unpacking `for _, (_, t, _, _) in items` and `for (tid, (conf, t, box, mask)), frame in zip(...)` depend on it. If a test stub still uses a 3-tuple it predates the mask-symmetry slice and must gain a trailing `, None`.
- **Do not touch** `check_reel._sample_frame` / `_frame_mean` / `_phash_bits` or `storyboard._sample_frames` — reels need output-seek frame-accuracy at cut boundaries and are short enough that speed is a non-issue (design §6).
- **Landmine check:** `frames_rgb` emits `-frames:v <k>` and no `-ss`; `scripts/lib/lint.py` `check_argv` must stay clean on it (the proc.run guard runs it automatically on every call a test exercises).
