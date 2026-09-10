"""The two reports say what they could not measure (design 2026-09-10).

No ffmpeg: both proofs drive the real scorer and the real edit_plan census over
constructed footage. Each carries a CONTROL that must NOT move — a report that
fires on everything is not a report."""
import json

from scripts import edit_plan, intake
from scripts.lib.footage import Footage, FootageClip, FootageWindow


def _win(present, motion=0.3, shake=0.0, sw=0.2, sh=0.2):
    return FootageWindow(start=0.0, dur=2.0, shot_type="wide", people=1 if present else 0,
                         motion=motion, shake=shake, present=present,
                         subject_w=sw, subject_h=sh)


def _clip(src, wins):
    return FootageClip(source=src, dur=60.0, res=(3840, 2160), fps=30.0, windows=wins)


def test_a_pool_where_everyone_is_present_reports_presence_separated_nothing(tmp_path):
    # motion AND shake both vary too, independently of each other and of `present`.
    # Holding shake constant at 0.0 throughout (as a first draft of this fixture
    # did) would make separated["shake"] structurally 0 whether or not score_pool
    # even reads w.shake — the exact hole a sibling unit test in test_intake.py was
    # reviewed into closing (test_score_pool_reports_a_presence_term_that_separated_nothing,
    # "review follow-up, MINOR 1"). Mirroring that fixture's shape here instead.
    wins = [_win(1.0, motion=m, shake=s) for m, s in
           zip((0.1, 0.2, 0.3, 0.4, 0.5, 0.6), (0.6, 0.5, 0.4, 0.3, 0.2, 0.1))]
    clips = [_clip("a.mp4", wins)]
    f = Footage(clips=clips, band=(1.2, 4.0), scoring=intake.score_pool(clips))
    assert f.scoring["separated"]["present"] == 0
    assert f.scoring["separated"]["motion"] > 0
    assert f.scoring["separated"]["shake"] > 0
    p = tmp_path / "FOOTAGE.json"
    p.write_text(json.dumps(f.to_dict(), indent=2))
    # it survives the round trip a downstream stage actually performs
    assert Footage.from_json(p).scoring["separated"]["present"] == 0
    assert "**present** 0/6" in f.to_markdown()


def test_control_a_pool_where_presence_varies_reports_presence_as_working():
    # motion and shake held constant here ON PURPOSE, mirroring the reviewed
    # unit-level control (test_score_pool_reports_a_presence_term_that_did_separate):
    # this control isolates presence's OWN separation working, so a bug that only
    # broke `present`'s path can't hide behind motion or shake picking up the slack.
    # Leaving them at 0 costs nothing here — the test above already varies both, and
    # test_intake.py pins _separated's own tie-counting directly — so this fixture
    # doesn't need to re-earn that coverage.
    wins = [_win(p, motion=0.3, shake=0.0) for p in (0.0, 0.25, 0.5, 0.75, 1.0, 1.0)]
    clips = [_clip("a.mp4", wins)]
    scoring = intake.score_pool(clips)
    assert scoring["separated"]["present"] == 4      # largest tie is the two 1.0s
    assert scoring["separated"]["motion"] == 0        # held constant: isolates presence
    assert scoring["separated"]["shake"] == 0         # held constant: isolates presence
    assert "**present** 0/6" not in Footage(clips=clips, scoring=scoring).to_markdown()


def test_a_people_free_census_says_it_could_not_see():
    wins = [FootageWindow(start=float(i), dur=2.0, shot_type="wide", people=0,
                          motion=0.3, shake=0.0, present=0.0,
                          subject_w=0.0, subject_h=0.0) for i in range(9)]
    counts, unmeasured = edit_plan._available_census(Footage(clips=[_clip("a.mp4", wins)]),
                                                     (9, 16))
    assert counts == {"close": 0, "medium": 0, "wide": 9}
    assert unmeasured == 9        # every one of them: the census measured nothing


def test_control_a_people_bearing_census_reports_no_blind_windows():
    wins = [FootageWindow(start=float(i), dur=2.0, shot_type="wide", people=1,
                          motion=0.3, shake=0.0, present=1.0,
                          subject_w=0.30, subject_h=0.40) for i in range(9)]
    counts, unmeasured = edit_plan._available_census(Footage(clips=[_clip("a.mp4", wins)]),
                                                     (9, 16))
    assert unmeasured == 0
    # Measured, not assumed (task-6 report): a 0.30x0.40 source-fraction subject
    # through a 9:16 crop of a 3840x2160 source (crop 1215x2160) reads `close` in
    # DELIVERED geometry — not `medium`, its own source-only tag, and nowhere near
    # `wide`. All nine land there, so this checks the exact bucket a genuine
    # measurement produces, not merely that a few of nine escaped `wide`.
    assert counts == {"close": 9, "medium": 0, "wide": 0}
