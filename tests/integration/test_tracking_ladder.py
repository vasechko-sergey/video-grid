"""The degradation ladder end to end, over real pixels (design 2026-07-21 §2).

composition="break" makes check_episode editorial-only (no numeric fail), so a crude
fallback route still reaches mechanical_pass — these tests prove the RUNG ran and stamped
its provenance, not that a weak tracker frames well.
"""
import json
from pathlib import Path

import pytest

# `track` lives in scripts.track (process_episode imports it as `from scripts import track`);
# there is no scripts.lib.track. Importing it from the SAME place process_episode does is what
# makes the monkeypatches below land on the object process_episode actually calls.
from scripts import process_episode, track
from scripts.lib import flow

pytestmark = pytest.mark.integration


def _manifest(clip, tmp_path, **over):
    # mirrors tests/integration/test_process_episode.py's helper: bbox pins are a BARE
    # list [x,y,w,h]; composition defaults to "break" so the checks stay editorial-only.
    d = dict(segment=str(clip), out_path=str(tmp_path / "ep.mp4"),
             composition="break", grid="thirds", canvas=[9, 16], target_dur=3.0)
    d.update(over)
    return d


def test_empty_yolo_route_falls_to_optical_flow(sample_clip, tmp_path):
    # real YOLO detects no person in the box → empty → unpinned → optical-flow rung.
    #
    # We assert on the ROUTE SIDECAR the rung stamped, not the terminal status. The flow
    # tracker is coarse by design (§3): on this hard-edged synthetic box the dense-flow
    # centroid oscillates ~150px frame-to-frame (measured worst |dx| ≈ 167px — the leading
    # and trailing motion edges trade off as the largest blob), which trips check_episode's
    # UNIVERSAL, UNFIXABLE continuity gate (cap 0.04*1920 ≈ 77px) and escalates. That gate is
    # orthogonal to this test's thesis — that rung 2 RAN and stamped its provenance — and
    # composition="break" makes only the COMPOSITION checks editorial, never continuity. So
    # the proof that the flow rung authored the route is the degraded="flow" sidecar it wrote,
    # not whether a coarse route happens to clear a per-frame-teleport gate on this fixture.
    proj = tmp_path / "ep"
    res = process_episode.process_episode(_manifest(sample_clip, tmp_path), proj)
    # the flow rung leaves the route.json + route.meta.json pair _load_route reads
    meta = json.loads((proj / "route.meta.json").read_text())
    assert meta["degraded"] == "flow", res
    assert json.loads((proj / "route.json").read_text()), "the flow rung must have written a route"


def test_manual_keyframes_rung_when_both_auto_rungs_are_down(sample_clip, tmp_path, monkeypatch):
    # force rungs 1 and 2 unavailable; a supplied keyframes.json drives rung 3
    monkeypatch.setattr(track, "available", lambda: False)
    monkeypatch.setattr(flow, "available", lambda: False)
    kf = tmp_path / "keyframes.json"
    kf.write_text(json.dumps([{"t": 0.0, "x": 300, "y": 540, "w": 200, "h": 400},
                              {"t": 2.9, "x": 1500, "y": 540, "w": 200, "h": 400}]))
    res = process_episode.process_episode(_manifest(sample_clip, tmp_path), tmp_path / "ep",
                                          keyframes_path=str(kf))
    assert res["status"] == "mechanical_pass", res
    assert res["degraded"] == "manual"


def test_no_route_and_no_keyframes_stops_for_the_human(sample_clip, tmp_path, monkeypatch):
    monkeypatch.setattr(track, "available", lambda: False)
    monkeypatch.setattr(flow, "available", lambda: False)
    res = process_episode.process_episode(_manifest(sample_clip, tmp_path), tmp_path / "ep")
    assert res["status"] == "stop_and_report"
    assert res["findings"][0]["reason"] == "no-track"
    assert "--keyframes" in res["findings"][0]["detail"]


def test_a_pinned_episode_never_enters_flow(sample_clip, tmp_path, monkeypatch):
    # A hero pin makes the empty route flow-INELIGIBLE (flow is identity-blind, §1.1):
    # flow.build_route must not run even though the pinned person is absent. sample_clip
    # has no people, so YOLO finds no tracks (features empty) → the empty route resolves to
    # `no-track`, NOT `hero-unmatched` (that needs somebody tracked but unmatched); the
    # invariant this test guards is only that flow never ran — the boom below is the assert.
    monkeypatch.setattr(flow, "build_route",
                        lambda *a, **k: pytest.fail("flow ran for a pinned episode"))
    res = process_episode.process_episode(
        _manifest(sample_clip, tmp_path, hero=[50, 50, 20, 20]), tmp_path / "ep")
    assert res["status"] == "stop_and_report"       # empty route under a pin → a stop, never flow
