"""Deliver a checked reel master → out/REEL_v{n}.<container> per an ExportProfile,
with a version log (design §5, montage §5.14 + §11 version-log binding). The one
encode of the back half; a hard gate refuses a failed reel."""
import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from scripts.lib import proc
from scripts.lib.models import ExportProfile, ReelReport


def _next_version(out_dir: str, container: str) -> int:
    rx = re.compile(rf"REEL_v(\d+)\.{re.escape(container)}$")
    ns = [int(m.group(1)) for p in Path(out_dir).glob(f"REEL_v*.{container}")
          if (m := rx.match(p.name))]
    return max(ns) + 1 if ns else 1


def _log_version(out_dir: str, n: int, changelog: str) -> None:
    vf = Path(out_dir) / "VERSIONS.md"
    if not vf.exists():
        vf.write_text("# Reel versions\n\n")
    stamp = datetime.now().strftime("%Y-%m-%d")
    with vf.open("a") as f:
        f.write(f"- v{n} | {stamp} | {changelog}\n")


def deliver(master: str, profile: ExportProfile, out_dir: str, changelog: str,
            report: ReelReport) -> str:
    """Encode the checked master to the next REEL_v{n} and log the version.
    Hard gate: a failed reel is never shipped (no fix-forward, montage §176)."""
    if not report.overall:
        raise RuntimeError("reel failed check_reel — fix the flagged episodes and re-check; "
                           "deliver does not ship a failed reel (no fix-forward)")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    n = _next_version(out_dir, profile.container)
    out = str(Path(out_dir) / f"REEL_v{n}.{profile.container}")
    proc.run(["ffmpeg", "-y", "-i", master, *profile.args(), out])
    _log_version(out_dir, n, changelog)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Deliver a checked reel master.")
    ap.add_argument("master")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--report", required=True, help="ReelReport JSON from check_reel")
    ap.add_argument("--changelog", default="")
    a = ap.parse_args()
    report = ReelReport.from_dict(json.loads(Path(a.report).read_text()))
    out = deliver(a.master, ExportProfile(), a.out_dir, a.changelog, report)
    print(out)


if __name__ == "__main__":
    main()
