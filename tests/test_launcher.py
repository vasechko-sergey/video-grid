"""bin/vg launcher (design 2026-07-22 §2.1, 2026-10-21) — the cwd-independence contract.

The launcher is the ONE door skills use to run the pipeline. Properties no skill
edit can be trusted to preserve, so they are pinned here: it resolves the code root
from its OWN path (works from any cwd and from any copy — a plugin version
directory or a clone), runs the venv kept in the user's data directory, works in the
shared models directory so the YOLO weights land there, and fails loud — naming the
setup skill and setup.sh — when the venv is absent, rather than emitting a raw ENOENT.

Every test points XDG_DATA_HOME at its own directory, holding a link to the venv
running the suite, so the user's real data directory is never touched.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VG = REPO / "bin" / "vg"


def _env(data_home: Path, *, venv: bool = True) -> dict:
    if venv:
        (data_home / "video-grid").mkdir(parents=True, exist_ok=True)
        (data_home / "video-grid" / "venv").symlink_to(Path(sys.prefix))
    return {**os.environ, "XDG_DATA_HOME": str(data_home)}


def test_launcher_runs_from_a_foreign_cwd(tmp_path):
    """Invoked with cwd OUTSIDE the checkout, bin/vg still resolves ROOT and runs
    `-m scripts.montage` — proving the launcher, not cwd, supplies the root."""
    run = tmp_path / "run"
    run.mkdir()
    scratch = tmp_path / "elsewhere"
    scratch.mkdir()
    proc = subprocess.run(
        [str(VG), "scripts.montage", "status", "--run-dir", str(run)],
        cwd=str(scratch), capture_output=True, text=True, env=_env(tmp_path / "data"))
    assert proc.returncode == 0, proc.stderr
    assert '"project-init"' in proc.stdout
    assert '"state": "next"' in proc.stdout


def test_launcher_runs_a_copy_of_the_code_that_is_not_a_clone(tmp_path):
    """The install-without-a-clone case: a plugin version directory is a plain copy of
    the code, with no .venv and no git — and its own launcher runs its own code."""
    copy = tmp_path / "cache" / "0.27.0"
    shutil.copytree(REPO, copy, ignore=shutil.ignore_patterns(
        ".git", ".venv", "tests", "docs", "*.pt", "__pycache__", ".pytest_cache",
        ".superpowers", "research_notes", "reports"))
    proc = subprocess.run(
        [str(copy / "bin" / "vg"), "-c", "import scripts.montage, sys; "
         "print(scripts.montage.__file__)"],
        cwd=str(tmp_path), capture_output=True, text=True, env=_env(tmp_path / "data"))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(copy / "scripts" / "montage.py")


def test_launcher_works_in_the_shared_models_directory(tmp_path):
    """`-c` cannot go through bin/vg's `-m "$@"` exec, so the launcher needs a
    passthrough — and that passthrough must still `cd` first, for the same reason
    `-m` mode does (ultralytics downloads YOLO weights by bare name into cwd). The
    directory is the shared models one, never the code's own: a plugin version
    directory is replaced on the next update, and the weights with it."""
    scratch = tmp_path / "elsewhere"
    scratch.mkdir()
    proc = subprocess.run(
        [str(VG), "-c", "import os; print(os.getcwd()); import scripts.montage"],
        cwd=str(scratch), capture_output=True, text=True, env=_env(tmp_path / "data"))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[0] == str((tmp_path / "data" / "video-grid" / "models")
                                              .resolve())


def test_launcher_fails_loud_without_a_venv(tmp_path):
    """No venv in the data directory: exit non-zero naming the setup skill and
    setup.sh — the mutation dropping the guard would surface a raw ENOENT."""
    proc = subprocess.run(
        [str(VG), "scripts.montage", "status"], capture_output=True, text=True,
        env=_env(tmp_path / "empty", venv=False))
    assert proc.returncode != 0
    assert "/video-grid:setup" in proc.stderr and "setup.sh" in proc.stderr
