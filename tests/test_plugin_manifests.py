"""Plugin + marketplace manifests (design 2026-07-22 §2.3).

Pins the facts a broken manifest fails silently on: valid JSON naming
`video-grid`, a marketplace listing it from the repo root, and `.claude-plugin/`
holding ONLY manifests (the reference's Critical Rule 1 — a skill or script
leaking in there is a structure bug).
"""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CP = REPO / ".claude-plugin"


def test_plugin_manifest_names_video_grid():
    data = json.loads((CP / "plugin.json").read_text())
    assert data["name"] == "video-grid"
    assert re.fullmatch(r"\d+\.\d+\.\d+", data["version"]), data["version"]
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


def test_the_changelog_top_entry_matches_the_plugin_version():
    """The install path is version-keyed — `cache/video-grid/video-grid/<version>/` —
    so a slice that lands without a bump lets a reinstall keep serving the old
    snapshot. That is not hypothetical: it is how `episode-qc` stayed missing from
    the installed skill set for 316 commits (2026-08-25).

    Binding the version to a CHANGELOG heading makes bumping and saying what changed
    ONE act. Forget the bump and the top entry names a version the manifest does not
    have; forget the entry and the manifest names a version the changelog does not.
    Either way this reddens."""
    version = json.loads((CP / "plugin.json").read_text())["version"]
    headings = [ln for ln in (REPO / "CHANGELOG.md").read_text().splitlines()
                if ln.startswith("## ")]
    assert headings, "CHANGELOG.md has no version headings"
    assert headings[0].startswith(f"## {version} "), (
        f"plugin.json says {version}, CHANGELOG.md's top entry is {headings[0]!r}")


def test_every_changelog_heading_is_a_semver_and_they_descend():
    """A heading that is not a version, or a release out of order, means the top-entry
    check above is reading something other than the newest release."""
    headings = [ln for ln in (REPO / "CHANGELOG.md").read_text().splitlines()
                if ln.startswith("## ")]
    versions = []
    for h in headings:
        m = re.fullmatch(r"## (\d+)\.(\d+)\.(\d+) — \d{4}-\d{2}-\d{2}", h)
        assert m, f"malformed changelog heading: {h!r}"
        versions.append(tuple(int(g) for g in m.groups()))
    assert versions == sorted(versions, reverse=True), versions
