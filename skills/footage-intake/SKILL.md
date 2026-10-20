---
name: footage-intake
description: "Conveyor stage — scan a folder of raw clips and photos into scored moment-windows (FOOTAGE.json/.md) and, when people matter, name the heroes into cast.json. Needs project.json. Required — feeds edit-plan. Conveyor position: after project-init, before contact-sheet. Tool index: references/tools.md."
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

## The Process

1. **Ensure env.** Intake needs a vidstab-enabled ffmpeg (it is the first runtime
   vidstab consumer). `bash setup.sh` installs one — `ffmpeg-full` carries
   `libvidstab` as baseline, no flag. Do **not** check by running
   `ffmpeg -hide_banner -filters` yourself: `ffmpeg-full` is keg-only, so a bare
   `ffmpeg` is a *different, slimmer* build and that probe answers about the
   wrong binary. The scan already fails loud with a remedy if the resolved
   binary lacks the filter.

2. **Scan.** `"$VG" scripts.intake <footage_root> <out_dir>`, where
   `<out_dir>` is `<footage_root>/montage/footage` — the run dir's `footage/`
   bucket, shared by every reel cut from this shoot; never the run root and never
   the footage folder itself (intake refuses a path that resolves to the footage
   root outright: its own outputs would be read as source clips by the next
   scan). This writes
   `<out_dir>/FOOTAGE.json` + `FOOTAGE.md` (every clip logged: resolution, fps,
   shaky flag, scene cuts, and per clip a table of candidate windows with
   shot-type, people, motion, shake, score, and a `★` on the best moments), plus
   — from the same single YOLO-seg pass — candidate hero crops under
   `<out_dir>/cast_crops/candidate_*.png` and a `<out_dir>/cast_candidates.json`
   manifest (`id, source, conf, presence, crop, crop_px, nameable, card,
   descriptor`), with one review card per candidate under `<out_dir>/cast_review/`. `score` is a
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

   **Photos are footage too** (design 2026-10-20). JPEG, PNG and HEIC/HEIF in the
   same folder are scanned beside the clips: each becomes one `photo` clip with
   one window of 2.0 s that pacing may stretch to 8.0 s, its people and shot size read
   by the same YOLO, decoded upright and in sRGB (a Display P3 iPhone photo is
   converted, not desaturated). Photos surface no cast candidates. The scan logs
   what it skipped by extension (`.dng`, `.webp` …) — say so to the user when it
   does — and names photo+video pairs sharing a name: those are usually iPhone
   Live Photos, and both halves enter as separate sources for now.

   `--win-min`/`--win-max` set the window length band a scan carves with —
   default `(1.2, 4.0)` seconds. The floor is the shortest shot the cut can have:
   edit-plan's length-band gate refuses a brief's `--asl` floor below whatever
   `FOOTAGE.json` was actually carved with, and names the remedy (a mood's band
   is only a suggestion and is logged instead). The band is part of the per-clip cache
   key, so changing either flag is a cache **miss**, never a silently stale
   result carved under the old numbers — but that means the first scan after
   raising or lowering the band re-scans the **whole** pool, one time, because
   every previously cached clip's key now differs. `Footage.band` in
   `FOOTAGE.json` records what a scan actually carved with, for anything
   downstream that reads it instead of assuming the default.

3. **Cast pass — only when people matter to the reel.** Read
   `cast_candidates.json` — each entry's `card` is what you show, `nameable` says
   whether to ask about it alone. Each entry
   records `crop_px` — the crop's real pixel size. **Say it out loud when you
   show a small one**: on the 2026-06 run seven of fifteen candidates were
   under 5000 px total and three were about 13x13, and the operator was asked
   to name them anyway. A candidate too small to identify is a candidate to
   skip, not to guess at; nothing interpolates it, because a smoothed 13x12
   crop looks like evidence and is not. **Show each candidate's `card`**
   (`cast_review/card_{i}.jpg`: the crop enlarged by whole pixels, captioned)
   **one per question** for every entry with `nameable: true`, and ask about all
   the `nameable: false` ones (long side under 96 px) in ONE question — "skip
   these N background figures?" — never one by one: the second real run asked
   ten such questions in a row. Show those cards together with that question and
   let the human name any of them anyway ("all but #7"). Candidates are
   **presence-ranked** — clustered by a person re-ID embedding and sorted by
   on-screen seconds, most-visible first — but the clustering is not identity
   you can rely on: on the second run (two people, a drone shoot) the descriptor
   tracked viewpoint more than person — one person surfaced as two entries and
   the other as three, and the closest man/woman pair sat at a cosine distance
   of 0.13 while the man's own front and back sat at 0.25. Expect the same person
   on several cards; the human's answer is the identity, not the cluster. **Ask the human
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
   `named = [(name, notes, descriptor, [candidate_crop_path]), …]`. Run it
   through the launcher like every other step — it imports `scripts`, so it
   needs the clone as working directory exactly as much as the scan does:

       "$VG" -c "
       import json
       from scripts import intake
       out_dir = '<out_dir>'
       cand = {c['id']: c for c in json.load(open(out_dir + '/cast_candidates.json'))}
       named = [(name, notes, cand[i]['descriptor'], [cand[i]['crop']])
                for i, name, notes in [(<id>, '<name>', '<notes>'), ]]
       print('cast.json:', [m.name for m in intake.write_cast(named, out_dir).members])
       "

   Fill one `(<id>, '<name>', '<notes>')` triple per candidate the human
   named, and leave out every candidate they did not. This writes
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
