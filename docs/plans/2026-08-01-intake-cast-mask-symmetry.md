# Intake cast-descriptor mask symmetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the intake↔delivery cast-descriptor mask symmetry the analysis-proxy slice broke — intake builds MASKED descriptors again (background removed, like delivery), by threading each track's proxy-scale YOLO seg mask through `_people_timeline`'s `best` refs and upsampling it onto the original crop.

**Architecture:** Delivery (`track._track_crops`) builds a descriptor from the crop's segmentation-mask pixels only (§6.1a: identity = clothing colour, not location). Intake shipped maskless after the proxy slice — an asymmetry that shifts the L1 distance one-sidedly and can flip a hero match. Fix: a shared `appearance.seg_mask` extractor (refactored out of `crop_and_mask`), a proxy-mask captured in `_people_timeline`'s per-track `best` (mask only, no pixels), and `appearance.upsample_mask` applied in `_cast_from_original` so the descriptor is background-removed at full res. The intake mask (proxy-YOLO, upsampled) is not the pixel twin of delivery's (original-YOLO) — but both are background-removed clothing histograms, the same proxy-scale equivalence §4 already accepted.

**Tech Stack:** Python 3.13 (`.venv/bin/python`), numpy + Pillow (no cv2 in appearance), pytest (`pytest.ini` `pythonpath = .`, run modules never scripts). Design: [docs/specs/2026-08-01-intake-analysis-proxy-design.md](../specs/2026-08-01-intake-analysis-proxy-design.md) §5 + §5a (already written).

**Landmines (unchanged by this slice):** no new ffmpeg argv is introduced — `seg_mask`/`upsample_mask` are Pillow-only, `frame_rgb` already uses `-ss` after `-i`. `lutrgb` untouched. So `lib/ffbin`/the landmine lint need no changes.

**Branch:** `feat/intake-cast-mask-symmetry` off `main` (38c68ba). Commit bodies end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Do NOT push; do NOT run installers.

---

### Task 0: `appearance.seg_mask` + refactor `crop_and_mask` + `upsample_mask`

**Files:**
- Modify: `scripts/lib/appearance.py`
- Test: `tests/lib/test_appearance.py`

One spelling of "model-space seg mask → resize to frame dims → crop to bbox" (the resize-landmine crop_and_mask carries), plus a proxy→crop upsampler. `crop_and_mask`'s public behaviour is unchanged — its existing tests must stay green.

- [x] **Step 1: Write the failing tests**

Add to `tests/lib/test_appearance.py` (module already imports `numpy as np`, `pytest`, `appearance`):

```python
class _Masks:
    def __init__(self, data): self.data = data


class _ResM:
    def __init__(self, orig_img, masks): self.orig_img = orig_img; self.masks = _Masks(masks)


class _BoxM:
    def __init__(self, xywh): self.xywh = [xywh]


def test_seg_mask_resizes_model_space_and_crops_to_bbox():
    # frame 40x40; model-space mask 20x20 (half) with a person blob → seg_mask
    # resizes the mask up to frame dims and crops it to the box's bbox
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    m = np.zeros((20, 20), dtype=np.float32)
    m[5:15, 5:10] = 1.0                                  # model-space blob
    box = _BoxM([20.0, 20.0, 20.0, 20.0])                # centre (20,20) → bbox [10:30, 10:30]
    mask = appearance.seg_mask(_ResM(frame, [m]), 0, box)
    assert mask.shape == (20, 20)                        # cropped to the bbox
    assert mask.max() > 0                                # the blob survived resize + crop


def test_seg_mask_is_none_without_masks_or_frame():
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    assert appearance.seg_mask(_ResM(frame, None), 0, _BoxM([4, 4, 4, 4])) is None
    assert appearance.seg_mask(_ResM(None, [np.ones((4, 4), np.float32)]), 0, _BoxM([4, 4, 4, 4])) is None


def test_upsample_mask_matches_target_shape():
    small = np.zeros((10, 5), dtype=np.uint8)
    small[2:8, 1:4] = 255
    up = appearance.upsample_mask(small, (200, 80))
    assert up.shape == (200, 80)
    assert up.max() > 0 and up.min() == 0                # foreground survived, corners stay bg
```

- [x] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_appearance.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'seg_mask'` / `'upsample_mask'`.

- [x] **Step 3: Implement**

In `scripts/lib/appearance.py`, add a shared bbox helper + `seg_mask`, refactor `crop_and_mask` to reuse both, and add `upsample_mask`. Replace the existing `crop_and_mask` (lines 71-88) with:

```python
def _bbox_ltrb(box: object) -> tuple[int, int, int, int]:
    """Clamp a box's centre-format xywh to integer (l, t, r, b), left/top >= 0.
    One spelling, shared by crop_and_mask and seg_mask so the crop and its mask
    are cut to the SAME rectangle."""
    x, y, w, h = (float(v) for v in box.xywh[0])
    l, t, r_, b_ = int(x - w / 2), int(y - h / 2), int(x + w / 2), int(y + h / 2)
    return max(0, l), max(0, t), r_, b_


def seg_mask(res: object, idx: int, box: object) -> np.ndarray | None:
    """The segmentation mask for detection `idx`, resized from model space up to the
    result's frame dims and cropped to `box`'s bbox — the mask half of crop_and_mask,
    extracted so intake (which crops pixels from the ORIGINAL, not this frame) can
    reuse the exact same resize+crop. None when the result carries no frame or masks
    (a mocked result), which is how the maskless fallback stays reachable."""
    img = getattr(res, "orig_img", None)
    masks = getattr(res, "masks", None)
    if img is None or masks is None or getattr(masks, "data", None) is None:
        return None
    arr = np.asarray(img)
    l, t, r_, b_ = _bbox_ltrb(box)
    m = np.asarray(masks.data[idx])                        # (H, W) in model space
    m = np.asarray(Image.fromarray((m * 255).astype("uint8")).resize((arr.shape[1], arr.shape[0])))
    return m[t:b_, l:r_]


def crop_and_mask(res: object, idx: int, box: object) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Extract the box's crop (RGB) + seg mask from an ultralytics result. Returns
    (None, None) when the frame image is unavailable (mocked tests); the mask alone
    is None when only masks are absent. The mask is extracted by seg_mask, so the
    model-space resize lives in one place."""
    img = getattr(res, "orig_img", None)
    if img is None:
        return None, None
    arr = np.asarray(img)[..., ::-1]                       # ultralytics orig_img is BGR → RGB
    l, t, r_, b_ = _bbox_ltrb(box)
    crop = arr[t:b_, l:r_]
    return (crop if crop.size else None), seg_mask(res, idx, box)


def upsample_mask(mask: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Resize a proxy-scale bbox mask up to `shape` (H, W) — the original crop's — so
    build_descriptor masks the same region at full res (design §5a). Same PIL resize
    crop_and_mask uses (default resampling), because build_descriptor thresholds
    `mask > 0`; PIL's resize takes (W, H)."""
    h, w = shape
    return np.asarray(Image.fromarray(mask.astype("uint8")).resize((w, h)))
```

- [x] **Step 4: Run the whole appearance suite**

Run: `.venv/bin/python -m pytest tests/lib/test_appearance.py tests/lib/test_intake.py -q`
Expected: PASS — new tests green AND the existing `test_crop_and_mask_*` / `test_crop_and_mask_rgb_and_aligned_mask` unchanged (behaviour preserved by the refactor).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/appearance.py tests/lib/test_appearance.py
git commit -m "feat(appearance): seg_mask extractor + upsample_mask; crop_and_mask reuses them"
```

---

### Task 1: `_people_timeline` captures the proxy seg mask into `best`

**Files:**
- Modify: `scripts/intake.py` (import line 22; `_people_timeline` lines 145-167)
- Test: `tests/lib/test_intake.py`

`best[tid]` grows from `(conf, t, bbox)` to `(conf, t, bbox, seg_mask)`. Mask captured only on confidence improvement (≈ once per track), never per frame; None for a mocked result with no masks.

- [x] **Step 1: Write the failing test**

Add to `tests/lib/test_intake.py` (it already imports `numpy as np`, `intake`, `appearance`; it defines a `_FakeBox` — if that fake lacks `conf`/`id`, define the local fakes below rather than reuse it):

```python
class _MaskTLBox:
    def __init__(self, xywh, tid, conf):
        self.xywh = [xywh]; self.id = [tid]; self.conf = [conf]


class _MaskTLMasks:
    def __init__(self, data): self.data = data


class _MaskTLRes:
    def __init__(self, boxes, orig_img, masks):
        self.boxes = boxes; self.orig_img = orig_img; self.masks = _MaskTLMasks(masks)


def test_people_timeline_captures_the_seg_mask_into_best(monkeypatch):
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    m = np.zeros((20, 20), dtype=np.float32); m[5:15, 5:10] = 1.0
    res = _MaskTLRes([_MaskTLBox([20.0, 20.0, 20.0, 20.0], 7, 0.9)], frame, [m])
    monkeypatch.setattr(intake, "_iter_seg", lambda src, **k: iter([(0, res)]))
    _timeline, best = intake._people_timeline("x.mp4", fps=30.0, res=(40, 40), sample_fps=3.0)
    conf, t, bbox, mask = best[7]                        # the 4-tuple, mask last
    assert conf == 0.9 and bbox == (20.0, 20.0, 20.0, 20.0)
    assert mask is not None and mask.shape == (20, 20)
```

- [x] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py::test_people_timeline_captures_the_seg_mask_into_best -q`
Expected: FAIL — `ValueError: not enough values to unpack (expected 4, got 3)`.

- [x] **Step 3: Implement**

In `scripts/intake.py` line 22, add `seg_mask` to the import:

```python
from scripts.lib.appearance import build_descriptor, crop_bbox, descriptor_dist, seg_mask
```

Rewrite `_people_timeline` (lines 145-167). Update the docstring's `best:` line + the "Cheap" line, enumerate the boxes, and append the mask:

```python
def _people_timeline(src: str, fps: float, res: tuple[int, int],
                     sample_fps: float = SAMPLE_FPS) -> tuple[list, dict]:
    """One seg pass → (timeline, best_by_track).
    timeline: [(t, people, primary_bbox, track_ids)] sampled at ~SAMPLE_FPS (primary = largest bbox).
    best: {tid: (conf, t, bbox_xywh, seg_mask)} — the timestamp + PROXY box + PROXY-scale
    seg mask of each track's highest-confidence detection, so the cast pass can re-crop that
    exact moment from the ORIGINAL and mask it like delivery (design 2026-08-01 §5/§5a).
    Cheap: records a REF (a float + four numbers) plus one small proxy-bbox mask per track
    (mask only via seg_mask, never the full crop), updated on confidence improvement — not
    per frame."""
    step = max(1, round(fps / sample_fps))
    timeline, best = [], {}                      # best: tid -> (conf, t, bbox_xywh, seg_mask)
    for i, r in _iter_seg(src):
        boxes = list(r.boxes) if getattr(r, "boxes", None) is not None else []
        for j, b in enumerate(boxes):
            tid = int(b.id[0]) if getattr(b, "id", None) is not None else None
            conf = float(b.conf[0]) if getattr(b, "conf", None) is not None else 1.0
            if tid is not None and conf > best.get(tid, (-1.0,))[0]:
                best[tid] = (conf, i / fps, tuple(float(v) for v in b.xywh[0]), seg_mask(r, j, b))
        if i % step:
            continue
        bbs = [tuple(float(v) for v in b.xywh[0]) for b in boxes]
        primary = max(bbs, key=lambda bb: bb[2] * bb[3]) if bbs else None
        tids = sorted({int(b.id[0]) for b in boxes if getattr(b, "id", None) is not None})
        timeline.append((i / fps, len(bbs), primary, tids))
    return timeline, best
```

- [x] **Step 4: Run it**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -q`
Expected: PASS (new test + existing lib intake tests).

Note: `_cast_from_original` still unpacks a 3-tuple at this point → the integration goldens fail until Task 2. That is expected mid-slice; the next task fixes it in the same working tree.

- [x] **Step 5: Commit**

```bash
git add scripts/intake.py tests/lib/test_intake.py
git commit -m "feat(intake): _people_timeline captures each track's proxy seg mask into best"
```

---

### Task 2: `_cast_from_original` builds a masked descriptor + `CACHE_VERSION` bump

**Files:**
- Modify: `scripts/intake.py` (import line 22; `_cast_from_original` lines 322-334)
- Modify: `scripts/lib/intake_cache.py` (`CACHE_VERSION` line 31 + comment lines 24-30)
- Test: `tests/lib/test_intake.py`

The crop still comes from the ORIGINAL frame; when a mask is present it is upsampled to the crop and passed to `build_descriptor`, else the maskless fallback (mocked YOLO). The real-footage descriptor changes shape → `CACHE_VERSION` 3→4 in the same commit.

- [x] **Step 1: Write the failing tests**

Add to `tests/lib/test_intake.py`:

```python
def test_cast_from_original_removes_background_via_the_mask(monkeypatch):
    # bbox = frame[10:30, 10:30]; red clothing fills its left, blue background its
    # right; the mask covers only the clothing → descriptor must be the pure-red one,
    # NOT the maskless (background-polluted) bbox histogram
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    frame[10:30, 10:25] = (250, 0, 0)                    # red clothing (RGB), left of bbox
    frame[10:30, 25:30] = (0, 0, 250)                    # blue background, right of bbox
    monkeypatch.setattr(intake.assembly, "frame_rgb", lambda path, t: frame)
    proxy_mask = np.zeros((10, 10), dtype=np.uint8); proxy_mask[:, :5] = 255   # left half
    best = {1: (0.9, 0.5, (20.0, 20.0, 20.0, 20.0), proxy_mask)}   # scale 1 (res == pres)
    cast = intake._cast_from_original("x.mp4", best, res=(40, 40), pres=(40, 40))
    red_only = intake.build_descriptor(np.full((20, 10, 3), (250, 0, 0), np.uint8), None)
    assert appearance.descriptor_dist(cast[0].descriptor, red_only) < 1e-9      # background gone
    maskless = intake.build_descriptor(frame[10:30, 10:30], None)
    assert appearance.descriptor_dist(cast[0].descriptor, maskless) > 0.1       # and NOT the polluted one


def test_cast_from_original_falls_back_to_maskless_when_no_mask(monkeypatch):
    frame = np.full((40, 40, 3), (250, 0, 0), dtype=np.uint8)
    monkeypatch.setattr(intake.assembly, "frame_rgb", lambda path, t: frame)
    best = {1: (0.9, 0.5, (20.0, 20.0, 20.0, 20.0), None)}         # no mask (mocked YOLO)
    cast = intake._cast_from_original("x.mp4", best, res=(40, 40), pres=(40, 40))
    assert cast[0].descriptor == intake.build_descriptor(frame[10:30, 10:30], None)
```

Add to `tests/lib/test_intake_cache.py` (asserts the analysis-proxy basis moved again):

```python
def test_cache_version_is_four_for_the_masked_cast_descriptor():
    # masked intake descriptor (design §5a) changes the cached shape → v3 must miss
    from scripts.lib import intake_cache
    assert intake_cache.CACHE_VERSION == 4
```

- [x] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py -k cast_from_original tests/lib/test_intake_cache.py::test_cache_version_is_four_for_the_masked_cast_descriptor -q`
Expected: FAIL — `_cast_from_original` unpacks a 3-tuple (`ValueError`) / `CACHE_VERSION == 3`.

- [x] **Step 3: Implement**

In `scripts/intake.py` line 22, extend the import:

```python
from scripts.lib.appearance import build_descriptor, crop_bbox, descriptor_dist, seg_mask, upsample_mask
```

Rewrite `_cast_from_original` (lines 322-334):

```python
def _cast_from_original(path: str, best: dict, res: tuple[int, int],
                        pres: tuple[int, int]) -> list[CastEntry]:
    """Re-crop each track's best moment from the ORIGINAL-res frame (the proxy box
    scales up by res/pres) and mask it with that track's proxy seg mask upsampled to
    the crop, so the descriptor is background-removed like delivery's (design §5a).
    A track with no mask (mocked YOLO) falls back to the maskless path; a box that
    yields an empty crop is dropped."""
    scale = res[0] / pres[0]                                     # proxy→original
    out: list[CastEntry] = []
    for tid, (conf, t, box, mask) in best.items():
        crop = crop_bbox(assembly.frame_rgb(path, t), box, scale=scale)
        if crop is not None:
            m = upsample_mask(mask, crop.shape[:2]) if mask is not None else None
            out.append(CastEntry(source=Path(path).name, tid=tid, conf=conf,
                                 descriptor=build_descriptor(crop, m), crop_rgb=crop))
    return out
```

In `scripts/lib/intake_cache.py`, bump `CACHE_VERSION` (line 31) to `4` and extend the comment (lines 24-30) with one sentence:

```python
# ... the analysis-proxy
# slice bumps it again (v2 → v3: analysis runs on a downscaled proxy, so a v2 result
# — computed on full-res — must miss, design 2026-08-01). The cast-mask-symmetry
# follow-up bumps it once more (v3 → v4: the cast descriptor is masked again — the
# proxy seg mask upsampled onto the original crop — so a v3 maskless descriptor must
# miss, design §5a). An all-or-nothing version beats a per-field logic hash nobody
# can audit.
CACHE_VERSION = 4
```

- [x] **Step 4: Run the intake suite (unit + integration)**

Run: `.venv/bin/python -m pytest tests/lib/test_intake.py tests/lib/test_intake_cache.py tests/integration/test_intake.py -q`
Expected: PASS. The `test_intake.py` integration goldens are UNCHANGED — its fake YOLO (`_FakeRes.masks = None`) → `seg_mask` returns None → maskless fallback → identical descriptors and the same `FootageClip` goldens.

- [x] **Step 5: Commit**

```bash
git add scripts/intake.py scripts/lib/intake_cache.py tests/lib/test_intake.py tests/lib/test_intake_cache.py
git commit -m "feat(intake): cast descriptors masked again (proxy mask upsampled); CACHE_VERSION 3→4"
```

---

### Task 3: real-pixel symmetry proof — intake ↔ delivery descriptors agree after masking

**Files:**
- Test: `tests/integration/test_cast_pin.py`

The equivalence proof (analogous to §4's shake exercise): for the SAME person on a background, intake's `_cast_from_original` descriptor and delivery's `crop_and_mask`+`build_descriptor` descriptor land within `CAST_MATCH`, while the pre-fix maskless intake descriptor is measurably FARTHER. The existing `_Res` fixture fills the whole bbox with one colour (no background inside the box), so this test builds its own person-on-background fixture.

- [x] **Step 1: Write the failing test**

Add to `tests/integration/test_cast_pin.py` (it already imports `numpy as np`, `pytest`, `intake`, `track`, `appearance`; reuse its module-level `_Masks`):

```python
class _BoxC:
    def __init__(self, xywh, tid, conf):
        self.xywh = [xywh]; self.id = [tid]; self.cls = [0]; self.conf = [conf]


class _ResC:
    """A person occupying the LEFT half of its bbox on a differently-coloured
    background filling the RIGHT half, with a model-space mask over the person only
    — so masking is NOT a no-op (unlike _Res, whose bbox is one flat colour)."""
    def __init__(self):
        W, H = 200, 200
        img = np.zeros((H, W, 3), dtype=np.uint8)        # BGR, like ultralytics orig_img
        img[40:160, 40:100] = (0, 0, 220)                # red person (BGR), left of bbox
        img[40:160, 100:160] = (0, 220, 0)               # green background, right of bbox
        m = np.zeros((H // 2, W // 2), dtype=np.float32)  # model space (half source)
        m[20:80, 20:50] = 1.0                            # person half only
        self.orig_img = img
        self.masks = _Masks([m])
        self.boxes = [_BoxC([100.0, 100.0, 120.0, 120.0], 1, 0.95)]   # bbox [40:160, 40:160]


@pytest.mark.integration
def test_intake_and_delivery_cast_descriptors_agree_after_masking(monkeypatch):
    r = _ResC()
    box = r.boxes[0]
    # delivery: crop_and_mask (BGR→RGB + model-mask resize) → masked descriptor
    crop_rgb, mask = appearance.crop_and_mask(r, 0, box)
    delivery = appearance.build_descriptor(crop_rgb, mask)
    # intake: same person, crop from the ORIGINAL (here the same frame, RGB), proxy
    # mask via seg_mask, upsampled inside _cast_from_original
    rgb = np.asarray(r.orig_img)[..., ::-1]
    monkeypatch.setattr(intake.assembly, "frame_rgb", lambda path, t: rgb)
    best = {1: (0.95, 0.0, tuple(float(v) for v in box.xywh[0]), appearance.seg_mask(r, 0, box))}
    cast = intake._cast_from_original("orig.mp4", best, res=(200, 200), pres=(200, 200))
    intake_desc = cast[0].descriptor
    # symmetric: the two masked descriptors match well within the cast gate
    assert appearance.descriptor_dist(intake_desc, delivery) < appearance.CAST_MATCH
    # and the pre-fix maskless bbox descriptor is measurably FARTHER — the regression
    l, t, r_, b_ = 40, 40, 160, 160
    maskless = appearance.build_descriptor(rgb[t:b_, l:r_], None)
    assert (appearance.descriptor_dist(maskless, delivery)
            > appearance.descriptor_dist(intake_desc, delivery))
```

- [x] **Step 2: Run it to verify it fails, then passes**

Run: `.venv/bin/python -m pytest tests/integration/test_cast_pin.py -q`
Expected: PASS once Tasks 0-2 are in (the test exercises the shipped code, not new production code). If it fails, the fix is wrong — debug before proceeding, do not weaken the assertion.

- [x] **Step 3: Commit**

```bash
git add tests/integration/test_cast_pin.py
git commit -m "test(intake): real-pixel proof intake↔delivery cast descriptors agree after masking"
```

---

### Task 4: docs sync + track mirror docstring + full suite + final review

**Files:**
- Modify: `scripts/track.py` (`_track_crops` docstring, lines 287-293)
- Modify: `CLAUDE.md` (intake analysis proxy registry row)
- Modify: `docs/build-status.md` (changelog line)
- (Design §5/§5a already amended — verify, do not rewrite.)

- [x] **Step 1: Correct the delivery mirror docstring**

`scripts/track.py` `_track_crops` says it "Mirrors intake._people_timeline: one crop_and_mask per confidence improvement". Intake now uses `seg_mask` (mask only; the crop comes from the original later). Update that sentence for accuracy:

```python
    Mirrors intake._people_timeline, which now captures the mask alone (seg_mask,
    once per confidence improvement) and crops pixels from the original later; here
    the crop and mask come together via crop_and_mask, since delivery already has the
    source frame. crop_and_mask carries the two landmines — ultralytics' orig_img is
    BGR, and the mask is in model space and must be resized to source dims — and
    returns (None, None) for a mocked result with no pixels, which is how every track
    test drives this.
```

- [x] **Step 2: Sync the registry + build-status**

In `CLAUDE.md`, the intake-analysis-proxy design row ends with the cast-crop note; append that the cast descriptor is masked via the proxy mask upsampled (design §5a), so intake/delivery stay symmetric. In `docs/build-status.md`, add a changelog line dated 2026-08-01: cast-descriptor mask symmetry restored (intake masks again via the proxy seg mask upsampled; `CACHE_VERSION` 3→4). Keep both edits to one line each — this is a registry, detail lives in the design.

- [x] **Step 3: Verify the design doc already carries §5a**

Run: `grep -n "5a. Cast descriptor mask symmetry" docs/specs/2026-08-01-intake-analysis-proxy-design.md`
Expected: one hit. If missing, the brainstorm amendment was lost — re-add per the design (it was written during brainstorming); otherwise do not edit.

- [x] **Step 4: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass / prior skips only (the analysis-proxy baseline was 2066 passed / 2 skipped; this slice adds tests, moves no golden). If the run exceeds the tool timeout, split: `.venv/bin/python -m pytest -q -m "not integration"` then `.venv/bin/python -m pytest -q -m integration`.

- [x] **Step 5: Commit**

```bash
git add scripts/track.py CLAUDE.md docs/build-status.md
git commit -m "docs(intake): cast-mask symmetry — registry, build-status, track mirror docstring"
```

- [x] **Step 6: Final whole-slice review**

Dispatch a fresh reviewer subagent (superpowers:requesting-code-review) over `main..HEAD`: verify (1) intake builds a MASKED descriptor on real masks and the maskless fallback survives for mocked YOLO; (2) `crop_and_mask` behaviour is unchanged by the refactor; (3) `CACHE_VERSION` bumped and no test pins the literal `3`; (4) the integration proof genuinely exercises `_cast_from_original` (not a re-assertion of `build_descriptor`); (5) no new ffmpeg argv / landmine. Then superpowers:finishing-a-development-branch.

---

## Self-Review

- **Spec coverage:** §5a's mechanism steps 1-4 map to Tasks 1 (capture), 0 (`seg_mask`/`upsample_mask`), 2 (apply + cache). The "restore symmetry, not maskless-both" decision is realized (delivery untouched; intake re-masked). The honest-limit (proxy mask ≠ delivery mask) is asserted only as "within CAST_MATCH", never pixel-equality — Task 3.
- **Placeholders:** none — every code step carries full code.
- **Type consistency:** `best[tid]` is a 4-tuple `(conf, t, bbox, mask)` produced in Task 1, consumed in Task 2; `seg_mask`/`upsample_mask` signatures match their call sites; `CACHE_VERSION` is an int.
- **Golden stability:** the `test_intake.py` integration fixture has `masks = None` → maskless fallback → the `FootageClip` goldens do not move (verified: they assert shake/motion/shot_type/score, not descriptors). Only the cache version changes, and every cache test writes fresh in tmp_path.
