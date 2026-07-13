#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SKILL_DIR/.venv"
PYTHON="${PYTHON:-python3.13}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"   # corporate mirrors time out off-VPN
# freeze brew version drift: a bare `brew install X` normally runs `brew update` first and
# can upgrade unrelated outdated formulae as a side effect (this bit us — an ad-hoc
# `brew install` silently bumped ffmpeg 8.1.1 -> 8.1.2, whose boxblur-validation change
# broke a golden). Disable auto-update so setup.sh installs only what is missing, never
# upgrades what is already present; ffmpeg is pinned at the end for the same reason.
export HOMEBREW_NO_AUTO_UPDATE=1

# scan all args so --with-vidstab, --with-fonts and --with-demucs compose (order-independent)
WANT_VIDSTAB=0; WANT_FONTS=0; WANT_DEMUCS=0
for arg in "$@"; do
  case "$arg" in
    --with-vidstab) WANT_VIDSTAB=1 ;;
    --with-fonts)   WANT_FONTS=1 ;;
    --with-demucs)  WANT_DEMUCS=1 ;;
  esac
done

# --- system deps: install what's missing (brew), fail loud only when we can't ---
# NOTE: macOS/homebrew only for now. On Linux/Windows install python3.13 + a
# drawtext-capable ffmpeg + a .ttf/.ttc font by hand (need_brew below degrades to a
# message). Cross-platform auto-install is a TODO — the runtime code is already
# portable (scripts/lib/fonts.py FONT_CANDIDATES carries Linux font paths too).
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
  brew unpin ffmpeg 2>/dev/null || true          # a prior run may have pinned it (see end)
  brew uninstall --ignore-dependencies ffmpeg 2>/dev/null || true
  brew install homebrew-ffmpeg/ffmpeg/ffmpeg
  ffmpeg -hide_banner -filters 2>/dev/null | grep -q drawtext || { echo "ERROR: drawtext still missing after tap install"; exit 1; }
fi

# drawtext also needs an actual font FILE, not just the filter — the two are
# decoupled (a build can carry the filter yet the box carry no font). macOS ships
# Arial/Helvetica system-wide, so this normally passes untouched; if a stripped box
# has none, INSTALL DejaVu (brew cask, lands in ~/Library/Fonts) rather than dead-end
# the user. Mirrors scripts/lib/fonts.py FONT_CANDIDATES. Linux fonts: TODO.
DRAWTEXT_FONTS=(
  /System/Library/Fonts/Supplemental/Arial.ttf
  /System/Library/Fonts/Helvetica.ttc
  /Library/Fonts/Arial.ttf
  "$HOME/Library/Fonts/DejaVuSans.ttf"
)
_have_font=0
for f in "${DRAWTEXT_FONTS[@]}"; do
  if [ -f "$f" ]; then _have_font=1; break; fi
done
if [ "$_have_font" -ne 1 ]; then
  need_brew "DejaVu font"
  echo "no drawtext font found -> installing DejaVu (brew cask font-dejavu -> ~/Library/Fonts)..."
  brew install --cask font-dejavu
  [ -f "$HOME/Library/Fonts/DejaVuSans.ttf" ] || { echo "ERROR: font still missing after install -> pass --font PATH to 'draft.py build'"; exit 1; }
fi

# curated title fonts (§5.16): opt-in nice fonts for on-screen text, resolved by
# name (scripts/lib/fonts.py FONT_NAMES). brew cask fonts land in ~/Library/Fonts.
# macOS-only for now (same cross-platform TODO as the rest of this script).
if [ "$WANT_FONTS" = 1 ]; then
  need_brew "title fonts"
  # guard each cask on already-installed (like the vidstab/DejaVu blocks guard on
  # outcome) so a rerun is a clean no-op — an unguarded `brew install --cask` on a
  # present cask exits non-zero and, under `set -e`, would abort the whole setup.
  for cask in font-montserrat font-inter font-bebas-neue font-oswald; do
    brew list --cask "$cask" >/dev/null 2>&1 || {
      echo "installing $cask -> ~/Library/Fonts..."; brew install --cask "$cask"; }
  done
fi

# vidstab: unused by core; required for stabilization in process-episode.
# homebrew-core ffmpeg ships WITHOUT libvidstab — the vidstab build comes from the
# homebrew-ffmpeg tap and REPLACES the ffmpeg formula, so it stays opt-in.
if ! ffmpeg -hide_banner -filters 2>/dev/null | grep -q vidstab; then
  if [ "$WANT_VIDSTAB" = 1 ]; then
    need_brew ffmpeg
    echo "installing vidstab-enabled ffmpeg (homebrew-ffmpeg tap, replaces core ffmpeg)..."
    brew tap homebrew-ffmpeg/ffmpeg
    brew unpin ffmpeg 2>/dev/null || true          # a prior run may have pinned it (see end)
    brew uninstall --ignore-dependencies ffmpeg 2>/dev/null || true
    brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-libvidstab
    ffmpeg -hide_banner -filters 2>/dev/null | grep -q vidstab || { echo "ERROR: vidstab still missing after tap install"; exit 1; }
  else
    echo "WARNING: ffmpeg lacks vidstab filters (unused by core; needed for stabilization in process-episode) -> rerun: bash setup.sh --with-vidstab"
  fi
fi

# pin ffmpeg so a later `brew upgrade` cannot silently drift the version out from under
# the goldens — boxblur/drawtext behavior is version-sensitive (8.1.2 changed boxblur
# validation). Any deliberate tap-swap above unpins first, then this re-pins the result.
if command -v brew >/dev/null; then brew pin ffmpeg 2>/dev/null || true; fi

# --- venv + python deps ---
if [ ! -d "$VENV" ]; then
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -r "$SKILL_DIR/requirements.txt"
# demucs: vocal separation for start-offset intelligence (§5.5). Opt-in — pulls
# torch (large). Absent → choose_offset falls back to a librosa mix-silence proxy,
# so this is accuracy, not a hard requirement. Guarded on already-installed so a
# rerun is a clean no-op (kept out of requirements.txt to keep the base install lean).
if [ "$WANT_DEMUCS" = 1 ]; then
  "$VENV/bin/pip" show demucs >/dev/null 2>&1 || {
    echo "installing demucs (vocal separation; pulls torch) into the venv..."
    "$VENV/bin/pip" install demucs; }
fi
# YOLO weights cached into models/ on first track.py run (ultralytics auto-download by NAME)
mkdir -p "$SKILL_DIR/models"
echo "venv ready: $VENV ($("$VENV/bin/python" -V))"
