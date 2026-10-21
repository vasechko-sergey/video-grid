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


def test_a_clones_dot_venv_is_a_symlink_into_the_external_venv_and_only_a_clones():
    i = SETUP.index('ln -sfn "$VENV" "$SKILL_DIR/.venv"')
    assert 'if [ -e "$SKILL_DIR/.git" ]; then' in SETUP[i - 300:i]


def test_setup_records_its_state_in_the_users_config_dir_not_beside_the_code():
    assert 'VG_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/video-grid"' in SETUP
    assert '> "$VG_CONFIG/ffmpeg.env"' in SETUP
    assert 'SRC_ENV="$VG_CONFIG/sourcing.env"' in SETUP
    assert '"$SKILL_DIR/config/ffmpeg.env"' not in SETUP       # the in-tree record is gone
    assert '> "$VG_CONFIG/root"' not in SETUP                  # the root is never recorded


def test_an_old_clones_jamendo_key_and_weights_are_carried_over_not_lost():
    """A plugin installed from GitHub has no config/, so the key must also be looked
    for in the clone 0.26.0 recorded (the review's I2) — and its weights, so an
    offline upgrade is not blocked by `weights` (M3)."""
    assert 'OLD_CLONE="$(cat "$VG_CONFIG/root" 2>/dev/null || true)"' in SETUP
    assert 'for old in "$SKILL_DIR" "$OLD_CLONE"; do' in SETUP
    i = SETUP.index('cp "$old/config/sourcing.env" "$SRC_ENV"')
    assert '[ ! -e "$SRC_ENV" ]' in SETUP[i - 120:i]
    assert 'cp "$old/yolo11n-seg.pt" "$MODELS_DIR/"' in SETUP


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


def test_setup_stamps_the_venv_after_everything_it_installs():
    i = SETUP.index('mv "$VENV/.video-grid-requirements.tmp" "$VENV/.video-grid-requirements"')
    assert SETUP.index('install -r "$SKILL_DIR/requirements.txt"') < i
    assert SETUP.rindex('pip" install') < i                   # demucs, torchreid: before it


def test_the_stamp_is_computed_away_from_the_callers_working_directory():
    """The re-review's regression: `-c` puts the cwd on sys.path ahead of PYTHONPATH,
    and the setup skill runs setup.sh from the user's project — an old clone's
    `scripts/` was imported instead of the plugin's, and the stamp came out empty or
    the clone's. Both Python steps run from $MODELS_DIR with -P, the stamp is handed
    its root explicitly, and it is written through a temp file."""
    i = SETUP.index('> "$VENV/.video-grid-requirements.tmp"')
    block = SETUP[SETUP.rfind("(cd ", 0, i):i]
    assert block.startswith('(cd "$MODELS_DIR" && PYTHONPATH="$SKILL_DIR" "$VENV/bin/python" -P -c')
    assert "requirements_digest(Path(sys.argv[1]))" in block and '"$SKILL_DIR")' in block
    j = SETUP.index("ensure_model(MODELS[0])")
    assert '"$VENV/bin/python" -P -c' in SETUP[SETUP.rfind("(cd ", 0, j):j]


def test_the_stamp_step_ignores_a_scripts_package_in_the_callers_directory(tmp_path):
    """The re-review's scenario, run: setup.sh's own stamp lines, cut out of the real
    script, executed from a directory holding a foreign `scripts/` package — an old
    clone's, or any project's. The stamp must still be the plugin's own digest."""
    import subprocess
    import sys
    from scripts.lib import userdirs
    repo = Path(__file__).resolve().parents[1]
    start = SETUP.index('(cd "$MODELS_DIR" && PYTHONPATH="$SKILL_DIR" "$VENV/bin/python" -P -c \'import sys')
    end = SETUP.index('mv "$VENV/.video-grid-requirements.tmp"')
    block = SETUP[start:SETUP.index("\n", end)]
    venv, models, evil = tmp_path / "venv", tmp_path / "models", tmp_path / "project"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(sys.executable)
    models.mkdir()
    (evil / "scripts").mkdir(parents=True)
    (evil / "scripts" / "__init__.py").write_text("")          # no scripts.lib in it
    env = {"PATH": "/usr/bin:/bin", "VENV": str(venv), "MODELS_DIR": str(models),
           "SKILL_DIR": str(repo)}
    proc = subprocess.run(["bash", "-euo", "pipefail", "-c", block], cwd=str(evil),
                          env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    stamp = (venv / ".video-grid-requirements").read_text().strip()
    assert stamp == userdirs.requirements_digest(repo)
    assert not (venv / ".video-grid-requirements.tmp").exists()
