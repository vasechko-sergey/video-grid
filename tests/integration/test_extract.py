import json, subprocess
import pytest
from scripts import extract
from scripts.lib import assembly
from scripts.lib.edl import EDL

def _duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])

@pytest.mark.integration
def test_extract_window_duration(sample_clip, tmp_path):
    out = tmp_path / "seg.mp4"
    extract.extract(src=str(sample_clip), start=1.0, dur=1.5, out=str(out))
    assert out.exists()
    assert abs(_duration(out) - 1.5) < 0.15   # frame-accurate re-encode


def _edl(episodes, **kw):
    return EDL.from_dict({"episodes": episodes, **kw})


def _row(source, start, dur):
    return dict(source=source, start=start, dur=dur, shot_type="wide",
                composition="lead", grid="thirds")


@pytest.mark.integration
def test_extract_edl_cuts_every_window_and_names_them_in_order(sample_clip, tmp_path):
    edl = _edl([_row(sample_clip.name, 0.2, 1.0), _row(sample_clip.name, 1.6, 1.0)])
    seg_dir = tmp_path / "segments"
    segs = extract.extract_edl(edl, footage_root=str(sample_clip.parent), seg_dir=str(seg_dir))
    assert segs == [str(seg_dir / "ep0_raw.mp4"), str(seg_dir / "ep1_raw.mp4")]
    for s, want in zip(segs, (1.0, 1.0)):
        assert abs(extract._probe_dur(s) - want) <= 1.0 / assembly.probe_stream(s).fps + 0.05


@pytest.mark.integration
def test_extract_edl_length_gate_trips_when_a_window_runs_past_eof(sample_clip, tmp_path):
    # sample_clip is 3.0s; a 2.0s window starting at 2.0s can only yield ~1.0s
    edl = _edl([_row(sample_clip.name, 2.0, 2.0)])
    with pytest.raises(ValueError, match="shorter than its 2.0s window|length"):
        extract.extract_edl(edl, str(sample_clip.parent), str(tmp_path / "segments"))


@pytest.mark.integration
def test_extract_edl_missing_source_names_the_resolved_path(tmp_path):
    edl = _edl([_row("nope.mp4", 0.0, 1.0)])
    with pytest.raises(ValueError, match="source not found"):
        extract.extract_edl(edl, str(tmp_path), str(tmp_path / "segments"))
