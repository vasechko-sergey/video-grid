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
