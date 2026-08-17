# Cheap P2 chores — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close four cheap P2 backlog rows — a licence, the authoring skill's knob
enumeration (#5), editorial constraints in `montage status`, and a test fixture
long enough to carve more than one window — and correct a fifth row's size.

**Architecture:** Four independent changes sharing nothing but their size. No
render path, no wire contract, no `CACHE_VERSION` bump, no golden moves.

**Tech Stack:** Python 3.13, pytest, real ffmpeg via `lib/ffbin`.

**Design:** [2026-08-17-cheap-p2-chores-design.md](../specs/2026-08-17-cheap-p2-chores-design.md)

---

## Global Constraints

- **Fail-loud contract, imports at top, typing** —
  [coding-standards.md](../coding-standards.md).
- **Whole-object asserts** where a shape is being pinned —
  [testing-guide.md](../testing-guide.md).
- **Scripts run as modules** (`pythonpath = .`); Python is `.venv/bin/python`.
- **No new dependency**, no network at test time, no system mutation.
- Every new test must be watched **fail first**. A test that passes against the
  unmodified tree is proving nothing and must be strengthened, not accepted.

---

### Task 0: LICENSE + the manifest field

**Files:**
- Create: `LICENSE`
- Modify: `.claude-plugin/plugin.json`, `README.md`
- Test: `tests/test_plugin_manifests.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_plugin_manifests.py`:

```python
def test_plugin_manifest_declares_the_agpl():
    data = json.loads((CP / "plugin.json").read_text())
    assert data["license"] == "AGPL-3.0-only"


def test_repo_ships_the_agpl_text():
    # The licence is constrained by a dependency, not chosen: ultralytics is
    # AGPL-3.0 and intake imports it on the main path (design §1). Pin the text's
    # identity, not merely the file's existence — an empty LICENSE would pass that.
    text = (REPO / "LICENSE").read_text()
    assert text.startswith(" " * 20 + "GNU AFFERO GENERAL PUBLIC LICENSE")
    assert "Version 3, 19 November 2007" in text.splitlines()[1]
```

- [ ] **Step 2: Run them and watch both fail**

Run: `.venv/bin/python -m pytest tests/test_plugin_manifests.py -v`
Expected: `KeyError: 'license'` and `FileNotFoundError: LICENSE`.

- [ ] **Step 3: Install the licence text from the dependency that forced it**

The canonical AGPL-3.0 text is already on this machine, shipped by the very
dependency that makes AGPL the necessary choice — 661 lines / 34523 bytes:

```bash
cp "$(.venv/bin/python -c 'import ultralytics,pathlib;print(pathlib.Path(ultralytics.__file__).parents[1])')"/ultralytics-*.dist-info/licenses/LICENSE LICENSE
```

Verify before continuing: `wc -lc LICENSE` must print `661` and `34523`.

- [ ] **Step 4: Add the manifest field**

In `.claude-plugin/plugin.json`, after `"description"`:

```json
  "license": "AGPL-3.0-only",
```

- [ ] **Step 5: The README third-party note**

Add a short section so a reader learns *why* the licence is what it is without
reverse-engineering it from `requirements.txt`:

```markdown
## Licence

AGPL-3.0 — see [LICENSE](LICENSE).

Not a preference: `ultralytics` (the YOLO11 runtime footage-intake depends on)
is AGPL-3.0, and `scripts/intake.py` imports it on the main path, so a
permissive licence over this tree would be internally inconsistent. The model
weights themselves are not redistributed here — `.gitignore` excludes
`yolo11*.pt` and `setup.sh` downloads them at install time.

This declares a licence; it is not a licence audit. The transitive dependency
tree has not been walked.
```

- [ ] **Step 6: Run the tests and the manifest suite**

Run: `.venv/bin/python -m pytest tests/test_plugin_manifests.py -v`
Expected: 5 passed. `test_claude_plugin_holds_only_manifests` must still pass —
`LICENSE` goes in the repo root, never in `.claude-plugin/`.

- [ ] **Step 7: Commit**

```bash
git add LICENSE .claude-plugin/plugin.json README.md tests/test_plugin_manifests.py
git commit
```

Message: name the constraint, not the act — the licence follows from
ultralytics being AGPL and imported on intake's main path, and the weights not
being redistributed is what narrows the question to linking alone.

---

### Task 1: The authoring skill enumerates every knob (#5)

**Files:**
- Modify: `skills/edit-plan/SKILL.md`
- Test: `tests/test_skill_convention.py`

- [ ] **Step 1: Write the failing coverage test**

Append to `tests/test_skill_convention.py` (adjust the repo-root constant to
whatever that file already defines):

```python
def test_edit_plan_skill_names_every_authorable_episode_field():
    """Every EDLEpisode field appears by name in the authoring skill.

    The skill is the ONLY place an author learns a knob exists, and it drifted
    silently once already: five fields (crop_aspect, crop_scale, border_px,
    border_color, color_means) were authorable and undocumented until 2026-08-17.
    This proves PRESENCE of the name, never that the explanation beside it is
    correct or current (design §2.2) — it stops the silent half of the drift."""
    import dataclasses
    from scripts.lib.edl import EDLEpisode
    skill = (REPO / "skills" / "edit-plan" / "SKILL.md").read_text()
    missing = sorted(f.name for f in dataclasses.fields(EDLEpisode)
                     if f.name not in skill)
    assert missing == [], (
        f"{len(missing)} EDLEpisode field(s) the authoring skill never names: "
        f"{missing}. Document them in skills/edit-plan/SKILL.md — an authorable "
        f"knob nobody can find is the same as one that does not exist")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py -k every_authorable -v`
Expected: FAIL naming exactly
`['border_color', 'border_px', 'color_aspect'...]` — the real list is
`['border_color', 'border_px', 'color_means', 'crop_aspect', 'crop_scale']`.
If the failure names a different set, re-measure before writing prose.

- [ ] **Step 3: Document the five, beside the knobs they belong with**

In `skills/edit-plan/SKILL.md`, step 2's bullet list. The four geometry knobs go
directly after the `background` / `background_color` bullet (they are the
`insert`-card's own geometry), `color_means` after the colour-grade material:

```markdown
   - `crop_aspect` (optional) — the crop rectangle's aspect as `"9:16"` or
     `[9, 16]`. Omit it and the manifest picks: the canvas for `fill`, the
     source's own aspect for `fit`/`insert`. Author it only to take a crop
     shaped like neither.
   - `crop_scale` (optional, default `1.0`) — the crop's size as a fraction of
     the largest one that fits. Below `1.0` tightens the frame and buys
     tracking freedom; it is a still framing choice, unlike `zoom`, which
     changes the crop width over time.
   - `border_px` / `border_color` (optional, `insert` only, default `0` /
     `"white"`) — the card's border in delivered pixels and its colour. `0`
     draws none.
   - `color_means` (optional) — the composition's target channel means as
     `[r, g, b]`, the reference `check_episode`'s colour check measures the
     delivered clip against. Leave it alone unless a shot must match a
     specific reference; the colour GRADE knobs above are what you reach for
     to change how a clip looks.
```

- [ ] **Step 4: Add the reference table at the end of step 2**

The row asked for the full set "in one place". The prose stays — it carries the
*why* and the refusals, which is what makes it worth its length. The table is an
index into it:

```markdown
   **Every knob, in one place.** The prose above is the explanation; this is the
   index. Anything not on this list is not authorable from `selection.json`.

   | knob | what it sets |
   |---|---|
   | `source` / `start` / `dur` | which clip, from where, for how long |
   | `base_dur` | the footage-projected length, recorded once at projection — never author it |
   | `shot_type` | the label (`wide`/`medium`/`close`); the variety gate measures geometry, not this |
   | `composition` / `grid` | `lead`/`center`/`break` × `thirds`/`phi` |
   | `layout` | `fill` / `fit` / `insert` |
   | `background` / `background_color` | the filler behind a `fit`/`insert` frame |
   | `crop_aspect` / `crop_scale` | the crop rectangle's shape and size |
   | `border_px` / `border_color` | the `insert` card's border |
   | `motion` | the SUBJECT's travel, for intent scoring |
   | `hero` | who to follow — bbox, rule, track id, or cast name |
   | `pan` | a generated camera move; refuses over a window holding people |
   | `zoom` | a subject-anchored push-in/pull-out along the tracked route |
   | `ramp` | a speed ramp to a slow plateau |
   | `stabilize` | vidstab pre-stage; never on a wade-in/out shot |
   | `smooth_window_s` | seconds of path smoothing |
   | `white_balance` / `black_point` / `highlight` / `highlight_red` / `shadow_red` / `mid_blue` / `saturation` / `dip` | the colour grade, applied in that order |
   | `tone_src` / `tone_dst` | the match-grade pair; `match_grade` authors these |
   | `color_means` | the colour check's reference means |
   | `processing_notes` | free text, rendered into `EDL.md` and the draft's labels |
   | `beat_slot` | which grid line the cut lands on; `--pacing` writes it |

   The reel-level keys are separate and live beside `episodes`, not inside one:
   `look`, `variety_waiver`.
```

- [ ] **Step 5: The reverse scan — a named-but-missing tool**

The backlog row asked to check the other direction too: a tool the skill *names*
that no field backs is a build-or-not decision, not a doc gap. Run:

```bash
.venv/bin/python - <<'EOF'
import dataclasses, re, pathlib
from scripts.lib.edl import EDLEpisode
from scripts.lib.models import ReframeSpec
known = {f.name for f in dataclasses.fields(EDLEpisode)} | {f.name for f in dataclasses.fields(ReframeSpec)}
text = pathlib.Path("skills/edit-plan/SKILL.md").read_text()
cited = {m for m in re.findall(r"`([a-z][a-z0-9_]{3,})`", text)}
print(sorted(c for c in cited if c.endswith(("_px", "_color", "_s")) or c in
             {"curves", "shadows", "contrast", "gamma", "vibrance", "sharpen"}))
EOF
```

Report what it prints in the commit message. A name that is a real missing tool
becomes a backlog row, not a fix in this task.

- [ ] **Step 6: Run the test and watch it pass**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py -v`
Expected: PASS, `missing == []`.

- [ ] **Step 7: Mutation check — the test must be discriminating**

Delete the word `crop_scale` from the SKILL, re-run, watch it FAIL naming
`['crop_scale']`, restore it. A green run after that deletion means the test
matched the word somewhere incidental and must be tightened.

- [ ] **Step 8: Commit**

```bash
git add skills/edit-plan/SKILL.md tests/test_skill_convention.py
git commit
```

Message: five knobs were authorable and undocumented; the table is the index the
row asked for; the test stops the next one going missing silently, and proves
presence only.

---

### Task 2: Editorial constraints in `montage status`

**Files:**
- Modify: `scripts/montage.py`
- Test: `tests/lib/test_montage.py`

- [ ] **Step 1: Write the three failing tests**

Append to `tests/lib/test_montage.py`:

```python
# ---- editorial constraints (design 2026-08-17 §3) ----

def test_no_constraints_file_is_named_absent_not_empty():
    pass  # replaced below — see Step 1's real body
```

The real bodies:

```python
def test_status_reports_no_constraints_file(tmp_path):
    res = next_action(str(tmp_path))
    assert res["constraints"] == {"present": False, "rules": [], "error": None}


def test_status_reports_the_authored_rules(tmp_path):
    (tmp_path / "CONSTRAINTS.json").write_text(json.dumps(
        {"rules": [{"kind": "open_with", "hero": "Mika",
                    "stated": "open on Mika"}]}))
    res = next_action(str(tmp_path))
    assert res["constraints"] == {
        "present": True,
        "rules": [{"kind": "open_with", "stated": "open on Mika", "hero": "Mika"}],
        "error": None}


def test_a_broken_constraints_file_reports_rather_than_raises(tmp_path):
    # The inspector is called constantly by the router. A refusal escaping here
    # replaces the whole status report with a traceback; reporting an empty rule
    # list instead would answer "nothing binds this cut" when the truth is
    # "nobody can tell" (design §3.1). Neither, so: present, empty, and WHY.
    (tmp_path / "CONSTRAINTS.json").write_text('{"rules": [{"kind": "bogus"}]}')
    res = next_action(str(tmp_path))                      # must not raise
    assert res["constraints"]["present"] is True
    assert res["constraints"]["rules"] == []
    assert "bogus" in res["constraints"]["error"]


def test_the_gate_still_refuses_what_status_only_reports(tmp_path):
    # Status softens NOTHING: the load path keeps its refusal, so the
    # write_edit_plan gate that stands on it is untouched.
    from scripts.lib import constraints as c
    (tmp_path / "CONSTRAINTS.json").write_text('{"rules": [{"kind": "bogus"}]}')
    with pytest.raises(ValueError, match="bogus"):
        c.Constraints.from_json(tmp_path / "CONSTRAINTS.json")
```

- [ ] **Step 2: Run them and watch all four fail**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -k constraints -v`
Expected: three `KeyError: 'constraints'`; the fourth passes already (it pins
existing behaviour that this task must not change — keep it).

- [ ] **Step 3: Implement `_constraints`**

In `scripts/montage.py`, add `constraints` to the `scripts.lib` import and a
helper beside `_deliveries`:

```python
def _constraints(run: Path) -> dict:
    """The editorial rules binding a re-cut, for a human who should not have to
    open CONSTRAINTS.json (design 2026-08-17 §3). Three states, all named:
    absent, authored, or present-and-unreadable.

    The refusal is CAUGHT here and carried in `error`, which is not a softening
    of it: this is the inspector the router calls constantly, so letting a typo
    in a rule file replace the status report with a traceback helps nobody — and
    reporting `rules: []` for an unreadable file would answer "nothing binds
    this cut" when the truth is "nobody can tell". The enforcement point does
    not move: write_edit_plan still discovers this file and still refuses,
    with no waiver."""
    p = run / "CONSTRAINTS.json"
    if not p.exists():
        return {"present": False, "rules": [], "error": None}
    try:
        loaded = constraints.Constraints.from_json(p)
    except ValueError as e:
        return {"present": True, "rules": [], "error": str(e)}
    return {"present": True, "rules": [r.to_dict() for r in loaded.rules],
            "error": None}
```

- [ ] **Step 4: Return it from `next_action`**

Extend the return dict and its docstring's shape line:

```python
    return {"stages": stages, "next": next_key, "delivered": delivered,
            "deliveries": _deliveries(out), "constraints": _constraints(run)}
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -v`
Expected: all pass, including the pre-existing whole-object stage assertions.

- [ ] **Step 6: Mutation check**

Replace the `except ValueError` body with `raise`, re-run, and watch
`test_a_broken_constraints_file_reports_rather_than_raises` FAIL. Restore. A
green run there means the test is not exercising the broken path.

- [ ] **Step 7: Commit**

```bash
git add scripts/montage.py tests/lib/test_montage.py
git commit
```

Message: the three named states, and why a broken file must be reported rather
than raised OR silently emptied.

---

### Task 3: A fixture longer than `WIN_MAX`

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/integration/test_intake.py`

- [ ] **Step 1: Add the fixture**

In `tests/conftest.py`, beside `sample_clip` (which is NOT touched — 27 test
files consume it and its goldens would move):

```python
@pytest.fixture(scope="session")
def multi_window_clip(tmp_path_factory):
    """12s 1920x1080 30fps, THREE segments separated by hard cuts at 5.0s and
    9.5s, each with its own background colour and its own box trajectory.

    Exists because `sample_clip` is 3s with no cut, and carve.units_for_span
    returns ONE whole unit for any span inside the [WIN_MIN, WIN_MAX] band — so
    that fixture is structurally unable to carve more than one window, which is
    why the 2026-08-06 pool-relative scoring shipped with no real-bytes proof
    (that design's §8). Two spans here are longer than WIN_MAX = 4.0 and reach
    units_for_span's PEAK branch; the third (2.5s) is in-band and yields one
    whole unit, so all the branches that matter are exercised.

    Distinct colours AND distinct trajectories on purpose: identical pixels
    would collide under the phash cull and mark every window but one a
    duplicate. Uses overlay, not drawbox, for the reason sample_clip records.
    """
    try:
        binary = ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    out = tmp_path_factory.mktemp("media") / "multi.mp4"
    src = []
    for colour, dur in (("0x101010", 5.0), ("0x304060", 4.5), ("0x603020", 2.5)):
        src += ["-f", "lavfi", "-i", f"color=c={colour}:s=1920x1080:d={dur}:r=30",
                "-f", "lavfi", "-i", f"color=c=white:s=140x320:d={dur}:r=30"]
    graph = ("[0][1]overlay=x='200+t*300':y=300[a];"
             "[2][3]overlay=x='1500-t*250':y=500[b];"
             "[4][5]overlay=x='700+t*120':y=200[c];"
             "[a][b][c]concat=n=3:v=1:a=0[v]")
    proc.run([binary, "-y", *src, "-filter_complex", graph, "-map", "[v]",
              "-t", "12", "-pix_fmt", "yuv420p", str(out)])
    return out
```

- [ ] **Step 2: Prove the fixture is what it claims, before using it**

Run this by hand and record the numbers in the commit message — a fixture whose
scene cuts do not land where the docstring says makes every assertion below a
coincidence:

```bash
.venv/bin/python - <<'EOF'
from scripts.lib import assembly
from scripts.intake import scene_bounds
# point at the file the fixture wrote; build it once via pytest --setup-only or
# reproduce the same ffmpeg command into /tmp first
src = "/tmp/multi.mp4"
print("dur", assembly.probe_duration(src), "cuts", scene_bounds(src))
EOF
```

Expected: `dur` ≈ 12.0 and two interior cuts near 5.0 and 9.5. If PySceneDetect
finds a different number of cuts, adjust the segments' colour contrast until it
does — and update the docstring to whatever is actually measured.

- [ ] **Step 3: Write the failing proof**

Append to `tests/integration/test_intake.py`. The detection stream is faked, as
every test in this file already fakes it and for the documented reason — a box
is not a person. What the fixture contributes is real: duration, fps, the scene
cuts that bound the spans, the proxy, and the phashes.

```python
def _fake_ramped_frames(n: int, step: int):
    """A person present throughout whose per-SAMPLE displacement alternates slow,
    slow, fast — so subject_curve has strict local maxima and units_for_span
    reaches its peak branch rather than _flat_unit. Only every `step`-th frame is
    sampled (intake._people_timeline), so the pattern is authored on the sample
    index. Proxy (960x540) coordinates, like the other fake here."""
    frames, x = [], 150.0
    for i in range(n):
        if i and i % step == 0:
            k = i // step
            x += 30.0 if k % 5 == 2 else 3.0
        frames.append(_FakeRes([_FakeBox([x, 250, 100, 150], 1)]))
    return frames


def test_a_long_clip_carves_a_real_window_pool(monkeypatch, tmp_path,
                                               multi_window_clip):
    """The proof sample_clip is structurally unable to give (design §4): enough
    windows to clear CLIP_POOL_MIN, so score_pool takes its clip-relative branch
    and `score` can be read as the percentile it claims to be."""
    root = tmp_path / "footage"; root.mkdir()
    shutil.copy(multi_window_clip, root / "clip.mp4")
    monkeypatch.setattr(intake, "_iter_seg",
                        lambda src, **k: iter(enumerate(_fake_ramped_frames(360, 10))))
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    monkeypatch.setattr(intake.reid, "embed",
                        lambda crops: [[0.0] * 512 for _ in crops])
    out = tmp_path / "run"; out.mkdir()
    fo = intake.intake(str(root), str(out), jobs=1)
    windows = fo.clips[0].windows
    assert len(windows) >= intake.CLIP_POOL_MIN, (
        f"{len(windows)} windows — the fixture must clear CLIP_POOL_MIN "
        f"({intake.CLIP_POOL_MIN}) or score_pool never takes its clip-relative "
        f"branch and this proof is vacuous")
    assert all(0.0 <= w.score <= 1.0 for w in windows)
    assert len({w.score for w in windows}) > 1, (
        "every window scored identically — a percentile over a real pool must "
        "separate its members, so this is a flat curve, not a ranking")
    # the boundaries are real too: no two windows are the same span
    assert len({(w.start, w.dur) for w in windows}) == len(windows)
```

- [ ] **Step 4: Run it and watch it fail first for the right reason**

Run: `.venv/bin/python -m pytest tests/integration/test_intake.py -k long_clip -v`
Before the fixture exists it errors on the missing fixture. After Step 1 it must
pass. If it fails on the `CLIP_POOL_MIN` assertion, the peaks are not landing —
print `fo.clips[0].scene_cuts` and the carved spans and fix the fake's pattern,
not the assertion.

- [ ] **Step 5: Vacuity check against the OLD fixture**

Swap `multi_window_clip` for `sample_clip` in the test, re-run, and watch it FAIL
on the `CLIP_POOL_MIN` assertion with 1 window. Restore. This is the step that
proves the new fixture is doing the work rather than the assertions being loose.

- [ ] **Step 6: Confirm no existing golden moved**

Run: `.venv/bin/python -m pytest tests/integration/test_intake.py -v`
Expected: the three pre-existing tests unchanged and passing — the fixture is
additive and `sample_clip` was not touched.

- [ ] **Step 7: Commit**

```bash
git add tests/conftest.py tests/integration/test_intake.py
git commit
```

Message: what the fixture makes provable, what stays faked (the detection
stream, as everywhere else in this file), and the measured cut positions.

---

### Task 4: Backlog, build status, registry

**Files:**
- Modify: `docs/backlog.md`, `docs/build-status.md`, `CLAUDE.md`

- [ ] **Step 1: Mark the four rows done**

In `docs/backlog.md`'s P2 table, flip to `✅` with a one-line what-and-when:
the `#5` knob row, the `montage status` constraints row, the `sample_clip`
fixture row, and the LICENSE row. For `#5`, record the measurement — 30 of 35
fields were already documented and five were not — so the next reader does not
re-derive the row's size.

- [ ] **Step 2: Correct the ramp row, do not close it**

Change its size `S` → `M` and append the reason:

> Sized S on the reasoning that `lib/anchors` already computes the curve.
> Measured 2026-08-17: `anchors` feeds **nothing** today — `pacing --anchors`
> prints a table into `PACING.md` and no code reads it. Auto-placement needs a
> wire format for "you pick" (`RampSpec.at` must be a number), a clamp into
> `ramp.validate_window`'s enclosure band, an ffmpeg pass per ramped episode
> inside `edit_plan` (which decodes nothing today), and a `MIN_RAMP_FPS`
> re-check. That is a slice with its own design.

- [ ] **Step 3: File this slice's own deferrals**

Per the backlog's own rule, the design's honest limits become rows:

- the skill-coverage test proves a field NAME is present, never that the
  explanation beside it is correct or current (P3/S, design §2.2)
- `montage status` surfaces rules without checking them against the current cut
  (P3/S, design §3.2)
- the new fixture's detection stream is faked, so the window pool proves the
  carve/pool plumbing, not the motion sensor's judgement (P3/S, design §4.1)
- no licence audit of the transitive dependency tree (P4/S, design §1.1)

- [ ] **Step 4: build-status + CLAUDE.md**

Add the Done entry to `docs/build-status.md` and the two registry rows (design +
plan) to `CLAUDE.md`'s Quick Reference table, in the established format.

- [ ] **Step 5: The whole suite, on a cleared bytecode cache**

```bash
find . -name __pycache__ -type d -prune -not -path "./.venv/*" -exec rm -rf {} + && .venv/bin/python -m pytest -q
```

Expected: the pre-slice baseline (2951 passed / 2 skipped) plus this slice's new
tests, zero failures, no golden moved. Report the real numbers; do not assume
them.

- [ ] **Step 6: Commit**

```bash
git add docs/ CLAUDE.md
git commit
```

---

## Self-Review

**Spec coverage.** §1 → Task 0. §2 (+§2.1 the coverage test, §2.2 its limit) →
Task 1. §3 (+§3.1 the three states) → Task 2. §4 → Task 3. §5 (the ramp row's
correction) → Task 4 Step 2. §6's four testing bullets are Tasks 0/1/2/3 Step 1
respectively. §8's limits become backlog rows in Task 4 Step 3.

**Placeholder scan.** Task 1 Step 5 and Task 3 Step 2 are measurements whose
*output* is not predictable — both say what to run, what to expect, and what to
do when it differs, which is a step, not a placeholder. Task 3 Step 1's
docstring pins cut positions the plan cannot know until Step 2 measures them;
Step 2 mandates updating the docstring to whatever is measured.

**Known weak point, stated rather than hidden.** Task 3's expected window count
is derived, not observed: with cuts at 5.0/9.5 the spans are 5.0 / 4.5 / 2.5,
the first two exceed `WIN_MAX = 4.0` and reach the peak branch, and the fake's
period-5 pattern puts strict local maxima 1.667s apart — above the `WIN_MIN =
1.2` peak spacing. That arithmetic predicts comfortably more than
`CLIP_POOL_MIN = 5` windows, but PySceneDetect's actual cut positions are an
empirical question, which is exactly why Step 2 measures before Step 3 asserts
and Step 5 checks the assertion is not vacuous.

**Type consistency.** `_constraints` returns the same three keys on every path.
`multi_window_clip` follows `sample_clip`/`ramp_clip`'s signature and skip
behaviour. `_fake_ramped_frames` reuses this file's existing `_FakeRes`/`_FakeBox`.
