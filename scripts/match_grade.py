"""The match-grade conductor (design 2026-07-30, montage §10): measure every EDL episode's
source, compute one common reel tone target (the median), and author tone_src/tone_dst into
the episodes that deviate — so the reel reads as one grade. Reads EDL.json, writes it back
enriched + a MATCH.md report. Opt-in: it CHANGES the look, so it is never on the autonomous
path. matchgrade owns the decisions; this driver owns the ffmpeg measuring (measure_profile)
and the EDL IO. Mirror of pacing.py: pure core in lib, driver here."""
import argparse
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

from scripts.color_measure import measure_profile
from scripts.lib import matchgrade
from scripts.lib.edl import EDL, write_edl


def conduct(edl: EDL, footage_root: str, *, eps: float = matchgrade.MATCH_EPS,
            force: bool = False) -> tuple[EDL, matchgrade.Profile, list[matchgrade.ToneDecision]]:
    """Measure each episode's source at its window MIDPOINT (start + dur/2 — a settled,
    representative frame of the shipped window; a WHOLE frame, not the crop — see design §5),
    compute the common target, and return (enriched EDL, target, decisions). The decisions
    carry each measured profile, so write_match writes the report with no second measure.
    Applying through dataclasses.replace rebuilds each EDLEpisode (re-coercing the tone
    pair to tuples). The pair's VALIDITY — ordering, gap, 0-255 range — is not gated here:
    EDLEpisode carries tone as data (like hero/pan/layout), and the check lives downstream
    in ReframeSpec (the soft-manifest / hard-engine split), so a malformed pair fails when
    the episode is processed, not in this driver."""
    profiles = [measure_profile(str(Path(footage_root) / e.source), at=e.start + e.dur / 2)
                for e in edl.episodes]
    target = matchgrade.common_target(profiles)
    has_tone = [e.tone_src is not None for e in edl.episodes]
    decisions = matchgrade.plan(profiles, has_tone, target, eps=eps, force=force)
    new_episodes = tuple(
        e if d.reason == "hand-authored"                       # respect the human's pair
        else replace(e, tone_src=d.tone_src, tone_dst=d.tone_dst)  # set, or clear (None) a stale one
        for e, d in zip(edl.episodes, decisions))
    return replace(edl, episodes=new_episodes), target, decisions


def _report_md(sources: list[str], target: matchgrade.Profile,
               decisions: list[matchgrade.ToneDecision], eps: float) -> str:
    """The human-readable half a reviewer reads at CP-time: the target, and one row per
    episode with its measured profile (carried on the decision — no second measure), its
    distance to the target, and what was decided."""
    def _triple(t):
        return "/".join(f"{v:.0f}" for v in t)
    n_auth = sum(1 for d in decisions if d.action == "author")
    lines = [f"# Match-grade — target {_triple(target)} (p5/p50/p95), eps {eps:g}", "",
             f"{n_auth}/{len(decisions)} episodes authored a tone pair.", "",
             "| # | source | measured (p5/p50/p95) | max Δ | action · reason |",
             "|---|--------|-----------------------|:-----:|-----------------|"]
    for src, d in zip(sources, decisions):
        delta = max(abs(a - b) for a, b in zip(d.measured, target))
        lines.append(f"| {d.index} | {src} | {_triple(d.measured)} | {delta:.0f} | {d.action} · {d.reason} |")
    return "\n".join(lines) + "\n"


def write_match(edl_path: str, footage_root: str, *, eps: float = matchgrade.MATCH_EPS,
                force: bool = False) -> dict:
    """Read EDL.json → conduct → write the enriched EDL BACK IN PLACE (the stage enriches the
    EDL a human then reviews) + a sibling MATCH.md. One measure pass (inside conduct); the
    decisions carry the measured profiles the report needs. Returns a status dict."""
    edl = EDL.from_json(edl_path)
    out, target, decisions = conduct(edl, footage_root, eps=eps, force=force)
    write_edl(out, edl_path)      # re-stamp: match_grade is a legitimate tool, and its
                                  # output is the tool's output (design §4)
    md_path = Path(edl_path).parent / "MATCH.md"
    md_path.write_text(_report_md([e.source for e in edl.episodes], target, decisions, eps))
    skipped = Counter(d.reason for d in decisions if d.action == "skip")
    return {"status": "written", "edl": str(edl_path), "md": str(md_path),
            "target": list(target), "eps": eps,
            "authored": sum(1 for d in decisions if d.action == "author"),
            "skipped": dict(skipped)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="match-grade conductor — author tone_src/tone_dst across an EDL (§10)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="measure every episode → common target → author tone pairs")
    b.add_argument("--edl", required=True, help="EDL.json — enriched IN PLACE with tone pairs")
    b.add_argument("--footage-root", required=True, help="dir the EDL 'source' paths resolve against")
    b.add_argument("--eps", type=float, default=matchgrade.MATCH_EPS,
                   help=f"skip an episode within this many luma units of the target "
                        f"(default {matchgrade.MATCH_EPS})")
    b.add_argument("--force", action="store_true",
                   help="re-author even hand-authored/previously-conducted episodes")
    a = ap.parse_args()
    result = write_match(a.edl, a.footage_root, eps=a.eps, force=a.force)
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
