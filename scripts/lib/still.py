"""A photo as pixels, a subject and a moving frame (design
docs/specs/2026-10-20-photos-design.md).

load()    the one decoder — intake, the contact sheet and extract all call it — so the
          three cannot disagree about which way up a photo is or what colour it has.
people()  one YOLO pass on the still; subject() the box a move aims at.
render()  a planned move (lib/kenburns) warped in float and streamed into one x264
          encode on the video segment's contract (§4).
"""
import datetime as dt
import io
import math
import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pi_heif
from PIL import Image, ImageCms, ImageOps

from scripts.lib import ffbin, proc
from scripts.lib.kenburns import Rect

pi_heif.register_heif_opener()      # once, at import: HEIC/HEIF open through Pillow

MAX_LONG_SIDE = 4096     # a 9:16 crop of a capped 4:3 photo is 2304x4096, 2.1x a 1080 delivery
SUBJECT_KEEP = 0.25      # a person box this fraction of the largest one's area joins the
                         # subject; smaller is a background figure. A convention (§6).
DETECT_IMGSZ = 960       # the inference size track.py and intake use
MAX_DENSITY = 2.0        # source pixels per output pixel a frame is warped from at most;
                         # past it the renderer drops to a half-size level (render)
_SRGB = ImageCms.createProfile("sRGB")
EXIF_IFD = 0x8769                    # the EXIF sub-IFD the capture-time tags live in
DATE_ORIGINAL = 0x9003               # DateTimeOriginal, "YYYY:MM:DD HH:MM:SS"
SUBSEC_ORIGINAL = 0x9291             # SubSecTimeOriginal, the fraction's digits
OFFSET_ORIGINAL = 0x9011             # OffsetTimeOriginal, "+HH:MM"
_OFFSET = re.compile(r"([+-])(\d{2}):(\d{2})")


@dataclass(frozen=True)
class Still:
    rgb: np.ndarray      # (h, w, 3) uint8, upright, sRGB
    record: dict         # what decoding changed, for the segment's sidecar

    @property
    def dims(self) -> tuple[int, int]:
        h, w = self.rgb.shape[:2]
        return w, h


def load(path: str | Path) -> Still:
    """Decode a photo upright, in 8-bit sRGB, with the long side capped (design §1).

    Orientation: a JPEG/PNG carries it as the EXIF tag, applied here. A HEIF (told by
    its decoder, never by its file name) carries it
    as the irot/imir properties, which libheif applies while decoding, and pi_heif then
    resets the EXIF tag to 1 (measured on a rotated HEIC) — so the tag is never applied
    a second time. An embedded ICC profile is converted to sRGB; none reads as sRGB. The
    decoders return the primary image: an HDR photo's SDR base, at 8 bits.
    """
    p = Path(path)
    try:
        im = Image.open(p)
        im.load()
    except (OSError, ValueError) as e:
        raise ValueError(f"{p.name}: not a photo this engine can decode — {e}") from e
    with im:
        # the DECODER, not the name: a JPEG saved as .heic still carries an EXIF tag
        # that nothing else will apply
        heif = im.format == "HEIF"
        rec: dict = {"decoder": im.format, "source_dims": list(im.size)}
        icc = im.info.get("icc_profile")
        exif = im.getexif()                # pi_heif hands a HEIF's EXIF to Pillow the same way
        taken = _taken(exif)
        if taken is not None:
            rec["taken"] = taken
        if heif:
            rec["orientation"] = ("heif transforms, applied by libheif "
                                  f"(EXIF tag was {im.info.get('original_orientation')})")
            up = im
        else:
            rec["orientation"] = int(exif.get(0x0112, 1))
            up = ImageOps.exif_transpose(im)
        mode = up.mode
        if mode.startswith("I;16"):
            # Pillow's convert() CLIPS a 16-bit value at 255 rather than scaling it, so a
            # 16-bit grey PNG came back almost white (the 2026-10-20 review's I4)
            up = Image.fromarray((np.asarray(up, dtype=np.uint16) >> 8).astype(np.uint8), "L")
            rec["mode"] = f"{mode} scaled to 8 bits"
        elif mode in ("I", "F"):
            raise ValueError(f"{p.name}: a {'32-bit integer' if mode == 'I' else 'floating-point'} "
                             f"image, whose value range this engine cannot know — re-export "
                             f"it as an 8-bit JPEG or PNG")
        elif mode in ("LA", "La"):
            rec["mode"] = f"{mode} read as L"          # the alpha is dropped
            up = up.convert("L")
        elif mode not in ("RGB", "L", "CMYK"):
            rec["mode"] = f"{mode} read as RGB"        # RGBA/P/… — any alpha is dropped
            up = up.convert("RGB")
        w, h = up.size
        if max(w, h) > MAX_LONG_SIDE:
            k = MAX_LONG_SIDE / max(w, h)
            up = up.resize((max(1, round(w * k)), max(1, round(h * k))),
                           Image.Resampling.LANCZOS)
            rec["scaled_to_long_side"] = MAX_LONG_SIDE
        if icc:
            try:
                prof = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                rec["icc"] = ImageCms.getProfileDescription(prof).strip()
                # the profile's own colour space decides the input mode: a monochrome
                # HEIC decodes to RGB beside a grey profile, a grey PNG with an RGB one
                want = {"GRAY": "L", "RGB": "RGB"}.get(prof.profile.xcolor_space.strip())
                if want and up.mode in ("L", "RGB") and up.mode != want:
                    up = up.convert(want)
                up = ImageCms.profileToProfile(
                    up, prof, _SRGB, renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                    outputMode="RGB")
            except (ImageCms.PyCMSError, OSError) as e:
                raise ValueError(
                    f"{p.name}: its embedded colour profile cannot be applied to its "
                    f"pixels ({e}) — re-export the photo as an sRGB JPEG") from e
        else:
            rec["icc"] = None                          # read as sRGB, the web default
            up = up.convert("RGB")
        rgb = np.ascontiguousarray(np.asarray(up, dtype=np.uint8))
    rec["dims"] = [int(rgb.shape[1]), int(rgb.shape[0])]
    return Still(rgb=rgb, record=rec)


def _taken(exif: Image.Exif) -> float | None:
    """When the photo was taken, in seconds since the epoch, or None when it carries no
    capture time that parses (design 2026-10-21 §5). Absence is not a failure: a
    screenshot or an exported PNG has none, and grouping then rests on the pHash alone.

    No OffsetTimeOriginal reads as UTC. Only DIFFERENCES between photos are used, and
    inside one camera those are right whatever its zone; across two cameras with
    different clocks they are not (§7). An unparseable sub-second or offset is dropped
    rather than taking the date with it."""
    ifd = exif.get_ifd(EXIF_IFD) or {}    # a corrupt IFD pointer comes back as None
    date = ifd.get(DATE_ORIGINAL)
    if not isinstance(date, str):
        return None
    try:
        t = dt.datetime.strptime(date.strip("\x00 "), "%Y:%m:%d %H:%M:%S")
    except ValueError:                    # "0000:00:00 00:00:00" is a camera's "unset"
        return None
    tz = dt.timezone.utc
    m = _OFFSET.fullmatch(str(ifd.get(OFFSET_ORIGINAL, "")).strip("\x00 "))
    if m and int(m[2]) < 24 and int(m[3]) < 60:
        sign = 1 if m[1] == "+" else -1
        tz = dt.timezone(sign * dt.timedelta(hours=int(m[2]), minutes=int(m[3])))
    sub = str(ifd.get(SUBSEC_ORIGINAL, "")).strip("\x00 ")
    frac = float("0." + sub) if sub.isascii() and sub.isdigit() else 0.0
    try:
        return t.replace(tzinfo=tz).timestamp() + frac
    except (OverflowError, OSError, ValueError):   # a year the platform clock cannot hold
        return None


def people(rgb: np.ndarray, model_path: str) -> list[tuple[float, float, float, float]]:
    """Person boxes (cx, cy, w, h) in raster pixels, largest first: one YOLO predict at
    the inference size the tracker uses. A model is loaded per call — ultralytics'
    predictor is not safe to share across intake's worker threads."""
    from ultralytics import YOLO          # lazy import: heavy optional dep (ultralytics/torch)
    res = YOLO(model_path).predict(Image.fromarray(rgb), classes=[0], imgsz=DETECT_IMGSZ,
                                   verbose=False)
    boxes = [tuple(float(v) for v in b.xywh[0])
             for r in res if getattr(r, "boxes", None) is not None for b in r.boxes]
    return sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)


def subject(boxes: list[tuple[float, float, float, float]],
            keep: float = SUBJECT_KEEP) -> Rect | None:
    """The union of the person boxes at least `keep` of the largest one's area — a
    couple framed together, a stranger in the back left out. None when nobody is there."""
    if not boxes:
        return None
    big = max(w * h for _, _, w, h in boxes)
    kept = [b for b in boxes if b[2] * b[3] >= keep * big]
    x0 = min(cx - w / 2 for cx, _, w, _ in kept)
    y0 = min(cy - h / 2 for _, cy, _, h in kept)
    x1 = max(cx + w / 2 for cx, _, w, _ in kept)
    y1 = max(cy + h / 2 for _, cy, _, h in kept)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def render(still: Still, frames: list[Rect], out_dims: tuple[int, int], rate: str,
           out: str, *, timescale: int | None = None) -> dict:
    """Encode `frames` (photo-pixel rects, one per output frame) into `out`.

    The raster is pre-scaled once with INTER_AREA so the TIGHTEST frame lands at 1:1 —
    the pre-scale never throws away detail the tightest frame could show — and the
    widest frame samples at wide/tight, under 1.1 for the default move. A frame past
    MAX_DENSITY takes a half-size level instead. Each frame is then one float affine
    warp, so the frame moves by fractions of a pixel instead of zoompan's whole ones.

    The encode is the video segment's contract (design §4): yuv420p, tv range, SAR 1:1,
    RGB→YUV through BT.709, and all four colour tags stamped on the FRAMES by
    `setparams`. Measured on ffmpeg 8.1.2: `-color_primaries`/`-color_trc` given as
    output options never reach the file, and an untagged segment is the silent trap —
    ffmpeg decodes it as BT.601 and agrees with itself, while a player reading an
    untagged HD stream as BT.709 shifts its saturated colours by 21 codes.
    """
    W, H = out_dims
    sw, sh = still.dims
    tight = min(r.w for r in frames)
    f = min(1.0, W / tight)
    base = still.rgb
    if f < 1.0:
        base = cv2.resize(base, (max(1, round(sw * f)), max(1, round(sh * f))),
                          interpolation=cv2.INTER_AREA)
    levels = [base]

    def level(k: int) -> np.ndarray:
        while len(levels) <= k:
            lv = levels[-1]
            levels.append(cv2.resize(lv, (max(1, lv.shape[1] // 2), max(1, lv.shape[0] // 2)),
                                     interpolation=cv2.INTER_AREA))
        return levels[k]

    def warp(src: np.ndarray, r: Rect) -> np.ndarray:
        fx, fy = src.shape[1] / sw, src.shape[0] / sh
        ax, ay = r.w * fx / W, r.h * fy / H
        m = np.array([[ax, 0.0, r.x * fx + 0.5 * ax - 0.5],
                      [0.0, ay, r.y * fy + 0.5 * ay - 0.5]], dtype=np.float64)
        return cv2.warpAffine(src, m, (W, H), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP,
                              borderMode=cv2.BORDER_REPLICATE)

    def frame(r: Rect) -> np.ndarray:
        """Past MAX_DENSITY source pixels per output pixel a cubic warp does no area
        filtering and shimmers, so the frame is drawn from half-size levels — blended
        between the two around its density (a mipmap's trilinear step), because a hard
        switch read as a jump in sharpness between two frames (the re-review measured
        Laplacian variance 719 -> 2269 across one switch)."""
        lod = math.log2(r.w * base.shape[1] / sw / W / MAX_DENSITY)
        if lod <= 0:
            return warp(base, r)
        k, frac = int(lod), lod - int(lod)
        a = warp(level(k), r)
        if frac < 1e-3:
            return a
        b = warp(level(k + 1), r)
        return cv2.addWeighted(a, 1.0 - frac, b, frac, 0.0)

    def chunks():
        for r in frames:
            yield frame(r).tobytes()

    cmd = [ffbin.ffmpeg(), "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-framerate", rate,
           "-i", "-",
           "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setsar=1,"
                  "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv",
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-color_range", "tv",
           *(["-video_track_timescale", str(timescale)] if timescale else []),
           "-an", out]
    proc.feed(cmd, chunks())
    return {"prescale": round(f, 4), "upscale": round(W / tight, 3), "levels": len(levels)}
