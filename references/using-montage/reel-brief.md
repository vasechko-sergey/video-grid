# reel-brief — router stage 5

**reel-brief (optional).** If the brief deserves shaping (mood/hook/ending/
shot length beyond the bare aspect), invoke the **reel-brief** skill — it asks the
idea one question at a time and writes `SPEC.md` + `SPEC.json` into `<run>/reels/<reel>`.
`montage status` never points `next` here (it is optional); offer it proactively.
**SPEC.md is CP1's richer artifact** — when it exists, it is what the user
approves at Checkpoint 1 (the `edit-plan` agent then reads it as guidance). On a
bare autonomous run, skip it and say so; `project.json` still anchors CP1.
