import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.lib import assembly
from scripts.lib.assembly import StreamInfo
from scripts import extract


def test_matches_is_true_only_when_all_fields_agree():
    ref = dict(dims=(606, 1080), fps=30.0)
    assert assembly.matches(StreamInfo(606, 1080, 30.0, "yuv420p", "h264"), **ref)
    assert not assembly.matches(StreamInfo(606, 1080, 59.94, "yuv420p", "h264"), **ref)
    assert not assembly.matches(StreamInfo(608, 1080, 30.0, "yuv420p", "h264"), **ref)
    assert not assembly.matches(StreamInfo(606, 1080, 30.0, "yuv444p", "h264"), **ref)
    assert not assembly.matches(StreamInfo(606, 1081, 30.0, "yuv420p", "h264"), **ref)   # h differs
    assert not assembly.matches(StreamInfo(606, 1080, 30.0, "yuv420p", "hevc"), **ref)   # vcodec differs


def test_matches_normalizes_only_a_foreign_explicit_range():
    from scripts.lib.assembly import StreamInfo, matches, DELIVERY_RANGE
    assert DELIVERY_RANGE == "tv"
    tv = StreamInfo(1080, 1920, 30.0, "yuv420p", "h264", "tv")
    pc = StreamInfo(1080, 1920, 30.0, "yuv420p", "h264", "pc")
    assert matches(tv, (1080, 1920), 30.0) is True
    assert matches(pc, (1080, 1920), 30.0) is False           # pc != DELIVERY_RANGE — a real foreign tag
    unknown = StreamInfo(1080, 1920, 30.0, "yuv420p", "h264", "unknown")
    assert matches(unknown, (1080, 1920), 30.0) is True       # untagged == this pipeline's own tv-by-convention output


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


def test_probe_stream_reports_missing_colour_range_as_unknown(tmp_path, monkeypatch):
    # ffprobe omits the color_range key entirely for an untagged stream (rather than
    # e.g. emitting "unknown" itself) — this is the exact JSON shape reframe's own
    # encoder output produces (it never passes -color_range). probe_stream must
    # normalize the missing key to the literal "unknown", not None or "".
    f = tmp_path / "e.mp4"
    f.write_text("x")
    payload = json.dumps({"streams": [{"width": 606, "height": 1080,
                                       "r_frame_rate": "30/1", "pix_fmt": "yuv420p",
                                       "codec_name": "h264"}]}).encode()   # no color_range key
    monkeypatch.setattr(assembly.proc, "run",
                        lambda cmd, **k: type("C", (), {"stdout": payload})())
    info = assembly.probe_stream(str(f))
    assert info.color_range == "unknown"


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


def _capture(monkeypatch, infos):
    """Mock probe_stream (per-path StreamInfo) + proc.run (record cmds)."""
    calls = []
    monkeypatch.setattr(assembly, "probe_stream", lambda p: infos[str(Path(p).name)])
    monkeypatch.setattr(assembly.proc, "run",
                        lambda cmd, **k: calls.append(cmd) or SimpleNamespace(stdout=b""))
    return calls


def _uniform():
    return StreamInfo(606, 1080, 30.0, "yuv420p", "h264")


def _untagged():
    # reframe's own encoder (scripts/reframe.py) never passes -color_range, so every
    # locked episode it writes probes as color_range="unknown" — never the delivery
    # target "tv" explicitly. This is the shape of a REAL reframe-produced episode.
    return StreamInfo(606, 1080, 30.0, "yuv420p", "h264", "unknown")


def test_uniform_episodes_concat_copy_without_reencode(tmp_path, monkeypatch):
    eps = [str(tmp_path / f"e{i}.mp4") for i in range(3)]
    calls = _capture(monkeypatch, {f"e{i}.mp4": _uniform() for i in range(3)})
    assembly.assemble(eps, (606, 1080), 30.0, str(tmp_path / "w" / "master.mp4"))
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "scale=" not in joined                    # nothing re-encoded
    assert "concat" in joined and "-c copy" in joined


def test_untagged_reframe_output_concats_copy_without_reencode(tmp_path, monkeypatch):
    # Anti-regression (Task 11 colour-stage review): a uniform reel of UNTAGGED
    # (reframe-style) episodes must still take the lossless -c copy path. An
    # untagged yuv420p stream IS limited-range ("tv") by mp4/h264 convention, so
    # "unknown" must be treated as delivery-compatible — never sent through
    # _normalize. Before the fix, matches() required color_range == "tv" exactly,
    # so EVERY reframe episode (always "unknown") failed the check and every reel
    # took a second lossy libx264 re-encode here, breaking the reel-back-half
    # invariant that assemble() is lossless and the one encode happens at deliver.
    eps = [str(tmp_path / f"e{i}.mp4") for i in range(3)]
    calls = _capture(monkeypatch, {f"e{i}.mp4": _untagged() for i in range(3)})
    assembly.assemble(eps, (606, 1080), 30.0, str(tmp_path / "w" / "master.mp4"))
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "scale=" not in joined                    # nothing re-encoded — no _normalize call
    assert "concat" in joined and "-c copy" in joined


def test_one_fps_outlier_is_normalized_alone(tmp_path, monkeypatch):
    eps = [str(tmp_path / f"e{i}.mp4") for i in range(3)]
    infos = {f"e{i}.mp4": _uniform() for i in range(3)}
    infos["e1.mp4"] = StreamInfo(606, 1080, 59.94, "yuv420p", "h264")
    calls = _capture(monkeypatch, infos)
    assembly.assemble(eps, (606, 1080), 30.0, str(tmp_path / "w" / "master.mp4"))
    scale_cmds = [c for c in calls if any("scale=606:1080" in str(x) for x in c)]
    assert len(scale_cmds) == 1                       # only the outlier


def test_assemble_zero_episodes_fails_loud(tmp_path):
    with pytest.raises(RuntimeError, match=">= 1 locked episode"):
        assembly.assemble([], (606, 1080), 30.0, str(tmp_path / "m.mp4"))


def test_concat_list_escapes_single_quotes_in_paths(tmp_path, monkeypatch):
    d = tmp_path / "O'Brien"
    d.mkdir()
    ep = d / "e0.mp4"
    _capture(monkeypatch, {"e0.mp4": _uniform()})
    assembly.assemble([str(ep)], (606, 1080), 30.0, str(tmp_path / "w" / "master.mp4"))
    listtext = (tmp_path / "w" / "_concat.txt").read_text()
    esc = str(ep.resolve()).replace("'", "'\\''")
    assert f"file '{esc}'" in listtext
    assert "'\\''" in listtext          # the ffmpeg-style escape is present


def test_concat_writes_resolved_escaped_listfile_and_copies(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(assembly.proc, "run",
                        lambda cmd, **k: calls.append(cmd) or SimpleNamespace(stdout=b""))
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    assembly.concat([str(a), str(b)], str(tmp_path / "w" / "m.mp4"))
    listtext = (tmp_path / "w" / "_concat.txt").read_text()
    assert f"file '{a.resolve()}'" in listtext and f"file '{b.resolve()}'" in listtext
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "concat" in joined and "-c copy" in joined


def test_probe_duration_is_the_shared_helper():
    # extract._probe_dur is promoted to assembly.probe_duration — one duration probe, shared.
    assert extract._probe_dur is assembly.probe_duration
    assert callable(assembly.probe_duration)


def _ffprobe_says(monkeypatch, payload: dict):
    seen = {}
    monkeypatch.setattr(assembly.proc, "run", lambda cmd, **k: (
        seen.setdefault("cmd", cmd), type("C", (), {"stdout": json.dumps(payload).encode()})())[1])
    return seen


def test_count_frames_counts_the_decoded_frames(monkeypatch):
    seen = _ffprobe_says(monkeypatch, {"streams": [{"nb_read_frames": "61"}]})
    assert assembly.count_frames("seg.mp4") == 61
    # COUNTED, by a decode — not the container's nb_frames, and not duration x rate
    assert "-count_frames" in seen["cmd"] and "stream=nb_read_frames" in seen["cmd"]


@pytest.mark.parametrize("payload", [{"streams": []}, {"streams": [{}]},
                                     {"streams": [{"nb_read_frames": "N/A"}]},
                                     {"streams": [{"nb_read_frames": "0"}]}])
def test_count_frames_refuses_a_stream_with_no_decodable_frame(monkeypatch, payload):
    _ffprobe_says(monkeypatch, payload)
    with pytest.raises(RuntimeError, match="seg.mp4 has no decodable video frame"):
        assembly.count_frames("seg.mp4")
