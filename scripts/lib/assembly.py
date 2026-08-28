"""Normalize-and-concat core for reel assembly (design 2026-07-10 §3). Shared by
the final assembler and the draft assembler (scripts/draft.py)."""
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from scripts.lib import ffbin, proc


DELIVERY_RANGE = "tv"
"""The one colour range the reel is assembled and delivered in (limited, 16-235).

Not a style choice — h264/mp4's own default, what every player expands on the way
out, and what a downstream re-encode (a platform's own transcode) assumes when a
file says nothing. `pc` files are the ones that get misread, not the reverse."""


@dataclass(frozen=True)
class StreamInfo:
    w: int
    h: int
    fps: float
    pix_fmt: str
    vcodec: str                     # ffprobe codec_name, e.g. "h264" for libx264 output
    # ffprobe color_range, or "unknown" when the stream carries no tag. Defaults to
    # the delivery range so a hand-built StreamInfo describes a conforming stream;
    # probe_stream always passes what it actually read, and never guesses "tv".
    color_range: str = DELIVERY_RANGE


def probe_stream(path: str) -> StreamInfo:
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"{p} is missing — assemble needs every locked episode on disk; "
                           "check the EDL paths or re-run process-episode for it")
    cmd = [ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height,r_frame_rate,pix_fmt,codec_name,color_range",
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
                      s["pix_fmt"], s["codec_name"], s.get("color_range") or "unknown")


def probe_duration(path: str) -> float:
    """Container duration in seconds (format=duration). StreamInfo carries w/h/fps
    only; this is the shared duration probe (was extract._probe_dur)."""
    out = proc.run([ffbin.ffprobe(), "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nk=1:nw=1", path]).stdout.decode().strip()
    try:
        return float(out)
    except ValueError as e:
        raise ValueError(f"ffprobe returned no duration for {path!r} ({out!r}) — corrupt/streamed source?") from e


def matches(info: StreamInfo, dims: tuple[int, int], fps: float,
            pix_fmt: str = "yuv420p", vcodec: str = "h264",
            color_range: str = DELIVERY_RANGE) -> bool:
    """Is this episode already concat-compatible with the reel?

    color_range is in here because concat below is a `-c copy` — it splices
    BITSTREAMS and takes the stream tags from the first entry. Two episodes cut
    from differently-ranged cameras (a DJI ships yuv420p/tv, a Canon yuvj420p/pc)
    both "match" on dims/fps/codec, then the pc tag of whichever landed first is
    stamped on the tv one's 16-235 data. Nothing errors: that episode alone
    delivers with its blacks lifted ~15 and its whites capped ~13 low, a 12%
    contrast loss that reads as milky, blown foam, and a white point that visibly
    jumps at the cut into the next episode.

    An "unknown" range IS treated as a match: assemble() only ever consumes this
    pipeline's own locked episodes (reframe's encoder never passes -color_range),
    so an untagged stream here is always our own yuv420p output — limited-range by
    mp4/h264 convention, the same convention DELIVERY_RANGE names. The hazard this
    guards is a DIFFERENT explicit tag (a foreign "pc" among "tv", or vice versa) —
    that is the real -c copy tag-stamping landmine, and still gets normalized."""
    return (info.w == dims[0] and info.h == dims[1] and abs(info.fps - fps) < 0.01
            and info.pix_fmt == pix_fmt and info.vcodec == vcodec
            and info.color_range in (color_range, "unknown"))


def _normalize(src: str, dims: tuple[int, int], fps: float, out: str,
               color_range: str = DELIVERY_RANGE) -> str:
    # the landmine (§12): concat of non-uniform streams desyncs. Normalize the
    # outlier ONLY — matched episodes are copied untouched.
    # in_range=auto reads the source's own tag (and ffmpeg's yuvj⇒full default when
    # it has none), so this CONVERTS the samples rather than relabelling them;
    # -color_range then writes the matching tag. Both are spelled out because it
    # costs nothing, NOT because both are required — measured 2026-08-27
    # (segment-range-contract §4.1), either half alone converts byte-identically
    # once the output pix_fmt is yuv420p, and that pix_fmt is the individually
    # necessary member: without it nothing here converts at all.
    vf = (f"scale={dims[0]}:{dims[1]}:in_range=auto:out_range={color_range},"
          f"fps={fps},format=yuv420p")
    proc.run([ffbin.ffmpeg(), "-y", "-i", src, "-vf", vf, "-color_range", color_range,
              "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-an", out])
    return out


def _concat_quote(path: str) -> str:
    # ffmpeg concat demuxer: a literal ' inside a single-quoted path is written
    # '\'' (close quote, escaped quote, reopen). Without this a path with an
    # apostrophe (e.g. a client dir "O'Brien") mis-tokenizes into a misleading
    # "no such file", not a clean error.
    return path.replace("'", "'\\''")


def concat(entries: list[str], out_master: str) -> str:
    """Concat pre-uniform files losslessly (-c copy) via the concat demuxer. Writes
    the list file next to out_master, resolving + escaping each entry path. Shared by
    assemble() (final reel, after normalizing outliers) and the draft driver
    (scripts/draft.py, over already-burned segments)."""
    work = Path(out_master).parent
    work.mkdir(parents=True, exist_ok=True)
    listfile = work / "_concat.txt"
    listfile.write_text("".join(
        f"file '{_concat_quote(str(Path(p).resolve()))}'\n" for p in entries))
    proc.run([ffbin.ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
              "-c", "copy", out_master])
    return out_master


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
            entries.append(ep)
        else:
            norm = str(work / f"_norm_{i:03d}.mp4")
            _normalize(ep, dims, fps, norm)
            entries.append(norm)
    return concat(entries, out_master)


def make_proxy(src: str, dst: str, long_side: int = 960) -> bool:
    """Downscale `src` to an analysis proxy at `dst`: long side == `long_side`,
    native fps, no audio, analysis-grade CRF. Returns True if a proxy was written,
    False if `src`'s long side is already <= `long_side` (caller analyses the
    original — no upscaling, no needless re-encode). Downscale ONLY (design §8)."""
    info = probe_stream(src)
    if max(info.w, info.h) <= long_side:
        return False
    # long-side box, aspect preserved, even dims (yuv420p needs them)
    vf = (f"scale='if(gt(iw,ih),{long_side},-2)':'if(gt(iw,ih),-2,{long_side})'")
    proc.run([ffbin.ffmpeg(), "-y", "-i", src, "-an", "-vf", vf,
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
              "-pix_fmt", "yuv420p", dst])
    return True


_SELECT_CHUNK = 60   # max eq(n,N) terms per select pass. A single select expression
                     # ENOMEMs on a 4K decode above ~100 terms (measured: 81 ok, 106
                     # fails); 60 keeps margin for wider (5-digit) frame numbers. Cost
                     # is one decode per chunk of <= _SELECT_CHUNK frames — ceil(N/chunk)
                     # decodes for N unique frames (one decode for the common small-N
                     # case; not O(1) for every N — a >60-unique-frame request costs
                     # more than one decode, by design).


def frames_rgb(src: str, times: list[float], fps: float) -> list[np.ndarray]:
    """Every frame at `times` (seconds) as HxWx3 uint8 RGB arrays at `src`'s own
    resolution, decoding the clip once per chunk of up to _SELECT_CHUNK frames (one
    decode for the common small-N case, ceil(N/_SELECT_CHUNK) decodes for larger N —
    see _SELECT_CHUNK above). Frame number is round(t*fps); a select filter picks
    those exact frames per chunk, so this is the batched-decode replacement for
    per-grab output seeks (design 2026-08-02 §4/§8). Returns a list aligned to
    `times`: same order and length, duplicate times share one decoded frame. Empty
    `times` → [] with no ffmpeg call. Uses select, never -ss, so the §12 seek
    landmine cannot apply."""
    if not times:
        return []
    nums = [round(t * fps) for t in times]
    uniq = sorted(set(nums))
    by_num: dict[int, np.ndarray] = {}
    with tempfile.TemporaryDirectory() as d:
        for ci in range(0, len(uniq), _SELECT_CHUNK):
            chunk = uniq[ci:ci + _SELECT_CHUNK]
            expr = "+".join(rf"eq(n\,{n})" for n in chunk)
            sub = Path(d) / f"c{ci:05d}"
            sub.mkdir()
            proc.run([ffbin.ffmpeg(), "-y", "-i", src, "-vf", f"select='{expr}'",
                      "-vsync", "0", "-frames:v", str(len(chunk)),
                      str(sub / "f%05d.png")])
            pngs = sorted(sub.glob("f*.png"))
            if len(pngs) != len(chunk):
                raise RuntimeError(
                    f"frames_rgb: chunk requested {len(chunk)} frames {chunk} but ffmpeg "
                    f"emitted {len(pngs)} — a frame number is past the stream end (a time "
                    f">= duration). times={times}")
            for n, p in zip(chunk, pngs):
                by_num[n] = np.asarray(Image.open(p).convert("RGB"))
    return [by_num[n] for n in nums]


def frame_rgb(src: str, t: float) -> np.ndarray:
    """One frame at time `t` as an HxWx3 uint8 RGB ndarray, at `src`'s own
    resolution — a single-frame convenience over frames_rgb (probes fps to place the
    frame). For many frames call frames_rgb directly: it decodes once (design
    2026-08-02 §4). For re-extracting cast crops from the ORIGINAL (design §5)."""
    return frames_rgb(src, [t], probe_stream(src).fps)[0]


# Seconds of safety margin scanned backward from the estimated last frame before
# giving up, for last_frame_rgb below. Covers duration-probe slop against the true
# encoded frame count — measured: a `-shortest`-muxed delivery's own probe_duration
# can overstate its last frame's index by at least one frame (video stream 2.966667s
# against a probed 3.0s container duration at 30fps — `round(dur*fps)` landed on a
# frame that does not exist). A full second of margin absorbs any plausible
# duration/frame-count disagreement (encoder padding, mux truncation, float slop)
# while still decoding only a handful of frames, never the whole file.
_LAST_FRAME_MARGIN_S = 1.0


def last_frame_rgb(src: str, fps: float) -> np.ndarray:
    """The file's TRUE last decodable frame, as an HxWx3 uint8 RGB ndarray.

    NOT `frames_rgb(src, [probe_duration(src) - 1/fps], fps)`: the container
    duration `probe_duration` reads does not always agree with the frame count the
    stream actually encoded, and asking `select` for a frame index one past the real
    end raises rather than returning the one right before it (design
    2026-08-15 §7, amended — final review I-3).

    Selects every frame from `_LAST_FRAME_MARGIN_S` seconds before the estimated
    last-frame index onward (`gte`, not `eq`) and keeps whichever ffmpeg actually
    emits last, so an over-estimated index still lands on the real last frame
    instead of raising, and an under-estimated one only costs a few extra decoded
    frames — never a full decode of the file, and no `-ss` (§12).
    """
    dur = probe_duration(src)
    est = max(0, round(dur * fps) - 1)
    start = max(0, est - round(_LAST_FRAME_MARGIN_S * fps))
    with tempfile.TemporaryDirectory() as d:
        sub = Path(d)
        proc.run([ffbin.ffmpeg(), "-y", "-i", src, "-vf", rf"select='gte(n\,{start})'",
                  "-vsync", "0", str(sub / "f%05d.png")])
        pngs = sorted(sub.glob("f*.png"))
        if not pngs:
            raise RuntimeError(
                f"last_frame_rgb: no frame at or after estimated index {start} in "
                f"{src} ({dur:.3f}s at {fps:.4g}fps) — the file may be empty, or "
                f"shorter than probe_duration reported")
        return np.asarray(Image.open(pngs[-1]).convert("RGB"))
