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
import sys
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from scripts.color_measure import measure_crop
from scripts.lib import color, matchgrade, moodpreset
from scripts.lib import regions as regions_lib
from scripts.lib.edl import EDL, write_edl
from scripts.lib.models import ReelGeometry
from scripts.lib.spec import Spec


@dataclass(frozen=True)
class Declared:
    """What `_find_regions` could learn about the author's REGIONS.json.

    The STATE and its DETAIL are separate fields, deliberately: they used to
    share one channel, a string that was either a real path, "" or something
    beginning "unreachable: ", disambiguated by `.startswith`. One channel
    carrying two types is exactly the conflation this slice exists to prevent —
    a project under a directory named `unreachable-takes/` would have made a
    found-and-used declaration report that it could not be looked for (whole-branch
    review, finding 6).

    `regions` is the parsed declaration and is present exactly when `state ==
    "found"`. `detail` is the declaration's path (found), the REGIONS.json that
    was looked for and is not there (none), or why it could not be looked for at
    all (unreachable).
    """
    state: str
    detail: str = ""
    regions: "regions_lib.Regions | None" = None

    def __post_init__(self) -> None:
        if self.state not in matchgrade.REGIONS_STATES:
            raise ValueError(f"Declared.state {self.state!r} unknown — expected one of "
                             f"{matchgrade.REGIONS_STATES}")
        if (self.regions is not None) != (self.state == "found"):
            raise ValueError(
                f"Declared: state {self.state!r} and a parsed declaration must agree — a "
                f"'found' state carries the Regions it found, and every other state "
                f"carries none. Two ways of saying whether a declaration exists is one "
                f"way too many")
        if self.state != "none" and not self.detail:
            raise ValueError(
                f"Declared: state {self.state!r} needs a detail — the path a declaration "
                f"was read from, or the reason it could not be looked for. 'found' with "
                f"no path and 'unreachable' with no reason are both a named state that "
                f"says nothing. Only 'none' may omit it: there, the detail (where it "
                f"looked) is a courtesy, not the answer")


#: `_report_md`'s default: the plain "no declaration" reading, so a caller that
#: renders a report about something else (a bias, a mood) need not invent one.
#: Frozen, so one shared instance is safe as a default argument.
_NO_DECLARATION = Declared("none")


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


def _row_dict(r: "regions_lib.AnchorReading") -> dict:
    """One AnchorReading as MATCH.json carries it. Rounded where it is printed:
    a fraction to four places is 0.01% resolution, which is finer than the gate
    it is compared against."""
    return {"anchor": r.anchor, "name": r.name, "of": r.of, "used": r.used,
            "fraction": round(r.fraction, 4), "value": round(r.value, 1),
            "fallback": r.fallback}


def conduct(geo: ReelGeometry, edl: EDL, *, eps: float = matchgrade.MATCH_EPS,
            force: bool = False, bias: tuple[float, float, float] = (0.0, 0.0, 0.0),
            decl: "regions_lib.Regions | None" = None
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

    `decl` is the author's REGIONS.json declaration (write_match finds it via
    _find_regions and hands it down here) — None measures every anchor from the
    whole crop, exactly as every episode was measured before design 2026-09-15.
    Every measure_crop call carries the SAME decl: one declaration governs the
    whole reel, not a per-episode choice.

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
    # measure_crop returns (profile, rows) (design 2026-09-15): rows carry one
    # AnchorReading per anchor, naming which region actually supplied it. Both
    # halves are kept — profiles feed the target exactly as before, and the rows
    # ride into matchgrade.plan so MATCH.json/MATCH.md can carry the provenance.
    measured = [measure_crop(eg.manifest, eg.source, eg.route, decl=decl)
                for eg in geo.episodes]
    profiles = [p for p, _ in measured]
    region_rows = [tuple(_row_dict(r) for r in rows) for _, rows in measured]
    target = matchgrade.common_target(profiles)
    # The displacement arrives already resolved (_resolve_bias): conduct does not know
    # what a preset is, so an authored bias and a preset's taste reach the target the
    # same way and there is one place that decides between them.
    target, scale = matchgrade.biased_target(target, bias)
    has_tone = [e.tone_src is not None for e in edl.episodes]
    decisions = matchgrade.plan(profiles, has_tone, target, eps=eps, force=force,
                                regions=region_rows)
    new_episodes = tuple(
        e if d.reason == "hand-authored"                       # respect the human's pair
        else replace(e, tone_src=d.tone_src, tone_dst=d.tone_dst)  # set, or clear (None) a stale one
        for e, d in zip(edl.episodes, decisions))
    return replace(edl, episodes=new_episodes), target, decisions, scale


def _report_md(sources: list[str], target: matchgrade.Profile,
               decisions: list[matchgrade.ToneDecision], eps: float, *,
               bias: tuple[float, float, float] = (0.0, 0.0, 0.0),
               bias_source: str = "", mood: str | None = None, k: float = 1.0,
               declared: Declared = _NO_DECLARATION,
               lifts: list[tuple[int, float, float]] = ()) -> str:
    """The human-readable half a reviewer reads at CP-time: the target, and one row per
    episode with its measured profile (carried on the decision — no second measure), its
    distance to the target, and what was decided.

    The displacement lines exist because a shift the footage had no room for is invisible
    in the pixels and has nowhere else to be seen (design 2026-08-17 §5), and now name
    WHERE the bias came from — SPEC.tone_bias or a mood preset (design 2026-09-03 §2) —
    closing the "silently" half of the retro's R1.1. A scale under the floor is the one
    thing in this report a human must act on.

    `mood` is the resolved preset's name, or None when no `--spec` was given at all — it
    exists ONLY to tell those two apart from a THIRD state, `bias_source == ""` with
    `mood` not None, which means a `--spec` WAS given but its mood text matched no preset
    (moodpreset.resolve fell back to `balanced`) and no `SPEC.tone_bias` was authored
    either. Losing that distinction (fix round 1, final-findings.md I-3) made a mood word
    that quietly failed to resolve read identically to a run with no brief at all — the
    exact "silently" class this slice exists to close, restoring the arm the pre-slice
    report carried under `elif preset is not None`.

    `declared` is _find_regions' own answer (design 2026-09-15 §4/§2.1) and carries
    THREE states, not two: `found` (a declaration was read, and `detail` is where
    from), `none` (the project resolves, is reachable, and holds no REGIONS.json —
    every anchor is the whole crop, on purpose), or `unreachable` (`detail` names
    why it could not even be looked for). The third must never read like the
    second: "graded against the whole crop because you asked for nothing" and
    "graded against the whole crop because I could not look" are different claims
    about the same pixels. The state is a FIELD, never a prefix on the detail
    string — see Declared.

    `lifts` is matchgrade.toe_lifts over the pairs the enriched EDL ships, computed by
    the caller because only it holds that EDL (retro 2026-10-16 S17)."""
    def _triple(t):
        return "/".join(f"{v:.0f}" for v in t)
    n_auth = sum(1 for d in decisions if d.action == "author")
    head = (f"# Match-grade — target {_triple(target)} (p5/p50/p95), eps {eps:g}\n\n"
            f"Measured on each episode's own tracked crop, "
            f"{color.FRAMES} frames per episode "
            f"(design 2026-08-30 §1) — not the whole source frame.")
    if declared.state == "unreachable":
        head += (f"\n\nREGIONS.json could not be looked for — {declared.detail}. Every "
                 f"anchor is the whole crop. Re-run `edl_to_reel --stop-after-geometry` "
                 f"to record a reachable project.")
    elif declared.state == "found":
        head += f"\n\nAnchors declared in {declared.detail}."
    else:
        head += "\n\nNo REGIONS.json — every anchor is the whole crop."
    if bias_source:
        head += f"\n\nTone displaced by {tuple(bias)} — from {bias_source}"
        if k < 1.0:
            head += f", scaled to {k:.0%} (the reel's own range left no room for the rest)"
        if matchgrade.bias_ineffective(bias, k):
            head += (f"\n\n> **mood-bias-ineffective** — what survived is under "
                     f"{matchgrade.MOOD_FLOOR:g} luma units, which is below this "
                     f"conductor's own delivery error, so the displacement will not be "
                     f"visible in the grade.")
    elif mood is not None:
        head += "\n\nNo mood matched the brief — the target is the plain median."
    lines = [head, "",
             f"{n_auth}/{len(decisions)} episodes authored a tone pair.", ""]
    for i, lo, hi in lifts:
        lines += [_toe_lift_line(i, sources[i], lo, hi, bias[0] * k), ""]
    lines += [
             "| # | source | measured (p5/p50/p95) | max Δ | action · reason |",
             "|---|--------|-----------------------|:-----:|-----------------|"]
    for src, d in zip(sources, decisions):
        delta = max(abs(a - b) for a, b in zip(d.measured, target))
        lines.append(f"| {d.index} | {src} | {_triple(d.measured)} | {delta:.0f} | {d.action} · {d.reason} |")
    # regions.assemble fills all three anchors for every real episode — an
    # undeclared one falls back to the crop and still reports — so this table is
    # unconditional. It was guarded until 2026-09-16 by a condition only a test
    # double could make false; the doubles now model the real shape
    # (design 2026-09-16 §2.6).
    lines += ["", "| # | anchor | region | kind | % of frame | value | fallback |",
              "|---|--------|--------|------|-----------:|------:|----------|"]
    for d in decisions:
        for r in d.regions:
            fb = r["fallback"] or "—"
            # TWO decimals, not one: MIN_REGION_FRAC is 1% of the frame, and
            # ".1f" rounds a 0.0099 region — which the gate REFUSED — to "1.0%",
            # printed beside a `too-small` fallback the docs describe as "under
            # 1% of the frame". A printed number must not round across the gate
            # it is being shown next to (whole-branch review, finding 9). The
            # stored value already carries four places (_row_dict).
            lines.append(f"| {d.index} | {r['anchor']} | {r['name']} | {r['of']} "
                         f"| {r['fraction'] * 100:.2f}% | {r['value']:.0f} | {fb} |")
    return "\n".join(lines) + "\n"


def _toe_lift_line(index: int, source: str, lo: float, hi: float, offset: float) -> str:
    """One warning per lifted toe — the same sentence in MATCH.md and the log, because
    the log is what the agent reads in the moment and MATCH.md what a human reads at the
    checkpoint (retro 2026-10-16 S17).

    The pin goes through selection.json, never EDL.json: write_match re-stamps the EDL,
    and EDL.from_json refuses a stamped file edited afterwards (review finding 1)."""
    bar = matchgrade.TOE_LIFT_WARN
    why = (f"{offset:+.0f} of it the mood's, the rest more than {bar:g} luma" if offset
           else f"more than {bar:g} luma")
    return (f"> **toe-lift** — episode {index} ({source}): shadows lifted p5 {lo:.0f} → "
            f"{hi:.0f}, {why}. If the dark is the point (a silhouette, a backlit hook), "
            f"look at it with `probe grade`, then pin it: in selection.json give that "
            f"episode tone_src and tone_dst both equal to its measured profile (its row "
            f"in MATCH.md), re-run `edit_plan build` with the same flags, then "
            f"`match_grade build` again — it leaves a pinned episode alone as "
            f"hand-authored.")


def _find_regions(geo: ReelGeometry) -> Declared:
    """The declaration beside project.json, and what to say about it.

    Three states, and they are three (design §4/§2.1): a declaration was `found`;
    the project resolves, is reachable, and holds `none`; or the declaration could
    not even be LOOKED FOR (`unreachable`) — no project was recorded at all (a
    GEOMETRY.json from before design 2026-09-15), or one was and it does not
    resolve from here (a relative `--project` read from a different working
    directory than the one that recorded it, or a project moved since).

    The reachability test is the project FILE, not its parent directory, and that
    is the whole of whole-branch review finding 2: `Path("project.json").parent`
    is `Path(".")`, whose `.is_dir()` is True from ANY working directory, so a
    bare relative project made the conductor look for `./REGIONS.json` in its own
    CWD, find nothing, and report `none` — "you asked for nothing" — while the
    author's declaration sat unread beside the real project.json. Testing the file
    also matches this stage's sibling contract: `geo.edl` is used verbatim and
    fails loud on the file, never on its directory.

    The two unreachable sub-cases share one sentence on purpose: a missing
    directory implies a missing file, and the remedy is identical either way
    (re-run `edl_to_reel --stop-after-geometry` from where the project actually
    is, or with an absolute `--project`). What separates them for a reader is data,
    not a second state — the reason names both the path as RECORDED and the
    absolute path it resolved to, which is what tells "wrong working directory"
    from "the project moved"."""
    if not geo.project:
        return Declared("unreachable", "GEOMETRY.json records no project")
    project = Path(geo.project)
    if not project.is_file():
        return Declared("unreachable",
                        f"{geo.project} does not resolve from here — no file at "
                        f"{project.resolve()}")
    p = project.parent / "REGIONS.json"
    if not p.exists():
        return Declared("none", str(p))
    return Declared("found", str(p), regions_lib.Regions.from_json(p))


def write_match(geometry_path: str, *, eps: float = matchgrade.MATCH_EPS,
                force: bool = False, spec: str | None = None) -> dict:
    """Read GEOMETRY.json → the EDL it names → conduct → write the enriched EDL BACK IN
    PLACE (the stage enriches the EDL a human then reviews) + a sibling MATCH.md and
    MATCH.json. One measure pass (inside conduct); the decisions carry the measured
    profiles the report needs, and MATCH.json carries the decisions themselves so the
    report's claim can be checked against the EDL later (design 2026-09-09 §2).
    Returns a status dict.

    `geo.edl` is used VERBATIM, never resolve()d against geometry_path's directory: it is
    stored exactly as edl_to_reel wrote it (design 2026-08-30 §2.2), and a relative path
    that does not resolve from the CURRENT directory fails loud in EDL.from_json rather
    than silently reading a different file.

    The REGIONS.json declaration (design 2026-09-15 §4), when the project is known and
    the file exists beside it, is found by _find_regions and threaded through conduct
    into every measure_crop call — one declaration governs the whole reel."""
    geo = ReelGeometry.from_json(geometry_path)
    edl = EDL.from_json(geo.edl)
    spec_obj = Spec.from_json(spec) if spec else None
    preset = moodpreset.resolve(spec_obj.mood) if spec_obj is not None else None
    bias, bias_source = _resolve_bias(spec_obj, preset)
    declared = _find_regions(geo)
    out, target, decisions, k = conduct(geo, edl, eps=eps, force=force, bias=bias,
                                        decl=declared.regions)
    # the reel's ONE common target (design §3) — deriving it from the episodes' own
    # tone_dst would fail on the reel where every episode was skipped (all None)
    out = replace(out, tone_target=target)
    write_edl(out, geo.edl)       # re-stamp: match_grade is a legitimate tool, and its
                                  # output is the tool's output (design §4)
    sources = [e.source for e in edl.episodes]
    lifts = matchgrade.toe_lifts([(e.tone_src, e.tone_dst) for e in out.episodes],
                                 offset=bias[0] * k)
    for i, lo, hi in lifts:
        print(_toe_lift_line(i, sources[i], lo, hi, bias[0] * k).removeprefix("> "),
              file=sys.stderr)
    md_path = Path(geo.edl).parent / "MATCH.md"
    md_path.write_text(_report_md(sources, target, decisions, eps,
                                  bias=bias, bias_source=bias_source,
                                  mood=preset.name if preset is not None else None, k=k,
                                  declared=declared, lifts=lifts))
    # The machine-readable twin (design 2026-09-09 §2). MATCH.md's claim — "8/8
    # episodes authored a tone pair" — was prose, and the EDL written an hour later
    # carried five with nothing able to notice. The decisions are what the report
    # ASSERTS, so they are what a reader compares against the EDL; `geo.edl` is
    # recorded verbatim, exactly as it was used, so the reader opens the same file
    # this wrote back into.
    json_path = Path(geo.edl).parent / "MATCH.json"
    matchgrade.MatchReport(
        target=target, eps=eps, decisions=tuple(decisions), edl=geo.edl,
        bias=bias, bias_source=bias_source, bias_scale=k,
        mood=preset.name if preset is not None else None,
        # The declaration state reaches MATCH.json too, not only MATCH.md's prose
        # (whole-branch review, finding 5). A later `montage status` reading this
        # file must be able to tell "no declaration" from "could not look" — the
        # §2.1 distinction — and a claim that lives only in prose cannot be checked,
        # which is the reason this twin exists at all.
        regions=declared.state, regions_at=declared.detail).write(json_path)
    skipped = Counter(d.reason for d in decisions if d.action == "skip")
    return {"status": "written", "edl": geo.edl, "md": str(md_path),
            "json": str(json_path),
            "target": list(target), "eps": eps,
            "mood": preset.name if preset is not None else None,
            "bias_source": bias_source, "bias_scale": k,
            "regions": declared.state, "regions_at": declared.detail,
            "authored": sum(1 for d in decisions if d.action == "author"),
            "skipped": dict(skipped),
            "toe_lifts": [{"index": i, "source": sources[i], "from": lo, "to": hi}
                          for i, lo, hi in lifts]}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="match-grade conductor — author tone_src/tone_dst across an EDL (§10)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="measure every episode → common target → author tone pairs",
                       description="measure every episode's tracked crop, compute one "
                                   "common reel tone target, and author tone_src/tone_dst "
                                   "on the episodes that deviate past --eps → a rewritten "
                                   "EDL.json plus MATCH.json and MATCH.md.")
    b.add_argument("--geometry", required=True,
                  help="GEOMETRY.json from edl_to_reel --stop-after-geometry; it names "
                       "the EDL this writes back")
    b.add_argument("--eps", type=float, default=matchgrade.MATCH_EPS,
                   help=f"skip an episode within this many luma units of the target "
                        f"(default {matchgrade.MATCH_EPS})")
    b.add_argument("--force", action="store_true",
                   help="re-author even hand-authored/previously-conducted episodes")
    b.add_argument("--spec", default=None,
                   help="SPEC.json — its mood displaces the common tone target, "
                        "unless SPEC.tone_bias is authored, which outranks the "
                        "preset's own displacement (absent --spec: the plain "
                        "median, exactly as before)")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    result = write_match(a.geometry, eps=a.eps, force=a.force, spec=a.spec)
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
