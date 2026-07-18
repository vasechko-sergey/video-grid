"""Golden integration for the layouts (plan 2026-07-10, Task 11): real ffmpeg,
the real golden_ride fixture, the frozen golden_route so no YOLO runs.

Every dimension assertion is on what ffprobe reports the delivered file to be —
never on a hardcoded resolution taken as an input assumption. The sidecar is
asserted AGAINST ffprobe, not against itself: it must describe the file on disk,
or nothing downstream (checks, storyboard) can trust it.
"""
import json
import subprocess
from pathlib import Path

import pytest

from scripts import check_episode, reframe
from scripts import process_episode as pe
from scripts.lib.models import Delivery, LayoutSpec, PathMeta, ReframeSpec

FIX = Path(__file__).parent.parent / "fixtures"
RIDE = str(FIX / "golden_ride.mp4")        # 1280x720 @ 59.94fps, ~1.585s
ROUTE = str(FIX / "golden_route.json")     # frozen tracker route beside it
NATIVE = Delivery("native", None)
COLOR = (105, 122, 137)


# `_dims` is defined locally rather than imported from test_reframe: there is no
# tests/__init__.py, so `tests.integration.test_reframe` is not an importable
# module path (pytest loads that file under the fragile internal name
# `integration.test_reframe`, dependent on collection order). test_process_episode
# inlines its own ffprobe for the same reason — a local probe helper is the
# convention in this suite.
def _dims(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    s = json.loads(out.stdout)["streams"][0]
    return (s["width"], s["height"])


# ---------------------------------------------------------------------------
# Step 1: engine-level — reframe() straight onto the golden ride
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_fit_on_the_golden_ride(tmp_path):
    out = tmp_path / "fitblur.mp4"
    path_out = tmp_path / "path.json"
    spec = ReframeSpec(composition="break", grid="thirds", canvas=(9, 16),
                       color_means=COLOR, delivery=NATIVE,
                       layout=LayoutSpec(mode="fit", crop_aspect="source"))
    reframe.reframe(spec, RIDE, ROUTE, str(out), str(path_out))
    assert _dims(out) == (1280, 2276)          # subject native, background upscaled
    meta = PathMeta.from_json(path_out.with_suffix(".meta.json"))
    assert (meta.crop_w, meta.crop_h) == (1280, 720)
    assert meta.freedom == 0
    assert meta.rect_px == (0, 778, 1280, 720)


@pytest.mark.integration
def test_solid_background_is_recorded_in_the_sidecar(tmp_path):
    # Coverage-hole check (Task 5 mutation check): dropping `background=rl.background`
    # from reframe's PathMeta(...) call left every test in the suite green, because
    # every one of them renders the field's own default (`blur`) — a from_dict that
    # silently re-defaulted a dropped key is indistinguishable from one that actually
    # round-tripped it, UNLESS the fixture uses the non-default value. Render `solid`
    # and read it back off disk, the same shape as test_fit_on_the_golden_ride above.
    out = tmp_path / "solid.mp4"
    path_out = tmp_path / "path.json"
    spec = ReframeSpec(composition="break", grid="thirds", canvas=(9, 16),
                       color_means=COLOR, delivery=NATIVE,
                       layout=LayoutSpec(mode="fit", crop_aspect="source",
                                         background="solid"))
    reframe.reframe(spec, RIDE, ROUTE, str(out), str(path_out))
    meta = PathMeta.from_json(path_out.with_suffix(".meta.json"))
    assert meta.background == "solid"


@pytest.mark.integration
def test_insert_on_the_golden_ride(tmp_path):
    out = tmp_path / "insert.mp4"
    path_out = tmp_path / "path.json"
    spec = ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                       color_means=COLOR, delivery=NATIVE,
                       layout=LayoutSpec(mode="insert", crop_aspect=(1, 1),
                                         rect=(0.05, 0.25, 0.90)))
    reframe.reframe(spec, RIDE, ROUTE, str(out), str(path_out))
    assert _dims(out) == (800, 1422)
    meta = PathMeta.from_json(path_out.with_suffix(".meta.json"))
    assert (meta.crop_w, meta.crop_h) == (720, 720)
    assert meta.freedom == 560                 # the card is tracked
    assert meta.rect_px == (40, 356, 720, 720)


@pytest.mark.integration
def test_fill_on_the_golden_ride_is_unchanged(tmp_path):
    # The number this whole plan promised would not change. If this fails, the
    # fast path has drifted — stop, do not paper over it.
    out = tmp_path / "fill.mp4"
    path_out = tmp_path / "path.json"
    spec = ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                       color_means=COLOR, delivery=NATIVE)
    reframe.reframe(spec, RIDE, ROUTE, str(out), str(path_out))
    assert _dims(out) == (404, 720)            # exactly what it produced before layouts


# ---------------------------------------------------------------------------
# Step 2: end-to-end through the orchestrator
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_fit_through_the_orchestrator(tmp_path):
    # composition 'break': a 'lead' at zero freedom is refused by the manifest
    # gate, by design — there is nothing to lead with
    manifest = dict(segment=RIDE,
                    out_path=str(tmp_path / "ep.mp4"),
                    composition="break", grid="thirds", canvas=[9, 16],
                    target_dur=1.58,               # golden clip ~1.585s, tol +/-0.5s
                    layout="fit", crop_aspect="source")
    result = pe.process_episode(manifest, project_dir=str(tmp_path), route_path=ROUTE)
    assert result["status"] == "mechanical_pass", result
    assert result["report"]["checks"]["framing"] == {
        "status": "editorial-only", "reason": "no horizontal freedom"}
    assert _dims(result["clip"]) == (1280, 2276)
    assert Path(result["storyboard"]).exists()


@pytest.mark.integration
@pytest.mark.parametrize("extra, problem", [
    (dict(rect=[0.0, 0.0, 0.05]), "past the 8192px limit"),      # native canvas explodes
    (dict(rect=[0.05, 0.90, 0.90]), "overflows"),                # card runs off the bottom
    (dict(rect=[0.05, 0.25, 0.90], border_px=400), "narrower than its own two borders"),
])
def test_a_layout_the_engine_cannot_build_comes_back_as_needs_input(tmp_path, extra, problem):
    """manifest.validate() cannot judge these — every one depends on the source
    dims, which exist only after ffprobe. Before the preflight, each returned
    `validate() == []` and then escaped process_episode as a raw ValueError on
    attempt 1. The orchestrator's contract is that a manifest problem comes back
    as a finding; a rect typo is a manifest problem.

    Marked integration: the preflight runs after _probe, so ffprobe is called.
    """
    manifest = dict(segment=RIDE, out_path=str(tmp_path / "ep.mp4"),
                    composition="break", grid="thirds", canvas=[9, 16], target_dur=1.58,
                    layout="insert", crop_aspect=[1, 1], **extra)
    result = pe.process_episode(manifest, project_dir=str(tmp_path), route_path=ROUTE)
    assert result["status"] == "needs_input", result
    assert result["attempt"] == 0
    assert any(problem in p for p in result["problems"]), result["problems"]
    assert not (tmp_path / "ep.mp4").exists()      # ffmpeg never ran


def test_lead_at_zero_freedom_never_reaches_the_engine(tmp_path):
    # UNMARKED on purpose: the soft manifest gate refuses this before ffprobe is
    # ever called, so no ffmpeg runs. (Confirmed: process_episode.validate()
    # returns needs_input before reframe._probe — see manifest.validate's
    # lead/crop_scale/source gate.)
    manifest = dict(segment=RIDE,
                    out_path=str(tmp_path / "ep.mp4"),
                    composition="lead", grid="thirds", canvas=[9, 16], target_dur=1.58,
                    layout="fit", crop_aspect="source")
    result = pe.process_episode(manifest, project_dir=str(tmp_path), route_path=ROUTE)
    assert result["status"] == "needs_input"
    assert any("crop_scale" in p for p in result["problems"])


# ---------------------------------------------------------------------------
# Step 3: extras
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_insert_through_the_orchestrator_insets_the_border(tmp_path):
    # A bordered insert: the 8px border sits OUTSIDE the content, so the sidecar's
    # rect_px — where the checks/storyboard place the hero marker — is the CONTENT
    # rect (48, 364, 704, 704), inset by the border, not the outer 720x720 card at
    # (40, 356). composition='lead' is a genuine numeric run: freedom is 560, so
    # on_line is a real check, and it passes on the golden route (ratio 1.0),
    # reaching mechanical_pass — verified before this assertion was written.
    manifest = dict(segment=RIDE,
                    out_path=str(tmp_path / "ep.mp4"),
                    composition="lead", grid="thirds", canvas=[9, 16], target_dur=1.58,
                    layout="insert", crop_aspect=[1, 1], rect=[0.05, 0.25, 0.90],
                    border_px=8)
    result = pe.process_episode(manifest, project_dir=str(tmp_path), route_path=ROUTE)
    assert result["status"] == "mechanical_pass", result
    assert result["report"]["checks"]["on_line"]["pass"] is True
    assert _dims(result["clip"]) == (800, 1422)
    meta = PathMeta.from_json(Path(tmp_path) / "path.meta.json")
    assert meta.rect_px == (48, 364, 704, 704)      # content rect, inset by the border


@pytest.mark.integration
@pytest.mark.parametrize("canvas, layout, delivery, expect", [
    # a 3840x200 cover: the ceiling binds at 50, where the unclamped 3840//60=64
    # is what real ffmpeg refuses. This is the premise the unit test asserts a
    # string about but never renders.
    ((21, 9), LayoutSpec(mode="insert", crop_aspect=(1, 1), rect=(0.4, 0.02, 0.03)),
     Delivery("exact", (3840, 200)), (3840, 200)),
    # a 1280x4 cover: the ceiling is 1, below the radius floor of 2. The floor
    # used to win and ffmpeg died.
    ((256, 1), LayoutSpec(mode="fit", crop_aspect=(256, 1)), NATIVE, (1280, 4)),
])
def test_extreme_covers_render_at_the_capped_blur_radius(tmp_path, canvas, layout,
                                                         delivery, expect):
    out = tmp_path / "cover.mp4"
    spec = ReframeSpec(composition="break", grid="thirds", canvas=canvas,
                       color_means=COLOR, delivery=delivery, layout=layout)
    reframe.reframe(spec, RIDE, ROUTE, str(out), str(tmp_path / "path.json"))
    assert _dims(out) == expect            # it rendered at all — ffmpeg did not refuse


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    """Render each engine layout once against the golden ride and hand back its
    (clip_path, meta). Shared by the two parametrized tests below so ffmpeg runs
    three times, not six; module-scoped because the clips are read-only here."""
    specs = {
        "fill": ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                            color_means=COLOR, delivery=NATIVE),
        "fit": ReframeSpec(composition="break", grid="thirds", canvas=(9, 16),
                                color_means=COLOR, delivery=NATIVE,
                                layout=LayoutSpec(mode="fit", crop_aspect="source")),
        "insert": ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                              color_means=COLOR, delivery=NATIVE,
                              layout=LayoutSpec(mode="insert", crop_aspect=(1, 1),
                                                rect=(0.05, 0.25, 0.90))),
    }
    d = tmp_path_factory.mktemp("layouts")
    out = {}
    for name, spec in specs.items():
        clip = d / f"{name}.mp4"
        path_out = d / f"{name}.json"
        reframe.reframe(spec, RIDE, ROUTE, str(clip), str(path_out))
        out[name] = (str(clip), PathMeta.from_json(path_out.with_suffix(".meta.json")))
    return out


@pytest.mark.integration
@pytest.mark.parametrize("layout_name", ["fill", "fit", "insert"])
def test_the_sidecar_describes_the_file_on_disk(rendered, layout_name):
    # The one assertion that catches geometry drifting between what resolve()
    # computed and what ffmpeg actually produced: the sidecar's own out_dims must
    # equal ffprobe's reading of the delivered clip, for every layout.
    clip, meta = rendered[layout_name]
    assert meta.out_dims == _dims(clip)


@pytest.mark.integration
@pytest.mark.parametrize("layout_name", ["fit", "insert"])
def test_composite_boundary_frames_are_not_black(rendered, layout_name):
    # Spec §9 / §12: the banned lutrgb produced BLACK frames historically, and a
    # composite that silently rendered black would pass every dimension assertion
    # above. The head and tail frames must not be black. Bar = 20: the composites
    # render at ~120 boundary luma (the source is ~103; colorchannelmixer lifts
    # it), so 20 sits ~6x below the real value and an order of magnitude above the
    # ~0 a black frame would give — comfortable margin on both sides.
    clip, _ = rendered[layout_name]
    lumas = check_episode._frame_lumas(clip, "boundary")
    assert lumas, "no boundary frames were sampled"
    assert min(lumas) > 20, lumas
