"""verify-runtime driver (design docs/specs/2026-08-01-verify-runtime-design.md,
docs/specs/2026-09-25-plugin-staleness-design.md).

Probes two layers and reports each gap with its remedy: the `setup.sh` baseline
contract (deps, ffmpeg, filters, font, weights, demucs) and whether the INSTALLED
plugin agrees with the clone this code lives in. The IMPURE half — it imports the
probed modules, resolves ffmpeg, spawns `-filters`, reads the installer's own
record — so the report logic (scripts/lib/preflight.py) stays testable without an
install.

Read-only: it PRINTS remedies, never runs setup.sh (§4). It runs INSIDE the venv
(via bin/vg), so it cannot report a missing venv — that is the pre-venv layer, bin/vg's
own refusal. See design §2/§5, and 2026-10-21 for the venv, the weights and the config
living outside the code.

Imports are kept LIGHT on purpose: a broken heavy dep must be REPORTED by
_probe_deps, not crash this checker on import. models.MODELS pulls no numpy/cv2.
"""
import argparse
import hashlib
import importlib
import json
import os
import sys
from pathlib import Path

from scripts.lib import ffbin, fonts, preflight, userdirs
from scripts.lib.models import MODELS

# The runtime modules the pipeline imports = requirements.txt runtime set (pytest
# excluded, dev-only). Import NAMES, not pip names (Pillow→PIL, yt-dlp→yt_dlp,
# pi-heif→pi_heif, opencv-python→cv2).
_DEPS = ("numpy", "scipy", "PIL", "cv2", "pi_heif", "librosa", "ultralytics",
         "scenedetect", "imagehash", "yt_dlp", "requests", "certifi", "fontTools")

_ROOT = Path(__file__).resolve().parent.parent   # the code's root: a plugin version dir or a clone
STAMP = ".video-grid-requirements"               # setup.sh writes it into the venv


def _probe_deps() -> tuple[bool, str]:
    missing = [m for m in _DEPS if not _importable(m)]
    if missing:
        return False, "missing: " + ", ".join(missing)
    return True, f"{len(_DEPS)} modules import"


def _importable(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:            # ImportError, or a broken C-extension raising other
        return False


def _probe_ffmpeg_bin() -> tuple[bool, str]:
    try:
        fb, fp = ffbin.ffmpeg(), ffbin.ffprobe()
    except ValueError:
        return False, "ffmpeg/ffprobe not on $FFMPEG, the recorded ffmpeg.env, or PATH"
    if not (Path(fb).exists() and Path(fp).exists()):
        return False, f"resolved path does not exist: {fb}"
    return True, fb


def _probe_filter(name: str) -> tuple[bool, str]:
    try:
        present = ffbin.has_filter(name)
    except (ValueError, RuntimeError, OSError):
        # ValueError/RuntimeError: ffbin's own raises (unresolved binary, proc.run's
        # wrapped failures). OSError (PermissionError is a subclass): a RESOLVED but
        # non-executable/corrupted binary — proc.run does not wrap that one, so it
        # would otherwise propagate straight through has_filter and crash this probe.
        return False, "ffmpeg unavailable"
    return (True, "present") if present else (False, f"{name} absent from this ffmpeg build")


def _probe_drawtext() -> tuple[bool, str]:
    return _probe_filter("drawtext")


def _probe_vidstab() -> tuple[bool, str]:
    for filt in ("vidstabdetect", "vidstabtransform"):
        ok, detail = _probe_filter(filt)
        if not ok:
            return False, detail
    return True, "present"


def _probe_font() -> tuple[bool, str]:
    try:
        return True, fonts.resolve_font()
    except ValueError:
        return False, f"no usable font found (checked {len(fonts.FONT_CANDIDATES)} candidates)"


def _probe_icon_font() -> tuple[bool, str]:
    try:
        return True, fonts.resolve_font(fonts.ICON_FONT)
    except ValueError:
        return False, f"{fonts.ICON_FONT} is not installed — a title carrying an icon is refused"


def _probe_weights() -> tuple[bool, str]:
    """In the shared models directory bin/vg works in (design 2026-10-21 §1), not
    beside the code: ultralytics resolves the bare name against the working
    directory, and a plugin version directory is gone on the next update."""
    path = userdirs.models_dir() / MODELS[0]
    if path.exists():
        return True, str(path)
    return False, f"missing at {path} (the first intake downloads it if online)"


def _probe_deps_stamp() -> tuple[bool, str]:
    """The venv's record of the requirements.txt setup.sh installed, against this
    code's own. `sys.prefix`, not userdirs.venv_dir(): the question is about the venv
    RUNNING this check."""
    want = hashlib.sha256((_ROOT / "requirements.txt").read_bytes()).hexdigest()
    stamp = Path(sys.prefix) / STAMP
    if not stamp.is_file():
        return False, (f"no record of which requirements built {sys.prefix} — set up "
                       f"before 0.27.0, or not by setup.sh")
    got = stamp.read_text().strip()
    if got != want:
        return False, (f"built from requirements {got[:12]}…, this code needs "
                       f"{want[:12]}… — the dependencies changed since setup ran")
    return True, f"requirements {want[:12]}…"


def _probe_demucs() -> tuple[bool, str]:
    return (True, "installed") if _importable("demucs") else (False, "not installed")


def _probe_reid() -> tuple[bool, str]:
    return (True, "installed") if _importable("torchreid") else (False, "not installed")


def _read_json(path: Path) -> dict:
    """Parse `path`, raising with the path NAMED. A JSONDecodeError carries only a
    line and column, so an error from a corrupt file would otherwise be attributed
    to whichever `try` block happened to catch it — which is how a broken clone
    manifest came to be reported as an unreadable install record."""
    try:
        return json.loads(path.read_text())
    except Exception as e:
        raise RuntimeError(f"{path}: {e}") from e


def _plugin_id() -> str:
    """`<plugin>@<marketplace>` — the key Claude Code files this install under.
    Derived from the clone's own two manifests rather than typed, so it cannot
    drift from them; the remedy string's copy is pinned to this by a test."""
    cp = _ROOT / ".claude-plugin"
    plugin = _read_json(cp / "plugin.json")["name"]
    market = _read_json(cp / "marketplace.json")["name"]
    return f"{plugin}@{market}"


def _probe_plugin() -> tuple[bool, str]:
    """Compare the INSTALLED plugin against the clone this code lives in.

    The two are installed by different tools into different directories: the
    skills come from Claude Code's version-keyed cache, the Python from the clone
    the recorded root names. Nothing compared them before (design §0.2).

    Read-only, and it reads the installer's own RECORD rather than the cache
    directory — the record is the installer's statement of what it did, and what
    this check asks is whether that statement agrees with the clone."""
    cfg = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    record = cfg / "plugins" / "installed_plugins.json"
    if not record.is_file():
        # Nothing is installed, so nothing can disagree with the clone — and the
        # clone's own manifests are deliberately NOT consulted here. Reading them
        # would let a broken marketplace.json block a run that has no installed
        # skills at all, which is a different question than the one this check
        # asks (design §2.2: a missing record is an unconditional pass).
        return True, preflight.NO_RECORD_DETAIL
    try:
        clone_version = _read_json(_ROOT / ".claude-plugin" / "plugin.json")["version"]
        plugin_id = _plugin_id()
    except Exception as e:
        return False, f"cannot read the clone's plugin manifests: {e}"
    try:
        data = json.loads(record.read_text())
        plugins = data["plugins"]
        if not isinstance(plugins, dict):
            raise TypeError(f"'plugins' is {type(plugins).__name__}, not a mapping")
        entries = plugins.get(plugin_id, [])
        records = tuple((str(e["scope"]), str(e["version"])) for e in entries)
    except Exception as e:
        # Cannot-answer must not read as "nothing installed" — a blocking check
        # that can silently turn itself off is the failure it exists to prevent.
        return False, f"install record unreadable at {record}: {e}"
    return preflight.plugin_staleness(records, clone_version)


_PROBES = {
    "plugin": _probe_plugin,
    "deps": _probe_deps,
    "deps_stamp": _probe_deps_stamp,
    "ffmpeg_bin": _probe_ffmpeg_bin,
    "drawtext": _probe_drawtext,
    "vidstab": _probe_vidstab,
    "font": _probe_font,
    "weights": _probe_weights,
    "demucs": _probe_demucs,
    "reid": _probe_reid,
    "icon_font": _probe_icon_font,
}


def run() -> preflight.RuntimeReport:
    """Run every probe and evaluate the result. evaluate() enforces that _PROBES's
    keys match the registry — a probe/Check drift raises here, not silently.

    Each probe is called defensively: a probe must never crash the whole checker,
    so an unexpected raise (a hole in one probe's own except clause, or a new
    failure mode nobody anticipated) becomes that ONE check's failed outcome
    instead of taking every other check down with it."""
    raw = {}
    for key, probe in _PROBES.items():
        try:
            raw[key] = probe()
        except Exception as e:            # a probe must never crash the checker
            raw[key] = (False, f"probe raised: {e}")
    # root=_ROOT so every remedy carries its own `cd <clone>` — the printed command
    # runs from ANY cwd (the user clicks Run wherever their shell is, not the clone).
    return preflight.evaluate(raw, root=str(_ROOT))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="verify the video-grid runtime is installed: the setup.sh "
                     "baseline (deps, ffmpeg, filters, font, weights, demucs) and "
                     "whether the installed plugin matches this code (design "
                     "2026-08-01, 2026-09-25)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable report instead of the text table")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    report = run()
    print(json.dumps(report.to_dict(), indent=2) if a.json else report.to_text())
    raise SystemExit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
