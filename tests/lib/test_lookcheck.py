from unittest import mock

import numpy as np
import pytest

from scripts.lib import lookcheck


def _flat(v: int, h: int = 200, w: int = 100) -> np.ndarray:
    return np.full((h, w, 3), v, dtype=np.uint8)


def _with_ink(v: int = 80) -> np.ndarray:
    """A flat frame carrying a bright block inside the (30, 70) band used below."""
    f = _flat(v)
    f[40:60, 10:40] = 255
    return f


def _corners_dark(v: int, frac: float, h: int = 200, w: int = 100) -> np.ndarray:
    """A flat frame whose corner boxes are darkened by `frac` — a rendered vignette."""
    f = _flat(v, h, w)
    bh, bw = h // lookcheck.BOX_DIV, w // lookcheck.BOX_DIV
    for ys in (slice(0, bh), slice(h - bh, h)):
        for xs in (slice(0, bw), slice(w - bw, w)):
            f[ys, xs] = int(round(v * (1.0 - frac)))
    return f


def test_nothing_declared_measures_nothing():
    assert lookcheck.evaluate([_flat(100)], [_flat(100)], None, None, None, None) == []


def test_a_declared_vignette_that_changed_no_pixels_fails():
    same = [_flat(100), _flat(100), _flat(100)]
    by = {f.check: f for f in lookcheck.evaluate(same, list(same), None, None, None, None,
                                                 vignette=0.3)}
    assert by["vignette"].status == "fail"
    assert by["vignette"].measured == pytest.approx(0.0)


def test_a_rendered_vignette_passes():
    master = [_flat(100), _flat(100), _flat(100)]
    delivered = [_corners_dark(100, 0.3) for _ in range(3)]
    by = {f.check: f for f in lookcheck.evaluate(master, delivered, None, None, None, None,
                                                 vignette=0.3)}
    assert by["vignette"].status == "pass"


def test_titles_alone_are_judged_with_no_look_declared():
    """Titles do not need a vignette or a fade beside them to be measured — a reel
    whose only declared treatment is its text still gets a verdict."""
    m = _flat(100)
    p = lookcheck.TitleProbe(label="hook", band=(30, 70), inside=(m, _with_ink(100)),
                             witnesses=((m, m),))
    out = lookcheck.evaluate([m] * 3, [m] * 3, None, None, None, None, titles=[p])
    assert [(f.check, f.status) for f in out] == [("titles:hook", "pass")]


def test_titles_are_reported_even_beside_a_rendered_vignette():
    """The common case: titles ride WITH a look. If the titles row only appeared when
    titles were alone, a defect that killed the drawtext stage while the vignette still
    rendered would ship attested with no trace titles were ever declared."""
    master = [_flat(100)] * 3
    delivered = [_corners_dark(100, 0.3) for _ in range(3)]
    m = _flat(100)
    p = lookcheck.TitleProbe(label="hook", band=(30, 70), inside=(m, m),
                             witnesses=((m, m),))
    by = {f.check: f.status for f in lookcheck.evaluate(master, delivered, None, None, None, None,
                                                        vignette=0.3, titles=[p])}
    assert by == {"vignette": "pass", "titles:hook": "fail"}


def test_a_vignette_too_shallow_to_be_the_declared_one_fails():
    master = [_flat(100)] * 3
    delivered = [_corners_dark(100, 0.05) for _ in range(3)]   # asked 0.30, got 0.05
    by = {f.check: f for f in lookcheck.evaluate(master, delivered, None, None, None, None,
                                                 vignette=0.30)}
    assert by["vignette"].status == "fail"


def test_a_vignette_on_black_corners_is_not_checked():
    """You cannot darken black. Reporting this as proven would be the lie the gate
    exists to stop (design §7)."""
    master = [_flat(3)] * 3
    delivered = [_flat(3)] * 3
    by = {f.check: f for f in lookcheck.evaluate(master, delivered, None, None, None, None,
                                                 vignette=0.3)}
    assert by["vignette"].status == "not-checked"


def test_a_rendered_fade_in_passes_and_a_missing_one_fails():
    mid_m, mid_d = [_flat(100)] * 3, [_flat(60)] * 3
    ok = {f.check: f for f in lookcheck.evaluate(
        mid_m, mid_d, _flat(80), _flat(0), _flat(80), _flat(0), fade=0.5, fps=30.0)}
    assert ok["fade-in"].status == "pass"
    bad = {f.check: f for f in lookcheck.evaluate(
        mid_m, mid_d, _flat(80), _flat(80), _flat(80), _flat(0), fade=0.5, fps=30.0)}
    assert bad["fade-in"].status == "fail"


def test_a_rendered_fade_out_passes_and_a_missing_one_fails():
    """final review I-3: the OLD single 'fade' check only ever sampled t=0, so a
    fade-out that silently failed to render reported 'pass' — reachable in practice
    because `deliver` computes `dur` from the MASTER while the audio branch muxes
    with `-shortest`, so a stem shorter than the master truncates the delivered
    video and pushes `fade=t=out` past its own end."""
    mid_m, mid_d = [_flat(100)] * 3, [_flat(60)] * 3
    ok = {f.check: f for f in lookcheck.evaluate(
        mid_m, mid_d, _flat(80), _flat(0), _flat(80), _flat(0), fade=0.5, fps=30.0)}
    assert ok["fade-out"].status == "pass"
    bad = {f.check: f for f in lookcheck.evaluate(
        mid_m, mid_d, _flat(80), _flat(0), _flat(80), _flat(80), fade=0.5, fps=30.0)}
    assert bad["fade-out"].status == "fail"


def test_fade_in_can_pass_while_fade_out_fails():
    """The two edges are independent evidence, not one check in two disguises — a
    fade-in that rendered cleanly says nothing about whether the fade-out did."""
    mid_m, mid_d = [_flat(100)] * 3, [_flat(60)] * 3
    by = {f.check: f for f in lookcheck.evaluate(
        mid_m, mid_d, _flat(80), _flat(0), _flat(80), _flat(80), fade=0.5, fps=30.0)}
    assert by["fade-in"].status == "pass"
    assert by["fade-out"].status == "fail"


def test_a_fade_in_on_an_already_black_opening_is_not_checked():
    by = {f.check: f for f in lookcheck.evaluate(
        [_flat(100)] * 3, [_flat(60)] * 3, _flat(2), _flat(0), _flat(80), _flat(0), fade=0.5, fps=30.0)}
    assert by["fade-in"].status == "not-checked"


def test_a_fade_out_on_an_already_black_ending_is_not_checked():
    """Mirrors the fade-in not-checked arm (design §7, amended): a reel that already
    ends on black cannot have that darkened further, so nothing here is proven
    either way."""
    by = {f.check: f for f in lookcheck.evaluate(
        [_flat(100)] * 3, [_flat(60)] * 3, _flat(80), _flat(0), _flat(2), _flat(0), fade=0.5, fps=30.0)}
    assert by["fade-out"].status == "not-checked"


def test_a_fade_out_with_a_small_quantization_residual_still_passes():
    """A correctly-rendered fade-out's LAST frame is not frame-exact at the ramp's
    true end the way fade-in's t=0 is exact at its start (final review I-3, second
    pass — found only by running this against a real render, not by inspection):
    at fade=0.5s/fps=30 the file's own reference fixture measures a residual of
    ~6.3% of the pre-fade brightness (tests/integration/test_look.py). Reusing
    FADE_BLACK_MAX (2.0) unchanged here would refuse that CORRECT render — d0=6
    against m0=80 is 7.5%, close to the measured 6.3%, and 6 > 2.0 fails the fixed
    bar while passing the dynamic one below."""
    mid_m, mid_d = [_flat(100)] * 3, [_flat(60)] * 3
    by = {f.check: f for f in lookcheck.evaluate(
        mid_m, mid_d, _flat(80), _flat(0), _flat(80), _flat(6), fade=0.5, fps=30.0)}
    assert by["fade-out"].status == "pass", by["fade-out"].detail


def test_a_short_low_fps_fade_out_needs_more_slack_but_still_catches_a_miss():
    """The residual scales with (1/fps)/fade: a legal-but-short 0.3s fade at a 24fps
    floor leaves a LARGER fraction unresolved (~13.9% by the linear model) than the
    0.5s/30fps case above — a single fixed threshold cannot be both tight enough for
    the common case and loose enough for this one. d0=11 mimics that larger
    residual (m0=80 * ~0.139) and must still pass; d0=80 (unchanged — a genuine
    non-render) must still fail by a wide margin, proving the wider slack this
    fps/fade combination needs has not made the check vacuous."""
    mid_m, mid_d = [_flat(100)] * 3, [_flat(60)] * 3
    ok = {f.check: f for f in lookcheck.evaluate(
        mid_m, mid_d, _flat(80), _flat(0), _flat(80), _flat(11), fade=0.3, fps=24.0)}
    assert ok["fade-out"].status == "pass", ok["fade-out"].detail
    bad = {f.check: f for f in lookcheck.evaluate(
        mid_m, mid_d, _flat(80), _flat(0), _flat(80), _flat(80), fade=0.3, fps=24.0)}
    assert bad["fade-out"].status == "fail"


def test_a_short_fade_out_that_did_not_render_is_not_checked_not_passed():
    """Coordinator re-review, second pass: at fade=0.1s/30fps, residual_frac clamps
    to 1.0 (fade <= 3/fps) — the bar becomes the master's own brightness, and
    d0 <= expected then holds for ANY fade-out, rendered or not, since a delivery
    cannot be brighter than its master. Reproduced on the shipped code before this
    fix: a completely UNRENDERED fade-out (d0 == m0 == 80) reported 'pass' with
    measured=80.0, expected=80.0. This is the discriminator for the fix — a
    regression back to reusing FADE_OUT_RESIDUAL_MARGIN alone, with no
    FADE_OUT_MIN_POWER floor, turns this red."""
    mid_m, mid_d = [_flat(100)] * 3, [_flat(60)] * 3
    by = {f.check: f for f in lookcheck.evaluate(
        mid_m, mid_d, _flat(80), _flat(0), _flat(80), _flat(80), fade=0.1, fps=30.0)}
    assert by["fade-out"].status == "not-checked", by["fade-out"].detail


def test_a_fade_declared_with_no_fps_refuses():
    """`fps` sizes the fade-out's quantization slack, so it is required whenever
    `fade` is, exactly like the four bookend frames — a caller that forgets it
    would silently get fade-in-only coverage under the old signature."""
    with pytest.raises(ValueError, match="fps"):
        lookcheck.evaluate([_flat(100)] * 3, [_flat(60)] * 3,
                           _flat(80), _flat(0), _flat(80), _flat(0), fade=0.5)


def test_mismatched_shapes_refuse():
    with pytest.raises(ValueError, match="same shape"):
        lookcheck.evaluate([_flat(100)], [_flat(100, h=100)], None, None, None, None,
                           vignette=0.3)


def test_a_declared_fade_without_bookend_frames_refuses():
    with pytest.raises(ValueError, match="first frame"):
        lookcheck.evaluate([_flat(100)] * 3, [_flat(60)] * 3, None, None, None, None, fade=0.5)


def test_a_declared_fade_without_a_last_frame_refuses():
    """The symmetric half of the guard above — first frame supplied, last frame is
    not. Both ends are required together; neither may stand in for the other."""
    with pytest.raises(ValueError, match="last frame"):
        lookcheck.evaluate([_flat(100)] * 3, [_flat(60)] * 3, _flat(80), _flat(0), None, None,
                           fade=0.5)


def test_title_evidence_finds_ink_the_master_does_not_explain():
    m = _flat(80)
    frac = lookcheck.title_evidence((m, _with_ink()), (m, m), (30, 70))
    assert frac == pytest.approx(20 * 30 / (40 * 100))


def test_title_evidence_is_zero_without_ink():
    m = _flat(80)
    assert lookcheck.title_evidence((m, m), (m, m), (30, 70)) == 0.0


def test_title_evidence_ignores_a_multiplicative_darkening():
    # the vignette case, and the reason this metric exists: a static transform
    # applied at BOTH times can only shrink the delivery's own frame-to-frame
    # change relative to the master's, so it scores <= 0 (design 2026-08-19 §2.3).
    m_in, m_out = _flat(200), _flat(60)
    d_in, d_out = _flat(100), _flat(30)                  # halved everywhere
    assert lookcheck.title_evidence((m_in, d_in), (m_out, d_out), (30, 70)) == 0.0


def test_title_evidence_ignores_picture_motion():
    m_in, m_out = _flat(20), _flat(220)                  # a hard cut between the samples
    assert lookcheck.title_evidence((m_in, m_in), (m_out, m_out), (30, 70)) == 0.0


def test_title_evidence_reads_only_the_band():
    m = _flat(80)
    above = _flat(80)
    above[0:20] = 255                                    # ink OUTSIDE the band
    assert lookcheck.title_evidence((m, above), (m, m), (30, 70)) == 0.0


def test_title_evidence_uses_the_worst_channel_not_their_mean():
    """A title in a saturated colour moves ONE channel and leaves the others; the
    mean of the three divides that evidence by three.

    The delta is chosen to straddle the bar rather than merely to exist: 90 clears
    TITLE_INK_DELTA on its own channel and 90/3 = 30 does not. A larger delta (255,
    the first version of this test) passes either way and proved nothing — mutation
    battery row 7 survived it."""
    m = _flat(80)
    one = _flat(80)
    one[40:60, 10:40, 0] = 80 + 90                       # red only, straddling the bar
    assert 90 > lookcheck.TITLE_INK_DELTA > 30           # the premise, pinned
    assert lookcheck.title_evidence((m, one), (m, m), (30, 70)) > 0.0


def test_title_evidence_refuses_a_band_outside_the_frame():
    m = _flat(80)
    with pytest.raises(ValueError, match="non-empty row range"):
        lookcheck.title_evidence((m, m), (m, m), (70, 30))


def test_evaluate_titles_passes_a_rendered_title():
    m = _flat(80)
    p = lookcheck.TitleProbe(label="hook", band=(30, 70),
                             inside=(m, _with_ink()), witnesses=((m, m),))
    f, = lookcheck.evaluate_titles([p])
    assert (f.check, f.status) == ("titles:hook", "pass")
    assert f.expected == pytest.approx(lookcheck.TITLE_MIN_FRACTION)


def test_evaluate_titles_fails_a_title_that_never_rendered():
    m = _flat(80)
    p = lookcheck.TitleProbe(label="hook", band=(30, 70), inside=(m, m),
                             witnesses=((m, m),))
    f, = lookcheck.evaluate_titles([p])
    assert f.status == "fail" and "did not render" in f.detail


def test_evaluate_titles_takes_the_best_witness():
    # measured: one bold-box title scored 3.53% against a dark witness frame and
    # 18.94% against a bright one, on the same in-window frame. ANY title-free
    # moment is a valid witness, so the rule is best-of, not first-of.
    m, ink = _flat(80), _with_ink()
    blind = (_flat(255), _flat(255))          # a witness that hides the ink entirely
    p = lookcheck.TitleProbe(label="hook", band=(30, 70), inside=(m, ink),
                             witnesses=(blind, (m, m)))
    assert lookcheck.evaluate_titles([p])[0].status == "pass"
    alone = lookcheck.TitleProbe(label="hook", band=(30, 70), inside=(m, ink),
                                 witnesses=(blind,))
    assert lookcheck.evaluate_titles([alone])[0].status == "fail"   # blind alone cannot


def test_evaluate_titles_reports_a_skipped_probe_as_not_checked():
    p = lookcheck.TitleProbe(label="hook", band=(30, 70),
                             skipped="every instant carries a title")
    f, = lookcheck.evaluate_titles([p])
    assert f.status == "not-checked" and "every instant" in f.detail


def test_evaluate_routes_title_probes_through():
    m = _flat(80)
    p = lookcheck.TitleProbe(label="hook", band=(30, 70), inside=(m, _with_ink()),
                             witnesses=((m, m),))
    out = lookcheck.evaluate([m], [m], None, None, None, None, titles=[p])
    assert [f.check for f in out] == ["titles:hook"]


def test_the_ink_bar_sits_between_the_measured_noise_and_the_measured_ink():
    """Rows 1 and 2 of this slice's mutation battery both SURVIVED: the mechanism
    tests above hold at any threshold, so nothing pinned the constant's value. It is
    justified by two measurements (design 2026-08-19 §3.1/§3.2) and this is where
    they live in code.

    Below: over 110 title-free frame pairs of a real delivered reel — plain
    re-encode and a max-depth 0.60 vignette — the worst single-pixel evidence was 30.
    Above: the faintest real title measured (two characters at the default size)
    peaked at 106. A bar outside [31, 106] either admits encoder noise or refuses a
    legitimate title, and neither is something a no-waiver gate may do quietly."""
    assert 30 < lookcheck.TITLE_INK_DELTA < 106


def test_the_fraction_floor_sits_between_zero_and_the_faintest_real_title():
    """The floor's own bounds, same reasoning. Below: 110 title-free pairs produced
    exactly 0.00000%. Above: a ONE-CHARACTER title — the faintest thing this repo can
    author — measured 0.0384% on real footage, the thinnest legitimate margin there
    is (design §3.4)."""
    assert 0.0 < lookcheck.TITLE_MIN_FRACTION < 0.000384




def test_a_fraction_exactly_on_the_floor_passes():
    """`>=`, not `>`. No other test in this file puts a measurement exactly ON the
    floor, so the boundary's direction was unguarded — the same hole the previous
    slice's curve_contrast row found (2026-08-18 battery 2 row 5).

    The band is 40 rows x 100 columns = 4000 pixels; TITLE_MIN_FRACTION * 4000 = 0.8,
    so ONE qualifying pixel is already above it. The tie is built by shrinking the
    floor to exactly what one pixel measures instead, which keeps the test honest if
    the constant is ever re-tuned."""
    m = _flat(80)
    d = _flat(80)
    d[45, 20] = 255                                       # exactly one ink pixel
    frac = lookcheck.title_evidence((m, d), (m, m), (30, 70))
    assert frac == pytest.approx(1 / 4000)
    p = lookcheck.TitleProbe(label="hook", band=(30, 70), inside=(m, d),
                             witnesses=((m, m),))
    with mock.patch.object(lookcheck, "TITLE_MIN_FRACTION", frac):
        assert lookcheck.evaluate_titles([p])[0].status == "pass"
