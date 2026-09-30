# Threshold surface — an authoring surface must carry its threshold's blast radius

**Status:** design, 2026-09-30. Backlog P1 (promoted by the unenforced-rules slice,
design 2026-09-29 §0.6), with R2.4 folded in.

**Row, as filed:** twelve of the eighteen fields of `ReelCheckSpec` and `CheckSpec`
are unreachable from any authoring surface — no CLI flag, no manifest field, no
convention file. A tool with twelve bars nailed to one shoot is single-domain by
construction.

---

## §0 Measurements

### §0.1 The twelve are not one population — and the split is the design

The row treats all twelve alike. They are not alike: five govern a check that
cannot block, seven govern one that can. Widening an advisory tolerance changes a
number in a report nobody gates on. Widening a blocking bar is a waiver written in
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
| `loudness_target` | `ReelCheckSpec` | `loudness` | **BLOCKING** |
| `loudness_tol` | `ReelCheckSpec` | `loudness` | **BLOCKING** |
| `grade_residual_max` | `ReelCheckSpec` | `grade_faithful` | **BLOCKING** |
| `length_retime_max` | `ReelCheckSpec` | `brief_length` (advisory) **and** `build_reel`'s absorb | **BLOCKING in effect** |
| `black_floor` | `CheckSpec` | `black` | **BLOCKING** |
| `black_rel` | `CheckSpec` | `black` | **BLOCKING** |
| `entropy_floor` | `CheckSpec` | `grade_damage` | **BLOCKING** |

**Seven blocking, five advisory.** `length_retime_max` is the one that had to be
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

`ReelCheckSpec` reaches the checks through `ReelManifest.check_spec()`
(`models.py:1716`), which is two lines:

```python
def check_spec(self) -> ReelCheckSpec:
    return ReelCheckSpec(self.target_dur, self.variety_min)
```

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
`check_spec()` sets only `target_dur` and `variety_min`, the diff can report
**exactly one field** — `variety_min` — and only when the EDL moved it. Its
docstring already promises more:

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

### §0.6 The vocabulary is exactly the twelve, and it derives itself

`ReelCheckSpec` has 11 fields, `CheckSpec` 7, sharing the name `target_dur`: 17
distinct names. Five are authored elsewhere and must be refused rather than
duplicated —

| name | where it is really authored |
|---|---|
| `target_dur` | the EDL (`EDL.target_dur`, from the footage via `_back_edge_target`) |
| `variety_min` | `ReelManifest.variety_min`, off the EDL |
| `composition` | `Manifest.composition`, per episode |
| `grid` | `Manifest.grid`, per episode |
| `attempt` | the retry loop's own counter, never an author's |

— leaving **17 − 5 = 12**, which is the row's twelve, arrived at from the
dataclasses rather than from the row. So the vocabulary is derived, not typed:
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
2. an unknown field name, naming the twelve;
3. one of the five §0.6 names, naming **where that value is really authored** (a
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
  seven blocking bars — accept `True`, `nan`, `inf`, `"6"`, `None` and `-1` without
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

`edl_to_reel` finds the file beside the `project_path` it already holds, once, in
`_phase_one_setup`, and threads it two ways:

`ReelManifest.gates` is **one new dict field carrying the whole authored set**,
both scopes together, not the reel subset. That single decision removes the second
carrier:

- `ReelManifest.check_spec()` applies the subset `ReelCheckSpec` owns and ignores
  the rest.
- Phase 1's pool passes the subset `CheckSpec` owns into
  `process_episode(..., gates=…)` — a parameter, not a `Manifest` field, which
  keeps a gate a **run policy** rather than a per-episode value an agent could
  author into an EDL.
- `build_reel`'s reprocess arm re-runs `process_episode` and reads the same subset
  off `rm.gates`. Without the whole set on the manifest it would have nowhere to
  read it from, and a reprocessed episode would be judged against a different bar
  than its siblings — silently, which is the shape of defect the retry-record slice
  (design 2026-09-24 §0.7) just finished closing in the neighbouring field.

It round-trips through `EPISODES.json`, and `ReelManifest.from_dict` re-validates
it by constructing `Gates` from the loaded dict rather than trusting it — the
`OutroFit.from_dict` idiom (pacing-fixed-point design §5), for the same reason: a
hand-edited or truncated `EPISODES.json` is one of the two live inlets to
`build_reel` and does not pass through `edl_to_reel`'s loader.

`check_episode`'s own CLI gains `--gates PATH`: it is the standalone judge and has
no project to derive from. An explicit path is right there and wrong in
`edl_to_reel`, which does have one.

### §2.4 The price of a blocking gate is visibility, and it is paid in three places

A `why` nobody reads is decoration. The reason is carried to every surface that
already reports a verdict:

1. **The check's own detail.** `loudness`, `grade_faithful`, `black`,
   `grade_damage` and the length band each already emit a detail dict; an authored
   bar adds `"authored": {"value": …, "default": …, "why": …}`. The artifact that
   says PASS also says the bar was moved, and why. This is the load-bearing one: it
   puts the reason next to the verdict it bought.
2. **The attestation.** `Attestation.gates`, a new list of
   `{field, value, default, scope, blocking, why}`. `spec_overrides` is left
   untouched and keeps answering its own question ("what differs from default,
   whatever the source") — it must keep working when there is no `GATES.json` at
   all, and it is the only thing that sees the EDL-sourced `variety_min`. A
   reel-scope gate appearing in both lists is correct: it is both.
3. **`montage status`.** A `gates` row carrying `_constraints`' own three states
   — absent, authored (with a count), or present-and-unreadable — found at the
   same place by the same rule (`montage._constraints` reads
   `run / "CONSTRAINTS.json"`, and the run dir is where `project.json` lives). A
   broken `GATES.json` must read as broken, never as "no gates": reporting
   "nothing moved the bars" when the truth is "nobody can tell" is the worse of
   the two lies, which is that function's own ruling (cheap-P2-chores design
   §3.1) applied unchanged. The load refusal is caught here and nowhere else —
   `edl_to_reel` still refuses, loudly, with no waiver.

### §2.5 Advisory and blocking take the same shape

Deliberately. Two shapes would mean the author must know the partition before
writing the file, and the partition is the machine's business, not theirs. What
differs is what the record says: `blocking: true/false` on every row, from
`gates.BLOCKING`, which is derived from `models._ADVISORY_CHECKS` and a
field→check map rather than typed a second time.

---

## §3 What does not change

- No threshold's default value. Not one of the twelve moves. This slice builds the
  surface; re-deriving a number on footage that does not exist yet is a different
  row, already filed, and blocked on that footage.
- No check's logic, no escalation routing, no `_ADVISORY_CHECKS` membership.
- `SAFE_ZONES`, and every stage that reads `platform`.
- `spec_overrides`, and every reading of `Attestation.overrides`.
- With no `GATES.json` present, every artifact is byte-identical.

---

## §4 The direction rejected

**A CLI flag per threshold.** Twelve flags across four drivers, each forgettable,
and `edl_to_reel` is re-run — the whole retry story is re-running it — so a dropped
flag silently reverts the bar. This is the exact defect `EDL.platform` shipped with
(housekeeping design 2026-08-12) and the reason both existing convention files have
no flag. Rejected on precedent the repo has already paid for.

**Blocking thresholds not authorable at all** — advisory only, and the seven
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
- The derived vocabulary equals the twelve, machine-checked against the two
  dataclasses — so the test fails the day a thirteenth threshold lands without a
  decision about it.
- With no `GATES.json`, the full suite is unchanged.

---

## §6 Honest limits

- **Authoring is not calibration.** This slice makes the twelve reachable. It does
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
- **Gates are reel-wide, not per-episode.** One episode's legitimate grade widens
  `entropy_floor` for every episode in the reel. Per-episode gating needs an
  episode identity that survives a re-cut, and the EDL's indices do not — a re-cut
  renumbers, so a waiver would silently migrate to a different shot. Filed, §7.
- **The dataclasses now validate their own fields, and that is all refusal 6
  promises.** §2.2a closes the reachable holes: type, `bool`, finiteness and range
  on all twelve. It does not make any of the twelve *right* — a `black_floor` of
  200 is a finite number in range and would pass every check while failing every
  episode. The refusal catches a typo and a nonsense type. Judgement is the
  reason's job, and the reason is free text.
- **`check_episode --gates` is a flag, and flags are forgettable.** It is the
  standalone judge with no project to derive from, so there is no convention to use
  instead; a run through `edl_to_reel` never touches it. Recorded rather than
  solved.

---

## §7 Deferred (to the backlog)

- `PLATFORM_LOUDNESS` beside `SAFE_ZONES`, when a platform with a target other than
  −14 LUFS enters the table (§0.2). P3.
- Per-episode gates, once an episode identity survives a re-cut (§6). P3.
- Re-deriving any of the twelve on a second shoot — the existing blocked
  calibration rows, unchanged by this slice. P4.
