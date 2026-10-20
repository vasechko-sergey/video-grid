# Music in the app — a music-less delivery and a sound note

**Status:** built 2026-10-20 (0.25.0). Backlog U3.

## §0 · Why

A track sourced through the `any` lane is downloaded with `yt-dlp`, and a song baked
into an uploaded file can be muted or blocked. On Instagram, TikTok and Shorts the
licence comes with the sound attached *inside the app* (the 2026-10-20 trend research,
the rights section). The second real run's reel is exactly this case: The Drums,
"Let's Go Surfing", fetched from YouTube.

So the user who will post with the in-app sound needs two things the engine does not
give today:

1. **the reel with the song removed and everything else kept**: the same picture,
   titles and look, and whatever natural sound and transition whooshes the reel has;
2. **a note** saying which track to attach and where in it the reel's music starts,
   because the cuts were fitted to that window (design 2026-07-24, scenario-first
   pacing).

The design spec's §5.14 described this as a delivery mode and it was parked; the
"trending sound" half went with U1. What remains is purely about rights.

## §1 · The brief records it; the reel carries it

`SPEC.music_in_app` (bool, default `False`), asked in the brief whenever the reel
has music, and recorded with `reel_brief --music-in-app`. A brief with `music: "none"`
refuses it, since there is nothing to attach. It rides the same pipe `platform` and
`brief_len` already ride, so it survives every re-cut that passes `--spec`, and
`edit_plan` logs it on every run so a dropped `--spec` on the pacing pass is seen:

`SPEC` → `edit_plan --spec` → `EDL.music_in_app` → `edl_to_reel` →
`ReelManifest.music_in_app` → `build_reel`'s deliver arm.

`ReelManifest` refuses `music_in_app` with no `music`, because a note with no track
is not a note; the remedy is `edl_to_reel --music`, and `edl_to_reel` refuses it
before the pool renders anything. `EDL` and `ReelManifest` omit the key when it is
`False`, so a run that never asked is byte-identical to one made before the field
existed; `SPEC.json` always writes it, as it does `music_known`.

## §2 · The stem: the music version with the song muted

The music-less stem is defined as *what the with-music stem sounds like with the
music track muted*, not as a fresh mix.

- **No ducking.** The ambient bed is ducked by `sidechaincompress` keyed on the
  music. With the music removed, the duck would still pump to a song that is not
  there, so the music-less graph has no key and no compressor.
- **The same weights.** `amix`'s default `normalize=1` scales each input by
  1/N, where N is the music mix's input count. The music-less graph uses
  `normalize=0` with the ambient and SFX weights the music mix gave them
  (`0.6/N`, `_SFX_MIX/N`).
- **The same gain.** loudnorm's second pass lifts the music mix to −14 LUFS. The
  music-less stem takes that gain, `−14 − measured_I`, as a plain `volume` and is
  **not** normalized again. Normalized alone to −14, an ambient bed would come up
  10–20 dB and lift the wind noise. In the app the user sets "original audio"
  against the added track anyway.
- **A ceiling, not a target.** Un-ducked, a wave crash can peak higher than it did
  under the duck, so an `alimiter` at the stem's true-peak target (−1.5 dBFS)
  catches it. It limits sample peaks, so it is not a true-peak limiter: the review
  measured a white-noise bed at −2.4 dBFS sample peak and +2.9 dBTP. **Landmine:** `alimiter` defaults to `level=true`, an *auto level*
  that silently normalizes its output up. The stem passes `level=0` (and
  `latency=1`, so the lookahead does not shift the sound against the picture).
- The same bookend fades as the music stem.
- **Nothing to keep → silence.** No ambient and no SFX gives a silent stem of the
  reel's length. A silent picture to add the sound to is still the deliverable.

`mix.mix(..., without_music=path)` renders it inside the same temp directory and
from the same beds and measurement as the music stem, so the two cannot drift
apart.

## §3 · Where it lands

`deliveries/no-music/REEL_v{n}.mp4` and `deliveries/no-music/REEL_v{n}.sound.md`
use the **same `n`** as the delivered reel they come from.

A subfolder, not a sibling, and that is load-bearing. Every delivery reader keys on
`REEL_v*` in the deliveries bucket:
- `montage._deliveries` would list a sibling as an unattested delivery;
- `montage._newest_delivery` matches `REEL_v(\d+)\.` and could return the sibling,
  making a review of `REEL_v5.mp4` read as stale.

`glob` does not recurse, so a subfolder is invisible to all of them, and it stays
inside the bucket that only grows.

The picture is the delivered file's own video stream, stream-copied (`-c:v copy`),
so it is byte-identical to the attested reel's picture. The file itself is not
attested: `check_reel` judged the with-music deliverable. The note says so and
records the source reel's digest.

## §4 · The note

- The track: artist and title from `music_fetch`'s sidecar, read through one
  helper `fetch.track_meta` (also `reel_review`'s), or the file name when there is
  no sidecar.
- Where the reel's music starts in the track (`MUSIC.start_offset`, as m:ss.s) and
  how long it runs (the reel's length).
- The cut times, so the start can be checked by ear: the first cut should land on
  a beat.
- The steps in the app.
- **The caveat this design cannot close:** the offset is measured on the file that
  was downloaded. A music video's audio can begin earlier or later than the app's
  version of the song, and a sped-up or remixed edit has a different beat grid. If
  the first cut is off the beat, the user nudges the start by ear.

## §5 · Honest limits

- The music-less file is not loudness-checked; its level is the music version's
  gain, not a target.
- The gain is loudnorm's *linear-mode* gain. loudnorm stays linear only while the
  measured range and the lifted true peak fit its targets; otherwise it rides a
  dynamic gain, and the review measured the music-less ambient **4.9 and 6.3 dB**
  quieter than the music version's on wide-range fixtures. `mix` records which case
  it was (`audio_no_music.json`, beside the stem), `build_reel` logs it, and the note
  tells the user to set the level by ear.
- The note's "the first cut lands on a beat" check holds only when a pacing pass
  fitted the cuts to the music (`ReelManifest.outro` is present), so without one the
  note says the start is only where the music was taken from.
- Nothing proves the app's catalogue has the track, or that its version matches
  the downloaded one (§4's caveat).
- No test listens to it. The proofs pin the graph (no compressor, `normalize=0`,
  `level=0`), the silence case, that the music-less ambient matches the music stem's
  within 3 % where the duck has released, for mono and stereo tracks, and that the
  picture's packets are byte-identical.
