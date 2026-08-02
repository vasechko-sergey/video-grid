"""Cast → hero-pin, end to end over REAL pixels (design §10).

YOLO itself is faked — this repo fakes it everywhere, because the synthetic clips
are boxes, not people, and real YOLO returns an empty route on them (see
tests/integration/test_intake.py:5). Everything BELOW the detector is real: the
fake result carries a real BGR frame and a real model-space mask, so
appearance.crop_and_mask (BGR→RGB + mask resize), build_descriptor and
descriptor_dist run on real arrays. This is the first test that takes a
descriptor from intake's own builder, through cast.json, to a route.

Two things a first-cut fixture (one flat colour per track, one constant
confidence, a mask built at frame size) would leave UNexercised, both handled
here instead:

- The seg mask is built at HALF the frame's resolution — a stand-in for YOLO's
  model-space output, which is never source-sized — so crop_and_mask's PIL
  resize back up to source dims does a REAL interpolation, not a no-op (a
  same-size "resize" is trivially safe regardless of whether the width/height
  args are even ordered correctly). Because each box's crop is one flat
  colour, the resize's exact edge behaviour can't change the resulting
  descriptor (any non-empty subset of a flat-colour crop yields the same
  histogram) — this proves the resize runs and produces a same-shaped,
  still-positive mask over the box, not that a transposed width/height would
  be caught by a wrong descriptor.
- Confidence is not constant across frames. Every frame but the last hands
  each track the OTHER track's colour at LOW confidence — a swapped decoy —
  and only the FINAL, HIGHEST-confidence frame carries the correct colours.
  _track_crops's accumulator must replace the low-confidence decoy with the
  high-confidence real sighting for the first test below to pick the right
  person; a constant-confidence fixture can only ever exercise "first
  sighting" and "exact tie", never "replace" (see test_track.py's
  test_track_crops_higher_confidence_resighting_replaces_the_crop, the
  isolated unit test for that same branch).
"""
import json

import numpy as np
import pytest

from scripts import intake, track
from scripts.lib import appearance, hero as hero_lib, models
from scripts.lib.footage import Cast, CastMember

_FRAME_W, _FRAME_H = 640, 360
_MODEL_W, _MODEL_H = 320, 180               # genuine model-space size (half source,
                                             # aspect-matched) — NOT source-sized, so the
                                             # PIL resize inside crop_and_mask does real work
_RED, _BLUE = (0, 0, 220), (220, 0, 0)      # BGR — orig_img is BGR, like ultralytics
_RED_X, _BLUE_X = 160, 480
_LOW_CONF, _HIGH_CONF = 0.3, 0.95
_N_FRAMES = 10
_FINAL_FRAME = _N_FRAMES - 1


class _Box:
    def __init__(self, xywh, tid, conf):
        self.xywh = [xywh]; self.id = [tid]; self.cls = [0]; self.conf = [conf]


class _Masks:
    def __init__(self, data):
        self.data = data


class _Res:
    """An ultralytics-result-shaped fake WITH pixels: two people, red-clothed at
    x=160 (track 1) and blue-clothed at x=480 (track 2) — on the FINAL frame
    only. Every earlier frame swaps the colours at low confidence (a decoy), so
    _track_crops's accumulator must correctly prefer the later, more-confident,
    correctly-coloured sighting over the earlier one; if it kept the wrong
    (decoy) sighting instead, the two tracks' identities would come out
    swapped and a cast pin would follow the wrong person.
    """
    def __init__(self, i: int):
        img = np.zeros((_FRAME_H, _FRAME_W, 3), dtype=np.uint8)
        masks = []
        self.boxes = []
        final = (i == _FINAL_FRAME)
        conf = _HIGH_CONF if final else _LOW_CONF
        colours = (_RED, _BLUE) if final else (_BLUE, _RED)      # swapped decoy pre-final
        for x, colour, tid in ((_RED_X, colours[0], 1), (_BLUE_X, colours[1], 2)):
            l, t, r, b = x - 40, 100, x + 40, 300
            img[t:b, l:r] = colour
            ml, mt, mr, mb = l // 2, t // 2, r // 2, b // 2      # same box, model-space scale
            m = np.zeros((_MODEL_H, _MODEL_W), dtype=np.float32)
            m[mt:mb, ml:mr] = 1.0
            masks.append(m)
            self.boxes.append(_Box([float(x), 200.0, 80.0, 200.0], tid, conf))
        self.orig_img = img
        self.masks = _Masks(masks)


def _fake_iter(src, **k):
    return iter((i, _Res(i)) for i in range(_N_FRAMES))


def _descriptor_of(colour_bgr):
    """Build a cast descriptor the way intake does — same builder, same masking."""
    crop = np.full((200, 80, 3), colour_bgr[::-1], dtype=np.uint8)     # RGB for the builder
    return intake.build_descriptor(crop, np.full((200, 80), 255, dtype=np.uint8))


def _cast():
    return Cast(members=[CastMember(name="Red", descriptor=_descriptor_of(_RED)),
                         CastMember(name="Blue", descriptor=_descriptor_of(_BLUE)),
                         CastMember(name="Green", descriptor=_descriptor_of((0, 220, 0)))])


@pytest.mark.integration
def test_cast_pin_follows_the_named_person(monkeypatch, tmp_path):
    monkeypatch.setattr(track, "_iter_detections", _fake_iter)
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", fps=30,
                            pin=hero_lib.resolve("Blue", _cast()))
    route = track.build_route(spec, out=str(out))
    # the BLUE-clothed person, not the red one — descriptor beats kinematics (§6.1a)
    assert route and all(pt.x == _BLUE_X for pt in route)
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.pin_matched is True and meta.ambiguous is False


@pytest.mark.integration
def test_cast_pin_naming_an_absent_person_is_unmatched(monkeypatch, tmp_path):
    monkeypatch.setattr(track, "_iter_detections", _fake_iter)
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", fps=30,
                            pin=hero_lib.resolve("Green", _cast()))   # nobody wears green
    route = track.build_route(spec, out=str(out))
    assert route == []
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.pin_matched is False and meta.hero is None


@pytest.mark.integration
def test_cast_descriptor_survives_the_cast_json_round_trip(tmp_path):
    # the descriptor intake writes is the descriptor track matches against
    path = tmp_path / "cast.json"
    path.write_text(json.dumps(_cast().to_dict()))
    pin = hero_lib.resolve("Blue", Cast.from_json(str(path)))
    assert appearance.descriptor_dist(list(pin.descriptor), _descriptor_of(_BLUE)) == 0.0


class _BoxC:
    def __init__(self, xywh, tid, conf):
        self.xywh = [xywh]; self.id = [tid]; self.cls = [0]; self.conf = [conf]


class _ResC:
    """A person occupying the LEFT half of its bbox on a differently-coloured
    background filling the RIGHT half, with a model-space mask over the person only
    — so masking is NOT a no-op (unlike _Res, whose bbox is one flat colour)."""
    def __init__(self):
        W, H = 200, 200
        img = np.zeros((H, W, 3), dtype=np.uint8)        # BGR, like ultralytics orig_img
        img[40:160, 40:100] = (0, 0, 220)                # red person (BGR), left of bbox
        img[40:160, 100:160] = (0, 220, 0)               # green background, right of bbox
        m = np.zeros((H // 2, W // 2), dtype=np.float32)  # model space (half source)
        m[20:80, 20:50] = 1.0                            # person half only
        self.orig_img = img
        self.masks = _Masks([m])
        self.boxes = [_BoxC([100.0, 100.0, 120.0, 120.0], 1, 0.95)]   # bbox [40:160, 40:160]


@pytest.mark.integration
def test_intake_and_delivery_cast_descriptors_agree_after_masking(monkeypatch):
    r = _ResC()
    box = r.boxes[0]
    # delivery: crop_and_mask (BGR→RGB + model-mask resize) → masked descriptor
    crop_rgb, mask = appearance.crop_and_mask(r, 0, box)
    delivery = appearance.build_descriptor(crop_rgb, mask)
    # intake: same person, crop from the ORIGINAL (here the same frame, RGB), proxy
    # mask via seg_mask, upsampled inside _cast_from_original
    rgb = np.asarray(r.orig_img)[..., ::-1]
    monkeypatch.setattr(intake.assembly, "frame_rgb", lambda path, t: rgb)
    best = {1: (0.95, 0.0, tuple(float(v) for v in box.xywh[0]), appearance.seg_mask(r, 0, box))}
    cast = intake._cast_from_original("orig.mp4", best, res=(200, 200), pres=(200, 200))
    intake_desc = cast[0].descriptor
    # symmetric: the two masked descriptors match well within the cast gate
    assert appearance.descriptor_dist(intake_desc, delivery) < appearance.CAST_MATCH
    # and the pre-fix maskless bbox descriptor is measurably FARTHER — the regression
    l, t, r_, b_ = 40, 40, 160, 160
    maskless = appearance.build_descriptor(rgb[t:b_, l:r_], None)
    assert (appearance.descriptor_dist(maskless, delivery)
            > appearance.descriptor_dist(intake_desc, delivery))
