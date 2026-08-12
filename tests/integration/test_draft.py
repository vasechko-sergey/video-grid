"""Real-ffmpeg golden for assemble-draft (montage §5.9, design docs/specs/
2026-07-13-assemble-draft-design.md): a project.json + a hand EDL.json + a sine-tone
MUSIC.json over the synthetic sample_clip -> build_draft -> a labelled, canvas-fit
draft.mp4 with a muxed music bed. Unlike test_front_spine, process_episode is NOT in
the loop, so the draft's scale-fit is real: this also proves draft resolves cfg.canvas
(an ASPECT, e.g. reel's (9, 16) — never pixels) through Delivery into real delivered
pixels on real bytes, not the aspect tuple spent as pixels (the 8x16 postage-stamp
bug, design 2026-08-12 §1.3)."""
import json

import pytest

from scripts import draft
from scripts.lib import assembly, ffbin, geometry, proc
from scripts.lib.models import Delivery, MusicSpec


@pytest.fixture(autouse=True)
def _need_drawtext(need_filter):
    need_filter("drawtext")


def _project(tmp_path):
    p = tmp_path / "project.json"
    # canvas is the ASPECT PURPOSE_CANVAS actually gives "reel" — (9, 16), never
    # pixels — with delivery "native", the real QUALITY_DELIVERY default. A
    # hand-picked [1080, 1920] here would double as valid pixels AND a valid
    # aspect, masking the aspect-spent-as-pixels bug entirely (design 2026-08-12
    # §1.3) — which is exactly how it shipped undetected the first time.
    p.write_text(json.dumps({"purpose": "reel", "canvas": [9, 16], "delivery": "native"}))
    return str(p)


def _edl(tmp_path, source, music=None):
    row = lambda s, d, n: dict(source=source, start=s, dur=d, shot_type="wide",
                               composition="lead", grid="thirds", crop_scale=0.8,
                               processing_notes=n)
    doc = {"episodes": [row(0.2, 1.0, "track surfer, punch-in"), row(1.8, 1.0, "stabilize")]}
    if music:
        doc["music"] = music
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps(doc))
    return str(p)


def _dims(path):
    out = proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                    "stream=width,height", "-of", "csv=p=0:s=x", str(path)]).stdout.decode().strip()
    w, h = out.split("x")
    return int(w), int(h)


def _has_aac(path):
    return "aac" in proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", "a",
                              "-show_entries", "stream=codec_name", "-of", "csv=p=0",
                              str(path)]).stdout.decode()


def _expected_native_dims(sample_clip):
    """What draft SHOULD render for the (9, 16) canvas + native delivery _project()
    writes: fit the aspect into the SOURCE's own real, independently-probed pixels
    (the same don't-upscale fit layout.resolve uses for a native canvas — lib/
    layout.py:62), then run that real magnitude through Delivery. native has no
    size of its own, so hardcoding an expected pixel count here would be as wrong
    as the bug this test exists to catch; this derives it instead."""
    src_w, src_h = _dims(sample_clip)
    crop_w, crop_h = geometry.crop_for((9, 16), 1.0, src_w, src_h)
    canvas_w = float(crop_w)
    canvas_h = canvas_w * 16 / 9
    return Delivery.from_spec("native").dims(canvas_w, canvas_h)


@pytest.mark.integration
def test_draft_fits_canvas_and_muxes_music(sample_clip, tmp_path):
    tone = tmp_path / "tone.wav"
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
              "-ac", "2", str(tone)])
    music = tmp_path / "MUSIC.json"
    music.write_text(json.dumps(
        MusicSpec(str(tone), 0.0, 2.0, 120.0, (0.0, 0.5, 1.0, 1.5), (0.3,), 2.0).to_dict()))
    out = tmp_path / "draft.mp4"
    res = draft.build_draft(
        _edl(tmp_path, sample_clip.name, str(music)), _project(tmp_path),
        footage_root=str(sample_clip.parent), work_dir=str(tmp_path / "w"), out=str(out))
    assert res == {"status": "written", "draft": str(out), "episodes": 2, "music": True}
    assert out.exists()
    w, h = _dims(out)
    # the regression floor: an 8x16 postage stamp cannot pass this under any formula
    assert w >= 100 and h >= 100, f"draft rendered {w}x{h} -- looks like the canvas-aspect-as-pixels bug"
    assert (w, h) == _expected_native_dims(sample_clip)     # real letterbox -> delivered dims
    assert abs(assembly.probe_duration(str(out)) - 2.0) < 0.2
    assert _has_aac(out)


@pytest.mark.integration
def test_draft_without_music_is_silent(sample_clip, tmp_path):
    out = tmp_path / "draft.mp4"
    res = draft.build_draft(
        _edl(tmp_path, sample_clip.name), _project(tmp_path),
        str(sample_clip.parent), str(tmp_path / "w"), str(out))
    assert res["music"] is False and res["episodes"] == 2
    assert out.exists()
    w, h = _dims(out)
    assert w >= 100 and h >= 100, f"draft rendered {w}x{h} -- looks like the canvas-aspect-as-pixels bug"
    assert (w, h) == _expected_native_dims(sample_clip)
    assert not _has_aac(out)


@pytest.mark.integration
def test_draft_cli_builds_and_exits_0(sample_clip, tmp_path, monkeypatch):
    out = tmp_path / "draft.mp4"
    monkeypatch.setattr("sys.argv",
                        ["draft", "build", "--edl", _edl(tmp_path, sample_clip.name),
                         "--project", _project(tmp_path), "--footage-root", str(sample_clip.parent),
                         "--work-dir", str(tmp_path / "w"), "--out", str(out)])
    with pytest.raises(SystemExit) as e:
        draft.main()
    assert e.value.code == 0 and out.exists()
