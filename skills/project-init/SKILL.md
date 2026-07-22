---
name: project-init
description: Use ONCE at the very start of a montage project to learn what the video is for and set its aspect + delivery quality. Asks the purpose (reel / youtube / square / cinema / custom) and quality (native-best / social-1080 / 4K, or an explicit delivery spec), writes project.json; every episode then inherits canvas/delivery unless it overrides. Run before any episode processing.
---

# project-init

## Overview

You set the project's **canvas** (aspect) and **delivery** (output resolution) once, up front, by asking what the video is for. Every episode manifest then inherits these — the editor never re-specifies aspect per clip. The engine is aspect/resolution-agnostic; this is the front-door that chooses.

**Core principle:** learn the intent, don't assume it. Default delivery is **native** (the crop's own pixels — no downscale, best quality for TVs/large screens); a 1080 cap is a deliberate social choice, not the default.

## The Process

Announce on entry: **"Using project-init to set this project's aspect + delivery."**

1. Ask the **purpose** — "What's this video for?" — reel/shorts/tiktok (9:16), youtube/landscape (16:9), square/feed (1:1), cinema/wide (21:9), or **custom** (you give an explicit `W:H`).
2. Ask the **quality/delivery** — "How should it be delivered?" — **native** (default, best — source resolution, no loss), **social** (1080 cap, smaller file), **4k**, or a custom delivery spec.

**Launcher.** Run every pipeline step through the repo-root launcher `bin/vg`,
never a bare venv `python` binary. Resolve it once: this skill lives at
`<repo>/skills/project-init/`, so the launcher is two levels up. Set
`VG=<repo>/bin/vg` (an absolute path) and pass **absolute** paths for every
footage / run / output directory — `bin/vg` runs from the repo root, so a
relative artifact path would land inside the checkout. If `bin/vg` reports no
venv, the user has not run `bash setup.sh` yet.

3. Run the deterministic writer (never hand-write project.json):
   ```bash
   "$VG" scripts.project_init --purpose <p> --quality <q> --project-dir <dir>
   # custom aspect: --purpose custom --canvas 4:5 ; explicit: --delivery exact:1080x1920
   ```
4. Read back the resolved `{canvas, delivery}` from the printed `project.json` and confirm with the user before any episodes are processed.

## Ask, don't guess

If the purpose is genuinely mixed (e.g. "a reel AND a youtube cut") or the platform is unstated, ask — one project.json is one aspect. A per-episode override exists (an episode manifest may set its own `canvas`/`delivery`), but the project default should match the primary deliverable. Never pick an aspect the user didn't indicate.

## References

- The map + inheritance: `scripts/lib/project.py` (`resolve_project`, `resolve_manifest`).
- Delivery modes (native/short_edge/long_edge/exact): `scripts/lib/models.py` `Delivery`.
- How episodes consume it: `scripts/process_episode.py` `process_episode(project=)`.
