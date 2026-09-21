"""Real-bytes proofs for the 2026-09-21 unvalidated-shapes slice.

Only one of the four items in that slice has a claim that real bytes can settle:
that a stream ffprobe cannot describe actually reaches color's depth guard. The
other three are pure-Python shape defects and are proven in tests/lib and
tests/test_check_episode.py, which need no ffmpeg.
"""
import pytest

from scripts import reframe
from scripts.lib import color

pytestmark = pytest.mark.integration


def test_ffprobe_omits_pix_fmt_for_a_codec_this_build_cannot_open(undescribable_plane):
    """The premise of color.refuse_ungradeable_plane's third clause, measured
    rather than assumed: four of the five values survive and the fifth is gone."""
    w, h, fps, dur, pix_fmt, color_range = reframe._probe(str(undescribable_plane))
    assert (w, h) == (1280, 720)          # from the stsd box, not the codec
    assert fps > 0 and dur > 0            # from stts and mvhd
    assert color_range == "tv"            # from the colr box
    assert pix_fmt == ""                  # the codec's, and the codec did not open


def test_the_depth_guard_refuses_that_stream_instead_of_calling_it_eight_bit(undescribable_plane):
    _, _, _, _, pix_fmt, color_range = reframe._probe(str(undescribable_plane))
    assert color.plane_depth(pix_fmt) == 8      # the wrong answer the guard prevents
    with pytest.raises(ValueError, match="pix_fmt"):
        color.refuse_ungradeable_plane(pix_fmt, color_range, str(undescribable_plane))


def test_the_control_the_same_segment_unpatched_passes_the_guard(golden_ride_segment):
    """Without this the test above proves only that SOMETHING about the file is
    refused. The segment fixture differs from the patched one by four bytes."""
    _, _, _, _, pix_fmt, color_range = reframe._probe(str(golden_ride_segment))
    assert pix_fmt == "yuv420p" and color_range == "tv"
    assert color.refuse_ungradeable_plane(pix_fmt, color_range,
                                          str(golden_ride_segment)) is None
