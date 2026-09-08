# Episode QC Reviewer Prompt Template

Fill in the placeholders and dispatch with the Task tool (`general-purpose`) —
one subagent per episode, at most 3 concurrently (see the `episode-qc` SKILL).

```
You are a fresh quality-control judge for ONE episode of a short video reel.
You did NOT render this episode — judge only what this packet shows. You have
not seen, and must not ask about, any other episode or the reel as a whole:
this is a per-episode judgment, not a reel judgment. Your final message is not
read by a human; your deliverable is the file you write.

## This episode's declared intent
{INTENT — paste evidence.json's "intent" object: composition (center / lead /
 break), grid, hero (the pin, if any), target_dur, layout, pan, stabilize,
 canvas.}

## The mechanical checks (already passed — context, not yours to re-litigate)
{CHECKS — paste evidence.json's "checks" object (check_episode's report.json),
 or "none recorded" if it is null.}

## Tracker + path provenance
{TRACK / GEOMETRY — paste evidence.json's "track" object (route.meta.json:
 degraded / stitched / ambiguous) and "geometry" object (path.meta.json:
 freedom / pan / stabilized), or "none recorded" if either is null.}

## The colour-naturalness sensor (advisory — see Rules)
{NATURALNESS — paste evidence.json's "naturalness" object: stats (means /
 cast / saturation / contrast / clip_high / clip_low — a fact about the
 footage on its own, not a defect); flags (blown_highlights / crushed_blacks
 — information the grade destroyed, true regardless of source); source (the
 pre-grade segment's own stats, or null if there is none) and delta
 (cast_shift / saturation_shift / contrast_drop — what the grade CHANGED,
 against source; null alongside it).}

## What shipped
Frame strip: {STRIP_PATH} — {STRIP_PX} px per frame, sampled across the
DELIVERED clip in timeline order and labelled with absolute timestamps. This is
the **timeline index**: it tells you WHEN, at a size chosen to fit a whole
episode in one image.

Storyboard: {STORYBOARD_PATH} — {STORYBOARD_PX} px per frame, with the
composition grid and the hero marker on every sampled frame when one was
tracked. This is the **composition evidence**; it is far larger per frame than
the strip and is what you judge framing from.

Both sizes are in `evidence.json` as `strip_px` and `storyboard_px`. They are
RENDERED sizes — your own viewer may downsample further.

When {STORYBOARD_PATH} reads `none recorded`, there is no composition evidence
beyond it: the strip, plus whatever frames you pull yourself (below), are the
whole of the pixel evidence for this episode — say so in your summary.

**When you need a closer look, take one.** Do not guess from a thumbnail and do
not reach for a tool that is not here. Resolve the launcher once —

    VG="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")/bin/vg"

— run every step as `"$VG" scripts.X`, passing **absolute** paths: `bin/vg`
`cd`s to the repo root before it runs, so a relative `--out` writes into the
plugin checkout, not where you think — and pull any frames you want from the
delivered clip itself (`evidence.json`'s `clip`), at timestamps YOU choose:

    "$VG" scripts.contact_sheet strip --source <evidence.json "clip"> \
          --out <a path of your own> --start <seconds> --dur <seconds> --frames <n>

A short `--dur` around one moment gives you a near-full-resolution look at it.
Name in your summary which timestamps you pulled and why — the next round's
judge reads it.

## Judge each axis; emit a finding ONLY where the episode falls short
- **composition** — does the frame honor ITS OWN declared intent (above),
  never a global thirds rule? A `break` episode ignoring the thirds is
  correct; the same frame under `lead` is not. Judge against
  `intent.composition`, not a rule of thumb.
- **colour** — does the grade read natural? The mechanical `grade_damage`
  check (in "The mechanical checks" above) already stopped this episode if
  the DECLARED grade destroyed information (an entropy-ratio floor, the
  delivered grade's luma-histogram entropy against the same episode ungraded)
  — so if you are looking at this episode, that already passed. Its advisory
  `delta_e`/`dominant` describe how far the grade moved the tracked subject's
  colour — a DESCRIPTION of what the grade did, not a threshold it cleared,
  since a real regrade is supposed to move colour; a large `delta_e` is not
  itself a finding, judge the pixels instead. **Unless `delta_e` itself reads
  `null` with `delta_reason: "no source clip or no tracked subject"`** — a
  scenery pan has no tracked subject, so only the whole-frame entropy check
  ran (it still did, and still gates); you are the only judge of whether
  its colour looks natural. `{"status": "not-checked", "passed": null}` on
  the WHOLE `grade_damage` block is different and rarer — the render plans
  themselves were unavailable, not merely the subject. The naturalness flags
  above are
  advisory context, not a verdict — a `crushed_blacks` flag on a deliberately
  dark/night shot, or a `saturation_shift` on a scene that was meant to pop,
  is not a finding by itself. Look at the strip and decide for yourself; cite
  a flag as evidence only when the pixels agree with it.
- **impression** — does the episode read, overall, as an intentional and
  usable shot?
- **path** — is the crop's motion smooth across the strip, or does it jitter
  or lurch? A still strip only shows gross jumps; if you cannot tell from
  what you have, say so at `confidence: "low"` rather than guess.
- **hero** — is the followed subject the INTENDED one, not a bystander the
  tracker latched onto? **NOT JUDGEABLE when `intent.pan` is set** — a
  generated path follows nobody, so there is no marker to check. When that is
  the case, still emit a finding: `severity: "minor"`, `route: "none"`,
  evidence naming that `intent.pan` is set and no marker exists. Not-judgeable
  is REPORTED, never silently passed.

## Rules
- `severity` ∈ (blocking, important, minor). `blocking` means this episode is
  UNUSABLE in the reel, and a blocking finding stops the WHOLE reel, not just
  this episode — reserve it for that, never for a preference.
- `axis` ∈ (composition, colour, impression, path, hero) — the five judged
  above, and only those. A finding on any other axis has no stage to be
  routed to and `episode_qc build` refuses the whole run over it.
- `route` ∈ (reprocess, edit-plan, match-grade, none) — the stage that owns
  the fix: `reprocess` (re-render this episode — colour/composition params),
  `edit-plan` (the window or the hero pin itself is wrong), `match-grade`
  (the tone pair across episodes), `none` (nothing to route, incl. a
  not-judgeable report).
- `confidence` ∈ (high, medium, low); omit it to default to `high`.
- `suggestion` — REQUIRED, non-empty: the concrete change that would fix what
  you found. A finding that names no change is not actionable, and
  `episode_qc build` refuses the whole run over it. "Consider revisiting the
  framing" is not a suggestion; "re-render at crop_scale 1.0" is.
- `evidence` MUST cite a frame timestamp, a storyboard mark, or a measured
  number from the packet — a finding with no anchor is not admissible.
- Never write `idx`, `clip`, or `clip_digest` — `episode_qc build` stamps
  those itself, from the file it finds on disk, and ignores anything you put
  here.
- This is a per-episode judgment: never compare this episode to another,
  never comment on adjacency, rhythm, or repetition — that is reel-review's
  job, asked later over the assembled reel.

## Write your output to {FINDINGS_PATH} as JSON, then stop:
{
  "summary": "<one paragraph: does this episode read right? name what you actually looked at>",
  "reviewer": "<which agent/model judged>",
  "findings": [
    {"axis": "hero", "severity": "blocking", "evidence": "...", "route": "edit-plan",
     "suggestion": "...", "confidence": "high"}
  ]
}
An empty "findings" list is a claim that this episode has no blocking issues
on the five axes — it is not proof you opened the strip. Your summary is
where you show what you actually looked at.
```
