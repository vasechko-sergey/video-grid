---
name: verify-runtime
description: "Preflight — verify the video-grid runtime is fully installed and print the exact command to fix any gap: the installed plugin matching this clone, deps, ffmpeg, drawtext and vidstab filters, font, YOLO weights, demucs. Read-only, never installs. Required — step 0, before every stage. Tool index: references/tools.md."
---

# verify-runtime

## Overview

Assert the runtime contract is intact and print each gap's remedy. Two layers: the
`setup.sh` **baseline** (deps, ffmpeg, filters, font, weights, demucs) and the
**installed plugin** — whether the skills Claude Code loaded are the ones this
clone's code expects. Read-only: it names what to run, it never runs an installer.
Designs: `docs/specs/2026-08-01-verify-runtime-design.md`,
`docs/specs/2026-09-25-plugin-staleness-design.md`.

## When to Use

A run would not start; right after `bash setup.sh` or a `/plugin` reinstall; or any
time you want to confirm the environment before conducting a montage.

## The Process

Announce on entry: **"Using verify-runtime to check the environment."**

**Launcher and references.** Run every pipeline step through the repo's launcher
`bin/vg`, never a bare `python`, and resolve every `references/…` read the same
way. `setup.sh` records the runtime's location at
`${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root`, so resolve it once:

    ROOT="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")"
    VG="$ROOT/bin/vg"

Then run every step as `"$VG" scripts.X`, read every reference as
`"$ROOT/references/…"`, and pass **absolute** paths for every footage / run /
output directory. Nothing here is relative to your working directory — a skill
runs from the user's footage project, not from the clone. If that file is
missing, the user has not run `bash setup.sh` — stop and say so rather than
guessing a path.

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
   - **Exit non-zero:** list each `BLOCKED` required check with its remedy. The
     remedy is already self-contained — it carries its own `cd <clone> &&`, so it
     runs from **any** directory. Present it **verbatim in a ```bash block** (so the
     Run button works wherever the user's shell is), then have them re-check. Do
     **not** run `setup.sh` yourself — installers are the user's to run.
   - A failing **`plugin`** check is the one gap whose remedy is not `bash setup.sh`:
     the clone's code and the installed skills disagree about which version is
     running. Relay `claude plugin update …` verbatim as above, and add that Claude
     Code must be **restarted** afterwards — the update rewrites the cache, it does
     not reload the skills this session already has in context.
   - **Optional (advisory) gaps** (e.g. `reid`): mention them as "only needed for
     X", not as blockers. `demucs` is **not** one of these — it moved to required
     on 2026-08-14 and blocks like any other required check.

## Boundaries

- **Read-only.** Never invoke `setup.sh` or any installer; print the remedy.
- **Reports a version disagreement, never that the instructions are right.** A
  matching install of a skill set with a wrong sentence in it passes, and a clone
  edited without a version bump is invisible by design — the version is the
  install key.
- **Cannot see the venv or the root record itself** — those are checked before it
  runs (the `cat` above and `bin/vg`). It reports everything *inside* the venv.
- Reports **all** capabilities, not what one brief needs; the caller decides
  relevance.
