import json
import pytest
from scripts import storyboard, check_episode

@pytest.mark.integration
def test_storyboard_creates_sheet(sample_clip, tmp_path):
    out = tmp_path / "sheet.jpg"
    storyboard.build(src=str(sample_clip), out=str(out), n=6,
                     grids=("thirds", "phi"))
    assert out.exists() and out.stat().st_size > 0

@pytest.mark.integration
def test_check_episode_reports(sample_clip, tmp_path):
    # a route+path where subject is centered → centered check should pass
    route = [dict(t=i/30, x=540, y=540, w=140, h=320) for i in range(30)]
    path = [540 - 607 // 2] * 30
    rp = tmp_path / "route.json"; rp.write_text(json.dumps(route))
    pp = tmp_path / "path.json"; pp.write_text(json.dumps(path))
    report = check_episode.run(clip=str(sample_clip), route_path=str(rp),
                               path_path=str(pp), composition="center",
                               grid="thirds", target_dur=3.0,
                               out=str(tmp_path / "report.json"))
    assert report["checks"]["centered"]["pass"] is True
    assert report["checks"]["continuity"]["pass"] is True
    assert "black_frames" in report["checks"]
    assert report["checks"]["horizon"] == {"status": "not-implemented"}
    assert report["attempt"] == 1 and "fail_reasons" in report
    assert report["overall"] in (True, False)

@pytest.mark.integration
def test_check_episode_rejects_unknown_composition(sample_clip, tmp_path):
    route = [dict(t=i/30, x=540, y=540, w=140, h=320) for i in range(30)]
    path = [200] * 30
    rp = tmp_path / "route.json"; rp.write_text(json.dumps(route))
    pp = tmp_path / "path.json"; pp.write_text(json.dumps(path))
    with pytest.raises(ValueError, match="unknown composition"):
        check_episode.run(clip=str(sample_clip), route_path=str(rp),
                          path_path=str(pp), composition="Lead",
                          grid="thirds", target_dur=3.0,
                          out=str(tmp_path / "report.json"))

@pytest.mark.integration
def test_check_episode_break_is_editorial_only(sample_clip, tmp_path):
    # break: crop pinned far from any line must NOT fail numerically
    route = [dict(t=i/30, x=900, y=540, w=140, h=320) for i in range(30)]
    path = [50] * 30
    rp = tmp_path / "route.json"; rp.write_text(json.dumps(route))
    pp = tmp_path / "path.json"; pp.write_text(json.dumps(path))
    report = check_episode.run(clip=str(sample_clip), route_path=str(rp),
                               path_path=str(pp), composition="break",
                               grid="thirds", target_dur=3.0,
                               out=str(tmp_path / "report.json"))
    assert report["checks"]["framing"] == {"status": "editorial-only"}
    assert "on_line" not in report["checks"]

def test_marks_from_route_path():
    route = [dict(t=i/30, x=400 + i, y=540, w=140, h=320) for i in range(30)]
    path = [200] * 30
    marks = storyboard.marks_from_route_path(route, path, crop_w=600,
                                             src_h=1080, n=6)
    assert len(marks) == 6
    fx0, fy0 = marks[0]
    assert abs(fx0 - (400 - 200) / 600) < 1e-9
    assert abs(fy0 - 0.5) < 1e-9

def test_marks_rejects_desync():
    route = [dict(x=400, y=540)] * 10
    with pytest.raises(ValueError, match="parallel"):
        storyboard.marks_from_route_path(route, [100] * 9, crop_w=600,
                                         src_h=1080, n=4)

@pytest.mark.integration
def test_black_frames_boundary_luma_fails_on_black_lead_in(tmp_path, sample_clip):
    # prepend 0.5s of pure black to the sample clip → boundary check must fail
    import subprocess
    bad = tmp_path / "bad.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=1920x1080:d=0.5:r=30",
         "-i", str(sample_clip), "-filter_complex",
         "[0:v][1:v]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", str(bad)],
        check=True, capture_output=True)
    route = [dict(t=i/30, x=540, y=540, w=140, h=320) for i in range(30)]
    path = [540 - 607 // 2] * 30
    rp = tmp_path / "route.json"; rp.write_text(json.dumps(route))
    pp = tmp_path / "path.json"; pp.write_text(json.dumps(path))
    report = check_episode.run(clip=str(bad), route_path=str(rp),
                               path_path=str(pp), composition="center",
                               grid="thirds", target_dur=3.5,
                               out=str(tmp_path / "report.json"))
    assert report["checks"]["black_frames"]["pass"] is False
    assert "black_frames" in report["fail_reasons"]
