"""Soft normalize-to-middle color (spec §10). lutrgb is banned; use mixer."""

import re

TARGET = (105, 122, 137)   # R, G, B middle tone
STRENGTH = 0.55
LO, HI = 0.7, 1.5


def gain(measured: float, target: float, strength: float = STRENGTH,
         lo: float = LO, hi: float = HI) -> float:
    if measured <= 0:
        raise ValueError(
            f"channel mean {measured} is not positive — all-black frames? "
            "check the extracted segment (blackdetect) before color normalization")
    g = 1 + strength * (target / measured - 1)
    return max(lo, min(hi, g))


def gains_for_means(measured: tuple[float, ...],
                    target: tuple[float, ...] = TARGET) -> tuple[float, ...]:
    return tuple(gain(m, t) for m, t in zip(measured, target))


def mixer_arg(rr: float, gg: float, bb: float) -> str:
    return f"colorchannelmixer=rr={rr:.3f}:gg={gg:.3f}:bb={bb:.3f}"


BLACK_POINT_MAX = 0.35     # past this the toe eats real shadow detail, not just a lifted floor


def black_point_arg(black: float) -> str:
    """A `colorlevels` fragment that subtracts a lifted black floor, or "" for 0.

    The grade above is a pure MULTIPLY, and a multiply cannot move a black floor:
    it maps `black` to `gain * black`, so a camera that records its toe at 26% grey
    stays washed out at every gain the clamps allow. Measured on this repo's drone
    footage — DJI's flat profile put the darkest 1% at 65.7/255 against 23.1 on the
    telephoto beside it, and matching that by gain alone would have needed 0.30,
    three times past the LO clamp and crushing the whole picture rather than its toe.

    `colorlevels` remaps [black, 1] onto [0, 1], which is the operation that actually
    exists for this: it moves the floor and leaves the white point alone. It runs
    BEFORE the mixer, so the gain that follows is solved against the corrected image —
    the two compose in the one order that makes the mean land where it was asked to.
    """
    # type FIRST: bool is a subclass of int and True == 1, so an early `== 0` shortcut
    # would let `black_point: false` through as "no correction" and `true` through as a
    # full-range subtraction — a JSON typo becoming a silent grade either way.
    if isinstance(black, bool) or not isinstance(black, (int, float)):
        raise ValueError(f"black_point must be a number in [0, {BLACK_POINT_MAX}], got {black!r}")
    if black == 0:
        return ""
    if not 0 <= black <= BLACK_POINT_MAX:
        raise ValueError(
            f"black_point {black} is outside [0, {BLACK_POINT_MAX}] — it is the fraction of "
            "the range subtracted from the toe, and past this it clips real shadow detail "
            "instead of a lifted floor. Measure the source's darkest 1% first")
    return f"colorlevels=rimin={black:.4f}:gimin={black:.4f}:bimin={black:.4f},"


HIGHLIGHT_KNEE = 0.55      # where the shoulder starts; below it the curve is left alone
HIGHLIGHT_MIN = 0.6        # past this the picture reads as fogged, not as tamed highlights


def highlight_arg(white: float, knee: float = HIGHLIGHT_KNEE) -> str:
    """A `curves` shoulder pulling the white end down to `white`, or "" for 1.0.

    The twin of black_point_arg, at the other end and for the same reason: a gain
    SCALES the top, it cannot bend it. Measured here, a drone's sunlit foam sits at
    253/255 in the source while the telephoto beside it tops out at 154, and the gain
    that lands the two on one mean drives 7% of the drone's red channel past 255 —
    so the brightest foam not only blows, it loses red first and shifts cold. Scaling
    that down linearly would need x0.79 across the whole frame, which is a different
    picture, not a tamed one.

    The knee is 0.55 and not higher because ffmpeg's `curves` fits a SPLINE through the
    control points: with a knee at 0.70 the curve bulges ABOVE the identity line below
    it and the mean comes out HIGHER than it went in (measured 113.2 -> 117.5), which
    is the opposite of what a highlight shoulder is asked to do. At 0.55 the same
    three points leave the mean within 1.5% (113.2 -> 111.5) while the clipping goes
    to zero.
    """
    # type FIRST — see black_point_arg: True == 1.0, so the identity shortcut would
    # swallow a boolean instead of refusing it.
    if isinstance(white, bool) or not isinstance(white, (int, float)):
        raise ValueError(f"highlight must be a number in [{HIGHLIGHT_MIN}, 1.0], got {white!r}")
    if white == 1.0:
        return ""
    if not HIGHLIGHT_MIN <= white <= 1.0:
        raise ValueError(
            f"highlight {white} is outside [{HIGHLIGHT_MIN}, 1.0] — it is the output level "
            "white is pulled down to, and past this the whole picture reads as fogged "
            "rather than as highlights brought back under control")
    return f",curves=all='0/0 {knee}/{knee} 1/{white:.4f}'"


SATURATION_MIN = 0.5       # below this the picture is visibly draining toward grey
SATURATION_MAX = 1.5       # above this a rebalanced cast comes back as neon


def saturation_arg(sat: float) -> str:
    """An `eq` chroma scale, or "" for 1.0. Hue-preserving: it scales the distance
    from grey, it does not rotate it.

    The gain (colorchannelmixer) can neutralize a CAST — match one camera's white
    balance to another's — but it cannot lower overall saturation, because deepening
    the black point to lift contrast (which the same grade does) STRETCHES chroma back
    out. On this reel the drone reads as more vivid than the telephoto beside it even
    after its white balance is matched: an aerial frame is mostly blue sky and green
    water, saturated by the medium, not the grade. This is the one knob that pulls the
    two together without touching hue — `eq=saturation` works in YUV and scales U/V
    about neutral, so a blue stays blue, just less insistent.
    """
    # type FIRST — see black_point_arg: True == 1.0 would slip the identity shortcut.
    if isinstance(sat, bool) or not isinstance(sat, (int, float)):
        raise ValueError(f"saturation must be a number in [{SATURATION_MIN}, {SATURATION_MAX}], got {sat!r}")
    if sat == 1.0:
        return ""
    if not SATURATION_MIN <= sat <= SATURATION_MAX:
        raise ValueError(
            f"saturation {sat} is outside [{SATURATION_MIN}, {SATURATION_MAX}] — it scales "
            "chroma about neutral; past this the image drains to grey or blooms to neon. "
            "Measure the colourfulness gap against the reference shot first")
    return f",eq=saturation={sat:.4f}"


SHADOW_RED_MAX = 0.20      # past this the toe goes visibly pink instead of neutral
SHADOW_RED_RETURN = 0.25   # where the lift has decayed to nothing (64/255)
SHADOW_RED_STEP = 0.05     # identity anchors above the return point. 0.05, not the twin's
                           # 0.1: measured 2026-08-15, 0.1 still leaves -2 codes at the
                           # shipped return point and -3 at the domain's worst; 0.05 leaves 0
                           # at the shipped return point, up to 2 across the domain (ret step
                           # 0.01, design 2026-08-15 Fix 1 — the 0.05-ret-step grid this first
                           # shipped on did not sample every `ret`)
SHADOW_RED_FMT_EPS = 5e-5  # half the anchors' .4f write quantum (1e-4 / 2) — the loop below
                           # must clear the EMITTED precision, not float precision. At 1e-9,
                           # an anchor within one write-quantum of 1.0 formatted to "1.0000"
                           # and duplicated the appended 1.0 point; ffmpeg's curves parser
                           # refuses two identical control points outright (exit 234)


def shadow_red_arg(lift: float, ret: float = SHADOW_RED_RETURN) -> str:
    """A red-channel `curves` that lifts ONLY the toe, or "" for 0.

    Two cameras that agree everywhere else can still disagree in the blacks. Measured
    on this reel: the telephoto's neoprene sits at R-G +0.3 (neutral black) while the
    drone's sits at -17.0 — its red is simply not there in the shadows, so a black
    wetsuit reads green-cyan. The eye is unforgiving about this precisely because it
    KNOWS the reference: black is supposed to be colourless.

    Why not the gain or the black point. `colorchannelmixer` multiplies, so lifting the
    toe's red enough to matter also warms the midtones — measured, it pushed skin from
    +46.8 to +47.4 and the board with it. `colorlevels` romin adds a constant that
    decays across the WHOLE range, which is the same problem, softer. Only a curve can
    put the correction where the fault is and be back to identity before skin starts.

    The anchors above `ret` are load-bearing, not decoration: ffmpeg fits a spline, and
    with the segment from `ret` to 1.0 unpinned it SAGS — measured, a red board lost 7
    units of R-G from a curve that never meant to touch it. They used to be three hardcoded
    points (0.50/0.70/0.85), which pinned the spline AT three points and not the curve it draws
    BETWEEN them — the same defect `highlight_red_arg` fixed on 2026-08-13, cited there and
    left standing here. Probed losslessly through a 256-step ramp (reframe.verify_tone's
    method), 2026-08-15: at the shipped ret=0.25 those three anchors left **-6** codes at
    SHADOW_RED_MAX, worst at code 79 (x~0.31) — in the gap immediately after the return
    point — and up to -14 across the legal (lift, ret) domain. Stepping SHADOW_RED_STEP from
    `ret` instead measures **exactly identity** at the shipped ret for every legal lift. On
    the ret-step-0.05 grid this was first measured on that also read as "at most one code
    anywhere legal"; re-measured at ret step 0.01 (design 2026-08-15 Fix 1) the true worst is
    **2** codes, at ret=0.04/lift=0.03 and ret=0.11/lift=0.10 — `ret` values the coarser grid
    never sampled.

    Why 0.05 when the twin steps 0.1: this curve returns from a lift to identity over a range
    of `ret` rather than easing across a wide shoulder, so its kink is steeper and 0.1 still
    leaves -2 codes where it ships. The divergence is deliberate — do not "fix" it back. At
    ret step 0.01 (design 2026-08-15 Fix 1) the cost is **15** single-code non-monotone cells,
    not three — the three first named are exactly the subset whose `ret` lands on the coarser
    0.05-step grid — spanning ret 0.13-0.23, up to **0.03** away from `lift` (not "within
    0.02"), where the toe's slope is already near zero; that is 8-bit rounding on a flat
    region, and the shipped ret has none of them (design 2026-08-15 §1.4/§6).
    """
    # type FIRST — see black_point_arg: True == 1 would slip the identity shortcut.
    if isinstance(lift, bool) or not isinstance(lift, (int, float)):
        raise ValueError(f"shadow_red must be a number in [0, {SHADOW_RED_MAX}], got {lift!r}")
    if lift == 0:
        return ""
    if not 0 <= lift <= SHADOW_RED_MAX:
        raise ValueError(
            f"shadow_red {lift} is outside [0, {SHADOW_RED_MAX}] — it is how far the red toe "
            "is lifted at black, and past this the shadows read pink rather than neutral. "
            "Measure the neoprene's R-G against the reference camera first")
    if not 0 < ret <= 0.45:
        raise ValueError(f"shadow_red return point {ret} must be in (0, 0.45] — past that the "
                         "lift reaches skin, which is the thing it exists to leave alone")
    if lift >= ret:
        raise ValueError(
            f"shadow_red {lift} inverts the toe against a return point of {ret} — the toe "
            f"maps x -> x + lift*(1 - x/ret), whose slope is 1 - lift/ret, so at lift >= ret "
            f"the curve stops rising and the shadows band. Lower the lift below the return "
            f"point, or move the return point above the lift")
    # linear decay from `lift` at black to nothing at `ret`, then identity
    xs = [i * ret / 3 for i in range(4)]
    pts = [f"{x:.4f}/{x + lift * max(0.0, 1 - x / ret):.4f}" for x in xs]
    # identity anchors every SHADOW_RED_STEP from `ret` to 1.0, derived from `ret` rather
    # than hardcoded, so a non-default return point gets a dense region too.
    hi_xs = []
    i = 1
    while ret + i * SHADOW_RED_STEP < 1.0 - SHADOW_RED_FMT_EPS:
        hi_xs.append(ret + i * SHADOW_RED_STEP)
        i += 1
    hi_xs.append(1.0)
    pts += [f"{x:.4f}/{x:.4f}" for x in hi_xs]
    return f",curves=r='{' '.join(pts)}'"


TONE_ANCHORS = 3           # toe, level, shoulder — p5 / p50 / p95 of luma
TONE_MIN_GAP = 6.0         # 0-255 units two anchors must differ by to stay orderable
TONE_TOP_SLOPE = 0.35      # how the curve continues ABOVE the shoulder anchor: gentle
                           # enough to compress specular foam, steep enough that the top
                           # 5% keeps its ordering instead of collapsing onto a ceiling
# The Y plane's range, MEASURED (design 2026-08-19 §3): black encodes to 16 and white
# to 235 through this repo's own yuv420p h264, while color_measure's `format=gray` path
# reads the same two as 0 and 255. `curves` never had to know — it works in RGB, so
# swscale converted both ways for free and invisibly. lutyuv writes the plane as stored,
# so the conversion is ours at both ends, or every anchor lands somewhere else with
# nothing failing. Pinned by tests against a real encode, not against these literals.
TV_LO, TV_SPAN = 16.0, 219.0

_DEPTH_SUFFIX = re.compile(r"(\d+)(le|be)$")


def plane_depth(pix_fmt: str) -> int:
    """Bits per sample carried by an ffmpeg pixel-format name.

    Read from the NAME, deliberately. ffprobe also reports `bits_per_raw_sample`
    and it is not trustworthy here: measured 2026-08-27 against the footage this
    slice was designed on, the one real 10-bit clip in the pool
    (`DJI_20260625083848_0548_D.MP4`, HEVC) reports `N/A` for that field while
    its `pix_fmt` says `yuv420p10le` — the exact file the guard exists to catch
    is the file that field cannot describe.

    An 8-bit format carries no depth marker at all (`yuv420p`, `yuvj420p`,
    `nv12`, `gray`), so the ABSENCE of one is eight bits, not an unknown.
    """
    m = _DEPTH_SUFFIX.search(pix_fmt)
    return int(m.group(1)) if m else 8


def refuse_ungradeable_plane(pix_fmt: str, color_range: str, src: str) -> None:
    """Refuse pixels this module's colour maths cannot read (design §4.3).

    TV_LO/TV_SPAN are constants of BOTH bit depth and range — together they say
    "the stored luma plane runs 16..235 in eight bits" — and every knob in
    grade_chain is written against that plane. Neither half is negotiable, and
    each fails SILENTLY when violated:

      * wrong range: measured, a full-range source lands 8.5 luma codes from the
        target it was given, against a MATCH_EPS of 4.0;
      * wrong depth: measured on a real 10-bit clip, tone_arg returns a plane
        with 99.26% of its pixels pinned to a single code.
      * unknown depth: an absent pix_fmt reads as 8 through plane_depth, which is
        the right answer for a NAME with no depth marker and the wrong one for no
        name at all — measured 2026-09-21 against a container this build has no
        decoder for (design §0.2).

    Only these two properties. Codec and resolution are nobody's assumption here,
    and refusing on them would block legitimate hand runs for no reason.

    An "unknown" range PASSES: untagged is the mp4/h264 convention for limited
    and assembly.matches already reads it that way. A full-range file that lost
    its tag is therefore still misread — a known gap, design §7, not an oversight.
    """
    if not pix_fmt:
        raise ValueError(
            f"{src}: ffprobe reported no pix_fmt for this stream, so its bit depth "
            f"is unknown — and an unknown depth reads as 8 through plane_depth, "
            f"which answers 8 for a NAME carrying no depth marker (yuv420p, nv12, "
            f"gray). An absent name is not such a name. A container whose codec "
            f"this ffmpeg build cannot open still reports width, height, frame rate "
            f"and duration from its own boxes, so the other four probed values look "
            f"healthy while this one is missing. Cut this source through "
            f"scripts.extract first: it re-encodes to 8-bit yuv420p at the source's "
            f"own resolution.")
    depth = plane_depth(pix_fmt)
    if depth != 8:
        raise ValueError(
            f"{src}: pixel format {pix_fmt} carries {depth} bits per sample, and this "
            f"pipeline's colour maths is written for 8 (TV_LO={TV_LO:.0f}, "
            f"TV_SPAN={TV_SPAN:.0f} describe an 8-bit limited luma plane). Rendering it "
            f"anyway does not shift the picture, it destroys it — measured on a real "
            f"10-bit clip, 99% of the pixels come back on one code. Cut this source "
            f"through scripts.extract first: it re-encodes to 8-bit yuv420p at the "
            f"source's own resolution.")
    if color_range == "pc":
        raise ValueError(
            f"{src}: color_range is pc (full, 0-255) and this pipeline's colour maths "
            f"is written for tv (limited, {TV_LO:.0f}-{TV_LO + TV_SPAN:.0f}). The grade "
            f"would be evaluated at the wrong place on its own curve, and everything "
            f"above code {TV_LO + TV_SPAN:.0f} would collapse onto one value — measured, "
            f"8.5 luma codes off target against a MATCH_EPS of 4.0, with nothing "
            f"failing. Cut this source through scripts.extract first: it normalizes "
            f"the range.")


def _segments(src: tuple[float, float, float],
              dst: tuple[float, float, float]) -> list[tuple[float, float]]:
    """The (in, out) knots of the tone map, in FULL-range luma.

    Its own function because two readers need exactly these: the expression tone_arg
    emits, and the proof that renders a ramp through it and compares against _lerp
    over the same points.

    The top endpoint is COMPUTED, not pinned to 255, and that is the whole trick.
    Pinning it would force the segment above the shoulder anchor to climb from dst_p95
    back to 255 — on the reel this was measured against, 221->148 followed by 255->255
    is a slope of 3.1, so the brightest foam would be EXPANDED by the very filter asked
    to tame it. Continuing the shoulder at a gentle fixed slope keeps the map monotone
    (highlights stay separable, no plate) while spending little range on it."""
    top = min(255.0, dst[2] + (255.0 - src[2]) * TONE_TOP_SLOPE)
    return [(0.0, 0.0), *zip(src, dst), (255.0, top)]


def tone_arg(src: tuple[float, float, float], dst: tuple[float, float, float]) -> str:
    """A luma-transfer fragment carrying one source's tone profile onto a common one.

    This is the stage black_point_arg and highlight_arg could not reach BETWEEN them,
    and the reason is a small piece of algebra: a black subtraction followed by a gain
    is an AFFINE map, and the shape of a histogram — where the median sits between toe
    and shoulder, measured as (p50-p5)/(p95-p5) — is invariant under affine maps. So no
    combination of those two knobs can move it. Measured on this reel: the DJI's flat
    profile sits at 0.27 and the Canon beside it at 0.48-0.58, and that difference is
    exactly what reads as "the drone glares" — the drone frame is mostly dark water with
    a small blazing patch, while the camera's is evenly weighted. Only a non-linear
    transfer can carry one to the other.

    The three anchors are the three things a profile IS: p5 is the toe (where black
    lands), p50 the exposure, p95 the shoulder (where highlights land). Mapping each
    onto the reel's common target normalizes all three at once, in one filter, with
    nothing left to fight: the old pair had the gain solving for a mean while the
    shoulder moved that same mean, so each correction partly undid the other.

    The caller measures `src` on the episode's OWN crop (the pixels that ship, not the
    full frame), because a crop centred on a rider has a different histogram from the
    frame around it.
    """
    for name, v in (("src", src), ("dst", dst)):
        if len(v) != TONE_ANCHORS or any(
                isinstance(x, bool) or not isinstance(x, (int, float)) for x in v):
            raise ValueError(f"tone {name} must be {TONE_ANCHORS} numbers (p5, p50, p95) "
                             f"in 0-255, got {v!r}")
        if not all(0 <= x <= 255 for x in v):
            raise ValueError(f"tone {name} anchors must lie in 0-255, got {v!r}")
        # strictly increasing with room between: curves needs ordered control points,
        # and two anchors that collapse together make a vertical segment the spline
        # answers with a wild overshoot rather than an error.
        if not all(b - a >= TONE_MIN_GAP for a, b in zip(v, v[1:])):
            raise ValueError(f"tone {name} anchors must increase by at least "
                             f"{TONE_MIN_GAP} units each, got {v!r} — measure p5/p50/p95 "
                             "of luma on the episode's own crop")
    # A LUT, not a spline. `curves` fits a natural cubic through whatever points it is
    # given, which is why this used to emit a TONE_SAMPLES grid, join the anchors to
    # that grid, and keep a minimum gap so two control points never nearly coincided
    # (ffmpeg answers that with no frame at all, not an error). lutyuv evaluates the
    # expression once per input code and stores a table, so the four segments ARE the
    # map: measured against _lerp over all 256 codes, worst deviation 0.98 codes —
    # integer rounding, nothing else — and monotone (design 2026-08-19 §2.3).
    #
    # And it is LUMA-only, which is the point: U and V are never written, so chroma
    # comes out bit-identical and the transfer finally acts on the same statistic the
    # target is measured in (§2.1/§2.2).
    v = f"(val-{TV_LO})*255/{TV_SPAN}"
    segs = _segments(src, dst)
    # ABOVE the top knot the map CONTINUES at the shoulder's own slope instead of
    # flattening onto a constant. Measured 2026-08-27 through the per-code ramp
    # harness: the constant put every stored code 236..255 onto ONE output (202)
    # — twenty codes to one, which is exactly the plate TONE_TOP_SLOPE's own
    # docstring exists to prevent — while continuing the slope spreads them over
    # 202..209 and leaves 200..235 untouched (14 distinct codes either way).
    # Bounded without clipping in every legal case: the largest `v` a stored code
    # can produce is (255-16)*255/219 = 278.3, `top` is at most 255 and this
    # slope at most TONE_TOP_SLOPE = 0.35 by construction of _segments, so the
    # extended output tops out at 242 — thirteen codes below the ceiling.
    # A zero-width final segment (p95 == 255) has no shoulder to continue and
    # keeps the constant, which is what "the map ends here" means.
    (xt0, yt0), (xt1, yt1) = segs[-2], segs[-1]
    expr = (f"{yt1:.4f}" if xt1 == xt0 else
            f"({yt1:.4f}+({v}-{xt1:.4f})*{(yt1 - yt0) / (xt1 - xt0):.6f})")
    for (x0, y0), (x1, y1) in reversed(list(zip(segs, segs[1:]))):
        # x1 == x0 happens when p5 is 0: the origin and the toe anchor coincide, and
        # the segment between them has no width to interpolate across. Its output is
        # the anchor's, which is what a zero-width segment means.
        piece = (f"{y1:.4f}" if x1 == x0 else
                 f"({y0:.4f}+({v}-{x0:.4f})*{(y1 - y0) / (x1 - x0):.6f})")
        expr = f"if(lte({v},{x1:.4f}),{piece},{expr})"
    return f"lutyuv=y='{TV_LO}+({expr})*{TV_SPAN}/255',"


def _lerp(knots: list[tuple[float, float]], x: float) -> float:
    """Piecewise-linear interpolation through sorted (in, out) knots, CONTINUING
    the final segment's slope above the last knot.

    No production caller since 2026-08-19, and kept deliberately: it is the tone
    map's reference definition, and tone_arg's emitted expression is a SECOND,
    independent implementation of the same arithmetic. The real-ffmpeg proof
    renders through one and compares against the other, which is only a proof
    because they are not the same code — a shared bug would cancel. Do not
    "simplify" by having tone_arg call this, and do not factor the extrapolation
    below into a helper both call: that is the same mistake wearing a hat.
    """
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    (x0, y0), (x1, y1) = knots[-2], knots[-1]
    if x1 == x0:
        return y1
    return y1 + (x - x1) * (y1 - y0) / (x1 - x0)


MID_BLUE_MIN = 0.80        # below this the midtones go visibly yellow, not just un-blued
MID_BLUE_MAX = 1.20
MID_BLUE_BAND = (0.45, 0.65)     # the midtone window skin sits in on this footage
MID_BLUE_PINS = (0.25, 0.85)     # identity below and above it — shadows and foam stay put


def mid_blue_arg(scale: float) -> str:
    """A blue-channel `curves` that scales ONLY the midtones, or "" for 1.0.

    The twin of shadow_red_arg, at the other end of the picture and for a different
    physical cause: sky bounce. Measured on this reel, the drone frames one rider with
    green a full 10 units above blue in his skin (warm, matching the telephoto) and the
    other with green and blue EQUAL — his skin reads grey-pink. It is not the camera and
    not the grade: shot from above, he catches more reflected sky than she does, and the
    telephoto shooting side-on catches none of it. Blue rides up into the skin midtones
    and the warmth drains out.

    Why the band and the pins. Blue must come down where skin lives and nowhere else:
    below MID_BLUE_PINS[0] are the shadows this reel has already neutralized with
    shadow_red, and above MID_BLUE_PINS[1] is white foam, which turns yellow the moment
    its blue is touched. Pinning both ends to identity keeps the correction inside the
    window — measured, foam moved 0.4 units of R-B while skin moved 10.

    The cost is the sky, which shares the band and comes out less blue (measured, B-R
    73 -> 64). That is a deliberate trade on this reel: the sky is the one reference
    nobody looks at, and skin is the one everybody does.
    """
    # type FIRST — see black_point_arg: True == 1.0 would slip the identity shortcut.
    if isinstance(scale, bool) or not isinstance(scale, (int, float)):
        raise ValueError(f"mid_blue must be a number in [{MID_BLUE_MIN}, {MID_BLUE_MAX}], got {scale!r}")
    if scale == 1.0:
        return ""
    if not MID_BLUE_MIN <= scale <= MID_BLUE_MAX:
        raise ValueError(
            f"mid_blue {scale} is outside [{MID_BLUE_MIN}, {MID_BLUE_MAX}] — it scales blue in "
            "the midtones, and past this the skin goes yellow rather than merely un-blued. "
            "Measure the skin's G-B against the reference camera first")
    lo, hi = MID_BLUE_PINS
    a, b = MID_BLUE_BAND
    pts = ["0/0", f"{lo}/{lo}", f"{a}/{a * scale:.4f}", f"{b}/{b * scale:.4f}", f"{hi}/{hi}", "1/1"]
    return f",curves=b='{' '.join(pts)}'"


DIP_MAX = 0.5              # a longer dip stops reading as a transition and starts reading as a gap
DIP_COLOR = "0x141414"     # dark grey, NOT black — see below


def dip_arg(dip: float, dur: float) -> str:
    """Fade an episode in from — and out to — a dark grey, or "" for 0.

    A transition that costs no time. Unlike a crossfade, which overlaps two episodes and
    therefore SHORTENS the reel, this lives entirely inside one episode: the cut stays
    where it was, so beat alignment, title timings and the whole layout are untouched,
    and the assembler needs no changes at all.

    The colour is dark grey and not black because check_reel's own `black` gate would
    otherwise fail the reel. It runs blackdetect at d=0.05:pic_th=0.98, and a 0.2s fade
    to true black measured 0.067s over that threshold (a 0.15s fade still measured
    0.050s — exactly on it). Fading to 0x141414 reads as the same dip to the eye and
    leaves the detector silent, which is the difference between a transition and a
    reprocess loop.
    """
    if isinstance(dip, bool) or not isinstance(dip, (int, float)):
        raise ValueError(f"dip must be a number in [0, {DIP_MAX}] seconds, got {dip!r}")
    if dip == 0:
        return ""
    if not 0 < dip <= DIP_MAX:
        raise ValueError(f"dip {dip} is outside (0, {DIP_MAX}] seconds — past this the pause "
                         "reads as a gap in the reel rather than a transition between shots")
    if dur <= 2 * dip:
        raise ValueError(f"dip {dip}s twice over does not fit a {dur:.3f}s episode — the fade in "
                         "and the fade out would overlap and the shot would never be fully visible")
    return (f",fade=t=in:st=0:d={dip:.3f}:color={DIP_COLOR}"
            f",fade=t=out:st={dur - dip:.3f}:d={dip:.3f}:color={DIP_COLOR}")


def white_balance_gains(means: tuple[float, ...], strength: float,
                        lo: float = LO, hi: float = HI) -> tuple[float, ...]:
    """Grey-world neutral gains: pull each channel mean toward the common average
    (true neutral) at `strength`, clamped to [lo, hi]. neutral = mean(means);
    g = clamp(1 + strength*(neutral/m - 1), lo, hi). strength 0 → (1, 1, 1).
    Unlike gains_for_means (which targets the fixed cool middle 105/122/137), this
    equalizes the channels — the "bring it to neutral first" white balance."""
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not 0 <= strength <= 1:
        raise ValueError(f"white_balance strength must be a number in [0, 1], got {strength!r}")
    if any(m <= 0 for m in means):
        raise ValueError(f"white_balance means must be positive, got {means!r} — all-black frames?")
    neutral = sum(means) / len(means)
    return tuple(max(lo, min(hi, 1 + strength * (neutral / m - 1))) for m in means)


def white_balance_arg(means: tuple[float, ...], strength: float) -> str:
    """A LEADING colorchannelmixer that neutralizes the source cast, or "" at strength 0.
    "" (not an identity mixer) so the fill fast path stays byte-identical when WB is off."""
    if isinstance(strength, bool) or not isinstance(strength, (int, float)):
        raise ValueError(f"white_balance strength must be a number in [0, 1], got {strength!r}")
    if strength == 0:
        return ""
    return mixer_arg(*white_balance_gains(means, strength)) + ","


HIGHLIGHT_RED_MAX = 0.35     # past this the whites lose their body and read cyan, not just de-pinked
HIGHLIGHT_RED_KNEE = 0.60    # identity at/below this — the pull acts only on the shoulder (specular
                             # foam), so a red board and skin (both below it) keep their red


def highlight_red_arg(pull: float, knee: float = HIGHLIGHT_RED_KNEE) -> str:
    """A red-channel `curves` that pulls ONLY the shoulder down, or "" for 0.

    The mirror of shadow_red_arg at the other end. A bright coloured object — a red
    surfboard — throws its hue into the white spray it kicks up, so foam that should be
    neutral reads PINK, and only in the highlights where the reflection lives. A global
    red cut (the mixer) would cool the water and cyan the sky with it; this leaves
    everything below `knee` (water, skin, the board itself) untouched and bends only the
    specular top back toward neutral.

    Anchors below `knee` step every 0.1 up to and including it — not the three points
    (0, knee/2, knee) this shipped with originally, which do NOT pin the CUBIC SPLINE
    ffmpeg fits BETWEEN them: pinning three points pins the spline AT three points, not
    the curve it draws in between (shadow_red_arg cites the same lesson and, measured
    2026-08-13, turns out to have the identical sparseness — unfixed here, pre-existing,
    queued separately). Probed losslessly through a 256-step ramp (reframe.verify_tone's
    method): with three anchors, pull=0.3 sagged the sub-knee region by up to +7/-3
    codes; densified, the same probe measures at most +1/-1. At HIGHLIGHT_RED_MAX=0.35
    it is +2/-1. Not zero — a natural cubic spline through evenly-spaced collinear
    points still curves infinitesimally between them — but confined to the bottom
    couple of bits, and monotone throughout at the knee this ships with."""
    if isinstance(pull, bool) or not isinstance(pull, (int, float)):
        raise ValueError(f"highlight_red must be a number in [0, {HIGHLIGHT_RED_MAX}], got {pull!r}")
    if pull == 0:
        return ""
    if not 0 <= pull <= HIGHLIGHT_RED_MAX:
        raise ValueError(
            f"highlight_red {pull} is outside [0, {HIGHLIGHT_RED_MAX}] — it is how far the red "
            "shoulder is pulled at white, and past this the foam reads cyan rather than neutral. "
            "Measure the foam's R-B against a white reference first")
    if not 0.3 <= knee <= 0.9:
        raise ValueError(f"highlight_red knee {knee} must be in [0.3, 0.9] — below it the pull "
                         "reaches skin/board, above it there is no shoulder left to correct")
    # dense identity anchors below the knee, not three sparse ones — see the docstring's
    # measured sag. Derived from `knee` (a step of 0.1 up to and including it) rather
    # than a hardcoded list, so a caller passing a non-default knee still gets a dense
    # sub-knee region instead of silently falling back to the old three-point sparsity.
    lo_xs = []
    i = 0
    while i * 0.1 < knee - 1e-9:
        lo_xs.append(i * 0.1)
        i += 1
    lo_xs.append(knee)
    lo = [f"{x:.4f}/{x:.4f}" for x in lo_xs]
    xs = [knee + (1 - knee) * i / 3 for i in range(1, 4)]                   # ..., 1.0
    hi = [f"{x:.4f}/{x - pull * (x - knee) / (1 - knee):.4f}" for x in xs]  # linear pull to 1-pull
    return f",curves=r='{' '.join(lo + hi)}'"


def grade_chain(gains: tuple[float, ...], *, wb: str = "", tone: str = "",
                black_point: float = 0.0, shadow_red: float = 0.0,
                mid_blue: float = 1.0, saturation: float = 1.0,
                highlight: float = 1.0, highlight_red: float = 0.0,
                dip: float = 0.0, dur: float) -> str:
    """The colour portion of reframe's -vf tail, in the ONE correct order:
    white-balance → tone (source profile) → black_point (toe) → gain (the mixer) →
    shadow_red → mid_blue → saturation → highlight (shoulder) → highlight_red (the red
    shoulder) → dip (timeline, last).
    `wb`/`tone` are pre-built fragments (the caller builds AND verifies them — a tone
    curve is ramp-checked in reframe.verify_tone before it reaches here).

    The comma discipline, stated because nothing else states it: every fragment
    BEFORE mixer_arg (`wb`, `tone`, black_point_arg) is either "" or ends with a
    comma; mixer_arg is the pivot, is NEVER "" and carries a comma at neither end;
    every fragment AFTER it is either "" or begins with a comma and does not end
    with one. That is what makes any subset of knobs compose into a filtergraph
    with no empty slot. It rests entirely on mixer_arg being unconditional — an
    identity branch there would fuse a wb/tone trailing comma against a
    shadow_red leading one. Pinned by two tests in tests/lib/test_color.py:
    test_the_grade_chain_is_well_formed_for_every_combination_of_knobs, which
    enumerates all 1024 on/off combinations, and
    test_each_builder_sits_on_its_own_side_of_the_mixer_pivot, which checks each
    builder's own boundary comma (design 2026-09-21 §2.4).

    Returns the fragment WITHOUT the trailing fps/format, which reframe owns.
    Every builder is "" at its identity value, so at defaults this returns
    exactly mixer_arg(*gains) and the fill fast path stays byte-identical to
    before colour-as-a-stage."""
    return (wb + tone + black_point_arg(black_point) + mixer_arg(*gains)
            + shadow_red_arg(shadow_red) + mid_blue_arg(mid_blue)
            + saturation_arg(saturation) + highlight_arg(highlight)
            + highlight_red_arg(highlight_red) + dip_arg(dip, dur))


def percentiles(hist256: list[int]) -> tuple[float, float, float]:
    """(p5, p50, p95) of an 8-bit luma histogram (256 bin counts), by cumulative count.
    Pure integer math — no numpy — so color.py stays dependency-free. The driver
    (color_measure.measure_profile) produces the histogram from a decoded still."""
    if len(hist256) != 256:
        raise ValueError(f"percentiles needs a 256-bin histogram, got {len(hist256)} bins")
    total = sum(hist256)
    if total <= 0:
        raise ValueError("percentiles: empty histogram — the clip decoded no pixels?")

    def _pct(p: float) -> float:
        target = p * total
        run = 0
        for code, c in enumerate(hist256):
            run += c
            if run >= target:
                return float(code)
        return 255.0

    return (_pct(0.05), _pct(0.50), _pct(0.95))


FRAMES = 3          # start / middle / end of a span, at (i+0.5)/N — never the first
                    # or last frame, which a dip or a bookend can own. Measured
                    # (design 2026-08-30 §0.4): 5 and 9 frames give the same residual
                    # median and a slightly worse maximum, because the residual is not
                    # sampling noise.
                    #
                    # Lives here rather than in color_measure because check_episode
                    # needs it and cannot import that driver: color_measure imports
                    # process_episode, which imports check_episode.


def sample_times(dur: float, frames: int = FRAMES) -> list[float]:
    """`frames` sample times spread over `dur`, at (k+0.5)/frames of it."""
    if not isinstance(frames, int) or isinstance(frames, bool) or frames < 1:
        raise ValueError(f"frames must be an integer >= 1, got {frames!r}")
    return [((k + 0.5) / frames) * dur for k in range(frames)]


def select_frames(times: list[float], fps: float) -> str:
    """An ffmpeg `select='eq(n\\,N)+...'` fragment picking the frame nearest each of
    `times`, rounded against `fps` to a frame index.

    Shared for the same reason FRAMES/sample_times live here rather than in
    color_measure (see the comment above): this two-line computation — round each
    time to a frame index, then OR the eq(n,N) terms together with the comma escaped
    — turned up hand-copied in three places in one slice (reframe.plan_frames_rgb,
    color_measure's percentile readers via a since-deleted `_select`, and
    probe._render), the exact species of duplication process_episode.plan_for was
    built one commit earlier to close for the manifest -> RenderPlan map. It cannot
    live in color_measure.py, the more obviously-named home: color_measure imports
    reframe (for the `RenderPlan` annotation on `crop_percentiles` — `plan_ungraded`
    itself lives in process_episode now, not here), so reframe importing a helper
    back from color_measure would be a cycle. color.py is a leaf every one of the
    three call sites already imports, so centralizing here moves nothing in the
    import graph.
    """
    nums = [round(t * fps) for t in times]
    return "select='" + "+".join(rf"eq(n\,{n})" for n in nums) + "'"
