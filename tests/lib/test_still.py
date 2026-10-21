"""lib/still: the one photo decoder and the subject rule (design 2026-10-20 §1, §2)."""
import io
import shutil
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageCms

from scripts.lib import still
from scripts.lib.kenburns import Rect

P3_ICC = Path("/System/Library/ColorSync/Profiles/Display P3.icc")
needs_sips = pytest.mark.skipif(shutil.which("sips") is None, reason="macOS sips makes HEIC fixtures")
needs_p3 = pytest.mark.skipif(not P3_ICC.exists(), reason="macOS Display P3 profile")

RED, BLUE = (255, 0, 0), (30, 120, 200)


def _marked(w=1200, h=800) -> Image.Image:
    """Blue, with a red block in the STORED top-left corner."""
    im = Image.new("RGB", (w, h), BLUE)
    im.paste(Image.new("RGB", (w // 4, h // 4), RED), (0, 0))
    return im


def _oriented_jpeg(path: Path, tag: int) -> Path:
    ex = Image.Exif()
    ex[0x0112] = tag
    _marked().save(path, exif=ex.tobytes(), quality=95)
    return path


def _near(px, want, tol=6) -> bool:
    return all(abs(int(a) - b) <= tol for a, b in zip(px, want))


def test_a_jpeg_is_turned_upright_by_its_exif_tag(tmp_path):
    st = still.load(_oriented_jpeg(tmp_path / "o6.jpg", 6))
    assert st.dims == (800, 1200)
    assert _near(st.rgb[5, 800 - 6], RED)           # tag 6: stored top-left shows top-right
    assert _near(st.rgb[5, 5], BLUE)
    assert st.record["orientation"] == 6 and st.record["source_dims"] == [1200, 800]


@needs_sips
def test_a_heic_is_turned_once_not_twice(tmp_path):
    """sips writes the rotation into the HEIF's own properties; libheif applies them and
    pi_heif resets the EXIF tag, so applying the tag again would turn it a second time."""
    jpg = _oriented_jpeg(tmp_path / "o6.jpg", 6)
    heic = tmp_path / "o6.heic"
    subprocess.run(["sips", "-s", "format", "heic", str(jpg), "--out", str(heic)],
                   check=True, capture_output=True)
    st = still.load(heic)
    assert st.dims == (800, 1200)
    assert _near(st.rgb[5, 800 - 6], RED, tol=10)
    assert st.record["decoder"] == "HEIF" and "libheif" in st.record["orientation"]


def _p3_jpeg(path: Path) -> Path:
    src = _marked()
    p3 = ImageCms.getOpenProfile(str(P3_ICC))
    ImageCms.profileToProfile(src, ImageCms.createProfile("sRGB"), p3,
                              outputMode="RGB").save(path, quality=98,
                                                     icc_profile=p3.tobytes())
    return path


@needs_p3
def test_a_display_p3_photo_is_converted_to_srgb(tmp_path):
    jpg = _p3_jpeg(tmp_path / "p3.jpg")
    st = still.load(jpg)
    assert st.record["icc"] == "Display P3"
    assert _near(st.rgb[10, 10], RED) and _near(st.rgb[600, 900], BLUE)
    # the control: the same file read without the profile is the silent landmine
    raw = np.asarray(Image.open(jpg).convert("RGB"))
    assert abs(int(raw[10, 10][0]) - 255) > 15 and abs(int(raw[10, 10][1]) - 0) > 30


@needs_p3
@needs_sips
def test_a_display_p3_heic_is_converted_too(tmp_path):
    png = tmp_path / "p3.png"
    _marked().save(png)
    p3png = tmp_path / "p3m.png"
    subprocess.run(["sips", "--matchTo", str(P3_ICC), str(png), "--out", str(p3png)],
                   check=True, capture_output=True)
    heic = tmp_path / "p3.heic"
    subprocess.run(["sips", "-s", "format", "heic", str(p3png), "--out", str(heic)],
                   check=True, capture_output=True)
    st = still.load(heic)
    assert st.record["icc"] == "Display P3"
    assert _near(st.rgb[10, 10], RED, tol=10) and _near(st.rgb[600, 900], BLUE, tol=6)


def test_no_profile_reads_as_srgb_untouched(tmp_path):
    p = tmp_path / "plain.png"
    _marked().save(p)
    st = still.load(p)
    assert st.record["icc"] is None
    assert tuple(st.rgb[10, 10]) == RED and tuple(st.rgb[600, 900]) == BLUE


def test_the_long_side_is_capped(tmp_path):
    p = tmp_path / "big.png"
    _marked(5000, 3000).save(p)
    st = still.load(p)
    assert st.dims == (4096, 2458)
    assert st.record["scaled_to_long_side"] == still.MAX_LONG_SIDE
    assert st.record["source_dims"] == [5000, 3000]


def test_an_alpha_png_reads_as_rgb_and_says_so(tmp_path):
    p = tmp_path / "a.png"
    Image.new("RGBA", (40, 30), (10, 20, 30, 128)).save(p)
    st = still.load(p)
    assert st.rgb.shape == (30, 40, 3) and st.record["mode"] == "RGBA read as RGB"


def test_a_file_that_is_not_a_photo_is_refused_by_name(tmp_path):
    p = tmp_path / "broken.jpg"
    p.write_bytes(b"not a jpeg")
    with pytest.raises(ValueError, match="broken.jpg: not a photo"):
        still.load(p)


def test_the_subject_is_the_union_of_the_people_who_matter():
    boxes = [(100, 200, 50, 100), (180, 210, 40, 90), (900, 100, 10, 20)]   # cx, cy, w, h
    s = still.subject(boxes)
    assert s == Rect(75.0, 150.0, 125.0, 105.0)        # the stranger (200 px²) is left out
    assert still.subject([]) is None


def test_people_asks_yolo_for_persons_at_the_trackers_size(monkeypatch):
    seen = {}

    class _Box:
        def __init__(self, xywh):
            self.xywh = [xywh]

    class _Res:
        boxes = [_Box((10, 10, 4, 4)), _Box((50, 50, 20, 30))]

    class _YOLO:
        def __init__(self, path):
            seen["path"] = path

        def predict(self, img, **kw):
            seen.update(kw, img=img)
            return [_Res()]

    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=_YOLO))
    got = still.people(np.zeros((8, 8, 3), np.uint8), "m.pt")
    assert got == [(50.0, 50.0, 20.0, 30.0), (10.0, 10.0, 4.0, 4.0)]     # largest first
    assert seen["path"] == "m.pt" and seen["classes"] == [0] and seen["imgsz"] == 960
    assert isinstance(seen["img"], Image.Image)        # PIL = RGB; a bare array reads as BGR


def test_a_16_bit_grey_png_is_scaled_not_clipped_to_white(tmp_path):
    """The 2026-10-20 review's I4: Pillow's convert() clips 16-bit values at 255."""
    ramp = (np.linspace(0, 65535, 256, dtype=np.float64)[None, :].repeat(8, 0)).astype(np.uint16)
    p = tmp_path / "g16.png"
    Image.fromarray(ramp).save(p)
    assert Image.open(p).mode.startswith("I;16")
    st = still.load(p)
    assert st.rgb.shape == (8, 256, 3)
    assert abs(float(st.rgb.mean()) - 127.5) < 2 and st.rgb[0, 0, 0] == 0
    assert st.record["mode"].endswith("scaled to 8 bits")


def test_a_32_bit_image_is_refused_by_name(tmp_path):
    p = tmp_path / "i32.tif"
    Image.fromarray(np.zeros((4, 4), np.int32), "I").save(p)
    with pytest.raises(ValueError, match="32-bit integer"):
        still.load(p)


def test_a_grey_photo_with_alpha_reads_as_grey(tmp_path):
    p = tmp_path / "la.png"
    Image.new("LA", (10, 6), (90, 255)).save(p)
    st = still.load(p)
    assert tuple(st.rgb[2, 2]) == (90, 90, 90) and st.record["mode"] == "LA read as L"


def test_an_rgb_decode_beside_a_grey_profile_is_converted_not_refused(tmp_path):
    """A monochrome HEIC decodes to RGB with a grey ICC profile; a JPEG is the stand-in."""
    gray_icc = Path("/System/Library/ColorSync/Profiles/Generic Gray Gamma 2.2 Profile.icc")
    if not gray_icc.exists():
        pytest.skip("macOS grey profile")
    p = tmp_path / "mono.png"
    Image.new("RGB", (10, 6), (120, 120, 120)).save(p, icc_profile=gray_icc.read_bytes())
    st = still.load(p)
    assert st.rgb.shape == (6, 10, 3) and abs(int(st.rgb[2, 2, 0]) - 120) <= 6


def test_a_jpeg_named_heic_is_still_turned_by_its_exif_tag(tmp_path):
    src = _oriented_jpeg(tmp_path / "o6.jpg", 6)
    named = tmp_path / "IMG_9.HEIC"
    named.write_bytes(src.read_bytes())
    st = still.load(named)
    assert st.dims == (800, 1200) and _near(st.rgb[5, 800 - 6], RED)
    assert st.record["orientation"] == 6


# --- capture time (design 2026-10-21 §5) -------------------------------------------

def _dated_jpeg(path: Path, date=None, subsec=None, offset=None, im=None) -> Path:
    """A JPEG whose EXIF IFD carries the three capture-time tags given (None = absent)."""
    ex = Image.Exif()
    ifd = ex.get_ifd(still.EXIF_IFD)
    for tag, v in ((still.DATE_ORIGINAL, date), (still.SUBSEC_ORIGINAL, subsec),
                   (still.OFFSET_ORIGINAL, offset)):
        if v is not None:
            ifd[tag] = v
    (im or _marked(64, 48)).save(path, exif=ex.tobytes(), quality=95)
    return path


def _epoch(*ymdhms, tz=0.0) -> float:
    import datetime as dt
    return dt.datetime(*ymdhms, tzinfo=dt.timezone(dt.timedelta(hours=tz))).timestamp()


def test_the_capture_time_is_read_from_exif_with_subseconds_and_offset(tmp_path):
    st = still.load(_dated_jpeg(tmp_path / "a.jpg", "2026:10:21 12:34:56", "25", "+02:00"))
    assert st.record["taken"] == _epoch(2026, 10, 21, 12, 34, 56, tz=2.0) + 0.25


@pytest.mark.parametrize("sub, frac", [("5", 0.5), ("007", 0.007), ("12345", 0.12345)])
def test_subseconds_are_digits_of_a_fraction_not_a_count(tmp_path, sub, frac):
    # three digits alone cannot tell a fraction from a millisecond count: "5" and
    # "12345" can
    st = still.load(_dated_jpeg(tmp_path / "a.jpg", "2026:10:21 12:34:56", sub, "-05:30"))
    assert st.record["taken"] == _epoch(2026, 10, 21, 12, 34, 56, tz=-5.5) + frac


def test_a_date_without_subseconds_or_offset_is_read_as_whole_seconds_utc(tmp_path):
    st = still.load(_dated_jpeg(tmp_path / "a.jpg", "2026:10:21 12:34:56"))
    assert st.record["taken"] == _epoch(2026, 10, 21, 12, 34, 56)


def test_two_photos_a_burst_apart_differ_by_the_burst_interval(tmp_path):
    a = still.load(_dated_jpeg(tmp_path / "a.jpg", "2026:10:21 12:34:56", "900"))
    b = still.load(_dated_jpeg(tmp_path / "b.jpg", "2026:10:21 12:34:57", "200"))
    assert round(b.record["taken"] - a.record["taken"], 6) == 0.3


def test_a_photo_without_a_capture_time_has_no_taken_key(tmp_path):
    p = tmp_path / "plain.png"
    _marked(64, 48).save(p)
    assert "taken" not in still.load(p).record
    assert "taken" not in still.load(_dated_jpeg(tmp_path / "o.jpg", subsec="5",
                                                 offset="+01:00")).record


@pytest.mark.parametrize("date", ["garbage", "0000:00:00 00:00:00", "2026:13:40 99:99:99",
                                  "2026-10-21 12:34:56", ""])
def test_an_unparseable_date_is_absent_never_a_failure(tmp_path, date):
    st = still.load(_dated_jpeg(tmp_path / "a.jpg", date, "12", "+02:00"))
    assert "taken" not in st.record and st.dims == (64, 48)


def test_garbage_subseconds_and_offset_leave_the_date_standing(tmp_path):
    st = still.load(_dated_jpeg(tmp_path / "a.jpg", "2026:10:21 12:34:56", "x1", "zz"))
    assert st.record["taken"] == _epoch(2026, 10, 21, 12, 34, 56)


def test_garbage_exif_bytes_do_not_stop_the_decode(tmp_path):
    p = tmp_path / "g.jpg"
    _marked(64, 48).save(p, exif=b"Exif\x00\x00garbagegarbage")
    st = still.load(p)
    assert "taken" not in st.record and st.dims == (64, 48)


@needs_sips
def test_a_heic_carries_its_capture_time_the_same_way(tmp_path):
    """pi_heif cannot ENCODE (no HEIF encoder in its build), so sips writes the fixture;
    sips carries the JPEG's EXIF into the HEIF, and pi_heif hands it to Pillow."""
    jpg = _dated_jpeg(tmp_path / "a.jpg", "2026:10:21 12:34:56", "5", "+02:00")
    heic = tmp_path / "a.heic"
    subprocess.run(["sips", "-s", "format", "heic", str(jpg), "--out", str(heic)],
                   check=True, capture_output=True)
    st = still.load(heic)
    assert st.record["decoder"] == "HEIF"
    assert st.record["taken"] == _epoch(2026, 10, 21, 12, 34, 56, tz=2.0) + 0.5
