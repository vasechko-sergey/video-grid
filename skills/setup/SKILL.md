---
name: setup
description: "Install — set up or update the runtime the video-grid skills drive: a Python venv, ffmpeg-full, the title fonts, demucs and the YOLO weights, kept outside the plugin so every installed version shares them. Asks before installing anything. Run it once after installing the plugin, and again when verify-runtime reports deps_stamp. Installs the runtime the other skills drive. Tool index: references/tools.md."
---

# setup

## Overview

The plugin carries the code; this skill installs what the code runs on, by running
the plugin's own `setup.sh`. Nothing lands inside the plugin's directory: the venv
and the YOLO weights go to `${XDG_DATA_HOME:-~/.local/share}/video-grid/`, the
recorded ffmpeg path and an optional Jamendo key to
`${XDG_CONFIG_HOME:-~/.config}/video-grid/`, so a plugin update — a new version
directory — finds them where it left them. Design:
`docs/specs/2026-10-21-install-without-clone-design.md`.

## When to Use

- Right after `/plugin install video-grid@video-grid`, before the first reel.
- When `bin/vg` says there is no runtime, or `verify-runtime` blocks on
  `deps_stamp` (a plugin update changed the dependencies) or on any check whose
  remedy is `bash setup.sh`.

Not for: checking the runtime (that is `verify-runtime`, read-only), or updating
the plugin itself (`claude plugin update video-grid@video-grid`, which the user
runs).

## The Process

Announce on entry: **"Using setup to install the video-grid runtime."**

**Launcher and references.** Run every pipeline step through the plugin's launcher
`bin/vg`, never a bare `python`, and resolve every `references/…` read the same
way. Claude Code writes this plugin's own directory into the line below when it
loads the skill, so resolve it once:

    ROOT="${CLAUDE_PLUGIN_ROOT}"
    VG="$ROOT/bin/vg"

If `ROOT` comes out empty — a harness that does not fill the line in — it is the
directory two levels above this skill's base directory. Then run every step as
`"$VG" scripts.X`, read every reference as `"$ROOT/references/…"`, and pass
**absolute** paths for every footage / run / output directory. Nothing here is
relative to your working directory — a skill runs from the user's footage
project. If `"$VG"` says there is no runtime, it has not been set up yet: run the
`setup` skill (`/video-grid:setup`), which asks before installing anything.

1. **Say what it installs, and ask.** Unless the user's own request was to install
   or set up the runtime, tell them first and wait for a yes:
   - Homebrew packages, only those missing: `python@3.13`, `ffmpeg-full` (installed
     beside any other ffmpeg, never replacing it, then pinned), and the title-font
     casks. Nothing is uninstalled or upgraded.
   - A Python venv in `~/.local/share/video-grid/venv` — about 2 GB with torch,
     demucs and torchreid — and the YOLO weights beside it.
   - The first run takes 10–20 minutes, mostly downloads. macOS with Homebrew only;
     without Homebrew the script says what to install by hand.

2. **Run it in the background.** `bash "$ROOT/setup.sh"` — background it, because a
   first install runs past a foreground command's time limit, and wait for it to
   finish. Never with `sudo`. If it stops with an error, quote its own last lines:
   each failure prints the step and the fix.

3. **Check.** Run `"$VG" scripts.verify_runtime` and report it the way the
   `verify-runtime` skill does. A clean run ends with "runtime ready".

## Boundaries

- Runs only the plugin's own `setup.sh`, only after the user agreed, and never
  edits it.
- Does not update the plugin. A failing `plugin` check is the user's
  `claude plugin update video-grid@video-grid` plus a restart.
- Installing Homebrew itself is the user's step (https://brew.sh): it asks for
  their password.
