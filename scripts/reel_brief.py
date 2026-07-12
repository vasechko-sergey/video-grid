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
