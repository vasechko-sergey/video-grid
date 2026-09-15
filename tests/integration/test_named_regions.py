"""Real ffmpeg, real camera footage, real tracked rider (design 2026-09-15).

Three claims, each with a control that must NOT move:

1. Naming the subject as the toe's reference moves the toe and only the toe.
2. The region ruler and the pooled ruler read the same crop, from one decode.
3. A run with no REGIONS.json writes the same EDL and the same target, and a
   run WITH one does not.

The fixture is `golden_ride_segment` plus `tests/fixtures/golden_route.json` —
the repo's only real footage with a real tracked person. The task brief said the
ride fixture "carries no tracked person" and pointed these proofs at
test_color_measure.py's synthetic `_subject_episode` instead; measured, that is
wrong (golden_route.json is the tracker's own output over this clip, a 77x175
box averaging 1.54% of the delivered crop), and the synthetic case is already
proven one layer down by
test_color_measure.py::test_a_subject_declaration_moves_the_toe_and_nothing_else.
Using the real clip here makes these proofs new evidence rather than a second
copy of that one, and it reproduces the design's §0.5 direction — deeper blacks
— on camera pixels: 38 -> 24 at p5, +0 at p50 and p95.
"""
import json
from pathlib import Path

import pytest
from scripts import color_measure, match_grade, process_episode
from scripts.lib import color, matchgrade, regions
from scripts.lib.edl import EDL, EDLEpisode
from scripts.lib.models import EpisodeGeometry, ReelGeometry

pytestmark = pytest.mark.integration

#: The route the tracker wrote over golden_ride.mp4, and the span it covers.
_ROUTE = str(Path(__file__).parent.parent / "fixtures" / "golden_route.json")
_DUR = 1.5

#: The toe-from-subject declaration, in the design's own §2.1 spelling. `wetsuit`
#: is the author's noun; nothing here or anywhere verifies that the dark end of
#: this route's box is actually a wetsuit (design §6), and these tests do not
#: pretend to — they measure that the SUBJECT REGION supplied the toe.
_TOE_DECL = {"anchors": [{"anchor": "toe", "name": "wetsuit", "of": "subject"}]}


def _episode_inputs(src) -> dict:
    """The ride segment as a whole-frame episode manifest.

    canvas [16, 9] matches the 1280x720 source exactly, so a `fill` layout's
    freedom is 0 and the crop IS the frame — the crop-vs-frame discrimination is
    test_color_measure.py's business, and holding it constant here is what leaves
    the region declaration as the only thing that can move a number.
    """
    return {"segment": str(src), "out_path": "ep.mp4", "composition": "center",
            "grid": "thirds", "canvas": [16, 9], "target_dur": _DUR}


def test_a_declared_subject_toe_moves_the_toe_and_only_the_toe(golden_ride_segment):
    """Design §0.5's headline, on real footage: naming the subject as the toe
    reference pulls p5 down and leaves p50 and p95 bit-identical.

    The control is the second and third anchors. They are not pinned by
    construction — they are read from the same three decoded frames through the
    same assembly, and a declaration that leaked across anchors (or an `assemble`
    that indexed every anchor at slot 0) would move them."""
    md = _episode_inputs(golden_ride_segment)
    plain, plain_rows = color_measure.measure_crop(md, str(golden_ride_segment), _ROUTE)
    decl = regions.Regions.from_dict(_TOE_DECL)
    toned, rows = color_measure.measure_crop(md, str(golden_ride_segment), _ROUTE, decl=decl)

    assert toned[1] == plain[1] and toned[2] == plain[2], (toned, plain)   # control
    assert toned[0] < plain[0] - matchgrade.MATCH_EPS, (toned, plain)
    # Pinned, not merely "moved": a bare inequality cannot tell "read the rider"
    # from "read some other darker thing", and these are the numbers the design's
    # own direction (deeper blacks) is claimed on.
    assert plain == pytest.approx((38.0, 84.0, 215.0))
    assert toned == pytest.approx((24.0, 84.0, 215.0))

    assert rows[0].of == "subject" and rows[0].used == "subject"
    assert rows[0].name == "wetsuit" and rows[0].fallback is None
    # Above MIN_REGION_FRAC, and not by much: this is the real scale design §0.1
    # measured — 0.23% to 37% of the frame, a 161x spread across one reel — not a
    # fixture built to clear the gate. (§0.1's prose says "0.14%"; its own table's
    # minimum is 0.23% and 37.09/0.23 is the 161x it states, so the table is what
    # is cited here.)
    assert regions.MIN_REGION_FRAC < rows[0].fraction < 0.03
    assert [r.used for r in plain_rows] == ["crop", "crop", "crop"]
    assert all(r.fallback is None for r in plain_rows)


def test_the_region_ruler_and_the_pooled_ruler_agree_on_the_crop(golden_ride_segment):
    """One ruler (Global Constraints). The crop region's profile must EQUAL
    crop_percentiles' pooled reading, not merely approximate it.

    The control is that this is the same decode: `crop_region_frames` issues the
    identical ffmpeg call `crop_percentiles` does, with the select appended
    through `with_tail`. Prepending it instead (the §12 landmine) emits one frame
    three times, and the two readings diverge — which is what this test is for."""
    md = _episode_inputs(golden_ride_segment)
    plan, _, _ = process_episode.plan_and_meta_ungraded(md, str(golden_ride_segment), _ROUTE)
    times = color.sample_times(plan.dur)
    assert len(times) == 3
    stack = color_measure.crop_region_frames(plan, str(golden_ride_segment), times)
    assert stack.shape == (3, plan.rl.out_h, plan.rl.out_w)
    # Three DIFFERENT frames, not one repeated: the landmine's signature is a
    # stack whose planes are identical, and a ruler comparison alone cannot see
    # it on footage flat enough for the percentiles to survive the collapse.
    assert not (stack[0] == stack[1]).all() or not (stack[1] == stack[2]).all()
    assert regions.measure(stack, None)["crop"].profile == \
        color_measure.crop_percentiles(plan, str(golden_ride_segment), times)


def _geometry_and_edl(tmp_path, src) -> tuple[str, str]:
    """(GEOMETRY.json path, EDL.json path) for a one-episode reel over `src`.

    Modelled on test_matchgrade.py's `_whole_frame_geometry`, plus the one thing
    this slice added: a `project.json` on disk at the path the geometry records,
    so `_find_regions` has a reachable directory to look for REGIONS.json beside
    (design §2.1's third state is about NOT having one)."""
    project = tmp_path / "project.json"
    project.write_text(json.dumps({"canvas": [16, 9], "delivery": "native"}))
    edl_path = tmp_path / "EDL.json"
    ep = EDLEpisode(source=str(src), start=0.0, dur=_DUR, shot_type="wide",
                    composition="center", grid="thirds")
    edl_path.write_text(json.dumps(EDL(episodes=(ep,)).to_dict(), indent=2))
    geo = ReelGeometry(
        episodes=(EpisodeGeometry(manifest=_episode_inputs(src), route=_ROUTE,
                                  source=str(src), project_dir=str(tmp_path / "p0")),),
        edl=str(edl_path), project=str(project))
    geo_path = tmp_path / "GEOMETRY.json"
    geo.write(geo_path)
    return str(geo_path), str(edl_path)


def test_a_run_with_no_declaration_writes_the_same_edl_and_target(tmp_path, golden_ride_segment):
    """The byte-identical default path, through the REAL driver and a real
    measure_crop — every other test of `write_match` in this suite fakes the
    measurement.

    The control is a third run WITH a declaration, which must differ. Without it
    the first assertion passes because nothing is wired at all."""
    geo, edl = _geometry_and_edl(tmp_path, golden_ride_segment)

    a = match_grade.write_match(geo)
    before = Path(edl).read_bytes()
    b = match_grade.write_match(geo, force=True)
    assert Path(edl).read_bytes() == before
    assert a["target"] == b["target"] == [38.0, 84.0, 215.0]
    assert a["regions"] == ""                       # reachable project, no declaration
    assert "No REGIONS.json — every anchor is the whole crop." in \
        Path(a["md"]).read_text()

    (Path(geo).parent / "REGIONS.json").write_text(json.dumps(_TOE_DECL))
    c = match_grade.write_match(geo, force=True)
    assert c["target"] != a["target"]                                     # control
    assert c["target"] == [24.0, 84.0, 215.0]
    assert c["regions"] == str(Path(geo).parent / "REGIONS.json")

    md = Path(c["md"]).read_text()
    assert f"Anchors declared in {c['regions']}." in md
    assert "| 0 | toe | wetsuit | subject |" in md
    rows = json.loads(Path(c["json"]).read_text())["decisions"][0]["regions"]
    assert [(r["anchor"], r["of"], r["used"], r["fallback"]) for r in rows] == [
        ("toe", "subject", "subject", None), ("mid", "crop", "crop", None),
        ("shoulder", "crop", "crop", None)]
