# Start-Offset Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-choose a reel's music in-point (`MusicSpec.start_offset`) — the strongest `duration`-length fragment whose start lands in a vocal pause, so the reel never opens mid-word.

**Architecture:** A pure decision core (`scripts/lib/offset.py`) picks the offset from numeric envelopes; a heavy-dependency boundary (`scripts/lib/vocals.py`) turns a track into a vocal-activity envelope via demucs (opt-in); a thin driver (`scripts/beats.py:choose_offset` + CLI `--auto-start`) orchestrates and falls back to a librosa mix-silence proxy when demucs is absent. `analyze()` is untouched — `choose_offset` produces the number it already accepts.

**Tech Stack:** Python 3.13, numpy, librosa (lazy), demucs+torch (opt-in, lazy), pytest.

**Spec:** [docs/specs/2026-07-13-start-offset-intelligence-design.md](../specs/2026-07-13-start-offset-intelligence-design.md).

**Repo conventions (read before starting):** [coding-standards.md](../coding-standards.md) (fail-loud with remedy, imports-at-top, every def typed, config-specs), [testing-guide.md](../testing-guide.md) (TDD, whole-object asserts, `@pytest.mark.integration`, skip-if-absent), [development-workflow.md](../development-workflow.md). Landmines (CLAUDE.md §12): relative not absolute thresholds; never a silent pass; scripts run as modules (`pythonpath = .`, `.venv/bin/python -m ...`).

**Branch:** all work on `feat/start-offset` (off `main`). Commit messages end with:
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

**⚠ Subagents:** do NOT run `brew`/`pip`/any installer, do NOT run `setup.sh`, do not mutate the machine. Verification is read-only + `pytest` + `bash -n`. demucs is NOT installed here by design — the demucs paths are covered by mocks (unit) and a skip-if-absent test (integration).

**Test runner:** `.venv/bin/python -m pytest <target> -v` from the repo root. Never pipe pytest through `tail`; append `; echo "EXIT: $?"` if you need the code past a pager.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `scripts/lib/offset.py` (NEW) | Pure: `HOP`, `downsample` (relocated from beats), `vocal_gaps`, `best_offset`. No IO/torch/librosa — the decision, unit-tested exhaustively. |
| `scripts/lib/vocals.py` (NEW) | `has_demucs`, `separate_vocal_energy`. The only demucs/torch importer (lazy). |
| `scripts/beats.py` (MODIFY) | Import `HOP`/`downsample` from offset (drop the local copies); add `_log`, `choose_offset`, CLI `--auto-start`. `analyze` unchanged. |
| `setup.sh` (MODIFY) | `--with-demucs` opt-in pip install into the venv (idempotent). |
| `SKILLS/using-montage/SKILL.md` (MODIFY) | Step 5: prefer `--auto-start` when a track is named without an explicit offset. |
| `tests/lib/test_offset.py` (NEW) | `downsample` (relocated tests) + `vocal_gaps` + `best_offset`. |
| `tests/lib/test_vocals.py` (NEW) | `has_demucs` both ways + raise-when-absent. |
| `tests/lib/test_beats.py` (MODIFY) | Drop the relocated downsample tests; add `choose_offset` + CLI tests. |
| `tests/integration/test_offset.py` (NEW) | no-demucs proxy path (always) + vocal path (skip-if-absent). |
| docs: `pipeline-map.md`, `build-status.md`, `CLAUDE.md`, `specs/2026-07-05-…-design.md` §5.5, `specs/2026-07-11-music-spine-design.md` §9 (MODIFY) | Sync status/registry. |

---

## Task 0: Relocate `downsample`+`HOP` to `offset.py`; refactor `beats.py`

Breaks the `beats ↔ vocals` circular import before it exists: both will share `offset.downsample`. Pure refactor — behaviour unchanged, suite stays green.

**Files:**
- Create: `scripts/lib/offset.py`
- Modify: `scripts/beats.py:12` (drop `_HOP`), `scripts/beats.py:15-21` (drop `_downsample`), `scripts/beats.py:4-10` (imports)
- Create: `tests/lib/test_offset.py`
- Modify: `tests/lib/test_beats.py` (remove the 3 downsample tests — they move to test_offset.py)

- [x] **Step 1: Create `scripts/lib/offset.py` with `HOP` + `downsample`**

```python
"""Pure decision core for start-offset intelligence (design
docs/specs/2026-07-13-start-offset-intelligence-design.md). Operates on numeric
envelopes only — no audio IO, no librosa, no demucs — so every branch of the
in-point decision is unit-tested deterministically. `downsample` (relocated from
beats.py) is the shared envelope-builder beats.py and vocals.py reuse without a
circular import."""
from collections.abc import Sequence

import numpy as np

HOP = 512                                             # librosa beat/rms default hop_length


def downsample(rms: np.ndarray, sr: int, hop: int, target_hz: float) -> tuple[list[float], float]:
    """Average per-frame RMS into ~target_hz bins → a short coarse energy curve.
    Returns (energy, energy_hz)."""
    frame_hz = sr / hop
    step = max(1, int(round(frame_hz / target_hz)))
    energy = [float(np.mean(rms[i:i + step])) for i in range(0, len(rms), step)]
    return energy, frame_hz / step
```

- [x] **Step 2: Point `beats.py` at the relocated helpers**

In `scripts/beats.py`, replace the module-level `_HOP` constant (line 12) and the entire `_downsample` function (lines 15-21) with an import. The header import block becomes:

```python
import argparse
import json
from pathlib import Path

import numpy as np

from scripts.lib import offset
from scripts.lib.models import MusicSpec

_HOP = offset.HOP                                     # kept as a module name for analyze() below
_downsample = offset.downsample                       # relocated to scripts/lib/offset.py
```

Leave `analyze()` and `main()` bodies unchanged — they reference `_HOP`/`_downsample`, which now alias the offset copies. (`import numpy as np` stays; `analyze` still uses it.)

- [x] **Step 3: Move the downsample tests into `tests/lib/test_offset.py`**

Create `tests/lib/test_offset.py` with the three relocated tests (now calling `offset.downsample` directly):

```python
import numpy as np

from scripts.lib import offset


def test_downsample_bins_and_energy_hz():
    rms = np.arange(10, dtype=float)                          # frame_hz=10 → target 2 → step 5 → 2 bins
    energy, hz = offset.downsample(rms, sr=1000, hop=100, target_hz=2.0)
    assert energy == [2.0, 7.0] and abs(hz - 2.0) < 1e-9


def test_downsample_short_array_single_bin():
    energy, hz = offset.downsample(np.array([1.0, 3.0]), sr=1000, hop=100, target_hz=2.0)  # step 5 > len → 1 bin
    assert energy == [2.0] and hz > 0


def test_downsample_empty_array_no_crash():
    energy, hz = offset.downsample(np.array([], dtype=float), sr=1000, hop=100, target_hz=2.0)
    assert energy == [] and hz > 0
```

Then delete those same three tests (and the now-unused `from scripts import beats` line if nothing else uses it) from `tests/lib/test_beats.py`. After this task `tests/lib/test_beats.py` may be reduced to just its imports — that is fine; Task 4 repopulates it.

- [x] **Step 4: Run the moved tests + the full beats suite**

Run: `.venv/bin/python -m pytest tests/lib/test_offset.py tests/lib/test_beats.py tests/integration/test_beats.py -v`
Expected: PASS (downsample behaviour unchanged; `analyze` still green via the aliases).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/offset.py scripts/beats.py tests/lib/test_offset.py tests/lib/test_beats.py
git commit -m "refactor: relocate downsample/HOP to lib/offset.py (share without a cycle)"
```

---

## Task 1: `offset.vocal_gaps`

**Files:**
- Modify: `scripts/lib/offset.py` (append)
- Modify: `tests/lib/test_offset.py` (append)

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_offset.py`:

```python
def test_vocal_gaps_finds_the_quiet_span():
    # hz=2 → each sample = 0.5s. Loud, loud, then 4 quiet samples (2.0s ≥ min_gap), loud.
    env = [1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0]
    assert offset.vocal_gaps(env, hz=2.0) == ((1.0, 3.0),)   # samples 2..5 → [1.0s, 3.0s)


def test_vocal_gaps_drops_a_sub_min_gap_dip():
    # at hz=10 one below-thresh sample = 0.1s < min_gap 0.35 → a between-words dip, dropped
    assert offset.vocal_gaps([1.0, 0.0, 1.0], hz=10.0) == ()


def test_vocal_gaps_all_loud_returns_empty():
    assert offset.vocal_gaps([1.0, 1.0, 1.0], hz=2.0) == ()


def test_vocal_gaps_all_zero_is_one_full_span():
    assert offset.vocal_gaps([0.0, 0.0, 0.0, 0.0], hz=2.0) == ((0.0, 2.0),)


def test_vocal_gaps_relative_threshold_scales():
    # a quiet master (peak 0.02) still yields the gap — relative bar, not absolute
    env = [0.02, 0.02, 0.0, 0.0, 0.0, 0.0, 0.02]
    assert offset.vocal_gaps(env, hz=2.0) == ((1.0, 3.0),)


def test_vocal_gaps_empty_envelope():
    assert offset.vocal_gaps([], hz=2.0) == ()
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_offset.py -k vocal_gaps -v`
Expected: FAIL with `AttributeError: module 'scripts.lib.offset' has no attribute 'vocal_gaps'`.

- [x] **Step 3: Implement `vocal_gaps`**

Append to `scripts/lib/offset.py`:

```python
def vocal_gaps(env: Sequence[float], hz: float, *,
               thresh_frac: float = 0.15, min_gap: float = 0.35) -> tuple[tuple[float, float], ...]:
    """Spans (start_s, end_s) where the activity envelope stays below
    thresh_frac * max(env) for at least min_gap seconds. Relative bar (design §12
    relative-gate lesson): a quiet mix must not read as all-silent. A below-thresh
    run shorter than min_gap is a between-words dip, dropped. env all-zero → one
    gap over the whole envelope (no vocals to avoid). Times are seconds (i / hz)."""
    n = len(env)
    if n == 0:
        return ()
    thresh = thresh_frac * max(env)
    gaps: list[tuple[float, float]] = []
    run_start: int | None = None
    for i, v in enumerate(env):
        below = v <= thresh
        if below and run_start is None:
            run_start = i
        elif not below and run_start is not None:
            if (i - run_start) / hz >= min_gap:
                gaps.append((run_start / hz, i / hz))
            run_start = None
    if run_start is not None and (n - run_start) / hz >= min_gap:
        gaps.append((run_start / hz, n / hz))
    return tuple(gaps)
```

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_offset.py -k vocal_gaps -v`
Expected: PASS (6 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/offset.py tests/lib/test_offset.py
git commit -m "feat: offset.vocal_gaps — relative-threshold vocal-pause spans"
```

---

## Task 2: `offset.best_offset`

**Files:**
- Modify: `scripts/lib/offset.py` (append)
- Modify: `tests/lib/test_offset.py` (append)

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_offset.py`:

```python
def test_best_offset_track_shorter_than_reel():
    assert offset.best_offset([1.0, 2.0], mix_hz=2.0, gaps=(), duration=5.0, track_dur=1.0) == 0.0


def test_best_offset_picks_gap_start_over_raw_peak():
    # mix_hz=2 → 8 samples = 4s. Peak energy in samples 2..5 (t=1.0..3.0). duration=2s
    # (4 samples), latest = 4-2 = 2.0s. A gap starts at t=1.0 → window [1.0,3.0] = the peak.
    mix = [1.0, 1.0, 5.0, 5.0, 5.0, 5.0, 1.0, 1.0]
    assert offset.best_offset(mix, mix_hz=2.0, gaps=((1.0, 1.5),),
                              duration=2.0, track_dur=4.0) == 1.0


def test_best_offset_drops_a_gap_that_starts_too_late():
    # gap starts at 3.0s but latest usable start is 2.0s → dropped → argmax fallback picks 1.0s
    mix = [1.0, 1.0, 5.0, 5.0, 5.0, 5.0, 1.0, 1.0]
    assert offset.best_offset(mix, mix_hz=2.0, gaps=((3.0, 3.5),),
                              duration=2.0, track_dur=4.0) == 1.0


def test_best_offset_no_gaps_falls_back_to_argmax():
    mix = [1.0, 1.0, 5.0, 5.0, 5.0, 5.0, 1.0, 1.0]
    assert offset.best_offset(mix, mix_hz=2.0, gaps=(),
                              duration=2.0, track_dur=4.0) == 1.0


def test_best_offset_chooses_the_louder_of_two_gap_windows():
    # two gaps: one leads into quiet, one leads into the loud region → pick the loud one
    mix = [1.0, 1.0, 1.0, 1.0, 5.0, 5.0, 5.0, 5.0]          # loud in the second half
    # gaps at t=0.0 (window [0,2] quiet) and t=1.5 (window [1.5,3.5] catches the loud tail)
    assert offset.best_offset(mix, mix_hz=2.0, gaps=((0.0, 0.5), (1.5, 2.0)),
                              duration=2.0, track_dur=4.0) == 1.5
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_offset.py -k best_offset -v`
Expected: FAIL with `AttributeError: module 'scripts.lib.offset' has no attribute 'best_offset'`.

- [x] **Step 3: Implement `best_offset`**

Append to `scripts/lib/offset.py`:

```python
def best_offset(mix_energy: Sequence[float], mix_hz: float,
                gaps: Sequence[tuple[float, float]],
                duration: float, track_dur: float) -> float:
    """start_offset (track seconds) of the max-mean-energy duration-window whose
    start lies in a vocal gap (design §2). track_dur <= duration → 0.0. Candidate
    starts = gap starts with start <= track_dur - duration (the window must fit the
    track); a gap starting later is dropped. No usable gap → argmax over a coarse
    per-sample slide (honest degrade — may begin mid-phrase; the driver logs it).
    Ties resolve to the earliest start (max() keeps the first maximum)."""
    if track_dur <= duration:
        return 0.0
    latest = track_dur - duration

    def win_mean(start: float) -> float:
        a = int(round(start * mix_hz))
        b = int(round((start + duration) * mix_hz))
        seg = mix_energy[a:b]
        return float(np.mean(seg)) if len(seg) else 0.0

    candidates = [g0 for (g0, _g1) in gaps if g0 <= latest + 1e-9]
    if candidates:
        return float(max(candidates, key=win_mean))
    starts = [i / mix_hz for i in range(int(round(latest * mix_hz)) + 1)]
    return float(max(starts, key=win_mean)) if starts else 0.0
```

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_offset.py -v`
Expected: PASS (all offset tests: downsample + vocal_gaps + best_offset).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/offset.py tests/lib/test_offset.py
git commit -m "feat: offset.best_offset — loudest gap-start window, argmax fallback"
```

---

## Task 3: `vocals.py` — demucs boundary

**Files:**
- Create: `scripts/lib/vocals.py`
- Create: `tests/lib/test_vocals.py`

- [x] **Step 1: Write the failing tests**

Create `tests/lib/test_vocals.py`:

```python
import importlib.util

import pytest

from scripts.lib import vocals


def test_has_demucs_true(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    assert vocals.has_demucs() is True


def test_has_demucs_false(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert vocals.has_demucs() is False


def test_separate_vocal_energy_raises_a_remedy_when_absent(monkeypatch):
    monkeypatch.setattr(vocals, "has_demucs", lambda: False)
    with pytest.raises(ValueError, match="--with-demucs"):
        vocals.separate_vocal_energy("track.wav")
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_vocals.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.lib.vocals'`.

- [x] **Step 3: Implement `vocals.py`**

Create `scripts/lib/vocals.py`:

```python
"""Vocal-separation boundary for start-offset intelligence (design §3). The only
module that imports demucs/torch (lazily). Turns a track into a coarse
vocal-activity envelope; the decision (offset.py) stays audio-agnostic."""
import importlib.util

import numpy as np

from scripts.lib import offset


def has_demucs() -> bool:
    """True if demucs is importable — the gate the driver checks before the heavy
    path (a spec probe; no torch load)."""
    return importlib.util.find_spec("demucs") is not None


def separate_vocal_energy(track: str, target_hz: float = 2.0) -> tuple[list[float], float]:
    """Whole-track demucs → vocal stem → mono RMS → downsample to ~target_hz.
    Returns (env, hz). Lazy demucs+torch import (heavy, opt-in). Raises ValueError
    naming setup.sh --with-demucs when demucs is absent (callers gate on
    has_demucs() first — defense-in-depth). demucs≥4 API; the real separation is
    exercised only by the skip-if-absent integration test."""
    if not has_demucs():
        raise ValueError("separate_vocal_energy needs demucs — install it with "
                         "`bash setup.sh --with-demucs` (opt-in; pulls torch)")
    import librosa
    import torch
    from demucs.apply import apply_model
    from demucs.audio import AudioFile
    from demucs.pretrained import get_model

    model = get_model("htdemucs")
    model.eval()
    wav = AudioFile(track).read(streams=0, samplerate=model.samplerate,
                                channels=model.audio_channels)
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / (ref.std() + 1e-8)
    with torch.no_grad():
        est = apply_model(model, wav[None], overlap=0.25, progress=False)[0]
    vocal = est[model.sources.index("vocals")]        # (channels, samples)
    mono = vocal.mean(0).cpu().numpy().astype(np.float32)
    rms = librosa.feature.rms(y=mono, hop_length=offset.HOP)[0]
    return offset.downsample(rms, model.samplerate, offset.HOP, target_hz)
```

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_vocals.py -v`
Expected: PASS (3 tests). (The demucs body is not imported unless `has_demucs()` is true, so the suite runs without demucs installed.)

- [x] **Step 5: Commit**

```bash
git add scripts/lib/vocals.py tests/lib/test_vocals.py
git commit -m "feat: vocals.py — opt-in demucs vocal-activity envelope"
```

---

## Task 4: `beats.choose_offset` driver

**Files:**
- Modify: `scripts/beats.py` (add `import sys`, `from scripts.lib import vocals`, `_log`, `choose_offset`)
- Modify: `tests/lib/test_beats.py` (add choose_offset tests)

- [x] **Step 1: Write the failing tests**

Add to `tests/lib/test_beats.py` (keep/restore `import numpy as np` and add the rest):

```python
import numpy as np

from scripts import beats
from scripts.lib import offset, vocals


def _fake_librosa(monkeypatch, track_seconds, sr=2000):
    """Make beats' lazy `import librosa` return a stub whose load() yields a signal
    of the requested length and whose feature.rms() returns a dummy frame array.
    offset.downsample is separately monkeypatched, so the rms values don't matter."""
    import librosa
    monkeypatch.setattr(librosa, "load",
                        lambda *a, **k: (np.zeros(int(track_seconds * sr), dtype=np.float32), sr))
    monkeypatch.setattr(librosa.feature, "rms", lambda *a, **k: np.array([[0.0]]))


def test_choose_offset_track_shorter_than_reel_returns_zero(monkeypatch, capsys):
    _fake_librosa(monkeypatch, track_seconds=2.0)
    assert beats.choose_offset("t.wav", duration=5.0) == 0.0
    assert "whole track" in capsys.readouterr().err


def test_choose_offset_vocal_path_when_demucs_present(monkeypatch, capsys):
    _fake_librosa(monkeypatch, track_seconds=4.0)
    # fixed mix envelope: loud in the second half (mix_hz=2 → 8 samples = 4s)
    monkeypatch.setattr(offset, "downsample",
                        lambda *a, **k: ([1.0, 1.0, 1.0, 1.0, 5.0, 5.0, 5.0, 5.0], 2.0))
    monkeypatch.setattr(vocals, "has_demucs", lambda: True)
    # vocal env silent at t=1.5s (sample 3) → a gap leading into the loud region
    monkeypatch.setattr(vocals, "separate_vocal_energy",
                        lambda *a, **k: ([9.0, 9.0, 9.0, 0.0, 0.0, 9.0, 9.0, 9.0], 2.0))
    off = beats.choose_offset("t.wav", duration=2.0, use_vocals=True)
    assert off == 1.5                                        # best_offset over the injected arrays
    assert "via vocal" in capsys.readouterr().err


def test_choose_offset_falls_back_to_mix_proxy_without_demucs(monkeypatch, capsys):
    _fake_librosa(monkeypatch, track_seconds=4.0)
    monkeypatch.setattr(offset, "downsample",
                        lambda *a, **k: ([1.0, 1.0, 5.0, 5.0, 5.0, 5.0, 1.0, 1.0], 2.0))
    monkeypatch.setattr(vocals, "has_demucs", lambda: False)
    called = {"vocal": False}
    monkeypatch.setattr(vocals, "separate_vocal_energy",
                        lambda *a, **k: called.__setitem__("vocal", True) or ([], 2.0))
    off = beats.choose_offset("t.wav", duration=2.0)
    assert called["vocal"] is False                         # vocal path not taken
    assert "mix-proxy" in capsys.readouterr().err
    assert 0.0 <= off <= 2.0
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_beats.py -k choose_offset -v`
Expected: FAIL with `AttributeError: module 'scripts.beats' has no attribute 'choose_offset'`.

- [x] **Step 3: Implement `_log` + `choose_offset`**

In `scripts/beats.py`: add `import sys` to the stdlib imports, add `from scripts.lib import vocals` beside the offset/models imports, then add (above `main`):

```python
def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def choose_offset(track: str, duration: float, *, use_vocals: bool = True) -> float:
    """Auto-pick MusicSpec.start_offset (design §4): the strongest duration-window
    whose start lands in a vocal pause. demucs vocal path when available+use_vocals,
    else a logged full-mix silence proxy. Emits one stderr info line."""
    import librosa                                    # lazy import: heavy optional dep (librosa)
    y, sr = librosa.load(track, sr=None, mono=True)
    track_dur = len(y) / sr
    if track_dur <= duration:
        _log(f"choose_offset: 0.00s (track {track_dur:.1f}s <= reel {duration:.1f}s — whole track)")
        return 0.0
    mix_rms = librosa.feature.rms(y=y, hop_length=offset.HOP)[0]
    mix_energy, mix_hz = offset.downsample(mix_rms, sr, offset.HOP, 2.0)
    if use_vocals and vocals.has_demucs():
        env, hz = vocals.separate_vocal_energy(track)
        gaps, path = offset.vocal_gaps(env, hz), "vocal"
    else:
        gaps, path = offset.vocal_gaps(mix_energy, mix_hz), "mix-proxy"
    off = offset.best_offset(mix_energy, mix_hz, gaps, duration, track_dur)
    extra = "" if path == "vocal" else " (demucs absent — setup.sh --with-demucs for vocal-accurate)"
    _log(f"choose_offset: {off:.2f}s via {path}{extra}")
    return off
```

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_beats.py -v`
Expected: PASS (choose_offset tests + any remaining beats tests).

- [x] **Step 5: Commit**

```bash
git add scripts/beats.py tests/lib/test_beats.py
git commit -m "feat: beats.choose_offset — vocal-pause in-point picker with mix fallback"
```

---

## Task 5: CLI `--auto-start`

**Files:**
- Modify: `scripts/beats.py:main`
- Modify: `tests/lib/test_beats.py` (add CLI tests)

- [x] **Step 1: Write the failing tests**

Add to `tests/lib/test_beats.py`:

```python
import pytest


def test_cli_auto_start_requires_duration(monkeypatch):
    monkeypatch.setattr("sys.argv", ["beats", "t.wav", "--auto-start", "--out", "M.json"])
    with pytest.raises(SystemExit):                          # argparse error() → SystemExit(2)
        beats.main()


def test_cli_auto_start_computes_offset(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(beats, "choose_offset", lambda track, dur: seen.setdefault("off", 7.5) or 7.5)

    def fake_analyze(track, start, duration):
        seen["start"] = start
        return MusicSpec(track=track, start_offset=start, duration=10.0, tempo=120.0,
                         beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0)

    monkeypatch.setattr(beats, "analyze", fake_analyze)
    out = tmp_path / "M.json"
    monkeypatch.setattr("sys.argv", ["beats", "t.wav", "--auto-start", "--duration", "10",
                                     "--out", str(out)])
    beats.main()
    assert seen["off"] == 7.5 and seen["start"] == 7.5 and out.exists()
```

(Ensure `from scripts.lib.models import MusicSpec` is imported at the top of the test file.)

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_beats.py -k auto_start -v`
Expected: FAIL — `--auto-start` is not a recognised argument (SystemExit for the wrong reason / the compute test errors).

- [x] **Step 3: Implement the CLI change**

Replace `main()` in `scripts/beats.py` with:

```python
def main() -> None:
    ap = argparse.ArgumentParser(description="analyse a track → MUSIC.json (tempo + beats + energy)")
    ap.add_argument("track")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--start-offset", type=float, default=0.0)
    g.add_argument("--auto-start", action="store_true",
                   help="auto-pick the in-point (strongest fragment, vocal-pause start); needs --duration")
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--out", required=True, help="MUSIC.json output path")
    a = ap.parse_args()
    if a.auto_start:
        if a.duration is None:
            ap.error("--auto-start needs --duration (the reel length) to size the window")
        start = choose_offset(a.track, a.duration)
    else:
        start = a.start_offset
    ms = analyze(a.track, start, a.duration)
    Path(a.out).write_text(json.dumps(ms.to_dict(), indent=2))
    print(a.out)
```

- [x] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_beats.py -v`
Expected: PASS (all beats tests).

- [x] **Step 5: Commit**

```bash
git add scripts/beats.py tests/lib/test_beats.py
git commit -m "feat: beats CLI --auto-start (mutually exclusive with --start-offset)"
```

---

## Task 6: Integration test — real paths

**Files:**
- Create: `tests/integration/test_offset.py`

- [x] **Step 1: Write the test**

Create `tests/integration/test_offset.py`:

```python
"""Real integration for start-offset intelligence (design §7). The no-demucs proxy
path runs on any machine; the demucs vocal path skips when demucs is absent
(mirrors the vidstab-gated goldens). Synthetic audio can't semantically exercise a
vocal-trained net, so the vocal test is a wiring smoke-test — semantic correctness
is carried by the pure offset unit tests."""
import importlib.util

import numpy as np
import pytest
from scipy.io import wavfile

from scripts import beats
from scripts.lib import vocals


def _has_demucs() -> bool:
    return importlib.util.find_spec("demucs") is not None


def _tone_wav(path, sr=22050, secs=12):
    """12s: a quiet 110 Hz bed throughout, a loud 300 Hz 'vocal' tone only in [4,8)s."""
    t = np.arange(int(secs * sr)) / sr
    bed = 0.05 * np.sin(2 * np.pi * 110 * t)
    vocal = 0.6 * np.sin(2 * np.pi * 300 * t) * ((t >= 4) & (t < 8))
    wavfile.write(path, sr, (bed + vocal).astype(np.float32))
    return str(path)


@pytest.mark.integration
def test_choose_offset_mix_proxy_runs_without_demucs(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vocals, "has_demucs", lambda: False)     # force the proxy path
    wav = _tone_wav(tmp_path / "t.wav")
    off = beats.choose_offset(wav, duration=4.0)
    assert 0.0 <= off <= 12.0 - 4.0                             # a valid in-window offset
    assert "mix-proxy" in capsys.readouterr().err              # took the fallback, logged it


@pytest.mark.integration
@pytest.mark.skipif(not _has_demucs(), reason="needs demucs (bash setup.sh --with-demucs)")
def test_choose_offset_vocal_path_wiring(tmp_path):
    # smoke: the whole demucs→envelope→decision path runs on real bytes and returns
    # a valid offset (slow — real separation). Semantic correctness is unit-tested.
    wav = _tone_wav(tmp_path / "t.wav")
    off = beats.choose_offset(wav, duration=4.0, use_vocals=True)
    assert 0.0 <= off <= 12.0 - 4.0
```

- [x] **Step 2: Run the always-on test**

Run: `.venv/bin/python -m pytest tests/integration/test_offset.py -v`
Expected: `test_choose_offset_mix_proxy_runs_without_demucs` PASS; `test_choose_offset_vocal_path_wiring` SKIPPED (demucs absent here).

- [x] **Step 3: Commit**

```bash
git add tests/integration/test_offset.py
git commit -m "test: real proxy path + skip-if-absent demucs vocal path for choose_offset"
```

---

## Task 7: `setup.sh --with-demucs`

**Files:**
- Modify: `setup.sh:15` (arg-scan) and `setup.sh:124` area (post-venv pip block)

- [x] **Step 1: Add the arg-scan flag**

In the arg-scan loop (currently `WANT_VIDSTAB=0; WANT_FONTS=0` on line 15 and the `case` below), add `WANT_DEMUCS`:

```bash
# scan all args so --with-vidstab, --with-fonts and --with-demucs compose (order-independent)
WANT_VIDSTAB=0; WANT_FONTS=0; WANT_DEMUCS=0
for arg in "$@"; do
  case "$arg" in
    --with-vidstab) WANT_VIDSTAB=1 ;;
    --with-fonts)   WANT_FONTS=1 ;;
    --with-demucs)  WANT_DEMUCS=1 ;;
  esac
done
```

- [x] **Step 2: Add the opt-in install after the venv deps**

In the `--- venv + python deps ---` block, after `"$VENV/bin/pip" install -r "$SKILL_DIR/requirements.txt"` and before the `models/` mkdir, add:

```bash
# demucs: vocal separation for start-offset intelligence (§5.5). Opt-in — pulls
# torch (large). Absent → choose_offset falls back to a librosa mix-silence proxy,
# so this is accuracy, not a hard requirement. Guarded on already-installed so a
# rerun is a clean no-op (kept out of requirements.txt to keep the base install lean).
if [ "$WANT_DEMUCS" = 1 ]; then
  "$VENV/bin/pip" show demucs >/dev/null 2>&1 || {
    echo "installing demucs (vocal separation; pulls torch) into the venv..."
    "$VENV/bin/pip" install demucs; }
fi
```

- [x] **Step 3: Verify shell syntax (do NOT run the installer)**

Run: `bash -n setup.sh; echo "EXIT: $?"`
Expected: `EXIT: 0` (parses clean). Do not execute `setup.sh` — the user runs it.

- [x] **Step 4: Commit**

```bash
git add setup.sh
git commit -m "feat: setup.sh --with-demucs (opt-in vocal separation, torch)"
```

---

## Task 8: `using-montage` wiring + docs sync

**Files:**
- Modify: `SKILLS/using-montage/SKILL.md` (step 5)
- Modify: `docs/pipeline-map.md`, `docs/build-status.md`, `CLAUDE.md`, `docs/specs/2026-07-05-montage-skillset-design.md` (§5.5), `docs/specs/2026-07-11-music-spine-design.md` (§9)

- [x] **Step 1: Wire `--auto-start` into the router SKILL**

In `SKILLS/using-montage/SKILL.md` step 5 (the music-and-mood step, ~lines 64-67), replace the command guidance so `--auto-start` is the default when a track is named without an explicit in-point:

```markdown
5. **music-and-mood (optional).** If the brief names a track or asks for music,
   analyse it. Prefer letting the tool pick the in-point:
   `.venv/bin/python -m scripts.beats <track> --auto-start --duration <reel_len>
   --out <run>/MUSIC.json` — it starts the reel on the strongest fragment, in a
   vocal pause (accurate with `bash setup.sh --with-demucs`; a librosa mix-silence
   proxy otherwise). Pass an explicit `--start-offset S` instead only to override.
   Then pass `<run>/MUSIC.json` to edit-plan. On "no music" / "без музыки", leave
   it unset — the reel is silent (a valid path).
```

- [x] **Step 2: Update `docs/pipeline-map.md`**

In the 5.5 row of "The 16 stages" table, keep the ◐ (B3/B4 still open) but note the in-point picker. Change the 5.5 "Module / note" cell to:

```
beats-core (tempo/beat-grid/RMS energy) ✅ + start_offset intelligence (auto in-point: peak-energy window, vocal-pause start via opt-in demucs / librosa proxy) ✅; mood-match + autonomous sourcing ❌
```

And in the "Remaining work" table 5.5 row, change "Left to build" to `mood-match + sourcing (B3)` (start-offset now done) — leave the rest of the row unchanged.

- [x] **Step 3: Add a `docs/build-status.md` entry**

Under "## Done", add a bullet (newest-style, matching the existing entries):

```markdown
- **start-offset intelligence (§5.5 sub-slice) DONE (2026-07-13)** — plan
  `docs/plans/2026-07-13-start-offset-intelligence.md` + design
  `docs/specs/2026-07-13-start-offset-intelligence-design.md`. `scripts/lib/offset.py`
  (`downsample` relocated from beats to break a beats↔vocals cycle; `vocal_gaps`
  relative-threshold pause spans; `best_offset` loudest gap-start window, argmax
  fallback) + `scripts/lib/vocals.py` (`has_demucs`/`separate_vocal_energy`, the
  lone lazy demucs importer) + `scripts/beats.py` `choose_offset` driver and CLI
  `--auto-start` (mutually exclusive with `--start-offset`, needs `--duration`).
  demucs is opt-in (`setup.sh --with-demucs`, pulls torch); absent → a logged
  librosa mix-silence proxy, never a crash. Pure decision exhaustively unit-tested;
  the demucs path is mocked (unit) + skip-if-absent (integration
  `test_offset.py`, real proxy path always runs). `analyze()` untouched.
  **Deferred:** beat-snap of the start, section detection (B4 pacing), mood-match/
  sourcing (B3).
```

Also update the "## Next action" list's music item to note start-offset is done and B3 sourcing / B4 pacing remain.

- [x] **Step 4: Add `CLAUDE.md` registry rows**

In the Quick Reference table, add two rows (design + plan), matching the existing format:

```markdown
| Start-offset intelligence design | [2026-07-13-start-offset-intelligence-design.md](docs/specs/2026-07-13-start-offset-intelligence-design.md) | §5.5 sub-slice: auto-pick the music in-point — peak-energy `duration`-window whose start sits in a vocal pause; pure `offset.py` decision + opt-in demucs `vocals.py` (librosa mix-proxy fallback); `beats --auto-start`. |
| Start-offset intelligence plan | [2026-07-13-start-offset-intelligence.md](docs/plans/2026-07-13-start-offset-intelligence.md) | Tasks 0–8: relocate downsample→offset, `vocal_gaps`/`best_offset`, `vocals.py` demucs boundary, `choose_offset`+`--auto-start`, integration proxy/skip, `setup.sh --with-demucs`, router+docs. |
```

- [x] **Step 5: Mark the design-spec §5.5 items built**

In `docs/specs/2026-07-05-montage-skillset-design.md`, immediately after the `### 5.5 music-and-mood → MUSIC.json` description paragraph (the one beginning "`beats.py`: **librosa**…"), insert this blockquote note verbatim (matching the existing `>`-blockquote status notes in the file):

```markdown
> **Built (2026-07-13, start-offset intelligence):** `start_offset` (the "chosen
> track fragment") and the `vocal-map` phrase-boundary start-snap now ship — a
> peak-energy `duration`-window whose start lands in a vocal pause (opt-in demucs
> vocal stem, librosa mix-silence proxy fallback), via `beats --auto-start`.
> Mood-match and autonomous sourcing (B3) remain deferred. See
> `docs/specs/2026-07-13-start-offset-intelligence-design.md`.
```

Do not restructure the section.

- [x] **Step 6: Cross-ref in the music-spine spec**

In `docs/specs/2026-07-11-music-spine-design.md` §9 (Non-goals / deferred), append this bullet verbatim to the list:

```markdown
- **Start-offset intelligence** — the "chosen fragment" `start_offset` + vocal-pause
  start-snap landed separately on 2026-07-13 (its own spec/plan:
  `docs/specs/2026-07-13-start-offset-intelligence-design.md`); B3 sourcing and B4
  pacing remain deferred as above.
```

- [x] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"`
Expected: green (all prior tests + the new offset/vocals/beats units + the always-on integration proxy test; the demucs vocal integration test SKIPPED).

- [x] **Step 8: Commit**

```bash
git add SKILLS/using-montage/SKILL.md docs/pipeline-map.md docs/build-status.md CLAUDE.md \
        docs/specs/2026-07-05-montage-skillset-design.md docs/specs/2026-07-11-music-spine-design.md
git commit -m "docs: sync registry/pipeline-map/build-status + using-montage --auto-start (start-offset intelligence)"
```

---

## Final review

After all tasks, dispatch a whole-slice review (spec ↔ code ↔ tests): confirm the beats↔vocals cycle is broken (offset owns `downsample`), the decision core is exhaustively unit-tested, demucs never loads on the stock path, every degrade is logged (never a silent pass), and `analyze()`/`mix.py` are untouched. Then invoke superpowers:finishing-a-development-branch.
