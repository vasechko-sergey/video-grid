"""Every libvidstab interaction in this repo (design 2026-07-20 §3).

Two consumers: intake measures shake per candidate window (§5.2), and
process_episode stabilizes a segment before tracking it (§1 of the same design —
stabilization CANNOT be a filter in reframe's chain, because the route is
measured on unstabilized pixels).

Extracted from intake.py, which held these as privates while it was the only
consumer — the same move scripts/lib/appearance.py made in the cast slice.
"""
import re
from pathlib import Path

from scripts.lib import ffbin, proc

# vidstabdetect over a whole raw clip is the one analysis in this repo whose
# input is unbounded raw footage; everything else works on 15-60s reels or
# extracted windows. A same-class motion-estimation proxy (mestimate=epzs)
# measured 13.6 fps analysing 4K/30 footage — ~2.2x realtime — and 4K/60 doubles
# the per-second frame count, so ~4.4x realtime is the worst measured case. 10x
# leaves > 2x headroom above that for slower hardware or larger frames.
SHAKE_TIMEOUT_REALTIME_MULTIPLE = 10.0

# The detect recipe, shared by BOTH consumers on purpose (design 2026-07-20 §5).
# intake used to detect at the binary's default shakiness=5 while the §10 recipe
# asked for 8; two different measurements would then have appeared under one word
# — "shake" in FOOTAGE.md and "before" in process_episode's result — with nothing
# saying they were incomparable. Changing this re-scales both.
#
# shakiness=8 is the only non-default here. The recipe's other detect option,
# accuracy=15, is the binary's own default (probed with `-h filter=vidstabdetect`),
# and spelling a default performs a choice that was never made. Nothing else in
# the recorded recipe belongs in this string: the transform pass has its own
# option namespace, and its knobs live in TRANSFORM_ARGS.
DETECT_ARGS = "shakiness=8"

_LM_RE = re.compile(r"\(LM\s+(-?\d+)\s+(-?\d+)")

_REMEDY = ("run `bash setup.sh`, which installs ffmpeg-full (libvidstab included) "
           "and records where it landed")


def require() -> None:
    """Fail loud unless the resolved ffmpeg carries BOTH vidstab filters.

    Both, not just detect: libvidstab supplies the pair, so checking one and
    using the other would let a strange build through to a mid-encode failure.
    Called at a consumer's ENTRY point, once per operation — `ffbin.has_filter`
    is uncached by design, so each call is a real `ffmpeg -filters` spawn.
    """
    ffbin.require_filter("vidstabdetect", _REMEDY)
    ffbin.require_filter("vidstabtransform", _REMEDY)


def read_trf(path: Path) -> str:
    """Decode a .trf, turning the binary-format case into the loud error the parser
    already meant to raise.

    parse_trf promises to fail loud on an unrecognized header rather than report a
    silent shake=0 — but it could never keep that promise against a binary file,
    because `Path.read_text()` raises UnicodeDecodeError several frames earlier,
    naming a byte offset instead of a remedy. Checking the magic on bytes first puts
    the intended error back within reach.
    """
    raw = path.read_bytes()
    if raw.startswith(b"TRF"):
        raise ValueError(
            f"vidstabdetect wrote a BINARY .trf (magic {raw[:4]!r}) — this parser reads "
            "the ASCII serializer. `fileformat=ascii` on the vidstabdetect call selects "
            "it; libvidstab's own default is binary")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(
            f"vidstabdetect .trf at {path} is neither UTF-8 text nor a known binary "
            "format — cannot trust the shake estimate. The detect pass wrote something "
            "this parser has no name for, which points at the library rather than the "
            f"footage: {_REMEDY}") from e


def parse_trf(text: str) -> list[float]:
    """Per-frame shake magnitude (median localmotion vector length, px) from a
    libvidstab VID.STAB transforms file. Fail loud on an unrecognized header —
    never a silent shake=0 (the format is libvidstab-version dependent)."""
    lines = text.splitlines()
    if not lines:
        raise ValueError("vidstabdetect produced an empty .trf (no transforms) — the analysis "
                         "failed; check the clip is readable")
    if not lines[0].startswith("VID.STAB"):
        raise ValueError("vidstabdetect .trf has an unrecognized header — libvidstab version mismatch? "
                         "cannot trust the shake estimate (run `bash setup.sh`)")
    mags: list[float] = []
    for line in lines[1:]:
        if not line.startswith("Frame"):
            continue
        lms = _LM_RE.findall(line)
        if lms:
            vecs = sorted((int(x) ** 2 + int(y) ** 2) ** 0.5 for x, y in lms)
            mags.append(vecs[len(vecs) // 2])          # upper-median localmotion magnitude
        else:
            mags.append(0.0)
    return mags


def _timeout(dur: float) -> float:
    return max(proc.DEFAULT_TIMEOUT_S, dur * SHAKE_TIMEOUT_REALTIME_MULTIPLE)


def detect(src: str, trf: str, dur: float) -> list[float]:
    """One vidstabdetect pass over `src` writing `trf` → per-frame magnitudes.

    `fileformat=ascii` is REQUIRED, not a preference: libvidstab defaults to a
    BINARY .trf (magic "TRF1") while parse_trf reads the ASCII serializer's
    "VID.STAB" text. Omitting it does not degrade gracefully — the read dies on
    the first non-UTF-8 byte. That was invisible until 2026-07-20, because no
    machine in this project carried libvidstab and the one covering test was
    skipped everywhere it ever ran.

    Does NOT call require(): the gate belongs at the entry points, so one caller
    does not pay three uncached `ffmpeg -filters` probes for one operation.
    """
    proc.run([ffbin.ffmpeg(), "-y", "-i", src, "-vf",
              f"vidstabdetect={DETECT_ARGS}:result={trf}:fileformat=ascii",
              "-f", "null", "-"], timeout=_timeout(dur))
    return parse_trf(read_trf(Path(trf)))


def mean_shake(mags: list[float], width: int) -> float:
    """Mean per-frame magnitude as a FRACTION OF FRAME WIDTH — the same unit
    FootageWindow.shake carries, so the two are directly comparable (design §5)."""
    if not mags:
        return 0.0
    return (sum(mags) / len(mags)) / (width or 1)
