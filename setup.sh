#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SKILL_DIR/.venv"
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -r "$SKILL_DIR/requirements.txt"
mkdir -p "$SKILL_DIR/models"
# Optional heavy ML deps (real tracking): pass --ml to install ultralytics/torch.
if [ "${1:-}" = "--ml" ]; then
  "$VENV/bin/pip" install -r "$SKILL_DIR/requirements-ml.txt"
fi
echo "venv ready: $VENV"
