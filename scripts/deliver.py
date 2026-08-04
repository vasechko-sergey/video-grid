"""Deliver a checked reel master → out/REEL_v{n}.<container> per an ExportProfile,
with a version log (design §5, montage §5.14 + §11 version-log binding). The one
encode of the back half; a hard gate refuses a failed reel."""
import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from scripts.lib import ffbin, proc, provenance
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
            report: ReelReport, *, audio: str | None = None, titles: str | None = None,
            platform: str = "", run_provenance: dict | None = None) -> str:
    """Encode the checked master to the next REEL_v{n} and log the version. With
    `audio`, mux the pre-normalized aac stem alongside the encode (design §6).
    Hard gate: a failed reel is never shipped (no fix-forward, montage §176).
    The mux path assumes the audio stem's duration matches the master (build_reel
    derives mix's dur from the probed master); -shortest only absorbs sub-second
    jitter — a grossly short stem would truncate the picture, so callers must keep
    them aligned.
    With `titles` (a TITLES.json path), burn the drawtext chain into this one encode
    (design §5.16) — no second pass. `platform` is the same safe-zone table key
    check_reel judges the PICTURE against; it must reach here too, or a bottom title
    is laid out against generic margins and lands under the app's chrome.

    Two bindings guard the gate, in this order. `report.overall` refuses a reel that
    failed; then `report.master_digest` refuses a report that does not describe THIS
    file — an empty digest means the report was not written by `check_reel` (its only
    producer, which always stamps), a mismatched one means the master was re-made after
    the check or assembled outside the pipeline. `run_provenance` carries what only the
    driver knows (the run's start stamp, the EDL's digest and state, the loosened
    thresholds) into the `REEL_v{n}.attest.json` sidecar this writes."""
    if not report.overall:
        raise RuntimeError("reel failed check_reel — fix the flagged episodes and re-check; "
                           "deliver does not ship a failed reel (no fix-forward)")
    if not report.master_digest:
        raise RuntimeError(
            "this reel report carries no master digest, so it did not come from check_reel — "
            "nothing binds it to the file being shipped. check_reel is the only thing that "
            "writes a report and it always stamps one. Run `check_reel` on this master and "
            "deliver with the report it writes")
    actual = provenance.digest_file(master)
    if actual != report.master_digest:
        raise RuntimeError(
            f"this reel report describes a different file than the master being shipped "
            f"(report {report.master_digest[:12]}…, master {actual[:12]}…) — the master was "
            f"re-made after the check, or assembled outside the pipeline. Re-run "
            f"`check_reel` on THIS master and deliver with the report it writes")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    # Titles ride deliver's ONE encode (§5.16): build_filterchain writes each title's
    # text to a title_i.txt sidecar in out_dir (work_dir=out_dir) and returns a drawtext
    # chain. This is the SOLE -vf slot — ExportProfile.args() emits no -vf/scale, so
    # nothing clobbers it (last -vf wins in ffmpeg — the §12 silent-drop flavor).
    vf: list[str] = []
    if titles is not None:
        chain = build_filterchain(Titles.from_json(titles), out_dir, platform=platform)
        if chain:
            vf = ["-vf", chain]
    n = _next_version(out_dir, profile.container)
    out = str(Path(out_dir) / f"REEL_v{n}.{profile.container}")
    if audio is None:
        proc.run([ffbin.ffmpeg(), "-y", "-i", master, *vf, *profile.args(), out])
    else:
        # mux the pre-normalized aac stem: profile audio settings don't apply — we
        # stream-copy to preserve the stem's −14 LUFS — so use video-only args + copy
        proc.run([ffbin.ffmpeg(), "-y", "-i", master, "-i", audio, *vf, *_video_only_args(profile),
                  "-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy", "-shortest", out])
    _log_version(out_dir, n, changelog)
    # The delivery's record (design §6). reel_digest binds it to the SHIPPED file, not
    # only to the master, so a reel swapped after delivery is detectable. A hand-run
    # ffmpeg produces no sidecar at all, which is what montage status reports.
    rp = run_provenance or {}
    provenance.Attestation(
        reel=Path(out).name, reel_digest=provenance.digest_file(out),
        master_digest=actual, report_digest=provenance.digest_obj(report.to_dict()),
        overall=report.overall,
        engine_at_start=rp.get("engine_at_start") or {},
        engine_at_deliver=provenance.engine_stamp(),
        edl=rp.get("edl") or {}, overrides=rp.get("overrides") or [],
        delivered_at=datetime.now().isoformat(timespec="seconds"),
    ).write(provenance.attest_path(out))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Deliver a checked reel master.")
    ap.add_argument("master")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--report", required=True, help="ReelReport JSON from check_reel")
    ap.add_argument("--changelog", default="")
    ap.add_argument("--titles", default=None, help="TITLES.json — burn on-screen text into the encode (§5.16)")
    ap.add_argument("--platform", default="", help="safe-zone table key (reel/tiktok/shorts/…) — "
                                                   "where the app's chrome sits; titles lay out inside it")
    a = ap.parse_args()
    report = ReelReport.from_dict(json.loads(Path(a.report).read_text()))
    out = deliver(a.master, ExportProfile(), a.out_dir, a.changelog, report,
                  titles=a.titles, platform=a.platform)
    print(out)


if __name__ == "__main__":
    main()
