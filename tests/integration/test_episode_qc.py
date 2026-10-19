"""The QC gate against real pixels (design docs/specs/2026-08-08-episode-qc-design.md §11).

Fixtures prove the contract; this proves the GATE: a reel that is not fully judged, is
judged stale, or carries a blocking verdict does not get assembled — and a clean one
delivers with the QC state on its attestation."""
import json
from pathlib import Path

import pytest

from scripts import build_reel, edl_to_reel, episode_qc, reframe
from scripts.lib import naturalness, prompts, provenance
from scripts.lib.models import (CheckResult, Delivery, LayoutSpec, ReelEpisode,
                                ReelFailure, ReelManifest, ReelReport, ReframeSpec)


def _episode(sample_clip, tmp, x_const, name, *, black_point: float = 0.0):
    """A real reframed episode with its sidecars named the way process_episode names
    them, so ReelEpisode.path/meta are coherent and pack can derive the scratch dir.

    The manifest carries out_path/canvas (design 2026-08-31 Task 8), matching the
    `spec` this same function renders with two lines above: _source_reading now
    builds an ungraded RENDER PLAN from this manifest (process_episode.plan_ungraded
    -> Manifest.from_dict), not just a file path, and manifest.REQUIRED demands both.
    Before Task 8, _source_reading read ep.manifest["segment"] directly and never
    planned anything, so this fixture's manifest never needed to be plannable.

    `black_point` defaults to 0.0 (identity — every caller but one) so the other
    tests in this file are byte-for-byte what they were before Task 8; one test
    below needs an episode that actually carries a grade."""
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    route = [dict(t=i / 10, x=float(x_const), y=540.0, w=140.0, h=320.0) for i in range(30)]
    (d / "route.json").write_text(json.dumps(route))
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=(105.0, 122.0, 137.0), delivery=Delivery("native"),
                       layout=LayoutSpec(mode="fill"), black_point=black_point)
    clip = str(tmp / f"{name}.mp4")
    reframe.reframe(spec, str(sample_clip), str(d / "route.json"), clip, str(d / "path.json"))
    md = {"segment": str(sample_clip), "out_path": clip, "target_dur": 3.0,
          "composition": "center", "grid": "thirds", "canvas": [9, 16]}
    if black_point:
        md["black_point"] = black_point
    return ReelEpisode(manifest=md, clip=clip, route=str(d / "route.json"),
                       path=str(d / "path.json"), meta=str(d / "path.meta.json"))


def _episodes_json(tmp_path, sample_clip, *, black_point: float = 0.0):
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    eps = [_episode(sample_clip, tmp_path, 645, "ep0", black_point=black_point),
           _episode(sample_clip, tmp_path, 1045, "ep1", black_point=black_point)]
    rm = ReelManifest(episodes=eps, target_dur=6.0, changelog="qc proof")
    p = out / "EPISODES.json"
    rm.write(p)
    return p, rm


def _judge(packets, i, severity=None):
    d = Path(packets) / f"ep{i}"
    d.mkdir(parents=True, exist_ok=True)
    fs = [] if severity is None else [
        {"axis": "hero", "severity": severity, "evidence": f"ep{i} follows a bystander",
         "route": "edit-plan", "suggestion": "pin the hero by cast name"}]
    (d / "findings.json").write_text(json.dumps(
        {"summary": f"ep{i}", "reviewer": "integration", "findings": fs}))


@pytest.mark.integration
def test_pack_gives_the_judge_pixels_and_numbers(tmp_path, sample_clip):
    p, _ = _episodes_json(tmp_path, sample_clip)
    res = episode_qc.pack(str(p), str(tmp_path / "qc"))
    assert res["episodes"] == 2
    ev = json.loads((tmp_path / "qc" / "ep0" / "evidence.json").read_text())
    assert (tmp_path / "qc" / "ep0" / "strip.jpg").exists()
    assert ev["intent"]["composition"] == "center"
    assert ev["naturalness"]["stats"]["frames"] == episode_qc.SENSOR_FRAMES
    assert set(ev["naturalness"]["flags"]) == {"blown_highlights", "crushed_blacks"}
    assert ev["geometry"] is not None          # the path.meta sidecar reframe wrote
    # The judge's prompt, filled from that same evidence (retro 2026-10-16 S14).
    prompt = (tmp_path / "qc" / "ep0" / "judge_prompt.md").read_text()
    assert prompts.tokens(prompt) == set()
    assert str((tmp_path / "qc" / "ep0" / "strip.jpg").resolve()) in prompt


@pytest.mark.integration
def test_the_evidence_packet_carries_the_pre_grade_reading(tmp_path, sample_clip):
    """R2.5: the judge must be able to see what the GRADE did, not only what the
    footage is. The segment has always been in the manifest and was never read.

    Task 8 fixed _source_reading to measure the source THROUGH THE EPISODE'S OWN
    CROP PLAN rather than the whole segment frame, so every OTHER episode in this
    file — rendered at identity colour (black_point=0.0) — now correctly reads
    source == stats: there is no grade left for a "delta" to carry, which is the
    point of the fix, not a bug in this test. So this one episode is rendered with
    an actual black_point, to give the grade something real to have done."""
    p, _ = _episodes_json(tmp_path, sample_clip, black_point=0.3)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    nat = json.loads((tmp_path / "qc" / "ep0" / "evidence.json").read_text())["naturalness"]
    assert set(nat) == {"stats", "flags", "source", "delta"}
    assert nat["source"]["frames"] == episode_qc.SENSOR_FRAMES
    # A source reading that happens to equal the graded reading is what a `seg`/`ep.clip`
    # mixup in _source_reading would produce (both would sample the SAME file) — this
    # episode's black_point=0.3 grade (see _episode) gives the two a real difference to
    # be measured, so a correct implementation can never land here by coincidence.
    assert nat["source"] != nat["stats"]
    # Recomputation, not just a key-set check: catches an evaluate_delta(src, graded)
    # argument-order swap. cast_shift/saturation_shift are abs()-symmetric and cannot see
    # a swap; contrast_drop is signed and is what discriminates here. MEASURED (not
    # assumed) on this fixture: source contrast 123.6 vs graded 150.0 — the black_point
    # grade STRETCHES contrast rather than crushing it here, so in the correct order
    # (src - grd = -26.4) contrast_drop reads False, and a swapped order (grd - src =
    # +26.4, past CONTRAST_DROP_MAX 20.0) would flip it to True — either way a swap
    # really does flip contrast_drop's boolean, which is what this assertion catches.
    assert nat["delta"] == naturalness.evaluate_delta(nat["source"], nat["stats"])
    assert set(nat["delta"]) == {"cast_shift", "saturation_shift", "contrast_drop"}


@pytest.mark.integration
def test_a_manifest_with_no_segment_reports_absent_not_empty(tmp_path, sample_clip):
    """Absent is reported as absent, never as a clean reading — the same rule the rest
    of _evidence already applies to the sidecars."""
    p, rm = _episodes_json(tmp_path, sample_clip)
    for ep in rm.episodes:
        ep.manifest.pop("segment")
    rm.write(p)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    nat = json.loads((tmp_path / "qc" / "ep0" / "evidence.json").read_text())["naturalness"]
    assert nat["source"] is None and nat["delta"] is None


@pytest.mark.integration
def test_a_segment_path_missing_from_disk_reports_absent_not_empty(tmp_path, sample_clip):
    """The other half of the guard: the manifest names a segment (the key is present,
    unlike the sibling test above), but the file it points at is gone — a stale manifest
    referencing scratch that has since been cleaned up. Absent is reported as absent
    here too, not a clean reading and not a crash."""
    p, rm = _episodes_json(tmp_path, sample_clip)
    for ep in rm.episodes:
        ep.manifest["segment"] = str(tmp_path / "no-such-segment.mp4")
    rm.write(p)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    nat = json.loads((tmp_path / "qc" / "ep0" / "evidence.json").read_text())["naturalness"]
    assert nat["source"] is None and nat["delta"] is None


@pytest.mark.integration
def test_a_clean_run_delivers_and_the_attestation_names_the_judged_bytes(tmp_path, sample_clip):
    p, rm = _episodes_json(tmp_path, sample_clip)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    _judge(tmp_path / "qc", 0)
    _judge(tmp_path / "qc", 1, "minor")
    episode_qc.build(str(p), str(tmp_path / "qc"), str(p.parent))
    res = edl_to_reel.assemble_reel(str(p), str(tmp_path / "work"))
    assert res["status"] == "delivered"
    att = json.loads(Path(str(provenance.attest_path(res["output"]))).read_text())
    assert att["episode_qc"]["state"] == "judged"
    assert att["episode_qc"]["judged"] == {
        "0": provenance.digest_file(rm.episodes[0].clip),
        "1": provenance.digest_file(rm.episodes[1].clip)}
    assert att["episode_qc"]["reprocessed_after"] == []


@pytest.mark.integration
def test_a_blocking_verdict_stops_the_reel_and_writes_nothing(tmp_path, sample_clip):
    p, _ = _episodes_json(tmp_path, sample_clip)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    _judge(tmp_path / "qc", 0)
    _judge(tmp_path / "qc", 1, "blocking")
    episode_qc.build(str(p), str(tmp_path / "qc"), str(p.parent))
    res = edl_to_reel.assemble_reel(str(p), str(tmp_path / "work"))
    assert res["finding"]["reason"] == "episode-qc-blocking"
    assert list(p.parent.glob("REEL_v*")) == []


@pytest.mark.integration
def test_a_re_rendered_episode_invalidates_its_verdict(tmp_path, sample_clip):
    """The digest binding is load-bearing, not decorative: judge, then rebuild ep0's
    bytes, and the verdict no longer describes the clip that would be assembled."""
    p, rm = _episodes_json(tmp_path, sample_clip)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    _judge(tmp_path / "qc", 0)
    _judge(tmp_path / "qc", 1)
    episode_qc.build(str(p), str(tmp_path / "qc"), str(p.parent))
    Path(rm.episodes[0].clip).write_bytes(
        Path(rm.episodes[0].clip).read_bytes() + b"\x00")      # a different render
    res = edl_to_reel.assemble_reel(str(p), str(tmp_path / "work"))
    assert res["finding"]["reason"] == "episode-qc-stale"
    assert "episode 0" in res["finding"]["problems"][0]


@pytest.mark.integration
def test_an_unjudged_reel_never_reaches_assembly(tmp_path, sample_clip):
    p, _ = _episodes_json(tmp_path, sample_clip)
    res = edl_to_reel.assemble_reel(str(p), str(tmp_path / "work"))
    assert res["finding"]["reason"] == "episode-qc-missing"


def _black_fail(idx):
    """The one canned report in this module. check_reel's real black check needs a real
    black frame in a real source; what this proof is about is the LOOP ARM the failure
    routes to — see the design's §9 note that the two proofs are not joined. (The colour
    corrector is retired, design 2026-08-29 — this used to build an across-cut colour
    fail; the LOOP ARM under test is the same reprocess arm either way.)"""
    return ReelReport(
        checks={"black": CheckResult("black", False, {})},
        fail_reasons=[ReelFailure("black", "reprocess", idx, {"t": 1.0})],
        episode_count=2)


@pytest.mark.integration
def test_a_reprocess_after_the_verdict_stops_the_delivery_and_a_re_judge_clears_it(
        tmp_path, sample_clip, monkeypatch):
    """design 2026-08-18 §2/§2.2 end to end: loop-2 rewrites ep1's bytes AFTER
    episode_qc digested them, so the delivery is refused; re-judging exactly ep1 and
    re-running the same command delivers, with an empty reprocessed list.

    The control that must not move is this module's own
    test_a_clean_run_delivers_and_the_attestation_names_the_judged_bytes — a reel with
    no reprocess still delivers in one pass. Run them together.

    process_episode is faked (the real one runs YOLO) and so is the FIRST check_reel
    round; everything else is real — real reframed clips, real digests, real pack/build,
    real gate, real assemble + check_reel + deliver."""
    p, rm = _episodes_json(tmp_path, sample_clip)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    _judge(tmp_path / "qc", 0)
    _judge(tmp_path / "qc", 1)
    episode_qc.build(str(p), str(tmp_path / "qc"), str(p.parent))
    judged_ep0 = provenance.digest_file(rm.episodes[0].clip)

    # the reprocess, faked at the boundary but writing where the real one writes: the
    # manifest's out_path IS ReelEpisode.clip, which is what makes the verdict stale.
    def fake_pe(manifest, project_dir, route_path=None):
        Path(rm.episodes[1].clip).write_bytes(
            Path(rm.episodes[1].clip).read_bytes() + b"\x00")   # a different render
        return {"status": "mechanical_pass", "clip": rm.episodes[1].clip}
    monkeypatch.setattr(build_reel.process_episode, "process_episode", fake_pe)
    real_run = build_reel.check_reel.run
    rounds = iter([_black_fail(1)])
    monkeypatch.setattr(build_reel.check_reel, "run",
                        lambda *a, **k: next(rounds, None) or real_run(*a, **k))

    res = edl_to_reel.assemble_reel(str(p), str(tmp_path / "work"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "episode-qc-reprocessed"
    assert res["reprocessed"] == [1]
    assert "episode 1" in res["finding"]["problems"][0]
    assert list(p.parent.glob("REEL_v*")) == []          # no version spent, no attestation

    # the re-judge: re-pack FIRST (Task 4, design 2026-09-09 §4) — ep1's evidence.json
    # still names the PREVIOUS render's digest, and re-judging over it unrefreshed is
    # exactly the silent gap this binding exists to close: the judge would be
    # re-validated against a packet describing pixels that no longer exist, even
    # though its findings.json is freshly written. Re-packing costs both episodes a
    # real decode (pack has no --only), but this module's own docstring already
    # promises "real pack/build" end to end. Only THEN are ep1's findings rewritten —
    # ep0's verdict is about bytes that did not change, and episode_qc build
    # re-stamps every digest from disk.
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    _judge(tmp_path / "qc", 1)
    episode_qc.build(str(p), str(tmp_path / "qc"), str(p.parent))
    monkeypatch.setattr(build_reel.check_reel, "run", real_run)
    again = edl_to_reel.assemble_reel(str(p), str(tmp_path / "work"))   # the SAME
    # work dir the router reuses — a fresh one would prove less than the real flow
    assert again["status"] == "delivered"
    assert again["reprocessed"] == []
    att = json.loads(Path(str(provenance.attest_path(again["output"]))).read_text())
    assert att["episode_qc"]["state"] == "judged"
    assert att["episode_qc"]["reprocessed_after"] == []
    # ep0 was never re-judged and never needed to be: its bytes are the judged ones
    assert att["episode_qc"]["judged"]["0"] == judged_ep0
    assert provenance.verify_delivery(again["output"])["episode_qc"] == "judged"


@pytest.mark.integration
def test_the_packet_records_the_digest_of_the_clip_it_decoded(tmp_path, sample_clip):
    p, rm = _episodes_json(tmp_path, sample_clip)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    ev = json.loads((tmp_path / "qc" / "ep0" / "evidence.json").read_text())
    assert ev["clip_digest"] == provenance.digest_file(rm.episodes[0].clip)


@pytest.mark.integration
def test_a_re_rendered_clip_invalidates_its_own_packet(tmp_path, sample_clip):
    """The gate the run needed: pack, re-render, and the judge's verdict must not be
    stamped against pixels nobody judged."""
    p, rm = _episodes_json(tmp_path, sample_clip)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    for i in range(2):
        _judge(str(tmp_path / "qc"), i)
    # control: nothing moved, the gate is silent
    assert episode_qc.build_qc(str(p), str(tmp_path / "qc")).ok
    Path(rm.episodes[0].clip).write_bytes(b"a different render entirely")
    with pytest.raises(ValueError, match="was packed from a different render"):
        episode_qc.build_qc(str(p), str(tmp_path / "qc"))
