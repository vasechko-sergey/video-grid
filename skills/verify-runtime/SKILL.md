---
name: verify-runtime
description: "Preflight — verify the video-grid runtime is fully installed and print the exact command to fix any gap: the installed plugin matching the code that runs it, deps and the requirements they were built from, ffmpeg, drawtext and vidstab filters, font, YOLO weights, demucs. Read-only, never installs. Required — step 0, before every stage. Tool index: references/tools.md."
---

# verify-runtime

## Overview

Assert the runtime contract is intact and print each gap's remedy. Two layers: the
`setup.sh` **baseline** (deps and the requirements the venv was built from, ffmpeg,
filters, font, weights, demucs) and the **installed plugin** — whether the skills
Claude Code loaded are the ones the running code expects. Read-only: it names what
to run, it never runs an installer. Designs:
`docs/specs/2026-08-01-verify-runtime-design.md`,
`docs/specs/2026-09-25-plugin-staleness-design.md`,
`docs/specs/2026-10-21-install-without-clone-design.md`.

## When to Use

A run would not start; right after `bash setup.sh` or a `/plugin` reinstall; or any
time you want to confirm the environment before conducting a montage.

## The Process

Announce on entry: **"Using verify-runtime to check the environment."**

**Launcher and references.** Run every pipeline step through the plugin's launcher
`bin/vg`, never a bare `python`, and resolve every `references/…` read the same
way. Claude Code writes this plugin's own directory into the line below when it
loads the skill, so resolve it once:

    ROOT="${CLAUDE_PLUGIN_ROOT}"
    VG="$ROOT/bin/vg"

If `ROOT` comes out empty, or `"$VG"` does not exist — a harness that did not fill
the line in — `ROOT` is the directory two levels above this skill's base directory.
Then run every step as
`"$VG" scripts.X`, read every reference as `"$ROOT/references/…"`, and pass
**absolute** paths for every footage / run / output directory. Nothing here is
relative to your working directory — a skill runs from the user's footage
project. If `"$VG"` says there is no runtime, it has not been set up yet: run the
`setup` skill (`/video-grid:setup`), which asks before installing anything.

1. **Run the check.** `"$VG" scripts.verify_runtime` (add `--json` when you want to
   parse it). `bin/vg` gates the venv itself: if it prints `no runtime at … — run
   /video-grid:setup`, the runtime has never been set up — say so and offer the
   `setup` skill; that is the venv layer's own remedy.

2. **Report the result.**
   - **Exit 0 / "runtime ready":** say the runtime is ready.
   - **Exit non-zero:** list each `BLOCKED` required check with its remedy. The
     remedy is already self-contained — it carries its own `cd <plugin dir> &&`, so
     it runs from **any** directory. Present it **verbatim in a ```bash block** (so
     the Run button works wherever the user's shell is), or offer the `setup` skill
     for a `bash setup.sh` remedy, then have them re-check. Do **not** run
     `setup.sh` from here — this skill is read-only; the `setup` skill asks first.
     A failing **`deps_stamp`** means the plugin was updated with new dependencies
     since setup last ran: the same remedy.
   - A failing **`plugin`** check is the one gap whose remedy is not `bash setup.sh`:
     the code running the check and the install record disagree about which
     version is installed — from a developer's clone, after `claude plugin update`
     in a session that loaded the old skills (restart), or with two install scopes
     at different versions. Relay `claude plugin update …` verbatim as above, and add that Claude
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
- **Cannot see the venv itself** — `bin/vg` checks it before this runs. It reports
  everything *inside* the venv.
- **Trusts the install record's shape**, which a third party (Claude Code) owns
  and versions — a future change to it could block every run with no clearable
  remedy, or pass silently, and only the `version` key is read today.
- Reports **all** capabilities, not what one brief needs; the caller decides
  relevance.
