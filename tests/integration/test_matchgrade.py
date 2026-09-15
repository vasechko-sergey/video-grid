"""Real-ffmpeg proof of the conductor: two clips of different exposure, each with tonal
range, converge toward the median target once the authored tone_arg curve is rendered."""
import json
from pathlib import Path

import pytest
from scripts import match_grade
from scripts.color_measure import measure_profile
from scripts.lib import color, ffbin, matchgrade, moodpreset, proc, regions
from scripts.lib.edl import EDL, EDLEpisode
from scripts.lib.models import EpisodeGeometry, ReelGeometry

pytestmark = pytest.mark.integration


def _three_band(path, lo, mid, hi):
    """A clip whose left 1/4 is `lo`, middle 1/2 is `mid`, right 1/4 is `hi` — a real
    tonal range with well-separated p5 < p50 < p95 around a controllable exposure. A
    50/50 two-band frame would collapse p5==p50 (invalid tone_src); the 1:2:1 split keeps
    all three anchors apart. (Mirrors tests/integration/test_color_measure.py's lavfi pattern.)"""
    proc.run([ffbin.ffmpeg(), "-y",
              "-f", "lavfi", "-i", f"color=c={lo}:s=80x240:d=2:r=25",
              "-f", "lavfi", "-i", f"color=c={mid}:s=160x240:d=2:r=25",
              "-f", "lavfi", "-i", f"color=c={hi}:s=80x240:d=2:r=25",
              "-filter_complex", "hstack=inputs=3", "-pix_fmt", "yuv420p", str(path)])
    return path


def _ep(source):
    return EDLEpisode(source=source, start=0.0, dur=2.0, shot_type="wide",
                      composition="center", grid="thirds")


def _graded_profile(clip, src, dst, out):
    """Apply the REAL tone_arg curve (what reframe's grade_chain emits) and measure the result."""
    vf = color.tone_arg(src, dst).rstrip(",")            # strip the chain-joining comma
    proc.run([ffbin.ffmpeg(), "-y", "-i", str(clip), "-vf", vf, "-pix_fmt", "yuv420p", str(out)])
    return measure_profile(str(out))


def _whole_frame_geometry(tmp_path, sources, dur):
    """A GEOMETRY.json-shaped fixture whose crop IS the whole frame: canvas [4, 3]
    matches _three_band's own 320x240 aspect exactly, so a `fill` layout's freedom is
    0 and measure_crop reads the identical pixels measure_profile does (design
    2026-08-30 §1 pattern, mirroring tests/integration/test_color_measure.py's
    _banded_episode). This test's business is the REAL tone_arg curve converging real
    footage once conduct measures the crop, not the crop-vs-frame discrimination
    itself (test_color_measure.py owns that)."""
    eps = []
    for i, src in enumerate(sources):
        route = [dict(t=0.0, x=160.0, y=120.0, w=10.0, h=10.0),
                 dict(t=dur, x=160.0, y=120.0, w=10.0, h=10.0)]
        route_path = tmp_path / f"route{i}.json"
        route_path.write_text(json.dumps(route))
        manifest = {"segment": str(src), "out_path": f"ep{i}.mp4", "composition": "center",
                    "grid": "thirds", "canvas": [4, 3], "target_dur": dur}
        eps.append(EpisodeGeometry(manifest=manifest, route=str(route_path),
                                   source=str(src), project_dir=str(tmp_path / f"p{i}")))
    return ReelGeometry(episodes=tuple(eps), edl=str(tmp_path / "EDL.json"))


def test_authored_tone_converges_two_exposures(tmp_path):
    dark = _three_band(tmp_path / "d.mp4", "0x101010", "0x404040", "0x808080")
    bright = _three_band(tmp_path / "b.mp4", "0x505050", "0xA0A0A0", "0xE0E0E0")
    edl = EDL(episodes=(_ep("d.mp4"), _ep("b.mp4")))
    geo = _whole_frame_geometry(tmp_path, [dark, bright], dur=2.0)

    out, target, decisions, _ = match_grade.conduct(geo, edl)
    assert all(d.action == "author" for d in decisions)   # both deviate from the median

    p_dark, p_bright = measure_profile(str(dark)), measure_profile(str(bright))
    for k in range(3):                                    # target (median of 2) lies between the sources
        lo, hi = sorted((p_dark[k], p_bright[k]))
        assert lo <= target[k] <= hi

    src_spread = abs(p_dark[1] - p_bright[1])             # p50 gap before grading
    g_dark = _graded_profile(dark, out.episodes[0].tone_src, out.episodes[0].tone_dst,
                             tmp_path / "gd.mp4")
    g_bright = _graded_profile(bright, out.episodes[1].tone_src, out.episodes[1].tone_dst,
                               tmp_path / "gb.mp4")
    graded_spread = abs(g_dark[1] - g_bright[1])

    assert graded_spread < src_spread                     # the reel converged
    assert abs(g_dark[1] - target[1]) < abs(p_dark[1] - target[1])       # each moved toward target
    assert abs(g_bright[1] - target[1]) < abs(p_bright[1] - target[1])


def test_tone_arg_transfer_is_actually_emitted():
    # re-pinned 2026-08-19: the actuator the conductor feeds is a lutyuv LUT over
    # the Y plane, not an RGB spline.
    frag = color.tone_arg((10.0, 90.0, 150.0), (20.0, 110.0, 210.0))
    assert frag.startswith("lutyuv=y='") and frag.endswith("',")


def test_a_moody_bias_renders_darker_than_the_plain_median(tmp_path):
    """The visibility proof (design 2026-08-17 §7). Not 'the curve was built' — the
    delivered frame's own percentiles must sit below the unbiased render's, in the
    direction the preset asked for. Same clip, same source profile, two targets."""
    clip = _three_band(tmp_path / "m.mp4", "0x101010", "0x404040", "0x808080")
    prof = measure_profile(str(clip))
    plain = matchgrade.common_target([prof, (60.0, 130.0, 220.0)])
    moody, k = matchgrade.biased_target(plain, moodpreset.resolve("moody").tone_bias)
    assert k == 1.0                      # the fixture leaves room; if not, the test lies

    got_plain = _graded_profile(clip, prof, plain, tmp_path / "plain.mp4")
    got_moody = _graded_profile(clip, prof, moody, tmp_path / "moody.mp4")
    assert got_moody[0] < got_plain[0]   # shadows crushed
    assert got_moody[1] < got_plain[1]   # midtones darker


# --- the ruler: design 2026-08-19 §1 -----------------------------------------

def _grid(path, dark: int = 24, mid: int = 90, spark: int = 240):
    """Two exposure bands carrying FINE bright structure — 1px lines on a 16px pitch,
    so about 12% of pixels are bright and none of the bright regions is wider than a
    single pixel.

    Three levels because tone_arg needs p5 < p50 < p95 with a real gap between them,
    and fine bright structure because that is the thing a downscale destroys. Both
    constraints are arithmetic, not taste: p95 needs 5% of the frame above it (so a
    patch smaller than that can never reach it at any resolution — this fixture's
    first version was 0.25% and could not have worked), and what averaging removes is
    bright DETAIL, not bright area.

    1920 wide for the same kind of reason: `scale=160:-2` is a 12x linear reduction of
    a 1920 frame and only 1.5x of a 240 one. At 240 the mutation battery put the
    downscale back and both tests still passed — they were not measuring the
    instrument at all (rows 9 and 10, first pass)."""
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i", "color=c=black:s=1920x1080:d=1:r=25",
              "-vf", "format=gray,"
                     f"geq=lum='if(lt(mod(X,16),1)+lt(mod(Y,16),1),{spark},"
                     f"if(lt(X,W/2),{dark},{mid}))',format=yuv420p",
              "-frames:v", "1", str(path)])
    return path


def test_measure_profile_reads_the_frames_own_fine_highlights(tmp_path):
    """design §1. `scale=160:-2` reduced the area 12x before histogramming and read
    the run's drone frame's p95 NINE UNITS LOW (196 against 205) — specular
    highlights are small and bright, and averaging is what a downscale does.

    The control is the same frame's p5: a bulk statistic, which never moved. Without
    it "p95 is high" cannot be told from "the whole frame got brighter"."""
    clip = _grid(tmp_path / "grid.mp4")
    p5, _, p95 = measure_profile(str(clip), at=0.0)
    assert p95 > 200, f"the fine structure never reached p95 (got {p95}) — averaged away"
    assert p5 < 60, f"the dark bulk moved too ({p5}) — this is not a p95-only effect"


# --- the transfer itself: design 2026-08-19 §2 -------------------------------

def _ramp_y(frag: str) -> list[int]:
    """A lossless 256-step ramp through `frag`, in and out as the raw Y PLANE — one
    sample per input code, no encode and no pixel-format conversion anywhere.

    yuv444p in and not gray-then-format, which is the harness's own version of the
    trap this slice is about: `format=yuv444p` from a gray source runs swscale, and
    swscale converts full range to tv on the way, so code 16 arrives at the filter
    as 30 and every reading is shifted (measured while writing this test). Handing
    ffmpeg the plane directly leaves nothing between the codes and the LUT."""
    y = bytes(bytearray([x for x in range(256) for _ in range(8)]))
    raw = y + bytes([128]) * (2 * len(y))          # U and V neutral
    out = proc.run([ffbin.ffmpeg(), "-v", "error", "-f", "rawvideo", "-pix_fmt", "yuv444p",
                    "-s", "2048x1", "-i", "-", "-vf", frag,
                    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "yuv444p", "-"],
                   input=raw).stdout
    assert len(out) >= 2048, f"no frame out of {frag[:60]!r}"
    return [out[i * 8] for i in range(256)]


def test_the_tone_map_renders_within_a_code_of_itself():
    """design §2.3. A LUT has no spline to overshoot, so the four segments ARE the
    map — the only error left is the integer rounding of storing it.

    The control is the map's own arithmetic: `_lerp` through the SAME knots, in
    full range, converted at both ends exactly as the emitted expression does. A
    test that compared the render only against itself would pass on any map."""
    src, dst = (73.0, 137.0, 196.0), (61.0, 123.5, 192.0)
    got = _ramp_y(color.tone_arg(src, dst).rstrip(","))
    segs = color._segments(src, dst)
    want = [color.TV_LO + color._lerp(segs, (y - color.TV_LO) * 255 / color.TV_SPAN)
            * color.TV_SPAN / 255 for y in range(256)]
    worst = max(abs(g - w) for g, w in zip(got[16:256], want[16:256]))
    assert worst <= 1.0, f"the LUT is {worst:.2f} codes off its own map"
    # Monotone over the WHOLE 0-255 plane, not only the legal 16-235: the
    # expression extrapolates below the toe and CONTINUES THE SHOULDER'S SLOPE
    # above it (2026-08-27), and a wrap at either end would be real corruption in
    # sub-black or super-white pixels. Measured on the shipped map: outputs span
    # 2-205 and never step backwards.
    assert all(b >= a for a, b in zip(got, got[1:])), "the transfer bands somewhere"


def test_the_shoulder_carries_the_superwhite_band():
    """Above the top knot the map continues instead of flattening — and the band
    BELOW it does not move, which is what separates a fix from a rescale.

    Measured 2026-08-27 on this exact (src, dst): codes 236..255 came back as ONE
    output value and now come back as eight. reframe.verify_tone cannot see any
    of this — it feeds rgb24 and rgb 255 converts to stored Y 235."""
    src, dst = (71.0, 133.0, 203.0), (61.0, 123.0, 198.5)
    lut = _ramp_y(color.tone_arg(src, dst).rstrip(","))

    tail = lut[236:256]
    assert len(set(tail)) == 8, sorted(set(tail))          # was 1
    assert (min(tail), max(tail)) == (202, 209)

    band = lut[200:236]                                     # the control
    assert (len(set(band)), min(band), max(band)) == (14, 189, 202)


def test_the_tone_transfer_leaves_chroma_byte_identical(tmp_path):
    """design §2.2. lutyuv never writes U or V, so a tone move cannot shift a hue.

    The CONTROL is the same knots emitted the old way — a curves=all spline over
    RGB — which must move them. Without it, "chroma did not change" cannot be told
    from "nothing rendered at all"."""
    clip = _three_band(tmp_path / "c.mp4", "0x402010", "0x80A040", "0xC0E0F0")
    src, dst = (30.0, 120.0, 200.0), (40.0, 130.0, 190.0)

    def planes(frag):
        a = [ffbin.ffmpeg(), "-v", "error", "-i", str(clip)]
        out = proc.run(a + (["-vf", frag] if frag else []) +
                       ["-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "yuv444p", "-"]).stdout
        n = len(out) // 3
        return out[n:]                                    # U and V, as bytes

    base = planes("")
    assert planes(color.tone_arg(src, dst).rstrip(",")) == base, "lutyuv touched chroma"

    segs = color._segments(src, dst)
    pts = " ".join(f"{x/255:.4f}/{color._lerp(segs, x)/255:.4f}" for x in range(0, 256, 20))
    assert planes(f"curves=all='{pts}'") != base, (
        "the per-channel control did NOT move chroma — the comparison proves nothing")


def _pcts(path, width) -> tuple[float, float, float]:
    """(p5,p50,p95) of the gray histogram at `width`, or at the frame's own if None —
    measure_profile's two instruments, side by side."""
    vf = "format=gray" if width is None else f"scale={width}:-2,format=gray"
    out = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", str(path), "-frames:v", "1",
                    "-vf", vf, "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    hist = [0] * 256
    for b in out:
        hist[b] += 1
    return color.percentiles(hist)


def test_both_halves_are_needed_to_close_the_residual(tmp_path):
    """design §0, as a test. The conductor MEASURES, targets, AUTHORS and is then
    judged — so an instrument change has to change all four, which is what the
    earlier §3.4 reading got wrong by changing only the last one.

    Four combinations of (instrument, transfer). The pair must beat both halves;
    if a later change fixes one alone, this reddens with the number saying which."""
    a = _grid(tmp_path / "a.mp4")
    b = _grid(tmp_path / "b.mp4", dark=70, mid=140, spark=250)
    # This test drives its own instrument so it can compare four combinations, which
    # leaves it free to prove a claim about an instrument the pipeline does not use.
    # The link: measure_profile must BE the full-width one (mutation battery row 10
    # survived without this, because mutating measure_profile could not reach here).
    assert measure_profile(str(a), at=0.0) == _pcts(a, None)

    def residual(width, luma: bool) -> float:
        srcs = [_pcts(c, width) for c in (a, b)]
        tgt = tuple(sorted(s[i] for s in srcs)[len(srcs) // 2] for i in range(3))
        worst = 0.0
        for clip, src in zip((a, b), srcs):
            if not (src[0] + color.TONE_MIN_GAP <= src[1] <= src[2] - color.TONE_MIN_GAP):
                continue                       # tone_arg would refuse it; not this test's case
            frag = color.tone_arg(src, tgt).rstrip(",")
            if not luma:                       # the per-channel shape, from the same knots
                segs = color._segments(src, tgt)
                frag = "curves=all='" + " ".join(
                    f"{x/255:.4f}/{color._lerp(segs, x)/255:.4f}"
                    for x in range(0, 256, 20)) + "'"
            out = tmp_path / f"o_{width or 'full'}_{luma}_{Path(clip).stem}.mkv"
            proc.run([ffbin.ffmpeg(), "-y", "-v", "error", "-i", str(clip), "-vf", frag,
                      "-c:v", "ffv1", "-pix_fmt", "yuv420p", str(out)])
            worst = max(worst, max(abs(g - t) for g, t in zip(_pcts(out, width), tgt)))
        return worst

    shipped = residual(160, luma=False)
    ruler_only = residual(None, luma=False)
    transfer_only = residual(160, luma=True)
    both = residual(None, luma=True)
    assert both < shipped, f"the pair did not improve on the shipped chain ({both} vs {shipped})"
    assert both <= ruler_only and both <= transfer_only, (
        f"one half alone matched the pair — pair {both}, ruler {ruler_only}, "
        f"transfer {transfer_only}. Each is a PARTIAL fix (design §0); if that has "
        f"stopped being true, the design's table is what needs re-measuring")


# --- named regions: the conductor reads the declaration (design 2026-09-15 §4) ----
# Fix round 1 (review): finding 1 found the fake diverging from measure_crop's own
# contract, finding 2 found the byte-identity pin comparing post-slice code to
# itself, finding 3 added a second unreachable sub-case, finding 6 the unused
# monkeypatch fixture + a dead binding, and finding 8 the misleading decl_file
# parameter. All four are addressed below, together.

def _write_match_with_fake_measurements(tmp_path, monkeypatch, *, project="project.json",
                                         subject_fraction=0.2):
    """A one-episode GEOMETRY.json + EDL.json under `tmp_path`, `write_match`'d with
    `measure_crop` monkeypatched so no ffmpeg runs.

    `project`, when not None, becomes `ReelGeometry.project` (a plain relative path
    joined onto `tmp_path` — the file itself need not exist, only its directory,
    which is all `_find_regions` ever looks at) — the ordinary case, a project.json
    known but no REGIONS.json beside it. `project=None` simulates a GEOMETRY.json
    written before Task 5, with no project field at all. A path whose OWN directory
    does not exist (e.g. "gone/project.json") simulates the other unreachable
    sub-case review finding 3 added: a recorded project this conductor cannot
    reach from here.

    Whether a REGIONS.json exists is entirely the CALLING TEST's own business —
    write it (or don't) before calling this helper, exactly as a real author
    would. This helper used to accept a `decl_file` naming a REGIONS.json and
    write a default declaration itself whenever nothing was on disk there yet,
    which implied the declaration's FILENAME was configurable (`_find_regions`
    hard-codes "REGIONS.json"; it never was) and made what a test measured
    depend on what happened to be on disk first (review finding 8) — every test
    below now writes its own REGIONS.json, explicitly, when it wants one.

    The fake `measure_crop` mirrors the real one's body EXACTLY (design
    2026-09-15, color_measure.measure_crop): `regions.assemble(decl if decl is
    not None else regions.Regions(), readings)` over a synthetic
    subject/background/crop reading (subject fraction/profile controllable via
    `subject_fraction`, so a caller can push it under MIN_REGION_FRAC and
    exercise the too-small fallback). It used to special-case `decl is None`
    into a hand-picked profile — (10.0, 100.0, 200.0) — that matched none of
    the three readings below; the real conductor never produces that number
    for "no declaration" (it falls back to the crop reading, (20.0, 100.0,
    200.0) here), so the old "byte-identical" test built on this fake was
    pinning a target production would never emit (review finding 1)."""
    source = tmp_path / "clip.mp4"
    route = tmp_path / "route.json"
    source.touch()
    route.touch()
    ep = EDLEpisode(source=str(source), start=0.0, dur=2.0, shot_type="wide",
                    composition="center", grid="thirds")
    edl_path = tmp_path / "EDL.json"
    edl_path.write_text(json.dumps(EDL(episodes=(ep,)).to_dict(), indent=2))

    geo_kwargs = {}
    if project is not None:
        geo_kwargs["project"] = str(tmp_path / project)
    geo = ReelGeometry(
        episodes=(EpisodeGeometry(manifest={}, route=str(route), source=str(source),
                                  project_dir=str(tmp_path / "p0")),),
        edl=str(edl_path), **geo_kwargs)
    geometry_path = tmp_path / "GEOMETRY.json"
    geo.write(geometry_path)

    def fake_measure_crop(manifest_dict, src, route_arg, *, decl=None, frames=None):
        readings = {
            "subject": regions.RegionReading("subject", subject_fraction, (10.0, 150.0, 220.0)),
            "background": regions.RegionReading("background", 1.0 - subject_fraction,
                                                (30.0, 100.0, 180.0)),
            "crop": regions.RegionReading("crop", 1.0, (20.0, 100.0, 200.0)),
        }
        return regions.assemble(decl if decl is not None else regions.Regions(), readings)

    monkeypatch.setattr(match_grade, "measure_crop", fake_measure_crop)
    return match_grade.write_match(str(geometry_path))


def _match_json(tmp_path) -> dict:
    return json.loads((tmp_path / "MATCH.json").read_text())


def test_no_regions_file_leaves_the_target_byte_identical(tmp_path, monkeypatch):
    """The pinned default path (Global Constraints), pinned against LITERALS this
    fixture's own crop reading determines — not against a second call of the same
    post-slice code (review finding 2: `before["target"] == after["target"]`
    compares two calls of `write_match` in the same tree, both already carrying
    whatever this slice changed, so it cannot fail on any regression this slice
    could introduce).

    With no REGIONS.json every anchor falls back to the crop exactly as it did
    before design 2026-09-15 (color_measure's own
    test_measure_crop_with_no_declaration_returns_the_old_profile pins the same
    fact one layer down): the target is this fixture's crop profile
    (20.0, 100.0, 200.0), the reel's only episode IS that profile so it is left
    untouched (within-eps, no pair — a real pin: an authored pair here would be
    a real regression), and every decision's regions carry the three boilerplate
    crop rows real `regions.assemble` always produces, never an empty list."""
    result = _write_match_with_fake_measurements(tmp_path, monkeypatch)
    assert result["target"] == [20.0, 100.0, 200.0]
    back = EDL.from_json(str(tmp_path / "EDL.json"))
    assert (back.episodes[0].tone_src, back.episodes[0].tone_dst) == (None, None)
    for d in _match_json(tmp_path)["decisions"]:
        assert [(r["anchor"], r["of"], r["used"], r["fallback"]) for r in d["regions"]] == [
            ("toe", "crop", "crop", None), ("mid", "crop", "crop", None),
            ("shoulder", "crop", "crop", None)]
    assert (tmp_path / "MATCH.md").read_text().startswith(
        "# Match-grade — target 20/100/200 (p5/p50/p95), eps 4")


def test_a_regions_file_beside_project_json_is_found_with_no_flag(tmp_path, monkeypatch):
    (tmp_path / "REGIONS.json").write_text(json.dumps({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]}))
    result = _write_match_with_fake_measurements(tmp_path, monkeypatch)
    assert result["regions"] == str(tmp_path / "REGIONS.json")
    rows = _match_json(tmp_path)["decisions"][0]["regions"]
    assert rows[0] == {"anchor": "toe", "name": "wetsuit", "of": "subject",
                       "used": "subject", "fraction": 0.2, "value": 10.0,
                       "fallback": None}


def test_a_geometry_with_no_project_says_so_rather_than_reporting_no_declaration(
        tmp_path, monkeypatch):
    result = _write_match_with_fake_measurements(tmp_path, monkeypatch, project=None)
    assert result["regions"] == "unreachable: GEOMETRY.json records no project"
    assert "GEOMETRY.json records no project" in (tmp_path / "MATCH.md").read_text()


def test_a_moved_project_is_unreachable_not_silently_no_declaration(tmp_path, monkeypatch):
    """Review finding 3, ruled correct by the design owner and NOT the brief's
    original body: `_find_regions` used to check only `p.exists()` for
    REGIONS.json itself, so a project.json whose own DIRECTORY cannot be
    reached from here (moved since, or a relative --project resolved against a
    different CWD than the one that recorded it) made that check False for the
    same reason a genuinely-absent REGIONS.json would — silently landing on
    "no declaration" when the true state is "could not even look". The
    unreachable state must carry the offending path, not just the bare word."""
    result = _write_match_with_fake_measurements(
        tmp_path, monkeypatch, project="gone/project.json")
    assert result["regions"].startswith("unreachable:")
    assert "gone" in result["regions"] and "does not exist" in result["regions"]
    assert "does not exist" in (tmp_path / "MATCH.md").read_text()


def test_the_report_prints_the_fallback_and_its_reason(tmp_path, monkeypatch):
    (tmp_path / "REGIONS.json").write_text(json.dumps({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]}))
    _write_match_with_fake_measurements(tmp_path, monkeypatch, subject_fraction=0.002)
    md = (tmp_path / "MATCH.md").read_text()
    assert "too-small" in md and "wetsuit" in md and "0.2%" in md
