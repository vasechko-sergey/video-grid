import json
from pathlib import Path
import pytest
from scripts import reframe, storyboard, check_episode

FIX = Path(__file__).parent.parent / "fixtures"

@pytest.mark.integration
def test_golden_ride_pipeline(tmp_path):
    src = FIX / "golden_ride.mp4"
    route = json.loads((FIX / "golden_route.json").read_text())
    rp = tmp_path / "route.json"; rp.write_text(json.dumps(route))
    ep = tmp_path / "ep.mp4"; pp = tmp_path / "path.json"

    reframe.reframe(str(src), str(rp), str(ep), composition="lead",
                    grid="thirds", canvas=(9, 16),
                    color_means=(105, 122, 137), stabilize=False,
                    path_out=str(pp))
    storyboard.build(str(ep), str(tmp_path / "sheet.jpg"), n=6,
                     grids=("thirds",))

    src_w, src_h, _ = reframe._probe(str(src))
    dur = check_episode._duration(str(ep))
    report = check_episode.run(str(ep), str(rp), str(pp),
                               composition="lead", grid="thirds",
                               target_dur=dur, out=str(tmp_path / "r.json"),
                               src_dims=(src_w, src_h))
    assert report["checks"]["black_frames"]["pass"] is True
    assert report["checks"]["on_line"]["pass"] is True    # real composition holds
    assert report["checks"]["jitter"]["pass"] is True
    assert report["checks"]["continuity"]["pass"] is True  # no ID-switch teleports
