---
name: pacing
description: Stage 5.6 — derive the reel's energy spine from MUSIC.json (PACING.json+.md), so edit-plan cuts with a density that rises and falls with the music (fast cuts on the drop, long holds when quiet), hook first. Runs after music-and-mood, before edit-plan. Optional — a music-less reel skips it and edit-plan runs pacing-less.
---

# pacing (stage 5.6, energy spine)

Turn the chosen track's beat grid + energy curve into an **energy spine**: an ordered
list of beat-aligned slots, each with a target length and an energy level, cut density
rising with the music. `edit-plan` then binds its episodes to the slots (`beat_slot` +
per-episode target length), so picture and music are **one arc**, not two glued halves.
A thin driver over the pure `scripts/lib/pacing` core.

**The spine is footage-blind numbers; selection is judgment.** Pacing derives the
skeleton from the music alone (before edit-plan); `edit-plan`'s `selection.json` still
decides *which* footage fills each slot. Pacing owns the per-slot length + energy target.

## Inputs

- **`MUSIC.json`** (from music-and-mood, stage 5.5) — beat grid + RMS energy curve +
  duration. No MUSIC.json (a music-less reel)? Skip this stage — edit-plan runs
  pacing-less (`beat_slot` stays null). Named, not silent.
- **`SPEC.json`** (optional) — cross-checks `length_s` against the fragment length.

## Procedure

Announce on entry: **"Using pacing to derive the reel's energy spine from the music."**

**Launcher.** Run every pipeline step through the repo's launcher `bin/vg`, never a
bare venv `python` binary. Resolve it once: `setup.sh` records the runtime's location
at `${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root`, so set
`VG="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")/bin/vg"` and run every
step as `"$VG" scripts.X`, passing **absolute** paths for every footage / run / output
directory. If that file is missing, the user has not run `bash setup.sh` — stop and
say so rather than guessing a path.

1. **Derive** (you type the flags; the user never does):
   `"$VG" scripts.pacing --music <run>/MUSIC.json --spec <run>/SPEC.json --out-dir <run>`
   — writes `<run>/PACING.json` + `<run>/PACING.md`. A `SPEC.length_s` that disagrees
   with the fragment logs a re-pick remedy (the spine follows the fragment).
2. **Sanity-check** the `PACING.md` slot table — the arc should open with a short
   `hook`, tighten to short `peak` slots on the drop, and stretch to long `release`
   slots when quiet. A wrong-looking arc means the fragment is off — re-pick with
   `beats --auto-start` (a different `start_offset`).
3. **Bind** — pass `<run>/PACING.json` to edit-plan:
   `"$VG" scripts.edit_plan build --footage <run>/FOOTAGE.json --selection <run>/selection.json --project <run>/project.json --out-dir <run> --pacing <run>/PACING.json`
   Each episode gets `beat_slot=i` and its window re-timed to slot `i`'s length; a
   count mismatch (more episodes than slots, or vice-versa) is logged, never silent.

## Not this skill

- **Choosing/analyzing the track** → music-and-mood (`beats`), not this.
- **Which footage fills a slot** → edit-plan's `selection.json` (judgment), not this.
- **Re-timing an already-delivered reel** to hit a length target → deferred (the
  retry-time auto-fix; today `build_reel`'s `length` failure stop-and-reports).
