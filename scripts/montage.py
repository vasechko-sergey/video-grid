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
    Stage("reel-brief", "SPEC.json", "optional", "reel-brief SKILL -> reel_brief CLI", "spec"),
    Stage("trend-scan", "TRENDS.md", "deferred", "5.4 - not built", None),
    Stage("music-and-mood", "MUSIC.json", "optional",
          "beats CLI (absent -> silent reel)", None),
    Stage("pacing", "PACING.md", "optional", "pacing SKILL -> pacing CLI", None),
    Stage("edit-plan", "EDL.json", "required",
          "edit-plan SKILL -> edit_plan build CLI", "edl"),
    Stage("assemble-draft", "draft.mp4", "optional",
          "draft CLI (optional QA preview)", "edl"),
    Stage("titles", "TITLES.json", "optional",
          "titles SKILL -> titles build CLI (optional on-screen text)", "final"),
    Stage("deliver", "REEL_v*.*", "required",
          "edl_to_reel CLI", "final", in_out=True),
)


def _exists(base: Path, glob: str) -> bool:
    """True iff at least one file matches `glob` under `base` (empty glob -> False)."""
    if not glob:
        return False
    return any(base.glob(glob))


def next_action(run_dir: str, out_dir: str | None = None) -> dict:
    """Inspect a run dir -> the ordered v1 stages with each stage's state, the next
    required action, and whether the reel is delivered. out_dir defaults to
    <run_dir>/out (where deliver versions REEL_v{n}). State per stage:
      done     - artifact exists (resume-for-free, design line 510)
      next     - the FIRST required stage whose artifact is missing (run this)
      pending  - a required stage after `next` still missing its artifact
      optional - an optional built stage not yet produced (music); never blocks
      skip     - a deferred stage (trend-scan/pacing); named, not silent
    Returns {"stages":[{key,artifact,kind,state,checkpoint,runner}, ...] in order,
             "next": <stage key | None>, "delivered": <bool>}."""
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
    return {"stages": stages, "next": next_key, "delivered": delivered}


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
    a = ap.parse_args()
    print(json.dumps(next_action(a.run_dir, a.out_dir), indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
