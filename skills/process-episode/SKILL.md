---
name: process-episode
description: "Per-episode worker — turn one approved EDL episode manifest into a checked, reframed clip at its chosen canvas and delivery (track -> reframe -> storyboard -> postcheck). Driven by edl_to_reel, one subagent per episode; not invoked directly. A per-episode worker under the episodes stage. Tool index: references/tools.md."
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
    "Editorial gate: read the storyboard (hand-driven only — dead in a router-driven run)" [shape=box];
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
    "status?" -> "Editorial gate: read the storyboard (hand-driven only — dead in a router-driven run)" [label="mechanical_pass"];
    "Editorial gate: read the storyboard (hand-driven only — dead in a router-driven run)" -> "Reads well AND right person?";
    "Reads well AND right person?" -> "Return stop_and_report (editorial)" [label="no"];
    "Reads well AND right person?" -> "Self-review, then return DONE + clip + report" [label="yes"];
}
```

Announce on entry: **"Using process-episode to process `<ep>`."**

**Launcher and references.** Run every pipeline step through the plugin's launcher
`bin/vg`, never a bare `python`, and resolve every `references/…` read the same
way. Claude Code writes this plugin's own directory into the line below when it
loads the skill, so resolve it once:

    ROOT="${CLAUDE_PLUGIN_ROOT}"
    VG="$ROOT/bin/vg"

If `ROOT` comes out empty — a harness that does not fill the line in — it is the
directory two levels above this skill's base directory. Then run every step as
`"$VG" scripts.X`, read every reference as `"$ROOT/references/…"`, and pass
**absolute** paths for every footage / run / output directory. Nothing here is
relative to your working directory — a skill runs from the user's footage
project. If `"$VG"` says there is no runtime, it has not been set up yet: run the
`setup` skill (`/video-grid:setup`), which asks before installing anything.

Run the orchestrator (never re-implement its loop in prose):

```bash
"$VG" scripts.process_episode <manifest.json> --project-dir <scratch> [--project <project.json>]
```

Pass `--project <project.json>` (written by project-init) so an episode manifest that omits `canvas`/`delivery` inherits them from the project. It also reads a `GATES.json` beside that file (if any) and judges the episode against the thresholds it moved, saying so on stderr — the same lookup `edl_to_reel` makes, so a hand-driven re-render is judged against the bar its siblings were — provided the file still matches what phase 1b froze: phase 2 and the delivery's attestation use the frozen set, not the live file, so check `montage status`'s `gates.frozen.state` first (`differs` means restore the file or re-run `--from-geometry`). With no `--project`, no gates are read and the episode is judged at the defaults, silently.

## Ask-before-start (§4.1)

Ask the user (or the dispatching orchestrator) a clarifying question ONLY when the manifest is genuinely under-determined in a way `validate()` cannot catch — e.g. the EDL prose says "the kid in red" but no `hero` pin was resolved and two children are plausible. Machine-checkable problems (bad composition, unsupported layout, an ffmpeg build missing `vidstabtransform` for a `stabilize=true` episode, `stabilize=true` combined with a supplied `--route`) come back as `needs_input` from the orchestrator with a precise message — relay that, do not re-derive it. Never ask mid-encode; never guess.

## Stop-and-report (§4.1: no improvising past the manifest)

When the orchestrator returns `stop_and_report`, the tracker's reality contradicts the brief (declared motion reversed; hero ambiguous with no pin; empty track). Return the finding verbatim to the orchestrator — the answer is a manifest edit (a `hero` pin, a corrected `motion`, a better model), not a workaround you invent. When it returns `escalate`, the fault is upstream — pass the `escalate_to` + `fail_reasons` up. Usually that means the same failure survived the retry budget and the culprit is the episode's window/composition in the EDL. One reason escalates on attempt 1 instead, with no retry at all: `grade-damage` (`check_episode`'s `grade_damage` — the declared grade rendered against an identity twin of itself and found to have DESTROYED information, an entropy-ratio floor a legitimate grade does not cross), because no reframe parameter can move a colour. Its culprit is the episode's colour block. (Before 2026-08-29 a driver-supplied `color_correct` could also be the cause, since `build_reel`'s retired convergence loop pulled a delivered episode toward a reel-wide target after the fact — that pull no longer exists, so the EDL's own colour block is the only source of a `grade-damage` finding now.) Read the `reason`, not just the `escalate_to`. Fixing forward is banned: a bad crop is never masked downstream.

## Editorial gate (the half the orchestrator cannot do)

**This gate is real only when you are driving ONE episode by hand** —
debugging, a one-off re-render, anything outside the conveyor. A
router-driven run never reaches it: `edl_to_reel` calls
`process_episode.process_episode` as a bare Python function inside its
thread pool, not through this SKILL and not through any subagent — nothing
in a conveyor run reads the storyboard at this point (design
docs/specs/2026-08-08-episode-qc-design.md §0). The per-episode judgment for
a conveyor run is a separate, later stage: **`episode-qc`**, which packs an
evidence directory per already-delivered clip (this same storyboard, plus a
frame strip of the shipped pixels and a colour-naturalness reading) and
dispatches a fresh judge against it, one per episode, after every episode is
rendered and before the reel is assembled — see the `episode-qc` SKILL. If
you are looking for where the conveyor judges an episode, it is not here.

When you ARE driving one episode by hand, on `mechanical_pass` open the
returned storyboard (`result["storyboard"]`) and judge, at the episode's
declared intent (not a global rule):
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

## Boundaries

**You may not disable, lower, or downgrade any quality gate.** A gate that
blocks is routed back to its stage's skill (here: `stop_and_report` /
`escalate`, upstream to the EDL), never loosened to pass. The thresholds move in
exactly one place, and it is not this skill's: a `GATES.json` beside
`project.json` — the operator's file, every entry carrying a written reason and
refused at load without one — which `--project` makes this invocation read (above)
so that a hand-driven re-render is judged against the bar its siblings were —
provided the file still matches what phase 1b froze (check `montage status`'s
`gates.frozen.state` first; on `differs`, re-run phase 1b rather than editing the file).
That is a lookup and not a lever you hold: never write or edit one to make a failing
episode pass. Any bar it moved is named beside the verdict, and in the delivery's
attestation only when phase 1b froze it.
A reel-level check's threshold belongs to `edl_to_reel`, which reads the same file;
no CLI flag exposes one (the last, `--color-delta-max`, was retired with the check it
bounded, 2026-08-29). A per-episode worker never reaches for either to make a failing
episode pass.

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
- Composition/grid math and the follow algorithm: `"$ROOT/references/editing-canon.md"` (video-grid:editing-canon).
- ffmpeg command shapes: `"$ROOT/references/ffmpeg-recipes.md"`. The banned-filter list is design §12 (`"$ROOT/references/landmines.md"` points at it); four entries are machine-checked by `scripts/lib/lint.py` and refused by `proc.run`, so a violating command raises instead of rendering.
- Escalation ladder and the three user-facing checkpoints: design §4.1.
