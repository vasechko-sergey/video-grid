"""Real-ffmpeg proofs that a colour knob set on ReframeSpec actually moves the
DELIVERED pixels through reframe.reframe end-to-end (colour-as-a-stage Task 15).

Audit of existing colour integration coverage (read first, before adding
anything here — this file exists to fill the GAP, not to repeat these):

  - tests/integration/test_reframe.py::test_filter_args_fast_path_byte_identical_at_defaults
    pins the FILTER-STRING at all-default knobs — but it calls `_filter_args`
    directly with an already-built `grade` string, no real ffmpeg render.
  - tests/integration/test_reframe.py::test_verify_tone_rejects_a_banding_curve /
    test_verify_tone_accepts_a_gentle_monotone_curve prove verify_tone's OWN
    accept/reject boundary on a bare fragment string returned by color.tone_arg
    — never wired through a real ReframeSpec + reframe.reframe() render.
  - tests/integration/test_color_fidelity.py proves check_episode's ADVISORY
    hue-drift check (source vs graded) — a different script's gate, and its
    "graded" fixture is rendered with a raw ffmpeg `hue=` filter directly, never
    through ReframeSpec's colour fields / reframe.reframe.
  - tests/integration/test_color_measure.py proves scripts/color_measure.py's
    measure_profile on synthesized clips — an authoring aid, unrelated to
    reframe's render path.
  - tests/lib/test_assembly.py proves range-tag matching/normalization logic
    against a monkeypatched proc.run (no real encode) — assembly's tv/pc/
    unknown handling is already covered there and is NOT repeated here.

None of the above renders a NON-DEFAULT grade through a real reframe.reframe()
call and measures the delivered pixels, or drives a valid tone pair through the
full pipeline (only the bare fragment is exercised elsewhere). That is the gap
this file closes: four proofs — the grade moves pixels (headline),
white_balance neutralizes a cast, a tone curve renders end-to-end, and a tone
curve measurably moves the delivered pixels (the last closes a coverage gap a
code review found: the third proof only asserted the tone render SURVIVES, so
a future drop of the `tone=tone` kwarg from reframe's color.grade_chain(...)
call would have passed it silently).

PITFALL (measured on this ffmpeg build): libx264 does not write the VUI range
tag for the default "tv" -color_range, so a probed file reads color_range ==
"unknown" even after an explicit `-color_range tv`. Nothing here asserts a
physical colour-range tag on any rendered file — that is assembly's proof
(test_assembly.py), already covered, and asserting it against a raw reframe
output would be asserting a physical property this ffmpeg build never writes.
"""
import json
import tempfile

import pytest
from PIL import Image, ImageStat

from scripts import reframe
from scripts.lib import color, ffbin, proc
from scripts.lib.models import Delivery, ReframeSpec

pytestmark = pytest.mark.integration

# color.TARGET verbatim: passing it as color_means makes gains_for_means an
# identity (1, 1, 1) mixer, so the base source-normalizing gain contributes
# NOTHING to either rendered variant below — any measured pixel difference is
# then attributable only to the grade knob(s) actually under test.
TARGET = (105.0, 122.0, 137.0)


def _duration(path) -> float:
    out = proc.run([ffbin.ffprobe(), "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nk=1:nw=1", str(path)], text=True)
    return float(out.stdout.strip())


def _frame_mean_rgb(clip: str, t: float) -> tuple[float, float, float]:
    """Mean (R, G, B) of one grabbed frame at time t."""
    with tempfile.TemporaryDirectory() as tmp:
        f = f"{tmp}/f.png"
        proc.run([ffbin.ffmpeg(), "-y", "-i", clip, "-ss", f"{t:.3f}",
                  "-frames:v", "1", f])          # -ss AFTER -i (§12 seek order)
        return tuple(ImageStat.Stat(Image.open(f).convert("RGB")).mean[:3])


def _flat_clip(path, color_hex: str, w: int, h: int, dur: float, fps: int) -> None:
    """A solid-colour field filling the whole frame. No subject box is needed:
    these proofs are about the GRADE, not tracking geometry, and canvas=(16, 9)
    against a 16:9 source below resolves freedom=0 (a whole-frame fill crop —
    see test_compute_path_at_zero_freedom_is_constant_zero), so the route's
    exact content is irrelevant to what gets measured."""
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", f"color=c={color_hex}:s={w}x{h}:d={dur}:r={fps}",
              "-t", str(dur), "-pix_fmt", "yuv420p", str(path)])


def _static_route(tmp_path, name: str, w: int, h: int, dur: float, fps: int) -> str:
    """A trivial centred route spanning the clip. At freedom=0 the crop cannot
    move regardless of route content (compute_path returns a constant path), so
    this only exists to satisfy reframe's "a route is required" contract."""
    p = tmp_path / name
    n = int(dur * fps)
    p.write_text(json.dumps([dict(t=i / fps, x=w / 2, y=h / 2, w=w * 0.3, h=h * 0.3)
                             for i in range(n)]))
    return str(p)


# --- Proof 1: the grade moves the delivered pixels (headline) ------------------

SAT_W, SAT_H, SAT_DUR, SAT_FPS = 640, 360, 2.0, 30
SAT_COLOR = "0xC85028"     # (200, 80, 40) — saturated orange, hue ~15°: the same
                           # subject colour test_color_fidelity.py already uses,
                           # so its measured properties are known-good.


@pytest.fixture(scope="module")
def saturated_clip(tmp_path_factory):
    p = tmp_path_factory.mktemp("colour_stage") / "saturated.mp4"
    _flat_clip(p, SAT_COLOR, SAT_W, SAT_H, SAT_DUR, SAT_FPS)
    return str(p)


def test_the_grade_moves_the_delivered_pixels(saturated_clip, tmp_path):
    """A non-default grade (saturation=1.4, black_point=0.1) must render
    MEASURABLY different pixels than the identity-default grade. The fast-path
    byte-identical pin (test_reframe.py) only proves DEFAULTS reproduce the old
    command; nothing until now proves a set knob actually reaches the delivered
    frame through a real reframe.reframe() encode."""
    rp = _static_route(tmp_path, "route.json", SAT_W, SAT_H, SAT_DUR, SAT_FPS)

    def _render(name, **colour_kwargs):
        out = tmp_path / f"{name}.mp4"
        spec = ReframeSpec(composition="center", grid="thirds", canvas=(16, 9),
                           color_means=TARGET, delivery=Delivery("native"), **colour_kwargs)
        reframe.reframe(spec, saturated_clip, rp, str(out), str(tmp_path / f"{name}_path.json"))
        return str(out)

    default_rgb = _frame_mean_rgb(_render("default"), 1.0)
    graded_rgb = _frame_mean_rgb(_render("graded", saturation=1.4, black_point=0.1), 1.0)

    delta = max(abs(a - b) for a, b in zip(default_rgb, graded_rgb))
    assert delta > 10.0, (
        f"default={default_rgb} graded={graded_rgb}: a saturation=1.4 + "
        "black_point=0.1 grade must move the delivered pixels measurably, not "
        "render identically to the default grade")


# --- Proof 2: white_balance neutralizes a cast ----------------------------------

CAST_W, CAST_H, CAST_DUR, CAST_FPS = 640, 360, 2.0, 30
CAST_COLOR = "0x5A6496"    # (90, 100, 150) — a clear blue-leaning cast


@pytest.fixture(scope="module")
def cast_clip(tmp_path_factory):
    p = tmp_path_factory.mktemp("colour_stage") / "cast.mp4"
    _flat_clip(p, CAST_COLOR, CAST_W, CAST_H, CAST_DUR, CAST_FPS)
    return str(p)


def test_white_balance_neutralizes_a_colour_cast(cast_clip, tmp_path):
    """white_balance=1.0 must pull the channels CLOSER TOGETHER (less cast) than
    white_balance=0.0 (off) once rendered — color.white_balance_gains already
    proves the pure per-channel math (tests/lib/test_color.py); this proves the
    grey-world neutralize actually reaches the delivered pixels through
    reframe.reframe, not merely the fragment builder.

    Both renders use the SAME measured `color_means` (the raw clip's own mean),
    so the base gains_for_means mixer is identical between them — any narrowing
    of the channel spread is then attributable to white_balance alone."""
    means = _frame_mean_rgb(cast_clip, 1.0)
    rp = _static_route(tmp_path, "route.json", CAST_W, CAST_H, CAST_DUR, CAST_FPS)

    def _render(name, wb):
        out = tmp_path / f"{name}.mp4"
        spec = ReframeSpec(composition="center", grid="thirds", canvas=(16, 9),
                           color_means=means, delivery=Delivery("native"), white_balance=wb)
        reframe.reframe(spec, cast_clip, rp, str(out), str(tmp_path / f"{name}_path.json"))
        return str(out)

    off_rgb = _frame_mean_rgb(_render("wb_off", 0.0), 1.0)
    on_rgb = _frame_mean_rgb(_render("wb_on", 1.0), 1.0)
    off_spread = max(off_rgb) - min(off_rgb)
    on_spread = max(on_rgb) - min(on_rgb)
    assert on_spread < off_spread - 5.0, (
        f"off={off_rgb} (spread {off_spread:.1f}) on={on_rgb} (spread {on_spread:.1f}): "
        "white_balance=1.0 must neutralize the cast measurably more than "
        "white_balance=0.0 (off)")


# --- Proof 3: a valid tone pair renders end-to-end ------------------------------

def test_tone_renders_a_full_length_clip_end_to_end(sample_clip, tmp_path):
    """A tone_src/tone_dst pair already proven monotone by test_reframe.py's
    verify_tone unit tests must also survive the FULL pipeline — a real route,
    a real ReframeSpec, a real ffmpeg encode — and deliver a clip at the
    source's own duration. Nothing until now drives a tone pair through an
    actual reframe.reframe() call; verify_tone was only ever handed a bare
    fragment string built by color.tone_arg directly."""
    src_dur = _duration(sample_clip)
    # the sliding-box route test_reframe_output_dims uses: matches sample_clip's
    # box motion (x = 200 + t*430), so the crop genuinely tracks something.
    route = [dict(t=i / 30, x=270 + (i / 30) * 430, y=540, w=140, h=320) for i in range(90)]
    rp = tmp_path / "route.json"; rp.write_text(json.dumps(route))
    out = tmp_path / "toned.mp4"
    spec = ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                       color_means=(105, 122, 137),
                       delivery=Delivery.from_spec("exact:1080x1920"),
                       tone_src=(30, 100, 148), tone_dst=(35, 110, 150))
    # verify_tone runs INSIDE reframe() before the encode — a raise here would
    # mean the curve failed the banding guard, not that the render broke.
    reframe.reframe(spec, str(sample_clip), str(rp), str(out), str(tmp_path / "path.json"))
    assert out.exists()
    assert _duration(out) == pytest.approx(src_dur, abs=0.1)


# --- Proof 4: a tone curve moves the delivered pixels (coverage-gap close) -----

TONE_W, TONE_H, TONE_DUR, TONE_FPS = 640, 360, 2.0, 30
TONE_COLOR = "0x646464"    # flat grey, (100, 100, 100) — sits EXACTLY on the p50
                           # input anchor of TONE_SRC below, so curves=all maps
                           # every pixel to TONE_DST's p50 (120) with no spline-fit
                           # slop: the measured delta is the exact knot jump, not
                           # an artifact of where the fitted curve happens to sit
                           # between anchors.
TONE_SRC = (30, 100, 148)
TONE_DST = (60, 120, 185)  # a BIGGER monotone remap than the gentle
                           # (30,100,148)->(35,110,150) pair test_reframe.py's own
                           # verify_tone accept-boundary test uses. Empirically
                           # measured on this fixture (see task notes): the gentle
                           # pair moves the mean by only ~9 units, too thin a
                           # margin for a regression proof; this pair — still
                           # confirmed monotone by verify_tone below — measures a
                           # clean 20.


@pytest.fixture(scope="module")
def tone_clip(tmp_path_factory):
    p = tmp_path_factory.mktemp("colour_stage") / "tone.mp4"
    _flat_clip(p, TONE_COLOR, TONE_W, TONE_H, TONE_DUR, TONE_FPS)
    return str(p)


def test_tone_moves_the_delivered_pixels(tone_clip, tmp_path):
    """A tone_src/tone_dst pair must render MEASURABLY different pixels than no
    tone at all — the grade-moves-pixels regression class (see
    test_the_grade_moves_the_delivered_pixels above), applied to the tone knob.

    test_tone_renders_a_full_length_clip_end_to_end (above) only proves the
    pipeline SURVIVES a tone pair end-to-end; it does not prove the curve
    reaches the delivered frame. Dropping the `tone=tone` kwarg from reframe's
    `color.grade_chain(...)` call — tone_src/tone_dst would still be validated
    and verify_tone would still run, then the render would silently skip the
    curve — would pass that test unchanged. This proof would catch it: with
    the kwarg dropped, `on_rgb` collapses to the same value as `off_rgb` and
    the delta assertion below fails.

    Same confound-isolation trick as Proof 1/2: color_means=TARGET makes the
    base gains_for_means mixer an identity (1, 1, 1), so ONLY the tone curve
    (applied earlier in grade_chain's fixed order — see its docstring) can
    move the flat clip's pixels between the two renders.
    """
    reframe.verify_tone(color.tone_arg(TONE_SRC, TONE_DST))   # confirm monotone FIRST
    rp = _static_route(tmp_path, "route.json", TONE_W, TONE_H, TONE_DUR, TONE_FPS)

    def _render(name, **colour_kwargs):
        out = tmp_path / f"{name}.mp4"
        spec = ReframeSpec(composition="center", grid="thirds", canvas=(16, 9),
                           color_means=TARGET, delivery=Delivery("native"), **colour_kwargs)
        reframe.reframe(spec, tone_clip, rp, str(out), str(tmp_path / f"{name}_path.json"))
        return str(out)

    off_rgb = _frame_mean_rgb(_render("tone_off"), 1.0)
    on_rgb = _frame_mean_rgb(_render("tone_on", tone_src=TONE_SRC, tone_dst=TONE_DST), 1.0)

    delta = max(abs(a - b) for a, b in zip(off_rgb, on_rgb))
    assert delta > 12.0, (
        f"off={off_rgb} on={on_rgb}: a tone_src/tone_dst pair must move the "
        "delivered pixels measurably, not render identically to no tone at all — "
        "this is exactly the regression a dropped `tone=tone` kwarg in "
        "color.grade_chain's call would cause (measured on this fixture: "
        "off=(100,100,100) on=(120,120,120), delta=20.0)")
