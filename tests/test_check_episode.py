"""Unit proofs for check_episode's grade description. Two numpy frame stacks are
all the advisory needs, so this needs no ffmpeg and does not carry the
integration marker. The real-bytes proof is tests/integration/test_color_fidelity.py.

Until 2026-09-16 the top of this file tested `_box_mean_rgb`, the pixel-box
reader the advisory used to sample a source clip and a delivered clip with. Both
that function and the two file decodes are gone: the description now means over
`regions.subject_mask`'s mask, on the (graded, plain) render pair `_grade_damage`
has already decoded. The straddling/out-of-frame box behaviour those tests pinned
is pinned by `tests/lib/test_regions.py` instead, and a box with no overlap now
contributes NO pixels rather than a fabricated edge sample.

The `grade_damage` section below (design 2026-08-31 §3) is a different shape —
it needs a real (graded, plain) RenderPlan pair, which needs a real manifest and
a real render, so it goes through `golden_ride_segment` + the committed
`tests/fixtures/golden_route.json` rather than a synthetic numpy frame.
"""
import numpy as np
import pytest

from scripts import check_episode, process_episode, reframe
from scripts.lib import color, geometry, regions
from scripts.lib import manifest as manifest_lib
from scripts.lib import orchestration as orch
from scripts.lib.models import CheckSpec, CropPath, Delivery, PathMeta, RoutePoint

N, H, W = 3, 40, 60


def _stacks(sub_plain=(10, 10, 10), sub_graded=(200, 10, 10),
            bg_plain=(60, 60, 60), bg_graded=(60, 60, 60)):
    """A plain/graded pair whose SUBJECT box moves and whose background does not."""
    plain = np.zeros((N, H, W, 3), np.uint8)
    graded = np.zeros((N, H, W, 3), np.uint8)
    plain[:] = bg_plain
    graded[:] = bg_graded
    plain[:, 10:30, 20:40] = sub_plain      # 20x20 of 40x60 = 16.7% of the frame
    graded[:, 10:30, 20:40] = sub_graded
    return list(plain), list(graded)


def _sidecar(box=(30.0, 20.0, 20.0, 20.0), src_w=60, src_h=40):
    """A route/path/meta trio that projects `box` onto the SAME rect the stacks
    paint, so the mask and the painted pixels agree by construction."""
    x, y, w, h = box
    route = [RoutePoint(t=t, x=x, y=y, w=w, h=h) for t in (0.0, 0.5, 1.0)]
    path = CropPath(xs=[0.0, 0.0, 0.0])
    meta = PathMeta(mode="fill", crop_w=src_w, crop_h=src_h, crop_y=0,
                    src_dims=(src_w, src_h), canvas=(W, H), out_dims=(W, H),
                    rect_px=(0, 0, W, H), freedom=0)
    return route, path, meta


def test_the_advisory_reads_the_subject_and_names_the_region_it_read():
    plain, graded = _stacks()
    route, path, meta = _sidecar()
    d = check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                              route, path, meta)
    assert d["region"] == "subject"
    assert d["region_fallback"] is None
    assert d["region_fraction"] == pytest.approx(0.1667, abs=5e-4)
    assert d["delta_e"] > 10          # (10,10,10) -> (200,10,10) is a large move
    assert d["samples"] == 3
    assert d["advisory_delta_e"] is True
    # plain -> graded, and NOT the other way round. The two stacks are positional,
    # and CIEDE2000's total is symmetric in magnitude — measured, a swapped call
    # returns the identical delta_e (40.34) with every signed component inverted
    # (delta_l 39.29 -> -39.29). The sign is the only assertion in this file that
    # can see that swap, which is the same inversion gradedamage.evaluate's
    # keyword-only signature exists to prevent.
    assert d["delta_l"] > 0


def test_the_advisory_reports_the_background_beside_the_subject():
    """The contamination check the folded backlog row is about: on a global grade
    the two agree, on a targeted one they do not (design §2.3)."""
    plain, graded = _stacks()
    route, path, meta = _sidecar()
    d = check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                              route, path, meta)
    # the background is painted identically on both sides — it did not move
    assert d["background_delta_e"] == 0.0
    assert d["delta_e"] > d["background_delta_e"]


def test_a_subject_under_the_floor_falls_back_to_the_crop_and_says_so():
    plain, graded = _stacks()
    # 4x4 of 40x60 = 0.17% of the frame, under regions.MIN_REGION_FRAC
    route, path, meta = _sidecar(box=(30.0, 20.0, 4.0, 4.0))
    d = check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                              route, path, meta)
    assert d["region"] == "crop"
    assert d["region_fallback"] == "too-small"
    assert d["region_fraction"] == pytest.approx(0.0067, abs=5e-4)
    # the fraction reported is the SUBJECT's, the evidence for the fallback —
    # never the crop's 1.0 it fell back to
    assert d["region_fraction"] < 0.01
    # BOTH keys, not just the number: after a fallback the reading IS the crop, so
    # there is no subject reading for a background to be contrasted with.
    assert "background_delta_e" not in d
    assert "background_fallback" not in d


def test_a_routeless_episode_reads_the_crop_and_names_no_route():
    """A pan has no subject. Today this reports delta_e: null; after this slice
    it reports a real crop reading with the absence named."""
    plain, graded = _stacks()
    _, path, meta = _sidecar()
    d = check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                              None, path, meta)
    assert d["region"] == "crop"
    assert d["region_fallback"] == "no-route"
    assert d["region_fraction"] == 0.0
    assert d["delta_e"] is not None
    assert "background_delta_e" not in d
    assert "background_fallback" not in d


def test_a_subject_covering_the_whole_frame_leaves_no_background_and_names_it():
    """The `~mask`-empty case. subject_mask clamps a projected bbox into the output
    frame, so a tight reframe ordinarily produces a subject that IS the frame —
    and then there is no background left to compare against.

    Until this was routed through regions.refuse the background arm called
    `.get("delta_e")` on evaluate's no-samples shape and emitted a bare `null`,
    which reads either as "the background did not move" or as an error. The
    absence is now named from regions.FALLBACKS, and no number is emitted at all."""
    plain, graded = _stacks()
    # centred, and exactly as large as the frame: fx0/fy0 project to 0.0 and
    # fx1/fy1 to 1.0, so the mask is every pixel of every frame
    route, path, meta = _sidecar(box=(30.0, 20.0, 60.0, 40.0))
    extents = geometry.extent_at_times(route, path, meta, [0.0, 0.5, 1.0])
    mask, frac = regions.subject_mask(extents, N, H, W)
    assert frac == 1.0 and not (~mask).any()      # the premise, stated not assumed

    d = check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                              route, path, meta)
    assert d["region"] == "subject"               # the subject itself is readable
    assert d["region_fallback"] is None
    assert d["region_fraction"] == 1.0
    assert d["delta_e"] > 10                      # ...and it carries a real number
    assert d["background_fallback"] == "too-small"
    assert d["background_fallback"] in regions.FALLBACKS
    assert "background_delta_e" not in d          # never a bare null


def test_a_subject_entirely_outside_the_frame_is_located_but_empty():
    """The `empty=True` branch of the located arm: a route EXISTS, and its box
    projects wholly outside the delivered frame, so the mask holds no pixels at a
    real, measured fraction of 0.0.

    `too-small` and not `no-route`: an episode that HAS a route must never be told
    it has none (regions.refuse's own docstring). Note the honest limit — at this
    call site `empty` is implied by `fraction`, since an empty mask means a
    fraction of exactly 0.0 and 0.0 is under MIN_REGION_FRAC anyway. What this
    test covers is the branch and its premise; what isolates the `empty` ARGUMENT
    from the area gate is tests/lib/test_regions.py's own refuse test."""
    plain, graded = _stacks()
    route, path, meta = _sidecar(box=(-100.0, 20.0, 20.0, 20.0))
    extents = geometry.extent_at_times(route, path, meta, [0.0, 0.5, 1.0])
    mask, frac = regions.subject_mask(extents, N, H, W)
    assert not mask.any() and frac == 0.0         # located, and holds no pixels

    d = check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                              route, path, meta)
    assert d["region"] == "crop"
    assert d["region_fallback"] == "too-small"    # NOT "no-route" — the route exists
    assert d["region_fraction"] == 0.0
    assert d["delta_e"] > 0                       # the crop still supplies a reading
    assert "background_delta_e" not in d
    assert "background_fallback" not in d


def test_the_advisory_refuses_two_stacks_of_different_shapes():
    """The two stacks are two renders of ONE plan pair — a disagreement is a
    caller error, not an input to broadcast over."""
    plain, graded = _stacks()
    route, path, meta = _sidecar()
    with pytest.raises(ValueError, match="same shape"):
        check_episode._subject_delta_advisory(plain[:2], graded, [0.0, 0.5, 1.0],
                                              route, path, meta)


def test_every_fallback_the_advisory_can_report_is_a_regions_name():
    """Three routes, three DIFFERENT answers — collected and compared as a set.

    Asserting `is None or in FALLBACKS` per iteration is satisfied by None on all
    three, so it would hold for an implementation that never refused anything and
    would not prove its own name."""
    plain, graded = _stacks()
    _, path, meta = _sidecar()
    seen = {check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                                  route, path, meta)["region_fallback"]
            for route in (None, _sidecar(box=(30.0, 20.0, 4.0, 4.0))[0], _sidecar()[0])}
    assert seen == {None, "no-route", "too-small"}
    assert seen - {None} <= set(regions.FALLBACKS)


# --- grade_damage (design 2026-08-31 §3): the entropy-ratio verdict, plans-gated ---
#
# `plans` is a real (graded, plain) RenderPlan pair — plan_frames_rgb decodes real
# ffmpeg bytes from them even in the tests below that stub gradedamage.evaluate, so
# a synthetic numpy frame (this file's usual style, above) cannot stand in for one.
# Built the same way process_episode will build it once Task 5 wires it through:
# process_episode.plan_for/plan_ungraded against a real manifest and the suite's
# own committed golden_ride_segment + golden_route.json (the same pair
# tests/lib/test_process_episode_plans.py and
# tests/integration/test_grade_sensor_calibration.py already build plans from).

_GOLDEN_ROUTE = "tests/fixtures/golden_route.json"


def _fake_manifest(src: str) -> dict:
    """Same shape as test_process_episode_plans.py's _md() — a real colour block
    (saturation/black_point) so plan_for's graded plan and plan_ungraded's plain
    plan actually differ, which is the damage sensor's whole premise."""
    return {"segment": src, "out_path": "/tmp/ep.mp4", "target_dur": 1.5,
            "composition": "center", "grid": "thirds", "layout": "fill",
            "canvas": [9, 16], "delivery": "short_edge:480",
            "saturation": 0.8, "black_point": 0.1}


def _fake_plans(golden_ride_segment):
    """A (graded, plain) RenderPlan pair, real and renderable against
    golden_ride_segment — see the section banner above for why."""
    src = str(golden_ride_segment)
    md = _fake_manifest(src)
    return (process_episode.plan_for(md, src, _GOLDEN_ROUTE),
            process_episode.plan_ungraded(md, src, _GOLDEN_ROUTE))


def _run_check_episode(tmp_path, monkeypatch, golden_ride_segment, plans):
    """One real episode — golden_ride_segment + golden_route.json, rendered for
    real through reframe.reframe (mirrors
    tests/integration/test_color_fidelity.py's _render_episode) — then checked by
    check_episode.run, with `plans` threaded through as the grade_damage
    ingredient. `monkeypatch` is accepted (unused here) for symmetry with the
    caller, which patches scripts.lib.gradedamage.evaluate BEFORE calling this,
    not from inside it.

    A REAL render, not a hand-built sidecar: the route/path.json/path.meta.json
    it produces must agree with `source` (golden_ride_segment itself — the exact
    file `plans` was built against) for extent_at_times' projection, and for
    plan_frames_rgb's decode, to mean anything.
    """
    del monkeypatch
    src = str(golden_ride_segment)
    md = _fake_manifest(src)
    rspec = process_episode.build_reframe_spec(
        manifest_lib.Manifest.from_dict(md), Delivery.from_spec(md["delivery"]),
        dict(orch.DEFAULT_PARAMS))
    clip = str(tmp_path / "ep.mp4")
    reframe.reframe(rspec, src, _GOLDEN_ROUTE, clip, str(tmp_path / "path.json"))
    spec = CheckSpec(composition="center", grid="thirds", target_dur=1.5)
    return check_episode.run(clip, _GOLDEN_ROUTE, str(tmp_path / "path.json"), spec,
                             str(tmp_path / "report.json"), source=src, plans=plans)


def test_grade_damage_is_not_checked_without_plans(tmp_path, monkeypatch, golden_ride_segment):
    """Same shape `source` already uses: absent input reports absent, never a
    clean pass, and never blocks."""
    rep = _run_check_episode(tmp_path, monkeypatch, golden_ride_segment, plans=None)
    d = rep.checks["grade_damage"]
    assert d.passed is None
    assert d.detail["status"] == "not-checked"
    assert "color_fidelity" not in rep.checks


def test_grade_damage_blocks_when_the_ratio_is_below_the_floor(tmp_path, monkeypatch,
                                                               golden_ride_segment):
    # NOTE: the brief's stub used positional-looking names (p, g, floor); _grade_damage
    # calls gradedamage.evaluate with KEYWORD arguments (plain=, graded=, floor=) —
    # deliberately, per gradedamage.evaluate's own keyword-only signature — so the
    # stub's parameter names must match those keywords or the call raises TypeError
    # before ever reaching this stub.
    monkeypatch.setattr(check_episode.gradedamage, "evaluate",
                        lambda plain, graded, floor: {"ratio": 0.80, "plain_bits": 7.0,
                                                       "graded_bits": 5.6, "floor": floor,
                                                       "frames": 3, "below": True})
    rep = _run_check_episode(tmp_path, monkeypatch, golden_ride_segment,
                             plans=_fake_plans(golden_ride_segment))
    assert rep.checks["grade_damage"].passed is False
    assert "grade_damage" in rep.fail_reasons


def test_the_subject_dE00_survives_as_an_advisory_number(tmp_path, monkeypatch,
                                                          golden_ride_segment):
    """It is a good DESCRIPTION of what a grade did and the QC judge reads it. It
    is not a gate: a conductor pair puts 5 of 8 real episodes over the old 5.0
    ceiling and none of them is damage (design §0.1).

    Since 2026-09-16 it also names the pixels it read. `samples` is `color.FRAMES`
    and not the 5 this asserted before: the description rides `_grade_damage`'s
    own (graded, plain) pair, which is decoded at `color.sample_times(dur)` — the
    five route-span fractions of the deleted `SAMPLE_FRACS` are gone with the two
    decodes they indexed. Read off the constant rather than retyped, so a re-tune
    of the pair's own count does not leave a stale literal here."""
    rep = _run_check_episode(tmp_path, monkeypatch, golden_ride_segment,
                             plans=_fake_plans(golden_ride_segment))
    d = rep.checks["grade_damage"].detail
    assert "delta_e" in d and "delta_l" in d and "delta_c" in d and "delta_h" in d
    assert d["advisory_delta_e"] is True
    assert d["samples"] == color.FRAMES == 3
    # The provenance the number is attributed to. golden_route.json's box averages
    # ~1.5% of the delivered crop — above regions.MIN_REGION_FRAC, so the subject
    # itself supplies the reading and the background rides along beside it.
    assert d["region"] == "subject"
    assert d["region_fallback"] is None
    assert d["region_fraction"] > regions.MIN_REGION_FRAC
    assert d["background_fallback"] is None
    assert "background_delta_e" in d
