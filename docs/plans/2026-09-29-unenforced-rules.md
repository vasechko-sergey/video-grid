# Unenforced rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** close three P2 rows — one by making the structure enforce a rule, one by
measurement alone, one by deleting a written rule that was never reliably honoured.

**Architecture:** `color_fidelity.validate_chroma` becomes the single validator for
the `ReelEpisode.chroma` shape, called both by the dataclass's `__post_init__` and
by `shift_from_report` on its own return, so the one producer cannot emit an
unvalidated dict. Nothing else in code changes. The four documents that told an
implementer to tick a plan's checkboxes (`development-workflow.md`, `CLAUDE.md`,
`build-status.md`, `README.md`) lose that instruction; `development-workflow.md`
gains the convention that actually governs, stated once, and `CLAUDE.md` points at it.

**Tech Stack:** Python 3, stdlib only, pytest.

**Design:** [docs/specs/2026-09-29-unenforced-rules-design.md](../specs/2026-09-29-unenforced-rules-design.md)

## Global Constraints

- **Interpreter is `.venv/bin/python`.** Scripts run as modules (`pythonpath = .`);
  never `cd scripts`.
- **Never run an installer.** No `bash setup.sh`, `brew`, `pip install`, `npm`, or
  `claude plugin update`. Verification is read-only plus pytest.
- **Never run `git checkout --`, `git restore`, `git reset --hard`, or
  `git stash`.** Undo committed content with `git show HEAD:<path> > <path>`; when
  the file being mutated is **uncommitted**, save your own copy first
  (`cp <path> <path>.bak`) and restore from that. Run any mutation on an otherwise
  clean tree and re-check `git diff --stat` after restoring.
- **Mutation batteries run under `PYTHONDONTWRITEBYTECODE=1`** — a one-byte edit
  can match the previous file's size and mtime-second and CPython serves a stale
  `.pyc`.
- **zsh does not word-split an unquoted variable** — a pytest selection held in a
  shell variable arrives as ONE argument and prints `no tests ran`, which reads
  exactly like a non-discriminating row. Write every selection literally.
- **`git add` named paths only**, never `git add -A`.
- **Code, comments, docs and commits in English.**
- **These five strings are asserted on by existing tests and must not change:**
  the three `ReelEpisode.chroma` refusal messages, verbatim; `"not-checked"`; and
  `"the report carries no grade_damage block"`.
- **Exactly one test is expected to fail, and it is not this slice's:**
  `tests/integration/test_verify_runtime.py::test_real_runtime_is_ready`. The
  0.14.0 slice added a blocking check that refuses a run whose installed plugin
  disagrees with the clone, and this machine's plugin is still 0.2.1 — the remedy
  (`claude plugin update video-grid@video-grid` plus a restart) is the user's to
  run and nobody else's. It stays red until they do, exactly as that test's own
  docstring prescribes. **Any OTHER failing test is this slice's regression.**
  (Corrected mid-slice: this plan's first draft said "fully green", which was
  wrong the moment it was written.) The suite takes ~7 minutes — run it in the
  background and wait for the real result.

---

## File structure

| File | Responsibility |
|---|---|
| `scripts/lib/color_fidelity.py` | **Modify.** New module-level `validate_chroma(c)`; `shift_from_report` calls it on its return. Stays a leaf — imports only `statistics` and `colordiff`. |
| `scripts/lib/models.py` | **Modify.** `ReelEpisode.__post_init__`'s three inline `chroma` refusals become one call to `color_fidelity.validate_chroma`. `models` already depends on four `lib` leaves; this is the fifth. |
| `tests/lib/test_color_fidelity.py` | **Modify.** Tests that the producer's own output is validated, and that the validator is the same one the dataclass uses. |
| `docs/development-workflow.md`, `CLAUDE.md` | **Modify.** The checkbox clause out, the governing convention in. |
| `docs/backlog.md`, `docs/backlog-closed.md`, `docs/build-status.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json` | **Modify.** Three closures, one P1 promotion, one P3 deferral, 0.14.1. |

---

## Task 1: One validator, both inlets

**Files:**
- Modify: `scripts/lib/color_fidelity.py`
- Modify: `scripts/lib/models.py`
- Test: `tests/lib/test_color_fidelity.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `color_fidelity.validate_chroma(c: dict | None) -> None` — raises
  `ValueError` on a bad shape, returns `None` on a good one or on `None` itself.

**Why the validator lives in `color_fidelity` and not in `models`:** the import
must run `models → color_fidelity`, never the reverse. `models` already imports
`color`, `geometry`, `look` and `outro`; `color_fidelity` imports only
`statistics` and `colordiff`. Putting the function the other way round would make
the leaf sensor depend on the contract module, and a future `models` import inside
`color_fidelity` would then be a cycle.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_color_fidelity.py`. **That file already imports the
module aliased — `from scripts.lib import color_fidelity as cf` — so the tests
below use `cf`, not `color_fidelity`; writing the full name would `NameError`.
It does not import `models`; add `from scripts.lib import models` to the
existing import block at the top of the file, never inside a function.

```python
def test_shift_from_report_validates_its_own_output():
    """The producer is the chokepoint. build_reel's reprocess arm assigns this
    function's return straight into the list check_reel reads, bypassing
    ReelEpisode.__post_init__ entirely — so a shape this function can emit but the
    carrier would refuse is a shape that reaches the consumer unchecked."""
    good = cf.shift_from_report(
        {"checks": {"grade_damage": {"region": "crop",
                                     "delta_c": 1.0, "delta_h": -2.0}}})
    assert good == {"delta_c": 1.0, "delta_h": -2.0}
    absent = cf.shift_from_report({})
    assert absent["status"] == "not-checked" and absent["reason"]


def test_validate_chroma_accepts_none_and_both_good_shapes():
    cf.validate_chroma(None)
    cf.validate_chroma({"delta_c": 0.0, "delta_h": 0.0})
    cf.validate_chroma({"status": "not-checked", "reason": "why"})


@pytest.mark.parametrize("bad,says", [
    ([], "must be a reading"),
    ({"status": "not-checked"}, "non-empty 'reason'"),
    ({"status": "not-checked", "reason": ""}, "non-empty 'reason'"),
    ({"delta_c": 1.0}, "numeric 'delta_c' and 'delta_h'"),
    ({"delta_c": True, "delta_h": 1.0}, "numeric 'delta_c' and 'delta_h'"),
])
def test_validate_chroma_refuses_each_bad_shape(bad, says):
    with pytest.raises(ValueError, match=says):
        cf.validate_chroma(bad)


def test_the_carrier_and_the_producer_share_one_validator(monkeypatch):
    """Not 'both validate' — both call the SAME function. Two validators that
    agree today are two that can disagree tomorrow, which is the shape this slice
    exists to remove: a rule kept by whoever remembers to keep it."""
    seen = []
    monkeypatch.setattr(cf, "validate_chroma",
                        lambda c: seen.append(c))
    models.ReelEpisode(manifest={}, clip="c.mp4",
                       chroma={"delta_c": 1.0, "delta_h": 2.0})
    cf.shift_from_report(
        {"checks": {"grade_damage": {"region": "crop",
                                     "delta_c": 3.0, "delta_h": 4.0}}})
    assert seen == [{"delta_c": 1.0, "delta_h": 2.0},
                    {"delta_c": 3.0, "delta_h": 4.0}]
```

If `tests/lib/test_color_fidelity.py` does not already import `pytest` or
`models`, add those imports at the top of the file — never inside a function
(`docs/coding-standards.md`).

If `models.ReelEpisode`'s constructor signature differs from the call above
(`manifest`, `clip`, `chroma`), use the real one — read the dataclass rather than
trusting this snippet, and report the difference.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_color_fidelity.py -k chroma -v`

Expected: the `validate_chroma` tests fail with
`AttributeError: module 'scripts.lib.color_fidelity' has no attribute 'validate_chroma'`.
`test_shift_from_report_validates_its_own_output` may already PASS — it pins
today's good behaviour so the extraction cannot change it. Report which did which.

- [ ] **Step 3: Extract the validator**

In `scripts/lib/color_fidelity.py`, add at module level (above `shift_from_report`):

```python
def validate_chroma(c: dict | None) -> None:
    """Refuse any shape `ReelEpisode.chroma` does not carry. `None` is legal.

    One validator, two callers: the dataclass's own `__post_init__` and
    `shift_from_report`, which validates what it is about to return. The second
    is the load-bearing one — `build_reel`'s reprocess arm assigns that return
    straight into the list `check_reel` reads, never constructing a `ReelEpisode`,
    so before this the carrier's refusals guarded one of the two inlets (design
    2026-09-29 §0.3/§2.1).

    Messages name `ReelEpisode.chroma` because that is the contract being
    enforced, not the module enforcing it; existing tests assert them verbatim."""
    if c is None:
        return
    if not isinstance(c, dict):
        raise ValueError(
            f"ReelEpisode.chroma must be a reading "
            f"{{delta_c, delta_h}} or an absence {{status, reason}}, "
            f"got {type(c).__name__} — build it with "
            f"cf.shift_from_report(report)")
    if c.get("status") == "not-checked":
        if not (isinstance(c.get("reason"), str) and c["reason"]):
            raise ValueError(
                f"ReelEpisode.chroma: a not-checked chroma must carry a "
                f"non-empty 'reason' naming the absence, got {c!r}")
        return
    if not all(isinstance(c.get(k), (int, float)) and not isinstance(c.get(k), bool)
               for k in ("delta_c", "delta_h")):
        raise ValueError(
            f"ReelEpisode.chroma must carry numeric 'delta_c' and 'delta_h' "
            f"(signed CIEDE2000 components), got {c!r} — build it with "
            f"cf.shift_from_report(report)")
```

The three message bodies are copied **verbatim** from `models.py`. Diff them
against the originals before you commit; a reworded message breaks
`check_reel`'s tests and the mutation battery.

- [ ] **Step 4: Both callers use it**

In `scripts/lib/color_fidelity.py`, `shift_from_report` returns at four points.
Route every return through the validator rather than adding four calls — bind the
result and validate once before returning, so a fifth return added later cannot
skip it:

```python
    out = _shift(report)
    validate_chroma(out)
    return out
```

…renaming the existing body to a module-level `_shift(report: dict) -> dict` that
keeps every current return statement and every comment unchanged. Keep
`shift_from_report`'s full docstring on the public function.

In `scripts/lib/models.py`, replace `ReelEpisode.__post_init__`'s entire body with:

```python
    def __post_init__(self) -> None:
        color_fidelity.validate_chroma(self.chroma)
```

and add `color_fidelity` to the existing `from scripts.lib import color` line's
module list (alphabetical: `color, color_fidelity`). Delete the now-dead inline
refusals — do not leave them beside the call.

- [ ] **Step 5: Run the targeted tests**

Run: `.venv/bin/python -m pytest tests/lib/test_color_fidelity.py tests/lib/test_models.py tests/test_check_episode.py -v`

Expected: green. If `tests/lib/test_models.py` does not exist, run whichever file
holds the `ReelEpisode.chroma` refusal tests — find it with
`grep -rln 'ReelEpisode.chroma' tests/`.

- [ ] **Step 6: Run the whole suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q` in the background.
Expected: exactly one failure, `tests/integration/test_verify_runtime.py::test_real_runtime_is_ready`, for the reason in Global Constraints — the user has not run the plugin update. Any other failure is this slice's. Record the exact counts.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/color_fidelity.py scripts/lib/models.py tests/lib/test_color_fidelity.py
git commit -m "fix(chroma): one validator for both inlets, at the producer"
```

---

## Task 2: Delete a written rule, write down the one that beat it

**Files:**
- Modify: `docs/development-workflow.md`
- Modify: `CLAUDE.md`
- Modify: `docs/build-status.md` (its header) and `README.md` (its Develop section): the
  two further copies of the instruction, which Step 3's whole-tree search finds

**Interfaces:** none — documentation only, no code, no tests.

The checkbox rule was met task by task once in 91 plans and fully ticked by its own
slice's commits in 34 of them: 53, 52, 31, 37 and 14 % across five date bands (design
§0.1). The 51-of-51 end state of the older plans is one retroactive commit, `878a713`,
and the 2026-08-06 boundary an earlier reading of it drew does not survive. The rule was
never reliably honoured, and beside it the repo already acts on an unwritten one: a plan
is the record of what was *planned* and is not amended in substance once its slice
ships. This task removes the contradiction by deleting the written rule and writing the
governing one, once.

- [ ] **Step 1: `docs/development-workflow.md`**

The convention is stated **once**, under one heading, so that `CLAUDE.md` can point at a
single anchor. Replace this paragraph in *Execution Protocol* (after the numbered list;
locate it by content):

```markdown
Spec and plan are kept **in sync** — if they drift, fix both, not one.
```

with:

```markdown
### Spec and plan

Until the slice ships — the version-bump commit ([Versioning](#versioning)) —
spec and plan are kept **in sync**: if they drift, fix both, not one. After that
the two part ways on purpose. A **design** is corrected in place when the code
moves under it. A **plan** is the record of what was *planned*, and is not amended
in substance: its account of what was planned stands, while a typo, a dead link or
a factual correction to a pointer is fine. What was *done* is carried by that
slice's per-task commits.

(Until 2026-09-29 this file also asked for the plan's checkboxes to be ticked as
each task landed. It was followed task by task exactly once, by the first plan. At
the close of their own slices, 53, 52, 31, 37 and 14 % of the 91 plans that had
landed were fully ticked, across five date bands from 2026-07-05 to 2026-09-25; the
end state reads 61 of 91 because one commit (`878a713`, 2026-08-06) ticked 27 of the
older ones retroactively. Measured 2026-09-29.)
```

Then, in *Branches & Commits*, replace:

```markdown
- After finishing a task: tick its checkboxes in the plan and update
  [build-status.md](./build-status.md); commit both.
```

with:

```markdown
- After finishing a task: update [build-status.md](./build-status.md) and commit
  it with the task's own code.
```

- [ ] **Step 2: `CLAUDE.md`**

In the **Source of truth** section, replace:

```markdown
- The design spec + core plan are the source of truth; **spec and plan stay in
  sync** — if they drift, fix **both**, not one.
- Current status and the next action live in
  [docs/build-status.md](docs/build-status.md); update it (and the plan's
  checkboxes) in the same commit after every task.
```

with a pointer only. The rule is stated in Step 1 and nowhere else, and the pointer names
the deleted checkbox rule in half a clause, because nothing else in this always-loaded
file says there ever was one:

```markdown
- The design spec is the source of truth; a plan is the record of what was
  planned. The rule for keeping the two in step, for when a plan stops being
  amended, and for why its checkboxes are no longer ticked as tasks land (this
  file used to say to) is in
  [development-workflow.md](docs/development-workflow.md#spec-and-plan).
- Current status and the next action live in
  [docs/build-status.md](docs/build-status.md); update it in the same commit
  after every task.
```

- [ ] **Step 3: Search the whole tree, and close the two further copies**

Search every tracked file, not the four paths (`CLAUDE.md docs/ skills/ references/`)
this step was first written with: `README.md` sits outside all four and would have
survived them.

```bash
git grep -n -i -E 'checkbox|check(ed|ing)? off' -- .
git grep -n -i -w -E 'tick|ticked|ticking|ticks' -- .
```

(`git grep -E` here does not support `\b`: it silently matches nothing. Use `-w`, and keep
a control that must hit.) Expected: four standing instructions to tick a plan's
checkboxes — the two Steps 1–2 remove, `docs/build-status.md`'s header and `README.md`'s
Develop section. Everything else is a plan header, a plan's own step, a description of the
deleted rule, or an unrelated idiom. Close the two further copies.

`docs/build-status.md`, header. Replace:

```markdown
**Update after every task** — tick the plan's checkboxes and add/adjust the
relevant bullet here in the same commit.
```

with:

```markdown
**Update after every task** — add/adjust the relevant bullet here in the same
commit.
```

`README.md`, Develop section. Replace, on the last line of the paragraph:

```markdown
keeps the design spec, the plan checkboxes, and `docs/build-status.md` in sync.
```

with:

```markdown
keeps the design spec and `docs/build-status.md` in sync.
```

- [ ] **Step 4: Run the doc-shaped checks**

Run: `.venv/bin/python -m pytest -q tests/test_skills_contract.py tests/test_tool_index.py tests/test_plugin_manifests.py tests/test_skill_convention.py`

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md README.md docs/build-status.md docs/development-workflow.md
git commit -m "docs: a plan is not amended after its slice ships"
```

---

## Task 3: The battery, the closures, the bump

**Files:**
- Modify: `docs/backlog.md`, `docs/backlog-closed.md`, `docs/build-status.md`,
  `CHANGELOG.md`, `.claude-plugin/plugin.json`
- Test: whichever file a GREEN battery row forces

**Interfaces:** consumes Tasks 1–2.

### Step 1: Run the mutation battery

Every row under `PYTHONDONTWRITEBYTECODE=1`, every selection written literally,
`git show HEAD:<path> > <path>` to restore, `git diff --stat` empty before the
next row.

| # | Mutation | Selection | Expect |
|---|---|---|---|
| 1 | `validate_chroma`: `if c is None: return` → `return` unconditionally | `tests/lib/test_color_fidelity.py` | RED |
| 2 | `validate_chroma`: drop the `isinstance(c, dict)` refusal | `tests/lib/test_color_fidelity.py` | RED |
| 3 | `validate_chroma`: drop the empty-`reason` half of the not-checked refusal | `tests/lib/test_color_fidelity.py` | RED |
| 4 | `validate_chroma`: drop `and not isinstance(c.get(k), bool)` | `tests/lib/test_color_fidelity.py` | RED |
| 5 | `validate_chroma`: `for k in ("delta_c", "delta_h")` → `("delta_c",)` | `tests/lib/test_color_fidelity.py` | RED |
| 6 | `shift_from_report`: drop the `validate_chroma(out)` call | `tests/lib/test_color_fidelity.py` | RED — this is the row the slice exists for; if it is GREEN the extraction bought nothing |
| 7 | `ReelEpisode.__post_init__`: drop the `validate_chroma` call | whichever file `grep -rln 'ReelEpisode.chroma' tests/` names, plus `tests/lib/test_color_fidelity.py` | RED |
| 8 | `models.py`: `__post_init__` re-inlines a *copy* of the refusals instead of calling the shared function | `tests/lib/test_color_fidelity.py` | RED via `test_the_carrier_and_the_producer_share_one_validator` — the point is one validator, not two that agree |
| 9 | `validate_chroma`: reword the first refusal's message | `tests/` (run the two files the message is asserted in; find them with `grep -rln 'must be a reading' tests/`) | RED |
| 10 | `docs/development-workflow.md`: restore the deleted checkbox bullet | — | **expected GREEN, and that is the finding.** Nothing machine-checks either version of this rule, which is precisely why it was never reliably honoured; record the non-discrimination and do NOT manufacture a check (design §2.3 rules that this rule earns deletion, not a test). |

Every GREEN that is not row 10 is a coverage hole: close it with a test confirmed
red under the mutation and green without, and say so in the report.

- [ ] **Step 2: Record the battery roll-call** in the report, row by row.

### Step 3: Version bump

`.claude-plugin/plugin.json`: `0.14.0` → `0.14.1`. PATCH — one validator moved,
no contract field, no new check, no behaviour a caller can observe except a
refusal that was already the carrier's.

Add to the top of `CHANGELOG.md`, under the intro paragraphs (heading shape
`## X.Y.Z — YYYY-MM-DD`, pinned by `tests/test_plugin_manifests.py`):

```markdown
## 0.14.1 — 2026-09-29

- The `ReelEpisode.chroma` shape now has **one** validator, called both by the
  carrier and by `color_fidelity.shift_from_report` on its own return. The
  reprocess arm of `build_reel` assigns that return straight into the list
  `check_reel` reads without ever constructing a `ReelEpisode`, so one of the two
  inlets was ungated.
- **The instruction to tick a plan's checkboxes is gone, and a plan is not amended in
  substance once its slice ships.** Four documents told an implementer to tick them
  as each task landed — `CLAUDE.md`, `development-workflow.md`, `build-status.md`
  and `README.md` — and the instruction is deleted, not repaired. It was followed
  task by task once, by the first plan; at the close of their own slices, 53, 52, 31,
  37 and 14 % of the 91 plans that had landed were fully ticked, across five date
  bands, and the end state reads 61 of 91 only because one commit ticked 27 of the
  older ones retroactively. `development-workflow.md` now states, once, that spec and
  plan are kept in sync until the slice ships — the version-bump commit — and that
  after it a design is corrected in place while its plan stays the record of what was
  planned; what was *done* is carried by each slice's per-task commits.
```

### Step 4: Sync the docs

**`docs/backlog.md`** — remove three P2 rows: the `check_reel.run(chroma=…)`
validator row, the two-producer-merges row, and the plan-checkbox row. Add one
P3 bullet under **Docs / test scaffolding** (`·`-terminated unless it is the
group's last):

```markdown
the two-producer merge predicate has no machine check — a merge of two
independently produced mappings whose result survives AS a mapping and is later
tested for a key's presence. The 2026-09-21 sweep found three sites by hand and
2026-09-29 measured that none of the two survivors can host the defect, so an AST
check would find zero true positives today; whether it is worth its false
positives is unmeasured (unenforced-rules §2.2/§5)
```

**Promote R2.4 to P1**, replacing the "P1 is empty" paragraph with a table
carrying one row: the twelve unreachable thresholds. Its text must carry the
measurement — `ReelManifest.check_spec` passes 2 of `ReelCheckSpec`'s 11 fields,
`process_episode` passes 3 of `CheckSpec`'s 7 plus `attempt`, no CLI exposes any
threshold, so 12 of 18 are unreachable and `spec_overrides` can only ever report
`variety_min` — and say that R2.4 folds into it, because a loosenable gate
without a recorded reason is the cry-wolf mechanism R2.4 was filed against.
Remove R2.4's own P2 row.

**`docs/backlog-closed.md`** — three rows under *Closed from P2*, each with the
closure note its measurement earned:
- the chroma validator: the deferring cost was one imagined remedy's;
- the two merges: closed by measurement with **no code change**, naming why
  neither site can host the defect and that the proposed comment was the defect
  class;
- the checkboxes: the row's premise ("no shipped plan has a single `[x]`") was false —
  at landing, 34 of 91 plans were fully ticked by their own slice's commits, one of
  them task by task; at HEAD, 61 of 91, the 27 older plans `878a713` ticked
  retroactively being the difference. The rule was deleted because it was never
  reliably honoured (53, 52, 31, 37 and 14 % across five date bands, design §0.1),
  and it contradicted an unwritten rule the repo already acts on.

Update `CLAUDE.md`'s archive parenthetical: **70 → 73** closure entries, and the
row count behind it **71 → 74**. Count the table rows yourself rather than
trusting these figures — this slice's own subject is a number nobody checked.

**`docs/build-status.md`** — a Done entry: the three tasks, the battery roll-call
with row 10's expected GREEN and its reason, the suite counts, and the P1
promotion.

Also add two Quick Reference rows to `CLAUDE.md` after the *Plugin staleness plan*
row, in the established design/plan pair idiom, carrying §0.1's at-landing date bands
(53, 52, 31, 37 and 14 %, with `878a713` explaining the 51-of-51 end state) and
§0.4's two-sites-cannot-host finding.

- [ ] **Step 5: Run the whole suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q` in the background.
Expected: exactly one failure, `tests/integration/test_verify_runtime.py::test_real_runtime_is_ready`, for the reason in Global Constraints. Any other failure is this slice's. Report exact counts.

- [ ] **Step 6: Commit**

```bash
git add .claude-plugin/plugin.json CHANGELOG.md CLAUDE.md docs/backlog.md docs/backlog-closed.md docs/build-status.md
git commit -m "docs: close three unenforced-rule rows, promote the threshold-surface row to P1, bump to 0.14.1"
```

---

## Self-review

**Spec coverage.** §2.1 → Task 1. §2.2 (no code, measurement recorded) → Task 3
Step 4's archive note and the P3 bullet. §2.3 → Task 2. §0.6's promotion → Task 3
Step 4. §4's honest limits ride in the design; the changelog carries the two a
user would feel.

**Placeholder scan.** No TBD/TODO. Every code step carries literal text. Row 10's
expected GREEN states its reason rather than deferring judgement.

**Type consistency.** `validate_chroma(c: dict | None) -> None` is used with that
signature in Task 1's tests, both call sites and battery rows 1–9.

**One plan defect found by self-review, before any code.** The first draft's
tests called `color_fidelity.validate_chroma(...)`, but
`tests/lib/test_color_fidelity.py` imports the module as `cf` and does not import
`models` at all — every new test would have raised `NameError` on its first line,
which reads like a missing function rather than a wrong import. Fixed in the test
snippets and stated in Step 1; the production snippets keep the real module name,
since `models.py` imports it unaliased.

**One risk named rather than assumed.** Task 1 Step 4 renames the body of
`shift_from_report` to `_shift`. That function's docstring is long and carries
four review-findings' worth of reasoning; it stays on the public function, and
the implementer must diff the moved body to confirm no comment was dropped in the
move. A lost comment here is a lost finding.

**One thing this plan does NOT check, deliberately.** Row 10 proves nothing holds
the checkbox rule in either direction. That is the slice's own thesis applied to
itself: the rule is deleted rather than tested, because after the deletion there
is no procedure left to enforce — only a description of what a plan is.
