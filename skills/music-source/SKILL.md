---
name: music-source
description: "Music lane — source the reel's track from the internet by mood: discover candidates (free = CC; any = YouTube and friends, copyrighted and the user's responsibility), rank, download, and write MUSIC.json. Serves the music-and-mood stage. Optional — see music-match for a local folder. Tool index: references/tools.md."
---

# music-source (stage 5.5, network lanes)

Source a track from the internet + rank by mood, so the user picks from a short,
mood-sorted list instead of hunting a library. The **sibling of music-match**: same
ranking, candidates come from a catalog instead of the user's folder. This is the
**selection** pass; the chosen track still goes through `beats --auto-start` for the
final `MUSIC.json`.

**The ranking is numbers; the pick is judgment.** `music_find` scores each candidate's
preview (energy / brightness / pace) against `SPEC.mood`; you surface the top rows; the
user makes the final call (the §4.1 music checkpoint stays human-influenced).

## Rights lanes (`SPEC.music_mode`)

- **`free`** (default, safe for distribution) — Creative-Commons only. ccMixter (no key)
  by default; Jamendo (richer) when a `JAMENDO_CLIENT_ID` is configured. Direct legal
  download; every file records its CC license.
- **`any`** — includes **copyrighted** audio via yt-dlp (YouTube default; iTunes/Deezer
  with `--catalog`). **Legally gray and jurisdiction-dependent — opt-in, the user's
  responsibility.** Only use it when `SPEC.music_mode` is explicitly `any`. Every fetch
  logs a responsibility line and records `license="unknown (any lane)"`.
  For a reel posted where the app licenses the sound, the brief's `--music-in-app`
  makes the delivery also ship the reel without the song plus a note for attaching
  the track in the app.

## Inputs

- **`SPEC.json`** (from reel-brief) — `mood`, `length_s`, `music_mode`. No SPEC? pass
  `--mood "..." --mode free|any`.
- **`yt-dlp`** (needed for the `any` lane) ships with `bash setup.sh` — no separate
  install. The `free` lane needs no install either. A Jamendo `client_id` is optional
  (add it to `config/sourcing.env`) and only enriches the `free` lane's catalog.

## Procedure

Announce on entry: **"Using music-source to source and shortlist the reel's track by mood."**

1. **Recon.** Read `SPEC.json` (note `mood`, `length_s`, `music_mode`, `music_known`).
   The brief's `music_mode` IS the user's answer on rights: state the lane once when you
   present the shortlist and never re-ask it later or attach it as a caveat to every
   pick (the second real run's operator: "the music limits were asked at the start and I
   answered"). With no brief, confirm the lane — and for `any`, the rights
   responsibility — before sourcing.

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

2. **Find** (you type the flags; the user never does):
   `"$VG" scripts.music_find --mode <free|any> --spec <run>/reels/<reel>/SPEC.json --out-dir <run>/reels/<reel>`
   (or `--mood "energetic"`; add `--catalog itunes` / `--n 12` / `--query "..."` to steer).
   It writes `<run>/reels/<reel>/MUSIC_SHORTLIST.md` + `.json`.
   - **Known tracks.** `SPEC.music_known` (or `--popular`) searches Deezer by its own
     ranking and sorts the list by popularity, the mood fit still shown per row. Query
     with genre and mood words ("surf rock summer", "chill indie"), not with niche
     artist names — a name query returns that artist's catalogue, never the hits around
     it. When the brief wants known music and the list is all deep cuts, say so.
   - An **unrecognized mood** is not an error — it logs and ranks by drive (energy+pace);
     say so when you present the list.
   - **No candidates / no network / yt-dlp missing** fail loud — fix and re-run.
3. **Present** the top few `MUSIC_SHORTLIST.md` rows (rank · title · artist · source · fit ·
   popularity · axes · license). The user picks one — or asks to hear previews and picks
   by ear: fetch the candidates and send each one's `beats --preview` (step 5's command
   with `--preview <run>/music/previews/<name>.mp3`) — the exact window that will play,
   not the catalog's 30 s clip from elsewhere in the song.
4. **Fetch** the pick:
   `"$VG" scripts.music_fetch --mode <free|any> --from-shortlist <run>/reels/<reel>/MUSIC_SHORTLIST.json --pick <row> --cache-dir <run>/music/cache --date $(date +%F)`
   — prints the cached file path.
5. **Lock** it into `MUSIC.json`:
   `"$VG" scripts.beats <cached-file> --auto-start --duration <length_s> --out <run>/reels/<reel>/MUSIC.json`
   — start-offset intelligence starts the reel on the strongest fragment, in a vocal
   pause. Add `--preview <run>/music/previews/<name>.mp3` to also write that window as
   an mp3 for the user. Pass `<run>/reels/<reel>/MUSIC.json` on to edit-plan.

**Explicit track already chosen?** When `SPEC.music` is a track name (not `auto`), skip
Find/Present — `"$VG" scripts.music_fetch --mode <free|any> --track "<name>"
--cache-dir <run>/music/cache --date $(date +%F)` resolves the top-1 match in the lane and
fetches it directly; then Lock (step 5). A track that is already a local file path needs no
fetch — Lock it directly.

## Not this skill

- **A local folder** the user already has → **music-match** (the `local` lane), not this.
- **Writing `MUSIC.json`** → `beats --auto-start` (step 5), not this skill.
- **"Trending" sounds** → not a lane: trend scanning was removed on 2026-10-20. Sourcing
  ranks by mood, or by the catalog's own popularity with `--popular` — call that
  "popular", never "trending".
