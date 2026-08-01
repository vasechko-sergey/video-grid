# Verify-runtime preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A startup runtime-preflight that asserts the `setup.sh` baseline contract, prints each gap's remedy, gates `using-montage` step 0, and is runnable on demand as a `verify-runtime` skill.

**Architecture:** Pure registry + evaluate in `scripts/lib/preflight.py` (no heavy imports, no ffmpeg — testable without an install); thin impure driver `scripts/verify_runtime.py` (probes + CLI, exit 0/1, read-only). Honest bootstrap boundary: the venv/root live in the pre-venv layer (`bin/vg` + skill preamble), not here. Design: [docs/specs/2026-08-01-verify-runtime-design.md](../specs/2026-08-01-verify-runtime-design.md).

**Tech Stack:** Python 3.13 stdlib (`dataclasses`, `argparse`, `importlib`, `json`, `pathlib`); reuses `scripts/lib/ffbin.py` (`ffmpeg`/`ffprobe`/`has_filter`), `scripts/lib/fonts.py` (`resolve_font`), `scripts/lib/models.py` (`MODELS`). pytest.

---

## File Structure

- Create `scripts/lib/preflight.py` — pure: `Check`, `CHECKS`, `CheckResult`, `Report` (`ok`/`failures`/`advisories`/`to_dict`/`to_text`), `evaluate`.
- Create `scripts/verify_runtime.py` — driver: probes, `_PROBES`, `run`, `main`.
- Create `tests/lib/test_preflight.py` — pure-core tests.
- Create `tests/lib/test_verify_runtime.py` — driver tests (stubbed probes).
- Create `tests/integration/test_verify_runtime.py` — real-machine proof (`integration` marker).
- Create `skills/verify-runtime/SKILL.md` — the on-demand check skill.
- Create `tests/test_verify_runtime_skill.py` — skill + using-montage wiring lint.
- Modify `skills/using-montage/SKILL.md` — step 0 gate.
- Modify `CLAUDE.md`, `docs/build-status.md`, `docs/pipeline-map.md`, `README.md` — docs sync.

The `deps`/probe constants and check `label`/`remedy` strings are the interface between the driver and the tests — they must match **exactly** across `preflight.py`, `verify_runtime.py`, and both test files.

---

## Task 0: `preflight.py` — dataclasses + registry

**Files:**
- Create: `scripts/lib/preflight.py`
- Test: `tests/lib/test_preflight.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/lib/test_preflight.py
import pytest

from scripts.lib import preflight
from scripts.lib.preflight import CHECKS, Check, CheckResult, Report


def _all_ok_raw():
    return {c.key: (True, "ok") for c in CHECKS}


def test_registry_keys_unique_and_expected_split():
    keys = [c.key for c in CHECKS]
    assert len(keys) == len(set(keys))
    assert [c.key for c in CHECKS if c.required] == [
        "deps", "ffmpeg", "drawtext", "vidstab", "font", "weights"]
    assert [c.key for c in CHECKS if not c.required] == ["demucs"]


def test_report_partition():
    results = tuple(
        CheckResult(key=c.key, label=c.label, required=c.required,
                    ok=(c.key not in ("drawtext", "demucs")),
                    detail="", remedy=c.remedy)
        for c in CHECKS)
    r = Report(results=results)
    assert r.ok is False                                  # a required miss (drawtext)
    assert [f.key for f in r.failures] == ["drawtext"]
    assert [a.key for a in r.advisories] == ["demucs"]


def test_report_ok_when_only_advisory_fails():
    results = tuple(
        CheckResult(key=c.key, label=c.label, required=c.required,
                    ok=(c.key != "demucs"), detail="", remedy=c.remedy)
        for c in CHECKS)
    assert Report(results=results).ok is True             # advisory never blocks
```

- [ ] **Step 2: Run it — expect failure**

Run: `.venv/bin/python -m pytest tests/lib/test_preflight.py -q`
Expected: FAIL (`ModuleNotFoundError: scripts.lib.preflight`).

- [ ] **Step 3: Write `scripts/lib/preflight.py`**

```python
"""Runtime-preflight registry (design docs/specs/2026-08-01-verify-runtime-design.md).

The PURE half of the verify-runtime check: the CHECKS registry (what the setup.sh
baseline contract is) and how a set of raw probe results becomes a Report. No
imports of the probed modules, no ffmpeg, no filesystem — the impure probing lives
in scripts/verify_runtime.py. That split is what makes the report logic testable
without a working install: feed evaluate() fabricated results.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    """One runtime requirement. `required` True → a failure BLOCKS the run; False →
    advisory (reported, never blocks). `remedy` is the exact shell command the user
    runs to fix it — verify_runtime PRINTS it, never runs it (design §4)."""
    key: str
    label: str
    required: bool
    remedy: str


CHECKS: tuple[Check, ...] = (
    Check("deps", "Python runtime deps import", True, "bash setup.sh"),
    Check("ffmpeg", "ffmpeg + ffprobe resolve", True, "bash setup.sh"),
    Check("drawtext", "ffmpeg drawtext filter (titles, draft labels)", True, "bash setup.sh"),
    Check("vidstab", "ffmpeg vidstab filters (intake shake, stabilize)", True, "bash setup.sh"),
    Check("font", "a drawtext font resolves", True, "bash setup.sh"),
    Check("weights", "YOLO segmentation weights present", True, "bash setup.sh"),
    Check("demucs", "demucs (sharper music in-point)", False, "bash setup.sh --with-demucs"),
)


@dataclass(frozen=True)
class CheckResult:
    """A Check joined with its probe outcome (`ok`, `detail`)."""
    key: str
    label: str
    required: bool
    ok: bool
    detail: str
    remedy: str


@dataclass(frozen=True)
class Report:
    """The outcome of every check. `ok` gates the run; `failures`/`advisories`
    split the gaps by whether they block."""
    results: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        """True iff every REQUIRED check passed — advisory results never move it."""
        return all(r.ok for r in self.results if r.required)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        """Required checks that failed — these block the run."""
        return tuple(r for r in self.results if r.required and not r.ok)

    @property
    def advisories(self) -> tuple[CheckResult, ...]:
        """Optional checks that failed — reported, never blocking."""
        return tuple(r for r in self.results if not r.required and not r.ok)
```

- [ ] **Step 4: Run it — expect pass**

Run: `.venv/bin/python -m pytest tests/lib/test_preflight.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Mutation check — `ok` is required-only**

Temporarily change `ok` to `all(r.ok for r in self.results)` (drop the `if r.required`). Run `test_report_ok_when_only_advisory_fails` — it must FAIL (advisory now blocks). Restore.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/preflight.py tests/lib/test_preflight.py
git commit -m "feat: preflight registry + Report partition (verify-runtime)"
```

---

## Task 1: `Report.to_dict` + `to_text`

**Files:**
- Modify: `scripts/lib/preflight.py`
- Test: `tests/lib/test_preflight.py`

- [ ] **Step 1: Add the failing tests**

```python
def test_to_dict_shape():
    from scripts.lib.preflight import evaluate  # noqa: PLC0415 (added next task; see Step 3 note)
```

Do NOT reference `evaluate` yet (it lands in Task 2). Instead build a `Report` directly:

```python
def test_to_dict_shape():
    results = tuple(
        CheckResult(key=c.key, label=c.label, required=c.required, ok=True,
                    detail="ok", remedy=c.remedy)
        for c in CHECKS)
    d = Report(results=results).to_dict()
    assert d["ok"] is True
    assert d["results"][0] == {
        "key": "deps", "label": "Python runtime deps import", "required": True,
        "ok": True, "detail": "ok", "remedy": "bash setup.sh"}


def test_to_text_ready_header_when_ok():
    results = tuple(
        CheckResult(key=c.key, label=c.label, required=c.required, ok=True,
                    detail="ok", remedy=c.remedy)
        for c in CHECKS)
    assert Report(results=results).to_text().startswith("runtime ready")


def test_to_text_lists_failures_and_advisories_with_remedies():
    results = tuple(
        CheckResult(key=c.key, label=c.label, required=c.required,
                    ok=(c.key not in ("font", "demucs")),
                    detail=("no system font" if c.key == "font" else
                            "not installed" if c.key == "demucs" else "ok"),
                    remedy=c.remedy)
        for c in CHECKS)
    text = Report(results=results).to_text()
    assert "runtime NOT ready" in text
    assert "[FAIL] font" in text and "font: bash setup.sh" in text
    assert "[warn] demucs" in text and "demucs: bash setup.sh --with-demucs" in text
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/lib/test_preflight.py -k "to_dict or to_text" -q`
Expected: FAIL (`AttributeError: 'Report' object has no attribute 'to_dict'`).

- [ ] **Step 3: Implement `to_dict` + `to_text` on `Report`**

Add these methods to the `Report` dataclass:

```python
    def to_dict(self) -> dict:
        """JSON payload: overall ok plus each result as a flat dict."""
        return {
            "ok": self.ok,
            "results": [
                {"key": r.key, "label": r.label, "required": r.required,
                 "ok": r.ok, "detail": r.detail, "remedy": r.remedy}
                for r in self.results],
        }

    def to_text(self) -> str:
        """A human report: one line per check (OK / FAIL / warn), then the remedy
        for each gap. Deterministic — the tests pin its shape."""
        header = "runtime ready" if self.ok else "runtime NOT ready"
        lines = [header]
        for r in self.results:
            mark = "OK  " if r.ok else ("FAIL" if r.required else "warn")
            line = f"[{mark}] {r.key}: {r.label}"
            if r.detail:
                line += f" — {r.detail}"
            lines.append(line)
        if self.failures:
            lines.append("")
            lines.append("BLOCKED — required checks failed; fix then re-run:")
            lines += [f"  {r.key}: {r.remedy}" for r in self.failures]
        if self.advisories:
            lines.append("")
            lines.append("Optional (not blocking):")
            lines += [f"  {r.key}: {r.remedy}" for r in self.advisories]
        return "\n".join(lines)
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/lib/test_preflight.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/preflight.py tests/lib/test_preflight.py
git commit -m "feat: Report.to_dict + to_text (verify-runtime)"
```

---

## Task 2: `evaluate(raw)` + key-mismatch raise

**Files:**
- Modify: `scripts/lib/preflight.py`
- Test: `tests/lib/test_preflight.py`

- [ ] **Step 1: Add the failing tests**

```python
def test_evaluate_all_ok_is_ready():
    r = preflight.evaluate(_all_ok_raw())
    assert r.ok is True and r.failures == () and r.advisories == ()


def test_evaluate_joins_label_and_remedy_from_registry():
    raw = _all_ok_raw()
    raw["drawtext"] = (False, "absent from build")
    dt = next(x for x in preflight.evaluate(raw).results if x.key == "drawtext")
    assert dt == CheckResult(
        key="drawtext", label="ffmpeg drawtext filter (titles, draft labels)",
        required=True, ok=False, detail="absent from build", remedy="bash setup.sh")


def test_evaluate_raises_on_missing_key():
    raw = _all_ok_raw()
    del raw["demucs"]
    with pytest.raises(ValueError, match="keys"):
        preflight.evaluate(raw)


def test_evaluate_raises_on_extra_key():
    raw = _all_ok_raw()
    raw["bogus"] = (True, "x")
    with pytest.raises(ValueError, match="keys"):
        preflight.evaluate(raw)
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/lib/test_preflight.py -k evaluate -q`
Expected: FAIL (`AttributeError: module ... has no attribute 'evaluate'`).

- [ ] **Step 3: Implement `evaluate`**

Append to `scripts/lib/preflight.py`:

```python
def evaluate(raw: dict[str, tuple[bool, str]]) -> Report:
    """Join raw probe results (key -> (ok, detail)) with CHECKS into a Report.

    `raw`'s keys MUST equal the registry's keys exactly. A probe without a Check,
    or a Check without a probe, is a bug — it raises rather than silently skipping
    a requirement (design §7 invariant 3)."""
    want = {c.key for c in CHECKS}
    got = set(raw)
    if want != got:
        raise ValueError(
            f"preflight raw keys {sorted(got)} != registry keys {sorted(want)}")
    results = tuple(
        CheckResult(key=c.key, label=c.label, required=c.required,
                    ok=raw[c.key][0], detail=raw[c.key][1], remedy=c.remedy)
        for c in CHECKS)
    return Report(results=results)
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/lib/test_preflight.py -q`
Expected: PASS (all preflight tests).

- [ ] **Step 5: Mutation check — the key guard**

Temporarily change `if want != got:` to `if False:`. Run `test_evaluate_raises_on_extra_key` — it must FAIL (now `raw["bogus"]` is silently ignored / a KeyError elsewhere, not the ValueError). Restore.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/preflight.py tests/lib/test_preflight.py
git commit -m "feat: preflight.evaluate joins probes to the registry (verify-runtime)"
```

---

## Task 3: `verify_runtime.py` — the probes

**Files:**
- Create: `scripts/verify_runtime.py`
- Test: `tests/lib/test_verify_runtime.py`

Design §3 / §5: the driver must import **light** (only stdlib + `ffbin`/`fonts`/`preflight`/`models`, all confirmed numpy-free), so a broken heavy dep is *reported* by `_probe_deps` rather than crashing the checker on import. `MODELS[0] == "yolo11n-seg.pt"` and importing `scripts.lib.models` pulls no numpy/cv2 (verified).

- [ ] **Step 1: Write the failing probe tests**

```python
# tests/lib/test_verify_runtime.py
import json
import sys

import pytest

from scripts import verify_runtime


def test_probe_deps_reports_missing(monkeypatch):
    real = verify_runtime.importlib.import_module

    def fake(name):
        if name == "librosa":
            raise ImportError("no librosa")
        return real(name)

    monkeypatch.setattr(verify_runtime.importlib, "import_module", fake)
    ok, detail = verify_runtime._probe_deps()
    assert ok is False and "librosa" in detail


def test_probe_weights_present_and_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_runtime, "_ROOT", tmp_path)
    ok, _ = verify_runtime._probe_weights()
    assert ok is False
    (tmp_path / verify_runtime.MODELS[0]).write_bytes(b"x")
    ok, detail = verify_runtime._probe_weights()
    assert ok is True and verify_runtime.MODELS[0] in detail


def test_probes_keys_match_registry():
    from scripts.lib.preflight import CHECKS
    assert set(verify_runtime._PROBES) == {c.key for c in CHECKS}
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/lib/test_verify_runtime.py -q`
Expected: FAIL (`ModuleNotFoundError: scripts.verify_runtime`).

- [ ] **Step 3: Write the probes + `_PROBES`**

```python
"""verify-runtime driver (design docs/specs/2026-08-01-verify-runtime-design.md).

Probes the setup.sh baseline contract and reports each gap with its remedy. The
IMPURE half — it imports the probed modules, resolves ffmpeg, spawns `-filters` —
so the report logic (scripts/lib/preflight.py) stays testable without an install.

Read-only: it PRINTS remedies, never runs setup.sh (§4). It runs INSIDE the venv
(via bin/vg), so it cannot report a missing venv or recorded-root — those are the
pre-venv layer (bin/vg + the skill preamble). See design §2/§5.

Imports are kept LIGHT on purpose: a broken heavy dep must be REPORTED by
_probe_deps, not crash this checker on import. models.MODELS pulls no numpy/cv2.
"""
import argparse
import importlib
import json
from pathlib import Path

from scripts.lib import ffbin, fonts, preflight
from scripts.lib.models import MODELS

# The runtime modules the pipeline imports = requirements.txt runtime set (pytest
# excluded, dev-only) + cv2 (a direct import of lib/flow.py; transitive via
# ultralytics). Import NAMES, not pip names (Pillow→PIL, yt-dlp→yt_dlp).
_DEPS = ("numpy", "scipy", "PIL", "cv2", "librosa", "ultralytics",
         "scenedetect", "imagehash", "yt_dlp", "requests")

_ROOT = Path(__file__).resolve().parent.parent   # repo root (bin/vg cd's here)


def _probe_deps() -> tuple[bool, str]:
    missing = [m for m in _DEPS if not _importable(m)]
    if missing:
        return False, "missing: " + ", ".join(missing)
    return True, f"{len(_DEPS)} modules import"


def _importable(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:            # ImportError, or a broken C-extension raising other
        return False


def _probe_ffmpeg() -> tuple[bool, str]:
    try:
        fb, fp = ffbin.ffmpeg(), ffbin.ffprobe()
    except ValueError:
        return False, "ffmpeg/ffprobe not on $FFMPEG, config/ffmpeg.env, or PATH"
    if not (Path(fb).exists() and Path(fp).exists()):
        return False, f"resolved path does not exist: {fb}"
    return True, fb


def _probe_filter(name: str) -> tuple[bool, str]:
    try:
        present = ffbin.has_filter(name)
    except (ValueError, RuntimeError):
        return False, "ffmpeg unavailable"
    return (True, "present") if present else (False, f"{name} absent from this ffmpeg build")


def _probe_drawtext() -> tuple[bool, str]:
    return _probe_filter("drawtext")


def _probe_vidstab() -> tuple[bool, str]:
    for filt in ("vidstabdetect", "vidstabtransform"):
        ok, detail = _probe_filter(filt)
        if not ok:
            return False, detail
    return True, "present"


def _probe_font() -> tuple[bool, str]:
    try:
        return True, fonts.resolve_font()
    except ValueError:
        return False, "no usable font among fonts.FONT_CANDIDATES"


def _probe_weights() -> tuple[bool, str]:
    path = _ROOT / MODELS[0]
    if path.exists():
        return True, str(path)
    return False, f"missing at {path} (the first intake downloads it if online)"


def _probe_demucs() -> tuple[bool, str]:
    return (True, "installed") if _importable("demucs") else (False, "not installed")


_PROBES = {
    "deps": _probe_deps,
    "ffmpeg": _probe_ffmpeg,
    "drawtext": _probe_drawtext,
    "vidstab": _probe_vidstab,
    "font": _probe_font,
    "weights": _probe_weights,
    "demucs": _probe_demucs,
}
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/lib/test_verify_runtime.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_runtime.py tests/lib/test_verify_runtime.py
git commit -m "feat: verify_runtime probes (light imports) (verify-runtime)"
```

---

## Task 4: `run()` + `main()` CLI

**Files:**
- Modify: `scripts/verify_runtime.py`
- Test: `tests/lib/test_verify_runtime.py`

- [ ] **Step 1: Add the failing tests**

```python
def _stub_all(monkeypatch, **overrides):
    """Force every probe to a chosen (ok, detail); default all-pass."""
    for key in verify_runtime._PROBES:
        result = overrides.get(key, (True, "ok"))
        monkeypatch.setitem(verify_runtime._PROBES, key, lambda r=result: r)


def test_run_all_pass_is_ready(monkeypatch):
    _stub_all(monkeypatch)
    assert verify_runtime.run().ok is True


def test_run_required_miss_not_ready(monkeypatch):
    _stub_all(monkeypatch, vidstab=(False, "vidstabdetect absent"))
    r = verify_runtime.run()
    assert r.ok is False and [f.key for f in r.failures] == ["vidstab"]


def test_cli_exit_0_when_ready(monkeypatch, capsys):
    _stub_all(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["verify_runtime"])
    with pytest.raises(SystemExit) as e:
        verify_runtime.main()
    assert e.value.code == 0
    assert "runtime ready" in capsys.readouterr().out


def test_cli_exit_1_on_required_miss(monkeypatch, capsys):
    _stub_all(monkeypatch, drawtext=(False, "absent"))
    monkeypatch.setattr(sys, "argv", ["verify_runtime"])
    with pytest.raises(SystemExit) as e:
        verify_runtime.main()
    assert e.value.code == 1
    assert "drawtext: bash setup.sh" in capsys.readouterr().out


def test_cli_exit_0_on_advisory_only_miss(monkeypatch, capsys):
    _stub_all(monkeypatch, demucs=(False, "not installed"))
    monkeypatch.setattr(sys, "argv", ["verify_runtime"])
    with pytest.raises(SystemExit) as e:
        verify_runtime.main()
    assert e.value.code == 0                     # advisory never changes the exit code


def test_cli_json(monkeypatch, capsys):
    _stub_all(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["verify_runtime", "--json"])
    with pytest.raises(SystemExit):
        verify_runtime.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and payload["results"][0]["key"] == "deps"
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/lib/test_verify_runtime.py -k "run or cli" -q`
Expected: FAIL (`AttributeError: ... has no attribute 'run'`).

- [ ] **Step 3: Implement `run` + `main`**

Append to `scripts/verify_runtime.py`:

```python
def run() -> preflight.Report:
    """Run every probe and evaluate the result. evaluate() enforces that _PROBES's
    keys match the registry — a probe/Check drift raises here, not silently."""
    raw = {key: probe() for key, probe in _PROBES.items()}
    return preflight.evaluate(raw)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="verify the video-grid runtime is installed (design 2026-08-01)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable report instead of the text table")
    a = ap.parse_args()
    report = run()
    print(json.dumps(report.to_dict(), indent=2) if a.json else report.to_text())
    raise SystemExit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/lib/test_verify_runtime.py -q`
Expected: PASS.

- [ ] **Step 5: Mutation check — the exit-code gate**

Temporarily change `SystemExit(0 if report.ok else 1)` to `SystemExit(0)`. Run `test_cli_exit_1_on_required_miss` — it must FAIL. Restore.

- [ ] **Step 6: Commit**

```bash
git add scripts/verify_runtime.py tests/lib/test_verify_runtime.py
git commit -m "feat: verify_runtime run + CLI, exit 0/1 (verify-runtime)"
```

---

## Task 5: integration proof (real machine)

**Files:**
- Create: `tests/integration/test_verify_runtime.py`

- [ ] **Step 1: Write the test**

```python
"""On a completed `bash setup.sh` install, the baseline contract holds (design §8).
The 'needs the user's install' proof — same shape as the ffmpeg-baseline slice."""
import pytest

from scripts import verify_runtime

pytestmark = pytest.mark.integration


def test_real_runtime_is_ready():
    report = verify_runtime.run()
    assert report.ok, "\n" + report.to_text()      # show the failing checks if red
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/integration/test_verify_runtime.py -q -m integration`
Expected: PASS on this machine (setup.sh has run; `config/ffmpeg.env` recorded, deps present, weights shipped). If it fails, the report text names the gap — that is a real finding, not a test bug.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_verify_runtime.py
git commit -m "test: real-runtime verify-runtime integration proof"
```

---

## Task 6: `verify-runtime` skill + `using-montage` step 0

**Files:**
- Create: `skills/verify-runtime/SKILL.md`
- Modify: `skills/using-montage/SKILL.md`
- Create: `tests/test_verify_runtime_skill.py`

- [ ] **Step 1: Write the wiring lint (failing)**

```python
# tests/test_verify_runtime_skill.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/verify-runtime/SKILL.md"
UM = ROOT / "skills/using-montage/SKILL.md"


def test_verify_runtime_skill_exists_and_runs_the_cli():
    text = SKILL.read_text()
    assert text.startswith("---")
    assert "name: verify-runtime" in text
    assert "scripts.verify_runtime" in text


def test_using_montage_step0_gates_on_verify_runtime():
    assert "scripts.verify_runtime" in UM.read_text()
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/test_verify_runtime_skill.py -q`
Expected: FAIL (skill file missing; `scripts.verify_runtime` absent from using-montage).

- [ ] **Step 3: Write `skills/verify-runtime/SKILL.md`**

```markdown
---
name: verify-runtime
description: Check that the video-grid runtime is fully installed before (or independent of) a montage run. Use when a run just failed to start, after `bash setup.sh` or a plugin reinstall, or whenever you want to confirm the environment is whole. Reports each missing piece (deps, ffmpeg, drawtext/vidstab filters, font, YOLO weights; demucs advisory) with the exact command to fix it. Read-only — it never installs anything.
---

# verify-runtime

## Overview

Assert the `setup.sh` **baseline contract** is intact and print each gap's remedy.
Read-only: it names what to run, it never runs an installer. Design:
`docs/specs/2026-08-01-verify-runtime-design.md`.

## When to Use

A run would not start; right after `bash setup.sh` or a `/plugin` reinstall; or any
time you want to confirm the environment before conducting a montage.

## The Process

Announce: **"Using verify-runtime to check the environment."**

1. **Resolve the runtime root (pre-venv layer).** Read the recorded root:
   `ROOT="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")"`. If that file
   is missing, the user has never run `bash setup.sh` — say exactly that and stop
   (there is no runtime to check yet).

2. **Run the check.** `"$ROOT/bin/vg" scripts.verify_runtime` (add `--json` when you
   want to parse it). `bin/vg` gates the venv itself: if it prints
   `no venv at … — run: bash …/setup.sh`, relay that and stop — that is the venv
   layer's own remedy.

3. **Report the result.**
   - **Exit 0 / "runtime ready":** say the runtime is ready.
   - **Exit non-zero:** list each `BLOCKED` required check with its remedy verbatim
     (almost always `bash setup.sh`). Tell the user to run it, then re-check. Do
     **not** run `setup.sh` yourself — installers are the user's to run.
   - **Optional (advisory) gaps** (e.g. `demucs`): mention them as "only needed for
     X", not as blockers.

## Boundaries

- **Read-only.** Never invoke `setup.sh` or any installer; print the remedy.
- **Cannot see the venv or the root record itself** — those are checked before it
  runs (the `cat` above and `bin/vg`). It reports everything *inside* the venv.
- Reports **all** capabilities, not what one brief needs; the caller decides
  relevance.
```

- [ ] **Step 4: Rewrite `using-montage` step 0**

In `skills/using-montage/SKILL.md`, replace the current step 0 block:

```
0. **Ensure env (one-time install).** `bash setup.sh` once per machine — one
   install, no capability flags. It puts keg-only `ffmpeg-full` (drawtext +
   vidstab) beside core ffmpeg and records the path in `config/ffmpeg.env`,
   which is how every stage resolves its binary. Not a per-run command — a
   missing venv on any later run surfaces as `bin/vg`'s own remedy message,
   not a reason to re-run this step.
```

with:

```
0. **Verify the runtime (gate).** After resolving `$VG` (below), run
   `"$VG" scripts.verify_runtime`. Exit 0 → the `setup.sh` baseline is intact,
   proceed. Non-zero → surface each `BLOCKED` check with its remedy (almost always
   `bash setup.sh`) and **stop** — do not run project-init against a broken
   runtime, and never run `setup.sh` yourself. Advisory gaps (e.g. `demucs`) are
   named, not blocking (they only affect optional lanes — e.g. music in-point uses
   the librosa proxy without demucs). The venv and the recorded root are the
   pre-venv layer, checked by the launcher preamble and `bin/vg` before this runs.
   The dedicated `verify-runtime` skill runs the same check on demand.
```

- [ ] **Step 5: Run the lint — expect pass**

Run: `.venv/bin/python -m pytest tests/test_verify_runtime_skill.py -q`
Expected: PASS.

- [ ] **Step 6: Confirm the skill-convention suite still passes**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py -q`
Expected: PASS (the new skill's frontmatter conforms). If it enforces a field the new SKILL lacks, add that field to match the other skills, then re-run.

- [ ] **Step 7: Commit**

```bash
git add skills/verify-runtime/SKILL.md skills/using-montage/SKILL.md tests/test_verify_runtime_skill.py
git commit -m "feat: verify-runtime skill + using-montage step-0 gate"
```

---

## Task 7: docs sync + final whole-slice review

**Files:**
- Modify: `CLAUDE.md`, `docs/build-status.md`, `docs/pipeline-map.md`, `README.md`

- [ ] **Step 1: `CLAUDE.md` — two Quick Reference rows**

Add, near the other util rows (e.g. the landmine-lint / ffmpeg-baseline rows):

```markdown
| Verify-runtime design | [2026-08-01-verify-runtime-design.md](docs/specs/2026-08-01-verify-runtime-design.md) | A startup runtime-preflight: assert the `setup.sh` baseline contract (deps/ffmpeg/drawtext+vidstab/font/weights required; demucs advisory), print each gap's remedy, gate using-montage step 0. Pure `lib/preflight.py` + thin `verify_runtime.py`; read-only; honest bootstrap boundary (venv/root are the pre-venv layer). |
| Verify-runtime plan | [2026-08-01-verify-runtime.md](docs/plans/2026-08-01-verify-runtime.md) | Tasks 0–7: `preflight` registry/Report/evaluate, `verify_runtime` probes+run+CLI (exit 0/1), real-machine proof, `verify-runtime` SKILL + using-montage step-0 gate, docs sync. |
```

- [ ] **Step 2: `docs/build-status.md`** — record verify-runtime as built (a runtime utility, not a conveyor stage). Mirror the phrasing of the ffmpeg-baseline / landmine-lint util entries.

- [ ] **Step 3: `docs/pipeline-map.md`** — add a one-line note that `verify-runtime` is a runtime util that gates `using-montage` step 0 (explicitly **not** in `V1_STAGES`, produces no run artifact).

- [ ] **Step 4: `README.md`** — in the Use section, after the `bash setup.sh` step, add a line: verify the install any time with `/video-grid:verify-runtime` (or `"$VG" scripts.verify_runtime`).

- [ ] **Step 5: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (prior green count + the new preflight/driver/skill tests; integration deselected by default).

Run: `.venv/bin/python -m pytest -q -m integration -k verify_runtime`
Expected: the real-runtime proof PASSES.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/build-status.md docs/pipeline-map.md README.md
git commit -m "docs: verify-runtime — registry, build-status, pipeline-map, README"
```

- [ ] **Step 7: Final whole-slice review**

Dispatch a fresh reviewer over `main..HEAD` for the whole slice (design compliance + code quality). Address any Critical/Important in separate follow-up commits (never amend). Confirm: read-only (no installer call), light imports (no numpy pulled at `verify_runtime` import), `_PROBES` keys == registry keys, exit 0/1 correct, honest bootstrap boundary documented.

---

## Self-Review (author checklist, done before handing off)

- **Spec coverage:** §1 registry → Task 0 `CHECKS`; §3 pure/driver split → Tasks 0–4; §4 read-only → SKILL wording + review; §5 boundary → docstrings + SKILL; §6 wiring → Task 6; §7 invariants → the ok/exit/key-mismatch tests; §8 testing → Tasks 0–5; §9 deferred → not built (correct).
- **Placeholder scan:** none — every code step carries real code.
- **Type consistency:** `Check`/`CheckResult`/`Report` fields and the `evaluate(raw: dict[str, tuple[bool,str]])` shape match across `preflight.py`, `verify_runtime.py`, and the tests; `_PROBES` keys and `CHECKS` keys are asserted equal; `label`/`remedy` strings are identical in registry and tests; `MODELS[0]` is the weights filename source (verified light import).
