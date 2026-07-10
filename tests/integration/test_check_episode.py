import json
import pytest
from scripts import check_episode
from scripts.lib.models import CheckSpec, PathMeta

SRC = (1920, 1080)
CROP_W_FILL = 607              # 9:16 of a 1920x1080 source


def _write(tmp_path, crop_w, freedom, mode):
    """A route the lead check passes: the subject sits on the left third of the
    crop at every frame, so on_line's ratio is 1.0 whenever freedom allows it."""
    route = [dict(t=i / 30, x=400.0 + i * 5, y=540.0, w=60.0, h=160.0) for i in range(30)]
    path = [int(max(0, min(freedom, round(p["x"] - crop_w / 3)))) for p in route]
    (tmp_path / "route.json").write_text(json.dumps(route))
    (tmp_path / "path.json").write_text(json.dumps(path))
    PathMeta(mode=mode, crop_w=crop_w, crop_h=1080, crop_y=0, src_dims=SRC,
             canvas=(9, 16), out_dims=(606, 1080), rect_px=(0, 0, 606, 1080),
             freedom=freedom).write(tmp_path / "path.meta.json")
    return str(tmp_path / "route.json"), str(tmp_path / "path.json")


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
def test_zero_freedom_makes_the_composition_check_editorial(tmp_path, sample_clip):
    # fit-blur at scale 1.0: the crop is the whole frame, so nobody controls
    # composition — it can neither fail nor silently pass
    rp, pp = _write(tmp_path, crop_w=1920, freedom=0, mode="fit-blur")
    spec = CheckSpec(composition="lead", grid="thirds", target_dur=3.0)
    report = check_episode.run(str(sample_clip), rp, pp, spec, str(tmp_path / "report.json"))
    assert "on_line" not in report.checks
    framing = report.checks["framing"]
    assert framing.passed is None
    assert framing.detail == {"status": "editorial-only", "reason": "no horizontal freedom"}
    assert report.overall is True          # passed=None never fails overall


@pytest.mark.integration
def test_positive_freedom_still_runs_the_numeric_check(tmp_path, sample_clip):
    rp, pp = _write(tmp_path, crop_w=CROP_W_FILL, freedom=1920 - CROP_W_FILL, mode="fill")
    spec = CheckSpec(composition="lead", grid="thirds", target_dur=3.0)
    report = check_episode.run(str(sample_clip), rp, pp, spec, str(tmp_path / "report.json"))
    assert report.checks["on_line"].passed is True


@pytest.mark.integration
def test_crop_w_comes_from_the_sidecar_not_the_canvas(tmp_path, sample_clip):
    """The bug this task fixes: a fit-blur crop is 1920 wide, and re-deriving it
    from the 9:16 canvas would give 607 — a verdict about a crop nobody cut."""
    rp, pp = _write(tmp_path, crop_w=1920, freedom=0, mode="fit-blur")
    spec = CheckSpec(composition="center", grid="thirds", target_dur=3.0)
    report = check_episode.run(str(sample_clip), rp, pp, spec, str(tmp_path / "report.json"))
    assert "centered" not in report.checks          # freedom is zero → editorial
    assert report.checks["framing"].passed is None
