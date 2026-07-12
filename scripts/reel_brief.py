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
