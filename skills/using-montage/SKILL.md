---
name: using-montage
description: Router — the montage conveyor's front door. Turns a folder of raw footage + a natural-language brief ("a 9:16 reel from this trip, no music") into a delivered reel. Use when the user wants a reel from footage — the 1%-chance montage router. Verifies the runtime, then conducts every stage in order (project-init → footage-intake → contact-sheet → [reel-brief] → edit-plan → [music] → [pacing] → episodes-geometry → match-grade → [assemble-draft] → [titles] → edl_to_reel episodes → episode-qc → edl_to_reel deliver → reel-review), stopping only at the three checkpoints, resuming a half-finished run, and naming any stage it skips. Required — the entry point.
---

# using-montage (stage 5.1)

## Overview

You are the **conductor** of the montage conveyor. One invocation turns a footage
folder + a brief into a delivered `REEL_v1.mp4` — `<run>/reels/<reel>/deliveries/`
(see **The run directory**, below) — by running the stages that are already
built — you never re-implement a stage, and you never silently skip one. The
mechanical spans are CLIs; the judgment (what the brief means, which cut is right,
does the reel read) is yours and the sub-skills'.

**Core principle:** sequence, checkpoint, resume. Run built stages in order;
surface the three user gates (design §4.1); resume from wherever the run's
artifacts already reach; and when a stage is deferred/unbuilt, say so in one line
rather than pretending it ran.

## When to Use

Use at the **front** of a montage: raw clips exist and the user wants a reel. Not
for re-running a single stage — invoke that stage's own skill (`project-init`,
`footage-intake`, `edit-plan`, `process-episode`) directly. One `using-montage`
run covers the whole conveyor for one project/aspect.

## The Process

Announce on entry: **"Using using-montage to conduct footage -> reel."**

## The run directory

`<run>` is `<footage_root>/montage`. Inside it, **a folder is a lifetime** — how long
what is in it stays true:

    <run>/project.json  CONSTRAINTS.json      the project: canvas, delivery, standing rules
    <run>/footage/                            a function of the raw clips; survives every re-cut
    <run>/music/                              downloaded tracks, shared by every reel
    <run>/reels/<reel>/                       one editorial variant; <reel> is `main` by default
    <run>/reels/<reel>/episodes/              one render generation + its QC verdicts
    <run>/reels/<reel>/deliveries/            append-only — nothing ever deletes this
    <run>/reels/<reel>/build/                 wiped at the start of every render

Never compose these paths from memory. `montage status --run-dir <run> --reel <reel>`
returns each stage's resolved `path` alongside `next`, plus the whole `layout` block.
A file written anywhere else is not seen by the router, and the stage runs again.

A **second cut of the same footage** is a new `<reel>`, never a filename suffix: run
edit-plan with `--out-dir <run>/reels/upbeat` and the whole editorial layer forks while
`footage/` and `music/` stay shared. `MUSIC_A.json` / `pacing_B/` style names are what
this replaces.

**Never the footage folder itself, either** — a hazard distinct from the wrong
bucket above. The conveyor discovers footage by extension over a flat listing of
the footage root, so an artifact written there that happens to be a video becomes
source material on the next scan (`draft.mp4` did exactly this). `intake` and
`draft` refuse a path that resolves to the footage root outright; the refusal
names the remedy.

Point **every** stage's output at its own bucket in the layout above — never all
at `<run>` itself: `project_init --project-dir <run>`, `intake <footage_root>
<run>/footage`, `reel_brief build --project <run>/project.json --out-dir
<run>/reels/<reel>`, `edit_plan build --out-dir <run>/reels/<reel>`,
`edl_to_reel --work-dir <run>/reels/<reel>/build --out-dir <run>/reels/<reel>/episodes`.

0. **Verify the runtime (gate).** After resolving `$VG` (below), run
   `"$VG" scripts.verify_runtime`. Exit 0 → the `setup.sh` baseline is intact,
   proceed. Non-zero → surface each `BLOCKED` check with its remedy (almost always
   `bash setup.sh`) and **stop** — do not run project-init against a broken
   runtime, and never run `setup.sh` yourself. Advisory gaps (e.g. `reid`) are
   named, not blocking (they only affect optional lanes — without `reid` intake
   still produces windows, only cast identity is unavailable). `demucs` is **not**
   advisory: it blocks, because the music in/out-point has no fallback sensor.
   The venv and the recorded root are the
   pre-venv layer, checked by the launcher preamble and `bin/vg` before this runs.
   The dedicated `verify-runtime` skill runs the same check on demand.

   If `montage status` reports `"legacy_layout": true`, this run was written before the
   0.3.0 layout: its artifacts sit directly in `<run>`. **Ask the user** whether to point
   the conveyor at a fresh `<run>` (re-scanning every clip, hours on a 99-clip shoot) or
   to keep driving the old run by passing the old paths explicitly. Do not move the tree:
   `EPISODES.json` alone carries 57 absolute paths, and moving it breaks the QC digest
   bindings and the delivery attestation.

**Launcher.** Run every pipeline step through the repo's launcher `bin/vg`, never a
bare venv `python` binary. Resolve it once: `setup.sh` records the runtime's location
at `${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root`, so set
`VG="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")/bin/vg"` and run every
step as `"$VG" scripts.X`, passing **absolute** paths for every footage / run / output
directory. If that file is missing, the user has not run `bash setup.sh` — stop and
say so rather than guessing a path.

1. **Locate the run.** `"$VG" scripts.montage status --run-dir <run> --reel <reel>` prints
   the ordered stages, each with a `state`, plus the `next` stage. **Resume from
   `next`** — a stage whose artifact already exists is done; do not redo it. Read
   the brief and parse intent into params (table below).
   **A run from before the `montage/` convention** lives directly in the footage
   folder. If `<run>` is empty but `<footage_root>/project.json` exists, say so and
   ask which to use — starting fresh silently would re-scan every clip.

2. **project-init** — if `next`. `"$VG" scripts.project_init
   --purpose <p> --quality <q> --project-dir <run>` (custom aspect:
   `--purpose custom --canvas W:H`). **Checkpoint 1 — SPEC approval:** read back the
   resolved `{canvas, delivery}` and the intent you parsed; confirm before moving on.
   When reel-brief runs, its SPEC.md is the fuller CP1 artifact; without it, the
   resolved {canvas, delivery} is the CP1 surface.

   When the user states an editorial rule that must hold across re-cuts ("one hero
   opens, the other closes", "no repeated episodes", "don't use that take"), append it
   to `CONSTRAINTS.json` beside `project.json` before continuing — see the edit-plan
   SKILL for the four kinds. `edit_plan build` enforces it on every later cut without
   being told. A rule outside the four kinds cannot be stored: tell the user it will
   not be enforced instead of leaving them to assume it is.

3. **footage-intake** — if `next`. Invoke the **footage-intake** skill (it scans ->
   `FOOTAGE.json`/`FOOTAGE.md` and, when people matter, runs the interactive
   cast-naming -> `cast.json`). Point its out-dir at `<run>/footage`.

4. **contact-sheet** — if `next`. `"$VG" scripts.contact_sheet build
   --footage <run>/footage/FOOTAGE.json --footage-root <footage_root> --out-dir <run>/footage`
   (`<footage_root>` is the same raw-clips folder footage-intake scanned —
   `FOOTAGE.json`'s `source` is a bare filename, not a path, so the build needs
   the root to resolve it). Then **read every sheet it wrote** — `SHEETS.md`
   links them. This is the only point in the conveyor where you see the raw
   footage; every later stage works from your reading of it, so a skipped look
   is a guess propagated through the whole reel. The sheets do not replace
   `FOOTAGE.md` — the table carries the numbers, the sheets carry what the
   numbers cannot say. Read both, and offer the sheets to the user at CP1
   alongside the brief. **A run dir from before this stage existed** simply
   needs the build run once — `next` reports `contact-sheet` forever until
   `SHEETS.md` exists, even for a run already delivered and reviewed; running
   the command above resolves it, it is not a sign anything is wrong.

5. **reel-brief (optional).** If the brief deserves shaping (mood/hook/ending/
   style-lean beyond the bare aspect), invoke the **reel-brief** skill — it asks the
   idea one question at a time and writes `SPEC.md` + `SPEC.json` into `<run>/reels/<reel>`.
   `montage status` never points `next` here (it is optional); offer it proactively.
   **SPEC.md is CP1's richer artifact** — when it exists, it is what the user
   approves at Checkpoint 1 (the `edit-plan` agent then reads it as guidance). On a
   bare autonomous run, skip it and say so; `project.json` still anchors CP1.

6. **edit-plan** — if `next`. Invoke the **edit-plan** skill (it authors
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
   **Checkpoint 2 — EDL approval + curation:** show the user `EDL.md`. To swap
   or re-order an episode, edit `selection.json` and re-run the build — never
   hand-edit `EDL.json`.
   **`draft.mp4` is CP2's richer artifact** — when it exists (the optional
   assemble-draft step below), it is what the user approves at Checkpoint 2; on a
   run without it, `EDL.md` still anchors CP2. **Ask explicitly at this checkpoint
   (#6):** *"titles? effects (slow-mo / speed ramp, transitions, SFX)?"* — CP2 is
   the right place because the EDL now exists, so the reel length is known and a
   title can actually be timed. Name what you are skipping on "no" (e.g. "no
   titles — the reel will carry no on-screen text") rather than silently passing
   over the optional stages below.

   When the user states an editorial rule that must hold across re-cuts ("one hero
   opens, the other closes", "no repeated episodes", "don't use that take"), append it
   to `CONSTRAINTS.json` beside `project.json` before continuing — see the edit-plan
   SKILL for the four kinds. `edit_plan build` enforces it on every later cut without
   being told. A rule outside the four kinds cannot be stored: tell the user it will
   not be enforced instead of leaving them to assume it is. `EDL.json` already exists
   at this checkpoint, so writing the rule down does not by itself re-judge the cut
   already on disk — re-run `edit_plan build` (and on a paced run, `pacing` followed
   by `edit_plan build --pacing`) so the rule binds the cut that already exists, not
   only the next one.

   The scenario comes first and the music is fitted to it (design 2026-07-24). Run
   `edit_plan build` with NO `--pacing` to get the cuts at their material lengths, then
   `pacing`, then `edit_plan build --pacing` to apply the fit. Never re-time a shot to make
   a slot: a shot that IS the content — a ride, a trick — is not a slot's length.

7. **music-and-mood (optional).** The cuts already exist (step 6), so the reel's
   length is the sum of `EDL.json`'s episode durations — analyse the track against
   **that** length, not a SPEC target. Point music-source's fetch at the shared
   bucket — `--cache-dir <run>/music/cache` — whenever it runs below: the
   downloaded audio is a function of the *track*, not the cut, so it survives a
   second `--reel` variant instead of re-fetching (`music-match` only ranks a
   local folder already on disk, so it never downloads and never touches this
   bucket). If the brief names a **track**:
   - a **local file path** -> analyse it directly, preferring the tool's own
     in-point pick: `"$VG" scripts.beats <track> --auto-start
     --duration <reel_len> --out <run>/reels/<reel>/MUSIC.json` — it starts the reel on the
     strongest fragment, in a vocal pause. The pauses come from demucs (installed
     by `bash setup.sh`, and required — step 0 already blocked if it is missing);
     there is no proxy fallback. Pass an explicit `--start-offset S` instead only
     to override.
   - an explicit **track name** (not a path) -> skip discovery; invoke
     **music-source** with `--track "<name>"` to resolve and fetch it, then the
     same `beats --auto-start` locks it.
   If instead the brief has a **mood but no chosen track**:
   - the user has a **folder** of candidates (`music_mode == local`) -> invoke
     **music-match** first — it ranks the folder by mood into
     `MUSIC_SHORTLIST.md`, the user picks, and it runs the same
     `beats --auto-start`.
   - no local folder (`music_mode` is `free` or `any`) -> invoke
     **music-source** instead — it discovers and ranks candidates from the
     internet (`free` = CC catalogs; `any` is opt-in/copyright-gray — confirm
     with the user first) into the same shortlist shape, the user picks, and it
     downloads then runs `beats --auto-start`.
   Either way, `MUSIC.json` feeds **pacing** next (step 8), and the EDL references it
   (`selection.json`'s `music` field) for the audio mux. On "no music" / "без
   музыки", leave it unset — the reel is silent, pacing is skipped (a valid path).

8. **pacing (§5.6, optional).** When `MUSIC.json` exists, invoke the **pacing**
   skill — it **fits** the cuts `EDL.json` already holds onto the music's beat grid
   (`"$VG" scripts.pacing --edl <run>/reels/<reel>/EDL.json --footage <run>/footage/FOOTAGE.json
   --music <run>/reels/<reel>/MUSIC.json --out-dir <run>/reels/<reel>`) and writes `PACING.json` + `PACING.md`
   into `<run>/reels/<reel>`. Then **apply the fit** by re-running edit-plan with the report:
   `edit_plan build ... --pacing <run>/reels/<reel>/PACING.json [--spec <run>/reels/<reel>/SPEC.json]
   --music <run>/reels/<reel>/MUSIC.json` — carry `--spec` through when reel-brief (step 5) ran,
   same as step 6's first build. This second pass re-stamps `EDL.json` from scratch,
   so a dropped `--spec` silently re-resolves the variety preset to `balanced` and
   re-stamps that instead of the brief's mood. `--music` here does a SECOND job
   beyond feeding the beat grid: it fits the reel's *end* to a bar line
   (`lib/outro.fit_outro`, applied after this pass binds every slot) so the music
   resolves on a downbeat instead of stopping mid-phrase — read `EDL.md`'s **Music
   outro** section for which rung won (`gap`/`no-gap`/`unchanged`, detailed in the
   **edit-plan** skill's step 3). No `MUSIC.json` (a silent reel) -> skip this whole
   step (named); the EDL stays pacing-less (`beat_slot` unset) and its length is
   whatever the footage gives it. `montage status` never points `next` here (it is
   optional).

9. **episodes-geometry (required, design 2026-08-30 §2 — the geometry seam).**
   `edl_to_reel --stop-after-geometry` runs everything process-episode does
   short of the actual encode — extract, stabilize, track, gate — for every
   episode, then stops:

   ```bash
   "$VG" scripts.edl_to_reel <run>/reels/<reel>/EDL.json --project <run>/project.json \
     --footage-root <footage_root> --work-dir <run>/reels/<reel>/build \
     --out-dir <run>/reels/<reel>/episodes --stop-after-geometry
   ```

   Writes `<run>/reels/<reel>/episodes/GEOMETRY.json` — every episode's frozen
   route and the crop it will actually ship, colour block stripped. No
   `ep{i}.mp4` exists yet; no `--music`/`--titles` here either (both are
   refused — they belong to the render and the delivery, not this seam). This
   is the seam **match-grade** (next) measures the shipped crop in, instead of
   the whole source frame it read before 2026-08-30. A `stop_and_report` here
   (a tracker contradiction, a hero pin matching nobody) is the same
   mechanical gate that used to surface only after a full render — now caught
   one phase earlier, before a single pixel is encoded.

10. **match-grade (required, §10 — colour conductor).** Measures every
    episode's OWN tracked crop — not the whole source frame — and authors
    `tone_src`/`tone_dst` into whichever episodes deviate from the reel's one
    common target (the per-anchor median):

    ```bash
    "$VG" scripts.match_grade build --geometry <run>/reels/<reel>/episodes/GEOMETRY.json \
      [--spec <run>/reels/<reel>/SPEC.json] [--eps 4.0] [--force]
    ```

    rewriting the EDL `GEOMETRY.json` itself names IN PLACE plus a sibling
    `MATCH.md`. **Run it AFTER episodes-geometry (step 9)** — there is no crop
    to measure before a route is frozen. Unlike before 2026-08-30 this is
    unconditional: even a single-camera reel costs a few seconds (eight crops
    in about five seconds on a real reel) and writes a `MATCH.md` saying every
    episode already lands `within-eps` — cheaper than silently walking past
    the only stage that would have caught it NOT agreeing (the retro's R4.2).
    `montage status` now points `next` here like any other required stage.

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
    > gate and no signal in `report.json`, while `MATCH.md` survives on disk
    > and `montage status` still reads match-grade as done.
    > **Nothing is encoded until you stop.** See the **edit-plan** skill's
    > colour-grade section for the full loop and its footguns, and
    > `--from-geometry` (step 13) refuses a `GEOMETRY.json` whose cut no
    > longer matches the current EDL, naming `--stop-after-geometry` as the
    > remedy when the edit changed the CUT rather than only the colour.

11. **assemble-draft (optional, §5.9 — CP2 preview).** Before the expensive
    process-episode render, offer a rough draft: "Want to see a rough cut first?"
    If yes, `"$VG" scripts.draft build --edl <run>/reels/<reel>/EDL.json
    --project <run>/project.json --footage-root <footage_root> --work-dir <run>/reels/<reel>/build
    --out <run>/reels/<reel>/draft.mp4 [--music <run>/reels/<reel>/MUSIC.json]`. `draft.mp4` concats the raw
    segments, scale-fit into the canvas, with `processing_notes` labels and a rough
    music bed — the user eyeballs layout / order / length / beat-landing and
    approves (or goes back to edit-plan) at Checkpoint 2. This stage is optional:
    `montage status` never points `next` at it, and the autonomous path skips it.
    **The draft never shows the reel's look** (the vignette/bookend fade, §5.14
    below) — it is a QA preview of the cut, not the finish, so do not judge
    vignette strength or fade timing from it; there is nothing to see here yet.

12. **titles (optional, §5.16 — CP3 review).** If reel-brief ran (`SPEC.json`
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

13. **episodes (edl_to_reel, phase 1b — the render).**

    ```bash
    "$VG" scripts.edl_to_reel --from-geometry <run>/reels/<reel>/episodes/GEOMETRY.json \
      --project <run>/project.json --work-dir <run>/reels/<reel>/build \
      --out-dir <run>/reels/<reel>/episodes [--music <run>/reels/<reel>/MUSIC.json]
    ```

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

14. **episode-qc (required, not a checkpoint).** Invoke the **episode-qc**
    skill — it packs one evidence directory per episode from
    `<run>/reels/<reel>/episodes/EPISODES.json`, dispatches one fresh judge subagent per
    episode (at most 3 concurrently) against composition/colour/impression/
    path/hero, then validates their findings into `<run>/reels/<reel>/episodes/EPISODE_QC.json`
    + `.md`, stamping each verdict's clip digest itself. This stage is
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

15. **deliver (edl_to_reel, phase 2).**

    ```bash
    "$VG" scripts.edl_to_reel --from-episodes <run>/reels/<reel>/episodes/EPISODES.json \
      --work-dir <run>/reels/<reel>/build [--titles <run>/reels/<reel>/TITLES.json]
    ```

    No `--out-dir` here — phase 2 takes none and refuses one if given: it
    derives the delivery dir from `EPISODES.json`'s OWN path — the episodes
    directory's SIBLING `deliveries/` (`<run>/reels/<reel>/deliveries/`), never
    the episodes directory itself, so clearing the render scratch can never take
    a delivered reel with it (design 2026-08-25 §0) — so do not re-add the flag
    by analogy with phase 1.
    Gates on `<run>/reels/<reel>/episodes/EPISODE_QC.json` beside `EPISODES.json` (missing /
    incomplete / stale / blocking all refuse before a single ffmpeg call —
    episode-qc having just run should make this a formality, not a surprise),
    then runs assemble -> check_reel -> deliver. When `TITLES.json` is
    passed, `deliver` burns its drawtext chain into the ONE encode it already
    runs — no second pass; `deliver` also writes a `REEL_v{n}.attest.json`
    sidecar beside the encode (design 2026-08-04). The reel's **look** (a
    plateau vignette and/or a bookend fade — `EDL.look`, authored in
    `selection.json` at step 6 or defaulted from the mood preset) rides this
    SAME one encode, exactly like titles. Because `check_reel` runs on the
    assembled master *before* `deliver` applies either, the look is invisible
    in `draft.mp4` and in every check that ran before this point — Checkpoint
    3, right here, is the first place anyone actually sees it (design
    2026-08-13 §11.1).

    **`episode-qc-reprocessed` is a stop, not a warning.** Phase 2 refuses to deliver when `build_reel`'s retry loop
    re-rendered an episode AFTER episode-qc judged it (design 2026-08-18 §2):
    the reprocess overwrites the very `ep{i}.mp4` the verdict was stamped
    against, so that verdict is about bytes that are gone. The picture passed
    every check — the report comes back with the stop — and no version number
    was spent. The remedy, in order:

    1. `"$VG" scripts.episode_qc pack --episodes <run>/reels/<reel>/episodes/EPISODES.json
       --out-dir <run>/reels/<reel>/episodes/qc` — safe to re-run: it rewrites `strip.jpg` and
       `evidence.json` and never touches a judge's `findings.json`.
    2. Dispatch **one fresh judge for the named indices only**. The other
       episodes' verdicts are about bytes that did not change; re-judging them
       spends context for nothing.
    3. `"$VG" scripts.episode_qc build …` — unchanged; it re-digests every clip
       from disk, so the untouched verdicts stay valid and the re-judged one
       binds the new bytes.
    4. Re-run this step. The corrected clips are already on disk where
       `EPISODES.json` points, so `check_reel` finds the picture fixed, nothing
       reprocesses, and the reel delivers with an empty `reprocessed` list.

    **Do NOT re-run phase 1 to clear this stop.** The reason this was first
    written for — `build_reel`'s compounded per-channel colour factor living
    only in the clip bytes on disk (design 2026-08-18 §4.1) — is gone along
    with the colour retry loop itself (design 2026-08-29,
    colour-convergence-retire): there is no unpersisted correction left for a
    fresh phase 1 to discard. The instruction still holds, on a plainer
    ground: a fresh phase 1 (`--from-geometry`, or `--stop-after-episodes` on a
    hand-driven run) re-renders **every** episode, not only the one this stop
    names, so it pays the full
    N-episode render cost again and invalidates every OTHER episode's
    still-good QC verdict along with the stale one — exactly the waste the
    remedy above (steps 1-4, re-judge the named indices only) exists to avoid.
    Use that remedy; reach for phase 1 only when you are already re-cutting
    the EDL for other reasons.

    A delivered reel's `reprocessed` list is therefore always empty on this
    path; if one ever comes back non-empty, something bypassed the refusal —
    name it at Checkpoint 3 rather than passing over it.

    **`grade_faithful` is also a stop here, and its remedy is a re-render, not
    an EDL edit.** In the same phase, `check_reel`'s blocking `grade_faithful`
    check (design 2026-08-31 §2) can name one episode whose delivered pixels
    disagree with what its OWN declared colour chain predicts by more than
    `grade_residual_max` luma units. Its finding's `escalate_to` reads
    `process-episode`, not `match-grade` or `edit-plan`: the declaration is
    fine, the render did not get it, so the fix is re-rendering that episode —
    never touching its colour block, which would just be faithfully re-applied
    and fail the same way again. `edl_to_reel` has no flag that re-renders a
    single episode: `--from-geometry` (step 13) is the only render entry
    point, and it always renders every episode over the current
    `GEOMETRY.json`, which invalidates every episode's `EPISODE_QC.json`
    verdict, not only the named one's. Pay that cost — there is no cheaper
    mechanical path today (backlog) — rather than hand-editing `EPISODES.json`
    to splice in one clip, which is a generated artifact like any other:
    re-run `edl_to_reel --from-geometry` (step 13, the whole reel), then
    **episode-qc** (step 14, every episode — every digest just changed), then
    this step again.

    **Checkpoint 3 — final
    review:** present `<run>/reels/<reel>/deliveries/REEL_v1.mp4`, the `check_reel`
    report, and (when titles were authored) `TITLES.md` alongside them. Before
    presenting the reel as final, run
    `"$VG" scripts.montage verify --run-dir <run> --reel <reel>` and
    show its result — a delivery whose state is not `attested` (most notably
    `unattested`: no `REEL_v{n}.attest.json`, meaning the file did not come
    out of `deliver`) must be named plainly as such, never presented as a
    finished reel. Its `episode_qc` field needs the same treatment when it
    is not `judged` (`absent`: shipped via the single-command `edl_to_reel`
    or `build_reel`'s own CLI, neither of which this router uses; `stale`:
    judged, then an episode was re-rendered after its verdict — which on this
    path means something bypassed phase 2's own refusal above; `unknown`: an
    old sidecar predating the field) — a reel this router delivered itself
    should always read `judged`, so anything else means an unjudged reel is
    about to be called final and must be named plainly, not passed over. A `stop_and_report` (a failed gate) is surfaced verbatim —
    never fixed forward; route it to the culprit stage's skill.

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

    When the user states an editorial rule that must hold across re-cuts ("one hero
    opens, the other closes", "no repeated episodes", "don't use that take"), append it
    to `CONSTRAINTS.json` beside `project.json` before continuing — see the edit-plan
    SKILL for the four kinds. `edit_plan build` enforces it on every later cut without
    being told. A rule outside the four kinds cannot be stored: tell the user it will
    not be enforced instead of leaving them to assume it is. `EDL.json` already exists
    at this checkpoint, so writing the rule down does not by itself re-judge the cut
    already on disk — re-run `edit_plan build` (and on a paced run, `pacing` followed
    by `edit_plan build --pacing`) so the rule binds the cut that already exists, not
    only the next one.

## Reading the brief (intent -> param)

The user speaks free text; you pass **explicit args** — the user never types flags.

| Said | -> |
|------|----|
| "reel"/"shorts"/"9:16" · "youtube"/"16:9" · "square"/"1:1" · "cinema"/"21:9" | `project_init --purpose` |
| "4k" · "1080"/"social" · "native"/(unstated) | `project_init --quality` |
| a reel idea / mood / hook / ending / style-lean | reel-brief SKILL -> SPEC.md |
| a track path / "with music" | `beats ... --out <run>/reels/<reel>/MUSIC.json` -> edit-plan `music` |
| "no music" / "без музыки" | leave `MUSIC.json` unset (silent reel) |
| "classic" <-> "trend" | edit-plan editorial guidance |

Mixed/unstated intent (e.g. "a reel AND a youtube cut") -> ask; one project is one
aspect (project-init's own "ask, don't guess").

## Boundaries

- The **three checkpoints** (SPEC, EDL, final review) are the ONLY user-facing
  gates (§4.1); everything else is a machine gate inside the sub-stages. CP3's
  review has two mechanisms: check_reel (mechanical) and the reel-review skill
  (editorial, §5.13 Slice B).
- **episode-qc (step 14) is required but is not a checkpoint.** It sits
  between the per-episode render and delivery, judges every episode's OWN
  clip (never the assembled reel, never against another episode), and only
  interrupts the run on a blocking finding — a clean verdict passes through
  with no approval asked. There is no waiver (design §7): a blocking finding
  is fixed by re-running the finding's routed stage, never by lowering the
  gate or re-judging in place until it passes. The stage proves the
  artifact's presence and its digest binding to the exact rendered bytes —
  never that a judge truly looked (design §12); say so when you report a
  clean verdict.
- **Deferred stages are named, not skipped silently:** trend-scan (5.4) is not
  built; say so when you pass over it. reel-brief (`SPEC.md`, 5.3) is optional —
  offer it; on a bare run, name it as skipped. assemble-draft (`draft.mp4`, 5.9)
  is optional too — offer it before edl_to_reel; the autonomous path skips it
  without asking (no approval needed to skip a preview). titles (`TITLES.json`,
  5.16) is optional too — offer it once `SPEC.json` exists; the autonomous path
  skips it without asking (no on-screen text is a valid, complete reel). pacing
  (`PACING.md`, 5.6) is optional too — it runs automatically whenever
  `MUSIC.json` exists; a music-less reel skips it and edit-plan runs pacing-less
  (`beat_slot` stays unset). **episodes-geometry (`GEOMETRY.json`) and
  match-grade (`MATCH.md`, §10) are both required, since 2026-08-30** — not
  named here as skippable, unlike everything else in this bullet: the router
  runs match-grade on every reel, even a single-camera one, because it costs
  seconds and a stage nobody is told to run at the moment of need is a stage
  that gets rebuilt by hand instead (design §6, the retro's R4.2). A
  single-camera reel still pays for it; every episode simply comes back
  `within-eps` and `MATCH.md` says so — there is no "skip it" branch to name.
  reel-review (§5.13 editorial half)
  runs at CP3 after deliver; it is **required** — `montage status` points `next`
  at it until it runs, so the run is not finished on `delivered: true` alone — and
  still human-gated: the reviewer proposes, you dispose.
- You never re-implement a stage and never hand-edit a generated artifact
  (`EDL.json` regenerates from `selection.json`; `FOOTAGE.json`/`project.json` from
  their writers) — `TITLES.json` is the one deliberate exception (titles SKILL): it
  is the source of record for on-screen text (no upstream judgment file to
  regenerate from), and `Title`/`Titles` validate on load, so a bad hand-edit fails
  loud at `deliver`. `EDL.json` is additionally **stamped** (design 2026-08-04):
  `edl_to_reel` loads a hand-authored EDL exactly as before, but refuses one whose
  provenance digest no longer matches its own contents — never hand-edit a
  tool-generated `EDL.json`, even to fix a small thing; revise `selection.json` and
  re-run the build instead.
- **You may not disable, lower, or downgrade any quality gate.** A gate that
  blocks is routed back to its stage's skill, never loosened to pass. There is
  currently no CLI flag on any conveyor stage for loosening a reel-level check
  threshold — the last one, `--color-delta-max`, was retired with the check it
  bounded (design 2026-08-29, colour-convergence-retire) rather than kept as
  an escape hatch. If a `ReelCheckSpec` field is ever hand-loosened through a
  manifest, `provenance.spec_overrides` still records it, never silently, and
  shows it at CP3. `episode-qc` carries no override at all (§7) — not even a
  measured one.
- **Built, not obvious:** the cap-3 **parallel** episode fan-out landed
  2026-07-18 — `edl_to_reel` processes episodes across a bounded thread pool
  (`jobs`, default 3, the measured knee) inside its own loop; you never drive
  that fan-out yourself. Since the geometry seam (design 2026-08-30) split
  tracking out of rendering, you invoke `edl_to_reel` **three** times per run,
  not two — `--stop-after-geometry` (step 9) to stabilize, track and gate
  every episode with no encode, `--from-geometry` (step 13) to render over
  those frozen routes with the EDL's current colour block, then
  `--from-episodes` (step 15) to assemble and deliver — with **match-grade**
  (step 10) and the **episode-qc** skill (step 14) both required in between.
