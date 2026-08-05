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

from scripts.lib import provenance

_KINDS = ("required", "optional", "deferred")
_CHECKPOINTS = (None, "spec", "edl", "final")


@dataclass(frozen=True)
class Stage:
    """One v1-conveyor stage the router sequences. `artifact` is a glob (under the
    run dir, or the out dir when `in_out`) whose presence marks the stage done — the
    resume-for-free marker (design line 510)."""
    key: str
    artifact: str
    kind: str
    runner: str
    checkpoint: str | None
    in_out: bool = False

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"Stage.kind must be one of {_KINDS}, got {self.kind!r}")
        if self.checkpoint not in _CHECKPOINTS:
            raise ValueError(
                f"Stage.checkpoint must be one of {_CHECKPOINTS}, got {self.checkpoint!r}")


V1_STAGES: tuple[Stage, ...] = (
    Stage("project-init", "project.json", "required",
          "project-init SKILL -> project_init CLI", "spec"),
    Stage("footage-intake", "FOOTAGE.json", "required",
          "footage-intake SKILL -> intake CLI", None),
    # required, not optional (design 2026-08-05 §2.5): a run must not reach the cut
    # without a SHEETS.md on disk. It gates the PRESENCE of the artifact, not its
    # use, and not a guarantee it holds a frame (a genuinely empty selection still
    # writes an honest zero-frame SHEETS.md, design §7) — see the design's §9
    # honest limit.
    Stage("contact-sheet", "SHEETS.md", "required",
          "contact_sheet build CLI (run by using-montage; edit-plan reads the sheets)",
          None),
    Stage("reel-brief", "SPEC.json", "optional", "reel-brief SKILL -> reel_brief CLI", "spec"),
    Stage("trend-scan", "TRENDS.md", "deferred", "5.4 - not built", None),
    Stage("edit-plan", "EDL.json", "required",
          "edit-plan SKILL -> edit_plan build CLI", "edl"),
    Stage("music-and-mood", "MUSIC.json", "optional",
          "beats CLI (absent -> silent reel)", None),
    Stage("pacing", "PACING.md", "optional",
          "pacing SKILL -> pacing CLI (fits the EDL's cuts; edit-plan re-runs with "
          "--pacing to apply)", None),
    Stage("match-grade", "MATCH.md", "optional",
          "match-grade SKILL -> match_grade build CLI (opt-in; run AFTER pacing settles "
          "the cut, before deliver)", None),
    Stage("assemble-draft", "draft.mp4", "optional",
          "draft CLI (optional QA preview)", "edl"),
    Stage("titles", "TITLES.json", "optional",
          "titles SKILL -> titles build CLI (optional on-screen text)", "final"),
    Stage("deliver", "REEL_v*.*", "required",
          "edl_to_reel CLI", "final", in_out=True),
    # required, not optional (design §8): the reviewer stage was skipped outright on
    # the 2026-08-03 run because `next` never pointed at it, and a gate that costs
    # nothing to skip is not a gate.
    Stage("reel-review", "REVIEW.json", "required",
          "reel-review SKILL -> reel_review build CLI (editorial CP3 review)", "final"),
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


def next_action(run_dir: str, out_dir: str | None = None) -> dict:
    """Inspect a run dir -> the ordered v1 stages with each stage's state, the next
    required action, and whether the reel is delivered. out_dir defaults to
    <run_dir>/out (where deliver versions REEL_v{n}). State per stage:
      done     - artifact exists (resume-for-free, design line 510)
      next     - the FIRST required stage whose artifact is missing (run this)
      pending  - a required stage after `next` still missing its artifact
      optional - an optional built stage not yet produced (music/pacing); never blocks
      skip     - a deferred stage (trend-scan); named, not silent
    `deliveries` reports each delivered file's attestation state from the sidecar
    alone — cheap, because the router calls status constantly. `verify()` re-hashes.
    Returns {"stages":[{key,artifact,kind,state,checkpoint,runner}, ...] in order,
             "next": <stage key | None>, "delivered": <bool>, "deliveries": [...]}."""
    run = Path(run_dir)
    out = Path(out_dir) if out_dir is not None else run / "out"
    stages: list[dict] = []
    next_key: str | None = None
    delivered = False
    for st in V1_STAGES:
        base = out if st.in_out else run
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
        stages.append({"key": st.key, "artifact": st.artifact, "kind": st.kind,
                       "state": state, "checkpoint": st.checkpoint, "runner": st.runner})
    return {"stages": stages, "next": next_key, "delivered": delivered,
            "deliveries": _deliveries(out)}


def verify(run_dir: str, out_dir: str | None = None) -> dict:
    """Re-hash every delivered reel against its attestation (design §6). Run once at
    CP3, where the cost is irrelevant and the answer matters: status answers "is there
    a record", verify answers "is this file the one the record describes"."""
    out = Path(out_dir) if out_dir is not None else Path(run_dir) / "out"
    return {"deliveries": _deliveries(out, rehash=True)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="montage router status inspector (stage 5.1)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status",
                       help="report which conveyor stage is next in a run dir")
    s.add_argument("--run-dir", required=True,
                   help="the project/run dir where stage artifacts land")
    s.add_argument("--out-dir", default=None,
                   help="delivery dir (default <run-dir>/out)")
    v = sub.add_parser("verify",
                       help="re-hash delivered reels against their attestations (CP3)")
    v.add_argument("--run-dir", required=True,
                   help="the project/run dir where stage artifacts land")
    v.add_argument("--out-dir", default=None, help="delivery dir (default <run-dir>/out)")
    a = ap.parse_args()
    result = next_action(a.run_dir, a.out_dir) if a.cmd == "status" else verify(a.run_dir, a.out_dir)
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
