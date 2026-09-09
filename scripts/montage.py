"""Stage 5.1 router backbone (design docs/specs/2026-07-12-using-montage-design.md):
a deterministic stage-status INSPECTOR for the montage conveyor. It reports where a
(possibly resumed) run stands and which stage is next; it does NOT run stages — the
front-half judgment steps (footage-intake cast-naming, edit-plan selection authoring)
are agent-interactive, so the using-montage SKILL runs the stages and consults
next_action() for the resume/next decision. Mirrors intake.py <-> footage-intake:
mechanical inspection here, judgment in the SKILL."""
import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from scripts.lib import constraints, provenance, runlayout

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
    `deliveries` reports each delivered file's attestation state from the sidecar
    alone — cheap, because the router calls status constantly. `verify()` re-hashes.
    `constraints` reports the editorial rules that bind a re-cut (see _constraints).
    `legacy_layout` marks a 0.2.x run whose artifacts sit at the run root: the skill
    asks rather than re-scanning every clip into an apparently empty run (§7).
    Returns {"stages":[{key,artifact,bucket,path,kind,state,checkpoint,runner}, ...],
             "next": <stage key | None>, "delivered": <bool>, "deliveries": [...],
             "constraints": {...}, "reel": <str>, "reels": [...],
             "layout": {bucket: path}, "legacy_layout": <bool>}."""
    run = Path(run_dir)
    lay = runlayout.RunLayout(run, reel)
    stages: list[dict] = []
    next_key: str | None = None
    delivered = False
    for st in V1_STAGES:
        base = lay.bucket(st.bucket)
        done = _exists(base, st.artifact)
        if st.kind == "deferred":
            state = "skip"
        elif st.kind == "optional":
            state = "done" if done else "optional"
        elif done:
            state = "done"
        elif next_key is None:
            state = "next"
            next_key = st.key
        else:
            state = "pending"
        if st.key == "deliver":
            delivered = done
        stages.append({"key": st.key, "artifact": st.artifact, "bucket": st.bucket,
                       "path": str(base / st.artifact), "kind": st.kind,
                       "state": state, "checkpoint": st.checkpoint, "runner": st.runner})
    return {"stages": stages, "next": next_key, "delivered": delivered,
            "deliveries": _deliveries(lay.deliveries), "constraints": _constraints(run),
            "reel": reel, "reels": runlayout.reel_names(run),
            "layout": lay.to_dict(), "legacy_layout": runlayout.is_legacy_run(run)}


def verify(run_dir: str, reel: str = runlayout.DEFAULT_REEL) -> dict:
    """Re-hash every delivered reel against its attestation (design §6). Run once at
    CP3, where the cost is irrelevant and the answer matters: status answers "is there
    a record", verify answers "is this file the one the record describes"."""
    return {"deliveries": _deliveries(
        runlayout.RunLayout(Path(run_dir), reel).deliveries, rehash=True)}


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
