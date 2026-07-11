import pytest
from scripts import build_reel
from scripts.lib.assembly import StreamInfo
from scripts.lib.models import (ReelEpisode, ReelManifest, ReelReport, ReelFailure,
                                CheckResult)


def _rm(cap=3, n=2):
    eps = [ReelEpisode(manifest={"segment": f"s{i}.mp4"}, clip=f"c{i}.mp4", route=f"r{i}.json")
           for i in range(n)]
    return ReelManifest(episodes=eps, target_dur=6.0, color_delta_max=12.0, cap=cap)


def _pass():
    return ReelReport(checks={"length": CheckResult("length", True, {})}, episode_count=2)


def _color_fail(idx, target, culprit):
    return ReelReport(
        checks={"color_across_cuts": CheckResult("color_across_cuts", False, {})},
        fail_reasons=[ReelFailure("color_across_cuts", "reprocess", idx,
                                  {"target": target, "culprit_mean": culprit})],
        episode_count=2)


def _wire(monkeypatch, reports, pe_results=None):
    """Feed check_reel.run a queue of canned reports; record deliver + the
    color_correct passed to each process_episode reprocess."""
    seen = {"deliver": [], "reprocess": []}
    rq = list(reports)
    monkeypatch.setattr(build_reel.assembly, "probe_stream",
                        lambda p: StreamInfo(1080, 1920, 30.0, "yuv420p", "h264"))
    monkeypatch.setattr(build_reel.assembly, "assemble", lambda clips, dims, fps, out: out)
    monkeypatch.setattr(build_reel.check_reel, "run", lambda m, e, s, o: rq.pop(0))
    monkeypatch.setattr(build_reel.deliver, "deliver",
                        lambda m, prof, od, cl, rep: seen["deliver"].append(od) or f"{od}/REEL_v1.mp4")
    results = iter(pe_results or [])

    def fake_pe(manifest, project_dir, route_path=None, color_correct=None):
        seen["reprocess"].append({"correct": color_correct, "route": route_path})
        return next(results, {"status": "mechanical_pass", "clip": project_dir + "/ep.mp4"})
    monkeypatch.setattr(build_reel.process_episode, "process_episode", fake_pe)
    return seen


def test_clean_reel_delivers_without_reprocess(monkeypatch, tmp_path):
    seen = _wire(monkeypatch, [_pass()])
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert res["output"].endswith("REEL_v1.mp4")
    assert seen["reprocess"] == []          # no fix needed


def test_color_fail_then_pass_reprocesses_then_delivers(monkeypatch, tmp_path):
    # round 0: ep1 warm → reprocess with med/d_i; round 1: passes → deliver
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]), _pass()]
    seen = _wire(monkeypatch, reports)
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert len(seen["reprocess"]) == 1
    assert seen["reprocess"][0]["correct"][0] == pytest.approx(120.0 / 150.0)
    assert seen["reprocess"][0]["route"] == "r1.json"     # frozen route reused


def test_color_correct_compounds_across_rounds(monkeypatch, tmp_path):
    # two failing rounds then pass: the 2nd reprocess factor is compounded onto
    # the 1st and clamped — the reversion bug (per-round-relative) would NOT compound
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]),   # ratio1 = .8
               _color_fail(1, [120.0, 120.0, 120.0], [130.0, 120.0, 120.0]),   # ratio2 = .923
               _pass()]
    seen = _wire(monkeypatch, reports)
    build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    r0 = seen["reprocess"][0]["correct"][0]
    r1 = seen["reprocess"][1]["correct"][0]
    assert r0 == pytest.approx(0.8)
    assert r1 == pytest.approx(0.8 * (120.0 / 130.0))     # compounded, not 120/130 alone


def test_variety_fail_stops_and_reports_without_delivering(monkeypatch, tmp_path):
    rep = ReelReport(checks={"variety": CheckResult("variety", False, {})},
                     fail_reasons=[ReelFailure("variety", "edit-plan", 1, {"distance": 1})],
                     episode_count=2)
    seen = _wire(monkeypatch, [rep])
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["escalate_to"] == "edit-plan"
    assert seen["deliver"] == []            # a failed reel is never delivered


def test_reprocess_failure_propagates(monkeypatch, tmp_path):
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0])]
    seen = _wire(monkeypatch, reports,
                 pe_results=[{"status": "needs_input", "problems": ["bad manifest"]}])
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "reprocess-failed" and res["finding"]["episode_idx"] == 1


def test_capped_episode_escalates(monkeypatch, tmp_path):
    # cap=1: round 0 reprocesses ep1 (attempts→1); round 1 still fails → capped escalate
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]),
               _color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0])]
    seen = _wire(monkeypatch, reports)
    res = build_reel.build_reel(_rm(cap=1), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "reprocess-capped"
    assert seen["deliver"] == []


def test_black_reprocess_reuses_the_standing_colour_correction(monkeypatch, tmp_path):
    # round 0 colour fail on ep1 sets cc[1]≈0.8 on red; round 1 BLACK fail on ep1 must
    # reprocess with the SAME standing cc (ratio itself None, but cc reused, NOT reverted
    # to None); round 2 passes → deliver. Inverse bug: if black reset cc→None, correct[1]
    # would be None and this asserts fail.
    def _black_fail(idx):
        return ReelReport(checks={"black": CheckResult("black", False, {})},
                          fail_reasons=[ReelFailure("black", "reprocess", idx, {"t": 1.0})],
                          episode_count=2)
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]),
               _black_fail(1), _pass()]
    seen = _wire(monkeypatch, reports)
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert seen["reprocess"][0]["correct"][0] == pytest.approx(0.8)   # round 0 colour set it
    assert seen["reprocess"][1]["correct"][0] == pytest.approx(0.8)   # round 1 black reused it, unchanged


def test_multi_culprit_round_second_failure_propagates_without_delivering(monkeypatch, tmp_path):
    # one round names TWO culprits (ep0 black, ep2 colour); ep0 reprocess succeeds, ep2's
    # fails → stop_and_report names ep2, deliver never called, both items were attempted.
    rep = ReelReport(
        checks={"black": CheckResult("black", False, {}),
                "color_across_cuts": CheckResult("color_across_cuts", False, {})},
        fail_reasons=[ReelFailure("black", "reprocess", 0, {"t": 1.0}),
                      ReelFailure("color_across_cuts", "reprocess", 2,
                                  {"target": [120.0, 120.0, 120.0], "culprit_mean": [150.0, 120.0, 120.0]})],
        episode_count=3)
    seen = _wire(monkeypatch, [rep],
                 pe_results=[{"status": "mechanical_pass", "clip": "ep0.mp4"},
                             {"status": "needs_input", "problems": ["bad"]}])
    res = build_reel.build_reel(_rm(n=3), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "reprocess-failed" and res["finding"]["episode_idx"] == 2
    assert seen["deliver"] == []
    assert len(seen["reprocess"]) == 2      # both attempted; the second's failure returned
