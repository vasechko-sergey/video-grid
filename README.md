# video-grid

A skill set for editing one video reel out of a pile of raw footage — modeled on
superpowers (idea → spec → plan → draft → per-episode processing → checks), for any platform.

Status: core engine + autonomous single-episode driver built. The engine (extract → YOLO/ByteTrack track → reframe to 9:16 → storyboard → numeric checks) is wrapped by `process_episode.py` + the `process-episode` skill, which run the §4.1 retry/escalation protocol for one episode. See [docs/2026-07-05-montage-skillset-design.md](docs/2026-07-05-montage-skillset-design.md) and [the plans](docs/plans/).
