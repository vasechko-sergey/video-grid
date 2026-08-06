---
name: using-montage
description: Router — the montage conveyor's front door. Turns a folder of raw footage + a natural-language brief ("a 9:16 reel from this trip, no music") into a delivered reel. Use when the user wants a reel from footage — the 1%-chance montage router. Verifies the runtime, then conducts every stage in order (project-init → footage-intake → contact-sheet → [reel-brief] → edit-plan → [music] → [pacing] → [match-grade] → [assemble-draft] → [titles] → edl_to_reel → [reel-review]), stopping only at the three checkpoints, resuming a half-finished run, and naming any stage it skips. Required — the entry point.
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

0. **Verify the runtime (gate).** After resolving `$VG` (below), run
   `"$VG" scripts.verify_runtime`. Exit 0 → the `setup.sh` baseline is intact,
   proceed. Non-zero → surface each `BLOCKED` check with its remedy (almost always
   `bash setup.sh`) and **stop** — do not run project-init against a broken
   runtime, and never run `setup.sh` yourself. Advisory gaps (e.g. `demucs`) are
   named, not blocking (they only affect optional lanes — e.g. music in-point uses
   the librosa proxy without demucs). The venv and the recorded root are the
   pre-venv layer, checked by the launcher preamble and `bin/vg` before this runs.
   The dedicated `verify-runtime` skill runs the same check on demand.

**Launcher.** Run every pipeline step through the repo's launcher `bin/vg`, never a
bare venv `python` binary. Resolve it once: `setup.sh` records the runtime's location
at `${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root`, so set
`VG="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")/bin/vg"` and run every
step as `"$VG" scripts.X`, passing **absolute** paths for every footage / run / output
directory. If that file is missing, the user has not run `bash setup.sh` — stop and
say so rather than guessing a path.

1. **Locate the run.** `"$VG" scripts.montage status --run-dir <run>` prints
   the ordered stages, each with a `state`, plus the `next` stage. **Resume from
   `next`** — a stage whose artifact already exists is done; do not redo it. Read
   the brief and parse intent into params (table below).

2. **project-init** — if `next`. `"$VG" scripts.project_init
   --purpose <p> --quality <q> --project-dir <run>` (custom aspect:
   `--purpose custom --canvas W:H`). **Checkpoint 1 — SPEC approval:** read back the
   resolved `{canvas, delivery}` and the intent you parsed; confirm before moving on.
   When reel-brief runs, its SPEC.md is the fuller CP1 artifact; without it, the
   resolved {canvas, delivery} is the CP1 surface.

3. **footage-intake** — if `next`. Invoke the **footage-intake** skill (it scans ->
   `FOOTAGE.json`/`FOOTAGE.md` and, when people matter, runs the interactive
   cast-naming -> `cast.json`). Point its out-dir at `<run>`.

4. **contact-sheet** — if `next`. `"$VG" scripts.contact_sheet build
   --footage <run>/FOOTAGE.json --footage-root <footage_root> --out-dir <run>`
   (`<footage_root>` is the same raw-clips folder footage-intake scanned —
   `FOOTAGE.json`'s `source` is a bare filename, not a path, so the build needs
   the root to resolve it). Then **read every sheet it wrote** — `SHEETS.md`
   links them. This is the only point in the conveyor where you see the raw
   footage; every later stage works from your reading of it, so a skipped look
   is a guess propagated through the whole reel. The sheets do not replace
   `FOOTAGE.md` — the table carries the numbers, the sheets carry what the
   numbers cannot say. Read both, and offer the sheets to the user at CP1
   alongside the brief. **A run dir from before this stage existed** simply
   needs the build run once — `next` reports `contact-sheet` forever until
   `SHEETS.md` exists, even for a run already delivered and reviewed; running
   the command above resolves it, it is not a sign anything is wrong.

5. **reel-brief (optional).** If the brief deserves shaping (mood/hook/ending/
   style-lean beyond the bare aspect), invoke the **reel-brief** skill — it asks the
   idea one question at a time and writes `SPEC.md` + `SPEC.json` into `<run>`.
   `montage status` never points `next` here (it is optional); offer it proactively.
   **SPEC.md is CP1's richer artifact** — when it exists, it is what the user
   approves at Checkpoint 1 (the `edit-plan` agent then reads it as guidance). On a
   bare autonomous run, skip it and say so; `project.json` still anchors CP1.

6. **edit-plan** — if `next`. Invoke the **edit-plan** skill (it authors
   `selection.json`, runs `edit_plan build` -> `EDL.json` + `EDL.md`). Pass
   `--spec <run>/SPEC.json` when reel-brief (step 5) ran — its mood picks the
   shot-mix preset the variety gate holds the cut to; without one the build still
   runs, against the `balanced` preset. A `variety-gap` stop routes back to
   **edit-plan** like any other `stop_and_report` — add the named shot size or
   state a `variety_waiver` in `selection.json`, never a loosened gate. edit-plan
   runs **before** music and pacing (steps 7-8): this first `edit_plan build`
   carries **no `--pacing`**, so each cut keeps the length its footage gives it.
   **Checkpoint 2 — EDL approval + curation:** show the user `EDL.md`. To swap
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

   The scenario comes first and the music is fitted to it (design 2026-07-24). Run
   `edit_plan build` with NO `--pacing` to get the cuts at their material lengths, then
   `pacing`, then `edit_plan build --pacing` to apply the fit. Never re-time a shot to make
   a slot: a shot that IS the content — a ride, a trick — is not a slot's length.

7. **music-and-mood (optional).** The cuts already exist (step 6), so the reel's
   length is the sum of `EDL.json`'s episode durations — analyse the track against
   **that** length, not a SPEC target. If the brief names a **track**:
   - a **local file path** -> analyse it directly, preferring the tool's own
     in-point pick: `"$VG" scripts.beats <track> --auto-start
     --duration <reel_len> --out <run>/MUSIC.json` — it starts the reel on the
     strongest fragment, in a vocal pause (demucs — installed by `bash setup.sh` —
     sharpens this; a librosa mix-silence proxy is the fallback). Pass an explicit
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
   Either way, `MUSIC.json` feeds **pacing** next (step 8), and the EDL references it
   (`selection.json`'s `music` field) for the audio mux. On "no music" / "без
   музыки", leave it unset — the reel is silent, pacing is skipped (a valid path).

8. **pacing (§5.6, optional).** When `MUSIC.json` exists, invoke the **pacing**
   skill — it **fits** the cuts `EDL.json` already holds onto the music's beat grid
   (`"$VG" scripts.pacing --edl <run>/EDL.json --footage <run>/FOOTAGE.json
   --music <run>/MUSIC.json --out-dir <run>`) and writes `PACING.json` + `PACING.md`
   into `<run>`. Then **apply the fit** by re-running edit-plan with the report:
   `edit_plan build ... --pacing <run>/PACING.json` — this second pass writes the
   snapped durations and `beat_slot` into `EDL.json`. No `MUSIC.json` (a silent reel)
   -> skip it (named); the EDL stays pacing-less (`beat_slot` unset). `montage status`
   never points `next` here (it is optional).

9. **match-grade (optional, §10 — colour conductor).** When episodes come from
   mixed cameras or mixed lighting, invoke the **match-grade** skill — it
   measures every episode's source tone, computes one common reel target (the
   per-anchor median), and authors `tone_src`/`tone_dst` into the episodes that
   deviate (`"$VG" scripts.match_grade build --edl <run>/EDL.json
   --footage-root <footage_root> [--eps 4.0] [--force]`), rewriting `EDL.json`
   IN PLACE plus a sibling `MATCH.md`. **Run it AFTER pacing (step 8)** —
   pacing's apply pass regenerates `EDL.json` and would wipe an authored tone,
   the same "settle the cut first" rule pacing itself carries. A single-camera
   reel needs it not (every episode lands `within-eps`, no pair authored).
   `montage status` never points `next` here (it is optional).

10. **assemble-draft (optional, §5.9 — CP2 preview).** Before the expensive
    process-episode render, offer a rough draft: "Want to see a rough cut first?"
    If yes, `"$VG" scripts.draft build --edl <run>/EDL.json
    --project <run>/project.json --footage-root <footage_root> --work-dir <run>/work
    --out <run>/draft.mp4 [--music <run>/MUSIC.json]`. `draft.mp4` concats the raw
    segments, scale-fit into the canvas, with `processing_notes` labels and a rough
    music bed — the user eyeballs layout / order / length / beat-landing and
    approves (or goes back to edit-plan) at Checkpoint 2. This stage is optional:
    `montage status` never points `next` at it, and the autonomous path skips it.

11. **titles (optional, §5.16 — CP3 review).** If reel-brief ran (`SPEC.json`
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

12. **edl_to_reel.** `"$VG" scripts.edl_to_reel <run>/EDL.json
    --project <run>/project.json --footage-root <footage_root>
    --work-dir <run>/work --out-dir <run>/out [--music <run>/MUSIC.json]
    [--titles <run>/TITLES.json]`. This runs
    the whole back half (extract -> process-episode ×N -> assemble -> check_reel ->
    deliver). When `TITLES.json` is passed, `deliver` burns its drawtext chain into
    the ONE encode it already runs — no second pass; `deliver` also writes a
    `REEL_v{n}.attest.json` sidecar beside the encode (design 2026-08-04). **Checkpoint
    3 — final review:** present `out/REEL_v1.mp4`, the `check_reel` report, and (when
    titles were authored) `TITLES.md` alongside them. Before presenting the reel as
    final, run `"$VG" scripts.montage verify --run-dir <run>` and show its result — a
    delivery whose state is not `attested` (most notably `unattested`: no
    `REEL_v{n}.attest.json`, meaning the file did not come out of `deliver`) must be
    named plainly as such, never presented as a finished reel. A `stop_and_report` (a
    failed gate) is surfaced verbatim — never fixed forward; route it to the culprit
    stage's skill.

    Then invoke the **reel-review** skill — it dispatches a fresh reviewer subagent
    that judges the reel against `SPEC` (idea/mood/hook/ending/spine) and writes
    `REVIEW.json` + `REVIEW.md`; present `REVIEW.md` alongside the reel and the
    `check_reel` report. For each finding the user chooses to act on, re-run the
    routed stage (`edit-plan`/`pacing`/`music`/`titles`) — never fix the reel
    forward — then re-review the new cut. reel-review is **required**, not optional
    (§5.13 editorial half, design 2026-08-04 §8) — the run is not finished when
    `delivered` is `true`, only when `"$VG" scripts.montage status --run-dir <run>`
    reports `next: null`; on a bare autonomous run reel-review still runs, judging
    against the `EDL`.

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
  (`beat_slot` stays unset). match-grade (`MATCH.md`, §10) is optional too — it
  is opt-in (offer it only when episodes come from mixed cameras/lighting) and
  must run AFTER pacing, never before (a pacing re-run regenerates `EDL.json`
  and would wipe an authored tone); the autonomous path skips it (a
  single-camera reel needs no conductor). reel-review (§5.13 editorial half)
  runs at CP3 after deliver; it is **required** — `montage status` points `next`
  at it until it runs, so the run is not finished on `delivered: true` alone — and
  still human-gated: the reviewer proposes, you dispose.
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
- **You may not disable, lower, or downgrade any quality gate.** A gate that
  blocks is routed back to its stage's skill, never loosened to pass.
  `--color-delta-max` exists for a reel that deliberately cuts between scenes of
  different exposure, with the measured delta in hand — never to silence a grade
  that is genuinely wrong — and every use of it is recorded in the delivery's
  attestation and shown at CP3.
- **Built, not obvious:** the cap-3 **parallel** episode fan-out landed
  2026-07-18 — `edl_to_reel` processes episodes across a bounded thread pool
  (`jobs`, default 3, the measured knee) inside its own loop; you invoke
  `edl_to_reel` once per run and never drive the fan-out yourself.
