"""The bindings, proved through the drivers that write them
(design docs/specs/2026-09-09-bound-reports-design.md).

Four proofs, each with a control that must NOT move. P3's control is the
load-bearing one: an EDL rewrite that does not touch tone must leave match-grade
FRESH, which is what separates a binding to the report's own claim from a digest
of the file it read — the naive instrument the design rejected in §1, because
match_grade rewrites that EDL itself and edit_plan --pacing rewrites it again.

Not proved here: a genuinely SIGKILLed ffmpeg. Task 5's kill is a stubbed proc.run
that writes bytes and then raises, which is the state a killed subprocess leaves;
arranging a real signal inside pytest tests the signal, not the rename.
"""
import json
from pathlib import Path

import pytest

from scripts import check_reel, deliver, match_grade, montage, reel_review
from scripts.lib import assembly, matchgrade, provenance, runlayout
from scripts.lib.edl import EDL, EDLEpisode
from scripts.lib.models import (EpisodeGeometry, ReelCheckSpec, ReelGeometry, REEL_H264)


def _deliver_one(tmp_path, sample_clip, changelog):
    """A real encode through deliver into the run's deliveries bucket. Returns its path."""
    lay = runlayout.RunLayout(tmp_path)
    lay.deliveries.mkdir(parents=True, exist_ok=True)
    master = str(tmp_path / "master.mp4")
    assembly.concat([str(sample_clip)], master)
    dur = assembly.probe_duration(master)
    rep = check_reel.run(master, [str(sample_clip)], ReelCheckSpec(target_dur=dur),
                         str(tmp_path / "r.json"))
    assert rep.overall
    return deliver.deliver(master, REEL_H264, str(lay.deliveries), changelog, rep,
                           scratch_dir=str(lay.build))


@pytest.mark.integration
def test_a_review_is_bound_to_the_bytes_it_judged(tmp_path, sample_clip):
    lay = runlayout.RunLayout(tmp_path)
    v1 = _deliver_one(tmp_path, sample_clip, "first cut")
    review = reel_review.build_review([], v1, summary="clean")
    reel_review.write_review(review, str(lay.reel_dir))
    # bound: verify re-hashes and agrees
    assert montage.verify(str(tmp_path))["review"]["state"] == "bound"
    # and the CONTROL that must not move: status, which hashes nothing, calls it fresh
    assert montage._review_state(lay.reel_dir, lay.deliveries) == ("fresh", "")
    # the reel is swapped under the same name (only possible by hand — 0.3.0's monotone
    # versioning stops the pipeline doing it): bytes catch it, names cannot
    Path(v1).write_bytes(b"a different reel entirely")
    assert montage.verify(str(tmp_path))["review"]["state"] == "digest-mismatch"
    assert montage._review_state(lay.reel_dir, lay.deliveries) == ("fresh", "")


@pytest.mark.integration
def test_a_second_delivery_makes_the_review_stale_without_hashing(tmp_path, sample_clip):
    """The run's actual failure: REVIEW.json approved REEL_v1 while a later version
    shipped, and the router still read the stage as done."""
    lay = runlayout.RunLayout(tmp_path)
    v1 = _deliver_one(tmp_path, sample_clip, "first cut")
    reel_review.write_review(reel_review.build_review([], v1, summary="clean"),
                             str(lay.reel_dir))
    before = next(s for s in montage.next_action(str(tmp_path))["stages"]
                  if s["key"] == "reel-review")
    assert (before["state"], before["stale_reason"]) == ("done", "")   # control
    _deliver_one(tmp_path, sample_clip, "second cut")
    after = next(s for s in montage.next_action(str(tmp_path))["stages"]
                 if s["key"] == "reel-review")
    assert after["state"] == "stale"
    assert "REEL_v1.mp4" in after["stale_reason"] and "REEL_v2.mp4" in after["stale_reason"]


def _geometry(tmp_path, sources):
    """A GEOMETRY.json + the EDL it names, one trivial episode per source.

    `EpisodeGeometry.source`/`.route` are what `conduct()`'s `require_inputs` guard
    checks for existence (whole-branch review, minor 5) BEFORE `measure_crop` is ever
    called — mirroring tests/lib/test_match_grade.py's own `_touch()` helper — so each
    source needs a real (empty; measure_crop is mocked below and never decodes it) file
    on disk. `EDLEpisode.source` carries no such check (it is an editorial label, not a
    path reframe opens here), so it stays the bare name.
    """
    lay = runlayout.RunLayout(tmp_path)
    lay.reel_dir.mkdir(parents=True, exist_ok=True)
    edl_path = lay.reel_dir / "EDL.json"
    # the same shape tests/lib/test_match_grade.py::_ep builds — EDLEpisode carries the
    # picture intent as flat fields, not a ReframeSpec
    eps = tuple(EDLEpisode(source=s, start=0.0, dur=2.0, shot_type="wide",
                           composition="center", grid="thirds")
                for s in sources)
    edl_path.write_text(json.dumps(EDL(episodes=eps).to_dict(), indent=2))
    geo_episodes = []
    for i, s in enumerate(sources):
        src_path = tmp_path / s
        src_path.touch()
        (tmp_path / f"r{i}.json").write_text("[]")
        geo_episodes.append(EpisodeGeometry(manifest={}, route=str(tmp_path / f"r{i}.json"),
                                            source=str(src_path),
                                            project_dir=str(tmp_path / f"p{i}")))
    geo = ReelGeometry(episodes=tuple(geo_episodes), edl=str(edl_path))
    gp = lay.episodes / "GEOMETRY.json"
    lay.episodes.mkdir(parents=True, exist_ok=True)
    geo.write(gp)
    return str(gp), edl_path


@pytest.mark.integration
def test_match_grade_goes_stale_on_a_wipe_and_stays_fresh_on_an_unrelated_rewrite(
        tmp_path, monkeypatch):
    """THE control of this branch. A tone wipe must be caught; an EDL rewrite that
    leaves tone alone must NOT be — a whole-file digest would fail this test, and the
    design rejected it for exactly that (§1)."""
    lay = runlayout.RunLayout(tmp_path)
    monkeypatch.setattr(match_grade, "measure_crop",
                        lambda md, src, route, **k: (10.0, 90.0, 150.0) if "a.mp4" in src
                        else (60.0, 140.0, 240.0))
    gp, edl_path = _geometry(tmp_path, ["a.mp4", "b.mp4"])
    match_grade.write_match(gp)
    assert montage._match_grade_state(lay.reel_dir) == ("fresh", "")

    # CONTROL: rewrite the EDL touching something that is not tone. The file's bytes
    # and its provenance stamp both change; the report's claim does not.
    raw = json.loads(edl_path.read_text())
    raw["changelog"] = "an unrelated edit"
    edl_path.write_text(json.dumps(raw, indent=2))
    assert montage._match_grade_state(lay.reel_dir) == ("fresh", "")

    # the failure: a later edit_plan --pacing run wipes authored tone
    raw = json.loads(edl_path.read_text())
    for e in raw["episodes"]:
        e["tone_src"] = e["tone_dst"] = None
    edl_path.write_text(json.dumps(raw, indent=2))
    state, why = montage._match_grade_state(lay.reel_dir)
    assert state == "stale"
    assert "episode 0 was authored a tone pair" in why
    row = next(s for s in montage.next_action(str(tmp_path))["stages"]
               if s["key"] == "match-grade")
    assert row["state"] == "stale"


@pytest.mark.integration
def test_an_interrupted_delivery_is_named_and_costs_no_version(tmp_path, sample_clip,
                                                               monkeypatch):
    lay = runlayout.RunLayout(tmp_path)
    v1 = _deliver_one(tmp_path, sample_clip, "first cut")
    # CONTROL: a completed delivery leaves nothing behind and reads as delivered
    res = montage.next_action(str(tmp_path))
    assert res["interrupted"] == [] and res["delivered"] is True

    real_run = deliver.proc.run
    def die(cmd, *a, **k):
        # Kill ONLY the encode that lands on the dotted `.part.` sibling (deliver's own
        # write, design 2026-09-09 §5) — not the concat/ffprobe/blackdetect/loudnorm
        # calls `_deliver_one` makes on the way there, and not the `git` calls
        # engine_stamp() makes inside deliver's own attestation. A blanket "anything
        # but git/ffprobe" kill (the brief's original shape) also catches
        # assembly.concat's ffmpeg call and check_reel's _black_hits ffmpeg call —
        # both proc.run through the SAME module object this monkeypatch replaces
        # globally — so the RuntimeError this test expects would fire one step early,
        # from _deliver_one's own concat, and deliver.deliver would never even run.
        if cmd and Path(str(cmd[-1])).match(runlayout.PARTIAL_GLOB):
            Path(cmd[-1]).write_bytes(b"half-an-encode")
            raise RuntimeError("killed by a Bash timeout")
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(deliver.proc, "run", die)
    with pytest.raises(RuntimeError, match="killed"):
        _deliver_one(tmp_path, sample_clip, "second cut")
    monkeypatch.undo()

    res = montage.next_action(str(tmp_path))
    assert res["interrupted"] == [".REEL_v2.part.mp4"]
    assert sorted(p.name for p in lay.deliveries.glob("REEL_v*.mp4")) == ["REEL_v1.mp4"]
    assert (lay.deliveries / "VERSIONS.md").read_text().count("- v2 |") == 0
    # the killed version is retried, not burned
    assert deliver._next_version(str(lay.deliveries), "mp4") == 2
    assert _deliver_one(tmp_path, sample_clip, "second cut, for real").endswith("REEL_v2.mp4")
    assert montage.next_action(str(tmp_path))["interrupted"] == []
