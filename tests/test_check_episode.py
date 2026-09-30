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

The last section is the CLI's (design 2026-09-30 §2.3): which bars `main` builds from
`--gates`, with the judge itself faked, so it needs neither ffmpeg nor a fixture.
"""
import json

import numpy as np
import pytest

from scripts import check_episode, process_episode, reframe
from scripts.lib import color, color_fidelity, geometry, regions
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
    """The located-and-holds-no-pixels case: a route EXISTS, and its box projects
    wholly outside the delivered frame, so the mask holds no pixels at a real,
    measured fraction of 0.0.

    `too-small` and not `no-route`: an episode that HAS a route must never be told
    it has none (regions.refuse's own docstring). The emptiness needs no separate
    input to be seen — the mask that holds no pixels IS the mask whose mean is
    0.0, and 0.0 is under MIN_REGION_FRAC. refuse() took a third `empty` argument
    for this until the slice's final review deleted it as undecidable at every
    production call site; this test is unchanged by that, because it drives the
    real array and never the argument."""
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


def test_a_subject_off_frame_for_one_sample_contributes_no_pair_for_that_frame():
    """`_region_pairs`'s own contract (its docstring): a frame whose mask slice
    holds no pixels contributes NO pair, never a fabricated one that would
    mean() an empty slice to NaN in silence.

    Task 7's mutation battery (row 12: dropping the `if not m.any(): continue`
    guard) found this untested — every other _subject_delta_advisory test in
    this file and in tests/integration/test_color_fidelity.py uses a STATIC
    route, so the mask is either empty in EVERY sampled frame (which routes
    through the fallback's all-True `read` and never reaches this branch at
    all) or non-empty in every one. Nothing exercised a mask that is empty in
    SOME frames and not others.

    A route that visits the painted subject box at t=0 and t=1.0 but swings far
    off-frame at t=0.5 does: the OVERALL fraction (pooled across all three
    frames) still clears regions.MIN_REGION_FRAC, so the subject reading is not
    the fallback and `_region_pairs` sees the real, mixed mask — one True frame,
    one all-False frame, one True frame."""
    plain, graded = _stacks()
    route = [RoutePoint(t=0.0, x=30.0, y=20.0, w=20.0, h=20.0),
             RoutePoint(t=0.5, x=-1000.0, y=20.0, w=20.0, h=20.0),
             RoutePoint(t=1.0, x=30.0, y=20.0, w=20.0, h=20.0)]
    path = CropPath(xs=[0.0, 0.0, 0.0])
    meta = PathMeta(mode="fill", crop_w=60, crop_h=40, crop_y=0, src_dims=(60, 40),
                    canvas=(W, H), out_dims=(W, H), rect_px=(0, 0, W, H), freedom=0)
    d = check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                              route, path, meta)
    assert d["region"] == "subject"          # the premise: NOT routed to the fallback
    assert d["region_fallback"] is None
    assert d["samples"] == 2                 # the off-frame sample contributed nothing


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


def test_a_subject_reading_also_carries_the_crops_own_displacement():
    """The reel-level check needs ONE pixel set every episode has. The subject is
    not it — it falls back by name — so a subject reading carries the crop's
    displacement alongside its own (design 2026-09-17 §2.2)."""
    out = _advisory_over_a_located_subject()          # helper below
    assert out["region"] == "subject"
    assert "crop_delta_c" in out and "crop_delta_h" in out
    assert isinstance(out["crop_delta_c"], float)
    assert isinstance(out["crop_delta_h"], float)


def test_a_crop_reading_does_not_repeat_itself_under_a_second_name():
    """When the subject fell back, delta_c/delta_h ALREADY are the crop's. A second
    key holding the same number is the contradiction surface 2026-09-16 §2.3
    refused for the background's fraction."""
    out = _advisory_over_a_refused_subject()          # helper below
    assert out["region"] == "crop"
    assert "crop_delta_c" not in out
    assert "crop_delta_h" not in out


def test_the_crops_displacement_is_the_whole_frame_not_the_background():
    """Not an approximation of the background reading: the crop is subject UNION
    background, and on a frame where the two differ the numbers must differ.

    Comparing only against the SUBJECT's own delta_c does not prove that: a
    build that read the BACKGROUND under the crop's name (`bg` instead of
    `whole` — the copy-paste one line above in the implementation) would also
    pass a bare `!= delta_c` check, because this fixture's background is
    unchanged between plain and graded (bg_plain == bg_graded), so a
    background-substituted crop reads exactly 0.0, and 0.0 != delta_c(subject)
    is still true. Asserting equality against an INDEPENDENTLY computed
    full-frame reading closes that hole, and also catches a `mask`-substituted
    build (which would read exactly delta_c(subject) instead)."""
    out, plain, graded = _advisory_over_a_located_subject_whose_subject_differs_from_its_background()
    assert out["region"] == "subject"
    p, g = np.asarray(plain), np.asarray(graded)
    whole = np.ones(g.shape[:3], dtype=bool)
    expected = color_fidelity.evaluate(check_episode._region_pairs(p, g, whole))
    assert out["crop_delta_c"] != 0.0
    assert out["crop_delta_c"] == expected["delta_c"]
    assert out["crop_delta_h"] == expected["delta_h"]
    assert out["crop_delta_c"] != out["delta_c"]


def test_a_subject_covering_the_whole_frame_still_carries_the_crops_displacement():
    """The crop's own displacement sits inside `if fallback is None:` ALONGSIDE
    the background arm, not nested inside `if out["background_fallback"] is
    None:` — an over-nesting mistake would still pass every other test in this
    file, because both other crop_delta_* fixtures have a subject at 16.7% of
    the frame and therefore a readable background. Same shape
    test_a_subject_covering_the_whole_frame_leaves_no_background_and_names_it
    builds: a subject that IS the whole frame, so region == "subject" but
    background_fallback is a name, not None (design 2026-09-17 §2.2)."""
    plain, graded = _stacks()
    # centred, and exactly as large as the frame: fx0/fy0 project to 0.0 and
    # fx1/fy1 to 1.0, so the mask is every pixel of every frame — the SAME box
    # test_a_subject_covering_the_whole_frame_leaves_no_background_and_names_it
    # uses, above.
    route, path, meta = _sidecar(box=(30.0, 20.0, 60.0, 40.0))
    out = check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                                 route, path, meta)
    assert out["region"] == "subject"
    assert out["background_fallback"] is not None
    assert out["background_fallback"] in regions.FALLBACKS
    assert "background_delta_e" not in out
    assert "crop_delta_c" in out and "crop_delta_h" in out
    assert isinstance(out["crop_delta_c"], float)
    assert isinstance(out["crop_delta_h"], float)


def _advisory_over_a_located_subject() -> dict:
    """A subject box comfortably over regions.MIN_REGION_FRAC — the ordinary,
    located case the crop's displacement is expected to ride alongside."""
    plain, graded = _stacks()
    route, path, meta = _sidecar()
    return check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                                  route, path, meta)


def _advisory_over_a_refused_subject() -> dict:
    """A subject box under regions.MIN_REGION_FRAC — the subject falls back to
    the crop, so `delta_c`/`delta_h` already ARE the crop's own."""
    plain, graded = _stacks()
    route, path, meta = _sidecar(box=(30.0, 20.0, 4.0, 4.0))
    return check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                                  route, path, meta)


def _advisory_over_a_located_subject_whose_subject_differs_from_its_background() -> tuple[dict, list, list]:
    """The default stacks already have this shape: the subject box takes a
    different colour from the rest of the frame in the GRADED stack only
    (sub_graded=(200,10,10) against an unchanged bg_graded=(60,60,60)), so the
    subject's chroma moves and the background's does not — the crop (subject
    UNION background) must then read a different displacement than the subject
    alone.

    Returns the raw stacks alongside the advisory's own dict: the caller needs
    them to compute an INDEPENDENT expectation for the crop's displacement
    (color_fidelity.evaluate over its own full-frame mask), not just an
    inequality against the subject's own delta_c."""
    plain, graded = _stacks()
    route, path, meta = _sidecar()
    out = check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                                 route, path, meta)
    return out, plain, graded


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


def _run_check_episode(tmp_path, monkeypatch, golden_ride_segment, plans, spec=None,
                       **run_kw):
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
    spec = spec or CheckSpec(composition="center", grid="thirds", target_dur=1.5)
    return check_episode.run(clip, _GOLDEN_ROUTE, str(tmp_path / "path.json"), spec,
                             str(tmp_path / "report.json"), source=src, plans=plans, **run_kw)


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


def test_a_region_that_refused_nothing_but_holds_no_pixels_is_a_contract_break(monkeypatch):
    """The advisory's ONLY absence shape is {status, reason}, and _grade_damage
    merges it flat into the verdict where `status` is the discriminator (design
    §0.1). It cannot happen: a crop read is the whole frame, and a subject read
    only runs when regions.refuse declined to refuse, which is the statement that
    the mask holds pixels. So a lying producer — a mask with no pixels reported at
    a fraction above MIN_REGION_FRAC — must RAISE here rather than describe itself
    as not-checked."""
    plain, graded = _stacks()
    route, path, meta = _sidecar()
    empty = np.zeros((N, H, W), dtype=bool)
    monkeypatch.setattr(regions, "subject_mask", lambda extents, n, h, w: (empty, 0.5))
    with pytest.raises(ValueError) as e:
        check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                              route, path, meta)
    msg = str(e.value)
    assert "subject" in msg                    # names the region it was reading
    assert "regions.subject_mask" in msg       # names where the break is
    assert "not-checked" in msg                # names the shape it refuses to emit


def test_an_ordinary_subject_read_still_carries_its_five_fidelity_keys():
    """The control for the refusal above: the guard must not fire on a real read."""
    plain, graded = _stacks()
    route, path, meta = _sidecar()
    d = check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                              route, path, meta)
    assert {"delta_e", "delta_l", "delta_c", "delta_h", "samples"} <= set(d)
    assert "status" not in d and "reason" not in d


def test_the_refusal_names_which_region_it_was_reading(monkeypatch):
    """Coverage hole found running the 2026-09-21 mutation battery, row 2:
    replacing the opening clause's `{'crop' if fallback else 'subject'}` with a
    bare "region" leaves `"subject" in msg` (the assertion two tests up) still
    true, because the word "subject" ALSO appears twice more in the message's
    fixed boilerplate — "a subject read only happens..." and
    "regions.subject_mask" — regardless of what the ternary says. That
    assertion is therefore blind to the one clause that actually commits to
    WHICH region broke contract; this test pins that clause by its exact
    opening phrase instead of by a substring the rest of the sentence already
    supplies for free."""
    plain, graded = _stacks()
    route, path, meta = _sidecar()
    empty = np.zeros((N, H, W), dtype=bool)
    monkeypatch.setattr(regions, "subject_mask", lambda extents, n, h, w: (empty, 0.5))
    with pytest.raises(ValueError, match="the subject read came back"):
        check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                              route, path, meta)


def test_the_verdict_is_read_from_the_verdict_not_from_the_merge(monkeypatch):
    """A flat merge puts the advisory second, so an advisory `status` overwrites
    into the dict the branch reads. Step 5 of Task 1 makes that shape impossible
    to produce; this pins that the BRANCH no longer depends on it, so a future
    advisory key cannot silently reopen the coupling (design §2.1).

    The stub is a lying advisory, not a reachable state — which is exactly why
    the assertion is about `passed`, and why this test would be meaningless if it
    also asserted the merged dict's keys."""
    monkeypatch.setattr(check_episode, "_subject_delta_advisory",
                        lambda *a, **k: {"status": "stubbed", "reason": "stubbed"})
    monkeypatch.setattr(check_episode.gradedamage, "evaluate",
                        lambda **k: {"ratio": 0.5, "plain_bits": 7.0, "graded_bits": 3.5,
                                     "floor": 0.9, "frames": 3, "below": True})
    monkeypatch.setattr(check_episode.reframe, "plan_frames_rgb",
                        lambda plan, src, times: list(np.zeros((3, 4, 4, 3), np.uint8)))
    route, path, meta = _sidecar()
    monkeypatch.setattr(check_episode.color, "sample_times", lambda dur, *a, **k: [0.0, 0.5, 1.0])

    class _Plan:
        dur = 1.0

    res = check_episode._grade_damage("src.mp4", (_Plan(), _Plan()), route, path, meta,
                                      CheckSpec(composition="center", grid="thirds",
                                                target_dur=1.5))
    assert res.passed is False          # the entropy verdict, not the advisory's status
    assert res.detail["below"] is True


# --- 2026-09-30 threshold surface Task 3: `--gates` on the standalone judge -----
# (design 2026-09-30 §2.3/§6.) A flag here and a convention in edl_to_reel, because this
# judge has no project.json to look beside.

def _judge_call(monkeypatch: pytest.MonkeyPatch, *argv: str) -> dict:
    """Run check_episode.main() over `argv` with the judge itself faked, and return what it
    was handed: {"spec": ..., "kw": {...}}. The clip, path and report never exist: what is under
    test is which bars the CLI built and which reasons it passed, and run() is the only thing
    that needs files."""
    seen = {}

    def fake_run(clip, route, path, spec, out, **kw):
        seen.update(spec=spec, kw=kw)
    monkeypatch.setattr(check_episode, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["check_episode", "c.mp4", "p.json", "o.json",
                                     "--target-dur", "3", *argv])
    check_episode.main()
    return seen


def _judge(monkeypatch: pytest.MonkeyPatch, *argv: str) -> CheckSpec:
    """The CheckSpec `main` would have judged against (see _judge_call)."""
    return _judge_call(monkeypatch, *argv)["spec"]


def test_the_gates_flag_moves_the_bar_the_standalone_judge_uses(tmp_path, monkeypatch):
    gates = tmp_path / "GATES.json"
    gates.write_text(json.dumps(
        {"black_floor": {"value": 2.0, "why": "night shoot, legitimately dark"}}))
    assert _judge(monkeypatch, "--gates", str(gates)) == CheckSpec(
        composition="lead", grid="thirds", target_dur=3.0, black_floor=2.0)


def test_without_the_gates_flag_every_bar_is_its_default(monkeypatch):
    """A control, green before `--gates` existed and the first test to drive `main()` at all:
    it pins that the flag is optional and that an absent flag builds the spec `main` built
    before this slice."""
    assert _judge(monkeypatch) == CheckSpec(composition="lead", grid="thirds", target_dur=3.0)


def test_an_empty_gates_path_is_refused_not_read_as_no_gates(monkeypatch):
    """`--gates ""` is what an unset shell variable produces, and reading it as "no gates"
    would put every authored bar back at its default in silence — the dropped-flag defect
    design §4 rejects per-threshold flags for."""
    with pytest.raises(OSError):
        _judge(monkeypatch, "--gates", "")


def test_a_gates_path_that_does_not_exist_is_refused_not_read_as_no_gates(tmp_path, monkeypatch):
    """"Absent means defaults" is true of the convention file beside project.json and must not
    leak onto an explicit flag: a typo'd path is the likeliest real silent revert. The empty-path
    test above cannot see a swallow of FileNotFoundError alone — `Path("")` is a directory."""
    with pytest.raises(FileNotFoundError):
        _judge(monkeypatch, "--gates", str(tmp_path / "GATE.json"))


def test_the_standalone_judge_never_goes_looking_for_a_gates_file(tmp_path, monkeypatch):
    """The flag-versus-convention asymmetry is deliberate (design §2.3, §6): this judge has no
    project.json to look beside, and guessing a file from the working directory would be a second,
    silent way to move a bar. A GATES.json sitting exactly where a lookup would try — the cwd, which
    is also beside the clip, path and report the relative argv names — changes nothing without
    the flag."""
    (tmp_path / "GATES.json").write_text(json.dumps(
        {"black_floor": {"value": 2.0, "why": "moves the bar if anything reads this file"}}))
    monkeypatch.chdir(tmp_path)
    assert _judge(monkeypatch) == CheckSpec(composition="lead", grid="thirds", target_dur=3.0)


def test_a_gates_file_the_loader_refuses_stops_the_judge_and_names_the_file(
        tmp_path, monkeypatch):
    gates = tmp_path / "GATES.json"
    gates.write_text(json.dumps({"black_floor": 2.0}))                 # a bare value: no reason
    with pytest.raises(ValueError) as e:
        _judge(monkeypatch, "--gates", str(gates))
    assert str(gates) in str(e.value)


# --- 2026-09-30 threshold surface Task 5: the reason rides the verdict it bought ---------
# (design §2.4 item 1.) The row has to be in the artifact that says PASS, which is report.json
# on disk — these read the file, because a row attached after report.write() is in memory only.

_BLACK_ROW = {"field": "black_floor", "value": 2.0, "default": 6.0,
              "why": "night shoot, legitimately dark"}
_ENTROPY_ROW = {"field": "entropy_floor", "value": 0.85, "default": 0.9,
                "why": "log profile; the ungraded render is already flat"}
_MOVED = {"black_floor": 2.0, "entropy_floor": 0.85}
_REASONS = {"black_floor": _BLACK_ROW["why"], "entropy_floor": _ENTROPY_ROW["why"]}


def _stub_damage_verdict(monkeypatch):
    """A damage verdict that EVALUATED (it carries the floor it judged by), so the run reaches
    grade_damage's judged arm without depending on what the golden footage's entropy is."""
    monkeypatch.setattr(check_episode.gradedamage, "evaluate",
                        lambda plain, graded, floor: {"ratio": 0.88, "plain_bits": 7.0,
                                                       "graded_bits": 6.2, "floor": floor,
                                                       "frames": 3, "below": 0.88 < floor})


def test_a_moved_bar_is_named_beside_each_episode_verdict_it_bought(
        tmp_path, monkeypatch, golden_ride_segment):
    """Both bars, through the real run, in the file on disk. The stubbed ratio is 0.88 — below
    the default 0.90 and above the authored 0.85 — so the damage verdict passes because the floor
    moved, which is the case the row exists for. `black_frames` is assigned before grade_damage
    and the pass is one call after both, so a call placed between them names one bar and not
    the other."""
    _stub_damage_verdict(monkeypatch)
    spec = CheckSpec(composition="center", grid="thirds", target_dur=1.5, **_MOVED)
    rep = _run_check_episode(tmp_path, monkeypatch, golden_ride_segment,
                             plans=_fake_plans(golden_ride_segment), spec=spec,
                             gate_reasons=_REASONS)
    assert rep.checks["grade_damage"].passed is True
    on_disk = json.loads((tmp_path / "report.json").read_text())["checks"]
    assert on_disk["black_frames"]["authored"] == [_BLACK_ROW]
    assert on_disk["grade_damage"]["authored"] == [_ENTROPY_ROW]


def test_the_standalone_judge_hands_the_reasons_to_the_run(tmp_path, monkeypatch):
    """check_episode.main is the third site a moved bar's reason has to leave from, and the
    easiest to miss: it holds a loaded Gates, and without g.reasons() here a `--gates` run
    writes a verdict with a moved bar and no reason beside it. The control is inside: with no
    flag the run is handed no reasons, so nothing is named."""
    gates = tmp_path / "GATES.json"
    gates.write_text(json.dumps({"black_floor": {"value": 2.0, "why": _BLACK_ROW["why"]}}))
    assert _judge_call(monkeypatch, "--gates", str(gates))["kw"] == {
        "gate_reasons": {"black_floor": _BLACK_ROW["why"]}}
    assert _judge_call(monkeypatch)["kw"] == {"gate_reasons": {}}
