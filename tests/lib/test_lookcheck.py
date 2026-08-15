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
    assert lookcheck.evaluate([_flat(100)], [_flat(100)], None, None) == []


def test_a_declared_vignette_that_changed_no_pixels_fails():
    same = [_flat(100), _flat(100), _flat(100)]
    by = {f.check: f for f in lookcheck.evaluate(same, list(same), None, None,
                                                 vignette=0.3)}
    assert by["vignette"].status == "fail"
    assert by["vignette"].measured == pytest.approx(0.0)


def test_a_rendered_vignette_passes():
    master = [_flat(100), _flat(100), _flat(100)]
    delivered = [_corners_dark(100, 0.3) for _ in range(3)]
    by = {f.check: f for f in lookcheck.evaluate(master, delivered, None, None,
                                                 vignette=0.3)}
    assert by["vignette"].status == "pass"


def test_titles_alone_report_not_checked_rather_than_nothing():
    """Titles have no check this slice (design §11). Returning [] would read as "the
    gate looked and was satisfied"; a not-checked finding records the absence."""
    out = lookcheck.evaluate([_flat(100)] * 3, [_flat(100)] * 3, None, None, titles=True)
    assert [(f.check, f.status) for f in out] == [("titles", "not-checked")]


def test_titles_are_reported_even_beside_a_rendered_vignette():
    """The common case: titles ride WITH a look. If the titles row only appeared when
    titles were alone, a defect that killed the drawtext stage while the vignette still
    rendered would ship attested with no trace titles were ever declared."""
    master = [_flat(100)] * 3
    delivered = [_corners_dark(100, 0.3) for _ in range(3)]
    by = {f.check: f.status for f in lookcheck.evaluate(master, delivered, None, None,
                                                        vignette=0.3, titles=True)}
    assert by == {"vignette": "pass", "titles": "not-checked"}


def test_a_vignette_too_shallow_to_be_the_declared_one_fails():
    master = [_flat(100)] * 3
    delivered = [_corners_dark(100, 0.05) for _ in range(3)]   # asked 0.30, got 0.05
    by = {f.check: f for f in lookcheck.evaluate(master, delivered, None, None, vignette=0.30)}
    assert by["vignette"].status == "fail"


def test_a_vignette_on_black_corners_is_not_checked():
    """You cannot darken black. Reporting this as proven would be the lie the gate
    exists to stop (design §7)."""
    master = [_flat(3)] * 3
    delivered = [_flat(3)] * 3
    by = {f.check: f for f in lookcheck.evaluate(master, delivered, None, None, vignette=0.3)}
    assert by["vignette"].status == "not-checked"


def test_a_rendered_fade_passes_and_a_missing_one_fails():
    mid_m, mid_d = [_flat(100)] * 3, [_flat(60)] * 3
    ok = {f.check: f for f in lookcheck.evaluate(
        mid_m, mid_d, _flat(80), _flat(0), fade=0.5)}
    assert ok["fade"].status == "pass"
    bad = {f.check: f for f in lookcheck.evaluate(
        mid_m, mid_d, _flat(80), _flat(80), fade=0.5)}
    assert bad["fade"].status == "fail"


def test_a_fade_on_an_already_black_opening_is_not_checked():
    by = {f.check: f for f in lookcheck.evaluate(
        [_flat(100)] * 3, [_flat(60)] * 3, _flat(2), _flat(0), fade=0.5)}
    assert by["fade"].status == "not-checked"


def test_mismatched_shapes_refuse():
    with pytest.raises(ValueError, match="same shape"):
        lookcheck.evaluate([_flat(100)], [_flat(100, h=100)], None, None, vignette=0.3)


def test_a_declared_fade_without_a_first_frame_refuses():
    with pytest.raises(ValueError, match="first frame"):
        lookcheck.evaluate([_flat(100)] * 3, [_flat(60)] * 3, None, None, fade=0.5)
