# Footage-intake (5.2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a folder of raw clips into a typed `FOOTAGE.json` + rendered `FOOTAGE.md` of scored candidate moment-windows, plus an interactive `cast.json` hero registry — stage 5.2, so 5.7 edit-plan has typed windows to select from.

**Architecture:** A hard config-spec module (`scripts/lib/footage.py`) + a mechanical CV driver (`scripts/intake.py`: probe → PySceneDetect → one YOLO11-seg pass → vidstabdetect → sub-scene carve → score → phash cull) + an interactive SKILL for hero naming. Every pure step is a standalone, unit-tested function with mocked CV; one real-ffmpeg golden proves the wiring.

**Tech stack:** Python 3.13, `ultralytics` (YOLO11-seg + ByteTrack), `scenedetect`, `imagehash`, `numpy`, `Pillow`, ffmpeg **with libvidstab** (intake is the repo's first runtime vidstab consumer), pytest.

**Design:** [docs/specs/2026-07-12-footage-intake-design.md](../specs/2026-07-12-footage-intake-design.md).

---

## File structure

| File | Responsibility |
|------|----------------|
| `scripts/lib/footage.py` (new) | `FootageWindow`/`FootageClip`/`Footage` (+`to_markdown`, `ranked_windows`) and `CastMember`/`Cast` config-specs — JSON round-trip, raise-on-bad. |
| `scripts/intake.py` (new) | CV driver: probe, scene bounds, YOLO-seg pass, vidstabdetect, carve, score, cull, cast helpers, `intake()` + CLI. |
| `scripts/lib/assembly.py` (modify) | Promote `probe_duration` (from `extract._probe_dur`). |
| `scripts/extract.py` (modify) | Import `probe_duration` from `assembly`. |
| `SKILLS/footage-intake/SKILL.md` (new) | Interactive subagent: run intake, surface crops, name heroes, write `cast.json`, report gate. |
| `tests/lib/test_footage.py` (new) | Contract raise-on-bad + round-trip + `to_markdown`. |
| `tests/lib/test_intake.py` (new) | Pure CV units with mocked YOLO. |
| `tests/integration/test_intake.py` (new) | Real-ffmpeg golden (sample_clip + faked `_iter_seg` + real scenes/vidstab). |
| docs (modify) | build-status, pipeline-map, CLAUDE.md registry, montage §5.2. |

---

## Task 0: Promote `assembly.probe_duration`

**Files:**
- Modify: `scripts/lib/assembly.py`
- Modify: `scripts/extract.py`
- Test: `tests/lib/test_assembly.py`

- [x] **Step 1: Write the failing test**

```python
# tests/lib/test_assembly.py  (add)
from scripts.lib import assembly
from scripts import extract

def test_probe_duration_is_the_shared_helper():
    # extract._probe_dur is promoted to assembly.probe_duration — one duration probe, shared.
    assert extract._probe_dur is assembly.probe_duration
    assert callable(assembly.probe_duration)
```

- [x] **Step 2: Run — expect fail** (`AttributeError: module 'scripts.lib.assembly' has no attribute 'probe_duration'`)

Run: `.venv/bin/python -m pytest tests/lib/test_assembly.py::test_probe_duration_is_the_shared_helper -v`

- [x] **Step 3: Implement** — move the body into `assembly.py`:

```python
# scripts/lib/assembly.py  (add near the other probes)
def probe_duration(path: str) -> float:
    """Container duration in seconds (format=duration). StreamInfo carries w/h/fps
    only; this is the shared duration probe (was extract._probe_dur)."""
    out = proc.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nk=1:nw=1", path]).stdout.decode().strip()
    try:
        return float(out)
    except ValueError as e:
        raise ValueError(f"ffprobe returned no duration for {path!r} ({out!r}) — corrupt/streamed source?") from e
```

Then in `scripts/extract.py` replace the `_probe_dur` definition with an import-backed alias:

```python
# scripts/extract.py
from scripts.lib.assembly import probe_duration as _probe_dur   # keep the local name its callers use
```

(Delete the old `def _probe_dur(...)` body. `assembly` already imports `proc`.)

- [x] **Step 4: Run — expect pass**, and the whole extract suite still green:

Run: `.venv/bin/python -m pytest tests/lib/test_assembly.py tests/lib/test_edl.py tests/integration/test_extract.py -q`

- [x] **Step 5: Commit**

```bash
git add scripts/lib/assembly.py scripts/extract.py tests/lib/test_assembly.py
git commit -m "refactor: promote extract._probe_dur → assembly.probe_duration (shared by intake)"
```

---

## Task 1: `footage.FootageWindow`

**Files:**
- Create: `scripts/lib/footage.py`
- Test: `tests/lib/test_footage.py`

- [x] **Step 1: Write the failing test**

```python
# tests/lib/test_footage.py
import pytest
from scripts.lib.footage import FootageWindow

def _win(**kw):
    d = dict(start=1.0, dur=2.0, shot_type="medium", people=1, motion=0.4, shake=0.01)
    d.update(kw)
    return FootageWindow(**d)

def test_window_roundtrips():
    w = _win(description="1 person, medium, dynamic", score=0.7, best=True)
    assert FootageWindow(**w.to_dict()).to_dict() == w.to_dict()

@pytest.mark.parametrize("kw,msg", [
    (dict(start=-1), "start"), (dict(dur=0), "dur"), (dict(shot_type=""), "shot_type"),
    (dict(people=-1), "people"), (dict(people=True), "people"),
    (dict(motion=1.5), "motion"), (dict(shake=-0.1), "shake"), (dict(score=2.0), "score"),
])
def test_window_rejects_bad(kw, msg):
    with pytest.raises(ValueError, match=msg):
        _win(**kw)
```

- [x] **Step 2: Run — expect fail** (`ModuleNotFoundError: scripts.lib.footage`)

- [x] **Step 3: Implement**

```python
# scripts/lib/footage.py
"""Footage-intake contracts: scored candidate windows + the cast registry
(design docs/specs/2026-07-12-footage-intake-design.md, stage 5.2).

Hard config-specs — validate-and-raise in __post_init__, JSON round-trip — like
models.py's TrackSpec/MusicSpec and edl.py's EDL (NOT the soft manifest gate).
Mutable on purpose: intake's cull sets FootageWindow.best after construction.
A FootageWindow projects onto an EDLEpisode (source lives on the parent clip),
so 5.7 edit-plan promotes a window to an episode by a mechanical field map.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@dataclass
class FootageWindow:
    start: float
    dur: float
    shot_type: str
    people: int
    motion: float
    shake: float
    description: str = ""
    score: float = 0.0
    best: bool = False

    def __post_init__(self) -> None:
        if not (_num(self.start) and self.start >= 0):
            raise ValueError(f"FootageWindow.start must be a number >= 0 (seconds), got {self.start!r}")
        if not (_num(self.dur) and self.dur > 0):
            raise ValueError(f"FootageWindow.dur must be a positive number (seconds), got {self.dur!r}")
        if not (isinstance(self.shot_type, str) and self.shot_type):
            raise ValueError("FootageWindow.shot_type must be a non-empty tag (e.g. 'wide', 'close')")
        if isinstance(self.people, bool) or not isinstance(self.people, int) or self.people < 0:
            raise ValueError(f"FootageWindow.people must be an int >= 0, got {self.people!r}")
        if not (_num(self.motion) and 0.0 <= self.motion <= 1.0):
            raise ValueError(f"FootageWindow.motion must be a number in [0, 1], got {self.motion!r}")
        if not (_num(self.shake) and self.shake >= 0):
            raise ValueError(f"FootageWindow.shake must be a number >= 0, got {self.shake!r}")
        if not isinstance(self.description, str):
            raise ValueError("FootageWindow.description must be a string")
        if not (_num(self.score) and 0.0 <= self.score <= 1.0):
            raise ValueError(f"FootageWindow.score must be a number in [0, 1], got {self.score!r}")
        if not isinstance(self.best, bool):
            raise ValueError("FootageWindow.best must be a bool")

    def to_dict(self) -> dict:
        return {"start": self.start, "dur": self.dur, "shot_type": self.shot_type,
                "people": self.people, "motion": self.motion, "shake": self.shake,
                "description": self.description, "score": self.score, "best": self.best}
```

- [x] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/lib/test_footage.py -q`

- [x] **Step 5: Commit**

```bash
git add scripts/lib/footage.py tests/lib/test_footage.py
git commit -m "feat: footage.FootageWindow config-spec (5.2)"
```

---

## Task 2: `footage.FootageClip`

**Files:**
- Modify: `scripts/lib/footage.py`
- Test: `tests/lib/test_footage.py`

- [x] **Step 1: Write the failing test**

```python
# tests/lib/test_footage.py  (add)
from scripts.lib.footage import FootageClip

def test_clip_roundtrips_and_wraps_windows():
    c = FootageClip(source="a.mp4", dur=22.0, res=(1920, 1080), fps=59.94,
                    shaky=False, scene_cuts=[3.0], windows=[_win()])
    back = FootageClip.from_dict(c.to_dict())
    assert back.to_dict() == c.to_dict()
    assert isinstance(back.windows[0], FootageWindow)

def test_clip_from_dict_names_bad_window():
    with pytest.raises(ValueError, match=r"windows\[0\]"):
        FootageClip.from_dict(dict(source="a.mp4", dur=1.0, res=[10, 10], fps=30,
                                   windows=[dict(start=1.0, dur=2.0, shot_type="x", people=1,
                                                 motion=0.4, shake=0.0, bogus=1)]))

def test_clip_rejects_bad_res():
    with pytest.raises(ValueError, match="res"):
        FootageClip(source="a.mp4", dur=1.0, res=(0, 10), fps=30)
```

- [x] **Step 2: Run — expect fail** (`ImportError: cannot import name 'FootageClip'`)

- [x] **Step 3: Implement** (append to `footage.py`)

```python
@dataclass
class FootageClip:
    source: str
    dur: float
    res: tuple[int, int]
    fps: float
    shaky: bool = False
    scene_cuts: list[float] = field(default_factory=list)
    windows: list[FootageWindow] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not (isinstance(self.source, str) and self.source):
            raise ValueError("FootageClip.source must be a non-empty clip path")
        if not (_num(self.dur) and self.dur > 0):
            raise ValueError(f"FootageClip.dur must be a positive number, got {self.dur!r}")
        if isinstance(self.res, list):
            self.res = tuple(self.res)
        if not (isinstance(self.res, tuple) and len(self.res) == 2
                and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in self.res)):
            raise ValueError(f"FootageClip.res must be (w, h) positive ints, got {self.res!r}")
        if not (_num(self.fps) and self.fps > 0):
            raise ValueError(f"FootageClip.fps must be a positive number, got {self.fps!r}")
        if not isinstance(self.shaky, bool):
            raise ValueError("FootageClip.shaky must be a bool")
        self.scene_cuts = [float(t) for t in self.scene_cuts]
        for k, w in enumerate(self.windows):
            if not isinstance(w, FootageWindow):
                raise ValueError(f"FootageClip.windows[{k}] must be a FootageWindow")

    @classmethod
    def from_dict(cls, d: dict) -> "FootageClip":
        wins_in = d.get("windows", [])
        if not isinstance(wins_in, list):
            raise ValueError("FootageClip.from_dict: 'windows' must be a list")
        wins = []
        for k, w in enumerate(wins_in):
            if not isinstance(w, dict):
                raise ValueError(f"FootageClip.from_dict: windows[{k}] must be an object")
            try:
                wins.append(FootageWindow(**w))
            except TypeError as ex:
                raise ValueError(f"FootageClip.from_dict: windows[{k}] has a missing or unknown field — {ex}") from ex
        try:
            return cls(**{**d, "windows": wins})       # unknown top-level key → TypeError → remedy
        except TypeError as ex:
            raise ValueError(f"FootageClip.from_dict: missing or unknown field — {ex}") from ex

    def to_dict(self) -> dict:
        return {"source": self.source, "dur": self.dur, "res": list(self.res), "fps": self.fps,
                "shaky": self.shaky, "scene_cuts": self.scene_cuts,
                "windows": [w.to_dict() for w in self.windows]}
```

- [x] **Step 4: Run — expect pass** (`.venv/bin/python -m pytest tests/lib/test_footage.py -q`)

- [x] **Step 5: Commit** (`git commit -m "feat: footage.FootageClip config-spec (5.2)"`)

---

## Task 3: `footage.Footage` + `to_markdown` + `ranked_windows` + `from_json`

**Files:** Modify `scripts/lib/footage.py`; Test `tests/lib/test_footage.py`

- [x] **Step 1: Write the failing test**

```python
# tests/lib/test_footage.py  (add)
from scripts.lib.footage import Footage

def _footage():
    return Footage(clips=[FootageClip(source="a.mp4", dur=22.0, res=(1920, 1080), fps=30,
                                      scene_cuts=[3.0],
                                      windows=[_win(score=0.8, best=True),
                                               _win(start=5.0, score=0.3)])])

def test_footage_roundtrips():
    f = _footage()
    assert Footage.from_dict(f.to_dict()).to_dict() == f.to_dict()

def test_footage_from_json_bad_syntax(tmp_path):
    p = tmp_path / "FOOTAGE.json"; p.write_text("{ not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        Footage.from_json(p)

def test_ranked_windows_is_score_descending():
    f = _footage()
    ranked = f.ranked_windows()
    assert [w.score for _, w in ranked] == [0.8, 0.3]

def test_to_markdown_renders_header_and_star():
    md = _footage().to_markdown()
    assert "# Footage — 1 clips, 2 windows (1 best)" in md
    assert "## a.mp4" in md and "★" in md
    assert "| start | dur | shot | people | motion | shake | score | best | description |" in md
```

- [x] **Step 2: Run — expect fail** (`ImportError: cannot import name 'Footage'`)

- [x] **Step 3: Implement** (append)

```python
@dataclass
class Footage:
    clips: list[FootageClip] = field(default_factory=list)

    def __post_init__(self) -> None:
        for k, c in enumerate(self.clips):
            if not isinstance(c, FootageClip):
                raise ValueError(f"Footage.clips[{k}] must be a FootageClip")

    @classmethod
    def from_dict(cls, d: dict) -> "Footage":
        clips_in = d.get("clips", [])
        if not isinstance(clips_in, list):
            raise ValueError("Footage.from_dict: 'clips' must be a list")
        clips = []
        for k, c in enumerate(clips_in):
            if not isinstance(c, dict):
                raise ValueError(f"Footage.from_dict: clips[{k}] must be an object")
            clips.append(FootageClip.from_dict(c))
        return cls(clips=clips)

    @classmethod
    def from_json(cls, path: str | Path) -> "Footage":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON ({e}) — fix the FOOTAGE syntax") from e
        return cls.from_dict(d)

    def to_dict(self) -> dict:
        return {"clips": [c.to_dict() for c in self.clips]}

    def ranked_windows(self) -> list[tuple["FootageClip", "FootageWindow"]]:
        pairs = [(c, w) for c in self.clips for w in c.windows]
        return sorted(pairs, key=lambda cw: cw[1].score, reverse=True)

    def to_markdown(self) -> str:
        wins = [w for c in self.clips for w in c.windows]
        n_best = sum(1 for w in wins if w.best)
        lines = [f"# Footage — {len(self.clips)} clips, {len(wins)} windows ({n_best} best)", ""]
        for c in self.clips:
            flag = " · shaky" if c.shaky else ""
            lines.append(f"## {c.source}  ({c.dur:.1f}s · {c.res[0]}×{c.res[1]} @{c.fps:g}{flag})")
            if c.scene_cuts:
                lines.append("scene cuts: " + ", ".join(f"{t:.2f}" for t in c.scene_cuts))
            lines.append("| start | dur | shot | people | motion | shake | score | best | description |")
            lines.append("|-------|-----|------|--------|--------|-------|-------|:----:|-------------|")
            for w in c.windows:
                star = "★" if w.best else ""
                lines.append(f"| {w.start:.2f} | {w.dur:.2f} | {w.shot_type} | {w.people} | "
                             f"{w.motion:.2f} | {w.shake:.2f} | {w.score:.2f} | {star} | {w.description} |")
            lines.append("")
        return "\n".join(lines)
```

- [x] **Step 4: Run — expect pass**

- [x] **Step 5: Commit** (`git commit -m "feat: footage.Footage + to_markdown/ranked_windows (5.2)"`)

---

## Task 4: `footage.CastMember` + `Cast`

**Files:** Modify `scripts/lib/footage.py`; Test `tests/lib/test_footage.py`

- [x] **Step 1: Write the failing test**

```python
# tests/lib/test_footage.py  (add)
from scripts.lib.footage import CastMember, Cast

def test_cast_roundtrips():
    c = Cast(members=[CastMember(name="Lena", descriptor=[0.5, 0.5], notes="red jacket",
                                 ref_crops=["crops/lena_0.png"])])
    assert Cast.from_dict(c.to_dict()).to_dict() == c.to_dict()

@pytest.mark.parametrize("kw,msg", [
    (dict(name=""), "name"), (dict(descriptor=[]), "descriptor"),
    (dict(descriptor=["x"]), "descriptor"),
])
def test_castmember_rejects_bad(kw, msg):
    d = dict(name="Lena", descriptor=[0.5, 0.5]); d.update(kw)
    with pytest.raises(ValueError, match=msg):
        CastMember(**d)
```

- [x] **Step 2: Run — expect fail**

- [x] **Step 3: Implement** (append)

```python
@dataclass
class CastMember:
    name: str
    descriptor: list[float]
    notes: str = ""
    ref_crops: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not (isinstance(self.name, str) and self.name):
            raise ValueError("CastMember.name must be a non-empty string")
        if not (isinstance(self.descriptor, list) and self.descriptor
                and all(_num(v) for v in self.descriptor)):
            raise ValueError("CastMember.descriptor must be a non-empty list of numbers (color histogram)")
        if not isinstance(self.notes, str):
            raise ValueError("CastMember.notes must be a string")
        if not (isinstance(self.ref_crops, list) and all(isinstance(p, str) for p in self.ref_crops)):
            raise ValueError("CastMember.ref_crops must be a list of path strings")
        self.descriptor = [float(v) for v in self.descriptor]

    def to_dict(self) -> dict:
        return {"name": self.name, "descriptor": self.descriptor,
                "notes": self.notes, "ref_crops": self.ref_crops}


@dataclass
class Cast:
    members: list[CastMember] = field(default_factory=list)

    def __post_init__(self) -> None:
        for k, m in enumerate(self.members):
            if not isinstance(m, CastMember):
                raise ValueError(f"Cast.members[{k}] must be a CastMember")

    @classmethod
    def from_dict(cls, d: dict) -> "Cast":
        ms_in = d.get("members", [])
        if not isinstance(ms_in, list):
            raise ValueError("Cast.from_dict: 'members' must be a list")
        ms = []
        for k, m in enumerate(ms_in):
            if not isinstance(m, dict):
                raise ValueError(f"Cast.from_dict: members[{k}] must be an object")
            try:
                ms.append(CastMember(**m))
            except TypeError as ex:
                raise ValueError(f"Cast.from_dict: members[{k}] has a missing or unknown field — {ex}") from ex
        return cls(members=ms)

    @classmethod
    def from_json(cls, path: str | Path) -> "Cast":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON ({e}) — fix the cast syntax") from e
        return cls.from_dict(d)

    def to_dict(self) -> dict:
        return {"members": [m.to_dict() for m in self.members]}
```

- [x] **Step 4: Run — expect pass** (`.venv/bin/python -m pytest tests/lib/test_footage.py -q`)

- [x] **Step 5: Commit** (`git commit -m "feat: footage.CastMember/Cast config-spec + cast.json round-trip (5.2)"`)

---

## Task 5: intake constants + `shot_type` + `_require_vidstab`

**Files:** Create `scripts/intake.py`; Test `tests/lib/test_intake.py`

- [x] **Step 1: Write the failing test**

```python
# tests/lib/test_intake.py
import types
import pytest
from scripts import intake

def test_shot_type_buckets():
    res = (1000, 1000)
    assert intake.shot_type((500, 500, 700, 700), res) == "close"    # area 0.49 > CLOSE_AREA
    assert intake.shot_type((500, 500, 300, 300), res) == "medium"   # area 0.09 in [0.08, 0.30)
    assert intake.shot_type((500, 500, 100, 100), res) == "wide"     # area 0.01 < MEDIUM_AREA
    assert intake.shot_type(None, res) == "wide"

def test_require_vidstab_raises_when_absent(monkeypatch):
    monkeypatch.setattr(intake.proc, "run",
                        lambda *a, **k: types.SimpleNamespace(stdout=b"... scale ... overlay ..."))
    with pytest.raises(ValueError, match="vidstab"):
        intake._require_vidstab()

def test_require_vidstab_ok_when_present(monkeypatch):
    monkeypatch.setattr(intake.proc, "run",
                        lambda *a, **k: types.SimpleNamespace(stdout=b"... vidstabdetect ..."))
    intake._require_vidstab()   # no raise
```

> Note: pick the `medium` fixture so its area lands in `[MEDIUM_AREA, CLOSE_AREA)`. With `MEDIUM_AREA=0.08`, a `(…, 300, 300)` box on a `1000×1000` frame is `0.09` → medium. Adjust the test's box to `(500,500,300,300)`.

- [x] **Step 2: Run — expect fail** (`ModuleNotFoundError: scripts.intake`)

- [x] **Step 3: Implement** — create `scripts/intake.py` with the constants + these two functions:

```python
# scripts/intake.py
"""footage-intake (stage 5.2): scan raw clips → scored candidate windows + cast
registry (design docs/specs/2026-07-12-footage-intake-design.md).

Mechanical CV: probe + PySceneDetect + one YOLO11-seg pass + vidstabdetect +
sub-scene carve + score + phash cull. The interactive hero-naming lives in the
footage-intake SKILL — Python cannot ask a human — this module only surfaces
crops and builds descriptors.
"""
import argparse, json, re, statistics, tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from scripts import check_reel                    # reuse _phash_bits / _hamming for cull
from scripts.lib import assembly, footage, proc
from scripts.track import MODEL                    # reuse the tracker's model choice

SAMPLE_FPS = 3.0
WIN_MIN, WIN_MAX, WIN_TARGET = 1.2, 4.0, 2.5      # seconds — the episode length band
W_PRESENT, W_MOTION, W_STABLE, W_DUR = 0.40, 0.25, 0.25, 0.10
MOTION_GAIN = 10.0                                # scales mean per-sample centre displacement to [0,1]
MOTION_PEAK = 0.35                                # motion value scored highest (triangular)
DEDUP_DIST = 8                                    # phash Hamming below which two windows are duplicates
BEST_FLOOR = 0.50
SHAKY_CLIP = 0.02                                 # shake (fraction of frame width) above which a clip is shaky — tune on real footage
CLOSE_AREA, MEDIUM_AREA = 0.30, 0.08
CAST_DEDUP = 0.30                                 # L1 descriptor distance below which two tracks are the same identity
_HIST_BINS = 8
_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi"}


def shot_type(bbox, res: tuple[int, int]) -> str:
    """close/medium/wide from the primary person's bbox area fraction. None → wide (scenery)."""
    if bbox is None:
        return "wide"
    _, _, bw, bh = bbox
    w, h = res
    area = (bw * bh) / float(w * h) if w and h else 0.0
    if area > CLOSE_AREA:
        return "close"
    if area >= MEDIUM_AREA:
        return "medium"
    return "wide"


def _require_vidstab() -> None:
    """Intake is the repo's first runtime vidstab consumer — fail loud with the remedy."""
    r = proc.run(["ffmpeg", "-hide_banner", "-filters"])
    if b"vidstabdetect" not in r.stdout:
        raise ValueError("footage-intake needs a vidstab-enabled ffmpeg (vidstabdetect filter missing) — "
                         "run `bash setup.sh --with-vidstab`")
```

- [x] **Step 4: Run — expect pass** (`.venv/bin/python -m pytest tests/lib/test_intake.py -q`)

- [x] **Step 5: Commit** (`git commit -m "feat: intake constants + shot_type + vidstab preflight (5.2)"`)

---

## Task 6: `carve_windows`

**Files:** Modify `scripts/intake.py`; Test `tests/lib/test_intake.py`

- [x] **Step 1: Write the failing test**

```python
# tests/lib/test_intake.py  (add)
def _line(n_from_to):   # helper: build a timeline [(t, people, bbox)] at 1s steps
    return [(float(t), n, (500, 500, 200, 300) if n else None) for t, n in n_from_to]

def test_carve_long_take_splits_by_length():
    # one 8s take, person present throughout, NO scene cuts → several windows in the band
    tl = _line([(t, 1) for t in range(9)])
    spans = intake.carve_windows([], tl, 8.0)
    assert len(spans) >= 2
    assert all(intake.WIN_MIN <= d <= intake.WIN_MAX + 1e-6 for _, d in spans)
    assert abs(sum(d for _, d in spans) - 8.0) < 1e-6      # cover the take, no gaps

def test_carve_splits_on_presence_transition():
    # empty 0–3, person 3–6 → boundary at 3
    tl = _line([(0, 0), (1, 0), (2, 0), (3, 1), (4, 1), (5, 1)])
    spans = intake.carve_windows([], tl, 6.0)
    assert any(abs(s - 3.0) < 1e-6 for s, _ in spans)

def test_carve_short_clip_yields_one_window():
    spans = intake.carve_windows([], _line([(0, 1)]), 0.8)   # < WIN_MIN
    assert spans == [(0.0, 0.8)]
```

- [x] **Step 2: Run — expect fail** (`AttributeError: … 'carve_windows'`)

- [x] **Step 3: Implement** (append)

```python
def carve_windows(scene_cuts: list[float], timeline: list, dur: float) -> list[tuple[float, float]]:
    """scene_cuts ∪ presence-transitions, length-capped into [WIN_MIN, WIN_MAX].
    timeline: sorted [(t, people, primary_bbox)]. Scenes alone do NOT split a long
    single take (MVI_3739 = 1 ride → 3 windows), so carve within a scene by
    people-presence + length. A clip shorter than WIN_MIN yields ONE window
    (never zero)."""
    bounds = {0.0, float(dur)}
    for t in scene_cuts:
        if 0.0 < t < dur:
            bounds.add(float(t))
    prev = None
    for t, n, _ in timeline:
        present = n > 0
        if prev is not None and present != prev and 0.0 < t < dur:
            bounds.add(float(t))
        prev = present
    edges = sorted(bounds)
    spans: list[tuple[float, float]] = []
    for a, b in zip(edges, edges[1:]):
        spans.extend(_split_span(a, b))
    if not spans:
        spans = [(0.0, float(dur))]
    return spans


def _split_span(a: float, b: float) -> list[tuple[float, float]]:
    length = b - a
    if length < WIN_MIN:
        return []
    if length <= WIN_MAX:
        return [(a, length)]
    n = max(1, round(length / WIN_TARGET))
    chunk = length / n
    return [(a + i * chunk, chunk) for i in range(n)]
```

- [x] **Step 4: Run — expect pass**

- [x] **Step 5: Commit** (`git commit -m "feat: intake.carve_windows — sub-scene carving (5.2)"`)

---

## Task 7: `score_window` + factor helpers + `_describe`

**Files:** Modify `scripts/intake.py`; Test `tests/lib/test_intake.py`

- [x] **Step 1: Write the failing test**

```python
# tests/lib/test_intake.py  (add)
def test_score_rises_with_presence():
    lo = intake.score_window(present=0.0, motion=0.35, shake=0.0, dur=intake.WIN_TARGET)
    hi = intake.score_window(present=1.0, motion=0.35, shake=0.0, dur=intake.WIN_TARGET)
    assert hi > lo

def test_score_penalises_shake():
    steady = intake.score_window(present=1.0, motion=0.35, shake=0.0, dur=intake.WIN_TARGET)
    shaky = intake.score_window(present=1.0, motion=0.35, shake=intake.SHAKY_CLIP, dur=intake.WIN_TARGET)
    assert steady > shaky

def test_motion_fit_peaks_in_the_middle():
    assert intake._motion_fit(intake.MOTION_PEAK) > intake._motion_fit(0.0)
    assert intake._motion_fit(intake.MOTION_PEAK) > intake._motion_fit(1.0)

def test_dur_fit_peaks_at_target():
    assert intake._dur_fit(intake.WIN_TARGET) > intake._dur_fit(intake.WIN_MIN + 0.01)
    assert intake._dur_fit(intake.WIN_TARGET) > intake._dur_fit(intake.WIN_MAX - 0.01)

def test_describe():
    assert intake._describe(1, "medium", 0.5) == "1 person, medium, dynamic"
    assert intake._describe(0, "wide", 0.1) == "no people, wide, calm"
```

- [x] **Step 2: Run — expect fail**

- [x] **Step 3: Implement** (append)

```python
def _motion_fit(m: float) -> float:
    """Triangular: 0 at static, 1 at MOTION_PEAK, decaying to 0 at chaotic (1.0)."""
    if m <= MOTION_PEAK:
        return m / MOTION_PEAK if MOTION_PEAK else 0.0
    return max(0.0, (1.0 - m) / (1.0 - MOTION_PEAK))


def _dur_fit(d: float) -> float:
    """1 at WIN_TARGET, falling toward WIN_MIN / WIN_MAX, 0 outside the band."""
    if d < WIN_MIN or d > WIN_MAX:
        return 0.0
    if d <= WIN_TARGET:
        return (d - WIN_MIN) / (WIN_TARGET - WIN_MIN)
    return (WIN_MAX - d) / (WIN_MAX - WIN_TARGET)


def score_window(present: float, motion: float, shake: float, dur: float) -> float:
    """Blend the four factors → [0, 1]. Pure math; each factor is tested in isolation."""
    stability = 1.0 - min(1.0, shake / SHAKY_CLIP)
    s = (W_PRESENT * present + W_MOTION * _motion_fit(motion)
         + W_STABLE * stability + W_DUR * _dur_fit(dur))
    return float(min(1.0, max(0.0, s)))


def _describe(people: int, shot: str, motion: float) -> str:
    who = "no people" if people == 0 else ("1 person" if people == 1 else f"{people} people")
    dyn = "dynamic" if motion >= MOTION_PEAK else "calm"
    return f"{who}, {shot}, {dyn}"
```

- [x] **Step 4: Run — expect pass**

- [x] **Step 5: Commit** (`git commit -m "feat: intake scoring — present/motion/stability/dur blend (5.2)"`)

---

## Task 8: shake — `_parse_trf` + `_windowed_shake` + `shake_by_window`

**Files:** Modify `scripts/intake.py`; Test `tests/lib/test_intake.py`

- [x] **Step 1: Write the failing test**

```python
# tests/lib/test_intake.py  (add)
_TRF = "\n".join([
    "VID.STAB 1",
    "Frame 1 (List 0 [])",
    "Frame 2 (List 2 [(LM 3 4 100 100 0.5 0.9) (LM 6 8 200 200 0.5 0.9)])",  # mags 5, 10 → median 10
    "Frame 3 (List 1 [(LM 0 0 100 100 0.5 0.9)])",                            # mag 0
])

def test_parse_trf_median_magnitudes():
    mags = intake._parse_trf(_TRF)
    assert mags == [0.0, 10.0, 0.0]

def test_parse_trf_bad_header_raises():
    with pytest.raises(ValueError, match="unrecognized header"):
        intake._parse_trf("not a vidstab file\nFrame 1 (List 0 [])")

def test_windowed_shake_averages_and_normalises():
    # fps=1 → frame i at second i; window 1–3s covers frames [1,3) = mags[1:3] = [10, 0] → avg 5 / width 1000
    mags = [0.0, 10.0, 0.0, 0.0]
    out = intake._windowed_shake(mags, [(1.0, 2.0)], fps=1.0, w=1000)
    assert out == [5.0 / 1000]
```

- [x] **Step 2: Run — expect fail**

- [x] **Step 3: Implement** (append)

```python
_LM_RE = re.compile(r"\(LM\s+(-?\d+)\s+(-?\d+)")


def _parse_trf(text: str) -> list[float]:
    """Per-frame shake magnitude (median localmotion vector length, px) from a
    libvidstab VID.STAB transforms file. Fail loud on an unrecognized header —
    never a silent shake=0 (the format is libvidstab-version dependent)."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("VID.STAB"):
        raise ValueError("vidstabdetect .trf has an unrecognized header — libvidstab version mismatch? "
                         "cannot trust the shake estimate (run `bash setup.sh --with-vidstab`)")
    mags: list[float] = []
    for line in lines[1:]:
        if not line.startswith("Frame"):
            continue
        lms = _LM_RE.findall(line)
        if lms:
            vecs = sorted((int(x) ** 2 + int(y) ** 2) ** 0.5 for x, y in lms)
            mags.append(vecs[len(vecs) // 2])          # median localmotion magnitude
        else:
            mags.append(0.0)
    return mags


def _windowed_shake(mags: list[float], windows: list[tuple[float, float]], fps: float, w: int) -> list[float]:
    out = []
    for a, d in windows:
        f0, f1 = int(a * fps), int((a + d) * fps)
        seg = mags[f0:f1] or [0.0]
        out.append((sum(seg) / len(seg)) / (w or 1))   # fraction of frame width
    return out


def shake_by_window(clip: str, windows: list[tuple[float, float]], fps: float, res: tuple[int, int]) -> list[float]:
    """vidstabdetect once per clip → per-frame magnitudes → averaged per window,
    normalized by frame width. No per-window cutting → no -ss seek landmine."""
    _require_vidstab()
    with tempfile.TemporaryDirectory() as d:
        trf = str(Path(d) / "t.trf")
        proc.run(["ffmpeg", "-y", "-i", clip, "-vf", f"vidstabdetect=result={trf}", "-f", "null", "-"])
        mags = _parse_trf(Path(trf).read_text())
    return _windowed_shake(mags, windows, fps, res[0])
```

- [x] **Step 4: Run — expect pass**

- [x] **Step 5: Commit** (`git commit -m "feat: intake shake — vidstabdetect .trf parse + per-window aggregate (5.2)"`)

---

## Task 9: YOLO-seg pass — `_iter_seg` + `_people_timeline`

**Files:** Modify `scripts/intake.py`; Test `tests/lib/test_intake.py`

- [x] **Step 1: Write the failing test** (mirror `test_track.py`'s `_FakeBox`, add masks)

```python
# tests/lib/test_intake.py  (add)
class _FakeBox:
    def __init__(self, xywh, tid, conf=0.9):
        self.xywh = [xywh]; self.id = [tid]; self.cls = [0]; self.conf = [conf]

class _FakeRes:
    def __init__(self, boxes):
        self.boxes = boxes

def test_people_timeline_samples_and_counts(monkeypatch):
    # 6 frames @ fps 6, SAMPLE_FPS 3 → step 2 → sample frames 0,2,4. subject slides right.
    frames = [_FakeRes([_FakeBox([300 + i * 40, 500, 200, 300], 1)]) for i in range(6)]
    monkeypatch.setattr(intake, "_iter_seg", lambda src, **k: iter(enumerate(frames)))
    tl, crops = intake._people_timeline("x.mp4", fps=6.0, res=(1920, 1080))
    assert [n for _, n, _ in tl] == [1, 1, 1]         # one person each sampled frame
    assert tl[0][0] == 0.0 and abs(tl[1][0] - 2/6) < 1e-6
    assert tl[0][2][2] == 200                          # primary bbox width threaded through
    # crops stay empty here: the fakes carry no orig_img, so there is nothing to retain.
    # crop/mask retention runs only on real bytes (build_descriptor covers the pixel math).
```

- [x] **Step 2: Run — expect fail**

- [x] **Step 3: Implement** (append)

```python
def _iter_seg(src: str, model_path: str = MODEL):
    """Mirror track.py's YOLO+ByteTrack config but keep masks (track omits them
    for speed). Yields (frame_index, ultralytics_result)."""
    from ultralytics import YOLO
    model = YOLO(model_path)
    for i, res in enumerate(model.track(src, stream=True, persist=True, classes=[0],
                                        tracker="bytetrack.yaml", imgsz=960, verbose=False)):
        yield i, res


def _people_timeline(src: str, fps: float, res: tuple[int, int]):
    """One seg pass → (timeline, crops_by_track).
    timeline: [(t, people, primary_bbox)] sampled at ~SAMPLE_FPS (primary = largest bbox).
    crops_by_track: {tid: (conf, crop_rgb, mask)} best crop per track id, for the cast pass."""
    step = max(1, round(fps / SAMPLE_FPS))
    timeline, crops = [], {}
    for i, r in _iter_seg(src):
        boxes = list(r.boxes) if getattr(r, "boxes", None) is not None else []
        for j, b in enumerate(boxes):
            tid = int(b.id[0]) if getattr(b, "id", None) is not None else None
            conf = float(b.conf[0]) if getattr(b, "conf", None) is not None else 1.0
            if tid is not None and conf > crops.get(tid, (-1.0,))[0]:
                crop_rgb, mask = _crop_and_mask(r, j, b)
                if crop_rgb is not None:
                    crops[tid] = (conf, crop_rgb, mask)
        if i % step:
            continue
        bbs = [tuple(float(v) for v in b.xywh[0]) for b in boxes]
        primary = max(bbs, key=lambda bb: bb[2] * bb[3]) if bbs else None
        timeline.append((i / fps, len(bbs), primary))
    return timeline, crops


def _crop_and_mask(res, idx: int, box):
    """Extract the box's crop (RGB) + seg mask from an ultralytics result. Returns
    (None, None) when the frame image or masks are unavailable (mocked tests)."""
    img = getattr(res, "orig_img", None)
    if img is None:
        return None, None
    arr = np.asarray(img)[..., ::-1]                       # ultralytics orig_img is BGR → RGB
    x, y, w, h = (float(v) for v in box.xywh[0])
    l, t, r_, b_ = int(x - w / 2), int(y - h / 2), int(x + w / 2), int(y + h / 2)
    l, t = max(0, l), max(0, t)
    crop = arr[t:b_, l:r_]
    mask = None
    masks = getattr(res, "masks", None)
    if masks is not None and getattr(masks, "data", None) is not None:
        m = np.asarray(masks.data[idx])                    # (H, W) in model space
        m = np.asarray(Image.fromarray((m * 255).astype("uint8")).resize((arr.shape[1], arr.shape[0])))
        mask = m[t:b_, l:r_]
    return (crop if crop.size else None), mask
```

> Scope: the mocked unit test pins the timeline (sampling cadence, people counts, primary-bbox threading). The crop/mask *pixel* path (`_crop_and_mask`: BGR→RGB, bbox slice, mask resize) is thin ffmpeg/ultralytics glue — left to the real golden (Task 13) and to `build_descriptor`'s direct pixel tests (Task 11); with `orig_img` absent the fakes retain nothing, which is correct.

- [x] **Step 4: Run — expect pass** (`.venv/bin/python -m pytest tests/lib/test_intake.py -q`)

- [x] **Step 5: Commit** (`git commit -m "feat: intake YOLO11-seg pass — people timeline + per-track crops (5.2)"`)

---

## Task 10: `cull` + `_phash_at`

**Files:** Modify `scripts/intake.py`; Test `tests/lib/test_intake.py`

- [x] **Step 1: Write the failing test**

```python
# tests/lib/test_intake.py  (add)
import imagehash
from PIL import Image as _Img
from scripts.lib.footage import Footage, FootageClip, FootageWindow

def _h(hexstr):   # build an ImageHash from a known 8x8 bit pattern via a solid image
    return imagehash.average_hash(_Img.new("L", (8, 8), 0))   # all-zero hash; tweak per test

def test_cull_marks_best_and_drops_duplicates():
    w_hi = FootageWindow(start=0, dur=2, shot_type="m", people=1, motion=0.4, shake=0.0, score=0.9)
    w_dup = FootageWindow(start=5, dur=2, shot_type="m", people=1, motion=0.4, shake=0.0, score=0.7)
    w_far = FootageWindow(start=9, dur=2, shot_type="m", people=1, motion=0.4, shake=0.0, score=0.6)
    clip = FootageClip(source="a.mp4", dur=20, res=(1920, 1080), fps=30,
                       windows=[w_hi, w_dup, w_far])
    # phash: w_hi and w_dup identical (distance 0 < DEDUP_DIST) → w_dup dropped from best;
    # w_far distinct.
    hashes = {id(w_hi): _h("a"), id(w_dup): _h("a"), id(w_far): imagehash.average_hash(_Img.new("L", (8, 8), 255))}
    intake.cull([clip], phash_of=lambda c, w: hashes[id(w)])
    assert w_hi.best is True         # top score, survives
    assert w_dup.best is False       # duplicate of w_hi
    assert w_far.best is True        # distinct, above floor

def test_cull_low_score_not_best():
    w = FootageWindow(start=0, dur=2, shot_type="m", people=0, motion=0.1, shake=0.0, score=0.2)
    clip = FootageClip(source="a.mp4", dur=5, res=(100, 100), fps=30, windows=[w])
    intake.cull([clip], phash_of=lambda c, w: imagehash.average_hash(_Img.new("L", (8, 8), 0)))
    assert w.best is False           # below BEST_FLOOR even though unique
```

- [x] **Step 2: Run — expect fail**

- [x] **Step 3: Implement** (append)

```python
def _phash_at(clip: str, t: float):
    return check_reel._phash_bits(clip, t)             # reuse the reel-variety phash


def cull(clips: list, phash_of) -> None:
    """Rank all windows by score; a window whose phash Hamming distance to an
    already-kept higher-scored window is < DEDUP_DIST is a duplicate (compare by
    IMAGE, never by filename — several windows of one clip are legitimate). Mark
    best on dedup survivors with score >= BEST_FLOOR. Mutates FootageWindow.best.
    phash_of(clip, window) -> imagehash.ImageHash (injected; the driver closes it
    over footage_root)."""
    ranked = sorted(((c, w) for c in clips for w in c.windows),
                    key=lambda cw: cw[1].score, reverse=True)
    kept: list = []
    for c, w in ranked:
        h = phash_of(c, w)
        dup = any(check_reel._hamming(h, kh) < DEDUP_DIST for kh in kept)
        w.best = (not dup) and w.score >= BEST_FLOOR
        if not dup:
            kept.append(h)
```

- [x] **Step 4: Run — expect pass**

- [x] **Step 5: Commit** (`git commit -m "feat: intake.cull — phash dedup + best marking (5.2)"`)

---

## Task 11: cast helpers — `build_descriptor` + `surface_crops` + `write_cast`

**Files:** Modify `scripts/intake.py`; Test `tests/lib/test_intake.py`

- [x] **Step 1: Write the failing test**

```python
# tests/lib/test_intake.py  (add)
def test_build_descriptor_normalised_and_masked():
    crop = np.zeros((10, 10, 3), dtype="uint8"); crop[:, :, 0] = 255   # pure red
    mask = np.ones((10, 10), dtype="uint8")
    d = intake.build_descriptor(crop, mask)
    assert len(d) == 3 * intake._HIST_BINS
    assert abs(sum(d) - 1.0) < 1e-6                    # L1-normalized
    assert d[intake._HIST_BINS - 1] > 0               # red maxed → top R bin populated

def test_surface_crops_dedups_identities():
    red = (np.zeros((8, 8, 3), "uint8"), np.ones((8, 8), "uint8")); red[0][:, :, 0] = 255
    red2 = (red[0].copy(), red[1].copy())
    blue = (np.zeros((8, 8, 3), "uint8"), np.ones((8, 8), "uint8")); blue[0][:, :, 2] = 255
    crops = {1: (0.9, *red), 2: (0.8, *red2), 3: (0.7, *blue)}
    picked = intake.surface_crops(crops, top_n=8)
    assert len(picked) == 2                            # the two reds collapse to one identity

def test_write_cast_writes_json(tmp_path):
    crop = np.zeros((8, 8, 3), "uint8"); crop[:, :, 1] = 255
    cast = intake.write_cast([("Lena", "green", [(crop, np.ones((8, 8), "uint8"))])], str(tmp_path))
    assert (tmp_path / "cast.json").exists()
    assert cast.members[0].name == "Lena"
    assert (tmp_path / "cast_crops" / "Lena_0.png").exists()
```

- [x] **Step 2: Run — expect fail**

- [x] **Step 3: Implement** (append)

```python
def build_descriptor(crop_rgb, mask) -> list[float]:
    """L1-normalized color histogram over the segmentation-mask pixels only
    (clothing/gear — background removed; §6.1a). numpy + Pillow, no cv2."""
    px = crop_rgb[mask > 0] if mask is not None else crop_rgb.reshape(-1, 3)
    if px.size == 0:
        px = crop_rgb.reshape(-1, 3)
    hist: list[float] = []
    for c in range(3):
        h, _ = np.histogram(px[:, c], bins=_HIST_BINS, range=(0, 255))
        hist.extend(h.tolist())
    total = float(sum(hist)) or 1.0
    return [v / total for v in hist]


def _descriptor_dist(a: list[float], b: list[float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b))


def surface_crops(crops_by_track: dict, top_n: int = 8) -> list:
    """Cluster retained per-track crops by descriptor similarity → top_n distinct
    identities (highest confidence first). Returns [(tid, conf, crop_rgb, mask, descriptor)]."""
    items = []
    for tid, (conf, crop_rgb, mask) in crops_by_track.items():
        if crop_rgb is None:
            continue
        items.append((tid, conf, crop_rgb, mask, build_descriptor(crop_rgb, mask)))
    items.sort(key=lambda it: it[1], reverse=True)
    picked: list = []
    for it in items:
        if all(_descriptor_dist(it[4], p[4]) > CAST_DEDUP for p in picked):
            picked.append(it)
        if len(picked) >= top_n:
            break
    return picked


def write_cast(named: list, out_dir: str):
    """named: [(name, notes, [(crop_rgb, mask), ...])]. Averages 1–3 reference
    descriptors, saves ref crop PNGs under out_dir/cast_crops/, writes cast.json."""
    crop_dir = Path(out_dir) / "cast_crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    members = []
    for name, notes, refs in named:
        descs, paths = [], []
        for j, (crop_rgb, mask) in enumerate(refs[:3]):
            descs.append(build_descriptor(crop_rgb, mask))
            p = str(crop_dir / f"{name}_{j}.png")
            Image.fromarray(crop_rgb.astype("uint8")).save(p)
            paths.append(p)
        avg = [sum(col) / len(descs) for col in zip(*descs)]
        members.append(footage.CastMember(name=name, descriptor=avg, notes=notes, ref_crops=paths))
    cast = footage.Cast(members=members)
    (Path(out_dir) / "cast.json").write_text(json.dumps(cast.to_dict(), indent=2))
    return cast
```

- [x] **Step 4: Run — expect pass**

- [x] **Step 5: Commit** (`git commit -m "feat: intake cast — seg-mask descriptor + surface_crops + write_cast (5.2)"`)

---

## Task 12: `intake()` driver + CLI

**Files:** Modify `scripts/intake.py`; Test `tests/lib/test_intake.py`

- [x] **Step 1: Write the failing test** (everything CV mocked — no ffmpeg/YOLO)

```python
# tests/lib/test_intake.py  (add)
def test_intake_builds_footage_and_writes(monkeypatch, tmp_path):
    root = tmp_path / "footage"; root.mkdir()
    (root / "a.mp4").write_bytes(b"x")
    monkeypatch.setattr(intake.assembly, "probe_stream",
                        lambda s: types.SimpleNamespace(w=1920, h=1080, fps=6.0))
    monkeypatch.setattr(intake.assembly, "probe_duration", lambda s: 8.0)
    monkeypatch.setattr(intake, "scene_bounds", lambda s: [])
    tl = [(float(i), 1, (500, 500, 300, 300)) for i in range(9)]
    monkeypatch.setattr(intake, "_people_timeline", lambda s, fps, res: (tl, {}))
    monkeypatch.setattr(intake, "shake_by_window",
                        lambda clip, spans, fps, res: [0.0 for _ in spans])
    import imagehash
    from PIL import Image as I
    monkeypatch.setattr(intake, "_phash_at",
                        lambda clip, t: imagehash.average_hash(I.new("L", (8, 8), int(t) % 256)))
    out = tmp_path / "out"
    result = intake.intake(str(root), str(out))
    assert (out / "FOOTAGE.json").exists() and (out / "FOOTAGE.md").exists()
    assert len(result.clips) == 1 and result.clips[0].source == "a.mp4"
    assert result.clips[0].windows                       # carved ≥1 window
    assert any(w.best for w in result.clips[0].windows)  # cull marked best
```

- [x] **Step 2: Run — expect fail** (`AttributeError: … 'intake'`)

- [x] **Step 3: Implement** (append)

```python
def scene_bounds(src: str) -> list[float]:
    """PySceneDetect ContentDetector → scene boundary timestamps (seconds). A
    continuous take returns [] (handled by carving)."""
    from scenedetect import detect, ContentDetector
    scenes = detect(src, ContentDetector())
    return [s[0].get_seconds() for s in scenes[1:]]      # boundaries = each scene's start bar the first


def _build_window(span, timeline, shake, res):
    a, d = span
    b = a + d
    samples = [(t, n, bb) for (t, n, bb) in timeline if a <= t < b]
    people = max((n for _, n, _ in samples), default=0)
    present = (sum(1 for _, n, _ in samples if n > 0) / len(samples)) if samples else 0.0
    boxes = [bb for _, _, bb in samples if bb is not None]
    primary = max(boxes, key=lambda bb: bb[2] * bb[3]) if boxes else None
    motion = _motion(samples, res)
    shot = shot_type(primary, res)
    score = score_window(present, motion, shake, d)
    return footage.FootageWindow(start=round(a, 3), dur=round(d, 3), shot_type=shot,
                                 people=people, motion=round(motion, 3), shake=round(shake, 4),
                                 description=_describe(people, shot, motion), score=round(score, 3))


def _motion(samples, res) -> float:
    centers = [(t, bb[0]) for (t, n, bb) in samples if bb is not None]
    if len(centers) < 2:
        return 0.0
    w = res[0] or 1
    disps = [abs(centers[i][1] - centers[i - 1][1]) / w for i in range(1, len(centers))]
    return float(min(1.0, (sum(disps) / len(disps)) * MOTION_GAIN))


def intake(footage_root: str, out_dir: str, sample_fps: float = SAMPLE_FPS) -> footage.Footage:
    root = Path(footage_root)
    paths = sorted(p for p in root.iterdir() if p.suffix.lower() in _VIDEO_EXTS)
    clips = []
    for p in paths:
        src = str(p)
        info = assembly.probe_stream(src)
        dur = assembly.probe_duration(src)
        res = (info.w, info.h)
        cuts = scene_bounds(src)
        timeline, _crops = _people_timeline(src, info.fps, res)
        spans = carve_windows(cuts, timeline, dur)
        shakes = shake_by_window(src, spans, info.fps, res)
        windows = [_build_window(sp, timeline, sh, res) for sp, sh in zip(spans, shakes)]
        med = statistics.median([w.shake for w in windows]) if windows else 0.0
        clips.append(footage.FootageClip(source=p.name, dur=dur, res=res, fps=info.fps,
                                         shaky=med > SHAKY_CLIP, scene_cuts=cuts, windows=windows))
    result = footage.Footage(clips=clips)
    cull(result.clips, phash_of=lambda c, w: _phash_at(str(root / c.source), w.start + w.dur / 2))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "FOOTAGE.json").write_text(json.dumps(result.to_dict(), indent=2))
    (out / "FOOTAGE.md").write_text(result.to_markdown())
    return result


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="footage-intake (5.2): scan clips → FOOTAGE.json/.md")
    ap.add_argument("footage_root")
    ap.add_argument("out_dir")
    ap.add_argument("--sample-fps", type=float, default=SAMPLE_FPS)
    a = ap.parse_args(argv)
    f = intake(a.footage_root, a.out_dir, a.sample_fps)
    print(f"{len(f.clips)} clips, {sum(len(c.windows) for c in f.clips)} windows → {a.out_dir}")


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Run — expect pass** (`.venv/bin/python -m pytest tests/lib/test_intake.py -q`)

- [x] **Step 5: Commit** (`git commit -m "feat: intake() driver + CLI — clips → FOOTAGE.json/.md (5.2)"`)

---

## Task 13: Integration golden (real ffmpeg + scenes + vidstab, faked YOLO)

**Files:** Create `tests/integration/test_intake.py`

- [x] **Step 1: Write the test**

```python
# tests/integration/test_intake.py
import shutil
import pytest
from scripts import intake
from scripts.lib import footage

pytestmark = pytest.mark.integration


def _has_vidstab():
    if not shutil.which("ffmpeg"):
        return False
    import subprocess
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True).stdout
    return b"vidstabdetect" in out


@pytest.mark.skipif(not _has_vidstab(), reason="needs vidstab-enabled ffmpeg (setup.sh --with-vidstab)")
def test_intake_wiring_on_real_bytes(monkeypatch, tmp_path, sample_clip):
    # real ffmpeg bytes (sample_clip = a box on a field) + real PySceneDetect + real
    # vidstabdetect; _iter_seg is faked because YOLO returns empty on synthetic footage
    # (design §12, same reason test_front_spine fakes process_episode).
    root = tmp_path / "footage"; root.mkdir()
    shutil.copy(sample_clip, root / "clip.mp4")

    class _FakeBox:
        def __init__(self, xywh, tid): self.xywh = [xywh]; self.id = [tid]; self.cls = [0]; self.conf = [0.9]

    class _FakeRes:
        def __init__(self, boxes): self.boxes = boxes; self.orig_img = None; self.masks = None

    # 3s @ 30fps ≈ 90 frames; subject present throughout, sliding right
    frames = [_FakeRes([_FakeBox([300 + i * 12, 500, 200, 300], 1)]) for i in range(90)]
    monkeypatch.setattr(intake, "_iter_seg", lambda src, **k: iter(enumerate(frames)))

    out = tmp_path / "out"
    result = intake.intake(str(root), str(out))

    assert (out / "FOOTAGE.json").exists() and (out / "FOOTAGE.md").exists()
    footage.Footage.from_json(out / "FOOTAGE.json")           # round-trips
    clip = result.clips[0]
    assert clip.res == (1920, 1080)
    assert len(clip.windows) >= 1
    w = clip.windows[0]
    assert w.shot_type in {"close", "medium", "wide"}
    assert w.shake >= 0.0                                     # vidstabdetect measured + parsed
    assert "# Footage —" in result.to_markdown()
```

- [x] **Step 2: Run** — passes where vidstab is installed, else skips:

Run: `.venv/bin/python -m pytest tests/integration/test_intake.py -v`
Expected: PASS (or SKIP with the vidstab reason).

- [x] **Step 3: Commit** (`git commit -m "test: intake real-ffmpeg golden — wiring on real bytes, faked YOLO (5.2)"`)

---

## Task 14: `SKILLS/footage-intake/SKILL.md`

**Files:** Create `SKILLS/footage-intake/SKILL.md`

- [x] **Step 1: Write the SKILL** (mirror `SKILLS/process-episode/SKILL.md`'s discipline: ask-before-proceeding, stop-and-report, never improvise). Content:

```markdown
---
name: footage-intake
description: Scan raw footage into scored candidate windows (FOOTAGE.json/.md) and, when people matter, an interactive cast.json hero registry. Stage 5.2.
---

# footage-intake (5.2)

Turn a folder of raw clips into what the edit-plan selects from.

## Steps

1. **Ensure env.** Intake needs a vidstab-enabled ffmpeg. If `ffmpeg -filters`
   lacks `vidstabdetect`, run `bash setup.sh --with-vidstab` before continuing.
2. **Scan.** `python -m scripts.intake <footage_root> <out_dir>` →
   `FOOTAGE.json` + `FOOTAGE.md`. Skim the render: every clip logged, windows
   carved and scored, `best` moments starred.
3. **Cast pass (only when people matter to the reel).** Surface the top-N
   distinct person crops (saved under `<out_dir>/cast_crops/`). **Show them to
   the human and ask who each hero is** — any domain (family, athletes, friends,
   a vlogger). Do not invent names; if the human is unsure, leave that identity
   out. Skip the whole step cleanly for scenery / no-people footage.
4. **Write cast.** Record `name → descriptor (+ notes)` into `cast.json`.
5. **Report the gate:** every clip logged · people tagged · windows carved +
   scored · cast named (when applicable). Stop-and-report anything ambiguous —
   never guess a hero identity.

## Boundaries

Intake **ranks and flags**; it does not pick the reel's episodes or their order
(that is 5.7 edit-plan + the episode-choice human loop). It does not choose
music or judge mood. `cast.json` is produced here; wiring hero descriptors into
episode manifests is a later step.
```

- [x] **Step 2: Commit** (`git commit -m "docs: footage-intake SKILL — interactive scan + cast naming (5.2)"`)

---

## Task 15: Docs sync + registry

**Files:** Modify `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`, `docs/specs/2026-07-05-montage-skillset-design.md`

- [x] **Step 1** — `pipeline-map.md`: flip **5.2** `❌ → ✅` (`intake.py`: probe + scenedetect + YOLO-seg + vidstab + carve + score + cull → FOOTAGE.json/.md + cast.json). Update the tally (6 done) and the "Front-half authoring" roadmap bullet (SP2 done; remaining SP1b/SP3/SP4). Note cast.json now produced (hero-pin wiring still pending).

- [x] **Step 2** — `build-status.md`: add a "**footage-intake (5.2) DONE**" entry (branch `feat/footage-intake`, contracts + intake.py + SKILL + golden, test count), and adjust "Next action" (SP1b / SP3 / router / cast-pin wiring).

- [x] **Step 3** — `CLAUDE.md`: add registry rows for the design + plan under the Quick Reference table.

- [x] **Step 4** — montage design `§5.2`: append a "**Built (2026-07-12, SP2)**" note (typed FOOTAGE.json + rendered FOOTAGE.md; vidstabdetect shake; cast.json; carve/score/cull as built). Keep spec ↔ plan in sync.

- [x] **Step 5** — run the full suite green, then commit:

```bash
.venv/bin/python -m pytest -q
git add docs/ CLAUDE.md
git commit -m "docs: sync build-status/pipeline-map/registry for footage-intake (5.2)"
```

---

## Self-review checklist (run before dispatching)

- **Spec coverage:** contracts (§2 → T1–T4), probe/scenes/YOLO/shake/carve/score/cull (§3 → T0, T5–T10, T12), cast (§4 → T11), SKILL (§5 → T14), tests (§6 → all + T13), docs (T15). ✓
- **Type consistency:** `carve_windows`/`_split_span` return `(start, dur)` tuples consumed by `shake_by_window` and `_build_window`; `_people_timeline` returns `(timeline, crops)` consumed by `carve_windows`/`_build_window` and `surface_crops`; `phash_of(clip, window)` signature matches `cull`'s call and the driver's lambda. ✓
- **Reuse:** `assembly.probe_stream`/`probe_duration`, `check_reel._phash_bits`/`_hamming`, `track.MODEL`, `_FakeBox` test idiom. ✓
- **Landmines:** vidstab preflight + skip-if-absent (T5/T8/T13); no `-ss` cut in the shake path (whole-clip vidstabdetect); YOLO faked on synthetic footage (T13). ✓
