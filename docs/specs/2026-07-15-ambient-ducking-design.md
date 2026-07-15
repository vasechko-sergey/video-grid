# Ambient ducking (stage 5.12 audio-mix, ambient sub-slice) — design

**Status:** design · **Date:** 2026-07-15 · **Stage:** montage §5.12 (audio-mix)

Maps to montage design [§5.12](2026-07-05-montage-skillset-design.md) (audio-mix)
and grows the [music-spine](2026-07-11-music-spine-design.md) B2 mixer. Adds the
**ambient bed** — the original nat-sound of each clip, ducked under the music —
to today's music-only stem. SFX (whoosh on transitions) stays a later sub-slice.

## Scope decisions

1. **Ambient only.** This slice adds ducked ambient; the §5.12 SFX layer (whoosh
   on transitions) is a separate slice — it needs an asset (bundled `.wav` or
   ffmpeg-synth) plus transition-point placement, orthogonal to the ambient bed.
2. **Ambient ON by default**, ducked low. When a segment carries an audio stream
   it is mixed in as a subtle realism bed (music stays primary). A clean off
   switch (`ReelManifest.ambient=false`) restores today's pure-music stem — for
   reels whose nat-sound is unusable (wind, handling noise).
3. **Ducked ambient, not ducked music.** Per §5.12 ("music + ducked ambient"):
   the ambient is the sidechaincompress *main*, the music is the *sidechain key*
   — the ambient drops when the music swells, never the reverse.
4. **Source = the preserved raw segments**, not the locked clips. `extract`
   preserves each segment's audio (`ep{i}_raw.mp4`, `-c:a aac`); `reframe`
   strips it (`-an`, [reframe.py:191](../../scripts/reframe.py)) so the assembled
   master is silent. The ambient bed is built in parallel from the raw segments —
   we do **not** un-`-an` the picture render (assemble concats uniform silent
   streams by construction).
5. **One stem, deliver unchanged.** The ambient is baked into the single
   `audio.m4a` before the final two-pass loudnorm, so `deliver` still
   stream-copies one pre-normalized −14 LUFS stem and `check_reel`'s loudness
   gate still measures the finished stem. No deliver/check_reel change.
6. **The blocker in the pipeline-map is already gone.** `docs/pipeline-map.md`
   listed 5.12 as "blocked by extract per-ep audio passthrough (small 5.8
   change)". `extract` already preserves segment audio
   ([extract.py:14](../../scripts/extract.py)) — no 5.8 change is needed; 5.12
   ambient is unblocked today.

## §1 — Architecture & files

The mixer grows one optional input; everything downstream is untouched.

```
build_reel (picture passed, stem hook)
  └─ segments = [(ep.manifest["segment"], ep.manifest["target_dur"]) …]   # raw segs + final durs, EDL order
     mix.mix(music, work_dir, dur, segments = segments if rm.ambient else None)
            │
            ├─ _build_ambient(segments, tmp) ─► ambient.wav  (or None if every segment is silent)
            │      per (seg, dur): audio-stream?  yes → trim+pad to dur → pcm wav
            │                                     no  → anullsrc dur → pcm wav
            │      assembly.concat(wavs, ambient.wav)                    # reel-length bed, EDL order
            │
            └─ music frag (seek+fade)  +  ambient.wav
                   → sidechaincompress (ambient ducked by music)  → amix  → two-pass loudnorm −14 → audio.m4a
```

| File | Δ | Responsibility |
|------|---|----------------|
| `scripts/mix.py` | EDIT | `mix(music, out_dir, dur, segments=None)` grows the optional ambient path; new module-level `_build_ambient(segments, tmp_dir) -> str \| None` |
| `scripts/lib/models.py` | EDIT | `ReelManifest.ambient: bool = True` + `from_dict` reads `d.get("ambient", True)` |
| `scripts/build_reel.py` | EDIT | stem hook passes `segments` from the episodes' manifests when `rm.ambient` |
| `scripts/lib/assembly.py` | reuse | `concat()` (`-c copy`, stream-agnostic) concatenates the per-segment wavs |
| `scripts/draft.py` | none | its `mix.mix(...)` call keeps `segments=None` → music-only rough bed, unchanged |
| `scripts/deliver.py`, `scripts/check_reel.py` | none | one pre-normalized stem in, −14 gate on it — behaviour identical |

**Dependency DAG (new edges only):** `build_reel → mix._build_ambient → assembly.concat`.
`mix` still imports only `proc` + `models.MusicSpec`; `_build_ambient` adds no repo
import (shells ffmpeg/ffprobe via `proc`, concats via `assembly.concat`).

## §2 — The mix filtergraph

Today `mix()` is two ffmpeg passes: pass-1 seeks+fades the music fragment →
`frag.wav`; pass-2 measures then loudnorms `frag.wav` → `audio.m4a`. The ambient
path inserts **one filtergraph pass between them** and swaps the pass-2 input
from `frag.wav` to the mixed signal:

```
inputs: 0 = frag.wav (seeked+faded music, exactly dur)   1 = ambient.wav (reel-length bed)
filter_complex:
  [0:a] asplit=2 [msum][mkey]
  [1:a][mkey] sidechaincompress=threshold=0.03:ratio=4:attack=20:release=300 [duck]
  [msum][duck] amix=inputs=2:duration=first:weights='1 0.6' [mixed]
-map [mixed]  mixed.wav
```

- **`asplit`** — the music is used twice (as the amix sum term *and* as the
  sidechain key), so it must be split; ffmpeg forbids re-using a pad.
- **`sidechaincompress`** — main = `[1:a]` ambient, key = `[mkey]` music →
  ambient ducks when the music is loud. `threshold=0.03` (linear) ducks readily;
  `ratio=4`, `attack=20`ms, `release=300`ms — a soft, un-pumping duck. These are
  conservative defaults, tunable in one place.
- **`amix=duration=first`** — the *first* input (`[msum]`, the music, exactly
  `dur` from pass-1's `-t dur`) fixes the output length. The ambient bed is
  truncated or silence-padded to match — so the stem is **exactly** master-length
  regardless of per-segment rounding drift. This closes the sync landmine
  (`deliver`'s `-shortest` only absorbs sub-second jitter). `weights='1 0.6'`
  keeps the raw ambient below the music before ducking; the final loudnorm then
  lifts the *sum* to −14.

When `segments is None` or `_build_ambient` returns `None`, `mix()` skips the
filtergraph pass entirely and measures+loudnorms `frag.wav` exactly as today —
the music-only path is byte-for-byte the current behaviour (regression-pinned).

## §3 — `_build_ambient(segments, tmp_dir)`

```python
def _build_ambient(segments: list[tuple[str, float]], tmp_dir: str) -> str | None:
    """Concatenate each raw segment's audio, trimmed/padded to its final episode
    dur and ordered as given (EDL order), into one reel-length ambient bed.
    Segments with no audio stream contribute silence (anullsrc) so the bed stays
    in sync with the picture. Returns the ambient.wav path, or None when EVERY
    segment is silent (→ mix falls back to the music-only stem)."""
```

Per `(seg, dur)`:
- **has an audio stream** (`ffprobe -select_streams a`): `ffmpeg -i seg -t dur
  -vn -ac 2 -ar 48000 -af apad -c:a pcm_s16le amb_i.wav` — `apad` fills a
  short tail, `-t dur` caps → exactly `dur`, uniform 48 kHz stereo s16.
- **no audio stream**: `ffmpeg -f lavfi -i anullsrc=r=48000:cl=stereo -t dur
  -c:a pcm_s16le amb_i.wav`.

All per-segment wavs are uniform (48 kHz / stereo / s16), so
`assembly.concat(wavs, tmp_dir/ambient.wav)` (`-c copy`) joins them losslessly in
order. If no segment had audio, return `None` and log one stderr note (pure-music
stem — not an error).

## §4 — Contract change

One field on `ReelManifest` — the on/off control, mirroring how `music` (the
MUSIC.json path) already lives there:

```python
@dataclass
class ReelManifest:
    …
    music: str | None = None
    ambient: bool = True        # NEW — duck each clip's nat-sound under the music; False → pure-music stem
```

`from_dict`: `ambient=d.get("ambient", True)`. Validation: `ambient` is a plain
bool default; no `__post_init__` clause needed (a JSON `true`/`false`/absent all
resolve). No other contract touches — `ReelEpisode.manifest` already carries
`segment` and `target_dur` (the ambient source and the trim length).

## §5 — build_reel wiring

At the once-after-picture stem hook
([build_reel.py:47-49](../../scripts/build_reel.py)):

```python
if music is not None and audio is None:            # picture passed → build the stem once, re-check with it
    segments = [(e.manifest["segment"], e.manifest["target_dur"]) for e in rm.episodes]
    audio = mix.mix(music, work_dir, check_reel._probe_dur(master),
                    segments=segments if rm.ambient else None)
    continue
```

The episodes list is already in reel order, so `segments` is EDL-ordered. When
`rm.ambient` is False, `segments=None` → the current music-only stem. Everything
after (the `continue`, the re-check, `deliver`) is unchanged.

## §6 — Edge cases & fail-loud

- **A segment path is missing** → `_build_ambient`'s ffprobe/ffmpeg raises via
  `proc.run` (non-zero exit, fail loud) — same class as `assembly.probe_stream`.
- **`ambient=True` but no segment has audio** → `_build_ambient` returns `None`,
  `mix` builds the music-only stem, one stderr note. Graceful, not an error.
- **A segment's audio is shorter than its window** → `apad` pads the tail to
  `dur`; the picture-length gate already lives in `extract` (§5.8).
- **Ambient bed drifts from master length** → `amix=duration=first` pins the stem
  to the music length (= `dur` = probed master); no separate trim needed.
- **`dur` guards** (`dur<=0`, `dur > music.duration+0.1`, `dur < 2*_FADE`) are
  unchanged — they gate the music fragment before any ambient work.
- **Accepted limitation — texture, not lip-sync.** The bed is built from each
  segment's `target_dur`; per-clip frame rounding can accumulate a few frames of
  drift between a nat-sound event and its picture cut over a long reel. Acceptable
  because the ambient is a subtextual bed, not sync-critical diegetic audio; if an
  editor ever needs a foregrounded, frame-locked clip sound that is the deferred
  per-episode-level work (§9), not this bed.

## §7 — §12 landmines touched

- **Sync / silent-truncation (§12).** The ambient bed must equal the master
  length exactly; `amix=duration=first` (music = `dur`) enforces it — the design's
  primary guard against a stem that silently desyncs from the picture.
- **Audio seek is exempt** from the frame-accurate `-ss`-after-`-i` video
  landmine (per `mix.py`'s existing note) — `_build_ambient`'s per-segment
  `-i seg -t dur` re-encodes from 0, no seek involved.
- **`-an` is deliberate in `reframe`/`assemble`** — the ambient must NOT be
  sourced from the locked clips or the master; sourcing it from the raw segments
  keeps assemble's uniform-silent-stream invariant intact.

## §8 — Testing

- **Unit (`tests/test_mix.py`, mock `proc.run`)** — `_build_ambient`: the
  audio-present branch trims+pads, the video-only branch emits `anullsrc`,
  all-silent returns `None`, wavs concat in the given order. `mix(segments=None)`
  emits the current two-pass graph (regression pin — no filtergraph pass).
- **Real-ffmpeg integration (`tests/integration/test_ambient.py`,
  skip-if-no-ffmpeg)** — mirrors `test_mood`/`test_offset` synth idiom
  (`scipy.io.wavfile` + numpy): two segments carrying distinct tones + a music
  wav → `mix(segments=…)` → assert the stem measures −14 LUFS (loudnorm) **and**
  the ambient energy during a loud-music span is below its un-ducked `amix`
  baseline — proving the duck moves samples, not just wires the graph.
- **build_reel integration** — extend the music-spine golden
  (`tests/integration/test_music_spine.py`): segments carry audio, assert the
  delivered reel still measures −14 and the stem is longer-than-silent (ambient
  present). Kept light — the ducking proof lives in `test_ambient`.

## §9 — Non-goals (deferred)

- **SFX / whoosh on transitions** — its own slice (asset + transition placement).
- **Per-episode ambient level / mute** — no `EDLEpisode`/`ReelEpisode` audio
  field in v1; uniform bed. Add when an editor needs one clip's sound foregrounded.
- **Ducking-depth advisory in `check_reel`** — the −14 loudness hard gate already
  covers overall level; a "how deep did it duck" advisory is deferred.
- **A SPEC / reel-brief field** — v1 control is `ReelManifest.ambient` (default
  True); `using-montage` can thread an intent → the field later.

## §10 — Doc sync (on landing)

`docs/build-status.md` (Done entry + test count), `docs/pipeline-map.md` (5.12
◐→ closer to ✅; drop the stale "blocked by extract" note; Tally),
`docs/specs/2026-07-05-montage-skillset-design.md` §5.12 (Built blockquote),
`docs/specs/2026-07-11-music-spine-design.md` (ambient landed), `CLAUDE.md`
(registry rows for this design + its plan).
