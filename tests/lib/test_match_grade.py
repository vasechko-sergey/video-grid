import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import match_grade
from scripts.lib import matchgrade, moodpreset, provenance
from scripts.lib.edl import EDLEpisode, EDL
from scripts.lib.models import EpisodeGeometry, ReelCheckSpec, ReelGeometry
from scripts.lib.spec import Spec


@pytest.fixture(autouse=True)
def _in_a_run_dir(tmp_path, monkeypatch):
    """Every test in this file runs inside its own empty directory.

    `_geo`/`_write_geometry` name their sources and routes RELATIVELY ("s0.mp4",
    "r0.json") and every assertion below reads those strings back, so the files have to
    exist somewhere the CWD reaches: `conduct` calls EpisodeGeometry.require_inputs
    before it measures anything (whole-branch review, minor 5), and a geometry naming
    files that are not on disk is precisely the wiped-build-dir state that guard exists
    to refuse. Chdir-ing rather than absolutising keeps the recorded paths — and the
    whole-object asserts over them — unchanged."""
    monkeypatch.chdir(tmp_path)


def _touch(*names) -> None:
    """Create the named files in the CWD, empty. `measure_crop` is monkeypatched in
    every test here, so nothing ever decodes them — they exist only to satisfy the
    existence guard, which asks whether the pixels are still there, not what is in
    them."""
    for n in names:
        if n is not None:
            Path(n).touch()


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
    for source, route in sources_routes:
        _touch(source, route)
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


@pytest.mark.parametrize("gone", ["s1.mp4", "r1.json"])
def test_conduct_refuses_a_wiped_build_dir_with_a_remedy(gone, monkeypatch):
    """Both halves of the frozen pair, and the routed remedy (whole-branch review,
    minor 5). Without this, conduct fed eg.source straight to ffprobe and a build dir
    wiped in the human gap between the phases surfaced as a bare CalledProcessError
    from inside reframe._probe — while edl_to_reel._refuse_on_missing_inputs and
    probe.source_for both answer the IDENTICAL condition with a remedy.

    The measure is stubbed to raise: this must refuse BEFORE any measuring, not after
    the first episode has already been decoded."""
    def _never(*a, **k):
        raise AssertionError("conduct measured before checking its inputs exist")
    monkeypatch.setattr(match_grade, "measure_crop", _never)
    geo = _geo(("s0.mp4", "r0.json"), ("s1.mp4", "r1.json"))
    Path(gone).unlink()
    with pytest.raises(FileNotFoundError) as e:
        match_grade.conduct(geo, _edl(_ep("d.mp4"), _ep("b.mp4")))
    msg = str(e.value)
    assert "episode 1" in msg and gone in msg
    assert "edl_to_reel --stop-after-geometry" in msg


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
    for i, e in enumerate(eps):
        _touch(e.source, f"r{i}.json")
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
                      "json": str(tmp_path / "MATCH.json"),
                      "target": list(target), "eps": matchgrade.MATCH_EPS,
                      "mood": None, "bias_source": "", "bias_scale": 1.0,  # no --spec: the plain median
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


def test_write_match_stamps_the_mood_biased_target_not_the_median(tmp_path, monkeypatch):
    """grade-shipped-pixels Task 6's missing test: write_match's `spec=` path resolves a
    mood preset and displaces the common target (design 2026-08-17 §1) INSIDE conduct() —
    which reassigns its one local `target` from matchgrade.biased_target, so both
    consumers (the per-episode tone_dst plan() authors, and the EDL.tone_target this
    stamps) read that same variable and cannot diverge today. check_reel's blocking
    gate no longer compares against this stamp at all (design 2026-08-31 renamed it
    grade_faithful and moved its reference to each episode's own predicted chain) —
    but the advisory `target_dev` it still reports (§2.1) reads every BOUND episode's
    PIXELS against EDL.tone_target/ReelManifest.tone_target, so if a future refactor
    ever let the raw median reach that stamp on a mood-biased reel while the render
    still graded toward the biased value, that advisory reading would silently claim
    every episode on the reel agrees with a target it was never graded toward, not
    just this one field.

    Profiles + preset (moody: -18/-16/-8, and moody never scales — biased_target's own
    docstring says so because it pulls inward) are the SAME ones
    test_conduct_with_a_bias_displaces_the_target already uses one level down; picked so
    the median and the biased target differ by MORE than ReelCheckSpec.grade_residual_max —
    discriminating the advisory reading's premise, not float noise."""
    monkeypatch.setattr(match_grade, "measure_crop", lambda md, src, route, **k: _MOOD_PROFS[src])
    geometry_path, edl_path = _write_geometry(tmp_path, _ep("d.mp4"), _ep("b.mp4"))
    spec_path = tmp_path / "SPEC.json"
    spec_path.write_text(json.dumps(
        Spec(canvas=(1080, 1920), length_s=10.0, mood="moody", hook="h").to_dict()))

    median = _plain_target()                                # (25.0, 110.0, 195.0)
    # read from the table (fix round 1 nit), not a hardcoded (-18.0, -16.0, -8.0) pin —
    # a table change would otherwise fail this test as an opaque value mismatch instead
    # of the test tracking whatever "moody" actually asks for today.
    bias = moodpreset.resolve("moody").tone_bias
    biased, k = matchgrade.biased_target(median, bias)
    assert k == 1.0                                          # the full bias survived, nothing scaled away
    worst = max(abs(a - b) for a, b in zip(median, biased))
    assert worst > ReelCheckSpec(target_dur=1.0).grade_residual_max    # > 4.0, or this proves nothing

    status = match_grade.write_match(geometry_path, spec=str(spec_path))

    assert status["target"] == list(biased) and status["mood"] == "moody"
    back = EDL.from_json(edl_path)
    assert back.tone_target == biased                              # the DISPLACED target
    assert back.tone_target != median                              # never the raw median


def test_write_match_prefers_an_authored_tone_bias_over_the_mood_preset(tmp_path, monkeypatch):
    """Fix round 1 (Important finding): every other write_match/spec test in this file
    either omits tone_bias or leaves it None, so write_match's own
    `bias, bias_source = _resolve_bias(spec_obj, preset)` call was never exercised
    end-to-end with BOTH a mood and an authored override present — the exact shape a
    real SPEC.json has. If that call ever reverted to `_resolve_bias(None, preset)`,
    every authored SPEC.tone_bias in production would be silently dropped for the
    preset's taste, and no other test would notice — none of them combine the two.

    Same fixture as test_write_match_stamps_the_mood_biased_target_not_the_median
    (_MOOD_PROFS, median (25.0, 110.0, 195.0)), so the three candidate targets are
    directly comparable, each computed via the real matchgrade.biased_target (not hand
    arithmetic):
      - the plain median:                        (25.0, 110.0, 195.0)
      - what "moody"'s OWN preset bias produces:  (7.0, 94.0, 187.0)   (bias -18/-16/-8)
      - what THIS authored bias produces:         (35.0, 115.0, 175.0) (bias 10/5/-20)
    all three pairwise more than ReelCheckSpec.grade_residual_max (4.0) apart — an
    authored bias that happened to land on the preset's own target (or the median)
    would pass this test against a broken _resolve_bias call and prove nothing."""
    monkeypatch.setattr(match_grade, "measure_crop", lambda md, src, route, **k: _MOOD_PROFS[src])
    geometry_path, edl_path = _write_geometry(tmp_path, _ep("d.mp4"), _ep("b.mp4"))
    authored_bias = (10.0, 5.0, -20.0)
    spec_path = tmp_path / "SPEC.json"
    spec_path.write_text(json.dumps(
        Spec(canvas=(1080, 1920), length_s=10.0, mood="moody", hook="h",
            tone_bias=authored_bias).to_dict()))

    median = _plain_target()                                            # (25.0, 110.0, 195.0)
    moody_bias = moodpreset.resolve("moody").tone_bias
    moody_biased, _ = matchgrade.biased_target(median, moody_bias)       # (7.0, 94.0, 187.0)
    authored_biased, k = matchgrade.biased_target(median, authored_bias)  # (35.0, 115.0, 175.0)
    assert k == 1.0                                                     # nothing scaled away
    # The three candidates must be well separated, or a broken _resolve_bias could land
    # on the wrong one and this test would not notice.
    for a, b in ((median, authored_biased), (moody_biased, authored_biased)):
        assert (max(abs(x - y) for x, y in zip(a, b))
                > ReelCheckSpec(target_dur=1.0).grade_residual_max)

    status = match_grade.write_match(geometry_path, spec=str(spec_path))

    # The AUTHORED bias won, not the mood preset's — and the report says so.
    assert status["target"] == list(authored_biased)
    assert status["target"] != list(moody_biased)
    assert status["mood"] == "moody"                    # the preset was still resolved...
    assert status["bias_source"] == "SPEC.tone_bias"    # ...but its bias was NOT the one used
    back = EDL.from_json(edl_path)
    assert back.tone_target == authored_biased
    assert back.tone_target != moody_biased
    assert back.tone_target != median
    md = (tmp_path / "MATCH.md").read_text()
    assert "SPEC.tone_bias" in md
    assert "the moody preset" not in md


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
    (outer / "d.mp4").touch()
    (outer / "r0.json").touch()     # relative, and resolved after the chdir below
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


def test_conduct_with_a_bias_displaces_the_target(monkeypatch):
    """conduct no longer resolves a preset itself (design 2026-09-03 §2, _resolve_bias) —
    it takes whatever bias the caller hands it; here, a mood's tone_bias fetched directly,
    to prove conduct still threads an arbitrary supplied bias through to the target."""
    geo, edl = _mood_geo_edl(monkeypatch)
    _, target, _, k = match_grade.conduct(geo, edl, bias=moodpreset.resolve("moody").tone_bias)
    assert (target, k) == matchgrade.biased_target(_plain_target(), (-18.0, -16.0, -8.0))
    assert target != _plain_target()          # the displacement is not a no-op on this fleet


def test_report_names_the_preset_source_and_flags_an_ineffective_bias():
    d = matchgrade.ToneDecision(0, "author", "authored", measured=(10.0, 90.0, 150.0),
                                tone_src=(10.0, 90.0, 150.0), tone_dst=(30.0, 80.0, 180.0))
    epic = moodpreset.resolve("epic")
    md = match_grade._report_md(["a.mp4"], (30.0, 80.0, 180.0), [d], 4.0,
                                bias=epic.tone_bias, bias_source=f"the {epic.name} preset",
                                k=5.0 / 16.0)
    assert "epic" in md and "mood-bias-ineffective" in md


def test_resolve_bias_guards_the_balanced_fallback_by_name_not_by_a_zero_vector():
    """Ported to _resolve_bias (design 2026-09-03 §2): conduct no longer knows what a
    preset is, so the balanced-name guard that used to live there now lives only here,
    and this is the only place left that can test it.

    Found by this slice's own mutation battery: dropping the `name != "balanced"` check
    changed NOTHING when tried against the shipped BALANCED.tone_bias, because that
    vector is already zero — so a test built on it proves the zero, not the guard. Hand
    a preset that is NAMED balanced and carries a real displacement: the guard, and only
    the guard, keeps it out.

    This is not hypothetical. BALANCED.look once carried a concrete fade and
    write_edit_plan applied it unconditionally, which put a real picture bookend on
    every autonomous reel (cinematic-look final review I-2). The guard exists so that
    filling this field later cannot repeat it."""
    loud = moodpreset.MoodPreset("balanced", None,
                                 {"close": 0.25, "medium": 0.40, "wide": 0.35}, (1.5, 4.0),
                                 tone_bias=(-18.0, -16.0, -8.0))
    assert match_grade._resolve_bias(None, loud) == ((0.0, 0.0, 0.0), "")


_SPEC = dict(canvas=(9, 16), length_s=30.0, mood="nostalgic warm", hook="open")


def test_resolve_bias_prefers_the_authored_triple_over_the_preset():
    spec = Spec(**{**_SPEC, "tone_bias": (1, 2, 3)})
    preset = moodpreset.resolve("nostalgic warm")
    assert preset.tone_bias != (1.0, 2.0, 3.0)          # the preset really differs
    assert match_grade._resolve_bias(spec, preset) == ((1.0, 2.0, 3.0), "SPEC.tone_bias")


def test_resolve_bias_honours_an_authored_zero_against_a_biased_preset():
    # The whole point of None-vs-zero: this mood, leave my colour alone.
    spec = Spec(**{**_SPEC, "tone_bias": (0, 0, 0)})
    preset = moodpreset.resolve("nostalgic warm")
    assert preset.tone_bias != (0.0, 0.0, 0.0)
    assert match_grade._resolve_bias(spec, preset) == ((0.0, 0.0, 0.0), "SPEC.tone_bias")


def test_resolve_bias_checks_identity_not_truthiness():
    # The test above cannot, by itself, tell `is not None` apart from a bare truthiness
    # check: Spec.tone_bias is always None or a validated 3-tuple, and a 3-tuple of
    # zeros is truthy in Python regardless of its contents, so `if spec.tone_bias:` and
    # `if spec.tone_bias is not None:` agree on every value the dataclass can actually
    # produce (mutation battery row 4, design 2026-09-03 §2 — found not to discriminate).
    # _resolve_bias only reads `.tone_bias` off its argument (no isinstance check), so a
    # duck-typed stand-in carrying a falsy-but-authored value pins the real check.
    class _AuthoredButFalsy:
        tone_bias = ()
    preset = moodpreset.resolve("nostalgic warm")
    assert match_grade._resolve_bias(_AuthoredButFalsy(), preset) == ((), "SPEC.tone_bias")


def test_resolve_bias_falls_back_to_the_preset_when_unauthored():
    spec = Spec(**_SPEC)                                 # tone_bias is None
    preset = moodpreset.resolve("nostalgic warm")
    assert match_grade._resolve_bias(spec, preset) == (preset.tone_bias,
                                                       f"the {preset.name} preset")


def test_resolve_bias_imposes_nothing_for_the_balanced_fallback():
    preset = moodpreset.resolve("no mood word matches this at all")
    assert preset.name == "balanced"
    assert match_grade._resolve_bias(None, preset) == ((0.0, 0.0, 0.0), "")


def test_resolve_bias_is_zero_with_no_spec_and_no_preset():
    assert match_grade._resolve_bias(None, None) == ((0.0, 0.0, 0.0), "")


def test_report_names_the_authored_source():
    md = match_grade._report_md([], (10.0, 100.0, 200.0), [], 4.0,
                                bias=(1.0, 2.0, 3.0), bias_source="SPEC.tone_bias")
    assert "SPEC.tone_bias" in md


def test_report_says_nothing_about_mood_when_no_spec_was_given_at_all():
    # The TRUE no-brief state: no --spec, so write_match never resolves a preset and
    # passes mood=None (its own default). Nothing about mood belongs in the report —
    # there was no brief to have an opinion about. `bias_source == ""` alone cannot
    # tell this apart from "a --spec was given but its mood matched nothing" (the case
    # test_report_names_no_mood_matched_when_the_brief_matched_nothing below covers) —
    # that is the exact ambiguity fix round 1 introduced (final-findings.md I-3) and
    # `mood` exists to resolve.
    md = match_grade._report_md([], (10.0, 100.0, 200.0), [], 4.0,
                                bias=(0.0, 0.0, 0.0), bias_source="", mood=None)
    assert "displaced" not in md
    assert "mood" not in md.lower()


def test_report_names_no_mood_matched_when_the_brief_matched_nothing():
    # Fix round 1 (Important finding I-3): the pre-slice report had an
    # `elif preset is not None:` arm printing this exact line whenever --spec was
    # given but its mood text resolved to NOTHING (moodpreset.resolve fell back to
    # `balanced`, unauthored). The rewrite for SPEC.tone_bias (design 2026-09-03 §2)
    # deleted the arm rather than porting it, reasoning bias_source == "" already
    # covered it — false: that string is IDENTICAL for "no --spec at all" (the test
    # above), so a mood word that quietly failed to resolve became indistinguishable
    # from a brief-less run, exactly the "silently" class this slice exists to close.
    md = match_grade._report_md([], (10.0, 100.0, 200.0), [], 4.0,
                                bias=(0.0, 0.0, 0.0), bias_source="", mood="balanced")
    assert "No mood matched the brief" in md
    assert "displaced" not in md


def test_write_match_reports_no_mood_matched_end_to_end(tmp_path, monkeypatch):
    # The end-to-end proof: a real SPEC.json whose mood text matches no preset (the
    # same "unspecified" string test_edit_plan.py's own housekeeping-task fixture
    # uses for exactly this reason) drives write_match through resolve() -> BALANCED
    # -> _resolve_bias -> "" -> _report_md, and MATCH.md must say so rather than
    # reading like a run with no brief at all.
    monkeypatch.setattr(match_grade, "measure_crop", lambda md, src, route, **k: (20.0, 100.0, 200.0))
    geometry_path, edl_path = _write_geometry(tmp_path, _ep("d.mp4"), _ep("b.mp4"))
    spec_path = tmp_path / "SPEC.json"
    spec_path.write_text(json.dumps(
        Spec(canvas=(1080, 1920), length_s=10.0, mood="unspecified", hook="h").to_dict()))

    status = match_grade.write_match(geometry_path, spec=str(spec_path))

    assert status["mood"] == "balanced" and status["bias_source"] == ""
    md = (tmp_path / "MATCH.md").read_text()
    assert "No mood matched the brief" in md


def test_write_match_writes_a_json_twin_carrying_every_decision(tmp_path, monkeypatch):
    monkeypatch.setattr(match_grade, "measure_crop",
                        lambda md, src, route, **k: (10.0, 90.0, 150.0) if "d.mp4" in src
                        else (40.0, 130.0, 240.0))
    ep0, ep1 = _ep("d.mp4"), _ep("b.mp4")
    geometry_path, edl_path = _write_geometry(tmp_path, ep0, ep1)
    status = match_grade.write_match(geometry_path)
    assert status["json"] == str(tmp_path / "MATCH.json")
    target = (25.0, 110.0, 195.0)
    report = matchgrade.MatchReport.from_json(tmp_path / "MATCH.json")
    assert report == matchgrade.MatchReport(
        target=target, eps=matchgrade.MATCH_EPS, edl=edl_path,
        decisions=(
            matchgrade.ToneDecision(0, "author", "authored", measured=(10.0, 90.0, 150.0),
                                    tone_src=(10.0, 90.0, 150.0), tone_dst=target),
            matchgrade.ToneDecision(1, "author", "authored", measured=(40.0, 130.0, 240.0),
                                    tone_src=(40.0, 130.0, 240.0), tone_dst=target)),
        bias=(0.0, 0.0, 0.0), bias_source="", bias_scale=1.0, mood=None)


def test_the_json_twin_names_the_edl_verbatim_as_geometry_gave_it(tmp_path, monkeypatch):
    """geo.edl is used verbatim, never resolve()d (write_match's own rule) — the twin
    must record the same string, or the freshness reader looks at a different file."""
    monkeypatch.setattr(match_grade, "measure_crop", lambda md, src, route, **k: (10.0, 90.0, 150.0))
    geometry_path, edl_path = _write_geometry(tmp_path, _ep("d.mp4"))
    match_grade.write_match(geometry_path)
    assert matchgrade.MatchReport.from_json(tmp_path / "MATCH.json").edl == edl_path


def test_the_json_twin_names_a_relative_edl_verbatim_not_resolved(tmp_path, monkeypatch):
    """The test above cannot actually tell verbatim apart from resolve()d: tmp_path is
    always already-absolute-and-resolved, so `geo.edl` and `str(Path(geo.edl).resolve())`
    are the same string on that fixture (2026-09-09 task-2 review, minor, deferred to this
    battery — battery row 7 came back GREEN and confirmed it). A RELATIVE edl path does
    discriminate: resolve() turns "EDL.json" into an absolute path, which is not the
    string write_match's own docstring says it stores."""
    monkeypatch.setattr(match_grade, "measure_crop", lambda md, src, route, **k: (10.0, 90.0, 150.0))
    ep0 = _ep("d.mp4")
    Path("EDL.json").write_text(json.dumps(_edl(ep0).to_dict(), indent=2))
    geo = _geo((ep0.source, "r0.json"), edl_path="EDL.json")
    geo.write(tmp_path / "GEOMETRY.json")
    match_grade.write_match(str(tmp_path / "GEOMETRY.json"))
    assert matchgrade.MatchReport.from_json("MATCH.json").edl == "EDL.json"


def test_the_json_twin_records_a_skip_with_its_reason(tmp_path, monkeypatch):
    # a flat source cannot be a tone_src, so the conductor skips it — and a reader must
    # be able to tell that skip from a pair that was wiped after the fact
    monkeypatch.setattr(match_grade, "measure_crop",
                        lambda md, src, route, **k: (10.0, 11.0, 12.0) if "d.mp4" in src
                        else (40.0, 130.0, 240.0))
    geometry_path, _ = _write_geometry(tmp_path, _ep("d.mp4"), _ep("b.mp4"))
    match_grade.write_match(geometry_path)
    report = matchgrade.MatchReport.from_json(tmp_path / "MATCH.json")
    assert (report.decisions[0].action, report.decisions[0].reason) == ("skip", "flat-source")
    assert report.decisions[0].tone_src is None


def test_the_json_twin_carries_the_mood_displacement(tmp_path, monkeypatch):
    monkeypatch.setattr(match_grade, "measure_crop", lambda md, src, route, **k: (10.0, 90.0, 150.0))
    geometry_path, _ = _write_geometry(tmp_path, _ep("d.mp4"))
    spec = tmp_path / "SPEC.json"
    # canvas/hook added (task-2-report.md): Spec.__post_init__ gates both as
    # required (scripts/lib/spec.py) — the brief's dict omitted them, which
    # raises "Spec.canvas must be [w, h] positive, got None" before write_match
    # ever reaches the mood/bias assertions below.
    spec.write_text(json.dumps({"idea": "a calm ride", "mood": "nostalgic", "length_s": 30.0,
                                "canvas": [1080, 1920], "hook": "h"}))
    match_grade.write_match(geometry_path, spec=str(spec))
    report = matchgrade.MatchReport.from_json(tmp_path / "MATCH.json")
    assert (report.mood, report.bias_source) == ("nostalgic", "the nostalgic preset")
    assert report.bias == moodpreset.resolve("nostalgic").tone_bias
