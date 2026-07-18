# Reel-review editorial (§5.13 Slice B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the §5.13 **editorial review** (Slice B) — a fresh reviewer subagent judges the delivered reel against `SPEC` and emits typed findings; a `Finding`/`Review` config-spec + a thin `reel_review` writer/CLI + a `reel-review` SKILL (dispatch + human loop) turn that judgement into `REVIEW.json`+`REVIEW.md` at CP3. Closes §5.13 ◐ → ✅.

**Architecture:** A straight twin of `reel-brief`: the typed contract in `scripts/lib/review.py` (`Finding` + `Review` dataclasses, validate-and-raise in `__post_init__`, `Review.verdict` computed property, JSON round-trip, `to_markdown`); the thin driver in `scripts/reel_review.py` (`build_review` validates the reviewer's **raw** findings JSON into a typed `Review`, `write_review` emits both files, argparse CLI) — the `selection.json → EDL.json` idiom (agent authors raw, driver validates+writes); `SKILLS/reel-review/SKILL.md` + `reel-reviewer.md` (dispatch a fresh reviewer subagent with a crafted packet, run the driver, surface `REVIEW.md` to the human, route findings to existing fixer stages) — the `requesting-code-review` calque. An optional `montage.py` `reel-review` Stage marks a reviewed reel. No ffmpeg — a text stage, no real-ffmpeg golden (like reel-brief). Human-gated (§4.1 CP3 stays human); `check_reel`/`build_reel`/`deliver`/loop-2 untouched.

**Tech Stack:** Python 3.13, dataclasses, argparse, pytest. Runs as modules (`pythonpath = .`, `.venv/bin/python -m ...`).

**Spec:** `docs/specs/2026-07-18-reel-review-editorial-design.md`.

**Conventions (all tasks):** Imports at module top. Every module-level def fully typed. Config-specs validate-and-raise in `__post_init__` with `ValueError`-with-remedy (name the value + allowed set), never a bare `KeyError`/`TypeError`. `from_dict` guards a non-dict top level first (the `Spec.from_dict` rule). Whole-object asserts where practical. All commits end with the trailer:
```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```
Run the suite without piping through `tail` (masks exit code): `.venv/bin/python -m pytest ... ; echo "EXIT: $?"`.

---

### Task 0: `Finding` config-spec — vocabs + fields + validation + JSON round-trip

**Files:**
- Create: `scripts/lib/review.py`
- Test: `tests/lib/test_review.py`

- [ ] **Step 1: Write the failing tests** (`tests/lib/test_review.py`)

```python
import pytest

from scripts.lib.review import (REVIEW_AXES, REVIEW_CONFIDENCE, REVIEW_ROUTES,
                                REVIEW_SEVERITY, Finding)

GOOD = dict(axis="hook", severity="important", evidence="ep0 opens on a slow pan",
            route="edit-plan", suggestion="open on the jump-cut instead")


def test_finding_accepts_good():
    f = Finding(**GOOD)
    assert f.axis == "hook" and f.severity == "important" and f.confidence == "high"


def test_finding_rejects_bad_axis():
    with pytest.raises(ValueError, match="axis"):
        Finding(**{**GOOD, "axis": "vibe"})


def test_finding_rejects_bad_severity():
    with pytest.raises(ValueError, match="severity"):
        Finding(**{**GOOD, "severity": "critical"})


def test_finding_rejects_empty_evidence():
    with pytest.raises(ValueError, match="evidence"):
        Finding(**{**GOOD, "evidence": "  "})


def test_finding_rejects_bad_route():
    with pytest.raises(ValueError, match="route"):
        Finding(**{**GOOD, "route": "rerender"})


def test_finding_rejects_empty_suggestion():
    with pytest.raises(ValueError, match="suggestion"):
        Finding(**{**GOOD, "suggestion": ""})


def test_finding_rejects_bad_confidence():
    with pytest.raises(ValueError, match="confidence"):
        Finding(**{**GOOD, "confidence": "sure"})


def test_finding_from_dict_non_dict_raises_clean():
    with pytest.raises(ValueError, match="Finding.from_dict"):
        Finding.from_dict(["not", "a", "dict"])


def test_finding_from_dict_missing_required_raises():
    with pytest.raises(ValueError, match="axis"):
        Finding.from_dict({"severity": "minor", "evidence": "x", "route": "none", "suggestion": "y"})


def test_finding_roundtrip_to_from_dict():
    f = Finding(**{**GOOD, "confidence": "low"})
    assert Finding.from_dict(f.to_dict()).to_dict() == f.to_dict()


def test_vocab_constants_are_the_allowed_sets():
    assert REVIEW_AXES == ("idea", "mood", "hook", "ending", "spine",
                           "edl_completeness", "trend_flavor")
    assert REVIEW_SEVERITY == ("blocking", "important", "minor")
    assert REVIEW_ROUTES == ("edit-plan", "pacing", "music", "reprocess", "titles", "none")
    assert REVIEW_CONFIDENCE == ("high", "medium", "low")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_review.py -q ; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.review'`.

- [ ] **Step 3: Implement `scripts/lib/review.py`** (`Finding` + vocabs; `Review` lands in Task 1)

```python
"""Reel-review: the §5.13 editorial verdict (design
docs/specs/2026-07-18-reel-review-editorial-design.md, Slice B). A fresh reviewer
subagent judges the delivered reel against SPEC and emits typed findings; this module
is the contract those findings validate against. Hard config-specs — validate-and-raise
in __post_init__, JSON round-trip — like spec.py's Spec / edl.py's EDL. No ffmpeg: a
text stage; the reviewer is an agent, this module is its typed sink.
"""
import json
from dataclasses import dataclass
from pathlib import Path

REVIEW_AXES = ("idea", "mood", "hook", "ending", "spine",       # the §5.13 editorial questions
               "edl_completeness", "trend_flavor")
REVIEW_SEVERITY = ("blocking", "important", "minor")             # blocking ⇒ verdict "revise"
REVIEW_ROUTES = ("edit-plan", "pacing", "music",                # the fixer stage the human re-runs
                 "reprocess", "titles", "none")
REVIEW_CONFIDENCE = ("high", "medium", "low")                   # trend_flavor is forced "low" (no §5.4 source)


@dataclass
class Finding:
    axis: str                  # ∈ REVIEW_AXES                              (gate)
    severity: str              # ∈ REVIEW_SEVERITY                          (gate)
    evidence: str              # non-empty — cite ep idx / timestamp / signal (gate)
    route: str                 # ∈ REVIEW_ROUTES — suggested fixer stage    (gate)
    suggestion: str            # non-empty — the concrete change            (gate)
    confidence: str = "high"   # ∈ REVIEW_CONFIDENCE

    def __post_init__(self) -> None:
        if self.axis not in REVIEW_AXES:
            raise ValueError(f"Finding.axis {self.axis!r} not in {REVIEW_AXES}")
        if self.severity not in REVIEW_SEVERITY:
            raise ValueError(f"Finding.severity {self.severity!r} not in {REVIEW_SEVERITY}")
        if not (isinstance(self.evidence, str) and self.evidence.strip()):
            raise ValueError("Finding.evidence must be a non-empty string (cite the episode / "
                             "timestamp / advisory signal that grounds the finding)")
        if self.route not in REVIEW_ROUTES:
            raise ValueError(f"Finding.route {self.route!r} not in {REVIEW_ROUTES}")
        if not (isinstance(self.suggestion, str) and self.suggestion.strip()):
            raise ValueError("Finding.suggestion must be a non-empty string (the concrete change)")
        if self.confidence not in REVIEW_CONFIDENCE:
            raise ValueError(f"Finding.confidence {self.confidence!r} not in {REVIEW_CONFIDENCE}")

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        # Top level checked FIRST (the Spec.from_dict rule) — a non-dict never reaches
        # __post_init__ as a bare AttributeError out of a boundary reading agent JSON.
        if not isinstance(d, dict):
            raise ValueError(f"Finding.from_dict: expected a finding object with 'axis'/'severity'/"
                             f"'evidence'/'route'/'suggestion' fields, got {type(d).__name__} — "
                             f"re-run reel-review to regenerate the findings")
        conf = d.get("confidence")
        return cls(axis=d.get("axis"), severity=d.get("severity"), evidence=d.get("evidence"),
                   route=d.get("route"), suggestion=d.get("suggestion"),
                   confidence="high" if conf is None else conf)

    def to_dict(self) -> dict:
        return {"axis": self.axis, "severity": self.severity, "evidence": self.evidence,
                "route": self.route, "suggestion": self.suggestion, "confidence": self.confidence}
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_review.py -q ; echo "EXIT: $?"`
Expected: PASS (11 tests), EXIT: 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/review.py tests/lib/test_review.py
git commit -m "feat: Finding config-spec + vocabs (reel-review §5.13 Slice B)"
```

---

### Task 1: `Review` config-spec — fields + `verdict` property + JSON round-trip

**Files:**
- Modify: `scripts/lib/review.py` (add `Review` after `Finding`)
- Test: `tests/lib/test_review.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `tests/lib/test_review.py`)

```python
from scripts.lib.review import Review

F_IMPORTANT = Finding(**GOOD)
F_BLOCKING = Finding(axis="idea", severity="blocking", evidence="reel tells a different story",
                     route="edit-plan", suggestion="reselect windows to the SPEC idea")


def test_review_accepts_good_and_defaults():
    r = Review(reel="out/REEL_v1.mp4", findings=[F_IMPORTANT])
    assert r.reel == "out/REEL_v1.mp4" and r.findings == (F_IMPORTANT,)
    assert r.summary == "" and r.platform == "" and r.spec_ref == "" and r.reviewer == ""


def test_review_rejects_empty_reel():
    with pytest.raises(ValueError, match="reel"):
        Review(reel="  ", findings=[F_IMPORTANT])


def test_review_rejects_raw_dict_finding():
    with pytest.raises(ValueError, match="findings"):
        Review(reel="out/REEL_v1.mp4", findings=[{"axis": "hook"}])


def test_verdict_approve_without_blocking():
    assert Review(reel="r.mp4", findings=[F_IMPORTANT]).verdict == "approve"


def test_verdict_revise_with_blocking():
    assert Review(reel="r.mp4", findings=[F_IMPORTANT, F_BLOCKING]).verdict == "revise"


def test_verdict_approve_when_empty():
    assert Review(reel="r.mp4").verdict == "approve"


def test_review_roundtrip_recomputes_verdict():
    r = Review(reel="out/REEL_v1.mp4", findings=[F_BLOCKING], summary="s", platform="tiktok")
    d = r.to_dict()
    assert d["verdict"] == "revise"
    d["verdict"] = "approve"                      # a lying stored verdict is ignored on load
    assert Review.from_dict(d).verdict == "revise"
    assert Review.from_dict(r.to_dict()).to_dict() == r.to_dict()


def test_review_from_json_corrupt_raises(tmp_path):
    p = tmp_path / "REVIEW.json"
    p.write_text("{not json")
    with pytest.raises(ValueError, match="corrupt"):
        Review.from_json(p)


def test_review_write_then_from_json(tmp_path):
    r = Review(reel="out/REEL_v1.mp4", findings=[F_IMPORTANT], summary="ok")
    p = tmp_path / "REVIEW.json"
    r.write(p)
    assert Review.from_json(p).to_dict() == r.to_dict()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_review.py -k review -q ; echo "EXIT: $?"`
Expected: FAIL — `ImportError: cannot import name 'Review' from 'scripts.lib.review'`.

- [ ] **Step 3: Add `Review` to `scripts/lib/review.py`** (after `Finding`)

```python
@dataclass
class Review:
    reel: str                  # path to the reviewed cut (out/REEL_v{n}.mp4); non-empty (gate)
    findings: tuple = ()       # tuple[Finding, ...] — build via reel_review.build_review (gate)
    summary: str = ""          # the reviewer's one-paragraph overall read
    spec_ref: str = ""         # echo of the intent judged (or the SPEC.json path)
    platform: str = ""         # from SPEC.platform, header only
    reviewer: str = ""         # free note — which agent/model reviewed

    def __post_init__(self) -> None:
        if not (isinstance(self.reel, str) and self.reel.strip()):
            raise ValueError("Review.reel must be a non-empty string (the reviewed reel path)")
        if not (isinstance(self.findings, (tuple, list))
                and all(isinstance(f, Finding) for f in self.findings)):
            raise ValueError("Review.findings must be a list of Finding objects "
                             "(build via reel_review.build_review, which validates each)")
        self.findings = tuple(self.findings)
        for name in ("summary", "spec_ref", "platform", "reviewer"):
            v = getattr(self, name)
            if not isinstance(v, str):
                raise ValueError(f"Review.{name} must be a string, got {v!r}")

    @property
    def verdict(self) -> str:
        """revise iff any blocking finding, else approve. A computed property, never a
        stored field — one source of truth, so a hand-edited REVIEW.json cannot lie about
        its own verdict. Advisory to the human: an approve with important findings is
        'approve with notes'; a human may waive a blocking finding and approve anyway."""
        return "revise" if any(f.severity == "blocking" for f in self.findings) else "approve"

    @classmethod
    def from_dict(cls, d: dict) -> "Review":
        if not isinstance(d, dict):
            raise ValueError(f"Review.from_dict: expected a REVIEW.json object with a 'reel' field "
                             f"and a 'findings' list, got {type(d).__name__} — re-run reel-review")
        raw = d.get("findings") or []
        if not isinstance(raw, (tuple, list)):
            raise ValueError(f"Review.findings must be a JSON list, got {type(raw).__name__}")
        findings = tuple(Finding.from_dict(f) for f in raw)   # an incoming 'verdict' is ignored (recomputed)

        def opt(key: str, default: object) -> object:
            v = d.get(key)
            return default if v is None else v
        return cls(reel=d.get("reel"), findings=findings, summary=opt("summary", ""),
                   spec_ref=opt("spec_ref", ""), platform=opt("platform", ""),
                   reviewer=opt("reviewer", ""))

    def to_dict(self) -> dict:
        # verdict is emitted for the .md/.json readers but recomputed on load (never trusted)
        return {"reel": self.reel, "verdict": self.verdict,
                "findings": [f.to_dict() for f in self.findings], "summary": self.summary,
                "spec_ref": self.spec_ref, "platform": self.platform, "reviewer": self.reviewer}

    @classmethod
    def from_json(cls, path: str | Path) -> "Review":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is corrupt ({e}) — re-run reel-review to regenerate it") from e
        return cls.from_dict(d)

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_review.py -q ; echo "EXIT: $?"`
Expected: PASS (20 tests), EXIT: 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/review.py tests/lib/test_review.py
git commit -m "feat: Review config-spec + verdict property (reel-review §5.13 Slice B)"
```

---

### Task 2: `Review.to_markdown()` — the `REVIEW.md` render (blocking-first)

**Files:**
- Modify: `scripts/lib/review.py` (add method to `Review`, after `write`)
- Test: `tests/lib/test_review.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `tests/lib/test_review.py`)

```python
def test_to_markdown_approve_header_and_summary():
    r = Review(reel="out/REEL_v1.mp4", findings=[F_IMPORTANT], summary="delivers the calm idea",
               platform="tiktok")
    md = r.to_markdown()
    assert md.startswith("# Reel review — ✅ approve · tiktok")
    assert "delivers the calm idea" in md
    assert "**[important] hook** → `edit-plan`" in md
    assert "open on the jump-cut instead" in md


def test_to_markdown_revise_orders_blocking_first():
    r = Review(reel="r.mp4", findings=[F_IMPORTANT, F_BLOCKING])
    md = r.to_markdown()
    assert md.startswith("# Reel review — 🔧 revise")
    assert md.index("[blocking] idea") < md.index("[important] hook")   # severity order, not input order


def test_to_markdown_empty_findings_is_clean():
    md = Review(reel="r.mp4", summary="clean").to_markdown()
    assert "✅ No findings" in md
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_review.py -k to_markdown -q ; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: 'Review' object has no attribute 'to_markdown'`.

- [ ] **Step 3: Add `to_markdown` to `Review`** (in `scripts/lib/review.py`, after `write`)

```python
    def to_markdown(self) -> str:
        icon = {"approve": "✅", "revise": "🔧"}[self.verdict]
        head = f"# Reel review — {icon} {self.verdict}"
        if self.platform:
            head += f" · {self.platform}"
        lines = [head, "", f"**Reel:** `{self.reel}`", ""]
        if self.summary:
            lines += [self.summary, ""]
        if not self.findings:
            lines.append("✅ No findings — the reel delivers the brief.")
            return "\n".join(lines)
        order = {"blocking": 0, "important": 1, "minor": 2}
        for f in sorted(self.findings, key=lambda f: order[f.severity]):
            lines.append(f"- **[{f.severity}] {f.axis}** → `{f.route}` (confidence: {f.confidence})")
            lines.append(f"  - {f.evidence}")
            lines.append(f"  - **Fix:** {f.suggestion}")
        return "\n".join(lines)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_review.py -q ; echo "EXIT: $?"`
Expected: PASS (23 tests), EXIT: 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/review.py tests/lib/test_review.py
git commit -m "feat: Review.to_markdown REVIEW.md render (reel-review §5.13 Slice B)"
```

---

### Task 3: `reel_review.py` — `build_review` + `write_review`

**Files:**
- Create: `scripts/reel_review.py`
- Test: `tests/test_reel_review.py`

- [ ] **Step 1: Write the failing tests** (`tests/test_reel_review.py`)

```python
import pytest

from scripts.lib.review import Review
from scripts.reel_review import build_review, write_review

RAW = [
    {"axis": "hook", "severity": "important", "evidence": "ep0 is a slow pan",
     "route": "edit-plan", "suggestion": "open on the jump-cut in ep2"},
    {"axis": "mood", "severity": "minor", "evidence": "track brighter than SPEC.mood",
     "route": "music", "suggestion": "pick a warmer cue", "confidence": "medium"},
]


def test_build_review_validates_and_sets_verdict():
    r = build_review(RAW, "out/REEL_v1.mp4", summary="delivers the calm idea")
    assert isinstance(r, Review) and r.verdict == "approve"   # no blocking finding
    assert len(r.findings) == 2 and r.findings[0].axis == "hook"
    assert r.summary == "delivers the calm idea"


def test_build_review_blocking_gives_revise():
    raw = [{"axis": "idea", "severity": "blocking", "evidence": "reel is a different story",
            "route": "edit-plan", "suggestion": "reselect windows to the SPEC idea"}]
    assert build_review(raw, "out/REEL_v1.mp4").verdict == "revise"


def test_build_review_rejects_bad_finding_writes_nothing():
    bad = [{"axis": "bogus", "severity": "minor", "evidence": "x", "route": "none", "suggestion": "y"}]
    with pytest.raises(ValueError, match="axis"):
        build_review(bad, "out/REEL_v1.mp4")


def test_build_review_rejects_non_list_findings():
    with pytest.raises(ValueError, match="list"):
        build_review({"axis": "hook"}, "out/REEL_v1.mp4")


def test_build_review_empty_findings_approves():
    r = build_review([], "out/REEL_v1.mp4")
    assert r.verdict == "approve" and r.findings == ()


def test_write_review_emits_both_files(tmp_path):
    r = build_review(RAW, "out/REEL_v1.mp4", platform="tiktok")
    res = write_review(r, str(tmp_path))
    assert res["status"] == "written" and res["verdict"] == "approve" and res["findings"] == 2
    assert (tmp_path / "REVIEW.json").exists() and (tmp_path / "REVIEW.md").exists()
    assert Review.from_json(tmp_path / "REVIEW.json").to_dict() == r.to_dict()
    assert (tmp_path / "REVIEW.md").read_text().startswith("# Reel review —")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_reel_review.py -q ; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.reel_review'`.

- [ ] **Step 3: Implement `scripts/reel_review.py`** (driver half; CLI lands in Task 4)

```python
"""Reel-review writer (design docs/specs/2026-07-18-reel-review-editorial-design.md,
§5.13 Slice B). The thin mechanical half: validate the reviewer subagent's RAW findings
JSON into a typed Review (fail-loud on a malformed finding), write REVIEW.json + REVIEW.md.
Judgment (the editorial verdict) is the reviewer subagent's, dispatched by
SKILLS/reel-review/SKILL.md. Mirror of reel_brief.py / edit_plan.py — contract in lib,
driver here; the raw-findings → typed-artifact idiom is edit_plan's selection.json → EDL.json.
"""
import argparse
import json
from pathlib import Path

from scripts.lib.review import Finding, Review


def build_review(raw_findings: list, reel: str, *, summary: str = "", spec_ref: str = "",
                 platform: str = "", reviewer: str = "") -> Review:
    """Validate a list of raw finding dicts (the reviewer subagent's output) into a typed
    Review. A malformed finding raises here (nothing is written) — the reviewer never writes
    REVIEW.json directly, so a bad finding fails loud at this boundary, not silently."""
    if not isinstance(raw_findings, (tuple, list)):
        raise ValueError(f"build_review: findings must be a list, got {type(raw_findings).__name__} "
                         f"— the reviewer writes a JSON list of finding objects")
    findings = tuple(f if isinstance(f, Finding) else Finding.from_dict(f) for f in raw_findings)
    return Review(reel=reel, findings=findings, summary=summary, spec_ref=spec_ref,
                  platform=platform, reviewer=reviewer)


def write_review(review: Review, out_dir: str) -> dict:
    """Write REVIEW.json + REVIEW.md together into out_dir. Returns a status dict."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    rj, rm = Path(out_dir) / "REVIEW.json", Path(out_dir) / "REVIEW.md"
    review.write(rj)
    rm.write_text(review.to_markdown())
    return {"status": "written", "verdict": review.verdict, "findings": len(review.findings),
            "review": str(rj), "md": str(rm)}
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_reel_review.py -q ; echo "EXIT: $?"`
Expected: PASS (6 tests), EXIT: 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/reel_review.py tests/test_reel_review.py
git commit -m "feat: reel_review build_review + write_review (§5.13 Slice B)"
```

---

### Task 4: `reel_review` CLI — `build` subcommand

**Files:**
- Modify: `scripts/reel_review.py` (add `_load_findings` + `main` + `__main__` guard)
- Test: `tests/test_reel_review.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_reel_review.py`)

```python
import json
import sys


def _write_findings(tmp_path, obj):
    p = tmp_path / "review_findings.json"
    p.write_text(json.dumps(obj))
    return str(p)


def test_cli_build_writes_and_exits_0(tmp_path, monkeypatch, capsys):
    from scripts import reel_review
    findings = _write_findings(tmp_path, {"summary": "good", "findings": RAW})
    monkeypatch.setattr(sys, "argv",
                        ["reel_review", "build", "--findings", findings,
                         "--reel", "out/REEL_v1.mp4", "--platform", "tiktok",
                         "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        reel_review.main()
    assert e.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "written" and payload["findings"] == 2
    r = Review.from_json(tmp_path / "REVIEW.json")
    assert r.verdict == "approve" and r.summary == "good" and r.platform == "tiktok"


def test_cli_accepts_bare_list_findings(tmp_path, monkeypatch, capsys):
    from scripts import reel_review
    findings = _write_findings(tmp_path, RAW)   # bare list, no summary object
    monkeypatch.setattr(sys, "argv",
                        ["reel_review", "build", "--findings", findings,
                         "--reel", "out/REEL_v1.mp4", "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        reel_review.main()
    assert e.value.code == 0
    assert Review.from_json(tmp_path / "REVIEW.json").summary == ""


def test_cli_bad_findings_json_fails_loud(tmp_path, monkeypatch):
    from scripts import reel_review
    p = tmp_path / "review_findings.json"
    p.write_text("{not json")
    monkeypatch.setattr(sys, "argv",
                        ["reel_review", "build", "--findings", str(p),
                         "--reel", "out/REEL_v1.mp4", "--out-dir", str(tmp_path)])
    with pytest.raises(ValueError, match="valid JSON"):
        reel_review.main()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_reel_review.py -k cli -q ; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: module 'scripts.reel_review' has no attribute 'main'`.

- [ ] **Step 3: Add `_load_findings` + the CLI** (append to `scripts/reel_review.py`)

```python
def _load_findings(path: str) -> tuple[list, str]:
    """Load the reviewer's raw findings file. Two accepted shapes:
      {"summary": "...", "findings": [ {...}, ... ]}   (preferred — carries the overall read)
      [ {...}, ... ]                                    (bare list, no summary)
    Returns (raw_findings_list, summary_str)."""
    try:
        data = json.loads(Path(path).read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON ({e}) — the reviewer must write a findings "
                         f"list or a {{'summary','findings'}} object") from e
    if isinstance(data, dict):
        return data.get("findings") or [], data.get("summary") or ""
    if isinstance(data, list):
        return data, ""
    raise ValueError(f"{path}: expected a findings list or a {{'summary','findings'}} object, "
                     f"got {type(data).__name__}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="write REVIEW.json + REVIEW.md — the editorial reel review (§5.13 Slice B)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="validate the reviewer's raw findings -> REVIEW.json + REVIEW.md")
    b.add_argument("--findings", required=True,
                   help="the reviewer subagent's raw findings JSON (list or {summary,findings})")
    b.add_argument("--reel", required=True, help="the reviewed reel path (e.g. out/REEL_v1.mp4)")
    b.add_argument("--spec", default="", help="SPEC.json path or a short intent echo (spec_ref)")
    b.add_argument("--platform", default="", help="platform label for the report header")
    b.add_argument("--reviewer", default="", help="free note — which agent/model reviewed")
    b.add_argument("--out-dir", required=True, help="dir for REVIEW.json + REVIEW.md")
    a = ap.parse_args()
    raw, summary = _load_findings(a.findings)
    review = build_review(raw, a.reel, summary=summary, spec_ref=a.spec,
                          platform=a.platform, reviewer=a.reviewer)
    result = write_review(review, a.out_dir)
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify they pass** (and the module runs end-to-end)

Run: `.venv/bin/python -m pytest tests/test_reel_review.py -q ; echo "EXIT: $?"`
Expected: PASS (9 tests), EXIT: 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/reel_review.py tests/test_reel_review.py
git commit -m "feat: reel_review CLI build subcommand (§5.13 Slice B)"
```

---

### Task 5: `montage.py` — optional `reel-review` Stage + test patch

**Files:**
- Modify: `scripts/montage.py:53-55` (add the Stage after `deliver`)
- Test: `tests/lib/test_montage.py` (patch structural assertions + add optional case)

- [ ] **Step 1: Patch the montage tests to the new expectation**

In `tests/lib/test_montage.py`, edit `test_v1_stages_order_and_keys` — append `"reel-review"` after `"deliver"`:

```python
def test_v1_stages_order_and_keys():
    assert [s.key for s in V1_STAGES] == [
        "project-init", "footage-intake", "reel-brief", "trend-scan",
        "music-and-mood", "pacing", "edit-plan", "assemble-draft", "titles",
        "deliver", "reel-review"]
```

In `test_v1_stages_kinds_and_flags`, add reel-review assertions (after the `titles` block, before the `deliver` line):

```python
    assert by["reel-review"].kind == "optional"
    assert by["reel-review"].artifact == "REVIEW.json"
    assert by["reel-review"].checkpoint == "final"
    assert by["reel-review"].in_out is False
```

Append a new optional-state case (after `test_titles_optional_absent_then_present`):

```python
def test_reel_review_optional_absent_then_present(tmp_path):
    # review runs AFTER deliver; it is optional and never blocks `next`
    for n in ("project.json", "FOOTAGE.json", "EDL.json"):
        _touch(tmp_path, n)
    out = tmp_path / "out"
    out.mkdir()
    (out / "REEL_v1.mp4").write_text("x")
    res = next_action(str(tmp_path))
    assert res["delivered"] is True and res["next"] is None
    assert _state(res, "reel-review") == "optional"   # absent optional never blocks
    _touch(tmp_path, "REVIEW.json")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "reel-review") == "done"
    assert res2["next"] is None                        # still nothing required outstanding
```

- [ ] **Step 2: Run to verify the patched tests fail against current code**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q ; echo "EXIT: $?"`
Expected: FAIL — `V1_STAGES` has no `reel-review` key; the order list and the kinds assertions mismatch.

- [ ] **Step 3: Add the Stage in `scripts/montage.py`**

After the `deliver` Stage (line 53-54), add a final row inside `V1_STAGES` (review happens **after** delivery):

```python
    Stage("deliver", "REEL_v*.*", "required",
          "edl_to_reel CLI", "final", in_out=True),
    Stage("reel-review", "REVIEW.json", "optional",
          "reel-review SKILL -> reel_review build CLI (editorial CP3 review)", "final"),
```

(`reel-review` reads the run dir, not the out dir — `in_out` stays the default `False`; its `REVIEW.json` lands beside `SPEC.json`/`EDL.json`.)

- [ ] **Step 4: Run the montage suite**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q ; echo "EXIT: $?"`
Expected: PASS (all montage tests), EXIT: 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/montage.py tests/lib/test_montage.py
git commit -m "feat: router adds optional reel-review Stage (REVIEW.json, CP3) (§5.13 Slice B)"
```

---

### Task 6: `SKILLS/reel-review/` + `using-montage` CP3 wiring

**Files:**
- Create: `SKILLS/reel-review/SKILL.md`
- Create: `SKILLS/reel-review/reel-reviewer.md`
- Modify: `SKILLS/using-montage/SKILL.md`

No pytest (SKILLs are prose). The gate is the full-suite green check (Task 7) + the final review.

- [ ] **Step 1: Write `SKILLS/reel-review/SKILL.md`**

```markdown
---
name: reel-review
description: Stage 5.13 editorial half (Slice B) — the reel's final editorial review. Use at Checkpoint 3, after edl_to_reel delivers out/REEL_v{n}.mp4, to judge whether the reel delivers SPEC's idea/mood/hook/ending/spine (and anything from the EDL missing/weak). Dispatch a fresh reviewer subagent with a crafted context packet, validate its findings into REVIEW.json + REVIEW.md, surface them beside the reel, and route the ones the human picks to the fixer stage (edit-plan/pacing/music). Human-gated — the reviewer proposes, the human disposes.
---

# reel-review (stage 5.13, editorial half)

## Overview

The **final editorial gate**. `check_reel` already judged the reel *mechanically*
(black/loudness/colour/variety/length + the advisory safe_zones/key_action/
pad_bars/transitions/beat). reel-review judges it *editorially*: does it deliver
the brief? This is the `requesting-code-review` pattern one level up — you
dispatch a **fresh reviewer subagent** with a crafted packet, it returns typed
findings, and the **human** decides what to act on at Checkpoint 3.

**Core principle:** fresh eyes, typed findings, human disposes. You built the reel
(or conducted its build), so you are anchored — a fresh subagent, given only the
artifacts, reviews without that bias. The verdict is advisory; the CP3 gate is the
human's sign-off.

## When to Use

At **Checkpoint 3**, once `out/REEL_v{n}.mp4` exists and `check_reel` has run. Not
before delivery (there is no reel to judge). Re-run it after any fix round (a new
cut is a new review).

## Inputs (the context packet — resolve paths under the run dir)

- **`out/REEL_v{n}.mp4`** (required) — the delivered reel.
- **`report.json`** (required) — `check_reel`'s report: the mechanical gates + the
  **Slice A advisory signals** (`key_action`/`pad_bars`/`transitions`/`safe_zones`/
  `beat`) the reviewer cites as evidence.
- **`SPEC.json`** (optional) — the brief's intent. Absent (a bare autonomous run) →
  review against the `EDL` + the run's stated intent; say so.
- **`EDL.md`** (required) — the realized plan (per-episode source/window/shot/
  layout/comp/motion/beat/notes).
- **`MUSIC.json` / `PACING.json`** (optional) — the mood target + energy spine.

## Procedure

Announce on entry: **"Using reel-review to judge the reel against the brief."**

1. **Build the packet.** Resolve the paths above. Grab a cheap **thumbnail
   contact-sheet** to ground visual judgement (output-seek — `-ss` AFTER `-i`,
   design §12): the hook frame, the ending frame, and one mid-frame per episode.
   Example (hook + ending stills; add per-episode mids from the EDL cut times):

       ffmpeg -y -i out/REEL_v1.mp4 -ss 0.5 -frames:v 1 <run>/_review/hook.png
       ffmpeg -y -i out/REEL_v1.mp4 -ss "$(python -c 'print(DUR-1)')" -frames:v 1 <run>/_review/ending.png

2. **Dispatch the reviewer subagent** (Task tool, `general-purpose`) with the
   `reel-reviewer.md` template filled in — the packet paths + the axes/questions +
   the required output shape. It writes `<run>/review_findings.json` and returns.
   Do NOT review inline — the dispatch is the point (fresh, unanchored eyes).

3. **Validate + write.** Turn the raw findings into the typed artifact:

       python -m scripts.reel_review build \
         --findings <run>/review_findings.json \
         --reel out/REEL_v{n}.mp4 \
         --spec <run>/SPEC.json --platform <platform> \
         --out-dir <run>

   The driver validates every finding (a malformed one raises — fix the reviewer's
   output and re-run; never hand-write `REVIEW.json`) and writes `REVIEW.json` +
   `REVIEW.md`.

4. **Surface to the human — CP3.** Present `REVIEW.md` **beside** the reel and the
   `check_reel` report. Read back the verdict (approve / revise) and the findings.

5. **The human disposes.** For each finding the human chooses to act on, re-run the
   **routed** stage (the map below); it regenerates the reel (a new
   `REEL_v{n+1}.mp4`). Then **re-review** (step 1) — the loop ends when the human
   **approves** (verdict `approve`, or every remaining finding waived).

## Routing map (finding.route → the stage the human re-runs)

reel-review builds **no fixer** — each `route` names a stage that already exists:

| route | re-run | typical finding |
|-------|--------|-----------------|
| `edit-plan` | edit-plan SKILL (edit `selection.json`, rebuild `EDL`) | weak hook / weak ending / missing EDL element / classic↔trend lean |
| `pacing` | pacing SKILL then `edit_plan build --pacing` | cuts drift off the energy spine |
| `music` | music-match / music-source SKILL | mood mismatch / wrong track |
| `reprocess` | process_episode on one episode (grade/layout redo) | one episode reads wrong vs the reel |
| `titles` | titles SKILL | hook/ending wants on-screen text |
| `none` | — (note only) | an observation to record, no action |

Same rule `using-montage` already applies to a mechanical `stop_and_report`:
"route it to the culprit stage's skill." reel-review extends it to editorial findings.

## Gate

The §5.13 editorial gate is the **human's CP3 sign-off** — never an automated
block. `REVIEW.json` records the reviewer's findings + verdict; the human approving
(or waiving) is what greens the stage.

## Boundaries

- **Human-gated (§4.1).** Nothing auto-fixes on these findings; the human picks and
  re-runs. `check_reel`/`build_reel`/`deliver`/loop-2 are untouched.
- **`trend_flavor` has no source of truth until §5.4 trend-scan.** The reviewer
  judges it from general knowledge at forced `confidence: low`, never `blocking`,
  and names §5.4 in the evidence.
- **Judgement over plan + signals + stills, not full playback** — the reviewer says
  so in its `summary`.
- **One reviewer, one reel per run.** A multi-perspective panel and cross-reel
  comparison are deferred. You never hand-edit `REVIEW.json` — the driver
  regenerates it from the reviewer's findings.
```

- [ ] **Step 2: Write `SKILLS/reel-review/reel-reviewer.md`** (the reviewer subagent prompt template)

```markdown
# Reel Editorial Reviewer Prompt Template

Fill in the placeholders and dispatch with the Task tool (`general-purpose`).

```
You are a fresh editorial reviewer for a short vertical video reel. You did NOT
build this reel — judge only what the artifacts show. Your final message is not
read by a human; your deliverable is the file you write.

## The brief (intent)
{SPEC_SUMMARY — paste the SPEC.md / SPEC.json intent: idea, mood, hook, ending,
 style_lean, length, platform. If none exists, say "no SPEC — judge against the EDL
 + this stated intent: {INTENT}".}

## The realized plan
{EDL_MD — paste EDL.md: per-episode source/window/shot/layout/comp/motion/beat/notes.}

## Mechanical + advisory signals (check_reel report.json)
{REPORT_JSON — paste report.json. The advisory signals key_action / pad_bars /
 transitions / safe_zones / beat are yours to cite as evidence.}

## Music / pacing (if present)
{MUSIC_JSON / PACING_JSON — mood_features + the energy spine, or "silent reel".}

## The reel + stills
The reel is at {REEL_PATH}. Contact-sheet stills: {STILL_PATHS} (hook, ending,
per-episode mids). You judge over the plan + signals + stills, NOT full playback —
say so in your summary.

## Judge each axis; emit a finding ONLY where the reel falls short
- idea             — delivers the brief's original idea?         (SPEC.idea vs the EDL arc)
- mood             — mood/story land?                            (SPEC.mood vs MUSIC mood_features; the stills)
- hook             — opening strong, first ~1–3s?                (ep0 shot/layout/description + hook still)
- ending           — ending right, last ~3s?                    (last-ep + ending still + SPEC.ending)
- spine            — cuts along the energy spine?                (PACING slots vs EDL beat_slot/dur; beat advisory)
- edl_completeness — anything from the EDL missing/weak?         (EDL episodes vs SPEC; variety/transitions signals)
- trend_flavor     — classic base AND trend flavor?              (general knowledge — NO source of truth)

## Rules
- severity ∈ (blocking, important, minor). blocking = the reel does NOT deliver the brief.
- route ∈ (edit-plan, pacing, music, reprocess, titles, none) — the fixer stage to re-run.
- confidence ∈ (high, medium, low).
- trend_flavor: ALWAYS confidence "low", NEVER blocking, and name §5.4 (no TRENDS.md source) in evidence.
- evidence must cite a concrete anchor (episode idx / timestamp / which signal).

## Write your output to {FINDINGS_PATH} as JSON, then stop:
{
  "summary": "<one paragraph: does it deliver the brief? name the plan+signals+stills boundary>",
  "findings": [
    {"axis": "hook", "severity": "important", "evidence": "...", "route": "edit-plan",
     "suggestion": "...", "confidence": "high"}
  ]
}
An empty "findings" list means the reel delivers the brief.
```
```

- [ ] **Step 3: Wire `reel-review` into `SKILLS/using-montage/SKILL.md`**

(a) Overview stage list — line 3 (the `description:` frontmatter) and line 13's prose chain, append `-> [reel-review]` after `edl_to_reel`:
`... -> edl_to_reel -> [reel-review])`.

(b) In step 10 (the `edl_to_reel` / "Checkpoint 3 — final review" step, ~line 130-135), append to the Checkpoint-3 sentence:

```markdown
    Then invoke the **reel-review** skill — it dispatches a fresh reviewer subagent
    that judges the reel against `SPEC` (idea/mood/hook/ending/spine) and writes
    `REVIEW.json` + `REVIEW.md`; present `REVIEW.md` alongside the reel and the
    `check_reel` report. For each finding the user chooses to act on, re-run the
    routed stage (`edit-plan`/`pacing`/`music`/`titles`) — never fix the reel
    forward — then re-review the new cut. reel-review is the §5.13 editorial half;
    on a bare autonomous run it still runs, judging against the `EDL`.
```

(c) Boundaries — the three-checkpoints bullet (~line 155-156): note that CP3's review mechanism is the reel-review skill (editorial), complementing `check_reel` (mechanical).

(d) Boundaries — the deferred/optional-stages bullet (~line 157-166): add a sentence — `reel-review (§5.13 editorial half) runs at CP3 after deliver; it is optional in montage status (never `next`) and human-gated (the reviewer proposes, you dispose).`

- [ ] **Step 4: Verify the full suite still green** (no code changed here, but confirm nothing references the SKILL text in tests)

Run: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`
Expected: PASS (all), EXIT: 0.

- [ ] **Step 5: Commit**

```bash
git add SKILLS/reel-review/SKILL.md SKILLS/reel-review/reel-reviewer.md SKILLS/using-montage/SKILL.md
git commit -m "feat: reel-review SKILL + reviewer template + using-montage CP3 wiring (§5.13 Slice B)"
```

---

### Task 7: Docs sync + full suite + final whole-slice review

**Files:**
- Modify: `docs/pipeline-map.md`, `docs/build-status.md`, `docs/specs/2026-07-05-montage-skillset-design.md`, `CLAUDE.md`

- [ ] **Step 1: `docs/pipeline-map.md`** — flip 5.13 to built.

In the 16-stage table (row 5.13), change status `◐ → ✅` and append to the note:
`Editorial half ✅ (2026-07-18) — reel-review SKILL dispatches a fresh reviewer subagent → typed REVIEW.json (Finding/Review), human-gated at CP3.` Remove "the stage stays ◐" wording.

In the remaining-work table (row 5.13), change `St` `◐ → ✅` and `Left to build` to `— (2026-07-18)`.

Update the **Tally** line `**Tally:** 14 ✅ · 1 ◐ · 1 ❌.` → `**Tally:** 15 ✅ · 0 ◐ · 1 ❌.` (the ❌ is §5.4 trend-scan). Update the surrounding prose sentence that names "5.13's editorial half" as open — it is now built.

In the "Phase roadmap → Upcoming", tick the **"Editorial reel-final"** item (`- [ ]` → `- [x]`) and rewrite its body: the mechanical half + the agent review are both built; the `trend_flavor` sub-criterion is judged at low confidence pending §5.4. Update the "Genuinely open on the quality side" sentence to drop 5.13 (leaving the two pacing auto-fixes).

- [ ] **Step 2: `docs/build-status.md`** — append to the Done section (chronological, newest last):

```markdown
- **reel-review editorial (§5.13 Slice B) DONE (2026-07-18)** — plan
  `docs/plans/2026-07-18-reel-review-editorial.md` + design
  `docs/specs/2026-07-18-reel-review-editorial-design.md`. **Closes §5.13** — both
  parts green, stage ◐ → ✅ (tally 15 ✅ · 0 ◐ · 1 ❌). The agent editorial review:
  at CP3 a fresh reviewer subagent judges the delivered reel against `SPEC`
  (idea/mood/hook/ending/spine/edl_completeness/trend_flavor) and emits typed
  findings, each routed to an existing fixer stage; the human disposes.
  `scripts/lib/review.py` — `Finding` + `Review` config-specs (`REVIEW_AXES`/
  `REVIEW_SEVERITY`/`REVIEW_ROUTES`/`REVIEW_CONFIDENCE` vocabs, `Review.verdict`
  computed property = revise iff any blocking, JSON round-trip, `to_markdown`
  blocking-first). `scripts/reel_review.py` — thin driver: `build_review` validates
  the reviewer's RAW findings (fail-loud on a malformed finding, nothing written) →
  typed `Review`, `write_review` → `REVIEW.json`+`REVIEW.md`, CLI `build`
  (`--findings` list-or-`{summary,findings}` → artifact) — the `selection.json →
  EDL.json` idiom. `SKILLS/reel-review/` — the SKILL (build packet → dispatch
  reviewer → driver → human loop + routing) + `reel-reviewer.md` prompt template
  (the `requesting-code-review` calque); `montage.py` gains an **optional**
  `reel-review` Stage (`REVIEW.json`, checkpoint `final`, never `next`);
  `using-montage` CP3 invokes it. **Human-gated (§4.1)** — `check_reel`/`build_reel`/
  `deliver`/loop-2 untouched; no auto-fix actuator. **`trend_flavor`** is judged
  from general knowledge at forced `confidence=low` (no source until §5.4). Text
  stage — no ffmpeg golden (reel-brief's twin). NN new unit tests; full suite green.
```

(Replace `NN` with the actual new-test count from Task 7 Step 5's run; state the full total.)

Update the "Next action" pointer: §5.13 is closed; the genuinely-open quality items are the two pacing auto-fixes and §5.4 trend-scan.

- [ ] **Step 3: `docs/specs/2026-07-05-montage-skillset-design.md`** — §5.13.

- Line 403 (the Editorial bullet): change the tail `**Not yet built (Slice B) — the only part of §5.13 still open.**` → `**Built 2026-07-18 (Slice B) — see below.**`
- After the "Built (2026-07-17 …)" block (after line 422), add a new note block:

```markdown
> **Built (2026-07-18, the editorial half — Slice B):** `scripts/lib/review.py`
> (`Finding` + `Review` config-specs, `Review.verdict` = revise-iff-any-blocking) +
> `scripts/reel_review.py` (validate the reviewer's raw findings → `REVIEW.json`+
> `REVIEW.md`) + `SKILLS/reel-review/` (a fresh reviewer subagent judges the reel
> against `SPEC` — idea/mood/hook/ending/spine/edl_completeness/trend_flavor — and
> emits routed findings; the human disposes at CP3). **Human-gated (§4.1)** — no
> auto-fix; `check_reel`/`build_reel`/`deliver`/loop-2 untouched. `trend_flavor` is
> judged at forced low confidence (no source until §5.4). **§5.13 is now ✅ — both
> parts green.** See `docs/specs/2026-07-18-reel-review-editorial-design.md`.
```

- [ ] **Step 4: `CLAUDE.md`** — add two registry rows to the Quick Reference table (after the Reel-final editorial checks rows):

```markdown
| Reel-review editorial design | [2026-07-18-reel-review-editorial-design.md](docs/specs/2026-07-18-reel-review-editorial-design.md) | §5.13 editorial half (Slice B): a fresh reviewer subagent judges the delivered reel vs `SPEC` (idea/mood/hook/ending/spine/edl_completeness/trend_flavor) → typed `Finding`/`Review` (`REVIEW.json`+`.md`), routed findings, **human-gated** at CP3; the `requesting-code-review` calque, reel-brief's twin. Closes §5.13 ◐ → ✅. |
| Reel-review editorial plan | [2026-07-18-reel-review-editorial.md](docs/plans/2026-07-18-reel-review-editorial.md) | Tasks 0–7: `Finding`+`Review` config-specs + `verdict` + `to_markdown`, `reel_review` `build_review`/`write_review` + CLI, optional `montage.py` Stage, `reel-review` SKILL + `reel-reviewer.md` + using-montage CP3 wiring, docs sync. |
```

- [ ] **Step 5: Full suite green** — record the count.

Run: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`
Expected: PASS (all prior + new review / reel_review / montage tests), EXIT: 0. Note the passed/skipped totals and backfill the `NN`/total in Step 2's bullet.

- [ ] **Step 6: Commit**

```bash
git add docs/pipeline-map.md docs/build-status.md docs/specs/2026-07-05-montage-skillset-design.md CLAUDE.md
git commit -m "docs: sync pipeline-map/build-status/spec/registry — §5.13 closed (reel-review Slice B)"
```

- [ ] **Step 7: Final whole-slice review**

Dispatch a code reviewer over the whole slice (BASE = the commit before Task 0; HEAD = current). Spec compliance vs `docs/specs/2026-07-18-reel-review-editorial-design.md` first, then code quality. Confirm the load-bearing invariants:
- **Every gate is enforced in `__post_init__`** — `Finding` rejects out-of-vocab axis/severity/route/confidence + empty evidence/suggestion; `Review` rejects empty reel + raw-dict findings.
- **`verdict` is a computed property, never stored** — a lying `REVIEW.json` verdict is recomputed on load.
- **`build_review` fails loud on a malformed finding and writes nothing** — the reviewer never writes `REVIEW.json` directly.
- **Human-gated, zero downstream blast radius** — no import of `reel_review`/`review` from `check_reel`/`build_reel`/`reel_orchestration`/`deliver`; the montage `reel-review` Stage is optional and never becomes `next`; the autonomous required-stage sequence is unchanged.
- **`trend_flavor` honesty** — the reviewer template forces `confidence=low` + names §5.4, never `blocking`.
- Docs in sync (tally `15 ✅ · 0 ◐ · 1 ❌`; §5.13 marked ✅ in all three docs + the registry).

Fix any findings in follow-up commits (not `--amend`).

---

## Self-Review

**1. Spec coverage** (against `docs/specs/2026-07-18-reel-review-editorial-design.md`):
- §2.1 `Finding` (fields, vocabs, validation, from_dict top-guard, round-trip) → Task 0. ✓
- §2.2 `Review` (fields, `verdict` property, validation, round-trip, from_json) → Task 1. ✓
- §2.2 `to_markdown` (verdict header, blocking-first, empty-clean) → Task 2. ✓
- §1/§4 `build_review` (validate raw → typed, fail-loud) + `write_review` (both files) → Task 3. ✓
- §4 CLI (`build`, `--findings` list-or-object, `_load_findings`) → Task 4. ✓
- §5 optional `montage.py` Stage (`REVIEW.json`, checkpoint `final`, never `next`) + test patch → Task 5. ✓
- §3 reviewer subagent template + §4 SKILL (packet → dispatch → driver → human loop + routing) + §5 using-montage CP3 wiring → Task 6. ✓
- §6 testing (test_review, test_reel_review, test_montage patch) → Tasks 0–5. ✓
- §8 docs + status flip (pipeline-map ◐→✅ + tally, build-status, design spec §5.13, CLAUDE.md) → Task 7. ✓
- §7 boundaries — asserted (human-gated, no actuator, single reviewer, trend_flavor low-confidence, untouched loop-2); no task builds them (correct — they are non-goals). ✓

**2. Placeholder scan:** no TBD/TODO; every code step shows complete code; every test step shows the assertions. The one intentional fill-in — the `NN`/total test count in Task 7 Step 2 — is explicitly backfilled from the Step 5 run (the reel-brief/safe-zones plans do the same). ✓

**3. Type consistency:** `Finding(axis, severity, evidence, route, suggestion, confidence)` is identical across Task 0 (def), Task 2 (`to_markdown` reads `severity`/`axis`/`route`/`confidence`/`evidence`/`suggestion`), Task 3 (`build_review` passes dicts through `Finding.from_dict`). `Review(reel, findings, summary, spec_ref, platform, reviewer)` + `verdict` property identical across Tasks 1–4; `write_review` returns `{"status","verdict","findings","review","md"}` — matched by Task 3/4 tests. The vocab tuples (`REVIEW_AXES`/`REVIEW_SEVERITY`/`REVIEW_ROUTES`/`REVIEW_CONFIDENCE`) are asserted equal in Task 0 and reused verbatim in the SKILL/reviewer template (Task 6). Router `Stage("reel-review", "REVIEW.json", "optional", <runner>, "final")` matches `montage.py`'s `Stage(key, artifact, kind, runner, checkpoint)` arg order and the `_CHECKPOINTS`/`_KINDS` vocab. CLI flag `--findings`→`_load_findings`, `--reel`→`reel`, `--spec`→`spec_ref`, `--platform`→`platform` map 1:1 to `build_review`. ✓
```
