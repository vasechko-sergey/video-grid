---
name: music-match
description: "Music lane — pick the reel's track from a LOCAL folder of candidates by mood-fit, ranked into MUSIC_SHORTLIST.md for the user to choose from. Serves the music-and-mood stage. Optional — skip when a track is already chosen; see music-source for the network lanes. Tool index: references/tools.md."
---

# music-match (stage 5.5, local lane)

Turn a **folder of candidate tracks** + the reel's mood into a ranked shortlist, so
the user picks a track by ear from a short, mood-sorted list instead of scrubbing a
whole library. Local and deterministic — no network, no downloads. This is the
**selection** pass; the chosen track still goes through `beats --auto-start` for the
final `MUSIC.json`.

**The ranking is numbers; the pick is judgment.** `mood.py` scores each track's
energy / brightness / pace against `SPEC.mood`; you surface the top rows; the user
makes the final call (the §4.1 music checkpoint stays human-influenced).

## Inputs

- **`SPEC.json`** (from reel-brief) — supplies `mood` and `length_s`. No SPEC? Pass
  the mood text directly with `--mood "..."`.
- **A candidate folder** — the user's own tracks (`music.mode=local`). Audio files
  only (`.mp3 .m4a .wav .flac .aac .ogg`).

## Procedure

Announce on entry: **"Using music-match to shortlist the reel's track by mood."**

1. **Recon.** Read `SPEC.json` (note `mood`, `length_s`) and confirm the candidate
   folder path with the user.

**Launcher and references.** Run every pipeline step through the plugin's launcher
`bin/vg`, never a bare `python`, and resolve every `references/…` read the same
way. Claude Code writes this plugin's own directory into the line below when it
loads the skill, so resolve it once:

    ROOT="${CLAUDE_PLUGIN_ROOT}"
    VG="$ROOT/bin/vg"

If `ROOT` comes out empty — a harness that does not fill the line in — it is the
directory two levels above this skill's base directory. Then run every step as
`"$VG" scripts.X`, read every reference as `"$ROOT/references/…"`, and pass
**absolute** paths for every footage / run / output directory. Nothing here is
relative to your working directory — a skill runs from the user's footage
project. If `"$VG"` says there is no runtime, it has not been set up yet: run the
`setup` skill (`/video-grid:setup`), which asks before installing anything.

2. **Rank** (you type the flags; the user never does):
   `"$VG" scripts.mood --folder <dir> --spec <run>/reels/<reel>/SPEC.json --out-dir <run>/reels/<reel>`
   (or `--mood "energetic"` when there is no SPEC). It writes
   `<run>/reels/<reel>/MUSIC_SHORTLIST.md` + `.json`.
   - An **unrecognized mood** is not an error — the tool logs it and ranks by drive
     (energy+pace); say so when you present the list.
   - An **empty / no-audio folder** fails loud — fix the path and re-run.
3. **Present** the top few `MUSIC_SHORTLIST.md` rows (rank · track · fit · the three
   axes). The user picks one — or asks to hear them and picks by ear.
4. **Lock the pick** into `MUSIC.json`:
   `"$VG" scripts.beats <picked-track> --auto-start --duration <length_s> --out <run>/reels/<reel>/MUSIC.json`
   — the start-offset intelligence starts the reel on the strongest fragment, in a
   vocal pause. Pass `<run>/reels/<reel>/MUSIC.json` on to edit-plan.

## Not this skill

- **Sourcing** a track from the internet (royalty-free or copyrighted) — that is the
  **music-source** skill (the `free`/`any` lanes); music-match ranks a **local folder**
  the user already has (`music.mode=local`).
- **Writing `MUSIC.json`** — that is `beats --auto-start` (step 4), not this skill.
- **The beat grid / loudness gate** — those are `beats.analyze` / `check_reel`.
