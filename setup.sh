#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The venv lives OUTSIDE the repo so `/plugin install`'s cp -R does not copy 1.1 GB
# into the plugin cache; <repo>/.venv becomes a symlink to it (below), which keeps
# every `.venv/bin/python` path working. (design 2026-07-22 runtime-resolution §3)
VENV="${XDG_DATA_HOME:-$HOME/.local/share}/video-grid/venv"
PYTHON="${PYTHON:-python3.13}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"   # corporate mirrors time out off-VPN
# freeze brew version drift: a bare `brew install X` normally runs `brew update` first and
# can upgrade unrelated outdated formulae as a side effect (this bit us — an ad-hoc
# `brew install` silently bumped ffmpeg 8.1.1 -> 8.1.2, whose boxblur-validation change
# broke a golden). Disable auto-update so setup.sh installs only what is missing, never
# upgrades what is already present; ffmpeg-full is pinned once installed, same reason.
export HOMEBREW_NO_AUTO_UPDATE=1

# No opt-in flags: this script installs the WHOLE runtime. A capability the pipeline
# is meant to have must be present after one `bash setup.sh`, or a run silently
# degrades (a real run had no demucs, so its phrase-aware music in/out-point fell
# back to the coarse librosa proxy, unnoticed). Where a platform genuinely cannot
# provide something, the relevant block WARNS and continues — it never aborts the
# venv and never leaves a capability missing without a printed reason. (design
# 2026-08-04 setup-install-all)

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
# The whole ffmpeg-full section is brew-gated rather than brew-REQUIRING. Hoisting
# need_brew above the paths (correct — the binaries are keg-only, so `brew --prefix`
# is the only thing that can name them, and deriving them from an absent brew yields
# "/opt/ffmpeg-full/bin/ffmpeg", a nonsense path failing the -x test for the wrong
# reason) had a side effect: it made brew a hard requirement of a script that used to
# let a Linux box with a capable ffmpeg on PATH fall through and still build its venv.
#
# So: warn and continue instead of exiting. There is nothing to install and nothing to
# record without brew — ffbin's third rung falls through to PATH — and re-checking the
# filters here would duplicate what require_filter already does at runtime, with a
# remedy attached. The venv is worth more than a second copy of that check.
if ! command -v brew >/dev/null; then
  echo "WARNING: no homebrew -> skipping the ffmpeg-full install (macOS-only for now)."
  echo "  scripts/lib/ffbin.py falls through to PATH. Install an ffmpeg built with"
  echo "  libfreetype (drawtext) and libvidstab, or the draft/titles/intake stages"
  echo "  will fail loud at runtime with the filter they could not find."
else
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
fi

# drawtext also needs an actual font FILE, not just the filter — the two are
# decoupled (a build can carry the filter yet the box carry no font). macOS ships
# Arial/Helvetica system-wide, so this normally passes untouched; if a stripped box
# has none, INSTALL DejaVu (brew cask, lands in ~/Library/Fonts) rather than dead-end
# the user. Mirrors scripts/lib/fonts.py FONT_CANDIDATES. Linux fonts: TODO.
# The Linux entries are not aspirational: this list claimed to mirror FONT_CANDIDATES
# and did not, carrying only the four macOS paths while fonts.py carries six. On a
# Debian box with DejaVu installed the check therefore failed and fell into need_brew.
DRAWTEXT_FONTS=(
  /System/Library/Fonts/Supplemental/Arial.ttf
  /System/Library/Fonts/Helvetica.ttc
  /Library/Fonts/Arial.ttf
  "$HOME/Library/Fonts/DejaVuSans.ttf"
  /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
  /usr/share/fonts/dejavu/DejaVuSans.ttf
)
_have_font=0
for f in "${DRAWTEXT_FONTS[@]}"; do
  if [ -f "$f" ]; then _have_font=1; break; fi
done
if [ "$_have_font" -ne 1 ]; then
  if ! command -v brew >/dev/null; then
    # Third and last brew gate, for the same reason as the other two: without brew
    # there is nothing to install, and drawtext already fails loud at render with a
    # --font remedy. Blocking the venv here would leave a Linux user with no way to
    # run setup.sh at all, which would make gating the other two pointless.
    echo "WARNING: no drawtext font found and no homebrew -> install DejaVu via your"
    echo "  package manager, or pass --font PATH to 'draft.py build'."
  else
    echo "no drawtext font found -> installing DejaVu (brew cask font-dejavu -> ~/Library/Fonts)..."
    brew install --cask font-dejavu
    [ -f "$HOME/Library/Fonts/DejaVuSans.ttf" ] || { echo "ERROR: font still missing after install -> pass --font PATH to 'draft.py build'"; exit 1; }
  fi
fi

# curated title fonts (§5.16): nice fonts for on-screen text, resolved by name
# (scripts/lib/fonts.py FONT_NAMES). brew cask fonts land in ~/Library/Fonts.
# Baseline rather than the old --with-fonts: four small casks, and without them the
# titles stage fails loud — which is precisely the "install a second thing later
# behind a flag" this script no longer asks for.
# macOS-only for now (same cross-platform TODO as the rest of this script), and
# brew-GATED for the same reason the ffmpeg-full block above is: this need_brew used to
# sit inside `if [ "$WANT_FONTS" = 1 ]`, so it only ever fired for a user who had asked
# for fonts. Promoting the block to baseline without the gate would make brew a hard
# requirement a second time, and a missing title font already fails loud at render with
# its own remedy — it is not worth blocking a venv over.
if ! command -v brew >/dev/null; then
  echo "WARNING: no homebrew -> skipping the curated title fonts."
  echo "  naming one in TITLES.json will fail loud in deliver with the font it wanted."
else
# guard each cask on already-installed (like the DejaVu block guards on outcome) so a
# rerun is a clean no-op — an unguarded `brew install --cask` on a present cask exits
# non-zero and, under `set -e`, would abort the whole setup.
# font-noto-emoji: the monochrome icons a title's 📍/🗓 are drawn from when its own
# font lacks them (scripts/lib/fonts.py ICON_FONT, retro 2026-10-16 S13).
for cask in font-montserrat font-inter font-bebas-neue font-oswald font-noto-emoji; do
  brew list --cask "$cask" >/dev/null 2>&1 || {
    echo "installing $cask -> ~/Library/Fonts..."; brew install --cask "$cask"; }
done
fi

# --- venv (external; <repo>/.venv is a symlink to it) + python deps ---
mkdir -p "$(dirname "$VENV")"
if [ ! -d "$VENV" ]; then
  "$PYTHON" -m venv "$VENV"
fi
# Migrate a pre-existing in-repo real venv to the symlink layout, then link. `ln -sfn`
# replaces an existing symlink atomically; a real dir must be removed first (its 1.1 GB
# is exactly what we are moving out of the tree).
if [ -e "$SKILL_DIR/.venv" ] && [ ! -L "$SKILL_DIR/.venv" ]; then
  rm -rf "$SKILL_DIR/.venv"
fi
ln -sfn "$VENV" "$SKILL_DIR/.venv"
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -r "$SKILL_DIR/requirements.txt"
# demucs: vocal separation for phrase-aware music in/out-point (§5.5, backlog #2 —
# "разбиение по фразам"). REQUIRED since 2026-08-14 — there is no longer a fallback:
# the librosa mix-silence proxy that used to cover an absence was deleted for
# answering WRONG instead of failing (measured: 2 gaps in a 228s dense-pop track, so
# every in-point candidate collapsed to 0.0). preflight's demucs row is now a
# BLOCKING check, so a run cannot start without it.
#
# This block still CONTINUES on failure rather than aborting, and that is deliberate:
# `set -e` here would leave torchreid, the models dir and the recorded runtime root
# unconfigured, turning one missing wheel into a half-built install that is harder to
# diagnose. Installing is this script's job; GATING is verify_runtime's. Kept OUT of
# requirements.txt for the same reason — a failed torch wheel must not abort the whole
# `pip install -r` (and with it the venv). Guarded on already-installed so a rerun is
# a clean no-op; the `|| echo` also makes the compound exit 0, so `set -e` does not trip.
"$VENV/bin/python" -c 'import demucs' >/dev/null 2>&1 || {
  echo "installing demucs (vocal separation for phrase-aware music points; pulls torch)..."
  "$VENV/bin/pip" install demucs \
    || echo "ERROR: demucs install failed (no torch wheel for this platform?) -> demucs is REQUIRED and 'verify_runtime' will BLOCK every montage run until it is present. There is no proxy fallback. Re-run 'bash setup.sh' to retry."
  "$VENV/bin/python" -c 'import demucs' >/dev/null 2>&1 \
    || echo "ERROR: demucs INSTALLED BUT DOES NOT IMPORT — $("$VENV/bin/python" -c 'import demucs' 2>&1 | tail -1). demucs is REQUIRED; 'verify_runtime' will BLOCK. Usually a missing transitive dep: pip-install it and re-run 'bash setup.sh'."; }
# torchreid: person re-ID embeddings for cast identity (§6.1 / backlog #1). Baseline
# install, WARN-AND-CONTINUE (advisory, unlike demucs): pulls torch, can lack a wheel
# on some platforms. Kept OUT of requirements.txt so a failed wheel degrades HERE (cast
# surfacing unavailable; windows/scoring still run) instead of aborting the venv.
# OSNet weights download on the first reid.ensure_model() (like YOLO on first track).
#
# The explicit dep list is not decoration: torchreid 0.2.5 declares NO runtime
# requirements at all (only test/dev extras), yet imports seven packages. Measured
# 2026-08-14 on a real install — `pip install torchreid` reported success, `pip show`
# listed it, and `import torchreid` raised ModuleNotFoundError for gdown. The
# capability was missing with no printed reason, which is exactly what this script's
# header promises never happens. Guard and verify on IMPORT, never on `pip show`.
#
# tensorboard joined the list on 2026-08-19, from a second real install, and it is the
# one no scan of torchreid's OWN imports can find: engine.py says `from
# torch.utils.tensorboard import SummaryWriter`, so the root name torchreid imports is
# `torch` — present — and it is torch's submodule that needs the separate `tensorboard`
# distribution. Found by walking all 189 torchreid modules and importing each of their
# 63 external dotted names; tensorboard was the only genuine gap left.
"$VENV/bin/python" -c 'import torchreid' >/dev/null 2>&1 || {
  echo "installing torchreid (person re-ID for cast identity; pulls torch)..."
  "$VENV/bin/pip" install torchreid gdown tabulate Cython h5py imageio yacs tensorboard \
    || echo "WARNING: torchreid install failed (no torch wheel for this platform?) -> cast identity is unavailable; intake still produces windows & scoring. Re-run 'bash setup.sh' to retry."
  "$VENV/bin/python" -c 'import torchreid' >/dev/null 2>&1 \
    || echo "WARNING: torchreid INSTALLED BUT DOES NOT IMPORT — $("$VENV/bin/python" -c 'import torchreid' 2>&1 | tail -1). Cast identity is unavailable; intake still produces windows & scoring. pip-install the named module and re-run 'bash setup.sh'."; }
# music sourcing (§5.5 B3): yt-dlp (the `any` lane) now ships in requirements.txt, so
# there is nothing to install here. The `any`-lane legal/responsibility gate is
# UNTOUCHED — it lives in the sourcing code at USE time, not at install time; having the
# yt-dlp binary present does not invoke it. The free lane works out of the box via
# ccMixter (no key); Jamendo's richer CC catalog needs a free client_id, surfaced as a
# NON-BLOCKING notice (no interactive read, so a non-interactive/CI `bash setup.sh`
# never stalls). Add the key yourself when you want it.
SRC_ENV="$SKILL_DIR/config/sourcing.env"
if [ -z "${JAMENDO_CLIENT_ID:-}" ] && ! grep -qs '^JAMENDO_CLIENT_ID=' "$SRC_ENV" 2>/dev/null; then
  echo "note: the free music lane uses ccMixter (no key). For Jamendo's richer CC catalog,"
  echo "  add 'JAMENDO_CLIENT_ID=...' to config/sourcing.env (get one at https://devportal.jamendo.com/)."
fi
mkdir -p "$SKILL_DIR/models"
# YOLO segmentation weights. verify_runtime REQUIRES them at <clone>/yolo11n-seg.pt with
# `bash setup.sh` as the remedy, and using-montage stops at step 0 on a failed check —
# so they are fetched HERE, or a fresh clone's first run dead-ends on a remedy that
# cannot fix it. Ultralytics downloads a bare model name into the CURRENT directory, so
# the fetch runs from the clone root, and names the file the probe checks (MODELS[0]).
# OSNet and demucs weights still download on first use: neither is a required check.
(cd "$SKILL_DIR" && "$VENV/bin/python" -c 'from pathlib import Path
from scripts.lib.models import MODELS
from scripts import track
Path(MODELS[0]).exists() or (print("fetching YOLO weights " + MODELS[0] + "..."), track.ensure_model(MODELS[0]))') \
  || echo "WARNING: could not fetch the YOLO weights (offline?) -> verify_runtime will report them missing until 'bash setup.sh' is re-run online."
echo "venv ready: $VENV ($("$VENV/bin/python" -V))"

# Record where the runtime lives. Claude Code installs the montage skills by COPYING
# them into a runtime-less plugin cache, so a skill cannot find this checkout from its
# own (copied) location — it reads this file and runs <clone>/bin/vg. Outside the tree
# on purpose. (design 2026-07-22 runtime-resolution §2)
VG_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/video-grid"
mkdir -p "$VG_CONFIG"
printf '%s\n' "$SKILL_DIR" > "$VG_CONFIG/root"
echo "recorded runtime root -> $VG_CONFIG/root ($SKILL_DIR)"
