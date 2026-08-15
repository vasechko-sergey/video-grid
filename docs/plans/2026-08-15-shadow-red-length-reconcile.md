# shadow_red + length-reconcile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close two P2 backlog rows — make `color.shadow_red_arg` hold identity above its
return point and refuse the parameter pair that inverts its toe, and make `edit_plan build`
refuse a pacing spine fitted to a different track than the music it is handed.

**Architecture:** Both are local. `shadow_red_arg` gains a refusal and swaps three hardcoded
identity anchors for a density derived from `ret`; `build_edl` gains one comparison beside the
`--music`-without-`--pacing` log it already carries. No contract changes, no new module, no
ffmpeg stage touched.

**Tech Stack:** Python 3, pytest, real ffmpeg (`lib/ffbin`) for the ramp probe.

**Design:** [2026-08-15-shadow-red-length-reconcile-design.md](../specs/2026-08-15-shadow-red-length-reconcile-design.md)

---

## Global Constraints

Binding on every task. A reviewer checks against these, not against taste.

1. **Fail loud.** New rejections `raise ValueError` with the measured reason and the remedy —
   never clamp, never warn-and-continue. See [coding-standards.md](../coding-standards.md).
2. **Imports at the top of the module.** No import inside a function, in source or in tests.
3. **Typed.** Every new/edited function keeps full annotations.
4. **TDD.** Write the failing test, run it, watch it fail for the stated reason, then
   implement. A test that passes before the implementation is a broken test.
5. **No new magic numbers.** `_TEMPO_TOL` and the anchor step are named constants with a
   comment saying what measured them.
6. **Do not touch** `scripts/mix.py`, `scripts/deliver.py`, `scripts/check_reel.py`,
   `scripts/build_reel.py`, `scripts/edl_to_reel.py`, `scripts/pacing.py`, or
   `scripts/lib/pacing.py`. This slice changes two files of production code and nothing else.
7. **Never** run `git checkout --`, `git restore`, `git reset --hard`, or `git stash`.
8. **Never** install anything (`brew`, `pip install`, `npm`, `setup.sh`). The venv is ready;
   verification is read-only plus `pytest`.
9. Python is `.venv/bin/python`. Scripts run as modules (`pythonpath = .`).
10. Commit per task with a message saying *why*, trailer
    `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Do **not** push.

---

## Task 0: `shadow_red_arg` refuses `lift >= ret`

**Why:** the toe maps `x ↦ x + lift·(1 − x/ret)`, slope `1 − lift/ret`. At `lift > ret` that
slope is negative — the curve decreases, which bands. Design §1.3. The existing bounds allow
`ret=0.10, lift=0.20`.

**Files:**
- Modify: `scripts/lib/color.py` (`shadow_red_arg`)
- Test: `tests/lib/test_color.py`

- [x] **Step 1: Write the failing tests**

Add to `tests/lib/test_color.py`, after `test_shadow_red_toe_only_pins_the_top`:

```python
def test_shadow_red_refuses_a_lift_that_inverts_the_toe():
    # slope in the toe is 1 - lift/ret; at lift > ret it is negative, so the mapping
    # DECREASES and the shadows band. Measured 2026-08-15 (design §1.3): every
    # non-monotone cell in the scan had lift >= ret, and none with lift < ret did.
    with pytest.raises(ValueError, match="inverts"):
        color.shadow_red_arg(0.20, ret=0.10)


def test_shadow_red_refuses_a_lift_equal_to_the_return_point():
    # lift == ret is slope exactly 0: a flat plateau in the toe, where 8-bit rounding
    # decides whether the output wobbles. Refused rather than left to the quantizer.
    with pytest.raises(ValueError, match="inverts"):
        color.shadow_red_arg(0.10, ret=0.10)


def test_shadow_red_accepts_a_lift_below_the_return_point():
    # the paired proof: the refusal must not swallow the configuration that ships.
    assert color.shadow_red_arg(0.20).startswith(",curves=r='")
    assert color.shadow_red_arg(0.09, ret=0.10).startswith(",curves=r='")
```

- [x] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py -k shadow_red -v`
Expected: the two `raises` tests FAIL (`DID NOT RAISE ValueError`); the acceptance test PASSES.

- [x] **Step 3: Implement**

In `scripts/lib/color.py`, inside `shadow_red_arg`, **after** the existing `ret` range check
(`if not 0 < ret <= 0.45:`), add:

```python
    if lift >= ret:
        raise ValueError(
            f"shadow_red {lift} inverts the toe against a return point of {ret} — the toe "
            f"maps x -> x + lift*(1 - x/ret), whose slope is 1 - lift/ret, so at lift >= ret "
            f"the curve stops rising and the shadows band. Lower the lift below the return "
            f"point, or move the return point above the lift")
```

- [x] **Step 4: Run the tests again**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py -k shadow_red -v`
Expected: all PASS.

- [x] **Step 5: Run the whole colour surface**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py tests/lib/test_models.py -q`
Expected: PASS. (The shipped default is `ret=0.25`, `SHADOW_RED_MAX=0.20`, so `lift < ret`
always holds and nothing existing should trip. If something does, report it — do not relax
the refusal.)

- [x] **Step 6: Commit**

```bash
git add scripts/lib/color.py tests/lib/test_color.py
git commit -m "fix(color): shadow_red refuses the lift that inverts its own toe"
```

---

## Task 1: densify `shadow_red_arg`'s identity anchors

**Why:** three anchors (0.50/0.70/0.85) pin the fitted spline at three points, not the curve
between them. Measured at the shipped `ret=0.25`: **−6** codes at `lift=0.20`, worst at code 79
(x≈0.31) — inside the gap between `ret` and the first anchor. Design §1.1–§1.2, §1.4.

**Files:**
- Modify: `scripts/lib/color.py` (`SHADOW_RED_ANCHORS` deleted, `shadow_red_arg` body +
  docstring)
- Test: `tests/lib/test_color.py`

- [x] **Step 1: Write the failing test**

Replace `test_shadow_red_toe_only_pins_the_top` in `tests/lib/test_color.py` with:

```python
def test_shadow_red_pins_the_identity_region_densely():
    # Three anchors (0.50/0.70/0.85) pinned three POINTS, not the spline between them:
    # measured -6 codes at the shipped ret, worst at x~0.31, in the gap right after the
    # return point (design 2026-08-15 §1.1). Anchors now step 0.05 from `ret` to 1.0.
    frag = color.shadow_red_arg(0.1)
    assert frag.startswith(",curves=r='") and frag.endswith("'")
    pts = frag[len(",curves=r='"):-1].split(" ")
    xs = [float(p.split("/")[0]) for p in pts]
    assert xs[:4] == [0.0, 0.0833, 0.1667, 0.25]              # the toe, unchanged
    above = xs[4:]
    assert above[0] == 0.3 and above[-1] == 1.0
    assert len(above) == 15                                    # 0.30..0.95 step .05, plus 1.0
    assert all(abs(b - a - 0.05) < 1e-9 for a, b in zip(above, above[1:]))
    assert all(p.split("/")[0] == p.split("/")[1] for p in pts[4:])   # identity, exactly


def test_shadow_red_density_follows_a_non_default_return_point():
    # derived from `ret`, not hardcoded — a caller passing a non-default return point
    # must not silently fall back to the old sparsity (the twin's knee lesson).
    frag = color.shadow_red_arg(0.05, ret=0.40)
    xs = [float(p.split("/")[0]) for p in frag[len(",curves=r='"):-1].split(" ")]
    assert xs[4] == 0.45 and xs[-1] == 1.0
```

- [x] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py -k shadow_red -v`
Expected: both new tests FAIL — today's fragment ends `0.85/0.85 1/1`, so `above[0]` is 0.50,
not 0.30.

- [x] **Step 3: Implement**

In `scripts/lib/color.py`:

(a) Delete the `SHADOW_RED_ANCHORS` line and put the step in its place:

```python
SHADOW_RED_MAX = 0.20      # past this the toe goes visibly pink instead of neutral
SHADOW_RED_RETURN = 0.25   # where the lift has decayed to nothing (64/255)
SHADOW_RED_STEP = 0.05     # identity anchors above the return point. 0.05, not the twin's
                           # 0.1: measured 2026-08-15, 0.1 still leaves -2 codes at the
                           # shipped return point and -3 at the domain's worst, 0.05 leaves 0
```

(b) Replace the two lines that build the anchors:

```python
    pts += [f"{a:.2f}/{a:.2f}" for a in SHADOW_RED_ANCHORS] + ["1/1"]
```

with:

```python
    # identity anchors every SHADOW_RED_STEP from `ret` to 1.0, derived from `ret` rather
    # than hardcoded, so a non-default return point gets a dense region too.
    hi_xs = []
    i = 1
    while ret + i * SHADOW_RED_STEP < 1.0 - 1e-9:
        hi_xs.append(ret + i * SHADOW_RED_STEP)
        i += 1
    hi_xs.append(1.0)
    pts += [f"{x:.4f}/{x:.4f}" for x in hi_xs]
```

(c) Replace the docstring's final paragraph — the one beginning "The anchors above `ret` are
load-bearing" — with:

```
    The anchors above `ret` are load-bearing, not decoration: ffmpeg fits a spline, and with
    the segment from `ret` to 1.0 unpinned it SAGS — measured, a red board lost 7 units of
    R-G from a curve that never meant to touch it. They used to be three hardcoded points
    (0.50/0.70/0.85), which pinned the spline AT three points and not the curve it draws
    BETWEEN them — the same defect `highlight_red_arg` fixed on 2026-08-13, cited there and
    left standing here. Probed losslessly through a 256-step ramp (reframe.verify_tone's
    method), 2026-08-15: at the shipped ret=0.25 those three anchors left **-6** codes at
    SHADOW_RED_MAX, worst at code 79 (x~0.31) — in the gap immediately after the return
    point — and up to -14 across the legal (lift, ret) domain. Stepping SHADOW_RED_STEP from
    `ret` instead measures **exactly identity** at the shipped ret for every legal lift, and
    at most one code anywhere legal.

    Why 0.05 when the twin steps 0.1: this curve returns from a lift to identity over a range
    of `ret` rather than easing across a wide shoulder, so its kink is steeper and 0.1 still
    leaves -2 codes where it ships. The divergence is deliberate — do not "fix" it back. The
    cost is three single-code non-monotone cells against 0.1's one, all where `lift` is within
    0.02 of `ret` and the toe's slope is already near zero; that is 8-bit rounding on a flat
    region, and the shipped ret has none of them (design 2026-08-15 §1.4/§6).
```

- [x] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py -q`
Expected: PASS.

- [x] **Step 5: Prove nothing else read the deleted constant**

Run: `grep -rn "SHADOW_RED_ANCHORS" --include="*.py" scripts/ tests/`
Expected: no output. (Two docs still mention it; Task 4 fixes those.)

- [x] **Step 6: Run the surfaces that render a grade**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py tests/lib/test_manifest.py tests/lib/test_models.py -q`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add scripts/lib/color.py tests/lib/test_color.py
git commit -m "fix(color): shadow_red pins its identity region densely, not at three points"
```

---

## Task 2: the real-ffmpeg ramp proof

**Why:** the unit test above asserts the emitted *control points*. Only pushing pixels through
ffmpeg proves the *spline* stays at identity — that is the whole lesson of this defect. Mirror
of `test_highlight_red_sub_knee_residual_is_small_and_monotone`, which already lives in this
file with the `_ramp_r_lut` helper the new test reuses.

**Files:**
- Modify: `tests/integration/test_reframe.py`

- [x] **Step 1: Write the test**

Append to `tests/integration/test_reframe.py`, immediately after
`test_highlight_red_sub_knee_residual_is_small_and_monotone`:

```python
@pytest.mark.integration
def test_shadow_red_identity_region_holds_after_the_return_point(need_filter):
    """The mirror of the test above, at the other end of the picture. shadow_red_arg's
    three hardcoded anchors (0.50/0.70/0.85) pinned three POINTS above the return point,
    not the spline between them: probed 2026-08-15 at the shipped ret=0.25, the region
    above `ret` sagged -6 codes at SHADOW_RED_MAX, worst at code 79 (x~0.31) — inside the
    gap between the return point and the first anchor. Densified to a step every 0.05 from
    `ret`, the same probe measures exactly 0 at every legal lift.

    The bound below is +1/-1: strictly tighter than the -3 the old anchors left at lift=0.1
    and the -6 they left at SHADOW_RED_MAX, so a regression back to sparse anchors fails
    here, and loose enough that 8-bit rounding cannot flake it.
    """
    need_filter("curves")
    ret_code = round(color.SHADOW_RED_RETURN * 255)        # 64 at the default 0.25

    for lift in (0.1, color.SHADOW_RED_MAX):
        lut = _ramp_r_lut(color.shadow_red_arg(lift))
        above = [lut[i] - i for i in range(ret_code, 256)]
        assert max(above) <= 1, (
            f"lift={lift}: identity region rises +{max(above)} above the return point — "
            "the densified anchors no longer hold the spline at identity")
        assert min(above) >= -1, (
            f"lift={lift}: identity region sags {min(above)} above the return point — "
            "the densified anchors no longer hold the spline at identity")
        assert all(lut[i + 1] >= lut[i] for i in range(255)), (
            f"lift={lift}: the curve is not monotone — a non-monotone transfer curve bands")
```

- [x] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/integration/test_reframe.py -k "shadow_red or highlight_red" -v`
Expected: PASS (both).

- [x] **Step 3: Prove the test discriminates**

Temporarily restore the sparse anchors — in `scripts/lib/color.py` replace the `hi_xs` block's
final line with `pts += [f"{a:.2f}/{a:.2f}" for a in (0.50, 0.70, 0.85)] + ["1/1"]` — and run
the same command. Expected: the new test FAILS with `identity region sags -6`. **Then revert
that edit by hand** (retype the correct line; do not use `git checkout`/`git restore`) and
re-run to confirm PASS. Record both outputs in the report.

- [x] **Step 4: Commit**

```bash
git add tests/integration/test_reframe.py
git commit -m "test(color): pixels prove shadow_red's identity region, not just its anchors"
```

---

## Task 3: `build_edl` refuses a spine fitted to a different track

**Why:** the 2026-08-03 run bound a spine fitted at **140.625 BPM** while `MUSIC.json` carried
**110.294** — `PACING.json` was nine hours older than the music and belonged to the track that
was swapped out. `edit_plan build` is handed both files and compares nothing.
`_bind_pacing`'s half-beat guard is a duration guard and never speaks about the track. Design
§2.2.

**Files:**
- Modify: `scripts/edit_plan.py` (`_TEMPO_TOL`, a guard in `build_edl`)
- Test: `tests/lib/test_edit_plan.py`

- [x] **Step 1: Write the failing tests**

Add to `tests/lib/test_edit_plan.py`, beside `test_music_without_pacing_says_it_did_nothing`
(~line 1293). These reuse the file's own `_footage()` / `_sel3()` / `_spine2()` trio — the
precedented shape from `test_build_edl_pacing_binds_slot_and_applies_the_fit` — whose spine is
**120.0 BPM**. `bars` is left at its `()` default so `_apply_outro` early-returns and the test
isolates the tempo guard.

```python
def test_build_edl_refuses_a_spine_fitted_to_a_different_track():
    # The 2026-08-03 run: PACING.json fitted at 140.625 BPM against a 110.294 BPM
    # MUSIC.json — nine hours older, and belonging to the track that was swapped out.
    # _bind_pacing's half-beat guard is a DURATION guard: it fires only once a stale
    # spine is bound, and it never says which track the spine came from (design
    # 2026-08-15 §2.2). _spine2() is 120.0 BPM.
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=90.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0)
    with pytest.raises(ValueError, match="DIFFERENT track"):
        edit_plan.build_edl(_footage(), _sel3(), pacing=_spine2(), music=music)


def test_build_edl_accepts_a_spine_and_music_from_the_same_track():
    # The paired proof. pacing.py copies MusicSpec.tempo straight into the spine, so an
    # honest pair is bit-identical and must still build — without this, a blanket
    # "--pacing with --music always raises" would satisfy the test above.
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.0,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0)
    edl = edit_plan.build_edl(_footage(), _sel3(), pacing=_spine2(), music=music)
    assert edl.episodes[0].beat_slot == 0


def test_build_edl_tolerates_a_sub_half_bpm_tempo_difference():
    # _TEMPO_TOL exists so a re-analysis or a hand-typed tempo does not trip the guard.
    # 0.4 BPM is inside it; the 30 BPM case above proves the guard is not merely absent.
    music = MusicSpec(track="t.wav", start_offset=0.0, duration=42.0, tempo=120.4,
                      beats=(0.0, 0.5), energy=(0.1,), energy_hz=2.0)
    edl = edit_plan.build_edl(_footage(), _sel3(), pacing=_spine2(), music=music)
    assert edl.episodes[0].beat_slot == 0
```

- [x] **Step 2: Run them and watch the first fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -k "different_track or same_track or sub_half_bpm" -v`
Expected: the refusal test FAILS (`DID NOT RAISE`); the two acceptance tests PASS.

- [x] **Step 3: Implement**

(a) In `scripts/edit_plan.py`, beside the other module constants (near `_SNAP_TOL`, line ~201):

```python
_TEMPO_TOL = 0.5      # BPM. A spine copies MusicSpec.tempo straight through, so an honest
                      # pair is bit-identical; half a BPM is far below any musically
                      # meaningful difference and far above float round-trip noise.
```

(b) In `build_edl`, **immediately after** the `if music is not None and pacing is None:` block
that logs the no-op case, and **before** `if pacing is not None:`:

```python
    if music is not None and pacing is not None and abs(pacing.tempo - music.tempo) > _TEMPO_TOL:
        # The one live defect behind "the length figures do not reconcile" (design
        # 2026-08-15 §2). _bind_pacing's half-beat guard is a DURATION guard: it fires only
        # once a stale spine is actually bound, and it never says which track the spine
        # came from. The 2026-08-03 run shipped a 140.625 BPM spine against a 110.294 BPM
        # reel and no stage objected.
        raise ValueError(
            f"pacing: the spine was fitted at {pacing.tempo:.3f} BPM but this MUSIC.json is "
            f"{music.tempo:.3f} BPM — further apart than the {_TEMPO_TOL} BPM two reads of "
            f"one track can differ by, so this PACING.json belongs to a DIFFERENT track. "
            f"Re-run pacing against this MUSIC.json before binding")
```

- [x] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py -q`
Expected: PASS.

- [x] **Step 5: Run the drivers that call build_edl**

Run: `.venv/bin/python -m pytest tests/lib/test_edit_plan.py tests/integration/test_outro.py tests/integration/test_edit_plan.py -q`
(Skip any path that does not exist; report which you ran.)
Expected: PASS. If an existing test passes a mismatched pair, that test was relying on the
hole — fix the test's tempo to match, and say so in the report.

- [x] **Step 6: Commit**

```bash
git add scripts/edit_plan.py tests/lib/test_edit_plan.py
git commit -m "fix(edit-plan): refuse a pacing spine fitted to a different track"
```

---

## Task 4: docs sync + the whole suite

**Why:** the deferral rule — a slice is not finished until its design's `§Deferred` items have
backlog rows. Two rows close, one P3 row gets unblocked, two design docs carry a deleted
constant's name.

**Files:**
- Modify: `docs/backlog.md`, `docs/build-status.md`, `CLAUDE.md`,
  `docs/specs/2026-07-26-colour-stage-design.md`,
  `docs/plans/2026-07-26-colour-stage.md`
- Modify: `docs/plans/2026-08-15-shadow-red-length-reconcile.md` (tick every checkbox)

- [x] **Step 1: `docs/backlog.md` — close both rows**

In **P2**, replace the `color.shadow_red_arg` row's status `○` with `✅` and rewrite its text
to record: the measured −6 at the shipped `ret` (worst at code 79, x≈0.31) and −14 across the
legal domain; the densification to a 0.05 step derived from `ret` (exactly identity at the
shipped `ret`); **and the second defect the probe found** — `lift >= ret` inverts the toe,
refused, and it is the refusal (not the density) that removes every non-monotone cell.

Replace the "The length figures do not reconcile" row's `○` with `✅` and rewrite it around the
design's §2.1 table: `EDL.target_dur` 34.072 = `sum(play_dur())` to 0.0004s, the master at
34.051 (21ms, under one frame), `PACING.json` nine hours stale at 140.625 BPM against
`MUSIC.json`'s 110.294, `EDL.md`'s 32.4s already fixed by `to_markdown`, and **"30.317" not
reproducible from any artifact**. Name the fix: the `_TEMPO_TOL` refusal.

- [x] **Step 2: `docs/backlog.md` — the unblock and the new rows**

In **P3 → Music**, annotate the `enforce SPEC.length_s` line: it is **unblocked** — the
diagnosis found the target it would gate (`EDL.target_dur`) already equals what the master
delivers, and only a stale artifact disagreed.

Fold into the existing P2 "Make pacing's round trip a fixed point again" row one sentence: the
strong form of the staleness check is recording the music file's **digest** on `Spine` — equal
tempo does not prove the same track — and it belongs with that row because it rewrites the same
file (design §6/§7).

Add to **P3 → Colour** one line: `shadow_red_arg`'s densified curve keeps three single-code
non-monotone cells where `lift` is within 0.02 of `ret` (0.15/0.14, 0.20/0.18, 0.20/0.19);
step 0.1 has one instead of three; the shipped `ret` has none (design §6).

Update `_Last updated:_` to 2026-08-15.

- [x] **Step 3: `docs/build-status.md`**

Add a Done entry for this slice in the file's existing style: what landed, the measured
numbers, and the two honest limits (equal tempo ≠ same track; the near-`ret` wobble).

- [x] **Step 4: `CLAUDE.md` — one registry row**

Add one row to the Quick Reference table pointing at the design, in the table's voice: what it
fixed and the one load-bearing surprise (the queued row's `−6` was real, but the same probe
found `lift >= ret` inverts the toe, and the length figures had **already** reconciled —
only a nine-hour-stale `PACING.json` disagreed). One row, not two.

- [x] **Step 5: the two stale `SHADOW_RED_ANCHORS` mentions**

`docs/specs/2026-07-26-colour-stage-design.md` lines ~120 and ~130 and
`docs/plans/2026-07-26-colour-stage.md` line ~78 name the deleted constant. Correct them to
`SHADOW_RED_STEP=0.05` with a pointer to this design — do not rewrite the surrounding
paragraphs.

Run: `grep -rn "SHADOW_RED_ANCHORS" --include="*.py" --include="*.md" . | grep -v '^./.venv'`
Expected: only this slice's own design/plan, which quote it historically.

- [x] **Step 6: Tick every checkbox in this plan file**

- [x] **Step 7: The whole suite, bytecode cleared**

```bash
find . -name __pycache__ -type d -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null; .venv/bin/python -m pytest -q
```

Expected: EXIT 0, no new failures, and the same 2 pre-existing skips (torchreid weights,
off-network iTunes). Report the exact counts.

- [x] **Step 8: Commit**

```bash
git add -A
git commit -m "docs: two P2 rows close — the shadow_red toe, and the length figures that already agreed"
```

---

## Mutation checks (steps, not suggestions)

Run after Task 4, before the final review. Each: make the mutation by hand, run the named
test, confirm it FAILS, then undo the mutation by hand (never `git checkout`/`git restore`)
and confirm it passes again. Record every result.

| # | Mutation | Must fail |
|---|---|---|
| 1 | `lift >= ret` → `lift > ret` | `test_shadow_red_refuses_a_lift_equal_to_the_return_point` |
| 2 | `SHADOW_RED_STEP` 0.05 → 0.10 | `test_shadow_red_pins_the_identity_region_densely` (the `len(above) == 15` and step assertions) |
| 3 | anchors back to `(0.50, 0.70, 0.85)` + `1/1` | `test_shadow_red_identity_region_holds_after_the_return_point` (real ffmpeg, `sags -6`) |
| 4 | `hi_xs` built from a hardcoded 0.25 instead of `ret` | `test_shadow_red_density_follows_a_non_default_return_point` |
| 5 | `> _TEMPO_TOL` → `> 100.0` | `test_build_edl_refuses_a_spine_fitted_to_a_different_track` |
| 6 | drop the `pacing is not None` conjunct from the tempo guard | `test_music_without_pacing_says_it_did_nothing` (an `AttributeError` on `None.tempo` counts) |
| 7 | the tempo guard moved *after* `_bind_pacing` | `test_build_edl_refuses_a_spine_fitted_to_a_different_track` must still raise, but with the WRONG message (`_bind_pacing`'s half-beat text). If it still matches `DIFFERENT track`, the ordering is untested — say so and add the assertion |

If a mutation does **not** fail its test, that is a coverage hole: write the test that closes
it, then re-run. Report every hole found.
