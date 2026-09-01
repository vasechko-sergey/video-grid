"""Real-ffmpeg proofs for the grade-shipped-pixels slice (design
docs/specs/2026-08-30-grade-shipped-pixels-design.md §8).

Everything above has been argued; these are the tests that would catch it being
wrong. Each proof carries a control that must NOT move — without one, a proof shows
that something happened, not that the right thing happened.

The footage is `tests/fixtures/golden_ride.mp4` re-exposed, not lavfi bands: the
thing this slice measures is a TRACKED CROP of a real shot, and every number in the
design's §0 was read off one. The tracker itself is stubbed with the committed
`golden_route.json` (see `_fake_tracker`); everything below it — the contradiction
gate, the geometry stop, the stabilize pre-stage, reframe, check_episode, the grade,
the assemble, check_reel and deliver — runs for real.
"""
import json
import shutil
from pathlib import Path

import pytest
from scripts import build_reel, color_measure, edl_to_reel, match_grade, probe
from scripts import process_episode as pe
from scripts import track
from scripts.lib import assembly, color, ffbin, manifest as manifest_lib, matchgrade
from scripts.lib import models, proc
from scripts.lib import provenance as prov_lib
from scripts.lib.edl import EDL, EDLEpisode, preflight
from scripts.lib.look import LookSpec
from scripts.lib.models import EpisodeGeometry, ReelGeometry
from scripts.lib.project import ProjectConfig
# `tests/` is what pytest puts on sys.path (tests/integration is a package, tests/ is
# not), so this is the sibling module's import path. Imported and not copied: a second
# copy of `_banded_episode` would drift from the fixture whose geometry — a 640x640
# square crop pinned into the bottom band of a 640x1280 source — is the only reason the
# two readings disagree at all.
from integration.test_color_measure import _banded_episode

pytestmark = pytest.mark.integration

FIX = Path(__file__).parent.parent / "fixtures"
_ROUTE = json.loads((FIX / "golden_route.json").read_text())
_ROUTE_META = json.loads((FIX / "golden_route.meta.json").read_text())

# The two exposures, and the two windows they are cut from.
#
# Measured on the tracked crops these produce (a 720x720 square crop out of a 1280x720
# frame — no resample, so the reading is of the crop's own pixels): 32/71/179 against
# 42/93/236. Each sits [5.0, 11.0, 28.5] from the common median 37/82/207.5 — the pull
# is NOT uniform across the anchors, it grows with luma, and 28.5 is the p95 anchor
# alone. matchgrade.needs_tone reads the MAX, so both get a pair; the subject the
# colour sensor watches sits nearer the 5-11 end.
#
# The upper bound is not taste, it is a MEASURED ceiling this repo shipped at the time
# these values were picked: check_episode's color_fidelity gate was BLOCKING at
# grade_delta_max = 5.0 dE00 from 2026-08-28, and the convergence grade IS grade
# movement to it. Swept on this exact fixture shape: at x0.78/x1.15 the bright episode
# read 5.48 and phase 1b stopped with `grade-damage`; here the sensor read 2.33 and 3.82.
# See the task report — a real reel with a wider exposure spread than this fixture could
# not be match-graded through that gate.
#
# Design 2026-08-31 §3 renamed the check `grade_damage` and replaced the dE00 verdict
# with a luma-entropy ratio (the dE00 reading is now an advisory description, not a
# vote) — and, until a later task wires process_episode to pass it a `plans` pair, the
# check reports not-checked for every episode this file renders, so the ceiling this
# comment describes is dormant here rather than enforced. DARK/BRIGHT are left at their
# originally-measured, conservative values regardless: they were never chosen to prove
# this specific gate, only to stay safely clear of it.
DARK, BRIGHT = 0.83, 1.09

# One window per episode, by index. Two DIFFERENT windows because check_reel's variety
# gate compares adjacent episodes' phashes: two exposures of the SAME window come back
# 2 bits apart against a variety_min of 8, so a reel built from them cannot be
# delivered at all (measured). `center` and not `lead` for the same kind of reason —
# over 0.75s the golden route's net travel is under the 15% of frame width
# orchestration.detect_contradictions requires of a lead, and the contradiction gate
# (correctly) refuses the episode.
_WINDOWS = ({"start": 0.0, "dur": 0.75, "composition": "center"},
            {"start": 0.8, "dur": 0.75, "composition": "center"})


def _exposed(out: Path, mul: float) -> Path:
    """`golden_ride.mp4` re-exposed by `mul`, limited range — one camera's shot as a
    second camera would have carried it. The lutyuv moves the exposure and keeps the
    shot's structure, which is what makes the two crops differ the way two cameras on
    one shoot differ rather than the way two test patterns do."""
    proc.run([ffbin.ffmpeg(), "-y", "-i", str(FIX / "golden_ride.mp4"),
              "-vf", f"scale=in_range=auto:out_range=tv,"
                     f"lutyuv=y='clip(16+(val-16)*{mul},16,235)'",
              "-color_range", "tv", "-c:v", "libx264", "-crf", "16", "-preset", "medium",
              "-pix_fmt", "yuv420p", "-an", str(out)])
    return out


def _fake_tracker(monkeypatch):
    """YOLO replaced by the committed golden route — and nothing else.

    The tracker is not what this slice moved, and a real pass would make every number
    below depend on a model version while costing more than every other stage here put
    together. The route is the real one measured on this same footage; it is written
    exactly where a real rung-1 pass writes it, so `_load_route`, the contradiction
    gate and the geometry stop all read what they always read."""
    def build_route(spec, out):
        dur = assembly.probe_duration(spec.src)
        pts = [p for p in _ROUTE if p["t"] <= dur]
        Path(out).write_text(json.dumps(pts))
        Path(out).with_suffix(".meta.json").write_text(json.dumps(_ROUTE_META))
        return [models.RoutePoint.from_dict(p) for p in pts]
    monkeypatch.setattr(track, "build_route", build_route)
    monkeypatch.setattr(track, "ensure_model", lambda model=track.MODEL: None)
    monkeypatch.setattr(track, "available", lambda descriptor=False: True)


def _run(tmp_path, monkeypatch, rows, *, canvas=(1, 1), **edl_fields):
    """A run dir shaped the way runlayout wants it, with one re-exposed source clip per
    row. `rows` are (multiplier, EDL-episode overrides). Returns the ctx every proof
    below drives.

    The square canvas is load-bearing, not arbitrary: 1:1 against a 1280x720 source
    crops 720x720 and `native` delivery keeps it. The chain still ends `…,scale=720:720,…`
    — the filter is emitted either way — but at equal dimensions it is an identity that
    takes swscale's unscaled path, so NOTHING RESAMPLES and the conductor's reading and
    the encoded clip's reading are of the same pixel population. Measured against a 9:16
    canvas (crop 405 wide, delivered 404 — one pixel of real resampling): every delivered
    residual rose from 1.0 to 3.5, because a resample and a non-linear tone curve do not
    commute. That is a real number about production geometry, recorded in the task
    report; here it is simply noise this fixture does not need to carry."""
    _fake_tracker(monkeypatch)
    foot = tmp_path / "footage"
    foot.mkdir(parents=True, exist_ok=True)
    episodes = []
    for i, (mul, over) in enumerate(rows):
        _exposed(foot / f"c{i}.mp4", mul)
        episodes.append({"source": f"c{i}.mp4", "shot_type": "wide", "grid": "thirds",
                         **_WINDOWS[i], **over})
    project = tmp_path / "project.json"
    project.write_text(json.dumps({"purpose": "reel", "canvas": list(canvas),
                                   "delivery": "native"}))
    edl = tmp_path / "EDL.json"
    edl.write_text(json.dumps({"episodes": episodes, **edl_fields}))
    reel = tmp_path / "reels" / "main"
    return {"footage": str(foot), "project": str(project), "edl": str(edl),
            "work": str(reel / "build"), "out": str(reel / "episodes"),
            "deliveries": str(reel / "deliveries"),
            "geometry": str(reel / "episodes" / "GEOMETRY.json")}


def _geometry(ctx):
    geo, stop = edl_to_reel.build_geometry(ctx["edl"], ctx["project"], ctx["footage"],
                                           ctx["work"], ctx["out"])
    assert stop is None, stop
    return geo


def _render(ctx):
    rm, stop = edl_to_reel.render_from_geometry(ctx["geometry"], ctx["project"],
                                               ctx["work"], ctx["out"])
    assert stop is None, stop
    return rm


def _profile(clip: str) -> tuple[float, float, float]:
    """The gate's own ruler over a finished clip, at the same (k+0.5)/3 times."""
    dur = assembly.probe_duration(clip)
    return color_measure.clip_percentiles(clip, color.sample_times(dur))


def _resid(profile, target) -> float:
    return max(abs(a - b) for a, b in zip(profile, target))


def _edit_edl(path: str, index: int, **fields) -> None:
    """Rewrite one episode row and DROP the provenance stamp.

    match_grade re-stamps the EDL it writes back, so an edited-in-place stamped EDL
    would be refused by EDL.from_json as tampered — a real guard, and the wrong one
    for the proofs below, which are about the geometry seam's own refusals. Dropping
    the block leaves the EDL `unstamped`, which the whole pipeline accepts by design
    (absence is not tampering)."""
    doc = json.loads(Path(path).read_text())
    doc["episodes"][index].update(fields)
    doc.pop(prov_lib.PROV_KEY, None)
    Path(path).write_text(json.dumps(doc))


def _fresh_manifest(ctx, index: int) -> dict:
    """The colour-stripped manifest `--from-geometry` re-derives from the EDL as it
    stands now — the half of the guard that compares against EpisodeGeometry.manifest."""
    cfg = ProjectConfig.from_json(ctx["project"])
    mds, stop = preflight(EDL.from_json(ctx["edl"]), cfg,
                          str(Path(ctx["work"]) / "segments"), ctx["out"])
    assert stop is None, stop
    return edl_to_reel._jsonable(manifest_lib.strip_colour(mds[index]))


# --- Proof 1: the central claim, end to end ----------------------------------

def test_the_conductor_converges_two_exposures_through_the_real_render(tmp_path, monkeypatch):
    """geometry → write_match → render, and every DELIVERED clip lands on the target.

    This is design §1 with nothing faked below the tracker: the conductor measures each
    episode's own tracked crop through `plan_render`, `common_target` picks the median,
    `render_from_geometry` renders over the frozen routes, and the clips that come out
    are read with the same gray ruler check_reel will use on the master.
    """
    ctx = _run(tmp_path, monkeypatch, [(DARK, {}), (BRIGHT, {})])
    _geometry(ctx)
    res = match_grade.write_match(ctx["geometry"])
    assert res["authored"] == 2 and res["skipped"] == {}, res

    edl = EDL.from_json(ctx["edl"])
    target = edl.tone_target
    assert target is not None
    src = [e.tone_src for e in edl.episodes]
    # the two crops really are far apart, and each really is far from the target —
    # without this the convergence below could be two episodes that never moved
    assert _resid(src[0], src[1]) > 40, src
    assert all(_resid(s, target) > matchgrade.MATCH_EPS for s in src), (src, target)

    rm = _render(ctx)
    got = [_profile(e.clip) for e in rm.episodes]
    resid = [_resid(g, target) for g in got]
    assert all(r <= matchgrade.MATCH_EPS for r in resid), (got, target, resid)
    # and they converged on EACH OTHER, not merely near a number
    assert _resid(got[0], got[1]) <= 2.0, got


def test_a_single_episode_reel_is_its_own_median_and_nothing_moves(tmp_path, monkeypatch):
    """The control for the proof above. A one-episode reel's own profile IS the median,
    so `plan` returns `within-eps` and authors nothing — and the clip must come out
    BYTE-IDENTICAL to the render made before the conductor ever ran. That is what
    proves the conductor does not move pixels it has no reason to move: a
    "within-eps" report with a re-graded clip underneath it would pass any assertion
    about the report alone."""
    ctx = _run(tmp_path, monkeypatch, [(DARK, {})])
    _geometry(ctx)
    before = _render(ctx)
    ungraded = tmp_path / "ungraded.mp4"
    shutil.copyfile(before.episodes[0].clip, ungraded)

    res = match_grade.write_match(ctx["geometry"])
    assert res["authored"] == 0 and res["skipped"] == {"within-eps": 1}, res
    edl = EDL.from_json(ctx["edl"])
    assert edl.episodes[0].tone_src is None and edl.episodes[0].tone_dst is None
    # the target IS this episode's own measured profile, gap-repaired — which is why
    # `plan` had nothing to author
    eg = ReelGeometry.from_json(ctx["geometry"]).episodes[0]
    assert edl.tone_target == matchgrade.common_target(
        [color_measure.measure_crop(eg.manifest, eg.source, eg.route)])

    after = _render(ctx)
    assert Path(after.episodes[0].clip).read_bytes() == ungraded.read_bytes()


# A legal, in-range value of a documented per-episode knob. 0.05 and not 0.35: this
# test records that ANY post-tone luma knob breaks the gate's premise, so it uses the
# smallest lift that shows it rather than the largest one available. Machine-checked
# against the ceiling color.py itself publishes, so a widened range cannot make this
# fixture quietly illegal.
_PIN_BLACK_POINT = 0.05


def test_a_black_point_beside_the_tone_pair_misses_the_target_RECORDED_LIMITATION(
        tmp_path, monkeypatch):
    """A RECORDED LIMITATION, not an endorsement — design §9.9, backlog P1.

    `_tone_match_check` justifies being BLOCKING on percentiles commuting with the
    monotone map `color.tone_arg` builds. That holds only while the tone curve is the
    LAST luma operation in the chain, and `color.grade_chain` puts six more after it
    (black_point, gain, shadow_red, mid_blue, highlight, highlight_red, dip — saturation
    and the leading white_balance are the two that do not move luma). The conductor
    solves the curve through `color_measure.measure_crop`, which reads via
    `manifest.strip_colour` — every knob at identity — so the fit never sees them.

    This test asserts the CURRENT behaviour: an episode graded correctly by the
    conductor, then given a legal `black_point`, lands OUTSIDE `matchgrade.MATCH_EPS`
    of the target it was authored against. Nobody thinks that is right; §9.9 names the
    open design question (measure the residual through the non-tone part of the chain,
    or exclude post-tone knobs from it). When that question is answered this test
    should go RED and be rewritten, not deleted.

    Measured here, on the same real footage every other proof in this file uses:
    tone alone lands **1.0** from the target, tone + `black_point=0.05` lands **13.0**
    — past `matchgrade.MATCH_EPS` (4.0) and past `ReelCheckSpec.tone_match_max` (12.0),
    so this is not a rounding complaint: the blocking gate really does fail this
    episode. The bar asserted below is MATCH_EPS and not the gate ceiling only because
    13.0 sits one unit above 12.0, which is too fine a margin to pin.

    CONTROL, and it carries the whole weight: the SAME two episodes, the SAME target,
    the SAME render path with tone ALONE both land inside MATCH_EPS — and episode 1,
    which is not touched, stays inside it in the second render too. Without both, a
    residual outside the bar would only show that something moved."""
    assert 0 < _PIN_BLACK_POINT <= color.BLACK_POINT_MAX

    ctx = _run(tmp_path, monkeypatch, [(DARK, {}), (BRIGHT, {})])
    _geometry(ctx)
    assert match_grade.write_match(ctx["geometry"])["authored"] == 2
    target = EDL.from_json(ctx["edl"]).tone_target
    assert target is not None

    clean = [_resid(_profile(e.clip), target) for e in _render(ctx).episodes]
    assert all(r <= matchgrade.MATCH_EPS for r in clean), (clean, target)

    # the knob is added AFTER the conductor ran, exactly as an author reaching for a
    # toe lift on one flat-profile source would add it. Only the colour block moves, so
    # the frozen routes still describe these episodes and --from-geometry renders them.
    _edit_edl(ctx["edl"], 0, black_point=_PIN_BLACK_POINT)
    got = [_resid(_profile(e.clip), target) for e in _render(ctx).episodes]
    assert got[0] > matchgrade.MATCH_EPS, (
        f"the recorded limitation no longer reproduces: episode 0 carries "
        f"black_point={_PIN_BLACK_POINT} beside its conductor-authored pair and still "
        f"lands {got[0]:.1f} from {target} (was {clean[0]:.1f} with tone alone). If the "
        f"chain or the measurement changed on purpose, rewrite this test and close the "
        f"P1 row; do not loosen the bar")
    assert got[1] <= matchgrade.MATCH_EPS, (got, clean, target)


# --- Proof 2: the frame and the crop disagree, at the stage that acts on it ----

def test_conduct_decides_on_the_crop_not_on_the_whole_frame(tmp_path):
    """design §0.1 as a behavioural proof. `test_color_measure.py` already shows the two
    READINGS differ; this shows the DIFFERENCE REACHING THE DECISION — the reading is an
    input to the reel's own common target, so measuring the frame instead of the crop
    re-aims every OTHER episode's grade.

    `_banded_episode` is imported rather than copied: a second copy would drift from the
    fixture whose crop is pinned into the bottom band (see the import's own note)."""
    # The REALISTIC band (120 over 100), not the fixture's dramatic 240/100 default —
    # its own docstring asks for this, and test_color_measure.py already reads it here.
    # A proof that only holds at a 35x margin says nothing about production scale; at
    # 120/100 the counterfactual target is still 10.0 from the real one against a
    # MATCH_EPS of 4.0 (measured).
    src, md, route = _banded_episode(tmp_path, top=120, bottom=100)
    other = tmp_path / "other.mp4"                          # a second, gradeable episode
    proc.run([ffbin.ffmpeg(), "-y",
              "-f", "lavfi", "-i", "color=c=0x202020:s=160x1280:d=2:r=30",
              "-f", "lavfi", "-i", "color=c=0x808080:s=320x1280:d=2:r=30",
              "-f", "lavfi", "-i", "color=c=0xE0E0E0:s=160x1280:d=2:r=30",
              "-filter_complex", "hstack=inputs=3", "-frames:v", "60",
              "-pix_fmt", "yuv420p", "-color_range", "tv", str(other)])
    md2 = {**md, "segment": str(other), "out_path": "ep1.mp4"}
    route2 = tmp_path / "route2.json"
    route2.write_text(Path(route).read_text())

    geo = ReelGeometry(episodes=(
        EpisodeGeometry(manifest=md, route=route, source=src,
                        project_dir=str(tmp_path / "p0")),
        EpisodeGeometry(manifest=md2, route=str(route2), source=str(other),
                        project_dir=str(tmp_path / "p1"))), edl=str(tmp_path / "EDL.json"))
    row = lambda s: EDLEpisode(source=s, start=0.0, dur=2.0, shot_type="wide",
                               composition="center", grid="thirds")
    edl = EDL(episodes=(row("banded.mp4"), row("other.mp4")))

    out, target, decisions, _ = match_grade.conduct(geo, edl)
    crop = decisions[0].measured
    frame = color_measure.measure_profile(src, at=0.5)

    assert crop == pytest.approx((100.0, 100.0, 100.0))      # the crop, exactly
    assert _resid(frame, crop) > matchgrade.MATCH_EPS, (frame, crop)
    assert (decisions[0].action, decisions[0].reason) == ("skip", "flat-source")

    # The CONTROL, and the reason this is asserted through `conduct` and not through
    # `measure_crop`: the reading is an input to the REEL'S OWN COMMON TARGET, so the
    # frame reading and the crop reading send every OTHER episode to a different grade.
    # Episode 1 is the one that actually receives a pair, and its tone_dst is the
    # crop-derived target — a whole-frame conductor would have graded it toward
    # `counterfactual`, which is more than MATCH_EPS away.
    counterfactual = matchgrade.common_target([frame, decisions[1].measured])
    assert _resid(target, counterfactual) > matchgrade.MATCH_EPS, (target, counterfactual)
    assert out.episodes[1].tone_dst == target
    assert decisions[1].action == "author"


# --- Proof 3: the cut guard ---------------------------------------------------

_RAMP = {"at": 0.5, "factor": 0.5, "ease": 0.1, "hold": 0.1}
_RAMP_MOVED = {**_RAMP, "at": 0.4}   # a real editorial move — the slow-mo moment lands
                                     # 100ms earlier — chosen because it leaves
                                     # ramp.ramp_extra EXACTLY equal (measured over this
                                     # window's own 0.75s: 0.18284271247461914 for both
                                     # `at` values), so target_dur is bit-identical and
                                     # the manifest half of the guard genuinely sees
                                     # nothing. Measured: most other `at` values land
                                     # within ONE ULP (1-7e-16) instead of exactly equal
                                     # — float summation noise, not a guard anything
                                     # could be built on.


def test_from_geometry_takes_a_regrade_and_refuses_a_moved_ramp(tmp_path, monkeypatch):
    """One GEOMETRY.json, two edits. A rewritten colour block is the seam and renders;
    a rewritten window is refused before any ffmpeg.

    The refused case moves a RAMP, not a `start`, because that is the one a naive guard
    cannot catch: `play_dur() = dur + ramp_extra` and `ramp_extra` is by design a
    `dur`-independent constant of the ramp region, so moving `at` leaves `target_dur`
    bit-identical and NOT ONE manifest field moves. The test asserts that emptiness
    first — otherwise it would pass over a guard with only its manifest half built."""
    ctx = _run(tmp_path, monkeypatch, [(DARK, {"ramp": dict(_RAMP)}), (BRIGHT, {})])
    _geometry(ctx)
    stored = ReelGeometry.from_json(ctx["geometry"]).episodes[0].manifest

    # accepted: match_grade rewrote the colour block, and the render goes through
    match_grade.write_match(ctx["geometry"])
    rm = _render(ctx)
    target = EDL.from_json(ctx["edl"]).tone_target
    assert rm.episodes[0].manifest["tone_dst"] == list(target)

    # refused: the ramp moves and the manifest cannot see it
    _edit_edl(ctx["edl"], 0, ramp=dict(_RAMP_MOVED))
    fresh = _fresh_manifest(ctx, 0)
    assert fresh == stored, "the moved ramp DID move a manifest field — pick another case"
    assert fresh["target_dur"] == stored["target_dur"]      # bit-identical, by §2.2
    with pytest.raises(ValueError, match="ramp"):
        edl_to_reel.render_from_geometry(ctx["geometry"], ctx["project"],
                                         ctx["work"], ctx["out"])

    # and the ordinary case still refuses too, naming the field that moved
    _edit_edl(ctx["edl"], 0, ramp=dict(_RAMP), start=0.05)
    with pytest.raises(ValueError, match="start"):
        edl_to_reel.render_from_geometry(ctx["geometry"], ctx["project"],
                                         ctx["work"], ctx["out"])


# --- Proof 4: stabilize -------------------------------------------------------

def test_a_stabilized_episode_renders_from_geometry_but_not_by_hand(tmp_path, monkeypatch,
                                                                    need_filter):
    """design §2.3. The split's `prepared_source` says "this route was measured on THIS
    file", which is the one thing the stabilize/route refusal could never know — so the
    driver renders and a hand-supplied `--route` still refuses, on the same route."""
    need_filter("vidstabdetect")
    need_filter("vidstabtransform")
    ctx = _run(tmp_path, monkeypatch, [(DARK, {"stabilize": True})])
    geo = _geometry(ctx)
    eg = geo.episodes[0]
    # the pre-stage really ran: the source reframe will consume is NOT the segment
    assert eg.source == str(Path(ctx["work"]) / "ep0" / "stabilized.mp4")
    assert Path(eg.source).exists() and eg.source != eg.manifest["segment"]

    rm = _render(ctx)
    assert Path(rm.episodes[0].clip).exists()
    assert rm.episodes[0].manifest["stabilize"] is True     # the report still says so

    # the control: the SAME frozen route, handed in by hand, is still refused
    res = pe.process_episode({**eg.manifest, "out_path": str(tmp_path / "byhand.mp4")},
                             str(tmp_path / "byhand"), route_path=eg.route)
    assert res["status"] == "needs_input", res
    assert "stabilize=true cannot be combined with a supplied --route" in res["problems"][0]
    assert not Path(tmp_path / "byhand.mp4").exists()       # refused before any encode


# --- Proofs 5 and 6: the gate --------------------------------------------------

def _spans(rm):
    """Each episode's own (k+0.5)/3 sample times, in MASTER time — the exact spans
    check_reel's tone_match measures."""
    durs = [assembly.probe_duration(e.clip) for e in rm.episodes]
    start, spans = 0.0, []
    for d in durs:
        spans.append([start + t for t in color.sample_times(d)])
        start += d
    return spans


def test_the_gate_fires_when_the_grade_never_reached_the_pixels(tmp_path, monkeypatch):
    """design §0.6's negative class, end to end: the conductor authored a pair, the
    manifest still declares it, and the render lost it. The reel's own record says
    graded; the pixels say otherwise, and `tone_match` is the only thing that looks.

    CONTROL: the SAME reel, from the SAME manifest, with the grade actually applied —
    it delivers, and its worst residual is a number, not a pass/fail."""
    ctx = _run(tmp_path, monkeypatch, [(DARK, {}), (BRIGHT, {})])
    _geometry(ctx)
    match_grade.write_match(ctx["geometry"])
    rm = _render(ctx)
    target = EDL.from_json(ctx["edl"]).tone_target
    assert rm.tone_target == target
    assert all(e.manifest["tone_dst"] == list(target) for e in rm.episodes)

    ok = build_reel.build_reel(rm, ctx["deliveries"], str(Path(ctx["work"]) / "reel"))
    assert ok["status"] == "delivered", ok
    tm = ok["report"]["checks"]["tone_match"]
    assert tm["pass"] is True, tm
    assert tm["not_checked"] == {} and set(tm["residuals"]) == {"0", "1"}, tm
    assert tm["worst"] <= rm.check_spec.tone_match_max

    # The colour block goes missing between authoring and render. `rm` is NOT rebuilt:
    # it is the record the reel ships with, and it still declares both pairs.
    _edit_edl(ctx["edl"], 1, tone_src=None, tone_dst=None)
    _render(ctx)
    bad = build_reel.build_reel(rm, str(tmp_path / "deliveries2"),
                               str(Path(ctx["work"]) / "reel2"))
    assert bad["status"] == "stop_and_report", bad
    assert bad["finding"]["check"] == "tone_match", bad["finding"]
    assert bad["finding"]["escalate_to"] == "match-grade", bad["finding"]
    bad_tm = bad["report"]["checks"]["tone_match"]
    assert bad_tm["pass"] is False
    assert bad_tm["residuals"]["1"] > rm.check_spec.tone_match_max
    # and episode 0, which kept its grade, is still where it was — the failure is
    # attributed to the one episode that lost it
    assert bad_tm["residuals"]["0"] == tm["residuals"]["0"]


def test_the_gate_reads_the_master_not_the_delivered_reel(tmp_path, monkeypatch):
    """design §5, and its §8.6 in full: the reel passes, AND WOULD NOT if the check
    sampled the delivery.

    `deliver`'s vignette and bookend fade both ride its one encode, and the master is
    the last artifact whose pixels are the episodes'. The look carries BOTH, because the
    vignette alone does not settle it — measured at vignette 0.6 with no fade, the
    delivery reads 5.5 against the master's 1.5: further, but still inside the gate's
    12.0 ceiling, so a check reading the wrong file would have reached the same verdict
    by luck. The fade is what makes the choice of file decide the answer: `fade_args`
    emits `fade=t=in:st=0:d=0.3`, and the first per-episode sample lands at 0.125s of
    the master — inside the fade-in, at roughly 42% brightness."""
    # authored on the EDL, where a look really is authored — LookSpec builds the dict so
    # the shape is the contract's, not a literal that can drift from it
    ctx = _run(tmp_path, monkeypatch, [(DARK, {}), (BRIGHT, {})],
               look=LookSpec(vignette=0.6, fade=0.3).to_dict())
    _geometry(ctx)
    match_grade.write_match(ctx["geometry"])
    rm = _render(ctx)
    assert rm.look is not None and (rm.look.vignette, rm.look.fade) == (0.6, 0.3)

    work = str(Path(ctx["work"]) / "reel")
    res = build_reel.build_reel(rm, ctx["deliveries"], work)
    assert res["status"] == "delivered", res
    tm = res["report"]["checks"]["tone_match"]
    assert tm["pass"] is True, tm

    target = rm.tone_target
    spans = _spans(rm)
    master = str(Path(work) / "master.mp4")
    m_prof = color_measure.clip_percentiles_batch(master, spans)
    d_prof = color_measure.clip_percentiles_batch(res["output"], spans)
    m_worst = max(_resid(p, target) for p in m_prof)
    d_worst = max(_resid(p, target) for p in d_prof)
    # the check read THIS file — not an inference, the two numbers are the same number
    assert m_worst == pytest.approx(tm["worst"], abs=0.01), (m_worst, tm)
    # and the choice of file decides the VERDICT, not merely the number. Measured: the
    # master reads 1.5 and the delivery 19.0 (episodes 18/65/198 and 21/67/197 against a
    # 37/82/207.5 target) — a check that sampled the delivery would have failed this reel
    # and escalated it to match-grade, which has nothing to fix.
    assert m_worst <= rm.check_spec.tone_match_max
    assert d_worst > rm.check_spec.tone_match_max, (m_prof, d_prof, target)


# --- Proof 7: the probe predicts the encode -----------------------------------

def test_probe_grade_geometry_predicts_the_encode(tmp_path, monkeypatch):
    """design §0.8, measured at 1 code on real footage. The probe renders three frames
    of episode 0 over its frozen route BEFORE any episode has ever been encoded; the
    clip that comes out of the real render must read the same.

    CONTROL (the brief names none, so: invented): the probe's number must be the GRADED
    one. Without that, "the probe agrees with the encode" would also hold for a probe
    that quietly ignored the EDL's colour block and an encode that did the same."""
    ctx = _run(tmp_path, monkeypatch, [(DARK, {}), (BRIGHT, {})])
    geo = _geometry(ctx)
    match_grade.write_match(ctx["geometry"])

    clip = Path(ctx["out"]) / "ep0.mp4"
    assert not clip.exists()                     # nothing has been encoded yet
    r = probe.probe_grade_geometry(ctx["geometry"], 0, out_dir=str(tmp_path / "probe0"))
    assert r["drift_checked"] is False           # there is no path.json to drift from
    predicted = tuple(r["tone_profile"])

    eg = geo.episodes[0]
    ungraded = color_measure.measure_crop(eg.manifest, eg.source, eg.route)
    assert _resid(predicted, ungraded) > matchgrade.MATCH_EPS, (predicted, ungraded)

    rm = _render(ctx)
    encoded = _profile(rm.episodes[0].clip)
    assert _resid(predicted, encoded) <= 1.5, (predicted, encoded)
