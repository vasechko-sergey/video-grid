import json
from pathlib import Path
import pytest
from scripts import reframe, storyboard, check_episode
from scripts.lib import models

FIX = Path(__file__).parent.parent / "fixtures"

@pytest.mark.integration
def test_golden_ride_pipeline(tmp_path, golden_ride_segment):
    src = golden_ride_segment
    route = json.loads((FIX / "golden_route.json").read_text())
    rp = tmp_path / "route.json"; rp.write_text(json.dumps(route))
    ep = tmp_path / "ep.mp4"; pp = tmp_path / "path.json"

    rspec = models.ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                               color_means=(105, 122, 137), delivery=models.Delivery("native"))
    reframe.reframe(rspec, str(src), str(rp), str(ep), str(pp))
    storyboard.build(str(ep), str(tmp_path / "sheet.jpg"),
                     models.StoryboardSpec(n=6, grids=("thirds",)))

    dur = check_episode._duration(str(ep))
    cspec = models.CheckSpec(composition="lead", grid="thirds", target_dur=dur)
    report = check_episode.run(str(ep), str(rp), str(pp), cspec, str(tmp_path / "r.json"))
    assert report.checks["black_frames"].passed is True
    assert report.checks["on_line"].passed is True    # real composition holds
    assert report.checks["jitter"].passed is True
    assert report.checks["continuity"].passed is True  # no ID-switch teleports
