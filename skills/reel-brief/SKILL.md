---
name: reel-brief
description: Conveyor stage — the editorial brief. Interrogate the idea one question at a time and write SPEC.md (+ SPEC.json). using-montage invokes this after project-init; run it directly only to (re)write the brief. Sets mood, hook, length, music intent, style-lean, cast — the editorial layer atop the machine canvas/delivery, approved by the user at checkpoint CP1. Optional — enriches the reel; the autonomous path skips it.
---

# reel-brief (stage 5.3)

Turn a rough idea into a locked **reel brief** — `SPEC.md`, the editorial layer on
top of `project-init`'s machine subset. This is the **brainstorming of reels**: a
one-question-at-a-time dialogue, a hard gate before anything is written, and a
deterministic writer (you never hand-write `SPEC.md`). No ffmpeg here.

**The brief is judgment; the write is mechanical.** You collect the answers; the
`reel_brief` CLI validates them and renders both files. `canvas` is **not** yours to
choose — it comes from `project.json` (reel-brief FOLLOWS project-init); never
re-ask aspect.

## Inputs

- **`project.json`** (required, from project-init) — the canvas the brief inherits.
  If it is missing, run project-init first; reel-brief will not source aspect itself.
- **`cast.json`** (optional, from footage-intake) — real cast names to reference in
  the brief's `cast`. Absent → enter names free-hand.

## Procedure

Announce on entry: **"Using reel-brief to lock the reel's SPEC."**

1. **Recon.** Read `<run>/project.json` (note the canvas) and `<run>/footage/cast.json` if present — they sit in different buckets: the project's canvas outlives every re-cut, the cast is a function of the footage.
2. **Ask one question at a time** — do not batch. Cover: reel count · platform ·
   target length (seconds) · mood · hook (the opening) · music (a track / "auto" /
   "none") + `music.mode` (local / free / any — default free, the safe distribution
   lane) · style-lean (classic / balanced / trend) · on-screen text · ending · cast.
   Prefer the user's free text ("without music" → `--music none`; "any source" →
   `--music-mode any`).
3. **HARD-GATE.** Do not write until **mood + canvas + length + hook** are locked.
   If any is vague, keep asking.
4. **Self-review** the assembled answers, then **build** (explicit args; the user
   never types flags):

       python -m scripts.reel_brief build --project <run>/project.json \
         --length 30 --mood "…" --hook "…" \
         [--reel-count 1] [--music …] [--music-mode free] [--style-lean balanced] \
         [--platform …] [--text …] [--ending …] [--cast NAME]... [--notes …] \
         --out-dir <run>/reels/<reel>

   It validates the fields and writes `SPEC.json` + `SPEC.md`. A `ValueError` names
   the offending field — fix it and re-run; never hand-write `SPEC.md`.
5. **Review — CP1.** Show the user `SPEC.md` and get approval before edit-plan.

## Gate

`mood`, `canvas`, `length`, `hook` locked; `SPEC.json` + `SPEC.md` written. The
edit-plan agent reads `SPEC.md` as guidance (mood / hook / style-lean / length).

## Boundaries

- **Optional stage.** The brief enriches the reel; the autonomous path runs off
  `project.json` alone. Run reel-brief when the idea deserves shaping.
- **Not consumed mechanically in v1:** `music`/`music_mode` are recorded for Phase
  B3 sourcing (unbuilt); `style_lean` is editorial guidance, not a `TRENDS.md` (5.4)
  input.
- **`reel_count` stays 1.** `Spec` refuses `reel_count > 1` outright — the field
  stays in the contract for the day multi-reel fan-out is built, but the CLI will
  not silently produce one reel for a brief that asked for more. If the user
  wants several reels, run the conveyor one reel at a time (a project directory
  per reel).
- **`tone_bias` is a brief-level colour field match-grade reads** (design
  2026-09-03 §2) — `Spec.tone_bias: tuple | None`. `None`, the default, takes
  the mood preset's own displacement; an authored `(p5, p50, p95)` triple of
  luma-unit displacements outranks the preset's, and an authored `(0, 0, 0)` is
  a real, different answer from leaving it unset — *this mood, but leave my
  colour alone*. `reel_brief build`'s CLI has no `--tone-bias` flag today, so
  every brief this skill writes leaves it `None` (the preset's own taste).
  Authoring it means constructing `Spec` directly — never hand-edit
  `SPEC.json` to add it, the same rule as the line below.
- You never hand-edit `SPEC.json`/`SPEC.md` — the CLI regenerates them from answers.
