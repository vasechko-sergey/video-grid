"""Normalize-and-concat core for reel assembly (design 2026-07-10 §3). Shared by
the final assembler and, later, the draft assembler."""
import json
from dataclasses import dataclass
from pathlib import Path

from scripts.lib import proc


@dataclass(frozen=True)
class StreamInfo:
    w: int
    h: int
    fps: float
    pix_fmt: str
    vcodec: str                     # ffprobe codec_name, e.g. "h264" for libx264 output


def probe_stream(path: str) -> StreamInfo:
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"{p} is missing — assemble needs every locked episode on disk; "
                           "check the EDL paths or re-run process-episode for it")
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height,r_frame_rate,pix_fmt,codec_name",
           "-of", "json", str(p)]
    out = proc.run(cmd).stdout.decode("utf-8", errors="replace")
    streams = json.loads(out).get("streams", [])
    if not streams:
        raise RuntimeError(f"{p} has no video stream — assemble cannot place it in the reel")
    s = streams[0]
    num, den = s["r_frame_rate"].split("/")
    if float(den) == 0:
        raise RuntimeError(f"{p} reports r_frame_rate {s['r_frame_rate']!r} — unusable, re-render it")
    return StreamInfo(int(s["width"]), int(s["height"]), float(num) / float(den),
                      s["pix_fmt"], s["codec_name"])


def matches(info: StreamInfo, dims: tuple[int, int], fps: float,
            pix_fmt: str = "yuv420p", vcodec: str = "h264") -> bool:
    return (info.w == dims[0] and info.h == dims[1] and abs(info.fps - fps) < 0.01
            and info.pix_fmt == pix_fmt and info.vcodec == vcodec)
