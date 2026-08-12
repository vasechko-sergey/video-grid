# Backlog — the queue

**This is the only document that holds priority.** Everything else records
*reasoning* (each design's `§Deferred`), *detail*
([fixes-backlog.md](fixes-backlog.md)), *history*
([build-status.md](build-status.md)) or *stage status*
([pipeline-map.md](pipeline-map.md)). When they disagree with this file about
what happens next, this file is right.

It exists because on 2026-08-12 an audit of all 28 design `§Deferred` sections
against the code found **four items that had left every list** — and three of
them were live defects shipping in every run. Deferrals were being *archived*,
never *scheduled*. See
[the housekeeping design](specs/2026-08-12-housekeeping-backlog-design.md).

> **The rule:** a slice is not finished until every item in its design's
> `§Deferred` has a row here. It is a convention, not a gate — nothing machine-
> checks it (design §6).

## Legend

| | |
|---|---|
| **Status** | `○` open · `◐` partial · `✅` done · `⊘` won't do |
| **Priority** | `P0` live defect · `P1` next · `P2` soon · `P3` someday · `P4` only on request |
| **Size** | `S` a task or two · `M` a slice · `L` several slices |

Priorities are one person's judgement on one day. P2 and below will not survive
contact with the next real run — they are a starting order, not a measurement.

**P0 is empty.** The four live defects the 2026-08-12 audit found are fixed (last
section). A P0 row means something ships wrong today, so an empty P0 is the
normal state and a populated one interrupts whatever is in P1.

**Three items span buckets** rather than sitting in one, and each says so where
it appears: **#9** (cinematic look) is split P1/P2/P3; the **episode-QC loop** is
P2 for the re-judge and P3 for the auto-route; and **reel length** is P2 for the
diagnosis and P3 for the enforcement. Do not close any of the three on its first
row alone.

---

## P1 — next

| | Item | Size | Source |
|---|------|------|--------|
| ○ | **Cinematic look filters + mood look** — vignette + grain + bookend fade as a reel-level `EDL.look` applied in `deliver`'s one encode, each with a measured visibility proof; `MoodPreset.look` supplies the default from the brief. Carries the two parked leftovers `highlight_red` and the `outline-bold` title style, which closes #18. | M | [#9](fixes-backlog.md#9-cinematic-effects-library--mood-oriented-palettes), [#18](fixes-backlog.md#18-cinematic-effects-were-born-as-live-patches--land-them-properly-and-verify-they-show), playbook P4 |
| ○ | **Music ends mid-phrase** — the cut grid is beat-aligned; the music *out-point* is not. Needs `systematic-debugging` on a real `MUSIC.json` before a design. Its likely fix is the librosa **section detection** that pacing §10, length-retime §9 and music-spine §9 have each deferred in turn. | M | [#2](fixes-backlog.md#2-music-is-cut-in-the-middle-of-a-phrase), pacing §10 |

## P2 — soon

| | Item | Size | Source |
|---|------|------|--------|
| ○ | **The authoring skill documents every knob it has** — `edit-plan` should enumerate the full set in one place: layout / composition / grid / motion / pan / zoom / ramp / stabilize / smooth_window_s + the colour grade. Verify each against `models.ReframeSpec` first: a named-but-missing tool (curves, shadows) is a build-or-not decision, not a doc gap. | S | [#5](fixes-backlog.md#5-the-authoring-skill-must-document-every-modification-tool-it-has) |
| ○ | **Cheap 3-frame probe** — render three frames with a new grade, measure, iterate; pay the full episode re-encode only once it converges. The 2026-08-03 run spent ~29 full re-encodes. Generalizes to effect *visibility*, not just colour — but it is a **run-time convergence loop**, not the same thing as the P1 row's per-effect visibility proofs, which are one-off measurements in the test suite. #18 asks for both; neither substitutes for the other. | M | [#10](fixes-backlog.md#10-cheap-3-frame-preview-to-converge-the-colour-grade-before-a-full-episode-re-render) |
| ○ | **Mood → grade** — bias `match_grade`'s common target by the brief's mood instead of taking the source median alone. This is the "§10 mood LUT" colour-as-a-stage deferred; the *look* half lands with #9 above, this is the grade half. | M | colour-stage §11, matchgrade §8 |
| ○ | **Re-assess §6.1a layer 3 against track-stitch** — both address a mid-episode hero ID switch, by different mechanisms (descriptor continuity vs geometric overlap-vs-gap). Decide whether a real remainder exists before building anything. | S | cast-hero-pin §11 |
| ○ | **Calibrate the first-cut identity thresholds** — `CAST_MATCH` / `CLUSTER_COS` / `MAX_CAST` are declared guesses; the distance distribution needed to derive them is already on disk in any real cache. | S | hero-reid §11, cast-hero-pin §11 |
| ○ | **Close the episode-QC loop** — two halves of one loop, both episode-qc §13, and the P3 list holds the other one. **This half:** `build_reel`'s retry reprocesses an episode *after* its QC verdict, so it ships judged one render out of date (recorded as `reprocessed` in the attestation, not prevented) — closes episode-qc §8. **The other half, in P3:** auto-routing a *blocking* finding back into a re-render. Do the re-judge first; routing findings into renders that are then never re-judged makes the hole bigger. | M | episode-qc §13 |
| ○ | **Surface the active editorial constraints in `montage status`** — a human should see which rules bind a re-cut without opening `CONSTRAINTS.json`. | S | constraints §11 |
| ○ | **Auto-place a ramp's `at` from the action anchors** — `lib/anchors` already computes the curve the author is eyeballing. | S | speed-ramp §13 |
| ○ | **A `sample_clip` fixture longer than `WIN_MAX`** — the 3s no-scene-cut fixture can only ever carve one window, which is why the pool-relative scoring and window-boundary changes have no real-bytes proof. A testing gap that blocks proofs, not a feature. | S | intake-motion-scoring §9 |
| ○ | **LICENSE + its `plugin.json` field** — the repo has none, and the plugin manifest omits the field. A distribution blocker, cheap to close. | S | plugin-packaging §6 |
| ○ | **The length figures do not reconcile** — the 2026-08-03 run showed a fitted spine of 27.7s, `target_dur` 30.317s and a rebuilt reel at 34.05s. **Do this before the P3 "enforce `SPEC.length_s`" row, not beside it**: you cannot enforce a number three stages disagree about, so that row is the fix and this is its diagnosis. | S | [#20 second pass](fixes-backlog.md), length-retime §9 |

## P3 — someday

Grouped by area. One line each; the source carries the reasoning.

**Front half / authoring**
`split` — the last genuine layout, two sources into two rects (misc-engine, fit-solid §9, pan §12) ·
trend-scan SP4 (§5.4), which also unblocks reel-review's `trend_flavor` ·
shot-order grammar, "never two same-size shots back to back" (mood-preset §14) ·
real window dedup for the variety census's `available` (mood-preset §14) ·
carrying editorial constraints through `edl_to_reel`'s hand-authored front door (constraints §11) ·
more constraint kinds — `no_adjacent`, visual-similarity repeats (constraints §11) ·
a semantic version marker on `FOOTAGE.json` so `from_dict` can refuse a stale artifact (intake-motion-scoring §9)

**Identity**
hero-conditioned re-scan — re-measure windows holding a named hero after cast naming; **blocked on a face detector** (mood-preset §14, playbook P3) ·
auto-register a chosen hero back into the cast (cast-hero-pin §11) ·
sharpness/blur metric — the cv2 blocker is gone, the cost is now measurement work plus a `CACHE_VERSION` bump (footage-intake §8)

**Colour**
reconcile the two neutralizers, white-balance vs normalize-gain, into one authority (colour-stage §11) ·
crop-accurate / K-frame tone measuring instead of the whole frame at the midpoint (matchgrade §8) ·
cross-episode white-balance / cast matching (matchgrade §8)

**Moves — geometry and time.** These move the frame or the clock, ride the
tracked route, and are judged by `check_episode` like any crop.
scenery zoom, Ken Burns over a subject-less shot (subject-anchored-moves §11) ·
easing for zoom and pan travel (subject-anchored-moves §11, pan §12) ·
`minterpolate` interpolated slow-mo — real intermediate frames instead of duplicates (speed-ramp §13) ·
speed-**up**, `factor > 1` (speed-ramp §13) ·
pan tilt (Y motion) and a pan over part of a clip (pan §12)

**Look — image treatment. The tail of #9, whose first half is the P1 row above.**
Nothing here moves the frame; it tints, darkens or textures it, so none of it
touches the route or the composition checks. Deferred *behind* the P1 slice, not
independently of it: film LUTs (need licensed asset files — a distribution
question before a code one), halation/bloom, light leaks, chromatic aberration,
letterbox bars (wrong on a 9:16 reel, where the `fit` layout's background already
does the job).

> **#9 is one item split across three buckets** — P1 builds vignette + grain +
> bookend fade with a visibility proof each, P2 biases the grade by mood (the
> long-deferred "mood LUT"), and this line holds the rest. When the P1 slice
> lands, all three rows move together; do not close #9 on the first one.

**Music**
adaptive hook length instead of a fixed `HOOK_BEATS` (pacing §10) ·
per-section mood arc (mood-match §9, pacing §10) ·
beat as a hard gate, once a cut can be re-trimmed (music-spine §9) ·
re-pick `MUSIC.start_offset` at the back-edge (length-retime §9) — **a second lever on the P1 "music ends mid-phrase" row**: moving the in-point moves the out-point, so it may fix #2 without section detection at all, and the investigation should weigh both ·
enforce `SPEC.length_s` rather than only logging the cross-check (length-retime §9) ·
music-less dual-emit + trending-sound sidecar, §5.14 (music-spine §9, using-montage §5) ·
a SPEC field for ambient / SFX instead of only `ReelManifest` flags (ambient §9, sfx §9) ·
per-episode ambient level or mute (ambient §9)

**Reel / QC / delivery**
secondary-aspect re-reframe on deliver — *the item that pointed at a "Phase F" which never existed* (reel-back-half §9) ·
`variety` auto-fix in loop-2, needs a front-half fixer (reel-retry-loop §8) ·
resumability / run-state persistence for the reel loop and the EDL run — deferred by four separate designs; only intake ever got it (reel-back-half §9, extract-spine §7, reel-retry-loop §8, edit-plan §7) ·
horizon-level detection (episode-qc §13) ·
auto-route a blocking QC finding into a re-render (episode-qc §13) ·
pixel/CV subject detection for safe zones, and a hard gate with a re-frame actuator (safe-zones §11) ·
a reviewer panel instead of one subagent, and judging real playback rather than stills (reel-review §7) ·
stamp the other six run artifacts with provenance (attested-run §12) ·
multi-reel fan-out — `reel_count > 1` now refuses loudly instead of silently making one (reel-brief §7, reel-review §7)

**Titles**
libass/ASS rendering · per-episode titles · the full pixel-level safe-zone gate — **the same capability the Reel/QC group's "pixel/CV subject detection for safe zones" needs; one measurement, two consumers, so build it once** · cross-platform font install (titles §7)

**Packaging / runtime**
GitHub-remote marketplace (plugin-packaging §6) ·
a leaner plugin root and relocating the ~12 MB of weights out of the tree (plugin-runtime-resolution §6) ·
dependency **version** assertions in preflight (verify-runtime §9)

**Contact sheets**
a platform crop guide on each cell · a contact sheet of the delivered reel for CP3 · per-window multi-frame cells (contact-sheet §10)

## P4 — only on request

Real but low-value, or explicitly priced and found not worth it.

`build_reel`'s reprocess loop stays sequential — batches are one or two culprits, so the fan-out's measured 1.70× has little to bite on (cap3 §9) ·
auto-sizing `jobs` from `cpu_count`, a GPU-aware cap, peak-memory measurement — no GPU box was available to measure (cap3 §9, intake-parallel §11) ·
caching CV intermediates and parallelising intake's Phase 2 (intake-parallel §11) ·
a user-tunable proxy scale beyond the fixed 960 (analysis-proxy §11) ·
per-track motion carried on `FootageWindow` (intake-motion-scoring §9) ·
multi-crop-per-track reID averaging (hero-reid §11) ·
per-part colour fidelity, skin vs gear, and an auto-fix for the advisory drift check (colour-stage §11, matchgrade §8) ·
a reference-episode tone target instead of the per-anchor median (matchgrade §8) ·
a check surface reading `TrackMeta.stitched`, and tuning the stitch thresholds — no synthetic case exists (track-stitch §8) ·
a vertical component for zoom (subject-anchored-moves §11) ·
a multi-plateau ramp, two slow moments in one shot (speed-ramp §13) ·
a true pitch-sweep whoosh, and per-episode SFX cues (sfx §9) ·
ducking-depth and SFX advisories in `check_reel` — the −14 LUFS hard gate already covers level (ambient §9, sfx §9) ·
per-track music feature caching, and ML-embedding mood (mood-match §9, sourcing §13) ·
merge-all-catalogs as the `any` default (sourcing §13) ·
draft-stage polish: creative crop/colour, ducked ambient, beat-accurate pacing, a segment cache, a standalone SKILL (assemble-draft §7) ·
gradient and auto-derived background colours (fit-solid §9) ·
network reachability probes in preflight (verify-runtime §9) ·
cross-platform `setup.sh` and `bin/vg` — macOS/Homebrew is a stated project boundary (ffmpeg-baseline §9, plugin-packaging §4)

## ⊘ Won't do

| Item | Why |
|------|-----|
| Face **recognition** for hero identity | Excluded by the montage design: faces are small, wet and turned away in this footage. **Not the same thing as the face *detector* the P3 hero-conditioned re-scan is blocked on** — that one only needs to find *a* face to say "this window has a person facing camera", and never matches one person against another. The identity work is what is refused here |
| A `verify_runtime --fix` that runs `setup.sh` | Rejected on principle — no autonomous system mutation (verify-runtime §4) |
| A signed rather than merely digested attestation | Pointless against a local adversary who holds the key (attested-run §12) |
| A per-episode `.attest.json` **sidecar** | Per-episode *binding* already exists and this row is not it — see the note below (attested-run §12) |
| Spotify `audio-features` for mood | Deprecated for new apps since Nov 2024 (sourcing §13) |
| A 4th "dynamism" mood axis | YAGNI — three axes already order the shortlist (mood-match §9) |
| The analysis proxy for delivery-time track/reframe | They run on short *original* segments; the proxy would cost fidelity for nothing (analysis-proxy §11) |
| Reducing the proxy's fps | Measured to break vidstab's inter-frame motion (analysis-proxy §8) |
| Re-tuning `_motion_fit` | Superseded — P3 slice S3 replaced the sensor and `score_window` outright rather than re-tuning them |

**Note on "per-episode attestation".** attested-run §12 deferred it on 2026-08-04
with the reason *"the reel is the delivered unit; episodes are intermediates"* —
true when written, and half-false four days later. episode-qc (2026-08-08) landed
`EpisodeVerdict.clip_digest`: the sha256 of each judged clip, **computed by
`episode_qc build` from the file on disk rather than taken from the judge's
claim**, a staleness gate that refuses when a verdict's digest no longer matches
the rendered clip, and an `episode_qc` block carried into the reel's
`REEL_v{n}.attest.json`. So an episode *is* bound to the pixels it was judged on.
What is still absent is only a separate attestation sidecar per clip, which buys
little on top of that — hence the row stays a won't-do, but under a reason that
is currently true. This one was caught by a reader of this queue on the day it
was written, which is the second stale-reason deferral the housekeeping audit
turned up after the three it set out to fix.

---

## Real-run findings — the #1–#20 list at a glance

The detail for each lives in [fixes-backlog.md](fixes-backlog.md); this is the
status column that file does not have.

| # | Finding | Status |
|---|---------|--------|
| 1 | Hero identity — colour-histogram descriptor → OSNet re-ID embedding | ✅ 2026-08-04 (the hero-conditioned re-scan remains, P3) |
| 2 | Music is cut in the middle of a phrase | ○ **P1** — needs investigation before design |
| 3 | Per-episode rendering and QC in subagents | ✅ 2026-08-08 |
| 4 | `setup.sh` installs everything; unavailable components warn and continue | ✅ 2026-08-04 |
| 5 | The authoring skill must document every modification tool it has | ○ **P2** |
| 6 | The router never asked about titles / effects | ✅ 2026-08-04 |
| 7 | Slow-mo is a first-class effect, and it changes the reel length | ✅ 2026-08-09 |
| 8 | Subagents must not be able to disable quality control | ✅ 2026-08-04 |
| 9 | Cinematic effects library + mood-oriented palettes | ○ **P1** (look half), P2 (grade half) |
| 10 | Cheap 3-frame preview to converge the grade | ○ **P2** |
| 11 | Freeze the engine during a run | ✅ 2026-08-04 |
| 12 | "Look, don't guess" — examine real frames | ✅ both halves (2026-08-05 selection, 2026-08-08 per-episode) |
| 13 | A quality gate must not be bypassable by manual assembly | ✅ 2026-08-04 |
| 14 | Editorial-constraint memory across iterations | ✅ 2026-08-07 |
| 15 | CP3 reel-review must not be silently skipped | ✅ 2026-08-04 |
| 16 | `VERSIONS.md` note bug — path logged instead of the reason | ✅ 2026-08-04 |
| 17 | Frame-moving effects stay subject-anchored and inside QC | ✅ 2026-08-08 |
| 18 | Cinematic effects were born as live patches — land them, verify they show | ◐ zoom ✅ 2026-08-08, ramp ✅ 2026-08-09; look filters + `highlight_red` + `outline-bold` ride #9 |
| 19 | Shot-type variety + brief fidelity | ✅ 2026-08-06 |
| 20 | Off-pipeline manual EDL editing | ✅ 2026-08-04 |

## Housekeeping — what the 2026-08-12 audit found and fixed

Four deferrals had left every list. Three were shipping as live defects.

| | Item | Landed |
|---|------|--------|
| ✅ | `platform` never reached the reel — the brief recorded it, `check_reel`'s safe-zone gate and `titles.y_exprs` both silently took the generic table | `EDL.platform`, carried by `edit_plan --spec` into `edl_to_reel` |
| ✅ | `EDLEpisode.smooth_window_s` could not be authored though `ReframeSpec` had the field — deferred by colour-stage §11, rediscovered by speed-ramp §9 | authored, and the retry ladder's lag branch now floors at the authored value instead of walking it back to 0.25 |
| ✅ | `draft.py` rendered an **8×16-pixel** video — it spent the canvas *aspect* as pixels. Two tests protected it: the unit test hand-passed the right pixels, and the integration fixture hand-wrote pixels where an aspect belonged | 8×16 → 606×1078, proven by probing the real output file |
| ✅ | `Spec.reel_count > 1` was accepted, printed as "3 reels", and produced one | refuses with the remedy; the field stays for the day fan-out lands |

All four landed 2026-08-12 on `chore/housekeeping-backlog`. The
`Delivery.dims(native)` trap is worth remembering: it returns `(even(w), even(h))`
and nothing else, so the obvious one-line fix for the draft would have reproduced
the same 8×16 output one call deeper.

Three pointers had gone stale and were corrected in the same pass: a "Phase F"
that never existed, a cv2 blocker that disappeared when the tracking ladder
landed, and three build-status entries about §6.1a layer 3 written as though
track-stitch had not shipped.

_Last updated: 2026-08-12._
