"""Soft normalize-to-middle color (spec §10). lutrgb is banned; use mixer."""

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
                           # shipped return point and -3 at the domain's worst, 0.05 leaves 0


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
    `ret` instead measures **exactly identity** at the shipped ret for every legal lift, and
    at most one code anywhere legal.

    Why 0.05 when the twin steps 0.1: this curve returns from a lift to identity over a range
    of `ret` rather than easing across a wide shoulder, so its kink is steeper and 0.1 still
    leaves -2 codes where it ships. The divergence is deliberate — do not "fix" it back. The
    cost is three single-code non-monotone cells against 0.1's one, all where `lift` is within
    0.02 of `ret` and the toe's slope is already near zero; that is 8-bit rounding on a flat
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
    while ret + i * SHADOW_RED_STEP < 1.0 - 1e-9:
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
TONE_SAMPLES = 13          # control points emitted; enough that the fitted spline tracks
                           # the piecewise-linear map instead of overshooting between corners


def tone_arg(src: tuple[float, float, float], dst: tuple[float, float, float]) -> str:
    """A `curves` fragment carrying one source's tone profile onto a common one.

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
    # The top endpoint is COMPUTED, not pinned to 1/1, and that is the whole trick.
    # Pinning it would force the segment above the shoulder anchor to climb from dst_p95
    # back to 255 — on this reel's drone shot, 221->148 followed by 255->255 is a slope
    # of 3.1, so the brightest foam would be EXPANDED by the very filter asked to tame
    # it. Continuing the shoulder at a gentle fixed slope instead keeps the curve
    # monotone (highlights stay separable, no plate) while spending little range on it.
    top = min(255.0, dst[2] + (255.0 - src[2]) * TONE_TOP_SLOPE)
    knots = [(0.0, 0.0), *zip(src, dst), (255.0, top)]
    # Emit the piecewise-linear map SAMPLED, not just its corners. ffmpeg fits a natural
    # cubic spline through whatever points it is given, and a spline through four corners
    # whose segment slopes differ sharply overshoots between them: measured on this
    # reel's telephoto (35/84/118 stretched onto 30/100/148) the fitted curve came back
    # with a -1 slope, i.e. a brighter input mapping to a darker output — invisible as
    # brightness, but it is banding waiting to happen in a smooth sky. Sampling the same
    # map densely leaves the spline no room to wander off it.
    # The anchors themselves join the grid: sampling ALONE pulls the fitted curve a few
    # units off each anchor (measured 5 low at the toe), and the anchors are the whole
    # point of this filter — the grid is only there to keep the spline honest between them.
    # An anchor always wins its neighbourhood: a grid point landing a fraction of a unit
    # away would hand the spline two near-coincident control points, and ffmpeg answers
    # that with an empty output rather than an error (measured: anchor 106.1 against grid
    # node 106.25 produced no frame at all).
    xs = sorted(list(src) + [x for x in (i * 255.0 / (TONE_SAMPLES - 1)
                                         for i in range(TONE_SAMPLES))
                             if all(abs(x - a) >= TONE_MIN_GAP for a in src)])
    pts = " ".join(f"{x/255:.4f}/{_lerp(knots, x)/255:.4f}" for x in xs)
    return f"curves=all='{pts}',"


def _lerp(knots: list[tuple[float, float]], x: float) -> float:
    """Piecewise-linear interpolation through sorted (in, out) knots."""
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return knots[-1][1]


def corrected(gains: tuple[float, ...], correction: tuple[float, ...],
              lo: float = LO, hi: float = HI) -> tuple[float, ...]:
    """Compose an external per-channel correction onto base grade gains and
    re-clamp to [lo, hi] (design 2026-07-11 §4). The reel retry loop passes an absolute
    factor here to pull one episode's delivered mean toward the reel median;
    the clamp keeps the total correction inside the same soft band as the grade."""
    return tuple(max(lo, min(hi, g * corr)) for g, corr in zip(gains, correction))

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
    curve is ramp-checked in reframe.verify_tone before it reaches here). Returns the
    fragment WITHOUT the trailing fps/format, which reframe owns. Every builder is ""
    at its identity value, so at defaults this returns exactly mixer_arg(*gains) and
    the fill fast path stays byte-identical to before colour-as-a-stage."""
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
