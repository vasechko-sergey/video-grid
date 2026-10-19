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


def test_setup_fetches_the_weights_verify_runtime_requires():
    """A fresh clone has no yolo11n-seg.pt (gitignored), verify_runtime REQUIRES it at
    the clone root with the remedy `bash setup.sh`, and using-montage stops at step 0 on
    a failed check — so setup must fetch it, or the remedy cannot fix what it names.
    Ultralytics downloads a bare model name into the CURRENT directory, so the fetch must
    run from the clone root and name the same file the probe checks (MODELS[0])."""
    i = SETUP.index("ensure_model(MODELS[0])")
    assert 'cd "$SKILL_DIR"' in SETUP[SETUP.rfind("\n", 0, SETUP.rfind("cd ", 0, i)):i]
    assert "from scripts.lib.models import MODELS" in SETUP
