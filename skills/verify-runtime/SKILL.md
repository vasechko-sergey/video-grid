---
name: verify-runtime
description: Check that the video-grid runtime is fully installed before (or independent of) a montage run. Use when a run just failed to start, after `bash setup.sh` or a plugin reinstall, or whenever you want to confirm the environment is whole. Reports each missing piece (deps, ffmpeg, drawtext/vidstab filters, font, YOLO weights; demucs advisory) with the exact command to fix it. Read-only — it never installs anything.
---

# verify-runtime

## Overview

Assert the `setup.sh` **baseline contract** is intact and print each gap's remedy.
Read-only: it names what to run, it never runs an installer. Design:
`docs/specs/2026-08-01-verify-runtime-design.md`.

## When to Use

A run would not start; right after `bash setup.sh` or a `/plugin` reinstall; or any
time you want to confirm the environment before conducting a montage.

## The Process

Announce on entry: **"Using verify-runtime to check the environment."**

1. **Resolve the runtime root (pre-venv layer).** Read the recorded root:
   `ROOT="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")"`. If that file
   is missing, the user has never run `bash setup.sh` — say exactly that and stop
   (there is no runtime to check yet).

2. **Run the check.** `"$ROOT/bin/vg" scripts.verify_runtime` (add `--json` when you
   want to parse it). `bin/vg` gates the venv itself: if it prints
   `no venv at … — run: bash …/setup.sh`, relay that and stop — that is the venv
   layer's own remedy.

3. **Report the result.**
   - **Exit 0 / "runtime ready":** say the runtime is ready.
   - **Exit non-zero:** list each `BLOCKED` required check with its remedy verbatim
     (almost always `bash setup.sh`). Tell the user to run it, then re-check. Do
     **not** run `setup.sh` yourself — installers are the user's to run.
   - **Optional (advisory) gaps** (e.g. `demucs`): mention them as "only needed for
     X", not as blockers.

## Boundaries

- **Read-only.** Never invoke `setup.sh` or any installer; print the remedy.
- **Cannot see the venv or the root record itself** — those are checked before it
  runs (the `cat` above and `bin/vg`). It reports everything *inside* the venv.
- Reports **all** capabilities, not what one brief needs; the caller decides
  relevance.
