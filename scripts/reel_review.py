"""Reel-review writer (design docs/specs/2026-07-18-reel-review-editorial-design.md,
§5.13 Slice B). The thin mechanical half: validate the reviewer subagent's RAW findings
JSON into a typed Review (fail-loud on a malformed finding), write REVIEW.json + REVIEW.md.
Judgment (the editorial verdict) is the reviewer subagent's, dispatched by
skills/reel-review/SKILL.md. Mirror of reel_brief.py / edit_plan.py — contract in lib,
driver here; the raw-findings → typed-artifact idiom is edit_plan's selection.json → EDL.json.
"""
import argparse
import json
from pathlib import Path

from scripts.lib import provenance
from scripts.lib.review import Finding, Review


def build_review(raw_findings: list, reel: str, *, summary: str = "", spec_ref: str = "",
                 platform: str = "", reviewer: str = "") -> Review:
    """Validate a list of raw finding dicts (the reviewer subagent's output) into a typed
    Review. Every finding is validated and every complaint is collected before raising
    (design 2026-09-08 §6, mirroring episode_qc.build_qc) — the reviewer has already
    exited by the time this runs, so raising on the first bad finding buys nothing about
    the rest of the list and costs a whole round to learn about the second. The refusal's
    STRENGTH is unchanged: any complaint still refuses the whole review and writes
    nothing — the reviewer never writes REVIEW.json directly, so a bad finding fails loud
    at this boundary, not silently."""
    if not isinstance(raw_findings, (tuple, list)):
        raise ValueError(f"build_review: findings must be a list, got {type(raw_findings).__name__} "
                         f"— the reviewer writes a JSON list of finding objects")
    findings: list[Finding] = []
    problems: list[str] = []
    for k, f in enumerate(raw_findings):
        if isinstance(f, Finding):
            findings.append(f)
            continue
        try:
            findings.append(Finding.from_dict(f))
        except ValueError as e:
            problems.append(f"  finding {k}: {e}")
    if problems:
        raise ValueError(
            f"build_review: {len(problems)} complaint(s) across {len(raw_findings)} "
            f"finding(s).\n" + "\n".join(problems)
            + "\nEvery complaint from this run is listed above, so one pass names them "
              "all. Fix or re-dispatch the reviewer, then re-run build.")
    # The digest is computed HERE from the file on disk, never taken from the reviewer's
    # findings file — episode_qc.build_qc's rule verbatim, and for the same reason: it is
    # what turns "a reel was reviewed" into "THIS reel was reviewed" (design 2026-09-09
    # §3). An absent file leaves it empty rather than raising: Review is also the typed
    # sink for a hand-authored review, and an unbound review is reported as unbound.
    # The one path a real run takes — the CLI — refuses an absent reel outright.
    digest = provenance.digest_file(reel) if Path(reel).exists() else ""
    return Review(reel=reel, findings=tuple(findings), summary=summary, spec_ref=spec_ref,
                  platform=platform, reviewer=reviewer, reel_digest=digest)


def write_review(review: Review, out_dir: str) -> dict:
    """Write REVIEW.json + REVIEW.md together into out_dir. Returns a status dict."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    rj, rm = Path(out_dir) / "REVIEW.json", Path(out_dir) / "REVIEW.md"
    review.write(rj)
    rm.write_text(review.to_markdown())
    return {"status": "written", "verdict": review.verdict, "findings": len(review.findings),
            "review": str(rj), "md": str(rm)}


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


def build_parser() -> argparse.ArgumentParser:
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
    return ap


def main() -> None:
    a = build_parser().parse_args()
    if not Path(a.reel).exists():
        raise ValueError(
            f"--reel {a.reel} names no file, so this review would be bound to nothing. "
            f"Point it at the delivered reel (the deliveries bucket's newest "
            f"REEL_v{{n}}.mp4); run `montage status` if you are not sure which that is")
    raw, summary = _load_findings(a.findings)
    review = build_review(raw, a.reel, summary=summary, spec_ref=a.spec,
                          platform=a.platform, reviewer=a.reviewer)
    result = write_review(review, a.out_dir)
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
