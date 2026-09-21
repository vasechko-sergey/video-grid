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

def test_corrected_is_gone():
    """color.corrected composed the reel loop's external pull onto the grade gains and
    re-clamped. The loop is retired and reframe's branch with it, so the primitive has
    no caller (design §3). LO/HI stay — color.gain reads them."""
    assert not hasattr(color, "corrected")
    assert (color.LO, color.HI) == (0.7, 1.5)


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


@pytest.mark.parametrize("pix_fmt, depth", [
    ("yuv420p", 8), ("yuvj420p", 8), ("yuv422p", 8), ("yuv444p", 8), ("nv12", 8),
    ("gray", 8),
    ("yuv420p10le", 10), ("yuv420p10be", 10), ("p010le", 10),
    ("yuv444p12le", 12), ("yuv420p16le", 16),
])
def test_plane_depth_reads_the_pixel_format_name(pix_fmt, depth):
    assert color.plane_depth(pix_fmt) == depth


def test_an_eight_bit_limited_plane_is_gradeable():
    assert color.refuse_ungradeable_plane("yuv420p", "tv", "seg.mp4") is None


def test_an_untagged_eight_bit_plane_is_gradeable():
    # "unknown" is the mp4/h264 convention for limited and assembly.matches
    # already reads it that way. A full-range file that lost its tag is
    # therefore still misread — a KNOWN gap (design §7), pinned here so nobody
    # later "fixes" it into a refusal that would reject every fixture in this
    # repo and every episode reframe writes.
    assert color.refuse_ungradeable_plane("yuv420p", "unknown", "seg.mp4") is None


def test_a_full_range_plane_is_refused_and_names_extract():
    with pytest.raises(ValueError) as e:
        color.refuse_ungradeable_plane("yuvj420p", "pc", "/f/MVI_3678.MP4")
    msg = str(e.value)
    assert "pc" in msg and "/f/MVI_3678.MP4" in msg
    assert "extract" in msg          # the remedy, not just the complaint


def test_a_ten_bit_plane_is_refused_and_names_the_depth():
    with pytest.raises(ValueError) as e:
        color.refuse_ungradeable_plane("yuv420p10le", "tv", "/f/DJI_0548.MP4")
    msg = str(e.value)
    assert "10 bits" in msg and "yuv420p10le" in msg
    assert "extract" in msg


def test_depth_is_reported_before_range_when_both_are_wrong():
    # A 10-bit full-range source is broken twice over, and the depth is the worse
    # of the two — measured, 99.26% of pixels come back on one code — so it is
    # the half the message must lead with.
    with pytest.raises(ValueError, match="10 bits"):
        color.refuse_ungradeable_plane("yuv420p10le", "pc", "x.mp4")


def test_a_stream_with_no_pix_fmt_is_refused_rather_than_assumed_eight_bit():
    """plane_depth answers 8 for a NAME with no depth marker (yuv420p, nv12,
    gray) and that is correct. An ABSENT name is not such a name — measured, a
    container whose codec this ffmpeg build cannot open reports width, height,
    frame rate and duration from its own boxes and omits pix_fmt, so the other
    four probed values look healthy while the depth is unknown (design §0.2)."""
    with pytest.raises(ValueError) as e:
        color.refuse_ungradeable_plane("", "tv", "/f/unknown_codec.mp4")
    msg = str(e.value)
    assert "pix_fmt" in msg and "/f/unknown_codec.mp4" in msg
    assert "extract" in msg          # the remedy, not just the complaint


def test_the_missing_pix_fmt_is_refused_before_the_range():
    """Order matters twice. The clause must run before plane_depth, or it is
    reached only after the wrong answer is already in hand — and an undescribable
    plane on a pc source must name the pix_fmt, not the range, because re-tagging
    the range would not make the depth knowable."""
    with pytest.raises(ValueError, match="pix_fmt"):
        color.refuse_ungradeable_plane("", "pc", "x.mp4")


def test_lerp_continues_the_last_segment_above_the_final_knot():
    knots = [(0.0, 0.0), (100.0, 50.0), (200.0, 100.0)]      # last slope 0.5
    assert color._lerp(knots, 200.0) == pytest.approx(100.0)
    assert color._lerp(knots, 240.0) == pytest.approx(120.0)
    assert color._lerp(knots, 278.3) == pytest.approx(139.15, abs=0.01)


def test_lerp_stays_flat_above_a_zero_width_final_segment():
    # p95 == 255 makes the final segment zero-width: there is no shoulder to
    # continue, so the map ends at its value rather than dividing by zero.
    knots = [(0.0, 0.0), (100.0, 50.0), (255.0, 120.0), (255.0, 120.0)]
    assert color._lerp(knots, 270.0) == pytest.approx(120.0)


def test_tone_arg_extends_the_shoulder_in_the_emitted_expression():
    frag = color.tone_arg((30.0, 100.0, 200.0), (40.0, 110.0, 190.0))
    # The final else-branch is now an expression anchored at the TOP knot
    # (x = 255) instead of a bare constant. No other segment subtracts 255 —
    # they subtract their own left anchor (0, 30, 100, 200) — so this substring
    # exists only when the extension is emitted.
    assert "-255.0000)*" in frag, frag


def test_tone_arg_keeps_a_constant_tail_when_p95_is_255():
    # zero-width final segment: the extension must not divide by zero, and must
    # not emit a slope it does not have
    frag = color.tone_arg((30.0, 100.0, 255.0), (40.0, 110.0, 200.0))
    assert "-255.0000)*" not in frag, frag
    assert frag.startswith("lutyuv=y='") and frag.endswith("',")


def test_sample_times_never_touches_the_ends():
    # The brief's own literal expected value here was [0.5, 2.0, 3.5], which is
    # only what (k+0.5)/frames*dur produces when dur happens to equal frames (the
    # pre-existing dur=3.0 case in tests/integration/test_color_measure.py gives
    # exactly [0.5, 1.5, 2.5]). At dur=4.0 with the default frames=3 the margin at
    # each end is dur/(2*frames) = 4/6 = 0.667s, not a fixed 0.5s, so the correct
    # triple is [2/3, 2.0, 10/3] — still strictly inside (0, 4.0), which is the
    # property this test's name is actually pinning.
    ts = color.sample_times(4.0)
    assert ts == pytest.approx([2 / 3, 2.0, 10 / 3])


def test_sample_times_refuses_a_non_positive_frame_count():
    with pytest.raises(ValueError, match="integer >= 1"):
        color.sample_times(4.0, 0)


def test_sample_times_refuses_a_bool_frame_count():
    with pytest.raises(ValueError, match="integer >= 1"):
        color.sample_times(4.0, True)


def test_select_frames_pins_the_comma_escaped_select_fragment():
    # 0.1*30=3, 0.5*30=15, 1.0*30=30 — round numbers chosen so the pin exercises the
    # \, escaping (design §12: ffmpeg's select expression needs the comma inside
    # eq(n,N) escaped from its own term separator) without floating-point rounding
    # near a .5 boundary muddying which integer is "the" expected one.
    frag = color.select_frames([0.1, 0.5, 1.0], 30.0)
    assert frag == r"select='eq(n\,3)+eq(n\,15)+eq(n\,30)'"


def test_select_frames_rounds_each_time_independently():
    # 0.05*30=1.5 rounds to 2 under Python's banker's rounding (round-half-to-even);
    # pinning it here means a future switch to a different rounding rule (e.g.
    # int(x+0.5)) would be caught by this test rather than silently shipping.
    frag = color.select_frames([0.05], 30.0)
    assert frag == r"select='eq(n\,2)'"


def test_the_grade_chain_is_well_formed_for_every_combination_of_knobs():
    """The comma discipline, as a property over the composition rather than a
    restatement of the docstring: independently rebuild what the discipline says
    the output must be — take the fragments in order, drop the empty ones, strip
    each survivor's OWN boundary comma, and join with exactly one comma — then
    compare that reconstruction against what grade_chain actually produced.
    Rebuilding is a different rule from the concatenation grade_chain performs, so
    the comparison is a real check and not a restatement, and unlike a comma scan
    it catches a MISSING boundary comma as well as a doubled one.

    A comma-count or ",," scan cannot do this job: tone_arg's own lutyuv expression
    carries 12 commas inside its single-quoted value, and dip_arg emits two fade
    filters separated by a comma of its own, so nothing about the total comma count
    or a ",," substring search can tell a correctly-placed separator apart from one
    sitting inside a fragment's own value. An earlier version of this test scanned
    only for ",," and dangling commas, and a missing (not doubled) boundary comma —
    dropping the leading comma from mid_blue_arg's active return — slipped through
    it undetected on all 512 combinations with mid_blue on (fix round 1).

    Enumerated over all 1024 combinations of the ten knobs at identity versus one
    legal non-identity value. Pure string construction — no ffmpeg. The empty-slot/
    dangling-comma/non-empty checks stay alongside the rebuild: they are what still
    catches mixer_arg going empty at unit gains, which the rebuild's own join would
    silently agree with (design §0.4/§2.4)."""
    import itertools
    wb_on = color.white_balance_arg((100.0, 110.0, 120.0), 1.0)
    tone_on = color.tone_arg((40.0, 120.0, 200.0), (52.0, 103.5, 191.5))
    axes = [
        ("wb", "", wb_on),
        ("tone", "", tone_on),
        ("gains", (1.0, 1.0, 1.0), (1.05, 1.0, 0.95)),
        ("black_point", 0.0, color.BLACK_POINT_MAX),
        ("shadow_red", 0.0, color.SHADOW_RED_MAX),
        ("mid_blue", 1.0, color.MID_BLUE_MAX),
        ("saturation", 1.0, color.SATURATION_MIN),
        ("highlight", 1.0, color.HIGHLIGHT_MIN),
        ("highlight_red", 0.0, color.HIGHLIGHT_RED_MAX),
        ("dip", 0.0, 0.5),
    ]
    seen = 0
    for combo in itertools.product(*[(off, on) for _, off, on in axes]):
        kw = {name: value for (name, _, _), value in zip(axes, combo)}
        gains = kw.pop("gains")
        out = color.grade_chain(gains, dur=4.0, **kw)
        # Rebuild what the discipline says the output must be — strip each
        # non-empty fragment's own boundary comma, join with exactly one — and
        # compare. A different rule from the concatenation grade_chain performs,
        # so this is a check and not a restatement, and unlike a comma scan it
        # catches a MISSING boundary comma as well as a doubled one: tone_arg
        # carries 12 commas inside its own quoted lutyuv expression and dip_arg
        # emits two fades separated by one, so nothing may split on commas here.
        frags = [wb_on if kw["wb"] else "",
                 tone_on if kw["tone"] else "",
                 color.black_point_arg(kw["black_point"]),
                 color.mixer_arg(*gains),
                 color.shadow_red_arg(kw["shadow_red"]),
                 color.mid_blue_arg(kw["mid_blue"]),
                 color.saturation_arg(kw["saturation"]),
                 color.highlight_arg(kw["highlight"]),
                 color.highlight_red_arg(kw["highlight_red"]),
                 color.dip_arg(kw["dip"], 4.0)]
        expected = ",".join(f.strip(",") for f in frags if f)
        assert out == expected, f"boundary defect with {kw}"
        assert ",," not in out, f"empty filter slot with {kw}"
        assert not out.startswith(",") and not out.endswith(","), f"dangling comma with {kw}"
        assert out, f"empty chain with {kw}"
        seen += 1
    assert seen == 1024        # the enumeration ran; a silent product() bug would not


def test_each_builder_sits_on_its_own_side_of_the_mixer_pivot():
    """The per-builder half of the discipline, so a new builder added on the wrong
    side fails with a message saying which side it belongs on."""
    before = [("white_balance_arg", color.white_balance_arg((100.0, 110.0, 120.0), 1.0)),
              ("tone_arg", color.tone_arg((40.0, 120.0, 200.0), (52.0, 103.5, 191.5))),
              ("black_point_arg", color.black_point_arg(color.BLACK_POINT_MAX))]
    after = [("shadow_red_arg", color.shadow_red_arg(color.SHADOW_RED_MAX)),
             ("mid_blue_arg", color.mid_blue_arg(1.2)),
             ("saturation_arg", color.saturation_arg(0.5)),
             ("highlight_arg", color.highlight_arg(0.6)),
             ("highlight_red_arg", color.highlight_red_arg(color.HIGHLIGHT_RED_MAX)),
             ("dip_arg", color.dip_arg(0.5, 4.0))]
    for name, frag in before:
        assert frag.endswith(","), f"{name} runs BEFORE mixer_arg: end with a comma"
        assert not frag.startswith(","), f"{name} runs BEFORE mixer_arg: no leading comma"
    for name, frag in after:
        assert frag.startswith(","), f"{name} runs AFTER mixer_arg: begin with a comma"
        assert not frag.endswith(","), f"{name} runs AFTER mixer_arg: no trailing comma"
    pivot = color.mixer_arg(1.0, 1.0, 1.0)
    assert pivot, "mixer_arg is the pivot and is never empty — the whole discipline rests on it"
    assert not pivot.startswith(",") and not pivot.endswith(",")
