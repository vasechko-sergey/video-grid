---
name: reel-review
description: "Conveyor stage — the reel's final editorial review at CP3: a fresh reviewer subagent judges the delivered reel against SPEC, findings validated into REVIEW.json + REVIEW.md and routed to the stage that owns each fix. Human-gated. Required. Conveyor position: after deliver, last. Tool index: references/tools.md."
---

# reel-review (stage 5.13, editorial half)

## Overview

The **final editorial gate**. `check_reel` already judged the reel *mechanically*
(black/loudness/variety/length + the advisory safe_zones/key_action/
pad_bars/transitions/beat/chroma_spread). `chroma_spread` (design 2026-09-17
§2.4) measures whether the grade treated the episodes ALIKE, never whether they
end up agreeing (§5.1) — colour AGREEMENT across episodes still has no
mechanical check of its own, which is what this stage's own `colour` axis
exists to judge (design 2026-08-29, colour-convergence-retire §4-§5; design
2026-09-17 §5.1). reel-review judges the
reel *editorially*: does it deliver the brief? This is the `requesting-code-review` pattern one level up — you
dispatch a **fresh reviewer subagent** with a crafted packet, it returns typed
findings, and the **human** decides what to act on at Checkpoint 3.

**Core principle:** fresh eyes, typed findings, human disposes. You built the reel
(or conducted its build), so you are anchored — a fresh subagent, given only the
artifacts, reviews without that bias. The verdict is advisory; the CP3 gate is the
human's sign-off.

## When to Use

At **Checkpoint 3**, once `<run>/reels/<reel>/deliveries/REEL_v{n}.mp4` exists and `check_reel` has run. Not
before delivery (there is no reel to judge). Re-run it after any fix round (a new
cut is a new review).

**`--reel` must name a file that exists, and the review is bound to its bytes,
not to the path.** Since 2026-09-09 `reel_review build`'s CLI refuses a
`--reel` naming no file outright (`names no file` in the error), and
`build_review` stamps `Review.reel_digest` from that file on disk — never
from the reviewer's claim, the same rule `episode_qc`'s clip digest already
follows. Always resolve `{n}` to the ACTUAL newest delivered version via
`montage status` before invoking this stage; a review naming an older or
now-deleted `REEL_v{n}` reads as **`stale`** in `montage status` (it compares
the review's filename against the newest delivery — free, no hashing) and
`montage verify` re-hashes the file to prove the bytes still match. A review
written before this field existed loads as **unbound**, not corrupt —
`REVIEW.md` says so plainly rather than pretending a digest that was never
computed.

**Launcher and references.** Run every pipeline step through the plugin's launcher
`bin/vg`, never a bare `python`, and resolve every `references/…` read the same
way. Claude Code writes this plugin's own directory into the line below when it
loads the skill, so resolve it once:

    ROOT="${CLAUDE_PLUGIN_ROOT}"
    VG="$ROOT/bin/vg"

If `ROOT` comes out empty, or `"$VG"` does not exist — a harness that did not fill
the line in — `ROOT` is the directory two levels above this skill's base directory.
Then run every step as
`"$VG" scripts.X`, read every reference as `"$ROOT/references/…"`, and pass
**absolute** paths for every footage / run / output directory. Nothing here is
relative to your working directory — a skill runs from the user's footage
project. If `"$VG"` says there is no runtime, it has not been set up yet: run the
`setup` skill (`/video-grid:setup`), which asks before installing anything.

## Inputs (the context packet — resolve paths under the run dir)

- **`<run>/reels/<reel>/deliveries/REEL_v{n}.mp4`** (required) — the delivered reel.
- **`report.json`** (required) — `check_reel`'s report: the mechanical gates + the
  **advisory signals** (`key_action`/`pad_bars`/`transitions`/`safe_zones`/`beat`/
  `brief_length`/`outro`/`chroma_spread`) the reviewer cites as evidence.
  `brief_length` is advisory by design and expected to be frequently red (design
  2026-09-07 §7) — a red row there is a real gap to weigh, not a mechanical
  failure. `chroma_spread` (design 2026-09-17 §2.4) measures whether the grade
  treated the episodes ALIKE, not whether they end up agreeing — cite it for the
  `colour` axis alongside the stills, never as proof of agreement on its own.
- **`SPEC.json`** (optional) — the brief's intent. Absent (a bare autonomous run) →
  review against the `EDL` + the run's stated intent; say so.
- **`EDL.md`** (required) — the realized plan (per-episode source/window/shot/
  layout/comp/motion/beat/notes).
- **`MUSIC.json` / `PACING.json` / `PACING.md`** (optional) — the mood target +
  energy spine; `PACING.md`'s Verdict and Energy agreement lines are what the
  `spine` axis's evidence actually cites (design 2026-09-07 §6).

## Procedure

Announce on entry: **"Using reel-review to judge the reel against the brief."**

1. **Pack.** Grab the stills and write the reviewer's prompt, filled:

       "$VG" scripts.reel_review pack \
         --reel <run>/reels/<reel>/deliveries/REEL_v{n}.mp4 \
         --reel-dir <run>/reels/<reel> \
         [--intent "<the user's own words for the reel>"]

   Use the `REEL_v{n}.mp4` `montage status` names as latest. `pack` grabs the
   hook, the ending and one mid-frame per episode from the delivered file into
   `build/_review/` — every one clamped out of the reel's own bookend fade, which
   would otherwise darken a still by the picture's fade rather than by anything
   the `colour` axis should read as a grade — and writes
   `build/_review/reviewer_prompt.md`: the `reel-reviewer.md` template filled with
   `SPEC.md`/`SPEC.json` (or that there is no brief), `EDL.md`, `check_reel`'s
   report, the track and `PACING.md` (or that the reel is silent), the reel and the
   stills. The stills sit under `build/`, not the reel dir: they are scratch, stale
   the moment the reel is re-rendered, and `build/` is the one bucket the next
   render clears.

   With no `SPEC.json` (the autonomous path), pass `--intent` with what the user
   said they wanted, in their words — otherwise the reviewer has only the EDL to
   judge against, and the prompt says so.

   The report defaults to `build/reel/reel_report.json`, and `pack` refuses it
   when the reel's attestation names a different one — `build/` keeps only the
   LAST render's report, and a later render that stopped rewrites it. Review the
   reel the report passed, or re-deliver and review the new `REEL_v{n+1}`. `report_bound: false` in the
   result means the reel has no attestation at all: say so at CP3 — `deliver`
   did not attest it (its look gate refused it, or it was encoded by hand).

2. **Dispatch the reviewer subagent** (Task tool, `general-purpose`) with the
   contents of `build/_review/reviewer_prompt.md`, verbatim. Never fill or edit
   it by hand. It writes `<run>/reels/<reel>/review_findings.json` and returns.
   Do NOT review inline — the dispatch is the point (fresh, unanchored eyes).

3. **Validate + write.** Turn the raw findings into the typed artifact:

       "$VG" scripts.reel_review build \
         --findings <run>/reels/<reel>/review_findings.json \
         --reel <run>/reels/<reel>/deliveries/REEL_v{n}.mp4 \
         --spec <run>/reels/<reel>/SPEC.json --platform <platform> \
         --out-dir <run>/reels/<reel>

   The driver validates every finding (a malformed one raises — fix the reviewer's
   output and re-run; never hand-write `REVIEW.json`) and writes `REVIEW.json` +
   `REVIEW.md`. Then run `montage verify` and surface its `review` block beside
   them — report the state, and the `detail` whenever it reads anything but
   `bound`.

4. **Surface to the human — CP3.** Present `REVIEW.md` **beside** the reel and the
   `check_reel` report. Read back the verdict (approve / revise) and the findings.

5. **The human disposes.** For each finding the human chooses to act on, re-run the
   **routed** stage (the map below); it regenerates the reel (a new
   `REEL_v{n+1}.mp4`). Then **re-review** (step 1) — the loop ends when the human
   **approves** (verdict `approve`, or every remaining finding waived).

## Routing map (finding.route → the stage the human re-runs)

reel-review builds **no fixer** — each `route` names a stage that already exists:

| route | re-run | typical finding |
|-------|--------|-----------------|
| `edit-plan` | edit-plan SKILL (edit `selection.json`, rebuild `EDL`) | weak hook / weak ending / missing EDL element |
| `pacing` | pacing SKILL then `edit_plan build --pacing` | cuts drift off the energy spine |
| `music` | music-match / music-source SKILL | mood mismatch / wrong track |
| `reprocess` | process_episode on one episode (grade/layout redo) | one episode reads wrong vs the reel |
| `titles` | reel-brief `--text` (the literal words), then titles SKILL | the reel wants on-screen text, or its titles are mistimed/misplaced |
| `match-grade` | match-grade SKILL then `edl_to_reel` | one episode reads as a different grade from the rest |
| `none` | — (note only) | an observation to record, no action |
| `outro-length-chosen` | pacing SKILL — grow or re-cut the closing episode, then re-apply | a mechanical stop, not an editorial finding: the reel loop refused to absorb a within-band shortfall because the outro fit CHOSE this reel's length as `line + fade`; it will not silently move the fade off the bar line |

Same rule `using-montage` already applies to a mechanical `stop_and_report`:
"route it to the culprit stage's skill." reel-review extends it to editorial findings.

## Gate

The §5.13 editorial gate is the **human's CP3 sign-off** — never an automated
block. `REVIEW.json` records the reviewer's findings + verdict; the human approving
(or waiving) is what greens the stage.

## Boundaries

- **Human-gated (§4.1).** Nothing auto-fixes on these findings; the human picks and
  re-runs. `check_reel`/`build_reel`/`deliver`/loop-2 are untouched.
- **No trend axis.** `trend_flavor` was removed on 2026-10-20 together with trend
  scanning: it had no source, so it was judged blind. An older `REVIEW.json` that
  carries a `trend_flavor` finding still reads in `montage status`/`verify`, which
  read the file raw.
- **Judgement over plan + signals + stills, not full playback** — the reviewer says
  so in its `summary`.
- **One reviewer, one reel per run.** A multi-perspective panel and cross-reel
  comparison are deferred. You never hand-edit `REVIEW.json` — the driver
  regenerates it from the reviewer's findings.
