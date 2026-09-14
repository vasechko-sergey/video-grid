"""bin/vg launcher (design 2026-07-22 §2.1) — the cwd-independence contract.

The launcher is the ONE door skills use to run the pipeline. Two properties no
skill edit can be trusted to preserve, so they are pinned here: it resolves the
repo root from its OWN path (works from any cwd), and it fails loud — naming
setup.sh — when the venv is absent, rather than emitting a raw ENOENT.
"""
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VG = REPO / "bin" / "vg"


def test_launcher_runs_from_a_foreign_cwd(tmp_path):
    """Invoked with cwd OUTSIDE the checkout, bin/vg still resolves ROOT and runs
    `-m scripts.montage` — proving the launcher, not cwd, supplies the root."""
    run = tmp_path / "run"
    run.mkdir()
    scratch = tmp_path / "elsewhere"
    scratch.mkdir()
    proc = subprocess.run(
        [str(VG), "scripts.montage", "status", "--run-dir", str(run)],
        cwd=str(scratch), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert '"project-init"' in proc.stdout
    assert '"state": "next"' in proc.stdout


def test_launcher_runs_a_dash_c_snippet_from_the_clone_cwd(tmp_path):
    """`-c` cannot go through bin/vg's `-m "$@"` exec, so the launcher needs a
    passthrough — and that passthrough must still `cd` to the clone first, for
    the same reason `-m` mode does (ultralytics downloads YOLO weights by bare
    name into cwd). Prove both properties an exit-code-only check would miss:
    the snippet runs at all, and it runs with the clone as cwd, not the
    caller's — asserting only returncode 0 would still pass if the `cd` were
    dropped from the `-c` branch."""
    scratch = tmp_path / "elsewhere"
    scratch.mkdir()
    proc = subprocess.run(
        [str(VG), "-c", "import os, sys; print(os.getcwd()); import scripts.montage"],
        cwd=str(scratch), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[0] == str(REPO)


def test_launcher_fails_loud_without_a_venv(tmp_path):
    """A copy of the launcher in a tree with no .venv exits non-zero and names
    setup.sh — the mutation dropping the guard would surface a raw ENOENT."""
    fake = tmp_path / "checkout"
    (fake / "bin").mkdir(parents=True)
    shutil.copy(VG, fake / "bin" / "vg")
    (fake / "bin" / "vg").chmod(0o755)
    proc = subprocess.run(
        [str(fake / "bin" / "vg"), "scripts.montage", "status"],
        capture_output=True, text=True)
    assert proc.returncode != 0
    assert "setup.sh" in proc.stderr
