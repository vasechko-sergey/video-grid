import pytest
from scripts import build_reel
from scripts.lib.assembly import StreamInfo
from scripts.lib.models import (ReelEpisode, ReelManifest, ReelReport, ReelFailure,
                                CheckResult, MusicSpec)


def _rm(cap=3, n=2, platform=""):
    eps = [ReelEpisode(manifest={"segment": f"s{i}.mp4"}, clip=f"c{i}.mp4", route=f"r{i}.json")
           for i in range(n)]
    return ReelManifest(episodes=eps, target_dur=6.0, color_delta_max=12.0, cap=cap,
                        platform=platform)


def _pass():
    return ReelReport(checks={"length": CheckResult("length", True, {})}, episode_count=2)


def _color_fail(idx, target, culprit):
    return ReelReport(
        checks={"color_across_cuts": CheckResult("color_across_cuts", False, {})},
        fail_reasons=[ReelFailure("color_across_cuts", "reprocess", idx,
                                  {"target": target, "culprit_mean": culprit})],
        episode_count=2)


def _length_fail(dur, target):
    return ReelReport(
        checks={"length": CheckResult("length", False, {"dur": dur, "target": target})},
        fail_reasons=[ReelFailure("length", "pacing", None, {"dur": dur, "target": target})],
        episode_count=2)


def _wire(monkeypatch, reports, pe_results=None):
    """Feed check_reel.run a queue of canned reports; record deliver + the
    color_correct passed to each process_episode reprocess."""
    seen = {"deliver": [], "reprocess": [], "titles": [], "geometry": None, "platform": "",
            "targets": [], "deliver_platform": ""}
    rq = list(reports)
    monkeypatch.setattr(build_reel.assembly, "probe_stream",
                        lambda p: StreamInfo(1080, 1920, 30.0, "yuv420p", "h264"))
    monkeypatch.setattr(build_reel.assembly, "assemble", lambda clips, dims, fps, out: out)
    # music=/audio= tolerated (and ignored): build_reel now always passes them (None for
    # these silent-reel tests, matching check_reel.run's real defaults) — not the subject
    # of this fixture, which only exercises the reprocess/deliver escalation ladder. titles=
    # IS captured into seen["titles"] so a test can assert build_reel forwards it to deliver.
    # geometry=/platform= ARE captured into seen so a test can assert build_reel builds and
    # forwards them to check_reel.run.
    def fake_run(m, e, s, o, music=None, audio=None, geometry=None, platform=""):
        seen["geometry"] = geometry
        seen["platform"] = platform
        seen["targets"].append(s.target_dur)     # a length re-time replaces it between rounds
        return rq.pop(0)
    monkeypatch.setattr(build_reel.check_reel, "run", fake_run)

    def fake_deliver(m, prof, od, cl, rep, audio=None, titles=None, platform="", run_provenance=None):
        # run_provenance= tolerated (and ignored): build_reel now always passes it (Task 4)
        # — not the subject of this fixture; see
        # test_build_reel_threads_the_manifest_provenance_into_deliver for the dedicated check.
        seen["deliver"].append(od)
        seen["titles"].append(titles)
        seen["deliver_platform"] = platform
        return f"{od}/REEL_v1.mp4"
    monkeypatch.setattr(build_reel.deliver, "deliver", fake_deliver)
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


def test_build_reel_forwards_titles_to_deliver(monkeypatch, tmp_path):
    seen = _wire(monkeypatch, [_pass()])
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"),
                                titles="TITLES.json")
    assert res["status"] == "delivered"
    assert seen["titles"] == ["TITLES.json"]        # titles= threaded build_reel -> deliver


def test_color_fail_then_pass_reprocesses_then_delivers(monkeypatch, tmp_path):
    # round 0: ep1 warm → reprocess with med/d_i; round 1: passes → deliver
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]), _pass()]
    seen = _wire(monkeypatch, reports)
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert len(seen["reprocess"]) == 1
    assert seen["reprocess"][0]["correct"][0] == pytest.approx(120.0 / 150.0)
    assert seen["reprocess"][0]["route"] == "r1.json"     # frozen route reused


def test_a_delivered_reel_reports_which_episodes_were_reprocessed(monkeypatch, tmp_path):
    """build_reel's loop-2 re-renders culprits AFTER the QC gate ran, so which ones
    it touched has to leave the loop (design §8) — a verdict on ep1 is one render out
    of date the moment ep1 is rebuilt."""
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]), _pass()]
    _wire(monkeypatch, reports)
    result = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert result["status"] == "delivered"
    assert result["reprocessed"] == [1]


def test_reprocessed_accumulates_across_rounds_for_different_episodes(monkeypatch, tmp_path):
    # design §8: the attestation's claim is about the WHOLE run, not the last round —
    # ep0 reprocessed in round 0 and ep2 reprocessed in round 1 (a DIFFERENT episode)
    # must BOTH survive into the final sorted list, not just the most recent culprit.
    round0 = ReelReport(
        checks={"color_across_cuts": CheckResult("color_across_cuts", False, {})},
        fail_reasons=[ReelFailure("color_across_cuts", "reprocess", 0,
                                  {"target": [120.0, 120.0, 120.0], "culprit_mean": [150.0, 120.0, 120.0]})],
        episode_count=3)
    round1 = ReelReport(
        checks={"color_across_cuts": CheckResult("color_across_cuts", False, {})},
        fail_reasons=[ReelFailure("color_across_cuts", "reprocess", 2,
                                  {"target": [120.0, 120.0, 120.0], "culprit_mean": [150.0, 120.0, 120.0]})],
        episode_count=3)
    round2 = ReelReport(checks={"length": CheckResult("length", True, {})}, episode_count=3)
    seen = _wire(monkeypatch, [round0, round1, round2])
    result = build_reel.build_reel(_rm(n=3), str(tmp_path / "out"), str(tmp_path / "w"))
    assert result["status"] == "delivered"
    assert result["reprocessed"] == [0, 2]
    assert len(seen["reprocess"]) == 2       # one reprocess call per round, different episodes


def test_stabilized_episode_reprocess_withholds_the_route_and_still_delivers(monkeypatch, tmp_path):
    # Twin of test_color_fail_then_pass_reprocesses_then_delivers, but ep1 stabilizes.
    # process_episode refuses stabilize + a supplied route (design 2026-07-20 §1), so
    # build_reel must withhold the frozen route AT THE REPROCESS CALL — else the reel
    # dead-ends as reprocess-failed the moment a stabilized episode is reprocessed. The
    # sibling above pins the non-stabilized branch (route == "r1.json"); together they
    # fix the branch both ways.
    eps = [ReelEpisode(manifest={"segment": "s0.mp4"}, clip="c0.mp4", route="r0.json"),
           ReelEpisode(manifest={"segment": "s1.mp4", "stabilize": True},
                       clip="c1.mp4", route="r1.json")]
    rm = ReelManifest(episodes=eps, target_dur=6.0, color_delta_max=12.0, cap=3)
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]), _pass()]
    seen = _wire(monkeypatch, reports)
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"                   # reprocess did NOT dead-end
    assert len(seen["reprocess"]) == 1
    assert seen["reprocess"][0]["route"] is None          # route WITHHELD — the episode stabilizes
    assert rm.episodes[1].route == "r1.json"              # model field untouched — check_reel reads it


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


def test_build_reel_passes_platform_and_omits_geometry_without_sidecars(monkeypatch, tmp_path):
    seen = _wire(monkeypatch, [_pass()])
    build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert seen["geometry"] is None          # _rm episodes carry no path/meta → no geometry
    assert seen["platform"] == ""            # _rm sets no platform → generic


def test_build_reel_builds_geometry_and_platform_when_sidecars_present(monkeypatch, tmp_path):
    seen = _wire(monkeypatch, [_pass()])
    eps = [ReelEpisode(manifest={"segment": "s.mp4"}, clip="c0.mp4", route="r0.json",
                       path="p0.json", meta="pm0.json")]
    rm = ReelManifest(episodes=eps, target_dur=6.0, platform="tiktok")
    build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))
    assert seen["geometry"] == [("r0.json", "p0.json", "pm0.json")]
    assert seen["platform"] == "tiktok"


def test_build_reel_forwards_platform_to_deliver(monkeypatch, tmp_path):
    seen = _wire(monkeypatch, [_pass()])
    res = build_reel.build_reel(_rm(platform="reel"), str(tmp_path / "out"),
                                str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert seen["deliver_platform"] == "reel"       # rm.platform → deliver(platform=)


def test_within_band_shortfall_retimes_the_target_and_delivers(monkeypatch, tmp_path):
    # round 1 sees a 0.7s shortfall → adopt 5.3 as the target and re-check; round 2 is clean
    seen = _wire(monkeypatch, [_length_fail(5.3, 6.0), _pass()])
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"                  # absorbed, not escalated
    assert seen["targets"] == [6.0, 5.3]                 # re-checked against the reel's real length
    assert seen["reprocess"] == []                       # nothing was re-rendered to fix a length


def test_shortfall_past_the_band_still_stops_and_reports(monkeypatch, tmp_path):
    seen = _wire(monkeypatch, [_length_fail(3.0, 6.0)])   # 3.0s short — a missing episode, not drift
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["check"] == "length" and res["finding"]["escalate_to"] == "pacing"
    assert seen["deliver"] == []


def test_retime_rides_along_with_a_colour_reprocess(monkeypatch, tmp_path):
    # The adopt block runs BEFORE the kind dispatch, so a re-time CARRIED BY a reprocess
    # round lands in that same round. Folding the adopt into the `kind == "retime"` branch
    # would still pass every other test in this file — and Task 1's pure next_action test,
    # which only inspects the returned action — while silently regressing this path: the
    # length failure would re-fire every round while the colour correction converged.
    both = ReelReport(
        checks={"length": CheckResult("length", False, {"dur": 5.3, "target": 6.0}),
                "color_across_cuts": CheckResult("color_across_cuts", False, {})},
        fail_reasons=[ReelFailure("length", "pacing", None, {"dur": 5.3, "target": 6.0}),
                      ReelFailure("color_across_cuts", "reprocess", 1,
                                  {"target": [120.0, 120.0, 120.0],
                                   "culprit_mean": [150.0, 120.0, 120.0]})],
        episode_count=2)
    seen = _wire(monkeypatch, [both, _pass()])
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert seen["targets"] == [6.0, 5.3]     # adopted on the REPROCESS round, not one round later
    assert len(seen["reprocess"]) == 1       # and the colour fix still ran


# --- music integration (Task 6) --------------------------------------------
# NOTE: _rm_music/_wire_music are deliberately NOT named _rm/_wire — this file
# already defines _rm(cap=3, n=2) and _wire(monkeypatch, reports, pe_results=None)
# for the pre-existing A.5 tests above; a same-named redefinition here would
# shadow those at module scope and break every test that calls them.

def _rm_music(music, ambient=True, sfx=False):
    ep0 = ReelEpisode(manifest={"segment": "s0.mp4", "target_dur": 3.0}, clip="c0.mp4", route="r0.json")
    ep1 = ReelEpisode(manifest={"segment": "s1.mp4", "target_dur": 3.0}, clip="c1.mp4", route="r1.json")
    return ReelManifest(episodes=[ep0, ep1], target_dur=6.0, variety_min=4,
                        music=music, ambient=ambient, sfx=sfx)


def _fake_music():
    return MusicSpec("t.wav", 0.0, 6.0, 120.0, (0.0, 0.5, 1.0), (0.3,), 2.0)


def _si():
    return StreamInfo(1080, 1920, 30.0, "yuv420p", "h264")   # StreamInfo(w, h, fps, pix_fmt, vcodec)


def _passing():
    return ReelReport(checks={"black": CheckResult("black", True, {})})   # no fail_reasons → deliver


def _loud_fail():
    r = ReelReport(checks={"loudness": CheckResult("loudness", False, {"measured": -9.0})})
    r.fail_reasons = [ReelFailure("loudness", "audio-mix", None, {"measured": -9.0})]
    return r


def _wire_music(monkeypatch, reports, mixed, delivered):
    monkeypatch.setattr(build_reel.assembly, "probe_stream", lambda p: _si())
    monkeypatch.setattr(build_reel.assembly, "assemble", lambda *a, **k: None)
    monkeypatch.setattr(build_reel.check_reel, "_probe_dur", lambda p: 6.0)
    monkeypatch.setattr(build_reel.check_reel, "run", lambda *a, **k: reports.pop(0))
    monkeypatch.setattr(build_reel.mix, "mix",
                        lambda mus, wd, dur, segments=None, ambient=True, sfx=False:
                        (mixed.append((wd, dur)), "stem.m4a")[1])
    monkeypatch.setattr(build_reel.deliver, "deliver",
                        lambda *a, audio=None, **k: (delivered.append(audio), "OUT.mp4")[1])
    # NOTE: reel_orchestration.next_action is REAL — proves loudness rides the true escalate path


def test_build_reel_mixes_once_then_delivers_with_stem(tmp_path, monkeypatch):
    mixed, delivered = [], []
    _wire_music(monkeypatch, [_passing(), _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    res = build_reel.build_reel(_rm_music(music=str(tmp_path / "MUSIC.json")),
                                str(tmp_path / "out"), str(tmp_path / "work"))
    assert res["status"] == "delivered"
    assert len(mixed) == 1 and mixed[0][1] == 6.0        # stem built exactly once, at the reel duration
    assert delivered == ["stem.m4a"]                     # deliver received the stem


def test_build_reel_loudness_fail_stops_and_never_delivers(tmp_path, monkeypatch):
    mixed, delivered = [], []
    _wire_music(monkeypatch, [_passing(), _loud_fail()], mixed, delivered)   # round1 passes→mix; round2 loudness fails
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    res = build_reel.build_reel(_rm_music(music=str(tmp_path / "MUSIC.json")),
                                str(tmp_path / "out"), str(tmp_path / "work"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "not-auto-fixable" and res["finding"]["check"] == "loudness"
    assert delivered == []                               # deliver NEVER called on a loudness fail


def test_build_reel_silent_path_unchanged_without_music(tmp_path, monkeypatch):
    mixed, delivered = [], []
    _wire_music(monkeypatch, [_passing()], mixed, delivered)
    res = build_reel.build_reel(_rm_music(music=None), str(tmp_path / "out"), str(tmp_path / "work"))
    assert res["status"] == "delivered"
    assert mixed == [] and delivered == [None]           # no music → no mix, deliver stays silent (A.5)


def _color_fail_music():
    # a fresh (no-arg) colour-fail report — NOT named _color_fail: the module already
    # defines _color_fail(idx, target, culprit) for the A.5 tests above; a same-named
    # redefinition would shadow it and break every caller.
    r = ReelReport(checks={"color_across_cuts": CheckResult("color_across_cuts", False, {})})
    r.fail_reasons = [ReelFailure("color_across_cuts", "reprocess", 0,
                                  {"target": [100.0, 100.0, 100.0], "culprit_mean": [120.0, 100.0, 100.0]})]
    return r


def test_build_reel_music_delivers_after_full_reprocess_budget(tmp_path, monkeypatch):
    # the mix `continue` needs +2 loop headroom, not +1 — a good, fully-mixed reel
    # that used its whole reprocess budget must deliver, not fall to reel-cap-exhausted
    ep = ReelEpisode(manifest={"segment": "s0.mp4", "target_dur": 6.0}, clip="c0.mp4", route="r0.json")
    rm = ReelManifest(episodes=[ep], target_dur=6.0, cap=3, music=str(tmp_path / "MUSIC.json"))
    mixed, delivered = [], []
    reports = [_color_fail_music(), _color_fail_music(), _color_fail_music(), _passing(), _passing()]
    monkeypatch.setattr(build_reel.assembly, "probe_stream", lambda p: _si())
    monkeypatch.setattr(build_reel.assembly, "assemble", lambda *a, **k: None)
    monkeypatch.setattr(build_reel.check_reel, "_probe_dur", lambda p: 6.0)
    monkeypatch.setattr(build_reel.check_reel, "run", lambda *a, **k: reports.pop(0))
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    monkeypatch.setattr(build_reel.mix, "mix",
                        lambda mus, wd, dur, segments=None, ambient=True, sfx=False:
                        (mixed.append(dur), "stem.m4a")[1])
    monkeypatch.setattr(build_reel.process_episode, "process_episode",
                        lambda *a, **k: {"status": "mechanical_pass", "clip": "c0.mp4"})
    monkeypatch.setattr(build_reel.deliver, "deliver",
                        lambda *a, audio=None, **k: (delivered.append(audio), "OUT.mp4")[1])
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "work"))
    assert res["status"] == "delivered"                 # NOT reel-cap-exhausted
    assert mixed == [6.0] and delivered == ["stem.m4a"]  # mixed once, delivered with the stem


def test_build_reel_passes_segments_when_ambient(tmp_path, monkeypatch):
    # ambient defaults True → build_reel hands mix the (segment, target_dur) list, EDL order
    mixed, delivered, got = [], [], {}
    _wire_music(monkeypatch, [_passing(), _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.mix, "mix",
                        lambda mus, wd, dur, segments=None, ambient=True, sfx=False:
                        (got.setdefault("segments", segments), "stem.m4a")[1])
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    build_reel.build_reel(_rm_music(music=str(tmp_path / "MUSIC.json")),
                          str(tmp_path / "out"), str(tmp_path / "work"))
    assert got["segments"] == [("s0.mp4", 3.0), ("s1.mp4", 3.0)]


def test_build_reel_ambient_false_passes_no_segments(tmp_path, monkeypatch):
    mixed, delivered, got = [], [], {}
    _wire_music(monkeypatch, [_passing(), _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.mix, "mix",
                        lambda mus, wd, dur, segments=None, ambient=True, sfx=False:
                        (got.setdefault("segments", segments), "stem.m4a")[1])
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    build_reel.build_reel(_rm_music(music=str(tmp_path / "MUSIC.json"), ambient=False),
                          str(tmp_path / "out"), str(tmp_path / "work"))
    assert got["segments"] is None            # ambient=False → pure-music stem


def test_build_reel_passes_sfx_flag_when_set(tmp_path, monkeypatch):
    # sfx=True → build_reel hands mix the flag AND the (segment, target_dur) list (durs drive placement)
    mixed, delivered, got = [], [], {}
    _wire_music(monkeypatch, [_passing(), _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.mix, "mix",
                        lambda mus, wd, dur, segments=None, ambient=True, sfx=False:
                        (got.update(segments=segments, sfx=sfx), "stem.m4a")[1])
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    build_reel.build_reel(_rm_music(music=str(tmp_path / "MUSIC.json"), sfx=True),
                          str(tmp_path / "out"), str(tmp_path / "work"))
    assert got["sfx"] is True
    assert got["segments"] == [("s0.mp4", 3.0), ("s1.mp4", 3.0)]


def test_build_reel_sfx_only_still_passes_segments(tmp_path, monkeypatch):
    # ambient OFF but sfx ON → segments still handed over (sfx needs the durations)
    mixed, delivered, got = [], [], {}
    _wire_music(monkeypatch, [_passing(), _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.mix, "mix",
                        lambda mus, wd, dur, segments=None, ambient=True, sfx=False:
                        (got.update(segments=segments, ambient=ambient, sfx=sfx), "stem.m4a")[1])
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    build_reel.build_reel(_rm_music(music=str(tmp_path / "MUSIC.json"), ambient=False, sfx=True),
                          str(tmp_path / "out"), str(tmp_path / "work"))
    assert got["ambient"] is False and got["sfx"] is True
    assert got["segments"] == [("s0.mp4", 3.0), ("s1.mp4", 3.0)]


def test_build_reel_refuses_a_target_longer_than_the_music_window(tmp_path, monkeypatch):
    # An unmixable manifest is a hard SETUP error, not an editorial finding to route. mix
    # refuses a stem longer than its fragment, and the length re-time only ever SHRINKS the
    # target — so if the target starts outside the window, nothing downstream can rescue it,
    # and absorbing a shortfall would only carry it further toward mix's raise. Fail in ms,
    # before any ffmpeg, with the re-pick remedy.
    mixed, delivered = [], []
    _wire_music(monkeypatch, [_passing(), _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    ep = ReelEpisode(manifest={"segment": "s0.mp4", "target_dur": 8.0}, clip="c0.mp4", route="r0.json")
    rm = ReelManifest(episodes=[ep], target_dur=8.0, music=str(tmp_path / "MUSIC.json"))
    with pytest.raises(ValueError, match="exceeds the analyzed music window"):
        build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "work"))
    assert mixed == [] and delivered == []      # refused before any work was spent


def test_build_reel_music_delivers_after_full_budget_plus_a_length_retime(tmp_path, monkeypatch):
    # the retime `continue` needs +3 loop headroom, not +2 — a reel that spends its WHOLE
    # reprocess budget, then takes a within-band re-time, and carries music must still
    # deliver rather than fall to reel-cap-exhausted after the stem was already built.
    # Sibling of test_build_reel_music_delivers_after_full_reprocess_budget, which pinned +2.
    ep = ReelEpisode(manifest={"segment": "s0.mp4", "target_dur": 6.0}, clip="c0.mp4", route="r0.json")
    rm = ReelManifest(episodes=[ep], target_dur=6.0, cap=3, music=str(tmp_path / "MUSIC.json"))
    mixed, delivered = [], []
    reports = [_color_fail_music(), _color_fail_music(), _color_fail_music(),
               _length_fail(5.3, 6.0), _passing(), _passing()]
    monkeypatch.setattr(build_reel.assembly, "probe_stream", lambda p: _si())
    monkeypatch.setattr(build_reel.assembly, "assemble", lambda *a, **k: None)
    monkeypatch.setattr(build_reel.check_reel, "_probe_dur", lambda p: 5.3)
    monkeypatch.setattr(build_reel.check_reel, "run", lambda *a, **k: reports.pop(0))
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    monkeypatch.setattr(build_reel.mix, "mix",
                        lambda mus, wd, dur, segments=None, ambient=True, sfx=False:
                        (mixed.append(dur), "stem.m4a")[1])
    monkeypatch.setattr(build_reel.process_episode, "process_episode",
                        lambda *a, **k: {"status": "mechanical_pass", "clip": "c0.mp4"})
    monkeypatch.setattr(build_reel.deliver, "deliver",
                        lambda *a, audio=None, **k: (delivered.append(audio), "OUT.mp4")[1])
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "work"))
    assert res["status"] == "delivered"                  # NOT reel-cap-exhausted
    assert mixed == [5.3] and delivered == ["stem.m4a"]  # stem built at the re-timed length


def test_build_reel_threads_the_manifest_provenance_into_deliver(tmp_path, monkeypatch):
    # Task 4: edl_to_reel assembles rm.provenance (the run's start-engine stamp, the EDL's
    # digest/state, the loosened-threshold diff); build_reel must carry it to deliver,
    # merging in episode_qc.reprocessed_after (Task 5, design §8) rather than replacing
    # it — deliver is what writes the REEL_v{n}.attest.json sidecar from it. No reprocess
    # happened here, so reprocessed_after is empty, but the key is always present: the
    # attestation must say "none were re-rendered", not stay silent on the question.
    seen = {}
    _wire(monkeypatch, [_pass()])
    monkeypatch.setattr(build_reel.deliver, "deliver",
                        lambda *a, **k: seen.update(k) or "out/REEL_v1.mp4")
    rm = _rm()
    rm.provenance = {"edl": {"state": "intact"}}
    build_reel.build_reel(rm, str(tmp_path / "o"), str(tmp_path / "w"))
    assert seen["run_provenance"] == {"edl": {"state": "intact"},
                                      "episode_qc": {"reprocessed_after": []}}
