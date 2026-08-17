"""Plugin + marketplace manifests (design 2026-07-22 §2.3).

Pins the facts a broken manifest fails silently on: valid JSON naming
`video-grid`, a marketplace listing it from the repo root, and `.claude-plugin/`
holding ONLY manifests (the reference's Critical Rule 1 — a skill or script
leaking in there is a structure bug).
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CP = REPO / ".claude-plugin"


def test_plugin_manifest_names_video_grid():
    data = json.loads((CP / "plugin.json").read_text())
    assert data["name"] == "video-grid"
    assert data["version"]
    assert data["description"]


def test_marketplace_lists_the_plugin_from_repo_root():
    data = json.loads((CP / "marketplace.json").read_text())
    entry = next(p for p in data["plugins"] if p["name"] == "video-grid")
    assert entry["source"] == "./"


def test_claude_plugin_holds_only_manifests():
    assert {p.name for p in CP.iterdir()} == {"plugin.json", "marketplace.json"}


def test_plugin_manifest_declares_the_agpl():
    data = json.loads((CP / "plugin.json").read_text())
    assert data["license"] == "AGPL-3.0-only"


def test_repo_ships_the_agpl_text():
    """The licence is constrained by a dependency, not chosen: ultralytics is
    AGPL-3.0 and scripts/intake.py imports it on the main path (design
    2026-08-17 §1). Pin the text's identity, not merely the file's existence —
    an empty LICENSE would satisfy that and satisfy nobody else."""
    text = (REPO / "LICENSE").read_text()
    lines = text.splitlines()
    assert lines[0].strip() == "GNU AFFERO GENERAL PUBLIC LICENSE"
    assert lines[1].strip() == "Version 3, 19 November 2007"
