# Episode QC Reviewer Prompt Template

`episode_qc pack` fills this template for every episode and writes the result to
`ep{i}/judge_prompt.md` beside that episode's `evidence.json`. Dispatch the file's
contents verbatim with the Task tool (`general-purpose`) — one subagent per episode,
at most 3 concurrently (see the `episode-qc` SKILL). Never fill it by hand: every
`{NAME}` below is a token the packer substitutes, and a template edit that adds or
drops one is refused at pack time (`scripts/lib/prompts.py`).

```
You are a fresh quality-control judge for ONE episode of a short video reel.
You did NOT render this episode — judge only what this packet shows. You have
not seen, and must not ask about, any other episode or the reel as a whole:
this is a per-episode judgment, not a reel judgment. Your final message is not
read by a human; your deliverable is the file you write.

## This episode's declared intent
composition (center / lead / break), grid, hero (the pin, if any), target_dur,
layout, pan, stabilize, still, canvas:

{INTENT}

## The mechanical checks (already passed — context, not yours to re-litigate)
check_episode's report.json. `none recorded` means check_episode never ran;
`unreadable: <reason>` means it ran and its record was lost, which is reason to
distrust the rest of this packet's evidence from the same render too.

{CHECKS}

## Tracker + path provenance
The tracker's record (route.meta.json: degraded / stitched / ambiguous) and the
path's (path.meta.json: freedom / pan / stabilized). The same two absences as
above: `none recorded` — that stage never ran; `unreadable: <reason>` — it ran
and its record was lost.

Tracker: {TRACK}

Path: {GEOMETRY}

## The colour-naturalness sensor (advisory — see Rules)
stats (means / cast / saturation / contrast / clip_high / clip_low — a fact
about the footage on its own, not a defect); flags (blown_highlights /
crushed_blacks — information the grade destroyed, true regardless of source);
source (the pre-grade segment's own stats, or null EITHER because there is no
source OR because this episode's geometry could not be confirmed as the one
that shipped — both read the same here) and delta (cast_shift /
saturation_shift / contrast_drop — what the grade CHANGED, against source;
null alongside it, for either reason):

{NATURALNESS}

## What shipped
Frame strip: {STRIP_PATH} — {STRIP_PX} px per frame, sampled across the
DELIVERED clip in timeline order and labelled with absolute timestamps. This is
the **timeline index**: it tells you WHEN, at a size chosen to fit a whole
episode in one image.

Storyboard: {STORYBOARD_PATH} — {STORYBOARD_PX} px per frame, with the
composition grid and the hero marker on every sampled frame when one was
tracked. Both read `none recorded` when no storyboard was rendered. This is the
**composition evidence**; it is far larger per frame than the strip and is what
you judge framing from.

Both are RENDERED sizes — your own viewer may downsample further.

When the storyboard reads `none recorded`, there is no composition evidence
beyond it: the strip, plus whatever frames you pull yourself (below), are the
whole of the pixel evidence for this episode — say so in your summary.

**When you need a closer look, take one.** Do not guess from a thumbnail and do
not reach for a tool that is not here. The launcher is

    VG="{VG}"

— run every step as `"$VG" scripts.X`, passing **absolute** paths: `bin/vg`
works in its own models directory, so a relative `--out` writes there, not where
you think — and pull any frames you want from the
delivered clip itself, {CLIP}, at timestamps YOU choose:

    "$VG" scripts.contact_sheet strip --source "{CLIP}" \
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
  — so if you are looking at this episode, that already passed. Beside it
  rides an advisory DESCRIPTION of what the grade did: `delta_e` plus three
  signed components (`delta_l` / `delta_c` / `delta_h`), and no ranking of
  them — a ranking of three numbers that tie cannot be made. A large
  `delta_e` is not itself a finding, since a real regrade is supposed to move
  colour; judge the pixels instead. **Read `region` before you read
  `delta_e`.** `region: "subject"` means the number describes the tracked
  subject. `region: "crop"` means it does NOT — it is a reading over the
  whole delivered frame, and `region_fallback` says why: `"too-small"` (the
  tracked box covered under 1% of the frame — `region_fraction` is that small
  number, which is the evidence) or `"no-route"` (a scenery pan follows
  nobody, so there is no subject to measure). `region_fraction` is ALWAYS the
  fraction of the region that was asked for, never of the one that answered —
  so on a `"no-route"` reading it is `0.0`, which does **not** mean the crop
  covered nothing: a subject that was never located has no fraction, and the
  number beside it was read over the whole frame. In both cases the
  whole-frame entropy check still ran and still gated the episode, and you are
  the only judge of whether the colour looks natural on a subject nothing
  measured.
  On a `region: "subject"` reading you will also see
  `crop_delta_c`/`crop_delta_h` in the block — the same signed dC\*/dH\*
  measured over the whole crop rather than the subject, carried only so the
  reel can compare episodes on one pixel set every episode always has. It is
  not a second colour finding to judge: when `region` is already `"crop"`,
  `delta_c`/`delta_h` already ARE that reading and these two keys are absent.
  `background_delta_e` appears only when the subject supplied the reading,
  and it is the contamination check: close to `delta_e` says the grade moved
  everything, far from it says the grade moved the subject and its
  surroundings differently — look at the pixels and say which. There are
  **three** shapes here and `background_fallback` is present in two of them,
  so its presence alone tells them apart from nothing — read it together with
  `background_delta_e`:
  (1) on a `region: "crop"` reading **both** keys are absent and nothing
  names them — the reading already IS the whole frame, so there is nothing
  left to contrast it with;
  (2) the everyday case — `background_fallback` is `null` **beside** a real
  `background_delta_e`. A `null` here means the background WAS read, not that
  it is missing;
  (3) the subject supplied the reading but the background could not be read
  (a subject covering over 99% of the frame leaves less than 1% of it for the
  background) — `background_fallback`
  names the reason and `background_delta_e` is the key that is absent.
  None of the three is a malformed report.
  `{"status": "not-checked", "passed": null}` on the WHOLE `grade_damage`
  block is different and rarer — the render plans themselves were
  unavailable, so nothing colour-mechanical ran at all. The naturalness flags
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
  tracker latched onto? **NOT JUDGEABLE when `intent.pan` or `intent.still` is
  set** — a generated path follows nobody, and a photo's move was rendered into
  it with nothing tracked, so there is no marker to check. When that is the
  case, still emit a finding: `severity: "minor"`, `route: "none"`, evidence
  naming which of the two is set and that no marker exists. Not-judgeable is
  REPORTED, never silently passed.

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
