"""Every libvidstab interaction in this repo (design 2026-07-20 §3).

Two consumers: intake measures shake per candidate window (§5.2), and
process_episode stabilizes a segment before tracking it (§1 of the same design —
stabilization CANNOT be a filter in reframe's chain, because the route is
measured on unstabilized pixels).

Extracted from intake.py, which held these as privates while it was the only
consumer — the same move scripts/lib/appearance.py made in the cast slice.
"""
import re
import tempfile
from pathlib import Path

from scripts.lib import assembly, ffbin, proc

# vidstabdetect's cost scales with pixel count AND shakiness's search window. On
# raw 4K/60 at shakiness=8 it is ~0.009x realtime — ~67 min for a 35 s clip
# (measured 2026-08-01; the earlier mestimate=epzs estimate of 2.2-4.4x was wrong by
# ~25x). intake therefore runs detect on a 960-long-side analysis PROXY, not the raw
# 4K (design 2026-08-01-intake-analysis-proxy): the shake fraction is preserved above
# the pixel-quantization floor (measured ratio 1.008, r 0.985 near the 0.02 gate),
# and the same 35 s clip drops to ~13 s. stabilize()'s detect still runs on the
# ORIGINAL short extracted segment.
#
# The 10x multiple is the timeout headroom over realtime (ample for the ~0.37x proxy
# pass, generous for stabilize's short segment). The floor in _timeout keeps both at
# proc's already-generous default when the input is short.
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

# The transform recipe (design 2026-07-20 §4). smoothing=40 and zoom=2 come from
# the session's proven recipe (design spec §10); crop=keep is stated explicitly
# even though it is the binary's default, because §10 says the opposite and a
# decision documented nowhere is a decision waiting to be reverted.
#
# crop=black is refused: it fills the uncovered border with black, and under a
# fill layout the crop takes the source's full height, so that band lands in the
# delivered frame whole. check_episode's black gate compares frame MEDIANS and a
# few percent of the frame does not move a median, so nothing would catch it.
# crop=keep fills from the previous frame instead — the failure class stops
# existing rather than being detected (§4.1).
TRANSFORM_ARGS = "smoothing=40:zoom=2:crop=keep"

# unsharp counters the softening from vidstabtransform's bilinear interpolation
# (design spec §10, proven on real footage). It is the one parameter whose
# POSITION changed relative to where it was proven — there it shared a chain with
# the crop at delivery scale, here it runs on an intermediate that a crop and a
# scale then consume (§4.3).
SHARPEN = "unsharp=5:5:0.4"

# The intermediate is consumed twice (YOLO, then reframe) and thrown away, and
# reframe re-encodes at 18 with deliver encoding again after that. At 18 this
# would spend a generation nothing can recover; 12 is visually lossless at a size
# that is irrelevant for a 1.2-4.0s window (§4.2).
INTERMEDIATE_CRF = "12"

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

    Does NOT call require(): the gate belongs at the entry points, so a caller
    running several passes pays it once rather than once per pass.
    """
    proc.run([ffbin.ffmpeg(), "-y", "-i", src, "-vf",
              f"vidstabdetect={DETECT_ARGS}:result={trf}:fileformat=ascii",
              "-f", "null", "-"], timeout=_timeout(dur))
    return parse_trf(read_trf(Path(trf)))


def mean_shake(mags: list[float], width: int) -> float:
    """Mean per-frame magnitude as a FRACTION OF FRAME WIDTH — the same unit
    FootageWindow.shake carries, so the two are directly comparable (design §5).

    A non-positive width is refused rather than defended against. It is not a
    degenerate-but-valid frame; it means the probe that produced it failed.
    Substituting 1 would not yield a wrong magnitude, it would yield a different
    UNIT — raw pixels wearing the name "fraction of frame width" — which then
    meets intake.SHAKY_CLIP (0.02), saturates every window's stability term to
    zero and culls footage that was never shaky. FootageClip already rejects a
    res with a zero side, so the silent substitution was this module disagreeing
    with the contract its own output feeds.
    """
    if width <= 0:
        raise ValueError(
            f"frame width is {width} — shake cannot be expressed as a fraction of it. "
            "The width comes from assembly.probe_stream's `width` field (intake passes "
            "res[0]); a non-positive one means ffprobe reported no usable video "
            "geometry for the clip, so re-probe it or re-render it")
    # Checked AFTER the width, on purpose: an empty magnitude list is a legitimate
    # input (a window whose frame slice is empty), a broken width never is, and the
    # broken width is worth reporting even when there are no magnitudes to scale.
    if not mags:
        return 0.0
    return (sum(mags) / len(mags)) / width


def stabilize(src: str, out: str, dims: tuple[int, int], fps: float,
              dur: float) -> tuple[float, float]:
    """Two-pass stabilization of `src` into `out`, plus a third pass that measures
    the residual; returns (before, after) shake as fractions of frame width.

    A PRE-STAGE, not a filter in reframe's chain, and the distinction is the whole
    point (design 2026-07-20 §1): the route is measured on unstabilized pixels, so
    a crop placed from it against transformed pixels leaves the subject offset by
    exactly the shake vidstab removed — a steady background with a jittering
    subject. check_episode would not catch it either, because path and route are
    both in source coordinates and agree with each other; only the pixels disagree.
    Writing a file that BOTH track and reframe read makes route and pixels one
    coordinate system by construction.

    `dims`/`fps`/`dur` are the caller's already-probed numbers, not re-probed here.
    They are what the layout resolution computed with, so handing them in states
    the belief the geometry guard below then proves still holds. dims[0] is also
    the width the returned fractions are normalised by.

    The residual is a MEASUREMENT, not a gate. It proves stabilization ran and did
    something; it does not prove it should have. In particular it does NOT catch
    the wade-in landmine (design spec §12) — "rolling ground" is a warp, and a
    successfully flattened wade shot reports a LOW residual (§7).

    `after` is comparable to `before` (identical recipe both sides, which is the
    comparison this slice rests on) but NOT to FootageWindow.shake's SHAKY_CLIP
    (0.02), even though §5 gave it that unit and that name on purpose. Pass 3 runs
    shakiness=8's wide search over near-motionless frames, where the extra
    candidate displacements find spurious minima in weak or repetitive texture;
    and on any frame whose displacement outran zoom=2, crop=keep's border fill
    leaves a seam between moving and frozen content that no single displacement
    fits. parse_trf's per-frame median suppresses a minority of such fields, not
    all of them, so the floor sits above zero — a successful stabilization does
    not report after ≈ 0, and reading one against SHAKY_CLIP would call it shaky.
    """
    require()
    with tempfile.TemporaryDirectory() as d:
        # one local, read by both the detect call and the transform's filtergraph:
        # spelling the path twice would let a rename leave the transform reading a
        # .trf nothing wrote.
        in_trf = str(Path(d) / "in.trf")
        before = mean_shake(detect(src, in_trf, dur), dims[0])
        proc.run([ffbin.ffmpeg(), "-y", "-i", src, "-vf",
                  f"vidstabtransform=input={in_trf}:{TRANSFORM_ARGS},{SHARPEN}",
                  "-c:v", "libx264", "-crf", INTERMEDIATE_CRF, "-preset", "medium",
                  "-an", out], timeout=_timeout(dur))
        _assert_geometry_held(out, dims, fps, dur)
        after = mean_shake(detect(out, str(Path(d) / "out.trf"), dur), dims[0])
    return before, after


def _assert_geometry_held(out: str, dims: tuple[int, int], fps: float, dur: float) -> None:
    """vidstabtransform preserves width/height/fps/duration — `zoom` is internal to
    the transform and the output frame is the input frame's size. But "preserves"
    is a promise from a library, and if it were ever false the caller's layout
    numbers would be stale while everything downstream kept computing with them.

    Uses assembly's probes rather than reframe._probe: scripts.reframe imports from
    scripts.lib, so reaching back for it would close an import cycle.
    """
    info = assembly.probe_stream(out)
    # indexed, and the 0.01 fps epsilon, both exactly as assembly.matches spells
    # the same comparison one module over.
    if info.w != dims[0] or info.h != dims[1] or abs(info.fps - fps) > 0.01:
        raise ValueError(
            f"vidstabtransform changed the geometry: asked to preserve {dims} @ {fps:.4g}fps, "
            f"{out} is {(info.w, info.h)} @ {info.fps:.4g}fps — the layout was already "
            "resolved against the original numbers, so every crop below this is stale. "
            "Re-check the vidstabtransform options (zoom must not resize the frame)")
    got = assembly.probe_duration(out)
    tol = 2.0 / fps          # two frames: a re-encode may shift the container slightly
    if abs(got - dur) > tol:
        raise ValueError(
            f"vidstabtransform changed the duration: expected {dur:.4f}s (±{tol:.4f}s, two "
            f"frames), {out} is {got:.4f}s — the episode's target_dur and the reel's length "
            "gate both key on the original. Re-check the vidstabtransform options and confirm "
            "the source segment's own duration; if the source is short, re-extract it rather "
            "than widening this tolerance")
