---
name: pacing
description: Conveyor stage — fit the cuts edit-plan already chose onto the music's beat grid (PACING.json/.md). using-montage invokes this after edit-plan and music; run it directly only to re-fit. Snaps each cut to the coarsest grid level it can reach within a half-beat, then re-run `edit_plan build --pacing` to apply; the footage owns each cut's length, pacing only picks which musical lines cuts land on. Optional — a music-less reel skips it.
---

# pacing (stage 5.6, grid fit)

Pacing is a **fitter**, not a generator. edit-plan already chose the cuts and the
footage already fixed each cut's length; pacing takes those existing cuts and snaps
them onto the **coarsest musical grid level they can reach** — beat, half-bar, bar,
2-bar, or phrase — within a **half-beat** allowance, so the picture lands on the lines
a listener hears as intended (a downbeat reads as deliberate; the third beat of a bar
reads as accidental even when it is "on the beat"). **The cuts are the input; the grid
is the output.** The fit is only a proposal until you re-run `edit_plan build --pacing`,
which is what writes the snapped durations and `beat_slot` back into `EDL.json`.

A thin driver over the pure `scripts/lib/gridfit` + `scripts/lib/pacing` core.

## Inputs

- **`EDL.json`** (required, from edit-plan) — the cuts to fit. Pacing runs **after**
  edit-plan; the cut lengths already exist and pacing never invents them. No `EDL.json`
  means there is nothing to fit — run edit-plan first.
- **`FOOTAGE.json`** (required, from footage-intake) — each shot's room, so a cut's
  out-point may slide up to ±½ beat to reach a line but never past the room its own
  shot still has.
- **`MUSIC.json`** (one or more, from music-and-mood, stage 5.5) — the candidate
  windows. Shifting the window moves every grid line with it, so each candidate is
  analysed into its own `MUSIC_<k>.json` and the fit is searched across all of them.
  No `MUSIC.json` (a music-less reel)? Skip this stage — the EDL stays off-grid
  (`beat_slot` unset), a valid path. Named, not silent.

Not `SPEC.json`: the scenario's length is whatever the cuts sum to, not a target the
music dictates.

## The Process

Announce on entry: **"Using pacing to fit the cuts onto the music's grid."**

**Launcher.** Run every pipeline step through the repo's launcher `bin/vg`, never a
bare venv `python` binary. Resolve it once: `setup.sh` records the runtime's location
at `${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root`, so set
`VG="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")/bin/vg"` and run every
step as `"$VG" scripts.X`, passing **absolute** paths for every footage / run / output
directory. If that file is missing, the user has not run `bash setup.sh` — stop and
say so rather than guessing a path.

1. **Recon.** The EDL must already exist — pacing runs AFTER edit-plan (design
   2026-07-24 §1). No `EDL.json` -> run edit-plan first; this stage has nothing to fit.

   **Re-fitting is safe to repeat.** The fit reads each episode's `base_dur` — the
   length the scenario projected — not the length a previous bind or outro fit left
   behind, so fitting an already-fitted `EDL.json` produces the same spine and
   re-applying reproduces the same EDL (design 2026-08-16 §3.1). An `EDL.json`
   written before 2026-08-16 has no `base_dur`: the old deadlock still applies there,
   and `edit_plan build --pacing` says so by name in its refusal.
2. **Analyze the candidate windows.** `beats --auto-start` picks one; for a real choice
   ask it for more and analyze each into its own `MUSIC_<k>.json`. Shifting the window
   moves every grid line with it, so it is one of the two search axes.
3. **Fit.**
   `"$VG" scripts.pacing --edl <run>/EDL.json --footage <run>/FOOTAGE.json --music <run>/MUSIC.json [--music <run>/MUSIC_2.json ...] --out-dir <run>`
   Add `--anchors --footage-root <root>` to also measure action anchors (one ffmpeg pass
   per episode).
4. **Read the report.** `PACING.md` names the level chosen and every coarser level it
   rejected WITH the number that rejected it. A miss is actionable, not fatal: try
   another window, change a scenario length, or accept an off-grid reel (check_reel's
   beat gate is advisory).
5. **Apply.** `"$VG" scripts.edit_plan build ... --pacing <run>/PACING.json
   [--spec <run>/SPEC.json] [--music <run>/MUSIC.json]` — this is what writes the
   snapped durations and `beat_slot` into `EDL.json`. Carry `--spec` through when a
   brief exists: this pass re-stamps the EDL from scratch, so a dropped `--spec`
   re-resolves the variety preset to `balanced` **and wipes `EDL.platform` back to
   `""`**, which reverts `check_reel`'s safe zone and the bottom title's y layout to
   the generic table. `edit_plan build` logs the platform it resolved on every run —
   read that line to confirm the second pass kept it. Also pass `--music` (the SAME
   `MUSIC.json` step 3 analysed): it fits the reel's *end* to a bar line —
   `edit_plan`'s own outro ladder, distinct from this skill's cut-grid fit — by
   moving only the last episode, after this pass binds every slot. Omitting it
   leaves the reel ending wherever the footage happens to; see the **edit-plan**
   skill's step 3 for what each rung (`gap`/`no-gap`/`unchanged`) means. Stopping
   at step 4 leaves the EDL un-snapped.

## Not this skill

- **Generating or sizing cut lengths** → the material owns them (edit-plan + each
  shot's room, §2); pacing only chooses which grid lines the *existing* cuts land on.
  It fits; it never re-times an episode to a slot's length.
- **Choosing the track** (which song) → music-and-mood (`music-match` / `music-source`),
  not this. Pacing analyses the chosen track's candidate windows, but it does not pick
  the song.
- **Which footage plays, in what order** → edit-plan's `selection.json` (judgment),
  not this.
- **Re-timing an already-delivered reel** to hit a length target → `build_reel`'s
  within-band length re-time (design 2026-07-18); over-length still stop-and-reports.
