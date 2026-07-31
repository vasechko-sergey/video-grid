---
name: match-grade
description: Montage design §10 — the match-grade conductor: measure every EDL episode's source tone (luma) at its window midpoint, compute one common reel target (the per-anchor median across episodes), and auto-author tone_src/tone_dst on episodes that deviate past --eps (default 4 luma units), rewriting EDL.json in place plus a MATCH.md report. Runs AFTER edit-plan and pacing — a pacing re-run regenerates EDL.json and would wipe an authored tone — and BEFORE edl_to_reel. Opt-in: only useful when episodes come from mixed cameras/lighting; a single-camera reel skips it.
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

- **`EDL.json`** (required, from edit-plan — and from pacing too, if the reel
  uses music) — the settled cut. match-grade reads it, measures each
  episode's *source* clip, and rewrites it IN PLACE with the tone pairs it
  authors.
- **A footage root** (required) — the directory each episode's `source` path
  resolves against, the same root every other stage uses.

Not `SPEC.json`/`MUSIC.json`: match-grade is a pure colour pass over a cut
that already exists — it invents no timing and reads no editorial brief.

## When to run

AFTER the cut is fully settled — edit-plan, and pacing too when the reel
carries music — and BEFORE `edl_to_reel`. Only run it when the episodes
actually come from mixed cameras or mixed lighting; a single-camera reel
already reads as one grade and needs it not (every episode would land
`within-eps` and receive no pair). Opt-in, like `white_balance`/`dip`/the SFX
whoosh: it changes the look, so it never sits on the autonomous path — a
human chooses to run it.

**Ordering landmine.** Pacing re-runs edit-plan with `--pacing` to apply its
fit, and that re-run REGENERATES `EDL.json` from `selection.json` — wiping
any tone pair match-grade already authored. Always run match-grade AFTER
pacing, never before it. Same "settle the cut first" rule pacing itself
carries.

## The Process

Announce on entry: **"Using match-grade to pull the episodes to one tone."**

**Launcher.** Run every pipeline step through the repo's launcher `bin/vg`, never a
bare venv `python` binary. Resolve it once: `setup.sh` records the runtime's location
at `${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root`, so set
`VG="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")/bin/vg"` and run every
step as `"$VG" scripts.X`, passing **absolute** paths for every footage / run / output
directory. If that file is missing, the user has not run `bash setup.sh` — stop and
say so rather than guessing a path.

1. **Recon.** `EDL.json` must already exist and the cut must be settled — this
   stage runs AFTER edit-plan and, if used, AFTER pacing's apply pass. No
   `EDL.json` -> run edit-plan first; there is no cut to grade.
2. **Conduct.**
   `"$VG" scripts.match_grade build --edl <run>/EDL.json --footage-root <footage_root> [--eps 4.0] [--force]`
   Measures every episode's source at its window midpoint, computes the one
   common target (the per-anchor median across episodes), and rewrites
   `EDL.json` IN PLACE — `tone_src`/`tone_dst` land on every episode that
   deviates past `--eps` (default 4 luma units). Also writes a sibling
   `MATCH.md`.
3. **Read the report.** `MATCH.md` lists the target triple (p5/p50/p95), then
   one row per episode: its measured profile, its distance (max Δ) to the
   target, and the action taken (`author`/`skip`) with a reason (`authored` /
   `within-eps` / `flat-source` / `hand-authored`). Surface it at the CP3
   final review beside the reel.
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

match-grade measures the WHOLE source frame at the window's midpoint, not the
shipped crop — it runs before tracking, so there is no crop yet to measure. A
tight crop on a rider can read a different histogram from the wide frame
around them. This is the same boundary `color_measure.measure_profile`
already ships with — the honest MVP, not hidden.

## Not this skill

- **Imposing an external look** (a mood LUT from `SPEC.mood`) → deferred,
  design §10's other half. match-grade only pulls episodes toward each
  OTHER, never toward an outside target.
- **White balance, black point, saturation, or any other grade knob** →
  hand/agent-authored on the EDL episode directly (or `edl_to_reel
  --color-delta-max` for the across-cut ceiling); this stage is tone (luma)
  only.
- **A deliberate exposure cut** (open water -> bright beach) → an editorial
  choice `edl_to_reel --color-delta-max` still honors; match-grade pulls
  toward one reel-wide target, it does not detect a scene-cut that means to
  change exposure.
- **Fixing a reel that already shipped** → `build_reel`'s in-loop colour
  reprocess (Phase A.5) corrects a *delivered-space* outlier against the
  reel's median after render; this stage runs earlier, on the EDL, before
  any pixel is cut.
