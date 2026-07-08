import json
from scripts import track
from scripts.lib import models

class _FakeBox:
    def __init__(self, xywh, tid):
        self.xywh = [xywh]; self.id = [tid]; self.cls = [0]  # cls 0 = person

def test_route_from_frames(monkeypatch, tmp_path):
    # fake per-frame detections: subject slides right
    frames = [[_FakeBox([300 + i * 50, 500, 140, 320], 1)] for i in range(10)]
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
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
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
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
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
    spec = models.TrackSpec(src="ignored.mp4", fps=30, intent="action")
    route = track.build_route(spec, out=str(tmp_path / "route.json"))
    xs = [pt.x for pt in route]
    assert xs[0] == 200 and xs[-1] == 200 + 11 * 120

def test_meta_flags_ambiguity(monkeypatch, tmp_path):
    # two indistinguishable static tracks → margin rule fires (spec §6.1a)
    frames = [[_FakeBox([500, 500, 140, 320], 1),
               _FakeBox([1400, 500, 140, 320], 2)] for _ in range(10)]
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
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
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="ignored.mp4", fps=30)
    route = track.build_route(spec, out=str(out))
    meta = models.TrackMeta.from_dict(json.loads((tmp_path / "route.meta.json").read_text()))
    assert meta.hero == 3
    assert "-1" not in meta.features
    assert [pt.x for pt in route] == [600 + i * 20 for i in range(20)]

def test_features_include_speed_and_border(monkeypatch, tmp_path):
    frames = [[_FakeBox([300 + i * 50, 500, 140, 320], 1)] for i in range(10)]
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
    spec = models.TrackSpec(src="ignored.mp4", fps=30)
    track.build_route(spec, out=str(tmp_path / "route.json"))
    meta = models.TrackMeta.from_dict(json.loads((tmp_path / "route.meta.json").read_text()))
    feats = meta.features["1"]
    assert abs(feats["speed"] - 50.0) < 1e-6      # 50 px/frame
    assert feats["border"] is None                # dims unknown in mocked run

def test_fps_probe_when_not_given(monkeypatch, tmp_path, sample_clip):
    # fps=None → probed from the real file (sample fixture is 30fps 1920x1080)
    frames = [[_FakeBox([300, 500, 140, 320], 1)] for _ in range(5)]
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
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
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))

    out = tmp_path / "route.json"
    spec = models.TrackSpec(src="seg.mp4", intent="static", fps=30.0)
    route = track.build_route(spec, out=str(out))
    assert route and isinstance(route[0], models.RoutePoint)
    meta = models.TrackMeta.from_dict(json.loads(out.with_suffix(".meta.json").read_text()))
    assert meta.hero == 1                      # static intent → the still, large subject
