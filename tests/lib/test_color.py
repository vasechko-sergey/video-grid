import math
from scripts.lib import color as c

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
