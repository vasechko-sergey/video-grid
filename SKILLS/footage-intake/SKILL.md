---
name: footage-intake
description: Use when a folder of raw clips needs to become the reel's candidate material — scan every clip into scored moment-windows (FOOTAGE.json/.md) and, when people matter, run one interactive pass to name the heroes into cast.json. Stage 5.2. Mechanical scan in Python; you own only the human-in-the-loop naming.
---

# footage-intake

## Overview

You turn a folder of raw footage into what the edit-plan selects from: a typed
`FOOTAGE.json` (+ a readable `FOOTAGE.md`) of **scored candidate moment-windows**,
and — when the reel is about specific people — a `cast.json` hero registry. The
scan is mechanical Python (`scripts/intake.py`); the one thing it cannot do is
ask a human who the heroes are. That naming pass is yours.

**Core principle:** intake **ranks and flags**; it never picks the reel's
episodes or their order (that is 5.7 edit-plan + the episode-choice human loop).
Do not invent hero identities — a name you are unsure of is a question, not a guess.

## When to Use

Use when raw clips exist but there is no `FOOTAGE`/`cast` yet — the front of the
conveyor, before edit-plan. One invocation covers the whole footage folder.

Do NOT use for: choosing episodes, ordering, music/mood, or any encoding — those
are later stages.

## The Process

1. **Ensure env.** Intake needs a vidstab-enabled ffmpeg (it is the first runtime
   vidstab consumer). If `ffmpeg -hide_banner -filters` lacks `vidstabdetect`,
   run `bash setup.sh --with-vidstab` before continuing — the scan fails loud
   otherwise.

2. **Scan.** `python -m scripts.intake <footage_root> <out_dir>`. This writes
   `<out_dir>/FOOTAGE.json` + `FOOTAGE.md` (every clip logged: resolution, fps,
   shaky flag, scene cuts, and per clip a table of candidate windows with
   shot-type, people, motion, shake, score, and a `★` on the best moments), plus
   — from the same single YOLO-seg pass — candidate hero crops under
   `<out_dir>/cast_crops/candidate_*.png` and a `<out_dir>/cast_candidates.json`
   manifest (`id, source, conf, crop, descriptor`). Skim `FOOTAGE.md`: confirm
   every clip is logged and the starred windows look like real moments.

3. **Cast pass — only when people matter to the reel.** Read
   `cast_candidates.json` and look at each `candidate_*.png`. **Ask the human who
   each hero is** — any domain (family, athletes, friends, a vlogger). If the
   reel is scenery or the footage has no people (empty manifest), skip this step
   cleanly. Never name a candidate the human did not identify; leave unknowns out.

4. **Write cast.** For each named candidate, take its **persisted descriptor**
   from `cast_candidates.json` (already computed — do not recompute) and call
   `scripts.intake.write_cast(named, out_dir)` with
   `named = [(name, notes, descriptor, [candidate_crop_path]), …]`. This writes
   `<out_dir>/cast.json` — the hero registry `SPEC.cast` and future hero-pins
   read.

5. **Report the gate:** every clip logged · people tagged · moment-windows carved
   and scored · cast named (when applicable). Stop-and-report anything ambiguous —
   an unreadable clip, or a hero the human could not identify — rather than
   guessing.

## Boundaries

- Intake produces `FOOTAGE`/`cast` only. Selecting and ordering episodes is 5.7
  edit-plan; wiring hero descriptors into episode manifests (cast-name hero pins)
  is a later plan — 5.2 just produces `cast.json`.
- The scan is deterministic and mechanical; your judgment is confined to the
  interactive hero-naming. Do not hand-edit `FOOTAGE.json` scores or windows —
  if the scan looks wrong, report it.
