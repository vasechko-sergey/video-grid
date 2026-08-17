# Build Status

What is built, what is next, and the external assets the build depends on.
**Update after every task** — tick the plan's checkboxes and add/adjust the
relevant bullet here in the same commit.

_Last updated: 2026-08-17._

> Bird's-eye progress across the full 16-stage conveyor:
> [pipeline-map.md](pipeline-map.md). This file is the detailed per-subsystem
> changelog; that one is the stage-by-stage map + phase roadmap.

## Done

- **Pacing fixed point — make the fit-then-apply round trip a fixed point, and
  stop the length absorb from overwriting a length the outro fit chose DONE
  (2026-08-17)** — plan `docs/plans/2026-08-16-pacing-fixed-point.md` + design
  `docs/specs/2026-08-16-pacing-fixed-point-design.md`, Tasks 0–7 (branch
  `feat/pacing-fixed-point`, commits `587fe8c`..`a4a68d8` + this docs sync).
  Backlog P2 "Make pacing's round trip a fixed point again" and P2 "Reconcile
  `build_reel`'s length re-time with the outro fit" both close; the P3 Music
  row "measure the delivered fade's real distance from `EDL.outro.line`"
  closes for free alongside them.

  **Why it was broken, measured.** `pacing.build_pacing` fit
  `[ep.play_dur() for ep in edl.episodes]` — the durations already written
  into `EDL.json` by an earlier bind or outro fit, not the scenario's own
  lengths — so the stage fit its own previous output. The already-queued half
  of this was a hard deadlock: after an outro fit the closing episode's `dur`
  is a length footage re-projection cannot reproduce, so re-applying a re-fit
  spine raised `slot 1 is 4.70s against a 4.00s episode` and the documented
  three-command detour was the only way out. A second, silent defect surfaced
  only while designing the fix: re-fitting an already-fitted EDL against a
  DIFFERENT music window does not converge on the scenario's own answer —
  measured on the real `fit_spine`, a scenario `[5.77, 3.41, 6.02, 4.88]` fit
  to 128 BPM and then re-fit to 110 BPM lands on beats `10/16/27`, where
  fitting the SCENARIO straight to 110 BPM lands on `11/17/28` — the whole
  reel **0.5455s short**. Not rounding: from the raw 5.77s the 6.0s line is
  0.23s away, inside the 110 BPM allowance; from the already-snapped 5.625s
  the same line is 0.375s away and unreachable. And it fires on precisely the
  workflow `build_pacing`'s own report recommends when no grid level fits:
  "Try another window (beats --auto-start)".

  **The fix.** `EDLEpisode.base_dur` — the footage-projected length —
  recorded ONCE by `window_to_episode` and never rewritten (`_bind_pacing`
  and `_apply_outro` both go through `dataclasses.replace`, which carries it
  across untouched). `base_play_dur()` adds back the ramp extra so a ramped
  episode's SCENARIO played length stays exact. `pacing.build_pacing`,
  `pacing._bounds`, and `edit_plan._bind_pacing`'s half-beat guard all read
  through it instead of the bound `dur` — the spine becomes a pure function
  of `(base, music)`, the bound `dur` a pure function of `(spine, ramp
  extra)`, so fit → apply → fit → apply reproduces the same `EDL.json` for
  any number of repetitions (design §3.1, proven end to end in
  `tests/lib/test_pacing_fixed_point.py` — five real driver calls, EDL **A**
  and **B** byte-identical, no ffmpeg needed since neither driver decodes a
  frame). An `EDL.json` written before this slice has no `base_dur`; it keeps
  the old deadlock, and the refusal message now names that arm by name rather
  than leaving a reader to guess whether the fix applies.

  **`Spine.music_digest`.** A spine now binds to the music WINDOW it was
  fitted to — `music_identity()` hashes the track's own content plus
  `start_offset` and `duration` — not merely its tempo, because the SAME
  track analysed at a different in-point moves every reel-relative grid line
  while the BPM stays bit-identical. `build_edl`'s ladder: matching digests
  bind, disagreeing digests refuse naming both, and either side missing (an
  old `PACING.json`, or an unreadable track) logs a NAMED not-checked and
  falls back to the old `_TEMPO_TOL` tempo proxy — weaker, and says so rather
  than reporting agreement it never measured.

  **The absorb refusal.** `build_reel`'s within-band length absorb justifies
  itself as "the reel IS that long, so the target was wrong" — false when an
  outro fit CHOSE the target as `line + fade`. `reel_orchestration.next_action`
  gains `outro_fixed`; a within-band shortfall now escalates to `pacing`
  (reason `outro-length-chosen`) instead of silently moving the fade off the
  bar line — `length_retime_max` is 1.0s, as wide as the 0.96s miss the whole
  outro slice exists to fix. `check_reel` gains an advisory `outro` check
  measuring the residual for free (`total` was already probed for the length
  gate); its `passed` flag keys on `_LENGTH_TOL` (0.5s — not "a fraction of a
  frame", the framing music-outro-fit's own deferral had assumed).

  **The mutation battery.** 22 rows — the plan's 20 plus two folded in from
  the earlier tasks' own reviews — every one watched red, then green after
  hand-reverting. One flagged row (`build_reel` dropping the outro rung test
  down to a bare `is not None`) turned out to already be closed by a test
  added during Task 5's own review round. Two rows needed a genuinely new
  test: the digest ladder's SILENT-SUCCESS leg (a pre-slice `PACING.json`
  with an empty `music_digest`, plus a readable, tempo-matching `MUSIC.json`,
  must still bind — every prior test only ever exercised the both-sides-empty
  leg) and `reel_orchestration`'s escalate-wins-the-round guarantee under a
  simultaneous reprocess-class failure with `outro_fixed=True` (a length
  shortfall that would otherwise legitimately ride along with a colour
  reprocess must not, once the outro fit chose the length). Both were
  confirmed discriminating by actually running the mutation, not by
  inspection. Whole suite: 2941 passed, 2 skipped (torchreid, no network) —
  the same skip count as before this branch.

  **The three-skill detour, deleted.** `skills/pacing/SKILL.md`,
  `skills/edit-plan/SKILL.md` and `skills/reel-review/SKILL.md` all taught
  "rebuild WITHOUT `--pacing`/`--music` first, else the re-fit deadlocks" —
  correct advice for code that no longer exists, so leaving it would have
  sent a reader through a needless rebuild. Replaced with "re-fitting is safe
  to repeat"; reel-review's routing table gains a row for the new
  `outro-length-chosen` stop.

  **Deferred (design §10, backlog):** a migration for an `EDL.json` with no
  `base_dur` (still deadlocks, by design — no refusal, since that would close
  the hand-authored front door); the digest's audio-unreadable rung falling
  back to a tempo-only comparison that cannot see a `start_offset` change;
  calibrating the outro residual's reporting boundary against perception
  (same class of open question as `TAIL_MIN`).

- **Frame probe + look gate — converge a colour grade without a reel
  re-render, and catch a look that silently failed to render DONE
  (2026-08-16)** — plan `docs/plans/2026-08-15-frame-probe-look-gate.md` +
  design `docs/specs/2026-08-15-frame-probe-look-gate-design.md`, Tasks 0–7
  (branch `feat/frame-probe-look-gate`, commits `86d84a5`..`47742b0` + this
  docs sync). Backlog P2 #10, closes it. One primitive answers two
  complaints: `scripts/probe.py grade` renders 3 frames of ONE episode
  through the SAME chain `reframe` would encode (`reframe.plan_render` +
  `RenderPlan.with_tail` — one chain builder now, not two implementations
  that can drift) over its frozen route, so a colour grade converges without
  paying for a reel re-render; `deliver`'s post-encode look gate
  (`scripts/lib/lookcheck.py`) samples the delivered `REEL_v{n}` against its
  master and hard-refuses a declared vignette/fade that did not reach the
  pixels — the exact bug class the cinematic-look review caught once by
  hand, now machine-checked on every delivery.

  **What the probe costs, measured.** Dropping the encode alone buys
  1.34–1.84× (full encode 0.59–3.83s across flat/grain 1080p/4K vs. the
  probe's 0.37–2.86s); the bigger saving is the tracking pass it also
  skips — **5.00s** on a 1080p/3s clip, against the encode's 0.59–2.41s
  beside it. One grade attempt today is track+encode ≥7.4s against the
  probe's 1.31s (**≈5.7×**), and via `edl_to_reel` that cost is paid per
  episode, every attempt.

  **Whether the probe's pixels are the shipped pixels, measured.** Probe
  PNGs against the same frame numbers decoded back out of `reframe`'s real
  output, on the grain source (the worst case for x264 at crf 18): mean
  |Δ| 1.07–1.39 codes per pixel. The statistic the grade decision actually
  reads — mean luma — agrees to **0.14 codes or better**.

  **The look gate's calibration, measured.** A declared vignette of
  0.10/0.30/0.60 drops the corner-over-centre ratio 0.0844/0.2576/0.5209 —
  0.84–0.87× of the declared depth, so `VIGNETTE_MIN_FRACTION = 0.5` sits
  with a 1.7× margin below the worst measured case. A 0.5s fade took a
  75.28-mean opening frame to exactly 0.00 (`FADE_BLACK_MAX = 2.0`). Task
  6's independent real-ffmpeg proof measured **0.2576 at declared 0.30** on
  a different canvas — matching the table at a different point. The gate's
  original THIRD check — a whole-frame noise-floor catch-all — was
  designed, measured, and deleted in this same slice: a fade touches only
  the first/last half-second, so the three interior samples it would have
  compared sit outside both ramps and read as "no look at all"
  (0.638–0.780 vs. the master, indistinguishable from a shallow vignette
  that passes the same floor by 3%) — the premise (any declared effect
  moves the whole frame) was wrong; only a vignette does.

  **The `select`-before-`fps=` landmine is now unreachable, not just
  documented.** `scripts/lib/lint.py` gained a seventh `check_argv` check,
  wired into `proc.run`'s always-on guard — production code can no longer
  construct that argv at all. Task 6's own proof of the duplication (three
  requested frames returned as one frame, three times) had to bypass
  `proc.run` via a direct `subprocess.run` call to still measure ffmpeg's
  raw behaviour; the design's §3.1 now says so explicitly (added this
  task, since a rule with no evidence behind it decays into folklore).

  **Task 7's 15-row mutation battery (17 checks counting the 6b/14b
  variants) found one coverage hole.** Row 15 asked whether `probe_grade`
  could render `md["segment"]` while still labelling its report with
  `source_for()`'s path — and nothing in the suite called `probe_grade`
  end-to-end on a `stabilize` episode to catch it. The gap is real and
  structural, not a test-writing oversight: a raw and a stabilized source
  of matching dims/fps/dur give `plan_render` IDENTICAL geometry either
  way, so `_refuse_on_drift` — the guard this whole slice built to catch
  drift — cannot see a pure content swap; only the rendered pixels would be
  wrong. Closed with
  `test_the_probes_frames_are_the_frames_the_render_ships_under_stabilize`
  (`tests/integration/test_probe.py`): a dark `raw.mp4` and a bright
  `stabilized.mp4`, an identity-gain grade so only the source pixels can
  move the mean, confirmed red under the mutation (p50 27.0, reading as the
  dark segment) before reverting clean. The other 16 checks held on their
  first try. Whole suite: **2881 passed / 2 skipped** (pre-existing skips:
  torchreid weights, off-network iTunes) — +1 over the prior 2880 baseline,
  exactly the one new test.

  **Wired into the skills.** `edit-plan`'s colour-grade section now carries
  the convergence loop (`probe grade` against an edited `EDL.json`, look at
  the pixels, edit, probe again; then materialize the converged manifest
  with `probe.regrade` itself — never a hand-merge, which keeps a colour
  field the EDL edit just deleted — and re-render one episode with its
  frozen route, never the reel). There is no one-step command for that last
  re-render yet; filed to the backlog (P4). `using-montage` notes at the
  episode-qc checkpoint to probe before spending a re-render on a colour
  finding, and that `deliver`'s look-gate refusal is a broken look chain,
  never something to retry as-is.

  **Honest limits, filed to the backlog, not left stranded in the design's
  own `§Deferred`.** Titles carry no pixel check in the look gate (only a
  `not-checked` finding that one was declared); the gate's constants are
  calibrated on synthetic patterns and one encode profile, not real
  footage; the probe is wired for colour only, not composition or path
  smoothness; there is no one-step re-render of a converged episode. All
  four now have their own row in `docs/backlog.md` (P3/P3/P3/P4), each
  citing `frame-probe-look-gate §11`, alongside backlog #10 itself flipping
  to ✅.

- **Two P2 rows close by measurement — the shadow_red toe, and the length
  figures that already agreed DONE (2026-08-15)** — plan
  `docs/plans/2026-08-15-shadow-red-length-reconcile.md` + design
  `docs/specs/2026-08-15-shadow-red-length-reconcile-design.md`, Tasks 0–4
  (branch `fix/shadow-red-and-length-reconcile`, commits `996b506`..`c91b73f`
  + this docs sync). Both rows were queued on a number that turned out to be
  incomplete or stale, and in both cases the fix is a refusal, not new
  machinery.

  **`shadow_red_arg`'s anchors, re-measured.** The queued row already
  suspected the three hardcoded identity anchors above the return point
  (0.50/0.70/0.85) sagged the fitted spline; re-measured here with the same
  lossless ramp probe `highlight_red_arg` used
  (`tests/integration/test_reframe.py::_ramp_r_lut`), the sag at the shipped
  `ret=0.25`/`SHADOW_RED_MAX` is **−6** codes, worst at code 79 (x≈0.31, in
  the gap right after the return point), and up to **−14** across the legal
  `(lift, ret)` domain. Fix: identity anchors every `SHADOW_RED_STEP=0.05`
  derived from `ret` rather than hardcoded, so a caller passing a
  non-default `ret` gets a dense region too — exactly identity above the
  return point at the shipped `ret` for every legal lift. **The same probe
  found a second, worse defect the queued row never named**: the toe maps
  `x -> x + lift*(1 - x/ret)`, slope `1 - lift/ret`, so once `lift >= ret`
  the slope is non-positive and the mapping inverts, banding the shadows —
  every non-monotone cell the grid scan found had `lift >= ret`, and none
  with `lift < ret` did. `shadow_red_arg` now refuses `lift >= ret`; it is
  THIS refusal, not the densification, that removes every non-monotone cell
  in the scanned domain. Unreachable in the shipped configuration today
  (`SHADOW_RED_MAX=0.20 < SHADOW_RED_RETURN=0.25`), so the refusal guards
  only a caller that does not exist yet, the same reachability class as the
  twin's `knee`.

  **The length figures, read off the run's own artifacts, not the summary
  that queued the row.** `EDL.target_dur` (34.072) equals `sum(play_dur())`
  (34.0724) to **0.0004s** — the rounding the field is written with — and
  the delivered `out/REEL_v1.mp4` (34.051) is **21ms** off `EDL.target_dur`,
  under one frame at 30fps (33.3ms). Those two never disagreed. What
  disagreed was `PACING.json`: written **nine hours** before `MUSIC.json`,
  fitted at **140.625** BPM against the shipped track's **110.294** — it
  belonged to a track that was later swapped out.
  `EDL.md`'s "32.4s" (sum of `dur`, ignoring the ramp) was **already
  fixed** — `edl.to_markdown` sums `play_dur()` — the run's markdown just
  predates the speed-ramp slice by eleven hours. And **"30.317" is not
  reproducible from any artifact** in the run: not `EDL.json`, not
  `PACING.json`, not `reel_report.json`, and no `.md`/`.txt`/`.log` contains
  the string "30.3". Fix: `build_edl` now refuses when `pacing.tempo` and
  `music.tempo` differ by more than `_TEMPO_TOL = 0.5` BPM, checked before
  `_bind_pacing` runs and named beside the existing
  `--music`-without-`--pacing` log.

  **The seven-row mutation battery (design/plan) found one coverage hole.**
  Row 7 asked whether the tempo guard's ordering — before `_bind_pacing`,
  not after — is actually observed by any test. It is not: the four
  existing tempo tests all bind through `_spine2()`, whose slots sit inside
  `_bind_pacing`'s own snap allowance, so relocating the guard to run AFTER
  `_bind_pacing` left all four green (the guard still ran, just later, and
  still raised the same message before anything else could). Closed with a
  new test, `test_build_edl_checks_tempo_before_binding_the_spine`, whose
  spine ALSO fails `_bind_pacing`'s own half-beat snap — so only "tempo
  checked first" reaches the DIFFERENT-track message, and "tempo checked
  after bind" hits `_bind_pacing`'s own "fitted to a different edit" message
  instead, which the test's regex catches. The other six rows failed their
  named test on the first try and reverted clean. Whole suite, bytecode
  cleared: **2845 passed, 2 skipped** (pre-existing: torchreid weights,
  off-network iTunes), 0 failed.

  **Two honest limits, left open on purpose.** Equal tempo does not prove
  the same track — two different tracks can sit within 0.5 BPM of each
  other; the strong version (recording the music file's digest on `Spine`)
  is folded into the existing P2 "make pacing's round trip a fixed point"
  row instead of a new one, because it rewrites that same file. And the
  densified `shadow_red_arg` curve keeps a one-code wobble of its own —
  unrelated to the inversion defect above — near `lift ≈ ret`: **15** cells
  at `ret` step 0.01, not three — the three first reported (0.15/0.14,
  0.20/0.18, 0.20/0.19) were read off a `ret`-step-0.05 grid and are exactly
  the subset it could see, up to 0.03 from `ret` (not "within 0.02"): 8-bit
  rounding where the toe's slope is already near zero. Step 0.10 has one
  such cell (uncounted at the finer step), and the shipped `ret=0.25` has
  none at any legal lift.
  One side effect: the P3 "enforce `SPEC.length_s`" row is now unblocked —
  the diagnosis found the target it would gate (`EDL.target_dur`) already
  equals what the master delivers, so a real number is waiting for it.

- **Music outro fit — the reel ends where the phrase does (backlog #2, closes it)
  DONE (2026-08-14)** — plan `docs/plans/2026-08-14-music-outro-fit.md` + design
  `docs/specs/2026-08-14-music-outro-fit-design.md`, Tasks 0–7 (+5b, a fix task
  forced mid-slice — see below) (branch `feat/music-outro-fit`, commits
  `58580e2`..`596cfc2` + this docs sync). Builds directly on the demucs-required
  entry just below: that slice made a vocal-free half-second *measurable*; this one
  is what spends the measurement.

  **The one lever.** `mix.py` already fades the music over `[dur - fade, dur]` —
  it always has. So a reel of length `line + fade`, for any detected bar line
  `line`, starts that EXISTING fade exactly on the line. No ffmpeg stage changes
  at all (design §1); the whole slice reduces to picking ONE number, the reel's
  length. `edit_plan` moves only the LAST episode's `dur` to reach it, after
  `_bind_pacing` and never through a slot — cuts before it keep the beat they
  were fitted to, so `check_reel`'s beat gate stays green by construction.

  **Bars come from the bass band, not the obvious detector.** Onset strength per
  beat phase, on the 2026-08-03 run's own 110.294-BPM track: **4.313 / 4.285 /
  4.267 / 4.309** — no signal, all four phases within 1%. A detector built on
  novelty picks a phase out of noise and looks like it works. Low-band (<150 Hz
  kick) peak per beat instead: **48.01 / 54.65 / 42.03 / 79.31**, a **1.887**
  max/min ratio, and the winning phase's beat was the loudest of its own bar in
  **14 of 18 bars** (78% against 25% by chance). `beats._downbeat_phase` reads the
  bass band exclusively; the mutation battery (Task 7, row 7) rebuilt the
  onset-strength variant for real on synthetic audio and it picked phase 3, not
  the phase 2 the fixture demands — the design's own claim, reproduced.

  **§8.1 — the resolution trap that fooled this design once.** The first pass of
  the investigation ran real demucs at the existing 2 Hz envelope
  (`MusicSpec.energy`'s own resolution) and reported "one usable bar line in the
  window, and it is at 4.71s" — i.e. no usable ending. A 2 Hz envelope has **0.5s
  bins**, and the rule asks about 0.5 vocal-free seconds after a boundary: a
  0.5s-binned sensor cannot resolve a 0.5s question, so the first pass concluded
  the whole feature was impossible. At the vocal stem's own resolution the same
  track has **two** usable lines, and the useful one is exactly the ending this
  design ships (bar 15, stem 35.26s, 1.50s of vocal-free space after it). The
  fix: `vocals.vocal_spans` builds its envelope at `_SPAN_HZ = 40.0` (~23ms bins)
  and nothing downstream ever reads the 2 Hz curve for this question again — one
  sensor now serves both the music in-point (`choose_offset`) and this out-point,
  so the two cannot disagree about the same track. The mutation battery's row 8
  rebuilt the ORIGINAL mistake (call `separate_vocal_energy` without the explicit
  `target_hz=_SPAN_HZ`, defaulting to 2.0) and confirmed the pure unit test catches
  it; the real-demucs integration wiring smoke test does not (its own docstring
  already disclaims semantic precision — see Task 7's report for why that stayed
  as a documented limit rather than a forced new assertion).

  **The defect this slice's end-to-end proof found — its most important finding.**
  Design §6 originally claimed that after the outro fit extends the closing
  episode, `_back_edge_target` "then reports the new total the ordinary way."
  That sentence was false, and a unit test could not have caught it: `_bind_pacing`
  gives a same-length spine `target_dur == sum(pre-fit play_durs)` BY
  CONSTRUCTION whenever the spine has as many slots as episodes (`pacing.fit_spine`'s
  own shape, with no slack), so ANY positive `moved` makes the realized total
  exceed `spine.target_dur`, and `_back_edge_target`'s over-flow branch — correct
  for footage the music genuinely cannot cover — clamped `target_dur` straight
  back down to the PRE-fit total. The EDL then disagreed with its own episodes,
  and `edl_to_reel` returned `stop_and_report` on the length check (`{"dur": 10.7,
  "target": 10.0}`) instead of delivering. **On a normally-fitted spine — the
  shape `pacing.fit_spine` actually produces — the feature did not ship at all.**
  Task 6's fixture had originally passed only because it gave the spine slack (an
  extra unfilled tail slot the fit's growth landed inside), which hid the exact
  defect the proof exists to catch; retightening the fixture to the real,
  no-slack shape is what surfaced it. The fix (Task 5b): `build_edl` now replaces
  `_back_edge_target`'s answer with `fit.reel_dur` whenever `_apply_outro` chose a
  line (`fit.rung != "unchanged"`) — safe because `fit_outro` already bounded that
  answer by `music_dur` (condition 2 of `_candidates`), so the length it returns
  is one the music provably covers; the clamp stays in charge on every OTHER
  path. Both the design and the plan were corrected in the same commit, the false
  sentence named as false rather than quietly reworded.

  **The mutation battery (Task 7) found one more coverage hole than the plan
  anticipated — five in total, across 14 rows.** The brief listed 12 rows and
  flagged 2 as
  certain to stay green (call-order swap, hardcoded fade) plus 2 new rows
  (dropping the `TAIL_MIN` floor, widening the `fit.rung != "unchanged"` guard).
  All 4 were real: the call-order swap needed a new integration-shaped test
  through `build_edl` (no existing test combines real pacing + real music in a
  way that observes call order inside it — the pacing-binding tests call
  `_bind_pacing` directly); the hardcoded-fade row needed a test authoring
  `look.fade != 0.5` (every existing outro test uses mix's own 0.5s default); the
  `TAIL_MIN` row needed a tail strictly between the fade and the floor (0.6s
  clears both a real 0.5s floor and a buggy 0.0s one); the `fit.rung` guard row
  was already covered by an existing test that trips at exactly `target_dur` 7.65
  vs 5.15. **A fifth hole surfaced only in execution, not in planning:** row 1
  (`free_after(...) >= need` flipped to `>`) stayed green against its own named
  test — the `- _EPS` float-slop the comparison carries means an ORDINARY decimal
  tie (tail == need) passes under `>=` and `>` alike, so only a tail landing
  bit-exactly on `need - _EPS` tells the two operators apart. Closed with a test
  constructed the same way the source computes that boundary (not a contrived
  coincidence). All 14 rows (the brief's 12 plus the 2 mandated additions; the
  fifth hole was inside row 1, not a fifteenth row) confirmed
  RED under the mutation and GREEN after an exact revert (`git diff` empty against
  `HEAD` for every touched production file). Two typing gaps against
  coding-standards.md's "every module-level function is fully typed" were closed
  in the same pass (`beats._downbeat_phase`'s `y`/`beat_times`,
  `edit_plan._apply_outro`'s `footage`/`music`/return type).

  **Two battery items were triaged as leave-as-is, with reasons** (recorded here
  rather than behind a pointer): row 8's real-demucs smoke test stayed green under
  its mutation — the *unit* test is what gives that row its RED, and the
  integration test's own docstring disclaims semantic precision; and
  `EDL.from_dict`'s truthy `outro` check matches its true peers `variety` and
  `constraints`, so aligning it with `look`'s `is not None` alone would have
  introduced a NEW inconsistency rather than removed one.

  **Five ffmpeg-stage scripts are untouched across the ENTIRE slice** —
  `mix.py`, `deliver.py`, `check_reel.py`, `build_reel.py`, `edl_to_reel.py`, all
  verified empty on `git diff --stat 58580e2..HEAD`. This is the slice's central
  engineering claim (design §1): the reel's length is the only lever, and it is
  paid entirely by `edit_plan`'s own episode list before any of those five ever
  runs.

  **Whole-suite proof.** `find . -name "__pycache__" ... -exec rm -rf` then the
  full suite: **2823 passed, 2 skipped** (the pre-existing `torchreid`
  unimportable-on-this-machine skip and the off-network iTunes smoke — no new
  skip), 0 failed, in ~171s.

  **Honest limits, copied verbatim from design §11 rather than paraphrased.**
  **§11.1** `TAIL_MIN = 0.5` is an assumption, not a measurement. It came from the
  project owner's ear, not from the editing literature, and nothing here
  validates it. It is one named constant in one module precisely so re-tuning is
  a one-line change, and a backlog row carries the check. **§11.2** `NO_GAP_FADE =
  1.5` is taste. No measurement says a 1.5s fade disguises a mid-vocal cut better
  than a 0.5s one. **§11.3** The downbeat detector is calibrated on one track.
  14/18 bars, ratio 1.887, one song, one genre. The 150 Hz band edge and the
  ±0.10s window are first cuts. **§11.4** The threshold behind the spans is
  inherited. `vocal_gaps`' 15%-of-peak relative bar is `offset.py`'s existing
  choice. Measured sensitivity on this track: 0.05 → 1 usable line, 0.10/0.15/
  0.20/0.30 → 2. Stable across the useful range, on one track. **§11.5** The gate
  proves placement, never taste. It proves the reel ends on a detected bar line
  with a measured vocal-free tail. It does not prove the phrase sounds resolved,
  that the line is a *phrase* boundary rather than merely a bar, or that a
  listener hears anything different. As with the cinematic look, no automated
  check ever hears the delivered reel — CP3 is the first place a human does.
  **§11.6** The `no-gap` rung ships a known-imperfect ending and says so in the
  report. That is the design's answer to material with no vocal-free space; it is
  not a claim that the result sounds good. **§11.7** `MIN_LAST = 1.0` is a floor,
  not a finding. It stops the shrink direction turning a closing shot into a
  flash; a real minimum would come from how long a viewer needs to read a shot,
  which nobody here has measured.

  **Deferred-minor triage (Task 7).** Two genuine one-line typing gaps fixed (see
  above). `EDL.from_dict`'s `outro` field uses a truthy check, flagged as an
  inconsistency against `look`'s `is not None` — investigated and left AS-IS: its
  true structural peers `variety` and `constraints` share the identical truthy
  pattern, and all three carriers (like `outro`) never legitimately round-trip to
  `{}` from any real writer, so aligning `outro` alone with `look` (a field with
  different, meaningful-empty-dict semantics) would have introduced a new
  inconsistency rather than resolved one. `tests/lib/test_edl.py`'s 6 pre-existing
  in-function imports (predating this slice) hoisted to the top, mechanical and
  zero behaviour change (155/155 still pass). A `pick()` tie-break in the pure
  ladder (design §5, "then toward the earlier line") had no test — closed with
  one. The rest (report-accuracy notes on earlier tasks' own scratch reports, a
  missing autouse `_SPANS`-reset fixture for `tests/integration/` — no
  conftest.py exists there yet, and creating one is a bigger structural change
  than this pass's scope, safe today only by the tmp_path convention) are named
  with reasoning rather than fixed reflexively.

  **Final whole-branch review — four Important findings, all fixed in one pass
  (2026-08-14).** The review verified the central claim and that the feature is
  reachable in a real run; these are what it found beside that.

  **I-1 · a fitted EDL breaks pacing's round trip.** `pacing.py` fits its spine to
  the durations it reads out of `EDL.json`, so after a fit it refits a length no
  footage re-projection can reproduce, and re-applying deadlocks in
  `_bind_pacing` — whose remedy ("re-run pacing against the current EDL.json")
  looped. Measured with the real `write_edit_plan`/`build_pacing` drivers on a
  120 BPM fixture: no fit `[6.0, 4.0]` → refit `[6.0, 4.0]` → binds; with fit
  `[6.0, 4.70]` → refit `[6.0, 4.70]` → raises. **Taken as the documentation fix,
  and the escape was VERIFIED before being documented**: rebuild without
  `--pacing` (durs return to `[6.0, 4.0]`), re-run pacing, re-apply — the fit
  lands again at `[6.0, 4.70]`, target 10.70. `_bind_pacing`'s refusal now names
  that sequence; the `pacing`, `edit-plan` and `reel-review` skills warn about it;
  design §11.8 records it and P2 carries the structural fix.

  **I-2 · the target override unclamped an over-flow the fit did not cause.** The
  guard was `fit.rung != "unchanged"` alone, which cannot tell the fit's own
  (music-bounded) growth from a pre-existing over-flow — so a stale `PACING.json`'s
  excess shipped silently whenever a bar line happened to be reachable, while
  `_back_edge_target` logged that it "escalates at the reel gate" and nothing did.
  Tightened to also require `pre_fit_realized <= pacing.target_dur +
  _BACK_EDGE_TOL` (equal by construction on the ordinary no-slack spine, which is
  why the tolerance matters), and the declined override now logs. New test
  proven RED before the fix (`assert 8.0 == 5.15`) and GREEN after.

  **I-3 · `EDL.md` contradicted the design and the skill.** The section was gated
  on `outro.line is not None`, so the `unchanged` rung — one of the three the
  edit-plan skill tells the agent to read this section for — rendered **nothing**;
  and the section never showed the distance from `SPEC.length_s`, which design §6
  requires in the only durable artifact. Both closed: `OutroFit` gained
  `brief_len` (round-tripping, defaulted `None` so every existing construction and
  every pre-existing artifact still loads), all three rungs render, and an absent
  brief is stated rather than omitted. No existing golden markdown moved.

  **I-4 · seven docs still advertised the deleted librosa mix-silence fallback.**
  Swept and corrected: `CLAUDE.md`'s two registry rows (always-loaded context) and
  its verify-runtime row, `pipeline-map.md` §5.5, `development-workflow.md`'s
  baseline-install bullet, and `fixes-backlog.md`'s finding #2 — which still read
  `NEEDS INVESTIGATION` and still carried the in-point hypothesis the
  investigation measured wrong, on the same day `backlog.md` declared it fixed.
  Five design docs got **amendment notes, not rewrites** (start-offset
  intelligence, verify-runtime, the montage skillset spec, setup-install-all,
  ffmpeg-baseline) plus a one-line correction in music-sourcing.

  **Cheap minors in the same pass.** `--music` without `--pacing` now says on
  stderr that it fitted nothing (it was silently ignored); the mutation-battery
  arithmetic above is corrected (five coverage holes across 14 rows, not "four
  rows total" and not 12+2+1=14); the gitignored `task-7-report.md` pointer is
  replaced by the facts it pointed at; `backlog.md`'s superseded P3
  `MUSIC.start_offset` row is marked measured-dead instead of still recommending
  itself; and #2's ✅ row now carries §11.5 (nothing hears the reel) and §11.6
  (`no-gap` ships a known-imperfect ending), which the skill already admitted and
  the queue did not. Design §11 gained §11.9 (the fade lands on the line only to
  the master's render accuracy) and §11.10 (`build_reel`'s within-band shortfall
  absorb replaces the fitted target with the master's real length and reports
  nothing about the outro) — both queued in P2/P3.

- **demucs becomes REQUIRED, and `choose_offset`'s mix-silence proxy is deleted
  (backlog #2, first step) DONE (2026-08-14)** — branch `feat/demucs-required`.
  No design doc: this is one semantic flip plus its fallout, and the evidence
  for it came out of the #2 investigation rather than a brainstorm. The
  investigation's own findings live in
  [backlog.md](backlog.md)'s P1 row, which is where a reader looking for "why
  does music end mid-phrase" will go.

  **What changed.** `preflight.CHECKS`' `demucs` row flips `required=False →
  True`, so `verify_runtime` exits 1 and `using-montage` step 0 stops the
  conveyor when it is absent. `beats.choose_offset` loses its `use_vocals`
  parameter and its fallback branch entirely: vocal-free spans now come from
  `vocals.separate_vocal_energy` and nothing else, and that function's existing
  guard — reworded to say REQUIRED and to name `bash setup.sh` — is the only
  remaining gate on the direct call path. The mix envelope still *ranks* the
  surviving candidates; it measures loudness, which it can do. Only the
  gap-finding moved.

  **Why the fallback had to go rather than stay as a ladder.** It is a §12
  silent-corruption shape: it does not fail, it answers **wrongly**. Measured on
  the 2026-08-03 run's own track (228s of dense pop), the full-mix envelope never
  drops to 15% of its peak mid-song, so `vocal_gaps` found exactly **2** spans —
  the lead-in and the fade-out — and every in-point candidate collapsed to
  **0.000** for durations 25/30/33/34/42/45. The run's `MUSIC.json` records
  `start_offset` 46.0, which therefore did **not** come from `--auto-start` at
  all. A degradation ladder is worth keeping when the lower rung is weaker; this
  one was confidently blind, which is worse than absent.

  **`setup.sh` still continues on a failed demucs install, deliberately.** Its
  `WARNING` became an `ERROR` naming the block, but the block does not abort:
  `set -e` there would leave torchreid, `models/` and the recorded runtime root
  unconfigured, turning one missing wheel into a half-built install that is
  harder to diagnose than a clean "verify_runtime says BLOCKED". Installing is
  setup's job; gating is `verify_runtime`'s. demucs stays out of
  `requirements.txt` for the same reason it always was — a failed torch wheel
  must not abort the whole `pip install -r` and with it the venv.

  **Tests.** Two new pins carry the behaviour change where a revert would
  otherwise pass: `test_demucs_alone_blocks_the_run` (a demucs-only miss →
  `ok is False`, `failures == ["demucs"]`, `advisories == ()`) and
  `test_cli_exit_1_on_demucs_miss`. `test_choose_offset_gaps_are_not_the_mix_envelope`
  is the discriminating one for the deletion: its mix envelope has a quiet run
  the vocal stem does not, so reading gaps off the mix picks 3.0s while reading
  them off the stem picks 1.5s — the old code passes only the first way. The five
  preflight/verify tests that had been using `demucs` as their stand-in advisory
  row moved to `reid`, now the only advisory. The mix-proxy unit test and its
  integration twin are replaced by refusal tests.

  **The suite is 2766 passed / 3 skipped / 1 FAILED, and the failure is the point.**
  `tests/integration/test_verify_runtime.py::test_real_runtime_is_ready` — the
  "needs the user's install" proof — now reports `[FAIL] demucs: not installed` on
  this machine, because this machine genuinely does not satisfy the contract any
  more. It was left red rather than skip-gated: skipping on a missing component is
  exactly how an incomplete install stops being visible, and it is the same shape
  that caught the never-working vidstab shake path in the ffmpeg-baseline slice.
  `bash setup.sh` (the user's to run — no autonomous installs) turns it green.

  **Verified after the user installed it (same day).** `verify_runtime` reports
  `runtime ready`, the skip-gated vocal integration test now runs, and the claim
  this slice rested on stopped being an inference: on the 2026-08-03 run's own
  track demucs finds **19** vocal-free spans against the proxy's **2**, five of
  them inside the reel's music window, and `best_offset` returns **147.772s**
  where the proxy returned 0.000. Measured cost: **62.1s / 46.2s** over a 229s
  track, ~0.2–0.27× realtime, paid once per `--auto-start`. The full #2 numbers
  live in [backlog.md](backlog.md)'s P1 row, including one they corrected — a
  first pass read the gaps off demucs' own 2 Hz envelope, whose **0.5s bins**
  cannot resolve a 0.5s rule; at the stem's 11.6 ms resolution the window has a
  usable ending that the coarse pass had reported as absent.

  **A latent probe defect the install exposed, fixed here.** Running the suite on
  the freshly-installed machine turned `test_reid.py` from *skipped* to *FAILED*,
  and the cause was not reid: torchreid 0.2.5 declares **no runtime requirements
  at all** while importing six packages, so `pip install torchreid` succeeded and
  `import torchreid` raised `ModuleNotFoundError: gdown`. The test's skip gate
  asked `find_spec("torchreid")` (a file exists) while `reid.available()` asked
  the real question (it imports) — so the gate said present, the code said absent,
  and the test failed instead of skipping. **The same weak probe was in
  `vocals.has_demucs()`**, which this slice had just made load-bearing: a
  half-installed demucs would have passed the REQUIRED gate and died at the first
  real call. Both now import. `setup.sh` guards and verifies on **import** rather
  than `pip show` for demucs and torchreid alike, installs torchreid's six
  undeclared deps explicitly, and prints the actual import error when a package is
  present but unusable — the header's "never leaves a capability missing without a
  printed reason" was not being honoured, because pip-installed ≠ importable.
  Suite after: **2770 passed / 2 skipped**, the skips being torchreid (still
  unimportable on this machine) and the off-network iTunes smoke.

  **Honest limits.** The change does not fix #2: it makes #2's second requirement
  (a vocal-free half-second after the boundary) *measurable*, which it was not
  before. And the vocal path is still covered in the suite only by a smoke test —
  synthetic audio cannot semantically exercise a vocal-trained net, so the
  evidence above is a one-off measurement on one real track, not a regression
  guard.

- **Cinematic look — a reel-level `EDL.look` (plateau vignette + bookend
  fade), the parked `highlight_red` + `outline-bold` leftovers (fixes-backlog
  #9 P1 look half, and #18 in full — cinematic-quality playbook priority 4,
  its third slice) DONE (2026-08-13)** — plan
  `docs/plans/2026-08-13-cinematic-look.md` + design
  `docs/specs/2026-08-13-cinematic-look-design.md`, Tasks 0–11 (branch
  `feat/cinematic-look`, commits `919950d`..`ca0fab6` + this docs sync). The
  2026-08-03 real run grew a five-item effects wishlist by patching the
  engine live; two items (`zoom`, the speed `ramp`) had already landed as
  first-class knobs (2026-08-08/09, see their own Done entries). This slice
  lands the remaining three — the look filters, `highlight_red`,
  `outline-bold` — and closes #18, whose demand is specific: not "add the
  effect" but that **every knob ships with a measurement of the pixels it
  moved**, because the live-added vignette had come out invisible (filter
  strength or chain order ate it) and no test caught it.

  **Where a look lives, and why there is only one place it can (design §1).**
  `EDL.look → ReelManifest.look → build_reel → deliver`'s single
  filtergraph — a copy of the `platform` pipe (2026-08-12). Two other
  positions were considered and are wrong for reasons the code already
  enforces: not in `assemble`, because `check_reel`'s black gate
  (`blackdetect=d=0.05:pic_th=0.98`) would fail a deliberate 0.5s bookend
  fade to black; not per-episode in `reframe`, because a vignette there
  would be re-judged by `check_episode`'s composition/colour checks (which
  know nothing about an intentional corner falloff) and cost one re-encode
  per episode instead of one for the reel.

  **The vignette's shape is the whole slice (design §2).** ffmpeg's built-in
  `vignette` filter is a `cos⁴` lens model with no plateau — measured on a
  flat 1080×1920 field at crf 18, its default angle puts the sky band above
  a subject at **0.637** of centre while the corner is **0.413**;
  `aspect=16/9` on the same tall frame drives corners **and the entire sky
  to 0.000** (landmine 5, below). Three ways to get a real plateau (identity
  to 55% of the corner radius, then a smoothstep falloff) were measured on a
  textured source: the built-in filter costs +0.33s over a 0.37s no-look
  baseline for corner/sky ratios of 0.728/0.843 (no plateau); a
  per-pixel-per-frame `geq` costs **+4.69s** for 0.664/0.990; the shipped
  **one-shot RGBA mask + `overlay`** costs **+0.18s** — cheaper than the
  built-in filter and **26.4× cheaper than `geq`** — for 0.709/0.995, the
  only route of the three with a genuine plateau. The centre is untouched
  (mean |ΔY| over a 240×240 patch: 0.144). Overlay also desaturates the
  corners where `geq` does not (corner chroma excursion 74.89 vs 108.28) —
  recorded as the *correct* choice (less light is less saturation), not an
  accident, and reversible later at a measured cost (§11.4, below).

  **The mechanism (design §3).** New `scripts/lib/look.py`, pure —
  `LookSpec(vignette: float = 0.0, fade: float = 0.0)`, both 0 at identity
  and 0 means *not emitted at all* (the `color.white_balance` convention, so
  `LookSpec()` renders exactly what today renders); `mask_expr` (the geq
  expression, refusing outside `(0, LOOK_VIGNETTE_MAX]`); `fade_args` (the
  two `fade` filters or `[]`, refusing `2*fade > dur`); `chain` (owns the
  order: titles, then the bookend fades — the vignette overlay is NOT in
  this list, since it needs a second input `deliver` wires by label).
  **`None` and `LookSpec()` are different, and the difference is
  load-bearing**: `EDL.look is None` means *never authored* (the mood preset
  fills it); `EDL.look == LookSpec()` means *authored as no look* (the
  preset does not get to override it) — the same `EDL.variety`/
  `EDL.constraints` shape. The JSON boundary tests `is not None`, never
  truthiness, because `{"vignette": 0, "fade": 0}` is a non-empty dict and
  therefore truthy either way — only `"look": {}` actually discriminates the
  two spellings, and review caught this as the slice's own reasoning error
  before it shipped (Task 2's fix round; a `{}`-specific test now pins it).

  **`deliver` grows one branch, and the off path stays byte-identical
  (design §3.2).** No vignette (including no look at all): unchanged `-vf`,
  byte-for-byte the same argv and delivered file as before looks existed
  (proven: three encodes — `look=None`, `look=LookSpec()`, and a reference
  built with the pre-look argv — all **16540 bytes, byte-for-byte equal**).
  A vignette needs a second input, so it takes `-loop 1 -i <mask.png>` plus
  `-filter_complex`, the mask rendered at the master's own probed dimensions
  (`assembly.probe_stream`) — never a config's idea of them, the exact
  `Delivery.dims(native)` trap that made `draft.py` render 8×16
  (housekeeping, 2026-08-12) one call away from here. There is no `movie=`
  shortcut to keep the single `-vf` slot — both obvious attempts fail
  silently (landmines 2/3, below).

  **Chain order, and the one part of it that is measured (design §4).**
  `overlay(mask) → drawtext(titles) → fade in/out`. Vignette before titles,
  so a bottom title is not dimmed by the corner falloff it sits near.
  **Fade last, and this is measured, not a preference**: with the fades at
  the end, the first delivered frame reads **0.0** — the title goes black
  with the picture. Move them before `drawtext` and the title burns on at
  full brightness over a black frame. The whole five-stage chain (overlay,
  noise, drawtext, two fades) composes in one filtergraph and runs in 1.39s
  on 3s of 1080×1920.

  **The audio, and the defect the fade exposed (design §5).** `mix.py`
  already faded the music (`_FADE = 0.5`, hardcoded) before this slice —
  applied to the music fragment BEFORE ambient/SFX were mixed in. That
  placement is wrong, and the bookend fade is what makes it visible:
  `_mix_graph` ducks the ambient with `sidechaincompress` keyed on the
  music, so when the music fades the key signal falls, the compressor
  **releases**, and the nat-sound gets *louder* exactly as the picture goes
  black. Fix: the fade moved off the music fragment onto the **mixed**
  stem, applied before `_measure` so `loudnorm` still measures what ships;
  `_FADE` became `mix(fade=)`, and `build_reel` passes `rm.look.fade` when a
  look exists (a reel with no look, or `fade=0`, keeps the 0.5s default
  unchanged — the audio bookend is not something a missing look should
  silently disable). Not claimed byte-identical on the music-only path — a
  double s16 quantization (once into `frag.wav`, once after the fade) costs
  up to 1 LSB on the faded 0.5s at each end, measured rather than asserted
  away.

  **`MoodPreset.look` — the brief's default (design §6).** Five rows, first
  cuts declared as guesses alongside `shot_mix`/`asl`: fun 0.00/0.3s, epic
  0.30/0.8s, moody 0.40/1.0s, nostalgic 0.25/0.8s, balanced (fallback)
  `LookSpec()` (0.00/0.00, never applied — see below). The authored
  `EDL.look` always wins over the preset; when a mood MATCHES, the preset
  only fills an unauthored one, and `edit_plan build` logs which source
  resolved (`selection.json` or the `<mood>` preset) on every run.

  **Fix wave, 2026-08-13 (final-findings.md I-2).** This entry originally read
  "`BALANCED` applies no vignette and exactly the 0.5s fade `mix` already did,
  so the autonomous path (no brief) delivers today's picture unchanged" — and
  shipped that way: `write_edit_plan` passed `preset.look` unconditionally, so
  a mood-less or skipped brief set `EDL.look = LookSpec(vignette=0.0,
  fade=0.5)`, which reached `deliver` as a real `fade=t=in`/`fade=t=out` pair —
  every autonomous reel opened on a black frame, the opposite of "unchanged"
  (pre-slice `deliver` had no video fade at all). The mechanism that actually
  delivers today's picture is `EDL.look is None`: `write_edit_plan` now passes
  `look=None` to `build_edl` whenever `moodpreset.resolve` falls back to
  `BALANCED` (`preset.name == "balanced"` is the exact test), which is the
  state `deliver`/`build_reel` already read as "nothing authored" — no
  vignette, no picture fade, and `mix` keeps its own 0.5s audio default
  because it is never told `fade=`. `BALANCED.look` itself was changed to
  `LookSpec()` as defence in depth only; filling it with anything concrete
  would be a change either way (a real fade imposes a taste, and even
  `fade=0.0` would reach `build_reel` as an AUTHORED zero that switches off
  the audio bookend — see the next paragraph). `None` is the only value that
  changes nothing, which is why the fallback's look is carried but never
  applied.

  **The two parked leftovers (design §7).** `highlight_red` — a red-channel
  `curves` fragment that pulls only the shoulder down (so specular foam
  carrying a red board's reflection reads neutral while water/skin/the
  board itself, below the 0.60 knee, keep their red), ported verbatim from
  `wip/montage-run-patches` into `color.py` beside its mirror
  `shadow_red_arg`, authored per-episode through `ReframeSpec`/
  `EDLEpisode`, not on the reel's look. `outline-bold` — a fourth title
  style (`STYLES = ("bold-box", "outline", "outline-bold", "plain")`), a
  heavier 7px border plus an offset shadow where a plain 4px `outline`
  disappears against a bright or busy background (the exact bright-water
  case the 2026-08-03 run hit).

  **Five landmines found while measuring, all silent — now in the
  design-spec §12 registry (this task).** (1) `blend=all_mode=multiply`
  against a single-plane mask destroys **chroma**, not just luma: U/V sit
  at 128 for neutral, so the multiply drags every pixel toward 0 — measured
  mean **|ΔU| 63.44, |ΔV| 62.76** against a `geq` reference; restricting the
  blend to the luma plane fixes it (ΔU/ΔV 0.18) at a five-node-graph cost.
  This one is now the landmine lint's **sixth `check_argv` check**
  (`scripts/lib/lint.py`), and the first of the five to also join
  `CLAUDE.md`'s always-loaded Known Troubles, since it is the one a future
  author is most likely to reach for and it is machine-checked, not just
  documented. (2) `movie=` inside `-vf` without `loop` truncates the whole
  reel to **one frame** — ffmpeg exits 0, writes a valid mp4 with
  `nb_frames=1`. (3) `movie=…:loop=0` — the obvious repair — **hangs**: the
  output stalled at 48 bytes with no progress for six minutes before being
  killed, against 0.55s for the same composite through a real `-loop 1 -i`
  input. (4) A mask built by grading a `color=c=white` source reads **253,
  not 255** — a silent 0.8% dim everywhere; building on `nullsrc` with an
  explicit `255*(…)` alpha expression gives a true 255 plateau. (5) The
  built-in `vignette` on a vertical canvas is a top-and-bottom dimmer (§2,
  above), and `aspect=16/9` on a 9:16 frame is the worst form — corners
  **and the entire sky** to pure black at any angle, a one-character
  authoring slip that silently destroys the frame.

  **Numbers measured after the design was written — carried here so nobody
  re-derives them.** `highlight_red_arg`'s docstring, ported verbatim from
  the parked branch, claimed its three sub-knee anchors (0, knee/2, knee)
  held the region below the knee at identity — false: three anchors pin the
  cubic spline ffmpeg fits AT three points, not the curve it draws BETWEEN
  them. A 256-step lossless ramp probe (the `reframe.verify_tone` method)
  found **249 of 256 codes deviating** at `pull=0.3`, peaking **+7** at code
  116 — mid grey (code 128) read 135, not 128. Densifying the sub-knee
  anchors to a step of 0.1 (derived from `knee`, not hardcoded) brought the
  same probe to **+1/−1** at `pull=0.3` and **+2/−1** at the
  `HIGHLIGHT_RED_MAX=0.35` ceiling — monotone throughout, and code 255
  (white, the shoulder's own computation, untouched by this fix)
  bit-identical before and after. On real delivered pixels this took the
  shadow-band R−B contamination from 2.054 to **0.046**. Two further
  findings, measured and deliberately **not** fixed, queued instead
  (`docs/backlog.md`, this task): `color.shadow_red_arg` — the mirror
  function, the one `highlight_red`'s own docstring cited as "the
  shadow_red lesson" — has the **identical** defect, worse: **−6** at
  `SHADOW_RED_MAX` against `highlight_red`'s pre-fix −3. And
  `highlight_red_arg`'s **shoulder** (`hi`) formula is
  monotonicity-fragile near `pull ≈ 1 − knee` for `knee ≥ 0.7` — a
  63-point knee×pull grid scan found the pre-existing code already broken
  there; unreachable today, since the one production call site never
  passes `knee=`. Separately, the audio proof's own first draft would have
  shipped green against the exact defect design §5 fixes: with `mix.py`
  reverted to the pre-slice fade placement, the **broadband** ratio
  (`rms[-1] < rms[mid]*0.35`) still reads **0.2078** — passing — while the
  ambient's own band ends at **1.81×** its mid level, because the music
  dominates the broadband sum and genuinely did fade. Only a band-isolated
  probe tone sees the ambient swelling into black; verified twice
  independently (a second run, at the final 700 Hz probe tone after the
  first round's 880 Hz was replaced, measured **1.8139** against an
  un-faded control of **0.9997**).

  **Three of the slice's own tests proved the wrong thing, and review
  caught every one before it shipped.** A `probe_stream` stub that
  returned a fixed 1080×1920 regardless of its argument, so a
  `_render_mask` that hardcoded those dimensions instead of probing them
  passed anyway (closed in Task 3's fix round by a discriminating test
  using 606×1078, a value appearing nowhere else in the file).
  `highlight_red` wired through every carrier — `ReframeSpec`,
  `EDLEpisode`, `Manifest`, `process_episode`'s construction — and
  validated correctly at each hop, while `reframe.py`'s own
  `grade_chain(...)` call never forwarded `spec.highlight_red` to a pixel:
  a fully carrier-proven, never render-proven value, the exact silent-no-op
  class #18 exists to close (found in Task 7's review, fixed the same
  round). And — the closest call, an Important finding from Task 9's
  review — a vignette+fade delivery still passed the WHOLE suite (2759
  passed) with `deliver`'s `-filter_complex` branch built from only
  `overlay=shortest=1`, dropping the titles+fade tail (`*parts`) that
  branch is supposed to carry: `parts` carries the titles chain too, and
  three of the four mood presets (epic/moody/nostalgic) ship a non-zero
  vignette, so this single mutation would have silently deleted the bookend
  fade **and every on-screen title** on 75% of mood presets. Closed the
  same round with a real-ffmpeg proof
  (`test_a_vignette_and_a_muxed_stem_pick_the_right_audio_input`, extended
  to assert both fade ends) and folded into the mutation battery as row 6b.

  **Honest limits (design §11, carried here in full).** Nothing checks the
  look happened: `check_reel` runs on the master, BEFORE `deliver` encodes
  the vignette/fade/titles, so no gate in this pipeline ever sees what
  actually shipped — the same boundary titles have carried since
  2026-07-13; the cheapest real fix is #10's 3-frame probe, now the named
  home for this too (`docs/backlog.md`, this task). Grain was measured and
  priced out, not built: at crf 18, `noise=alls=8` (the first setting with
  any real presence) costs **×4.36** the file size, `alls=12` **×8.82**,
  `alls=20` **×14.08** — a 30s reel goes from ~37MB to ~160MB at the
  cheapest useful strength, and the platform re-encodes it away on upload
  regardless, so the cost is paid for nothing. `LOOK_VIGNETTE_MAX` (0.6),
  the 0.55/0.45 plateau/falloff split, and every `MoodPreset.look` row are
  hand-picked on synthetic test patterns — no real footage has graded
  against them yet. The corner desaturation (§2, above) is a recorded
  choice, not a match: overlay and `geq` agree on luma (mean |ΔY| 1.39) and
  disagree on corner saturation by construction; the chroma-preserving
  alternative costs `geq`'s 26× or a five-node luma-plane-blend graph. A
  0.5s fade on a 30fps reel is 15 frames whose last one lands wherever the
  reel's own duration puts it — measured 7.5/255 on a 3s test, "near 0" not
  exactly 0, no visible consequence. The mask renders once per `deliver`
  call at the master's probed dimensions, uncached by design — a cached
  mask keyed on the wrong dimensions is a silent letterbox, and the thing
  being avoided costs a tenth of a second.

  **Deferred (design §12) — every row now in `docs/backlog.md` (this
  task), per the 2026-08-12 rule.** Grain (P3, the look tail, with its cost
  table so nobody re-measures); folding "does the look actually render"
  into #10's 3-frame probe (P2); calibrating `LOOK_VIGNETTE_MAX`/the
  plateau-falloff split/`MoodPreset.look` on real footage (P2); the
  chroma-preserving vignette, if the desaturation reads wrong on real
  footage (P4); a per-episode look override (P4) — plus the two findings
  above (`shadow_red_arg`'s worse defect, P2; `highlight_red_arg`'s
  shoulder fragility, P3). #9 does **not** close: its P1 look half is done,
  the P2 grade half (mood biasing `match_grade`'s common target — the
  long-deferred "mood LUT") and the P3 tail stay open. #18 **does** close —
  all five originally-named pieces (zoom, ramp, look filters,
  `highlight_red`, `outline-bold`) now have their own real-ffmpeg
  visibility proof.

  **One production fix riding this task:** `scripts/lib/lint.py`'s own
  `_seek_order` error message cited `scripts/mix.py:193` as an example
  `-accurate_seek` call site; the bookend fade moved off that line during
  the slice (it is now the fade-validation guard), and the real
  `-accurate_seek` call sits at `scripts/mix.py:205`. Corrected;
  `tests/lib/test_lint.py`'s own `REAL_SITES` fixture dict had already been
  resynced to the same line in Task 10 — this was the one remaining stale
  citation, in a user-facing message rather than a test fixture.

  **2761 passed / 3 skipped**, full suite (unchanged from Task 10's own
  count — this task is docs-only plus the one-line lint.py message fix,
  which no test asserts on literally). The three skips are the
  pre-existing environment ones (demucs, torchreid, no-network iTunes),
  none new. **Mutation battery (Task 10, 14 rows + one historical bonus
  row): all 15 caught by an existing test — no coverage hole needing a new
  test.** Two of the battery's OWN row pointers were themselves stale
  (found and corrected in Task 10, not new tests): row 7's named test used
  a `probe_stream` stub that discards its argument and cannot discriminate
  a hardcoded mask size (a different, already-existing test does); row 9's
  named test authors a truthy non-empty dict that passes under either the
  `is not None` or the truthiness spelling (a different, already-existing
  `{}`-specific test does).

- **Housekeeping — the four orphaned deferrals, and a backlog that is a queue
  DONE (2026-08-12)** — plan `docs/plans/2026-08-12-housekeeping-backlog.md` +
  design `docs/specs/2026-08-12-housekeeping-backlog-design.md`. An audit of all
  28 design `§Deferred` sections against the code found **four items that had
  left every list**, three of them shipping as live defects. (1) `Spec.platform`
  was written by `reel_brief` and read by nothing that builds a reel, so
  `ReelManifest.platform` stayed `""` and both consumers — `check_reel`'s
  safe-zone section and `titles.y_exprs` — silently judged and typeset against
  the generic table; `EDL.platform` now carries it from `edit_plan --spec` to
  `edl_to_reel`. (2) `EDLEpisode.smooth_window_s` could not be authored though
  `ReframeSpec` had the field — deferred by colour-stage §11 and rediscovered by
  speed-ramp §9 as an accident three weeks later; it is authorable now, and
  because it is a **retry-ladder knob**, `adjust_reframe_params` gained a `floor`
  so a lag retry can no longer halve an authored 0.6 back toward the 0.25 default
  and discard the instruction. (3) `draft.py` rendered an **8×16-pixel** video: it
  spent `ProjectConfig.canvas`, an *aspect* tuple, as pixels. Two tests protected
  it — the unit test hand-passed the right pixels, and the integration fixture
  hand-wrote `canvas: [1080, 1920]`, literal pixels wearing an aspect's name,
  whose equality assertion passed only by coincidence. Both fixed; the proof now
  probes the real output file (8×16 → 606×1078). The obvious one-line fix was a
  trap: `Delivery.dims` for `native` is exactly `(even(w), even(h))`, so it would
  have returned `(8, 16)` one call deeper. (4) `Spec.reel_count > 1` was accepted,
  printed as "3 reels" and produced one; it refuses now, keeping the field for the
  day fan-out lands. Three stale pointers corrected in the same pass — a "Phase F"
  that never existed, a cv2 blocker that disappeared when the tracking ladder
  landed, and three layer-3 entries written as though track-stitch had not
  shipped. **The root cause was structural**, and is what the slice actually
  fixes: four documents recorded deferrals and none of them was a *queue*.
  `docs/backlog.md` is now the single place holding priority and status, and
  `development-workflow.md` carries the rule that a slice is not finished until
  its design's `§Deferred` has rows there. Honest limit (design §6): nothing
  machine-checks that rule, and four orphans is a lower bound — the sweep matched
  deferral-shaped headings, so one phrased mid-paragraph elsewhere was not found.

- **Speed ramp — slow-mo as a first-class, length-aware EDL knob (fixes-backlog
  #7, and the speed half of #18 — cinematic-quality playbook priority 4, its
  second slice) DONE (2026-08-09)** — plan
  `docs/plans/2026-08-09-speed-ramp.md` + design
  `docs/specs/2026-08-09-speed-ramp-design.md`, Tasks 0–10 (branch
  `feat/speed-ramp`, commits `e65eb1b`..`1aed618` + this docs sync). The
  2026-08-03 real run added slow-mo by patching the engine live (parked on
  `wip/montage-run-patches`, `fbcd052`, "NOT suite-validated") and updated
  exactly two length readers — `to_manifest_dict`'s `target_dur` and
  `EDL.to_markdown`'s total — while scenario-first pacing's beat-grid fitter,
  the pacing binding guard, the back-edge target and `edl_to_reel`'s reel
  target all kept reading `ep.dur`: every cut after a ramp silently drifted
  off its musical line. This slice makes the ramp's added time a first-class
  fact every length consumer reads, instead of an afterthought two functions
  happened to see. **The rule: two lengths, both named (design §1).**
  `EDLEpisode.dur` is how much SOURCE the episode consumes; the new
  `play_dur()` is how long it PLAYS — `dur + ramp_extra(ramp, dur)`, equal to
  `dur` without a ramp. **The enclosure refusal (design §2).** A `RampSpec`'s
  region `[at − hold/2 − ease, at + hold/2 + ease]` must lie inside `[0,
  dur]`, checked in `EDLEpisode.__post_init__` (so `dataclasses.replace`
  re-validates on every pacing bind) — not tidiness: with the region
  enclosed, `ramp_extra` becomes a `dur`-independent CONSTANT, which is what
  lets `edit_plan._bind_pacing` invert "what source window plays for
  `slot.dur` seconds?" with one subtraction instead of a solver. **The
  render: one ffmpeg pass, knots anchored to the region (design §3).**
  `O(t) = ∫1/s` has no closed form under the cosine ease, so it ships as a
  piecewise-linear `setpts` expression built from knots that `ramp_extra`
  (the record) and `setpts_expr` (the render) both read from the SAME
  `knots()` call — record and render cannot drift apart. The knot PLACEMENT
  was the slice's one real design correction, caught while the plan was
  being written: spreading knots evenly across `[0, dur]` makes the
  approximated `ramp_extra` drift with the window length — 2.0812s at
  `dur=3.5` against 2.0779s at `dur=6.0` for the reference spec, a 3.3ms
  spread that grows to 124ms on a shorter ease, silently breaking §2's
  constancy claim and with it `_bind_pacing`'s subtraction. Anchoring
  `RAMP_EASE_KNOTS = 16` knots to each ease instead, and spending exactly one
  interval on each flat and the plateau (where `1/s` is constant and the
  trapezoid is exact), makes `ramp_extra` bit-identical across
  `dur ∈ {3.5, 4.0, 6.0, 9.0}` — reconfirmed directly against the shipped
  `scripts/lib/ramp.py` while writing this entry — and cuts the error
  against an independent Simpson integration from 5.3ms to **1.8e-15s**,
  twelve orders of magnitude, because the cosine ease's derivative vanishes
  at both ends and kills every Euler–Maclaurin correction term (measured:
  the value stops moving between 8 and 16 subdivisions, Δ=1.4e-10). The
  reference spec (`at=2.0, factor=0.4, ease=0.5, hold=1.0`) yields **36
  knots** — 32 spent on the two eases (`RAMP_EASE_KNOTS` each), 4 on the
  region's own boundaries and the window's — and a **1758-character**
  expression, the same order as the zoom's crop-path expression. **What the
  render still costs.** The design's own pre-implementation check rendered
  the reference spec at 6.0667s against an analytic 6.0811s — 14.5ms of pure
  frame quantization (6.0811s × 30fps = 182.43 frames, `fps=` emits 182), not
  knot error. The shipped real-ffmpeg golden
  (`tests/integration/test_ramp.py::test_the_rendered_length_matches_the_recorded_one`,
  `at=1.0, factor=0.4, ease=0.25, hold=0.5` on the new 60fps `ramp_clip`
  fixture) tells the same story at a different scale, reconfirmed by direct
  measurement while writing this entry: analytic `play_dur()` 3.0406s against
  a rendered 3.0330s, a 7.6ms residual — under half a frame at 60fps, well
  inside the test's own `abs=2.0/FPS` (two-frame) tolerance. **Visibility —
  backlog #18's demand, measured directly against the shipped fixture:** mean
  `|frame − prev|` over decoded gray frames (the way `lib/anchors` already
  measures motion) reads 0.657 in the normal band and 0.257 on the plateau, a
  ratio of **0.391 against a commanded `factor` of 0.40** — the picture is
  actually slowing, not merely an argv that looks correct. (The design's own
  §11 illustrative number, 0.453, was measured against a preliminary spec
  this slice's shipped fixture superseded; 0.391 is what
  `test_the_ramp_actually_slows_the_picture` measures today, reproduced
  independently while writing this entry.) **Where it runs, and why (design
  §4).** `extract_edl` cuts `ep{i}_raw.mp4`, then — when the episode carries
  a `ramp` — `ramp.retime` replaces that file IN PLACE with a one-pass
  `setpts='(…)/TB',fps=<source fps>` render before tracking ever sees the
  segment: a pre-stage writing a file, exactly like vidstab's own stabilize
  pre-stage (2026-07-20 §1) and for the same reason — the route must be
  measured on the pixels that ship, or `check_episode` would confirm a
  framing that agrees with itself while disagreeing with the pixels. The
  retime is video-only (`-an`): slowed audio is pitch garbage, and
  `mix._build_ambient`'s existing `anullsrc` substitution keeps the ambient
  bed in sync by construction. **The judder gate, no waiver (design §5).**
  `MIN_RAMP_FPS = 24.0` — a hard refusal, not a clamp — is checked twice:
  free, in `edit_plan.window_to_episode`, against `FootageClip.fps`, before
  any encode is spent; and again in the extract pre-stage against the
  PROBED rate, catching a hand-authored EDL that skipped the first gate.
  `factor` is a literal multiplier (`0.4` = 2.5× slower), so the floor is
  `24 / fps` — 0.4 on 60fps footage, 0.8 on 30fps. **Eight length sites
  converted (design §6), each reconfirmed at its shipped location — seven
  found while designing this slice, an eighth by its final whole-branch
  review:** `pacing.build_pacing`'s `durs` (`pacing.py:86`), `pacing._bounds`'s
  inward shrink floor (`pacing.py:43`, via the new `ramp.tail_room`),
  `edit_plan._bind_pacing`'s guard (`edit_plan.py:211`) and its assignment
  (`edit_plan.py:222–223`, `dur = slot.dur − ramp_extra` — exact, because
  §2's enclosure makes `ramp_extra` constant), `edit_plan._back_edge_target`
  (`edit_plan.py:246`), `edl.to_manifest_dict`'s `target_dur` (`edl.py:375`),
  `edl_to_reel`'s reel target sum (`edl_to_reel.py:148`), and
  `edit_plan.build_edl`'s ASL average (`edit_plan.py:370`, `sum(e.dur) /
  len(episodes)` → `sum(e.play_dur()) / len(episodes)` — the review's find:
  `moodpreset.py` only ever REPORTS `asl` against a band, never enforces it,
  so the miscount was mechanically harmless but still falsified "every length
  consumer reads `play_dur()`") — plus `EDL.to_markdown`'s total and a
  `⏱ ramp x2.5 @2.0s (plays 6.08s, silent)`-shaped row annotation. Every one
  now reads `play_dur()`, not `dur`, wherever it means screen time.
  **End to end (Task 8, real ffmpeg through a faked
  `process_episode` middle — see the honest-record note below):** `dur=2.0s`,
  analytic `play_dur()=3.0406s`, delivered master measured at **3.033s** —
  within 8ms of the played length (frame quantization, same story as above)
  and 1.03s longer than the 2.0s source window it was cut from. **The
  rejected renderer (design §0, §3.4).** The parked WIP's `apply_ramp` opened
  a decoder/encoder `Popen` pair and pumped raw RGB frames through Python — a
  fourth `subprocess` importer beside `fetch`/`catalog`/`proc`, invisible to
  the landmine lint's `proc.run` chokepoint. Measured at 1080p60/3s: the
  one-pass `setpts`+`fps` render took 0.85s wall-clock for an identical
  5.083s output; the parked pipe took 1.12s — **1.32×** the cost — and pushed
  **1.90GB** through the pipe (quadrupling at 4K). Speed was the weakest of
  the three arguments; going through `proc.run` where the lint can see it,
  and deleting ~60 lines of hand-rolled frame pumping, were the deciding
  ones. **Honest limits (design §12, carried here in full).** Slowing
  duplicates frames; it recovers no detail never shot — a 24fps plateau from
  a 60fps source is this design's ceiling, not a floor it improves on. A
  ramped segment loses its natural sound entirely (recorded in
  `processing_notes`, not left to be discovered). Record and render differ
  by under one frame — `fps=` cannot emit a fractional frame, so the EDL's
  number is not bit-exact against the file, though three orders of magnitude
  under the length gate's ±0.5s band. The ramp costs a second encode
  generation (crf 8, near-lossless — crf 18 was measured too lossy once a
  held frame is enlarged by a later tight hero crop). `MIN_RAMP_FPS = 24.0`
  is a film-rate convention, not a measurement against this engine's own
  footage — the constant here most likely to want revisiting. The
  hand-authored front door still bypasses the early gate: an `EDL.json`
  driven straight through `edl_to_reel`'s SP1 door meets only the extract
  pre-stage's judder check, never `edit_plan`'s — one gate rather than two,
  the same shape #17 and #14 already recorded (no *silent* bypass, not no
  bypass). And the gate proves the ramp is renderable, its claimed length is
  its played length, and the slowdown is visible in pixels — never whether
  this was the right moment to slow down. **Deferred (design §13), not
  rejected:** interpolated slow-mo (`minterpolate`) — real intermediate
  frames instead of duplicates, deliberately not offered because
  whitewater/spray is optical flow's worst case (melting artefacts, a worse
  failure than honest judder) and needs its own artefact study first;
  speed-UP (`factor > 1`) — the whole design rests on `s ≤ 1` meaning frames
  are only ever duplicated, and a speed-up drops motion, a different
  argument; a ramp spanning more than one plateau — the contract admits one
  region by construction; and auto-placing `at` from `lib/anchors`' action
  peaks — tempting, and exactly the guess-instead-of-look pattern #12 exists
  to stop, so it needs the QC judge's eyes, not a heuristic. **Honest-record
  items, worth more than the wins.** (1) The landmine-lint proof
  (`test_the_retime_argv_passes_the_landmine_lint`) proves less than its name
  suggests — verified directly against `scripts/lib/lint.py` while writing
  this entry: `_seek_order` short-circuits on
  `if "-t" not in cmd and "-to" not in cmd: return []` (the retime argv has
  neither), `_unbounded_source` needs a `SYNTH_SOURCES` token present before
  it ever calls `_element`, and `_zoompan_defaults` needs a literal
  `"zoompan="` to split on — none of the three appears in a `setpts`+`fps`
  argv, so only the always-on `lutrgb` substring scan does any real work.
  The test does prove the production guarantee that matters (the lint does
  not refuse a real ramp render), just not that `_element`'s quote-aware
  parsing — the exact thing that once silently refused every real zoom
  render — was exercised here. (2) The end-to-end proof (Task 8) fakes
  `process_episode`: real YOLO finds no person in the synthetic drawn box,
  tracking falls to optical flow, and that route fails `check_episode`'s
  continuity gate — the same limitation
  `tests/lib/test_tracking_ladder.py::test_empty_yolo_route_falls_to_optical_flow`
  documents, and the reason `tests/integration/test_edit_plan.py` fakes the
  same middle. So Task 8 establishes the LENGTH chain through a real retime
  at extract; it does not establish tracking or framing on a ramped clip.
  (3) **The mutation battery (Task 9, 21 rows, reconfirmed against the
  shipped diff) found three real coverage holes, all closed with new tests —
  18/21 caught outright:** `probe_stream`'s `r_frame_rate` reports the
  container's declared nominal rate and never moves whether or not `fps=`
  ran, so the row-3 mutation (dropping `,fps=…`) survived until
  `test_the_retimed_stream_actually_holds_fps_many_frames_per_second`
  asserted the real frame COUNT instead; the `ramp_clip` fixture carries no
  audio stream at all, so dropping `-an` (row 5) left "no audio out" true
  either way until `test_retime_drops_a_source_that_actually_has_audio`
  muxed a synthesized tone in first; and the cosine and linear eases
  coincide exactly at both endpoints AND at the exact midpoint
  (`cos(π·0.5) = 0`), precisely the three points
  `test_the_ease_is_monotonic_and_meets_both_ends` sampled, so swapping the
  cosine for a straight line (row 18) survived until
  `test_the_ease_follows_the_cosine_shape_not_a_straight_line` checked an
  off-centre point. (4) The length proof's tolerance is loose: `abs=2.0/FPS`
  is two frames — double the one-frame quantization the design claims as the
  true residual — against a measured residual of 0.0076s; a genuine
  ~1-frame regression would slip through today. **Two out-of-scope gaps
  this slice found and deliberately did not fix (design §9):** `EDLEpisode`
  cannot author `smooth_window_s` even though `ReframeSpec` has carried the
  field since path-quality (2026-07-28) — a real one-field authoring hole,
  unrelated to length; and `draft.py` uses the canvas aspect where it needs
  delivery pixels — a correct fix, but independent of the ramp and belongs
  on its own evidence. **2614 passed / 3 skipped**, full suite (re-run
  during this docs-sync task) — the same three pre-existing environment
  skips (demucs, torchreid, no-network iTunes), none new, no golden fixture
  moved; an unramped run's argv and segment bytes stay identical by
  construction (`test_an_unramped_extract_is_unchanged_by_this_slice`) — NOT
  `EDL.json` itself, which now carries a `"ramp": null` key on every episode
  (the same precedent as `pan`/`zoom`/`stabilize`), harmless to provenance
  because `digest_obj` hashes the dict as loaded. **`ramp.retime` writes with
  no post-condition (design §12, recorded not fixed).** Unlike
  `vidstab.stabilize`, which probes its own output and refuses a geometry
  change or a >2-frame duration drift, `ramp.retime` verifies nothing it
  wrote — a wrong retime surfaces only downstream, at `check_reel`'s ±0.5s
  reel-length gate, and is attributed to the REEL rather than the episode
  that actually caused it. Not implemented here; a probe-and-refuse
  post-condition is new behaviour and needs its own evidence, the way
  vidstab's did.

- **Subject-anchored frame moves (fixes-backlog #17, and the frame-moving half
  of #18 — cinematic-quality playbook priority 4, its first slice) DONE
  (2026-08-08)** — plan `docs/plans/2026-08-08-subject-anchored-moves.md` +
  design `docs/specs/2026-08-08-subject-anchored-moves-design.md`, Tasks 0–14
  (branch `feat/subject-anchored-moves`, commits `8a668f0`..`5497c7a` — the
  battery + this docs sync are `36ae135`, the final review's fix wave
  `5497c7a`). The 2026-08-03 real run shipped ep5 as a `pan`, and its
  `report.json` read `framing: editorial-only`, `continuity: not-checked`,
  `color_fidelity: not-checked` — three of `check_episode`'s checks turned off
  on the AUTHOR's word alone, over a shot with a surfer in it. Each arm is
  individually correct (you cannot judge composition against a subject never
  observed); the defect was that nothing ever established the premise they
  rest on. This slice closes that on both applications design §1 names.
  **Half A — `pan` stops being an escape hatch.**
  `edit_plan.window_to_episode` refuses a `pan` when `window.present >
  PAN_PRESENCE_MAX` (0.10) — a MEASURED fact from intake's own YOLO pass, not
  a claim; `_merge_windows`, found while reading for this, reported a merged
  span's FIRST window's presence rather than the busiest one in the span (a
  span starting empty and filling with people would have slipped the gate),
  fixed alongside. The hand-authored `edl_to_reel` door, which never sees
  `FOOTAGE.json`, keeps the weaker check that needs none: `manifest.validate`
  and `edl.preflight` refuse a `pan` beside a hero pin or cast name outright
  — a self-contradiction readable from the EDL alone. **Half B — `zoom`.** A
  `ZoomSpec` push-in/pull-out is not a generated path like `pan`: at every
  route sample the crop's rect is chosen by the SAME `geometry.crop_x`
  composition rule that places every tracked episode's crop — only the width
  in force at that sample shrinks or grows — so the subject sits on its
  composition line throughout the move and framing/continuity/color_fidelity
  all apply exactly as they do to any tracked episode. The shrinking rect is
  cut by a `zoompan` inserted between the existing `crop` and `scale`, `z` in
  CLOSED FORM (`1/s(t)`, never the knot-simplifying `_xexpr` builder — a
  two-knot linear approximation of a hyperbola is 6.6% wrong at the midpoint
  of a 1.0→0.6 push-in) and `s` forced to the CROP's own dimensions, never
  the delivery's (zoompan clamps `z` below 1 to 1 byte-identically, so an `s`
  smaller than the crop would silently render nothing). `PathMeta` gains
  three optional parallel arrays (`crop_ws`/`crop_hs`/`crop_ys`, plus a
  `zoomed` PROPERTY rather than a redundant bool that could disagree with
  them) recording the per-sample rect ffmpeg actually cut; the two geometry
  chokepoints (`marks_at_times`/`extent_at_times`) and
  `checks.on_line`/`centered`/`jitter` read that record instead of three
  scalars, which is why fixing two functions also fixes `safezones`,
  `key_action`, the storyboard's marks and `check_reel`'s geometry section
  without any of them learning a zoom exists. **The measured numbers — the
  evidence this renders real pixels, not a plausible-looking argv:** the
  push-in proof (`ZoomSpec(1.0→0.6)` over a marked synthetic clip) measured
  the subject's on-screen width grow 24px → 39px, a ratio of 1.625 against
  1.6667 expected (2.5% deviation, inside the proof's 12% tolerance — encode
  edge-softening + integer rounding account for the gap). The upscale
  headroom table that forced `ZOOM_MAX_UPSCALE = 1.5` (refusing every
  upsample was measured to cap the reel format this engine exists for below
  visibility): 9:16 native delivery, 1215px crop vs 1214px out — 1.001×; 9:16
  at 1080x1920 — 1.125×; 16:9 at 1920x1080 — 2.000×. **Two defects this slice
  found in its OWN safety net, and did not hide.** First (Task 13's real-pixel
  proof, fixed in `0d50db4`): `lint._element` was quote-blind — it bounded a
  filtergraph element at the first RAW `,`/`;`/`[`, and `reframe._xexpr`
  emits zoompan's `x=`/`y=` as `if(lt(it,T),then,else)` whenever a path has
  two or more knots (always, in practice — Douglas-Peucker keeps both
  endpoints), so the element was cut off INSIDE the quoted expression,
  discarding the real `:d=1:s=...:fps=...` that followed it. `check_argv`
  then reported a fully correct zoompan as missing all three defaults, and
  because `proc.run`'s guard is always-on, it refused every real zoom render
  before ffmpeg ever ran — invisible to every unit test (the lint fixtures
  used a literal `x='0'`; the reframe zoompan test monkeypatched `proc.run`
  past the guard) and surfaced only by the real-ffmpeg proof, which failed on
  a `ValueError` from the lint guard, never on a pixel. Second (found
  writing Task 12's own check, fixed in the same commit `c053263` that added
  it): the fifth landmine check's own `"s=" in body` test was ALWAYS true
  whenever `fps=` was present, because the string `"fps="` ends in the same
  two characters `"s="` — it would have silently failed to detect the exact
  hd720 landmine it exists to catch, on any zoompan that remembered `fps=`
  but forgot `s=`. Both are now anchored (a word-boundary regex per
  required key; a quote-aware element bound), and neither was hypothetical —
  the first refused every one of the four real-pixel proofs the moment they
  first ran. **A third, found in the whole-branch review that followed and
  closed in the same pass:** the quote-aware toggle itself latches
  `in_quote=True` for good on an ODD apostrophe count (an unbalanced quote),
  so it never finds a way out and returns everything to end-of-string as
  "the element" — the OPPOSITE failure from the first, a silent MISS that
  lets a neighbouring filter's own `s=`/`fps=`/`d=` satisfy an element that
  never set any of them. Dormant (no producer here emits a quote today, let
  alone an unbalanced one) but unenforced, so it was parked rather than
  shipped blind; closed by falling `_element` back to the pre-fix quote-blind
  bound the instant a quote fails to close — the same false-positive-over-
  miss preference this module already commits to everywhere else it faces
  this choice. **Design §11 defers four widenings, none built here:** a
  scenery zoom (Ken Burns) over a subject-less shot — legitimate, deliberately
  excluded so narrowing the generated branch and widening it don't happen in
  the same breath; a vertical component (the zoom holds the frame's vertical
  centre; a tilt needs the route's own y and a headroom rule that does not
  exist yet); easing (`s(t)` is linear, as `PanSpec`'s travel already is —
  belongs with the speed-ramp slice, #7); and re-scoping `pan` as a special
  case of `zoom` (both are now "a rect path over time", tempting but premature
  until the scenery zoom above exists to unify with). **The honest limits,
  from design §10, in full.** The
  hand-authored `edl_to_reel` door never runs the tracker on a `pan` episode
  (deliberate — a scenery shot should not pay for a YOLO pass it does not
  need), so it never sees the MEASURED gate, only the self-contradiction one.
  `PAN_PRESENCE_MAX` (0.10), `ZOOM_MAX_RATE` (0.5 crop-widths/s) and
  `ZOOM_MAX_UPSCALE` (1.5×) are uncalibrated first cuts — nobody has judged a
  1.5× push-in on real graded footage — and `ZOOM_MAX_UPSCALE` is the
  sharpest admission of the three: the exact point where this design stops
  refusing upsampled pixels and starts permitting them. The recorded and
  rendered rects can differ by up to a pixel (`w_i = int(W0/z_i)` in
  Python's doubles vs ffmpeg's own division in its own doubles). A zoom
  costs a second resample (region → crop size → canvas, where an unzoomed
  episode resamples once). Presence is a people-only proxy — a dog, a car or
  a drone reads as subject-less and may still be panned, the same gap
  intake's whole people-first model already carries. And the gate proves the
  PREMISE, never the taste: it establishes a panned shot held no people; it
  says nothing about whether the pan was a good move, which stays
  episode-QC's and CP3's question. **Mutation battery (Task 14, 14 rows): 9/14
  caught exactly as named; 3/14 caught by a different test than the row named
  (a stale mapping, not a hole — see below); 2/14 genuine holes, found and
  closed with new tests.** `zoom.rects`'s `int(crop_w/z)` vs `int(crop_w*s)` mutant
  survives the existing test's chosen numbers (1001×0.7 and 1001/(1/0.7) land
  on the SAME double under Python's rounding — the test's own comment already
  flags this for a `round()` mutant but not an `int()` one); a second pair
  (650/1300) that disagrees even under truncation closes it. `reframe`'s
  containment-centring line (`base_xs`) had no test anywhere in the suite
  catching its removal — the width-ratio proof (design §9 proof 1) only ever
  checked magnification, never position, though §9 itself asks for both ("its
  normalized x stayed on the composition line"); closed with a position proof
  predicted from the SAME sidecar the render writes, not a flat centre line
  (the test route's coarse 1Hz sampling legitimately lags the target under
  `max_speed` rate-limiting even on correct code). Three further rows are
  each caught, but by a different test than the one named, for three
  different reasons: the `s=`-set-to-the-delivery row's named pixel proof
  can't discriminate on a zero-freedom fixture (the crop and the delivery
  cancel algebraically) but a lib-level string assertion on the emitted
  argv does; the `d=1`-drop row's named test builds its own literal argv and
  never calls into `reframe.py` at all, so it can't see the mutation, while a
  sibling lib test (a real string check) and every real-pixel zoom proof (via
  `proc.run`'s always-on guard) both do; and the jitter edge-vs-centre row's
  named test happens to pick numbers where the "right"-direction edge
  matches the correct centre's answer by coincidence, while its very next
  sibling test — written for exactly this — does not. **2534 passed, 3
  skipped**, full suite (pre-slice baseline: 2423 passed, 3 skipped) — the
  same three environment skips as always (demucs, torchreid, no-network
  iTunes), none new, no golden moved.

- **Per-episode QC gate before reel assembly (fixes-backlog #3, the per-episode
  half of #12, cinematic-quality playbook P3) DONE (2026-08-08)** — plan
  `docs/plans/2026-08-08-episode-qc.md` + design
  `docs/specs/2026-08-08-episode-qc-design.md`, Tasks 0–10 (branch
  `feat/episode-qc`, commits `15e773d`..`d5aa4e8` + this docs sync). The
  2026-08-03 real run shipped episodes nobody had looked at: `edl_to_reel`
  calls `process_episode.process_episode` as a **Python function** inside a
  `ThreadPoolExecutor`, never a subagent, so the editorial gate
  `skills/process-episode/SKILL.md` describes was dead text on every
  conveyor run — it fires only when a human drives one episode by hand. This
  slice puts a new gate where the render actually happens, not where the old
  skill text imagined it. `edl_to_reel` splits into two phases around that
  seam: `--stop-after-episodes` renders every episode and writes
  `EPISODES.json`, a serialized `ReelManifest` (`ReelEpisode`/`ReelManifest`
  finally gain `to_dict`/`write`, Task 0 — closing an asymmetry where
  `build_reel`'s CLI could read a manifest that nothing in the codebase could
  write); `--from-episodes` gates on `EPISODE_QC.json` found **beside it, by
  convention** (no flag to forget — the editorial-constraints slice's own
  reasoning) before `build_reel` runs at all. One fresh judge subagent per
  episode (cap 3, the new `episode-qc` SKILL) reads an evidence packet — a
  frame strip off the DELIVERED clip, the storyboard, `check_episode`'s
  mechanical `report.json`, and a new colour-naturalness sensor
  (`lib/naturalness.py`: blown highlights / crushed blacks / colour cast /
  oversaturation / flatness, averaged per frame, never pooled, so one bad
  frame in a long episode can't read as a blown episode) — and writes
  findings against five axes: `composition`, `colour`, `impression`, `path`,
  and `hero` (*is the followed subject the intended one* — its own axis
  because a beautifully composed, naturally graded, smoothly tracked episode
  that follows a stranger must still fail). `episode_qc build` validates
  every judge's raw findings into a typed `ReelQC`
  (`EpisodeVerdict.verdict` is a **computed** property — `revise` iff any
  `blocking` finding — never a stored field a hand-edited artifact could lie
  through) and stamps `clip_digest` **itself**, from the file on disk,
  overwriting whatever the judge's file claimed — the producer/consumer
  split that turns "this episode was judged" into "**this render** was
  judged." The pure gate (`episode_qc.gate`) refuses in a fixed order —
  incomplete (some episode has no verdict, or a verdict names an episode the
  reel doesn't have), then stale (a verdict's digest no longer matches the
  clip on disk), then blocking (a judged verdict carries a `blocking`
  finding) — before a single ffmpeg call, writing nothing. No waiver field
  exists anywhere on this path (governance #8): a subagent proposes
  findings, never the gate's inputs. `montage.V1_STAGES`' single `deliver`
  row becomes three required stages — `episodes` → `episode-qc` →
  `deliver` — so a run cannot resume past an episode nobody judged.
  **The hole this shape carries (design §8), stated plainly:** `build_reel`'s
  loop-2 reprocesses a culprit episode (colour convergence, and for a
  stabilized episode a full re-track) AFTER the QC gate has already run — a
  verdict on that episode is stale the moment its clip is rebuilt, and this
  slice does not close that. Forbidding the auto-reprocess would close it,
  and was rejected (design §2) because it would also kill the colour-
  convergence loop Phase A.5 exists for. What lands instead: `build_reel`
  reports every episode it reprocessed (`result["reprocessed"]`, accumulated
  across every round, not just the last), and the delivery's attestation
  carries an `episode_qc` block (`state: "judged"|"absent"`, the per-episode
  `judged` digests, and `reprocessed_after`) — so a re-rendered-post-verdict
  episode is at least **named**, never silently reshipped as "judged" without
  qualification. The single-command `edl_to_reel` (the hand-authored SP1
  front door) still ships with `episode_qc: {"state": "absent"}` — unjudged,
  and honestly says so; no silent bypass, not no bypass. **§12 honest
  limits, carried here rather than left in the design alone:** the stage
  gates the artifact's PRESENCE and its digest BINDING, never proof that
  anyone looked — an empty findings list is indistinguishable from a
  diligent judge's; the sensor's advisory flags rest on threshold constants
  that are first cuts, never run against real graded footage; a pan episode
  has no route and no marker, so its `hero` axis is reported not-judgeable,
  never passed; QC is per-episode and blind to adjacency (still
  reel-review's question); and an agent with a shell can re-run the judge
  until it comes back green — `reviewer` is a record, not a prohibition.
  **Mutation battery (Task 10, 11 rows): all eleven held** — no coverage
  hole to close. It probed the gate's three-reason precedence and each
  reason's own predicate (a missing verdict, blocking checked before stale,
  the digest comparison defeated), the digest producer/consumer split
  (`build_qc` ignoring the judge's own claimed digest), the fail-loud
  missing-`findings.json` refusal, the computed-not-stored `verdict`
  property, `assemble_reel` actually gating before `build_reel` runs, the
  single-shot path's honest `absent` state, the reprocessed accounting
  (whose accumulation across rounds is separately pinned by
  `test_reprocessed_accumulates_across_rounds_for_different_episodes`), the
  sensor's per-frame averaging (vs. a pixel-pooling regression), and the
  router stage's `required` kind. **It did not and cannot probe** whether a
  judge actually looked before writing an empty findings list (§12's own
  limit — no code predicate distinguishes diligence from a rubber stamp),
  the sensor's threshold VALUES (only its aggregation logic was mutated),
  or the `episode-qc` SKILL's dispatch behavior (cap-3 concurrency, one
  packet per judge) — that lives in prose dispatched to subagents, not in a
  function the battery can call. **2403 passed / 3 skipped**, full suite
  including integration (the same three skips as the pre-branch baseline of
  2339 passed / 3 skipped — demucs / torchreid / no-network iTunes smoke;
  none newly skipped), no golden moved.

- **Editorial-constraint memory (fixes-backlog #14, the last CHEAP item of
  cinematic-quality playbook P3 — design §0) DONE (2026-08-07)** — plan
  `docs/plans/2026-08-07-editorial-constraints.md` + design
  `docs/specs/2026-08-07-editorial-constraints-design.md`, Tasks 0–6 (branch
  `feat/editorial-constraints`, commits `9dd2b84`..`546ef4c` + this docs
  sync). The 2026-08-03 real run broke two rules the user had stated out
  loud — a bookend (*"one hero opens, the other closes"*) and a no-repeat
  rule — and both were mechanically checkable over an EDL; neither was
  checked, because neither was written anywhere a checker could reach. This
  slice gives a stated rule a home: `CONSTRAINTS.json`, discovered BY
  CONVENTION beside `project.json` — there is no flag to forget, so a
  present file binds every later `edit_plan build`, which is what makes the
  rule survive a re-cut. **The vocabulary is four CLOSED kinds and only
  four:** `no_repeat` (no two episodes share one shot), `open_with` /
  `close_with` (the first / last episode must pin a cast name), `exclude`
  (bans a shot, or a whole clip). An unknown `kind` is a load-time refusal,
  never a stored-but-unenforced note — so a rule that does not fit one of
  the four ("don't put two drone shots back to back") cannot be written
  down at all: it stays in chat and is forgotten, exactly as before this
  slice, and the skills now say so out loud instead of inventing a field.
  The identity unit is the SHOT, not the window or the time span: new
  `FootageClip.shot_at(t)` returns the scene-cut segment containing `t`,
  sharing `room_after`'s `c > t` boundary rule so the two authorities never
  disagree about where a shot ends; `no_repeat` groups episodes on
  `(source, shot)` and `exclude` compares against the same shot bounds, so
  two windows carved from one drone pass are a repeat even when their spans
  do not overlap — the case the real run actually produced (a per-window or
  per-interval comparison would have missed it). New pure
  `scripts/lib/constraints.py` (`Rule`/`Constraints`/`Placed`/`Violation`/
  `ConstraintReport`/`evaluate`) stays import-clean of `edl.py` (`edl.py`
  imports `ConstraintReport` to carry it, so the dependency runs one way);
  `edit_plan._placed` projects each episode, and a `hero` reaches the
  projection only as a cast NAME — a bbox, a track id, or a `HERO_RULES`
  string like `"largest"` projects to `None`, which a bookend rule reads as
  *unsatisfied*, never satisfied. `build_edl(rules=)` only measures — a
  missing `rules` (no file) leaves `EDL.constraints` `None`, read as "not
  evaluated," never "passed"; `write_edit_plan` is the one that refuses,
  with reason `constraint-violation`, **before** the variety gate (a
  human's stated rule outranks a preset's inference) and before preflight,
  writing nothing. **There is no waiver** — the variety gate's waiver is
  legitimate because that rule is the machine's own guess; this one is the
  user's sentence, and a waivable path here would reproduce the exact
  2026-08-03 failure with a paper trail. The report rides in
  `EDL.json`/`EDL.md` (`EDL.constraints`; the `## Editorial rules` section
  renders only when a rule file was present and non-empty), so a later
  reader sees which rules bound the cut without reconstructing the session.
  **Honest limits (design §10):** `edl_to_reel`'s hand-authored `EDL.json`
  front door — the SP1 door by design — never sees this gate, so a
  hand-built EDL bypasses every rule here; deleting `CONSTRAINTS.json`
  passes everything, because the invariant is *no silent bypass*, not *no
  bypass* (an agent with a shell can always delete a file — what it cannot
  do is skip the gate while the file is there); `no_repeat` catches one
  shot used twice, never two different shots that merely look alike (a
  second pass of the same beach, cut identically, reads as a different shot
  — visual similarity is a different sensor, deferred, §11); and a bookend
  rule needs cast-name pins on the edge episodes, so a project with no
  `cast.json` can satisfy it only by failing loud — not merely leaving it
  unchecked, but making it unusable there. **Mutation battery (Task 6, 9
  mutations across 8 sites):** every one — the `_no_repeat` shot-identity
  key mutated both directions (coarsened to source-only, narrowed to
  per-occurrence), `_bookend`'s unpinned-edge pass-through, `_placed`'s
  dropped `HERO_RULES` exclusion, `shot_at`'s cut-boundary side, the
  constraint-before-variety gate order, refuse-vs-log-and-continue, the
  singleton refusal, and the missing-file default — was caught by the
  existing suite. That is a claim about the nine sites it probed, not about
  the module: it found no hole *among them*, and — see the Follow-up below —
  could not have found one outside them. **2335 passed / 3
  skipped**, full suite including integration, no
  golden moved (`EDL.to_dict()` gains a `"constraints": null` key, but no
  existing golden compares the whole dict against a literal). What remains
  of P3 — #3 per-episode QC and the hero-conditioned re-scan, both bigger
  slices needing their own design — is named in the Next-action head below.
  - **Follow-up (2026-08-07, same day — whole-branch review) — `shot_at`'s
    float-drift hole, outside the battery's nine sites.** `shot_at` returned
    `(max(before), t + room_after(t))` — an end derived from the CALLER's own
    `t`, not from the shot's own boundary. In IEEE-754, `t + (cut - t)` is not
    bit-identical to `cut` in general, so two episodes inside the SAME shot at
    different non-round in-points could key differently, and `no_repeat` /
    `exclude` — which group and compare on that pair — silently missed the
    repeat on roughly 6% of realistic `(start, start, cut)` triples, including
    at 30/29.97/59.94fps. None of the battery's nine mutations encodes this
    shape (its `shot_at` mutation used `c < t` in place of `c <= t` — a
    discrete boundary-classification failure, testing which shot a cut-exact
    `t` belongs to, not this float-precision one), and every pre-existing
    `shot_at`/constraints fixture used round seconds
    (1.0/6.0/10.0/22.0), where the arithmetic happens to be exact — so nothing
    short of a dedicated non-round fixture could have caught it. Fixed the
    same day: `shot_at` now returns the surrounding cut VALUES themselves,
    never a value derived from `t`; three regression tests
    (`test_footage.py::test_shot_at_is_bit_identical_for_two_times_in_the_same_shot`
    plus two constraints-layer siblings) pin the non-round reproduction at
    both layers; and the `_exclude` comment that had (wrongly) attributed the
    old code's bit-identity to "same clip" now names the real reason — the
    pair is built from the cut values, not from `t`.

- **Intake motion sensor + pool-relative scoring (cinematic-quality playbook P3
  slice S3) DONE (2026-08-06)** — plan
  `docs/plans/2026-08-06-intake-motion-scoring.md` + design
  `docs/specs/2026-08-06-intake-motion-scoring-design.md`, Tasks 0–6 (branch
  `feat/intake-motion-scoring`, commits `96cc121`..`3581e22` + this docs sync).
  **Not the `_motion_fit` re-tune S2 deferred and paid a `CACHE_VERSION` 6→7 to
  make free** — that re-tune's premise was that the *constant* needed a better
  fit; scoring a real 99-clip/1565-window DJI tuning set falsified it. Three of
  `score_window`'s four terms turned out to be near-constant (`present` = 1.0 on
  1563/1565 windows BY CONSTRUCTION — carve already splits on presence
  transitions; `_dur_fit` an exact zero on the 76% of windows carve emits at
  `WIN_MIN`; `stability` compressed 2–14× below its own `SHAKY_CLIP` divisor),
  leaving `score ≈ 0.61 + 0.25·_motion_fit` — one narrow band, `BEST_FLOOR`
  passed 99.6% of windows, and `best` carried no scoring signal at all, just the
  phash-dedup flag. Worse, `_motion` itself was wrong (design §1.2): it
  differenced the centroid of the LARGEST bbox between samples, so in a crowd
  "largest" swapping from one person to another read as movement. That
  saturated 310/1565 windows (19.8%) at the `MOTION_GAIN` ceiling — a decaying
  decile histogram (355…28) with an unexplainable spike at the clip point — and
  the saturated population was 90.3% multi-person against 57.1% for the rest.
  `carve.subject_curve` built its activity curve from the same contaminated
  primary-bbox centres, so the artifact also decided **where window boundaries
  fall**, not only how they score. This slice fixes the sensor, not the
  constant. **Phase 1:** the people timeline's row grows `boxes_by_tid` (`{tid:
  (cx,cy,w,h)}` per sample); new `carve.track_displacements(prev, cur)` takes
  the MEDIAN centre displacement across track ids present in both samples (the
  median, not the mean, so one residual ID switch inside a crowd cannot swing
  the result the way it would swing an average) and returns `0.0` on no shared
  id, the same rule presence gaps already followed; `subject_curve` and
  `intake._motion` both switch onto it, so window boundaries move (§3.3, the
  slice's largest behavioural change) and `_motion` is finally identity-
  consistent. `MOTION_GAIN` is deleted outright, not re-fit — a rank has no
  ceiling to saturate and no scale to invent — so `FootageWindow.motion` reads
  ~10× smaller than before (it is the measurement, not measurement × display
  gain). **Phase 2:** new `score_pool(clips)` (called in `intake()` between
  `Footage` assembly and `cull`, replacing `_build_window`'s old per-window
  `score_window` call) scales each factor on the scale its question deserves —
  `motion` by percentile WITHIN its own clip (falling back to the pool below
  `CLIP_POOL_MIN = 5` windows, since a smaller clip has no distribution to rank
  inside), `shake` by percentile across the whole pool (steadiness is a camera
  property, so a within-clip comparison asks nothing), `present` unchanged and
  absolute — then rank-normalises the weighted blend itself, so
  `FootageWindow.score` **is** a percentile. New `_percentile_rank` (tie-aware:
  equal inputs share the mid-rank of their group, so a structurally constant
  factor like `present` shifts every window equally and cannot reorder the
  pool). One mechanism now fixes three defects at once: a constant factor can't
  distort the order, `BEST_FLOOR` becomes a real top-half cut instead of an
  inert 99.6%-pass bar, and saturation is unrepresentable (a rank has no
  ceiling). `_describe`'s dynamic/calm word moves to Phase 2 too, reading the
  motion rank instead of a raw fraction. `W_PRESENT`/`W_MOTION`/`W_STABLE` =
  0.44/0.28/0.28 and `BEST_FLOOR` = 0.50 (value unchanged — the MEANING change
  is the fix); all first cuts calibrated on the one tuning pool, named as such
  at their definitions (the `SHAKY_CLIP`/`CLUSTER_COS` precedent). **`CACHE_VERSION`
  7→8** — Phase 1's timeline and `_motion` both change, so a cached v7
  `ClipResult` cannot supply the new measurement; **the next `footage-intake`
  run re-scans every clip in the folder, from scratch, with no partial resume
  possible against the old cache.** **The determinism re-proof
  (`test_output_is_byte_identical_across_a_cache_mix`):** the three pre-existing
  byte-identity proofs all compare an all-cold run against an all-cached run: none
  covered a MIX, and a mix is exactly where a pool-relative score can silently
  diverge — an implementation that ranked only the freshly-rescanned clips would
  pass all three existing proofs and still write different percentiles on a
  resume. The new test builds a real mix (one clip cached, one re-scanned) against
  a fixture whose motion differs BETWEEN clips (there must be something for a
  percentile to order) and asserts byte-identical `FOOTAGE.json`. **Goldens
  re-pinned, diff read, no fourth cause found:** both `tests/integration/
  test_intake.py` whole-object goldens moved on exactly the two expected axes —
  `motion` 0.625→0.062 (MOTION_GAIN deleted: the fixture's 6px/frame slide at
  SAMPLE_FPS 3 over a 30fps clip is 60px between samples, 60/960 = 0.0625, and
  the derivation is now spelled out in the test comment) and `score` 0.861→0.5
  (a single-window pool: `_percentile_rank` returns exactly `[0.5]` for n==1 —
  "neither above nor below anything" — so a singleton-clip fixture cannot pin an
  ordering; the real ordering proof lives in `tests/lib/test_intake.py`'s
  `score_pool` tests). **Honest limits (design §8, 11 items — four added by this
  docs-sync task after a review pass on the shipped design found them
  understated):** first cuts on one shoot/one camera (§8.1); `score` is not
  comparable across shoots, by design (§8.2); `present` stays dead until B-roll
  exists to discriminate against (§8.3); a v7 `FOOTAGE.json` loads silently with
  old-meaning numbers in new-meaning columns, since the change is semantic and
  `from_dict` only sees shape (§8.4); the sensor fix is verified on aggregate
  statistics, not hand-labelled ground truth (§8.5); a genuine mid-window
  ByteTrack ID switch (not just a largest-box swap) still thins the shared-id
  set, unlike route stitching which does not apply to an intake timeline (§8.6);
  nothing here proves the ranking is editorially right, only that a measurement
  artifact is gone (§8.7); the "dynamic" word in `FOOTAGE.md` is CLIP-relative,
  not pool-relative, so a completely static clip still calls roughly half its
  own windows "dynamic" (§8.8, new); `round(score, 3)` quantises the percentile
  above roughly 1000 windows in a pool — deterministic, not silently wrong, but
  silently coarser (§8.9, new); `_percentile_rank` ties on bit equality, not
  mathematical equality, so `0.28*0.75 + 0.28*0.25` need not tie with
  `0.28*1.0 + 0.28*0.0` even though both equal `0.28` (§8.10, new); and the
  slice's largest behavioural change — window-boundary movement and
  multi-window `score_pool` ranking — has NO real-bytes proof, structurally:
  `tests/conftest.py`'s `sample_clip` is 3 s with no scene cut and `WIN_MAX` is
  4.0 s, so `carve.units_for_span`'s `L <= win_max` branch makes exactly one
  window unavoidable whatever the activity curve does (§8.11, new; a
  pre-existing fixture limit, not introduced by this slice). **This docs-sync
  task (Task 6) also corrected six statements that were false or misleading in
  already-shipped files**, carried over from the Task 5 review: the design §4.3
  sentence and the plan's Self-review note both claimed `WIN_TARGET` "stays" —
  it was in fact deleted as a review finding before Task 4 began, and only
  `WIN_MIN`/`WIN_MAX` remain as carve's band; the two real-bytes goldens'
  comments explained `score`/`description` as structurally forced on a
  singleton pool but did not name that `best` is forced too (`BEST_FLOOR` ==
  0.50 == a singleton's only possible score); and a function-local `import
  shutil` (banned by `docs/coding-standards.md`) moved to
  `tests/lib/test_intake.py`'s top, which also let a second, pre-existing local
  `import shutil as _sh` two tests above it come out. **Acceptance snippet
  (design §6.2), a documented one-off, not a new production script:**

  ```bash
  .venv/bin/python - <<'PY'
  import json, statistics as st
  d = json.load(open("FOOTAGE.json"))
  ws = [w for c in d["clips"] for w in c["windows"]]
  sat = sum(1 for w in ws if w["motion"] >= 0.999)
  # baseline is 310/1565 (19.8%) at motion==1.0 exactly (design §1.2's own table);
  # 321 is a DIFFERENT number — the motion >= 0.95 histogram bin, one step down
  # from the ceiling, not this check's quantity.
  top = sorted(ws, key=lambda w: w["motion"], reverse=True)[:max(1, len(ws)//10)]
  print("1. ceiling pile-up:", sat, "windows at motion=1.0 (was 310/1565, 19.8%)")
  print("2. crowd share in the top motion decile: %.1f%% vs pool %.1f%% (was 90.3 vs 57.1)"
        % (100*sum(1 for w in top if w["people"] >= 2)/len(top),
           100*sum(1 for w in ws if w["people"] >= 2)/len(ws)))
  print("3. score quartiles (want ~0.25/0.50/0.75):",
        [round(st.quantiles([w["score"] for w in ws], n=4)[i], 3) for i in range(3)])
  print("4. best share: %.1f%% of all windows (was 77.6%%)"
        % (100*sum(1 for w in ws if w["best"])/len(ws)))
  PY
  ```

  Run this against the `FOOTAGE.json` the next real `footage-intake` scan writes
  (the `CACHE_VERSION` bump forces that scan to be a full one) — it has not been
  run against real footage yet, so the four criteria are unverified against
  reality until then; §8.5 already records that even a clean pass proves the
  signature is gone, not that the numbers are right. **2286 passed / 3 skipped**
  (full suite, before and after this docs-sync task — it changed comments,
  docstrings, and prose only, no production code path).

- **Mood presets + shot-size variety (cinematic-quality playbook P3 slice S2,
  backlog #19) DONE (2026-08-06)** — plan
  `docs/plans/2026-08-06-mood-preset-variety.md` + design
  `docs/specs/2026-08-06-mood-preset-variety-design.md`, Tasks 0–7 (branch
  `feat/mood-preset-variety`, commits `e96f035`..`16ef627` + this docs sync).
  S1 (footage contact-sheet, 2026-08-05) gave the edit-plan agent its first
  look at pixels; the 2026-08-03 real run still delivered a reel where every
  shot was the same medium-wide side-on "surfer on a wave" — no close-ups,
  no faces, none of the *"laughs and moments, personality-forward"* the
  `fun and playful` brief asked for — because variety was nobody's
  objective, mood was a music-search string nothing about the picture
  consulted, and the shot-size tag bucketed on the primary person's bbox
  area as a fraction of the **source** frame, where a surfer shot from the
  beach occupies 1–2% of a 4K frame: every window tagged `wide`, so a target
  distribution over shot sizes was unreachable by construction. This slice
  closes all three. New pure `scripts/lib/moodpreset.py` (`MoodPreset`,
  `PRESETS` — `fun`/`epic`/`moody`/`nostalgic`, hand-tuned first-cut numbers
  — `BALANCED` fallback kept deliberately OUT of the nearest-neighbour
  search so a mid-range vector cannot swallow every mood between the four
  named ones, `resolve(mood_text)` reusing `mood.py`'s existing anchor
  vocabulary, `VarietyReport`, `evaluate`) carries exactly the two fields
  its one consumer reads: `shot_mix` (a distribution over
  `footage.SHOT_TYPES`, deciding which under-use is refusable) and `asl`
  (reported, never enforced — shot length is the footage's and pacing's to
  set, not a reason to blame the editor). Four new `mood.py` anchors
  (`fun`/`playful`/`nostalgic`/`adventure`) fix a second bug found along the
  way: `"fun and playful"` matched no anchor before this slice and fell
  into the blind drive-ranking fallback, so even the *music* ranking on the
  real run had been running blind. `scripts/lib/footage.py`'s
  `shot_type(subject_w, subject_h)` — moved out of `intake.py`, thresholds
  unchanged — now has a `delivered_shot(subject_w, subject_h, res, aspect,
  crop_scale=1.0)` sibling that reclassifies in the project's **delivered**
  canvas: a 9:16 fill crop of a 3840×2160 source cuts width only, scaling
  the subject's area fraction by `3840/1215 = 3.16×`, which moves the
  `medium` boundary from 8% of the source frame to 2.5% — three times wider
  a net, and the reason a distribution can exist at all where before there
  was one bucket. `edit_plan build` (`aspect`/`preset` keyword-only,
  keyword-absent ⇒ not evaluated, never a silent pass — the SP1 door for a
  hand-authored selection with no project geometry) tallies `available`
  (every window in the footage, in delivered geometry — never filtered to
  `best`, since `best` is a threshold on a score that itself leans toward
  motion, §1.1) against `used` (what the cut actually took) and calls
  `moodpreset.evaluate`; `write_edit_plan` turns a gap into a
  `stop_and_report` (reason `variety-gap`, never `edl-invalid`) naming the
  preset, the unused size, and the top-3 candidate windows by score — unless
  `selection.json` carries a `variety_waiver` (a blank one is refused: an
  empty string is a bypass wearing the costume of a decision). The waiver
  rides into `EDL.variety.waiver`, prints in `EDL.md`'s new `## Variety`
  section, and lands inside the artifact `edl.write_edl` stamps, so the
  exception is recorded where it cannot be quietly revised later. **The
  `CACHE_VERSION` 6→7 cost, and why it was paid now:** `FootageWindow` gains
  `subject_w`/`subject_h`/`present` — the primary-subject bbox and presence
  fraction `_build_window` already computed as locals and then discarded.
  Storing them forces every cached clip to miss and the next
  `footage-intake` to re-scan the whole folder — paid once, and paid now
  rather than twice, because the `_motion_fit` re-tune this design's §1.1
  explicitly declines to do in this slice would have needed its own bump
  later; after this slice it needs none, since `present`/`motion`/`shake`/
  `dur` are all on disk and `score` becomes recomputable outside Phase 1
  forever. A `FOOTAGE.json` written before this slice has no `present` key;
  `FootageClip.from_dict` checks key *presence* (not value — `0.0` is a
  legitimate measurement) and refuses it by name with a re-scan remedy,
  rather than silently reconstructing a window that claims "no people
  anywhere". **Honest limits, one sentence (design §13):** the gate proves
  *"you used what was there,"* never *"the reel is varied"* — two close-ups
  of the same pose satisfy it completely, it cannot fire at all on footage
  whose subject never exceeds ~2.5% of the source frame, a hand-authored
  `EDL.json` through `edl_to_reel`'s SP1 front door is never evaluated, and
  the waiver is self-granted (a recorded decision, not an independent
  check). **Mutation battery (Task 7, six checks — the design's five plus a
  sixth `WANT_FLOOR`-boundary check the brief added on a Task-3 reviewer
  finding):** four turned red exactly or more broadly than predicted
  (`_available_census` filtered to `best`; `delivered_shot` replaced by the
  source-geometry tag; the blank-waiver refusal dropped; `BALANCED` entering
  the preset search). Two stayed **green** on their first predicted test —
  both real coverage gaps, both closed with a new test in the same commit:
  counting `available` by summed duration instead of by window slipped past
  `test_build_edl_counts_both_censuses_in_delivered_geometry` because its
  fixture's windows all carry `dur=1.0`, where "sum of seconds" and "count
  of windows" are numerically identical (closed by
  `test_available_census_counts_windows_not_seconds`, non-uniform
  durations); and `WANT_FLOOR`'s `>=` loosened to `>` found no test pinning
  the boundary exactly — the nearest case pins `0.10`, well below it (closed
  by `test_evaluate_fires_exactly_at_the_want_floor_boundary` +
  `test_evaluate_is_silent_just_below_the_want_floor_boundary`). Every
  mutation was reverted; none was committed; `scripts/` carries no diff
  beyond the two new regression tests. **2272 passed / 3 skipped** (whole
  suite; the three skips are the pre-existing demucs/torchreid/iTunes-network
  gaps this tree already carried, none new), no golden moved. **Deferred minors, not silently discarded** (per-task review
  findings, cosmetic — none blocks): `intake_cache.py`'s `CACHE_VERSION`
  6→7 note is a trailing comment rather than extending the running narrative
  paragraph the four prior bumps used; `edl.py`'s `from_dict` reads
  `if d.get("variety")`, so a hand-authored `"variety": {}` is swallowed as
  `None` instead of failing loud (the machine path never emits an empty
  report, so this is unreachable today); three test files place a
  `from scripts.lib import X` mid-file rather than in the top import block,
  each mirroring a pre-existing instance in the same file. **What's left of
  P3** (S3's `_motion_fit` re-tune, the hero-conditioned re-scan, #14, #3)
  is named in the Next-action head below.

- **Footage contact-sheet (cinematic-quality playbook P3 slice S1, backlog
  #12 "look, don't guess" — the selection half) DONE (2026-08-05)** — plan
  `docs/plans/2026-08-05-footage-contact-sheet.md` + design
  `docs/specs/2026-08-05-footage-contact-sheet-design.md`, Tasks 0–5 (branch
  `feat/footage-contact-sheet`, commits `6cc9e31`..`bc30b82` + this docs
  sync). Until this slice, the edit-plan agent's entire sensory input was
  text: `FOOTAGE.md`'s `shot_type` (a bbox area fraction) and a three-token
  `description`. The 2026-08-03 real run priced that out — slow-mo placement
  took ≥6 corrections, hero identity was described rather than observed
  (*"«Шаг назад» я выдумал"*), and the delivered reel stayed one shot size
  end to end — so this slice gives the agent its first look at actual
  pixels. New pure `scripts/lib/sheet.py` (`Cell`/`tile`/`paginate` — PIL +
  numpy only, no ffmpeg, no `footage` import, fully testable on synthetic
  arrays) contain-fits every thumbnail into a fixed `CELL_W×CELL_H` box so
  mixed source aspects tile without distortion or a ragged grid; thin driver
  `scripts/contact_sheet.py` adds two modes sharing that tiler. `build`
  renders ONE frame per `FootageWindow` at its **midpoint**, in **timeline**
  order — clip then window index, never score order, because the scorer
  already leans toward action (§1.1 below) and sorting by it would just
  repeat the bias the sheet exists to correct — over **every** window by
  default (`--best-only` narrows; `best` is marked twice — the label appends
  a ★ glyph, and separately `marked=True` draws a plain gold rectangle
  outline with no star in it — named in `SHEETS.md` as a fact to weigh, not
  a ranking to follow), writing
  `sheets/sheet_NN.png` + `SHEETS.md`, the artifact the router keys on and
  the agent's entry point. `strip` renders MANY frames inside **one** window
  (explicit `--start`/`--dur`, or `--footage`+`--window` sugar), each cell
  labelled with its **absolute** timestamp so a chosen frame converts
  straight into a `selection.json` `start_offset` — the answer to "where
  exactly is the peak?" that one midpoint frame cannot give. Both modes grab
  frames through the existing `assembly.frames_rgb` batched-select decoder
  (one decode per clip for the ordinary case, `ceil(n/60)` beyond 60
  windows), never `-ss` (§12). **A separate pass after intake, not inside
  it:** riding intake's own proxy decode would cost `CACHE_VERSION` 6→7 — a
  full re-scan of every clip — for thumbnails a `FOOTAGE.json` already on
  disk can produce in one additional pass; it also keeps the boundary clean
  (intake measures, the sheet presents). `montage.V1_STAGES` gains
  `Stage("contact-sheet", "SHEETS.md", "required", ..., None)` between
  `footage-intake` and `reel-brief` — **required, not optional**, the #15
  lesson applied again (a stage that costs nothing to skip is not a stage):
  a run can no longer reach `edit-plan` without a `SHEETS.md` on disk — the
  gate is the artifact's PRESENCE, not a guarantee it holds a frame. A clip
  that will not decode is skipped and named under a `SHEETS.md` "Not
  sheeted" section (`intake_report.json`'s quarantine precedent, its error
  trimmed to the one line that names what went wrong) rather than aborting
  every other clip's sheet; an empty or `--best-only`-emptied window set
  writes an honest empty `SHEETS.md` instead of wedging `next_action` on a
  missing artifact — but every candidate window failing to decode (a wrong
  `--footage-root`, a moved footage folder, a broken ffmpeg install) is a
  different case from one bad file, and now raises instead of silently
  writing a thin `SHEETS.md` that looked like a normal success. Both the
  floor and the `--footage-root` it depends on (`FootageClip.source` is a
  bare filename — intake stores only `Path(path).name` — resolved against
  the root the same way `edl_to_reel`/`draft` already do) are a
  whole-branch-review fixup landed on `feat/footage-contact-sheet` after
  Tasks 0–5, not part of the original five tasks.
  Real-ffmpeg proof (`tests/integration/test_contact_sheet.py`, 7 tests)
  covers sheet count/dimensions, label and clip-then-index ordering against
  the FOOTAGE order (not re-derived), `--best-only` filtering, the
  not-sheeted skip path, the every-clip-failed floor against a real missing
  root, and `strip`'s `--window` sugar resolving to the same range as an
  explicit `--start`/`--dur`. Two skills now read the
  output: `using-montage` runs the build directly after footage-intake and
  reads every sheet before moving on, offering them at CP1 alongside the
  brief; `edit-plan`'s Recon step reads `SHEETS.md` and every sheet before
  selection (with the `strip` incantation for a timing/identity question),
  and its selection step is told the ranking is not the answer — the same
  motion-peaks-at-0.35/zero-at-static finding recorded in the design's §1.1,
  so S3 (backlog #19) does not have to rediscover it. **Honest limit
  (design §9), stated in the stage's own code comment and both skills, not
  strengthened by this slice:** the conveyor can force the sheet to exist —
  gating its PRESENCE, not a guarantee it holds a frame — and it cannot prove
  the agent looked at it; this closes backlog #12 for the **selection** half
  only, and the per-episode QC agent that judges rendered frames (#3) is the
  remaining half. **2206 passed / 3 skipped** (no golden moved; this
  docs-sync task changed no code). **Whole-branch-review fixup, same
  branch:** the `--footage-root` join above, the every-candidate-failed
  floor, the trimmed skip reasons, the `_markdown`/build-status/backlog
  wording corrections, and the re-pointed integration fixture (bare filename
  + root, not an absolute path standing in for both) all landed together in
  one follow-up commit after Tasks 0–5, closing the seam none of the six
  per-task reviews owned. **2216 passed / 3 skipped**, no golden moved.

- **Attested run (provenance chain + gates out of the worker's reach) DONE
  (2026-08-04)** — plan `docs/plans/2026-08-04-attested-run.md` + design
  `docs/specs/2026-08-04-attested-run-design.md`, Tasks 0–7 (branch
  `feat/attested-run`, commits `d40df21`..`17ccfb9` + this docs sync).
  Promoted from fixes-backlog #8/#11/#13/#15/#20 (+ riders #6/#16): the
  2026-08-03 real run shipped a reel `check_reel` had rejected, hand-assembled
  outside `deliver`, from an `EDL.json` hand-edited outside `edit_plan`, on an
  engine that changed ~40 times mid-run, with `reel-review` never invoked —
  and nothing any artifact carried could be checked against anything else to
  catch any of it. New `scripts/lib/provenance.py` is the ONLY module that
  shells to git or hashes a file: `engine_stamp()` (short HEAD sha + a dirty
  bit measured over `scripts`/`skills`/`bin` **only** — a doc edit or a
  scratch file is not an engine change — `{"sha": "", "dirty": None}`,
  recorded as unknown rather than guessed, when git cannot answer),
  `digest_file` (streaming sha256), `digest_obj` (sha256 of an object's
  canonical JSON with its own `provenance` key excluded, so a block can be
  recomputed over the object that carries it), `stamp`/`check` (state ∈
  `unstamped`/`intact`/`tampered`), `spec_overrides` (a **diff** of a spec
  instance against a default-constructed one of the same class, field by
  field — not a registry, so a threshold added to `ReelCheckSpec` later is
  covered the day it lands), `attest_path`, `class Attestation`, and
  `verify_delivery`. Three artifacts gain a `provenance` field, all
  defaulting empty so every existing artifact and fixture still loads:
  `project.json` (stamped by `project_init` at run start — the reference
  `edl_to_reel` later compares against), `EDL.json` (stamped by the ONE new
  writer chokepoint `edl.write_edl`, which both `edit_plan.write_edit_plan`
  and `match_grade`'s in-place rewrite now route through — two writers
  stamping independently was the shape that drifts), and `ReelReport`, which
  gains `master_digest` (set unconditionally by `check_reel.run` from the
  master it just measured). **The load-bearing distinction (design §5): a
  MISSING provenance block is legal, a PRESENT-but-mismatched one is
  refused.** `EDL.from_json` — the one read chokepoint all four EDL
  consumers (`edl_to_reel`/`draft`/`pacing`/`match_grade`) share — loads an
  unstamped (hand-authored) EDL exactly as before, since that is
  `edl_to_reel`'s documented SP1 front door, but raises `ValueError` on a
  tampered one (a digest that no longer matches its contents) naming the
  remedy: edit `selection.json` and re-run `edit_plan build`, because
  raw-JSON surgery bypasses the manifest preflight that catches a window past
  EOF, a scene-cut straddle, or an unresolved cast pin. `deliver` is the
  deliberate exception to the absence rule: it refuses a report whose
  `master_digest` is empty (meaning it did not come from `check_reel`, the
  report's only producer) or does not match the sha256 of the master file it
  is about to encode (a hand-assembled or re-made master) — both raise
  `RuntimeError` naming the fix (run `check_reel` on this master and deliver
  with the report it writes). On success `deliver` now writes
  `out/REEL_v{n}.attest.json` beside the encode: both engine stamps
  (`engine_at_start` from the run's `project.json`, `engine_at_deliver`
  measured live), the master/report/**reel** digests (the reel digest binds
  the attestation to the shipped file itself, so a swap after delivery is
  detectable), the EDL's digest+state, and the `spec_overrides` list of every
  loosened `ReelCheckSpec` threshold (e.g. `--color-delta-max`) — a
  legitimate gate loosening stays available but can no longer pass silently.
  `edl_to_reel` now raises `ValueError` the moment it starts if
  `engine_stamp()` disagrees with the sha/dirty bit `project.json` recorded
  at run start (naming both revisions) — a run must not straddle an engine
  change, because the stages already finished were produced by different
  code; an unknown stamp on either side (git absent, or a run started before
  this slice existed) proves nothing and never stops the run, and a *static*
  dirty tree at run start is not itself a stop, only a recorded fact.
  `edl_to_reel` also assembles the run's `ReelManifest.provenance` (the EDL's
  digest/state, the start engine stamp, the override diff) for `deliver` to
  merge into the attestation, and gained `--changelog` — closing #16, whose
  root cause was `edl_to_reel` passing `VERSIONS.md`'s own path as the
  version note text instead of a reason; 12 of 13 entries in the 2026-08-03
  run's log were unreadable because of it. `montage.py`'s `reel-review` stage
  flips from `kind="optional"` to `"required"` (#15) — a gate that costs
  nothing to skip is not a gate — so a run is finished when
  `next_action()["next"]` is `None`, not merely when `delivered` is true;
  `next_action` also gains a `deliveries` list, one entry per `out/REEL_v*`
  reporting its attestation's presence/`overall` from the sidecar alone
  (cheap — the router calls `status` constantly; a hand-concatenated reel
  with no sidecar reports `unattested`), and a new `montage verify --run-dir`
  subcommand re-hashes every delivered file against its attestation — run
  once at CP3, where the cost is irrelevant and a swapped file would
  otherwise pass for attested. Three real-ffmpeg integration tests
  (`tests/integration/test_attested_run.py`) prove the chain against real
  pixels rather than only fixtures: assemble → `check_reel` → `deliver`
  produces an attestation `verify_delivery` confirms as `attested`; a master
  re-made after the check is refused at `deliver` (#13, `"different file"`);
  and a reel byte-appended after delivery is caught by `montage verify` as
  `digest-mismatch`. **Riders landed alongside:** `using-montage`'s CP2 step
  now asks explicitly *"titles? effects (slow-mo / speed ramp, transitions,
  SFX)?"* and names what is skipped on "no" (#6); `using-montage`,
  `process-episode`, and `edit-plan` each gained an explicit boundary line
  that a worker may not disable, lower, or downgrade any quality gate — a
  blocking gate routes back to its stage, never loosened to pass — and
  `edit-plan`'s brief additionally says never to hand-edit `EDL.json` now
  that it is stamped. **wip-branch triage, corrected in this docs-sync task:**
  the design's §9 originally claimed both parked branches were superseded and
  deleted; the truth verified against the actual repo state is narrower —
  `wip/montage-run-hardening` (`4841dd3`) WAS fully ported across three
  earlier slices (track-stitch, path-quality, titles-animations) and has been
  deleted, but `wip/montage-run-patches` (`fbcd052`) has **not** been deleted
  and must not be: it still carries the only copy of `scripts/lib/ramp.py`
  (212 lines, speed-ramp + Ken-Burns zoom), which does not exist on `main`,
  and fixes-backlog #7/#18 still track that work as open — the live tree
  itself is clean. **Honest limits (design §11, not solved by this slice):**
  an agent with a shell still bypasses all of it — it can run `ffmpeg` by
  hand, write its own JSON, and hand the user a file, and nothing short of
  taking the shell away prevents that. What this slice achieves is narrower:
  **no delivered reel can claim a gate it did not pass, and every bypass now
  leaves a machine-detectable trace** — a hand-assembled reel ships with no
  `attest.json` and `montage status`/CP3 report it `unattested`; a
  gate-weakening knob outside `ReelCheckSpec`/`CheckSpec` would not appear in
  `spec_overrides` (no machine predicate for "this flag weakens a gate"
  exists); a tampered EDL that is also re-stamped by hand defeats the check
  (the stamp stops casual raw-JSON surgery, not a deliberate forgery); engine
  drift **within** a stage is not caught until the next run's comparison; and
  `dirty` is a boolean over three directories that does not say *what*
  changed. **2152 passed / 3 skipped** (full suite, re-run clean at the end
  of this docs-sync task; no golden moved — this task changed no code).

- **Hero re-ID embedding DONE (2026-08-04)** — plan
  `docs/plans/2026-08-04-hero-reid.md` + design
  `docs/specs/2026-08-04-hero-reid-design.md`, Tasks 0–6 (branch `feat/hero-reid`,
  commits `91202aa`..`6aef567` + this docs sync). Promoted from fixes-backlog #1:
  the appearance descriptor (`lib/appearance.build_descriptor`) was a 24-dim
  L1-normalized RGB colour histogram (8 bins × 3 channels) over the seg-mask
  pixels — it encoded clothing colour, not identity, and on the 2026-08-03 surf
  run 4062 tracks collapsed to 892 "identities" with true/false-match distances
  overlapping (not separable by any threshold). This slice replaces it
  end-to-end with a 512-dim OSNet (`osnet_x1_0`, Market-1501) person-re-ID
  embedding, cosine-compared. New `scripts/lib/reid.py` is the ONLY importer of
  `torchreid` (mirrors `lib/vidstab`'s isolation of libvidstab) —
  `available`/`require`/`ensure_model`/`embed`, lazy torch/torchreid imports,
  weights warmed once before a pool (closes the concurrent-download landmine
  already closed for YOLO). `appearance.descriptor_dist` becomes true cosine
  distance (range [0,2]); `appearance.crop_from_result` replaces `crop_and_mask`
  — the OSNet crop is the raw bbox, UNMASKED (a silhouette is out-of-distribution
  for a bbox-trained reID net) — `build_descriptor`/`seg_mask`/`crop_and_mask`/
  `upsample_mask` all deleted. `footage.DESCRIPTOR_LEN` 24→512 (`HIST_BINS`
  gone), `CastMember` validates the new length with a re-run-intake remedy.
  `CastEntry.presence` (on-screen seconds) rides the cache; `intake_cache.clip_key`
  gains a `reid_model` term so a scan run without reID never masquerades as one
  run with it; `CACHE_VERSION` 5→6. `intake.surface_crops` is rewritten from
  greedy top-n dedup to agglomerative clustering (`scipy.cluster.hierarchy`,
  average linkage, cosine, cut at `CLUSTER_COS`) — one candidate per real
  identity (centroid descriptor, medoid crop), ranked by summed presence,
  adaptive-capped at `MAX_CAST` with a logged (never silent) drop. The reID gate
  (design §6) resolves backlog #1's three-way tension: `preflight`'s `reid`
  Check is advisory (never blocks a run); `intake()` warns-and-continues when
  torchreid is absent (windows/scoring/phashes still produced, cast embed
  skipped, `cast_candidates.json` empty); a cast-identity hero pin fails loud —
  `process_episode` checks `reid.available()` the moment a cast pin resolves and
  the tracker itself is present, returning an explicit `stop_and_report`
  (finding reason `reid-unavailable`, naming torchreid + the `bash setup.sh`
  remedy) BEFORE the ladder runs, rather than let an empty route misreport
  `no-track` (optical flow is correctly skipped regardless — a pinned hero never
  falls to flow, design 2026-07-21 §1.1). `setup.sh` installs `torchreid` at
  baseline, warn-and-continue, kept OUT of `requirements.txt` (the demucs
  pattern). A weights-gated real-OSNet integration test (skipped when torchreid
  is absent, like vidstab/demucs) embeds two synthetic crops and asserts cosine
  separates them past `CAST_MATCH`, and that the same crop embeds ≈identically
  twice — the only place the BGR→RGB colour-order landmine (design §10) can be
  corroborated. **Honest limits (§9, not yet resolved):**
  `CAST_MATCH`(0.35)/`CLUSTER_COS`(0.30)/`MAX_CAST`(15) are first-cut thresholds
  with no labelled data — the repo's honest-threshold pattern; they must be
  calibrated against the real cache after the FIRST re-scan with reID installed,
  the same way `CAST_DEDUP` was left uncalibrated in the original cast→hero-pin
  slice. Single crop per track for v1 (multi-crop averaging deferred). **2087
  passed / 3 skipped** (demucs, iTunes-network, and the weights-gated real-OSNet
  test — torchreid stays absent/mocked in this suite by design; two tests added
  by this docs-sync task: a non-skipped negative-stride-crop contiguity proof
  for `reid.embed`'s `np.ascontiguousarray` fix, and a
  `verify_runtime._probe_reid` unit test).

- **Setup installs everything — no opt-in flags DONE (2026-08-04)** — backlog #4,
  design `docs/specs/2026-08-04-setup-install-all-design.md` (branch
  `feat/setup-install-all`). The real run had no `demucs`, so its phrase-aware music
  in/out-point silently fell back to the coarse librosa proxy ("разбиение по фразам"
  effectively off). `setup.sh` now installs the **whole** runtime: `demucs` is a
  baseline install (was `--with-demucs`) with **warn-and-continue** — kept OUT of
  `requirements.txt` so a platform with no torch wheel degrades to the proxy instead
  of aborting the venv; `--with-sourcing` is gone (yt-dlp already ships in
  `requirements.txt`; the `any`-lane legal gate is use-time, untouched) and its
  Jamendo `client_id` prompt became a **non-blocking notice** so a non-interactive
  run never stalls on `read`. `preflight.py`'s `demucs` row stays advisory (a warn-
  and-continue absence is valid) with its remedy moved to plain `bash setup.sh`;
  `vocals.py`'s ValueError remedy likewise. `bash -n` clean (the installer itself is
  not run here — no autonomous system mutation); full suite green. Docs swept
  (README, CLAUDE registry left as history, dev-workflow, verify-runtime row, both
  SKILLs, this file).
- **Intake flush-per-clip + `--jobs` default 2 DONE (2026-08-02)** — surfaced by
  the first real full-folder scan (branch `feat/intake-flush-per-clip`). `intake()`
  submitted all clips then stored nothing until the whole pool drained, so every
  clip's `crop_rgb` arrays piled in RAM at once (swaps a big 4K folder) and no
  artifact appeared until the end ("5 min, not one clip"). Now `as_completed` +
  `store()` **inside** the pool, and `futs.pop(fut)` drops each completed future so
  its cached `.result()` stops pinning the worker's crop arrays — live crops bounded
  to ~`jobs` clips, per-clip progress (`✓`), per-clip crash-resume. `DEFAULT_JOBS`
  3→2 (a laptop thermally throttles at 3 full-clip passes; `--jobs` raises it).
  Clean per-clip cost measured ~155s (YOLO 72s floor + cast 59s + proxy 11 +
  vidstab 9); no thread regression (worker≈main). `edl_to_reel` jobs untouched.
- **Intake frame-grab batch (one decode per chunk for cast crops + window
  phashes) DONE (2026-08-02)** — plan
  `docs/plans/2026-08-02-intake-frame-grab-batch.md` + design
  `docs/specs/2026-08-02-intake-frame-grab-batch-design.md`, Tasks 0–4 (branch
  `feat/intake-frame-grab-batch`, commits `23a87c7`..`c229ca7` + this docs
  sync). The analysis-proxy slice (2026-08-01) killed the `vidstabdetect`
  wall; profiling the finished pipeline on real 4K footage then found the
  **frame GRABS**, not the transcode, dominate — one of them pathologically:
  `_cast_from_original` issued one output-seek 4K decode per track (cost
  **linear in the timestamp**) and blew past a 10-minute timeout; phash added
  another 15s on top. New `assembly.frames_rgb(src, times, fps)` selects every
  requested frame via one `select`-filter decode per **chunk of ≤60 frame
  numbers** (`_SELECT_CHUNK`) — a single `select` expression above ~100 terms
  **ENOMEMs a 4K decode** (measured 81 ok / 106 fail), so chunking at 60 keeps
  margin; the common small-N case (every per-window phash batch, most
  per-clip cast batches) still costs exactly one decode, while N>60 unique
  frames costs `ceil(N/60)` decodes — bounded, never one-per-frame, but not a
  flat O(1) either. Both `_cast_from_original` (cast crops from the ORIGINAL)
  and intake's per-window phash (from the proxy) now route through it;
  `frame_rgb` becomes a thin `frames_rgb(src, [t], fps)[0]` wrapper,
  `_phash_at` is deleted, and `check_reel`/`storyboard` stay untouched — reels
  are short enough that output-seek's frame-accuracy at cut boundaries is
  still the right tradeoff (design §6). Batch uses `select`, never `-ss`, so
  the §12 seek landmine does not apply (the repo's own lint already exempts a
  `-frames:v` still grab). Batch selects frame `round(t·fps)` vs
  output-seek's first-frame-at-`pts≥t` — these differ by ≤1 frame, so
  `CACHE_VERSION` 4 → 5 (every existing `.intake_cache` entry misses and
  recomputes) and the real-ffmpeg intake golden is re-pinned to the
  batch-measured values (mocked unit goldens monkeypatch the grab, so they do
  not move). **Measured before/after** (real DJI 4K/60 HEVC clip, 3840×2160,
  35.5 s, 123 tracks, `_process_clip`, `jobs=1`, M4 Pro): phash **15.3 s →
  1.14 s**; `_cast_from_original` **>480 s (hung, unbounded) → 57.4 s** (123
  tracks chunk into `ceil(123/60) = 3` decodes); per-clip total **>600 s
  (timed out) → 149.8 s**, now **YOLO-bound** (`_people_timeline` ~70.7 s of
  that — the compute floor, untouched by this slice). **A load-bearing bug
  surfaced by this exact measurement mid-slice:** the first cut's unchunked
  `select` (every unique frame number in one expression) ENOMEMed on the real
  123-track clip — unit tests never caught it, since their clips are tiny;
  fixed by the chunking above (commit `c229ca7`) before this docs sync
  landed. **2078 passed / 2 skipped**, no golden moved beyond the already
  re-pinned intake values. **Deferred (NOT built):** the YOLO floor
  (`_people_timeline`, ~71 s) and `make_proxy` VideoToolbox transcode —
  both named, neither touched, this slice is the frame-grab tail only.

- **Cast-descriptor mask symmetry (analysis-proxy follow-up) DONE
  (2026-08-01)** — cast-descriptor mask symmetry restored: intake masks again
  via the proxy seg mask upsampled onto the original crop, keeping intake and
  delivery descriptors on the same footing (design §5a). `CACHE_VERSION` 3 → 4.

- **Intake analysis proxy (all CV analysis on one decode-once proxy) DONE
  (2026-08-01)** — plan `docs/plans/2026-08-01-intake-analysis-proxy.md` +
  design `docs/specs/2026-08-01-intake-analysis-proxy-design.md`, Tasks 0–7
  (branch `feat/intake-analysis-proxy`, commits `3d87ff5`..`688039e` + this
  docs sync). **2066 passed / 2 skipped.** Intake decoded every clip's
  ORIGINAL three times — scene-detect, YOLO+ByteTrack, `vidstabdetect` — and
  one of those, `vidstabdetect` at `shakiness=8`, ran at FULL resolution: on
  real 4K/60 drone footage a **measured ~0.0089× realtime — ≈ 67 min for a
  35 s clip** (the old `lib/vidstab.py` `mestimate=epzs` estimate of 2.2–4.4×
  was wrong by ~25×, because `shakiness=8`'s wide block search scales with
  pixel count). This slice routes ALL of intake's analysis (scene-detect,
  YOLO+ByteTrack, `vidstabdetect`, per-window phash) through **one decode-once
  960-long-side proxy** per clip — the three 4K decodes collapse to one, and
  the vidstab wall drops to **~13 s (~300×)**. New `assembly.make_proxy`
  builds the proxy once (long side 960, native fps, no audio, CRF ~18; a clip
  already ≤960 long side is analysed in place — no needless re-encode, no
  upscale) and `assembly.frame_rgb` grabs a single ORIGINAL frame.
  **Analysis-only — the load-bearing invariant:** the proxy is never a
  delivered pixel. Cast crops re-extract from the ORIGINAL frame
  (`appearance.crop_bbox` scales the proxy bbox up by original/proxy;
  `build_descriptor` runs on the original crop, so `cast.json` descriptors
  stay on the same footing as the delivery-time tracker's), and
  extract/reframe/stabilize-apply/deliver are untouched. `FootageClip.res`
  still records the ORIGINAL geometry; intake's stored numbers are already
  **scale-normalized fractions** (`_motion`, `mean_shake`, `shot_type` all
  divide by frame width), so moving to the proxy only changes the divisor
  width fed to the measurement helpers — no coordinate ever maps back to the
  original (`edit_plan`→`process_episode` re-tracks the extracted segment from
  scratch, so intake's proxy-space geometry never leaves intake).
  **Equivalence, measured** on a real 4K clip: the `mean_shake` fraction
  survives downscaling exactly where a decision is made — near the 0.02
  `SHAKY_CLIP` gate (synthetic shake ~0.016) the full-vs-960 ratio is
  **1.008**, per-frame **r 0.985**; only BELOW the integer-pixel quantization
  floor (a near-still ~0.002 clip, r≈0.07) does it collapse, and there the
  footage is `calm` at either scale, so no window's shaky/calm verdict flips —
  the honest limit, recorded not hidden. `_people_timeline` now returns
  best-crop **refs** `(conf, t, bbox)` per track (the pixel crop moved to the
  original-frame re-extraction). `CACHE_VERSION` 2 → 3 (the analysis basis
  changed — every existing `.intake_cache` entry must miss and recompute) and
  `intake_cache.clip_key` gains `proxy_long_side`, so a scale change
  invalidates the cache the same way `sample_fps`/`model` do. The stale
  `lib/vidstab.py` cost comment is corrected to the measured reality + the
  proxy note; `stabilize()`'s detect still runs on the ORIGINAL short
  extracted segment (it stabilizes delivered pixels), and §4's scale-invariance
  above the floor is exactly the property the shared `shakiness=8` recipe
  exists to protect. Real-ffmpeg equivalence proof
  (`tests/integration/test_intake_proxy.py`) runs proxy intake on a real
  fixture and asserts the emitted cast crops carry ORIGINAL resolution; the
  existing intake golden was re-pinned to the proxy-measured values (the
  proxy-basis change, not a regression). **Deferred (NOT built):** a proxy for
  delivery-time track/reframe (they already run on short *original* extracted
  segments — no wall there), any **fps** reduction of the proxy (rejected —
  breaks `vidstabdetect`'s inter-frame motion and ByteTrack continuity), and a
  user-tunable proxy scale beyond the fixed 960 (YAGNI).

- **Verify-runtime (startup runtime preflight) DONE (2026-08-01)** — plan
  `docs/plans/2026-08-01-verify-runtime.md` + design
  `docs/specs/2026-08-01-verify-runtime-design.md` (branch `feat/verify-runtime`,
  commits `6a57003`..`884d502` + this docs sync). **2052 passed / 2 skipped.**
  Before this slice a missing ffmpeg filter surfaced only when the stage that
  needed it ran — for `drawtext` that was `deliver`, minutes into a reel. Now
  one startup check asserts the `setup.sh` **baseline contract** — required:
  `deps` (the `requirements.txt` runtime set + `cv2`), `ffmpeg_bin`, `drawtext`,
  `vidstab` (both `vidstabdetect`/`vidstabtransform`), `font`, `weights`
  (YOLO); advisory: `demucs` — and prints each gap's exact remedy (almost
  always `bash setup.sh`) instead of failing loud mid-run. Mirrors the repo's
  pure-core/thin-driver split: `scripts/lib/preflight.py` is pure (no heavy
  imports, no subprocess) — `CHECKS` registry + `CheckOutcome`/`RuntimeReport`
  (named to dodge a collision with `models.py`'s own `CheckResult`/`Report`
  family) + `evaluate(raw)`, raising if a probe's keys ever drift from the
  registry's. `scripts/verify_runtime.py` is the thin impure driver — one
  probe per check reusing the already-tested helpers (`ffbin.has_filter`,
  `fonts.resolve_font`, `models.MODELS[0]`), kept **light-import** on purpose
  (stdlib + `ffbin`/`fonts`/`preflight`/`models` only, numpy/cv2-free) so a
  broken heavy dep is *reported* by `_probe_deps` rather than crashing the
  checker's own import — plus `run()`/`main()` (`--json`; exit 0 iff every
  **required** check passes, an advisory-only miss never flips the code).
  **`run()` is defensive per probe:** each call is wrapped so a probe that
  *raises* (not merely returns `False`) becomes that ONE check's failed
  outcome (`detail` = `"probe raised: {e}"`) rather than taking every other
  check down with it — the checker always returns a `RuntimeReport`, never a
  traceback. **Read-only by design** — it prints remedies, never runs
  `setup.sh` or any installer. **Honest bootstrap boundary:** it runs *inside*
  the venv (via `bin/vg`), so it cannot report a missing venv or a missing
  recorded root itself — those stay the pre-venv layer's job (the skill
  preamble's root-record read, `bin/vg`'s own gate); the full picture spans
  `skill preamble (root) → bin/vg (venv) → verify_runtime (deps/ffmpeg/
  filters/font/weights/opt)`, no single process owns it end to end. New
  `skills/verify-runtime/SKILL.md` — an on-demand check, runnable any time.
  `using-montage`'s step 0 turns from a one-time "ensure the env" install
  prompt into an explicit **gate**: it runs `scripts.verify_runtime` before
  project-init and stops on any required failure (naming the remedy);
  advisory gaps (e.g. `demucs`) are named and never block. Not a conveyor
  stage — no run artifact, not in `V1_STAGES` (see `docs/pipeline-map.md`).

- **Match-grade conductor (montage design §10, the last colour-as-a-stage
  deferral) DONE (2026-07-30)** — plan
  `docs/plans/2026-07-30-matchgrade-conductor.md` + design
  `docs/specs/2026-07-30-matchgrade-conductor-design.md`, Tasks 0–7.
  Colour-as-a-stage (2026-07-27) landed the per-episode tone **actuator**
  (`color.tone_arg`, the `curves` fragment that maps one source profile onto a
  common one) and the authoring aid (`color_measure.measure_profile`), but
  left the pairs entirely hand-authored; this slice lands the **conductor** on
  top — a standalone post-EDL stage that measures every episode's source at
  its window MIDPOINT, computes ONE common reel tone target (the per-anchor
  **median** across every measured profile, gap-repaired to
  `color.TONE_MIN_GAP` — never widened past 0–255; a reel whose median carries
  no usable range is REFUSED, not silently flattened), and auto-authors
  `tone_src`/`tone_dst` into the episodes that deviate past `--eps` (default 4
  luma units), so a reel cut from mixed cameras/lighting reads as one grade.
  New pure `scripts/lib/matchgrade.py` (`common_target`/`_repair_gaps` +
  `valid_src`/`needs_tone` + `ToneDecision`/`plan` — no ffmpeg, no numpy) —
  `plan`'s guard order is the contract: a **hand-authored pair is respected
  first** (unless `--force`), then a **flat/low-contrast source is skipped**
  (`flat-source` — its contrast cannot be invented, though it still counts
  toward the median: every episode votes, not every episode receives), then a
  **within-eps episode is left untouched** (byte-identical — reframe's fast
  path is never spent on an imperceptible curve), else it authors its own
  profile → the common target. Thin driver `scripts/match_grade.py` —
  `conduct(edl, footage_root, eps, force)` reuses `color_measure.measure_profile`
  (one pass; the returned `ToneDecision`s carry their measured profile so the
  report needs no second measure), applies decisions via `dataclasses.replace`
  (clearing a stale pair on a `--force` re-conduct — match-grade cannot tell
  its own prior authorship from a human's, so a plain re-run without `--force`
  is a safe no-op, `hand-authored` on every episode); `write_match` rewrites
  `EDL.json` **IN PLACE** (git-tracked, recoverable) plus a sibling `MATCH.md`
  (target triple · one row per episode: measured profile · max Δ ·
  action/reason); CLI `match_grade build --edl EDL.json --footage-root DIR
  [--eps 4.0] [--force]`. New optional `montage.py` stage `match-grade`
  (artifact `MATCH.md`, checkpoint `None`, reviewed at CP3 like pacing)
  inserted between `pacing` and `assemble-draft` — `next_action` never blocks
  on it, matching every other optional stage. **Opt-in by design**: like
  `white_balance`/`dip`/the SFX whoosh, the conductor changes the look, so it
  never sits on the autonomous path — a human runs it only when episodes
  actually come from mixed cameras/light (a single-camera reel would see every
  episode land `within-eps` and receive no pair). Real-ffmpeg convergence
  proof (`tests/integration/test_matchgrade.py`): two clips of deliberately
  different exposure both get authored a tone pair, and rendering each through
  the real `color.tone_arg` curve the conductor picked measurably shrinks the
  p50 spread between them versus their un-graded source — the reel actually
  converges, not just the decision table. **Honest limits, recorded not
  hidden:** measures the WHOLE source frame at the window midpoint (the stage
  runs before tracking, so there is no crop yet) — the same boundary
  `measure_profile` already shipped with; one frame, not a temporal average;
  tone (luma) only — it cannot fix a cross-episode colour cast, which stays a
  hand/agent job. New `skills/match-grade/SKILL.md` + `using-montage` wiring
  (conveyor order + a new numbered step + a Boundaries mention) name the
  ordering landmine explicitly: run match-grade AFTER pacing, never before —
  pacing's apply pass regenerates `EDL.json` from `selection.json` and would
  wipe any tone the conductor had authored, the same "settle the cut first"
  rule pacing itself carries. **2027 passed / 2 skipped** (33 new: 22
  pure-core + 8 driver unit tests, 1 router stage-list test, 2 real-ffmpeg
  integration tests), no golden moved. **Closes the last item colour-as-a-stage's
  design left deferred** — the §10 mood LUT stays the one remaining deferred
  colour item, and it is a different problem (imposing an external look, not
  pulling episodes toward each other).

- **Titles animations (§5.16 fade/reveal/colour + the platform safe-zone fix)
  DONE (2026-07-29)** — plan `docs/plans/2026-07-29-titles-animations.md` +
  design `docs/specs/2026-07-29-titles-animations-design.md`, Tasks 0–6. Port
  of the parked `4841dd3` `lib/titles.py` hunk ("word reveal / stair / fade"),
  written live on the same 99-clip montage run and never designed, through the
  design→plan→TDD-review cycle it skipped. `Title` gains six animation fields
  — `fade` (alpha ramp in+out), `reveal` (`"none"`/`"word"`/`"stair"`),
  `reveal_step`, `color`, `scale`, `line_spacing` — each defaulting to the
  historical behaviour, with validate-and-raise refusals: `2*fade > dur` (the
  title would never reach full opacity) and a reveal whose last step can't
  arrive, hold, and still leave inside the window both **refuse, never
  clamp** (the invisible-creative-change class). A new `_measure`/`_layers`
  pair (PIL font metrics, stub-injected for the unit suite) bakes each reveal
  step's x at its FINAL position — the measured prefix width as a fraction of
  `h` — so a word never re-centres on its own entrance the way a naive
  per-word `(w-tw)/2` would; `stair` reuses that same x and additionally drops
  a line per step via the ink-box-top-corrected baseline math.
  `build_filterchain` gained the per-layer loop plus a `fade=0` no-alpha fast
  path — the anti-regression pin that keeps a pre-existing TITLES.json
  rendering unchanged. Coupled bug fix landed in the same hot `y=` line:
  `y_exprs(platform)` replaces the frozen `_Y_EXPR` module constant, so a
  bottom title now lays out against the exact `safe_zone_for(platform)` table
  `check_reel` already judges the subject against (Reels 16%, TikTok 18%, vs
  the generic table's 12%) — before this fix a bottom title on those
  platforms rendered under the app's own caption/button chrome, invisibly.
  `deliver` threads `platform` (+ a `--platform` CLI flag) into
  `build_filterchain`; `build_reel` wires `platform=rm.platform` — one line.
  **Pixel-identical defaults**: an unauthored `Title` (`fade=0`,
  `reveal="none"`, `color="white"`, `scale=1.0`, `line_spacing=1.15`) at an
  empty platform renders the same pixels as before this slice — only two
  filterchain *spellings* change (`fontsize=h/18` → `h*0.055556`, and the
  `_Y_EXPR` constant → the `y_exprs()` function), both re-pinned by unit
  assertions; no integration golden moved. 8-guard mutation battery (the
  `fade=0` fast path, a reveal word's final-x placement, both refuse-not-clamp
  boundaries, the platform-vs-generic safe-zone read, the `*h`
  resolution-independence bake, and the `deliver`/`build_reel` platform
  threading) — each neutralized line flipped its named test red, confirmed
  clean restored. Full suite **1994 passed / 2 skipped**, no golden moved.
  **3rd and final parked montage-run bucket landed** (after track-stitch
  2026-07-28, path-quality 2026-07-29) — closes the
  `wip/montage-run-hardening` port; colour-as-a-stage's design-§10
  match-grade conductor stays separately deferred.

- **Reframe path-quality cluster (smoothing window · jitter check ·
  lead-from-travel) DONE (2026-07-29)** — plan
  `docs/plans/2026-07-28-path-quality.md` + design
  `docs/specs/2026-07-28-path-quality-design.md`, Tasks 0–9. Three coupled
  fixes the first real montage run wrote live, landed through the
  design→plan→TDD cycle they skipped. **(A)** the crop's savgol smoothing
  window is now specified in **seconds**, not frames
  (`pathsmooth.window_frames`), resolved against each clip's own fps at render
  time — 30fps still resolves to the historical 7 frames, 60fps resolves to 15
  (the same literal window was filtering half as much motion on the
  drone/telephoto footage this repo actually gets). **(B)** `checks.jitter` is
  now **route-aware** — it subtracts only the subject's own backtrack (never
  its forward motion) before scoring the crop's reversals, box-filtering the
  route first via `_route_window` (spanning the route's own cadence, ~0.08s)
  so per-frame detector noise isn't mistaken for the subject's own signal.
  **(C)** an authored `lead` composition is honoured — not silently swapped to
  `center` — when `motion.classify` lands in its ambiguous zone (a subject
  that crosses the frame AND grows toward the camera, e.g. a surfer on a
  beach-side telephoto): the new `motion.travel_direction` (net-dx sign) is
  the one spelling both `reframe.compute_path` (lays the crop out) and
  `check_episode` (grades it) read, so the two can never disagree about which
  line is correct. Port of the parked `wip/montage-run-hardening` commit
  `4841dd3`'s "pathsmooth smooth_window_s" bucket (the colour half of the same
  park already landed via colour-as-a-stage) through the design→plan→TDD-review
  cycle it skipped — the code ran green on that 99-clip run (1697 passed) but
  never went through review. Full suite **1951 passed / 2 skipped**, no golden
  moved. 2nd parked montage-run bucket landed (after track-stitch, 2026-07-28);
  titles-animations landed next (2026-07-29, own entry above) as the 3rd and
  final parked bucket, and colour-as-a-stage's design-§10 match-grade
  conductor stays separately deferred.

- **Track-stitch (§6.1a ID-switch bridging) DONE (2026-07-28)** — plan
  `docs/plans/2026-07-28-track-stitch.md` + design
  `docs/specs/2026-07-28-track-stitch-design.md`, Tasks 0–5. `build_route` built
  the crop's route from a single tracked id, so when ByteTrack drops the hero
  through an occlusion and re-acquires the same person under a fresh id, the
  route ended at the switch and `reframe` froze the crop for the remainder —
  measured on the run that surfaced it: a 9.14s drone ride whose hero track
  ended at 3.04s left the final 6.10s (67%) of the shot delivered as a frozen
  crop. New pure `scripts/track.py` core — `_segments`/`_median`/`_joinable`/
  `stitch_ids` + the measured `STITCH_*` threshold block — chains
  forward/backward from the hero id, judging each candidate against the segment
  it would attach to (not the original hero, since a subject drifts across a
  shot). `_joinable` has two evidence regimes: an OVERLAP (ByteTrack often
  confirms the new id before dropping the old — measured 2–29 shared frames) is
  judged by median offset on the shared frames alone, skipping the box-area
  gate (a dying track's last boxes are already degrading); a GAP falls back to
  an endpoint jump bounded by the hero's own speed plus a same-size-class guard
  against a distant bystander. Thresholds are deliberately **tight** and
  field-measured, not tuned against synthetic footage — stitching too eagerly
  teleports a stranger's coordinates into the route, which reads far worse than
  the frozen crop it replaces. `build_route` now calls `stitch_ids` **before**
  writing the `TrackMeta` sidecar (the one deviation from the parked patch) so
  the merged ids ride as `TrackMeta.stitched: list[int]` provenance (`[]` =
  clean, back-compatible `from_dict`); the route loop picks the overlap
  candidate nearer the route's own last point, not detection order, so a
  handover never writes a small teleport into an otherwise-continuous crop.
  Port of the parked `wip/montage-run-hardening` commit `4841dd3`'s "track.py
  stitch" bucket — the same park that colour-as-a-stage and
  scenario-first-pacing already landed hunks from — through the
  design→plan→TDD cycle it skipped. **No consumer gate**: `stitched` is
  observability only, matching `PathMeta.pan`/`.stabilized`; stitching is
  rung-1 (YOLO) only, since `flow`/`manual` degraded routes carry no ids to
  stitch, and a `None` hero stitches nothing by construction. Tested over
  synthetic `per_frame` lists (a real ByteTrack switch is expensive to stage
  deterministically) plus the established faked-detector `build_route`
  integration harness — no new render path, no golden moved. Full suite **1897
  passed / 2 skipped**.

- **Colour-as-a-stage (slice F) DONE (2026-07-27)** — plan
  `docs/plans/2026-07-26-colour-stage.md` + design
  `docs/specs/2026-07-26-colour-stage-design.md`, Tasks 0–16. Promotes colour from
  the single normalize-to-middle gain to a per-episode **actuator**, landing the
  parked `wip/montage-run-hardening` colour code (commit `4841dd3`, written live on
  the first 99-clip run, never TDD-reviewed) through the design→plan→TDD cycle it
  skipped, plus four additions. `scripts/lib/color.py` becomes the single colour
  authority: the seven parked grade primitives (`black_point`/`highlight`/
  `saturation`/`shadow_red`/`mid_blue`/`dip` + the non-linear `tone` profile
  transfer) + a new `grade_chain` composer that owns the one fixed op order (moved
  out of `reframe`) + an **additive, identity-off auto white-balance**
  (`white_balance_gains`/`_arg`, grey-world toward the common channel average,
  emitted first, `""` at strength 0 so every pre-slice render stays byte-identical)
  + a pure `percentiles`. `reframe` builds the `wb`/`tone` fragments, runs the
  render-time `verify_tone` banding guard, and splices the finished grade into its
  one `-vf` tail (**one encode preserved**). `ReframeSpec`/`EDLEpisode`/`Manifest`
  carry the nine identity-default colour fields (`+white_balance`); `process_episode`
  threads them into `ReframeSpec` and passes the pre-grade segment as `source=` to
  the check. New pure `scripts/lib/color_fidelity.py` (`hue`/`hue_drift`/`evaluate`,
  exposure/saturation-invariant hue-angle) + `check_episode`'s advisory
  `color_fidelity` check — subject-region hue drift source-vs-graded, `passed=None`,
  **out of `overall`** (never fails the episode). New `scripts/color_measure.py`
  (`measure_profile` → `(p5,p50,p95)` luma) makes `tone` hand-authorable. Colour-
  range (tv/pc) correctness in `assembly`/`ExportProfile`. `edl_to_reel
  --color-delta-max` overrides the across-cut ceiling. **1869 passed / 2 skipped**
  (real ffmpeg colour proofs: the grade — incl. `white_balance` and `tone` — moves
  the delivered pixels; the fast path is byte-identical at defaults; `verify_tone`
  refuses a banding curve; the fidelity check flags a hue-broken grade). **Approach:
  faithful port + tighten the colour boundary** (`color.py` owns the op order via
  `grade_chain`). **Review-driven fixes (separate follow-up commits):** the parked
  `assembly.matches` required an exact `tv` tag, which silently re-encoded every
  self-produced (untagged) episode — a lossless-assemble regression — fixed by
  treating `"unknown"` as delivery-compatible + an anti-regression test
  (`a78a53e`); `EDLEpisode` now coerces `tone_src`/`tone_dst` list→tuple for
  round-trip symmetry (`16df305`); `_colour_fidelity`'s params typed (`f4f5069`);
  `ReframeSpec` colour-range tests assert the remedy text + bool-reject
  (`7164576`); the tone integration proof asserts the curve moves the delivered
  pixels (`f5f75f8`). **Deferred (NOT built):** the design-§10 match-grade
  **conductor** (measure every episode → one common target → auto-author `tone`
  pairs — slice F is its foundation, reusing `measure_profile`), the §10 mood LUT,
  the §9 in-episode "mean-RGB ±8" gate (the richer grade supersedes it),
  `smooth_window_s` (pathsmooth), and `edl_to_reel`'s `platform` param (safe-zones
  follow-up — the current signature still has none).

- **Edit-plan span merge (feedback #3, slice 3b) DONE (2026-07-26)** — plan
  `docs/plans/2026-07-26-edit-plan-span-merge.md` + design
  `docs/specs/2026-07-26-edit-plan-span-merge-design.md`, Tasks 0–4. An EDL episode
  may reference a range of adjacent footage windows — `"window": [i, j]` in
  `selection.json` — and `edit_plan` projects the range onto one continuous episode
  spanning `[min start … max end]`, carrying the connective footage between the
  windows ("turn → drive → turn"). New pure `edit_plan._merge_windows` synthesizes
  one `FootageWindow` (union `track_ids`, inherit window i's shot_type/description)
  fed to the unchanged `window_to_episode`, so `FootageClip.room_after` refuses a
  range that straddles a scene cut for free (a presence transition inside one shot
  is allowed; a ~1ms FOOTAGE-rounding overshoot is clamped to the boundary, not
  refused); `_resolve_window` branches the `window` ref (int → single, `[i, j]`
  → merge) with fail-loud validation. No contract, intake, or pacing change; the
  single-window path is byte-for-byte unchanged.

- **Intake parallel scan + resumable checkpoint DONE (2026-07-25)** — plan
  `docs/plans/2026-07-25-intake-parallel-checkpoint.md`, Tasks 0–6 (slice B, #4/#5).
  `intake()` split into a parallel checkpointed Phase 1 (`_process_clip` worker in a
  `ThreadPoolExecutor`, `--jobs` default 3, `ensure_model` before the pool) and a
  cheap deterministic Phase 2 (cull + cast in `sorted(paths)` order). New
  `scripts/lib/intake_cache.py`: atomic per-clip store/load keyed on
  size/mtime/sample_fps/model/`CACHE_VERSION`; `--fresh` bypasses it. Output is
  byte-identical at any `jobs` and any cache hit/miss mix. A bad clip is quarantined
  to `intake_report.json` + a `## Failed clips` section (exit 0); a re-run retries
  exactly the failed clips. #3 window band deferred to its own slice.

- **Intake activity-units carving (feedback #3, slice 3a) DONE (2026-07-25)** —
  plan `docs/plans/2026-07-25-intake-activity-units.md` + design
  `docs/specs/2026-07-25-intake-activity-units-design.md`, Tasks 0–6. Replaces
  intake's equal-interval `_split_span` tiling with activity-anchored units: new
  pure `scripts/lib/carve.py` (`subject_curve`/`camera_curve`/`find_peaks`/
  `units_for_span` — local-maxima peaks relative to the clip, no absolute
  threshold invented; each peak yields a tight + a lead-in candidate, band-clamped
  with the peak kept inside; a flat span yields one max-mean window, never a
  tiling). `intake.carve_windows` builds the per-span activity curve — 2-D bbox
  displacement where people are present, resampled vidstab magnitudes otherwise —
  and delegates to `carve.units_for_span`; the vidstab detect pass moves ahead of
  carving inside `_process_clip` so a people-less span has its curve at carve
  time, and the same magnitudes feed `_windowed_shake` (`shake_by_window`
  deleted, along with `_split_span`). `FootageWindow` gains `track_ids` (who is
  in the unit — `_build_window` unions the per-sample ids; names resolve
  downstream via `cast.json`); `_motion` is now 2-D bbox displacement (a
  vertical slide or cross-step registers, not only horizontal motion).
  `CACHE_VERSION` 1 → 2 invalidates every clip cached under the old carve.
  `FootageClip.room_after`/`edit_plan.window_to_episode`'s docstrings de-cite
  the retired equal-interval tiling (text only, no behaviour change). **1788
  passed / 2 skipped.** 3b (`edit_plan` span merge) landed 2026-07-26 — see the
  entry above.

- **Core engine — plan `docs/plans/2026-07-05-video-grid-core.md`, Tasks 0–11 ALL
  COMPLETE**, final review verdict READY (2026-07-07). 49 tests green (incl.
  golden fixture: real MVI_3739 footage @59.94fps through the full engine).
  Notable amendments beyond plan-verbatim code:
  - vidstab preflight = warning, not blocker (`07d2e68`) — homebrew-core ffmpeg
    lacks libvidstab; core never calls it; process-episode re-checks hard.
  - lib hardening (`341d059`): smooth([])→[], savgol odd-window ordering, on_line
    raises on route/path desync, gain(≤0) raises with remedy.
  - **route-gap desync fix (`a19937f`)**: crop x(t) built from route timestamps,
    not frame index — occlusion gaps no longer desync crop from video timeline;
    empty route fails loud.
  - Golden fixture as-built: window 9.083–10.668s (not lena_ride2) — diagonal
    motion means no 2.5s window in MVI_3739 classifies lateral; see plan Task 9.5.
  - **Hardening round (2026-07-07, fresh-eyes audit, 5 commits `27e3571`→`0c8c283`):**
    proc.run surfaces ffmpeg stderr; check_episode validates composition
    (+`break`=editorial-only) and uses spec-§9 boundary-luma black check; track
    drops id=None frankentracks, probes fps/dims, adds speed+border features;
    reframe caps expr knots (~80), even dims for all canvases, §6.4 Y headroom,
    loud stabilize/fps guards; storyboard hero-marks helper. **68 tests green.**
    Spec/plan/landmines synced same round.

- **process-episode orchestrator DONE (2026-07-08)** — plan
  `docs/plans/2026-07-08-process-episode-orchestrator.md`, Tasks 0–7 via strict
  subagent-driven-development. **122 tests green.** Built: `scripts/lib/manifest.py`
  (validate gate), `scripts/lib/orchestration.py` (contradiction detect +
  retry-ladder + escalation), `scripts/lib/proc.py`, `scripts/process_episode.py`
  (deterministic loop: track→reframe→storyboard→check, threads probed
  canvas/src_dims — **closes the contract note** — times stages, hero marks on
  storyboard), `skills/process-episode/SKILL.md` (subagent: ask-before-start,
  editorial gate, stop-and-report). Golden fixture runs the whole orchestrator
  through real ffmpeg. Review-driven fixes: manifest null/unknown-key/model/color/
  canvas hardening, hero truthiness, centered→on_line alias, project_dir mkdir,
  hero-marks wiring. **Final whole-slice review (`5da32b2`):** verdict READY after
  one Important fix — a named/rule hero (non-tuple) silently suppressed the §6.1a
  hero-ambiguity stop-and-report while never being seeded; introduced
  `orch.is_seed_pin` (non-empty tuple), the single predicate shared by the
  ambiguity gate and the shell's `seed_bbox` gate. **124 tests green.**

- **engine dataclass-hardening DONE (2026-07-09)** — plan
  `docs/plans/2026-07-08-engine-dataclass-hardening.md` + design
  `docs/specs/2026-07-08-engine-dataclass-hardening-design.md`, Tasks 0–10 via
  strict subagent-driven-development (branch `feat/engine-hardening`, commits
  `78e0fb9`..`4509cd6`). **168 tests green incl. 3 real-ffmpeg integration tests
  (2 on the golden ride).** Built `scripts/lib/models.py` — typed wire-contracts
  (`RoutePoint`/`TrackMeta`/`CropPath`/`CheckResult`/`Report`, JSON
  schema-compatible round-trip) + config-specs (`TrackSpec`/`ReframeSpec`/
  `CheckSpec`/`StoryboardSpec`/`Delivery`) that raise on bad construction. Every
  engine script retyped onto specs; `check_episode.run` returns a `Report`,
  `track.build_route`/`reframe.reframe`/`storyboard.build` take specs.
  **Validation principle:** manifest gate stays SOFT (`validate()`→`needs_input`);
  everything below it is HARD (raises). **Fixes:** #1 hero `intent` derived from
  composition/motion (was always "action" → wrong hero on static/center); #2
  lead-over-nonlateral → `stop_and_report` before wasting reframes; #3
  `black_frames` relative gate (near-black AND < 0.35×body-median — dark footage
  no longer false-fails); #4 hero marks at frame-SAMPLE times (was route-index,
  desynced on gaps); #5 Douglas-Peucker iterative (no RecursionError on long
  routes); #F engine resolution/aspect-agnostic — `Delivery` (native/short_edge/
  long_edge/exact), no 9:16/1080×1920 hardcode; #G `color_means` positivity.
  Review-driven fixes: `CheckResult.to_dict` strips stale pass-key; `Delivery`
  guards non-positive crop + clean `from_spec` errors; specs raise `ValueError`
  (not `TypeError`) on wrong-type; `check_episode` body-luma sampling spread
  across clip (was first ~1s → `body_median`=0 defeated the gate). ~~**Known
  limitation:** the storyboard hero-marker's vertical fraction uses `y/src_h`
  (exact only when `crop_h==src_h`, i.e. 9:16-from-landscape).~~ **Resolved by
  layouts (2026-07-10)** — `marks_at_times` divides by `crop_h` and honours
  `crop_y`, both read from the sidecar.

- **project-init DONE (2026-07-09)** — plan `docs/plans/2026-07-09-project-init.md`
  + design `docs/specs/2026-07-09-project-init-design.md`, Tasks 0–4 via strict
  subagent-driven-development (branch `feat/project-init`, commits
  `af3753a`..`54dfa35`). **188 tests green incl. a real-ffmpeg native-inheritance
  golden.** The front-door that drives the aspect/resolution-agnostic engine:
  `scripts/lib/project.py` — `ProjectConfig` (raises on bad),
  `PURPOSE_CANVAS`/`QUALITY_DELIVERY` maps (**delivery defaults to `native`** — no
  silent downscale; a 1080 cap is a deliberate social opt-in), `resolve_project`,
  and `resolve_manifest` (episode inherits absent canvas/delivery, explicit
  episode value overrides, null=inherit, no mutation). `scripts/process_episode.py`
  gains `project=` (a `ProjectConfig` or a `project.json` path) applied before
  validation. `scripts/project_init.py` CLI writes `project.json`;
  `skills/project-init/SKILL.md` is the one-time "what's this video for" pass.
  Review-driven: override integration test made load-bearing (21:9),
  `ProjectConfig.from_json` corrupt→ValueError-with-remedy, SKILL description fixed
  ('custom' quality is an explicit `--delivery`). **Reconciliation note:**
  `project.json` is the machine `{canvas, delivery}` subset; the fuller `SPEC.md`
  reel-brief (music/mood/hook/cast) will later populate/supersede it — no conflict.
  cast.json/SPEC.md-brief/router/footage-intake stayed out of scope.

- **layouts DONE (2026-07-10)** — plan `docs/plans/2026-07-10-layouts.md` + design
  `docs/specs/2026-07-10-layouts-design.md`, Tasks 0–12 via strict
  subagent-driven-development (branch `feat/layouts`, commits `7543d95`..`93c0a4d`).
  **284 tests green incl. 14 real-ffmpeg layout goldens.** `fit-blur` and `insert`
  ship, and `fill` still delivers exactly 404×720 on the golden ride from a
  whole-string-pinned filtergraph. Built `scripts/lib/layout.py` — `LayoutSpec`
  (in `models.py`, to avoid a `models→layout→models` cycle) resolves to a frozen
  `ResolvedLayout`, and a layout is now **three parameters** — crop (aspect+scale)
  × rect in canvas × background filler — with the named modes as presets, not code
  branches. `fill` keeps its single-`-vf` fast path; the composites emit one
  `-filter_complex` (`split` → blurred cover background, tracked crop scaled into
  the card, `overlay`). `insert` takes an **opt-in border** (`border_px`,
  `border_color`, default off), and `rect` carries three numbers, not four —
  its height is derived, so a card cannot disagree with what is inside it.
  **Two silent-corruption defects fixed, both of the same class** (a consumer
  re-deriving geometry the engine already knew): `check_episode.run` re-derived
  `crop_w` from the canvas and, under `fit-blur`, judged a composition that never
  happened (405 vs the 1280 actually cut); `storyboard.marks_at_times` mapped the
  §6.1a hero marker as a fraction of the crop, so under a composite the marker
  landed on the blurred background. Both now read one `path.meta.json` sidecar
  (`models.PathMeta`) that `reframe` writes beside `path.json`, mirroring
  `track.py`'s `route.meta.json`. `CheckSpec` **loses** `canvas`/`src_dims` —
  the value has exactly one source now, the code that did the cropping.
  **Freedom, not the layout name, decides the check:** `freedom = src_w − crop_w`,
  and at zero freedom the composition check is `editorial-only` (`passed=None`)
  rather than failed-or-silently-passed. The manifest gate refuses a `lead` whose
  crop provably has no freedom — its **honest limit** is that `crop_aspect: [16,9]`
  on 16:9 footage has the same zero freedom and is not catchable before ffprobe;
  the sidecar's `freedom` is the real safety net. Found beyond the plan: `boxblur`'s
  radius must not exceed `min(out_w,out_h)//4` (yuv420p halves the chroma plane —
  real ffmpeg dies at 64 on a 3840×200 cover); `fill`'s canvas **is** its crop and
  re-deriving it drifted 21:9-of-4K by 2px; a native canvas can explode
  (`rect_w=0.02` → 36000×64000, 2.3 Gpx) so `layout.MAX_SIDE = 8192` guards right
  after `delivery.dims`. **Final review (two reviewers + a mutation battery over
  production code, `72da96f`/`93c0a4d`):** every one of nine mutations was killed
  by a test — except one, and it was the test *named for* this plan's headline
  defect. `test_crop_w_comes_from_the_sidecar_not_the_canvas` used a zero-freedom
  fixture, where `check_episode` short-circuits to `editorial-only` and never
  reaches the `crop_w` arithmetic; it is rebuilt against an `insert` with 840px of
  freedom, where re-deriving the width drops `on_line`'s ratio from 1.0 to 0.0.
  Four error-path holes closed: a manifest that `validate()` accepted could still
  crash the orchestrator (rect overflow / border-eats-card / `MAX_SIDE` all need
  the source dims, so the soft gate cannot see them) — `process_episode` now
  resolves the layout as a **preflight** right after the probe and returns
  `needs_input`, and probes before tracking so a typo fails in ms, not after YOLO;
  the `boxblur` floor `max(2, min(w//60, ceiling))` **defeated its own ceiling**
  when the ceiling was 0 or 1, so the ceiling is applied last (no real canvas
  changes: golden fit-blur 21, insert 13, wide cover 50); `PathMeta.from_json`
  raised a bare `JSONDecodeError` on the truncated sidecar its own message names;
  and two raises named remedies their caller could not act on (an `exact` delivery
  told to "pin the output", a `fit-blur` told to shrink a `rect` it forbids).
  **Fixed (2026-07-10):** `check_episode._black_frames_check` returned `pass=True`
  on a *uniformly* black clip — `worst < black_rel * ref` is `0 < 0` — now the
  relative gate is OR'd with an absolute body-black floor (`ref < black_floor`);
  real-ffmpeg all-black test in `test_verify.py`, design §12 logged. The layout
  goldens still measure boundary luma against their own (stricter) absolute bar —
  left as-is, they guard the render pipeline, not the check. The
  `Delivery("exact", …)` even-dims hole filed here is **now closed**: it was the
  one mode that skipped `geometry.even()`, so an odd side reached `scale=` and
  libx264 failed cryptic; `__post_init__` raises a remedy-carrying `ValueError`
  (exact never silently rounds — 405x721 → "use (404, 720) or (406, 722)"), and
  `from_spec("exact:WxH")` refuses identically. design §12 logged.

- **docs registry + coding standards (2026-07-09)** — specs moved to
  [`docs/specs/`](./specs/); anna-auth-style standards adopted
  ([coding-standards.md](./coding-standards.md), [testing-guide.md](./testing-guide.md),
  [development-workflow.md](./development-workflow.md)); `CLAUDE.md` became a
  registry; scripts brought into compliance (full type hints, imports-at-top).

- **reel back half DONE (2026-07-11)** — plan `docs/plans/2026-07-10-reel-back-half.md`
  + design `docs/specs/2026-07-10-reel-back-half-design.md`, Tasks 0–11 via strict
  subagent-driven-development (branch `feat/reel-back-half`, commits
  `6c6b1e4`..`8e1d768`). **342 tests green incl. a real-ffmpeg whole-slice golden**
  (`test_reel_backhalf.py`: 2 windows → `process_episode` ×2 → `assemble` →
  `check_reel` → `deliver`). The silent back half of the conveyor: `[locked
  out/<ep>.mp4 …] → assemble → work/master.mp4 → check_reel → deliver →
  out/REEL_v{n}.mp4`, exactly one encode anywhere in it (at deliver). Built
  `scripts/lib/assembly.py` (`probe_stream`/`matches`: all-uniform episodes concat
  losslessly with `-c copy`; an outlier is normalized alone, then copy-concat) +
  typed contracts in `scripts/lib/models.py` — `ExportProfile`/`REEL_H264`,
  `ReelCheckSpec`, `ReelFailure`, `ReelReport` (raise-on-bad-construction + JSON
  round-trip, mirroring `Delivery`/`LayoutSpec`). `scripts/check_reel.py` runs four
  mechanical checks against the master — black, color-across-cuts (mean-RGB delta;
  culprit = the span **farther from the reel's per-channel median**, with a tie —
  every 2-episode reel, whose 2-value median is equidistant from both spans —
  blaming the LATER episode), variety (phash Hamming distance at episode
  midpoints), length — while `beat`/`loudness`/`safe_zones` honestly report
  `CheckResult(passed=None, detail={"status":"not-implemented"})`, **never** a
  silent pass. Every failure emits a machine-readable `ReelFailure` (`check`,
  `episode_idx`, `escalate_to`, `detail`) so a future driver reads the culprit
  straight off the report instead of re-deriving it. `scripts/deliver.py` is the
  **one encode** — `ExportProfile.args()` is its single source of ffmpeg flags —
  behind a **hard gate** (`report.overall is False` → raise, no fix-forward); it
  versions `out/REEL_v{n}.<container>` (never overwrites) and appends a changelog
  line to `out/VERSIONS.md`. **Found beyond the plan:** the shared `sample_clip`
  test fixture's `drawbox` position expressions are inert under ffmpeg 8.1.1 (`t`
  reads as `INT32_MAX`, not frame time) — switched to compositing the moving box
  with `overlay` instead (`fae6209`), a test-fixture-only fix; `testing-guide.md`
  now warns against reintroducing the `drawbox` form. **Deferred → built (Phase
  A.5, see the entry below):** the retry *loop* — `reel_orchestration.next_action`
  (the §4.1 ladder) + the `build_reel` driver (assemble → check → reprocess culprit
  via `process_episode` → recheck → deliver | stop-and-report) + a per-episode
  colour override in `reframe` (shipped as `ReframeSpec.color_correct`) so a
  reprocess can re-grade one episode toward the reel median.

- **reel retry loop (Phase A.5) DONE (2026-07-11)** — plan
  `docs/plans/2026-07-11-reel-retry-loop.md` + design
  `docs/specs/2026-07-11-reel-retry-loop-design.md`, Tasks 0–7 via strict
  subagent-driven-development (branch `feat/reel-retry-loop`, commits
  `39adba0`..`a06a07e`). **389 tests green** (47 new, incl. 2 real-ffmpeg
  tests in `tests/integration/test_reel_retry.py`). `scripts/build_reel.py`
  loops `assemble → check_reel → next_action → reprocess culprit → deliver |
  stop-and-report` over a typed `ReelManifest` (locked episodes, each a
  manifest + clip + **frozen route** — a reprocess reuses it, so colour/black
  fixes never re-track). `reel_orchestration.next_action` is the §4.1 ladder
  one level up, mapping a `check_reel` report to Deliver | Reprocess[...] |
  Escalate. A colour reprocess corrects via `color.corrected()` (composes an
  external per-channel factor onto grade gains, re-clamps to `[LO,HI]`)
  through `ReframeSpec.color_correct`, threaded by `process_episode`'s new
  `color_correct` param (constant across attempts, like `layout`);
  `check_reel`'s colour fail `detail` now carries `target` + `culprit_mean` so
  the driver computes the correction with no re-probe. **Two subtle rules
  define the loop: escalate-wins** (§3) — any non-auto-fixable or capped
  failure escalates immediately, never spending a round on a reel that also
  carries an unfixable fault — **and compound-not-revert** (§4) — each
  round's `med/d_i` ratio compounds onto the episode's *stored* factor
  (`cc[i] ← clamp(cc[i] * med/d_i, LO, HI)`) rather than replacing it, since
  `process_episode` regrades from source every pass and a per-round factor
  alone would revert instead of converging. **Only `black`/`color_across_cuts`
  auto-close**; `variety` (→ edit-plan) and `length` (→ pacing)
  stop-and-report — their front-half fixers (EDL, pacing) aren't built.
  **`build_reel` never delivers a failed reel:** escalate, reprocess-failure,
  and capped-attempts all stop-and-report a machine-readable finding instead.
  **Review-driven:** Task 2's `ReelManifest` validation closed gaps found on
  review (lazy threshold fields, a null-manifest `TypeError`, a bare
  `KeyError` — all now raise `ValueError` with a remedy); Task 3 gained type
  hints + 3 branch-pinning tests; Task 5's `_compound` now reuses
  `color.corrected`.

- **music spine (Phase B · B1+B2) DONE (2026-07-11)** — plan
  `docs/plans/2026-07-11-music-spine.md` + design
  `docs/specs/2026-07-11-music-spine-design.md`. **426 tests green.** Gives the
  reel sound and closes two of `check_reel`'s silent `passed=None` gates.
  Built: `scripts/beats.py` (B1) — librosa `analyze(track, start_offset,
  duration) → MusicSpec` (tempo + reel-relative beat grid + coarse RMS
  energy), CLI writes `MUSIC.json`; `scripts/lib/models.py` gains the
  `MusicSpec` config-spec, `ReelCheckSpec.beat_tol/loudness_target/
  loudness_tol`, `_ADVISORY_CHECKS` (excludes `beat` from `ReelReport.overall`),
  and `ReelManifest.music`; `scripts/check_reel.py` — loudness is a **hard**
  gate (escalates to `audio-mix`), beat is **advisory** (measured, reported,
  never blocking); `scripts/mix.py` (B2) — music-only audio stem: accurate
  seek + afade + two-pass loudnorm −14 LUFS → aac (ambient ducking/SFX
  deferred to when `extract`, §5.8, preserves per-episode audio);
  `scripts/deliver.py` muxes the stem (stream-copy, preserves −14 LUFS);
  `scripts/build_reel.py` builds the stem once after the picture pass,
  re-checks loudness/beat, delivers with audio — `music=None` keeps the
  silent Phase A.5 path unchanged. **Code polish (same-day):** `check_reel`'s
  `_NOT_IMPL` stub was overloaded — it labeled `beat`/`loudness` "not
  implemented" when they are now built and simply have nothing to check on a
  silent reel. Split into `_UNCHECKED` (`beat`/`loudness` → status
  `"not-checked"`, reason names the missing input) and `_NOT_IMPL`
  (`safe_zones` only, genuinely unbuilt) — `passed` stays `None` either way,
  so no control-flow changed, only the honesty of the report. **Deferred (NOT
  built):** B3 autonomous sourcing (`music_find`/`music_fetch`, `music.mode`,
  mood-match), B4 pacing (5.6), ambient ducking/SFX, downbeats/sections/
  spectral/mood, `safe_zones`.

- **extract spine (Front-half SP1) DONE (2026-07-11)** — plan
  `docs/plans/2026-07-11-extract-spine.md` + design
  `docs/specs/2026-07-11-extract-spine-design.md`, Tasks 0–6 via strict
  subagent-driven-development (branch `feat/extract-spine`, commits
  `f7061be`..`ee5f6ba`). **470 tests green.** A hand-authored `EDL.json` now
  drives the whole conveyor to a delivered `REEL_v1.mp4` — no more
  hand-supplied segments or per-episode manifests. Built four units:
  `scripts/lib/edl.py` — `EDLEpisode`/`EDL` typed config-specs (JSON
  round-trip) + `to_manifest_dict` bridge (EDL row → process-episode manifest
  dict; omits canvas/delivery so they inherit); `scripts/extract.py` —
  `extract_edl(edl, footage_root, seg_dir)` loops the untouched single-window
  `extract()` over every EDL episode, plus the §5.8 length gate (segment
  duration must match its window, else raise); `scripts/edl_to_reel.py` — the
  thin SEQUENTIAL driver: load EDL+project → bridge+resolve+preflight →
  `extract_edl` → `process_episode` per episode → assemble a `ReelManifest` →
  `build_reel` → delivered | stop-and-report (CLI);
  `tests/integration/test_front_spine.py` — a real-ffmpeg golden proving the
  EDL→driver→`build_reel`→deliver **wiring**. **Load-bearing invariant:** the
  driver resolves canvas/delivery **once** (bridge → `resolve_manifest`) and
  stores the resolved manifest in each `ReelEpisode`, because `build_reel`'s
  reprocess calls `process_episode.process_episode(...)` **without**
  `project=` — an unresolved manifest would silently lose canvas/delivery on
  any reprocess round. **The golden's honest scope:** `process_episode` is
  faked (a real `route.json` + a copied, re-muxed clip) because the synthetic
  `sample_clip` is a box, not a person, so real YOLO tracking returns an empty
  route — the golden proves the wiring on real bytes (real extract, assemble,
  `check_reel` gates, mix, deliver mux), not pixel-level crop-to-canvas
  correctness (that stays covered by `process_episode`'s own real-footage
  goldens). **Deferred (NOT built):** SP1b `draft.mp4` (labels + music bed,
  §5.9), SP2 footage-intake, SP3 `EDL.md` markdown render + interactive
  edit-plan authoring, SP4 trend-scan, and the cap-3 PARALLEL router +
  episode-choice curation (montage §5.1).

- **footage-intake (5.2) DONE (2026-07-12)** — plan
  `docs/plans/2026-07-12-footage-intake.md` + design
  `docs/specs/2026-07-12-footage-intake-design.md`, Tasks 0–15 via strict
  subagent-driven-development (branch `feat/footage-intake`). **522 tests green**
  (+1 vidstab-gated integration golden, skipped without libvidstab).
  `scripts/intake.py` scans a footage folder → `FOOTAGE.json` (typed) +
  `FOOTAGE.md` (rendered): per clip, scored candidate **moment-windows** — probe
  + PySceneDetect scene bounds + one YOLO11-seg + ByteTrack pass (people/tracks/
  masks) + `vidstabdetect` shake, **sub-scene carve** into the episode band
  (scenes alone don't split a long take), present/motion/stability/dur **score**,
  **phash cull** marking the best (dedup by image, not filename). New contracts
  in `scripts/lib/footage.py` — `FootageWindow`/`FootageClip`/`Footage`
  (+`to_markdown`) and `CastMember`/`Cast`; a `FootageWindow` projects onto an
  `EDLEpisode` (5.7's input). The **cast pass**: the single seg pass surfaces
  top-N distinct person crops → `cast_candidates.json` + `cast_crops/`; the
  `footage-intake` SKILL names them interactively → `write_cast` → `cast.json`.
  `assembly.probe_duration` promoted from `extract._probe_dur` (shared). **Intake
  is the repo's first runtime vidstab consumer** — hard preflight + skip-if-absent
  tests. **Review-driven fixes:** carve dropped a shredded clip to one over-band
  window (now yields empty — band invariant held); the cast pass was built but
  **unreachable** (`intake()` discarded crops, `write_cast` took arrays that
  didn't survive the boundary) — wired end-to-end (persist candidates +
  descriptor-based `write_cast`, `(source, track_id)` keys since ByteTrack ids
  restart per clip); `SHAKY_CLIP` width-fraction spec-sync; a `cull` test-fixture
  bug (`imagehash.average_hash` of any uniform image is all-zero); full type
  hints. **Deferred (NOT built):** SP1b `draft.mp4`, SP3 authoring, SP4
  trend-scan; descriptor→manifest hero-pin wiring landed 2026-07-16 as its own
  slice, cast → hero-pin (see below) — `orch.is_seed_pin` was deleted there,
  not left bbox-only.

- **edit-plan spine (Front-half SP3 · 5.7) DONE (2026-07-12)** — plan
  `docs/plans/2026-07-12-edit-plan-spine.md` + design
  `docs/specs/2026-07-12-edit-plan-spine-design.md`, Tasks 0–7 via strict
  subagent-driven-development (branch `feat/edit-plan-spine`, commits
  `3208f0e`..`796e74f`). **548 tests green** (+1 vidstab-gated integration
  golden, skipped without libvidstab). Closes the critical-path head to
  autonomous v1 (5.2 → **5.7** → 5.1 router). `scripts/lib/edl.py` gains
  `EDLEpisode.to_dict`/`EDL.to_dict` (JSON round-trip serializer),
  `EDL.to_markdown` (the `EDL.md` human map: source/window/shot/layout/comp/
  grid/motion/beat/notes per episode), and `preflight` — the EDL→manifest
  gate extracted verbatim from `edl_to_reel`'s inline step-1 loop, now shared
  by the driver and the new authoring path (`edl_to_reel`'s own tests stay
  green, unchanged). `scripts/edit_plan.py` (new): `window_to_episode`
  projects a scored `FootageWindow`/`FootageClip` (5.2) onto an `EDLEpisode`
  **by reference** — mechanical fields (source/start/dur/shot_type/
  description) copied straight from `FOOTAGE.json`, never retyped, closing
  off the silent-wrong-cut class (montage §12); only editorial fields
  (composition/grid required, layout/motion/hero/… optional) are
  agent-supplied. `build_edl` resolves a `selection.json` (window refs by
  source + integer index, plus editorial fields and reel knobs) into a typed
  `EDL`, fail-loud on an unknown source (lists what's available) or an
  out-of-range window index. `write_edit_plan` + CLI
  (`python -m scripts.edit_plan build`) chains Footage→selection→`build_edl`
  →`preflight`→`EDL.json`+`EDL.md`, writing **nothing** on a preflight
  `stop_and_report`. `skills/edit-plan/SKILL.md` — the writing-plans-style
  **autonomous draft + single review gate** subagent (context recon → author
  `selection.json` → build → present `EDL.md`; edits round-trip through
  `selection.json`, the SKILL never hand-patches `EDL.json`).
  `tests/integration/test_edit_plan.py` — the real-ffmpeg SP3→SP1 golden: a
  hand-written `FOOTAGE.json` + `selection.json` + `project.json` →
  `edit_plan build` → `EDL.json` round-trips and `EDL.md` renders → **the
  same `EDL.json` feeds the existing `edl_to_reel`** on synthesized source
  clips → `status == "delivered"`, `REEL_v1.mp4` exists — proving the
  SP3→SP1 seam on real bytes. **Selection stays the agent's judgment, code
  stays thin** — no Python window-scorer, since 5.2 already scored/culled/
  best-marked the windows; 5.7 only projects references and renders the map.
  **Deferred (NOT built):** full reel-brief `SPEC.md` authoring (§5.3),
  `PACING.md`/`beat_slot` binding (§5.6/B4 — `beat_slot` stays `None`
  without pacing), cap-3 **parallel** router + episode-choice curation
  (§5.1), cast→hero-pin descriptor resolution (`hero` still rides as a bare
  bbox/rule/name string).

- **using-montage router (5.1, entry-skill) DONE (2026-07-12)** — plan
  `docs/plans/2026-07-12-using-montage.md` + design
  `docs/specs/2026-07-12-using-montage-design.md` (branch `feat/using-montage`).
  Ships the conveyor's front door: `skills/using-montage/SKILL.md` conducts the
  built stages (project-init → footage-intake → [music] → edit-plan → edl_to_reel)
  with the three §4.1 user checkpoints (SPEC · EDL+curation · final review),
  resuming a half-finished run for free and naming any deferred stage on skip.
  Backed by `scripts/montage.py` — a thin deterministic **inspector**
  (`Stage`/`V1_STAGES` + `next_action(run_dir)` reporting each stage's state
  done/next/pending/optional/skip from artifact presence, + a `status` CLI). 15 new
  unit tests (**564 green**, 1 skipped). **Inspector, not runner:** the judgment
  steps (cast-naming, selection authoring) stay agent-interactive, so the SKILL runs
  stages and consults `next_action` for the resume/next decision (mirrors intake.py
  ↔ footage-intake). No stage re-implemented; no new integration golden — the
  SP1/SP3 seam goldens already prove intake→edit→reel on real bytes. **Deferred (NOT
  built):** cap-3 **parallel** episode fan-out (edl_to_reel stays sequential), full
  reel-brief `SPEC.md` (5.3), `draft.mp4` (SP1b), dual-emit "without-music"+sidecar
  (5.14), trend-scan (5.4), pacing (5.6), cast-name hero-pin resolution.

- **reel-brief (5.3, editorial spine) DONE (2026-07-12)** — `scripts/lib/spec.py`
  (`Spec` config-spec: canvas-from-project + gate on mood/hook/length, JSON
  round-trip, `to_markdown`) + `scripts/reel_brief.py` (`build_spec`/`write_reel_brief`
  + CLI) + `skills/reel-brief` (one-question-at-a-time → `SPEC.md`+`SPEC.json`). Router
  flips reel-brief deferred → **optional** (SPEC.md enriches CP1; autonomous path
  intact). Text stage — no ffmpeg, no golden. See `docs/plans/2026-07-12-reel-brief.md`.

- **assemble-draft (5.9, QA-preview spine) DONE (2026-07-13)** — plan
  `docs/plans/2026-07-13-assemble-draft.md` + design
  `docs/specs/2026-07-13-assemble-draft-design.md`. **603 tests green** (+4
  skipped: the 3 real-ffmpeg draft goldens on a machine whose ffmpeg lacks
  drawtext, +1 pre-existing vidstab-gated). `scripts/draft.py`
  (`build_draft` + CLI): extract each EDL window, burn a canvas-fit (letterbox)
  + `processing_notes` label into every segment, concat via the shared core, mux
  a rough music bed by reusing `mix.mix` — one source of truth for laying music,
  absent music → a silent draft. `scripts/lib/draft.py` — the pure helpers
  (`resolve_font`/`label_text`/`segment_filter`), split out so the drawtext
  `fontfile=` landmine (design §12 — macOS has no fontconfig default) is caught
  in a unit test, not at render. An `ensure_drawtext` runtime preflight fails
  loud with a remedy when the active ffmpeg lacks the filter. `scripts/lib/
  assembly.py` gains a shared `concat()` (extracted verbatim out of `assemble()`,
  behaviour unchanged — the final assembler and the draft now reuse one concat
  core). Router: an **optional** `assemble-draft` Stage in `montage.py`
  (`draft.mp4`, checkpoint `"edl"`, CP2) — never chosen as `next`, so the
  autonomous chain is untouched; `using-montage` offers it as an optional CP2
  preview after edit-plan. Real-ffmpeg golden (`tests/integration/test_draft.py`:
  canvas-fit dims, muxed music bed, silent variant, CLI) behind an autouse
  drawtext skip-guard so the suite stays green on a machine without a
  drawtext-capable ffmpeg; `setup.sh` now ensures one by default (homebrew-ffmpeg
  tap fallback, mirroring the vidstab block).

- **titles (5.16, on-screen text spine) DONE (2026-07-13)** — plan
  `docs/plans/2026-07-13-titles.md` + design
  `docs/specs/2026-07-13-titles-design.md`. **638 tests green** (+6 skipped:
  the 2 real-ffmpeg titles goldens + the 3 draft goldens on a machine whose
  ffmpeg lacks drawtext, +1 pre-existing vidstab-gated). `scripts/lib/fonts.py`
  — `resolve_font` extracted from `draft.py` plus a name-mode (`FONT_NAMES`):
  a curated cask font resolves by friendly name, unknown/uninstalled fails
  loud with the `--with-fonts` remedy — no silent substitution.
  `scripts/lib/titles.py` — `Title`/`Titles` config-specs + `build_filterchain`
  (one `drawtext` per title, `enable='between(...)'` windows, per-title
  `textfile=`). `scripts/titles.py` — `build_titles` projects `SPEC.hook/text/
  ending` into a starting `Titles` (hook opens, ending closes in the last 3s);
  CLI writes `TITLES.json`+`TITLES.md`. `scripts/deliver.py` gains `titles=` —
  burns the chain into the **one encode** it already runs (silent and
  music-muxed paths both covered, never a second pass); `build_reel`/
  `edl_to_reel` thread `titles=` through. Optional `montage.py` Stage
  (`TITLES.json`, checkpoint `"final"`) — never chosen as `next`; `titles`
  SKILL + `using-montage` CP3 wiring (offered alongside the final reel
  review). `setup.sh --with-fonts` installs a curated set (Montserrat/Inter/
  Bebas Neue/Oswald) on top of the DejaVu floor. Real-ffmpeg golden
  (`tests/integration/test_titles.py`) confirms the burned encode differs
  pixel-for-pixel from an untitled one, both silent and muxed, behind the
  existing drawtext skip-guard. See `docs/plans/2026-07-13-titles.md`.

- **start-offset intelligence (§5.5 sub-slice) DONE (2026-07-13)** — plan
  `docs/plans/2026-07-13-start-offset-intelligence.md` + design
  `docs/specs/2026-07-13-start-offset-intelligence-design.md`. `scripts/lib/offset.py`
  (`downsample` relocated from beats to break a beats↔vocals cycle; `vocal_gaps`
  relative-threshold pause spans; `best_offset` loudest gap-start window, argmax
  fallback — with a review-fixed invariant so the offset never overruns
  `track_dur − duration`) + `scripts/lib/vocals.py` (`has_demucs`/
  `separate_vocal_energy`, the lone lazy demucs importer) + `scripts/beats.py`
  `choose_offset` driver and CLI `--auto-start` (mutually exclusive with
  `--start-offset`, needs `--duration`). demucs installs at baseline (`bash setup.sh`,
  pulls torch; warn-and-continue since 2026-08-04, was `--with-demucs`); absent → a
  logged librosa mix-silence proxy, never a crash. Pure
  decision exhaustively unit-tested; the demucs path is mocked (unit) +
  skip-if-absent (integration `test_offset.py`, real proxy path always runs).
  `analyze()` untouched. **Deferred:** beat-snap of the start, section detection
  (B4 pacing), mood-match/sourcing (B3).

- **mood-match (§5.5 sub-slice, local lane) DONE (2026-07-14)** — plan
  `docs/plans/2026-07-13-mood-match.md` + design
  `docs/specs/2026-07-13-mood-match-design.md`. `scripts/lib/mood.py` — the pure
  core (the `offset.py` analog): `MoodVector` (3 axes energy/brightness/pace,
  validate + JSON round-trip, remedy-bearing `from_dict`), a synonym-rich
  `MOOD_ANCHORS` lexicon, `mood_target` (free-text mood → target, zero-match →
  None), `distance` (weighted Euclidean), `rank`, and `rank_by_drive` (the
  no-target fallback, positive drive under its own key). `scripts/beats.py` gains
  `mood_features(track)` — lazy librosa: tempo → pace, spectral centroid →
  brightness, **peak-normalized** RMS mean → energy (loudness-robust, the §12
  relative-gate discipline). `scripts/mood.py` — the driver: scan a folder →
  `mood_features` each → rank vs `mood_target(SPEC.mood)` (or `rank_by_drive` on a
  zero-match, logged never silent) → `MUSIC_SHORTLIST.{json,md}`; CLI
  `--folder (--spec|--mood) --out-dir`. `skills/music-match` runs it, presents the
  shortlist, the user picks, then the existing `beats --auto-start` writes
  `MUSIC.json`. Pure core exhaustively unit-tested (24); `mood_features` + the
  ranking golden are real-librosa integration tests (synthetic known-answer
  signals, ±tol). **702 tests green.** **Deferred:** B3 autonomous sourcing
  (networked), catalog-metadata mood, a 4th dynamism axis, feature caching.

- **music-sourcing (§5.5 B3, network lanes) DONE (2026-07-14)** — plan
  `docs/plans/2026-07-14-music-sourcing.md` + design
  `docs/specs/2026-07-14-music-sourcing-design.md`. `scripts/lib/catalog.py`
  (`Candidate` + per-source discovery over stdlib `urllib` / an opt-in `yt-dlp`
  module invocation, `preview_clip`) + `scripts/lib/fetch.py` (download + cache +
  sidecar + responsibility log) + `scripts/music_find.py` / `scripts/music_fetch.py`
  drivers reuse the mood engine (`beats.mood_features` + `mood.rank`) to source &
  rank internet tracks into `MUSIC_SHORTLIST`: `free` = ccMixter (no key) /
  Jamendo (keyed upgrade), `any` = YouTube (yt-dlp, default) + iTunes/Deezer
  opt-in, behind an explicit responsibility switch — `any` always logs + records
  `license="unknown (any lane)"`, never silently. `music-source` SKILL runs
  find→pick→fetch; yt-dlp ships in `requirements.txt` and a Jamendo key is an
  optional non-blocking notice (`config/sourcing.env`) since 2026-08-04 (was
  `setup.sh --with-sourcing`). **5.5 now fully ✅** — all three `music.mode` rights
  lanes (`local`/`free`/`any`) complete. **740 tests green** (+8 skipped: 3
  drawtext-gated draft-goldens + 2 drawtext-gated titles-goldens on a machine
  whose ffmpeg lacks drawtext, +1 pre-existing vidstab-gated intake golden, +1
  pre-existing demucs-gated offset golden, +1 off-network iTunes sourcing
  smoke). **Deferred:** B4 pacing (5.6), trend-presence ranking (blocked on 5.4
  trend-scan), catalog-metadata mood.

- **pacing (§5.6, B4 energy-spine authoring) DONE (2026-07-14)** — plan
  `docs/plans/2026-07-14-pacing.md` + design
  `docs/specs/2026-07-14-pacing-design.md`. `scripts/lib/pacing.py` — the pure
  core (the `offset.py`/`mood.py` analog): `Slot` (index/start/dur/energy/kind,
  validate + JSON round-trip) + `Spine` (slots/target_dur/tempo, validates
  hook-first/contiguous/duration-sum, `to_dict`/`from_dict`/`from_json`/
  `to_markdown`), band constants (`LOW_BAND`/`HIGH_BAND`, `SLOW_BEATS`/
  `MID_BEATS`/`FAST_BEATS`, `HOOK_BEATS`) + `_kind`/`_beats_per_slot`/
  `_beat_energy` helpers, and `build_spine` — folds the beat grid + RMS energy
  curve into a beat-aligned energy spine, cut density rising with energy (hook
  first). stdlib only (`statistics.fmean`, no numpy/librosa) — bit-exact,
  goldens pin exact slots. `scripts/pacing.py` — the driver: `build_pacing`
  reads `MUSIC.json` → `build_spine` → writes `PACING.{json,md}`, logging a
  `SPEC.length_s`/`MUSIC.duration` mismatch (never silent); CLI mirrors
  `scripts/mood.py`. `scripts/edit_plan.py` gains `build_edl(pacing=)` +
  `--pacing`: binds the i-th selected episode to slot i (`beat_slot=i`,
  `dur←slot.dur`, window start preserved), zip-to-min; a short window keeps
  its own `dur` + logs the shortfall, an episode/slot count mismatch logs an
  over/underflow report — `pacing=None` leaves the existing no-pacing path
  unchanged (the regression guard). `scripts/montage.py`'s `pacing` `Stage`
  flips `deferred → optional`; `skills/pacing/SKILL.md` runs the driver,
  sanity-checks the `PACING.md` arc, then passes `PACING.json` to edit-plan;
  `using-montage` wires it in as an optional step between music-and-mood and
  edit-plan. Real-librosa integration golden
  (`tests/integration/test_pacing.py`): a synthetic quiet-half/loud-half WAV →
  `beats.analyze` → `build_spine` proves the loud half carries more (shorter)
  slots end-to-end. **781 tests green** (+8 skipped, unchanged from
  sourcing: 3 drawtext-gated draft + 2 drawtext-gated titles + 1 vidstab-gated
  intake + 1 demucs-gated offset + 1 off-network sourcing smoke). **B4
  authoring (role 1) complete — §5.6 now ✅.** **Deferred:** the retry-time
  auto-fix (role 2 — `build_reel`'s `length` failure re-timing the spine), the
  pacing-gate back-edge (auto re-pick `start_offset` on a misfit), librosa
  section detection, musical-phrase-aware grouping.

- **ambient ducking (§5.12 audio-mix, ambient sub-slice) DONE (2026-07-15)** —
  plan `docs/plans/2026-07-15-ambient-ducking.md` + design
  `docs/specs/2026-07-15-ambient-ducking-design.md`. Grows the music-spine
  (B2) mixer with a ducked ambient bed built from each clip's preserved
  nat-sound. `scripts/lib/models.py` gains
  `ReelManifest.ambient: bool = True` — the on/off switch (`False` restores
  today's pure-music stem).
  `scripts/mix.py` gains `_build_ambient(segments, tmp_dir)`: per `(segment,
  target_dur)` in EDL order, an audio-bearing segment trims/pads (`apad` +
  `-t dur`) to a uniform 48kHz/stereo/s16 wav, a video-only segment synths
  `anullsrc` silence instead, and `assembly.concat` joins them into one
  reel-length bed (`None` when every segment is silent — a graceful
  music-only fallback, not an error); `mix(segments=)` inserts one
  filtergraph pass between the existing seek+fade and loudnorm passes —
  `sidechaincompress` ducks the ambient (main) under the music (sidechain
  key, via `asplit`), `amix=duration=first` pins the mixed stem to exactly
  the music's `dur` so it can never drift from the picture — before the
  unchanged two-pass loudnorm. `scripts/build_reel.py`'s stem hook gathers
  each episode's `(segment, target_dur)` from its manifest and passes
  `segments` only when `rm.ambient`. **Two real-ffmpeg proofs**
  (`tests/integration/test_ambient.py`): a bed-mixed stem still measures −14
  LUFS, and the ambient's frequency band measurably drops during the loud
  half of a synthetic music track (the duck moves samples, not just wires
  the graph); `tests/integration/test_music_spine.py`'s `build_reel` golden
  now hands real `segment`/`target_dur` manifests, proving the default
  `ambient=True` path survives real — but audioless, since `reframe` renders
  with `-an` — segments end-to-end. **796 tests green** (+8 skipped,
  unchanged from pacing). **Correction:** the pipeline-map's old "blocked by
  extract per-ep audio passthrough" note was stale — `extract` already
  preserves segment audio (§5.8), so no 5.8 change was needed; the ambient
  source is the preserved raw `ep{i}_raw.mp4` segments, never the silent
  locked clips. **Deferred → built (transition SFX sub-slice, see the entry
  below):** SFX (whoosh on transitions) — its own slice; shipped as a pure
  ffmpeg-synth whoosh (no asset) placed on major transitions.

- **transition SFX (§5.12 audio-mix, whoosh sub-slice) DONE (2026-07-15)** —
  plan `docs/plans/2026-07-15-transition-sfx.md` + design
  `docs/specs/2026-07-15-transition-sfx-design.md`. **Closes §5.12** — grows
  the music-spine mixer with a synthesized whoosh on the reel's major
  transitions, no assets shipped or downloaded. `scripts/lib/models.py`
  gains `ReelManifest.sfx: bool = False` — off by default (a deliberate
  stylistic accent, unlike the ambient bed which defaults on).
  `scripts/mix.py` gains `_whoosh(tmp_dir)` (ffmpeg `anoisesrc=color=pink` →
  `bandpass` → `afade` in/out swell, seeded and deterministic) and
  `_build_sfx(durs, tmp_dir)` (a cut is "major" when `max(neighbour dur) >
  _MAJOR_FACTOR * median(durs)`, throttled by `_MIN_GAP` between kept
  whooshes; synthesizes the whoosh once, `adelay` copies it onto each kept
  cut offset, `amix`es onto a silent base pinned to the reel length);
  `mix()` now composes up to three optional layers (music/ambient/sfx)
  across four cases — the music-only and ambient-only filtergraph strings
  stay byte-identical to before this slice (regression-pinned) — with the
  whoosh entering the final `amix` **un-ducked** (an accent, not
  background) at its own `volume`, trimmed to −14 LUFS by the unchanged
  final loudnorm. `scripts/build_reel.py`'s stem hook passes `segments`
  when `rm.ambient or rm.sfx` (SFX needs the episode durations even with
  ambient off) plus `ambient=rm.ambient, sfx=rm.sfx`. **Two real-ffmpeg
  proofs** (`tests/integration/test_sfx.py`): a whoosh-bearing stem still
  measures −14 LUFS, and the whoosh's frequency band measurably spikes at
  the one major cut's timestamp and nowhere else (placement, not just
  wiring). `deliver.py`/`check_reel.py` untouched — one pre-normalized stem
  in, same −14 gate. **812 tests green** (+8 skipped, unchanged from
  ambient ducking). **§5.12 audio-mix is now complete.**

- **safe-zones (§5.13) DONE (2026-07-16)** — plan
  `docs/plans/2026-07-16-safe-zones.md` + design
  `docs/specs/2026-07-16-safe-zones-design.md`. Closes the last unbuilt
  `check_reel` check — §5.13's **mechanical** half; the stage itself stays ◐
  until its editorial half lands (the spec's gate is "both parts green").
  `scripts/lib/safezones.py` — `SafeZone` config-spec +
  `SAFE_ZONES` platform table (`generic`/`tiktok`/`reels`/`shorts`, generic ==
  titles' 0.08/0.12) + `safe_zone_for`/`default_zone` + `subject_marks` (k=5) +
  pure `evaluate` (worst-offender). The subject→canvas projection
  `marks_at_times` moved from `scripts/storyboard.py` to
  `scripts/lib/geometry.py` (a checker must not import a driver; `storyboard`
  re-imports it). `check_reel.run` gains `geometry=`/`platform=`: with the
  frozen per-episode sidecars it projects each subject and tests it against
  the zone, reporting an **advisory** `CheckResult` (joins `_ADVISORY_CHECKS`
  with `beat` — reported, out of `overall`, no `ReelFailure`); `_NOT_IMPL` is
  gone (a geometry-less reel reports `not-checked`). `ReelEpisode` gains
  `path`/`meta`, `ReelManifest` gains `platform` (from `Spec.platform`);
  `build_reel` builds the geometry list once (invariant across colour/black
  reprocess — the route is frozen) and `edl_to_reel` wires the sidecars.
  `titles._Y_EXPR` now derives its margins from `safezones.default_zone()`
  (one authority; rendered exprs unchanged). No auto-fix actuator exists, so
  the check stays advisory by design. **835 passed / 8 skipped** (23 new
  incl. 1 real-ffmpeg proof in `tests/integration/test_safezones.py`).

- **cast → hero-pin (§6.1a ingestion half) DONE (2026-07-16)** — plan
  `docs/plans/2026-07-16-cast-hero-pin.md` + design
  `docs/specs/2026-07-16-cast-hero-pin-design.md`. Makes the manifest's `hero`
  pin mean something: **every** §5.10 pin form now resolves — a seed bbox
  (unchanged IoU match), a rule (`largest`/`leftmost`), an explicit track id,
  or a cast name matched by appearance descriptor — where before only the bbox
  did anything and a rule or cast name silently fell back to intent scoring,
  and `cast.json` (shipped with 5.2) was never read back by anything. Built:
  `scripts/lib/appearance.py` (**new** — `CAST_MATCH`/`build_descriptor`/
  `descriptor_dist`/`crop_and_mask`, moved verbatim out of `intake.py` so a
  driver need not import a driver; `HIST_BINS`/`DESCRIPTOR_LEN` live in
  `lib/footage` — the descriptor's shape is `cast.json`'s contract, and the gate
  path must stay numpy-free) + `scripts/lib/hero.py`
  (**new** — `resolve(hero, cast) -> HeroPin | None`, the one boundary; raises
  with a remedy on anything unresolvable, used both as `manifest.validate()`'s
  oracle and as the shell's real resolution, so validation and behaviour
  cannot drift apart) + `scripts/lib/models.py` (`HERO_RULES`/`HERO_KINDS`
  vocab, the frozen `HeroPin` config-spec, `TrackSpec.seed_bbox` → `pin`,
  `TrackMeta.pin_matched`) + `scripts/track.py` (`_rule_track`/`_id_track`/
  `_descriptor_track` rungs, masks now reach the tracker but are only read on
  the cast path, `build_route` dispatches every pin kind with **no
  fallback** — a pin matching nobody reports `pin_matched=False` and an empty
  route) + `scripts/lib/orchestration.py` (`is_seed_pin` **deleted**;
  `hero-unmatched` fires **before** `no-track` when a track existed and the pin
  missed it — the unmatched pin produced that empty route, so "hero never
  detected" would misdiagnose it; when the detector confirmed nobody at all,
  `no-track` wins instead, since the *detector* produced the empty route
  there, not the pin) +
  `scripts/lib/manifest.py` (`Manifest.cast` path field; `validate(m, cast=)`
  finally gates `hero`, using `hero.resolve` as its oracle — the `LayoutSpec`
  calque) + `scripts/lib/edl.py` (`EDL.cast`; `preflight` loads the registry
  **once** before the episode loop) + `scripts/lib/footage.py`
  (`Cast.from_dict` guards its own top level) + `scripts/process_episode.py`
  (loads the cast, resolves the pin, threads a `HeroPin` into `TrackSpec`) +
  `scripts/edit_plan.py` (`build_edl(cast=)`/`write_edit_plan(cast=)`/
  `--cast`). **Review-driven:** an exact descriptor tie (`d1 == d2`, including
  a perfect 0.0 double-match) is ambiguous, not confident — two tracks
  bit-identical to the pinned cast member is §6.1a mode 1's extreme case, not
  high confidence; `_rule_track` raises on a rule it has no implemented branch
  for rather than silently answering `leftmost` (the exact substitution this
  slice deletes everywhere else); `Cast.from_dict` needed its own top-level
  guard (a syntactically-valid but wrong-shape `cast.json` crashed
  `AttributeError` through preflight's narrow `except (OSError, ValueError)`,
  not caught by it). **Three more from the final review (2026-07-17), all
  registry-shaped — the pin was gated, the file behind it was not:**
  `validate()` now type-checks `Manifest.cast` (the one path field `from_dict`
  passes through raw, so `{"cast": 123}` reached `Cast.from_json` → `Path(123)`
  → a `TypeError` out of the soft gate; the load site needs the guard too, since
  it necessarily runs *before* `validate()`, which needs the loaded `Cast` as its
  oracle); `CastMember.descriptor` is checked against `DESCRIPTOR_LEN`, so a
  stale `cast.json` fails at load instead of passing every gate and detonating in
  `track.build_route` after every window was cut (`descriptor_dist`'s remedy was
  right, its *timing* was wrong — and its message promised a `3 * HIST_BINS`
  check it never made, now corrected to what it does); `Cast` rejects duplicate
  member names, which `resolve` used to answer by list order — a coin flip, and
  a plausible one, since intake dedups at `CAST_DEDUP=0.30` and a human names
  both surfaced crops "Lena". **Five more from completing that same review
  (2026-07-17):** the `hero-unmatched`-before-`no-track` ordering above became
  conditional on `features` (a segment the detector found nobody in now
  reports `no-track`, not `hero-unmatched` — see above); `hero.resolve`'s "no
  cast.json" remedy stopped naming a CLI flag (it is shared by three callers
  with three different registry spellings — `manifest.validate()` has no CLI
  at all, `edit_plan.py` has `--cast`, `track.py` has `--cast-json` — so the
  old "or pass --cast" text was wrong for two of the three and, on `track.py`,
  actively landed a reader in an `ambiguous option` argparse error; it now
  names the `cast` artefact/field instead) and `hero-ambiguous`'s detail text
  now splits on `pin_matched` (nobody pinned + a scoring tie ⇒ "pin a hero" is
  the action; a human's own pin tying two candidates ⇒ telling them to re-pin
  the same way would send them to re-run the exact match that just failed); a
  400-digit JSON int in a bbox pin no longer escapes `manifest.validate()` as
  a bare `OverflowError` (new public `models.is_bbox_coord`, the one
  finite-magnitude predicate `HeroPin` and `hero.resolve` now share); and
  `track.py --seed ''` — an unset shell variable's typical shape — is refused
  by `track._parse_seed` instead of silently downgrading a pinned run to a
  scored one. `tests/integration/test_cast_pin.py` (**new**) is the
  proof over real pixels — YOLO mocked (as every test in this repo mocks it),
  but the fake result carries a real BGR frame and a real model-space mask, so
  `crop_and_mask`, `build_descriptor`, `descriptor_dist` and the descriptor
  rung all execute for real. **§6.1a layer 3** (descriptor continuity
  re-match — intra-episode ID-switch repair) is a separate mechanism this
  slice does not build, but it is now **unblocked**: it needed the cast
  wiring, and the wiring has landed. **Correction (2026-08-12):**
  track-stitch (2026-07-28, see the Done entry above) has since landed
  against that same mid-episode ID-switch failure by a different
  mechanism — geometric overlap-vs-gap evidence and median-based
  joinability across track-id segments, not descriptor continuity. Whether
  it subsumes layer 3 or leaves a real remainder has not been re-assessed.
  **960 passed / 8 skipped** (936 at the slice's landing, +12 from the
  first three review fixes, +12 more from completing that review above).

- **reel-final editorial checks (§5.13 Slice A) DONE (2026-07-17)** — plan
  `docs/plans/2026-07-17-reel-final-editorial-checks.md` + design
  `docs/specs/2026-07-17-reel-final-editorial-checks-design.md` (branch
  `feat/reel-final-editorial`, commits `0f18c69`..`bcdedbf`). Completes the
  still-**mechanical** enumeration under §5.13's editorial half — three new
  checks, all **advisory** (measured + reported into the `ReelReport`,
  excluded from `overall`, never a `ReelFailure` — zero blast radius on
  loop-2/`reel_orchestration`/`build_reel`/`deliver`), mirroring `safe_zones`'s
  policy exactly: `key_action` (the tracked-subject bbox must not be clipped
  by the frame edge beyond `clip_tol`, via a new `geometry.extent_at_times`
  corner projection + `safezones.subject_extents`), `pad_bars` (non-`fill`
  filler bars well-formed — content rect inside frame, bars symmetric within
  `bar_symmetry_tol`; **structural**, read from the `path.meta` sidecar only,
  no pixels), `transitions` (adjacent-episode layout must not jump jarringly —
  a layout-jump proxy: `|Δcoverage| + centre-shift + a mode-change penalty`
  against `layout_jump_max`, read from `PathMeta` only). New module
  `scripts/lib/reel_final.py` (the three pure `evaluate_*` cores, importing
  only `lib.geometry`/`lib.models` — no driver import); `ReelCheckSpec` grows
  `clip_tol`/`bar_symmetry_tol`/`layout_jump_max`; `_ADVISORY_CHECKS` widens to
  `("beat", "safe_zones", "key_action", "pad_bars", "transitions")`;
  `check_reel.run` wires all three into the existing `geometry` block (no new
  CLI flag — they ride the same `--geometry` inputs `safe_zones` already
  consumes); `_UNCHECKED` gains three silent-path entries so a geometry-less
  reel reports `not-checked`, never a silent pass. **§5.13's gate is "both
  parts green", so the stage stays ◐** — this slice closes the mechanical
  enumeration under the editorial half, not the stage itself; the **agent
  editorial review** (Slice B — does the reel deliver SPEC's idea/mood/hook/
  ending/spine?) **remains open**, its own future spec → plan → implementation
  cycle. Pipeline tally unchanged: **14 ✅ · 1 ◐ · 1 ❌**. **1183 passed / 8
  skipped** (23 new).

- **reel-review editorial (§5.13 Slice B) DONE (2026-07-18)** — plan
  `docs/plans/2026-07-18-reel-review-editorial.md` + design
  `docs/specs/2026-07-18-reel-review-editorial-design.md`. **Closes §5.13** — both
  parts green, stage ◐ → ✅ (tally 15 ✅ · 0 ◐ · 1 ❌). The agent editorial review:
  at CP3 a fresh reviewer subagent judges the delivered reel against `SPEC`
  (idea/mood/hook/ending/spine/edl_completeness/trend_flavor) and emits typed
  findings, each routed to an existing fixer stage; the human disposes.
  `scripts/lib/review.py` — `Finding` + `Review` config-specs (`REVIEW_AXES`/
  `REVIEW_SEVERITY`/`REVIEW_ROUTES`/`REVIEW_CONFIDENCE` vocabs, `Review.verdict`
  computed property = revise iff any blocking, JSON round-trip, `to_markdown`
  blocking-first). `scripts/reel_review.py` — thin driver: `build_review` validates
  the reviewer's RAW findings (fail-loud on a malformed finding, nothing written) →
  typed `Review`, `write_review` → `REVIEW.json`+`REVIEW.md`, CLI `build`
  (`--findings` list-or-`{summary,findings}` → artifact) — the `selection.json →
  EDL.json` idiom. `skills/reel-review/` — the SKILL (build packet → dispatch
  reviewer → driver → human loop + routing) + `reel-reviewer.md` prompt template
  (the `requesting-code-review` calque); `montage.py` gains an **optional**
  `reel-review` Stage (`REVIEW.json`, checkpoint `final`, never `next`);
  `using-montage` CP3 invokes it. **Human-gated (§4.1)** — `check_reel`/`build_reel`/
  `deliver`/loop-2 untouched; no auto-fix actuator. **`trend_flavor`** is judged
  from general knowledge at forced `confidence=low` (no source until §5.4). Text
  stage — no ffmpeg golden (reel-brief's twin). **33 new unit tests; full suite
  1216 passed / 8 skipped.**

- **length re-time (Phase B tail) DONE (2026-07-18)** — plan
  `docs/plans/2026-07-18-length-retime.md` + design
  `docs/specs/2026-07-18-length-retime-design.md`. Closes the two auto-fixes
  the pacing design parked together in its scope decision 1
  (`docs/specs/2026-07-14-pacing-design.md` §10) — the last open items of
  **Phase B — music spine**, now ◐ → ✅. Both are the same move at two edges:
  the reel's target length re-times DOWN to what the footage actually
  delivers. **Fix A — `build_reel`** (commits `99864c5`, `c6d32f6`, `ba5e64d`,
  `e3c5dcc`, `2fa0258`): `ReelCheckSpec.length_retime_max = 1.0` (max
  shortfall absorbed, on top of `check_reel`'s newly-named `_LENGTH_TOL = 0.5`
  gate). `reel_orchestration.next_action` gained a 4th `length_retime_max`
  parameter (default `0.0` = pre-slice behaviour), a `ReelAction.retime` field
  and a `"retime"` kind, and `_shortfall()`. `build_reel` keeps the check spec
  in a round-scoped local, adopts `action.retime` BEFORE dispatching on kind,
  logs it to stderr, and `continue`s to re-check — it never patches the
  report, so `deliver`'s hard gate is satisfied by a report the checker
  genuinely produced. **Fix B — `edit_plan`** (commit `5b851ba`):
  `_back_edge_target` sets a paced EDL's `target_dur = min(realized footage,
  spine.target_dur)`; an under-fill re-times down (the montage §4.1
  pacing-gate back-edge), an over-flow clamps to the fragment, both logged.
  **Proof** (commit `460d120`): two real-ffmpeg integration tests — a
  within-band shortfall delivers with a re-timed target; past the band
  escalates. **Load-bearing invariants:** the band is **one-sided** — only a
  SHORTER reel is absorbed, since `mix.mix` refuses a stem longer than the
  analyzed music fragment and `build_reel` cuts the stem at the master's real
  duration, so re-timing UP would trade a clean stop-and-report for a hard
  raise in the mixer; loop-2 stays **mechanical** (locked clips, frozen
  routes, no re-cut, no reach-back into `extract`/`edit_plan`); the delivered
  `reel_report.json` states the re-timed target because `check_reel`
  genuinely **re-ran** — re-checked, never patched; **escalate-wins
  survives** — a capped or unfixable failure alongside an absorbable
  shortfall still escalates, and the pending re-time dies with the round.
  **A bonus fix:** a paced over-flow EDL with no explicit `target_dur`
  previously fell through to `sum(ep.dur)`, passed the length gate, and hit an
  uncaught `ValueError` inside `mix.mix` after a full picture pass — the §4
  clamp turns that into a clean stop-and-report at the reel gate. The final
  whole-slice review found the mirror of that same hole still open — the
  absorb's one-sidedness was anchored to `target_dur`, not to the music
  fragment, so a `target_dur` above `music.duration` could still carry a
  master into `mix`'s raise; `build_reel` now preflights the two and refuses
  an unmixable manifest before any ffmpeg (design §6). **1237 passed / 8
  skipped** (19 new unit + 2 new real-ffmpeg integration tests).
  **Deferred:** re-picking `MUSIC.start_offset` via librosa (`beats.
  choose_offset` stays the manual rung); re-cutting footage inside loop-2;
  auto-fixing an over-length reel; re-deriving a truncated `Spine` for
  `PACING.json`; librosa section detection / phrase-aware grouping.

- **cap-3 parallel episode fan-out (§5.1's last sub-item) DONE (2026-07-18)** —
  plan `docs/plans/2026-07-18-cap3-fanout.md` + design
  `docs/specs/2026-07-18-cap3-fanout-design.md`. **1259 passed / 8 skipped**
  (**+22**: 2 fixture pins, 2 `ensure_model` + 1 MODEL-drift pin, 6 `jobs`
  validation, 6 pool, 3 failure-channel, 2 CLI).
  `scripts/edl_to_reel.py`'s sequential per-episode
  loop becomes `ThreadPoolExecutor(max_workers=jobs)`, default
  `DEFAULT_JOBS = 3`, exposed as `--jobs`. **Stage 5.1 now has no open
  sub-items.**
  **The number was measured, not inherited.** The repo's own docs disagreed:
  montage §5.10 said three saturate the box, `build_reel.py:88` said one does.
  A spike ran six real 2.5 s windows from `MVI_3739` through the full
  `process_episode` (YOLO11-seg → reframe → check → storyboard) at each
  concurrency on a 14-core M-series box: **41.1 s → 27.4 s (1.50×) → 24.2 s
  (1.70×) → 24.4 s (1.68×)** for jobs 1/2/3/4. The knee is exactly 3; at 4,
  per-episode latency reaches 1.85× for no throughput. §5.10 was right;
  `build_reel`'s comment was the wrong one and is corrected in place.
  **Three decisions.** *Threads, not processes* — `process_episode` is torch plus
  subprocess ffmpeg, both of which release the GIL, and the 1.70× is a thread
  measurement. *Run every episode, report the lowest index* — a failing episode
  no longer short-circuits later ones (a deliberate behaviour change, pinned by
  its own test), and the finding is chosen by INDEX so it never depends on
  thread scheduling; a raised setup error keeps its **own type** (`add_note`
  carries the episode) because `edl_to_reel`'s docstring contracts those as
  `ValueError`. **The final review caught the subtle half of this:** the first
  implementation drained the exception channel fully, *then* scanned statuses —
  giving each channel its own lowest-index rule but none *between* them, so a
  raise at episode 2 beat a routable `stop_and_report` at episode 0 and a caller
  branching on `result["status"]` got a traceback instead of a finding. One loop
  over the indices now decides both, and both orderings are tested.
  *`edl_to_reel` only* —
  loop-2's reprocess batch is one or two culprits and was hardened days earlier.
  Named `jobs`, not `cap`: `cap` already means loop-2's reprocess cap
  (`EDL.cap` → `ReelManifest.cap`), read a few statements below.
  **New §12 landmine, required for correctness:** ultralytics auto-downloads a
  bare model NAME on first use, so N cold workers race to write one weights
  file — silent corruption, not a raise. `track.ensure_model` warms every
  distinct model before the pool. A second, subtler entry followed from it: a
  unit test that fakes `process_episode` does **not** thereby avoid ultralytics,
  because the driver calls `ensure_model` itself — left real, `tests/lib/`
  imported torch and would have downloaded 6 MB on a cold CI cache, invisible on
  a dev box that already has the weights. The fixture stubs it.
  **Review-driven:** the fixture's `dict(pe_results or {})` silently coerced the
  old list shape (a one-element list holding a 2-key result dict becomes
  `{"status": "problems"}`, after which every episode falls through to
  `mechanical_pass`) — it now raises, because the coming "every episode runs past
  a failure" test would otherwise have passed hollow. The final review also found
  that the three real-ffmpeg SP1/SP3 goldens had silently acquired a torch
  dependency for the same reason as the unit tier, downloading weights into the
  **repo root** (ultralytics falls back to the CWD when its configured
  `weights_dir` is absent) past a `.gitignore` that only covered `models/`; they
  now stub `ensure_model`, and `yolo11*.pt` is ignored. A `track.MODEL` ==
  `manifest.DEFAULT_MODEL` pin was added: the driver warms the former while every
  worker builds the latter, and drift between two independent literals would
  reinstate the very race the warm-up removes.
  **Mutation-verified three times:** the barrier test goes red under
  `max_workers=1`, the exception-type test goes red when the bare re-raise is
  replaced by a wrapper, and the channel-precedence test goes red against the
  two-pass code.

- **fit-solid (§7 misc-engine, slice A) DONE (2026-07-18)** — plan
  `docs/plans/2026-07-18-fit-solid.md` + design
  `docs/specs/2026-07-18-fit-solid-design.md`. **1304 passed / 8 skipped**
  (+45 over the 1259 baseline). Makes the background filler a real parameter
  and ships the rename that had to precede it: **`fit-blur` → `fit`**, atomic,
  no alias (the `TrackSpec.seed_bbox → pin` precedent) — a second filler would
  otherwise force an EDL author to write `{"layout": "fit-blur", "background":
  "solid"}`, contradicting itself, with the half that wins (`background`) not
  the half read first. `BACKGROUNDS` gains `solid`; `LayoutSpec` gains
  `background_color` (default `"black"`, validated exactly like `border_color`
  — non-empty, none of `,:;'[]\`); `fill` refuses any filler but blur, since it
  covers the canvas edge to edge and a filler would be an inert setting that
  reads as if it did something. The colour rides the whole authoring path —
  `LayoutSpec` → `ResolvedLayout` → `Manifest` → `EDLEpisode` →
  `to_manifest_dict` → `process_episode`, plus `reframe.py`'s
  `--background`/`--background-color` CLI flags — so it is authorable from
  JSON, not only from Python (a review-caught gap: `process_episode`'s own
  `LayoutSpec` construction had zero coverage of the hop and would have
  silently rendered every authored colour as the default). `PathMeta` gains
  `background`, read from a missing sidecar key as `"blur"` — a one-key
  exemption from the sidecar's otherwise-strict integrity check, justified
  because `blur` was provably the only value the field could ever have held
  before this slice. `reel_final.evaluate_transitions` keys its layout-jump
  penalty on the pair `(mode, background)` instead of `mode` alone, since a
  `(fit, blur)` → `(fit, solid)` cut leaves the mode untouched while the pad's
  appearance changes hard; advisory, so no gate verdict moves.
  **Two landmines, both measured rather than reasoned — the most transferable
  part of this slice, full writeup in design §12:** (1) `color` is an
  **infinite** source, and **both** obvious ways to end it are wrong.
  `overlay=…:shortest=1` terminates but truncates **exactly one frame** off
  every render at any rate (golden fixture: source 95 frames, blur 95, solid
  94; reproduced on synthetic 1s/3s/5s sources) — enough on its own to eat
  `check_reel`'s entire 0.5s length band across ~30 solid episodes. Bounding
  the *source* instead with `color=…:d={duration}` is necessary but **not
  sufficient**: `overlay` inherits the synthesized background's timebase, and
  a 3s/30fps clip renders as 1536s (`container_tb / fps` = 15360/30 = 512).
  The fix is `-t {duration}` on the **output**, applied unconditionally to
  every layout. **The trigger is an exact rate match, not a frame rate** —
  integer rates (24/25/30/50/60) blow up, NTSC fractional ones do not, and
  this repo's 59.94fps fixtures survive only because `f"{fps:.6g}"` mangles
  `60000/1001` into `59.9401` — a **formatting accident**, so a future
  29.97fps fixture added to "cover another rate" would prove nothing (an
  integer-rate proof is the only kind that can see this failure at all). The
  same infinite-source hazard is why `proc.run` now carries a default timeout
  (`DEFAULT_TIMEOUT_S = 900.0`) and raises instead of hanging — measured
  90s-and-killed against a 0.8s normal run, on a machine with no
  `timeout`/`gtimeout` binary to bound it from outside. (2) `background_color`
  reaches an ffmpeg argument and carries `border_color`'s injection surface —
  same guard, because a colour string is not a safe literal just because it
  is short. **Real-ffmpeg proof:** a solid render terminates with duration
  matching the source to within half a frame period, at an **integer** frame
  rate (not just the 59.94fps golden ride — that rate class is exactly what
  the timebase landmine does not trigger on) — `tests/integration/test_reframe.py`;
  a pad pixel is the requested colour, and the same frame under `blur` differs
  — `tests/integration/test_layouts.py`. **Review-driven fixes beyond the plan's own tasks:** three
  test-strength gaps a mutation pass caught with the whole suite still green —
  `proc.run`'s timeout kwarg was asserted as "a positive number" but never
  exercised end-to-end; `-t` being unconditional (so no future filler can
  forget it) had no test forcing it off; and `_background_args`' exhaustiveness
  raise had no test bypassing `LayoutSpec`'s own vocabulary gate to reach it
  directly. **Deferred (by design, non-goals §9):** gradient fill, an
  auto-derived background colour, `split`, `pan`, any `fit-blur` alias.

- **pan (§7 misc-engine, slice B) DONE (2026-07-19)** — plan
  `docs/plans/2026-07-19-pan.md` + design `docs/specs/2026-07-19-pan-design.md`
  (branch `feat/pan`). **1400 passed / 8 skipped** (+96 over the 1304
  baseline). Gives the crop's x(t) a second, *declared* source: a
  constant-velocity pan generated from two fractions of horizontal freedom,
  used *instead of* a tracked route. **Not a layout, despite sitting in the
  design's §7 five-names table** — the layouts model already gives `pan` the
  identical row to `fill` (canvas-aspect crop, whole-canvas rect, no filler),
  so this slice touches `LayoutSpec` not at all; what distinguishes a pan is
  where the crop's x(t) comes from, a motion-source question. Built:
  `PanSpec` (`scripts/lib/models.py` — two fractions `start`/`end` of
  `freedom = src_w − crop_w`, wire keys `from`/`to` since `from` is a Python
  keyword, direction is the sign of `end − start`, no direction vocabulary);
  `reframe.generate_pan_path` — a pure generator with **four** refusals
  (`freedom <= 0`, `dur <= 0`, `x0 == x1` after rounding, `v > max_speed`) and
  deliberately **no smoothing** (`pathsmooth` is for observation noise; a
  generated line has none); `reframe()`'s pan branch, where `route_path`
  becomes optional and **no route is read, and none is written**;
  `PathMeta.pan` — the one-bit provenance the sidecar carries, read with the
  same `.get`-based one-key exemption `background` took; `check_episode`
  branches framing to `editorial-only` and continuity to `not-checked` under
  a pan (jitter/length/black_frames keep running — they judge the rendered
  clip, not an observation); the manifest gate's two refusals (a
  `lead`/`break` composition, since a pan consults no subject; a `hero` pin,
  since a pan follows nobody) with `motion` deliberately **not** refused (the
  canonical pan is `motion: static` *and* a pan — a still subject, a moving
  frame); `process_episode` skips tracking and the contradiction gate outright
  under a pan (a real saving — a whole YOLO pass — and the honest statement
  that no observation exists) and treats a generated path as **not
  retryable** (the ladder's one lever, `max_speed`, is only a ceiling for a
  pan, so a retry would re-render byte-identical pixels, or worse, break on a
  damped ceiling); the EDL authoring path (`EDLEpisode.pan` → `to_manifest_dict`
  → `Manifest.pan`, riding the same rails `background_color` did); and a
  real-ffmpeg pixel proof (`tests/integration/test_pan.py`) that a `0→1` pan
  starts on one edge marker and ends on the other, with a centre-pinned
  control that sees neither.
  **Two measured blast-radius facts, not reasoned:** with `pan=None`,
  `reframe`'s emitted ffmpeg argv is byte-identical to before this slice; and
  a tracked episode's `report.json` is byte-for-byte identical before and
  after the whole slice. **Four landmines, all measured rather than assumed,
  full writeup in design §11/§12:** (1) `pathsmooth.smooth`'s rate limiter
  only bites near `max_speed`, so a realistic slow reveal (192 px/s) survives
  a full smoothing pass with **byte-identical endpoints** — measured: 11 of
  12 endpoint-based tests stayed green under that exact regression, so only a
  test that monkeypatches the smoother to fail on call proves the refusal.
  (2) An empty or fabricated `route.json` is not a neutral placeholder — an
  empty route already means "the tracker found nobody", a fabricated one
  makes `check_episode`'s composition check circular, and
  `checks.continuity([])` returns `pass=True` (its `zip` over an empty route
  never iterates), so the absence is not even loud. (3) `PanSpec` honestly
  refuses `start == end` in **fractions**, but cannot see the `freedom`
  those fractions get multiplied by — a span under half a pixel rounds both
  ends onto the same integer and renders a static frame nobody asked for;
  closed by `generate_pan_path`'s own `x0 == x1` raise, one level down, where
  the pixel arithmetic is visible. (4) `is not None` is not truthiness on a
  dict-valued optional — an empty dict is falsy, so `if m.pan:` silently
  skips validation in `manifest.validate()` and drops the key entirely in
  `edl.to_manifest_dict`; both mutations left the **whole suite green**.
  **Final Task 10 mutation battery: 18 checks against the finished tree, 0
  survivors** — including two escalation-order guards and both
  `is-not-None`-vs-truthiness sites found by review after the original
  14-check plan was written. **Closes §7's `pan` row** — see
  `docs/pipeline-map.md`'s misc-engine bullet for what's left (`split`,
  ~~stabilization's apply half~~ (landed 2026-07-20, see the Done entry below),
  ~~the tracking-degradation ladder~~ (landed 2026-07-21, see the Done entry
  below)).
  **Reel-level support was NOT part of the above — it landed after, as three
  more commits (Tasks 11-13, plan `docs/plans/2026-07-19-pan.md`), because a
  fifth consumer of `route.json` had been missed.** Task 10's audit (design §2)
  counted four readers; a fifth — `check_reel.run`'s geometry section — had
  already landed via two unrelated slices (safe-zones, 2026-07-16;
  reel-final-editorial-checks, 2026-07-17) before this design was even written,
  and nothing re-checked. `edl_to_reel` is the only multi-episode driver this
  slice's own authoring path builds, and every reel it built containing a pan
  episode crashed with `FileNotFoundError` — invisible to every test above,
  since all of them (this slice's own, and check_reel's) stop at a single
  episode. Found only by a final whole-slice review. Fixed by: `c1b3ffd`
  (`ReelEpisode.route: str | None = None` — `None` states a generated path has
  no observation to freeze; an empty *string* stays refused, since that is a
  caller who lost a path, not one who never had one); `caa6505` (`check_reel`
  reads each meta's `pan` bit before it will open a route, contributes an EMPTY
  mark list for a generated episode rather than dropping it — so
  `worst_episode` still names the reel's own index — and states an all-pan
  reel's coverage as `not-checked` instead of passing it vacuously); and the
  `edl_to_reel` fix itself (`route=None if md.get("pan") is not None else
  str(...)`, the same `is not None`-not-truthiness rule as landmine 4, a third
  instance of that exact substitution surviving elsewhere in this slice).
  Proved end to end by two new real-ffmpeg tests in
  `tests/integration/test_front_spine.py` — an all-pan EDL and a mixed
  tracked+pan EDL through the real `edl_to_reel` → `build_reel` → `check_reel`
  wiring, the level nothing exercised before, because
  `tests/lib/test_edl_to_reel.py` fakes `process_episode` entirely and a canned
  status dict never writes or fails to write a route file. **Final: 1415
  passed / 8 skipped** (+2 over the 1413 after `caa6505`, +15 over the 1400
  Task-10 baseline above). Mutation-checked: reverting the `edl_to_reel` fix to
  an unconditional route path turns **only** the two new tests red — nothing
  else in the suite depends on the value, because `check_reel` already branches
  on the meta rather than the route; the `is not None`→truthiness substitution
  stays unreachable here too, since the manifest gate refuses `pan={}` before
  `edl_to_reel` ever builds a `ReelEpisode`.

- **landmine lint DONE (2026-07-20)** — plan
  `docs/plans/2026-07-20-landmine-lint.md` + design
  `docs/specs/2026-07-20-landmine-lint-design.md` (branch `feat/landmine-lint`,
  commits `b02a467`..`908d2e2` plus this docs sync). **1491 passed / 8 skipped**
  (+75 over the 1416 baseline — the pan entry above records 1415 because it
  predates pan's own last fix commit `25ec48e`, which added one test). Closes the
  §11 charter item that three places in this repo committed to and none had
  built. The four §12 patterns that fail **silently** — `lutrgb`, an input-side
  `-ss` on a re-encoded window, an unbounded synthesized lavfi source, and
  `drawtext` without `fontfile=` — are now machine-checked at two layers, and
  `references/landmines.md` stops being a drifted second copy of §12 (17 entries
  against 26, one of them asserting something §12 had struck through as never
  true) and becomes a pointer to it.
  **Built:** `scripts/lib/lint.py` — pure, argv in, violation messages out, no
  I/O; `scripts/lib/proc.py`'s `run()` gains an always-on guard (never behind an
  env flag — a guard that is off in production does not protect production) that
  raises `ValueError` **before** `subprocess.run`, so it sees the *assembled*
  command including the graphs that arrive through a splat. `ValueError` and not
  `RuntimeError` deliberately: `proc.run`'s existing `RuntimeError`s say the
  ENVIRONMENT failed; a landmine says the CALLER is wrong.
  `tests/lib/test_landmine_scan.py` is the static half.
  **The static scan reads AST string literals, not lines — the plan prescribed a
  line-level scan and asserted the tree was clean. It is not.**
  `scripts/lib/color.py:1` and `scripts/check_episode.py:56` both name `lutrgb`
  in prose, documenting the ban at exactly the two places an author would look. A
  line scan cannot tell documenting a ban from violating it, and both escapes
  were worse than the problem — a path allowlist is forbidden by design §6, and
  deleting the documentation makes a landmine undocumentable at its own site.
  Reading the AST dissolves it: comments never enter it, and docstrings are
  subtracted by node identity. **The check measures *emission*, not *mention*** —
  which is what its name always claimed, and the two differ precisely where the
  codebase is most careful.
  **The rules are narrower than the slogans.** A `-ss` violation needs **five**
  conditions together (input-side seek · a `-t`/`-to` window · no
  `-accurate_seek` · no `-frames:v` · not a stream copy); a naive positional
  check produces four false positives out of seven hits on a clean tree, and this
  guard raises in production, so a false positive breaks a live render. The fifth
  condition arrived *after* the first implementation: the message and docstring
  both said *re-encoded* window while nothing checked for re-encoding, so a
  `-c copy` fast trim was flagged — a claim asserted but never verified. Every
  comparison is anchored, because ffmpeg's vocabulary is full of tokens that
  contain shorter tokens (`-sseof` ⊃ `-ss`, `boxcolor=` ⊃ `color=`, `seed=` and
  `pad=` ⊃ `d=`).
  **The choke point the whole runtime layer stands on is itself machine-checked**
  — the scan refuses any module under `scripts/` that imports `subprocess`
  outside `_MAY_IMPORT_SUBPROCESS` (`proc.py`, plus the two documented yt-dlp
  sites `catalog.py`/`fetch.py`). Design §2's "all 35 invocations funnel through
  `proc.run`" was hand-verified at design time — in the one slice whose entire
  thesis is that hand-verified invariants decay. **That constant, not prose, is
  now the authority on the list**, so the two copies cannot drift.
  **`REAL_SITES` grew from the plan's 9 to 22 fixtures**, with the filter strings
  printed from the real builders rather than hand-transcribed. It is the
  regression guard that matters: it proves the predicate matches the codebase
  rather than the slogan. Roughly **30 mutation rows** across the slice; one
  survivor, judged **equivalent** — dropping `[` from `_element`'s separators
  changes the verdict only on `testsrc=…[d=1]`, and ffmpeg link labels are
  identifiers, so that graph is invalid.
  **What this lint does NOT cover** (design §5, stated plainly because a lint
  believed to cover more than it does converts an unexamined risk into a false
  sense of safety):
  - **Ten test-side sites bypass `proc.run`.** Most are read-only ffprobe/raw-frame
    probes that cannot carry these landmines; the one that genuinely emits a
    filtergraph is **`tests/conftest.py:17`**, the session-scoped `sample_clip`
    fixture that roughly twenty tests measure their pixels against. It is correct
    today (`d=` on both sources **and** an output `-t`) and it is still a real
    blind spot — the fixture every pixel proof in the suite is measured against
    is the one command the guard cannot see. `scripts/` funnels through one choke
    point; `tests/` does not have to.
  - **Runtime coverage equals test coverage**, so a splat-assembled graph on an
    unexercised path is covered by **neither** layer. That is the residual hole
    and it is real.
  - **`SYNTH_SOURCES` is a five-entry denylist and it under-covers** — by a
    dozen other infinite lavfi sources (`nullsrc`, `aevalsrc`, `rgbtestsrc`,
    `yuvtestsrc`, `smptebars`, `gradients`, `cellauto`, `life`, `mandelbrot`,
    `allrgb`, `allyuv`, `haldclutsrc`). **`nullsrc` is one keystroke from the
    covered `anullsrc`.** These are misses, not false positives — the safe
    direction — but structurally the same flaw this slice was chartered to fix.
  - **A parameterless `-f lavfi -i color` is not detected.** `color=` and `sine=`
    carry a trailing `=` to disambiguate `color=` from `colorchannelmixer`, so
    the legal, infinite bare forms read clean. A deliberate trade-off, recorded
    because the code cannot express it.
  - **`drawtext` has zero real-argv corroboration on this machine.** This ffmpeg
    is built without libfreetype, so all of its integration tests skip and **not
    one** `drawtext=` argv reaches the predicate across the whole suite. That
    check is pinned by unit tests and by reading both producers — not by
    measurement. A drawtext-capable ffmpeg would close it.
  - **The static layer sees literals**, so a filter name assembled by `%`,
    `.format()` or concatenation would pass it. No such site exists today — every
    filter string in `scripts/` is a constant, an f-string, or a `join()` over
    those — so the completeness claim holds *for this codebase as it stands*, and
    the day someone builds a name a new way it stops holding silently.
  **The slice's most transferable lesson: twelve real defects were found by
  review, and none by the suite going red.** Four were **hollow tests** —
  assertions that held for a reason other than the behaviour they named (a
  `REAL_SITES` label crediting an exemption that never ran; `proc` tests that
  passed with the guard deleted; a real-tree scan asserting `== []`, which also
  passes when literal extraction is broken — now pinned by a positive control
  that requires a known-present filter name to be found). **The technique that
  found what neither the unit tests nor the mutation battery could was running
  the predicate over every argv the real suite issues (~700) and looking at what
  it flagged.** That is how a **masking pair** surfaced: `pad=` contains the
  substring `d=`, so every letterbox argument read as "bounded" and was exempted
  wholesale — a silent miss that was swallowing a false positive in the
  source-name boundary rule. Both mutation rows passed against a predicate that
  was wrong in two places, and fixing only the bound test would have converted a
  quiet miss into a **live raise on every letterbox render**. The two corrections
  had to land together, boundary first, so each commit is green on its own.
  Generalised: **when a check has an early exemption and a detector, a bug in the
  exemption can conceal a bug in the detector — so measure the predicate against
  the codebase, not only against its own fixtures.**
  **Drive-bys:** `tests/integration/test_pan.py:41`'s comment stated the seek
  landmine backwards (introduced by the pan slice, 2026-07-19) and is corrected;
  the two live links that promised `landmines.md` was a list
  (`references/ffmpeg-recipes.md`, `skills/process-episode/SKILL.md`) now point
  at §12. **Deliberately out of scope** (design §7): the even-`scale=`,
  crop-expression-ceiling and dependency-pin family, all of which fail **loud** —
  worth guarding eventually, but adding them would dilute this lint's claim, that
  it catches the landmines which do *not* announce themselves.
  - **Cleanup round (2026-07-20, whole-slice review, commit `c01618b` + this
    docs sync). Final: 1512 passed / 8 skipped** (+21 over the 1491 above). The
    review returned READY TO MERGE with nothing blocking; **all three code
    findings were false positives**, which §6 ranks as the worst direction for a
    guard that raises in production, so they landed before the merge rather than
    after. Two were the same defect one option apart: ffmpeg spells a video copy
    seven ways and `_VIDEO_COPY_FLAGS` knew two, so `-vcodec copy`,
    `-codec:v copy`, `-c:v:0 copy` and `-codec copy` each raised on a correct
    windowed command — re-opening the door §4.2 added condition 5 to shut, one
    spelling over — and `-vframes 1`, the alias every tutorial still teaches, was
    not read as a still grab. Both became `fullmatch` regexes rather than wider
    string tests, because `-acodec`/`-codec:a` end in the same letters and copy
    AUDIO while the video is re-encoded, which is exactly when the landmine
    bites; `-c:0`, bare `-frames` and `-frames:a` stay unmatched on purpose,
    since matching them would EXEMPT a re-encoded window.
    **The third was the fifth instance of the boundary family**, and the first to
    point the other way: `_SYNTH_RE` was anchored only on its left, and string
    start is where that anchor is weakest, because an `-i` value is an element
    too — so `-i testsrc.mp4` read as a synthesized source and raised. Only a
    bare basename bit; the same path written absolutely was clean because `/`
    sits in the lookbehind's reject set, which is precisely what kept it hidden.
    Argv position would settle it but a per-element scan cannot see argv
    position; **spelling can** — a real source is `name` or `name=params`, never
    `name.ext` — so an `=`-less name now needs a `=`, an element separator, or
    end-of-element after it. `color=`/`sine=` were left alone: their trailing `=`
    already spells that requirement, and widening them would have silently
    changed §5's recorded parameterless trade-off.
    **Docs corrections:** §4.3's prose said a source is bounded by a `-t` "on the
    output" while the code accepts one **anywhere** in the argv — the prose was
    wrong and the code right, because `scripts/mix.py:137` ships a `-t` *ahead*
    of its lavfi `-i`; the loose reading's price (a `-t` bound to input #1 leaves
    an unbounded input #2 reading clean, and still hanging) is now recorded in
    §5, along with two measured `drawtext` gaps — a miss when a later filter in
    the same argv element carries `fontfile=`, and the converse false positive
    when a literal `drawtext=` sits inside a quoted `text=` value. **And the
    arithmetic: §12 carries 26 entries, not 28** — the "17 against 28" claim was
    wrong in all three places it appeared (this file, the lint design §9,
    `references/landmines.md`); the 17 was exact. `lint.py`'s comment naming the
    uncovered infinite sources had drifted to ten of twelve and now points at §5
    instead of carrying a third copy — the drift this slice was already bitten by
    twice. Each of the three widenings was mutation-checked in isolation:
    reverting it turns its own new test red and nothing else in the suite.

- **ffmpeg baseline — Tasks 0–7 DONE (2026-07-20)** —
  plan `docs/plans/2026-07-20-ffmpeg-baseline.md` + design
  `docs/specs/2026-07-20-ffmpeg-baseline-design.md` (branch
  `feat/ffmpeg-baseline`, commits `04b7600`..`a789431` + this docs sync).
  **1530 passed / 8 skipped.** One ffmpeg install carrying every library the
  pipeline needs, resolved from a path `setup.sh` records — and a `setup.sh`
  that can no longer uninstall a working binary. Before this slice the box's
  homebrew-core ffmpeg carried neither `libfreetype` nor `libvidstab`, so §5.9
  assemble-draft, §5.16 titles and 5.2 intake's shake score were dead on it and
  three integration tests skipped permanently.
  - **The headline finding is why `setup.sh`'s repair branch was destructive,
    and it is not what the design first said.** The branch guarding
    `brew uninstall --ignore-dependencies ffmpeg` was
    `if ! ffmpeg -filters | grep -q drawtext`, read as "fires when drawtext is
    missing". It is a **tautology**: under the script's own `set -o pipefail`,
    `grep -q` exits at its first match, ffmpeg still has 20KB of a ~36KB filter
    list to write, takes `SIGPIPE` and exits 141, and `pipefail` promotes that
    to the pipeline's status — while a genuinely absent filter exits 1. Both
    arms are non-zero, `!` inverts both, so the check can never report
    "present" and **the uninstall ran on machines where the filter was there**,
    against an `--enable-shared` build that `openai-whisper` and `summarize`
    link. Measured 141 on 5 of 5 runs, 0 without `pipefail`. The branch could
    not have completed either: its own post-install verification used the same
    idiom *without* the `!`, so the guaranteed path was uninstall → compile a
    tap build → abort with a false "drawtext still missing". Registered as a
    **new §12 landmine** (counted, not trusted: §12 is now **27** entries, up
    from the 26 the lint slice measured) and rewritten as design §1; the
    replacement captures the filter list once and matches in-shell.
  - **Built:** `scripts/lib/ffbin.py` — `$FFMPEG`/`$FFPROBE` →
    `config/ffmpeg.env` → `shutil.which`, always an **absolute** path (a machine
    now carries two ffmpeg builds, and a log that names which one ran is the
    difference between seeing a mixed pipeline and inferring it), plus
    `has_filter`/`require_filter`. **The path is frozen at install, the filters
    are probed every time** (design §4): a stale path fails loud through
    `FileNotFoundError`, a stale *capability* record would fail silently — the
    §12 shape — for the ~50ms it would save, and memoizing was dropped on the
    same argument (a test forgetting `cache_clear()` passes for the wrong
    reason). 33 production argv literals (11 files) and 37 integration-test
    literals (16 files) moved onto the resolver.
  - **§5 was the load-bearing half, not tidiness.** Four sites asked "does this
    build have that filter" four ways. Move production onto keg-only
    `ffmpeg-full` and leave the three test guards plus `conftest.sample_clip`
    probing PATH, and they find the *slim* build, skip forever, and report green
    with three integration tests silently uncovered. All four now go through one
    `need_filter` fixture, which also owns both skip reasons (nothing resolves →
    skip, not error). Three machine checks stop the drift back: bare
    `"ffmpeg"`/`"ffprobe"` literals are banned in `scripts/` (AST scan, **exact
    equality** — prose says "ffmpeg" constantly and stays legal) and in
    `tests/integration/`, and **no test anywhere may spell `-filters`**, since an
    independent capability probe is precisely the trap. Filed as a *convention*
    check, deliberately **not** in `check_argv`: a drawtext graph on a build
    without libfreetype exits `No such filter`, which `proc.run` raises loudly,
    so widening the silent-corruption guard with it would dilute what a
    `check_argv` refusal means.
  - **`setup.sh` stops being destructive.** Both `brew uninstall` branches
    deleted outright rather than guarded — `ffmpeg-full` is keg-only (same
    version *and* revision as core ffmpeg, 8.1.2_1), so it installs beside core
    ffmpeg and nothing needs removing. It now verifies rather than assumes (both
    binaries executable, both filters really present) before recording
    `config/ffmpeg.env`, and pins **without** `2>/dev/null || true` — that idiom
    is why the pin the old comments credited with protecting the goldens had
    never once applied. `--with-vidstab` and `--with-fonts` are deleted; both
    fold into baseline (fonts are four small casks, and without them titles
    fails loud). `--with-demucs` / `--with-sourcing` stayed opt-in then — torch
    and yt-dlp as size, not capability — **superseded 2026-08-04: both folded
    into baseline** (see the setup-install-all entry). Three brew gates
    warn-and-continue so a
    no-brew box still builds its venv, which hoisting `need_brew` had silently
    turned into a hard requirement.
  - **Found by the docs sync (Task 6), beyond the plan's file list:**
    `scripts/lib/fonts.py` still emitted `bash setup.sh --with-fonts` as its
    **runtime** remedy for an uninstalled font — a fail-loud message naming a
    flag this slice deleted — on *both* of its raises, with
    `tests/lib/test_fonts.py` pinning that exact string. **The obvious repair is
    a hollow test, and the mutation check caught it:** retargeting the assertion
    to `match="bash setup.sh"` can never fail, because the stale
    `bash setup.sh --with-fonts` contains it as a substring. Restoring the flag
    left the suite green. The property needs both halves — the installer named
    **and** the dead flag absent — and both raises now carry it (three
    mutations, each killed by exactly one test).  Worse,
    `skills/footage-intake/SKILL.md` told the agent to check vidstab by running
    `ffmpeg -hide_banner -filters` itself, which on a keg-only install probes
    the *wrong build* — §5's trap written into the instructions. Five SKILL/spec
    sites in total plus two runtime strings; historical plans keep their
    original wording, per the `fit-blur`→`fit` precedent.
  - **Task 7 (the proof) is blocked on the user, not on code.**
    `config/ffmpeg.env` does not exist yet — `setup.sh` writes it and has not
    been run — so `ffbin` falls through to PATH and the 8 skips stand. After
    `bash setup.sh` the target is **2 skips, checked by identity**: `test_offset`
    (demucs, opt-in) and `test_sourcing` (an SSL failure unrelated to ffmpeg).
    Any surviving `test_draft`/`test_titles`/`test_intake` skip means the guards
    are probing the wrong binary — invisible in a count. The **goldens are the
    only real test of the design's same-version argument**; if one moves, that is
    a real pixel difference to record, not to re-pin away.

- **stabilize-apply (§5.2/§10 apply half) DONE (2026-07-20)** — plan
  `docs/plans/2026-07-20-stabilize-apply.md` + design
  `docs/specs/2026-07-20-stabilize-apply-design.md` (commits `9ffa33d`..HEAD).
  **1579 passed / 2 skipped.** `stabilize: true` now does something: a
  `vidstabdetect`/`vidstabtransform` pre-stage writes a stabilized copy of the
  segment, and BOTH the tracker and `reframe` read that file — never a filter
  inside `reframe`'s own chain, because the route is measured on unstabilized
  pixels, and a crop placed from it against transformed pixels would re-inject
  exactly the shake vidstab removed while `check_episode` kept confirming the
  framing regardless, since path and route are both in source coordinates and
  agree with each other; only the pixels would disagree (design §1).
  - **Built:** `scripts/lib/vidstab.py` (extracted from `intake.py`, its first
    consumer) — `require`/`detect`/`mean_shake`/`stabilize` + the `.trf`
    primitives, one shared `DETECT_ARGS` so `FOOTAGE.md`'s `shake` column and
    the pre-stage's `before` mean the same thing; `PathMeta.stabilized` fed by
    a keyword-only `reframe(..., *, stabilized=)` parameter (declarative — a
    fact about `src`, not an instruction `reframe` can act on);
    `ReframeSpec.stabilize` deleted outright rather than left refused; the
    manifest gate now calls `vidstab.require()` instead of hardcoding "not
    supported yet"; `EDLEpisode.stabilize` + the `to_manifest_dict` bridge
    (carries the key only when `True`); the `process_episode` pre-stage
    (after the preflights, so a manifest the layout cannot satisfy still
    fails in milliseconds; outside the retry loop, since stabilization is the
    loop's input, not one of its parameters); a frozen-route refusal
    (`stabilize=true` + a supplied `--route` → `needs_input`, since nothing
    records whether that route was measured on raw or stabilized pixels); and
    a `build_reel` fix so a reprocessed stabilized episode withholds its
    frozen route and re-tracks on the re-stabilized segment instead of
    dead-ending as `reprocess-failed`.
  - **`crop=black` → `crop=keep`.** The recorded recipe's `crop=black` fills
    the uncovered border with black, and under a `fill` layout the crop takes
    the source's full height, so that band lands in the delivered frame
    whole. `check_episode`'s black gate compares frame MEDIANS against a
    floor, and a few percent of the frame does not move a median — nothing
    would have caught it. `crop=keep` (also libvidstab's own default) removes
    the failure class instead of adding a check for it.
  - **What the proofs found, not just what they confirmed:**
    - The intake shake golden (`test_intake_real_vidstab_shake`) did **not**
      move when Task 1 unified the detect recipe at `shakiness=8`. Its only
      assertion is `shake >= 0.0` — a structural check with no pinned
      magnitude — and a check outside the suite confirmed why: on the
      synthetic `sample_clip` fixture, vidstabdetect's per-frame local-motion
      data comes back byte-identical across the entire `shakiness` range
      (1–10); only the `.trf` header's recorded parameter differs. The
      synthetic clip is too simple to expose what `shakiness` tunes — real
      footage is expected to differ.
    - `crop=keep` is proven on real pixels to leave no black edge, but the
      first version of that control **passed even against `crop=black`** — it
      controlled nothing. Two compounding reasons, both measured: (1) the
      aggregation — `band.max() > 16` passes as long as one bright pixel
      survives anywhere along an edge, and `crop=black` leaves a wedge, not a
      solid line; (2) the geometry — `zoom=2` pulls the outermost ~8px from
      real content, so the uncovered black band sits inset from the true
      edge, where reading only the outermost row/column never sees it. Fixed
      by reading a dark-pixel **fraction** over a 20px border **ring**, and by
      slowing the synthetic fixture's shake frequency (1.7 → 0.3): a fast
      oscillation is under-tracked, the correction is a few px, and `zoom=2`
      covers it — both crop modes then come out identical, exactly why the
      first version could not tell them apart. Calibrated over three
      rebuilds: `crop=keep`'s worst-frame border dark-fraction is
      0.0006–0.0069 against `crop=black`'s 0.3235, a threshold of 0.05 sitting
      cleanly between them. `test_stabilization_actually_reduces_the_shake`'s
      own margin on the same fixture: before ≈ 0.066, after ≈ 0.040, a ~40%
      reduction.
    - The frozen-route × stabilize collision (an open question the design had
      parked to final review) surfaced as soon as Task 8 wired `stabilize`
      into `to_manifest_dict`: `build_reel`'s reprocess loop was still passing
      loop-1's frozen route into a now-`stabilize: true` manifest, and
      `process_episode` correctly refuses that pair — so every reel
      reprocessing a stabilized episode dead-ended as `reprocess-failed`.
      Fixed by having `build_reel` withhold the route at the reprocess call
      for a stabilized episode (it re-tracks on the re-stabilized segment
      instead — one extra YOLO pass on the rare reprocess path) while leaving
      `ReelEpisode.route` itself populated, since `check_reel`'s geometry
      section still reads it.

- **tracking-degradation ladder (§6.1) DONE (2026-07-21)** — plan
  `docs/plans/2026-07-21-tracking-ladder.md` + design
  `docs/specs/2026-07-21-tracking-ladder-design.md` (commits `babad02`..HEAD).
  **1601 passed / 2 skipped.** `process_episode`'s reserved `"degraded": None`
  placeholder is now fed: an unpinned episode whose route comes back empty (or
  whose primary tracker is unavailable) falls to `scripts/lib/flow.py`'s
  optical-flow centroid tracker (cv2, no ML deps), then to
  `scripts/lib/keyframes.py`'s sparse marks + interpolation (the new
  `--keyframes` answer channel) — each rung stamped on `TrackMeta.degraded`
  (`None`/`"flow"`/`"manual"`). The identity-blind guard
  (`orchestration.flow_eligible`) keeps a pinned hero out of the flow rung
  entirely: an empty route under a pin stays `hero-unmatched`, never a
  motion-blob stand-in.
  - **Built:** `TrackMeta.degraded` + `DEGRADED_LEVELS`; `track.available()`
    (the rung-1 gate, symmetric with `flow.available()`);
    `scripts/lib/keyframes.py` (`interpolate`/`write_route`);
    `scripts/lib/flow.py` (`available`/`_centroid_bbox`/`build_route`, dense
    Farneback optical flow over real cv2 — the first runtime *tracker* use of
    OpenCV); the `process_episode` ladder wiring + `--keyframes` CLI flag.
  - **As-built fact worth recording:** `degraded` rides ALL post-tracking
    terminal results, not only `mechanical_pass` — a follow-up commit
    (`191be8d`) carries it onto the contradiction-`stop_and_report` result and
    both `escalate` results too, conditionally, the same shape as
    `stabilize_report`. Reason: a flow route's centroid is jittery on hard
    edges and reliably trips the `_UNFIXABLE` continuity gate, so the common
    outcome for a flow-rung episode is an **escalate**, not a
    `mechanical_pass` — restricting the stamp to `mechanical_pass` would have
    hidden the provenance in exactly the case a human most needs it. The
    integration proof asserts `degraded == "flow"` on an escalate result and
    `degraded == "manual"` on a `mechanical_pass` (the interpolated keyframe
    route is smooth by construction and clears continuity).
  - §6.1a layer 3 (descriptor continuity re-match — mid-episode ID-switch
    repair) is unchanged by this slice and stays its own slice.
    **Correction (2026-08-12):** track-stitch (2026-07-28) has since landed
    against that same mid-episode ID-switch failure by a different
    mechanism — geometric overlap-vs-gap evidence and median-based
    joinability across track-id segments, not descriptor continuity.
    Whether it subsumes layer 3 or leaves a real remainder has not been
    re-assessed.
  - **Follow-up (2026-07-21) — `--keyframes` answer-channel refusals.** The
    whole-slice review found the manual channel silently dropped its marks under
    two edge cases; a third of the same class turned up beside them. All three now
    hard-refuse at the input gate (`needs_input`, remedy-bearing, *before* tracking
    and the stabilization pre-stage), because `validate()` cannot see
    `keyframes_path`: **hero pin + `--keyframes`** (two identity mechanisms — the
    keyframes ARE the assertion, §1.1's mechanism-conflict, not flow's
    identity-blindness), **`stabilize: true` + `--keyframes`** (source-coord marks
    over stabilized pixels — the `stabilize + --route` coordinate-mismatch class,
    milder but still refused symmetrically), and **supplied `--route` +
    `--keyframes`** (competing route sources). One invariant: `--keyframes` drives
    the raw, unpinned, unstabilized, un-pre-routed segment — nothing else. Design
    §1.1/§2/§4/§7 amended; +3 integration tests. **1604 passed / 2 skipped.**

- **plugin packaging DONE (2026-07-22)** — plan
  `docs/plans/2026-07-22-plugin-packaging.md` + design
  `docs/specs/2026-07-22-plugin-packaging-design.md` (branch
  `feat/plugin-packaging`, commits `f92450e`..HEAD). **1611 passed / 2
  skipped** (+7 over the 1604 baseline: 2 launcher + 3 manifest + 2
  skill-convention tests). video-grid now installs and runs like an ordinary
  Claude Code plugin, and its skills work from **any** working directory —
  not only from inside the checkout.
  - **Built:** `.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json`
    — a self dev-marketplace naming `video-grid`, listing it with
    `source: "./"`. Install is two runtime commands plus two plugin commands:
    `bash setup.sh` (the venv/`ffmpeg-full`/fonts/weights runtime) →
    `/plugin marketplace add .` → `/plugin install video-grid@video-grid`.
    `SKILLS/` → `skills/` (the lowercase dir the plugin loader scans), with
    the 16 live `SKILLS/` references across `scripts/` docstrings and current
    docs repointed — the dated `docs/plans/`/`docs/specs/` keep their
    as-written historical spelling.
  - **`bin/vg` is the one launch chokepoint, and its `cd $ROOT` is
    load-bearing, not cosmetic.** It self-resolves `ROOT` from its own path
    (`bin/vg` ⇒ `dirname/..`), so it is correct from any `cwd`; guards the
    venv and fails loud naming `setup.sh` when it is absent, instead of a raw
    `ENOENT`; then `cd`s to `ROOT` before `exec`ing `.venv/bin/python -m
    "$@"`. The `cd` is the point of the design, not a style choice: almost
    all of this codebase already resolves its own paths off `Path(__file__)`,
    never `cwd`, so `PYTHONPATH=ROOT` alone would nearly have sufficed —
    except ultralytics resolves YOLO weights by **bare name** and
    auto-downloads a missing one **into `cwd`** (design §1.1, a §12-shaped
    silent trap: run from the wrong directory and it quietly re-downloads the
    weights into the wrong place, or races under cap-3 fan-out). The 16 skill
    call-sites across the 6 runner skills (`using-montage`/`music-source`/
    `music-match`/`pacing`/`process-episode`/`project-init`) now each resolve
    an absolute `VG=<skill-base>/../../bin/vg` and run `"$VG" scripts.X` with
    **absolute** footage/run/output paths — a relative one would now land
    inside the checkout, since the launcher `cd`s there first.
    `tests/test_skill_convention.py` lints the outcome (no skill may spell a
    bare `.venv/bin/python`), so a reverted call-site fails the suite, not
    just a manual read.
  - README rewritten for two audiences (Use / Develop), leading with an
    honest banner: the plugin ships the skills, `setup.sh` still provisions
    the runtime — both are required, and a plugin install alone cannot make
    a reel.
  - **Honest limits (design §4), stated rather than hidden:** macOS/homebrew
    only, inheriting `setup.sh`'s own limitation; no GitHub-remote
    marketplace yet — `/plugin marketplace add <github-repo>` would clone
    into the plugin cache and need the `.venv` rebuilt on every version bump,
    wrong for a multi-GB runtime, so the supported path stays the
    local-clone self dev-marketplace above; no LICENSE / `plugin.json`
    `license` field yet.

- **plugin runtime-resolution fix DONE (2026-07-22)** — plan
  `docs/plans/2026-07-22-plugin-runtime-resolution.md` + design
  `docs/specs/2026-07-22-plugin-runtime-resolution-design.md` (branch
  `fix/plugin-runtime-resolution`, commits `3ecd0db`..HEAD). **1615 passed / 2
  skipped** (+4 over the 1611 baseline: 3 setup-lint + 1 skill-convention
  test). Found by installing the plugin-packaging slice above for real: the
  first actual `/plugin install` `cp -R`s the whole repo into a runtime-less
  plugin cache — a Python venv does not survive a copy (`bin/python`'s
  symlink and `pyvenv.cfg`'s absolute paths break), so a skill deriving ROOT
  from its own (copied) base dir ran the cache's dead `.venv`, and `bin/vg`
  failed loud from there: neither the CLI nor the desktop app could actually
  run the pipeline as installed. The copy also carried 1.1 GB (the venv) on
  every install / version bump.
  - **Fix:** `setup.sh` now records the clone's absolute path to
    `${XDG_CONFIG_HOME:-~/.config}/video-grid/root`; the 6 runner skills'
    `**Launcher.**` preamble reads that file instead of deriving ROOT from
    their own base dir, resolving `"$ROOT/bin/vg"` (a missing file fails loud
    naming `bash setup.sh`). `setup.sh` also moves the venv external
    (`${XDG_DATA_HOME:-~/.local/share}/video-grid/venv`) and points
    `<clone>/.venv` at it with a symlink (migrating a pre-existing real
    `.venv` first) — `cp -R` preserves a symlink (measured: the cached copy
    is a 0-byte symlink that still resolves), so the plugin cache stays lean
    instead of carrying the venv. **`bin/vg` and its 16 skill call-sites are
    unchanged** — only how `VG` gets resolved moved.
  - **Corrects the packaging design:** §2.2's "a skill resolves ROOT from its
    own harness-given base directory" does not survive the copy-to-cache
    `/plugin install` actually performs, and §4 had scoped the recorded-root
    anchor to only a future GitHub-remote marketplace — the **local**
    `directory` marketplace decouples skills from the runtime too. Both
    sections now carry a **Correction (2026-07-22)** note pointing at this
    design.
  - **Testing:** the two new checks are lints, not runtime proofs —
    `test_setup_runtime.py` greps `setup.sh` for the three emitted operations
    (external XDG-path venv, `ln -sfn` symlink, recorded XDG-config root);
    `test_skill_convention.py` gains a third assertion that all 6 runners
    read `video-grid/root`. `bin/vg` and `tests/test_launcher.py` stay
    untouched and green — a `.venv` symlink is transparent to both. **The
    end-to-end proof — reinstall, then a foreign-directory montage brief
    reaching `out/REEL_v1.mp4`, plus `du -sh` on the cache showing no venv —
    needs the user's own `/plugin install`, same as the ffmpeg-baseline
    proof; it is documented as a user-run proof, not asserted by the suite.**

- **scenario-first pacing (§5.6 re-cut) DONE (2026-07-24)** — plan
  `docs/plans/2026-07-24-scenario-first-pacing.md` + design
  `docs/specs/2026-07-24-scenario-first-pacing-design.md` (branch
  `feat/scenario-first-pacing`, commits `c149f06`..HEAD). **1722 passed / 2
  skipped.** The §5.6 stage stops GENERATING slot lengths and starts FITTING a
  grid to the cuts the footage already fixed. The 2/4/8 beat ladder — which
  capped a slot at 4.6s and could not express a 6–9s surf ride — and its
  `build_spine` are **DELETED**, replaced by `fit_spine` over the new pure
  `scripts/lib/gridfit.py`: five grid **levels** (beat/half-bar/bar/2-bar/phrase),
  and `best_fit` picks the COARSEST whose lines the existing cuts reach inside a
  fixed **±half-beat** `allowance` (never ½ a LINE — that would be a different
  episode), via a CUMULATIVE left-to-right snap clamped twice (allowance ∧ the
  shot's room). Nothing fits → the least-bad fit is returned with every rejected
  level named, so the report can print the number that rejected each.
  - **The conveyor is inverted:** `montage.V1_STAGES` now runs **edit-plan (5.7)
    BEFORE music (5.5) / pacing (5.6)** — two-pass: build the cuts at their
    material length → pacing FITS a grid to them (`PACING.{json,md}`) →
    `edit_plan build --pacing` applies the fit. An episode's length comes from its
    own shot, and `_bind_pacing` REFUSES a slot further than a snap from its
    episode (the anti-truncation guard — the old code silently truncated a 7.3s
    ride into a 4.6s slot).
  - **Supporting pieces:** `FootageClip.room_after` (a shot's remaining room, one
    owner); `offset.best_offsets` (top-K in-point candidates for the fitter);
    `Slot.line`/`Slot.dev` (the line a slot was fitted to + its deviation);
    `edit_plan` `start_offset` (move an in-point later inside the SAME shot — dur
    still comes from the window, so it never lengthens an episode); and a new
    `scripts/lib/anchors.py` — a pure `anchors_from_curve` picker (advisory action
    anchors, thinned to the STRONGER of two close peaks) + an ffmpeg
    `measure_curve` (one frame-difference pass, `-ss` AFTER `-i`).
  - **Adopted from the parked `wip/montage-run-hardening` branch:** two hunks —
    `start_offset` and the shot-room helper (`room_after`) — landed here as their
    own reviewed slices rather than left stranded on the WIP branch.
  - **Review-driven amendments:** `FootageClip` validates scene_cuts/windows
    before coercing (fail-loud, not a silent bad type); `window_to_episode`
    refuses an out-point that leaves the shot; the off-grid pacing report lists
    each level once (de-dup) and is tested; `best_fit` skips a level's empty
    phases so a short beat grid can't crash the coarse sweep.
  - **Testing:** real-ffmpeg proof that a ride survives the fit at its own length;
    `gridfit` goldens pin exact fit numbers (stdlib-only, bit-exact). Task 14's
    8-check mutation battery ran — 6 bit their named test directly; two
    battery-SPEC errors (not coverage holes) were corrected: #4's named
    `test_fit_snaps_the_cumulative_cut_not_each_duration` used degenerate
    equal-1.9s data that could not distinguish cumulative from independent
    snapping (replaced with clamped, unequal data that now bites), and #7's
    `-ss`/`-i` reorder is caught by the runtime `proc.run` `_seek_order` guard via
    `tests/integration/test_anchors.py`, NOT by the AST literal scan (which cannot
    see an argv reordering — landmine-lint design §5).

## Next action

- **Cinematic-quality P3 continues — what's left after S3** (synthesis
  `docs/cinematic-quality-playbook.md` §3/§4 priority 3) — S1 (footage
  contact-sheet, DONE 2026-08-05) gave the edit-plan agent its first look at
  pixels; S2 (mood presets + shot-size variety, backlog #19, DONE 2026-08-06)
  gave the cut a mood and an objective it can be held to — `edit_plan build`
  now refuses a cut that takes zero of a shot size the mood's preset wants
  when the footage offers three or more. **S3 is now also DONE (intake motion
  sensor + pool-relative scoring, 2026-08-06, see the Done entry above)** —
  and it was **not** the `_motion_fit` re-tune this section, and S2's own
  design §14, predicted it would be. Scoring a real tuning pool falsified
  that premise: the sensor itself was wrong (`_motion` differenced the
  largest bbox's centre, so a crowd's person-swap read as movement — design
  2026-08-06-intake-motion-scoring §1.2), not merely the constant weighing
  it. `score` is now a pool-relative percentile from a new Phase-2
  `score_pool`, `motion` lost its 10× display gain, and window boundaries
  moved with the corrected activity curve. **#14 (editorial-constraint
  memory) is now also DONE (2026-08-07, see the Done entry above)** — a
  stated rule now has a home (`CONSTRAINTS.json`) and a gate
  (`write_edit_plan`) that binds it to every re-cut. **#3 (per-episode QC in
  subagents) is now also DONE (2026-08-08, see the Done entry above)** — a
  fresh judge subagent per episode reads a frame strip off the delivered
  clip, the storyboard, and a new colour-naturalness sensor, and writes
  findings against five axes (composition/colour/impression/path/hero); the
  pure gate refuses an incomplete, stale, or blocking verdict before
  `build_reel` ever runs, and the judge cannot write the digest that binds
  its verdict to the bytes it judged (governance #8, no waiver). **After
  this slice, only one item of P3 is still open:**
  - **The hero-conditioned re-scan** (S2 design
    `docs/specs/2026-08-06-mood-preset-variety-design.md` §14) — after cast
    naming, re-measure the windows holding a named hero cropped to their
    *own* bbox (not the largest person's) plus face visibility. Its own
    slice: face detection is a new model, a new download, a new
    `verify_runtime` gate. S3's per-track median displacement already stops
    a largest-person SWAP from reading as motion, but it still measures
    whichever tracks are present, not one named hero — a different, narrower
    question this item still answers.
  This is the active critical path — the north star (`docs/fixes-backlog.md`,
  2026-08-03) reprioritized ahead of the front-half items below, which stay
  open but are no longer next. **OR**
- **Cinematic-quality playbook priority 4 has started** — subject-anchored
  moves (fixes-backlog #17, DONE 2026-08-08, see the Done entry above) is P4's
  first slice, and it also closed the frame-moving half of #18: a `zoom` now
  rides the tracked route through the SAME composition rule every check
  already judges, and a `pan` is refused over any window intake measured as
  holding people. **#7 (the speed ramp) is now also DONE (2026-08-09, see the
  Done entry above)** — a `RampSpec` eases playback down to a cosine plateau
  around one moment and back up, retimed in a single `setpts`+`fps` ffmpeg
  pass as a pre-stage at extract (the same shape as vidstab's own pre-stage,
  and for the same reason), and `EDLEpisode.play_dur()` is now the length
  every pacing and reel-length consumer reads — closing the exact coupling
  the 2026-08-03 run broke, where a ramp changed the reel's length but only
  two of eight readers noticed. That also closes the speed half of #18, with
  its own visibility proof (mean frame-difference ratio measured at 0.391
  against a commanded `factor` of 0.40). **#9's P1 look half, and #18 in
  full, are now also DONE (2026-08-13, see the Done entry above)** — a
  reel-level `EDL.look` (plateau vignette + bookend fade) rides `deliver`'s
  one encode, defaulted per mood by `MoodPreset.look`, closing #18 alongside
  the parked `highlight_red` colour primitive and the `outline-bold` title
  style — every one of the five originally-named pieces (zoom, ramp, look
  filters, `highlight_red`, `outline-bold`) now carries its own real-ffmpeg
  visibility proof. **What remains of P4** (`docs/cinematic-quality-playbook.md`
  §4): **#9**'s P2 grade half (bias `match_grade`'s common target by mood —
  the long-deferred "mood LUT") and P3 image-treatment tail (film LUTs,
  halation, light leaks, chromatic aberration, letterbox, and now **grain**
  — measured and priced out rather than merely deferred: at the delivery
  profile's own crf 18, `noise=alls=8` already costs ×4.36 the file size,
  and the platform re-encodes it away on upload regardless); **#10** the
  cheap 3-frame preview to converge a grade/effect before a full re-encode —
  now also the named home for "does the look actually render", since
  `check_reel` runs on the master *before* `deliver` applies the
  vignette/fade/titles, so no gate today ever sees them; and **#5** (the
  authoring skill must enumerate every knob), which trails these since it
  documents whatever surface #9's remainder lands. ~~**Two out-of-scope gaps
  this slice found and deliberately did not fix**: `EDLEpisode` cannot
  author `smooth_window_s`...; and `draft.py` uses the canvas aspect where
  it needs delivery pixels.~~ — **both fixed by the housekeeping slice,
  2026-08-12** (see its Done entry above): `smooth_window_s` is authorable
  now, with a retry-ladder floor that stops a lag retry discarding it, and
  `draft.py` renders real delivery pixels (8×16 → 606×1078). **Two new
  findings the cinematic-look slice made, reported not fixed** (see its own
  Done entry above, and `docs/backlog.md`): `color.shadow_red_arg` has
  `highlight_red_arg`'s identical pre-fix sparse-anchor defect, worse
  (measured **−6** at `SHADOW_RED_MAX` against highlight_red's pre-fix −3);
  and `highlight_red_arg`'s shoulder formula is monotonicity-fragile near
  `pull ≈ 1 − knee` for `knee ≥ 0.7`, unreachable today (the one call site
  never passes `knee=`). **OR**
- **Front-half continuation — trend-scan, then the real-footage v1 gate**
  (`TRENDS.md` cache, §5.4 — low-priority/YAGNI) — the only front-half stage
  left now that SP1b (assemble-draft, DONE 2026-07-13) has shipped; once it's
  built (or knowingly skipped) the front half is complete enough to run the
  whole `using-montage` conveyor end-to-end on Sergei's real footage — the
  milestone the synthetic goldens stand in for today. **OR**
- **`split`** — the one genuinely remaining item of the design's §7
  five-names list (two clips → two rects; changes the manifest's shape). The
  three-parameter layout model was built to absorb it without a new code
  path, and it is the one that will actually stress that model, since it
  needs two sources — unlike `fit-solid` (2026-07-18) and `pan` (2026-07-19),
  both of which turned out to need no new layout code at all; see the two
  Done entries above. **OR**
- ~~**stabilization's apply half + tracking degradation**~~ — **both landed**:
  the apply half **2026-07-20** (see the Done entry above) — `vidstabtransform`
  now runs as a pre-stage in `process_episode`, feeding the same stabilized file
  to both the tracker and `reframe`, wired through the manifest capability gate
  and the EDL authoring path; and the **tracking-degradation ladder 2026-07-21**
  (see the Done entry above) — an unpinned episode's empty route (or an
  unavailable primary tracker) now falls to `scripts/lib/flow.py`'s
  optical-flow centroid tracker, then to `scripts/lib/keyframes.py`'s manual
  keyframes, each rung stamped on `TrackMeta.degraded`; *not* the reframe-param
  retry ladder in `orchestration.py`, which was already built. **OR**
- **the real-footage v1 gate** — run the whole `using-montage` conveyor
  end-to-end on Sergei's own footage. Every seam golden today is synthetic
  (`sample_clip` is a box, not a person, so the SP1/SP3 goldens honestly fake
  `process_episode`); the engine's own `MVI_3739` fixtures are the only real
  pixels in the suite. This is the milestone the synthetic goldens stand in for.
  **OR**
- **golden-canon armature** — the storyboard's dynamic-symmetry overlay (root
  rectangle + diagonals + reciprocals + the "eye" horizontals/verticals,
  `references/editing-canon.md`). Still unbuilt: `geometry.grid_lines` knows
  `thirds` and `phi` and **raises** on `golden-canon`, and `storyboard._overlay`'s
  palette has no entry for it — the vocabulary is accepted as a *static editorial*
  grid (`manifest.py:135`, `edl.py:69` both refuse it as a tracking target) but
  nothing draws it. ~~+ landmine lint~~ — **the lint half landed 2026-07-20**
  (see the Done entry above); the two were only ever paired here by proximity.

**Phase B is now closed (2026-07-18)** — the length re-time slice
(`docs/specs/2026-07-18-length-retime-design.md`) landed the last two
auto-fixes the pacing design had parked (§10): `build_reel`'s within-band
length-shortfall absorb and `edit_plan`'s pacing-gate back-edge. See the Done
entry above.

**Reel-loop deferrals still open** (design §8 non-goals,
`docs/specs/2026-07-11-reel-retry-loop-design.md`): `variety` auto-fix still
needs the front-half EDL fixer (`length` landed 2026-07-18 — see the Done
entry above); reprocess is sequential, not parallel; and the loop has no
resumability / Phase A.5 retry-state persistence.

## Deferred / open

> **The queue lives in [backlog.md](backlog.md) since 2026-08-12** — one file,
> every open item, with a priority, a status and a size. This section is kept for
> the history in its entries; when it and the queue disagree about what happens
> next, the queue is right. Anything newly deferred goes there, not here.

- ~~vidstab-capable ffmpeg (`bash setup.sh --with-vidstab`)~~ — **the flag is
  gone and vidstab is baseline since 2026-07-20** (see the ffmpeg-baseline entry
  above): `ffmpeg-full` carries `libvidstab`, so 5.2 intake's `vidstabdetect`
  shake score gets its filter from a plain `bash setup.sh`. It remains a **hard**
  runtime gate (`vidstab.require()`, extracted from intake's old
  `_require_vidstab` when `process_episode` became a second consumer). ~~The
  *apply* half (`vidstabtransform`) is what remains unbuilt.~~ **The apply half
  landed 2026-07-20 too** (see the Done entry above): a pre-stage in
  `process_episode`, never a filter in `reframe`'s chain.
- §6.1a layer 3 (descriptor continuity re-match — mid-episode ID-switch
  repair) was **unblocked** by cast → hero-pin (2026-07-16, see Done
  above): the cast wiring it needed had landed. As originally specified —
  a per-frame descriptor jump + x-teleport + area jump ⇒ split the route,
  re-match the pieces — it targets the same failure mode as a mid-episode
  hero ID switch on occlusion. **Track-stitch (2026-07-28, see Done
  above)** has since landed against that failure by a different
  mechanism: geometric overlap-vs-gap evidence and median-based
  joinability across track-id segments, not descriptor continuity.
  Whether stitch subsumes layer 3 or leaves a real remainder has not been
  re-assessed.
- ~~cap-3 parallel fan-out remains deferred~~ — **landed 2026-07-18** (see the Done
  entry). `build_reel`'s loop-2 reprocess batch stays sequential by decision, not
  by oversight: batches are typically one or two culprits, so the fan-out's 1.70×
  has little to bite on there.
- **Real-run findings** (defects/quality gaps from running on real surf footage)
  live in [fixes-backlog.md](fixes-backlog.md), not here — a living list added to
  during the 2026-08-03 review pass. Hero identity (colour-histogram descriptor →
  OSNet re-ID embedding) is **design-approved**; the rest need
  design/investigation. The synthesis — craft research + session verdict + the
  mood-preset idea, prioritized — is [cinematic-quality-playbook.md](cinematic-quality-playbook.md),
  the working doc we develop from.

## External assets (outside this repo)

- **Golden fixture source (plan Task 9.5):** session footage + window map at
  `/Users/serg/Downloads/untitled folder/REEL_SOURCES.md` — footage (`MVI_*.MP4`,
  `DJI_*.MP4`, ~128 files) sits in that same folder. `MVI_3739.MP4` (the long
  ride) is the suggested fixture source.
- The Jul 3–5 montage session that this design was reverse-engineered from
  produced Reel A (ODESZA) and Reel B (Billie Eilish); real-footage validation
  happens when Sergei re-montages that footage — user-driven, not a milestone.

- **ffmpeg baseline — Task 7, the proof (2026-07-20)** — `bash setup.sh` run against
  the rewritten script: verified both filters, recorded `config/ffmpeg.env`, pinned;
  core `ffmpeg` untouched and `openai-whisper`/`summarize` still installed. Suite
  **1539 passed / 2 skipped** — exactly the two predicted (demucs opt-in, an SSL
  certificate failure unrelated to this slice). The six drawtext/vidstab skips are
  gone, which is design §5's trap proven closed rather than merely argued. **No
  golden moved**, so §2's "same version, same revision" argument survives its only
  real test. What did break was better: `test_intake_real_vidstab_shake` failed on
  its **first-ever execution** — libvidstab writes a BINARY `.trf` (magic `TRF1`) by
  default while `_parse_trf` reads the ASCII serializer, so the shake path had never
  worked on any machine and no machine could see it. Fixed with the filter's own
  `fileformat=ascii` rather than a reverse-engineered binary reader (guessing that
  layout risks silently wrong shake magnitudes — the §12 class); `_read_trf` now
  checks the magic on bytes so `_parse_trf`'s fail-loud promise is reachable at all,
  which it was not while `read_text()` raised `UnicodeDecodeError` several frames
  earlier. See design §12.
