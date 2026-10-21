"""Runtime-preflight registry (designs docs/specs/2026-08-01-verify-runtime-design.md
and docs/specs/2026-09-25-plugin-staleness-design.md).

The PURE half of the verify-runtime check: the CHECKS registry and how a set of raw
probe results becomes a RuntimeReport. No imports of the probed modules, no ffmpeg,
no filesystem — the impure probing lives in scripts/verify_runtime.py. That split is
what makes the report logic testable without a working install: feed evaluate()
fabricated results.

The registry covers TWO layers, not one. Every row but one is the `setup.sh`
baseline contract — what the installer put in the clone — and its remedy is
`bash setup.sh`. The `plugin` row is the other layer: whether the INSTALLED
skills are the ones this code expects, which `setup.sh` neither installs nor can
fix. Its remedy is `claude plugin update`. That partition is machine-checked by
tests/lib/test_preflight.py, because a count here would be wrong again the next
time a row is added — which is precisely the stale description this paragraph
replaced.
"""
import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    """One runtime requirement. `required` True → a failure BLOCKS the run; False →
    advisory (reported, never blocks). `remedy` is the shell command the user runs
    to fix it — verify_runtime PRINTS it, never runs it (design §4). It is stored
    relative (`bash setup.sh`); evaluate(root=) prefixes `cd <clone> &&` so the
    printed command runs from ANY working directory."""
    key: str
    label: str
    required: bool
    remedy: str


#: The detail `plugin_staleness` returns for `records is None`, and the exact
#: string `verify_runtime._probe_plugin` returns from its own early return for
#: the same case (no install-record file at all) without ever calling
#: `plugin_staleness`. One constant so the two call sites cannot drift apart —
#: they used to be two independently-typed copies of the same sentence.
NO_RECORD_DETAIL = "no install record — running from the clone"


CHECKS: tuple[Check, ...] = (
    Check("plugin", "installed plugin matches the code running this check", True,
          "claude plugin update video-grid@video-grid"),
    Check("deps", "Python runtime deps import", True, "bash setup.sh"),
    # A plugin update is a new code directory against the SAME venv: an update that
    # changed requirements.txt would otherwise surface as the first import that moved
    # (design 2026-10-21 §3).
    Check("deps_stamp", "the venv was built from this code's requirements.txt", True,
          "bash setup.sh"),
    Check("ffmpeg_bin", "ffmpeg + ffprobe resolve", True, "bash setup.sh"),
    Check("drawtext", "ffmpeg drawtext filter (titles, draft labels)", True, "bash setup.sh"),
    Check("vidstab", "ffmpeg vidstab filters (intake shake, stabilize)", True, "bash setup.sh"),
    Check("font", "a drawtext font resolves", True, "bash setup.sh"),
    Check("weights", "YOLO segmentation weights present", True, "bash setup.sh"),
    Check("demucs", "demucs vocal separation (music in/out-point)", True, "bash setup.sh"),
    Check("reid", "torchreid person-re-ID (cast identity)", False, "bash setup.sh"),
    # Advisory: only a title carrying an icon needs it, and that title is refused by name
    # at `titles check` without it (retro 2026-10-16 S13).
    Check("icon_font", "icon font for title icons (Noto Emoji)", False, "bash setup.sh"),
)


@dataclass(frozen=True)
class CheckOutcome:
    """A Check joined with its probe outcome (`ok`, `detail`)."""
    key: str
    label: str
    required: bool
    ok: bool
    detail: str
    remedy: str


@dataclass(frozen=True)
class RuntimeReport:
    """The outcome of every check. `ok` gates the run; `failures`/`advisories`
    split the gaps by whether they block."""
    results: tuple[CheckOutcome, ...]

    @property
    def ok(self) -> bool:
        """True iff every REQUIRED check passed — advisory results never move it."""
        return all(r.ok for r in self.results if r.required)

    @property
    def failures(self) -> tuple[CheckOutcome, ...]:
        """Required checks that failed — these block the run."""
        return tuple(r for r in self.results if r.required and not r.ok)

    @property
    def advisories(self) -> tuple[CheckOutcome, ...]:
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


def evaluate(raw: dict[str, tuple[bool, str]],
             root: str | None = None) -> RuntimeReport:
    """Join raw probe results (key -> (ok, detail)) with CHECKS into a RuntimeReport.

    `raw`'s keys MUST equal the registry's keys exactly. A probe without a Check,
    or a Check without a probe, is a bug — it raises rather than silently skipping
    a requirement (design §7 invariant 3).

    When `root` (the clone directory) is given, each remedy is prefixed with
    `cd <root> &&` so the printed command runs from ANY working directory — the
    user can click Run wherever their shell happens to be, not only from the clone
    root. `root` is shell-quoted, so a path with spaces stays one argument. Without
    `root` the remedies stay relative (`bash setup.sh`)."""
    want = {c.key for c in CHECKS}
    got = set(raw)
    if want != got:
        raise ValueError(
            f"preflight raw keys {sorted(got)} != registry keys {sorted(want)}")
    prefix = f"cd {shlex.quote(str(root))} && " if root is not None else ""
    results = tuple(
        CheckOutcome(key=c.key, label=c.label, required=c.required,
                     ok=raw[c.key][0], detail=raw[c.key][1], remedy=prefix + c.remedy)
        for c in CHECKS)
    return RuntimeReport(results=results)


def plugin_staleness(records: tuple[tuple[str, str], ...] | None,
                     clone_version: str) -> tuple[bool, str]:
    """Does the INSTALLED plugin agree with the clone about to run?

    `records` is one (scope, version) pair per install record, or None when there
    is no install-record file at all. The two absences are reported separately
    because they have different causes and the same conclusion: there is no
    installed instruction set that could be stale, so both PASS.

    A sequence — not one record — because installed_plugins.json maps a plugin id
    to a LIST (user / project / local / managed scopes). Every record is compared
    and every mismatch is named; `scope` is reported, never interpreted, since
    nothing here knows which one Claude Code actually loaded (design §6).

    The direction of a mismatch is deliberately not computed: the marketplace is
    the clone itself, so one remedy resolves it either way, and a number that
    changes no decision is not reported (design §4)."""
    if records is None:
        return True, NO_RECORD_DETAIL
    if not records:
        return True, "not installed as a plugin — running from the clone"
    bad = [(scope, ver) for scope, ver in records if ver != clone_version]
    if not bad:
        return True, f"{clone_version} installed"
    named = ", ".join(f"{scope} scope has {ver}" for scope, ver in bad)
    return False, (f"{named}; the clone is {clone_version} — the installed "
                   f"skills are not the ones this code expects. After updating, "
                   f"restart Claude Code: the update rewrites the cache, it does "
                   f"not reload the skills a running session already holds.")
