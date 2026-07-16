# Music Spine — Design Spec (Phase B · B1+B2)

The slice that gives the reel **sound** and closes the first two silent gates.
Two coupled sub-projects, one cycle:

- **B1 · beats-core** — `beats.py` analyses a local music file and emits a lean
  typed `MUSIC.json` (tempo + beat grid + coarse RMS energy).
- **B2 · mix + gates** — `mix.py` muxes the music onto the (silent) reel master
  and `check_reel` gains two real checks: **loudness** (hard, −14 LUFS) and
  **beat** (advisory, cuts-vs-grid). `deliver` muxes the stem.

Maps to montage design §5.5 (music-and-mood, lean subset), §5.12 (audio-mix,
music-only subset), and §5.13 (reel-final-check — turns the `beat`/`loudness`
`passed=None` stubs into real measurements). Sits on top of the Phase A.5 driver
(`build_reel`); the picture reprocess loop is untouched.

## Goal

`music file → beats.analyze → MUSIC.json {tempo, beats[], energy[]}`, then inside
`build_reel`: `assemble (silent) → picture loop (A.5, unchanged) → mix → check_reel
{loudness hard, beat advisory} → deliver (mux)` → `out/REEL_v{n}.mp4` **with audio**.

The reel is silent today (processed episode clips are video-only; `build_reel`
assembles and delivers a soundless master). B1+B2 makes a music-only reel deliver
end-to-end and replaces the dishonest `beat`/`loudness` = `passed=None` with real
numbers. `safe_zones` stayed deferred at authorship (honest `passed=None`); it
landed 2026-07-16 as an advisory route-geometry check
(`docs/specs/2026-07-16-safe-zones-design.md`).

## Scope decisions (from brainstorming, 2026-07-11)

1. **B1 + B2 only.** B3 (autonomous sourcing: `music_find`/`music_fetch`,
   `music.mode` rights lanes, mood-cosine) and B4 (pacing / energy-spine) are
   deferred — B3 is networked and legally-gray, B4 is blocked on the unbuilt
   front half (edit-plan/extract). The track is a **local file** (`music.mode=local`)
   whose path rides the reel manifest.
2. **Lean `MUSIC.json`.** tempo + beat grid + a coarse RMS energy curve only. No
   downbeats, no section detection, no spectral stats, no mood vector — added
   when a consumer (B3 mood-match, B4 spine) actually exists. YAGNI.
3. **Beat advisory, loudness hard.** The reel's cut times are **fixed** by the
   locked episode durations — there is no edit-plan/extract to re-trim a cut onto
   a beat. A hard beat gate would have **no actuator** and would block otherwise
   fine reels. So beat is *measured and reported, non-blocking*; it promotes to a
   hard gate when the front half can act on it. Loudness is genuinely fixable
   (`loudnorm` two-pass hits −14 by construction) → it stays a hard gate.
4. **One-shot stem, muxed at deliver.** Music is independent of the picture, so
   the stem is built **once** after the picture passes — the A.5 reprocess loop
   runs on the silent master exactly as before. (Rejected: re-muxing every
   reprocess round — wasteful, music never changes; inlining at deliver — breaks
   the check-before-deliver ordering.)
5. **Music-only mix v1.** Ambient ducking (`sidechaincompress`) and SFX (whoosh
   on transitions) were deferred to when `extract` (§5.8) preserves per-episode
   ambient — **ambient landed 2026-07-15** (turned out §5.8 needed no change;
   `extract` already preserved the raw segments — see
   `docs/specs/2026-07-15-ambient-ducking-design.md`); **SFX landed 2026-07-15
   too** (see `docs/specs/2026-07-15-transition-sfx-design.md`) — §5.12 is now
   complete. `mix.py`'s signature left the room; ambient was the first thing
   grown into it, SFX the second.

## §1 — Architecture & files

Thin entry scripts over `lib/` contracts, the established split. Six touches
(two new scripts, four edits):

```
scripts/beats.py            NEW  shell  analyze(track, start_offset, duration) → MusicSpec.
                                         Lazy `import librosa` (montage §5.5): beat_track →
                                         tempo + reel-relative beat grid; feature.rms → coarse
                                         energy. CLI writes MUSIC.json.
scripts/mix.py              NEW  shell  mix(music, out_dir, dur) → out/audio.m4a: accurate seek
                                         start_offset, trim dur, afade in/out, loudnorm two-pass
                                         −14 LUFS → aac. Music-only v1; CLI.
scripts/lib/models.py       EDIT  add MusicSpec config-spec (validates/raises). ReelManifest +=
                                         music: str|None (MUSIC.json path). ReelCheckSpec +=
                                         beat_tol/loudness_target/loudness_tol. _ADVISORY_CHECKS +
                                         ReelReport.overall excludes them.
scripts/check_reel.py       EDIT  run() += music: MusicSpec|None, audio: str|None. audio → loudness
                                         (hard, CheckResult + ReelFailure on miss). music → beat
                                         (advisory, CheckResult only). Uncomputed → the _NOT_IMPL
                                         passed=None fallback (safe_zones always).
scripts/deliver.py          EDIT  deliver() += audio: str|None; when set, mux the stem into the
                                         final container (audio stream-copy, video encoded as now).
scripts/build_reel.py       EDIT  load MusicSpec from rm.music; after the picture passes, mix once,
                                         re-check with music+audio, deliver with the stem. need_assemble
                                         guard avoids a redundant re-assemble. music=None → silent, as today.
```

## §2 — Output contract: `MusicSpec` / `MUSIC.json`

A config-spec parallel to `ReframeSpec`/`ReelManifest` — validates on
construction, raises with a remedy (a malformed `MUSIC.json` must fail loud, not
mis-mix silently). Lives in `models.py` beside the other specs.

```json
{ "track": "music/cache/odesza.m4a",
  "start_offset": 15.0,
  "duration": 30.0,
  "tempo": 120.0,
  "beats": [0.0, 0.5, 1.0, 1.5, 2.0, ...],
  "energy": [0.12, 0.31, 0.44, ...],
  "energy_hz": 2.0 }
```

| field | type | meaning |
|---|---|---|
| `track` | `str` | path to the local audio file (the `music.mode=local` source) |
| `start_offset` | `float` | in-point in the track (the strongest fragment, §5.5); **0.0** default |
| `duration` | `float` | analysed window length = the reel length |
| `tempo` | `float` | librosa BPM estimate |
| `beats` | `tuple[float,...]` | beat times **relative to the window start** (0 = reel start), each in `[0, duration]`, sorted |
| `energy` | `tuple[float,...]` | coarse RMS curve over the window (forward-looking for B4; **no consumer in B1+B2**) |
| `energy_hz` | `float` | energy sample rate (≈ 2 Hz) |

**Validation (`__post_init__`, raise `ValueError` with a remedy):**
- `track` a non-empty `str`; else "MusicSpec.track must be a non-empty path".
- `start_offset ≥ 0`, `duration > 0`, `tempo > 0`.
- `beats` non-empty, ascending, every value in `[0, duration]` — a stray value
  means `analyze()` didn't window to the reel span; remedy names the offending
  time and the `[0, duration]` bound.
- `energy` non-empty, `energy_hz > 0`.

`from_dict`/`from_json`/`to_dict` coerce list↔tuple, like the sibling specs.
**Hand-authored or emitted by `beats.py`; B1+B2 defines the schema and the
analyser, not a sourcing stage.**

## §3 — B1: `beats.py`

```python
def analyze(track: str, start_offset: float, duration: float) -> MusicSpec:
    import librosa                                    # lazy — montage §5.5 (keep collection fast, mockable)
    y, sr = librosa.load(track, sr=None, offset=start_offset, duration=duration)
    tempo, frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    beats = tuple(t for t in librosa.frames_to_time(frames, sr=sr) if 0.0 <= t <= duration)
    rms = librosa.feature.rms(y=y)[0]                 # per-frame energy
    energy, energy_hz = _downsample(rms, sr, target_hz=2.0)   # coarse curve
    return MusicSpec(track, start_offset, duration, float(tempo),
                     beats, tuple(float(e) for e in energy), energy_hz)
```

- **Windowed at load** (`offset`/`duration`) — beats come out reel-relative, so
  they compare directly to the reel's cut times with no offset arithmetic. A
  changed `start_offset` re-runs the (cheap) analysis; caching is a B3/router
  concern (§9).
- `_downsample` averages RMS frames into ~2 Hz bins → a short, coarse energy
  curve (no consumer yet; keeps `MUSIC.json` small and B4-ready).
- CLI `main()` (`argparse`: `track`, `--start-offset`, `--duration`,
  `--out MUSIC.json`) writes `to_dict()`; `SystemExit 0`.

**Determinism / testing.** librosa on a real song is heavy and not bit-exact,
so the golden fixture is a **synthetic click track**: numpy renders clicks at a
known BPM into a temp WAV, `analyze` runs the real librosa path, asserts
`tempo` within ±tol and beat spacing within ±tol. Mirrors the repo's
real-ffmpeg golden ethos — a real dependency, a synthetic known-answer input.

## §4 — B2: `mix.py` (audio-mix, music-only v1)

```python
def mix(music: MusicSpec, out_dir: str, dur: float) -> str:
    # 1) accurate-seek the fragment + fade → intermediate
    # 2) loudnorm two-pass to −14 LUFS → out/audio.m4a (aac)
    ...
    return os.path.join(out_dir, "audio.m4a")
```

- **Seek:** the frame-accurate-video landmine (§12, `-ss` after `-i`) is about
  *video* cut points; audio has no keyframe hazard, but the in-point is still
  placed accurately (`-accurate_seek -ss <start_offset> -i` / `-ss` after `-i`) so
  the fragment starts exactly where `start_offset` says.
- **Trim** to `dur` (the reel length, from the master); **`afade`** in/out
  (`t=in:st=0:d=0.5`, `t=out:st=dur-0.5:d=0.5`).
- **Loudnorm two-pass** — pass 1 `loudnorm=print_format=json` measures
  `input_i/TP/LRA/thresh`; pass 2 applies `loudnorm=I=-14:...:measured_*` for an
  accurate integrated −14 LUFS. Encode `aac`.
- **Music only.** No ambient/SFX inputs in v1 (they need `extract`'s preserved
  per-episode audio, §5.8). The signature (`music`, `out_dir`, `dur`) is the
  stable seam; ambient/SFX arrive as added inputs later, one code path grown.
- CLI `main()` (`MUSIC.json`, `--out-dir`, `--dur`) → prints the stem path.

## §5 — B2: the two gates in `check_reel`

`run()` grows two optional inputs; when absent (every picture-loop round) the
audio checks fall through to the existing `passed=None` stub — the A.5 loop is
byte-for-byte unaffected.

```python
def run(master, episodes, spec, out_report,
        music: MusicSpec | None = None, audio: str | None = None) -> ReelReport:
    ...
    if audio is not None:                              # LOUDNESS — hard
        measured = _loudnorm_measure(audio)            # ffmpeg loudnorm print_format=json → input_i
        ok = abs(measured - spec.loudness_target) <= spec.loudness_tol
        checks["loudness"] = CheckResult("loudness", ok,
                                         {"measured": round(measured, 2), "target": spec.loudness_target})
        if not ok:
            fails.append(ReelFailure("loudness", "audio-mix", None,
                                     {"measured": round(measured, 2), "target": spec.loudness_target}))
    if music is not None:                              # BEAT — advisory
        if cuts:
            worst = max(min(abs(t - b) for b in music.beats) for t in cuts)
            on_beat = worst <= spec.beat_tol
            checks["beat"] = CheckResult("beat", on_beat,
                                         {"worst_dev": round(worst, 3), "tol": spec.beat_tol, "n_cuts": len(cuts)})
            # ADVISORY: no ReelFailure appended — excluded from `overall` (see below)
        else:                                          # single episode → no cut to land on a beat
            checks["beat"] = CheckResult("beat", None, {"status": "n/a", "reason": "single episode, no cut"})
    for name, reason in _NOT_IMPL.items():             # fill only what wasn't computed (safe_zones always)
        checks.setdefault(name, CheckResult(name, None, {"status": "not-implemented", "reason": reason}))
```

**Advisory = real bool, excluded from `overall`.** `ReelReport.overall` is
`all(c.passed is not False …)` — it keys off *checks*, so a `passed=False` beat
would trip `deliver`'s hard gate and block a reel with no actuator to fix it.
Fix: a module set `_ADVISORY_CHECKS = ("beat",)` and

```python
@property
def overall(self) -> bool:
    return all(c.passed is not False
               for n, c in self.checks.items() if n not in _ADVISORY_CHECKS)
```

So beat carries the **real** `on_beat` bool (visibly *closed* — no longer a
`None` stub) yet never blocks delivery. A passing reel is unaffected (the
comprehension only ever skips a check that would otherwise be `False`).
Promotion path: when edit-plan/extract land, drop `beat` from `_ADVISORY_CHECKS`
and append a `ReelFailure(escalate_to="pacing"/"edit-plan")` → it becomes a hard
gate with a real fixer.

**Loudness rides the existing escalate path — `next_action` needs no change.**
A `ReelFailure(check="loudness", escalate_to="audio-mix")` is not in
`_REPROCESS_CLASS`, so `next_action` returns `Escalate(reason="not-auto-fixable",
escalate_to="audio-mix")` — exactly as it does for `variety`/`length` today. A
loudness miss means the mix is broken (near-tautological after two-pass
loudnorm); it stops-and-reports rather than looping a non-existent audio
actuator. `safe_zones` stays `passed=None`.

`ReelCheckSpec` gains `beat_tol: float = 0.05`, `loudness_target: float = -14.0`,
`loudness_tol: float = 1.0` (validated positive/`≤0`-guarded like the existing
fields; `loudness_target` is negative so it is range-checked, not sign-checked).

## §6 — Driver: `build_reel` integration

Music is independent of the picture, so the stem is built **once**, after the
picture passes, then folded into a final re-check. The picture loop is unchanged.

```python
music = MusicSpec.from_json(rm.music) if rm.music else None      # None → silent reel, exactly as today
audio, need_assemble = None, True
for _ in range(rm.cap * len(rm.episodes) + 1):
    if need_assemble:
        assembly.assemble(clips, dims, fps, master); need_assemble = False
    report = check_reel.run(master, clips, rm.check_spec, report_path, music=music, audio=audio)
    action = reel_orchestration.next_action(report.fail_reasons, attempts, rm.cap)
    if action.kind == "deliver":
        if music is not None and audio is None:                  # picture passed → build the stem, re-check with it
            audio = mix.mix(music, out_dir, _probe_dur(master)); continue
        out = deliver.deliver(master, REEL_H264, out_dir, rm.changelog, report, audio=audio)
        return {"status": "delivered", "output": out, "report": report.to_dict()}
    if action.kind == "escalate":
        return {"status": "stop_and_report", "finding": action.finding, "report": report.to_dict(), "attempts": attempts}
    for r in action.reprocess:
        ... process_episode ...; clips[r.idx] = res["clip"]; need_assemble = True
```

- **Picture first, then audio.** The stem is never built for a reel that
  escalates or fails on picture — `mix` runs only on the `deliver` branch, once
  (`audio is None` guard), then `continue` re-enters the loop so the *next*
  `check_reel` includes loudness+beat. `need_assemble` stays `False` there (clips
  unchanged) — no redundant re-assemble.
- **Loudness fail is caught.** If the re-check's loudness fails, `next_action`
  returns `escalate` (audio-mix) → `stop_and_report`; `deliver` is never reached.
- **Backward compatible.** `rm.music is None` → `audio` stays `None` → the loop
  is the A.5 loop and `deliver` ships a silent reel, unchanged. Existing A.5
  tests keep passing.
- **deliver muxing.** `deliver(..., audio=stem)` adds `-i stem -map 0:v -map 1:a
  -c:a copy` (the stem is already aac) to the existing video encode → one
  container, no audio re-encode, loudness preserved.

## §7 — Testing

**Unit (fast, pure / mocked):**
- `models.MusicSpec` — round-trips (`to_dict`/`from_dict`/`from_json`); raises
  with a remedy on `tempo≤0`, `duration≤0`, `start_offset<0`, empty beats,
  unsorted beats, a beat outside `[0, duration]`, empty energy.
- `ReelReport.overall` — a `beat` check `passed=False` does **not** flip
  `overall` (advisory exclusion); a `loudness` `passed=False` **does**.
- `check_reel` beat math — cuts against a known grid → expected `worst_dev` and
  `on_beat` bool; single-episode (no cuts) → `beat` n/a (`passed=None`).
- `check_reel` loudness — a mocked `_loudnorm_measure` in range → `passed=True`,
  no fail; out of range → `passed=False` + a `ReelFailure(escalate_to="audio-mix")`.
- `build_reel` — mock `assemble`/`check_reel`/`mix`/`deliver`: with `rm.music`
  set and picture passing, `mix` is called once and `deliver` receives the stem;
  a mocked loudness fail → `stop_and_report` with `deliver` **never** called;
  `rm.music=None` → `deliver` called with `audio=None` (silent path intact).

**Integration (real ffmpeg/librosa, `@pytest.mark.integration`):**
- **`test_beats.py`** — synthetic click WAV at a known BPM (numpy → temp WAV) →
  `analyze` → `tempo` within ±tol, beat count/spacing within ±tol, `MusicSpec`
  validates. Proves the real librosa path, deterministically.
- **`test_music_spine.py` (mix + loudness)** — render a test tone, `mix` it, then
  `_loudnorm_measure` the stem → integrated loudness within −14 ±1. Proves the
  two-pass loudnorm on real audio.
- **`test_music_spine.py` (build_reel end-to-end)** — two uniform `reframe`-built
  silent clips + a `MUSIC.json` (synthetic track) → `ReelManifest(music=…)` →
  `build_reel` delivers `REEL_v1.mp4` **with an audio stream** (ffprobe shows an
  aac track) and a report whose `loudness` passed and `beat` carries a real
  `worst_dev`. Proves the real wiring the unit test mocks.

## §8 — Landmines touched (montage §12)

- **`-ss` seek** — no *video* seek is added; `mix`'s audio in-point is placed
  accurately (not the frame-accurate-video landmine, but exact anyway).
- **`lutrgb`** — not touched; audio-mix does no colour op.
- **Even output dims** — untouched; `mix`/`deliver` add no `scale`, the muxed
  reel keeps the master's even canvas.
- **Never a silent pass** — loudness is a *hard* gate (a bad mix stops-and-reports,
  never ships); beat is *measured and reported* (a real `worst_dev`, non-blocking
  only because no re-trim actuator exists yet — an honest, documented limit, not a
  fake green); `safe_zones` landed the same way 2026-07-16 — measured and
  reported (advisory route-geometry), non-blocking because no auto-fix actuator
  exists either; a geometry-less reel still reports the honest `passed=None`.
- **Determinism** — librosa isn't bit-exact on real audio, so tests pin a
  synthetic known-BPM fixture; production `MUSIC.json` is written once per track
  and reused (a bad re-analysis can't silently drift a shipped reel).

## §9 — Non-goals / deferred

- **B3 — autonomous sourcing** — `music_find`/`music_fetch`, catalog discovery
  (Jamendo/ccMixter for the `free` lane, YouTube/iTunes/Deezer for `any` via
  yt-dlp), `music.mode` rights lanes — **landed 2026-07-14** (its own spec/plan:
  `docs/specs/2026-07-14-music-sourcing-design.md`). v1 (this spec) hands
  `beats.py` a local file path; sourcing is the separate slice that supplies it.
- **B4 — pacing / energy-spine** (`PACING.md`, section-pinning) — **landed
  2026-07-14** (its own spec/plan: `docs/specs/2026-07-14-pacing-design.md`).
  The `energy` curve this spec recorded but left unread now has its consumer:
  `pacing.build_spine` folds it (min-max normalized, beat-aligned) into slots
  edit-plan binds episodes to. The retry-time auto-fix (`build_reel`'s
  `length` failure re-timing the spine) and librosa section detection remain
  deferred.
- **Ambient ducking** in the mix — **landed 2026-07-15** (its own spec/plan:
  `docs/specs/2026-07-15-ambient-ducking-design.md`); turned out `extract`
  already preserved per-episode audio (§5.8), so no §5.8 change was needed.
  **SFX** (whoosh on transitions) — **landed 2026-07-15** too (its own
  spec/plan: `docs/specs/2026-07-15-transition-sfx-design.md`); §5.12
  (audio-mix) is now complete.
- **Downbeats / section detection / spectral / mood vector** — added when B3/B4
  consume them.
- **`safe_zones`** — needs a per-episode route + a platform safe-margin table
  (Editorial reel-final, a later phase) — **landed 2026-07-16** (its own
  spec/plan: `docs/specs/2026-07-16-safe-zones-design.md`); no longer stays
  `passed=None` by default — it's now an advisory route-geometry check against
  a platform `SafeZone` table.
- **Music-less delivery mode** — `baked` only; ambient ducking (2026-07-15)
  now bakes each clip's nat-sound *into* the music stem, so `mix.py` emits a
  single inseparable music+ambient stem — a music-less-but-ambient-kept export
  would need a separable ambient-only stem the mixer doesn't yet produce.
- **Beat as a hard gate** — advisory until edit-plan/extract can re-trim a cut.
- **Start-offset intelligence** — the "chosen fragment" `start_offset` + vocal-pause
  start-snap landed separately on 2026-07-13 (its own spec/plan:
  `docs/specs/2026-07-13-start-offset-intelligence-design.md`); B4 pacing and
  B3 sourcing have since landed too (see above).
- **Mood-match (local lane)** — ranking a user's own folder of tracks against
  `SPEC.mood` (`scripts/lib/mood.py` + `scripts/mood.py` → `MUSIC_SHORTLIST`, the
  `music-match` SKILL) landed 2026-07-14 (its own spec/plan:
  `docs/specs/2026-07-13-mood-match-design.md`); its ranking core was reused
  unchanged by B3's networked sourcing (also landed 2026-07-14 — see above), so
  B3 is now complete end-to-end; B4 pacing has since landed too (2026-07-14 —
  see above). The pacing retry-time auto-fix is what remains open in this
  spec's scope (ambient ducking and SFX both landed 2026-07-15 — see above;
  §5.12 is now complete).
