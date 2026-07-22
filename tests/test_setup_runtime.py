"""setup.sh runtime layout (design 2026-07-22 runtime-resolution §2/§3).

setup.sh is shell, not Python — its real behaviour is a user-run proof (rebuild +
/plugin install). This lints that it EMITS the three operations the fix depends on,
so a regression that drops one fails loud here: an external venv, a `.venv` symlink
into it, and the recorded runtime root outside the tree.
"""
from pathlib import Path

SETUP = (Path(__file__).resolve().parents[1] / "setup.sh").read_text()


def test_venv_is_built_at_an_external_xdg_path():
    assert "XDG_DATA_HOME" in SETUP
    assert "video-grid/venv" in SETUP  # not $SKILL_DIR/.venv any more


def test_dot_venv_is_a_symlink_into_the_external_venv():
    assert "ln -sfn" in SETUP
    # the in-repo .venv is replaced by a link, not a real dir (migration)
    assert '"$SKILL_DIR/.venv"' in SETUP


def test_setup_records_the_runtime_root_outside_the_tree():
    assert "XDG_CONFIG_HOME" in SETUP
    assert "video-grid" in SETUP and "/root" in SETUP
