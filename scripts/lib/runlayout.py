"""Where a montage run's artifacts live, and the one rule about where they do not.

The conveyor discovers footage by extension over a FLAT listing of the footage
root (intake.py: `root.iterdir()`, no exclusion). Anything it writes there that
happens to be a video — or, since photos are footage too, an image — therefore
becomes source material on the next scan —
measured 2026-08-19: `draft.mp4` sat among 99 real clips and escaped the scan
only because the scan had already run (design 2026-08-25 §0).

So the run gets its own folder, `<footage_root>/montage/`, and the two stages
that know the footage root and write into a caller-chosen directory refuse to
be pointed at the footage root itself.
"""
import shutil
from dataclasses import dataclass
from pathlib import Path

RUN_DIRNAME = "montage"       # <footage_root>/montage — see the skills and the README
VIDEO_EXTS = frozenset({".mp4", ".mov", ".m4v", ".avi"})
# Stills intake reads since 2026-10-20 (design docs/specs/2026-10-20-photos-design.md §1).
# RAW (.dng) is not here: Pillow would hand back the embedded preview, not the photo.
PHOTO_EXTS = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif"})
FOOTAGE_EXTS = VIDEO_EXTS | PHOTO_EXTS   # what intake scans for, and so what marks a
                                         # directory as footage


def is_photo(name: str | Path) -> bool:
    """The one predicate for "this source is a still": its extension. Asked by intake,
    the EDL, the manifest bridge and extract, so the four cannot disagree."""
    return Path(name).suffix.lower() in PHOTO_EXTS

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
    always matches. "The directory is named build" would make a hand-driven
    `--work-dir ~/build` a grenade (design §6).

    It is NOT unique to the canonical run, and this docstring claimed it was until
    2026-08-27. The predicate reads "work_dir is out_dir's sibling named build" — it
    never checks reels/ or episodes — so `--work-dir <X>/build --out-dir <X>/notes`
    matches too. What bounds it is that the directory wiped is always the one the
    caller itself nominated as scratch, plus edl_to_reel's refusal of
    `work_dir == out_dir`, which was the one arrangement where this was destructive.
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


PARTIAL_GLOB = ".REEL_v*.part.*"   # what montage looks for to report an interrupted delivery


def partial_path(out_dir: str, n: int, container: str) -> Path:
    """Where the encode lands before it is a delivery (design 2026-09-09 §5).

    Three details are load-bearing. It sits in `out_dir`, not scratch_dir, so the
    os.replace below is a same-filesystem rename and therefore atomic — a caller may
    point scratch_dir at another mount. It starts with a DOT, which takes it out of
    all three globs that look for deliveries (_next_version's REEL_v*.{container},
    montage._deliveries' REEL_v*, and the router's Stage("deliver", "REEL_v*.*")), so
    a killed encode consumes no version and does not make the stage read done. And the
    container extension comes LAST, because ffmpeg picks its muxer from the output
    filename — `.REEL_v3.part` would fail to guess one.

    A leftover partial is not litter: it is the record that a delivery was interrupted,
    which is the second half of what the retro's R5.3 asked for. `-y` stays on the
    encode, so a retry overwrites it rather than accumulating."""
    return Path(out_dir) / f".REEL_v{n}.part.{container}"


def refuse_output_in_footage(footage_root: str, out_dir: str, what: str) -> None:
    """Raise unless `out_dir` is somewhere other than the footage root itself.

    EQUALITY, never containment: `<footage_root>/montage` is inside the footage
    root and must pass, or this would forbid the layout it exists to protect.
    Both ends resolve() so a trailing slash, a `..` segment or a symlink cannot
    spell past it.
    """
    root = Path(footage_root).resolve()
    if Path(out_dir).resolve() != root:
        return
    raise ValueError(
        f"{what} resolves to the footage folder itself ({root}) — the conveyor "
        f"would write its output into the directory intake scans for source "
        f"clips, and any .mp4 landing there is taken as footage by the next scan "
        f"(draft.mp4 already did, and went unnoticed). Point it at "
        f"{root / RUN_DIRNAME} instead.")


def refuse_project_dir_holding_footage(project_dir: str, what: str) -> None:
    """Raise when `project_dir` itself holds video files — it is the footage folder, and
    the run belongs in `<it>/montage`.

    Only the directory's own files count (intake's flat iterdir): the run dir keeps its
    renders deeper, under reels/<reel>/, so it passes however much it has rendered. The
    second real run began with /video-grid:project-init, whose skill said only
    --project-dir <dir>, and project.json landed beside the clips (retro 2026-10-16 S10).
    """
    d = Path(project_dir)
    if not d.is_dir():
        return
    clips = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in FOOTAGE_EXTS]
    if not clips:
        return
    raise ValueError(
        f"{what}: {d.resolve()} holds {len(clips)} video or photo file(s) — it is the footage "
        f"folder, which intake scans for source clips, not the run directory. Point it "
        f"at {d.resolve() / RUN_DIRNAME} instead.")
