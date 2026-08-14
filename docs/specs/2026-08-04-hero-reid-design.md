# Hero identity — a person-re-ID embedding replaces the colour histogram

**Status:** design (promoted from fixes-backlog #1, approved 2026-08-03). Cinematic
-quality playbook Phase 1. Successor to the cast→hero-pin slice
([2026-07-16-cast-hero-pin-design.md](2026-07-16-cast-hero-pin-design.md)) — it
keeps that slice's plumbing (HeroPin, `hero.resolve`, the manifest hero oracle,
`cast.json`) and swaps only the *feature* the plumbing carries.

## 1. The problem

Hero selection on real footage is unusable. The appearance descriptor
([`lib/appearance.py`](../../scripts/lib/appearance.py) `build_descriptor`) is a
24-dim L1-normalized RGB colour histogram (8 bins × 3 channels) over the seg-mask
pixels. It encodes **clothing colour, not identity**. On the 2026-08-03 surf run
(dark/navy wetsuits, water background, small far subjects) it is not separable:

- Whole-cache scan: **4062 tracks** → greedy dedup at `CAST_DEDUP=0.30` left
  **892 "identities"** → `surface_crops` capped at **top_n=8**.
- Two opposite failures at once: **over-merge** (one surfaced candidate absorbed
  41 tracks from 24 clips within 0.30 — including a child) *and* **over-split**
  (892 survivors for a session with a handful of real people).
- Pairwise L1 among the 8 surfaced candidates clustered at **0.37–0.7**,
  straddling both the 0.30 dedup line and the downstream `CAST_MATCH=0.6` line.
  Threshold tuning cannot fix it — true-match and false-match distances overlap
  because the feature does not encode identity.
- The analysis proxy is NOT implicated: cast crops are re-cut full-res from the
  ORIGINAL frame (candidate_0 = 331×926 px, sharp). The candidate *list* is the
  problem, not crop resolution.

**Consequence (2026-08-03 run):** every `route.meta.json` shows `pin=None`,
`EDL.cast=None`; the whole cast→hero-pin machinery was bypassed for
`hero:largest` + hand-made reference crops. Without reliable identity the reel
cannot feature *this person* — the entire "personality-forward" editorial axis is
dead. This is the highest-leverage fix in the playbook.

## 2. Decisions locked (brainstorm 2026-08-03)

- Real person-re-ID **embedding**, not a better handcrafted feature.
- Model: **OSNet** via `torchreid` (Market-1501 pretrained, 512-dim, cosine),
  behind a clean `lib/reid.py` boundary so swapping to CLIP/torchvision is a
  one-file change. New dependency, installed at setup baseline (warn-and-continue,
  the #4 pattern).
- Surface: **agglomerative clustering** into the real number of people, each
  person once, ranked by **presence** (on-screen seconds across all clips), not
  YOLO confidence. Adaptive cap (~15) with a logged truncation — no silent caps.
- Migration: **none** — `CACHE_VERSION` bump and a clean fresh re-scan (the user
  re-runs intake). The embedding is computed inline during the scan.
- OSNet is fed the **tight person bbox crop, UNMASKED** (reID is trained on
  bbox+background; a silhouette is out-of-distribution). The seg-mask plumbing in
  the cast path is removed — it was a histogram-era need.

## 3. Module boundaries

The direction of the existing cast slice is preserved: `lib/footage` is the
numpy-free contract (the manifest gate imports it and owes an answer in ms);
`lib/appearance` is numpy+PIL (crops, the pure distance); the new `lib/reid` is
the only place torch is touched, imported by the two *producers* only.

### 3.1 `lib/reid.py` (new) — the only importer of `torchreid`

```
available() -> bool          # torchreid imports? (mirrors track.available/flow.available)
require() -> None            # fail-loud with a remedy if not (mirrors vidstab.require)
ensure_model() -> None       # materialize OSNet weights ONCE before any pool (mirrors track.ensure_model)
embed(crops: list[np.ndarray]) -> list[list[float]]
                             # batch RGB HxWx3 crops → L2-normalized 512-d vectors
```

- Lazy `import torchreid` inside each function (heavy optional dep, mirrors
  `track._iter_detections`).
- `embed` constructs a module-level `FeatureExtractor(model_name="osnet_x1_0",
  device=<mps|cpu>)` once and reuses it; resizes each crop to 256×128; returns
  each row L2-normalized so `appearance.descriptor_dist` is a true cosine.
- `ensure_model()` builds the extractor once (forcing the one-time weight
  download) so N pool workers do not race the same download into the same path —
  the concurrent-writer landmine `track.ensure_model` already closes for YOLO
  (§12). Callers that fan out MUST call it first.
- `require()`'s remedy: `run \`bash setup.sh\`, which installs torchreid + OSNet
  weights` (the `vidstab._REMEDY` shape).

### 3.2 `lib/appearance.py` — cosine distance + crop helpers, no torch

- `descriptor_dist(a, b)` becomes **cosine distance** `1 - dot(a, b)` on
  L2-normalized vectors, range **[0, 2]** (0 = identical direction, 1 =
  orthogonal, 2 = opposite). Pure Python, keeps the equal-length guard.
- `crop_from_result(res, idx, box) -> np.ndarray | None` — the crop half of
  today's `crop_and_mask` (ultralytics `orig_img` is BGR→RGB, crop the bbox), no
  mask. Used by `track` where the source frame rides in the detection result.
- `crop_bbox(frame_rgb, box_xywh, scale)` — kept unchanged (intake crops the
  ORIGINAL frame).
- **Deleted:** `build_descriptor` (histogram), `seg_mask`, `crop_and_mask` (its
  mask half), `upsample_mask`. The `HIST_BINS` import goes with them.

### 3.3 `lib/footage.py` — the on-disk contract

- `DESCRIPTOR_LEN = 512` (was `3 * HIST_BINS = 24`); `HIST_BINS` deleted.
- `CastMember.__post_init__` validates `len(descriptor) == 512`, remedy = re-run
  intake (a stale 24-d `cast.json` fails in ms at the load boundary, the same
  channel a typo'd name already fails through).
- No new field on `CastMember` — presence is a candidate-surfacing concept, it
  lives on `CastEntry` (§3.4).

### 3.4 `lib/intake_cache.py` — the cached worker result

- `CastEntry` gains `presence: float = 0.0` (on-screen seconds of the track);
  `store`/`load` round-trip it. `CACHE_VERSION` **5 → 6** (a v5 result carries
  24-d descriptors and no presence — it must miss so the new code recomputes).

## 4. Producers

### 4.1 intake (`scripts/intake.py`)

- `_people_timeline` stops storing the seg mask: `best[tid] = (conf, t, bbox)`,
  and computes each track's **presence** = (count of timeline samples carrying
  that tid) × the sample step in seconds.
- `_cast_from_original` crops the ORIGINAL-frame bbox **unmasked** (via
  `crop_bbox`), collects one crop per track, batches them through `reid.embed`,
  and builds `CastEntry(descriptor=<512-d>, presence=<seconds>, ...)`.
- `surface_crops` is rewritten: cluster ALL entries' embeddings with
  `scipy.cluster.hierarchy` (average linkage, cosine metric) cut at
  `CLUSTER_COS`; per cluster the descriptor = **centroid** (mean embedding,
  re-L2-normed), the representative crop = **medoid** (member nearest the
  others), presence = **sum** over members; rank clusters by presence; adaptive
  cap `MAX_CAST` (~15) with a `log`-ged drop count. (`scipy` is already present
  via librosa — no new dep.)
- `save_cast_candidates` / `cast_candidates.json` carry `presence` and rank by
  it; the footage-intake SKILL shows the human a presence-ranked, one-per-person
  list to name.

### 4.2 track (`scripts/track.py`)

- `_track_crops` collects the highest-confidence **unmasked crop** per track
  (`appearance.crop_from_result`), not a descriptor.
- `build_route`, on a cast pin, batches the collected crops through `reid.embed`
  once, then `_descriptor_track` ranks by `appearance.descriptor_dist` (cosine)
  with the existing min-distance + `AMBIG_MARGIN` rule and `CAST_MATCH` absence
  gate — unchanged logic, cosine numbers.
- Every non-cast pin still costs nothing extra (crops collected only when
  `spec.pin.kind == "cast"`, as today).

## 5. Thresholds (first cut, calibratable)

Cosine distance lives in [0, 2]; same-identity distances cluster low, cross
-identity high. First-cut values, to be calibrated on the real cache after the
first re-scan (the repo's honest-threshold pattern — no footage exists to tune):

- `appearance.CAST_MATCH` (absence gate, track): **0.35**.
- `intake.CLUSTER_COS` (cluster cut): **0.30**.
- `intake.MAX_CAST` (adaptive cap): **15**.

`AMBIG_MARGIN` (0.8) is metric-agnostic (a ratio of distances) and is unchanged.

## 6. The reID gate — where absence is felt (resolves backlog #1 point 5)

Backlog #1 says reID is "required for people footage" yet "scenery footage is not
blocked" and "only the cast step fails loud with a remedy". A single global
`required` preflight check cannot honour all three (it would block scenery too).
The coherent resolution, consistent with the #4 install-everything philosophy
("if a capability cannot be installed, warn and keep working"):

| Site | Behaviour when torchreid is absent |
|------|-----------------------------------|
| `preflight` `reid` Check | **advisory** (`required=False`) — never blocks the global runtime; reported with a remedy by `verify_runtime`. *(This row said "mirrors demucs" until 2026-08-14; it no longer does — demucs became `required=True` when its fallback sensor was deleted, so `reid` is now the ONLY advisory row.)* |
| `intake()` producer | **warn-and-continue**: `reid.ensure_model()` best-effort; if `not reid.available()` the scan still produces windows/scoring/phashes, the cast embed is **skipped**, `cast_candidates.json` is written empty, and ONE warning names the remedy. A useful scan is not held hostage to a missing optional model, and no clip is quarantined for it. |
| `track.build_route` cast pin | **fail-loud + remedy**: a descriptor pin *explicitly asks* for identity, so guessing is worse than refusing. As built, `process_episode` checks this BEFORE the ladder runs: when a cast pin resolves and the tracker itself is present but reID is not, it returns an explicit `stop_and_report` — finding reason `reid-unavailable`, naming torchreid and the `bash setup.sh` remedy — instead of letting the ladder run (an empty `track_meta` there would make `detect_contradictions` skip `hero-unmatched` and misreport `no-track`, a misleading remedy for an install gap; optical flow is correctly skipped regardless, since a pinned hero never falls to flow, design 2026-07-21 §1.1). `track.available(descriptor=)` also gains a reID term on the descriptor path, gating rung 1 for any caller that reaches the ladder directly. |

This keeps the producer generous (a scan without reID is still worth having) and
the explicit consumer strict (a named-hero pin never silently degrades to a colour
guess — the exact failure this slice deletes).

## 7. Setup + preflight

- `setup.sh`: a torchreid block mirroring the demucs block **exactly** —
  `pip install torchreid || echo "WARNING: ... reID cast identity falls back to
  unavailable; re-run 'bash setup.sh' to retry."`, guarded on already-installed,
  the `|| echo` keeping `set -e` happy. Kept OUT of `requirements.txt` for the
  same reason demucs is: a failed torch/torchreid wheel must degrade here, not
  abort the whole venv. OSNet weights download on the first `reid.ensure_model()`
  (like YOLO weights on first track), not in setup.
- `preflight.CHECKS`: `Check("reid", "torchreid person-re-ID (cast identity)",
  False, "bash setup.sh")`. `verify_runtime._probe_reid` = `importable("torchreid")`.

## 8. Testing

- Pure/unit (no weights): cosine `descriptor_dist` (range, identity, orthogonal,
  opposite); `crop_from_result` (BGR→RGB, empty→None); `footage.CastMember`
  accepts 512-d / rejects 24-d; `CastEntry.presence` round-trips the cache;
  `surface_crops` clustering + presence ranking + adaptive-cap log on **synthetic
  embeddings** (monkeypatch `reid.embed`); `_descriptor_track` cosine match/ambiguous/
  absent on injected embeddings; the reID gate table (§6) with `reid.available`
  monkeypatched both ways.
- Real OSNet behind a **weights-gated** integration test (skip if torchreid
  absent, like the vidstab/demucs goldens): embed two genuinely different real
  crops → cosine separates them past `CAST_MATCH`; embed the same crop twice →
  ≈0. This is where the RGB/BGR colour-order landmine (§10) is actually caught —
  a mocked embed cannot.
- `CACHE_VERSION` bump: re-pin `test_intake` / `test_cast_pin` goldens.

## 9. Honest limits

- OSNet is out-of-domain for surf (water, crouch, far/small subjects); quality is
  **not guaranteed** — verify on the real cache after the first re-scan and
  calibrate §5 there. This slice makes identity *possible and separable*, not
  perfect.
- **Single crop per track** for v1 (the highest-confidence detection). Multi-crop
  averaging per track is deferred — trivially enabled later since scans are fresh.
- The clustering cut (`CLUSTER_COS`) is a first cut without labelled data.
- Embeddings may differ slightly across devices (MPS vs CPU); thresholds are set
  with margin, but a device change is a reason to re-verify §5, not to trust the
  numbers blindly.

## 10. Landmines (candidates for §12 registry)

Silent-corruption class — no crash, just a quietly-wrong identity:

- **Masking the OSNet crop.** A seg-mask silhouette is out-of-distribution for a
  bbox-trained reID net: it still returns a 512-d vector, so nothing fails — the
  vector is just a poor identity feature. The crop fed to `reid.embed` MUST be the
  raw bbox crop. (This is *why* the mask plumbing is deleted, not merely unused.)
- **Colour order into OSNet.** ultralytics `orig_img` is BGR; feeding BGR where
  the net expects RGB yields plausible-but-wrong 512-d vectors and silently poor
  identity. `crop_from_result` / `crop_bbox` hand `reid.embed` **RGB**; the real
  -OSNet test (§8) is the only thing that can corroborate the order.
- **Concurrent OSNet weight download.** Same class as YOLO's — closed by
  `reid.ensure_model()` before the pool.

## 11. Deferred

- Threshold derivation from the candidate distance distribution (still a first
  cut; same deferral the cast slice made for `CAST_MATCH`).
- Multi-crop-per-track averaging.
- Swapping OSNet for CLIP/torchvision (the `lib/reid` boundary makes it one file).

## 12. Non-goals

- No change to HeroPin / `hero.resolve` / the manifest hero oracle / EDL.cast
  shapes — only the *vector* they carry changes length (24 → 512) and metric
  (L1 → cosine).
- No change to the tracking-ladder, stitch, or path-quality logic.
- Not promoting reID to a `required` preflight check (§6).
