# match-grade — router stage 10

**match-grade (required, §10 — colour conductor).** Measures every
episode's OWN tracked crop — not the whole source frame — and authors
`tone_src`/`tone_dst` into whichever episodes deviate from the reel's one
common target (the per-anchor median):

```bash
"$VG" scripts.match_grade build --geometry <run>/reels/<reel>/episodes/GEOMETRY.json \
  [--spec <run>/reels/<reel>/SPEC.json] [--eps 4.0] [--force]
```

rewriting the EDL `GEOMETRY.json` itself names IN PLACE plus a sibling
`MATCH.json` — the decisions themselves, since 2026-09-09 the artifact
`montage status` keys this stage's `done` on, like every other stage —
and its rendered `MATCH.md`. **Run it AFTER episodes-geometry (step 9)**
— there is no crop to measure before a route is frozen. Unlike before
2026-08-30 this is unconditional: even a single-camera reel costs a few
seconds (eight crops in about five seconds on a real reel) and writes a
`MATCH.md` saying every episode already lands `within-eps` — cheaper than
silently walking past the only stage that would have caught it NOT
agreeing (the retro's R4.2). `montage status` now points `next` here like
any other required stage.

> **Before the render, look.** `probe grade --geometry
> <run>/reels/<reel>/episodes/GEOMETRY.json --index <N>` renders three
> crop-accurate frames of episode `<N>` with the grade `EDL.json`
> currently declares — no encode, no re-track, because nothing has been
> rendered yet. Edit `selection.json`, re-run `edit_plan build` (a pure
> projection that re-stamps `EDL.json` at the same path `GEOMETRY.json`
> names), **re-run `match_grade build --geometry ...` — always, not only
> when the edit should feed back into the common target** — then probe
> again. The re-run is not optional: `edit_plan build` projects the EDL
> from `selection.json` alone, so a rebuild drops **both** the per-episode
> `tone_src`/`tone_dst` match-grade authored **and `EDL.tone_target`**, and
> losing the target now makes the loss INVISIBLE rather than merely
> unblocked: `check_reel`'s blocking `grade_faithful` predicts each episode
> against its OWN declared chain, and with no pair declared it predicts an
> ungraded profile that the (now genuinely ungraded) render matches — a
> clean **pass**, not a visible `not-checked`. The advisory `target_dev`
> goes silently empty in the same stroke (it needs `EDL.tone_target` to
> compare against). So the reel ships ungraded with a green mechanical
> gate and no signal in `report.json` — but not silently past `montage
> status`: since 2026-09-09 it compares `MATCH.json`'s authored pairs
> against the EDL as it is NOW and reports match-grade **`stale`**, not
> `done`, naming the episode that lost its pair. That is a `status`/`next`
> signal only, not a render-time gate — check it before delivering.
> **Nothing is encoded until you stop.** See the **edit-plan** skill's
> colour-grade section for the full loop and its footguns, and
> `--from-geometry` (step 13) refuses a `GEOMETRY.json` whose cut no
> longer matches the current EDL, naming `--stop-after-geometry` as the
> remedy when the edit changed the CUT rather than only the colour.

**Required since 2026-08-30, with no "skip it" branch:** the router runs
match-grade on every reel, even a single-camera one, because it costs seconds
and a stage nobody is told to run at the moment of need is a stage that gets
rebuilt by hand instead (design §6, the retro's R4.2). A single-camera reel
still pays for it; every episode simply comes back `within-eps` and `MATCH.md`
says so — there is no "skip it" branch to name.
