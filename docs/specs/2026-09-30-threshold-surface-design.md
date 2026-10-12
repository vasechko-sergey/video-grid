# Threshold surface — an authoring surface must carry its threshold's blast radius

**Status:** shipped 2026-10-12, version 0.15.0 (MINOR — new contract fields, a new CLI
flag, no breaking change). Designed 2026-09-30; §0.2a, §2.2a, §2.3 and §6 were written or
rewritten during the slice as measurements overturned the plan, and should be read as the
as-built record. Backlog P1 (promoted by the unenforced-rules slice, design 2026-09-29 §0.6), with
R2.4 folded in.

**Row, as filed:** twelve of the eighteen fields of `ReelCheckSpec` and `CheckSpec`
are unreachable from any authoring surface — no CLI flag, no manifest field, no
convention file. A tool with twelve bars nailed to one shoot is single-domain by
construction.

---

## §0 Measurements

### §0.1 The row's twelve are not one population — and the split is the design

The row treats all twelve alike. They are not alike: five govern a check that
cannot block, six govern one that can, and one is not a bar at all (§0.2a). Widening an
advisory tolerance changes a number in a report nobody gates on. Widening a blocking bar is a waiver written in
numbers, and the repo has already watched that mechanism run once —
`color_delta_max` went 12 → 44 → 56 to switch a gate off (colour-convergence-retire
design §0.1).

`models.py:1350` is the partition's own source:

```python
_ADVISORY_CHECKS = ("beat", "safe_zones", "key_action", "pad_bars", "transitions",
                    "outro", "brief_length", "chroma_spread")
```

| field | owning class | check it sets the bar for | blocks? |
|---|---|---|---|
| `beat_tol` | `ReelCheckSpec` | `beat` | advisory |
| `clip_tol` | `ReelCheckSpec` | `key_action` | advisory |
| `bar_symmetry_tol` | `ReelCheckSpec` | `pad_bars` | advisory |
| `layout_jump_max` | `ReelCheckSpec` | `transitions` | advisory |
| `chroma_spread_max` | `ReelCheckSpec` | `chroma_spread` | advisory |
| ~~`loudness_target`~~ | `ReelCheckSpec` | `loudness` | **not a bar at all — see §0.2a** |
| `loudness_tol` | `ReelCheckSpec` | `loudness` | **BLOCKING** |
| `grade_residual_max` | `ReelCheckSpec` | `grade_faithful` | **BLOCKING** |
| `length_retime_max` | `ReelCheckSpec` | `brief_length` (advisory) **and** `build_reel`'s absorb | **BLOCKING in effect** |
| `black_floor` | `CheckSpec` | `black_frames` | **BLOCKING** |
| `black_rel` | `CheckSpec` | `black_frames` | **BLOCKING** |
| `entropy_floor` | `CheckSpec` | `grade_damage` | **BLOCKING** |

**Six blocking, five advisory, and one that is not a threshold** (§0.2a, found by Task 5). Two names in that table are easy to get wrong
and were, in this design's first draft: the episode-level black gate's key is
`black_frames` (`check_episode.py:412`), not `black` — `black` is a *reel* check
(`check_reel.py:436`) that reads no threshold at all; and an episode check has no
advisory registry to be absent from, so it blocks by default rather than by
membership. `length_retime_max` is the one that had to be
traced rather than read off the table, and the first pass of this design got it
wrong twice — first calling it "not a check threshold at all", then "a driver
behaviour". It is read at two sites:

- `check_reel.py:171` — `budget = _LENGTH_TOL + spec.length_retime_max`, the
  *advisory* `brief_length` check's band. Harmless.
- `build_reel.py:142` → `reel_orchestration.next_action(..., length_retime_max, ...)`
  — how much shortfall the driver **absorbs by re-timing the target** instead of
  escalating. Widening it does not move a bar; it converts a blocking length
  failure into a silent re-target. That is the cry-wolf mechanism exactly, and it
  is why the field sits in the blocking bucket despite the advisory check that also
  reads it.

### §0.2a `loudness_target` is not a bar, and authoring it would break every reel

Found by Task 5 and verified: `mix.py:16` holds `_TARGET_LUFS = -14.0`, `mix.mix`
takes no target parameter, and line 231 bakes that constant straight into the
`loudnorm` filter that renders the stem. So `loudness_target` has **two**
consumers — the renderer and the gate — and `GATES.json` would reach only the
second. Authoring `-16` moves the ruler and not the thing measured: the stem is
still rendered at −14, `_loudness_check(-14.0, target=-16)` fails, and the reel
escalates to `audio-mix`. The only escape is widening `loudness_tol`, which is a
waiver wearing the target's name — the exact mechanism §1 exists to stop.

The category is the point. The other eleven are **bars**: a number a check
compares against, whose whole meaning is "how far is too far". `loudness_target`
is the value the pipeline **renders to**, and the gate's job is to confirm it got
there. A file of gates is the wrong home for it, the same way a thermostat's
set-point is not a tolerance.

**It moves to `AUTHORED_ELSEWHERE`**, naming `mix._TARGET_LUFS` as its real home,
and the vocabulary drops from twelve to **eleven**. `loudness_tol` stays: widening
the band around a rendered −14 is a genuine authored waiver.

This also sharpens §0.2. A platform table is not merely "four identical rows
today" — it is the **only correct place** for this value, because it is the only
shape that can set both consumers at once. A broadcast deliverable at −23 LUFS is
a real need for a general tool, and it is filed (§7) as one row that moves the
mixer and the gate together, never one of them.

### §0.2 Half the obvious work is removed by measurement

`loudness_target` looks platform-derivable, and the pipeline already has what it
would need: `ReelManifest.platform` exists, `check_reel.run(platform=…)` already
resolves `safezones.safe_zone_for(platform)`. So a `PLATFORM_LOUDNESS` table beside
`SAFE_ZONES` is one hour's work.

It is not worth doing. All four platforms in `SAFE_ZONES` — `generic`, `tiktok`,
`reels`, `shorts` — want **−14 LUFS** today. The table would be four identical
rows, i.e. a knob that reads as configurable while being inert — the
`gradedamage.ENTROPY_BINS` mistake (design 2026-08-31, fix round 1) in a new
costume. A real difference appears only at a platform this table does not carry
(broadcast −23, Apple Music −16), and that is when the table earns its existence.
Recorded here so the next reader does not re-derive it. **Deferred, §7.**

### §0.3 Three of the twelve are not merely flagless — they have nowhere to be written

`ReelCheckSpec` reaches the checks through `ReelManifest.check_spec`
(`models.py:1716`), which is two lines:

```python
@property
def check_spec(self) -> ReelCheckSpec:
    return ReelCheckSpec(self.target_dur, self.variety_min)
```

(A `@property`, not a method — both real callers, `edl_to_reel.py:307` and
`build_reel.py:95`, read it as an attribute. Recorded because this design's first
draft and the plan both wrote `check_spec()` and would have handed five
uncallable test snippets to later tasks.)

So its nine remaining fields have no carrier: the manifest has no field to hold
them. `CheckSpec` is worse. It is built at two sites —
`process_episode.py:565` and `check_episode.py:447` — both from a `Manifest`'s
`composition`/`grid`/`target_dur` plus `attempt`. `Manifest` carries no
`black_floor`, no `black_rel`, no `entropy_floor`. There is no hand-edit that
reaches them: an operator who wants a different black floor must edit
`scripts/lib/models.py`. That is the row's sharpest form and it is about the
*general tool* constraint directly — a bar calibrated on one shoot, editable only
by patching the engine.

Confirmed no CLI reaches any of the twelve: `check_episode`'s parser carries
`--composition`, `--grid`, `--target-dur`, `--attempt` and nothing else
(`check_episode.py:430-440`); `edl_to_reel`, `check_reel` and `build_reel` carry
none at all. The one threshold flag that ever existed, `--color-delta-max`, was
deleted with its check in 0.5.0.

### §0.4 `spec_overrides` reports one field today, and this slice is what makes it mean something

`provenance.spec_overrides` (`provenance.py:99`) diffs a spec against a
default-constructed one of its own class and is called once, from
`edl_to_reel.py:307`, on `rm.check_spec` with `target_dur` exempt. Since
`check_spec` sets only `target_dur` and `variety_min`, the diff can report
**exactly one field** — `variety_min`.

**And it cannot report even that one on a sanctioned run.** `variety_min` occurs
nowhere in `edl.py` or `edl_to_reel.py`; the `ReelManifest(...)` construction at
`edl_to_reel.py:281` does not pass it, so it takes its dataclass default of 8 and
diffs against a baseline of 8. Its only other inlet is
`ReelManifest.from_dict`'s `d.get("variety_min", 8)` (`models.py:1744`) — a
hand-edited `EPISODES.json`. And `spec_overrides` **cannot see even that**: it is
called once, in phase 1's `_reel_manifest`, on the manifest phase 1 just built, so
a hand-edit made between the phases is invisible to it (measured by Task 5:
`check_spec.variety_min == 4` while `Attestation.overrides == []`). So on every
run this conveyor made before this slice, `Attestation.overrides` was the empty
list, by construction rather than by coincidence. (Derived from the code path, not
read off a delivered artifact.) This slice changes that for the reel scope only:
phase 1 now sets authored reel-scope bars on the manifest before `spec_overrides`
runs, so they appear in `overrides` — still with no reason, and never an
episode-scope bar (§2.4 item 2).

Its docstring already promises more:

> A diff, NOT a registry: a threshold added to ReelCheckSpec later is covered the
> day it lands, with no second place to remember to update.

It is right, and it has had nothing to cover. R2.4's complaint (a loosened gate
that leaves no trace) is not that the instrument is missing; it is that nothing can
loosen a gate, so the instrument reports nothing. This slice supplies the input
that instrument was built for.

### §0.5 The convention-file idiom is settled, and one of its two users is already a post-EDL consumer

Two files are already found by convention beside `project.json`, with no flag:

- `CONSTRAINTS.json` — `edit_plan.py:677`,
  `rules_path = Path(project_path).parent / "CONSTRAINTS.json"`, loaded through
  `Constraints.from_json`, an unknown rule kind refused **at load, by name**
  (`constraints.py:60`).
- `REGIONS.json` — `match_grade.py:282`, `p = project.parent / "REGIONS.json"`,
  unknown anchor or kind refused at load (`regions.py`).

The stated reason is the same in both and is recorded in `models.py:1558`: *a flag
can be forgotten, and a forgotten flag here silently reverts* the stage to its
unnamed default.

`match_grade` matters here beyond precedent: it is a **post-EDL** consumer that
finds its file at run time, not a stage that freezes the answer into the EDL. That
is the behaviour a gate needs. A bar is discovered to be wrong *after* a check
fails; if the value were frozen onto the EDL at `edit_plan` time, changing it would
require re-cutting the reel.

`edl_to_reel` already takes `project_path` (`_phase_one_setup`, `edl_to_reel.py:87`)
and already reads `ProjectConfig.from_json(project_path)` from it, so the finder
costs nothing.

### §0.6 The vocabulary is exactly the eleven, and it derives itself

`ReelCheckSpec` has 11 fields, `CheckSpec` 7, sharing the name `target_dur`: 17
distinct names. Six are authored elsewhere and must be refused rather than
duplicated —

| name | where it is really authored |
|---|---|
| `target_dur` | the EDL (`EDL.target_dur`, from the footage via `_back_edge_target`) |
| `variety_min` | `ReelManifest.variety_min` — in practice the `variety_min` key of a hand-edited `EPISODES.json`, since no producer sets it (§0.4) |
| `composition` | `Manifest.composition`, per episode |
| `grid` | `Manifest.grid`, per episode |
| `attempt` | the retry loop's own counter, never an author's |
| `loudness_target` | `mix._TARGET_LUFS` — the value the stem is rendered to, not a bar (§0.2a) |

— leaving **17 − 6 = 11**. The row said twelve, and twelve is what the first
five tasks built; Task 5 measured `loudness_target` to be a rendered set-point
rather than a bar (§0.2a) and it joins the exempt set, which is the vocabulary
correcting itself from the dataclasses rather than from the row. So the vocabulary is derived, not typed:
a threshold added to either class later joins `GATES.json` the day it lands, with
no second list to update. Same property `spec_overrides` has, and for the same
reason.

---

## §1 The rule

**An authoring surface must carry the same blast radius as the threshold it
authors.**

A threshold that cannot block is a preference: author it, done. A threshold that
can block is a waiver in numeric clothing, and a waiver whose reason is not
recorded is the whole cry-wolf mechanism — the bar moves, the reel ships, and six
months later nobody can say whether the number was earned or was the fastest way
past a red check.

The corollary, which decides the shape: **the reason must be structurally required,
not conventionally expected.** The previous slice's own finding (unenforced-rules
§1) gives the three remedies available — make the structure enforce it,
machine-check it, or delete the rule. A `GATES.json` that accepts a bare number and
asks politely for a comment is remedy 2 at best and in practice remedy 0. A
`GATES.json` that **refuses to load** a value without a reason is remedy 1, and it
is no harder to build.

---

## §2 Contract

### §2.1 `GATES.json`, beside `project.json`

Found by convention, no flag, exactly as `CONSTRAINTS.json` and `REGIONS.json` are.
Absent means every threshold is its default — which is today's behaviour, unchanged
and byte-identical.

```json
{
  "entropy_floor": {
    "value": 0.85,
    "why": "log profile; the ungraded render is already flat, so the ratio starts near 1"
  },
  "beat_tol": {
    "value": 0.08,
    "why": "handheld, no click track — 50ms was never reachable on this material"
  }
}
```

One shape for both scopes. The author does not need to know which of the two
dataclasses owns a field; the loader does.

### §2.2 Refused at load, by name

`gates.Gates.from_json` refuses — never warns, never stores-and-ignores:

1. a non-object document;
2. an unknown field name, naming the eleven;
3. one of the six §0.6 names, naming **where that value is really authored** (a
   value silently ignored here would read as authored);
4. an entry that is not a `{"value": …, "why": …}` object;
5. a missing, non-string, or blank `why` — **this is remedy 1**, the structural
   half of §1;
6. a value the owning dataclass's own `__post_init__` rejects. The loader
   constructs a probe instance and lets the existing validator raise, re-raising
   with the `GATES.json` path attached. No second copy of eighteen range checks.

**§2.2a — refusal 6 is vacuous today, and that is this slice's problem to fix.**
Measured against the real classes while Task 1 landed:

- `CheckSpec.__post_init__` validates `composition`, `grid`, `target_dur` and
  `entropy_floor` and **nothing else**. `black_floor` and `black_rel` — two of the
  six blocking bars — accept `True`, `nan`, `inf`, `"6"`, `None` and `-1` without
  a word. A string reaches `check_episode._black_frames_check` and dies there in a
  bare `TypeError` naming no file; a negative value disables the check in silence.
- `nan` passes **every** `> 0` guard in both classes, on seven further fields. The
  guards are written `... or v <= 0`, and `nan <= 0` is `False`, so the raise never
  fires. `inf` passes the same seven, and `True` passes five (`bool` is an `int`).

Before this slice none of it was reachable — there was no way to author any of
these values at all. This slice is what makes it reachable, so closing it is in
scope and not a separate row. The fix goes where the other sixteen range checks
already live, in the two dataclasses' own `__post_init__`: remedy 1, the structure
enforcing it, at the layer that owns the field. It does **not** go in `gates.py` —
a second copy of validation beside the first is exactly what refusal 6 exists to
avoid, and it would drift.

No default moves. Nothing in `scripts/` or `tests/` passes a non-default
`black_floor` or `black_rel`, so the widened guards refuse only values that were
already broken.

### §2.3 Where the values are read

`edl_to_reel` finds the file beside the `project_path` it already holds and
threads it to every arm that renders.

**There are THREE such arms, not the two this design first named** (found by
Task 4, verified: `_run_pool` is called from `edl_to_reel.py:367`, `:460` and
`:609`). The third is `render_from_geometry` — phase 1b, `--from-geometry` — and
it does **not** go through `_phase_one_setup`. It is also the arm the router
actually renders through. Phase 1a is the one arm where `check_episode` does
**not** run: it stops at the geometry boundary before any `CheckSpec` exists.
(The single-pass arm runs the check in full too — an earlier draft of this
sentence said phase 1b was "the only one where `check_episode` runs at all",
which is false.) Wiring
only the two arms this design originally named would have shipped the whole
slice **inert on the real path**, passing every test that did not drive phase 1b.
The discovery is therefore factored as `gates.beside_project(path)` and called
from both entry points.

`ReelManifest.gates` is **one new dict field carrying the whole authored set**,
both scopes together, not the reel subset. That single decision removes the second
carrier:

- `ReelManifest.check_spec` applies the subset `ReelCheckSpec` owns and ignores
  the rest.
- Phase 1's pool passes the **whole authored document** into
  `process_episode(..., gates=…)` — a parameter, not a `Manifest` field, which
  keeps a gate a **run policy** rather than a per-episode value an agent could
  author into an EDL. No caller partitions: the one place a spec is constructed
  does, with `for_spec`. A document-shaped `Gates.subset` was designed and then
  deleted before it was built — it would have made every call site filter a set
  the constructor filters anyway.
- `build_reel`'s reprocess arm re-runs `process_episode` and passes `rm.gates`
  straight through. Without the whole set on the manifest it would have nowhere to
  read it from, and a reprocessed episode would be judged against a different bar
  than its siblings — silently, which is the shape of defect the retry-record slice
  (design 2026-09-24 §0.7) just finished closing in the neighbouring field.

It round-trips through `EPISODES.json`, and `ReelManifest.from_dict` re-validates
it by constructing `Gates` from the loaded dict rather than trusting it — the
`OutroFit.from_dict` idiom (pacing-fixed-point design §5), for the same reason: a
hand-edited or truncated `EPISODES.json` is one of the two live inlets to
`build_reel` and does not pass through `edl_to_reel`'s loader.

One CLI gets an explicit `--gates PATH` instead, because it has no project to
derive from: `check_episode`, the standalone episode judge. A second,
`process_episode`'s own CLI — the hand-driven path
`skills/process-episode/SKILL.md` documents — already takes `--project`, so it
gets the convention lookup like the drivers do. An explicit path is right in the
first two and wrong in anything holding a project, which is the same asymmetry,
applied by what the entry point already knows.

**`probe.py` is a fourth consumer this design's §0.3 census missed**, because the
census grepped for `CheckSpec(` and `probe` does not construct one: it reads
`CheckSpec.__dataclass_fields__["entropy_floor"].default` directly, at
`probe.py:245` and `:338`, to predict `grade_damage` without a reel re-render.
A prediction made against a different bar than the gate will use is worse than no
prediction — it is the cry-wolf mechanism with the sign flipped, a tool that says
"this will fail" about a render that will pass. `probe_grade` holds `rm.gates`;
`probe_geometry` holds only `geo.project`, which may not resolve, and there it
reports a **named absence** rather than silently predicting against the default.

### §2.4 The price of a blocking gate is visibility, and it is paid in three places

A `why` nobody reads is decoration. The reason is carried to every surface that
already reports a verdict:

1. **The check's own detail.** Every check that judges by a bar an author moved
   carries `"authored"`: a **list** of `{field, value, default, why}` rows, one per
   moved bar the check reads. (The first draft of this section said a single
   `{value, default, why}` object, on five named checks. Both were wrong: a check can
   read two bars — `black_frames` reads `black_floor` and `black_rel` — and the set
   of checks is not a list anyone should type.) Which checks read which bars is
   **derived** — `gates.fields_judged_by`, from `OF_CHECK` plus one named peer
   (`brief_length` borrows `length_retime_max` as its band) — so a threshold added
   later is named beside its verdict the day `OF_CHECK` learns where it belongs,
   the property `FIELDS` and `BLOCKING` already have. Today that is eleven checks:
   nine on the reel (`beat`, `key_action`, `pad_bars`, `transitions`,
   `chroma_spread`, `loudness`, `grade_faithful`, `length`, `brief_length`) and two
   on the episode (`black_frames`, `grade_damage`). The key is **absent** — never
   an empty list — when no bar the check reads was moved, so an unauthored run is
   byte-identical; a bar written at its own default is not reported (nothing
   moved); and a check that reached no verdict (`passed is None`) is skipped, so a
   row never claims a bar shaped a result that does not exist. On disk the key is
   `checks[name]["authored"]`, because `CheckResult.to_dict` flattens the detail.
   The artifact that says PASS also says the bar was moved, and why. This is the
   load-bearing one: it puts the reason next to the verdict it bought.
2. **The attestation.** `Attestation.gates`, a new list of
   `{field, value, default, scope, blocking, why}`. `spec_overrides` is left
   untouched and keeps answering its own question ("what differs from default,
   whatever the source") — it must keep working when there is no `GATES.json` at
   all. (An earlier draft said it is "the only thing that sees a hand-edited
   `variety_min`"; §0.4 records that it cannot see that either, because it runs in
   phase 1.) A
   reel-scope gate appearing in both lists is correct: it is both.
3. **`montage status`.** A `gates` block, `{present, gates, error}`, carrying
   `_constraints`' own three states — absent (`present: false`), authored (the rows
   of `Gates.record()`: value, default, scope, blocking, why), or present-and-
   unreadable (`present: true` with an `error`) — found at the same place by the
   same rule (`montage._constraints` reads
   `run / "CONSTRAINTS.json"`, and the run dir is where `project.json` lives). A
   broken `GATES.json` must read as broken, never as "no gates": reporting
   "nothing moved the bars" when the truth is "nobody can tell" is the worse of
   the two lies, which is that function's own ruling (cheap-P2-chores design
   §3.1) applied unchanged. The load refusal is caught here and nowhere else —
   `edl_to_reel` still refuses, loudly, with no waiver. An unreadable file (a
   directory, a permission) is caught with it. Once an `EPISODES.json` exists the
   block gains `frozen`: `same`, `differs` or `unreadable` — whether the set phase 1b
   froze into it is still what the file says (§6), absent when both sides are empty.
   Each delivery row that `status`/`verify` report carries the attestation's `gates`
   as well, because `overrides` there covers only reel-scope bars and carries no
   reason: an authored episode-scope bar never appears in it at all. (It read `[]` on
   every run before this slice, §0.4 — and an earlier draft of this sentence kept
   saying so in the present tense, which the slice itself had made false: phase 1
   sets the authored reel-scope bars on the manifest before `spec_overrides` runs,
   so they DO appear in `overrides` now, which §2.4 item 2 already said.) A status
   showing only `overrides` would say "no waivers" about a delivery whose sidecar
   records an authored `entropy_floor` with its reason.

### §2.5 Advisory and blocking take the same shape

Deliberately. Two shapes would mean the author must know the partition before
writing the file, and the partition is the machine's business, not theirs. What
differs is what the record says: `blocking: true/false` on every row, from
`gates.BLOCKING`, which is derived from `models._ADVISORY_CHECKS` and a
field→check map rather than typed a second time.

---

## §3 What does not change

- No threshold's default value. Not one of the eleven moves (nor `loudness_target`'s, which
  is no longer a gate but is still a default). This slice builds the
  surface; re-deriving a number on footage that does not exist yet is a different
  row, already filed, and blocked on that footage.
- No check's logic, no escalation routing, no `_ADVISORY_CHECKS` membership.
- `SAFE_ZONES`, and every stage that reads `platform`.
- `spec_overrides`, and every reading of `Attestation.overrides`.
- With no `GATES.json` present, every artifact is byte-identical.

---

## §4 The direction rejected

**A CLI flag per threshold.** Eleven flags across four drivers, each forgettable,
and `edl_to_reel` is re-run — the whole retry story is re-running it — so a dropped
flag silently reverts the bar. This is the exact defect `EDL.platform` shipped with
(housekeeping design 2026-08-12) and the reason both existing convention files have
no flag. Rejected on precedent the repo has already paid for.

**Blocking thresholds not authorable at all** — advisory only, and the six
blocking bars closed with "they stay where they are". This is the conservative
reading of the repo's own no-waiver doctrine (`episode_qc`, `CONSTRAINTS.json`),
and it is wrong here for the reason the row was promoted to P1: a bar calibrated on
one shoot will refuse correctly-shot footage from another. §9.8 of the
grade-shipped-pixels design is that scenario already on record — all eight real-run
episodes exceeded a blocking colour bar, with no waiver anywhere. The answer to a
bar that is wrong for legitimate footage cannot be "patch the engine". It is an
authored value with a recorded reason, which is what makes it reviewable.

**A `PLATFORM_LOUDNESS` table.** §0.2 — four identical rows today.

---

## §5 Acceptance

- A `GATES.json` authoring `entropy_floor` changes the bar `check_episode` judges
  against, end to end through `edl_to_reel`, and the resulting `report.json` names
  the authored value and its reason beside the verdict.
- The same for a reel-scope field through `check_reel`, including across the
  `EPISODES.json` round trip into `build_reel`.
- Each of the six §2.2 refusals fires, with the path in the message.
- The derived vocabulary equals the eleven, machine-checked against the two
  dataclasses — so the test fails the day a thirteenth threshold lands without a
  decision about it.
- With no `GATES.json`, the full suite is unchanged.

---

## §6 Honest limits

- **Authoring is not calibration.** This slice makes the eleven reachable. It does
  not make any of them right, and every one of them is still a first cut from one
  shoot. The rows that re-derive them on other footage stay open and stay blocked
  on footage that does not exist.
- **A reason is free text and nothing validates it.** `"why": "x"` loads. The
  refusal buys that a reason was *written*, never that it is true or good. What
  makes it worth anything is §2.4 — it is carried to the verdict, the attestation
  and the inspector, where a human reviewing a delivery reads it. That is the same
  honesty boundary `episode_qc` states: the gate proves presence, never that anyone
  looked.
- **Deleting `GATES.json` passes everything at default.** No silent bypass, not no
  bypass — the `CONSTRAINTS.json` ruling (design 2026-08-07 §10), unchanged.
- **`check_reel`'s own CLI is not an authoring surface, and giving it a flag was
  a mistake this design made and then measured.** Task 4 added `--gates` there on
  the reasoning that the CLI builds a `ReelCheckSpec` directly and so must be
  reachable. It is inert: `check_reel.main` calls `run(master, episodes, spec,
  report)` and supplies no music, audio, geometry, prediction, chroma or
  `brief_len`, and **every one of the nine reel-scope thresholds is read only
  behind one of those inputs** — `beat_tol` behind music, the loudness pair behind
  audio, the three geometry tolerances behind geometry, `length_retime_max` behind
  `brief_len`, `grade_residual_max` behind the prediction (whose own remedy text
  already says "the CLI cannot"), `chroma_spread_max` behind chroma. Measured: with
  all nine authored at extreme values the report and the exit code are
  byte-identical to a run with no file at all. That is precisely the knob §0.2
  rejects for reading as configurable while being inert, and the store-and-ignore
  §2.2 forbids. **The flag is deleted.** `check_reel`'s reel-scope bars are reached
  through the drivers, which supply those inputs; its standalone CLI is a
  master-and-clips checker and cannot apply a threshold whatever surface it is
  given.
  The same lens, applied to `check_episode --gates`, leaves it standing but
  partial: it is live for `black_floor` and `black_rel` (`black_frames` really
  flips) and inert for `entropy_floor`, because that CLI passes no source or plans
  and `grade_damage` is `not-checked` there for reasons that predate this slice.
- **Phase 2 carries the set frozen at phase 1b and never re-reads the file, and
  that is correct rather than a limitation.** `assemble_reel` takes an
  `EPISODES.json` path and no project path at all, so it structurally cannot look
  beside one — but it should not want to. The set in `EPISODES.json` is the record
  of *which bars judged these clips*, and re-reading the file in phase 2 would let
  a bar change between the judging and the attestation that binds it, which is the
  drift the attested-run design (2026-08-04) exists to prevent. The real cost is a
  surprise, not a defect: an operator who edits `GATES.json` between phases sees no
  effect until phase 1b is re-run, and for a reel-scope bar that means re-rendering
  every episode to change a number applied at `check_reel` time. The remedy is
  **visibility, not freshness** — `montage status` shows the authored set and says
  which phase froze it (§2.4 item 3).
- **Two of the six blocking bars cannot fire at all on an ungraded reel, so
  authoring them there does nothing.** Measured by Task 6 while building the
  proofs, on the suite's own `golden_ride_segment`: `grade_damage` divides the
  graded render's luma entropy by the plain one's, and with no grade declared the
  two renders are the *same* render, so the ratio is exactly **1.0** and no floor
  below 1 can refuse it. `grade_faithful` compares the delivered profile against
  what the episode's own declared chain predicts, and with nothing declared the
  residual measured exactly **0.0**, so no positive bar refused it either. The two
  halves differ in strength: for `entropy_floor` it is arithmetic (the ratio is 1.0
  and the floor is at most 1.0); for `grade_residual_max` it is one measurement on
  one fixture, no test pins the zero, and a bar below about 1 luma unit could in
  principle fire through encode rounding on other footage. Both are
  working as designed — they measure what a grade *did*, and nothing did anything —
  but an operator who authors `entropy_floor` on a reel with no tone pair has
  authored a no-op, and nothing says so.
  The same measurement gives the reachable range, and **the exposure it was taken
  at is part of the reading** — the figures below are `golden_ride.mp4` re-exposed
  at `DARK` 0.83x, not the neutral `golden_ride_segment`, and the same knob reads
  differently at each:

  | knob | neutral | DARK 0.83x | BRIGHT 1.09x |
  |---|---|---|---|
  | `highlight` 0.70 | 0.932 | 0.963 | 0.918 |
  | `black_point` 0.05 | 1.015 | 1.008 | 1.015 |
  | `black_point` 0.10 | 1.021 | 1.011 | 1.019 |

  Two directional facts hold at **every** exposure and are what the sensor can be
  trusted on: an ungraded episode reads exactly 1.0 (and residual exactly 0.0), and
  `black_point` *raises* the ratio rather than lowering it — so the sensor is
  directional, and a "damage" knob can move it the safe way.

  What does **not** generalize, and an earlier draft of this section asserted
  anyway: a conductor tone pair reads **1.016 on ep0 but 0.962 on ep1** of the same
  reel — below 1.0, and between the two candidate floors. So "no floor in (0, 1]
  can refuse a conductor-graded episode" is a statement about one episode, not
  about the conductor. The implementer's report carried the `(ep0)` qualifier and
  this design dropped it.
- **Gates are reel-wide, not per-episode.** One episode's legitimate grade widens
  `entropy_floor` for every episode in the reel. Per-episode gating needs an
  episode identity that survives a re-cut, and the EDL's indices do not — a re-cut
  renumbers, so a waiver would silently migrate to a different shot. Filed, §7.
- **The dataclasses now validate their own fields, and that is all refusal 6
  promises.** §2.2a closes the reachable holes: type, `bool`, finiteness and range
  on all eleven. It does not make any of the eleven *right* — a `black_floor` of
  200 is a finite number in range and would pass every check while failing every
  episode. The refusal catches a typo and a nonsense type. Judgement is the
  reason's job, and the reason is free text.
- **`check_episode --gates` is a flag, and flags are forgettable.** It is the
  standalone judge with no project to derive from, so there is no convention to use
  instead; a run through `edl_to_reel` never touches it. Recorded rather than
  solved.

---

## §7 Deferred (to the backlog)

- **A delivery loudness that moves the mixer and the gate together** — the
  `PLATFORM_LOUDNESS` table beside `SAFE_ZONES` threading its value into both
  `mix.mix` and `ReelCheckSpec.loudness_target` (§0.2/§0.2a). Today `mix` hardcodes
  −14 and all four platforms want it, so nothing is reachable and nothing is wrong;
  a broadcast −23 or Apple Music −16 deliverable needs both to move at once, which
  is why this is one row and not two. **P2** — a general tool that cannot deliver to
  broadcast loudness is a real limit, not a tidiness one.
- Per-episode gates, once an episode identity survives a re-cut (§6). P3.
- Re-deriving any of the eleven on a second shoot — the existing blocked
  calibration rows, unchanged by this slice. P4.
