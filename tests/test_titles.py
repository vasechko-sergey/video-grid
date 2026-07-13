import json
import sys

import pytest

from scripts import titles as titles_cli
from scripts.lib.spec import Spec


def test_build_cli_writes_pair_and_exits_0(tmp_path, monkeypatch, capsys):
    sp = tmp_path / "SPEC.json"
    Spec(canvas=(1080, 1920), length_s=30.0, mood="calm", hook="Hi", ending="Bye").write(sp)
    out = tmp_path / "run"
    monkeypatch.setattr(sys, "argv", ["titles", "build", "--spec", str(sp),
                                      "--total", "30", "--out-dir", str(out)])
    with pytest.raises(SystemExit) as e:
        titles_cli.main()
    assert e.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 2
    assert (out / "TITLES.json").exists()
