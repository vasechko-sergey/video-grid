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


def test_zoom_max_upscale_is_one_and_a_half():
    # Pins the exact ceiling named in the interface (zoom.ZOOM_MAX_UPSCALE: float).
    # Measured, not arbitrary (design §6/§10): refusing every upsample caps a 9:16
    # crop of a 16:9 4K source at a 1.125x push-in, so a silent drift here would
    # silently re-impose that cap or loosen it further with no test noticing.
    assert zoom.ZOOM_MAX_UPSCALE == 1.5


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


def test_scales_grow_for_a_pull_out():
    # Every test above is a push-in (end < start): scale only ever shrinks. A
    # pull-out (end > start) is half the feature and exercises the same
    # interpolation in the opposite direction — an implementation that silently
    # assumed start > end (e.g. always subtracting the smaller from the larger)
    # would get this backwards while every push-in test kept passing.
    s = zoom.scales(ZoomSpec(start=0.6, end=1.0), [0.0, 1.0])
    assert s == pytest.approx([0.6, 1.0])
    assert s[1] > s[0]


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
    # s = 0.7 -> z = 1/0.7 = 1.428571...; crop_w=1001/crop_h=2001 are chosen because
    # this is where the two formulations actually disagree: int(1001/z) is 700 but
    # round(1001*0.7) is 701, and int(2001/z) is 1400 but round(2001*0.7) is 1401
    # (measured — Python's `1001*0.7` is 700.6999999999999, `2001*0.7` is
    # 1400.7). A crop of 1000/2000 does NOT discriminate: every formulation
    # agrees on 700/1400 there (`1000*0.7` is exactly `700.0`), which is why an
    # earlier version of this test using those numbers passed against a
    # `round(crop_w * s)` mutant of `rects` — it asserted a value both
    # formulations produce. The record must follow z, not s (design 3.2), and
    # the same z-vs-s gap applies to height, not only width.
    ws, hs, _ = zoom.rects(ZoomSpec(start=0.7, end=0.5), crop_w=1001, crop_h=2001,
                           crop_y=0, src_h=2160, times=[0.0, 1.0])
    assert ws[0] == int(1001 / (1 / 0.7))
    assert hs[0] == int(2001 / (1 / 0.7))


def test_rects_grow_for_a_pull_out_and_z_never_drops_below_one():
    # ffmpeg's zoompan silently CLAMPS z below 1 to 1 (design §3.3 — measured:
    # z=0.5 renders byte-identical to z=1) — a push-in never reaches z < 1 since
    # s <= 1.0 there too, but a PULL-OUT is exactly the direction a bug (e.g.
    # z = s instead of z = 1/s) would produce it, and the render would then
    # silently do nothing instead of failing loud. ZoomSpec bounds both ends to
    # (0, 1], so z = 1/s >= 1.0 always; this pins that invariant against the
    # actual rect record, not just against the arithmetic in isolation.
    spec = ZoomSpec(start=0.6, end=1.0)
    ws, hs, _ = zoom.rects(spec, crop_w=1000, crop_h=2000, crop_y=0, src_h=2160,
                           times=[0.0, 1.0])
    assert ws == [600, 1000]
    assert hs == [1200, 2000]
    assert ws[1] > ws[0] and hs[1] > hs[0]
    for s in zoom.scales(spec, [0.0, 1.0]):
        assert 1.0 / s >= 1.0


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


def test_z_expr_handles_a_pull_out():
    # The two z_expr tests above only ever push in (end < start, z rising from 1.0).
    # A pull-out (end > start) must still evaluate correctly, and — the same
    # zoompan clamp concern as the rects pull-out test above — every z along it
    # must stay >= 1.0, shrinking TOWARD 1 rather than below it.
    e = zoom.z_expr(ZoomSpec(start=0.6, end=1.0), t0=0.0, t1=2.0)
    z0 = eval(e.replace("it", "0.0"))
    z1 = eval(e.replace("it", "2.0"))
    assert z0 == pytest.approx(1 / 0.6, abs=1e-4)
    assert z1 == pytest.approx(1.0, abs=1e-4)
    assert z0 >= 1.0 and z1 >= 1.0
    assert z1 < z0


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


def test_validate_refuses_a_push_in_past_the_upscale_ceiling():
    # crop_w=2000, end=0.3 -> tightest=600px against a 1080px delivery is a 1.8x
    # upsample — past ZOOM_MAX_UPSCALE (1.5x), so this must still refuse under
    # the bounded allowance, not just under the old (unbounded) rule.
    with pytest.raises(ValueError, match="upsampling"):
        zoom.validate(ZoomSpec(start=1.0, end=0.3), crop_w=2000, out_w=1080, dur=4.0)


def test_validate_accepts_a_push_in_that_upsamples_within_the_ceiling():
    # The SAME numbers as the old (pre-scope-change) refusing case: crop_w=2000,
    # end=0.4 -> tightest=800px against 1080px is a 1.35x upsample. Refusing ANY
    # upsample made this illegal; the measured ruling (design §6) is that 1.35x
    # must be legal because it is below the 1.5x ceiling — a 9:16 crop of a 16:9
    # 4K source only reaches 1.125x, so a stricter line would cap the flagship
    # format below visibility.
    assert zoom.validate(ZoomSpec(start=1.0, end=0.4), crop_w=2000, out_w=1080,
                         dur=4.0) is None


def test_validate_accepts_a_zoom_that_stays_above_the_delivery_width():
    # No upsampling at all (tightest 1200 > out_w 1080, ratio 0.9x) — legal under
    # either rule, kept distinct from the "upsamples but within the ceiling" case
    # above since it exercises a different branch (tightest is nowhere near
    # `floor` here, so a bug in `floor`'s arithmetic could still slip past this
    # one alone).
    assert zoom.validate(ZoomSpec(start=1.0, end=0.6), crop_w=2000, out_w=1080,
                         dur=4.0) is None


def test_validate_accepts_a_zoom_exactly_at_the_upscale_ceiling():
    # tightest == floor exactly: crop_w=2000, end=0.4 -> tightest=800; out_w=1200
    # -> floor = 1200 / 1.5 = 800.0 exactly (a 1.5x upsample, right at the
    # ceiling). The refusal is `tightest < floor`; a mutant tightening that to
    # `<=` would refuse exactly this input and nothing else here would catch it —
    # the "refuses" test sits well below this boundary (600 vs 720) and the
    # "within the ceiling" test sits well above it (800 vs 720, a different floor).
    assert zoom.validate(ZoomSpec(start=1.0, end=0.4), crop_w=2000, out_w=1200,
                         dur=4.0) is None


def test_validate_refuses_a_crop_that_tightens_to_zero_pixels():
    # A plausible authoring typo (an extra zero in the `to` fraction) on a narrow
    # crop tightens to 0px. The whip-rate check does not catch it first: rate is
    # abs(0.02-1.0)/2.0 = 0.49, just under the 0.5 ceiling. Before the fix, the
    # upsample-ratio message computed `out_w / tightest` and crashed with a bare
    # ZeroDivisionError instead of raising the ValueError this function promises
    # for every input — ValueError is the ONLY exception `validate` may ever
    # raise, and a rect with no width is refused as its own defect, not folded
    # into the upsample-ratio message that would have to divide by it.
    with pytest.raises(ValueError, match="not a rectangle"):
        zoom.validate(ZoomSpec(start=1.0, end=0.02), crop_w=40, out_w=1080, dur=2.0)
