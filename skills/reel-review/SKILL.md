---
name: reel-review
description: Conveyor stage — the reel's final editorial review. using-montage invokes this at checkpoint CP3, after edl_to_reel delivers <run>/reels/<reel>/deliveries/REEL_v{n}.mp4, to judge whether the reel delivers SPEC's idea/mood/hook/ending/spine. Dispatch a fresh reviewer subagent, validate its findings into REVIEW.json + REVIEW.md, surface them beside the reel, and route the ones the human picks to the fixer stage (edit-plan/pacing/music). Human-gated — the reviewer proposes, the human disposes. Optional — a final quality pass.
---

# reel-review (stage 5.13, editorial half)

## Overview

The **final editorial gate**. `check_reel` already judged the reel *mechanically*
(black/loudness/colour/variety/length + the advisory safe_zones/key_action/
pad_bars/transitions/beat). reel-review judges it *editorially*: does it deliver
the brief? This is the `requesting-code-review` pattern one level up — you
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

## Inputs (the context packet — resolve paths under the run dir)

- **`<run>/reels/<reel>/deliveries/REEL_v{n}.mp4`** (required) — the delivered reel.
- **`report.json`** (required) — `check_reel`'s report: the mechanical gates + the
  **Slice A advisory signals** (`key_action`/`pad_bars`/`transitions`/`safe_zones`/
  `beat`) the reviewer cites as evidence.
- **`SPEC.json`** (optional) — the brief's intent. Absent (a bare autonomous run) →
  review against the `EDL` + the run's stated intent; say so.
- **`EDL.md`** (required) — the realized plan (per-episode source/window/shot/
  layout/comp/motion/beat/notes).
- **`MUSIC.json` / `PACING.json`** (optional) — the mood target + energy spine.

## Procedure

Announce on entry: **"Using reel-review to judge the reel against the brief."**

1. **Build the packet.** Resolve the paths above. Grab a cheap **thumbnail
   contact-sheet** to ground visual judgement (output-seek — `-ss` AFTER `-i`,
   design §12): the hook frame, the ending frame, and one mid-frame per episode.
   Example (hook + ending stills; add per-episode mids from the EDL cut times):

       ffmpeg -y -i <run>/reels/<reel>/deliveries/REEL_v1.mp4 -ss 0.5 -frames:v 1 <run>/reels/<reel>/_review/hook.png
       ffmpeg -y -i <run>/reels/<reel>/deliveries/REEL_v1.mp4 -ss "$(python -c 'print(DUR-1)')" -frames:v 1 <run>/reels/<reel>/_review/ending.png

2. **Dispatch the reviewer subagent** (Task tool, `general-purpose`) with the
   `reel-reviewer.md` template filled in — the packet paths + the axes/questions +
   the required output shape. It writes `<run>/reels/<reel>/review_findings.json` and returns.
   Do NOT review inline — the dispatch is the point (fresh, unanchored eyes).

3. **Validate + write.** Turn the raw findings into the typed artifact:

       python -m scripts.reel_review build \
         --findings <run>/reels/<reel>/review_findings.json \
         --reel <run>/reels/<reel>/deliveries/REEL_v{n}.mp4 \
         --spec <run>/reels/<reel>/SPEC.json --platform <platform> \
         --out-dir <run>/reels/<reel>

   The driver validates every finding (a malformed one raises — fix the reviewer's
   output and re-run; never hand-write `REVIEW.json`) and writes `REVIEW.json` +
   `REVIEW.md`.

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
| `edit-plan` | edit-plan SKILL (edit `selection.json`, rebuild `EDL`) | weak hook / weak ending / missing EDL element / classic↔trend lean |
| `pacing` | pacing SKILL then `edit_plan build --pacing` | cuts drift off the energy spine |
| `music` | music-match / music-source SKILL | mood mismatch / wrong track |
| `reprocess` | process_episode on one episode (grade/layout redo) | one episode reads wrong vs the reel |
| `titles` | titles SKILL | hook/ending wants on-screen text |
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
- **`trend_flavor` has no source of truth until §5.4 trend-scan.** The reviewer
  judges it from general knowledge at forced `confidence: low`, never `blocking`,
  and names §5.4 in the evidence.
- **Judgement over plan + signals + stills, not full playback** — the reviewer says
  so in its `summary`.
- **One reviewer, one reel per run.** A multi-perspective panel and cross-reel
  comparison are deferred. You never hand-edit `REVIEW.json` — the driver
  regenerates it from the reviewer's findings.
