---
name: match-grade
description: Conveyor stage — the match-grade conductor. Measures every EDL episode's own tracked crop (the pixels that actually ship, read through GEOMETRY.json's frozen route), computes one common reel target (the per-anchor median), and auto-authors tone_src/tone_dst on episodes that deviate past --eps (default 4 luma units), rewriting EDL.json in place plus a MATCH.md report. using-montage invokes this after episodes-geometry (there is no crop to measure before a route is frozen) and before the render; run it directly only to re-grade. Required — the router runs it on every reel, even a single-camera one, since it costs seconds and reports within-eps for free.
---

# match-grade (design §10, tone conductor)

match-grade is a **conductor, not a corrector**: it never imposes an outside
look (that stays the deferred §10 mood LUT) — it only pulls every episode's
tone toward the reel's OWN common target, the per-anchor median of everything
measured, so a reel cut from mixed cameras/lighting reads as one grade. It
touches **only** the `tone_src`/`tone_dst` pair colour-as-a-stage's actuator
already knows how to render (`color.tone_arg` → reframe's `grade_chain`,
riding the ONE encode `edl_to_reel` already runs) — no new pass, no other
grade knob.

A thin driver (`scripts/match_grade.py`) over the pure `scripts/lib/matchgrade`
core (median target + gap-repair + eps-gate + a per-episode planner — no
ffmpeg, no numpy).

## Inputs

- **`GEOMETRY.json`** (required, from `edl_to_reel --stop-after-geometry`) —
  every episode's frozen route and the crop it will actually ship, colour
  block stripped. match-grade reads the EDL it names, measures each episode's
  OWN tracked **crop** through that frozen route — never the whole source
  frame — and rewrites the EDL IN PLACE with the tone pairs it authors.

Not `SPEC.json`/`MUSIC.json` for timing: match-grade is a pure colour pass over
a cut that already exists — it invents no timing and reads no editorial brief.

## When to run

AFTER `episodes-geometry` (`edl_to_reel --stop-after-geometry`) has frozen
every episode's route — there is no crop to measure before a route exists —
and BEFORE the render (`edl_to_reel --from-geometry`). **Required, not
opt-in**, since 2026-08-30: the router runs it on every reel, even a
single-camera one — every episode simply lands `within-eps` and `MATCH.md`
says so, which costs a few seconds (eight crops in about five seconds on a
real reel) and is cheaper than a stage nobody is told to run at the moment of
need being rebuilt by hand instead (design §6, closing the retro's R4.2). It
still changes nothing on a reel that already reads as one grade: no pair is
authored unless an episode actually deviates past `--eps`.

**Ordering landmine.** Pacing re-runs edit-plan with `--pacing` to apply its
fit, and that re-run REGENERATES `EDL.json` from `selection.json` — wiping any
tone pair match-grade already authored, and orphaning the frozen
`GEOMETRY.json`'s cut identity too (`edl_to_reel --from-geometry` would then
refuse the changed cut). Always settle the cut — edit-plan, then pacing's
apply pass — BEFORE running `--stop-after-geometry`, and run match-grade only
after that. Same "settle the cut first" rule pacing itself carries, now also
enforced mechanically: a re-cut after freezing the geometry is refused, not
silently graded.

## The Process

Announce on entry: **"Using match-grade to pull the episodes to one tone."**

**Launcher.** Run every pipeline step through the repo's launcher `bin/vg`, never a
bare venv `python` binary. Resolve it once: `setup.sh` records the runtime's location
at `${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root`, so set
`VG="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")/bin/vg"` and run every
step as `"$VG" scripts.X`, passing **absolute** paths for every footage / run / output
directory. If that file is missing, the user has not run `bash setup.sh` — stop and
say so rather than guessing a path.

1. **Recon.** `<run>/reels/<reel>/episodes/GEOMETRY.json` must already exist —
   this stage runs AFTER **episodes-geometry**, which itself needs a settled
   cut (edit-plan, and pacing's apply pass too, if used). No `GEOMETRY.json`
   -> run `edl_to_reel --stop-after-geometry` first; there is no frozen route
   and no crop to measure yet.
2. **Conduct.**
   `"$VG" scripts.match_grade build --geometry <run>/reels/<reel>/episodes/GEOMETRY.json [--spec <run>/reels/<reel>/SPEC.json] [--eps 4.0] [--force]`
   Measures every episode's OWN tracked crop — read through the route
   `GEOMETRY.json` froze, at colour identity — computes the one common target
   (the per-anchor median across episodes), and rewrites the EDL
   `GEOMETRY.json` itself names IN PLACE — `tone_src`/`tone_dst` land on every
   episode that deviates past `--eps` (default 4 luma units). Also writes a
   sibling `MATCH.md` beside that EDL. No `--edl` and no `--footage-root`:
   the geometry file names the EDL, and every episode's source is already an
   absolute path inside it.

   **Pass `--spec` when a brief exists.** Without it the conductor is pure
   consistency: it makes the cameras agree and has no view on what they should
   agree *to*. With it, `SPEC.mood` displaces the common target in the direction
   the mood asks for — brighter and airier for `fun`, wider contrast for `epic`,
   darker and crushed for `moody`, faded for `nostalgic` (design 2026-08-17 §4).
   A brief whose mood matches nothing resolves to `balanced` and displaces
   nothing, on purpose.
3. **Read the report.** `MATCH.md` lists the target triple (p5/p50/p95), then
   one row per episode: its measured profile, its distance (max Δ) to the
   target, and the action taken (`author`/`skip`) with a reason (`authored` /
   `within-eps` / `flat-source` / `hand-authored`). Surface it at the CP3
   final review beside the reel.

   **`mood-bias-ineffective` is the one line that needs a decision.** It means
   the reel's own tonal range left no room for the mood's displacement, so what
   survived is under the ~10-luma floor where a grade change becomes visible at
   all — most often `epic` on footage whose highlights already sit near the top.
   The stage does not refuse. Either accept a consistency-only grade, or choose a
   mood that pulls inward (`moody`, `nostalgic`) instead of one that asks for
   more highlight headroom than the footage has.
4. **Nothing further to apply.** Unlike pacing, there is no second
   `edit_plan build` pass here — `write_match` already rewrote `EDL.json`.
   The next stage (`assemble-draft`/`edl_to_reel`) reads the enriched EDL
   directly.

## Guarantees

- **Touches only the tone pair.** No other grade knob (`white_balance`,
  `black_point`, `saturation`, `shadow_red`, `mid_blue`, `dip`) is read or
  written — those stay hand/agent-authored, untouched by this stage.
- **Byte-identical when already close.** An episode already within `--eps`
  luma units of the target gets NO tone pair — reframe's byte-identical fast
  path is preserved for it, not spent on a curve nobody would see.
- **A hand-authored pair is respected.** An episode that already carries a
  `tone_src`/`tone_dst` (a human pasted `measure_profile` output, or a prior
  match-grade run) is left alone UNLESS `--force`.
- **A flat/low-contrast source is skipped, never faked.** An episode whose
  own measured profile has no usable range (gaps under `color.TONE_MIN_GAP`,
  6 units) cannot be a curve's source — its contrast cannot be invented — so
  it is reported `flat-source` and left untouched. It still counts toward the
  reel's common target: every episode votes; not every episode receives.

## In-place rewrite

`match_grade build` rewrites `EDL.json` IN PLACE — that is the stage's actual
output, enriching the EDL a human then reviews, the same file `edl_to_reel`
reads next. It is git-tracked, so a mistaken run is recoverable via git.
Re-running WITHOUT `--force` is a safe no-op: match-grade cannot tell its own
prior tone from a human's, so it treats it as hand-authored and skips every
episode.

## Honest limit

**Closed 2026-08-30.** match-grade used to measure the WHOLE source frame at
the window's midpoint, before tracking ever ran — a tight crop on a rider
could read a different histogram from the wide frame around them. Measured on
a real 8-episode reel: seven of eight episodes disagreed with a crop-based
reading by more than `--eps`, median 14 and max 36 luma units, which moved
five episodes' authored pairs by roughly 10 units each while their p5/p95
anchors (pinned by sky and specular water) never moved at all. It now measures
each episode's own tracked crop through `GEOMETRY.json`'s frozen route — the
pixels that actually ship.

What is still true: **luma only**. The target and every measured profile are
(p5, p50, p95) of luma — two cameras can still disagree on white balance after
every episode lands on the same tone target, and nothing here measures
agreement between episodes (`color_fidelity` compares an episode against its
OWN source, i.e. damage, never episode against episode). Filed under the
mood-LUT/agreement gap, design §10.

**And `color_fidelity` may STOP a run this stage just fixed.** It is blocking at
5.0 dE00 with **no waiver anywhere**, and the tone pair authored here is grade
movement to it: its whole headroom is roughly 14–20 codes of subject luma, and on
the one real 8-episode reel every episode has a band that exceeds it. The stop
arrives as `grade-damage`, routed to edit-plan's colour block — the pair this
stage just wrote on purpose. There is no lever to lower; if you hit it, read
`docs/backlog.md`'s P1 row and the grade-shipped-pixels design §9.8 rather than
looking for a flag.

## Not this skill

- **Imposing an external look** (a mood LUT from `SPEC.mood`) → deferred,
  design §10's other half. match-grade only pulls episodes toward each
  OTHER, never toward an outside target.
- **White balance, black point, saturation, or any other grade knob** →
  hand/agent-authored on the EDL episode directly; this stage is tone (luma)
  only.
- **A deliberate exposure cut** (open water -> bright beach) → still an
  editorial choice this stage does not detect — match-grade pulls every
  episode toward one reel-wide target, it does not read intent into a
  scene-cut. Nothing mechanical checks this anymore either: the reel-level
  `color_across_cuts` ceiling (`--color-delta-max`) is retired (2026-08-29),
  since it could not tell "deliberate cut" from "wrong grade" in the first
  place. `reel-review`'s `colour` axis is where a human now makes that call.
- **Fixing a reel that already shipped** → there is no automatic in-loop
  colour reprocess anymore. `build_reel`'s Phase A.5 colour arm (which pulled
  a *delivered-space* outlier toward the reel's median after render) is
  retired with the check that drove it (2026-08-29) — it optimised a
  different quantity than any gate read. The path now is editorial:
  `reel-review`'s `colour` axis names the episode that drifted, routed back
  to THIS skill — re-run match-grade against the SAME `GEOMETRY.json`
  (`--force` if the episode already carries a tone pair), then
  `edl_to_reel --from-geometry` to re-render over the still-frozen routes
  (never `--stop-after-geometry` again unless the cut itself is changing too
  — that pays for a full re-track this seam exists to avoid), then episode-qc
  and deliver again.
