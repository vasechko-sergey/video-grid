import json
import pytest
from scripts import storyboard, check_episode
from scripts.lib import models

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
    spec = models.CheckSpec(composition="center", grid="thirds", target_dur=3.0,
                            canvas=(9, 16), src_dims=(1920, 1080))
    report = check_episode.run(clip=str(sample_clip), route_path=str(rp),
                               path_path=str(pp), spec=spec,
                               out=str(tmp_path / "report.json"))
    assert report.checks["centered"].passed is True
    assert report.checks["continuity"].passed is True
    assert "black_frames" in report.checks
    assert report.checks["horizon"].to_dict() == {"status": "not-implemented"}
    assert report.attempt == 1 and isinstance(report.fail_reasons, list)
    assert report.overall in (True, False)

@pytest.mark.integration
def test_check_episode_rejects_unknown_composition(sample_clip, tmp_path):
    route = [dict(t=i/30, x=540, y=540, w=140, h=320) for i in range(30)]
    path = [200] * 30
    rp = tmp_path / "route.json"; rp.write_text(json.dumps(route))
    pp = tmp_path / "path.json"; pp.write_text(json.dumps(path))
    # composition validity is now guarded by CheckSpec itself (raises before
    # check_episode.run is ever called) — a bad value must still fail loud
    with pytest.raises(ValueError, match="composition"):
        spec = models.CheckSpec(composition="Lead", grid="thirds", target_dur=3.0,
                                canvas=(9, 16), src_dims=(1920, 1080))
        check_episode.run(clip=str(sample_clip), route_path=str(rp),
                          path_path=str(pp), spec=spec,
                          out=str(tmp_path / "report.json"))

@pytest.mark.integration
def test_check_episode_break_is_editorial_only(sample_clip, tmp_path):
    # break: crop pinned far from any line must NOT fail numerically
    route = [dict(t=i/30, x=900, y=540, w=140, h=320) for i in range(30)]
    path = [50] * 30
    rp = tmp_path / "route.json"; rp.write_text(json.dumps(route))
    pp = tmp_path / "path.json"; pp.write_text(json.dumps(path))
    spec = models.CheckSpec(composition="break", grid="thirds", target_dur=3.0,
                            canvas=(9, 16), src_dims=(1920, 1080))
    report = check_episode.run(clip=str(sample_clip), route_path=str(rp),
                               path_path=str(pp), spec=spec,
                               out=str(tmp_path / "report.json"))
    assert report.checks["framing"].to_dict() == {"status": "editorial-only"}
    assert "on_line" not in report.checks

def test_boundary_black_relative_passes_uniformly_dark(monkeypatch):
    # dark night clip: boundary ~10, body ~12 -> NOT a defect
    monkeypatch.setattr(check_episode, "_frame_lumas",
                        lambda clip, where, n=3: [10.0, 11.0] if where == "boundary" else [12.0, 12.0])
    res = check_episode._black_frames_check("clip.mp4", black_floor=6.0, black_rel=0.35)
    assert res["pass"] is True

def test_boundary_black_relative_fails_black_cut(monkeypatch):
    # seek-landmine: boundary ~0, body ~120 -> defect
    monkeypatch.setattr(check_episode, "_frame_lumas",
                        lambda clip, where, n=3: [0.5, 0.2] if where == "boundary" else [120.0, 118.0])
    res = check_episode._black_frames_check("clip.mp4", black_floor=6.0, black_rel=0.35)
    assert res["pass"] is False

def test_run_returns_report(monkeypatch, tmp_path):
    route = [models.RoutePoint(i / 30, 300 + i * 90, 500, 140, 320) for i in range(10)]
    models.route_to_json(route, tmp_path / "route.json")
    models.CropPath([300 + i * 90 - 200 for i in range(10)]).to_json(tmp_path / "path.json")
    monkeypatch.setattr(check_episode, "_duration", lambda clip: 3.0)
    monkeypatch.setattr(check_episode, "_black_frames_check",
                        lambda clip, **k: {"pass": True, "boundary_lumas": [120.0]})
    spec = models.CheckSpec(composition="lead", grid="thirds", target_dur=3.0,
                            canvas=(9, 16), src_dims=(1920, 1080))
    report = check_episode.run(str(tmp_path / "clip.mp4"), str(tmp_path / "route.json"),
                               str(tmp_path / "path.json"), spec, str(tmp_path / "report.json"))
    assert isinstance(report, models.Report)
    assert "on_line" in report.checks and report.attempt == 1

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
    spec = models.CheckSpec(composition="center", grid="thirds", target_dur=3.5,
                            canvas=(9, 16), src_dims=(1920, 1080))
    report = check_episode.run(clip=str(bad), route_path=str(rp),
                               path_path=str(pp), spec=spec,
                               out=str(tmp_path / "report.json"))
    assert report.checks["black_frames"].passed is False
    assert "black_frames" in report.fail_reasons
