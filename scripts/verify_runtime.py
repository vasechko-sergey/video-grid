"""verify-runtime driver (design docs/specs/2026-08-01-verify-runtime-design.md).

Probes the setup.sh baseline contract and reports each gap with its remedy. The
IMPURE half — it imports the probed modules, resolves ffmpeg, spawns `-filters`
— so the report logic (scripts/lib/preflight.py) stays testable without an install.

Read-only: it PRINTS remedies, never runs setup.sh (§4). It runs INSIDE the venv
(via bin/vg), so it cannot report a missing venv or recorded-root — those are the
pre-venv layer (bin/vg + the skill preamble). See design §2/§5.

Imports are kept LIGHT on purpose: a broken heavy dep must be REPORTED by
_probe_deps, not crash this checker on import. models.MODELS pulls no numpy/cv2.
"""
import argparse
import importlib
import json
from pathlib import Path

from scripts.lib import ffbin, fonts, preflight
from scripts.lib.models import MODELS

# The runtime modules the pipeline imports = requirements.txt runtime set (pytest
# excluded, dev-only) + cv2 (a direct import of lib/flow.py; transitive via
# ultralytics). Import NAMES, not pip names (Pillow→PIL, yt-dlp→yt_dlp).
_DEPS = ("numpy", "scipy", "PIL", "cv2", "librosa", "ultralytics",
         "scenedetect", "imagehash", "yt_dlp", "requests")

_ROOT = Path(__file__).resolve().parent.parent   # repo root (bin/vg cd's here)


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


def _probe_ffmpeg() -> tuple[bool, str]:
    try:
        fb, fp = ffbin.ffmpeg(), ffbin.ffprobe()
    except ValueError:
        return False, "ffmpeg/ffprobe not on $FFMPEG, config/ffmpeg.env, or PATH"
    if not (Path(fb).exists() and Path(fp).exists()):
        return False, f"resolved path does not exist: {fb}"
    return True, fb


def _probe_filter(name: str) -> tuple[bool, str]:
    try:
        present = ffbin.has_filter(name)
    except (ValueError, RuntimeError):
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
        return False, "no usable font among fonts.FONT_CANDIDATES"


def _probe_weights() -> tuple[bool, str]:
    path = _ROOT / MODELS[0]
    if path.exists():
        return True, str(path)
    return False, f"missing at {path} (the first intake downloads it if online)"


def _probe_demucs() -> tuple[bool, str]:
    return (True, "installed") if _importable("demucs") else (False, "not installed")


_PROBES = {
    "deps": _probe_deps,
    "ffmpeg_bin": _probe_ffmpeg,
    "drawtext": _probe_drawtext,
    "vidstab": _probe_vidstab,
    "font": _probe_font,
    "weights": _probe_weights,
    "demucs": _probe_demucs,
}


def run() -> preflight.RuntimeReport:
    """Run every probe and evaluate the result. evaluate() enforces that _PROBES's
    keys match the registry — a probe/Check drift raises here, not silently."""
    raw = {key: probe() for key, probe in _PROBES.items()}
    return preflight.evaluate(raw)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="verify the video-grid runtime is installed (design 2026-08-01)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable report instead of the text table")
    a = ap.parse_args()
    report = run()
    print(json.dumps(report.to_dict(), indent=2) if a.json else report.to_text())
    raise SystemExit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
