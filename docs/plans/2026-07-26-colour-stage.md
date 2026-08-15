# Colour-as-a-stage (slice F) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote colour from the single normalize-to-middle gain to a per-episode
actuator — the seven parked grade primitives + a `grade_chain` composer, an additive
identity-off auto white-balance, a tone measurer, a render-time banding guard, an
advisory subject-hue-drift check, and tv/pc colour-range correctness — all riding the
one existing reframe encode.

**Architecture:** `lib/color.py` becomes the single colour authority (pure fragment
builders + the fixed-order `grade_chain` + `white_balance_*` + `percentiles`). `reframe`
builds the `wb`/`tone` fragments, runs `verify_tone`, and splices the finished `grade`
string into its one `-vf` tail. The nine colour fields ride `EDLEpisode → Manifest →
ReframeSpec` (the editorial passthrough is already generic). A new pure
`lib/color_fidelity.py` + `check_episode` wiring add an advisory hue-drift check.
`assembly`/`ExportProfile` carry the range tag.

**Tech Stack:** Python 3.13, ffmpeg via `scripts/lib/ffbin` + `scripts/lib/proc`, PIL
(already a dep) for still sampling, `colorsys` (stdlib) for hue, pytest.

**Source material:** the parked branch `wip/montage-run-hardening`, commit `4841dd3`,
holds the grade primitives, the `ReframeSpec` colour fields, `verify_tone`, and the
range correctness — unit-green but never TDD-reviewed. **Port those pieces verbatim**
via `git show 4841dd3:<path>` (do not retype the long docstrings — copy them). The
white-balance, `grade_chain`, `percentiles`, the tone measurer, and the fidelity check
are **new** (full code below). Design: `docs/specs/2026-07-26-colour-stage-design.md`.

**Conventions (repo):** scripts run as modules (`pythonpath = .`); Python is
`.venv/bin/python`; ffmpeg only via `scripts/lib/ffbin` (never PATH); `lutrgb` is banned
(`colorchannelmixer`/`curves`/`eq`/`colorlevels`/`fade` only); every commit body ends
with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Run one test with
`.venv/bin/python -m pytest <path>::<name> -q`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `scripts/lib/color.py` | pure colour authority | +7 grade primitives + constants (port), `grade_chain`, `white_balance_gains`/`_arg`, `percentiles` |
| `scripts/lib/models.py` | typed specs | `ReframeSpec` +9 colour fields & validation; `ExportProfile.color_range`; `CheckSpec.hue_drift_max` |
| `scripts/reframe.py` | the one encode | `verify_tone`; `_filter_args(grade)`; build `wb`/`tone`/`grade` |
| `scripts/lib/color_fidelity.py` | **new** pure metric | `hue`, `hue_drift`, `evaluate` |
| `scripts/check_episode.py` | episode postcheck | `source=` param + advisory `color_fidelity` check |
| `scripts/color_measure.py` | **new** authoring aid | `measure_profile` + CLI |
| `scripts/lib/edl.py` | authoring carrier | `EDLEpisode` +9 fields, `to_dict`, `to_manifest_dict` |
| `scripts/lib/manifest.py` | manifest carrier | `Manifest` +9 fields, `OPTIONAL`, `from_dict` |
| `scripts/process_episode.py` | manifest→spec bridge | 9 colour fields into `ReframeSpec`; `source=src` into the check |
| `scripts/lib/assembly.py` | range-correct concat | `StreamInfo.color_range` + probe + `matches` + `_normalize` convert |
| `scripts/edl_to_reel.py` | SP1 driver | `--color-delta-max` override (NOT `platform` — that is a safe-zones follow-up) |
| `scripts/edit_plan.py` | authoring | `window_to_episode` docstring only (passthrough already generic) |
| `skills/edit-plan/SKILL.md` | authoring guidance | grade / white-balance / tone + `measure` |
| tests + docs | | unit + real-ffmpeg proofs; build-status, pipeline-map, CLAUDE, this plan |

**Excluded from every task (belongs to other slices):** `ReframeSpec.smooth_window_s`
and the `compute_path` lead-direction/`smooth_window` changes in the parked `reframe`
diff (pathsmooth/motion); `edl_to_reel`'s `platform` param (safe-zones); the match-grade
conductor and mood LUT.

---

## Task 0: `color.py` — the seven grade primitives (port)

**Files:**
- Modify: `scripts/lib/color.py`
- Test: `tests/lib/test_color.py`

Port **verbatim** from `git show 4841dd3:scripts/lib/color.py`: the module constants and
the functions `black_point_arg`, `highlight_arg`, `saturation_arg`, `shadow_red_arg`,
`tone_arg`, `_lerp`, `mid_blue_arg`, `dip_arg` (copy the docstrings — they carry the
measured rationale). Keep parked placement (`black_point`…`tone_arg`/`_lerp` between
`mixer_arg` and `corrected`; `mid_blue`/`dip` after `corrected`). Do **not** retype —
copy the bodies. Each returns `""` at its identity value and type-checks `bool` first.

Constants: `BLACK_POINT_MAX=0.35`, `HIGHLIGHT_KNEE=0.55`, `HIGHLIGHT_MIN=0.6`,
`SATURATION_MIN=0.5`, `SATURATION_MAX=1.5`, `SHADOW_RED_MAX=0.20`,
`SHADOW_RED_RETURN=0.25`, `SHADOW_RED_STEP=0.05` (`SHADOW_RED_ANCHORS` deleted
2026-08-15 — see
[shadow-red-length-reconcile](../specs/2026-08-15-shadow-red-length-reconcile-design.md)),
`TONE_ANCHORS=3`,
`TONE_MIN_GAP=6.0`, `TONE_TOP_SLOPE=0.35`, `TONE_SAMPLES=13`, `MID_BLUE_MIN=0.80`,
`MID_BLUE_MAX=1.20`, `MID_BLUE_BAND=(0.45,0.65)`, `MID_BLUE_PINS=(0.25,0.85)`,
`DIP_MAX=0.5`, `DIP_COLOR="0x141414"`.

- [x] **Step 1: Write the failing tests** (representative — cover every primitive's identity, a value, out-of-range, and `bool`)

```python
# tests/lib/test_color.py — add
import pytest
from scripts.lib import color


def test_black_point_identity_and_value():
    assert color.black_point_arg(0) == ""
    assert color.black_point_arg(0.1) == "colorlevels=rimin=0.1000:gimin=0.1000:bimin=0.1000,"


def test_black_point_rejects_bool_and_range():
    with pytest.raises(ValueError):
        color.black_point_arg(True)             # bool must not slip the == 0 shortcut
    with pytest.raises(ValueError):
        color.black_point_arg(0.5)              # > BLACK_POINT_MAX


def test_highlight_saturation_shadow_mid_dip_identities():
    assert color.highlight_arg(1.0) == ""
    assert color.saturation_arg(1.0) == ""
    assert color.shadow_red_arg(0) == ""
    assert color.mid_blue_arg(1.0) == ""
    assert color.dip_arg(0, 3.0) == ""


def test_saturation_value_and_range():
    assert color.saturation_arg(1.2) == ",eq=saturation=1.2000"
    with pytest.raises(ValueError):
        color.saturation_arg(2.0)


def test_dip_fits_the_episode():
    frag = color.dip_arg(0.2, 3.0)
    assert "fade=t=in:st=0:d=0.200:color=0x141414" in frag
    assert "fade=t=out" in frag
    with pytest.raises(ValueError):
        color.dip_arg(0.5, 0.8)                 # dur <= 2*dip → fades overlap


def test_tone_validates_anchors_and_emits_a_curve():
    frag = color.tone_arg((30, 100, 148), (35, 110, 150))
    assert frag.startswith("curves=all='") and frag.endswith("',")
    with pytest.raises(ValueError):
        color.tone_arg((30, 33, 148), (35, 110, 150))   # p5→p50 gap < TONE_MIN_GAP


def test_shadow_red_toe_only_pins_the_top():
    frag = color.shadow_red_arg(0.1)
    assert frag.startswith(",curves=r='") and "0.50/0.50" in frag and "1/1" in frag
```

- [x] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/lib/test_color.py -q` → FAIL (`AttributeError: module 'scripts.lib.color' has no attribute 'black_point_arg'`).
- [x] **Step 3: Port the primitives** — copy the constants + eight functions verbatim from `git show 4841dd3:scripts/lib/color.py` into `scripts/lib/color.py`.
- [x] **Step 4: Run to verify they pass** — `.venv/bin/python -m pytest tests/lib/test_color.py -q` → PASS.
- [x] **Step 5: Commit**

```bash
git add scripts/lib/color.py tests/lib/test_color.py
git commit -m "feat: color.py — seven per-episode grade primitives (port from 4841dd3)"
```

---

## Task 1: `color.py` — `grade_chain` composer

**Files:**
- Modify: `scripts/lib/color.py`
- Test: `tests/lib/test_color.py`

The single authority for the colour-op order (moves the composition out of
`reframe._filter_args`). `wb`/`tone` are pre-built fragments the caller supplies.

- [x] **Step 1: Write the failing test**

```python
def test_grade_chain_default_is_just_the_mixer():
    gains = (1.1, 1.0, 0.9)
    assert color.grade_chain(gains, dur=3.0) == color.mixer_arg(*gains)


def test_grade_chain_orders_every_op():
    gains = (1.0, 1.0, 1.0)
    out = color.grade_chain(gains, wb="colorchannelmixer=rr=1.010:gg=1.000:bb=0.990,",
                            tone="curves=all='0/0 1/1',", black_point=0.1, shadow_red=0.1,
                            mid_blue=0.9, saturation=1.2, highlight=0.9, dip=0.2, dur=3.0)
    # wb → tone → black_point → gain(mixer) → shadow_red → mid_blue → saturation → highlight → dip
    assert out.index("rr=1.010") < out.index("curves=all") < out.index("colorlevels")
    assert out.index("colorlevels") < out.index("gg=1.000")          # black_point before the gain
    assert out.index("colorchannelmixer=rr=1.000") < out.index("curves=r=")   # gain before shadow_red
    assert out.index("curves=r=") < out.index("curves=b=") < out.index("eq=saturation")
    assert out.index("eq=saturation") < out.index("curves=all='0/0 0.55") < out.index("fade=t=in")
```

- [x] **Step 2: Run to verify it fails** — `pytest tests/lib/test_color.py::test_grade_chain_default_is_just_the_mixer -q` → FAIL.
- [x] **Step 3: Implement**

```python
def grade_chain(gains: tuple[float, ...], *, wb: str = "", tone: str = "",
                black_point: float = 0.0, shadow_red: float = 0.0,
                mid_blue: float = 1.0, saturation: float = 1.0,
                highlight: float = 1.0, dip: float = 0.0, dur: float) -> str:
    """The colour portion of reframe's -vf tail, in the ONE correct order:
    white-balance → tone (source profile) → black_point (toe) → gain (the mixer) →
    shadow_red → mid_blue → saturation → highlight (shoulder) → dip (timeline, last).
    `wb`/`tone` are pre-built fragments (the caller builds AND verifies them — a tone
    curve is ramp-checked in reframe.verify_tone before it reaches here). Returns the
    fragment WITHOUT the trailing fps/format, which reframe owns. Every builder is ""
    at its identity value, so at defaults this returns exactly mixer_arg(*gains) and
    the fill fast path stays byte-identical to before colour-as-a-stage."""
    return (wb + tone + black_point_arg(black_point) + mixer_arg(*gains)
            + shadow_red_arg(shadow_red) + mid_blue_arg(mid_blue)
            + saturation_arg(saturation) + highlight_arg(highlight)
            + dip_arg(dip, dur))
```

- [x] **Step 4: Run to verify it passes** — `pytest tests/lib/test_color.py -q` → PASS.
- [x] **Step 5: Commit**

```bash
git add scripts/lib/color.py tests/lib/test_color.py
git commit -m "feat: color.grade_chain — the one fixed colour-op order"
```

---

## Task 2: `color.py` — additive auto white-balance

**Files:**
- Modify: `scripts/lib/color.py`
- Test: `tests/lib/test_color.py`

Grey-world neutralize toward the common channel average; OFF (`""`) at strength 0.

- [x] **Step 1: Write the failing test**

```python
def test_white_balance_off_is_identity():
    assert color.white_balance_gains((80, 100, 120), 0.0) == (1.0, 1.0, 1.0)
    assert color.white_balance_arg((80, 100, 120), 0.0) == ""


def test_white_balance_full_neutralizes_toward_the_average():
    means = (80.0, 100.0, 120.0)          # avg 100
    gr, gg, gb = color.white_balance_gains(means, 1.0)
    assert gr > 1.0 and gg == pytest.approx(1.0) and gb < 1.0   # lift low channel, drop high
    assert color.white_balance_arg(means, 1.0).endswith(",")    # leading position → trailing comma
    assert color.white_balance_arg(means, 1.0).startswith("colorchannelmixer=")


def test_white_balance_clamps_and_rejects_bool():
    # an extreme cast is clamped to [LO, HI], never past
    gains = color.white_balance_gains((10.0, 100.0, 100.0), 1.0)
    assert all(color.LO <= g <= color.HI for g in gains)
    with pytest.raises(ValueError):
        color.white_balance_arg((80, 100, 120), True)
```

- [x] **Step 2: Run to verify it fails** — FAIL (no `white_balance_gains`).
- [x] **Step 3: Implement**

```python
def white_balance_gains(means: tuple[float, ...], strength: float,
                        lo: float = LO, hi: float = HI) -> tuple[float, ...]:
    """Grey-world neutral gains: pull each channel mean toward the common average
    (true neutral) at `strength`, clamped to [lo, hi]. neutral = mean(means);
    g = clamp(1 + strength*(neutral/m - 1), lo, hi). strength 0 → (1, 1, 1).
    Unlike gains_for_means (which targets the fixed cool middle 105/122/137), this
    equalizes the channels — the "bring it to neutral first" white balance."""
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not 0 <= strength <= 1:
        raise ValueError(f"white_balance strength must be a number in [0, 1], got {strength!r}")
    if any(m <= 0 for m in means):
        raise ValueError(f"white_balance means must be positive, got {means!r} — all-black frames?")
    neutral = sum(means) / len(means)
    return tuple(max(lo, min(hi, 1 + strength * (neutral / m - 1))) for m in means)


def white_balance_arg(means: tuple[float, ...], strength: float) -> str:
    """A LEADING colorchannelmixer that neutralizes the source cast, or "" at strength 0.
    "" (not an identity mixer) so the fill fast path stays byte-identical when WB is off."""
    if isinstance(strength, bool) or not isinstance(strength, (int, float)):
        raise ValueError(f"white_balance strength must be a number in [0, 1], got {strength!r}")
    if strength == 0:
        return ""
    return mixer_arg(*white_balance_gains(means, strength)) + ","
```

- [x] **Step 4: Run to verify it passes** — PASS.
- [x] **Step 5: Commit**

```bash
git add scripts/lib/color.py tests/lib/test_color.py
git commit -m "feat: color.white_balance — additive grey-world neutralize, identity-off"
```

---

## Task 3: `color.py` — `percentiles` (pure, for the measurer)

**Files:**
- Modify: `scripts/lib/color.py`
- Test: `tests/lib/test_color.py`

- [x] **Step 1: Write the failing test**

```python
def test_percentiles_of_a_known_histogram():
    # a flat 0..255 histogram (one count per code) → p5≈12.75, p50≈127.5, p95≈242.25
    hist = [1] * 256
    p5, p50, p95 = color.percentiles(hist)
    assert 10 <= p5 <= 16 and 125 <= p50 <= 130 and 240 <= p95 <= 246


def test_percentiles_of_a_spike():
    hist = [0] * 256
    hist[100] = 1000                    # all mass at code 100
    assert color.percentiles(hist) == (100.0, 100.0, 100.0)


def test_percentiles_rejects_wrong_length():
    with pytest.raises(ValueError):
        color.percentiles([1, 2, 3])
```

- [x] **Step 2: Run to verify it fails** — FAIL.
- [x] **Step 3: Implement**

```python
def percentiles(hist256: list[int]) -> tuple[float, float, float]:
    """(p5, p50, p95) of an 8-bit luma histogram (256 bin counts), by cumulative count.
    Pure integer math — no numpy — so color.py stays dependency-free. The driver
    (color_measure.measure_profile) produces the histogram from a decoded still."""
    if len(hist256) != 256:
        raise ValueError(f"percentiles needs a 256-bin histogram, got {len(hist256)} bins")
    total = sum(hist256)
    if total <= 0:
        raise ValueError("percentiles: empty histogram — the clip decoded no pixels?")

    def _pct(p: float) -> float:
        target = p * total
        run = 0
        for code, c in enumerate(hist256):
            run += c
            if run >= target:
                return float(code)
        return 255.0

    return (_pct(0.05), _pct(0.50), _pct(0.95))
```

- [x] **Step 4: Run to verify it passes** — PASS.
- [x] **Step 5: Commit**

```bash
git add scripts/lib/color.py tests/lib/test_color.py
git commit -m "feat: color.percentiles — pure p5/p50/p95 from a luma histogram"
```

---

## Task 4: `models.py` — `ReframeSpec` nine colour fields

**Files:**
- Modify: `scripts/lib/models.py` (`ReframeSpec` fields + `__post_init__`; add `from scripts.lib import color` at top)
- Test: `tests/lib/test_models.py`

Port the parked `ReframeSpec` colour fields (`git diff 4841dd3^ 4841dd3 -- scripts/lib/models.py`)
**minus `smooth_window_s`**, and **add `white_balance: float = 0.0`**. Nine fields total:
`white_balance`, `black_point`, `highlight`, `saturation`, `shadow_red`, `mid_blue`,
`dip`, `tone_src`, `tone_dst` — all identity-default. `models` importing `color` is
safe (color imports nothing from models). tone validation delegates to `color.tone_arg`.

- [x] **Step 1: Write the failing test**

```python
# tests/lib/test_models.py — add
def test_reframespec_colour_defaults_are_identity():
    from scripts.lib.models import ReframeSpec, Delivery
    s = ReframeSpec(composition="center", grid="thirds", canvas=(1080, 1920),
                    color_means=(100, 100, 100), delivery=Delivery("native"))
    assert (s.white_balance, s.black_point, s.highlight, s.saturation, s.shadow_red,
            s.mid_blue, s.dip) == (0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0)
    assert s.tone_src is None and s.tone_dst is None


@pytest.mark.parametrize("field,bad", [
    ("white_balance", 1.5), ("black_point", 0.5), ("highlight", 0.4),
    ("saturation", 2.0), ("shadow_red", 0.5), ("mid_blue", 1.5), ("dip", 0.9)])
def test_reframespec_colour_ranges(field, bad):
    from scripts.lib.models import ReframeSpec, Delivery
    with pytest.raises(ValueError):
        ReframeSpec(composition="center", grid="thirds", canvas=(1080, 1920),
                    color_means=(100, 100, 100), delivery=Delivery("native"), **{field: bad})


def test_reframespec_tone_is_an_xor_pair_validated_by_color():
    from scripts.lib.models import ReframeSpec, Delivery
    base = dict(composition="center", grid="thirds", canvas=(1080, 1920),
                color_means=(100, 100, 100), delivery=Delivery("native"))
    with pytest.raises(ValueError):
        ReframeSpec(**base, tone_src=(30, 100, 148))          # dst missing
    with pytest.raises(ValueError):
        ReframeSpec(**base, tone_src=(30, 33, 148), tone_dst=(35, 110, 150))  # gap < 6 → color.tone_arg
    ReframeSpec(**base, tone_src=(30, 100, 148), tone_dst=(35, 110, 150))     # valid, no raise
```

- [x] **Step 2: Run to verify it fails** — FAIL.
- [x] **Step 3: Implement** — add `from scripts.lib import color` near the geometry import; add the nine fields (identity defaults) to `ReframeSpec` after `color_correct`; add validation in `__post_init__`. `white_balance` block:

```python
        if (isinstance(self.white_balance, bool) or not isinstance(self.white_balance, (int, float))
                or not 0 <= self.white_balance <= 1):
            raise ValueError(f"ReframeSpec.white_balance must be a fraction in [0, 1], "
                             f"got {self.white_balance!r}")
```

For `black_point`/`dip`/`mid_blue`/`shadow_red`/`saturation`/`highlight` and the tone
XOR + `color.tone_arg(...)` delegation, copy the parked `__post_init__` blocks verbatim
(from the models diff) — but **do not** copy the `smooth_window_s` block.

- [x] **Step 4: Run to verify it passes** — `pytest tests/lib/test_models.py -q` → PASS.
- [x] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: ReframeSpec — nine identity-default colour fields (+white_balance)"
```

---

## Task 5: `models.py` — `ExportProfile.color_range` + `CheckSpec.hue_drift_max`

**Files:**
- Modify: `scripts/lib/models.py` (`ExportProfile`, `CheckSpec`)
- Test: `tests/lib/test_models.py`

Port `ExportProfile.color_range` (field + validation + `args()` append) verbatim from the
parked models diff. Add `CheckSpec.hue_drift_max: float = 25.0` (degrees; the advisory
subject-hue-drift threshold) + validation.

- [x] **Step 1: Write the failing test**

```python
def test_export_profile_color_range():
    from scripts.lib.models import ExportProfile
    assert "-color_range" in ExportProfile().args() and "tv" in ExportProfile().args()
    assert "pc" in ExportProfile(color_range="pc").args()
    with pytest.raises(ValueError):
        ExportProfile(color_range="full")


def test_checkspec_hue_drift_max():
    from scripts.lib.models import CheckSpec
    assert CheckSpec(composition="center", grid="thirds", target_dur=3.0).hue_drift_max == 25.0
    with pytest.raises(ValueError):
        CheckSpec(composition="center", grid="thirds", target_dur=3.0, hue_drift_max=-1)
```

- [x] **Step 2: Run to verify it fails** — FAIL.
- [x] **Step 3: Implement** — port `color_range` (field default `"tv"`, `__post_init__` `in ("tv","pc")` check, `args()` appends `"-color_range", self.color_range`). Add to `CheckSpec`:

```python
    hue_drift_max: float = 25.0   # deg: advisory subject hue-drift ceiling (color_fidelity)
```
and in `CheckSpec.__post_init__`:
```python
        if (isinstance(self.hue_drift_max, bool) or not isinstance(self.hue_drift_max, (int, float))
                or self.hue_drift_max <= 0):
            raise ValueError(f"CheckSpec.hue_drift_max must be a positive number of degrees, "
                             f"got {self.hue_drift_max!r}")
```

- [x] **Step 4: Run to verify it passes** — PASS.
- [x] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: ExportProfile.color_range (tv/pc) + CheckSpec.hue_drift_max"
```

---

## Task 6: `reframe.py` — `verify_tone` + `grade_chain` wiring

**Files:**
- Modify: `scripts/reframe.py` (`_filter_args`, `reframe`, add `verify_tone`)
- Test: `tests/lib/test_reframe.py` (or the existing reframe unit test module)

Port `verify_tone` + `RAMP_PROBE_W` verbatim from the parked reframe diff. Then, under
**Approach A**, `_filter_args` takes a finished `grade` string (cleaner than the parked
8-param version); `reframe` builds `wb`/`tone`/`grade` via `color`. **Do not** port the
parked `compute_path` lead-direction fix or the `smooth_window` plumbing.

- [x] **Step 1: Write the failing tests**

```python
# tests/lib/test_reframe.py — add
from scripts.reframe import _filter_args, verify_tone
from scripts.lib import color
from scripts.lib.layout import resolve as resolve_layout
from scripts.lib.models import LayoutSpec, Delivery


def _fill_layout():
    return resolve_layout(LayoutSpec(mode="fill"), (1080, 1920), (1920, 1080), Delivery("native"))


def test_filter_args_fast_path_byte_identical_at_defaults():
    rl = _fill_layout()
    gains = (1.1, 1.0, 0.9)
    grade = color.grade_chain(gains, dur=3.0)                 # all knobs default
    got = _filter_args(rl, "0", 0, grade, 30.0, 3.0)
    assert got[0] == "-vf"
    assert got[1].endswith(f"{color.mixer_arg(*gains)},fps=30,format=yuv420p")


def test_verify_tone_rejects_a_banding_curve():
    # a deliberately non-monotone anchor triple; verify_tone must raise
    frag = color.tone_arg((10, 20, 245), (200, 30, 210))
    with pytest.raises(RuntimeError):
        verify_tone(frag)


def test_verify_tone_accepts_a_gentle_monotone_curve():
    verify_tone(color.tone_arg((30, 100, 148), (35, 110, 150)))   # no raise
```

(`test_verify_tone_*` need a working ffmpeg — mark with `@pytest.mark.integration` if the
module separates them, else they run in the unit suite as the repo's ffmpeg is baseline.)

- [x] **Step 2: Run to verify they fail** — FAIL (`_filter_args` takes `gains`, not `grade`; no `verify_tone`).
- [x] **Step 3: Implement**
  - Add `verify_tone` + `RAMP_PROBE_W` (copy from parked reframe diff).
  - Change `_filter_args` signature to `(rl, xexpr, cy, grade, fps, dur)` and body:
    ```python
    tail = f"{grade},fps={fps:.6g},format=yuv420p"
    if rl.fast_path:
        return ["-vf", (f"crop={rl.crop_w}:{rl.crop_h}:x='{xexpr}':y={cy},"
                        f"scale={rl.out_w}:{rl.out_h},{tail}")]
    rx, ry, rw, rh = rl.rect_px
    b = rl.border_px
    ox, oy, ow, oh = rx - b, ry - b, rw + 2 * b, rh + 2 * b
    bg_chain, fg_src, ov_opts = _background_args(rl, fps, dur)
    pad = f",pad={ow}:{oh}:{b}:{b}:{rl.border_color}" if b else ""
    return ["-filter_complex",
            (f"{bg_chain}"
             f"{fg_src}crop={rl.crop_w}:{rl.crop_h}:x='{xexpr}':y={cy},scale={rw}:{rh}{pad}[fg];"
             f"[bg][fg]overlay={ox}:{oy}{ov_opts},{tail}")]
    ```
  - In `reframe`, after the existing `gains`/`color_correct` block, build the grade and pass it:
    ```python
    gains = color.gains_for_means(spec.color_means)
    if spec.color_correct is not None:  # reel retry loop; see docstring
        gains = color.corrected(gains, spec.color_correct)
    wb = color.white_balance_arg(spec.color_means, spec.white_balance)
    tone = ""
    if spec.tone_src is not None:
        tone = color.tone_arg(tuple(spec.tone_src), tuple(spec.tone_dst))
        verify_tone(tone)      # a banding spline fails HERE, not in the delivered reel
    grade = color.grade_chain(gains, wb=wb, tone=tone, black_point=spec.black_point,
                              shadow_red=spec.shadow_red, mid_blue=spec.mid_blue,
                              saturation=spec.saturation, highlight=spec.highlight,
                              dip=spec.dip, dur=dur)
    ```
    and change the command splice to `*_filter_args(rl, xexpr, cy, grade, fps, dur),`.

- [x] **Step 4: Run to verify they pass, and the whole reframe suite stays green** — `pytest tests/lib/test_reframe.py tests/integration -k reframe -q` → PASS (the fast-path pin is the byte-identical guard).
- [x] **Step 5: Commit**

```bash
git add scripts/reframe.py tests/lib/test_reframe.py
git commit -m "feat: reframe builds grade via color.grade_chain + verify_tone (Approach A)"
```

---

## Task 7: `lib/color_fidelity.py` — pure hue-drift metric (new)

**Files:**
- Create: `scripts/lib/color_fidelity.py`
- Test: `tests/lib/test_color_fidelity.py`

- [x] **Step 1: Write the failing test**

```python
# tests/lib/test_color_fidelity.py — new
import pytest
from scripts.lib import color_fidelity as cf


def test_exposure_and_saturation_do_not_count_as_drift():
    base = (150.0, 90.0, 60.0)
    assert cf.hue_drift(base, (75.0, 45.0, 30.0)) == pytest.approx(0.0, abs=1.0)   # 0.5x exposure
    # scale chroma about the mean (saturation up) — hue angle is unchanged
    m = sum(base) / 3
    sat = tuple(m + (c - m) * 1.4 for c in base)
    assert cf.hue_drift(base, sat) == pytest.approx(0.0, abs=2.0)


def test_a_real_hue_rotation_is_drift():
    assert cf.hue_drift((150.0, 90.0, 60.0), (60.0, 150.0, 90.0)) > 60.0   # orange → green


def test_near_grey_has_no_hue():
    assert cf.hue((128.0, 130.0, 129.0)) is None
    assert cf.hue_drift((128.0, 130.0, 129.0), (60.0, 150.0, 90.0)) is None


def test_evaluate_worst_and_threshold():
    pairs = [((150, 90, 60), (150, 90, 60)), ((150, 90, 60), (60, 150, 90))]
    d = cf.evaluate(pairs, threshold=25.0)
    assert d["exceeded"] is True and d["worst_drift_deg"] > 60 and d["samples"] == 2
    grey = cf.evaluate([((128, 130, 129), (100, 101, 102))], threshold=25.0)
    assert grey["status"] == "not-checked"
```

- [x] **Step 2: Run to verify it fails** — FAIL (module missing).
- [x] **Step 3: Implement**

```python
"""Advisory colour-fidelity metric (design 2026-07-26 §7): subject hue drift,
source vs graded. Pure — the ffmpeg/PIL sampling lives in check_episode."""
import colorsys

GREY_EPS = 10.0     # min chroma (max-min of mean RGB, 0-255) for a defined hue


def hue(rgb: tuple[float, float, float]) -> float | None:
    """HSV hue angle in degrees, or None when the colour is too near grey to have one.
    Hue is invariant to exposure (scaling all channels) and to saturation (scaling
    chroma about grey), so a drift in it means a real hue shift, not the grade's
    intended exposure/saturation move."""
    if max(rgb) - min(rgb) < GREY_EPS:
        return None
    h, _, _ = colorsys.rgb_to_hsv(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)
    return h * 360.0


def hue_drift(src_rgb: tuple[float, float, float],
              graded_rgb: tuple[float, float, float]) -> float | None:
    """Circular hue distance in degrees, or None when either side is near-grey."""
    hs, hg = hue(src_rgb), hue(graded_rgb)
    if hs is None or hg is None:
        return None
    d = abs(hs - hg)
    return min(d, 360.0 - d)


def evaluate(pairs: list[tuple], threshold: float) -> dict:
    """Aggregate per-sample (src_rgb, graded_rgb) pairs into an advisory result.
    All-grey samples → not-checked (a grey subject cannot 'drift')."""
    drifts = [d for src, graded in pairs if (d := hue_drift(src, graded)) is not None]
    if not drifts:
        return {"status": "not-checked", "reason": "subject near-grey in every sample"}
    worst = max(drifts)
    return {"worst_drift_deg": round(worst, 1), "threshold": threshold,
            "exceeded": worst > threshold, "samples": len(drifts)}
```

- [x] **Step 4: Run to verify it passes** — PASS.
- [x] **Step 5: Commit**

```bash
git add scripts/lib/color_fidelity.py tests/lib/test_color_fidelity.py
git commit -m "feat: lib/color_fidelity — pure subject hue-drift metric"
```

---

## Task 8: `check_episode.py` — advisory colour-fidelity check

**Files:**
- Modify: `scripts/check_episode.py` (`run` gains `source=`; a sampling helper; the advisory check)
- Test: `tests/lib/test_check_episode.py` + `tests/integration/test_color_fidelity.py`

Sample the subject region in the source (route bbox, source px) and in the graded clip
(`geometry.extent_at_times` → output px) at K times; call `color_fidelity.evaluate`;
report `CheckResult("color_fidelity", None, …)` — advisory, `passed=None`, excluded from
`overall`. `source=None`, a pan, or an empty route → `not-checked`.

- [x] **Step 1: Write the failing tests** (a pure-logic unit for the `not-checked` arms + an integration proof)

```python
# tests/lib/test_check_episode.py — add
def test_color_fidelity_not_checked_without_source(tmp_path):
    # build a minimal graded clip + route + sidecar via the existing fixtures, call run
    # with source=None, and assert the color_fidelity check is reported not-checked.
    ...  # reuse this module's existing clip/route/meta fixture; assert:
    # report.checks["color_fidelity"].passed is None
    # report.checks["color_fidelity"].detail["status"] == "not-checked"
```

```python
# tests/integration/test_color_fidelity.py — new (real ffmpeg)
import pytest
pytestmark = pytest.mark.integration
# Build a source clip with a coloured subject box, reframe it once ungraded and once with
# a deliberate hue-breaking grade (e.g. saturation + a mid_blue that flips skin), run
# check_episode with source=<raw>, and assert:
#   - the faithful grade → color_fidelity detail["exceeded"] is False
#   - the hue-broken grade → detail["exceeded"] is True, worst_drift_deg large
#   - color_fidelity never sets report.overall to False (advisory)
```

- [x] **Step 2: Run to verify they fail** — FAIL (`run` has no `source`).
- [x] **Step 3: Implement**
  - `run(clip, route_path, path_path, spec, out, source: str | None = None)`.
  - Keep the CropPath object (not only `.xs`) and the `RoutePoint` list for the projection:
    ```python
    path_obj = CropPath.from_json(path_path)
    ...
    route_pts = None if meta.pan or route_path is None else route_from_json(route_path)
    ```
  - After the `black_frames` check, add:
    ```python
    checks["color_fidelity"] = _colour_fidelity(clip, source, route_pts, path_obj, meta, spec)
    ```
  - New module-level helper (uses PIL, already imported):
    ```python
    def _region_mean_rgb(clip: str, t: float, box: tuple[int, int, int, int]) -> tuple[float, float, float]:
        """Mean (R,G,B) of a pixel box in one grabbed frame at time t. box = (x0,y0,x1,y1)."""
        with tempfile.TemporaryDirectory() as tmp:
            f = f"{tmp}/f.png"
            proc.run([ffbin.ffmpeg(), "-y", "-i", clip, "-ss", f"{t:.3f}",
                      "-frames:v", "1", f])          # -ss AFTER -i (§12 seek order)
            im = Image.open(f).convert("RGB")
            x0, y0, x1, y1 = box
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(im.width, max(x1, x0 + 1)), min(im.height, max(y1, y0 + 1))
            return tuple(ImageStat.Stat(im.crop((x0, y0, x1, y1))).mean[:3])


    def _colour_fidelity(clip, source, route_pts, path_obj, meta, spec) -> "CheckResult":
        if source is None or not route_pts:
            return CheckResult("color_fidelity", None,
                               {"status": "not-checked",
                                "reason": "no source clip or no tracked subject"})
        ts = [p.t for p in route_pts]
        times = [ts[0] + (ts[-1] - ts[0]) * f for f in (0.25, 0.5, 0.75)]
        extents = geometry.extent_at_times(route_pts, path_obj, meta, times)   # output fractions
        out_w, out_h = meta.out_dims
        pairs = []
        for t, (fx0, fy0, fx1, fy1) in zip(times, extents):
            p = min(route_pts, key=lambda q: abs(q.t - t))          # nearest source bbox
            sbox = (round(p.x - p.w / 2), round(p.y - p.h / 2),
                    round(p.x + p.w / 2), round(p.y + p.h / 2))
            gbox = (round(fx0 * out_w), round(fy0 * out_h), round(fx1 * out_w), round(fy1 * out_h))
            pairs.append((_region_mean_rgb(source, t, sbox), _region_mean_rgb(clip, t, gbox)))
        return CheckResult("color_fidelity", None,
                           color_fidelity.evaluate(pairs, spec.hue_drift_max))
    ```
  - Imports: `from scripts.lib import color_fidelity` and ensure `geometry`, `route_from_json`, `CropPath` are imported (geometry + route_from_json + CropPath already are).
  - **Advisory:** `passed=None` keeps it out of `report.overall` (same convention as the zero-freedom `framing` check). Confirm `Report.overall`/`fail_reasons` ignore `passed is None`.

- [x] **Step 4: Run to verify they pass** — `pytest tests/lib/test_check_episode.py tests/integration/test_color_fidelity.py -q` → PASS.
- [x] **Step 5: Commit**

```bash
git add scripts/check_episode.py tests/lib/test_check_episode.py tests/integration/test_color_fidelity.py
git commit -m "feat: check_episode — advisory subject hue-drift (source vs graded)"
```

---

## Task 9: authoring carriers — `EDLEpisode` + `Manifest`

**Files:**
- Modify: `scripts/lib/edl.py` (`EDLEpisode` +9 fields, `to_dict`, `to_manifest_dict`)
- Modify: `scripts/lib/manifest.py` (`Manifest` +9 fields, `OPTIONAL`, `from_dict`)
- Modify: `scripts/edit_plan.py` (`window_to_episode` docstring only — list the colour fields)
- Test: `tests/lib/test_edl.py`, `tests/lib/test_manifest.py`

Port the parked `edl.py`/`manifest.py` colour additions and **add `white_balance`** to
each (parked had 8; we carry 9). The editorial passthrough in `build_edl`/`window_to_episode`
is already generic (`**ed` → `EDLEpisode(**editorial)`), so **no `edit_plan` logic change** —
only extend `window_to_episode`'s docstring field list to mention the colour knobs.

- [x] **Step 1: Write the failing tests**

```python
# tests/lib/test_edl.py — add
def test_edlepisode_colour_round_trips():
    from scripts.lib.edl import EDLEpisode
    ep = EDLEpisode(source="a.mp4", start=0.0, dur=2.0, composition="center", grid="thirds",
                    white_balance=0.5, black_point=0.1, saturation=1.2,
                    tone_src=(30, 100, 148), tone_dst=(35, 110, 150))
    d = ep.to_dict()
    assert d["white_balance"] == 0.5 and d["tone_src"] == [30, 100, 148]
    md = to_manifest_dict(ep, "seg.mp4", "out.mp4")   # import as the module does
    assert md["white_balance"] == 0.5 and md["saturation"] == 1.2 and md["tone_dst"] == [35, 110, 150]
```

```python
# tests/lib/test_manifest.py — add
def test_manifest_from_dict_reads_colour():
    from scripts.lib.manifest import Manifest
    m = Manifest.from_dict({"segment": "s.mp4", "out_path": "o.mp4", "composition": "center",
                            "grid": "thirds", "canvas": [1080, 1920], "target_dur": 2.0,
                            "white_balance": 0.5, "dip": 0.2, "tone_src": [30, 100, 148],
                            "tone_dst": [35, 110, 150]})
    assert m.white_balance == 0.5 and m.dip == 0.2 and m.tone_src == (30, 100, 148)


def test_manifest_colour_defaults_identity():
    from scripts.lib.manifest import Manifest
    m = Manifest.from_dict({"segment": "s.mp4", "out_path": "o.mp4", "composition": "center",
                            "grid": "thirds", "canvas": [1080, 1920], "target_dur": 2.0})
    assert (m.white_balance, m.black_point, m.saturation, m.dip) == (0.0, 0.0, 1.0, 0.0)
    assert m.tone_src is None
```

- [x] **Step 2: Run to verify they fail** — FAIL.
- [x] **Step 3: Implement**
  - `EDLEpisode`: add the 9 fields (copy the parked 8 + add `white_balance: float = 0.0`); extend `to_dict` and `to_manifest_dict` to emit all 7 scalars always and the tone pair only when set (copy the parked `**({"tone_src": …} if … else {})` idioms, adding `white_balance`).
  - `Manifest`: add the 9 fields; add their names to `OPTIONAL` (copy parked, add `"white_balance"`); add the `from_dict` parses (copy parked, add `white_balance=float(d.get("white_balance") or 0.0)`).
  - `window_to_episode` docstring: add `white_balance/black_point/highlight/saturation/shadow_red/mid_blue/dip/tone_src/tone_dst` to the "optional editorial fields" list.

- [x] **Step 4: Run to verify they pass** — `pytest tests/lib/test_edl.py tests/lib/test_manifest.py -q` → PASS.
- [x] **Step 5: Commit**

```bash
git add scripts/lib/edl.py scripts/lib/manifest.py scripts/edit_plan.py tests/lib/test_edl.py tests/lib/test_manifest.py
git commit -m "feat: EDLEpisode + Manifest carry the nine colour fields"
```

---

## Task 10: `process_episode.py` — manifest→spec wiring

**Files:**
- Modify: `scripts/process_episode.py` (the `ReframeSpec(...)` construction; the `check_episode.run` call)
- Test: covered by the integration golden (Task 15); an optional spy unit below

Thread the nine colour fields from the `Manifest` into `ReframeSpec`, and pass the
pre-grade segment `src` to the check as `source=`. **Exclude `smooth_window_s`** from the
parked block.

- [x] **Step 1: Write the failing test** (a spy that `ReframeSpec` receives the colour fields — monkeypatch `reframe.reframe` and `check_episode.run` so no ffmpeg runs)

```python
# tests/lib/test_process_episode.py — add (or the module that already fakes reframe)
def test_process_episode_threads_colour_and_source(monkeypatch, tmp_path):
    # Arrange a manifest dict with white_balance/dip set; monkeypatch reframe.reframe to
    # capture its ReframeSpec, and check_episode.run to capture its source= kwarg.
    # Assert captured spec.white_balance == 0.5, spec.dip == 0.2, and the check's source
    # is the reframe input path (pre-grade segment).
    ...
```

- [x] **Step 2: Run to verify it fails** — FAIL (`ReframeSpec` built without colour fields; check has no `source=`).
- [x] **Step 3: Implement** — in the `ReframeSpec(...)` build, add (do NOT add `smooth_window_s`):

```python
        rspec = ReframeSpec(composition=m.composition, grid=m.grid, canvas=m.canvas,
                            color_means=m.color_means, delivery=delivery, layout=lspec,
                            max_speed=params["max_speed"], color_correct=color_correct,
                            white_balance=m.white_balance, black_point=m.black_point,
                            highlight=m.highlight, saturation=m.saturation,
                            shadow_red=m.shadow_red, mid_blue=m.mid_blue, dip=m.dip,
                            tone_src=m.tone_src, tone_dst=m.tone_dst, pan=pan)
```

and pass the pre-grade segment to the check:

```python
        report = _timed("check", lambda: check_episode.run(
            m.out_path, rp, path_out, cspec, str(Path(project_dir) / "report.json"), source=src))
```

- [x] **Step 4: Run to verify it passes** — PASS.
- [x] **Step 5: Commit**

```bash
git add scripts/process_episode.py tests/lib/test_process_episode.py
git commit -m "feat: process_episode threads the colour grade + source into the check"
```

---

## Task 11: `assembly.py` — colour-range correctness

**Files:**
- Modify: `scripts/lib/assembly.py`
- Test: `tests/lib/test_assembly.py`

Port verbatim from the parked assembly diff: `DELIVERY_RANGE`, `StreamInfo.color_range`,
the `probe_stream` `color_range` select + read, `matches(color_range=)`, and
`_normalize`'s `in_range=auto:out_range=` convert + `-color_range` tag.

- [x] **Step 1: Write the failing test**

```python
# tests/lib/test_assembly.py — add
def test_matches_treats_a_differing_range_as_an_outlier():
    from scripts.lib.assembly import StreamInfo, matches, DELIVERY_RANGE
    tv = StreamInfo(1080, 1920, 30.0, "yuv420p", "h264", "tv")
    pc = StreamInfo(1080, 1920, 30.0, "yuv420p", "h264", "pc")
    assert matches(tv, (1080, 1920), 30.0) is True
    assert matches(pc, (1080, 1920), 30.0) is False          # pc ≠ DELIVERY_RANGE tv
    unknown = StreamInfo(1080, 1920, 30.0, "yuv420p", "h264", "unknown")
    assert matches(unknown, (1080, 1920), 30.0) is False      # never assume an untagged stream
    assert DELIVERY_RANGE == "tv"
```

- [x] **Step 2: Run to verify it fails** — FAIL (`StreamInfo` has no `color_range`).
- [x] **Step 3: Implement** — copy the parked assembly changes.
- [x] **Step 4: Run to verify it passes, plus the assemble goldens stay green** — `pytest tests/lib/test_assembly.py tests/integration -k assemble -q` → PASS.
- [x] **Step 5: Commit**

```bash
git add scripts/lib/assembly.py tests/lib/test_assembly.py
git commit -m "feat: assembly — probe/match/normalize colour range (tv/pc) for -c copy"
```

---

## Task 12: `edl_to_reel.py` — `--color-delta-max` override

**Files:**
- Modify: `scripts/edl_to_reel.py`
- Test: `tests/lib/test_edl_to_reel.py`

Add `color_delta_max: float | None = None` to `edl_to_reel(...)` (keyword-only, in the
`*` group) and a `--color-delta-max` CLI flag; when set, pass it into `ReelManifest`
(`**({} if None else {"color_delta_max": …})`). **Do not** add `platform` (safe-zones
follow-up — the current signature has none, and colour is this slice's scope).

- [x] **Step 1: Write the failing test**

```python
def test_color_delta_max_overrides_the_reel_ceiling(monkeypatch, tmp_path):
    # monkeypatch build_reel.build_reel to capture the ReelManifest, drive edl_to_reel on a
    # tiny valid EDL/project, and assert the captured rm.color_delta_max == 20.0 when passed,
    # and the ReelCheckSpec default (12.0) when omitted.
    ...
```

- [x] **Step 2: Run to verify it fails** — FAIL (`edl_to_reel` has no `color_delta_max`).
- [x] **Step 3: Implement** — copy the parked edl_to_reel `color_delta_max` pieces only (the `extra = {} if color_delta_max is None else {"color_delta_max": color_delta_max}`, `ReelManifest(..., **extra)`, the CLI flag + its docstring), leaving `platform` out.
- [x] **Step 4: Run to verify it passes** — PASS.
- [x] **Step 5: Commit**

```bash
git add scripts/edl_to_reel.py tests/lib/test_edl_to_reel.py
git commit -m "feat: edl_to_reel --color-delta-max overrides the across-cut ceiling"
```

---

## Task 13: `scripts/color_measure.py` — the tone measurer (new)

**Files:**
- Create: `scripts/color_measure.py`
- Test: `tests/integration/test_color_measure.py`

A per-clip `(p5,p50,p95)` luma reader so `tone` is hand-authorable. Decodes a downscaled
grayscale still (numpy in the driver only) → 256-bin histogram → `color.percentiles`.

- [x] **Step 1: Write the failing test** (real ffmpeg — a synthesized mid-grey clip has all three percentiles near its known level)

```python
# tests/integration/test_color_measure.py — new
import pytest
pytestmark = pytest.mark.integration
# Synthesize a flat colour clip (e.g. color=c=gray) via ffmpeg, run measure_profile, and
# assert p5 ≈ p50 ≈ p95 ≈ the known luma (within a few codes). Then a two-band clip
# (dark half / bright half) → p5 low, p95 high, p50 between.
```

- [x] **Step 2: Run to verify it fails** — FAIL (module missing).
- [x] **Step 3: Implement**

```python
"""Measure a clip's (p5, p50, p95) luma — the authoring aid for ReframeSpec.tone
(design 2026-07-26 §5). Pure percentile math lives in color.percentiles; this driver
only produces the histogram from a decoded still."""
import argparse
import subprocess
import numpy as np
from scripts.lib import color, ffbin, proc


def measure_profile(clip: str, at: float | None = None) -> tuple[float, float, float]:
    """(p5, p50, p95) luma of `clip` at time `at` (default: 1s in — a settled frame).
    Decodes ONE 160-wide grayscale still to rawvideo, histograms it, and delegates the
    percentiles to color.percentiles (numpy stays in this driver, out of lib/color)."""
    t = 1.0 if at is None else at
    out = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", clip, "-ss", f"{t:.3f}",
                    "-frames:v", "1", "-vf", "scale=160:-2,format=gray",
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout      # -ss AFTER -i (§12)
    if not out:
        raise RuntimeError(f"color_measure: no frame decoded from {clip} at {t:.2f}s")
    hist = np.bincount(np.frombuffer(out, dtype=np.uint8), minlength=256)[:256]
    return color.percentiles([int(c) for c in hist])


def main() -> None:
    ap = argparse.ArgumentParser(description="measure a clip's (p5,p50,p95) luma for ReframeSpec.tone")
    ap.add_argument("clip")
    ap.add_argument("--at", type=float, default=None, help="sample time in seconds (default 1.0)")
    a = ap.parse_args()
    p5, p50, p95 = measure_profile(a.clip, a.at)
    print(f"p5={p5:.1f} p50={p50:.1f} p95={p95:.1f}")
    print(f'tone_src: [{p5:.0f}, {p50:.0f}, {p95:.0f}]')


if __name__ == "__main__":
    main()
```

(The `import subprocess` line is only if the file needs it; if `proc.run` covers all calls,
omit it — the landmine-lint requires the `subprocess` import allowlist to match actual use.)

- [x] **Step 4: Run to verify it passes** — `pytest tests/integration/test_color_measure.py -q` → PASS.
- [x] **Step 5: Commit**

```bash
git add scripts/color_measure.py tests/integration/test_color_measure.py
git commit -m "feat: color_measure — per-clip (p5,p50,p95) luma for tone authoring"
```

---

## Task 14: `edit-plan` SKILL — colour authoring guidance

**Files:**
- Modify: `skills/edit-plan/SKILL.md`
- Test: none (docs); a manual read-through

- [x] **Step 1: Add a colour paragraph** after the layout/background bullets in the "Author `selection.json`" section:

> **Colour (optional, per episode).** Every episode carries an identity-default grade, so
> omit these unless a clip needs correcting. `white_balance` (0–1) neutralizes a cast
> first (grey-world; 0 = off). `black_point` (0–0.35) lifts a washed toe; `highlight`
> (0.6–1.0) tames blown whites; `saturation` (0.5–1.5) scales chroma; `shadow_red`
> (0–0.20) neutralizes a green/cyan black; `mid_blue` (0.80–1.20) fixes sky-bounce on
> skin; `dip` (0–0.5 s) fades in/out to dark grey. `tone` matches a clip's profile to the
> reel: set `tone_src` to that clip's measured `[p5, p50, p95]` and `tone_dst` to the
> common target — measure both with `bin/vg color_measure <clip>`. A banding tone curve
> fails loud at render (verify_tone), so trust the error's advice to widen the anchors.

- [x] **Step 2: Add the field to the shape example** — one episode with e.g. `"white_balance": 0.5, "saturation": 1.1`.
- [x] **Step 3: Commit**

```bash
git add skills/edit-plan/SKILL.md
git commit -m "docs: edit-plan SKILL — colour grade / white-balance / tone authoring"
```

---

## Task 15: real-ffmpeg proofs (integration battery)

**Files:**
- Create/extend: `tests/integration/test_colour_stage.py`
- Test: itself

Prove the load-bearing behaviours on real bytes (some overlap Tasks 6/8/13 — consolidate
the cross-cutting proofs here).

- [x] **Step 1: Write the failing tests**

```python
# tests/integration/test_colour_stage.py — new
import pytest
pytestmark = pytest.mark.integration
# 1. fast-path byte-identical: reframe a fill episode with all colour defaults; assert the
#    emitted -vf equals the pre-slice command (mixer,fps,format) — the regression pin.
# 2. the grade moves pixels: reframe once default, once with saturation=1.4 + black_point=0.1;
#    assert the two outputs' mean/hue differ measurably.
# 3. white_balance=0 renders byte-identical to omitting it (the additive/identity pin).
# 4. tv/pc concat: assemble two episodes, one tagged pc, one tv; assert the delivered
#    master's per-episode contrast is preserved (not milky) and the range tag is tv.
# 5. verify_tone: a banding triple raises at reframe time (episode never delivers).
```

- [x] **Step 2: Run to verify they fail** — FAIL.
- [x] **Step 3: Implement the fixtures/assertions** (reuse `sample_clip` and the existing
  integration helpers; measure means via `ffprobe`/PIL as the other integration tests do).
- [x] **Step 4: Run to verify they pass** — `pytest tests/integration/test_colour_stage.py -q` → PASS.
- [x] **Step 5: Commit**

```bash
git add tests/integration/test_colour_stage.py
git commit -m "test: real-ffmpeg colour-stage proofs (byte-identical, grade moves pixels, range)"
```

---

## Task 16: docs sync + final whole-slice review

**Files:**
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`, this plan (tick checkboxes)

- [x] **Step 1: Run the whole suite** — `.venv/bin/python -m pytest -q`. Record the exact pass/skip counts.
- [x] **Step 2: build-status** — add a "colour-as-a-stage (slice F) DONE" entry (the parked port + WB + measurer + fidelity check + range correctness; what is deferred: the conductor, mood LUT, `smooth_window_s`, `edl_to_reel` `platform`). Bump `_Last updated_`.
- [x] **Step 3: pipeline-map** — note colour is now a per-episode actuator at §5.10 (the grade rides reframe) + the advisory fidelity check at episode postcheck; the design §10 match-grade conductor stays deferred.
- [x] **Step 4: CLAUDE.md** — add two registry rows (the colour-stage design + this plan) in the Quick Reference table.
- [x] **Step 5: Tick this plan's checkboxes** (`- [ ]` → `- [x]`), then commit.

```bash
git add docs/ CLAUDE.md
git commit -m "docs: register colour-as-a-stage (slice F) — build-status, pipeline-map, registry"
```

- [x] **Step 6: Final whole-slice review** — dispatch a fresh reviewer (opus) over the branch diff vs `main`: assert the fast path is byte-identical at defaults (the regression pin), `grade_chain` is the single order authority, `white_balance` is identity-off, the fidelity check is advisory (never sets `overall` False), no `lutrgb` reaches an argv (landmine-lint green), and `smooth_window_s`/`platform` were correctly excluded.

---

## Self-Review Notes

**Spec coverage.** §1 color.py primitives → Task 0; grade_chain → Task 1; white_balance
→ Task 2; percentiles → Task 3. §2/§3 ReframeSpec + reframe verify_tone/grade_chain →
Tasks 4, 6. §3 measurer → Task 13. §4 authoring carriers → Task 9; process_episode
bridge → Task 10. §5 range correctness → Tasks 5 (ExportProfile) + 11 (assembly) + 12
(edl_to_reel override). §6 white balance → Task 2 (+ wiring in 4/6/9/10). §7 fidelity
check → Tasks 5 (CheckSpec.hue_drift_max) + 7 (color_fidelity) + 8 (check_episode). §8
landmines → covered across Tasks 0 (dip grey/`dur≤2·dip`), 6 (verify_tone), 16 (lint
green). §9 testing → Tasks 0–15 unit + 8/13/15 integration. §10/§11 SKILL/non-goals →
Task 14 + the exclusions stated in File Structure.

**Placeholder scan.** Tasks 8, 10, 12, 15 use `...` inside test bodies that reuse existing
module fixtures whose exact shape the implementer reads in-repo; every one names the exact
asserts required. All production code is given in full or pointed at the exact
`git show 4841dd3:<path>` to copy verbatim (the seven primitives, the parked field blocks,
assembly, verify_tone) — deliberate, to avoid a transcription typo in a 230-line port.

**Type consistency.** `grade_chain(gains, *, wb, tone, black_point, shadow_red, mid_blue,
saturation, highlight, dip, dur)` is called with those exact keywords in Task 6.
`white_balance_arg(means, strength)` and `white_balance_gains(means, strength)` match
Tasks 2/6. The nine `ReframeSpec`/`EDLEpisode`/`Manifest` field names
(`white_balance, black_point, highlight, saturation, shadow_red, mid_blue, dip, tone_src,
tone_dst`) are identical across Tasks 4, 9, 10. `CheckSpec.hue_drift_max` (Task 5) is read
in Task 8. `color_fidelity.evaluate(pairs, threshold)` (Task 7) is called with
`spec.hue_drift_max` in Task 8. `_filter_args(rl, xexpr, cy, grade, fps, dur)` (Task 6)
matches its one caller.
