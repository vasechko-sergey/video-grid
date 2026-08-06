# Edit-plan spine (SP3 · stage 5.7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the scored candidate windows of `FOOTAGE.json` (5.2) into a typed `EDL.json` + a human `EDL.md` map, authored by an agent's `selection.json`, then drivable to a reel by the existing `edl_to_reel` (SP1).

**Architecture:** The agent selects windows by judgment; code stays thin. `scripts/lib/edl.py` gains a markdown render (`EDL.to_markdown`), a serializer (`EDL.to_dict` / `EDLEpisode.to_dict`), and the shared manifest preflight extracted from `edl_to_reel`. A new `scripts/edit_plan.py` projects a `selection.json` (window references + editorial fields) through `window_to_episode` — mechanical fields come from `FOOTAGE.json` **by reference**, never retyped — into an `EDL`, preflights it against the project, and writes `EDL.json` + `EDL.md`. A new `SKILLS/edit-plan` is the writing-plans-style authoring subagent.

**Tech Stack:** Python 3.11, dataclass config-specs, pytest (`pythonpath = .`, scripts run as modules), real-ffmpeg golden. No new third-party deps.

**Spec:** [docs/specs/2026-07-12-edit-plan-spine-design.md](../specs/2026-07-12-edit-plan-spine-design.md).

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `scripts/lib/edl.py` | EDL contract | **Modify** — add `EDLEpisode.to_dict`, `EDL.to_dict`, `EDL.to_markdown`, `preflight()`; extend imports |
| `scripts/edl_to_reel.py` | SP1 driver | **Modify** — replace inline preflight loop with `edl.preflight`; drop dead `_stop` + now-unused imports |
| `scripts/edit_plan.py` | 5.7 authoring logic + CLI | **Create** — `window_to_episode`, `build_edl`, `write_edit_plan`, `main` |
| `SKILLS/edit-plan/SKILL.md` | authoring subagent | **Create** |
| `tests/lib/test_edl.py` | EDL contract tests | **Modify** — `to_dict` round-trip, `to_markdown`, `preflight` |
| `tests/lib/test_edit_plan.py` | authoring-logic tests | **Create** |
| `tests/integration/test_edit_plan.py` | real-ffmpeg SP3→SP1 seam | **Create** |
| `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`, `docs/specs/2026-07-05-montage-skillset-design.md`, `docs/specs/2026-07-11-extract-spine-design.md` | docs | **Modify** — Task 8 |

**Conventions (all tasks):** run from repo root; `pytest.ini` sets `pythonpath = .` so `from scripts…` imports resolve. Fail loud with a remedy (`raise ValueError(...)`). Imports at module top. Every module-level def fully typed. Do **not** pipe pytest through `tail` — it masks the exit code; read the summary line directly. Commit bodies end with the `Co-Authored-By` trailer.

---

## Task 0: `EDLEpisode.to_dict` + `EDL.to_dict` (round-trip serializer)

`EDL` has `from_dict`/`from_json` but no serializer; `write_edit_plan` (Task 5) needs one to persist `EDL.json`. Add the symmetric `to_dict` on both dataclasses, JSON-friendly (tuples → lists).

**Files:**
- Modify: `scripts/lib/edl.py`
- Test: `tests/lib/test_edl.py`

- [x] **Step 1: Write the failing test**

Add to `tests/lib/test_edl.py` (the `_ep` / `_edl` helpers already exist at the top of the file):

```python
def test_episode_to_dict_is_json_friendly_and_round_trips():
    e = _ep(hero=[10, 20, 30, 40], crop_aspect=[9, 16], rect=[0.1, 0.2, 0.8],
            color_means=[100, 110, 120], motion="static", beat_slot=3, processing_notes="hold here")
    d = e.to_dict()
    assert d["hero"] == [10, 20, 30, 40] and d["crop_aspect"] == [9, 16]   # tuples → lists
    assert d["rect"] == [0.1, 0.2, 0.8] and d["color_means"] == [100, 110, 120]
    assert d["beat_slot"] == 3 and d["processing_notes"] == "hold here"
    back = EDLEpisode(**d)                       # round-trips through the constructor
    assert back.to_dict() == d


def test_episode_to_dict_keeps_none_optionals():
    d = _ep().to_dict()                          # motion/hero/crop_aspect/rect default None
    assert d["motion"] is None and d["hero"] is None and d["crop_aspect"] is None and d["rect"] is None
    assert d["beat_slot"] is None


def test_edl_to_dict_round_trips():
    e = _edl(music="MUSIC.json", cap=2, target_dur=8.0)
    assert EDL.from_dict(e.to_dict()).to_dict() == e.to_dict()
    assert e.to_dict()["cap"] == 2 and e.to_dict()["music"] == "MUSIC.json"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_edl.py -k "to_dict" -v`
Expected: FAIL with `AttributeError: 'EDLEpisode' object has no attribute 'to_dict'`.

- [x] **Step 3: Write minimal implementation**

In `scripts/lib/edl.py`, add a `to_dict` method to `EDLEpisode` (after `__post_init__`):

```python
    def to_dict(self) -> dict:
        def _j(v: object) -> object:
            return list(v) if isinstance(v, tuple) else v
        return {"source": self.source, "start": self.start, "dur": self.dur,
                "shot_type": self.shot_type, "composition": self.composition, "grid": self.grid,
                "layout": self.layout, "crop_aspect": _j(self.crop_aspect), "crop_scale": self.crop_scale,
                "rect": _j(self.rect), "background": self.background, "border_px": self.border_px,
                "border_color": self.border_color, "motion": self.motion, "hero": _j(self.hero),
                "color_means": list(self.color_means), "processing_notes": self.processing_notes,
                "beat_slot": self.beat_slot}
```

And a `to_dict` method to `EDL` (after `from_json`):

```python
    def to_dict(self) -> dict:
        return {"episodes": [e.to_dict() for e in self.episodes],
                "music": self.music, "cap": self.cap, "target_dur": self.target_dur}
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_edl.py -k "to_dict" -v`
Expected: PASS (3 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/edl.py tests/lib/test_edl.py
git commit -m "$(cat <<'EOF'
feat: EDL.to_dict / EDLEpisode.to_dict — JSON-friendly round-trip serializer

write_edit_plan (5.7) needs to persist EDL.json; the contract had from_dict
but no to_dict. Tuples (hero/crop_aspect/rect/color_means) serialize to lists.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 1: `EDL.to_markdown` — the `EDL.md` human map

Renders the ordered edit decision list to markdown (montage §5.7: "a map — which file holds what and from which timestamp — no cutting yet"). Mirrors `Footage.to_markdown`.

**Files:**
- Modify: `scripts/lib/edl.py`
- Test: `tests/lib/test_edl.py`

- [x] **Step 1: Write the failing test**

Add to `tests/lib/test_edl.py`:

```python
def test_to_markdown_renders_header_and_rows():
    e = _edl(target_dur=8.0)          # two episodes, start 0.0 and 2.0, dur 2.0 each
    md = e.to_markdown()
    assert md.startswith("# Edit plan — 2 episodes, 4.0s · target 8.0s")
    assert "| # | source | window | shot | layout | comp | grid | motion | beat | notes |" in md
    assert "| 0 | a.mp4 | 0.00–2.00 (2.00s) | wide | fill | lead | thirds | – | – |" in md


def test_to_markdown_header_omits_target_when_unset():
    md = _edl().to_markdown()         # target_dur None
    assert md.startswith("# Edit plan — 2 episodes, 4.0s\n")
    assert "target" not in md.splitlines()[0]


def test_to_markdown_shows_motion_and_beat_when_set():
    ep = dict(source="b.mp4", start=1.0, dur=3.0, shot_type="close",
              composition="center", grid="phi", motion="lateral:right", beat_slot=2,
              processing_notes="nose")
    md = EDL.from_dict({"episodes": [ep]}).to_markdown()
    assert "| 0 | b.mp4 | 1.00–4.00 (3.00s) | close | fill | center | phi | lateral:right | 2 | nose |" in md
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_edl.py -k "to_markdown" -v`
Expected: FAIL with `AttributeError: 'EDL' object has no attribute 'to_markdown'`.

- [x] **Step 3: Write minimal implementation**

In `scripts/lib/edl.py`, add to `EDL` (after `to_dict`):

```python
    def to_markdown(self) -> str:
        total = sum(e.dur for e in self.episodes)
        head = f"# Edit plan — {len(self.episodes)} episodes, {total:.1f}s"
        if self.target_dur is not None:
            head += f" · target {self.target_dur:.1f}s"
        lines = [head, "",
                 "| # | source | window | shot | layout | comp | grid | motion | beat | notes |",
                 "|---|--------|--------|------|--------|------|------|--------|:----:|-------|"]
        for i, e in enumerate(self.episodes):
            motion = e.motion if e.motion is not None else "–"
            beat = str(e.beat_slot) if e.beat_slot is not None else "–"
            window = f"{e.start:.2f}–{e.start + e.dur:.2f} ({e.dur:.2f}s)"
            lines.append(f"| {i} | {e.source} | {window} | {e.shot_type} | {e.layout} | "
                         f"{e.composition} | {e.grid} | {motion} | {beat} | {e.processing_notes} |")
        return "\n".join(lines)
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_edl.py -k "to_markdown" -v`
Expected: PASS (3 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/edl.py tests/lib/test_edl.py
git commit -m "$(cat <<'EOF'
feat: EDL.to_markdown — the EDL.md human map (stage 5.7)

Ordered episodes table: source, window (start–end (dur)), shot/layout/
comp/grid/motion/beat/notes. Header shows episode count + summed dur, and
target_dur when set (a target disagreeing with Σ dur is a pacing signal).
Mirrors Footage.to_markdown.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `edl.preflight` — extract the shared manifest gate, rewire `edl_to_reel`

`edl_to_reel` inlines the EDL→manifest preflight (resolve + `Manifest.from_dict` + `validate`). `write_edit_plan` needs the same gate. Extract it to `edl.py` as `preflight()` and rewire the driver — behaviour identical, one source of truth.

**Files:**
- Modify: `scripts/lib/edl.py` (add `preflight` + imports)
- Modify: `scripts/edl_to_reel.py` (call `preflight`; drop dead `_stop` + unused imports)
- Test: `tests/lib/test_edl.py`

- [x] **Step 1: Write the failing test**

Add to `tests/lib/test_edl.py` (imports `EDL`, `preflight` from `scripts.lib.edl`; `ProjectConfig` from `scripts.lib.project`). Extend the top-of-file import line to `from scripts.lib.edl import EDL, EDLEpisode, preflight, to_manifest_dict` and add `from scripts.lib.project import ProjectConfig`:

```python
def _cfg():
    return ProjectConfig(purpose="reel", canvas=[1080, 1920], delivery="native")


def test_preflight_resolves_all_episodes_clean():
    # crop_scale 0.8 gives 'lead' horizontal freedom, so validate() passes
    e = EDL.from_dict({"episodes": [dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
                       composition="lead", grid="thirds", crop_scale=0.8)]})
    mds, stop = preflight(e, _cfg(), "seg", "out")
    assert stop is None
    assert len(mds) == 1 and mds[0]["canvas"] == [1080, 1920] and mds[0]["delivery"] == "native"
    assert mds[0]["segment"] == "seg/ep0_raw.mp4" and mds[0]["out_path"] == "out/ep0.mp4"


def test_preflight_stops_on_a_bad_layout_episode_naming_the_index():
    e = EDL.from_dict({"episodes": [
        dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide", composition="lead",
             grid="thirds", crop_scale=0.8),                          # ep0 fine
        dict(source="a.mp4", start=2.0, dur=2.0, shot_type="wide", composition="lead",
             grid="thirds", layout="fill", border_px=5)]})            # ep1 fill+border → LayoutSpec rejects
    mds, stop = preflight(e, _cfg(), "seg", "out")
    assert stop["status"] == "stop_and_report"
    assert stop["finding"]["reason"] == "edl-invalid" and stop["finding"]["episode_idx"] == 1
    assert stop["finding"]["problems"]                                # non-empty problem list
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_edl.py -k "preflight" -v`
Expected: FAIL with `ImportError: cannot import name 'preflight'`.

- [x] **Step 3: Write minimal implementation**

In `scripts/lib/edl.py`, extend the imports at the top (the `manifest` import currently pulls `DEFAULT_COLOR, LAYOUTS_SUPPORTED`):

```python
from scripts.lib.manifest import DEFAULT_COLOR, LAYOUTS_SUPPORTED, Manifest, validate
from scripts.lib.models import COMPOSITIONS, GRIDS, MOTIONS
from scripts.lib.project import ProjectConfig, resolve_manifest
```

*(No import cycle: `project` imports only `models`; `manifest` imports only `models`; `models` imports neither `edl` nor `project`. So `edl → {manifest, models, project}` is acyclic. Verified by grep — `project.py`/`manifest.py`/`models.py` never import `edl`.)*

At the **end** of `scripts/lib/edl.py` (after `to_manifest_dict`), add:

```python
def preflight(edl: EDL, cfg: ProjectConfig, seg_dir: str,
              out_dir: str) -> tuple[list[dict], dict | None]:
    """Resolve + gate every EDL episode against the project BEFORE any ffmpeg.
    For each episode: bridge to a manifest dict, inherit canvas/delivery from the
    project, then Manifest.from_dict + validate. Returns (resolved manifest dicts,
    None) when all pass, or (dicts-so-far, stop) where stop is a machine-readable
    stop_and_report naming the first invalid episode. validate() never touches the
    filesystem (it checks layout params/dims, not file existence — this is what
    lets it fail in ms), so seg_dir/out_dir may be placeholder paths."""
    mds: list[dict] = []
    for i, ep in enumerate(edl.episodes):
        seg = str(Path(seg_dir) / f"ep{i}_raw.mp4")
        md = resolve_manifest(to_manifest_dict(ep, seg, str(Path(out_dir) / f"ep{i}.mp4")), cfg)
        try:
            m = Manifest.from_dict(md)
        except (KeyError, TypeError, ValueError) as e:
            return mds, {"status": "stop_and_report",
                         "finding": {"reason": "edl-invalid", "episode_idx": i, "problems": [str(e)]}}
        problems = validate(m)
        if problems:
            return mds, {"status": "stop_and_report",
                         "finding": {"reason": "edl-invalid", "episode_idx": i, "problems": problems}}
        mds.append(md)
    return mds, None
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_edl.py -k "preflight" -v`
Expected: PASS (2 tests).

- [x] **Step 5: Rewire `edl_to_reel` to the shared preflight**

Replace the imports block in `scripts/edl_to_reel.py` (lines 8–16) with:

```python
import argparse
import json
from pathlib import Path

from scripts import build_reel, extract, process_episode
from scripts.lib.edl import EDL, preflight
from scripts.lib.models import ReelEpisode, ReelManifest
from scripts.lib.project import ProjectConfig
```

Delete the `_stop` helper (lines 19–20) entirely. Replace the `edl_to_reel` body's step-1 block (the `# 1. bridge + resolve + preflight` loop, current lines 34–46) with:

```python
    # 1. resolve + preflight every episode — fail in ms, before any ffmpeg
    mds, stop = preflight(edl, cfg, seg_dir, out_dir)
    if stop:
        return stop
```

Leave steps 2–4 (extract / fan-out / build_reel) unchanged. The `seg_dir` and `out_dir` locals already exist above step 1.

- [x] **Step 6: Run the full `edl_to_reel` suite to verify no regression**

Run: `pytest tests/lib/test_edl_to_reel.py -v`
Expected: PASS (5 tests). In particular `test_bad_episode_preflights_before_any_ffmpeg` still returns `edl-invalid` / `episode_idx == 0` with `seen["segments"] == []` (preflight returns the stop before `extract_edl` is called).

Run: `pytest tests/lib/test_edl.py -v`
Expected: PASS (all — Tasks 0–2).

- [x] **Step 7: Commit**

```bash
git add scripts/lib/edl.py scripts/edl_to_reel.py tests/lib/test_edl.py
git commit -m "$(cat <<'EOF'
refactor: extract edl.preflight, share it between edl_to_reel and edit-plan

The EDL→manifest gate (resolve + Manifest.from_dict + validate) lived inline
in edl_to_reel; the 5.7 authoring path needs the same gate. Extract it to
edl.preflight (one source of truth) and rewire the driver — behaviour
identical (edl_to_reel's 5 tests stay green, including the pre-ffmpeg stop).
edl.py now imports project.resolve_manifest (acyclic: project/manifest/models
never import edl). Drops the now-dead _stop helper + unused imports.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `window_to_episode` — the FootageWindow → EDLEpisode projection

The mechanical heart of 5.7: promote a scored window to an episode, copying the mechanical fields (source/start/dur/shot_type/description) **by reference** and forwarding the agent's editorial fields.

**Files:**
- Create: `scripts/edit_plan.py`
- Test: `tests/lib/test_edit_plan.py`

- [x] **Step 1: Write the failing test**

Create `tests/lib/test_edit_plan.py`:

```python
import pytest
from scripts import edit_plan
from scripts.lib.footage import FootageClip, FootageWindow


def _clip(**kw):
    d = dict(source="MVI_3739.mp4", dur=22.0, res=(1920, 1080), fps=30.0,
             windows=[FootageWindow(start=2.1, dur=4.0, shot_type="close", people=1,
                                    motion=0.4, shake=0.01, description="lena nose")])
    d.update(kw)
    return FootageClip(**d)


def test_window_to_episode_copies_mechanical_fields_by_reference():
    clip = _clip()
    ep = edit_plan.window_to_episode(clip, clip.windows[0], composition="lead", grid="thirds")
    assert ep.source == "MVI_3739.mp4"                      # from the parent clip
    assert ep.start == 2.1 and ep.dur == 4.0                # from the window, not retyped
    assert ep.shot_type == "close"                          # window.shot_type default
    assert ep.processing_notes == "lena nose"               # window.description seed
    assert ep.composition == "lead" and ep.grid == "thirds"


def test_window_to_episode_forwards_editorial_and_overrides_defaults():
    clip = _clip()
    ep = edit_plan.window_to_episode(clip, clip.windows[0], composition="center", grid="phi",
                                     layout="insert", motion="lateral:right", hero=[10, 20, 30, 40],
                                     shot_type="wide", processing_notes="custom")
    assert ep.layout == "insert" and ep.motion == "lateral:right" and ep.hero == (10, 20, 30, 40)
    assert ep.shot_type == "wide"                           # editorial override wins over window default
    assert ep.processing_notes == "custom"


def test_window_to_episode_unknown_editorial_key_raises():
    clip = _clip()
    with pytest.raises(ValueError, match="bogus"):
        edit_plan.window_to_episode(clip, clip.windows[0], composition="lead", grid="thirds", bogus=1)


def test_window_to_episode_missing_required_composition_raises():
    clip = _clip()
    with pytest.raises(ValueError, match="composition"):
        edit_plan.window_to_episode(clip, clip.windows[0], grid="thirds")
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_edit_plan.py -k window_to_episode -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.edit_plan'`.

- [x] **Step 3: Write minimal implementation**

Create `scripts/edit_plan.py`:

```python
"""Edit-plan authoring (design docs/specs/2026-07-12-edit-plan-spine-design.md, stage 5.7).

The 5.7 driver: an agent-authored selection.json (window references + editorial
fields) → a typed EDL.json + a human EDL.md map, which the existing edl_to_reel
(SP1) takes to a delivered reel. Selection lives in the agent's judgment; this
module is the thin mechanical half — projection + preflight + render. Contract
vs. logic split mirrors footage.py (contract) ↔ intake.py (logic).

The mechanical window fields (source/start/dur/shot_type/description) reach the
EDL BY REFERENCE through window_to_episode — never retyped by the agent, because
a retyped start/dur is the silent-wrong-cut class (montage §12). selection.json
carries only integer window indices + editorial enums/notes.
"""
import argparse
import json
from pathlib import Path

from scripts.lib.edl import EDL, EDLEpisode, preflight
from scripts.lib.footage import Footage, FootageClip, FootageWindow
from scripts.lib.project import ProjectConfig


def window_to_episode(clip: FootageClip, window: FootageWindow, **editorial: object) -> EDLEpisode:
    """Project a scored FootageWindow onto an EDLEpisode. Mechanical fields come
    from the clip/window by reference; editorial fields (composition/grid required;
    layout/motion/hero/crop_*/rect/background/border_*/color_means/beat_slot
    optional) are forwarded to EDLEpisode, whose __post_init__ is the single
    value-validation site. shot_type/processing_notes default to the window's
    shot_type/description but an editorial value overrides. An unknown or missing
    editorial field raises ValueError naming it."""
    defaults = {"shot_type": window.shot_type, "processing_notes": window.description}
    try:
        return EDLEpisode(source=clip.source, start=window.start, dur=window.dur,
                          **{**defaults, **editorial})
    except TypeError as ex:
        raise ValueError(f"window_to_episode: unknown or missing editorial field — {ex}") from ex
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_edit_plan.py -k window_to_episode -v`
Expected: PASS (4 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/edit_plan.py tests/lib/test_edit_plan.py
git commit -m "$(cat <<'EOF'
feat: edit_plan.window_to_episode — FootageWindow → EDLEpisode projection

Mechanical fields (source/start/dur/shot_type/description) copied from the
clip/window by reference — never retyped (silent-wrong-cut class, §12).
Editorial fields forward to EDLEpisode (the single validation site); unknown
or missing field raises ValueError naming it.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `build_edl` — resolve a selection into an EDL

Assemble an `EDL` from a `selection.json` dict: resolve each window reference (source + integer index) against `FOOTAGE.json`, project it, and attach the reel knobs. Fail loud on a bad source or an out-of-range index.

**Files:**
- Modify: `scripts/edit_plan.py`
- Test: `tests/lib/test_edit_plan.py`

- [x] **Step 1: Write the failing test**

Add to `tests/lib/test_edit_plan.py` (add `from scripts.lib.footage import Footage` to the imports and `from scripts.lib.edl import EDL`):

```python
def _footage():
    return Footage(clips=[
        _clip(source="A.mp4", windows=[
            FootageWindow(start=0.5, dur=2.0, shot_type="wide", people=1, motion=0.3, shake=0.0),
            FootageWindow(start=5.0, dur=3.0, shot_type="close", people=1, motion=0.5, shake=0.0)]),
        _clip(source="B.mp4", windows=[
            FootageWindow(start=1.0, dur=2.5, shot_type="medium", people=2, motion=0.2, shake=0.0)])])


def test_build_edl_resolves_refs_and_projects_in_order():
    sel = {"episodes": [
        {"source": "B.mp4", "window": 0, "composition": "center", "grid": "phi"},
        {"source": "A.mp4", "window": 1, "composition": "lead", "grid": "thirds", "motion": "static"}]}
    edl = edit_plan.build_edl(_footage(), sel)
    assert isinstance(edl, EDL) and len(edl.episodes) == 2
    assert edl.episodes[0].source == "B.mp4" and edl.episodes[0].start == 1.0    # by reference
    assert edl.episodes[1].source == "A.mp4" and edl.episodes[1].start == 5.0 and edl.episodes[1].dur == 3.0
    assert edl.episodes[1].motion == "static"


def test_build_edl_carries_reel_knobs():
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}],
           "music": "MUSIC.json", "cap": 2, "target_dur": 6.0}
    edl = edit_plan.build_edl(_footage(), sel)
    assert edl.music == "MUSIC.json" and edl.cap == 2 and edl.target_dur == 6.0


def test_build_edl_defaults_cap_when_absent():
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}]}
    assert edit_plan.build_edl(_footage(), sel).cap == 3


def test_build_edl_unknown_source_raises_listing_available():
    sel = {"episodes": [{"source": "Z.mp4", "window": 0, "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r"'Z\.mp4' not in FOOTAGE.*A\.mp4.*B\.mp4"):
        edit_plan.build_edl(_footage(), sel)


def test_build_edl_out_of_range_window_raises_with_count():
    sel = {"episodes": [{"source": "B.mp4", "window": 3, "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match="window 3 out of range for B.mp4 .has 1."):
        edit_plan.build_edl(_footage(), sel)


def test_build_edl_missing_episodes_raises():
    with pytest.raises(ValueError, match="non-empty list"):
        edit_plan.build_edl(_footage(), {"episodes": []})


def test_build_edl_bad_window_type_raises():
    sel = {"episodes": [{"source": "A.mp4", "window": "first", "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match="'window' must be an integer"):
        edit_plan.build_edl(_footage(), sel)
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_edit_plan.py -k build_edl -v`
Expected: FAIL with `AttributeError: module 'scripts.edit_plan' has no attribute 'build_edl'`.

- [x] **Step 3: Write minimal implementation**

Add to `scripts/edit_plan.py` (after `window_to_episode`):

```python
def build_edl(footage: Footage, selection: dict) -> EDL:
    """Assemble an EDL from a selection dict. Each selection episode references a
    window by (source, integer index) into FOOTAGE and supplies editorial fields;
    window_to_episode projects the mechanical fields. Reel knobs (music/cap/
    target_dur) ride at the top level. Fail-loud on a source not in FOOTAGE or an
    out-of-range window index (a typo would else surface as a FileNotFound deep in
    extract — montage §12)."""
    eps_in = selection.get("episodes")
    if not isinstance(eps_in, list) or not eps_in:
        raise ValueError("selection.episodes must be a non-empty list of episode objects")
    by_source = {c.source: c for c in footage.clips}
    episodes: list[EDLEpisode] = []
    for k, sel in enumerate(eps_in):
        if not isinstance(sel, dict):
            raise ValueError(f"selection episode {k} must be an object, got {type(sel).__name__}")
        ed = dict(sel)
        source = ed.pop("source", None)
        window = ed.pop("window", None)
        if not (isinstance(source, str) and source):
            raise ValueError(f"selection episode {k}: 'source' must be a clip path string")
        if isinstance(window, bool) or not isinstance(window, int):
            raise ValueError(f"selection episode {k}: 'window' must be an integer index into FOOTAGE")
        clip = by_source.get(source)
        if clip is None:
            raise ValueError(f"selection episode {k}: source {source!r} not in FOOTAGE — "
                             f"have {sorted(by_source)}")
        if not 0 <= window < len(clip.windows):
            raise ValueError(f"selection episode {k}: window {window} out of range for {source} "
                             f"(has {len(clip.windows)})")
        episodes.append(window_to_episode(clip, clip.windows[window], **ed))
    cap = selection.get("cap")
    return EDL(episodes=tuple(episodes), music=selection.get("music"),
               cap=cap if cap is not None else 3, target_dur=selection.get("target_dur"))
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_edit_plan.py -k build_edl -v`
Expected: PASS (7 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/edit_plan.py tests/lib/test_edit_plan.py
git commit -m "$(cat <<'EOF'
feat: edit_plan.build_edl — resolve a selection.json into a typed EDL

Resolves each window ref (source + integer index) against FOOTAGE, projects
via window_to_episode, attaches reel knobs (music/cap/target_dur). Fail-loud:
unknown source raises listing available sources; out-of-range index raises
with the window count (a typo'd ref would else be a deep FileNotFound, §12).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `write_edit_plan` + CLI — author `EDL.json` + `EDL.md`, gated by preflight

The one-call entry the SKILL/CLI drives: load inputs, build the EDL, preflight against the project, and write both artifacts — **nothing written when preflight fails**.

**Files:**
- Modify: `scripts/edit_plan.py`
- Test: `tests/lib/test_edit_plan.py`

- [x] **Step 1: Write the failing test**

Add to `tests/lib/test_edit_plan.py` (add `import json` and `from scripts.lib.edl import EDL`):

```python
def _write_inputs(tmp_path, sel):
    (tmp_path / "FOOTAGE.json").write_text(json.dumps(_footage().to_dict()))
    (tmp_path / "selection.json").write_text(json.dumps(sel))
    (tmp_path / "project.json").write_text(
        json.dumps({"purpose": "reel", "canvas": [1080, 1920], "delivery": "native"}))
    return (str(tmp_path / "FOOTAGE.json"), str(tmp_path / "selection.json"),
            str(tmp_path / "project.json"))


def test_write_edit_plan_writes_both_files_and_round_trips(tmp_path):
    sel = {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds", "crop_scale": 0.8},
        {"source": "B.mp4", "window": 0, "composition": "center", "grid": "phi"}]}
    fj, sj, pj = _write_inputs(tmp_path, sel)
    out = tmp_path / "out"
    res = edit_plan.write_edit_plan(fj, sj, pj, str(out))
    assert res["status"] == "written" and res["episodes"] == 2
    assert (out / "EDL.json").exists() and (out / "EDL.md").exists()
    edl = EDL.from_json(str(out / "EDL.json"))                 # round-trips through the contract
    assert edl.episodes[0].source == "A.mp4" and edl.episodes[1].source == "B.mp4"
    assert "# Edit plan — 2 episodes" in (out / "EDL.md").read_text()


def test_write_edit_plan_bad_episode_stops_and_writes_nothing(tmp_path):
    # ep1 is fill+border → LayoutSpec rejects it in preflight
    sel = {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds", "crop_scale": 0.8},
        {"source": "B.mp4", "window": 0, "composition": "center", "grid": "phi",
         "layout": "fill", "border_px": 5}]}
    fj, sj, pj = _write_inputs(tmp_path, sel)
    out = tmp_path / "out"
    res = edit_plan.write_edit_plan(fj, sj, pj, str(out))
    assert res["status"] == "stop_and_report" and res["finding"]["reason"] == "edl-invalid"
    assert res["finding"]["episode_idx"] == 1
    assert not (out / "EDL.json").exists() and not (out / "EDL.md").exists()   # nothing written


def test_write_edit_plan_corrupt_selection_raises(tmp_path):
    (tmp_path / "FOOTAGE.json").write_text(json.dumps(_footage().to_dict()))
    (tmp_path / "project.json").write_text(
        json.dumps({"purpose": "reel", "canvas": [1080, 1920], "delivery": "native"}))
    (tmp_path / "selection.json").write_text("{ not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        edit_plan.write_edit_plan(str(tmp_path / "FOOTAGE.json"), str(tmp_path / "selection.json"),
                                  str(tmp_path / "project.json"), str(tmp_path / "out"))
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_edit_plan.py -k write_edit_plan -v`
Expected: FAIL with `AttributeError: module 'scripts.edit_plan' has no attribute 'write_edit_plan'`.

- [x] **Step 3: Write minimal implementation**

Add to `scripts/edit_plan.py` (after `build_edl`):

```python
def write_edit_plan(footage_path: str, selection_path: str, project_path: str, out_dir: str) -> dict:
    """Author EDL.json + EDL.md from FOOTAGE + a selection, gated by the project's
    manifest preflight. Nothing is written when preflight fails — a bad EDL never
    lands as a half-valid artifact. Returns {"status": "written", ...} or the
    preflight stop_and_report verbatim."""
    footage = Footage.from_json(footage_path)
    try:
        selection = json.loads(Path(selection_path).read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{selection_path} is not valid JSON ({e}) — fix the selection syntax") from e
    cfg = ProjectConfig.from_json(project_path)
    edl = build_edl(footage, selection)
    _, stop = preflight(edl, cfg, str(Path(out_dir) / "segments"), out_dir)
    if stop:
        return stop
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    edl_path, md_path = Path(out_dir) / "EDL.json", Path(out_dir) / "EDL.md"
    edl_path.write_text(json.dumps(edl.to_dict(), indent=2))
    md_path.write_text(edl.to_markdown())
    return {"status": "written", "edl": str(edl_path), "md": str(md_path),
            "episodes": len(edl.episodes)}


def main() -> None:
    ap = argparse.ArgumentParser(description="author EDL.json + EDL.md from FOOTAGE + a selection (stage 5.7)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build EDL.json + EDL.md from a selection")
    b.add_argument("--footage", required=True, help="FOOTAGE.json from intake (stage 5.2)")
    b.add_argument("--selection", required=True, help="selection.json — window refs + editorial fields")
    b.add_argument("--project", required=True, help="project.json — canvas/delivery for the preflight")
    b.add_argument("--out-dir", required=True, help="dir for EDL.json + EDL.md")
    a = ap.parse_args()
    result = write_edit_plan(a.footage, a.selection, a.project, a.out_dir)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "written" else 1)


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_edit_plan.py -v`
Expected: PASS (all — Tasks 3–5).

- [x] **Step 5: Commit**

```bash
git add scripts/edit_plan.py tests/lib/test_edit_plan.py
git commit -m "$(cat <<'EOF'
feat: edit_plan.write_edit_plan + CLI — author EDL.json + EDL.md (stage 5.7)

Load FOOTAGE + selection + project → build_edl → preflight → write EDL.json
(to_dict) + EDL.md (to_markdown). Nothing written when preflight fails — a
bad EDL never lands as a half-valid artifact. CLI: `edit_plan build
--footage --selection --project --out-dir`, exit 0 written / 1 stop.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Integration golden — the SP3 → SP1 seam on real bytes

Prove that an agent's `selection.json` ultimately yields a delivered reel: real `edit_plan build` → `EDL.json` → the existing `edl_to_reel` on synthesized source clips. `process_episode`'s mechanical middle is faked (the synthetic clip is a box, not a person → real YOLO returns an empty route), exactly as `test_front_spine`.

**Files:**
- Create: `tests/integration/test_edit_plan.py`

- [x] **Step 1: Write the test**

Create `tests/integration/test_edit_plan.py`:

```python
"""Real-ffmpeg SP3→SP1 seam (design docs/specs/2026-07-12-edit-plan-spine-design.md):
a selection.json + FOOTAGE.json → edit_plan build → EDL.json → the existing
edl_to_reel → a delivered REEL_v1.mp4. Real edit_plan + real extract/assemble/
check_reel/deliver; process_episode's mechanical middle is faked because the
synthetic sample_clip is a box, not a person (real YOLO returns an empty route —
same reason test_front_spine fakes it). Proves the selection → EDL → reel WIRING
on real bytes, not pixel-level crop correctness."""
import json
from pathlib import Path

import pytest

from scripts import edit_plan, edl_to_reel
from scripts.lib import proc
from scripts.lib.footage import Footage, FootageClip, FootageWindow

pytestmark = pytest.mark.integration


def _fake_track_pe(monkeypatch):
    def fake_pe(manifest, project_dir, route_path=None, color_correct=None):
        Path(project_dir).mkdir(parents=True, exist_ok=True)
        (Path(project_dir) / "route.json").write_text(
            json.dumps([{"t": 0.0, "x": 960, "y": 540, "w": 120, "h": 120, "id": 1}]))
        proc.run(["ffmpeg", "-y", "-i", manifest["segment"], "-c:v", "copy", "-an", manifest["out_path"]])
        return {"status": "mechanical_pass", "clip": manifest["out_path"]}
    monkeypatch.setattr(edl_to_reel.process_episode, "process_episode", fake_pe)


def _footage_json(tmp_path, source):
    # two windows far apart → the box sits at very different x → distinct phash (variety)
    f = Footage(clips=[FootageClip(source=source, dur=3.0, res=(1920, 1080), fps=30.0, windows=[
        FootageWindow(start=0.2, dur=1.0, shot_type="wide", people=1, motion=0.3, shake=0.0),
        FootageWindow(start=1.8, dur=1.0, shot_type="wide", people=1, motion=0.3, shake=0.0)])])
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict()))
    return str(p)


def _selection_json(tmp_path, source):
    sel = {"episodes": [
        {"source": source, "window": 0, "composition": "lead", "grid": "thirds", "crop_scale": 0.8},
        {"source": source, "window": 1, "composition": "lead", "grid": "thirds", "crop_scale": 0.8}]}
    p = tmp_path / "selection.json"
    p.write_text(json.dumps(sel))
    return str(p)


def _project_json(tmp_path):
    p = tmp_path / "project.json"
    p.write_text(json.dumps({"purpose": "reel", "canvas": [1080, 1920], "delivery": "native"}))
    return str(p)


def test_selection_becomes_edl_becomes_reel(sample_clip, tmp_path, monkeypatch):
    fj = _footage_json(tmp_path, sample_clip.name)
    sj = _selection_json(tmp_path, sample_clip.name)
    pj = _project_json(tmp_path)
    plan_out = tmp_path / "plan"

    res = edit_plan.write_edit_plan(fj, sj, pj, str(plan_out))
    assert res["status"] == "written", res
    edl_path = plan_out / "EDL.json"
    assert edl_path.exists() and (plan_out / "EDL.md").exists()
    assert "# Edit plan — 2 episodes" in (plan_out / "EDL.md").read_text()

    _fake_track_pe(monkeypatch)
    reel = edl_to_reel.edl_to_reel(
        str(edl_path), pj, footage_root=str(sample_clip.parent),
        work_dir=str(tmp_path / "w"), out_dir=str(tmp_path / "out"))
    assert reel["status"] == "delivered", reel
    out = Path(reel["output"])
    assert out.exists() and out.name == "REEL_v1.mp4"
    codecs = proc.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                       "stream=codec_type", "-of", "csv=p=0", str(out)]).stdout.decode()
    assert "video" in codecs
```

- [x] **Step 2: Run the test**

Run: `pytest tests/integration/test_edit_plan.py -v`
Expected: PASS (1 test; skips only if ffmpeg is absent, via the `sample_clip` fixture's own skip).

- [x] **Step 3: Commit**

```bash
git add tests/integration/test_edit_plan.py
git commit -m "$(cat <<'EOF'
test: real-ffmpeg SP3→SP1 seam — selection.json → EDL → delivered reel

A selection.json + FOOTAGE.json → edit_plan build → EDL.json → the existing
edl_to_reel → REEL_v1.mp4 on synthesized bytes. process_episode's mechanical
middle is faked (box, not a person → empty YOLO route), as test_front_spine.
Proves the authoring→driver wiring end-to-end.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `SKILLS/edit-plan/SKILL.md` — the authoring subagent

The writing-plans-style edit-plan skill (montage §5.7): autonomous draft + a single review gate. Model the frontmatter/structure on `SKILLS/footage-intake/SKILL.md`.

**Files:**
- Create: `SKILLS/edit-plan/SKILL.md`
- Reference (read, do not modify): `SKILLS/footage-intake/SKILL.md`

- [x] **Step 1: Read the sibling skill for house style**

Run: `cat SKILLS/footage-intake/SKILL.md`
Note the frontmatter shape (`name`, `description`), the script-invocation style (explicit args, run as a module), and the tone.

- [x] **Step 2: Write the skill**

Create `SKILLS/edit-plan/SKILL.md`:

```markdown
---
name: edit-plan
description: Stage 5.7 — author an EDL from scored footage windows. Use after footage-intake (FOOTAGE.json exists) and project-init (project.json) to turn candidate moment-windows into a typed EDL.json + a human EDL.md map that edl_to_reel drives to a reel. Autonomous draft + one review gate.
---

# edit-plan (stage 5.7)

Turn the scored candidate windows of `FOOTAGE.json` into an ordered **edit
decision list** — a map of which clip window plays when, with what composition,
layout, grid, and motion. This is the writing-plans of reels: **a map, not a
cut** — no ffmpeg here. The picture params you assign here are the process-episode
brief; the actual cutting and reframing happen downstream (5.8 → 5.10).

**Selection is your judgment.** intake (5.2) already scored, culled, and
`best`-marked the windows; your job is editorial — *which* best moments, in *what
order*, with *what* composition/layout/motion. You never retype a timestamp: you
reference a window by its clip source + index, and the code copies its start/dur
from `FOOTAGE.json`.

## Inputs

- **`FOOTAGE.json` + `FOOTAGE.md`** (required, from footage-intake) — the ranked
  candidate windows. Read `FOOTAGE.md` for the human view; the window **index**
  you reference is the 0-based position within that clip's window list.
- **`project.json`** (required, from project-init) — the canvas/delivery the
  episodes inherit; used by the preflight.
- **`references/editing-canon.md`** (required read) — thirds, headroom, lead room,
  the 180° rule, cut-on-action, contrast. Your editorial base.
- **`SPEC.md` / `PACING.md` / `MUSIC.json`** (optional) — read as guidance when
  present. Without `PACING.md`, leave `beat_slot` unset. Point `music` at a
  `MUSIC.json` when one exists.

## Procedure

1. **Recon.** Read `FOOTAGE.md`, `project.json`, `references/editing-canon.md`, and
   any soft inputs present. Note the reel's target length (from `SPEC.md` or
   `project.json`, else propose one from the strongest windows).
2. **Author `selection.json`.** Pick the best windows (they are already ranked),
   dedup across sources so one clip doesn't dominate, fit the running sum to the
   target length, and order them **hook first**. For each episode assign:
   - `composition` ∈ `lead` / `center` / `break` (required)
   - `grid` ∈ `thirds` / `phi` (required)
   - `layout` ∈ `fill` / `fit-blur` / `insert` (default `fill`)
   - `motion` ∈ `lateral:right` / `lateral:left` / `head-on` / `static` (optional)
   - `hero` — a rule (`largest`/`leftmost`), a first-frame bbox `[x,y,w,h]`, or a
     cast name (optional; resolving a cast name to a descriptor is a later task)
   - `processing_notes` — a short note for the draft labels (optional)

   The shape (integer window indices + editorial only — no timestamps):

       {
         "episodes": [
           {"source": "MVI_3739.mp4", "window": 2, "composition": "lead",
            "grid": "thirds", "layout": "fill", "motion": "lateral:right", "hero": "largest"},
           {"source": "MVI_3998.mp4", "window": 1, "composition": "center", "grid": "phi"}
         ],
         "music": null, "cap": 3, "target_dur": null
       }

3. **Build.** Run the authoring script (explicit args; the user never types flags):

       python -m scripts.edit_plan build --footage FOOTAGE.json \
         --selection selection.json --project project.json --out-dir .

   It projects each window, **preflights** the EDL against the project, and writes
   `EDL.json` + `EDL.md`. On a `stop_and_report` (reason `edl-invalid`), fix the
   named episode in `selection.json` and re-run — never hand-edit `EDL.json`
   (`selection.json` is the source; the EDL is generated).

4. **Review.** Show the user `EDL.md`. On edits, revise `selection.json` and
   re-run step 3. `EDL.json` is regenerated every time — never patched by hand.

## Gate

Every episode has a source + window + shot-type. A preflight `stop_and_report` is
surfaced verbatim (episode index + problems), never worked around. When
`PACING.md` exists, every episode also carries a `beat_slot`.

## Hand-off

`EDL.json` drives the rest of the conveyor: `edl_to_reel` (or, later, the 5.1
router) extracts each window, runs process-episode per episode, and builds the
delivered reel — with music when `EDL.music` points at a `MUSIC.json`.
```

- [x] **Step 3: Sanity-check the skill references**

Run: `test -f references/editing-canon.md && echo OK`
Expected: `OK` (the skill tells the agent to read it).
Run: `python -m scripts.edit_plan build --help`
Expected: the argparse help for `--footage/--selection/--project/--out-dir` (confirms the invocation in the skill is accurate).

- [x] **Step 4: Commit**

```bash
git add SKILLS/edit-plan/SKILL.md
git commit -m "$(cat <<'EOF'
feat: SKILLS/edit-plan — the stage 5.7 authoring subagent

Writing-plans-style: recon FOOTAGE.md + project + editing-canon → author
selection.json (window refs + editorial, no timestamps) → edit_plan build →
EDL.json + EDL.md → single review gate. Selection is judgment; the code
projects windows by reference. beat_slot left unset without PACING.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Docs sync + registry + final whole-slice review

Update the status docs and registry, then dispatch a final review over the whole slice.

**Files:**
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`, `docs/specs/2026-07-05-montage-skillset-design.md`, `docs/specs/2026-07-11-extract-spine-design.md`

- [x] **Step 1: Update `docs/pipeline-map.md`**

In the "15 stages" table, change the 5.7 row's status `◐` → `✅` and its note to:

```
| 5.7  | edit-plan | `EDL.md` | ✅ | `EDL.json` typed contract + `to_manifest_dict` bridge ✅ (SP1); `EDL.md` render + `edit_plan.py` (selection→projection→EDL) + `edit-plan` SKILL ✅ (SP3) | Front-half authoring |
```

In the "Remaining work — blockers & critical path" table, change the 5.7 row to `✅` and set "Left to build" to `— (SP3, 2026-07-12)`; update the 5.1 router row's "Blocked by" to note 5.7 is now ✅. Update the tally (`7 ✅ · 5 ◐ · 3 ❌`) and the critical-path diagram (`5.7 edit-plan ✅`). Bump `_Last updated: 2026-07-12._` (unchanged date, but confirm).

- [x] **Step 2: Update `docs/build-status.md`**

Add a DONE entry for SP3 (mirror the SP2 entry's format): what shipped (`EDL.to_markdown`/`to_dict`/`preflight`, `edit_plan.py`, `edit-plan` SKILL, the SP3→SP1 golden), the commit range, and set the "next action" to the next front-half slice (SP1b assemble-draft or the full reel-brief). Flip stage 5.7 to ✅ wherever it is tracked.

- [x] **Step 3: Update `CLAUDE.md` registry**

Add a Quick Reference row for the edit-plan spine design + plan (mirror the extract-spine rows):

```
| Edit-plan spine design | [2026-07-12-edit-plan-spine-design.md](docs/specs/2026-07-12-edit-plan-spine-design.md) | Front-half SP3 (§5.7): FOOTAGE.json scored windows → agent `selection.json` → `edit_plan.py` projection → `EDL.json` + `EDL.md`; thin code (selection is judgment), shared `edl.preflight`, autonomous-draft SKILL. |
| Edit-plan spine plan | [2026-07-12-edit-plan-spine.md](docs/plans/2026-07-12-edit-plan-spine.md) | Tasks 0–8: EDL.to_markdown/to_dict, extract edl.preflight, edit_plan.py (window_to_episode/build_edl/write_edit_plan), edit-plan SKILL, real-ffmpeg SP3→SP1 golden, docs. |
```

- [x] **Step 4: Update the montage design spec §5.7 Built note**

In `docs/specs/2026-07-05-montage-skillset-design.md`, replace the §5.7 "Built (2026-07-11, SP1)" note's deferral sentence — the `EDL.md` render + interactive authoring are no longer deferred. Add a "Built (2026-07-12, SP3)" note: `scripts/edit_plan.py` + `SKILLS/edit-plan` author an `EDL.json` + `EDL.md` from `FOOTAGE.json` via an agent `selection.json` (selection = judgment; code projects windows by reference); `EDL.to_markdown` renders the map; `edl.preflight` (shared with `edl_to_reel`) gates before extract. Point at `docs/plans/2026-07-12-edit-plan-spine.md`.

- [x] **Step 5: Update the extract-spine spec's SP3 pointer**

In `docs/specs/2026-07-11-extract-spine-design.md` §7 (Non-goals), the line "`EDL.md` markdown render + interactive edit-plan authoring → **SP3**" now has a home — append `(built 2026-07-12, docs/specs/2026-07-12-edit-plan-spine-design.md)`.

- [x] **Step 6: Run the full suite**

Run: `pytest -q; echo "EXIT: $?"`
Expected: all green (unit + integration), `EXIT: 0`. (Do not pipe through `tail` — it masks the exit code.)

- [x] **Step 7: Commit the docs**

```bash
git add docs/ CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: edit-plan spine (SP3 · 5.7) — status, pipeline-map, registry sync

5.7 ◐→✅: EDL.md render + edit_plan.py (selection→projection→EDL) + edit-plan
SKILL. build-status DONE entry, pipeline-map stage + blockers/critical-path,
CLAUDE.md registry rows, montage §5.7 Built note, extract-spine SP3 pointer.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

- [x] **Step 8: Final whole-slice review**

Dispatch a fresh code-review subagent (opus) over the whole branch diff `main..HEAD`. Focus: (a) no float transcription leaks — the only path from window start/dur to the EDL is `window_to_episode`; (b) `edl.preflight` behaviour is identical to the old inline loop (edl_to_reel's 5 tests green); (c) no import cycle from `edl → project`; (d) fail-loud with remedy on every raise; (e) `EDL.json` is always generated from `selection.json`, never hand-authored in the flow. Fold any legitimate finding, then the slice is ready to merge.

---

## Self-Review

**Spec coverage** (each spec section → task):
- §2.1 `EDL.to_markdown` → Task 1. §2.2 `preflight` extraction + rewire → Task 2.
- §2 `EDL.to_dict` (called out in §3.3) → Task 0.
- §3.1 `window_to_episode` → Task 3. §3.2 `build_edl` → Task 4. §3.3 `write_edit_plan` + §3.4 CLI → Task 5.
- §4 SKILL → Task 7. §5 testing → Tasks 0–6 (unit) + Task 6 (integration golden). §6 landmines → enforced by Tasks 2/3/4/5 tests. §7 non-goals → nothing built (beat_slot stays None; hero stays a string). §8 reused → no changes to those modules.

**Placeholder scan:** every code step shows complete code; every command shows expected output. No "TBD"/"handle edge cases". Task 8 docs steps describe exact edits (row text given for the two tables) — the prose steps (build-status/§5.7 note) reference the sibling format to copy, which is the established doc-sync pattern.

**Type consistency:** `preflight(edl, cfg, seg_dir, out_dir) -> tuple[list[dict], dict | None]` — defined Task 2, consumed identically in `edl_to_reel` (Task 2 Step 5) and `write_edit_plan` (Task 5). `window_to_episode(clip, window, **editorial) -> EDLEpisode` — defined Task 3, called in `build_edl` (Task 4). `build_edl(footage, selection) -> EDL` → consumed by `write_edit_plan` (Task 5). `EDL.to_dict`/`EDL.to_markdown` (Tasks 0/1) consumed by `write_edit_plan` (Task 5). Selection shape (`source`, `window`, editorial + `music`/`cap`/`target_dur`) is consistent across Tasks 4/5/6/7. Bad-episode preflight trip (`layout="fill"` + `border_px=5`) is the same across Tasks 2/5.
