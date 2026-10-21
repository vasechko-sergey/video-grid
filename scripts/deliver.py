"""Deliver a checked reel master → out/REEL_v{n}.<container> per an ExportProfile,
with a version log (design §5, montage §5.14 + §11 version-log binding). The one
encode of the back half; a hard gate refuses a failed reel."""
import argparse
import json
import math
import os
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from scripts.lib import (assembly, ffbin, look as look_lib, lookcheck, proc,
                         provenance, runlayout, titles as titles_lib)
from scripts.lib.look import LookSpec
from scripts.lib.models import ExportProfile, ReelReport
from scripts.lib.titles import Title, Titles, build_filterchain


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


def _since_last(out_dir: str, n: int, container: str, run_provenance: dict | None) -> str:
    """' · same EDL as v{n-1}' / ' · EDL changed since v{n-1}', or '' when either side
    carries no EDL digest. Tells a re-cut from a re-render of the same cut — the second
    real run's five VERSIONS.md lines were identical words (retro 2026-10-16 S11)."""
    now = ((run_provenance or {}).get("edl") or {}).get("digest") or ""
    prev = Path(out_dir) / f"REEL_v{n - 1}.{container}"
    if n < 2 or not now or not provenance.attest_path(prev).is_file():
        return ""
    try:
        edl = provenance.Attestation.from_json(provenance.attest_path(prev)).edl
    except (OSError, ValueError, TypeError):
        return ""
    before = edl.get("digest") if isinstance(edl, dict) else None
    if not before:
        return ""
    return f" · same EDL as v{n - 1}" if before == now else f" · EDL changed since v{n - 1}"


def _log_version(out_dir: str, n: int, changelog: str) -> None:
    vf = Path(out_dir) / "VERSIONS.md"
    if not vf.exists():
        vf.write_text("# Reel versions\n\n")
    stamp = datetime.now().strftime("%Y-%m-%d")
    with vf.open("a") as f:
        f.write(f"- v{n} | {stamp} | {changelog}\n")


def _render_mask(master: str, scratch_dir: str, vignette: float) -> str:
    """Render the one-frame RGBA vignette mask at the MASTER's real pixels.

    Probed, never derived from a config: the delivery's dimensions are what the
    episodes actually produced, and a mask built at a config's idea of the canvas
    would letterbox the whole reel silently. No cache — this is one frame, and a
    stale mask keyed to the wrong dimensions is exactly the failure not caching
    avoids (design §11.6)."""
    si = assembly.probe_stream(master)
    mask = str(Path(scratch_dir) / "look_mask.png")
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", f"nullsrc=s={si.w}x{si.h}:d=1:r=1",
              "-vf", look_lib.mask_expr(vignette), "-frames:v", "1", mask])
    return mask


# How many title-free moments to compare a title against. Measured, the witness barely
# matters for a single-shot title (2.9645%-2.9966% across five), but a bold-box one
# swings 3.53%-18.94% on what the witness frame happens to show — so a handful,
# best-of. Each costs one frame from each file (design 2026-08-19 §2.4).
_TITLE_WITNESSES = 3
_WITNESS_GRID = 24          # candidate instants scanned across the legal window


def _title_band(t: Title, h: int, platform: str) -> tuple[int, int]:
    """The delivered rows lookcheck measures for this title: titles.ink_extent padded
    by lookcheck.TITLE_BAND_PAD font sizes each side, in pixels, clamped to the frame."""
    top, bottom = titles_lib.ink_extent(t, platform)
    pad = lookcheck.TITLE_BAND_PAD * t.scale / titles_lib.FONTSIZE_DIV
    return (max(0, int((top - pad) * h)), min(h, int(math.ceil((bottom + pad) * h))))


def _title_times(items: tuple[Title, ...], i: int, dur: float,
                 fade: float, fade_in: float | None = None, *,
                 windows: Sequence[tuple[float, float]] = ()
                 ) -> tuple[float, tuple[float, ...], str]:
    """(in-window time, witness times, skip reason) for item `i`.

    Both ends are clamped into [fade, dur - fade] because BOTH break inside a ramp, in
    opposite directions and for different reasons (design 2026-08-19 §4): a title
    sampled at alpha 0.10 has almost no ink left to find, and a witness faded toward
    black makes |d_in - d_out| large with no title involved at all — a false fail and a
    false pass respectively, and a no-waiver gate can afford neither.

    `fade` is the closing ramp and, unless `fade_in` sets it apart, the opening one: a
    reel that opens on picture has no opening ramp to clamp out of (retro 2026-10-16 S6).

    `windows` are the shutter flashes' (look.flash_windows): the flash is white in the
    delivered file and absent from the master, so a sample on one reads as a title
    where there is none. The in-window time is the midpoint of the longest flash-free
    part of the clamped window, and a witness inside a flash is dropped. With no
    flashes this is the sampling it always was (design 2026-10-21 §4)."""
    head = fade if fade_in is None else fade_in
    lo, hi = float(head), float(dur) - float(fade)
    t = items[i]
    ramps = (f"{fade:g}s bookend fade" if head == fade
             else f"bookend fades ({head:g}s in, {fade:g}s out)")
    if hi - lo <= 0:
        return 0.0, (), (f"the {ramps} cover{'s' if head == fade else ''} the whole "
                         f"{dur:g}s reel, so there is no frame outside a ramp to measure")
    w_lo, w_hi = max(t.start, lo), min(t.start + t.dur, hi)
    if w_hi - w_lo <= 0:
        return 0.0, (), (f"the title's window [{t.start:g}, {t.start + t.dur:g}] lies "
                         f"entirely inside the {ramps}, where a correctly "
                         f"rendered title is drawn too faint to measure")
    parts = look_lib.flash_free(w_lo, w_hi, windows)
    if not parts:
        return 0.0, (), (f"every instant of the title's measurable window [{w_lo:g}, "
                         f"{w_hi:g}] sits on a shutter flash or the frame either side of "
                         f"one, where the delivered picture is white and the master's is not")
    p_lo, p_hi = max(parts, key=lambda p: p[1] - p[0])
    covered = [(it.start, it.start + it.dur) for it in items]
    grid = [lo + (hi - lo) * (k + 0.5) / _WITNESS_GRID for k in range(_WITNESS_GRID)]
    free = [x for x in grid if not any(a <= x <= b for a, b in covered)
            and look_lib.clear_of_flash(x, windows) == x]
    if not free:
        return 0.0, (), ("every instant of the reel carries a title or a shutter flash, "
                         "so there is no title-free frame to compare against"
                         if windows else
                         "every instant of the reel carries a title, so there is no "
                         "title-free frame to compare against")
    step = max(1, len(free) // _TITLE_WITNESSES)
    return (p_lo + p_hi) / 2, tuple(free[::step][:_TITLE_WITNESSES]), ""


def _verify_look(master: str, out: str, look: LookSpec | None,
                 titles: str | None, platform: str = "",
                 flashes: Sequence[float] = ()) -> list[lookcheck.LookFinding]:
    """Prove the declared look reached the DELIVERED pixels (design 2026-08-15 §7).

    check_reel measured the master; everything below rides this encode and nothing
    else ever reads the result. Samples three interior frames from both files at the
    same timestamps — and, when a fade was declared, BOTH bookend frames from both
    files: t=0 (fade-in) and each file's own TRUE last decodable frame (fade-out),
    via `assembly.last_frame_rgb` rather than a computed timestamp — `deliver`
    derives the fade-out's start from the MASTER's duration, but the audio mux's
    `-shortest` can truncate the DELIVERED file short of that, and even without any
    truncation a computed `dur - 1/fps` can land on a frame index one past a file's
    real last frame (final review I-3; see `last_frame_rgb`'s own docstring). A
    single "fade" check that only ever sampled t=0 could not see any of that.

    Each file's own fps is probed separately rather than shared: a profile that
    changed the rate would otherwise shift every frame number on one side only, and
    compare two different moments as if they were one. `d_fps` (the DELIVERED file's
    own rate) is also what sizes the fade-out's quantization slack in
    `lookcheck.evaluate` — passed through even when a fade is not declared, since it
    costs nothing to compute and `evaluate` itself only ever reads it when a fade end
    is declared.

    Titles do not share those samples. A title occupies a band and a window nothing
    else here does, so each gets its own in-window frame plus a pool of title-free
    witnesses — all gathered into ONE extra `frames_rgb` per file, which selects them
    in a single decode, so N titles do not cost N decodes.

    `flashes` are the shutter accent's cut times (design 2026-10-21 §4). The flash is
    in the delivered file and not in the master, so every sample this gate compares is
    kept out of every look.flash_windows span: an interior sample inside one moves to
    its end, and the titles' times avoid them (_title_times). The two bookend frames
    are not moved — t=0 is black under a declared fade-in, flash or not, and a flash
    deliver accepts ends a frame before the last. The flash itself is declared but not
    proven here (design §7).

    With nothing declared this makes no ffmpeg call at all, so a look-less delivery
    costs exactly what it cost before this gate existed.
    """
    vig = look.vignette if look is not None else 0.0
    fade = look.tail if look is not None else 0.0
    head = look.head if look is not None else 0.0
    if not (vig or fade or head or titles is not None):
        return []
    out_dur = assembly.probe_duration(out)
    m_si, d_si = assembly.probe_stream(master), assembly.probe_stream(out)
    m_fps, d_fps = m_si.fps, d_si.fps
    windows = look_lib.flash_windows(flashes, d_fps)
    ts = [look_lib.clear_of_flash(out_dur * f, windows) for f in (0.25, 0.5, 0.75)]
    first_m = first_d = last_m = last_d = None
    if head:
        first_m = assembly.frames_rgb(master, [0.0], m_fps)[0]
        first_d = assembly.frames_rgb(out, [0.0], d_fps)[0]
    if fade:
        last_m = assembly.last_frame_rgb(master, m_fps)
        last_d = assembly.last_frame_rgb(out, d_fps)
    probes: list[lookcheck.TitleProbe] = []
    if titles is not None:
        items = Titles.from_json(titles).items
        plan = [_title_times(items, i, out_dur, fade, head, windows=windows)
                for i in range(len(items))]
        extra = sorted({t for t_in, ws, why in plan if not why for t in (t_in, *ws)})
        m_extra = dict(zip(extra, assembly.frames_rgb(master, extra, m_fps))) if extra else {}
        d_extra = dict(zip(extra, assembly.frames_rgb(out, extra, d_fps))) if extra else {}
        for i, (t_in, ws, why) in enumerate(plan):
            probes.append(lookcheck.TitleProbe(
                # Indexed, because two titles may legitimately share their opening
                # line (a repeated caption) and a duplicated `check` name makes the
                # attestation unreadable — any consumer keying findings by name
                # silently keeps one of them.
                label=f"{i} {items[i].text.splitlines()[0][:24]}".strip(),
                band=_title_band(items[i], d_si.h, platform), skipped=why,
                inside=None if why else (m_extra[t_in], d_extra[t_in]),
                witnesses=() if why else tuple((m_extra[w], d_extra[w]) for w in ws)))
    return lookcheck.evaluate(assembly.frames_rgb(master, ts, m_fps),
                              assembly.frames_rgb(out, ts, d_fps),
                              first_m, first_d, last_m, last_d,
                              vignette=vig, fade=fade, fade_in=head, fps=d_fps,
                              titles=probes)


def deliver(master: str, profile: ExportProfile, out_dir: str, changelog: str,
            report: ReelReport, *, scratch_dir: str, audio: str | None = None,
            titles: str | None = None, platform: str = "",
            look: LookSpec | None = None, run_provenance: dict | None = None,
            flashes: Sequence[float] = ()) -> str:
    """Encode the checked master to the next REEL_v{n} and log the version. With
    `audio`, mux the pre-normalized aac stem alongside the encode (design §6).
    Hard gate: a failed reel is never shipped (no fix-forward, montage §176).
    The mux path assumes the audio stem's duration matches the master (build_reel
    derives mix's dur from the probed master); -shortest only absorbs sub-second
    jitter — a grossly short stem would truncate the picture, so callers must keep
    them aligned.

    `scratch_dir` receives the one-frame vignette mask and the per-title textfile
    sidecars. It is required and separate from `out_dir` because out_dir is the
    append-only deliveries bucket: writing scratch there is how look_mask.png and
    title_0_0.txt ended up beside the shipped reels (design 2026-08-26 §3).
    With `titles` (a TITLES.json path), burn the drawtext chain into this one encode
    (design §5.16) — no second pass. `platform` is the same safe-zone table key
    check_reel judges the PICTURE against; it must reach here too, or a bottom title
    is laid out against generic margins and lands under the app's chrome.

    `flashes` are the shutter accent's cut times on the master (design 2026-10-21 §4):
    a white flash on each, first in the chain so the titles sit over it and the
    bookend fade still darkens it. Placed at the master's probed fps; with none the
    argv is byte-for-byte what it was before the accent existed. The attestation
    lists them, since the delivered file differs from the master there on purpose.

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
    thresholds, the authored gates with their reasons, the episode QC state) into the
    `REEL_v{n}.attest.json` sidecar this writes.

    The encode lands on `.REEL_v{n}.part.{container}` and is os.replace()d onto its
    delivered name (design 2026-09-09 §5). Until that rename no file in the deliveries
    bucket bears a delivered name, so a killed encode — the 2026-06 run lost one to a
    Bash timeout — consumes no version and leaves the partial as the record that a
    delivery was interrupted. The look gate below stays AFTER the rename: its subject is
    a complete delivered file, and its deliberate behaviour on failure (the file stays,
    the attestation is withheld) is unchanged.

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
    # The two must be different directories, and this is a refusal rather than a
    # convention because `scratch_dir` being separate is the ONLY thing keeping
    # look_mask.png and the title_i.txt sidecars out of the append-only deliveries
    # bucket — and the caller that passes them (build_reel) had no test proving it
    # passed the right one: the final review measured that swapping it to out_dir
    # left the whole suite byte-identical (2026-08-27). A runtime refusal makes that
    # mutation raise wherever it happens, including from a caller nobody has written
    # yet.
    if Path(scratch_dir).resolve() == Path(out_dir).resolve():
        raise ValueError(
            f"deliver's scratch_dir and out_dir are the same directory ({out_dir}) — "
            f"out_dir is the append-only deliveries bucket, and the vignette mask and "
            f"per-title textfile sidecars would land beside the shipped reels, which is "
            f"exactly what the 2026-06 run did. Point scratch_dir at the reel's build/ "
            f"dir instead")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(scratch_dir).mkdir(parents=True, exist_ok=True)
    # Titles and the look share ONE video-filter slot (§5.16 + design 2026-08-13 §4):
    # build_filterchain writes each title's text to a title_i.txt sidecar in
    # scratch_dir and returns a drawtext chain; look.chain appends the bookend fade
    # AFTER it, so a title goes to black with the picture. ExportProfile.args() emits
    # no -vf/scale, so nothing clobbers this (last -vf wins in ffmpeg — the §12
    # silent-drop flavor).
    title_chain = ""
    if titles is not None:
        title_chain = build_filterchain(Titles.from_json(titles), scratch_dir, platform=platform)
    dur = (assembly.probe_duration(master)
           if (look is not None and look.has_fade) or flashes else 0.0)
    flash_chain: list[str] = []
    if flashes:
        fps = assembly.probe_stream(master).fps
        flash_chain = look_lib.flash_args(flashes, fps)
        # Its frames and the frame after them inside the reel: a flash placed later
        # renders partly or not at all, which nothing downstream would notice, and the
        # look gate's fade-out reads the last frame unmoved (_verify_look).
        late = [t for t in flashes if t + (look_lib.FLASH_FRAMES + 1) / fps > dur + 1e-6]
        if late:
            raise ValueError(
                f"a shutter flash at {late[0]:g}s needs {look_lib.FLASH_FRAMES} frames and "
                f"one after them before the {dur:g}s reel ends — the accented episode is "
                f"shorter than its flash; lengthen it, or drop its `shutter` in the EDL")
    parts = look_lib.chain(look, dur, title_chain, flashes=flash_chain)
    mask_in: list[str] = []
    graph: list[str] = []
    vmap: list[str] = []
    if look is not None and look.has_vignette:
        mask_in = ["-loop", "1", "-i", _render_mask(master, scratch_dir, look.vignette)]
        graph = ["-filter_complex",
                 ",".join(["[0:v][1:v]overlay=shortest=1", *parts]) + "[v]"]
        vmap = ["-map", "[v]"]
    elif parts:
        graph = ["-vf", ",".join(parts)]
    n = _next_version(out_dir, profile.container)
    out = str(Path(out_dir) / f"REEL_v{n}.{profile.container}")
    part = runlayout.partial_path(out_dir, n, profile.container)
    if audio is None:
        proc.run([ffbin.ffmpeg(), "-y", "-i", master, *mask_in, *graph, *vmap,
                  *profile.args(), str(part)])
    else:
        # mux the pre-normalized aac stem: profile audio settings don't apply — we
        # stream-copy to preserve the stem's −14 LUFS — so use video-only args + copy.
        # The stem's input index is 1 normally and 2 behind the mask: `-loop 1 -i mask`
        # occupies index 1, and mapping 1:a:0 there would look for an audio stream in
        # a PNG.
        aidx = 2 if mask_in else 1
        proc.run([ffbin.ffmpeg(), "-y", "-i", master, *mask_in, "-i", audio, *graph,
                  *_video_only_args(profile), *(vmap or ["-map", "0:v:0"]),
                  "-map", f"{aidx}:a:0", "-c:a", "copy", "-shortest", str(part)])
    # Atomic commit (design 2026-09-09 §5), the same shape intake_cache.store uses:
    # until this line no file bears a delivered name, so a process killed inside the
    # encode above leaves the partial and nothing else — no version consumed, no
    # truncated file reading as a delivery.
    os.replace(part, out)
    # The look gate (design 2026-08-15 §7). AFTER the encode, because the honest
    # subject is the file that shipped, not a prediction of it. On a failure the file
    # stays on disk — deleting output nobody asked to delete is worse than leaving the
    # evidence — but no attestation is written, which montage status already reports as
    # an unattested delivery. No waiver (governance #8).
    look_checks = _verify_look(master, out, look, titles, platform, flashes)
    bad = [f for f in look_checks if f.status == "fail"]
    if bad:
        raise RuntimeError(
            f"{Path(out).name} does not carry the look it declared: "
            + "; ".join(f"{f.check} — {f.detail}" for f in bad)
            + f". The file is on disk to look at, but no attestation was written, so "
              f"`montage status` reports it as unattested. Fix the look chain (EDL.look, "
              f"or the titles file) and deliver again — this gate has no waiver")
    _log_version(out_dir, n, changelog + _since_last(out_dir, n, profile.container,
                                                     run_provenance))
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
        gates=rp.get("gates") or [],
        episode_qc=rp.get("episode_qc") or {},
        look_checks=[f.to_dict() for f in look_checks],
        flashes=[round(float(t), 6) for t in flashes],
        delivered_at=datetime.now().isoformat(timespec="seconds"),
    ).write(provenance.attest_path(out))
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Deliver a checked reel master.")
    ap.add_argument("master", help="the checked reel master to deliver")
    ap.add_argument("--out-dir", required=True,
                    help="deliveries dir — append-only, nothing ever deletes it")
    ap.add_argument("--scratch-dir", required=True,
                    help="where the vignette mask and title sidecars go — NOT the "
                         "deliveries dir, which is append-only")
    ap.add_argument("--report", required=True, help="ReelReport JSON from check_reel")
    ap.add_argument("--changelog", default="",
                    help="one line recorded in the version log beside the delivery")
    ap.add_argument("--titles", default=None, help="TITLES.json — burn on-screen text into the encode (§5.16)")
    ap.add_argument("--platform", default="", help="safe-zone table key (reel/tiktok/shorts/…) — "
                                                   "where the app's chrome sits; titles lay out inside it")
    ap.add_argument("--vignette", type=float, default=0.0,
                    help="corner darkening 0..0.6 (0 = off) — the reel's plateau vignette")
    ap.add_argument("--fade", type=float, default=0.0,
                    help="closing fade seconds 0..2.0 (0 = off) — and the opening one, "
                         "unless --fade-in")
    ap.add_argument("--fade-in", type=float, default=None,
                    help="opening fade seconds 0..2.0 when it differs from --fade "
                         "(0 = the reel opens on picture)")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    report = ReelReport.from_dict(json.loads(Path(a.report).read_text()))
    out = deliver(a.master, ExportProfile(), a.out_dir, a.changelog, report,
                  scratch_dir=a.scratch_dir, titles=a.titles, platform=a.platform,
                  look=LookSpec(vignette=a.vignette, fade=a.fade, fade_in=a.fade_in))
    print(out)


if __name__ == "__main__":
    main()
