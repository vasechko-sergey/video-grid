# Run-Layout Lifetimes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the montage run directory an interior organised by lifetime, so the half that cannot be rebuilt stops living in the half that gets deleted.

**Architecture:** One authority (`scripts/lib/runlayout.RunLayout`) computes every path from `(run root, reel name)`. `scripts/montage.py` resolves every stage artifact through it, which makes the inspector the enforcement point: an artifact written outside the layout is not seen, so the router re-runs the stage into the canonical path. Two physical backstops sit under that — `build/` is wiped at the start of every phase-1 render, and `deliveries/` is reachable by no wipe in the codebase, with `deliver._next_version` reading `VERSIONS.md` so numbering survives whatever else is lost.

**Tech Stack:** Python 3.12, pytest, dataclasses, pathlib, ffmpeg (real-binary integration proofs only).

## Global Constraints

- **Design spec:** [docs/specs/2026-08-26-run-layout-lifetimes-design.md](../specs/2026-08-26-run-layout-lifetimes-design.md). Spec and plan stay in sync; if they drift, fix both.
- **Coding standards:** [docs/coding-standards.md](../coding-standards.md) — fail-loud contract, imports at top, full typing, no bare `except`.
- **Testing guide:** [docs/testing-guide.md](../testing-guide.md) — TDD, whole-object asserts, real-ffmpeg goldens.
- **Python is `.venv/bin/python`.** Scripts run as modules (`pythonpath = .` in `pytest.ini`); never `python scripts/foo.py`.
- **Run the whole suite before every commit:** `.venv/bin/python -m pytest -q`.
- **Mutation batteries run under `PYTHONDONTWRITEBYTECODE=1`** — a one-byte edit can match the previous file's size and mtime-second, and CPython then serves a stale `.pyc`.
- **Never touch `/Users/serg/Downloads/untitled folder/`.** It is the 2026-06 run, kept for two open calibration rows. §7 of the design says it does not migrate.
- **Do not run installers** (brew/pip/apt/npm/uv install, `setup.sh`). Verification is read-only plus pytest.
- **Exact names, fixed by this plan:** bucket names `run`, `footage`, `music`, `reel`, `episodes`, `deliveries`, `build`; the default reel name is `main`; the constant is `DEFAULT_REEL`.
- **Refusals carry a remedy.** Every `raise` added here names what to do instead, in the style of `runlayout.refuse_output_in_footage`.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `scripts/lib/runlayout.py` (modify) | the layout authority: `RunLayout`, `reel_names`, `is_legacy_run`, `deliveries_for`, `wipe_build`; keeps 0.2.1's `refuse_output_in_footage` | 0 |
| `tests/lib/test_runlayout.py` (modify) | unit proofs for all of the above, alongside the nine existing 0.2.1 tests | 0 |
| `scripts/montage.py` (modify) | `Stage.bucket`; `next_action`/`verify` resolve through `RunLayout`; report `path` per stage plus `layout`, `reel`, `reels`, `legacy_layout` | 1 |
| `tests/lib/test_montage.py` (modify) | the 40 existing tests re-pointed at the layout, plus the new reporting | 1 |
| `scripts/deliver.py` (modify) | `_logged_versions`; `_next_version` reads the log; required keyword-only `scratch_dir` | 2 |
| `scripts/build_reel.py` (modify) | pass its own `work_dir` to `deliver` as the scratch dir | 2 |
| `tests/lib/test_deliver.py`, `tests/test_deliver.py` (modify) | version-log unit proofs; the 21 call sites gain `scratch_dir` | 2 |
| `scripts/edl_to_reel.py` (modify) | `_note`; the guarded `build/` wipe; the `deliveries_dir` split between phase 1 and phase 2 | 3 |
| `tests/lib/test_edl_to_reel.py` (modify) | wipe predicate + deliveries split | 3 |
| `tests/integration/test_reel_backhalf.py` (modify) | the two real-ffmpeg proofs: nothing but deliveries in `deliveries/`, and a version that survives its file | 4 |
| `skills/*/SKILL.md` (9 files) | the buckets; `using-montage` defines the layout and the legacy discriminator | 5 |
| `tests/test_skill_convention.py` (modify) | machine-check that no skill spells a stage artifact outside its bucket | 5 |
| `CLAUDE.md`, `README.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json`, `docs/backlog.md`, `docs/build-status.md` | docs sync + the 0.3.0 bump | 7 |

---

### Task 0: The layout authority

**Files:**
- Modify: `scripts/lib/runlayout.py`
- Test: `tests/lib/test_runlayout.py`

**Interfaces:**
- Consumes: nothing (this is the first task).
- Produces:
  - `DEFAULT_REEL: str = "main"`
  - `BUCKETS: tuple[str, ...] = ("run", "footage", "music", "reel", "episodes", "deliveries", "build")`
  - `RunLayout(root: Path, reel: str = DEFAULT_REEL)` — frozen dataclass with properties `footage`, `music`, `reel_dir`, `episodes`, `deliveries`, `build`, `project`, all `Path`; method `bucket(name: str) -> Path`; method `to_dict() -> dict[str, str]`; classmethod `for_footage(footage_root: str, reel: str = DEFAULT_REEL) -> RunLayout`
  - `reel_names(root: str | Path) -> list[str]`
  - `is_legacy_run(root: str | Path) -> bool`
  - `deliveries_for(episodes_dir: str) -> Path`
  - `wipe_build(work_dir: str, out_dir: str) -> list[str] | None`
  - unchanged: `RUN_DIRNAME`, `refuse_output_in_footage`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_runlayout.py`:

```python
def test_the_layout_places_every_bucket(tmp_path):
    lay = runlayout.RunLayout(tmp_path / "montage", "main")
    assert lay.to_dict() == {
        "run": str(tmp_path / "montage"),
        "footage": str(tmp_path / "montage" / "footage"),
        "music": str(tmp_path / "montage" / "music"),
        "reel": str(tmp_path / "montage" / "reels" / "main"),
        "episodes": str(tmp_path / "montage" / "reels" / "main" / "episodes"),
        "deliveries": str(tmp_path / "montage" / "reels" / "main" / "deliveries"),
        "build": str(tmp_path / "montage" / "reels" / "main" / "build"),
    }


def test_the_default_reel_is_main(tmp_path):
    assert runlayout.RunLayout(tmp_path).reel == "main"
    assert runlayout.DEFAULT_REEL == "main"


def test_a_variant_only_moves_the_reel_buckets(tmp_path):
    a = runlayout.RunLayout(tmp_path, "main")
    b = runlayout.RunLayout(tmp_path, "upbeat")
    assert a.footage == b.footage and a.music == b.music and a.project == b.project
    assert a.reel_dir != b.reel_dir and a.deliveries != b.deliveries


def test_for_footage_hangs_the_run_off_the_footage_root(tmp_path):
    lay = runlayout.RunLayout.for_footage(str(tmp_path), "main")
    assert lay.root == tmp_path.resolve() / "montage"


def test_project_json_sits_at_the_run_root(tmp_path):
    """CONSTRAINTS.json is found beside project.json by edit_plan — a code fact.
    Moving project.json into a bucket would silently move the rules with it."""
    assert runlayout.RunLayout(tmp_path).project == tmp_path / "project.json"


@pytest.mark.parametrize("bad", ["", "a/b", "a\\b", ".", "..", "  "])
def test_a_reel_name_that_is_not_one_path_segment_is_refused(tmp_path, bad):
    with pytest.raises(ValueError) as e:
        runlayout.RunLayout(tmp_path, bad)
    assert "reel name" in str(e.value)


def test_an_unknown_bucket_is_refused(tmp_path):
    with pytest.raises(ValueError) as e:
        runlayout.RunLayout(tmp_path).bucket("scratch")
    assert "scratch" in str(e.value)


def test_reel_names_lists_the_variants(tmp_path):
    for n in ("upbeat", "main"):
        (tmp_path / "reels" / n).mkdir(parents=True)
    (tmp_path / "reels" / "notes.txt").write_text("x")
    assert runlayout.reel_names(tmp_path) == ["main", "upbeat"]


def test_reel_names_is_empty_before_any_reel_exists(tmp_path):
    assert runlayout.reel_names(tmp_path) == []


def test_a_legacy_run_is_recognised_by_footage_json_at_the_root(tmp_path):
    (tmp_path / "FOOTAGE.json").write_text("{}")
    assert runlayout.is_legacy_run(tmp_path) is True


def test_a_current_run_is_not_legacy(tmp_path):
    (tmp_path / "footage").mkdir()
    (tmp_path / "footage" / "FOOTAGE.json").write_text("{}")
    assert runlayout.is_legacy_run(tmp_path) is False


def test_an_empty_run_is_not_legacy(tmp_path):
    assert runlayout.is_legacy_run(tmp_path) is False


def test_deliveries_is_the_sibling_of_episodes(tmp_path):
    eps = tmp_path / "reels" / "main" / "episodes"
    assert runlayout.deliveries_for(str(eps)) == (tmp_path / "reels" / "main"
                                                  / "deliveries").resolve()


def test_the_build_wipe_fires_on_the_canonical_pair(tmp_path):
    reel = tmp_path / "reels" / "main"
    build, eps = reel / "build", reel / "episodes"
    (build / "segments").mkdir(parents=True)
    (build / "segments" / "ep0_raw.mp4").write_text("x")
    eps.mkdir(parents=True)
    assert runlayout.wipe_build(str(build), str(eps)) == ["segments"]
    assert build.is_dir() and list(build.iterdir()) == []


def test_the_build_wipe_does_not_fire_on_a_hand_driven_scratch(tmp_path):
    """SP1's front door: edl_to_reel with a hand-authored EDL and --work-dir
    anywhere. Returning None (not []) is what lets the caller say WHY nothing
    was wiped."""
    scratch = tmp_path / "build"          # named build, but not the sibling
    scratch.mkdir()
    (scratch / "keep.txt").write_text("x")
    eps = tmp_path / "elsewhere" / "episodes"
    eps.mkdir(parents=True)
    assert runlayout.wipe_build(str(scratch), str(eps)) is None
    assert (scratch / "keep.txt").exists()


def test_the_build_wipe_on_a_canonical_pair_that_does_not_exist_yet(tmp_path):
    reel = tmp_path / "reels" / "main"
    eps = reel / "episodes"
    eps.mkdir(parents=True)
    assert runlayout.wipe_build(str(reel / "build"), str(eps)) == []


def test_the_build_wipe_matches_through_a_symlinked_spelling(tmp_path):
    reel = tmp_path / "reels" / "main"
    (reel / "build").mkdir(parents=True)
    (reel / "episodes").mkdir()
    link = tmp_path / "link"
    link.symlink_to(reel / "build")
    assert runlayout.wipe_build(str(link), str(reel / "episodes")) == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_runlayout.py -q`
Expected: FAIL — `AttributeError: module 'scripts.lib.runlayout' has no attribute 'RunLayout'`.

- [ ] **Step 3: Implement**

Add to the top of `scripts/lib/runlayout.py`, after the existing `from pathlib import Path`:

```python
import shutil
from dataclasses import dataclass
```

Add after `RUN_DIRNAME`:

```python
DEFAULT_REEL = "main"         # a run has one reel unless the user names a variant

# Every lifetime in the conveyor, in the order the design's §1 table lists them.
# `build` is a bucket but never a Stage artifact's bucket — nothing a human is
# meant to open lives there, and the router has nothing to look for in it.
BUCKETS: tuple[str, ...] = ("run", "footage", "music", "reel", "episodes",
                            "deliveries", "build")


@dataclass(frozen=True)
class RunLayout:
    """Every path in a montage run, computed from (run root, reel name).

    One authority, because the layout used to exist only as 74 `<run>` strings
    across nine SKILL.md files — a second, unchecked copy (design §4).

    The reel level sits BELOW footage/ and music/ on a measured ratio: the
    editorial layer is 120 KB against footage's 194M, so a variant duplicates the
    free half and shares the expensive one (design §0).
    """
    root: Path
    reel: str = DEFAULT_REEL

    def __post_init__(self) -> None:
        # One path segment, or `reels/<name>` is not a directory name any more —
        # `--reel ../..` would escape the run dir entirely.
        if (not self.reel or self.reel.strip() != self.reel
                or "/" in self.reel or "\\" in self.reel or self.reel in (".", "..")):
            raise ValueError(
                f"reel name must be a single path segment with no separators or "
                f"surrounding space, got {self.reel!r} — use a plain name like "
                f"{DEFAULT_REEL!r} or 'upbeat'")

    @classmethod
    def for_footage(cls, footage_root: str, reel: str = DEFAULT_REEL) -> "RunLayout":
        """The run dir 0.2.1 established: <footage_root>/montage."""
        return cls(Path(footage_root).resolve() / RUN_DIRNAME, reel)

    @property
    def footage(self) -> Path:
        return self.root / "footage"

    @property
    def music(self) -> Path:
        return self.root / "music"

    @property
    def reel_dir(self) -> Path:
        return self.root / "reels" / self.reel

    @property
    def episodes(self) -> Path:
        return self.reel_dir / "episodes"

    @property
    def deliveries(self) -> Path:
        return self.reel_dir / "deliveries"

    @property
    def build(self) -> Path:
        return self.reel_dir / "build"

    @property
    def project(self) -> Path:
        # At the run root, not in a bucket: edit_plan discovers CONSTRAINTS.json
        # beside project.json, so moving one moves the other (design §8).
        return self.root / "project.json"

    def bucket(self, name: str) -> Path:
        if name not in BUCKETS:
            raise ValueError(f"unknown bucket {name!r} — one of {BUCKETS}")
        return {"run": self.root, "footage": self.footage, "music": self.music,
                "reel": self.reel_dir, "episodes": self.episodes,
                "deliveries": self.deliveries, "build": self.build}[name]

    def to_dict(self) -> dict[str, str]:
        return {b: str(self.bucket(b)) for b in BUCKETS}


def reel_names(root: str | Path) -> list[str]:
    """The reel variants that exist under a run root, sorted; [] before the first."""
    d = Path(root) / "reels"
    return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.is_dir() else []


def is_legacy_run(root: str | Path) -> bool:
    """True for a run written under the 0.2.x flat convention.

    The discriminator is FOOTAGE.json at the run root with no footage/ bucket
    beside it. Without this the router sees an empty run and re-scans 99 4K clips
    (design §7); with it, the skill asks.
    """
    r = Path(root)
    return (r / "FOOTAGE.json").exists() and not (r / "footage").is_dir()


def deliveries_for(episodes_dir: str) -> Path:
    """The sibling deliveries/ of an episodes/ dir.

    The same structural relationship wipe_build uses, and for the same reason: it
    is true exactly for a canonical reel and for nothing else. Phase 1 fills
    episodes/, phase 2 delivers next door — they must not share a directory, or a
    human clearing the render output takes the deliveries with it, which is what
    47 `rm -rf out/` did (design §0).
    """
    return Path(episodes_dir).resolve().parent / "deliveries"


def wipe_build(work_dir: str, out_dir: str) -> list[str] | None:
    """Delete this reel's scratch tree, leaving the directory empty.

    Returns the entry names removed, [] when the canonical directory did not exist
    yet, and **None** when the predicate did not hold — three outcomes, because the
    caller reports "wiped X" and "did not wipe, not canonical" differently.

    The predicate is STRUCTURAL, never name-based: under the layout `out_dir` is
    reels/<name>/episodes and its sibling is reels/<name>/build, so a canonical run
    always matches and nothing else can. "The directory is named build" would make
    a hand-driven `--work-dir ~/build` a grenade (design §6).
    """
    work = Path(work_dir).resolve()
    if work != Path(out_dir).resolve().parent / "build":
        return None
    if not work.is_dir():
        return []
    removed = sorted(p.name for p in work.iterdir())
    shutil.rmtree(work)
    work.mkdir(parents=True)
    return removed
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_runlayout.py -q`
Expected: PASS, 25 tests (the nine from 0.2.1 plus sixteen new).

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — nothing consumes the new API yet.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/runlayout.py tests/lib/test_runlayout.py
git commit -m "feat: RunLayout — one authority for every path in a run"
```

---

### Task 1: The inspector speaks the layout

**Files:**
- Modify: `scripts/montage.py`
- Test: `tests/lib/test_montage.py`

**Interfaces:**
- Consumes: `runlayout.RunLayout`, `runlayout.reel_names`, `runlayout.is_legacy_run`, `runlayout.BUCKETS`, `runlayout.DEFAULT_REEL` (Task 0).
- Produces:
  - `Stage(key, artifact, kind, runner, checkpoint, bucket)` — `in_out: bool` is **deleted**, `bucket: str` replaces it and is validated against `runlayout.BUCKETS`.
  - `next_action(run_dir: str, reel: str = runlayout.DEFAULT_REEL) -> dict` — the `out_dir` parameter is **deleted**. Each stage dict gains `"path"`. The result gains `"reel"`, `"reels"`, `"layout"`, `"legacy_layout"`.
  - `verify(run_dir: str, reel: str = runlayout.DEFAULT_REEL) -> dict`
  - CLI: `--reel` replaces `--out-dir` on both subcommands.

- [ ] **Step 1: Write the failing tests**

Replace the whole of `tests/lib/test_montage.py`'s setup helper and add these. The existing 40 tests build their fixtures by touching artifact files at the run root; re-point each to the stage's bucket using this helper, added at the top of the file:

```python
from scripts.lib import runlayout


def _touch(run, stage_key, name=None):
    """Create the artifact that marks `stage_key` done, in its own bucket."""
    st = next(s for s in montage.V1_STAGES if s.key == stage_key)
    lay = runlayout.RunLayout(run)
    d = lay.bucket(st.bucket)
    d.mkdir(parents=True, exist_ok=True)
    (d / (name or st.artifact.replace("*", "1"))).write_text("{}")
```

New tests:

```python
def test_every_stage_declares_a_known_bucket():
    assert all(s.bucket in runlayout.BUCKETS for s in montage.V1_STAGES)


def test_no_stage_lives_in_build():
    """build/ is wiped at every render — a stage marker there would make a
    finished stage un-finish itself (design §1)."""
    assert all(s.bucket != "build" for s in montage.V1_STAGES)


def test_an_unknown_bucket_is_refused():
    with pytest.raises(ValueError) as e:
        montage.Stage("x", "X.json", "required", "runner", None, "scratch")
    assert "scratch" in str(e.value)


def test_each_stage_reports_its_resolved_path(tmp_path):
    """The path comes back in the same answer as `next` — the moment the agent is
    asking where to write (design §5)."""
    got = {s["key"]: s["path"] for s in montage.next_action(str(tmp_path))["stages"]}
    assert got["footage-intake"] == str(tmp_path / "footage" / "FOOTAGE.json")
    assert got["edit-plan"] == str(tmp_path / "reels" / "main" / "EDL.json")
    assert got["episodes"] == str(tmp_path / "reels" / "main" / "episodes"
                                  / "EPISODES.json")
    assert got["deliver"] == str(tmp_path / "reels" / "main" / "deliveries"
                                 / "REEL_v*.*")
    assert got["project-init"] == str(tmp_path / "project.json")


def test_an_artifact_outside_the_layout_does_not_count(tmp_path):
    """The enforcement, stated as a test: EDL.json at the run root is invisible, so
    the router re-runs edit-plan into the canonical path (design §5)."""
    _touch(tmp_path, "project-init")
    _touch(tmp_path, "footage-intake")
    _touch(tmp_path, "contact-sheet")
    (tmp_path / "EDL.json").write_text("{}")          # the 0.2.x place
    assert montage.next_action(str(tmp_path))["next"] == "edit-plan"


def test_the_result_carries_the_whole_layout(tmp_path):
    got = montage.next_action(str(tmp_path))
    assert got["layout"] == runlayout.RunLayout(tmp_path).to_dict()
    assert got["reel"] == "main"


def test_the_result_lists_the_reels_that_exist(tmp_path):
    (tmp_path / "reels" / "main").mkdir(parents=True)
    (tmp_path / "reels" / "upbeat").mkdir()
    assert montage.next_action(str(tmp_path))["reels"] == ["main", "upbeat"]


def test_a_variant_has_its_own_progress(tmp_path):
    _touch(tmp_path, "project-init")
    _touch(tmp_path, "footage-intake")
    _touch(tmp_path, "contact-sheet")
    lay = runlayout.RunLayout(tmp_path, "main")
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    (lay.reel_dir / "EDL.json").write_text("{}")
    assert montage.next_action(str(tmp_path), "main")["next"] != "edit-plan"
    assert montage.next_action(str(tmp_path), "upbeat")["next"] == "edit-plan"


def test_a_legacy_run_is_flagged(tmp_path):
    (tmp_path / "FOOTAGE.json").write_text("{}")
    got = montage.next_action(str(tmp_path))
    assert got["legacy_layout"] is True


def test_a_current_run_is_not_flagged(tmp_path):
    assert montage.next_action(str(tmp_path))["legacy_layout"] is False


def test_verify_reads_the_deliveries_bucket(tmp_path):
    lay = runlayout.RunLayout(tmp_path)
    lay.deliveries.mkdir(parents=True)
    (lay.deliveries / "REEL_v1.mp4").write_bytes(b"x")
    assert len(montage.verify(str(tmp_path))["deliveries"]) == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q`
Expected: FAIL — `TypeError: Stage.__init__() got an unexpected keyword argument 'bucket'` and `KeyError: 'path'`.

- [ ] **Step 3: Implement**

In `scripts/montage.py`, change the import line to:

```python
from scripts.lib import constraints, provenance, runlayout
```

Replace the `Stage` dataclass:

```python
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
```

Set each stage's bucket in `V1_STAGES` — keep every existing comment, add the bucket argument, and delete every `in_out=True`:

```python
    Stage("project-init", "project.json", "required",
          "project-init SKILL -> project_init CLI", "spec", "run"),
    Stage("footage-intake", "FOOTAGE.json", "required",
          "footage-intake SKILL -> intake CLI", None, "footage"),
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
    Stage("match-grade", "MATCH.md", "optional",
          "match-grade SKILL -> match_grade build CLI (opt-in; run AFTER pacing settles "
          "the cut, before deliver)", None, "reel"),
    Stage("assemble-draft", "draft.mp4", "optional",
          "draft CLI (optional QA preview)", "edl", "reel"),
    Stage("titles", "TITLES.json", "optional",
          "titles SKILL -> titles build CLI (optional on-screen text)", "final", "reel"),
    Stage("episodes", "EPISODES.json", "required",
          "edl_to_reel --stop-after-episodes (renders every episode, then stops at the "
          "QC seam)", None, "episodes"),
    Stage("episode-qc", "EPISODE_QC.json", "required",
          "episode-qc SKILL -> episode_qc pack, one judge per episode (cap 3), "
          "episode_qc build", None, "episodes"),
    Stage("deliver", "REEL_v*.*", "required",
          "edl_to_reel --from-episodes (gates on EPISODE_QC.json, then assembles)",
          "final", "deliveries"),
    Stage("reel-review", "REVIEW.json", "required",
          "reel-review SKILL -> reel_review build CLI (editorial CP3 review)",
          "final", "reel"),
```

Replace `next_action` and `verify`:

```python
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
```

Change `_deliveries`' first line to tolerate a directory that does not exist yet — `sorted(out.glob(...))` already returns `[]` for a missing dir, so no change is needed; confirm by running the tests.

Replace the CLI body's two `--out-dir` arguments:

```python
    s.add_argument("--reel", default=runlayout.DEFAULT_REEL,
                   help=f"which reel variant to inspect (default {runlayout.DEFAULT_REEL})")
```

and the same for `v`, then:

```python
    result = next_action(a.run_dir, a.reel) if a.cmd == "status" else verify(a.run_dir, a.reel)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. If a test outside `tests/lib/test_montage.py` fails, it is calling `next_action(run, out)` positionally — re-point it at the bucket layout rather than restoring the parameter.

- [ ] **Step 6: Commit**

```bash
git add scripts/montage.py tests/lib/test_montage.py
git commit -m "feat: the router inspector resolves every stage through the layout"
```

---

### Task 2: Deliveries survive, and deliver stops littering them

**Files:**
- Modify: `scripts/deliver.py`, `scripts/build_reel.py`
- Test: `tests/lib/test_deliver.py`, `tests/test_deliver.py`

**Interfaces:**
- Consumes: nothing from Tasks 0-1.
- Produces:
  - `deliver._logged_versions(out_dir: str) -> list[int]`
  - `deliver.deliver(master, profile, out_dir, changelog, report, *, scratch_dir: str, audio=None, titles=None, platform="", look=None, run_provenance=None) -> str` — `scratch_dir` is required and keyword-only.
  - `build_reel.build_reel` unchanged in signature; it passes its own `work_dir` as `scratch_dir`.
  - CLI: `deliver --scratch-dir` (required).

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_deliver.py`:

```python
def test_the_next_version_reads_the_log_when_the_file_is_gone(tmp_path):
    """R5.1, measured: 14 delivering runs left 2 log records because _next_version
    counted surviving files, so numbering restarted and three different reels
    shipped as REEL_v1.mp4."""
    (tmp_path / "VERSIONS.md").write_text(
        "# Reel versions\n\n- v1 | 2026-08-25 | first\n- v2 | 2026-08-25 | second\n")
    assert deliver._next_version(str(tmp_path), "mp4") == 3


def test_the_next_version_takes_the_higher_of_log_and_files(tmp_path):
    """The glob stays as a FLOOR: a log deleted by hand must not renumber over a
    reel that is still on disk."""
    (tmp_path / "VERSIONS.md").write_text("# Reel versions\n\n- v1 | 2026-08-25 | a\n")
    (tmp_path / "REEL_v4.mp4").write_bytes(b"x")
    assert deliver._next_version(str(tmp_path), "mp4") == 5


def test_the_next_version_is_one_on_an_empty_directory(tmp_path):
    assert deliver._next_version(str(tmp_path), "mp4") == 1


def test_the_log_reader_ignores_prose(tmp_path):
    (tmp_path / "VERSIONS.md").write_text(
        "# Reel versions\n\nversion 7 was skipped\n- v2 | 2026-08-25 | real\n")
    assert deliver._logged_versions(str(tmp_path)) == [2]


def test_the_log_reader_is_empty_with_no_log(tmp_path):
    assert deliver._logged_versions(str(tmp_path)) == []


def test_deliver_requires_a_scratch_dir():
    """deliveries/ is append-only; the mask and the title sidecars are scratch.
    A default of out_dir would keep the leak one forgotten argument away."""
    import inspect
    p = inspect.signature(deliver.deliver).parameters["scratch_dir"]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY
    assert p.default is inspect.Parameter.empty
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_deliver.py -q`
Expected: FAIL — `AttributeError: module 'scripts.deliver' has no attribute '_logged_versions'`, and the log-reading assertions return 1.

- [ ] **Step 3: Implement**

In `scripts/deliver.py`, replace `_next_version` and add `_logged_versions` above it:

```python
def _logged_versions(out_dir: str) -> list[int]:
    """The version numbers VERSIONS.md records, in file order.

    Parsed off the exact line _log_version writes ("- v{n} | {stamp} | {changelog}"),
    so a heading or a hand-written note between entries is ignored rather than
    misread."""
    vf = Path(out_dir) / "VERSIONS.md"
    if not vf.exists():
        return []
    return [int(m.group(1)) for line in vf.read_text().splitlines()
            if (m := re.match(r"- v(\d+) \|", line))]


def _next_version(out_dir: str, container: str) -> int:
    """max(the log, the files) + 1.

    The LOG is the source: it survives a delivery being archived, renamed or deleted,
    which is what makes REEL_v{n} a monotone identity instead of a count of whatever
    is in one directory today. Measured on the 2026-06 run, the file-glob-only version
    shipped three different reels as REEL_v1.mp4 (design 2026-08-26 §0/§4.1). The glob
    stays as a FLOOR, for a log deleted by hand; both being gone is named in §8, not
    closed."""
    rx = re.compile(rf"REEL_v(\d+)\.{re.escape(container)}$")
    ns = [int(m.group(1)) for p in Path(out_dir).glob(f"REEL_v*.{container}")
          if (m := rx.match(p.name))]
    ns += _logged_versions(out_dir)
    return max(ns) + 1 if ns else 1
```

Change `deliver`'s signature to add the required keyword-only parameter:

```python
def deliver(master: str, profile: ExportProfile, out_dir: str, changelog: str,
            report: ReelReport, *, scratch_dir: str, audio: str | None = None,
            titles: str | None = None, platform: str = "",
            look: LookSpec | None = None, run_provenance: dict | None = None) -> str:
```

Add to the docstring, after the first paragraph:

```
    `scratch_dir` receives the one-frame vignette mask and the per-title textfile
    sidecars. It is required and separate from `out_dir` because out_dir is the
    append-only deliveries bucket: writing scratch there is how look_mask.png and
    title_0_0.txt ended up beside the shipped reels (design 2026-08-26 §3).
```

Inside the body, after `Path(out_dir).mkdir(parents=True, exist_ok=True)`, add:

```python
    Path(scratch_dir).mkdir(parents=True, exist_ok=True)
```

Change the two scratch call sites — `build_filterchain(Titles.from_json(titles), out_dir, platform=platform)` becomes `..., scratch_dir, platform=platform)`, and `_render_mask(master, out_dir, look.vignette)` becomes `_render_mask(master, scratch_dir, look.vignette)`. Update `_render_mask`'s parameter name from `out_dir` to `scratch_dir` and its docstring's `out_dir` reference.

In `main()`, add the CLI argument after `--out-dir`:

```python
    ap.add_argument("--scratch-dir", required=True,
                    help="where the vignette mask and title sidecars go — NOT the "
                         "deliveries dir, which is append-only")
```

and pass it: `out = deliver(a.master, ExportProfile(), a.out_dir, a.changelog, report, scratch_dir=a.scratch_dir, titles=a.titles, ...)`.

In `scripts/build_reel.py`, change the `deliver.deliver(...)` call at line 134 to pass the scratch dir it already owns:

```python
            out = deliver.deliver(master, REEL_H264, out_dir, rm.changelog, report,
                                  scratch_dir=work_dir,   # build/reel — never the deliveries bucket
                                  audio=audio, titles=titles, platform=rm.platform,
                                  look=rm.look, run_provenance=prov)
```

- [ ] **Step 4: Update the 21 existing call sites**

Run: `grep -rn "deliver\.deliver(" tests/`
For each, add `scratch_dir=str(tmp_path / "scratch")` (or the test's own scratch path) as a keyword argument. Do not point it at the same directory as `out_dir` — a test that does would keep passing while the leak returns.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_deliver.py tests/test_deliver.py -q`
Expected: PASS.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/deliver.py scripts/build_reel.py tests/lib/test_deliver.py tests/test_deliver.py tests/integration
git commit -m "fix: deliver reads the version log and keeps its scratch out of deliveries"
```

---

### Task 3: The guarded build wipe, and the deliveries split

**Files:**
- Modify: `scripts/edl_to_reel.py`
- Test: `tests/lib/test_edl_to_reel.py`

**Interfaces:**
- Consumes: `runlayout.wipe_build`, `runlayout.deliveries_for` (Task 0).
- Produces:
  - `edl_to_reel._note(msg: str) -> None`
  - `edl_to_reel.edl_to_reel(edl_path, project_path, footage_root, work_dir, out_dir, *, deliveries_dir: str | None = None, music=None, jobs=DEFAULT_JOBS, color_delta_max=None, changelog="", titles=None)`
  - `edl_to_reel.assemble_reel(episodes_path, work_dir, *, deliveries_dir: str | None = None, titles=None)`
  - CLI: `--deliveries-dir` (optional; defaults to `runlayout.deliveries_for(out_dir)`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_edl_to_reel.py`:

```python
def test_phase_one_wipes_the_canonical_build_dir(tmp_path, capsys, monkeypatch):
    """17 work/ep* directories and 17 segments survived for an 8-episode reel
    because nothing ever deleted scratch (design §0)."""
    reel = tmp_path / "montage" / "reels" / "main"
    build, eps = reel / "build", reel / "episodes"
    (build / "ep99").mkdir(parents=True)
    eps.mkdir(parents=True)
    edl_to_reel._wipe_scratch(str(build), str(eps))
    assert not (build / "ep99").exists()
    assert "wiped" in capsys.readouterr().err


def test_phase_one_leaves_a_hand_driven_scratch_alone_and_says_so(tmp_path, capsys):
    """SP1's front door stays open — the cost named in design §8."""
    scratch = tmp_path / "scratch"
    (scratch / "keep").mkdir(parents=True)
    eps = tmp_path / "somewhere" / "episodes"
    eps.mkdir(parents=True)
    edl_to_reel._wipe_scratch(str(scratch), str(eps))
    assert (scratch / "keep").exists()
    err = capsys.readouterr().err
    assert "not the canonical" in err


def test_the_deliveries_dir_defaults_to_the_episodes_sibling(tmp_path):
    eps = tmp_path / "montage" / "reels" / "main" / "episodes"
    eps.mkdir(parents=True)
    assert edl_to_reel._deliveries_dir(None, str(eps)) == str(
        (tmp_path / "montage" / "reels" / "main" / "deliveries").resolve())


def test_an_explicit_deliveries_dir_wins(tmp_path):
    eps = tmp_path / "episodes"
    eps.mkdir()
    assert edl_to_reel._deliveries_dir(str(tmp_path / "elsewhere"), str(eps)) == str(
        tmp_path / "elsewhere")


def test_the_deliveries_dir_is_never_the_episodes_dir(tmp_path):
    """A human clearing the render output must not take the deliveries with it —
    that is what 47 `rm -rf out/` did (design §0)."""
    eps = tmp_path / "montage" / "reels" / "main" / "episodes"
    eps.mkdir(parents=True)
    assert edl_to_reel._deliveries_dir(None, str(eps)) != str(eps)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edl_to_reel.py -q`
Expected: FAIL — `AttributeError: module 'scripts.edl_to_reel' has no attribute '_wipe_scratch'`.

- [ ] **Step 3: Implement**

In `scripts/edl_to_reel.py`, add `import sys` to the imports and these two helpers after `DEFAULT_JOBS`:

```python
def _note(msg: str) -> None:
    print(msg, file=sys.stderr)


def _wipe_scratch(work_dir: str, out_dir: str) -> None:
    """Clear this reel's build/ before a phase-1 render, and report either way.

    Phase 1 has no resume — every run re-renders every episode from scratch — so the
    wipe discards nothing that would have been reused. It must NOT happen between the
    phases: EPISODES.json carries absolute paths into build/ep{i}/ and phase 2's retry
    loop reads the frozen route from there (design §6)."""
    removed = runlayout.wipe_build(work_dir, out_dir)
    if removed is None:
        _note(f"edl_to_reel: {work_dir} is not the canonical build dir for {out_dir} "
              f"— leaving it alone. Scratch there accumulates across runs.")
    elif removed:
        _note(f"edl_to_reel: wiped {len(removed)} entries from {work_dir}")


def _deliveries_dir(explicit: str | None, out_dir: str) -> str:
    """Where REEL_v{n} goes: the episodes dir's sibling deliveries/, unless named.

    Phase 1 fills out_dir with ep{i}.mp4 and phase 2 delivers next door, because a
    delivery inside the render output is a delivery a human deletes when clearing the
    render output (design §0/§4)."""
    return explicit if explicit is not None else str(runlayout.deliveries_for(out_dir))
```

In `_build_manifest`, insert the wipe immediately after the two existing `refuse_output_in_footage` calls — after the guards, never before, so a run pointed at the footage root is refused rather than wiped:

```python
    runlayout.refuse_output_in_footage(footage_root, work_dir, "edl_to_reel's work_dir")
    _wipe_scratch(work_dir, out_dir)
```

Add `deliveries_dir: str | None = None` to `edl_to_reel()`'s and `assemble_reel()`'s keyword-only parameters, and change each `build_reel.build_reel(rm, out_dir, ...)` call to pass the resolved deliveries dir:

```python
    return build_reel.build_reel(rm, _deliveries_dir(deliveries_dir, out_dir),
                                 str(Path(work_dir) / "reel"), titles=titles)
```

In `assemble_reel`, `out_dir` is derived from `Path(episodes_path).parent`; pass that same value into `_deliveries_dir`.

In `main()`, add the CLI argument beside `--out-dir`:

```python
    ap.add_argument("--deliveries-dir", default=None,
                    help="where REEL_v{n} lands (default: the episodes dir's sibling "
                         "deliveries/) — never the same dir as --out-dir")
```

and thread `deliveries_dir=a.deliveries_dir` into both dispatch calls.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_edl_to_reel.py -q`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/edl_to_reel.py tests/lib/test_edl_to_reel.py
git commit -m "feat: wipe build/ at every render, deliver next door to episodes/"
```

---

### Task 4: The two real-ffmpeg proofs

**Files:**
- Modify: `tests/integration/test_reel_backhalf.py`

**Interfaces:**
- Consumes: `deliver.deliver(..., scratch_dir=...)` (Task 2).
- Produces: nothing consumed downstream.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_reel_backhalf.py`, reusing that file's existing `_episode` helper and `sample_clip` fixture:

```python
def test_the_deliveries_dir_holds_nothing_but_deliveries(tmp_path, sample_clip):
    """The leak this closes is real: the 2026-06 run's out/ carried look_mask.png
    and title_0_0.txt beside the shipped reels (design §3). Titles and a vignette
    are BOTH on, because each writes a different sidecar."""
    eps = [_episode(sample_clip, tmp_path, x, f"ep{i}")
           for i, x in enumerate((300.0, 845.0))]
    master = str(tmp_path / "master.mp4")
    assembly.concat(eps, master, str(tmp_path / "concat.txt"))
    report = check_reel.check_reel(eps, master, ReelCheckSpec(), str(tmp_path / "r.json"))
    assert report.overall
    titles = tmp_path / "TITLES.json"
    titles.write_text(json.dumps({"items": [
        {"text": "HELLO", "start": 0.0, "dur": 1.0, "position": "center"}]}))
    deliveries, scratch = tmp_path / "deliveries", tmp_path / "build"
    out = deliver.deliver(master, REEL_H264, str(deliveries), "first", report,
                          scratch_dir=str(scratch), titles=str(titles),
                          look=LookSpec(vignette=0.4, fade=0.0))
    assert Path(out).parent == deliveries
    names = sorted(p.name for p in deliveries.iterdir())
    assert names == ["REEL_v1.attest.json", "REEL_v1.mp4", "VERSIONS.md"]
    # the control: the sidecars exist, they are just next door
    assert (scratch / "look_mask.png").exists()
    assert any(p.name.startswith("title_") for p in scratch.iterdir())


def test_a_version_survives_its_own_file_being_archived(tmp_path, sample_clip):
    """R5.1 end to end: three different reels shipped as REEL_v1.mp4 because
    _next_version counted files. Moving v1 away must still yield v2."""
    eps = [_episode(sample_clip, tmp_path, x, f"ep{i}")
           for i, x in enumerate((300.0, 845.0))]
    master = str(tmp_path / "master.mp4")
    assembly.concat(eps, master, str(tmp_path / "concat.txt"))
    report = check_reel.check_reel(eps, master, ReelCheckSpec(), str(tmp_path / "r.json"))
    deliveries, scratch = tmp_path / "deliveries", tmp_path / "build"
    first = deliver.deliver(master, REEL_H264, str(deliveries), "first", report,
                            scratch_dir=str(scratch))
    assert Path(first).name == "REEL_v1.mp4"
    archive = tmp_path / "archive"
    archive.mkdir()
    Path(first).rename(archive / "REEL_v1.mp4")
    second = deliver.deliver(master, REEL_H264, str(deliveries), "second", report,
                             scratch_dir=str(scratch))
    assert Path(second).name == "REEL_v2.mp4"
    assert "- v1 |" in (deliveries / "VERSIONS.md").read_text()
    assert "- v2 |" in (deliveries / "VERSIONS.md").read_text()
```

Add the imports this file does not already have at its top: `from pathlib import Path`, `from scripts.lib.look import LookSpec`, and `deliver` in the existing `from scripts import ...` line.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_reel_backhalf.py -q -k "deliveries_dir_holds or survives_its_own_file"`
Expected: FAIL — before Task 2's change, the first assertion `names == [...]` fails on the extra `look_mask.png` and `title_*.txt`, and the second returns `REEL_v1.mp4` twice. If Task 2 is already committed, they should pass; run them at this point to confirm they genuinely discriminate by reverting `_next_version`'s `ns += _logged_versions(out_dir)` line, watching the second test fail, then restoring it.

- [ ] **Step 3: Run them**

Run: `.venv/bin/python -m pytest tests/integration/test_reel_backhalf.py -q`
Expected: PASS.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_reel_backhalf.py
git commit -m "test: real-ffmpeg proofs for the deliveries bucket and the version log"
```

---

### Task 5: The nine skills, and the check that keeps them honest

**Files:**
- Modify: `skills/using-montage/SKILL.md`, `skills/edit-plan/SKILL.md`, `skills/episode-qc/SKILL.md`, `skills/match-grade/SKILL.md`, `skills/music-match/SKILL.md`, `skills/music-source/SKILL.md`, `skills/pacing/SKILL.md`, `skills/reel-review/SKILL.md`, `skills/titles/SKILL.md`, `skills/footage-intake/SKILL.md`
- Test: `tests/test_skill_convention.py`

**Interfaces:**
- Consumes: `montage.V1_STAGES` (Task 1), `runlayout.RunLayout` (Task 0).
- Produces: nothing consumed downstream.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_skill_convention.py`:

```python
def test_no_skill_spells_a_stage_artifact_outside_its_bucket():
    """The layout had 74 `<run>` strings across nine SKILL.md files and no authority
    (design §4). A skill writing <run>/EDL.json now writes somewhere the router does
    not look, so the stage would re-run forever."""
    from scripts import montage
    offenders = []
    for path in sorted(SKILLS.glob("*/SKILL.md")):
        text = path.read_text()
        for st in montage.V1_STAGES:
            if st.bucket == "run":
                continue
            if f"<run>/{st.artifact}" in text:
                offenders.append(f"{path.relative_to(REPO)}: <run>/{st.artifact}")
    assert offenders == []


def test_no_skill_still_names_the_retired_out_dir():
    """`<run>/out` was the deliveries dir the workflow rm -rf'd 47 times."""
    offenders = sorted(str(p.relative_to(REPO)) for p in SKILLS.glob("*/SKILL.md")
                       if "<run>/out" in p.read_text())
    assert offenders == []


def test_using_montage_defines_every_bucket():
    """Nine skills mention <run>; only using-montage defines it (design §4).

    Each bucket has ONE spelling here on purpose: `<run>/reel` would be satisfied
    by the substring of `<run>/reels/`, so the reel row would pass without the
    variant level ever being documented."""
    from scripts.lib import runlayout
    spelling = {"footage": "<run>/footage/", "music": "<run>/music/",
                "reel": "<run>/reels/<reel>/",
                "episodes": "<run>/reels/<reel>/episodes/",
                "deliveries": "<run>/reels/<reel>/deliveries/",
                "build": "<run>/reels/<reel>/build/"}
    assert set(spelling) == set(runlayout.BUCKETS) - {"run"}
    text = (SKILLS / "using-montage" / "SKILL.md").read_text()
    missing = sorted(b for b, sp in spelling.items() if sp not in text)
    assert missing == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py -q`
Expected: FAIL — the offender lists are non-empty (74 `<run>` mentions, 16 of them `<run>/out`).

- [ ] **Step 3: Rewrite the skill paths**

Apply this substitution table to every `SKILL.md`. `<reel>` is a placeholder the skills define as "the reel name — `main` unless the user asked for a variant".

| was | becomes |
|---|---|
| `<run>/project.json` | unchanged |
| `<run>/CONSTRAINTS.json` | unchanged |
| `<run>/FOOTAGE.json`, `<run>/FOOTAGE.md` | `<run>/footage/FOOTAGE.json`, `…/FOOTAGE.md` |
| `<run>/SHEETS.md`, `<run>/sheets/` | `<run>/footage/SHEETS.md`, `<run>/footage/sheets/` |
| `<run>/cast.json`, `<run>/cast_candidates.json`, `<run>/cast_crops/` | `<run>/footage/…` |
| `<run>/SPEC.json`, `<run>/SPEC.md` | `<run>/reels/<reel>/SPEC.json`, `…/SPEC.md` |
| `<run>/selection.json`, `<run>/EDL.json`, `<run>/EDL.md` | `<run>/reels/<reel>/…` |
| `<run>/MUSIC.json`, `<run>/MUSIC_SHORTLIST.*` | `<run>/reels/<reel>/…` |
| `<run>/PACING.json`, `<run>/PACING.md`, `<run>/MATCH.md` | `<run>/reels/<reel>/…` |
| `<run>/TITLES.json`, `<run>/TITLES.md` | `<run>/reels/<reel>/…` |
| `<run>/REVIEW.json`, `<run>/REVIEW.md` | `<run>/reels/<reel>/…` |
| `<run>/draft.mp4` | `<run>/reels/<reel>/draft.mp4` |
| `<run>/out/EPISODES.json`, `<run>/out/EPISODE_QC.*`, `<run>/out/ep{i}.mp4`, `<run>/qc/` | `<run>/reels/<reel>/episodes/…` |
| `<run>/out/REEL_v*.mp4`, `<run>/out/VERSIONS.md` | `<run>/reels/<reel>/deliveries/…` |
| `<run>/work/` (as `--work-dir`) | `<run>/reels/<reel>/build` |
| a music download folder | `<run>/music` |

And the driver invocations whose output directory names a bucket rather than a file:

| driver | was | becomes |
|---|---|---|
| `intake <footage_root> <out_dir>` | `<run>` | `<run>/footage` — this is what relocates `.intake_cache/`, `cast_crops/` and the 93M cache for free (design §3) |
| `contact_sheet build --out-dir` | `<run>` | `<run>/footage` |
| `music_fetch` / `music_find` download dir | `<run>` or ad hoc | `<run>/music` |
| `edl_to_reel --out-dir` (phase 1) | `<run>/out` | `<run>/reels/<reel>/episodes` |
| `edl_to_reel --work-dir` | `<run>/work` | `<run>/reels/<reel>/build` |
| `episode_qc pack --out-dir` | `<run>/qc` | `<run>/reels/<reel>/episodes/qc` |
| `episode_qc build --out-dir` | `<run>/out` | `<run>/reels/<reel>/episodes` |
| every other stage's `--out-dir` | `<run>` | `<run>/reels/<reel>` |

Also update every CLI invocation shown in the skills: `--out-dir`, `--work-dir`, `--project`, `--footage`, `--edl`, `--music`, `--titles`, `--spec`, `--cast`, `--episodes`, `--packets` all take the new paths, and `montage status` takes `--reel <reel>` in place of `--out-dir`. `deliver` invocations gain `--scratch-dir <run>/reels/<reel>/build`.

- [ ] **Step 4: Add the layout definition to using-montage**

In `skills/using-montage/SKILL.md`, replace the sentence that defines `<run>` with this block:

```markdown
## The run directory

`<run>` is `<footage_root>/montage`. Inside it, **a folder is a lifetime** — how long
what is in it stays true:

    <run>/project.json  CONSTRAINTS.json      the project: canvas, delivery, standing rules
    <run>/footage/                            a function of the raw clips; survives every re-cut
    <run>/music/                              downloaded tracks, shared by every reel
    <run>/reels/<reel>/                       one editorial variant; <reel> is `main` by default
    <run>/reels/<reel>/episodes/              one render generation + its QC verdicts
    <run>/reels/<reel>/deliveries/            append-only — nothing ever deletes this
    <run>/reels/<reel>/build/                 wiped at the start of every render

Never compose these paths from memory. `montage status --run-dir <run> --reel <reel>`
returns each stage's resolved `path` alongside `next`, plus the whole `layout` block.
A file written anywhere else is not seen by the router, and the stage runs again.

A **second cut of the same footage** is a new `<reel>`, never a filename suffix: run
edit-plan with `--out-dir <run>/reels/upbeat` and the whole editorial layer forks while
`footage/` and `music/` stay shared. `MUSIC_A.json` / `pacing_B/` style names are what
this replaces.
```

Add to the step-0 preflight section:

```markdown
If `montage status` reports `"legacy_layout": true`, this run was written before the
0.3.0 layout: its artifacts sit directly in `<run>`. **Ask the user** whether to point
the conveyor at a fresh `<run>` (re-scanning every clip, hours on a 99-clip shoot) or
to keep driving the old run by passing the old paths explicitly. Do not move the tree:
`EPISODES.json` alone carries 57 absolute paths, and moving it breaks the QC digest
bindings and the delivery attestation.
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py -q`
Expected: PASS.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add skills tests/test_skill_convention.py
git commit -m "docs: the nine skills move onto the lifetime layout"
```

---

### Task 6: The mutation battery

**Files:**
- No production changes. This task proves the tests written above discriminate.

**Interfaces:**
- Consumes: everything from Tasks 0-5.
- Produces: a Done entry recording which rows held.

Every row below is a **step, not a suggestion**. For each: apply the mutation, run the named command, confirm it goes RED, then restore. Run the whole battery under `PYTHONDONTWRITEBYTECODE=1` — a one-byte edit can match the previous file's size and mtime-second, and CPython then serves the stale `.pyc`.

- [x] **Step 1: Run every row**

| # | Mutation | Command | Must go RED because |
|---|---|---|---|
| 1 | `RunLayout.deliveries` returns `self.episodes` | `pytest tests/lib/test_runlayout.py -q` | `test_the_layout_places_every_bucket` |
| 2 | `__post_init__`'s reel check drops the `"/" in self.reel` clause | `pytest tests/lib/test_runlayout.py -q` | `test_a_reel_name_that_is_not_one_path_segment_is_refused[a/b]` |
| 3 | `wipe_build`'s predicate becomes `work.name == "build"` | `pytest tests/lib/test_runlayout.py -q` | `test_the_build_wipe_does_not_fire_on_a_hand_driven_scratch` |
| 4 | `wipe_build` returns `[]` instead of `None` on a non-match | `pytest tests/lib/test_runlayout.py -q` | the same test's `is None` |
| 5 | `wipe_build` drops the trailing `work.mkdir(parents=True)` | `pytest tests/lib/test_runlayout.py -q` | `test_the_build_wipe_fires_on_the_canonical_pair`'s `build.is_dir()` |
| 6 | `is_legacy_run` drops the `not (r / "footage").is_dir()` clause | `pytest tests/lib/test_runlayout.py -q` | `test_a_root_with_both_legacy_file_and_footage_dir_is_not_legacy` — **not** `test_a_current_run_is_not_legacy`, which this plan first named and which Task 0's review proved sleeps through the mutation: with no `FOOTAGE.json` at the root the first clause is already False and `and` short-circuits before the second is ever evaluated |
| 7 | `Stage.bucket`'s default changes from `"reel"` to `"run"` | `pytest tests/lib/test_montage.py -q` | `test_each_stage_reports_its_resolved_path` (defaults are not used by V1_STAGES, so if this row does NOT go red, delete the default and make bucket required) |
| 8 | the `deliver` stage's bucket changes to `"episodes"` | `pytest tests/lib/test_montage.py -q` | `test_each_stage_reports_its_resolved_path` |
| 9 | `next_action` drops `"path"` from each stage dict | `pytest tests/lib/test_montage.py -q` | `test_each_stage_reports_its_resolved_path` |
| 10 | `next_action` resolves every stage against `lay.root` regardless of bucket | `pytest tests/lib/test_montage.py -q` | `test_an_artifact_outside_the_layout_does_not_count` |
| 11 | `legacy_layout` is hardcoded `False` | `pytest tests/lib/test_montage.py -q` | `test_a_legacy_run_is_flagged` |
| 12 | `_next_version` drops `ns += _logged_versions(out_dir)` | `pytest tests/lib/test_deliver.py -q` | `test_the_next_version_reads_the_log_when_the_file_is_gone` |
| 13 | `_next_version` returns `max(_logged_versions(...) or [0]) + 1` (log only, no glob floor) | `pytest tests/lib/test_deliver.py -q` | `test_the_next_version_takes_the_higher_of_log_and_files` |
| 14 | `_logged_versions`' regex loses its `\|` anchor (`r"- v(\d+)"`) | `pytest tests/lib/test_deliver.py -q` | `test_the_log_reader_ignores_prose` — **already fired once, during Task 2's review**: the original fixture's prose line (`version 7 was skipped`) never starts with `- v`, so it never reaches the part of the pattern the anchor guards and both regexes returned `[2]`. The fixture now carries `- v9 not a real entry`, which straddles it (`[9, 2]` vs `[2]`). Re-run to confirm it still discriminates, not to discover whether it does |
| 15 | `deliver`'s `scratch_dir` gains `= out_dir`-equivalent default (`scratch_dir: str = ""` plus `scratch_dir = scratch_dir or out_dir`) | `pytest tests/lib/test_deliver.py tests/integration/test_reel_backhalf.py -q` | `test_deliver_requires_a_scratch_dir` and `test_the_deliveries_dir_holds_nothing_but_deliveries` |
| 16 | `_render_mask` is called with `out_dir` again | `pytest tests/integration/test_reel_backhalf.py -q` | `test_the_deliveries_dir_holds_nothing_but_deliveries` |
| 17 | `_wipe_scratch` is moved ABOVE the two `refuse_output_in_footage` calls | `pytest tests/lib/test_edl_to_reel.py -q` | `test_a_footage_root_work_dir_is_refused_before_anything_is_wiped` — **added during Task 3's review**, which proved the ordering was otherwise unpinned: the pre-existing refusal tests use path pairs where the wipe is a no-op regardless of order. The test needs BOTH conditions at once (`work_dir == footage_root` AND `work_dir == out_dir.parent / "build"`), and the load-bearing assertion is that the marker file SURVIVES, not that ValueError is raised |
| 18 | `_deliveries_dir` returns `out_dir` when `explicit is None` | `pytest tests/lib/test_edl_to_reel.py -q` | `test_the_deliveries_dir_is_never_the_episodes_dir` |
| 18b | `edl_to_reel()`'s `build_reel.build_reel(...)` call passes raw `out_dir` instead of `_deliveries_dir(...)` | `pytest tests/lib/test_edl_to_reel.py -q` | `test_edl_to_reel_delivers_to_the_episodes_sibling_deliveries_dir` — row 18 alone does NOT cover this: it tests the helper in isolation, and Task 3's review proved a call-site revert passed the whole suite |
| 18c | the SAME revert at `assemble_reel()`'s call | `pytest tests/lib/test_edl_to_reel.py -q` | `test_assemble_reel_delivers_to_the_episodes_sibling_deliveries_dir` — and it must be a DIFFERENT test than 18b's, or the two call sites are not independently covered |
| 19 | `_wipe_scratch` stays silent on the non-canonical branch | `pytest tests/lib/test_edl_to_reel.py -q` | `test_phase_one_leaves_a_hand_driven_scratch_alone_and_says_so` |
| 20 | `skills/edit-plan/SKILL.md` gets one `<run>/EDL.json` back | `pytest tests/test_skill_convention.py -q` | `test_no_skill_spells_a_stage_artifact_outside_its_bucket` |
| 21 | `skills/using-montage/SKILL.md` loses the `<run>/footage` line | `pytest tests/test_skill_convention.py -q` | `test_using_montage_defines_every_bucket` |
| 22 | `skills/edit-plan/SKILL.md`'s `--out-dir <run>/reels/<reel>` becomes `--out-dir .` | `pytest tests/test_skill_convention.py -q` | `test_no_skill_example_passes_a_bare_path_into_the_run` — a check added during Task 5's fix round, for the class the other three cannot see: they look for a WRONG `<run>/` prefix, and a bare path has none |
| 23 | `skills/footage-intake/SKILL.md`'s `<out_dir>` binding points at the run root | `pytest tests/test_skill_convention.py -q` | `test_footage_intake_binds_its_out_dir_to_the_footage_bucket` — that file never writes `<run>/`, so every other check is blind to it |
| 24 | the four `<run>/reels/<reel>/EDL.json` citations in `using-montage` are blanked, child buckets left intact | `pytest tests/test_skill_convention.py -q` | `test_using_montage_defines_every_bucket` — before Task 5's fix the `reel` row was a bare directory, a string PREFIX of the episodes/deliveries/build rows, so any one of them satisfied it for free |

**Run 2026-08-27, controller-executed under `PYTHONDONTWRITEBYTECODE=1`: 26 mutations, 26 RED, zero holes.** Each row was caught by the test named for it; rows 18b and 18c produced disjoint failing sets, so the two `build_reel` call sites are independently covered. Row 7's conditional does not apply — the `Stage.bucket` default IS pinned, by `test_stage_accepts_good`.

- [x] **Step 2: Close every hole**

A row that does not go RED is a coverage hole, never a row to soften. Write the missing test, confirm it discriminates by re-applying the mutation, and record it in the Done entry.

- [ ] **Step 3: Run the whole suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests
git commit -m "test: mutation battery for the run layout"
```

---

### Task 7: Docs sync and the 0.3.0 bump

**Files:**
- Modify: `.claude-plugin/plugin.json`, `CHANGELOG.md`, `CLAUDE.md`, `README.md`, `docs/backlog.md`, `docs/build-status.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Bump the plugin version**

In `.claude-plugin/plugin.json`, set `"version": "0.3.0"`. MINOR, not PATCH: the conveyor is driven differently — new paths, a new `--reel`, a new required `--scratch-dir` ([development-workflow.md](../development-workflow.md#versioning)).

- [ ] **Step 2: Add the CHANGELOG entry**

Insert above the `## 0.2.2` heading:

```markdown
## 0.3.0 — 2026-08-26

- **The run directory gets an interior, organised by lifetime.** `montage/footage/`
  survives every re-cut, `montage/reels/<name>/` holds one editorial variant, and
  inside it `episodes/` is one render generation, `deliveries/` is append-only and
  `build/` is wiped at the start of every render. Measured on the 2026-06 run: 52.8 %
  of 1119 MB was scratch nothing had ever deleted, while the 16.0 % that cannot be
  rebuilt lived in the directory the workflow `rm -rf`'d 47 times.
- **Version numbering survives.** `deliver` reads `VERSIONS.md` instead of counting
  surviving files, so an archived or deleted reel no longer renumbers the next one —
  three different reels had shipped as `REEL_v1.mp4`. Its scratch (the vignette mask,
  the title sidecars) now needs an explicit `--scratch-dir` and never lands beside the
  deliveries.
- **A second cut is a directory, not a filename suffix.** `--reel <name>` forks the
  120 KB editorial layer and shares the 194M footage layer, retiring `MUSIC_A/B/alt`
  and `pacing_A/B`.
- **`montage status` takes `--reel` in place of `--out-dir`** and returns each stage's
  resolved path, the whole layout, the reels that exist, and whether the run predates
  this layout.
```

- [ ] **Step 3: Add the CLAUDE.md registry rows**

In the Quick Reference table, after the run-dir separation rows:

```markdown
| Run-layout lifetimes design | [2026-08-26-run-layout-lifetimes-design.md](docs/specs/2026-08-26-run-layout-lifetimes-design.md) | 0.3.0: **a folder is a lifetime**. Measured on the 2026-06 run, the interior kept the wrong half — 52.8 % of 1119 MB was scratch nothing ever deleted (17 `work/ep*` for 8 episodes), while the 16.0 % that cannot be rebuilt sat in the directory `rm -rf`'d **47 times** (14 delivering runs, 2 surviving log records, three reels shipped as `REEL_v1.mp4`). `footage/` · `music/` · `reels/<name>/{episodes,deliveries,build}`; the variant boundary sits below footage because editorial is **120 KB against 194M**. **§5 inverts 0.2.1's enforcement**: a refusal needs a predicate for *wrong* and a free-form `--out-dir` is not wrong, so the INSPECTOR resolves every stage through `RunLayout` and an artifact written elsewhere simply does not count. §6: the wipe predicate is structural (`work_dir == out_dir.parent / "build"`), because "named build" makes `--work-dir ~/build` a grenade. |
| Run-layout lifetimes plan | [2026-08-26-run-layout-lifetimes.md](docs/plans/2026-08-26-run-layout-lifetimes.md) | Tasks 0–7: `RunLayout` + `wipe_build`/`deliveries_for`/`is_legacy_run`, `Stage.bucket` + the inspector's resolved paths, `deliver`'s log-reading `_next_version` + required `scratch_dir`, the guarded wipe + the phase-1/phase-2 deliveries split, two real-ffmpeg proofs, the nine skills + the machine-checked path convention, a 21-row mutation battery, the 0.3.0 bump. |
```

- [ ] **Step 4: Update README.md**

`README.md:54-55` currently reads:

> footage folder by absolute path; every artifact lands in one `montage/` folder
> beside the clips, and the finished reel in `montage/out/`.

Replace the second clause — `montage/out/` no longer exists — with:

> footage folder by absolute path; every artifact lands in one `montage/` folder
> beside the clips, organised by lifetime: `footage/` survives every re-cut,
> `reels/<name>/` holds one cut, and the finished reel sits in
> `reels/<name>/deliveries/`, which nothing ever deletes.

- [ ] **Step 5: Flip the backlog rows**

In `docs/backlog.md`, change R9.1's and R5.1's status from `○` to `✅` and append to each: `— landed 2026-08-26 (0.3.0), see [design](specs/2026-08-26-run-layout-lifetimes-design.md).`

Then add the design's §9 deferrals as new rows, per the rule that a slice is not finished until its `§Deferred` has rows here:

```markdown
| ○ | **Migrate a pre-0.3.0 run into the lifetime layout.** Not a `mv`: `out/EPISODES.json` alone carries 57 absolute paths, and moving the tree breaks the QC digest bindings and the delivery attestation that exist to notice exactly that. A path rewrite. | M | [design](specs/2026-08-26-run-layout-lifetimes-design.md) §7 |
| ○ | **Per-reel `CONSTRAINTS.json`.** `edit_plan` finds it beside `project.json`, so two variants of one reel cannot hold different standing rules. Follows today's code rather than choosing anything; no demand yet. | S | [design](specs/2026-08-26-run-layout-lifetimes-design.md) §8 |
```

- [ ] **Step 6: Update build-status.md**

Add a Done entry naming: the seven buckets, the inverted enforcement, the wipe predicate, the version-log fix, which mutation rows held, and which coverage holes the battery found.

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — `tests/test_plugin_manifests.py` enforces that the CHANGELOG's top entry matches `plugin.json`'s version.

- [ ] **Step 8: Commit**

```bash
git add CHANGELOG.md CLAUDE.md README.md .claude-plugin/plugin.json docs/backlog.md docs/build-status.md
git commit -m "docs: 0.3.0 — the run directory gets an interior"
```
