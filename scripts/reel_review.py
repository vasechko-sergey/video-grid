"""Reel-review writer (design docs/specs/2026-07-18-reel-review-editorial-design.md,
§5.13 Slice B). The thin mechanical half: validate the reviewer subagent's RAW findings
JSON into a typed Review (fail-loud on a malformed finding), write REVIEW.json + REVIEW.md.
Judgment (the editorial verdict) is the reviewer subagent's, dispatched by
skills/reel-review/SKILL.md. Mirror of reel_brief.py / edit_plan.py — contract in lib,
driver here; the raw-findings → typed-artifact idiom is edit_plan's selection.json → EDL.json.
"""
import argparse
import json
from itertools import accumulate
from pathlib import Path

from PIL import Image

from scripts.lib import assembly, prompts, provenance, runlayout
from scripts.lib.look import LookSpec
from scripts.lib.models import MusicSpec, ReelManifest
from scripts.lib.review import Finding, Review

# The stills' margins, in seconds: the hook no earlier than _HOOK_MIN, the ending no
# later than _END_MIN before the end, and both _CLEAR past the bookend fade, which
# darkens a frame by the picture's own fade rather than by anything the `colour` axis
# should read as a grade (deliver._title_times clamps its look-gate samples the same way).
_HOOK_MIN, _END_MIN, _CLEAR = 0.5, 1.0, 0.1


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


def still_times(clip_durs: list[float], reel_dur: float,
                look: LookSpec | None) -> dict[str, float]:
    """The reviewer's stills: the hook, the ending and one mid-frame per episode, every
    one clamped out of the reel's own bookend fade."""
    head = look.head if look is not None else 0.0
    tail = look.tail if look is not None else 0.0
    lo, hi = max(_HOOK_MIN, head + _CLEAR), reel_dur - max(_END_MIN, tail + _CLEAR)
    if hi < lo:
        raise ValueError(f"a {reel_dur:g}s reel leaves no frame outside its {head:g}s/"
                         f"{tail:g}s bookend fades to grab a still from")
    starts = [0.0, *accumulate(clip_durs)][:-1]
    mids = {f"mid{i}": min(max(s + d / 2, lo), hi)
            for i, (s, d) in enumerate(zip(starts, clip_durs))}
    return {"hook": lo, "ending": hi, **mids}


def _report_bound(reel: str, report: dict, at: Path) -> bool:
    """True when the delivery's attestation names this very report, False when the reel
    has no attestation. A report from another render is refused: `build/` holds only
    the LAST render's report, and a later render that stopped rewrites it."""
    att = provenance.attest_path(reel)
    if not att.is_file():
        return False
    named = provenance.Attestation.from_json(att).report_digest
    if named != provenance.digest_obj(report):
        raise ValueError(
            f"the check_reel report at {at} judged a different render than {reel} — its "
            f"attestation names report {named[:12]}, this one is "
            f"{provenance.digest_obj(report)[:12]}. build/ keeps only the last render's "
            f"report: review the reel that report passed (`montage status` names the "
            f"newest delivery), or pass --report with the one this reel shipped with")
    return True


def _spec_block(reel_dir: Path) -> str:
    sj, sm = reel_dir / "SPEC.json", reel_dir / "SPEC.md"
    if not sj.is_file():
        return ("no SPEC — there is no brief. Judge against the EDL and the reel's "
                "evident intent, and say in your summary that you did.")
    md = sm.read_text() if sm.is_file() else "(no SPEC.md beside SPEC.json)"
    spec = json.dumps(json.loads(sj.read_text()), indent=1, ensure_ascii=False)
    return f"{md.rstrip()}\n\nSPEC.json:\n{spec}"


def _music_block(reel_dir: Path) -> str:
    mj = reel_dir / "MUSIC.json"
    if not mj.is_file():
        return "silent reel — no MUSIC.json beside the EDL."
    m = MusicSpec.from_json(mj)
    # music_fetch writes the track's identity beside the file it downloaded.
    meta = Path(m.track).with_suffix(".json")
    if meta.is_file():
        t = json.loads(meta.read_text())
        name = f"{t['artist']} — {t['title']} ({t['source']}, licence: {t['license']})"
    else:
        name = Path(m.track).name
    pacing = reel_dir / "PACING.md"
    return "\n\n".join([
        f"Track: {name}, from {m.start_offset:g}s for {m.duration:g}s at "
        f"{m.tempo:.1f} BPM; {len(m.beats)} beats, {len(m.bars)} bars, "
        f"{len(m.vocal_spans)} vocal spans.",
        pacing.read_text().rstrip() if pacing.is_file()
        else "No PACING.md — the cut was not fitted to the music."])


def pack(reel: str, reel_dir: str, *, report: str | None = None) -> dict:
    """Grab the reviewer's stills from the delivered reel and write its prompt, filled
    (retro 2026-10-16 S14: the second real run's agent grabbed the stills with an
    inline script and wrote a second one to fill the template). Returns a status dict."""
    r = Path(reel_dir)
    if r.parent.name != "reels":
        raise ValueError(f"--reel-dir {reel_dir} is not a reel directory — pass "
                         f"<run>/reels/<reel>, where EDL.md, episodes/ and build/ live")
    lay = runlayout.RunLayout(r.parent.parent, r.name)
    if not Path(reel).is_file():
        raise ValueError(f"--reel {reel} names no file — point it at the delivered reel "
                         f"(`montage status` names the newest REEL_v{{n}}.mp4)")
    rep = Path(report) if report else lay.build / "reel" / "reel_report.json"
    if not rep.is_file():
        raise ValueError(f"no check_reel report at {rep} — the delivering run writes it "
                         f"there; pass --report if it lives elsewhere")
    report_obj = json.loads(rep.read_text())
    bound = _report_bound(reel, report_obj, rep)
    edl_md = lay.reel_dir / "EDL.md"
    if not edl_md.is_file():
        raise ValueError(f"no EDL.md in {lay.reel_dir} — the reviewer judges the reel "
                         f"against its plan; run `edit_plan build` there")
    rm = ReelManifest.from_json(lay.episodes / "EPISODES.json")
    times = still_times([assembly.probe_duration(e.clip) for e in rm.episodes],
                        assembly.probe_duration(reel), rm.look)
    out = lay.build / "_review"
    out.mkdir(parents=True, exist_ok=True)
    frames = assembly.frames_rgb(reel, list(times.values()), assembly.probe_stream(reel).fps)
    stills = []
    for name, frame in zip(times, frames):
        Image.fromarray(frame).save(out / f"{name}.png")
        stills.append(str((out / f"{name}.png").resolve()))
    text = prompts.render(prompts.REVIEWER_TEMPLATE, {
        "SPEC": _spec_block(lay.reel_dir),
        "EDL_MD": edl_md.read_text().rstrip(),
        "REPORT_JSON": json.dumps(report_obj, indent=1, ensure_ascii=False),
        "MUSIC": _music_block(lay.reel_dir),
        "REEL_PATH": str(Path(reel).resolve()),
        "STILL_PATHS": "\n".join(f"{n}: {p}" for n, p in zip(times, stills)),
        "FINDINGS_PATH": str((lay.reel_dir / "review_findings.json").resolve()),
    })
    prompt = out / "reviewer_prompt.md"
    prompt.write_text(text)
    return {"status": "packed", "prompt": str(prompt), "stills": stills,
            "report": str(rep), "report_bound": bound}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="write REVIEW.json + REVIEW.md — the editorial reel review (§5.13 Slice B)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="validate the reviewer's raw findings -> REVIEW.json + REVIEW.md",
                       description="validate the reviewer subagent's raw findings into "
                                   "REVIEW.json + REVIEW.md, stamping the reel's own "
                                   "digest read from disk. The CP3 editorial verdict.")
    b.add_argument("--findings", required=True,
                   help="the reviewer subagent's raw findings JSON (list or {summary,findings})")
    b.add_argument("--reel", required=True, help="the reviewed reel path (e.g. out/REEL_v1.mp4)")
    b.add_argument("--spec", default="", help="SPEC.json path or a short intent echo (spec_ref)")
    b.add_argument("--platform", default="", help="platform label for the report header")
    b.add_argument("--reviewer", default="", help="free note — which agent/model reviewed")
    b.add_argument("--out-dir", required=True, help="dir for REVIEW.json + REVIEW.md")
    k = sub.add_parser("pack", help="grab the stills and write the reviewer's filled prompt",
                       description="grab the hook, ending and per-episode stills from the "
                                   "delivered reel (clear of its bookend fade) and write "
                                   "build/_review/reviewer_prompt.md — the reviewer "
                                   "template filled with SPEC, EDL.md, the check_reel "
                                   "report and the music. Dispatch that file verbatim.")
    k.add_argument("--reel", required=True,
                   help="the delivered reel to review (deliveries/REEL_v{n}.mp4)")
    k.add_argument("--reel-dir", required=True,
                   help="<run>/reels/<reel> — where EDL.md, episodes/ and build/ live")
    k.add_argument("--report", default=None,
                   help="check_reel's report for this reel (default: "
                        "build/reel/reel_report.json); refused when the reel's "
                        "attestation names a different one")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    if a.cmd == "pack":
        print(json.dumps(pack(a.reel, a.reel_dir, report=a.report), indent=2))
        raise SystemExit(0)
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
