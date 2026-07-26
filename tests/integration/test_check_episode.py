import json
import pytest
from scripts import check_episode
from scripts.lib.models import CheckSpec, PathMeta

SRC = (1920, 1080)
CROP_W_FILL = 607              # 9:16 of a 1920x1080 source


def _write(tmp_path, crop_w, freedom, mode, out_dims, rect_px):
    """A route the lead check passes: the subject sits on the left third of the
    crop at every frame, so on_line's ratio is 1.0 whenever freedom allows it.

    check_episode never reads `out_dims`/`rect_px`, but they are still what
    layout.resolve really produces for that mode on a 1920x1080 source. A
    sidecar that could not have been written teaches the next reader a shape
    that does not exist.
    """
    route = [dict(t=i / 30, x=400.0 + i * 5, y=540.0, w=60.0, h=160.0) for i in range(30)]
    path = [int(max(0, min(freedom, round(p["x"] - crop_w / 3)))) for p in route]
    (tmp_path / "route.json").write_text(json.dumps(route))
    (tmp_path / "path.json").write_text(json.dumps(path))
    PathMeta(mode=mode, crop_w=crop_w, crop_h=1080, crop_y=0, src_dims=SRC,
             canvas=(9, 16), out_dims=out_dims, rect_px=rect_px,
             freedom=freedom).write(tmp_path / "path.meta.json")
    return str(tmp_path / "route.json"), str(tmp_path / "path.json")


def _fill(tmp_path):
    """resolve(fill, 9:16, 1920x1080, native) -> 606x1080, crop 607, whole canvas."""
    return _write(tmp_path, crop_w=CROP_W_FILL, freedom=1920 - CROP_W_FILL, mode="fill",
                  out_dims=(606, 1080), rect_px=(0, 0, 606, 1080))


def _fit(tmp_path):
    """resolve(fit/source, 9:16, 1920x1080, native) -> 1920x3412, the whole
    frame centred at y=1166. The crop IS the source, so freedom is zero."""
    return _write(tmp_path, crop_w=1920, freedom=0, mode="fit",
                  out_dims=(1920, 3412), rect_px=(0, 1166, 1920, 1080))


def _insert(tmp_path):
    """resolve(insert/1:1 @ rect(.05,.25,.90), 9:16, 1920x1080, native) ->
    1200x2132, a 1080x1080 card at (60, 533). A square crop of a 16:9 source
    leaves 840px of freedom, so the numeric composition check really runs — and
    the canvas-derived width (607) is nowhere near the 1080 that was cut."""
    return _write(tmp_path, crop_w=1080, freedom=840, mode="insert",
                  out_dims=(1200, 2132), rect_px=(60, 533, 1080, 1080))


@pytest.mark.integration
def test_run_fails_loud_when_the_sidecar_is_missing(tmp_path, sample_clip):
    route = [dict(t=i / 30, x=400.0, y=540.0, w=60.0, h=160.0) for i in range(30)]
    (tmp_path / "route.json").write_text(json.dumps(route))
    (tmp_path / "path.json").write_text(json.dumps([0] * 30))
    spec = CheckSpec(composition="lead", grid="thirds", target_dur=3.0)
    with pytest.raises(RuntimeError, match="re-run reframe"):
        check_episode.run(str(sample_clip), str(tmp_path / "route.json"),
                          str(tmp_path / "path.json"), spec, str(tmp_path / "report.json"))


@pytest.mark.integration
@pytest.mark.parametrize("composition, numeric_check", [("lead", "on_line"),
                                                        ("center", "centered")])
def test_zero_freedom_makes_the_composition_check_editorial(tmp_path, sample_clip,
                                                            composition, numeric_check):
    # fit at scale 1.0: the crop is the whole frame, so nobody controls
    # composition — it can neither fail nor silently pass. True of both numeric
    # compositions: the branch keys off freedom, never off the composition name.
    rp, pp = _fit(tmp_path)
    spec = CheckSpec(composition=composition, grid="thirds", target_dur=3.0)
    report = check_episode.run(str(sample_clip), rp, pp, spec, str(tmp_path / "report.json"))
    assert numeric_check not in report.checks
    framing = report.checks["framing"]
    assert framing.passed is None
    assert framing.detail == {"status": "editorial-only", "reason": "no horizontal freedom"}
    assert report.overall is True          # passed=None never fails overall


@pytest.mark.integration
def test_positive_freedom_still_runs_the_numeric_check(tmp_path, sample_clip):
    rp, pp = _fill(tmp_path)
    spec = CheckSpec(composition="lead", grid="thirds", target_dur=3.0)
    report = check_episode.run(str(sample_clip), rp, pp, spec, str(tmp_path / "report.json"))
    assert report.checks["on_line"].passed is True


@pytest.mark.integration
def test_color_fidelity_not_checked_without_source(tmp_path, sample_clip):
    """No source= at all (the process_episode wiring is a later task) → the
    advisory check reports honestly instead of silently skipping, and — being
    advisory — never moves `overall`, which stays driven by the real gates."""
    rp, pp = _fill(tmp_path)
    spec = CheckSpec(composition="lead", grid="thirds", target_dur=3.0)
    report = check_episode.run(str(sample_clip), rp, pp, spec, str(tmp_path / "report.json"))
    cf = report.checks["color_fidelity"]
    assert cf.passed is None
    assert cf.detail["status"] == "not-checked"
    assert report.overall is True


@pytest.mark.integration
def test_crop_w_comes_from_the_sidecar_not_the_canvas(tmp_path, sample_clip):
    """The bug this task fixes: re-deriving crop_w from the canvas yields a
    verdict about a crop nobody cut.

    It must be checked where freedom is POSITIVE. Under fit freedom is zero,
    the editorial-only branch short-circuits, and crop_w is never used for the
    composition check at all — a fit fixture here cannot tell the two
    implementations apart.

    So: an `insert` with a 1:1 crop of a 1920x1080 source. reframe cut 1080px;
    the 9:16 canvas would re-derive 607. The route puts the subject exactly one
    third into the real crop (360/1080 = 0.3333, dead on the left third line, so
    on_line's ratio is 1.0). Re-derived, the same subject reads 360/607 = 0.593
    — a quarter of the frame off the line, ratio 0.0, and the check fails.
    """
    rp, pp = _insert(tmp_path)
    spec = CheckSpec(composition="lead", grid="thirds", target_dur=3.0)
    report = check_episode.run(str(sample_clip), rp, pp, spec, str(tmp_path / "report.json"))
    assert report.checks["on_line"].passed is True
    assert report.checks["on_line"].detail == {"ratio": 1.0}
