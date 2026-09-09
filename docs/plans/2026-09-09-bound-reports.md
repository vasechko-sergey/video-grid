# Bound Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three reports that state a conclusion and record nothing about what they concluded from gain a binding to what they assert, a reader that notices when it no longer holds, and `deliver` stops writing a truncated file under a delivered name.

**Architecture:** Bindings go at the point of *assertion*, not at the file read (design §1): `REVIEW.json` gains the reel's digest, the QC evidence packet gains the clip's, and `MATCH.md` gains a machine-readable `MATCH.json` twin whose recorded decisions are compared against the EDL's current tone pairs — because the EDL is legitimately rewritten and a whole-file digest would fire on the sanctioned rewrite too. `montage status` grows a fifth stage state, `stale`, so a report that no longer describes what is on disk stops reading as `done`. `deliver` encodes to a dotted sibling and `os.replace`s it into position, so a killed encode consumes no version, is invisible to every delivery glob, and leaves the partial as the record that a delivery was interrupted.

**Tech Stack:** Python 3, pytest, ffmpeg via `scripts/lib/proc.py` + `scripts/lib/ffbin.py`, `scripts/lib/provenance.py` for sha256.

**Design:** [docs/specs/2026-09-09-bound-reports-design.md](../specs/2026-09-09-bound-reports-design.md)

## Global Constraints

- **Do NOT install anything.** No `brew`, `pip`, `apt`, `npm`, `uv install`, no `bash setup.sh`. The venv at `.venv/` is already complete. Verification is read-only plus `pytest`.
- **Do NOT use `git checkout --`, `git restore`, `git reset --hard` or `git stash`.** To undo a change to a **committed** file use `git show HEAD:<path> > <path>`; when the file you are about to mutate is **uncommitted**, save your own copy first (`cp <path> <path>.bak`) and restore from that.
- Run Python as `.venv/bin/python`; scripts are modules (`pythonpath = .` in `pytest.ini`), so it is `.venv/bin/python -m scripts.match_grade`, never `python scripts/match_grade.py`.
- **Any mutation battery runs under `PYTHONDONTWRITEBYTECODE=1`.** A one-byte edit can match the previous file's size and mtime-second, and CPython then serves a stale `.pyc`.
- **zsh does not word-split an unquoted variable.** A test selection built in a shell variable arrives as ONE argument and pytest prints `no tests ran`, which reads exactly like a non-discriminating mutation row. Pass selections literally.
- The real run at `/Users/serg/Downloads/untitled folder/` is **read-only**. Never write there.
- Fail-loud contract, imports at top of file, typing on every signature, whole-object asserts in tests — see [docs/coding-standards.md](../coding-standards.md) and [docs/testing-guide.md](../testing-guide.md).
- Commit at the end of every task with a message that says **why**, not only what.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `scripts/lib/matchgrade.py` | + `ToneDecision.to_dict/from_dict`, `MatchReport` contract, pure `tone_drift` | 1 |
| `scripts/match_grade.py` | `write_match` writes `MATCH.json` beside `MATCH.md` | 2 |
| `scripts/montage.py` | `V1_STAGES` match-grade row → `MATCH.json`; the `stale` state; interrupted deliveries | 2, 6 |
| `scripts/lib/review.py` | + `Review.reel_digest` | 3 |
| `scripts/reel_review.py` | `build_review` stamps the digest from disk; CLI refuses a missing reel | 3 |
| `scripts/episode_qc.py` | `pack` records `clip_digest`; `build_qc` refuses a mismatched packet | 4 |
| `scripts/deliver.py` | atomic rename through a dotted partial | 5 |
| `scripts/lib/provenance.py` | the unattested-file detail stops asserting the least-true cause | 6 |
| `tests/integration/test_bound_reports.py` | end-to-end proofs, each with a control | 7 |

---

### Task 1: `MatchReport` — the machine-readable half of MATCH.md

**Why:** `MATCH.md` asserts "8/8 episodes authored a tone pair" and the shipped EDL carried 5 (design §0.1). The assertion is only checkable if it is machine-readable, and `ToneDecision` already *is* the record — it carries index, action, reason, measured profile and the pair. This task serializes it and writes the pure comparison; nothing writes a file yet.

**Files:**
- Modify: `scripts/lib/matchgrade.py` (append after `plan`, which ends at line 150)
- Test: `tests/lib/test_matchgrade.py`

**Interfaces:**
- Consumes: `ToneDecision`, `Profile` (both already in this module).
- Produces, for Tasks 2 and 6:
  - `ToneDecision.to_dict() -> dict` / `ToneDecision.from_dict(d: dict) -> ToneDecision`
  - `MatchReport(target, eps, decisions, edl, bias=(0.0,0.0,0.0), bias_source="", bias_scale=1.0, mood=None)` — frozen dataclass with `to_dict()`, `from_dict(d)`, `from_json(path)`, `write(path)`
  - `tone_drift(decisions: Sequence[ToneDecision], pairs: Sequence[tuple[Profile | None, Profile | None]]) -> list[str]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_matchgrade.py`:

```python
def test_tone_decision_round_trips_through_a_dict():
    d = matchgrade.ToneDecision(2, "author", "authored", measured=(10.0, 100.0, 200.0),
                                tone_src=(10.0, 100.0, 200.0), tone_dst=(20.0, 110.0, 210.0))
    assert matchgrade.ToneDecision.from_dict(d.to_dict()) == d


def test_a_skip_round_trips_with_its_null_pair():
    d = matchgrade.ToneDecision(0, "skip", "flat-source", measured=(10.0, 11.0, 12.0))
    assert d.to_dict()["tone_src"] is None
    assert matchgrade.ToneDecision.from_dict(d.to_dict()) == d


def test_match_report_round_trips_through_a_file(tmp_path):
    r = matchgrade.MatchReport(
        target=(76.0, 108.0, 176.0), eps=4.0, edl=str(tmp_path / "EDL.json"),
        decisions=(matchgrade.ToneDecision(0, "author", "authored", measured=(71.0, 102.0, 166.0),
                                           tone_src=(71.0, 102.0, 166.0),
                                           tone_dst=(76.0, 108.0, 176.0)),),
        bias=(20.0, 0.0, -18.0), bias_source="the nostalgic preset", bias_scale=1.0,
        mood="nostalgic")
    p = tmp_path / "MATCH.json"
    r.write(p)
    assert matchgrade.MatchReport.from_json(p) == r


def test_match_report_refuses_a_non_object():
    with pytest.raises(ValueError, match="expected a MATCH.json object"):
        matchgrade.MatchReport.from_dict([1, 2, 3])


def test_match_report_refuses_an_empty_edl_path():
    with pytest.raises(ValueError, match="MatchReport.edl is empty"):
        matchgrade.MatchReport(target=(1.0, 2.0, 3.0), eps=4.0, decisions=(), edl="")


def test_no_drift_when_every_authored_pair_is_still_in_the_edl():
    d = [matchgrade.ToneDecision(0, "author", "authored", measured=(1.0, 2.0, 3.0),
                                 tone_src=(1.0, 2.0, 3.0), tone_dst=(4.0, 5.0, 6.0)),
         matchgrade.ToneDecision(1, "skip", "within-eps", measured=(1.0, 2.0, 3.0))]
    pairs = [((1.0, 2.0, 3.0), (4.0, 5.0, 6.0)), (None, None)]
    assert matchgrade.tone_drift(d, pairs) == []


def test_a_wiped_pair_is_drift_and_the_reason_names_the_episode():
    d = [matchgrade.ToneDecision(0, "author", "authored", measured=(1.0, 2.0, 3.0),
                                 tone_src=(1.0, 2.0, 3.0), tone_dst=(4.0, 5.0, 6.0))]
    assert matchgrade.tone_drift(d, [(None, None)]) == [
        "episode 0 was authored a tone pair, and the EDL now carries none"]


def test_a_changed_pair_is_drift_and_says_changed_not_wiped():
    d = [matchgrade.ToneDecision(0, "author", "authored", measured=(1.0, 2.0, 3.0),
                                 tone_src=(1.0, 2.0, 3.0), tone_dst=(4.0, 5.0, 6.0))]
    assert matchgrade.tone_drift(d, [((9.0, 9.0, 9.0), (4.0, 5.0, 6.0))]) == [
        "episode 0's tone pair in the EDL is not the one this report authored"]


def test_a_skipped_episode_that_gained_a_pair_is_not_drift():
    # the report asserts nothing about an episode it skipped, so a pair appearing
    # there (a human authoring one by hand) is outside what this report claims
    d = [matchgrade.ToneDecision(0, "skip", "within-eps", measured=(1.0, 2.0, 3.0))]
    assert matchgrade.tone_drift(d, [((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))]) == []


def test_an_episode_count_change_is_drift_before_any_pair_is_compared():
    d = [matchgrade.ToneDecision(0, "author", "authored", measured=(1.0, 2.0, 3.0),
                                 tone_src=(1.0, 2.0, 3.0), tone_dst=(4.0, 5.0, 6.0)),
         matchgrade.ToneDecision(1, "author", "authored", measured=(1.0, 2.0, 3.0),
                                 tone_src=(1.0, 2.0, 3.0), tone_dst=(4.0, 5.0, 6.0))]
    assert matchgrade.tone_drift(d, [((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))]) == [
        "this report describes 2 episodes and the EDL now has 1 — the cut changed"]
```

Add `import pytest` at the top of the file if it is not already there.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_matchgrade.py -x -q`
Expected: FAIL with `AttributeError: module 'scripts.lib.matchgrade' has no attribute 'MatchReport'`

- [ ] **Step 3: Implement**

At the top of `scripts/lib/matchgrade.py`, extend the imports (imports at top, always):

```python
import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from scripts.lib import color
```

Append to the end of `scripts/lib/matchgrade.py`:

```python
def _triple(v, what: str) -> Profile:
    """A JSON list of three numbers back into a Profile, refusing anything else by name."""
    if not (isinstance(v, (list, tuple)) and len(v) == 3
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)):
        raise ValueError(f"{what} must be three numbers (p5, p50, p95), got {v!r}")
    return (float(v[0]), float(v[1]), float(v[2]))


def _opt_triple(v, what: str) -> Profile | None:
    return None if v is None else _triple(v, what)


@dataclass(frozen=True)
class MatchReport:
    """MATCH.json — the conductor's decisions in machine-readable form (design §2).

    MATCH.md said "8/8 episodes authored a tone pair" while the EDL written an hour
    later carried five, and nothing could check the claim because the claim was prose
    (design §0.1). This is the same content MATCH.md renders, in the form a reader can
    compare against the EDL — every other stage in the conveyor writes X.json + X.md,
    and match-grade was one of only two that did not.

    `edl` is the path this conductor wrote back into, stored exactly as write_match
    received it — the same verbatim-not-resolved rule ReelGeometry.edl follows.
    """
    target: Profile
    eps: float
    decisions: tuple[ToneDecision, ...]
    edl: str
    bias: tuple[float, float, float] = (0.0, 0.0, 0.0)
    bias_source: str = ""
    bias_scale: float = 1.0
    mood: str | None = None

    def __post_init__(self) -> None:
        if not (isinstance(self.edl, str) and self.edl):
            raise ValueError("MatchReport.edl is empty — it names the EDL this report's "
                             "decisions were written into, and the freshness check has "
                             "nothing to compare against without it")
        if not all(isinstance(d, ToneDecision) for d in self.decisions):
            raise ValueError("MatchReport.decisions must be ToneDecision objects — build "
                             "them with matchgrade.plan()")

    def to_dict(self) -> dict:
        return {"target": list(self.target), "eps": self.eps, "edl": self.edl,
                "bias": list(self.bias), "bias_source": self.bias_source,
                "bias_scale": self.bias_scale, "mood": self.mood,
                "decisions": [d.to_dict() for d in self.decisions]}

    @classmethod
    def from_dict(cls, d: dict) -> "MatchReport":
        if not isinstance(d, dict):
            raise ValueError(f"MatchReport.from_dict: expected a MATCH.json object, got "
                             f"{type(d).__name__} — produce it with `match_grade build`")
        raw = d.get("decisions")
        if not isinstance(raw, list):
            raise ValueError("MatchReport.decisions must be a JSON list — re-run match-grade")
        return cls(target=_triple(d.get("target"), "MatchReport.target"),
                   eps=float(d.get("eps", MATCH_EPS)),
                   decisions=tuple(ToneDecision.from_dict(x) for x in raw),
                   edl=d.get("edl") or "",
                   bias=_triple(d.get("bias") or [0.0, 0.0, 0.0], "MatchReport.bias"),
                   bias_source=d.get("bias_source") or "",
                   bias_scale=float(d.get("bias_scale", 1.0)),
                   mood=d.get("mood"))

    @classmethod
    def from_json(cls, path: str | Path) -> "MatchReport":
        try:
            return cls.from_dict(json.loads(Path(path).read_text()))
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is corrupt ({e}) — re-run `match_grade build`") from e

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))


def tone_drift(decisions: Sequence[ToneDecision],
               pairs: Sequence[tuple[Profile | None, Profile | None]]) -> list[str]:
    """Which of this report's authored pairs the EDL no longer carries — [] when the
    report still describes the EDL (design §2).

    The instrument is the PAIRS, not a digest of the EDL, and that is deliberate:
    match_grade rewrites the EDL itself and `edit_plan build --pacing` legitimately
    rewrites it again afterwards, so a whole-file digest would fire on the sanctioned
    rewrite exactly as loudly as on the wipe — and a gate that cries wolf gets its
    ceiling raised (design §1, the R2.4 mechanism measured on color_delta_max).

    A `skip` decision asserts nothing about that episode's pair, so a pair appearing
    where one was skipped is not drift. Comparison is exact equality: both sides are
    the same floats round-tripped through json, and a re-conducted episode rewrites
    this report too.

    `pairs` is per-episode (tone_src, tone_dst) read from the EDL as it is NOW —
    supplied by the caller as plain data so this module keeps its no-IO contract and
    montage's inspector need not import the EDL contract (whose from_json refuses a
    tampered file, which must not take the whole status report down with it).
    """
    if len(decisions) != len(pairs):
        return [f"this report describes {len(decisions)} episodes and the EDL now has "
                f"{len(pairs)} — the cut changed"]
    out: list[str] = []
    for d, (src, dst) in zip(decisions, pairs):
        if d.action != "author":
            continue
        if src is None and dst is None:
            out.append(f"episode {d.index} was authored a tone pair, and the EDL now "
                       f"carries none")
        elif (src, dst) != (d.tone_src, d.tone_dst):
            out.append(f"episode {d.index}'s tone pair in the EDL is not the one this "
                       f"report authored")
    return out
```

And add the two methods to `ToneDecision`, directly under its existing fields:

```python
    def to_dict(self) -> dict:
        return {"index": self.index, "action": self.action, "reason": self.reason,
                "measured": list(self.measured),
                "tone_src": None if self.tone_src is None else list(self.tone_src),
                "tone_dst": None if self.tone_dst is None else list(self.tone_dst)}

    @classmethod
    def from_dict(cls, d: dict) -> "ToneDecision":
        if not isinstance(d, dict):
            raise ValueError(f"ToneDecision.from_dict: expected an object, got "
                             f"{type(d).__name__}")
        return cls(index=int(d["index"]), action=str(d["action"]), reason=str(d["reason"]),
                   measured=_triple(d.get("measured"), "ToneDecision.measured"),
                   tone_src=_opt_triple(d.get("tone_src"), "ToneDecision.tone_src"),
                   tone_dst=_opt_triple(d.get("tone_dst"), "ToneDecision.tone_dst"))
```

`_triple` / `_opt_triple` are module-level and defined above `MatchReport`, so they are in scope for `ToneDecision`'s classmethod at call time regardless of where the class sits in the file.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_matchgrade.py -q`
Expected: PASS, no failures.

- [ ] **Step 5: Run the module's other consumers**

Run: `.venv/bin/python -m pytest tests/lib/test_match_grade.py tests/integration/test_matchgrade.py -q`
Expected: PASS — this task adds only new names; nothing existing changed.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/matchgrade.py tests/lib/test_matchgrade.py
git commit -m "$(cat <<'MSG'
feat(matchgrade): make the conductor's decisions checkable, not prose

MATCH.md claimed 8/8 authored tone pairs against an EDL carrying 5 and
nothing could check it, because the claim was a sentence. ToneDecision
was already the whole record; this serializes it into a MatchReport and
adds the pure comparison a reader needs.

tone_drift compares the authored PAIRS rather than digesting the EDL:
match_grade rewrites that file itself and edit_plan --pacing rewrites it
again, so a whole-file digest would fire on the sanctioned rewrite as
loudly as on the wipe, and a gate that cries wolf gets its ceiling
raised. It takes plain data so this module keeps its no-IO contract.
MSG
)"
```

---

### Task 2: `write_match` writes MATCH.json, and the stage keys on it

**Why:** MATCH.md is one of only two run artifacts written as markdown with no JSON twin, and its stage is required (design §2). This puts the twin on disk and moves the `montage status` stage row onto it, matching every other stage.

**Files:**
- Modify: `scripts/match_grade.py` (`write_match`, ~line 142–174)
- Modify: `scripts/montage.py` (the `match-grade` `Stage` row, ~line 70)
- Test: `tests/lib/test_match_grade.py`, `tests/lib/test_montage.py`

**Interfaces:**
- Consumes: `matchgrade.MatchReport`, `matchgrade.ToneDecision` (Task 1).
- Produces, for Tasks 6 and 7: `MATCH.json` written beside `MATCH.md` in `Path(geo.edl).parent`; `write_match`'s status dict gains `"json": <path>`.

**Known ripple:** `test_write_match_rewrites_the_edl_and_writes_md` asserts the status dict as a whole object (this project's convention). Adding the `"json"` key makes it fail; update that expected dict in the same commit — do NOT weaken the assert to a subset.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_match_grade.py`:

```python
def test_write_match_writes_a_json_twin_carrying_every_decision(tmp_path, monkeypatch):
    monkeypatch.setattr(match_grade, "measure_crop",
                        lambda md, src, route, **k: (10.0, 90.0, 150.0) if "d.mp4" in src
                        else (40.0, 130.0, 240.0))
    ep0, ep1 = _ep("d.mp4"), _ep("b.mp4")
    geometry_path, edl_path = _write_geometry(tmp_path, ep0, ep1)
    status = match_grade.write_match(geometry_path)
    assert status["json"] == str(tmp_path / "MATCH.json")
    target = (25.0, 110.0, 195.0)
    report = matchgrade.MatchReport.from_json(tmp_path / "MATCH.json")
    assert report == matchgrade.MatchReport(
        target=target, eps=matchgrade.MATCH_EPS, edl=edl_path,
        decisions=(
            matchgrade.ToneDecision(0, "author", "authored", measured=(10.0, 90.0, 150.0),
                                    tone_src=(10.0, 90.0, 150.0), tone_dst=target),
            matchgrade.ToneDecision(1, "author", "authored", measured=(40.0, 130.0, 240.0),
                                    tone_src=(40.0, 130.0, 240.0), tone_dst=target)),
        bias=(0.0, 0.0, 0.0), bias_source="", bias_scale=1.0, mood=None)


def test_the_json_twin_names_the_edl_verbatim_as_geometry_gave_it(tmp_path, monkeypatch):
    """geo.edl is used verbatim, never resolve()d (write_match's own rule) — the twin
    must record the same string, or the freshness reader looks at a different file."""
    monkeypatch.setattr(match_grade, "measure_crop", lambda md, src, route, **k: (10.0, 90.0, 150.0))
    geometry_path, edl_path = _write_geometry(tmp_path, _ep("d.mp4"))
    match_grade.write_match(geometry_path)
    assert matchgrade.MatchReport.from_json(tmp_path / "MATCH.json").edl == edl_path


def test_the_json_twin_records_a_skip_with_its_reason(tmp_path, monkeypatch):
    # a flat source cannot be a tone_src, so the conductor skips it — and a reader must
    # be able to tell that skip from a pair that was wiped after the fact
    monkeypatch.setattr(match_grade, "measure_crop",
                        lambda md, src, route, **k: (10.0, 11.0, 12.0) if "d.mp4" in src
                        else (40.0, 130.0, 240.0))
    geometry_path, _ = _write_geometry(tmp_path, _ep("d.mp4"), _ep("b.mp4"))
    match_grade.write_match(geometry_path)
    report = matchgrade.MatchReport.from_json(tmp_path / "MATCH.json")
    assert (report.decisions[0].action, report.decisions[0].reason) == ("skip", "flat-source")
    assert report.decisions[0].tone_src is None


def test_the_json_twin_carries_the_mood_displacement(tmp_path, monkeypatch):
    monkeypatch.setattr(match_grade, "measure_crop", lambda md, src, route, **k: (10.0, 90.0, 150.0))
    geometry_path, _ = _write_geometry(tmp_path, _ep("d.mp4"))
    spec = tmp_path / "SPEC.json"
    spec.write_text(json.dumps({"idea": "a calm ride", "mood": "nostalgic", "length_s": 30.0}))
    match_grade.write_match(geometry_path, spec=str(spec))
    report = matchgrade.MatchReport.from_json(tmp_path / "MATCH.json")
    assert (report.mood, report.bias_source) == ("nostalgic", "the nostalgic preset")
    assert report.bias == moodpreset.resolve("nostalgic").tone_bias
```

Add `from scripts.lib import matchgrade, moodpreset` to the file's imports if either name is missing.

Append to `tests/lib/test_montage.py`:

```python
def test_the_match_grade_stage_keys_on_the_json_not_the_markdown():
    """Every other stage's presence marker is its X.json; match-grade was the
    exception, and MATCH.md alone carries nothing a reader can check."""
    row = next(s for s in montage.V1_STAGES if s.key == "match-grade")
    assert row.artifact == "MATCH.json"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_match_grade.py tests/lib/test_montage.py -q`
Expected: FAIL — `KeyError: 'json'` on the new match_grade tests and `assert 'MATCH.md' == 'MATCH.json'` on the montage one.

- [ ] **Step 3: Implement**

In `scripts/match_grade.py`, replace the body of `write_match` from the `write_edl` line to the `return` with:

```python
    write_edl(out, geo.edl)       # re-stamp: match_grade is a legitimate tool, and its
                                  # output is the tool's output (design §4)
    md_path = Path(geo.edl).parent / "MATCH.md"
    md_path.write_text(_report_md([e.source for e in edl.episodes], target, decisions, eps,
                                  bias=bias, bias_source=bias_source,
                                  mood=preset.name if preset is not None else None, k=k))
    # The machine-readable twin (design 2026-09-09 §2). MATCH.md's claim — "8/8
    # episodes authored a tone pair" — was prose, and the EDL written an hour later
    # carried five with nothing able to notice. The decisions are what the report
    # ASSERTS, so they are what a reader compares against the EDL; `geo.edl` is
    # recorded verbatim, exactly as it was used, so the reader opens the same file
    # this wrote back into.
    json_path = Path(geo.edl).parent / "MATCH.json"
    matchgrade.MatchReport(
        target=target, eps=eps, decisions=tuple(decisions), edl=geo.edl,
        bias=bias, bias_source=bias_source, bias_scale=k,
        mood=preset.name if preset is not None else None).write(json_path)
    skipped = Counter(d.reason for d in decisions if d.action == "skip")
    return {"status": "written", "edl": geo.edl, "md": str(md_path),
            "json": str(json_path),
            "target": list(target), "eps": eps,
            "mood": preset.name if preset is not None else None,
            "bias_source": bias_source, "bias_scale": k,
            "authored": sum(1 for d in decisions if d.action == "author"),
            "skipped": dict(skipped)}
```

Also extend `write_match`'s docstring's first line to say it writes the twin:

```python
    """Read GEOMETRY.json → the EDL it names → conduct → write the enriched EDL BACK IN
    PLACE (the stage enriches the EDL a human then reviews) + a sibling MATCH.md and
    MATCH.json. One measure pass (inside conduct); the decisions carry the measured
    profiles the report needs, and MATCH.json carries the decisions themselves so the
    report's claim can be checked against the EDL later (design 2026-09-09 §2).
```

In `scripts/montage.py`, change the `match-grade` stage row's artifact:

```python
    Stage("match-grade", "MATCH.json", "required",
          "match-grade SKILL -> match_grade build --geometry (measures each episode's "
          "own crop; run AFTER episodes-geometry, before the render)", None, "reel"),
```

- [ ] **Step 4: Update the whole-object status assert**

In `tests/lib/test_match_grade.py`, `test_write_match_rewrites_the_edl_and_writes_md`'s expected dict gains the new key:

```python
    assert status == {"status": "written", "edl": edl_path, "md": str(tmp_path / "MATCH.md"),
                      "json": str(tmp_path / "MATCH.json"),
                      "target": list(target), "eps": matchgrade.MATCH_EPS,
                      "mood": None, "bias_source": "", "bias_scale": 1.0,  # no --spec: the plain median
                      "authored": 2, "skipped": {}}
```

Search the file for any other whole-object assert on `write_match`'s return and update it the same way:

Run: `grep -n 'status == {' tests/lib/test_match_grade.py`

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_match_grade.py tests/lib/test_montage.py tests/lib/test_matchgrade.py -q`
Expected: PASS.

- [ ] **Step 6: Prove MATCH.md did not move**

The report a human reads must be byte-identical — `_report_md`'s signature and output are untouched by this task.

Run: `.venv/bin/python -m pytest tests/lib/test_match_grade.py -q -k "md"`
Expected: PASS, including the existing byte-exact `md ==` assertion in `test_write_match_rewrites_the_edl_and_writes_md`.

- [ ] **Step 7: Run every consumer of the stage table**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py tests/integration/test_matchgrade.py tests/integration/test_verify.py -q`
Expected: PASS. If a test writes a fake `MATCH.md` to make the stage read `done`, it must now write `MATCH.json` — report which tests you changed and why in your task report.

- [ ] **Step 8: Commit**

```bash
git add scripts/match_grade.py scripts/montage.py tests/lib/test_match_grade.py tests/lib/test_montage.py
git commit -m "$(cat <<'MSG'
feat(match_grade): write the twin the required stage never had

MATCH.md and SHEETS.md were the only two run artifacts written as
markdown with no JSON beside them, and match-grade is a required stage
whose router row keyed on that markdown. MATCH.json now carries the
decisions the report renders, so the claim can be checked against the
EDL, and the stage row moves onto it like every other stage.

MATCH.md itself is byte-identical: _report_md is untouched.
MSG
)"
```

---

### Task 3: `Review.reel_digest` — the review names bytes, not a path

**Why:** `REVIEW.json` recorded `{"reel": ".../out/REEL_v1.mp4"}` and approved a reel that no longer exists — the file at that path is dated a day and a half after the review (design §0.2). A path is not an identity.

**Files:**
- Modify: `scripts/lib/review.py` (`Review` dataclass, `__post_init__`, `to_dict`, `from_dict`, `to_markdown`)
- Modify: `scripts/reel_review.py` (`build_review`, `main`)
- Test: `tests/lib/test_review.py`, `tests/test_reel_review.py`

**Interfaces:**
- Produces, for Tasks 6 and 7: `Review.reel_digest: str = ""` — the sha256 of the reviewed file, stamped by `build_review` from disk. `""` means unbound.

**A deliberate split, not a softening.** `build_review` stamps when the file exists and leaves `""` when it does not; the CLI `main()` refuses a `--reel` that names no file. The library function stays permissive because `Review` is also the typed sink for a hand-authored review and 15 existing unit tests exercise its pure validation against a path with no file behind it; the refusal lands on the one path a real run takes. An empty digest is reported as *unbound* by Task 6, never as fresh.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_review.py`:

```python
def test_reel_digest_defaults_to_empty_and_round_trips(tmp_path):
    r = Review(reel="out/REEL_v1.mp4", reel_digest="a" * 64)
    assert Review(reel="out/REEL_v1.mp4").reel_digest == ""
    assert Review.from_dict(r.to_dict()) == r


def test_reel_digest_must_be_a_string():
    with pytest.raises(ValueError, match="Review.reel_digest must be a string"):
        Review(reel="out/REEL_v1.mp4", reel_digest=12345)


def test_a_pre_slice_review_loads_as_unbound_not_as_a_failure():
    """An artifact written before this field existed must still load: the honest
    reading is 'nothing binds this review', not 'this file is corrupt'."""
    assert Review.from_dict({"reel": "out/REEL_v1.mp4", "findings": []}).reel_digest == ""


def test_to_markdown_names_the_digest_when_it_has_one():
    md = Review(reel="out/REEL_v1.mp4", reel_digest="abc123def456" + "0" * 52,
                summary="clean").to_markdown()
    assert "`abc123def456…`" in md


def test_to_markdown_says_unbound_when_it_has_none():
    md = Review(reel="out/REEL_v1.mp4", summary="clean").to_markdown()
    assert "not bound to the file's bytes" in md
```

Append to `tests/test_reel_review.py`:

```python
def test_build_review_stamps_the_digest_from_disk(tmp_path):
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"delivered-bytes")
    r = build_review(RAW, str(reel), summary="ok")
    assert r.reel_digest == provenance.digest_file(reel)


def test_build_review_ignores_a_digest_nobody_computed_from_disk(tmp_path):
    """The episode_qc idiom verbatim: the digest is computed HERE, so a reviewer
    cannot hand one in. There is no parameter to pass one through."""
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"delivered-bytes")
    with pytest.raises(TypeError):
        build_review(RAW, str(reel), reel_digest="deadbeef")


def test_build_review_leaves_the_digest_empty_when_the_file_is_absent():
    assert build_review(RAW, "out/REEL_v1.mp4").reel_digest == ""


def test_the_cli_refuses_a_reel_that_names_no_file(tmp_path, monkeypatch, capsys):
    findings = tmp_path / "f.json"
    findings.write_text(json.dumps(RAW))
    monkeypatch.setattr(sys, "argv",
                        ["reel_review", "build", "--findings", str(findings),
                         "--reel", str(tmp_path / "nope.mp4"), "--out-dir", str(tmp_path)])
    with pytest.raises(ValueError, match="names no file"):
        reel_review.main()
```

Add whatever of `import json`, `import sys`, `import pytest`, `from scripts import reel_review`, `from scripts.lib import provenance` the file is missing.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_review.py tests/test_reel_review.py -q`
Expected: FAIL — `TypeError: Review.__init__() got an unexpected keyword argument 'reel_digest'`.

- [ ] **Step 3: Implement the contract**

In `scripts/lib/review.py`, add the field under `reel`:

```python
    reel: str                  # path to the reviewed cut (out/REEL_v{n}.mp4); non-empty (gate)
    reel_digest: str = ""      # sha256 of that file, stamped from disk by build_review;
                               # "" means nothing binds this review to any bytes
```

Note the field ordering: `reel_digest` must come after `findings`/`summary`/… only if it is given a default, which it is — place it after `reviewer` so the existing positional call sites (`Review(reel=..., findings=...)`) keep working, and keep the comment above beside `reel` as a cross-reference. Concretely, put the field last:

```python
    reviewer: str = ""         # free note — which agent/model reviewed
    reel_digest: str = ""      # sha256 of the reviewed file, stamped from disk by
                               # build_review — never from the reviewer's claim (the
                               # episode_qc.clip_digest idiom). "" means unbound: a
                               # review written before this field existed, or one whose
                               # reel was not on disk.
```

Extend the string-type loop in `__post_init__`:

```python
        for name in ("summary", "spec_ref", "platform", "reviewer", "reel_digest"):
```

`to_dict` gains the key:

```python
        return {"reel": self.reel, "reel_digest": self.reel_digest, "verdict": self.verdict,
                "findings": [f.to_dict() for f in self.findings], "summary": self.summary,
                "spec_ref": self.spec_ref, "platform": self.platform, "reviewer": self.reviewer}
```

`from_dict` reads it through the existing `opt` helper:

```python
        return cls(reel=d.get("reel"), findings=findings, summary=opt("summary", ""),
                   spec_ref=opt("spec_ref", ""), platform=opt("platform", ""),
                   reviewer=opt("reviewer", ""), reel_digest=opt("reel_digest", ""))
```

`to_markdown`'s reel line names what binds it:

```python
        lines = [head, "", f"**Reel:** `{self.reel}`"]
        lines.append(f"**Bound to:** `{self.reel_digest[:12]}…`" if self.reel_digest
                     else "**Bound to:** _nothing_ — this review is not bound to the "
                          "file's bytes, so nothing can tell whether the reel it judged "
                          "is the reel that shipped")
        lines.append("")
```

- [ ] **Step 4: Implement the stamping**

In `scripts/reel_review.py`, add `from pathlib import Path` (already present) and `from scripts.lib import provenance` to the imports, then stamp at the end of `build_review`:

```python
    # The digest is computed HERE from the file on disk, never taken from the reviewer's
    # findings file — episode_qc.build_qc's rule verbatim, and for the same reason: it is
    # what turns "a reel was reviewed" into "THIS reel was reviewed" (design 2026-09-09
    # §3). An absent file leaves it empty rather than raising: Review is also the typed
    # sink for a hand-authored review, and an unbound review is reported as unbound.
    # The one path a real run takes — the CLI — refuses an absent reel outright.
    digest = provenance.digest_file(reel) if Path(reel).exists() else ""
    return Review(reel=reel, findings=tuple(findings), summary=summary, spec_ref=spec_ref,
                  platform=platform, reviewer=reviewer, reel_digest=digest)
```

And in `main()`, before `build_review` is called:

```python
    if not Path(a.reel).exists():
        raise ValueError(
            f"--reel {a.reel} names no file, so this review would be bound to nothing. "
            f"Point it at the delivered reel (the deliveries bucket's newest "
            f"REEL_v{{n}}.mp4); run `montage status` if you are not sure which that is")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_review.py tests/test_reel_review.py -q`
Expected: PASS.

- [ ] **Step 6: Run every Review consumer**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py tests/integration/test_verify.py -q -k "review or Review"`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/review.py scripts/reel_review.py tests/lib/test_review.py tests/test_reel_review.py
git commit -m "$(cat <<'MSG'
feat(review): bind the review to the reel's bytes, not to a path

REVIEW.json recorded a path and approved a reel that no longer exists:
the file at that path is dated a day and a half after the review that
approved it. A path is not an identity.

reel_digest is stamped from the file on disk by build_review, never from
the reviewer's claim — the episode_qc.clip_digest rule verbatim, since
that is the one binding that held all week. It defaults to empty so a
review written before this field loads as unbound rather than corrupt,
and to_markdown says which of the two it is. The CLI, the only path a
real run takes, refuses a --reel that names no file.
MSG
)"
```

---

### Task 4: the QC evidence packet binds to the clip it was packed from

**Why:** `episode_qc build` stamps `clip_digest` from disk and refuses a stale verdict — that binding held all week. `episode_qc pack`, the other half of the same stage, records nothing, so a re-render between packing and judging leaves the judge reading one set of pixels while its verdict is stamped against another. The run hit exactly this: a stale packet went to three judges and only a judge's own blocking verdict caught it (design §0.3, R10.9).

This one is a **gate**, not a report, and the reason is not severity: a stale evidence packet makes a verdict *claim to bind* pixels the judge never saw. An assertion that is false is worse than an absent one.

**Files:**
- Modify: `scripts/episode_qc.py` (`_evidence`, `build_qc`)
- Test: `tests/lib/test_episode_qc.py`, `tests/integration/test_episode_qc.py`

**Interfaces:**
- Produces: `evidence.json` gains `"clip_digest": "<sha256>"`. `build_qc` raises when a packet's recorded digest is missing or does not match the clip on disk, collected into the existing one-pass complaint list.

**Deliberate behaviour change:** a packet written before this slice carries no digest and is refused with a named remedy (re-pack, then re-judge). That is the point — an unbound packet is what failed — and re-packing eight episodes costs seconds (the measurement behind the existing `pack --only` won't-do row). Say so in the message rather than letting it read as corruption.

- [ ] **Step 1: Write the failing unit tests**

Append to `tests/lib/test_episode_qc.py`:

```python
def test_build_qc_refuses_a_packet_whose_clip_has_been_re_rendered(tmp_path):
    clip = tmp_path / "ep0.mp4"
    clip.write_bytes(b"first-render")
    ep = _ep(str(clip), tmp_path)                     # the file's existing helper
    p = tmp_path / "EPISODES.json"
    ReelManifest(episodes=[ep], target_dur=3.0, changelog="x").write(p)
    packets = tmp_path / "qc"
    (packets / "ep0").mkdir(parents=True)
    (packets / "ep0" / "evidence.json").write_text(json.dumps(
        {"idx": 0, "clip": str(clip), "clip_digest": provenance.digest_file(clip)}))
    (packets / "ep0" / "findings.json").write_text(json.dumps(
        {"summary": "ok", "reviewer": "t", "findings": []}))
    clip.write_bytes(b"second-render")                # re-rendered after packing
    with pytest.raises(ValueError, match="was packed from a different render"):
        episode_qc.build_qc(str(p), str(packets))


def test_build_qc_refuses_a_packet_that_records_no_digest_at_all(tmp_path):
    clip = tmp_path / "ep0.mp4"
    clip.write_bytes(b"render")
    ep = _ep(str(clip), tmp_path)
    p = tmp_path / "EPISODES.json"
    ReelManifest(episodes=[ep], target_dur=3.0, changelog="x").write(p)
    packets = tmp_path / "qc"
    (packets / "ep0").mkdir(parents=True)
    (packets / "ep0" / "evidence.json").write_text(json.dumps({"idx": 0, "clip": str(clip)}))
    (packets / "ep0" / "findings.json").write_text(json.dumps(
        {"summary": "ok", "reviewer": "t", "findings": []}))
    with pytest.raises(ValueError, match="records no clip digest"):
        episode_qc.build_qc(str(p), str(packets))


def test_a_packet_digest_complaint_joins_the_others_in_one_raise(tmp_path):
    """One pass names every complaint (the build_qc rule since 2026-09-08): a digest
    mismatch on ep0 must not hide a malformed finding on ep1."""
    clips = []
    for i in range(2):
        c = tmp_path / f"ep{i}.mp4"
        c.write_bytes(f"render{i}".encode())
        clips.append(c)
    eps = [_ep(str(c), tmp_path, name=f"ep{i}") for i, c in enumerate(clips)]
    p = tmp_path / "EPISODES.json"
    ReelManifest(episodes=eps, target_dur=3.0, changelog="x").write(p)
    packets = tmp_path / "qc"
    for i, c in enumerate(clips):
        (packets / f"ep{i}").mkdir(parents=True)
        (packets / f"ep{i}" / "evidence.json").write_text(json.dumps(
            {"idx": i, "clip": str(c), "clip_digest": provenance.digest_file(c)}))
    (packets / "ep0" / "findings.json").write_text(json.dumps(
        {"summary": "ok", "reviewer": "t", "findings": []}))
    (packets / "ep1" / "findings.json").write_text(json.dumps(
        {"summary": "ok", "reviewer": "t", "findings": [{"axis": "nope"}]}))
    clips[0].write_bytes(b"re-rendered")
    with pytest.raises(ValueError) as e:
        episode_qc.build_qc(str(p), str(packets))
    assert "ep0" in str(e.value) and "ep1 finding 0" in str(e.value)
```

`_ep` is whatever minimal `ReelEpisode` helper `tests/lib/test_episode_qc.py` already uses; if the file has none, write one that produces a `ReelEpisode` with `clip`, `path` and a manifest, mirroring how the file's existing `build_qc` tests build their manifests. Report in your task report which you did.

- [ ] **Step 2: Write the failing integration test**

Append to `tests/integration/test_episode_qc.py`:

```python
@pytest.mark.integration
def test_the_packet_records_the_digest_of_the_clip_it_decoded(tmp_path, sample_clip):
    p, rm = _episodes_json(tmp_path, sample_clip)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    ev = json.loads((tmp_path / "qc" / "ep0" / "evidence.json").read_text())
    assert ev["clip_digest"] == provenance.digest_file(rm.episodes[0].clip)


@pytest.mark.integration
def test_a_re_rendered_clip_invalidates_its_own_packet(tmp_path, sample_clip):
    """The gate the run needed: pack, re-render, and the judge's verdict must not be
    stamped against pixels nobody judged."""
    p, rm = _episodes_json(tmp_path, sample_clip)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    for i in range(2):
        _judge(str(tmp_path / "qc"), i)
    # control: nothing moved, the gate is silent
    assert episode_qc.build_qc(str(p), str(tmp_path / "qc")).ok
    Path(rm.episodes[0].clip).write_bytes(b"a different render entirely")
    with pytest.raises(ValueError, match="was packed from a different render"):
        episode_qc.build_qc(str(p), str(tmp_path / "qc"))
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_episode_qc.py -q -k "digest or one_raise"`
Expected: FAIL — `DID NOT RAISE` on all three, since nothing reads a packet digest yet.

Run: `.venv/bin/python -m pytest tests/integration/test_episode_qc.py -q -k "decoded or re_rendered" -m integration`
Expected: FAIL — `KeyError: 'clip_digest'`.

- [ ] **Step 4: Implement `pack`'s half**

In `scripts/episode_qc.py`, inside `_evidence`, add the key to the `out` dict right after `"clip": ep.clip`:

```python
    out: dict = {
        "idx": i, "clip": ep.clip,
        # What these pixels ARE (design 2026-09-09 §4). The verdict has carried a
        # clip digest since 2026-08-08 and the packet never did, so a re-render
        # between pack and judge left the judge reading one render while its verdict
        # was stamped against another — which is what happened on the real run, and
        # only a judge's own blocking verdict caught it.
        "clip_digest": provenance.digest_file(ep.clip),
        "intent": {k: m.get(k) for k in ("composition", "grid", "hero", "target_dur",
                                         "layout", "pan", "stabilize", "canvas")},
```

- [ ] **Step 5: Implement `build_qc`'s half**

In `build_qc`, add a packet-digest reader beside `_raw`, then compare before the verdict is built. Add this helper next to `_raw`:

```python
def _packed_digest(packets: str, i: int) -> str:
    """The clip digest `pack` recorded in this episode's evidence.json.

    An absent file or an absent key both return "" — reported by the caller as
    'records no clip digest', which is the true statement about a packet written
    before this binding existed. read_text's own OSError is not caught here, exactly
    as _raw does not catch its own: build_qc's call site collects it with every other
    complaint rather than letting one packet's filesystem trouble abort the rest."""
    p = Path(packets) / f"ep{i}" / "evidence.json"
    if not p.exists():
        return ""
    try:
        d = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{p} is not valid JSON ({e}) — re-run `episode_qc pack`") from e
    return d.get("clip_digest") or "" if isinstance(d, dict) else ""
```

Then, inside `build_qc`'s per-episode loop, after the `findings` list is validated (`if len(problems) != before: continue`) and before the `EpisodeVerdict` is constructed:

```python
        try:
            actual = provenance.digest_file(ep.clip)
            packed = _packed_digest(packets, i)
        except (ValueError, OSError) as e:
            problems.append(f"  ep{i}: {e}")
            continue
        if not packed:
            problems.append(
                f"  ep{i}: its evidence packet records no clip digest, so nothing says "
                f"which render the judge looked at. A packet written before this binding "
                f"existed reads exactly like a stale one — re-run `episode_qc pack`, then "
                f"re-dispatch the judge for this episode")
            continue
        if packed != actual:
            problems.append(
                f"  ep{i}: its evidence packet was packed from a different render than "
                f"the clip on disk (packet {packed[:12]}…, clip {actual[:12]}…). The "
                f"judge read pixels that no longer exist, so its verdict cannot be "
                f"stamped against this render — re-run `episode_qc pack`, then re-dispatch "
                f"the judge for this episode")
            continue
        try:
            verdicts.append(EpisodeVerdict(
                idx=i, clip=ep.clip, clip_digest=actual,
                findings=tuple(built),
                summary=raw.get("summary") or "", reviewer=raw.get("reviewer") or ""))
        except (ValueError, OSError) as e:
            problems.append(f"  ep{i}: {e}")
```

Note the `EpisodeVerdict` now uses the `actual` computed above rather than calling `provenance.digest_file(ep.clip)` a second time — one hash per episode, not two, and the verdict is provably stamped with the same value the gate compared.

Extend `build_qc`'s docstring with a paragraph naming the second binding:

```python
    Two bindings, not one (design 2026-09-09 §4). The verdict's digest says WHICH
    render was judged; the packet's says which render the judge LOOKED AT. They must
    agree, or the verdict claims to bind pixels nobody saw — and a false binding is
    worse than an absent one, which is why this refuses rather than reports.
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_episode_qc.py -q`
Expected: PASS.

Run: `.venv/bin/python -m pytest tests/integration/test_episode_qc.py -q -m integration`
Expected: PASS. Existing tests in this file that build packets by hand (rather than through `pack`) will now be refused for recording no digest — fix each by writing an `evidence.json` carrying the real digest, and name them in your task report.

- [ ] **Step 7: Commit**

```bash
git add scripts/episode_qc.py tests/lib/test_episode_qc.py tests/integration/test_episode_qc.py
git commit -m "$(cat <<'MSG'
feat(episode_qc): bind the evidence packet, not only the verdict

The verdict has carried a clip digest since 2026-08-08 and refuses a
stale one; the packet the judge actually reads carried nothing. So a
re-render between pack and judge left the judge reading one render
while its verdict was stamped against another — which is what happened
on the real run, and only a judge's own blocking verdict caught it.

This refuses rather than reports, and the difference is not severity:
an unbound packet makes the verdict CLAIM to bind pixels the judge
never saw, and a false binding is worse than an absent one. A packet
predating this binding is refused too, with the remedy named — re-pack
costs seconds for eight episodes.
MSG
)"
```

---

### Task 5: `deliver` encodes to a dotted sibling and renames it into place

**Why:** ffmpeg is handed the delivered path directly, so a killed encode leaves a truncated file under a delivered name, permanently consuming a version number and reading as `deliver: done` (design §0.4, R5.3). The row asks for atomicity **or** a record; a dotted partial plus `os.replace` gives both, with no new state to go stale.

**Files:**
- Modify: `scripts/lib/runlayout.py` (the naming convention)
- Modify: `scripts/deliver.py` (the two `proc.run` branches + the rename)
- Test: `tests/lib/test_runlayout.py`, `tests/lib/test_deliver.py`

**Interfaces:**
- Produces, for Task 6: `runlayout.PARTIAL_GLOB = ".REEL_v*.part.*"` and `runlayout.partial_path(out_dir, n, container) -> Path`.

**Why the name lives in `runlayout` and not in `deliver`:** `runlayout` owns where things live in a run, `montage` already imports it, and it is light (shutil + dataclasses + pathlib). Putting the convention in `deliver` would make the constantly-called `montage status` import `assembly`, `look`, `lookcheck` and `titles` to learn one glob.

**Three details are load-bearing** and each has its own test below:
1. **Same directory** as the delivery, so the rename is same-filesystem and therefore atomic. `scratch_dir` cannot be used — a caller may point it at another mount.
2. **A leading dot**, which takes the partial out of all three existing globs: `_next_version`'s `REEL_v*.{container}`, `montage._deliveries`' `REEL_v*`, and `Stage("deliver", "REEL_v*.*")`.
3. **The container extension last**, because ffmpeg picks its muxer from the output filename — `.REEL_v3.part` would fail to guess one.

The precedent for the write-then-`os.replace` shape is `scripts/lib/intake_cache.store`, which commits `clip.json` the same way for the same reason.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_runlayout.py`:

```python
def test_the_partial_ends_in_the_container_so_ffmpeg_can_pick_a_muxer(tmp_path):
    assert runlayout.partial_path(str(tmp_path), 3, "mp4").name.endswith(".mp4")
    assert runlayout.partial_path(str(tmp_path), 3, "mov").name == ".REEL_v3.part.mov"


def test_a_partial_is_invisible_to_every_delivery_glob(tmp_path):
    (tmp_path / "REEL_v1.mp4").write_text("x")
    (tmp_path / ".REEL_v2.part.mp4").write_text("half")
    assert sorted(p.name for p in tmp_path.glob("REEL_v*")) == ["REEL_v1.mp4"]
    assert sorted(p.name for p in tmp_path.glob("REEL_v*.*")) == ["REEL_v1.mp4"]
    assert sorted(p.name for p in tmp_path.glob(runlayout.PARTIAL_GLOB)) == [".REEL_v2.part.mp4"]
```

Append to `tests/lib/test_deliver.py`:

```python
def test_the_partial_does_not_raise_the_version_floor(tmp_path):
    """_next_version's glob must skip it, or a killed encode burns a version."""
    (tmp_path / "REEL_v1.mp4").write_text("x")
    (tmp_path / ".REEL_v2.part.mp4").write_text("half")
    assert deliver._next_version(str(tmp_path), "mp4") == 2


def test_ffmpeg_is_handed_a_partial_never_the_delivered_name(tmp_path, monkeypatch):
    calls = []
    _fake_encode(monkeypatch, calls)
    master, rep = _bound(tmp_path)
    out = deliver.deliver(master, REEL_H264, str(tmp_path), "first cut", rep,
                          scratch_dir=str(tmp_path / "scratch"))
    assert calls[0][-1] == str(tmp_path / ".REEL_v1.part.mp4")
    assert out == str(tmp_path / "REEL_v1.mp4")
    assert not (tmp_path / ".REEL_v1.part.mp4").exists()      # renamed, not copied


def test_the_partial_sits_beside_the_delivery_not_in_scratch(tmp_path, monkeypatch):
    """Same directory, so os.replace is a same-filesystem rename and therefore atomic;
    scratch_dir may be on another mount."""
    calls = []
    _fake_encode(monkeypatch, calls)
    master, rep = _bound(tmp_path)
    out_dir = tmp_path / "deliveries"
    deliver.deliver(master, REEL_H264, str(out_dir), "x", rep,
                    scratch_dir=str(tmp_path / "scratch"))
    assert Path(calls[0][-1]).parent == out_dir


def test_a_killed_encode_leaves_a_partial_and_no_delivery(tmp_path, monkeypatch):
    """The whole point: the process dies inside ffmpeg. Nothing is renamed, so no file
    bears a delivered name, no version is logged, and the partial is the record."""
    real_run = deliver.proc.run
    def run(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            return real_run(cmd, *a, **k)
        Path(cmd[-1]).write_bytes(b"half-an-encode")   # ffmpeg wrote some bytes...
        raise RuntimeError("killed")                    # ...then the process died
    monkeypatch.setattr(deliver.proc, "run", run)
    master, rep = _bound(tmp_path)
    with pytest.raises(RuntimeError, match="killed"):
        deliver.deliver(master, REEL_H264, str(tmp_path), "x", rep,
                        scratch_dir=str(tmp_path / "scratch"))
    assert not (tmp_path / "REEL_v1.mp4").exists()
    assert (tmp_path / ".REEL_v1.part.mp4").read_bytes() == b"half-an-encode"
    assert not (tmp_path / "VERSIONS.md").exists()
    assert not (tmp_path / "REEL_v1.attest.json").exists()


def test_the_next_delivery_after_a_kill_reuses_the_version_and_clears_the_partial(
        tmp_path, monkeypatch):
    (tmp_path / ".REEL_v1.part.mp4").write_bytes(b"half-an-encode")
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    out = deliver.deliver(master, REEL_H264, str(tmp_path), "retry", rep,
                          scratch_dir=str(tmp_path / "scratch"))
    assert out.endswith("REEL_v1.mp4")                 # the killed version is retried
    assert not (tmp_path / ".REEL_v1.part.mp4").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_runlayout.py tests/lib/test_deliver.py -q -k "partial or killed"`
Expected: FAIL — `AttributeError: module 'scripts.lib.runlayout' has no attribute 'partial_path'` on the runlayout tests, and `assert '.../REEL_v1.mp4' == '.../.REEL_v1.part.mp4'` on the deliver ones.

Confirm the selector actually matched tests — a `-k` that matches nothing prints `no tests ran`, which reads exactly like a passing run.

- [ ] **Step 3: Implement**

Add to `scripts/lib/runlayout.py`:

```python
PARTIAL_GLOB = ".REEL_v*.part.*"   # what montage looks for to report an interrupted delivery


def partial_path(out_dir: str, n: int, container: str) -> Path:
    """Where the encode lands before it is a delivery (design 2026-09-09 §5).

    Three details are load-bearing. It sits in `out_dir`, not scratch_dir, so the
    os.replace below is a same-filesystem rename and therefore atomic — a caller may
    point scratch_dir at another mount. It starts with a DOT, which takes it out of
    all three globs that look for deliveries (_next_version's REEL_v*.{container},
    montage._deliveries' REEL_v*, and the router's Stage("deliver", "REEL_v*.*")), so
    a killed encode consumes no version and does not make the stage read done. And the
    container extension comes LAST, because ffmpeg picks its muxer from the output
    filename — `.REEL_v3.part` would fail to guess one.

    A leftover partial is not litter: it is the record that a delivery was interrupted,
    which is the second half of what the retro's R5.3 asked for. `-y` stays on the
    encode, so a retry overwrites it rather than accumulating."""
    return Path(out_dir) / f".REEL_v{n}.part.{container}"
```

The convention lives here, not in `deliver`, because `runlayout` is what owns a run's
paths and because `montage` — the inspector called constantly — already imports it and
must not pull in `deliver`'s ffmpeg-side dependency tree to learn one glob.

In `scripts/deliver.py`, add `import os` to the stdlib import block and `runlayout` to
the `scripts.lib` import line.

Replace the two encode branches and add the rename immediately after them:

```python
    n = _next_version(out_dir, profile.container)
    out = str(Path(out_dir) / f"REEL_v{n}.{profile.container}")
    part = runlayout.partial_path(out_dir, n, profile.container)
    if audio is None:
        proc.run([ffbin.ffmpeg(), "-y", "-i", master, *mask_in, *graph, *vmap,
                  *profile.args(), str(part)])
    else:
        # mux the pre-normalized aac stem: profile audio settings don't apply — we
        # stream-copy to preserve the stem's −14 LUFS — so use video-only args + copy.
        # The stem's input index is 1 normally and 2 behind the mask: `-loop 1 -i mask`
        # occupies index 1, and mapping 1:a:0 there would look for an audio stream in
        # a PNG.
        aidx = 2 if mask_in else 1
        proc.run([ffbin.ffmpeg(), "-y", "-i", master, *mask_in, "-i", audio, *graph,
                  *_video_only_args(profile), *(vmap or ["-map", "0:v:0"]),
                  "-map", f"{aidx}:a:0", "-c:a", "copy", "-shortest", str(part)])
    # Atomic commit (design 2026-09-09 §5), the same shape intake_cache.store uses:
    # until this line no file bears a delivered name, so a process killed inside the
    # encode above leaves the partial and nothing else — no version consumed, no
    # truncated file reading as a delivery.
    os.replace(part, out)
```

Extend `deliver`'s docstring with a paragraph:

```python
    The encode lands on `.REEL_v{n}.part.{container}` and is os.replace()d onto its
    delivered name (design 2026-09-09 §5). Until that rename no file in the deliveries
    bucket bears a delivered name, so a killed encode — the 2026-06 run lost one to a
    Bash timeout — consumes no version and leaves the partial as the record that a
    delivery was interrupted. The look gate below stays AFTER the rename: its subject is
    a complete delivered file, and its deliberate behaviour on failure (the file stays,
    the attestation is withheld) is unchanged.
```

- [ ] **Step 4: Fix the one existing assertion this moves**

`tests/lib/test_deliver.py:106` asserts `cmd[-1].endswith("REEL_v1.mp4")`, which is now the partial. That assertion's intent is "the encode's output is this version's file", so point it at the partial and keep the delivered-name check on the return value:

```python
    assert "-an" in cmd and cmd[-1].endswith(".REEL_v1.part.mp4") and master in cmd
```

Then sweep for any other test that reads the encode argv's tail:

Run: `grep -rn 'REEL_v1.mp4' tests/lib/test_deliver.py tests/test_deliver.py`

For each hit, decide whether it is asserting the *encode's target* (update to the partial) or the *delivered path* (leave). Name each decision in your task report.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_deliver.py tests/test_deliver.py -q`
Expected: PASS.

- [ ] **Step 6: Run every deliver consumer**

Run: `.venv/bin/python -m pytest tests/lib/test_build_reel.py tests/lib/test_edl_to_reel.py tests/integration/test_attested_run.py tests/integration/test_reel_backhalf.py -q`
Expected: PASS. The `_fake_encode`-style stubs in these files write `Path(cmd[-1])`, which is now the partial — and since `deliver` renames it, the delivered file still appears. A stub that hardcodes the output name instead of reading `cmd[-1]` will break; fix it to read the argv.

- [ ] **Step 7: Commit**

```bash
git add scripts/deliver.py scripts/lib/runlayout.py tests/lib/test_deliver.py tests/lib/test_runlayout.py tests/test_deliver.py
git commit -m "$(cat <<'MSG'
fix(deliver): a killed encode must not leave a file named like a delivery

ffmpeg was handed the delivered path directly, so a process killed
mid-encode — the 2026-06 run lost one to a Bash timeout — left a
truncated file under REEL_v{n}, permanently consuming that version and
reading as a delivered stage to the router.

The encode now lands on a dotted sibling and is os.replace()d into
place, the same commit shape intake_cache.store uses. Same directory so
the rename is atomic; leading dot so all three delivery globs skip it;
container extension last so ffmpeg can still pick its muxer. The
leftover partial IS the interruption record R5.3 asked for, so the row
gets both halves without a marker that could itself go stale.
MSG
)"
```

---

### Task 6: `montage status` grows a fifth state, and `verify` proves the review's bytes

**Why:** `next_action`'s per-stage state is existence and nothing else, which is why the router reads `reel-review: done` for a review that judged a reel two versions ago (design §6). A stage whose report no longer describes what is on disk must not read as done.

**Files:**
- Modify: `scripts/montage.py` (`_match_grade_state`, `_review_state`, `_newest_delivery`, `_partials`, `next_action`, `verify`)
- Modify: `scripts/lib/provenance.py` (`verify_delivery`'s unattested detail)
- Test: `tests/lib/test_montage.py`, `tests/lib/test_provenance.py`

**Interfaces:**
- Consumes: `matchgrade.MatchReport` + `matchgrade.tone_drift` (Task 1), `runlayout.PARTIAL_GLOB` (Task 5), `Review.reel_digest` (Task 3).
- Produces, for Task 7: every stage dict gains `"stale_reason": str` (empty unless the state is `stale`); `next_action`'s result gains `"interrupted": [<partial filenames>]`; `verify`'s result gains `"review": {...}`.

**Two rules this task must not break.** Both checks run on every `status` call, which the router makes constantly, so **neither may hash a file**: §2's check reads two small JSON files, §3's compares filenames. And both read raw JSON rather than the typed constructors — the same rule `_constraints` follows and records: `EDL.from_json` refuses a tampered EDL, and letting that take the whole status report down with it helps nobody.

The digest is deliberately **not** consulted by `status`. It is `verify`'s instrument, exactly as the module's own docstring already splits the two: *status answers "is there a record", verify answers "is this file the one the record describes"*.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_montage.py`:

```python
def _match_json(reel_dir, edl_path, *, authored=((0, (1.0, 2.0, 3.0), (4.0, 5.0, 6.0)),)):
    """A MATCH.json whose decisions author a pair on each listed episode index."""
    decisions = [matchgrade.ToneDecision(i, "author", "authored", measured=src,
                                         tone_src=src, tone_dst=dst)
                 for i, src, dst in authored]
    matchgrade.MatchReport(target=(4.0, 5.0, 6.0), eps=4.0, decisions=tuple(decisions),
                           edl=str(edl_path)).write(Path(reel_dir) / "MATCH.json")


def _edl_json(path, pairs):
    """A minimal EDL.json — raw, because the reader reads raw."""
    Path(path).write_text(json.dumps({"episodes": [
        {"source": f"s{i}.mp4", "start": 0.0, "dur": 2.0,
         "tone_src": None if s is None else list(s),
         "tone_dst": None if d is None else list(d)}
        for i, (s, d) in enumerate(pairs)]}))


def test_match_grade_is_fresh_when_the_edl_still_carries_its_pairs(tmp_path):
    lay = runlayout.RunLayout(tmp_path, "reel")
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    edl = lay.reel_dir / "EDL.json"
    _edl_json(edl, [((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))])
    _match_json(lay.reel_dir, edl)
    assert montage._match_grade_state(lay.reel_dir) == ("fresh", "")


def test_match_grade_is_stale_when_a_pacing_rerun_wiped_the_pairs(tmp_path):
    lay = runlayout.RunLayout(tmp_path, "reel")
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    edl = lay.reel_dir / "EDL.json"
    _edl_json(edl, [((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))])
    _match_json(lay.reel_dir, edl)
    _edl_json(edl, [(None, None)])                      # edit_plan --pacing wiped the tone
    state, why = montage._match_grade_state(lay.reel_dir)
    assert state == "stale"
    assert "episode 0 was authored a tone pair" in why


def test_an_unreadable_match_json_is_stale_and_says_so_rather_than_raising(tmp_path):
    """The inspector must never replace a whole status report with a traceback —
    _constraints' rule, for the same reason."""
    lay = runlayout.RunLayout(tmp_path, "reel")
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    (lay.reel_dir / "MATCH.json").write_text("{not json")
    state, why = montage._match_grade_state(lay.reel_dir)
    assert state == "stale" and "corrupt" in why


def test_a_stale_match_grade_stage_is_not_done_and_next_points_back_at_it(tmp_path):
    lay = runlayout.RunLayout(tmp_path, "reel")
    _full_run(tmp_path)                                  # the file's existing helper
    edl = lay.reel_dir / "EDL.json"
    _edl_json(edl, [((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))])
    _match_json(lay.reel_dir, edl)
    _edl_json(edl, [(None, None)])
    res = montage.next_action(str(tmp_path))
    row = next(s for s in res["stages"] if s["key"] == "match-grade")
    assert row["state"] == "stale"
    assert row["stale_reason"]
    assert res["next"] == "match-grade"


def test_a_review_of_the_newest_delivery_is_fresh(tmp_path):
    lay = runlayout.RunLayout(tmp_path, "reel")
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    (lay.deliveries / "REEL_v2.mp4").write_text("x")
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps(
        {"reel": str(lay.deliveries / "REEL_v2.mp4"), "findings": []}))
    assert montage._review_state(lay.reel_dir, lay.deliveries) == ("fresh", "")


def test_a_review_of_an_older_version_is_stale_and_names_both(tmp_path):
    lay = runlayout.RunLayout(tmp_path, "reel")
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    (lay.deliveries / "REEL_v1.mp4").write_text("x")
    (lay.deliveries / "REEL_v2.mp4").write_text("x")
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps(
        {"reel": str(lay.deliveries / "REEL_v1.mp4"), "findings": []}))
    state, why = montage._review_state(lay.reel_dir, lay.deliveries)
    assert state == "stale"
    assert "REEL_v1.mp4" in why and "REEL_v2.mp4" in why


def test_the_status_check_hashes_nothing(tmp_path, monkeypatch):
    """status is called constantly by the router; re-hashing a 100 MB reel on every
    call is the one thing these two checks must never do."""
    _full_run(tmp_path)
    monkeypatch.setattr(montage.provenance, "digest_file",
                        lambda p: pytest.fail(f"status hashed {p}"))
    montage.next_action(str(tmp_path))


def test_an_interrupted_delivery_is_reported_and_does_not_read_as_delivered(tmp_path):
    lay = runlayout.RunLayout(tmp_path, "reel")
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    (lay.deliveries / ".REEL_v1.part.mp4").write_text("half")
    res = montage.next_action(str(tmp_path))
    assert res["interrupted"] == [".REEL_v1.part.mp4"]
    assert res["delivered"] is False


def test_verify_rehashes_the_review_against_the_reel_it_judged(tmp_path):
    lay = runlayout.RunLayout(tmp_path, "reel")
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    reel = lay.deliveries / "REEL_v1.mp4"
    reel.write_text("delivered")
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps(
        {"reel": str(reel), "reel_digest": provenance.digest_file(reel), "findings": []}))
    assert montage.verify(str(tmp_path))["review"]["state"] == "bound"
    reel.write_text("a different reel entirely")
    assert montage.verify(str(tmp_path))["review"]["state"] == "digest-mismatch"


def test_verify_calls_an_unstamped_review_unbound_not_mismatched(tmp_path):
    """A review written before the digest existed asserts nothing about bytes — the
    honest word for that is unbound, not a failed comparison."""
    lay = runlayout.RunLayout(tmp_path, "reel")
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    (lay.deliveries / "REEL_v1.mp4").write_text("delivered")
    (lay.reel_dir / "REVIEW.json").write_text(json.dumps(
        {"reel": str(lay.deliveries / "REEL_v1.mp4"), "findings": []}))
    assert montage.verify(str(tmp_path))["review"]["state"] == "unbound"
```

Add whatever of `import json`, `from pathlib import Path`, `from scripts.lib import matchgrade, provenance, runlayout` the file is missing. `_full_run` is the helper `tests/lib/test_montage.py` already uses to fill a run dir; if it does not exist under that name, use the file's own equivalent and say which in your task report.

Append to `tests/lib/test_provenance.py`:

```python
def test_an_unattested_file_detail_does_not_assert_the_least_likely_cause(tmp_path):
    """deliver DOES write the file before the look gate withholds an attestation, and
    (since 2026-09-09) before the attestation is written at all — so 'this file was not
    produced by deliver()' is the one reading that is usually false."""
    p = tmp_path / "REEL_v1.mp4"
    p.write_text("x")
    detail = provenance.verify_delivery(p)["detail"]
    assert "no attestation sidecar" in detail
    assert "was not produced by deliver()" not in detail
    assert "look gate" in detail and "interrupted" in detail
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py tests/lib/test_provenance.py -q -k "stale or fresh or review or interrupted or hashes or unattested"`
Expected: FAIL — `AttributeError: module 'scripts.montage' has no attribute '_match_grade_state'`.

- [ ] **Step 3: Implement the two freshness readers**

In `scripts/montage.py`, extend the imports:

```python
from scripts.lib import constraints, matchgrade, provenance, runlayout
```

`matchgrade` is the only new import and it is light (statistics + `scripts.lib.color`).
`runlayout` — already imported — is where the partial's glob lives, so this inspector
does not pull in `deliver`'s ffmpeg-side dependency tree.

Add, next to `_constraints`:

```python
def _match_grade_state(reel_dir: Path) -> tuple[str, str]:
    """("fresh"|"stale", reason) for the conductor's report against the EDL today.

    The instrument is the authored PAIRS, not a digest — match_grade rewrites the EDL
    itself and edit_plan --pacing rewrites it again, so a whole-file digest would fire
    on the sanctioned rewrite too (design 2026-09-09 §1/§2).

    Both files are read as RAW JSON on purpose. EDL.from_json refuses a tampered file,
    and this is the inspector the router calls constantly: a typo or a tampered stamp
    must not replace the whole status report with a traceback. That is the rule
    _constraints already records, for the same reason.

    Anything that cannot be read — corrupt MATCH.json, a named EDL that is not there —
    is reported as `stale` with the cause named, never as fresh: a report that cannot
    be shown to describe the EDL is not one a reader should trust, and the remedy is
    the same either way (re-run the conductor).

    Hashes nothing: status is called constantly.
    """
    mp = reel_dir / "MATCH.json"
    if not mp.exists():
        return "stale", "there is no MATCH.json — run `match_grade build --geometry`"
    try:
        report = matchgrade.MatchReport.from_json(mp)
    except (ValueError, OSError) as e:
        return "stale", f"MATCH.json is corrupt or unreadable ({e})"
    try:
        edl_raw = json.loads(Path(report.edl).read_text())
        episodes = edl_raw["episodes"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        return "stale", (f"MATCH.json names {report.edl}, which cannot be read as an EDL "
                         f"({e}) — nothing can check what this report claims")
    pairs = [(_opt_profile(e.get("tone_src")), _opt_profile(e.get("tone_dst")))
             for e in episodes]
    drift = matchgrade.tone_drift(report.decisions, pairs)
    if not drift:
        return "fresh", ""
    return "stale", ("; ".join(drift) + ". Re-run `match_grade build --geometry` — a "
                     "later `edit_plan build --pacing` wipes authored tone, which is "
                     "what this reports")


def _opt_profile(v) -> tuple[float, float, float] | None:
    """A raw JSON tone anchor triple, or None. Anything malformed reads as None, which
    tone_drift reports as a wiped pair — the reader's job is to notice a difference,
    not to validate the EDL, whose own constructor does that where it is loaded."""
    if not (isinstance(v, (list, tuple)) and len(v) == 3):
        return None
    try:
        return (float(v[0]), float(v[1]), float(v[2]))
    except (TypeError, ValueError):
        return None


def _newest_delivery(out: Path) -> str | None:
    """The highest-numbered REEL_v{n} file in the deliveries bucket, by name.

    The same monotone identity _next_version defends: v10 sorts before v2 as a string,
    so the version number is parsed, never sorted lexically."""
    best: tuple[int, str] | None = None
    for p in out.glob("REEL_v*"):
        m = re.match(r"REEL_v(\d+)\.", p.name)
        if m and p.suffix != ".json" and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), p.name)
    return None if best is None else best[1]


def _review_state(reel_dir: Path, out: Path) -> tuple[str, str]:
    """("fresh"|"stale", reason) for REVIEW.json against the newest delivery.

    Names, not bytes — this is the cheap half of the split the module already declares
    for deliveries: status answers "is there a record", verify answers "is this file
    the one the record describes". The run's actual failure was a review two VERSIONS
    stale, which a name comparison catches for free; a file swapped in place under the
    same name is verify's business, and 0.3.0's monotone versioning already stops the
    pipeline producing one.

    Hashes nothing.
    """
    rp = reel_dir / "REVIEW.json"
    if not rp.exists():
        return "stale", "there is no REVIEW.json — run the reel-review stage"
    try:
        judged = json.loads(rp.read_text()).get("reel") or ""
    except (OSError, ValueError) as e:
        return "stale", f"REVIEW.json is corrupt or unreadable ({e})"
    newest = _newest_delivery(out)
    if newest is None:
        return "stale", "no delivered reel to review — deliver first"
    if Path(judged).name != newest:
        return "stale", (f"this review judged {Path(judged).name or '(nothing named)'} "
                         f"and the newest delivery is {newest} — re-run the reel-review "
                         f"stage against the reel that shipped")
    return "fresh", ""


def _partials(out: Path) -> list[str]:
    """Deliveries that were interrupted mid-encode: the dotted partials deliver leaves
    behind (design 2026-09-09 §5). The partial IS the record — there is no separate
    marker to go stale."""
    return sorted(p.name for p in out.glob(runlayout.PARTIAL_GLOB))
```

Add `import re` to the module's stdlib imports.

- [ ] **Step 4: Wire the state into `next_action`**

First, at module level, directly below `_partials` (so both readers are already
defined), the table of which stages have a freshness answer at all:

```python
# The two stages whose artifact asserts something checkable about another file. Every
# other stage's artifact is its own statement, and existence is the whole of what
# status can say about it.
_FRESHNESS = {"match-grade": lambda lay: _match_grade_state(lay.reel_dir),
              "reel-review": lambda lay: _review_state(lay.reel_dir, lay.deliveries)}
```

Then replace the stage loop in `next_action`:

```python
    for st in V1_STAGES:
        base = lay.bucket(st.bucket)
        done = _exists(base, st.artifact)
        stale_reason = ""
        if done and st.key in _FRESHNESS:
            state_name, stale_reason = _FRESHNESS[st.key](lay)
            done = state_name == "fresh"
        if st.kind == "deferred":
            state = "skip"
        elif st.kind == "optional":
            state = "done" if done else "optional"
        elif done:
            state = "done"
        elif stale_reason:
            # the artifact IS there; it just no longer describes what is on disk. A
            # fifth state, because "next" alone would say the stage never ran
            # (design 2026-09-09 §6).
            state = "stale"
            if next_key is None:
                next_key = st.key
        elif next_key is None:
            state = "next"
            next_key = st.key
        else:
            state = "pending"
        if st.key == "deliver":
            delivered = done
        stages.append({"key": st.key, "artifact": st.artifact, "bucket": st.bucket,
                       "path": str(base / st.artifact), "kind": st.kind,
                       "state": state, "stale_reason": stale_reason,
                       "checkpoint": st.checkpoint, "runner": st.runner})
```

And the returned dict gains one key:

```python
    return {"stages": stages, "next": next_key, "delivered": delivered,
            "deliveries": _deliveries(lay.deliveries), "interrupted": _partials(lay.deliveries),
            "constraints": _constraints(run),
            "reel": reel, "reels": runlayout.reel_names(run),
            "layout": lay.to_dict(), "legacy_layout": runlayout.is_legacy_run(run)}
```

Extend `next_action`'s docstring's state list:

```
      stale    - the artifact exists but no longer describes what is on disk: a
                 match-grade report whose authored pairs the EDL has lost, or a review
                 of an older delivery. Not done, so `next` points back at it — that is
                 the teeth, and there is no separate refusal (design 2026-09-09 §6)
```

and its Returns line gains `"stale_reason"` per stage and `"interrupted": [...]` at the top level.

- [ ] **Step 5: Wire the expensive half into `verify`**

```python
def _verify_review(reel_dir: Path, out: Path) -> dict:
    """Re-hash the reel REVIEW.json judged against the digest it recorded — the
    expensive half of the split status declares (design 2026-09-09 §3).

    Three states, each a different true statement: `unbound` (no digest — a review
    written before this binding, which asserts nothing about bytes), `bound` (the file
    is the one reviewed), `digest-mismatch` (it is not)."""
    rp = reel_dir / "REVIEW.json"
    if not rp.exists():
        return {"state": "absent", "detail": "no REVIEW.json in this reel"}
    try:
        d = json.loads(rp.read_text())
    except (OSError, ValueError) as e:
        return {"state": "unreadable", "detail": f"REVIEW.json is corrupt ({e})"}
    reel, want = d.get("reel") or "", d.get("reel_digest") or ""
    if not want:
        return {"state": "unbound", "reel": Path(reel).name,
                "detail": "this review records no reel digest, so nothing binds it to "
                          "the bytes it judged — re-run the reel-review stage"}
    if not Path(reel).exists():
        return {"state": "missing", "reel": Path(reel).name,
                "detail": f"the reviewed reel {reel} is not on disk any more"}
    actual = provenance.digest_file(reel)
    if actual != want:
        return {"state": "digest-mismatch", "reel": Path(reel).name,
                "detail": (f"the file hashes to {actual[:12]}… but the review records "
                           f"{want[:12]}… — this is not the reel that was reviewed")}
    return {"state": "bound", "reel": Path(reel).name, "detail": ""}


def verify(run_dir: str, reel: str = runlayout.DEFAULT_REEL) -> dict:
    """Re-hash every delivered reel against its attestation, and the reviewed reel
    against REVIEW.json's own digest (design §6, 2026-09-09 §3). Run once at CP3, where
    the cost is irrelevant and the answer matters: status answers "is there a record",
    verify answers "is this file the one the record describes"."""
    lay = runlayout.RunLayout(Path(run_dir), reel)
    return {"deliveries": _deliveries(lay.deliveries, rehash=True),
            "review": _verify_review(lay.reel_dir, lay.deliveries)}
```

- [ ] **Step 6: Correct the unattested detail**

In `scripts/lib/provenance.py`, `verify_delivery`'s initial `out` dict:

```python
    out: dict = {"file": p.name, "state": "unattested", "overall": None, "overrides": [],
                 "engine_drift": False, "episode_qc": "unknown",
                 "detail": ("no attestation sidecar — the look gate withheld it, the "
                            "delivery was interrupted after the encode, or this file "
                            "was not produced by deliver() at all. The file itself is "
                            "complete: deliver renames the encode into place before any "
                            "of the three (design 2026-09-09 §5)")}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py tests/lib/test_provenance.py -q`
Expected: PASS. Existing `next_action` tests that assert a stage dict as a whole object gain the `stale_reason` key — update them rather than weakening the assert, and list them in your task report.

- [ ] **Step 8: Run every router consumer**

Run: `.venv/bin/python -m pytest tests/integration/test_verify.py tests/integration/test_attested_run.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add scripts/montage.py scripts/lib/provenance.py tests/lib/test_montage.py tests/lib/test_provenance.py
git commit -m "$(cat <<'MSG'
feat(montage): a report that no longer describes the run is not "done"

next_action's per-stage state was existence and nothing else, which is
why the router read reel-review as done for a review that judged a reel
two versions ago. A fifth state, stale, joins the four: the artifact is
there and no longer describes what is on disk. It is not done, so next
points back at it — that is the teeth, and no separate refusal is added.

Both checks hash nothing, because the router calls status constantly:
match-grade compares the pairs its own report authored against the EDL
today, reel-review compares version names. Bytes are verify's business,
which is the split this module already declared for deliveries. Both
read raw JSON rather than the typed constructors, so a tampered EDL
cannot replace the whole status report with a traceback — _constraints'
rule, for its reason.

verify_delivery's detail stops asserting the least likely of its three
causes: deliver renames the encode into place before the look gate, the
version log and the attestation, so an unattested file is complete.
MSG
)"
```

---

### Task 7: end-to-end proofs, each with a control that must not move

**Why:** Each of the previous tasks proved its own unit. This proves the three bindings and the rename **through the drivers that produce them**, and — most importantly — proves the match-grade check is not a file digest in disguise. That control is what separates this design from the naive one the design rejected in §1.

**Files:**
- Create: `tests/integration/test_bound_reports.py`

**What is and is not proved on real bytes.** P1/P2/P4 run a real ffmpeg encode through `deliver`. P3 stubs `measure_crop`: its subject is the report's binding, not the measurement, and `tests/integration/test_matchgrade.py` already measures real crops. There is **no real-bytes proof of a genuinely killed ffmpeg** — Task 5's kill is a stubbed `proc.run` that writes bytes then raises, which is what a killed subprocess leaves behind; arranging a real SIGKILL mid-encode inside pytest buys a different failure mode, not more truth about the rename. Say this in the module docstring.

- [ ] **Step 1: Write the proof module**

Create `tests/integration/test_bound_reports.py`:

```python
"""The bindings, proved through the drivers that write them
(design docs/specs/2026-09-09-bound-reports-design.md).

Four proofs, each with a control that must NOT move. P3's control is the
load-bearing one: an EDL rewrite that does not touch tone must leave match-grade
FRESH, which is what separates a binding to the report's own claim from a digest
of the file it read — the naive instrument the design rejected in §1, because
match_grade rewrites that EDL itself and edit_plan --pacing rewrites it again.

Not proved here: a genuinely SIGKILLed ffmpeg. Task 5's kill is a stubbed proc.run
that writes bytes and then raises, which is the state a killed subprocess leaves;
arranging a real signal inside pytest tests the signal, not the rename.
"""
import json
from pathlib import Path

import pytest

from scripts import check_reel, deliver, match_grade, montage, reel_review
from scripts.lib import assembly, matchgrade, provenance, runlayout
from scripts.lib.edl import EDL, EDLEpisode
from scripts.lib.models import (EpisodeGeometry, ReelCheckSpec, ReelGeometry, REEL_H264)


def _deliver_one(tmp_path, sample_clip, changelog):
    """A real encode through deliver into the run's deliveries bucket. Returns its path."""
    lay = runlayout.RunLayout(tmp_path, "reel")
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    master = str(tmp_path / "master.mp4")
    assembly.concat([str(sample_clip)], master)
    dur = assembly.probe_duration(master)
    rep = check_reel.run(master, [str(sample_clip)], ReelCheckSpec(target_dur=dur),
                         str(tmp_path / "r.json"))
    assert rep.overall
    return deliver.deliver(master, REEL_H264, str(lay.deliveries), changelog, rep,
                           scratch_dir=str(lay.build))


@pytest.mark.integration
def test_a_review_is_bound_to_the_bytes_it_judged(tmp_path, sample_clip):
    lay = runlayout.RunLayout(tmp_path, "reel")
    v1 = _deliver_one(tmp_path, sample_clip, "first cut")
    review = reel_review.build_review([], v1, summary="clean")
    reel_review.write_review(review, str(lay.reel_dir))
    # bound: verify re-hashes and agrees
    assert montage.verify(str(tmp_path))["review"]["state"] == "bound"
    # and the CONTROL that must not move: status, which hashes nothing, calls it fresh
    assert montage._review_state(lay.reel_dir, lay.deliveries) == ("fresh", "")
    # the reel is swapped under the same name (only possible by hand — 0.3.0's monotone
    # versioning stops the pipeline doing it): bytes catch it, names cannot
    Path(v1).write_bytes(b"a different reel entirely")
    assert montage.verify(str(tmp_path))["review"]["state"] == "digest-mismatch"
    assert montage._review_state(lay.reel_dir, lay.deliveries) == ("fresh", "")


@pytest.mark.integration
def test_a_second_delivery_makes_the_review_stale_without_hashing(tmp_path, sample_clip):
    """The run's actual failure: REVIEW.json approved REEL_v1 while a later version
    shipped, and the router still read the stage as done."""
    lay = runlayout.RunLayout(tmp_path, "reel")
    v1 = _deliver_one(tmp_path, sample_clip, "first cut")
    reel_review.write_review(reel_review.build_review([], v1, summary="clean"),
                             str(lay.reel_dir))
    before = next(s for s in montage.next_action(str(tmp_path))["stages"]
                  if s["key"] == "reel-review")
    assert (before["state"], before["stale_reason"]) == ("done", "")   # control
    _deliver_one(tmp_path, sample_clip, "second cut")
    after = next(s for s in montage.next_action(str(tmp_path))["stages"]
                 if s["key"] == "reel-review")
    assert after["state"] == "stale"
    assert "REEL_v1.mp4" in after["stale_reason"] and "REEL_v2.mp4" in after["stale_reason"]


def _geometry(tmp_path, sources):
    """A GEOMETRY.json + the EDL it names, one trivial episode per source."""
    lay = runlayout.RunLayout(tmp_path, "reel")
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    edl_path = lay.reel_dir / "EDL.json"
    # the same shape tests/lib/test_match_grade.py::_ep builds — EDLEpisode carries the
    # picture intent as flat fields, not a ReframeSpec
    eps = tuple(EDLEpisode(source=s, start=0.0, dur=2.0, shot_type="wide",
                           composition="center", grid="thirds")
                for s in sources)
    edl_path.write_text(json.dumps(EDL(episodes=eps).to_dict(), indent=2))
    for i, s in enumerate(sources):
        (tmp_path / f"r{i}.json").write_text("[]")
    geo = ReelGeometry(episodes=tuple(
        EpisodeGeometry(manifest={}, route=str(tmp_path / f"r{i}.json"), source=s,
                        project_dir=str(tmp_path / f"p{i}"))
        for i, s in enumerate(sources)), edl=str(edl_path))
    gp = lay.episodes / "GEOMETRY.json"
    lay.episodes.mkdir(parents=True, exist_ok=True)
    geo.write(gp)
    return str(gp), edl_path


@pytest.mark.integration
def test_match_grade_goes_stale_on_a_wipe_and_stays_fresh_on_an_unrelated_rewrite(
        tmp_path, monkeypatch):
    """THE control of this branch. A tone wipe must be caught; an EDL rewrite that
    leaves tone alone must NOT be — a whole-file digest would fail this test, and the
    design rejected it for exactly that (§1)."""
    lay = runlayout.RunLayout(tmp_path, "reel")
    monkeypatch.setattr(match_grade, "measure_crop",
                        lambda md, src, route, **k: (10.0, 90.0, 150.0) if "a.mp4" in src
                        else (60.0, 140.0, 240.0))
    gp, edl_path = _geometry(tmp_path, ["a.mp4", "b.mp4"])
    match_grade.write_match(gp)
    assert montage._match_grade_state(lay.reel_dir) == ("fresh", "")

    # CONTROL: rewrite the EDL touching something that is not tone. The file's bytes
    # and its provenance stamp both change; the report's claim does not.
    raw = json.loads(edl_path.read_text())
    raw["changelog"] = "an unrelated edit"
    edl_path.write_text(json.dumps(raw, indent=2))
    assert montage._match_grade_state(lay.reel_dir) == ("fresh", "")

    # the failure: a later edit_plan --pacing run wipes authored tone
    raw = json.loads(edl_path.read_text())
    for e in raw["episodes"]:
        e["tone_src"] = e["tone_dst"] = None
    edl_path.write_text(json.dumps(raw, indent=2))
    state, why = montage._match_grade_state(lay.reel_dir)
    assert state == "stale"
    assert "episode 0 was authored a tone pair" in why
    row = next(s for s in montage.next_action(str(tmp_path))["stages"]
               if s["key"] == "match-grade")
    assert row["state"] == "stale"


@pytest.mark.integration
def test_an_interrupted_delivery_is_named_and_costs_no_version(tmp_path, sample_clip,
                                                               monkeypatch):
    lay = runlayout.RunLayout(tmp_path, "reel")
    v1 = _deliver_one(tmp_path, sample_clip, "first cut")
    # CONTROL: a completed delivery leaves nothing behind and reads as delivered
    res = montage.next_action(str(tmp_path))
    assert res["interrupted"] == [] and res["delivered"] is True

    real_run = deliver.proc.run
    def die(cmd, *a, **k):
        if cmd and cmd[0] in ("git", "ffprobe") or "ffprobe" in str(cmd[0]):
            return real_run(cmd, *a, **k)
        Path(cmd[-1]).write_bytes(b"half-an-encode")
        raise RuntimeError("killed by a Bash timeout")
    monkeypatch.setattr(deliver.proc, "run", die)
    with pytest.raises(RuntimeError, match="killed"):
        _deliver_one(tmp_path, sample_clip, "second cut")
    monkeypatch.undo()

    res = montage.next_action(str(tmp_path))
    assert res["interrupted"] == [".REEL_v2.part.mp4"]
    assert sorted(p.name for p in lay.deliveries.glob("REEL_v*.mp4")) == ["REEL_v1.mp4"]
    assert (lay.deliveries / "VERSIONS.md").read_text().count("- v2 |") == 0
    # the killed version is retried, not burned
    assert deliver._next_version(str(lay.deliveries), "mp4") == 2
    assert _deliver_one(tmp_path, sample_clip, "second cut, for real").endswith("REEL_v2.mp4")
    assert montage.next_action(str(tmp_path))["interrupted"] == []
```

- [ ] **Step 2: Run the proofs**

Run: `.venv/bin/python -m pytest tests/integration/test_bound_reports.py -q -m integration -v`
Expected: 4 passed.

If a proof fails on a fixture detail (an `EDLEpisode` field this plan named that the contract does not have, a `check_reel.run` signature mismatch), **fix the test to match the real contract and say what you changed** — do not weaken an assertion to make it pass. In particular, `_deliver_one`'s `check_reel.run(...)` call must produce a report that passes; if the sample clip cannot, use the idiom `tests/integration/test_reel_backhalf.py` already uses to build a passing report and name the change.

- [ ] **Step 3: Prove the control actually discriminates**

The unrelated-rewrite control is only worth something if the naive instrument would fail it. Verify by hand, then restore:

```bash
cp scripts/montage.py scripts/montage.py.bak
```

Edit `_match_grade_state` so the drift check is a digest of the EDL file instead of the pair comparison (compare `provenance.digest_file(report.edl)` against a digest recorded at write time — since none is recorded, simply `return "stale", "digest"` when the EDL's mtime differs is enough to show the shape). Then:

Run: `.venv/bin/python -m pytest tests/integration/test_bound_reports.py -q -m integration -k "unrelated_rewrite"`
Expected: FAIL — the control catches the naive instrument.

Restore: `cp scripts/montage.py.bak scripts/montage.py && rm scripts/montage.py.bak`

Then confirm the restore is exact: `git diff --stat scripts/montage.py` must show no change beyond what this branch already committed.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_bound_reports.py
git commit -m "$(cat <<'MSG'
test: prove the bindings through the drivers, with the control that matters

Four end-to-end proofs, each with a control that must not move. The
load-bearing one is the unrelated EDL rewrite: it changes the file's
bytes and its provenance stamp while leaving the tone pairs alone, and
match-grade must stay FRESH. A digest of the EDL — the obvious
instrument, and the one the design rejected — fails that test, which is
the whole reason the check compares the report's own claim instead.

Not proved here and said so in the docstring: a genuinely SIGKILLed
ffmpeg. The stubbed kill leaves the state a killed subprocess leaves.
MSG
)"
```

---

### Task 8: the mutation battery, then the docs

**Why:** Every guard this branch added must be shown to be load-bearing. A test that passes when the code it guards is removed is not a test. Then the queue, the changelog and the skills catch up in the same task, because a capability nobody is told about is the `probe grade` story again.

**Files:**
- Modify: `CHANGELOG.md`, `.claude-plugin/plugin.json`, `CLAUDE.md`, `docs/backlog.md`, `docs/backlog-closed.md`, `docs/build-status.md`, `docs/pipeline-map.md`
- Modify: `skills/match-grade/SKILL.md`, `skills/using-montage/SKILL.md`, `skills/reel-review/SKILL.md`, `skills/episode-qc/SKILL.md`

- [ ] **Step 1: Run the mutation battery**

**Run every command below under `PYTHONDONTWRITEBYTECODE=1`** — a one-byte edit can match the previous file's size and mtime-second, and CPython then serves a stale `.pyc`, which reads exactly like a non-discriminating row.

For each row: make the edit, run the selector, record RED or GREEN, then restore. Restore a **committed** file with `git show HEAD:<path> > <path>`; every file in this table is committed by an earlier task, so that is the route for all of them. After each restore run `git diff --stat <path>` and confirm it is empty.

| # | File | Mutation | Selector | Expect |
|---|------|----------|----------|--------|
| 1 | `scripts/lib/matchgrade.py` | in `tone_drift`, delete `if d.action != "author": continue` | `tests/lib/test_matchgrade.py -k skipped_episode_that_gained` | RED |
| 2 | `scripts/lib/matchgrade.py` | in `tone_drift`, delete the `len(decisions) != len(pairs)` guard | `tests/lib/test_matchgrade.py -k episode_count_change` | RED |
| 3 | `scripts/lib/matchgrade.py` | in `tone_drift`, make the `elif` branch emit the same string as the `if` | `tests/lib/test_matchgrade.py -k changed_pair` | RED |
| 4 | `scripts/lib/matchgrade.py` | in `MatchReport.__post_init__`, delete the empty-`edl` refusal | `tests/lib/test_matchgrade.py -k empty_edl_path` | RED |
| 5 | `scripts/lib/matchgrade.py` | in `ToneDecision.from_dict`, pass `d.get("tone_src")` through unconverted | `tests/lib/test_matchgrade.py -k round_trips` | RED |
| 6 | `scripts/match_grade.py` | delete the `MatchReport(...).write(json_path)` line | `tests/lib/test_match_grade.py -k json_twin` | RED |
| 7 | `scripts/match_grade.py` | write `edl=str(Path(geo.edl).resolve())` instead of `edl=geo.edl` | `tests/lib/test_match_grade.py -k verbatim` | RED |
| 8 | `scripts/montage.py` | set the match-grade stage's artifact back to `"MATCH.md"` | `tests/lib/test_montage.py -k keys_on_the_json` | RED |
| 9 | `scripts/reel_review.py` | in `build_review`, take the digest from `raw_findings[0].get("clip_digest", "")` instead of from disk | `tests/test_reel_review.py -k stamps_the_digest` | RED |
| 10 | `scripts/reel_review.py` | delete `main`'s missing-reel refusal | `tests/test_reel_review.py -k names_no_file` | RED |
| 11 | `scripts/lib/review.py` | drop `"reel_digest"` from `to_dict` | `tests/lib/test_review.py -k round_trips` | RED |
| 12 | `scripts/episode_qc.py` | delete the `"clip_digest"` key from `_evidence` | `tests/integration/test_episode_qc.py -m integration -k decoded` | RED |
| 13 | `scripts/episode_qc.py` | delete `build_qc`'s `if not packed:` branch | `tests/lib/test_episode_qc.py -k records_no_digest` | RED |
| 14 | `scripts/episode_qc.py` | delete `build_qc`'s `if packed != actual:` branch | `tests/lib/test_episode_qc.py -k re_rendered` | RED |
| 15 | `scripts/lib/runlayout.py` | in `partial_path`, drop the leading dot (`f"REEL_v{n}.part.{container}"`) | `tests/lib/test_runlayout.py -k ends_in_the_container` | RED |
| 16 | `scripts/deliver.py` | pass `out` to both `proc.run` calls and delete the `os.replace` | `tests/lib/test_deliver.py -k killed_encode` | RED |
| 17 | `scripts/montage.py` | in `next_action`, delete `done = state_name == "fresh"` | `tests/lib/test_montage.py -k next_points_back` | RED |
| 18 | `scripts/lib/provenance.py` | restore the old `"this file was not produced by deliver()"` detail | `tests/lib/test_provenance.py -k least_likely_cause` | RED |

**Row 15's selector was corrected after Task 5's review**, which caught that the
obvious choice does not discriminate: `test_a_partial_is_invisible_to_every_delivery_glob`
hand-types the excluded filename and never calls `partial_path`, so dropping the dot
leaves it GREEN. `test_the_partial_ends_in_the_container_so_ffmpeg_can_pick_a_muxer`
asserts `partial_path`'s exact output string and is the one that catches it. The same
review recorded two of this branch's own tests as passing with the feature reverted —
see the ledger's Task 5 deferred minors; the whole-branch review should triage whether
either is worth strengthening.

Run each as, for example:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/lib/test_matchgrade.py -q -k skipped_episode_that_gained
```

**A row that comes back GREEN is a finding, not a nuisance.** Report it, then either close the hole with a new test or explain why the guard is genuinely unobservable — do not quietly move on, and do not weaken a selector to make a row go red. Note also that a `-k` matching nothing prints `no tests ran`, which is NOT a RED — check the collected count on every row.

- [ ] **Step 2: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. Record the exact counts; the pre-branch baseline is `3548 passed, 1 skipped`.

- [ ] **Step 3: Bump the version**

`.claude-plugin/plugin.json` → `"version": "0.9.0"`. **MINOR**, not PATCH: this adds a required artifact (`MATCH.json`), a new stage state the router reads, and two contract fields — a change in how the conveyor is driven, which is the MINOR line in [docs/development-workflow.md](../development-workflow.md#versioning).

Add to the top of `CHANGELOG.md`, immediately under the preamble:

```markdown
## 0.9.0 — 2026-09-09

Three reports stated a conclusion and recorded nothing about what they concluded
from, so nothing could tell a current one from a report describing a file that had
moved. Measured on the 2026-06 run: `MATCH.md` claimed 8/8 authored tone pairs
against an `EDL.json` carrying 5 (episodes 0/2/7 empty at a max Δ of 10, 6 and 49,
so not `within-eps` skips); `REVIEW.json` named a path whose file is dated a day and
a half after the review that approved it; and the QC evidence packet carried no
digest while the verdict stamped from it did.

- **`MATCH.json`** — the conductor writes the twin every other stage already had.
  `MATCH.md` is unchanged and byte-identical; the JSON carries the decisions the
  report renders, so its claim can be checked. The router's `match-grade` row keys
  on it.
- **`Review.reel_digest`** — stamped by `build_review` from the file on disk, never
  from the reviewer's claim. A review written before this field loads as *unbound*,
  which `montage verify` reports as such rather than as a failed comparison.
- **The QC evidence packet binds too.** `pack` records the clip's digest and
  `build_qc` refuses a packet that was made from a different render. This one
  refuses rather than reports: an unbound packet makes the verdict claim to bind
  pixels the judge never saw.
- **`deliver` is atomic.** The encode lands on `.REEL_v{n}.part.<container>` and is
  `os.replace`d into position, so a killed encode — the 2026-06 run lost one to a
  Bash timeout — consumes no version, is invisible to every delivery glob, and
  leaves the partial as the record that a delivery was interrupted.
- **`montage status` has a fifth stage state, `stale`** — the artifact exists and no
  longer describes what is on disk. It is not `done`, so `next` points back at it.
  Both checks hash nothing: match-grade compares the pairs its own report authored,
  reel-review compares version names. Bytes are `montage verify`'s business.

The instrument is deliberately the report's own claim rather than a digest of the
file it read. `match_grade` rewrites the EDL itself and `edit_plan build --pacing`
rewrites it again, so a whole-file digest would fire on the sanctioned rewrite as
loudly as on the wipe — and a gate that cries wolf gets its ceiling raised, which
is this project's own measured history on `color_delta_max` (12 → 44 → 56).

Closes R5.2, R5.3 and R10.9. Two of the retro's four R5 bullets were already closed
by 0.3.0, and R5.2's own claim that `episode_qc` held "the one binding" is now wrong
by four — `master_digest`, `reel_digest`, `music_digest` and `ReelGeometry.cuts` all
landed since it was written.
```

Do **not** add a subtitle after the date: `tests/test_plugin_manifests.py` matches
`## (\d+)\.(\d+)\.(\d+) — \d{4}-\d{2}-\d{2}` with `re.fullmatch`, and a trailing
`· Bound reports` breaks it.

- [ ] **Step 4: Sync the queue**

In `docs/backlog.md`:
- Delete the P1 rows **R5.3** and **R5.2**, and the P2 row **R10.9**.
- Add the five rows from the design's `§Deferred` table into P3 (`stamp(inputs=)`'s missing reader; what rewrote the run's EDL; a marker for the post-rename window; `SHEETS.md` having no machine-readable form; extending the staleness reader to the optional stages) — group them under the existing **Reel / QC / delivery** and **Docs / test scaffolding** headings as each fits.
- Update `_Last updated: 2026-09-09._`

In `docs/backlog-closed.md`, add the three closed rows with the closure note each was closed *with* — that note is the one thing no other document carries. Each must say what the row's own premise got wrong:
- **R5.2** — closed, and its wording was already stale: "the one binding that held" was true on 2026-08-25 and is now wrong by four.
- **R5.3** — closed with both halves at once; the partial file IS the interruption record, so no marker with a lifetime was needed.
- **R10.9** — closed; the packet's binding is a refusal and not a report, and the reason is that a false binding is worse than an absent one.

- [ ] **Step 5: Sync the registry and the maps**

`CLAUDE.md`'s Quick Reference gains two rows (design + plan), placed after the legible-evidence pair, in the same voice as the rows around them — say what the slice measured and what it overturned, not what it "adds".

`docs/build-status.md` gains a Done entry.

`docs/pipeline-map.md`: check whether it names `MATCH.md` as the match-grade stage's artifact and update to `MATCH.json` if so.

Run: `grep -rn "MATCH.md" docs/pipeline-map.md docs/build-status.md`

- [ ] **Step 6: Sync the skills**

The capability has to be reachable from where a reader is standing — that is the R4.2 lesson this project has now learned twice.

Run: `grep -rln "MATCH.md\|REVIEW.json\|evidence.json\|REEL_v" skills/`

At minimum:
- `skills/match-grade/SKILL.md` — names `MATCH.json` as the stage's output beside `MATCH.md`, and says that a later `edit_plan build --pacing` wipes authored tone and that `montage status` will then report this stage `stale`.
- `skills/using-montage/SKILL.md` — the `stale` state and what to do about it (re-run that stage; the reason string says why), and that an `interrupted` entry means a delivery was killed mid-encode and can simply be re-run.
- `skills/reel-review/SKILL.md` — `--reel` must point at the delivered file, which must exist; the review is bound to its bytes.
- `skills/episode-qc/SKILL.md` — after any re-render, `pack` again before dispatching judges; a packet from an older render is refused by name.

- [ ] **Step 7: Verify the manifests agree**

Run: `.venv/bin/python -m pytest tests/test_plugin_manifests.py -q`
Expected: PASS.

- [ ] **Step 8: Full suite, then commit**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

```bash
git add CHANGELOG.md .claude-plugin/plugin.json CLAUDE.md docs/ skills/
git commit -m "$(cat <<'MSG'
docs: 0.9.0 — three reports now say what they read

MINOR, not PATCH: a required artifact (MATCH.json), a fifth stage state
the router reads, and two contract fields all change how the conveyor is
driven.

Closes R5.2, R5.3 and R10.9, each with what its own premise got wrong.
Five deferrals filed, including the one nothing asked for: provenance's
stamp(inputs=) is written at one site and read in production at none, so
the generic half of the provenance block is a format with no reader.
MSG
)"
```

---

## Self-Review

**Spec coverage.** §2 → Tasks 1–2. §3 → Task 3. §4 → Task 4. §5 → Task 5. §6 → Task 6 (both halves, plus the `verify_delivery` detail). §1's principle is enforced by Task 7's unrelated-rewrite control. §7's honest limits are recorded in the CHANGELOG and in Task 7's module docstring. §8's Deferred table → Task 8 Step 4.

**Type consistency.** `MatchReport` / `ToneDecision.to_dict` / `tone_drift` are defined in Task 1 and used under those names in Tasks 2, 6 and 7. `runlayout.PARTIAL_GLOB` / `runlayout.partial_path` are defined in Task 5 and used in Task 6. `Review.reel_digest` is defined in Task 3 and read in Task 6. `stale_reason` and `interrupted` are produced in Task 6 and asserted in Task 7.

**Two things a reviewer should push on.**
1. Task 6's `_review_state` compares **names**, and the digest never enters `status`. That is deliberate (design §3/§7) and Task 7's first proof pins both halves — a name-fresh, byte-mismatched pair. If a reviewer reads the name comparison as the weak half, they are right, and the design says so.
2. Task 4 refuses packets written before this slice. That is a deliberate behaviour change, not an oversight; the remedy is named in the message and costs seconds.
