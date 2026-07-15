# Transition SFX (stage 5.12 audio-mix, whoosh sub-slice) — design

**Status:** design · **Date:** 2026-07-15 · **Stage:** montage §5.12 (audio-mix)

Maps to montage design [§5.12](2026-07-05-montage-skillset-design.md) (audio-mix)
and closes it: the [music-spine](2026-07-11-music-spine-design.md) B2 mixer grew a
music-only stem, then the [ambient bed](2026-07-15-ambient-ducking-design.md); this
slice adds the last §5.12 piece — a **whoosh on major transitions**, synthesized
by ffmpeg (no assets) and mixed on top of the music-and-ambient stem before the
final loudnorm. With it landed, 5.12 is complete.

## Scope decisions

1. **Synthesized whoosh, no assets.** Each whoosh is rendered on the fly by ffmpeg
   (pink noise → bandpass → fade envelope), not shipped as a `.wav`. No binary in
   the repo, nothing to license or download, deterministic (fixed `anoisesrc`
   seed), and provable with the same numpy/DFT idiom as the ambient/mood/offset
   golden fixtures. A real designed whoosh sample and a true pitch-sweep are a
   deferred refinement (§10); v1 is a filtered-noise swell that reads as a whoosh.
2. **Off by default, opt-in.** `ReelManifest.sfx = False`. A whoosh on transitions
   is a strong stylistic choice (TikTok-accent), not a universal realism lift like
   the ambient bed — so it is enabled deliberately (`sfx = true`), the mirror of
   "a default must not impose taste". Contrast the ambient bed, which defaults ON.
3. **Major transitions only.** The whoosh accents a *scene change*, not every
   rapid cut. A cut is "major" when the longer of its two adjacent clips exceeds
   the median clip length (§3) — so it fires when the cut touches a held/hero shot
   on either side and stays silent through the middle of a fast montage run (both
   neighbours short). A min-gap throttle is a secondary guard against a close
   double. Uniform pacing (all durs equal → nothing exceeds the median) → no
   whooshes, correctly.
4. **One stem, deliver unchanged.** The whoosh track is baked into the single
   `audio.m4a` before the final two-pass loudnorm, exactly like the ambient bed —
   so `deliver` still stream-copies one pre-normalized −14 LUFS stem and
   `check_reel`'s loudness gate still measures the finished stem. No
   deliver/check_reel change. (The design-§5.14 "music-less export keeps
   ambient/SFX" split is a separate future deliver feature, §10 — orthogonal to
   baking the stem here.)
5. **Whoosh punches, it is not ducked.** Unlike the ambient bed (ducked *under*
   the music via sidechaincompress), the whoosh is an accent meant to be heard —
   it enters the final `amix` un-ducked, its level set by one `volume` constant and
   trimmed to −14 by the same final loudnorm.

## §1 — Architecture & files

The mixer grows one more optional input; everything downstream is untouched.

```
build_reel (picture passed, stem hook)
  └─ want = rm.ambient or rm.sfx
     segments = [(ep.manifest["segment"], ep.manifest["target_dur"]) …] if want else None
     mix.mix(music, work_dir, dur, segments=segments, ambient=rm.ambient, sfx=rm.sfx)
            │
            ├─ _build_ambient(segments, tmp) ─► ambient.wav | None      (unchanged, §5.12 ambient)
            ├─ _build_sfx([dur …], tmp)       ─► sfx.wav     | None
            │      major cuts: max(d[k],d[k+1]) > factor·median(durs), min-gap throttled
            │      synth whoosh once → adelay copies onto the cut offsets → amix(normalize=0)
            │
            └─ music frag  (+ ambient ducked)  (+ sfx on top)
                   → amix(duration=first) → two-pass loudnorm −14 → audio.m4a
```

| File | Δ | Responsibility |
|------|---|----------------|
| `scripts/mix.py` | EDIT | `mix(music, out_dir, dur, segments=None, ambient=True, sfx=False)`; new `_build_sfx(durs, tmp_dir) -> str \| None` + `_whoosh(tmp_dir) -> str`; the filtergraph composes the optional ambient/sfx layers (four cases) |
| `scripts/lib/models.py` | EDIT | `ReelManifest.sfx: bool = False` + `__post_init__` bool guard + `from_dict` `d.get("sfx", False)` |
| `scripts/build_reel.py` | EDIT | stem hook: pass `segments` when `rm.ambient or rm.sfx`, plus `ambient=rm.ambient, sfx=rm.sfx` |
| `scripts/lib/assembly.py` | none | (SFX uses `adelay`+`amix`, not `concat`) |
| `scripts/draft.py` | none | its `mix.mix(...)` keeps `segments=None` → music-only rough bed, unchanged |
| `scripts/deliver.py`, `scripts/check_reel.py` | none | one pre-normalized stem in, −14 gate on it — behaviour identical |

**Dependency DAG (new edges only):** `build_reel → mix._build_sfx → mix._whoosh`.
`mix` gains one stdlib import (`statistics.median`); `_build_sfx`/`_whoosh` add no
repo import (they shell ffmpeg via `proc`).

## §2 — The mix filtergraph

Today `mix()` seeks+fades the music → `frag.wav`, then (when an ambient bed
exists) ducks the ambient under the music in one filtergraph pass, then
measures+loudnorms → `audio.m4a`. This slice makes the middle pass compose the
optional layers so the same code path serves all four cases. The music-only and
**ambient-only graphs stay byte-for-byte identical** to today (regression-pinned):

**Inputs** (order): `0 = frag.wav` (music, exactly `dur`), then `ambient.wav` if
built, then `sfx.wav` if built.

- **music-only** (no ambient, no sfx): no filtergraph pass — measure+loudnorm
  `frag.wav`, exactly as today.
- **ambient-only** (bed, no sfx): today's exact graph —
  ```
  [0:a]asplit=2[msum][mkey];
  [1:a]volume=0.6[amb];
  [amb][mkey]sidechaincompress=threshold=0.03:ratio=4:attack=20:release=300[duck];
  [msum][duck]amix=inputs=2:duration=first[mixed]
  ```
- **sfx-only** (no ambient, sfx bed = input 1): music needs no split (used once) —
  ```
  [1:a]volume=_SFX_MIX[sfx];
  [0:a][sfx]amix=inputs=2:duration=first[mixed]
  ```
- **ambient + sfx** (ambient = input 1, sfx = input 2):
  ```
  [0:a]asplit=2[msum][mkey];
  [1:a]volume=0.6[amb];[amb][mkey]sidechaincompress=threshold=0.03:ratio=4:attack=20:release=300[duck];
  [2:a]volume=_SFX_MIX[sfx];
  [msum][duck][sfx]amix=inputs=3:duration=first[mixed]
  ```

The graph is assembled programmatically from three optional terms (`[msum]`, the
ducked `[duck]`, the `[sfx]`) so the input indices track which beds exist; the
ambient-only and music-only branches emit the identical strings they do today.

- **`amix=duration=first`** — the *first* term is always the music (`[msum]` or
  `[0:a]`), exactly `dur` from the seek's `-t dur`; it fixes the output length. A
  short sfx bed (whooshes near the start) is silence-padded, a long one truncated
  — the stem is **exactly** master-length regardless of per-clip rounding drift
  (the §12 sync landmine, same guard the ambient bed uses).
- **whoosh un-ducked** — `[sfx]` enters `amix` at its own `_SFX_MIX` volume, not
  through the sidechain; the final loudnorm lifts the *sum* to −14.
- **amix normalize** — the ambient/sfx amix keeps ffmpeg's default `normalize=1`
  (a uniform pre-loudnorm attenuation the final loudnorm cancels); it does not
  change the ratio between layers, so the whoosh's relative punch is set by
  `_SFX_MIX` and the whoosh synth amplitude alone.

## §3 — `_build_sfx(durs, tmp_dir)`

```python
def _build_sfx(durs: list[float], tmp_dir: str) -> str | None:
    """Render a whoosh at each MAJOR internal cut of a reel whose episodes have the
    given durations (EDL order), returning the sfx-bed wav path — or None when the
    reel has no major cut (fewer than two clips, or none exceed the median). A cut
    between ep[k] and ep[k+1] sits at the cumulative offset T[k]=sum(durs[:k+1]); it
    is major when max(durs[k], durs[k+1]) > _MAJOR_FACTOR * median(durs), and kept
    only if at least _MIN_GAP past the previous kept whoosh (throttle). The whoosh
    is synthesized once (_whoosh) and placed by adelay onto the cut offsets."""
```

Logic:
- `len(durs) < 2` → `None` (no internal transition).
- `med = statistics.median(durs)`; for `k` in `0 … len(durs)-2`: the cut is major
  iff `max(durs[k], durs[k+1]) > _MAJOR_FACTOR * med`. Offset `T[k] =
  sum(durs[:k+1])`.
- **Throttle:** walking majors in time order, keep one only if `T[k] - last_kept ≥
  _MIN_GAP`. (Majors are already sparse; this just kills an accidental close
  double.)
- No kept offset → `None`.
- Else: `whoosh = _whoosh(tmp_dir)` once, then one ffmpeg call places a delayed
  copy per offset onto a finite silent base and amixes them (normalize off so the
  whoosh keeps its level):
  ```
  ffmpeg -y -t {total} -f lavfi -i anullsrc=r=48000:cl=stereo -i {whoosh}
    -filter_complex
      "[1:a]asplit={K}[w0]…[w{K-1}];
       [w0]adelay={start0_ms}:all=1[d0]; … ;
       [0:a][d0]…[d{K-1}]amix=inputs={K+1}:duration=first:normalize=0[sfx]"
    -map [sfx] -c:a pcm_s16le {tmp_dir}/sfx.wav
  ```
  `total = sum(durs)`; the base's `-t total` bounds the (otherwise infinite)
  `anullsrc` and `duration=first` pins the bed to it (mix's own
  `amix=duration=first` then re-pins to the music `dur` — a short/long bed is
  padded/trimmed there). `start_k = max(0, T[k] - _SFX_LEAD)` so the whoosh's fast
  attack peaks near the cut; `adelay` is milliseconds, `:all=1` delays both
  channels.

`_whoosh(tmp_dir)` renders the single whoosh (uniform 48 kHz stereo s16):
```
ffmpeg -y -f lavfi -i anoisesrc=color=pink:r=48000:d={_SFX_DUR}:a=0.9:seed={_SFX_SEED}
  -af "bandpass=f={_SFX_FREQ}:width_type=q:w={_SFX_Q},
       afade=t=in:st=0:d={_SFX_ATTACK},
       afade=t=out:st={_SFX_ATTACK}:d={_SFX_DUR-_SFX_ATTACK}"
  -ac 2 -ar 48000 -c:a pcm_s16le {tmp_dir}/whoosh.wav
```
Pink noise (airier than white) through a resonant bandpass around `_SFX_FREQ`, a
fast attack then a decay over the tail — a swell that reads as a transition
whoosh. `seed` fixes it so the golden is reproducible.

**Constants** (grouped in `mix.py`, tunable in one place like the sidechain
params):

| Const | Default | Meaning |
|-------|---------|---------|
| `_MAJOR_FACTOR` | `1.0` | a cut is major when `max(neighbour durs) > factor·median`; raise to thin whooshes |
| `_MIN_GAP` | `0.6` | min seconds between kept whooshes (throttle) |
| `_SFX_DUR` | `0.35` | whoosh length (s) |
| `_SFX_FREQ` | `1200` | bandpass centre (Hz) |
| `_SFX_Q` | `0.7` | bandpass width (Q; smaller = wider/airier) |
| `_SFX_ATTACK` | `0.08` | whoosh rise time (s); peak lands here |
| `_SFX_LEAD` | `0.2` | seconds the whoosh starts before the cut so its peak sits near it |
| `_SFX_MIX` | `1.0` | whoosh volume entering the final amix (relative punch) |
| `_SFX_SEED` | `42` | `anoisesrc` seed (deterministic whoosh) |

## §4 — Contract change

One field on `ReelManifest`, the on/off control, mirroring `ambient`:

```python
@dataclass
class ReelManifest:
    …
    music: str | None = None
    ambient: bool = True        # duck each clip's nat-sound under the music; False → pure-music stem
    sfx: bool = False           # NEW — whoosh on major transitions; default off (opt-in stylistic accent)
```

`from_dict`: `sfx=d.get("sfx", False)`. `__post_init__` gains a bool guard
mirroring `ambient`'s (fail loud on a non-bool):

```python
if not isinstance(self.sfx, bool):
    raise ValueError(f"ReelManifest.sfx must be a bool (True → whoosh on major "
                     f"transitions, False → no SFX), got {self.sfx!r}")
```

No other contract touches — `ReelEpisode.manifest` already carries `target_dur`
(the durations the major-cut detector needs), and the whoosh source is synthesized.

## §5 — build_reel wiring

At the once-after-picture stem hook
([build_reel.py:47-51](../../scripts/build_reel.py)):

```python
if music is not None and audio is None:            # picture passed → build the stem once, re-check with it
    want = rm.ambient or rm.sfx
    segments = ([(e.manifest["segment"], e.manifest["target_dur"]) for e in rm.episodes]
                if want else None)
    audio = mix.mix(music, work_dir, check_reel._probe_dur(master),
                    segments=segments, ambient=rm.ambient, sfx=rm.sfx)
    continue
```

`ambient` is now an explicit flag rather than "segments given?" — because SFX also
needs the durations from `segments` but may run with the ambient bed off
(`ambient=False, sfx=True`). Passing `segments` whenever *either* layer is on, and
gating each layer by its own bool inside `mix`, cleanly separates the two intents.
When both are False, `segments=None` → today's music-only stem. Everything after
(the `continue`, the re-check, `deliver`) is unchanged.

## §6 — Edge cases & fail-loud

- **Fewer than two episodes** → `_build_sfx` returns `None` (no internal cut);
  `mix` skips the sfx layer. A one-clip reel simply gets no whoosh.
- **No cut exceeds the median** (uniform pacing) → `None`; music (+ambient) stem
  only. Correct: a reel with no held-shot contrast has no scene change to accent.
- **`sfx=True` but `segments` is None** (both flags off is the only way build_reel
  passes None; but a direct caller could) → `mix` has no durs, skips the sfx layer
  gracefully — the whoosh needs the episode durations, absent them there is nothing
  to place.
- **A whoosh would start before 0** (a major cut within `_SFX_LEAD` of the reel
  start — only possible when ep0 is shorter than the lead) → `adelay` is clamped to
  `≥ 0`, the whoosh simply starts at 0.
- **ffmpeg failure** (bad lavfi expr, etc.) → `proc.run` non-zero exit, fail loud —
  same class as the ambient/`assembly` shells.
- **Accepted limitation — accent, not lip-sync.** Offsets are cumulative
  `target_dur`s; per-clip frame rounding can drift the whoosh a few frames from the
  exact picture cut over a long reel. Acceptable — the whoosh is an accent swell,
  not sync-critical diegetic audio (same accepted texture-not-lip-sync limitation
  as the ambient bed).

## §7 — §12 landmines touched

- **Sync / silent-truncation (§12).** The sfx bed must not stretch the stem;
  `mix`'s `amix=duration=first` (first term = music = `dur`) pins the stem to the
  master length, padding/trimming the bed — the same guard the ambient bed uses.
- **Audio seek is exempt** from the frame-accurate `-ss`-after-`-i` video landmine;
  `_whoosh`/`_build_sfx` use `anoisesrc`/`anullsrc`/`adelay`, no seek at all.
- **`-an` in reframe/assemble stays** — SFX, like ambient, is a mixer-side layer
  baked into the audio stem; the picture master stays silent by construction.

## §8 — Testing

- **Unit (`tests/test_mix.py`, mock `proc.run` + `assembly`)** —
  - `_build_sfx`: `< 2` durs → `None`; all-equal durs (nothing beats the median) →
    `None`; one clear major cut → one offset at the right cumulative time; a second
    major within `_MIN_GAP` is throttled out; offsets are cumulative sums.
  - `mix`: `sfx=False` emits today's graph unchanged (regression pin — music-only
    and ambient-only strings byte-identical); `sfx=True` inserts the `[sfx]` amix
    term; `ambient=True, sfx=True` produces the three-input graph with both the
    sidechain and the sfx term; `ambient=False, sfx=True` produces the two-input
    sfx graph with **no** `sidechaincompress`.
- **Real-ffmpeg integration (`tests/integration/test_sfx.py`, skip-if-no-ffmpeg)** —
  mirrors `test_ambient`'s synth idiom (`scipy.io.wavfile` + numpy):
  1. **Loudness** — a music wav + `sfx=True` over segments with varied durs
     (≥ one major cut) → the stem measures −14 LUFS ±1 (loudnorm still lands with
     the whoosh layer present).
  2. **Placement** — durs with exactly one major cut (e.g. `[3.0, 0.5, 0.5]`:
     median `0.5`, the cut after ep0 has `max(3.0, 0.5) > 0.5` → major at `t≈3.0`;
     the cut after ep1 has `max(0.5, 0.5) = 0.5`, not `> 0.5` → none), music near
     silent → decode the stem, band-pass around `_SFX_FREQ`, assert the whoosh-band
     energy in a short window at `t≈3.0` exceeds a control window (e.g. `t≈1.5`) by
     a clear margin → the whoosh landed on the major cut **and only there**.
- **build_reel integration** — extend the music-spine golden lightly: a manifest
  with `sfx=True` still delivers a reel that measures −14 (the ducking/placement
  proofs live in `test_sfx`; the golden just proves the flag flows end-to-end).

## §9 — Non-goals (deferred)

- **True pitch-sweep / designed whoosh** — v1 is a filtered-noise swell. A rising
  or falling pitch sweep (afftfilt / an external synth) or a curated CC0 sample is
  a later refinement; the synth lives behind one set of constants.
- **Per-episode SFX choice / alternate cues** — one whoosh cue, uniform; no
  `EDLEpisode`/`ReelEpisode` SFX field in v1.
- **Music-less export keeping ambient/SFX** (design §5.14) — the `baked` vs
  music-less deliver split is separate future deliver work; here SFX is baked into
  the one stem.
- **check_reel SFX advisory** — the −14 loudness hard gate already covers level; a
  "did the whoosh land on cuts" advisory is deferred.
- **A SPEC / reel-brief field** — v1 control is `ReelManifest.sfx` (default False);
  `using-montage` can thread an intent → the field later.

## §10 — Doc sync (on landing)

`docs/build-status.md` (Done entry + test count), `docs/pipeline-map.md` (5.12
**◐ → ✅** — SFX is the last §5.12 piece; drop the "SFX ❌" note; Tally
13 ✅ · 2 ◐ · 1 ❌ → **14 ✅ · 1 ◐ · 1 ❌**; the "Phase B remaining: SFX" lines),
`docs/specs/2026-07-05-montage-skillset-design.md` §5.12 (SFX Built blockquote),
`docs/specs/2026-07-11-music-spine-design.md` (SFX landed), `CLAUDE.md` (registry
rows for this design + its plan).
