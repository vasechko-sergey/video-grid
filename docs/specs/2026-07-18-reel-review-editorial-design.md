# Reel-review — the §5.13 editorial half (Slice B) (design)

**Related:** montage §5.13 `reel-final-check` — the gate this **closes** (its
mechanical half shipped 2026-07-16 `safe_zones` + 2026-07-17 the `key_action`/
`pad_bars`/`transitions` trio, see
`docs/specs/2026-07-17-reel-final-editorial-checks-design.md`; this is **Slice
B**, the agent editorial review that half named as its follow-on).
`superpowers:requesting-code-review` (the model this calques — a SKILL that
dispatches a reviewer subagent with crafted context, acts on findings). The
`reel-brief` spine (`scripts/lib/spec.py` + `scripts/reel_brief.py` +
`SKILLS/reel-brief/`, design `docs/specs/2026-07-12-reel-brief-design.md`) — the
**structural twin**: a typed judgment artifact written by a thin driver, a text
stage with no ffmpeg golden. `using-montage` §5.1 Checkpoint 3 (the human gate
this plugs into). `edit_plan.py`'s `selection.json → EDL.json` (the
agent-authors-raw-JSON → driver-validates-and-writes idiom reused here).

**Intent:** build the **agent editorial review** — the second half of §5.13,
the last part of the stage still open. At the final checkpoint (§4.1 CP3), a
fresh **reviewer subagent** judges the delivered reel against the brief: does it
deliver `SPEC`'s original idea? mood/story? hook strong? ending right? pacing
along the spine? anything from the `EDL` missing/weak? classic base **and** trend
flavor (not bland, not gimmicky)? It emits typed **findings**, each with a
suggested **route** to an existing fixer stage; a thin driver validates and
writes `REVIEW.json` + `REVIEW.md`; the conductor surfaces them beside the reel;
the **human** picks what to act on, re-runs the routed stage, and re-reviews.
Reviewer proposes, human disposes — CP3 stays a human gate (§4.1). Closing this
flips **§5.13 ◐ → ✅** (both parts green); pipeline tally becomes **15 ✅ · 0 ◐ ·
1 ❌** (the ❌ is §5.4 trend-scan).

## Scope decisions (locked in brainstorming)

- **Human-gated fix loop, not autonomous.** §5.13's "findings → fix loop →
  re-check" runs through the human: the reviewer emits findings + a suggested
  route per finding, the human picks which to act on, the conductor re-runs that
  stage (`edit-plan` / `pacing` / `music` / a `reprocess`), then re-reviews. No
  new automation on the editorial axis — CP3 is one of the two checkpoints §4.1
  keeps human **by design**. (`overall` / `reel_orchestration` / `build_reel` /
  loop-2 are untouched — the reel-orchestration ladder auto-fixes only the
  **mechanical** `black`/`color_across_cuts` faults; editorial judgement never
  drove it and still does not.)
- **Typed `REVIEW.json` + `REVIEW.md`, not ephemeral prose.** Findings are a
  first-class artifact, matching the repo's typed-contract spine (`SPEC`/`EDL`/
  `TITLES`/`ReelReport` all have one). A `Finding` + `Review` config-spec, a thin
  writer, an optional `montage.py` Stage. Machine-routable (each finding names a
  fixer), resumable (a `REVIEW.json` on disk marks the reel reviewed), and it
  sits naturally beside `check_reel`'s `report.json`. The reviewer authors **raw**
  findings JSON; a typed driver validates it (fail-loud on a malformed finding)
  and renders the human-facing `.md` — the `selection.json → EDL.json` idiom, so
  writing stays in typed Python, never in the agent's free text.
- **Dispatched reviewer subagent, not the inline conductor.** The conductor
  **built** the reel — it is anchored on its own edit, the exact bias
  `requesting-code-review` exists to remove. A fresh subagent gets a **crafted**
  context packet (SPEC + EDL + reel + `check_reel` report + Slice A's advisory
  signals), never the conductor's history, and returns findings. Fresh,
  unanchored eyes; the conductor's context is preserved for the fix loop.
- **The reviewer reasons over artifacts + a few stills, and says so.** Its
  primary evidence is the **plan-vs-intent** delta (`SPEC` intent vs the `EDL`'s
  realized per-episode plan) plus the mechanical + Slice A advisory signals from
  `report.json`; it *may* pull a cheap thumbnail contact-sheet (hook frame,
  ending frame, per-episode mids) to ground visual judgements. It is **honest**
  that this is judgement over plan + signals + stills, not full playback — the
  same "wiring, not pixels" honesty the repo's goldens carry. Real motion/timing
  it cannot watch, it infers from the signals that *do* measure it (`beat`
  advisory for cuts-on-beat, `PACING.json` for the energy spine, `MUSIC.json`
  `mood_features` for mood).
- **No new fixer, no new CLI surface downstream.** Every `route` names a stage
  that **already exists** (`edit-plan`, `pacing`, `music-*`, a `process_episode`
  reprocess, `titles`). Slice B produces the finding that tells the human *which*
  to re-run; it builds none of them. The only new CLI is `reel_review build`
  (raw findings → `REVIEW.json`+`.md`), mirroring `reel_brief`/`edit_plan build`.

## §1 Architecture

Everything Slice B needs is already on disk after a run reaches CP3: the brief,
the realized plan, the mechanical report (which already carries Slice A's
advisory signals), and the delivered reel.

```
context packet (crafted, NOT conductor history)
  SPEC.json         intent — idea/mood/hook/ending/style_lean/length/platform
  EDL.md            realized plan — per-ep source/window/shot/layout/comp/motion/beat/notes
  report.json       check_reel — mechanical gates + Slice A advisory signals
                    (key_action / pad_bars / transitions / safe_zones / beat)
  MUSIC.json        mood target + energy curve   (when present)
  PACING.json       the beat-aligned energy spine (when present)
  out/REEL_v{n}.mp4 the reel + a thumbnail contact-sheet (ffmpeg stills)
        │
        ▼   SKILLS/reel-review  — dispatch a fresh reviewer subagent (reel-reviewer.md template)
  reviewer subagent → review_findings.json   (raw: [{axis,severity,evidence,route,suggestion,confidence}], +summary)
        │
        ▼   scripts/reel_review.py — build_review(raw) validates → Review, write_review → REVIEW.json + REVIEW.md
  REVIEW.json / REVIEW.md
        │
        ▼   using-montage CP3 — surface REVIEW.md + the reel to the HUMAN
  human picks findings → re-run the routed stage → re-deliver → re-review (new round)
                                    ── until the human approves ──
```

New units:

| Unit | Role | Sibling it mirrors |
|------|------|--------------------|
| `scripts/lib/review.py` | `Finding` + `Review` config-specs; `REVIEW_AXES`/`REVIEW_SEVERITY`/`REVIEW_ROUTES`/`REVIEW_CONFIDENCE` vocabs; `Review.verdict` property; `Review.to_markdown`; JSON round-trip; validate-on-construct | `lib/spec.py` (`Spec`), `models.ReelReport` (the `overall` property) |
| `scripts/reel_review.py` | thin driver — `build_review(raw_findings, reel, …) → Review`, `write_review → REVIEW.json + REVIEW.md`, CLI `python -m scripts.reel_review build` | `scripts/reel_brief.py`, `scripts/edit_plan.py` |
| `SKILLS/reel-review/SKILL.md` | the process: build the packet → dispatch the reviewer → run the driver → the human loop + routing | `SKILLS/reel-brief/`, `requesting-code-review` |
| `SKILLS/reel-review/reel-reviewer.md` | the reviewer subagent prompt template (packet placeholders + the axes/questions + the required raw-findings JSON shape) | `requesting-code-review/code-reviewer.md` |

`scripts/lib/review.py` imports only stdlib (`json`, `dataclasses`, `pathlib`) —
pure, unit-testable, no ffmpeg, no driver import. It is the reel-brief calque:
a text stage with a typed artifact.

## §2 The typed contract (`scripts/lib/review.py`)

Vocabularies (module tuples, the `MOOD_ANCHORS`/`HERO_RULES` idiom):

```python
REVIEW_AXES       = ("idea", "mood", "hook", "ending", "spine",
                     "edl_completeness", "trend_flavor")   # the §5.13 editorial questions
REVIEW_SEVERITY   = ("blocking", "important", "minor")     # guides the human; blocking ⇒ verdict "revise"
REVIEW_ROUTES     = ("edit-plan", "pacing", "music", "reprocess", "titles", "none")  # suggested fixer
REVIEW_CONFIDENCE = ("high", "medium", "low")              # trend_flavor is forced low (no §5.4 source)
```

### 2.1 `Finding`

A hard config-spec — validate-and-raise in `__post_init__`, JSON round-trip,
remedy-bearing `ValueError`, exactly like `Spec` / `EDLEpisode`:

| Field | Type | Rule (gate) |
|-------|------|-------------|
| `axis` | str | ∈ `REVIEW_AXES` |
| `severity` | str | ∈ `REVIEW_SEVERITY` |
| `evidence` | str | non-empty — cite the episode idx / timestamp / the advisory signal that grounds it |
| `route` | str | ∈ `REVIEW_ROUTES` — the fixer stage the human would re-run |
| `suggestion` | str | non-empty — the concrete change |
| `confidence` | str = `"high"` | ∈ `REVIEW_CONFIDENCE` |

`from_dict` guards the top level first (non-dict → one documented `ValueError`
with a "re-run reel-review" remedy, the `Spec.from_dict` rule), then hands raw
required values to `__post_init__`. No cross-field coupling in code (an
`axis=="trend_flavor"` finding *should* carry `confidence=="low"`, but that is
the **reviewer prompt's** instruction, not a validation rule — the contract
stays orthogonal; the low-confidence honesty is enforced in prose, §3).

### 2.2 `Review`

| Field | Type | Rule |
|-------|------|------|
| `reel` | str | non-empty — path to the reviewed cut (`out/REEL_v{n}.mp4`); pins *which* reel this judges |
| `findings` | tuple[`Finding`, …] | every element a `Finding` (raw dicts are rejected — construct via `build_review`) |
| `summary` | str = `""` | the reviewer's one-paragraph overall read |
| `spec_ref` | str = `""` | a short echo of the intent judged (or the `SPEC.json` path) |
| `platform` | str = `""` | from `SPEC.platform`, for the report header |
| `reviewer` | str = `""` | free note (which agent/model reviewed) |

`verdict` is a **computed property**, not a stored field (the `ReelReport.overall`
idiom — one source of truth): `"revise"` iff any finding is `severity=="blocking"`,
else `"approve"`. It is **advisory to the human**: an `"approve"` with `important`
findings is "approve with notes"; a human may waive a `blocking` finding and
approve anyway. `to_dict` emits `verdict` for the `.md`/`.json` readers;
`from_dict` ignores an incoming `verdict` (recomputes it — a hand-edited
`REVIEW.json` cannot lie about its own verdict).

`to_markdown` renders the human-facing report: a header line with the verdict +
platform + reel, the `summary` paragraph, then findings grouped **blocking →
important → minor**, each as `axis · route · confidence — evidence → suggestion`.
An empty-findings review renders "✅ no findings — reel delivers the brief".

## §3 The reviewer subagent (`SKILLS/reel-review/reel-reviewer.md`)

The template mirrors `requesting-code-review/code-reviewer.md`: placeholders for
the **packet paths**, the **axes/questions**, and the **required output shape**.
Dispatched via the Task tool (`general-purpose`), the reviewer:

1. **Reads the packet** — `SPEC.json` (intent), `EDL.md` (realized plan),
   `report.json` (mechanical + Slice A advisory signals), `MUSIC.json`/
   `PACING.json` when present, and the thumbnail contact-sheet.
2. **Judges each axis** and emits a finding only where the reel falls short:

   | Axis | Question | Evidence it cites |
   |------|----------|-------------------|
   | `idea` | Delivers `SPEC`'s original idea? | SPEC.idea vs the EDL's actual episode arc |
   | `mood` | Mood/story land? | `SPEC.mood` vs `MUSIC.json` `mood_features`; the stills |
   | `hook` | Opening strong (first ~1–3s)? | ep-0 shot_type/layout/description + the hook still |
   | `ending` | Ending right (last ~3s)? | last-ep + the ending still + `SPEC.ending` |
   | `spine` | Cuts along the energy spine? | `PACING.json` slots vs EDL `beat_slot`/dur; `beat` advisory |
   | `edl_completeness` | Anything from the EDL missing/weak? | EDL episodes vs SPEC intent; the `variety`/`transitions` signals |
   | `trend_flavor` | Classic base **and** trend flavor (not bland, not gimmicky)? | general knowledge — **no source of truth** |

3. **Writes `review_findings.json`** — a raw list of finding dicts + a top-level
   `summary` string. (The subagent writes raw JSON to a path the SKILL gives it;
   the typed driver validates it next — the subagent never writes `REVIEW.json`
   directly, so a malformed finding fails loud at the driver, not silently.)

**The `trend_flavor` honesty rule (prose-enforced):** its criterion has **no
source of truth until §5.4 `trend-scan`** (YAGNI, unbuilt). The template
**requires** every `trend_flavor` finding to carry `confidence="low"` and to name
§5.4 in its `evidence` ("judged from general knowledge; no `TRENDS.md` source —
§5.4 unbuilt"). It never emits a `blocking` `trend_flavor` finding — an unsourced
taste call must not read as "reel fails to deliver".

**The contact-sheet** is a cheap `ffmpeg` still-grab the SKILL builds before
dispatch (hook frame at `t≈0.5`, ending frame at `t≈dur−1`, one mid-frame per
episode from the EDL cut times) — output-seek (`-ss` **after** `-i`, §12
landmine) into a tiles montage or N PNGs. It lives in the **SKILL prose as an
ffmpeg one-liner**, not in Python (no new module, no golden).

## §4 The SKILL + the human loop (`SKILLS/reel-review/SKILL.md`)

Announce on entry: **"Using reel-review to judge the reel against the brief."**

1. **Build the packet.** Resolve the run's `SPEC.json` / `EDL.md` / `report.json`
   / `MUSIC.json` / `PACING.json` paths + the delivered reel; grab the
   contact-sheet stills. A missing optional artifact (silent reel → no
   `MUSIC.json`; autonomous run → no `SPEC.json`) is named, not fatal — the
   reviewer judges against what exists (no `SPEC.json` → it reviews against the
   `EDL` + the run's stated intent).
2. **Dispatch the reviewer subagent** with `reel-reviewer.md` filled in. It
   returns after writing `review_findings.json`.
3. **Validate + write.** `python -m scripts.reel_review build --findings
   review_findings.json --reel out/REEL_v{n}.mp4 --spec <run>/SPEC.json --out-dir
   <run>` → the driver builds a typed `Review` (fail-loud on a bad finding) and
   writes `REVIEW.json` + `REVIEW.md`.
4. **Surface to the human (CP3).** Present `REVIEW.md` **beside** the reel and the
   `check_reel` report. This is the gate — the human reads the verdict + findings.
5. **The human disposes.** For each finding the human chooses to act on, re-run
   the **routed** stage (the map below), which regenerates the reel; then
   **re-review** (step 1, a new round — the new reel is a new `REEL_v{n+1}.mp4`,
   `REVIEW.json` is overwritten to judge the latest cut). The loop ends when the
   human **approves** (verdict `approve`, or every remaining finding waived).

**Routing map** (finding `route` → the existing stage the human re-runs — no new
fixer is built):

| `route` | Re-run | Typical finding |
|---------|--------|-----------------|
| `edit-plan` | `edit-plan` SKILL (edit `selection.json`, rebuild `EDL`) | weak hook / weak ending / missing EDL element / classic↔trend lean |
| `pacing` | `pacing` SKILL then `edit_plan build --pacing` | cuts drift off the energy spine |
| `music` | `music-match` / `music-source` SKILL | mood mismatch / wrong track |
| `reprocess` | `process_episode` on one episode (a grade/layout redo) | one episode reads wrong vs the reel |
| `titles` | `titles` SKILL | hook/ending wants on-screen text |
| `none` | — (note only) | an observation the reviewer wants recorded, no action |

The routing mirrors `using-montage`'s existing rule for a mechanical
`stop_and_report`: "route it to the culprit stage's skill." Slice B extends the
*same* dispatch pattern to editorial findings.

## §5 Wiring

- **`using-montage` CP3 (`SKILLS/using-montage/SKILL.md`, step 10 "final
  review").** After it presents `REEL_v1.mp4` + the `check_reel` report, it
  **invokes reel-review** to produce `REVIEW.md` and presents it alongside. The
  existing "a failed gate is surfaced verbatim, never fixed forward; route it to
  the culprit stage's skill" sentence already describes the editorial loop — the
  edit is to name reel-review as the CP3 review mechanism and point findings at
  their routes. On a bare autonomous run the review still runs (it judges against
  the `EDL` when no `SPEC.json` exists).
- **`scripts/montage.py` — an optional `reel-review` Stage.** Artifact
  `REVIEW.json`, checkpoint `"final"`, **never** pointed at by `next` (the
  `titles`/`assemble-draft` optional-Stage pattern). It gives the inspector a
  presence-marker ("this reel has been reviewed") and resumability; it does **not**
  drive an autonomous loop (a human review does not autonomously resume). A test
  patch mirrors the titles/draft optional-Stage tests.

No other driver changes: `build_reel` / `edl_to_reel` / `deliver` / `check_reel`
are untouched (reel-review runs *after* deliver, reading its outputs).

## §6 Testing (TDD)

Pure-contract + driver unit tests (the bulk — deterministic, no ffmpeg), mirroring
`tests/lib/test_spec.py` / `test_edl.py`:

- **`Finding`** — each vocab field rejects an out-of-vocab value / a bool / (for
  `evidence`,`suggestion`) an empty string, with a remedy-bearing message;
  `confidence` defaults `"high"`; `from_dict` rejects a non-dict top level; JSON
  round-trip (`to_dict`→`from_dict` is identity).
- **`Review`** — rejects a raw-dict in `findings` (must be `Finding`); `verdict`
  property: any `blocking` → `"revise"`, only `important`/`minor` or empty →
  `"approve"`; `from_dict` recomputes `verdict` (a lying stored `verdict` is
  ignored); empty `reel` raises; JSON round-trip; `from_json` corrupt →
  `ValueError` with remedy.
- **`to_markdown`** — contains the verdict + reel; findings render **blocking
  first**; an empty-findings review renders the "no findings" line.
- **`scripts/reel_review.py`** — `build_review` validates each raw finding (a bad
  one raises, nothing written) and derives the verdict; `write_review` writes
  **both** `REVIEW.json` and `REVIEW.md`; a CLI smoke test drives
  `review_findings.json → REVIEW.json` (the `reel_brief`/`edit_plan` CLI-test
  shape).

**No ffmpeg golden.** This is a text stage over artifacts other stages already
produce; the reviewer is an **agent** (prose SKILL), not pytest-tested — the same
call `reel-brief` and `edit-plan` make. The contact-sheet is an ffmpeg one-liner
in the SKILL, not Python, so nothing new needs a golden.

## §7 Out of scope (boundaries)

- **The `trend_flavor` source.** The axis exists and is judged from general
  knowledge at forced `confidence="low"`; a real source of truth waits on §5.4
  `trend-scan` (YAGNI, unbuilt). Slice B does not block on it.
- **No auto-fix actuator.** Findings are surfaced; nothing re-reframes on them.
  The route is frozen after loop-1; the layout is the edit-plan's decision; the
  human re-runs the fixer. (The `safe_zones` / Slice A "advisory, no actuator"
  argument, one level up.)
- **Single reviewer, not a panel.** One subagent; the human is the final gate. A
  multi-perspective panel (idea-lens / craft-lens / trend-lens voters) is a
  deferred enhancement, not this slice.
- **`overall` / `reel_orchestration` / `build_reel` / `deliver` / loop-2 —
  untouched.** Editorial "green" is the human's CP3 sign-off, never an automated
  block. The §5.13 gate reads "both parts green": mechanical green is
  `check_reel`'s `overall`; editorial green is the human approving the review.
- **Full playback.** The reviewer judges plan + signals + stills, not motion in
  real time — stated honestly in every review (`summary` names the boundary).
- **Multi-reel batch.** One reel per review run (`SPEC.reel_count > 1` is
  reviewed one cut at a time); no cross-reel comparison.

## §8 Docs impact + status flip

- **`docs/pipeline-map.md`** — 5.13 row `◐ → ✅` ("editorial agent review built —
  reel-review SKILL + typed `REVIEW.json`"); **tally `14 ✅ · 1 ◐ · 1 ❌` →
  `15 ✅ · 0 ◐ · 1 ❌`**; the "Editorial reel-final" phase-roadmap item ticks;
  the "Remaining work" 5.13 row empties (only §5.4 stays ❌).
- **`docs/build-status.md`** — a new DONE bullet under the reel-final work; the
  §5.13 "editorial half" is no longer the open item.
- **`CLAUDE.md` Quick Reference** — two rows (this design + its plan).
- **The montage design spec** — §5.13 line 403 "**Not yet built (Slice B)**" →
  built; §5.13 "Gate: both parts green" now satisfiable; the §5.1/§4.1 CP3
  description names reel-review as the review mechanism.

**Why the stage flips to ✅ despite the `trend_flavor` caveat:** the §5.13 gate is
"both parts green", and *green* means the review **mechanism** exists and is
operable — the human can run it, read typed findings, route fixes, and approve.
`trend_flavor` is one **sub-criterion** judged at low confidence, not a missing
half; documenting its confidence ceiling (and its §5.4 dependency) is the honest
close, not a reason to hold the whole stage partial. (Confirmed in brainstorming.)
