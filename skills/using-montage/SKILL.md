---
name: using-montage
description: "Router — the montage conveyor's front door: a folder of raw footage plus a natural-language brief (\"a 9:16 reel from this trip, no music\") becomes a delivered reel. Use when the user wants a reel from footage — the router itself — it conducts every stage in order, stops at the three checkpoints, resumes a half-finished run, and names any stage it skips. Required — the entry point. Conveyor: project-init -> footage-intake -> contact-sheet -> [reel-brief] -> edit-plan -> [music-and-mood] -> [pacing] -> episodes-geometry -> match-grade -> [assemble-draft] -> [titles] -> episodes -> episode-qc -> deliver -> reel-review. Tool index: references/tools.md."
---

# using-montage (stage 5.1)

## Overview

You are the **conductor** of the montage conveyor. One invocation turns a footage
folder + a brief into a delivered `REEL_v1.mp4` — `<run>/reels/<reel>/deliveries/`
(see **The run directory**, below) — by running the stages that are already
built — you never re-implement a stage, and you never silently skip one. The
mechanical spans are CLIs; the judgment (what the brief means, which cut is right,
does the reel read) is yours and the sub-skills'.

**Core principle:** sequence, checkpoint, resume. Run built stages in order;
surface the three user gates (design §4.1); resume from wherever the run's
artifacts already reach; and when a stage is deferred/unbuilt, say so in one line
rather than pretending it ran.

## When to Use

Use at the **front** of a montage: raw clips exist and the user wants a reel. Not
for re-running a single stage — invoke that stage's own skill (`project-init`,
`footage-intake`, `edit-plan`, `process-episode`) directly. One `using-montage`
run covers the whole conveyor for one project/aspect.

## The Process

Announce on entry: **"Using using-montage to conduct footage -> reel."**

## The run directory

`<run>` is `<footage_root>/montage`. Inside it, **a folder is a lifetime** — how long
what is in it stays true:

    <run>/project.json  CONSTRAINTS.json      the project: canvas, delivery, standing rules
    <run>/GATES.json    REGIONS.json          optional, found by convention beside project.json:
                                              authored check bars (each with a reason), tone regions
    <run>/footage/                            a function of the raw clips; survives every re-cut
    <run>/music/                              downloaded tracks, shared by every reel
    <run>/reels/<reel>/                       one editorial variant; <reel> is `main` by default
    <run>/reels/<reel>/episodes/              one render generation + its QC verdicts
    <run>/reels/<reel>/deliveries/            append-only — nothing ever deletes this
    <run>/reels/<reel>/build/                 wiped at the start of every render

Never compose these paths from memory. `montage status --run-dir <run> --reel <reel>`
returns each stage's resolved `path` alongside `next`, plus the whole `layout` block.
A file written anywhere else is not seen by the router, and the stage runs again.

A **second cut of the same footage** is a new `<reel>`, never a filename suffix: run
edit-plan with `--out-dir <run>/reels/upbeat` and the whole editorial layer forks while
`footage/` and `music/` stay shared. `MUSIC_A.json` / `pacing_B/` style names are what
this replaces.

**Never the footage folder itself, either** — a hazard distinct from the wrong
bucket above. The conveyor discovers footage by extension over a flat listing of
the footage root, so an artifact written there that happens to be a video becomes
source material on the next scan (`draft.mp4` did exactly this). `intake` and
`draft` refuse a path that resolves to the footage root outright; the refusal
names the remedy.

Point **every** stage's output at its own bucket in the layout above — never all
at `<run>` itself: `project_init --project-dir <run>`, `intake <footage_root>
<run>/footage`, `reel_brief build --project <run>/project.json --out-dir
<run>/reels/<reel>`, `edit_plan build --out-dir <run>/reels/<reel>`,
`edl_to_reel --work-dir <run>/reels/<reel>/build --out-dir <run>/reels/<reel>/episodes`.

## The stages

Generated from `montage.V1_STAGES` — the registry the inspector resolves against.
Read a stage's page before running it; each row's stub, under **The steps**
below, carries the command and nothing else.

<!-- generated: stages — "$VG" scripts.montage stages -->
| step | stage | kind | gate | writes | page |
|---|---|---|---|---|---|
| 2 | `project-init` | required | CP1 | `project.json` | `references/using-montage/project-init.md` |
| 3 | `footage-intake` | required | — | `FOOTAGE.json` | `references/using-montage/footage-intake.md` |
| 4 | `contact-sheet` | required | — | `SHEETS.md` | `references/using-montage/contact-sheet.md` |
| 5 | `reel-brief` | optional | CP1 | `SPEC.json` | `references/using-montage/reel-brief.md` |
| 6 | `edit-plan` | required | CP2 | `EDL.json` | `references/using-montage/edit-plan.md` |
| 7 | `music-and-mood` | optional | — | `MUSIC.json` | `references/using-montage/music-and-mood.md` |
| 8 | `pacing` | optional | — | `PACING.md` | `references/using-montage/pacing.md` |
| 9 | `episodes-geometry` | required | — | `GEOMETRY.json` | `references/using-montage/episodes-geometry.md` |
| 10 | `match-grade` | required | — | `MATCH.json` | `references/using-montage/match-grade.md` |
| 11 | `assemble-draft` | optional | CP2 | `draft.mp4` | `references/using-montage/assemble-draft.md` |
| 12 | `titles` | optional | CP3 | `TITLES.json` | `references/using-montage/titles.md` |
| 13 | `episodes` | required | — | `EPISODES.json` | `references/using-montage/episodes.md` |
| 14 | `episode-qc` | required | — | `EPISODE_QC.json` | `references/using-montage/episode-qc.md` |
| 15 | `deliver` | required | CP3 | `REEL_v*.*` | `references/using-montage/deliver.md` |
| 16 | `reel-review` | required | CP3 | `REVIEW.json` | `references/using-montage/reel-review.md` |
<!-- /generated -->

## Checkpoints

The three user gates (design §4.1). They stay here, resident: a stage
page that goes unread costs detail, a checkpoint that goes unread is a
user gate silently skipped. The table above says which stage sits at
which gate.

**Checkpoint 1 — SPEC approval:** read back the
resolved `{canvas, delivery}` and the intent you parsed; confirm before moving on.
When reel-brief runs, its SPEC.md is the fuller CP1 artifact; without it, the
resolved {canvas, delivery} is the CP1 surface.

**Checkpoint 2 — EDL approval + curation:** show the user `EDL.md`, and say its
**Screen time** numbers out loud when the reel has more than one hero — each
hero's seconds and share beside the brief's `cast_share`. To swap
or re-order an episode, edit `selection.json` and re-run the build — never
hand-edit `EDL.json`.
**`draft.mp4` is CP2's richer artifact** — when it exists (the optional
assemble-draft step below), it is what the user approves at Checkpoint 2; on a
run without it, `EDL.md` still anchors CP2. **Ask explicitly at this checkpoint
(#6):** *"titles? effects (slow-mo / speed ramp, transitions, SFX)?"* — CP2 is
the right place because the EDL now exists, so the reel length is known and a
title can actually be timed. Name what you are skipping on "no" (e.g. "no
titles — the reel will carry no on-screen text") rather than silently passing
over the optional stages below.

**Checkpoint 3 — final
review:** present `<run>/reels/<reel>/deliveries/REEL_v1.mp4`, the `check_reel`
report, and (when titles were authored) `TITLES.md` alongside them. Before
presenting the reel as final, run
`"$VG" scripts.montage verify --run-dir <run> --reel <reel>` and
show its result — a delivery whose state is not `attested` (most notably
`unattested`: no `REEL_v{n}.attest.json`) must be named plainly as such,
never presented as a finished reel. **Do not say "the file did not come
out of `deliver`" — since 2026-09-09 that is the LEAST likely of three
causes**: most often the look gate withheld the attestation on purpose (a
declared vignette/fade did not reach the pixels — the file is complete,
look at it, `deliver` renamed it into place before the gate ever ran);
next most often the process was killed AFTER the rename but before the
attestation was written (a window of seconds now, not the old window of
an entire encode); rarest of all, the file genuinely predates `deliver`.
If `verify` lists `gates`, name each moved bar and its written reason beside the
reel: they are waivers the operator authored, and this is where a human reads them
(a blocking bar's reason is also in `REEL_v{n}.attest.json`). `montage status`'s
own `interrupted` list is the separate, cheaper signal
for the failure that used to hide behind this one: a non-empty list
names a leftover `.REEL_v{n}.part.<container>` from an encode killed
mid-write — that delivery consumed no version and is invisible as one,
so there is nothing to clean up and nothing to explain away; just
re-run `deliver` (or `edl_to_reel --from-episodes`) and it overwrites
the partial. Its
`episode_qc` field needs the same treatment when it
is not `judged` (`absent`: shipped via the single-command `edl_to_reel`
or `build_reel`'s own CLI, neither of which this router uses; `stale`:
judged, then an episode was re-rendered after its verdict — which on this
path means something bypassed phase 2's own `episode-qc-reprocessed`
refusal (step 15); `unknown`: an
old sidecar predating the field) — a reel this router delivered itself
should always read `judged`, so anything else means an unjudged reel is
about to be called final and must be named plainly, not passed over. A `stop_and_report` (a failed gate) is surfaced verbatim —
never fixed forward; route it to the culprit stage's skill.
`verify`'s `review` block is not yet meaningful at this call — `REVIEW.json`
does not exist until reel-review below writes it, so reading `absent` here
is expected, not a fault; reel-review's own procedure re-runs `montage
verify` once it has, and that later reading is the one to report.

**Standing rules — at every checkpoint.** The `EDL.json` sentence below
applies from Checkpoint 2 on; at Checkpoint 1 there is no cut yet to
re-judge.

When the user states an editorial rule that must hold across re-cuts ("one hero
opens, the other closes", "no repeated episodes", "don't use that take"), append it
to `CONSTRAINTS.json` beside `project.json` before continuing — see the edit-plan
SKILL for the four kinds. `edit_plan build` enforces it on every later cut without
being told. A rule outside the four kinds cannot be stored: tell the user it will
not be enforced instead of leaving them to assume it is. `EDL.json` already exists
at this checkpoint, so writing the rule down does not by itself re-judge the cut
already on disk — re-run `edit_plan build` (and on a paced run, `pacing` followed
by `edit_plan build --pacing`) so the rule binds the cut that already exists, not
only the next one.

## The steps

0. **Verify the runtime (gate).** After resolving `$VG` (below), run
   `"$VG" scripts.verify_runtime`. It checks **two** layers: the `setup.sh`
   baseline (deps/ffmpeg/filters/font/weights/demucs) and, since 2026-09-25,
   whether the **installed plugin** matches this clone. Exit 0 → proceed.
   Non-zero → surface each `BLOCKED` check with its remedy and **stop** — do not
   run project-init against a broken runtime, and never run an installer
   yourself. A failing **`plugin`** check's remedy is
   `claude plugin update video-grid@video-grid`, **not** `bash setup.sh` like
   every other row's — relay it verbatim, then say Claude Code must be
   **restarted** afterwards: the update rewrites the cache, it does not reload
   the skills this session already holds, so a green re-check can still
   describe a run still driven by the stale text. Advisory gaps (e.g. `reid`)
   are named, not blocking (they only affect optional lanes — without `reid`
   intake still produces windows, only cast identity is unavailable). `demucs`
   is **not** advisory: it blocks, because the music in/out-point has no
   fallback sensor. The venv and the recorded root are the
   pre-venv layer, checked by the launcher preamble and `bin/vg` before this runs.
   The dedicated `verify-runtime` skill runs the same check on demand.

   If `montage status` reports `"legacy_layout": true`, this run was written before the
   0.3.0 layout: its artifacts sit directly in `<run>`. **Ask the user** whether to point
   the conveyor at a fresh `<run>` (re-scanning every clip, hours on a 99-clip shoot) or
   to keep driving the old run by passing the old paths explicitly. Do not move the tree:
   `EPISODES.json` alone carries 57 absolute paths, and moving it breaks the QC digest
   bindings and the delivery attestation.

**Launcher and references.** Run every pipeline step through the repo's launcher
`bin/vg`, never a bare `python`, and resolve every `references/…` read the same
way. `setup.sh` records the runtime's location at
`${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root`, so resolve it once:

    ROOT="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")"
    VG="$ROOT/bin/vg"

Then run every step as `"$VG" scripts.X`, read every reference as
`"$ROOT/references/…"`, and pass **absolute** paths for every footage / run /
output directory. Nothing here is relative to your working directory — a skill
runs from the user's footage project, not from the clone. If that file is
missing, the user has not run `bash setup.sh` — stop and say so rather than
guessing a path.

1. **Locate the run.** `"$VG" scripts.montage status --run-dir <run> --reel <reel>` prints
   the ordered stages, each with a `state`, plus the `next` stage. **Resume from
   `next`** — a stage whose artifact already exists and still describes what is
   on disk is `done`; do not redo it. **Since 2026-09-09 a required stage can
   also read `stale`** (match-grade, reel-review) — the artifact exists but no
   longer describes the current cut or delivery, each row carries a
   `stale_reason` naming what moved, and `next` points BACK at a stale stage
   exactly as if it had never run: re-run it, do not skip past it because
   something with the right filename is already on disk. Also check
   `interrupted` — a non-empty list names a delivery killed mid-encode (a
   leftover `.REEL_v{n}.part.<container>`); it consumed no version and needs
   no cleanup, just a re-run of `deliver`. Read `gates` too: it lists any check
   threshold the operator moved beside `project.json`, with its reason; an `error`
   there means the file is broken and the next `edl_to_reel` will refuse it; and a
   `frozen` block says whether the set a render froze still matches the file. Read
   the brief and parse intent into params (table below).
   **A run from before the `montage/` convention** lives directly in the footage
   folder. If `<run>` is empty but `<footage_root>/project.json` exists, say so and
   ask which to use — starting fresh silently would re-scan every clip.

2. **project-init** — if `next`, resolve the canvas and delivery.

   ```bash
   "$VG" scripts.project_init --purpose <p> --quality <q> --project-dir <run>
   ```

   Before running it, read `"$ROOT/references/using-montage/project-init.md"`.

3. **footage-intake** — if `next`, invoke the **footage-intake** skill and point
   its out-dir at `<run>/footage`.

   Before running it, read `"$ROOT/references/using-montage/footage-intake.md"`.

4. **contact-sheet** — if `next`, render the sheets and read every one of them.

   ```bash
   "$VG" scripts.contact_sheet build \
     --footage <run>/footage/FOOTAGE.json --footage-root <footage_root> \
     --out-dir <run>/footage
   ```

   Before running it, read `"$ROOT/references/using-montage/contact-sheet.md"`.

5. **reel-brief** — optional; invoke the **reel-brief** skill to write `SPEC.md`
   + `SPEC.json` into `<run>/reels/<reel>`.

   Before running it, read `"$ROOT/references/using-montage/reel-brief.md"`.

6. **edit-plan** — if `next`, invoke the **edit-plan** skill; its first
   `edit_plan build` carries NO `--pacing`, and carries
   `--spec <run>/reels/<reel>/SPEC.json` when reel-brief ran.
   Stops: `variety-gap`.

   Before running it, read `"$ROOT/references/using-montage/edit-plan.md"`.

7. **music-and-mood** — optional; choose the track (a path, a name, or the
   **music-match** / **music-source** lanes), then lock its in-point:

   ```bash
   "$VG" scripts.beats <track> --auto-start \
     --duration <reel_len> --out <run>/reels/<reel>/MUSIC.json
   ```

   Fetches cache into `<run>/music/cache`. Before running it, read
   `"$ROOT/references/using-montage/music-and-mood.md"`.

8. **pacing** — optional; invoke the **pacing** skill to fit the existing
   cuts onto the beat grid, then re-run edit-plan to apply the fit.

   ```bash
   "$VG" scripts.pacing --edl <run>/reels/<reel>/EDL.json \
     --footage <run>/footage/FOOTAGE.json --music <run>/reels/<reel>/MUSIC.json \
     --out-dir <run>/reels/<reel>
   "$VG" scripts.edit_plan build <step 6's own flags> \
     --pacing <run>/reels/<reel>/PACING.json \
     [--spec <run>/reels/<reel>/SPEC.json] --music <run>/reels/<reel>/MUSIC.json
   ```

   Before running it, read `"$ROOT/references/using-montage/pacing.md"`.

9. **episodes-geometry** — required; extract, stabilize, track and gate every
   episode, then stop before the encode.

   ```bash
   "$VG" scripts.edl_to_reel <run>/reels/<reel>/EDL.json --project <run>/project.json \
     --footage-root <footage_root> --work-dir <run>/reels/<reel>/build \
     --out-dir <run>/reels/<reel>/episodes --stop-after-geometry
   ```

   Before running it, read `"$ROOT/references/using-montage/episodes-geometry.md"`.

10. **match-grade** — required; measure every episode's tracked crop and author
    the tone pairs that bring the reel to one common target.

    ```bash
    "$VG" scripts.match_grade build --geometry <run>/reels/<reel>/episodes/GEOMETRY.json \
      [--spec <run>/reels/<reel>/SPEC.json] [--eps 4.0] [--force]
    ```

    Before running it, read `"$ROOT/references/using-montage/match-grade.md"`.

11. **assemble-draft** — optional; a rough cut offered before the expensive
    render, approved at Checkpoint 2.

    ```bash
    "$VG" scripts.draft build --edl <run>/reels/<reel>/EDL.json \
      --project <run>/project.json --footage-root <footage_root> \
      --work-dir <run>/reels/<reel>/build --out <run>/reels/<reel>/draft.mp4 \
      [--music <run>/reels/<reel>/MUSIC.json]
    ```

    Before running it, read `"$ROOT/references/using-montage/assemble-draft.md"`.

12. **titles** — optional; invoke the **titles** skill to write `TITLES.json` +
    `TITLES.md` into `<run>/reels/<reel>`. It needs the reel length (`--total`);
    compute it, never guess it.

    Before running it, read `"$ROOT/references/using-montage/titles.md"`.

13. **episodes** — required; render every episode over the frozen routes.

    ```bash
    "$VG" scripts.edl_to_reel --from-geometry <run>/reels/<reel>/episodes/GEOMETRY.json \
      --project <run>/project.json --work-dir <run>/reels/<reel>/build \
      --out-dir <run>/reels/<reel>/episodes [--music <run>/reels/<reel>/MUSIC.json] \
      [--changelog "<what changed and why>"]   # on every re-cut — the version note
    ```

    Stops: `grade-damage`. Before running it, read
    `"$ROOT/references/using-montage/episodes.md"`.

14. **episode-qc** — required, not a checkpoint; invoke the **episode-qc** skill
    over `<run>/reels/<reel>/episodes/EPISODES.json`, which writes
    `<run>/reels/<reel>/episodes/EPISODE_QC.json` + `.md`. A blocking finding
    stops the run and there is no waiver.

    Before running it, read `"$ROOT/references/using-montage/episode-qc.md"`.

15. **deliver** — required; encode the judged episodes into one versioned
    delivery.

    ```bash
    "$VG" scripts.edl_to_reel --from-episodes <run>/reels/<reel>/episodes/EPISODES.json \
      --work-dir <run>/reels/<reel>/build [--titles <run>/reels/<reel>/TITLES.json]
    ```

    Stops: `episode-qc-reprocessed`, `grade_faithful`. Before running it, read
    `"$ROOT/references/using-montage/deliver.md"`.

16. **reel-review** — required at Checkpoint 3; invoke the **reel-review** skill
    to write `REVIEW.json` + `REVIEW.md` into `<run>/reels/<reel>`. The run is
    finished only when `montage status` reports `next: null`.

    Before running it, read `"$ROOT/references/using-montage/reel-review.md"`.

## Reading the brief (intent -> param)

The user speaks free text; you pass **explicit args** — the user never types flags.

| Said | -> |
|------|----|
| "reel"/"shorts"/"9:16" · "youtube"/"16:9" · "square"/"1:1" · "cinema"/"21:9" | `project_init --purpose` |
| "4k" · "1080"/"social" · "native"/(unstated) | `project_init --quality` |
| a reel idea / mood / hook / ending / style-lean | reel-brief SKILL -> SPEC.md |
| a track path / "with music" | `beats ... --out <run>/reels/<reel>/MUSIC.json` -> edit-plan `music` |
| "no music" / "без музыки" | leave `MUSIC.json` unset (silent reel) |
| "classic" <-> "trend" | edit-plan editorial guidance |

Mixed/unstated intent (e.g. "a reel AND a youtube cut") -> ask; one project is one
aspect (project-init's own "ask, don't guess").

## Boundaries

- The **three checkpoints** (SPEC, EDL, final review) are the ONLY user-facing
  gates (§4.1); everything else is a machine gate inside the sub-stages. CP3's
  review has two mechanisms: check_reel (mechanical) and the reel-review skill
  (editorial, §5.13 Slice B).
- **episode-qc (step 14) is required but is not a checkpoint.** The stage proves the
  artifact's presence and its digest binding to the exact rendered bytes —
  never that a judge truly looked (design §12); say so when you report a
  clean verdict.
- **Deferred stages are named, not skipped silently:** trend-scan (5.4) is not
  built; say so when you pass over it. For the live stages the table's `kind`
  column above is the authority on which are optional — read it there rather
  than from a sentence here, name every stage you pass over out loud, and see
  that stage's page for what skipping it costs.
- You never re-implement a stage and never hand-edit a generated artifact
  (`EDL.json` regenerates from `selection.json`; `FOOTAGE.json`/`project.json` from
  their writers) — `TITLES.json` is the one deliberate exception (titles SKILL): it
  is the source of record for on-screen text (no upstream judgment file to
  regenerate from), and `Title`/`Titles` validate on load, so a bad hand-edit fails
  loud at `deliver`. `EDL.json` is additionally **stamped** (design 2026-08-04):
  `edl_to_reel` loads a hand-authored EDL exactly as before, but refuses one whose
  provenance digest no longer matches its own contents — never hand-edit a
  tool-generated `EDL.json`, even to fix a small thing; revise `selection.json` and
  re-run the build instead.
- **Read a stage's whole output.** Never pipe a conveyor command through
  `tail`/`head`/`grep` — its stdout is the result. The first real run did that on
  95% of its calls and lost the answer twice, once paying a 173 s re-render to
  re-read output already printed. If it is long, redirect it to a file in
  `<run>/reels/<reel>/logs/` (create it first) and read the file — never under
  `build/`, which phase 1 wipes at its start, deleting its own log.
- **Keep the machine awake for a long run** (`caffeinate -i` in the user's own
  terminal, or the host's keep-awake setting) and tell every subagent you dispatch
  to write its output file incrementally: on the first real run the Mac sleeping
  killed 11 of 98 subagents.
- **You may not disable, lower, or downgrade any quality gate.** A gate that
  blocks is routed back to its stage's skill, never loosened to pass. No flag on
  any stage this router drives loosens a check threshold — the last one,
  `--color-delta-max`, was retired with the check it bounded (design 2026-08-29,
  colour-convergence-retire) rather than kept as an escape hatch. There is exactly
  one sanctioned lever and it is the user's, not yours: a `GATES.json` beside
  `project.json` (design 2026-09-30), each entry carrying a written `why` — refused
  at load without one — that is named beside the verdict it bought, in
  `REEL_v{n}.attest.json`'s `gates`, and in `montage status`/`verify`. Write an
  entry only when the user has said a bar is wrong for their footage, with *their*
  reason in `why`; never author one to clear a finding, and show every `gates` row at
  CP3. The attestation's `overrides` is a different, narrower list: it lists only
  reel-scope bars that differ from default, with no reason, and no episode-scope one
  (`entropy_floor`, `black_floor`, `black_rel`), so an empty one is not evidence that
  no bar moved — read `gates`. `episode-qc`
  carries no override at all (§7) — not even a measured one, and `GATES.json` cannot
  reach it.
