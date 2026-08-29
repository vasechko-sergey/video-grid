import pytest
from scripts import build_reel
from scripts.lib.assembly import StreamInfo
from scripts.lib.look import LookSpec
from scripts.lib.models import (ReelEpisode, ReelManifest, ReelReport, ReelFailure,
                                CheckResult, MusicSpec)


def _rm(cap=3, n=2, platform="", look=None, outro=None):
    eps = [ReelEpisode(manifest={"segment": f"s{i}.mp4"}, clip=f"c{i}.mp4", route=f"r{i}.json")
           for i in range(n)]
    return ReelManifest(episodes=eps, target_dur=6.0, color_delta_max=12.0, cap=cap,
                        platform=platform, look=look, outro=outro)


def _pass():
    return ReelReport(checks={"length": CheckResult("length", True, {})}, episode_count=2)


def _color_fail(idx, target, culprit):
    # The colour corrector is retired (design 2026-08-29): every canned report this
    # factory used to build as a "color_across_cuts" fail is now a black hit instead —
    # the failure class that still reprocesses. target/culprit are accepted but no
    # longer used: every call site below still passes them (only the failure's SHAPE
    # changed), which is why they are unused rather than deleted from the signature.
    return ReelReport(
        checks={"black": CheckResult("black", False, {"black_start": [1.0]})},
        fail_reasons=[ReelFailure("black", "reprocess", idx, {"t": 1.0})],
        episode_count=2)


def _length_fail(dur, target):
    return ReelReport(
        checks={"length": CheckResult("length", False, {"dur": dur, "target": target})},
        fail_reasons=[ReelFailure("length", "pacing", None, {"dur": dur, "target": target})],
        episode_count=2)


def _wire(monkeypatch, reports, pe_results=None):
    """Feed check_reel.run a queue of canned reports; record deliver + the route
    passed to each process_episode reprocess. color_correct is captured too — the
    mock mirrors process_episode's real signature, which still accepts the keyword
    (design 2026-08-29 Task 1 only stops build_reel from SUPPLYING it) — but no
    caller in this file asserts on it any more, since build_reel never passes it."""
    seen = {"deliver": [], "reprocess": [], "titles": [], "geometry": None, "platform": "",
            "targets": [], "deliver_platform": "", "outro": None}
    rq = list(reports)
    monkeypatch.setattr(build_reel.assembly, "probe_stream",
                        lambda p: StreamInfo(1080, 1920, 30.0, "yuv420p", "h264"))
    monkeypatch.setattr(build_reel.assembly, "assemble", lambda clips, dims, fps, out: out)
    # music=/audio= tolerated (and ignored): build_reel now always passes them (None for
    # these silent-reel tests, matching check_reel.run's real defaults) — not the subject
    # of this fixture, which only exercises the reprocess/deliver escalation ladder. titles=
    # IS captured into seen["titles"] so a test can assert build_reel forwards it to deliver.
    # geometry=/platform=/outro= ARE captured into seen so a test can assert build_reel builds
    # and forwards them to check_reel.run. outro_fixed (build_reel.py's OWN escalation gate,
    # derived directly off rm.outro BEFORE check_reel.run is ever called, at line ~66) is a
    # SEPARATE computation from this kwarg — the two tests below exercise outro_fixed, not this
    # forward. Conflating the two left the outro= forward with no coverage at all: flipping
    # build_reel.py's `outro=rm.outro` to `outro=None` changed nothing either test could see.
    def fake_run(m, e, s, o, music=None, audio=None, geometry=None, platform="", outro=None):
        seen["geometry"] = geometry
        seen["platform"] = platform
        seen["outro"] = outro
        seen["targets"].append(s.target_dur)     # a length re-time replaces it between rounds
        return rq.pop(0)
    monkeypatch.setattr(build_reel.check_reel, "run", fake_run)

    def fake_deliver(m, prof, od, cl, rep, *, scratch_dir, audio=None, titles=None,
                     platform="", look=None, run_provenance=None):
        # run_provenance= tolerated (and ignored): build_reel now always passes it (Task 4)
        # — not the subject of this fixture; see
        # test_build_reel_threads_the_manifest_provenance_into_deliver for the dedicated check.
        # look= similarly tolerated (and ignored) — Task 5; see
        # test_build_reel_hands_the_look_to_deliver for the dedicated check.
        # scratch_dir= required with no default, mirroring the real deliver() (run-layout-
        # lifetimes Task 2) — build_reel always passes its own work_dir; a caller that
        # forgot to would TypeError here exactly as it would against the real function.
        # Ignored otherwise: no test in this file asserts on where build_reel points it.
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
    # round 0: ep1 fails (black hit — the colour corrector is retired) → reprocess;
    # round 1: passes → deliver
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]), _pass()]
    seen = _wire(monkeypatch, reports)
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert len(seen["reprocess"]) == 1
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
        checks={"black": CheckResult("black", False, {})},
        fail_reasons=[ReelFailure("black", "reprocess", 0, {"t": 1.0})],
        episode_count=3)
    round1 = ReelReport(
        checks={"black": CheckResult("black", False, {})},
        fail_reasons=[ReelFailure("black", "reprocess", 2, {"t": 1.0})],
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


def test_multi_culprit_round_second_failure_propagates_without_delivering(monkeypatch, tmp_path):
    # one round names TWO culprits (ep0, ep2 — both black); ep0 reprocess succeeds, ep2's
    # fails → stop_and_report names ep2, deliver never called, both items were attempted.
    rep = ReelReport(
        checks={"black": CheckResult("black", False, {})},
        fail_reasons=[ReelFailure("black", "reprocess", 0, {"t": 1.0}),
                      ReelFailure("black", "reprocess", 2, {"t": 2.0})],
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


def test_retime_rides_along_with_a_black_reprocess(monkeypatch, tmp_path):
    # The adopt block runs BEFORE the kind dispatch, so a re-time CARRIED BY a reprocess
    # round lands in that same round. Folding the adopt into the `kind == "retime"` branch
    # would still pass every other test in this file — and Task 1's pure next_action test,
    # which only inspects the returned action — while silently regressing this path: the
    # length failure would re-fire every round while the black fix converged.
    both = ReelReport(
        checks={"length": CheckResult("length", False, {"dur": 5.3, "target": 6.0}),
                "black": CheckResult("black", False, {})},
        fail_reasons=[ReelFailure("length", "pacing", None, {"dur": 5.3, "target": 6.0}),
                      ReelFailure("black", "reprocess", 1, {"t": 1.0})],
        episode_count=2)
    seen = _wire(monkeypatch, [both, _pass()])
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert seen["targets"] == [6.0, 5.3]     # adopted on the REPROCESS round, not one round later
    assert len(seen["reprocess"]) == 1       # and the black fix still ran


# --- pacing-fixed-point Task 4: build_reel's own outro_fixed computation ----
# reel_orchestration.next_action's tests already cover the pure decision exhaustively;
# these two confirm build_reel actually DERIVES outro_fixed from rm.outro and threads
# it through — this file was named as a Test target in the Task 4 brief, but the brief
# gave no literal test snippet for it (unlike test_reel_orchestration.py/test_models.py).

def test_a_within_band_shortfall_escalates_when_the_manifests_outro_chose_the_length(monkeypatch, tmp_path):
    seen = _wire(monkeypatch, [_length_fail(5.3, 6.0)])
    outro = {"reel_dur": 6.0, "line": 5.5, "fade": 0.5, "tail": 1.0, "rung": "gap", "moved": 0.3}
    res = build_reel.build_reel(_rm(outro=outro), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "outro-length-chosen"
    assert seen["deliver"] == []
    # THE FORWARD ITSELF: outro_fixed (asserted via the finding above) is derived from
    # rm.outro directly and does not, by itself, prove build_reel hands rm.outro to
    # check_reel.run — a caller could compute outro_fixed correctly and still pass
    # outro=None into check_reel.run's own (separately advisory) outro check. This is
    # the one place in the suite that would catch that.
    assert seen["outro"] == outro


def test_an_unchanged_rung_outro_does_not_block_the_absorb(monkeypatch, tmp_path):
    # rung "unchanged" means the fit chose NOTHING — the reel kept its footage-derived
    # length, so it must not block the absorb, exactly like a reel with outro=None.
    seen = _wire(monkeypatch, [_length_fail(5.3, 6.0), _pass()])
    outro = {"reel_dur": 6.0, "line": None, "fade": 0.5, "tail": 0.0,
             "rung": "unchanged", "moved": 0.0}
    res = build_reel.build_reel(_rm(outro=outro), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert seen["targets"] == [6.0, 5.3]


# --- music integration (Task 6) --------------------------------------------
# NOTE: _rm_music/_wire_music are deliberately NOT named _rm/_wire — this file
# already defines _rm(cap=3, n=2) and _wire(monkeypatch, reports, pe_results=None)
# for the pre-existing A.5 tests above; a same-named redefinition here would
# shadow those at module scope and break every test that calls them.

def _rm_music(music, ambient=True, sfx=False, look=None):
    ep0 = ReelEpisode(manifest={"segment": "s0.mp4", "target_dur": 3.0}, clip="c0.mp4", route="r0.json")
    ep1 = ReelEpisode(manifest={"segment": "s1.mp4", "target_dur": 3.0}, clip="c1.mp4", route="r1.json")
    return ReelManifest(episodes=[ep0, ep1], target_dur=6.0, variety_min=4,
                        music=music, ambient=ambient, sfx=sfx, look=look)


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
    # a fresh (no-arg) reprocessable-fail report — NOT named _color_fail: the module
    # already defines _color_fail(idx, target, culprit) for the A.5 tests above; a
    # same-named redefinition would shadow it and break every caller. The colour
    # corrector is retired (design 2026-08-29): this now builds a black hit, same as
    # _color_fail above — only the name is legacy.
    r = ReelReport(checks={"black": CheckResult("black", False, {})})
    r.fail_reasons = [ReelFailure("black", "reprocess", 0, {"t": 1.0})]
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
    #
    # rm.provenance carries no "episode_qc" block at all here — the exact shape
    # build_reel's own CLI produces when run directly against an EPISODES.json (the
    # third bypass, design §10/§12 review fix): the merge must stamp state "absent"
    # rather than leave a block with neither "judged" nor "absent".
    seen = {}
    _wire(monkeypatch, [_pass()])
    monkeypatch.setattr(build_reel.deliver, "deliver",
                        lambda *a, **k: seen.update(k) or "out/REEL_v1.mp4")
    rm = _rm()
    rm.provenance = {"edl": {"state": "intact"}}
    build_reel.build_reel(rm, str(tmp_path / "o"), str(tmp_path / "w"))
    assert seen["run_provenance"] == {"edl": {"state": "intact"},
                                      "episode_qc": {"state": "absent", "reprocessed_after": []}}


def test_build_reel_does_not_clobber_an_already_judged_qc_state(tmp_path, monkeypatch):
    # The two-phase gate (assemble_reel) stamps episode_qc.state="judged" onto
    # rm.provenance BEFORE calling build_reel — the setdefault added for the state-less
    # bypass above must not overwrite that with "absent".
    seen = {}
    _wire(monkeypatch, [_pass()])
    monkeypatch.setattr(build_reel.deliver, "deliver",
                        lambda *a, **k: seen.update(k) or "out/REEL_v1.mp4")
    rm = _rm()
    rm.provenance = {"episode_qc": {"state": "judged", "judged": {"0": "aa", "1": "bb"}}}
    build_reel.build_reel(rm, str(tmp_path / "o"), str(tmp_path / "w"))
    assert seen["run_provenance"]["episode_qc"] == {
        "state": "judged", "judged": {"0": "aa", "1": "bb"}, "reprocessed_after": []}


# --- Task 5: rm.look -> deliver(look=), and its fade -> mix(fade=) ---------------

def test_build_reel_hands_the_look_to_deliver(monkeypatch, tmp_path):
    seen = {}
    _wire(monkeypatch, [_pass()])
    monkeypatch.setattr(build_reel.deliver, "deliver",
                        lambda *a, **k: seen.update(k) or "out.mp4")
    build_reel.build_reel(_rm(look=LookSpec(vignette=0.4, fade=0.6)),
                          str(tmp_path / "out"), str(tmp_path / "w"))
    assert seen["look"] == LookSpec(vignette=0.4, fade=0.6)


def test_a_reel_with_no_look_passes_none_to_deliver(monkeypatch, tmp_path):
    # the other half of the wire: a reel with no look must still deliver exactly as
    # before — look=None reaches deliver, which is its own byte-identical fast path
    seen = {}
    _wire(monkeypatch, [_pass()])
    monkeypatch.setattr(build_reel.deliver, "deliver",
                        lambda *a, **k: seen.update(k) or "out.mp4")
    build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert seen["look"] is None


def test_build_reel_gives_mix_the_looks_fade(tmp_path, monkeypatch):
    mixed, delivered, got = [], [], {}
    _wire_music(monkeypatch, [_passing(), _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.mix, "mix", lambda *a, **k: (got.update(k), "stem.m4a")[1])
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    build_reel.build_reel(_rm_music(music=str(tmp_path / "MUSIC.json"), look=LookSpec(fade=0.8)),
                          str(tmp_path / "out"), str(tmp_path / "work"))
    assert got["fade"] == 0.8


def test_a_reel_with_no_look_keeps_mixs_own_default(tmp_path, monkeypatch):
    # absence of a look must not switch the audio bookend off: no fade= kwarg at all,
    # so mix keeps its own _FADE default rather than being handed something else
    mixed, delivered, got = [], [], {}
    _wire_music(monkeypatch, [_passing(), _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.mix, "mix", lambda *a, **k: (got.update(k), "stem.m4a")[1])
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    build_reel.build_reel(_rm_music(music=str(tmp_path / "MUSIC.json")),
                          str(tmp_path / "out"), str(tmp_path / "work"))
    assert "fade" not in got


def test_a_look_with_fade_zero_reaches_mix_as_zero_not_the_default(tmp_path, monkeypatch):
    # The one judgement call this task makes concrete: rm.look is not None but
    # rm.look.fade == 0.0 must still pass fade=0.0 explicitly — `rm.look.fade or 0.5`
    # would silently turn an authored 0 back into mix's 0.5s default, which is wrong:
    # an author who wrote fade: 0 asked for no bookend, in the picture AND the sound.
    mixed, delivered, got = [], [], {}
    _wire_music(monkeypatch, [_passing(), _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.mix, "mix", lambda *a, **k: (got.update(k), "stem.m4a")[1])
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    build_reel.build_reel(_rm_music(music=str(tmp_path / "MUSIC.json"), look=LookSpec(fade=0.0)),
                          str(tmp_path / "out"), str(tmp_path / "work"))
    assert "fade" in got and got["fade"] == 0.0


# --- 2026-08-18 re-judge: a judged reel does not ship over a re-rendered episode ---

def test_a_judged_reel_refuses_to_deliver_over_a_re_rendered_episode(monkeypatch, tmp_path):
    """design 2026-08-18 §2: the retry loop rewrote ep1's bytes AFTER episode_qc
    digested them, so the verdict is one render out of date and the reel must not ship."""
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]), _pass()]
    seen = _wire(monkeypatch, reports)
    rm = _rm()
    rm.provenance = {"episode_qc": {"state": "judged", "judged": {"0": "aa", "1": "bb"}}}
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "episode-qc-reprocessed"
    assert res["reprocessed"] == [1]
    assert "episode 1" in res["finding"]["problems"][0]
    assert res["report"]["checks"]["length"]["pass"] is True    # the PICTURE passed
    assert seen["deliver"] == []                                # nothing was delivered


def test_the_stop_costs_no_mix(monkeypatch, tmp_path):
    """The refusal sits at the TOP of the deliver arm, before the stem is built — a reel
    that is not going to ship must not pay for an audio pass first (design §2)."""
    mixed, delivered = [], []
    _wire_music(monkeypatch, [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]),
                              _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    monkeypatch.setattr(build_reel.process_episode, "process_episode",
                        lambda m, d, route_path=None, color_correct=None:
                        {"status": "mechanical_pass", "clip": d + "/ep.mp4"})
    rm = _rm_music(music=str(tmp_path / "MUSIC.json"))
    rm.provenance = {"episode_qc": {"state": "judged"}}
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "work"))
    assert res["finding"]["reason"] == "episode-qc-reprocessed"
    assert mixed == [] and delivered == []          # no stem built, nothing delivered


def test_an_unjudged_reel_still_delivers_after_a_reprocess(monkeypatch, tmp_path):
    """The other side of §2.1 — build_reel's own CLI has no verdict to invalidate, and
    the SP1 front door must keep working exactly as it did before this slice."""
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]), _pass()]
    _wire(monkeypatch, reports)
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert res["reprocessed"] == [1]
