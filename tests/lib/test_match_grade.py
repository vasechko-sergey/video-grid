import json
import sys
from dataclasses import replace

import pytest

from scripts import match_grade
from scripts.lib import matchgrade, moodpreset, provenance
from scripts.lib.edl import EDLEpisode, EDL


def _ep(source, start=0.0, dur=2.0, **kw):
    return EDLEpisode(source=source, start=start, dur=dur, shot_type="wide",
                      composition="center", grid="thirds", **kw)


def _edl(*eps):
    return EDL(episodes=tuple(eps))


def test_conduct_measures_at_the_window_midpoint(monkeypatch):
    seen = []
    monkeypatch.setattr(match_grade, "measure_profile",
                        lambda clip, at=None: seen.append((clip, at)) or (10.0, 100.0, 150.0))
    edl = _edl(_ep("a.mp4", start=4.0, dur=2.0))
    match_grade.conduct(edl, "/foot")
    assert seen == [("/foot/a.mp4", 5.0)]           # start + dur/2, resolved under footage_root


def test_conduct_authors_deviating_and_leaves_near_median(monkeypatch):
    # ep0 dark, ep1 bright → median between; ep2 sits on the median (within eps)
    profs = {"d.mp4": (10.0, 90.0, 150.0), "b.mp4": (40.0, 130.0, 240.0),
             "m.mp4": (25.0, 110.0, 195.0)}
    monkeypatch.setattr(match_grade, "measure_profile", lambda clip, at=None: profs[clip.split("/")[-1]])
    edl = _edl(_ep("d.mp4"), _ep("b.mp4"), _ep("m.mp4"))
    out, target, decisions, _ = match_grade.conduct(edl, "/foot")
    assert target == (25.0, 110.0, 195.0)            # per-anchor median of the three
    assert out.episodes[0].tone_src == (10.0, 90.0, 150.0) and out.episodes[0].tone_dst == target
    assert out.episodes[1].tone_src == (40.0, 130.0, 240.0)
    assert out.episodes[2].tone_src is None          # within eps → no pair, byte-identical
    assert out.episodes[0] == replace(edl.episodes[0], tone_src=(10.0, 90.0, 150.0), tone_dst=target)


def test_conduct_leaves_a_hand_authored_pair(monkeypatch):
    monkeypatch.setattr(match_grade, "measure_profile", lambda clip, at=None: (10.0, 90.0, 150.0))
    edl = _edl(_ep("d.mp4", tone_src=(5.0, 80.0, 140.0), tone_dst=(20.0, 110.0, 210.0)))
    out, _, _, _ = match_grade.conduct(edl, "/foot")
    assert out.episodes[0].tone_src == (5.0, 80.0, 140.0)     # untouched
    assert out.episodes[0] == edl.episodes[0]      # whole episode untouched, not just tone_src


def test_conduct_force_clears_a_now_within_eps_pair(monkeypatch):
    # a previously-authored episode now sits on the median → force removes the stale pair
    profs = {"d.mp4": (25.0, 110.0, 195.0), "b.mp4": (25.0, 110.0, 195.0)}
    monkeypatch.setattr(match_grade, "measure_profile", lambda clip, at=None: profs[clip.split("/")[-1]])
    edl = _edl(_ep("d.mp4", tone_src=(5.0, 80.0, 140.0), tone_dst=(20.0, 110.0, 210.0)), _ep("b.mp4"))
    out, _, _, _ = match_grade.conduct(edl, "/foot", force=True)
    assert out.episodes[0].tone_src is None and out.episodes[0].tone_dst is None


def _write_edl(path, *eps):
    path.write_text(json.dumps(_edl(*eps).to_dict(), indent=2))
    return str(path)


def test_write_match_rewrites_the_edl_and_writes_md(tmp_path, monkeypatch):
    monkeypatch.setattr(match_grade, "measure_profile",
                        lambda clip, at=None: (10.0, 90.0, 150.0) if "d.mp4" in clip
                        else (40.0, 130.0, 240.0))
    ep0, ep1 = _ep("d.mp4"), _ep("b.mp4")
    edl_path = _write_edl(tmp_path / "EDL.json", ep0, ep1)
    status = match_grade.write_match(edl_path, "/foot")
    target = (25.0, 110.0, 195.0)                      # median of the two measured profiles
    assert status == {"status": "written", "edl": edl_path, "md": str(tmp_path / "MATCH.md"),
                      "target": list(target), "eps": matchgrade.MATCH_EPS,
                      "mood": None, "bias_scale": 1.0,     # no --spec: the plain median
                      "authored": 2, "skipped": {}}
    back = EDL.from_json(edl_path)                     # the EDL was rewritten in place
    # attested-run Task 2: match_grade now routes its rewrite through edl.write_edl,
    # so the file on disk carries a fresh, self-consistent stamp — check it, then
    # strip it before the whole-object comparison below (that comparison's own intent
    # predates provenance and is about the EPISODES, not the stamp's exact contents).
    assert provenance.check(back.to_dict())[0] == "intact"
    assert replace(back, provenance={}) == EDL(episodes=(
        replace(ep0, tone_src=(10.0, 90.0, 150.0), tone_dst=target),
        replace(ep1, tone_src=(40.0, 130.0, 240.0), tone_dst=target),
    ))
    md = (tmp_path / "MATCH.md").read_text()
    assert md == (
        "# Match-grade — target 25/110/195 (p5/p50/p95), eps 4\n\n"
        "2/2 episodes authored a tone pair.\n\n"
        "| # | source | measured (p5/p50/p95) | max Δ | action · reason |\n"
        "|---|--------|-----------------------|:-----:|-----------------|\n"
        "| 0 | d.mp4 | 10/90/150 | 45 | author · authored |\n"
        "| 1 | b.mp4 | 40/130/240 | 45 | author · authored |\n"
    )


def test_write_match_reports_skips(tmp_path, monkeypatch):
    monkeypatch.setattr(match_grade, "measure_profile", lambda clip, at=None: (126.0, 128.0, 130.0)
                        if "flat.mp4" in clip else (10.0, 90.0, 150.0))
    edl_path = _write_edl(tmp_path / "EDL.json", _ep("d.mp4"), _ep("flat.mp4"))
    status = match_grade.write_match(edl_path, "/foot")
    assert status["skipped"].get("flat-source") == 1


def test_report_md_renders_every_reason_with_correct_max_delta():
    target = (20.0, 110.0, 210.0)
    decisions = [
        matchgrade.ToneDecision(0, "author", "authored", measured=(10.0, 100.0, 150.0),
                                tone_src=(10.0, 100.0, 150.0), tone_dst=target),
        matchgrade.ToneDecision(1, "skip", "within-eps", measured=(21.0, 111.0, 211.0)),
        matchgrade.ToneDecision(2, "skip", "flat-source", measured=(126.0, 128.0, 130.0)),
        matchgrade.ToneDecision(3, "skip", "hand-authored", measured=(5.0, 80.0, 140.0)),
    ]
    md = match_grade._report_md(["a.mp4", "b.mp4", "c.mp4", "d.mp4"], target, decisions, eps=4.0)
    assert "| 0 | a.mp4 | 10/100/150 | 60 | author · authored |" in md
    assert "| 1 | b.mp4 | 21/111/211 | 1 | skip · within-eps |" in md
    assert "| 2 | c.mp4 | 126/128/130 | 106 | skip · flat-source |" in md
    assert "| 3 | d.mp4 | 5/80/140 | 70 | skip · hand-authored |" in md


def test_cli_build_threads_eps_and_force(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(match_grade, "write_match",
                        lambda edl, footage_root, **k: seen.update(edl=edl, footage_root=footage_root, **k)
                        or {"status": "written", "target": [0, 0, 0], "authored": 0, "skipped": {}})
    monkeypatch.setattr(sys, "argv",
                        ["match_grade", "build", "--edl", "E.json", "--footage-root", "F",
                         "--eps", "6", "--force"])
    with pytest.raises(SystemExit) as e:
        match_grade.main()
    assert e.value.code == 0
    assert seen == {"edl": "E.json", "footage_root": "F", "eps": 6.0, "force": True,
                    "spec": None}


_MOOD_PROFS = {"d.mp4": (10.0, 90.0, 150.0), "b.mp4": (40.0, 130.0, 240.0)}


def _mood_edl(monkeypatch):
    monkeypatch.setattr(match_grade, "measure_profile",
                        lambda clip, at=None: _MOOD_PROFS[clip.split("/")[-1]])
    return _edl(_ep("d.mp4"), _ep("b.mp4"))


def _plain_target():
    return matchgrade.common_target(list(_MOOD_PROFS.values()))


def test_conduct_without_a_spec_authors_the_plain_median(monkeypatch):
    """The anti-regression pin for the off switch: no --spec must reproduce the
    pre-mood conductor exactly, not approximately (design 2026-08-17 §1)."""
    edl = _mood_edl(monkeypatch)
    _, target, _, k = match_grade.conduct(edl, "/foot")
    assert (target, k) == (_plain_target(), 1.0)


def test_conduct_with_a_mood_displaces_the_target(monkeypatch):
    edl = _mood_edl(monkeypatch)
    _, target, _, k = match_grade.conduct(edl, "/foot", preset=moodpreset.resolve("moody"))
    assert (target, k) == matchgrade.biased_target(_plain_target(), (-18.0, -16.0, -8.0))
    assert target != _plain_target()          # the displacement is not a no-op on this fleet


def test_a_balanced_brief_displaces_nothing(monkeypatch):
    """resolve() returned the fallback, so no mood matched — and an unmatched brief
    must not have a grade imposed on it (design §1)."""
    edl = _mood_edl(monkeypatch)
    _, target, _, k = match_grade.conduct(edl, "/foot", preset=moodpreset.BALANCED)
    assert (target, k) == (_plain_target(), 1.0)


def test_the_report_names_the_mood_and_flags_an_ineffective_bias():
    d = matchgrade.ToneDecision(0, "author", "authored", measured=(10.0, 90.0, 150.0),
                                tone_src=(10.0, 90.0, 150.0), tone_dst=(30.0, 80.0, 180.0))
    md = match_grade._report_md(["a.mp4"], (30.0, 80.0, 180.0), [d], 4.0,
                                preset=moodpreset.resolve("epic"), k=5.0 / 16.0)
    assert "epic" in md and "mood-bias-ineffective" in md


def test_the_report_says_when_no_mood_matched():
    d = matchgrade.ToneDecision(0, "skip", "within-eps", measured=(30.0, 80.0, 180.0))
    md = match_grade._report_md(["a.mp4"], (30.0, 80.0, 180.0), [d], 4.0,
                                preset=moodpreset.BALANCED, k=1.0)
    assert "No mood matched" in md and "mood-bias-ineffective" not in md
