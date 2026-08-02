# Intake frame-grab batch — one decode for all cast crops and window phashes

**Status:** design approved 2026-08-02.

The analysis-proxy slice (2026-08-01) killed the `vidstabdetect` wall and collapsed
three 4K decodes into one for the *analysis* passes. It left the **frame grabs**
untouched, and profiling the finished pipeline on real 4K footage shows they are
now the dominant cost — one of them pathologically so. This slice routes intake's
two frame-grab consumers — cast crops (from the original) and per-window phashes
(from the proxy) — through **one batched, frame-accurate decode** each, instead of
one full decode per grab.

## 1. The cost that forces this (measured)

One real 4K/60 HEVC drone clip (`3840×2160`, 35.5 s), `_process_clip`, `jobs=1`,
on the M4 Pro:

| phase | wall | note |
|-------|------|------|
| `make_proxy` (libx264) | 12.0 s | 137 s **CPU** — saturates all P-cores |
| `scene_bounds` | 0.8 s | |
| `_people_timeline` (YOLO) | **78.8 s** | the compute floor; GPU/MPS |
| `vidstab.detect` | 9.8 s | |
| `phash` (per window) | **15.3 s** | slow-seek on the proxy |
| `_cast_from_original` | **> 480 s (hung)** | ~50 tracks × slow-seek 4K grab |

The run did not finish inside a 10-minute timeout — it was still inside
`_cast_from_original`, issuing one `ffmpeg -i <4K> -ss <t> -frames:v 1` per track.

**The frame grab, not the transcode, is the bottleneck.** The transcode the
optimization discussion started from (12 s) is fourth on this list. The two grab
phases together are the whole tail.

### 1.1 Why the grab is slow — seek microbench

Cost of one 4K frame grab, measured across the clip:

| method | cost | vs slow |
|--------|------|:-------:|
| slow (`-ss` **after** `-i`, current `frame_rgb`/`_sample_frame`) | 3.2 s → 15.1 s, **grows with position**, avg 9.3 s | 1× |
| fast (`-ss` **before** `-i`, keyframe-approx) | flat ~2.4 s | 3.9× |
| fast+accurate (coarse `-ss` before + fine `-ss` after) | flat ~3.15 s, exact frame | 2.9× |
| **one-pass batch** (`select`, single decode) | 11.6 s for 6 = **1.93 s/frame** | 4.8× |

Output seek (`-ss` after `-i`) decodes from the start to `t`, so its cost is
**linear in the timestamp**. Times the number of tracks — spread across the clip —
that is minutes. This is the whole disease.

The batch column is the key one: **one decode emits all requested frames**, so its
per-frame cost falls as the count rises. For N grabs its total is ~one full decode
(fixed), where slow-seek is N × (avg position).

## 2. Decision — batch, one decode per consumer (approach B)

Three approaches were on the table:

- **A — fast-seek per grab.** `-ss` before `-i`, 3.9×/grab, but still **O(N)
  decodes**: 50 tracks × 2.4 s ≈ 120 s. Simple, but does not kill the cast monster
  — the cost stays linear in track count.
- **B — batch (chosen).** A new `assembly.frames_rgb(src, times, fps)` primitive:
  **one** `select`-filter pass returns every requested frame, **O(1) decodes**
  regardless of count. cast ≈ one 4K decode (~12 s) for any N; phash ≈ one proxy
  decode. Both consumers share the primitive.
- **C — hybrid.** batch cast + fast-seek phash. Pragmatic, less uniform.

**B** wins on three counts beyond speed:

1. **Frame-accurate.** `select='eq(n,N)'` decodes the whole stream and picks frame
   `N` exactly — not the keyframe-approximate frame that fast-seek (`-ss` before
   `-i`) would land on. It is *closer* to the current output-seek frame than A is,
   not farther.
2. **O(1) decodes.** The cast phase stops being linear in track count — the
   pathological case is gone by construction, not merely mitigated.
3. **Zero seek surface.** Batch uses `select`, no `-ss` at all, so the §12 seek
   landmine simply does not apply to the new path.

## 3. The seek landmine is already satisfied (why this is allowed)

The §12 landmine is `-ss` **before** `-i` on a **re-encoded cut** — it puts black
frames at the cut boundary. A single still grab is not a cut, and the repo's own
lint already encodes that. `scripts/lib/lint.py:159`, inside `_seek_order`:

```python
if any(_STILL_GRAB_RE.fullmatch(a) for a in cmd):   # a still grab is not a cut
    return []
```

`_STILL_GRAB_RE` matches `-frames:v` / `-vframes`. Both current grabbers already
pass `-frames:v 1`, so **fast-seek on a still grab is lint-clean today** — no
carve-out is needed for approach A either, and the batch path (no `-ss` at all) is
clean a second way. This is documented so a future reader does not "fix" the new
code back to output-seek believing the landmine requires it.

## 4. The primitive — `assembly.frames_rgb`

```
frames_rgb(src: str, times: list[float], fps: float) -> list[np.ndarray]
```

- Frame number per time: `n = round(t * fps)`. `fps` is passed in (the caller
  already holds it), so the primitive does no probe.
- Decode: `ffmpeg -i src -vf select='eq(n\,N1)+eq(n\,N2)+...' -vsync 0
  -frames:v <k> <tmp>/f%0*d.png`, over the **unique, sorted** frame numbers.
  ffmpeg emits the frames in ascending-`n` order.
- Return: a list **aligned to the input `times`** — same order, same length.
  Duplicate times map to the same decoded frame (decoded once, referenced twice).
  Empty `times` → `[]` with no ffmpeg call.
- RGB `HxWx3 uint8`, `src`'s own resolution (`np.asarray(Image.open(png)...)`),
  matching today's `frame_rgb`.

It lives in `assembly` beside `frame_rgb`/`make_proxy` — the module that already
owns single-frame extraction and the proxy. Pure ffmpeg + Pillow + numpy, no cv2.

**`frame_rgb`** becomes a thin wrapper — `frames_rgb(src, [t], fps)[0]` — so the
single-frame API and its test survive and there is one decode path. (Its current
signature `frame_rgb(src, t)` probes fps internally to stay source-compatible; the
wrapper keeps that.) The plan settles whether any caller still needs it.

## 5. Consumers

1. **`_cast_from_original`** — collect every track's `t` from `best`, one
   `frames_rgb(original, times, fps)` call, then `crop_bbox` + mask each returned
   frame as today. Replaces the per-track `frame_rgb`. This is the > 480 s → ~12 s
   phase.
2. **phash** — intake grabs all window-midpoint frames from the **proxy** in one
   `frames_rgb(proxy, mids, proxy_fps)`, then hashes each array with
   `imagehash.phash(Image.fromarray(arr))`. This **decouples intake from
   `check_reel._sample_frame`** (the shared, deliberately slow-seek reel grabber).
   `check_reel._hamming` (pure) stays reused by `cull`.

## 6. What is deliberately NOT touched

- **`check_reel._sample_frame` / `_frame_mean` / `_phash_bits`.** Reels are short,
  so output-seek is cheap there, and the color-across-cut check reads frames at
  `bt ± 0.05 s` where output-seek's frame-accuracy is load-bearing. intake gets its
  own batched grab; the reel path is left exactly as is.
- **`storyboard._sample_frames`.** Out of scope; its own concern.
- **YOLO (`_people_timeline`, 78.8 s).** The true compute floor. Untouched by
  request — this slice is the frame-grab tail only. `imgsz`/`fps` levers are a
  separate, higher-blast-radius decision.
- **`make_proxy` transcode / VideoToolbox.** Deferred. Measured (VT-hybrid: 2×
  wall, 7× CPU) but it changes proxy pixels and needs its own re-validation; not in
  this slice.

## 7. Contract change and cache

Batch selects frame `round(t·fps)`; the current output-seek grabs the first frame
with `pts ≥ t`. These differ by **≤ 1 frame**, so real cast descriptors and window
phashes shift infinitesimally. A color histogram / perceptual hash is unaffected in
*quality* by a one-frame move, but the values are not bit-identical.

- **`CACHE_VERSION` 4 → 5** (`lib/intake_cache.py`), so a stale v4 entry recomputes.
- **Mocked goldens unchanged.** intake's unit tests monkeypatch the frame grab
  (`assembly.frame_rgb` today → `assembly.frames_rgb` after), so no real pixels
  flow and `FootageClip` goldens do not move.
- **The real-ffmpeg intake golden is re-pinned** — the one integration test that
  runs actual decodes.

## 8. Honest limits

- The ≤ 1-frame shift above is real, accepted, and the reason for the cache bump.
- This does not touch the run's floor: after the fix the clip is **YOLO-bound**
  (~79 s). Rough projection with cast+phash batched: > 600 s → **~110 s/clip**.
  "Better," measured, is the success bar — not a specific target.
- The ~50 tracks the drone clip produces are mostly spurious `person` detections.
  Batch makes cast cheap *regardless* of that count, so this slice does **not**
  filter them; culling noise tracks (which would also shrink `cast.json` for the
  human) is a separate concern, noted, not done here.

## 9. Testing

- **`frames_rgb` unit, real ffmpeg** — a synthetic clip with a known distinct
  colour per frame; assert each returned array is the frame for `round(t·fps)`
  (frame-accurate selection), that an unsorted `times` returns arrays in **input**
  order, that duplicate times return equal arrays, and that `[]` makes no call.
- **intake unit tests** — repoint the `frame_rgb` monkeypatches to `frames_rgb`
  (return a list); assert `_cast_from_original` issues **one** batched call.
- **`CACHE_VERSION == 5`**; the v4→v5 key test updated.
- **Real-ffmpeg intake golden re-pinned** under cache 5.
- **Measurement re-run** on the same drone clip: cast and phash wall-time
  before/after recorded in the plan's closing step.
