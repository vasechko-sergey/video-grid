---
name: edit-plan
description: "Conveyor stage — author the cut: turn FOOTAGE.json's scored windows into EDL.json + EDL.md, the map edl_to_reel drives to a reel. Needs FOOTAGE.json and project.json. Required — its output drives the whole conveyor. Conveyor position: after reel-brief, before music-and-mood. Tool index: references/tools.md."
---

# edit-plan (stage 5.7)

Turn the scored candidate windows of `FOOTAGE.json` into an ordered **edit
decision list** — a map of which clip window plays when, with what composition,
layout, grid, and motion. This is the writing-plans of reels: **a map, not a
cut** — no ffmpeg here. The picture params you assign here are the process-episode
brief; the actual cutting and reframing happen downstream (5.8 → 5.10).

**Selection is your judgment.** intake (5.2) already scored, culled, and
`best`-marked the windows; your job is editorial — *which* best moments, in *what
order*, with *what* composition/layout/motion. You never retype a timestamp: you
reference a window by its clip source + index, and the code copies its start/dur
from `FOOTAGE.json`.

## Inputs

These do NOT sit in one directory. A run is organised by lifetime, so an input's
bucket says how long it stays true: `<run>/project.json` and `CONSTRAINTS.json` at
the run root, everything derived from the raw clips under `<run>/footage/`, and
everything editorial under `<run>/reels/<reel>/` — where `<reel>` is `main` unless
the user asked for a variant. Pass every path fully qualified; no working
directory resolves all three at once.

- **`FOOTAGE.json` + `FOOTAGE.md`** (required, from footage-intake) — the ranked
  candidate windows. Read `FOOTAGE.md` for the human view; the window **index**
  you reference is the 0-based position within that clip's window list.
- **`SHEETS.md` + `sheets/*.png`** (required, from contact-sheet) — one
  thumbnail per window, in timeline order. **Read every sheet before you
  select.** `shot_type` is bbox area and `description` is three generated
  tokens; neither can tell you whether a moment has a face, a laugh, or a
  story. The frames can.
- **`project.json`** (required, from project-init) — the canvas/delivery the
  episodes inherit; used by the preflight.
- **`references/editing-canon.md`** (required read) — thirds, headroom, lead room,
  the 180° rule, cut-on-action, contrast. Your editorial base.
- **`SPEC.md` / `SPEC.json`** (optional, from reel-brief) — its `mood` picks the
  shot-mix preset the variety gate (step 2) holds the cut to. Without one, the
  `balanced` preset applies — skipping the brief does not turn the gate off.
- **`PACING.md` / `MUSIC.json`** (optional) — read as guidance when present.
  Without `PACING.md`, leave `beat_slot` unset. Point `music` at a `MUSIC.json`
  when one exists.

`start_offset` (optional, per selection episode) moves the in-point later inside the SAME
shot — the window grid is a scoring artifact, not an editorial one. It never crosses a
scene cut and never changes `dur`. Use it to start on the first manoeuvre when the pacing
report says that lands a better ending.

A **span** merges adjacent windows into one episode: set `window` to a two-element
list `[i, j]` instead of a single index, and the episode runs from the start of
window `i` to the end of window `j`, carrying the footage between them. Use it when
consecutive windows are one arc — an approach into an action, or
"turn → drive → turn" — so the reel plays them as one continuous beat and the music
falls on the true length, instead of hard-cutting between windows that are one
motion. A span stays within **one clip**, its indices must be **adjacent**, and it
**cannot cross a scene cut** — the build refuses that, naming the cut (split into two
episodes there). `start_offset` still applies, moving the merged in-point later.

## Procedure

1. **Recon.** Read `FOOTAGE.md`, `project.json`, `references/editing-canon.md`, and
   any soft inputs present. Note the reel's target length (from `SPEC.md` or
   `project.json`, else propose one from the strongest windows).

   Read `SHEETS.md` and every sheet it links. When a window's exact in-point
   matters — the peak of a manoeuvre, the frame a person turns to camera —
   zoom in before deciding:

       python -m scripts.contact_sheet strip --footage <run>/footage/FOOTAGE.json \
         --footage-root <footage_root> --source MVI_3739.mp4 --window 2 \
         --frames 12 --out <run>/reels/<reel>/build/w2.png

   `--footage-root` is the same raw-clips folder footage-intake scanned —
   `FOOTAGE.json`'s `source` is a bare filename, not a path, so resolving a
   window into a decodable clip needs the root too. Each cell is labelled
   with its absolute timestamp; subtract the window's start to get the
   `start_offset` for that frame.

2. **Author `selection.json`.** Pick the best windows (they are already ranked).

   The ranking is not the answer. `score` is a **percentile within this shoot**
   (design 2026-08-06-intake-motion-scoring §4.2) — 0.9 means "ranks above 90% of
   the windows scanned here", never "is 90% good". It cannot be compared against
   another shoot's numbers, and it says nothing about whether the moment serves
   YOUR cut. `best` marks the top half that also survived phash dedup. Look at the
   contact sheets.

   **Variety is an objective, not a preference.** The build refuses a cut that uses
   *zero* of a shot size the mood's preset wants when the footage offers three or
   more windows of it — the reason is `variety-gap` and it names candidate windows
   by clip and index. Shot size is judged in the **delivered** frame, so a window
   tagged `wide` in `FOOTAGE.md` or on its `SHEETS.md` tile may well be `medium`
   once the 9:16 crop is taken; trust the refusal's numbers over the tag. The
   census reads a window's measured geometry directly, never an episode's
   `shot_type` label — relabelling an episode in `selection.json` cannot clear a
   gap. That geometry comes from a person detector, so a window with nobody in
   it reads as `wide` by construction; when that happens, `unmeasured`
   (printed beside `available` once non-zero) says how much of the census is
   the detector's silence, not evidence the footage lacks close-ups. If the
   cut is genuinely right as it stands — every close window is soft,
   or the reel is deliberately one texture — state why in `selection.json`:

       {"episodes": [...], "variety_waiver": "every close window is out of focus"}

   The reason is printed in `EDL.md` and stamped into `EDL.json`. A blank waiver is
   refused.

   **The reel's finish is `"look"`, a top-level key, not a per-episode one.**
   `{"vignette": 0.0-0.6, "fade": 0.0-2.0}` — corner darkening and a bookend fade
   in seconds, applied once over the whole reel at `deliver`, never per episode.
   Omit it and the mood's preset (`MoodPreset.look`, resolved from `SPEC.mood`
   the same way the variety gate resolves its shot-mix) decides — unless
   nothing matches: a skipped or mood-less brief leaves `EDL.look`
   **unauthored** (`None`), never filled from `balanced`'s own preset row,
   because filling it with any concrete value would itself be a taste nobody
   chose (a real fade) or a silent change to the audio bookend every reel has
   had since the music spine (see the next paragraph). Unauthored, `deliver`
   applies no vignette or fade and `mix` keeps its own 0.5s audio default — so
   an autonomous run with no brief looks exactly as it did before looks
   existed.

   Write `{}` or `{"vignette": 0, "fade": 0}` to mean *no look, and the preset
   does not get to override that* — but know this is **not** the same as
   omitting the key. An authored `{"vignette": 0, "fade": 0}` sets `EDL.look`
   to a real `LookSpec`, and `build_reel` then passes its `fade=0.0` to `mix`
   explicitly, switching OFF the 0.5s audio bookend every other reel keeps. An
   authored zero is a decision with an audible consequence, not the same
   no-op as leaving the key out — they render the same silent picture but not
   the same audio. A hand-picked `{"vignette": 0.4, "fade": 1.0}` overrides
   the preset the same way. `edit_plan build` logs which source won
   (`selection.json`, the `<mood>` preset, or "left unauthored" when nothing
   matched) on every run — read that line rather than assuming.

   Dedup across sources so one clip doesn't dominate, fit the running sum to the
   target length, and order them **hook first**. For each episode assign:
   - `composition` ∈ `lead` / `center` / `break` (required)
   - `grid` ∈ `thirds` / `phi` (required)
   - `layout` ∈ `fill` / `fit` / `insert` (default `fill`)
   - `background` ∈ `blur` / `solid` (default `blur`; `fill` accepts only `blur` —
     it covers the canvas edge to edge, so there is nothing else to fill) +
     optional `background_color` (an ffmpeg colour name or hex, default `black`,
     `solid` only)
   - `crop_aspect` (optional) — the crop rectangle's aspect, `"9:16"` or
     `[9, 16]`. Omit it and the manifest picks: the canvas for `fill`, the
     source's own aspect for `fit`/`insert`. Author it only to take a crop
     shaped like neither.
   - `crop_scale` (optional, default `1.0`) — the crop's size as a fraction of
     the largest one that fits. Below `1.0` tightens the framing and buys the
     tracker freedom to move within the source. A **still** choice, unlike
     `zoom`, which changes the crop's width over time.
   - `border_px` / `border_color` (optional, `insert` only, default `0` /
     `white`) — the card's border in delivered pixels and its colour. `0` draws
     none.
   - `motion` ∈ `lateral:right` / `lateral:left` / `head-on` / `static` (optional)
   - `hero` (optional) — a first-frame seed bbox `[x,y,w,h]` (centre-format,
     source px), a rule (`largest`/`leftmost`), an integer track id, or a cast
     name resolved through `cast.json` (§6.1a). A cast name needs the registry:
     pass `--cast` (step 3) and the name must exist in `cast.json` — an
     unresolvable name is a preflight `edl-invalid` (fix `selection.json` and
     re-run), and a pin that matches nobody in the episode's segment is a
     `hero-unmatched` stop-and-report at process-episode time — never a silent
     fallback to intent scoring.
   - `zoom` (optional) — `{"from": 1.0, "to": 0.7}`, a **subject-anchored**
     push-in/pull-out: two fractions of the layout's crop WIDTH (`1.0` the
     whole crop, `0.7` a 1.43x push-in; direction is the sign of `to - from`,
     same convention as `pan`). Unlike `pan` it does NOT replace the tracked
     route — the rect's position still comes from the SAME composition rule
     as any tracked episode, only its width shrinks or grows, which is what
     keeps every `check_episode` check (framing/continuity/`grade_damage`)
     applying to it in full, exactly as it does to a still crop. It therefore
     **needs a tracked subject** — there is no route to ride without one —
     and `zoom` together with `pan` on one episode is refused (one anchors to
     a subject, the other declares there is none). Both fractions must be in
     `(0, 1]`; a push-in tightened past `ZOOM_MAX_UPSCALE` (1.5x, an
     unresolved-upsample ceiling) or faster than `ZOOM_MAX_RATE` (0.5
     crop-widths/second, a whip-zoom guard) is refused, not silently clamped.
   - `pan` (optional) — `{"from": f, "to": f}`, a **generated** constant-velocity
     camera move: two fractions of the crop's horizontal freedom (`0.0` hard
     left, `1.0` hard right; direction is the sign of `to - from`). It replaces
     tracked motion for the episode — no route is read, no hero is followed.
     May be authored **only over a window `FOOTAGE.md`/`SHEETS.md` show as
     empty of people** — intake's own measured `present` fraction, not your
     read of the frame. `edit_plan build` refuses a `pan` over a window
     holding people (`FootageWindow.present` above `PAN_PRESENCE_MAX`, 10% of
     samples): a route-less move turns off framing/continuity/`grade_damage`,
     which is only legitimate for a shot with no subject to check in the
     first place — not an editorial choice `pan` gets to make on your word.
     The gate enforces two further constraints: `composition` must be
     `center` (a pan positions the crop by its own law, so `lead`/`break`'s
     subject-relative framing has nothing to consult — a preflight
     `edl-invalid` names the conflict), and no `hero` pin may be set alongside
     it (the pin says "follow this person", the pan says "follow nobody").
     `motion` may still be set — it describes the *subject*, the pan describes
     the *camera*, and the canonical pan is `motion: static` with a moving
     frame, both at once.
   - `ramp` (optional) — `{"at": 2.0, "factor": 0.4, "ease": 0.5, "hold": 1.0}`,
     a **speed ramp**: playback eases down to a slow plateau around one moment
     and back up — the "hit the drop in slow-mo" move, not a whole-shot
     slowdown. All four numbers are seconds (or a plain multiplier) measured
     from the **window's own start**, never the clip's: `at` is the plateau's
     centre, `factor` is the minimum speed as a literal multiplier (`0.4`
     means 2.5x slower, not "40% speed"), `ease` is the cosine ramp-in/
     ramp-out length each side, and `hold` is the plateau's own length at
     `factor`. The region `[at − hold/2 − ease, at + hold/2 + ease]` must sit
     entirely inside the window — a ramp that pokes past either edge is
     refused, naming the overhang, not clamped. The slowest legal `factor` is
     capped by `MIN_RAMP_FPS = 24.0`: slowing DUPLICATES frames rather than
     creating them, so a plateau below 24 unique frames per second reads as
     stutter — the floor is `24 / clip fps`, i.e. `0.4` on 60 fps footage but
     only `0.8` on 30 fps (`FOOTAGE.md` prints each clip's rate; a deeper
     ramp needs higher-fps footage, not a lower floor). **Author the ramp
     before running pacing** — the beat grid is fitted to each episode's
     PLAYED length, and a ramp added afterwards makes the binding guard
     refuse, naming the pacing re-run as the fix. A ramped episode therefore
     plays longer than its window; `EDL.md` shows both numbers on its row. The
     segment loses its audio entirely (slowed sound is pitch garbage) — say so
     in `processing_notes` when the shot had nat sound worth keeping, and
     weigh leaving it unramped instead.
   - `processing_notes` — a short note for the draft labels (optional)
   - **colour** (all optional, per episode; every episode carries an identity-default
     grade, so omit these unless a clip needs correcting): `white_balance` ∈ `[0, 1]`
     neutralizes a cast first (grey-world; `0` = off); `black_point` ∈ `[0, 0.35]`
     lifts a washed toe; `highlight` ∈ `[0.6, 1.0]` tames blown whites; `saturation`
     ∈ `[0.5, 1.5]` scales chroma; `shadow_red` ∈ `[0, 0.20]` neutralizes a green/cyan
     black; `highlight_red` ∈ `[0, 0.35]` pulls only the red **shoulder** down — de-pinks
     specular foam/spray carrying a bright red object's reflection, leaving everything
     below the 0.60 knee (water, skin, the object itself) alone; `mid_blue` ∈
     `[0.80, 1.20]` fixes sky-bounce on skin; `dip` ∈ `[0, 0.5]`s
     fades the episode in/out to dark grey. `tone` matches a clip's tonal profile to
     the reel: set `tone_src` to that clip's measured `[p5, p50, p95]` luma and
     `tone_dst` to the reel's common target. **You will rarely author this pair by
     hand**: **match-grade** authors it for every episode from the tracked CROP, and
     that is the reading the reel is judged against (`check_reel`'s blocking
     `grade_faithful`, which predicts from your FULL declared chain, not the
     bare tone pair — a post-tone knob moves the prediction and the delivery
     together and cancels). If you do author one, read `tone_src` off the crop — `probe grade
     --geometry ... --index N` prints `tone_profile`, ONE pooled `(p5, p50, p95)` of
     the pixels that ship. `python -m scripts.color_measure <clip>` measures a WHOLE
     source frame instead, which on real footage differs from the crop by a median of
     14 and a maximum of 36 luma units — useful for a quick look at a file, wrong as
     the source anchor of a pair. A banding `tone` curve fails loud at render
     (`verify_tone`), so trust the error and widen the anchors.
   - `color_means` (optional) — the target channel means `[r, g, b]` that
     `check_episode`'s colour check measures the DELIVERED clip against. Not a
     grade: it changes what "correct" means, never how a pixel looks. Leave it
     at its default unless a shot must match a specific reference — reach for
     the grade knobs above to change how a clip looks, and for `tone_src`/
     `tone_dst` to make several clips agree.

   **Every knob, in one place.** The prose above is the explanation — it carries
   the refusals and the reasons, and it is what you read before authoring. This
   is the index into it. Anything absent from this table is not authorable from
   `selection.json`.

   | knob | what it sets |
   |---|---|
   | `source` / `start` / `dur` | which clip, from where, for how long |
   | `base_dur` | the footage-projected length, recorded once at projection — never author it |
   | `shot_type` | the label; the variety gate measures delivered geometry, not this |
   | `composition` / `grid` | `lead`/`center`/`break` × `thirds`/`phi` |
   | `layout` | `fill` / `fit` / `insert` |
   | `background` / `background_color` | the filler behind a `fit`/`insert` frame |
   | `crop_aspect` / `crop_scale` | the crop rectangle's shape and its size |
   | `border_px` / `border_color` | the `insert` card's border |
   | `motion` | the SUBJECT's travel, for intent scoring |
   | `hero` | who to follow — bbox, rule, track id, or cast name |
   | `pan` | a generated camera move; refused over a window holding people |
   | `zoom` | a subject-anchored push-in/pull-out along the tracked route |
   | `ramp` | a speed ramp down to a slow plateau and back |
   | `stabilize` | the vidstab pre-stage; never on a wade-in/out shot |
   | `smooth_window_s` | seconds of path smoothing |
   | `white_balance` · `black_point` · `highlight` · `highlight_red` · `shadow_red` · `mid_blue` · `saturation` · `dip` | the colour grade, applied in that order |
   | `tone_src` / `tone_dst` | the match-grade pair; `match_grade` authors these |
   | `color_means` | the colour CHECK's reference means, not a grade |
   | `processing_notes` | free text, rendered into `EDL.md` and the draft's labels |
   | `beat_slot` | which grid line the cut lands on; `--pacing` writes it |

   Two keys are **reel-level** and sit beside `episodes`, never inside one:
   `look` and `variety_waiver`.

   **Converging a grade before anything is ever rendered (the normal case,
   design 2026-08-30).** `edl_to_reel --stop-after-geometry` freezes every
   episode's route into `<run>/reels/<reel>/episodes/GEOMETRY.json` — no
   `ep{i}.mp4` exists yet, and **match-grade** (its own skill) already read
   this same file to author a first tone pass. Edit the episode's colour
   fields in **`selection.json`**, re-run this build (step 3 below — the SAME
   command with the SAME flags the earlier build used), then probe the
   freshly-written `EDL.json` straight through the frozen geometry:

       python -m scripts.probe grade --geometry <run>/reels/<reel>/episodes/GEOMETRY.json \
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

       python -m scripts.edit_plan build \
         --footage <run>/footage/FOOTAGE.json \
         --selection <run>/reels/<reel>/selection.json \
         --project <run>/project.json \
         --out-dir <run>/reels/<reel> \
         [--cast <run>/footage/cast.json] [--spec <run>/reels/<reel>/SPEC.json] \
         [--pacing <run>/reels/<reel>/PACING.json --music <run>/reels/<reel>/MUSIC.json]

   — a pure projection, no ffmpeg, that re-stamps `EDL.json` — then probe the
   freshly-written file:

       python -m scripts.probe grade --episodes <run>/reels/<reel>/episodes/EPISODES.json \
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

       python -c "
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

       python -m scripts.process_episode <run>/reels/<reel>/build/ep<N>/manifest.json \
         --project-dir <run>/reels/<reel>/build/ep<N> [--route <run>/reels/<reel>/build/ep<N>/route.json]

   Omit `--route` entirely when `stabilize` or `pan` printed truthy — for
   `stabilize` this pays for one re-track on the re-stabilized segment (still far
   cheaper than a reel re-render); for `pan` there is nothing to track either way,
   so the flag would do nothing even if the file existed. Keep it only when both
   printed falsy, exactly as before.

   The shape (integer window indices — or a `[i, j]` span — + editorial only, no timestamps):

       {
         "episodes": [
           {"source": "MVI_3739.mp4", "window": 2, "composition": "lead",
            "grid": "thirds", "layout": "fill", "motion": "lateral:right", "hero": "largest"},
           {"source": "MVI_3739.mp4", "window": [4, 6], "composition": "center",
            "grid": "thirds", "white_balance": 0.5, "saturation": 1.1},
           {"source": "MVI_3998.mp4", "window": 1, "composition": "center", "grid": "phi"}
         ],
         "music": null, "cap": 3, "target_dur": null, "look": {"vignette": 0.3, "fade": 0.8}
       }

3. **Build.** Run the authoring script (explicit args; the user never types flags):

       python -m scripts.edit_plan build \
         --footage <run>/footage/FOOTAGE.json \
         --selection <run>/reels/<reel>/selection.json \
         --project <run>/project.json \
         --out-dir <run>/reels/<reel> \
         [--cast <run>/footage/cast.json] [--spec <run>/reels/<reel>/SPEC.json] \
         [--pacing <run>/reels/<reel>/PACING.json --music <run>/reels/<reel>/MUSIC.json]

   Pass `--music` together with `--pacing` on the pacing-apply re-run (step 5 of the
   **pacing** skill) to fit the reel's END to a bar line: `lib/outro.fit_outro`
   grows or shrinks the LAST episode only, after pacing binds every cut, so the
   music resolves on a detected downbeat with a vocal-free half-second after it,
   instead of stopping mid-phrase wherever the footage happened to end. `--music`
   with no `--pacing` is a no-op — the fit needs the bound episode list, never a
   slot. Read `EDL.md`'s **Music outro** section (or the `outro:` log line) for
   which of three rungs won:
   - **`gap`** — a bar line has enough vocal-free space after it for the reel's own
     fade; the ending is clean. Nothing to do.
   - **`no-gap`** — no line had room at the normal fade, so the fit fell back to the
     nearest line with a longer fade (masking the cut instead of landing in
     silence) and says so in the report. A known-imperfect ending, not a failure —
     weigh whether a different closing shot (more `room_after`) or a different music
     window would do better before accepting it.
   - **`unchanged`** — nothing moved; the reel keeps its footage-derived length and
     the music will end mid-phrase. `EDL.md`'s **Music outro** section now names
     WHICH of five causes it was (`OutroFit.cause`) instead of one reading for all
     five — the exact collapse this field replaced (design 2026-09-07 §3). Each
     has its own remedy:
     - **`no-bars`** — the analysed music window carries no bar grid, so the fit
       never ran; re-analyse the window or pick a track with a detectable bar grid.
     - **`ramped-closer`** — the closing episode carries a ramp, whose played
       length is not its source length, so the fit is skipped rather than
       guessed; move the ramp off the last episode.
     - **`closer-not-in-footage`** — the closing episode's source is not in
       `FOOTAGE.json`, so its remaining room could not be measured; re-run intake
       so the closing source is in `FOOTAGE.json`.
     - **`no-reachable-line`** — the fit ran and no bar line within one bar of the
       cut's own length was one the closing shot could reach. Only this cause's
       log line names the grow/shrink room it had to work with — a shot with more
       `room_after` (a longer take, or moving the outro to a different episode),
       or a different music window, is the usual fix.
     - **`""`** (empty) — a pre-2026-09-07 `EDL.json`, written before the five
       causes became distinguishable; re-run `edit_plan build --pacing --music`
       to regenerate it.
     - **`no-episodes`** — the cut has no episodes to move. Unreachable through
       `edit_plan build` today (design §3); named here only so the vocabulary is
       complete, not because you will see it.

   `EDL.md`'s outro section also shows the move (seconds, signed) and, when
   `--spec` supplied a brief, the distance from `SPEC.length_s` — the fit does not
   resolve that tension silently, so read it rather than assume the length still
   matches the brief.

   **Re-fitting a fitted EDL is safe when it carries `base_dur`** — see the
   **pacing** skill's step 1 for why (design 2026-08-16 §3.1). Re-run pacing
   against the current `EDL.json` and re-apply with `--pacing --music`; no detour
   needed, including when a **reel-review** finding routes you back to `pacing`.
   An `EDL.json` written before 2026-08-16, or hand-authored through the SP1
   front door, has no `base_dur` — `pacing` warns on stderr when it reads one,
   and if that EDL also carries an outro fit, re-applying deadlocks; follow the
   escape the refusal names (rebuild WITHOUT `--pacing`/`--music`, re-fit,
   re-apply).

   Pass `--cast` when any episode's `hero` is a cast name — it sets `EDL.cast`,
   the registry the preflight resolves that name against. Pass `--spec` whenever
   `SPEC.json` exists — it carries two separate things onto the EDL. `SPEC.mood`
   selects the shot-mix preset the variety gate holds the cut to (without it the
   gate still runs, against `balanced`), and `SPEC.platform` becomes
   `EDL.platform`, which decides the safe-zone table `check_reel` judges the
   subject against and where a bottom title is laid out — without it, the generic
   zone. The build **logs the platform it resolved on every run**, including when
   there is none and when the label has no zone of its own; read that line rather
   than assuming. Pass `--spec` again on the `--pacing` re-apply, which re-stamps
   the EDL from scratch and would otherwise silently drop both. It projects each
   window, **preflights** the EDL against the project, and writes `EDL.json` +
   `EDL.md`. On a `stop_and_report`, fix and re-run — never hand-edit `EDL.json`
   (`selection.json` is the source; the EDL is generated). Four reasons exist.
   `edl-invalid` names the offending episode index for a per-episode failure —
   fix that episode in `selection.json` — but carries `episode_idx: null`
   instead when the failure is `EDL.cast` itself (an unreadable registry, no
   one episode to blame). `variety-gap`, `constraint-violation` and
   `length-band` are always `episode_idx: null` too: all three judge the whole
   cut, not one row, so "the named episode" is never the fix — `variety-gap`'s
   remedy is in step 2 above; `constraint-violation`'s is in Editorial rules
   below (revise `selection.json` to satisfy the rule, or have the user
   change/delete it in `CONSTRAINTS.json`); `length-band`'s is to re-scan
   footage-intake with a lower `--win-min`, choose a mood whose `asl` band
   starts at or above the carved floor the refusal names, or drop `--spec`
   (never fired by the `balanced` fallback itself — an absent or unmatched
   brief must not refuse a cut).

4. **Review.** Show the user `EDL.md`. On edits, revise `selection.json` and
   re-run step 3. `EDL.json` is regenerated every time — never patched by hand.

   That is how you revise THIS cut. A genuinely different cut of the same footage
   is a different reel: point `--out-dir` at a new directory under `<run>/reels/`
   — `<run>/reels/upbeat` beside `<run>/reels/main` — and author its own
   `selection.json` there. The editorial layer is about 120 KB, so forking it is
   free, while `<run>/footage/` (194 MB on a real shoot) and `<run>/music/` stay
   shared and are never re-scanned. Do NOT distinguish variants by filename:
   `MUSIC_A.json`, `MUSIC_B.json`, `pacing_B/` and `MATCH_nostalgic.md` are real
   names from a real run, and nothing in them records which is current or which
   pacing fit belongs to which track. A directory does.

## Editorial rules the user stated (CONSTRAINTS.json)

`edit_plan build` reads `CONSTRAINTS.json` from the folder holding `project.json`.
There is no flag: if the file is there, its rules bind this cut and every re-cut.
A broken rule stops the build with `"reason": "constraint-violation"` and writes
nothing. **There is no waiver** — the rule is the user's, so only the user changes
or deletes it. Report the refusal verbatim and fix the cut.

When the user states an editorial rule, write it down immediately, in their own
words:

```json
{"rules": [
  {"kind": "no_repeat", "stated": "эпизоды не должны повторяться"},
  {"kind": "open_with", "hero": "Serge", "stated": "дрон-сцена с Сержем открывает"},
  {"kind": "close_with", "hero": "Anna", "stated": "вторая дрон-сцена закрывает"},
  {"kind": "exclude", "source": "clips/DJI_0042.MP4", "window": 7, "stated": "этот дубль не брать"}
]}
```

- `no_repeat` — no two episodes from one shot (a scene-cut segment). Two windows of
  the same drone pass are a repeat even when their spans do not overlap.
- `open_with` / `close_with` — the first / last episode must pin that cast name.
  A bbox, a track id, or `"largest"` does NOT satisfy it: those name a tracking
  target, not a person. Pin the name.
- `exclude` — with `window`, bans that window's whole shot; without it, the clip.

Only these four kinds exist, and an unknown `kind` is refused at load. If the user
states a rule that does not fit — "don't put two drone shots back to back" — say so
out loud instead of inventing a field: it cannot be stored, so it cannot be enforced.

## Gate

Every episode has a source + window + shot-type. A preflight `stop_and_report`
is surfaced verbatim, never worked around. When `PACING.md` exists, every
episode also carries a `beat_slot`.

**You may not disable, lower, or downgrade any quality gate.** A gate that
blocks is routed back to its stage's skill, never loosened to pass. Never
hand-edit `EDL.json`: it is stamped (design 2026-08-04), and `edl_to_reel`
refuses a stamped EDL whose contents no longer match what was stamped —
raw-JSON surgery bypasses the very preflight this gate runs. Editorial changes
belong in `selection.json`; edit that and re-run the build (step 3).

## Hand-off

`EDL.json` drives the rest of the conveyor: `edl_to_reel` (or, later, the 5.1
router) extracts each window, runs process-episode per episode, and builds the
delivered reel — with music when `EDL.music` points at a `MUSIC.json`.
