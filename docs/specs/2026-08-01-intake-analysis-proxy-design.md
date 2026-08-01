# Intake analysis proxy — one downscaled variant for all clip analysis

**Status:** design approved 2026-08-01.

`intake` scans raw footage into scored moment-windows. Today every heavy CV pass
decodes the **original** clip independently, and one of them — `vidstabdetect` —
runs at full resolution. On 4K/60 drone footage that is not a tax, it is a wall:
**measured ~0.0089× realtime, ≈ 67 minutes for a 35-second clip** (§1). This
design routes *all* of intake's analysis through **one downscaled proxy per clip**
— the "assess on the small copy, work on the original" split the user asked for —
killing the wall (→ ~13 s) and collapsing three 4K decodes into one.

## 1. The cost that forces this (measured)

On a real 4K/60 drone clip (`3840×2160`, 35.5 s), the repo's exact detect recipe
(`vidstabdetect=shakiness=8`, ascii):

| input | wall time | ×realtime | vs full |
|-------|-----------|:---------:|--------:|
| **full-res 3840×2160** | **~67 min** | 0.0089× | 1× |
| `scale=1280` wide | 45 s | 1.26× | ~90× |
| **`scale=960` wide** | **13 s** | 0.37× | **~300×** |

The `lib/vidstab.py:17` comment estimated 2.2–4.4× realtime from an `mestimate=epzs`
proxy. That estimate is **wrong for this case** by ~25×: the proxy does not model
`shakiness=8`'s wide block-search cost, which scales with pixel count. The comment
is corrected as part of this slice.

`intake` also decodes the original **three** times per clip (scene-detect, YOLO,
vidstab) plus per-window phash seeks. Decoding 4K is itself expensive; the proxy
makes it happen **once**.

## 2. Architecture — a decode-once analysis proxy

Per clip, `_process_clip`:

1. **Probe the ORIGINAL** (`assembly.probe_stream`/`probe_duration`) → `res`,
   `dur`, `fps`. These describe the source and are stored on `FootageClip.res`
   unchanged (original geometry).
2. **Build the proxy** — one ffmpeg pass, original → a temp file: scale to
   **long side 960**, **native fps**, no audio, analysis-grade encode. This is the
   only 4K decode.
3. **Analyse the PROXY** — `scene_bounds`, `_people_timeline` (YOLO+ByteTrack),
   `vidstab.detect`, and per-window phash all read the proxy.
4. **Re-extract cast crops from the ORIGINAL** (§5).

The proxy is a throwaway intermediate (worker `TemporaryDirectory`, deleted with
the clip). The cached artifact stays the `ClipResult`, as today.

**Invariant (load-bearing):** the proxy exists **only for assessment**. Nothing
the proxy produces is a delivered pixel. Extract, reframe, stabilize-apply and
deliver continue to read the **original**, always.

## 3. What reads the proxy vs the original

| pass | input | why safe on the proxy |
|------|-------|-----------------------|
| scene-detect (`ContentDetector`) | proxy | content-based cut detection, scale-robust |
| YOLO seg + ByteTrack | proxy | proxy long-side = YOLO `imgsz=960`; boxes in proxy px → all downstream uses are **fractions** (§4) |
| `vidstab.detect` (shake) | proxy | fraction-of-width preserved above the quantization floor (§4, measured) |
| per-window phash (cull dedup) | proxy | dedup compares windows to each other; internal consistency is all it needs |
| **cast crop pixels + descriptor** | **original** | the one pixel artifact; compared against delivery-time descriptors (§5) |

## 4. Why the numbers survive downscaling

Intake's stored measurements are already **scale-normalized fractions**, so the
proxy changes the space the pixels are measured in, not the recorded value:

- `_motion` divides bbox displacement by frame width → fraction.
- `mean_shake` divides localmotion magnitude by frame width → fraction.
- `shot_type` is a bbox-vs-frame ratio.
- `people`, `track_ids`, `scene_cuts` are counts/ids/times — scale-free.

The functions are therefore fed the **proxy** width (not `res[0]`) when measuring
proxy pixels; `FootageClip.res` still stores the original.

**No coordinate mapping back to the original is needed** — intake emits no absolute
pixel coordinate that delivery consumes. `edit_plan`→`process_episode` re-tracks
the extracted original segment from scratch (`track.build_route`), so intake's
proxy-space geometry never leaves intake.

**Equivalence, measured** (real 4K clip, `mean_shake` fraction, full vs `scale=960`):

| regime | full | 960 | ratio | per-frame r | decision |
|--------|------|-----|:-----:|:-----------:|----------|
| synthetic shake ~0.016 (near the 0.02 SHAKY_CLIP gate) | 0.0091 | 0.0091 | **1.008** | **0.985** | matches |
| real near-still clip ~0.002 (at the integer-pixel floor) | 0.0019 | 0.0009 | 0.47 | 0.07 | `calm`=`calm` |

Downscale-960 is accurate exactly where a decision is made (shake ≳ 0.005, the
whole region around the 0.02 gate). It collapses only **below** the floor, where
the footage is `calm` at either scale — so no window's shaky/calm verdict flips.
That is the honest limit, not a hidden one (§9).

## 5. Cast crops and descriptors come from the original

`build_descriptor` output lives in two places that must be comparable:
`cast.json` (written by intake) and the **delivery-time** tracker
(`track.py:303`, built from the original extracted segment and matched to the cast
via `hero.resolve`). If intake built descriptors from 960 pixels and delivery from
original pixels, their comparability would ride on `build_descriptor` being
scale-invariant — an unproven dependency.

So: YOLO-on-proxy yields the best-crop `(track_id, timestamp, bbox)` per track (the
bbox in proxy pixels); intake then **seeks those few frames in the ORIGINAL** and
crops at original resolution. The crop rect is the proxy bbox scaled up by
`original/proxy` — the one place a proxy→original coordinate mapping is needed, and
it is local to the crop, never leaving intake. `build_descriptor` runs on the
original crop. This keeps `cast.json` descriptors on the same footing as delivery's,
and the human-facing candidate PNGs stay full-res. Cost: a handful of original
frame-seeks per clip (one per surviving track) — cheap. The YOLO mask is
proxy-scale; it is upsampled to the crop so the descriptor is background-removed
like delivery's — see §5a for how (the mask survives the follow-up; the shipped
first cut went maskless and had to be corrected).

## 5a. Cast descriptor mask symmetry (follow-up 2026-08-01)

`build_descriptor(crop, mask)` builds an L1 colour histogram over the segmentation
mask pixels only — background removed — because §6.1a's identity match keys on
**clothing colour, not location**: intake snaps a person from one clip and delivery
re-snaps them from a different extracted segment (different background, light, pose),
and a masked histogram is what lets the two compare. `CAST_MATCH = 0.6` already
budgets for that cross-clip drift; it does not budget for one side carrying
background pixels the other dropped.

The first cut of §5 resolved the "upsampled or maskless" parenthetical as
**maskless** on the intake side (`_cast_from_original` → `build_descriptor(crop,
None)`) while delivery stayed **masked** (`track._track_crops` →
`build_descriptor(crop, mask)`). That asymmetry — intake histograms polluted by a
person-bbox's background triangles (arms/legs leave large gaps), delivery's not —
did not exist before the proxy slice (intake was masked via `crop_and_mask`), and
the final review flagged it: it shifts the L1 distance one-sidedly and can push a
true hero past `CAST_MATCH` or flip the margin rule.

**Decision — restore symmetry (mask both sides), do not go maskless-both.**
Maskless-both was rejected: dropping delivery's mask regresses the discrimination
§6.1a depends on (two people against the same background read as falsely similar),
and "measure it's harmless" has no fixture — `sample_clip` is a white box, no person
for YOLO to segment.

**Mechanism.** The YOLO seg mask exists at **proxy** scale (YOLO ran on the 960
proxy); the cast crop is taken at **original** scale. So:

1. `_people_timeline` records, alongside each track's best `(conf, t, bbox)`, the
   seg mask cropped to that proxy bbox → `best[tid] = (conf, t, bbox, mask)`. This
   mirrors `crop_and_mask`'s model→frame resize + bbox crop, at proxy scale; a
   detection with no mask (mocked YOLO) records `None`.
2. A shared `appearance.seg_mask(res, idx, box)` extracts the proxy-bbox mask (mask
   only, no pixels — the pixels come from the original later); `crop_and_mask` is
   refactored to reuse it, so the resize-landmine has one spelling.
3. `appearance.upsample_mask(mask, (H, W))` resizes the proxy-bbox mask up to the
   original crop's shape.
4. `_cast_from_original` crops the original as before; when a mask is present it
   builds `build_descriptor(crop, upsample_mask(mask, crop.shape[:2]))`, else falls
   back to the maskless path (unchanged for the mocked-YOLO tests).

**Honest limit.** The intake mask (proxy-YOLO, then upsampled) is **not** the
pixel-identical twin of delivery's mask (original-YOLO): YOLO ran on differently
scaled inputs. But both are background-removed clothing histograms — vastly closer
than maskless-vs-masked, and the same proxy-scale equivalence §4 already measured
and accepted. The residual is the irreducible proxy effect, not a new asymmetry.

**Cache.** `CACHE_VERSION` 3→4: the real-footage descriptor changes shape
(maskless → masked), so every v3 entry must miss and recompute. The mocked-YOLO
goldens carry no masks → maskless → their recorded values are unchanged.

## 6. vidstab shared-recipe interaction

`DETECT_ARGS = "shakiness=8"` is shared by intake's measure and the stabilize
pre-stage's detect (`lib/vidstab.py:29`). This slice does **not** touch the recipe
— both keep `shakiness=8`. Only intake's **input** changes (proxy). The stabilize
detect still runs on the **original** short extracted segment, because it stabilizes
original pixels for delivery. §4's measurement shows the fraction is scale-invariant
above the floor, so intake's proxy "shake" and process_episode's original "before"
stay comparable — the property the shared recipe exists to protect.

## 7. Cache

- **`CACHE_VERSION` bump** — the analysis basis changes; every existing
  `.intake_cache` entry must miss and recompute.
- `intake_cache.clip_key` gains **`proxy_long_side`** (alongside `sample_fps`,
  `model`), so changing the proxy scale invalidates the cache the same way.

## 8. Decisions (fixed)

- **Long side 960** — matches YOLO `imgsz=960` (no second internal resize) and is
  the measured shake-equivalent scale.
- **Native fps** — no temporal reduction. `vidstabdetect` measures *inter-frame*
  motion and ByteTrack needs frame continuity; dropping frames changes the shake
  unit and breaks track association. `SAMPLE_FPS=3` stays the *timeline* record
  granularity, unchanged and independent of the proxy.
- **Proxy is analysis-only and throwaway.**

## 9. Honest limits

- **Near-still footage** reads roughly half its (already sub-threshold) shake at
  960 and loses per-frame shape (r≈0.07) — the integer-pixel quantization floor.
  It does not matter: `calm` stays `calm`. Genuinely shaky footage (the only kind
  the gate acts on) is preserved (§4).
- The proxy adds **one encode generation** before analysis. At analysis-grade
  quality (CRF ~18) this is well below any threshold intake measures; the
  real-ffmpeg test (§10) confirms the golden still holds through the file-based
  proxy (the equivalence numbers in §4 were measured filter-inline, not through a
  written file — the test closes that gap).
- Proxy generation itself decodes 4K once (~1–3× realtime). It replaces three 4K
  decodes, so it is still a net win, but a very short clip sees less benefit than a
  long one.

## 10. Testing

- **Real-ffmpeg equivalence (integration):** run proxy-based intake on a real 4K
  clip; assert its `FootageClip` (shake, motion, shot_type, window spans,
  scene_cuts) matches the pre-proxy golden within a stated tolerance, and that the
  emitted cast crop PNGs carry **original** resolution.
- **Golden re-pin:** the footage golden shifts slightly (proxy-measured values);
  re-pin with the new values recorded.
- **Cache:** `CACHE_VERSION` bump asserted; `proxy_long_side` participates in the
  key (a scale change → miss).
- **Speed sanity (non-gating):** the proxy path completes a 4K clip in seconds, not
  tens of minutes.

## 11. Deferred / out of scope

- The same proxy for **delivery-time** track/reframe — they run on short *original*
  extracted segments (1–4 s) and are already bounded; no wall there.
- **fps** reduction of the proxy — rejected (§8): breaks vidstab inter-frame motion
  and ByteTrack continuity.
- A user-tunable proxy scale beyond the fixed 960 — YAGNI until a case needs it.
