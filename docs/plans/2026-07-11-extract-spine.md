# Extract spine (Front-half SP1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a hand-authored `EDL.json` drives the whole conveyor to a delivered `REEL_v1.mp4` — no hand-supplied segments or per-episode manifests.

**Architecture:** a typed `EDL` config-spec (`scripts/lib/edl.py`) + an EDL-driven extract loop with a length gate (`scripts/extract.py`) + a picture-only EDL→manifest bridge + a thin **sequential** driver (`scripts/edl_to_reel.py`) that fans out `process_episode` per episode, assembles a `ReelManifest`, and hands off to the existing `build_reel`. The driver resolves `canvas`/`delivery` once (via `resolve_manifest`) and stores the resolved manifest in each `ReelEpisode`, because `build_reel`'s reprocess re-runs `process_episode` without `project=`.

**Tech Stack:** Python 3, dataclasses (config-spec pattern), ffmpeg/ffprobe via `scripts.lib.proc`, pytest (`pythonpath = .`, scripts-as-modules). Design: [docs/specs/2026-07-11-extract-spine-design.md](../specs/2026-07-11-extract-spine-design.md).

---

## File Structure

- **Create `scripts/lib/edl.py`** — `EDLEpisode` + `EDL` config-specs (validate-and-raise, JSON round-trip) + `to_manifest_dict` bridge. Mirrors `scripts/lib/manifest.py`. One responsibility: the EDL contract + its map onto the episode manifest.
- **Modify `scripts/extract.py`** — keep `extract()` untouched; add `_probe_dur` + `extract_edl(edl, footage_root, seg_dir)` (loop + §5.8 length gate).
- **Create `scripts/edl_to_reel.py`** — the sequential end-to-end driver + CLI.
- **Create `tests/lib/test_edl.py`** — `EDLEpisode`/`EDL`/`to_manifest_dict` unit tests.
- **Modify `tests/integration/test_extract.py`** — real-ffmpeg `extract_edl` loop + gate tests.
- **Create `tests/lib/test_edl_to_reel.py`** — driver unit tests (monkeypatched extract/process_episode/build_reel).
- **Create `tests/integration/test_front_spine.py`** — real-ffmpeg end-to-end golden (fakes only the YOLO-tracking `process_episode` step).
- **Modify** `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`, `docs/specs/2026-07-05-montage-skillset-design.md` (Task 6 docs sync).

Reused unchanged: `extract.extract()`, `process_episode`, `resolve_manifest`, `build_reel`, `ReelManifest`/`ReelEpisode`/`ReelCheckSpec`, `assembly.probe_stream`, `ProjectConfig`, `manifest.Manifest`/`validate`.

---

### Task 0: `EDLEpisode` config-spec

**Files:**
- Create: `scripts/lib/edl.py`
- Test: `tests/lib/test_edl.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/lib/test_edl.py
import pytest
from scripts.lib.edl import EDLEpisode
from scripts.lib.manifest import DEFAULT_COLOR


def _ep(**kw):
    base = dict(source="a.mp4", start=1.0, dur=2.0, shot_type="wide",
                composition="lead", grid="thirds")
    base.update(kw)
    return EDLEpisode(**base)


def test_minimal_episode_defaults():
    e = _ep()
    assert e.source == "a.mp4" and e.start == 1.0 and e.dur == 2.0
    assert e.layout == "fill" and e.crop_aspect is None and e.crop_scale == 1.0
    assert e.color_means == DEFAULT_COLOR and e.beat_slot is None and e.processing_notes == ""


def test_json_arrays_coerce_to_tuples():
    e = _ep(hero=[10, 20, 30, 40], crop_aspect=[9, 16], rect=[0.1, 0.2, 0.8], color_means=[100, 110, 120])
    assert e.hero == (10, 20, 30, 40) and e.crop_aspect == (9, 16)
    assert e.rect == (0.1, 0.2, 0.8) and e.color_means == (100, 110, 120)


@pytest.mark.parametrize("kw, needle", [
    (dict(source=""), "source"),
    (dict(source=None), "source"),
    (dict(start=-0.5), "start"),
    (dict(start=True), "start"),
    (dict(dur=0), "dur"),
    (dict(dur=-1.0), "dur"),
    (dict(dur=True), "dur"),
    (dict(shot_type=""), "shot_type"),
    (dict(composition="zoom"), "composition"),
    (dict(grid="golden"), "grid"),          # golden-canon is editorial, not a tracking grid
    (dict(layout="split"), "layout"),       # split/pan land in their own plans
    (dict(motion="orbit"), "motion"),
    (dict(beat_slot=1.5), "beat_slot"),
    (dict(beat_slot=True), "beat_slot"),    # bool is not an int index
    (dict(color_means=None), "color_means"),
    (dict(color_means=[1, 2]), "color_means"),
    (dict(color_means=[1, 2, 0]), "color_means"),
])
def test_bad_field_raises_valueerror_with_remedy(kw, needle):
    with pytest.raises(ValueError, match=needle):
        _ep(**kw)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -q`
Expected: FAIL — `ModuleNotFoundError: scripts.lib.edl`.

- [ ] **Step 3: Write `scripts/lib/edl.py` (episode only)**

```python
"""EDL contract + the EDL→manifest bridge (design docs/specs/2026-07-11-extract-spine-design.md).

The typed source of truth for the front half's edit decision list. Follows the
hard config-spec pattern — validate-and-raise in `__post_init__`, JSON round-trip —
like `models.py`'s `TrackSpec`/`MusicSpec`. (Distinct from `manifest.py`'s soft
`Manifest` gate, whose `validate()` returns problem strings and never raises.)
The human-facing EDL.md render + interactive authoring are SP3;
this module is what the mechanical extract spine reads. Imports the shared
vocab from models + manifest — manifest never imports edl, so no cycle.
"""
import json
from dataclasses import dataclass
from pathlib import Path

from scripts.lib.manifest import DEFAULT_COLOR, LAYOUTS_SUPPORTED
from scripts.lib.models import COMPOSITIONS, GRIDS, MOTIONS


@dataclass
class EDLEpisode:
    """One ordered edit-decision row: a source window + its picture intent.
    Layout-parameter cross-validation (crop_scale range, rect bounds, fill-vs-
    border) is NOT duplicated here — it has one home, LayoutSpec, reached via the
    manifest gate in the driver's preflight. This validates only what the manifest
    gate cannot see cheaply (source/window/shot_type) plus flat membership."""
    source: str
    start: float
    dur: float
    shot_type: str
    composition: str
    grid: str
    layout: str = "fill"
    crop_aspect: str | tuple[int, int] | None = None   # None → manifest picks canvas/source by layout
    crop_scale: float = 1.0
    rect: tuple[float, float, float] | None = None
    background: str = "blur"
    border_px: int = 0
    border_color: str = "white"
    motion: str | None = None
    hero: tuple | str | None = None
    color_means: tuple = DEFAULT_COLOR
    processing_notes: str = ""       # authoring metadata → SP1b draft labels; not acted on here
    beat_slot: int | None = None     # authoring metadata → B4 pacing; not acted on here

    def __post_init__(self) -> None:
        if not (isinstance(self.source, str) and self.source):
            raise ValueError("EDLEpisode.source must be a non-empty clip path")
        if isinstance(self.start, bool) or not isinstance(self.start, (int, float)) or self.start < 0:
            raise ValueError(f"EDLEpisode.start must be a number >= 0 (seconds), got {self.start!r}")
        if isinstance(self.dur, bool) or not isinstance(self.dur, (int, float)) or self.dur <= 0:
            raise ValueError(f"EDLEpisode.dur must be a positive number (seconds), got {self.dur!r}")
        if not (isinstance(self.shot_type, str) and self.shot_type):
            raise ValueError("EDLEpisode.shot_type must be a non-empty tag (e.g. 'wide', 'close')")
        if self.composition not in COMPOSITIONS:
            raise ValueError(f"EDLEpisode.composition {self.composition!r} unknown — expected {COMPOSITIONS}")
        if self.grid not in GRIDS:
            raise ValueError(f"EDLEpisode.grid {self.grid!r} unknown — expected {GRIDS} "
                             "(golden-canon is a static editorial layer, not a tracking grid)")
        if self.layout not in LAYOUTS_SUPPORTED:
            raise ValueError(f"EDLEpisode.layout {self.layout!r} not supported — {LAYOUTS_SUPPORTED} only; "
                             "split and pan land in their own plans")
        if self.motion is not None and self.motion not in MOTIONS:
            raise ValueError(f"EDLEpisode.motion {self.motion!r} unknown — expected one of {MOTIONS} or null")
        if self.beat_slot is not None and (isinstance(self.beat_slot, bool) or not isinstance(self.beat_slot, int)):
            raise ValueError(f"EDLEpisode.beat_slot must be an int index or null, got {self.beat_slot!r}")
        if not (isinstance(self.color_means, (tuple, list)) and len(self.color_means) == 3
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
                        for v in self.color_means)):
            raise ValueError(f"EDLEpisode.color_means must be 3 positive channel means [R, G, B]; "
                             f"got {self.color_means!r}")
        self.color_means = tuple(self.color_means)
        if isinstance(self.hero, list):
            self.hero = tuple(self.hero)              # JSON arrays → tuple (seed-bbox pin survives)
        if isinstance(self.crop_aspect, list):
            self.crop_aspect = tuple(self.crop_aspect)
        if isinstance(self.rect, list):
            self.rect = tuple(self.rect)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/edl.py tests/lib/test_edl.py
git commit -m "feat: EDLEpisode config-spec (Front-half SP1)"
```

---

### Task 1: `EDL` config-spec + JSON round-trip

**Files:**
- Modify: `scripts/lib/edl.py`
- Test: `tests/lib/test_edl.py`

- [ ] **Step 1: Add the failing tests**

```python
# append to tests/lib/test_edl.py
from scripts.lib.edl import EDL


def _edl(**kw):
    ep = dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
              composition="lead", grid="thirds")
    base = dict(episodes=[ep, {**ep, "start": 2.0}])
    base.update(kw)
    return EDL.from_dict(base)


def test_edl_from_dict_defaults():
    e = _edl()
    assert len(e.episodes) == 2 and all(isinstance(x, EDLEpisode) for x in e.episodes)
    assert e.cap == 3 and e.music is None and e.target_dur is None


def test_edl_reel_level_fields():
    e = _edl(music="MUSIC.json", cap=2, target_dur=8.0)
    assert e.music == "MUSIC.json" and e.cap == 2 and e.target_dur == 8.0


def test_edl_null_cap_defaults_to_three():
    e = _edl(cap=None)
    assert e.cap == 3


@pytest.mark.parametrize("kw, needle", [
    (dict(episodes=[]), "at least one"),
    (dict(cap=0), "cap"),
    (dict(cap=True), "cap"),
    (dict(target_dur=-1.0), "target_dur"),
    (dict(music=""), "music"),
])
def test_edl_bad_reel_field_raises(kw, needle):
    with pytest.raises(ValueError, match=needle):
        _edl(**kw)


def test_edl_episodes_must_be_a_list():
    with pytest.raises(ValueError, match="episodes"):
        EDL.from_dict({"episodes": "nope"})


def test_edl_episode_unknown_field_names_the_key():
    bad = dict(source="a.mp4", start=0.0, dur=2.0, shot_type="w",
               composition="lead", grid="thirds", typo=1)
    with pytest.raises(ValueError, match="episodes\\[0\\]"):
        EDL.from_dict({"episodes": [bad]})


def test_edl_from_json_roundtrip(tmp_path):
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps({"episodes": [dict(source="a.mp4", start=0.0, dur=2.0,
                 shot_type="wide", composition="lead", grid="thirds")], "cap": 2}))
    e = EDL.from_json(str(p))
    assert e.cap == 2 and e.episodes[0].source == "a.mp4"
```

Add `import json` at the top of the test file if not already present.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -q`
Expected: FAIL — `ImportError: cannot import name 'EDL'`.

- [ ] **Step 3: Append `EDL` to `scripts/lib/edl.py`**

```python
@dataclass
class EDL:
    """The ordered edit decision list + reel-level knobs. target_dur=None → the
    reel total is the sum of window durations (the length gate then passes by
    construction; a user-set target that disagrees is a real pacing signal)."""
    episodes: tuple[EDLEpisode, ...]
    music: str | None = None       # MUSIC.json path; None → a silent reel (Phase A.5 path)
    cap: int = 3                   # build_reel reprocess cap
    target_dur: float | None = None

    def __post_init__(self) -> None:
        eps = tuple(self.episodes)
        if not eps:
            raise ValueError("EDL.episodes is empty — an EDL needs at least one episode")
        for k, e in enumerate(eps):
            if not isinstance(e, EDLEpisode):
                raise ValueError(f"EDL.episodes[{k}] must be an EDLEpisode")
        self.episodes = eps
        if isinstance(self.cap, bool) or not isinstance(self.cap, int) or self.cap < 1:
            raise ValueError(f"EDL.cap must be an int >= 1, got {self.cap!r}")
        if self.music is not None and not (isinstance(self.music, str) and self.music):
            raise ValueError("EDL.music must be a MUSIC.json path or null, got an empty/non-str value")
        if self.target_dur is not None and (isinstance(self.target_dur, bool)
                or not isinstance(self.target_dur, (int, float)) or self.target_dur <= 0):
            raise ValueError(f"EDL.target_dur must be a positive number or null, got {self.target_dur!r}")

    @classmethod
    def from_dict(cls, d: dict) -> "EDL":
        eps_in = d.get("episodes")
        if not isinstance(eps_in, list):
            raise ValueError("EDL.from_dict: 'episodes' must be a list of episode objects")
        eps = []
        for k, e in enumerate(eps_in):
            if not isinstance(e, dict):
                raise ValueError(f"EDL.from_dict: episodes[{k}] must be an object, got {type(e).__name__}")
            try:
                eps.append(EDLEpisode(**e))       # missing-required / unknown key → TypeError → remedy below
            except TypeError as ex:
                raise ValueError(f"EDL.from_dict: episodes[{k}] has a missing or unknown field — {ex}") from ex
        cap = d.get("cap")
        return cls(episodes=tuple(eps), music=d.get("music"),
                   cap=cap if cap is not None else 3, target_dur=d.get("target_dur"))

    @classmethod
    def from_json(cls, path: str | Path) -> "EDL":
        return cls.from_dict(json.loads(Path(path).read_text()))
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/edl.py tests/lib/test_edl.py
git commit -m "feat: EDL config-spec + JSON round-trip (Front-half SP1)"
```

---

### Task 2: `to_manifest_dict` bridge

**Files:**
- Modify: `scripts/lib/edl.py`
- Test: `tests/lib/test_edl.py`

- [ ] **Step 1: Add the failing tests** — the bridge output, merged with a project canvas, must pass the real manifest gate clean and carry no EDL-only keys.

```python
# append to tests/lib/test_edl.py
from scripts.lib.edl import to_manifest_dict
from scripts.lib import manifest as manifest_lib


def test_bridge_produces_a_valid_manifest():
    ep = _ep(composition="lead", grid="thirds", layout="fill", crop_scale=0.8)
    md = to_manifest_dict(ep, segment="segments/ep0_raw.mp4", out_path="out/ep0.mp4")
    md["canvas"] = [1080, 1920]                   # the driver injects this via resolve_manifest
    m = manifest_lib.Manifest.from_dict(md)       # would raise on an unknown key or a bad field
    assert manifest_lib.validate(m) == []
    assert m.segment == "segments/ep0_raw.mp4" and m.out_path == "out/ep0.mp4"
    assert m.target_dur == ep.dur and m.crop_scale == 0.8


def test_bridge_omits_canvas_delivery_and_edl_only_fields():
    ep = _ep(shot_type="wide", processing_notes="stabilize here", beat_slot=3)
    md = to_manifest_dict(ep, "s.mp4", "o.mp4")
    for k in ("canvas", "delivery", "model", "stabilize",       # inherited / defaulted downstream
              "source", "start", "dur", "shot_type", "processing_notes", "beat_slot"):
        assert k not in md, f"{k} must not cross the EDL↔manifest boundary"


def test_bridge_forwards_layout_and_hero_when_set():
    ep = _ep(layout="insert", crop_aspect=[9, 16], rect=[0.1, 0.1, 0.8],
             motion="lateral", hero=[10, 20, 30, 40])
    md = to_manifest_dict(ep, "s.mp4", "o.mp4")
    assert md["layout"] == "insert" and md["crop_aspect"] == [9, 16]
    assert md["rect"] == [0.1, 0.1, 0.8] and md["motion"] == "lateral" and md["hero"] == [10, 20, 30, 40]


def test_bridge_omits_crop_aspect_when_none_so_manifest_auto_picks():
    md = to_manifest_dict(_ep(layout="insert"), "s.mp4", "o.mp4")   # crop_aspect defaults None
    assert "crop_aspect" not in md                                  # manifest defaults it to 'source' for insert
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -q`
Expected: FAIL — `ImportError: cannot import name 'to_manifest_dict'`.

- [ ] **Step 3: Append the bridge to `scripts/lib/edl.py`**

```python
def to_manifest_dict(ep: EDLEpisode, segment: str, out_path: str) -> dict:
    """Map an EDL row + its extracted segment + output path onto a Manifest-shaped
    dict (the process_episode brief). A deliberate field MAP, not a dump — the
    manifest gate rejects unknown keys. Omits canvas/delivery (the driver fills
    them from the project via resolve_manifest) and model/stabilize (manifest
    defaults). EDL-only fields (source/start/dur/shot_type/processing_notes/
    beat_slot) do NOT cross — this map is the documented EDL↔manifest boundary."""
    md: dict = {
        "segment": segment, "out_path": out_path, "target_dur": ep.dur,
        "composition": ep.composition, "grid": ep.grid, "layout": ep.layout,
        "crop_scale": ep.crop_scale, "background": ep.background,
        "border_px": ep.border_px, "border_color": ep.border_color,
        "color_means": list(ep.color_means),
    }
    if ep.crop_aspect is not None:      # None → let Manifest pick canvas/source by layout
        md["crop_aspect"] = list(ep.crop_aspect) if isinstance(ep.crop_aspect, tuple) else ep.crop_aspect
    if ep.rect is not None:
        md["rect"] = list(ep.rect)
    if ep.motion is not None:
        md["motion"] = ep.motion
    if ep.hero is not None:
        md["hero"] = list(ep.hero) if isinstance(ep.hero, tuple) else ep.hero
    return md
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/edl.py tests/lib/test_edl.py
git commit -m "feat: EDL→manifest bridge to_manifest_dict (Front-half SP1)"
```

---

### Task 3: `extract_edl` loop + length gate

**Files:**
- Modify: `scripts/extract.py`
- Test: `tests/integration/test_extract.py`

- [ ] **Step 1: Add the failing tests** (real ffmpeg — uses the `sample_clip` fixture: 1920×1080 @ 30 fps, 3.0 s).

```python
# append to tests/integration/test_extract.py
import pytest
from scripts import extract
from scripts.lib import assembly
from scripts.lib.edl import EDL


def _edl(episodes, **kw):
    return EDL.from_dict({"episodes": episodes, **kw})


def _row(source, start, dur):
    return dict(source=source, start=start, dur=dur, shot_type="wide",
                composition="lead", grid="thirds")


def test_extract_edl_cuts_every_window_and_names_them_in_order(sample_clip, tmp_path):
    edl = _edl([_row(sample_clip.name, 0.2, 1.0), _row(sample_clip.name, 1.6, 1.0)])
    seg_dir = tmp_path / "segments"
    segs = extract.extract_edl(edl, footage_root=str(sample_clip.parent), seg_dir=str(seg_dir))
    assert segs == [str(seg_dir / "ep0_raw.mp4"), str(seg_dir / "ep1_raw.mp4")]
    for s, want in zip(segs, (1.0, 1.0)):
        assert abs(extract._probe_dur(s) - want) <= 1.0 / assembly.probe_stream(s).fps + 0.05


def test_extract_edl_length_gate_trips_when_a_window_runs_past_eof(sample_clip, tmp_path):
    # sample_clip is 3.0s; a 2.0s window starting at 2.0s can only yield ~1.0s
    edl = _edl([_row(sample_clip.name, 2.0, 2.0)])
    with pytest.raises(ValueError, match="shorter than its 2.0s window|length"):
        extract.extract_edl(edl, str(sample_clip.parent), str(tmp_path / "segments"))


def test_extract_edl_missing_source_names_the_resolved_path(tmp_path):
    edl = _edl([_row("nope.mp4", 0.0, 1.0)])
    with pytest.raises(ValueError, match="source not found"):
        extract.extract_edl(edl, str(tmp_path), str(tmp_path / "segments"))
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_extract.py -q`
Expected: FAIL — `AttributeError: module 'scripts.extract' has no attribute 'extract_edl'`.

- [ ] **Step 3: Add `_probe_dur` + `extract_edl` to `scripts/extract.py`**

Add imports at the top (keep `import argparse` and `from scripts.lib import proc`):

```python
from pathlib import Path
from scripts.lib import assembly, proc
from scripts.lib.edl import EDL

_LEN_EPS = 0.05    # seconds of slack beyond one frame — a re-encoded window lands ±1 frame
```

Append:

```python
def _probe_dur(path: str) -> float:
    out = proc.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nk=1:nw=1", path]).stdout.decode().strip()
    try:
        return float(out)
    except ValueError:
        raise ValueError(f"{path} reports no usable duration (ffprobe gave {out!r}) — the extract "
                         "produced an unreadable segment") from None


def extract_edl(edl: EDL, footage_root: str, seg_dir: str) -> list[str]:
    """Cut every EDL window into seg_dir/ep{i}_raw.mp4 (reel order). Gate (§5.8):
    each segment's probed duration matches its window within one frame, else raise
    — a short segment is the silent-truncation class (design §12)."""
    Path(seg_dir).mkdir(parents=True, exist_ok=True)
    segments: list[str] = []
    for i, ep in enumerate(edl.episodes):
        src = str(Path(footage_root) / ep.source)
        if not Path(src).exists():
            raise ValueError(f"EDL episode {i} source not found: {src!r} "
                             f"(footage_root={footage_root!r} + source={ep.source!r})")
        out = str(Path(seg_dir) / f"ep{i}_raw.mp4")
        extract(src, ep.start, ep.dur, out)
        probed, fps = _probe_dur(out), assembly.probe_stream(out).fps
        if probed + 1.0 / fps + _LEN_EPS < ep.dur:
            raise ValueError(
                f"EDL episode {i} segment is {probed:.3f}s — shorter than its {ep.dur}s window "
                f"(source {src!r} start={ep.start}); the window runs past the clip. Trim the window "
                "or fix the in-point.")
        segments.append(out)
    return segments
```

Note: the gate is one-sided (`probed < window`) — a re-encode never overshoots the requested `-t`, and a source shorter than `start+dur` yields a short tail, exactly the case to catch.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_extract.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/extract.py tests/integration/test_extract.py
git commit -m "feat: extract_edl loop + length gate (Front-half SP1)"
```

---

### Task 4: `edl_to_reel` driver (unit)

**Files:**
- Create: `scripts/edl_to_reel.py`
- Test: `tests/lib/test_edl_to_reel.py`

- [ ] **Step 1: Write the failing tests** (monkeypatch extract/process_episode/build_reel — mirrors `tests/lib/test_build_reel.py`).

```python
# tests/lib/test_edl_to_reel.py
import json
import pytest
from pathlib import Path
from scripts import edl_to_reel


def _project(tmp_path):
    p = tmp_path / "project.json"
    p.write_text(json.dumps({"purpose": "reel", "canvas": [1080, 1920], "delivery": "native"}))
    return str(p)


def _edl_file(tmp_path, episodes=None, **reel):
    ep = dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
              composition="lead", grid="thirds", crop_scale=0.8)
    doc = {"episodes": episodes or [ep, {**ep, "start": 2.0}], **reel}
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps(doc))
    return str(p)


def _wire(monkeypatch, pe_results=None, build_result=None):
    """Fake extract_edl / process_episode / build_reel; record what the driver builds."""
    seen = {"segments": [], "pe": [], "rm": None, "build": []}

    def fake_extract(edl, footage_root, seg_dir):
        segs = [str(Path(seg_dir) / f"ep{i}_raw.mp4") for i in range(len(edl.episodes))]
        seen["segments"] = segs
        return segs
    monkeypatch.setattr(edl_to_reel.extract, "extract_edl", fake_extract)

    results = iter(pe_results or [])

    def fake_pe(manifest, project_dir, route_path=None, color_correct=None):
        seen["pe"].append({"manifest": manifest, "project_dir": project_dir})
        return next(results, {"status": "mechanical_pass", "clip": manifest["out_path"]})
    monkeypatch.setattr(edl_to_reel.process_episode, "process_episode", fake_pe)

    def fake_build(rm, out_dir, work_dir):
        seen["rm"] = rm
        seen["build"].append((out_dir, work_dir))
        return build_result or {"status": "delivered", "output": f"{out_dir}/REEL_v1.mp4", "report": {}}
    monkeypatch.setattr(edl_to_reel.build_reel, "build_reel", fake_build)
    return seen


def test_happy_path_drives_extract_then_episodes_then_build_reel(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path),
                                  footage_root=str(tmp_path), work_dir=str(tmp_path / "w"),
                                  out_dir=str(tmp_path / "out"))
    assert res["status"] == "delivered"
    assert len(seen["pe"]) == 2                                  # one process_episode per episode
    # each manifest is resolved (concrete canvas) — build_reel reprocess runs without project=
    assert all(m["manifest"]["canvas"] == [1080, 1920] for m in seen["pe"])
    rm = seen["rm"]
    assert len(rm.episodes) == 2 and rm.target_dur == 4.0        # Σ window durs (2.0 + 2.0)
    assert rm.episodes[0].manifest["canvas"] == [1080, 1920]     # RESOLVED dict stored, not canvas-less
    assert rm.episodes[0].route.endswith("ep0/route.json")
    assert rm.cap == 3


def test_edl_music_and_target_override_reach_the_reel_manifest(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path, music="M.json", cap=2, target_dur=9.0),
                            _project(tmp_path), str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"),
                            music="OVERRIDE.json")
    rm = seen["rm"]
    assert rm.music == "OVERRIDE.json"        # --music beats edl.music
    assert rm.target_dur == 9.0 and rm.cap == 2


def test_bad_episode_preflights_before_any_ffmpeg(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    bad = dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
               composition="lead", grid="thirds", crop_scale=1.0, crop_aspect="source")  # lead + no freedom
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path, episodes=[bad]), _project(tmp_path),
                                  str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert res["status"] == "stop_and_report" and res["finding"]["reason"] == "edl-invalid"
    assert res["finding"]["episode_idx"] == 0
    assert seen["segments"] == [] and seen["pe"] == []        # nothing extracted, no episode run


def test_episode_failure_stops_and_reports_without_building(monkeypatch, tmp_path):
    seen = _wire(monkeypatch, pe_results=[{"status": "needs_input", "problems": ["ambiguous hero"]}])
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path),
                                  str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert res["status"] == "stop_and_report" and res["finding"]["reason"] == "episode-failed"
    assert res["finding"]["episode_idx"] == 0 and res["finding"]["sub_status"] == "needs_input"
    assert seen["rm"] is None and seen["build"] == []         # build_reel never reached


def test_build_reel_stop_is_passed_through(monkeypatch, tmp_path):
    _wire(monkeypatch, build_result={"status": "stop_and_report", "finding": {"reason": "variety"}})
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path),
                                  str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert res["status"] == "stop_and_report" and res["finding"]["reason"] == "variety"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_edl_to_reel.py -q`
Expected: FAIL — `ModuleNotFoundError: scripts.edl_to_reel`.

- [ ] **Step 3: Write `scripts/edl_to_reel.py`**

```python
"""Front-half SP1 driver (design docs/specs/2026-07-11-extract-spine-design.md):
a hand-authored EDL.json → a delivered REEL_v1.mp4. The thin SEQUENTIAL loop-1
fan-out — extract every window, run process_episode per episode, assemble a
ReelManifest — then hand off to build_reel (loop-2). The cap-3 PARALLEL router +
episode-choice curation (montage §5.1) is a later optimization that wraps this.
Canvas/delivery are resolved ONCE here and stored in each ReelEpisode, because
build_reel's reprocess re-runs process_episode without project=."""
import argparse
import json
from pathlib import Path

from scripts import build_reel, extract, process_episode
from scripts.lib import manifest as manifest_lib
from scripts.lib.edl import EDL, to_manifest_dict
from scripts.lib.models import ReelEpisode, ReelManifest
from scripts.lib.project import ProjectConfig, resolve_manifest


def _stop(reason: str, idx: int, **extra) -> dict:
    return {"status": "stop_and_report", "finding": {"reason": reason, "episode_idx": idx, **extra}}


def edl_to_reel(edl_path: str, project_path: str, footage_root: str,
                work_dir: str, out_dir: str, music: str | None = None) -> dict:
    """Drive EDL.json → REEL_v1.mp4, or a machine-readable stop-and-report."""
    edl = EDL.from_json(edl_path)
    cfg = ProjectConfig.from_json(project_path)
    seg_dir = str(Path(work_dir) / "segments")
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    # 1. bridge + resolve + preflight — fail in ms, before any ffmpeg (mirrors the layouts plan)
    mds: list[dict] = []
    for i, ep in enumerate(edl.episodes):
        seg = str(Path(seg_dir) / f"ep{i}_raw.mp4")
        md = resolve_manifest(to_manifest_dict(ep, seg, str(Path(out_dir) / f"ep{i}.mp4")), cfg)
        try:
            m = manifest_lib.Manifest.from_dict(md)
        except (KeyError, TypeError, ValueError) as e:
            return _stop("edl-invalid", i, problems=[str(e)])
        problems = manifest_lib.validate(m)
        if problems:
            return _stop("edl-invalid", i, problems=problems)
        mds.append(md)

    # 2. extract every window (paths match the seg_dir/ep{i}_raw.mp4 the bridge used)
    extract.extract_edl(edl, footage_root, seg_dir)

    # 3. loop-1 fan-out: one process_episode per episode (sequential)
    episodes: list[ReelEpisode] = []
    for i, md in enumerate(mds):
        epdir = str(Path(work_dir) / f"ep{i}")
        res = process_episode.process_episode(md, epdir)   # md already resolved → no project= needed
        if res.get("status") != "mechanical_pass":
            return {"status": "stop_and_report",
                    "finding": {"reason": "episode-failed", "episode_idx": i,
                                "sub_status": res.get("status")}, "sub": res}
        episodes.append(ReelEpisode(manifest=md, clip=res["clip"],
                                    route=str(Path(epdir) / "route.json")))

    # 4. loop-2: assemble the ReelManifest and drive build_reel
    target = edl.target_dur if edl.target_dur is not None else sum(ep.dur for ep in edl.episodes)
    rm = ReelManifest(episodes=episodes, target_dur=target, cap=edl.cap,
                      changelog=str(Path(out_dir) / "VERSIONS.md"), music=music or edl.music)
    return build_reel.build_reel(rm, out_dir, str(Path(work_dir) / "reel"))


def main() -> None:
    ap = argparse.ArgumentParser(description="drive a hand-authored EDL.json → delivered REEL_v1.mp4")
    ap.add_argument("edl", help="path to an EDL.json (design docs/specs/2026-07-11-extract-spine-design.md)")
    ap.add_argument("--project", required=True, help="project.json — episodes inherit its canvas/delivery")
    ap.add_argument("--footage-root", required=True, help="dir the EDL 'source' paths resolve against")
    ap.add_argument("--work-dir", required=True, help="scratch for segments / per-episode / reel master")
    ap.add_argument("--out-dir", required=True, help="delivery dir for ep{i}.mp4 + REEL_v{n}.mp4")
    ap.add_argument("--music", default=None, help="MUSIC.json path; overrides the EDL's music field")
    a = ap.parse_args()
    result = edl_to_reel(a.edl, a.project, a.footage_root, a.work_dir, a.out_dir, music=a.music)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "delivered" else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_edl_to_reel.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/edl_to_reel.py tests/lib/test_edl_to_reel.py
git commit -m "feat: edl_to_reel sequential driver + CLI (Front-half SP1)"
```

---

### Task 5: real-ffmpeg end-to-end golden

**Files:**
- Create: `tests/integration/test_front_spine.py`

**Why `process_episode` is faked here:** the driver's first `process_episode` pass runs YOLO tracking (`route_path=None`), which needs a *person* in-frame — the `sample_clip` fixture is a moving box, so real tracking returns an empty route. `process_episode` has its own real-footage golden (`test_process_episode`/`test_golden`); this golden proves the SP1 wiring — real `extract_edl` → bridge → `ReelManifest` → real `build_reel`/`deliver` — with only the tracking step stubbed. The stub writes a real `route.json` and produces a real clip by copying its segment (uniform streams, distinct box position per window → variety passes; same source colour → colour-across-cuts passes).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_front_spine.py
import json
import pytest
from pathlib import Path
from scripts import edl_to_reel
from scripts.lib import proc


def _project(tmp_path):
    p = tmp_path / "project.json"
    p.write_text(json.dumps({"purpose": "reel", "canvas": [1080, 1920], "delivery": "native"}))
    return str(p)


def _edl(tmp_path, source, music=None):
    # two windows far apart → the box sits at very different x → distinct phash (variety)
    row = lambda s, d: dict(source=source, start=s, dur=d, shot_type="wide",
                            composition="lead", grid="thirds", crop_scale=0.8)
    doc = {"episodes": [row(0.2, 1.0), row(1.8, 1.0)]}
    if music:
        doc["music"] = music
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps(doc))
    return str(p)


def _fake_track_pe(monkeypatch):
    """Stub process_episode: write a route.json + copy the segment to the locked clip."""
    def fake_pe(manifest, project_dir, route_path=None, color_correct=None):
        Path(project_dir).mkdir(parents=True, exist_ok=True)
        (Path(project_dir) / "route.json").write_text(
            json.dumps([{"t": 0.0, "x": 960, "y": 540, "w": 120, "h": 120, "id": 1}]))
        # silent video-only clip, exactly like a real reframe output (the reel master is
        # silent; the music stem is muxed at deliver) — keeps assemble's streams uniform
        proc.run(["ffmpeg", "-y", "-i", manifest["segment"], "-c:v", "copy", "-an", manifest["out_path"]])
        return {"status": "mechanical_pass", "clip": manifest["out_path"]}
    monkeypatch.setattr(edl_to_reel.process_episode, "process_episode", fake_pe)


def test_edl_drives_a_silent_reel_end_to_end(sample_clip, tmp_path, monkeypatch):
    _fake_track_pe(monkeypatch)
    res = edl_to_reel.edl_to_reel(
        _edl(tmp_path, sample_clip.name), _project(tmp_path),
        footage_root=str(sample_clip.parent), work_dir=str(tmp_path / "w"),
        out_dir=str(tmp_path / "out"))
    assert res["status"] == "delivered", res
    out = Path(res["output"])
    assert out.exists() and out.name == "REEL_v1.mp4"
    # real ffprobe: the delivered reel carries a video stream
    codecs = proc.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                       "stream=codec_type", "-of", "csv=p=0", str(out)]).stdout.decode()
    assert "video" in codecs


def test_edl_drives_a_reel_with_music(sample_clip, tmp_path, monkeypatch):
    _fake_track_pe(monkeypatch)
    # a tone track + a hand MUSIC.json (beats/energy are not the subject — the mux is)
    tone = tmp_path / "tone.wav"
    proc.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
              "-ac", "2", str(tone)])
    from scripts.lib.models import MusicSpec
    music = tmp_path / "MUSIC.json"
    music.write_text(json.dumps(MusicSpec(str(tone), 0.0, 2.0, 120.0, (0.0, 0.5, 1.0, 1.5), (0.3,), 2.0).to_dict()))
    res = edl_to_reel.edl_to_reel(
        _edl(tmp_path, sample_clip.name), _project(tmp_path),
        str(sample_clip.parent), str(tmp_path / "w"), str(tmp_path / "out"),
        music=str(music))
    assert res["status"] == "delivered", res
    audio = proc.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                      "stream=codec_name", "-of", "csv=p=0", str(Path(res["output"]))]).stdout.decode()
    assert "aac" in audio
```

If `MusicSpec.to_dict`'s field order differs, construct the dict directly from the design's MUSIC.json shape — the point is a valid `MusicSpec.from_json` round-trip, which `build_reel` calls.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_front_spine.py -q`
Expected: FAIL first for the right reason (the driver already exists from Task 4, so this exercises the real `extract_edl` + `build_reel` path). If it fails, read the failure: a length/variety/colour gate miss means the fixture windows need adjusting, not a code change.

- [ ] **Step 3: Make it pass**

No new production code is expected — Tasks 0–4 built the path. If a check gate legitimately fails on the synthetic clip (e.g. variety distance below `ReelManifest.variety_min` default 8), widen the window separation in `_edl` until the two box positions differ enough, and document why in a comment. Do **not** loosen a real gate to pass a test.

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (prior 426 + the new SP1 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_front_spine.py
git commit -m "test: real-ffmpeg EDL→REEL_v1 end-to-end golden (Front-half SP1)"
```

---

### Task 6: docs sync + final review

**Files:**
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`, `docs/specs/2026-07-05-montage-skillset-design.md`

- [ ] **Step 1: `docs/pipeline-map.md`** — flip the stage rows and roadmap:
  - 5.7 edit-plan: `❌` → `◐` — "EDL.json contract + bridge ✅ (SP1); markdown render + interactive authoring ❌ (SP3)".
  - 5.8 extract: `❌` → `✅` — "`extract_edl` loop + length gate ✅ (SP1)".
  - 5.9 assemble-draft: stays `❌` — note "draft (labels + music bed) → SP1b".
  - 5.1 router: note the `edl_to_reel` sequential driver is the precursor; cap-3 parallel + curation still `❌`.
  - "What produces a reel today": a hand-authored `EDL.json` now drives the full conveyor (`edl_to_reel`); the remaining front half (5.2 intake, 5.3 full brief, 5.4 trends, 5.9 draft) is unbuilt.
  - Phase roadmap "Front-half authoring": mark SP1 done, list SP1b (draft) / SP2 (intake) / SP3 (authoring skills) / SP4 (trends) as remaining.

- [ ] **Step 2: `docs/build-status.md`** — add a "Done" entry: **extract spine (Front-half SP1) DONE (2026-07-11)** — plan + design paths, the four units (`lib/edl.py`, `extract.extract_edl`, `edl_to_reel.py`), what closes (EDL→delivered reel), the faked-tracking golden rationale, and the deferrals (SP1b draft, SP2 intake, SP3 authoring, cap-3 router). Update the total test count. Point "Next action" at SP1b / SP2 / SP3.

- [ ] **Step 3: `CLAUDE.md`** — add a Quick Reference row for the extract-spine design + plan; if a landmine surfaced during implementation (e.g. the one-sided length gate), add it to the Known-troubles only if it fails silently.

- [ ] **Step 4: `docs/specs/2026-07-05-montage-skillset-design.md`** — add "Built (2026-07-11, SP1)" notes under §5.7 (EDL.json typed contract + bridge; markdown/authoring = SP3) and §5.8 (`extract_edl` loop + length gate), mirroring the §5.5 music-spine note style.

- [ ] **Step 5: Run the full suite once more, then commit**

```bash
.venv/bin/python -m pytest -q
git add docs/ CLAUDE.md
git commit -m "docs: sync build-status/pipeline-map/registry for extract spine (SP1)"
```

- [ ] **Step 6: Final whole-slice review** — dispatch a code-quality reviewer over the whole SP1 diff (`git diff main...feat/extract-spine`): the contract's fail-loud completeness, the bridge boundary (no key leak), the one-sided length gate, the driver's resolve-once/store-resolved invariant (the `build_reel`-reprocess-without-project coupling), and the golden's faked-tracking honesty. Fold findings, then finish via `superpowers:finishing-a-development-branch`.

---

## Notes for the executor

- **`pythonpath = .`** — run scripts as modules (`.venv/bin/python -m pytest`), never `python scripts/edl_to_reel.py`.
- **Fail loud with a remedy** — every raise is a `ValueError` naming the fix, matching `manifest.py`/`models.py`.
- **The resolve-once invariant is load-bearing** — `ReelEpisode.manifest` must carry a concrete `canvas`/`delivery`, because `build_reel`'s reprocess calls `process_episode` without `project=`. A canvas-less dict would raise there, only on a reprocess round — a latent bug the Task 4 assertion `rm.episodes[0].manifest["canvas"] == [1080, 1920]` pins.
- **Don't loosen gates to pass the golden** — if Task 5's synthetic reel trips a check, fix the fixture, not the threshold.
