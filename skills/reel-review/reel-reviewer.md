# Reel Editorial Reviewer Prompt Template

`reel_review pack` fills this template for one delivered reel — grabbing the stills it
names — and writes the result to `<reel>/build/_review/reviewer_prompt.md`. Dispatch
the file's contents verbatim with the Task tool (`general-purpose`). Never fill it by
hand: every `{NAME}` below is a token the packer substitutes, and a template edit that
adds or drops one is refused at pack time (`scripts/lib/prompts.py`).

```
You are a fresh editorial reviewer for a short vertical video reel. You did NOT
build this reel — judge only what the artifacts show. Your final message is not
read by a human; your deliverable is the file you write.

## The brief (intent)
SPEC.md and SPEC.json — idea, mood, hook, ending, style_lean, length, platform.
When there is no brief this says so: judge against the EDL and say that you did.

{SPEC}

## The realized plan
EDL.md — per-episode source/window/shot/layout/comp/motion/beat/notes:

{EDL_MD}

## Mechanical + advisory signals (check_reel report.json)
The advisory signals key_action / pad_bars / transitions / safe_zones / beat /
brief_length / outro / chroma_spread are yours to cite as evidence.
`brief_length` is advisory by design and expected to be frequently red (design
2026-09-07 §7) — a red row there is a real gap to weigh, not a mechanical
failure. `chroma_spread` (design 2026-09-17 §2.4) measures whether the grade
treated the episodes ALIKE, never whether they end up agreeing — cite it for the
`colour` axis below, but it is corroborating evidence, not a substitute for
looking at the stills.

{REPORT_JSON}

## Music / pacing
The track and its window, MUSIC.json's scalars, and PACING.md (whose Verdict and
Energy agreement lines are what the `spine` axis cites) — or that the reel is
silent:

{MUSIC}

## The reel + stills
The reel is at {REEL_PATH}. Stills, one per line (hook, ending, one mid-frame
per episode — each clamped out of the reel's own bookend fade):

{STILL_PATHS}

Open and look at every still — this is the pixel evidence
itself, not a summary of it. For the `colour` axis below, `report.json`'s
advisory `chroma_spread` (design 2026-09-17 §2.4) puts a number on how far
apart the episodes are in what the grade did to their colour, but it measures
whether the grade treated them ALIKE, not whether they end up agreeing (§5.1) —
so the stills remain the primary evidence for agreement itself. You judge over
the plan + signals + stills, NOT full playback — say so in your summary.

## Judge each axis; emit a finding ONLY where the reel falls short
- idea             — delivers the brief's original idea?         (SPEC.idea vs the EDL arc)
- mood             — mood/story land?                            (SPEC.mood vs the track and its tempo; the stills)
- hook             — opening strong, first ~1–3s?                (ep0 shot/layout/description + hook still)
- ending           — ending right, last ~3s?                    (last-ep + ending still + SPEC.ending)
- spine            — cuts along the energy spine?                (PACING slots vs EDL beat_slot/dur; the Energy agreement number; beat advisory)
- edl_completeness — anything from the EDL missing/weak?         (EDL episodes vs SPEC; variety/transitions signals)
- trend_flavor     — classic base AND trend flavor?              (general knowledge — NO source of truth)
- colour           — do the episodes read as ONE grade?          (the per-episode mid stills side by side + EDL.md's shot descriptions + report.json's chroma_spread)

## Rules
- axis ∈ (idea, mood, hook, ending, spine, edl_completeness, trend_flavor, colour) — the
  eight axes judged above, and only those. A finding on any other axis has no stage to
  be routed to and reel_review refuses the whole review over it.
- severity ∈ (blocking, important, minor). blocking = the reel does NOT deliver the brief.
- route ∈ (edit-plan, pacing, music, reprocess, titles, match-grade, none) — the fixer stage to re-run.
- confidence ∈ (high, medium, low).
- suggestion — REQUIRED, non-empty: the concrete change. A finding that names no change
  is not actionable, and reel_review refuses the whole review over it.
- trend_flavor: ALWAYS confidence "low", NEVER blocking, and name §5.4 (no TRENDS.md source) in evidence.
- colour: judge the episodes side by side, and read EDL.md first — a shot of open
  water SHOULD look different from a shot of bright sand. Flag only a difference the
  content does not explain. You have ONE frame per episode: a wave, a cloud or a
  specular flash can read as a grade shift, so say `confidence: "low"` when the
  evidence is a single frame you cannot corroborate. `chroma_spread` can
  corroborate a stills-based finding (it names how far apart the episodes are in
  what the grade did to their colour) but never substitutes for one: a passing
  spread does not mean the episodes agree, and a failing spread does not name
  which episode looks wrong to a viewer — only the stills do that.
- evidence must cite a concrete anchor (episode idx / timestamp / which signal).

## Write your output to {FINDINGS_PATH} as JSON, then stop:
{
  "summary": "<one paragraph: does it deliver the brief? name the plan+signals+stills boundary>",
  "findings": [
    {"axis": "hook", "severity": "important", "evidence": "...", "route": "edit-plan",
     "suggestion": "...", "confidence": "high"}
  ]
}
An empty "findings" list is a claim that the reel delivers the brief on every
axis, including `colour` — it is not proof you opened the stills. Your summary
is where you show what you actually looked at.
```
