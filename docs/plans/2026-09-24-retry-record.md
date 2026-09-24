# The retry loop's record — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record the reframe params each render actually used, beside what it
rendered, and stop the reel-level reprocess writing its record into a second
directory nothing points at.

**Architecture:** `reframe.path_meta` writes `max_speed`/`smooth_window_s` into
`path.meta.json` — the renderer records what it used, because nothing else can.
`process_episode.rendered_params` turns that sidecar back into a params dict, and
`plan_for`/`plan_ungraded` accept it, so the three consumers that reconstruct an
episode's plan reconstruct the render that happened instead of the one the
manifest declares. Separately, `build_reel`'s reprocess arm writes its sidecars
beside the record it replaces rather than under its own work dir.

**Tech Stack:** Python 3, pytest, real ffmpeg for the round-trip proofs.

**Design:** [docs/specs/2026-09-24-retry-record-design.md](../specs/2026-09-24-retry-record-design.md).
Section references below (§0.5, §2.1, …) are to that file.

## Global Constraints

- **Interpreter:** `.venv/bin/python`. Scripts run as modules; `pythonpath = .`
  is set in `pytest.ini`, so tests import `from scripts import …`.
- **Never install anything.** No `brew`, `pip install`, `uv`, `npm`, no
  `setup.sh`. Verification is read-only plus `pytest`.
- **Never run `git checkout --`, `git restore`, `git reset --hard`, or
  `git stash`.** To restore a file you changed for a mutation check, use
  `git show HEAD:<path> > <path>` for committed content; if the file is
  uncommitted, save your own copy first with `cp <path> <path>.bak` and restore
  from that. Run every mutation on an otherwise-clean tree and re-check
  `git diff --stat` after restoring.
- **Mutation batteries run under `PYTHONDONTWRITEBYTECODE=1`.** A one-byte edit
  can match the previous file's size and mtime-second and CPython then serves a
  stale `.pyc`.
- **zsh does not word-split an unquoted variable.** A pytest selection held in a
  shell variable arrives as ONE argument and prints `no tests ran`, which reads
  exactly like a non-discriminating mutation row. Write selections out literally.
- **`git add` named paths only. Never `git add -A`.**
- **Do not touch `/Users/serg/Downloads/untitled folder/`.** It is the only real
  run and it is read-only evidence.
- **Byte-identity is a requirement, not a nicety.** An episode that was neither
  authored nor retried must write a `path.meta.json` byte-identical to today's.
- **Exact values, copied from the design:** `ReframeSpec` defaults are
  `max_speed = 750.0` and `smooth_window_s = 0.25`. `orch.DEFAULT_PARAMS` is
  `{"max_speed": 750.0, "smooth_window_s": 0.25}`. The three fail reasons that
  move a knob are `on_line`, `centered`, `jitter` (§0.6).

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `scripts/lib/models.py` | `PathMeta` gains two optional fields; `to_dict` emits them when present; `from_dict` reads them as exemptions defaulting to `None` | 1 |
| `scripts/reframe.py` | `path_meta` fills them from the `ReframeSpec` it already receives, passing `None` when the value is the dataclass default | 1 |
| `scripts/process_episode.py` | `rendered_params(meta_json)`; `_plan_parts`/`plan_for`/`plan_ungraded` accept `params` | 2 |
| `scripts/build_reel.py` | `_predict` reconstructs with the recorded params (3); the reprocess arm writes beside the record it replaces (5) | 3, 5 |
| `scripts/probe.py` | `probe_grade` reconstructs both halves of its pair with the recorded params | 3 |
| `scripts/episode_qc.py` | `_source_reading` reconstructs with the recorded params and gains the drift guard it never had | 4 |
| `tests/lib/test_models.py` | contract round-trip, conditional emission, absence-reads-as-None | 1 |
| `tests/integration/test_reframe.py` | the writer fills them from the spec; a default spec's sidecar is unchanged | 1 |
| `tests/lib/test_process_episode.py` | `rendered_params`' four cases; `plan_for`'s `params` arm | 2 |
| `tests/lib/test_build_reel.py` | `_predict` threading (3); the reprocess directory + its control (5) | 3, 5 |
| `tests/integration/test_probe.py` | `probe_grade` threading | 3 |
| `tests/test_episode_qc.py` | `_source_reading` threading, the guard, and the two existing wiring tests' stubs | 4 |
| `tests/integration/test_retry_record.py` | **new** — the real-ffmpeg round trip and the ladder-drift measurement | 6 |

---

## Task 1: The sidecar records the params

The contract and its one writer, together: a field nothing writes is an inert
surface, and the writer is two constructor arguments in the function that already
receives the spec.

**Files:**
- Modify: `scripts/lib/models.py` — `PathMeta` fields (after `crop_ys`, ~line 192), `to_dict` (~line 218), `from_dict` (~line 269)
- Modify: `scripts/reframe.py` — imports (line 3), a new module-level constant + helper above `path_meta` (~line 594), `path_meta`'s return (~line 604)
- Test: `tests/lib/test_models.py`, `tests/integration/test_reframe.py`

**Interfaces:**
- Produces: `PathMeta.max_speed: float | None`, `PathMeta.smooth_window_s: float | None` — `None` means *the sidecar does not say*. Task 2 reads them.

- [ ] **Step 1: Write the failing contract tests**

Append to `tests/lib/test_models.py`, after `test_pathmeta_still_hard_fails_on_a_missing_non_exempt_key`:

```python
# --- 2026-09-24 retry-record Task 1: the sidecar records the render's own params ---

def test_pathmeta_round_trips_the_render_params():
    pm = m.PathMeta(**_META_KW, max_speed=1125.0, smooth_window_s=0.5)
    assert m.PathMeta.from_dict(pm.to_dict()) == pm


def test_pathmeta_omits_the_params_it_was_not_given():
    # The byte-identity rule (design §2.1): a PathMeta carrying neither value must
    # serialize to exactly the dict today's code produces, or every golden sidecar
    # moves. Compared as a whole dict, not by absence of two keys: `not in` would
    # also pass if to_dict had started emitting some THIRD key.
    d = m.PathMeta(**_META_KW).to_dict()
    assert d == {"mode": "fill", "crop_w": 405, "crop_h": 720, "crop_y": 0,
                 "src_dims": [1280, 720], "canvas": [9, 16], "out_dims": [404, 720],
                 "rect_px": [0, 0, 404, 720], "freedom": 875,
                 "background": "blur", "pan": False, "stabilized": False}


def test_pathmeta_emits_each_param_independently():
    # The ladder can move one knob and leave the other at its default — a lag retry
    # with an authored window at the floor does exactly that (design §2.1's table).
    assert m.PathMeta(**_META_KW, max_speed=1125.0).to_dict()["max_speed"] == 1125.0
    assert "smooth_window_s" not in m.PathMeta(**_META_KW, max_speed=1125.0).to_dict()


def test_pathmeta_reads_an_older_sidecar_as_saying_nothing_about_the_params():
    # The fifth exemption, and the only one whose default is an ABSENCE rather than
    # a provable truth: `background`/`pan`/`stabilized`/the zoom arrays each
    # substitute the one value the field could have held before it existed. Here
    # None means either "predates the field" or "used the defaults", and nothing
    # distinguishes them (design §2.1).
    d = m.PathMeta(**_META_KW).to_dict()
    pm = m.PathMeta.from_dict(d)
    assert pm.max_speed is None and pm.smooth_window_s is None


def test_pathmeta_still_hard_fails_when_a_param_is_present_but_unusable():
    # An exemption covers an ABSENT key, never a corrupt one: a hand-edited
    # "max_speed": "fast" must keep the integrity arm, exactly as crop_w does.
    d = m.PathMeta(**_META_KW).to_dict()
    d["max_speed"] = "fast"
    with pytest.raises(RuntimeError, match=r"unusable field"):
        m.PathMeta.from_dict(d)
```

**Expected-before-the-change audit, per test** (corrected during Task 1's own
execution — the first draft of this paragraph both said "none of these five is
expected to pass" and then named the control that does, and it predicted the wrong
failure mode for the last one):

| test | before | why |
|---|---|---|
| `…round_trips_the_render_params` | FAIL | constructs `PathMeta` with keyword arguments that do not exist yet (`TypeError`) |
| `…omits_the_params_it_was_not_given` | **PASS** | It asserts today's dict. Written reason: it is the byte-identity control — the one thing standing between Step 4's conditional emission and a change that moves every golden sidecar. Confirm it passes at Step 2 and still passes at Step 6. |
| `…emits_each_param_independently` | FAIL | same `TypeError` |
| `…reads_an_older_sidecar_as_saying_nothing…` | FAIL | reads attributes that do not exist yet (`AttributeError`) |
| `…still_hard_fails_when_a_param_is_present_but_unusable` | FAIL, as `Failed: DID NOT RAISE RuntimeError` | **not** a `TypeError`: this one never passes a new kwarg to the constructor. It sets `d["max_speed"] = "fast"` on a dict `from_dict` currently ignores, so nothing raises at all. Red either way, but for this reason. |

- [ ] **Step 2: Run them and record which fail**

```bash
.venv/bin/python -m pytest tests/lib/test_models.py -k "pathmeta and (round_trips_the_render or omits_the_params or emits_each_param or saying_nothing or param_is_present_but_unusable)" -v
```

Expected: four FAIL (`TypeError: __init__() got an unexpected keyword argument
'max_speed'`, and `AttributeError` for the fourth);
`test_pathmeta_omits_the_params_it_was_not_given` **PASSES** — it is the control,
and a control that fails here means `_META_KW` or `to_dict` has drifted from this
plan and you must stop and report rather than adjust the expected dict.

- [ ] **Step 3: Add the two fields**

In `scripts/lib/models.py`, immediately after the `crop_ys` field of `PathMeta`:

```python
    #: The two retry-ladder knobs THIS render used. Recorded by the renderer
    #: because nothing else can: `max_speed` has no manifest field at all, and
    #: `orch.adjust_reframe_params` rescales both between attempts without
    #: touching the declaration — so a reader rebuilding the plan from the
    #: manifest rebuilds a DIFFERENT geometry (design 2026-09-24 §0.2, §0.5:
    #: one jitter step moved 74 of 95 path samples by up to 5px).
    #:
    #: None is an ABSENCE, not a value, and unlike the four exemptions above it
    #: is not a provable truth: it means either "this sidecar predates the
    #: field" or "this render used the ReframeSpec defaults", and nothing here
    #: distinguishes them.
    #:
    #: That conflation is safe, but NOT because the two reconstruct identically —
    #: they do not. A reader planning from the manifest alone reproduces a
    #: defaults render exactly, and reproduces a PRE-SLICE retried render's
    #: geometry WRONGLY (design 2026-09-24 §2.1's table). What makes both
    #: outcomes correct is that every consumer of a rebuilt plan must check it
    #: against the frozen sidecars before using it — probe._refuse_on_drift — so
    #: the second case is refused by name instead of read as a measurement. A
    #: consumer that skips that check reads a crop the episode never shipped.
    max_speed: float | None = None
    smooth_window_s: float | None = None
```

- [ ] **Step 4: Emit them when present**

In `PathMeta.to_dict`, after the `if self.zoomed:` block and before `return d`:

```python
        # Same conditional emission as the zoom arrays above, and for the same
        # reason: an episode that was neither authored nor retried writes the
        # sidecar it has always written. The judgement of whether a value is
        # NEWS lives in reframe.path_meta, which knows the spec's defaults;
        # here the rule is only "emit what you were given".
        if self.max_speed is not None:
            d["max_speed"] = self.max_speed
        if self.smooth_window_s is not None:
            d["smooth_window_s"] = self.smooth_window_s
```

- [ ] **Step 5: Read them as the fifth exemption**

In `PathMeta.from_dict`, inside the `cls(...)` call, after
`crop_ys=_int_list(d.get("crop_ys"))`, add a trailing comma and:

```python
                       # Fifth exemption, and the only one defaulting to an
                       # ABSENCE rather than a provable truth — see the fields'
                       # own comment. A key that is PRESENT and unusable still
                       # falls to the integrity arm below, exactly as crop_w does:
                       # _opt_float raises TypeError/ValueError, which the except
                       # clause already turns into the "unusable field" message.
                       max_speed=_opt_float(d.get("max_speed")),
                       smooth_window_s=_opt_float(d.get("smooth_window_s")))
```

and add this helper beside `_int_list` (above the `PathMeta` dataclass):

```python
def _opt_float(v: object) -> float | None:
    """A sidecar's optional scalar, or None when the key is absent. float() raises
    on a present-but-unusable value, which from_dict's except clause turns into the
    integrity message — an exemption covers a MISSING key, never a corrupt one."""
    return None if v is None else float(v)
```

- [ ] **Step 6: Run the contract tests**

```bash
.venv/bin/python -m pytest tests/lib/test_models.py -v
```

Expected: PASS, whole file.

- [ ] **Step 7: Write the failing writer test**

Append to `tests/integration/test_reframe.py`:

```python
# --- 2026-09-24 retry-record Task 1: path_meta records what the render used ---

@pytest.mark.integration
def test_path_meta_records_params_that_differ_from_the_spec_defaults(golden_ride_segment):
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=(128.0, 128.0, 128.0),
                       delivery=Delivery.from_spec("native"),
                       max_speed=450.0, smooth_window_s=0.5)
    plan = reframe.plan_render(spec, str(golden_ride_segment),
                               "tests/fixtures/golden_route.json")
    meta = reframe.path_meta(plan, spec, stabilized=False)
    assert (meta.max_speed, meta.smooth_window_s) == (450.0, 0.5)


@pytest.mark.integration
def test_path_meta_records_nothing_when_the_render_used_the_defaults(golden_ride_segment):
    """The byte-identity half. A spec at ReframeSpec's own defaults must produce a
    sidecar with neither key — the check is on to_dict, not on the attributes,
    because it is the FILE that must not move."""
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=(128.0, 128.0, 128.0),
                       delivery=Delivery.from_spec("native"))
    plan = reframe.plan_render(spec, str(golden_ride_segment),
                               "tests/fixtures/golden_route.json")
    d = reframe.path_meta(plan, spec, stabilized=False).to_dict()
    assert "max_speed" not in d and "smooth_window_s" not in d
```

Both are expected to FAIL before Step 9: the first because `path_meta` does not
set the fields (they come back `None`); the second is expected to **PASS** before
the change — `path_meta` sets nothing today, so neither key is emitted. Its
written reason: it is the control that Step 9's conditional did not turn into an
unconditional write. Confirm it passes at Step 8 and still passes at Step 10.

**Import, checked at planning time:** `tests/integration/test_reframe.py` already
imports `pytest`, `reframe` and `Delivery`, but **not** `ReframeSpec` — add it to
the existing `from scripts.lib.models import (...)` list, which currently reads
`BACKGROUNDS, CropPath, Delivery, LayoutSpec, PanSpec, PathMeta, ZoomSpec`.

- [ ] **Step 8: Run the writer tests**

```bash
.venv/bin/python -m pytest tests/integration/test_reframe.py -k "path_meta_records" -v
```

Expected: `..._params_that_differ_from_the_spec_defaults` FAILS
(`assert (None, None) == (450.0, 0.5)`);
`..._nothing_when_the_render_used_the_defaults` PASSES.

- [ ] **Step 9: Fill them in `path_meta`**

In `scripts/reframe.py`, change line 3 to:

```python
from dataclasses import dataclass, fields as _dc_fields
```

Add immediately above `def path_meta(`:

```python
#: ReframeSpec's own declared defaults, read from the dataclass rather than
#: hand-copied: a default that moves must not silently start — or stop — being
#: recorded in the sidecar. Same rule the colour identity follows (design
#: 2026-08-15 Task 4 review).
#:
#: Safe only for fields with a plain `= value` default: a field(default_factory=…)
#: field's own .default is dataclasses.MISSING, so `value == _SPEC_DEFAULTS[name]`
#: would never be true and that field would be recorded on every render — the
#: byte-identity hole this exists to close, reopened silently. ReframeSpec already
#: has one such field (`layout`), so re-check before calling _recorded with a new
#: name. Same caveat manifest.COLOUR_IDENTITY carries, for the same reason.
_SPEC_DEFAULTS = {f.name: f.default for f in _dc_fields(ReframeSpec)}


def _recorded(name: str, value: float) -> float | None:
    """`value`, or None when it IS the ReframeSpec default for `name`.

    The sidecar records news, not restatement: an episode that was neither
    authored nor retried must write the file it has always written (design §2.1).
    The judgement lives here and not in PathMeta.to_dict because this is the only
    place that holds the spec.
    """
    return None if value == _SPEC_DEFAULTS[name] else value
```

and extend `path_meta`'s return, replacing the final line
`crop_ys=plan.crop_ys if spec.zoom is not None else None)` with:

```python
                    crop_ys=plan.crop_ys if spec.zoom is not None else None,
                    max_speed=_recorded("max_speed", spec.max_speed),
                    smooth_window_s=_recorded("smooth_window_s", spec.smooth_window_s))
```

- [ ] **Step 10: Run the writer tests and the reframe suite**

```bash
.venv/bin/python -m pytest tests/integration/test_reframe.py tests/lib/test_models.py -v
```

Expected: PASS.

- [ ] **Step 11: Prove no golden moved**

```bash
.venv/bin/python -m pytest tests/integration/test_golden.py tests/test_fake_render.py -v
```

Expected: PASS. These are the two places a changed `path.meta.json` would show
up — `test_fake_render.py:32` compares a whole sidecar dict (the fake's own
hand-written one, which this change does not touch) and the golden suite pins
rendered output.

- [ ] **Step 12: Commit**

```bash
git add scripts/lib/models.py scripts/reframe.py tests/lib/test_models.py tests/integration/test_reframe.py
git commit -m "feat(reframe): record the render's own max_speed/smooth_window_s in path.meta.json

max_speed has no manifest field at all and the retry ladder rescales both
knobs without touching the declaration, so a reader rebuilding the plan from
the manifest rebuilds a different geometry. The renderer records what it
used; None means the sidecar does not say.

Emitted only when the value differs from ReframeSpec's own default, read
from the dataclass rather than hand-copied, so an unauthored and un-retried
episode writes a byte-identical sidecar.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: `rendered_params` and `plan_for(params=…)`

**Files:**
- Modify: `scripts/process_episode.py` — `_plan_parts` (~line 60), `plan_for` (~line 80), `plan_ungraded` (~line 95), and a new `rendered_params` beside them
- Test: `tests/lib/test_process_episode.py`

**Interfaces:**
- Consumes: `PathMeta.max_speed` / `PathMeta.smooth_window_s` from Task 1.
- Produces:
  - `process_episode.rendered_params(meta_json: str | Path | None) -> dict | None`
  - `process_episode.plan_for(manifest_dict, src, route, *, params: dict | None = None)`
  - `process_episode.plan_ungraded(manifest_dict, src, route, *, params: dict | None = None)`

  Tasks 3 and 4 call exactly these.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_process_episode.py`:

```python
# --- 2026-09-24 retry-record Task 2: reconstruct the render, not the declaration ---

def _meta_json(tmp_path, **over):
    """A real path.meta.json on disk. PathMeta's own to_dict writes it, so the file
    this reads is the shape reframe writes — not a hand-built dict that could drift
    from it."""
    pm = models.PathMeta(mode="fill", crop_w=405, crop_h=720, crop_y=0,
                         src_dims=(1280, 720), canvas=(9, 16), out_dims=(404, 720),
                         rect_px=(0, 0, 404, 720), freedom=875, **over)
    p = tmp_path / "path.meta.json"
    p.write_text(json.dumps(pm.to_dict()))
    return p


def test_rendered_params_reads_both_knobs_from_the_sidecar(tmp_path):
    p = _meta_json(tmp_path, max_speed=450.0, smooth_window_s=0.5)
    assert process_episode.rendered_params(p) == {"max_speed": 450.0,
                                                  "smooth_window_s": 0.5}


def test_rendered_params_fills_an_omitted_knob_from_the_defaults(tmp_path):
    # A lag retry moves max_speed and can leave the window exactly at the default,
    # which is then not emitted. The omitted key means "the render used the
    # default" — NOT "ask the manifest", which is what the authored value would
    # wrongly supply (design §2.2).
    p = _meta_json(tmp_path, max_speed=1125.0)
    assert process_episode.rendered_params(p) == {
        "max_speed": 1125.0, "smooth_window_s": orch.DEFAULT_PARAMS["smooth_window_s"]}


def test_rendered_params_reports_a_sidecar_that_says_nothing_as_absence(tmp_path):
    assert process_episode.rendered_params(_meta_json(tmp_path)) is None


def test_rendered_params_reports_a_missing_or_unnamed_sidecar_as_absence(tmp_path):
    # ReelEpisode.meta defaults to "" and a reel manifest may legally carry no
    # sidecar: that is an absence, not a fault.
    assert process_episode.rendered_params("") is None
    assert process_episode.rendered_params(None) is None
    assert process_episode.rendered_params(tmp_path / "gone.json") is None


def test_rendered_params_still_raises_on_a_corrupt_sidecar(tmp_path):
    # A file that EXISTS and will not parse is machine-written content gone wrong.
    # Laundering it into "the defaults, then" hands the caller a plan built on a
    # guess — the exact substitution PathMeta.from_json refuses by design.
    p = tmp_path / "path.meta.json"
    p.write_text("{not json")
    with pytest.raises(RuntimeError, match=r"is corrupt"):
        process_episode.rendered_params(p)


def test_plan_for_uses_the_given_params_instead_of_the_manifests_authored_window(
        tmp_path, monkeypatch):
    """The replace-not-merge rule. A recorded sidecar is a COMPLETE account of what
    the render used, so an authored smooth_window_s must not win over it — after a
    retry the authored value is precisely what the ladder overrode."""
    seen = {}

    def _fake_plan_render(spec, src, route):
        seen["spec"] = spec
        return "plan"
    monkeypatch.setattr(process_episode.reframe, "plan_render", _fake_plan_render)

    md = _episode_manifest(tmp_path, smooth_window_s=1.2)
    process_episode.plan_for(md, "src.mp4", None,
                             params={"max_speed": 450.0, "smooth_window_s": 0.5})
    assert (seen["spec"].max_speed, seen["spec"].smooth_window_s) == (450.0, 0.5)


def test_plan_for_without_params_still_reads_the_manifests_authored_window(
        tmp_path, monkeypatch):
    """The control on the arm above: params=None must keep today's behaviour
    exactly, or every caller that does not pass params silently changes geometry."""
    seen = {}

    def _fake_plan_render(spec, src, route):
        seen["spec"] = spec
        return "plan"
    monkeypatch.setattr(process_episode.reframe, "plan_render", _fake_plan_render)

    md = _episode_manifest(tmp_path, smooth_window_s=1.2)
    process_episode.plan_for(md, "src.mp4", None)
    assert (seen["spec"].max_speed, seen["spec"].smooth_window_s) == (750.0, 1.2)


def test_plan_ungraded_threads_params_through_to_the_spec(tmp_path, monkeypatch):
    """The plain half of the damage pair must share the graded half's geometry. A
    passthrough that is silently dropped here would compare two crops and call the
    difference a grade."""
    seen = {}

    def _fake_plan_render(spec, src, route):
        seen["spec"] = spec
        return "plan"
    monkeypatch.setattr(process_episode.reframe, "plan_render", _fake_plan_render)

    process_episode.plan_ungraded(_episode_manifest(tmp_path), "src.mp4", None,
                                  params={"max_speed": 450.0, "smooth_window_s": 0.5})
    assert (seen["spec"].max_speed, seen["spec"].smooth_window_s) == (450.0, 0.5)
```

**Expected-before-the-change audit, per test:**

| test | before | why |
|---|---|---|
| `…reads_both_knobs…` | FAIL | `rendered_params` does not exist (`AttributeError`) |
| `…fills_an_omitted_knob…` | FAIL | same |
| `…says_nothing_as_absence` | FAIL | same |
| `…missing_or_unnamed…` | FAIL | same |
| `…corrupt_sidecar` | FAIL | same |
| `…uses_the_given_params…` | FAIL | `plan_for` has no `params` (`TypeError`) |
| `…without_params_still_reads_the_manifests_authored_window` | **PASS** | It is the control: it asserts today's behaviour and must keep asserting it after. Written reason as required — a new test that passes before the change is wrong unless it says why, and this one's job is to catch Step 4 changing the `params=None` arm. |
| `…plan_ungraded_threads_params…` | FAIL | `plan_ungraded` has no `params` (`TypeError`) |

`_episode_manifest(tmp_path, **over)` already exists in this file at line 38 and
ends with `d.update(over)`, so `smooth_window_s=1.2` reaches the manifest dict —
checked at planning time, no helper change needed. The file also has an autouse
`_stub_probe` fixture stubbing `reframe._probe`; these tests stub `plan_render`
above it, so the two do not collide.

`json`, `models` and `orch` must be importable in this file: it already imports
`json`, `from scripts.lib import models` and `from scripts.lib import orchestration
as orch` at lines 1, 7 and 8.

- [ ] **Step 2: Run them**

```bash
.venv/bin/python -m pytest tests/lib/test_process_episode.py -k "rendered_params or plan_for_uses or plan_for_without or plan_ungraded_threads" -v
```

Expected: seven FAIL, `test_plan_for_without_params_still_reads_the_manifests_authored_window`
PASS. A different split means this plan's reading of the file is wrong — stop and
report rather than adjusting the tests to match.

- [ ] **Step 3: Add `rendered_params`**

In `scripts/process_episode.py`, immediately above `def _plan_parts(`:

```python
def rendered_params(meta_json: str | Path | None) -> dict | None:
    """The reframe params the render that wrote this sidecar actually used, or None
    when the sidecar does not say.

    None is the named absence and it has two causes nothing here distinguishes: a
    sidecar written before PathMeta carried these fields, and one whose render used
    the defaults. Safe, but NOT because the two reconstruct identically — they do
    not: a defaults render is reproduced exactly at params=None, and a PRE-SLICE
    retried render's geometry is reproduced WRONGLY (design 2026-09-24 §2.1's
    table). What makes both outcomes correct is that a caller receiving None must
    still check the rebuilt plan against the frozen sidecars before trusting it —
    probe._refuse_on_drift — so the second case is refused by name instead of read
    as a measurement.

    A path that is empty or names no file is also None — ReelEpisode.meta defaults
    to "" and a hand-authored reel manifest may carry no sidecar, which is an
    absence and not a fault. A sidecar that EXISTS and will not parse still raises
    through PathMeta.from_json: machine-written content gone wrong is a fault, and
    answering "the defaults, then" would hand the caller a plan built on a guess.

    `is_file`, not `exists`: a Path("") is truthy like every Path and normalizes to
    Path("."), which exists — so the falsy check alone lets a directory through to
    a read that raises IsADirectoryError, which is neither of this function's two
    documented answers. A path naming a directory is not a sidecar.

    Keys the sidecar omits are filled from orch.DEFAULT_PARAMS and never from the
    manifest's authored smooth_window_s. A recorded sidecar is a COMPLETE account
    of what the render used, so an omitted key means the render used the default —
    after a retry the authored value is exactly what the ladder overrode.
    """
    if not meta_json or not Path(meta_json).is_file():
        return None
    meta = PathMeta.from_json(meta_json)
    if meta.max_speed is None and meta.smooth_window_s is None:
        return None
    p = dict(orch.DEFAULT_PARAMS)
    if meta.max_speed is not None:
        p["max_speed"] = meta.max_speed
    if meta.smooth_window_s is not None:
        p["smooth_window_s"] = meta.smooth_window_s
    return p
```

- [ ] **Step 4: Thread `params` through the plan map**

Replace `_plan_parts`'s signature and its params block. The whole function
becomes:

```python
def _plan_parts(manifest_dict: dict, src: str, route: str | None,
                params: dict | None = None) -> tuple[manifest_lib.Manifest, ReframeSpec,
                                                     reframe.RenderPlan]:
    """The manifest -> (Manifest, ReframeSpec, RenderPlan) map, in ONE place.

    Private because every caller wants one of the two public shapes below; it
    exists because they want DIFFERENT parts of the same map — plan_for the plan,
    plan_and_meta_ungraded the plan AND the spec (path_meta needs it) AND the
    Manifest (its `stabilize` flag). Copying four lines to hand back a third
    field is exactly the field-by-field drift plan_for's own docstring is about:
    the copy read `orch.DEFAULT_PARAMS` and the smooth_window_s override
    independently, so a change to either reached one geometry and not the other.

    `params`, when given, REPLACES the derivation rather than merging over it: it
    is a complete account of what a past render used (see rendered_params), so the
    manifest's authored smooth_window_s must not win over it — a retry is precisely
    the case where the ladder overrode that value. Two independently-produced
    mappings merged into one is also the shape the 2026-09-21 slice found reading
    as a defect the day anything downstream discriminates on a shared key; there is
    nothing to merge here.
    """
    m = manifest_lib.Manifest.from_dict(manifest_dict)
    if params is None:
        params = dict(orch.DEFAULT_PARAMS)
        if m.smooth_window_s is not None:
            params["smooth_window_s"] = m.smooth_window_s
    spec = build_reframe_spec(m, Delivery.from_spec(m.delivery), params)
    return m, spec, reframe.plan_render(spec, src, route)
```

Then `plan_for`:

```python
def plan_for(manifest_dict: dict, src: str, route: str | None,
             *, params: dict | None = None) -> reframe.RenderPlan:
    """The RenderPlan this manifest would render — the ONE manifest -> plan map.

    Lives here because build_reframe_spec does, and its docstring already names the
    risk this function exists to remove: a caller carrying its own copy of the map
    drifts field by field. Two callers used to have one each (color_measure's
    stripped variant and probe's graded one) and check_episode now needs a third.

    With `params` omitted, params come from orch.DEFAULT_PARAMS plus the manifest's
    authored smooth_window_s: a plan from a manifest ALONE, which is what a caller
    with nothing rendered yet — probe's geometry mode, the match-grade conductor —
    wants. The retry loop below still does not come through here; it carries the
    attempt's own params into build_reframe_spec directly.

    `params` is for reconstructing a PAST render: hand it
    rendered_params(<the episode's path.meta.json>) and the plan is the geometry
    that shipped, rather than the geometry the declaration describes. Before this
    existed, an episode whose accepted attempt was not attempt 1 could not be
    replanned at all — the recomputed path disagreed with the frozen one and every
    reader either lost its reading or reported a wrong one (design 2026-09-24 §0.3).
    """
    return _plan_parts(manifest_dict, src, route, params)[2]


def plan_ungraded(manifest_dict: dict, src: str, route: str | None,
                  *, params: dict | None = None) -> reframe.RenderPlan:
    """`plan_for` with every colour knob at identity — the render a measurement reads
    through, and the plain half of the damage sensor's pair.

    `params` must carry whatever the graded half carried, or the pair compares two
    geometries and reports the difference as a grade."""
    return plan_for(manifest_lib.strip_colour(manifest_dict), src, route, params=params)
```

- [ ] **Step 5: Run the tests**

```bash
.venv/bin/python -m pytest tests/lib/test_process_episode.py -v
```

Expected: PASS, whole file.

- [ ] **Step 6: Run every caller's suite**

```bash
.venv/bin/python -m pytest tests/lib/test_build_reel.py tests/test_episode_qc.py tests/integration/test_probe.py tests/integration/test_color_measure.py -q
```

Expected: PASS. `_plan_parts` gained a positional-with-default parameter and
`plan_and_meta_ungraded`'s existing call is unchanged, so nothing should move.

- [ ] **Step 7: Commit**

```bash
git add scripts/process_episode.py tests/lib/test_process_episode.py
git commit -m "feat(process_episode): reconstruct a past render from its recorded params

rendered_params turns a path.meta.json back into the params dict its render
used; plan_for/plan_ungraded accept it. params REPLACES the manifest-derived
derivation rather than merging over it: a recorded sidecar is a complete
account of what ran, and after a retry the authored smooth_window_s is
exactly the value the ladder overrode.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: The two guarded readers

**Files:**
- Modify: `scripts/build_reel.py` — `_predict` (lines 28–70)
- Modify: `scripts/probe.py` — `probe_grade` (lines ~206, ~218)
- Test: `tests/lib/test_build_reel.py`, `tests/integration/test_probe.py`

**Interfaces:**
- Consumes: `process_episode.rendered_params`, `plan_for(..., params=)`,
  `plan_ungraded(..., params=)` from Task 2.

- [ ] **Step 1: Write the failing `_predict` test**

Append to `tests/lib/test_build_reel.py`:

```python
# --- 2026-09-24 retry-record Task 3: _predict rebuilds the render that shipped ---

def test_predict_plans_each_episode_with_the_params_its_sidecar_recorded(
        monkeypatch, tmp_path):
    """A retried episode used to contribute None here — the drift oracle correctly
    refused a plan rebuilt at the defaults — so the episode that had trouble was
    the episode that lost its grade_faithful gate (design 2026-09-24 §0.3).

    Spied on the ARGUMENTS, not on the returned profile: a wrong implementation
    that ignored the recorded params would still return a profile, and on any
    fixture flat enough to fake it would be the same profile."""
    d = tmp_path / "ep0"
    d.mkdir()
    meta = d / "path.meta.json"
    meta.write_text(json.dumps(PathMeta(
        mode="fill", crop_w=405, crop_h=720, crop_y=0, src_dims=(1280, 720),
        canvas=(9, 16), out_dims=(404, 720), rect_px=(0, 0, 404, 720), freedom=875,
        max_speed=450.0, smooth_window_s=0.5).to_dict()))
    ep = ReelEpisode(manifest={"segment": "s.mp4"}, clip="c0.mp4", route="r0.json",
                     path=str(d / "path.json"), meta=str(meta))
    rm = ReelManifest(episodes=[ep], target_dur=6.0)

    seen = {}
    monkeypatch.setattr(build_reel.probe, "source_for", lambda md, epdir: "src.mp4")

    class _Plan:                 # NOT the bare string "plan": _predict's very next
        dur = 3.0                # line reads plan.dur, and its `except Exception`
                                 # arm would swallow the AttributeError into a None,
                                 # so the test could never go green — before OR after
                                 # the change. Same idiom as tests/test_check_episode.py.

    def _plan_for(md, src, route, *, params=None):
        seen["params"] = params
        return _Plan()
    monkeypatch.setattr(build_reel.process_episode, "plan_for", _plan_for)
    monkeypatch.setattr(build_reel.probe, "_refuse_on_drift", lambda *a: None)
    monkeypatch.setattr(build_reel.color_measure, "crop_percentiles",
                        lambda plan, src, times: (1.0, 2.0, 3.0))
    monkeypatch.setattr(build_reel.color, "sample_times", lambda dur: [0.0])
    monkeypatch.setattr(build_reel, "_log", lambda *a, **k: None)

    out = build_reel._predict(rm)
    assert seen["params"] == {"max_speed": 450.0, "smooth_window_s": 0.5}
    assert out == [(1.0, 2.0, 3.0)]
```

**Imports, checked at planning time and corrected during Task 3's execution:**
`json` and `PathMeta` go at the module top of `tests/lib/test_build_reel.py`, not
inside the function — `docs/coding-standards.md` says "All imports at module top.
No imports inside functions", and its only exemption is a heavy optional
third-party dependency, which `PathMeta` is not. `Path` is NOT needed: `tmp_path`
is already one and the bare constructor is never called in that file.

`_predict` reads `plan.dur` as an argument expression, *before* `color.sample_times`
is called — so stubbing `sample_times` does not save a fake plan that has no `dur`.
That is why the fake returns `_Plan()` and not a string. (The plan's first draft got
this backwards, and its test could never have reached green either way: the
`AttributeError` is caught by `_predict`'s own `except Exception` and appended as
`None`, failing the second assertion while the first one passed.)

Expected before the change: **FAIL** on the first assertion. The real `_predict`
calls `plan_for(md, src, e.route)` positionally, so `seen["params"]` stays `None`
and `assert None == {...}` fails. (No `TypeError`: the fake's `params` is
keyword-only *with a default*, so a positional three-argument call binds fine.)

- [ ] **Step 2: Run it**

```bash
.venv/bin/python -m pytest tests/lib/test_build_reel.py -k predict_plans_each_episode -v
```

Expected: FAIL.

- [ ] **Step 3: Thread the params into `_predict`**

In `scripts/build_reel.py`, inside `_predict`'s loop, replace

```python
            plan = process_episode.plan_for(md, src, e.route)
```

with

```python
            plan = process_episode.plan_for(
                md, src, e.route, params=process_episode.rendered_params(e.meta))
```

and, in the docstring, replace the paragraph beginning
`probe._refuse_on_drift, reused verbatim rather than a second oracle:` through
`… right after building the identical plan.` with:

```
    probe._refuse_on_drift, reused verbatim rather than a second oracle: it is the
    one check that the plan rebuilt here is the geometry that shipped. Since
    2026-09-24 the rebuild carries the params the render RECORDED
    (process_episode.rendered_params off this episode's path.meta.json), so an
    episode whose accepted attempt was not attempt 1 rebuilds correctly instead of
    drifting — before that, its rescaled max_speed/smooth_window_s existed nowhere
    and the recomputed crop trajectory disagreed with the frozen one even though
    nothing about the DECLARED colour had changed. The oracle stays, because a
    sidecar written before the fields existed still records nothing, and because a
    re-track or a swapped source drifts for reasons no params record can fix.
    Without it that disagreement would still produce a profile and grade_faithful
    would report it as a colour residual — the wrong remedy (process-episode
    cannot fix a geometry mismatch by re-grading). `probe.probe_grade` guards the
    identical hazard the identical way, right after building the identical plan.
```

- [ ] **Step 4: Run it**

```bash
.venv/bin/python -m pytest tests/lib/test_build_reel.py -v
```

Expected: PASS, whole file.

- [ ] **Step 5: Write the failing `probe_grade` test**

Append to `tests/integration/test_probe.py`:

```python
# --- 2026-09-24 retry-record Task 3: probe_grade rebuilds the render that shipped ---

def test_probe_grade_plans_both_halves_with_the_recorded_params(monkeypatch, tmp_path):
    """Both halves: the graded plan AND the plain one. If only the graded half
    carried the recorded params, the damage pair would compare two geometries and
    call the difference a grade — which is the defect plan_ungraded's own docstring
    now names."""
    seen = {"graded": "unset", "plain": "unset"}

    def _plan_for(md, src, route, *, params=None):
        seen["graded"] = params
        return _FakePlan()

    def _plan_ungraded(md, src, route, *, params=None):
        seen["plain"] = params
        return _FakePlan()
    monkeypatch.setattr(probe.process_episode, "plan_for", _plan_for)
    monkeypatch.setattr(probe.process_episode, "plan_ungraded", _plan_ungraded)
    monkeypatch.setattr(probe.process_episode, "rendered_params",
                        lambda meta: {"max_speed": 450.0, "smooth_window_s": 0.5})
    monkeypatch.setattr(probe, "_refuse_on_drift", lambda *a: None)
    ...
```

**This test is deliberately left incomplete in the plan and must NOT be written
this way.** `probe_grade` renders real frames and measures them; stubbing its
whole body to observe two keyword arguments produces a test that asserts its own
stubs. Write it instead as a real-pixel test in Task 6, where the round trip is
proved end to end, and in this task assert only what can be asserted honestly
without ffmpeg:

```python
def test_probe_grade_asks_for_the_recorded_params_of_the_episode_it_probes(
        monkeypatch, tmp_path):
    """The narrow claim this task owns: probe_grade consults the episode's OWN
    sidecar. The claim that the resulting plan reproduces the shipped geometry is
    Task 6's, proved against real pixels."""
    asked = []
    monkeypatch.setattr(probe.process_episode, "rendered_params",
                        lambda meta: asked.append(meta) or None)
    ...  # build a minimal EPISODES.json and call probe.probe_grade, expecting it
         # to fail later (no real source); assert `asked` before the failure
```

Choose the smaller, honest shape: put a real `EPISODES.json` with one episode on
disk whose `meta` points at a path that does not exist, call `probe.probe_grade`,
let it raise whatever it raises when the source is missing, and assert
`asked == [ep.meta]` inside `pytest.raises`. That is a claim about wiring, which
is what this task changes, and it cannot pass before the change because
`rendered_params` is never called.

- [ ] **Step 6: Run it**

```bash
.venv/bin/python -m pytest tests/integration/test_probe.py -k recorded_params -v
```

Expected: FAIL — `asked` is empty.

- [ ] **Step 7: Thread the params into `probe_grade`**

In `scripts/probe.py`, in `probe_grade`, replace

```python
    plan = process_episode.plan_for(md, src, ep.route)
```

with

```python
    # The params this episode's render RECORDED, not the declaration's: an episode
    # whose accepted attempt was not attempt 1 shipped with rescaled
    # max_speed/smooth_window_s, and rebuilding at the defaults made _refuse_on_drift
    # refuse the probe with a remedy — "re-render, then probe" — that could not
    # restore them (design 2026-09-24 §0.3). Read ONCE and used for both halves of
    # the pair below: two reads could not disagree today, but two call sites is how
    # one of them later stops being updated.
    params = process_episode.rendered_params(ep.meta)
    plan = process_episode.plan_for(md, src, ep.route, params=params)
```

and replace

```python
    plain = process_episode.plan_ungraded(md, src, ep.route)
```

with

```python
    plain = process_episode.plan_ungraded(md, src, ep.route, params=params)
```

- [ ] **Step 8: Run the probe suite**

```bash
.venv/bin/python -m pytest tests/integration/test_probe.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add scripts/build_reel.py scripts/probe.py tests/lib/test_build_reel.py tests/integration/test_probe.py
git commit -m "fix(build_reel,probe): rebuild a retried episode's plan from its recorded params

_predict contributed None for a retried episode, so the episode that had
trouble was the one that lost its grade_faithful gate; probe_grade refused
outright with a remedy that could not restore the lost values. Both now read
the params off the episode's own path.meta.json. probe_grade reads once and
uses it for both halves of the damage pair, which must share one geometry.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: The unguarded reader

`episode_qc._source_reading` is the one consumer with no drift oracle: for a
retried episode it plans at the defaults, reads the source through a crop the
episode never shipped, and hands the judge that reading as the episode's own.
Threading the params fixes the episode rendered *after* this slice; the guard is
what stops the silent lie for every episode rendered before it, whose sidecar
records nothing.

**Files:**
- Modify: `scripts/episode_qc.py` — `_source_reading` (lines 89–126)
- Test: `tests/test_episode_qc.py` — two new tests, plus **two existing tests that
  must be updated**:
  - `test_source_reading_measures_the_source_IN_THE_EPISODE_S_CROP` (line 151) —
    its `_plan_ungraded(md, src, route)` stub must accept `params`, and it must
    stub `episode_qc.probe._refuse_on_drift`, because `_episode()` points `path`/
    `meta` at files it never writes.
  - `test_source_reading_reads_the_stabilized_file_not_the_raw_segment` (line 216)
    — the same two changes, for the same reason.

  Both are wiring tests about *which* functions run with *what* arguments; drift
  is not their subject, and stubbing the oracle is what keeps them about their own
  subject.

**Interfaces:**
- Consumes: `process_episode.rendered_params`, `plan_ungraded(..., params=)`,
  `probe._refuse_on_drift(plan, path_json, meta_json)`.

- [ ] **Step 1: Update the two existing wiring tests**

In both tests, change the stub signature from

```python
    def _plan_ungraded(md, src, route):
```

to

```python
    def _plan_ungraded(md, src, route, *, params=None):
        seen["params"] = params
```

(keeping each test's existing body), and add, beside the other `monkeypatch`
calls:

```python
    # This test's episode points path/meta at files it never writes — drift is not
    # its subject, the wiring is. Task 4 added the oracle to _source_reading, so it
    # is stubbed here exactly as tests/lib/test_build_reel.py stubs it for _predict.
    monkeypatch.setattr(episode_qc.probe, "_refuse_on_drift", lambda *a: None)
```

In `test_source_reading_measures_the_source_IN_THE_EPISODE_S_CROP`, the existing
assertion `assert seen["planned"] == (ep.manifest, ep.manifest["segment"], ep.route)`
stays exactly as it is — `params` is keyword-only and so is not in that tuple.

- [ ] **Step 2: Write the two failing tests**

Append to `tests/test_episode_qc.py`, after
`test_source_reading_reads_the_stabilized_file_not_the_raw_segment`:

```python
# --- 2026-09-24 retry-record Task 4: the reading that had no oracle ---

def test_source_reading_plans_with_the_params_the_render_recorded(monkeypatch, tmp_path):
    """The silent one of the three consumers (design 2026-09-24 §0.3): with no
    oracle, a retried episode's source was read through a crop the episode never
    shipped and reported to the judge as its own."""
    ep = _episode(tmp_path)
    seen = {}
    monkeypatch.setattr(episode_qc.process_episode, "rendered_params",
                        lambda meta: {"max_speed": 450.0, "smooth_window_s": 0.5})

    def _plan_ungraded(md, src, route, *, params=None):
        seen["params"] = params
        return _fake_plan()
    monkeypatch.setattr(episode_qc.process_episode, "plan_ungraded", _plan_ungraded)
    monkeypatch.setattr(episode_qc.probe, "_refuse_on_drift", lambda *a: None)
    monkeypatch.setattr(episode_qc.reframe, "plan_frames_rgb",
                        lambda plan, src, times: [_flat_frame() for _ in times])

    episode_qc._source_reading(ep, {"cast": 0.0, "saturation": 0.0, "contrast": 100.0})
    assert seen["params"] == {"max_speed": 450.0, "smooth_window_s": 0.5}


def test_source_reading_reports_absence_when_the_geometry_drifted(monkeypatch, tmp_path):
    """A sidecar that records no params — every episode rendered before this slice
    — still drifts for a retried episode, and absence is the honest answer. Never a
    reading: a number read through the wrong crop is worse than no number, because
    the judge cannot tell it apart from a real one.

    The message is NOT asserted: this call site swallows the oracle's RuntimeError
    on purpose and reports absence instead, so there is no string to pin. What is
    pinned is that the frames were never decoded — the assertion on `decoded`, not
    only on the return value, because a return of two Nones could also come from
    the reading having been computed and then thrown away."""
    ep = _episode(tmp_path)
    decoded = []
    monkeypatch.setattr(episode_qc.process_episode, "plan_ungraded",
                        lambda md, src, route, *, params=None: _fake_plan())

    def _drifted(plan, path_json, meta_json):
        raise RuntimeError("the recomputed crop path does not match the frozen path.json")
    monkeypatch.setattr(episode_qc.probe, "_refuse_on_drift", _drifted)
    monkeypatch.setattr(episode_qc.reframe, "plan_frames_rgb",
                        lambda plan, src, times: decoded.append(1) or [_flat_frame()])

    assert episode_qc._source_reading(ep, {}) == {"source": None, "delta": None}
    assert decoded == []


def test_source_reading_still_lets_a_broken_render_raise(monkeypatch, tmp_path):
    """The control on the guard's narrowness. The existing except clause
    deliberately excludes RuntimeError, because proc.run raises it for a broken
    ffmpeg install and reporting that as a clean 'absent' is the swallow that
    clause was written to prevent. The new guard must catch the oracle's
    RuntimeError at the oracle's own call and nowhere else — a widened clause would
    make this test's RuntimeError, raised from the PLAN build, report absence."""
    ep = _episode(tmp_path)

    def _boom(md, src, route, *, params=None):
        raise RuntimeError("ffprobe: command not found")
    monkeypatch.setattr(episode_qc.process_episode, "plan_ungraded", _boom)
    with pytest.raises(RuntimeError, match=r"command not found"):
        episode_qc._source_reading(ep, {})
```

**Expected-before-the-change audit:**

| test | before | why |
|---|---|---|
| `…plans_with_the_params_the_render_recorded` | FAIL | `rendered_params` is never called, so `seen["params"]` is `None`; and the stub's keyword-only `params` is never passed |
| `…reports_absence_when_the_geometry_drifted` | FAIL | no guard exists, so `_drifted` never runs. Corrected during Task 4's execution: it does not fail by *returning* a reading with `decoded == [1]` — it never reaches a return, because this test passes `{}` as the graded reading and `naturalness.evaluate_delta(src_stats, {})` raises an uncaught `KeyError` first. Red either way, and it still discriminates the guard (with the guard present the function returns before that call), but the mechanism named here was wrong. |
| `…still_lets_a_broken_render_raise` | **PASS** | Written reason: it is the control on the guard's narrowness, and it passes today because there is no guard at all to be too wide. Its job begins at Step 4 — if the implementer widens the existing `except` clause instead of wrapping the oracle's own call, this is the test that goes red. |

- [ ] **Step 3: Run them**

```bash
.venv/bin/python -m pytest tests/test_episode_qc.py -k source_reading -v
```

Expected: the two new behavioural tests FAIL, the control PASSES, and the two
existing wiring tests PASS (Step 1 kept them callable).

- [ ] **Step 4: Thread the params and add the guard**

In `scripts/episode_qc.py`, replace `_source_reading`'s body from `md = dict(ep.manifest)`
to the line before `frames = reframe.plan_frames_rgb(...)` with:

```python
    md = dict(ep.manifest)
    # The frozen sidecar first, on its own. rendered_params raises RuntimeError for a
    # path.meta.json that exists and will not parse — deliberately, so no caller
    # silently plans on the defaults instead (design §2.2) — and in THIS caller that
    # is one episode's geometry being unreadable, which is a named absence, not a
    # reason to abandon the packet run over the others. build_reel._predict already
    # degrades the identical failure to None for one episode via its broad clause;
    # this is that same decision, made narrowly.
    #
    # plan_ungraded deliberately does NOT share this clause: its own RuntimeError
    # comes from proc.run — a broken ffmpeg install, a corrupt but present video —
    # and reporting either as a clean 'absent' is exactly the swallow the clause
    # below was written to prevent.
    try:
        params = process_episode.rendered_params(ep.meta)
    except RuntimeError:
        return {"source": None, "delta": None}
    try:
        src = probe.source_for(md, Path(ep.path).parent)
        if not Path(src).exists():
            return {"source": None, "delta": None}
        plan = process_episode.plan_ungraded(md, src, ep.route, params=params)
    except (FileNotFoundError, KeyError, ValueError):
        return {"source": None, "delta": None}
    try:
        probe._refuse_on_drift(plan, ep.path, ep.meta)
    except RuntimeError:
        # The oracle the other two consumers of this plan map have always had
        # (build_reel._predict, probe.probe_grade) and this one never did — so a
        # retried episode's source was read through a crop it never shipped and
        # reported to the judge as its own (design 2026-09-24 §0.3). Recording the
        # render's params fixes every episode rendered from now on; this catches
        # the ones whose sidecar predates the field, and any drift a params record
        # cannot explain — a re-track, a swapped source.
        #
        # Caught HERE, at the oracle's own call, and not by widening the clause
        # above: that clause excludes RuntimeError for a measured reason — proc.run
        # raises it for a broken ffmpeg install or a corrupt-but-present file, and
        # reporting either as a clean 'absent' is exactly the swallow it was
        # written to prevent.
        #
        # Absence and not a raise: _evidence already reports every other sidecar
        # this way, and one episode's unreadable geometry must not abort a packet
        # run over the other seven.
        return {"source": None, "delta": None}
```

and append to the docstring, before the closing `"""`:

```
    Since 2026-09-24 the plan carries the params the render RECORDED
    (process_episode.rendered_params off ep.meta) and is checked against the frozen
    sidecars before anything is decoded. Absence is reported for a plan that cannot
    be shown to be the shipped geometry — a number read through the wrong crop is
    worse than no number, because the judge cannot tell it from a real one.
```

- [ ] **Step 5: Run the episode_qc suites**

```bash
.venv/bin/python -m pytest tests/test_episode_qc.py tests/lib/test_episode_qc.py tests/integration/test_episode_qc.py -v
```

Expected: PASS. The integration file builds its episodes with a **real**
`reframe.reframe` at default params over a real route, so the recomputed plan
agrees with the frozen sidecar and the new guard passes — confirm that rather
than assuming it.

- [ ] **Step 6: Commit**

```bash
git add scripts/episode_qc.py tests/test_episode_qc.py
git commit -m "fix(episode_qc): give the source reading the oracle it never had

_source_reading was the one consumer of the manifest->plan map with no drift
guard: for a retried episode it planned at the defaults and reported a source
read through a crop the episode never shipped as that episode's own. It now
plans with the params the render recorded and reports absence when the
recomputed geometry cannot be shown to be the shipped one.

The oracle's RuntimeError is caught at its own call rather than by widening
the existing except clause, which excludes RuntimeError for a measured
reason: proc.run raises it for a broken ffmpeg install.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: The reprocess writes beside the record it replaces

**Files:**
- Modify: `scripts/build_reel.py` — the reprocess arm (~line 201)
- Test: `tests/lib/test_build_reel.py` — one new test, one control, and **one
  shared-harness change**: `_wire`'s `fake_pe` records only `{"route": route_path}`
  and must also record `project_dir`.

**Interfaces:**
- Consumes: nothing from earlier tasks. Independent of 1–4.

- [ ] **Step 1: Widen the shared harness**

In `tests/lib/test_build_reel.py`, in `_wire`, change

```python
    def fake_pe(manifest, project_dir, route_path=None):
        seen["reprocess"].append({"route": route_path})
```

to

```python
    def fake_pe(manifest, project_dir, route_path=None):
        # project_dir recorded since 2026-09-24 (retry-record Task 5): WHERE the
        # reprocess writes its sidecars is the subject of a test now, and a fake
        # that drops the argument cannot tell the two candidate directories apart.
        seen["reprocess"].append({"route": route_path, "project_dir": project_dir})
```

**This claim was WRONG and Task 5's execution found it:** not every reader indexes
`["route"]`. `test_a_reprocessed_episode_hands_check_reel_its_NEW_chroma` asserted
the whole list-of-dicts (`seen["reprocess"] == [{"route": "r1.json"}]`) and breaks
on the added key. It has to be updated in the same step. Run the whole file at
Step 3 rather than trusting a claim like this one.

- [ ] **Step 2: Write the failing test and its control**

Append to `tests/lib/test_build_reel.py`:

```python
# --- 2026-09-24 retry-record Task 5: one episode, one scratch directory ---

def test_a_reprocess_writes_beside_the_sidecars_episodes_json_names(monkeypatch, tmp_path):
    """Phase 1 writes build/ep{i}; this driver is handed build/reel, so a reprocess
    used to write build/reel/ep{i} while ReelEpisode.path/meta still named the
    first. A re-pack then read a MIXED packet — fresh pixels, stale report,
    storyboard, geometry and track record — and the clip_digest binding that exists
    to catch a stale packet could not see it, because the stale half is not the
    clip (design 2026-09-24 §0.7).

    Note _rm() builds episodes with NO path, which is why this test builds its own:
    under the empty-path fallback every other test in this file keeps the old
    location, which is the control below."""
    phase1 = tmp_path / "build" / "ep0"
    phase1.mkdir(parents=True)
    eps = [ReelEpisode(manifest={"segment": "s0.mp4"}, clip="c0.mp4", route="r0.json",
                       path=str(phase1 / "path.json"), meta=str(phase1 / "path.meta.json")),
           ReelEpisode(manifest={"segment": "s1.mp4"}, clip="c1.mp4", route="r1.json")]
    rm = ReelManifest(episodes=eps, target_dur=6.0, cap=3)
    seen = _wire(monkeypatch, [_black_fail(0), _pass()])

    build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "build" / "reel"))

    assert seen["reprocess"] == [{"route": "r0.json", "project_dir": str(phase1)}]


def test_a_reprocess_of_an_episode_with_no_sidecar_keeps_the_work_dir(monkeypatch, tmp_path):
    """The control. A hand-authored reel manifest may legally carry no path
    (ReelEpisode.path defaults to "" and episode_qc._epdir refuses such a manifest
    by name), so there is nothing to derive and nothing to keep in step — today's
    location is kept rather than Path("").parent, which is "." and would write into
    the current working directory in silence."""
    rm = _rm(n=2)
    work = tmp_path / "build" / "reel"
    seen = _wire(monkeypatch, [_black_fail(0), _pass()])

    build_reel.build_reel(rm, str(tmp_path / "out"), str(work))

    assert seen["reprocess"] == [{"route": "r0.json", "project_dir": str(work / "ep0")}]
```

**Expected-before-the-change audit:**

| test | before | why |
|---|---|---|
| `…writes_beside_the_sidecars_episodes_json_names` | FAIL | today `epdir` is `work_dir/ep0`, so `project_dir` is `<tmp>/build/reel/ep0`, not `<tmp>/build/ep0` |
| `…with_no_sidecar_keeps_the_work_dir` | **PASS** | Written reason: it is the control, asserting today's behaviour for the branch Step 4 must not change. It is also the only thing standing between the fix and `Path("").parent == Path(".")` silently writing into the cwd. |

- [ ] **Step 3: Run them**

```bash
.venv/bin/python -m pytest tests/lib/test_build_reel.py -v
```

Expected: `…writes_beside_the_sidecars…` FAILS, `…keeps_the_work_dir` PASSES, and
every pre-existing test in the file PASSES (Step 1's extra key is additive).

- [ ] **Step 4: Derive the directory from the record**

In `scripts/build_reel.py`, in the reprocess loop, replace

```python
            epdir = str(Path(work_dir) / f"ep{item.idx}")
            manifest = rm.episodes[item.idx].manifest
```

with

```python
            ep = rm.episodes[item.idx]
            # Beside the record it replaces, not under this driver's own work dir.
            # ReelEpisode is frozen and nothing rewrites EPISODES.json, so its
            # path/meta keep naming phase 1's directory — and a second directory is
            # a second record with nothing keeping the two in step. The clip already
            # has this property: it is overwritten in place, which is why a re-pack
            # reads fresh pixels beside a stale report, storyboard, geometry and
            # track record (design 2026-09-24 §0.7). Same derivation
            # episode_qc._epdir already uses, so the packet and the render agree on
            # where one episode's scratch lives.
            #
            # This deliberately writes OUTSIDE work_dir: in a two-phase run phase 1
            # owns build/ep{i} and this driver is handed build/reel, so "beside the
            # record" is always outside it, and a guard refusing that would refuse
            # the only case that matters.
            #
            # The empty-path arm is not defensive padding: ReelEpisode.path defaults
            # to "" and a hand-authored reel manifest may carry none, where
            # Path("").parent is Path(".") — the current working directory, silently.
            epdir = (str(Path(ep.path).parent) if ep.path
                     else str(Path(work_dir) / f"ep{item.idx}"))
            manifest = ep.manifest
```

and in the two lines below, replace `rm.episodes[item.idx].route` with `ep.route`
so the local is used consistently.

- [ ] **Step 5: Run the file**

```bash
.venv/bin/python -m pytest tests/lib/test_build_reel.py -v
```

Expected: PASS, whole file.

- [ ] **Step 6: Run the reel-level suites**

```bash
.venv/bin/python -m pytest tests/integration/test_reel_retry.py tests/integration/test_reel_backhalf.py tests/lib/test_edl_to_reel.py tests/integration/test_episode_qc.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/build_reel.py tests/lib/test_build_reel.py
git commit -m "fix(build_reel): a reprocess writes beside the record EPISODES.json names

Phase 1 writes build/ep{i}; this driver is handed build/reel, so a reprocess
wrote build/reel/ep{i} while ReelEpisode.path/meta still named the first. A
re-pack then read a mixed packet: fresh pixels beside a stale report,
storyboard, geometry and track record, invisible to the clip_digest binding
because the stale half is not the clip.

The empty-path arm keeps today's location for a hand-authored manifest, where
Path('').parent would otherwise write into the working directory in silence.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: The real-pixel proofs

Design §4.1 and §4.4, plus §0.5's measurement kept as a test so the number that
justifies the whole slice cannot quietly stop being true.

**Files:**
- Create: `tests/integration/test_retry_record.py`
- Test: itself

**Interfaces:**
- Consumes: everything from Tasks 1–4.

- [ ] **Step 1: Write the file**

```python
"""The retry loop's record, proved against real pixels (design 2026-09-24 §4).

Every test here uses `golden_ride_segment` — the committed golden_ride.mp4 through
the range conversion — and the committed golden_route.json sampled against that
clip's own timeline. The real run cannot prove any of this any more: four of its
eight episodes, including the one retried episode the row was filed from, are
refused by plan_render's range guard before the drift oracle runs (§0.4).
"""
import json
from pathlib import Path

import pytest

from scripts import process_episode, probe, reframe
from scripts.lib import orchestration as orch
from scripts.lib.models import Delivery, ReframeSpec

ROUTE = "tests/fixtures/golden_route.json"


def _spec(**over):
    kw = dict(composition="center", grid="thirds", canvas=(9, 16),
              color_means=(128.0, 128.0, 128.0), delivery=Delivery.from_spec("native"))
    kw.update(over)
    return ReframeSpec(**kw)


@pytest.mark.integration
def test_one_ladder_step_moves_the_crop_path(golden_ride_segment):
    """§0.5, kept as a test. If this ever reports 0 moved samples the slice's whole
    premise is gone — the params would be unobservable in the geometry and nothing
    would need recording.

    Both knobs are asserted separately because they are NOT equally load-bearing:
    on this fixture the smoothing window does all the work and max_speed moves one
    sample by one pixel. Recording max_speed is still required, because
    _refuse_on_drift compares the path exactly and one pixel refuses as loudly as
    five — but a reader must not be told the two matter equally.
    """
    src = str(golden_ride_segment)
    base = reframe.plan_render(_spec(), src, ROUTE)
    stepped = orch.adjust_reframe_params(dict(orch.DEFAULT_PARAMS), ["jitter"])
    assert stepped == {"max_speed": 450.0, "smooth_window_s": 0.5}

    after = reframe.plan_render(_spec(**stepped), src, ROUTE)
    moved = [i for i, (a, b) in enumerate(zip(base.path, after.path)) if a != b]
    assert len(base.path) == len(after.path) == 95
    assert len(moved) == 74
    assert max(abs(a - b) for a, b in zip(base.path, after.path)) == 5

    speed_only = reframe.plan_render(_spec(max_speed=450.0), src, ROUTE)
    window_only = reframe.plan_render(_spec(smooth_window_s=0.5), src, ROUTE)
    assert sum(1 for a, b in zip(base.path, speed_only.path) if a != b) == 1
    assert sum(1 for a, b in zip(base.path, window_only.path) if a != b) == 74


@pytest.mark.integration
def test_a_first_lag_retry_moves_nothing_on_this_footage(golden_ride_segment):
    """§0.5's sharper half, kept so the slice cannot over-claim. The lag branch
    raises max_speed to 1125 and leaves the window alone — its own halving is
    `max(lo, w / 2)` where w starts AT lo, so it is inert until an earlier round has
    already widened it. The result here is a byte-identical path: on this footage a
    first on_line/centered retry was never broken, the oracle always passed, and a
    reader rebuilding at the defaults was already right.

    Recorded as a test and not only as a design sentence because it is the one
    number that bounds this slice's claim, and a change to the ladder or to
    pathsmooth would move it silently."""
    src = str(golden_ride_segment)
    base = reframe.plan_render(_spec(), src, ROUTE)
    lag = orch.adjust_reframe_params(dict(orch.DEFAULT_PARAMS), ["on_line"])
    assert lag == {"max_speed": 1125.0, "smooth_window_s": 0.25}
    after = reframe.plan_render(_spec(**lag), src, ROUTE)
    assert list(after.path) == list(base.path)


@pytest.mark.integration
def test_a_retry_only_happens_for_the_three_reasons_that_move_a_knob(golden_ride_segment):
    """§0.6. A retry for any other reason re-renders the same geometry, so it
    creates no unrecorded state and this slice's fix is not needed for it. Asserted
    on the params rather than on the rendered path: identical params cannot produce
    a different path, and comparing paths would leave the claim resting on the
    renderer's determinism instead of on the ladder's own branching."""
    base = dict(orch.DEFAULT_PARAMS)
    for reason in ("on_line", "centered", "jitter"):
        assert orch.adjust_reframe_params(base, [reason]) != base, reason
    for reason in ("composition", "black", "hero", "grade_damage"):
        assert orch.adjust_reframe_params(base, [reason]) == base, reason


@pytest.mark.integration
def test_the_sidecar_lets_a_retried_render_be_replanned_exactly(golden_ride_segment, tmp_path):
    """§4.4, the round trip. Render at attempt-2 params, then rebuild the plan from
    the sidecar: the oracle passes. Rebuild it from the manifest alone and the
    oracle refuses — which is what every reader did before this slice."""
    src = str(golden_ride_segment)
    d = tmp_path / "ep0"
    d.mkdir()
    out = str(d / "out.mp4")
    path_out = str(d / "path.json")
    meta_out = str(d / "path.meta.json")
    spec = _spec(max_speed=450.0, smooth_window_s=0.5)
    reframe.reframe(spec, src, ROUTE, out, path_out)

    md = {"segment": src, "out_path": out, "target_dur": 1.5,
          "composition": "center", "grid": "thirds", "canvas": [9, 16]}

    params = process_episode.rendered_params(meta_out)
    assert params == {"max_speed": 450.0, "smooth_window_s": 0.5}
    probe._refuse_on_drift(process_episode.plan_for(md, src, ROUTE, params=params),
                           path_out, meta_out)

    with pytest.raises(RuntimeError, match=r"recomputed crop path does not match"):
        probe._refuse_on_drift(process_episode.plan_for(md, src, ROUTE),
                               path_out, meta_out)


@pytest.mark.integration
def test_an_unretried_render_writes_the_sidecar_it_always_wrote(golden_ride_segment, tmp_path):
    """The control that must not move. An episode at the defaults writes neither
    key, so every golden sidecar and every byte-identity claim in the suite holds."""
    d = tmp_path / "ep0"
    d.mkdir()
    reframe.reframe(_spec(), str(golden_ride_segment), ROUTE,
                    str(d / "out.mp4"), str(d / "path.json"))
    written = json.loads((d / "path.meta.json").read_text())
    assert "max_speed" not in written and "smooth_window_s" not in written
    assert process_episode.rendered_params(d / "path.meta.json") is None
```

**Expected-before-the-change audit:** Tasks 1–4 are already committed by the time
this task runs, so all four tests are expected to PASS on first run. Their reason
for existing is not to go red now but to pin four numbers and one byte-identity
claim that nothing else in the suite pins. The two that would silently stop
discriminating are named in their own docstrings.

- [ ] **Step 2: Run the file**

```bash
.venv/bin/python -m pytest tests/integration/test_retry_record.py -v
```

Expected: PASS, five tests. If `test_one_ladder_step_moves_the_crop_path` reports
numbers other than 95/74/5/1/74, or the lag test's path is not byte-identical,
**stop and report** — the measurement this slice
is built on has moved, and adjusting the expected numbers to match would erase
the finding rather than record it.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_retry_record.py
git commit -m "test: pin the retry-record round trip against real pixels

One jitter ladder step moves 74 of 95 crop-path samples by up to 5px, almost
entirely through smooth_window_s; max_speed alone moves one sample by one
pixel. A render at those params replans exactly from its sidecar and refuses
from the manifest alone. An unretried render's sidecar is unchanged.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: Mutation battery, version, docs

**Files:**
- Modify: `CHANGELOG.md`, `.claude-plugin/plugin.json`, `docs/backlog.md`,
  `docs/backlog-closed.md`, `docs/build-status.md`, `CLAUDE.md`,
  `docs/specs/2026-08-18-episode-qc-rejudge-design.md`
- Test: the whole suite

- [ ] **Step 1: Run the battery**

17 rows. For each: apply the mutation with `sed`/a short python script, run the
named selection, restore with `git show HEAD:<path> > <path>`, and re-check
`git diff --stat` is empty before the next row. Every run under
`PYTHONDONTWRITEBYTECODE=1`. Write selections out literally — an unquoted shell
variable holding a selection arrives as one argument and prints `no tests ran`,
which reads exactly like a non-discriminating row.

| # | file | mutation | expect | named by |
|---|---|---|---|---|
| 1 | `scripts/reframe.py` | drop `max_speed=_recorded(...)` from `path_meta` | RED | `test_path_meta_records_params_that_differ_from_the_spec_defaults` |
| 2 | `scripts/reframe.py` | drop `smooth_window_s=_recorded(...)` from `path_meta` | RED | same |
| 3 | `scripts/reframe.py` | `_recorded` returns `value` unconditionally | RED | `test_path_meta_records_nothing_when_the_render_used_the_defaults`, `test_an_unretried_render_writes_the_sidecar_it_always_wrote` |
| 4 | `scripts/lib/models.py` | `to_dict` emits `max_speed` unconditionally | RED | `test_pathmeta_omits_the_params_it_was_not_given` |
| 5 | `scripts/lib/models.py` | `from_dict` uses `d.get("max_speed", 750.0)` | RED | `test_pathmeta_reads_an_older_sidecar_as_saying_nothing_about_the_params` |
| 6 | `scripts/lib/models.py` | `_opt_float` returns `None` on any exception instead of raising | RED | `test_pathmeta_still_hard_fails_when_a_param_is_present_but_unusable` |
| 7 | `scripts/process_episode.py` | `rendered_params` returns `{}` instead of `None` when nothing recorded | RED | `test_rendered_params_reports_a_sidecar_that_says_nothing_as_absence` |
| 8 | `scripts/process_episode.py` | `rendered_params` fills omitted keys from `meta` alone (drop the `DEFAULT_PARAMS` base) | RED | `test_rendered_params_fills_an_omitted_knob_from_the_defaults` |
| 9 | `scripts/process_episode.py` | `rendered_params` returns `None` for a corrupt sidecar instead of raising | RED | `test_rendered_params_still_raises_on_a_corrupt_sidecar` |
| 9b | `scripts/process_episode.py` | `rendered_params`' absence guard back to `.exists()` from `.is_file()` | RED | `test_rendered_params_reports_a_missing_or_unnamed_sidecar_as_absence` — its fourth assertion, added in Task 2's fix round, is the only thing covering this; under `.exists()` a `Path("")` raises an uncaught `IsADirectoryError` |
| 10 | `scripts/process_episode.py` | `_plan_parts` merges (`params = {**params, **derived}`) instead of replacing | RED | `test_plan_for_uses_the_given_params_instead_of_the_manifests_authored_window` |
| 11 | `scripts/process_episode.py` | `plan_for` ignores `params` (drop it from the `_plan_parts` call) | RED | the same, plus `test_the_sidecar_lets_a_retried_render_be_replanned_exactly` |
| 12 | `scripts/process_episode.py` | `plan_ungraded` drops the `params=params` passthrough | RED | `test_plan_ungraded_threads_params_through_to_the_spec` |
| 13 | `scripts/build_reel.py` | `_predict` drops `params=` | RED | `test_predict_plans_each_episode_with_the_params_its_sidecar_recorded` |
| 14 | `scripts/probe.py` | `probe_grade` drops `params=` on the **plain** plan only | **expected GREEN — see below** | — |
| 15 | `scripts/episode_qc.py` | `_source_reading` drops `params=` | RED | `test_source_reading_plans_with_the_params_the_render_recorded` |
| 16 | `scripts/episode_qc.py` | delete the `_refuse_on_drift` try/except block | RED | `test_source_reading_reports_absence_when_the_geometry_drifted` |
| 17 | `scripts/episode_qc.py` | widen the existing clause to `except (FileNotFoundError, KeyError, ValueError, RuntimeError)` and delete the separate guard block | RED | `test_source_reading_still_lets_a_broken_render_raise` |
| 17b | `scripts/episode_qc.py` | move `rendered_params(ep.meta)` back inside the `plan_ungraded` try, so its RuntimeError escapes | RED | `test_source_reading_reports_absence_for_a_corrupt_geometry_sidecar` — added in Task 4's fix round, and the only thing covering the guarantee the guard's comment states. Confirmed discriminating by reverting: an uncaught `RuntimeError` propagates out of `pack()`. |
| 18 | `scripts/build_reel.py` | revert `epdir` to `str(Path(work_dir) / f"ep{item.idx}")` | RED | `test_a_reprocess_writes_beside_the_sidecars_episodes_json_names` |
| 19 | `scripts/build_reel.py` | drop the empty-path arm: `epdir = str(Path(ep.path).parent)` always | RED | `test_a_reprocess_of_an_episode_with_no_sidecar_keeps_the_work_dir` |

**Row 14 is predicted GREEN and the prediction is part of the row.** Task 3 Step 7
reads `rendered_params` once into a local and passes the same local to both
halves, so "drops `params=` on the plain plan only" is a one-character-scale edit
with no test aimed at it: the probe's own pair-geometry claim is proved by
rendering, and no test in the suite renders a probe pair on a *retried* episode.
If it comes back RED, say which test caught it and why. If it comes back GREEN,
that is a real coverage hole and it must be closed with a new test before this
task is done — add one to `tests/integration/test_retry_record.py` that renders
an episode at attempt-2 params and asserts `probe.probe_grade`'s graded and plain
plans have the same `path`.

Rows 1–19 plus 9b are 20, not 17; the table is the authority. (Row 9b was added
during Task 2's fix round, which is why the numbering is not contiguous — renumbering
after the fact would break the roll-call's pointers back to this table.)

- [ ] **Step 2: Record the roll-call**

For every row: the mutation applied, the selection run, RED or GREEN, and for any
GREEN the test that closed it. A row whose named test turns out not to see its
own mutation is a finding about the test, not about the row — correct the table
in this plan rather than leaving a wrong pointer for the next reader.

- [ ] **Step 2b: Restore one dropped assertion (Task 5's deferred minor)**

Task 5 narrowed a pre-existing assertion to accommodate the harness's new
`project_dir` key: `test_a_reprocessed_episode_hands_check_reel_its_NEW_chroma`
went from `seen["reprocess"] == [{"route": "r1.json"}]` to
`seen["reprocess"][0]["route"] == "r1.json"`, dropping the "exactly one reprocess
ran" half. Narrowing was the right call — a full-dict equality re-couples an
unrelated test to this feature's output shape — but the file's own idiom pairs the
index check with a length check, and the length check never referenced
`project_dir`. Add it back, immediately above that line:

```python
    assert len(seen["reprocess"]) == 1
```

Run `.venv/bin/python -m pytest tests/lib/test_build_reel.py -v`; expected PASS.

- [ ] **Step 3: Run the whole suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS. Record the exact counts; the tree before this slice was
**3971 passed, 1 skipped**.

- [ ] **Step 4: Version and changelog**

This slice adds two optional contract fields and changes no CLI — **MINOR**.
Bump `.claude-plugin/plugin.json` and add the matching `CHANGELOG.md` heading.
The heading MUST be `## X.Y.Z — YYYY-MM-DD`;
`tests/test_plugin_manifests.py::test_every_changelog_heading_is_a_semver_and_they_descend`
enforces it, and a prose heading fails the suite.

```markdown
## 0.13.0 — 2026-09-24

### The retry loop's record

A retry changes what shipped and the record did not follow it.

- `path.meta.json` now records the `max_speed`/`smooth_window_s` the render
  actually used. `max_speed` had no manifest field at all, and the retry ladder
  rescales both without touching the declaration — one jitter step moves 74 of 95
  crop-path samples by up to 5px, so a reader rebuilding from the manifest rebuilt
  a different geometry. Emitted only when it differs from the default, so an
  unauthored, un-retried episode's sidecar is byte-identical.
- `build_reel._predict` and `probe grade` rebuild a retried episode's plan from
  that record. Before this, the episode that had trouble was the episode that lost
  its `grade_faithful` gate, and `probe grade` refused with a remedy that could not
  restore the lost values.
- `episode_qc`'s source reading was the one consumer with no drift oracle: it read
  a retried episode's source through a crop the episode never shipped and reported
  it to the judge as that episode's own. It now plans with the recorded params and
  reports absence when the geometry cannot be shown to be the shipped one.
- `build_reel`'s reprocess writes its sidecars beside the record `EPISODES.json`
  names, instead of one level deeper under its own work dir. A re-pack after an
  automatic retry was producing a mixed packet — fresh pixels, stale report,
  storyboard, geometry and track record — invisible to the packet's `clip_digest`
  binding, because the stale half is not the clip.
```

- [ ] **Step 5: Correct the re-judge design's §1.4**

`docs/specs/2026-08-18-episode-qc-rejudge-design.md` line ~71 states **"The retry
loop never engaged."** Nine `work/reel/ep{i}` reprocess directories across three
dates say otherwise (design 2026-09-24 §0.1). Replace that sentence — do not
delete the paragraph, whose cost conclusion survives — with:

```
`fail_reasons: []`. That is the LAST round of the last invocation, not the
history: nine `work/reel/ep{i}` reprocess directories across three dates say the
loop did engage, three of them recording `attempt: 2` (corrected 2026-09-24, see
[the retry-record design](2026-09-24-retry-record-design.md) §0.1). What the clean
final report does establish is the cost: a stop-before-delivery costs nothing on a
reel whose last round needed no reprocess, and costs one QC round exactly when an
episode was re-rendered — which is exactly when the verdict is stale.
```

- [ ] **Step 6: Backlog, archive, build status, registry**

- `docs/backlog.md`: remove the two rows this slice closes (the `EPISODES.json`
  retry-params row and the `build_reel` scratch-depth row). Add the four §6
  deferrals as new P3 rows, each with its source link.
- `docs/backlog-closed.md`: add both rows under *Closed from P2* with their
  closure notes. The note for the first must say that its cited evidence is no
  longer reproducible and why (§0.4) — that is the one fact no other document
  carries. Then **re-count by hand** and update the count in `CLAUDE.md`'s
  archive row: it was **67**, counted 2026-09-21, and `grep -c` is wrong in two
  directions (see that row's own parenthetical).
- `docs/build-status.md`: a Done entry naming the battery roll-call and the suite
  counts.
- `CLAUDE.md`: two Quick Reference rows, design and plan, in the house style —
  what the slice measured and what overturned, not what it built.

- [ ] **Step 7: Run the doc-contract tests and the whole suite**

```bash
.venv/bin/python -m pytest tests/test_plugin_manifests.py tests/test_skills_contract.py tests/test_cli_help.py -v && .venv/bin/python -m pytest -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add CHANGELOG.md .claude-plugin/plugin.json docs/backlog.md docs/backlog-closed.md docs/build-status.md CLAUDE.md docs/specs/2026-08-18-episode-qc-rejudge-design.md docs/plans/2026-09-24-retry-record.md
git commit -m "docs: close the two retry-record rows, bump to 0.13.0

Also corrects the episode-QC re-judge design's §1.4 'the retry loop never
engaged': that was read from the final reel_report.json, which describes the
last round and not the history. Nine reprocess directories across three dates
say the loop did engage.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage.**

| design section | task |
|---|---|
| §2.1 `PathMeta` gains the two knobs, conditional emission | 1 |
| §2.2 `rendered_params`, `plan_for(params=)` | 2 |
| §2.3 the three readers | 3 (two), 4 (the third + its guard) |
| §2.4 the reprocess directory + the empty-path fallback | 5 |
| §3 what does not change | 1 Step 11, 2 Step 6, 5 Step 6, 6's control test |
| §4.1 ladder step moves the path | 6 |
| §4.2 sidecar round-trips and stays still | 1 |
| §4.3 an old sidecar reads as absence | 1, 2 |
| §4.4 the round trip closes | 6 |
| §4.5 the reprocess writes into the phase-1 directory | 5 |
| §4.6 the packet stops being mixed | 5 Step 6 (the integration suite re-packs) |
| §4.7 the unguarded reading is guarded | 4 |
| §4.8 controls that must not move | 1 Step 11, 6's fourth test |
| §5 honest limits | recorded in the design; §5.2's asymmetry is pinned by Task 6's per-knob assertions |
| §6 deferrals | 7 Step 6 |

Gap found and closed while reviewing: §4.6 had no task of its own. It is covered
by Task 5 Step 6 running `tests/integration/test_episode_qc.py`, which packs real
episodes — but that suite has no *reprocessed* episode, so the coverage is
structural, not behavioural. Recorded here rather than papered over: closing it
properly needs an integration fixture that reprocesses and re-packs, which is
larger than this slice. **Added as a fifth §6 deferral in Task 7 Step 6.**

**2. Placeholder scan.** One deliberate non-placeholder: Task 3 Step 5 shows a
test shape and then rejects it in the same step, with the reason and the
replacement. That is a warning to the implementer, not a gap — the step ends with
a concrete instruction. No `TBD`, no "similar to Task N", no "add error
handling".

**3. Type consistency.** `rendered_params(meta_json: str | Path | None) -> dict | None`
is called in Tasks 3, 4 and 6 with exactly that name and that argument.
`plan_for(..., *, params=None)` and `plan_ungraded(..., *, params=None)` are
keyword-only everywhere they appear, including in every stub signature the plan
asks tests to write. `PathMeta.max_speed`/`smooth_window_s` are `float | None`
throughout. `epdir` stays a `str` in Task 5, matching what `process_episode`
already receives.

**4. Each code block against the prose that introduces it.** Checked block by
block. Two corrections made inline: Task 1 Step 4's prose said "conditional
emission" while an earlier draft's block emitted unconditionally and compared
against a constant inside `to_dict` — the judgement was moved to
`reframe._recorded` so the prose and the block agree on where it lives; and Task 2
Step 4's prose said "REPLACES rather than merges" while the block had a
`params.update(...)` merge, now a single `if params is None:` branch with no merge
at all.
