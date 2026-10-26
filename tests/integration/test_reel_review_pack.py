"""reel_review pack against real pixels (retro 2026-10-16 S14): the stills come out of
the delivered file as images, and the prompt names them with nothing left to fill."""
import json
import shutil

import numpy as np
import pytest
from PIL import Image

from scripts import deliver
from scripts import reel_review
from scripts.lib import assembly, ffbin, proc, prompts, provenance
from scripts.lib.models import REEL_H264, ReelEpisode, ReelManifest, ReelReport


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


def _grey(path, secs: float) -> str:
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i",
              f"color=c=0x808080:s=180x320:d={secs}:r=30", "-t", f"{secs}",
              "-pix_fmt", "yuv420p", str(path)])
    return str(path)


@pytest.mark.integration
def test_the_ending_still_of_an_accented_closer_is_not_the_flash(tmp_path):
    """Review I1 on real pixels: a 3 s episode, then a 1 s accented one delivered with
    its flash. The ending still's clamp (1 s before the end) is the flash's cut, so a
    pack blind to the flash would hand the colour axis a frame 85% of the way to white
    (the control below reads it); this one grabs the grey a frame before the window."""
    try:
        ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    reel_dir = tmp_path / "montage" / "reels" / "main"
    for sub in ("episodes", "deliveries", "build/reel"):
        (reel_dir / sub).mkdir(parents=True)
    eps = [ReelEpisode(manifest={"segment": "s.mp4", "target_dur": d},
                       clip=_grey(reel_dir / "episodes" / f"ep{i}.mp4", d),
                       route=None, path="", meta="")
           for i, d in enumerate((3.0, 1.0))]
    ReelManifest(episodes=eps, target_dur=4.0, shutters=(1,)).write(
        reel_dir / "episodes" / "EPISODES.json")
    master = _grey(tmp_path / "master.mp4", 4.0)
    rep = ReelReport(checks={}, master_digest=provenance.digest_file(master))
    (reel_dir / "build" / "reel" / "reel_report.json").write_text(json.dumps(rep.to_dict()))
    (reel_dir / "EDL.md").write_text("# EDL\n")
    reel = deliver.deliver(master, REEL_H264, str(reel_dir / "deliveries"), "accent", rep,
                           scratch_dir=str(tmp_path / "scratch"), flashes=[3.0])

    res = reel_review.pack(reel, str(reel_dir))

    stills = {s.rsplit("/", 1)[1]: np.asarray(Image.open(s), float) for s in res["stills"]}
    assert abs(stills["ending.png"].mean() - 128.0) < 4.0
    assert all(abs(a.mean() - 128.0) < 4.0 for a in stills.values())
    on_cut = assembly.frames_rgb(reel, [3.0], assembly.probe_stream(reel).fps)[0]
    assert on_cut.mean() > 200.0                  # the control: the blind still's frame
