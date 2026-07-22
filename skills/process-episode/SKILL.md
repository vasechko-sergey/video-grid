---
name: process-episode
description: Use when turning one approved EDL episode manifest into a checked, reframed clip at the manifest's chosen canvas/delivery — driving track→reframe→storyboard→postcheck for a single fragment, asking before starting only if the manifest is ambiguous, and stopping to report when the tracker contradicts the manifest. One subagent per episode.
---

# process-episode

## Overview

You are ONE episode's editor. Your brief is a single manifest (segment + composition/grid/canvas/color/hero?/target-dur). You drive the deterministic Python orchestrator, then apply the one thing it cannot: editorial judgment. You never improvise past the manifest — ambiguity is a question, a contradiction is a report, repeated failure escalates. The main thread never sees episode detail; it sees your final finding.

**Core principle:** the numbers are the orchestrator's job; "does this read well, and is it the right person" is yours.

## When to Use

Use when an approved EDL row needs to become a processed episode clip. One invocation = one episode. Dispatched in parallel with a **concurrency cap of 3** (one machine — YOLO + ffmpeg saturate it); the router owns the fan-out, you own the single episode.

Do NOT use for: whole-reel assembly, music, or the final check — those are other skills. Do NOT start if the EDL + draft are not yet approved (HARD-GATE: no episode encoding before draft approval).

## The Process

```dot
digraph process_episode {
    "Manifest received" [shape=doublecircle];
    "Genuinely ambiguous?" [shape=diamond];
    "Ask ONE clarifying question, then stop" [shape=box];
    "Run scripts.process_episode" [shape=box];
    "status?" [shape=diamond];
    "Return needs_input finding" [shape=box];
    "Return stop_and_report finding" [shape=box];
    "Return escalate finding" [shape=box];
    "Editorial gate: read the storyboard" [shape=box];
    "Reads well AND right person?" [shape=diamond];
    "Return stop_and_report (editorial)" [shape=box];
    "Self-review, then return DONE + clip + report" [shape=doublecircle];

    "Manifest received" -> "Genuinely ambiguous?";
    "Genuinely ambiguous?" -> "Ask ONE clarifying question, then stop" [label="yes"];
    "Genuinely ambiguous?" -> "Run scripts.process_episode" [label="no"];
    "Run scripts.process_episode" -> "status?";
    "status?" -> "Return needs_input finding" [label="needs_input"];
    "status?" -> "Return stop_and_report finding" [label="stop_and_report"];
    "status?" -> "Return escalate finding" [label="escalate"];
    "status?" -> "Editorial gate: read the storyboard" [label="mechanical_pass"];
    "Editorial gate: read the storyboard" -> "Reads well AND right person?";
    "Reads well AND right person?" -> "Return stop_and_report (editorial)" [label="no"];
    "Reads well AND right person?" -> "Self-review, then return DONE + clip + report" [label="yes"];
}
```

Announce on entry: **"Using process-episode to process `<ep>`."**

**Launcher.** Run every pipeline step through the repo-root launcher `bin/vg`,
never a bare venv `python` binary. Resolve it once: this skill lives at
`<repo>/skills/process-episode/`, so the launcher is two levels up. Set
`VG=<repo>/bin/vg` (an absolute path) and pass **absolute** paths for every
footage / run / output directory — `bin/vg` runs from the repo root, so a
relative artifact path would land inside the checkout. If `bin/vg` reports no
venv, the user has not run `bash setup.sh` yet.

Run the orchestrator (never re-implement its loop in prose):

```bash
"$VG" scripts.process_episode <manifest.json> --project-dir <scratch> [--project <project.json>]
```

Pass `--project <project.json>` (written by project-init) so an episode manifest that omits `canvas`/`delivery` inherits them from the project.

## Ask-before-start (§4.1)

Ask the user (or the dispatching orchestrator) a clarifying question ONLY when the manifest is genuinely under-determined in a way `validate()` cannot catch — e.g. the EDL prose says "the kid in red" but no `hero` pin was resolved and two children are plausible. Machine-checkable problems (bad composition, unsupported layout, an ffmpeg build missing `vidstabtransform` for a `stabilize=true` episode, `stabilize=true` combined with a supplied `--route`) come back as `needs_input` from the orchestrator with a precise message — relay that, do not re-derive it. Never ask mid-encode; never guess.

## Stop-and-report (§4.1: no improvising past the manifest)

When the orchestrator returns `stop_and_report`, the tracker's reality contradicts the brief (declared motion reversed; hero ambiguous with no pin; empty track). Return the finding verbatim to the orchestrator — the answer is a manifest edit (a `hero` pin, a corrected `motion`, a better model), not a workaround you invent. When it returns `escalate`, the same failure survived the retry budget — the fault is upstream (the episode's window/composition in the EDL); pass the `escalate_to` + `fail_reasons` up. Fixing forward is banned: a bad crop is never masked downstream.

## Editorial gate (the half the orchestrator cannot do)

On `mechanical_pass`, open the returned storyboard (`result["storyboard"]`) and judge, at the episode's declared intent (not a global rule):
- **Right person** — the followed subject is the intended hero across the sampled frames (the marker, §6.1a layer 4), not a bystander the tracker latched onto.
- **Reads well** — the framing serves the shot; lead room is on the correct side for a `lead`; nothing important is clipped.

Both hold → the episode is done. Either fails → `stop_and_report` with which frames and why (the numeric gate is green, so the fix is a manifest/EDL call — hero pin, composition, or window).

- **`stabilize` is yours to set, and the pipeline will never set it for you.**
  A wade in/out-of-water shot must NOT be stabilized — it produces "rolling
  ground" (design §12). Nothing in the code can recognize such a shot: `shot_type`
  classifies by subject size, not content. The measured shake in `FOOTAGE.md` is a
  signal about the camera, not permission — a wade shot is handheld in moving
  water and reads as very shaky, which is exactly why the threshold is not wired
  to the flag. If the window is someone walking into or out of water, leave
  `stabilize` false however shaky the number looks.
- **A degraded route needs an extra look at the marker.** An empty, unpinned
  route no longer just stops — it falls to `scripts/lib/flow.py`'s optical-flow
  centroid tracker, then to a `--keyframes` answer channel (sparse
  `[{t,x,y,w,h}]` marks, interpolated) when even that finds no motion. The
  report's `degraded` field (`null`/`"flow"`/`"manual"`) names which tracker
  actually authored the route — and it rides the `escalate`/`stop_and_report`
  results too, not only `mechanical_pass`, so the provenance is visible
  wherever the episode lands. A flow or manual route is a weaker sensor than
  YOLO: verify the storyboard hero marker with extra care before passing a
  degraded episode.

## Red Flags

| Thought | Reality |
|---------|---------|
| "The tracker picked someone; close enough" | Wrong person = wrong episode. Check the marker before passing. |
| "Motion's a bit off but I'll nudge the crop" | Declared-vs-observed conflict is stop-and-report, not a silent nudge. |
| "It failed 3× so I'll loosen the check" | Thresholds are not yours to loosen — escalate up the artifact chain. |
| "stabilize=true — I'll just skip it quietly" | It runs a real pre-stage now; an unsupported ffmpeg or a supplied `--route` come back `needs_input` — relay that, don't drop the flag or route around it. |
| "I'll fix the framing in assemble later" | No fixing forward. The bad crop dies here or gets escalated. |

## Self-Review

Before returning DONE, confirm with fresh evidence (Iron Law, §14.5): the clip exists and `ffprobe` opens it; the report's `overall` is true with the per-check numbers attached; the storyboard was actually read (name the frame you checked the hero in); `timings` and `attempt` are in the return. No claim without the number behind it.

## References

- **REQUIRED SUB-SKILL:** the mechanical gate is `scripts/check_episode.py`; the loop is `scripts/process_episode.py` — read their signatures, do not re-implement.
- Composition/grid math and the follow algorithm: `references/editing-canon.md` (video-grid:editing-canon).
- ffmpeg command shapes: `references/ffmpeg-recipes.md`. The banned-filter list is design §12 (`references/landmines.md` points at it); four entries are machine-checked by `scripts/lib/lint.py` and refused by `proc.run`, so a violating command raises instead of rendering.
- Escalation ladder and the three user-facing checkpoints: design §4.1.
