import json
from pathlib import Path

import pytest

from scripts import probe
from scripts.lib.edl import EDL, EDLEpisode, write_edl


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
