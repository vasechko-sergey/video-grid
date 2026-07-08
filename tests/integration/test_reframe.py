import json, subprocess
import pytest
from scripts import reframe

def _dims(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    s = json.loads(out.stdout)["streams"][0]
    return (s["width"], s["height"])

def test_compute_path_lead_right():
    # pure path computation (no ffmpeg): subject slides right → crop_x rises
    route = [dict(t=i/30, x=300 + i*40, y=500, w=140, h=320) for i in range(20)]
    path = reframe.compute_path(route, composition="lead", grid="thirds",
                                canvas=(9, 16), src=(1920, 1080),
                                motion=("lateral", "right"), max_step=25)
    assert len(path) == 20
    assert path[-1] >= path[0]                  # crop follows subject right
    assert all(0 <= x <= 1920 - 607 for x in path)

@pytest.mark.integration
def test_reframe_output_dims(sample_clip, tmp_path):
    # build a route matching the fixture's sliding box (x = 200 + t*430 + w/2)
    route = [dict(t=i/30, x=270 + (i/30)*430, y=540, w=140, h=320)
             for i in range(90)]
    rpath = tmp_path / "route.json"; rpath.write_text(json.dumps(route))
    out = tmp_path / "ep.mp4"
    reframe.reframe(src=str(sample_clip), route_path=str(rpath), out=str(out),
                    composition="lead", grid="thirds", canvas=(9, 16),
                    color_means=(105, 122, 137), stabilize=False,
                    path_out=str(tmp_path / "path.json"))
    assert _dims(out) == (1080, 1920)
    assert (tmp_path / "path.json").exists()

def test_xexpr_uses_route_times_across_gap():
    # 10 frames, then a 10-frame tracking gap, then 10 more frames (30fps).
    # The expression's last knot must sit at the route's REAL last t (~0.966s),
    # not at index-derived (len(path)-1)/fps (~0.633s) — the desync bug.
    times = [i / 30 for i in range(10)] + [(i + 20) / 30 for i in range(10)]
    path = list(range(0, 100, 10)) + list(range(300, 400, 10))
    knots = reframe._simplify(path, times)
    assert abs(knots[-1][0] - times[-1]) < 1e-9
    assert abs(knots[0][0] - times[0]) < 1e-9

def test_reframe_rejects_empty_route(sample_clip, tmp_path):
    rp = tmp_path / "route.json"; rp.write_text("[]")
    with pytest.raises(ValueError, match="empty"):
        reframe.reframe(src=str(sample_clip), route_path=str(rp),
                        out=str(tmp_path / "ep.mp4"), composition="lead",
                        grid="thirds", canvas=(9, 16),
                        color_means=(105, 122, 137), stabilize=False,
                        path_out=str(tmp_path / "path.json"))

@pytest.mark.integration
def test_reframe_with_route_gap_still_renders(sample_clip, tmp_path):
    # gappy route (subject lost frames 30-59) must still produce a valid clip
    route = ([dict(t=i/30, x=270 + (i/30)*430, y=540, w=140, h=320)
              for i in range(30)]
             + [dict(t=i/30, x=270 + (i/30)*430, y=540, w=140, h=320)
                for i in range(60, 90)])
    rpath = tmp_path / "route.json"; rpath.write_text(json.dumps(route))
    out = tmp_path / "ep.mp4"
    reframe.reframe(src=str(sample_clip), route_path=str(rpath), out=str(out),
                    composition="lead", grid="thirds", canvas=(9, 16),
                    color_means=(105, 122, 137), stabilize=False,
                    path_out=str(tmp_path / "path.json"))
    assert _dims(out) == (1080, 1920)

def test_simplify_caps_knots_on_long_noisy_path():
    # ~83s at 60fps with residual tracker jitter: must stay under the knot cap
    import math
    times = [i / 60 for i in range(5000)]
    path = [int(200 + i * 0.15 + 2.5 * math.sin(i * 1.7)) for i in range(5000)]
    knots = reframe._simplify(path, times)
    assert len(knots) <= 80
    expr = reframe._xexpr(path, times)
    assert len(expr) < 8000        # comfortably inside ffmpeg's parser budget

def test_stabilize_true_fails_loud(sample_clip, tmp_path):
    rp = tmp_path / "route.json"
    rp.write_text(json.dumps([dict(t=0, x=500, y=540, w=140, h=320),
                              dict(t=0.1, x=510, y=540, w=140, h=320)]))
    with pytest.raises(NotImplementedError, match="process-episode"):
        reframe.reframe(src=str(sample_clip), route_path=str(rp),
                        out=str(tmp_path / "ep.mp4"), composition="lead",
                        grid="thirds", canvas=(9, 16),
                        color_means=(105, 122, 137), stabilize=True,
                        path_out=str(tmp_path / "path.json"))

@pytest.mark.integration
def test_reframe_non_916_canvas_even_dims(sample_clip, tmp_path):
    # canvas 5:8 from 1080p → crop 675x1080 (odd) — output must be even and encode
    route = [dict(t=i/30, x=270 + (i/30)*430, y=540, w=140, h=320)
             for i in range(90)]
    rpath = tmp_path / "route.json"; rpath.write_text(json.dumps(route))
    out = tmp_path / "ep58.mp4"
    reframe.reframe(src=str(sample_clip), route_path=str(rpath), out=str(out),
                    composition="lead", grid="thirds", canvas=(5, 8),
                    color_means=(105, 122, 137), stabilize=False,
                    path_out=str(tmp_path / "path.json"))
    w, h = _dims(out)
    assert w % 2 == 0 and h % 2 == 0
