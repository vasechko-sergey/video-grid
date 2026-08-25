---
name: footage-intake
description: Conveyor stage — scan a folder of raw clips into scored moment-windows (FOOTAGE.json/.md) and, when people matter, name the heroes into cast.json. using-montage invokes this after project-init; run it directly only to (re)scan footage. Needs project.json. Mechanical scan in Python; you own only the human-in-the-loop naming. Required — feeds edit-plan.
---

# footage-intake

## Overview

You turn a folder of raw footage into what the edit-plan selects from: a typed
`FOOTAGE.json` (+ a readable `FOOTAGE.md`) of **scored candidate moment-windows**,
and — when the reel is about specific people — a `cast.json` hero registry. The
scan is mechanical Python (`scripts/intake.py`); the one thing it cannot do is
ask a human who the heroes are. That naming pass is yours. The scan analyses a
downscaled 960-long-side proxy of each clip while delivery always uses the
original frames, so a folder of 4K footage scans in seconds rather than hours.

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
   vidstab consumer). `bash setup.sh` installs one — `ffmpeg-full` carries
   `libvidstab` as baseline, no flag. Do **not** check by running
   `ffmpeg -hide_banner -filters` yourself: `ffmpeg-full` is keg-only, so a bare
   `ffmpeg` is a *different, slimmer* build and that probe answers about the
   wrong binary. The scan already fails loud with a remedy if the resolved
   binary lacks the filter.

2. **Scan.** `python -m scripts.intake <footage_root> <out_dir>`, where
   `<out_dir>` is `<footage_root>/montage` — the run dir, never the footage folder
   itself (intake refuses that outright: its own outputs would be read as source
   clips by the next scan). This writes
   `<out_dir>/FOOTAGE.json` + `FOOTAGE.md` (every clip logged: resolution, fps,
   shaky flag, scene cuts, and per clip a table of candidate windows with
   shot-type, people, motion, shake, score, and a `★` on the best moments), plus
   — from the same single YOLO-seg pass — candidate hero crops under
   `<out_dir>/cast_crops/candidate_*.png` and a `<out_dir>/cast_candidates.json`
   manifest (`id, source, conf, presence, crop, descriptor`). `score` is a
   **percentile within this footage set** (design 2026-08-06-intake-motion-scoring
   §4.2), never an absolute quality bar and never comparable to another shoot's
   numbers; `motion` is the window's raw mean per-sample subject displacement as a
   fraction of frame width, no display gain applied. Skim `FOOTAGE.md`: confirm
   every clip is logged and the starred windows look like real moments.

   Windows are **activity units**, not equal-length tiles: each is an activity
   peak plus its lead-in (windows may overlap a neighbor, never a fixed-size
   tiling), and carries `track_ids` — who is in it, resolved to names via
   `cast.json` once written. A flat, uneventful span yields one representative
   window, not a forced split.

   Two flags tune that same command: `--jobs N` controls how many clips are
   scanned in parallel (default 2 — a laptop thermally throttles at 3 full-clip
   passes; raise it on a cooled/desktop box, lower it on tight memory), and
   `--fresh` ignores the per-clip `.intake_cache`
   and rescans every clip (a plain re-run instead resumes: cached clips are
   skipped, only new/changed/failed ones re-scan). A bad/corrupt clip is
   quarantined rather than killing the scan — it is named in
   `<out_dir>/intake_report.json` and a `## Failed clips` section of
   `FOOTAGE.md`, and a re-run retries exactly the failed clips.

3. **Cast pass — only when people matter to the reel.** Read
   `cast_candidates.json` and look at each `candidate_*.png`. Candidates are
   **presence-ranked** — clustered into real identities (a person re-ID
   embedding, not a colour/clothing feature) and sorted by on-screen seconds
   across all clips, most-visible first — so each entry is one real person, not
   one track, and entry 0 is normally the easiest to recognize. **Ask the human
   who each hero is** — any domain (family, athletes, friends, a vlogger); name
   the people you recognize and skip the rest. If the reel is scenery or the
   footage has no people (empty manifest), skip this step cleanly. Never name a
   candidate the human did not identify; leave unknowns out. If intake printed a
   `WARNING: torchreid not installed` line, `cast_candidates.json` is empty
   regardless of how many people are on screen — that is a missing dependency,
   not an empty cast: run `bash setup.sh` to install it, then re-run intake with
   `--fresh` to rebuild the cast.

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
  edit-plan; wiring hero descriptors into episode manifests is the cast →
  hero-pin slice (2026-07-16) — `cast.json` is now read by `edit-plan --cast` →
  `EDL.cast` → the manifest → `track`, so a cast name in `selection.json`
  resolves into a real pin. 5.2's own scope stays just producing `cast.json`.
- The scan is deterministic and mechanical; your judgment is confined to the
  interactive hero-naming. Do not hand-edit `FOOTAGE.json` scores or windows —
  if the scan looks wrong, report it.
