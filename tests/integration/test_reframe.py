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
