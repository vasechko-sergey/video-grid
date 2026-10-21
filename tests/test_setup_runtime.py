"""setup.sh runtime layout (design 2026-07-22 runtime-resolution §2/§3, 2026-10-21 §1).

setup.sh is shell, not Python — its real behaviour is a user-run proof (a fresh
install, then a reel). This lints that it EMITS the operations the layout depends on,
so a regression that drops one fails loud here: an external venv, the state it
records kept in the user's directories rather than beside the code (a plugin version
directory is replaced on the next update), the weights fetched where bin/vg works,
and the requirements stamp verify_runtime reads.
"""
from pathlib import Path

SETUP = (Path(__file__).resolve().parents[1] / "setup.sh").read_text()


def test_venv_is_built_at_an_external_xdg_path():
    assert 'VG_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/video-grid"' in SETUP
    assert 'VENV="$VG_DATA/venv"' in SETUP


def test_a_clones_dot_venv_is_a_symlink_into_the_external_venv():
    assert 'ln -sfn "$VENV" "$SKILL_DIR/.venv"' in SETUP


def test_setup_records_its_state_in_the_users_config_dir_not_beside_the_code():
    assert 'VG_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/video-grid"' in SETUP
    assert '> "$VG_CONFIG/ffmpeg.env"' in SETUP
    assert 'SRC_ENV="$VG_CONFIG/sourcing.env"' in SETUP
    assert '"$SKILL_DIR/config/ffmpeg.env"' not in SETUP       # the in-tree record is gone
    assert '/root"' not in SETUP                               # nothing reads a recorded root


def test_an_old_clones_jamendo_key_is_moved_not_lost():
    i = SETUP.index('cp "$SKILL_DIR/config/sourcing.env" "$SRC_ENV"')
    assert '[ ! -e "$SRC_ENV" ]' in SETUP[SETUP.rfind("\n", 0, i - 120):i]


def test_setup_fetches_the_weights_where_bin_vg_works():
    """verify_runtime REQUIRES the weights in the shared models directory, and
    ultralytics downloads a bare model name into the CURRENT directory — so the fetch
    must run from $MODELS_DIR, bin/vg's own working directory, with the code on
    PYTHONPATH, and name the same file the probe checks (MODELS[0])."""
    i = SETUP.index("ensure_model(MODELS[0])")
    line = SETUP[SETUP.rfind("(cd ", 0, i):i]
    assert line.startswith('(cd "$MODELS_DIR" && PYTHONPATH="$SKILL_DIR"'), line[:80]
    assert "from scripts.lib.models import MODELS" in SETUP
    assert 'MODELS_DIR="$VG_DATA/models"' in SETUP


def test_setup_stamps_the_venv_with_the_requirements_it_installed():
    i = SETUP.index('> "$VENV/.video-grid-requirements"')
    assert SETUP.index('install -r "$SKILL_DIR/requirements.txt"') < i
    assert '"$SKILL_DIR/requirements.txt"' in SETUP[i - 200:i]
