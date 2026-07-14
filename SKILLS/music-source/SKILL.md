---
name: music-source
description: Stage 5.5 (network lanes) — source the reel's track from the internet when the brief has a mood but no chosen track and no local folder. Discovers candidates (free = ccMixter/Jamendo CC; any = YouTube/iTunes/Deezer incl. copyrighted), ranks them by fit to SPEC.mood into MUSIC_SHORTLIST.md, you present the top few, the user picks, then it downloads the pick and beats --auto-start writes MUSIC.json. The any lane is copyrighted and legally gray — opt-in, user's responsibility.
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

## Inputs

- **`SPEC.json`** (from reel-brief) — `mood`, `length_s`, `music_mode`. No SPEC? pass
  `--mood "..." --mode free|any`.
- **`yt-dlp`** is needed for the `any` lane — `bash setup.sh --with-sourcing` (opt-in).
  The `free` lane needs no install.

## Procedure

Announce on entry: **"Using music-source to source and shortlist the reel's track by mood."**

1. **Recon.** Read `SPEC.json` (note `mood`, `length_s`, `music_mode`). Confirm the lane
   with the user — and for `any`, confirm they accept the copyright/rights responsibility
   before sourcing.
2. **Find** (you type the flags; the user never does):
   `.venv/bin/python -m scripts.music_find --mode <free|any> --spec <run>/SPEC.json --out-dir <run>`
   (or `--mood "energetic"`; add `--catalog itunes` / `--n 12` / `--query "..."` to steer).
   It writes `<run>/MUSIC_SHORTLIST.md` + `.json`.
   - An **unrecognized mood** is not an error — it logs and ranks by drive (energy+pace);
     say so when you present the list.
   - **No candidates / no network / yt-dlp missing** fail loud — fix and re-run.
3. **Present** the top few `MUSIC_SHORTLIST.md` rows (rank · title · artist · source · fit ·
   axes · license). The user picks one — or asks to hear previews and picks by ear.
4. **Fetch** the pick:
   `.venv/bin/python -m scripts.music_fetch --mode <free|any> --from-shortlist <run>/MUSIC_SHORTLIST.json --pick <row> --cache-dir <run>/music/cache --date $(date +%F)`
   — prints the cached file path.
5. **Lock** it into `MUSIC.json`:
   `.venv/bin/python -m scripts.beats <cached-file> --auto-start --duration <length_s> --out <run>/MUSIC.json`
   — start-offset intelligence starts the reel on the strongest fragment, in a vocal
   pause. Pass `<run>/MUSIC.json` on to edit-plan.

**Explicit track already chosen?** When `SPEC.music` is a track name (not `auto`), skip
Find/Present — `.venv/bin/python -m scripts.music_fetch --mode <free|any> --track "<name>"
--cache-dir <run>/music/cache --date $(date +%F)` resolves the top-1 match in the lane and
fetches it directly; then Lock (step 5). A track that is already a local file path needs no
fetch — Lock it directly.

## Not this skill

- **A local folder** the user already has → **music-match** (the `local` lane), not this.
- **Writing `MUSIC.json`** → `beats --auto-start` (step 5), not this skill.
- **Trend-sound presence** in the ranking → deferred with 5.4 trend-scan; sourcing ranks
  by mood only.
