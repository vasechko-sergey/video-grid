# Mood → Grade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Displace `match_grade`'s common tone target in the direction `SPEC.mood`
asks for, so a reel cut from mixed cameras not only reads as one grade but as the
*brief's* grade — with no second colour stage and no extra encode.

**Architecture:** One new field on the existing `MoodPreset` (beside `look`), one
new pure function in `matchgrade`, and one new flag on the `match_grade build`
driver. `common_target` and everything downstream of it are untouched.

**Tech Stack:** Python, ffmpeg (`curves`, via the existing `color.tone_arg`), pytest.

**Design:** [2026-08-17-mood-grade-design.md](../specs/2026-08-17-mood-grade-design.md)

---

## Global Constraints

- **Fail-loud contract, imports at top, typing** — `docs/coding-standards.md`.
- **Whole-object asserts** where a test compares a returned object.
- Scripts run as modules; Python is `.venv/bin/python`; `pythonpath = .`.
- ffmpeg landmines apply: `-ss` AFTER `-i`; `lutrgb` banned.
- Commit messages say *why*. One commit per task.
- **Do not** run installers or mutate the environment. Verification is read-only
  plus pytest.
- **Do not** run `git checkout --`, `git restore`, `git reset --hard`, `git stash`.
- **The numbers are measured** (design §3/§4/§5). Do not round the bias vectors or
  invent new ones.
- **The off switch is an anti-regression pin, not a nicety**: with no `--spec`,
  the authored target must equal today's median exactly.

## File Structure

| File | Change |
|---|---|
| `scripts/lib/moodpreset.py` | `MoodPreset.tone_bias` + validation + 4 vectors + BALANCED zero |
| `scripts/lib/matchgrade.py` | `MOOD_FLOOR`, `biased_target` |
| `scripts/match_grade.py` | `--spec`, resolve, apply, report the bias/`k`/note |
| `tests/lib/test_moodpreset.py` | the field |
| `tests/lib/test_matchgrade.py` | the displacement + the scale |
| `tests/lib/test_match_grade.py` | the driver, incl. the off-switch pin |
| `tests/integration/test_matchgrade.py` | the real-ffmpeg visibility proof |
| `docs/backlog.md`, `docs/build-status.md`, `CLAUDE.md` | sync |

---

### Task 0: `MoodPreset.tone_bias`

**Files:**
- Modify: `scripts/lib/moodpreset.py`
- Test: `tests/lib/test_moodpreset.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_every_preset_carries_a_tone_bias_and_balanced_carries_none():
    """The bias is a taste, so the no-match fallback must not have one — the same
    rule BALANCED.look already states: a skipped brief must not silently impose a
    look (design 2026-08-17 §1)."""
    assert moodpreset.BALANCED.tone_bias == (0.0, 0.0, 0.0)
    assert {p.name: p.tone_bias for p in moodpreset.PRESETS} == {
        "fun": (10.0, 18.0, 8.0),
        "epic": (-16.0, 0.0, 16.0),
        "moody": (-18.0, -16.0, -8.0),
        "nostalgic": (20.0, 0.0, -18.0),
    }


def test_tone_bias_must_be_three_numbers():
    with pytest.raises(ValueError, match="tone_bias"):
        moodpreset.MoodPreset("x", None, {"close": 0.3, "medium": 0.4, "wide": 0.3},
                              (1.0, 2.0), tone_bias=(1.0, 2.0))
```

- [ ] **Step 2: Run them and watch them fail**

```bash
.venv/bin/python -m pytest tests/lib/test_moodpreset.py -k tone_bias -v
```

Expected: FAIL — `MoodPreset` has no `tone_bias`.

- [ ] **Step 3: Add the field**

In `scripts/lib/moodpreset.py`, after the `look` field:

```python
    tone_bias: tuple[float, float, float] = (0.0, 0.0, 0.0)
    """(p5, p50, p95) luma-unit displacement of the reel's common tone target
    (design 2026-08-17 §4). Hand-authored FIRST CUT at ~15-20 units — above the
    conductor's own measured 6.5-11.5-unit delivery error (§3), which is the real
    floor and is why a subtle table cannot work. Spent by match_grade, never by
    edit_plan."""
```

and in `__post_init__`, after the `look` check:

```python
        if not (isinstance(self.tone_bias, (tuple, list)) and len(self.tone_bias) == 3
                and all(_num(v) for v in self.tone_bias)):
            raise ValueError(f"MoodPreset.tone_bias must be three numbers — a (p5, p50, p95) "
                             f"luma displacement — got {self.tone_bias!r}")
        self.tone_bias = tuple(float(v) for v in self.tone_bias)
```

Then add the vectors to the four `PRESETS` rows:
`fun` → `tone_bias=(10.0, 18.0, 8.0)`, `epic` → `(-16.0, 0.0, 16.0)`,
`moody` → `(-18.0, -16.0, -8.0)`, `nostalgic` → `(20.0, 0.0, -18.0)`.
`BALANCED` takes the default and gets a comment pointing at the `look` docstring
above it — the rule is identical and stated once.

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/lib/test_moodpreset.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/moodpreset.py tests/lib/test_moodpreset.py
git commit -m "$(cat <<'EOF'
feat(moodpreset): a mood asks something of the grade, not only the cut

The preset table already carries what a mood wants from shot selection, pace and
the reel's finish. tone_bias adds what it wants from the grade: a (p5, p50, p95)
displacement of the common tone target, in the same luma vocabulary the conductor
already speaks.

The magnitudes are ~15-20 units because measurement says a subtle table cannot
work -- the conductor lands 6.5-11.5 units from its own target, so anything below
that disappears into its error rather than into the picture.

BALANCED stays at zero for the reason its look field already gives: a brief that
was skipped or did not match must not have a taste imposed on it silently.
EOF
)"
```

---

### Task 1: `matchgrade.biased_target`

**Files:**
- Modify: `scripts/lib/matchgrade.py`
- Test: `tests/lib/test_matchgrade.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_biased_target_displaces_and_reports_a_full_scale():
    """The real run's measured median, displaced by the moody vector. k == 1.0
    means the whole displacement survived (design §5)."""
    got, k = matchgrade.biased_target((49.5, 100.0, 194.5), (-18.0, -16.0, -8.0))
    assert (got, k) == ((31.5, 84.0, 186.5), 1.0)


def test_biased_target_scales_the_whole_vector_rather_than_clamping_one_anchor():
    """Measured (design §5): at a median of (110, 170, 250) the epic vector cannot
    have its +16 highlight lift, and clamping THAT anchor alone would leave
    'crush the blacks' — a different mood. Scaling keeps the direction and loses
    only magnitude, and k reports how much."""
    got, k = matchgrade.biased_target((110.0, 170.0, 250.0), (-16.0, 0.0, 16.0))
    assert k == pytest.approx(5.0 / 16.0)
    assert got == pytest.approx((105.0, 170.0, 255.0))


def test_biased_target_is_the_identity_at_a_zero_bias():
    """The off switch: no mood -> the median is handed on untouched, so a run
    without --spec authors exactly what it authored before this slice."""
    t = (49.5, 100.0, 194.5)
    assert matchgrade.biased_target(t, (0.0, 0.0, 0.0)) == (t, 1.0)


def test_a_scaled_bias_below_the_floor_is_named_ineffective():
    """5 luma units is under the conductor's own delivery error, so the grade
    cannot show it. The stage does not refuse — it reports (design §5)."""
    assert matchgrade.bias_ineffective((-16.0, 0.0, 16.0), 5.0 / 16.0) is True
    assert matchgrade.bias_ineffective((-16.0, 0.0, 16.0), 1.0) is False
```

- [ ] **Step 2: Run them and watch them fail**

```bash
.venv/bin/python -m pytest tests/lib/test_matchgrade.py -k "biased_target or ineffective" -v
```

Expected: FAIL — no such functions.

- [ ] **Step 3: Implement**

Add to `scripts/lib/matchgrade.py`, after `_repair_gaps`:

```python
MOOD_FLOOR = 10.0      # luma units below which a displacement cannot be seen. Measured
                       # (design §3): rendering an episode through the curve the conductor
                       # authors lands 6.5-11.5 units from the target it asked for, so a
                       # displacement smaller than that disappears into the conductor's own
                       # error. Not a taste threshold — a sensor-resolution one.


def biased_target(target: Profile, bias: tuple[float, float, float]) -> tuple[Profile, float]:
    """Displace the common target by a mood's `bias`, scaled to stay inside 0-255.

    Returns (displaced target, k) where k in [0, 1] is how much of the asked
    displacement survived. SCALING THE WHOLE VECTOR is the contract, not clamping the
    offending anchor: `epic` is "deep blacks AND bright highs", and clamping only its
    highlight lift would silently ship "crush the blacks", which is a different mood
    (design §5). Scaling keeps the direction and loses magnitude, and k lets the caller
    say so.

    Measured across eight plausible reel medians: k == 1 on five, and scaling fires only
    on bright targets and only for the two presets that push p95 up — at a median of
    (110, 170, 250), fun keeps 0.62 and epic 0.31 of its vector. moody and nostalgic
    never scale, because both pull inward.

    A zero bias returns the target unchanged with k == 1.0 — the off switch a run
    without --spec takes, byte-identical to the pre-2026-08-17 conductor."""
    k = 1.0
    for a, d in zip(target, bias):
        if d and not (0.0 <= a + d <= 255.0):
            limit = (255.0 - a) / d if d > 0 else (0.0 - a) / d
            k = min(k, max(limit, 0.0))
    if k == 1.0 and not any(bias):
        return (tuple(float(v) for v in target), 1.0)
    return _repair_gaps(tuple(a + d * k for a, d in zip(target, bias))), k


def bias_ineffective(bias: tuple[float, float, float], k: float,
                     floor: float = MOOD_FLOOR) -> bool:
    """True when scaling has taken the bias's LARGEST component under the floor — the
    grade cannot show it, so the report must (design §5). Judged on the largest
    component because a mood's smaller axes ride along with its dominant one."""
    return bool(any(bias)) and max(abs(d) for d in bias) * k < floor
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/lib/test_matchgrade.py -q
```

Expected: PASS, including the pre-existing `common_target` tests — its signature
did not move.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/matchgrade.py tests/lib/test_matchgrade.py
git commit -m "$(cat <<'EOF'
feat(matchgrade): displace the common target, and report what did not fit

biased_target sits beside common_target rather than inside it: the median is
still exactly the median, and a run with no mood gets the same Profile object it
got before. What is new is a second, separately testable step.

Scaling the whole vector instead of clamping the offending anchor is the part
worth reading twice. Clamping is the obvious implementation and it is wrong --
epic without its highlight lift is not a weaker epic, it is a different mood.
Scale keeps the direction, and returning k lets the driver say how much of the
mood the footage had room for. Measured: on a reel whose median highlights sit at
250, epic keeps 31% of its vector, which is under the floor where any grade
change is visible at all -- hence bias_ineffective, which reports rather than
refuses.
EOF
)"
```

---

### Task 2: the driver reads `--spec` and reports

**Files:**
- Modify: `scripts/match_grade.py`
- Test: `tests/lib/test_match_grade.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_conduct_without_a_spec_authors_the_plain_median(monkeypatch, tmp_path):
    """The anti-regression pin for the off switch: no --spec must reproduce the
    pre-mood conductor exactly, not approximately."""
    ...  # build a 2-episode EDL, stub measure_profile to return two known profiles
    _, target, _ = match_grade.conduct(edl, str(tmp_path))
    assert target == matchgrade.common_target([p0, p1])


def test_conduct_with_a_mood_displaces_the_target(monkeypatch, tmp_path):
    _, target, _ = match_grade.conduct(edl, str(tmp_path), preset=moodpreset.resolve("moody"))
    plain = matchgrade.common_target([p0, p1])
    assert target == matchgrade.biased_target(plain, (-18.0, -16.0, -8.0))[0]


def test_a_balanced_brief_displaces_nothing(monkeypatch, tmp_path):
    """resolve() returned the fallback, so no mood matched — and an unmatched
    brief must not have a grade imposed on it (design §1)."""
    _, target, _ = match_grade.conduct(edl, str(tmp_path), preset=moodpreset.BALANCED)
    assert target == matchgrade.common_target([p0, p1])


def test_the_report_names_the_mood_the_bias_and_the_scale():
    md = match_grade._report_md(["a.mp4"], (30.0, 80.0, 180.0), [decision], 4.0,
                                preset=moodpreset.resolve("epic"), k=0.31)
    assert "epic" in md and "mood-bias-ineffective" in md
```

- [ ] **Step 2: Run them and watch them fail**

```bash
.venv/bin/python -m pytest tests/lib/test_match_grade.py -q
```

Expected: FAIL — `conduct` takes no `preset`.

- [ ] **Step 3: Thread the preset through `conduct`**

Give `conduct` a keyword-only `preset: moodpreset.MoodPreset | None = None`, and
after `target = matchgrade.common_target(profiles)`:

```python
    bias = preset.tone_bias if preset is not None and preset.name != "balanced" else (0.0, 0.0, 0.0)
    target, k = matchgrade.biased_target(target, bias)
```

Return `(edl, target, decisions, k)` — a 4-tuple; update `write_match`'s unpack.
The `preset.name != "balanced"` test is the same exact-string check
`write_edit_plan` uses for `look`, and for the same reason.

- [ ] **Step 4: Report the mood**

`_report_md` gains `preset` and `k` keyword arguments. Its header line becomes:

```python
    head = f"# Match-grade — target {_triple(target)} (p5/p50/p95), eps {eps:g}"
    if preset is not None and preset.name != "balanced":
        head += f"\n\nMood **{preset.name}** displaced the target by {preset.tone_bias}"
        if k < 1.0:
            head += f", scaled to {k:.0%} (the reel's own range left no room for the rest)"
        if matchgrade.bias_ineffective(preset.tone_bias, k):
            head += (f"\n\n> **mood-bias-ineffective** — what survived is under "
                     f"{matchgrade.MOOD_FLOOR:g} luma units, which is below this "
                     f"conductor's own delivery error, so the mood will not be visible "
                     f"in the grade.")
    elif preset is not None:
        head += "\n\nNo mood matched the brief — the target is the plain median."
```

- [ ] **Step 5: Wire the CLI**

`write_match` gains `spec: str | None = None`; it resolves once:

```python
    preset = moodpreset.resolve(Spec.from_json(spec).mood) if spec else None
```

and passes it to `conduct`. The returned status dict gains
`"mood": preset.name if preset else None` and `"bias_scale": k`.

Add the flag:

```python
    b.add_argument("--spec", default=None,
                   help="SPEC.json — its mood displaces the common tone target "
                        "(absent: the plain median, exactly as before)")
```

- [ ] **Step 6: Run the tests**

```bash
.venv/bin/python -m pytest tests/lib/test_match_grade.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/match_grade.py tests/lib/test_match_grade.py
git commit -m "$(cat <<'EOF'
feat(match-grade): the brief's mood reaches the reel's grade

--spec, the same flag and the same file edit_plan already takes, resolved through
the same moodpreset.resolve. EDL.variety.preset was the other candidate carrier
and lost on measurement: it is None on the one real run on disk, and a carrier
absent from real artifacts is a bad carrier.

MATCH.md now names the mood, the displacement and -- when the reel's own range
could not fit it -- how much survived, because a bias scaled under the floor is
invisible in the pixels and has nowhere else to be seen.
EOF
)"
```

---

### Task 3: the real-ffmpeg visibility proof

**Files:**
- Modify: `tests/integration/test_matchgrade.py`

- [ ] **Step 1: Write the proof**

The claim to prove is the one every look change in this project must prove: the
declared change reached the pixels. Render one clip through the pair the
conductor authors for a **moody** brief and for no brief, and measure both:

```python
def test_a_moody_bias_renders_darker_than_the_plain_median(tmp_path, sample_clip):
    """The visibility proof (design §7). Not 'the curve was built' — the delivered
    frame's own percentiles must sit below the unbiased render's, in the direction
    the preset asked for."""
    prof = measure_profile(sample_clip, at=0.5)
    plain = matchgrade.common_target([prof, (40.0, 90.0, 180.0)])
    moody, k = matchgrade.biased_target(plain, moodpreset.resolve("moody").tone_bias)
    assert k == 1.0                       # the fixture leaves room; if not, the test lies
    got_plain = _render_and_measure(sample_clip, color.tone_arg(prof, plain), tmp_path)
    got_moody = _render_and_measure(sample_clip, color.tone_arg(prof, moody), tmp_path)
    assert got_moody[0] < got_plain[0] and got_moody[1] < got_plain[1]
```

Write `_render_and_measure` as a module-level helper: one ffmpeg pass with
`-ss` AFTER `-i`, `-vf <chain>`, then `measure_profile` on the output.

- [ ] **Step 2: Run it**

```bash
.venv/bin/python -m pytest tests/integration/test_matchgrade.py -q
```

Expected: PASS. If `k != 1.0` on the fixture, the assertion catches it — do not
weaken that line; pick different profiles so the fixture has room.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_matchgrade.py
git commit -m "test(matchgrade): the mood displacement reaches the pixels"
```

---

### Task 4: mutation battery + the whole suite

**These are steps, not suggestions.** Watch each red, then restore by editing the
line back — never with `git checkout`.

- [ ] **Step 1: Mutation — clamp instead of scale**

Replace `biased_target`'s scaling with a per-anchor clamp
(`min(255.0, max(0.0, a + d))`).

Expected: `test_biased_target_scales_the_whole_vector_rather_than_clamping_one_anchor`
FAILS. Restore.

- [ ] **Step 2: Mutation — swallow `k`**

Return `1.0` unconditionally as the second element.

Expected: the scale test FAILS. Restore.

- [ ] **Step 3: Mutation — apply the bias to BALANCED too**

Drop the `preset.name != "balanced"` test in `conduct`.

Expected: `test_a_balanced_brief_displaces_nothing` FAILS. Restore.

- [ ] **Step 4: Mutation — the off switch leaks**

Make `conduct`'s default bias the `fun` vector instead of zeros.

Expected: `test_conduct_without_a_spec_authors_the_plain_median` FAILS. Restore.

- [ ] **Step 5: Mutation — the floor is ignored**

Make `bias_ineffective` return `False` always.

Expected: the report test FAILS. Restore.

- [ ] **Step 6: Full suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: the pre-slice baseline (2963 passed, 2 skipped) plus this slice's new
tests. **No golden may move** — the off switch means an unmooded conduct is
byte-identical. If one moves, stop and report which.

- [ ] **Step 7: Commit any test changes**

```bash
git add -A tests/
git commit -m "test(mood-grade): the mutation battery"
```

(Skip if nothing changed; say so in the report.)

---

### Task 5: Docs, backlog, registry

**Files:**
- Modify: `docs/backlog.md`, `docs/build-status.md`, `CLAUDE.md`,
  `skills/match-grade/SKILL.md`

- [ ] **Step 1: Close the P2 row**

Flip "Mood → grade" to `✅` with the measured content: the `--spec` carrier
decision and why `EDL.variety` lost, the table, the §3 floor, and §5's scale rule
with `epic`'s measured collapse at bright medians.

**#9 does not close** — its P3 image-treatment tail stays open. Update the
three-buckets note near the top of the file, which currently says "P2 (mood
biasing the grade) and P3 ... stay open".

- [ ] **Step 2: Open the four deferrals (design §8)**

P2: diagnose the conductor's 6.5–11.5-unit residual (its own slice — it bounds
how fine any grade table can be, and this slice measured it without explaining
it). P3: a range-relative displacement; chroma as well as luma. P4: a per-episode
mood override.

- [ ] **Step 3: build-status Done entry**

Name the measurements: the eight real profiles and their median
`(49.5, 100.0, 194.5)`; the `none`-row residual that set the floor; the eight-target
scale scan; and that `EDL.variety` is `None` on the real run, which is what chose
`--spec`.

- [ ] **Step 4: `match-grade` SKILL**

Add `--spec` to the invocation, and one paragraph on reading `MATCH.md`'s mood
line — especially the `mood-bias-ineffective` note, which is the one thing in the
report a human must act on (by choosing a different mood or accepting a
consistency-only grade).

- [ ] **Step 5: CLAUDE.md registry rows**

Design + plan, in the established style.

- [ ] **Step 6: Verify the docs against the code**

```bash
grep -n "tone_bias" scripts/lib/moodpreset.py && grep -n "MOOD_FLOOR" scripts/lib/matchgrade.py
```

Every number quoted in the docs must match.

- [ ] **Step 7: Commit**

```bash
git add docs/ CLAUDE.md skills/
git commit -m "$(cat <<'EOF'
docs(mood-grade): close the grade half of #9, and file what it could not do

The row is closed; #9 is not -- its image-treatment tail is still open, and the
three-buckets note at the top of the queue now says so correctly.

Four deferrals filed, one of them found by this slice rather than planned by it:
the conductor misses its own target by 6.5-11.5 luma units, which is what makes a
coarse mood table the only kind that can work here. Nobody knows why yet, so it is
a row, not a fix.
EOF
)"
```

---

## Self-Review

**Spec coverage.** §1 → Task 2 Steps 3/5. §2 → Task 0. §3 → Task 1's `MOOD_FLOOR`.
§4 → Task 0 Step 3. §5 → Task 1 + Task 2 Step 4. §6 → Task 1 Step 4 (the
untouched `common_target` tests) and Task 4 Step 6. §7 → Tasks 0–3. §8 → Task 5
Step 2. §9 → Task 5 Steps 1/3.

**The plan's own weak point.** Task 3 proves the displacement reaches the pixels
and proves the *direction*. It does not prove — and nothing in this repo can —
that the four vectors mean what their four names claim. That is design §9's first
limit, and it is a CP3 judgement on real footage, not a test. Do not add a test
that appears to check it.

**A second one, smaller.** The mutation in Task 4 Step 4 makes the *default* bias
non-zero, which is a stand-in for the real risk (a future edit letting the mood
leak into a no-`--spec` run). The genuine protection is the byte-identity of the
goldens in Step 6, which is why that step says "no golden may move" rather than
"the suite passes".

**Type consistency.** `biased_target` returns `(Profile, float)` everywhere;
`conduct` returns a 4-tuple and `write_match` is the only caller — checked, it is
(the CLI goes through `write_match`).
