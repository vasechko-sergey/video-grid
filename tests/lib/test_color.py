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


def test_tone_validates_anchors_and_emits_a_curve():
    frag = color.tone_arg((30, 100, 148), (35, 110, 150))
    assert frag.startswith("curves=all='") and frag.endswith("',")
    with pytest.raises(ValueError):
        color.tone_arg((30, 33, 148), (35, 110, 150))


def test_shadow_red_toe_only_pins_the_top():
    frag = color.shadow_red_arg(0.1)
    assert frag.startswith(",curves=r='") and "0.50/0.50" in frag and "1/1" in frag


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
