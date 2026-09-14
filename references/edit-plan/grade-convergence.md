# edit-plan — converging a grade

**Converging a grade before anything is ever rendered (the normal case,
design 2026-08-30).** `edl_to_reel --stop-after-geometry` freezes every
episode's route into `<run>/reels/<reel>/episodes/GEOMETRY.json` — no
`ep{i}.mp4` exists yet, and **match-grade** (its own skill) already read
this same file to author a first tone pass. Edit the episode's colour
fields in **`selection.json`**, re-run this build (step 3 below — the SAME
command with the SAME flags the earlier build used), then probe the
freshly-written `EDL.json` straight through the frozen geometry:

    "$VG" scripts.probe grade --geometry <run>/reels/<reel>/episodes/GEOMETRY.json \
      --index <N>

No `--edl`: geometry mode always applies the EDL's CURRENT colour block,
read from the path `GEOMETRY.json` itself names, so a rebuild is picked up
on the very next probe with nothing else to pass. It writes the same
`probe.jpg`/`probe.json` pair described below, with one difference:
`probe.json`'s `drift_checked` reads `false`, because there is no rendered
file yet for the recomputed plan to be checked against — the plan itself
IS the source of truth before an encode. Loop (edit `selection.json`,
rebuild, probe) for as long as you like — **nothing is encoded** until
`edl_to_reel --from-geometry` runs. The one thing this mode refuses: a real
CUT change (a different window, source, or ramp) since the geometry was
frozen — `--from-geometry` catches that at render time and names
`--stop-after-geometry` as the remedy, because a moved cut needs a fresh
route, not just a fresh grade.

**Re-run `match_grade build --geometry ...` after every rebuild — always,
not only when the edit should feed back into the common target.**
`edit_plan build` projects the EDL from `selection.json` alone, so a
rebuild drops **both** the per-episode `tone_src`/`tone_dst` match-grade
authored **and `EDL.tone_target`** (measured: both come back `None`). The
pairs going means the reel is genuinely ungraded, and this is now
INVISIBLE to the mechanical gate rather than merely unblocked: `check_reel`'s
blocking `grade_faithful` predicts each episode against its OWN declared
chain — with no pair declared, it predicts an ungraded profile, the render
is genuinely ungraded too, the two agree, and the check reports a clean
**pass**. The advisory `target_dev` goes silently empty in the same stroke
(it needs `EDL.tone_target` to have anything to compare against), so
nothing in `report.json` flags the loss at all. `MATCH.md` does not
change — it still shows whatever it said before the rebuild — but since
2026-09-09 `montage status` compares `MATCH.json`'s authored pairs against
the EDL as it is NOW and reports match-grade **`stale`**, not `done`, the
moment a pair the report authored is gone (bound-reports design §2/§6).
That is a `status`/`next` signal only, not a render-time gate: it does not
stop `edl_to_reel --from-geometry` from rendering, so skip the re-run and
the reel still ships ungraded with a green mechanical gate unless you
check status first.

This is also simpler than the post-render path below: once satisfied,
`edl_to_reel --from-geometry` renders directly off the converged
`EDL.json` — no manual manifest patch, because nothing was ever rendered
with the stale grade in the first place.

**Converging a grade once episodes already exist — do not re-render a reel
to look at one episode.** This is the path once
`edl_to_reel --from-geometry` (or, driven by hand, `--stop-after-episodes`)
has actually written `<run>/reels/<reel>/episodes/EPISODES.json` — mid-loop
if you kept going past a render, or because **episode-qc** routed a
post-render colour finding back here. Edit the episode's colour fields in
**`selection.json`** — never `EDL.json` directly.
`EDL.json` is stamped (design 2026-08-04): `probe grade --edl` opens it through
the same `EDL.from_json` that refuses a file whose contents no longer match its
own stamp, so a hand-edited `EDL.json` is refused on the probe's very first
command, naming this exact remedy. Re-run the build (step 3 below, the SAME
command with the SAME flags the earlier build used — omitting `--pacing`/
`--music` here silently discards the pacing binding and the outro fit):

    "$VG" scripts.edit_plan build \
      --footage <run>/footage/FOOTAGE.json \
      --selection <run>/reels/<reel>/selection.json \
      --project <run>/project.json \
      --out-dir <run>/reels/<reel> \
      [--cast <run>/footage/cast.json] [--spec <run>/reels/<reel>/SPEC.json] \
      [--pacing <run>/reels/<reel>/PACING.json --music <run>/reels/<reel>/MUSIC.json]

— a pure projection, no ffmpeg, that re-stamps `EDL.json` — then probe the
freshly-written file:

    "$VG" scripts.probe grade --episodes <run>/reels/<reel>/episodes/EPISODES.json \
      --index <N> --edl <run>/reels/<reel>/EDL.json

It writes `<run>/reels/<reel>/build/ep<N>/probe/probe.jpg` (the frames) and `probe.json`
(naturalness flags plus `tone_profile`, ONE pooled `(p5, p50, p95)` triple
across all the probe's frames together — not a reading per frame — which
reads straight into a `tone_src`/`tone_dst` pair). Look at the pixels, edit
`selection.json`, rebuild, probe again. This `--episodes` mode's probe
**refuses** if the recomputed crop path differs from the
frozen one: that means something other than colour changed (a re-track, a
retry-adjusted `max_speed`/`smooth_window_s`, a different source file), and its
frames would not be the frames the next render ships.

**This loop is not free just because it skips ffmpeg.** Every rebuild re-runs
the variety gate and the `CONSTRAINTS.json` gate over the WHOLE cut, not only
the episode you touched — an unrelated pre-existing gap can surface
mid-convergence; it is not caused by the colour edit, so read the
`stop_and_report` and fix or waive it the normal way (step 2 above). And if
**match-grade** authored this episode's `tone_src`/`tone_dst` (it rewrites
`EDL.json` in place, bypassing `selection.json`), a rebuild from
`selection.json` does **not** carry that pair forward — the projection reads
`selection.json` only, so match-grade's result is silently gone from the new
`EDL.json` unless you copy the pair into `selection.json` yourself or re-run
**match-grade** again after converging. **`EDL.tone_target` goes with it**,
and that is the half that hides the first — more completely than before:
`check_reel`'s blocking `grade_faithful` predicts THIS episode against its
own (now empty) declared chain, the render is genuinely ungraded to match,
the two agree, and the gate reports a clean **pass**, not a visible
`not-checked`. The advisory `target_dev` — the one number that USED to hint
something was off — goes silently empty for the same reason (no
`EDL.tone_target` means nothing to compare it against). So an ungraded reel
passes the one gate that exists to catch it, with no signal anywhere in
`report.json` — though `montage status` now names it: the same
`stale`-on-a-wipe check above fires here too, since `selection.json`
dropping the pair reads identically to a rebuild dropping it. Re-running
**match-grade** after the last rebuild is still what closes it, every
time — not only when the edit should move the common target, and still the
only thing standing between a silently ungraded reel and delivery, since
`status` is something you have to go read.

Only when it converges is the full render worth paying for — and re-render
**that one episode**, never the reel, so the tracker never runs again. There is
no one-step command for this yet (backlog, `frame-probe-look-gate §11`):
materialize the converged manifest with the SAME `regrade` the probe used
internally — never hand-merge the colour block yourself; a plain merge keeps a
field the EDL edit just deleted (see `_COLOUR_KEYS` in `scripts/probe.py`) — and
write it back into **both** places that carry a copy, not only the scratch file:

    "$VG" -c "
    import json
    from scripts import probe
    ep_path = '<run>/reels/<reel>/episodes/EPISODES.json'
    rm = json.load(open(ep_path))
    regraded = probe.regrade(rm['episodes'][<N>]['manifest'], 'EDL.json', <N>)
    json.dump(regraded, open('<run>/reels/<reel>/build/ep<N>/manifest.json', 'w'), indent=2)
    rm['episodes'][<N>]['manifest'] = regraded
    json.dump(rm, open(ep_path, 'w'), indent=2)
    print('stabilize:', regraded.get('stabilize'), '  pan:', regraded.get('pan'))
    "

**`EPISODES.json`'s own copy is not optional** (final review I-4): a later
reel-level retry (`build_reel`, inside `deliver`) reprocesses a colour-culprit
episode from `rm.episodes[idx].manifest` — the entry INSIDE `EPISODES.json`,
never the scratch `<run>/reels/<reel>/build/ep<N>/manifest.json` above. Skip the second
`json.dump` and that retry silently re-renders this episode from the STALE
pre-convergence grade — no error, no trace. The alternative is re-running phase 1
(`edl_to_reel --from-geometry`, step 3's driver) from the re-stamped
`EDL.json`, which writes a fully consistent `EPISODES.json` too — but at the cost
of re-tracking and re-rendering EVERY episode, the whole expense this loop exists
to avoid; reach for it only when converging several episodes at once makes that
cost worth it.

This still leaves the run's eventual attestation stating a stale fact, and there
is no code fix for it here: `deliver` binds `REEL_v{n}.attest.json`'s `edl` block
to the digest phase 1 stamped when it first wrote `EPISODES.json`
(`rm.provenance["edl"]["digest"]`), and nothing re-reads that block after the
patch above — the shipped pixels came from the re-stamped `EDL.json`, but the
attestation still names the ORIGINAL one. Say so plainly if reel-review or the
user asks why the attested EDL digest does not match the file on disk; re-running
phase 1 (the alternative above) is the only way to make the attestation agree
with the pixels again.

Then pass the episode's frozen route so tracking is skipped — but only when
there IS a route to reuse. `process_episode` refuses `stabilize=true` combined
with a supplied `--route` (the frozen route was measured against pixels that no
longer exist once stabilize re-runs), and a `pan` episode never had a
`route.json` written for it at all (design 2026-07-19 §6.1) — passing `--route`
in either case is wrong, not merely redundant. Read the `stabilize`/`pan` line
the command above printed before choosing:

    "$VG" scripts.process_episode <run>/reels/<reel>/build/ep<N>/manifest.json \
      --project-dir <run>/reels/<reel>/build/ep<N> [--route <run>/reels/<reel>/build/ep<N>/route.json]

Omit `--route` entirely when `stabilize` or `pan` printed truthy — for
`stabilize` this pays for one re-track on the re-stabilized segment (still far
cheaper than a reel re-render); for `pan` there is nothing to track either way,
so the flag would do nothing even if the file existed. Keep it only when both
printed falsy, exactly as before.
