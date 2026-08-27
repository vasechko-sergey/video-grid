"""Cut an EDL window into a standalone fragment (spec §5.8, §12)."""
import argparse
from pathlib import Path

from scripts.lib import assembly, ffbin, proc, ramp
from scripts.lib.assembly import probe_duration as _probe_dur   # keep the local name its callers use
from scripts.lib.edl import EDL
from scripts.lib.models import RampSpec

_LEN_EPS = 0.05    # seconds of slack beyond one frame — a re-encoded window lands ±1 frame


def extract(src: str, start: float, dur: float, out: str, crf: int = 18) -> str:
    # output-seek (-ss after -i) + re-encode → frame-accurate, no black frames.
    # Audio is PRESERVED (spec §5.8): segments are the ambient bed for audio-mix;
    # sources without an audio stream simply produce video-only segments.
    cmd = [
        ffbin.ffmpeg(), "-y", "-i", src,
        "-ss", f"{start}", "-t", f"{dur}",
        # The segment is the pipeline's canonical form and its range is part of
        # that contract (design 2026-08-27 §2). `-pix_fmt yuv420p` alone READS as
        # a normalization and is not one: measured, libx264 keeps full range for
        # a full-range input, so a Canon window — 67 of the 99 clips this was
        # designed against — shipped `yuvj420p`/pc the whole way into reframe's
        # lutyuv, whose TV_LO/TV_SPAN are written for 16..235.
        # in_range=auto reads the source's own tag (and ffmpeg's yuvj=>full
        # default when it has none), so this CONVERTS the samples; -color_range
        # writes the matching tag. Both halves are needed, and it is the same
        # pair assembly._normalize already uses at concat — moved to where it can
        # still save the grade instead of arriving after it.
        # The scale carries NO dimensions: resolution stays native because
        # reframe crops from native pixels (design §3). Measured byte-identical
        # on untagged, tv-tagged and 10-bit sources, so no golden moves.
        "-vf", "scale=in_range=auto:out_range=tv", "-color_range", "tv",
        "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out,
    ]
    proc.run(cmd)
    return out


def extract_edl(edl: EDL, footage_root: str, seg_dir: str) -> list[str]:
    """Cut every EDL window into seg_dir/ep{i}_raw.mp4 (reel order). Gate (§5.8):
    each segment's probed duration matches its window within one frame, else raise
    — a short segment is the silent-truncation class (design §12)."""
    Path(seg_dir).mkdir(parents=True, exist_ok=True)
    segments: list[str] = []
    for i, ep in enumerate(edl.episodes):
        src = str(Path(footage_root) / ep.source)
        if not Path(src).exists():
            raise ValueError(f"EDL episode {i} source not found: {src!r} "
                             f"(footage_root={footage_root!r} + source={ep.source!r})")
        out = str(Path(seg_dir) / f"ep{i}_raw.mp4")
        extract(src, ep.start, ep.dur, out)
        probed, fps = _probe_dur(out), assembly.probe_stream(out).fps
        if probed + 1.0 / fps + _LEN_EPS < ep.dur:
            raise ValueError(
                f"EDL episode {i} segment is {probed:.3f}s — shorter than its {ep.dur}s window "
                f"(source {src!r} start={ep.start}); the window runs past the clip. Trim the window "
                "or fix the in-point.")
        if ep.ramp is not None:
            # A PRE-STAGE writing a file, exactly like vidstab.stabilize and for
            # the same reason (design §4): the route must be measured on the
            # pixels that ship. A route tracked on un-retimed time and applied to
            # retimed pixels would place the crop at the wrong moment, and
            # check_episode would confirm the framing — path and route would
            # agree with each other while only the pixels disagreed.
            #
            # It replaces ep{i}_raw.mp4 IN PLACE because draft.py and the reel
            # manifest built by preflight both reference that exact name; a ramp
            # written beside it would simply be ignored, leaving reframe the
            # un-ramped cut.
            ramped = str(Path(seg_dir) / f"ep{i}_ramped.mp4")
            ramp.retime(out, ramped, RampSpec.from_dict(ep.ramp), ep.dur, fps)
            Path(ramped).replace(out)
        segments.append(out)
    return segments


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--dur", type=float, required=True)
    a = ap.parse_args()
    extract(a.src, a.start, a.dur, a.out)
