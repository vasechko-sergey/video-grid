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
    Check("ffmpeg_bin", "ffmpeg + ffprobe resolve", True, "bash setup.sh"),
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

    def to_dict(self) -> dict:
        """JSON payload: overall ok plus each result as a flat dict."""
        return {
            "ok": self.ok,
            "results": [
                {"key": r.key, "label": r.label, "required": r.required,
                 "ok": r.ok, "detail": r.detail, "remedy": r.remedy}
                for r in self.results],
        }

    def to_text(self) -> str:
        """A human report: one line per check (OK / FAIL / warn), then the remedy
        for each gap. Deterministic — the tests pin its shape."""
        header = "runtime ready" if self.ok else "runtime NOT ready"
        lines = [header]
        for r in self.results:
            mark = "OK  " if r.ok else ("FAIL" if r.required else "warn")
            line = f"[{mark}] {r.key}: {r.label}"
            if r.detail:
                line += f" — {r.detail}"
            lines.append(line)
        if self.failures:
            lines.append("")
            lines.append("BLOCKED — required checks failed; fix then re-run:")
            lines += [f"  {r.key}: {r.remedy}" for r in self.failures]
        if self.advisories:
            lines.append("")
            lines.append("Optional (not blocking):")
            lines += [f"  {r.key}: {r.remedy}" for r in self.advisories]
        return "\n".join(lines)


def evaluate(raw: dict[str, tuple[bool, str]]) -> Report:
    """Join raw probe results (key -> (ok, detail)) with CHECKS into a Report.

    `raw`'s keys MUST equal the registry's keys exactly. A probe without a Check,
    or a Check without a probe, is a bug — it raises rather than silently skipping
    a requirement (design §7 invariant 3)."""
    want = {c.key for c in CHECKS}
    got = set(raw)
    if want != got:
        raise ValueError(
            f"preflight raw keys {sorted(got)} != registry keys {sorted(want)}")
    results = tuple(
        CheckResult(key=c.key, label=c.label, required=c.required,
                    ok=raw[c.key][0], detail=raw[c.key][1], remedy=c.remedy)
        for c in CHECKS)
    return Report(results=results)
