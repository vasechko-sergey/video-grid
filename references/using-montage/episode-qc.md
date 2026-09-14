# episode-qc — router stage 14

**episode-qc (required, not a checkpoint).** Invoke the **episode-qc**
skill — it packs one evidence directory per episode from
`<run>/reels/<reel>/episodes/EPISODES.json`, dispatches one fresh judge subagent per
episode (at most 3 concurrently) against composition/colour/impression/
path/hero, then validates their findings into `<run>/reels/<reel>/episodes/EPISODE_QC.json`
+ `.md`, stamping each verdict's clip digest itself. episode-qc
judges every episode's OWN clip (never the assembled reel, never
against another episode). This stage is
**required** — a reel is never assembled over an episode nobody judged —
but it is **not** one of the three §4.1 checkpoints: a clean verdict
passes straight through with no approval asked, and only a blocking
finding stops the run, here, with the routed finding surfaced (the same
`stop_and_report` shape every other stage stop already has). There is no
waiver — a blocking finding is fixed by re-running the finding's routed
stage (`reprocess` / `edit-plan` / `match-grade`), then episode-qc runs
again from its own step 1 (a re-render makes the old verdict stale).

When a blocking finding is on the **colour** axis, run the probe
convergence loop (**edit-plan** skill, colour-grade section) against
`EDL.json` before spending a re-render on it — look at the pixels, edit,
probe again, and only re-render the episode once it converges. `probe
grade`'s baseline is faithful to what was actually rendered **by
construction** (design 2026-08-29, colour-convergence-retire §3): there is
no reel-level colour correction left anywhere — not on `deliver`, not
inside `build_reel`'s retry loop — that could make a baseline stale, so the
same baseline is just as trustworthy on a SECOND pass through this step
(after step 15 already delivered once and named episodes in a
`reprocessed` list) as on the first. Separately: `deliver` (step 15)
hard-refuses a reel whose declared vignette/fade did
not reach the delivered pixels (design 2026-08-15 §7 — a declared titles
track has no pixel check yet, only a `not-checked` finding) — that failure
is a broken look chain (a filter silently dropped from the encode), never
something to retry as-is; fix `EDL.look` or the titles file and deliver
again.
