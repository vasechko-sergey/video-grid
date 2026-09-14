# music-and-mood — router stage 7

**music-and-mood (optional).** The cuts already exist (step 6), so the reel's
length is the sum of `EDL.json`'s episode durations — analyse the track against
**that** length, not a SPEC target. Point music-source's fetch at the shared
bucket — `--cache-dir <run>/music/cache` — whenever it runs below: the
downloaded audio is a function of the *track*, not the cut, so it survives a
second `--reel` variant instead of re-fetching (`music-match` only ranks a
local folder already on disk, so it never downloads and never touches this
bucket). If the brief names a **track**:
- a **local file path** -> analyse it directly, preferring the tool's own
  in-point pick: `"$VG" scripts.beats <track> --auto-start
  --duration <reel_len> --out <run>/reels/<reel>/MUSIC.json` — it starts the reel on the
  strongest fragment, in a vocal pause. The pauses come from demucs (installed
  by `bash setup.sh`, and required — step 0 already blocked if it is missing);
  there is no proxy fallback. Pass an explicit `--start-offset S` instead only
  to override.
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
