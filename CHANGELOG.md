# Changelog

Releases of the **plugin** — the skills you install and the runtime they drive.
The top entry must match `.claude-plugin/plugin.json`; a test enforces that,
because the install path is version-keyed and an unbumped version lets a
reinstall keep serving the old snapshot.

Versioning rules are in
[docs/development-workflow.md](docs/development-workflow.md#versioning).
Per-subsystem detail lives in [docs/build-status.md](docs/build-status.md); this
file is the short "what changed for someone who installs it" list.

## 0.8.1 — 2026-09-07

**A measurement survives a pass: three reports stop collapsing a distinguishable
absence into something that reads as a normal reading.** Each already computed
the number a reader needed and then discarded it (`variety`, `pacing`) or
reported it under one sentence true for only one of five causes (`outro`). The
only real run's own artifacts are the evidence: all four `MUSIC*.json` carry
`bars: []`, so the outro-fit feature reported "n/a" for the one cause it did
not mean; the shipped `EDL.json` was 22.4% short of `SPEC.length_s` with
nothing anywhere comparing the two; and the shipped pacing spine's Spearman
agreement (dur vs. energy, −0.571, the correct direction) and the earlier cut
it was trimmed from (+0.509, inverted) were both real, in two different files,
with no report naming either number.

- **`variety`'s detail now reports the global minimum distance on every
  path**, not only a failing one — beside the pair it came from and the bar
  it was judged against. A passing check used to report `{}`.
- **`OutroFit.cause` names WHICH of five absences made a fit "unchanged"**
  (`no-bars`/`no-episodes`/`ramped-closer`/`closer-not-in-footage`/
  `no-reachable-line`) instead of the one sentence — "the fit chose no bar
  line" — that was true for exactly one of them.
- **A new advisory `brief_length` check** compares the delivered reel against
  `SPEC.length_s` for the first time at any gate; `EDL.brief_len` and
  `ReelManifest.brief_len` carry the brief's length end to end to reach it.
- **`Slot.beats_in` distinguishes a measured energy from `fit_spine`'s `0.5`
  fallback**, and a new `pacing.energy_agreement` reports the Spearman
  correlation between cut length and music energy over measured slots — a
  description, not a verdict; no threshold is claimed.

PATCH, not MINOR: no new stage, no flag, no renamed signature, and no changed
default that alters output — `check_reel.run` gains one defaulted keyword and
`ReelReport.overall` cannot move. Mutation battery: 13 rows, 13 red, zero
coverage holes.

## 0.8.0 — 2026-09-03

**The mood contract: a mood word declares only what it commands.** Closes the
retro's R1.1/R1.2/R1.3 — and R1.2 closes as **overturned**, not delivered as
asked: measured read-only against the 2026-06 run's own artifacts, 72.9% of a
1508-window pool sits on the carve's 1.2s floor and only 0.2% ever reaches its
4.0s ceiling, the footage had room regardless (92.9% of scene spans run past
4.0s), and the shipped reel already exceeds the ceiling in 4 of 8 episodes
because `edit_plan` joins adjacent windows — so a wider ceiling would not have
changed the delivered cut, and the operator's "pull toward two seconds" is not
explained by the `asl` band either (the shipped reel's median shot was 4.10s,
above `nostalgic`'s own declared ceiling). What actually needed fixing was that
the band could change with nobody the wiser.

- **`Spec.tone_bias` is now authorable** — `None` and `(0, 0, 0)` are different
  answers (take the mood preset's own taste, vs. this mood but leave my colour
  alone), and `match_grade` reads an authored value before the preset's.
  `MATCH.md` now names which one won.
- **The intake window band (`--win-min`/`--win-max`) is a real parameter**, not
  a module constant — it joins the per-clip cache key (`CACHE_VERSION` 8→9), so
  changing it is a cache miss, never silently-stale window boundaries. The
  first scan after a band change re-scans the whole pool, once.
- **`edit_plan` refuses a mood whose length floor the footage cannot supply** —
  checked against what a scan actually carved with, floor only: nothing splits
  a window, but `edit_plan`'s own span merge always reaches a taller ceiling,
  so a preset ceiling above the carved one is legal and is not refused.

Mutation battery: 10 rows, 10 red — one only after closing a coverage hole the
battery itself found (`if spec.tone_bias:` cannot be told apart from `is not
None` by any real `Spec`, since a 3-tuple of zeros is truthy regardless of its
contents; closed with a test built to discriminate the two directly).

## 0.7.2 — 2026-09-02

- `fake_render`'s docstring now states that `delivery` reaches no encode. `Delivery.dims()`
  is called only from the real reframe path (`lib/layout.py`) and `draft.py`; a real reframe
  records its result as `path.meta.json`'s `out_dims`, while the fake stream-copies and
  writes `out_dims = src_dims`. The value still reaches `project.json`, where `ProjectConfig`
  and the soft manifest gate validate it. Measured: `long_edge:240` and `native` deliver the
  same 640x360 file in the same 1.39s. The design's §1 table already said this (0.7.1); the
  fixture a reader actually opens did not.

## 0.7.1 — 2026-09-02

- **Nothing about a reel changes here.** This is a documentation-and-tests PATCH:
  `git diff --stat -- scripts/` across the whole slice is empty. It ships because
  the install path is version-keyed, so a reinstall at an unmoved version keeps
  serving the previous snapshot of the docs and skills that ride into the cache
  alongside the code.
- **One shared test fixture where five hand-written copies used to be.** Four
  integration tests — one of them twice over, a plain fake and a pan-aware sibling
  — each declared a canvas their own fake renderer never honoured: the same
  defect, repaired by hand four times, with nothing stopping a fifth.
  `tests/conftest.py` now derives both the declared canvas and the fake's own
  geometry sidecar from a single source size, so the two readings cannot disagree.
  Recorded honestly rather than overstated: it unifies the **canvas**, not every
  field of the geometry — a declared `crop_scale` is still a number the fake does
  not honour.

## 0.7.0 — 2026-09-02

**Each colour gate gets a reference that admits the grade.** Two blocking
colour gates each measured the render against a reference that pretended the
declared grade did not exist, so each failed correctly-graded episodes and
routed them back to the stage that authored the grade — the two P1 rows
0.6.0 filed and left open.

`check_episode.color_fidelity` → **`grade_damage`**. It renders the same
episode twice — once with its declared colour block, once with every knob at
identity — and asks whether the Shannon entropy of the two luma histograms
says the declared map DESTROYED information, against `CheckSpec.entropy_floor
= 0.90` (measured: a conductor-shaped tone pair reads 0.933, `black_point =
0.35` reads 0.753, an ungraded episode reads 1.000 exactly). A grade IS
movement and entropy is blind to a bijective one, so a real conductor pair —
which used to cross the OLD 5.0 dE00 ceiling on five of eight real-run
episodes — now passes clean. The old dE00 statistic survives as an advisory
`delta_e`/`dominant` pair, read by the QC judge, never a gate.

`check_reel.tone_match` → **`grade_faithful`**. It is now judged against the
profile each episode's OWN full declared chain predicts — rendered fresh
through the same `RenderPlan` the real render uses — instead of a common
target solved with every other knob at identity. `ReelCheckSpec.
grade_residual_max = 4.0` replaces `tone_match_max = 12.0`. Every episode is
judged now, not only ones bound to a target. **Demoted, not silently lost:**
cross-episode agreement no longer gates anything — it survives as the
advisory `target_dev`, because gating it re-opens the same deadlock from the
other side (a conductor pair that lands an episode on the common target can
still read far from it once the episode's own post-tone knobs are applied).

**Breaking:** `report.json`'s `color_fidelity` key and `reel_report.json`'s
`tone_match` key are gone, replaced by `grade_damage` and `grade_faithful`;
`CheckSpec.grade_delta_max` and `ReelCheckSpec.tone_match_max` no longer
exist. A pre-0.7.0 artifact keeps its old keys; nothing reads them forward.

**Also:** `probe grade` now predicts both gates (`grade_damage` +
`predicted_profile` in `probe.json`, agreeing with the real gate to within
0.02), so an operator converging on stills sees both stops coming instead of
meeting them after a full render; `episode_qc`'s colour-naturalness sensor
now reads the source through the episode's own crop geometry instead of a
whole segment frame, so its advisory deltas finally compare like with like.

## 0.6.0 — 2026-08-30

**The grade is now measured on the pixels that ship.** `match-grade` used to read a
whole source frame at each window's midpoint — a region no delivered frame matches,
since every episode ships a tracked crop of it. Measured on the real run, seven of
eight episodes differ between the two readings by more than `MATCH_EPS`, median 14 and
max 36 luma units, so the reel's "common target" was computed from pixels nobody sees.
The conductor now measures each episode's own tracked crop through
`reframe.plan_render` — literally the plan the render uses — pooled over three frames.
Result on that same footage: the **delivered** spread across the three anchors falls
**44 / 64 / 120 → 11 / 6 / 2** luma units, with a residual max of **8.0** and a median
of **3.5**.

**Breaking:** `match_grade build --edl X --footage-root Y` no longer exists. The
conductor reads `GEOMETRY.json` instead — `match_grade build --geometry
<run>/reels/<reel>/episodes/GEOMETRY.json` — because measuring a crop requires the
route, and the route does not exist until an episode has been tracked.

**New phase boundary in `edl_to_reel`.** Phase 1 splits at geometry:
`--stop-after-geometry` extracts, stabilizes, tracks and gates every episode, writes
`GEOMETRY.json` and stops **before any encode**; `--from-geometry` renders every
episode over those frozen routes with the EDL's current colour block. Between them sits
the seam the conductor (and a human) works in — a re-authored grade costs nothing to
apply, because nothing has been encoded yet. `--from-geometry` refuses a cut that moved
since the freeze (window, source clip or ramp), a build directory that was wiped in the
gap, and an engine that changed underneath; each refusal names its remedy.

**`probe grade --geometry`** renders and measures three frames of one episode over its
frozen route before anything is encoded, always through the EDL's current colour block —
so a grade converges in seconds instead of a reel per attempt. It agrees with the shipped
encode's mean luma to **1 code**. `probe.json`'s `drift_checked` reads `false` there and
says so: there is no rendered file yet for the recomputed plan to be checked against.

**`check_reel` gains a blocking `tone_match`.** Three frames per bound episode, read off
the **master** (not the delivery — `deliver`'s vignette and bookend fade both move
percentiles), against the reel's one common target now stamped on `EDL.tone_target` and
carried to `ReelManifest`. A failure escalates to `match-grade`. `tone_match_max = 12.0`
sits between a measured positive maximum of 8.0 and a negative minimum of 19.5.

**`match-grade` is now a required stage**, and the router leads through the new order:
… pacing → **episodes-geometry** → **match-grade** → … → `edl_to_reel --from-geometry`.
A reel that skips the conductor is a reel nothing measured: without the target it stamps,
`tone_match` reports `not-checked`.

**Known collision, recorded not fixed:** `check_episode`'s `color_fidelity` is blocking
at 5.0 dE00 with no waiver, and a conductor-authored tone pair is grade movement to it.
On the real run's own pairs the crop-based conductor's pulls exceed that ceiling. See
the design's §9.8 and the P1 row in `docs/backlog.md` before running a mixed-camera reel.

## 0.5.0 — 2026-08-29

**Retired the reel's colour-convergence loop.** `check_reel`'s `color_across_cuts`
compared two frames straddling a cut — two different shots — so six of the only real
reel's seven cuts exceeded its 12.0 default and the operator raised the ceiling to
56.0 to switch it off. Its corrector then optimised a different quantity than the gate
read, demanding pulls of 1.41x and 1.75x against 0.71 dE00 of fidelity headroom. Both
are deleted, along with the `color_correct` cascade they were the only consumers of:
`ReframeSpec.color_correct`, `process_episode`'s parameter, `reframe`'s compose branch
and `color.corrected`.

**Breaking:** `ReelCheckSpec.color_delta_max`, `ReelManifest.color_delta_max`,
`ReframeSpec.color_correct` and `edl_to_reel --color-delta-max` are removed. A
pre-0.5.0 `EPISODES.json` carrying `color_delta_max` is silently ignored; the CLI flag
fails loud.

**Added:** a `colour` axis on `reel-review`, routed to `match-grade`. Reel-level colour
agreement is now judged by a reader over the per-episode stills the packet already
carries, because no whole-frame statistic separates a grade mismatch from a content
change. Nothing automated measures it — see the design's §5.

## 0.4.0 — 2026-08-28

- **A damaged colour grade now stops an episode instead of shipping it
  unnoticed.** `color_fidelity` replaces its old hue-angle metric — blind to
  exposure and saturation, the two things a grade actually moves, and prone to
  discarding a sample outright near grey — with the median CIEDE2000 colour
  difference over five source-vs-delivered samples of the tracked subject. It
  now **fails the episode** above `CheckSpec.grade_delta_max = 5.0` (the field
  replaces `hue_drift_max`), and a colour failure escalates immediately to
  `edit-plan` as `grade-damage` instead of burning three full-resolution
  re-renders on reframe knobs that cannot move a colour. Measured on one
  reference shoot: every episode that graded cleanly stayed under the bar
  (4.29 at most), with simulated damage starting at 5.04 — a gap of 0.75 dE00,
  17% of that healthy maximum.
- **The per-episode QC judge now sees what the grade changed, not what the
  footage already was.** The colour-naturalness sensor drops three flags that
  were measuring the scene rather than the grade — one fired on most source
  clips before any grade touched them, two never reached their own bars on
  real footage. In their place: two flags for information a grade can destroy
  (`blown_highlights`, `crushed_blacks`), plus a new source-relative reading
  (`cast_shift` / `saturation_shift` / `contrast_drop`) measured against the
  pre-grade footage, which the QC evidence packet now carries alongside the
  delivered clip's own numbers.
- Both checks answer whether the colour moved and by how much — neither says
  the result looks good. That judgment still belongs to the QC judge and the CP3
  reviewer.

## 0.3.1 — 2026-08-28

- **Two thirds of the footage was being graded in the wrong colour range, silently.**
  `extract` re-encoded with `-pix_fmt yuv420p`, which reads as a normalization and
  is not one — libx264 keeps full range for a full-range input. Of the 99 clips in
  the reference shoot **67 are full-range**, so most of the footage reached the tone
  transfer, whose constants describe a *limited* 8-bit plane, in a range those
  constants are not written for. Measured against one common target, the transfer
  missed by **8.5 luma codes** on a full-range source and **1.5** on a limited one,
  against a threshold of 4.0 that decides whether to correct at all. Segments are
  now normalized at the cut, and the two land on the same numbers. Byte-identical
  on everything already correct, so nothing that looked right has moved.
- **The tone map no longer flattens the highlights.** Above its top anchor the curve
  fell through to a constant, so twenty stored codes arrived as one — a plate
  exactly where the shoulder exists to prevent one. It now continues the shoulder's
  own slope.
- **Raw camera footage is refused where it cannot be graded.** A 10-bit source
  through the same transfer came back with **99.26 %** of its pixels on a single
  code — destroyed, not shifted — and nothing said so. `reframe` now refuses a
  source whose bit depth or colour range its colour maths cannot read, naming the
  remedy. It caught this repo's own test fixture on its first day.

## 0.3.0 — 2026-08-27

- **The run directory gets an interior, organised by lifetime.** `montage/footage/`
  survives every re-cut, `montage/reels/<name>/` holds one editorial variant, and
  inside it `episodes/` is one render generation, `deliveries/` is append-only and
  `build/` is wiped at the start of every render. Measured on the 2026-06 run:
  **52.8 %** of 1119 MB was scratch nothing had ever deleted — 17 `work/ep*`
  directories for an 8-episode reel — while the **16.0 %** that cannot be rebuilt
  lived in the one directory the workflow `rm -rf`'d **47 times**.
- **Version numbering survives.** `deliver` reads `VERSIONS.md` instead of counting
  surviving files, so an archived or deleted reel no longer renumbers the next one —
  three different reels had shipped as `REEL_v1.mp4`. Its scratch (the vignette mask,
  the title sidecars) now takes an explicit `--scratch-dir` and never lands beside
  the deliveries.
- **A second cut is a directory, not a filename suffix.** `--reel <name>` forks the
  120 KB editorial layer and shares the 194 MB footage layer, retiring `MUSIC_A/B/alt`
  and `pacing_A/B`.
- **`montage status` takes `--reel` in place of `--out-dir`** and returns each stage's
  resolved path, the whole layout, the reels that exist, and whether the run predates
  this layout. That resolution is also the enforcement: an artifact written outside
  the layout is not seen, so the router runs its stage again into the canonical path.

## 0.2.2 — 2026-08-25

- **Retro of the first real run** — six days, 99 clips, one delivered reel — written
  to `docs/retro/2026-08-25-first-real-run.md` before the session transcripts are
  deleted, and **42 backlog rows** filed from it (18 at P1). No behaviour change;
  this release is the record.
- The headline is that capability was not the problem. `scripts.probe grade` ran
  **0** times and `CONSTRAINTS` was mentioned **0** times in 831 tool calls, though
  the installed plugin shipped both two hours before the run started — while the
  agent rebuilt the colour probe by hand as a 2.0 GB private lab.
- Four of the first pass's six findings were refuted on re-reading, and the wrong
  versions are recorded beside the right ones.

## 0.2.1 — 2026-08-25

- **Run artifacts move to `<footage_root>/montage/`.** The footage folder gets one
  entry instead of the 38 a real run left in it. `intake`, `draft` and
  `edl_to_reel` now refuse an output directory that resolves to the footage root.
  Not tidiness: intake discovers clips by extension over a flat listing with no
  exclusion, so a rendered `.mp4` written beside the source — `draft.mp4` did
  exactly this — is taken as footage by the next scan.
- **A run from before this convention no longer resumes on its own.** It lives
  directly in the footage folder; the router now asks instead of silently starting
  fresh and re-scanning every clip. Moving such a run is not a `mv` — its artifacts
  carry absolute paths to each other.

## 0.2.0 — 2026-08-19

- **Cast identity works for the first time.** `lib/reid` reached
  `FeatureExtractor` through an import path torchreid 0.2.5's layout does not
  have, so every real embedding died one line below the availability gate. The
  boundary had never executed anywhere — its proof was the suite's one skip.
- **`setup.sh` installs `tensorboard`.** torchreid declares no runtime
  requirements at all and reaches it through `torch.utils.tensorboard`, so
  `pip install torchreid` succeeded and `import torchreid` raised.
- **Version bumped so a reinstall actually replaces the plugin.** The install path
  is version-keyed; at an unchanged `0.1.0` the cache had served a 316-commit-old
  snapshot, which is why the required `episode-qc` stage was missing from the
  installed skill set.

## 0.1.0 — 2026-07-22

- First packaged plugin: `skills/` distributed through a self dev-marketplace,
  with `bin/vg` as the launch chokepoint and `setup.sh` provisioning the runtime
  it drives.
