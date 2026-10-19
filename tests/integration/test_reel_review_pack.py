"""reel_review pack against real pixels (retro 2026-10-16 S14): the stills come out of
the delivered file as images, and the prompt names them with nothing left to fill."""
import json
import shutil

import numpy as np
import pytest
from PIL import Image

from scripts import reel_review
from scripts.lib import prompts
from scripts.lib.models import ReelEpisode, ReelManifest


@pytest.mark.integration
def test_pack_grabs_real_stills_and_fills_every_token(tmp_path, sample_clip):
    reel_dir = tmp_path / "montage" / "reels" / "main"
    for sub in ("episodes", "deliveries", "build/reel"):
        (reel_dir / sub).mkdir(parents=True)
    clip = reel_dir / "episodes" / "ep0.mp4"
    shutil.copy(sample_clip, clip)
    ReelManifest(episodes=[ReelEpisode(manifest={"segment": "s.mp4", "target_dur": 3.0},
                                       clip=str(clip), route=None, path="", meta="")],
                 target_dur=3.0).write(reel_dir / "episodes" / "EPISODES.json")
    reel = reel_dir / "deliveries" / "REEL_v1.mp4"
    shutil.copy(sample_clip, reel)
    (reel_dir / "EDL.md").write_text("# EDL\n")
    (reel_dir / "build" / "reel" / "reel_report.json").write_text(json.dumps({"overall": True}))

    res = reel_review.pack(str(reel), str(reel_dir))

    assert [s.rsplit("/", 1)[1] for s in res["stills"]] == ["hook.png", "ending.png", "mid0.png"]
    for s in res["stills"]:
        arr = np.asarray(Image.open(s))
        assert arr.ndim == 3 and arr.shape[2] == 3 and arr.std() > 0   # a real frame, not a blank
    text = (reel_dir / "build" / "_review" / "reviewer_prompt.md").read_text()
    assert prompts.tokens(text) == set()
    assert res["report_bound"] is False                               # no attestation beside it
