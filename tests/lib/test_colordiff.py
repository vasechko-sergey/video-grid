"""The colour-difference primitive (design docs/specs/2026-08-28-grade-delta-sensors-design.md §2.1)."""
import pytest

from scripts.lib import colordiff


# Published CIEDE2000 reference pairs (Sharma/Wu/Dalal): (lab1, lab2, expected dE00).
# The 1.0000 rows are the deliberate near-discontinuity cases; the 7.1792 row
# straddles the a'-axis where the mean-hue term has to pick the right branch.
REFERENCE = [
    ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
    ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
    ((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
    ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -1.1848, -84.8006), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -0.9009, -85.5211), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0009), 7.1792),
    ((50.0000, 2.5000, 0.0000), (73.0000, 25.0000, -18.0000), 27.1492),
    ((50.0000, 2.5000, 0.0000), (61.0000, -5.0000, 29.0000), 22.8977),
    ((50.0000, 2.5000, 0.0000), (56.0000, -27.0000, -3.0000), 31.9030),
    ((50.0000, 2.5000, 0.0000), (58.0000, 24.0000, 15.0000), 19.4535),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.1736, 0.5854), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2972, 0.0000), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 1.8634, 0.5757), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2592, 0.3350), 1.0000),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
    ((61.2901, 3.7196, -5.3901), (61.4292, 2.2480, -4.9620), 1.8731),
    ((35.0831, -44.1164, 3.7933), (35.0232, -40.0716, 1.5901), 1.8645),
    ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
]


@pytest.mark.parametrize("lab1,lab2,expected", REFERENCE)
def test_ciede2000_matches_the_published_reference(lab1, lab2, expected):
    assert colordiff.ciede2000(lab1, lab2)[0] == pytest.approx(expected, abs=1e-4)


def test_ciede2000_is_symmetric_in_total_and_signed_in_components():
    a, b = (50.0, 2.5, 0.0), (58.0, 24.0, 15.0)
    fwd, rev = colordiff.ciede2000(a, b), colordiff.ciede2000(b, a)
    assert fwd[0] == pytest.approx(rev[0], abs=1e-9)      # the total is symmetric
    for i in (1, 2, 3):                                   # the components are not
        assert fwd[i] == pytest.approx(-rev[i], abs=1e-9)


def test_identical_colours_have_zero_difference():
    assert colordiff.ciede2000((42.0, -3.0, 7.0), (42.0, -3.0, 7.0)) == (0.0, 0.0, 0.0, 0.0)


def test_rgb_to_lab_anchors():
    """Black, white and mid-grey pin the transfer curve and the white point."""
    assert colordiff.rgb_to_lab((0.0, 0.0, 0.0)) == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)
    L, a, b = colordiff.rgb_to_lab((255.0, 255.0, 255.0))
    assert L == pytest.approx(100.0, abs=1e-4) and abs(a) < 1e-3 and abs(b) < 1e-3
    L, a, b = colordiff.rgb_to_lab((128.0, 128.0, 128.0))
    assert L == pytest.approx(53.585, abs=0.01) and abs(a) < 1e-3 and abs(b) < 1e-3


def test_a_saturated_red_has_strongly_positive_a_and_positive_b():
    """Pins the XYZ matrix's columns to their actual R/G/B channels, not just their
    magnitudes. A grey input is symmetric under swapping the R and B columns (r == b),
    so `test_rgb_to_lab_anchors` cannot see a column swap, and the published reference
    table (`test_ciede2000_matches_the_published_reference`) never calls `rgb_to_lab` at
    all. Saturated red is the case where R and B genuinely differ: swapping the R and B
    columns leaves a* still positive (~79 either way) but flips b* from strongly positive
    (~+67, the textbook sRGB-red Lab value) to strongly negative (~-108)."""
    L, a, b = colordiff.rgb_to_lab((255.0, 0.0, 0.0))
    assert a > 50.0
    assert b > 0.0


def test_a_pure_luma_lift_lands_in_dL_only():
    """The component split is the report's whole explanatory value: a grey lift
    must not leak into chroma or hue."""
    _, dL, dC, dH = colordiff.ciede2000(colordiff.rgb_to_lab((100.0, 100.0, 100.0)),
                                        colordiff.rgb_to_lab((128.0, 128.0, 128.0)))
    assert dL > 10.0 and abs(dC) < 1e-5 and abs(dH) < 1e-5
