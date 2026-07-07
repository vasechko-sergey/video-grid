import json
from scripts import track

class _FakeBox:
    def __init__(self, xywh, tid):
        self.xywh = [xywh]; self.id = [tid]; self.cls = [0]  # cls 0 = person

def test_route_from_frames(monkeypatch, tmp_path):
    # fake per-frame detections: subject slides right
    frames = [[_FakeBox([300 + i * 50, 500, 140, 320], 1)] for i in range(10)]
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
    out = tmp_path / "route.json"
    route = track.build_route(src="ignored.mp4", fps=30, out=str(out))
    assert len(route) == 10
    assert route[0]["x"] == 300 and route[-1]["x"] == 300 + 9 * 50
    assert json.loads(out.read_text())[0]["x"] == 300

def test_route_seed_pin(monkeypatch, tmp_path):
    # two persistent tracks; the seed bbox must pin the RIGHT one as hero
    frames = [[_FakeBox([300, 500, 140, 320], 1),
               _FakeBox([1500, 500, 120, 300], 2)] for _ in range(10)]
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
    out = tmp_path / "route.json"
    route = track.build_route(src="ignored.mp4", fps=30, out=str(out),
                              seed_bbox=(1500, 500, 120, 300))
    assert all(pt["x"] == 1500 for pt in route)

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
    route = track.build_route(src="ignored.mp4", fps=30,
                              out=str(tmp_path / "route.json"))
    xs = [pt["x"] for pt in route]
    assert xs[0] == 200 and xs[-1] == 200 + 11 * 120

def test_meta_flags_ambiguity(monkeypatch, tmp_path):
    # two indistinguishable static tracks → margin rule fires (spec §6.1a)
    frames = [[_FakeBox([500, 500, 140, 320], 1),
               _FakeBox([1400, 500, 140, 320], 2)] for _ in range(10)]
    monkeypatch.setattr(track, "_iter_detections",
                        lambda src, **k: iter(enumerate(frames)))
    out = tmp_path / "route.json"
    track.build_route(src="ignored.mp4", fps=30, out=str(out))
    meta = json.loads((tmp_path / "route.meta.json").read_text())
    assert meta["ambiguous"] is True
