# episodes — router stage 13

**episodes (edl_to_reel, phase 1b — the render).**

Renders every episode over the route **episodes-geometry** (step 9)
already froze, with `EDL.json`'s CURRENT colour block — the one
**match-grade** (step 10) and any convergence loop you ran last wrote. No
positional EDL and no `--footage-root`: the EDL is the one `GEOMETRY.json`
itself names, and nothing is extracted again (phase 1a already cut the
segments those routes were measured against — cutting them again would be
waste on top of a lie about which pixels were tracked). `--out-dir` must
be the SAME episodes dir `--stop-after-geometry` wrote into. Writes
`<run>/reels/<reel>/episodes/EPISODES.json` (a serialized `ReelManifest`)
beside the `ep{i}.mp4` clips it names — the same artifact
`--stop-after-episodes` used to write directly, before the geometry split;
do not fall back to that flag here, since a plain
`edl_to_reel`/`--stop-after-episodes` run on the same reel dirs wipes
`build/` and takes the frozen routes with it. It
**refuses** a cut that changed since the geometry was frozen (a moved
window, source or ramp) and a build dir that was wiped since — both name
the remedy (`--stop-after-geometry` again, or restore the EDL). A
`stop_and_report` here (an episode failed its own mechanical gate) is
surfaced verbatim — never fixed forward; route it to the culprit stage's
skill. **One reason names a genuine colour defect and must be recognised
by name: `grade-damage`** (`check_episode`'s `grade_damage`, blocking at
an entropy-ratio floor of 0.90 with no waiver anywhere) names edit-plan's
colour block as its culprit. Since 2026-09-02 this diagnosis is
trustworthy rather than a trap: `grade_damage` renders the episode's own
declared grade against an identity render of the SAME clip and fails only
when the declared map actually destroys information (an extreme
`black_point`/`highlight`, for instance) — never on a legitimate
**match-grade**-authored tone pair, which reads as movement, not damage.
So a `grade-damage` finding is not `match-grade`'s pair being
misdiagnosed; it means the named colour knob really is too aggressive —
soften it in the episode's colour block via **edit-plan**, the way any
other mechanical finding is fixed.
