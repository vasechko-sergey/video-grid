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


def probe_duration(path: str) -> float:
    """Container duration in seconds (format=duration). StreamInfo carries w/h/fps
    only; this is the shared duration probe (was extract._probe_dur)."""
    out = proc.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nk=1:nw=1", path]).stdout.decode().strip()
    try:
        return float(out)
    except ValueError as e:
        raise ValueError(f"ffprobe returned no duration for {path!r} ({out!r}) — corrupt/streamed source?") from e


def matches(info: StreamInfo, dims: tuple[int, int], fps: float,
            pix_fmt: str = "yuv420p", vcodec: str = "h264") -> bool:
    return (info.w == dims[0] and info.h == dims[1] and abs(info.fps - fps) < 0.01
            and info.pix_fmt == pix_fmt and info.vcodec == vcodec)


def _normalize(src: str, dims: tuple[int, int], fps: float, out: str) -> str:
    # the landmine (§12): concat of non-uniform streams desyncs. Normalize the
    # outlier ONLY — matched episodes are copied untouched.
    vf = f"scale={dims[0]}:{dims[1]},fps={fps},format=yuv420p"
    proc.run(["ffmpeg", "-y", "-i", src, "-vf", vf,
              "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-an", out])
    return out


def _concat_quote(path: str) -> str:
    # ffmpeg concat demuxer: a literal ' inside a single-quoted path is written
    # '\'' (close quote, escaped quote, reopen). Without this a path with an
    # apostrophe (e.g. a client dir "O'Brien") mis-tokenizes into a misleading
    # "no such file", not a clean error.
    return path.replace("'", "'\\''")


def assemble(episodes: list[str], dims: tuple[int, int], fps: float, out_master: str) -> str:
    """Concat locked episodes into one silent master. Reference = the caller's
    intended (dims, fps) — the same delivery process-episode rendered to. All
    match → lossless -c copy; an outlier is normalized alone, then copy-concat."""
    if len(episodes) < 1:
        raise RuntimeError("assemble needs >= 1 locked episode, got none — the EDL "
                           "produced no episodes for this reel")
    work = Path(out_master).parent
    work.mkdir(parents=True, exist_ok=True)
    entries: list[str] = []
    for i, ep in enumerate(episodes):
        info = probe_stream(ep)
        if matches(info, dims, fps):
            entries.append(str(Path(ep).resolve()))
        else:
            norm = str(work / f"_norm_{i:03d}.mp4")
            _normalize(ep, dims, fps, norm)
            entries.append(str(Path(norm).resolve()))
    listfile = work / "_concat.txt"
    listfile.write_text("".join(f"file '{_concat_quote(p)}'\n" for p in entries))
    proc.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
              "-c", "copy", out_master])
    return out_master
