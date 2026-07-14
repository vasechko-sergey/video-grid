# tests/test_pacing_driver.py
"""pacing driver — synthetic MUSIC.json (no librosa); asserts artifacts + cross-check log."""
import json
import sys

import pytest

from scripts import pacing as driver
from scripts.lib.pacing import Spine


def _music_json(tmp_path, duration=12.0):
    p = tmp_path / "MUSIC.json"
    beats = [round(i * 0.5, 6) for i in range(int(duration / 0.5))]
    energy = [0.05] * 8 + [0.95] * 8 + [0.05] * 8
    p.write_text(json.dumps({"track": "t.wav", "start_offset": 0.0, "duration": duration,
                             "tempo": 120.0, "beats": beats, "energy": energy, "energy_hz": 2.0}))
    return p


def _spec_json(tmp_path, length_s):
    p = tmp_path / "SPEC.json"
    p.write_text(json.dumps({"canvas": [1080, 1920], "length_s": length_s,
                             "mood": "energetic", "hook": "watch this"}))
    return p


def test_build_pacing_writes_json_and_md(tmp_path):
    res = driver.build_pacing(str(_music_json(tmp_path)), str(tmp_path))
    assert res["json"].endswith("PACING.json") and res["md"].endswith("PACING.md")
    sp = Spine.from_json(res["json"])
    assert sp is res["spine"] or sp == res["spine"]      # round-trips + validates
    assert (tmp_path / "PACING.md").read_text().startswith("# Pacing")


def test_build_pacing_logs_length_mismatch(tmp_path, capsys):
    driver.build_pacing(str(_music_json(tmp_path, duration=12.0)), str(tmp_path),
                        str(_spec_json(tmp_path, length_s=30.0)))
    assert "SPEC.length_s 30.0s != MUSIC.duration 12.0s" in capsys.readouterr().err


def test_build_pacing_silent_when_length_matches(tmp_path, capsys):
    driver.build_pacing(str(_music_json(tmp_path, duration=12.0)), str(tmp_path),
                        str(_spec_json(tmp_path, length_s=12.0)))
    assert capsys.readouterr().err == ""


def test_cli_prints_two_paths(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["pacing", "--music", str(_music_json(tmp_path)),
                                      "--out-dir", str(tmp_path)])
    driver.main()
    out = capsys.readouterr().out.splitlines()
    assert out[0].endswith("PACING.json") and out[1].endswith("PACING.md")
