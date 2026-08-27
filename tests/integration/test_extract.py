import hashlib, json, subprocess
from pathlib import Path
import pytest
from scripts import extract
from scripts.lib import assembly, ffbin, proc
from scripts.lib.edl import EDL

def _duration(path):
    out = subprocess.run(
        [ffbin.ffprobe(), "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])


def _md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def _stream(path, field):
    out = subprocess.run(
        [ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0",
         "-show_entries", f"stream={field}", "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    return json.loads(out.stdout)["streams"][0].get(field)


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


@pytest.mark.integration
def test_normalizing_is_byte_identical_on_an_untagged_source(
        sample_clip, extract_unnormalized, tmp_path):
    """Control 1 of 3, and the one that protects every golden in this repo:
    every fixture here is untagged, ffmpeg reads untagged as limited, so the
    conversion is a no-op and the bytes must not move."""
    old = extract_unnormalized(sample_clip, 0.5, 1.0, tmp_path / "old.mp4")
    new = tmp_path / "new.mp4"
    extract.extract(src=str(sample_clip), start=0.5, dur=1.0, out=str(new))
    assert _md5(new) == _md5(old)


@pytest.mark.integration
def test_normalizing_is_byte_identical_on_an_explicitly_limited_source(
        sample_clip, extract_unnormalized, tmp_path):
    """Control 2 of 3: an untagged source and a tv-TAGGED source are different
    inputs to `in_range=auto`, and only one of them is covered above."""
    tagged = tmp_path / "tagged.mp4"
    # the bt709 description is required for the tag to be written at all — see
    # pc_ramp_clip's docstring; `-color_range tv` alone leaves ffprobe at "unknown"
    proc.run([ffbin.ffmpeg(), "-y", "-i", str(sample_clip), "-c:v", "libx264",
              "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
              "-color_range", "tv", "-color_primaries", "bt709",
              "-color_trc", "bt709", "-colorspace", "bt709", str(tagged)])
    assert _stream(tagged, "color_range") == "tv", "the control source is not tagged"

    old = extract_unnormalized(tagged, 0.5, 1.0, tmp_path / "old.mp4")
    new = tmp_path / "new.mp4"
    extract.extract(src=str(tagged), start=0.5, dur=1.0, out=str(new))
    assert _md5(new) == _md5(old)


@pytest.mark.integration
def test_normalizing_is_byte_identical_on_a_ten_bit_source(
        tenbit_clip, extract_unnormalized, tmp_path):
    """Control 3 of 3: the depth conversion `-pix_fmt yuv420p` already performs
    must not change because a range filter joined the chain."""
    old = extract_unnormalized(tenbit_clip, 0.2, 0.5, tmp_path / "old.mp4")
    new = tmp_path / "new.mp4"
    extract.extract(src=str(tenbit_clip), start=0.2, dur=0.5, out=str(new))
    assert _stream(new, "pix_fmt") == "yuv420p"
    assert _md5(new) == _md5(old)


@pytest.mark.integration
def test_a_full_range_source_comes_out_limited(
        pc_ramp_clip, extract_unnormalized, tmp_path):
    """The change itself. Note what the control proves: today's command READS as
    a normalization and is not one — libx264 keeps full range for a full-range
    input. That is the entire defect."""
    old = extract_unnormalized(pc_ramp_clip, 0.2, 1.0, tmp_path / "old.mp4")
    new = tmp_path / "new.mp4"
    extract.extract(src=str(pc_ramp_clip), start=0.2, dur=1.0, out=str(new))
    assert (_stream(old, "color_range"), _stream(old, "pix_fmt")) == ("pc", "yuvj420p")
    assert (_stream(new, "color_range"), _stream(new, "pix_fmt")) == ("tv", "yuv420p")
    assert _md5(new) != _md5(old)


@pytest.mark.integration
def test_normalizing_leaves_the_resolution_alone(sample_clip, tmp_path):
    """The scale filter carries no dimensions on purpose: reframe crops from
    native pixels, so a downscale here would discard exactly the detail a 4K
    source was shot for (design §3)."""
    out = tmp_path / "seg.mp4"
    extract.extract(src=str(sample_clip), start=0.5, dur=1.0, out=str(out))
    assert (_stream(out, "width"), _stream(out, "height")) == (1920, 1080)


@pytest.mark.integration
def test_the_golden_fixture_is_raw_footage_and_its_segment_is_not(golden_ride_segment):
    """The committed golden fixture is genuinely full-range camera footage, and
    that is why reframe cannot be handed it directly. If someone ever normalizes
    the committed file in place, this test says so out loud rather than letting
    `golden_ride_segment` quietly become a no-op copy."""
    raw = Path(__file__).parent.parent / "fixtures" / "golden_ride.mp4"
    assert (_stream(raw, "pix_fmt"), _stream(raw, "color_range")) == ("yuvj420p", "pc")
    assert (_stream(golden_ride_segment, "pix_fmt"),
            _stream(golden_ride_segment, "color_range")) == ("yuv420p", "tv")


@pytest.mark.integration
def test_normalising_the_golden_fixture_preserves_its_timeline(golden_ride_segment):
    """golden_route.json is sampled against this clip's own timeline, so the
    normalization must move the range and nothing else. Measured: 1280x720,
    60000/1001, 95 frames, 1.584917s — identical on both sides."""
    raw = Path(__file__).parent.parent / "fixtures" / "golden_ride.mp4"
    for field in ("width", "height", "r_frame_rate"):
        assert _stream(raw, field) == _stream(golden_ride_segment, field), field
    assert abs(_duration(raw) - _duration(golden_ride_segment)) < 0.001
