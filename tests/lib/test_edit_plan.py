import json
import re
from dataclasses import replace

import pytest
from scripts import edit_plan
from scripts.lib import gridfit, hold, mood, outro, pacing, provenance
from scripts.lib.constraints import Constraints
from scripts.lib.edl import EDL, EDLEpisode
from scripts.lib.footage import Footage, FootageClip, FootageWindow
from scripts.lib.models import MusicSpec
from scripts.lib.spec import Spec


def _clip(**kw):
    d = dict(source="MVI_3739.mp4", dur=22.0, res=(1920, 1080), fps=30.0,
             windows=[FootageWindow(start=2.1, dur=4.0, shot_type="close", people=1,
                                    motion=0.4, shake=0.01, description="lena nose")])
    d.update(kw)
    return FootageClip(**d)


def _window(**kw):
    d = dict(start=2.1, dur=4.0, shot_type="close", people=1, motion=0.4, shake=0.01,
             description="lena nose")
    d.update(kw)
    return FootageWindow(**d)


def _merge_clip(**kw):
    d = dict(source="M.mp4", dur=30.0, res=(1920, 1080), fps=30.0, scene_cuts=[],
             windows=[
                 FootageWindow(start=2.0, dur=3.0, shot_type="wide", people=1, motion=0.4,
                               shake=0.01, description="approach", track_ids=[1]),
                 FootageWindow(start=6.0, dur=2.0, shot_type="close", people=1, motion=0.6,
                               shake=0.02, description="cross-step", track_ids=[1, 2]),
                 FootageWindow(start=9.0, dur=2.0, shot_type="wide", people=1, motion=0.5,
                               shake=0.01, description="exit turn", track_ids=[2])])
    d.update(kw)
    return FootageClip(**d)


def test_window_to_episode_copies_mechanical_fields_by_reference():
    clip = _clip()
    ep = edit_plan.window_to_episode(clip, clip.windows[0], composition="lead", grid="thirds")
    assert ep.source == "MVI_3739.mp4"                      # from the parent clip
    assert ep.start == 2.1 and ep.dur == 4.0                # from the window, not retyped
    assert ep.shot_type == "close"                          # window.shot_type default
    assert ep.processing_notes == "lena nose"                # window.description seed
    assert ep.composition == "lead" and ep.grid == "thirds"


def test_window_to_episode_forwards_editorial_and_overrides_defaults():
    clip = _clip()
    ep = edit_plan.window_to_episode(clip, clip.windows[0], composition="center", grid="phi",
                                     layout="insert", motion="lateral:right", hero=[10, 20, 30, 40],
                                     shot_type="wide", processing_notes="custom")
    assert ep.layout == "insert" and ep.motion == "lateral:right" and ep.hero == (10, 20, 30, 40)
    assert ep.shot_type == "wide"                           # editorial override wins over window default
    assert ep.processing_notes == "custom"


def test_window_to_episode_unknown_editorial_key_raises():
    clip = _clip()
    with pytest.raises(ValueError, match="bogus"):
        edit_plan.window_to_episode(clip, clip.windows[0], composition="lead", grid="thirds", bogus=1)


def test_window_to_episode_missing_required_composition_raises():
    clip = _clip()
    with pytest.raises(ValueError, match="composition"):
        edit_plan.window_to_episode(clip, clip.windows[0], grid="thirds")


def _footage(drop_last=False):
    """`drop_last` (Task 3's outro-cause tests, below) omits the B.mp4 clip — the
    source _two_episodes()'s closing episode uses — so a lookup by source misses,
    without disturbing any of this file's many other zero-arg callers."""
    clips = [
        _clip(source="A.mp4", windows=[
            FootageWindow(start=0.5, dur=2.0, shot_type="wide", people=1, motion=0.3, shake=0.0),
            FootageWindow(start=5.0, dur=3.0, shot_type="close", people=1, motion=0.5, shake=0.0)]),
        _clip(source="B.mp4", windows=[
            FootageWindow(start=1.0, dur=2.5, shot_type="medium", people=2, motion=0.2, shake=0.0)])]
    return Footage(clips=clips[:-1] if drop_last else clips)


def test_build_edl_resolves_refs_and_projects_in_order():
    sel = {"episodes": [
        {"source": "B.mp4", "window": 0, "composition": "center", "grid": "phi"},
        {"source": "A.mp4", "window": 1, "composition": "lead", "grid": "thirds", "motion": "static"}]}
    edl = edit_plan.build_edl(_footage(), sel)
    assert isinstance(edl, EDL) and len(edl.episodes) == 2
    assert edl.episodes[0].source == "B.mp4" and edl.episodes[0].start == 1.0    # by reference
    assert edl.episodes[1].source == "A.mp4" and edl.episodes[1].start == 5.0 and edl.episodes[1].dur == 3.0
    assert edl.episodes[1].motion == "static"


def test_build_edl_carries_reel_knobs():
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}],
           "music": "MUSIC.json", "cap": 2, "target_dur": 6.0}
    edl = edit_plan.build_edl(_footage(), sel)
    assert edl.music == "MUSIC.json" and edl.cap == 2 and edl.target_dur == 6.0


def test_build_edl_defaults_cap_when_absent():
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}]}
    assert edit_plan.build_edl(_footage(), sel).cap == 3


def test_build_edl_carries_the_cast_path():
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}]}
    edl = edit_plan.build_edl(_footage(), sel, cast="proj/cast.json")
    assert edl.cast == "proj/cast.json"


def test_build_edl_without_a_cast():
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}]}
    assert edit_plan.build_edl(_footage(), sel).cast is None


def test_build_edl_empty_cast_string_raises():
    # "" is EDL.__post_init__'s own guard (EDL.cast must be a path or null) — build_edl
    # must let it through untouched, not swallow or reinterpret it (§12: never silently fall back).
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match="EDL.cast"):
        edit_plan.build_edl(_footage(), sel, cast="")


def test_build_edl_unknown_source_raises_listing_available():
    sel = {"episodes": [{"source": "Z.mp4", "window": 0, "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r"'Z\.mp4' not in FOOTAGE.*A\.mp4.*B\.mp4"):
        edit_plan.build_edl(_footage(), sel)


def test_build_edl_out_of_range_window_raises_with_count():
    sel = {"episodes": [{"source": "B.mp4", "window": 3, "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match="window 3 out of range for B.mp4 .has 1."):
        edit_plan.build_edl(_footage(), sel)


def test_build_edl_missing_episodes_raises():
    with pytest.raises(ValueError, match="non-empty list"):
        edit_plan.build_edl(_footage(), {"episodes": []})


def test_build_edl_bad_window_type_raises():
    sel = {"episodes": [{"source": "A.mp4", "window": "first", "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match="'window' must be an integer"):
        edit_plan.build_edl(_footage(), sel)


def test_build_edl_rejects_bool_window_not_index_one():
    # True is an int in Python — the guard must reject it, not treat it as window 1
    sel = {"episodes": [{"source": "A.mp4", "window": True, "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match="'window' must be an integer"):
        edit_plan.build_edl(_footage(), sel)


def test_build_edl_non_dict_episode_raises():
    with pytest.raises(ValueError, match="must be an object"):
        edit_plan.build_edl(_footage(), {"episodes": ["not-a-dict"]})


def test_build_edl_bad_source_type_raises():
    sel = {"episodes": [{"source": 5, "window": 0, "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match="'source' must be a clip path string"):
        edit_plan.build_edl(_footage(), sel)


def _write_inputs(tmp_path, sel, footage=None):
    # footage=None reuses this file's plain wide-only _footage() fixture — the variety
    # tests below pass _varied_footage() instead, so this one helper stays the file's
    # single "write FOOTAGE/selection/project.json into tmp_path" fixture style rather
    # than a second one growing up beside it.
    (tmp_path / "FOOTAGE.json").write_text(json.dumps((footage or _footage()).to_dict()))
    (tmp_path / "selection.json").write_text(json.dumps(sel))
    (tmp_path / "project.json").write_text(
        json.dumps({"purpose": "reel", "canvas": [1080, 1920], "delivery": "native"}))
    return (str(tmp_path / "FOOTAGE.json"), str(tmp_path / "selection.json"),
            str(tmp_path / "project.json"))


def test_write_edit_plan_writes_both_files_and_round_trips(tmp_path):
    sel = {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds", "crop_scale": 0.8},
        {"source": "B.mp4", "window": 0, "composition": "center", "grid": "phi"}]}
    fj, sj, pj = _write_inputs(tmp_path, sel)
    out = tmp_path / "out"
    res = edit_plan.write_edit_plan(fj, sj, pj, str(out))
    assert res["status"] == "written" and res["episodes"] == 2
    assert (out / "EDL.json").exists() and (out / "EDL.md").exists()
    edl = EDL.from_json(str(out / "EDL.json"))                 # round-trips through the contract
    assert edl.episodes[0].source == "A.mp4" and edl.episodes[1].source == "B.mp4"
    assert "# Edit plan — 2 episodes" in (out / "EDL.md").read_text()
    # The written EDL.json must be STAMPED, not merely loadable: an unstamped EDL is
    # legal (edl_to_reel's hand-authored SP1 front door), so a regression that swapped
    # the write_edl() chokepoint for a raw write_text(json.dumps(...)) would still load
    # here and pass every assertion above in silence — exactly the regression class
    # this slice exists to prevent (design docs/specs/2026-08-04-attested-run-design.md
    # §4: "two writers stamping independently is the shape that drifts").
    on_disk = json.loads((out / "EDL.json").read_text())
    assert provenance.check(on_disk)[0] == "intact"


def test_write_edit_plan_bad_episode_stops_and_writes_nothing(tmp_path):
    # ep1 is fill+border → LayoutSpec rejects it in preflight
    sel = {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds", "crop_scale": 0.8},
        {"source": "B.mp4", "window": 0, "composition": "center", "grid": "phi",
         "layout": "fill", "border_px": 5}]}
    fj, sj, pj = _write_inputs(tmp_path, sel)
    out = tmp_path / "out"
    res = edit_plan.write_edit_plan(fj, sj, pj, str(out))
    assert res["status"] == "stop_and_report" and res["finding"]["reason"] == "edl-invalid"
    assert res["finding"]["episode_idx"] == 1
    assert not (out / "EDL.json").exists() and not (out / "EDL.md").exists()   # nothing written


def test_write_edit_plan_corrupt_selection_raises(tmp_path):
    (tmp_path / "FOOTAGE.json").write_text(json.dumps(_footage().to_dict()))
    (tmp_path / "project.json").write_text(
        json.dumps({"purpose": "reel", "canvas": [1080, 1920], "delivery": "native"}))
    (tmp_path / "selection.json").write_text("{ not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        edit_plan.write_edit_plan(str(tmp_path / "FOOTAGE.json"), str(tmp_path / "selection.json"),
                                  str(tmp_path / "project.json"), str(tmp_path / "out"))


@pytest.mark.parametrize("body", ["[]", '"str"', "42", "true", "null"])
def test_write_edit_plan_wrong_shaped_footage_raises_valueerror_not_attributeerror(tmp_path, body):
    # A syntactically-valid FOOTAGE.json whose TOP LEVEL is not an object once reached
    # Footage.from_dict's `d.get("clips", [])` and raised a bare AttributeError straight out
    # of this driver — write_edit_plan has no except around Footage.from_json at all.
    # Fixed at the source, NOT here: from_dict guards its own top level and raises
    # ValueError-with-remedy, which lands this in the SAME channel write_edit_plan already
    # uses for its sibling bad inputs (bad-syntax FOOTAGE/selection → ValueError, see
    # test_write_edit_plan_corrupt_selection_raises above; missing file → OSError). A
    # stop_and_report here would make wrong-shape the ONE input failure that reports softly.
    # Asserting the remedy text is what pins the guard: a bare AttributeError carries no
    # 'clips'/re-run remedy, so this fails if the from_dict guard is removed.
    (tmp_path / "FOOTAGE.json").write_text(body)
    (tmp_path / "project.json").write_text(
        json.dumps({"purpose": "reel", "canvas": [1080, 1920], "delivery": "native"}))
    (tmp_path / "selection.json").write_text(json.dumps(
        {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}]}))
    with pytest.raises(ValueError) as ei:
        edit_plan.write_edit_plan(str(tmp_path / "FOOTAGE.json"), str(tmp_path / "selection.json"),
                                  str(tmp_path / "project.json"), str(tmp_path / "out"))
    msg = str(ei.value)
    assert "expected a FOOTAGE.json object" in msg and "re-run footage-intake" in msg
    assert "has no attribute" not in msg
    assert not (tmp_path / "out" / "EDL.json").exists()          # nothing written


from scripts.lib import pacing
from scripts.lib.pacing import Slot, Spine, music_identity


def _sel3():
    return {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"},   # window dur 2.0
        {"source": "A.mp4", "window": 1, "composition": "lead", "grid": "thirds"},   # window dur 3.0
        {"source": "B.mp4", "window": 0, "composition": "center", "grid": "phi"}]}   # window dur 2.5


def _spine2():
    # A FITTED spine's slot durations sit within the snap allowance of their own
    # episodes' durations (_sel3: window durs 2.0s, 3.0s) — the fitter reads the same
    # EDL, so it can only nudge an out-point by half a beat, never invent a length.
    return Spine(slots=(Slot(0, 0.0, 2.1, 0.2, "hook"),
                        Slot(1, 2.1, 3.05, 0.9, "peak")), target_dur=5.15, tempo=120.0)


def test_build_edl_pacing_binds_slot_and_applies_the_fit():
    # pre-2026-07-24 this asserted RE-TIMING DOWN to a smaller slot (1.0s/1.5s) — the
    # exact truncation the design forbids. _spine2's slots now sit within the snap
    # allowance of their episodes' own durations, so binding applies them verbatim.
    edl = edit_plan.build_edl(_footage(), _sel3(), pacing=_spine2())
    assert edl.episodes[0].beat_slot == 0 and edl.episodes[0].dur == pytest.approx(2.1)
    assert edl.episodes[1].beat_slot == 1 and edl.episodes[1].dur == pytest.approx(3.05)
    assert edl.episodes[0].start == 0.5                                     # window start preserved


def test_build_edl_pacing_overflow_tail_unbound(capsys):
    edl = edit_plan.build_edl(_footage(), _sel3(), pacing=_spine2())        # 3 eps, 2 slots
    assert edl.episodes[2].beat_slot is None and edl.episodes[2].dur == 2.5  # tail unchanged
    assert "exceed the 2-slot spine" in capsys.readouterr().err


def test_build_edl_pacing_refuses_a_slot_far_from_its_window():
    # pre-2026-07-24 this asserted "keep 2s + log shortfall" for a slot wanting 5s
    # against a 2s window — that whole rescue is gone. A slot this far from its own
    # episode (2.7s, past the ~0.25s snap allowance) means the PACING.json was fitted
    # to a DIFFERENT edit; binding must refuse, not keep/stretch/truncate.
    spine = Spine(slots=(Slot(0, 0.0, 5.0, 0.5, "hook"),), target_dur=5.0, tempo=120.0)
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match="fitted to a different"):
        edit_plan.build_edl(_footage(), sel, pacing=spine)


def test_build_edl_no_pacing_leaves_beat_slot_none():
    edl = edit_plan.build_edl(_footage(), _sel3())
    assert all(e.beat_slot is None for e in edl.episodes)                   # regression: unchanged path
    assert edl.episodes[0].dur == 2.0                                       # window dur untouched


def test_cli_build_threads_pacing(tmp_path, monkeypatch, capsys):
    import sys
    from scripts.lib.pacing import Slot, Spine
    # reuse _write_inputs: it writes the on-disk FOOTAGE/selection/project.json shape
    # the real preflight (ProjectConfig + resolve_manifest + preflight) accepts.
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}]}
    fj, sj, pj = _write_inputs(tmp_path, sel)
    # window A/0 is 2.0s; a 2.02s slot sits inside the snap allowance so binding applies it
    # (this test is about the --pacing CLI wire, not the retime amount — pre-2026-07-24 it
    # used a 1.0s slot, which the new guard now refuses as fitted to a different edit)
    (tmp_path / "PACING.json").write_text(json.dumps(
        Spine((Slot(0, 0.0, 2.02, 0.5, "hook"),), 2.02, 120.0).to_dict()))
    monkeypatch.setattr(sys, "argv", ["edit_plan", "build",
                                      "--footage", fj,
                                      "--selection", sj,
                                      "--project", pj,
                                      "--out-dir", str(tmp_path),
                                      "--pacing", str(tmp_path / "PACING.json")])
    with pytest.raises(SystemExit) as e:
        edit_plan.main()
    assert e.value.code == 0
    edl = json.loads((tmp_path / "EDL.json").read_text())
    assert edl["episodes"][0]["beat_slot"] == 0 and edl["episodes"][0]["dur"] == pytest.approx(2.02)


def test_build_edl_back_edge_retimes_the_target_to_the_realized_footage(capsys):
    # 1 episode (2.0s window, matching slot 0 exactly, so binding does not refuse) against
    # a 2-slot, 5.0s spine — the extra slot has no episode to fill it, so the reel realizes
    # only 2.0s and the target re-times DOWN to that, not the spine's optimistic 5.0 (§4).
    # (pre-2026-07-24 this used a single 5s slot against a 2s window — that gap is now a
    # bind-time refusal, not a back-edge retime; see test_build_edl_pacing_refuses_a_slot_far_from_its_window)
    spine = Spine(slots=(Slot(0, 0.0, 2.0, 0.5, "hook"),
                        Slot(1, 2.0, 3.0, 0.5, "peak")), target_dur=5.0, tempo=120.0)
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}]}
    edl = edit_plan.build_edl(_footage(), sel, pacing=spine)
    assert edl.target_dur == 2.0                       # re-timed DOWN, not the optimistic 5.0
    assert "back-edge" in capsys.readouterr().err      # never silent


def test_build_edl_back_edge_silent_when_the_footage_fills_the_spine(capsys):
    # window A/0 is 2s and its only slot wants exactly 2s → nothing to re-time
    spine = Spine(slots=(Slot(0, 0.0, 2.0, 0.5, "hook"),), target_dur=2.0, tempo=120.0)
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}]}
    edl = edit_plan.build_edl(_footage(), sel, pacing=spine)
    assert edl.target_dur == 2.0
    assert "back-edge" not in capsys.readouterr().err


def test_build_edl_back_edge_clamps_an_overflow_to_the_fragment(capsys):
    # 3 episodes realize 2.1+3.05+2.5=7.65s against a 5.15s (2-slot) spine → the target
    # stays at the fragment so the excess escalates at the reel gate; mix can't stretch
    # music to cover it (design §2)
    edl = edit_plan.build_edl(_footage(), _sel3(), pacing=_spine2())
    assert edl.target_dur == pytest.approx(5.15)
    err = capsys.readouterr().err
    assert "back-edge" in err and "escalates at the reel gate" in err


def test_build_edl_without_pacing_keeps_the_selections_target(capsys):
    # regression guard: the un-paced path is untouched by the back-edge
    sel = dict(_sel3(), target_dur=9.0)
    edl = edit_plan.build_edl(_footage(), sel)
    assert edl.target_dur == 9.0
    assert "back-edge" not in capsys.readouterr().err


@pytest.fixture
def offset_clip():
    return FootageClip(source="a.mp4", dur=30.0, res=(1920, 1080), fps=30.0, shaky=False,
                       scene_cuts=[12.0],
                       windows=[FootageWindow(start=2.0, dur=4.0, shot_type="wide",
                                              people=1, motion=0.4, shake=0.001,
                                              description="a ride", score=0.8, best=True)])


def _ep(**kw):
    base = dict(source="a.mp4", start=0.0, dur=4.0, shot_type="wide",
                composition="lead", grid="thirds")
    return EDLEpisode(**{**base, **kw})


def test_start_offset_moves_the_in_point_but_not_the_duration(offset_clip):
    w = offset_clip.windows[0]
    ep = edit_plan.window_to_episode(offset_clip, w, start_offset=1.5,
                                     composition="center", grid="thirds")
    assert ep.start == pytest.approx(w.start + 1.5)
    assert ep.dur == pytest.approx(w.dur)


def test_start_offset_defaults_to_the_window_start(offset_clip):
    w = offset_clip.windows[0]
    ep = edit_plan.window_to_episode(offset_clip, w, composition="center", grid="thirds")
    assert ep.start == pytest.approx(w.start)


def test_start_offset_refuses_to_cross_a_scene_cut(offset_clip):
    with pytest.raises(ValueError, match="scene cut"):
        edit_plan.window_to_episode(offset_clip, offset_clip.windows[0],
                                    start_offset=11.0,
                                    composition="center", grid="thirds")


def test_start_offset_past_the_clip_is_refused(offset_clip):
    with pytest.raises(ValueError, match="past the end"):
        edit_plan.window_to_episode(offset_clip, offset_clip.windows[0],
                                    start_offset=999.0,
                                    composition="center", grid="thirds")


@pytest.mark.parametrize("bad", [-1.0, True, "1.5", None])
def test_start_offset_must_be_a_nonnegative_number(offset_clip, bad):
    with pytest.raises(ValueError, match="start_offset"):
        edit_plan.window_to_episode(offset_clip, offset_clip.windows[0],
                                    start_offset=bad,
                                    composition="center", grid="thirds")


def test_bind_applies_a_fitted_slot_verbatim():
    """A fitted spine's slot IS the episode's duration plus its snap — binding copies it
    across and sets beat_slot; it never invents a length."""
    eps = [_ep(dur=2.0), _ep(dur=3.0)]
    spine = pacing.Spine((pacing.Slot(0, 0.0, 2.1, 0.5, "hook", line=2.1, dev=0.0),
                          pacing.Slot(1, 2.1, 3.0, 0.5, "peak", line=None, dev=0.0)),
                         5.1, 120.0)
    bound = edit_plan._bind_pacing(eps, spine)
    assert [e.dur for e in bound] == pytest.approx([2.1, 3.0])
    assert [e.beat_slot for e in bound] == [0, 1]


def test_bind_refuses_a_spine_fitted_to_a_different_edit():
    """The pre-2026-07-24 behaviour truncated a 7.3s ride into a 4.6s slot in silence.
    A slot further from its episode than the allowance means the spine was fitted to
    OTHER cuts — that is a wiring bug, not a re-time."""
    eps = [_ep(dur=7.3), _ep(dur=3.0)]
    spine = pacing.Spine((pacing.Slot(0, 0.0, 4.6, 0.5, "hook", line=4.6, dev=0.0),
                          pacing.Slot(1, 4.6, 3.0, 0.5, "peak", line=None, dev=0.0)),
                         7.6, 120.0)
    with pytest.raises(ValueError, match="fitted to a different"):
        edit_plan._bind_pacing(eps, spine)


def test_start_offset_out_point_may_not_cross_a_mid_body_scene_cut():
    # window [6,10] sits inside shot A (cut at 12); shifting the in-point to 9 pushes the
    # OUT-point to 13, past the cut — the episode would splice shot A and shot B.
    clip = FootageClip(source="a.mp4", dur=30.0, res=(1920, 1080), fps=30.0, shaky=False,
                       scene_cuts=[12.0],
                       windows=[FootageWindow(start=6.0, dur=4.0, shot_type="wide",
                                              people=1, motion=0.4, shake=0.001,
                                              description="d", score=0.8, best=True)])
    with pytest.raises(ValueError, match="room"):
        edit_plan.window_to_episode(clip, clip.windows[0], start_offset=3.0,
                                    composition="center", grid="thirds")


def test_start_offset_out_point_may_not_run_past_the_clip_end():
    # No cut, but start+dur exceeds clip.dur.
    clip = FootageClip(source="a.mp4", dur=10.0, res=(1920, 1080), fps=30.0, shaky=False,
                       scene_cuts=[],
                       windows=[FootageWindow(start=4.0, dur=5.0, shot_type="wide",
                                              people=1, motion=0.4, shake=0.001,
                                              description="d", score=0.8, best=True)])
    with pytest.raises(ValueError, match="room"):
        edit_plan.window_to_episode(clip, clip.windows[0], start_offset=2.0,
                                    composition="center", grid="thirds")


def test_start_offset_zero_with_a_window_flush_to_a_cut_is_accepted():
    # Default path: an episode ending EXACTLY at the cut is fine (out-point on the cut,
    # not past it). This guards against a false-refusal on the offset=0 path.
    clip = FootageClip(source="a.mp4", dur=30.0, res=(1920, 1080), fps=30.0, shaky=False,
                       scene_cuts=[10.0],
                       windows=[FootageWindow(start=6.0, dur=4.0, shot_type="wide",
                                              people=1, motion=0.4, shake=0.001,
                                              description="d", score=0.8, best=True)])
    ep = edit_plan.window_to_episode(clip, clip.windows[0], composition="center",
                                     grid="thirds")
    assert ep.dur == pytest.approx(4.0)


def test_merge_windows_envelope_spans_the_range_and_unions_track_ids():
    clip = _merge_clip()
    fw = edit_plan._merge_windows(clip, 0, 1)
    assert fw.start == 2.0
    assert fw.dur == 6.0                        # 8.0 (w1 end) - 2.0 (w0 start): covers the 5.0-6.0 drive between
    assert fw.track_ids == [1, 2]              # sorted union across the range
    assert fw.shot_type == "wide"             # inherited from window i (the arc's opening)
    assert fw.description == "approach"       # inherited from window i


def test_merge_windows_covers_the_whole_range_not_just_endpoints():
    clip = _merge_clip()
    fw = edit_plan._merge_windows(clip, 0, 2)
    assert fw.start == 2.0 and fw.dur == 9.0   # 11.0 (w2 end) - 2.0 (w0 start)
    assert fw.track_ids == [1, 2]              # unions w0, w1, w2


def test_merge_windows_allows_a_scene_cut_outside_the_span():
    # a cut AFTER the [0,1] envelope's end (8.0) does not block the merge — only a cut
    # INSIDE [start, end] splices two shots; a presence transition (no cut) is fine
    clip = _merge_clip(scene_cuts=[8.5])
    fw = edit_plan._merge_windows(clip, 0, 1)
    assert fw.dur == 6.0


def test_merge_windows_refuses_to_cross_a_scene_cut():
    # a cut between w0 (ends 5.0) and w1 (starts 6.0) sits inside the [2.0, 8.0] envelope
    clip = _merge_clip(scene_cuts=[5.5])
    with pytest.raises(ValueError, match=r"scene cut at 5\.50s.*cannot cross"):
        edit_plan._merge_windows(clip, 0, 1)


def test_merge_windows_clamps_a_sub_ms_clip_end_overshoot_instead_of_crashing():
    # intake stores round(start,3)+round(dur,3) independently, so the last window's start+dur
    # can land ~1ms past clip.dur (6.667+3.334 = 10.001 > 10.0); that is a legit clip-end span,
    # not a straddle — the merge clamps the envelope to the clip end, no crash, no false refusal
    clip = FootageClip(source="M.mp4", dur=10.0, res=(1920, 1080), fps=30.0, scene_cuts=[],
                       windows=[FootageWindow(start=2.0, dur=3.0, shot_type="wide", people=1,
                                              motion=0.4, shake=0.0),
                                FootageWindow(start=6.667, dur=3.334, shot_type="wide", people=1,
                                              motion=0.4, shake=0.0)])
    fw = edit_plan._merge_windows(clip, 0, 1)
    assert fw.start == 2.0
    assert fw.dur == pytest.approx(8.0)          # clamped to the clip end (10.0 - 2.0), not 8.001


def test_merge_windows_refuses_an_envelope_well_past_the_clip_end():
    # a window genuinely beyond the clip (8+5=13 >> 10, not rounding) → loud fail with a remedy,
    # not a crash and not a spurious "scene cut" message
    clip = FootageClip(source="M.mp4", dur=10.0, res=(1920, 1080), fps=30.0, scene_cuts=[],
                       windows=[FootageWindow(start=2.0, dur=3.0, shot_type="wide", people=1,
                                              motion=0.4, shake=0.0),
                                FootageWindow(start=8.0, dur=5.0, shot_type="wide", people=1,
                                              motion=0.4, shake=0.0)])
    with pytest.raises(ValueError, match=r"past the end of M\.mp4"):
        edit_plan._merge_windows(clip, 0, 1)


def test_build_edl_span_window_merges_into_one_episode():
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [0, 1],
                         "composition": "lead", "grid": "thirds"}]}
    edl = edit_plan.build_edl(footage, sel)
    assert len(edl.episodes) == 1
    assert edl.episodes[0].start == 2.0 and edl.episodes[0].dur == 6.0   # merged envelope, not one window
    assert edl.episodes[0].shot_type == "wide"                          # window i's shot_type default


def test_build_edl_span_forwards_editorial_and_overrides():
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [0, 2], "composition": "center",
                         "grid": "phi", "motion": "static", "shot_type": "medium",
                         "processing_notes": "turn-drive-turn"}]}
    ep = edit_plan.build_edl(footage, sel).episodes[0]
    assert ep.dur == 9.0 and ep.motion == "static"
    assert ep.shot_type == "medium"                    # editorial override beats window i's default
    assert ep.processing_notes == "turn-drive-turn"


def test_build_edl_span_round_trips_through_to_dict():
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [0, 1],
                         "composition": "lead", "grid": "thirds"}]}
    edl = edit_plan.build_edl(footage, sel)
    assert EDL.from_dict(edl.to_dict()).episodes[0].dur == 6.0    # a merged episode is an ordinary EDLEpisode


def test_build_edl_span_reversed_range_raises():
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [1, 0], "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r"span window \[1, 0\] out of range"):
        edit_plan.build_edl(footage, sel)


def test_build_edl_span_degenerate_i_equals_j_raises():
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [1, 1], "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r'for a single window use "window": i'):
        edit_plan.build_edl(footage, sel)


def test_build_edl_span_out_of_range_j_raises():
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [0, 9], "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r"span window \[0, 9\] out of range"):
        edit_plan.build_edl(footage, sel)


def test_build_edl_span_wrong_length_raises():
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [0, 1, 2], "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r"a span 'window' must be \[i, j\]"):
        edit_plan.build_edl(footage, sel)


def test_build_edl_span_non_int_element_raises():
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [0, "x"], "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r"a span 'window' must be \[i, j\]"):
        edit_plan.build_edl(footage, sel)


def test_build_edl_span_bool_element_raises():
    # True is an int in Python — the guard must reject a bool element, not treat it as index 1
    footage = Footage(clips=[_merge_clip()])
    sel = {"episodes": [{"source": "M.mp4", "window": [0, True], "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r"a span 'window' must be \[i, j\]"):
        edit_plan.build_edl(footage, sel)


def test_build_edl_span_crossing_a_scene_cut_raises():
    footage = Footage(clips=[_merge_clip(scene_cuts=[5.5])])
    sel = {"episodes": [{"source": "M.mp4", "window": [0, 1], "composition": "lead", "grid": "thirds"}]}
    with pytest.raises(ValueError, match=r"scene cut at 5\.50s.*cannot cross"):
        edit_plan.build_edl(footage, sel)


from scripts.lib import moodpreset


def _varied_footage():
    """One clip: 3 close windows (a subject filling the frame) + 6 wide ones."""
    close = [FootageWindow(start=float(i), dur=1.0, shot_type="close", people=1,
                           motion=0.2, shake=0.0, subject_w=0.8, subject_h=0.8,
                           present=1.0) for i in range(3)]
    wide = [FootageWindow(start=float(3 + i), dur=1.0, shot_type="wide", people=1,
                          motion=0.3, shake=0.0, subject_w=0.02, subject_h=0.05,
                          present=1.0) for i in range(6)]
    clip = FootageClip(source="a.mp4", dur=20.0, res=(3840, 2160), fps=30.0,
                       windows=close + wide)
    return Footage(clips=[clip])


def _wide_only_selection():
    return {"episodes": [{"source": "a.mp4", "window": 3 + i, "composition": "center",
                          "grid": "thirds"} for i in range(3)]}


def test_build_edl_counts_both_censuses_in_delivered_geometry():
    edl = edit_plan.build_edl(_varied_footage(), _wide_only_selection(),
                              aspect=(9, 16), preset=moodpreset.resolve("fun"))
    assert edl.variety.available["close"] == 3
    assert edl.variety.used == {"close": 0, "medium": 0, "wide": 3}
    assert edl.variety.gaps == ("close",)


def test_available_census_counts_windows_not_seconds():
    # design §7: "Counting is by window, not by duration". _varied_footage's windows
    # are all dur=1.0, so summing durations and counting windows land on the same
    # number there (3) and a duration-summing bug would slip past that fixture. Here
    # the three close windows carry non-uniform, non-1.0 durations (2.0, 3.25, 4.5s,
    # summing to 9.75) so the two counting strategies diverge: int(sum(dur)) == 9,
    # count-of-windows == 3.
    close = [FootageWindow(start=float(i) * 10, dur=2.0 + i * 1.25, shot_type="close",
                           people=1, motion=0.2, shake=0.0, subject_w=0.8, subject_h=0.8,
                           present=1.0) for i in range(3)]
    wide = [FootageWindow(start=float(3 + i), dur=1.0, shot_type="wide", people=1,
                          motion=0.3, shake=0.0, subject_w=0.02, subject_h=0.05,
                          present=1.0) for i in range(6)]
    clip = FootageClip(source="a.mp4", dur=100.0, res=(3840, 2160), fps=30.0,
                       windows=close + wide)
    footage = Footage(clips=[clip])
    edl = edit_plan.build_edl(footage, _wide_only_selection(), aspect=(9, 16),
                              preset=moodpreset.resolve("fun"))
    assert edl.variety.available["close"] == 3


def test_available_census_counts_windows_with_no_detected_subject():
    clip = _clip(res=(3840, 2160), windows=[_window(subject_w=0.0, subject_h=0.0),
                                            _window(subject_w=0.0, subject_h=0.4),
                                            _window(subject_w=0.5, subject_h=0.6)])
    counts, unmeasured = edit_plan._available_census(Footage(clips=[clip]), (9, 16))
    assert unmeasured == 2          # (0, 0) and (0, 0.4) both have zero subject AREA
    assert sum(counts.values()) == 3


def test_available_census_counts_a_zero_height_subject_as_unmeasured_too():
    # Coverage hole found running the Task 7 mutation battery: row 15 ("counts
    # subject_w == 0.0 only, drops the * subject_h product") is invisible to
    # test_available_census_counts_windows_with_no_detected_subject just above,
    # because every window there with subject_w == 0.0 also has subject_h ==
    # 0.0 -- checking subject_w alone gives the same count as checking the
    # product on that fixture. `unmeasured` is defined on the subject's AREA
    # (design 2026-09-10 §0.5, and shot_type/delivered_shot both key on w*h
    # too) -- a degenerate box with ONE dimension at zero still has zero area
    # and must count as unmeasured even though the OTHER dimension is not.
    clip = _clip(res=(3840, 2160), windows=[_window(subject_w=0.5, subject_h=0.0),
                                            _window(subject_w=0.0, subject_h=0.5),
                                            _window(subject_w=0.5, subject_h=0.6)])
    counts, unmeasured = edit_plan._available_census(Footage(clips=[clip]), (9, 16))
    assert unmeasured == 2          # both zero-AREA windows, regardless of which factor is zero


def test_available_census_reports_no_blind_windows_when_every_subject_was_found():
    clip = _clip(res=(3840, 2160), windows=[_window(subject_w=0.3, subject_h=0.4)])
    counts, unmeasured = edit_plan._available_census(Footage(clips=[clip]), (9, 16))
    assert unmeasured == 0
    assert sum(counts.values()) == 1


def test_build_edl_carries_the_call_sites_own_unmeasured_count():
    # Review question for this task: the two tests above call `_available_census`
    # directly, so neither one exercises build_edl's call site at all -- a call site
    # that hardcoded unmeasured=0 instead of forwarding the counted value would pass
    # both of them in silence. Two close windows a person detector measured (used,
    # so no variety-gap on "close") plus one wide window it found nobody in
    # (unmeasured, and left unused -- "wide" has only 1 available window, under
    # MIN_AVAIL, so leaving it unused cannot trip the gate either).
    clip = _clip(res=(3840, 2160), windows=[_window(subject_w=0.8, subject_h=0.8),
                                            _window(subject_w=0.8, subject_h=0.8),
                                            _window(subject_w=0.0, subject_h=0.0)])
    footage = Footage(clips=[clip])
    sel = {"episodes": [{"source": clip.source, "window": 0, "composition": "center", "grid": "thirds"},
                        {"source": clip.source, "window": 1, "composition": "center", "grid": "thirds"}]}
    edl = edit_plan.build_edl(footage, sel, aspect=(9, 16), preset=moodpreset.resolve("fun"))
    assert edl.variety.gaps == ()                    # fixture sanity: the gate must not stop here
    assert edl.variety.unmeasured == 1


def test_write_edit_plan_logs_and_writes_the_unmeasured_count(tmp_path, capsys):
    # The companion to the test above, one level up: write_edit_plan is the gate that
    # actually LOGS the count (edit_plan.py's `_log("variety: ...")` line) and writes
    # it into EDL.json -- neither is reached by calling build_edl directly.
    clip = _clip(res=(3840, 2160), windows=[_window(subject_w=0.8, subject_h=0.8),
                                            _window(subject_w=0.8, subject_h=0.8),
                                            _window(subject_w=0.0, subject_h=0.0)])
    footage = Footage(clips=[clip])
    sel = {"episodes": [{"source": clip.source, "window": 0, "composition": "center", "grid": "thirds"},
                        {"source": clip.source, "window": 1, "composition": "center", "grid": "thirds"}]}
    fp, sp, pp = _write_inputs(tmp_path, sel, footage)
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path))
    assert result["status"] == "written"
    written = json.loads((tmp_path / "EDL.json").read_text())
    assert written["variety"]["unmeasured"] == 1
    err = capsys.readouterr().err
    assert "(1 with no detected subject)" in err


def test_write_edit_plan_logs_no_clause_when_every_subject_was_measured(tmp_path, capsys):
    # The control for the test above: _varied_footage()'s nine windows are ALL
    # explicitly measured (subject_w/subject_h > 0), so the gate must add no clause at
    # all -- a regression that rendered the clause unconditionally (or on `is not
    # None` rather than truthiness) would slip past every test above, none of which
    # drives write_edit_plan on all-measured footage.
    sel = {**_wide_only_selection(), "variety_waiver": "close windows are soft"}
    fp, sp, pp = _write_inputs(tmp_path, sel, _varied_footage())
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path))
    assert result["status"] == "written"
    err = capsys.readouterr().err
    assert "no detected subject" not in err


def test_variety_asl_reads_played_time_not_source_time():
    # Final-review finding (the eighth length consumer, design §6): a ramped episode's
    # `dur` is how much SOURCE it consumes, not how long it PLAYS — summing `dur` for
    # ASL under-reports exactly the episodes a ramp was authored on. One 4.0s wide
    # window with a ramp (region [1.0, 3.0], well inside it) at fps=60 so the judder
    # gate at edit_plan.window_to_episode's ramp check does not itself refuse.
    clip = FootageClip(source="a.mp4", dur=20.0, res=(3840, 2160), fps=60.0, windows=[
        FootageWindow(start=0.0, dur=4.0, shot_type="wide", people=1, motion=0.3,
                     shake=0.0, subject_w=0.02, subject_h=0.05, present=1.0)])
    footage = Footage(clips=[clip])
    sel = {"episodes": [{"source": "a.mp4", "window": 0, "composition": "center",
                         "grid": "thirds",
                         "ramp": {"at": 2.0, "factor": 0.4, "ease": 0.5, "hold": 1.0}}]}
    edl = edit_plan.build_edl(footage, sel, aspect=(9, 16), preset=moodpreset.resolve("fun"))
    played = edl.episodes[0].play_dur()
    assert played > edl.episodes[0].dur, "fixture sanity: the ramp must actually add time"
    assert edl.variety.asl == pytest.approx(played)


def test_build_edl_skips_the_evaluation_without_an_aspect_or_preset():
    # the SP1 boundary: no project geometry, no report — not a silent pass
    edl = edit_plan.build_edl(_varied_footage(), _wide_only_selection())
    assert edl.variety is None


def test_build_edl_reads_the_waiver_from_the_selection():
    sel = {**_wide_only_selection(), "variety_waiver": "the close windows are all soft"}
    edl = edit_plan.build_edl(_varied_footage(), sel, aspect=(9, 16),
                              preset=moodpreset.resolve("fun"))
    assert edl.variety.waiver == "the close windows are all soft"
    assert edl.variety.ok is True


def test_build_edl_refuses_a_blank_waiver():
    sel = {**_wide_only_selection(), "variety_waiver": "   "}
    with pytest.raises(ValueError, match="waiver"):
        edit_plan.build_edl(_varied_footage(), sel, aspect=(9, 16),
                            preset=moodpreset.resolve("fun"))


def test_write_edit_plan_stops_on_a_variety_gap_and_names_candidates(tmp_path):
    fp, sp, pp = _write_inputs(tmp_path, _wide_only_selection(), _varied_footage())
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path))
    assert result["status"] == "stop_and_report"
    assert result["finding"]["reason"] == "variety-gap"
    problems = " ".join(result["finding"]["problems"])
    assert "close" in problems and "a.mp4 #0" in problems and "variety_waiver" in problems
    assert not (tmp_path / "EDL.json").exists()      # nothing lands on a stop


def test_write_edit_plan_passes_with_a_waiver(tmp_path):
    sel = {**_wide_only_selection(), "variety_waiver": "close windows are soft"}
    fp, sp, pp = _write_inputs(tmp_path, sel, _varied_footage())
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path))
    assert result["status"] == "written"
    written = json.loads((tmp_path / "EDL.json").read_text())
    assert written["variety"]["waiver"] == "close windows are soft"
    assert written["variety"]["gaps"] == ["close"]


def test_write_edit_plan_without_a_spec_uses_balanced(tmp_path):
    # no --spec: the gate stays live, so the same wide-only selection still stops
    fp, sp, pp = _write_inputs(tmp_path, _wide_only_selection(), _varied_footage())
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path))
    assert result["finding"]["reason"] == "variety-gap"
    assert "balanced" in " ".join(result["finding"]["problems"])


# --- housekeeping Task 0: SPEC.platform -> EDL.platform (design 2026-08-12 §1.1) ---
# No SPEC.json fixture helper existed in this module before this task — Spec requires
# canvas/length_s/mood/hook (scripts/lib/spec.py). mood="unspecified" matches no
# scripts.lib.mood.MOOD_ANCHORS token, so moodpreset.resolve falls to BALANCED here
# exactly as it does on the no-spec path above — keeping the variety gate identical
# between the two tests below so only the platform assertion is in play.

def _write_spec(tmp_path, **kw):
    base = dict(canvas=(1080, 1920), length_s=30.0, mood="unspecified", hook="hook")
    base.update(kw)
    p = tmp_path / "SPEC.json"
    Spec(**base).write(p)
    return str(p)


def _plain_selection():
    return {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds", "crop_scale": 0.8},
        {"source": "B.mp4", "window": 0, "composition": "center", "grid": "phi"}]}


def test_write_edit_plan_carries_spec_platform_into_the_edl(tmp_path):
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection())
    spec_path = _write_spec(tmp_path, platform="tiktok")
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path), spec=spec_path)
    assert result["status"] == "written"
    edl = EDL.from_json(str(tmp_path / "EDL.json"))
    assert edl.platform == "tiktok"


def test_write_edit_plan_without_spec_leaves_platform_empty(tmp_path):
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection())
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path))
    assert result["status"] == "written"
    edl = EDL.from_json(str(tmp_path / "EDL.json"))
    assert edl.platform == ""


def _cut_footage():
    # One clip, a cut at 10.0. Windows 0 and 1 sit in the SAME shot [0, 10) without
    # overlapping; window 2 is in the later shot [10, 20).
    return Footage(clips=[_clip(source="A.mp4", dur=20.0, scene_cuts=[10.0], windows=[
        FootageWindow(start=1.0, dur=2.0, shot_type="wide", people=1, motion=0.3, shake=0.0),
        FootageWindow(start=6.0, dur=2.0, shot_type="wide", people=1, motion=0.3, shake=0.0),
        FootageWindow(start=12.0, dur=2.0, shot_type="close", people=1, motion=0.3,
                      shake=0.0)])])


def _two_from_one_shot():
    return {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"},
        {"source": "A.mp4", "window": 1, "composition": "lead", "grid": "thirds"}]}


def _no_repeat_rules():
    return Constraints.from_dict({"rules": [
        {"kind": "no_repeat", "stated": "эпизоды не должны повторяться"}]})


def test_build_edl_without_rules_leaves_constraints_unevaluated():
    edl = edit_plan.build_edl(_cut_footage(), _two_from_one_shot())
    assert edl.constraints is None


def test_build_edl_measures_a_repeat_but_does_not_refuse():
    edl = edit_plan.build_edl(_cut_footage(), _two_from_one_shot(), rules=_no_repeat_rules())
    assert edl.constraints is not None and not edl.constraints.ok
    assert edl.constraints.violations[0].kind == "no_repeat"


def test_build_edl_passes_two_episodes_from_different_shots():
    sel = {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"},
        {"source": "A.mp4", "window": 2, "composition": "lead", "grid": "thirds"}]}
    edl = edit_plan.build_edl(_cut_footage(), sel, rules=_no_repeat_rules())
    assert edl.constraints.ok


def test_a_rule_pin_does_not_satisfy_a_bookend():
    # "largest" is a HERO_RULES tracking target, not a person — it must project to
    # None, so the bookend rule refuses instead of being fooled by the string.
    rules = Constraints.from_dict({"rules": [
        {"kind": "open_with", "stated": "Serge opens", "hero": "Serge"}]})
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead",
                         "grid": "thirds", "hero": "largest"}]}
    edl = edit_plan.build_edl(_cut_footage(), sel, rules=rules)
    assert not edl.constraints.ok and "pins no cast name" in edl.constraints.violations[0].message


def test_a_cast_name_pin_satisfies_a_bookend():
    rules = Constraints.from_dict({"rules": [
        {"kind": "open_with", "stated": "Serge opens", "hero": "Serge"}]})
    sel = {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead",
                         "grid": "thirds", "hero": "Serge"}]}
    assert edit_plan.build_edl(_cut_footage(), sel, rules=rules).constraints.ok


def _write_rules(tmp_path, rules_dict):
    (tmp_path / "CONSTRAINTS.json").write_text(json.dumps(rules_dict))


def test_write_edit_plan_finds_the_rule_file_beside_project_json_and_refuses(tmp_path):
    fj, sj, pj = _write_inputs(tmp_path, _two_from_one_shot(), footage=_cut_footage())
    _write_rules(tmp_path, {"rules": [{"kind": "no_repeat",
                                       "stated": "эпизоды не должны повторяться"}]})
    out = tmp_path / "out"
    res = edit_plan.write_edit_plan(fj, sj, pj, str(out))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "constraint-violation"
    assert "эпизоды не должны повторяться" in res["finding"]["problems"][0]
    assert not (out / "EDL.json").exists() and not (out / "EDL.md").exists()


def test_write_edit_plan_without_a_rule_file_writes_and_leaves_constraints_null(tmp_path):
    fj, sj, pj = _write_inputs(tmp_path, _two_from_one_shot(), footage=_cut_footage())
    out = tmp_path / "out"
    assert edit_plan.write_edit_plan(fj, sj, pj, str(out))["status"] == "written"
    assert json.loads((out / "EDL.json").read_text())["constraints"] is None


def test_write_edit_plan_records_the_rules_that_held(tmp_path):
    sel = {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"},
        {"source": "A.mp4", "window": 2, "composition": "lead", "grid": "thirds"}]}
    fj, sj, pj = _write_inputs(tmp_path, sel, footage=_cut_footage())
    _write_rules(tmp_path, {"rules": [{"kind": "no_repeat", "stated": "no repeats"}]})
    out = tmp_path / "out"
    assert edit_plan.write_edit_plan(fj, sj, pj, str(out))["status"] == "written"
    edl = EDL.from_json(str(out / "EDL.json"))
    assert edl.constraints.ok and edl.constraints.rules[0]["stated"] == "no repeats"
    assert "## Editorial rules" in (out / "EDL.md").read_text()


def test_a_broken_rule_outranks_a_variety_gap(tmp_path):
    # Both gates would fire on this cut (one shot twice, and it takes no close
    # window while the footage offers three). The USER's rule is the reported one.
    close = [FootageWindow(start=float(12 + i), dur=0.5, shot_type="close", people=1,
                           motion=0.3, shake=0.0, subject_w=0.8, subject_h=0.8)
             for i in range(3)]
    wide = [FootageWindow(start=1.0, dur=2.0, shot_type="wide", people=1, motion=0.3,
                          shake=0.0, subject_w=0.02, subject_h=0.05),
            FootageWindow(start=6.0, dur=2.0, shot_type="wide", people=1, motion=0.3,
                          shake=0.0, subject_w=0.02, subject_h=0.05)]
    footage = Footage(clips=[_clip(source="A.mp4", dur=20.0, res=(3840, 2160),
                                   scene_cuts=[10.0], windows=wide + close)])
    sel = {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"},
        {"source": "A.mp4", "window": 1, "composition": "lead", "grid": "thirds"}]}
    fj, sj, pj = _write_inputs(tmp_path, sel, footage=footage)
    _write_rules(tmp_path, {"rules": [{"kind": "no_repeat", "stated": "no repeats"}]})
    res = edit_plan.write_edit_plan(fj, sj, pj, str(tmp_path / "out"))
    assert res["finding"]["reason"] == "constraint-violation"


def test_write_edit_plan_propagates_a_corrupt_rule_file(tmp_path):
    fj, sj, pj = _write_inputs(tmp_path, _two_from_one_shot(), footage=_cut_footage())
    (tmp_path / "CONSTRAINTS.json").write_text("{ not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        edit_plan.write_edit_plan(fj, sj, pj, str(tmp_path / "out"))


def test_window_to_episode_refuses_a_pan_over_a_window_holding_people():
    clip = _clip(windows=[_window(present=0.8)])
    with pytest.raises(ValueError, match="holds people in 80%"):
        edit_plan.window_to_episode(clip, clip.windows[0], composition="center",
                                    grid="thirds", pan={"from": 0.0, "to": 1.0})


def test_window_to_episode_allows_a_pan_over_an_empty_window():
    clip = _clip(windows=[_window(present=0.0)])
    ep = edit_plan.window_to_episode(clip, clip.windows[0], composition="center",
                                     grid="thirds", pan={"from": 0.0, "to": 1.0})
    assert ep.pan == {"from": 0.0, "to": 1.0}


def test_window_to_episode_leaves_a_people_bearing_window_alone_without_a_pan():
    clip = _clip(windows=[_window(present=0.8)])
    ep = edit_plan.window_to_episode(clip, clip.windows[0], composition="center",
                                     grid="thirds")
    assert ep.pan is None


def test_merged_window_reports_the_busiest_presence_in_the_span():
    clip = _clip(windows=[_window(present=0.0, start=0.0, dur=2.0),
                          _window(present=0.9, start=2.0, dur=2.0)])
    merged = edit_plan._merge_windows(clip, 0, 1)
    assert merged.present == 0.9


# --- speed ramp: bind/target/gate read PLAYED time (design 2026-08-09) ---------------


def _ramped_episode(dur, factor):
    """_ep's own shape (source/shot_type), plus a ramp whose region [0.6s, 1.4s] sits
    well inside any `dur` this slice's tests use, so validate_window never fights the
    fixture regardless of `factor`."""
    return EDLEpisode(source="a.mp4", start=0.0, dur=dur, shot_type="wide",
                      composition="lead", grid="thirds",
                      ramp={"at": 1.0, "factor": factor, "ease": 0.3, "hold": 0.2})


def _plain_episode(dur):
    """An unramped EDLEpisode — _ep's own shape, named for parity with _ramped_episode
    so a test reads which kind of fixture it is building."""
    return _ep(dur=dur)


def _spine(durs, tempo, target=None):
    """A Spine whose slots carry `durs` back to back, hook first — Spine.__post_init__'s
    own contiguity/hook-first rules, which pacing.py's real fitter always satisfies, so a
    hand-built spine for these binding tests must too. `target` defaults to sum(durs),
    the only value __post_init__ accepts without an explicit target of its own."""
    slots, start = [], 0.0
    for i, d in enumerate(durs):
        slots.append(Slot(i, start, d, 0.5, "hook" if i == 0 else "release"))
        start += d
    return Spine(tuple(slots), target if target is not None else sum(durs), tempo)


def test_the_binding_guard_compares_the_played_length():
    # A ramped 4.0s window plays measurably longer than 4.0s. Against a slot sized to
    # ITS PLAYED length it must BIND; comparing the source window (dur) would see a gap
    # past the snap allowance and refuse a correct fit.
    ep = _ramped_episode(dur=4.0, factor=0.4)
    slot_dur = ep.play_dur()
    bound = edit_plan._bind_pacing([ep], _spine([slot_dur], tempo=120.0))
    assert bound[0].beat_slot == 0


def test_binding_sets_the_source_window_the_slot_implies():
    # The episode must PLAY for slot.dur, so its SOURCE window is slot.dur minus
    # the ramp's added time — one subtraction, exact because the enclosed region
    # makes ramp_extra constant in dur (design §2).
    ep = _ramped_episode(dur=4.0, factor=0.4)
    extra = ep.play_dur() - ep.dur
    slot_dur = ep.play_dur() + 0.10
    bound = edit_plan._bind_pacing([ep], _spine([slot_dur], tempo=120.0))
    assert bound[0].dur == pytest.approx(slot_dur - extra)
    assert bound[0].play_dur() == pytest.approx(slot_dur)


def test_binding_an_unramped_episode_is_unchanged():
    ep = _plain_episode(dur=4.0)
    bound = edit_plan._bind_pacing([ep], _spine([4.1], tempo=120.0))
    assert bound[0].dur == pytest.approx(4.1)


def test_the_guard_still_refuses_a_spine_fitted_to_a_different_edit():
    ep = _ramped_episode(dur=4.0, factor=0.4)
    with pytest.raises(ValueError, match="fitted to a different edit"):
        edit_plan._bind_pacing([ep], _spine([2.0], tempo=120.0))


def test_the_back_edge_target_sums_played_time():
    eps = [_ramped_episode(dur=4.0, factor=0.4), _plain_episode(dur=3.0)]
    want = eps[0].play_dur() + 3.0
    got = edit_plan._back_edge_target(eps, _spine([99.0], tempo=120.0, target=99.0))
    assert got == pytest.approx(want)


def test_window_to_episode_refuses_a_juddering_ramp_early():
    # FOOTAGE knows the clip's fps, so the refusal costs no encode at all.
    clip = _clip(fps=30.0)
    with pytest.raises(ValueError, match="unique frames per second"):
        edit_plan.window_to_episode(
            clip, clip.windows[0], composition="lead", grid="thirds",
            ramp={"at": 1.0, "factor": 0.4, "ease": 0.3, "hold": 0.2})


def test_window_to_episode_accepts_a_ramp_the_clip_can_carry():
    clip = _clip(fps=60.0)
    ep = edit_plan.window_to_episode(
        clip, clip.windows[0], composition="lead", grid="thirds",
        ramp={"at": 1.0, "factor": 0.4, "ease": 0.3, "hold": 0.2})
    assert ep.ramp == {"at": 1.0, "factor": 0.4, "ease": 0.3, "hold": 0.2}


# --- EDL.look: the mood preset's default, selection.json's override (design 2026-08-13 §6) --

from scripts.lib.look import LookSpec


def _look_selection():
    return {"episodes": [{"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"}]}


def test_an_unauthored_look_comes_from_the_preset():
    edl = edit_plan.build_edl(_footage(), _look_selection(), preset=moodpreset.resolve("moody"),
                              look=moodpreset.resolve("moody").look, aspect=(9, 16))
    assert edl.look == LookSpec(vignette=0.40, fade=1.0, fade_in=0.0)


def test_selection_json_overrides_the_preset():
    sel = {**_look_selection(), "look": {"vignette": 0.1, "fade": 0.2}}
    edl = edit_plan.build_edl(_footage(), sel, preset=moodpreset.resolve("moody"),
                              look=moodpreset.resolve("moody").look, aspect=(9, 16))
    assert edl.look == LookSpec(vignette=0.1, fade=0.2)


def test_an_authored_no_look_beats_the_preset():
    # {"vignette": 0, "fade": 0} is falsy-looking and meaningful: the author said no
    sel = {**_look_selection(), "look": {"vignette": 0, "fade": 0}}
    edl = edit_plan.build_edl(_footage(), sel, preset=moodpreset.resolve("moody"),
                              look=moodpreset.resolve("moody").look, aspect=(9, 16))
    assert edl.look == LookSpec()


def test_an_authored_empty_look_object_beats_the_preset():
    # {} is the spelling that actually discriminates a truthiness bug from `is not
    # None`: {"vignette": 0, "fade": 0} above is a non-empty dict (truthy), so it would
    # pass even a buggy `if sel_look:` check. {} is falsy — only `is not None` resolves
    # it to "the author decided" rather than "nothing was authored".
    sel = {**_look_selection(), "look": {}}
    edl = edit_plan.build_edl(_footage(), sel, preset=moodpreset.resolve("moody"),
                              look=moodpreset.resolve("moody").look, aspect=(9, 16))
    assert edl.look == LookSpec()


def test_build_edl_without_a_look_or_a_selection_override_stays_unauthored():
    # No `look=` argument and no selection.json key: EDL.look stays None, the same
    # "never authored" state a hand-authored SP1 EDL.json reads as.
    edl = edit_plan.build_edl(_footage(), _look_selection())
    assert edl.look is None


# --- write_edit_plan's own fallback resolution (final-findings.md I-2) --------------
#
# Every test above exercises build_edl directly, passing `look=` explicitly — none of
# them can see the bug that shipped: write_edit_plan ALWAYS passed preset.look, even
# when moodpreset.resolve fell back to BALANCED, so a mood-less/skipped brief set
# EDL.look = LookSpec(vignette=0.0, fade=0.5) instead of leaving it None. That reached
# deliver as a real fade=t=in/fade=t=out pair — every autonomous reel opened on a
# black frame, an editorial decision nobody made (pre-slice `deliver` had no video
# fade at all). These two pin write_edit_plan's OWN resolution, the layer the bug
# actually lived in.

def test_write_edit_plan_leaves_the_look_unauthored_when_no_mood_matches(tmp_path):
    # mood="unspecified" matches no scripts.lib.mood.MOOD_ANCHORS token, so
    # moodpreset.resolve falls back to BALANCED (see the housekeeping-task comment on
    # _write_spec above) — and EDL.look must stay None, not fill from BALANCED.look.
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection())
    spec_path = _write_spec(tmp_path, mood="unspecified")
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path), spec=spec_path)
    assert result["status"] == "written"
    edl = EDL.from_json(str(tmp_path / "EDL.json"))
    assert edl.look is None


def test_write_edit_plan_fills_the_look_from_a_matched_preset(tmp_path):
    # The opposite case: a mood that DOES match a preset still fills EDL.look from it,
    # so the fix above did not turn "unauthored" into "always unauthored".
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection())
    spec_path = _write_spec(tmp_path, mood="dark and moody")
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path), spec=spec_path)
    assert result["status"] == "written"
    edl = EDL.from_json(str(tmp_path / "EDL.json"))
    assert edl.look == LookSpec(vignette=0.40, fade=1.0, fade_in=0.0)


# --- outro fit: edit_plan applies the pure ladder to the last episode (design
# 2026-08-14-music-outro-fit-design.md §6/§7) -----------------------------------------


def _footage_with(*, source, dur, scene_cuts):
    """A single-clip Footage for the outro-fit tests below — _apply_outro only ever
    reads clip.source/dur/room_after, never clip.windows, so windows stays empty
    rather than carrying _clip's unrelated default window. Built on _clip (not a bare
    FootageClip(...)) to inherit its fps/res, and scene_cuts is coerced to a list:
    FootageClip.__post_init__ requires a real list — a tuple (including the empty ()
    a caller reaches for) fails its isinstance check."""
    return Footage(clips=[_clip(source=source, dur=dur, scene_cuts=list(scene_cuts), windows=[])])


def _edl_ep(**kw):
    """A minimal EDLEpisode with every required field defaulted — none of this file's
    other episode helpers (_ep/_plain_episode/_ramped_episode) take an arbitrary
    `start`, which the tests below need to place two episodes back to back."""
    base = dict(source="a.mp4", start=0.0, dur=1.0, shot_type="wide",
                composition="center", grid="thirds", layout="fill")
    base.update(kw)
    return EDLEpisode(**base)


def test_apply_outro_extends_the_last_episode(tmp_path):
    """The reel grows to line + fade, and the growth lands on the LAST episode's dur."""
    footage = _footage_with(source="a.mp4", dur=30.0, scene_cuts=())
    eps = [_edl_ep(source="a.mp4", start=0.0, dur=10.0),
           _edl_ep(source="a.mp4", start=12.0, dur=4.0)]
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(15.0,), vocal_spans=((15.0, 17.0),))
    out, fit = edit_plan._apply_outro(eps, footage, music, fade=0.5, brief_len=None)
    assert fit.rung == "gap" and fit.line == 15.0
    assert fit.reel_dur == pytest.approx(15.5)
    assert out[-1].dur == pytest.approx(4.0 + 1.5)     # 14.0 realized -> 15.5
    assert out[0].dur == 10.0                          # only the last one moves


def test_apply_outro_refuses_to_move_a_ramped_last_episode(tmp_path, capsys):
    """A ramp makes play_dur() a non-linear function of dur; moving it would need the
    ramp arithmetic and is out of this slice's scope. Skipped and logged, not guessed."""
    footage = _footage_with(source="a.mp4", dur=30.0, scene_cuts=())
    eps = [_edl_ep(source="a.mp4", start=0.0, dur=10.0),
           _edl_ep(source="a.mp4", start=12.0, dur=4.0,
                   # at=2.0, not the design doc's 1.0: the region [at-hold/2-ease,
                   # at+hold/2+ease] = [0.75, 3.25] must sit inside this 4.0s window
                   # (EDLEpisode.__post_init__ -> ramp.validate_window enforces it),
                   # and at=1.0 puts the region's start at -0.25s — before the window
                   # even begins. Only `at` moved; factor/ease/hold are unchanged.
                   ramp={"at": 2.0, "factor": 0.5, "ease": 1.0, "hold": 0.5})]
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(15.0,), vocal_spans=((15.0, 17.0),))
    out, fit = edit_plan._apply_outro(eps, footage, music, fade=0.5, brief_len=None)
    assert fit.rung == "unchanged" and out == eps
    assert "ramp" in capsys.readouterr().err


def test_apply_outro_is_bounded_by_the_closing_shot(capsys):
    """room_after stops at the next scene cut — the fit must not splice two shots."""
    footage = _footage_with(source="a.mp4", dur=30.0, scene_cuts=(16.2,))
    eps = [_edl_ep(source="a.mp4", start=0.0, dur=10.0),
           _edl_ep(source="a.mp4", start=12.0, dur=4.0)]
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(15.0,), vocal_spans=((15.0, 17.0),))
    out, fit = edit_plan._apply_outro(eps, footage, music, fade=0.5, brief_len=None)
    assert fit.rung == "unchanged" and out[-1].dur == 4.0


def test_apply_outro_shrink_floor(capsys):
    """MIN_LAST keeps the closing shot readable."""
    footage = _footage_with(source="a.mp4", dur=30.0, scene_cuts=())
    eps = [_edl_ep(source="a.mp4", start=0.0, dur=10.0),
           _edl_ep(source="a.mp4", start=12.0, dur=1.2)]
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      # bars=(9.0,), not the design doc's (10.2,): at 10.2 the ladder's
                      # SECOND rung (the NO_GAP_FADE=1.5s retry) lands at 10.2+1.5=11.7,
                      # which is ABOVE the 11.2s realized total — a grow, not a shrink —
                      # so shrink_max (0.2s, from last.play_dur() 1.2 - MIN_LAST 1.0)
                      # never gets asked and the fit lands on rung "no-gap" instead of
                      # "unchanged". 9.0 keeps BOTH the 0.5s and the 1.5s fade shrinking
                      # past that 0.2s floor, so the whole ladder empties out.
                      bars=(9.0,), vocal_spans=((9.0, 11.0),))
    out, fit = edit_plan._apply_outro(eps, footage, music, fade=0.5, brief_len=None)
    assert fit.rung == "unchanged" and out[-1].dur == pytest.approx(1.2)


def test_a_growing_outro_fit_sets_the_target_that_ships():
    """The clamp in _back_edge_target must not discard the fit's growth.

    _bind_pacing gives a same-length spine `target_dur == sum(pre-fit play_durs)` by
    construction, so ANY growth makes realized > spine.target_dur and the over-flow
    clamp returns the PRE-fit total. The EDL then disagrees with its own episodes and
    edl_to_reel escalates on `length` — measured end-to-end by Task 6, whose real-
    ffmpeg proof of a no-slack spine hit exactly this and got back `stop_and_report`
    ({"check": "length", "detail": {"dur": 10.7, "target": 10.0}}). The clamp is
    right for footage the music cannot cover; the fit's growth is not that, because
    fit_outro already bounded it by music_dur (Task 5b; design 2026-08-14 §6)."""
    footage = Footage(clips=[_clip(source="a.mp4", dur=30.0, scene_cuts=[], windows=[
        _window(start=0.0, dur=6.0, shot_type="wide", description="approach"),
        _window(start=8.0, dur=4.0, shot_type="wide", description="closer")])])
    sel = {"episodes": [
        {"source": "a.mp4", "window": 0, "composition": "lead", "grid": "thirds"},
        {"source": "a.mp4", "window": 1, "composition": "lead", "grid": "thirds"}]}
    # NO SLACK: 2 slots for 2 episodes, target_dur == 6.0 + 4.0 exactly — the shape
    # pacing.fit_spine actually produces. _bind_pacing fits each episode's dur to its
    # own slot's dur exactly, so a spine with as many slots as episodes always has
    # spine.target_dur == the pre-fit episode total BY CONSTRUCTION (design §6).
    spine = _spine([6.0, 4.0], tempo=120.0)
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(10.2,), vocal_spans=((10.2, 12.0),))
    # Derive the expected numbers from fit_outro directly, using the SAME grow_max/
    # shrink_max _apply_outro will itself compute for this fixture (clip dur 30.0, no
    # scene cuts, closing episode start=8.0/dur=4.0): room_after(8.0) = 30.0 - 8.0 =
    # 22.0, so grow_max = 22.0 - 4.0 = 18.0; shrink_max = 4.0 - outro.MIN_LAST = 3.0.
    fit = outro.fit_outro(music.bars, music.vocal_spans, reel_dur=6.0 + 4.0,
                          bar_s=outro.bar_seconds(120.0), fade=0.5, music_dur=42.0,
                          grow_max=18.0, shrink_max=3.0)
    assert fit.rung == "gap" and fit.moved > 0    # fixture sanity: it must actually grow

    edl = edit_plan.build_edl(footage, sel, pacing=spine, music=music)
    assert edl.outro.rung == "gap"
    assert edl.outro.moved > 0
    assert edl.outro.reel_dur == pytest.approx(fit.reel_dur)
    assert edl.target_dur == pytest.approx(edl.outro.reel_dur)
    assert edl.target_dur == pytest.approx(sum(e.play_dur() for e in edl.episodes))


def test_an_unchanged_outro_fit_does_not_unclamp_an_unrelated_pacing_overflow():
    """The `fit.rung != "unchanged"` exclusion in build_edl's override guards a real
    hole, found in code review of Task 5b (not by this test, until now).

    On the "unchanged" rung, OutroFit.reel_dur is just the raw pre-fit `realized`
    passed straight through _apply_outro's early return (music.bars empty, or no
    reachable line) — it never passes through outro._candidates' music_dur bound,
    which only applies on the "gap"/"no-gap" rungs. So an "unchanged" fit's reel_dur
    carries NO bound against the music at all.

    Here the over-flow has NOTHING to do with the outro fit: reusing the precedented
    _sel3()/_spine2() shape (test_build_edl_pacing_overflow_tail_unbound,
    test_build_edl_back_edge_clamps_an_overflow_to_the_fragment) — 3 episodes
    (durs 2.0/3.0/2.5) against a 2-slot spine (target_dur=5.15) — _bind_pacing
    leaves the 3rd episode unbound at its own 2.5s, so realized (2.1+3.05+2.5=7.65)
    over-flows the 5.15s spine independently of music. `_back_edge_target`'s clamp
    is the ONLY thing standing between that unbound tail and a target_dur the music
    (bars=() here — no grid at all) cannot be shown to cover. If the guard were
    `if fit is not None:` (dropping the rung check), `target` would become the
    unclamped `fit.reel_dur` (7.65) instead of the clamped 5.15 — silently
    reproducing the exact class of bug Task 5b fixed, through a door the fit itself
    never opens."""
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(), vocal_spans=())                 # no bar grid; beats out of reach
    edl = edit_plan.build_edl(_footage(), _sel3(), pacing=_spine2(), music=music)
    assert edl.outro.rung == "unchanged"
    assert edl.outro.reel_dur == pytest.approx(7.65)           # unbound tail included, UNCLAMPED
    assert edl.target_dur == pytest.approx(5.15)                # _back_edge_target's clamp must hold


def test_a_reachable_line_does_not_unclamp_a_PRE_EXISTING_pacing_overflow(capsys):
    """The sibling hole the `rung != "unchanged"` guard alone does NOT close (final
    review I-3 -> I-2): a cut that ALREADY over-flowed the spine before the fit ran.

    test_an_unchanged_outro_fit_does_not_unclamp_an_unrelated_pacing_overflow above
    covers the case where no line is reachable — there the rung check does the work.
    Give the SAME over-flowing fixture a bar line the closing shot can reach and the
    rung becomes "gap", so the rung check waves it through and the override replaces
    the clamped 5.15s target with the fit's 8.0s. Nothing then escalates, even though
    _back_edge_target has just logged that the excess "escalates at the reel gate" —
    a stale PACING.json's over-flow ships silently, and the log is false while it does.

    The fit's own bound is only over the length IT chose (outro._candidates' music_dur
    condition). The 2.85s of pre-existing excess never passed through it, so the
    override may only fire when there was no pre-existing over-flow at all.

    Same precedented shape as the sibling: _sel3() (durs 2.0/3.0/2.5) against the
    2-slot _spine2() (target_dur 5.15) leaves the 3rd episode unbound at 2.5s, so
    realized = 2.1 + 3.05 + 2.5 = 7.65s > 5.15s independently of any music. The line
    at 7.5s is inside the +/-one-bar band of 7.65 (bar_s = 2.0 at 120 BPM), the
    closing B.mp4 shot has room to grow into it, and (7.5, 9.0) leaves 1.5s of
    vocal-free tail — so the fitter answers "gap" at 7.5 + 0.5 = 8.0s."""
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(7.5,), vocal_spans=((7.5, 9.0),))
    edl = edit_plan.build_edl(_footage(), _sel3(), pacing=_spine2(), music=music)
    # fixture sanity: the fit really does land on a line here, so the rung check alone
    # cannot be what saves us — otherwise this test would pass for the wrong reason
    assert edl.outro.rung == "gap" and edl.outro.reel_dur == pytest.approx(8.0)
    # ...and the target must STILL be the clamped fragment length, not the fit's 8.0
    assert edl.target_dur == pytest.approx(5.15)
    err = capsys.readouterr().err
    assert "escalates at the reel gate" in err        # _back_edge_target's line stays TRUE
    assert "over-flowed the 5.15s spine before the fit ran" in err   # and the decline is said


def test_music_without_pacing_says_it_did_nothing(capsys):
    """--music is accepted without --pacing and then fits NOTHING: the whole fit sits
    inside build_edl's `pacing is not None` branch. Silence there reads as "the fit
    ran and found nothing" — the house style is to say so (final review, minor)."""
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(7.5,), vocal_spans=((7.5, 9.0),))
    edl = edit_plan.build_edl(_footage(), _sel3(), music=music)     # no pacing
    assert edl.outro is None                                        # nothing was fitted
    assert "--music was supplied without --pacing" in capsys.readouterr().err


def test_build_edl_refuses_a_spine_fitted_to_a_different_track():
    # The 2026-08-03 run: PACING.json fitted at 140.625 BPM against a 110.294 BPM
    # MUSIC.json — nine hours older, and belonging to the track that was swapped out.
    # _bind_pacing's half-beat guard is a DURATION guard: it fires only once a stale
    # spine is bound, and it never says which track the spine came from (design
    # 2026-08-15 §2.2). _spine2() is 120.0 BPM.
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=90.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0)
    with pytest.raises(ValueError, match="DIFFERENT track"):
        edit_plan.build_edl(_footage(), _sel3(), pacing=_spine2(), music=music)


def test_build_edl_accepts_a_spine_and_music_from_the_same_track():
    # The paired proof. pacing.py copies MusicSpec.tempo straight into the spine, so an
    # honest pair is bit-identical and must still build — without this, a blanket
    # "--pacing with --music always raises" would satisfy the test above.
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0)
    edl = edit_plan.build_edl(_footage(), _sel3(), pacing=_spine2(), music=music)
    assert edl.episodes[0].beat_slot == 0


def test_build_edl_tolerates_a_sub_half_bpm_tempo_difference():
    # _TEMPO_TOL exists so a re-analysis or a hand-typed tempo does not trip the guard.
    # 0.4 BPM is inside it; the 30 BPM case above proves the guard is not merely absent.
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.4,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0)
    edl = edit_plan.build_edl(_footage(), _sel3(), pacing=_spine2(), music=music)
    assert edl.episodes[0].beat_slot == 0


def test_build_edl_checks_tempo_before_binding_the_spine():
    # ORDER, not just presence. The four tests above all bind through _spine2(), whose
    # slots sit inside _bind_pacing's own snap allowance — so they cannot tell "tempo
    # checked before _bind_pacing" from "tempo checked after": relocating the guard to
    # run AFTER _bind_pacing left every one of them green (2026-08-15 mutation battery,
    # row 7 — a real coverage hole, found by running the mutation, not anticipated).
    # This spine ALSO fails _bind_pacing's half-beat snap (slot 0 is 5.0s against a
    # 2.0s episode), so only "tempo checked first" reaches the DIFFERENT-track message
    # before _bind_pacing ever runs; "tempo checked after bind" hits _bind_pacing's own
    # "fitted to a different edit" refusal instead, which does not match this regex.
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=90.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0)
    mismatched = Spine(slots=(Slot(0, 0.0, 5.0, 0.2, "hook"),
                              Slot(1, 5.0, 8.0, 0.9, "peak")), target_dur=13.0, tempo=120.0)
    with pytest.raises(ValueError, match="DIFFERENT track"):
        edit_plan.build_edl(_footage(), _sel3(), pacing=mismatched, music=music)


def test_the_fit_carries_the_briefs_length_onto_the_edl(capsys):
    """brief_len reaches OutroFit, so EDL.md — not only the stderr line — can state
    the distance from SPEC.length_s (design §6; final review I-3)."""
    footage = _footage_with(source="a.mp4", dur=30.0, scene_cuts=())
    eps = [_edl_ep(source="a.mp4", start=0.0, dur=10.0),
           _edl_ep(source="a.mp4", start=12.0, dur=4.0)]
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(15.0,), vocal_spans=((15.0, 17.0),))
    _out, fit = edit_plan._apply_outro(eps, footage, music, fade=0.5, brief_len=12.0)
    assert fit.rung == "gap" and fit.brief_len == 12.0
    assert "vs the brief's 12.0s" in capsys.readouterr().err


def test_an_unfittable_reel_still_carries_the_briefs_length(capsys):
    """The `unchanged` early returns build their OutroFit in edit_plan, not in
    fit_outro — so they need the brief threaded through separately, and a reel that
    could not be fitted is exactly when the distance from the brief matters."""
    footage = _footage_with(source="a.mp4", dur=30.0, scene_cuts=())
    eps = [_edl_ep(source="a.mp4", start=0.0, dur=10.0)]
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(), vocal_spans=())                     # no bar grid; beats out of reach
    _out, fit = edit_plan._apply_outro(eps, footage, music, fade=0.5, brief_len=12.0)
    assert fit.rung == "unchanged" and fit.brief_len == 12.0


def test_write_edit_plan_threads_music_into_the_fit(tmp_path, monkeypatch):
    seen = {}
    real = edit_plan.build_edl
    monkeypatch.setattr(edit_plan, "build_edl",
                        lambda *a, **k: seen.update(k) or real(*a, **k))
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection())
    mj = tmp_path / "MUSIC.json"
    mj.write_text(json.dumps(MusicSpec("t.wav", 0.0, 2.0, 120.0,
                                       (0.0, 0.5, 1.0, 1.5), (0.3,), 2.0).to_dict()))
    edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path), music=str(mj))
    assert isinstance(seen["music"], MusicSpec)


# --- named-absence Task 3: the three causes _apply_outro knows itself (design
# 2026-09-07-named-absence-design.md §3) ----------------------------------------


def _two_episodes(*, ramp_last=False):
    """Two back-to-back episodes on _footage()'s own two sources (A.mp4/B.mp4) —
    _apply_outro only ever reads the LAST one (source/start/dur/ramp), so the first
    exists only to make this a cut, not a single clip. `ramp_last` reuses
    _ramped_episode's own region ([0.6s, 1.4s]), well inside this 2.5s window, so
    validate_window never fights the fixture."""
    last = dict(source="B.mp4", start=1.0, dur=2.5)
    if ramp_last:
        last["ramp"] = {"at": 1.0, "factor": 0.5, "ease": 0.3, "hold": 0.2}
    return [_edl_ep(source="A.mp4", start=0.5, dur=2.0), _edl_ep(**last)]


def _outro_music(**kw):
    """MusicSpec built from this file's own outro fixtures' shape (e.g.
    test_apply_outro_extends_the_last_episode) — bars/vocal_spans are the only
    fields a caller below overrides; none of the four tests reach the ladder that
    reads anything past them.

    Named `_outro_music`, not the brief's own `_music`: a DIFFERENT `_music(tmp_path,
    ...)` already lives at line ~1593 (the music_digest section, whose own comment
    notes it is "kept exactly as named in task-3-brief.md" — a different slice's
    Task 3). Both briefs independently reached for the same free name; this one loses
    since it is defined first and would otherwise be silently shadowed by the later
    def at module-exec time (the `_digest_spine`/`_digest_footage` rename just above
    that section is the same move for `_spine`/`_footage`)."""
    d = dict(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
             beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
             bars=(15.0,), vocal_spans=((15.0, 17.0),))
    d.update(kw)
    return MusicSpec(**d)


def test_apply_outro_runs_on_the_beats_when_the_music_has_no_bar_grid():
    """All four MUSIC*.json of the first real run carried `bars: []` and the fit
    reported "n/a" (retro R7.1); the second run's track had none either (retro
    2026-10-16 S7). A bar-less window is no longer an absence: the fit runs on its
    beats, and "no-bars" is left for artifacts written before that — MusicSpec refuses
    an empty beat list, so no window today has neither."""
    eps, fit = edit_plan._apply_outro(_two_episodes(), _footage(),
                                      _outro_music(bars=()), fade=0.3, brief_len=45.0)
    assert fit.grid == "beat" and fit.cause != "no-bars"
    assert fit.brief_len == 45.0


def test_apply_outro_names_a_ramped_closing_episode():
    eps, fit = edit_plan._apply_outro(_two_episodes(ramp_last=True), _footage(),
                                      _outro_music(), fade=0.3, brief_len=None)
    assert (fit.rung, fit.cause) == ("unchanged", "ramped-closer")


def test_apply_outro_names_a_closing_source_missing_from_footage():
    eps, fit = edit_plan._apply_outro(_two_episodes(), _footage(drop_last=True),
                                      _outro_music(), fade=0.3, brief_len=None)
    assert (fit.rung, fit.cause) == ("unchanged", "closer-not-in-footage")


def test_apply_outro_names_an_empty_cut():
    """_apply_outro's guard is `not episodes or not music.bars` — one branch for two
    unrelated absences. Unreachable through build_edl today; lumping it under
    'no-bars' would re-create in miniature the collapse this field ends."""
    eps, fit = edit_plan._apply_outro([], _footage(), _outro_music(), fade=0.3, brief_len=None)
    assert (fit.rung, fit.cause) == ("unchanged", "no-episodes")


# --- Task 7 mutation battery: two coverage holes a review found in the original
# rows (progress.md, Task 5's two warnings) -------------------------------------


def test_build_edl_applies_the_outro_fit_after_binding_not_before():
    """Row 9. No existing test can see a call-order swap of _apply_outro/_bind_pacing
    INSIDE build_edl: the pacing-binding tests (test_bind_applies_a_fitted_slot_
    verbatim etc.) call _bind_pacing directly, and every other outro test either
    skips pacing or uses a spine the fit never grows past. This drives real pacing +
    real music through build_edl together, sized so the fit's own growth (0.7s) trips
    _bind_pacing's half-beat guard (0.25s at 120 BPM) if _apply_outro ever ran BEFORE
    binding instead of after it — an outro extension routed through the slot is
    exactly landmine #3 in the design's §8."""
    footage = Footage(clips=[_clip(source="a.mp4", dur=30.0, scene_cuts=[], windows=[
        _window(start=0.0, dur=6.0, shot_type="wide", description="approach"),
        _window(start=8.0, dur=4.0, shot_type="wide", description="closer")])])
    sel = {"episodes": [
        {"source": "a.mp4", "window": 0, "composition": "lead", "grid": "thirds"},
        {"source": "a.mp4", "window": 1, "composition": "lead", "grid": "thirds"}]}
    spine = _spine([6.0, 4.0], tempo=120.0)
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(10.2,), vocal_spans=((10.2, 12.0),))
    # fixture sanity: the fit really does move the closing episode past the bind
    # guard's allowance (30/120 + 1e-3 = 0.251s) -- otherwise a call-order swap would
    # be invisible either way, and this test would prove nothing
    fit = outro.fit_outro(music.bars, music.vocal_spans, reel_dur=10.0,
                          bar_s=outro.bar_seconds(120.0), fade=0.5, music_dur=42.0,
                          grow_max=18.0, shrink_max=3.0)
    assert fit.rung == "gap" and fit.moved == pytest.approx(0.7) and fit.moved > 0.3
    # the CORRECT order (bind, THEN fit) must not raise, and the fit must land
    edl = edit_plan.build_edl(footage, sel, pacing=spine, music=music)
    assert edl.outro.rung == "gap" and edl.outro.moved == pytest.approx(0.7)


def test_build_edl_threads_the_authored_look_fade_into_the_outro_fit():
    """Row 12. Every existing outro test passes fade=0.5 (mix's own default), so a
    `resolved_fade` hardcoded to the literal 0.5 in build_edl is invisible to all of
    them. Author a look.fade of 1.0 and prove _apply_outro actually receives IT, not
    a constant standing in for it."""
    footage = Footage(clips=[_clip(source="a.mp4", dur=30.0, scene_cuts=[], windows=[
        _window(start=0.0, dur=6.0, shot_type="wide", description="approach"),
        _window(start=8.0, dur=4.0, shot_type="wide", description="closer")])])
    sel = {"episodes": [
        {"source": "a.mp4", "window": 0, "composition": "lead", "grid": "thirds"},
        {"source": "a.mp4", "window": 1, "composition": "lead", "grid": "thirds"}],
        "look": {"vignette": 0.0, "fade": 1.0}}
    spine = _spine([6.0, 4.0], tempo=120.0)
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(10.2,), vocal_spans=((10.2, 12.0),))
    edl = edit_plan.build_edl(footage, sel, pacing=spine, music=music)
    assert edl.outro.fade == 1.0
    assert edl.outro.reel_dur == pytest.approx(11.2)     # line 10.2 + the AUTHORED 1.0 fade


# --- base_dur: the scenario's own length, the half-beat guard's fixed point (design
# 2026-08-16-pacing-fixed-point-design.md §2/§3) --------------------------------------


def test_window_to_episode_records_the_projected_length():
    clip = FootageClip(source="a.mp4", dur=20.0, res=(640, 360), fps=30.0, windows=[
        FootageWindow(start=1.0, dur=4.0, shot_type="wide", people=1, motion=0.3, shake=0.0)])
    ep = edit_plan.window_to_episode(clip, clip.windows[0], composition="lead", grid="thirds")
    assert ep.dur == 4.0
    assert ep.base_dur == 4.0


def test_base_dur_cannot_be_authored_from_selection():
    # `dur` is passed positionally and editorial is forwarded as **kwargs, so an
    # author trying to set either gets the same named refusal.
    clip = FootageClip(source="a.mp4", dur=20.0, res=(640, 360), fps=30.0, windows=[
        FootageWindow(start=1.0, dur=4.0, shot_type="wide", people=1, motion=0.3, shake=0.0)])
    with pytest.raises(ValueError, match="unknown or missing editorial field"):
        edit_plan.window_to_episode(clip, clip.windows[0], composition="lead",
                                    grid="thirds", base_dur=9.0)


def test_bind_pacing_accepts_a_slot_that_matches_the_SCENARIO_not_the_bound_length():
    # The deadlock, in one assert: an episode already grown 0.70s by an outro fit
    # binds against a spine fitted to its 4.00s scenario length. Half a beat at
    # 120 BPM is 0.25s, so the OLD guard (comparing 4.70 against 4.00) refused.
    ep = _ep(dur=4.70, base_dur=4.00)
    spine = Spine(slots=(Slot(0, 0.0, 4.0, 0.5, "hook", line=4.0, dev=0.0),),
                  target_dur=4.0, tempo=120.0)
    bound = edit_plan._bind_pacing([ep], spine)
    assert bound[0].dur == 4.0
    assert bound[0].base_dur == 4.0
    assert bound[0].beat_slot == 0


def test_bind_pacing_still_refuses_a_spine_fitted_to_a_different_edit():
    ep = _ep(dur=4.0, base_dur=4.0)
    spine = Spine(slots=(Slot(0, 0.0, 7.3, 0.5, "hook", line=7.3, dev=0.0),),
                  target_dur=7.3, tempo=120.0)
    with pytest.raises(ValueError, match="fitted to a different edit"):
        edit_plan._bind_pacing([ep], spine)


def test_bind_pacing_names_the_arm_when_an_episode_has_no_base_dur():
    ep = _ep(dur=4.70)                       # no base_dur: pre-slice or hand-authored
    spine = Spine(slots=(Slot(0, 0.0, 4.0, 0.5, "hook", line=4.0, dev=0.0),),
                  target_dur=4.0, tempo=120.0)
    with pytest.raises(ValueError, match="carries no `base_dur`"):
        edit_plan._bind_pacing([ep], spine)


def test_bind_pacing_refusal_always_carries_the_escape_detour():
    # Final review Finding 1: the population that actually reaches this refusal from
    # a STALE PACING.json is not the one the arm note alone would catch. pacing.py
    # fits a base_dur-less EDL.json by falling back to play_dur() (correct, by
    # design), but build_edl then re-projects FRESH episodes via window_to_episode,
    # which ALWAYS sets base_dur — so `ep.base_dur is not None` is true right here,
    # the arm note stays empty, and a reader trusting the arm alone would wrongly
    # conclude no detour applies. The detour must appear regardless.
    ep = _ep(dur=4.00, base_dur=4.00)
    spine = Spine(slots=(Slot(0, 0.0, 4.70, 0.5, "hook", line=4.70, dev=0.0),),
                  target_dur=4.70, tempo=120.0)
    with pytest.raises(ValueError, match=r"rebuild the EDL WITHOUT --pacing/--music") as e:
        edit_plan._bind_pacing([ep], spine)
    assert "NOTE: this episode carries no `base_dur`" not in str(e.value)


# --- music_digest: bind a spine to the music WINDOW it was fitted to (design
# 2026-08-16-pacing-fixed-point-design.md §4). `_spine` (line ~943, a list-of-durations
# binding helper) and `_footage` (line ~73, the two-clip A.mp4/B.mp4 fixture) already
# name unrelated fixtures elsewhere in this file, so the digest fixtures below are
# `_digest_spine`/`_digest_footage` instead of shadowing them; `_music`/`_selection` are
# free names, kept exactly as named in task-3-brief.md. -------------------------------


def _digest_spine(tempo=120.0, digest=""):
    return Spine(slots=(Slot(0, 0.0, 4.0, 0.5, "hook", line=4.0, dev=0.0),),
                 target_dur=4.0, tempo=tempo, music_digest=digest)


def _music(tmp_path, tempo=120.0, offset=0.0, track=None):
    # Beat count DERIVED from the window: MusicSpec refuses a beat outside
    # [0, duration], and at 110 BPM a hardcoded 40 beats overruns a 20s window.
    if track is None:
        track = tmp_path / "t.wav"
        track.write_bytes(b"bytes")
    step = 60.0 / tempo
    return MusicSpec(track=str(track), start_offset=offset, duration=20.0, tempo=tempo,
                     beats=tuple(i * step for i in range(int(20.0 / step))),
                     energy=(0.3,) * 10, energy_hz=2.0)


def _digest_footage(tmp_path, window_dur=4.0):
    return Footage(clips=[FootageClip(source="a.mp4", dur=20.0, res=(640, 360), fps=30.0,
                                      windows=[FootageWindow(start=0.0, dur=window_dur,
                                                             shot_type="wide", people=1,
                                                             motion=0.3, shake=0.0)])])


def _selection():
    return {"episodes": [{"source": "a.mp4", "window": 0,
                          "composition": "lead", "grid": "thirds"}]}


def test_build_edl_refuses_a_spine_fitted_to_a_different_music_window(tmp_path):
    # SAME track, SAME tempo, different in-point: the tempo check cannot see this.
    m = _music(tmp_path, offset=147.772)
    stale = music_identity(m.track, 46.0, m.duration)
    with pytest.raises(ValueError, match="fitted to a different music window"):
        edit_plan.build_edl(_digest_footage(tmp_path), _selection(),
                            pacing=_digest_spine(digest=stale), music=m)


def test_build_edl_binds_when_the_window_identity_matches(tmp_path):
    m = _music(tmp_path)
    good = music_identity(m.track, m.start_offset, m.duration)
    edl = edit_plan.build_edl(_digest_footage(tmp_path), _selection(),
                              pacing=_digest_spine(digest=good), music=m)
    assert edl.episodes[0].beat_slot == 0


def test_build_edl_names_the_not_checked_arm_and_falls_back_to_tempo(tmp_path, capsys):
    m = _music(tmp_path, tempo=110.0)
    with pytest.raises(ValueError, match="belongs to a DIFFERENT track"):
        edit_plan.build_edl(_digest_footage(tmp_path), _selection(),
                            pacing=_digest_spine(tempo=140.625), music=m)
    err = capsys.readouterr().err
    assert "music identity not-checked" in err
    assert "records no music_digest" in err


def test_build_edl_binds_silently_on_a_pre_slice_pacing_json_with_a_readable_track(tmp_path, capsys):
    # The backward-compatibility claim the not-checked rung rests on: a PACING.json
    # written before this slice has NO music_digest at all (_digest_spine's own ""
    # default), but MUSIC.json's track is perfectly readable and the tempo agrees —
    # the ladder must fall back to the tempo comparison and bind, not refuse.
    #
    # Every OTHER music+pacing test in this file (the ~1120-1450 block) passes a bare
    # `MusicSpec(track="t.wav", ...)` with no file ever written at tmp_path, so
    # music_identity() on IT also returns "" (OSError on a nonexistent path) — those
    # tests only ever exercise the BOTH-SIDES-empty leg of the ladder. This is the one
    # combination where the track is readable (want is non-empty) but the recorded
    # digest still is not — nothing pinned it before this test.
    m = _music(tmp_path)   # tempo=120.0, offset=0.0 — a REAL file under tmp_path
    edl = edit_plan.build_edl(_digest_footage(tmp_path), _selection(),
                              pacing=_digest_spine(), music=m)   # digest="" (the default)
    assert edl.episodes[0].beat_slot == 0
    err = capsys.readouterr().err
    assert "music identity not-checked" in err
    assert "records no music_digest" in err


# --- length-band reconciliation: the preset's asl FLOOR vs. the footage's carved
# floor (design 2026-09-03 §4) — only the floor is checkable; a preset ceiling
# above the carve ceiling is always reachable through edit_plan's own span merge.

def test_a_mood_floor_under_the_carved_floor_is_a_suggestion_not_a_refusal(monkeypatch, tmp_path,
                                                                            capsys):
    """Backlog U2 (2026-10-20): a mood's shot-length band is a recommendation the brief
    offers, never a rule — so a mood floor the footage cannot reach is said in the log
    and the build goes on. Only a band the user chose (SPEC.asl) can refuse."""
    # A carved floor above the preset's floor, so the gate is reachable at all:
    # at carve.DEFAULT_BAND every shipped preset passes (design §4).
    deep = moodpreset.MoodPreset("deep", mood.MoodVector(0.5, 0.5, 0.5),
                                 {"close": 0.3, "medium": 0.4, "wide": 0.3}, (2.5, 5.0))
    monkeypatch.setattr(moodpreset, "PRESETS", (deep,))
    footage = replace(_footage(), band=(3.0, 4.0))
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection(), footage=footage)
    # moodpreset.resolve matches on the mood TEXT against scripts.lib.mood's anchor
    # vocabulary, not on a preset's name — "deep" itself matches no anchor, which
    # would fall back to BALANCED without ever consulting the patched PRESETS.
    # "brooding" is a real anchor token; since PRESETS above was patched down to
    # exactly one entry, any text that matches SOMETHING routes to that one preset.
    spec_path = _write_spec(tmp_path, mood="brooding")
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path), spec=spec_path)
    assert result["status"] == "written", result
    err = capsys.readouterr().err
    assert "the deep mood suggests shots from 2.5s" in err and "--win-min 2.5" in err
    assert "a suggestion, so the build goes on" in err


def test_a_brief_floor_under_the_carved_floor_still_refuses(tmp_path):
    """The other half of U2: a band the user chose is a decision, and the footage
    cannot honour it — that stays a refusal, named in the brief's own words."""
    footage = replace(_footage(), band=(3.0, 4.0))
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection(), footage=footage)
    spec_path = _write_spec(tmp_path, mood="nostalgic", asl=(2.0, 4.0))
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path), spec=spec_path)
    assert result["status"] == "stop_and_report"
    assert result["finding"]["reason"] == "length-band"
    assert "the brief's --asl floor 2.0s" in result["finding"]["problems"][0]


def test_write_edit_plan_passes_a_carved_band_the_preset_fits_inside(tmp_path):
    # The control: same inputs, a floor the preset clears, and the run proceeds
    # past this gate. Without it the test above passes for a gate that always fires.
    footage = replace(_footage(), band=(1.2, 4.0))
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection(), footage=footage)
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path),
                                       spec=_write_spec(tmp_path))
    assert result["status"] == "written"


def test_write_edit_plan_reports_not_checked_on_a_legacy_footage_without_a_band(tmp_path, capsys):
    # _write_inputs' default footage=None reuses _footage(), which never sets band
    # so it defaults to None — exactly the legacy (pre-2026-09-03) FOOTAGE.json this
    # arm guards, per tests/lib/test_footage.py's own promise that "edit_plan's
    # reconciliation reports not-checked rather than passing green". Mirrors
    # test_build_edl_names_the_not_checked_arm_and_falls_back_to_tempo's capsys
    # pattern (line 1573) for a structurally identical not-checked gate.
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection())
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path), spec=_write_spec(tmp_path))
    assert result["status"] == "written"
    err = capsys.readouterr().err
    assert "length band: not checked" in err
    assert "Re-run footage-intake to record it" in err


def test_write_edit_plan_does_not_refuse_a_brief_less_run_against_a_high_carved_floor(tmp_path, capsys):
    # I-1 (final-findings.md): the BALANCED fallback must never be held to its own
    # asl[0]=1.5s floor — that number is resolve()'s "nothing matched" artifact, not
    # a decision, exactly as `look` (edit_plan.py:681) and `match_grade._resolve_bias`
    # already guard on `preset.name == "balanced"` for the SAME reason: an absent or
    # unmatched brief must never have a taste imposed on it. Before this fix, a carved
    # floor above 1.5s stopped a run that never passed --spec at all, with "reason":
    # "length-band" and a remedy telling the operator to "drop --spec" on a run that
    # had none — reproduced here almost verbatim from the reviewer's repro
    # (`intake --win-min 2.0` then `edit_plan build` with NO --spec).
    footage = replace(_footage(), band=(2.0, 4.0))
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection(), footage=footage)
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path))     # no spec= at all
    assert result["status"] == "written"
    # The log still says something (this file's own idiom: every fallback branch above
    # — variety, look, platform — explains itself rather than going silent), but it must
    # say the check was SKIPPED for the fallback, never claim a comparison happened.
    err = capsys.readouterr().err
    assert "length band: no SPEC mood matched a preset" in err
    assert "never reconciled" in err


def test_write_edit_plan_carries_the_briefs_cast_share_and_reports_screen_time(tmp_path, capsys):
    """retro 2026-10-16 S9: the brief's "both equally" must reach EDL.md and the log at
    CP2, beside the cut's own screen time — REEL_v3 shipped 55/45 unnoticed."""
    sel = _plain_selection()
    sel["episodes"][0]["hero"] = "Lena"
    sel["episodes"][1]["hero"] = "Sergei"
    fp, sp, pp = _write_inputs(tmp_path, sel)
    spec_path = _write_spec(tmp_path, cast=("Lena", "Sergei"),
                            cast_share={"Lena": 1, "Sergei": 1})
    from scripts.lib.footage import DESCRIPTOR_LEN, Cast, CastMember
    cast = tmp_path / "cast.json"
    cast.write_text(json.dumps(Cast(members=[
        CastMember(name=n, descriptor=[1.0 if k == i else 0.0 for k in range(DESCRIPTOR_LEN)])
        for i, n in enumerate(("Lena", "Sergei"))]).to_dict()))
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path), cast=str(cast),
                                       spec=spec_path)
    assert result["status"] == "written", result
    edl = EDL.from_json(str(tmp_path / "EDL.json"))
    assert edl.cast_share == {"Lena": 1.0, "Sergei": 1.0}
    assert "## Screen time" in (tmp_path / "EDL.md").read_text()
    err = capsys.readouterr().err
    assert "screen time: Lena" in err and "brief: Lena 50% · Sergei 50%" in err


def test_screen_time_log_says_when_there_was_no_spec_rather_than_no_share(tmp_path, capsys):
    from scripts.lib.edl import EDL as _EDL, EDLEpisode
    ep = EDLEpisode(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
                    composition="center", grid="thirds", hero="Lena")
    edit_plan._log_screen_time(_EDL(episodes=(ep,)), spec_given=False)
    assert "no SPEC.json was given" in capsys.readouterr().err
    edit_plan._log_screen_time(_EDL(episodes=(ep,)), spec_given=True)
    assert "the brief set no share" in capsys.readouterr().err
    edit_plan._log_screen_time(_EDL(episodes=(ep,), cast_share={"Lena": 1, "Sergei": 1}),
                               spec_given=True)
    err = capsys.readouterr().err
    assert "Sergei 0.0s (0%)" in err and "brief: Lena 50% · Sergei 50%" in err


def test_the_briefs_shot_length_band_outranks_the_presets_and_is_said_out_loud(tmp_path, capsys):
    """retro 2026-10-16 S5: the first plan cut longboard rides to `nostalgic`'s 2-4 s
    band and the operator rejected it at CP2. A brief band replaces the preset's in the
    report, and a cut outside it is named before CP2 — still a report, not a gate."""
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection())
    spec_path = _write_spec(tmp_path, mood="nostalgic", asl=(6, 10))
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path), spec=spec_path)
    assert result["status"] == "written", result
    v = EDL.from_json(str(tmp_path / "EDL.json")).variety
    assert (v.asl_band, v.asl_from) == ((6.0, 10.0), "brief")
    err = capsys.readouterr().err
    assert "length band: the brief asks 6.0–10.0s" in err
    assert f"ASL {v.asl:.2f}s is under the brief's 6.0–10.0s band" in err


def test_a_brief_band_on_an_unmatched_mood_is_still_reconciled(tmp_path):
    # the balanced exemption is for a skipped brief; a brief that set --asl decided
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection(),
                               footage=replace(_footage(), band=(1.2, 4.0)))
    spec_path = _write_spec(tmp_path, asl=(0.6, 3.0))          # mood "unspecified"
    res = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path), spec=spec_path)
    assert res["status"] == "stop_and_report" and res["finding"]["reason"] == "length-band"


@pytest.mark.parametrize("lo_off,hi_off,said", [(-0.5, -0.1, "over the brief's"),
                                                (-0.5, 0.0, ""),        # hi == ASL: inclusive
                                                (0.0, 40.0, ""),        # lo == ASL: inclusive
                                                (0.1, 40.0, "under the brief's")])
def test_the_out_of_band_line_names_the_side_and_is_silent_in_band(tmp_path, capsys,
                                                                    lo_off, hi_off, said):
    eps = edit_plan.build_edl(_footage(), _plain_selection()).episodes
    asl = sum(e.play_dur() for e in eps) / len(eps)
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection())
    spec_path = _write_spec(tmp_path, asl=(asl + lo_off, asl + hi_off))
    edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path), spec=spec_path)
    err = capsys.readouterr().err
    if said:
        assert said in err
    else:
        assert "is under the" not in err and "is over the" not in err


def test_a_preset_band_is_information_not_an_order(tmp_path, capsys, monkeypatch):
    """Only a band the brief chose earns "re-plan"; a preset band is a default nobody
    chose, and the balanced fallback's is resolve()'s artifact — silent."""
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection())
    edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path))                     # balanced
    err = capsys.readouterr().err
    assert "re-plan" not in err and "band —" not in err
    # a preset whose band the cut cannot be inside ("brooding" routes to the one
    # patched preset — see test_a_mood_floor_under_the_carved_floor_is_a_suggestion_not_a_refusal)
    slow = moodpreset.MoodPreset("slow", mood.MoodVector(0.5, 0.5, 0.5),
                                 {"close": 0.3, "medium": 0.4, "wide": 0.3}, (20.0, 30.0))
    monkeypatch.setattr(moodpreset, "PRESETS", (slow,))
    edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path),
                              spec=_write_spec(tmp_path, mood="brooding"))
    err = capsys.readouterr().err
    assert "re-plan" not in err and "is under the slow mood's suggested 20.0–30.0s" in err


def test_a_track_with_no_bar_grid_still_ends_on_a_beat(capsys):
    """retro 2026-10-16 S7: with bars=() the fit used to stay `unchanged` and the music
    was cut mid-phrase. It now falls back to the beat grid under the longer fade."""
    footage = _footage_with(source="a.mp4", dur=30.0, scene_cuts=())
    eps = [_edl_ep(source="a.mp4", start=0.0, dur=10.0),
           _edl_ep(source="a.mp4", start=12.0, dur=4.0)]
    beats = tuple(round(0.5 * k, 3) for k in range(0, 80))
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=beats, energy=(0.1,), energy_hz=2.0,
                      bars=(), vocal_spans=())
    out, fit = edit_plan._apply_outro(eps, footage, music, fade=0.8, brief_len=None)
    assert fit.grid == "beat" and fit.rung in ("gap", "no-gap") and fit.line in beats
    assert sum(e.play_dur() for e in out) == pytest.approx(fit.reel_dur)
    assert "beat grid" in capsys.readouterr().err


def test_the_briefs_music_in_app_reaches_the_edl(tmp_path):
    """Backlog U3: SPEC.music_in_app rides the same pipe platform and brief_len ride, so
    a re-cut keeps it without a flag to forget (design 2026-10-20 §1)."""
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection())
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path),
                                       spec=_write_spec(tmp_path, music_in_app=True))
    assert result["status"] == "written", result
    assert EDL.from_json(str(tmp_path / "EDL.json")).music_in_app is True


# --- photos (design 2026-10-20 §2) ----------------------------------------------------

def _photo_clip(res):
    return FootageClip(source="IMG_1.HEIC", dur=8.0, res=res, fps=0.0, kind="photo",
                       windows=[FootageWindow(start=0.0, dur=2.0, shot_type="medium",
                                              people=1, motion=0.0, shake=0.0)])


@pytest.mark.parametrize("res, canvas, layout", [
    ((3024, 4032), (9, 16), "fill"),     # 3:4 keeps 75%
    ((3200, 4000), (9, 16), "fill"),     # 4:5 keeps 70%
    ((3000, 3000), (9, 16), "fit"),      # 1:1 keeps 56%
    ((4032, 3024), (9, 16), "fit"),      # 4:3 keeps 42%
    ((4032, 3024), (16, 9), "fill"),     # the same photo on a horizontal canvas
    ((3024, 4032), (16, 9), "fit"),
])
def test_a_photo_fills_when_the_canvas_crop_keeps_most_of_it(res, canvas, layout):
    assert edit_plan.photo_layout(res, canvas) == layout
    clip = _photo_clip(res)
    ep = edit_plan.window_to_episode(clip, clip.windows[0], canvas=canvas,
                                     composition="center", grid="thirds")
    assert ep.layout == layout


def test_an_authored_layout_wins_and_needs_no_canvas():
    clip = _photo_clip((4032, 3024))
    ep = edit_plan.window_to_episode(clip, clip.windows[0], composition="center",
                                     grid="thirds", layout="insert", rect=[0.1, 0.2, 0.8])
    assert ep.layout == "insert"


def test_a_photo_default_layout_without_a_canvas_is_refused():
    clip = _photo_clip((4032, 3024))
    with pytest.raises(ValueError, match="depends on the canvas"):
        edit_plan.window_to_episode(clip, clip.windows[0], composition="center", grid="thirds")


def test_a_ramp_on_a_photo_meets_the_photo_refusal_not_the_judder_gate():
    clip = _photo_clip((3024, 4032))
    with pytest.raises(ValueError, match="is a photo and cannot carry ramp"):
        edit_plan.window_to_episode(clip, clip.windows[0], canvas=(9, 16),
                                    composition="center", grid="thirds",
                                    ramp={"at": 1.0, "factor": 0.5, "ease": 0.2, "hold": 0.2})


def test_a_fit_photo_is_censused_by_the_band_it_fills_not_as_a_crop():
    """The review's M3: delivered_shot reads a landscape photo as if cropped to 9:16,
    which multiplies its subject's width 2.4x; fit keeps the width and shrinks the
    height to the photo's band on the canvas."""
    clip = _photo_clip((4032, 3024))                       # fit by default on 9:16
    w = FootageWindow(start=0.0, dur=2.0, shot_type="medium", people=1, motion=0.0,
                      shake=0.0, subject_w=0.4, subject_h=0.9)
    # as a crop: (0.4 * 2.37, 0.9) -> close; on the band: (0.4, 0.9 * 0.42) -> medium
    assert edit_plan._delivered(clip, w, (9, 16)) == "medium"
    assert edit_plan._delivered(clip, w, (9, 16), "fill") == "close"


def test_a_canvas_in_selection_is_refused_by_name():
    f = Footage(clips=[_photo_clip((3024, 4032))])
    sel = {"episodes": [{"source": "IMG_1.HEIC", "window": 0, "composition": "center",
                         "grid": "thirds", "canvas": [9, 16]}]}
    with pytest.raises(ValueError, match="`canvas` is the project's"):
        edit_plan.build_edl(f, sel, aspect=(9, 16))


# --- the freeze (design 2026-10-21 §3) -------------------------------------------------

def _freeze_footage(fps=30.0):
    """A.mp4 with a cut at 10.0 (windows 0 and 1 share the shot [0, 10)) and a photo."""
    return Footage(clips=[
        _clip(source="A.mp4", dur=22.0, fps=fps, scene_cuts=[10.0], windows=[
            FootageWindow(start=1.0, dur=2.0, shot_type="wide", people=1, motion=0.3,
                          shake=0.0, description="approach"),
            FootageWindow(start=5.0, dur=3.0, shot_type="close", people=1, motion=0.5,
                          shake=0.0, description="the turn"),
            FootageWindow(start=12.0, dur=2.0, shot_type="medium", people=1, motion=0.3,
                          shake=0.0, description="exit")]),
        _photo_clip((3024, 4032))])


def _turn(**kw):
    return {"source": "A.mp4", "window": 1, "composition": "lead", "grid": "thirds", **kw}


def test_a_freeze_holds_the_previous_episodes_last_frame_in_its_framing():
    sel = {"episodes": [_turn(layout="fit", hero="Lena", saturation=0.9, motion="static",
                              stabilize=True, smooth_window_s=0.5, crop_scale=0.8,
                              zoom={"from": 1.0, "to": 0.9}),
                        {"freeze": True}]}
    prev, fr = edit_plan.build_edl(_freeze_footage(), sel).episodes
    # `center` (a held route has no travel to lead with), at the crop the push-in ENDS on
    assert fr == replace(prev, freeze=True, shutter=True, hold=None,
                         start=5.0 + 3.0 - 1 / 30.0, composition="center",
                         crop_scale=0.8 * 0.9,
                         dur=hold.HOLD_DEFAULT, base_dur=hold.HOLD_DEFAULT, beat_slot=None,
                         ramp=None, pan=None, zoom=None, still=None, motion=None,
                         smooth_window_s=None, stabilize=False,
                         processing_notes="freeze · the turn")


def test_a_freeze_without_a_zoom_before_it_keeps_the_crop_scale():
    sel = {"episodes": [_turn(crop_scale=0.8), {"freeze": True}]}
    prev, fr = edit_plan.build_edl(_freeze_footage(), sel).episodes
    assert (prev.composition, fr.composition) == ("lead", "center")
    assert fr.crop_scale == prev.crop_scale == 0.8


def test_a_freeze_drops_a_ramp_and_reads_the_source_window():
    sel = {"episodes": [_turn(ramp={"at": 1.5, "factor": 0.5, "ease": 0.3, "hold": 0.2}),
                        {"freeze": True}]}
    prev, fr = edit_plan.build_edl(_freeze_footage(fps=60.0), sel).episodes
    assert prev.ramp is not None and fr.ramp is None
    # the last SOURCE frame of the window, whatever the ramp did to its screen time
    assert fr.start == 5.0 + 3.0 - 1 / 60.0


def test_a_freeze_after_a_pan_is_refused():
    # a pan has no route to hold, and its window holds nobody to freeze on
    sel = {"episodes": [_turn(composition="center", pan={"from": 0.2, "to": 0.7}),
                        {"freeze": True}]}
    with pytest.raises(ValueError, match="selection episode 1: a freeze holds the subject "
                                         "where the previous episode left them, and episode "
                                         "0 is a pan, which follows nobody — freeze the "
                                         "episode before or after it, or drop the pan"):
        edit_plan.build_edl(_freeze_footage(), sel)


def test_a_freeze_takes_an_explicit_shutter_and_hold():
    sel = {"episodes": [_turn(), {"freeze": True, "shutter": False, "hold": 3}]}
    fr = edit_plan.build_edl(_freeze_footage(), sel).episodes[1]
    assert (fr.freeze, fr.shutter, fr.hold) == (True, False, 3)


def test_a_freeze_cannot_open_the_cut():
    with pytest.raises(ValueError, match="selection episode 0: a freeze .* must follow a "
                                         "video episode"):
        edit_plan.build_edl(_freeze_footage(), {"episodes": [{"freeze": True}]})


@pytest.mark.parametrize("before", [
    [{"source": "IMG_1.HEIC", "window": 0, "composition": "center", "grid": "thirds",
      "layout": "fill"}],
    [_turn(), {"freeze": True}],
])
def test_a_freeze_after_a_held_episode_is_refused(before):
    sel = {"episodes": [*before, {"freeze": True}]}
    with pytest.raises(ValueError, match=f"selection episode {len(before)}: a freeze .* must "
                                         f"follow a video episode"):
        edit_plan.build_edl(_freeze_footage(), sel)


@pytest.mark.parametrize("extra", [{"source": "A.mp4"}, {"window": 1}, {"layout": "fit"}])
def test_a_freeze_carries_nothing_but_its_own_keys(extra):
    sel = {"episodes": [_turn(), {"freeze": True, **extra}]}
    with pytest.raises(ValueError, match="inherits the previous episode's framing"):
        edit_plan.build_edl(_freeze_footage(), sel)


@pytest.mark.parametrize("value", [False, "yes", 1])
def test_freeze_must_be_true(value):
    sel = {"episodes": [_turn(), {"freeze": value}]}
    with pytest.raises(ValueError, match="`freeze` must be true"):
        edit_plan.build_edl(_freeze_footage(), sel)


def test_freeze_false_beside_a_window_is_told_to_drop_the_key():
    # a played window with a stray `"freeze": false`: the remedy that applies is "drop the
    # key", not "a freeze carries only freeze, shutter, hold"
    sel = {"episodes": [_turn(), {**_turn(), "freeze": False}]}
    with pytest.raises(ValueError, match="selection episode 1: `freeze` must be true, got "
                                         "False — to cut a played window, drop the key"):
        edit_plan.build_edl(_freeze_footage(), sel)


def test_a_freeze_is_not_a_new_use_of_footage_in_the_variety_census():
    sel = {"episodes": [_turn(), {"freeze": True}]}
    edl = edit_plan.build_edl(_freeze_footage(), sel, aspect=(16, 9),
                              preset=moodpreset.resolve(None))
    assert sum(edl.variety.used.values()) == 1


def test_no_repeat_does_not_read_a_freeze_as_a_repeat_of_its_own_shot():
    sel = {"episodes": [_turn(), {"freeze": True}]}
    edl = edit_plan.build_edl(_freeze_footage(), sel, rules=_no_repeat_rules())
    assert edl.constraints.ok and len(edl.constraints.rules) == 1
    # the control: the same shot used again IS a repeat
    again = {"episodes": [_turn(), {**_turn(), "window": 0}]}
    assert not edit_plan.build_edl(_freeze_footage(), again,
                                   rules=_no_repeat_rules()).constraints.ok


@pytest.mark.parametrize("rule, message", [
    ({"kind": "no_repeat", "stated": "no repeats"},
     "episodes 0, 3 are all from A.mp4 [0.00s–10.00s]"),
    ({"kind": "exclude", "stated": "not that take", "source": "A.mp4", "window": 0},
     "episode(s) 0, 3 use A.mp4 [0.00s–10.00s]"),
])
def test_a_constraint_refusal_names_edl_indices_past_a_freeze(rule, message):
    # the freeze at 1 is not projected, so the repeat at EDL index 3 is the projection's
    # third entry — and the agent edits the selection entry the message names
    sel = {"episodes": [_turn(), {"freeze": True}, {**_turn(), "window": 2},
                        {**_turn(), "window": 0}]}
    edl = edit_plan.build_edl(_freeze_footage(), sel,
                              rules=Constraints.from_dict({"rules": [rule]}))
    assert edl.constraints.violations[0].message.startswith(message)


def test_resolve_freezes_reads_the_predecessor_as_it_is_now():
    footage = _freeze_footage()
    prev = _edl_ep(source="A.mp4", start=5.0, dur=3.0)
    fr = replace(prev, freeze=True, dur=2.0)                      # placeholder start
    out = edit_plan._resolve_freezes([prev, fr], footage)
    assert out == [prev, replace(fr, start=5.0 + 3.0 - 1 / 30.0)]
    # the outro fit grows the freeze's own length, never the frame it holds
    grown = edit_plan._resolve_freezes([prev, replace(fr, dur=3.5)], footage)[1]
    assert grown.start == out[1].start
    # a predecessor whose cut moved takes the frozen frame with it
    longer = edit_plan._resolve_freezes([replace(prev, dur=3.2), fr], footage)[1]
    assert longer.start == 5.0 + 3.2 - 1 / 30.0


def test_resolve_freezes_never_holds_a_frame_before_the_window():
    prev = _edl_ep(source="A.mp4", start=5.0, dur=0.02)           # under one frame at 30fps
    fr = replace(prev, freeze=True, dur=2.0)
    assert edit_plan._resolve_freezes([prev, fr], _freeze_footage())[1].start == 5.0


def test_a_paced_predecessor_moves_the_frozen_frame():
    spine = Spine(slots=(Slot(0, 0.0, 3.2, 0.5, "hook"),
                         Slot(1, 3.2, 2.0, 0.5, "peak", held=True)),
                  target_dur=5.2, tempo=120.0)
    sel = {"episodes": [_turn(), {"freeze": True}]}
    prev, fr = edit_plan.build_edl(_freeze_footage(), sel, pacing=spine).episodes
    assert prev.dur == pytest.approx(3.2)
    assert fr.start == pytest.approx(5.0 + 3.2 - 1 / 30.0)


def test_the_outro_fit_grows_a_frozen_closer_without_moving_its_frame():
    spine = Spine(slots=(Slot(0, 0.0, 3.0, 0.5, "hook"),
                         Slot(1, 3.0, 2.0, 0.5, "peak", held=True)),
                  target_dur=5.0, tempo=120.0)
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(6.0,), vocal_spans=((6.0, 8.0),))
    sel = {"episodes": [_turn(), {"freeze": True}]}
    edl = edit_plan.build_edl(_freeze_footage(), sel, pacing=spine, music=music)
    prev, fr = edl.episodes
    assert edl.outro.rung == "gap" and fr.dur == pytest.approx(3.5)
    assert fr.start == 5.0 + 3.0 - 1 / 30.0


def test_a_held_closer_grows_into_the_hold_room_not_the_clips():
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0,
                      bars=(15.0,), vocal_spans=((15.0, 17.0),))
    # the shot after 9.0 has 1.5s of room — a 4.0s freeze has none to grow into by the
    # clip's measure, and the 4.0s it has under HOLD_ROOM is what the fit uses
    cut = _footage_with(source="a.mp4", dur=30.0, scene_cuts=(10.5,))
    eps = [_edl_ep(source="a.mp4", start=0.0, dur=9.0),
           _edl_ep(source="a.mp4", start=9.0, dur=1.0),
           _edl_ep(source="a.mp4", start=9.0, dur=4.0, freeze=True)]
    out, fit = edit_plan._apply_outro(eps, cut, music, fade=0.5, brief_len=None)
    assert fit.rung == "gap" and out[-1].dur == pytest.approx(5.5)
    # ...and HOLD_ROOM bounds it: a 7.0s freeze may grow 1.0s, short of the line, though
    # the clip itself has 24s of room after its placeholder start
    open_clip = _footage_with(source="a.mp4", dur=30.0, scene_cuts=())
    eps = [_edl_ep(source="a.mp4", start=0.0, dur=6.0),
           _edl_ep(source="a.mp4", start=6.0, dur=1.0),
           _edl_ep(source="a.mp4", start=6.0, dur=7.0, freeze=True)]
    out, fit = edit_plan._apply_outro(eps, open_clip, music, fade=0.5, brief_len=None)
    assert fit.rung == "unchanged" and out[-1].dur == 7.0


def test_an_authored_hold_without_pacing_is_said_to_be_unused(capsys):
    sel = {"episodes": [_turn(), {"freeze": True, "hold": 2}]}
    fr = edit_plan.build_edl(_freeze_footage(), sel).episodes[1]
    assert (fr.hold, fr.dur) == (2, hold.HOLD_DEFAULT)
    err = capsys.readouterr().err
    assert "episode 1" in err and "beats need a tempo" in err


def test_no_authored_hold_and_a_bound_spine_say_nothing_about_holds(capsys):
    edit_plan.build_edl(_freeze_footage(), {"episodes": [_turn(), {"freeze": True}]})
    spine = Spine(slots=(Slot(0, 0.0, 3.0, 0.5, "hook"),
                         Slot(1, 3.0, 1.0, 0.5, "peak", held=True, hold=2)),
                  target_dur=4.0, tempo=120.0)
    edit_plan.build_edl(_freeze_footage(), {"episodes": [_turn(), {"freeze": True, "hold": 2}]},
                        pacing=spine)
    assert "beats need a tempo" not in capsys.readouterr().err


def test_write_edit_plan_writes_a_freeze_through_the_preflight(tmp_path):
    sel = {"episodes": [
        {"source": "A.mp4", "window": 0, "composition": "lead", "grid": "thirds"},
        {"freeze": True},
        {"source": "B.mp4", "window": 0, "composition": "center", "grid": "phi"}]}
    fj, sj, pj = _write_inputs(tmp_path, sel)
    res = edit_plan.write_edit_plan(fj, sj, pj, str(tmp_path / "out"))
    assert res["status"] == "written" and res["episodes"] == 3
    fr = EDL.from_json(str(tmp_path / "out" / "EDL.json")).episodes[1]
    assert (fr.freeze, fr.shutter, fr.source, fr.start) == (True, True, "A.mp4",
                                                           0.5 + 2.0 - 1 / 30.0)
    assert "freeze @2.47s (2.00s)" in (tmp_path / "out" / "EDL.md").read_text()


def test_a_bad_freeze_field_names_the_selection_episode():
    sel = {"episodes": [_turn(), {"freeze": True, "shutter": "yes"}]}
    with pytest.raises(ValueError, match="selection episode 1: EDLEpisode.shutter must be true "
                                         "or false"):
        edit_plan.build_edl(_freeze_footage(), sel)


def test_resolve_freezes_refuses_a_freeze_with_nothing_before_it():
    # out[i - 1] at i == 0 is the LAST episode: a silent wrong frame, so it is refused
    fr = _edl_ep(source="A.mp4", start=5.0, dur=2.0, freeze=True)
    with pytest.raises(ValueError, match="freeze 0 has no episode before it"):
        edit_plan._resolve_freezes([fr, _edl_ep(source="A.mp4", start=12.0, dur=2.0)],
                                   _freeze_footage())


# --- binding a held episode: the grid authored its length (design 2026-10-21 §2.3) ----

def _held_spine(*slots):
    """(dur, held) pairs → a contiguous hook-first Spine at 120 BPM."""
    out, start = [], 0.0
    for i, (d, h) in enumerate(slots):
        out.append(Slot(i, start, d, 0.5, "hook" if i == 0 else "build", held=h))
        start += d
    return Spine(tuple(out), start, 120.0)


def test_a_held_episode_takes_its_slots_length_however_far_it_moved():
    # 2.0 s placeholder -> 0.5 s (one loud beat) and -> 4.0 s: seconds, not a half-beat
    eps = [_edl_ep(source="A.mp4", start=5.0, dur=3.0, base_dur=3.0),
           _edl_ep(source="A.mp4", start=7.97, dur=2.0, base_dur=2.0, freeze=True),
           _edl_ep(source="IMG_1.HEIC", start=0.0, dur=2.0, base_dur=2.0),
           _edl_ep(source="A.mp4", start=12.0, dur=2.0, base_dur=2.0)]
    spine = _held_spine((3.0, False), (0.5, True), (4.0, True), (2.0, False))
    bound = edit_plan._bind_pacing(eps, spine)
    assert bound == [replace(eps[0], beat_slot=0, dur=3.0),
                     replace(eps[1], beat_slot=1, dur=0.5),
                     replace(eps[2], beat_slot=2, dur=4.0),
                     replace(eps[3], beat_slot=3, dur=2.0)]


@pytest.mark.parametrize("ep, what", [
    (_edl_ep(source="IMG_1.HEIC", start=0.0, dur=2.0, base_dur=2.0), "photo"),
    (_edl_ep(source="A.mp4", start=7.97, dur=2.0, base_dur=2.0, freeze=True), "freeze"),
])
def test_a_held_episode_on_a_footage_slot_is_refused(ep, what):
    eps = [_edl_ep(source="A.mp4", start=5.0, dur=3.0, base_dur=3.0), ep]
    with pytest.raises(ValueError, match=f"slot 1 was fitted with episode 1 as footage; it is "
                                         f"now a {what} — re-run pacing"):
        edit_plan._bind_pacing(eps, _held_spine((3.0, False), (2.0, False)))


def test_a_footage_episode_on_a_held_slot_is_refused():
    # even at the very length the slot carries: the kinds disagree, so the fit was not of
    # this edit
    eps = [_edl_ep(source="A.mp4", start=5.0, dur=3.0, base_dur=3.0),
           _edl_ep(source="A.mp4", start=12.0, dur=2.0, base_dur=2.0)]
    with pytest.raises(ValueError, match="slot 1 was fitted with episode 1 held \\(a photo or "
                                         "a freeze\\); it is now footage — re-run pacing"):
        edit_plan._bind_pacing(eps, _held_spine((3.0, False), (2.0, True)))


@pytest.mark.parametrize("fitted, authored, said", [
    (None, 4, "hold=none (the grid's own count); episode 1 now authors 4"),
    (4, None, "hold=4; episode 1 now authors none (the grid's own count)"),
    (4, 8, "hold=4; episode 1 now authors 8"),
])
def test_a_held_episode_whose_hold_changed_since_the_fit_is_refused(fitted, authored, said):
    # "hold the hero photo longer": the agent adds a `hold` and re-binds the old spine —
    # its slot length was placed for the count the episode authored THEN
    eps = [_edl_ep(source="A.mp4", start=5.0, dur=3.0, base_dur=3.0),
           _edl_ep(source="IMG_1.HEIC", start=0.0, dur=2.0, base_dur=2.0, hold=authored)]
    spine = Spine((Slot(0, 0.0, 3.0, 0.5, "hook"),
                   Slot(1, 3.0, 2.0, 0.5, "build", held=True, hold=fitted)), 5.0, 120.0)
    with pytest.raises(ValueError, match=f"slot 1 was fitted with {re.escape(said)} — re-run "
                                         f"pacing"):
        edit_plan._bind_pacing(eps, spine)


def test_a_held_episode_binds_when_its_hold_is_the_one_the_slot_was_fitted_with():
    eps = [_edl_ep(source="A.mp4", start=5.0, dur=3.0, base_dur=3.0),
           _edl_ep(source="IMG_1.HEIC", start=0.0, dur=2.0, base_dur=2.0, hold=3)]
    spine = Spine((Slot(0, 0.0, 3.0, 0.5, "hook"),
                   Slot(1, 3.0, 1.5, 0.5, "build", held=True, hold=3)), 4.5, 120.0)
    assert edit_plan._bind_pacing(eps, spine)[1] == replace(eps[1], beat_slot=1, dur=1.5)


def _one_held(dur, hold=None, tempo=120.0):
    return (_edl_ep(source="IMG_1.HEIC", start=0.0, dur=2.0, base_dur=2.0, hold=hold),
            Spine((Slot(0, 0.0, dur, 0.5, "hook", held=True, hold=hold),), dur, tempo))


@pytest.mark.parametrize("dur, hold_", [
    (30.0, None), (0.05, None),                       # a hand-edited or corrupt file
    (hold.HOLD_ROOM + 1e-5, None), (hold.HOLD_MIN - 1e-5, None),
    (8.3, 16),                                        # 0.3 s from its 16 beats
])
def test_a_held_slot_the_fit_cannot_have_written_is_refused(dur, hold_):
    ep, spine = _one_held(dur, hold_)
    said = re.escape(f"slot 0 holds {dur:.3f}s, outside the [0.33, 8.0]s a held episode "
                     f"may last")
    with pytest.raises(ValueError, match=f"{said}.* was edited or is corrupt\\. Re-run pacing"):
        edit_plan._bind_pacing([ep], spine)
    if hold_ is not None:
        with pytest.raises(ValueError, match="further than half a beat from its authored 16 "
                                             "beats"):
            edit_plan._bind_pacing([ep], spine)


@pytest.mark.parametrize("dur, hold_, tempo", [
    (hold.HOLD_ROOM + 1e-7, None, 120.0), (hold.HOLD_MIN - 1e-7, None, 120.0),  # slack
    (8.016, 16, 120.0),        # an authored 16 beats on a grid 0.2 % slow (gridfit keeps it)
    (1 / 3 - 0.001, 1, 180.0), # an authored beat detected 1 ms early, at 180 BPM's floor
])
def test_a_held_slot_the_fit_can_write_binds(dur, hold_, tempo):
    ep, spine = _one_held(dur, hold_, tempo)
    assert edit_plan._bind_pacing([ep], spine)[0].dur == dur


def test_an_authored_count_at_the_range_edge_is_fitted_and_bound_whole():
    # the fit keeps an authored 16 beats on its own 16th detected beat, 8.016 s on a grid
    # 0.2 % slow — past HOLD_ROOM by the tracker's jitter — and binding takes it
    spine, _, _ = pacing.fit_spine([2.0, 3.0], [i * 0.501 for i in range(40)], [0.5] * 20,
                                   1.0, 120.0, [(0.0, 0.0), (-0.25, 0.25)],
                                   held=[gridfit.Held(16, hold.HOLD_MIN, hold.HOLD_ROOM), None])
    ep = _edl_ep(source="IMG_1.HEIC", start=0.0, dur=2.0, base_dur=2.0, hold=16)
    tail = _edl_ep(source="A.mp4", start=5.0, dur=3.0, base_dur=3.0)
    bound = edit_plan._bind_pacing([ep, tail], spine)
    assert bound[0].dur == pytest.approx(16 * 0.501) and spine.slots[0].hold == 16


def test_a_footage_episode_keeps_the_half_beat_guard_beside_held_ones():
    eps = [_edl_ep(source="IMG_1.HEIC", start=0.0, dur=2.0, base_dur=2.0),
           _edl_ep(source="A.mp4", start=5.0, dur=3.0, base_dur=3.0)]
    with pytest.raises(ValueError, match="fitted to a different edit"):
        edit_plan._bind_pacing(eps, _held_spine((0.5, True), (4.0, False)))


# --- a paced reel its music window cannot cover is refused here (final review M5) ---

def _short_music(duration):
    return MusicSpec(track="t.wav", start_offset=0.0, duration=duration, tempo=120.0,
                     beats=tuple(i * 0.5 for i in range(int(duration / 0.5))),
                     energy=(0.1,), energy_hz=2.0)


def test_a_paced_reel_its_music_cannot_cover_is_refused_before_any_render():
    """_spine2 binds the cut to a 5.15 s target. Against a 4.0 s window build_reel
    refused it — after every episode had been rendered and judged, as a bare
    ValueError. edit_plan holds both numbers and says so first."""
    with pytest.raises(ValueError) as e:
        edit_plan.build_edl(_footage(), _sel3(), pacing=_spine2(), music=_short_music(4.0))
    assert str(e.value) == (
        "edit_plan: the reel's target 5.15s overruns its music window (4.00s, t.wav) by "
        "1.15s — build_reel refuses a reel longer than its window, and only after every "
        "episode is rendered and judged. Held lengths (photos, freezes) are the grid's "
        "and can grow a reel past the length its music was analysed for: re-analyse with "
        "headroom (beats --auto-start --duration 10), re-run pacing, then this build")


def test_a_paced_reel_inside_build_reels_tolerance_builds():
    # 0.05 s past a 5.1 s window is inside build_reel's own MUSIC_OVERRUN_TOL
    edl = edit_plan.build_edl(_footage(), _sel3(), pacing=_spine2(),
                              music=_short_music(5.1))
    assert edl.target_dur == pytest.approx(5.15)
