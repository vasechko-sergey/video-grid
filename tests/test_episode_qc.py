"""episode_qc driver — validation and stamping (design §6/§7)."""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import episode_qc
from scripts.lib import provenance
from scripts.lib.models import ReelEpisode, ReelManifest


def _rm(tmp_path, n=2):
    eps = []
    for i in range(n):
        clip = tmp_path / f"ep{i}.mp4"
        clip.write_bytes(f"clip-{i}".encode())
        eps.append(ReelEpisode(manifest={"segment": f"s{i}.mp4", "target_dur": 2.0},
                               clip=str(clip), route=None,
                               path=str(tmp_path / f"ep{i}" / "path.json"),
                               meta=str(tmp_path / f"ep{i}" / "path.meta.json")))
    return ReelManifest(episodes=eps, target_dur=4.0)


def _findings(packets, i, severity="minor"):
    d = packets / f"ep{i}"
    d.mkdir(parents=True, exist_ok=True)
    # Task 4 (2026-09-09 bound-reports): build_qc now refuses a packet whose
    # evidence.json is missing or names a stale digest, so a hand-built packet must
    # carry one too — naming the same clip _rm() already wrote to tmp_path/f"ep{i}.mp4".
    clip = Path(packets).parent / f"ep{i}.mp4"
    (d / "evidence.json").write_text(json.dumps(
        {"idx": i, "clip": str(clip), "clip_digest": provenance.digest_file(clip)}))
    (d / "findings.json").write_text(json.dumps({
        "summary": f"ep{i} reads well", "reviewer": "test-judge",
        "findings": [{"axis": "colour", "severity": severity, "evidence": "warm cast",
                      "route": "match-grade", "suggestion": "cool it by 4 units"}]}))


def test_build_stamps_the_digest_itself_and_ignores_what_the_judge_claimed(tmp_path):
    rm = _rm(tmp_path)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    packets = tmp_path / "qc"
    _findings(packets, 0)
    _findings(packets, 1)
    (packets / "ep0" / "findings.json").write_text(json.dumps({
        "clip_digest": "deadbeef", "findings": []}))          # the judge tries to set it
    res = episode_qc.build(str(ep_path), str(packets), str(tmp_path))
    qc = json.loads((tmp_path / "EPISODE_QC.json").read_text())
    assert res["status"] == "written" and res["verdict"] == "approve"
    assert qc["episodes"][0]["clip_digest"] == provenance.digest_file(rm.episodes[0].clip)
    assert (tmp_path / "EPISODE_QC.md").exists()


def test_build_refuses_an_unjudged_episode(tmp_path):
    rm = _rm(tmp_path)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    packets = tmp_path / "qc"
    _findings(packets, 0)
    with pytest.raises(ValueError, match="episode 1 has no findings.json"):
        episode_qc.build(str(ep_path), str(packets), str(tmp_path))


def test_build_reports_revise_when_a_finding_blocks(tmp_path):
    rm = _rm(tmp_path)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    packets = tmp_path / "qc"
    _findings(packets, 0)
    _findings(packets, 1, severity="blocking")
    res = episode_qc.build(str(ep_path), str(packets), str(tmp_path))
    assert res["verdict"] == "revise" and res["blocking"] == 1


def test_pack_refuses_an_episode_with_no_sidecar_path(tmp_path):
    rm = ReelManifest(episodes=[ReelEpisode(manifest={"segment": "s.mp4"},
                                            clip=str(tmp_path / "ep0.mp4"))],
                      target_dur=2.0)
    (tmp_path / "ep0.mp4").write_bytes(b"x")
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    with pytest.raises(ValueError, match="no path sidecar"):
        episode_qc.pack(str(ep_path), str(tmp_path / "qc"))


def _episode_with_scratch(tmp_path):
    d = tmp_path / "ep0"
    d.mkdir()
    clip = tmp_path / "ep0.mp4"
    clip.write_bytes(b"x")     # Task 4: _evidence digests ep.clip itself now
    ep = ReelEpisode(manifest={"segment": "s.mp4"}, clip=str(clip),
                     path=str(d / "path.json"), meta=str(d / "path.meta.json"))
    return ep, d


def test_evidence_reports_a_missing_storyboard_as_none(tmp_path):
    # The storyboard is the evidence the `hero` axis stands on (design §6) — a judge
    # must be able to tell "there was no storyboard" from "there was one", the same
    # distinction _evidence already draws for report.json/route.meta.json/path.meta.json.
    ep, _ = _episode_with_scratch(tmp_path)
    ev = episode_qc._evidence(ep, 0, {"stats": {}, "flags": {}}, {"strip": "s.jpg", "cell_px": [1, 1]}, (10, 10))
    assert ev["storyboard"] is None
    assert ev["checks"] is None and ev["track"] is None and ev["geometry"] is None


def test_evidence_reports_an_existing_storyboard_path(tmp_path):
    ep, d = _episode_with_scratch(tmp_path)
    (d / "storyboard.jpg").write_bytes(b"x")
    ev = episode_qc._evidence(ep, 0, {"stats": {}, "flags": {}}, {"strip": "s.jpg", "cell_px": [1, 1]}, (10, 10))
    assert ev["storyboard"] == str(d / "storyboard.jpg")


# --- 2026-08-31 grade-sensor-references Task 8: _source_reading reads the CROP ----

def _episode(tmp_path, segment=None):
    """A ReelEpisode whose segment exists on disk by default (a placeholder — the
    wiring test below fakes both process_episode.plan_ungraded and
    reframe.plan_frames_rgb, so its bytes are never actually decoded) or is a
    caller-chosen path that need not exist, for the absent-source case.

    The manifest carries every field manifest.REQUIRED needs — not just "segment" —
    so that Manifest.from_dict (plan_ungraded's first step) actually succeeds and
    execution reaches the real read this test means to exercise, rather than
    returning early on a manifest-validation ValueError that would land on the SAME
    except branch for an unrelated reason. Measured while writing this test: a
    thinner manifest (segment/target_dur only) made the absent-source test pass even
    with the exists() guard deleted, because Manifest.from_dict itself raised
    ValueError first — a false pass this fuller manifest closes."""
    d = tmp_path / "ep0"
    d.mkdir(exist_ok=True)
    if segment is None:
        segment = str(d / "segment.mp4")
        Path(segment).write_bytes(b"x")
    manifest = {"segment": segment, "out_path": str(d / "out.mp4"), "target_dur": 2.0,
                "composition": "center", "grid": "thirds", "canvas": [9, 16]}
    return ReelEpisode(manifest=manifest, clip=str(tmp_path / "ep0.mp4"), route=None,
                       path=str(d / "path.json"), meta=str(d / "path.meta.json"))


def _fake_plan():
    return SimpleNamespace(dur=2.0)


def _flat_frame():
    return np.full((8, 8, 3), 128, dtype=np.uint8)


def test_source_reading_measures_the_source_IN_THE_EPISODE_S_CROP(monkeypatch, tmp_path):
    """_source_reading used to read the whole segment frame at its native size
    (assembly.frames_rgb straight on ep.manifest["segment"]) and compare THAT against
    the delivered clip's crop — the branch's own fixture measured that as source
    contrast 0.0 against graded 123.6 with no grade at all, which is the crop
    showing up as a "delta", not the grade. See
    test_the_evidence_packet_carries_the_pre_grade_reading in
    tests/integration/test_episode_qc.py — its own comment warns of exactly this
    "seg"/"ep.clip" mixup shape. Named by test, not by line: a line number rots the
    moment either file grows a line above it, which this very commit already did
    once. This slice replaced the read with the episode's own
    plan_ungraded/plan_frames_rgb pair, so both readings come from the same geometry.

    A reverted (old) implementation never calls plan_ungraded or plan_frames_rgb at
    all, so asserting on the OUTPUT numbers could not catch it — a flat fake frame
    reads the same whichever path produced it (measured: cast/saturation/contrast
    are all 0.0 on a constant-128 frame regardless of who rendered it). Spying on
    which functions ran, with what arguments, is what tells the two apart — the same
    shape of trap the comment linked above names for evaluate_delta's argument
    order."""
    ep = _episode(tmp_path)
    seen = {}

    def _no_old_path(*a, **k):
        raise AssertionError("assembly.frames_rgb must not run any more — "
                             "_source_reading has to read the source through the "
                             "episode's own crop plan, not at native size")
    monkeypatch.setattr(episode_qc.assembly, "frames_rgb", _no_old_path)

    plan_obj = _fake_plan()

    def _plan_ungraded(md, src, route, *, params=None):
        seen["params"] = params
        seen["planned"] = (md, src, route)
        return plan_obj
    monkeypatch.setattr(episode_qc.process_episode, "plan_ungraded", _plan_ungraded)

    def _plan_frames_rgb(plan, src, times):
        seen["rendered"] = (plan, src, times)
        return [_flat_frame() for _ in times]
    monkeypatch.setattr(episode_qc.reframe, "plan_frames_rgb", _plan_frames_rgb)
    # This test's episode points path/meta at files it never writes — drift is not
    # its subject, the wiring is. Task 4 added the oracle to _source_reading, so it
    # is stubbed here exactly as tests/lib/test_build_reel.py stubs it for _predict.
    monkeypatch.setattr(episode_qc.probe, "_refuse_on_drift", lambda *a: None)

    graded = {"cast": 0.0, "saturation": 0.0, "contrast": 100.0}
    d = episode_qc._source_reading(ep, graded)

    assert seen["planned"] == (ep.manifest, ep.manifest["segment"], ep.route)
    assert seen["rendered"][0] is plan_obj          # the SAME plan — not re-derived
    assert seen["rendered"][1] == ep.manifest["segment"]
    assert len(seen["rendered"][2]) == episode_qc.SENSOR_FRAMES
    assert d["source"]["frames"] == episode_qc.SENSOR_FRAMES


def test_source_reading_still_reports_absent_as_absent(tmp_path):
    """A source that resolves to nothing must report {"source": None, "delta": None}
    — never let plan_ungraded reach a real ffprobe on a missing file. Per
    _source_reading's own docstring, a missing/garbage path there surfaces as a
    RuntimeError through proc.run, not one of FileNotFoundError/KeyError/ValueError —
    so this is what a wrong implementation that folded the explicit
    `Path(src).exists()` guard (which runs BEFORE plan_ungraded) into the except
    clause, or dropped it, would break: the call would reach ffprobe on
    "/nowhere/gone.mp4" and this test would error instead of asserting a clean
    absent reading."""
    ep = _episode(tmp_path, segment="/nowhere/gone.mp4")
    assert episode_qc._source_reading(ep, {}) == {"source": None, "delta": None}


def test_source_reading_reads_the_stabilized_file_not_the_raw_segment(monkeypatch, tmp_path):
    """Task 8 fix round 1 (Important 2). _source_reading's own docstring names a
    STABILIZED episode as the motivating case: probe.source_for resolves to
    <epdir>/stabilized.mp4, not ep.manifest["segment"], because on a stabilized
    episode reframe consumed the pre-stage output, not the raw segment (design
    2026-08-28 §9.8). Every other test in this file leaves stabilize unset, where
    probe.source_for's non-stabilized branch returns md["segment"] VERBATIM — so a
    regression that bypassed probe.source_for entirely and read
    ep.manifest["segment"] directly would satisfy those tests' spy assertions
    IDENTICALLY (same string, either way). `grep -rn stabilize tests/test_episode_qc.py
    tests/integration/test_episode_qc.py` found zero hits before this test — this is
    the only case that can tell "called probe.source_for" apart from "read
    ep.manifest['segment'] directly", the same shape of gap Task 7's own review found
    in its own stabilize test.

    raw.mp4 is never even created on disk: if a wrong implementation fell back to
    reading it, Path(src).exists() would find nothing and this would fail loudly as
    a wrong absent reading, not silently pass."""
    d = tmp_path / "ep0"
    d.mkdir()
    raw = str(d / "raw.mp4")                    # must never be planned from, and
                                                # is never even written to disk
    stabilized = d / "stabilized.mp4"
    stabilized.write_bytes(b"x")                # what probe.source_for must resolve to
    manifest = {"segment": raw, "out_path": str(d / "out.mp4"), "target_dur": 2.0,
                "composition": "center", "grid": "thirds", "canvas": [9, 16],
                "stabilize": True}
    ep = ReelEpisode(manifest=manifest, clip=str(tmp_path / "ep0.mp4"), route=None,
                     path=str(d / "path.json"), meta=str(d / "path.meta.json"))
    seen = {}

    def _plan_ungraded(md, src, route, *, params=None):
        seen["params"] = params
        seen["planned"] = (md, src, route)
        return _fake_plan()
    monkeypatch.setattr(episode_qc.process_episode, "plan_ungraded", _plan_ungraded)
    monkeypatch.setattr(episode_qc.reframe, "plan_frames_rgb",
                        lambda plan, src, times: [_flat_frame() for _ in times])
    # This test's episode points path/meta at files it never writes — drift is not
    # its subject, the wiring is. Task 4 added the oracle to _source_reading, so it
    # is stubbed here exactly as tests/lib/test_build_reel.py stubs it for _predict.
    monkeypatch.setattr(episode_qc.probe, "_refuse_on_drift", lambda *a: None)

    d_out = episode_qc._source_reading(ep, {"cast": 0.0, "saturation": 0.0, "contrast": 100.0})

    assert seen["planned"][1] == str(stabilized)
    assert seen["planned"][1] != raw
    assert d_out["source"] is not None


# --- 2026-09-24 retry-record Task 4: the reading that had no oracle ---

def test_source_reading_plans_with_the_params_the_render_recorded(monkeypatch, tmp_path):
    """The silent one of the three consumers (design 2026-09-24 §0.3): with no
    oracle, a retried episode's source was read through a crop the episode never
    shipped and reported to the judge as its own."""
    ep = _episode(tmp_path)
    seen = {}
    monkeypatch.setattr(episode_qc.process_episode, "rendered_params",
                        lambda meta: {"max_speed": 450.0, "smooth_window_s": 0.5})

    def _plan_ungraded(md, src, route, *, params=None):
        seen["params"] = params
        return _fake_plan()
    monkeypatch.setattr(episode_qc.process_episode, "plan_ungraded", _plan_ungraded)
    monkeypatch.setattr(episode_qc.probe, "_refuse_on_drift", lambda *a: None)
    monkeypatch.setattr(episode_qc.reframe, "plan_frames_rgb",
                        lambda plan, src, times: [_flat_frame() for _ in times])

    episode_qc._source_reading(ep, {"cast": 0.0, "saturation": 0.0, "contrast": 100.0})
    assert seen["params"] == {"max_speed": 450.0, "smooth_window_s": 0.5}


def test_source_reading_reports_absence_when_the_geometry_drifted(monkeypatch, tmp_path):
    """A sidecar that records no params — every episode rendered before this slice
    — still drifts for a retried episode, and absence is the honest answer. Never a
    reading: a number read through the wrong crop is worse than no number, because
    the judge cannot tell it apart from a real one.

    The message is NOT asserted: this call site swallows the oracle's RuntimeError
    on purpose and reports absence instead, so there is no string to pin. What is
    pinned is that the frames were never decoded — the assertion on `decoded`, not
    only on the return value, because a return of two Nones could also come from
    the reading having been computed and then thrown away."""
    ep = _episode(tmp_path)
    decoded = []
    monkeypatch.setattr(episode_qc.process_episode, "plan_ungraded",
                        lambda md, src, route, *, params=None: _fake_plan())

    def _drifted(plan, path_json, meta_json):
        raise RuntimeError("the recomputed crop path does not match the frozen path.json")
    monkeypatch.setattr(episode_qc.probe, "_refuse_on_drift", _drifted)
    monkeypatch.setattr(episode_qc.reframe, "plan_frames_rgb",
                        lambda plan, src, times: decoded.append(1) or [_flat_frame()])

    assert episode_qc._source_reading(ep, {}) == {"source": None, "delta": None}
    assert decoded == []


def test_source_reading_still_lets_a_broken_render_raise(monkeypatch, tmp_path):
    """The control on the guard's narrowness. The existing except clause
    deliberately excludes RuntimeError, because proc.run raises it for a broken
    ffmpeg install and reporting that as a clean 'absent' is the swallow that
    clause was written to prevent. The new guard must catch the oracle's
    RuntimeError at the oracle's own call and nowhere else — a widened clause would
    make this test's RuntimeError, raised from the PLAN build, report absence."""
    ep = _episode(tmp_path)

    def _boom(md, src, route, *, params=None):
        raise RuntimeError("ffprobe: command not found")
    monkeypatch.setattr(episode_qc.process_episode, "plan_ungraded", _boom)
    with pytest.raises(RuntimeError, match=r"command not found"):
        episode_qc._source_reading(ep, {})


def test_source_reading_reports_absence_for_a_corrupt_geometry_sidecar(tmp_path):
    """One episode's unreadable sidecar must not abort a packet run over the others
    — the guarantee the guard's own comment states. rendered_params raises
    RuntimeError for a path.meta.json that exists and will not parse (Task 2, so a
    caller never silently plans on the defaults); here that is this episode's
    geometry being unreadable, and the honest answer is absence.

    Not monkeypatched: the real rendered_params reads the real file, so this covers
    the actual raise rather than a stand-in for it."""
    ep = _episode(tmp_path)
    Path(ep.meta).write_text("{not json")
    assert episode_qc._source_reading(ep, {}) == {"source": None, "delta": None}


# --- final whole-branch review, Important 1: _refuse_on_drift's own two reads
# escape the guard above uncaught ---

def test_source_reading_reports_absence_for_a_truncated_frozen_path(monkeypatch, tmp_path):
    """_refuse_on_drift's FIRST read, CropPath.from_json(ep.path), is a bare
    json.loads(Path(path).read_text()) with no wrapping at all — unlike
    PathMeta.from_json, nothing there translates a bad file into RuntimeError. A
    path.json that died mid-write raises json.JSONDecodeError (a ValueError)
    straight out of _refuse_on_drift, before RuntimeError is ever in play, so the
    old `except RuntimeError:` alone let it escape _source_reading and abort
    pack()'s loop over every episode after this one.

    plan_ungraded is stubbed (as every other _source_reading test stubs it) so this
    exercises the real, unstubbed probe._refuse_on_drift against a real corrupt
    file — the escape lives in that function, not in a mock of it."""
    ep = _episode(tmp_path)
    Path(ep.path).write_text("{not json")
    monkeypatch.setattr(episode_qc.process_episode, "plan_ungraded",
                        lambda md, src, route, *, params=None: _fake_plan())
    assert episode_qc._source_reading(ep, {}) == {"source": None, "delta": None}


def test_source_reading_reports_absence_for_an_empty_meta_beside_a_frozen_path(monkeypatch, tmp_path):
    """The escape that matters most: ReelEpisode.meta defaults to "" and its own
    docstring calls that legal ("empty = geometry unavailable"). Path("")
    normalizes to Path(".") — a directory .exists() reports True for — so
    PathMeta.from_json("") passes its own existence guard and then raises
    IsADirectoryError from read_text(), not RuntimeError.

    Reaching that second read needs the FIRST comparison in _refuse_on_drift (the
    frozen crop path vs the plan's own) to PASS, or it raises its own RuntimeError
    first and never touches PathMeta.from_json at all — so this test freezes a real
    path.json and gives the fake plan the identical xs."""
    d = tmp_path / "ep0"
    d.mkdir()
    segment = str(d / "segment.mp4")
    Path(segment).write_bytes(b"x")
    manifest = {"segment": segment, "out_path": str(d / "out.mp4"), "target_dur": 2.0,
                "composition": "center", "grid": "thirds", "canvas": [9, 16]}
    path_json = d / "path.json"
    path_json.write_text(json.dumps([1, 2, 3]))
    ep = ReelEpisode(manifest=manifest, clip=str(tmp_path / "ep0.mp4"), route=None,
                     path=str(path_json), meta="")

    fake_plan = SimpleNamespace(dur=2.0, path=[1, 2, 3])
    monkeypatch.setattr(episode_qc.process_episode, "plan_ungraded",
                        lambda md, src, route, *, params=None: fake_plan)

    assert episode_qc._source_reading(ep, {}) == {"source": None, "delta": None}


def test_the_packet_reports_an_unreadable_sidecar_instead_of_dying_on_it(tmp_path):
    """The guarantee _source_reading's guard states, at the level it is actually
    made: a corrupt path.meta.json must cost this episode its geometry reading and
    nothing else. Before this, json.loads raised out of _evidence, out of pack()'s
    loop, and every LATER episode went unpacked.

    Asserts BOTH halves — the None and the named reason — because None alone is
    what an absent sidecar already produces, and a judge that cannot tell the two
    apart has been told the render wrote no geometry when it wrote a broken one."""
    ep = _episode(tmp_path)
    Path(ep.meta).write_text("{not json")
    # _episode()'s clip (unlike its scratch dir/segment) is never written to disk —
    # every _source_reading test reaches it only through mocks. _evidence digests
    # ep.clip itself (design 2026-09-09 §4), so this test needs real bytes there to
    # reach the loop under test at all — confirmed by running this test without the
    # write first: it fails on FileNotFoundError from provenance.digest_file, before
    # ever reaching the sidecar loop.
    Path(ep.clip).write_bytes(b"x")
    out = episode_qc._evidence(ep, 0, {"stats": {}, "flags": []},
                               {"strip": "s.jpg", "cell_px": (10, 10)}, (100, 200))
    assert out["geometry"] is None
    assert "path.meta.json" in out["unreadable"]


# --- Task 3: legible-evidence slice ---

def _stub_strip(monkeypatch, cell_px=(313, 556)):
    """Replace the decode+tile with a recorder, so _evidence's wiring is observable
    without ffmpeg."""
    def _build(src, out, *, start, dur, frames, fps=None):
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"strip")
        return {"status": "written", "strip": str(out), "frames": frames,
                "cols": 5, "cell_px": list(cell_px), "times": []}
    monkeypatch.setattr(episode_qc.contact_sheet, "build_strip", _build)


def test_evidence_names_the_strip_and_its_rendered_pixel_size(tmp_path):
    rm = _rm(tmp_path, n=1)
    ep = rm.episodes[0]
    Path(ep.path).parent.mkdir(parents=True, exist_ok=True)
    (Path(ep.path).parent / "storyboard.jpg").write_bytes(b"sb")
    strip = {"strip": str(tmp_path / "qc" / "ep0" / "strip.jpg"), "cell_px": [313, 556]}
    ev = episode_qc._evidence(ep, 0, {"stats": {}}, strip, (1080, 1922))
    assert ev["strip"] == strip["strip"]
    assert ev["strip_px"] == [313, 556]
    # storyboard.build pastes each sampled frame at FULL resolution, so one of its
    # cells IS the delivered clip's own frame (design §3).
    assert ev["storyboard_px"] == [1080, 1922]


def test_evidence_reports_no_storyboard_pixels_when_there_is_no_storyboard(tmp_path):
    rm = _rm(tmp_path, n=1)
    ep = rm.episodes[0]
    Path(ep.path).parent.mkdir(parents=True, exist_ok=True)
    strip = {"strip": "s.jpg", "cell_px": [313, 556]}
    ev = episode_qc._evidence(ep, 0, {"stats": {}}, strip, (1080, 1922))
    assert ev["storyboard"] is None and ev["storyboard_px"] is None
    assert ev["strip_px"] == [313, 556]      # the strip is still reported


def test_pack_writes_the_strips_own_measurements_into_evidence(tmp_path, monkeypatch):
    rm = _rm(tmp_path, n=1)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    Path(rm.episodes[0].path).parent.mkdir(parents=True, exist_ok=True)
    _stub_strip(monkeypatch, cell_px=(222, 395))
    monkeypatch.setattr(episode_qc.assembly, "probe_stream",
                        lambda p: SimpleNamespace(w=1080, h=1922, fps=30.0))
    monkeypatch.setattr(episode_qc.assembly, "probe_duration", lambda p: 4.0)
    monkeypatch.setattr(episode_qc.assembly, "frames_rgb",
                        lambda src, times, fps: [np.zeros((8, 8, 3), np.uint8)])
    monkeypatch.setattr(episode_qc, "_source_reading",
                        lambda ep, graded: {"source": None, "delta": None})
    episode_qc.pack(str(ep_path), str(tmp_path / "qc"))
    ev = json.loads((tmp_path / "qc" / "ep0" / "evidence.json").read_text())
    assert ev["strip"].endswith("strip.jpg")
    assert ev["strip_px"] == [222, 395] and ev["storyboard_px"] is None


# --- Task 4: legible-evidence slice: every complaint in one pass ---

def _bad_findings(packets, i, finding):
    d = packets / f"ep{i}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "findings.json").write_text(json.dumps({
        "summary": "s", "reviewer": "r", "findings": [finding]}))


def test_build_names_every_bad_packet_in_one_pass(tmp_path):
    rm = _rm(tmp_path, n=3)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    packets = tmp_path / "qc"
    _bad_findings(packets, 0, {"axis": "colour", "severity": "minor",
                               "evidence": "e", "route": "none"})       # no suggestion
    _findings(packets, 1)                                               # fine
    # ep2 has no findings.json at all
    with pytest.raises(ValueError) as e:
        episode_qc.build(str(ep_path), str(packets), str(tmp_path))
    msg = str(e.value)
    assert "ep0 finding 0" in msg and "suggestion must be a non-empty string" in msg
    assert "ep2" in msg and "has no findings.json" in msg
    assert "ep1" not in msg


def test_build_names_every_bad_finding_inside_one_packet(tmp_path):
    rm = _rm(tmp_path, n=1)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    packets = tmp_path / "qc"
    d = packets / "ep0"
    d.mkdir(parents=True)
    (d / "findings.json").write_text(json.dumps({"summary": "s", "reviewer": "r",
        "findings": [
            {"axis": "framing", "severity": "minor", "evidence": "e",
             "route": "none", "suggestion": "s"},               # bad axis
            {"axis": "colour", "severity": "minor", "evidence": "e",
             "route": "none"},                                  # no suggestion
        ]}))
    with pytest.raises(ValueError) as e:
        episode_qc.build(str(ep_path), str(packets), str(tmp_path))
    msg = str(e.value)
    assert "ep0 finding 0" in msg and "ep0 finding 1" in msg


def test_build_still_refuses_the_whole_run_over_one_bad_packet(tmp_path):
    rm = _rm(tmp_path, n=2)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    packets = tmp_path / "qc"
    _findings(packets, 0)
    _bad_findings(packets, 1, {"axis": "colour", "severity": "catastrophic",
                               "evidence": "e", "route": "none", "suggestion": "s"})
    with pytest.raises(ValueError, match="severity 'catastrophic'"):
        episode_qc.build(str(ep_path), str(packets), str(tmp_path))
    # EPISODE_QC.json describes the REEL; a partial one would be a reel partly
    # unjudged, so collecting complaints must not weaken the refusal.
    assert not (tmp_path / "EPISODE_QC.json").exists()


def test_build_collects_a_packet_whose_findings_file_is_unreadable(tmp_path):
    # findings.json exists but is a DIRECTORY: read_text raises OSError, not
    # ValueError. It must be collected like any other complaint, not escape as a
    # traceback that aborts every later episode.
    rm = _rm(tmp_path, n=2)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    packets = tmp_path / "qc"
    (packets / "ep0" / "findings.json").mkdir(parents=True)
    _findings(packets, 1)
    with pytest.raises(ValueError) as e:
        episode_qc.build(str(ep_path), str(packets), str(tmp_path))
    msg = str(e.value)
    assert "ep0" in msg and "complaint(s) across" in msg
    assert not (tmp_path / "EPISODE_QC.json").exists()


# --- 2026-09-09 bound-reports Task 4: the evidence packet binds to its own clip ---

def _ep(clip: str, tmp_path, name: str = "ep0") -> ReelEpisode:
    """A single ReelEpisode for a caller-supplied clip path, mirroring _rm's own
    per-episode construction (this file's existing build_qc tests) but for a clip a
    test needs to hold a reference to and mutate (re-render) after building the
    manifest — which is exactly what the tests below need to do."""
    return ReelEpisode(manifest={"segment": f"{name}.mp4", "target_dur": 2.0},
                       clip=clip, route=None,
                       path=str(tmp_path / name / "path.json"),
                       meta=str(tmp_path / name / "path.meta.json"))


def test_build_qc_refuses_a_packet_whose_clip_has_been_re_rendered(tmp_path):
    clip = tmp_path / "ep0.mp4"
    clip.write_bytes(b"first-render")
    ep = _ep(str(clip), tmp_path)                     # the file's existing helper
    p = tmp_path / "EPISODES.json"
    ReelManifest(episodes=[ep], target_dur=3.0, changelog="x").write(p)
    packets = tmp_path / "qc"
    (packets / "ep0").mkdir(parents=True)
    (packets / "ep0" / "evidence.json").write_text(json.dumps(
        {"idx": 0, "clip": str(clip), "clip_digest": provenance.digest_file(clip)}))
    (packets / "ep0" / "findings.json").write_text(json.dumps(
        {"summary": "ok", "reviewer": "t", "findings": []}))
    clip.write_bytes(b"second-render")                # re-rendered after packing
    with pytest.raises(ValueError, match="was packed from a different render"):
        episode_qc.build_qc(str(p), str(packets))


def test_build_qc_refuses_a_packet_that_records_no_digest_at_all(tmp_path):
    clip = tmp_path / "ep0.mp4"
    clip.write_bytes(b"render")
    ep = _ep(str(clip), tmp_path)
    p = tmp_path / "EPISODES.json"
    ReelManifest(episodes=[ep], target_dur=3.0, changelog="x").write(p)
    packets = tmp_path / "qc"
    (packets / "ep0").mkdir(parents=True)
    (packets / "ep0" / "evidence.json").write_text(json.dumps({"idx": 0, "clip": str(clip)}))
    (packets / "ep0" / "findings.json").write_text(json.dumps(
        {"summary": "ok", "reviewer": "t", "findings": []}))
    with pytest.raises(ValueError, match="records no clip digest"):
        episode_qc.build_qc(str(p), str(packets))


def test_a_packet_digest_complaint_joins_the_others_in_one_raise(tmp_path):
    """One pass names every complaint (the build_qc rule since 2026-09-08): a digest
    mismatch on ep0 must not hide a malformed finding on ep1."""
    clips = []
    for i in range(2):
        c = tmp_path / f"ep{i}.mp4"
        c.write_bytes(f"render{i}".encode())
        clips.append(c)
    eps = [_ep(str(c), tmp_path, name=f"ep{i}") for i, c in enumerate(clips)]
    p = tmp_path / "EPISODES.json"
    ReelManifest(episodes=eps, target_dur=3.0, changelog="x").write(p)
    packets = tmp_path / "qc"
    for i, c in enumerate(clips):
        (packets / f"ep{i}").mkdir(parents=True)
        (packets / f"ep{i}" / "evidence.json").write_text(json.dumps(
            {"idx": i, "clip": str(c), "clip_digest": provenance.digest_file(c)}))
    (packets / "ep0" / "findings.json").write_text(json.dumps(
        {"summary": "ok", "reviewer": "t", "findings": []}))
    (packets / "ep1" / "findings.json").write_text(json.dumps(
        {"summary": "ok", "reviewer": "t", "findings": [{"axis": "nope"}]}))
    clips[0].write_bytes(b"re-rendered")
    with pytest.raises(ValueError) as e:
        episode_qc.build_qc(str(p), str(packets))
    assert "ep0" in str(e.value) and "ep1 finding 0" in str(e.value)


# --- second real run S14: pack writes the judge's prompt, filled ---

def _ev(tmp_path, **over):
    ev = {"idx": 0, "clip": str(tmp_path / "ep0.mp4"), "clip_digest": "d",
          "intent": {"composition": "lead", "grid": "thirds"},
          "storyboard": str(tmp_path / "sb.jpg"), "storyboard_px": [1080, 1920],
          "strip": str(tmp_path / "qc" / "ep0" / "strip.jpg"), "strip_px": [180, 320],
          "naturalness": {"stats": {"frames": 3}}, "checks": {"overall": "pass"},
          "track": {"degraded": None}, "geometry": {"freedom": 384}}
    ev.update(over)
    return ev


def test_the_judge_prompt_carries_this_episodes_own_evidence(tmp_path):
    d = tmp_path / "qc" / "ep0"
    text = episode_qc.judge_prompt(_ev(tmp_path), d)
    assert "{" + "INTENT}" not in text and '"composition": "lead"' in text
    assert f"Frame strip: {tmp_path / 'qc' / 'ep0' / 'strip.jpg'} — 180x320 px" in text
    assert f"Storyboard: {tmp_path / 'sb.jpg'} — 1080x1920 px" in text
    assert f'--source "{tmp_path / "ep0.mp4"}"' in text      # quoted: macOS paths carry spaces
    assert f"Write your output to {(d / 'findings.json').resolve()} as JSON" in text
    assert 'Path: {\n "freedom": 384\n}' in text


def test_the_judge_prompt_tells_never_ran_from_ran_and_lost(tmp_path):
    ev = _ev(tmp_path, storyboard=None, storyboard_px=None, checks=None, track=None,
             unreadable={"route.meta.json": "Expecting value: line 1 column 1 (char 0)"})
    text = episode_qc.judge_prompt(ev, tmp_path / "qc" / "ep0")
    assert "Storyboard: none recorded — none recorded px" in text
    assert "## The mechanical checks (already passed — context, not yours to re-litigate)" in text
    checks = text.split("## The mechanical checks")[1].split("## Tracker")[0]
    assert checks.rstrip().endswith("none recorded")
    assert "Tracker: unreadable: Expecting value: line 1 column 1 (char 0)" in text


def test_pack_writes_the_prompt_beside_the_evidence(tmp_path, monkeypatch):
    rm = _rm(tmp_path, n=1)
    p = tmp_path / "EPISODES.json"
    rm.write(p)
    monkeypatch.setattr(episode_qc, "_epdir", lambda ep, i: tmp_path / f"ep{i}")
    monkeypatch.setattr(episode_qc.assembly, "probe_stream",
                        lambda c: SimpleNamespace(fps=30.0, w=1080, h=1920))
    monkeypatch.setattr(episode_qc.assembly, "probe_duration", lambda c: 2.0)
    monkeypatch.setattr(episode_qc.contact_sheet, "build_strip",
                        lambda src, out, **k: {"strip": out, "cell_px": (180, 320)})
    monkeypatch.setattr(episode_qc.assembly, "frames_rgb",
                        lambda c, t, fps: [np.full((4, 4, 3), 128, dtype=np.uint8)
                                           for _ in t])
    monkeypatch.setattr(episode_qc, "_source_reading", lambda ep, stats: {})
    res = episode_qc.pack(str(p), str(tmp_path / "qc"))
    prompt = tmp_path / "qc" / "ep0" / "judge_prompt.md"
    assert res["prompts"] == [str(prompt)]
    assert "Frame strip: " + str(tmp_path / "qc" / "ep0" / "strip.jpg") in prompt.read_text()


def test_an_unreadable_report_lands_under_the_checks(tmp_path):
    ev = _ev(tmp_path, checks=None, unreadable={"report.json": "truncated"})
    text = episode_qc.judge_prompt(ev, tmp_path / "qc" / "ep0")
    checks = text.split("## The mechanical checks")[1].split("## Tracker")[0]
    assert checks.rstrip().endswith("unreadable: truncated")
    assert text.count("unreadable: truncated") == 1


def test_an_unreadable_path_record_lands_under_the_path(tmp_path):
    ev = _ev(tmp_path, geometry=None, unreadable={"path.meta.json": "truncated"})
    text = episode_qc.judge_prompt(ev, tmp_path / "qc" / "ep0")
    assert "Path: unreadable: truncated" in text
    assert text.count("unreadable: truncated") == 1
