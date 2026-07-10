import json
import pytest
from scripts import extract, reframe, storyboard, check_episode
from scripts.lib import models

@pytest.mark.integration
def test_core_pipeline(sample_clip, tmp_path):
    seg = tmp_path / "seg.mp4"
    extract.extract(str(sample_clip), start=0.2, dur=2.0, out=str(seg))

    # route tracing the fixture box centre (x = 200 + t*430 + 70)
    route = [dict(t=i/30, x=270 + (i/30)*430, y=540, w=140, h=320)
             for i in range(60)]
    rp = tmp_path / "route.json"; rp.write_text(json.dumps(route))

    ep = tmp_path / "ep.mp4"; pp = tmp_path / "path.json"
    rspec = models.ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                               color_means=(105, 122, 137), delivery=models.Delivery("native"))
    reframe.reframe(rspec, str(seg), str(rp), str(ep), str(pp))

    storyboard.build(str(ep), str(tmp_path / "sheet.jpg"),
                     models.StoryboardSpec(n=6, grids=("thirds", "phi")))

    cspec = models.CheckSpec(composition="lead", grid="thirds", target_dur=2.0)
    report = check_episode.run(str(ep), str(rp), str(pp), cspec, str(tmp_path / "report.json"))
    assert ep.exists()
    assert (tmp_path / "sheet.jpg").exists()
    assert report.checks["black_frames"].passed is True
    assert "on_line" in report.checks
