"""Real-ffmpeg proof for the subject grade-delta ADVISORY (design 2026-08-28 §2,
demoted from a blocking dE00 gate to a description of check_episode.grade_damage
2026-08-31 §3 — see design §0.1: a grade IS movement, so a dE00 threshold could not
tell a grade from damage): real bytes through the batched `assembly.frames_rgb`
sampling (`check_episode._box_mean_rgb`) + evaluate (`color_fidelity.evaluate`) path,
driven directly through `check_episode._subject_delta_advisory` (the sampling body,
unchanged) where the check no longer needs a `plans` pair to exercise it, and through
`check_episode.run(..., source=, plans=)` where the whole grade_damage verdict matters.

Fixture shape: a coloured subject box on a dark-grey field (`source.mp4`), and
a "graded" clip that is a REAL crop of it (`crop=480:360:80:0` — a non-trivial
x offset, not an identity pass-through) so the route/path/meta sidecar's
`geometry.extent_at_times` projection is genuinely exercised, not vacuously
satisfied. `faithful.mp4` re-runs the identical recipe (no colour change);
`broken.mp4` adds a strong `hue=h=120` rotation after the crop — the
"simplest" grade-breaker the task names, verified empirically (see below) to
land the subject's median dE00 well past the old 5.0 `grade_delta_max` ceiling
(deleted 2026-08-31 §3) and any plausible grading move.

A SECOND fixture pair at the bottom of this file covers what those three could
not: a real authored `ReframeSpec` colour block rendered by `reframe.reframe`
itself. Neither a colour-identity re-encode nor a raw `hue=h=120` is a grade
this pipeline can actually author, and design §2.4's live control — ep1's
+10.6-code tone pair landing at 1.44 — had no reproducible form in CI. For a
gate that now stops episodes, that is the control worth having.
"""
import json
from pathlib import Path

import pytest
from scripts import check_episode, reframe
from scripts.lib import assembly, color, ffbin, proc
from scripts.lib.models import (CheckSpec, CropPath, Delivery, LayoutSpec, PathMeta,
                                ReframeSpec, route_from_json)

pytestmark = pytest.mark.integration

W, H = 640, 360                      # source dims
BOX = (220, 100, 200, 160)           # x0, y0, w, h of the colour box in the source
SUBJECT_COLOR = "0xC85028"           # RGB (200, 80, 40) — saturated orange, hue ~15°
DUR = 2.0

# A route's timestamps and the delivered clip's duration are independent facts —
# a trim or a retime changes one without rewriting the other. This route spans
# past DUR on purpose: SAMPLE_FRACS' top fraction (0.9) * ROUTE_OVERRUN_T (2.4)
# = 2.16s, past the ~1.967s last-decodable-frame boundary (DUR - 1/30fps) of a
# DUR=2.0s clip — the exact disagreement _last_sampleable_t's clamp exists for.
ROUTE_OVERRUN_T = 2.4

# The "graded" clip is a real crop of the source: 480x360 starting at x=80 —
# freedom = 640 - 480 = 160, a non-zero crop offset so the sidecar's projection
# genuinely has to place the subject, not just echo an identity mapping.
CROP_W, CROP_X = 480, 80

# Subject sample box in SOURCE px (centre-format, matching a route point): a
# margin inside the box's own edges so the sampled mean never touches the
# overlay's crisp edge / the grey field beyond it.
SUBJECT_X, SUBJECT_Y = BOX[0] + BOX[2] / 2, BOX[1] + BOX[3] / 2   # 320, 180
SUBJECT_W, SUBJECT_H = 160.0, 120.0


def _render(path, crop: bool, hue: bool) -> None:
    bg = f"color=c=0x303030:s={W}x{H}:d={DUR}:r=30"
    box = f"color=c={SUBJECT_COLOR}:s={BOX[2]}x{BOX[3]}:d={DUR}:r=30"
    graph = f"[0][1]overlay=x={BOX[0]}:y={BOX[1]}"
    if crop:
        graph += f",crop={CROP_W}:360:{CROP_X}:0"
    if hue:
        graph += ",hue=h=120"
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i", bg, "-f", "lavfi", "-i", box,
              "-filter_complex", graph, "-t", str(DUR), "-pix_fmt", "yuv420p", str(path)])


@pytest.fixture(scope="module")
def source_clip(tmp_path_factory):
    p = tmp_path_factory.mktemp("cf") / "source.mp4"
    _render(p, crop=False, hue=False)
    return p


@pytest.fixture(scope="module")
def faithful_clip(tmp_path_factory):
    """The same recipe, cropped only — a "grade" that changed nothing."""
    p = tmp_path_factory.mktemp("cf") / "faithful.mp4"
    _render(p, crop=True, hue=False)
    return p


@pytest.fixture(scope="module")
def broken_clip(tmp_path_factory):
    """Cropped + a strong hue rotation — the deliberately hue-broken grade."""
    p = tmp_path_factory.mktemp("cf") / "broken.mp4"
    _render(p, crop=True, hue=True)
    return p


def _sidecar(tmp_path):
    """A STATIC subject (fixed x/y/w/h) so sample-time choice is irrelevant, and
    a STATIC crop offset (path is constant CROP_X) — the crop is real (not an
    identity pass-through: CROP_X=80 != 0), so extent_at_times must actually
    place the subject rather than vacuously echoing the source box."""
    n = 5
    route = [dict(t=round(0.2 + i * 1.6 / (n - 1), 3), x=SUBJECT_X, y=SUBJECT_Y,
                  w=SUBJECT_W, h=SUBJECT_H) for i in range(n)]
    path = [CROP_X] * n
    (tmp_path / "route.json").write_text(json.dumps(route))
    (tmp_path / "path.json").write_text(json.dumps(path))
    PathMeta(mode="fill", crop_w=CROP_W, crop_h=H, crop_y=0, src_dims=(W, H),
             canvas=(CROP_W, H), out_dims=(CROP_W, H), rect_px=(0, 0, CROP_W, H),
             freedom=W - CROP_W).write(tmp_path / "path.meta.json")
    return str(tmp_path / "route.json"), str(tmp_path / "path.json")


def test_box_mean_rgb_reads_the_synthesized_colour(source_clip):
    """One decode, five frames, box means — the production sampling path.
    SUBJECT_COLOR 0xC85028 = (200, 80, 40); sampled well inside the box."""
    fps = assembly.probe_stream(str(source_clip)).fps
    frames = assembly.frames_rgb(str(source_clip), [0.5, 1.0, 1.5], fps)
    assert len(frames) == 3
    r, g, b = check_episode._box_mean_rgb(frames[1], (240, 120, 400, 240))
    assert abs(r - 200) < 15 and abs(g - 80) < 15 and abs(b - 40) < 15


def _route_pts_path_meta(rp: str, pp: str):
    """The three ingredients `check_episode.run` derives from `rp`/`pp` before
    calling `_subject_delta_advisory` — built the same way here so these tests can
    call that sampling body directly, without a `plans` pair `run()` now also
    requires before it will report anything but not-checked (design 2026-08-31 §3)."""
    route_pts = route_from_json(rp)
    path_obj = CropPath.from_json(pp)
    meta = PathMeta.from_json(Path(pp).with_suffix(".meta.json"))
    return route_pts, path_obj, meta


def test_the_check_takes_five_samples(tmp_path, source_clip, faithful_clip):
    """The sample count is the statistic's own denominator — the median of five is
    what the design's thresholds were measured on (§0.4/§2.2)."""
    rp, pp = _sidecar(tmp_path)
    route_pts, path_obj, meta = _route_pts_path_meta(rp, pp)
    d = check_episode._subject_delta_advisory(str(faithful_clip), str(source_clip),
                                              route_pts, path_obj, meta)
    assert d["samples"] == 5


def test_sampling_survives_a_route_that_reaches_the_last_frame(tmp_path, source_clip,
                                                               faithful_clip):
    """A route's timestamps and the delivered clip's own duration are independent
    facts — a trim or a retime changes the delivered length without rewriting the
    route that was measured against the pre-trim footage. This route spans
    0..ROUTE_OVERRUN_T (2.4s) while both clips are only DUR (2.0s) long, so
    SAMPLE_FRACS' top fraction (0.9) asks for t=2.16s — past the ~1.967s
    last-decodable-frame boundary (DUR - 1/fps at 30fps).

    Verified empirically (task-2-report.md, fix round 1): with
    _last_sampleable_t's `min(..., last)` clamp removed, this raises
    `RuntimeError: frames_rgb: chunk requested 5 frames [7, 22, 36, 50, 65] but
    ffmpeg emitted 4 — a frame number is past the stream end` from
    assembly.frames_rgb; with the clamp in place (as shipped), it passes and
    still reports 5 samples."""
    n = 5
    route = [dict(t=round(i * ROUTE_OVERRUN_T / (n - 1), 3), x=SUBJECT_X, y=SUBJECT_Y,
                  w=SUBJECT_W, h=SUBJECT_H) for i in range(n)]
    (tmp_path / "route.json").write_text(json.dumps(route))
    (tmp_path / "path.json").write_text(json.dumps([CROP_X] * n))
    PathMeta(mode="fill", crop_w=CROP_W, crop_h=H, crop_y=0, src_dims=(W, H),
             canvas=(CROP_W, H), out_dims=(CROP_W, H), rect_px=(0, 0, CROP_W, H),
             freedom=W - CROP_W).write(tmp_path / "path.meta.json")
    rp, pp = str(tmp_path / "route.json"), str(tmp_path / "path.json")
    route_pts, path_obj, meta = _route_pts_path_meta(rp, pp)
    d = check_episode._subject_delta_advisory(str(faithful_clip), str(source_clip),
                                              route_pts, path_obj, meta)
    assert d["samples"] == 5


def test_faithful_grade_reads_a_small_advisory_delta(tmp_path, source_clip, faithful_clip):
    rp, pp = _sidecar(tmp_path)
    route_pts, path_obj, meta = _route_pts_path_meta(rp, pp)
    d = check_episode._subject_delta_advisory(str(faithful_clip), str(source_clip),
                                              route_pts, path_obj, meta)
    assert d["advisory_delta_e"] is True
    assert d["delta_e"] < 5.0

    # Without a `plans` pair, grade_damage AS A WHOLE reports not-checked and never
    # blocks — even for a grade this clean. design 2026-08-31 §3: process_episode
    # is what supplies `plans` (a later task), and until then the advisory above is
    # computed here directly, not through run().
    spec = CheckSpec(composition="center", grid="thirds", target_dur=DUR)
    report = check_episode.run(str(faithful_clip), rp, pp, spec,
                               str(tmp_path / "report.json"), source=str(source_clip))
    gd = report.checks["grade_damage"]
    assert gd.passed is None and gd.detail["status"] == "not-checked"
    assert report.overall is True


def test_hue_broken_grade_reads_a_large_advisory_delta_but_no_longer_blocks(
        tmp_path, source_clip, broken_clip):
    """dE00 stopped voting 2026-08-31 §3 — design's own point: a grade IS movement,
    so a dE00 threshold cannot tell a grade from damage, and on the reference run a
    real conductor pair put five of eight episodes over the old 5.0 ceiling with
    none of them damage. The sampling still describes a large move accurately (the
    direct call below); check_episode.run no longer stops the episode over it, and
    — without a `plans` pair — could not vote on it at all even if it still did."""
    rp, pp = _sidecar(tmp_path)
    route_pts, path_obj, meta = _route_pts_path_meta(rp, pp)
    d = check_episode._subject_delta_advisory(str(broken_clip), str(source_clip),
                                              route_pts, path_obj, meta)
    assert d["delta_e"] > 20.0           # hue=h=120 on a saturated orange
    assert d["dominant"] == "hue"

    spec = CheckSpec(composition="center", grid="thirds", target_dur=DUR)
    report = check_episode.run(str(broken_clip), rp, pp, spec,
                               str(tmp_path / "report.json"), source=str(source_clip))
    gd = report.checks["grade_damage"]
    assert gd.passed is None and gd.detail["status"] == "not-checked"
    assert report.overall is True


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
    a real (graded, plain) RenderPlan pair built the same way process_episode will build
    one (a later task's wiring).

    The dE00 advisory rides along too: measured on these bytes, the authored grade lands
    at ΔE00 **1.59**, and the identity control at **0.79** — so roughly half of the
    authored reading is the re-encode and the crop's own resampling. (Design §2.4's ep1
    reads 1.44 on real footage; this fixture is not that footage and the agreement is a
    sanity check, not a pin.)

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
    assert report.overall is True, report.fail_reasons

    # 3. The identity control reads a smaller advisory delta too — the headroom the
    #    authored grade spends is real. Its OWN entropy ratio is exactly 1.0 (both
    #    halves of the pair are the same identity plan), so it cannot be below the floor.
    control_report = check_episode.run(
        control_clip, route_path, str(tmp_path / "control" / "path.json"),
        CheckSpec(composition="center", grid="thirds", target_dur=GRADE_DUR),
        str(tmp_path / "control" / "report_with_plans.json"), source=str(graded_source),
        plans=(control_plan, control_plan))
    ccf = control_report.checks["grade_damage"]
    assert ccf.passed is True, ccf.detail
    assert ccf.detail["ratio"] == pytest.approx(1.0, abs=1e-3)
    assert ccf.detail["delta_e"] < gd.detail["delta_e"]
    assert control_report.overall is True, control_report.fail_reasons
