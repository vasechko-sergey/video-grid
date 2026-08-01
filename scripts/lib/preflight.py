"""Runtime-preflight registry (design docs/specs/2026-08-01-verify-runtime-design.md).

The PURE half of the verify-runtime check: the CHECKS registry (what the setup.sh
baseline contract is) and how a set of raw probe results becomes a Report. No
imports of the probed modules, no ffmpeg, no filesystem — the impure probing lives
in scripts/verify_runtime.py. That split is what makes the report logic testable
without a working install: feed evaluate() fabricated results.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    """One runtime requirement. `required` True → a failure BLOCKS the run; False →
    advisory (reported, never blocks). `remedy` is the exact shell command the user
    runs to fix it — verify_runtime PRINTS it, never runs it (design §4)."""
    key: str
    label: str
    required: bool
    remedy: str


CHECKS: tuple[Check, ...] = (
    Check("deps", "Python runtime deps import", True, "bash setup.sh"),
    Check("ffmpeg", "ffmpeg + ffprobe resolve", True, "bash setup.sh"),
    Check("drawtext", "ffmpeg drawtext filter (titles, draft labels)", True, "bash setup.sh"),
    Check("vidstab", "ffmpeg vidstab filters (intake shake, stabilize)", True, "bash setup.sh"),
    Check("font", "a drawtext font resolves", True, "bash setup.sh"),
    Check("weights", "YOLO segmentation weights present", True, "bash setup.sh"),
    Check("demucs", "demucs (sharper music in-point)", False, "bash setup.sh --with-demucs"),
)


@dataclass(frozen=True)
class CheckResult:
    """A Check joined with its probe outcome (`ok`, `detail`)."""
    key: str
    label: str
    required: bool
    ok: bool
    detail: str
    remedy: str


@dataclass(frozen=True)
class Report:
    """The outcome of every check. `ok` gates the run; `failures`/`advisories`
    split the gaps by whether they block."""
    results: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        """True iff every REQUIRED check passed — advisory results never move it."""
        return all(r.ok for r in self.results if r.required)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        """Required checks that failed — these block the run."""
        return tuple(r for r in self.results if r.required and not r.ok)

    @property
    def advisories(self) -> tuple[CheckResult, ...]:
        """Optional checks that failed — reported, never blocking."""
        return tuple(r for r in self.results if not r.required and not r.ok)
