import json
import sys
from dataclasses import replace

import pytest

from scripts import match_grade
from scripts.lib import matchgrade, moodpreset, provenance
from scripts.lib.edl import EDLEpisode, EDL
from scripts.lib.models import EpisodeGeometry, ReelGeometry


def _ep(source, start=0.0, dur=2.0, **kw):
    return EDLEpisode(source=source, start=start, dur=dur, shot_type="wide",
                      composition="center", grid="thirds", **kw)


def _edl(*eps):
    return EDL(episodes=tuple(eps))


def _geo(*sources_routes, edl_path="EDL.json"):
    """A ReelGeometry in memory — no disk IO — for tests that call `conduct` directly.
    `sources_routes` is a list of (source, route) pairs, one per episode, in EDL order
    (design 2026-08-30 §2.2: geo.episodes[i] is edl.episodes[i]'s frozen geometry). The
    manifest is irrelevant to every test in this file except the pan/measure_crop
    integration proof (tests/integration/test_color_measure.py) — measure_crop itself
    is monkeypatched here, so an empty dict satisfies EpisodeGeometry's own guard."""
    return ReelGeometry(episodes=tuple(
        EpisodeGeometry(manifest={}, route=route, source=source, project_dir=f"p{i}")
        for i, (source, route) in enumerate(sources_routes)),
        edl=edl_path)


def test_conduct_measures_every_episode_crop(monkeypatch):
    """One measure_crop call per episode, with that episode's own route."""
    seen = []
    monkeypatch.setattr(match_grade, "measure_crop",
                        lambda md, src, route, **k: seen.append((src, route)) or (20.0, 100.0, 200.0))
    geo = _geo(("s0.mp4", "r0.json"), ("s1.mp4", "r1.json"))
    edl = _edl(_ep("d.mp4"), _ep("b.mp4"))
    match_grade.conduct(geo, edl)
    assert seen == [("s0.mp4", "r0.json"), ("s1.mp4", "r1.json")]


def test_conduct_authors_deviating_and_leaves_near_median(monkeypatch):
    # ep0 dark, ep1 bright → median between; ep2 sits on the median (within eps)
    profs = {"d.mp4": (10.0, 90.0, 150.0), "b.mp4": (40.0, 130.0, 240.0),
             "m.mp4": (25.0, 110.0, 195.0)}
    monkeypatch.setattr(match_grade, "measure_crop", lambda md, src, route, **k: profs[src])
    geo = _geo(("d.mp4", "r0.json"), ("b.mp4", "r1.json"), ("m.mp4", "r2.json"))
    edl = _edl(_ep("d.mp4"), _ep("b.mp4"), _ep("m.mp4"))
    out, target, decisions, _ = match_grade.conduct(geo, edl)
    assert target == (25.0, 110.0, 195.0)            # per-anchor median of the three
    assert out.episodes[0].tone_src == (10.0, 90.0, 150.0) and out.episodes[0].tone_dst == target
    assert out.episodes[1].tone_src == (40.0, 130.0, 240.0)
    assert out.episodes[2].tone_src is None          # within eps → no pair, byte-identical
    assert out.episodes[0] == replace(edl.episodes[0], tone_src=(10.0, 90.0, 150.0), tone_dst=target)


def test_conduct_leaves_a_hand_authored_pair(monkeypatch):
    monkeypatch.setattr(match_grade, "measure_crop", lambda md, src, route, **k: (10.0, 90.0, 150.0))
    geo = _geo(("d.mp4", "r0.json"))
    edl = _edl(_ep("d.mp4", tone_src=(5.0, 80.0, 140.0), tone_dst=(20.0, 110.0, 210.0)))
    out, _, _, _ = match_grade.conduct(geo, edl)
    assert out.episodes[0].tone_src == (5.0, 80.0, 140.0)     # untouched
    assert out.episodes[0] == edl.episodes[0]      # whole episode untouched, not just tone_src


def test_conduct_force_clears_a_now_within_eps_pair(monkeypatch):
    # a previously-authored episode now sits on the median → force removes the stale pair
    profs = {"d.mp4": (25.0, 110.0, 195.0), "b.mp4": (25.0, 110.0, 195.0)}
    monkeypatch.setattr(match_grade, "measure_crop", lambda md, src, route, **k: profs[src])
    geo = _geo(("d.mp4", "r0.json"), ("b.mp4", "r1.json"))
    edl = _edl(_ep("d.mp4", tone_src=(5.0, 80.0, 140.0), tone_dst=(20.0, 110.0, 210.0)), _ep("b.mp4"))
    out, _, _, _ = match_grade.conduct(geo, edl, force=True)
    assert out.episodes[0].tone_src is None and out.episodes[0].tone_dst is None


def test_conduct_no_longer_reads_the_footage_root():
    """Anti-regression pin for the breaking CLI/API change (design 2026-08-30 §3): the
    whole-frame mode and its footage_root parameter are DELETED, not defaulted away."""
    with pytest.raises(TypeError):
        match_grade.write_match("EDL.json", footage_root="/anywhere")


def _write_geometry(tmp_path, *eps):
    """Write EDL.json + a GEOMETRY.json naming it, with one trivial (source, route) pair
    per episode in EDL order. Returns (geometry_path, edl_path), both str."""
    edl_path = tmp_path / "EDL.json"
    edl_path.write_text(json.dumps(_edl(*eps).to_dict(), indent=2))
    geo = ReelGeometry(episodes=tuple(
        EpisodeGeometry(manifest={}, route=f"r{i}.json", source=e.source, project_dir=f"p{i}")
        for i, e in enumerate(eps)),
        edl=str(edl_path))
    geometry_path = tmp_path / "GEOMETRY.json"
    geo.write(geometry_path)
    return str(geometry_path), str(edl_path)


def test_write_match_rewrites_the_edl_and_writes_md(tmp_path, monkeypatch):
    monkeypatch.setattr(match_grade, "measure_crop",
                        lambda md, src, route, **k: (10.0, 90.0, 150.0) if "d.mp4" in src
                        else (40.0, 130.0, 240.0))
    ep0, ep1 = _ep("d.mp4"), _ep("b.mp4")
    geometry_path, edl_path = _write_geometry(tmp_path, ep0, ep1)
    status = match_grade.write_match(geometry_path)
    target = (25.0, 110.0, 195.0)                      # median of the two measured profiles
    assert status == {"status": "written", "edl": edl_path, "md": str(tmp_path / "MATCH.md"),
                      "target": list(target), "eps": matchgrade.MATCH_EPS,
                      "mood": None, "bias_scale": 1.0,     # no --spec: the plain median
                      "authored": 2, "skipped": {}}
    back = EDL.from_json(edl_path)                     # the EDL was rewritten in place
    assert back.tone_target == target
    # attested-run Task 2: match_grade now routes its rewrite through edl.write_edl,
    # so the file on disk carries a fresh, self-consistent stamp — check it, then
    # strip it (and the new tone_target, checked above) before the whole-object
    # comparison below (that comparison's own intent predates both fields and is
    # about the EPISODES, not the stamp's or the reel target's exact contents).
    assert provenance.check(back.to_dict())[0] == "intact"
    assert replace(back, provenance={}, tone_target=None) == EDL(episodes=(
        replace(ep0, tone_src=(10.0, 90.0, 150.0), tone_dst=target),
        replace(ep1, tone_src=(40.0, 130.0, 240.0), tone_dst=target),
    ))
    md = (tmp_path / "MATCH.md").read_text()
    assert md == (
        "# Match-grade — target 25/110/195 (p5/p50/p95), eps 4\n\n"
        "Measured on each episode's own tracked crop, 3 frames per episode "
        "(design 2026-08-30 §1) — not the whole source frame.\n\n"
        "2/2 episodes authored a tone pair.\n\n"
        "| # | source | measured (p5/p50/p95) | max Δ | action · reason |\n"
        "|---|--------|-----------------------|:-----:|-----------------|\n"
        "| 0 | d.mp4 | 10/90/150 | 45 | author · authored |\n"
        "| 1 | b.mp4 | 40/130/240 | 45 | author · authored |\n"
    )


def test_write_match_stamps_the_tone_target_on_the_edl(tmp_path, monkeypatch):
    """The gate of design §6 needs ONE number for the reel; deriving it from the
    episodes' own tone_dst would fail on the reel where every episode was skipped."""
    monkeypatch.setattr(match_grade, "measure_crop", lambda md, src, route, **k: (20.0, 100.0, 200.0))
    geometry_path, edl_path = _write_geometry(tmp_path, _ep("d.mp4"), _ep("b.mp4"))
    match_grade.write_match(geometry_path)
    assert EDL.from_json(str(edl_path)).tone_target == (20.0, 100.0, 200.0)


def test_write_match_does_not_resolve_the_geometrys_edl_path(tmp_path, monkeypatch):
    """geo.edl is stored VERBATIM (design 2026-08-30 §2.2, matching how
    edl_to_reel.render_from_geometry already reads it) — resolving it against
    GEOMETRY.json's own directory would silently read a DIFFERENT file the day the
    two are not siblings. Here they are not: EDL.json lives beside the CURRENT
    directory (`outer`), GEOMETRY.json lives in a sibling (`inner`), and geo.edl
    names the EDL only as \"EDL.json\" — a relative path that resolves correctly
    ONLY if nothing joins it against inner first."""
    monkeypatch.setattr(match_grade, "measure_crop", lambda md, src, route, **k: (20.0, 100.0, 200.0))
    outer, inner = tmp_path / "outer", tmp_path / "inner"
    outer.mkdir()
    inner.mkdir()
    edl_path = outer / "EDL.json"
    edl_path.write_text(json.dumps(_edl(_ep("d.mp4")).to_dict(), indent=2))
    geo = ReelGeometry(episodes=(EpisodeGeometry(manifest={}, route="r0.json",
                                                 source="d.mp4", project_dir="p0"),),
                       edl="EDL.json")           # relative — resolves against the CWD
    geometry_path = inner / "GEOMETRY.json"
    geo.write(geometry_path)
    monkeypatch.chdir(outer)                     # geo.edl must resolve from HERE, not `inner`
    match_grade.write_match(str(geometry_path))
    assert EDL.from_json(str(edl_path)).tone_target == (20.0, 100.0, 200.0)


def test_write_match_reports_skips(tmp_path, monkeypatch):
    monkeypatch.setattr(match_grade, "measure_crop",
                        lambda md, src, route, **k: (126.0, 128.0, 130.0)
                        if "flat.mp4" in src else (10.0, 90.0, 150.0))
    geometry_path, _ = _write_geometry(tmp_path, _ep("d.mp4"), _ep("flat.mp4"))
    status = match_grade.write_match(geometry_path)
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


def test_cli_build_threads_eps_and_force(monkeypatch):
    seen = {}
    monkeypatch.setattr(match_grade, "write_match",
                        lambda geometry, **k: seen.update(geometry=geometry, **k)
                        or {"status": "written", "target": [0, 0, 0], "authored": 0, "skipped": {}})
    monkeypatch.setattr(sys, "argv",
                        ["match_grade", "build", "--geometry", "G.json",
                         "--eps", "6", "--force"])
    with pytest.raises(SystemExit) as e:
        match_grade.main()
    assert e.value.code == 0
    assert seen == {"geometry": "G.json", "eps": 6.0, "force": True, "spec": None}


_MOOD_PROFS = {"d.mp4": (10.0, 90.0, 150.0), "b.mp4": (40.0, 130.0, 240.0)}


def _mood_geo_edl(monkeypatch):
    monkeypatch.setattr(match_grade, "measure_crop", lambda md, src, route, **k: _MOOD_PROFS[src])
    geo = _geo(("d.mp4", "r0.json"), ("b.mp4", "r1.json"))
    return geo, _edl(_ep("d.mp4"), _ep("b.mp4"))


def _plain_target():
    return matchgrade.common_target(list(_MOOD_PROFS.values()))


def test_conduct_without_a_spec_authors_the_plain_median(monkeypatch):
    """The anti-regression pin for the off switch: no --spec must reproduce the
    pre-mood conductor exactly, not approximately (design 2026-08-17 §1)."""
    geo, edl = _mood_geo_edl(monkeypatch)
    _, target, _, k = match_grade.conduct(geo, edl)
    assert (target, k) == (_plain_target(), 1.0)


def test_conduct_with_a_mood_displaces_the_target(monkeypatch):
    geo, edl = _mood_geo_edl(monkeypatch)
    _, target, _, k = match_grade.conduct(geo, edl, preset=moodpreset.resolve("moody"))
    assert (target, k) == matchgrade.biased_target(_plain_target(), (-18.0, -16.0, -8.0))
    assert target != _plain_target()          # the displacement is not a no-op on this fleet


def test_a_balanced_brief_displaces_nothing(monkeypatch):
    """resolve() returned the fallback, so no mood matched — and an unmatched brief
    must not have a grade imposed on it (design §1)."""
    geo, edl = _mood_geo_edl(monkeypatch)
    _, target, _, k = match_grade.conduct(geo, edl, preset=moodpreset.BALANCED)
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


def test_the_balanced_guard_is_tested_by_name_not_by_a_zero_vector(monkeypatch):
    """Found by this slice's own mutation battery: dropping the `name != "balanced"`
    check changed NOTHING, because the shipped BALANCED.tone_bias is already zero — so
    the test above proves the zero, not the guard. Hand a preset that is NAMED balanced
    and carries a real displacement: the guard, and only the guard, keeps it out.

    This is not hypothetical. BALANCED.look once carried a concrete fade and
    write_edit_plan applied it unconditionally, which put a real picture bookend on
    every autonomous reel (cinematic-look final review I-2). The guard exists so that
    filling this field later cannot repeat it."""
    geo, edl = _mood_geo_edl(monkeypatch)
    loud = moodpreset.MoodPreset("balanced", None,
                                 {"close": 0.25, "medium": 0.40, "wide": 0.35}, (1.5, 4.0),
                                 tone_bias=(-18.0, -16.0, -8.0))
    _, target, _, k = match_grade.conduct(geo, edl, preset=loud)
    assert (target, k) == (_plain_target(), 1.0)
