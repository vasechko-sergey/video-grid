#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SKILL_DIR/.venv"
PYTHON="${PYTHON:-python3.13}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"   # corporate mirrors time out off-VPN

command -v "$PYTHON" >/dev/null || { echo "ERROR: $PYTHON not found -> brew install python@3.13 (or set PYTHON=...)"; exit 1; }
command -v ffmpeg >/dev/null || { echo "ERROR: ffmpeg not found -> brew install ffmpeg"; exit 1; }
ffmpeg -hide_banner -filters 2>/dev/null | grep -q vidstab || echo "WARNING: ffmpeg lacks vidstab filters (unused by core; needed for stabilization in process-episode) -> brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-libvidstab"

if [ ! -d "$VENV" ]; then
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -r "$SKILL_DIR/requirements.txt"
# YOLO weights cached into models/ on first track.py run (ultralytics auto-download by NAME)
mkdir -p "$SKILL_DIR/models"
echo "venv ready: $VENV ($("$VENV/bin/python" -V))"
