"""Stage 5.1 router backbone (design docs/specs/2026-07-12-using-montage-design.md):
a deterministic stage-status INSPECTOR for the montage conveyor. It reports where a
(possibly resumed) run stands and which stage is next; it does NOT run stages — the
front-half judgment steps (footage-intake cast-naming, edit-plan selection authoring)
are agent-interactive, so the using-montage SKILL runs the stages and consults
next_action() for the resume/next decision. Mirrors intake.py <-> footage-intake:
mechanical inspection here, judgment in the SKILL."""
import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from scripts.lib import constraints, matchgrade, provenance, runlayout

_KINDS = ("required", "optional", "deferred")
_CHECKPOINTS = (None, "spec", "edl", "final")


@dataclass(frozen=True)
class Stage:
    """One v1-conveyor stage the router sequences. `artifact` is a glob whose presence
    inside `bucket` marks the stage done — the resume-for-free marker (design line
    510). The bucket is the artifact's LIFETIME (design 2026-08-26 §1), which is why
    an artifact written anywhere else is not seen and the stage re-runs."""
    key: str
    artifact: str
    kind: str
    runner: str
    checkpoint: str | None
    bucket: str = "reel"

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"Stage.kind must be one of {_KINDS}, got {self.kind!r}")
        if self.checkpoint not in _CHECKPOINTS:
            raise ValueError(
                f"Stage.checkpoint must be one of {_CHECKPOINTS}, got {self.checkpoint!r}")
        if self.bucket not in runlayout.BUCKETS:
            raise ValueError(f"Stage.bucket must be one of {runlayout.BUCKETS}, "
                             f"got {self.bucket!r}")


V1_STAGES: tuple[Stage, ...] = (
    Stage("project-init", "project.json", "required",
          "project-init SKILL -> project_init CLI", "spec", "run"),
    Stage("footage-intake", "FOOTAGE.json", "required",
          "footage-intake SKILL -> intake CLI", None, "footage"),
    # required, not optional (design 2026-08-05 §2.5): a run must not reach the cut
    # without a SHEETS.md on disk. It gates the PRESENCE of the artifact, not its
    # use, and not a guarantee it holds a frame (a genuinely empty selection still
    # writes an honest zero-frame SHEETS.md, design §7) — see the design's §9
    # honest limit.
    Stage("contact-sheet", "SHEETS.md", "required",
          "contact_sheet build CLI (run by using-montage; edit-plan reads the sheets)",
          None, "footage"),
    Stage("reel-brief", "SPEC.json", "optional",
          "reel-brief SKILL -> reel_brief CLI", "spec", "reel"),
    Stage("trend-scan", "TRENDS.md", "deferred", "5.4 - not built", None, "reel"),
    Stage("edit-plan", "EDL.json", "required",
          "edit-plan SKILL -> edit_plan build CLI", "edl", "reel"),
    Stage("music-and-mood", "MUSIC.json", "optional",
          "beats CLI (absent -> silent reel)", None, "reel"),
    Stage("pacing", "PACING.md", "optional",
          "pacing SKILL -> pacing CLI (fits the EDL's cuts; edit-plan re-runs with "
          "--pacing to apply)", None, "reel"),
    Stage("episodes-geometry", "GEOMETRY.json", "required",
          "edl_to_reel --stop-after-geometry (stabilize, track and gate every "
          "episode; no encode) — the seam match-grade measures the shipped crop in",
          None, "episodes"),
    Stage("match-grade", "MATCH.json", "required",
          "match-grade SKILL -> match_grade build --geometry (measures each episode's "
          "own crop; run AFTER episodes-geometry, before the render)", None, "reel"),
    Stage("assemble-draft", "draft.mp4", "optional",
          "draft CLI (optional QA preview)", "edl", "reel"),
    Stage("titles", "TITLES.json", "optional",
          "titles SKILL -> titles build CLI (optional on-screen text)", "final", "reel"),
    Stage("episodes", "EPISODES.json", "required",
          "edl_to_reel --from-geometry (renders every episode over its frozen route, "
          "then stops at the QC seam)", None, "episodes"),
    # required, not optional (design 2026-08-08 §1): a reel assembled over an episode
    # nobody judged is exactly what the 2026-08-03 run shipped. The stage gates the
    # artifact's presence and its digest binding — never proof that anyone looked (§12).
    Stage("episode-qc", "EPISODE_QC.json", "required",
          "episode-qc SKILL -> episode_qc pack, one judge per episode (cap 3), "
          "episode_qc build", None, "episodes"),
    Stage("deliver", "REEL_v*.*", "required",
          "edl_to_reel --from-episodes (gates on EPISODE_QC.json, then assembles)",
          "final", "deliveries"),
    # required, not optional (design §8): the reviewer stage was skipped outright on
    # the 2026-08-03 run because `next` never pointed at it, and a gate that costs
    # nothing to skip is not a gate.
    Stage("reel-review", "REVIEW.json", "required",
          "reel-review SKILL -> reel_review build CLI (editorial CP3 review)",
          "final", "reel"),
)


def _exists(base: Path, glob: str) -> bool:
    """True iff at least one file matches `glob` under `base` (empty glob -> False)."""
    if not glob:
        return False
    return any(base.glob(glob))


def _deliveries(out: Path, *, rehash: bool = False) -> list[dict]:
    """One entry per delivered reel with its attestation state (design §6). The
    sidecars share the REEL_v* prefix, so they are filtered out by suffix — listing
    REEL_v1.attest.json as a delivery would double every reel."""
    return [provenance.verify_delivery(p, rehash=rehash)
            for p in sorted(out.glob("REEL_v*")) if p.suffix != ".json"]


def _constraints(run: Path) -> dict:
    """The editorial rules binding a re-cut, so a human need not open
    CONSTRAINTS.json to see them (design 2026-08-17 §3). Three states, each
    named: absent, authored, or present-and-unreadable.

    The load refusal is CAUGHT here, and that is not a softening of it. This is
    the inspector the router calls constantly, so letting a typo in a rule file
    replace the whole status report with a traceback helps nobody — and
    reporting `rules: []` for an unreadable file would answer "nothing binds
    this cut" when the truth is "nobody can tell", which is the worse of the two
    lies. The enforcement point does not move: write_edit_plan still discovers
    this file, still loads it through the same refusing constructor, and still
    has no waiver."""
    p = run / "CONSTRAINTS.json"
    if not p.exists():
        return {"present": False, "rules": [], "error": None}
    try:
        loaded = constraints.Constraints.from_json(p)
    except ValueError as e:
        return {"present": True, "rules": [], "error": str(e)}
    return {"present": True, "rules": [r.to_dict() for r in loaded.rules],
            "error": None}


def _match_grade_state(reel_dir: Path) -> tuple[str, str]:
    """("fresh"|"stale", reason) for the conductor's report against the EDL today.

    The instrument is the authored PAIRS, not a digest — match_grade rewrites the EDL
    itself and edit_plan --pacing rewrites it again, so a whole-file digest would fire
    on the sanctioned rewrite too (design 2026-09-09 §1/§2).

    Both files are read as RAW JSON on purpose. EDL.from_json refuses a tampered file,
    and this is the inspector the router calls constantly: a typo or a tampered stamp
    must not replace the whole status report with a traceback. That is the rule
    _constraints already records, for the same reason.

    Anything that cannot be read — corrupt MATCH.json, a named EDL that is not there —
    is reported as `stale` with the cause named, never as fresh: a report that cannot
    be shown to describe the EDL is not one a reader should trust, and the remedy is
    the same either way (re-run the conductor).

    Hashes nothing: status is called constantly.
    """
    mp = reel_dir / "MATCH.json"
    if not mp.exists():
        return "stale", "there is no MATCH.json — run `match_grade build --geometry`"
    try:
        report = matchgrade.MatchReport.from_json(mp)
    except (ValueError, OSError) as e:
        return "stale", f"MATCH.json is corrupt or unreadable ({e})"
    try:
        edl_raw = json.loads(Path(report.edl).read_text())
        episodes = edl_raw["episodes"]
        if not isinstance(episodes, list) or not all(isinstance(e, dict) for e in episodes):
            raise TypeError("'episodes' is not a list of episode objects")
    except (OSError, ValueError, KeyError, TypeError) as e:
        return "stale", (f"MATCH.json names {report.edl}, which cannot be read as an EDL "
                         f"({e}) — nothing can check what this report claims")
    pairs = [(_opt_profile(e.get("tone_src")), _opt_profile(e.get("tone_dst")))
             for e in episodes]
    drift = matchgrade.tone_drift(report.decisions, pairs)
    if not drift:
        return "fresh", ""
    return "stale", ("; ".join(drift) + ". Re-run `match_grade build --geometry` — a "
                     "later `edit_plan build --pacing` wipes authored tone, which is "
                     "what this reports. If a reel already shipped from this EDL, "
                     "re-render (`edl_to_reel --from-geometry`) and re-deliver too — "
                     "re-conducting alone rewrites only the pairs, never pixels already "
                     "rendered")


def _opt_profile(v) -> tuple[float, float, float] | None:
    """A raw JSON tone anchor triple, or None. Anything malformed reads as None, which
    tone_drift reports as a wiped pair — the reader's job is to notice a difference,
    not to validate the EDL, whose own constructor does that where it is loaded."""
    if not (isinstance(v, (list, tuple)) and len(v) == 3):
        return None
    try:
        return (float(v[0]), float(v[1]), float(v[2]))
    except (TypeError, ValueError):
        return None


def _newest_delivery(out: Path) -> str | None:
    """The highest-numbered REEL_v{n} file in the deliveries bucket, by name.

    The same monotone identity _next_version defends: v10 sorts before v2 as a string,
    so the version number is parsed, never sorted lexically."""
    best: tuple[int, str] | None = None
    for p in out.glob("REEL_v*"):
        m = re.match(r"REEL_v(\d+)\.", p.name)
        if m and p.suffix != ".json" and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), p.name)
    return None if best is None else best[1]


def _as_str(v: object) -> str:
    """A raw JSON scalar, kept only if it is already a string.

    `Path()` raises on a number/bool/list/dict — and both `_review_state` and
    `_verify_review` read `reel`/`reel_digest` from hand-editable JSON with no typed
    constructor in front of them, the same reason they read raw JSON at all. Anything
    but a string reads as "", the same value an absent or null field already
    produces: the reader's job is to notice a mismatch, not to validate REVIEW.json's
    shape."""
    return v if isinstance(v, str) else ""


def _review_state(reel_dir: Path, out: Path) -> tuple[str, str]:
    """("fresh"|"stale", reason) for REVIEW.json against the newest delivery.

    Names, not bytes — this is the cheap half of the split the module already declares
    for deliveries: status answers "is there a record", verify answers "is this file
    the one the record describes". The run's actual failure was a review two VERSIONS
    stale, which a name comparison catches for free; a file swapped in place under the
    same name is verify's business, and 0.3.0's monotone versioning already stops the
    pipeline producing one.

    Hashes nothing.
    """
    rp = reel_dir / "REVIEW.json"
    if not rp.exists():
        return "stale", "there is no REVIEW.json — run the reel-review stage"
    try:
        judged = _as_str(json.loads(rp.read_text()).get("reel"))
    except (OSError, ValueError, AttributeError) as e:
        return "stale", f"REVIEW.json is corrupt or unreadable ({e})"
    newest = _newest_delivery(out)
    if newest is None:
        return "stale", "no delivered reel to review — deliver first"
    if Path(judged).name != newest:
        return "stale", (f"this review judged {Path(judged).name or '(nothing named)'} "
                         f"and the newest delivery is {newest} — re-run the reel-review "
                         f"stage against the reel that shipped")
    return "fresh", ""


def _partials(out: Path) -> list[str]:
    """Deliveries that were interrupted mid-encode: the dotted partials deliver leaves
    behind (design 2026-09-09 §5). The partial IS the record — there is no separate
    marker to go stale."""
    return sorted(p.name for p in out.glob(runlayout.PARTIAL_GLOB))


# The two stages whose artifact asserts something checkable about another file. Every
# other stage's artifact is its own statement, and existence is the whole of what
# status can say about it.
_FRESHNESS = {"match-grade": lambda lay: _match_grade_state(lay.reel_dir),
              "reel-review": lambda lay: _review_state(lay.reel_dir, lay.deliveries)}


def next_action(run_dir: str, reel: str = runlayout.DEFAULT_REEL) -> dict:
    """Inspect a run dir -> the ordered v1 stages with each stage's state, the next
    required action, and whether the reel is delivered. Every artifact is resolved
    through RunLayout, which is what makes this the enforcement point: a file written
    outside the layout is not seen, the stage reads as not done, and the router runs
    it again into the canonical path (design 2026-08-26 §5). State per stage:
      done     - artifact exists (resume-for-free, design line 510)
      next     - the FIRST required stage whose artifact is missing (run this)
      pending  - a required stage after `next` still missing its artifact
      optional - an optional built stage not yet produced (music/pacing); never blocks
      skip     - a deferred stage (trend-scan); named, not silent
      stale    - the artifact exists but no longer describes what is on disk: a
                 match-grade report whose authored pairs the EDL has lost, or a review
                 of an older delivery. Not done, so `next` points back at it — that is
                 the teeth, and there is no separate refusal (design 2026-09-09 §6)
    `deliveries` reports each delivered file's attestation state from the sidecar
    alone — cheap, because the router calls status constantly. `verify()` re-hashes.
    `constraints` reports the editorial rules that bind a re-cut (see _constraints).
    `legacy_layout` marks a 0.2.x run whose artifacts sit at the run root: the skill
    asks rather than re-scanning every clip into an apparently empty run (§7).
    Returns {"stages":[{key,artifact,bucket,path,kind,state,stale_reason,checkpoint,
             runner}, ...], "next": <stage key | None>, "delivered": <bool>,
             "deliveries": [...], "interrupted": [...], "constraints": {...},
             "reel": <str>, "reels": [...],
             "layout": {bucket: path}, "legacy_layout": <bool>}."""
    run = Path(run_dir)
    lay = runlayout.RunLayout(run, reel)
    stages: list[dict] = []
    next_key: str | None = None
    delivered = False
    for st in V1_STAGES:
        base = lay.bucket(st.bucket)
        done = _exists(base, st.artifact)
        stale_reason = ""
        if done and st.key in _FRESHNESS:
            state_name, stale_reason = _FRESHNESS[st.key](lay)
            done = state_name == "fresh"
        if st.kind == "deferred":
            state = "skip"
        elif st.kind == "optional":
            state = "done" if done else "optional"
        elif done:
            state = "done"
        elif stale_reason:
            # the artifact IS there; it just no longer describes what is on disk. A
            # fifth state, because "next" alone would say the stage never ran
            # (design 2026-09-09 §6).
            state = "stale"
            if next_key is None:
                next_key = st.key
        elif next_key is None:
            state = "next"
            next_key = st.key
        else:
            state = "pending"
        if st.key == "deliver":
            delivered = done
        stages.append({"key": st.key, "artifact": st.artifact, "bucket": st.bucket,
                       "path": str(base / st.artifact), "kind": st.kind,
                       "state": state, "stale_reason": stale_reason,
                       "checkpoint": st.checkpoint, "runner": st.runner})
    return {"stages": stages, "next": next_key, "delivered": delivered,
            "deliveries": _deliveries(lay.deliveries), "interrupted": _partials(lay.deliveries),
            "constraints": _constraints(run),
            "reel": reel, "reels": runlayout.reel_names(run),
            "layout": lay.to_dict(), "legacy_layout": runlayout.is_legacy_run(run)}


def _verify_review(reel_dir: Path, out: Path) -> dict:
    """Re-hash the reel REVIEW.json judged against the digest it recorded — the
    expensive half of the split status declares (design 2026-09-09 §3).

    Three states, each a different true statement: `unbound` (no digest — a review
    written before this binding, which asserts nothing about bytes), `bound` (the file
    is the one reviewed), `digest-mismatch` (it is not)."""
    rp = reel_dir / "REVIEW.json"
    if not rp.exists():
        return {"state": "absent", "detail": "no REVIEW.json in this reel"}
    try:
        d = json.loads(rp.read_text())
        reel, want = _as_str(d.get("reel")), _as_str(d.get("reel_digest"))
    except (OSError, ValueError, AttributeError) as e:
        return {"state": "unreadable", "detail": f"REVIEW.json is corrupt ({e})"}
    if not want:
        return {"state": "unbound", "reel": Path(reel).name,
                "detail": "this review records no reel digest, so nothing binds it to "
                          "the bytes it judged — re-run the reel-review stage"}
    if not reel or not Path(reel).exists():
        # `Path("").exists()` alone would say True here (pathlib normalizes "" to
        # ".", the cwd, which always exists) while the raw `open()` behind
        # digest_file() below does NOT do that normalization and raises
        # FileNotFoundError on "" — so an empty/malformed `reel` must be caught
        # explicitly, before it ever reaches Path.exists()'s cwd-shaped answer.
        return {"state": "missing", "reel": Path(reel).name,
                "detail": f"the reviewed reel {reel} is not on disk any more"}
    actual = provenance.digest_file(reel)
    if actual != want:
        return {"state": "digest-mismatch", "reel": Path(reel).name,
                "detail": (f"the file hashes to {actual[:12]}… but the review records "
                           f"{want[:12]}… — this is not the reel that was reviewed")}
    return {"state": "bound", "reel": Path(reel).name, "detail": ""}


def verify(run_dir: str, reel: str = runlayout.DEFAULT_REEL) -> dict:
    """Re-hash every delivered reel against its attestation, and the reviewed reel
    against REVIEW.json's own digest (design §6, 2026-09-09 §3). Run once at CP3, where
    the cost is irrelevant and the answer matters: status answers "is there a record",
    verify answers "is this file the one the record describes"."""
    lay = runlayout.RunLayout(Path(run_dir), reel)
    return {"deliveries": _deliveries(lay.deliveries, rehash=True),
            "review": _verify_review(lay.reel_dir, lay.deliveries)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="montage router status inspector (stage 5.1)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status",
                       help="report which conveyor stage is next in a run dir")
    s.add_argument("--run-dir", required=True,
                   help="the project/run dir where stage artifacts land")
    s.add_argument("--reel", default=runlayout.DEFAULT_REEL,
                   help=f"which reel variant to inspect (default {runlayout.DEFAULT_REEL})")
    v = sub.add_parser("verify",
                       help="re-hash delivered reels against their attestations (CP3)")
    v.add_argument("--run-dir", required=True,
                   help="the project/run dir where stage artifacts land")
    v.add_argument("--reel", default=runlayout.DEFAULT_REEL,
                   help=f"which reel variant to inspect (default {runlayout.DEFAULT_REEL})")
    a = ap.parse_args()
    result = next_action(a.run_dir, a.reel) if a.cmd == "status" else verify(a.run_dir, a.reel)
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
