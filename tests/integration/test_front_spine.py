"""Real-ffmpeg whole-conveyor proof for the Front-half SP1 extract spine (design
docs/specs/2026-07-11-extract-spine-design.md): a hand-authored EDL.json →
edl_to_reel → a delivered REEL_v1.mp4. Real extract, assemble, check_reel gates,
mix, deliver mux — process_episode's WHOLE mechanical middle (tracking AND
reframe's crop-to-canvas AND check_episode) is faked, because the synthetic
sample_clip is a box, not a person, so real YOLO tracking returns an empty route.
This proves the EDL -> driver -> build_reel -> deliver WIRING on real bytes; it
deliberately does NOT prove pixel-level canvas/crop correctness — the delivered
reel keeps the source dims, not the project canvas. Crop-to-canvas is covered by
process_episode's own real-footage goldens (test_process_episode / test_golden).

Also proves the pan slice's reel-level wiring (design
docs/specs/2026-07-19-pan-design.md): an EDL episode carrying a `pan` must drive
edl_to_reel -> build_reel -> check_reel without check_reel's geometry section
crashing on the route.json a pan never writes."""
import json
import pytest
from pathlib import Path
from scripts import edl_to_reel
from scripts.lib import ffbin, proc


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
    def fake_pe(manifest, project_dir, route_path=None):
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
        proc.run([ffbin.ffmpeg(), "-y", "-i", manifest["segment"], "-c:v", "copy", "-an", manifest["out_path"]])
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
    codecs = proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", "v", "-show_entries",
                       "stream=codec_type", "-of", "csv=p=0", str(out)]).stdout.decode()
    assert "video" in codecs


@pytest.mark.integration
def test_edl_drives_a_reel_with_music(sample_clip, tmp_path, monkeypatch):
    _fake_track_pe(monkeypatch)
    tone = tmp_path / "tone.wav"
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
              "-ac", "2", str(tone)])
    from scripts.lib.models import MusicSpec
    music = tmp_path / "MUSIC.json"
    music.write_text(json.dumps(MusicSpec(str(tone), 0.0, 2.0, 120.0, (0.0, 0.5, 1.0, 1.5), (0.3,), 2.0).to_dict()))
    res = edl_to_reel.edl_to_reel(
        _edl(tmp_path, sample_clip.name), _project(tmp_path),
        str(sample_clip.parent), str(tmp_path / "w"), str(tmp_path / "out"),
        music=str(music))
    assert res["status"] == "delivered", res
    audio = proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", "a", "-show_entries",
                      "stream=codec_name", "-of", "csv=p=0", str(Path(res["output"]))]).stdout.decode()
    assert "aac" in audio


def _fake_track_or_pan_pe(monkeypatch):
    """Pan-aware sibling of _fake_track_pe (above): a pan episode — its resolved
    manifest carries a "pan" key — gets ONLY path.json + path.meta.json (pan=True)
    and deliberately NO route.json, mirroring what the real process_episode
    leaves on disk under a pan (design 2026-07-19 §6.1: an empty route.json
    already means "the tracker ran and found nobody", so none is written at
    all). A tracked episode (no "pan" key) still gets all three sidecars, exactly
    as _fake_track_pe. This is what lets the tests below exercise the REAL
    absence of route.json on disk, rather than a stand-in that always writes
    one — tests/lib/test_edl_to_reel.py's canned {"status": ...} results never
    touch the filesystem, so they cannot see this class of bug at all."""
    def fake_pe(manifest, project_dir, route_path=None):
        Path(project_dir).mkdir(parents=True, exist_ok=True)
        is_pan = manifest.get("pan") is not None
        if not is_pan:
            (Path(project_dir) / "route.json").write_text(
                json.dumps([{"t": 0.0, "x": 960, "y": 540, "w": 120, "h": 120, "id": 1}]))
        (Path(project_dir) / "path.json").write_text(json.dumps([0]))
        (Path(project_dir) / "path.meta.json").write_text(json.dumps(
            {"mode": "fill", "crop_w": 1920, "crop_h": 1080, "crop_y": 0,
             "src_dims": [1920, 1080], "canvas": [1920, 1080], "out_dims": [1920, 1080],
             "rect_px": [0, 0, 1920, 1080], "freedom": 0, "pan": is_pan}))
        proc.run([ffbin.ffmpeg(), "-y", "-i", manifest["segment"], "-c:v", "copy", "-an", manifest["out_path"]])
        return {"status": "mechanical_pass", "clip": manifest["out_path"]}
    monkeypatch.setattr(edl_to_reel.process_episode, "process_episode", fake_pe)
    monkeypatch.setattr(edl_to_reel.track, "ensure_model", lambda m: None)


def _spy_on_build_reel(monkeypatch):
    """Capture the ReelManifest edl_to_reel assembles, while still running the
    REAL build_reel (and therefore the real check_reel) underneath it — this is
    what lets a test assert on ReelEpisode.route without faking away the exact
    code path the regression lived in."""
    captured = {}
    real_build = edl_to_reel.build_reel.build_reel

    def spy(rm, *a, **kw):
        captured["rm"] = rm
        return real_build(rm, *a, **kw)
    monkeypatch.setattr(edl_to_reel.build_reel, "build_reel", spy)
    return captured


def _edl_all_pan(tmp_path, source):
    ep = dict(source=source, start=0.2, dur=1.0, shot_type="wide", composition="center",
              grid="thirds", crop_scale=0.8, pan={"from": 0.0, "to": 1.0})
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps({"episodes": [ep]}))
    return str(p)


def _edl_mixed(tmp_path, source):
    # same two far-apart windows _edl() uses above — distinct phash keeps the
    # variety check meaningful, not merely non-crashing
    tracked = dict(source=source, start=0.2, dur=1.0, shot_type="wide",
                   composition="lead", grid="thirds", crop_scale=0.8)
    panned = dict(source=source, start=1.8, dur=1.0, shot_type="wide",
                  composition="center", grid="thirds", crop_scale=0.8,
                  pan={"from": 0.0, "to": 1.0})
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps({"episodes": [tracked, panned]}))
    return str(p)


@pytest.mark.integration
def test_edl_with_a_pan_episode_drives_a_reel_without_the_route_it_never_wrote(
        sample_clip, tmp_path, monkeypatch):
    """THE REGRESSION the three-task pan-reel fix exists for (design
    docs/specs/2026-07-19-pan-design.md §2's consumer table; docs/build-status.md).
    edl_to_reel is the only multi-episode driver, and it used to build every
    ReelEpisode.route as str(epdir / "route.json") unconditionally — a name for
    a file a pan episode never writes. Every reel containing one died with
    FileNotFoundError inside check_reel's geometry section (fixed by caa6505,
    which branches check_reel on PathMeta.pan instead of opening a route
    unconditionally) — but only once edl_to_reel itself stops handing it a path
    to open (fixed here). This test runs the real edl_to_reel -> build_reel ->
    check_reel wiring end to end; tests/lib/test_edl_to_reel.py cannot see this
    class of bug because it fakes process_episode entirely and so never writes
    or fails to write a route file."""
    _fake_track_or_pan_pe(monkeypatch)
    captured = _spy_on_build_reel(monkeypatch)
    res = edl_to_reel.edl_to_reel(
        _edl_all_pan(tmp_path, sample_clip.name), _project(tmp_path),
        footage_root=str(sample_clip.parent), work_dir=str(tmp_path / "w"),
        out_dir=str(tmp_path / "out"))
    assert res["status"] == "delivered", res      # NOT a raised FileNotFoundError
    rm = captured["rm"]
    assert len(rm.episodes) == 1
    assert rm.episodes[0].route is None            # not merely falsy — no route.json to name
    assert not (tmp_path / "w" / "ep0" / "route.json").exists()   # the absence is real, on disk
    # an all-pan reel STATES the absence rather than passing vacuously (caa6505) —
    # proof that check_reel's real geometry branch actually ran on these files,
    # not that geometry was simply withheld
    assert res["report"]["checks"]["safe_zones"] == {
        "status": "not-checked", "advisory": True,
        "reason": "every episode is a generated pan — no tracked subject to project"}


@pytest.mark.integration
def test_edl_mixing_tracked_and_pan_episodes_keeps_the_tracked_route(
        sample_clip, tmp_path, monkeypatch):
    """The mixed shape edl_to_reel actually produces once an author pans one
    episode and tracks another: the pan's route stays None, and the tracked
    episode's route is a real, existing route.json path — this fix must not
    touch the non-pan branch."""
    _fake_track_or_pan_pe(monkeypatch)
    captured = _spy_on_build_reel(monkeypatch)
    res = edl_to_reel.edl_to_reel(
        _edl_mixed(tmp_path, sample_clip.name), _project(tmp_path),
        footage_root=str(sample_clip.parent), work_dir=str(tmp_path / "w"),
        out_dir=str(tmp_path / "out"))
    assert res["status"] == "delivered", res
    rm = captured["rm"]
    assert len(rm.episodes) == 2
    assert rm.episodes[0].route is not None and Path(rm.episodes[0].route).exists()
    assert rm.episodes[1].route is None
    assert not (tmp_path / "w" / "ep1" / "route.json").exists()
    # the branch, not merely the outcome: check_reel told the two episodes apart
    # via PathMeta.pan and NAMED ep1 as skipped, rather than silently folding it
    # into a passing "episodes: 2" count (caa6505)
    assert res["report"]["checks"]["safe_zones"]["skipped_episodes"] == [1]
    assert res["report"]["checks"]["key_action"]["skipped_episodes"] == [1]
