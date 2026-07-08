import json
from pathlib import Path
import pytest
from PIL import Image
from scripts import storyboard, check_episode
from scripts.lib import models

@pytest.mark.integration
def test_storyboard_creates_sheet(sample_clip, tmp_path):
    out = tmp_path / "sheet.jpg"
    spec = models.StoryboardSpec(n=6, grids=("thirds", "phi"))
    storyboard.build(str(sample_clip), str(out), spec)
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

def test_marks_at_times_interpolates_on_t():
    # route with a time GAP: index-sampling would misplace the mark; time-sampling won't
    route = [models.RoutePoint(0.0, 100, 500, 100, 200),
             models.RoutePoint(0.1, 200, 500, 100, 200),
             models.RoutePoint(1.0, 1000, 500, 100, 200)]   # big gap in t
    path = models.CropPath([0, 100, 900])
    marks = storyboard.marks_at_times(route, path, crop_w=200, src_h=1000,
                                      times=[0.0, 0.5, 1.0])
    # at t=1.0: x=1000, crop_x=900 -> fx=(1000-900)/200=0.5 ; fy=500/1000=0.5
    assert abs(marks[-1][0] - 0.5) < 1e-6 and abs(marks[-1][1] - 0.5) < 1e-6
    assert len(marks) == 3

def test_marks_at_times_rejects_desync():
    route = [models.RoutePoint(i / 30, 400, 540, 140, 320) for i in range(10)]
    with pytest.raises(ValueError, match="parallel"):
        storyboard.marks_at_times(route, models.CropPath([100] * 9), crop_w=600,
                                  src_h=1080, times=[0.0, 0.5])

def test_build_computes_marks_at_sample_times(monkeypatch, tmp_path):
    # behavioral pin for #4: build() must sample frames BY TIME and compute the
    # hero marks at those SAME times (interpolated from route/path) — not by
    # route index, which is what let the marker drift on a gappy route.
    captured = {}

    def fake_sample_frames(src, n, tmp, times):
        captured["times"] = list(times)
        files = []
        for i in range(len(times)):
            f = Path(tmp) / f"f{i:02d}.png"
            Image.new("RGB", (2, 2), (10, 10, 10)).save(f)
            files.append(f)
        return files

    overlay_marks = []
    real_overlay = storyboard._overlay
    def spy_overlay(img, grids, mark=None):
        overlay_marks.append(mark)
        return real_overlay(img, grids, mark=mark)

    monkeypatch.setattr(storyboard, "_duration", lambda src: 3.0)
    monkeypatch.setattr(storyboard, "_sample_frames", fake_sample_frames)
    monkeypatch.setattr(storyboard, "_overlay", spy_overlay)

    route = [models.RoutePoint(0.0, 400, 540, 100, 200),
             models.RoutePoint(1.5, 700, 540, 100, 200),
             models.RoutePoint(3.0, 1000, 540, 100, 200)]
    path = models.CropPath([200, 400, 700])
    spec = models.StoryboardSpec(n=3, grids=("thirds",))
    out = tmp_path / "sheet.jpg"

    result = storyboard.build(str(tmp_path / "clip.mp4"), str(out), spec,
                              route=route, path=path, crop_w=600, src_h=1080)

    times = captured["times"]
    assert len(times) == spec.n == 3
    assert result == (str(out), times)
    expected_marks = storyboard.marks_at_times(route, path, crop_w=600,
                                               src_h=1080, times=times)
    assert overlay_marks == expected_marks
    assert out.exists() and out.stat().st_size > 0

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
