import json
import pytest
from scripts import track
from scripts.lib import models

class _FakeBox:
    def __init__(self, xywh, tid):
        self.xywh = [xywh]; self.id = [tid]; self.cls = [0]  # cls 0 = person


class _FakeRes:
    """An ultralytics-result-shaped fake: boxes only. No orig_img/masks, so
    appearance.crop_and_mask returns (None, None) — the same way the intake tests
    drive it. Tests that need real pixels build their own (see test_cast_pin.py)."""
    def __init__(self, boxes):
        self.boxes = boxes
        self.orig_img = None
        self.masks = None


def _fake_iter(frames):
    """The monkeypatch body every track test shares: frames of boxes → (i, res)."""
    return lambda src, **k: iter(enumerate(_FakeRes(f) for f in frames))

def test_route_from_frames(monkeypatch, tmp_path):
    # fake per-frame detections: subject slides right
    frames = [[_FakeBox([300 + i * 50, 500, 140, 320], 1)] for i in range(10)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", fps=30)
    route = track.build_route(spec, out=str(out))
    assert len(route) == 10
    assert isinstance(route[0], models.RoutePoint)
    assert route[0].x == 300 and route[-1].x == 300 + 9 * 50
    assert json.loads(out.read_text())[0]["x"] == 300

def test_route_seed_pin(monkeypatch, tmp_path):
    # two persistent tracks; the seed bbox must pin the RIGHT one as hero
    frames = [[_FakeBox([300, 500, 140, 320], 1),
               _FakeBox([1500, 500, 120, 300], 2)] for _ in range(10)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", fps=30, seed_bbox=(1500, 500, 120, 300))
    route = track.build_route(spec, out=str(out))
    assert all(pt.x == 1500 for pt in route)

def test_action_intent_prefers_mover_over_bystander(monkeypatch, tmp_path):
    # bystander in ALL 20 frames (static); mover in 12 frames, crosses frame.
    # most-frames would pick the bystander — scoring must pick the mover.
    frames = []
    for i in range(20):
        dets = [_FakeBox([960, 700, 150, 340], 7)]              # bystander
        if 4 <= i < 16:
            dets.append(_FakeBox([200 + (i - 4) * 120, 500, 140, 320], 9))
        frames.append(dets)
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    spec = models.TrackSpec(src="ignored.mp4", fps=30, intent="action")
    route = track.build_route(spec, out=str(tmp_path / "route.json"))
    xs = [pt.x for pt in route]
    assert xs[0] == 200 and xs[-1] == 200 + 11 * 120

def test_meta_flags_ambiguity(monkeypatch, tmp_path):
    # two indistinguishable static tracks → margin rule fires (spec §6.1a)
    frames = [[_FakeBox([500, 500, 140, 320], 1),
               _FakeBox([1400, 500, 140, 320], 2)] for _ in range(10)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", fps=30)
    track.build_route(spec, out=str(out))
    meta = models.TrackMeta.from_dict(json.loads((tmp_path / "route.meta.json").read_text()))
    assert meta.ambiguous is True

def test_unconfirmed_detections_never_become_hero(monkeypatch, tmp_path):
    # id=None detections (two DIFFERENT people) must not merge into a fake
    # track that outscores the real confirmed hero
    class _NoneBox:
        def __init__(self, xywh):
            self.xywh = [xywh]; self.id = None; self.cls = [0]
    frames = []
    for i in range(20):
        dets = [_FakeBox([600 + i * 20, 500, 140, 320], 3)]      # real hero
        dets.append(_NoneBox([200, 500, 100, 300] if i % 2 else [1700, 500, 100, 300]))
        frames.append(dets)
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", fps=30)
    route = track.build_route(spec, out=str(out))
    meta = models.TrackMeta.from_dict(json.loads((tmp_path / "route.meta.json").read_text()))
    assert meta.hero == 3
    assert "-1" not in meta.features
    assert [pt.x for pt in route] == [600 + i * 20 for i in range(20)]

def test_features_include_speed_and_border(monkeypatch, tmp_path):
    frames = [[_FakeBox([300 + i * 50, 500, 140, 320], 1)] for i in range(10)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    spec = models.TrackSpec(src="ignored.mp4", fps=30)
    track.build_route(spec, out=str(tmp_path / "route.json"))
    meta = models.TrackMeta.from_dict(json.loads((tmp_path / "route.meta.json").read_text()))
    feats = meta.features["1"]
    assert abs(feats["speed"] - 50.0) < 1e-6      # 50 px/frame
    assert feats["border"] is None                # dims unknown in mocked run

def test_fps_probe_when_not_given(monkeypatch, tmp_path, sample_clip):
    # fps=None → probed from the real file (sample fixture is 30fps 1920x1080)
    frames = [[_FakeBox([300, 500, 140, 320], 1)] for _ in range(5)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    spec = models.TrackSpec(src=str(sample_clip))
    route = track.build_route(spec, out=str(tmp_path / "route.json"))
    assert abs(route[1].t - 1 / 30) < 1e-6
    meta = models.TrackMeta.from_dict(json.loads((tmp_path / "route.meta.json").read_text()))
    assert meta.features["1"]["border"] is not None      # dims known from probe

def test_build_route_uses_spec_and_returns_routepoints(monkeypatch, tmp_path):
    # two tracks: id 1 stands still (big), id 2 crosses fast. intent must decide.
    frames = []
    for i in range(6):
        frames.append([_FakeBox([900, 500, 300, 600], 1),
                       _FakeBox([100 + i * 200, 500, 120, 300], 2)])
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))

    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="seg.mp4", intent="static", fps=30.0)
    route = track.build_route(spec, out=str(out))
    assert route and isinstance(route[0], models.RoutePoint)
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.hero == 1                      # static intent → the still, large subject


def _feats():
    # tid 1: left + small; tid 2: right + large
    return {1: {"n": 10, "disp": 0.0, "area": 100.0, "x0": 300.0, "speed": 0.0, "border": None},
            2: {"n": 10, "disp": 0.0, "area": 900.0, "x0": 1500.0, "speed": 0.0, "border": None}}


def test_rule_track_largest():
    assert track._rule_track(_feats(), "largest") == 2


def test_rule_track_leftmost():
    assert track._rule_track(_feats(), "leftmost") == 1


def test_rule_track_breaks_ties_on_the_lowest_id():
    feats = {5: {"area": 100.0, "x0": 10.0}, 2: {"area": 100.0, "x0": 10.0}}
    assert track._rule_track(feats, "largest") == 2
    assert track._rule_track(feats, "leftmost") == 2


def test_rule_track_empty_feats_is_unmatched():
    assert track._rule_track({}, "largest") is None


def test_rule_track_unknown_rule_raises_instead_of_answering_leftmost():
    # a typo'd rule must NOT silently select a DIFFERENT valid rule -- that is the
    # same silent substitution this slice exists to delete, one level down. The
    # sibling rung _id_track answers an unmatched pin with an honest None; a rule
    # this function does not know is not "unmatched", it is a caller bug.
    with pytest.raises(ValueError) as e:
        track._rule_track(_feats(), "tallest")
    msg = str(e.value)
    assert "_rule_track" in msg                              # names the function
    assert "tallest" in msg                                  # echoes the offending rule
    for r in models.HERO_RULES:                              # lists what IS accepted
        assert r in msg


def test_id_track_hit_and_miss():
    assert track._id_track(_feats(), 2) == 2
    assert track._id_track(_feats(), 99) is None


def test_ambig_margin_is_the_one_spelling_of_the_margin_rule():
    assert track.AMBIG_MARGIN == 0.8


def test_pick_hero_reads_ambig_margin_not_a_reinlined_literal(monkeypatch):
    # score ratio pinned at 0.85 (intent="static": score = n/mx_n + area/mx_area;
    # n equal so that term is 1.0 for both, area 100 vs 70 -> scores 2.0 vs 1.7).
    # Ambiguous under the real 0.8 margin (1.7 >= 0.8*2.0) but not once the margin
    # is raised past that ratio -- the flip only happens if _pick_hero reads
    # track.AMBIG_MARGIN itself at call time, rather than a re-inlined 0.8 literal
    # that a future edit could silently reintroduce (the constant exists precisely
    # so there is one spelling of the margin, not two that can drift apart).
    feats = {1: {"n": 10, "disp": 0.0, "area": 100.0},
             2: {"n": 10, "disp": 0.0, "area": 70.0}}
    _, ambiguous = track._pick_hero(feats, "static")
    assert ambiguous is True
    monkeypatch.setattr(track, "AMBIG_MARGIN", 0.9)
    _, ambiguous_raised = track._pick_hero(feats, "static")
    assert ambiguous_raised is False


def _desc(*channels):
    """A hand-built descriptor: `channels` are per-channel weights, HIST_BINS wide."""
    from scripts.lib.appearance import HIST_BINS
    d = []
    for w in channels:
        d.extend([w / HIST_BINS] * HIST_BINS)
    return tuple(d)


def test_descriptor_track_picks_the_closest():
    crops = {1: [1.0, 0.0, 0.0] + [0.0] * 21, 2: [0.0, 0.0, 1.0] + [0.0] * 21}
    pin = tuple([0.0, 0.0, 1.0] + [0.0] * 21)
    hero_id, ambiguous = track._descriptor_track(crops, pin)
    assert hero_id == 2 and ambiguous is False


def test_descriptor_track_beyond_the_threshold_is_unmatched():
    # both tracks sit at the maximum distance (disjoint supports) → nobody matches
    crops = {1: [1.0] + [0.0] * 23, 2: [1.0] + [0.0] * 23}
    pin = tuple([0.0] * 23 + [1.0])
    hero_id, ambiguous = track._descriptor_track(crops, pin)
    assert hero_id is None and ambiguous is False


def test_descriptor_track_margin_flags_ambiguity():
    # two near-identical descriptors → d1 >= 0.8*d2 → §6.1a mode 1
    crops = {1: [0.50, 0.50] + [0.0] * 22, 2: [0.52, 0.48] + [0.0] * 22}
    pin = tuple([0.51, 0.49] + [0.0] * 22)
    hero_id, ambiguous = track._descriptor_track(crops, pin)
    assert hero_id in (1, 2) and ambiguous is True


def test_descriptor_track_single_track_is_never_ambiguous():
    crops = {7: [1.0, 0.0] + [0.0] * 22}
    hero_id, ambiguous = track._descriptor_track(crops, tuple([1.0, 0.0] + [0.0] * 22))
    assert hero_id == 7 and ambiguous is False


def test_descriptor_track_no_crops_is_unmatched():
    assert track._descriptor_track({}, _desc(1.0, 0.0, 0.0)) == (None, False)
