# using-montage router (stage 5.1) — design

**Date:** 2026-07-12. The front door of the montage conveyor: one skill that turns
a footage folder + a natural-language brief into a delivered reel, by conducting
the stages that are already built. Design spec §5.1 (router), §4.1 (the three
user checkpoints), pipeline line 510 (resume-for-free).

## Scope decisions (locked in brainstorming)

- **Slice = the entry-skill (end-to-end), not the parallel fan-out.** The user
  chose the front-door conductor over the cap-3 optimisation. `edl_to_reel` keeps
  its **sequential** loop-1; the cap-3 *parallel* fan-out (§5.10) is a separate,
  later slice and is an explicit non-goal here.
- **SKILL + a thin `montage.py` inspector**, not SKILL-only and not a full Python
  driver. Every mechanical span already has a TDD'd CLI (`project_init`, `intake`,
  `beats`, `edit_plan build`, `edl_to_reel`); the router adds only orchestration
  and judgment. The one deterministic thing worth coding is **where a run stands**
  — a stage-status inspector — so resumability (line 510) is testable, not prose.
- **`montage.py` inspects, it does not run.** The front-half judgment steps
  (footage-intake cast-naming, edit-plan `selection.json` authoring) are
  agent-interactive; a headless Python driver can't perform them without breaking
  the "selection is judgment" invariant (§5.7). So the SKILL runs the stages —
  invoking sub-skills for judgment, sub-processing CLIs for mechanical work — and
  calls `next_action()` to know where a (possibly resumed) run stands. This
  mirrors `intake.py` ↔ `footage-intake` and `edit_plan.py` ↔ `edit-plan`:
  mechanical inspection in code, judgment in the SKILL.
- **The analogue is `using-superpowers`** (design §5.1 says so): a router is a
  conductor, not a component. The bulk of it is a markdown skill.

## 1. Goal & data flow

One invocation — "make a 9:16 reel from this footage, no music" — walks the
conveyor to `out/REEL_v1.mp4`, stopping only at the **three** user checkpoints
(§4.1). The router does not re-implement any stage; it sequences the built ones
and **names** the deferred ones so a skipped stage is visible, never silent.

```
using-montage (SKILL) ── parses the brief, conducts:
  0. ensure-env         bash setup.sh [--with-vidstab]
  1. project-init  ───► project.json          [CP1: spec approval]
  2. footage-intake ──► FOOTAGE.json (+cast.json)
     (3 reel-brief SPEC.md — optional, enriches CP1 · 4 trend-scan TRENDS.md — DEFERRED, named)
  5. music-and-mood ──► MUSIC.json             (optional; absent → silent reel)
     (6 pacing PACING.md — optional; 5.6 energy spine, run after music,
      --pacing into edit-plan; music-less path only → beat_slot stays unset)
  7. edit-plan     ───► EDL.json + EDL.md      [CP2: EDL approval + curation loop]
  8. edl_to_reel   ───► out/REEL_v1.mp4        [CP3: final review]

  montage.next_action(run_dir) tells the SKILL which of the above is `next`.
```

Every stage skips itself when its artifact already exists (§5.1 resumability):
a dead session resumes for free. The inspector is what makes "which stage is
next" a computed fact rather than a re-reading of prose.

## 2. The inspector (`scripts/montage.py`, new)

Pure, deterministic, no ffmpeg, no network. One typed stage table + one function.

### 2.1 `Stage`

```python
@dataclass(frozen=True)
class Stage:
    key: str            # "project-init", "footage-intake", ...
    artifact: str       # glob that marks it done ("project.json", "REEL_v*.*"); "" = none
    kind: str           # "required" | "optional" | "deferred"
    runner: str         # human: how it runs ("project-init SKILL → project_init CLI")
    checkpoint: str | None   # "spec" | "edl" | "final" | None
    in_out: bool = False     # artifact lives in out_dir, not run_dir (deliver only)
```

`__post_init__` validates: `kind ∈ {"required","optional","deferred"}`,
`checkpoint ∈ {None,"spec","edl","final"}` — raise `ValueError` with the bad value
and the allowed set (fail-loud contract). Display order is the tuple position —
there is no ordinal field (it would only collide with the design's own §5.N
numbers).

### 2.2 `V1_STAGES: tuple[Stage, ...]`

The ordered v1 conveyor as data (single source of truth for the SKILL prose too);
the leading `#` is the tuple position, not a field:

| # | key | artifact | kind | checkpoint | runner |
|---|-----|----------|------|-----------|--------|
| 1 | project-init | `project.json` | required | spec | project-init SKILL → `project_init` CLI |
| 2 | footage-intake | `FOOTAGE.json` | required | — | footage-intake SKILL → `intake` CLI |
| 3 | reel-brief | `SPEC.json` | optional | spec | reel-brief SKILL → `reel_brief` CLI |
| 4 | trend-scan | `TRENDS.md` | deferred | — | 5.4 — not built |
| 5 | music-and-mood | `MUSIC.json` | optional | — | `beats` CLI (absent → silent reel) |
| 6 | pacing | `PACING.md` | optional | — | 5.6 — energy spine; run after music, `--pacing` into edit-plan (music-less path only: `beat_slot` stays unset) |
| 7 | edit-plan | `EDL.json` | required | edl | edit-plan SKILL → `edit_plan build` CLI |
| 8 | deliver | `REEL_v*.*` | required | final | `edl_to_reel` CLI (extract→process×N→assemble→check→deliver) |

Stages 5.8–5.13 are not separately tracked at the router level — they live inside
the one `edl_to_reel` hop, whose delivered `REEL_v*.mp4` is the stage-8 artifact.

### 2.3 `next_action(run_dir: str, out_dir: str | None = None) -> dict`

```python
def next_action(run_dir: str, out_dir: str | None = None) -> dict:
    """Inspect a run dir → the ordered v1 stages with each stage's state, the next
    required action, and whether the reel is delivered. out_dir defaults to
    <run_dir>/out (where deliver versions REEL_v{n}). State per stage:
      done     — artifact exists (resume-for-free, design line 510)
      next     — the FIRST required stage whose artifact is missing (run this)
      pending  — a required stage after `next` still missing its artifact
      optional — an optional built stage not yet produced (music/pacing); never blocks
      skip     — a deferred stage (trend-scan); named, not silent
    Returns {"stages":[{key,artifact,kind,state,checkpoint,runner}, ...] in order,
             "next": <stage key | None>, "delivered": <bool>}."""
```

Rules (deterministic, per-artifact — honest about inconsistent resumes):

- A stage is **done** iff a file matches its `artifact` glob under its base dir
  (`out_dir` when `in_out`, else `run_dir`). Empty `artifact` ⇒ never auto-done.
- Walk **required** stages in order. The first one that is not done is **next**
  (and sets the returned `"next"`); required stages after it that are not done are
  **pending**; a required stage that is done is **done** even if an earlier
  required stage is missing (this surfaces a broken resume — an EDL atop no
  FOOTAGE — rather than masking it).
- **optional** stages are `done` if their artifact exists, else `optional` — they
  never become `next` and never block the required chain.
- **deferred** stages are always `skip`.
- `"next"` is `None` when every required stage is done; `delivered` is the
  stage-8 (deliver) done-state.

### 2.4 CLI — `python -m scripts.montage status`

```
python -m scripts.montage status --run-dir <dir> [--out-dir <dir>]
```

Prints `json.dumps(next_action(...), indent=2)`; exit 0 always (status query, not
a gate). The SKILL reads it to decide the next hop; a human can read it to see
where a stalled run stands.

## 3. The SKILL (`SKILLS/using-montage/SKILL.md`, new)

Frontmatter `name: using-montage`, a description carrying the "1% → invoke"
entry-router intent. Sections:

- **Overview / Core principle** — you are the conductor; you run built stages in
  order, surface the three checkpoints, and never silently skip a deferred stage.
  Judgment (what the brief means, is this the right cut, does the reel read) is
  yours; the mechanical spans are the CLIs'.
- **When to Use** — a footage folder + an intent to make a reel; the front of the
  conveyor. Not for re-running a single stage (invoke that stage's own skill).
- **The Process** — point **every** stage's output at the one run dir
  (`project_init --project-dir`, `intake <root> <run_dir>`, `edit_plan --out-dir`,
  `edl_to_reel --work-dir/--out-dir`) so the inspector sees a coherent run:
  0. **Ensure env** — `bash setup.sh`; add `--with-vidstab` (intake is the first
     runtime vidstab consumer, §5.2).
  1. Consult `python -m scripts.montage status --run-dir <dir>` — **resume from
     `next`**; a stage whose artifact exists is already done.
  2. **project-init** (if `next`) → `project.json`. **CP1 (spec approval):** read
     back the resolved `{canvas, delivery}` + the parsed intent, confirm.
  3. **footage-intake** (if `next`) → `FOOTAGE.json` (+ `cast.json` when people
     matter). Interactive cast-naming is the sub-skill's.
  4. **music-and-mood (optional)** — when the brief names a track or "with music",
     run `beats` → `MUSIC.json`; on "no music" / "без музыки" leave it unset
     (silent reel). Point edit-plan's `music` at it when present.
  5. **edit-plan** (if `next`) → `EDL.json` + `EDL.md`. **CP2 (EDL approval +
     curation):** show `EDL.md`; the user swaps/re-orders episodes → you edit
     `selection.json` and re-run `edit_plan build` (it round-trips; never
     hand-edit `EDL.json`). No `draft.mp4` in v1 (SP1b deferred) — the `EDL.md`
     map is the approval surface; say so.
  6. **edl_to_reel** → `out/REEL_v1.mp4`. **CP3 (final review):** present the
     delivered reel + the `check_reel` report; a fail is surfaced verbatim
     (stop-and-report), never fixed forward.
- **Reading the brief** — a small intent→param table (below).
- **Boundaries** — the three checkpoints are the ONLY user-facing gates (§4.1);
  deferred stages are named on skip; the router never re-implements a stage and
  never hand-edits a generated artifact.

### 3.1 Reading the brief (intent → param)

The user speaks free text; the SKILL parses intent and passes **explicit args** to
the CLIs (the user never types flags, §5.1). Judgment lives in the SKILL, not code.

| Said in the invocation | → param |
|------------------------|---------|
| "reel"/"shorts"/"9:16" · "youtube"/"16:9" · "square"/"1:1" · "cinema"/"21:9" | `project_init --purpose …` |
| "4k" · "1080"/"social" · "native"/(unstated) | `project_init --quality …` |
| a track path / "with music" | `beats … --out MUSIC.json`, then edit-plan's `selection.json` `music` field |
| "no music" / "без музыки" | leave `MUSIC.json` unset (silent path; `music=None`) |
| "classic" ↔ "trend" (style-lean) | edit-plan guidance (composition/pacing choices) |

Ambiguous or mixed intent (e.g. "a reel AND a youtube cut") → ask, one project per
aspect (defers to project-init's own "ask, don't guess").

## 4. Testing

- **`tests/lib/test_montage.py`** (unit, the bulk): `next_action` over a `tmp_path`
  run dir — empty (next=project-init, delivered False), project.json only
  (next=footage-intake), +FOOTAGE (next=edit-plan, music `optional`), +MUSIC
  (music `done`), +EDL (next=deliver), +`out/REEL_v1.mp4` (next None, delivered
  True); deferred stages always `skip`; the **broken-resume** case (EDL present,
  FOOTAGE missing → footage-intake `next`, edit-plan `done`); `Stage` rejects a
  bad `kind`/`checkpoint`; the `status` CLI prints the JSON and exits 0.
- **No new integration golden.** The end-to-end seams are already proven on real
  bytes: `tests/integration/test_edit_plan.py` (SP3→SP1: selection→EDL→reel) and
  `tests/integration/test_front_spine.py` (EDL→reel). The router only sequences
  those proven hops; a router-specific golden would re-run intake→edit→reel with a
  faked `process_episode` (synthetic footage yields empty YOLO routes, as SP1
  found) — marginal coverage over the existing seam goldens for real cost. Called
  out here so the omission is a decision, not an oversight.

## 5. Non-goals (v1 / 5.1 entry-skill)

- ~~**cap-3 *parallel* fan-out** (§5.10) — `edl_to_reel` stays sequential; a
  separate later slice.~~ **Landed 2026-07-18** as that separate slice:
  `edl_to_reel` fans out across a bounded thread pool (`jobs`, default 3 — the
  measured knee, 1.70×). This was 5.1's last open sub-item, so the stage now has
  none. See `docs/specs/2026-07-18-cap3-fanout-design.md`.
- **`draft.mp4`** (SP1b, §5.9) — CP2 approves the `EDL.md` map, no burnt-in draft.
- **dual-emit "without music" + trending-sound sidecar** (§5.14) — v1 "no music"
  is the plain silent path; the with/without dual export is a deliver enhancement.
- **trend-scan (§5.4)** — a deferred stage, named on skip. (pacing (§5.6) is now
  built — an optional stage, run when `MUSIC.json` exists; see stage 6.)
- **a headless auto-run mode** (no checkpoints) — v1 is interactive at the three
  gates by design (§4.1).
- **cast-name hero-pin resolution** — `hero` still rides as a bbox/rule/name
  string into the EDL (a later plan wires descriptors).

## 6. Reused as-is (no change)

`scripts/project_init.py`, `scripts/intake.py`, `scripts/beats.py`,
`scripts/edit_plan.py`, `scripts/edl_to_reel.py`, `build_reel`, `deliver`, and the
four sub-skills (`project-init`, `footage-intake`, `edit-plan`, `process-episode`).
The router is additive: one new script (`montage.py`) + one new SKILL, plus doc
sync. No existing behaviour changes.

## 7. Docs to sync (same commit as the build)

- `docs/pipeline-map.md` — 5.1 `◐ → ✅` (entry-skill done; note the parallel
  fan-out remains the one open 5.1 sub-item); tally + critical-path diagram.
- `docs/build-status.md` — a "using-montage router (5.1) DONE" entry; move the
  "router" next-action bullet to "cap-3 parallel fan-out" only.
- `CLAUDE.md` — registry row for this design + its plan.
- design spec §5.1 — a "> Built (2026-07-12)" note pointing here.
