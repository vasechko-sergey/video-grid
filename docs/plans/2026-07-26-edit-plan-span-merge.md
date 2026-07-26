# Edit-plan span merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let one EDL episode reference a range of adjacent footage windows
(`"window": [i, j]` in `selection.json`) and project that range onto a single
continuous episode spanning `[min start … max end]`, carrying the connective
footage between the windows ("turn → drive → turn" → one episode).

**Architecture:** A new pure `edit_plan._merge_windows(clip, i, j)` synthesizes
**one** `FootageWindow` covering the range (union `track_ids`, inherit window `i`'s
`shot_type`/`description`), which the **unchanged** `window_to_episode` projects —
so its existing `FootageClip.room_after` check refuses a range that straddles a
scene cut for free. `build_edl` gains one branch: when an episode's `window` is a
two-element list it validates the range and calls the merge; an integer keeps the
current single-window path byte-for-byte. No contract, intake, or pacing change.

**Tech Stack:** Python 3.13 (`.venv/bin/python`), pytest (`pythonpath = .`,
scripts run as modules), real-ffmpeg integration golden. Design:
[docs/specs/2026-07-26-edit-plan-span-merge-design.md](../specs/2026-07-26-edit-plan-span-merge-design.md).

**Conventions (read before starting):**
- Run tests with `.venv/bin/python -m pytest` from the repo root. A single test:
  `.venv/bin/python -m pytest tests/lib/test_edit_plan.py::test_name -v`.
- Fail-loud contract, imports-at-top, config-spec dataclasses — see
  [docs/coding-standards.md](../coding-standards.md).
- **Do NOT run any installer** (`brew`/`pip`/`uv`/`npm`/`setup.sh`); the env is
  already provisioned. Verification is read-only + pytest.
- Commit after each task. Post-review fixes are **separate follow-up commits**,
  never `git commit --amend`. Commit bodies end with the `Co-Authored-By` trailer.

---

## File-by-file change map

- **`scripts/edit_plan.py`** — add `_merge_windows` (pure envelope + scene-cut
  refusal) and `_resolve_window` (window-ref → `FootageWindow`, int or `[i, j]`);
  `build_edl`'s loop calls `_resolve_window`. (Tasks 0, 1)
- **`tests/lib/test_edit_plan.py`** — `_merge_clip` fixture + `_merge_windows`
  unit tests + `build_edl` span-path/validation tests. (Tasks 0, 1)
- **`tests/integration/test_edit_plan.py`** — a span episode survives the real
  SP3→SP1 seam. (Task 2)
- **`skills/edit-plan/SKILL.md`** — span authoring guidance. (Task 3)
- **`CLAUDE.md`, `docs/build-status.md`, `docs/pipeline-map.md`** — registry +
  status + stage-map sync. (Task 4)

---

### Task 0: `_merge_windows` — the pure envelope + scene-cut refusal

**Files:**
- Modify: `scripts/edit_plan.py` (add `_merge_windows` after `window_to_episode`)
- Test: `tests/lib/test_edit_plan.py`

- [ ] **Step 1: Add the `_merge_clip` fixture**

Add near the top of `tests/lib/test_edit_plan.py`, after the existing `_clip`
helper (a clip with three windows in one uninterrupted shot; `w0=[2.0,5.0)`,
`w1=[6.0,8.0)`, `w2=[9.0,11.0)`, with distinct `track_ids` so the union is
observable):

```python
def _merge_clip(**kw):
    d = dict(source="M.mp4", dur=30.0, res=(1920, 1080), fps=30.0, scene_cuts=[],
             windows=[
                 FootageWindow(start=2.0, dur=3.0, shot_type="wide", people=1, motion=0.4,
                               shake=0.01, description="approach", track_ids=[1]),
                 FootageWindow(start=6.0, dur=2.0, shot_type="close", people=1, motion=0.6,
                               shake=0.02, description="cross-step", track_ids=[1, 2]),
                 FootageWindow(start=9.0, dur=2.0, shot_type="wide", people=1, motion=0.5,
                               shake=0.01, description="exit turn", track_ids=[2])])
    d.update(kw)
    return FootageClip(**d)
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/lib/test_edit_plan.py`:

```python
def test_merge_windows_envelope_spans_the_range_and_unions_track_ids():
    clip = _merge_clip()
    fw = edit_plan._merge_windows(clip, 0, 1)
    assert fw.start == 2.0
    assert fw.dur == 6.0                        # 8.0 (w1 end) - 2.0 (w0 start): covers the 5.0-6.0 drive between
    assert fw.track_ids == [1, 2]              # sorted union across the range
    assert fw.shot_type == "wide"             # inherited from window i (the arc's opening)
    assert fw.description == "approach"       # inherited from window i


def test_merge_windows_covers_the_whole_range_not_just_endpoints():
    clip = _merge_clip()
    fw = edit_plan._merge_windows(clip, 0, 2)
    assert fw.start == 2.0 and fw.dur == 9.0   # 11.0 (w2 end) - 2.0 (w0 start)
    assert fw.track_ids == [1, 2]              # unions w0, w1, w2


def test_merge_windows_allows_a_scene_cut_outside_the_span():
    # a cut AFTER the [0,1] envelope's end (8.0) does not block the merge — only a cut
    # INSIDE [start, end] splices two shots; a presence transition (no cut) is fine (§3)
    clip = _merge_clip(scene_cuts=[8.5])
    fw = edit_plan._merge_windows(clip, 0, 1)
    assert fw.dur == 6.0


def test_merge_windows_refuses_to_cross_a_scene_cut():
    # a cut between w0 (ends 5.0) and w1 (starts 6.0) sits inside the [2.0, 8.0] envelope
    clip = _merge_clip(scene_cuts=[5.5])
    with pytest.raises(ValueError, match=r"scene cut at 5\.50s.*cannot cross"):
        edit_plan._merge_windows(clip, 0, 1)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -k merge_windows -v`
Expected: FAIL with `AttributeError: module 'scripts.edit_plan' has no attribute '_merge_windows'`.

- [ ] **Step 4: Implement `_merge_windows`**

In `scripts/edit_plan.py`, add this function immediately after `window_to_episode`
(before `_SNAP_TOL`). `dataclasses`, `FootageClip`, `FootageWindow` are already
imported. **Note the `_MERGE_TOL` guard**: `FOOTAGE.json` rounds `start` and `dur`
independently, so a merged envelope end can land ~1ms past a cut/clip-end boundary —
tolerate + clamp that slop rather than crash on an empty `min()` or falsely refuse a
legitimate clip-end span (found in code review of the naive `if end - start > room`).

```python
_MERGE_TOL = 1e-3   # s: FOOTAGE rounds start and dur independently, so a merged envelope end can
                    # sit up to ~1ms past its true cut/clip-end boundary; tolerate + clamp that slop.


def _merge_windows(clip: FootageClip, i: int, j: int) -> FootageWindow:
    """Merge adjacent footage windows i..j (inclusive) into one FootageWindow covering
    [min start .. max end] — an episode spanning several activity units plus the connective
    footage between them (design 2026-07-26-edit-plan-span-merge §3, "turn -> drive -> turn").

    The merged window inherits window i's shot_type/description as the projection seed (an
    editorial override still wins in window_to_episode) and unions the track_ids across the
    range. It refuses a range whose envelope straddles a scene cut — that would splice two
    shots into one episode; `room_after` is the single geometric authority (the same rule
    window_to_episode applies), naming the offending cut for a span-specific remedy. Crossing
    a presence transition inside one shot is allowed (scene_cuts holds only real cuts, and
    room_after stops only at cuts). An envelope end within _MERGE_TOL of a cut/clip-end
    boundary is a rounding artefact (FOOTAGE rounds start and dur independently), so it is
    clamped to the boundary rather than refused; beyond the tolerance with no cut inside, the
    last window lies past the clip and the merge fails loud. Assumes a valid
    0 <= i < j < len(clip.windows); build_edl bounds-checks."""
    wins = clip.windows[i:j + 1]
    start = min(w.start for w in wins)
    end = max(w.start + w.dur for w in wins)
    tids = sorted({t for w in wins for t in w.track_ids})
    room = clip.room_after(start)
    if end - start > room + _MERGE_TOL:
        inside = [c for c in clip.scene_cuts if start < c < end]
        if inside:
            raise ValueError(
                f"_merge_windows: span [{i}, {j}] runs {end - start:.2f}s from {start:.2f}s in "
                f"{clip.source}, but a scene cut at {min(inside):.2f}s lies inside it — a span cannot "
                f"cross a scene cut (it would splice two shots into one episode). Split it into two "
                f"episodes, one on each side of the cut")
        raise ValueError(
            f"_merge_windows: span [{i}, {j}] envelope ends at {end:.2f}s, past the end of "
            f"{clip.source} ({clip.dur:.2f}s) — the last window extends beyond the clip; re-run "
            f"footage-intake to regenerate FOOTAGE.json")
    return dataclasses.replace(clip.windows[i], start=start,
                               dur=min(end - start, room), track_ids=tids)
```

Two more `_merge_windows` tests cover the rounding guard (append them to the Step 2
block above):

```python
def test_merge_windows_clamps_a_sub_ms_clip_end_overshoot_instead_of_crashing():
    clip = FootageClip(source="M.mp4", dur=10.0, res=(1920, 1080), fps=30.0, scene_cuts=[],
                       windows=[FootageWindow(start=2.0, dur=3.0, shot_type="wide", people=1,
                                              motion=0.4, shake=0.0),
                                FootageWindow(start=6.667, dur=3.334, shot_type="wide", people=1,
                                              motion=0.4, shake=0.0)])   # 6.667+3.334 = 10.001 > 10.0
    fw = edit_plan._merge_windows(clip, 0, 1)
    assert fw.start == 2.0 and fw.dur == pytest.approx(8.0)   # clamped to clip end, not 8.001


def test_merge_windows_refuses_an_envelope_well_past_the_clip_end():
    clip = FootageClip(source="M.mp4", dur=10.0, res=(1920, 1080), fps=30.0, scene_cuts=[],
                       windows=[FootageWindow(start=2.0, dur=3.0, shot_type="wide", people=1,
                                              motion=0.4, shake=0.0),
                                FootageWindow(start=8.0, dur=5.0, shot_type="wide", people=1,
                                              motion=0.4, shake=0.0)])   # 8+5=13 >> 10
    with pytest.raises(ValueError, match=r"past the end of M\.mp4"):
        edit_plan._merge_windows(clip, 0, 1)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -k merge_windows -v`
Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/edit_plan.py tests/lib/test_edit_plan.py
git commit -m "feat: _merge_windows — envelope over a window range, scene-cut refusal"
```

---

### Task 1: `build_edl` span branch — the `window` overload

**Files:**
- Modify: `scripts/edit_plan.py` (add `_resolve_window`; `build_edl` calls it)
- Test: `tests/lib/test_edit_plan.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_edit_plan.py` (they use the `_merge_clip` fixture from
Task 0):

```python
def test_build_edl_span_window_merges_into_one_episode():
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [0, 1],
                         "composition": "lead", "grid": "thirds"}]}
    edl = edit_plan.build_edl(footage, sel)
    assert len(edl.episodes) == 1
    assert edl.episodes[0].start == 2.0 and edl.episodes[0].dur == 6.0   # merged envelope, not one window
    assert edl.episodes[0].shot_type == "wide"                          # window i's shot_type default


def test_build_edl_span_forwards_editorial_and_overrides():
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [0, 2], "composition": "center",
                         "grid": "phi", "motion": "static", "shot_type": "medium",
                         "processing_notes": "turn-drive-turn"}]}
    ep = edit_plan.build_edl(footage, sel).episodes[0]
    assert ep.dur == 9.0 and ep.motion == "static"
    assert ep.shot_type == "medium"                    # editorial override beats window i's default
    assert ep.processing_notes == "turn-drive-turn"


def test_build_edl_span_round_trips_through_to_dict():
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [0, 1],
                         "composition": "lead", "grid": "thirds"}]}
    edl = edit_plan.build_edl(footage, sel)
    assert EDL.from_dict(edl.to_dict()).episodes[0].dur == 6.0    # a merged episode is an ordinary EDLEpisode


def test_build_edl_span_reversed_range_raises():
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [1, 0], "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r"span window \[1, 0\] out of range"):
        edit_plan.build_edl(footage, sel)


def test_build_edl_span_degenerate_i_equals_j_raises():
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [1, 1], "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r'for a single window use "window": i'):
        edit_plan.build_edl(footage, sel)


def test_build_edl_span_out_of_range_j_raises():
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [0, 9], "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r"span window \[0, 9\] out of range"):
        edit_plan.build_edl(footage, sel)


def test_build_edl_span_wrong_length_raises():
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [0, 1, 2], "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r"a span 'window' must be \[i, j\]"):
        edit_plan.build_edl(footage, sel)


def test_build_edl_span_non_int_element_raises():
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [0, "x"], "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r"a span 'window' must be \[i, j\]"):
        edit_plan.build_edl(footage, sel)


def test_build_edl_span_bool_element_raises():
    # True is an int in Python — the guard must reject a bool element, not treat it as index 1
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [0, True], "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r"a span 'window' must be \[i, j\]"):
        edit_plan.build_edl(footage, sel)


def test_build_edl_span_crossing_a_scene_cut_raises():
    footage = Footage(clips=[_merge_clip(scene_cuts=[5.5])])
    sel = {"episodes": [{"source": "M.mp4", "window": [0, 1], "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r"scene cut at 5\.50s.*cannot cross"):
        edit_plan.build_edl(footage, sel)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -k "build_edl_span" -v`
Expected: FAIL — the span selections currently hit the single-window guard
(`'window' must be an integer index into FOOTAGE`), so the merge/validation
assertions do not hold.

- [ ] **Step 3: Add `_resolve_window`**

In `scripts/edit_plan.py`, add this function immediately after `_merge_windows`
(before `_SNAP_TOL`):

```python
def _resolve_window(clip: FootageClip, window: object, source: str, k: int) -> FootageWindow:
    """Resolve a selection episode's `window` ref to one FootageWindow. An int is a single
    window (the 5.7 behaviour); a two-element [i, j] list is a span merged into one episode
    (§3b). Fail-loud on a bad shape, a bad type, or an out-of-range index — naming episode k."""
    if isinstance(window, list):
        if len(window) != 2 or any(isinstance(v, bool) or not isinstance(v, int) for v in window):
            raise ValueError(f"selection episode {k}: a span 'window' must be [i, j] — two "
                             f"integer indices, got {window!r}")
        i, j = window
        if not 0 <= i < j < len(clip.windows):
            raise ValueError(f"selection episode {k}: span window {window} out of range for "
                             f"{source} (need 0 <= i < j < {len(clip.windows)}; for a single "
                             f'window use "window": i)')
        return _merge_windows(clip, i, j)
    if isinstance(window, bool) or not isinstance(window, int):
        raise ValueError(f"selection episode {k}: 'window' must be an integer index or a "
                         f"[i, j] span into FOOTAGE")
    if not 0 <= window < len(clip.windows):
        raise ValueError(f"selection episode {k}: window {window} out of range for {source} "
                         f"(has {len(clip.windows)})")
    return clip.windows[window]
```

- [ ] **Step 4: Rewire `build_edl`'s loop to call it**

In `build_edl`, replace the per-episode resolution block. The current loop body
(from `if not (isinstance(source, str) and source):` through the
`episodes.append(...)` call) reads:

```python
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
        episodes.append(window_to_episode(clip, clip.windows[window],
                                          start_offset=start_offset, **ed))
```

Replace it with (clip is resolved first — both the int and the span form need it
to bounds-check — then `_resolve_window` handles the window ref):

```python
        if not (isinstance(source, str) and source):
            raise ValueError(f"selection episode {k}: 'source' must be a clip path string")
        clip = by_source.get(source)
        if clip is None:
            raise ValueError(f"selection episode {k}: source {source!r} not in FOOTAGE — "
                             f"have {sorted(by_source)}")
        fw = _resolve_window(clip, window, source, k)
        episodes.append(window_to_episode(clip, fw, start_offset=start_offset, **ed))
```

Then update `build_edl`'s docstring: change the sentence "Each selection episode
references a window by (source, integer index) into FOOTAGE and supplies editorial
fields" to "Each selection episode references a window by (source, integer index) —
or a two-element `[i, j]` span merged into one episode (§3b) — into FOOTAGE and
supplies editorial fields".

- [ ] **Step 5: Run the new tests AND the full `test_edit_plan.py` (regression)**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -v`
Expected: all PASS — the new span tests pass, and every pre-existing test
(single-window resolution, OOB `window 3 out of range for B.mp4 (has 1)`, bad
type `'window' must be an integer`, bool rejection, pacing, back-edge) stays green.
The single-window error strings are unchanged and the moved clip-resolution does
not reorder any tested failure.

- [ ] **Step 6: Commit**

```bash
git add scripts/edit_plan.py tests/lib/test_edit_plan.py
git commit -m "feat: build_edl accepts a [i, j] span window that merges into one episode"
```

---

### Task 2: integration golden — a span survives the SP3→SP1 seam

**Files:**
- Modify: `tests/integration/test_edit_plan.py`

- [ ] **Step 1: Add the span fixtures + the test**

Append to `tests/integration/test_edit_plan.py` (reuses the module's existing
`_project_json` and `_fake_track_pe`):

```python
def _span_footage_json(tmp_path, source):
    # three windows in one 3s shot (no scene cut) → a [0,1] span merges the first two,
    # window 2 stays single; the two episodes sit at different x so phash variety holds
    f = Footage(clips=[FootageClip(source=source, dur=3.0, res=(1920, 1080), fps=30.0, windows=[
        FootageWindow(start=0.2, dur=0.7, shot_type="wide", people=1, motion=0.3, shake=0.0),
        FootageWindow(start=1.1, dur=0.7, shot_type="wide", people=1, motion=0.3, shake=0.0),
        FootageWindow(start=2.1, dur=0.7, shot_type="wide", people=1, motion=0.3, shake=0.0)])])
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict()))
    return str(p)


def _span_selection_json(tmp_path, source):
    sel = {"episodes": [
        {"source": source, "window": [0, 1], "composition": "lead", "grid": "thirds", "crop_scale": 0.8},
        {"source": source, "window": 2, "composition": "lead", "grid": "thirds", "crop_scale": 0.8}]}
    p = tmp_path / "selection.json"
    p.write_text(json.dumps(sel))
    return str(p)


def test_span_selection_becomes_edl_becomes_reel(sample_clip, tmp_path, monkeypatch):
    fj = _span_footage_json(tmp_path, sample_clip.name)
    sj = _span_selection_json(tmp_path, sample_clip.name)
    pj = _project_json(tmp_path)
    plan_out = tmp_path / "plan"

    res = edit_plan.write_edit_plan(fj, sj, pj, str(plan_out))
    assert res["status"] == "written", res
    edl_path = plan_out / "EDL.json"
    edl = json.loads(edl_path.read_text())
    assert len(edl["episodes"]) == 2
    # episode 0 is the merged span: from window 0's start (0.2) to window 1's end (1.8)
    assert edl["episodes"][0]["start"] == 0.2 and edl["episodes"][0]["dur"] == pytest.approx(1.6)

    _fake_track_pe(monkeypatch)
    reel = edl_to_reel.edl_to_reel(
        str(edl_path), pj, footage_root=str(sample_clip.parent),
        work_dir=str(tmp_path / "w"), out_dir=str(tmp_path / "out"))
    assert reel["status"] == "delivered", reel
    out = Path(reel["output"])
    assert out.exists() and out.name == "REEL_v1.mp4"
```

- [ ] **Step 2: Run the integration test**

Run: `.venv/bin/python -m pytest tests/integration/test_edit_plan.py -v`
Expected: both the pre-existing `test_selection_becomes_edl_becomes_reel` and the
new `test_span_selection_becomes_edl_becomes_reel` PASS (real ffmpeg; needs the
provisioned env). If the run reports the integration marker is deselected, add
`-m integration`.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_edit_plan.py
git commit -m "test: a [i, j] span episode survives the real SP3->SP1 seam"
```

---

### Task 3: `edit-plan` SKILL — span authoring guidance

**Files:**
- Modify: `skills/edit-plan/SKILL.md`

- [ ] **Step 1: Add the span paragraph after the `start_offset` note**

In `skills/edit-plan/SKILL.md`, the paragraph that begins "`start_offset`
(optional, per selection episode) moves the in-point later…" ends with "…lands a
better ending." Immediately after that paragraph, insert:

```markdown
A **span** merges adjacent windows into one episode: set `window` to a two-element
list `[i, j]` instead of a single index, and the episode runs from the start of
window `i` to the end of window `j`, carrying the footage between them. Use it when
consecutive windows are one arc — an approach into an action, or
"turn → drive → turn" — so the reel plays them as one continuous beat and the music
falls on the true length, instead of hard-cutting between windows that are one
motion. A span stays within **one clip**, its indices must be **adjacent**, and it
**cannot cross a scene cut** — the build refuses that, naming the cut (split into two
episodes there). `start_offset` still applies, moving the merged in-point later.
```

- [ ] **Step 2: Show a span in the shape example**

In the same file, in step 2, the `episodes` example currently has two entries.
Add a span entry between them so the shape is:

```
    {
      "episodes": [
        {"source": "MVI_3739.mp4", "window": 2, "composition": "lead",
         "grid": "thirds", "layout": "fill", "motion": "lateral:right", "hero": "largest"},
        {"source": "MVI_3739.mp4", "window": [4, 6], "composition": "center", "grid": "thirds"},
        {"source": "MVI_3998.mp4", "window": 1, "composition": "center", "grid": "phi"}
      ],
      "music": null, "cap": 3, "target_dur": null
    }
```

And in the line introducing that example, change the parenthetical "The shape
(integer window indices + editorial only — no timestamps):" to "The shape (integer
window indices — or a `[i, j]` span — + editorial only, no timestamps):".

- [ ] **Step 3: Verify the SKILL reads cleanly**

Run: `.venv/bin/python -m pytest tests/ -k skill -q` (if any SKILL-lint test
exists) — otherwise re-read the file top-to-bottom to confirm the new paragraph
and example are well-formed Markdown and the constraints match the design
(one clip, adjacent, no scene cut).

- [ ] **Step 4: Commit**

```bash
git add skills/edit-plan/SKILL.md
git commit -m "docs: edit-plan SKILL teaches the [i, j] span merge"
```

---

### Task 4: docs sync + full suite

**Files:**
- Modify: `CLAUDE.md`, `docs/build-status.md`, `docs/pipeline-map.md`

- [ ] **Step 1: CLAUDE.md registry rows**

In `CLAUDE.md`'s Quick Reference table, after the "Intake activity-units plan"
row, add two rows:

```markdown
| Edit-plan span-merge design | [2026-07-26-edit-plan-span-merge-design.md](docs/specs/2026-07-26-edit-plan-span-merge-design.md) | Feedback #3 slice 3b: an EDL episode may reference a window range `"window": [i, j]`; `edit_plan._merge_windows` synthesizes one `FootageWindow` over `[min start … max end]` (union `track_ids`, inherit window i's shot_type/description) and the unchanged `window_to_episode` projects it — so `FootageClip.room_after` refuses a range that straddles a scene cut for free (crossing a presence transition inside one shot is allowed). Thin: no contract/intake/pacing change. |
| Edit-plan span-merge plan | [2026-07-26-edit-plan-span-merge.md](docs/plans/2026-07-26-edit-plan-span-merge.md) | Tasks 0–4: `_merge_windows` envelope + scene-cut refusal, `build_edl` `window`-overload + `_resolve_window`, real-ffmpeg SP3→SP1 span golden, edit-plan SKILL span guidance, docs sync. |
```

Then in the existing "Intake activity-units design" row, change the trailing
sentence "**3b (`edit_plan` span [i..j] merge) deferred.**" to "3b (`edit_plan`
span merge) landed 2026-07-26 — its own slice."

- [ ] **Step 2: docs/build-status.md**

Change the `_Last updated:` line to `_Last updated: 2026-07-26._`. Add a new bullet
at the top of the `## Done` list (newest first):

```markdown
- **Edit-plan span merge (feedback #3, slice 3b) DONE (2026-07-26)** — plan
  `docs/plans/2026-07-26-edit-plan-span-merge.md` + design
  `docs/specs/2026-07-26-edit-plan-span-merge-design.md`, Tasks 0–4. An EDL episode
  may reference a range of adjacent footage windows — `"window": [i, j]` in
  `selection.json` — and `edit_plan` projects the range onto one continuous episode
  spanning `[min start … max end]`, carrying the connective footage between the
  windows ("turn → drive → turn"). New pure `edit_plan._merge_windows` synthesizes
  one `FootageWindow` (union `track_ids`, inherit window i's shot_type/description)
  fed to the unchanged `window_to_episode`, so `FootageClip.room_after` refuses a
  range that straddles a scene cut for free (a presence transition inside one shot
  is allowed); `_resolve_window` branches the `window` ref (int → single, `[i, j]`
  → merge) with fail-loud validation. No contract, intake, or pacing change; the
  single-window path is byte-for-byte unchanged.
```

Then, in the 3a bullet, change its trailing "**Deferred:** 3b — `edit_plan`
merging adjacent activity-unit spans `[i..j]` into one episode — its own slice."
to "3b (`edit_plan` span merge) landed 2026-07-26 — see the entry above."

- [ ] **Step 3: docs/pipeline-map.md**

In the 5.2 row (line with `footage-intake`), change "#3 slice 3a landed 2026-07-25
(3b `edit_plan` span-merge deferred)" to "#3 slice 3a landed 2026-07-25, 3b
`edit_plan` span-merge landed 2026-07-26".

In the 5.7 row (`| 5.7  | edit-plan | ...`), append to the description cell (before
the closing `|`): "; a `selection.json` episode may reference a window range
`"window": [i, j]` to merge adjacent activity units into one episode (3b,
2026-07-26)".

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass, 2 pre-existing skips (demucs + network, environmental). No
golden fixture moved (3b adds no numeric pins to existing goldens).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/build-status.md docs/pipeline-map.md
git commit -m "docs: register edit-plan span merge (feedback #3, slice 3b)"
```

---

## After all tasks

Dispatch a final whole-slice code review (fresh reviewer over
`main..feat/edit-plan-span-merge`), fix any Critical/Important findings as
separate follow-up commits, then hand to
`superpowers:finishing-a-development-branch`.

## Self-review notes (plan vs. spec)

- **Spec §2 (window overload)** → Task 1 (`_resolve_window` accepts int or
  `[i, j]`).
- **Spec §3 (`_merge_windows`)** → Task 0 (envelope, `track_ids` union, inherit
  window i, `room_after` scene-cut refusal with the cut named).
- **Spec §4 (`build_edl` wiring + validation)** → Task 1 (all six validation
  cases: reversed, `i==j`, OOB `j`, length≠2, non-int, bool; plus scene-cut
  crossing through the merge).
- **Spec §5 (no pacing/contract change)** → verified by Task 1's regression run
  (existing pacing/back-edge tests stay green) and Task 2's round-trip.
- **Spec §6 (SKILL)** → Task 3.
- **Spec §7 (testing)** → Tasks 0–2 (unit envelope/refusal/inheritance,
  build_edl span + validation, integration SP3→SP1 span golden).
- **Spec §8 (landmines)** → Task 0 (no float transcription via min/max by
  reference; fail-loud scene-cut with the cut named; `room_after` single
  authority).
- Type/name consistency: `_merge_windows(clip, i, j)`,
  `_resolve_window(clip, window, source, k)`, fixture `_merge_clip`,
  `_span_footage_json`/`_span_selection_json` used consistently across tasks.
