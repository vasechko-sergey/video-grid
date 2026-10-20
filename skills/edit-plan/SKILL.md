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
- **`"$ROOT/references/editing-canon.md"`** (required read) — thirds, headroom, lead room,
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

**Plan to the brief's shot-length band** — `SPEC.md`'s **Shot length** line
(`SPEC.asl`) before the first build; the build log's `length band: the brief asks …`
confirms it. With no brief band, the mood's band is only a suggestion — it never
refuses the build — so cut to whole actions. A window is only 1–4 s, so a shot
inside a 6–10 s band IS a span; size every span to the whole action, not to the
window grid. The build says so when the cut's ASL falls outside the band — re-plan
before CP2 rather than show it (the second real run's first plan cut longboard rides
into 13 pieces of 3.3 s and was rejected).

**Launcher and references.** Run every pipeline step through the repo's launcher
`bin/vg`, never a bare `python`, and resolve every `references/…` read the same
way. `setup.sh` records the runtime's location at
`${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root`, so resolve it once:

    ROOT="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")"
    VG="$ROOT/bin/vg"

Then run every step as `"$VG" scripts.X`, read every reference as
`"$ROOT/references/…"`, and pass **absolute** paths for every footage / run /
output directory. Nothing here is relative to your working directory — a skill
runs from the user's footage project, not from the clone. If that file is
missing, the user has not run `bash setup.sh` — stop and say so rather than
guessing a path.

## Procedure

1. **Recon.** Read `FOOTAGE.md`, `project.json`, `"$ROOT/references/editing-canon.md"`, and
   any soft inputs present. Note the reel's target length (from `SPEC.md` or
   `project.json`, else propose one from the strongest windows).

   Read `SHEETS.md` and every sheet it links. When a window's exact in-point
   matters — the peak of a manoeuvre, the frame a person turns to camera —
   zoom in before deciding:

       "$VG" scripts.contact_sheet strip --footage <run>/footage/FOOTAGE.json \
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

   Every authorable key — layout, motion, colour, the reel-level `look` and
   `variety_waiver` — with the refusals that go with it, and the index table
   of all of them: read `"$ROOT/references/edit-plan/episode-fields.md"`
   before authoring.

   Converging a grade, before episodes exist and after: read
   `"$ROOT/references/edit-plan/grade-convergence.md"`. It is the loop that
   rebuilds `selection.json` and re-runs **match-grade**, and running it wrong
   re-renders a reel that did not need re-rendering.

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

       "$VG" scripts.edit_plan build \
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
   slot. A window with no bar grid (most calm tracks — 26 of 32 on the second real
   run) does not stop the fit: it falls back to the **beat** grid under a 1.5 s fade
   (`OutroFit.grid == "beat"`, named in the report), so the music still starts to fall
   on a line of its own grid. Read `EDL.md`'s **Music outro** section (or the `outro:`
   log line) for which of three rungs won:
   - **`gap`** — a line (bar, or beat) has enough vocal-free space after it for the
     fade; the ending is clean. Nothing to do.
   - **`no-gap`** — no line had room at that fade, so the fit fell back to the
     nearest line with the longer fade (a beat fit already uses it on both rungs) (masking the cut instead of landing in
     silence) and says so in the report. A known-imperfect ending, not a failure —
     weigh whether a different closing shot (more `room_after`) or a different music
     window would do better before accepting it.
   - **`unchanged`** — nothing moved; the reel keeps its footage-derived length and
     the music will end mid-phrase. `EDL.md`'s **Music outro** section now names
     WHICH of five causes it was (`OutroFit.cause`) instead of one reading for all
     five — the exact collapse this field replaced (design 2026-09-07 §3). Each
     has its own remedy:
     - **`no-bars`** — only on an EDL written before 2026-10-19, when a window with
       no bar grid stopped the fit; re-run `edit_plan build --pacing --music` and it
       falls back to the beats.
     - **`ramped-closer`** — the closing episode carries a ramp, whose played
       length is not its source length, so the fit is skipped rather than
       guessed; move the ramp off the last episode.
     - **`closer-not-in-footage`** — the closing episode's source is not in
       `FOOTAGE.json`, so its remaining room could not be measured; re-run intake
       so the closing source is in `FOOTAGE.json`.
     - **`no-reachable-line`** — the fit ran and no line of its grid within one bar of the
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
   the EDL from scratch and would otherwise silently drop both — and the brief's
   `music_in_app` with them (the log's `music in the app:` line shows it). It projects each
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
   change/delete it in `CONSTRAINTS.json`); `length-band` fires only for a band
   the brief chose (`SPEC.asl`) whose floor is under the carved floor, and its
   remedy is to raise the brief's `--asl` floor or re-scan footage-intake with a
   lower `--win-min`. A mood's band never fires it — since 2026-10-20 it is a
   suggestion, logged as one.

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
