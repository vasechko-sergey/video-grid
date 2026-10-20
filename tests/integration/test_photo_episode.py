"""A photo through the front half on real ffmpeg (design 2026-10-20 §2, §4, §5):
extract renders it beside a video window on the video's clock, then process_episode
crops the whole segment, tracks nothing and says so in the report."""
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from scripts import extract, process_episode
from scripts.lib import assembly, ffbin, proc
from scripts.lib.edl import EDL, EDLEpisode, preflight
from scripts.lib.models import PathMeta
from scripts.lib.project import ProjectConfig

pytestmark = pytest.mark.integration

ORANGE = (230, 120, 40)


def _photo(path, size):
    """A flat orange field with a dark figure-sized block right of centre."""
    w, h = size
    im = Image.new("RGB", size, ORANGE)
    im.paste(Image.new("RGB", (w // 8, h // 3), (20, 20, 30)), (int(w * 0.6), h // 3))
    im.save(path)
    return path


def _project(tmp_path, delivery="short_edge:360") -> ProjectConfig:
    p = tmp_path / "project.json"
    p.write_text(json.dumps({"canvas": [9, 16], "delivery": delivery, "purpose": "reel",
                             "quality": "preview"}))
    return ProjectConfig.from_json(p)


def _probe(path) -> dict:
    return json.loads(proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0",
                                "-show_streams", "-of", "json", str(path)]).stdout)["streams"][0]


@pytest.fixture
def run(tmp_path, sample_clip, monkeypatch):
    """A footage folder holding the sample clip, a portrait and a landscape photo; the
    subject pass is pinned to the figure block so the test does not depend on what a
    person detector makes of an orange rectangle."""
    root = tmp_path / "footage"
    root.mkdir()
    shutil.copy(sample_clip, root / "clip.mp4")
    # a 25 fps clip, so "the video's clock" cannot be told apart from extract's 30/1
    # default by accident (the review's M4: the sample clip IS 30/1)
    proc.run([ffbin.ffmpeg(), "-y", "-v", "error", "-f", "lavfi",
              "-i", "testsrc2=s=640x360:r=25:d=2", "-pix_fmt", "yuv420p",
              str(root / "clip25.mp4")])
    _photo(root / "IMG_P.png", (600, 800))
    _photo(root / "IMG_L.png", (800, 600))
    monkeypatch.setattr(extract.still, "people", lambda rgb, model: [
        (rgb.shape[1] * 0.6 + rgb.shape[1] / 16, rgb.shape[0] / 2, rgb.shape[1] / 8,
         rgb.shape[0] / 3)])
    monkeypatch.setattr(extract.track, "ensure_model", lambda m: None)
    return root


def _edl(*eps) -> EDL:
    return EDL(episodes=tuple(eps))


def _vid(source="clip.mp4"):
    return EDLEpisode(source=source, start=0.5, dur=1.0, shot_type="wide",
                      composition="center", grid="thirds")


def _pho(name, **kw):
    return EDLEpisode(source=name, start=0.0, dur=1.5, shot_type="medium",
                      composition="center", grid="thirds", **kw)


def test_a_portrait_photo_fills_the_canvas_on_the_videos_clock(run, tmp_path):
    seg = tmp_path / "segments"
    edl = _edl(_vid("clip25.mp4"), _pho("IMG_P.png", layout="fill"))
    segs = extract.extract_edl(edl, str(run), str(seg), project=_project(tmp_path))
    v, p = _probe(segs[0]), _probe(segs[1])
    assert (p["width"], p["height"]) == (360, 640)            # the delivered canvas
    assert v["r_frame_rate"] == "25/1"
    assert p["r_frame_rate"] == v["r_frame_rate"] and p["time_base"] == v["time_base"]
    assert p["color_space"] == "bt709" and p["color_range"] == "tv"
    assert assembly.probe_duration(segs[1]) == pytest.approx(1.5, abs=1 / 30 + 0.02)
    rec = json.loads((seg / "ep1_raw.still.json").read_text())
    assert rec["layout"] == "fill" and rec["frames"] == 38 and rec["people"] == 1   # 1.5s at 25
    assert rec["move"]["applied"] == {"from": 1.0, "to": 0.92} and rec["move"]["note"] == ""
    assert rec["first"][2] > rec["last"][2]                   # it pushed in


def test_a_landscape_photo_fits_and_reframe_lays_it_on_a_blurred_field(run, tmp_path):
    cfg = _project(tmp_path)
    edl = _edl(_pho("IMG_L.png", layout="fit"))
    seg_dir, out_dir = tmp_path / "segments", tmp_path / "episodes"
    (seg,) = extract.extract_edl(edl, str(run), str(seg_dir), project=cfg)
    p = _probe(seg)
    assert (p["width"], p["height"]) == (360, 270)            # the content rect, 4:3
    assert p["r_frame_rate"] == "30/1"                         # no video: the default clock
    mds, stop = preflight(edl, cfg, str(seg_dir), str(out_dir))
    assert stop is None and mds[0]["still"] is True
    out_dir.mkdir()
    res = process_episode.process_episode(mds[0], tmp_path / "ep0")
    assert res["status"] == "mechanical_pass", res
    checks = res["report"]["checks"]
    assert checks["framing"]["status"] == "editorial-only"
    assert checks["framing"]["reason"].startswith("photo")
    assert checks["continuity"]["status"] == "not-checked"
    o = _probe(mds[0]["out_path"])
    assert (o["width"], o["height"]) == (360, 640)
    meta = PathMeta.from_json(tmp_path / "ep0" / "path.meta.json")
    assert meta.still and not meta.pan and meta.freedom == 0
    frame = assembly.frames_rgb(mds[0]["out_path"], [0.5], 30.0)[0].astype(int)
    band = frame[20:100, :, :].reshape(-1, 3).mean(axis=0)     # the field above the photo
    assert np.abs(band - np.array(ORANGE)).max() < 40          # a blur of it, not black


def test_under_native_a_photo_takes_the_videos_canvas_not_its_own_pixels(run, tmp_path):
    """The review's I3: native keeps a crop's own pixels, and a photo's are thousands
    wide — first in the reel it set the canvas and every video was upscaled to it."""
    cfg = _project(tmp_path, delivery="native")
    edl = _edl(_pho("IMG_L.png", layout="fit"), _vid())
    segs = extract.extract_edl(edl, str(run), str(tmp_path / "s"), project=cfg)
    p = _probe(segs[0])
    assert (p["width"], p["height"]) == (606, 454)   # the 1080p clip's native 9:16 width
    # ...and laid out on the video's 606x1080 canvas, not on 606 x even(606*16/9) = 1076,
    # which would have the reel squash every video episode to match (the re-review)
    mds, stop = preflight(edl, cfg, str(tmp_path / "s"), str(tmp_path / "o"))
    (tmp_path / "o").mkdir()
    res = process_episode.process_episode(mds[0], tmp_path / "ep0")
    assert res["status"] == "mechanical_pass", res
    o = _probe(mds[0]["out_path"])
    assert (o["width"], o["height"]) == (606, 1080)


def test_a_reel_of_photos_alone_under_native_takes_the_first_photos_fill_canvas(run, tmp_path):
    cfg = _project(tmp_path, delivery="native")
    segs = extract.extract_edl(_edl(_pho("IMG_P.png", layout="fill"),
                                    _pho("IMG_L.png", layout="fit")), str(run),
                               str(tmp_path / "s"), project=cfg)
    a, b = _probe(segs[0]), _probe(segs[1])
    assert (a["width"], a["height"]) == (450, 800)   # a 9:16 crop of 600x800
    assert b["width"] == 450                         # the same canvas, not 800 wide
    plan = process_episode.plan_for(
        preflight(_edl(_pho("IMG_P.png", layout="fill"), _pho("IMG_L.png", layout="fit")),
                  cfg, str(tmp_path / "s"), str(tmp_path / "o"))[0][1], segs[1], None)
    assert (plan.rl.out_w, plan.rl.out_h) == (450, 800)


def test_a_photo_without_the_project_is_refused(run, tmp_path):
    with pytest.raises(ValueError, match="pass the project to extract_edl"):
        extract.extract_edl(_edl(_pho("IMG_P.png")), str(run), str(tmp_path / "s"))


def test_a_reel_of_photos_is_delivered_with_music(run, tmp_path):
    """The whole back half with nothing tracked: assemble, the silent-segment music bed,
    check_reel's geometry section over route-less episodes, deliver."""
    from scripts import edl_to_reel
    from scripts.lib.models import MusicSpec
    tone = tmp_path / "tone.wav"
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
              "-ac", "2", str(tone)])
    music = tmp_path / "MUSIC.json"
    music.write_text(json.dumps(MusicSpec(str(tone), 0.0, 2.0, 120.0, (0.0, 0.5, 1.0, 1.5),
                                          (0.3,), 2.0).to_dict()))
    edl = tmp_path / "EDL.json"
    edl.write_text(json.dumps({"episodes": [
        dict(source="IMG_P.png", start=0.0, dur=1.0, shot_type="medium",
             composition="center", grid="thirds", layout="fill"),
        dict(source="IMG_L.png", start=0.0, dur=1.0, shot_type="medium",
             composition="center", grid="thirds", layout="fit",
             still={"from": 0.95, "to": 1.0})]}))
    project = tmp_path / "project.json"
    project.write_text(json.dumps({"canvas": [9, 16], "delivery": "short_edge:360",
                                   "purpose": "reel", "quality": "preview"}))
    res = edl_to_reel.edl_to_reel(str(edl), str(project), footage_root=str(run),
                                  work_dir=str(tmp_path / "w"), out_dir=str(tmp_path / "out"),
                                  music=str(music))
    assert res["status"] == "delivered", res
    v = _probe(res["output"])
    assert (v["width"], v["height"]) == (360, 640)
    checks = res["report"]["checks"]
    assert checks["safe_zones"]["status"] == "not-checked"     # nothing tracked to project
    assert "photo" in checks["safe_zones"]["reason"]


def test_a_failing_still_escalates_once_instead_of_retrying(tmp_path, monkeypatch):
    """A still's path is a constant: every retry would render the same pixels."""
    from scripts import check_episode, reframe
    from scripts.lib import kenburns, models, still
    st = still.Still(rgb=np.full((640, 360, 3), 128, np.uint8), record={})
    seg = tmp_path / "seg.mp4"
    still.render(st, [kenburns.Rect(0.0, 0.0, 360.0, 640.0)] * 30, (360, 640), "30/1", str(seg))
    calls = []
    real = reframe.reframe
    monkeypatch.setattr(reframe, "reframe", lambda *a, **k: calls.append(1) or real(*a, **k))
    monkeypatch.setattr(check_episode, "run", lambda *a, **k: models.Report(
        checks={"jitter": models.CheckResult("jitter", False, {"worst_reversal": 99.0})}))
    md = {"segment": str(seg), "out_path": str(tmp_path / "o.mp4"), "composition": "center",
          "grid": "thirds", "canvas": [9, 16], "target_dur": 1.0, "still": True,
          "delivery": "short_edge:360"}
    res = process_episode.process_episode(md, str(tmp_path / "p"))
    assert (res["status"], res["reason"]) == ("escalate", "still-not-retryable")
    assert len(calls) == 1


def test_a_photo_crosses_the_geometry_split(run, tmp_path):
    """The router's real road: --stop-after-geometry freezes a photo with no route, and
    --from-geometry renders it over the segment phase 1a cut."""
    from scripts import edl_to_reel
    edl = tmp_path / "EDL.json"
    edl.write_text(json.dumps({"episodes": [
        dict(source="IMG_P.png", start=0.0, dur=1.0, shot_type="medium",
             composition="center", grid="thirds"),
        dict(source="IMG_L.png", start=0.0, dur=1.0, shot_type="medium",
             composition="center", grid="thirds", still={"from": 0.95, "to": 1.0})]}))
    project = tmp_path / "project.json"
    project.write_text(json.dumps({"canvas": [9, 16], "delivery": "short_edge:360",
                                   "purpose": "reel", "quality": "preview"}))
    reel = tmp_path / "reels" / "main"
    work, out = str(reel / "build"), str(reel / "episodes")
    geo, stop = edl_to_reel.build_geometry(str(edl), str(project), str(run), work, out)
    assert stop is None and geo.episodes[0].route is None
    rm, stop = edl_to_reel.render_from_geometry(str(Path(out) / "GEOMETRY.json"),
                                                str(project), work, out)
    assert stop is None and rm.episodes[0].route is None
    assert (_probe(rm.episodes[0].clip)["width"], _probe(rm.episodes[0].clip)["height"]) == (
        360, 640)
