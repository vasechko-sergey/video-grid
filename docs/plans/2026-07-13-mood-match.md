# Mood-Match Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Rank a local folder of candidate tracks by fit to `SPEC.mood` → a `MUSIC_SHORTLIST` the agent picks from, closing the montage §5.5 "mood matches SPEC" gate for the `local` music lane.

**Architecture:** Mirrors the start-offset slice — a pure numeric core (`scripts/lib/mood.py`, the `offset.py` analog: `MoodVector` + `MOOD_ANCHORS` lexicon + `mood_target`/`distance`/`rank`/`rank_by_drive`, stdlib only), a librosa extractor that maps a file into that space (`beats.mood_features`, where librosa already lives), and a thin driver (`scripts/mood.py`) that scans a folder → ranks → writes `MUSIC_SHORTLIST.{json,md}`. A `music-match` SKILL runs the driver, presents the shortlist, and hands the pick to the existing `beats --auto-start`.

**Tech Stack:** Python 3, numpy, librosa (lazy import, already a dep), scipy.io.wavfile (test fixtures, already used), pytest (`pythonpath = .`, marker `integration`).

**Spec:** `docs/specs/2026-07-13-mood-match-design.md`.

---

## Shared conventions (read once)

- **Branch off `main` first** (`git checkout -b feat/mood-match`); never commit to `main`, never push (the user pushes `main` himself).
- **Scripts run as modules:** `.venv/bin/python -m scripts.mood ...`; tests import `from scripts.lib import mood`, `from scripts import mood as driver`.
- **Run tests without piping through `tail`** (it hides the exit code). Use `; echo "EXIT: $?"` or zsh `$pipestatus[1]`.
- **Fail loud with a remedy** (`ValueError` naming the bad value + the fix); imports at top; every `def` typed; a config-spec validates in `__post_init__`.
- **Commit** per task; end each commit body with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Message convention: `<type>: <summary> (5.5)`.
- **No machine mutation.** This slice installs nothing — librosa and scipy are already deps; demucs is **not** used here. A shell-capable subagent must not run any installer or `setup.sh`; verification is read-only + pytest.
- Two modules are named `mood`: the pure core `scripts/lib/mood.py` (imported `from scripts.lib import mood`) and the driver `scripts/mood.py` (imported `from scripts import mood`). Keep the import aliases straight.

---

## Task 0: `mood.py` core — MoodVector, norm01, refs, lexicon

**Files:**
- Create: `scripts/lib/mood.py`
- Test: `tests/lib/test_mood.py`

- [x] **Step 1: Write the failing test**

```python
# tests/lib/test_mood.py
import pytest

from scripts.lib.mood import (MoodVector, MOOD_ANCHORS, norm01,
                              PACE_BPM, BRIGHT_HZ, ENERGY_RMS)


def test_moodvector_roundtrip():
    v = MoodVector(0.9, 0.7, 0.85)
    assert v.as_tuple() == (0.9, 0.7, 0.85)
    assert MoodVector.from_dict(v.to_dict()) == v


def test_moodvector_rejects_out_of_range():
    with pytest.raises(ValueError, match=r"energy.*\[0, 1\]"):
        MoodVector(1.5, 0.5, 0.5)


def test_moodvector_rejects_bool():
    with pytest.raises(ValueError):
        MoodVector(True, 0.5, 0.5)


def test_moodvector_rejects_non_number():
    with pytest.raises(ValueError):
        MoodVector("hi", 0.5, 0.5)


def test_norm01_endpoints_midpoint_and_clamp():
    assert norm01(60, 60, 180) == 0.0
    assert norm01(180, 60, 180) == 1.0
    assert norm01(120, 60, 180) == 0.5
    assert norm01(30, 60, 180) == 0.0        # below lo clamps
    assert norm01(240, 60, 180) == 1.0       # above hi clamps


def test_norm01_requires_hi_gt_lo():
    with pytest.raises(ValueError):
        norm01(1, 5, 5)


def test_refs_are_ordered_pairs():
    for lo, hi in (PACE_BPM, BRIGHT_HZ, ENERGY_RMS):
        assert hi > lo


def test_anchors_all_valid_and_lowercase():
    assert MOOD_ANCHORS
    for name, v in MOOD_ANCHORS.items():
        assert name == name.lower() and name.isalpha()
        assert isinstance(v, MoodVector)     # __post_init__ already validated its ranges


def test_anchor_families_present():
    for w in ("energetic", "chill", "epic", "dark", "happy",
              "melancholic", "dreamy", "tense"):
        assert w in MOOD_ANCHORS
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_mood.py -q ; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.mood'`.

- [x] **Step 3: Write minimal implementation**

```python
# scripts/lib/mood.py
"""Pure decision core for mood-match (design docs/specs/2026-07-13-mood-match-design.md).
The MoodVector space + the anchor lexicon + scoring — stdlib only, no audio IO,
no librosa — so every branch is unit-tested deterministically (the offset.py discipline).
beats.mood_features maps an audio file into this space; scripts/mood.py ranks a folder."""
from dataclasses import dataclass

PACE_BPM = (60.0, 180.0)         # tempo → pace axis
BRIGHT_HZ = (500.0, 5000.0)      # spectral centroid → brightness axis
ENERGY_RMS = (0.0, 0.35)         # peak-normalized RMS mean → energy axis


@dataclass
class MoodVector:
    energy: float                # [0,1] soft ↔ driving (loudness-robust)
    brightness: float            # [0,1] dark/warm ↔ airy/bright
    pace: float                  # [0,1] slow ↔ fast

    def __post_init__(self) -> None:
        for name in ("energy", "brightness", "pace"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 <= v <= 1.0:
                raise ValueError(f"MoodVector.{name} must be a number in [0, 1], got {v!r}")
            setattr(self, name, float(v))

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.energy, self.brightness, self.pace)

    def to_dict(self) -> dict:
        return {"energy": self.energy, "brightness": self.brightness, "pace": self.pace}

    @classmethod
    def from_dict(cls, d: dict) -> "MoodVector":
        return cls(energy=d["energy"], brightness=d["brightness"], pace=d["pace"])


def norm01(x: float, lo: float, hi: float) -> float:
    """Map x from [lo, hi] onto [0, 1], clamped. hi>lo required (raise otherwise)."""
    if hi <= lo:
        raise ValueError(f"norm01 needs hi>lo, got lo={lo}, hi={hi}")
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


# curated, synonym-rich — synonyms share their family's vector so unknowns are rare.
# COARSE hand-tuned guesses (energy, brightness, pace); they only need to ORDER
# roughly — the agent picks the shortlist. All tunable in this one place.
MOOD_ANCHORS: dict[str, MoodVector] = {
    "energetic": MoodVector(0.90, 0.70, 0.85), "hype": MoodVector(0.92, 0.72, 0.88),
    "driving": MoodVector(0.85, 0.60, 0.80),   "intense": MoodVector(0.88, 0.55, 0.75),
    "chill": MoodVector(0.25, 0.50, 0.30),     "mellow": MoodVector(0.30, 0.50, 0.35),
    "calm": MoodVector(0.20, 0.45, 0.25),      "relaxed": MoodVector(0.25, 0.48, 0.30),
    "epic": MoodVector(0.80, 0.55, 0.55),      "cinematic": MoodVector(0.75, 0.50, 0.50),
    "triumphant": MoodVector(0.85, 0.65, 0.60),
    "dark": MoodVector(0.50, 0.20, 0.45),      "moody": MoodVector(0.45, 0.25, 0.40),
    "brooding": MoodVector(0.50, 0.18, 0.40),
    "happy": MoodVector(0.70, 0.85, 0.70),     "joyful": MoodVector(0.75, 0.88, 0.72),
    "upbeat": MoodVector(0.72, 0.80, 0.75),    "bright": MoodVector(0.68, 0.90, 0.68),
    "melancholic": MoodVector(0.30, 0.35, 0.35), "sad": MoodVector(0.28, 0.30, 0.30),
    "somber": MoodVector(0.30, 0.28, 0.32),
    "dreamy": MoodVector(0.30, 0.60, 0.30),    "ethereal": MoodVector(0.28, 0.65, 0.28),
    "ambient": MoodVector(0.25, 0.55, 0.25),
    "tense": MoodVector(0.75, 0.40, 0.60),     "dramatic": MoodVector(0.78, 0.45, 0.55),
    "urgent": MoodVector(0.80, 0.42, 0.70),
}
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_mood.py -q ; echo "EXIT: $?"`
Expected: PASS (9 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/mood.py tests/lib/test_mood.py
git commit -m "feat: mood.py MoodVector + norm01 + MOOD_ANCHORS lexicon (5.5)"
```

---

## Task 1: `mood.mood_target` — free-text mood → target vector

**Files:**
- Modify: `scripts/lib/mood.py`
- Test: `tests/lib/test_mood.py`

- [x] **Step 1: Write the failing test** (append to `tests/lib/test_mood.py`)

```python
from scripts.lib.mood import mood_target


def test_mood_target_single_anchor():
    assert mood_target("energetic") == MOOD_ANCHORS["energetic"]


def test_mood_target_averages_multiple():
    t = mood_target("energetic dark")
    e, d = MOOD_ANCHORS["energetic"], MOOD_ANCHORS["dark"]
    assert t == MoodVector((e.energy + d.energy) / 2,
                           (e.brightness + d.brightness) / 2,
                           (e.pace + d.pace) / 2)


def test_mood_target_case_insensitive():
    assert mood_target("ENERGETIC") == MOOD_ANCHORS["energetic"]


def test_mood_target_ignores_punctuation_and_filler():
    assert mood_target("energetic, and driving!") == mood_target("energetic driving")


def test_mood_target_synonym_resolves():
    assert mood_target("mellow") == MOOD_ANCHORS["mellow"]


def test_mood_target_zero_match_returns_none():
    assert mood_target("purple wombat") is None


def test_mood_target_empty_returns_none():
    assert mood_target("") is None
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_mood.py -k mood_target -q ; echo "EXIT: $?"`
Expected: FAIL — `ImportError: cannot import name 'mood_target'`.

- [x] **Step 3: Write minimal implementation**

Add `import re` to the top of `scripts/lib/mood.py` (below the module docstring, above `from dataclasses import dataclass`), then add:

```python
def mood_target(text: str) -> "MoodVector | None":
    """Free-text mood → target MoodVector: lowercase, tokenize on word boundaries,
    average every token that is a MOOD_ANCHORS key. No known token → None (the driver
    falls back to rank_by_drive). 'energetic and dark' averages the two anchors."""
    matched = [MOOD_ANCHORS[t] for t in re.findall(r"[a-z]+", text.lower()) if t in MOOD_ANCHORS]
    if not matched:
        return None
    n = len(matched)
    return MoodVector(energy=sum(v.energy for v in matched) / n,
                      brightness=sum(v.brightness for v in matched) / n,
                      pace=sum(v.pace for v in matched) / n)
```

(Place `mood_target` after `MOOD_ANCHORS` — it references the table.)

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_mood.py -q ; echo "EXIT: $?"`
Expected: PASS (16 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/mood.py tests/lib/test_mood.py
git commit -m "feat: mood_target parses free-text mood → target vector (5.5)"
```

---

## Task 2: `mood.distance` + `rank` + `rank_by_drive`

**Files:**
- Modify: `scripts/lib/mood.py`
- Test: `tests/lib/test_mood.py`

- [x] **Step 1: Write the failing test** (append to `tests/lib/test_mood.py`)

```python
from scripts.lib.mood import distance, rank, rank_by_drive


def test_distance_identical_is_zero():
    v = MoodVector(0.5, 0.5, 0.5)
    assert distance(v, v) == 0.0


def test_distance_known_pair():
    assert distance(MoodVector(0.0, 0.0, 0.0), MoodVector(1.0, 0.0, 0.0)) == 1.0


def test_distance_weights_scale_one_axis():
    a, b = MoodVector(0.0, 0.0, 0.0), MoodVector(1.0, 0.0, 0.0)
    assert distance(a, b, weights=(4.0, 1.0, 1.0)) == 2.0     # sqrt(4 * 1) = 2


def test_rank_orders_ascending_by_distance():
    target = MoodVector(1.0, 1.0, 1.0)
    cands = [("far", MoodVector(0.0, 0.0, 0.0)), ("near", MoodVector(0.9, 0.9, 0.9))]
    assert [n for n, _d, _v in rank(cands, target)] == ["near", "far"]


def test_rank_stable_on_ties():
    target = MoodVector(0.0, 0.0, 0.0)
    a, b = MoodVector(0.5, 0.0, 0.0), MoodVector(0.5, 0.0, 0.0)   # equidistant
    assert [n for n, _d, _v in rank([("a", a), ("b", b)], target)] == ["a", "b"]


def test_rank_empty():
    assert rank([], MoodVector(0.5, 0.5, 0.5)) == []


def test_rank_by_drive_orders_by_energy_plus_pace_desc():
    lo = MoodVector(0.1, 0.9, 0.1)     # drive 0.2
    hi = MoodVector(0.8, 0.0, 0.7)     # drive 1.5
    ranked = rank_by_drive([("lo", lo), ("hi", hi)])
    assert [n for n, _s, _v in ranked] == ["hi", "lo"]
    assert ranked[0][1] == pytest.approx(1.5)      # positive drive in the score slot
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_mood.py -k "distance or rank" -q ; echo "EXIT: $?"`
Expected: FAIL — `ImportError: cannot import name 'distance'`.

- [x] **Step 3: Write minimal implementation**

Add `import math` at the top of `scripts/lib/mood.py` (with the other imports), add `from collections.abc import Sequence`, then append:

```python
def distance(a: MoodVector, b: MoodVector,
             weights: tuple[float, float, float] = (1.0, 1.0, 1.0)) -> float:
    """Weighted Euclidean distance in the 3-axis space (smaller = closer fit).
    Euclidean, not cosine: the axes are [0,1] and magnitude is meaningful."""
    return math.sqrt(sum(w * (x - y) ** 2
                         for w, x, y in zip(weights, a.as_tuple(), b.as_tuple())))


def rank(candidates: Sequence[tuple[str, MoodVector]], target: MoodVector,
         weights: tuple[float, float, float] = (1.0, 1.0, 1.0)
         ) -> list[tuple[str, float, MoodVector]]:
    """(name, vector) → sorted ascending by distance to target. Returns
    (name, distance, vector). Stable on ties (Python's sort preserves input order)."""
    scored = [(name, distance(v, target, weights), v) for name, v in candidates]
    return sorted(scored, key=lambda t: t[1])


def rank_by_drive(candidates: Sequence[tuple[str, MoodVector]]
                  ) -> list[tuple[str, float, MoodVector]]:
    """Fallback when mood_target is None: sort by drive = energy + pace DESCENDING
    (most-driving first — the most defensible order with no mood direction). Returns
    (name, drive, vector) with drive POSITIVE — the driver writes it under a `drive`
    key, never `distance`, so the two score semantics never share a field."""
    scored = [(name, v.energy + v.pace, v) for name, v in candidates]
    return sorted(scored, key=lambda t: t[1], reverse=True)
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_mood.py -q ; echo "EXIT: $?"`
Expected: PASS (23 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/mood.py tests/lib/test_mood.py
git commit -m "feat: mood distance + rank + rank_by_drive fallback (5.5)"
```

---

## Task 3: `beats.mood_features` — librosa file → MoodVector

**Files:**
- Modify: `scripts/beats.py` (import line + a new function)
- Test: `tests/lib/test_beats.py`

- [x] **Step 1: Write the failing test** (append to `tests/lib/test_beats.py`)

```python
from scripts.lib import mood


def _fake_librosa_mood(monkeypatch, *, tempo, centroid, rms_after_norm):
    """Stub beats' lazy librosa for mood_features: beat_track→tempo, spectral_centroid
    →centroid, rms→a frame whose mean is rms_after_norm. load() returns a peak=1.0
    signal so peak-normalization runs (rms is mocked, so its input doesn't matter)."""
    import librosa
    monkeypatch.setattr(librosa, "load",
                        lambda *a, **k: (np.array([1.0, -1.0], dtype=np.float32), 22050))
    monkeypatch.setattr(librosa.beat, "beat_track",
                        lambda *a, **k: (np.array([tempo]), np.array([])))
    monkeypatch.setattr(librosa.feature, "spectral_centroid",
                        lambda *a, **k: np.array([[centroid]]))
    monkeypatch.setattr(librosa.feature, "rms", lambda *a, **k: np.array([[rms_after_norm]]))


def test_mood_features_maps_into_the_vector_space(monkeypatch):
    _fake_librosa_mood(monkeypatch, tempo=120.0, centroid=2750.0, rms_after_norm=0.175)
    v = beats.mood_features("t.wav")
    assert v == mood.MoodVector(energy=mood.norm01(0.175, *mood.ENERGY_RMS),
                                brightness=mood.norm01(2750.0, *mood.BRIGHT_HZ),
                                pace=mood.norm01(120.0, *mood.PACE_BPM))
    # 120 BPM, 2750 Hz, 0.175 RMS are the axis midpoints → ~0.5 each
    assert v.energy == pytest.approx(0.5)
    assert v.brightness == pytest.approx(0.5)
    assert v.pace == pytest.approx(0.5)


def test_mood_features_silent_track_guards_zero_division(monkeypatch):
    import librosa
    monkeypatch.setattr(librosa, "load", lambda *a, **k: (np.zeros(100, dtype=np.float32), 22050))
    monkeypatch.setattr(librosa.beat, "beat_track", lambda *a, **k: (np.array([90.0]), np.array([])))
    monkeypatch.setattr(librosa.feature, "spectral_centroid", lambda *a, **k: np.array([[1000.0]]))
    monkeypatch.setattr(librosa.feature, "rms", lambda *a, **k: np.array([[0.0]]))
    v = beats.mood_features("silent.wav")     # peak=0 → guarded, no ZeroDivisionError
    assert v.energy == 0.0
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_beats.py -k mood_features -q ; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: module 'scripts.beats' has no attribute 'mood_features'`.

- [x] **Step 3: Write minimal implementation**

In `scripts/beats.py`, change the lib import line
```python
from scripts.lib import offset, vocals
```
to
```python
from scripts.lib import mood, offset, vocals
```
Then add (e.g. after `choose_offset`):

```python
def mood_features(track: str) -> mood.MoodVector:
    """Map a track into the mood.py vector space (design §3): tempo → pace,
    spectral-centroid mean → brightness, peak-normalized RMS mean → energy (loudness-
    robust: divide by max|y| before RMS, so mastering gain cancels). Lazy librosa,
    like analyze()/choose_offset()."""
    import librosa                                    # lazy import: heavy optional dep (librosa)
    y, sr = librosa.load(track, sr=None, mono=True)
    tempo = float(np.atleast_1d(librosa.beat.beat_track(y=y, sr=sr, hop_length=_HOP)[0])[0])
    centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=_HOP)))
    peak = float(np.max(np.abs(y))) or 1.0           # silent track → guard /0
    rms_mean = float(np.mean(librosa.feature.rms(y=y / peak, hop_length=_HOP)[0]))
    return mood.MoodVector(energy=mood.norm01(rms_mean, *mood.ENERGY_RMS),
                           brightness=mood.norm01(centroid, *mood.BRIGHT_HZ),
                           pace=mood.norm01(tempo, *mood.PACE_BPM))
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_beats.py -q ; echo "EXIT: $?"`
Expected: PASS (the two new tests plus the pre-existing `test_beats.py` tests).

- [x] **Step 5: Commit**

```bash
git add scripts/beats.py tests/lib/test_beats.py
git commit -m "feat: beats.mood_features maps a track into the mood vector space (5.5)"
```

---

## Task 4: `scripts/mood.py` driver — build_shortlist + writer + CLI

**Files:**
- Create: `scripts/mood.py`
- Test: `tests/lib/test_mood_driver.py`

- [x] **Step 1: Write the failing test**

```python
# tests/lib/test_mood_driver.py
"""scripts/mood.py driver — mocks beats.mood_features so no librosa runs here."""
import json
from pathlib import Path

import pytest

from scripts import mood as driver
from scripts.lib.mood import MoodVector


def _fake_folder(base, names):
    base.mkdir(parents=True, exist_ok=True)
    for n in names:
        (base / n).write_bytes(b"\x00")     # content irrelevant — mood_features is mocked
    return base


def _mock_features(monkeypatch, vecs):
    monkeypatch.setattr(driver.beats, "mood_features", lambda p: vecs[Path(p).name])


def test_build_shortlist_ranks_and_writes(tmp_path, monkeypatch):
    folder = _fake_folder(tmp_path / "trk", ["chill.wav", "energetic.wav"])
    _mock_features(monkeypatch, {"chill.wav": MoodVector(0.2, 0.5, 0.3),
                                 "energetic.wav": MoodVector(0.9, 0.7, 0.85)})
    out = tmp_path / "out"; out.mkdir()
    driver.build_shortlist(str(folder), "energetic", str(out))
    data = json.loads((out / "MUSIC_SHORTLIST.json").read_text())
    assert data["mood_text"] == "energetic" and data["fallback"] is None
    assert data["target"] is not None
    assert [c["track"] for c in data["candidates"]] == ["energetic.wav", "chill.wav"]
    assert "fit" in data["candidates"][0] and "distance" in data["candidates"][0]
    assert (out / "MUSIC_SHORTLIST.md").exists()


def test_build_shortlist_empty_folder_raises(tmp_path):
    empty = tmp_path / "empty"; empty.mkdir()
    with pytest.raises(ValueError, match="no audio files"):
        driver.build_shortlist(str(empty), "energetic", str(tmp_path))


def test_build_shortlist_unknown_mood_falls_back_to_drive(tmp_path, monkeypatch, capsys):
    folder = _fake_folder(tmp_path / "trk", ["a.wav", "b.wav"])
    _mock_features(monkeypatch, {"a.wav": MoodVector(0.1, 0.5, 0.1),    # drive 0.2
                                 "b.wav": MoodVector(0.9, 0.5, 0.9)})   # drive 1.8
    out = tmp_path / "out"; out.mkdir()
    driver.build_shortlist(str(folder), "purple wombat", str(out))
    data = json.loads((out / "MUSIC_SHORTLIST.json").read_text())
    assert data["fallback"] == "drive" and data["target"] is None
    assert [c["track"] for c in data["candidates"]] == ["b.wav", "a.wav"]   # higher drive first
    assert "drive" in data["candidates"][0] and "distance" not in data["candidates"][0]
    assert "ranking by drive" in capsys.readouterr().err


def test_cli_requires_spec_or_mood(tmp_path, monkeypatch):
    _fake_folder(tmp_path / "trk", ["x.wav"])
    monkeypatch.setattr("sys.argv", ["mood", "--folder", str(tmp_path / "trk"),
                                     "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit):        # mutually-exclusive group required → argparse error
        driver.main()


def test_cli_mood_text_writes_shortlist(tmp_path, monkeypatch):
    folder = _fake_folder(tmp_path / "trk", ["a.wav"])
    _mock_features(monkeypatch, {"a.wav": MoodVector(0.5, 0.5, 0.5)})
    out = tmp_path / "out"; out.mkdir()
    monkeypatch.setattr("sys.argv", ["mood", "--folder", str(folder), "--mood", "chill",
                                     "--out-dir", str(out)])
    driver.main()
    assert (out / "MUSIC_SHORTLIST.json").exists()


def test_cli_reads_mood_from_spec(tmp_path, monkeypatch):
    from scripts.lib.spec import Spec
    folder = _fake_folder(tmp_path / "trk", ["a.wav"])
    _mock_features(monkeypatch, {"a.wav": MoodVector(0.9, 0.7, 0.85)})
    spec = tmp_path / "SPEC.json"
    Spec(canvas=(1080, 1920), length_s=30.0, mood="energetic", hook="x").write(spec)
    out = tmp_path / "out"; out.mkdir()
    monkeypatch.setattr("sys.argv", ["mood", "--folder", str(folder), "--spec", str(spec),
                                     "--out-dir", str(out)])
    driver.main()
    data = json.loads((out / "MUSIC_SHORTLIST.json").read_text())
    assert data["mood_text"] == "energetic"
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_mood_driver.py -q ; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.mood'`.

- [x] **Step 3: Write minimal implementation**

```python
# scripts/mood.py
"""music-and-mood selection (design docs/specs/2026-07-13-mood-match-design.md, §5.5
local lane): rank a folder of candidate tracks by fit to SPEC.mood → MUSIC_SHORTLIST.
The agent picks the top row, then `beats --auto-start` produces MUSIC.json. A thin
driver over the pure scripts/lib/mood.py core + beats.mood_features (librosa extractor)."""
import argparse
import json
import sys
from pathlib import Path

from scripts import beats
from scripts.lib import mood
from scripts.lib.spec import Spec

AUDIO_EXT = (".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg")


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def build_shortlist(folder: str, mood_text: str, out_dir: str) -> dict:
    """Rank the audio files in `folder` by fit to `mood_text` → MUSIC_SHORTLIST.{json,md}
    in out_dir. Returns {"json": path, "md": path, "ranked": [...]}. Empty folder raises;
    a mood matching no anchor logs and falls back to drive-ranking (never silent)."""
    tracks = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in AUDIO_EXT)
    if not tracks:
        raise ValueError(f"no audio files ({'/'.join(AUDIO_EXT)}) in {folder} — "
                         f"point --folder at a folder of candidate tracks")
    cands = [(p.name, beats.mood_features(str(p))) for p in tracks]
    target = mood.mood_target(mood_text)
    if target is None:
        _log(f"mood-match: '{mood_text}' matched no mood anchor "
             f"({', '.join(sorted(mood.MOOD_ANCHORS))}) — ranking by drive (energy+pace)")
        ranked = mood.rank_by_drive(cands)
        head = {"target": None, "fallback": "drive"}
        cand_json = [{"track": n, "drive": round(s, 4), "vector": v.to_dict()}
                     for n, s, v in ranked]
    else:
        ranked = mood.rank(cands, target)
        head = {"target": target.to_dict(), "fallback": None}
        cand_json = [{"track": n, "distance": round(s, 4), "fit": round(1.0 / (1.0 + s), 4),
                      "vector": v.to_dict()} for n, s, v in ranked]
    payload = {"mood_text": mood_text, **head, "candidates": cand_json}
    out = Path(out_dir)
    json_path, md_path = out / "MUSIC_SHORTLIST.json", out / "MUSIC_SHORTLIST.md"
    json_path.write_text(json.dumps(payload, indent=2))
    md_path.write_text(_to_markdown(payload))
    return {"json": str(json_path), "md": str(md_path), "ranked": ranked}


def _to_markdown(payload: dict) -> str:
    if payload["fallback"] == "drive":
        sub = "_no mood anchor matched — ranked by drive (energy+pace)_"
    else:
        t = payload["target"]
        sub = (f"_target: energy {t['energy']:.2f} · brightness {t['brightness']:.2f} "
               f"· pace {t['pace']:.2f}_")
    lines = [f"# Music shortlist — mood: {payload['mood_text']}", "", sub, "",
             "| # | track | fit | energy | brightness | pace |",
             "|--:|-------|----:|-------:|-----------:|-----:|"]
    for i, c in enumerate(payload["candidates"], 1):
        v = c["vector"]
        fit = f"{c['fit']:.2f}" if "fit" in c else f"drive {c['drive']:.2f}"
        lines.append(f"| {i} | {c['track']} | {fit} | {v['energy']:.2f} | "
                     f"{v['brightness']:.2f} | {v['pace']:.2f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="rank a folder of tracks by mood-fit → MUSIC_SHORTLIST.{json,md}")
    ap.add_argument("--folder", required=True, help="folder of candidate audio tracks")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--spec", help="SPEC.json — reads its mood field")
    g.add_argument("--mood", help="mood text directly (e.g. 'energetic')")
    ap.add_argument("--out-dir", required=True, help="where to write MUSIC_SHORTLIST.{json,md}")
    a = ap.parse_args()
    mood_text = Spec.from_json(a.spec).mood if a.spec else a.mood
    res = build_shortlist(a.folder, mood_text, a.out_dir)
    print(res["json"])
    print(res["md"])


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_mood_driver.py -q ; echo "EXIT: $?"`
Expected: PASS (6 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/mood.py tests/lib/test_mood_driver.py
git commit -m "feat: mood.py driver — build_shortlist + MUSIC_SHORTLIST writer + CLI (5.5)"
```

---

## Task 5: integration `test_mood.py` — real librosa + golden

**Files:**
- Create: `tests/integration/test_mood.py`

- [x] **Step 1: Write the test** (these pass once Tasks 3–4 are in; they exercise the real librosa path)

```python
# tests/integration/test_mood.py
"""Real-librosa integration for mood-match (design §7): mood_features on synthetic
known signals (a real dep, a known-answer input — the test_beats ethos), and a
2-track golden proving build_shortlist ranks the energetic track first. All ±tol —
librosa isn't bit-exact on synthetic audio."""
import json

import numpy as np
import pytest
from scipy.io import wavfile

from scripts import beats, mood as driver


def _sine_wav(path, sr, secs, freq, amp=0.5):
    t = np.arange(int(secs * sr)) / sr
    wavfile.write(path, sr, (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32))
    return str(path)


def _mix_wav(path, sr, secs, freq, bpm, amp):
    """A tone at `freq` gated into clicks at `bpm` — carries both a spectral centroid
    (freq → brightness) and a tempo (bpm → pace), so mood_features reads both axes."""
    t = np.arange(int(secs * sr)) / sr
    tone = np.sin(2 * np.pi * freq * t)
    env = np.zeros_like(t)
    step = int(sr * 60.0 / bpm)
    width = max(1, step // 4)
    for i in range(0, len(env), step):
        env[i:i + width] = 1.0
    wavfile.write(path, sr, (amp * tone * env).astype(np.float32))
    return str(path)


@pytest.mark.integration
def test_mood_features_brightness_tracks_frequency(tmp_path):
    dark = beats.mood_features(_sine_wav(tmp_path / "d.wav", 22050, 4, freq=200))
    bright = beats.mood_features(_sine_wav(tmp_path / "b.wav", 22050, 4, freq=6000))
    assert bright.brightness > dark.brightness


@pytest.mark.integration
def test_mood_features_energy_is_loudness_robust(tmp_path):
    loud = beats.mood_features(_sine_wav(tmp_path / "l.wav", 22050, 4, freq=1000, amp=0.9))
    quiet = beats.mood_features(_sine_wav(tmp_path / "q.wav", 22050, 4, freq=1000, amp=0.1))
    assert loud.energy == pytest.approx(quiet.energy, abs=0.05)   # peak-normalized → equal


@pytest.mark.integration
def test_mood_features_pace_tracks_tempo(tmp_path):
    slow = beats.mood_features(_mix_wav(tmp_path / "s.wav", 22050, 8, freq=1000, bpm=70, amp=0.6))
    fast = beats.mood_features(_mix_wav(tmp_path / "f.wav", 22050, 8, freq=1000, bpm=150, amp=0.6))
    assert fast.pace > slow.pace


@pytest.mark.integration
def test_build_shortlist_golden_ranks_energetic_first(tmp_path):
    folder = tmp_path / "trk"; folder.mkdir()
    _mix_wav(folder / "energetic.wav", 22050, 8, freq=5000, bpm=150, amp=0.9)  # bright + fast
    _mix_wav(folder / "chill.wav", 22050, 8, freq=250, bpm=70, amp=0.3)        # dark + slow
    out = tmp_path / "out"; out.mkdir()
    driver.build_shortlist(str(folder), "energetic", str(out))
    data = json.loads((out / "MUSIC_SHORTLIST.json").read_text())
    assert data["candidates"][0]["track"] == "energetic.wav"
```

- [x] **Step 2: Run the tests**

Run: `.venv/bin/python -m pytest tests/integration/test_mood.py -q ; echo "EXIT: $?"`
Expected: PASS (4 tests). If `test_mood_features_pace_tracks_tempo` is flaky on librosa's tempo estimate, widen the BPM gap (e.g. 60 vs 170) — do **not** loosen it into a tautology.

- [x] **Step 3: Commit**

```bash
git add tests/integration/test_mood.py
git commit -m "test: real-librosa mood_features + build_shortlist golden (5.5)"
```

---

## Task 6: `music-match` SKILL + using-montage wiring

**Files:**
- Create: `SKILLS/music-match/SKILL.md`
- Modify: `SKILLS/using-montage/SKILL.md:64-71` (the music step)

- [x] **Step 1: Write the SKILL**

```markdown
<!-- SKILLS/music-match/SKILL.md -->
---
name: music-match
description: Stage 5.5 (local lane) — pick the reel's track from a folder of candidates by mood. Use when the brief has a mood but no chosen track and the user has a music folder. Ranks every track by fit to SPEC.mood into MUSIC_SHORTLIST.md, you present the top few, the user picks, then beats --auto-start writes MUSIC.json. Optional: enriches the music checkpoint; the autonomous path (an explicit track) skips it.
---

# music-match (stage 5.5, local lane)

Turn a **folder of candidate tracks** + the reel's mood into a ranked shortlist, so
the user picks a track by ear from a short, mood-sorted list instead of scrubbing a
whole library. Local and deterministic — no network, no downloads. This is the
**selection** pass; the chosen track still goes through `beats --auto-start` for the
final `MUSIC.json`.

**The ranking is numbers; the pick is judgment.** `mood.py` scores each track's
energy / brightness / pace against `SPEC.mood`; you surface the top rows; the user
makes the final call (the §4.1 music checkpoint stays human-influenced).

## Inputs

- **`SPEC.json`** (from reel-brief) — supplies `mood` and `length_s`. No SPEC? Pass
  the mood text directly with `--mood "..."`.
- **A candidate folder** — the user's own tracks (`music.mode=local`). Audio files
  only (`.mp3 .m4a .wav .flac .aac .ogg`).

## Procedure

Announce on entry: **"Using music-match to shortlist the reel's track by mood."**

1. **Recon.** Read `SPEC.json` (note `mood`, `length_s`) and confirm the candidate
   folder path with the user.
2. **Rank** (you type the flags; the user never does):
   `.venv/bin/python -m scripts.mood --folder <dir> --spec <run>/SPEC.json --out-dir <run>`
   (or `--mood "energetic"` when there is no SPEC). It writes
   `<run>/MUSIC_SHORTLIST.md` + `.json`.
   - An **unrecognized mood** is not an error — the tool logs it and ranks by drive
     (energy+pace); say so when you present the list.
   - An **empty / no-audio folder** fails loud — fix the path and re-run.
3. **Present** the top few `MUSIC_SHORTLIST.md` rows (rank · track · fit · the three
   axes). The user picks one — or asks to hear them and picks by ear.
4. **Lock the pick** into `MUSIC.json`:
   `.venv/bin/python -m scripts.beats <picked-track> --auto-start --duration <length_s> --out <run>/MUSIC.json`
   — the start-offset intelligence starts the reel on the strongest fragment, in a
   vocal pause. Pass `<run>/MUSIC.json` on to edit-plan.

## Not this skill

- **Sourcing** a track from the internet (royalty-free or otherwise) — deferred
  (B3); music-match ranks a **local folder** the user already has.
- **Writing `MUSIC.json`** — that is `beats --auto-start` (step 4), not this skill.
- **The beat grid / loudness gate** — those are `beats.analyze` / `check_reel`.
```

- [x] **Step 2: Wire it into using-montage**

In `SKILLS/using-montage/SKILL.md`, replace the step-5 block (lines 64–71, "music-and-mood (optional)…") with:

```markdown
5. **music-and-mood (optional).** If the brief names a **track**, analyse it
   directly — prefer letting the tool pick the in-point:
   `.venv/bin/python -m scripts.beats <track> --auto-start --duration <reel_len>
   --out <run>/MUSIC.json` — it starts the reel on the strongest fragment, in a
   vocal pause (accurate with `bash setup.sh --with-demucs`; a librosa mix-silence
   proxy otherwise). Pass an explicit `--start-offset S` instead only to override.
   If instead the brief has a **mood but no chosen track** and the user has a
   **folder** of candidates, invoke the **music-match** skill first — it ranks the
   folder by mood into `MUSIC_SHORTLIST.md`, the user picks, and it runs the same
   `beats --auto-start`. Then pass `<run>/MUSIC.json` to edit-plan. On "no music" /
   "без музыки", leave it unset — the reel is silent (a valid path).
```

- [x] **Step 3: Verify the SKILL files are well-formed**

Run: `.venv/bin/python -c "import pathlib; [print(p, 'OK') for p in ('SKILLS/music-match/SKILL.md', 'SKILLS/using-montage/SKILL.md') if pathlib.Path(p).read_text().startswith('---') or 'music-match' in pathlib.Path(p).read_text()]"`
Expected: both paths print `OK` (the SKILL has frontmatter; using-montage references music-match).

Run the full suite to confirm nothing regressed: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`
Expected: PASS (green; the prior count + the new mood tests).

- [x] **Step 4: Commit**

```bash
git add SKILLS/music-match/SKILL.md SKILLS/using-montage/SKILL.md
git commit -m "feat: music-match SKILL + using-montage music-step wiring (5.5)"
```

---

## Task 7: docs sync + final whole-slice review

**Files:**
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`,
  `docs/specs/2026-07-05-montage-skillset-design.md`,
  `docs/specs/2026-07-11-music-spine-design.md`

- [x] **Step 1: `docs/build-status.md`** — add a "Done" entry after the start-offset one:

```markdown
- **mood-match (§5.5 sub-slice, local lane) DONE (2026-07-13)** — plan
  `docs/plans/2026-07-13-mood-match.md` + design
  `docs/specs/2026-07-13-mood-match-design.md`. `scripts/lib/mood.py` — the pure
  core (the `offset.py` analog): `MoodVector` (3 axes energy/brightness/pace,
  validate + round-trip), a synonym-rich `MOOD_ANCHORS` lexicon, `mood_target`
  (free-text mood → target, zero-match → None), `distance` (weighted Euclidean),
  `rank`, and `rank_by_drive` (the no-target fallback). `scripts/beats.py` gains
  `mood_features(track)` — lazy librosa: tempo → pace, spectral centroid →
  brightness, **peak-normalized** RMS mean → energy (loudness-robust, the §12
  relative-gate discipline). `scripts/mood.py` — the driver: scan a folder →
  `mood_features` each → rank vs `mood_target(SPEC.mood)` (or `rank_by_drive` on a
  zero-match) → `MUSIC_SHORTLIST.{json,md}`; CLI `--folder (--spec|--mood) --out-dir`.
  `SKILLS/music-match` runs it, presents the shortlist, the user picks, then the
  existing `beats --auto-start` writes `MUSIC.json`. Pure core exhaustively
  unit-tested; `mood_features` + the ranking golden are real-librosa integration
  tests (synthetic known-answer signals, ±tol). **Deferred:** B3 autonomous
  sourcing (networked), catalog-metadata mood, a 4th dynamism axis, feature caching.
```

  And refresh **"Next action"** — drop mood-match from the open list and note 5.5's
  remaining gap is now only **B3 sourcing** (mood-match landed): edit the first
  "Front-half continuation" bullet's siblings so the "Phase B3 — autonomous music
  sourcing" bullet reads that mood-match is now built and B3 (sourcing) + B4 (pacing)
  remain.

- [x] **Step 2: `docs/pipeline-map.md`** — update the 5.5 row's "Module / note" cell
  to append `+ mood-match (local: rank a folder vs SPEC.mood → MUSIC_SHORTLIST) ✅`,
  and change its "Left to build" cell in the blockers table to `sourcing (B3)` only
  (mood-match done). 5.5 **stays ◐** (B3 still open). The tally (11 ✅ · 3 ◐ · 2 ❌)
  is unchanged.

- [x] **Step 3: `CLAUDE.md`** — add two Quick-Reference rows (after the start-offset rows):

```markdown
| Mood-match design | [2026-07-13-mood-match-design.md](docs/specs/2026-07-13-mood-match-design.md) | §5.5 local lane: rank a folder vs `SPEC.mood` — pure `mood.py` core (`MoodVector`/`MOOD_ANCHORS` lexicon/`rank`) + loudness-robust `beats.mood_features` + `scripts/mood.py` driver → `MUSIC_SHORTLIST`; `music-match` SKILL; B3 sourcing deferred. |
| Mood-match plan | [2026-07-13-mood-match.md](docs/plans/2026-07-13-mood-match.md) | Tasks 0–7: `mood.py` (MoodVector/norm01/anchors, mood_target, distance/rank/rank_by_drive), `beats.mood_features`, `scripts/mood.py` driver + CLI, real-librosa golden, `music-match` SKILL + wiring, docs. |
```

- [x] **Step 4: `docs/specs/2026-07-05-montage-skillset-design.md`** — add a "Built"
  blockquote under the §5.5 section (after the start-offset one):

```markdown
> **Built (2026-07-13, mood-match):** the §5.5 mood-match (local lane) now ships —
> `scripts/lib/mood.py` scores a track's energy/brightness/pace (loudness-robust)
> against a curated mood lexicon and `scripts/mood.py` ranks a local folder vs
> `SPEC.mood` into `MUSIC_SHORTLIST.md` for the agent to pick from (`music-match`
> SKILL). Autonomous **sourcing** (`music_find`/`music_fetch`, `music.mode`
> free/any) stays deferred (B3). See `docs/specs/2026-07-13-mood-match-design.md`.
```

- [x] **Step 5: `docs/specs/2026-07-11-music-spine-design.md`** — extend the §9
  "Start-offset intelligence" deferred bullet (or add a sibling) noting mood-match
  landed 2026-07-13 (`docs/specs/2026-07-13-mood-match-design.md`); **B3 sourcing**
  remains the sole deferred §5.5 item.

- [x] **Step 6: Tick this plan's checkboxes** — mark every `- [x]` in
  `docs/plans/2026-07-13-mood-match.md` as `- [x]` (the source-of-truth rule:
  plan checkboxes + build-status move in the same commit as the work).

- [x] **Step 7: Run the whole suite green**

Run: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`
Expected: PASS, EXIT 0.

- [x] **Step 8: Commit**

```bash
git add docs/ CLAUDE.md
git commit -m "docs: sync build-status/pipeline-map/specs/registry for mood-match (5.5)"
```

- [x] **Step 9: Final whole-slice review**

Dispatch a fresh reviewer subagent (most-capable model) over the whole branch diff
(`git diff main...HEAD`) against `docs/specs/2026-07-13-mood-match-design.md`. The
review brief MUST forbid machine mutation (no installers, no `setup.sh`; read-only +
pytest). Focus: the `mood_features` peak-normalization (loudness-robustness is the
headline §12 discipline — verify a mocked/real loud-vs-quiet pair reads equal
energy), the `rank`/`rank_by_drive` score-field separation (`distance`/`fit` vs
`drive` never conflated), the zero-match fallback logging, and the empty-folder
raise. Fix any Important/Minor findings in **separate follow-up commits** (never
`--amend`). Then proceed to `superpowers:finishing-a-development-branch`.

---

## Self-review (writing-plans checklist — completed)

**Spec coverage:** §1 architecture → Tasks 0–6 (files match). §2 pure core (MoodVector/
lexicon/mood_target/distance/rank/rank_by_drive) → Tasks 0–2. §3 mood_features (peak-
normalized) → Task 3. §4 driver + shortlist json/md + CLI → Task 4. §5 SKILL + wiring
→ Task 6. §6 edge cases (empty folder raise, zero-match fallback, silent-track guard,
norm01 clamp) → Tasks 0/3/4 tests. §7 testing (pure unit + real-librosa integration +
golden) → Tasks 0–5. §8 landmines (loudness-robust energy, determinism, never-silent)
→ Tasks 3/4/5 + review Task 7. §9 non-goals → not built (correct). §10 doc-sync → Task 7.

**Placeholder scan:** no TBD/TODO; every code step is literal; the full `MOOD_ANCHORS`
table is enumerated (Task 0); the SKILL body is complete (Task 6).

**Type consistency:** `MoodVector(energy, brightness, pace)` used identically in Tasks
0–5; `norm01(x, lo, hi)`, `mood_target→MoodVector|None`, `rank→[(name,distance,vector)]`,
`rank_by_drive→[(name,drive,vector)]`, `build_shortlist(folder, mood_text, out_dir)→dict`,
`beats.mood_features(track)→MoodVector` consistent across tasks and the driver/tests.
The two `mood` modules (`scripts.lib.mood` vs `scripts.mood`) are aliased consistently
(`mood` vs `driver`).

## Review addendum (as-built delta)

Beyond the as-planned literal blocks above:

- **Task 0 — `from_dict` missing-key (commit `edff5d7`).** The adversarial review of
  the pure core found `MoodVector.from_dict` raised a bare `KeyError` on a truncated
  dict, unmet by design §6 ("a corrupt shortlist fails loud with the remedy") and §7
  (which enumerates a missing-key test). Fixed as a separate follow-up commit:
  `from_dict` now raises a remedy-bearing `ValueError` naming the missing key(s), and
  `test_moodvector_from_dict_missing_key_raises` was added. `tests/lib/test_mood.py`
  is therefore **24** tests, not the 23 of the as-planned blocks (the earlier "24" in
  Task 2's step 4 was an arithmetic slip; the review test independently brings the real
  count to 24). Whole suite: **702 passed / 7 skipped**.
- The `distance()` short-`weights` truncation the review also noted was left as-is
  (YAGNI: the parameter is type-hinted 3-tuple, the only in-repo caller passes the
  3-tuple default, and it matches the `offset.py` sibling that this slice mirrors).
