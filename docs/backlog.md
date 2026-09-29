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

A row that closes leaves for [backlog-closed.md](backlog-closed.md) with its
closure note intact, so this file stays a queue and stops being a history.
Look there for what a row was closed *by*, and for the premises that were
overturned rather than delivered — 2026-09-06 moved 39 of them out, which was
41% of this file.

## Legend

| | |
|---|---|
| **Status** | `○` open · `◐` partial · `✅` done · `⊘` won't do |
| **Priority** | `P0` live defect · `P1` next · `P2` soon · `P3` someday · `P4` only on request |
| **Size** | `S` a task or two · `M` a slice · `L` several slices |

Priorities are one person's judgement on one day. P2 and below will not survive
contact with the next real run — they are a starting order, not a measurement.

**P0 is empty.** The four live defects the 2026-08-12 audit found are fixed
([the archive](backlog-closed.md) records them). A P0 row means something ships
wrong today, so an empty P0 is the normal state and a populated one interrupts
whatever is in P1.

**Three items span buckets**, and only their open halves are still here — the
closed halves are in [the archive](backlog-closed.md), so a bucket reading empty
is not the same as an item being done. **#9** (cinematic look): the P1 look half
landed 2026-08-13 and the P2 grade half 2026-08-17, and **P3 — the
image-treatment tail, now incl. grain — stays open, so #9 itself is not
closed**. The **episode-QC loop**: the re-judge half landed 2026-08-18, the
auto-route is still P3. **Reel length**: diagnosed 2026-08-15, the enforcement
is still P3.

---

## P1 — next

| | Item | Size | Source |
|---|------|------|--------|
| ○ | **Every threshold but `variety_min` — twelve of the eighteen fields of `ReelCheckSpec` and `CheckSpec` — is unreachable from any authoring surface, and R2.4 (a threshold widened by hand needs a reason attached) folds into this row.** `ReelManifest.check_spec` is `ReelCheckSpec(self.target_dur, self.variety_min)`: 2 of the class's 11 fields arrive from the manifest. `process_episode` builds `CheckSpec` from 3 of its 7 fields (all from the manifest) plus `attempt`, a retry counter. No CLI sets a threshold — `edl_to_reel`, `check_reel`, `build_reel` and `check_episode` offer none — so **12 of the 18 fields can only ever hold their default**: `beat_tol`, `loudness_target`, `loudness_tol`, `clip_tol`, `bar_symmetry_tol`, `layout_jump_max`, `length_retime_max`, `grade_residual_max` and `chroma_spread_max` on `ReelCheckSpec`; `black_floor`, `black_rel` and `entropy_floor` — the blocking grade-damage bar — on `CheckSpec`. Every one is a first cut on a single shoot. `provenance.spec_overrides`, the diff machine written to catch any loosened gate, is called once, on `ReelManifest.check_spec`, with `target_dur` exempt — so it can only ever report **`variety_min`**, and the mechanism R2.4 was filed against has exactly one reachable knob. The defect for a general tool is therefore the opposite of the one R2.4 named: not "widened silently" but "cannot be set at all". Two halves, one slice: give `ReelCheckSpec` and `CheckSpec` an authoring surface, and make `spec_overrides` meaningful by requiring a reason at the point of authoring — because a loosenable gate without a recorded reason is exactly the cry-wolf mechanism R2.4 was filed against (`color_delta_max`: 12 → 44 → **56** across the first real run, each widening silencing a complaint that was correct; that knob is deleted, colour-convergence-retire 2026-08-29). **R2.4's own row is removed and its correction carried here:** the example it first named, `grade_delta_max`, was itself renamed to `CheckSpec.entropy_floor` in 0.7.0 (grade-sensor-references, 2026-09-02) and fixed in the 2026-09-03 audit. | M | [unenforced-rules](specs/2026-09-29-unenforced-rules-design.md) §0.6, §5; [retro](retro/2026-08-25-first-real-run.md) R2 |

## P2 — soon

| | Item | Size | Source |
|---|------|------|--------|
| ○ | **Colour matrix / primaries / transfer are not in the segment contract.** All 99 clips of the only real pool are bt709, so there is no evidence to build against and an unmeasured `scale` matrix conversion would be a new landmine. A bt601 or HLG source is misread silently today. | S | [segment-range-contract](specs/2026-08-27-segment-range-contract-design.md) §8 |
| ○ | **Nothing gates that the authored tone actually reached its target.** After the range fix the miss is ~1.5 codes, but nothing anywhere compares a delivered episode against the target it was given: `grade_damage` measures how far the grade moved the tracked subject from ITS OWN pre-grade source — including exposure, via `delta_l`, since the 2026-08-28 grade-delta slice — never whether the episode reached the `tone_dst` match-grade assigned it, and the reel-level `color_across_cuts` check — which compared episodes to *each other*, never to a target — is retired outright (colour-convergence-retire, 2026-08-29) rather than ever having closed this gap. Its deletion does not touch this row: a check that never verified the authored pair was reached leaves exactly the same hole once it is gone. Adjacent to R2.2 and R2.6 but neither of them — those judge drift and regression, not whether the authored pair was reached. | M | [segment-range-contract](specs/2026-08-27-segment-range-contract-design.md) §7 |
| ○ | **`tests/fixtures/golden_ride.mp4` is raw full-range footage and four integration files fed it straight into `reframe`.** Found by the new depth/range guard on its first day — 12 failures and 5 errors, every one the same refusal. Worked around with a `golden_ride_segment` session fixture that normalizes it per run; the committed fixture stays raw, which is right for a *footage* fixture but makes the workaround permanent until something else owns the boundary. | S | segment-range-contract, Task 3 |
| ○ | **Migrate a pre-0.3.0 run into the lifetime layout.** Not a `mv`: `out/EPISODES.json` alone carries **57** absolute paths, and moving the tree breaks the QC digest bindings and the delivery attestation that exist to notice exactly that kind of change. A path rewrite. `montage status` already reports `legacy_layout` so the router asks instead of re-scanning 99 clips into an apparently empty run — that is the mitigation, not the fix. | M | [design](specs/2026-08-26-run-layout-lifetimes-design.md) §7 |
| ○ | **R10.8 · A judge's "clean pass" means "nothing I was told to look for".** Coverage tracked the prompt, not the episode: an episode passed clean, one sentence was added to the brief, and the next judge found something. | M | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R10.10 · The `_review/` stills packet is mis-indexed** — the reviewer noticed and it was never fixed. | S | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R8.2 · The pool was never widened after day 1.** The delivered reel uses 8 windows out of 1508, and the required contact-sheet "look at the pixels" stage ran **once**, for 177 seconds, on day 1, and was never re-run against a revised cut. | S | [retro](retro/2026-08-25-first-real-run.md) R8 |
| ○ | **R10.11 · "(silent reel)" in the pre-mix loudness check made the agent conclude the music had been lost.** A diagnostic message that reads as a failure. | S | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R10.12 · Eight of 22 `AskUserQuestion` turns were the human arbitrating a per-episode sensor failure** — the clearest measure of where a person's attention was actually spent. | S | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R8.1 · The score bought no part of the delivered reel.** Of 1508 windows the selection reaches rank **1338**; **zero** of the top-8 are used; 8 of 30 chosen windows are `best=False`. `cull` only marks `best`, so nothing was unreachable — but the CV time spent ranking contributed nothing. Either it earns its cost or it stops being presented as authority. **Measured and named, 2026-09-10**: `Footage.scoring` (design [unmeasured-named](specs/2026-09-10-unmeasured-named-design.md) §0.1/§4) is the number this row was missing — the largest weight, `W_PRESENT` at 0.44, separated **3 of 1508** windows on the only real pool: not that the score was ignored, but that 44% of it had nothing to say. | M | [retro](retro/2026-08-25-first-real-run.md) R8 |
| ○ | **R10.3 · 95% of conveyor calls were piped through `tail`/`grep`/`head`**, twice losing the answer — once costing a 173-second re-render to read output already produced. | S | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R10.5 · QC has no "judge only what changed" and no memory between rounds** — ~14 rounds, **97 judges, 160 MB, 8 episodes**, two blocking verdicts, one of them a false alarm from a stale evidence packet. | M | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R11.1 · Infrastructure ate 16 of 98 subagents** — 11 killed by the machine sleeping (episodes 0, 4 and 7 each needed three dispatches), 5 stopped deliberately. Incremental writing belongs in every subagent brief by default; it was proven necessary twice again while writing this retro. | S | [retro](retro/2026-08-25-first-real-run.md) R11 |
| ○ | **R12.1 · A film look: grain, gate weave, a soft edge falloff.** The look layer today is two knobs — a vignette and a bookend fade. Grain was measured and priced out in the cinematic-look design; unfreeze it. | M | [retro](retro/2026-08-25-first-real-run.md) R12 |
| ○ | **R12.2 · Visual transitions between episodes.** Hard cuts only today; the audio side already synthesises whooshes on major cuts and has no picture counterpart. | M | [retro](retro/2026-08-25-first-real-run.md) R12 |
| ○ | **R12.3 · Survey what effects are worth having, and encode WHEN to apply each.** `MoodPreset.look` is the routing hook that already exists and should carry it — otherwise this repeats the `probe grade` story: built, shipped, never reached. | M | [retro](retro/2026-08-25-first-real-run.md) R12 |
| ○ | **Calibrate the look** — `LOOK_VIGNETTE_MAX` (0.6), the 0.55/0.45 plateau/falloff split, and every row of `MoodPreset.look` are hand-picked on synthetic test patterns; no real footage has graded against them yet. | S | cinematic-look §11.3/§12 |
| ○ | **Calibrate the first-cut identity thresholds** — `CAST_MATCH` / `CLUSTER_COS` / `MAX_CAST` are declared guesses; the distance distribution needed to derive them is already on disk in any real cache. | S | hero-reid §11, cast-hero-pin §11 |
| ○ | **Re-derive `SAT_DELTA_MAX`/`CONTRAST_DROP_MAX` on a run whose baseline is not the complaint.** Both bars are set to zero false positives against the shipped reel — the very "washed out" run the operator complained about — so they are, if anything, too loose. **Unblocked 2026-09-03**: R1.1 shipped, so a mood no longer orders a grade silently and a reel graded without one is now authorable (`--tone-bias 0,0,0` keeps the mood and leaves colour alone). What is still needed is the reel itself. | S | [grade-delta-sensors](specs/2026-08-28-grade-delta-sensors-design.md) §9.4 |
| ○ | **Re-derive `entropy_floor` on a run whose negative class is real footage, not synthesized knob extremes.** `CheckSpec.entropy_floor = 0.90` is measured against two real classes — eight shipped episodes and eight synthesized conductor pairs — but its NEGATIVE class (six deliberate damages at legal knob extremes) is entirely synthetic, so the floor's 1.2% margin (design §0.4) has never been tested against a grade an author actually pushed too far, only against ones pushed there on purpose for the measurement. Blocked on a run graded after R1.1 (mood no longer silently ordering a grade), so the run's own damaged episodes, if any, are a real negative class rather than noise from an unrelated defect. | S | [grade-sensor-references design](specs/2026-08-31-grade-sensor-references-design.md) §10 row 1, §9.1 |
| ○ | **Let the conductor solve the tone pair THROUGH the post-tone knobs, then re-block cross-episode agreement.** `match_grade` measures at identity and the post-tone knobs (`black_point`, `highlight`, `shadow_red`, …) then displace the delivered result by up to 4.0 units on real footage and 12.50 on one real episode (design §0.2) — this is exactly what turned the OLD `tone_match` gate into a deadlock, and is why `grade_faithful` demoted cross-episode agreement to the advisory `target_dev` (§2.1) rather than fix it. An iterative solve — author the tone pair against the FULL chain's predicted output, not the bare crop — would let `target_dev` become a gate again without re-opening the deadlock. | M | [grade-sensor-references design](specs/2026-08-31-grade-sensor-references-design.md) §10 row 4, §2.1 |
| ○ | **Measure the length band against real footage and genre — R1.2's second half.** `carve.DEFAULT_BAND = (1.2, 4.0)` is the same first-cut pair the old `WIN_MIN`/`WIN_MAX` module constants held; mood-contract (0.8.0) made the band selectable and impossible to change silently, not *right* — no number in it was measured against taste. The right floor/ceiling are unknown and genre-dependent and must be measured, not typed. | S | [mood-contract](specs/2026-09-03-mood-contract-design.md) §7, R1.2 |
| ○ | **Explain the operator's "pull toward two seconds" against the run's own drafts.** mood-contract (0.8.0) ruled out both mechanisms the retro's R1.2 named, without explaining the impression itself: the delivered reel's median shot was 4.10s — *above* `nostalgic`'s own declared 2.0–4.0s `asl` ceiling — and the carve floor was already 1.2s before this slice touched anything, so neither the preset band nor `WIN_MAX` produced it. Whatever did is still unexplained. | S | [mood-contract](specs/2026-09-03-mood-contract-design.md) §0.4/§8 |
| ○ | **Re-derive `W_PRESENT`/`W_MOTION`/`W_STABLE` against a pool where presence varies.** The three weights are first cuts calibrated on one drone shoot, and the largest of them (`W_PRESENT`, 0.44) separated **3 windows of 1508** on the only real pool — which shows the term is currently harmless, not that it is well-weighted. Re-weighting needs a pool with real presence variance, which does not exist yet. | S | [unmeasured-named design](specs/2026-09-10-unmeasured-named-design.md) §7 |
| ○ | **A masked `subject`, instead of the route's bbox.** A box over water contains water, which is exactly why design §0.3 measures the subject as the **worst** mid reference (sd 21.0, against the background's 14.4) and the best toe one. The seg model already runs at intake and its masks have been discarded since 2026-08-04. Costs a `CACHE_VERSION` bump or a fresh seg pass. **Sharpened 2026-09-16**: the dE00 grade description now reads the same box, so a **second** sensor is waiting on this mask, not only the tone stage. Closing the dE00 sampling-box row (sensor-provenance §0.2) made the box's SIZE and its fallback VISIBLE — it did not make the box a subject, which is this row and only this row. **Not a half of R2.1**: R2.1's two folded rows are the dE00 sampling box (closed 2026-09-16) and chroma agreement (closed 2026-09-17, by measurement, not a target — see the chroma-spread design); this is named-regions §7 row 2's own row and was never folded into R2.1. | M | [named regions](specs/2026-09-15-named-regions-design.md) §7 row 2, [sensor provenance](specs/2026-09-16-sensor-provenance-design.md) §5 |
| ○ | **Re-extract the real run's segments through today's `extract` so the region-consistency table can be re-measured on SOURCE.** `plan_ungraded` refuses four of the eight (ep1, ep3, ep5, ep6) as `pc` — they predate the 0.3.1 segment range contract — which is why design §0.3's cross-episode spreads are measured on DELIVERED clips that already carry each episode's authored tone pair, saturation 0.92, `shadow_red` 0.1 and `mid_blue` 1.2. The toe's direction and magnitude do reproduce on the four readable sources; the spreads have no source-side reading at all. Same class as the `golden_ride.mp4` row above, on a run instead of a fixture. | S | [named regions](specs/2026-09-15-named-regions-design.md) §7 row 5, §0.6 |
| ○ | **A real `pix_fmt`-less camera source.** `color.refuse_ungradeable_plane`'s new third clause (design 2026-09-21 §2.2) is proven reachable only by a constructed fixture — the `stsd` fourcc of a segment built at test time from the committed `golden_ride.mp4`, patched from `avc1` to an unknown codec. No real proprietary or next-generation camera codec file exhibiting this property is on this machine, so the inference that such codecs are disproportionately the 10-/12-bit sources the depth guard exists for is marked as an inference, not a measurement (design §5.2). Would turn the constructed fixture into a measured one. | S | [unvalidated-shapes](specs/2026-09-21-unvalidated-shapes-design.md) §5.2, §6 row 2; blocked on footage |
| ○ | **Two unit-tier tests download `yolo11n-seg.pt` when the weights are absent, so an offline `-m "not integration"` run is not offline.** `tests/lib/test_intake.py::test_intake_records_the_band_it_carved_with` and `::test_intake_records_the_default_band_when_none_is_given` call the real `intake.intake()` on the ffmpeg-built `sample_clip` without the `ensure_model` stub their neighbours install (in the test, or through the shared `_stub_cache` helper), so with no `yolo11n-seg.pt` in the working directory ultralytics fetches the 6,182,636-byte file from GitHub. Measured 2026-09-29 on a `git archive` export (the weights are gitignored, so an export never has them), run under `sandbox-exec` with the network denied so that nothing was actually fetched: `-m "not integration"` gave 5 failed, 3732 passed, 306 deselected. Two of the five are these, each a `ConnectionError` naming `github.com/ultralytics/assets/releases/download/…/yolo11n-seg.pt`; the other three are export artefacts unrelated to the weights (`test_engine_stamp_on_this_repo_reports_a_sha` needs `.git`, and both `test_launcher.py` failures need the `.venv` symlink). `pytest.ini` documents the `integration` marker as "requires ffmpeg and/or model weights", so these two are either mismarked or should be cut off from the detector. **Stubbing `ensure_model` alone is not the fix, and it passes for the wrong reason** — reproduced 2026-09-29 in a weight-less export with the network denied: both tests pass, but only because `intake()` quarantines the clip. `intake_report.json` records `scanned: 0` and the download failure for `sample.mp4`, `FOOTAGE.json` has `clips: []`, and each test asserts only the `band` the run recorded from its own parameter (the second from the default), which survives an empty pool. On an online machine the worker's own `YOLO(model_path)` in `_iter_seg` would still fetch. The fix is either to stub `ensure_model` **and** cut the detector off as the neighbours do — `_process_clip` itself, as `test_pool_reaches_the_cap_and_never_exceeds_it` and eleven others do, or the seams beneath it, as `test_intake_builds_footage_and_writes` does — or to mark the two tests `integration`. | S | first seen in five reviewer scratch exports during unenforced-rules; pinned to these two tests in its Task 3; remedy corrected in its fix round 1 (the review found that an `ensure_model`-only stub passes for the wrong reason, and this reproduces it) |

## P3 — someday

Grouped by area. One line each; the source carries the reasoning.

**Front half / authoring**
per-reel `CONSTRAINTS.json` — `edit_plan` finds it beside `project.json`, so two variants of one reel cannot hold different standing rules (run-layout-lifetimes §8) ·
`split` — the last genuine layout, two sources into two rects (misc-engine, fit-solid §9, pan §12) ·
trend-scan SP4 (§5.4), which also unblocks reel-review's `trend_flavor` ·
shot-order grammar, "never two same-size shots back to back" (mood-preset §14) ·
real window dedup for the variety census's `available` (mood-preset §14) ·
carrying editorial constraints through `edl_to_reel`'s hand-authored front door (constraints §11) ·
more constraint kinds — `no_adjacent`, visual-similarity repeats (constraints §11) ·
a semantic version marker on `FOOTAGE.json` so `from_dict` can refuse a stale artifact (intake-motion-scoring §9) ·
gate the realized `asl` — `variety` records it and refuses nothing, and mood-contract's
R1.3 reconciliation only checks the DECLARED band against what was carved, never the
shot lengths the cut actually chose; worth building if a run ever shows the reported
overshoot mattering (mood-contract §7/§8)

**Front-half sensors**
a **subject-motion** anchor sensor — global frame difference cannot place a ramp
(measured: 7 of 8 real episodes are a flat plateau to it). Two candidate sensors are
already BUILT AND RUNNING, just not reachable from here: `carve.track_displacements`
(median displacement across shared track ids — identity-consistent by construction)
and a vidstab-subtracted curve, both of which `intake.py` calls today. What is
missing is not the code, it is a route from intake's tracking data to `lib/anchors`,
which runs at pacing time over an episode's source and has none. (This row said
"exist unwired" until 2026-08-19, which read as dead code and is the opposite of the
truth — it is a subsystem boundary.) Only with a route does auto-placing a ramp's
`at` become a question about wire format and clamping rather than about whether
there is any signal (deferred-measurements §4.5) ·
`carve._tight_unit` emits a window of exactly `win_min` per activity peak, which is
why 72.9% of a real 1508-window pool is one length, the floor exactly (mood-contract
§0.1/§8) — whether a tight candidate should scale with its own peak's width instead
of pinning to the band's floor is untouched here, a carve-sensor question ·
a **non-person subject sensor** — `classes=[0]` is right for heroes (a hero is a
person, deliberately out of scope), but nothing measures what a people-free frame
CONTAINS, so `VarietyReport.unmeasured` can only name the census's silence on such
footage and never fill it — a new instrument, not a report fix
(unmeasured-named §7)

**Identity**
hero-conditioned re-scan — re-measure windows holding a named hero after cast naming; **blocked on a face detector** (mood-preset §14, playbook P3) ·
auto-register a chosen hero back into the cast (cast-hero-pin §11) ·
sharpness/blur metric — the cv2 blocker is gone, the cost is now measurement work plus a `CACHE_VERSION` bump (footage-intake §8)

**Colour**
a tonal `band` INSIDE a region ("skin" as the brightest 30% of the subject, "wetsuit" as the darkest 40%) — measured and **rejected** 2026-09-15, not deferred for want of time: `dark40` sd 14.9 against the plain p5's 10.0, `bright30` 34.3 against the crop p95's 36.8. Re-open only with footage where a band beats the percentile it would replace, AND with an answer to its own circularity — a band defined by rank on the pixels being graded re-selects different pixels after the grade (named-regions §0.4, §7 row 1) ·
`regions.MIN_REGION_FRAC = 0.01` on a pool that discriminates it — a convention, not a measurement: on the only real pool one episode sits at 0.23% and the next at 2.19%, so every value in that interval selects the same seven episodes (named-regions §3.1, §7 row 6) ·
the grey-world white balance has never measured the footage — `manifest.DEFAULT_COLOR == color.TARGET`, so `gains_for_means` is exactly identity on every real episode regardless of content; closing it means measuring per-episode channel means over a named region AND answering what neutral means on footage that is mostly ocean. **M**, a slice and not a chore (chroma-spread §0.8, §6 row 1) ·
an absolute cross-episode chroma target, blocked on the seg mask — content cannot be separated from a grade mismatch on this footage today (four ungraded drone episodes already differ by 4.87 b\* with no grade applied at all), and the one referent every episode shares, the person, is the noisy region until it is a mask, not a bbox. Re-open when the masked-`subject` row above lands AND a pool shows a subject reference beating the crop it would replace — the same bar named-regions set for the rejected tonal `band`. **S** (chroma-spread §0.4, §0.5, §6 row 2) ·
a per-episode chroma actuator the conductor could solve through — today no automatic stage writes any chroma knob (`match_grade` authors only `tone_src`/`tone_dst`), so a chroma target with no actuator behind it would be a gate with no remedy, the same `tone_match` deadlock the luma target already cost its own gate once. **M** (chroma-spread §5.2, §6 row 3) ·
re-derive `chroma_spread_max` on a reel whose episodes are readable on both cameras — the only real reel's four Canon segments are `pc`, cut before the 0.3.1 segment range contract, so the 5.0 bar is derived from one camera's four episodes plus the suite's own single-clip fixture, never from a pool where both cameras have a render pair. **S** (chroma-spread §0.7, §5.3, §6 row 4) ·
the conductor reports no **within-episode outlier** — it pools three frames into one profile and never says they disagreed. ep0's residual of 8.0, the worst in the healthy class, is its third frame disagreeing with its first two (p95 spread 39 across the episode); the right answer for such a shot is probably to cut it, and nothing says so (grade-shipped-pixels §9.5/§10.4) ·
a **one-step converged re-render** — the frame-probe design deferred it, and the geometry seam makes it cheap: the routes are already frozen and only the colour block would change, so a converged grade could go straight to `--from-geometry` without a human turn (grade-shipped-pixels §10.3) ·
nobody has looked at the **extended shoulder** — `tone_arg` now spreads stored
codes 236..255 over eight outputs instead of one, but whether that looks better
is unmeasured and it touches 0.1247% of pixels on the frame it was measured on
(segment-range-contract §7) ·
`process_episode`'s preflight `_probe` **discards** `pix_fmt`/`color_range`, so on
the tracked path YOLO walks a segment before `plan_render` refuses it — wasted
compute only, and the guard was scoped to `plan_render` deliberately
(segment-range-contract, Task 3 review) ·
a range-relative mood displacement instead of the additive one — it would fix the
headroom collapse the additive table measurably suffers on bright footage (`epic`
keeps 31% of its vector at a median p95 of 250), at the cost of "moody" meaning
something different on every reel. Only worth it if the `mood-bias-ineffective`
note fires often on real briefs (mood-grade §2/§8) ·
mood as **chroma**, not only luma — a mood is warmth as much as contrast, and the
2026-08-17 slice moves only the luma triple the conductor owns; the warm/cool half
needs the cross-episode white-balance actuator already deferred below (mood-grade §8) ·
reconcile the two neutralizers, white-balance vs normalize-gain, into one authority (colour-stage §11) ·
crop-accurate / K-frame tone measuring instead of the whole frame at the midpoint (matchgrade §8) ·
cross-episode white-balance / cast matching (matchgrade §8) ·
`highlight_red_arg`'s shoulder (`hi`) formula is monotonicity-fragile near
`pull ≈ 1 − knee` for `knee ≥ 0.7` — a knee×pull grid scan found the
pre-existing code already broken there; unreachable today (the one production
call site never passes `knee=`), reported not fixed (cinematic-look §12) ·
`shadow_red_arg`'s densified curve keeps a one-code wobble near `lift ≈
ret` — **15** cells at `ret` step 0.01, not three: that count was a
`ret`-step-0.05 reading, and the three it named (0.15/0.14, 0.20/0.18,
0.20/0.19) are exactly the subset that coarser grid could see, up to 0.03
from `ret` (not "within 0.02"); step 0.1 has one, uncounted at the finer
step; the shipped `ret` has none (shadow-red-length-reconcile §1.2/§6) ·
`highlight_red_arg`'s sub-knee loop carries the same `1e-9`-bound-vs-`.4f`-
emission mismatch `shadow_red_arg` fixed on 2026-08-15 with
`SHADOW_RED_FMT_EPS`: a `knee` landing in a ~5e-5 band would emit a
duplicated control point and ffmpeg refuses the filter (exit 234).
Unreachable today — the one production call site never passes `knee=`, and
the default 0.60 is an exact 0.1 multiple — so it is filed, not fixed; the
one-line fix is the constant that already exists (shadow-red-length-reconcile
§1.2 M-2, found by that slice's whole-branch review) ·
a **chroma-damage sensor** — `grade_damage`'s luma-histogram entropy is blind
to chroma by construction, so a grade that destroys colour while leaving the
luma histogram intact reads clean; `naturalness`'s source-relative
`cast_shift`/`saturation_shift` are the only cover today, both advisory, with
bars set against the run that IS the complaint (grade-sensor-references §9.3,
§10 row 2) ·
make `grade_faithful`'s reference independent of `process_episode.build_reframe_spec` —
today the prediction shares the SAME manifest→plan map the real render uses, so a
bug dropping a field on the way from manifest to `ReframeSpec` breaks both sides
identically and passes; a second, separately-written path is a cure worth less
than the disease until something actually breaks this way (grade-sensor-references
§9.4, §10 row 3)

the `lutrgb` ban rests on a symptom with no recorded mechanism, and it does not
reproduce — measured 2026-08-19, every spelling renders correctly and identity is
exact to the code. The ban **stays** (one synthetic probe on one ffmpeg build does
not overturn a landmine written from a real corrupted render), but a candidate
misdiagnosis is on record: `check_episode.py` calls it "the seek/lutrgb
corruption", so the two were seen together, and the `-ss`-after-`-i` landmine
produces black frames on its own. Closing this needs the original render, which
nobody kept (luma-tone-transfer §5) ·
the tone shoulder's slope (`TONE_TOP_SLOPE = 0.35`) is what the remaining 1–2 units
of residual are made of — the output's top percentile is not the map of the input's
because the segment above the shoulder anchor is deliberately gentle. Working as
written, and nobody has asked whether 0.35 is right (luma-tone-transfer §8) ·
**nobody has looked at the new grade on a screen.** Chroma no longer rides the tone
curve, so a graded reel is visibly different — more saturated where the curve
compresses, less where it lifts. Correct for an operation named "tone", and still a
change no human has judged (luma-tone-transfer §8) ·
calibrate the luma transfer beyond two frames of one shoot — every number in its
design comes from one drone frame and one Canon frame (luma-tone-transfer §8) ·
the right sample count and placement for the dE00 grade description — **restated
2026-09-16**: there are no "five box-mean samples" any more. Sensor provenance put
the reading on `_grade_damage`'s own `(graded, plain)` render pair, so the count is
`color.FRAMES` (**3**) at `color.sample_times`, the placement is the plan's own
fractions shared with the entropy ratio that carries the verdict, and the count is
now RECORDED in the report (`samples`) rather than argued. What stays open is the
same question with new numbers: `delta_e` moves 0.05–0.33 between n=3 and n=5 on
four real episodes, which is why the ranking over the components was deleted
rather than re-sampled. **That figure is quoted, not shown** — design §0.5's table
carries the three components and no `delta_e` column, and §0.4's table is a
different quantity (it moves the baseline too), so a re-measurement starts by
re-taking it — nobody has shown 3 is right,
only that it is stated (grade-delta-sensors §9.5, sensor-provenance §5) ·
a second calibration shoot for the **retired 5.0 dE00 bar** — the field this row
opened by naming, `CheckSpec.grade_delta_max`, does not exist anywhere in the tree:
it was replaced by `CheckSpec.entropy_floor` in 0.7.0 (the P1 row above, which R2.4
folded into, records the same correction), which measures an entropy ratio and not
a colour distance, so the dE00 has had no bar of its own since. Every number
behind the 5.0 dE00 bar comes from one shoot, one grade, and simulated
damage, and the whole healthy-to-damage gap is **0.75 dE00**. And those
artifacts were rendered by an engine that no longer exists: they predate the
segment-range contract (R2.0/R2.3, 2026-08-27, released as 0.3.1), which
removed a transfer error of **8.5 → 1.5 codes** on the 67-of-99 full-range
clips. The source side should decode near-identically, but the delivered side
of every pc-sourced episode moves by ~7 codes — measured through the branch's
own `colordiff`, **2.10–2.65 dE00** on a mid tone (2.48 on ep2's box mean),
more than 3x the whole gap the bar sits in. `5.0` does not move on that
inference; what settles it is re-running `check_episode._subject_delta_advisory` (the dE00 sensor `color_fidelity` became — blocking then, advisory now) over
the eight episodes **re-extracted under the 0.3.1 contract** and comparing the
per-episode medians against 0.89–4.29. **Harder since 2026-09-16, and the row must
say so**: that 0.89–4.29 reference class was measured source-vs-clip, and sensor
provenance moved the sensor onto the render pair — the same four episodes move
+0.84 / +0.14 / −0.68 / −0.47 on the baseline swap alone (design §0.4), which is
more than the whole healthy-to-damage gap the bar sits in. A re-measurement must
re-take BOTH classes on the new baseline, not compare a new reading against the old
numbers
(grade-delta-sensors §9.1, final review I-2; sensor-provenance §0.4) ·
`naturalness.BLOWN_FRAC`/`CRUSHED_FRAC` remain uncalibrated — one data point
(`blown_highlights` fired once, plausibly) and zero (`crushed_blacks` never
fired on footage that never crushed) (grade-delta-sensors §6) ·
the two colour sensors do not share a baseline on a **stabilized** episode —
`check_episode` compares against `<project_dir>/stabilized.mp4` (the file
reframe consumed), `episode_qc._source_reading` always reads
`ep.manifest["segment"]`. `probe.source_for` already resolves this correctly;
routing `episode_qc` through it fixes it (grade-delta-sensors §9.8, final
review M-1) ·
give the reviewer more frames per episode if the new `colour` axis proves noisy on a
real run — `contact_sheet strip` already takes any file and any range, labelling
cells with absolute timestamps; evidence first, not built ahead of it
(colour-convergence-retire §9.3, §10) ·
put a per-episode grade-movement table in the reviewer's packet so the `colour` axis
can cite a number instead of judging blind — `color_fidelity` already writes
`delta_e`/`delta_l`/`delta_c`/`delta_h` per episode into `build/ep{i}/report.json`,
which every render wipes; `EPISODE_QC.json` is the candidate non-wiped source
(colour-convergence-retire §9.4, §10) ·
`grade_faithful`'s advisory `target_dev_reason` distinguishes "no target" from
"target exists but nothing bound", but collapses at least four different causes
of the second into one string — a flat-source/within-eps conductor skip, a
hand-authored pair that misses the target, every prediction failing to build, or
some mix, are all `no-episode-bound` today; a reader still has to open
`MATCH.md` or the EDL by hand to tell which (grade-sensor-references design §9.7,
final review I-3) ·
`grade_damage` and `grade_faithful` name the same shape of absence in different
words — `check_episode`'s not-checked reason is `"no render plans"`/`"no source
clip"` against `check_reel`'s `"no-predictions"`/`"no-episode-predicted"`/
`"no-prediction"`, and the advisory flag is `advisory_delta_e` on one and
`target_dev_advisory`/`target_dev_reason` on the other. Real, but a convention
pass over strings a QC judge and a router both read is its own change, not one
folded into a merge-eve review (grade-sensor-references, final review,
deliberately out of scope) ·
`check_episode._region_pairs` re-gathers the full mask once per channel — `plain[i][m]` and `graded[i][m]` are each evaluated three times per frame, six whole boolean-mask gathers where two would do, and on the crop-fallback path `m` is all-ones so every one of them copies the whole ~6 MB frame. The `_box_mean_rgb` it replaced hoisted its slice once. A one-line hoist recovers 3×; no correctness impact, and no run has yet shown the cost mattering (sensor-provenance, final review) ·
`check_reel`'s `grade_faithful.frames` reports ONE episode's count under a comment that says "per episode" — it is `len(spans[0])`, the first PREDICTED episode's span length, and its range today is `{0, 3}`, because `color.sample_times(dur)` returns `color.FRAMES` entries for every `dur`. What the field genuinely tracks is a change to that call, which is what it was built for; what it does not track is a per-episode count, and if the counts ever diverge it silently reports the first one's. Either carry the per-episode list or rename it for what it is (sensor-provenance §2.5, final review) ·
`frames` and `samples` sit adjacent in one flat `grade_damage` block with different definitions and nothing anywhere explaining either — `frames` comes from `gradedamage.evaluate` and counts render-pair frames, `samples` comes from `color_fidelity.evaluate` and counts non-empty mask pairs. They legitimately differ (a subject that leaves the frame for one of three samples can give `frames: 3` alongside `samples: 2`), but only the `samples: 2` half is pinned — by a direct call to `_subject_delta_advisory`, whose returned dict carries no `frames` key at all (`tests/test_check_episode.py:214`); the file's only `"frames": 3` (`:312`) is a hardcoded `gradedamage.evaluate` stub in the blocking-verdict test, which asserts nothing about `samples`. Neither episode-qc skill file names either field, so the judge reading them has no way to know that one is not a typo for the other (sensor-provenance, final review) ·
the **L3 colour-knob one-shoot constants** — `MID_BLUE_BAND`'s "the midtone
window skin sits in on this footage" and `shadow_red_arg`'s neoprene reference
are the same class of leak the unmeasured-named audit found elsewhere in this
tree, in optional knobs a reel that never sets them does not touch — a
separate blast radius, deliberately split out when that slice was scoped
(unmeasured-named §7) ·
Nothing machine-checks that the QC judge's skill files describe the report shape the code emits. This slice shipped two skill files telling the judge that `background_fallback` is present only when the background could not be read, while `check_episode` sets it unconditionally — caught by a human reviewer, not by a test, and only after it had been written twice and carried to a third surface. `tests/test_skills_contract.py` already machine-checks a skills Rules block against `EpisodeFinding`'s own fields, so the shape of the check exists; what it would need is the set of keys `_subject_delta_advisory` and `_grade_damage` actually emit, compared against the field names those two files name (sensor-provenance, final fix-wave re-review)

**Moves — geometry and time.** These move the frame or the clock, ride the
tracked route, and are judged by `check_episode` like any crop.
scenery zoom, Ken Burns over a subject-less shot (subject-anchored-moves §11) ·
easing for zoom and pan travel (subject-anchored-moves §11, pan §12) ·
`minterpolate` interpolated slow-mo — real intermediate frames instead of duplicates (speed-ramp §13) ·
speed-**up**, `factor > 1` (speed-ramp §13) ·
pan tilt (Y motion) and a pan over part of a clip (pan §12)

**Look — image treatment. The tail of #9, whose vignette + bookend fade half
landed 2026-08-13 (cinematic-look).**
Nothing here moves the frame; it tints, darkens or textures it, so none of it
touches the route or the composition checks. **Grain** (`noise`) joins this
line rather than the landed half — measured and priced out, not merely
deferred for time: at the delivery profile's own crf 18, `noise=alls=8` (the
first setting with any real presence) costs **×4.36** the file size, `alls=12`
**×8.82**, `alls=20` **×14.08** — a 30s reel goes from ~37MB to ~160MB at the
cheapest useful strength, and the platform re-encodes on upload anyway, so the
cost is paid and the grain is then destroyed by someone else's encoder
(cinematic-look §11.2/§12). Also here: film LUTs (need licensed asset files —
a distribution question before a code one), halation/bloom, light leaks,
chromatic aberration, letterbox bars (wrong on a 9:16 reel, where the `fit`
layout's background already does the job).

> **#9 is one item split across three buckets** — P1 built the vignette +
> bookend fade, each with a measured visibility proof (2026-08-13,
> cinematic-look — closing #18 alongside it), P2 biases the grade by mood
> (the long-deferred "mood LUT", still open), and this line holds the rest,
> now joined by grain. Landing P1 does not close #9 — it stays open until P2
> and this P3 line land too.

**Music**
a real downbeat detector — madmom or a trained model instead of a bass-band
heuristic. This is the honest fix for the 2026-08-17 finding that the current
one works on **one real track in five** and cannot be made to work on the other
four; the confidence gate that shipped only makes it say so. **M**, and it
brings a new dependency (downbeat-confidence §9) ·
calibrate the positive class on more than one song — everything the gate's
threshold rests on separates **one** positive track from four negatives; the
negatives are well sampled (97 windows), the positive is 27 windows from one
song (downbeat-confidence §9/§10) ·
meter beyond 4/4 — the downbeat detector assumes it, so a 3/4 track silently gets a wrong bar grid. **One of two known premise failures since 2026-08-17**, and the smaller one: the kick-marks-the-bar assumption fails on more music than 3/4 does (music-outro-fit §10/§11.3, downbeat-confidence §3) ·
real librosa **section** detection — the outro fitter approximates a phrase boundary with a bar line; segmentation would find the real ones (music-outro-fit §10) ·
a check that HEARS the delivered audio — the same hole the cinematic look has, now with a second occupant (music-outro-fit §11.5, cinematic-look §11.1) ·
whole-spine re-fit across in-point candidates — the surviving half of the "re-pick `MUSIC.start_offset`" row, now in ⊘ Won't do because its back-edge form is measured dead (music-outro-fit §0) ·
fit a RAMPED closing episode instead of skipping it — `play_dur()` is non-linear in `dur` once a ramp is present, so the outro fit refuses to move it; inverting `ramp_extra` the way `_bind_pacing` does would close it (music-outro-fit §5/§12) ·
adaptive hook length instead of a fixed `HOOK_BEATS` (pacing §10) ·
per-section mood arc (mood-match §9, pacing §10) ·
beat as a hard gate, once a cut can be re-trimmed (music-spine §9) ·
a migration for `EDL.json` files with no `base_dur` — they keep the old fixed-point deadlock forever; no auto-migration and no refusal were added on purpose, since either would touch the hand-authored SP1 front door this project keeps deliberately open. A one-shot re-projection from `selection.json` could fill the field, or the three-command detour stays the answer for these artifacts forever (pacing-fixed-point §9/§10) ·
the digest's audio-unreadable rung falls back to a check that cannot see a window change — when `MUSIC.json`'s track cannot be read, `build_edl`'s identity ladder falls back to comparing tempo alone, which is named as not-checked but still blind to the SAME track re-analysed at a different `start_offset`; recording `start_offset`/`duration` on `Spine` beside the digest would let the fallback compare those too (pacing-fixed-point §4.1/§9/§10) ·
calibrate the outro residual against perception — `check_reel`'s advisory `outro` check keys `passed` on `_LENGTH_TOL` (0.5s), a reporting boundary borrowed from the length gate, not a measured answer to how far a fade may start from a bar line before the ending stops resolving; same open class of question as `outro.TAIL_MIN` above (pacing-fixed-point §6/§10) ·
a real-ffmpeg proof of the length absorb's outro refusal — design §7 asks for a reel short by more than `_LENGTH_TOL` and less than `length_retime_max`, delivering with `outro` absent and stopping-and-reporting with it present; the branch proved both only against a monkeypatched `check_reel.run` (pacing-fixed-point §7/§9, final-review Finding 6) ·
enforce `SPEC.length_s` rather than only logging the cross-check —
**unblocked 2026-08-15**: the length diagnosis found the target this would
gate (`EDL.target_dur`) already equals what the master delivers, and only a
stale `PACING.json` ever disagreed (length-retime §9,
shadow-red-length-reconcile §2) ·
music-less dual-emit + trending-sound sidecar, §5.14 (music-spine §9, using-montage §5) ·
a SPEC field for ambient / SFX instead of only `ReelManifest` flags (ambient §9, sfx §9) ·
per-episode ambient level or mute (ambient §9) ·
rank candidate music windows on energy agreement, not only grid quality —
`build_pacing` picks the winner with `(fit.level_n if fit.fits else 0, -fit.worst)`
and nothing in that tuple sees whether the window's energy arc matches the cut's
rhythm, which is the stage's one real choice. Deferred on evidence, not doubt: the
only A/B pair on disk agrees on both criteria (window A wins the grid AND the
agreement), so any weighting between them would be typed rather than measured
(named-absence §1, §7) ·
a window whose beats start well into the reel is accepted — `pacing_B`'s first beat
is at 9.74s, its slot 0 carries `dev: 7.14`, and `build_pacing` neither refuses it
nor ranks it down; `Slot.beats_in` now makes the resulting hole visible in the
report, which is the whole of what this slice did about it (named-absence §7)

**Reel / QC / delivery**
secondary-aspect re-reframe on deliver — *the item that pointed at a "Phase F" which never existed* (reel-back-half §9) ·
`variety` auto-fix in loop-2, needs a front-half fixer (reel-retry-loop §8) ·
resumability / run-state persistence for the reel loop and the EDL run — deferred by four separate designs; only intake ever got it (reel-back-half §9, extract-spine §7, reel-retry-loop §8, edit-plan §7) ·
horizon-level detection (episode-qc §13) ·
auto-route a blocking QC finding into a re-render (episode-qc §13) ·
bound the outer re-judge loop — nothing caps how many stop → re-judge → phase-2
cycles a reel can take; `rm.cap` bounds attempts *within* one `build_reel` call and
nothing bounds them across calls. Each cycle needs a human or an agent to dispatch
judges, so it cannot spin unattended. Name a real case before inventing a constant
(re-judge §8) ·
pixel/CV subject detection for safe zones, and a hard gate with a re-frame actuator (safe-zones §11) ·
a reviewer panel instead of one subagent, and judging real playback rather than stills (reel-review §7) ·
stamp the other six run artifacts with provenance (attested-run §12) ·
multi-reel fan-out — `reel_count > 1` now refuses loudly instead of silently making one (reel-brief §7, reel-review §7) ·
calibrate the look gate's constants (`VIGNETTE_MIN_FRACTION`/`FADE_BLACK_MAX`/`FADE_SOURCE_MIN`/`VIGNETTE_FLOOR` in `lib/lookcheck.py`) on real footage — measured, but on synthetic patterns and one encode profile (frame-probe-look-gate §11) ·
generalize the frame probe to the other QC axes, composition and path smoothness — `RenderPlan` + `with_tail` are axis-agnostic, only colour is wired this slice (frame-probe-look-gate §11) ·
a titles-only delivery — and even an explicitly EMPTY `TITLES.json` (the predicate `_verify_look`/`lookcheck.evaluate` use is `titles is not None`, a path was passed, never "the parsed `Titles` has items" — filed at this slice's own Task 5 but never promoted to this file) — still pays the full 3-frame decode (5 subprocess calls) that `evaluate` never reads for anything but a permanent `not-checked` finding; gate the sampling in `_verify_look`/`probe_look` on `vig or fade` (frame-probe-look-gate, whole-branch review) ·
`provenance.verify_delivery`'s detail for an unattested file reads "this file was not produced by deliver()" — literally false for the look-gate-withheld case (`deliver` DID run and DID write `REEL_v{n}` before refusing); and `look_checks` (the gate's own findings, present in a WRITTEN attestation) is never surfaced by `montage status`/`verify`, so a `not-checked` vignette or fade reads no differently from a passing one at either command (frame-probe-look-gate, whole-branch review) ·
`grade_faithful` names one episode but nothing can re-render just that one —
`edl_to_reel`'s only render entry point, `--from-geometry`, always renders every
episode, so recovering from this stop pays a full N-episode re-render and a full
episode-qc re-judge, the exact waste the `episode-qc-reprocessed` remedy
(using-montage step 15) was built to avoid for its own stop. `build_reel`'s own
retry loop already reprocesses ONE episode in place for a `black` hit
(`process_episode.process_episode` on that episode's own manifest and
directory); a CLI entry point onto the same call, or widening
`_REPROCESS_CLASS`'s reach into a bounded per-episode retry, would close it for
`grade_faithful` too (grade-sensor-references, final review I-2) ·
`episode_qc zoom` subcommand — wraps contact_sheet strip and would itself need
naming in the same template it exists to serve (legible-evidence §4/§8) ·
pack a high-resolution artifact per episode by default — pays decode on every
episode to guess timestamps the judges choose themselves (legible-evidence §4/§8) ·
`episode_qc validate` so a judge can check its own findings.json before it stops —
R10.6 asked "validate early OR state it", and stating it was the root
(legible-evidence §6/§8) ·
re-tile the storyboard 3×2 for portrait content — 392×698 → 441×784, 12 % on
process_episode's hot path behind a golden (legible-evidence §8) ·
measure READER_LONG_SIDE — not observable from inside this pipeline, so the 1568
stays inherited from PER_SHEET's own comment (legible-evidence §7.2) ·
give `provenance.stamp(inputs=)` a reader, or delete it — written once
(`EDL.json` recording its own `selection.json` input) and read in production
nowhere; either wire it into a freshness report for the eight artifacts that
carry no provenance at all, or stop the field implying a check that does not
exist (bound-reports §0.5) ·
find what rewrote the real run's EDL and dropped three authored tone pairs an
hour after the conductor — `MATCH.json` (this slice) makes the contradiction
VISIBLE, it does not diagnose it, and the tool transcript that would show the
cause was deleted before the retro (bound-reports §0.1/§7) ·
a marker with a lifetime for the window between `os.replace` and the
attestation — a process killed there leaves a complete, unattested reel
indistinguishable from a look-gate-withheld one; seconds of exposure against
the minutes §5 already closed (bound-reports §7) ·
`SHEETS.md` is the second markdown-only run artifact with no JSON twin
(`MATCH.md` was the first, fixed this slice) — it asserts nothing checkable
about another file, so it has no binding to gain, but it also has no
machine-readable form for any future reader (bound-reports §2/§8) ·
extend the `montage status` staleness reader to the optional stages —
`pacing` against `MUSIC.json` (already answerable off `Spine.music_digest`)
and `titles` against the delivered reel; neither ever blocked the real run
(bound-reports §6/§8) ·
`tone_drift` binds only the authored pairs and the episode count, so a report
where every decision is `skip` — the `within-eps` single-camera reel
`skills/match-grade/SKILL.md` calls routine, and the shape the router
produces on every reel — cannot go stale for any same-length rewrite:
measured, an all-skip report reads `fresh` against a totally re-cut EDL, and
a same-length re-cut that keeps the pairs also reads `fresh`. The design
cites `ReelGeometry.provenance.cuts` (`{source, start, dur, ramp}`, built
precisely so a re-cut is caught) as its own model; `MATCH.json` already
carries `measured` per episode and could carry the cut identity for free —
the design's §7 does not name this limit (bound-reports §1/§2, whole-branch
review I-3) ·
`_review_state`'s freshness check compares `Path(judged).name` only, though
design §3 promises a `Review.reel` naming a path outside the deliveries
bucket reads as stale — "the honest answer for a hand-pointed path too."
Measured: a review naming `<run>/elsewhere/REEL_v1.mp4` while
`deliveries/REEL_v1.mp4` is newest reads `fresh`, and `verify` then re-hashes
the OUTSIDE file and calls it `bound`. The one-line fix is the full-path
comparison the design already argued for (bound-reports §3, whole-branch
review M-2) ·
a combined tidy of small `bound-reports` nits, most still open:
`_verify_review`'s docstring says "Three states" but the function returns
six (`absent`/`unreadable`/`unbound`/`missing`/`digest-mismatch`/`bound`);
`_verify_review(reel_dir, out)` never reads `out`; the reused `missing`
detail renders a double space and implies a file existed and vanished when
the reel was never named at all; `runlayout.partial_path`'s docstring still
says "all three globs" now that a fourth reader, `montage._newest_delivery`,
globs the same bucket (the claim itself still holds — the dot prefix
excludes the partial here too — only the census is stale); and four
spellings of one remedy are scattered across `matchgrade.py`/`montage.py`,
two of which omit `--geometry` and so name a command argparse rejects
outright. **One item already fixed by this session's audit, 2026-09-09**:
`docs/build-status.md` and the design both named a `tone_drift` signature
that never existed (`tone_drift(report, pairs)` / `tone_drift(match, edl)`
against the shipped `tone_drift(decisions, pairs)`) — corrected in both
places; the rest of this row stays open. The natural first instalment of the
existing open row on `grade_damage`/`grade_faithful` naming the same shape
of absence in different words (bound-reports, whole-branch review) ·
this slice's near-miss looked like R2.4 (folded into the P1 row above on
2026-09-29) but is a different mechanism —
a RENDERED value (`max_speed`) with no manifest field at all, not a THRESHOLD
widened by hand with no reason recorded — so R2.4 stays open, unmerged and
untouched by this row (retry-record §6) ·
recording the accepted attempt *number* on `ReelEpisode`/`EPISODES.json` —
not needed once this slice's sidecar record landed: the mechanical
`report.json` already carries `attempt`, and after the fix the report a
re-pack reads is the reprocess's own (retry-record §6) ·
a machine check that every `ReelEpisode.path`/`.meta` sidecar actually
resolves — this slice's `epdir` fix makes it correct BY CONSTRUCTION, not
checked; nothing asserts it (retry-record §5.5/§6) ·
record that a reel-level reprocess replaced a stabilized episode's frozen
route — `build_reel` passes `route_path=None` and re-tracks, so the previous
round's route is gone with nothing saying it was replaced; `TrackMeta`
already carries provenance bits (`degraded`, `stitched`) a "re-tracked at
round N" bit would join, and nothing reads it today (retry-record §5.4/§6) ·
an integration fixture that reprocesses an episode and then re-packs it —
`tests/integration/test_episode_qc.py` packs real episodes but none of them
has ever been reprocessed, so design §4.6 ("the packet stops being mixed")
is covered only structurally, by the unit-level reprocess-then-pack tests,
never by an end-to-end one (retry-record design §4.6, plan self-review) ·
retry-record design §2.3 still describes `_source_reading`'s drift guard as
catching `RuntimeError`, which was true when it was written and is now
incomplete: the whole-branch review found `probe._refuse_on_drift` opens a
SECOND sidecar through `CropPath.from_json`'s bare `json.loads`, so the clause
was widened to `(RuntimeError, OSError, ValueError, TypeError)` and the design
was not re-worded to match. Factually true, materially incomplete — a reader
implementing the same guard elsewhere would under-widen it, which is the harm
that made that finding blocking in the first place. Parked rather than fixed
because the protocol allows one fix wave and this surfaced in its re-review
(retry-record whole-branch review, fix-wave re-review residual) ·
`build_reel._predict` builds every episode's `grade_faithful` prediction ONCE,
before the retry loop's first reprocess, and nothing rebuilds it afterward — so
a reprocessed episode's entry in `predicted` can describe a render `build_reel`
has since replaced. The adjacent `chroma[item.idx]` IS refreshed after a
reprocess, with a comment explaining why (the episode is re-rendered and
check_episode measures it again); `predicted` carries no equivalent. This
branch enlarges the affected set rather than shrinking it: before it, a
retried episode's rebuilt plan disagreed with the frozen sidecars and
`_predict` returned `None` for it, named in `not_checked`; now that
`rendered_params` lets the rebuild agree, `_predict` returns a real profile
that a LATER reprocess in the SAME round can go on to invalidate.
`grade_faithful` is blocking at a 4.0 ceiling, so a stale prediction can pass a
reel that should have stopped, or stop one that would have passed (retry-record,
whole-branch review Minor 1)

**Titles**
libass/ASS rendering · per-episode titles · the full pixel-level safe-zone gate for
the **subject** — the titles half landed 2026-08-19 (`titles.zone_overflow` refuses a
staircase that would render into the app's chrome, measured at 244px on the reels
table), and what remains is **the same capability the Reel/QC group's "pixel/CV
subject detection for safe zones" needs; one measurement, two consumers, so build it
once** · `x`-axis containment for titles — the gate's band is rows only, so a very
long line at a large `scale` can overflow the left/right margins unchecked
(titles-pixel-gate §9) · the gate reads no TEXT: proving ink appeared is not proving
the words are the author's, and any font puts ink in the band, so a WRONG FONT passes
(§9; the glyph metrics `_layers` already computes would close the font half) · titles
in the frame probe — they are burned at `deliver`, so converging a title's position
still costs a reel encode (§9) · a ONE-CHARACTER title clears the evidence floor by
only 1.9x, the thinnest legitimate margin in the table (§3.4) · calibrate
`TITLE_INK_DELTA`/`TITLE_MIN_FRACTION`/`TITLE_BAND_PAD` on a second shoot — all three
are measured against one delivered reel plus a synthetic corpus (§10) ·
cross-platform font install (titles §7)

**Docs / test scaffolding**
the edit-plan knob-coverage test proves a field NAME is present, never that the
explanation beside it is correct or current — it stops the silent half of the
drift, and a word pasted into a table cell passes it (cheap-P2-chores §2.2) ·
`montage status` surfaces the editorial rules without checking them against the
current cut — it never sees an EDL, so it can say which rules exist and not
whether they hold; and a DELETED `CONSTRAINTS.json` still passes everything
everywhere, exactly as constraints §10 already recorded (cheap-P2-chores §3.2) ·
`multi_window_clip`'s detection stream is faked like every other intake
integration test, so the new window-pool proof covers the carve and pool-scoring
plumbing on real bytes, NOT the motion sensor's judgement — the sensor still has
no real-footage proof, which is the calibration row's territory
(cheap-P2-chores §4.1) ·
the `noqa: BLE001` on `build_reel._predict`'s broad `except Exception` is
inert — nothing there currently raises a non-`Exception` the lint would
otherwise flag — kept because the guard is right regardless
(grade-sensor-references Task 7) ·
the twelve remaining skill bodies have no page structure — seven are under
10 KB and do not need one, but `episode-qc` (16.3 KB), `titles` (13.8) and
`match-grade` (13.8) are the three that reach the 26 KB budget first, and the
addition that takes one of them there is what should force the question, not a
sweep now (reachable-instructions §6 row 2) ·
whether `edit-plan`'s remaining body is ONE coherent procedure or two has not
been measured — §2.5 split it along the subject boundary measurement made
obvious (the field reference, the convergence loop), and the residue was never
asked the same question (reachable-instructions §6 row 3) ·
a reference page's prose is not checked against the code it describes: the
stage index is generated and byte-pinned and every page is proven to EXIST and
be reachable, but a page can still describe a flag that no longer exists —
`tests/test_cli_help.py` knows every flag from the parser objects themselves
and nothing joins the two (reachable-instructions §6 row 4) ·
the router split gave the step numbers a fifteenfold typed home — 15 page H1s
(`# match-grade — router stage 10`) plus 26 in-page cross-references ("step 9",
"step 13"), 41 numbers in all, none bound to `V1_STAGES`. §3.1 argued the stage
list must not get a third copy and the pages took one anyway, in a different
column: the generated table and the stubs are both checked, the pages are not,
so inserting one stage silently invalidates all 41 (reachable-instructions §6
row 5, S) ·
two runtime remedies spell a command the skills are forbidden to spell —
`scripts/lib/footage.py`'s stale-descriptor `ValueError` and
`scripts/project_init.py`'s module docstring both name
`.venv/bin/python -m scripts.…`, the §0.4 bypass, at exactly the moment an
agent is looking for a command to run; `BANNED_SPELLINGS` covers skills only,
and whether it should reach `scripts/` error strings is the open question
(found proving reachable-instructions F4, S) ·
the stabilize test in `tests/integration/test_grade_shipped_pixels.py`
(`test_predict_reads_the_stabilized_source_not_the_raw_segment`)
discriminates SOLELY via its `source_for` call-spy: raw and stabilized
`golden_ride` yield the identical crop profile on this fixture, so the value
assertion alone would pass a `_predict` wired to the wrong file too
(grade-sensor-references Task 7, same shape as Task 5's own finding on the
preflight-probe test; mis-attributed to `tests/test_episode_qc.py` until
corrected by the whole-branch final review, M-2) ·
the two-producer merge predicate has no machine check — a merge of two
independently produced mappings whose result survives AS a mapping and is later
tested for a key's presence. The 2026-09-21 sweep found three sites by hand and
2026-09-29 measured that none of the two survivors can host the defect, so an AST
check would find zero true positives today; whether it is worth its false
positives is unmeasured (unenforced-rules §2.2/§5) ·
designs are not moved off their authoring-time Status when a slice ships — of the
42 shipped designs that carry a Status statement (44 specs do in their first 40
lines; the umbrella spec has no ship event of its own, and this slice's own
design was in flight), 35 do not say their slice shipped and 7 do. Of the 35, 8
assert a pre-ship state that is now false ("not yet built", "ready for a plan",
"plan next", "pending … plan", "pre-implementation") and 27 carry only an
authoring-time label ("design", "design approved <date>"); counting only the bold
`**Status:**` form it is 33 of 40. The classifier reads the whole Status
paragraph, from `Status:` to the next bold field label or blank line, and not the
first line alone: `path-quality` and `track-stitch` open "landing the parked
hot-patch" and end "landed <date>". Whether to machine-check it (a Status that
still reads design-stage once its slice has shipped) or to flip it in the slice's
own version-bump commit is open; this design's own Status was flipped in its
version-bump commit, the first application (unenforced-rules §2.3/§5) ·
a `test_…` name cited in a `scripts/` docstring or comment is not checked to
resolve — and a pointer is a claim: rename the test and the text names nothing.
`color_fidelity.validate_chroma`'s docstring cites the test that pins its
messages, and unenforced-rules Task 1 added one guard for that one pointer
(`test_the_validators_docstring_names_the_test_that_pins_its_messages`). One
generic check (~15 lines: collect every `test_\w+` token under `scripts/`, resolve
each against the `def test_…` names and the `test_*.py` files under `tests/`)
would subsume it. Re-derived 2026-09-29: 26 distinct names are cited — 12 test
functions in 13 citations and 14 test modules — and all 26 resolve, so there is
no rot yet and this is the guard placed before there is (unenforced-rules Task 1
re-review) ·
`docs/build-status.md` is updated by 16 of the 208 commits since 2026-09-01 that
touch `scripts/`, `tests/`, `skills/`, `references/` or `bin/` (measured at
`464d7ef`; 12 of 193 counting only `scripts/` and `tests/`, 4 of 123 counting only
`scripts/`), against a standing instruction to update it in the same commit as
each task ([development-workflow.md](development-workflow.md), `CLAUDE.md`). It
is the other half of the sentence unenforced-rules deleted the checkbox clause
from, and it is honoured about as rarely as the clause was; that slice deleted the
one and left this one. Filed, not acted on: whether the instruction or the
practice is what is wrong is unmeasured (unenforced-rules Task 2 review)

**CLI / tool index**
`Stage.runner` names a tool and nothing checks the tool exists — `trend-scan`'s
runner is the literal string `"5.4 - not built"`, so any check needs a
deferred exemption; worth building only if a rename ever breaks a runner
pointer (rederivable-purpose §6) ·
ten CLI descriptions substitute a repo-internal pointer (`stage 5.2b`,
`§5.13 Slice B`) for a statement — §3.7 shows no honest machine predicate
separates them from a description that merely also cites; a prose pass is a
review item, not a gate (rederivable-purpose §3.7/§6) ·
the index as its own skill, reachable by name instead of by path — a
`video-grid:tools` skill whose body is the index would need no runtime root,
no `$VG` and no path, but costs a fifteenth row in the always-resident
listing and gives the same content a second home; worth building only if
path resolution proves to be the barrier in practice (rederivable-purpose §6) ·
the index answers *which tool*, never *is this tool right here* — a row says
`probe grade` exists and renders stills over a frozen route, but cannot say
that this is the moment in your run to reach for it; that judgement stays in
the perishable skill body (rederivable-purpose §6) ·
`tests/test_skill_convention.py` and
`tests/integration/test_skill_process_episode.py` both dequote a YAML
description with `.strip('"')`, which strips every leading or trailing quote
rather than parsing — latent only today (no current description starts or
ends with a literal quote), but a duplicated ad-hoc parser where
`yaml.safe_load` is already available (rederivable-purpose, Task 5/6 review
loop) ·
`toolindex.surface_labels()` ships with zero readers — it is the exact
function the plan ruled out wiring the index test to, since a walk that
missed every subparser would render no subcommand rows and report none
missing; it also carries no docstring saying so. Either delete it or give
it one (rederivable-purpose, final review) ·
`toolindex.SKILL_ROLES` is a second hand-written table and nothing pins
it — no test asserts its keys are real skill directories or that they are
disjoint from the stage keys, so a future `V1_STAGES` key colliding with a
`SKILL_ROLES` name would make `test_every_skill_states_its_conveyor_place`
silently take the role branch and stop requiring that skill's generated
position sentence (rederivable-purpose, final review) ·
the index's byte-pin compares the committed `references/tools.md` to
`toolindex.render_index()` in-process; nothing runs
`python -m scripts.montage tools` as a subprocess, the same emission gap
`test_the_real_entry_point_routes_through_build_parser` closes for
`--help` but unapplied here — a broken `tools` branch in `main()` would
leave the pin green while the regeneration command every failure message
names emits a file that fails it (rederivable-purpose, final review) ·
design §3.2 specifies two subprocess `--help` sweeps, top-level and
`<sub> --help`; only the top-level one was built. Run by hand for the
final review, all 16 subcommands exit 0 and print their description, so
nothing is masked today — but the sweep itself is still missing
(rederivable-purpose §3.2, final review) ·
`tests/test_tool_index.py::test_every_help_surface_has_a_row`'s hardcoded
`47` lands a newly added script RED on a count assertion whose message
reads as though the walk is broken; name the constant and the file
(`references/tools.md`) in the message so the failure reads as staleness,
not a bug (rederivable-purpose, final review) ·
`toolindex.position()` raises a bare `ValueError: 'x' is not in list` for
a skill that is neither a stage key nor named in `SKILL_ROLES`, instead of
failing through the crafted assertion message two lines below it in
`tests/test_skills_contract.py` — a fifteenth such skill gets a traceback
instead of the intended guidance (rederivable-purpose, final review)

**Packaging / runtime**
migrating a **pre-convention run** into `montage/` — not a `mv`: measured 2026-08-25,
artifacts carry absolute paths to OTHER artifacts, not only to footage
(`out/EPISODES.json` 57, `cast_candidates.json` 15, `cast.json` 10,
`out/EPISODE_QC.json` 8, each `.intake_cache/*/clip.json` 52 — every crop PNG), so a
move breaks the QC digest bindings and the delivery attestation built to notice
exactly that. A path rewrite, if ever wanted; until then such a run stays readable
where it is, because every driver takes explicit paths (run-dir-separation §5) ·
a rendered video **hand-copied among the footage** is still scanned — the run-dir
gate proves the run dir is not the footage dir, never that no `.mp4` beside the
clips is pipeline output, because an `.mp4` is an `.mp4`. Would need content
provenance at scan time (an attestation lookup, or a digest check against `out/`),
which is a slice and not a guard (run-dir-separation §6) ·
GitHub-remote marketplace (plugin-packaging §6) ·
a leaner plugin root and relocating the ~12 MB of weights out of the tree (plugin-runtime-resolution §6) ·
dependency **version** assertions in preflight (verify-runtime §9) ·
nothing gates that a run's instructions match its code at the CONTENT level —
0.14.0's check reports a version disagreement, and the fourteen stale bodies it
found are counted, not repaired; a content gate needs an answer to the cry-wolf
problem first (the version is the install key precisely because this repo bumps
once per slice) (plugin-staleness §7) ·
nothing verifies the recorded root is a checkout of the marketplace it claims —
`~/.config/video-grid/root` and `known_marketplaces.json`'s `installLocation` both
name a directory and are never compared, so a `setup.sh` run from a second clone
would point the skills at one tree while the plugin was installed from another,
and every check would still pass (plugin-staleness §7). Same family, found by
this branch's own review: `_plugin_id()` also trusts the clone's two manifests to
name the marketplace correctly, so a plugin filed under a *different*
marketplace name (`video-grid@anything-else`) reads as "not installed" and
passes too — a wrong root and a wrong marketplace name are the same unchecked
trust, reached from opposite ends (plugin-staleness §6) ·
the `gitCommitSha` the installer records is unused — it resolves in the clone and
yields an exact commit distance (392 on the machine 0.14.0 shipped from), strictly
sharper than the version and strictly noisier, since any docs commit moves it
(plugin-staleness §7) ·
the install record's shape is a third party's and versions itself —
`installed_plugins.json`'s own `"version": 2` is deliberately not interpreted
(§4's ruling stands), so a future Claude Code release that reshapes the record
fails in one of two directions: a `plugins` no longer a mapping blocks every run
with an unclearable remedy, or a moved id key reads as `()` and passes silently
— the worse direction, because it is exactly the self-off this check exists to
prevent. Worth acting on once one of those actually happens, or a second
consumer of the same file needs the shape validated for its own reasons
(plugin-staleness §6)

**Contact sheets**
a platform crop guide on each cell · a contact sheet of the delivered reel for CP3 · per-window multi-frame cells (contact-sheet §10)

## P4 — only on request

Real but low-value, or explicitly priced and found not worth it.

build **§6.1a layer 3** (descriptor continuity re-match) — deferred on measured
evidence, not on doubt that it is needed: the remainder over `stitch_ids` is real and
inverse, but seven real routes produced zero `continuity` failures and the shoot
offered one two-person opportunity, which did not swap. **Trigger:** a run producing
a `continuity` stop or an episode-QC `hero` finding naming a mid-episode swap
(deferred-measurements §2.5) ·
`checks.continuity` cannot see an ID switch between **adjacent** people — its
`4%-of-src_w` cap is a physically-impossible-teleport gate (4603 px/s on the run's
1920×1080@60 footage, the subject crossing frame in 0.42s), so a swap fires it only
when the two bodies are more than 4% of the frame apart. Nothing in code claims
otherwise; now nothing in the docs does either (deferred-measurements §2.4) ·
a per-episode mood override for the grade — the reel's grade is reel-level by
construction, exactly as its `look` is, and no request for it exists (mood-grade §8) ·
carry the measured phase margin on `MusicSpec` rather than only acting on it —
`_downbeat_phase` computes the winner-over-runner-up ratio and then discards it,
so a skill can say "this track has no bar grid" but never "and here is how close
it came". Not built because no consumer asked (downbeat-confidence §9) ·
`episode_qc pack --only <idx>` — re-packing all N episodes to re-judge one costs N
strip builds; measured at 8 episodes that is seconds, so this is convenience, not a
fix, and `pack` already preserves the `findings.json` being kept (re-judge §8) ·
no licence audit of the transitive dependency tree — the AGPL-3.0 declaration
(2026-08-17) was driven by ONE dependency checked by hand, `ultralytics`; nobody
walked the rest, and no lawyer read any of it (cheap-P2-chores §1.1) ·
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
the chroma-preserving vignette — a luma-plane blend or `geq` — if the corner
desaturation reads wrong on real footage; 26× the cost or a five-node graph,
for a difference that may be an improvement (cinematic-look §11.4/§12) ·
a per-episode look override — the reel's finish is reel-level by
construction, and no request for it exists (cinematic-look §12) ·
network reachability probes in preflight (verify-runtime §9) ·
cross-platform `setup.sh` and `bin/vg` — macOS/Homebrew is a stated project boundary (ffmpeg-baseline §9, plugin-packaging §4) ·
implementation plans must not hand a task a literal one-line `git commit -m` subject while the plan's own Global Constraints ask for a message that says *why* — five of this slice's six commits were generated exactly that way and shipped subject-only, and none of the five can be repaired now since amending is forbidden (shadow-red-length-reconcile, whole-branch review 2026-08-15) ·
a one-step re-render of a converged episode — `process_episode --route <frozen>` already skips tracking, so this is possible today, just not one command: the agent materializes the regraded manifest by hand (skill guidance, `edit-plan` colour-grade section) rather than a driver doing it in one call (frame-probe-look-gate §11) ·
`lookcheck.evaluate`'s vignette check reads only the MIDDLE of the three sampled mid-frames (`mid_master[mid]`/`mid_delivered[mid]`) — four of the six frames `_verify_look`/`probe_look` decode for it are never read, while the design's own §5/§6 cost tables price three frames as the unit of work (frame-probe-look-gate, whole-branch review) ·
`probe._render` does not dedupe frame numbers the way its sibling `assembly.frames_rgb` does (`uniq = sorted(set(nums))`) — two `times` that round to the same `n` make the `select` expression request that frame twice but ffmpeg emit it once, so `len(pngs) != len(nums)` fires the generic "a frame number is past the stream's end" message even though every requested time is well inside the stream (frame-probe-look-gate, whole-branch review) ·
no import-time assert that `probe._COLOUR_KEYS` is a subset of `Manifest`'s dataclass field names (filed at this slice's own Task 4 but never promoted to this file) — a colour field added to `EDLEpisode`/`edl.to_manifest_dict` later but forgotten from `_COLOUR_KEYS` is silently dropped by `regrade` (its drop-then-reapply reads only the named keys) rather than caught at import time; nothing machine-checks the set stays complete (frame-probe-look-gate, whole-branch review) ·
`ReelEpisode.path` defaults to `""` — a manifest entry missing it collapses `probe_grade`'s `epdir = Path(ep.path).parent` to `.` (cwd) and fails with an opaque `IsADirectoryError` out of `CropPath.from_json("")` (reproduced: `Path("").read_text()` raises `Is a directory: '.'`) rather than a named refusal pointing at the missing field (frame-probe-look-gate, whole-branch review) ·
`tests/lib/test_edit_plan.py` has a mid-file `from scripts.lib.pacing import Slot, Spine` (line ~250) — pre-existing and untouched by this slice, but every task that extended the file inherited the imports-at-top violation rather than fixing it in passing (pacing-fixed-point, Task 1 review) ·
when BOTH `Spine.music_digest` and `MusicSpec.track` are unreadable, `build_edl`'s logged `why` names only the spine ("this PACING.json records no music_digest") and never says the track was *also* unreadable — the fallback still runs correctly, only the diagnostic is incomplete (pacing-fixed-point, Task 3 review) ·
several new tests (`test_reel_orchestration.py`'s two outro-refusal tests, `test_check_reel.py`'s `test_an_unchanged_rung_reports_n_a_not_a_measurement` and `test_a_residual_past_the_reporting_tolerance_is_flagged_but_advisory`) still assert a subset of the returned object/detail rather than the whole thing, against this project's own whole-object-assert convention — inherited verbatim from the plan's literal test snippets, not an implementer choice; `test_the_residual_is_the_master_against_the_length_the_fit_asked_for` was fixed to a whole-`CheckResult` equality by the final review (pacing-fixed-point, Tasks 4/5 review; Finding 5) ·
`scripts/reframe.py:12` imports `ZoomSpec` from `scripts/lib/models.py` and never uses
it — pre-existing, introduced by the zoom-render slice (`3d28e2a`), untouched by this
branch; noticed during Task 4's review while auditing `reframe.py` for the
`color_correct` cascade deletion (colour-convergence-retire, Task 4 review) ·
**the ENCODE's own colour cost, which nothing measures.** Sensor provenance
(2026-09-16) put both sides of the grade description on the `(graded, plain)`
render pair, so the CRF-18 encode left the number: measured, the baseline swap
moves the reading by **up to 0.84 dE00** on four real episodes (+0.84 / +0.14 /
−0.68 / −0.47), against the old blocking bar's entire healthy-to-damage
separation of 0.75. That is a real quantity, now cleanly ISOLATED — and measured
by nothing, before or after: the old reading conflated it with the grade rather
than isolating it. Size S (the render pair and the shipped clip are both already
produced; the work is one comparison and a name for it). **Worth a row only if a
run ever shows it mattering** — it votes on nothing today, since the dE00 is
advisory (sensor-provenance §5, §6 row 3)

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
| Re-picking `MUSIC.start_offset` at the back-edge (length-retime §9) | **Measured dead 2026-08-14** and superseded by the "whole-spine re-fit across in-point candidates" row in P3: the shift the 2026-08-03 reel needed was 2.235 beats, and only a whole-*beat* shift keeps the existing cuts on the grid (two beats leaves the end 0.128s off; a whole-*bar* shift maps the grid onto itself and changes nothing). Kept as a row so nobody re-derives it (music-outro-fit §0) |

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

_Last updated: 2026-09-17._
