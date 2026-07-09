# Project-init (purpose→aspect/delivery + inheritance) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the project-level front-door that drives the now-aspect/resolution-agnostic engine — a `project.json` learned once at project start (purpose→canvas, quality→delivery, delivery defaults to `native`), which episode manifests inherit unless they override.

**Architecture:** All determinism in a new pure `scripts/lib/project.py` (a `ProjectConfig` dataclass that raises on bad construction, the `purpose→canvas`/`quality→delivery` maps, `resolve_project`, and the `resolve_manifest` inheritance merge), TDD'd like the rest of `scripts/lib/`. A thin CLI `scripts/project_init.py` writes `project.json`; `process_episode` gains an optional `project=` that applies inheritance before manifest validation; a thin `SKILLS/project-init/SKILL.md` does the interactive asking. Design spec: `docs/2026-07-09-project-init-design.md`.

**Tech Stack:** Python 3.13 (existing `.venv`), stdlib `dataclasses`/`json`, the shipped `scripts/lib/models.Delivery`, pytest. No new third-party deps.

**Scope boundaries (deferred — documented, not silently missing):**
- **`cast.json` / hero-identity ingestion** (interactive naming, seg-mask descriptors, cast-name hero pins) → the montage design's "ingestion plan" (a different axis: identity, not aspect).
- **The full `SPEC.md` reel-brief** (length/mood/music/hook/cast) → later; `project.json` is the machine `{canvas, delivery}` subset it will one day feed.
- **Router / cap-3 fan-out** → its own plan; this plan makes inheritance available via `process_episode(project=)`, it does not build the dispatch loop.
- **Footage reading / segment extraction** → unchanged upstream intake.

**Repo layout produced by this plan:**
```
scripts/
├── lib/
│   └── project.py          # NEW: ProjectConfig + maps + resolve_project + resolve_manifest
├── project_init.py         # NEW: CLI — purpose+quality → project.json
└── process_episode.py      # MODIFY: +project= param (inheritance before validate)
SKILLS/
└── project-init/
    └── SKILL.md            # NEW: interactive "what's this video for" → project.json
tests/
├── lib/test_project.py                    # NEW
├── integration/test_process_episode.py    # +project= inheritance tests
└── integration/test_skill_project_init.py # NEW: structural
```

**`project.json` schema** (written by the CLI, read by `process_episode`):
```json
{"purpose": "reel", "canvas": [9, 16], "delivery": "native", "notes": ""}
```

---

## Task 0: `project.py` — `ProjectConfig` + maps + `resolve_project`

Pure, TDD. The typed config + the deterministic purpose/quality resolution.

**Files:**
- Create: `scripts/lib/project.py`
- Create: `tests/lib/test_project.py`

- [ ] **Step 1: Write the failing tests**

`tests/lib/test_project.py`:
```python
import json
import pytest
from scripts.lib import project as pj


def test_resolve_project_purposes():
    assert pj.resolve_project("reel").canvas == (9, 16)
    assert pj.resolve_project("tiktok").canvas == (9, 16)
    assert pj.resolve_project("youtube").canvas == (16, 9)
    assert pj.resolve_project("square").canvas == (1, 1)
    assert pj.resolve_project("cinema").canvas == (21, 9)


def test_resolve_project_quality_default_native():
    assert pj.resolve_project("reel").delivery == "native"           # default = no downscale
    assert pj.resolve_project("reel", quality="social").delivery == "short_edge:1080"
    assert pj.resolve_project("youtube", quality="4k").delivery == "long_edge:2160"


def test_resolve_project_custom_needs_canvas():
    with pytest.raises(ValueError, match="custom"):
        pj.resolve_project("custom")
    c = pj.resolve_project("custom", canvas=(4, 5))
    assert c.canvas == (4, 5) and c.delivery == "native"


def test_resolve_project_explicit_delivery_overrides_quality():
    c = pj.resolve_project("reel", quality="social", delivery="exact:1080x1920")
    assert c.delivery == "exact:1080x1920"


def test_resolve_project_unknown_raises():
    with pytest.raises(ValueError, match="purpose"):
        pj.resolve_project("bogus")
    with pytest.raises(ValueError, match="quality"):
        pj.resolve_project("reel", quality="ultra")


def test_projectconfig_validation():
    pj.ProjectConfig(purpose="reel", canvas=(9, 16), delivery="native")
    with pytest.raises(ValueError, match="purpose"):
        pj.ProjectConfig(purpose="nope", canvas=(9, 16), delivery="native")
    with pytest.raises(ValueError, match="canvas"):
        pj.ProjectConfig(purpose="reel", canvas=(9, 0), delivery="native")
    with pytest.raises(ValueError, match="delivery"):
        pj.ProjectConfig(purpose="reel", canvas=(9, 16), delivery="huge:9x")


def test_projectconfig_json_roundtrip(tmp_path):
    c = pj.resolve_project("youtube", quality="4k", notes="tv cut")
    fp = tmp_path / "project.json"
    c.write(fp)
    on_disk = json.loads(fp.read_text())
    assert on_disk == {"purpose": "youtube", "canvas": [16, 9],
                       "delivery": "long_edge:2160", "notes": "tv cut"}
    back = pj.ProjectConfig.from_json(fp)
    assert back.canvas == (16, 9) and back.delivery == "long_edge:2160"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_project.py -q`
Expected: FAIL (`module 'scripts.lib.project' has no attribute ...`).

- [ ] **Step 3: Implement**

`scripts/lib/project.py`:
```python
"""Project config: purpose→aspect, quality→delivery, learned once at project
start (design 2026-07-09). Determinism here; the interactive asking lives in
SKILLS/project-init/SKILL.md. Episode manifests inherit canvas/delivery from the
project unless they override."""
import json
from dataclasses import dataclass
from pathlib import Path

from scripts.lib.models import Delivery

PURPOSE_CANVAS = {
    "reel": (9, 16), "shorts": (9, 16), "tiktok": (9, 16),
    "youtube": (16, 9), "landscape": (16, 9),
    "square": (1, 1), "feed": (1, 1),
    "cinema": (21, 9), "wide": (21, 9),
    "custom": None,                       # explicit canvas required
}
QUALITY_DELIVERY = {
    "native": "native",                   # DEFAULT — crop's own pixels, no scale, no loss
    "social": "short_edge:1080",          # deliberate downscale for social / small file
    "4k": "long_edge:2160",               # normalize/upscale to 4K delivery
}


@dataclass
class ProjectConfig:
    purpose: str
    canvas: tuple
    delivery: str
    notes: str = ""

    def __post_init__(self):
        if self.purpose not in PURPOSE_CANVAS:
            raise ValueError(f"ProjectConfig.purpose {self.purpose!r} not in {sorted(PURPOSE_CANVAS)}")
        if not (isinstance(self.canvas, (tuple, list)) and len(self.canvas) == 2
                and all(isinstance(v, (int, float)) and v > 0 for v in self.canvas)):
            raise ValueError(f"ProjectConfig.canvas must be [w, h] positive, got {self.canvas!r}")
        self.canvas = tuple(self.canvas)
        try:
            Delivery.from_spec(self.delivery)
        except (ValueError, TypeError) as e:
            raise ValueError(f"ProjectConfig.delivery {self.delivery!r} invalid — {e}") from e

    @classmethod
    def from_dict(cls, d):
        return cls(purpose=d["purpose"], canvas=tuple(d["canvas"]),
                   delivery=d["delivery"], notes=d.get("notes") or "")

    def to_dict(self):
        return {"purpose": self.purpose, "canvas": list(self.canvas),
                "delivery": self.delivery, "notes": self.notes}

    @classmethod
    def from_json(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text()))

    def write(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))


def resolve_project(purpose, quality="native", canvas=None, delivery=None, notes=""):
    """Deterministic purpose+quality → ProjectConfig. `custom` purpose requires an
    explicit `canvas=(w, h)`; an explicit `delivery` overrides the quality map.
    Raises ValueError-with-remedy on unknown purpose/quality or a missing custom canvas."""
    if purpose not in PURPOSE_CANVAS:
        raise ValueError(f"purpose {purpose!r} unknown — one of {sorted(PURPOSE_CANVAS)}")
    if purpose == "custom":
        if canvas is None:
            raise ValueError("purpose 'custom' needs an explicit canvas=(w, h)")
        cv = tuple(canvas)
    else:
        cv = PURPOSE_CANVAS[purpose]
    if delivery is not None:
        dv = delivery
    elif quality in QUALITY_DELIVERY:
        dv = QUALITY_DELIVERY[quality]
    else:
        raise ValueError(f"quality {quality!r} unknown — one of {sorted(QUALITY_DELIVERY)} "
                         "or pass an explicit delivery=")
    return ProjectConfig(purpose=purpose, canvas=cv, delivery=dv, notes=notes)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_project.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/project.py tests/lib/test_project.py
git commit -m "feat: project.py — ProjectConfig + purpose/quality resolution (native default)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 1: `project.py` — `resolve_manifest` (episode inheritance)

Pure, TDD. The inheritance merge: episode inherits absent canvas/delivery; explicit episode value wins.

**Files:**
- Modify: `scripts/lib/project.py`
- Modify: `tests/lib/test_project.py`

- [ ] **Step 1: Append the failing tests**

Append to `tests/lib/test_project.py`:
```python
def test_resolve_manifest_fills_absent():
    cfg = pj.resolve_project("square")             # (1,1), native
    ep = {"segment": "s.mp4", "out_path": "o.mp4", "composition": "lead",
          "grid": "thirds", "target_dur": 3.0}     # no canvas / delivery
    out = pj.resolve_manifest(ep, cfg)
    assert out["canvas"] == [1, 1] and out["delivery"] == "native"


def test_resolve_manifest_episode_overrides():
    cfg = pj.resolve_project("reel")               # (9,16), native
    ep = {"canvas": [16, 9], "delivery": "short_edge:1080"}
    out = pj.resolve_manifest(ep, cfg)
    assert out["canvas"] == [16, 9] and out["delivery"] == "short_edge:1080"


def test_resolve_manifest_null_inherits():
    cfg = pj.resolve_project("reel")
    out = pj.resolve_manifest({"canvas": None, "delivery": None}, cfg)
    assert out["canvas"] == [9, 16] and out["delivery"] == "native"


def test_resolve_manifest_does_not_mutate_input():
    cfg = pj.resolve_project("reel")
    ep = {"segment": "s.mp4"}
    out = pj.resolve_manifest(ep, cfg)
    assert "canvas" not in ep                       # input untouched
    assert out["canvas"] == [9, 16] and out is not ep
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_project.py -k resolve_manifest -q`
Expected: FAIL (`resolve_manifest` undefined).

- [ ] **Step 3: Implement**

Append to `scripts/lib/project.py`:
```python
def resolve_manifest(episode_dict, config):
    """Fill canvas/delivery from the project when the episode omits them (missing
    OR explicit JSON null → inherit, matching the manifest's null-is-absent rule);
    an explicit episode value wins (override). Returns a NEW dict; never mutates."""
    out = dict(episode_dict)
    if out.get("canvas") is None:
        out["canvas"] = list(config.canvas)
    if out.get("delivery") is None:
        out["delivery"] = config.delivery
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_project.py -q`
Expected: PASS (all — Task 0 + the 4 new).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/project.py tests/lib/test_project.py
git commit -m "feat: resolve_manifest — episode inherits project canvas/delivery, override wins

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `process_episode.py` — `project=` param (inheritance wiring)

Wire the inheritance into the shell: an optional `project=` (a `ProjectConfig` or a path to `project.json`) resolves the manifest before validation. Contract otherwise unchanged.

**Files:**
- Modify: `scripts/process_episode.py`
- Modify: `tests/integration/test_process_episode.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_process_episode.py` (the file has `_stub_engine`, `_manifest(tmp_path, **over)`, `pe`; `_stub_engine` records `calls["reframe_delivery"]` from the fake `ReframeSpec`; add a `calls["reframe_canvas"]` capture in the fake reframe if not present — see note):
```python
from scripts.lib import project as pj


def test_project_inherits_canvas_and_delivery(monkeypatch, tmp_path):
    # a youtube (16:9) project + an episode WITHOUT canvas/delivery → inherits;
    # the non-9:16 canvas + native delivery reach the ReframeSpec (mocked engine)
    calls = _stub_engine(monkeypatch, tmp_path)
    cfg = pj.resolve_project("youtube")                 # (16,9), native
    d = _manifest(tmp_path); del d["canvas"]            # omit canvas → inherit
    result = pe.process_episode(d, project_dir=str(tmp_path), project=cfg)
    assert result["status"] == "mechanical_pass"
    assert calls["reframe_canvas"] == (16, 9)
    assert calls["reframe_delivery"].mode == "native"


def test_project_episode_canvas_overrides(monkeypatch, tmp_path):
    calls = _stub_engine(monkeypatch, tmp_path)
    cfg = pj.resolve_project("youtube")                 # project says 16:9
    result = pe.process_episode(_manifest(tmp_path, canvas=[9, 16]),  # episode says 9:16
                                project_dir=str(tmp_path), project=cfg)
    assert result["status"] == "mechanical_pass"
    assert calls["reframe_canvas"] == (9, 16)           # episode wins


def test_project_from_json_path(monkeypatch, tmp_path):
    # project= may be a path to project.json, not just a ProjectConfig
    _stub_engine(monkeypatch, tmp_path)
    pj.resolve_project("square").write(tmp_path / "project.json")
    d = _manifest(tmp_path); del d["canvas"]
    result = pe.process_episode(d, project_dir=str(tmp_path),
                                project=str(tmp_path / "project.json"))
    assert result["status"] == "mechanical_pass"
```

Note: if `_stub_engine`'s fake `reframe` does not already capture the canvas, add `calls["reframe_canvas"] = spec.canvas` inside it (alongside the existing `calls["reframe_delivery"] = spec.delivery`).

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/integration/test_process_episode.py -k project -q`
Expected: FAIL (`process_episode() got an unexpected keyword argument 'project'`).

- [ ] **Step 3: Implement**

In `scripts/process_episode.py`, add the import near the other `scripts.lib` imports:
```python
from scripts.lib.project import ProjectConfig, resolve_manifest
```
Change the signature and add the resolve step at the very top of the body (after the `max_attempts` guard, before `Manifest.from_dict`):
```python
def process_episode(manifest_dict, project_dir, route_path=None, max_attempts=3, project=None):
    ...docstring...
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    if project is not None:
        cfg = project if isinstance(project, ProjectConfig) else ProjectConfig.from_json(project)
        manifest_dict = resolve_manifest(manifest_dict, cfg)
    try:
        m = manifest_lib.Manifest.from_dict(manifest_dict)
    except (KeyError, TypeError, ValueError) as e:
        return {"status": "needs_input", "problems": [str(e)], "attempt": 0}
    ...rest unchanged...
```
(The `try/except` around `from_dict` already exists from the engine-hardening branch — keep it; only add the `project` param + the `if project is not None:` resolve block above it.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/integration/test_process_episode.py -q`
Expected: PASS (existing + the 3 new). Then the full suite `.venv/bin/python -m pytest -q` — no regression.

- [ ] **Step 5: Commit**

```bash
git add scripts/process_episode.py tests/integration/test_process_episode.py
git commit -m "feat: process_episode(project=) — episode manifests inherit project canvas/delivery

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `project_init.py` — deterministic CLI

The CLI that turns purpose+quality into `project.json`. Thin wrapper over `resolve_project`.

**Files:**
- Create: `scripts/project_init.py`
- Modify: `tests/lib/test_project.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_project.py`:
```python
def test_project_init_cli_writes_json(tmp_path, monkeypatch, capsys):
    import sys
    from scripts import project_init
    argv = ["project_init", "--purpose", "youtube", "--quality", "4k",
            "--project-dir", str(tmp_path)]
    monkeypatch.setattr(sys, "argv", argv)
    project_init.main()
    out = tmp_path / "project.json"
    assert out.exists()
    cfg = pj.ProjectConfig.from_json(out)
    assert cfg.canvas == (16, 9) and cfg.delivery == "long_edge:2160"
    assert capsys.readouterr().out.strip().endswith("project.json")


def test_project_init_cli_custom(tmp_path, monkeypatch):
    import sys
    from scripts import project_init
    monkeypatch.setattr(sys, "argv",
                        ["project_init", "--purpose", "custom", "--canvas", "4:5",
                         "--project-dir", str(tmp_path)])
    project_init.main()
    assert pj.ProjectConfig.from_json(tmp_path / "project.json").canvas == (4, 5)


def test_project_init_cli_bad_purpose_raises(tmp_path, monkeypatch):
    import sys
    from scripts import project_init
    monkeypatch.setattr(sys, "argv",
                        ["project_init", "--purpose", "bogus", "--project-dir", str(tmp_path)])
    with pytest.raises(ValueError, match="purpose"):
        project_init.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/lib/test_project.py -k cli -q`
Expected: FAIL (`No module named 'scripts.project_init'`).

- [ ] **Step 3: Implement**

`scripts/project_init.py`:
```python
"""project-init CLI: purpose+quality → project.json (design 2026-07-09).

    .venv/bin/python -m scripts.project_init --purpose reel --quality native \
        --project-dir out/myproject
Custom aspect: --purpose custom --canvas 4:5 ; explicit delivery: --delivery exact:1080x1920.
"""
import argparse
from pathlib import Path

from scripts.lib.project import resolve_project


def main():
    ap = argparse.ArgumentParser(description="write project.json (purpose→aspect/delivery)")
    ap.add_argument("--purpose", required=True,
                    help="reel/shorts/tiktok/youtube/landscape/square/feed/cinema/wide/custom")
    ap.add_argument("--quality", default="native", help="native (default) / social / 4k")
    ap.add_argument("--canvas", default=None, help="explicit W:H (required for --purpose custom)")
    ap.add_argument("--delivery", default=None, help="explicit delivery spec (overrides --quality)")
    ap.add_argument("--notes", default="")
    ap.add_argument("--project-dir", required=True, help="dir to write project.json into")
    a = ap.parse_args()
    canvas = tuple(int(v) for v in a.canvas.split(":")) if a.canvas else None
    cfg = resolve_project(a.purpose, quality=a.quality, canvas=canvas,
                          delivery=a.delivery, notes=a.notes)
    Path(a.project_dir).mkdir(parents=True, exist_ok=True)
    out = Path(a.project_dir) / "project.json"
    cfg.write(out)
    print(str(out))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/lib/test_project.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add scripts/project_init.py tests/lib/test_project.py
git commit -m "feat: project_init CLI — purpose+quality → project.json

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `project-init` SKILL + real-ffmpeg integration + docs

The interactive agent layer + the end-to-end proof that the project front-door drives the engine, + docs sync.

**Files:**
- Create: `SKILLS/project-init/SKILL.md`
- Create: `tests/integration/test_skill_project_init.py`
- Modify: `tests/integration/test_process_episode.py` (real-ffmpeg inheritance test)
- Modify: `CLAUDE.md`, `README.md`, `docs/2026-07-09-project-init-design.md`

- [ ] **Step 1: Write the SKILL**

`SKILLS/project-init/SKILL.md`:
```markdown
---
name: project-init
description: Use ONCE at the very start of a montage project to learn what the video is for and set its aspect + delivery quality. Asks the purpose (reel / youtube / square / cinema / custom) and quality (native-best / social-1080 / 4K / custom), writes project.json; every episode then inherits canvas/delivery unless it overrides. Run before any episode processing.
---

# project-init

## Overview

You set the project's **canvas** (aspect) and **delivery** (output resolution) once, up front, by asking what the video is for. Every episode manifest then inherits these — the editor never re-specifies aspect per clip. The engine is aspect/resolution-agnostic; this is the front-door that chooses.

**Core principle:** learn the intent, don't assume it. Default delivery is **native** (the crop's own pixels — no downscale, best quality for TVs/large screens); a 1080 cap is a deliberate social choice, not the default.

## The Process

Announce on entry: **"Using project-init to set this project's aspect + delivery."**

1. Ask the **purpose** — "What's this video for?" — reel/shorts/tiktok (9:16), youtube/landscape (16:9), square/feed (1:1), cinema/wide (21:9), or **custom** (you give an explicit `W:H`).
2. Ask the **quality/delivery** — "How should it be delivered?" — **native** (default, best — source resolution, no loss), **social** (1080 cap, smaller file), **4k**, or a custom delivery spec.
3. Run the deterministic writer (never hand-write project.json):
   ```bash
   .venv/bin/python -m scripts.project_init --purpose <p> --quality <q> --project-dir <dir>
   # custom aspect: --purpose custom --canvas 4:5 ; explicit: --delivery exact:1080x1920
   ```
4. Read back the resolved `{canvas, delivery}` from the printed `project.json` and confirm with the user before any episodes are processed.

## Ask, don't guess

If the purpose is genuinely mixed (e.g. "a reel AND a youtube cut") or the platform is unstated, ask — one project.json is one aspect. A per-episode override exists (an episode manifest may set its own `canvas`/`delivery`), but the project default should match the primary deliverable. Never pick an aspect the user didn't indicate.

## References

- The map + inheritance: `scripts/lib/project.py` (`resolve_project`, `resolve_manifest`).
- Delivery modes (native/short_edge/long_edge/exact): `scripts/lib/models.py` `Delivery`.
- How episodes consume it: `scripts/process_episode.py` `process_episode(project=)`.
```

- [ ] **Step 2: Write the structural + integration tests**

`tests/integration/test_skill_project_init.py`:
```python
from pathlib import Path

SKILL = Path(__file__).parent.parent.parent / "SKILLS" / "project-init" / "SKILL.md"


def test_skill_frontmatter_and_shape():
    text = SKILL.read_text()
    assert text.startswith("---")
    assert "name: project-init" in text
    assert "description:" in text
    # points at the deterministic writer, not hand-authoring
    assert "scripts.project_init" in text
    # names the two questions it must ask
    assert "purpose" in text.lower() and "delivery" in text.lower()
    # native-default principle is stated
    assert "native" in text.lower()
```

Append the real-ffmpeg end-to-end test to `tests/integration/test_process_episode.py`:
```python
@pytest.mark.integration
def test_project_native_delivery_end_to_end(tmp_path):
    # a reel (9:16) project with NATIVE delivery + an episode omitting canvas/delivery →
    # inherits → the golden ride renders at the source's native 9:16 crop, not a pinned
    # 1080×1920. Proves the project front-door drives the engine end-to-end through real ffmpeg.
    cfg = pj.resolve_project("reel")                    # (9,16), native
    manifest = dict(segment=str(FIX / "golden_ride.mp4"), out_path=str(tmp_path / "ep.mp4"),
                    composition="lead", grid="thirds", target_dur=1.58)   # no canvas/delivery
    result = pe.process_episode(manifest, project_dir=str(tmp_path),
                                route_path=str(FIX / "golden_route.json"), project=cfg)
    assert result["status"] == "mechanical_pass", result
    import json as _j
    probe = _j.loads(pe.check_episode.proc.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", result["clip"]],
        text=True).stdout)["streams"][0]
    # golden source 1280×720 → 9:16 crop 405×720 → even native → 404×720
    assert (probe["width"], probe["height"]) == (404, 720)
```
(Import `from scripts.lib import project as pj` at the top of the test module if not already added in Task 2. `FIX` is the fixtures path already defined in the file.)

- [ ] **Step 3: Run to verify**

Run: `.venv/bin/python -m pytest tests/integration/test_skill_project_init.py tests/integration/test_process_episode.py -q`
Expected: PASS. If the golden's crop dims differ from `(404, 720)` because the fixture source isn't 1280×720, probe the fixture (`ffprobe` its width/height), recompute `crop_size(9, 16, W, H)` floored even, and use that value — the point is native == the crop's own even dims, not a specific literal.

- [ ] **Step 4: Full suite + docs sync**

Run: `.venv/bin/python -m pytest -q` — expect full green (report the count).
- `docs/2026-07-09-project-init-design.md`: add a "Built (2026-07-09, commit)" note at the top.
- `CLAUDE.md` Status: new bullet — project-init done, N tests, `project.json` + `resolve_manifest` + `process_episode(project=)` + the SKILL; **Next action** → cast.json ingestion or router.
- `README.md`: note that a project's aspect/delivery is set once via `project-init` and episodes inherit.

- [ ] **Step 5: Commit**

```bash
git add SKILLS/project-init/SKILL.md tests/integration/test_skill_project_init.py tests/integration/test_process_episode.py CLAUDE.md README.md docs/2026-07-09-project-init-design.md
git commit -m "feat: project-init SKILL + end-to-end native-inheritance golden; docs sync

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the executor

- **TDD discipline:** test-first → watch fail → implement → pass → commit, per step.
- **`native` is the default and the point** — never make a downscale the default; the engine exists to preserve source resolution.
- **Inheritance is upstream, non-destructive:** `resolve_manifest` returns a new dict and only fills absent (missing/null) fields; the manifest contract and `process_episode`'s body are otherwise untouched.
- **Hard rules (design §12) unchanged:** scripts run as modules; fail loud with a remedy; `pytest.ini` keeps `pythonpath = .`.
```
