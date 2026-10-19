---
name: match-grade
description: "Conveyor stage — the match-grade conductor: measure every episode's tracked crop, compute one common reel tone target, and author tone_src/tone_dst on the episodes that deviate. Required. Conveyor position: after episodes-geometry, before assemble-draft. Tool index: references/tools.md."
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

- **`REGIONS.json`** (optional, beside `<run>/project.json`) — the author's
  declaration of WHICH region supplies WHICH tone anchor. Found by convention,
  never by a flag: `GEOMETRY.json` records the project file phase 1a was given,
  and match-grade looks next to it. A flag can be forgotten, and a forgotten
  flag here silently reverts the grade to whole-crop anchors. Absent, every
  anchor is the whole crop — the same EDL and the same target, byte for byte.
  (`MATCH.md`/`MATCH.json` are not byte-identical: they gain the declaration
  line and the per-anchor table on every run, declared or not.) Full contract
  below.

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

**If this order is missed anyway, `montage status` now says so.** Since
2026-09-09, `montage status`/`next_action` compares `MATCH.json`'s authored
decisions against the EDL as it is right now — not a digest of the file, the
pairs themselves, because a legitimate re-conduct rewrites the same file. A
`--pacing` re-run (or any other rewrite) that drops a pair this stage
authored makes the `match-grade` row read **`stale`**, not `done`, with a
reason naming which episode lost its pair — so `next` points back at this
stage instead of skipping it as already finished. This is a `status`/`next`
signal only: it does not stop a render already in flight, and the mechanical
gate (`grade_faithful`) still cannot see the loss either, since it predicts
each episode against its OWN (now pair-less) declared chain and the two
agree — re-run this stage before delivering, do not rely on a render-time
check to catch it.

## The Process

Announce on entry: **"Using match-grade to pull the episodes to one tone."**

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
   sibling `MATCH.json` — the decisions themselves (index/action/reason/
   measured profile/pair), what `montage status` reads to notice a later wipe
   — and its rendered `MATCH.md`, byte-identical to before this twin existed.
   No `--edl` and no `--footage-root`: the geometry file names the EDL, and
   every episode's source is already an absolute path inside it.

   **Pass `--spec` when a brief exists.** Without it the conductor is pure
   consistency: it makes the cameras agree and has no view on what they should
   agree *to*. With it, `SPEC.mood` displaces the common target in the direction
   the mood asks for — brighter and airier for `fun`, wider contrast for `epic`,
   darker and crushed for `moody`, faded for `nostalgic` (design 2026-08-17 §4).
   A brief whose mood matches nothing resolves to `balanced` and displaces
   nothing, on purpose.

   **An authored `SPEC.tone_bias` outranks the mood preset's own** (design
   2026-09-03 §2). `None` — the default, no `tone_bias` key in `SPEC.json` —
   takes the preset's taste exactly as above; an explicit `[0, 0, 0]` is a
   real, different answer, *this mood, but leave my colour alone*, and is
   honoured exactly rather than treated as absent. `MATCH.md`'s header now
   names which one actually won — `from SPEC.tone_bias` or `from the
   nostalgic preset` — instead of printing a displacement with no stated
   source.
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

   **`toe-lift` names an episode whose shadows the pair raises by more than 15
   luma** (also printed to stderr, and in the status JSON's `toe_lifts`). The
   conductor cannot tell an underexposed shot from one that is dark on purpose —
   the second real run lifted a backlit silhouette from p5 38 to 60. Look at it
   with `probe grade --geometry`; if the dark is the point, pin the episode with
   an identity pair (`tone_dst` equal to its `tone_src` in `EDL.json`), which the
   conductor then leaves alone as `hand-authored` unless `--force`.
4. **Nothing further to apply.** Unlike pacing, there is no second
   `edit_plan build` pass here — `write_match` already rewrote `EDL.json`.
   The next stage (`assemble-draft`/`edl_to_reel`) reads the enriched EDL
   directly.

## Naming the regions — `REGIONS.json` (design 2026-09-15)

An anchor is a measurement, and a measurement needs a subject. Without a
declaration all three anchors share one subject — every pixel of the crop — and
on real footage that resolves to **whichever region is largest**, not to some
neutral whole. Measured on the only real 8-episode reel: the tracked subject is
**0.23% to 37% of the frame, a 161x spread inside one reel**, and seven of the
eight crops read within about a code of their own *background*. Naming regions
does not introduce a bias into a neutral measurement; it replaces an unnamed one.

Write the file beside the project:

```json
{"anchors": [
  {"anchor": "toe",      "name": "wetsuit", "of": "subject"},
  {"anchor": "mid",      "name": "water",   "of": "background"},
  {"anchor": "shoulder", "name": "frame",   "of": "crop"}]}
```

**Two closed sets and one free string.**

- **`anchor`** — `toe` (p5) | `mid` (p50) | `shoulder` (p95). The anchor names
  the STATISTIC; a declaration chooses the pixel set and never the percentile.
  Each anchor may be declared at most once; an undeclared anchor is the crop, so
  a partial declaration is a real answer and not a half-configured state.
- **`of`** — `subject` (the frozen route's own bbox, projected into the
  delivered crop by the same function the safe-zone check uses) | `background`
  (everything the subject box is not) | `crop` (every pixel — the default).
- **`name`** — **your noun, and nothing verifies it.** The code never
  interprets it; it carries it into the report so a reader sees `toe from
  wetsuit (subject, 2.2% of frame)` instead of `toe from subject`. If the rider
  is in white that day the declaration is wrong and every report will faithfully
  print `wetsuit`.

Anything outside those two sets is refused **at load, by name** — an unknown
anchor, an unknown kind, an extra field, an empty `name`, one anchor declared
twice, a malformed file. Nothing lives in this file that the machine does not
check; that is the same rule `CONSTRAINTS.json` carries.

**What it buys, measured.** On the only real reel, taking the toe from the
subject moved the common target's p5 by **23 luma codes on the delivered clips
and 34 on the source**, against an `--eps` of 4 — while the mid moved +1.5 and
the shoulder 0.0. One anchor of three is earned; the per-anchor form is general
because the assignment is a three-entry loop either way, not because two thirds
of it were measured to help.

**What was measured and rejected.** A tonal *band inside* a region — "skin" as
the brightest 30% of the subject box — is the **worst** reference of everything
measured (cross-episode sd 34.3, worse than the crop's own p95 at 36.8), and the
dark band standing in for the wetsuit (14.9) **loses to the plain p5 it would
replace** (10.0). There is deliberately no `band` kind. Do not hand-roll one.

**Three named fallbacks**, each printed in `MATCH.md` beside the anchor it fired
on, none silent and none repaired:

- **`no-route`** — a pan episode's path is generated, so it has no route, no
  subject and no background. That anchor takes the crop. This fires on a MISSING
  ROUTE and on nothing else.
- **`too-small`** — the region averages under 1% of the frame
  (`regions.MIN_REGION_FRAC`). A 54x69 tracked box over breaking water is more
  likely a mis-track than a subject: on the real reel that episode's subject p50
  read **243.5** against its background's 133.2. This is also where a routed
  episode lands when its subject leaves the delivered frame entirely — the
  region was located and measured at 0.00% of it, which is a real reading, not
  a missing route.
- **`unorderable`** — the assembled (p5, p50, p95) does not increase by
  `color.TONE_MIN_GAP`. The **whole episode** drops back to its crop profile,
  never the offending anchor alone: a mixed profile whose toe came from a region
  and whose mid came from the crop is a third thing nobody can name. A measured
  source profile is never widened to fit — that would author a curve from a
  number no frame contains.

**`MATCH.md` and `MATCH.json` both state which of three things happened to the
declaration itself**, because two of them look identical in the pixels: it was
`found` (and where); the project resolved and held `none` ("every anchor is the
whole crop because you asked for nothing"); or it was `unreachable`
("...because I could not look") — a `GEOMETRY.json` written before this feature
records no project, and a recorded project that does not resolve from where
match-grade is running is the same blindness wearing a different hat. The
reachability test is the project FILE, so a bare relative `project.json`
recorded in one directory and read from another is `unreachable`, never
"nothing was declared". In `MATCH.json` the state is the `regions` field and its
path-or-reason is `regions_at`; an empty `regions` there means the report
predates the field, not that no declaration was found. Re-run
`edl_to_reel --stop-after-geometry` to record a reachable project.

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

**Still true of a named region (2026-09-15).** `subject` is the route's
**box, not a mask** — a box over a rider contains water, which is precisely why
the subject is the best toe reference and the worst mid one. The intake seg
model's masks have been discarded since 2026-08-04; a masked subject is a real
improvement this does not make. And an episode follows **one** route, so
`subject` means "whoever this episode follows": naming a second person in the
same frame is unreachable without a second route. The stage proves a region was
used; it never proves it was the right region, and it cannot check your noun.

What is still true: **luma only**. The target and every measured profile are
(p5, p50, p95) of luma — two cameras can still disagree on white balance after
every episode lands on the same tone target, and nothing here measures
agreement between episodes (`check_episode`'s `grade_damage` compares an
episode against its OWN source, i.e. damage, never episode against episode).
Filed under the mood-LUT/agreement gap, design §10.

**Closed 2026-09-02: `grade_damage` no longer STOPS a run this stage just
fixed.** Until then, the mechanical gate this pair fed into measured how far
the grade moved the tracked subject's colour from its own source — and a
grade IS movement, so a real conductor pair routinely crossed it: on the one
real 8-episode reel every episode had a subject-luma band that exceeded the
old 5.0 dE00 ceiling, and that gate had no lever at all. `check_episode.color_fidelity`
is now `grade_damage`: it renders the episode's OWN declared grade twice —
once as declared, once with every colour knob at identity — and asks whether
the declared map DESTROYED information (Shannon entropy of the luma
histogram, against `CheckSpec.entropy_floor`, 0.90 by default), not whether it moved
anything. A tone pair authored here reads as movement, which the sensor is
now built to ignore, and passes cleanly; the old dE00 reading survives only as
an advisory number in `report.json`, read by the QC judge, never a gate. If a
`grade-damage` finding does arrive now, it means the named colour knob is
genuinely too aggressive (e.g. `black_point`/`highlight` near their legal
limit) — soften it in the episode's colour block via **edit-plan**; it is no
longer this stage's own pair being misdiagnosed.

The floor is the one bar here an operator may move, and only through a `GATES.json`
beside `project.json` whose `entropy_floor` entry carries a written reason — refused
at load without one, then named beside the verdict it bought, in the attestation and in
`montage status`. That is the user's decision for footage the default is wrong for,
never this stage's and never a way to wave through a pair it authored: a `grade-damage`
finding is still routed to the episode's colour block. With no colour block declared the
graded and plain renders are the same render, the ratio is exactly 1.0, and no floor
can refuse it — moving the floor on an ungraded reel changes nothing.

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
