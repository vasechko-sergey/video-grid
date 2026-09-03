# The Mood Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A mood word commands only what it can be held to — `tone_bias`
becomes authorable, the window band becomes a parameter that cannot change
silently, and the preset's length band is reconciled against what was
actually carved.

**Architecture:** Three independent seams on one theme. (A) `Spec` gains
`tone_bias`; `match_grade` resolves authored-over-preset and says which won.
(B) `intake`'s `WIN_MIN`/`WIN_MAX` become a band parameter that joins
`intake_cache.clip_key`, so a changed band is a cache MISS instead of stale
boundaries; `Footage` records what was carved. (C) `write_edit_plan`
reconciles the preset's band against the carved one on the lower bound only,
because windows can be joined but never split.

**Tech Stack:** Python 3, dataclass config-specs, pytest. No ffmpeg change,
no render change.

**Design:** [docs/specs/2026-09-03-mood-contract-design.md](../specs/2026-09-03-mood-contract-design.md)

## Global Constraints

- **Fail loud with a remedy.** Every refusal raises `ValueError` (or returns
  a `stop_and_report` finding) whose message names the offending value AND
  what to do about it. See `docs/coding-standards.md`.
- **Imports at top of file.** No function-local imports.
- **Scripts run as modules.** `pythonpath = .`; run tests as
  `.venv/bin/python -m pytest`, never `python scripts/foo.py`.
- **`None` and `(0, 0, 0)` are different for `tone_bias`.** `None` means
  "not authored — take the preset's"; `(0, 0, 0)` means "no displacement".
  A default of `(0, 0, 0)` makes the second inexpressible and is wrong.
- **Only the LOWER bound of the band is checkable** (design §4). A preset
  ceiling above the carved ceiling is legal — span merge reaches it, proven
  by the run's own 5.80 s episode against a 4.0 s ceiling.
- **`band` is a required keyword in `intake_cache`** (`clip_key`, `store`,
  `load`) — exactly like `proxy_long_side`, and for the same reason: a
  silent default there serves stale window boundaries. It gets a DEFAULT on
  the drivers (`intake`, `_process_clip`, `carve_windows`), exactly like
  `sample_fps`.
- **One definition of the default band.** `carve.DEFAULT_BAND = (1.2, 4.0)`.
  `intake` imports it; nothing re-declares it.
- **Whole-object asserts** where a dataclass is the subject — assert the
  object or its `to_dict()`, not one field at a time.
- **Mutation batteries run under `PYTHONDONTWRITEBYTECODE=1`.** A one-byte
  edit can match the previous size and mtime-second, and CPython then serves
  a stale `.pyc`.
- **Commit per task**, message body says *why*, ends with
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **Never** run installers (`brew`, `pip install`, `setup.sh`) or
  `git checkout --` / `git restore` / `git reset --hard` / `git stash`. To
  restore a committed file: `git show HEAD:<path> > <path>`. To restore an
  UNCOMMITTED file, you must save your own copy first — there is no other
  route back.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `scripts/lib/spec.py` | `Spec.tone_bias` — the authored displacement | 1 |
| `scripts/match_grade.py` | resolve authored-over-preset, report the source | 2 |
| `scripts/lib/footage.py` | `Footage.band` — what was carved | 3 |
| `scripts/lib/carve.py` | `DEFAULT_BAND` — the one definition | 4 |
| `scripts/intake.py` | band parameter + CLI + fills `Footage.band` | 4 |
| `scripts/lib/intake_cache.py` | band in the key, `CACHE_VERSION` 8→9 | 5 |
| `scripts/lib/moodpreset.py` | `reconcile_band` — the pure lower-bound check | 6 |
| `scripts/edit_plan.py` | the reconciliation gate + not-checked log | 6 |

---

### Task 1: `Spec.tone_bias`

**Files:**
- Modify: `scripts/lib/spec.py:16-25` (fields), `:41-66` (validation), `:80-95` (`from_dict`/`to_dict`)
- Test: `tests/lib/test_spec.py`

**Interfaces:**
- Produces: `Spec.tone_bias: tuple | None` — `None` or a 3-tuple of floats
  `(p5, p50, p95)` luma displacement. Task 2 reads it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_spec.py`:

```python
def test_spec_tone_bias_defaults_to_none_not_zero():
    # None and (0,0,0) mean different things: None = "take the preset's taste",
    # (0,0,0) = "this mood, leave my colour alone". A zero default would make
    # the second inexpressible (design 2026-09-03 §2).
    assert Spec(**GOOD).tone_bias is None


def test_spec_accepts_an_authored_tone_bias():
    s = Spec(**{**GOOD, "tone_bias": [10, 0, -18]})
    assert s.tone_bias == (10.0, 0.0, -18.0)


def test_spec_accepts_an_explicit_zero_bias():
    s = Spec(**{**GOOD, "tone_bias": (0, 0, 0)})
    assert s.tone_bias == (0.0, 0.0, 0.0)


def test_spec_rejects_a_two_element_tone_bias():
    with pytest.raises(ValueError, match="tone_bias"):
        Spec(**{**GOOD, "tone_bias": (10, 0)})


def test_spec_rejects_a_bool_in_tone_bias():
    with pytest.raises(ValueError, match="tone_bias"):
        Spec(**{**GOOD, "tone_bias": (10, True, 0)})


def test_spec_round_trips_tone_bias_through_json_shape():
    s = Spec(**{**GOOD, "tone_bias": (10, 0, -18)})
    assert Spec.from_dict(s.to_dict()) == s


def test_spec_round_trips_an_absent_tone_bias():
    s = Spec(**GOOD)
    assert Spec.from_dict(s.to_dict()).tone_bias is None
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_spec.py -k tone_bias -v
```

Expected: FAIL — `Spec.__init__() got an unexpected keyword argument 'tone_bias'`.

- [ ] **Step 3: Add the field**

In `scripts/lib/spec.py`, add after `cast: tuple = ()`:

```python
    tone_bias: tuple | None = None   # (p5, p50, p95) luma displacement, or None
```

- [ ] **Step 4: Add the validation**

In `__post_init__`, after the `cast` block:

```python
        if self.tone_bias is not None:
            if not (isinstance(self.tone_bias, (tuple, list)) and len(self.tone_bias) == 3
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                            for v in self.tone_bias)):
                raise ValueError(
                    f"Spec.tone_bias must be three numbers — a (p5, p50, p95) luma "
                    f"displacement, the same shape as MoodPreset.tone_bias — or null to "
                    f"take the mood preset's own. Got {self.tone_bias!r}. Write [0, 0, 0] "
                    f"to keep the mood and leave the colour alone")
            self.tone_bias = tuple(float(v) for v in self.tone_bias)
```

- [ ] **Step 5: Wire serialization**

In `from_dict`, add to the `cls(...)` call:

```python
            notes=opt("notes", ""), tone_bias=d.get("tone_bias"))
```

(Note: `d.get`, NOT `opt` — `None` is a meaningful value here, not "absent,
use the default", and they happen to coincide only because the default IS
`None`. Using `opt` would read as "null → default" and mislead the next
reader.)

In `to_dict`, add:

```python
                "notes": self.notes,
                "tone_bias": None if self.tone_bias is None else list(self.tone_bias)}
```

- [ ] **Step 6: Run the whole spec suite**

```bash
.venv/bin/python -m pytest tests/lib/test_spec.py -v
```

Expected: PASS, all of them.

- [ ] **Step 7: Check nothing else broke on Spec's shape**

```bash
.venv/bin/python -m pytest tests/ -k "spec or brief" -q
```

Expected: PASS. `reel_brief` writes `SPEC.json` through `to_dict`, so a
golden comparison there would surface here.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/spec.py tests/lib/test_spec.py
git commit -F - <<'EOF'
feat: Spec.tone_bias — the authored displacement that outranks the preset

R1.1's half of the mood contract: today the only way to stop a mood word
ordering a colour grade is to withhold --spec from match_grade, which the
driver needs for nothing else. The field makes the choice sayable.

None and (0,0,0) deliberately differ. None means "not authored, take the
preset's taste"; (0,0,0) means "this mood, leave my colour alone". A zero
default would make the second inexpressible, which is the shape `look`
already got right.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 2: `match_grade` resolves authored-over-preset and names the source

**Files:**
- Modify: `scripts/match_grade.py:26-70` (`conduct`), `:73-100` (`_report_md`), `:118-140` (`write_match`)
- Test: `tests/lib/test_match_grade.py`

**Interfaces:**
- Consumes: `Spec.tone_bias` (Task 1).
- Produces:
  - `match_grade._resolve_bias(spec: Spec | None, preset: MoodPreset | None) -> tuple[tuple[float, float, float], str]`
    — `(bias, source)`. `source` is `"SPEC.tone_bias"`, `"the <name> preset"`,
    or `""` when the bias is zero because nothing asked for one.
  - `conduct(geo, edl, *, eps=..., force=False, bias=(0.0, 0.0, 0.0))` —
    `preset=` is REPLACED by `bias=`; `conduct` no longer knows what a preset is.
  - `_report_md(sources, target, decisions, eps, *, bias=(0.0,0.0,0.0), bias_source="", k=1.0)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_match_grade.py`:

```python
from scripts.lib import moodpreset
from scripts.lib.spec import Spec

_SPEC = dict(canvas=(9, 16), length_s=30.0, mood="nostalgic warm", hook="open")


def test_resolve_bias_prefers_the_authored_triple_over_the_preset():
    spec = Spec(**{**_SPEC, "tone_bias": (1, 2, 3)})
    preset = moodpreset.resolve("nostalgic warm")
    assert preset.tone_bias != (1.0, 2.0, 3.0)          # the preset really differs
    assert match_grade._resolve_bias(spec, preset) == ((1.0, 2.0, 3.0), "SPEC.tone_bias")


def test_resolve_bias_honours_an_authored_zero_against_a_biased_preset():
    # The whole point of None-vs-zero: this mood, leave my colour alone.
    spec = Spec(**{**_SPEC, "tone_bias": (0, 0, 0)})
    preset = moodpreset.resolve("nostalgic warm")
    assert preset.tone_bias != (0.0, 0.0, 0.0)
    assert match_grade._resolve_bias(spec, preset) == ((0.0, 0.0, 0.0), "SPEC.tone_bias")


def test_resolve_bias_falls_back_to_the_preset_when_unauthored():
    spec = Spec(**_SPEC)                                 # tone_bias is None
    preset = moodpreset.resolve("nostalgic warm")
    assert match_grade._resolve_bias(spec, preset) == (preset.tone_bias,
                                                       f"the {preset.name} preset")


def test_resolve_bias_imposes_nothing_for_the_balanced_fallback():
    preset = moodpreset.resolve("no mood word matches this at all")
    assert preset.name == "balanced"
    assert match_grade._resolve_bias(None, preset) == ((0.0, 0.0, 0.0), "")


def test_resolve_bias_is_zero_with_no_spec_and_no_preset():
    assert match_grade._resolve_bias(None, None) == ((0.0, 0.0, 0.0), "")


def test_report_names_the_authored_source():
    md = match_grade._report_md([], (10.0, 100.0, 200.0), [], 4.0,
                                bias=(1.0, 2.0, 3.0), bias_source="SPEC.tone_bias")
    assert "SPEC.tone_bias" in md


def test_report_says_nothing_about_mood_when_no_bias_was_asked_for():
    md = match_grade._report_md([], (10.0, 100.0, 200.0), [], 4.0,
                                bias=(0.0, 0.0, 0.0), bias_source="")
    assert "displaced" not in md
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_match_grade.py -k "resolve_bias or report_names or report_says" -v
```

Expected: FAIL — `module 'scripts.match_grade' has no attribute '_resolve_bias'`.

- [ ] **Step 3: Add `_resolve_bias`**

In `scripts/match_grade.py`, above `conduct`:

```python
def _resolve_bias(spec: Spec | None,
                  preset: moodpreset.MoodPreset | None) -> tuple[tuple[float, float, float], str]:
    """The tone displacement and WHERE it came from (design 2026-09-03 §2).

    An authored `Spec.tone_bias` outranks the preset's taste, and an authored
    (0, 0, 0) is a real answer — "this mood, but leave my colour alone" — not the
    absence of one, which is why the field's default is None rather than a zero
    triple. `balanced` is tested by NAME, exactly as write_edit_plan tests it for
    `look` and for the same reason: it is resolve()'s "nothing matched", and an
    unmatched brief must not have a taste imposed on it.

    The source string is what MATCH.md prints. Until this slice the report showed
    the displacement without ever saying where it came from, which is the
    "silently" half of the retro's R1.1.
    """
    if spec is not None and spec.tone_bias is not None:
        return spec.tone_bias, "SPEC.tone_bias"
    if preset is not None and preset.name != "balanced":
        return preset.tone_bias, f"the {preset.name} preset"
    return (0.0, 0.0, 0.0), ""
```

Add `from scripts.lib.spec import Spec` to the imports if it is not already
there (it is — `write_match` already calls `Spec.from_json`).

- [ ] **Step 4: Swap `conduct`'s parameter**

Replace `conduct`'s signature and its bias block:

```python
def conduct(geo: ReelGeometry, edl: EDL, *, eps: float = matchgrade.MATCH_EPS,
            force: bool = False, bias: tuple[float, float, float] = (0.0, 0.0, 0.0)
            ) -> tuple[EDL, matchgrade.Profile, list[matchgrade.ToneDecision], float]:
```

and, where the old `bias = preset.tone_bias if ...` line stood:

```python
    # The displacement arrives already resolved (_resolve_bias): conduct does not know
    # what a preset is, so an authored bias and a preset's taste reach the target the
    # same way and there is one place that decides between them.
    target, scale = matchgrade.biased_target(target, bias)
```

Update `conduct`'s docstring paragraph that mentions the mood so it says the
bias is supplied, not derived.

- [ ] **Step 5: Swap `_report_md`'s parameter**

Replace its signature and the mood block:

```python
def _report_md(sources: list[str], target: matchgrade.Profile,
               decisions: list[matchgrade.ToneDecision], eps: float, *,
               bias: tuple[float, float, float] = (0.0, 0.0, 0.0),
               bias_source: str = "", k: float = 1.0) -> str:
```

```python
    if bias_source:
        head += f"\n\nTone displaced by {tuple(bias)} — from {bias_source}"
        if k < 1.0:
            head += f", scaled to {k:.0%} (the reel's own range left no room for the rest)"
        if matchgrade.bias_ineffective(bias, k):
            head += (f"\n\n> **mood-bias-ineffective** — what survived is under "
                     f"{matchgrade.MOOD_FLOOR:g} luma units, which is below this "
                     f"conductor's own delivery error, so the displacement will not be "
                     f"visible in the grade.")
```

Delete the `elif preset is not None:` arm that reported the balanced
fallback — `bias_source == ""` now covers it, and the arm's message named a
preset the function no longer receives.

- [ ] **Step 6: Wire `write_match`**

Replace the preset line and the `conduct`/`_report_md` calls:

```python
    spec_obj = Spec.from_json(spec) if spec else None
    preset = moodpreset.resolve(spec_obj.mood) if spec_obj is not None else None
    bias, bias_source = _resolve_bias(spec_obj, preset)
    out, target, decisions, k = conduct(geo, edl, eps=eps, force=force, bias=bias)
```

```python
    md_path.write_text(_report_md([e.source for e in edl.episodes], target, decisions, eps,
                                  bias=bias, bias_source=bias_source, k=k))
```

The returned dict gains the source beside the existing mood name:

```python
            "mood": preset.name if preset is not None else None,
            "bias_source": bias_source, "bias_scale": k,
```

- [ ] **Step 7: Run the tests**

```bash
.venv/bin/python -m pytest tests/lib/test_match_grade.py tests/lib/test_matchgrade.py -v
```

Expected: PASS. Any test that called `conduct(..., preset=...)` must be
updated to `conduct(..., bias=...)` — that is the intended blast radius of
the rename, and a test still passing `preset=` would be passing on a
parameter the function no longer honours.

- [ ] **Step 8: Commit**

```bash
git add scripts/match_grade.py tests/lib/test_match_grade.py
git commit -F - <<'EOF'
feat: an authored tone_bias outranks the preset, and MATCH.md says which won

conduct() stops knowing what a preset is: _resolve_bias decides between an
authored Spec.tone_bias and the preset's taste in one place, and hands
conduct a plain triple. The report gains the source string, closing the
"silently" half of R1.1 — until now MATCH.md printed the displacement
without ever saying where it came from.

The balanced arm of _report_md is deleted rather than ported: an empty
bias_source covers it, and the arm named a preset the function no longer
receives.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 3: `Footage.band` — what was actually carved

**Files:**
- Modify: `scripts/lib/footage.py:245-285` (`Footage` dataclass, `from_dict`, `to_dict`)
- Test: `tests/lib/test_footage.py`

**Interfaces:**
- Produces: `Footage.band: tuple | None` — the `(win_min, win_max)` the scan
  carved with, `None` on an artifact written before this slice. Tasks 4 and 6
  read it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_footage.py`:

```python
def test_footage_band_defaults_to_none_for_a_legacy_artifact():
    # A FOOTAGE.json written before 2026-09-03 carries no band. None is "unknown",
    # and edit_plan's reconciliation reports not-checked rather than passing green.
    assert footage.Footage.from_dict({"clips": []}).band is None


def test_footage_round_trips_its_band():
    f = footage.Footage(clips=[], band=(1.2, 4.0))
    assert footage.Footage.from_dict(f.to_dict()).band == (1.2, 4.0)


def test_footage_band_is_coerced_to_a_tuple_of_floats():
    assert footage.Footage(clips=[], band=[1, 4]).band == (1.0, 4.0)


def test_footage_rejects_a_one_element_band():
    with pytest.raises(ValueError, match="band"):
        footage.Footage(clips=[], band=(1.2,))


def test_footage_rejects_an_inverted_band():
    with pytest.raises(ValueError, match="band"):
        footage.Footage(clips=[], band=(4.0, 1.2))
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_footage.py -k band -v
```

Expected: FAIL — `Footage.__init__() got an unexpected keyword argument 'band'`.

- [ ] **Step 3: Add the field and its validation**

In `scripts/lib/footage.py`:

```python
class Footage:
    clips: list[FootageClip] = field(default_factory=list)
    band: tuple | None = None        # (win_min, win_max) this scan carved with

    def __post_init__(self) -> None:
        for k, c in enumerate(self.clips):
            if not isinstance(c, FootageClip):
                raise ValueError(f"Footage.clips[{k}] must be a FootageClip")
        if self.band is not None:
            if not (isinstance(self.band, (tuple, list)) and len(self.band) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                            for v in self.band)
                    and 0 < self.band[0] <= self.band[1]):
                raise ValueError(
                    f"Footage.band must be (win_min, win_max) seconds with "
                    f"0 < win_min <= win_max, or null on an artifact written before "
                    f"2026-09-03. Got {self.band!r} — re-run footage-intake to "
                    f"regenerate FOOTAGE.json")
            self.band = (float(self.band[0]), float(self.band[1]))
```

- [ ] **Step 4: Wire serialization**

```python
        return cls(clips=clips, band=d.get("band"))
```

```python
    def to_dict(self) -> dict:
        return {"clips": [c.to_dict() for c in self.clips],
                "band": None if self.band is None else list(self.band)}
```

- [ ] **Step 5: Run the footage suite**

```bash
.venv/bin/python -m pytest tests/lib/test_footage.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/footage.py tests/lib/test_footage.py
git commit -F - <<'EOF'
feat: Footage.band records the window band a scan carved with

Task 6's reconciliation needs to know what the footage can actually offer,
and until now the band was a module constant nobody downstream could read.
None is "unknown" — a legacy artifact — and reads as not-checked rather
than as a pass.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 4: the band becomes an intake parameter

**Files:**
- Modify: `scripts/lib/carve.py` (add `DEFAULT_BAND`)
- Modify: `scripts/intake.py:28` (constants), `:58-92` (`carve_windows`), `:385-410` (`_process_clip`), `:464-535` (`intake`), `:550-563` (CLI)
- Test: `tests/lib/test_intake.py`

**Interfaces:**
- Consumes: `Footage.band` (Task 3).
- Produces:
  - `carve.DEFAULT_BAND = (1.2, 4.0)` — the one definition.
  - `intake.carve_windows(scene_cuts, timeline, mags, fps, dur, band=carve.DEFAULT_BAND)`
  - `intake._process_clip(path, sample_fps=SAMPLE_FPS, embed_cast=True, band=carve.DEFAULT_BAND)`
  - `intake.intake(footage_root, out_dir, sample_fps=SAMPLE_FPS, *, jobs=..., fresh=False, band=carve.DEFAULT_BAND)`
  - The written `Footage` carries `band=band`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_intake.py`:

```python
from scripts.lib import carve


def test_default_band_has_exactly_one_definition():
    # intake must not re-declare the numbers: one constant, imported.
    assert carve.DEFAULT_BAND == (1.2, 4.0)
    assert not hasattr(intake, "WIN_MIN") and not hasattr(intake, "WIN_MAX")


def test_carve_windows_honours_a_wider_band():
    # A 6s span with no interior peak is one flat unit sized by win_max: at the
    # default band that is 4.0s, at a (1.2, 6.0) band it is the whole 6.0s.
    times = [i * 0.5 for i in range(13)]                   # 0.0 .. 6.0
    line = [(t, 0, None, [], {}) for t in times]
    mags = [1.0] * len(times)
    narrow = intake.carve_windows([], line, mags, 2.0, 6.0)
    wide = intake.carve_windows([], line, mags, 2.0, 6.0, band=(1.2, 6.0))
    assert max(d for _, d in narrow) <= 4.0
    assert max(d for _, d in wide) > 4.0


def test_intake_records_the_band_it_carved_with(sample_clip, tmp_path):
    out = tmp_path / "run"
    f = intake.intake(str(sample_clip.parent), str(out), band=(1.0, 3.0))
    assert f.band == (1.0, 3.0)
    assert json.loads((out / "FOOTAGE.json").read_text())["band"] == [1.0, 3.0]


def test_intake_records_the_default_band_when_none_is_given(sample_clip, tmp_path):
    f = intake.intake(str(sample_clip.parent), str(tmp_path / "run"))
    assert f.band == carve.DEFAULT_BAND
```

Add `import json` at the top of the test file if absent.

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_intake.py -k "band" -v
```

Expected: FAIL — `module 'scripts.lib.carve' has no attribute 'DEFAULT_BAND'`.

- [ ] **Step 3: Add the one definition**

In `scripts/lib/carve.py`, near the top with the other module constants:

```python
DEFAULT_BAND = (1.2, 4.0)   # (win_min, win_max) seconds — units_for_span's band when a
                            # caller states none. Lives here, not in intake, because
                            # intake_cache must key on it too and a lib cannot import a
                            # driver (design 2026-09-03 §3).
```

- [ ] **Step 4: Delete `intake`'s constants and thread the parameter**

In `scripts/intake.py`, DELETE line 28 (`WIN_MIN, WIN_MAX = 1.2, 4.0`) and
add `carve` to the imports if it is not already imported (it is —
`carve.units_for_span` is called).

`carve_windows`:

```python
def carve_windows(scene_cuts: list[float],
                  timeline: list[tuple[float, int, tuple[float, float, float, float] | None, list[int],
                                       dict[int, tuple[float, float, float, float]]]],
                  mags: list[float], fps: float, dur: float,
                  band: tuple[float, float] = carve.DEFAULT_BAND) -> list[tuple[float, float]]:
```

and its one call site inside the function:

```python
        spans.extend(carve.units_for_span(a, b, times, curve, band[0], band[1]))
```

Fix the two docstring references that name the constants — `A single
sub-WIN_MIN shot` becomes `A single shot shorter than the band's floor`, and
line 92's comment likewise. Line 131's `stability` docstring mentions
`WIN_MIN` as prose about the measurement; reword it to "the band's floor"
rather than deleting the sentence.

`_process_clip`:

```python
def _process_clip(path: str, sample_fps: float = SAMPLE_FPS, embed_cast: bool = True,
                  band: tuple[float, float] = carve.DEFAULT_BAND) -> ClipResult:
```

with its `carve_windows` call becoming:

```python
        spans = carve_windows(cuts, timeline, mags, info.fps, dur, band=band)
```

`intake`:

```python
def intake(footage_root: str, out_dir: str, sample_fps: float = SAMPLE_FPS, *,
           jobs: int = DEFAULT_JOBS, fresh: bool = False,
           band: tuple[float, float] = carve.DEFAULT_BAND) -> footage.Footage:
```

Validate it beside the `jobs` check, so a bad band costs no scan:

```python
    if not (isinstance(band, (tuple, list)) and len(band) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in band)
            and 0 < band[0] <= band[1]):
        raise ValueError(f"intake: band must be (win_min, win_max) seconds with "
                         f"0 < win_min <= win_max, got {band!r}")
    band = (float(band[0]), float(band[1]))
```

Pass it to the worker:

```python
        futs = {ex.submit(_process_clip, str(p), sample_fps, reid_ok, band): p for p in misses}
```

(`_process_clip`'s third positional is `embed_cast`; the existing call uses
the keyword `embed_cast=reid_ok`. Keep the keyword form and add
`band=band` — do NOT switch to positionals.)

And record it on the artifact:

```python
    result = footage.Footage(clips=[r.clip for r in ok], band=band)
```

- [ ] **Step 5: Add the CLI flags**

```python
    ap.add_argument("--win-min", type=float, default=carve.DEFAULT_BAND[0],
                    help="shortest carved window, seconds (default %(default)s). "
                         "Changing either bound is a full cache MISS: window "
                         "boundaries were carved under the old band")
    ap.add_argument("--win-max", type=float, default=carve.DEFAULT_BAND[1],
                    help="longest carved window, seconds (default %(default)s). "
                         "edit_plan can JOIN adjacent windows, so this is not a "
                         "ceiling on episode length")
```

```python
    f = intake(a.footage_root, a.out_dir, a.sample_fps, jobs=a.jobs, fresh=a.fresh,
               band=(a.win_min, a.win_max))
```

- [ ] **Step 6: Run the intake suite**

```bash
.venv/bin/python -m pytest tests/lib/test_intake.py tests/lib/test_carve.py -v
```

Expected: PASS. Tests referring to `intake.WIN_MIN`/`WIN_MAX` must be
re-pointed at `carve.DEFAULT_BAND` — `tests/lib/test_intake.py:53` and the
comments in `tests/conftest.py:37-41` and `tests/lib/test_carve.py`.

- [ ] **Step 7: Prove the default run did not move**

```bash
.venv/bin/python -m pytest tests/ -k "intake or footage or carve" -q
```

Expected: PASS with no golden re-pin. If a golden moved, the parameter
changed default behaviour and that is a bug in this task, not a golden to
update.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/carve.py scripts/intake.py tests/lib/test_intake.py tests/lib/test_carve.py tests/conftest.py
git commit -F - <<'EOF'
feat: the window band becomes an intake parameter, defined once in carve

WIN_MIN/WIN_MAX stop being module constants read at the carve call and
become a band threaded intake() -> _process_clip() -> carve_windows() ->
carve.units_for_span(), which already took the band as arguments because a
lib must not depend on a driver.

The default lives in carve, not intake: Task 5 needs intake_cache to key on
it, and a lib cannot import a driver. Footage records what was carved so
edit_plan can reconcile against it instead of assuming the constant.

Measured, so the scope is honest: the ceiling binds three windows in 1508
on the reference pool and the shipped reel already exceeds it in five of
eight episodes via span merge. This does not make shots longer. It makes
the band changeable at all.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 5: the band joins the cache key

**Files:**
- Modify: `scripts/lib/intake_cache.py:39-43` (`CACHE_VERSION`), `:67-80` (`clip_key`), `:88-115` (`store`), `:117-135` (`load`)
- Modify: `scripts/intake.py:499-524` (the two cache call sites)
- Test: `tests/lib/test_intake_cache.py`

**Interfaces:**
- Consumes: `carve.DEFAULT_BAND` (Task 4).
- Produces: `clip_key(path, sample_fps, model, proxy_long_side, reid_model="", *, band)`,
  `store(out_dir, path, sample_fps, result, model, proxy_long_side, reid_model="", *, band)`,
  `load(out_dir, path, sample_fps, model, proxy_long_side, reid_model="", *, band)`.
  `band` is a REQUIRED keyword in all three — like `proxy_long_side`, and for
  the same reason.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_intake_cache.py`:

```python
def test_clip_key_carries_the_band(tmp_path):
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    k = intake_cache.clip_key(str(p), 2.0, "m.pt", 960, band=(1.2, 4.0))
    assert k["band"] == [1.2, 4.0]


def test_a_different_band_is_a_different_key(tmp_path):
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    a = intake_cache.clip_key(str(p), 2.0, "m.pt", 960, band=(1.2, 4.0))
    b = intake_cache.clip_key(str(p), 2.0, "m.pt", 960, band=(1.2, 6.0))
    assert a != b


def test_band_is_a_required_keyword(tmp_path):
    # A silent default here would serve boundaries carved under another band —
    # the same failure proxy_long_side is a required argument to prevent.
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    with pytest.raises(TypeError):
        intake_cache.clip_key(str(p), 2.0, "m.pt", 960)


def test_cache_version_is_nine():
    assert intake_cache.CACHE_VERSION == 9
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_intake_cache.py -k "band or version_is_nine" -v
```

Expected: FAIL — `clip_key() got an unexpected keyword argument 'band'`.

- [ ] **Step 3: Bump the version with its reason**

```python
CACHE_VERSION = 9   # 8→9 (2026-09-03): the carve band joins the key. carve_windows runs
                    # inside the cached Phase 1, so before this a changed WIN_MIN/WIN_MAX
                    # returned boundaries carved under the OLD band, silently — the band
                    # was the only carve input absent from the key (design
                    # 2026-09-03 §0.5). The bump exists so the reason is recorded rather
                    # than inferred from a key that merely happens to differ.
```

- [ ] **Step 4: Add the key term**

```python
def clip_key(path: str, sample_fps: float, model: str, proxy_long_side: int,
             reid_model: str = "", *, band: tuple[float, float]) -> dict:
```

with, in the returned dict:

```python
            "reid_model": str(reid_model), "band": [float(band[0]), float(band[1])],
            "version": CACHE_VERSION}
```

and one docstring sentence:

```
    `band` is the carve band (win_min, win_max): window BOUNDARIES are decided
    inside the cached phase, so a changed band must miss (design 2026-09-03 §3).
```

A list, not a tuple, because the key is compared against a value round-tripped
through JSON — where a tuple comes back as a list and would never match.

- [ ] **Step 5: Thread it through `store` and `load`**

Add `*, band: tuple[float, float]` to both signatures and pass it into their
`clip_key(...)` calls.

- [ ] **Step 6: Update the two production call sites**

In `scripts/intake.py`:

```python
        hit = None if fresh else intake_cache.load(str(out), str(p), sample_fps, MODEL,
                                                   PROXY_LONG_SIDE, reid_model=reid_model,
                                                   band=band)
```

```python
                results[p] = intake_cache.store(str(out), str(p), sample_fps,
                                                fut.result(), MODEL, PROXY_LONG_SIDE,
                                                reid_model=reid_model, band=band)
```

- [ ] **Step 7: Update the test call sites**

The 26 `clip_key`/`store`/`load` calls in `tests/` each need `band=`. Most
take the default:

```bash
grep -rn 'clip_key(\|cache.store(\|cache.load(' tests/ | wc -l
```

Add `band=carve.DEFAULT_BAND` (importing `carve`) to each, EXCEPT the two
new tests above that pass a band deliberately. Then confirm none was missed:

```bash
.venv/bin/python -m pytest tests/lib/test_intake_cache.py -v
```

Expected: PASS. A `TypeError: missing a required keyword-only argument`
names any call site still unfixed.

- [ ] **Step 8: Prove the round trip**

```bash
.venv/bin/python -m pytest tests/ -k "intake" -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add scripts/lib/intake_cache.py scripts/intake.py tests/lib/test_intake_cache.py
git commit -F - <<'EOF'
fix: the carve band joins the cache key, so a changed band cannot go unnoticed

carve_windows runs inside _process_clip — cached Phase 1 — and the band was
the only carve input absent from clip_key. Change WIN_MAX today and every
cached clip still answers with boundaries carved under the old band, with
nothing said. That is the live defect behind this slice's part B; the rest
of it is plumbing.

band is a required keyword in clip_key/store/load, exactly like
proxy_long_side and for exactly its reason: a silent default serves stale
boundaries. CACHE_VERSION 8->9 records why, rather than leaving it to be
inferred from a key that merely happens to differ. The first scan after
this re-scans the pool once.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 6: the two bands are reconciled before the cut

**Files:**
- Modify: `scripts/lib/moodpreset.py` (add `reconcile_band`)
- Modify: `scripts/edit_plan.py:713-730` (the gate region)
- Test: `tests/lib/test_moodpreset.py`, `tests/lib/test_edit_plan.py`

**Interfaces:**
- Consumes: `Footage.band` (Task 3).
- Produces: `moodpreset.reconcile_band(preset: MoodPreset, carved: tuple | None) -> str | None`
  — `None` when compatible or uncheckable; the refusal's problem text otherwise.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_moodpreset.py`:

```python
_FLOOR_PRESET = moodpreset.MoodPreset(
    "deep", None, {"close": 0.3, "medium": 0.4, "wide": 0.3}, (2.5, 5.0))


def test_reconcile_refuses_a_preset_floor_below_the_carved_floor():
    # The preset wants shots down to 2.5s; nothing in FOOTAGE.json is shorter
    # than 3.0s, and no stage splits a window.
    msg = moodpreset.reconcile_band(_FLOOR_PRESET, (3.0, 4.0))
    assert msg is not None
    assert "2.5" in msg and "3.0" in msg and "--win-min" in msg


def test_reconcile_allows_a_preset_ceiling_above_the_carved_ceiling():
    # edit_plan JOINS adjacent windows (span merge), so a taller ceiling is
    # always reachable — the run's own 5.80s episode against a 4.0s carve
    # proves it (design 2026-09-03 §0.3). Refusing here would be wrong.
    assert moodpreset.reconcile_band(_FLOOR_PRESET, (1.2, 4.0)) is None


def test_reconcile_allows_an_exactly_equal_floor():
    assert moodpreset.reconcile_band(_FLOOR_PRESET, (2.5, 4.0)) is None


def test_reconcile_is_silent_without_a_carved_band():
    # A legacy FOOTAGE.json: uncheckable, and the caller says so out loud.
    assert moodpreset.reconcile_band(_FLOOR_PRESET, None) is None


def test_reconcile_never_fires_at_the_shipped_defaults():
    # Honest scope (design §4): at carve.DEFAULT_BAND every shipped preset passes,
    # so this check goes live only when an operator raises --win-min.
    for p in moodpreset.PRESETS + (moodpreset.BALANCED,):
        assert moodpreset.reconcile_band(p, carve.DEFAULT_BAND) is None
```

Import `carve` at the top of the test file.

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/lib/test_moodpreset.py -k reconcile -v
```

Expected: FAIL — `module 'scripts.lib.moodpreset' has no attribute 'reconcile_band'`.

- [ ] **Step 3: Implement the check**

In `scripts/lib/moodpreset.py`, after `evaluate`:

```python
def reconcile_band(preset: MoodPreset, carved: tuple | None) -> str | None:
    """The preset's asl band against the band the footage was CARVED with.
    None = compatible, or uncheckable; a string = the refusal's problem text.

    Only the LOWER bound is checkable, and that asymmetry is the whole check
    (design 2026-09-03 §4). edit_plan joins adjacent windows through its span
    merge, so a preset ceiling above the carved ceiling is always reachable —
    the reference run shipped a 5.80s episode against a 4.0s carve ceiling, and
    refusing that would be refusing a cut that works. Nothing splits a window,
    so a preset FLOOR below the carved floor asks for a shot length that exists
    nowhere in FOOTAGE.json, and no selection can supply it.

    `carved` is None on a FOOTAGE.json written before 2026-09-03. The check
    cannot run; the caller reports not-checked rather than a pass.
    """
    if carved is None:
        return None
    if preset.asl[0] >= carved[0]:
        return None
    return (f"preset {preset.name!r} wants shots from {preset.asl[0]:.1f}s, but the "
            f"footage was carved with a {carved[0]:.1f}s floor, so no window in "
            f"FOOTAGE.json is shorter than {carved[0]:.1f}s and nothing splits one. "
            f"Re-scan with `--win-min {preset.asl[0]:g}`, choose a mood whose band "
            f"starts at or above {carved[0]:.1f}s, or drop --spec to run without a "
            f"preset. (The preset's CEILING is not checked: span merge joins adjacent "
            f"windows, so a longer shot is always reachable.)")
```

- [ ] **Step 4: Wire the gate**

In `scripts/edit_plan.py`, insert immediately BEFORE the `v = edl.variety`
line (so a length contradiction is reported before a shot-mix one — the
footage cannot supply the length at all, while a variety gap is a choice):

```python
    band_problem = moodpreset.reconcile_band(preset, footage.band)
    if footage.band is None:
        _log("length band: not checked — this FOOTAGE.json predates the recorded carve "
             "band (2026-09-03). Re-run footage-intake to record it")
    else:
        _log(f"length band: preset {preset.name} wants "
             f"{preset.asl[0]:.1f}–{preset.asl[1]:.1f}s, footage carved "
             f"{footage.band[0]:.1f}–{footage.band[1]:.1f}s")
    if band_problem is not None:
        return {"status": "stop_and_report",
                "finding": {"reason": "length-band", "episode_idx": None,
                            "problems": [band_problem]}}
```

- [ ] **Step 5: Write the driver test**

Append to `tests/lib/test_edit_plan.py`:

The file already has every helper this needs: `_write_inputs(tmp_path, sel,
footage=None)` takes a ready-made `Footage`, `_write_spec(tmp_path, **kw)`
writes a `SPEC.json`, `_plain_selection()` supplies a two-episode selection,
and `_footage()` builds the plain fixture. Use them — do not grow a second
"write the three inputs" helper beside `_write_inputs`, whose own comment
asks for exactly that.

```python
def test_write_edit_plan_refuses_a_preset_floor_under_the_carved_floor(monkeypatch, tmp_path):
    # A carved floor above the preset's floor, so the gate is reachable at all:
    # at carve.DEFAULT_BAND every shipped preset passes (design §4).
    deep = moodpreset.MoodPreset("deep", mood.MoodVector(0.5, 0.5, 0.5),
                                 {"close": 0.3, "medium": 0.4, "wide": 0.3}, (2.5, 5.0))
    monkeypatch.setattr(moodpreset, "PRESETS", (deep,))
    footage = replace(_footage(), band=(3.0, 4.0))
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection(), footage=footage)
    spec_path = _write_spec(tmp_path, mood="deep")
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path), spec=spec_path)
    assert result["status"] == "stop_and_report"
    assert result["finding"]["reason"] == "length-band"
    assert "--win-min" in result["finding"]["problems"][0]


def test_write_edit_plan_passes_a_carved_band_the_preset_fits_inside(tmp_path):
    # The control: same inputs, a floor the preset clears, and the run proceeds
    # past this gate. Without it the test above passes for a gate that always fires.
    footage = replace(_footage(), band=(1.2, 4.0))
    fp, sp, pp = _write_inputs(tmp_path, _plain_selection(), footage=footage)
    result = edit_plan.write_edit_plan(fp, sp, pp, str(tmp_path),
                                       spec=_write_spec(tmp_path))
    assert result["status"] == "written"
```

`replace` is `dataclasses.replace` — import it if the file does not already.
`moodpreset.resolve` matches on the mood TEXT, so `_write_spec(mood="deep")`
is what routes to the patched preset; a mood string matching nothing would
resolve to `BALANCED`, whose floor is 1.5 and would not fire the gate.

Do NOT move either test onto the `fake_render` fixture: like the file's three
other pure-gate tests, they render no frame and need a declared geometry that
deliberately does not match the source (fake-render-fixture design §3).

- [ ] **Step 6: Run both suites**

```bash
.venv/bin/python -m pytest tests/lib/test_moodpreset.py tests/lib/test_edit_plan.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/moodpreset.py scripts/edit_plan.py tests/lib/test_moodpreset.py tests/lib/test_edit_plan.py
git commit -F - <<'EOF'
feat: reconcile the preset's length band against the carved one, floor only

R1.3 asked for "either it gates or it stops declaring a band". It now
declares something that is checked, at the one edge where checking is sound.

Windows can be joined but never split. edit_plan's span merge reaches any
ceiling — the reference run shipped a 5.80s episode against a 4.0s carve
ceiling — so refusing a tall preset ceiling would refuse a cut that works.
A preset FLOOR below the carved floor asks for a length no window carries
and no selection can supply, so that is the refusal.

At shipped defaults the check fires on nothing (every preset floor is at or
above 1.2s); it goes live when an operator raises --win-min, which is the
knob the previous task introduced. A legacy FOOTAGE.json with no recorded
band reports not-checked, never a pass.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 7: end-to-end proofs

**Files:**
- Test: `tests/integration/test_mood_contract.py` (create)

**Interfaces:**
- Consumes: everything above.

These are design §6's proofs 2, 3 and 4 — the ones that need a real driver
rather than a unit. Each carries a control that must NOT move, because a
proof whose control also changes proves nothing about the change.

- [ ] **Step 1: Write proof 3 — a changed band misses the cache**

```python
def test_a_changed_band_misses_the_cache_and_recarves(multi_window_clip, tmp_path):
    root, out = multi_window_clip.parent, tmp_path / "run"
    a = intake.intake(str(root), str(out), band=(1.2, 4.0))
    b = intake.intake(str(root), str(out), band=(1.2, 6.0))
    wins_a = [(w.start, w.dur) for c in a.clips for w in c.windows]
    wins_b = [(w.start, w.dur) for c in b.clips for w in c.windows]
    assert wins_a != wins_b, "a changed band must re-carve, not serve cached boundaries"


def test_the_same_band_twice_hits_the_cache_and_is_identical(multi_window_clip, tmp_path):
    # The control: without this, the test above passes for a cache that never hits.
    root, out = multi_window_clip.parent, tmp_path / "run"
    a = intake.intake(str(root), str(out), band=(1.2, 4.0))
    b = intake.intake(str(root), str(out), band=(1.2, 4.0))
    assert a.to_dict() == b.to_dict()
```

- [ ] **Step 2: Write proof 4 — the default run is unchanged**

```python
def test_a_default_run_carves_what_the_explicit_default_carves(multi_window_clip, tmp_path):
    root = multi_window_clip.parent
    implicit = intake.intake(str(root), str(tmp_path / "a"))
    explicit = intake.intake(str(root), str(tmp_path / "b"), band=carve.DEFAULT_BAND)
    assert implicit.to_dict() == explicit.to_dict()
```

- [ ] **Step 3: Write proof 2 — an explicit zero bias equals no bias at all**

```python
def test_an_authored_zero_bias_conducts_like_no_spec_at_all():
    preset = moodpreset.resolve("nostalgic warm")
    assert preset.tone_bias != (0.0, 0.0, 0.0)           # the preset really would bias
    spec_zero = Spec(canvas=(9, 16), length_s=30.0, mood="nostalgic warm",
                     hook="open", tone_bias=(0, 0, 0))
    assert match_grade._resolve_bias(spec_zero, preset)[0] == (0.0, 0.0, 0.0)
    assert match_grade._resolve_bias(None, None)[0] == (0.0, 0.0, 0.0)
    # the control that must NOT move: unauthored still takes the preset's taste
    spec_none = Spec(canvas=(9, 16), length_s=30.0, mood="nostalgic warm", hook="open")
    assert match_grade._resolve_bias(spec_none, preset)[0] == preset.tone_bias
```

- [ ] **Step 4: Run the integration file**

```bash
.venv/bin/python -m pytest tests/integration/test_mood_contract.py -v
```

Expected: PASS. If `test_a_changed_band_misses_the_cache_and_recarves` does
not discriminate, the fixture's clip carves identically under both bands —
use a longer band spread rather than weakening the assertion.

- [ ] **Step 5: Run the whole suite**

```bash
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all pass. Record the count in the commit body.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_mood_contract.py
git commit -F - <<'EOF'
test: end-to-end proofs for the mood contract, each with a control

Three claims that only a driver can settle: a changed band re-carves rather
than serving cached boundaries, a default run is byte-identical to the
explicit default, and an authored zero bias conducts exactly like no spec.

Each carries a control that must not move — without the same-band-twice
test the cache-miss proof would pass for a cache that never hits, and
without the unauthored arm the zero-bias proof would pass for a resolver
that always returns zero.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 8: mutation battery, docs, version

**Files:**
- Modify: `docs/backlog.md`, `docs/build-status.md`, `CLAUDE.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json`
- Modify: `skills/footage-intake/SKILL.md`, `skills/match-grade/SKILL.md`, `skills/reel-brief/SKILL.md`

- [ ] **Step 1: Run the mutation battery**

Ten rows. For each: apply the mutation, run the named test, confirm it goes
RED, then restore with `git show HEAD:<path> > <path>`. Run every row under
`PYTHONDONTWRITEBYTECODE=1`.

| # | File | Mutation | Must go RED |
|---|---|---|---|
| 1 | `spec.py` | `tone_bias: tuple \| None = (0.0, 0.0, 0.0)` | `test_spec_tone_bias_defaults_to_none_not_zero` |
| 2 | `spec.py` | drop the bool check from the `tone_bias` validation | `test_spec_rejects_a_bool_in_tone_bias` |
| 3 | `match_grade.py` | `_resolve_bias` checks the preset before the spec | `test_resolve_bias_prefers_the_authored_triple_over_the_preset` |
| 4 | `match_grade.py` | `_resolve_bias` treats `(0,0,0)` as unauthored (`if spec.tone_bias:`) | `test_resolve_bias_honours_an_authored_zero_against_a_biased_preset` |
| 5 | `match_grade.py` | drop the `preset.name != "balanced"` test | `test_resolve_bias_imposes_nothing_for_the_balanced_fallback` |
| 6 | `footage.py` | `band` survives `to_dict` but `from_dict` ignores it | `test_footage_round_trips_its_band` |
| 7 | `intake.py` | `carve_windows` ignores `band` and uses `carve.DEFAULT_BAND` | `test_carve_windows_honours_a_wider_band` |
| 8 | `intake_cache.py` | drop `"band"` from `clip_key`'s dict | `test_a_different_band_is_a_different_key` |
| 9 | `intake_cache.py` | `band` gets a default `= carve.DEFAULT_BAND` | `test_band_is_a_required_keyword` |
| 10 | `moodpreset.py` | `reconcile_band` also refuses on the ceiling | `test_reconcile_allows_a_preset_ceiling_above_the_carved_ceiling` |

Row 10 is the one that matters most: it is the design's central asymmetry,
and a reviewer who did not read §0.3 would call the ceiling check an
improvement.

Any row that does NOT go red is a coverage hole — write the test that closes
it before moving on, and say in the report which row found it.

- [ ] **Step 2: Restore and confirm the tree is clean**

```bash
git status --short && git diff --stat
```

Expected: empty. A battery that leaves a mutation behind ships it.

- [ ] **Step 3: Update the backlog**

Mark R1.1, R1.2 and R1.3 `✅` with the date and what actually happened —
including that R1.2's premise was overturned, since a future reader will
otherwise re-derive the ceiling theory. Add the design's four §8 deferrals as
new rows:

1. Measure the band against real footage and genre (P2, S) — R1.2's second half.
2. Explain the "pull toward two seconds" against the run's drafts (P2, S) —
   §0.4 rules out both mechanisms the retro named.
3. `_tight_unit` emits exactly `win_min` per peak, so 72.9% of the pool is
   one length (P3, M) — a carve-sensor question.
4. Gate the realized `asl` if a run shows the reported overshoot mattering (P3, S).

Also correct the four stale rows this session's audit found, since they are
in the same file and a reader hitting them will not trust the rest:
R2.7 (`colour_cast` deleted 2026-08-28 — close it), R10.4 (`episode_qc` now
names the episode — close it), R11.2 (project memory is populated — close
it), R2.4 (its `grade_delta_max` example was renamed to `entropy_floor` in
0.7.0 — fix the example, the mechanism is still live).

- [ ] **Step 4: Update build-status, the registry and the skills**

Add a `## Done` entry to `docs/build-status.md` in the established shape:
design link, plan link, task range, commits, what was measured, honest
limits carried forward.

Add two rows to `CLAUDE.md`'s Quick Reference — the design and the plan —
following the existing row style.

Three skills reference the changed surfaces:
- `skills/footage-intake/SKILL.md` — the `--win-min`/`--win-max` flags and
  the one-time re-scan.
- `skills/match-grade/SKILL.md` — `--spec` now carries an authorable
  `tone_bias`, and the report names the source.
- `skills/reel-brief/SKILL.md` — `tone_bias` is a brief-level field, with
  the `None`-vs-zero distinction stated.

- [ ] **Step 5: Bump the version**

`.claude-plugin/plugin.json` → `0.8.0`, and a matching top entry in
`CHANGELOG.md`. The install path is version-keyed, so an unbumped version
lets a reinstall keep serving the old snapshot —
`tests/test_plugin_manifests.py` enforces the match.

- [ ] **Step 6: Full suite**

```bash
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -F - <<'EOF'
docs: 0.8.0 — the mood contract, and four stale backlog rows closed

The slice's own record: R1.1/R1.2/R1.3 closed, with R1.2 marked as
overturned rather than delivered — the ceiling binds three windows in 1508
and the shipped reel already exceeds it, so what landed is a band that
cannot change silently, not a longer shot. Four §8 deferrals get rows.

Four unrelated rows are corrected in the same pass because a reader who
hits a stale one stops trusting the file: R2.7's colour_cast was deleted
2026-08-28, R10.4's episode_qc now names the episode, R11.2's project
memory is populated, and R2.4's example named a field renamed in 0.7.0.

Battery: 10 mutations, all red.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Self-Review

**Spec coverage.** §2 (A) → Tasks 1, 2. §3 (B) → Tasks 3, 4, 5. §4 (C) →
Task 6. §5 contracts table → Tasks 1, 3, 4, 5. §6 proofs: proof 1 is Task
2's `test_resolve_bias_prefers_the_authored_triple_over_the_preset` plus
`test_report_names_the_authored_source`; proofs 2, 3, 4 are Task 7; proofs 5
and 6 are Task 6's `reconcile` tests. §7 honest limits and §8 deferrals →
Task 8, step 3. No gap.

**Placeholder scan.** Every code step carries real code. Task 6 step 5 names
an existing helper to build from rather than showing a fixture the file
already has; Task 8 step 1's table names the exact mutation and the exact
test for each row.

**Type consistency.** `carve.DEFAULT_BAND` is the single definition (Task 4)
and is what Tasks 5, 6 and 7 import. `band` is `tuple | None` on `Footage`
(nullable — legacy artifacts) and `tuple[float, float]` everywhere else
(never null in flight). `tone_bias` is `tuple | None` on `Spec` and a plain
3-tuple past `_resolve_bias`, which is the one place the `None` collapses.
`_resolve_bias` returns `(bias, source)` in that order in Task 2, Task 7 and
the battery.

**One risk worth naming for the implementer.** Task 5 step 7 rewrites 26
test call sites. That is mechanical, but a `sed` that also matches the two
tests which pass a band deliberately would silently un-test the very thing
Task 5 exists to prove. Read the two new tests' names before running any
bulk edit, and re-read the diff after.
