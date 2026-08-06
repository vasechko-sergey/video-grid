# Music Spine (Phase B · B1+B2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the reel sound — a lean `MUSIC.json` analysis (`beats.py`), a music-only audio stem muxed at deliver (`mix.py`), and the first two silent gates closed (`check_reel` loudness=hard, beat=advisory).

**Architecture:** `beats.analyze` (librosa) emits a typed `MusicSpec`. Inside the shipped `build_reel` driver the picture reprocess loop is untouched; once the picture passes, the stem is built **once** (`mix.py`), a final `check_reel` lights loudness (hard) + beat (advisory), and `deliver` muxes the stem. `MusicSpec` is a config-spec (validates hard); beat is measured but excluded from `ReelReport.overall` (no re-trim actuator yet), loudness rides `next_action`'s existing escalate path via `escalate_to="audio-mix"` — so `next_action` needs no change.

**Tech Stack:** Python 3.13, librosa (lazy import), ffmpeg/ffprobe (external, `loudnorm` two-pass + `afade` + mux), numpy/scipy (synthetic WAV fixtures), pytest. Reuses the shipped `models`, `check_reel`, `deliver`, `build_reel`, `assembly`, `process_episode`.

**Design spec:** [docs/specs/2026-07-11-music-spine-design.md](../specs/2026-07-11-music-spine-design.md). Read §2 (contract), §5 (the two gates + the `_ADVISORY_CHECKS`/`overall` rule — the one subtle part), and §6 (driver integration) before starting.

**Standards:** [docs/coding-standards.md](../coding-standards.md) — fail loud WITH a remedy, imports at module top (librosa is the sanctioned lazy exception, §5.5), every module-level def fully typed, config-specs raise `ValueError` in `__post_init__`, scripts run as modules (`pythonpath = .`). Landmines ([CLAUDE.md](../../CLAUDE.md)): `-ss` after `-i` for frame-accurate **video** (audio seek is exempt but placed accurately), `colorchannelmixer` only, even output dims.

**Testing:** [docs/testing-guide.md](../testing-guide.md) — TDD, whole-object asserts, real-dependency goldens on synthetic known-answer inputs, `@pytest.mark.integration` for anything touching ffmpeg/librosa.

---

## File Structure

```
scripts/beats.py            NEW    B1: analyze(track, start_offset, duration) → MusicSpec; CLI writes MUSIC.json.
scripts/mix.py              NEW    B2: mix(music, out_dir, dur) → out_dir/audio.m4a (fade + two-pass loudnorm −14 LUFS aac); CLI.
scripts/lib/models.py       EDIT   MusicSpec config-spec; ReelCheckSpec += beat_tol/loudness_target/loudness_tol;
                                   _ADVISORY_CHECKS + ReelReport.overall excludes them; ReelManifest += music path.
scripts/check_reel.py       EDIT   run() += music/audio; _loudness_check + _beat_check + _loudnorm_measure helpers;
                                   _NOT_IMPL loop → setdefault so computed checks aren't overwritten.
scripts/deliver.py          EDIT   deliver() += audio: mux the aac stem (strip the profile's -an, map both streams).
scripts/build_reel.py       EDIT   load MusicSpec from rm.music; mix once after picture passes; deliver with the stem;
                                   need_assemble guard; music=None → silent path unchanged.
```

Tests: `tests/lib/test_models.py`, `tests/lib/test_check_reel.py`, `tests/lib/test_deliver.py`, `tests/lib/test_build_reel.py` (add); `tests/integration/test_beats.py`, `tests/integration/test_music_spine.py` (new).

Task order respects dependencies: **0** contract → **1** beats (B1 done) → **2** model gate-support → **3** check_reel gates → **4** mix → **5** deliver mux → **6** driver integration → **7** real-ffmpeg end-to-end → **8** docs.

---

## Task 0: `MusicSpec` config-spec

**Files:**
- Modify: `scripts/lib/models.py` (add `MusicSpec` after `ReelCheckSpec`)
- Test: `tests/lib/test_models.py`

- [x] **Step 1: Write the failing tests**

Add to `tests/lib/test_models.py` (top-level, near the other spec tests; `MusicSpec` must be in the file's `from scripts.lib.models import ...`):

```python
def _music(**kw):
    d = dict(track="t.m4a", start_offset=0.0, duration=10.0, tempo=120.0,
             beats=(0.0, 0.5, 1.0), energy=(0.1, 0.2), energy_hz=2.0)
    d.update(kw)
    return d


def test_musicspec_roundtrips():
    m = MusicSpec.from_dict(_music())
    assert MusicSpec.from_dict(m.to_dict()) == m
    assert m.beats == (0.0, 0.5, 1.0) and m.duration == 10.0


@pytest.mark.parametrize("kw, msg", [
    (dict(track=""), "non-empty path"),
    (dict(start_offset=-1), ">= 0"),
    (dict(duration=0), "positive number"),
    (dict(tempo=0), "positive BPM"),
    (dict(beats=()), "beats is empty"),
    (dict(beats=(1.0, 0.5)), "ascending"),
    (dict(beats=(0.0, 99.0)), r"outside \[0, 10.0\]"),
    (dict(energy=()), "energy is empty"),
    (dict(energy_hz=0), "positive sample rate"),
])
def test_musicspec_rejects_with_remedy(kw, msg):
    with pytest.raises(ValueError, match=msg):
        MusicSpec.from_dict(_music(**kw))
```

- [x] **Step 2: Run to verify it fails**

Run: `pytest tests/lib/test_models.py -k musicspec -q`
Expected: FAIL — `ImportError`/`NameError: MusicSpec`.

- [x] **Step 3: Implement `MusicSpec`**

In `scripts/lib/models.py`, add after the `ReelCheckSpec` class:

```python
@dataclass
class MusicSpec:
    """MUSIC.json — the lean music analysis a reel is cut to (design §2, Phase B).
    Config-spec: validates on construction so a malformed track spec fails loud,
    not into a silent mis-mix. Beats are reel-relative (0.0 = reel start)."""
    track: str
    start_offset: float
    duration: float
    tempo: float
    beats: tuple[float, ...]
    energy: tuple[float, ...]
    energy_hz: float

    def __post_init__(self) -> None:
        if not (isinstance(self.track, str) and self.track):
            raise ValueError("MusicSpec.track must be a non-empty path to the audio file")
        if not isinstance(self.start_offset, (int, float)) or self.start_offset < 0:
            raise ValueError(f"MusicSpec.start_offset must be >= 0 seconds, got {self.start_offset!r}")
        if not isinstance(self.duration, (int, float)) or self.duration <= 0:
            raise ValueError(f"MusicSpec.duration must be a positive number of seconds, got {self.duration!r}")
        if not isinstance(self.tempo, (int, float)) or self.tempo <= 0:
            raise ValueError(f"MusicSpec.tempo must be a positive BPM, got {self.tempo!r}")
        self.beats = tuple(float(b) for b in self.beats)
        if not self.beats:
            raise ValueError("MusicSpec.beats is empty — analyze() found no beats; check the track/window")
        if list(self.beats) != sorted(self.beats):
            raise ValueError("MusicSpec.beats must be ascending — analyze() emits them in time order")
        for b in self.beats:
            if not (0.0 <= b <= self.duration):
                raise ValueError(f"MusicSpec.beats has {b} outside [0, {self.duration}] — beats are "
                                 "reel-relative; a stray value means the analysis window is wrong")
        self.energy = tuple(float(e) for e in self.energy)
        if not self.energy:
            raise ValueError("MusicSpec.energy is empty — analyze() produced no RMS curve")
        if not isinstance(self.energy_hz, (int, float)) or self.energy_hz <= 0:
            raise ValueError(f"MusicSpec.energy_hz must be a positive sample rate, got {self.energy_hz!r}")

    def to_dict(self) -> dict:
        return {"track": self.track, "start_offset": self.start_offset, "duration": self.duration,
                "tempo": self.tempo, "beats": list(self.beats),
                "energy": list(self.energy), "energy_hz": self.energy_hz}

    @classmethod
    def from_dict(cls, d: dict) -> "MusicSpec":
        # .get with validation-tripping defaults → a missing key surfaces a remedy, not a bare KeyError
        return cls(track=d.get("track", ""), start_offset=d.get("start_offset", 0.0),
                   duration=d.get("duration", 0.0), tempo=d.get("tempo", 0.0),
                   beats=tuple(d.get("beats", ())), energy=tuple(d.get("energy", ())),
                   energy_hz=d.get("energy_hz", 0.0))

    @classmethod
    def from_json(cls, path: str | Path) -> "MusicSpec":
        return cls.from_dict(json.loads(Path(path).read_text()))
```

(`Path`, `json`, `dataclass`, `field` are already imported at the top of `models.py`.)

- [x] **Step 4: Run to verify it passes**

Run: `pytest tests/lib/test_models.py -k musicspec -q`
Expected: PASS (10 cases: 1 round-trip + 9 rejects).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "$(printf 'feat: MusicSpec config-spec (MUSIC.json contract, Phase B)\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 1: `beats.py` — analyze → MusicSpec (B1)

**Files:**
- Create: `scripts/beats.py`
- Test: `tests/integration/test_beats.py`

- [x] **Step 1: Write the failing test** (real librosa, synthetic click track)

Create `tests/integration/test_beats.py`:

```python
"""Real-librosa golden for beats-core (design §3). A synthetic click track at a
known BPM is a deterministic known-answer input — librosa isn't bit-exact on real
songs, so we pin tempo/beat-spacing within tolerance, not exactly."""
import numpy as np
import pytest
from scipy.io import wavfile

from scripts import beats
from scripts.lib.models import MusicSpec


def _click_wav(path, bpm=120, secs=8, sr=22050):
    """`secs` of silence with a short 1 kHz burst on every beat."""
    n = int(secs * sr)
    y = np.zeros(n, dtype=np.float32)
    burst = (0.9 * np.sin(2 * np.pi * 1000 * np.arange(int(0.02 * sr)) / sr)).astype(np.float32)
    period = 60.0 / bpm
    for k in range(int(secs / period)):
        i = int(k * period * sr)
        y[i:i + len(burst)] += burst[:max(0, n - i)]
    wavfile.write(path, sr, y)
    return str(path)


@pytest.mark.integration
def test_analyze_recovers_tempo_beats_and_energy(tmp_path):
    wav = _click_wav(tmp_path / "click.wav", bpm=120, secs=8)
    ms = beats.analyze(wav, start_offset=0.0, duration=None)
    assert isinstance(ms, MusicSpec)
    assert abs(ms.tempo - 120) <= 3                          # librosa recovers the click BPM
    assert len(ms.beats) >= 12                               # ~16 beats in 8s @120bpm; generous floor
    gaps = [b2 - b1 for b1, b2 in zip(ms.beats, ms.beats[1:])]
    assert abs(float(np.median(gaps)) - 0.5) <= 0.08         # median inter-beat ≈ 0.5s
    assert all(0.0 <= b <= ms.duration for b in ms.beats)    # reel-relative, in-window
    assert len(ms.energy) > 0 and ms.energy_hz > 0           # coarse RMS curve present
```

- [x] **Step 2: Run to verify it fails**

Run: `pytest tests/integration/test_beats.py -q`
Expected: FAIL — `ModuleNotFoundError: scripts.beats`.

- [x] **Step 3: Implement `scripts/beats.py`**

```python
"""music-and-mood (montage §5.5, lean B1): analyse a local track → MusicSpec
(tempo + reel-relative beat grid + coarse RMS energy). librosa imports lazily
(§5.5 — heavy, keep test collection fast). CLI writes MUSIC.json."""
import argparse
import json
from pathlib import Path

import numpy as np

from scripts.lib.models import MusicSpec

_HOP = 512                                            # librosa beat/rms default hop_length


def _downsample(rms: np.ndarray, sr: int, hop: int, target_hz: float) -> tuple[list[float], float]:
    """Average per-frame RMS into ~target_hz bins → a short coarse energy curve.
    Returns (energy, energy_hz)."""
    frame_hz = sr / hop
    step = max(1, int(round(frame_hz / target_hz)))
    energy = [float(np.mean(rms[i:i + step])) for i in range(0, len(rms), step)]
    return energy, frame_hz / step


def analyze(track: str, start_offset: float = 0.0, duration: float | None = None) -> MusicSpec:
    """Analyse track's [start_offset, start_offset+duration] window → MusicSpec.
    Beats come out reel-relative (0.0 = window start) so they compare directly to
    reel cut times. duration=None analyses to the end of the track."""
    import librosa                                    # lazy — heavy; montage §5.5
    y, sr = librosa.load(track, sr=None, offset=start_offset, duration=duration)
    dur = float(len(y) / sr)
    tempo, frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=_HOP, units="frames")
    tempo = float(np.atleast_1d(tempo)[0])            # librosa >=0.10 returns tempo as an array
    beats = tuple(float(t) for t in librosa.frames_to_time(frames, sr=sr, hop_length=_HOP)
                  if 0.0 <= t <= dur)
    rms = librosa.feature.rms(y=y, hop_length=_HOP)[0]
    energy, energy_hz = _downsample(rms, sr, _HOP, target_hz=2.0)
    return MusicSpec(track=track, start_offset=float(start_offset), duration=dur,
                     tempo=tempo, beats=beats, energy=tuple(energy), energy_hz=energy_hz)


def main() -> None:
    ap = argparse.ArgumentParser(description="analyse a track → MUSIC.json (tempo + beats + energy)")
    ap.add_argument("track")
    ap.add_argument("--start-offset", type=float, default=0.0)
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--out", required=True, help="MUSIC.json output path")
    a = ap.parse_args()
    ms = analyze(a.track, a.start_offset, a.duration)
    Path(a.out).write_text(json.dumps(ms.to_dict(), indent=2))
    print(a.out)


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Run to verify it passes**

Run: `pytest tests/integration/test_beats.py -q`
Expected: PASS (librosa analyses the 8s click track in ~1–2s).

- [x] **Step 5: Commit**

```bash
git add scripts/beats.py tests/integration/test_beats.py
git commit -m "$(printf 'feat: beats.py — analyze track → MusicSpec (B1, real-librosa golden)\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 2: `ReelCheckSpec` thresholds + advisory-aware `overall`

**Files:**
- Modify: `scripts/lib/models.py` (`ReelCheckSpec`, new `_ADVISORY_CHECKS`, `ReelReport.overall`)
- Test: `tests/lib/test_models.py`

- [x] **Step 1: Write the failing tests**

Add to `tests/lib/test_models.py` (`CheckResult`, `ReelReport`, `ReelCheckSpec` are already imported there):

```python
def test_reelcheckspec_audio_thresholds_default_and_validate():
    s = ReelCheckSpec(target_dur=30.0)
    assert (s.beat_tol, s.loudness_target, s.loudness_tol) == (0.05, -14.0, 1.0)
    with pytest.raises(ValueError, match="beat_tol"):
        ReelCheckSpec(target_dur=30.0, beat_tol=0)
    with pytest.raises(ValueError, match="loudness_tol"):
        ReelCheckSpec(target_dur=30.0, loudness_tol=-1)


def test_reelreport_overall_excludes_advisory_beat():
    checks = {"black": CheckResult("black", True, {}),
              "beat": CheckResult("beat", False, {"worst_dev": 0.3})}
    assert ReelReport(checks=checks).overall is True          # advisory beat=False does NOT block delivery


def test_reelreport_overall_blocks_on_loudness_false():
    assert ReelReport(checks={"loudness": CheckResult("loudness", False, {"measured": -9.0})}).overall is False
```

- [x] **Step 2: Run to verify it fails**

Run: `pytest tests/lib/test_models.py -k "audio_thresholds or advisory or loudness_false" -q`
Expected: FAIL — `TypeError: unexpected keyword 'beat_tol'` / advisory test asserts `True` but gets `False`.

- [x] **Step 3: Implement the model changes**

In `ReelCheckSpec`, add the three fields (after `color_delta_max`):

```python
    beat_tol: float = 0.05             # advisory: max cut-vs-beat deviation (s) that still reads "on beat"
    loudness_target: float = -14.0     # EBU R128 integrated LUFS target (montage §5.12)
    loudness_tol: float = 1.0          # ± band around the target
```

and append to its `__post_init__`:

```python
        if not isinstance(self.beat_tol, (int, float)) or self.beat_tol <= 0:
            raise ValueError(f"ReelCheckSpec.beat_tol must be a positive number of seconds, got {self.beat_tol!r}")
        if not isinstance(self.loudness_target, (int, float)):
            raise ValueError(f"ReelCheckSpec.loudness_target must be a number (LUFS), got {self.loudness_target!r}")
        if not isinstance(self.loudness_tol, (int, float)) or self.loudness_tol <= 0:
            raise ValueError(f"ReelCheckSpec.loudness_tol must be a positive number, got {self.loudness_tol!r}")
```

Add a module constant immediately above the `ReelReport` class:

```python
_ADVISORY_CHECKS = ("beat",)           # measured + reported but non-blocking — no re-trim actuator yet (design §5)
```

Replace `ReelReport.overall` with the advisory-aware form:

```python
    @property
    def overall(self) -> bool:
        return all(c.passed is not False
                   for n, c in self.checks.items() if n not in _ADVISORY_CHECKS)
```

- [x] **Step 4: Run to verify it passes**

Run: `pytest tests/lib/test_models.py -q`
Expected: PASS (new cases green; existing `ReelReport`/`ReelCheckSpec` cases unaffected — a passing reel has no advisory `False` to skip).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "$(printf 'feat: ReelCheckSpec audio thresholds + advisory-aware overall\n\nbeat_tol/loudness_target/loudness_tol; _ADVISORY_CHECKS excludes beat from\nReelReport.overall so an off-beat reel is reported but not blocked (design §5).\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 3: `check_reel` — loudness (hard) + beat (advisory)

**Files:**
- Modify: `scripts/check_reel.py` (`run` signature/body; `_loudnorm_measure`, `_loudness_check`, `_beat_check` helpers; `MusicSpec` import)
- Test: `tests/lib/test_check_reel.py`

- [x] **Step 1: Write the failing tests** (pure — no ffmpeg; the helpers are extracted for exactly this)

Add to `tests/lib/test_check_reel.py`:

```python
from scripts.lib.models import ReelCheckSpec        # if not already imported


def test_beat_check_on_beat():
    cr = check_reel._beat_check([1.0, 2.0], (0.0, 1.02, 1.98, 3.0), 0.05)
    assert cr.passed is True and cr.detail["worst_dev"] == 0.02 and cr.detail["n_cuts"] == 2


def test_beat_check_off_beat():
    cr = check_reel._beat_check([1.0], (0.0, 0.5, 1.3), 0.05)   # nearest beat 1.3 → dev 0.30
    assert cr.passed is False and cr.detail["worst_dev"] == 0.3


def test_beat_check_single_episode_na():
    cr = check_reel._beat_check([], (0.0, 0.5), 0.05)
    assert cr.passed is None and cr.detail["status"] == "n/a"


def test_loudness_check_in_range():
    cr, fail = check_reel._loudness_check(-14.4, ReelCheckSpec(target_dur=30.0))
    assert cr.passed is True and fail is None


def test_loudness_check_out_of_range_escalates_to_audio_mix():
    cr, fail = check_reel._loudness_check(-9.0, ReelCheckSpec(target_dur=30.0))
    assert cr.passed is False
    assert fail is not None and fail.check == "loudness" and fail.escalate_to == "audio-mix"
```

- [x] **Step 2: Run to verify it fails**

Run: `pytest tests/lib/test_check_reel.py -k "beat_check or loudness_check" -q`
Expected: FAIL — `AttributeError: module 'scripts.check_reel' has no attribute '_beat_check'`.

- [x] **Step 3: Implement the helpers + wire `run`**

In `scripts/check_reel.py`, extend the models import to include `MusicSpec`:

```python
from scripts.lib.models import CheckResult, MusicSpec, ReelCheckSpec, ReelFailure, ReelReport
```

Add these three helpers (near the other module helpers, e.g. after `_hamming`):

```python
def _loudnorm_measure(audio: str) -> float:
    """Integrated loudness (LUFS) via ffmpeg loudnorm's analysis pass — the same
    measure loudnorm normalizes to, so the gate reads what deliver ships (§5)."""
    r = proc.run(["ffmpeg", "-i", audio, "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    err = (r.stderr or b"").decode("utf-8", errors="replace")
    m = re.search(r'"input_i"\s*:\s*"?(-?\d+\.?\d*)"?', err)
    if not m:
        raise RuntimeError(f"loudnorm printed no input_i for {audio} — the file may have no audio "
                           "stream; mix must produce the stem before the loudness gate runs")
    return float(m.group(1))


def _loudness_check(measured: float, spec: ReelCheckSpec) -> tuple[CheckResult, ReelFailure | None]:
    """LOUDNESS — hard gate. In band → pass; out → a ReelFailure that next_action
    escalates via escalate_to='audio-mix' (a bad mix stops-and-reports, §5)."""
    ok = abs(measured - spec.loudness_target) <= spec.loudness_tol
    detail = {"measured": round(measured, 2), "target": spec.loudness_target}
    fail = None if ok else ReelFailure("loudness", "audio-mix", None, dict(detail))
    return CheckResult("loudness", ok, detail), fail


def _beat_check(cuts: list[float], beats: tuple[float, ...], tol: float) -> CheckResult:
    """BEAT — advisory. Worst deviation of a cut from its nearest beat; reported,
    never a ReelFailure (excluded from overall via _ADVISORY_CHECKS, §5)."""
    if not cuts:
        return CheckResult("beat", None, {"status": "n/a", "reason": "single episode, no cut"})
    worst = max(min(abs(t - b) for b in beats) for t in cuts)
    return CheckResult("beat", worst <= tol,
                       {"worst_dev": round(worst, 3), "tol": tol, "n_cuts": len(cuts)})
```

Change `run`'s signature to accept the two optional inputs:

```python
def run(master: str, episodes: list[str], spec: ReelCheckSpec, out_report: str,
        music: MusicSpec | None = None, audio: str | None = None) -> ReelReport:
```

Immediately **before** the existing `for name, reason in _NOT_IMPL.items():` block, insert:

```python
    if audio is not None:
        cr, fail = _loudness_check(_loudnorm_measure(audio), spec)
        checks["loudness"] = cr
        if fail is not None:
            fails.append(fail)
    if music is not None:
        checks["beat"] = _beat_check(cuts, music.beats, spec.beat_tol)
```

and change the `_NOT_IMPL` loop from an unconditional assign to `setdefault` so a computed check isn't overwritten (safe_zones always stays a stub):

```python
    for name, reason in _NOT_IMPL.items():
        checks.setdefault(name, CheckResult(name, None, {"status": "not-implemented", "reason": reason}))
```

(`cuts` is already in scope — `cuts = _boundaries(durations)` earlier in `run`. `re`, `proc` are already imported.)

- [x] **Step 4: Run to verify it passes**

Run: `pytest tests/lib/test_check_reel.py -q`
Expected: PASS (new helper tests green; existing check_reel tests unaffected — `music`/`audio` default `None`, so those checks fall through to the `setdefault` stub exactly as before).

- [x] **Step 5: Commit**

```bash
git add scripts/check_reel.py tests/lib/test_check_reel.py
git commit -m "$(printf 'feat: check_reel loudness (hard) + beat (advisory) gates\n\nrun() gains optional music/audio; _loudness_check escalates to audio-mix on a\nmiss, _beat_check is measured-but-advisory. Absent inputs → unchanged stubs.\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 4: `mix.py` — music-only stem (B2)

**Files:**
- Create: `scripts/mix.py`
- Test: `tests/integration/test_music_spine.py`

- [x] **Step 1: Write the failing test** (real ffmpeg — the stem hits −14 LUFS)

Create `tests/integration/test_music_spine.py`:

```python
"""Real-ffmpeg proofs for the music spine (design §7): (A) mix hits −14 LUFS;
(B) build_reel delivers a reel WITH an audio stream end-to-end. Clips are built
with the real reframe encoder, matching test_reel_retry.py's precedent."""
import json

import numpy as np
import pytest
from scipy.io import wavfile

from scripts import build_reel, check_reel, mix, reframe
from scripts.lib import proc
from scripts.lib.models import (Delivery, LayoutSpec, MusicSpec, ReframeSpec,
                                ReelEpisode, ReelManifest)


def _tone_music(tmp_path, secs=6, sr=22050):
    """A steady 220 Hz tone + a MusicSpec describing it (a beat every 0.5s)."""
    n = int(secs * sr)
    y = (0.3 * np.sin(2 * np.pi * 220 * np.arange(n) / sr)).astype(np.float32)
    wav = tmp_path / "tone.wav"
    wavfile.write(wav, sr, y)
    beats = tuple(round(k * 0.5, 3) for k in range(int(secs / 0.5)))
    return MusicSpec(track=str(wav), start_offset=0.0, duration=float(secs), tempo=120.0,
                     beats=beats, energy=(0.3, 0.3, 0.3), energy_hz=2.0)


@pytest.mark.integration
def test_mix_hits_target_loudness(tmp_path):
    ms = _tone_music(tmp_path, secs=6)
    stem = mix.mix(ms, str(tmp_path / "out"), dur=6.0)
    measured = check_reel._loudnorm_measure(stem)
    assert abs(measured - (-14.0)) <= 1.5          # two-pass loudnorm lands within ~1 LUFS; margin generous
```

- [x] **Step 2: Run to verify it fails**

Run: `pytest tests/integration/test_music_spine.py -k mix -q`
Expected: FAIL — `ModuleNotFoundError: scripts.mix`.

- [x] **Step 3: Implement `scripts/mix.py`**

```python
"""audio-mix (montage §5.12, music-only B2): build the reel's audio stem from a
MusicSpec — seek the chosen fragment, fade, two-pass loudnorm to −14 LUFS → aac.
Ambient ducking + SFX arrive when extract preserves per-episode audio (§5.8);
this signature is the stable seam for them."""
import argparse
import os
import re
import tempfile

from scripts.lib import proc
from scripts.lib.models import MusicSpec

_TARGET_LUFS = -14.0                                  # EBU R128 (montage §5.12)
_FADE = 0.5


def _measure(audio: str) -> dict:
    """loudnorm analysis pass → the measured stats the accurate second pass needs."""
    r = proc.run(["ffmpeg", "-i", audio, "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    err = (r.stderr or b"").decode("utf-8", errors="replace")
    stats = {}
    for k in ("input_i", "input_tp", "input_lra", "input_thresh"):
        m = re.search(rf'"{k}"\s*:\s*"?(-?\d+\.?\d*)"?', err)
        if not m:
            raise RuntimeError(f"loudnorm printed no {k} for {audio} — cannot run the accurate "
                               "second pass; the chosen fragment may be silent")
        stats[k] = m.group(1)
    return stats


def mix(music: MusicSpec, out_dir: str, dur: float) -> str:
    """Music-only audio stem for a `dur`-second reel → out_dir/audio.m4a (aac, −14 LUFS)."""
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "audio.m4a")
    with tempfile.TemporaryDirectory() as d:
        frag = os.path.join(d, "frag.wav")
        # accurate-seek the fragment (audio seek is exempt from the frame-accurate-video
        # landmine, but placed exactly), trim to the reel length, fade in/out
        proc.run(["ffmpeg", "-y", "-accurate_seek", "-ss", f"{music.start_offset}",
                  "-i", music.track, "-t", f"{dur}",
                  "-af", f"afade=t=in:st=0:d={_FADE},afade=t=out:st={max(0.0, dur - _FADE)}:d={_FADE}",
                  frag])
        st = _measure(frag)
        proc.run(["ffmpeg", "-y", "-i", frag, "-af",
                  (f"loudnorm=I={_TARGET_LUFS}:TP=-1.5:LRA=11:"
                   f"measured_I={st['input_i']}:measured_TP={st['input_tp']}:"
                   f"measured_LRA={st['input_lra']}:measured_thresh={st['input_thresh']}"),
                  "-c:a", "aac", "-b:a", "192k", out])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="build the reel audio stem from MUSIC.json")
    ap.add_argument("music", help="MUSIC.json path")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--dur", type=float, required=True, help="reel length (seconds)")
    a = ap.parse_args()
    print(mix(MusicSpec.from_json(a.music), a.out_dir, a.dur))


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Run to verify it passes**

Run: `pytest tests/integration/test_music_spine.py -k mix -q`
Expected: PASS (measured integrated loudness within 1.5 LUFS of −14).

- [x] **Step 5: Commit**

```bash
git add scripts/mix.py tests/integration/test_music_spine.py
git commit -m "$(printf 'feat: mix.py — music-only audio stem, two-pass loudnorm -14 LUFS (B2)\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 5: `deliver` — mux the audio stem

**Files:**
- Modify: `scripts/deliver.py` (`deliver` signature/body)
- Test: `tests/lib/test_deliver.py`

- [x] **Step 1: Write the failing tests** (mock `proc.run` — assert the command shape, no ffmpeg)

Add to `tests/lib/test_deliver.py` (create the file if absent, with `import subprocess`, `import pytest`, `from scripts import deliver`, `from scripts.lib.models import REEL_H264, ReelReport, CheckResult`):

```python
def _fake_cp():
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")


def _ok_report():
    return ReelReport(checks={"black": CheckResult("black", True, {})})


def test_deliver_muxes_audio_when_given(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(deliver.proc, "run", lambda cmd, **k: (calls.append(cmd), _fake_cp())[1])
    deliver.deliver(str(tmp_path / "m.mp4"), REEL_H264, str(tmp_path / "out"), "v1",
                    _ok_report(), audio=str(tmp_path / "a.m4a"))
    cmd = calls[0]
    assert str(tmp_path / "a.m4a") in cmd and cmd.count("-i") == 2
    assert "0:v:0" in cmd and "1:a:0" in cmd
    assert "-an" not in cmd                              # profile's video-only -an is stripped for the mux


def test_deliver_silent_when_no_audio(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(deliver.proc, "run", lambda cmd, **k: (calls.append(cmd), _fake_cp())[1])
    deliver.deliver(str(tmp_path / "m.mp4"), REEL_H264, str(tmp_path / "out"), "v1", _ok_report())
    assert "-an" in calls[0] and "1:a:0" not in calls[0]
```

- [x] **Step 2: Run to verify it fails**

Run: `pytest tests/lib/test_deliver.py -k "muxes or silent" -q`
Expected: FAIL — `TypeError: deliver() got an unexpected keyword argument 'audio'`.

- [x] **Step 3: Implement the mux**

In `scripts/deliver.py`, change the signature and the encode call:

```python
def deliver(master: str, profile: ExportProfile, out_dir: str, changelog: str,
            report: ReelReport, audio: str | None = None) -> str:
    """Encode the checked master to the next REEL_v{n} and log the version. With
    `audio`, mux the pre-normalized aac stem alongside the encode (design §6).
    Hard gate: a failed reel is never shipped (no fix-forward, montage §176)."""
    if not report.overall:
        raise RuntimeError("reel failed check_reel — fix the flagged episodes and re-check; "
                           "deliver does not ship a failed reel (no fix-forward)")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    n = _next_version(out_dir, profile.container)
    out = str(Path(out_dir) / f"REEL_v{n}.{profile.container}")
    if audio is None:
        proc.run(["ffmpeg", "-y", "-i", master, *profile.args(), out])
    else:
        # the default profile is video-only (-an); drop it and map both streams,
        # stream-copying the already-aac stem so its −14 LUFS is preserved
        vargs = [x for x in profile.args() if x != "-an"]
        proc.run(["ffmpeg", "-y", "-i", master, "-i", audio, *vargs,
                  "-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy", "-shortest", out])
    _log_version(out_dir, n, changelog)
    return out
```

- [x] **Step 4: Run to verify it passes**

Run: `pytest tests/lib/test_deliver.py -q`
Expected: PASS (both new cases; existing deliver tests unaffected — `audio` defaults `None`).

- [x] **Step 5: Commit**

```bash
git add scripts/deliver.py tests/lib/test_deliver.py
git commit -m "$(printf 'feat: deliver muxes the audio stem (strip -an, map both streams)\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 6: `build_reel` — mix once, deliver with the stem

**Files:**
- Modify: `scripts/lib/models.py` (`ReelManifest.music`), `scripts/build_reel.py`
- Test: `tests/lib/test_models.py`, `tests/lib/test_build_reel.py`

- [x] **Step 1a: Write the failing test for `ReelManifest.music`**

Add to `tests/lib/test_models.py`:

```python
def test_reelmanifest_accepts_music_path_and_defaults_none():
    ep = dict(manifest={"a": 1}, clip="c.mp4", route="r.json")
    assert ReelManifest.from_dict(dict(episodes=[ep], target_dur=10.0)).music is None
    rm = ReelManifest.from_dict(dict(episodes=[ep], target_dur=10.0, music="MUSIC.json"))
    assert rm.music == "MUSIC.json"
    with pytest.raises(ValueError, match="music must be"):
        ReelManifest.from_dict(dict(episodes=[ep], target_dur=10.0, music=""))
```

- [x] **Step 1b: Implement `ReelManifest.music`**

In `scripts/lib/models.py` `ReelManifest`, add the field (after `changelog`):

```python
    music: str | None = None           # MUSIC.json path (design §6); None → a silent reel, as Phase A.5
```

append to its `__post_init__`:

```python
        if self.music is not None and not (isinstance(self.music, str) and self.music):
            raise ValueError("ReelManifest.music must be a MUSIC.json path or None, got an empty/non-str value")
```

and add to the `from_dict` `return cls(...)` kwargs:

```python
                   music=d.get("music"),
```

- [x] **Step 1c: Verify the manifest test**

Run: `pytest tests/lib/test_models.py -k reelmanifest_accepts_music -q`
Expected: PASS.

- [x] **Step 2: Write the failing driver tests**

Add to `tests/lib/test_build_reel.py` (imports needed: `from scripts import build_reel`; `from scripts.lib.models import CheckResult, ReelReport, ReelFailure, ReelEpisode, ReelManifest, MusicSpec`; `from scripts.lib.reel_orchestration import ReelAction`; `from scripts.lib.assembly import StreamInfo`):

```python
def _rm(music):
    ep = ReelEpisode(manifest={"a": 1}, clip="c0.mp4", route="r0.json")
    return ReelManifest(episodes=[ep, ReelEpisode(manifest={"a": 2}, clip="c1.mp4", route="r1.json")],
                        target_dur=6.0, variety_min=4, music=music)


def _fake_music():
    return MusicSpec("t.wav", 0.0, 6.0, 120.0, (0.0, 0.5, 1.0), (0.3,), 2.0)


def _si():
    return StreamInfo(1080, 1920, 30.0, "yuv420p", "h264")   # StreamInfo(w, h, fps, pix_fmt, vcodec)


def _passing():
    return ReelReport(checks={"black": CheckResult("black", True, {})})   # no fail_reasons → deliver


def _loud_fail():
    r = ReelReport(checks={"loudness": CheckResult("loudness", False, {"measured": -9.0})})
    r.fail_reasons = [ReelFailure("loudness", "audio-mix", None, {"measured": -9.0})]
    return r


def _wire(monkeypatch, reports, mixed, delivered):
    monkeypatch.setattr(build_reel.assembly, "probe_stream", lambda p: _si())
    monkeypatch.setattr(build_reel.assembly, "assemble", lambda *a, **k: None)
    monkeypatch.setattr(build_reel.check_reel, "_probe_dur", lambda p: 6.0)
    monkeypatch.setattr(build_reel.check_reel, "run", lambda *a, **k: reports.pop(0))
    monkeypatch.setattr(build_reel.mix, "mix", lambda m, wd, dur: (mixed.append((wd, dur)), "stem.m4a")[1])
    monkeypatch.setattr(build_reel.deliver, "deliver",
                        lambda *a, audio=None, **k: (delivered.append(audio), "OUT.mp4")[1])
    # NOTE: reel_orchestration.next_action is REAL — proves loudness rides the true escalate path


def test_build_reel_mixes_once_then_delivers_with_stem(tmp_path, monkeypatch):
    mixed, delivered = [], []
    _wire(monkeypatch, [_passing(), _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    res = build_reel.build_reel(_rm(music=str(tmp_path / "MUSIC.json")),
                                str(tmp_path / "out"), str(tmp_path / "work"))
    assert res["status"] == "delivered"
    assert len(mixed) == 1 and mixed[0][1] == 6.0        # stem built exactly once, at the reel duration
    assert delivered == ["stem.m4a"]                     # deliver received the stem


def test_build_reel_loudness_fail_stops_and_never_delivers(tmp_path, monkeypatch):
    mixed, delivered = [], []
    _wire(monkeypatch, [_passing(), _loud_fail()], mixed, delivered)   # round1 passes→mix; round2 loudness fails
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    res = build_reel.build_reel(_rm(music=str(tmp_path / "MUSIC.json")),
                                str(tmp_path / "out"), str(tmp_path / "work"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "not-auto-fixable" and res["finding"]["check"] == "loudness"
    assert delivered == []                               # deliver NEVER called on a loudness fail


def test_build_reel_silent_path_unchanged_without_music(tmp_path, monkeypatch):
    mixed, delivered = [], []
    _wire(monkeypatch, [_passing()], mixed, delivered)
    res = build_reel.build_reel(_rm(music=None), str(tmp_path / "out"), str(tmp_path / "work"))
    assert res["status"] == "delivered"
    assert mixed == [] and delivered == [None]           # no music → no mix, deliver stays silent (A.5)
```

- [x] **Step 3: Run to verify they fail**

Run: `pytest tests/lib/test_build_reel.py -k "mixes_once or loudness_fail or silent_path" -q`
Expected: FAIL — `AttributeError: module 'scripts.build_reel' has no attribute 'mix'` / `MusicSpec`.

- [x] **Step 4: Implement the driver integration**

In `scripts/build_reel.py`, extend the imports:

```python
from scripts import check_reel, deliver, mix, process_episode
from scripts.lib import assembly, reel_orchestration
from scripts.lib.color import corrected
from scripts.lib.models import ReelManifest, MusicSpec, REEL_H264
```

Replace the body of `build_reel` (from the `clips = ...` line through the loop) with:

```python
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    clips = [e.clip for e in rm.episodes]
    si = assembly.probe_stream(clips[0])          # actual delivered dims/fps (episodes uniform by construction)
    dims, fps = (si.w, si.h), si.fps
    master = str(Path(work_dir) / "master.mp4")
    report_path = str(Path(work_dir) / "reel_report.json")
    music = MusicSpec.from_json(rm.music) if rm.music else None   # None → silent reel, exactly as Phase A.5
    attempts: dict[int, int] = {}
    cc: dict[int, tuple[float, float, float]] = {}
    audio: str | None = None
    need_assemble = True
    for _ in range(rm.cap * len(rm.episodes) + 1):   # defensive bound; next_action is the real terminator
        if need_assemble:
            assembly.assemble(clips, dims, fps, master)
            need_assemble = False
        report = check_reel.run(master, clips, rm.check_spec, report_path, music=music, audio=audio)
        action = reel_orchestration.next_action(report.fail_reasons, attempts, rm.cap)
        if action.kind == "deliver":
            if music is not None and audio is None:  # picture passed → build the stem once, re-check with it
                audio = mix.mix(music, work_dir, check_reel._probe_dur(master))
                continue                             # need_assemble stays False — clips unchanged, no re-assemble
            out = deliver.deliver(master, REEL_H264, out_dir, rm.changelog, report, audio=audio)
            return {"status": "delivered", "output": out, "report": report.to_dict()}
        if action.kind == "escalate":
            return {"status": "stop_and_report", "finding": action.finding,
                    "report": report.to_dict(), "attempts": dict(attempts)}
        for item in action.reprocess:                # sequential — one process_episode saturates the box
            # black item (ratio None) adds no new correction but must NOT reset cc — the episode
            # keeps its standing colour factor, else a black fix reverts colour and flip-flops
            if item.color_correct is not None:
                cc[item.idx] = _compound(cc.get(item.idx, (1.0, 1.0, 1.0)), item.color_correct)
            epdir = str(Path(work_dir) / f"ep{item.idx}")
            res = process_episode.process_episode(
                rm.episodes[item.idx].manifest, epdir,
                route_path=rm.episodes[item.idx].route, color_correct=cc.get(item.idx))
            if res["status"] != "mechanical_pass":
                return {"status": "stop_and_report",
                        "finding": {"reason": "reprocess-failed", "episode_idx": item.idx,
                                    "sub_status": res["status"]},
                        "sub": res, "attempts": dict(attempts)}
            clips[item.idx] = res["clip"]
            attempts[item.idx] = attempts.get(item.idx, 0) + 1
            need_assemble = True
    return {"status": "stop_and_report",             # defensive: next_action escalates a capped reel first
            "finding": {"reason": "reel-cap-exhausted"}, "attempts": dict(attempts)}
```

- [x] **Step 5: Run to verify they pass**

Run: `pytest tests/lib/test_build_reel.py -q`
Expected: PASS (new music-path cases + existing A.5 cases — the silent path is byte-for-byte the same when `music=None`).

- [x] **Step 6: Commit**

```bash
git add scripts/lib/models.py scripts/build_reel.py tests/lib/test_models.py tests/lib/test_build_reel.py
git commit -m "$(printf 'feat: build_reel mixes once after picture-pass, delivers with the stem\n\nReelManifest.music threads MUSIC.json; the stem is built once (music is\nindependent of the picture), a final check_reel lights loudness/beat, deliver\nmuxes. need_assemble guard avoids a redundant re-assemble. music=None → the\nA.5 silent path, unchanged.\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 7: real-ffmpeg end-to-end — a reel that delivers WITH audio

**Files:**
- Modify: `tests/integration/test_music_spine.py`

- [x] **Step 1: Write the failing test**

Add to `tests/integration/test_music_spine.py` (reuses `_tone_music` from Task 4; `sample_clip` is the shared fixture in `tests/conftest.py`):

```python
def _reframe(src, tmp, x_const, name):
    """A clip via the real reframe encoder with a constant-x crop route. A distinct
    x_const frames sample_clip's moving box differently → distinct phash, so two
    clips at 645 vs 1045 clear the variety check (test_reel_retry.py's precedent)."""
    route = [dict(t=i / 10, x=float(x_const), y=540.0, w=140.0, h=320.0) for i in range(30)]
    rp = tmp / f"{name}.route.json"
    rp.write_text(json.dumps(route))
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=(105.0, 122.0, 137.0), delivery=Delivery("native"),
                       layout=LayoutSpec(mode="fill"))
    out = str(tmp / f"{name}.mp4")
    reframe.reframe(spec, str(src), str(rp), out, str(tmp / f"{name}.path.meta.json"))
    return out


@pytest.mark.integration
def test_build_reel_delivers_reel_with_audio_stream(tmp_path, sample_clip):
    ep0 = _reframe(sample_clip, tmp_path, 645, "ep0")
    ep1 = _reframe(sample_clip, tmp_path, 1045, "ep1")
    dur = sum(check_reel._probe_dur(e) for e in (ep0, ep1))
    ms = _tone_music(tmp_path, secs=max(2, int(round(dur)) + 1))   # track at least the reel length
    music_json = tmp_path / "MUSIC.json"
    music_json.write_text(json.dumps({**ms.to_dict(), "duration": dur,
                                      "beats": [b for b in ms.beats if b <= dur]}))
    rm = ReelManifest(
        episodes=[ReelEpisode(manifest={"_": 0}, clip=ep0, route=str(tmp_path / "r0.json")),
                  ReelEpisode(manifest={"_": 1}, clip=ep1, route=str(tmp_path / "r1.json"))],
        target_dur=dur, variety_min=4, color_delta_max=40.0, music=str(music_json))
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "work"))
    assert res["status"] == "delivered"
    r = proc.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                  "stream=codec_name", "-of", "default=nk=1:nw=1", res["output"]])
    assert r.stdout.decode().strip().startswith("aac")           # the delivered reel carries an aac stem
    assert res["report"]["checks"]["loudness"]["pass"] is True    # loudness gate green
    assert "worst_dev" in res["report"]["checks"]["beat"]         # beat measured (advisory)
```

- [x] **Step 2: Run to verify it fails**

Run: `pytest tests/integration/test_music_spine.py -k with_audio_stream -q`
Expected: FAIL first for the right reason if any wiring is off; once Tasks 0–6 are in, this is the integration proof. (If it errors on `duration`, the `music_json` override already pins `duration=dur` and clips beats to the reel span.)

- [x] **Step 3: (No new implementation)**

This task adds no production code — it is the end-to-end proof of Tasks 0–6. If it fails, fix the culprit task, do not special-case the test.

- [x] **Step 4: Run the whole suite**

Run: `pytest -q` (and `pytest -q -m integration` to confirm the real-ffmpeg/librosa goldens)
Expected: all green. Note the new total in the commit.

- [x] **Step 5: Commit**

```bash
git add tests/integration/test_music_spine.py
git commit -m "$(printf 'test: real-ffmpeg end-to-end — reel delivers with an aac stem + green loudness\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 8: docs sync + final whole-slice review

**Files:**
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`, `docs/specs/2026-07-05-montage-skillset-design.md`

- [x] **Step 1: `docs/build-status.md`** — add a "Music spine (Phase B · B1+B2) DONE (2026-07-11)" entry (beats-core → MUSIC.json; mix.py music-only stem; check_reel loudness hard / beat advisory; deliver mux; build_reel integration). Repoint the Next-action to **B3 (autonomous sourcing)** / **B4 (pacing)** with the deferred items listed (ambient/SFX, downbeats/sections/spectral/mood, safe_zones, music-less delivery). Update the test count to the new total from Task 7.

- [x] **Step 2: `docs/pipeline-map.md`** — status column: **5.5** `❌ → ◐` (lean beats-core built; mood-match/sourcing ❌), **5.12** `❌ → ◐` (music-only mix built; ambient ducking/SFX ❌), **5.13** — note `beat`/`loudness` now measured (loudness hard, beat advisory); `safe_zones` still ❌. Update "What produces a reel today" (a reel now delivers **with music**; loudness gated, beat reported). In the roadmap, change **Phase B — music spine** from `🔜` to `◐ B1+B2 done — beats-core + music-only mix + loudness/beat gates; remaining: B3 sourcing, B4 pacing (5.6), ambient/SFX`. Bump `_Last updated_`.

- [x] **Step 3: `CLAUDE.md`** — add two registry rows after the Reel-retry-loop rows:

```markdown
| Music spine design | [2026-07-11-music-spine-design.md](docs/specs/2026-07-11-music-spine-design.md) | Phase B · B1+B2: beats-core → lean MUSIC.json; music-only audio-mix; check_reel loudness (hard) + beat (advisory, non-blocking via `_ADVISORY_CHECKS`); deliver muxes the stem. |
| Music spine plan | [2026-07-11-music-spine.md](docs/plans/2026-07-11-music-spine.md) | Tasks 0–8: MusicSpec, beats.py, gate thresholds, check_reel gates, mix.py, deliver mux, build_reel integration, real goldens. |
```

- [x] **Step 4: `docs/specs/2026-07-05-montage-skillset-design.md`** — keep spec+plan in sync: add a "Built (2026-07-11, B1+B2)" note under §5.5 (lean subset: tempo/beats/energy; sourcing/mood deferred) and §5.12 (music-only; ambient/SFX deferred); update the §12/gate line that reads "beat/loudness/safe-zones report not-implemented" to "loudness hard, beat advisory (built 2026-07-11); safe-zones deferred".

- [x] **Step 5: Commit the docs**

```bash
git add docs/build-status.md docs/pipeline-map.md CLAUDE.md docs/specs/2026-07-05-montage-skillset-design.md
git commit -m "$(printf 'docs: sync build-status, pipeline-map, registry, design for the music spine (B1+B2)\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

- [x] **Step 6: Final whole-slice review** — dispatch one reviewer over the whole diff (`main..feat/music-spine`) against this plan + the design spec. Verify: the two subtle rules (loudness rides the real `next_action` escalate via `audio-mix`; beat measured-but-excluded-from-`overall`); `music=None` leaves the A.5 silent path byte-for-byte; landmines clean (no video `-ss` regressions, `colorchannelmixer` untouched, even dims); no failed-reel-delivers path (loudness fail → stop_and_report, `deliver` unreachable). Fold any findings back and re-run `pytest -q`.

---

## Self-Review (checklist run against the spec)

**1. Spec coverage:** §2 MusicSpec → T0; §3 beats.py → T1; §5 ReelCheckSpec/`_ADVISORY_CHECKS`/`overall` → T2; §5 loudness/beat in check_reel → T3; §4 mix.py → T4; §6 deliver mux → T5; §6 ReelManifest.music + driver → T6; §7 tests → T1/T4/T7 (+ unit tests in T0/T2/T3/T5/T6); §8 landmines + §9 non-goals honoured (music-only, safe_zones deferred, beat advisory) → T3/T4/T8. No gaps.

**2. Placeholders:** none — every code step carries full code; every run step names the command + expected result. T7 adds no production code by design (stated).

**3. Type consistency:** `MusicSpec(track, start_offset, duration, tempo, beats, energy, energy_hz)` identical across T0/T1/T4/T6/T7. `check_reel.run(..., music=None, audio=None)` matches its callers (T3 defines, T6 calls). `deliver(..., report, audio=None)` matches (T5 defines, T6 calls). `_loudness_check`/`_beat_check`/`_loudnorm_measure` signatures consistent T3↔callers. `ReelManifest.music` added T6, read T6/T7. `ReelAction("deliver"|"escalate"|"reprocess")` unchanged (no `next_action` edit). `StreamInfo(w, h, fps, …)` — the driver reads `.w/.h/.fps` (matches `assembly.probe_stream`).
