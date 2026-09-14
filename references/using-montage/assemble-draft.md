# assemble-draft — router stage 11

**assemble-draft (optional, §5.9 — CP2 preview).** Before the expensive
process-episode render, offer a rough draft: "Want to see a rough cut first?"
If yes, `"$VG" scripts.draft build --edl <run>/reels/<reel>/EDL.json
--project <run>/project.json --footage-root <footage_root> --work-dir <run>/reels/<reel>/build
--out <run>/reels/<reel>/draft.mp4 [--music <run>/reels/<reel>/MUSIC.json]`. `draft.mp4` concats the raw
segments, scale-fit into the canvas, with `processing_notes` labels and a rough
music bed — the user eyeballs layout / order / length / beat-landing and
approves (or goes back to edit-plan) at Checkpoint 2. This stage is optional:
`montage status` never points `next` at it, and the autonomous path skips it
without asking (no approval needed to skip a preview).
**The draft never shows the reel's look** (the vignette/bookend fade, §5.14
below) — it is a QA preview of the cut, not the finish, so do not judge
vignette strength or fade timing from it; there is nothing to see here yet.
