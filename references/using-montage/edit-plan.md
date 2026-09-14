# edit-plan — router stage 6

Invoke the **edit-plan** skill (it authors
`selection.json`, runs `edit_plan build` -> `EDL.json` + `EDL.md`). Pass
`--spec <run>/reels/<reel>/SPEC.json` when reel-brief (step 5) ran — it carries two things:
the mood that picks the shot-mix preset the variety gate holds the cut to, and
`SPEC.platform`, which becomes `EDL.platform` and decides which safe-zone table
`check_reel` judges the subject against and where a bottom title sits. Without
it the build still runs, against the `balanced` preset and the generic zone.
Pass it again on the pacing re-apply (step 8) — that pass re-stamps the EDL from
scratch and would otherwise drop both. A `variety-gap` stop routes back to
**edit-plan** like any other `stop_and_report` — add the named shot size or
state a `variety_waiver` in `selection.json`, never a loosened gate. edit-plan
runs **before** music and pacing (steps 7-8): this first `edit_plan build`
carries **no `--pacing`**, so each cut keeps the length its footage gives it.

The scenario comes first and the music is fitted to it (design 2026-07-24). Run
`edit_plan build` with NO `--pacing` to get the cuts at their material lengths, then
`pacing`, then `edit_plan build --pacing` to apply the fit. Never re-time a shot to make
a slot: a shot that IS the content — a ride, a trick — is not a slot's length.
