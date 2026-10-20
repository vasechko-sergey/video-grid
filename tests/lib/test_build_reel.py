import dataclasses
import json
from pathlib import Path

import pytest
from scripts import build_reel
from scripts.lib.assembly import StreamInfo
from scripts.lib.look import LookSpec
from scripts.lib.models import (ReelEpisode, ReelManifest, ReelReport, ReelFailure,
                                CheckResult, MusicSpec, PathMeta)


def _rm(cap=3, n=2, platform="", look=None, outro=None):
    eps = [ReelEpisode(manifest={"segment": f"s{i}.mp4"}, clip=f"c{i}.mp4", route=f"r{i}.json")
           for i in range(n)]
    return ReelManifest(episodes=eps, target_dur=6.0, cap=cap,
                        platform=platform, look=look, outro=outro)


def _pass():
    return ReelReport(checks={"length": CheckResult("length", True, {})}, episode_count=2)


def _black_fail(idx):
    # A black-frame hit — the only failure class the reel-retry loop still
    # reprocesses now that the colour corrector is retired (design 2026-08-29,
    # colour-convergence-retire). Was _color_fail(idx, target, culprit): the
    # across-cut colour fail this factory used to build is gone, and so are the
    # target/culprit args every call site passed it to describe that pull.
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
    passed to each process_episode reprocess."""
    seen = {"deliver": [], "reprocess": [], "titles": [], "geometry": None, "platform": "",
            "targets": [], "deliver_platform": "", "outro": None,
            "tone_target": None, "tone_dsts": None, "predicted": None, "brief_len": None,
            "chroma": None, "gate_reasons": None}
    rq = list(reports)
    monkeypatch.setattr(build_reel.assembly, "probe_stream",
                        lambda p: StreamInfo(1080, 1920, 30.0, "yuv420p", "h264"))
    monkeypatch.setattr(build_reel.assembly, "assemble", lambda clips, dims, fps, out: out)
    # music=/audio= tolerated (and ignored): build_reel now always passes them (None for
    # these silent-reel tests, matching check_reel.run's real defaults) — not the subject
    # of this fixture, which only exercises the reprocess/deliver escalation ladder. titles=
    # IS captured into seen["titles"] so a test can assert build_reel forwards it to deliver.
    # geometry=/platform=/outro=/tone_target=/tone_dsts=/predicted=/brief_len= ARE captured
    # into seen so a test can assert build_reel builds and forwards them to check_reel.run.
    #
    # fix round 1 (Important): tone_target=/tone_dsts= used to be accepted-and-dropped here,
    # with a comment claiming their forwarding was "proven at the check_reel.run level" —
    # circular, since test_check_reel.py calls check_reel.run directly and never imports
    # build_reel. Changing tone_dsts to [None, ...] or tone_target to None at the real call
    # site left the whole suite green: in production every episode would then read
    # not-bound, the no-episode-bound arm returns passed=None, overall is unaffected, and the
    # reel delivers having examined zero pixels — the exact silent bypass this gate exists to
    # close. See test_build_reel_forwards_the_tone_convergence_pair_to_check_reel below,
    # mirroring the outro= precedent's own "THE FORWARD ITSELF" comment.
    #
    # predicted= is the same shape of risk one task later (2026-08-31 Task 7): a bare
    # `predicted=None` parameter that nothing asserts would let build_reel silently drop
    # its own _predict(rm) output and still leave every test in this file green — see
    # test_build_reel_forwards_one_prediction_per_episode below, which is the one place
    # that would catch it.
    #
    # outro_fixed (build_reel.py's OWN escalation gate, derived directly off rm.outro BEFORE
    # check_reel.run is ever called, at line ~66) is a SEPARATE computation from the outro=
    # kwarg — the two tests below exercise outro_fixed, not this forward. Conflating the two
    # left the outro= forward with no coverage at all: flipping build_reel.py's
    # `outro=rm.outro` to `outro=None` changed nothing either test could see.
    #
    # brief_len= is the same shape of risk again (2026-09-07, named-absence Task 5): a bare
    # `brief_len=None` parameter that nothing asserts would let build_reel silently drop
    # rm.brief_len, leaving check_reel.run's advisory brief_length row reading not-checked
    # forever while every test in this file stays green — see
    # test_build_reel_forwards_brief_len_to_check_reel below.
    #
    # chroma= is the same shape of risk again (2026-09-17, chroma-spread Task 5, carried
    # from Task 4's review): fake_run needs its OWN chroma=None parameter just to stay
    # callable — its signature is fixed with no **kwargs, so the real call's chroma=chroma
    # would otherwise raise "unexpected keyword argument" (exactly what happened here
    # before this parameter existed). But the parameter alone proves nothing about
    # CORRECTNESS: a dropped keyword silently defaults to None, and a wrong-variable
    # substitution (chroma=tone_dsts, say) binds just as silently under the right name —
    # neither raises. This file's own comments above record that tone_dsts=/tone_target=
    # were once silently dropped at the real call site while the whole suite stayed green,
    # until a dedicated assertion like this one was added — see
    # test_build_reel_forwards_chroma_to_check_reel below.
    #
    # gate_reasons= is the same shape of risk once more (2026-09-30, threshold-surface Task 5):
    # dropped, it silently defaults to None and every authored bar vanishes from the report
    # that says PASS while the suite stays green — see
    # test_build_reel_hands_the_gate_reasons_to_check_reel below.
    def fake_run(m, e, s, o, music=None, audio=None, geometry=None, platform="", outro=None,
                predicted=None, tone_target=None, tone_dsts=None, brief_len=None,
                chroma=None, gate_reasons=None):
        seen["geometry"] = geometry
        seen["platform"] = platform
        seen["outro"] = outro
        seen["predicted"] = predicted
        seen["tone_target"] = tone_target
        seen["tone_dsts"] = tone_dsts
        seen["brief_len"] = brief_len
        seen["chroma"] = chroma
        seen["gate_reasons"] = gate_reasons
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

    def fake_pe(manifest, project_dir, route_path=None):
        # project_dir recorded since 2026-09-24 (retry-record Task 5): WHERE the
        # reprocess writes its sidecars is the subject of a test now, and a fake
        # that drops the argument cannot tell the two candidate directories apart.
        seen["reprocess"].append({"route": route_path, "project_dir": project_dir})
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
    reports = [_black_fail(1), _pass()]
    seen = _wire(monkeypatch, reports)
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert len(seen["reprocess"]) == 1
    assert seen["reprocess"][0]["route"] == "r1.json"     # frozen route reused


def test_a_delivered_reel_reports_which_episodes_were_reprocessed(monkeypatch, tmp_path):
    """build_reel's loop-2 re-renders culprits AFTER the QC gate ran, so which ones
    it touched has to leave the loop (design §8) — a verdict on ep1 is one render out
    of date the moment ep1 is rebuilt."""
    reports = [_black_fail(1), _pass()]
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
    rm = ReelManifest(episodes=eps, target_dur=6.0, cap=3)
    reports = [_black_fail(1), _pass()]
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
    reports = [_black_fail(1)]
    seen = _wire(monkeypatch, reports,
                 pe_results=[{"status": "needs_input", "problems": ["bad manifest"]}])
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "reprocess-failed" and res["finding"]["episode_idx"] == 1


def test_capped_episode_escalates(monkeypatch, tmp_path):
    # cap=1: round 0 reprocesses ep1 (attempts→1); round 1 still fails → capped escalate
    reports = [_black_fail(1), _black_fail(1)]
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


def test_build_reel_forwards_the_tone_convergence_pair_to_check_reel(monkeypatch, tmp_path):
    """fix round 1, Important: fake_run accepted tone_target=/tone_dsts= and dropped
    them, and nothing in this file — or anywhere else — ever looked at what arrived. A
    comment here used to claim the forwarding was "proven at the check_reel.run level",
    which was circular: test_check_reel.py calls check_reel.run directly and never
    imports build_reel, so it cannot see whether build_reel itself hands over the right
    values. Changing tone_dsts to [None, None], or tone_target to None, at the real
    call site in build_reel.py left the whole suite green before this test existed — in
    production that reaches the exact silent bypass this gate exists to close: every
    episode reads not-bound, the no-episode-bound arm returns passed=None, overall is
    unaffected, and the reel delivers having examined zero pixels.

    THE FORWARD ITSELF, mirroring test_a_within_band_shortfall_escalates_when_the_
    manifests_outro_chose_the_length above: rm.tone_target is a plain attribute read
    and the per-episode tone_dst list is a comprehension over rm.episodes, so a correct
    manifest alone proves nothing about whether build_reel actually hands both to
    check_reel.run — this is the one place in the suite that would catch it not doing so."""
    seen = _wire(monkeypatch, [_pass()])
    eps = [ReelEpisode(manifest={"segment": "s0.mp4", "tone_dst": [20.0, 100.0, 200.0]},
                       clip="c0.mp4", route="r0.json"),
           ReelEpisode(manifest={"segment": "s1.mp4"}, clip="c1.mp4", route="r1.json")]
    rm = ReelManifest(episodes=eps, target_dur=6.0, tone_target=(20.0, 100.0, 200.0))
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert seen["tone_target"] == (20.0, 100.0, 200.0)
    assert seen["tone_dsts"] == [[20.0, 100.0, 200.0], None]


def test_build_reel_forwards_brief_len_to_check_reel(monkeypatch, tmp_path):
    """named-absence Task 5: rm.brief_len is a plain attribute read, so a manifest
    carrying it proves nothing about whether build_reel actually hands it to
    check_reel.run — mirroring the tone_target/tone_dsts precedent immediately above.
    Without this test, dropping `brief_len=rm.brief_len` at the real call site would
    leave check_reel's advisory brief_length row reading not-checked forever and the
    whole suite green."""
    seen = _wire(monkeypatch, [_pass()])
    eps = [ReelEpisode(manifest={"segment": "s0.mp4"}, clip="c0.mp4", route="r0.json"),
           ReelEpisode(manifest={"segment": "s1.mp4"}, clip="c1.mp4", route="r1.json")]
    rm = ReelManifest(episodes=eps, target_dur=6.0, brief_len=45.0)
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert seen["brief_len"] == 45.0


def test_build_reel_forwards_chroma_to_check_reel(monkeypatch, tmp_path):
    """chroma-spread Task 5, mandated by Task 4's review: build_reel.py builds
    `chroma = [e.chroma for e in rm.episodes]` as a local list (design
    2026-09-17 §2.3) — a plain comprehension over rm.episodes, so a manifest
    carrying real chroma readings proves nothing about whether build_reel
    actually hands that list to check_reel.run, mirroring the tone_target/
    tone_dsts/brief_len precedents above. fake_run's `chroma=None` parameter
    (added this task) only keeps the fake callable against the real call's
    `chroma=chroma` — a dropped keyword or a wrong-variable substitution would
    each bind just as silently under it, with no error either way; this
    assertion is what would catch either."""
    seen = _wire(monkeypatch, [_pass()])
    eps = [ReelEpisode(manifest={"segment": "s0.mp4"}, clip="c0.mp4", route="r0.json",
                       chroma={"delta_c": -4.18, "delta_h": -1.22}),
           ReelEpisode(manifest={"segment": "s1.mp4"}, clip="c1.mp4", route="r1.json")]
    rm = ReelManifest(episodes=eps, target_dur=6.0)
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    # No `region` key on the carried reading (final whole-branch review, FIX 1).
    assert seen["chroma"] == [{"delta_c": -4.18, "delta_h": -1.22}, None]


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


def _black_fail_music():
    # a fresh (no-arg) reprocessable-fail report — NOT named _black_fail: the module
    # already defines _black_fail(idx) for the A.5 tests above; a same-named
    # redefinition would shadow it and break every caller. Kept as its own tiny
    # factory rather than calling _black_fail(0) because the two build slightly
    # different reports (episode_count, check detail) and no test here depends on
    # them matching — sharing one would be coincidence, not intent.
    r = ReelReport(checks={"black": CheckResult("black", False, {})})
    r.fail_reasons = [ReelFailure("black", "reprocess", 0, {"t": 1.0})]
    return r


def test_build_reel_music_delivers_after_full_reprocess_budget(tmp_path, monkeypatch):
    # the mix `continue` needs +2 loop headroom, not +1 — a good, fully-mixed reel
    # that used its whole reprocess budget must deliver, not fall to reel-cap-exhausted
    ep = ReelEpisode(manifest={"segment": "s0.mp4", "target_dur": 6.0}, clip="c0.mp4", route="r0.json")
    rm = ReelManifest(episodes=[ep], target_dur=6.0, cap=3, music=str(tmp_path / "MUSIC.json"))
    mixed, delivered = [], []
    reports = [_black_fail_music(), _black_fail_music(), _black_fail_music(), _passing(), _passing()]
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
    reports = [_black_fail_music(), _black_fail_music(), _black_fail_music(),
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
    assert (got["fade"], got["fade_in"]) == (0.8, 0.8)


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
    reports = [_black_fail(1), _pass()]
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
    _wire_music(monkeypatch, [_black_fail(1), _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    monkeypatch.setattr(build_reel.process_episode, "process_episode",
                        lambda m, d, route_path=None:
                        {"status": "mechanical_pass", "clip": d + "/ep.mp4"})
    rm = _rm_music(music=str(tmp_path / "MUSIC.json"))
    rm.provenance = {"episode_qc": {"state": "judged"}}
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "work"))
    assert res["finding"]["reason"] == "episode-qc-reprocessed"
    assert mixed == [] and delivered == []          # no stem built, nothing delivered


def test_an_unjudged_reel_still_delivers_after_a_reprocess(monkeypatch, tmp_path):
    """The other side of §2.1 — build_reel's own CLI has no verdict to invalidate, and
    the SP1 front door must keep working exactly as it did before this slice."""
    reports = [_black_fail(1), _pass()]
    _wire(monkeypatch, reports)
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert res["reprocessed"] == [1]


# --- grade-sensor-references Task 7: build_reel predicts each episode's own
# declared profile -----------------------------------------------------------
# check_reel.grade_faithful (design 2026-08-31) needs a per-episode (p5, p50, p95)
# prediction of what each episode's OWN declared chain renders; build_reel is where
# the manifests live, so it builds that list (_predict) and forwards it. These three
# tests are the ones that would catch a dropped or per-round-rebuilt argument — see
# the "predicted=" note on _wire above, which mirrors the tone_dsts/outro precedents
# this same file already carries.

def test_build_reel_forwards_one_prediction_per_episode(monkeypatch, tmp_path):
    """Nothing else pins this. A dropped argument leaves the gate reporting
    not-checked forever and the suite green."""
    seen = _wire(monkeypatch, [_pass()])
    monkeypatch.setattr(build_reel, "_predict",
                        lambda rm: [(52.0, 104.0, 192.0)] * len(rm.episodes))
    build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert seen["predicted"] == [(52.0, 104.0, 192.0)] * 2


def test_a_plan_that_cannot_be_built_becomes_None_not_a_crash(monkeypatch, tmp_path):
    """One unplannable episode must not cost the reel its whole gate — check_reel
    names it in not_checked."""
    def boom(md, src, route):
        raise FileNotFoundError("gone")
    monkeypatch.setattr(build_reel.process_episode, "plan_for", boom)
    rm = _rm()
    assert build_reel._predict(rm) == [None] * len(rm.episodes)


def test_predictions_are_built_ONCE_not_per_retry_round(monkeypatch, tmp_path):
    """A reprocess re-renders with the same manifest, so the declaration cannot move
    between rounds — the same argument tone_dsts already makes."""
    calls = []
    monkeypatch.setattr(build_reel, "_predict", lambda rm: calls.append(1) or [None, None])
    _wire(monkeypatch, [_black_fail(1), _pass()])   # round 0 reprocesses ep1; round 1 delivers
    build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert len(calls) == 1


# --- chroma-spread Task 4: the retry loop keeps chroma fresh (design
# docs/specs/2026-09-17-chroma-spread-design.md §2.3) ---

def test_a_reprocessed_episode_hands_check_reel_its_NEW_chroma(monkeypatch, tmp_path):
    """A reprocess re-renders the episode, so check_episode ran again and produced a
    fresh displacement. The stale phase-1 value must not outlive the clip it
    described (design §2.3).

    Rewritten, final whole-branch review, FIX 8: check_reel.run has taken a
    chroma= keyword since Task 5 landed, and build_reel's real call site already
    passes chroma=chroma every round, so the spy below reads that KEYWORD
    ARGUMENT directly rather than reaching into build_reel's own stack frame for a
    local variable by NAME (the previous version's `inspect.currentframe()
    .f_back.f_locals["chroma"]`, written before Task 5 existed and never updated
    once it did). Still not redundant with
    test_build_reel_forwards_chroma_to_check_reel: that test captures a
    reference to build_reel's live `chroma` list, which the reprocess arm
    mutates IN PLACE, so by the time the test inspects it every round has
    already collapsed to the SAME final list. This test's whole
    point is the two rounds disagreeing — round 0 must still show phase 1's stale
    value and only round 1 the refreshed one — so the spy takes its own
    `list(...)` copy of `chroma` at each call, before the reprocess arm's next
    mutation, rather than reading the list back afterwards. Built on the file's
    existing reprocess fixture (_wire/_black_fail/_pass), one layer of
    monkeypatch.setattr on top of it — safe because monkeypatch unwinds setattr
    calls in reverse order regardless of how many times the same attribute was
    patched."""
    fresh_report = {"checks": {"grade_damage": {"region": "crop",
                                                 "delta_c": 2.0, "delta_h": 0.3}}}
    seen = _wire(monkeypatch, [_black_fail(1), _pass()],
                pe_results=[{"status": "mechanical_pass", "clip": "c1.mp4",
                             "report": fresh_report}])
    inner_run = build_reel.check_reel.run   # _wire's own fake_run, still queued on the reports
    rounds = []

    def spying_run(*a, **kw):
        rounds.append(list(kw["chroma"]))
        return inner_run(*a, **kw)
    monkeypatch.setattr(build_reel.check_reel, "run", spying_run)

    eps = [ReelEpisode(manifest={"segment": "s0.mp4"}, clip="c0.mp4", route="r0.json"),
           ReelEpisode(manifest={"segment": "s1.mp4"}, clip="c1.mp4", route="r1.json",
                       chroma={"delta_c": -9.0, "delta_h": -2.0})]
    rm = ReelManifest(episodes=eps, target_dur=6.0)
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))

    assert res["status"] == "delivered"
    assert len(seen["reprocess"]) == 1
    # Narrowed to the "route" key alone since 2026-09-24 (retry-record Task 5):
    # _wire's fake_pe now also records project_dir (a different test's subject),
    # and a full-dict equality here would fail on that unrelated addition — this
    # test's own subject is the chroma refresh below, not the reprocess dict's shape.
    assert seen["reprocess"][0]["route"] == "r1.json"      # the reprocess ran on ep1, frozen route
    assert len(rounds) == 2                                # round 0 (reprocess) + round 1 (deliver)
    assert rounds[0][1] == {"delta_c": -9.0, "delta_h": -2.0}   # still phase 1's
    assert rounds[-1][1] == {"delta_c": 2.0, "delta_h": 0.3}    # refreshed


def test_a_rejected_reprocess_never_relabels_the_episodes_chroma(monkeypatch, tmp_path):
    """Fix round 1, Important finding: the reprocess arm's early return on a
    REJECTED re-render (`if res["status"] != "mechanical_pass": return ...`,
    build_reel.py line 221) sits three lines ABOVE the chroma refresh (line 227).
    Today's ordering is correct, but nothing pinned it — a future edit that moved
    `chroma[item.idx] = color_fidelity.shift_from_report(res.get("report") or {})`
    above that guard would not crash (`res.get("report") or {}` degrades to a
    not-checked reading rather than raising, and a status like "escalate" carries
    a real `report` besides) and would silently relabel a rejected render's
    episode with a reading taken from a clip nobody accepted. The two existing
    tests that already drive this branch — test_reprocess_failure_propagates and
    test_multi_culprit_round_second_failure_propagates_without_delivering — assert
    on the stop_and_report finding and nothing about chroma.

    The rejected result here is `status="escalate"` carrying a REAL report (not
    the report-less "needs_input" those two tests use) — process_episode.py's own
    docstring says escalate DOES carry one — so the mutation this test guards
    against would not merely degrade to "not-checked": it would read a plausible-
    looking, wrong number off an unaccepted render. That is also why this cannot
    be observed the way the sibling test above observes a refresh: a rejection
    returns stop_and_report immediately, before any second check_reel.run call
    exists to spy on. color_fidelity.shift_from_report is the ONLY statement in
    the reprocess arm that ever writes chroma[item.idx], so proving it is never
    called for this rejected attempt IS proving the entry was left exactly as
    phase 1 left it."""
    calls = []
    monkeypatch.setattr(build_reel.color_fidelity, "shift_from_report",
                        lambda report: calls.append(report) or {"status": "not-checked",
                                                                 "reason": "spy"})
    rejected_report = {"checks": {"grade_damage": {"region": "crop",
                                                    "delta_c": 99.0, "delta_h": 99.0}}}
    seen = _wire(monkeypatch, [_black_fail(1)],
                pe_results=[{"status": "escalate", "report": rejected_report}])

    eps = [ReelEpisode(manifest={"segment": "s0.mp4"}, clip="c0.mp4", route="r0.json"),
           ReelEpisode(manifest={"segment": "s1.mp4"}, clip="c1.mp4", route="r1.json",
                       chroma={"delta_c": -9.0, "delta_h": -2.0})]
    rm = ReelManifest(episodes=eps, target_dur=6.0)
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))

    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "reprocess-failed" and res["finding"]["episode_idx"] == 1
    assert seen["deliver"] == []                # a rejected reprocess is never delivered
    assert calls == []                          # shift_from_report never ran on the rejected report


# --- 2026-09-24 retry-record Task 3: _predict rebuilds the render that shipped ---

def test_predict_plans_each_episode_with_the_params_its_sidecar_recorded(
        monkeypatch, tmp_path):
    """A retried episode used to contribute None here — the drift oracle correctly
    refused a plan rebuilt at the defaults — so the episode that had trouble was
    the episode that lost its grade_faithful gate (design 2026-09-24 §0.3).

    Spied on the ARGUMENTS, not on the returned profile: a wrong implementation
    that ignored the recorded params would still return a profile, and on any
    fixture flat enough to fake it would be the same profile."""
    d = tmp_path / "ep0"
    d.mkdir()
    meta = d / "path.meta.json"
    meta.write_text(json.dumps(PathMeta(
        mode="fill", crop_w=405, crop_h=720, crop_y=0, src_dims=(1280, 720),
        canvas=(9, 16), out_dims=(404, 720), rect_px=(0, 0, 404, 720), freedom=875,
        max_speed=450.0, smooth_window_s=0.5).to_dict()))
    ep = ReelEpisode(manifest={"segment": "s.mp4"}, clip="c0.mp4", route="r0.json",
                     path=str(d / "path.json"), meta=str(meta))
    rm = ReelManifest(episodes=[ep], target_dur=6.0)

    seen = {}
    monkeypatch.setattr(build_reel.probe, "source_for", lambda md, epdir: "src.mp4")

    class _Plan:
        dur = 3.0

    def _plan_for(md, src, route, *, params=None):
        seen["params"] = params
        return _Plan()
    monkeypatch.setattr(build_reel.process_episode, "plan_for", _plan_for)
    monkeypatch.setattr(build_reel.probe, "_refuse_on_drift", lambda *a: None)
    monkeypatch.setattr(build_reel.color_measure, "crop_percentiles",
                        lambda plan, src, times: (1.0, 2.0, 3.0))
    monkeypatch.setattr(build_reel.color, "sample_times", lambda dur: [0.0])
    monkeypatch.setattr(build_reel, "_log", lambda *a, **k: None)

    out = build_reel._predict(rm)
    assert seen["params"] == {"max_speed": 450.0, "smooth_window_s": 0.5}
    assert out == [(1.0, 2.0, 3.0)]


# --- 2026-09-24 retry-record Task 5: one episode, one scratch directory ---

def test_a_reprocess_writes_beside_the_sidecars_episodes_json_names(monkeypatch, tmp_path):
    """Phase 1 writes build/ep{i}; this driver is handed build/reel, so a reprocess
    used to write build/reel/ep{i} while ReelEpisode.path/meta still named the
    first. A re-pack then read a MIXED packet — fresh pixels, stale report,
    storyboard, geometry and track record — and the clip_digest binding that exists
    to catch a stale packet could not see it, because the stale half is not the
    clip (design 2026-09-24 §0.7).

    Note _rm() builds episodes with NO path, which is why this test builds its own:
    under the empty-path fallback every other test in this file keeps the old
    location, which is the control below."""
    phase1 = tmp_path / "build" / "ep0"
    phase1.mkdir(parents=True)
    eps = [ReelEpisode(manifest={"segment": "s0.mp4"}, clip="c0.mp4", route="r0.json",
                       path=str(phase1 / "path.json"), meta=str(phase1 / "path.meta.json")),
           ReelEpisode(manifest={"segment": "s1.mp4"}, clip="c1.mp4", route="r1.json")]
    rm = ReelManifest(episodes=eps, target_dur=6.0, cap=3)
    seen = _wire(monkeypatch, [_black_fail(0), _pass()])

    build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "build" / "reel"))

    assert seen["reprocess"] == [{"route": "r0.json", "project_dir": str(phase1)}]


def test_a_reprocess_of_an_episode_with_no_sidecar_keeps_the_work_dir(monkeypatch, tmp_path):
    """The control. A hand-authored reel manifest may legally carry no path
    (ReelEpisode.path defaults to "" and episode_qc._epdir refuses such a manifest
    by name), so there is nothing to derive and nothing to keep in step — today's
    location is kept rather than Path("").parent, which is "." and would write into
    the current working directory in silence."""
    rm = _rm(n=2)
    work = tmp_path / "build" / "reel"
    seen = _wire(monkeypatch, [_black_fail(0), _pass()])

    build_reel.build_reel(rm, str(tmp_path / "out"), str(work))

    assert seen["reprocess"] == [{"route": "r0.json", "project_dir": str(work / "ep0")}]


# --- threshold-surface Task 4: the reprocess arm reads the carrier (design
# docs/specs/2026-09-30-threshold-surface-design.md §2.3) ---

GATES_DOC = {"entropy_floor": {"value": 0.85, "why": "log profile"},
             "loudness_tol": {"value": 2.0, "why": "live room"}}


def _spy_reprocess_kwargs(monkeypatch, passed):
    """Wrap the process_episode fake `_wire` installed, recording into `passed` the EXTRA
    keyword arguments each reprocess was handed.

    The fake takes no `gates`, exactly as the real call shape did before this slice, so the
    wrapper strips it before delegating: what is under test is what the reprocess arm PASSED,
    not what a fake tolerates. Everything else is forwarded, so the fake's own signature still
    bites on any other keyword."""
    inner = build_reel.process_episode.process_episode

    def spy(manifest, project_dir, route_path=None, **kw):
        passed.append(dict(kw))
        return inner(manifest, project_dir, route_path=route_path,
                     **{k: v for k, v in kw.items() if k != "gates"})
    monkeypatch.setattr(build_reel.process_episode, "process_episode", spy)


def test_a_reprocess_is_judged_against_the_same_authored_bar_as_its_siblings(
        monkeypatch, tmp_path):
    """Without the whole set on the manifest the reprocess arm has nowhere to read it from,
    and the re-rendered episode is judged against a different bar in silence (design §2.3).
    The set is handed through WHOLE — both scopes, unfiltered — because process_episode
    partitions where a CheckSpec is built and no caller does. An unauthored reel's reprocess
    call keeps the shape it had before gates existed; that control is INSIDE this test so the
    instrument has just been shown able to see a `gates` kwarg before it is trusted to report
    the absence of one."""
    _wire(monkeypatch, [_black_fail(1), _pass(), _black_fail(1), _pass()])
    passed = []
    _spy_reprocess_kwargs(monkeypatch, passed)

    authored = dataclasses.replace(_rm(), gates=GATES_DOC)
    res = build_reel.build_reel(authored, str(tmp_path / "out1"), str(tmp_path / "w1"))
    assert res["status"] == "delivered"
    assert passed == [{"gates": GATES_DOC}]

    passed.clear()
    res = build_reel.build_reel(_rm(), str(tmp_path / "out2"), str(tmp_path / "w2"))
    assert res["status"] == "delivered"
    assert passed == [{}]


# --- threshold-surface Task 5: the reason rides the verdict and the attestation (design
# docs/specs/2026-09-30-threshold-surface-design.md §2.4) ---


def test_build_reel_hands_the_gate_reasons_to_check_reel(monkeypatch, tmp_path):
    """The one place check_reel.run is called, so the only place a reel-scope bar's reason can
    leave for the verdict it bought. The WHOLE authored set goes through, both scopes — the
    callee names only the bars its own spec class owns. The control is inside the test, so the
    instrument has just been shown able to see the kwarg before it is trusted to report its
    absence: a reel that authored nothing is handed none and keeps the call shape it had."""
    seen = _wire(monkeypatch, [_pass()])
    build_reel.build_reel(dataclasses.replace(_rm(), gates=GATES_DOC),
                          str(tmp_path / "o1"), str(tmp_path / "w1"))
    assert seen["gate_reasons"] == {"entropy_floor": "log profile", "loudness_tol": "live room"}

    seen = _wire(monkeypatch, [_pass()])
    build_reel.build_reel(_rm(), str(tmp_path / "o2"), str(tmp_path / "w2"))
    assert seen["gate_reasons"] is None


def test_the_attestation_is_handed_every_authored_gate_with_its_scope_and_reason(
        monkeypatch, tmp_path):
    """Derived from the manifest's own `gates`, the same set check_spec judged the reel by, at
    the moment of delivery — not from a copy stored somewhere else, which could disagree with
    the bar that actually ran. Both scopes: episode_qc judged the clips by the episode half, and
    the attestation is the record of which bars judged THESE clips (design §6). Absent, rather
    than an empty list, when nothing was authored (the exact-dict control is
    test_build_reel_threads_the_manifest_provenance_into_deliver)."""
    seen = {}
    _wire(monkeypatch, [_pass()])
    monkeypatch.setattr(build_reel.deliver, "deliver",
                        lambda *a, **k: seen.update(k) or "out/REEL_v1.mp4")
    build_reel.build_reel(dataclasses.replace(_rm(), gates=GATES_DOC),
                          str(tmp_path / "o"), str(tmp_path / "w"))
    assert seen["run_provenance"]["gates"] == [
        {"field": "entropy_floor", "value": 0.85, "default": 0.9, "scope": "episode",
         "blocking": True, "why": "log profile"},
        {"field": "loudness_tol", "value": 2.0, "default": 1.0, "scope": "reel",
         "blocking": True, "why": "live room"}]


def test_a_stale_gates_block_in_the_provenance_never_reaches_the_attestation(
        monkeypatch, tmp_path):
    """The comment at the call says the attestation's rows are DERIVED from the set that judged
    the reel, never copied through provenance, which a hand-edited EPISODES.json can leave
    disagreeing with `gates`. That held only when something was authored: with `gates` empty
    the branch was skipped and a stale `gates` key already sitting in `provenance` survived
    `dict(rm.provenance)` into the attestation, naming a bar no check was judged by (final
    review M5). The control is the previous test: an authored set replaces whatever was there."""
    stale = [{"field": "entropy_floor", "value": 0.1, "default": 0.9, "scope": "episode",
              "blocking": True, "why": "left over from an earlier edit"}]
    seen = {}
    _wire(monkeypatch, [_pass()])
    monkeypatch.setattr(build_reel.deliver, "deliver",
                        lambda *a, **k: seen.update(k) or "out/REEL_v1.mp4")
    build_reel.build_reel(dataclasses.replace(_rm(), provenance={"gates": stale}),
                          str(tmp_path / "o"), str(tmp_path / "w"))
    assert "gates" not in seen["run_provenance"]


# --- retro 2026-10-16 S6/S18: the opening and the music's closing fade ---------------

def _mix_kwargs(tmp_path, monkeypatch, rm):
    mixed, delivered, got = [], [], {}
    _wire_music(monkeypatch, [_passing(), _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.mix, "mix", lambda *a, **k: (got.update(k), "stem.m4a")[1])
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "work"))
    return got


def test_a_look_that_opens_on_picture_opens_the_sound_without_a_fade(tmp_path, monkeypatch):
    rm = _rm_music(music=str(tmp_path / "MUSIC.json"), look=LookSpec(fade=0.8, fade_in=0.0))
    got = _mix_kwargs(tmp_path, monkeypatch, rm)
    assert (got["fade"], got["fade_in"]) == (0.8, 0.0)


def test_a_length_the_outro_fit_chose_closes_on_the_fits_own_fade(tmp_path, monkeypatch):
    """The second real run's REEL_v5 (retro 2026-10-16 S18): the outro fit made the reel
    `line + 1.5` so the music's fade would START on the bar line, but mix was handed the
    look's 0.8 — the level held until 0.8s from the end, 0.7s past the line."""
    rm = _rm_music(music=str(tmp_path / "MUSIC.json"), look=LookSpec(fade=0.8, fade_in=0.0))
    rm.outro = {"reel_dur": 6.0, "line": 4.5, "fade": 1.5, "tail": 0.0,
                "rung": "no-gap", "moved": 0.0}
    got = _mix_kwargs(tmp_path, monkeypatch, rm)
    assert (got["fade"], got["fade_in"]) == (1.5, 0.0)


def test_an_unchanged_outro_leaves_the_looks_fade(tmp_path, monkeypatch):
    rm = _rm_music(music=str(tmp_path / "MUSIC.json"), look=LookSpec(fade=0.8, fade_in=0.0))
    rm.outro = {"reel_dur": 6.0, "line": None, "fade": 0.8, "tail": 0.0,
                "rung": "unchanged", "moved": 0.0, "cause": "no-bars"}
    got = _mix_kwargs(tmp_path, monkeypatch, rm)
    assert (got["fade"], got["fade_in"]) == (0.8, 0.0)


def test_a_fitted_outro_without_a_look_keeps_mixs_default_opening(tmp_path, monkeypatch):
    rm = _rm_music(music=str(tmp_path / "MUSIC.json"))
    rm.outro = {"reel_dur": 6.0, "line": 4.5, "fade": 1.5, "tail": 0.0,
                "rung": "no-gap", "moved": 0.0}
    got = _mix_kwargs(tmp_path, monkeypatch, rm)
    assert (got["fade"], got["fade_in"]) == (1.5, build_reel.mix._FADE)


# --- music in the app: the music-less delivery and its note (design 2026-10-20) ---

def _wire_in_app(monkeypatch, tmp_path, mixed, runs):
    """_wire_music's world plus what the music-less arm touches: the mux (a fake proc.run
    that writes its output file, so os.replace has something to move) and the digest."""
    delivered = tmp_path / "out" / "REEL_v3.mp4"
    delivered.parent.mkdir(parents=True)
    delivered.write_bytes(b"reel")
    monkeypatch.setattr(build_reel.assembly, "probe_stream", lambda p: _si())
    monkeypatch.setattr(build_reel.assembly, "assemble", lambda *a, **k: None)
    monkeypatch.setattr(build_reel.check_reel, "_probe_dur",
                        lambda p: 3.0 if Path(p).name.startswith("c") else 6.0)
    reports = [_passing(), _passing()]
    monkeypatch.setattr(build_reel.check_reel, "run", lambda *a, **k: reports.pop(0))
    def fake_mix(mus, wd, dur, segments=None, ambient=True, sfx=False, **k):
        mixed.append(k)
        if "without_music" in k:                  # mix's own record of what it rendered
            Path(wd).mkdir(parents=True, exist_ok=True)
            Path(k["without_music"]).with_suffix(".json").write_text(json.dumps(
                {"ambient": True, "sfx": False, "gain_db": 6.0, "linear": True}))
        return "stem.m4a"
    monkeypatch.setattr(build_reel.mix, "mix", fake_mix)
    monkeypatch.setattr(build_reel.deliver, "deliver", lambda *a, **k: str(delivered))

    def fake_run(cmd, **k):
        runs.append(cmd)
        Path(cmd[-1]).write_bytes(b"muxed")
    monkeypatch.setattr(build_reel.proc, "run", fake_run)
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    return delivered


def test_a_reel_for_the_app_also_ships_without_its_song_and_with_a_note(tmp_path, monkeypatch):
    mixed, runs = [], []
    delivered = _wire_in_app(monkeypatch, tmp_path, mixed, runs)
    rm = dataclasses.replace(_rm_music(music=str(tmp_path / "MUSIC.json")), music_in_app=True)
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "work"))
    assert res["status"] == "delivered"
    # the stem without the song was asked for alongside the music stem
    assert mixed == [{"without_music": str(tmp_path / "work" / "audio_no_music.m4a")}]
    nm = tmp_path / "out" / "no-music" / "REEL_v3.mp4"
    note = tmp_path / "out" / "no-music" / "REEL_v3.sound.md"
    assert res["no_music"] == str(nm) and res["sound_note"] == str(note)
    assert nm.read_bytes() == b"muxed" and not list(nm.parent.glob(".*part*"))
    mux = runs[-1]
    assert mux[mux.index("-c") + 1] == "copy" and mux[mux.index("-map") + 1] == "0:v"
    assert str(delivered) in mux
    text = note.read_text()
    assert "Start in the track | 0:00.0" in text and "| Cuts | 3.0 s |" in text
    # the music-less file sits in a subfolder, so no delivery reader can mistake it
    assert sorted(p.name for p in (tmp_path / "out").glob("REEL_v*")) == ["REEL_v3.mp4"]


def test_a_reel_not_for_the_app_ships_exactly_as_before(tmp_path, monkeypatch):
    mixed, runs = [], []
    _wire_in_app(monkeypatch, tmp_path, mixed, runs)
    res = build_reel.build_reel(_rm_music(music=str(tmp_path / "MUSIC.json")),
                                str(tmp_path / "out"), str(tmp_path / "work"))
    assert "no_music" not in res and mixed == [{}] and runs == []
    assert not (tmp_path / "out" / "no-music").exists()



def test_a_failed_music_less_mux_is_reported_beside_the_delivery_not_raised(tmp_path, monkeypatch):
    """The reel is already delivered and attested when this runs; raising would lose that
    result and a re-run would spend the next version number on the same reel."""
    mixed, runs = [], []
    _wire_in_app(monkeypatch, tmp_path, mixed, runs)

    def failing_run(cmd, **k):
        Path(cmd[-1]).write_bytes(b"half")
        raise RuntimeError("ffmpeg exited 1")
    monkeypatch.setattr(build_reel.proc, "run", failing_run)
    rm = dataclasses.replace(_rm_music(music=str(tmp_path / "MUSIC.json")), music_in_app=True)
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "work"))
    assert res["status"] == "delivered" and "no_music" not in res
    assert "ffmpeg exited 1" in res["no_music_error"]
    assert not list((tmp_path / "out" / "no-music").glob(".*part*"))   # no half-written file
