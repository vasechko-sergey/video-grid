import json
import sys

import pytest

from scripts import titles as titles_cli
from scripts.lib.spec import Spec
from scripts.lib.titles import Title, Titles, build_filterchain, STYLES


def test_build_cli_writes_pair_and_exits_0(tmp_path, monkeypatch, capsys):
    sp = tmp_path / "SPEC.json"
    Spec(canvas=(1080, 1920), length_s=30.0, mood="calm", hook="Hi", text="Bye").write(sp)
    out = tmp_path / "run"
    monkeypatch.setattr(sys, "argv", ["titles", "build", "--spec", str(sp),
                                      "--total", "30", "--out-dir", str(out)])
    with pytest.raises(SystemExit) as e:
        titles_cli.main()
    assert e.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1                 # the text only — hook names a shot
    assert (out / "TITLES.json").exists()


def test_outline_bold_is_a_style():
    assert "outline-bold" in STYLES
    assert Title(text="hi", start=0.0, dur=1.0, style="outline-bold").style == "outline-bold"


def test_outline_bold_draws_a_heavier_border_than_outline(tmp_path):
    bold = build_filterchain(Titles(items=(Title(text="hi", start=0.0, dur=1.0,
                                                 style="outline-bold"),)), str(tmp_path))
    thin = build_filterchain(Titles(items=(Title(text="hi", start=0.0, dur=1.0,
                                                 style="outline"),)), str(tmp_path))
    assert "borderw=7" in bold and "borderw=4" in thin
    assert "shadowx=3" in bold and "shadow" not in thin
