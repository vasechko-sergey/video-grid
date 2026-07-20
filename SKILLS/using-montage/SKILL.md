---
name: using-montage
description: The montage conveyor's front door — use when a folder of raw footage plus a natural-language brief ("a 9:16 reel from this trip, no music") should become a delivered reel. The "1% chance a montage skill applies -> invoke it" router: ensure the env, then conduct the built stages (project-init -> footage-intake -> [reel-brief] -> [music] -> [pacing] -> edit-plan -> [assemble-draft] -> [titles] -> edl_to_reel -> [reel-review]) in order, stopping only at the three user checkpoints, resuming a half-finished run for free, and naming any stage it skips. Stage 5.1.
---

# using-montage (stage 5.1)

## Overview

You are the **conductor** of the montage conveyor. One invocation turns a footage
folder + a brief into `out/REEL_v1.mp4`, by running the stages that are already
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

Point **every** stage's output at one **run dir** so the inspector sees a coherent
run: `project_init --project-dir <run>`, `intake <root> <run>`,
`reel_brief build --project <run>/project.json --out-dir <run>`, `edit_plan build --out-dir <run>`,
`edl_to_reel --work-dir <run>/work --out-dir <run>/out`.

0. **Ensure env.** `bash setup.sh` — one install, no capability flags. It puts
   keg-only `ffmpeg-full` (drawtext + vidstab) beside core ffmpeg and records
   the path in `config/ffmpeg.env`, which is how every stage resolves its
   binary.

1. **Locate the run.** `.venv/bin/python -m scripts.montage status --run-dir <run>` prints
   the ordered stages, each with a `state`, plus the `next` stage. **Resume from
   `next`** — a stage whose artifact already exists is done; do not redo it. Read
   the brief and parse intent into params (table below).

2. **project-init** — if `next`. `.venv/bin/python -m scripts.project_init
   --purpose <p> --quality <q> --project-dir <run>` (custom aspect:
   `--purpose custom --canvas W:H`). **Checkpoint 1 — SPEC approval:** read back the
   resolved `{canvas, delivery}` and the intent you parsed; confirm before moving on.
   When reel-brief runs, its SPEC.md is the fuller CP1 artifact; without it, the
   resolved {canvas, delivery} is the CP1 surface.

3. **footage-intake** — if `next`. Invoke the **footage-intake** skill (it scans ->
   `FOOTAGE.json`/`FOOTAGE.md` and, when people matter, runs the interactive
   cast-naming -> `cast.json`). Point its out-dir at `<run>`.

4. **reel-brief (optional).** If the brief deserves shaping (mood/hook/ending/
   style-lean beyond the bare aspect), invoke the **reel-brief** skill — it asks the
   idea one question at a time and writes `SPEC.md` + `SPEC.json` into `<run>`.
   `montage status` never points `next` here (it is optional); offer it proactively.
   **SPEC.md is CP1's richer artifact** — when it exists, it is what the user
   approves at Checkpoint 1 (the `edit-plan` agent then reads it as guidance). On a
   bare autonomous run, skip it and say so; `project.json` still anchors CP1.

5. **music-and-mood (optional).** If the brief names a **track**:
   - a **local file path** -> analyse it directly, preferring the tool's own
     in-point pick: `.venv/bin/python -m scripts.beats <track> --auto-start
     --duration <reel_len> --out <run>/MUSIC.json` — it starts the reel on the
     strongest fragment, in a vocal pause (accurate with `bash setup.sh
     --with-demucs`; a librosa mix-silence proxy otherwise). Pass an explicit
     `--start-offset S` instead only to override.
   - an explicit **track name** (not a path) -> skip discovery; invoke
     **music-source** with `--track "<name>"` to resolve and fetch it, then the
     same `beats --auto-start` locks it.
   If instead the brief has a **mood but no chosen track**:
   - the user has a **folder** of candidates (`music_mode == local`) -> invoke
     **music-match** first — it ranks the folder by mood into
     `MUSIC_SHORTLIST.md`, the user picks, and it runs the same
     `beats --auto-start`.
   - no local folder (`music_mode` is `free` or `any`) -> invoke
     **music-source** instead — it discovers and ranks candidates from the
     internet (`free` = CC catalogs; `any` is opt-in/copyright-gray — confirm
     with the user first) into the same shortlist shape, the user picks, and it
     downloads then runs `beats --auto-start`.
   Either way, pass `<run>/MUSIC.json` to edit-plan. On "no music" / "без
   музыки", leave it unset — the reel is silent (a valid path).

6. **pacing (§5.6, optional).** When `MUSIC.json` exists, invoke the **pacing**
   skill — it derives the beat-aligned energy spine (`.venv/bin/python -m
   scripts.pacing --music <run>/MUSIC.json --spec <run>/SPEC.json --out-dir
   <run>`) and writes `PACING.json` + `PACING.md` into `<run>`. No `MUSIC.json`
   (a silent reel) -> skip it (named); edit-plan runs pacing-less (`beat_slot`
   stays unset). `montage status` never points `next` here (it is optional).
   Pass `<run>/PACING.json` to edit-plan next (`--pacing <run>/PACING.json`).

7. **edit-plan** — if `next`. Invoke the **edit-plan** skill (it authors
   `selection.json`, runs `edit_plan build` -> `EDL.json` + `EDL.md`). **Checkpoint
   2 — EDL approval + curation:** show the user `EDL.md`. To swap or re-order an
   episode, edit `selection.json` and re-run the build — never hand-edit `EDL.json`.
   **`draft.mp4` is CP2's richer artifact** — when it exists (the optional
   assemble-draft step below), it is what the user approves at Checkpoint 2; on a
   run without it, `EDL.md` still anchors CP2.

8. **assemble-draft (optional, §5.9 — CP2 preview).** Before the expensive
   process-episode render, offer a rough draft: "Want to see a rough cut first?"
   If yes, `.venv/bin/python -m scripts.draft build --edl <run>/EDL.json
   --project <run>/project.json --footage-root <footage_root> --work-dir <run>/work
   --out <run>/draft.mp4 [--music <run>/MUSIC.json]`. `draft.mp4` concats the raw
   segments, scale-fit into the canvas, with `processing_notes` labels and a rough
   music bed — the user eyeballs layout / order / length / beat-landing and
   approves (or goes back to edit-plan) at Checkpoint 2. This stage is optional:
   `montage status` never points `next` at it, and the autonomous path skips it.

9. **titles (optional, §5.16 — CP3 review).** If reel-brief ran (`SPEC.json`
   exists) and the reel wants on-screen text, invoke the **titles** skill — it
   reads `SPEC.json`'s `hook`/`text`/`ending`, proposes timing/position/style/
   font, and writes `TITLES.json` + `TITLES.md` into `<run>`. It needs the reel
   length (`--total`); compute it here — sum `EDL.json`'s episode durations, or
   probe `draft.mp4` if it exists; never guess it. `montage status` never points
   `next` here; the autonomous path (no `SPEC.json`, or no on-screen text wanted)
   skips it and says so. **`TITLES.md` is reviewed together with the near-final
   reel at Checkpoint 3** — not standalone. When it exists, pass it to
   `edl_to_reel` next (`--titles <run>/TITLES.json`) so the reel actually renders
   the text.

10. **edl_to_reel.** `.venv/bin/python -m scripts.edl_to_reel <run>/EDL.json
    --project <run>/project.json --footage-root <footage_root>
    --work-dir <run>/work --out-dir <run>/out [--music <run>/MUSIC.json]
    [--titles <run>/TITLES.json]`. This runs
    the whole back half (extract -> process-episode ×N -> assemble -> check_reel ->
    deliver). When `TITLES.json` is passed, `deliver` burns its drawtext chain into
    the ONE encode it already runs — no second pass. **Checkpoint 3 — final
    review:** present `out/REEL_v1.mp4`, the `check_reel` report, and (when titles
    were authored) `TITLES.md` alongside them. A `stop_and_report` (a failed gate)
    is surfaced verbatim — never fixed forward; route it to the culprit stage's
    skill.

    Then invoke the **reel-review** skill — it dispatches a fresh reviewer subagent
    that judges the reel against `SPEC` (idea/mood/hook/ending/spine) and writes
    `REVIEW.json` + `REVIEW.md`; present `REVIEW.md` alongside the reel and the
    `check_reel` report. For each finding the user chooses to act on, re-run the
    routed stage (`edit-plan`/`pacing`/`music`/`titles`) — never fix the reel
    forward — then re-review the new cut. reel-review is the §5.13 editorial half;
    on a bare autonomous run it still runs, judging against the `EDL`.

## Reading the brief (intent -> param)

The user speaks free text; you pass **explicit args** — the user never types flags.

| Said | -> |
|------|----|
| "reel"/"shorts"/"9:16" · "youtube"/"16:9" · "square"/"1:1" · "cinema"/"21:9" | `project_init --purpose` |
| "4k" · "1080"/"social" · "native"/(unstated) | `project_init --quality` |
| a reel idea / mood / hook / ending / style-lean | reel-brief SKILL -> SPEC.md |
| a track path / "with music" | `beats ... --out MUSIC.json` -> edit-plan `music` |
| "no music" / "без музыки" | leave `MUSIC.json` unset (silent reel) |
| "classic" <-> "trend" | edit-plan editorial guidance |

Mixed/unstated intent (e.g. "a reel AND a youtube cut") -> ask; one project is one
aspect (project-init's own "ask, don't guess").

## Boundaries

- The **three checkpoints** (SPEC, EDL, final review) are the ONLY user-facing
  gates (§4.1); everything else is a machine gate inside the sub-stages. CP3's
  review has two mechanisms: check_reel (mechanical) and the reel-review skill
  (editorial, §5.13 Slice B).
- **Deferred stages are named, not skipped silently:** trend-scan (5.4) is not
  built; say so when you pass over it. reel-brief (`SPEC.md`, 5.3) is optional —
  offer it; on a bare run, name it as skipped. assemble-draft (`draft.mp4`, 5.9)
  is optional too — offer it before edl_to_reel; the autonomous path skips it
  without asking (no approval needed to skip a preview). titles (`TITLES.json`,
  5.16) is optional too — offer it once `SPEC.json` exists; the autonomous path
  skips it without asking (no on-screen text is a valid, complete reel). pacing
  (`PACING.md`, 5.6) is optional too — it runs automatically whenever
  `MUSIC.json` exists; a music-less reel skips it and edit-plan runs pacing-less
  (`beat_slot` stays unset). reel-review (§5.13 editorial half) runs at CP3
  after deliver; it is optional in montage status (never next) and human-gated
  — the reviewer proposes, you dispose.
- You never re-implement a stage and never hand-edit a generated artifact
  (`EDL.json` regenerates from `selection.json`; `FOOTAGE.json`/`project.json` from
  their writers) — `TITLES.json` is the one deliberate exception (titles SKILL): it
  is the source of record for on-screen text (no upstream judgment file to
  regenerate from), and `Title`/`Titles` validate on load, so a bad hand-edit fails
  loud at `deliver`.
- **Not built here:** the cap-3 **parallel** episode fan-out — `edl_to_reel`
  processes episodes sequentially; parallelising it is a later slice.
