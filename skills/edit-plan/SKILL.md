---
name: edit-plan
description: Stage 5.7 — author an EDL from scored footage windows. Use after footage-intake (FOOTAGE.json exists) and project-init (project.json) to turn candidate moment-windows into a typed EDL.json + a human EDL.md map that edl_to_reel drives to a reel. Autonomous draft + one review gate.
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

- **`FOOTAGE.json` + `FOOTAGE.md`** (required, from footage-intake) — the ranked
  candidate windows. Read `FOOTAGE.md` for the human view; the window **index**
  you reference is the 0-based position within that clip's window list.
- **`project.json`** (required, from project-init) — the canvas/delivery the
  episodes inherit; used by the preflight.
- **`references/editing-canon.md`** (required read) — thirds, headroom, lead room,
  the 180° rule, cut-on-action, contrast. Your editorial base.
- **`SPEC.md` / `PACING.md` / `MUSIC.json`** (optional) — read as guidance when
  present. Without `PACING.md`, leave `beat_slot` unset. Point `music` at a
  `MUSIC.json` when one exists.

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
2. **Author `selection.json`.** Pick the best windows (they are already ranked),
   dedup across sources so one clip doesn't dominate, fit the running sum to the
   target length, and order them **hook first**. For each episode assign:
   - `composition` ∈ `lead` / `center` / `break` (required)
   - `grid` ∈ `thirds` / `phi` (required)
   - `layout` ∈ `fill` / `fit` / `insert` (default `fill`)
   - `background` ∈ `blur` / `solid` (default `blur`; `fill` accepts only `blur` —
     it covers the canvas edge to edge, so there is nothing else to fill) +
     optional `background_color` (an ffmpeg colour name or hex, default `black`,
     `solid` only)
   - `motion` ∈ `lateral:right` / `lateral:left` / `head-on` / `static` (optional)
   - `hero` (optional) — a first-frame seed bbox `[x,y,w,h]` (centre-format,
     source px), a rule (`largest`/`leftmost`), an integer track id, or a cast
     name resolved through `cast.json` (§6.1a). A cast name needs the registry:
     pass `--cast` (step 3) and the name must exist in `cast.json` — an
     unresolvable name is a preflight `edl-invalid` (fix `selection.json` and
     re-run), and a pin that matches nobody in the episode's segment is a
     `hero-unmatched` stop-and-report at process-episode time — never a silent
     fallback to intent scoring.
   - `pan` (optional) — `{"from": f, "to": f}`, a **generated** constant-velocity
     camera move: two fractions of the crop's horizontal freedom (`0.0` hard
     left, `1.0` hard right; direction is the sign of `to - from`). It replaces
     tracked motion for the episode — no route is read, no hero is followed.
     The gate enforces two constraints: `composition` must be `center` (a pan
     positions the crop by its own law, so `lead`/`break`'s subject-relative
     framing has nothing to consult — a preflight `edl-invalid` names the
     conflict), and no `hero` pin may be set alongside it (the pin says
     "follow this person", the pan says "follow nobody"). `motion` may still
     be set — it describes the *subject*, the pan describes the *camera*, and
     the canonical pan is `motion: static` with a moving frame, both at once.
   - `processing_notes` — a short note for the draft labels (optional)

   The shape (integer window indices — or a `[i, j]` span — + editorial only, no timestamps):

       {
         "episodes": [
           {"source": "MVI_3739.mp4", "window": 2, "composition": "lead",
            "grid": "thirds", "layout": "fill", "motion": "lateral:right", "hero": "largest"},
           {"source": "MVI_3739.mp4", "window": [4, 6], "composition": "center", "grid": "thirds"},
           {"source": "MVI_3998.mp4", "window": 1, "composition": "center", "grid": "phi"}
         ],
         "music": null, "cap": 3, "target_dur": null
       }

3. **Build.** Run the authoring script (explicit args; the user never types flags):

       python -m scripts.edit_plan build --footage FOOTAGE.json \
         --selection selection.json --project project.json --out-dir . \
         [--cast cast.json]

   Pass `--cast` when any episode's `hero` is a cast name — it sets `EDL.cast`,
   the registry the preflight resolves that name against. It projects each
   window, **preflights** the EDL against the project, and writes `EDL.json` +
   `EDL.md`. On a `stop_and_report` (reason `edl-invalid`), fix the named
   episode in `selection.json` and re-run — never hand-edit `EDL.json`
   (`selection.json` is the source; the EDL is generated).

4. **Review.** Show the user `EDL.md`. On edits, revise `selection.json` and
   re-run step 3. `EDL.json` is regenerated every time — never patched by hand.

## Gate

Every episode has a source + window + shot-type. A preflight `stop_and_report` is
surfaced verbatim (episode index + problems), never worked around. When
`PACING.md` exists, every episode also carries a `beat_slot`.

## Hand-off

`EDL.json` drives the rest of the conveyor: `edl_to_reel` (or, later, the 5.1
router) extracts each window, runs process-episode per episode, and builds the
delivered reel — with music when `EDL.music` points at a `MUSIC.json`.
