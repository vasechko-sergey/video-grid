"""zoom — the pure rect + expression arithmetic behind a subject-anchored
push-in/pull-out (design 2026-08-08 §3)."""
import pytest

from scripts.lib import zoom
from scripts.lib.models import ZoomSpec


def test_zoom_max_rate_is_half_a_crop_width_per_second():
    # Pins the exact ceiling named in the interface (zoom.ZOOM_MAX_RATE: float) —
    # uncalibrated (design §10), but a silent drift here would silently loosen or
    # tighten every whip-zoom refusal below.
    assert zoom.ZOOM_MAX_RATE == 0.5


def test_scales_interpolate_linearly_over_the_routes_own_span():
    s = zoom.scales(ZoomSpec(start=1.0, end=0.6), [2.0, 2.5, 3.0])
    assert s == pytest.approx([1.0, 0.8, 0.6])


def test_scales_refuse_a_single_sample():
    with pytest.raises(ValueError, match="at least two samples"):
        zoom.scales(ZoomSpec(start=1.0, end=0.6), [2.0])


def test_scales_refuses_a_non_increasing_time_span():
    # t0 == t1: no test above reaches this branch, and without it the division
    # by (t1 - t0) below would raise a bare ZeroDivisionError instead of the
    # named, actionable refusal.
    with pytest.raises(ValueError, match="increasing"):
        zoom.scales(ZoomSpec(start=1.0, end=0.6), [2.0, 2.0])


def test_rects_shrink_from_the_full_crop_and_keep_its_centre():
    ws, hs, ys = zoom.rects(ZoomSpec(start=1.0, end=0.5), crop_w=1000, crop_h=2000,
                            crop_y=80, src_h=2160, times=[0.0, 1.0])
    assert ws == [1000, 500]
    assert hs == [2000, 1000]
    # centre_y = 80 + 1000 = 1080; the tighter rect keeps it: 1080 - 500 = 580
    assert ys == [80, 580]


def test_rects_clamp_the_top_edge_into_the_source():
    ws, hs, ys = zoom.rects(ZoomSpec(start=1.0, end=0.5), crop_w=1000, crop_h=2000,
                            crop_y=0, src_h=2000, times=[0.0, 1.0])
    assert ys == [0, 500]
    assert all(y + h <= 2000 for y, h in zip(ys, hs))


def test_rects_are_derived_from_z_so_they_match_what_ffmpeg_cuts():
    # s = 0.7 -> z = 1/0.7 = 1.428571...; int(1000/z) is 700, and int(1000*0.7) is 699
    # on this arithmetic. The record must follow z, not s (design 3.2).
    ws, _, _ = zoom.rects(ZoomSpec(start=0.7, end=0.5), crop_w=1000, crop_h=2000,
                          crop_y=0, src_h=2160, times=[0.0, 1.0])
    assert ws[0] == int(1000 / (1 / 0.7))


def test_z_expr_evaluates_to_one_over_the_scale_at_both_ends():
    e = zoom.z_expr(ZoomSpec(start=1.0, end=0.5), t0=0.0, t1=2.0)
    assert e.count("it") == 1
    assert eval(e.replace("it", "0.0")) == pytest.approx(1.0, abs=1e-4)
    assert eval(e.replace("it", "2.0")) == pytest.approx(2.0, abs=1e-4)


def test_z_expr_takes_the_variable_name_it_is_given():
    assert "t-" in zoom.z_expr(ZoomSpec(start=1.0, end=0.5), 0.0, 2.0, var="t")


def test_z_expr_refuses_a_non_increasing_time_span():
    # Same boundary as scales' — z_expr has its own guard (it does not call
    # scales), and no test above ever calls it with t0 == t1 or t1 < t0.
    with pytest.raises(ValueError, match="t1 > t0"):
        zoom.z_expr(ZoomSpec(start=1.0, end=0.5), t0=2.0, t1=2.0)


def test_validate_refuses_a_zoom_with_no_duration():
    with pytest.raises(ValueError, match="duration to travel across"):
        zoom.validate(ZoomSpec(start=1.0, end=0.7), crop_w=2000, out_w=1080, dur=0.0)


def test_validate_refuses_a_whip_zoom():
    with pytest.raises(ValueError, match="per second"):
        zoom.validate(ZoomSpec(start=1.0, end=0.2), crop_w=2000, out_w=1080, dur=0.5)


def test_validate_accepts_a_zoom_exactly_at_the_rate_ceiling():
    # rate == ZOOM_MAX_RATE exactly (0.5/1.0). The refusal is `rate > ZOOM_MAX_RATE`;
    # a mutant loosening that to `>=` would only be caught right at this boundary —
    # neither the whip-zoom nor the accepts test above sits on it.
    assert zoom.validate(ZoomSpec(start=1.0, end=0.5), crop_w=2000, out_w=1000,
                         dur=1.0) is None


def test_validate_refuses_a_push_in_past_the_delivery_width():
    with pytest.raises(ValueError, match="upsample"):
        zoom.validate(ZoomSpec(start=1.0, end=0.4), crop_w=2000, out_w=1080, dur=4.0)


def test_validate_accepts_a_zoom_that_stays_above_the_delivery_width():
    assert zoom.validate(ZoomSpec(start=1.0, end=0.6), crop_w=2000, out_w=1080,
                         dur=4.0) is None


def test_validate_accepts_a_zoom_that_exactly_meets_the_delivery_width():
    # tightest == out_w exactly (1000 == 1000). The refusal is `tightest < out_w`;
    # a mutant tightening that to `<=` would only be caught right at this boundary —
    # the "refuses" test sits below it and the "accepts" test above sits above it.
    assert zoom.validate(ZoomSpec(start=1.0, end=0.5), crop_w=2000, out_w=1000,
                         dur=4.0) is None
