# titles — router stage 12

**titles (optional, §5.16 — CP3 review).** If reel-brief ran (`SPEC.json`
exists) and the reel wants on-screen text, invoke the **titles** skill — it
reads `SPEC.json`'s `hook`/`text`/`ending`, proposes timing/position/style/
font, and writes `TITLES.json` + `TITLES.md` into `<run>/reels/<reel>`. It needs the reel
length (`--total`); compute it here — sum `EDL.json`'s episode durations, or
probe `draft.mp4` if it exists; never guess it. `montage status` never points
`next` here; the autonomous path (no `SPEC.json`, or no on-screen text wanted)
skips it and says so. **`TITLES.md` is reviewed together with the near-final
reel at Checkpoint 3** — not standalone. When it exists, pass it to
`edl_to_reel`'s **deliver** invocation at step 15 (`--from-episodes ... --titles
<run>/reels/<reel>/TITLES.json`) so the reel actually renders the text — never to step 13's
`--from-geometry` invocation, which takes no titles parameter either and
refuses the combination outright (titles are burned into the ONE encode at
delivery, not the per-episode render).
