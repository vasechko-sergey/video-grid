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
    ep = ReelEpisode(manifest={"segment": "s.mp4"}, clip=str(tmp_path / "ep0.mp4"),
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

    def _plan_ungraded(md, src, route):
        seen["planned"] = (md, src, route)
        return plan_obj
    monkeypatch.setattr(episode_qc.process_episode, "plan_ungraded", _plan_ungraded)

    def _plan_frames_rgb(plan, src, times):
        seen["rendered"] = (plan, src, times)
        return [_flat_frame() for _ in times]
    monkeypatch.setattr(episode_qc.reframe, "plan_frames_rgb", _plan_frames_rgb)

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

    def _plan_ungraded(md, src, route):
        seen["planned"] = (md, src, route)
        return _fake_plan()
    monkeypatch.setattr(episode_qc.process_episode, "plan_ungraded", _plan_ungraded)
    monkeypatch.setattr(episode_qc.reframe, "plan_frames_rgb",
                        lambda plan, src, times: [_flat_frame() for _ in times])

    d_out = episode_qc._source_reading(ep, {"cast": 0.0, "saturation": 0.0, "contrast": 100.0})

    assert seen["planned"][1] == str(stabilized)
    assert seen["planned"][1] != raw
    assert d_out["source"] is not None


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
