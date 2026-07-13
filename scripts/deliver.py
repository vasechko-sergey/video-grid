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
from scripts.lib.titles import Titles, build_filterchain


def _next_version(out_dir: str, container: str) -> int:
    rx = re.compile(rf"REEL_v(\d+)\.{re.escape(container)}$")
    ns = [int(m.group(1)) for p in Path(out_dir).glob(f"REEL_v*.{container}")
          if (m := rx.match(p.name))]
    return max(ns) + 1 if ns else 1


def _video_only_args(profile: ExportProfile) -> list[str]:
    """profile.args() with any audio-output flag stripped — the mux path stream-copies
    a pre-encoded −14 LUFS stem, so the profile's audio codec/bitrate never apply (and
    leaving -c:a/-b:a in would double-specify against the -c:a copy below)."""
    args = profile.args()
    out: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "-an":
            i += 1
        elif args[i] in ("-c:a", "-b:a"):
            i += 2                      # drop the flag and its value
        else:
            out.append(args[i])
            i += 1
    return out


def _log_version(out_dir: str, n: int, changelog: str) -> None:
    vf = Path(out_dir) / "VERSIONS.md"
    if not vf.exists():
        vf.write_text("# Reel versions\n\n")
    stamp = datetime.now().strftime("%Y-%m-%d")
    with vf.open("a") as f:
        f.write(f"- v{n} | {stamp} | {changelog}\n")


def deliver(master: str, profile: ExportProfile, out_dir: str, changelog: str,
            report: ReelReport, audio: str | None = None, titles: str | None = None) -> str:
    """Encode the checked master to the next REEL_v{n} and log the version. With
    `audio`, mux the pre-normalized aac stem alongside the encode (design §6).
    Hard gate: a failed reel is never shipped (no fix-forward, montage §176).
    The mux path assumes the audio stem's duration matches the master (build_reel
    derives mix's dur from the probed master); -shortest only absorbs sub-second
    jitter — a grossly short stem would truncate the picture, so callers must keep
    them aligned.
    With `titles` (a TITLES.json path), burn the drawtext chain into this one
    encode (design §5.16) — no second pass."""
    if not report.overall:
        raise RuntimeError("reel failed check_reel — fix the flagged episodes and re-check; "
                           "deliver does not ship a failed reel (no fix-forward)")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    vf: list[str] = []
    if titles is not None:
        chain = build_filterchain(Titles.from_json(titles), out_dir)
        if chain:
            vf = ["-vf", chain]
    n = _next_version(out_dir, profile.container)
    out = str(Path(out_dir) / f"REEL_v{n}.{profile.container}")
    if audio is None:
        proc.run(["ffmpeg", "-y", "-i", master, *vf, *profile.args(), out])
    else:
        # mux the pre-normalized aac stem: profile audio settings don't apply — we
        # stream-copy to preserve the stem's −14 LUFS — so use video-only args + copy
        proc.run(["ffmpeg", "-y", "-i", master, "-i", audio, *vf, *_video_only_args(profile),
                  "-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy", "-shortest", out])
    _log_version(out_dir, n, changelog)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Deliver a checked reel master.")
    ap.add_argument("master")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--report", required=True, help="ReelReport JSON from check_reel")
    ap.add_argument("--changelog", default="")
    ap.add_argument("--titles", default=None, help="TITLES.json — burn on-screen text into the encode (§5.16)")
    a = ap.parse_args()
    report = ReelReport.from_dict(json.loads(Path(a.report).read_text()))
    out = deliver(a.master, ExportProfile(), a.out_dir, a.changelog, report, titles=a.titles)
    print(out)


if __name__ == "__main__":
    main()
