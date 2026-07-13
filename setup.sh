#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SKILL_DIR/.venv"
PYTHON="${PYTHON:-python3.13}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"   # corporate mirrors time out off-VPN

# --- system deps: install what's missing (brew), fail loud only when we can't ---
need_brew() {
  command -v brew >/dev/null || {
    echo "ERROR: '$1' is missing and homebrew is not installed -> install brew (https://brew.sh) or install '$1' manually"; exit 1; }
}

if ! command -v "$PYTHON" >/dev/null; then
  need_brew "$PYTHON"
  echo "installing python@3.13 via brew..."
  brew install python@3.13
fi
command -v "$PYTHON" >/dev/null || { echo "ERROR: $PYTHON still not found after install (set PYTHON=... to your 3.13 binary)"; exit 1; }

if ! command -v ffmpeg >/dev/null; then
  need_brew ffmpeg
  echo "installing ffmpeg via brew..."
  brew install ffmpeg
fi

# drawtext: the assemble-draft stage (§5.9) burns labels via drawtext, which needs
# libfreetype. Most homebrew ffmpeg builds carry it; some don't. The homebrew-ffmpeg
# tap full build has drawtext (and vidstab). Unlike vidstab this is a baseline
# requirement (the draft stage needs it), so ensure it by default — the branch only
# fires, and only replaces ffmpeg, when drawtext is genuinely missing.
if ! ffmpeg -hide_banner -filters 2>/dev/null | grep -q drawtext; then
  need_brew ffmpeg
  echo "ffmpeg lacks drawtext (needed for draft labels) -> installing drawtext-capable ffmpeg (homebrew-ffmpeg tap, replaces core ffmpeg)..."
  brew tap homebrew-ffmpeg/ffmpeg
  brew uninstall --ignore-dependencies ffmpeg 2>/dev/null || true
  brew install homebrew-ffmpeg/ffmpeg/ffmpeg
  ffmpeg -hide_banner -filters 2>/dev/null | grep -q drawtext || { echo "ERROR: drawtext still missing after tap install"; exit 1; }
fi

# vidstab: unused by core; required for stabilization in process-episode.
# homebrew-core ffmpeg ships WITHOUT libvidstab — the vidstab build comes from the
# homebrew-ffmpeg tap and REPLACES the ffmpeg formula, so it stays opt-in.
if ! ffmpeg -hide_banner -filters 2>/dev/null | grep -q vidstab; then
  if [ "${1:-}" = "--with-vidstab" ]; then
    need_brew ffmpeg
    echo "installing vidstab-enabled ffmpeg (homebrew-ffmpeg tap, replaces core ffmpeg)..."
    brew tap homebrew-ffmpeg/ffmpeg
    brew uninstall --ignore-dependencies ffmpeg 2>/dev/null || true
    brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-libvidstab
    ffmpeg -hide_banner -filters 2>/dev/null | grep -q vidstab || { echo "ERROR: vidstab still missing after tap install"; exit 1; }
  else
    echo "WARNING: ffmpeg lacks vidstab filters (unused by core; needed for stabilization in process-episode) -> rerun: bash setup.sh --with-vidstab"
  fi
fi

# --- venv + python deps ---
if [ ! -d "$VENV" ]; then
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -r "$SKILL_DIR/requirements.txt"
# YOLO weights cached into models/ on first track.py run (ultralytics auto-download by NAME)
mkdir -p "$SKILL_DIR/models"
echo "venv ready: $VENV ($("$VENV/bin/python" -V))"
