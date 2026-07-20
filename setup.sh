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
# upgrades what is already present; ffmpeg-full is pinned once installed, same reason.
export HOMEBREW_NO_AUTO_UPDATE=1

# scan all args so --with-demucs and --with-sourcing compose (order-independent)
WANT_DEMUCS=0; WANT_SOURCING=0
for arg in "$@"; do
  case "$arg" in
    --with-demucs)   WANT_DEMUCS=1 ;;
    --with-sourcing) WANT_SOURCING=1 ;;
  esac
done

# --- system deps: install what's missing (brew), fail loud only when we can't ---
# NOTE: macOS/homebrew only for now. On Linux/Windows install python3.13 + a
# drawtext-capable ffmpeg + a .ttf/.ttc font by hand (need_brew below degrades to a
# message). Cross-platform auto-install is a TODO — the runtime code is already
# portable (scripts/lib/fonts.py FONT_CANDIDATES carries Linux font paths too, and
# scripts/lib/ffbin.py falls through to PATH when config/ffmpeg.env is absent).
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

# --- ffmpeg: ONE build carrying every library the pipeline needs ---
# libfreetype for drawtext (§5.9 draft labels, §5.16 titles) and libvidstab for the
# shake measurement (§5.2 footage-intake). homebrew-core's ffmpeg-full is the SAME
# version and revision as core ffmpeg, so the build swaps while the source does not,
# and it is keg-only: it installs BESIDE core ffmpeg instead of replacing it.
#
# Nothing is ever uninstalled here. Two branches used to run
# `brew uninstall --ignore-dependencies ffmpeg` to get these filters back from a tap
# build; core ffmpeg has its own dependents (openai-whisper, summarize) against a
# --enable-shared build, so that left them linked to libraries that were gone. A
# keg-only formula makes the whole manoeuvre unnecessary, so the code for it is gone
# rather than guarded. Core ffmpeg is neither installed nor touched by this script.
#
# need_brew comes BEFORE the paths are built, not inside the install branch: the
# binaries are keg-only, so `brew --prefix` is the only thing that can name them.
# Deriving them from an absent brew yields "/opt/ffmpeg-full/bin/ffmpeg", a nonsense
# path that then fails the -x test for entirely the wrong reason.
need_brew ffmpeg-full
BREW_PREFIX="$(brew --prefix)"
FFMPEG_BIN="$BREW_PREFIX/opt/ffmpeg-full/bin/ffmpeg"
FFPROBE_BIN="$BREW_PREFIX/opt/ffmpeg-full/bin/ffprobe"
if [ ! -x "$FFMPEG_BIN" ]; then
  echo "installing ffmpeg-full (keg-only; drawtext + vidstab; core ffmpeg untouched)..."
  brew install ffmpeg-full
fi

# VERIFY, do not assume — and re-verify on every run, not just after an install.
# The formula's dependency list names freetype and libvidstab, which is evidence,
# not observation: the binary had not been inspected. A setup script that trusts its
# own success is exactly how the pin below sat broken and unnoticed.
[ -x "$FFMPEG_BIN" ]  || { echo "ERROR: $FFMPEG_BIN missing after install"; exit 1; }
[ -x "$FFPROBE_BIN" ] || { echo "ERROR: $FFPROBE_BIN missing after install"; exit 1; }
# Capture the filter list ONCE, then match in-shell. The obvious spelling —
# `"$FFMPEG_BIN" -filters | grep -q "$filt"` — is broken under `set -o pipefail`, and
# not intermittently: measured failing 40 runs out of 40. `grep -q` exits at its first
# match, ffmpeg still has ~20KB of a ~36KB filter list to write, so it takes SIGPIPE
# and exits 141, and pipefail promotes that to the pipeline's status. The check then
# reports "no drawtext" for a build that has drawtext. Both deleted branches above
# carried this bug, which is why their post-install verification could never once have
# passed — and why the drawtext branch fired its uninstall even where drawtext existed.
FILTERS="$("$FFMPEG_BIN" -hide_banner -filters 2>/dev/null)" || {
  echo "ERROR: $FFMPEG_BIN exists but will not run (\`-filters\` failed)"; exit 1; }
for filt in drawtext vidstabdetect; do
  case "$FILTERS" in
    *"$filt"*) ;;
    *) echo "ERROR: ffmpeg-full has no '$filt' filter — the install is not usable"; exit 1 ;;
  esac
done

# Record where it landed. keg-only means these binaries never reach PATH, so the
# path is the one thing the runtime cannot rediscover; scripts/lib/ffbin.py reads
# this file. The FILTERS are deliberately NOT recorded — a stale path fails loud,
# a stale capability record fails silently (design §4).
mkdir -p "$SKILL_DIR/config"
printf 'FFMPEG=%s\nFFPROBE=%s\n' "$FFMPEG_BIN" "$FFPROBE_BIN" > "$SKILL_DIR/config/ffmpeg.env"
echo "recorded config/ffmpeg.env -> $FFMPEG_BIN"

# Pin so a later `brew upgrade` cannot drift the version out from under the goldens —
# boxblur/drawtext behavior is version-sensitive (8.1.2 changed boxblur validation).
# NOT `2>/dev/null || true`: that idiom is why the pin these comments credited with
# protecting the goldens had never applied once. An already-pinned formula warns and
# exits 0, so a rerun stays a clean no-op, while a real failure now stops the script.
brew pin ffmpeg-full

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

# curated title fonts (§5.16): nice fonts for on-screen text, resolved by name
# (scripts/lib/fonts.py FONT_NAMES). brew cask fonts land in ~/Library/Fonts.
# Baseline rather than the old --with-fonts: four small casks, and without them the
# titles stage fails loud — which is precisely the "install a second thing later
# behind a flag" this script no longer asks for.
# macOS-only for now (same cross-platform TODO as the rest of this script).
need_brew "title fonts"
# guard each cask on already-installed (like the DejaVu block guards on outcome) so a
# rerun is a clean no-op — an unguarded `brew install --cask` on a present cask exits
# non-zero and, under `set -e`, would abort the whole setup.
for cask in font-montserrat font-inter font-bebas-neue font-oswald; do
  brew list --cask "$cask" >/dev/null 2>&1 || {
    echo "installing $cask -> ~/Library/Fonts..."; brew install --cask "$cask"; }
done

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
# music sourcing (§5.5 B3). Opt-in — installs yt-dlp (the `any` lane) and configures the
# free lane's OPTIONAL Jamendo key. The free lane works out of the box via ccMixter (no
# key), so this is capability, not a hard requirement. Guarded on already-installed so a
# rerun is a clean no-op (kept out of requirements.txt to keep the base install lean).
if [ "$WANT_SOURCING" = 1 ]; then
  "$VENV/bin/pip" show yt-dlp >/dev/null 2>&1 || {
    echo "installing yt-dlp (any-lane audio sourcing) into the venv..."
    "$VENV/bin/pip" install yt-dlp; }
  SRC_ENV="$SKILL_DIR/config/sourcing.env"
  if [ -z "${JAMENDO_CLIENT_ID:-}" ] && ! grep -qs '^JAMENDO_CLIENT_ID=' "$SRC_ENV" 2>/dev/null; then
    echo ""
    echo "Free-lane music source. Jamendo (richer CC catalog) needs a free client_id;"
    echo "without one the free lane uses ccMixter (no key)."
    echo "  [1] paste a Jamendo client_id   [2] open the devportal to create one   [3] use ccMixter"
    printf "choose [1/2/3] (default 3): "
    read -r choice || choice=3
    case "${choice:-3}" in
      1) printf "paste client_id: "; read -r cid
         mkdir -p "$SKILL_DIR/config"; echo "JAMENDO_CLIENT_ID=$cid" > "$SRC_ENV"
         echo "saved to config/sourcing.env (gitignored)" ;;
      2) echo "open https://devportal.jamendo.com/ , create an app, then re-run: bash setup.sh --with-sourcing"
         echo "(the free lane uses ccMixter until a key is configured)" ;;
      *) echo "using ccMixter (no key) for the free lane" ;;
    esac
  fi
fi
# YOLO weights cached into models/ on first track.py run (ultralytics auto-download by NAME)
mkdir -p "$SKILL_DIR/models"
echo "venv ready: $VENV ($("$VENV/bin/python" -V))"
