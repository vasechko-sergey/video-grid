# Four deferred measurements — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `outro.TAIL_MIN` with a sensor-derived margin, make the no-gap
message quote the requirement that actually applied, stop `PACING.md` printing a flat
curve's noise as editorial advice, and record two diagnoses (§6.1a layer 3, the
conductor's residual) that close their rows without code.

**Architecture:** One pure module changes (`scripts/lib/outro.py`), one wire
contract gains an additive field (`OutroFit.need`), one markdown sentence stops
quoting a module constant. Everything else is documentation.

**Tech Stack:** Python 3.13, pytest, `pythonpath = .`, `.venv/bin/python`.

**Design:** [2026-08-18-deferred-measurements-design.md](../specs/2026-08-18-deferred-measurements-design.md)

---

## Global Constraints

- **`TAIL_MARGIN = 0.05` is derived, and the derivation is machine-checked.** It is
  `2.0 / vocals._SPAN_HZ` (two envelope bins at 40 Hz). A test pins the identity so
  the two cannot drift apart silently. `outro.py` still does **not** import `vocals`
  — it stays pure; only the test crosses the boundary.
- **`need = fade + TAIL_MARGIN`, not `max(fade, TAIL_MARGIN)`.** Design §1.5: at
  fade 0 they agree, but only the sum gives a positive fade a margin too.
- **`OutroFit.need` is additive on the wire.** `from_dict` defaults it; an EDL
  written before this slice must still load.
- **`test_gap_rung_needs_tail_min_not_just_the_fade` is rewritten, not deleted.** Its
  job — discriminate the floor from a bare `need = fade` — still exists at the new
  scale.
- **The `_EPS`-boundary test is not touched.** It pins the `>=`/`>` operator, and it
  builds its tie from the need it passes in, not from the constant.
- Full suite green before the branch is offered for merge; no golden may move.

---

## Task 0: `TAIL_MARGIN` replaces `TAIL_MIN`

**Files:**
- Modify: `scripts/lib/outro.py` (the constant, `fit_outro`'s `need`)
- Test: `tests/lib/test_outro.py`

- [ ] **Step 1: Write the failing tests**

Replace `test_gap_rung_needs_tail_min_not_just_the_fade` with the pair below, and
add the inversion pin. Append the derivation pin at the end of the file.

```python
def test_gap_rung_needs_the_margin_on_top_of_the_fade():
    """The replacement for test_gap_rung_needs_tail_min_not_just_the_fade (design
    §1.5). Its job is unchanged — tell `need = fade + TAIL_MARGIN` apart from a bare
    `need = fade` — only the scale moved: 0.02s of vocal-free space clears fade=0.0
    but not the 0.05s margin, so only the real floor refuses the gap rung here."""
    line = 20.0
    fit = outro.fit_outro((line,), ((line, line + 0.02),), reel_dur=20.3, bar_s=BAR,
                          fade=0.0, music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "no-gap"


def test_the_margin_is_all_a_zero_fade_needs():
    """...and the companion that stops the margin from being mistaken for the old
    0.5s floor: 0.06s clears it. Under TAIL_MIN=0.5 this same call answered
    'no-gap'."""
    line = 20.0
    fit = outro.fit_outro((line,), ((line, line + 0.06),), reel_dur=20.3, bar_s=BAR,
                          fade=0.0, music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "gap" and fit.reel_dur == line


def test_a_short_fade_inside_a_short_gap_takes_the_gap_rung():
    """design §1.3, the measured inversion, pinned as a regression. One bar line with
    0.35s of vocal-free space after it — the SHORTEST gap offset.vocal_gaps can emit
    (min_gap=0.35) — and the `fun` preset's 0.3s fade. The fade fits inside the gap
    with room to spare, so the gap rung must take it. Under `max(TAIL_MIN, fade)` this
    fell to no-gap and shipped a 1.50s fade over 1.15s of singing: the floor made the
    outcome worse against the very thing it protected."""
    line = 30.0
    fit = outro.fit_outro((line,), ((line, line + 0.35),), reel_dur=30.2, bar_s=BAR,
                          fade=0.3, music_dur=60.0, grow_max=5.0, shrink_max=5.0)
    assert fit.rung == "gap"
    assert fit.fade == 0.3
    assert fit.reel_dur == pytest.approx(line + 0.3)
    # the played tail [line, line+fade] lies entirely inside the vocal-free span
    assert fit.tail >= fit.fade


def test_the_margin_is_two_bins_of_the_vocal_envelope():
    """TAIL_MARGIN is not taste — it is the boundary quantization of the sensor that
    produces the spans it is compared against (design §1.5). vocals._SPAN_HZ is 40 Hz,
    so two bins is 0.05s. outro.py must NOT import vocals (it is pure arithmetic; the
    module docstring promises no audio IO), so the derivation lives here, machine-
    checked, instead of in a comment that could go stale."""
    from scripts.lib import vocals
    assert outro.TAIL_MARGIN == pytest.approx(2.0 / vocals._SPAN_HZ)
    assert not hasattr(outro, "TAIL_MIN"), "TAIL_MIN is deleted, not renamed in place"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_outro.py -x -q`
Expected: FAIL — `test_gap_rung_needs_the_margin_on_top_of_the_fade` and the
derivation pin fail on `AttributeError: module 'scripts.lib.outro' has no attribute
'TAIL_MARGIN'`.

- [ ] **Step 3: Make the change**

In `scripts/lib/outro.py`, replace the `TAIL_MIN` constant with:

```python
TAIL_MARGIN = 0.05  # vocal-free seconds required ON TOP OF the fade. DERIVED, not
                    # taste: two bins of the vocal envelope at vocals._SPAN_HZ (40 Hz,
                    # ~23 ms each), which is the boundary quantization of the very
                    # sensor that produced the spans this is compared against.
                    # tests/lib/test_outro.py pins the identity so the two cannot
                    # drift; outro.py itself stays free of the vocals import.
                    #
                    # It replaced TAIL_MIN = 0.5 on 2026-08-18 (design
                    # docs/specs/2026-08-18-deferred-measurements-design.md §1). That
                    # constant was wrong in KIND, not in value: the reel is
                    # `line + fade` long, so `max(TAIL_MIN, fade)` at fade < 0.5
                    # demanded silence in audio the stem never contains — and when it
                    # bit, the no-gap rung it fell to checks no tail at all and shipped
                    # a 1.5s fade over 1.15s of singing (§1.3). It also disqualified
                    # every gap in [0.35, 0.5), a band offset.vocal_gaps' own
                    # min_gap=0.35 declares valid — 16% of the real track's gaps.
```

and in `fit_outro`, replace

```python
    need = max(TAIL_MIN, float(fade))
```

with

```python
    # The fade must land in silence — that is arithmetic, not taste: the stem is
    # `line + fade` long and mix fades over [line, line + fade], so a vocal inside
    # that span is the only one anyone hears. TAIL_MARGIN rides on top for the
    # sensor's own +/-1-bin boundary error, and at fade == 0 it is the ONLY thing
    # keeping the line out of a vocal: free_after returns 0.0 for a line outside
    # every gap, and `0.0 >= 0.0 - _EPS` would accept it (design §1.5).
    need = float(fade) + TAIL_MARGIN
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_outro.py -q`
Expected: PASS. `test_fade_zero_needs_only_tail_min` still passes — its 0.6s tail
clears 0.05 as easily as it cleared 0.5 — but rename it to
`test_fade_zero_needs_only_the_margin` and update its docstring to say the margin
alone is the bar.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/outro.py tests/lib/test_outro.py
git commit -m "fix(outro): the floor guards the fade, not audio the reel never plays"
```

---

## Task 1: `OutroFit.need` and the sentence that quotes it

**Files:**
- Modify: `scripts/lib/outro.py` (`OutroFit`, both `fit_outro` return sites)
- Modify: `scripts/lib/edl.py:~457` (the no-gap sentence)
- Test: `tests/lib/test_outro.py`, `tests/lib/test_edl.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_the_fit_records_the_requirement_it_applied():
    """A bare tail cannot say what it was measured against, and the requirement is no
    longer a module constant a reader can look up: it depends on the fade. `need` is
    provenance beside `tail` (design §1.6)."""
    line = 20.0
    fit = outro.fit_outro((line,), ((line, line + 3.0),), reel_dur=20.3, bar_s=BAR,
                          fade=0.8, music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "gap" and fit.need == pytest.approx(0.85)


def test_the_no_gap_rung_records_the_requirement_that_refused_it():
    """On no-gap, `fade` is already NO_GAP_FADE — so without `need` nothing in the
    artifact can say how much space the gap rung actually wanted. It is the ORIGINAL
    fade's requirement, not the long fade's."""
    line = 20.0
    fit = outro.fit_outro((line,), ((line, line + 0.02),), reel_dur=20.3, bar_s=BAR,
                          fade=0.3, music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert fit.rung == "no-gap"
    assert fit.fade == outro.NO_GAP_FADE
    assert fit.need == pytest.approx(0.35)


def test_need_round_trips_and_an_old_artifact_still_loads():
    line = 20.0
    fit = outro.fit_outro((line,), ((line, line + 3.0),), reel_dur=20.3, bar_s=BAR,
                          fade=0.8, music_dur=42.0, grow_max=99.0, shrink_max=99.0)
    assert outro.OutroFit.from_dict(fit.to_dict()) == fit
    old = {"reel_dur": 30.0, "line": 29.5, "fade": 0.5, "tail": 1.0, "rung": "gap",
           "moved": 0.0}                       # written before this slice: no `need`
    assert outro.OutroFit.from_dict(old).need == 0.0
```

and in `tests/lib/test_edl.py`, replace the `TAIL_MIN` assertion:

```python
    # The sentence quotes the fit's OWN requirement, not a module constant: under
    # `need = fade + TAIL_MARGIN` the amount depends on the fade, and on the no-gap
    # rung `o.fade` is already NO_GAP_FADE (design §1.6).
    assert f"no bar line in range left {fit.need:.2f}s of vocal-free space" in md
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_outro.py tests/lib/test_edl.py -q`
Expected: FAIL with `TypeError: OutroFit.__init__() got an unexpected keyword
argument 'need'` / the edl assertion.

- [ ] **Step 3: Add the field**

In `OutroFit`, after `brief_len`:

```python
    need: float = 0.0                # vocal-free seconds the GAP rung required:
                                     # fade + TAIL_MARGIN, at the fade the caller
                                     # asked for. Recorded because on the "no-gap"
                                     # rung `fade` has already been replaced by
                                     # NO_GAP_FADE, so nothing else in the artifact
                                     # can say what the refusal was measured against
                                     # (design §1.6). Defaults to 0.0 so an EDL
                                     # written before 2026-08-18 still loads.
```

Add `"need": self.need` to `to_dict`, `need=d.get("need", 0.0)` to `from_dict`, and
`need=need` to the two `OutroFit(...)` constructions inside `fit_outro` that follow
the `need = ...` line (the `gap` and `no-gap` returns). Both `unchanged` returns keep
the default 0.0 — **and the field's docstring must say why, because the two are not
alike**: the early no-bars return never computed a need, while the final one is
reached after the gap rung ran and refused. 0.0 on that rung means "not applicable";
a real number there would read as a requirement applied and met.

- [ ] **Step 4: Fix the sentence**

In `scripts/lib/edl.py`, the `elif o.rung == "no-gap":` branch:

```python
            elif o.rung == "no-gap":
                why = (f"no bar line in range left {o.need:.2f}s of "
                       f"vocal-free space, so the reel ends on the nearest line at "
                       f"{o.line:.2f}s under a longer fade")
```

If `outro_mod` is now unused in that module, drop the import.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_outro.py tests/lib/test_edl.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/outro.py scripts/lib/edl.py tests/lib/test_outro.py tests/lib/test_edl.py
git commit -m "feat(outro): the fit records the requirement that judged it"
```

---

## Task 2: the comment that used `TAIL_MIN` as its example

**Files:**
- Modify: `scripts/check_reel.py` (~line 221)

- [ ] **Step 1: Rewrite the comment**

`check_reel`'s outro block explains that `_LENGTH_TOL` is a borrowed reporting
boundary and says inventing one here "would be inventing `TAIL_MIN` a second time".
`TAIL_MIN` is gone and its replacement is derived, so the example no longer lands.
Keep the point, drop the example:

```python
        # `passed` keys on the length gate's own _LENGTH_TOL — a REPORTING boundary
        # borrowed from a neighbouring check, not a claim about when an ending stops
        # resolving. Nobody has measured that, and a number invented here would be a
        # third un-measured constant wearing a threshold's clothes.
```

- [ ] **Step 2: Verify nothing else references the old name**

Run: `grep -rn "TAIL_MIN" scripts/ tests/ docs/`
Expected: only `docs/specs/2026-08-14-music-outro-fit-design.md` (its own §11.1
history), `docs/specs/2026-08-18-deferred-measurements-design.md`, this plan, and
`docs/backlog.md`'s closed row — no live code reference.

- [ ] **Step 3: Commit**

```bash
git add scripts/check_reel.py
git commit -m "docs(check_reel): the borrowed tolerance keeps its point without a dead example"
```

---

## Task 3: mutation battery

**Files:** none (verification only)

Run each mutation, confirm the named test fails, then restore by **editing the line
back** — never `git checkout --`/`git restore`/`git stash`.

| # | mutation | must fail |
|---|---|---|
| 1 | `need = float(fade) + TAIL_MARGIN` → `need = float(fade)` | `test_gap_rung_needs_the_margin_on_top_of_the_fade` |
| 2 | → `need = max(float(fade), TAIL_MARGIN)` | `test_the_fit_records_the_requirement_it_applied` (need 0.85 → 0.8) |
| 3 | → `need = max(0.5, float(fade))` (the old rule) | `test_a_short_fade_inside_a_short_gap_takes_the_gap_rung` |
| 4 | `TAIL_MARGIN = 0.05` → `0.5` | `test_the_margin_is_two_bins_of_the_vocal_envelope`, `test_the_margin_is_all_a_zero_fade_needs` |
| 5 | `TAIL_MARGIN = 0.05` → `0.0` | `test_the_margin_is_two_bins_of_the_vocal_envelope`, `test_gap_rung_needs_the_margin_on_top_of_the_fade` |
| 6 | `need=need` on the no-gap return → `need=0.0` | `test_the_no_gap_rung_records_the_requirement_that_refused_it` |
| 7 | `from_dict`'s `d.get("need", 0.0)` → `d["need"]` | `test_need_round_trips_and_an_old_artifact_still_loads` |
| 8 | `edl.py`'s `{o.need:.2f}` → `{o.fade:.2f}` | the rewritten `test_edl.py` assertion |
| 9 | the gap filter's `>= need - _EPS` → `> need - _EPS` | `test_gap_rung_tail_exactly_at_the_epsilon_floor_still_counts` |

- [ ] **Step 1: Run all nine, one at a time**

For each: apply the edit, run
`.venv/bin/python -m pytest tests/lib/test_outro.py tests/lib/test_edl.py -q`,
record pass/fail, edit back.

- [ ] **Step 2: Any row that does NOT discriminate gets a new test, not a shrug**

A mutation the suite survives is a coverage hole. Close it before moving on, the
same way the outro slice's own Task 7 did.

- [ ] **Step 3: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: the same pass/skip counts as `main` at `af907a1` (2989 passed, 2 skipped),
no golden moved.

- [ ] **Step 4: Commit any tests the battery forced**

```bash
git add tests/
git commit -m "test(outro): the battery's coverage holes, closed"
```

---

## Task 4: the anchor curve says when it has nothing to say

**Files:**
- Modify: `scripts/lib/anchors.py` (`ANCHOR_FLAT_FRAC`, `curve_contrast`, the guard)
- Modify: `scripts/pacing.py` (`anchor_map` carries the contrast, `_report` prints it)
- Test: `tests/lib/test_anchors.py`, `tests/lib/test_pacing.py`

Design §4. Auto-placing a ramp's `at` is **not built** — the sensor cannot answer the
question (7 of 8 real episodes have 100% of their curve above the anchor floor). What
IS built is the honesty: the same measurement showed `pacing --anchors` printing that
noise into `PACING.md` as advice with nothing qualifying it.

- [ ] **Step 1:** `curve_contrast(curve, rel)` returns the fraction of samples at or
      above `rel * peak`; `ANCHOR_FLAT_FRAC = 0.5`; `anchors_from_curve` gains a
      `flat_frac` parameter and returns `[]` past it. `flat_frac=1.0` still yields the
      raw maxima — the guard hides nothing.
- [ ] **Step 2:** `build_pacing`'s `anchor_map[i]` becomes `(anchors, contrast)`;
      `_report` gains a contrast column and says *"flat — no moment is
      distinguishable"* instead of an empty cell.
- [ ] **Step 3:** tests — the plateau case built from **the measured 21 samples of
      MVI_3998**, a control that must not move (a real one-spike curve), the exact-on-
      floor case that tells `>=` from `>`, and the first-ever `_report` test.
- [ ] **Step 4:** a nine-row battery. **Run it with `PYTHONDONTWRITEBYTECODE=1`** — a
      one-byte mutation can leave the file the same size and mtime-second as the
      previous row's and CPython then reuses the stale `.pyc`. Row 7 (the driver's
      contrast wiring) is expected to survive; rows 8 and 9 exist so the `_report` test
      is not vacuous.

```bash
git add scripts/lib/anchors.py scripts/pacing.py tests/lib/test_anchors.py tests/lib/test_pacing.py
git commit -m "fix(anchors): a flat curve reports that it is flat, instead of naming noise"
```

---

## Task 5: docs sync

**Files:**
- Modify: `docs/specs/2026-08-17-mood-grade-design.md` (§3 correction)
- Modify: `docs/specs/2026-08-14-music-outro-fit-design.md` (§11.1 disposition)
- Modify: `docs/specs/2026-07-16-cast-hero-pin-design.md` (§11 layer-3 disposition)
- Modify: `docs/specs/2026-08-09-speed-ramp-design.md` (§13 anchor disposition)
- Modify: `docs/backlog.md`, `docs/build-status.md`, `CLAUDE.md`

- [ ] **Step 1: mood-grade §3**

Add an as-built blockquote under the table: the residual is diagnosed, all three
listed candidates are eliminated by measurement, the cause is `curves=all` being
per-channel against a luma target, the magnitude is content-dependent (DJI −7 at
p95, Canon −3, grayscale exactly 0), and §3.4's trap — "fixing" the 160-wide
measurement alone makes the delivered p95 worse, because the two biases currently
cancel. Its conclusion (the 15–20-unit vectors) is unchanged and say so.

- [ ] **Step 2: music-outro-fit §11.1**

`TAIL_MIN` was that design's own honest limit. Record that the row it spawned came
back and the constant is gone — wrong in kind, not in value — with a pointer.

- [ ] **Step 3: cast-hero-pin §11**

The layer-3 deferral gets its disposition: remainder real and orthogonal to
track-stitch, evidence says do not build, trigger named (a `continuity` stop or an
episode-QC `hero` finding).

- [ ] **Step 4: backlog**

Flip three rows to `✅` with their measurements. File the four new rows from design
§6. Re-check the P2 count.

- [ ] **Step 5: build-status + CLAUDE.md**

A Done entry; two Quick Reference rows (design + plan).

- [ ] **Step 6: Commit**

```bash
git add docs/ CLAUDE.md
git commit -m "docs: three deferred measurements, and what they overturned"
```

---

## Self-Review

**Spec coverage.** §1 → Tasks 0–2. §2 → Task 4 step 3 (docs only, by design §2.5).
§3 → Task 4 step 1 (docs only, by design §3.5). §4's five items map to Tasks 0–2 and
4. §5's six testing points map to Tasks 0, 1 and 3. §6's four rows → Task 4 step 4.

**The weak point.** Task 3 row 9 re-runs a test the outro slice already wrote, and
that test's own docstring explains it can only discriminate because it builds its tie
bit-exactly from the need. Under the new rule the need is `0.5 + 0.05` rather than
`0.5`, and the test constructs `tail = 0.5 - _EPS` against `fade=0.5` — which is now
`need = 0.55`, so the tail no longer sits on the boundary and the row stops
discriminating. **Task 0 must re-point that test at the new need** (`tail = 0.55 -
_EPS`), or row 9 will pass for the wrong reason. Called out here because the plan's
Global Constraints say the test is "not touched" — that is true of its *intent*, not
of its literal number, and the two are easy to confuse.

**Type consistency.** `need: float` is the same type as `tail`/`fade`/`moved`; it is
read in `edl.py` as `o.need` and in tests as `fit.need`; `to_dict`/`from_dict` use
the key `"need"` throughout.
