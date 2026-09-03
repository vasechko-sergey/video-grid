"""The match-grade conductor (design 2026-07-30, montage §10; crop-based measuring since
design 2026-08-30 §3): measure every EDL episode's own tracked CROP — the pixels that
actually ship — compute one common reel tone target (the median), and author
tone_src/tone_dst into the episodes that deviate — so the reel reads as one grade. Reads
GEOMETRY.json (edl_to_reel --stop-after-geometry's output) + the EDL it names, writes the
EDL back enriched + a MATCH.md report. REQUIRED since design 2026-08-30 §6, not opt-in:
the router runs it on every reel, because a reel it skips is a reel nothing measured —
check_reel's blocking grade_faithful (named tone_match before design 2026-08-31) reads
its advisory target_dev against the target this stamps.
matchgrade owns the decisions; this driver owns the ffmpeg measuring
(color_measure.measure_crop) and the EDL IO. Mirror of pacing.py: pure core in lib, driver
here."""
import argparse
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

from scripts.color_measure import measure_crop
from scripts.lib import color, matchgrade, moodpreset
from scripts.lib.edl import EDL, write_edl
from scripts.lib.models import ReelGeometry
from scripts.lib.spec import Spec


def _resolve_bias(spec: Spec | None,
                  preset: moodpreset.MoodPreset | None) -> tuple[tuple[float, float, float], str]:
    """The tone displacement and WHERE it came from (design 2026-09-03 §2).

    An authored `Spec.tone_bias` outranks the preset's taste, and an authored
    (0, 0, 0) is a real answer — "this mood, but leave my colour alone" — not the
    absence of one, which is why the field's default is None rather than a zero
    triple. `balanced` is tested by NAME, exactly as write_edit_plan tests it for
    `look` and for the same reason: it is resolve()'s "nothing matched", and an
    unmatched brief must not have a taste imposed on it.

    The source string is what MATCH.md prints. Until this slice the report showed
    the displacement without ever saying where it came from, which is the
    "silently" half of the retro's R1.1.
    """
    if spec is not None and spec.tone_bias is not None:
        return spec.tone_bias, "SPEC.tone_bias"
    if preset is not None and preset.name != "balanced":
        return preset.tone_bias, f"the {preset.name} preset"
    return (0.0, 0.0, 0.0), ""


def conduct(geo: ReelGeometry, edl: EDL, *, eps: float = matchgrade.MATCH_EPS,
            force: bool = False, bias: tuple[float, float, float] = (0.0, 0.0, 0.0)
            ) -> tuple[EDL, matchgrade.Profile, list[matchgrade.ToneDecision], float]:
    """Measure each episode's own tracked CROP (design 2026-08-30 §1) — the pixels
    that ship, read through the same RenderPlan the render will use, with the
    colour block at identity — compute the common target, and return (enriched
    EDL, target, decisions, bias scale).

    Measured against the whole source frame this stage read until 2026-08-30:
    seven of eight real episodes differ by more than MATCH_EPS, median 14, max 36
    — so the pairs authored from the frame moved five episodes' midpoints by ~10
    units each while their p5 and p95 anchors, pinned by sky and specular water,
    were identical on both sides of every pair.

    The scale is 1.0 unless the supplied bias had to be shrunk to fit (see biased_target); it
    is returned rather than swallowed because a weakened displacement is invisible in the
    pixels and the report is the only place it can be seen. The decisions
    carry each measured profile, so write_match writes the report with no second measure.
    Applying through dataclasses.replace rebuilds each EDLEpisode (re-coercing the tone
    pair to tuples). The pair's VALIDITY — ordering, gap, 0-255 range — is not gated here:
    EDLEpisode carries tone as data (like hero/pan/layout), and the check lives downstream
    in ReframeSpec (the soft-manifest / hard-engine split), so a malformed pair fails when
    the episode is processed, not in this driver."""
    # Before any ffprobe: measure_crop opens eg.source, and a build dir wiped in the
    # human gap between the phases would otherwise surface as a bare CalledProcessError
    # from inside reframe._probe (whole-branch review, minor 5).
    for i, eg in enumerate(geo.episodes):
        eg.require_inputs(i)
    profiles = [measure_crop(eg.manifest, eg.source, eg.route)
                for eg in geo.episodes]
    target = matchgrade.common_target(profiles)
    # The displacement arrives already resolved (_resolve_bias): conduct does not know
    # what a preset is, so an authored bias and a preset's taste reach the target the
    # same way and there is one place that decides between them.
    target, scale = matchgrade.biased_target(target, bias)
    has_tone = [e.tone_src is not None for e in edl.episodes]
    decisions = matchgrade.plan(profiles, has_tone, target, eps=eps, force=force)
    new_episodes = tuple(
        e if d.reason == "hand-authored"                       # respect the human's pair
        else replace(e, tone_src=d.tone_src, tone_dst=d.tone_dst)  # set, or clear (None) a stale one
        for e, d in zip(edl.episodes, decisions))
    return replace(edl, episodes=new_episodes), target, decisions, scale


def _report_md(sources: list[str], target: matchgrade.Profile,
               decisions: list[matchgrade.ToneDecision], eps: float, *,
               bias: tuple[float, float, float] = (0.0, 0.0, 0.0),
               bias_source: str = "", k: float = 1.0) -> str:
    """The human-readable half a reviewer reads at CP-time: the target, and one row per
    episode with its measured profile (carried on the decision — no second measure), its
    distance to the target, and what was decided.

    The displacement lines exist because a shift the footage had no room for is invisible
    in the pixels and has nowhere else to be seen (design 2026-08-17 §5), and now name
    WHERE the bias came from — SPEC.tone_bias or a mood preset (design 2026-09-03 §2) —
    closing the "silently" half of the retro's R1.1. A scale under the floor is the one
    thing in this report a human must act on."""
    def _triple(t):
        return "/".join(f"{v:.0f}" for v in t)
    n_auth = sum(1 for d in decisions if d.action == "author")
    head = (f"# Match-grade — target {_triple(target)} (p5/p50/p95), eps {eps:g}\n\n"
            f"Measured on each episode's own tracked crop, "
            f"{color.FRAMES} frames per episode "
            f"(design 2026-08-30 §1) — not the whole source frame.")
    if bias_source:
        head += f"\n\nTone displaced by {tuple(bias)} — from {bias_source}"
        if k < 1.0:
            head += f", scaled to {k:.0%} (the reel's own range left no room for the rest)"
        if matchgrade.bias_ineffective(bias, k):
            head += (f"\n\n> **mood-bias-ineffective** — what survived is under "
                     f"{matchgrade.MOOD_FLOOR:g} luma units, which is below this "
                     f"conductor's own delivery error, so the displacement will not be "
                     f"visible in the grade.")
    lines = [head, "",
             f"{n_auth}/{len(decisions)} episodes authored a tone pair.", "",
             "| # | source | measured (p5/p50/p95) | max Δ | action · reason |",
             "|---|--------|-----------------------|:-----:|-----------------|"]
    for src, d in zip(sources, decisions):
        delta = max(abs(a - b) for a, b in zip(d.measured, target))
        lines.append(f"| {d.index} | {src} | {_triple(d.measured)} | {delta:.0f} | {d.action} · {d.reason} |")
    return "\n".join(lines) + "\n"


def write_match(geometry_path: str, *, eps: float = matchgrade.MATCH_EPS,
                force: bool = False, spec: str | None = None) -> dict:
    """Read GEOMETRY.json → the EDL it names → conduct → write the enriched EDL BACK IN
    PLACE (the stage enriches the EDL a human then reviews) + a sibling MATCH.md. One
    measure pass (inside conduct); the decisions carry the measured profiles the report
    needs. Returns a status dict.

    `geo.edl` is used VERBATIM, never resolve()d against geometry_path's directory: it is
    stored exactly as edl_to_reel wrote it (design 2026-08-30 §2.2), and a relative path
    that does not resolve from the CURRENT directory fails loud in EDL.from_json rather
    than silently reading a different file."""
    geo = ReelGeometry.from_json(geometry_path)
    edl = EDL.from_json(geo.edl)
    spec_obj = Spec.from_json(spec) if spec else None
    preset = moodpreset.resolve(spec_obj.mood) if spec_obj is not None else None
    bias, bias_source = _resolve_bias(spec_obj, preset)
    out, target, decisions, k = conduct(geo, edl, eps=eps, force=force, bias=bias)
    # the reel's ONE common target (design §3) — deriving it from the episodes' own
    # tone_dst would fail on the reel where every episode was skipped (all None)
    out = replace(out, tone_target=target)
    write_edl(out, geo.edl)       # re-stamp: match_grade is a legitimate tool, and its
                                  # output is the tool's output (design §4)
    md_path = Path(geo.edl).parent / "MATCH.md"
    md_path.write_text(_report_md([e.source for e in edl.episodes], target, decisions, eps,
                                  bias=bias, bias_source=bias_source, k=k))
    skipped = Counter(d.reason for d in decisions if d.action == "skip")
    return {"status": "written", "edl": geo.edl, "md": str(md_path),
            "target": list(target), "eps": eps,
            "mood": preset.name if preset is not None else None,
            "bias_source": bias_source, "bias_scale": k,
            "authored": sum(1 for d in decisions if d.action == "author"),
            "skipped": dict(skipped)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="match-grade conductor — author tone_src/tone_dst across an EDL (§10)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="measure every episode → common target → author tone pairs")
    b.add_argument("--geometry", required=True,
                  help="GEOMETRY.json from edl_to_reel --stop-after-geometry; it names "
                       "the EDL this writes back")
    b.add_argument("--eps", type=float, default=matchgrade.MATCH_EPS,
                   help=f"skip an episode within this many luma units of the target "
                        f"(default {matchgrade.MATCH_EPS})")
    b.add_argument("--force", action="store_true",
                   help="re-author even hand-authored/previously-conducted episodes")
    b.add_argument("--spec", default=None,
                   help="SPEC.json — its mood displaces the common tone target "
                        "(absent: the plain median, exactly as before)")
    a = ap.parse_args()
    result = write_match(a.geometry, eps=a.eps, force=a.force, spec=a.spec)
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
