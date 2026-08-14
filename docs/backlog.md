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
it appears: **#9** (cinematic look) was split P1/P2/P3 — the **P1 look half
landed 2026-08-13** (cinematic-look: vignette + bookend fade, each with a
measured visibility proof); **P2 (mood biasing the grade) and P3 (the image-
treatment tail, now incl. grain) stay open, so #9 itself is not closed**. The
**episode-QC loop** is P2 for the re-judge and P3 for the auto-route; and
**reel length** is P2 for the diagnosis and P3 for the enforcement. Do not
close either of those two on its first row alone.

---

## P1 — next

| | Item | Size | Source |
|---|------|------|--------|
| ◐ | **Music ends mid-phrase** — **investigated 2026-08-14** against the 2026-08-03 run's own artifacts; findings below. First step landed the same day: **demucs is now a REQUIRED runtime component** and `choose_offset`'s mix-silence proxy is deleted. The out-point fix itself is still open and still needs the librosa **section detection** that pacing §10, length-retime §9 and music-spine §9 have each deferred in turn. | M | [#2](fixes-backlog.md#2-music-is-cut-in-the-middle-of-a-phrase), pacing §10 |

**What the 2026-08-14 investigation measured** (scripts under the session scratchpad;
every number is from the delivered `out/REEL_v1.mp4` and its own track):

- **Root cause confirmed, and it is structural, not a bug.** `MUSIC.json` records
  tempo, a flat beat list and a 2 Hz energy curve — *no downbeats, no bars, no
  sections*. `mix.py` trims the music to the master's length. So no stage in the
  pipeline is *able* to end on a phrase; the out-point is whatever the picture's
  length happens to be. In the run: reel 34.051s, out-point at track 80.044s,
  **0.96s past a bar line**.
- **The fade is not the problem.** It fires correctly — 18.1 dB over the last
  ~800ms, final 200ms at −33 dBFS — but the song is at full energy there (6.1× the
  gap threshold), so 0.5s ducks the chop without resolving the phrase.
- **Bars ARE recoverable, but not by the obvious detector.** Onset strength per beat
  phase: 4.313 / 4.285 / 4.267 / 4.309 — no signal, all four within 1%. Low-band
  (<150 Hz kick) peak per beat: phase 3 at 79.31 vs phase 2 at 42.03, ratio **1.89**,
  and the phase-3 beat is the loudest of its bar in **14/18 bars** (78% against 25%
  by chance). Any section detector should use the bass band, not novelty.
- **The triage hypothesis in [fixes-backlog #2](fixes-backlog.md) was wrong.** It
  assumed `--auto-start` had already placed the in-point in a vocal pause. Run
  `best_offset` on that track and it returns **0.000** for every plausible duration
  (25/30/33/34/42/45); `MUSIC.json` records 46.0. The in-point was hand-set, and the
  auto path would have started the reel at second 0 of the song.
- **There is headroom.** The analysed window is 42s and only 34.04s was used —
  **7.96s of already-analysed music**, so moving the out-point to a bar line needs no
  `beats` re-run. Nearest bar up is +1.22s; but the reel is already **+4.04s** over
  `SPEC.length_s` (30.0), and the only candidate landing *under* the brief is a 4-bar
  step down to 28.73s. "End on a musical line" and "hit the brief's length" pull
  against each other, and the stage must **report** that tension rather than resolve
  it silently.
- **A vocal-free half-second after the boundary exists, and there is exactly one
  usable place for it.** This was measured twice; only the second measurement is
  right. With no demucs installed the mix-silence proxy found **2** vocal-free spans
  in 228s and none in the window, which is what made the fallback's deletion
  obviously correct — but it is not evidence about the music. Re-run with real
  demucs (installed 2026-08-14): **19** spans in the track, **5** overlapping the
  reel's 42s music window. A first pass on demucs' own 2 Hz envelope still said "one
  usable bar line", and that was an artifact — a 2 Hz envelope has **0.5s bins** and
  the rule asks for 0.5s, so it cannot resolve the answer. At the vocal stem's full
  11.6 ms resolution: **2 of the window's 18 bar lines** can end the music with
  ≥0.5s of silence after, and the useful one is **bar 15 at stem 35.26s — +1.22s
  from the reel's current end, with 1.50s of vocal-free after it**. Stable across
  threshold fractions 0.10–0.30 (0.05 drops it to 1). Any gap sensor built for this
  must measure at frame resolution, not on the 2 Hz curve `MusicSpec.energy` stores.
- **The 1.22s is available, and the in-point lever cannot pay it instead.** The
  closing clip has **11.53s** of unused source after its episode, so extending is
  cheap in footage terms (35.26s reel = +5.26s over the brief's 30.0s, against
  +4.04s today — the tension to report, not resolve). Moving `start_offset` instead
  looks free but is not: the shift needed is **2.235 beats**, and only a whole-beat
  shift keeps the existing cuts on the grid — 2 beats leaves the end 0.128s off the
  bar line, and a whole-*bar* shift maps the grid onto itself and changes nothing.
  So the P3 row "re-pick `MUSIC.start_offset` at the back-edge" is **measured
  insufficient on its own**: it can only work as part of re-fitting the whole spine
  (pacing's two-axis search), never as a back-edge tweak.
- **`--auto-start` now answers.** With real vocal gaps `best_offset` returns
  **147.772s** for every duration tried (30/34/42), against the proxy's 0.000.
- **Cost of the requirement:** htdemucs separation measured **62.1s and 46.2s** on
  two runs over this 229s track — roughly **0.2–0.27× realtime**, paid once per
  `--auto-start`.

Two run-hygiene observations, neither the cause: `PACING.json` was stale from the
previously-chosen Manson track (tempo 140.625 vs the actual 110.294) — harmless,
because `check_reel` shows the cuts land on `MUSIC.json`'s own beats at 0.017s worst
deviation, so the EDL was re-bound after the swap; and `MUSIC_SHORTLIST` was built
from an explicitly-passed mood ("aggressive driving energetic industrial") rather than
`SPEC.mood` ("Fun and playful"), which the file mtimes confirm was already on disk —
an override, not a bug.

## P2 — soon

| | Item | Size | Source |
|---|------|------|--------|
| ○ | **The authoring skill documents every knob it has** — `edit-plan` should enumerate the full set in one place: layout / composition / grid / motion / pan / zoom / ramp / stabilize / smooth_window_s + the colour grade. Verify each against `models.ReframeSpec` first: a named-but-missing tool (curves, shadows) is a build-or-not decision, not a doc gap. | S | [#5](fixes-backlog.md#5-the-authoring-skill-must-document-every-modification-tool-it-has) |
| ○ | **Cheap 3-frame probe, now also folded: does the look actually render?** — render three frames with a new grade, measure, iterate; pay the full episode re-encode only once it converges. The 2026-08-03 run spent ~29 full re-encodes. Generalizes to effect *visibility*, not just colour — but it is a **run-time convergence loop**, not the same thing as the cinematic-look slice's per-effect visibility proofs, which are one-off measurements in the test suite (both exist now; neither substitutes for the other). The cinematic-look design adds a second reason: `check_reel` runs on the master, BEFORE `deliver` encodes the vignette/fade/titles, so **no gate today ever sees the look that shipped** — the same probe this row already owns is the cheapest real fix, generalized from colour to effect visibility. | M | [#10](fixes-backlog.md#10-cheap-3-frame-preview-to-converge-the-colour-grade-before-a-full-episode-re-render), cinematic-look §11.1/§12 |
| ○ | **Calibrate the look** — `LOOK_VIGNETTE_MAX` (0.6), the 0.55/0.45 plateau/falloff split, and every row of `MoodPreset.look` are hand-picked on synthetic test patterns; no real footage has graded against them yet. | S | cinematic-look §11.3/§12 |
| ○ | **Validate `outro.TAIL_MIN` against editing practice** — the 0.5s of vocal-free space a music boundary must leave is the project owner's assumption stated out loud, not a measurement or a citation. One named constant in one module, so re-tuning is a one-line change; check it against the literature on cutting to music. | S | music-outro-fit §11.1 |
| ○ | **Calibrate the downbeat detector on more than one track** — the <150 Hz band edge, the ±0.10s window and the phase-confidence margin are first cuts measured on one song (14/18 bars, ratio 1.887). A second genre is the cheapest next evidence. | S | music-outro-fit §11.3 |
| ○ | **`color.shadow_red_arg` has `highlight_red_arg`'s pre-fix sparse-anchor defect — worse.** Found while fixing `highlight_red_arg` for the identical flaw (three sparse anchors pin the spline AT three points, not the curve it draws between them): measured **−6** at `SHADOW_RED_MAX` against `highlight_red`'s pre-fix worst case of −3. It is the mirror function, and `highlight_red`'s own docstring cited "the shadow_red lesson" for a lesson `shadow_red` itself never learned. Same one-line densification fix, plus a probe test. | S | cinematic-look §12 |
| ○ | **Mood → grade** — bias `match_grade`'s common target by the brief's mood instead of taking the source median alone. This is the "§10 mood LUT" colour-as-a-stage deferred; #9's *look* half landed 2026-08-13 (cinematic-look), this is the grade half that remains. | M | colour-stage §11, matchgrade §8, [#9](fixes-backlog.md#9-cinematic-effects-library--mood-oriented-palettes) |
| ○ | **Re-assess §6.1a layer 3 against track-stitch** — both address a mid-episode hero ID switch, by different mechanisms (descriptor continuity vs geometric overlap-vs-gap). Decide whether a real remainder exists before building anything. | S | cast-hero-pin §11 |
| ○ | **Calibrate the first-cut identity thresholds** — `CAST_MATCH` / `CLUSTER_COS` / `MAX_CAST` are declared guesses; the distance distribution needed to derive them is already on disk in any real cache. | S | hero-reid §11, cast-hero-pin §11 |
| ○ | **Confirm the torchreid dep list on a clean install** — torchreid 0.2.5 declares **no runtime requirements at all** while importing six packages, so `pip install torchreid` succeeds and `import torchreid` raises (measured 2026-08-14: `gdown` missing, and `tabulate`/`Cython`/`h5py`/`imageio`/`yacs` absent too). `setup.sh` now installs all six explicitly and verifies on **import** rather than `pip show`, but that fix is **unverified** — it was written on a machine where the broken install already existed, so nobody has watched a clean run succeed. The suite's 1 remaining skip is this. | S | demucs-required slice, 2026-08-14 |
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
cross-episode white-balance / cast matching (matchgrade §8) ·
`highlight_red_arg`'s shoulder (`hi`) formula is monotonicity-fragile near
`pull ≈ 1 − knee` for `knee ≥ 0.7` — a knee×pull grid scan found the
pre-existing code already broken there; unreachable today (the one production
call site never passes `knee=`), reported not fixed (cinematic-look §12)

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
meter beyond 4/4 — the downbeat detector assumes it, so a 3/4 track silently gets a wrong bar grid (music-outro-fit §10/§11.3) ·
real librosa **section** detection — the outro fitter approximates a phrase boundary with a bar line; segmentation would find the real ones (music-outro-fit §10) ·
a check that HEARS the delivered audio — the same hole the cinematic look has, now with a second occupant (music-outro-fit §11.5, cinematic-look §11.1) ·
whole-spine re-fit across in-point candidates — the surviving half of the "re-pick `MUSIC.start_offset`" row below, now that its back-edge form is measured dead (music-outro-fit §0) ·
fit a RAMPED closing episode instead of skipping it — `play_dur()` is non-linear in `dur` once a ramp is present, so the outro fit refuses to move it; inverting `ramp_extra` the way `_bind_pacing` does would close it (music-outro-fit §5/§12) ·
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
the chroma-preserving vignette — a luma-plane blend or `geq` — if the corner
desaturation reads wrong on real footage; 26× the cost or a five-node graph,
for a difference that may be an improvement (cinematic-look §11.4/§12) ·
a per-episode look override — the reel's finish is reel-level by
construction, and no request for it exists (cinematic-look §12) ·
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
| 2 | Music is cut in the middle of a phrase | ◐ **P1** — investigated 2026-08-14 (root cause + six measurements in the P1 row above); demucs made required the same day; the out-point fix itself still open |
| 3 | Per-episode rendering and QC in subagents | ✅ 2026-08-08 |
| 4 | `setup.sh` installs everything; unavailable components warn and continue | ✅ 2026-08-04 |
| 5 | The authoring skill must document every modification tool it has | ○ **P2** |
| 6 | The router never asked about titles / effects | ✅ 2026-08-04 |
| 7 | Slow-mo is a first-class effect, and it changes the reel length | ✅ 2026-08-09 |
| 8 | Subagents must not be able to disable quality control | ✅ 2026-08-04 |
| 9 | Cinematic effects library + mood-oriented palettes | ◐ P1 look half ✅ 2026-08-13 (vignette + bookend fade, cinematic-look); P2 grade half ○ open; P3 tail ○ open (incl. grain, measured and priced out) |
| 10 | Cheap 3-frame preview to converge the grade | ○ **P2** |
| 11 | Freeze the engine during a run | ✅ 2026-08-04 |
| 12 | "Look, don't guess" — examine real frames | ✅ both halves (2026-08-05 selection, 2026-08-08 per-episode) |
| 13 | A quality gate must not be bypassable by manual assembly | ✅ 2026-08-04 |
| 14 | Editorial-constraint memory across iterations | ✅ 2026-08-07 |
| 15 | CP3 reel-review must not be silently skipped | ✅ 2026-08-04 |
| 16 | `VERSIONS.md` note bug — path logged instead of the reason | ✅ 2026-08-04 |
| 17 | Frame-moving effects stay subject-anchored and inside QC | ✅ 2026-08-08 |
| 18 | Cinematic effects were born as live patches — land them, verify they show | ✅ 2026-08-13 — zoom ✅ 2026-08-08, ramp ✅ 2026-08-09, look filters (vignette + bookend fade) + `highlight_red` + `outline-bold` ✅ 2026-08-13 (cinematic-look), each with a measured visibility proof |
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

_Last updated: 2026-08-14._
