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
