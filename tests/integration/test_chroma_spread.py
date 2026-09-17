"""Real-ffmpeg proofs for `check_reel.chroma_spread` (design
docs/specs/2026-09-17-chroma-spread-design.md §2, §4), and the bar re-derived
against the suite's own `golden_ride_segment` fixture rather than only against
the real reel design §2.5 quotes.

The statistic is always measured over the CROP — the whole rendered frame, the
one pixel set every episode always has (design §2.2) — never a named subject:
`_chroma_reading` below means each frame's RGB over its full extent, exactly
the "mean RGB of the ungraded frames" / "mean RGB of the graded frames" the
task brief names, then hands the two per-frame series to
`color_fidelity.evaluate`, the same arithmetic
`check_episode._subject_delta_advisory` uses for its own `crop_delta_c`/
`crop_delta_h` pair (2026-09-16 §2.2). Going through `check_episode`/`regions`
directly would pull in subject-mask/sidecar machinery this reel-level
statistic does not need — the crop needs no route, no mask, nothing but the
two renders.
"""
import numpy as np
import pytest

from scripts import process_episode, reframe
from scripts.check_reel import _chroma_spread_check
from scripts.lib import color, color_fidelity
from scripts.lib.models import ReelCheckSpec

pytestmark = pytest.mark.integration

ROUTE = "tests/fixtures/golden_route.json"     # sampled against golden_ride_segment's
                                               # own timeline (tests/conftest.py)


def _md(src: str, **extra) -> dict:
    md = {"segment": src, "out_path": "unused.mp4", "target_dur": 1.5,
          "composition": "center", "grid": "thirds", "layout": "fill",
          "canvas": [9, 16], "delivery": "short_edge:480"}
    md.update(extra)
    return md


def _crop_pairs(plain_frames: list, graded_frames: list) -> list[tuple]:
    """One (plain_rgb, graded_rgb) mean pair per frame, over the WHOLE frame.

    Mirrors check_episode._region_pairs with an all-True mask, without pulling
    in regions.subject_mask/refuse — the crop is defined identically on every
    episode and needs no route to resolve (design §2.2)."""
    plain, graded = np.asarray(plain_frames), np.asarray(graded_frames)
    return [(tuple(float(plain[i][:, :, c].mean()) for c in range(3)),
             tuple(float(graded[i][:, :, c].mean()) for c in range(3)))
            for i in range(len(graded))]


def _chroma_reading(md: dict, src: str) -> dict:
    """Render `md` graded and ungraded, and describe the crop's displacement in
    the exact shape `_chroma_spread_check` reads: `{delta_c, delta_h}` — no
    `region` key (final whole-branch review, FIX 1; design §2.3 amended)."""
    graded_plan = process_episode.plan_for(md, src, ROUTE)
    plain_plan = process_episode.plan_ungraded(md, src, ROUTE)
    times = color.sample_times(graded_plan.dur)
    plain_frames = reframe.plan_frames_rgb(plain_plan, src, times)
    graded_frames = reframe.plan_frames_rgb(graded_plan, src, times)
    d = color_fidelity.evaluate(_crop_pairs(plain_frames, graded_frames))
    return {"delta_c": d["delta_c"], "delta_h": d["delta_h"]}


def test_two_identical_chains_displace_nothing(golden_ride_segment):
    """The control that must not move: content cancels by construction, so a
    displacement measured between two renders of ONE chain is exactly 0.0 on both
    components (design §4.4). If this ever drifts, the statistic is measuring the
    encoder, not the grade."""
    src = str(golden_ride_segment)
    # A real grade in the chain, not the trivial ungraded case — the claim is
    # that content cancels EVEN THROUGH a colour operation, not merely that an
    # identity chain reads as identity.
    plan = process_episode.plan_for(_md(src, saturation=0.85, mid_blue=1.1), src, ROUTE)
    times = color.sample_times(plan.dur)
    a = reframe.plan_frames_rgb(plan, src, times)
    b = reframe.plan_frames_rgb(plan, src, times)
    d = color_fidelity.evaluate(_crop_pairs(a, b))
    print(f"\nMEASURED identical-chain reading: {d}")
    assert d["delta_e"] == 0.0
    assert d["delta_c"] == 0.0
    assert d["delta_h"] == 0.0


def test_a_saturation_pull_moves_dC_and_leaves_the_sign_readable(golden_ride_segment):
    """saturation_arg is the one clean, hue-preserving chroma scaler: a pull below
    1.0 must come back as a NEGATIVE delta_c (design §5.2)."""
    src = str(golden_ride_segment)
    reading = _chroma_reading(_md(src, saturation=0.8), src)
    print(f"\nMEASURED saturation=0.8 crop reading: {reading}")
    # Not merely < 0: a value hugging zero would be noise reading a sign by luck.
    # Measured -1.3 on this fixture, comfortably clear of that.
    assert reading["delta_c"] < -0.5, reading


def test_the_bar_separates_a_consistent_reel_from_one_odd_episode(golden_ride_segment):
    """The bar re-derived on the suite's own fixture rather than only on the run it
    came from: three episodes graded alike against one graded the other way.

    Measured on golden_ride_segment (four renders of the one real clip this suite
    carries, differing only in saturation/mid_blue — this fixture has no second
    camera to shoot four distinct episodes with):
        trio saturation=0.85            -> delta_c=-1.28, delta_h=-2.04
        trio saturation=0.88 mid_blue=1.02 -> delta_c=-0.48, delta_h=-1.69
        trio saturation=0.90 mid_blue=1.03 -> delta_c=-0.33, delta_h=-2.72
        odd  saturation=1.30 mid_blue=1.20 -> delta_c=+10.90, delta_h=+4.04
    trio-only spread: spread_c=0.95, spread_h=1.03, worst=1.03 (bar=5.0 -> PASS).
    trio+odd spread:  spread_c=12.18, spread_h=6.76, worst=12.18 (bar=5.0 -> FAIL).
    These are the fixture-side evidence for 5.0: a consistent trio lands well
    under it and one episode graded the other way lands well over it, the same
    shape (not the same numbers) as design §2.5's real-reel margin of 1.48
    below / 4.07 above.
    """
    src = str(golden_ride_segment)
    bar = ReelCheckSpec(target_dur=1.5).chroma_spread_max
    trio = [
        _chroma_reading(_md(src, saturation=0.85), src),
        _chroma_reading(_md(src, saturation=0.88, mid_blue=1.02), src),
        _chroma_reading(_md(src, saturation=0.90, mid_blue=1.03), src),
    ]
    odd_one_out = _chroma_reading(_md(src, saturation=1.30, mid_blue=1.20), src)
    print(f"\nMEASURED trio={trio} odd={odd_one_out}")

    cr_trio = _chroma_spread_check(trio, bar)
    print(f"MEASURED trio-only check: {cr_trio.detail}")
    assert cr_trio.passed is True, cr_trio.detail
    assert cr_trio.detail["worst"] < bar, cr_trio.detail

    cr_all = _chroma_spread_check(trio + [odd_one_out], bar)
    print(f"MEASURED trio+odd check: {cr_all.detail}")
    assert cr_all.passed is False, cr_all.detail
    assert cr_all.detail["worst"] > bar, cr_all.detail
