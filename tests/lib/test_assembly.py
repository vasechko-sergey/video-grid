import json
import pytest
from scripts.lib import assembly
from scripts.lib.assembly import StreamInfo


def test_matches_is_true_only_when_all_fields_agree():
    ref = dict(dims=(606, 1080), fps=30.0)
    assert assembly.matches(StreamInfo(606, 1080, 30.0, "yuv420p", "h264"), **ref)
    assert not assembly.matches(StreamInfo(606, 1080, 59.94, "yuv420p", "h264"), **ref)
    assert not assembly.matches(StreamInfo(608, 1080, 30.0, "yuv420p", "h264"), **ref)
    assert not assembly.matches(StreamInfo(606, 1080, 30.0, "yuv444p", "h264"), **ref)
    assert not assembly.matches(StreamInfo(606, 1081, 30.0, "yuv420p", "h264"), **ref)   # h differs
    assert not assembly.matches(StreamInfo(606, 1080, 30.0, "yuv420p", "hevc"), **ref)   # vcodec differs


def test_probe_stream_missing_file_fails_loud(tmp_path):
    with pytest.raises(RuntimeError, match="missing"):
        assembly.probe_stream(str(tmp_path / "nope.mp4"))


def test_probe_stream_no_video_stream_fails_loud(tmp_path, monkeypatch):
    f = tmp_path / "audio_only.mp4"
    f.write_text("x")
    monkeypatch.setattr(assembly.proc, "run",
                        lambda cmd, **k: type("C", (), {"stdout": b'{"streams": []}'})())
    with pytest.raises(RuntimeError, match="no video stream"):
        assembly.probe_stream(str(f))


def test_probe_stream_parses_fps_ratio(tmp_path, monkeypatch):
    f = tmp_path / "e.mp4"
    f.write_text("x")
    payload = json.dumps({"streams": [{"width": 606, "height": 1080,
                                       "r_frame_rate": "30000/1001", "pix_fmt": "yuv420p",
                                       "codec_name": "h264"}]}).encode()
    monkeypatch.setattr(assembly.proc, "run",
                        lambda cmd, **k: type("C", (), {"stdout": payload})())
    info = assembly.probe_stream(str(f))
    assert info.w == 606 and info.h == 1080 and abs(info.fps - 29.97) < 0.01


def test_probe_stream_zero_denominator_fails_loud(tmp_path, monkeypatch):
    f = tmp_path / "e.mp4"
    f.write_text("x")
    payload = json.dumps({"streams": [{"width": 606, "height": 1080,
                                       "r_frame_rate": "0/0", "pix_fmt": "yuv420p",
                                       "codec_name": "h264"}]}).encode()
    monkeypatch.setattr(assembly.proc, "run",
                        lambda cmd, **k: type("C", (), {"stdout": payload})())
    with pytest.raises(RuntimeError, match="unusable"):
        assembly.probe_stream(str(f))
