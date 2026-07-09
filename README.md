# video-grid

A skill set for editing one video reel out of a pile of raw footage — modeled on
superpowers (idea → spec → plan → draft → per-episode processing → checks), for any platform.

Status: core engine + autonomous single-episode driver built, now **resolution/aspect-agnostic** and driven by typed dataclass specs (no hardcoded 9:16 or 1080×1920 — delivery is `native`/`short_edge`/`long_edge`/`exact`). A project's aspect + delivery are set **once** up front via `project-init` (asks what the video is for → `project.json`), and every episode inherits them (or overrides per-episode). The engine (extract → YOLO/ByteTrack track → reframe → storyboard → numeric checks) is wrapped by `process_episode.py` + the `process-episode` skill, which run the §4.1 retry/escalation protocol for one episode. See [the design spec](docs/specs/2026-07-05-montage-skillset-design.md) and [the plans](docs/plans/).

Working in this repo? Start at the [CLAUDE.md](CLAUDE.md) registry — it maps to the
[coding standards](docs/coding-standards.md), [testing guide](docs/testing-guide.md),
[development workflow](docs/development-workflow.md), and [build status](docs/build-status.md).
