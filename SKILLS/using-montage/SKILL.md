---
name: using-montage
description: The montage conveyor's front door — use when a folder of raw footage plus a natural-language brief ("a 9:16 reel from this trip, no music") should become a delivered reel. The "1% chance a montage skill applies -> invoke it" router: ensure the env, then conduct the built stages (project-init -> footage-intake -> [reel-brief] -> [music] -> edit-plan -> edl_to_reel) in order, stopping only at the three user checkpoints, resuming a half-finished run for free, and naming any stage it skips. Stage 5.1.
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

0. **Ensure env.** `bash setup.sh` (add `--with-vidstab` — footage-intake is the
   first runtime vidstab consumer, §5.2).

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

5. **music-and-mood (optional).** If the brief names a track or asks for music,
   `.venv/bin/python -m scripts.beats <track> --out <run>/MUSIC.json
   [--start-offset S --duration D]`, then pass `<run>/MUSIC.json` to edit-plan. On
   "no music" / "без музыки", leave it unset — the reel is silent (a valid path).

6. **edit-plan** — if `next`. Invoke the **edit-plan** skill (it authors
   `selection.json`, runs `edit_plan build` -> `EDL.json` + `EDL.md`). **Checkpoint
   2 — EDL approval + curation:** show the user `EDL.md`. To swap or re-order an
   episode, edit `selection.json` and re-run the build — never hand-edit `EDL.json`.
   There is **no `draft.mp4`** in v1 (deferred) — the `EDL.md` map is the approval
   surface; say so plainly.

7. **edl_to_reel.** `.venv/bin/python -m scripts.edl_to_reel <run>/EDL.json
   --project <run>/project.json --footage-root <footage_root>
   --work-dir <run>/work --out-dir <run>/out [--music <run>/MUSIC.json]`. This runs
   the whole back half (extract -> process-episode ×N -> assemble -> check_reel ->
   deliver). **Checkpoint 3 — final review:** present `out/REEL_v1.mp4` and the
   `check_reel` report. A `stop_and_report` (a failed gate) is surfaced verbatim -
   never fixed forward; route it to the culprit stage's skill.

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
  gates (§4.1); everything else is a machine gate inside the sub-stages.
- **Deferred stages are named, not skipped silently:** trend-scan (5.4), pacing
  (`PACING.md`, 5.6 — `beat_slot` stays unset), and the `draft.mp4` (SP1b) are not
  built; say so when you pass over them. reel-brief (`SPEC.md`, 5.3) is optional —
  offer it; on a bare run, name it as skipped.
- You never re-implement a stage and never hand-edit a generated artifact
  (`EDL.json` regenerates from `selection.json`; `FOOTAGE.json`/`project.json` from
  their writers).
- **Not built here:** the cap-3 **parallel** episode fan-out — `edl_to_reel`
  processes episodes sequentially; parallelising it is a later slice.
