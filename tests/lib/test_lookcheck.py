import numpy as np
import pytest

from scripts.lib import lookcheck


def _flat(v: int, h: int = 200, w: int = 100) -> np.ndarray:
    return np.full((h, w, 3), v, dtype=np.uint8)


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


def test_titles_alone_report_not_checked_rather_than_nothing():
    """Titles have no check this slice (design §11). Returning [] would read as "the
    gate looked and was satisfied"; a not-checked finding records the absence."""
    out = lookcheck.evaluate([_flat(100)] * 3, [_flat(100)] * 3, None, None, None, None,
                             titles=True)
    assert [(f.check, f.status) for f in out] == [("titles", "not-checked")]


def test_titles_are_reported_even_beside_a_rendered_vignette():
    """The common case: titles ride WITH a look. If the titles row only appeared when
    titles were alone, a defect that killed the drawtext stage while the vignette still
    rendered would ship attested with no trace titles were ever declared."""
    master = [_flat(100)] * 3
    delivered = [_corners_dark(100, 0.3) for _ in range(3)]
    by = {f.check: f.status for f in lookcheck.evaluate(master, delivered, None, None, None, None,
                                                        vignette=0.3, titles=True)}
    assert by == {"vignette": "pass", "titles": "not-checked"}


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
