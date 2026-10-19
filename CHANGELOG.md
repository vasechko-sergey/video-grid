# Changelog

Releases of the **plugin** — the skills you install and the runtime they drive.
The top entry must match `.claude-plugin/plugin.json`; a test enforces that,
because the install path is version-keyed and an unbumped version lets a
reinstall keep serving the old snapshot.

Versioning rules are in
[docs/development-workflow.md](docs/development-workflow.md#versioning).
Per-subsystem detail lives in [docs/build-status.md](docs/build-status.md); this
file is the short "what changed for someone who installs it" list.

## 0.19.0 — 2026-10-19

- **Music with no bar grid still ends on its own grid.** When the analysed window
  carries no bar grid — most calm tracks — the outro fit now falls back to the beat
  grid under a 1.5 s fade instead of leaving the music to stop mid-phrase. `EDL.md`
  and the log say when the fit used beats. The second real run's first track had no
  bar grid, and the reel cut it off; the operator swapped the track.

## 0.18.0 — 2026-10-19

- **The brief sets the shot length.** `reel_brief --asl LO,HI` records the reel's
  average-shot-length band in `SPEC.asl`; it outranks the mood preset's band in the
  edit plan's report and length check (`EDL.md` says which band it read). `edit_plan`
  logs the band and names a cut whose average shot falls outside it, before CP2.
  The second real run's "calm" brief got `nostalgic`'s 2–4 s and the first plan cut
  longboard rides into 3.3 s pieces.

## 0.17.0 — 2026-10-19

- **The brief's hero balance is checked at CP2.** `reel_brief --cast-share equal`
  (or `NAME=WEIGHT` per hero) records the split in `SPEC.cast_share`; `edit_plan`
  carries it onto the EDL, and `EDL.md` gains a **Screen time** section — each
  hero's played seconds and share beside the brief's — with the same line in the
  log. A report, not a gate. The second real run's "both equally" lived only in
  `notes` and REEL_v3 shipped 55/45.

## 0.16.0 — 2026-10-19

- **A reel opens on picture.** The look's opening fade is its own number
  (`look.fade_in`; absent = the same as `fade`, so older EDLs render unchanged),
  and every mood preset now sets it to 0 — the second real run's hook opened on a
  black frame. The closing fade is unchanged. The music keeps a 20 ms anti-click
  ramp at its start.
- **The music closes on the bar line it was fitted to.** When the outro fit chose
  the reel's length as `line + fade`, the music's fade-out is the fit's own fade;
  it used to be the look's, so the fade started late (0.7 s on REEL_v5).
- `deliver --fade-in` and `probe look --fade-in`; the look gate checks each end only
  when it is declared.

## 0.15.2 — 2026-10-19

The second real run's retro (`docs/retro/2026-10-16-second-real-run.md`, 18
backlog rows) and its four P0 rows:

- A 9:16 reel from 1080p footage is delivered at **1080×1920**, not 1080×1922 —
  a sized delivery takes the canvas aspect, not the truncated integer crop.
- `titles build` drafts only the brief's on-screen text; it no longer puts the
  hook/ending notes (file names included) on screen.
- Music sourcing verifies HTTPS against certifi, so a python.org interpreter no
  longer fails every Deezer request.
- The Reels safe zone keeps the top 14% clear of the app header (was 8%) — for
  titles, and for `check_reel`'s advisory subject safe-zone check.

## 0.15.1 — 2026-10-13

- `check_reel`'s pre-mix loudness reason no longer reads "(silent reel)" on a reel
  that has music — the first real run's agent took that to mean the music was lost.
- The router tells the agent to read a stage's whole output (not `tail`/`grep` it),
  to keep the machine awake for a long run, and to have subagents write
  incrementally.
- The backlog now holds only what a real run showed or the user asked for; the old
  P3/P4 entries are parked in `docs/backlog-parked.md`.

## 0.15.0 — 2026-10-12

### Check thresholds are authorable — and a moved bar must say why

Eleven check thresholds had no authoring surface at all: no flag, no manifest field,
no file. The only way to move a bar was to edit `scripts/lib/models.py`, so a bar
calibrated on one shoot could be changed only by patching the engine — and the
mechanism written to catch a loosened gate, `provenance.spec_overrides`, had
nothing to report.

- **`GATES.json`, beside `project.json`, moves them.** Found by convention and read
  afresh by every `edl_to_reel` run that renders (and by `process_episode`'s own CLI
  when it is given `--project`) — never by a flag, because a flag can be dropped on a
  re-run and a dropped threshold flag reverts the bar in silence. Each entry is
  `{"value": …, "why": "…"}`. A missing or blank `why` is **refused at load**, as is
  an unknown name, a name authored somewhere else (each refusal says where), and any
  value the owning spec class itself rejects — with the file's own path in the
  message, and no fallback to defaults. With no file present every artifact is
  byte-identical to 0.14.1, with one named exception: `probe grade --geometry`'s
  `probe.json` gains `gates: {"status": "not-read", ...}` when the project cannot be
  resolved, so a prediction made against the default floor says so.
- **Eleven authorable, not twelve; six of them can stop a delivery.** The row that
  asked for this said twelve. `loudness_target` is not a bar — it is the value `mix`
  renders to, and a gate file can reach only the check that confirms it, so authoring
  `-16` would fail every reel with audio — and it is refused by name, with where it
  lives. Of the eleven, `black_floor`, `black_rel`, `entropy_floor`,
  `grade_residual_max`, `loudness_tol` and `length_retime_max` block (the last through
  `build_reel`'s shortfall absorb) and five are advisory. The partition is derived
  from the code (`models._ADVISORY_CHECKS` and each check's own threshold), not typed
  a second time, so a threshold added later joins the file the day it lands.
- **The reason is carried to the verdict it bought.** A moved bar is named, with its
  written reason, in the check's own detail (`report.json`'s `checks.<name>.authored`),
  in `REEL_v{n}.attest.json`'s new `gates` list (scope, whether the bar can block, the
  reason), in `montage status` (which also says which phase froze the set and whether
  the file has drifted from it) and `montage verify`. `probe grade` predicts
  `grade_damage` against the authored floor — the value only, with no `authored` row
  or reason — where it used to read the dataclass default and would otherwise have
  predicted a failure the gate would not raise.
- **New contract surface.** `ReelManifest.gates` (the whole authored set, both scopes,
  carried across the `EPISODES.json` round trip so a reprocessed episode is judged by
  the bar its siblings were; omitted when empty), `Attestation.gates`,
  `process_episode(gates=)`, and one new flag, `check_episode --gates PATH` — the
  standalone judge has no project to look beside. `check_reel` has no such flag: it was
  built and then deleted, because every reel threshold is read behind an input its CLI
  never supplies, so it moved nothing.
- **The spec classes now validate the thresholds they hold.** `black_floor` and
  `black_rel` had no guard at all and accepted `True`, `nan`, `inf`, `"6"`, `None` and
  `-1`; `nan` passed every `> 0` guard on seven further fields. Unreachable until
  something could author them. No default moved.
- **Not solved, and said so.** Authoring is not calibration: every default is still a
  first cut from one shoot. A reason is free text and nothing checks it is true.
  `GATES.json` is reel-wide, and phase 2 judges by the set phase 1b froze and never
  re-reads the file — but a hand-driven `process_episode --project` re-render does, so
  check `montage status`'s `gates.frozen.state` before one (`differs` means restore the
  file or re-run `--from-geometry`); a phase-2 refusal for that gap is filed P1. On a reel
  with no declared grade `entropy_floor` cannot fire (the graded and plain renders are the
  same render, so the ratio is exactly 1.0) and `grade_residual_max` read a zero residual
  on the one fixture it was measured on, so authoring either there changes nothing in
  practice. And `GATES.json` is the user's lever, not the agent's: the router's
  instructions say never to author an entry to get a finding past.

## 0.14.1 — 2026-09-29

- The `ReelEpisode.chroma` shape now has **one** validator, called both by the
  carrier and by `color_fidelity.shift_from_report` on its own return. The
  reprocess arm of `build_reel` assigns that return straight into the list
  `check_reel` reads without ever constructing a `ReelEpisode`, so one of the
  two inlets was ungated.
- **The instruction to tick a plan's checkboxes is gone, and a plan is not amended in
  substance once its slice ships.** Four documents told an implementer to tick them
  as each task landed — `CLAUDE.md`, `development-workflow.md`, `build-status.md`
  and `README.md` — and the instruction is deleted, not repaired. It was followed
  task by task once, by the first plan; at the close of their own slices, 53, 52, 31,
  37 and 14 % of the 91 plans that had landed were fully ticked, across five date
  bands, and the end state reads 61 of 91 only because one commit ticked 27 of the
  older ones retroactively. `development-workflow.md` now states, once, that spec and
  plan are kept in sync until the slice ships — the version-bump commit — and that
  after it a design is corrected in place while its plan stays the record of what was
  planned; what was *done* is carried by each slice's per-task commits.

## 0.14.0 — 2026-09-26

- `verify_runtime` now refuses a run whose **installed plugin disagrees with the
  clone it is about to execute**. The code and the instructions come from two
  different places — the Python from the clone the recorded root names, the skills
  from Claude Code's version-keyed cache — and nothing compared them. Measured on
  the machine this shipped from: the cache held 0.2.1 against a clone at 0.13.0,
  392 commits, all fourteen skill bodies and all fourteen always-resident
  descriptions stale, and a *required* conveyor stage (`episodes-geometry`, the
  seam `match-grade` measures the shipped crop in) mentioned nowhere in the
  instructions the agent actually reads.
- The remedy is `claude plugin update video-grid@video-grid`, printed like every
  other gap. **Restart Claude Code afterwards** — the update rewrites the cache,
  it does not reload the skills a running session already holds.
- Not installed as a plugin? Nothing changes: a missing install record reads as
  "running from the clone" and passes.

## 0.13.0 — 2026-09-24

### The retry loop's record

A retry changes what shipped and the record did not follow it.

- `path.meta.json` now records the `max_speed`/`smooth_window_s` the render
  actually used. `max_speed` had no manifest field at all, and the retry ladder
  rescales both without touching the declaration — one jitter step moves 74 of 95
  crop-path samples by up to 5px, so a reader rebuilding from the manifest rebuilt
  a different geometry. Emitted only when it differs from the default, so an
  unauthored, un-retried episode's sidecar is byte-identical.
- `build_reel._predict` and `probe grade` rebuild a retried episode's plan from
  that record. Before this, the episode that had trouble was the episode that lost
  its `grade_faithful` gate, and `probe grade` refused with a remedy that could not
  restore the lost values.
- `episode_qc`'s source reading was the one consumer with no drift oracle: it read
  a retried episode's source through a crop the episode never shipped and reported
  it to the judge as that episode's own. It now plans with the recorded params and
  reports absence when the geometry cannot be shown to be the shipped one.
- `build_reel`'s reprocess writes its sidecars beside the record `EPISODES.json`
  names, instead of one level deeper under its own work dir. A re-pack after an
  automatic retry was producing a mixed packet — fresh pixels, stale report,
  storyboard, geometry and track record — invisible to the packet's `clip_digest`
  binding, because the stale half is not the clip.
- `episode_qc`'s evidence packet gains a third sidecar state, beside present and
  absent: a `path.meta.json` / `route.meta.json` / `report.json` that exists but
  will not parse — what a render that died mid-write leaves behind. It used to
  raise out of `pack()`'s loop and cost every LATER episode its packet; it now
  reads as `None`, exactly like an absent sidecar, with the reason carried in a
  new optional `unreadable` map (emitted only when non-empty, so every packet
  written before this stays byte-identical) — and the judge's template names it
  at both of its sidecar placeholders, filled by the stage's own dispatch step,
  because an unparseable sidecar is a reason to distrust the rest of that
  render's evidence and an absent one is not. The same corrupt-sidecar
  `RuntimeError` `rendered_params` raises by design no longer escapes
  `_source_reading` either: one episode's unreadable geometry now costs that
  episode a reading, not the whole packet run.

## 0.12.1 — 2026-09-21

Three latent defects closed and one backlog row closed by measurement. A reader
may no longer rely on an invariant that only a comment asserts.

- `check_episode._grade_damage` reads its verdict from the verdict's own dict
  instead of from the flat merge with the dE00 advisory, and the advisory can no
  longer return a `{status, reason}` absence at all — it raises, because the region
  it reads holds pixels by construction. Until now an advisory absence would have
  overwritten the discriminator and turned a BLOCKING entropy verdict into
  `passed=None`. Unreachable then; impossible now.
- `color.refuse_ungradeable_plane` refuses a stream whose `pix_fmt` ffprobe did not
  report, instead of grading it as 8-bit. Measured: a container whose codec this
  build cannot open still reports width, height, frame rate, duration and range
  from its own boxes, so four of the five probed values look healthy while
  `plane_depth("")` answers 8.
- `check_reel._chroma_spread_check` keys on `status`, the same discriminator
  `ReelEpisode.__post_init__` uses. A dict carrying both a `not-checked` status and
  a stray `delta_c` constructed fine and raised `KeyError` on read. Fixed in the
  reader, not the validator: `build_reel` hands the reader a plain list the
  validator never sees.
- `color.grade_chain`'s comma discipline is stated and pinned over all 1024 knob
  combinations. Backlog row R2.8 closes ⊘: a maximal LEGAL chain is 1206 bytes
  across 11 filters, every builder validates its own argument, and a comma error is
  a loud ffmpeg parse failure — so "1.5 KB of ffmpeg garbage" is not evidence of
  anything, and the retro section the row cites mentions none of it.

## 0.12.0 — 2026-09-17

**MINOR: a new contract field and a new advisory check.** `ReelEpisode` gains
`chroma`, and `check_reel` gains `chroma_spread`. No existing check's verdict
changes and nothing new blocks a reel.

- **Each episode now carries what the grade did to its COLOUR, not only its
  tone.** `check_episode`'s `grade_damage` advisory gains `crop_delta_c` /
  `crop_delta_h` — the same signed CIEDE2000 chroma/hue displacement already
  measured for the tracked subject, read instead over the whole crop (the
  one region every episode always has), and emitted only when the subject
  supplied the primary reading — a crop-fallback reading already IS the
  crop's, so a second key holding the same number would repeat itself under
  a different name.
- **`ReelEpisode.chroma`** carries that displacement (or a named absence)
  across the `EPISODES.json` boundary from phase 1 to phase 2, refused at
  construction if it is neither shape. `edl_to_reel` fills it from each
  episode's own report; `build_reel`'s retry loop replaces it when a
  reprocess re-renders an episode, so the value is never older than the clip
  beside it.
- **`check_reel` gains the advisory `chroma_spread`** — how far apart the
  reel's episodes are in what the grade did to their colour, reported as
  `per_episode`, `not_checked` (naming every absence, never a silent 0.0),
  `spread_c`, `spread_h` and `worst = max(spread_c, spread_h)` against
  `ReelCheckSpec.chroma_spread_max = 5.0`. **This is not a chroma target**:
  an absolute cross-episode chroma statistic cannot be separated from
  content on this footage (the same failure mode that got
  `color_across_cuts` deleted in 0.5.0), so this measures only whether the
  grade treated the episodes alike, never whether they end up looking the
  same. Advisory end to end — nothing blocks, and no chroma knob is
  authored anywhere.
- **Closes the last open half of backlog R2.1** — not by delivering the
  chroma target the row asked for, but by measuring that one cannot be
  built on this footage today: the pipeline's one automatic colour stage
  cannot move chroma at all, and the one referent every episode shares, the
  person, is too noisy a region to carry a target until it is a mask, not a
  bbox.

See [the design](docs/specs/2026-09-17-chroma-spread-design.md) for the
measurements behind the threshold.

## 0.11.0 — 2026-09-16

**MINOR: a reading names the pixels, the count and the baseline it came from.**
Report shapes change — `check_episode`'s `grade_damage` block and
`check_reel`'s `grade_faithful` detail. No threshold moves, no verdict changes,
no pixel moves.

- **The grade description says which pixels it read.** `report.json`'s
  `grade_damage` advisory gains `region` (`"subject"` or `"crop"` — what
  actually supplied the number), `region_fraction` (the fraction of the region
  **asked for**, so a fallback row carries the small number that is the
  evidence, never the crop's 1.0) and `region_fallback` (`null`,
  `"too-small"` under 1% of the frame, or `"no-route"`). The rule that
  resolves them is the SAME `lib/regions` rule the match-grade conductor
  authors a grade with, so the two cannot drift apart.
- **`background_delta_e` is the new contamination check,** present only when
  the subject supplied the reading: close to `delta_e` means the grade moved
  everything, far from it means it moved the subject and its surroundings
  differently. `background_fallback` rides beside it and is **present-or-null**,
  the way `region_fallback` is: `null` means the background WAS read and the
  number beside it is real. Only when the background cannot be read at all — a
  subject covering over 99% of the frame, ordinary on a tight reframe, leaving
  under 1% for the background — does it
  name the absence, and then `background_delta_e` is the key that is missing.
  After a SUBJECT fallback both keys are absent: the reading already is the
  whole frame, so there is nothing to contrast it with.
- **A scenery pan gains a reading it never had.** It used to report
  `delta_e: null` beside `delta_reason: "no source clip or no tracked
  subject"`; it now reports a real dE00 over the whole delivered frame with
  `region_fallback: "no-route"`. **`delta_reason` is deleted** — it was one
  string for several absences, and its first half could never be the cause,
  since the check had already returned when there was no source. Strictly more
  information, and named.
- **`dominant` is deleted.** It named which of luma/chroma/hue moved most, and
  it flipped on **three of the four** real episodes when the sample count moved
  from 5 to 3 — every flip with its top two components within 0.5, one an exact
  tie resolved by the order of a tuple. This release is what moves the count,
  so the field went rather than shipping the flips. The three signed components
  (`delta_l` / `delta_c` / `delta_h`) are the explanation and stay; there is no
  ranking of them. **If you read `dominant`, read the three.**
- **The reading now rides the render pair the verdict already uses.** Both
  sides come from `grade_damage`'s own (graded, plain) renders, at the same
  times, in the same geometry — instead of re-decoding the raw source and the
  shipped clip two lines below the pair it could have used. That removes **4
  decodes and 4 `ffprobe` calls per episode** for zero coverage loss, and it
  removes the CRF-18 encode from the number: the dE00 now describes the
  DECLARED grade, not the delivered file. Measured, the swap moves the reading
  by up to **0.84 dE00**, so a number compared against a pre-0.11.0 one is
  being compared across rulers.
- **`grade_faithful` states what it read over.** `check_reel`'s detail gains
  `frames`, the count actually read from the master per episode — `0` when no
  episode could be predicted. Not `color.FRAMES`: a constant echoing itself
  records nothing and would not move if the call changed.
- **The QC judge's instructions were rewritten for all of it** — read `region`
  before `delta_e`, because a reading whose region is `crop` is not a statement
  about the subject.

## 0.10.0 — 2026-09-15

**MINOR: an anchor is a measurement, and a measurement has a subject.** A new
author-facing contract file, and a changed `color_measure.measure_crop`
signature — it now returns `(profile, rows)`.

- **`REGIONS.json`, beside `project.json`.** Declare which region supplies which
  tone anchor: `{"anchor": "toe", "name": "wetsuit", "of": "subject"}`. `anchor`
  is `toe`/`mid`/`shoulder` (p5/p50/p95, not configurable — a declaration
  chooses the pixel set, never the percentile); `of` is
  `subject`/`background`/`crop`; `name` is your noun, carried into the report
  and never interpreted. Found by convention, with no flag — `GEOMETRY.json`
  now records the project file it was given, because a flag can be forgotten
  and a forgotten flag here silently reverts the grade to whole-crop anchors.
  Anything outside the two closed sets is refused at load, by name.
- **Absent the file, nothing changes.** Every anchor is the whole crop, the
  same EDL and the same target, byte for byte — pinned by a test that drives
  the real conductor over real footage, with a declared run as the control.
- **What it is worth, measured on the only real reel.** Taking the toe from the
  subject moves the common target's p5 by **−23.2** luma on the delivered clips
  and **−33.7** on the readable sources, against an `--eps` of 4.0; the mid
  moves +1.5 and the shoulder 0.0. The direction is deeper blacks — the
  "washed out, shadows gone" complaint arriving a second time, by a mechanism
  independent of the `nostalgic` preset's `tone_bias`.
- **Why it is not a bias you are adding.** The subject is 0.23% to 37% of the
  frame — a 161× spread inside one reel — so seven of the eight crops already
  read within about a code of their own *background*. The stage was measuring
  whichever region is largest, which on this footage is the water.
- **The first noun lost.** `skin` — a bright band inside the subject — is the
  worst cross-episode reference of everything measured (sd 34.3, against the
  crop's own p95 at 36.8), and the wetsuit band (14.9) loses to the plain p5 it
  would replace (10.0). There is no tonal `band` kind, on purpose.
- **Three named fallbacks in `MATCH.md` and `MATCH.json`,** one row per anchor
  with the region's own measured frame fraction: `no-route` (a pan generates its
  path, so there is no subject), `too-small` (under 1% of the frame), and a
  whole-episode `unorderable` that never repairs a measured profile. The report
  also tells "no declaration" apart from "could not look for one" — a
  `GEOMETRY.json` written before this release records no project, and a
  recorded project whose directory does not resolve from here is the same
  blindness.

## 0.9.3 — 2026-09-14

**PATCH: a skill's instructions are reachable from where it runs.** No contract,
no CLI behaviour, no pixel moves. What changes is whether an agent that loads a
skill can actually reach what the skill points at.

- Every one of the 14 skills carries the same resolution preamble: resolve the
  recorded clone root once, then run every step as `"$VG" scripts.X` and read
  every reference as `"$ROOT/references/…"`. Nineteen bare `references/…`
  pointers had no rule anywhere for resolving them.
- The launcher ban widened from one literal to a spelling set. It had tested
  `.venv/bin/python` only, so eleven `python -m scripts.X` examples walked past
  it — worst in `footage-intake`, whose CLI is the reason `bin/vg` must `cd`
  into the clone at all. Two more turned up in a second spelling (`python -c`),
  which `bin/vg` could not run: the launcher gained a `-c` passthrough.
- The router's 15-stage table is generated from `V1_STAGES` and pinned
  byte-for-byte. Its hand-written body had drifted the same way its chain had:
  15 live stages, 14 numbered blocks, and `reel-review` — required — buried
  inside the `deliver` block with no number of its own.
- The two biggest bodies become stubs plus pages: `using-montage`
  45 547 → 22 268 B (**−51%**), `edit-plan` 41 521 → 18 340 B (**−56%**).
  A stage is now one page at `references/using-montage/<stage-key>.md`, set-equal
  with the registry in both directions. Total corpus bytes rose 5.6% — the trade
  is that resident bytes are paid every invocation and page bytes only when read.
- A body budget of 26 KB, checked. It is set from what the split measured itself
  landing, not from a projection: every projection this design made was wrong in
  the same direction (−80%, then −69%/−74%, against −51%/−56%).
- The final review found the anchoring rule shipped as a claim rather than a
  check. Five prose pointers were still bare — including `edit-plan`'s
  **required read** of `editing-canon.md` — and `footage-intake`'s cast-writing
  step still named a bare `scripts.intake.write_cast(…)` with no way to run it;
  both are fixed, and two checks now hold them: every `references/…` pointer in
  a body or page must be written `"$ROOT/…"`, and the preamble's root path is
  rebuilt from `setup.sh`'s own lines and compared against the command all
  fourteen skills run. The command ban also widened to the `python3` and
  `python scripts/x.py` spellings that walked past it.

## 0.9.2 — 2026-09-12

**PATCH: a tool's purpose is re-derivable.** No behaviour changes, no argv
changes, no pixel moves. What changes is what the product can tell its own
operator.

- Every `scripts/*.py` exposes `build_parser()`; 47 help surfaces are now
  walkable objects rather than scrapeable text.
- 5 top-level parsers and **all 15 subcommands** gained a description.
  `probe grade --help` printed nothing about itself before this.
- 56 of 210 arguments gained `help` — 20 of 27 positionals among them.
- `references/tools.md`: a generated 47-row index, printed by
  `montage tools` and pinned byte-for-byte by a test.
- All 14 skill descriptions rewritten to trigger plus pointer plus a
  conveyor position rendered from `V1_STAGES`: 7244 → 4685 characters,
  ~1811 → ~1171 tokens, **−35%**, about 640 tokens freed in every session.
- Closes backlog R4.1, R4.2 and R4.3.

## 0.9.1 — 2026-09-10

**PATCH.** No flag, no stage, no required artifact, and nothing renamed — two
report fields nothing is required to read, and a blend term corrected from an
absolute fraction to a rank, measured as a no-op on the only real pool.
`score` moves in its third decimal, but `FOOTAGE.md` itself documents `score`
as a percentile within one footage set, "never an absolute quality bar." The
driving is unchanged **on the only real pool this shipped against** — the
design's §3.2 is explicit that on a mixed-presence pool the change is meant to
move the ordering, and `best` with it; that pool does not exist yet (§0.3/§6).

Two reports stop reading as a finished measurement when they were actually
silent. The window scorer's largest blend weight (`W_PRESENT`, 0.44)
separated **3 of 1508** windows on the only real pool and said so nowhere;
the variety census counts a person detector's silence as a `wide` shot, so a
people-free reel would read "the footage offers zero close-ups" about
footage that may be entirely close-ups.

- **`Footage.scoring`** — `{"windows": N, "separated": {term: count}}`,
  written by `intake` and rendered as one paragraph in `FOOTAGE.md`; `null`
  on a `FOOTAGE.json` written before this slice. `separated[t]` is the pool
  size minus the term's largest tie group, measured on the RANKED vector the
  blend actually consumes.
- **`VarietyReport.unmeasured`** — how many of the `available` census's
  windows carried no detected subject at all. They stay counted as `wide`
  (correctly — shot size is the subject's area fraction, and nothing fills
  an empty frame), but the count says how much of that bucket is the
  detector's silence rather than a measurement of the footage. Threaded
  through `edit_plan`'s census, the gate's log line, and a new `EDL.md`
  sentence rendered only when non-zero.
- **`present` becomes a pool-wide percentile rank**, joining `motion`/
  `shake`, instead of a raw fraction summed against two ranks. Measured as a
  no-op on the only real pool (Spearman 0.999039 between the two orderings,
  identical `best` set, identical top-8/top-30/top-100) — the argument for
  fixing it now, for free: on a mixed shoot a people-free window otherwise
  needs a mean rank of 0.786 across motion and shake merely to tie the WORST
  window that has a person in it.

Two plausible-looking statistics were measured and overturned before
shipping: "ranking presence changes 555 windows' scores" and "leave-one-out
says presence moves 493" both re-round a percentile rather than measure a
term's contribution — separation is the number that survives, because it
asks about the term's own input, not the downstream rounding. And
`shot_type(0.0, 0.0) == "wide"` is not the defect: a drone shot of empty
coastline really is a wide shot; the defect was one level up, in a census
that reads as a description of the footage rather than of what the detector
could see.

## 0.9.0 — 2026-09-09

Three reports stated a conclusion and recorded nothing about what they concluded
from, so nothing could tell a current one from a report describing a file that had
moved. Measured on the 2026-06 run: `MATCH.md` claimed 8/8 authored tone pairs
against an `EDL.json` carrying 5 (episodes 0/2/7 empty at a max Δ of 10, 6 and 49,
so not `within-eps` skips); `REVIEW.json` named a path whose file is dated a day and
a half after the review that approved it; and the QC evidence packet carried no
digest while the verdict stamped from it did.

- **`MATCH.json`** — the conductor writes the twin every other stage already had.
  `MATCH.md` is unchanged and byte-identical; the JSON carries the decisions the
  report renders, so its claim can be checked. The router's `match-grade` row keys
  on it.
- **`Review.reel_digest`** — stamped by `build_review` from the file on disk, never
  from the reviewer's claim. A review written before this field loads as *unbound*,
  which `montage verify` reports as such rather than as a failed comparison.
- **The QC evidence packet binds too.** `pack` records the clip's digest and
  `build_qc` refuses a packet that was made from a different render. This one
  refuses rather than reports: an unbound packet makes the verdict claim to bind
  pixels the judge never saw.
- **`deliver` is atomic.** The encode lands on `.REEL_v{n}.part.<container>` and is
  `os.replace`d into position, so a killed encode — the 2026-06 run lost one to a
  Bash timeout — consumes no version, is invisible to every delivery glob, and
  leaves the partial as the record that a delivery was interrupted.
- **`montage status` has a fifth stage state, `stale`** — the artifact exists and no
  longer describes what is on disk. It is not `done`, so `next` points back at it.
  Both checks hash nothing: match-grade compares the pairs its own report authored,
  reel-review compares version names. Bytes are `montage verify`'s business.

The instrument is deliberately the report's own claim rather than a digest of the
file it read. `match_grade` rewrites the EDL itself and `edit_plan build --pacing`
rewrites it again, so a whole-file digest would fire on the sanctioned rewrite as
loudly as on the wipe — and a gate that cries wolf gets its ceiling raised, which
is this project's own measured history on `color_delta_max` (12 → 44 → 56).

Closes R5.2, R5.3 and R10.9. Two of the retro's four R5 bullets were already closed
by 0.3.0, and R5.2's own claim that `episode_qc` held "the one binding" is now wrong
by four — `master_digest`, `reel_digest`, `music_digest` and `ReelGeometry.cuts` all
landed since it was written.

## 0.8.2 — 2026-09-08

Three artifacts in this tree are evidence handed to a judge — the QC frame strip,
the cast candidate crop, and the judge's own output contract — and each was
produced with no model of its reader. Backlog R10.1, R10.2, R10.6, R10.7.

Two of the four rows' premises needed correcting, and one correction is the
content of the slice:

- **R10.1's number was a misreading.** Today's code reproduces the run's strip
  byte-exactly (1800×406 = 6 cols × 2 rows of 300×203); the real per-frame picture
  is 95×169, and 83×147 after the reader's downscale. Nothing had regressed. 68 %
  of every cell was black because `CELL_H` is a 16:9 box and a delivered reel is
  9:16.
- **Six of eight judges say in their own summaries that they pulled their own
  full-resolution frames**, one of them hitting `magick not found`.
  `contact_sheet strip` already does exactly that and was named nowhere in the
  template. That, not the cell size, is R10.1.
- **R10.2 is not "too small".** Over the run's 15 candidates,
  Spearman(presence, crop area) = **−0.486**: the person with 479 s on screen was
  a 16×19 crop, the one with 32 s got 535×373.
- **R10.7 was larger than filed** — the Rules block named neither `suggestion`
  nor `axis`, and both refuse the whole run.

**Changed**
- `sheet.fit_layout` picks the column count whose cell picture is widest inside a
  named `READER_LONG_SIDE`; `sheet.tile`/`_fit` take the cell box as a parameter
  defaulting to today's values, so the footage contact sheet is byte-identical.
  `contact_sheet.STRIP_COLS` is deleted. On the run's own case, 83×147 as read
  becomes 313×556 with the sheet landing inside the budget — 3.8× linear, 14.3×
  area.
- `episode_qc`'s packet names the strip it never named and records `strip_px` and
  `storyboard_px`, the rendered per-frame size of each artifact. Reported, never
  gated — no threshold is introduced.
- `episode_qc.build` collects every validation complaint across every packet and
  raises once, with the episode and finding index for each. The refusal's strength
  is unchanged: one bad packet still refuses the whole run.
- `intake.surface_crops` surfaces the cluster's largest crop instead of its
  medoid; the descriptor is still the re-L2-normed centroid, so no downstream
  consumer changes. `cast_candidates.json` records `crop_px`. Phase 2 only —
  `CACHE_VERSION` does not move and no footage is re-scanned.
- The judge template states `axis` and `suggestion`, names the extraction, and
  distinguishes the timeline index from the composition evidence.
  `tests/test_skills_contract.py` machine-checks the Rules block against
  `EpisodeFinding`'s own fields.
- The final whole-branch review found the same two unnamed gates and the same
  raise-on-first-failure shape in the OTHER judge template:
  `reel-reviewer.md`'s Rules block named neither `axis` nor `suggestion` either,
  and `reel_review.build_review` raised on the first malformed finding instead
  of collecting every complaint. Both fixed the same way as their `episode-qc`
  counterparts, and `tests/test_skills_contract.py` now checks both templates
  against their own dataclasses.
- `build_strip`'s cell height rounded up like its width, undoing `fit_layout`'s
  own "never past budget" guarantee — a 16:9 clip at 13-15 frames landed one
  pixel-row over. Height truncates too now.
- `episode-reviewer.md` states what the judge should do when
  `{STORYBOARD_PATH}` reads `none recorded`, and names the reason its `$VG`
  preamble needs an absolute `--out` path (`bin/vg` `cd`s to the repo root
  first).
- `intake.save_cast_candidates` refuses a candidate carrying neither `crop`
  nor `crop_rgb`, naming its source and track id, instead of crashing inside
  `Image.fromarray`.

**Honest limits** — nothing here proves a judge looked; `READER_LONG_SIDE` is
inherited from `PER_SHEET`'s own comment and cannot be measured from inside this
pipeline (`fit_layout` maximizes *under* it, so a wrong budget is a suboptimal
sheet and never a broken one); and nothing creates pixels — if a person was only
ever 13 px tall, `crop_px` is what makes that reportable.

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
