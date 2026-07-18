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
