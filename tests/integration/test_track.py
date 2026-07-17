import json
import numpy as np
import pytest
from scripts import track
from scripts.lib import models, orchestration
from scripts.lib.appearance import HIST_BINS

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

def test_route_bbox_pin(monkeypatch, tmp_path):
    # two persistent tracks; the seed bbox must pin the RIGHT one as hero
    frames = [[_FakeBox([300, 500, 140, 320], 1),
               _FakeBox([1500, 500, 120, 300], 2)] for _ in range(10)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", fps=30,
                            pin=models.HeroPin(kind="bbox", bbox=(1500.0, 500.0, 120.0, 300.0)))
    route = track.build_route(spec, out=str(out))
    assert all(pt.x == 1500 for pt in route)
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.pin_matched is True


# A pin's whole job is to OUTRANK the intent scoring it replaces, so each fixture
# below makes the two DISAGREE: the pinned track is deliberately not the one
# _pick_hero would choose. Both fixtures used to answer the same track either way,
# which left the rule and track-id rungs unable to tell a working pin from a
# re-inlined `hero_id = _pick_hero(feats, spec.intent)` — the exact silent
# substitution this slice exists to delete. The mover/bystander split does it: with
# intent="action" the displacement term carries weight 2.0 against area's 0.3, so
# whoever crosses the frame wins the scoring no matter how small they are.
#
# Both also assert the route as a LIST rather than with all(): `all()` over the
# empty route an unmatched rung returns is VACUOUSLY TRUE, so the old assertions
# held even when the rung picked nobody at all.


def test_route_rule_pin(monkeypatch, tmp_path):
    # "largest" must win on SIZE: track 2 is the big bystander standing still,
    # track 1 the small one crossing the frame that action scoring prefers. A rule
    # makes no claim about identity — the human said largest, so largest wins.
    frames = [[_FakeBox([200 + i * 100, 500, 140, 320], 1),
               _FakeBox([1500, 500, 300, 700], 2)] for i in range(10)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    spec = models.TrackSpec(src="ignored.mp4", fps=30,
                            pin=models.HeroPin(kind="rule", rule="largest"))
    route = track.build_route(spec, out=str(tmp_path / "route.json"))
    assert [pt.x for pt in route] == [1500.0] * 10


def test_route_track_id_pin(monkeypatch, tmp_path):
    # The named id must win outright: track 1 is the small static one the human
    # pinned, track 2 the big mover scoring would hand back instead.
    frames = [[_FakeBox([300, 500, 140, 320], 1),
               _FakeBox([200 + i * 100, 500, 300, 700], 2)] for i in range(10)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    spec = models.TrackSpec(src="ignored.mp4", fps=30,
                            pin=models.HeroPin(kind="track", track_id=1))
    route = track.build_route(spec, out=str(tmp_path / "route.json"))
    assert [pt.x for pt in route] == [300.0] * 10


def test_unmatched_pin_never_falls_back_to_scoring(monkeypatch, tmp_path):
    # the pinned track id is not in this segment: the route must be EMPTY and the
    # sidecar must say so — silently following whoever scored highest is the bug
    # this slice deletes
    frames = [[_FakeBox([300, 500, 140, 320], 1)] for _ in range(10)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", fps=30,
                            pin=models.HeroPin(kind="track", track_id=99))
    route = track.build_route(spec, out=str(out))
    assert route == []
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.pin_matched is False and meta.hero is None


def test_a_pin_over_an_empty_segment_reports_no_track_not_hero_unmatched(monkeypatch, tmp_path):
    """The real producer feeding the real gate, for the case the pre-emption gets wrong.

    A rule pin over frames the detector found nobody in: _rule_track({}, "largest")
    returns None for an empty feats, so build_route writes pin_matched=False — and
    the gate used to read that alone and answer hero-unmatched, whose detail talks
    about "the pinned person" and "the cast descriptor". A rule pin names no person
    and claims no identity, so that is a diagnosis of a claim it never made; and it
    was the DETECTOR, not the pin, that emptied the route. `features` is what tells
    the two apart, which is why this drives build_route rather than hand-writing a
    sidecar: it pins the producer and the consumer to the same story.
    """
    frames = [[] for _ in range(10)]            # detector confirms nobody, ten frames running
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", fps=30,
                            pin=models.HeroPin(kind="rule", rule="largest"))
    route = track.build_route(spec, out=str(out))
    meta = json.loads(out.with_suffix(".meta.json").read_text())
    assert route == [] and meta["pin_matched"] is False and meta["features"] == {}
    findings = orchestration.detect_contradictions(motion=None, route=[], track_meta=meta,
                                                   src_w=1920, src_h=1080)
    assert [f["reason"] for f in findings] == ["no-track"]


def test_no_pin_leaves_pin_matched_none(monkeypatch, tmp_path):
    frames = [[_FakeBox([300 + i * 50, 500, 140, 320], 1)] for i in range(10)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    out = tmp_path / "route.json"
    track.build_route(models.TrackSpec(src="ignored.mp4", fps=30), out=str(out))
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.pin_matched is None


def test_build_route_raises_on_an_unrecognized_pin_kind(monkeypatch, tmp_path):
    # HeroPin.kind is gated to HERO_KINDS at construction, so this can only be
    # reached by a caller that bypasses HeroPin's own validation (e.g. HERO_KINDS
    # grows a 5th kind with no matching rung here). The dispatch must raise, not
    # silently treat the new kind as "cast" — same reasoning as _rule_track's
    # raise-on-an-unimplemented-rule: the raise is keyed to the branches actually
    # implemented, not to vocabulary membership, so a vocab that outgrows the
    # dispatch fails loud instead of guessing.
    monkeypatch.setattr(models, "HERO_KINDS", models.HERO_KINDS + ("beacon",))
    bogus_pin = models.HeroPin(kind="beacon")
    frames = [[_FakeBox([300, 500, 140, 320], 1)] for _ in range(10)]
    monkeypatch.setattr(track, "_iter_detections", _fake_iter(frames))
    spec = models.TrackSpec(src="ignored.mp4", fps=30, pin=bogus_pin)
    with pytest.raises(ValueError, match="beacon"):
        track.build_route(spec, out=str(tmp_path / "route.json"))

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


def _twin(shift: float) -> list[float]:
    """A descriptor at L1 distance exactly `2 * shift` from `_CAST_PIN` — one of two
    near-identical twins whose RELATIVE distance is the only thing the margin rule
    reads (§6.1a mode 1: two people in similar clothing).

    Shaped the way build_descriptor really emits: three per-channel histograms
    normalized over the GRAND total, so each channel's HIST_BINS bins sum to 1/3 —
    every pixel feeds all three. Only red differs from the pin: `shift` of its mass
    moves from bin 0 to bin 1, costing `shift` out of one bin plus `shift` into the
    next; green and blue are the pin's own and cancel. So two twins' distance ratio
    is just their shift ratio — which is what lets a fixture sit at a CHOSEN ratio
    either side of AMBIG_MARGIN instead of only at the degenerate extremes.
    """
    red = [1 / 3 - shift, shift] + [0.0] * (HIST_BINS - 2)
    green_blue = ([1 / 3] + [0.0] * (HIST_BINS - 1)) * 2
    return red + green_blue


_CAST_PIN = tuple(_twin(0.0))       # the pinned cast member: each channel's mass in bin 0


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


# --- the margin band: where "clearly this one" ends and a coin flip begins ----
# The pair below are the ONLY cases that enter the band AMBIG_MARGIN*d2 <= d1 < d2.
# Every other _descriptor_track fixture sits at a degenerate extreme — d1 == d2 (a
# tie, ambiguous under ANY margin) or d1 == 0 against a far runner-up (confident
# under any) — so none of them can see what AMBIG_MARGIN's VALUE is. Straddling the
# band from both sides is what pins it: the ratios are 0.85 and 0.75, so the
# constant is held inside (0.75, 0.85] and a margin that drifts either way fails
# here instead of silently widening or narrowing the band a human gets called into.


def test_descriptor_track_reads_ambig_margin_not_a_reinlined_literal(monkeypatch):
    # INSIDE the band: d1 = 0.17, d2 = 0.20 → ratio 0.85. Ambiguous under the real
    # 0.8 margin (0.17 >= 0.16), confident once the margin is raised past the ratio
    # (0.17 < 0.18) — and that flip can only happen if _descriptor_track reads
    # track.AMBIG_MARGIN at call time rather than a re-inlined 0.8 that could later
    # drift from _pick_hero's copy. The constant's comment claims "one spelling, two
    # readers"; this is the second reader's half of that claim (the first is
    # test_pick_hero_reads_ambig_margin_not_a_reinlined_literal above).
    crops = {1: _twin(0.085), 2: _twin(0.10)}
    assert track._descriptor_track(crops, _CAST_PIN) == (1, True)
    monkeypatch.setattr(track, "AMBIG_MARGIN", 0.9)
    assert track._descriptor_track(crops, _CAST_PIN) == (1, False)


def test_descriptor_track_below_the_margin_is_confident():
    # BELOW the band: d1 = 0.15, d2 = 0.20 → ratio 0.75, clear of the 0.8 margin
    # (0.15 < 0.16), so track 1 IS meaningfully closer and no human is needed. This
    # is the margin's other side, and the side no test had: the band is a range, and
    # a fixture that only ever proves "a tie is ambiguous" cannot notice a margin
    # LOWERED far enough to call every clean match a coin flip — stopping delivery
    # to ask about a person the histogram already separated perfectly well.
    crops = {1: _twin(0.075), 2: _twin(0.10)}
    assert track._descriptor_track(crops, _CAST_PIN) == (1, False)


def test_descriptor_track_single_track_is_never_ambiguous():
    crops = {7: [1.0, 0.0] + [0.0] * 22}
    hero_id, ambiguous = track._descriptor_track(crops, tuple([1.0, 0.0] + [0.0] * 22))
    assert hero_id == 7 and ambiguous is False


def test_descriptor_track_no_crops_is_unmatched():
    assert track._descriptor_track({}, _desc(1.0, 0.0, 0.0)) == (None, False)


def test_descriptor_track_exact_tie_is_the_most_ambiguous_case():
    # Two tracks whose descriptors are bit-identical to the pinned cast member's --
    # and therefore to each other. A PERFECT double-match reads at a glance like
    # maximum confidence; it is the exact opposite. d1 == d2 == 0.0 means a colour
    # histogram cannot tell these two people apart at all, which is the most
    # extreme instance of §6.1a mode 1 (two people in similar clothing) -- the very
    # failure the ambiguous flag exists to catch. Picking one silently would be a
    # coin flip dressed up as a decision; only a human can break this tie.
    pin = _desc(0.5, 0.3, 0.2)
    crops = {1: list(pin), 2: list(pin)}
    hero_id, ambiguous = track._descriptor_track(crops, pin)
    assert hero_id in (1, 2) and ambiguous is True


# --- _track_crops: the highest-confidence-crop accumulator ------------------
# _FakeRes above is deliberately pixel-less (crop_and_mask → (None, None)), which
# is right for the build_route tests but means it can never exercise the store.
# These need real pixels, so they bring their own minimal fixture: a flat colour
# is enough -- _track_crops's contract is WHICH crop is kept, not what the
# histogram of it contains (that is test_appearance.py's job).

_RED, _GREEN = (0, 0, 255), (0, 255, 0)     # BGR — orig_img is BGR, like ultralytics


class _PixelRes:
    """An ultralytics-result-shaped fake WITH pixels: a frame of one flat colour."""
    def __init__(self, colour_bgr=_RED, size=(40, 40)):
        h, w = size
        self.orig_img = np.full((h, w, 3), colour_bgr, dtype=np.uint8)
        self.masks = None                   # no seg mask → build_descriptor uses every pixel


class _ConfBox(_FakeBox):
    """A _FakeBox that also carries ultralytics' .conf — the field _track_crops
    reads to decide whether a resighting beats the crop already stored."""
    def __init__(self, xywh, tid, conf):
        super().__init__(xywh, tid)
        self.conf = [conf]


def _box(tid, conf=None):
    """A 20x20 box centred in the _PixelRes frame."""
    xywh = [20.0, 20.0, 20.0, 20.0]
    return _ConfBox(xywh, tid, conf) if conf is not None else _FakeBox(xywh, tid)


def _flat_desc(r_bin, g_bin, b_bin):
    """The descriptor a flat-colour crop must produce: each channel's whole mass
    lands in exactly one of its HIST_BINS bins, and the three channels are
    normalized over the GRAND total — so each spike is 1/3, not 1.0. Spelled out
    from the histogram's semantics rather than by calling build_descriptor, so the
    assert cannot pass by echoing the code under test back at itself."""
    d = [0.0] * (3 * HIST_BINS)
    d[r_bin] = d[HIST_BINS + g_bin] = d[2 * HIST_BINS + b_bin] = 1 / 3
    return d


_RED_DESC = _flat_desc(7, 0, 0)             # BGR (0,0,255) → RGB (255,0,0): R maxed, G/B zero
_GREEN_DESC = _flat_desc(0, 7, 0)           # BGR (0,255,0) → RGB (0,255,0): G maxed, R/B zero


def test_track_crops_first_sighting_stores_the_descriptor():
    crops = {}
    track._track_crops(_PixelRes(_RED), [_box(1, conf=0.7)], crops)
    assert crops == {1: (0.7, pytest.approx(_RED_DESC))}


def test_track_crops_lower_confidence_resighting_does_not_overwrite():
    crops = {}
    track._track_crops(_PixelRes(_RED), [_box(1, conf=0.9)], crops)
    track._track_crops(_PixelRes(_GREEN), [_box(1, conf=0.4)], crops)
    # the GREEN pixels of the worse sighting must not have displaced the RED ones
    assert crops == {1: (0.9, pytest.approx(_RED_DESC))}


def test_track_crops_higher_confidence_resighting_replaces_the_crop():
    # The accumulator's whole reason for existing: a later, more confident sighting
    # of the same tid REPLACES the stored crop. Nothing else in this slice covers
    # this branch -- a fixture with a constant conf only ever exercises "first
    # sighting" (stores) and "exact tie" (skips), never the replace.
    crops = {}
    track._track_crops(_PixelRes(_RED), [_box(1, conf=0.4)], crops)
    track._track_crops(_PixelRes(_GREEN), [_box(1, conf=0.9)], crops)
    assert crops == {1: (0.9, pytest.approx(_GREEN_DESC))}


def test_track_crops_equal_confidence_resighting_keeps_the_first():
    # `conf <= stored` is a <=, not a <: an exact tie keeps the incumbent rather
    # than re-running crop_and_mask on every frame of a steady-confidence track.
    crops = {}
    track._track_crops(_PixelRes(_RED), [_box(1, conf=0.9)], crops)
    track._track_crops(_PixelRes(_GREEN), [_box(1, conf=0.9)], crops)
    assert crops == {1: (0.9, pytest.approx(_RED_DESC))}


def test_track_crops_box_without_conf_defaults_to_full_confidence():
    # ultralytics always sets .conf; the getattr default is for the fakes and for
    # a box shape that predates it. The default must be 1.0 (certain), not 0.0 --
    # a later 0.99 sighting losing to it is what proves the value is really 1.0.
    crops = {}
    track._track_crops(_PixelRes(_RED), [_box(1)], crops)          # no .conf at all
    assert crops == {1: (1.0, pytest.approx(_RED_DESC))}
    track._track_crops(_PixelRes(_GREEN), [_box(1, conf=0.99)], crops)
    assert crops == {1: (1.0, pytest.approx(_RED_DESC))}


def test_track_crops_without_pixels_stores_nothing_and_leaves_the_dict_clean():
    # crop_and_mask returns (None, None) for a result with no orig_img (every
    # build_route test drives exactly this). Storing a None crop would poison the
    # dict -- _descriptor_track would hand it to descriptor_dist and crash on len().
    crops = {}
    track._track_crops(_FakeRes([]), [_box(1, conf=0.9)], crops)
    assert crops == {}


def test_track_crops_skips_unconfirmed_detections():
    # id=None is a normal ByteTrack state (first frames / after occlusion). There
    # is no tid to file the crop under, so it must be skipped outright -- int(None[0])
    # would raise, and any fabricated shared id would blend two strangers' pixels
    # into one descriptor.
    unconfirmed = _ConfBox([20.0, 20.0, 20.0, 20.0], 1, 0.9)
    unconfirmed.id = None
    crops = {}
    track._track_crops(_PixelRes(_RED), [unconfirmed], crops)
    assert crops == {}


# --- the CLI: four pin spellings, exactly one at a time ---------------------


def test_cli_rejects_two_pin_flags(monkeypatch):
    # The four pin flags are four SPELLINGS of one pin, and main()'s raw-value
    # chain resolves them by PRECEDENCE -- so ungrouped, `--rule largest
    # --track-id 3` silently honours the rule and discards the id. A human asking
    # for one pin and quietly getting a different one is the exact silent
    # substitution this slice deletes from the manifest path; the CLI must not
    # reintroduce it at the front door.
    monkeypatch.setattr("sys.argv", ["track", "s.mp4", "route.json",
                                     "--rule", "largest", "--track-id", "3"])
    with pytest.raises(SystemExit):     # argparse group conflict → error() → SystemExit(2)
        track.main()


def test_cli_empty_seed_is_a_malformed_pin_not_no_pin(monkeypatch, tmp_path):
    """`--seed ''` is a pin that was GIVEN, so it must be honoured or refused — never
    read as "no pin at all".

    An unset variable in a wrapper script (`--seed "$SEED"`) is the way this arrives,
    and '' is falsy: the raw-value chain tested it for truth, fell through every rung
    to raw=None, and resolve(None) returned "no pin" — silently downgrading a pinned
    run to a scored one. That is this slice's own thesis one level down, and
    --cast-name '' already refuses it. --track-id 0 shows the same trap is why every
    OTHER rung tests `is not None`: 0 is falsy but a real track id.
    """
    monkeypatch.setattr(track, "build_route",
                        lambda spec, out: pytest.fail(f"empty --seed built a pin: {spec.pin!r}"))
    monkeypatch.setattr("sys.argv", ["track", "s.mp4", str(tmp_path / "route.json"),
                                     "--seed", ""])
    with pytest.raises(ValueError, match="--seed"):
        track.main()


def test_cli_malformed_seed_names_the_flag_not_floats_internals(monkeypatch, tmp_path):
    # the remedy must be one a stranger can act on: float()'s bare "could not convert
    # string to float: 'x'" names neither the flag they typed nor the shape it wants
    monkeypatch.setattr(track, "build_route", lambda spec, out: None)
    monkeypatch.setattr("sys.argv", ["track", "s.mp4", str(tmp_path / "route.json"),
                                     "--seed", "900,540,x,480"])
    with pytest.raises(ValueError) as e:
        track.main()
    assert "--seed" in str(e.value) and "x,y,w,h" in str(e.value)


def test_cli_seed_pin_still_builds_the_pin(monkeypatch, tmp_path):
    # the rejections above must not have cost the working path: a real --seed still
    # parses into the bbox pin resolve() turns into a HeroPin
    seen = {}
    monkeypatch.setattr(track, "build_route", lambda spec, out: seen.update(pin=spec.pin))
    monkeypatch.setattr("sys.argv", ["track", "s.mp4", str(tmp_path / "route.json"),
                                     "--seed", "900,540,220,480"])
    track.main()
    assert seen["pin"] == models.HeroPin(kind="bbox", bbox=(900.0, 540.0, 220.0, 480.0))


def test_cli_single_pin_flag_still_builds_the_pin(monkeypatch, tmp_path):
    # The rejection test above exits inside argparse and never reaches main()'s
    # body, so on its own it cannot prove the group left the normal path intact --
    # a stray required=True, or a broken raw-value chain, would still pass it.
    # This drives main() all the way to the TrackSpec it hands build_route.
    seen = {}
    monkeypatch.setattr(track, "build_route",
                        lambda spec, out: seen.update(pin=spec.pin, out=out))
    monkeypatch.setattr("sys.argv", ["track", "s.mp4", str(tmp_path / "route.json"),
                                     "--rule", "largest"])
    track.main()
    assert seen["pin"] == models.HeroPin(kind="rule", rule="largest")
    assert seen["out"] == str(tmp_path / "route.json")
