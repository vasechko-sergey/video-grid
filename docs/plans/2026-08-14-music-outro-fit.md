# Music Outro Fit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the reel's length becomes `bar_line + fade`, so the music resolves on a
musical boundary with vocal-free room for its own fade-out, instead of stopping
wherever the picture happened to end.

**Architecture:** `MUSIC.json` gains the two facts it never carried — `bars`
(downbeats, from the bass band) and `vocal_spans` (from the demucs stem at full
resolution). A pure `lib/outro.fit_outro` runs a three-rung ladder over the bar lines
within ±one bar, bounded by what the closing shot can grow or shrink by. `edit_plan`
applies the winner to the last episode. **No ffmpeg stage changes** — `mix` already
fades over `[dur - fade, dur]`, so a reel of `line + fade` starts its fade exactly on
the line.

**Tech Stack:** Python 3.13, librosa (lazy), demucs (required), pytest.

**Design:** [docs/specs/2026-08-14-music-outro-fit-design.md](../specs/2026-08-14-music-outro-fit-design.md)

## Global Constraints

- **Python is `.venv/bin/python`.** Scripts run as modules (`pytest.ini` sets
  `pythonpath = .`); never `python scripts/foo.py`.
- **Fail loud with a remedy.** Every refusal names what is wrong AND the command or
  edit that fixes it. See [docs/coding-standards.md](../coding-standards.md).
- **Imports at top of file**, except the documented heavy-optional lazies
  (`librosa`, `torch`, `demucs`, `ultralytics`) which stay inside the function that
  needs them, each with the existing `# lazy import: heavy optional dep (...)` comment.
- **Exact constant values, copied verbatim from the design:** `TAIL_MIN = 0.5`,
  `NO_GAP_FADE = 1.5`, `MIN_LAST = 1.0`, `BAR_BEATS = 4`, `_SPAN_HZ = 40.0`,
  `_LOW_HZ = 150.0`, `_BAR_WIN = 0.10`, `_MIN_BEATS_FOR_BARS = 8`.
- **`mix.py`, `deliver.py`, `check_reel.py`, `build_reel.py`, `edl_to_reel.py` are NOT
  touched.** If a task seems to need one of them, stop and report — the design's §1
  claim is wrong and that is a finding, not something to work around.
- **Whole-object asserts** in tests where a dataclass is returned; compare the whole
  `OutroFit`, not one field. See [docs/testing-guide.md](../testing-guide.md).
- **No installers.** Never run `pip`, `brew`, or `setup.sh`. Verification is
  read-only plus `pytest`.
- **Never** `git checkout --`, `git restore`, `git reset --hard`, or `git stash`.
- Times in `MusicSpec` are **stem-relative** (0.0 = the music fragment's start),
  exactly like `beats`. `vocals.vocal_spans` returns **track-relative** times; the
  conversion is `outro.window_spans` and it happens once, in `beats.main`.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/lib/models.py` | `MusicSpec.bars`, `MusicSpec.vocal_spans` + validation + serialization |
| `scripts/lib/vocals.py` | `vocal_spans(track)` — the demucs boundary's span accessor, memoized |
| `scripts/lib/outro.py` | **new, pure** — `BAR_BEATS`, `TAIL_MIN`, `NO_GAP_FADE`, `MIN_LAST`, `OutroFit`, `free_after`, `window_spans`, `fit_outro` |
| `scripts/beats.py` | `_downbeat_phase` + `analyze` fills `bars`; `main` fills `vocal_spans`; `choose_offset` moves onto `vocal_spans` |
| `scripts/lib/edl.py` | `EDL.outro` carrier + the `EDL.md` **Music outro** section |
| `scripts/edit_plan.py` | `--music`, `_apply_outro` after `_bind_pacing` |

---

### Task 0: `MusicSpec` carries bars and vocal spans

**Files:**
- Modify: `scripts/lib/models.py` (the `MusicSpec` dataclass, ~1095-1170)
- Test: `tests/lib/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `MusicSpec.bars: tuple[float, ...]` and
  `MusicSpec.vocal_spans: tuple[tuple[float, float], ...]`, both stem-relative
  seconds, both defaulting to `()`. Both round-trip through
  `to_dict`/`from_dict`/`from_json`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_models.py`:

```python
def _music(**kw):
    base = dict(track="t.wav", start_offset=0.0, duration=10.0, tempo=120.0,
                beats=(0.0, 0.5, 1.0, 1.5), energy=(0.1,), energy_hz=2.0)
    base.update(kw)
    return MusicSpec(**base)


def test_musicspec_bars_and_spans_default_empty():
    """An artifact written before this slice still loads — the outro fit reads the
    empty grid as 'unchanged', which is honest, rather than raising."""
    m = _music()
    assert m.bars == () and m.vocal_spans == ()


def test_musicspec_bars_round_trip():
    m = _music(bars=[0.0, 2.0], vocal_spans=[[1.0, 1.8]])
    assert m.bars == (0.0, 2.0)
    assert m.vocal_spans == ((1.0, 1.8),)
    assert MusicSpec.from_dict(m.to_dict()) == m


def test_musicspec_bars_must_be_ascending():
    with pytest.raises(ValueError, match="ascending"):
        _music(bars=[2.0, 1.0])


def test_musicspec_bars_must_be_inside_the_window():
    with pytest.raises(ValueError, match=r"outside \[0, 10.0\]"):
        _music(bars=[0.0, 11.0])


def test_musicspec_span_must_be_a_pair():
    with pytest.raises(ValueError, match="two numbers"):
        _music(vocal_spans=[[1.0]])


def test_musicspec_span_must_be_forward():
    with pytest.raises(ValueError, match="start before its end"):
        _music(vocal_spans=[[2.0, 1.0]])


def test_musicspec_spans_must_be_ascending_and_disjoint():
    with pytest.raises(ValueError, match="ascending, non-overlapping"):
        _music(vocal_spans=[[1.0, 3.0], [2.0, 4.0]])


def test_musicspec_span_must_be_inside_the_window():
    with pytest.raises(ValueError, match=r"outside \[0, 10.0\]"):
        _music(vocal_spans=[[9.0, 12.0]])
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -q -k "musicspec_bars or musicspec_span"`
Expected: FAIL — `TypeError: MusicSpec.__init__() got an unexpected keyword argument 'bars'`

- [ ] **Step 3: Add the fields**

In `scripts/lib/models.py`, after `energy_hz: float` in `MusicSpec`:

```python
    bars: tuple[float, ...] = ()          # downbeat times, stem-relative (design
                                          # 2026-08-14 §2/§3). Derived from `beats` by
                                          # the bass-band phase test, NOT from onset
                                          # strength, which carries no downbeat signal
                                          # (§3: all four phases within 1%). () = the
                                          # producer could not tell — fewer than 8 beats,
                                          # or an artifact written before this slice.
                                          # Assumes 4/4 (§11.3).
    vocal_spans: tuple[tuple[float, float], ...] = ()
                                          # (start, end) spans with NO vocal, stem-
                                          # relative and clipped to [0, duration]. From
                                          # the demucs stem at ~23 ms resolution, never
                                          # from `energy`: a 2 Hz curve has 0.5s bins and
                                          # the outro rule asks about 0.5s (§8.1).
```

- [ ] **Step 4: Add the validation**

At the end of `MusicSpec.__post_init__`, after the `energy_hz` check:

```python
        if not isinstance(self.bars, (tuple, list)):
            raise ValueError("MusicSpec.bars must be a list of stem-relative downbeat "
                             "times (seconds) — re-run beats to regenerate MUSIC.json")
        try:
            self.bars = tuple(float(b) for b in self.bars)
        except (TypeError, ValueError):
            raise ValueError("MusicSpec.bars must contain only numeric times — a "
                             "non-numeric entry means the MUSIC.json is malformed") from None
        if list(self.bars) != sorted(self.bars):
            raise ValueError("MusicSpec.bars must be ascending — beats emits them in time order")
        for b in self.bars:
            if not (0.0 <= b <= self.duration):
                raise ValueError(f"MusicSpec.bars has {b} outside [0, {self.duration}] — bars "
                                 "are stem-relative; a stray value means the window is wrong")
        if not isinstance(self.vocal_spans, (tuple, list)):
            raise ValueError("MusicSpec.vocal_spans must be a list of [start, end] pairs — "
                             "re-run beats to regenerate MUSIC.json")
        spans: list[tuple[float, float]] = []
        prev_end = -1.0
        for s in self.vocal_spans:
            if not isinstance(s, (tuple, list)) or len(s) != 2:
                raise ValueError(f"MusicSpec.vocal_spans entry {s!r} must be two numbers "
                                 "[start, end] in stem-relative seconds")
            try:
                a, b = float(s[0]), float(s[1])
            except (TypeError, ValueError):
                raise ValueError(f"MusicSpec.vocal_spans entry {s!r} must be numeric") from None
            if a >= b:
                raise ValueError(f"MusicSpec.vocal_spans entry {s!r} must start before its end")
            if not (0.0 <= a and b <= self.duration):
                raise ValueError(f"MusicSpec.vocal_spans entry {s!r} is outside "
                                 f"[0, {self.duration}] — spans are stem-relative and clipped "
                                 "to the analysed window by outro.window_spans")
            if a < prev_end:
                raise ValueError("MusicSpec.vocal_spans must be ascending, non-overlapping — "
                                 "offset.vocal_gaps emits them that way; overlap means the "
                                 "MUSIC.json was hand-edited")
            prev_end = b
            spans.append((a, b))
        self.vocal_spans = tuple(spans)
```

- [ ] **Step 5: Serialize both**

In `MusicSpec.to_dict`, add to the returned dict:

```python
                "bars": list(self.bars),
                "vocal_spans": [list(s) for s in self.vocal_spans],
```

In `MusicSpec.from_dict`, add to the `cls(...)` call:

```python
                   bars=d.get("bars", ()), vocal_spans=d.get("vocal_spans", ()),
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -q`
Expected: PASS, no other test in the file breaks (the defaults keep every existing
`MusicSpec(...)` construction valid).

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat(music): MusicSpec carries bars and vocal_spans"
```

---

### Task 1: `vocals.vocal_spans` — one sensor, at a resolution that can answer

**Files:**
- Modify: `scripts/lib/vocals.py`
- Modify: `scripts/beats.py` (`choose_offset` only)
- Test: `tests/lib/test_vocals.py`, `tests/lib/test_beats.py`

**Interfaces:**
- Consumes: `offset.vocal_gaps(env, hz)` (unchanged), `vocals.separate_vocal_energy`.
- Produces: `vocals.vocal_spans(track: str) -> tuple[tuple[float, float], ...]`,
  **track-relative** seconds, memoized per track path for the process.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_vocals.py`:

```python
def test_vocal_spans_uses_a_fine_envelope_not_the_2hz_one(monkeypatch):
    """§8.1 — a 2 Hz envelope has 0.5s bins and the outro rule asks about 0.5s. The
    span sensor must ask separate_vocal_energy for _SPAN_HZ, not the 2.0 default."""
    seen = {}

    def fake(track, target_hz=2.0):
        seen["hz"] = target_hz
        return [9.0] * 40 + [0.0] * 40 + [9.0] * 40, 40.0

    monkeypatch.setattr(vocals, "separate_vocal_energy", fake)
    vocals._SPANS.clear()
    spans = vocals.vocal_spans("t.wav")
    assert seen["hz"] == vocals._SPAN_HZ == 40.0
    assert spans == ((1.0, 2.0),)


def test_vocal_spans_memoizes_per_track(monkeypatch):
    """The separation costs 46-62s. choose_offset and beats.main both want the spans
    in one process; the second call must not pay again."""
    calls = []

    def fake(track, target_hz=2.0):
        calls.append(track)
        return [0.0] * 40, 40.0

    monkeypatch.setattr(vocals, "separate_vocal_energy", fake)
    vocals._SPANS.clear()
    vocals.vocal_spans("t.wav")
    vocals.vocal_spans("t.wav")
    assert calls == ["t.wav"]
```

Replace `test_choose_offset_gaps_come_from_the_vocal_stem` and
`test_choose_offset_gaps_are_not_the_mix_envelope` in `tests/lib/test_beats.py` so
they stub `vocals.vocal_spans` instead of `vocals.separate_vocal_energy` — the spans
are now track-relative, and `choose_offset` works in track time already:

```python
def test_choose_offset_gaps_come_from_the_vocal_stem(monkeypatch, capsys):
    _fake_librosa(monkeypatch, track_seconds=4.0)
    monkeypatch.setattr(offset, "downsample",
                        lambda *a, **k: ([1.0, 1.0, 1.0, 1.0, 5.0, 5.0, 5.0, 5.0], 2.0))
    monkeypatch.setattr(vocals, "vocal_spans", lambda *a, **k: ((1.5, 2.5),))
    off = beats.choose_offset("t.wav", duration=2.0)
    assert off == 1.5
    assert "via vocal" in capsys.readouterr().err


def test_choose_offset_gaps_are_not_the_mix_envelope(monkeypatch):
    """Discriminates the deleted mix-proxy: the mix envelope has its own quiet run
    that the vocal stem does not. Reading gaps off the mix would pick 3.0s."""
    _fake_librosa(monkeypatch, track_seconds=4.0)
    monkeypatch.setattr(offset, "downsample",
                        lambda *a, **k: ([0.0, 0.0, 1.0, 5.0, 5.0, 5.0, 0.0, 0.0], 2.0))
    monkeypatch.setattr(vocals, "vocal_spans", lambda *a, **k: ((1.5, 2.5),))
    assert beats.choose_offset("t.wav", duration=2.0) == 1.5
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_vocals.py tests/lib/test_beats.py -q`
Expected: FAIL — `AttributeError: module 'scripts.lib.vocals' has no attribute '_SPANS'`

- [ ] **Step 3: Implement `vocal_spans`**

In `scripts/lib/vocals.py`, after `has_demucs`:

```python
_SPAN_HZ = 40.0                  # ~23 ms bins after downsample's integer step. NOT 2.0:
                                 # a 2 Hz envelope has 0.5s bins and the outro rule asks
                                 # about 0.5s, so it cannot resolve its own question — the
                                 # first pass of the 2026-08-14 investigation reported the
                                 # feature impossible because of exactly this (design §8.1).
_SPANS: dict[str, tuple[tuple[float, float], ...]] = {}   # per-process memo, keyed on the
                                 # track path: choose_offset and beats.main both want the
                                 # spans inside one beats.py run, and the separation costs
                                 # 46-62s on a 229s track (measured 2026-08-14).


def vocal_spans(track: str) -> tuple[tuple[float, float], ...]:
    """TRACK-relative (start, end) spans where the vocal stem is quiet.

    The one sensor both the music IN-point (choose_offset) and the OUT-point (the
    outro fit) read, so the two cannot disagree about where the singing stops. The
    decision stays pure — this only supplies the envelope offset.vocal_gaps judges.

    Times are track-relative because that is what separate_vocal_energy measures;
    outro.window_spans converts them to the stem-relative form MusicSpec stores."""
    if track not in _SPANS:
        env, hz = separate_vocal_energy(track, target_hz=_SPAN_HZ)
        _SPANS[track] = offset.vocal_gaps(env, hz)
    return _SPANS[track]
```

- [ ] **Step 4: Point `choose_offset` at it**

In `scripts/beats.py`, replace these two lines in `choose_offset`:

```python
    env, hz = vocals.separate_vocal_energy(track)
    gaps = offset.vocal_gaps(env, hz)
```

with:

```python
    gaps = vocals.vocal_spans(track)
```

and add to the docstring, after the "mix envelope still RANKS" paragraph:

```
    Since 2026-08-14 the spans come from vocals.vocal_spans at ~23 ms resolution
    rather than from a 2 Hz envelope. That is a deliberate change of ANSWER as well
    as of precision: finer bins find short gaps the coarse binning smeared away and
    drop ones binning invented. One sensor serves the in-point and the out-point, so
    the two cannot disagree about the same track (design 2026-08-14 §4).
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_vocals.py tests/lib/test_beats.py tests/integration/test_offset.py -q`
Expected: PASS. `test_choose_offset_refuses_without_demucs` still passes — the
refusal now comes from `separate_vocal_energy` one call deeper, through
`vocal_spans`, which is the same guard.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/vocals.py scripts/beats.py tests/lib/test_vocals.py tests/lib/test_beats.py
git commit -m "feat(music): one vocal-span sensor, at a resolution that can answer 0.5s"
```

---

### Task 2: `beats` detects the downbeat phase and fills both fields

**Files:**
- Modify: `scripts/beats.py`
- Test: `tests/lib/test_beats.py`, `tests/integration/test_offset.py`

**Interfaces:**
- Consumes: `outro.BAR_BEATS`, `outro.window_spans` (Task 3 defines them — implement
  Task 3 first if you are working out of order), `vocals.vocal_spans`.
- Produces: `beats._downbeat_phase(y, sr, beats) -> int | None`; `analyze()` returns a
  `MusicSpec` whose `bars` is populated; `main()` writes a MUSIC.json with both new
  keys.

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_beats.py`:

```python
def test_downbeat_phase_finds_the_bass_phase(monkeypatch):
    """§3 — the kick marks the downbeat. Synthesize a 4/4 grid whose every 4th beat
    (phase 2 here) carries a 60 Hz thump and the rest carry a 1 kHz tick, and the
    detector must return 2. Onset strength cannot do this (measured: all four phases
    within 1%), which is why the band is the bass band."""
    sr = 22050
    period = 0.5
    times = [i * period for i in range(16)]
    y = np.zeros(int(sr * (times[-1] + period)), dtype=np.float32)
    t = np.arange(int(sr * 0.12)) / sr
    thump = (0.9 * np.sin(2 * np.pi * 60 * t)).astype(np.float32)
    tick = (0.9 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    for i, bt in enumerate(times):
        a = int(bt * sr)
        pulse = thump if i % 4 == 2 else tick
        y[a:a + len(pulse)] += pulse
    assert beats._downbeat_phase(y, sr, times) == 2


def test_downbeat_phase_none_when_too_few_beats():
    """A phase argmax over one or two samples per group is noise; () is the honest
    answer and the outro fit reads it as the 'unchanged' rung."""
    assert beats._downbeat_phase(np.zeros(1000, dtype=np.float32), 22050,
                                 [0.0, 0.5, 1.0, 1.5]) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_beats.py -q -k downbeat`
Expected: FAIL — `AttributeError: module 'scripts.beats' has no attribute '_downbeat_phase'`

- [ ] **Step 3: Implement the detector**

In `scripts/beats.py`, after the `_downsample` alias near the top:

```python
_LOW_HZ = 150.0                # kick band edge — measured 2026-08-14 §3
_BAR_WIN = 0.10                # +/- seconds sampled around each beat
_MIN_BEATS_FOR_BARS = 8        # below this a per-phase mean is one or two samples
_NFFT = 2048
```

and this function after `analyze`:

```python
def _downbeat_phase(y, sr: int, beat_times) -> int | None:
    """Which of the four beat phases carries the bar's kick — the downbeat.

    Peak STFT energy below _LOW_HZ in a +/-_BAR_WIN window around each beat, averaged
    per phase; the loudest phase wins. Measured on a real track (design §3): phases
    scored 48.01 / 54.65 / 42.03 / 79.31, a 1.887 max/min ratio, and the winner's beat
    was the loudest of its own bar in 14 of 18 bars against 25% by chance.

    ONSET STRENGTH DOES NOT WORK HERE — the same track scored 4.313 / 4.285 / 4.267 /
    4.309, all four phases inside 1%. A detector built on novelty picks a phase out of
    noise and looks like it works. Do not 'simplify' this to librosa.onset.

    None when there are fewer than _MIN_BEATS_FOR_BARS beats. Assumes 4/4 (§11.3).
    `beat_times` are relative to the START of `y`, which is what analyze() passes."""
    import librosa                                    # lazy import: heavy optional dep (librosa)
    if len(beat_times) < _MIN_BEATS_FOR_BARS:
        return None
    spec = np.abs(librosa.stft(y, n_fft=_NFFT, hop_length=_HOP))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=_NFFT)
    low = spec[freqs < _LOW_HZ].sum(axis=0)
    hz = sr / _HOP

    def peak(t: float) -> float:
        a, b = int((t - _BAR_WIN) * hz), int((t + _BAR_WIN) * hz)
        seg = low[max(a, 0):b]
        return float(seg.max()) if len(seg) else 0.0

    vals = [peak(float(t)) for t in beat_times]
    means = [float(np.mean(vals[p::outro.BAR_BEATS])) for p in range(outro.BAR_BEATS)]
    return int(np.argmax(means))
```

Add `outro` to the existing lib import line:

```python
from scripts.lib import mood, offset, outro, vocals
```

- [ ] **Step 4: Run the detector tests**

Run: `.venv/bin/python -m pytest tests/lib/test_beats.py -q -k downbeat`
Expected: PASS

- [ ] **Step 5: Write the failing wiring tests**

Append to `tests/lib/test_beats.py`:

```python
def test_analyze_fills_bars_from_the_detected_phase(monkeypatch):
    import librosa
    times = [i * 0.5 for i in range(16)]
    monkeypatch.setattr(librosa, "load",
                        lambda *a, **k: (np.zeros(int(8.0 * 22050), dtype=np.float32), 22050))
    monkeypatch.setattr(librosa.beat, "beat_track",
                        lambda *a, **k: (np.array([120.0]), np.arange(16)))
    monkeypatch.setattr(librosa, "frames_to_time", lambda f, **k: np.array(times))
    monkeypatch.setattr(librosa.feature, "rms", lambda *a, **k: np.array([[0.1]]))
    monkeypatch.setattr(beats, "_downbeat_phase", lambda *a, **k: 1)
    ms = beats.analyze("t.wav")
    assert ms.bars == (0.5, 2.5, 4.5, 6.5)


def test_analyze_leaves_bars_empty_when_the_phase_is_unknown(monkeypatch):
    import librosa
    monkeypatch.setattr(librosa, "load",
                        lambda *a, **k: (np.zeros(int(8.0 * 22050), dtype=np.float32), 22050))
    monkeypatch.setattr(librosa.beat, "beat_track",
                        lambda *a, **k: (np.array([120.0]), np.arange(4)))
    monkeypatch.setattr(librosa, "frames_to_time",
                        lambda f, **k: np.array([0.0, 0.5, 1.0, 1.5]))
    monkeypatch.setattr(librosa.feature, "rms", lambda *a, **k: np.array([[0.1]]))
    monkeypatch.setattr(beats, "_downbeat_phase", lambda *a, **k: None)
    assert beats.analyze("t.wav").bars == ()


def test_cli_fills_vocal_spans_windowed_to_the_stem(monkeypatch, tmp_path):
    """The spans MusicSpec stores are stem-relative and clipped to the window; the
    sensor measures track-relative. main() is where the one conversion happens."""
    monkeypatch.setattr(vocals, "vocal_spans", lambda t: ((3.0, 4.0), (19.0, 30.0)))
    monkeypatch.setattr(beats, "analyze", lambda track, start, duration: MusicSpec(
        track=track, start_offset=start, duration=10.0, tempo=120.0,
        beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0, bars=(0.0,)))
    out = tmp_path / "M.json"
    monkeypatch.setattr("sys.argv", ["beats", "t.wav", "--start-offset", "12",
                                     "--duration", "10", "--out", str(out)])
    beats.main()
    ms = MusicSpec.from_json(out)
    assert ms.vocal_spans == ((7.0, 10.0),)     # (19,30) clipped; (3,4) is before the window
```

- [ ] **Step 6: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_beats.py -q -k "analyze_fills or analyze_leaves or cli_fills"`
Expected: FAIL — `analyze` returns `bars=()`; the CLI writes no `vocal_spans`.

- [ ] **Step 7: Wire `analyze` and `main`**

In `analyze`, replace the `return MusicSpec(...)` with:

```python
    phase = _downbeat_phase(y, sr, beats)
    bars = tuple(beats[phase::outro.BAR_BEATS]) if phase is not None else ()
    return MusicSpec(track=track, start_offset=float(start_offset), duration=dur,
                     tempo=tempo, beats=beats, energy=tuple(energy), energy_hz=energy_hz,
                     bars=bars)
```

In `main`, replace the line that writes the file with:

```python
    # Always measured, with or without --auto-start: vocal_spans is part of MUSIC.json's
    # contract now, and the outro fit cannot run without it. When --auto-start already
    # ran, vocals.vocal_spans is memoized and this call is free (design §4).
    ms = dataclasses.replace(
        ms, vocal_spans=outro.window_spans(vocals.vocal_spans(a.track),
                                           ms.start_offset, ms.duration))
    Path(a.out).write_text(json.dumps(ms.to_dict(), indent=2))
```

Add `import dataclasses` to the top-of-file imports (alphabetically before `import json`).

- [ ] **Step 8: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_beats.py tests/integration/test_offset.py -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add scripts/beats.py tests/lib/test_beats.py
git commit -m "feat(music): beats detects downbeats from the bass band and records the spans"
```

---

### Task 3: `lib/outro.py` — the pure fitter

**Files:**
- Create: `scripts/lib/outro.py`
- Test: `tests/lib/test_outro.py` (new)

**Interfaces:**
- Consumes: nothing (pure).
- Produces:
  - `BAR_BEATS = 4`, `TAIL_MIN = 0.5`, `NO_GAP_FADE = 1.5`, `MIN_LAST = 1.0`
  - `OutroFit(reel_dur, line, fade, tail, rung, moved)` + `to_dict`/`from_dict`
  - `free_after(spans, t) -> float`
  - `window_spans(spans, start_offset, duration) -> tuple[tuple[float, float], ...]`
  - `bar_seconds(tempo) -> float`
  - `fit_outro(bars, vocal_spans, reel_dur, bar_s, fade, *, music_dur, grow_max, shrink_max, brief_len=None) -> OutroFit`

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/test_outro.py`:

```python
"""outro.py — the pure outro fit (design docs/specs/2026-08-14-music-outro-fit-design.md)."""
import pytest

from scripts.lib import outro
from scripts.lib.outro import OutroFit

# a 110.294 BPM grid, the 2026-08-03 run's own: bar = 2.176s
BAR = 2.176
BARS = tuple(round(2.548 + i * BAR, 3) for i in range(18))     # 2.548 .. 39.54


def test_bar_seconds_is_four_beats():
    assert outro.bar_seconds(120.0) == pytest.approx(2.0)


def test_window_spans_offsets_and_clips():
    assert outro.window_spans(((3.0, 4.0), (19.0, 30.0)), 12.0, 10.0) == ((7.0, 10.0),)


def test_window_spans_drops_an_empty_intersection():
    assert outro.window_spans(((0.0, 1.0),), 12.0, 10.0) == ()


def test_free_after_inside_a_span():
    assert outro.free_after(((10.0, 12.0),), 10.5) == pytest.approx(1.5)


def test_free_after_outside_every_span_is_zero():
    assert outro.free_after(((10.0, 12.0),), 9.0) == 0.0


def test_gap_rung_picks_the_line_with_room_for_the_fade():
    """The 2026-08-03 case: the reel ends 0.956s past a bar line; the next line up has
    1.50s of vocal-free after it, so the reel grows to line + fade."""
    line = BARS[15]                                    # 35.188 on this synthetic grid
    fit = outro.fit_outro(BARS, ((line, line + 1.5),), reel_dur=34.044, bar_s=BAR,
                          fade=0.5, music_dur=42.0, grow_max=11.5, shrink_max=3.0)
    assert fit == OutroFit(reel_dur=line + 0.5, line=line, fade=0.5, tail=1.5,
                           rung="gap", moved=pytest.approx(line + 0.5 - 34.044))


def test_no_gap_rung_lengthens_the_fade():
    """No line leaves room: fall to the nearest line with NO_GAP_FADE, and say so."""
    fit = outro.fit_outro(BARS, (), reel_dur=34.044, bar_s=BAR, fade=0.5,
                          music_dur=42.0, grow_max=11.5, shrink_max=3.0)
    assert fit.rung == "no-gap"
    assert fit.fade == outro.NO_GAP_FADE
    assert fit.reel_dur == pytest.approx(fit.line + outro.NO_GAP_FADE)
    assert fit.tail == 0.0


def test_no_gap_re_filters_the_band_with_its_own_fade():
    """The longer fade must not smuggle length past the band. With bar_s tight enough
    that line + NO_GAP_FADE leaves it, the answer is 'unchanged', not 'no-gap'."""
    fit = outro.fit_outro((10.0,), (), reel_dur=10.0, bar_s=0.6, fade=0.5,
                          music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "unchanged" and fit.line is None and fit.reel_dur == 10.0


def test_unchanged_when_no_bars():
    fit = outro.fit_outro((), ((0.0, 5.0),), reel_dur=34.044, bar_s=BAR, fade=0.5,
                          music_dur=42.0, grow_max=11.5, shrink_max=3.0)
    assert fit == OutroFit(reel_dur=34.044, line=None, fade=0.5, tail=0.0,
                           rung="unchanged", moved=0.0)


def test_the_music_window_bounds_the_candidates():
    """mix refuses dur > music.duration + 0.1; the fitter must reject the candidate
    instead of letting it crash three stages later."""
    fit = outro.fit_outro((35.0,), ((35.0, 40.0),), reel_dur=34.5, bar_s=BAR, fade=0.5,
                          music_dur=35.2, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "unchanged"


def test_grow_max_bounds_the_extension():
    line = 35.0
    fit = outro.fit_outro((line,), ((line, line + 2.0),), reel_dur=34.0, bar_s=BAR,
                          fade=0.5, music_dur=42.0, grow_max=0.2, shrink_max=99.0)
    assert fit.rung == "unchanged"


def test_shrink_max_bounds_the_shortening():
    """Without it a one-bar step down can leave a 2.5s closing shot at 0.3s."""
    line = 33.0
    fit = outro.fit_outro((line,), ((line, line + 2.0),), reel_dur=34.5, bar_s=BAR,
                          fade=0.5, music_dur=42.0, grow_max=99.0, shrink_max=0.2)
    assert fit.rung == "unchanged"


def test_shortening_is_searched_too():
    line = 33.0
    fit = outro.fit_outro((line,), ((line, line + 2.0),), reel_dur=34.5, bar_s=BAR,
                          fade=0.5, music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "gap" and fit.moved == pytest.approx(33.5 - 34.5)


def test_the_brief_breaks_the_tie():
    """Two qualifying lines, one either side. Without a brief the smaller move wins;
    with a brief the one closer to SPEC.length_s does."""
    spans = ((32.0, 34.0), (36.0, 38.0))
    kw = dict(bars=(32.0, 36.0), vocal_spans=spans, reel_dur=34.4, bar_s=BAR, fade=0.5,
              music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert outro.fit_outro(**kw).line == 32.0                  # |32.5-34.4| < |36.5-34.4|
    assert outro.fit_outro(**kw, brief_len=36.0).line == 36.0   # |36.5-36| < |32.5-36|


def test_fade_zero_needs_only_tail_min():
    """A brief with no look leaves fade at mix's default, but an authored fade of 0 is
    legal: the reel then ends exactly on the line and TAIL_MIN alone is the bar."""
    line = 20.0
    fit = outro.fit_outro((line,), ((line, line + 0.6),), reel_dur=20.3, bar_s=BAR,
                          fade=0.0, music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "gap" and fit.reel_dur == line and fit.fade == 0.0


def test_fit_round_trips():
    fit = OutroFit(reel_dur=35.7, line=35.2, fade=0.5, tail=1.5, rung="gap", moved=1.7)
    assert OutroFit.from_dict(fit.to_dict()) == fit


def test_negative_fade_is_refused():
    with pytest.raises(ValueError, match="fade must be"):
        outro.fit_outro(BARS, (), reel_dur=34.0, bar_s=BAR, fade=-1.0, music_dur=42.0,
                        grow_max=1.0, shrink_max=1.0)


def test_non_positive_bar_is_refused():
    with pytest.raises(ValueError, match="bar_s must be"):
        outro.fit_outro(BARS, (), reel_dur=34.0, bar_s=0.0, fade=0.5, music_dur=42.0,
                        grow_max=1.0, shrink_max=1.0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_outro.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.outro'`

- [ ] **Step 3: Write the module**

Create `scripts/lib/outro.py`:

```python
"""Outro fit — where the reel's music stops (design
docs/specs/2026-08-14-music-outro-fit-design.md).

Pure: numbers in, one OutroFit out. No audio IO, no ffmpeg, no librosa. The whole
slice reduces to picking ONE number, the reel's length, because mix already fades
over [dur - fade, dur] — so a reel of `line + fade` starts its fade exactly on the
bar line and no ffmpeg stage changes at all (design §1)."""
from collections.abc import Sequence
from dataclasses import dataclass

BAR_BEATS = 4       # 4/4 assumed — beats.py's downbeat detector reads this too (§11.3)
TAIL_MIN = 0.5      # vocal-free seconds a boundary must leave. THE PROJECT OWNER'S
                    # ASSUMPTION, not a measurement or a citation (§11.1) — one constant
                    # in one place precisely so re-tuning is a one-line change.
NO_GAP_FADE = 1.5   # the longer fade rung 2 falls back to. Taste, not a measurement (§11.2)
MIN_LAST = 1.0      # the last episode may not be shrunk below this. A floor, not a
                    # finding (§11.7): without it a one-bar step down can leave a 2.5s
                    # closing shot at 0.3s, which is a glitch, not an ending.
RUNGS = ("gap", "no-gap", "unchanged")
_EPS = 1e-9


@dataclass(frozen=True)
class OutroFit:
    """What the fit decided, and on which rung. Carried on EDL.outro as provenance —
    nothing downstream reads it, but a bare duration cannot say why it is that length."""
    reel_dur: float           # the reel length this fit asks for
    line: float | None        # the bar line the music resolves on; None on "unchanged"
    fade: float               # the fade that follows the line
    tail: float               # measured vocal-free seconds after the line
    rung: str                 # one of RUNGS
    moved: float              # reel_dur minus the input reel_dur (signed)

    def __post_init__(self) -> None:
        if self.rung not in RUNGS:
            raise ValueError(f"OutroFit.rung must be one of {RUNGS}, got {self.rung!r}")

    def to_dict(self) -> dict:
        return {"reel_dur": self.reel_dur, "line": self.line, "fade": self.fade,
                "tail": self.tail, "rung": self.rung, "moved": self.moved}

    @classmethod
    def from_dict(cls, d: dict) -> "OutroFit":
        if not isinstance(d, dict):
            raise ValueError(f"OutroFit.from_dict: expected an object, got "
                             f"{type(d).__name__} — re-run edit_plan build")
        return cls(reel_dur=d.get("reel_dur", 0.0), line=d.get("line"),
                   fade=d.get("fade", 0.0), tail=d.get("tail", 0.0),
                   rung=d.get("rung", "unchanged"), moved=d.get("moved", 0.0))


def bar_seconds(tempo: float) -> float:
    """One bar in seconds at `tempo` BPM, assuming 4/4."""
    if not isinstance(tempo, (int, float)) or isinstance(tempo, bool) or tempo <= 0:
        raise ValueError(f"outro.bar_seconds: tempo must be a positive BPM, got {tempo!r}")
    return BAR_BEATS * 60.0 / float(tempo)


def window_spans(spans: Sequence[tuple[float, float]], start_offset: float,
                 duration: float) -> tuple[tuple[float, float], ...]:
    """TRACK-relative spans -> STEM-relative, clipped to [0, duration].

    vocals.vocal_spans measures the whole track; MusicSpec stores the window. This is
    the ONE place the two coordinate systems meet. A span that does not intersect the
    window is dropped, not clamped to a zero-length pair."""
    out = []
    for a, b in spans:
        s, e = max(float(a) - start_offset, 0.0), min(float(b) - start_offset, duration)
        if e > s:
            out.append((s, e))
    return tuple(out)


def free_after(spans: Sequence[tuple[float, float]], t: float) -> float:
    """Continuous vocal-free seconds starting AT `t`; 0.0 when `t` is inside a vocal.

    Spans are ascending and disjoint (MusicSpec enforces it), so the first containing
    span is the answer."""
    for a, b in spans:
        if a - _EPS <= t <= b + _EPS:
            return max(0.0, b - t)
    return 0.0


def _candidates(bars, reel_dur, bar_s, fade, music_dur, grow_max, shrink_max):
    """Bar lines whose `line + fade` is a legal reel length (design §5)."""
    out = []
    for line in bars:
        end = line + fade
        move = end - reel_dur
        if abs(move) > bar_s + _EPS:            # 1. the +/- one-bar band
            continue
        if end > music_dur + _EPS:              # 2. inside the analysed music window
            continue
        if move > grow_max + _EPS:              # 3. the closing shot can grow this far
            continue
        if -move > shrink_max + _EPS:           # 4. ...and shrink this far
            continue
        out.append(float(line))
    return out


def fit_outro(bars: Sequence[float], vocal_spans: Sequence[tuple[float, float]],
              reel_dur: float, bar_s: float, fade: float, *, music_dur: float,
              grow_max: float, shrink_max: float,
              brief_len: float | None = None) -> OutroFit:
    """Pick the reel length that makes the music resolve on a bar line.

    The ladder (design §5): a line with `max(TAIL_MIN, fade)` of vocal-free space after
    it; else the nearest line with NO_GAP_FADE, re-filtered through the band so the
    longer fade cannot smuggle length past it; else nothing moves. There is no refusal
    rung — an awkward music tail is not worth blocking a delivery over, and the caller
    reports which rung won.

    Ties resolve toward `brief_len` (SPEC.length_s) when it is known, else toward the
    smallest move, then toward the earlier line so the answer is deterministic."""
    if not isinstance(fade, (int, float)) or isinstance(fade, bool) or fade < 0:
        raise ValueError(f"outro.fit_outro: fade must be a non-negative number of "
                         f"seconds, got {fade!r}")
    if not isinstance(bar_s, (int, float)) or isinstance(bar_s, bool) or bar_s <= 0:
        raise ValueError(f"outro.fit_outro: bar_s must be a positive number of seconds "
                         f"(one bar) — got {bar_s!r}; derive it with outro.bar_seconds")
    reel_dur = float(reel_dur)
    unchanged = OutroFit(reel_dur=reel_dur, line=None, fade=float(fade), tail=0.0,
                         rung="unchanged", moved=0.0)
    if not bars:
        return unchanged

    def pick(cands, f):
        ref = brief_len if brief_len is not None else reel_dur
        return min(cands, key=lambda line: (abs((line + f) - ref), line))

    need = max(TAIL_MIN, float(fade))
    gapped = [line for line in _candidates(bars, reel_dur, bar_s, fade, music_dur,
                                           grow_max, shrink_max)
              if free_after(vocal_spans, line) >= need - _EPS]
    if gapped:
        line = pick(gapped, fade)
        return OutroFit(reel_dur=line + fade, line=line, fade=float(fade),
                        tail=free_after(vocal_spans, line), rung="gap",
                        moved=(line + fade) - reel_dur)
    long_fade = max(float(fade), NO_GAP_FADE)
    nearest = _candidates(bars, reel_dur, bar_s, long_fade, music_dur,
                          grow_max, shrink_max)
    if nearest:
        line = pick(nearest, long_fade)
        return OutroFit(reel_dur=line + long_fade, line=line, fade=long_fade,
                        tail=free_after(vocal_spans, line), rung="no-gap",
                        moved=(line + long_fade) - reel_dur)
    return unchanged
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_outro.py -q`
Expected: PASS (all 17)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/outro.py tests/lib/test_outro.py
git commit -m "feat(music): lib/outro — the pure outro-fit ladder"
```

---

### Task 4: `EDL.outro` carrier and its markdown section

**Files:**
- Modify: `scripts/lib/edl.py`
- Test: `tests/lib/test_edl.py`

**Interfaces:**
- Consumes: `outro.OutroFit` (Task 3).
- Produces: `EDL.outro: OutroFit | None`, round-tripping through
  `to_dict`/`from_dict`; a **Music outro** section in `EDL.to_markdown()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_edl.py`:

```python
def test_edl_outro_round_trips():
    fit = OutroFit(reel_dur=35.7, line=35.2, fade=0.5, tail=1.5, rung="gap", moved=1.7)
    e = EDL(episodes=(_ep(),), outro=fit)
    assert EDL.from_dict(e.to_dict()).outro == fit


def test_edl_outro_defaults_to_none():
    """None = never fitted (a hand-authored SP1 EDL, or a run with no music), never
    'the ending is fine'."""
    assert EDL(episodes=(_ep(),)).outro is None
    assert EDL.from_dict({"episodes": [_ep().to_dict()]}).outro is None


def test_edl_outro_must_be_an_outrofit():
    with pytest.raises(ValueError, match="EDL.outro must be an OutroFit"):
        EDL(episodes=(_ep(),), outro={"rung": "gap"})


def test_markdown_reports_the_rung_and_the_move():
    fit = OutroFit(reel_dur=35.76, line=35.26, fade=0.5, tail=1.5, rung="gap", moved=1.72)
    md = EDL(episodes=(_ep(),), outro=fit).to_markdown()
    assert "## Music outro" in md
    assert "`gap`" in md and "35.26s" in md and "1.50s" in md and "+1.72s" in md


def test_markdown_has_no_outro_section_when_unfitted():
    assert "Music outro" not in EDL(episodes=(_ep(),)).to_markdown()
```

Add `from scripts.lib.outro import OutroFit` to the test file's imports. `_ep()` is
the existing episode helper in that file; if it is named differently, use whatever
the file already uses to build a minimal `EDLEpisode`.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -q -k outro`
Expected: FAIL — `TypeError: EDL.__init__() got an unexpected keyword argument 'outro'`

- [ ] **Step 3: Add the field**

In `scripts/lib/edl.py`, add `from scripts.lib.outro import OutroFit` to the imports,
and add to `EDL` after `constraints`:

```python
    outro: OutroFit | None = None   # design 2026-08-14 §7. None = never fitted (a
                                    # hand-authored SP1 EDL, or a reel with no music) —
                                    # never "the ending is fine". Provenance only:
                                    # nothing downstream reads it, but the reel's length
                                    # cannot otherwise say which rung chose it.
```

- [ ] **Step 4: Validate, serialize, deserialize**

In `__post_init__`, after the `constraints` check:

```python
        if self.outro is not None and not isinstance(self.outro, OutroFit):
            raise ValueError(f"EDL.outro must be an OutroFit or None, got "
                             f"{type(self.outro).__name__} — re-run edit_plan build")
```

In `to_dict`, inside the dict literal after `"constraints"`:

```python
             "outro": self.outro.to_dict() if self.outro is not None else None,
```

In `from_dict`, in the `cls(...)` call after `constraints=`:

```python
                   outro=OutroFit.from_dict(d["outro"]) if d.get("outro") else None,
```

- [ ] **Step 5: Add the markdown section**

In `to_markdown`, immediately before the final `return "\n".join(lines)`:

```python
        if self.outro is not None and self.outro.line is not None:
            o = self.outro
            if o.rung == "gap":
                why = (f"the music resolves on a bar line at {o.line:.2f}s with "
                       f"{o.tail:.2f}s of vocal-free space after it")
            else:
                why = (f"no bar line in range left {outro_mod.TAIL_MIN:.2f}s of "
                       f"vocal-free space, so the reel ends on the nearest line at "
                       f"{o.line:.2f}s under a longer fade")
            lines += ["", "## Music outro", "", f"- **rung:** `{o.rung}` — {why}",
                      f"- **line** {o.line:.2f}s · **fade** {o.fade:.2f}s · "
                      f"**reel** {o.reel_dur:.2f}s ({o.moved:+.2f}s)"]
```

Import the module for the constant alongside the class:

```python
from scripts.lib import outro as outro_mod
from scripts.lib.outro import OutroFit
```

The section is emitted only when a line was chosen: an `unchanged` rung is the
absence of a decision, and an always-present section would move every existing golden
markdown.

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -q`
Expected: PASS, and no existing markdown golden moves.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/edl.py tests/lib/test_edl.py
git commit -m "feat(music): EDL.outro carries which rung chose the reel's length"
```

---

### Task 5: `edit_plan` applies the fit to the last episode

**Files:**
- Modify: `scripts/edit_plan.py`
- Test: `tests/lib/test_edit_plan.py`

**Interfaces:**
- Consumes: `outro.fit_outro`, `outro.bar_seconds`, `outro.MIN_LAST`,
  `MusicSpec.from_json`, `FootageClip.room_after`, `EDL.outro`.
- Produces: `edit_plan._apply_outro(episodes, footage, music, fade, brief_len) ->
  tuple[list[EDLEpisode], OutroFit]`; `build_edl(..., music=None)`;
  `write_edit_plan(..., music=None)`; the `--music` CLI flag.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_edit_plan.py`:

```python
def test_apply_outro_extends_the_last_episode(tmp_path):
    """The reel grows to line + fade, and the growth lands on the LAST episode's dur."""
    footage = _footage_with(source="a.mp4", dur=30.0, scene_cuts=())
    eps = [_edl_ep(source="a.mp4", start=0.0, dur=10.0),
           _edl_ep(source="a.mp4", start=12.0, dur=4.0)]
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(15.0,), vocal_spans=((15.0, 17.0),))
    out, fit = edit_plan._apply_outro(eps, footage, music, fade=0.5, brief_len=None)
    assert fit.rung == "gap" and fit.line == 15.0
    assert fit.reel_dur == pytest.approx(15.5)
    assert out[-1].dur == pytest.approx(4.0 + 1.5)     # 14.0 realized -> 15.5
    assert out[0].dur == 10.0                          # only the last one moves


def test_apply_outro_refuses_to_move_a_ramped_last_episode(tmp_path, capsys):
    """A ramp makes play_dur() a non-linear function of dur; moving it would need the
    ramp arithmetic and is out of this slice's scope. Skipped and logged, not guessed."""
    footage = _footage_with(source="a.mp4", dur=30.0, scene_cuts=())
    eps = [_edl_ep(source="a.mp4", start=0.0, dur=10.0),
           _edl_ep(source="a.mp4", start=12.0, dur=4.0,
                   ramp={"at": 1.0, "factor": 0.5, "ease": 1.0, "hold": 0.5})]
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(15.0,), vocal_spans=((15.0, 17.0),))
    out, fit = edit_plan._apply_outro(eps, footage, music, fade=0.5, brief_len=None)
    assert fit.rung == "unchanged" and out == eps
    assert "ramp" in capsys.readouterr().err


def test_apply_outro_is_bounded_by_the_closing_shot(capsys):
    """room_after stops at the next scene cut — the fit must not splice two shots."""
    footage = _footage_with(source="a.mp4", dur=30.0, scene_cuts=(16.2,))
    eps = [_edl_ep(source="a.mp4", start=0.0, dur=10.0),
           _edl_ep(source="a.mp4", start=12.0, dur=4.0)]
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(15.0,), vocal_spans=((15.0, 17.0),))
    out, fit = edit_plan._apply_outro(eps, footage, music, fade=0.5, brief_len=None)
    assert fit.rung == "unchanged" and out[-1].dur == 4.0


def test_apply_outro_shrink_floor(capsys):
    """MIN_LAST keeps the closing shot readable."""
    footage = _footage_with(source="a.mp4", dur=30.0, scene_cuts=())
    eps = [_edl_ep(source="a.mp4", start=0.0, dur=10.0),
           _edl_ep(source="a.mp4", start=12.0, dur=1.2)]
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(10.2,), vocal_spans=((10.2, 13.0),))
    out, fit = edit_plan._apply_outro(eps, footage, music, fade=0.5, brief_len=None)
    assert fit.rung == "unchanged" and out[-1].dur == pytest.approx(1.2)
```

`_footage_with` and `_edl_ep` are helpers — if the test file has equivalents under
other names, reuse those. Otherwise add:

```python
def _footage_with(*, source, dur, scene_cuts):
    return Footage(clips=(FootageClip(source=source, dur=dur, fps=30.0,
                                      res=(1920, 1080), scene_cuts=scene_cuts,
                                      shaky=False, windows=()),))


def _edl_ep(**kw):
    base = dict(source="a.mp4", start=0.0, dur=1.0, shot_type="wide",
                composition="center", grid="thirds", layout="fill")
    base.update(kw)
    return EDLEpisode(**base)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -q -k apply_outro`
Expected: FAIL — `AttributeError: module 'scripts.edit_plan' has no attribute '_apply_outro'`

- [ ] **Step 3: Implement `_apply_outro`**

In `scripts/edit_plan.py`, add `outro` to the lib imports and add this function just
after `_back_edge_target`:

```python
def _apply_outro(episodes: list, footage, music, fade: float,
                 brief_len: float | None) -> tuple[list, "outro.OutroFit"]:
    """Move the LAST episode's end so the music resolves on a bar line (design §6).

    The reel's length is the one number this whole slice decides: `line + fade`, which
    starts mix's existing bookend exactly on the line. Only the closing episode moves —
    every cut before it keeps the beat it was fitted to, so check_reel's beat gate stays
    green by construction.

    Applied AFTER _bind_pacing and never through a slot. That guard refuses a slot more
    than half a beat from its episode and exists to catch a spine fitted to a DIFFERENT
    edit; an outro extension is typically two beats and would trip it (§6).

    A ramped closing episode is skipped: `play_dur()` is a non-linear function of `dur`
    once a ramp is present, so growing it would need the ramp arithmetic. Skipped and
    logged, never guessed."""
    if not episodes or not music.bars:
        return episodes, outro.OutroFit(reel_dur=sum(e.play_dur() for e in episodes),
                                        line=None, fade=fade, tail=0.0,
                                        rung="unchanged", moved=0.0)
    last = episodes[-1]
    realized = sum(e.play_dur() for e in episodes)
    unchanged = outro.OutroFit(reel_dur=realized, line=None, fade=fade, tail=0.0,
                               rung="unchanged", moved=0.0)
    if last.ramp is not None:
        _log(f"outro: the closing episode carries a ramp — its played length is not its "
             f"source length, so the outro fit is skipped and the reel stays "
             f"{realized:.2f}s. Move the ramp off the last episode to fit the ending.")
        return episodes, unchanged
    clip = next((c for c in footage.clips if c.source == last.source), None)
    if clip is None:
        _log(f"outro: {last.source!r} is not in FOOTAGE — cannot measure the closing "
             f"shot's room, so the reel stays {realized:.2f}s")
        return episodes, unchanged
    grow_max = max(0.0, clip.room_after(last.start) - last.dur)
    shrink_max = max(0.0, last.play_dur() - outro.MIN_LAST)
    fit = outro.fit_outro(music.bars, music.vocal_spans, realized,
                          outro.bar_seconds(music.tempo), fade,
                          music_dur=music.duration, grow_max=grow_max,
                          shrink_max=shrink_max, brief_len=brief_len)
    if fit.rung == "unchanged":
        _log(f"outro: no bar line within one bar of {realized:.2f}s that the closing shot "
             f"can reach (grow {grow_max:.2f}s / shrink {shrink_max:.2f}s) — the reel "
             f"keeps its footage-derived length and the music will end mid-phrase")
        return episodes, fit
    out = list(episodes)
    out[-1] = dataclasses.replace(last, dur=last.dur + fit.moved)
    brief = "" if brief_len is None else f", {fit.reel_dur - brief_len:+.2f}s vs the brief's {brief_len:.1f}s"
    _log(f"outro: rung {fit.rung} — the music resolves on the bar line at {fit.line:.2f}s "
         f"with {fit.tail:.2f}s of vocal-free space after it; the reel moves "
         f"{fit.moved:+.2f}s to {fit.reel_dur:.2f}s (fade {fit.fade:.2f}s){brief}")
    return out, fit
```

Add `import dataclasses` to the top-of-file imports if it is not already there.

- [ ] **Step 4: Run the unit tests**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -q -k apply_outro`
Expected: PASS

- [ ] **Step 5: Thread it through `build_edl`**

In `build_edl`'s signature add a keyword-only `music=None` (a `MusicSpec | None`) and
a `brief_len: float | None = None`. In the body, replace:

```python
    if pacing is not None:
        episodes = _bind_pacing(episodes, pacing)
        target = _back_edge_target(episodes, pacing)   # pacing owns a paced reel's length (§4)
```

with:

```python
    fit = None
    if pacing is not None:
        episodes = _bind_pacing(episodes, pacing)
        # AFTER the binding and BEFORE the back-edge target: _bind_pacing's half-beat
        # guard must keep guarding what it was built for, and _back_edge_target must
        # report the length the outro fit actually chose (design §6).
        if music is not None:
            episodes, fit = _apply_outro(episodes, footage, music,
                                         resolved_fade, brief_len)
        target = _back_edge_target(episodes, pacing)   # pacing owns a paced reel's length (§4)
```

`resolved_fade` must be the SAME number `build_reel` hands `mix` — the reel's own
bookend. Compute it just above, next to where `resolved_look` is decided, and move
that decision earlier in the function so the fit can read it:

```python
    # the reel's bookend fade, resolved exactly as EDL.look is (selection.json wins over
    # the preset), because it is the number mix uses and therefore the number the outro
    # fit must add to the bar line. No look at all -> mix's own default.
    sel_look = selection.get("look")
    resolved_look = LookSpec.from_dict(sel_look) if sel_look is not None else look
    resolved_fade = resolved_look.fade if resolved_look is not None else _MIX_DEFAULT_FADE
```

Add near the other module constants:

```python
_MIX_DEFAULT_FADE = 0.5    # mix._FADE — the bookend a reel gets when no look is authored.
                           # Duplicated rather than imported: edit_plan must not import a
                           # driver, and this slice does not touch mix.py at all (§1).
```

Delete the now-duplicated `sel_look`/`resolved_look` lines from their old position
near the `return EDL(...)`, and add `outro=fit` to that `EDL(...)` call.

- [ ] **Step 6: Thread it through `write_edit_plan` and the CLI**

`write_edit_plan` gains `music: str | None = None`. Just before `build_edl` is called:

```python
    ms = MusicSpec.from_json(music) if music else None
    if ms is not None and not ms.bars:
        _log(f"outro: {music} has no bar grid (beats found fewer than 8 beats, or the "
             f"file predates the 2026-08-14 fields) — re-run beats to regenerate it; "
             f"the reel keeps its footage-derived length")
```

Pass `music=ms, brief_len=sp.length_s if sp else None` into `build_edl`.

Add the flag in `main`:

```python
    b.add_argument("--music", help="MUSIC.json — fit the reel's end to a bar line "
                                   "with a vocal-free tail (optional, §5.5/backlog #2)")
```

and pass it: `write_edit_plan(..., spec=a.spec, music=a.music)`.

Add `MusicSpec` to the `scripts.lib.models` import line in `edit_plan.py`.

- [ ] **Step 7: Write and run the wiring test**

```python
def test_write_edit_plan_threads_music_into_the_fit(tmp_path, monkeypatch):
    seen = {}
    real = edit_plan.build_edl
    monkeypatch.setattr(edit_plan, "build_edl",
                        lambda *a, **k: seen.update(k) or real(*a, **k))
    # ... build the minimal footage/selection/project/MUSIC.json fixtures the other
    # write_edit_plan tests in this file already use, then:
    edit_plan.write_edit_plan(str(fj), str(sj), str(pj), str(tmp_path),
                              music=str(mj))
    assert isinstance(seen["music"], MusicSpec)
```

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add scripts/edit_plan.py tests/lib/test_edit_plan.py
git commit -m "feat(music): edit_plan fits the reel's end to a bar line"
```

---

### Task 6: The real-ffmpeg end-to-end proof

**Files:**
- Create: `tests/integration/test_outro.py`

**Interfaces:**
- Consumes: everything above, plus the existing integration fixtures.

- [ ] **Step 1: Write the proof**

Create `tests/integration/test_outro.py`. It must run the real chain — write a
MUSIC.json whose bar grid makes exactly one line qualify, run `edit_plan build
--pacing --music`, then `edl_to_reel`, then probe the delivered file:

```python
"""The outro fit, end to end on real bytes (design §9).

The claim under test is the one §1 rests on: choosing reel_dur = line + fade makes
mix's EXISTING afade start exactly on the bar line, with no change to any ffmpeg
stage. A unit test cannot show that — only a delivered file can."""
import json
import subprocess

import numpy as np
import pytest

from scripts.lib import ffbin

pytestmark = pytest.mark.integration


def _probe_dur(path):
    r = subprocess.run([ffbin.ffprobe(), "-v", "error", "-show_entries",
                        "format=duration", "-of", "default=nk=1:nw=1", str(path)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def _rms(path, ss, t):
    raw = subprocess.run([ffbin.ffmpeg(), "-v", "error", "-ss", str(ss), "-i", str(path),
                          "-t", str(t), "-vn", "-ac", "1", "-ar", "22050",
                          "-f", "f32le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.float32)
    return float(np.sqrt((a ** 2).mean())) if len(a) else 0.0


def test_delivered_reel_ends_at_line_plus_fade(tmp_path):
    # 1. build a tone wav long enough to be the music, and a two-episode EDL whose
    #    realized length sits just short of a bar line
    # 2. write MUSIC.json by hand with bars/vocal_spans placing ONE qualifying line
    # 3. edit_plan build --pacing --music, then edl_to_reel
    # 4. assert:
    dur = _probe_dur(out_reel)
    assert dur == pytest.approx(expected_line + expected_fade, abs=0.10)
    # the fade lives AFTER the line: loud just before it, quiet at the very end
    assert _rms(out_reel, expected_line - 0.30, 0.20) > 5 * _rms(out_reel, dur - 0.10, 0.08)
```

Model the fixture construction on the existing SP3→SP1 integration test
(`tests/integration/test_edit_plan.py` or whichever file currently runs
`write_edit_plan` followed by `edl_to_reel` on real bytes) — reuse its clip
synthesis, project.json and selection.json rather than inventing new ones. Fill in
`out_reel`, `expected_line` and `expected_fade` from the fixture you build; the two
asserts above are the actual claims and must not be weakened.

- [ ] **Step 2: Add the control that must NOT move**

In the same file, a second test: the same fixture with `bars=()` in MUSIC.json must
deliver a reel whose duration equals the un-fitted realized length. Without this the
first test passes for any implementation that always extends.

- [ ] **Step 3: Run**

Run: `.venv/bin/python -m pytest tests/integration/test_outro.py -q`
Expected: PASS (slow — real encodes)

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_outro.py
git commit -m "test(music): the delivered reel ends at line + fade, on real bytes"
```

---

### Task 7: Mutation battery, docs and skills

**Files:**
- Modify: `docs/build-status.md`, `docs/backlog.md`, `docs/pipeline-map.md`,
  `CLAUDE.md`, `skills/edit-plan/SKILL.md`, `skills/pacing/SKILL.md`,
  `skills/using-montage/SKILL.md`

- [ ] **Step 1: Run the mutation battery**

For each row: make the mutation, run the named test, **confirm RED**, revert,
**confirm GREEN**. A row that stays green is a coverage hole — close it with a new
test before moving on, and record what you added.

| # | Mutation | Must fail |
|---|---|---|
| 1 | `free_after(...) >= need` → `> need` | `test_gap_rung_picks_the_line_with_room_for_the_fade` |
| 2 | delete the `end > music_dur` condition | `test_the_music_window_bounds_the_candidates` |
| 3 | delete the `move > grow_max` condition | `test_grow_max_bounds_the_extension` |
| 4 | delete the `-move > shrink_max` condition | `test_shrink_max_bounds_the_shortening` |
| 5 | rung 2 reuses rung 1's candidate list instead of re-filtering | `test_no_gap_re_filters_the_band_with_its_own_fade` |
| 6 | `bars = tuple(beats[0::BAR_BEATS])` unconditionally in `analyze` | `test_analyze_fills_bars_from_the_detected_phase` |
| 7 | `_downbeat_phase` uses `librosa.onset.onset_strength` instead of the low band | `test_downbeat_phase_finds_the_bass_phase` |
| 8 | `vocal_spans` calls `separate_vocal_energy(track)` (2 Hz default) | `test_vocal_spans_uses_a_fine_envelope_not_the_2hz_one` **and** the integration proof — this is §8.1, the mutation that already fooled this design once |
| 9 | `_apply_outro` applied before `_bind_pacing` | the pacing binding tests (must trip the half-beat guard) |
| 10 | `_apply_outro` moves `episodes[0]` instead of `episodes[-1]` | `test_apply_outro_extends_the_last_episode` |
| 11 | drop the ramp guard in `_apply_outro` | `test_apply_outro_refuses_to_move_a_ramped_last_episode` |
| 12 | `resolved_fade` hardcoded to `0.5` | add a test with an authored `look.fade = 1.0` if none fails |

- [ ] **Step 2: Run the whole suite on cleared bytecode**

```bash
find . -name "__pycache__" -type d -not -path "./.git/*" -exec rm -rf {} + 2>/dev/null
.venv/bin/python -m pytest -q
```

Expected: all pass; the only skips are the pre-existing torchreid and off-network
iTunes ones. Report the exact counts.

- [ ] **Step 3: Sync the docs**

- `docs/build-status.md` — a **Done** entry at the top: what landed, the measured
  numbers from the design (`4.313/4.285/4.267/4.309` vs `1.887` and 14/18), the
  §8.1 resolution trap, and the honest limits verbatim from §11.
- `docs/backlog.md` — flip **#2** from `◐` to `✅` in both the P1 table and the
  #1–#20 status table, dated 2026-08-14, naming what remains (meter, real section
  detection, the audio check — already filed in P3). Update `_Last updated:_`.
- `docs/pipeline-map.md` — §5.6/§5.7's row gains the outro fit.
- `CLAUDE.md` — a plan row beside the existing design row.
- `skills/edit-plan/SKILL.md` — `--music` and what each rung means for the author.
- `skills/pacing/SKILL.md` — the re-run of `edit_plan build` now also passes
  `--music`.
- `skills/using-montage/SKILL.md` — the same flag in the stage's command.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs(music): the outro fit lands — backlog #2 closed"
```

---

## Self-Review

**Spec coverage.** §1 → Task 5 (the reel length is the only lever; no ffmpeg file is
touched — enforced by a Global Constraint). §2 → Task 0. §3 → Task 2. §4 → Task 1.
§5 → Task 3 (every condition and rung has a test). §6 → Task 5. §7 → Task 4.
§8 → the mutation battery rows 5, 8, 9 and the `music_dur` condition. §9 → Tasks 3, 6, 7.
§11 → the constants carry their honesty in comments; Task 7 copies them into
build-status. §12 → the backlog rows are already filed (commit `58580e2`).

**One design amendment this plan forces:** §5 does not mention a ramped closing
episode. `play_dur()` is non-linear in `dur` once a ramp is present, so the fit
cannot simply add `moved` to `dur`. The plan skips-and-logs (Task 5, Step 3) and the
design gets a matching sentence in the same commit as Task 5.

**Placeholders.** Task 6 leaves the fixture construction to the implementer with a
pointer to the file to model it on, but states the two asserts literally — that is
the boundary between "reuse the existing pattern" and "invent the claim", and the
claim is written out.

**Type consistency.** `OutroFit` field names are identical in Tasks 3, 4 and 5.
`fit_outro`'s keyword-only arguments (`music_dur`, `grow_max`, `shrink_max`,
`brief_len`) match between the module, the tests and `_apply_outro`'s call.
`outro.BAR_BEATS` is defined in Task 3 and consumed by Task 2 — noted in Task 2's
Interfaces block, so an out-of-order implementer knows to do Task 3 first.
