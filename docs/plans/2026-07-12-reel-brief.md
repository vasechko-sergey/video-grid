# Reel-brief spine (5.3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build stage 5.3 `reel-brief` — a typed `Spec` config-spec + a thin writer/CLI + an interrogating SKILL that produce `SPEC.md` (+ `SPEC.json`), the editorial brief the user approves at §4.1 CP1, atop project-init's machine subset.

**Architecture:** A straight mirror of `project-init`: contract in `scripts/lib/spec.py` (`Spec` dataclass, validate-and-raise in `__post_init__`, JSON round-trip, `to_markdown`), the thin driver in `scripts/reel_brief.py` (`build_spec` reads canvas from `project.json`, `write_reel_brief` emits both files, argparse CLI), and `SKILLS/reel-brief/SKILL.md` (one-question-at-a-time dialogue). No ffmpeg — a text stage, so no real-ffmpeg golden. The router flips `reel-brief` from deferred → optional.

**Tech Stack:** Python 3.13, dataclasses, argparse, pytest. Runs as modules (`pythonpath = .`, `.venv/bin/python -m ...`).

**Spec:** `docs/specs/2026-07-12-reel-brief-design.md`.

**Conventions (all tasks):** Imports at module top. Every module-level def fully typed. Config-specs validate-and-raise in `__post_init__` with `ValueError`-with-remedy (name the value + allowed set), never a bare `KeyError`/`TypeError`. Whole-object asserts where practical. All commits end with the trailer:
```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```
Run the suite without piping through `tail` (masks exit code): `.venv/bin/python -m pytest ... ; echo "EXIT: $?"`.

---

### Task 0: `Spec` config-spec — fields + validation + JSON round-trip

**Files:**
- Create: `scripts/lib/spec.py`
- Test: `tests/lib/test_spec.py`

- [x] **Step 1: Write the failing tests** (`tests/lib/test_spec.py`)

```python
import pytest

from scripts.lib.spec import MUSIC_MODES, STYLE_LEANS, Spec

GOOD = dict(canvas=(9, 16), length_s=30.0, mood="energetic", hook="jump-cut open")


def test_spec_accepts_good():
    s = Spec(**GOOD)
    assert s.canvas == (9, 16) and s.reel_count == 1 and s.music_mode == "free"
    assert s.style_lean == "balanced" and s.music == "auto" and s.cast == ()


def test_spec_rejects_bad_canvas():
    with pytest.raises(ValueError, match="canvas"):
        Spec(**{**GOOD, "canvas": (9,)})


def test_spec_rejects_nonpositive_length():
    with pytest.raises(ValueError, match="length_s"):
        Spec(**{**GOOD, "length_s": 0})


def test_spec_rejects_bool_length():
    with pytest.raises(ValueError, match="length_s"):
        Spec(**{**GOOD, "length_s": True})


def test_spec_rejects_empty_mood():
    with pytest.raises(ValueError, match="mood"):
        Spec(**{**GOOD, "mood": "  "})


def test_spec_rejects_empty_hook():
    with pytest.raises(ValueError, match="hook"):
        Spec(**{**GOOD, "hook": ""})


def test_spec_rejects_reel_count_below_one():
    with pytest.raises(ValueError, match="reel_count"):
        Spec(**{**GOOD, "reel_count": 0})


def test_spec_rejects_empty_music():
    with pytest.raises(ValueError, match="music"):
        Spec(**{**GOOD, "music": ""})


def test_spec_rejects_bad_music_mode():
    with pytest.raises(ValueError, match="music_mode"):
        Spec(**{**GOOD, "music_mode": "pirate"})


def test_spec_rejects_bad_style_lean():
    with pytest.raises(ValueError, match="style_lean"):
        Spec(**{**GOOD, "style_lean": "edgy"})


def test_spec_rejects_nonstr_cast_entry():
    with pytest.raises(ValueError, match="cast"):
        Spec(**{**GOOD, "cast": ["Anna", 7]})


def test_spec_normalises_canvas_and_cast_to_tuple():
    s = Spec(**{**GOOD, "canvas": [9, 16], "cast": ["Anna", "Ben"]})
    assert s.canvas == (9, 16) and s.cast == ("Anna", "Ben")


def test_spec_roundtrip_to_from_dict():
    s = Spec(**{**GOOD, "cast": ["Anna"], "platform": "tiktok", "notes": "n"})
    assert Spec.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_spec_from_dict_missing_required_raises_clean():
    with pytest.raises(ValueError, match="mood"):
        Spec.from_dict({"canvas": [9, 16], "length_s": 30, "hook": "x"})


def test_spec_from_json_corrupt_raises(tmp_path):
    p = tmp_path / "SPEC.json"
    p.write_text("{not json")
    with pytest.raises(ValueError, match="corrupt"):
        Spec.from_json(p)


def test_spec_write_then_from_json(tmp_path):
    s = Spec(**GOOD)
    p = tmp_path / "SPEC.json"
    s.write(p)
    assert Spec.from_json(p).to_dict() == s.to_dict()


def test_vocab_constants_are_the_allowed_sets():
    assert MUSIC_MODES == ("local", "free", "any")
    assert STYLE_LEANS == ("classic", "balanced", "trend")
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_spec.py -q ; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.spec'`.

- [x] **Step 3: Implement `scripts/lib/spec.py`** (config-spec core; `to_markdown` lands in Task 1)

```python
"""Reel brief: the editorial SPEC atop project-init's machine subset (design
docs/specs/2026-07-12-reel-brief-design.md, stage 5.3). A hard config-spec —
validate-and-raise in __post_init__, JSON round-trip — like project.py's
ProjectConfig / edl.py's EDL. canvas comes from project.json (reel-brief FOLLOWS
project-init); this module never sources aspect itself. No ffmpeg — a text stage.
"""
import json
from dataclasses import dataclass
from pathlib import Path

MUSIC_MODES = ("local", "free", "any")            # rights lane (design §5.5); default "free"
STYLE_LEANS = ("classic", "balanced", "trend")    # classic ↔ trend axis; default "balanced"


@dataclass
class Spec:
    canvas: tuple            # from project.json; positive [w, h]      (gate)
    length_s: float          # target length per reel, seconds, > 0    (gate)
    mood: str                # non-empty                               (gate)
    hook: str                # non-empty                               (gate)
    reel_count: int = 1
    music: str = "auto"      # track name / "auto" / "none" (free, non-empty)
    music_mode: str = "free"
    style_lean: str = "balanced"
    platform: str = ""
    text: str = ""
    ending: str = ""
    cast: tuple = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not (isinstance(self.canvas, (tuple, list)) and len(self.canvas) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
                        for v in self.canvas)):
            raise ValueError(f"Spec.canvas must be [w, h] positive, got {self.canvas!r}")
        self.canvas = tuple(self.canvas)
        if (isinstance(self.length_s, bool) or not isinstance(self.length_s, (int, float))
                or self.length_s <= 0):
            raise ValueError(f"Spec.length_s must be a positive number (seconds), got {self.length_s!r}")
        if not (isinstance(self.mood, str) and self.mood.strip()):
            raise ValueError("Spec.mood must be a non-empty string (the §5.3 gate)")
        if not (isinstance(self.hook, str) and self.hook.strip()):
            raise ValueError("Spec.hook must be a non-empty string (the §5.3 gate)")
        if isinstance(self.reel_count, bool) or not isinstance(self.reel_count, int) or self.reel_count < 1:
            raise ValueError(f"Spec.reel_count must be an int >= 1, got {self.reel_count!r}")
        if not (isinstance(self.music, str) and self.music.strip()):
            raise ValueError("Spec.music must be a non-empty string (track name / 'auto' / 'none')")
        if self.music_mode not in MUSIC_MODES:
            raise ValueError(f"Spec.music_mode {self.music_mode!r} not in {MUSIC_MODES}")
        if self.style_lean not in STYLE_LEANS:
            raise ValueError(f"Spec.style_lean {self.style_lean!r} not in {STYLE_LEANS}")
        for name in ("platform", "text", "ending", "notes"):
            v = getattr(self, name)
            if not isinstance(v, str):
                raise ValueError(f"Spec.{name} must be a string, got {v!r}")
        if not (isinstance(self.cast, (tuple, list))
                and all(isinstance(c, str) and c.strip() for c in self.cast)):
            raise ValueError(f"Spec.cast must be a list of non-empty name strings, got {self.cast!r}")
        self.cast = tuple(self.cast)

    @classmethod
    def from_dict(cls, d: dict) -> "Spec":
        # Pass required raw values through so __post_init__ yields the clean
        # ValueError-with-remedy for missing/None/garbage; supply defaults for
        # absent optional keys (None → default, matching the manifest null rule).
        def opt(key: str, default: object) -> object:
            v = d.get(key)
            return default if v is None else v
        return cls(
            canvas=d.get("canvas"), length_s=d.get("length_s"),
            mood=d.get("mood"), hook=d.get("hook"),
            reel_count=opt("reel_count", 1), music=opt("music", "auto"),
            music_mode=opt("music_mode", "free"), style_lean=opt("style_lean", "balanced"),
            platform=opt("platform", ""), text=opt("text", ""),
            ending=opt("ending", ""), cast=tuple(opt("cast", ())), notes=opt("notes", ""))

    def to_dict(self) -> dict:
        return {"canvas": list(self.canvas), "length_s": self.length_s,
                "mood": self.mood, "hook": self.hook, "reel_count": self.reel_count,
                "music": self.music, "music_mode": self.music_mode,
                "style_lean": self.style_lean, "platform": self.platform,
                "text": self.text, "ending": self.ending, "cast": list(self.cast),
                "notes": self.notes}

    @classmethod
    def from_json(cls, path: str | Path) -> "Spec":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is corrupt ({e}) — re-run reel-brief to regenerate it") from e
        return cls.from_dict(d)

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))
```

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_spec.py -q ; echo "EXIT: $?"`
Expected: PASS (16 tests), EXIT: 0.

- [x] **Step 5: Commit**

```bash
git add scripts/lib/spec.py tests/lib/test_spec.py
git commit -m "feat: Spec config-spec + validation (reel-brief 5.3)"
```

---

### Task 1: `Spec.to_markdown()` — the `SPEC.md` render

**Files:**
- Modify: `scripts/lib/spec.py` (add method to `Spec`)
- Test: `tests/lib/test_spec.py` (append)

- [x] **Step 1: Write the failing tests** (append to `tests/lib/test_spec.py`)

```python
def test_to_markdown_heading_and_gate_fields():
    s = Spec(**{**GOOD, "reel_count": 2, "platform": "tiktok", "cast": ["Anna"]})
    md = s.to_markdown()
    assert md.startswith("# Reel brief — 2 reels, 30s, 9:16")
    assert "**Mood:** energetic" in md
    assert "**Hook:** jump-cut open" in md
    assert "**Music:** auto (mode: free)" in md
    assert "**Cast:** Anna" in md


def test_to_markdown_singular_reel_and_empty_frees_dash():
    md = Spec(**GOOD).to_markdown()
    assert md.startswith("# Reel brief — 1 reel, 30s, 9:16")
    assert "**Platform:** –" in md
    assert "**Cast:** –" in md
    assert "**Text:** –" in md
    assert "**Ending:** –" in md
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_spec.py -k to_markdown -q ; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: 'Spec' object has no attribute 'to_markdown'`.

- [x] **Step 3: Add `to_markdown` to `Spec`** (in `scripts/lib/spec.py`, after `write`)

```python
    def to_markdown(self) -> str:
        w, h = self.canvas
        reels = f"{self.reel_count} reel" + ("s" if self.reel_count != 1 else "")
        cast = ", ".join(self.cast) if self.cast else "–"
        lines = [
            f"# Reel brief — {reels}, {self.length_s:.0f}s, {w}:{h}",
            "",
            f"- **Mood:** {self.mood}",
            f"- **Hook:** {self.hook}",
            f"- **Music:** {self.music} (mode: {self.music_mode})",
            f"- **Style-lean:** {self.style_lean}",
            f"- **Platform:** {self.platform or '–'}",
            f"- **Cast:** {cast}",
            f"- **Text:** {self.text or '–'}",
            f"- **Ending:** {self.ending or '–'}",
            f"- **Notes:** {self.notes or '–'}",
        ]
        return "\n".join(lines)
```

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_spec.py -q ; echo "EXIT: $?"`
Expected: PASS (18 tests), EXIT: 0.

- [x] **Step 5: Commit**

```bash
git add scripts/lib/spec.py tests/lib/test_spec.py
git commit -m "feat: Spec.to_markdown SPEC.md render (reel-brief 5.3)"
```

---

### Task 2: `reel_brief.py` — `build_spec` + `write_reel_brief`

**Files:**
- Create: `scripts/reel_brief.py`
- Test: `tests/test_reel_brief.py`

- [x] **Step 1: Write the failing tests** (`tests/test_reel_brief.py`)

```python
import pytest

from scripts.lib.project import resolve_project
from scripts.lib.spec import Spec
from scripts.reel_brief import build_spec, write_reel_brief


def _project(tmp_path):
    cfg = resolve_project("reel", quality="native")
    cfg.write(tmp_path / "project.json")
    return str(tmp_path / "project.json")


def test_build_spec_reads_canvas_from_project(tmp_path):
    spec = build_spec(_project(tmp_path), length_s=30, mood="calm", hook="slow push")
    assert spec.canvas == (9, 16)          # reel purpose → 9:16, inherited not re-asked
    assert isinstance(spec, Spec)


def test_build_spec_missing_project_fails_loud(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_spec(str(tmp_path / "nope.json"), length_s=30, mood="x", hook="y")


def test_build_spec_forwards_cast_and_editorial(tmp_path):
    spec = build_spec(_project(tmp_path), length_s=20, mood="calm", hook="h",
                      cast=["Anna", "Ben"], music_mode="local", style_lean="trend")
    assert spec.cast == ("Anna", "Ben") and spec.music_mode == "local"
    assert spec.style_lean == "trend"


def test_write_reel_brief_emits_both_files(tmp_path):
    spec = build_spec(_project(tmp_path), length_s=30, mood="calm", hook="slow push")
    res = write_reel_brief(spec, str(tmp_path))
    assert res["status"] == "written"
    assert (tmp_path / "SPEC.json").exists() and (tmp_path / "SPEC.md").exists()
    assert Spec.from_json(tmp_path / "SPEC.json").to_dict() == spec.to_dict()
    assert (tmp_path / "SPEC.md").read_text().startswith("# Reel brief —")
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_reel_brief.py -q ; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.reel_brief'`.

- [x] **Step 3: Implement `scripts/reel_brief.py`** (driver half; CLI lands in Task 3)

```python
"""Reel-brief writer (design docs/specs/2026-07-12-reel-brief-design.md, stage 5.3).

The thin mechanical half: read canvas from project.json, build+validate a Spec,
write SPEC.json + SPEC.md. Judgment (the interrogation dialogue) lives in
SKILLS/reel-brief/SKILL.md. Mirror of edit_plan.py — contract in lib, driver here.
"""
import argparse
import json
from pathlib import Path

from scripts.lib.project import ProjectConfig
from scripts.lib.spec import Spec


def build_spec(project_path: str, *, length_s: float, mood: str, hook: str,
               reel_count: int = 1, music: str = "auto", music_mode: str = "free",
               style_lean: str = "balanced", platform: str = "", text: str = "",
               ending: str = "", cast: tuple = (), notes: str = "") -> Spec:
    """Read canvas from project.json (fail-loud if absent — reel-brief FOLLOWS
    project-init), then construct+validate a Spec. The project is the single source
    of aspect; build_spec never sources canvas itself."""
    cfg = ProjectConfig.from_json(project_path)
    return Spec(canvas=cfg.canvas, length_s=length_s, mood=mood, hook=hook,
                reel_count=reel_count, music=music, music_mode=music_mode,
                style_lean=style_lean, platform=platform, text=text,
                ending=ending, cast=tuple(cast), notes=notes)


def write_reel_brief(spec: Spec, out_dir: str) -> dict:
    """Write SPEC.json + SPEC.md together into out_dir. Returns a status dict."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    sj, sm = Path(out_dir) / "SPEC.json", Path(out_dir) / "SPEC.md"
    spec.write(sj)
    sm.write_text(spec.to_markdown())
    return {"status": "written", "spec": str(sj), "md": str(sm)}
```

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_reel_brief.py -q ; echo "EXIT: $?"`
Expected: PASS (4 tests), EXIT: 0.

- [x] **Step 5: Commit**

```bash
git add scripts/reel_brief.py tests/test_reel_brief.py
git commit -m "feat: reel_brief build_spec + write_reel_brief (5.3)"
```

---

### Task 3: `reel_brief` CLI

**Files:**
- Modify: `scripts/reel_brief.py` (add `main` + `__main__` guard)
- Test: `tests/test_reel_brief.py` (append)

- [x] **Step 1: Write the failing test** (append to `tests/test_reel_brief.py`)

```python
import sys
import json


def test_cli_build_writes_and_exits_0(tmp_path, monkeypatch, capsys):
    from scripts import reel_brief
    proj = _project(tmp_path)
    monkeypatch.setattr(sys, "argv",
                        ["reel_brief", "build", "--project", proj, "--length", "30",
                         "--mood", "calm", "--hook", "slow push",
                         "--cast", "Anna", "--cast", "Ben", "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        reel_brief.main()
    assert e.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "written"
    spec = Spec.from_json(tmp_path / "SPEC.json")
    assert spec.cast == ("Anna", "Ben") and spec.length_s == 30.0
```

- [x] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reel_brief.py -k cli -q ; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: module 'scripts.reel_brief' has no attribute 'main'`.

- [x] **Step 3: Add the CLI** (append to `scripts/reel_brief.py`)

```python
def main() -> None:
    ap = argparse.ArgumentParser(description="write SPEC.json + SPEC.md — the reel brief (stage 5.3)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build SPEC.json + SPEC.md from brief fields")
    b.add_argument("--project", required=True, help="project.json — canvas source (from project-init)")
    b.add_argument("--length", type=float, required=True, help="target reel length, seconds")
    b.add_argument("--mood", required=True, help="the reel's mood (gate)")
    b.add_argument("--hook", required=True, help="the opening hook intent (gate)")
    b.add_argument("--reel-count", type=int, default=1, help="how many reels (default 1)")
    b.add_argument("--music", default="auto", help="track name / 'auto' / 'none'")
    b.add_argument("--music-mode", default="free", help="local / free (default) / any")
    b.add_argument("--style-lean", default="balanced", help="classic / balanced (default) / trend")
    b.add_argument("--platform", default="", help="free label (reel/tiktok/youtube/…)")
    b.add_argument("--text", default="", help="on-screen text intent")
    b.add_argument("--ending", default="", help="ending intent")
    b.add_argument("--cast", action="append", default=None, help="a cast name (repeatable)")
    b.add_argument("--notes", default="")
    b.add_argument("--out-dir", required=True, help="dir for SPEC.json + SPEC.md")
    a = ap.parse_args()
    spec = build_spec(a.project, length_s=a.length, mood=a.mood, hook=a.hook,
                      reel_count=a.reel_count, music=a.music, music_mode=a.music_mode,
                      style_lean=a.style_lean, platform=a.platform, text=a.text,
                      ending=a.ending, cast=tuple(a.cast or ()), notes=a.notes)
    result = write_reel_brief(spec, a.out_dir)
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Run to verify it passes** (and the module runs end-to-end)

Run: `.venv/bin/python -m pytest tests/test_reel_brief.py -q ; echo "EXIT: $?"`
Expected: PASS (5 tests), EXIT: 0.

Smoke (optional): with a `project.json` present,
`.venv/bin/python -m scripts.reel_brief build --project <dir>/project.json --length 30 --mood calm --hook "slow push" --out-dir <dir>` prints `{"status": "written", ...}`.

- [x] **Step 5: Commit**

```bash
git add scripts/reel_brief.py tests/test_reel_brief.py
git commit -m "feat: reel_brief CLI build subcommand (5.3)"
```

---

### Task 4: Router flip — `reel-brief` deferred → optional

**Files:**
- Modify: `scripts/montage.py:42`
- Test: `tests/lib/test_montage.py` (patch stale assertions + add optional case)

- [x] **Step 1: Patch the montage tests to the new expectation**

In `tests/lib/test_montage.py`, edit `test_v1_stages_kinds_and_flags` — change the deferred-set line and add reel-brief assertions:

```python
def test_v1_stages_kinds_and_flags():
    by = {s.key: s for s in V1_STAGES}
    assert [s.key for s in V1_STAGES if s.kind == "deferred"] == [
        "trend-scan", "pacing"]
    assert by["music-and-mood"].kind == "optional"
    assert by["reel-brief"].kind == "optional"
    assert by["reel-brief"].artifact == "SPEC.json"
    assert by["reel-brief"].checkpoint == "spec"
    assert by["deliver"].in_out is True and by["deliver"].artifact == "REEL_v*.*"
    assert by["project-init"].checkpoint == "spec"
    assert by["edit-plan"].checkpoint == "edl"
    assert by["deliver"].checkpoint == "final"
```

Edit `test_deferred_stages_always_skip` — drop `reel-brief` from the loop:

```python
def test_deferred_stages_always_skip(tmp_path):
    res = next_action(str(tmp_path))
    for k in ("trend-scan", "pacing"):
        assert _state(res, k) == "skip"
```

Append a new optional-state case:

```python
def test_reel_brief_optional_absent_then_present(tmp_path):
    _touch(tmp_path, "project.json")
    res = next_action(str(tmp_path))
    assert _state(res, "reel-brief") == "optional"   # absent optional never blocks
    assert res["next"] == "footage-intake"           # next unaffected by an optional stage
    _touch(tmp_path, "SPEC.json")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "reel-brief") == "done"
    assert res2["next"] == "footage-intake"
```

- [x] **Step 2: Run to verify the patched tests fail against current code**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q ; echo "EXIT: $?"`
Expected: FAIL — the deferred set still contains `reel-brief`; `test_reel_brief_optional_absent_then_present` sees `state == "skip"`.

- [x] **Step 3: Flip the stage in `scripts/montage.py`**

Line 42 — replace:

```python
    Stage("reel-brief", "SPEC.md", "deferred", "5.3 - not built", None),
```

with:

```python
    Stage("reel-brief", "SPEC.json", "optional", "reel-brief SKILL -> reel_brief CLI", "spec"),
```

- [x] **Step 4: Run the montage suite**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q ; echo "EXIT: $?"`
Expected: PASS (all montage tests), EXIT: 0.

- [x] **Step 5: Commit**

```bash
git add scripts/montage.py tests/lib/test_montage.py
git commit -m "feat: router treats reel-brief as optional, SPEC.json artifact (5.3)"
```

---

### Task 5: `SKILLS/reel-brief/SKILL.md` + `using-montage` wiring

**Files:**
- Create: `SKILLS/reel-brief/SKILL.md`
- Modify: `SKILLS/using-montage/SKILL.md`

No pytest (SKILLs are prose). The gate is the full-suite green check + the final review.

- [x] **Step 1: Write `SKILLS/reel-brief/SKILL.md`**

```markdown
---
name: reel-brief
description: Stage 5.3 — the reel's editorial brief. Use after project-init (project.json exists) to interrogate the idea one question at a time and write SPEC.md (+ SPEC.json), the brief the user approves at the CP1 checkpoint. Mood, hook, length, music intent, style-lean, cast — the editorial layer atop the machine canvas/delivery. Optional: enriches the reel; the autonomous path runs without it.
---

# reel-brief (stage 5.3)

Turn a rough idea into a locked **reel brief** — `SPEC.md`, the editorial layer on
top of `project-init`'s machine subset. This is the **brainstorming of reels**: a
one-question-at-a-time dialogue, a hard gate before anything is written, and a
deterministic writer (you never hand-write `SPEC.md`). No ffmpeg here.

**The brief is judgment; the write is mechanical.** You collect the answers; the
`reel_brief` CLI validates them and renders both files. `canvas` is **not** yours to
choose — it comes from `project.json` (reel-brief FOLLOWS project-init); never
re-ask aspect.

## Inputs

- **`project.json`** (required, from project-init) — the canvas the brief inherits.
  If it is missing, run project-init first; reel-brief will not source aspect itself.
- **`cast.json`** (optional, from footage-intake) — real cast names to reference in
  the brief's `cast`. Absent → enter names free-hand.

## Procedure

Announce on entry: **"Using reel-brief to lock the reel's SPEC."**

1. **Recon.** Read `project.json` (note the canvas) and `cast.json` if present.
2. **Ask one question at a time** — do not batch. Cover: reel count · platform ·
   target length (seconds) · mood · hook (the opening) · music (a track / "auto" /
   "none") + `music.mode` (local / free / any — default free, the safe distribution
   lane) · style-lean (classic / balanced / trend) · on-screen text · ending · cast.
   Prefer the user's free text ("without music" → `--music none`; "any source" →
   `--music-mode any`).
3. **HARD-GATE.** Do not write until **mood + canvas + length + hook** are locked.
   If any is vague, keep asking.
4. **Self-review** the assembled answers, then **build** (explicit args; the user
   never types flags):

       python -m scripts.reel_brief build --project project.json \
         --length 30 --mood "…" --hook "…" \
         [--reel-count N] [--music …] [--music-mode free] [--style-lean balanced] \
         [--platform …] [--text …] [--ending …] [--cast NAME]... [--notes …] \
         --out-dir .

   It validates the fields and writes `SPEC.json` + `SPEC.md`. A `ValueError` names
   the offending field — fix it and re-run; never hand-write `SPEC.md`.
5. **Review — CP1.** Show the user `SPEC.md` and get approval before edit-plan.

## Gate

`mood`, `canvas`, `length`, `hook` locked; `SPEC.json` + `SPEC.md` written. The
edit-plan agent reads `SPEC.md` as guidance (mood / hook / style-lean / length).

## Boundaries

- **Optional stage.** The brief enriches the reel; the autonomous path runs off
  `project.json` alone. Run reel-brief when the idea deserves shaping.
- **Not consumed mechanically in v1:** `music`/`music_mode` are recorded for Phase
  B3 sourcing (unbuilt); `reel_count > 1` is recorded intent (the mechanical path is
  single-reel); `style_lean` is editorial guidance, not a `TRENDS.md` (5.4) input.
- You never hand-edit `SPEC.json`/`SPEC.md` — the CLI regenerates them from answers.
```

- [x] **Step 2: Wire `reel-brief` into `SKILLS/using-montage/SKILL.md`**

(a) Overview stage list — line 13, change
`(project-init -> footage-intake -> [music] -> edit-plan -> edl_to_reel)` to
`(project-init -> footage-intake -> [reel-brief] -> [music] -> edit-plan -> edl_to_reel)`.

(b) Insert a new **step 4** after the footage-intake step (currently ending at line 51), and renumber the following steps (music 4→5, edit-plan 5→6, edl_to_reel 6→7):

```markdown
4. **reel-brief (optional).** If the brief deserves shaping (mood/hook/ending/
   style-lean beyond the bare aspect), invoke the **reel-brief** skill — it asks the
   idea one question at a time and writes `SPEC.md` + `SPEC.json` into `<run>`.
   `montage status` never points `next` here (it is optional); offer it proactively.
   **SPEC.md is CP1's richer artifact** — when it exists, it is what the user
   approves at Checkpoint 1 (the `edit-plan` agent then reads it as guidance). On a
   bare autonomous run, skip it and say so; `project.json` still anchors CP1.
```

(c) Checkpoint-1 note — in the project-init step (line 46-47), append a sentence:
`When reel-brief runs, SPEC.md is the fuller CP1 artifact; without it, the resolved {canvas, delivery} is the CP1 surface.`

(d) Intent table (after line 83) — add a row:
`| a reel idea / mood / hook / "no music" | reel-brief SKILL -> SPEC.md |`

(e) Deferred-stages line (92-94) — remove reel-brief, leaving:

```markdown
- **Deferred stages are named, not skipped silently:** trend-scan (5.4), pacing
  (`PACING.md`, 5.6 — `beat_slot` stays unset), and the `draft.mp4` (SP1b) are not
  built; say so when you pass over them. reel-brief (`SPEC.md`, 5.3) is optional —
  offer it; on a bare run, name it as skipped.
```

- [x] **Step 3: Verify the full suite still green** (no code changed, but confirm nothing references the old SKILL text in tests)

Run: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`
Expected: PASS (all), EXIT: 0.

- [x] **Step 4: Commit**

```bash
git add SKILLS/reel-brief/SKILL.md SKILLS/using-montage/SKILL.md
git commit -m "feat: reel-brief SKILL + using-montage wiring (5.3)"
```

---

### Task 6: Docs sync + final whole-slice review

**Files:**
- Modify: `docs/pipeline-map.md`, `docs/build-status.md`, `docs/specs/2026-07-05-montage-skillset-design.md`, `CLAUDE.md`

- [x] **Step 1: `docs/pipeline-map.md`** — flip 5.3 to built.

In the 15-stage table (row 5.3), change status `◐ → ✅` and the note to:
`\`reel-brief\` SKILL → \`reel_brief\` CLI + typed \`Spec\` (\`scripts/lib/spec.py\`) writes \`SPEC.md\`+\`SPEC.json\` atop project-init's machine subset (5.3)`.

In the remaining-work table (row 5.3), change `St` `◐ → ✅` and `Left to build` to `— (2026-07-12)`.

Update the tally line `**Tally:** 8 ✅ · 4 ◐ · 3 ❌.` → `**Tally:** 9 ✅ · 3 ◐ · 3 ❌.`

In the critical-path prose and "Front-half authoring ◐" roadmap bullet, mark reel-brief done: the front half's remaining authoring is now SP1b (`draft.mp4`) + trend-scan (5.4); `SPEC.md` (5.3) is built (optional enricher).

- [x] **Step 2: `docs/build-status.md`** — append to the Done section (chronological, newest last):

```markdown
- **reel-brief (5.3, editorial spine) DONE (2026-07-12)** — `scripts/lib/spec.py`
  (`Spec` config-spec: canvas-from-project + gate on mood/hook/length, JSON
  round-trip, `to_markdown`) + `scripts/reel_brief.py` (`build_spec`/`write_reel_brief`
  + CLI) + `SKILLS/reel-brief` (one-question-at-a-time → `SPEC.md`+`SPEC.json`). Router
  flips reel-brief deferred → **optional** (SPEC.md enriches CP1; autonomous path
  intact). Text stage — no ffmpeg, no golden. See `docs/plans/2026-07-12-reel-brief.md`.
```

Narrow the "Next action" pointer so it no longer lists reel-brief; the front-half's open items are SP1b draft + trend-scan (5.4) + music B3.

- [x] **Step 3: `docs/specs/2026-07-05-montage-skillset-design.md`** — add a note under §5.3 (after the "Gate:" line, line ~216):

```markdown
> **Built (2026-07-12):** `scripts/lib/spec.py` (`Spec` config-spec + `to_markdown`)
> + `scripts/reel_brief.py` (`build_spec` reads canvas from `project.json`,
> `write_reel_brief` → `SPEC.md`+`SPEC.json`) + `SKILLS/reel-brief`. Router treats it
> as **optional** (enriches CP1; the autonomous path runs off `project.json`). Music
> sourcing/mood-match (B3), cast.json cross-validation, and multi-reel fan-out are
> deferred — `SPEC` records `music`/`music_mode`/`reel_count` but nothing consumes
> them yet. See `docs/plans/2026-07-12-reel-brief.md`.
```

- [x] **Step 4: `CLAUDE.md`** — add two registry rows to the Quick Reference table (after the Router entry-skill rows):

```markdown
| Reel-brief spine design | [2026-07-12-reel-brief-design.md](docs/specs/2026-07-12-reel-brief-design.md) | Stage 5.3: editorial `SPEC.md`+`SPEC.json` atop project-init's machine subset; typed `Spec` config-spec (gate on mood/hook/length), thin `reel_brief.py` writer, one-question SKILL; router optional (enriches CP1). |
| Reel-brief spine plan | [2026-07-12-reel-brief.md](docs/plans/2026-07-12-reel-brief.md) | Tasks 0–6: `Spec` + `to_markdown`, `build_spec`/`write_reel_brief` + CLI, router deferred→optional flip + test patch, `reel-brief` SKILL + using-montage wiring, docs. |
```

- [x] **Step 5: Full suite green**

Run: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`
Expected: PASS (all prior + new spec/reel_brief/montage tests), EXIT: 0.

- [x] **Step 6: Commit**

```bash
git add docs/pipeline-map.md docs/build-status.md docs/specs/2026-07-05-montage-skillset-design.md CLAUDE.md
git commit -m "docs: sync pipeline-map/build-status/spec/registry for reel-brief (5.3)"
```

- [x] **Step 7: Final whole-slice review**

Dispatch a code reviewer over the whole slice (spec compliance vs `docs/specs/2026-07-12-reel-brief-design.md`, then code quality). Confirm: the gate is enforced in `__post_init__`; `build_spec` sources canvas only from the project; both files are written together; the router flip left the autonomous flow's `next` sequence unchanged; docs are in sync. Fix any findings in follow-up commits (not `--amend`).

---

## Self-Review

**1. Spec coverage** (against `docs/specs/2026-07-12-reel-brief-design.md`):
- §2 `Spec` contract (fields, validation, gate, from_dict/to_dict/from_json/write) → Task 0. ✓
- §2 `to_markdown` → Task 1. ✓
- §3 `build_spec` (canvas from project, fail-loud) + `write_reel_brief` (both files) → Task 2. ✓
- §3 CLI (build subcommand, `--cast` append, SystemExit 0) → Task 3. ✓
- §5 router flip deferred→optional + `SPEC.json` glob + `checkpoint="spec"` + test patches → Task 4. ✓
- §4 SKILL + §5 using-montage wiring → Task 5. ✓
- §6 testing (test_spec, test_reel_brief, test_montage patches) → Tasks 0–4. ✓
- §8 docs to sync → Task 6. ✓
- §7 non-goals — asserted as recorded-not-consumed; no task builds them (correct). ✓

**2. Placeholder scan:** no TBD/TODO; every code step shows complete code; every test step shows the assertions. ✓

**3. Type consistency:** `Spec(canvas, length_s, mood, hook, reel_count, music, music_mode, style_lean, platform, text, ending, cast, notes)` is identical across Task 0 (def), Task 1 (`to_markdown` reads the same fields), Task 2 (`build_spec` forwards them), Task 3 (CLI flags map 1:1, `--reel-count`→`reel_count`, `--music-mode`→`music_mode`, `--style-lean`→`style_lean`). `MUSIC_MODES`/`STYLE_LEANS` are tuples in both the module and the test. `write_reel_brief` returns `{"status": "written", "spec", "md"}` — matched by Task 2/3 tests. Router `Stage(...)` arg order matches `montage.py`'s existing rows (`key, artifact, kind, runner, checkpoint`). ✓
