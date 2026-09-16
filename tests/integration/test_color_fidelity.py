"""Real-ffmpeg proof for the subject grade-delta ADVISORY (design 2026-08-28 §2,
demoted from a blocking dE00 gate to a description of check_episode.grade_damage
2026-08-31 §3, re-based onto grade_damage's own render pair and given a NAMED
region 2026-09-16 §2.2/§2.1).

What changed here on 2026-09-16: the advisory no longer takes two file paths and
decodes them. It takes two RGB frame stacks of ONE shape — the (graded, plain)
pair `_grade_damage` has already rendered — and resolves the pixels it means over
through `regions.subject_mask`/`regions.refuse`, the same resolver the tone stage
authors a grade with. So every test below hands it arrays: either
`reframe.plan_frames_rgb` over a real RenderPlan (the production shape), or
`assembly.frames_rgb` over two real clips rendered at the SAME dimensions (the
synthetic hue family, kept from the old file because a hue rotation is not a
grade this pipeline can author and it is still the cleanest large-move control).

Fixture shape, unchanged in recipe: a coloured subject box on a dark-grey field,
cropped by `crop=480:360:80:0` — a non-trivial x offset, not an identity
pass-through, so the route/path/meta sidecar's `geometry.extent_at_times`
projection is genuinely exercised. `plain.mp4` is that crop with no colour
operation; `gentle.mp4` adds `hue=h=4`; `broken.mp4` adds `hue=h=120`.

One recipe change: `-color_range tv`, so the clips satisfy the 0.3.1 segment
range contract `color.refuse_ungradeable_plane` enforces at `plan_render`.
"""
import json
from pathlib import Path

import pytest
from scripts import check_episode, color_measure, process_episode, reframe
from scripts.lib import assembly, color, ffbin, geometry, proc, regions
from scripts.lib import manifest as manifest_lib
from scripts.lib import orchestration as orch
from scripts.lib.models import (CheckSpec, CropPath, Delivery, LayoutSpec, PathMeta,
                                ReframeSpec, route_from_json)

pytestmark = pytest.mark.integration

W, H = 640, 360                      # source dims
BOX = (220, 100, 200, 160)           # x0, y0, w, h of the colour box in the source
SUBJECT_COLOR = "0xC85028"           # RGB (200, 80, 40) — saturated orange, hue ~15°
DUR = 2.0

# The "graded" clips are a real crop of the source: 480x360 starting at x=80 —
# freedom = 640 - 480 = 160, a non-zero crop offset so the sidecar's projection
# genuinely has to place the subject, not just echo an identity mapping.
CROP_W, CROP_X = 480, 80

# Subject sample box in SOURCE px (centre-format, matching a route point): a
# margin inside the box's own edges so the sampled mean never touches the
# overlay's crisp edge / the grey field beyond it.
SUBJECT_X, SUBJECT_Y = BOX[0] + BOX[2] / 2, BOX[1] + BOX[3] / 2   # 320, 180
SUBJECT_W, SUBJECT_H = 160.0, 120.0


def _render(path, crop: bool, hue: float | None) -> None:
    bg = f"color=c=0x303030:s={W}x{H}:d={DUR}:r=30"
    box = f"color=c={SUBJECT_COLOR}:s={BOX[2]}x{BOX[3]}:d={DUR}:r=30"
    graph = f"[0][1]overlay=x={BOX[0]}:y={BOX[1]}"
    if crop:
        graph += f",crop={CROP_W}:360:{CROP_X}:0"
    if hue is not None:
        graph += f",hue=h={hue}"
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i", bg, "-f", "lavfi", "-i", box,
              "-filter_complex", graph, "-t", str(DUR), "-pix_fmt", "yuv420p",
              "-color_range", "tv", str(path)])


@pytest.fixture(scope="module")
def source_clip(tmp_path_factory):
    """The uncropped field — the pre-grade segment an episode is rendered FROM."""
    p = tmp_path_factory.mktemp("cf") / "source.mp4"
    _render(p, crop=False, hue=None)
    return p


@pytest.fixture(scope="module")
def plain_clip(tmp_path_factory):
    """The crop with no colour operation — the PLAIN half of every pair below."""
    p = tmp_path_factory.mktemp("cf") / "plain.mp4"
    _render(p, crop=True, hue=None)
    return p


@pytest.fixture(scope="module")
def plain_twin_clip(tmp_path_factory):
    """A SECOND render of `plain_clip`'s identical recipe, to its own file.

    The faithful pair below needs two independently encoded and independently
    decoded stacks. Handing one decode's list object in as both halves would make
    every pair reaching evaluate an (x, x) — a tautology that reads 0.0 for any
    implementation that subtracts at all, whatever the fixture, the mask or the
    baseline do."""
    p = tmp_path_factory.mktemp("cf") / "plain_twin.mp4"
    _render(p, crop=True, hue=None)
    return p


@pytest.fixture(scope="module")
def gentle_clip(tmp_path_factory):
    """The same crop plus a 4° hue rotation — a real but small colour move.

    It exists to give the factor-of-three comparison in
    test_a_hue_broken_pair_reads_large_over_the_subject a non-zero denominator:
    a pair that carries NO colour change now reads exactly 0.0 (both sides share
    one baseline — design §0.3's whole point), and a ratio against zero states
    nothing."""
    p = tmp_path_factory.mktemp("cf") / "gentle.mp4"
    _render(p, crop=True, hue=4)
    return p


@pytest.fixture(scope="module")
def broken_clip(tmp_path_factory):
    """Cropped + a strong hue rotation — the deliberately hue-broken grade."""
    p = tmp_path_factory.mktemp("cf") / "broken.mp4"
    _render(p, crop=True, hue=120)
    return p


TIMES = [0.4, 1.0, 1.6]


def _frames(clip) -> list:
    """The clip's own pixels at TIMES, at its own resolution. Every pair fed to
    the advisory is read this way, so both halves share a shape by construction —
    which is what the advisory now refuses a violation of."""
    return assembly.frames_rgb(str(clip), TIMES, assembly.probe_stream(str(clip)).fps)


def _sidecar(tmp_path, box=(SUBJECT_X, SUBJECT_Y, SUBJECT_W, SUBJECT_H)):
    """The (route_pts, CropPath, PathMeta) trio the advisory takes, written to
    disk and read back through the production readers rather than constructed —
    so a sidecar this suite could not actually load would fail here.

    A STATIC subject and a STATIC crop offset (path is constant CROP_X); the crop
    is real (CROP_X=80 != 0), so extent_at_times must actually place the subject
    rather than vacuously echoing the source box."""
    x, y, w, h = box
    n = 5
    route = [dict(t=round(0.2 + i * 1.6 / (n - 1), 3), x=x, y=y, w=w, h=h)
             for i in range(n)]
    (tmp_path / "route.json").write_text(json.dumps(route))
    (tmp_path / "path.json").write_text(json.dumps([CROP_X] * n))
    PathMeta(mode="fill", crop_w=CROP_W, crop_h=H, crop_y=0, src_dims=(W, H),
             canvas=(CROP_W, H), out_dims=(CROP_W, H), rect_px=(0, 0, CROP_W, H),
             freedom=W - CROP_W).write(tmp_path / "path.meta.json")
    rp, pp = str(tmp_path / "route.json"), str(tmp_path / "path.json")
    return (route_from_json(rp), CropPath.from_json(pp),
            PathMeta.from_json(Path(pp).with_suffix(".meta.json")))


# --- 1/2: what the reading says over a real subject, and what separates the two -

def test_a_faithful_pair_reads_zero_over_the_subject(tmp_path, plain_clip,
                                                    plain_twin_clip):
    """TWO clips, rendered and encoded separately through one recipe and decoded
    separately — a real pair carrying no colour change, not one stack handed in
    twice. The reading is then not merely small, it is EXACTLY zero, which is the
    design's own consequence of putting both sides on one baseline (§0.3). Before
    2026-09-16 this same claim read ~0.8 on this fixture: the old sensor compared
    a pre-grade source against a CRF-18 clip, so the encode's own residual was
    inside every number it reported.

    The provenance is the other half of the claim: the number is attributed to
    the SUBJECT, at the fraction it actually covers, with no fallback."""
    route_pts, path_obj, meta = _sidecar(tmp_path)
    plain, twin = _frames(plain_clip), _frames(plain_twin_clip)
    assert plain is not twin                  # two decodes, not one list reused
    d = check_episode._subject_delta_advisory(plain, twin, TIMES,
                                              route_pts, path_obj, meta)
    assert d["advisory_delta_e"] is True
    assert d["region"] == "subject"
    assert d["region_fallback"] is None
    assert d["delta_e"] == 0.0
    assert d["samples"] == 3
    # 160x120 of 480x360 — the mask is strictly inside the painted box, so it
    # reads pure SUBJECT_COLOR and nothing of the grey field.
    assert d["region_fraction"] == pytest.approx(0.1111, abs=5e-4)
    assert d["background_fallback"] is None
    assert d["background_delta_e"] == 0.0


def test_a_hue_broken_pair_reads_large_over_the_subject(tmp_path, plain_clip,
                                                        gentle_clip, broken_clip):
    """The control for the faithful pair, on the SAME fixture and the SAME knob at
    two magnitudes — so this cannot pass merely because the sensor always reads
    large.

    The factor-of-three is measured against `gentle` (hue=h=4), not against the
    faithful pair: the faithful pair reads exactly 0.0 and a ratio against zero
    states nothing. gentle is a real colour move of the same kind, three orders of
    rotation smaller."""
    route_pts, path_obj, meta = _sidecar(tmp_path)
    plain = _frames(plain_clip)
    gentle = check_episode._subject_delta_advisory(plain, _frames(gentle_clip), TIMES,
                                                   route_pts, path_obj, meta)
    broken = check_episode._subject_delta_advisory(plain, _frames(broken_clip), TIMES,
                                                   route_pts, path_obj, meta)
    print(f"\nMEASURED hue advisory: gentle={gentle['delta_e']} broken={broken['delta_e']}")
    assert broken["region"] == "subject" and broken["region_fallback"] is None
    assert broken["delta_e"] > 20.0            # hue=h=120 on a saturated orange
    assert broken["delta_h"] > 50.0            # the rotation shows up as a hue component
    assert gentle["delta_e"] > 0.0             # the denominator is real, not zero
    assert broken["delta_e"] > 3.0 * gentle["delta_e"]
    # The background moved too — a hue rotation is global — but the two are
    # reported as two numbers, which is what makes a TARGETED grade visible.
    assert broken["background_fallback"] is None
    assert broken["background_delta_e"] > 0.0


# --- 3: the subject the resolver refuses to read ------------------------------

def test_a_subject_under_the_floor_falls_back_to_the_crop_and_says_so(tmp_path,
                                                                      plain_clip,
                                                                      broken_clip):
    """design §0.2: the region choice is worth the most exactly where the region
    is least trustworthy. A 12x12 box is 0.083% of this 480x360 crop, an order
    under regions.MIN_REGION_FRAC — so the reading comes from the crop, says so,
    reports the SUBJECT's own fraction as the evidence, and drops
    `background_delta_e`, which after a fallback would be a second name for the
    number already reported."""
    route_pts, path_obj, meta = _sidecar(
        tmp_path, box=(SUBJECT_X, SUBJECT_Y, 12.0, 12.0))
    d = check_episode._subject_delta_advisory(_frames(plain_clip), _frames(broken_clip),
                                              TIMES, route_pts, path_obj, meta)
    assert d["region"] == "crop"
    assert d["region_fallback"] == "too-small"
    assert d["region_fallback"] in regions.FALLBACKS
    assert d["region_fraction"] < regions.MIN_REGION_FRAC
    assert d["region_fraction"] == pytest.approx(0.00083, abs=5e-5)
    assert d["delta_e"] > 0.0
    assert "background_delta_e" not in d
    assert "background_fallback" not in d


# --- 4/6: the wired path — what run() reports, and which frames it reads -------

_GOLDEN_ROUTE = "tests/fixtures/golden_route.json"


def _episode_md(src: str, out: str, **extra) -> dict:
    md = {"segment": src, "out_path": out, "target_dur": 1.5,
          "composition": "center", "grid": "thirds", "layout": "fill",
          "canvas": [9, 16], "delivery": "short_edge:480"}
    md.update(extra)
    return md


def _run_episode(tmp_path, src: str, md: dict):
    """Render `md` for real and check it with the (graded, plain) pair
    process_episode builds — the whole wired path, not the sensor in isolation."""
    d = tmp_path / "ep"
    d.mkdir(parents=True, exist_ok=True)
    clip = str(d / "ep.mp4")
    spec = process_episode.build_reframe_spec(
        manifest_lib.Manifest.from_dict(md), Delivery.from_spec(md["delivery"]),
        dict(orch.DEFAULT_PARAMS))
    reframe.reframe(spec, src, _GOLDEN_ROUTE, clip, str(d / "path.json"))
    plans = (process_episode.plan_for(md, src, _GOLDEN_ROUTE),
             process_episode.plan_ungraded(md, src, _GOLDEN_ROUTE))
    cspec = CheckSpec(composition="center", grid="thirds", target_dur=md["target_dur"])
    return check_episode.run(clip, _GOLDEN_ROUTE, str(d / "path.json"), cspec,
                             str(d / "report.json"), source=src, plans=plans)


def test_run_carries_the_region_and_the_description_does_not_vote(tmp_path,
                                                                  golden_ride_segment):
    """design §1.1 and §2.3, end to end. The `grade_damage` detail must carry the
    three provenance fields, and `passed` must be the entropy ratio's verdict
    ALONE — asserted on an episode whose `delta_e` is large enough that the OLD
    5.0 dE00 ceiling would have stopped it.

    The tone pair is conductor-shaped (this crop's own measured profile, uniformly
    lifted 30 luma units): the same recipe
    test_grade_sensor_references.py's proof 1 measures at ratio 0.977 / delta_e
    9.63 on this fixture, chosen there because a uniform translation costs a
    whole-frame entropy statistic almost nothing while still moving the tracked
    subject's own colour past the old bar."""
    src = str(golden_ride_segment)
    base = _episode_md(src, str(tmp_path / "unused.mp4"))
    prof, _ = color_measure.measure_crop(base, src, _GOLDEN_ROUTE)
    md = dict(base, tone_src=list(prof), tone_dst=[round(v + 30, 1) for v in prof])
    report = _run_episode(tmp_path, src, md)
    gd = report.checks["grade_damage"]
    print(f"\nMEASURED run() grade_damage: {gd.detail}")
    # The deterministic answer for golden_route.json, not the set of legal values:
    # an implementation that lost the route on the WIRED path and reported crop /
    # 0.0 / "no-route" for every routed episode would satisfy a presence check.
    assert gd.detail["region"] == "subject", gd.detail
    assert gd.detail["region_fallback"] is None, gd.detail
    assert gd.detail["region_fraction"] > regions.MIN_REGION_FRAC, gd.detail
    # The description is large — the old gate would have blocked here...
    assert gd.detail["delta_e"] > 5.0, gd.detail
    # ...and the verdict comes from the entropy ratio, which is healthy.
    assert gd.detail["below"] is False, gd.detail
    assert gd.passed is True, gd.detail
    assert report.overall is True, report.fail_reasons


def test_the_advisory_reads_the_frames_grade_damage_already_decoded(
        tmp_path, monkeypatch, golden_ride_segment):
    """design §4 proof 3, by identity and not by equality: the two stacks the
    advisory receives must BE the objects `reframe.plan_frames_rgb` returned, not
    equal copies a second decode produced. Two renders of one plan are
    byte-identical, so an equality assertion here would pass against exactly the
    duplicate decode this slice deleted."""
    rendered, seen = [], {}
    real = check_episode.reframe.plan_frames_rgb

    def _record_render(plan, src, times):
        out = real(plan, src, times)
        rendered.append(out)
        return out

    def _record_advisory(plain_frames, graded_frames, times, *a, **k):
        seen["plain"], seen["graded"] = plain_frames, graded_frames
        return {"advisory_delta_e": True}

    monkeypatch.setattr(check_episode.reframe, "plan_frames_rgb", _record_render)
    monkeypatch.setattr(check_episode, "_subject_delta_advisory", _record_advisory)
    src = str(golden_ride_segment)
    _run_episode(tmp_path, src, _episode_md(src, str(tmp_path / "unused.mp4"),
                                            saturation=0.8, black_point=0.1))
    assert len(rendered) == 2, rendered          # graded, then plain — exactly two
    assert seen["graded"] is rendered[0]
    assert seen["plain"] is rendered[1]


# --- 5: the reading rides the pair — no subprocess of its own ------------------

def test_the_advisory_issues_no_subprocess_of_its_own(tmp_path, monkeypatch,
                                                      plain_clip, broken_clip):
    """design §4 proof 3's other half. The old path called ffprobe four times and
    ffmpeg twice from inside this function; the new one is pure numpy over frames
    it was handed. Decoding happens BEFORE the patch, so a reading that comes back
    at all is proof that nothing under it shelled out."""
    route_pts, path_obj, meta = _sidecar(tmp_path)
    plain, graded = _frames(plain_clip), _frames(broken_clip)

    def _boom(*a, **k):
        raise AssertionError(f"the advisory shelled out: {a[0] if a else k}")

    monkeypatch.setattr(proc, "run", _boom)
    d = check_episode._subject_delta_advisory(plain, graded, TIMES,
                                              route_pts, path_obj, meta)
    assert d["delta_e"] > 20.0
    assert d["region"] == "subject"


# --- 7: ONE resolver, two readers ---------------------------------------------

def test_one_resolver_two_readers_agree_on_the_same_fraction(tmp_path, source_clip):
    """design §4 proof 2. The tone stage (regions.assemble, through
    color_measure.measure_crop) and the grade description must refuse the SAME
    subject for the SAME reason at the SAME fraction — that equality is the whole
    claim of lifting `subject_mask`/`refuse` out of `regions.measure`.

    A shared threshold is not the claim: two readers could both say `too-small`
    from two different fractions and the report would still mislead about which
    box was refused. So the fractions are compared, not merely the verdicts."""
    src = str(source_clip)
    route = tmp_path / "tiny_route.json"
    # 10x10 px on a 640x360 frame — under MIN_REGION_FRAC by two orders whatever
    # the delivered crop turns out to be.
    route.write_text(json.dumps(
        [dict(t=round(i * 0.4, 3), x=SUBJECT_X, y=SUBJECT_Y, w=10.0, h=10.0)
         for i in range(5)]))
    md = _episode_md(src, str(tmp_path / "unused.mp4"), target_dur=1.6)

    decl = regions.Regions.from_dict(
        {"anchors": [{"anchor": "toe", "name": "wetsuit", "of": "subject"}]})
    _, rows = color_measure.measure_crop(md, src, str(route), decl=decl)

    plan, path_obj, meta = process_episode.plan_and_meta_ungraded(md, src, str(route))
    times = color.sample_times(plan.dur)
    frames = reframe.plan_frames_rgb(plan, src, times)
    d = check_episode._subject_delta_advisory(frames, frames, times,
                                              route_from_json(str(route)), path_obj, meta)

    assert rows[0].of == "subject" and rows[0].used == "crop"
    assert rows[0].fallback == "too-small" == d["region_fallback"]
    assert d["region"] == "crop"
    assert round(rows[0].fraction, 4) == d["region_fraction"]
    # The reported field is rounded to 4 places, and on a fraction this small that
    # is two significant figures — enough to mislead. So the same claim again at
    # full precision, against the resolver the advisory itself calls: one mask
    # rule, one number, no `approx`.
    extents = geometry.extent_at_times(route_from_json(str(route)), path_obj,
                                       meta, times)
    _, exact = regions.subject_mask(extents, len(times), plan.rl.out_h, plan.rl.out_w)
    assert exact == rows[0].fraction
    print(f"\nMEASURED shared fraction: tone={rows[0].fraction} advisory={d['region_fraction']}")


# --- A REAL authored grade must clear the bar (final review M-7) ---------------
#
# design §2.4's live control is ep1's authored tone pair [20, 135.4, 255] ->
# [20, 146, 255]: a +10.6-code lift of the MID anchor with the toe and the
# shoulder held, landing at ΔE00 1.44. TONE_LIFT reproduces that magnitude and
# that shape on this fixture's own measured profile, so the control is a real
# `match-grade`-shaped pair rather than a number chosen to pass.
GRADE_W, GRADE_H = 1920, 1080
GRADE_DUR = 3.0
# A gradient field, not a flat one: a flat frame has no p5/p50/p95 to carry, and
# `tone_arg` interpolates BETWEEN its anchors — a fixture with three levels would
# only ever exercise the anchors themselves. Measured on these exact bytes,
# color_measure.measure_profile reads (77, 161, 217).
GRADE_PROFILE = (77.0, 161.0, 217.0)
TONE_LIFT = 10.6
GRADE_SUBJECT = (760, 380, 400, 320)          # x, y, w, h in source px
GRADE_SUBJECT_COLOR = "0x8A6E5A"              # (138, 110, 90) — a mid, warm, skin-ish tone,
                                              # deliberately BETWEEN p5 and p50 so the transfer
                                              # is interpolating over it, not pinned at an anchor


@pytest.fixture(scope="module")
def graded_source(tmp_path_factory):
    """The pre-grade segment: a mid-tone subject over a luma gradient, tv range."""
    p = tmp_path_factory.mktemp("cfg") / "segment.mp4"
    bg = (f"gradients=s={GRADE_W}x{GRADE_H}:c0=0x101010:c1=0xD8D8D8:d={GRADE_DUR}:r=30"
          f":x0=0:y0=0:x1={GRADE_W}:y1={GRADE_H}")
    box = f"color=c={GRADE_SUBJECT_COLOR}:s={GRADE_SUBJECT[2]}x{GRADE_SUBJECT[3]}:d={GRADE_DUR}:r=30"
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i", bg, "-f", "lavfi", "-i", box,
              "-filter_complex", f"[0][1]overlay=x={GRADE_SUBJECT[0]}:y={GRADE_SUBJECT[1]}",
              "-t", str(GRADE_DUR), "-pix_fmt", "yuv420p", "-color_range", "tv", str(p)])
    return p


def _grade_route(tmp_path):
    cx = GRADE_SUBJECT[0] + GRADE_SUBJECT[2] / 2
    cy = GRADE_SUBJECT[1] + GRADE_SUBJECT[3] / 2
    route = [dict(t=round(i / 10, 3), x=cx, y=cy, w=260.0, h=220.0) for i in range(30)]
    rp = tmp_path / "route.json"
    rp.write_text(json.dumps(route))
    return str(rp)


def _episode_spec(tone) -> ReframeSpec:
    """color_means is color.TARGET, so gains_for_means returns (1, 1, 1) and the
    mixer is an identity — a tone pair, when given, is then the ONLY colour
    operation in the chain. Factored out so the test can build a RenderPlan from
    the exact same spec _render_episode renders, without a second render."""
    return ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=tuple(float(v) for v in color.TARGET),
                       delivery=Delivery("native"), layout=LayoutSpec(mode="fill"),
                       tone_src=tone[0] if tone else None, tone_dst=tone[1] if tone else None)


def _render_episode(src, route_path, out_dir, tone, plans=None):
    """One real episode through reframe.reframe, with or without an authored tone
    pair, then checked with `plans` threaded through as grade_damage's ingredient
    (design 2026-08-31 §3) — None (the default) leaves it not-checked, exactly the
    shape `source` already had before plans existed."""
    out_dir.mkdir(parents=True, exist_ok=True)
    spec = _episode_spec(tone)
    clip = str(out_dir / "ep.mp4")
    reframe.reframe(spec, str(src), route_path, clip, str(out_dir / "path.json"))
    cspec = CheckSpec(composition="center", grid="thirds", target_dur=GRADE_DUR)
    report = check_episode.run(clip, route_path, str(out_dir / "path.json"), cspec,
                               str(out_dir / "report.json"), source=str(src), plans=plans)
    return spec, clip, report


def test_a_real_authored_grade_does_not_trip_the_entropy_gate(tmp_path, graded_source):
    """§2.4's live control, reproducible: a `match-grade`-shaped tone pair of ep1's own
    magnitude, rendered by reframe itself, must NOT read as damage.

    Renamed from '..._clears_the_blocking_bar': the bar that used to block here (median
    subject dE00 vs CheckSpec.grade_delta_max) is retired (design 2026-08-31 §3) because
    it could not tell a grade from damage — this proves the REPLACEMENT (the whole-frame
    luma-entropy ratio vs entropy_floor) also does not fire on a legitimate grade, using
    a real (graded, plain) RenderPlan pair built the same way process_episode builds one.

    The dE00 advisory rides along too. Since 2026-09-16 it is measured on THAT SAME
    pair, so the identity control's own reading is exactly 0.0 — both halves of its
    pair are the same identity plan — where the old source-vs-clip baseline read 0.79
    of pure encode residual. The authored grade's reading stays a real, non-zero
    number, which is what keeps the comparison below meaningful.

    The control is what stops this test being vacuous. A tone pair silently dropped
    from the chain would leave a passing episode and prove nothing, so the render is
    asserted to carry a real `lutyuv` transfer AND to differ in bytes from the
    identity render."""
    route_path = _grade_route(tmp_path)
    control_spec, control_clip, _ = _render_episode(
        graded_source, route_path, tmp_path / "control", None)
    control_plan = reframe.plan_render(control_spec, str(graded_source), route_path)

    tone = (GRADE_PROFILE, (GRADE_PROFILE[0], GRADE_PROFILE[1] + TONE_LIFT, GRADE_PROFILE[2]))
    graded_plan = reframe.plan_render(_episode_spec(tone), str(graded_source), route_path)
    spec, graded_clip, report = _render_episode(
        graded_source, route_path, tmp_path / "graded", tone,
        plans=(graded_plan, control_plan))

    # 1. The grade is real: a luma transfer in the chain, and different pixels out.
    plan = reframe.plan_render(spec, str(graded_source), route_path)
    assert "lutyuv" in plan.grade, plan.grade
    assert Path(graded_clip).read_bytes() != Path(control_clip).read_bytes()

    # 2. And the entropy gate does not fire — a +10.6-code lift of one anchor is
    #    movement, not destruction.
    gd = report.checks["grade_damage"]
    assert gd.passed is True, gd.detail
    assert gd.detail["below"] is False
    assert gd.detail["advisory_delta_e"] is True
    assert gd.detail["delta_e"] < 5.0          # still a small move in absolute terms
    assert gd.detail["delta_e"] > 0.0          # ...and a real one, not a dropped chain
    assert report.overall is True, report.fail_reasons

    # 3. The identity control reads a SMALLER advisory delta — exactly 0.0, since
    #    both halves of its pair are the same identity plan. Its own entropy ratio
    #    is 1.0 for the same reason, so it cannot be below the floor.
    control_report = check_episode.run(
        control_clip, route_path, str(tmp_path / "control" / "path.json"),
        CheckSpec(composition="center", grid="thirds", target_dur=GRADE_DUR),
        str(tmp_path / "control" / "report_with_plans.json"), source=str(graded_source),
        plans=(control_plan, control_plan))
    ccf = control_report.checks["grade_damage"]
    assert ccf.passed is True, ccf.detail
    assert ccf.detail["ratio"] == pytest.approx(1.0, abs=1e-3)
    assert ccf.detail["delta_e"] == 0.0
    assert ccf.detail["delta_e"] < gd.detail["delta_e"]
    assert control_report.overall is True, control_report.fail_reasons
