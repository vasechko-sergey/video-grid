import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import probe
from scripts.lib import gradedamage
from scripts.lib.edl import EDL, EDLEpisode, write_edl
from scripts.lib.models import EpisodeGeometry, ReelEpisode, ReelGeometry, ReelManifest


def _md(**over) -> dict:
    md = {"segment": "seg.mp4", "out_path": "o.mp4", "target_dur": 2.0,
          "composition": "lead", "grid": "thirds", "canvas": [9, 16],
          "color_means": [110.0, 120.0, 130.0], "delivery": "short_edge:540",
          "white_balance": 0.0, "black_point": 0.0, "highlight": 1.0,
          "saturation": 1.0, "shadow_red": 0.0, "mid_blue": 1.0, "dip": 0.0,
          "highlight_red": 0.25, "tone_src": [18.0, 110.0, 220.0],
          "tone_dst": [26.0, 118.0, 210.0]}
    md.update(over)
    return md


def _edl_dict(**over) -> dict:
    # The minimum EDLEpisode.from_dict (via EDLEpisode(**e)) actually accepts:
    # source/start/dur/shot_type/composition/grid are the only fields with no
    # dataclass default (scripts/lib/edl.py EDLEpisode). "clip" is not a field name
    # (it's "source"), and shot_type has no default either — both are required here
    # even though this test only cares about the colour block.
    ep = {"source": "c.mp4", "start": 0.0, "dur": 2.0, "shot_type": "wide",
          "composition": "lead", "grid": "thirds"}
    ep.update(over)
    return {"episodes": [ep], "target_dur": 2.0}


def test_source_for_returns_the_segment_without_stabilize(tmp_path):
    assert probe.source_for(_md(), tmp_path) == "seg.mp4"


def test_source_for_returns_the_prestage_output_under_stabilize(tmp_path):
    (tmp_path / "stabilized.mp4").write_bytes(b"x")
    assert probe.source_for(_md(stabilize=True), tmp_path) == str(tmp_path / "stabilized.mp4")


def test_source_for_refuses_a_missing_prestage_output(tmp_path):
    """reframe consumed the stabilized file. Falling back to the raw segment would
    render pixels the episode never shipped, and say nothing about it."""
    with pytest.raises(FileNotFoundError, match="stabilize"):
        probe.source_for(_md(stabilize=True), tmp_path)


def test_regrade_drops_a_colour_field_the_author_deleted(tmp_path):
    """to_manifest_dict omits highlight_red at its identity, so a plain merge would
    keep the OLD value and the probe would show a grade the next render will not."""
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps(_edl_dict()))
    out = probe.regrade(_md(), str(p), 0)
    assert out["highlight_red"] == 0.0
    assert out["segment"] == "seg.mp4"          # non-colour keys survive


def test_regrade_drops_a_deleted_tone_pair(tmp_path):
    """to_manifest_dict emits tone_src/tone_dst only as a pair and only when authored,
    so an author who deletes the pair (the EDL episode below authors neither) must see
    it gone from the probe's grade too — not the tone pair `_md()` used to carry."""
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps(_edl_dict()))       # no tone_src/tone_dst authored
    out = probe.regrade(_md(), str(p), 0)
    assert out["tone_src"] is None and out["tone_dst"] is None


def test_regrade_refuses_an_index_past_the_edl(tmp_path):
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps(_edl_dict()))
    with pytest.raises(IndexError, match="out of range"):
        probe.regrade(_md(), str(p), 3)


def _stamped_edl(path: Path, **ep_over) -> None:
    """A write_edl-stamped EDL.json — the shape the pipeline actually hands the
    probe: edit_plan.write_edit_plan always routes through write_edl, so every
    EDL.json a real run produces carries a provenance stamp (design 2026-08-04)."""
    ep = {"source": "c.mp4", "start": 0.0, "dur": 2.0, "shot_type": "wide",
          "composition": "lead", "grid": "thirds"}
    ep.update(ep_over)
    write_edl(EDL(episodes=(EDLEpisode(**ep),)), path)


def test_regrade_reads_a_write_edl_stamped_edl(tmp_path):
    """The stamp itself must never be mistaken for tampering — only a stamp that no
    longer matches its own contents is (final review C1)."""
    p = tmp_path / "EDL.json"
    _stamped_edl(p, highlight_red=0.3)
    out = probe.regrade(_md(), str(p), 0)
    assert out["highlight_red"] == 0.3
    assert out["segment"] == "seg.mp4"          # non-colour keys survive


def test_regrade_refuses_a_hand_edited_stamped_edl_naming_the_probe_loop(tmp_path):
    """Reproduces the documented convergence loop's OLD failure mode (final review
    C1): EDL.json is stamped, then hand-edited — exactly what the SKILL used to
    instruct before this fix. EDL.from_json's tamper refusal must survive through
    regrade, but naming the probe's actual remedy (selection.json + edit_plan
    build), not just the generic edit_plan-build pointer the design layer's own
    message already gives."""
    p = tmp_path / "EDL.json"
    _stamped_edl(p)
    d = json.loads(p.read_text())
    d["episodes"][0]["white_balance"] = 0.9      # edited after the stamp, stamp untouched
    p.write_text(json.dumps(d))
    with pytest.raises(ValueError, match="selection.json") as exc:
        probe.regrade(_md(), str(p), 0)
    assert "edit_plan build" in str(exc.value)


def _fake_render():
    """A stand-in for probe._render: one tiny black RGB frame per requested time, with
    no ffmpeg call at all — this file (tests/lib) stays fast and hermetic; the
    real-pixel proof that a probe's frames match the encode lives in
    tests/integration/test_probe.py and Task 8's real-ffmpeg battery. Creates `d`
    itself, exactly as the real _render does (probe_grade/probe_grade_geometry both
    write probe.json into it right after)."""
    def _render(plan, src, times, d):
        d.mkdir(parents=True, exist_ok=True)
        return [np.zeros((2, 2, 3), dtype=np.uint8) for _ in times]
    return _render


def _fake_plan_frames_rgb():
    """A stand-in for reframe.plan_frames_rgb — Task 8's probe_grade/probe_grade_geometry
    call this a second time, on the UNGRADED plan, to build grade_damage's `plain` half.
    process_episode.plan_ungraded reaches reframe.plan_render internally too (patched
    below onto the shared reframe module both probe.py and process_episode.py import,
    so plan_ungraded's plan is the SAME fake_plan object plan_render already returns),
    but that fake plan carries none of a real RenderPlan's fields (fps, path, rl, ...)
    that plan_frames_rgb needs — so this fakes the read itself, exactly as _render
    fakes the graded one. All-zero (flat) frames are fine: neither test below asserts
    on grade_damage's content, and gradedamage.evaluate already has a defined,
    non-crashing answer for an all-flat plain half ({"status": "not-checked", ...})."""
    def _pfr(plan, src, times):
        return [np.zeros((2, 2, 3), dtype=np.uint8) for _ in times]
    return _pfr


def test_probe_grade_from_geometry_needs_no_episodes_json(tmp_path, monkeypatch):
    """probe_grade_geometry works from GEOMETRY.json alone — no EPISODES.json ever
    exists before the first encode (design §4) — and always applies the EDL's
    CURRENT colour block (there is no 'grade that was rendered' to fall back to)."""
    edl_path = tmp_path / "EDL.json"
    _stamped_edl(edl_path, highlight_red=0.3)
    # the source is named relatively and EpisodeGeometry.require_inputs resolves it
    # against the CWD, so this test runs where it says its pixels are
    monkeypatch.chdir(tmp_path)
    (tmp_path / "seg.mp4").touch()
    geo = ReelGeometry(
        episodes=(EpisodeGeometry(manifest=_md(), route=None, source="seg.mp4",
                                  project_dir=str(tmp_path)),),
        edl=str(edl_path))
    geo_path = tmp_path / "GEOMETRY.json"
    geo.write(geo_path)

    fake_plan = SimpleNamespace(dur=2.0, grade="")
    monkeypatch.setattr(probe.reframe, "plan_render", lambda *a, **k: fake_plan)
    monkeypatch.setattr(probe.reframe, "plan_frames_rgb", _fake_plan_frames_rgb())
    monkeypatch.setattr(probe, "_render", _fake_render())
    monkeypatch.setattr(probe.color_measure, "crop_percentiles",
                        lambda *a, **k: (10.0, 20.0, 30.0))

    r = probe.probe_grade_geometry(str(geo_path), 0, out_dir=str(tmp_path / "p"))
    assert r["frames"] == 3
    assert r["source"] == "seg.mp4"
    assert r["drift_checked"] is False           # no path.json exists yet — the plan
                                                 # IS the source of truth; --episodes
                                                 # mode keeps the oracle instead
    assert r["colour"]["highlight_red"] == 0.3   # the EDL's CURRENT block, not
                                                 # eg.manifest's stripped identity


def test_probe_grade_geometry_refuses_an_edl_stamp_it_did_not_write(tmp_path, monkeypatch):
    """geo.edl is read VERBATIM through the same regrade probe_grade uses — the tamper
    refusal must survive here exactly as it does for --episodes/--edl."""
    edl_path = tmp_path / "EDL.json"
    _stamped_edl(edl_path)
    d = json.loads(edl_path.read_text())
    d["episodes"][0]["white_balance"] = 0.9
    edl_path.write_text(json.dumps(d))
    geo = ReelGeometry(
        episodes=(EpisodeGeometry(manifest=_md(), route=None, source="seg.mp4",
                                  project_dir=str(tmp_path)),),
        edl=str(edl_path))
    geo_path = tmp_path / "GEOMETRY.json"
    geo.write(geo_path)
    with pytest.raises(ValueError, match="selection.json"):
        probe.probe_grade_geometry(str(geo_path), 0, out_dir=str(tmp_path / "p"))


def test_probe_reports_the_gray_ruler(tmp_path, monkeypatch):
    """probe.json's tone must be the number the conductor authored and the gate
    reads — measured, the RGB/BT.601 ruler differs by up to 6 codes (design §0.5)."""
    ep = ReelEpisode(manifest=_md(), clip="o.mp4", route=None,
                     path=str(tmp_path / "path.json"), meta=str(tmp_path / "path.meta.json"))
    ep_json = tmp_path / "EPISODES.json"
    ReelManifest(episodes=[ep], target_dur=2.0).write(ep_json)

    fake_plan = SimpleNamespace(dur=2.0, grade="")
    monkeypatch.setattr(probe.reframe, "plan_render", lambda *a, **k: fake_plan)
    monkeypatch.setattr(probe.reframe, "plan_frames_rgb", _fake_plan_frames_rgb())
    monkeypatch.setattr(probe, "_refuse_on_drift", lambda *a, **k: None)
    monkeypatch.setattr(probe, "_render", _fake_render())
    calls = []
    monkeypatch.setattr(probe.color_measure, "crop_percentiles",
                        lambda *a, **k: calls.append(a) or (1.0, 2.0, 3.0))

    r = probe.probe_grade(str(ep_json), 0, out_dir=str(tmp_path / "out"))
    assert r["tone_profile"] == [1.0, 2.0, 3.0] and calls


def test_predicted_profile_ignores_frames_but_tone_profile_does_not(tmp_path, monkeypatch):
    """Task 8 fix round 1, Minor 2. predicted_profile must always be build_reel._predict's
    OWN recipe (color_measure.crop_percentiles at color.sample_times' DEFAULT count) —
    never moved by --frames, or a probe run with a non-default --frames would silently
    report a number check_reel.grade_faithful (via _predict) was never going to compare
    against. tone_profile, by contrast, IS supposed to move with --frames: it describes
    the stills THIS call rendered, and narrowing/widening that set is the whole point of
    the knob.

    The mock keys its answer on len(times) rather than returning one fixed tuple, which
    is what makes this discriminate: a wrong implementation that (again) used `tone` for
    predicted_profile would report the WIDENED reading for both fields, not just
    tone_profile — a mock returning a single constant regardless of args could not
    tell the two calls apart."""
    ep = ReelEpisode(manifest=_md(), clip="o.mp4", route=None,
                     path=str(tmp_path / "path.json"), meta=str(tmp_path / "path.meta.json"))
    ep_json = tmp_path / "EPISODES.json"
    ReelManifest(episodes=[ep], target_dur=2.0).write(ep_json)

    fake_plan = SimpleNamespace(dur=2.0, grade="")
    monkeypatch.setattr(probe.reframe, "plan_render", lambda *a, **k: fake_plan)
    monkeypatch.setattr(probe.reframe, "plan_frames_rgb", _fake_plan_frames_rgb())
    monkeypatch.setattr(probe, "_refuse_on_drift", lambda *a, **k: None)
    monkeypatch.setattr(probe, "_render", _fake_render())

    def _by_sample_count(plan, src, times):
        return (9.0, 9.0, 9.0) if len(times) != 3 else (1.0, 2.0, 3.0)
    monkeypatch.setattr(probe.color_measure, "crop_percentiles", _by_sample_count)

    r = probe.probe_grade(str(ep_json), 0, out_dir=str(tmp_path / "out"), frames=7)
    assert len(r["times"]) == 7                    # the widened request really landed
    assert r["tone_profile"] == [9.0, 9.0, 9.0]    # the widened (7-sample) reading
    assert r["predicted_profile"] == [1.0, 2.0, 3.0]   # ALWAYS the default (3-sample) one


# --- threshold-surface Task 5: the probe predicts against the bar the gate will use ---
# probe.py read CheckSpec's dataclass default for entropy_floor directly, which the design's
# census of CheckSpec( call sites could not see because nothing here constructs one. A prediction
# made against a different bar than the gate will use is the cry-wolf mechanism with the sign
# flipped: a tool that says "this will fail" about a render that will pass (design §2.3).

def _gray(values: np.ndarray) -> np.ndarray:
    return np.stack([values] * 3, axis=-1)


def _damage_pair() -> tuple[np.ndarray, np.ndarray]:
    """Gray frames whose luma entropy falls from 7.95 to 4.995 bits when 3 bits are dropped:
    a ratio of 0.628 — BELOW CheckSpec's default floor (0.90) and ABOVE the 0.5 authored below,
    so the verdict itself says which bar was used. Measured, not assumed."""
    v = np.random.default_rng(7).integers(0, 256, (64, 64), dtype=np.uint8)
    return _gray(v), _gray(v // 8 * 8)


def _fake_pair_render(monkeypatch):
    """probe's two frame readers over a pair whose entropy ratio is known: `_render` yields the
    graded half and plan_frames_rgb the plain one, exactly the roles they play in the real call."""
    plain, graded = _damage_pair()
    assert gradedamage.evaluate(plain=[plain], graded=[graded], floor=0.9)["ratio"] == 0.628

    def render(plan, src, times, d):
        d.mkdir(parents=True, exist_ok=True)
        return [graded for _ in times]
    monkeypatch.setattr(probe, "_render", render)
    monkeypatch.setattr(probe.reframe, "plan_frames_rgb",
                        lambda plan, src, times: [plain for _ in times])
    monkeypatch.setattr(probe.reframe, "plan_render",
                        lambda *a, **k: SimpleNamespace(dur=2.0, grade=""))
    monkeypatch.setattr(probe.color_measure, "crop_percentiles",
                        lambda *a, **k: (10.0, 20.0, 30.0))


_FLOOR_GATE = {"entropy_floor": {"value": 0.5, "why": "log profile"}}


def test_probe_grade_predicts_against_the_floor_the_episodes_froze(tmp_path, monkeypatch):
    """The manifest's own `gates` is the set that judged these clips, so it is the bar the
    prediction must use. The control is inside the test: the SAME frames against a manifest that
    authored nothing fail at the default, so the authored run passing is the floor and nothing
    else. `below` and not merely `floor` is asserted, because a floor reported and ignored would
    still print the right number."""
    _fake_pair_render(monkeypatch)
    monkeypatch.setattr(probe, "_refuse_on_drift", lambda *a, **k: None)
    ep = ReelEpisode(manifest=_md(), clip="o.mp4", route=None,
                     path=str(tmp_path / "path.json"), meta=str(tmp_path / "path.meta.json"))
    verdicts = {}
    for label, gates in (("authored", _FLOOR_GATE), ("default", {})):
        ep_json = tmp_path / f"{label}.json"
        ReelManifest(episodes=[ep], target_dur=2.0, gates=gates).write(ep_json)
        damage = probe.probe_grade(str(ep_json), 0, out_dir=str(tmp_path / label))["grade_damage"]
        verdicts[label] = (damage["floor"], damage["below"])
    assert verdicts == {"authored": (0.5, False), "default": (0.9, True)}


def _geometry(tmp_path, monkeypatch, project: str) -> str:
    """A GEOMETRY.json recording `project`, over the same faked render as above."""
    edl_path = tmp_path / "EDL.json"
    _stamped_edl(edl_path)
    monkeypatch.chdir(tmp_path)          # the source is named relatively; see the test above
    (tmp_path / "seg.mp4").touch()
    geo = ReelGeometry(
        episodes=(EpisodeGeometry(manifest=_md(), route=None, source="seg.mp4",
                                  project_dir=str(tmp_path)),),
        edl=str(edl_path), project=project)
    geo_path = tmp_path / "GEOMETRY.json"
    geo.write(geo_path)
    _fake_pair_render(monkeypatch)
    return str(geo_path)


def test_probe_geometry_reads_the_gates_beside_the_project_geometry_recorded(
        tmp_path, monkeypatch):
    """No EPISODES.json exists before the first encode, so the set is found the way phase 1b
    will find it: beside the project. The decoy in the working directory authors 0.99, which
    would FAIL this pair — the opposite of the 0.5 beside the project — so a lookup that strays
    there reads the wrong file instead of reading nothing. The control is inside: with no file
    beside the project the same pair fails at the default, and nothing is named, because
    nothing was unread."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "project.json").write_text("{}")
    (tmp_path / "GATES.json").write_text(json.dumps(
        {"entropy_floor": {"value": 0.99, "why": "a decoy: the working directory"}}))
    geo = _geometry(tmp_path, monkeypatch, str(run / "project.json"))

    (run / "GATES.json").write_text(json.dumps(_FLOOR_GATE))
    r = probe.probe_grade_geometry(geo, 0, out_dir=str(tmp_path / "a"))
    assert (r["grade_damage"]["floor"], r["grade_damage"]["below"]) == (0.5, False)
    assert "gates" not in r

    (run / "GATES.json").unlink()
    r = probe.probe_grade_geometry(geo, 0, out_dir=str(tmp_path / "b"))
    assert (r["grade_damage"]["floor"], r["grade_damage"]["below"]) == (0.9, True)
    assert "gates" not in r


@pytest.mark.parametrize("recorded, why", [
    ("", "GEOMETRY.json records no project"),
    ("gone/project.json", "gone/project.json does not resolve from here"),
    ("project.json", "project.json does not resolve from here"),
], ids=["none-recorded", "moved", "bare-relative"])
def test_probe_geometry_names_the_absence_when_it_cannot_look_for_the_gates(
        tmp_path, monkeypatch, recorded, why):
    """geo.project may not resolve from here: nothing recorded at all (a GEOMETRY.json from
    before the field), a project that has since moved, or a bare relative name read from another
    working directory. In each the gates cannot even be LOOKED FOR, so a prediction against the
    default floor would read "no gates authored" — a statement nobody made. It is still made, at
    the default, but the report says it was unread and why (design §2.3; match_grade._find_regions
    states the same three). The bare relative case is whole-branch-review finding 2 there: the
    parent of "project.json" is ".", which exists from any directory, so a test of the
    DIRECTORY would look for ./GATES.json in the wrong place and call it "none"."""
    (tmp_path / "GATES.json").write_text(json.dumps(_FLOOR_GATE))   # beside the cwd, NOT the project
    geo = _geometry(tmp_path, monkeypatch, recorded)
    r = probe.probe_grade_geometry(geo, 0, out_dir=str(tmp_path / "p"))
    assert (r["grade_damage"]["floor"], r["grade_damage"]["below"]) == (0.9, True)
    assert r["gates"]["status"] == "not-read"
    assert why in r["gates"]["reason"] and "DEFAULT" in r["gates"]["reason"]


def test_probe_geometry_refuses_a_gates_file_it_cannot_load_before_rendering_anything(
        tmp_path, monkeypatch):
    """The arm where the project DOES resolve and the file beside it is broken. Phase 1b would
    refuse the same file, so a probe that swallowed the refusal into "no gates" would predict, at
    the default floor and without a word, a run that cannot happen — a silent prediction against
    the wrong bar, which is the defect this whole lookup exists to prevent. And it must refuse
    BEFORE a frame is rendered: the lookup's position in probe_grade_geometry says so in a comment,
    and nothing held it. Moved below the renders, the same ValueError still comes out of the same
    probe, only after it has spent them. Both halves are asserted because each mutant passes the
    other's assertion: a swallow renders everything and raises nothing; a late lookup raises
    exactly what the shipped code raises."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "project.json").write_text("{}")
    (run / "GATES.json").write_text("{broken")
    geo = _geometry(tmp_path, monkeypatch, str(run / "project.json"))
    rendered = []
    graded_half, plain_half = probe._render, probe.reframe.plan_frames_rgb
    monkeypatch.setattr(probe, "_render",
                        lambda *a, **k: rendered.append("graded") or graded_half(*a, **k))
    monkeypatch.setattr(probe.reframe, "plan_frames_rgb",
                        lambda *a, **k: rendered.append("plain") or plain_half(*a, **k))

    with pytest.raises(ValueError) as e:
        probe.probe_grade_geometry(geo, 0, out_dir=str(tmp_path / "p"))
    assert str(run / "GATES.json") in str(e.value)
    assert rendered == []


def test_probe_tone_is_gone():
    assert not hasattr(probe, "_tone")


def _no_dispatch(monkeypatch):
    """Patch both grade entry points so a CLI-refusal test proves argparse/ap.error
    fired BEFORE any dispatch — not merely that main() eventually raised SystemExit
    for some other reason (the same idiom test_edl_to_reel.py's _no_dispatch uses)."""
    called = []
    monkeypatch.setattr(probe, "probe_grade", lambda *a, **k: called.append("probe_grade"))
    monkeypatch.setattr(probe, "probe_grade_geometry",
                        lambda *a, **k: called.append("probe_grade_geometry"))
    return called


def test_cli_grade_refuses_neither_episodes_nor_geometry(monkeypatch, tmp_path, capsys):
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["probe", "grade", "--index", "0"])
    with pytest.raises(SystemExit) as ei:
        probe.main()
    assert ei.value.code == 2
    assert called == []
    err = capsys.readouterr().err
    assert "--episodes" in err and "--geometry" in err


def test_cli_grade_refuses_both_episodes_and_geometry(monkeypatch, tmp_path):
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["probe", "grade",
                                      "--episodes", str(tmp_path / "EPISODES.json"),
                                      "--geometry", str(tmp_path / "GEOMETRY.json"),
                                      "--index", "0"])
    with pytest.raises(SystemExit) as ei:
        probe.main()
    assert ei.value.code == 2             # argparse's own mutually_exclusive_group
    assert called == []


def test_cli_grade_refuses_edl_combined_with_geometry(monkeypatch, tmp_path):
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["probe", "grade",
                                      "--geometry", str(tmp_path / "GEOMETRY.json"),
                                      "--edl", str(tmp_path / "EDL.json"),
                                      "--index", "0"])
    with pytest.raises(SystemExit) as ei:
        probe.main()
    assert ei.value.code == 2
    assert called == []
