"""Real-ffmpeg proof for the advisory colour-fidelity check (design 2026-07-26
§7): real bytes through the sampling (`_region_mean_rgb`) + evaluate
(`color_fidelity.evaluate`) path, driven by `check_episode.run(..., source=)`.

Fixture shape: a coloured subject box on a dark-grey field (`source.mp4`), and
a "graded" clip that is a REAL crop of it (`crop=480:360:80:0` — a non-trivial
x offset, not an identity pass-through) so the route/path/meta sidecar's
`geometry.extent_at_times` projection is genuinely exercised, not vacuously
satisfied. `faithful.mp4` re-runs the identical recipe (no colour change);
`broken.mp4` adds a strong `hue=h=120` rotation after the crop — the
"simplest" grade-breaker the task names, verified empirically (see below) to
land the subject's hue ~118° away from source, far past both the 25° default
threshold and any plausible grading move.
"""
import json
import pytest
from scripts import check_episode
from scripts.check_episode import _region_mean_rgb
from scripts.lib import ffbin, proc
from scripts.lib.models import CheckSpec, PathMeta

pytestmark = pytest.mark.integration

W, H = 640, 360                      # source dims
BOX = (220, 100, 200, 160)           # x0, y0, w, h of the colour box in the source
SUBJECT_COLOR = "0xC85028"           # RGB (200, 80, 40) — saturated orange, hue ~15°
DUR = 2.0

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


def test_region_mean_rgb_reads_the_synthesized_colour(source_clip):
    # SUBJECT_COLOR 0xC85028 = (200, 80, 40); sampled well inside the box.
    sbox = (240, 120, 400, 240)
    r, g, b = _region_mean_rgb(str(source_clip), 1.0, sbox)
    assert abs(r - 200) < 15 and abs(g - 80) < 15 and abs(b - 40) < 15


def test_faithful_grade_does_not_exceed(tmp_path, source_clip, faithful_clip):
    rp, pp = _sidecar(tmp_path)
    spec = CheckSpec(composition="center", grid="thirds", target_dur=DUR)
    report = check_episode.run(str(faithful_clip), rp, pp, spec,
                               str(tmp_path / "report.json"), source=str(source_clip))
    cf = report.checks["color_fidelity"]
    assert cf.passed is None                     # still advisory in this task
    assert cf.detail.get("status") != "not-checked", cf.detail
    assert cf.detail["exceeded"] is False
    assert cf.detail["delta_e"] < 5.0
    assert report.overall is True


def test_hue_broken_grade_is_flagged(tmp_path, source_clip, broken_clip):
    rp, pp = _sidecar(tmp_path)
    spec = CheckSpec(composition="center", grid="thirds", target_dur=DUR)
    report = check_episode.run(str(broken_clip), rp, pp, spec,
                               str(tmp_path / "report.json"), source=str(source_clip))
    cf = report.checks["color_fidelity"]
    assert cf.passed is None                     # Task 3 flips this
    assert cf.detail["exceeded"] is True
    assert cf.detail["delta_e"] > 20.0           # hue=h=120 on a saturated orange
    assert cf.detail["dominant"] == "hue"
    assert report.overall is True
