# Length re-time (Phase B tail) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two auto-fixes the pacing design parked together — `build_reel` absorbs a within-band length shortfall instead of escalating, and `edit_plan` re-times a paced reel's target to the footage it actually has.

**Architecture:** No new modules. `ReelCheckSpec` gains one threshold; `reel_orchestration.next_action` gains a one-sided length absorb and a `retime` action; `build_reel` adopts the re-timed target and re-checks; `edit_plan.build_edl` sets a paced reel's `target_dur` from the realized footage. The target only ever shrinks — see design §2 for why the physics forbids growing it.

**Tech Stack:** Python 3, stdlib only (`dataclasses`, `sys`), pytest. No new dependency, no ffmpeg argument, no librosa.

**Design:** [docs/specs/2026-07-18-length-retime-design.md](../specs/2026-07-18-length-retime-design.md)

---

## File Structure

| File | Responsibility after this slice |
|------|--------------------------------|
| `scripts/lib/models.py` | `ReelCheckSpec` carries `length_retime_max` — the max shortfall the reel driver may absorb |
| `scripts/check_reel.py` | the length gate's own `± 0.5 s` band is a named constant, readable against the absorb band |
| `scripts/lib/reel_orchestration.py` | the pure ladder decides: a within-band **shortfall** re-times, everything else about length still escalates |
| `scripts/build_reel.py` | executes the re-time — adopts the target, logs it, re-checks; never patches the report |
| `scripts/edit_plan.py` | a paced EDL's `target_dur` is `min(realized footage, spine fragment)`, both directions logged |

Tests extend four existing files; no new test module. Docs sync touches six files.

**Task order is dependency order:** Task 0's field is what Task 1 reads, Task 1's action is what Task 2 executes. Tasks 3 (authoring) and 4 (integration proof) depend only on 0–2 landing first.

---

## Task 0: `ReelCheckSpec.length_retime_max` + the named length gate

**Files:**
- Modify: `scripts/lib/models.py` (the `ReelCheckSpec` dataclass, ~line 626–656)
- Modify: `scripts/check_reel.py` (module constants near the top; the length gate at ~line 146)
- Test: `tests/lib/test_models.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_models.py`:

```python
def test_reel_check_spec_length_retime_max_defaults_to_one_second():
    # the band build_reel may absorb as a SHORTFALL, on top of the gate's own 0.5s (design §3.1)
    assert ReelCheckSpec(target_dur=12.0).length_retime_max == 1.0


def test_reel_check_spec_length_retime_max_rejects_non_positive():
    for bad in (0, -1.0):
        with pytest.raises(ValueError, match="length_retime_max"):
            ReelCheckSpec(target_dur=12.0, length_retime_max=bad)


def test_reel_check_spec_length_retime_max_rejects_non_number():
    with pytest.raises(ValueError, match="length_retime_max"):
        ReelCheckSpec(target_dur=12.0, length_retime_max="1.0")
```

If `ReelCheckSpec` / `pytest` are not already imported at the top of that file, add them to the existing import lines rather than duplicating imports mid-file.

- [ ] **Step 2: Run the tests to verify they fail**

```
.venv/bin/python -m pytest tests/lib/test_models.py -k length_retime_max -v ; echo "EXIT: $?"
```
Expected: FAIL — `TypeError: ReelCheckSpec.__init__() got an unexpected keyword argument 'length_retime_max'` (and the default test fails with `AttributeError`).

- [ ] **Step 3: Add the field + validation**

In `scripts/lib/models.py`, add the field as the LAST field of `ReelCheckSpec` (after `layout_jump_max`):

```python
    length_retime_max: float = 1.0     # max shortfall (target − dur) build_reel absorbs by
                                       # re-timing the target to the reel's real length (§3)
```

and the validation as the LAST check in its `__post_init__` (after the `layout_jump_max` check):

```python
        if not isinstance(self.length_retime_max, (int, float)) or self.length_retime_max <= 0:
            raise ValueError(f"ReelCheckSpec.length_retime_max must be a positive number of "
                             f"seconds, got {self.length_retime_max!r}")
```

Note `isinstance(True, int)` is `True`, matching the neighbouring `color_delta_max`/`layout_jump_max` checks, which accept a bool for the same reason — do not add a bool guard here that its siblings do not have.

- [ ] **Step 4: Run the tests to verify they pass**

```
.venv/bin/python -m pytest tests/lib/test_models.py -v ; echo "EXIT: $?"
```
Expected: PASS, whole file green (the new field is defaulted, so no existing construction changes).

- [ ] **Step 5: Promote the length gate's literal to a named constant**

In `scripts/check_reel.py`, add beside the existing `_UNCHECKED` dict (module level, after it):

```python
_LENGTH_TOL = 0.5      # the length gate's own ± band; build_reel absorbs a further
                       # (_LENGTH_TOL, spec.length_retime_max] of SHORTFALL on top (§3)
```

and change the gate in `run()` from the literal to the constant:

```python
    length_ok = abs(total - spec.target_dur) <= _LENGTH_TOL
```

This is behaviour-preserving — the same number, named.

- [ ] **Step 6: Run the reel-check tests to confirm nothing moved**

```
.venv/bin/python -m pytest tests/lib/test_check_reel.py tests/lib/test_models.py -v ; echo "EXIT: $?"
```
Expected: PASS — the constant is the same number, so every existing length assertion holds.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/models.py scripts/check_reel.py tests/lib/test_models.py
git commit -m "feat: ReelCheckSpec.length_retime_max + named length gate (§3.1)"
```

---

## Task 1: `next_action` absorbs a within-band shortfall

**Files:**
- Modify: `scripts/lib/reel_orchestration.py` (whole file is 63 lines; touch `ReelAction`, add `_shortfall`, rewrite `next_action`'s loop)
- Test: `tests/lib/test_reel_orchestration.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_reel_orchestration.py`:

```python
def _length(dur, target):
    return ReelFailure("length", "pacing", None, {"dur": dur, "target": target})


def test_within_band_shortfall_retimes_to_the_reels_real_length():
    # the reel is 0.7s SHORT of target, inside a 1.0s band → accept the real length
    a = ro.next_action([_length(11.3, 12.0)], {}, cap=3, length_retime_max=1.0)
    assert a.kind == "retime"
    assert a.retime == 11.3
    assert a.reprocess == () and a.finding is None


def test_shortfall_past_the_band_still_escalates():
    a = ro.next_action([_length(10.5, 12.0)], {}, cap=3, length_retime_max=1.0)
    assert a.kind == "escalate"
    assert a.finding["check"] == "length" and a.finding["escalate_to"] == "pacing"
    assert a.retime is None


def test_over_length_reel_is_never_absorbed_even_inside_the_band():
    # the one-sided proof: the SAME 0.7s gap that re-times as a shortfall must escalate
    # when the reel runs LONG — mix refuses a stem longer than its fragment (design §2)
    a = ro.next_action([_length(12.7, 12.0)], {}, cap=3, length_retime_max=1.0)
    assert a.kind == "escalate" and a.finding["check"] == "length"


def test_within_band_shortfall_rides_along_with_a_colour_reprocess():
    fails = [_length(11.3, 12.0),
             _color(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0])]
    a = ro.next_action(fails, {}, cap=3, length_retime_max=1.0)
    assert a.kind == "reprocess"
    assert a.reprocess[0].idx == 1
    assert a.retime == 11.3          # adopted first so length stops re-firing while colour converges


def test_escalate_still_wins_over_an_absorbable_shortfall():
    # a capped colour fail alongside a within-band shortfall → escalate; the pending
    # re-time is discarded with the round (the reel never delivers on an unfixable fault)
    fails = [_length(11.3, 12.0),
             _color(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0])]
    a = ro.next_action(fails, {1: 3}, cap=3, length_retime_max=1.0)
    assert a.kind == "escalate"
    assert a.finding["reason"] == "reprocess-capped"
    assert a.retime is None


def test_length_band_defaults_to_zero_so_an_unaware_caller_keeps_escalating():
    # the pure core's conservative default: opting in lives in the spec the driver threads
    a = ro.next_action([_length(11.3, 12.0)], {}, cap=3)
    assert a.kind == "escalate" and a.finding["check"] == "length"
```

- [ ] **Step 2: Run the tests to verify they fail**

```
.venv/bin/python -m pytest tests/lib/test_reel_orchestration.py -v ; echo "EXIT: $?"
```
Expected: the six new tests FAIL — `TypeError: next_action() got an unexpected keyword argument 'length_retime_max'`; the 13 pre-existing tests still PASS.

- [ ] **Step 3: Implement**

In `scripts/lib/reel_orchestration.py`, extend `ReelAction`:

```python
@dataclass(frozen=True)
class ReelAction:
    """The outcome of one reel-loop round (design §3): deliver the reel as-is,
    reprocess a set of culprit episodes, re-time the target to the reel's real
    length, or escalate up the chain with a finding. Exactly one kind fires per
    round; the shell dispatches on it. `retime` may also ride along with a
    reprocess — the target is adopted before the round's work."""
    kind: str                          # "deliver" | "reprocess" | "escalate" | "retime"
    reprocess: tuple[ReprocessItem, ...] = ()
    finding: dict | None = None
    retime: float | None = None        # new target_dur when a within-band shortfall is absorbed (§3)
```

add the helper below `_correction`:

```python
def _shortfall(f: ReelFailure) -> float | None:
    """target − dur for a length failure, or None when the reel runs LONGER than target.
    An over-length reel is never absorbed: the stem is cut from a fixed music fragment and
    mix.mix refuses dur > music.duration, so re-timing UP would trade a clean escalate for
    a hard raise at the mixer (design §2)."""
    gap = f.detail["target"] - f.detail["dur"]
    return gap if gap > 0 else None
```

and rewrite `next_action`:

```python
def next_action(fail_reasons: list[ReelFailure], attempts: dict[int, int], cap: int,
                length_retime_max: float = 0.0) -> ReelAction:
    """One decision for the whole reel (design §3). Escalate wins the round: any
    non-auto-fixable or capped failure returns Escalate immediately, so we never
    spend reprocess rounds on a reel that also carries an unfixable fault. `length`
    is auto-fixable in exactly one shape — a shortfall inside length_retime_max,
    absorbed by re-timing the target DOWN to the reel's real length; an over-length
    reel and a shortfall past the band still escalate to pacing. The 0.0 default
    reproduces the pre-slice behaviour for a caller that passes no band."""
    if not fail_reasons:
        return ReelAction("deliver")
    items: dict[int, ReprocessItem] = {}   # idx → ReprocessItem; colour wins over a bare black re-encode
    retime: float | None = None
    for f in fail_reasons:
        if f.check == "length":
            gap = _shortfall(f)
            if gap is not None and gap <= length_retime_max:
                retime = f.detail["dur"]   # the reel IS this long — make it the target
                continue
            return ReelAction("escalate", finding={
                "reason": "not-auto-fixable", "check": f.check,
                "episode_idx": f.episode_idx, "escalate_to": f.escalate_to,
                "detail": f.detail})
        if f.check not in _REPROCESS_CLASS:
            return ReelAction("escalate", finding={
                "reason": "not-auto-fixable", "check": f.check,
                "episode_idx": f.episode_idx, "escalate_to": f.escalate_to,
                "detail": f.detail})
        if attempts.get(f.episode_idx, 0) >= cap:
            return ReelAction("escalate", finding={
                "reason": "reprocess-capped", "check": f.check, "episode_idx": f.episode_idx,
                "escalate_to": "edit-plan",
                "detail": (f"episode {f.episode_idx} still fails {f.check} after {cap} "
                           "reprocesses — the source window or grade is wrong; fix the segment/EDL")})
        corr = _correction(f) if f.check == "color_across_cuts" else None
        if f.episode_idx not in items or corr is not None:
            items[f.episode_idx] = ReprocessItem(f.episode_idx, corr)
    if items:
        return ReelAction("reprocess", reprocess=tuple(items[k] for k in sorted(items)), retime=retime)
    if retime is not None:
        return ReelAction("retime", retime=retime)
    return ReelAction("deliver")
```

Note the `length` branch is checked BEFORE the generic `_REPROCESS_CLASS` branch, and both escalate with the identical finding shape — `length` is not added to `_REPROCESS_CLASS` (it is not a reprocess; nothing is re-rendered).

- [ ] **Step 4: Run the tests to verify they pass**

```
.venv/bin/python -m pytest tests/lib/test_reel_orchestration.py -v ; echo "EXIT: $?"
```
Expected: PASS — all 19 (13 pre-existing, unchanged by the defaulted parameter, + 6 new).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/reel_orchestration.py tests/lib/test_reel_orchestration.py
git commit -m "feat: next_action absorbs a within-band length shortfall (§3.2)"
```

---

## Task 2: `build_reel` adopts the re-time and re-checks

**Files:**
- Modify: `scripts/build_reel.py` (imports; `build_reel()`'s spec/loop)
- Test: `tests/lib/test_build_reel.py` (extend the shared `_wire` helper at line 26, then append two tests)

- [ ] **Step 1: Write the failing tests**

This file drives the loop through `_wire(monkeypatch, reports)`, which feeds `check_reel.run` a **queue** of canned reports (one per round) and records what the driver forwarded into a `seen` dict. To assert the re-timed target reached the second check, record the spec's target — the same additive extension `geometry`/`platform`/`titles` already got, and which the helper's own comment documents.

In `_wire`, add `"targets": []` to the `seen` dict literal and one line to `fake_run`:

```python
    seen = {"deliver": [], "reprocess": [], "titles": [], "geometry": None, "platform": "",
            "targets": []}
```
```python
    def fake_run(m, e, s, o, music=None, audio=None, geometry=None, platform=""):
        seen["geometry"] = geometry
        seen["platform"] = platform
        seen["targets"].append(s.target_dur)     # a length re-time replaces it between rounds
        return rq.pop(0)
```

Add a failure builder beside `_color_fail`:

```python
def _length_fail(dur, target):
    return ReelReport(
        checks={"length": CheckResult("length", False, {"dur": dur, "target": target})},
        fail_reasons=[ReelFailure("length", "pacing", None, {"dur": dur, "target": target})],
        episode_count=2)
```

and append the two tests (`_rm()` builds a `target_dur=6.0` manifest, so a 5.3 s reel is a 0.7 s shortfall — inside the 1.0 s band):

```python
def test_within_band_shortfall_retimes_the_target_and_delivers(monkeypatch, tmp_path):
    # round 1 sees a 0.7s shortfall → adopt 5.3 as the target and re-check; round 2 is clean
    seen = _wire(monkeypatch, [_length_fail(5.3, 6.0), _pass()])
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"                  # absorbed, not escalated
    assert seen["targets"] == [6.0, 5.3]                 # re-checked against the reel's real length
    assert seen["reprocess"] == []                       # nothing was re-rendered to fix a length


def test_shortfall_past_the_band_still_stops_and_reports(monkeypatch, tmp_path):
    seen = _wire(monkeypatch, [_length_fail(3.0, 6.0)])   # 3.0s short — a missing episode, not drift
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["check"] == "length" and res["finding"]["escalate_to"] == "pacing"
    assert seen["deliver"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```
.venv/bin/python -m pytest tests/lib/test_build_reel.py -v ; echo "EXIT: $?"
```
Expected: the first new test FAILS — `status == "stop_and_report"` (today `length` escalates) and `seen["targets"] == [6.0]`, with the second canned report left unconsumed. The second new test already PASSES (past-the-band escalation is today's behaviour) — it is the regression guard that the band did not swallow everything, so a green run for it here is correct.

- [ ] **Step 3: Implement**

In `scripts/build_reel.py`, extend the imports:

```python
import argparse
import dataclasses
import json
import sys
from pathlib import Path
```

add the logger below the imports (the `beats._log` / `edit_plan._log` pattern):

```python
def _log(msg: str) -> None:
    print(msg, file=sys.stderr)
```

inside `build_reel()`, make the check spec a round-scoped local — add it beside the other loop state (next to `attempts`/`cc`):

```python
    spec = rm.check_spec          # mutable across rounds: a length re-time replaces target_dur
```

grow the defensive bound by one:

```python
    for _ in range(rm.cap * len(rm.episodes) + 3):   # defensive bound; +3 leaves headroom for the
                                                     # once-after-picture mix `continue`, one
                                                     # length-retime `continue`, and the deliver pass
```

pass the local spec + the band, and adopt a re-time before dispatching on `kind` — replace the two lines that currently read `report = check_reel.run(... rm.check_spec ...)` and `action = reel_orchestration.next_action(report.fail_reasons, attempts, rm.cap)` with:

```python
        report = check_reel.run(master, clips, spec, report_path,
                                music=music, audio=audio, geometry=geometry, platform=rm.platform)
        action = reel_orchestration.next_action(report.fail_reasons, attempts, rm.cap,
                                                spec.length_retime_max)
        if action.retime is not None:      # absorb a within-band shortfall: the reel IS this long
            _log(f"build_reel: reel is {action.retime:.2f}s against a {spec.target_dur:.2f}s target "
                 f"— inside the {spec.length_retime_max:.2f}s band, re-timing the target to the "
                 f"reel's real length (the stem is already cut to the master, so audio stays in sync)")
            spec = dataclasses.replace(spec, target_dur=action.retime)
        if action.kind == "retime":
            continue                       # re-check with the re-timed target; clips unchanged,
                                           # need_assemble stays False so nothing is re-assembled
```

Leave the `deliver` / `escalate` / reprocess branches exactly as they are.

- [ ] **Step 4: Run the tests to verify they pass**

```
.venv/bin/python -m pytest tests/lib/test_build_reel.py -v ; echo "EXIT: $?"
```
Expected: PASS, whole file green. The existing driver tests are unaffected: on a round with no re-time the local `spec` is exactly the `rm.check_spec` value they always saw, and `seen["targets"]` is additive — no existing assertion reads it.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_reel.py tests/lib/test_build_reel.py
git commit -m "feat: build_reel adopts a length re-time and re-checks (§3.3)"
```

---

## Task 3: the authoring back-edge in `edit_plan.build_edl`

**Files:**
- Modify: `scripts/edit_plan.py` (a module constant, a helper beside `_bind_pacing`, three lines in `build_edl`)
- Test: `tests/lib/test_edit_plan.py` (append to the pacing section at the tail)

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_edit_plan.py` (the pacing section already imports `Slot`/`Spine` and defines `_footage`/`_sel3`/`_spine2`):

```python
def test_build_edl_back_edge_retimes_the_target_to_the_realized_footage(capsys):
    # slot 0 wants 5s, window A/0 is only 2s → the reel is 2s, so say 2s (design §4)
    spine = Spine(slots=(Slot(0, 0.0, 5.0, 0.5, "hook"),), target_dur=5.0, tempo=120.0)
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}],
           "target_dur": 5.0}
    edl = edit_plan.build_edl(_footage(), sel, pacing=spine)
    assert edl.target_dur == 2.0                       # re-timed DOWN, not the optimistic 5.0
    assert "back-edge" in capsys.readouterr().err      # never silent


def test_build_edl_back_edge_silent_when_the_footage_fills_the_spine(capsys):
    # window A/0 is 2s and its only slot wants exactly 2s → nothing to re-time
    spine = Spine(slots=(Slot(0, 0.0, 2.0, 0.5, "hook"),), target_dur=2.0, tempo=120.0)
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}]}
    edl = edit_plan.build_edl(_footage(), sel, pacing=spine)
    assert edl.target_dur == 2.0
    assert "back-edge" not in capsys.readouterr().err


def test_build_edl_back_edge_clamps_an_overflow_to_the_fragment(capsys):
    # 3 episodes realize 5.0s against a 2.5s spine → the target stays at the fragment so the
    # excess escalates at the reel gate; mix can't stretch music to cover it (design §2)
    edl = edit_plan.build_edl(_footage(), _sel3(), pacing=_spine2())
    assert edl.target_dur == 2.5
    err = capsys.readouterr().err
    assert "back-edge" in err and "escalates at the reel gate" in err


def test_build_edl_without_pacing_keeps_the_selections_target(capsys):
    # regression guard: the un-paced path is untouched by the back-edge
    sel = dict(_sel3(), target_dur=9.0)
    edl = edit_plan.build_edl(_footage(), sel)
    assert edl.target_dur == 9.0
    assert "back-edge" not in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

```
.venv/bin/python -m pytest tests/lib/test_edit_plan.py -k back_edge -v ; echo "EXIT: $?"
```
Expected: FAIL — the first asserts `edl.target_dur == 2.0` but gets `5.0` (the selection's optimistic value); the overflow test gets `None`.

- [ ] **Step 3: Implement**

In `scripts/edit_plan.py`, add the constant at module level (below the imports, above `_log` or beside any existing module constant):

```python
_BACK_EDGE_TOL = 1e-6      # a realized total within this of the spine target "fills the spine"
```

add the helper immediately after `_bind_pacing`:

```python
def _back_edge_target(episodes: list, spine: Spine) -> float:
    """The paced reel's target length (design §4): the realized footage, clamped to the
    spine's fragment. An under-fill re-times the target DOWN to what the footage actually
    delivers — the montage §4.1 pacing-gate back-edge — so the reel's length gate passes by
    construction instead of escalating a whole pipeline later. An over-flow keeps the
    fragment length, so the excess escalates at the reel gate rather than reaching mix,
    which refuses a stem longer than its fragment (§2). `realized` sums EVERY bound episode,
    including an over-flow tail left at beat_slot=None — the reel is as long as everything
    in it. Both directions log; neither is silent."""
    realized = sum(e.dur for e in episodes)
    if realized < spine.target_dur - _BACK_EDGE_TOL:
        _log(f"pacing back-edge: the bound footage realizes {realized:.2f}s of the "
             f"{spine.target_dur:.2f}s spine — re-timing the reel target to {realized:.2f}s; "
             f"for a tighter cut re-pick a shorter fragment "
             f"(beats --auto-start --duration {realized:.0f}) and re-derive the spine")
    elif realized > spine.target_dur + _BACK_EDGE_TOL:
        _log(f"pacing back-edge: the bound footage realizes {realized:.2f}s against a "
             f"{spine.target_dur:.2f}s spine — the target stays at the fragment length; the "
             f"excess {realized - spine.target_dur:.2f}s escalates at the reel gate "
             f"(extend the fragment or drop episodes — music cannot be invented)")
    return min(realized, spine.target_dur)
```

and wire it into `build_edl`'s tail — replace

```python
    if pacing is not None:
        episodes = _bind_pacing(episodes, pacing)
    cap = selection.get("cap")
    return EDL(episodes=tuple(episodes), music=selection.get("music"), cast=cast,
               cap=cap if cap is not None else 3, target_dur=selection.get("target_dur"))
```

with

```python
    target = selection.get("target_dur")
    if pacing is not None:
        episodes = _bind_pacing(episodes, pacing)
        target = _back_edge_target(episodes, pacing)   # pacing owns a paced reel's length (§4)
    cap = selection.get("cap")
    return EDL(episodes=tuple(episodes), music=selection.get("music"), cast=cast,
               cap=cap if cap is not None else 3, target_dur=target)
```

Also extend `build_edl`'s docstring sentence about reel knobs to note that `target_dur` is derived from the spine when pacing is supplied, so the contract is documented where a reader looks for it.

- [ ] **Step 4: Run the whole edit-plan suite to verify the new tests pass and the old ones still do**

```
.venv/bin/python -m pytest tests/lib/test_edit_plan.py -v ; echo "EXIT: $?"
```
Expected: PASS. Three pre-existing paced tests now produce a non-`None` `target_dur` where they produced `None` — none of them assert on `target_dur`, so they stay green, and `test_build_edl_pacing_overflow_tail_unbound`'s `"exceed the 2-slot spine" in err` still holds because the new line is appended, not substituted. If any assertion did break, fix the TEST only if it asserted the old `None`; a broken assertion about `beat_slot`/`dur` means the implementation is wrong.

- [ ] **Step 5: Commit**

```bash
git add scripts/edit_plan.py tests/lib/test_edit_plan.py
git commit -m "feat: pacing-gate back-edge re-times a paced EDL's target (§4)"
```

---

## Task 4: real-ffmpeg proof that the reel re-times instead of escalating

**Files:**
- Test: `tests/integration/test_reel_retry.py` (append — reuses the file's existing `_reframe` helper and the `sample_clip` fixture)

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_reel_retry.py`:

```python
@pytest.mark.integration
def test_build_reel_absorbs_a_within_band_shortfall(tmp_path, sample_clip):
    # the reel is real; the TARGET is 0.7s optimistic — inside the 1.0s band, so the driver
    # re-times to the reel's real length and delivers instead of waking a human (design §3)
    ep0 = _reframe(sample_clip, tmp_path, 645, "ep0")
    ep1 = _reframe(sample_clip, tmp_path, 1045, "ep1")
    real = sum(check_reel._probe_dur(e) for e in (ep0, ep1))
    rm = ReelManifest(
        episodes=[ReelEpisode(manifest={"segment": str(sample_clip)}, clip=ep0,
                              route=str(tmp_path / "ep0.route.json")),
                  ReelEpisode(manifest={"segment": str(sample_clip)}, clip=ep1,
                              route=str(tmp_path / "ep1.route.json"))],
        target_dur=real + 0.7, variety_min=4, changelog="retime golden")
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))

    assert res["status"] == "delivered"
    length = res["report"]["checks"]["length"]
    assert length["passed"] is True
    # the delivered report states the reel's REAL length as its target — re-checked, not patched
    assert abs(length["detail"]["target"] - real) < 0.05


@pytest.mark.integration
def test_build_reel_escalates_a_shortfall_past_the_band(tmp_path, sample_clip):
    ep0 = _reframe(sample_clip, tmp_path, 645, "ep0")
    real = check_reel._probe_dur(ep0)
    rm = ReelManifest(
        episodes=[ReelEpisode(manifest={"segment": str(sample_clip)}, clip=ep0,
                              route=str(tmp_path / "ep0.route.json"))],
        target_dur=real + 3.0, variety_min=4, changelog="retime golden")
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))

    assert res["status"] == "stop_and_report"
    assert res["finding"]["check"] == "length" and res["finding"]["escalate_to"] == "pacing"
```

- [ ] **Step 2: Run the tests to verify they fail**

```
.venv/bin/python -m pytest tests/integration/test_reel_retry.py -m integration -v ; echo "EXIT: $?"
```
Expected: the first new test FAILS with `status == "stop_and_report"` if Tasks 1–2 were skipped. If Tasks 1–2 are already committed, it should PASS on the first run — that is fine and expected for an integration proof written after the unit work; state which happened in the task report rather than forcing a red run.

- [ ] **Step 3: No implementation — this task is proof only**

If either test fails after Tasks 0–3 are in, the defect is in the implementation, not the test. Debug with `superpowers:systematic-debugging`; do not weaken the assertions.

- [ ] **Step 4: Run the full integration suite to confirm no neighbour moved**

```
.venv/bin/python -m pytest tests/integration -m integration -v ; echo "EXIT: $?"
```
Expected: PASS (a handful of skips are normal on a machine without libvidstab / drawtext / demucs / network — report the skip count, do not chase it).

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_reel_retry.py
git commit -m "test: real-ffmpeg proof of the length re-time and its band (§7)"
```

---

## Task 5: docs sync + full suite

**Files:**
- Modify: `docs/specs/2026-07-14-pacing-design.md`, `docs/specs/2026-07-11-reel-retry-loop-design.md`, `docs/specs/2026-07-05-montage-skillset-design.md`, `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`

- [ ] **Step 1: Reconcile the two designs that deferred this work**

In `docs/specs/2026-07-14-pacing-design.md`:
- §10's first bullet ("**Retry-time auto-fix** … deferred (scope 1)") and second bullet ("**Pacing-gate back-edge** … deferred") each become **landed 2026-07-18**, naming `docs/specs/2026-07-18-length-retime-design.md`. Keep the librosa `start_offset` re-pick called out as still-deferred inside the back-edge bullet — it is, and the sentence "`choose_offset` already exists to re-pick manually" stays true.
- Scope decision 1's "stays deferred … is a separate slice" sentence gains a trailing "**(landed 2026-07-18 as its own slice — see the length re-time design.)**" rather than being rewritten — dated decisions are append-only.

In `docs/specs/2026-07-11-reel-retry-loop-design.md`:
- the ladder table row `| length (whole-reel, no episode_idx) | escalate | **Escalate**(pacing, "spine off target") |` gains the within-band shortfall re-time as its new first outcome; over-length and past-the-band still escalate.
- the deferred bullet "**`variety` / `length` auto-fix** — need the front-half EDL/pacing stages" records that `length` landed 2026-07-18 and `variety` did not.

- [ ] **Step 2: Mark the montage back-edge built**

In `docs/specs/2026-07-05-montage-skillset-design.md`, the §4.1 back-edge row (`| pacing gate (spine won't fit) | re-pick start_offset | music-and-mood: different fragment/track |`) and the §4.1 prose sentence about the built-in back-edge gain a **Built (2026-07-18)** note: the re-time ships as a pure `min(realized, fragment)` in `edit_plan.build_edl`; re-picking `start_offset` stays the manual rung (`beats --auto-start`).

- [ ] **Step 3: Update the status docs**

In `docs/build-status.md`, add a "Done" entry in the established shape — plan + design links, what shipped per file, the load-bearing invariants (one-sided band; loop-2 stays mechanical; report re-checked not patched), the test count from Step 5's run, and what stays deferred (librosa re-pick, re-cut in loop-2, overflow auto-fix). Refresh `_Last updated:_`.

In `docs/pipeline-map.md`:
- the **Upcoming** roadmap bullet "**Phase B — music spine** ◐" flips to `- [x] **Phase B — music spine**` with its "Remaining — the **two** auto-fixes…" sentence replaced by a landed note dated 2026-07-18.
- the "Critical path to autonomous v1" paragraph's closing sentence "Genuinely open on the quality side: the two **pacing auto-fixes**." retires — with Phase B closed the honest replacement names what is actually left (5.4 trend-scan, the 5.1 cap-3 parallel fan-out, the §7 misc-engine tail).
- refresh `_Last updated:_`.

In `CLAUDE.md`, add two Quick Reference rows (this design + this plan) in the established one-line style, placed after the reel-review rows.

- [ ] **Step 4: Run the full suite**

```
.venv/bin/python -m pytest tests -v ; echo "EXIT: $?"
```
Expected: PASS. Record the exact `N passed, M skipped` line — do NOT pipe through `tail`/`head`, which swallows the exit code. The prior slice's tip was **1216 passed, 8 skipped**; this slice adds ~15 unit + 2 integration tests.

- [ ] **Step 5: Commit**

```bash
git add docs CLAUDE.md
git commit -m "docs: sync pacing/reel-retry/montage/status — Phase B tail closed"
```

- [ ] **Step 6: Final whole-slice review**

Dispatch a fresh reviewer over `git diff main...HEAD` with the design as the requirement. It must verify, adversarially:
1. **One-sidedness** — no path absorbs an over-length reel; `_shortfall` returns `None` for it and both edges escalate. A reel longer than its music fragment must never reach `mix`.
2. **Escalate-wins survives** — a capped/unfixable failure alongside an absorbable shortfall still escalates, and the pending `retime` dies with the round.
3. **Loop-2 stays mechanical** — no new import of `extract`/`edit_plan` in `build_reel`; frozen routes and locked clips untouched; the master's duration is still invariant across reprocess rounds.
4. **The report is re-checked, not patched** — nothing writes a `CheckResult` outside `check_reel`, and `deliver`'s hard gate is satisfied by a genuinely passing report.
5. **Termination** — the loop bound still covers the worst case (`cap × episodes` reprocess rounds + the mix `continue` + the retime `continue` + the deliver pass), and a re-time cannot loop (adopting the target makes the gate pass).
6. **The un-paced path is untouched** — `pacing is None` yields exactly today's `EDL.target_dur`, and `next_action`'s `0.0` default yields exactly today's escalation.

---

## Self-Review

**Spec coverage.** Design §3.1 → Task 0 (field, validation, `_LENGTH_TOL`). §3.2 → Task 1 (`retime`, `_shortfall`, the absorb). §3.3 → Task 2 (mutable spec, adopt, `continue`, bound, `_log`). §4 → Task 3 (`_back_edge_target`, the three cases, the wiring). §7 → Tasks 0–4 (every listed test has a step; the §7 count of 7 orchestration tests maps to 6 new + the pre-existing `test_length_escalates_to_pacing`, which is the seventh and needs no change since its 7.0-vs-6.0 failure is over-length). §10 → Task 5. §2/§8/§9 are rationale and non-goals — nothing to build.

**Placeholder scan.** Every code step carries the actual code; every run step carries the exact command and its expected outcome, and every test path is a verified real file (`tests/lib/test_models.py`, `tests/lib/test_reel_orchestration.py`, `tests/lib/test_build_reel.py`, `tests/lib/test_edit_plan.py`, `tests/lib/test_check_reel.py`, `tests/integration/test_reel_retry.py`). Two expectations are deliberately "may already pass" rather than red, and say so explicitly instead of pretending: Task 2's second test (past-the-band escalation is today's behaviour — it is a regression guard) and Task 4's proofs when Tasks 1–2 already landed. Neither is a placeholder; both name the outcome to report.

**Type consistency.** `ReelAction.retime` is `float | None` everywhere it is read (`action.retime is not None` in the shell, `a.retime == 11.3` / `is None` in tests). `_shortfall` returns `float | None` and is only ever compared after a `None` check. `length_retime_max` is a `float` on `ReelCheckSpec`, threaded positionally as `next_action`'s fourth argument, defaulting to `0.0` in the pure core and `1.0` in the spec. `_back_edge_target` returns `float`, which `EDL.target_dur` accepts (it validates `float | None`, positive). `dataclasses.replace` re-runs `ReelCheckSpec.__post_init__`, so a re-timed target is re-validated as positive — a zero-length master would raise there rather than deliver, which is correct.
