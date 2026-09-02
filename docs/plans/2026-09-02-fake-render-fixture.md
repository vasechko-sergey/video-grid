# Shared fake-renderer fixture — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make it impossible for a test that renders through a fake `process_episode` to declare
a `project.json` canvas its fake never honours, by giving the fake and the project **one**
geometry value instead of two that happen to agree.

**Architecture:** One factory fixture in `tests/conftest.py` returns a `FakeRender` object that
holds `src_dims`. Calling it installs the fake `process_episode` (which writes `route.json`,
`path.json`, `path.meta.json` and a `-c:v copy` clip, all derived from `src_dims`); its
`.project(tmp_path)` writes the `project.json` whose `canvas` is that same `src_dims`. Four
integration files drop five local copies and adopt it. Three pure-`edit_plan` gate tests keep
their deliberately-mismatched local project writer — see design §3.

**Tech stack:** pytest fixtures, `monkeypatch`, `scripts.lib.ffbin`/`proc`, real ffmpeg
(`-c:v copy`), no production code.

**Design:**
[2026-09-02-fake-render-fixture-design.md](../specs/2026-09-02-fake-render-fixture-design.md)

## Global Constraints

- **No production file changes.** This slice touches `tests/` and `docs/` only. If a task seems
  to need a change under `scripts/`, stop and report — that is a finding, not a step.
- **The suite count must not drop.** Baseline is **3398 passed, 1 skipped**. A refactor that
  silently stops collecting a test looks exactly like success.
- Run every suite command with `PYTHONDONTWRITEBYTECODE=1`. A one-byte edit can match the
  previous file's size and mtime-second, and CPython then serves a stale `.pyc`.
- Branch is `feat/fake-render-fixture`, already created off `main`. Do not commit to `main`.
- Line length ≤ 100 chars in docs; follow [coding-standards.md](../coding-standards.md).
- `tests/integration/test_edit_plan.py`'s `_project_json` (9:16) and its three gate tests
  (`test_sp3_stops_on_a_variety_gap_then_passes_with_a_waiver`,
  `test_sp3_delivered_geometry_is_what_decides`,
  `test_sp3_refuses_a_repeat_the_user_forbade_and_records_the_rule_when_it_holds`) **must not**
  move onto the fixture. Their mismatch is the thing they test.

---

### Task 1: The `fake_render` fixture and its invariant

**Files:**
- Modify: `tests/conftest.py` (append after the `need_filter` fixture, ~line 230)
- Test: `tests/test_fake_render.py` (create)

**Interfaces:**
- Consumes: `scripts.lib.ffbin`, `scripts.lib.proc` (already imported in `conftest.py`).
- Produces: pytest fixture `fake_render`, callable as
  `fake_render(monkeypatch, src_dims=(1920, 1080), delivery="native", pan_aware=False)`,
  returning a `FakeRender` with attributes `src_dims: tuple[int, int]`, `delivery: str`,
  `pan_aware: bool` and one method `project(tmp_path) -> str` (the `project.json` path).
  Calling the factory installs the fake; `project()` may be called before or after.

- [x] **Step 1: Write the failing test**

Create `tests/test_fake_render.py`:

```python
"""The fixture's own invariant: one geometry, not two that agree.

This is the whole point of design 2026-09-02 — a test that renders through the fake
cannot declare a canvas the fake does not honour, because the declaration and the
sidecar are two renderings of one `src_dims`. If someone reintroduces a literal on
either side, this test is what notices.
"""
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("dims", [(1920, 1080), (640, 360)])
def test_the_project_canvas_is_the_dims_the_fake_writes(dims, tmp_path, monkeypatch):
    from scripts import edl_to_reel

    fake = fake_render_factory(monkeypatch, src_dims=dims)     # replaced in step 3
    project = json.loads(Path(fake.project(tmp_path)).read_text())

    epdir = tmp_path / "ep0"
    edl_to_reel.process_episode.process_episode(
        {"segment": "unused.mp4", "out_path": str(tmp_path / "ep0.mp4")}, str(epdir))
    meta = json.loads((epdir / "path.meta.json").read_text())

    assert project["canvas"] == list(dims)
    assert meta["canvas"] == project["canvas"] == meta["src_dims"]


def test_pan_aware_writes_no_route_for_a_pan_episode(tmp_path, monkeypatch):
    from scripts import edl_to_reel

    fake = fake_render_factory(monkeypatch, src_dims=(1920, 1080), pan_aware=True)
    fake.project(tmp_path)
    epdir = tmp_path / "ep0"
    edl_to_reel.process_episode.process_episode(
        {"segment": "unused.mp4", "out_path": str(tmp_path / "ep0.mp4"),
         "pan": {"from": 0.0, "to": 1.0}}, str(epdir))

    assert not (epdir / "route.json").exists()
    assert json.loads((epdir / "path.meta.json").read_text())["pan"] is True
```

Note the two tests call the fake with a `segment` that does not exist: they assert on the
sidecars, not on a clip. Step 3's implementation guards the copy with
`if Path(manifest["segment"]).exists()` for exactly this reason — every migrated call site
passes a real segment, so the copy still runs everywhere it matters.

- [x] **Step 2: Run it and watch it fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_fake_render.py -q`
Expected: FAIL — `NameError: name 'fake_render_factory' is not defined`.

- [x] **Step 3: Implement the fixture**

Append to `tests/conftest.py`:

```python
@dataclass
class FakeRender:
    """A fake `process_episode` and the `project.json` that agrees with it, by construction.

    The whole class of defect this closes (design 2026-09-02 §0) is a test stating its
    geometry twice — once in `project.json`, once in the `path.meta.json` its fake writes
    — with nothing keeping the two in step. Here there is one `src_dims` and both readings
    come off it, so they cannot disagree.

    NOT for tests that render nothing. `tests/integration/test_edit_plan.py`'s three
    pure-`edit_plan` gate tests (variety-gap, delivered-geometry, constraints) need a
    declared canvas that deliberately does NOT match the source — that mismatch is what
    they prove (design §3). They keep their own writer; do not "unify" them onto this.
    """
    src_dims: tuple
    delivery: str = "native"
    pan_aware: bool = False

    def project(self, tmp_path) -> str:
        p = Path(tmp_path) / "project.json"
        p.write_text(json.dumps({"purpose": "reel", "canvas": list(self.src_dims),
                                 "delivery": self.delivery}))
        return str(p)


@pytest.fixture
def fake_render():
    """Install a fake `process_episode` that copies instead of reframing, and hand back the
    object that also writes the matching `project.json`.

    The real `process_episode` cannot run in these tests: the synthetic clips are a box, not
    a person, so real YOLO tracking returns an empty route and the tracking ladder's
    optical-flow fallback produces a route too jittery for `check_episode`'s gates — the run
    escalates rather than delivering. Faking the mechanical middle (tracking + reframe +
    check_episode) is what keeps those tests on the wiring they are about.

    The fake mirrors what a real `mechanical_pass` leaves on disk: `route.json`, `path.json`
    and `path.meta.json` beside the clip, so `build_reel`'s frozen geometry reads real files.
    Every number is derived from `src_dims`: the route point is the frame centre with a
    `w//16 x h//9` box (exactly the 120x120 the 1920x1080 call sites used by hand), and the
    sidecar is a plain full-frame `fill` — which is the truth, because the clip is a
    `-c:v copy` and no crop is taken.
    """
    def _install(monkeypatch, src_dims=(1920, 1080), delivery="native", pan_aware=False):
        from scripts import edl_to_reel

        w, h = src_dims

        def fake_pe(manifest, project_dir, route_path=None):
            Path(project_dir).mkdir(parents=True, exist_ok=True)
            is_pan = pan_aware and manifest.get("pan") is not None
            if not is_pan:
                (Path(project_dir) / "route.json").write_text(json.dumps(
                    [{"t": 0.0, "x": w // 2, "y": h // 2,
                      "w": w // 16, "h": h // 9, "id": 1}]))
            (Path(project_dir) / "path.json").write_text(json.dumps([0]))
            meta = {"mode": "fill", "crop_w": w, "crop_h": h, "crop_y": 0,
                    "src_dims": [w, h], "canvas": [w, h], "out_dims": [w, h],
                    "rect_px": [0, 0, w, h], "freedom": 0}
            if pan_aware:
                meta["pan"] = is_pan
            (Path(project_dir) / "path.meta.json").write_text(json.dumps(meta))
            if Path(manifest["segment"]).exists():
                proc.run([ffbin.ffmpeg(), "-y", "-i", manifest["segment"], "-c:v", "copy",
                          "-an", manifest["out_path"]])
            return {"status": "mechanical_pass", "clip": manifest["out_path"]}

        monkeypatch.setattr(edl_to_reel.process_episode, "process_episode", fake_pe)
        # process_episode is faked, but edl_to_reel calls track.ensure_model ITSELF above the
        # pool — unstubbed, these goldens also construct a real YOLO (importing torch, and
        # downloading 6MB on a cold cache) for a tracking pass they never run.
        monkeypatch.setattr(edl_to_reel.track, "ensure_model", lambda m: None)
        return FakeRender(tuple(src_dims), delivery, pan_aware)
    return _install
```

Add to `tests/conftest.py`'s imports at the top: `import json` and
`from dataclasses import dataclass`.

The `if Path(manifest["segment"]).exists()` guard is what lets the fixture's own invariant
tests exercise the sidecars without a real clip. Every migrated call site passes a real
segment, so the copy still runs there.

- [x] **Step 4: Point the test at the real fixture**

In `tests/test_fake_render.py`, add `fake_render` to each test's parameters and replace both
`fake_render_factory(` calls with `fake_render(`.

- [x] **Step 5: Run the test**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_fake_render.py -q`
Expected: PASS, 3 tests (two parametrized + the pan one).

- [x] **Step 6: Prove the invariant test actually discriminates**

Temporarily change `FakeRender.project` to write `"canvas": [1080, 1920]`.
Run the same command. Expected: both parametrized tests FAIL.
Restore the file, re-run, confirm green, and confirm `git diff tests/conftest.py` shows only the
intended addition.

- [x] **Step 7: Commit**

```bash
git add tests/conftest.py tests/test_fake_render.py
git commit -m "test: a fake renderer that owns its geometry, and the project that reads it"
```

---

### Task 2: Migrate `test_front_spine.py` (both fakes)

**Files:**
- Modify: `tests/integration/test_front_spine.py` — delete `_project` (lines ~23-49),
  `_fake_track_pe` (~63-97) and `_fake_track_or_pan_pe` (~132-158); rewrite four call sites.
- Test: the file's own four tests are the proof.

**Interfaces:**
- Consumes: `fake_render` from Task 1.
- Produces: nothing new.

- [x] **Step 1: Rewrite the four tests**

`test_edl_drives_a_silent_reel_end_to_end` and `test_edl_drives_a_reel_with_music` replace
`_fake_track_pe(monkeypatch)` + `_project(tmp_path)` with:

```python
    fake = fake_render(monkeypatch, src_dims=(1920, 1080))
```

and pass `fake.project(tmp_path)` where `_project(tmp_path)` was. Add `fake_render` to each
test's parameter list.

`test_edl_with_a_pan_episode_drives_a_reel_without_the_route_it_never_wrote` and
`test_edl_mixing_tracked_and_pan_episodes_keeps_the_tracked_route` do the same with
`pan_aware=True`:

```python
    fake = fake_render(monkeypatch, src_dims=(1920, 1080), pan_aware=True)
```

Every existing assertion stays exactly as it is — in particular the pan tests' `route is None`,
the on-disk `not (...).exists()` checks, and the `safe_zones` / `key_action` `skipped_episodes`
assertions. Those are what prove `pan_aware` is not a no-op.

- [x] **Step 2: Delete the three local helpers**

Remove `_project`, `_fake_track_pe` and `_fake_track_or_pan_pe`. Move nothing else: `_edl`,
`_edl_all_pan`, `_edl_mixed` and `_spy_on_build_reel` stay.

- [x] **Step 3: Keep the module docstring honest**

The docstring says the mechanical middle is faked and "the delivered reel keeps the source dims,
not the project canvas". That second clause is now the fixture's guarantee rather than a
coincidence — reword it to say the project canvas IS the source dims, via `fake_render`, and
point at `docs/specs/2026-09-02-fake-render-fixture-design.md`.

- [x] **Step 4: Run the file**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/integration/test_front_spine.py -q`
Expected: PASS, 4 tests.

- [x] **Step 5: Prove `pan_aware` still carries its weight**

Temporarily pass `pan_aware=False` in the two pan tests. Run the file.
Expected: both pan tests FAIL (`route is None` and the on-disk absence both break).
Restore, re-run, confirm 4 pass, confirm `git diff` shows only the intended change.

- [x] **Step 6: Commit**

```bash
git add tests/integration/test_front_spine.py
git commit -m "test: front_spine takes its geometry from the shared fake renderer"
```

---

### Task 3: Migrate `test_edit_plan.py`'s two driver tests only

**Files:**
- Modify: `tests/integration/test_edit_plan.py` — delete `_fake_track_pe` (~21-41) and
  `_project_json_source_aspect` (~73-92); rewrite two call sites; KEEP `_project_json`.

**Interfaces:**
- Consumes: `fake_render` from Task 1.
- Produces: nothing new.

- [x] **Step 1: Rewrite the two driver tests**

In `test_selection_becomes_edl_becomes_reel` and `test_span_selection_becomes_edl_becomes_reel`,
add `fake_render` to the parameters and replace the helper pair:

```python
    fake = fake_render(monkeypatch, src_dims=(1920, 1080))
    pj = fake.project(tmp_path)
```

then delete the later `_fake_track_pe(monkeypatch)` line — the factory already installed it.
`pj` continues to be passed to `edit_plan.write_edit_plan` and `edl_to_reel.edl_to_reel`
unchanged.

- [x] **Step 2: Delete only the two now-unused helpers**

Remove `_fake_track_pe` and `_project_json_source_aspect`. **Keep `_project_json`** and its
comment. Extend that comment with one sentence naming the fixture and why these three tests are
not on it:

```python
    # Deliberately NOT `fake_render` (design 2026-09-02 §3): the fixture ties the declared
    # canvas to the source, and these three tests need them to differ — that is what they
    # prove. A gate test moved onto the fixture fails loudly; a driver test left off it fails
    # silently.
```

- [x] **Step 3: Run the file**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/integration/test_edit_plan.py -q`
Expected: PASS, all tests in the file (5 at time of writing).

- [x] **Step 4: Prove the gate tests are still on the 9:16 declaration**

Temporarily point `test_sp3_delivered_geometry_is_what_decides`'s `pp_9x16` at
`fake_render(monkeypatch, src_dims=(3840, 2160)).project(tmp_path / "c")`.
Run the file. Expected: that test FAILS — the variety gap it asserts disappears once the
declared canvas matches the source, which is precisely design §3's point.
Restore, re-run, confirm green, confirm `git diff`.

- [x] **Step 5: Commit**

```bash
git add tests/integration/test_edit_plan.py
git commit -m "test: edit_plan's two driver tests move onto the shared fake renderer"
```

---

### Task 4: Migrate `test_outro.py` and `test_ramp.py`

**Files:**
- Modify: `tests/integration/test_outro.py` — delete `_fake_track_pe` (~101-124) and
  `_project_json` (~148-170); rewrite the one test that uses them.
- Modify: `tests/integration/test_ramp.py` — delete `_fake_track_pe` (~266-289) and
  `_write_project` (~229-245); rewrite both tests.

**Interfaces:**
- Consumes: `fake_render` from Task 1.
- Produces: nothing new.

- [x] **Step 1: Rewrite `test_outro.py`'s call site**

Both `W, H = 640, 360` and the `long_edge:240` delivery are already module constants. Replace
the `_fake_track_pe(monkeypatch)` + `pj = _project_json(tmp_path)` pair with:

```python
    fake = fake_render(monkeypatch, src_dims=(W, H), delivery="long_edge:240")
    pj = fake.project(tmp_path)
```

adding `fake_render` to the test's parameters. Delete both local helpers. The long comment on
`_project_json` explaining the 9:16 repair goes away with it — the fixture's docstring and the
design now carry that reasoning; do not copy it to the call site.

- [x] **Step 2: Rewrite `test_ramp.py`'s two call sites**

`test_a_ramped_episode_reaches_the_reel_at_its_played_length` takes the same two lines as
Step 1. `test_the_edl_markdown_reports_the_ramp` renders nothing but still needs a project:

```python
    proj = fake_render(monkeypatch, src_dims=(W, H), delivery="long_edge:240").project(tmp_path)
```

It gains `monkeypatch` and `fake_render` parameters. Installing a fake it never triggers is
harmless — the test calls only `edit_plan.write_edit_plan` — and it keeps one source of truth
for the canvas rather than a second hand-written project beside it.

Delete `_write_project` and `_fake_track_pe`. The section comment above them (the long note on
why the mechanical middle is faked here) keeps its first two paragraphs about ramp-specific
scope; drop only the sentences that describe the now-deleted helpers' internals.

- [x] **Step 3: Run both files**

Run:
```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
    tests/integration/test_outro.py tests/integration/test_ramp.py -q
```
Expected: PASS, all tests in both files (15 at time of writing, together with Task 3's file).

- [x] **Step 4: Prove the delivery parameter is real**

Temporarily drop `delivery="long_edge:240"` from `test_ramp.py`'s ramped-reel test so it falls
back to `"native"`. Run that test with `-q`. Expected: it still passes but takes materially
longer (a full-size encode instead of a 240-long-edge one) — record the two wall-clock numbers
in the commit message. If it does NOT get slower, the parameter is not reaching the encode and
that is a finding to report, not to paper over.
Restore and re-run.

- [x] **Step 5: Commit**

```bash
git add tests/integration/test_outro.py tests/integration/test_ramp.py
git commit -m "test: outro and ramp take their geometry from the shared fake renderer"
```

---

### Task 5: Full-suite proof and docs sync

**Files:**
- Modify: `docs/backlog.md` (the fixture-class row, P3 → "Docs / test scaffolding")
- Modify: `docs/build-status.md` (a `## Done` entry at the top)
- Modify: `CLAUDE.md` (two Quick Reference rows: the design and this plan)

- [x] **Step 1: Run the whole suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q 2>&1 | tail -5`
Expected: **3401 passed, 1 skipped** — the 3398 baseline plus Task 1's three new tests. Any
other number needs explaining before proceeding: fewer means a test stopped being collected.

- [x] **Step 2: Confirm no production file moved**

Run: `git diff --stat main...HEAD -- scripts/`
Expected: empty output. If not, stop and report.

- [x] **Step 3: Rewrite the backlog row**

The row currently ends with "A shared fixture helper that derives the declared canvas FROM
whatever the fake renderer actually produces, honouring that split, would stop a fifth copy from
reintroducing this". Replace that sentence with what was built: the `fake_render` fixture, the
four files on it, the three gate tests deliberately off it, and the limit that survives —
nothing forces a new test to use the fixture, and a copy written from scratch would still be
born dormant behind the drift guard. Keep the row's history intact; only its open tail changes.

- [x] **Step 4: Add the `## Done` entry**

At the top of `docs/build-status.md`'s `## Done` list, add an entry naming the design and plan,
the census (30 declare a canvas / 8 fake / 4 render), what moved, what deliberately did not, the
suite numbers before and after, and the mutation checks from Tasks 1, 2, 3 and 4 with their
results. Follow the existing entries' shape.

- [x] **Step 5: Add the two `CLAUDE.md` registry rows**

One row for the design, one for the plan, in the Quick Reference table beside the other test-
scaffolding entries. One line each, saying what the reader gets — including §3, since that is
the part a future unifier needs to read before touching `test_edit_plan.py`.

- [x] **Step 6: Commit**

```bash
git add docs/backlog.md docs/build-status.md CLAUDE.md
git commit -m "docs: the fixture class closes with a fixture, not a fifth repair"
```

---

## Self-review

**Spec coverage.** §1 (the shape) → Task 1. §2 (census; only the four rendering files) → Tasks
2-4, and the census itself is restated in Task 5's Done entry. §3 (what does not move) → Task 3
Steps 2 and 4, plus the fixture docstring in Task 1 Step 3. §4 (testing) → Task 1's invariant
test, Task 2 Step 5's `pan_aware` check, Task 5 Step 1's count. §5 (out of scope) → the Global
Constraints' "no production file changes" and Task 5 Step 2's machine check. §6 (honest limits)
→ Task 5 Step 3 carries them into the backlog row rather than letting them expire with the
design.

**Type consistency.** `fake_render(monkeypatch, src_dims=..., delivery=..., pan_aware=...)` and
`FakeRender.project(tmp_path) -> str` are used identically in Tasks 2, 3 and 4. `src_dims` is a
tuple everywhere; `project()` returns a `str` path, matching what `edl_to_reel.edl_to_reel` and
`edit_plan.write_edit_plan` already take.

**Known gap, deliberate.** The route box becomes `w//16 x h//9`, which reproduces the
1920x1080 sites' `120x120` exactly but gives `40x40` where `test_outro.py`/`test_ramp.py` wrote
`40x80`. Verified 2026-09-02 that no test asserts a route bounding box — they assert presence,
absence and file existence only — so this is safe; design §6 records it as the one behaviour
change in the slice.
