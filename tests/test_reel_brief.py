import json
import sys

import pytest

from scripts import reel_brief
from scripts.lib.project import resolve_project
from scripts.lib.spec import Spec
from scripts.reel_brief import build_spec, write_reel_brief


def _project(tmp_path):
    cfg = resolve_project("reel", quality="native")
    cfg.write(tmp_path / "project.json")
    return str(tmp_path / "project.json")


def test_build_spec_reads_canvas_from_project(tmp_path):
    spec = build_spec(_project(tmp_path), length_s=30, mood="calm", hook="slow push")
    assert spec.canvas == (9, 16)          # reel purpose → 9:16, inherited not re-asked
    assert isinstance(spec, Spec)


def test_build_spec_missing_project_fails_loud(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_spec(str(tmp_path / "nope.json"), length_s=30, mood="x", hook="y")


def test_build_spec_forwards_cast_and_editorial(tmp_path):
    spec = build_spec(_project(tmp_path), length_s=20, mood="calm", hook="h",
                      cast=["Anna", "Ben"], music_mode="local")
    assert spec.cast == ("Anna", "Ben") and spec.music_mode == "local"


def test_the_cli_has_no_style_lean_flag_any_more():
    """Removed 2026-10-20 (backlog U1): the brief asked it and no code read it."""
    with pytest.raises(SystemExit):
        reel_brief.build_parser().parse_args(
            ["build", "--project", "p.json", "--length", "30", "--mood", "calm",
             "--hook", "h", "--out-dir", "o", "--style-lean", "trend"])


def test_write_reel_brief_emits_both_files(tmp_path):
    spec = build_spec(_project(tmp_path), length_s=30, mood="calm", hook="slow push")
    res = write_reel_brief(spec, str(tmp_path))
    assert res["status"] == "written"
    assert (tmp_path / "SPEC.json").exists() and (tmp_path / "SPEC.md").exists()
    assert Spec.from_json(tmp_path / "SPEC.json").to_dict() == spec.to_dict()
    assert (tmp_path / "SPEC.md").read_text().startswith("# Reel brief —")


def test_cli_build_writes_and_exits_0(tmp_path, monkeypatch, capsys):
    proj = _project(tmp_path)
    monkeypatch.setattr(sys, "argv",
                        ["reel_brief", "build", "--project", proj, "--length", "30",
                         "--mood", "calm", "--hook", "slow push",
                         "--cast", "Anna", "--cast", "Ben", "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        reel_brief.main()
    assert e.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "written"
    spec = Spec.from_json(tmp_path / "SPEC.json")
    assert spec.cast == ("Anna", "Ben") and spec.length_s == 30.0


def test_build_spec_leaves_tone_bias_none_when_unasked(tmp_path):
    # None is not the same answer as (0,0,0): it means "take the mood preset's
    # taste" (design 2026-09-03 §2), so an accidental default here would silently
    # disable the preset's own displacement on every brief.
    spec = build_spec(_project(tmp_path), length_s=30, mood="calm", hook="h")
    assert spec.tone_bias is None


def test_build_spec_forwards_an_authored_tone_bias(tmp_path):
    spec = build_spec(_project(tmp_path), length_s=30, mood="calm", hook="h",
                      tone_bias=(20, 0, -18))
    assert spec.tone_bias == (20.0, 0.0, -18.0)


def _cli(tmp_path, monkeypatch, *extra):
    proj = _project(tmp_path)
    monkeypatch.setattr(sys, "argv",
                        ["reel_brief", "build", "--project", proj, "--length", "30",
                         "--mood", "calm", "--hook", "h", "--out-dir", str(tmp_path),
                         *extra])
    with pytest.raises(SystemExit) as e:
        reel_brief.main()
    assert e.value.code == 0
    return Spec.from_json(tmp_path / "SPEC.json")


def test_cli_round_trips_an_authored_tone_bias(tmp_path, monkeypatch, capsys):
    spec = _cli(tmp_path, monkeypatch, "--tone-bias", "20,0,-18")
    # The absolute value first, and deliberately: comparing only against build_spec's
    # own output passes when BOTH sides drop the field, which is exactly what a
    # missing forward looks like (caught by mutating the forward away).
    assert spec.tone_bias == (20.0, 0.0, -18.0)
    assert spec.to_dict() == build_spec(_project(tmp_path), length_s=30, mood="calm",
                                        hook="h", tone_bias=(20, 0, -18)).to_dict()


def test_cli_without_the_flag_writes_null_not_a_default(tmp_path, monkeypatch, capsys):
    # The omitted flag must reach Spec as None, and SPEC.json must say null —
    # match_grade._resolve_bias reads that null as "take the preset's taste".
    spec = _cli(tmp_path, monkeypatch)
    assert spec.tone_bias is None
    assert json.loads((tmp_path / "SPEC.json").read_text())["tone_bias"] is None


def test_cli_accepts_an_explicit_zero_bias(tmp_path, monkeypatch, capsys):
    # "this mood, but leave my colour alone" — a real answer, and the one a
    # truthiness test on the raw flag string would collapse into None.
    spec = _cli(tmp_path, monkeypatch, "--tone-bias", "0,0,0")
    assert spec.tone_bias == (0.0, 0.0, 0.0)


def test_cli_refuses_a_two_element_tone_bias(tmp_path, monkeypatch, capsys):
    proj = _project(tmp_path)
    monkeypatch.setattr(sys, "argv",
                        ["reel_brief", "build", "--project", proj, "--length", "30",
                         "--mood", "calm", "--hook", "h", "--tone-bias", "20,0",
                         "--out-dir", str(tmp_path)])
    with pytest.raises(ValueError, match="tone_bias"):
        reel_brief.main()


def test_cast_share_parses_weights_and_the_equal_shorthand():
    assert reel_brief.parse_cast_share(["Sergei=1", "Lena=2"], ("Sergei", "Lena")) == \
        {"Sergei": 1.0, "Lena": 2.0}
    assert reel_brief.parse_cast_share(["equal"], ("Sergei", "Lena")) == \
        {"Sergei": 1.0, "Lena": 1.0}
    assert reel_brief.parse_cast_share(None, ("Sergei",)) is None
    with pytest.raises(ValueError, match="NAME=WEIGHT"):
        reel_brief.parse_cast_share(["Sergei"], ("Sergei",))
    with pytest.raises(ValueError, match="--cast"):
        reel_brief.parse_cast_share(["equal"], ())


def test_the_cli_writes_the_share_into_spec(tmp_path, monkeypatch, capsys):
    proj = _project(tmp_path)
    monkeypatch.setattr(sys, "argv", ["reel_brief", "build", "--project", str(proj),
                                      "--length", "45", "--mood", "calm", "--hook", "h",
                                      "--cast", "Sergei", "--cast", "Lena",
                                      "--cast-share", "equal", "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        reel_brief.main()
    assert Spec.from_json(tmp_path / "SPEC.json").cast_share == {"Sergei": 1.0, "Lena": 1.0}


def test_cast_share_refuses_a_name_given_twice():
    with pytest.raises(ValueError, match="twice"):
        reel_brief.parse_cast_share(["Lena=1", "Lena=2"], ("Lena",))


def test_the_cli_writes_the_briefs_shot_length(tmp_path, monkeypatch):
    proj = _project(tmp_path)
    monkeypatch.setattr(sys, "argv", ["reel_brief", "build", "--project", str(proj),
                                      "--length", "45", "--mood", "calm", "--hook", "h",
                                      "--asl", "6,10", "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        reel_brief.main()
    assert Spec.from_json(tmp_path / "SPEC.json").asl == (6.0, 10.0)


def test_the_cli_records_a_wish_for_known_tracks(tmp_path, monkeypatch):
    proj = _project(tmp_path)
    monkeypatch.setattr(sys, "argv", ["reel_brief", "build", "--project", str(proj),
                                      "--length", "45", "--mood", "calm", "--hook", "h",
                                      "--music-mode", "any", "--music-known",
                                      "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        reel_brief.main()
    assert Spec.from_json(tmp_path / "SPEC.json").music_known is True


# --- second real run S15: an unknown platform is refused at the brief ---

def test_the_brief_stores_the_zone_a_platform_label_resolves_to(tmp_path):
    """Retro 2026-10-16 S15: "Instagram Reels" was stored as typed and judged against the
    generic zone. The brief now stores the zone's own name, so SPEC.md, the EDL and the
    attestation all say which table applies."""
    spec = build_spec(_project(tmp_path), length_s=30, mood="calm", hook="h",
                      platform="Instagram Reels")
    assert spec.platform == "reels"


@pytest.mark.parametrize("unset", ["", "   "])
def test_the_brief_leaves_an_unset_platform_unset(tmp_path, unset):
    spec = build_spec(_project(tmp_path), length_s=30, mood="calm", hook="h",
                      platform=unset)
    assert spec.platform == ""


def test_the_brief_refuses_a_platform_no_zone_answers_to(tmp_path):
    with pytest.raises(ValueError) as e:
        build_spec(_project(tmp_path), length_s=30, mood="calm", hook="h",
                   platform="facebook")
    msg = str(e.value)
    assert "'facebook'" in msg and "generic zone" in msg
    assert "reels" in msg and "tiktok" in msg and "shorts" in msg
