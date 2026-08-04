"""Cast → hero-pin, end to end over REAL pixels (design 2026-08-04 §10).

YOLO itself is faked — this repo fakes it everywhere, because the synthetic clips
are boxes, not people, and real YOLO returns an empty route on them (see
tests/integration/test_intake.py:5). OSNet (`reid.embed`) is faked too: torchreid
is an optional dep that is not installed on CI, and the genuine real-OSNet
separation is a LATER slice (Task 5). Everything BETWEEN detector and embedder is
real: the fake result carries a real BGR frame, so `appearance.crop_from_result`
(the BGR→RGB colour-order landmine, design §10) and `descriptor_dist` (cosine) run
on real arrays, and the fake embedder maps a crop's dominant channel to a distinct
512-d one-hot — so a red-clothed track and a blue-clothed track embed to
orthogonal vectors, exactly as a real re-ID model separates two people.

Two things a first-cut fixture (one flat colour per track, one constant
confidence) would leave UNexercised, both handled here instead:

- The crop fed to OSNet is the RAW bbox in RGB, UNMASKED (a silhouette is
  out-of-distribution — the histogram-era seg-mask plumbing is gone). This is
  where the RGB/BGR colour-order landmine is actually caught: if either side
  forgot the conversion, intake's crop and delivery's crop would differ.
- Confidence is not constant across frames. Every frame but the last hands each
  track the OTHER track's colour at LOW confidence — a swapped decoy — and only
  the FINAL, HIGHEST-confidence frame carries the correct colours.
  `_track_crops`'s accumulator must replace the low-confidence decoy with the
  high-confidence real sighting for the first test below to pick the right
  person; a constant-confidence fixture can only ever exercise "first sighting"
  and "exact tie", never "replace".
"""
import json

import numpy as np
import pytest

from scripts import intake, track
from scripts.lib import appearance, hero as hero_lib, models, reid
from scripts.lib.footage import Cast, CastMember

_FRAME_W, _FRAME_H = 640, 360
_RED, _BLUE = (0, 0, 220), (220, 0, 0)      # BGR — orig_img is BGR, like ultralytics
_RED_X, _BLUE_X = 160, 480
_LOW_CONF, _HIGH_CONF = 0.3, 0.95
_N_FRAMES = 10
_FINAL_FRAME = _N_FRAMES - 1


class _Box:
    def __init__(self, xywh, tid, conf):
        self.xywh = [xywh]; self.id = [tid]; self.cls = [0]; self.conf = [conf]


class _Res:
    """An ultralytics-result-shaped fake WITH pixels: two people, red-clothed at
    x=160 (track 1) and blue-clothed at x=480 (track 2) — on the FINAL frame only.
    Every earlier frame swaps the colours at low confidence (a decoy), so
    _track_crops's accumulator must prefer the later, more-confident, correctly
    coloured sighting; if it kept the decoy, the two tracks' identities would come
    out swapped and a cast pin would follow the wrong person."""
    def __init__(self, i: int):
        img = np.zeros((_FRAME_H, _FRAME_W, 3), dtype=np.uint8)
        self.boxes = []
        final = (i == _FINAL_FRAME)
        conf = _HIGH_CONF if final else _LOW_CONF
        colours = (_RED, _BLUE) if final else (_BLUE, _RED)      # swapped decoy pre-final
        for x, colour, tid in ((_RED_X, colours[0], 1), (_BLUE_X, colours[1], 2)):
            l, t, r, b = x - 40, 100, x + 40, 300
            img[t:b, l:r] = colour
            self.boxes.append(_Box([float(x), 200.0, 80.0, 200.0], tid, conf))
        self.orig_img = img
        self.masks = None


def _fake_iter(src, **k):
    return iter((i, _Res(i)) for i in range(_N_FRAMES))


def _embed(crops):
    """Fake OSNet: a crop's dominant RGB channel → a one-hot 512-d unit vector, so
    two differently-clothed people embed to ORTHOGONAL rows (cosine dist 1.0) and a
    match to self is 0.0. Crops arrive RGB (crop_from_result/crop_bbox already did
    BGR→RGB), so a colour-order slip upstream would flip the argmax and swap ids."""
    out = []
    for c in crops:
        idx = int(np.asarray(c).reshape(-1, 3).mean(axis=0).argmax())
        v = [0.0] * reid.EMBED_DIM
        v[idx] = 1.0
        out.append(v)
    return out


def _mock_reid(monkeypatch):
    monkeypatch.setattr(reid, "require", lambda: None)          # torchreid absent on CI
    monkeypatch.setattr(reid, "embed", _embed)


def _descriptor_of(colour_bgr):
    """The 512-d embedding _embed would produce for a crop of this BGR colour — the
    SAME mapping, so a cast member's stored descriptor equals its person's embedding."""
    return _embed([np.full((4, 4, 3), colour_bgr[::-1], dtype=np.uint8)])[0]


def _cast():
    return Cast(members=[CastMember(name="Red", descriptor=_descriptor_of(_RED)),
                         CastMember(name="Blue", descriptor=_descriptor_of(_BLUE)),
                         CastMember(name="Green", descriptor=_descriptor_of((0, 220, 0)))])


@pytest.mark.integration
def test_cast_pin_follows_the_named_person(monkeypatch, tmp_path):
    monkeypatch.setattr(track, "_iter_detections", _fake_iter)
    _mock_reid(monkeypatch)
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", fps=30,
                            pin=hero_lib.resolve("Blue", _cast()))
    route = track.build_route(spec, out=str(out))
    # the BLUE-clothed person, not the red one — the embedding beats kinematics (§6.1a)
    assert route and all(pt.x == _BLUE_X for pt in route)
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.pin_matched is True and meta.ambiguous is False


@pytest.mark.integration
def test_cast_pin_naming_an_absent_person_is_unmatched(monkeypatch, tmp_path):
    monkeypatch.setattr(track, "_iter_detections", _fake_iter)
    _mock_reid(monkeypatch)
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


class _ResC:
    """A person occupying the LEFT half of its bbox on a differently-coloured
    background filling the RIGHT half — so the raw (unmasked) bbox crop carries BOTH
    colours, and intake and delivery must crop the SAME region for their embeddings
    to agree."""
    def __init__(self):
        W, H = 200, 200
        img = np.zeros((H, W, 3), dtype=np.uint8)        # BGR, like ultralytics orig_img
        img[40:160, 40:100] = (0, 0, 220)                # red person (BGR), left of bbox
        img[40:160, 100:160] = (0, 220, 0)               # green background, right of bbox
        self.orig_img = img
        self.masks = None
        self.boxes = [_Box([100.0, 100.0, 120.0, 120.0], 1, 0.95)]   # bbox [40:160, 40:160]


@pytest.mark.integration
def test_intake_and_delivery_crop_the_same_raw_bbox(monkeypatch):
    # The symmetry that matters now the mask plumbing is gone: intake and delivery
    # feed OSNet the IDENTICAL raw bbox crop (RGB, unmasked), so any embedder returns
    # the same vector. A BGR/RGB slip on either side would make the crops differ.
    r = _ResC()
    box = r.boxes[0]
    delivery_crop = appearance.crop_from_result(r, box)          # what _track_crops feeds reid
    rgb = np.asarray(r.orig_img)[..., ::-1]                       # intake crops the ORIGINAL (RGB)
    monkeypatch.setattr(intake.assembly, "frames_rgb", lambda path, times, fps: [rgb for _ in times])
    captured = {}

    def spy_embed(crops):
        captured["crop"] = np.array(crops[0])
        return [[1.0] + [0.0] * (reid.EMBED_DIM - 1) for _ in crops]

    monkeypatch.setattr(intake.reid, "embed", spy_embed)
    best = {1: (0.95, 0.0, tuple(float(v) for v in box.xywh[0]))}   # 3-tuple, no mask
    cast = intake._cast_from_original("orig.mp4", best, res=(200, 200), pres=(200, 200), fps=30.0)
    # pixel-identical crops on both sides → identical embeddings
    assert np.array_equal(captured["crop"], delivery_crop)
    assert cast[0].descriptor == [1.0] + [0.0] * (reid.EMBED_DIM - 1)
