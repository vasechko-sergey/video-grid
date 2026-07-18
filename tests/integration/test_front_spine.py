"""Real-ffmpeg whole-conveyor proof for the Front-half SP1 extract spine (design
docs/specs/2026-07-11-extract-spine-design.md): a hand-authored EDL.json →
edl_to_reel → a delivered REEL_v1.mp4. Real extract, assemble, check_reel gates,
mix, deliver mux — process_episode's WHOLE mechanical middle (tracking AND
reframe's crop-to-canvas AND check_episode) is faked, because the synthetic
sample_clip is a box, not a person, so real YOLO tracking returns an empty route.
This proves the EDL -> driver -> build_reel -> deliver WIRING on real bytes; it
deliberately does NOT prove pixel-level canvas/crop correctness — the delivered
reel keeps the source dims, not the project canvas. Crop-to-canvas is covered by
process_episode's own real-footage goldens (test_process_episode / test_golden)."""
import json
import pytest
from pathlib import Path
from scripts import edl_to_reel
from scripts.lib import proc


def _project(tmp_path):
    p = tmp_path / "project.json"
    p.write_text(json.dumps({"purpose": "reel", "canvas": [1080, 1920], "delivery": "native"}))
    return str(p)


def _edl(tmp_path, source, music=None):
    # two windows far apart → the box sits at very different x → distinct phash (variety)
    row = lambda s, d: dict(source=source, start=s, dur=d, shot_type="wide",
                            composition="lead", grid="thirds", crop_scale=0.8)
    doc = {"episodes": [row(0.2, 1.0), row(1.8, 1.0)]}
    if music:
        doc["music"] = music
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps(doc))
    return str(p)


def _fake_track_pe(monkeypatch):
    """Stub process_episode with a faithful-enough stand-in: write a real route.json
    and a real SILENT video-only clip (copy of the segment, like a real reframe's
    -an output). This fakes process_episode's ENTIRE mechanical middle — tracking
    AND reframe's crop-to-canvas AND check_episode — because the synthetic sample_clip
    is a box, not a person, so real YOLO tracking returns an empty route. Consequence:
    this golden proves the EDL -> driver -> build_reel -> deliver WIRING on real bytes
    (real extract, assemble, check_reel gates, mix, deliver mux). It deliberately does
    NOT prove pixel-level canvas/crop correctness — the delivered reel keeps the source
    dims, not the project canvas. That the resolved canvas flows into each manifest is
    pinned by the Task 4 unit test; crop-to-canvas is covered by process_episode's own
    real-footage goldens (test_process_episode / test_golden)."""
    def fake_pe(manifest, project_dir, route_path=None, color_correct=None):
        Path(project_dir).mkdir(parents=True, exist_ok=True)
        (Path(project_dir) / "route.json").write_text(
            json.dumps([{"t": 0.0, "x": 960, "y": 540, "w": 120, "h": 120, "id": 1}]))
        # real process_episode writes path.json + path.meta.json beside route.json on every
        # mechanical_pass (reframe emits both); mirror that so build_reel's frozen safe_zones
        # geometry reads real files. CropPath [0] is parallel to the single route point above;
        # a plain fill sidecar at the 1920x1080 source dims (safe_zones is advisory — these
        # tests don't assert it, so the values need only be valid, not "safe").
        (Path(project_dir) / "path.json").write_text(json.dumps([0]))
        (Path(project_dir) / "path.meta.json").write_text(json.dumps(
            {"mode": "fill", "crop_w": 1920, "crop_h": 1080, "crop_y": 0,
             "src_dims": [1920, 1080], "canvas": [1920, 1080], "out_dims": [1920, 1080],
             "rect_px": [0, 0, 1920, 1080], "freedom": 0}))
        proc.run(["ffmpeg", "-y", "-i", manifest["segment"], "-c:v", "copy", "-an", manifest["out_path"]])
        return {"status": "mechanical_pass", "clip": manifest["out_path"]}
    monkeypatch.setattr(edl_to_reel.process_episode, "process_episode", fake_pe)
    # process_episode is faked, but edl_to_reel calls track.ensure_model ITSELF above
    # the pool — unstubbed, this ffmpeg golden also constructs a real YOLO (importing
    # torch, and downloading 6MB on a cold cache) for a tracking pass it never runs.
    monkeypatch.setattr(edl_to_reel.track, "ensure_model", lambda m: None)


@pytest.mark.integration
def test_edl_drives_a_silent_reel_end_to_end(sample_clip, tmp_path, monkeypatch):
    _fake_track_pe(monkeypatch)
    res = edl_to_reel.edl_to_reel(
        _edl(tmp_path, sample_clip.name), _project(tmp_path),
        footage_root=str(sample_clip.parent), work_dir=str(tmp_path / "w"),
        out_dir=str(tmp_path / "out"))
    assert res["status"] == "delivered", res
    out = Path(res["output"])
    assert out.exists() and out.name == "REEL_v1.mp4"
    codecs = proc.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                       "stream=codec_type", "-of", "csv=p=0", str(out)]).stdout.decode()
    assert "video" in codecs


@pytest.mark.integration
def test_edl_drives_a_reel_with_music(sample_clip, tmp_path, monkeypatch):
    _fake_track_pe(monkeypatch)
    tone = tmp_path / "tone.wav"
    proc.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
              "-ac", "2", str(tone)])
    from scripts.lib.models import MusicSpec
    music = tmp_path / "MUSIC.json"
    music.write_text(json.dumps(MusicSpec(str(tone), 0.0, 2.0, 120.0, (0.0, 0.5, 1.0, 1.5), (0.3,), 2.0).to_dict()))
    res = edl_to_reel.edl_to_reel(
        _edl(tmp_path, sample_clip.name), _project(tmp_path),
        str(sample_clip.parent), str(tmp_path / "w"), str(tmp_path / "out"),
        music=str(music))
    assert res["status"] == "delivered", res
    audio = proc.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                      "stream=codec_name", "-of", "csv=p=0", str(Path(res["output"]))]).stdout.decode()
    assert "aac" in audio
