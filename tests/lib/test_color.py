import math
import pytest
from scripts.lib import color as c
from scripts.lib import color

def test_gain_no_change_when_on_target():
    assert math.isclose(c.gain(measured=105, target=105), 1.0, abs_tol=1e-6)

def test_gain_boosts_dark_channel():
    # measured below target → gain > 1
    val = c.gain(measured=90, target=105)  # 1 + 0.55*(105/90 - 1) = 1.0917
    assert math.isclose(val, 1.0917, abs_tol=1e-3)

def test_gain_clamped_low():
    assert c.gain(measured=1000, target=105) == 0.7

def test_gain_clamped_high():
    assert c.gain(measured=1, target=105) == 1.5

def test_mixer_arg_format():
    arg = c.mixer_arg(1.092, 1.028, 1.063)
    assert arg == "colorchannelmixer=rr=1.092:gg=1.028:bb=1.063"

def test_targets_from_means():
    rr, gg, bb = c.gains_for_means(measured=(90, 118, 130))
    # defaults target R105/G122/B137
    assert math.isclose(rr, c.gain(90, 105), abs_tol=1e-6)
    assert math.isclose(gg, c.gain(118, 122), abs_tol=1e-6)
    assert math.isclose(bb, c.gain(130, 137), abs_tol=1e-6)

def test_gain_rejects_nonpositive_measured():
    import pytest
    with pytest.raises(ValueError, match="not positive"):
        c.gain(measured=0, target=105)

def test_corrected_composes_and_leaves_unit_factor_alone():
    # base gains unchanged where the correction is 1.0; scaled where it is not
    assert c.corrected((1.0, 1.0, 1.0), (1.2, 1.0, 0.9)) == (1.2, 1.0, 0.9)


def test_corrected_clamps_high():
    # 1.4 * 1.4 = 1.96 → clamped to the grade ceiling HI=1.5
    assert c.corrected((1.4, 1.0, 1.0), (1.4, 1.0, 1.0)) == (1.5, 1.0, 1.0)


def test_corrected_clamps_low():
    # 0.8 * 0.8 = 0.64 → clamped to the grade floor LO=0.7
    assert c.corrected((0.8, 1.0, 1.0), (0.8, 1.0, 1.0)) == (0.7, 1.0, 1.0)


def test_black_point_identity_and_value():
    assert color.black_point_arg(0) == ""
    assert color.black_point_arg(0.1) == "colorlevels=rimin=0.1000:gimin=0.1000:bimin=0.1000,"


def test_black_point_rejects_bool_and_range():
    with pytest.raises(ValueError):
        color.black_point_arg(True)
    with pytest.raises(ValueError):
        color.black_point_arg(0.5)


def test_highlight_saturation_shadow_mid_dip_identities():
    assert color.highlight_arg(1.0) == ""
    assert color.saturation_arg(1.0) == ""
    assert color.shadow_red_arg(0) == ""
    assert color.mid_blue_arg(1.0) == ""
    assert color.dip_arg(0, 3.0) == ""


def test_saturation_value_and_range():
    assert color.saturation_arg(1.2) == ",eq=saturation=1.2000"
    with pytest.raises(ValueError):
        color.saturation_arg(2.0)


def test_dip_fits_the_episode():
    frag = color.dip_arg(0.2, 3.0)
    assert "fade=t=in:st=0:d=0.200:color=0x141414" in frag
    assert "fade=t=out" in frag
    with pytest.raises(ValueError):
        color.dip_arg(0.5, 0.8)


def test_tone_validates_anchors_and_emits_a_transfer():
    # re-pinned 2026-08-19: the actuator is a luma LUT, not an RGB spline. The
    # refusal on near-coincident anchors is unchanged and pinned here too.
    frag = color.tone_arg((30, 100, 148), (35, 110, 150))
    assert frag.startswith("lutyuv=y='") and frag.endswith("',")
    with pytest.raises(ValueError):
        color.tone_arg((30, 33, 148), (35, 110, 150))


def test_shadow_red_pins_the_identity_region_densely():
    # Three anchors (0.50/0.70/0.85) pinned three POINTS, not the spline between them:
    # measured -6 codes at the shipped ret, worst at x~0.31, in the gap right after the
    # return point (design 2026-08-15 §1.1). Anchors now step 0.05 from `ret` to 1.0.
    frag = color.shadow_red_arg(0.1)
    assert frag.startswith(",curves=r='") and frag.endswith("'")
    pts = frag[len(",curves=r='"):-1].split(" ")
    xs = [float(p.split("/")[0]) for p in pts]
    assert xs[:4] == [0.0, 0.0833, 0.1667, 0.25]              # the toe, unchanged
    above = xs[4:]
    assert above[0] == 0.3 and above[-1] == 1.0
    assert len(above) == 15                                    # 0.30..0.95 step .05, plus 1.0
    assert all(abs(b - a - 0.05) < 1e-9 for a, b in zip(above, above[1:]))
    assert all(p.split("/")[0] == p.split("/")[1] for p in pts[4:])   # identity, exactly


def test_shadow_red_density_follows_a_non_default_return_point():
    # derived from `ret`, not hardcoded — a caller passing a non-default return point
    # must not silently fall back to the old sparsity (the twin's knee lesson).
    frag = color.shadow_red_arg(0.05, ret=0.40)
    xs = [float(p.split("/")[0]) for p in frag[len(",curves=r='"):-1].split(" ")]
    assert xs[4] == 0.45 and xs[-1] == 1.0


def test_shadow_red_refuses_a_lift_that_inverts_the_toe():
    # slope in the toe is 1 - lift/ret; at lift > ret it is negative, so the mapping
    # DECREASES and the shadows band. Measured 2026-08-15 (design §1.3): every
    # non-monotone cell in the scan had lift >= ret, and none with lift < ret did.
    with pytest.raises(ValueError, match="inverts"):
        color.shadow_red_arg(0.20, ret=0.10)


def test_shadow_red_refuses_a_lift_equal_to_the_return_point():
    # lift == ret is slope exactly 0: a flat plateau in the toe, where 8-bit rounding
    # decides whether the output wobbles. Refused rather than left to the quantizer.
    with pytest.raises(ValueError, match="inverts"):
        color.shadow_red_arg(0.10, ret=0.10)


def test_shadow_red_accepts_a_lift_below_the_return_point():
    # the paired proof: the refusal must not swallow the configuration that ships.
    assert color.shadow_red_arg(0.20).startswith(",curves=r='")
    assert color.shadow_red_arg(0.09, ret=0.10).startswith(",curves=r='")


def test_shadow_red_anchors_never_duplicate_the_appended_endpoint():
    # The loop building the identity anchors above `ret` used to bound itself with a bare
    # `1e-9` against FLOAT precision, but the anchors are EMITTED at .4f (1e-4) precision:
    # an anchor within the last half-quantum below 1.0 (ret within ~5e-5 below a
    # SHADOW_RED_STEP multiple — e.g. ret=0.04996) formatted to "1.0000" and was then
    # followed by the unconditionally-appended "1.0000" — two identical control points,
    # which ffmpeg's curves parser refuses outright (confirmed: exit 234). Fixed by
    # SHADOW_RED_FMT_EPS, derived from the .4f quantum instead of a bare float epsilon.
    #
    # Swept at 1e-5 resolution — finer than the ~5e-5-wide bad bands — across the whole
    # legal `ret` domain. `lift` is pinned to a tiny constant rather than swept too: the
    # anchors above `ret` are built from `ret` and SHADOW_RED_STEP alone (see
    # shadow_red_arg's `hi_xs` loop) and do not depend on `lift`, so varying it would
    # repeat the same check for no extra coverage.
    lift = 1e-6
    i = 1
    checked = 0
    while True:
        ret = round(i * 1e-5, 6)
        i += 1
        if ret > 0.45 + 1e-9:
            break
        if lift >= ret:
            continue
        frag = color.shadow_red_arg(lift, ret=ret)
        pts = frag[len(",curves=r='"):-1].split(" ")
        above = pts[4:]                  # the toe is always exactly 4 points; skip it
        xs = [p.split("/")[0] for p in above]
        assert above[-1] == "1.0000/1.0000", (
            f"ret={ret}: last control point is {above[-1]!r}, not the appended endpoint")
        assert len(xs) == len(set(xs)), (
            f"ret={ret}: duplicate x among the formatted anchors {xs} — ffmpeg's curves "
            "parser refuses two identical control points")
        floats = [float(x) for x in xs]
        assert all(b > a for a, b in zip(floats, floats[1:])), (
            f"ret={ret}: formatted anchors are not strictly increasing: {xs}")
        checked += 1
    assert checked > 40000, f"only {checked} ret values were swept — the loop ran short"


def test_grade_chain_default_is_just_the_mixer():
    gains = (1.1, 1.0, 0.9)
    assert color.grade_chain(gains, dur=3.0) == color.mixer_arg(*gains)


def test_grade_chain_orders_every_op():
    gains = (1.0, 1.0, 1.0)
    out = color.grade_chain(gains, wb="colorchannelmixer=rr=1.010:gg=1.000:bb=0.990,",
                            tone="curves=all='0/0 1/1',", black_point=0.1, shadow_red=0.1,
                            mid_blue=0.9, saturation=1.2, highlight=0.9, dip=0.2, dur=3.0)
    # wb → tone → black_point → gain(mixer) → shadow_red → mid_blue → saturation → highlight → dip
    assert out.index("rr=1.010") < out.index("curves=all") < out.index("colorlevels")
    # bb=1.000, not gg=1.000: the wb fixture above already contains the literal text
    # "gg=1.000", so index() on that substring would match wb's copy (before black_point),
    # not the mixer's — bb=1.000 only ever comes from the mixer (wb's is bb=0.990).
    assert out.index("colorlevels") < out.index("bb=1.000")          # black_point before the gain
    assert out.index("colorchannelmixer=rr=1.000") < out.index("curves=r=")   # gain before shadow_red
    assert out.index("curves=r=") < out.index("curves=b=") < out.index("eq=saturation")
    assert out.index("eq=saturation") < out.index("curves=all='0/0 0.55") < out.index("fade=t=in")


def test_white_balance_off_is_identity():
    assert color.white_balance_gains((80, 100, 120), 0.0) == (1.0, 1.0, 1.0)
    assert color.white_balance_arg((80, 100, 120), 0.0) == ""


def test_white_balance_full_neutralizes_toward_the_average():
    means = (80.0, 100.0, 120.0)          # avg 100
    gr, gg, gb = color.white_balance_gains(means, 1.0)
    assert gr > 1.0 and gg == pytest.approx(1.0) and gb < 1.0   # lift low channel, drop high
    assert color.white_balance_arg(means, 1.0).endswith(",")    # leading position → trailing comma
    assert color.white_balance_arg(means, 1.0).startswith("colorchannelmixer=")


def test_white_balance_clamps_and_rejects_bool():
    gains = color.white_balance_gains((10.0, 100.0, 100.0), 1.0)
    assert all(color.LO <= g <= color.HI for g in gains)
    with pytest.raises(ValueError):
        color.white_balance_arg((80, 100, 120), True)


def test_percentiles_of_a_known_histogram():
    # a flat 0..255 histogram (one count per code) → p5≈12.75, p50≈127.5, p95≈242.25
    hist = [1] * 256
    p5, p50, p95 = color.percentiles(hist)
    assert 10 <= p5 <= 16 and 125 <= p50 <= 130 and 240 <= p95 <= 246


def test_percentiles_of_a_spike():
    hist = [0] * 256
    hist[100] = 1000                    # all mass at code 100
    assert color.percentiles(hist) == (100.0, 100.0, 100.0)


def test_percentiles_rejects_wrong_length():
    with pytest.raises(ValueError):
        color.percentiles([1, 2, 3])


def test_highlight_red_is_identity_at_zero():
    assert color.highlight_red_arg(0.0) == ""


def test_highlight_red_pins_everything_below_the_knee_to_identity():
    # fix round 2 (2026-08-13): dense anchors every 0.1 up to and including the knee,
    # not the original three (0, knee/2, knee) — pinning three points does not pin
    # the CUBIC SPLINE ffmpeg fits between them (measured: up to +7/-3 codes of sag
    # with three anchors; see the docstring and test_highlight_red_sub_knee_residual
    # below for the real-ffmpeg proof this string-level test cannot give on its own).
    arg = color.highlight_red_arg(0.2)
    assert arg.startswith(",curves=r='")
    lo = arg.split("'")[1].split()[:7]
    assert lo == ["0.0000/0.0000", "0.1000/0.1000", "0.2000/0.2000", "0.3000/0.3000",
                  "0.4000/0.4000", "0.5000/0.5000", "0.6000/0.6000"]


def test_highlight_red_pulls_white_by_the_full_amount():
    # the top anchor is x=1.0 mapped to 1-pull: that IS the pull, at white
    arg = color.highlight_red_arg(0.2)
    assert arg.split("'")[1].split()[-1] == "1.0000/0.8000"


@pytest.mark.parametrize("pull", [-0.01, 0.36, True, "0.2"])
def test_highlight_red_refuses_out_of_band(pull):
    with pytest.raises(ValueError, match="highlight_red"):
        color.highlight_red_arg(pull)


@pytest.mark.parametrize("knee", [0.29, 0.91])
def test_highlight_red_refuses_a_knee_outside_its_band(knee):
    with pytest.raises(ValueError, match="knee"):
        color.highlight_red_arg(0.2, knee=knee)


def test_grade_chain_places_highlight_red_after_the_shoulder():
    # the shoulder lift, then the red shoulder pull, then the timeline dip LAST.
    # NOTE: the task brief's snippet used highlight=1.2 — out of highlight_arg's own
    # [0.6, 1.0] band (HIGHLIGHT_MIN), so it raises rather than returning a fragment
    # to search for. 0.8 is in-band and, per the self-review note above, not 1.0
    # (highlight's identity, which would emit "" and make the ordering assert vacuous).
    out = color.grade_chain((1.0, 1.0, 1.0), highlight=0.8, highlight_red=0.2,
                            dip=0.1, dur=3.0)
    hi = color.highlight_arg(0.8).lstrip(",")
    hr = color.highlight_red_arg(0.2).lstrip(",")
    dip = color.dip_arg(0.1, 3.0).lstrip(",")
    assert out.index(hi) < out.index(hr) < out.index(dip)


def test_grade_chain_is_unchanged_at_the_highlight_red_default():
    assert (color.grade_chain((1.1, 1.0, 0.9), dur=3.0)
            == color.grade_chain((1.1, 1.0, 0.9), highlight_red=0.0, dur=3.0))


def test_tv_range_constants_match_what_the_pipeline_encodes():
    """Measured, not typed (design 2026-08-19 §3): black and white through this
    repo's own yuv420p h264 land on 16 and 235 in the Y plane, while
    measure_profile's format=gray path reads the same two as 0 and 255. If either
    end changes, every tone anchor lands somewhere else and nothing else fails.
    tests/integration/test_matchgrade.py proves the pair against a real encode."""
    assert (color.TV_LO, color.TV_LO + color.TV_SPAN) == (16.0, 235.0)


def test_segments_are_the_knots_the_map_was_given():
    src, dst = (73.0, 137.0, 196.0), (61.0, 123.5, 192.0)
    segs = color._segments(src, dst)
    assert [x for x, _ in segs] == [0.0, 73.0, 137.0, 196.0, 255.0]
    assert [y for _, y in segs][:4] == [0.0, 61.0, 123.5, 192.0]
    top = min(255.0, dst[2] + (255.0 - src[2]) * color.TONE_TOP_SLOPE)
    assert segs[-1] == (255.0, top)


def test_segments_survive_a_zero_low_anchor():
    # p5 == 0 is legal on a crushed source, and a naive first-segment slope would
    # divide by zero. The knots stay; the emitter is what has to cope.
    segs = color._segments((0.0, 100.0, 200.0), (10.0, 110.0, 210.0))
    assert segs[0] == (0.0, 0.0) and segs[1] == (0.0, 10.0)


def test_tone_arg_emits_a_luma_only_transfer():
    frag = color.tone_arg((10.0, 90.0, 150.0), (20.0, 110.0, 210.0))
    assert frag.startswith("lutyuv=y='") and frag.endswith("',")
    assert "curves" not in frag          # chroma no longer rides the tone curve


def test_tone_arg_converts_both_ends_of_the_range():
    frag = color.tone_arg((10.0, 90.0, 150.0), (20.0, 110.0, 210.0))
    assert f"val-{color.TV_LO}" in frag        # tv Y -> full-range value, going in
    assert f"{color.TV_SPAN}/255" in frag      # full-range result -> tv Y, coming out


def test_tone_arg_still_refuses_the_same_bad_anchors():
    # unchanged by the actuator swap, and pinned so the rewrite cannot quietly drop
    # a refusal along with the spline scaffolding it was tangled with.
    for bad in ((150.0, 90.0, 10.0), (10.0, 10.5, 150.0)):
        with pytest.raises(ValueError):
            color.tone_arg(bad, (20.0, 110.0, 210.0))
