"""Deliver a checked reel master → out/REEL_v{n}.<container> per an ExportProfile,
with a version log (design §5, montage §5.14 + §11 version-log binding). The one
encode of the back half; a hard gate refuses a failed reel."""
import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from scripts.lib import assembly, ffbin, look as look_lib, lookcheck, proc, provenance
from scripts.lib.look import LookSpec
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


def _render_mask(master: str, out_dir: str, vignette: float) -> str:
    """Render the one-frame RGBA vignette mask at the MASTER's real pixels.

    Probed, never derived from a config: the delivery's dimensions are what the
    episodes actually produced, and a mask built at a config's idea of the canvas
    would letterbox the whole reel silently. No cache — this is one frame, and a
    stale mask keyed to the wrong dimensions is exactly the failure not caching
    avoids (design §11.6)."""
    si = assembly.probe_stream(master)
    mask = str(Path(out_dir) / "look_mask.png")
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", f"nullsrc=s={si.w}x{si.h}:d=1:r=1",
              "-vf", look_lib.mask_expr(vignette), "-frames:v", "1", mask])
    return mask


def _verify_look(master: str, out: str, look: LookSpec | None,
                 titles: str | None) -> list[lookcheck.LookFinding]:
    """Prove the declared look reached the DELIVERED pixels (design 2026-08-15 §7).

    check_reel measured the master; everything below rides this encode and nothing
    else ever reads the result. Samples three interior frames from both files at the
    same timestamps — and t=0 from both as well when a fade was declared.

    Each file's own fps is probed separately rather than shared: a profile that
    changed the rate would otherwise shift every frame number on one side only, and
    compare two different moments as if they were one.

    With nothing declared this makes no ffmpeg call at all, so a look-less delivery
    costs exactly what it cost before this gate existed.
    """
    vig = look.vignette if look is not None else 0.0
    fade = look.fade if look is not None else 0.0
    if not (vig or fade or titles is not None):
        return []
    ts = [d * f for d in (assembly.probe_duration(out),) for f in (0.25, 0.5, 0.75)]
    m_fps, d_fps = assembly.probe_stream(master).fps, assembly.probe_stream(out).fps
    first_m = first_d = None
    if fade:
        first_m = assembly.frames_rgb(master, [0.0], m_fps)[0]
        first_d = assembly.frames_rgb(out, [0.0], d_fps)[0]
    return lookcheck.evaluate(assembly.frames_rgb(master, ts, m_fps),
                              assembly.frames_rgb(out, ts, d_fps),
                              first_m, first_d,
                              vignette=vig, fade=fade, titles=titles is not None)


def deliver(master: str, profile: ExportProfile, out_dir: str, changelog: str,
            report: ReelReport, *, audio: str | None = None, titles: str | None = None,
            platform: str = "", look: LookSpec | None = None,
            run_provenance: dict | None = None) -> str:
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

    With `look` (design 2026-08-13), a plateau vignette and/or a bookend fade ride
    this same encode. A vignette needs a second input (the mask), so the video
    filters move from -vf into -filter_complex and the audio stem — when there is
    one — becomes input 2 rather than input 1. Without a vignette the argv is
    byte-for-byte what it was before looks existed.

    Two bindings guard the gate, in this order. `report.overall` refuses a reel that
    failed; then `report.master_digest` refuses a report that does not describe THIS
    file — an empty digest means the report was not written by `check_reel` (its only
    producer, which always stamps), a mismatched one means the master was re-made after
    the check or assembled outside the pipeline. `run_provenance` carries what only the
    driver knows (the run's start stamp, the EDL's digest and state, the loosened
    thresholds, the episode QC state) into the `REEL_v{n}.attest.json` sidecar this
    writes.

    A third refusal fires AFTER the encode: `_verify_look` (design 2026-08-15 §7)
    samples the shipped file against the master and refuses when a declared vignette,
    fade or titles did not reach the delivered pixels — check_reel never sees this
    file, so nothing else would ever catch a filter silently dropped from the chain.
    Unlike the two bindings above, the file is left on disk on failure; only the
    attestation is withheld, which is what has no waiver."""
    if not report.overall:
        raise RuntimeError("reel failed check_reel — fix the flagged episodes and re-check; "
                           "deliver does not ship a failed reel (no fix-forward)")
    # Two refusals below, deliberately in this order, and deliberately carrying DIFFERENT
    # remedies: an empty digest means no check_reel run ever produced this report at all
    # (no producer); a mismatched one means a check_reel run happened but not against
    # THIS file. Do not fold them into one condition. Deleting the empty-digest check
    # would not go silent — a real sha256 (`actual`) is never "", so "" != actual falls
    # straight through to the mismatch branch and still raises — but
    # test_deliver_refuses_a_report_with_no_master_digest pins the FIRST message's text
    # ("did not come from check_reel"), which the mismatch branch does not contain. That
    # test would still go red on a dropped check, just on the regex, not on "no exception
    # was raised" — a weaker signal to notice, which is why the message text is load-bearing.
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
    # Titles and the look share ONE video-filter slot (§5.16 + design 2026-08-13 §4):
    # build_filterchain writes each title's text to a title_i.txt sidecar in out_dir
    # and returns a drawtext chain; look.chain appends the bookend fade AFTER it, so
    # a title goes to black with the picture. ExportProfile.args() emits no -vf/scale,
    # so nothing clobbers this (last -vf wins in ffmpeg — the §12 silent-drop flavor).
    title_chain = ""
    if titles is not None:
        title_chain = build_filterchain(Titles.from_json(titles), out_dir, platform=platform)
    dur = assembly.probe_duration(master) if (look is not None and look.fade) else 0.0
    parts = look_lib.chain(look, dur, title_chain)
    mask_in: list[str] = []
    graph: list[str] = []
    vmap: list[str] = []
    if look is not None and look.has_vignette:
        mask_in = ["-loop", "1", "-i", _render_mask(master, out_dir, look.vignette)]
        graph = ["-filter_complex",
                 ",".join(["[0:v][1:v]overlay=shortest=1", *parts]) + "[v]"]
        vmap = ["-map", "[v]"]
    elif parts:
        graph = ["-vf", ",".join(parts)]
    n = _next_version(out_dir, profile.container)
    out = str(Path(out_dir) / f"REEL_v{n}.{profile.container}")
    if audio is None:
        proc.run([ffbin.ffmpeg(), "-y", "-i", master, *mask_in, *graph, *vmap,
                  *profile.args(), out])
    else:
        # mux the pre-normalized aac stem: profile audio settings don't apply — we
        # stream-copy to preserve the stem's −14 LUFS — so use video-only args + copy.
        # The stem's input index is 1 normally and 2 behind the mask: `-loop 1 -i mask`
        # occupies index 1, and mapping 1:a:0 there would look for an audio stream in
        # a PNG.
        aidx = 2 if mask_in else 1
        proc.run([ffbin.ffmpeg(), "-y", "-i", master, *mask_in, "-i", audio, *graph,
                  *_video_only_args(profile), *(vmap or ["-map", "0:v:0"]),
                  "-map", f"{aidx}:a:0", "-c:a", "copy", "-shortest", out])
    # The look gate (design 2026-08-15 §7). AFTER the encode, because the honest
    # subject is the file that shipped, not a prediction of it. On a failure the file
    # stays on disk — deleting output nobody asked to delete is worse than leaving the
    # evidence — but no attestation is written, which montage status already reports as
    # an unattested delivery. No waiver (governance #8).
    look_checks = _verify_look(master, out, look, titles)
    bad = [f for f in look_checks if f.status == "fail"]
    if bad:
        raise RuntimeError(
            f"{Path(out).name} does not carry the look it declared: "
            + "; ".join(f"{f.check} — {f.detail}" for f in bad)
            + f". The file is on disk to look at, but no attestation was written, so "
              f"`montage status` reports it as unattested. Fix the look chain (EDL.look, "
              f"or the titles file) and deliver again — this gate has no waiver")
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
        episode_qc=rp.get("episode_qc") or {},
        look_checks=[f.to_dict() for f in look_checks],
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
    ap.add_argument("--vignette", type=float, default=0.0,
                    help="corner darkening 0..0.6 (0 = off) — the reel's plateau vignette")
    ap.add_argument("--fade", type=float, default=0.0,
                    help="bookend fade seconds per end 0..2.0 (0 = off)")
    a = ap.parse_args()
    report = ReelReport.from_dict(json.loads(Path(a.report).read_text()))
    out = deliver(a.master, ExportProfile(), a.out_dir, a.changelog, report,
                  titles=a.titles, platform=a.platform,
                  look=LookSpec(vignette=a.vignette, fade=a.fade))
    print(out)


if __name__ == "__main__":
    main()
