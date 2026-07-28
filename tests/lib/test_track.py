import sys
import types

from scripts import track
from scripts.lib.manifest import DEFAULT_MODEL


def _fake_ultralytics(calls):
    """A stand-in ultralytics module whose YOLO records the path it was built with.
    Faked at the sys.modules level because ensure_model imports ultralytics lazily,
    INSIDE the function — so the fake must be in place at call time, not import time.
    Keeps the fast tier free of real weights and of any network access."""
    mod = types.ModuleType("ultralytics")

    class _YOLO:
        def __init__(self, path):
            calls.append(path)

    mod.YOLO = _YOLO
    return mod


def test_ensure_model_constructs_the_named_model(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "ultralytics", _fake_ultralytics(calls))
    track.ensure_model("yolo11s-seg.pt")
    assert calls == ["yolo11s-seg.pt"]


def test_ensure_model_defaults_to_the_module_model(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "ultralytics", _fake_ultralytics(calls))
    track.ensure_model()
    assert calls == [track.MODEL]


def test_the_module_model_matches_the_manifest_default():
    # The fan-out warms track.MODEL (scripts/edl_to_reel.py) while every worker ends up
    # constructing manifest.DEFAULT_MODEL (Manifest -> TrackSpec -> _iter_detections).
    # They are independent literals. If they ever drift, the driver warms model A while N
    # workers race a cold download of model B into one path — precisely the silent
    # corruption the warm-up exists to prevent, and nothing else asserts they agree.
    assert track.MODEL == DEFAULT_MODEL


def test_available_true_when_ultralytics_imports():
    # this repo's env ships ultralytics (requirements.txt), so the gate is open
    assert track.available() is True


def test_available_false_when_ultralytics_absent(monkeypatch):
    # setting the module to None makes `import ultralytics` raise ImportError —
    # the "ultralytics unavailable" rung-1 trigger, simulated without uninstalling
    monkeypatch.setitem(sys.modules, "ultralytics", None)
    assert track.available() is False


# --- ID-switch stitching (§6.1a) ------------------------------------------------

def _frames(spans):
    """spans: {tid: (first, last, x0, dx, w, h)} → the per_frame shape build_route builds."""
    n = 1 + max(s[1] for s in spans.values())
    out = []
    for idx in range(n):
        dets = []
        for tid, (a, b, x0, dx, w, h) in spans.items():
            if a <= idx <= b:
                dets.append((tid, x0 + dx * (idx - a), 500.0, w, h))
        out.append((idx, dets))
    return out


def test_segments_records_ends_count_and_per_frame_x():
    pf = _frames({1: (0, 4, 100.0, 10.0, 120, 300)})
    assert track._segments(pf) == {1: {"first": 0, "last": 4, "n": 5,
                                       "head": (100.0, 500.0, 120, 300),
                                       "tail": (140.0, 500.0, 120, 300),
                                       "at": {0: 100.0, 1: 110.0, 2: 120.0,
                                              3: 130.0, 4: 140.0}}}


def test_median_handles_odd_and_even_lengths():
    assert track._median([3.0, 1.0, 2.0]) == 2.0
    assert track._median([1.0, 2.0, 3.0, 4.0]) == 2.5


def test_joinable_overlap_uses_shared_frames_and_skips_the_area_gate():
    # two segments that share frames 2..4, ~3px apart, one box COLLAPSING (area would
    # reject on endpoints) — the overlap regime joins them anyway.
    a = {"at": {0: 100.0, 1: 101.0, 2: 102.0, 3: 103.0, 4: 104.0},
         "tail": (104.0, 500.0, 40, 80), "head": (100.0, 500.0, 104, 207)}
    b = {"at": {2: 105.0, 3: 106.0, 4: 107.0, 5: 108.0},
         "head": (105.0, 500.0, 70, 116), "tail": (108.0, 500.0, 70, 116)}
    assert track._joinable(a, b, gap=-2, speed=3.0, src_w=1920) is True


def test_joinable_gap_joins_within_reach_and_same_size_class():
    a = {"at": {0: 100.0}, "tail": (100.0, 500.0, 120, 300), "head": (100.0, 500.0, 120, 300)}
    b = {"at": {10: 130.0}, "head": (130.0, 500.0, 120, 300), "tail": (130.0, 500.0, 120, 300)}
    # 30px jump vs reach = max(0.02*1920=38.4, 3.0*9*3.0=81.0) = 81.0; same size → joins
    assert track._joinable(a, b, gap=9, speed=3.0, src_w=1920) is True


def test_joinable_gap_refuses_a_jump_beyond_reach():
    a = {"at": {0: 100.0}, "tail": (100.0, 500.0, 120, 300), "head": (100.0, 500.0, 120, 300)}
    b = {"at": {10: 900.0}, "head": (900.0, 500.0, 120, 300), "tail": (900.0, 500.0, 120, 300)}
    assert track._joinable(a, b, gap=9, speed=3.0, src_w=1920) is False


def test_joinable_gap_refuses_a_very_different_size():
    a = {"at": {0: 100.0}, "tail": (100.0, 500.0, 120, 300), "head": (100.0, 500.0, 120, 300)}
    b = {"at": {10: 110.0}, "head": (110.0, 500.0, 20, 40), "tail": (110.0, 500.0, 20, 40)}
    assert track._joinable(a, b, gap=9, speed=3.0, src_w=1920) is False


_SPEED = {1: {"speed": 3.0}}


def test_stitch_joins_a_track_that_resumes_where_the_hero_stopped():
    # the measured case: hero ends at frame 182, a new id picks the SAME subject up at 183
    pf = _frames({1: (0, 182, 900.0, 3.0, 120, 300),
                  142: (183, 550, 1450.0, 3.0, 130, 310)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1, 142}


def test_stitch_refuses_a_stranger_across_the_frame():
    pf = _frames({1: (0, 182, 900.0, 3.0, 120, 300),
                  9: (183, 550, 200.0, 3.0, 120, 300)})     # 1250px away in one frame
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1}


def test_stitch_refuses_a_resumption_after_a_long_gap():
    # 0.4s at 60fps = 24 frames; 40 is past it — not a blink, a different moment
    pf = _frames({1: (0, 182, 900.0, 3.0, 120, 300),
                  7: (223, 550, 1450.0, 3.0, 120, 300)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1}


def test_stitch_refuses_a_track_of_a_very_different_size():
    pf = _frames({1: (0, 182, 900.0, 3.0, 120, 300),
                  8: (183, 550, 1450.0, 3.0, 20, 40)})      # a distant bystander
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1}


def test_stitch_ignores_noise_fragments():
    pf = _frames({1: (0, 182, 900.0, 3.0, 120, 300),
                  5: (183, 185, 1450.0, 3.0, 120, 300)})    # 3 frames < STITCH_MIN_FRAMES
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1}


def test_stitch_chains_through_two_switches():
    pf = _frames({1: (0, 100, 900.0, 3.0, 120, 300),
                  2: (101, 200, 1210.0, 3.0, 120, 300),
                  3: (201, 300, 1520.0, 3.0, 120, 300)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1, 2, 3}


def test_stitch_reaches_backwards_for_the_head_of_a_shot():
    # `largest` picks the LONGER late fragment; the take-off is the earlier one
    pf = _frames({4: (0, 100, 600.0, 3.0, 120, 300),
                  1: (101, 500, 910.0, 3.0, 120, 300)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1, 4}


def test_stitch_with_no_hero_stitches_nothing():
    pf = _frames({1: (0, 182, 900.0, 3.0, 120, 300)})
    assert track.stitch_ids(pf, None, 60.0, 1920, _SPEED) == set()


def test_stitch_without_a_frame_width_declines_to_guess():
    # build_route skips the probe when the caller supplies fps — no scale, no stitch
    pf = _frames({1: (0, 182, 900.0, 3.0, 120, 300),
                  142: (183, 550, 1450.0, 3.0, 130, 310)})
    assert track.stitch_ids(pf, 1, 60.0, None, _SPEED) == {1}


def test_stitch_joins_an_overlapping_handover():
    # the measured shape: ByteTrack confirms the new id 2 frames BEFORE it drops the old.
    # Positions and boxes are the real ones — tid 1 ends at (845, 151x360) and tid 66
    # opens at (868, 142x352): 23px apart, the same rider.
    pf = _frames({1: (0, 182, 1027.0, -1.0, 151, 360),      # tail x = 1027 - 182 = 845
                  66: (180, 547, 868.0, 1.0, 142, 352)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1, 66}


def test_stitch_refuses_a_bystander_who_brackets_the_hero():
    # a track spanning the whole shot (0..500) gives a LARGE negative gap at both ends
    # (fwd -300, bwd -400) — the gap-range window refuses it before the extend guard is
    # ever reached. The shadowed-inside case below is what exercises the extend guard.
    pf = _frames({1: (100, 300, 900.0, 3.0, 120, 300),
                  5: (0, 500, 880.0, 0.0, 120, 300)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1}


def test_stitch_refuses_a_shadowed_bystander_inside_the_hero():
    # tid 5's whole track sits INSIDE the hero's, near its tail. Forward the gap is
    # 20-40 = -20 (inside the window) and 5 does NOT extend coverage (last 35 <= the
    # hero's 40), so ONLY the extend guard refuses it — were it removed, the overlap
    # regime (frames 20..35, 20px apart) would wrongly join it. Backward it falls to
    # the gap check (0-35 = -35, past the -30 overlap floor), so it is never added.
    pf = _frames({1: (0, 40, 900.0, 0.0, 120, 300),
                  5: (20, 35, 880.0, 0.0, 120, 300)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1}


def test_stitch_refuses_an_overlap_longer_than_a_handover():
    # 0.5s at 60fps = 30 frames; a 61-frame overlap is two people, not one handover
    pf = _frames({1: (0, 182, 900.0, 3.0, 120, 300),
                  6: (122, 547, 1450.0, 3.0, 120, 300)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1}


def test_stitch_uses_where_two_overlapping_tracks_actually_sit():
    # the same rider handed over across a 29-frame overlap, with the outgoing track's
    # box COLLAPSING through spray (104x207 -> 70x116). The area gate would reject that
    # pair on endpoints alone; on the frames they share they are 3px apart.
    pf = _frames({1: (0, 157, 1079.0, -1.13, 104, 207),
                  7: (129, 177, 1079.0 - 1.13 * 129 + 3, -1.13, 70, 116)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1, 7}


def test_stitch_refuses_two_people_who_merely_coexist():
    # same overlap, same sizes — but 400px apart on every frame they share
    pf = _frames({1: (0, 157, 1079.0, -1.13, 104, 207),
                  7: (129, 177, 1079.0 - 1.13 * 129 + 400, -1.13, 104, 207)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1}


def test_stitch_chains_a_shot_fragmented_into_four():
    # the measured day-1 ride: overlap, overlap, then a 2-frame gap
    pf = _frames({1:  (0,   157, 1079.0, -1.13, 104, 207),
                  7:  (129, 177,  934.0, -0.4,   76, 112),
                  10: (168, 221,  905.0,  1.0,   70, 116),
                  14: (223, 547,  958.0,  0.23,  81, 175)})
    assert track.stitch_ids(pf, 1, 60.0, 1920, _SPEED) == {1, 7, 10, 14}
