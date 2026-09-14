# reel-review — router stage 16

Then invoke the **reel-review** skill — it dispatches a fresh reviewer subagent
that judges the reel against `SPEC` (idea/mood/hook/ending/spine/colour) and writes
`REVIEW.json` + `REVIEW.md`; present `REVIEW.md` alongside the reel and the
`check_reel` report. For each finding the user chooses to act on, re-run the
routed stage (`edit-plan`/`pacing`/`music`/`titles`/`match-grade`) — never fix the reel
forward — then re-review the new cut. reel-review is **required**, not optional
(§5.13 editorial half, design 2026-08-04 §8) — the run is not finished when
`delivered` is `true`, only when `"$VG" scripts.montage status --run-dir <run> --reel <reel>`
reports `next: null`; on a bare autonomous run reel-review still runs, judging
against the `EDL`.
