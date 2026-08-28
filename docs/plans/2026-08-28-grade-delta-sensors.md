# Grade-damage sensors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two blind colour sensors with one blocking measurement of
what the grade did to the subject (CIEDE2000, source→graded) and one advisory
measurement of what it did to the frame (source-relative deltas).

**Architecture:** A new pure `lib/colordiff.py` owns sRGB→Lab and CIEDE2000.
`lib/color_fidelity.py` is rewritten on top of it — the hue angle and its grey
floor are deleted, the per-episode **median ΔE00** becomes the verdict, and the
three signed components ride along as the explanation. `check_episode` samples
five points through `assembly.frames_rgb` (one decode per file instead of one
per sample), the check becomes blocking, and `orchestration` learns that a
colour failure cannot be fixed by a geometry knob. `lib/naturalness.py` keeps
only its two absolute clipping flags and gains a source-relative
`evaluate_delta`; `episode_qc.pack` reads the pre-grade segment it has always
held and puts both readings in front of the judge.

**Tech Stack:** Python 3, stdlib `math`/`statistics`, numpy (already a
dependency), ffmpeg via `scripts/lib/assembly.frames_rgb`, pytest.

**Design:** [docs/specs/2026-08-28-grade-delta-sensors-design.md](../specs/2026-08-28-grade-delta-sensors-design.md)

## Global Constraints

- **Scripts are modules.** Run everything as `python -m scripts.<name>`;
  `pytest.ini` sets `pythonpath = .`. The interpreter is `.venv/bin/python`.
- **Fail loud.** Every refusal is a `ValueError`/`RuntimeError` whose message
  names the remedy. No silent fallbacks, no defaults that paper over bad input.
- **Imports at top of file.** No function-local imports.
- **Type hints on every public signature.** Dataclass conventions per
  [docs/coding-standards.md](../coding-standards.md).
- **Thresholds live in exactly one place.** A threshold a caller can pass is a
  threshold a subagent can pass — `naturalness`'s constants are module-level and
  are not parameters. `CheckSpec.grade_delta_max` is the one exception, because
  `CheckSpec` is the episode's config-spec and every other check bar lives there
  too.
- **Do NOT install anything.** No `brew`, `pip install`, `npm`, `uv`, no running
  `setup.sh`. The runtime is already installed. Verification is read-only plus
  `pytest`.
- **Do NOT run `git checkout --`, `git restore`, `git reset --hard`, or
  `git stash`.** If a change must be undone, undo it with an edit.
- **Never touch `/Users/serg/Downloads/untitled folder`.** It is a preserved
  real run kept for calibration. Read-only at most; this plan needs no access
  to it at all.
- **Landmines that apply here** (full registry: `CLAUDE.md`): `-ss` goes AFTER
  `-i`; `select` placed before a chain's `fps=` emits the same frame N times —
  `assembly.frames_rgb` already routes around both, which is one reason this
  plan moves sampling onto it.
- **Exact measured values are not negotiable.** `5.0`, `0.08`, `0.12`, `20.0`
  and the five sample fractions come from measurements recorded in the design's
  §0; do not round, retune or "improve" them.

---

## File Structure

| file | responsibility |
|---|---|
| `scripts/lib/colordiff.py` | **new.** sRGB→Lab and CIEDE2000. Colour-difference arithmetic only. |
| `scripts/lib/color_fidelity.py` | **rewritten.** Per-episode subject verdict from a list of (source, graded) mean-RGB pairs. |
| `scripts/lib/models.py` | `CheckSpec.hue_drift_max` → `CheckSpec.grade_delta_max`. |
| `scripts/check_episode.py` | Batched five-point sampling; the check's `passed` becomes a boolean. |
| `scripts/lib/orchestration.py` | `color_fidelity` joins `_UNFIXABLE`; a per-reason escalation message. |
| `scripts/lib/naturalness.py` | `evaluate` trimmed to the two absolute flags; new `evaluate_delta`. |
| `scripts/episode_qc.py` | The evidence packet gains `naturalness.source` and `naturalness.delta`. |
| `tests/lib/test_colordiff.py` | **new.** 21 published CIEDE2000 reference pairs. |
| `tests/lib/test_color_fidelity.py` | **rewritten** for the new contract. |
| `tests/lib/test_naturalness.py` | **rewritten** for the trimmed `evaluate` + `evaluate_delta`. |
| `tests/integration/test_color_fidelity.py` | **rewritten**: real-ffmpeg damage/control proofs. |
| `tests/lib/test_orchestration.py` | the `grade-damage` escalation. |
| `tests/integration/test_episode_qc.py` | the evidence packet's two new keys. |

---

## Task 0: `lib/colordiff.py` — the colour-difference primitive

**Files:**
- Create: `scripts/lib/colordiff.py`
- Test: `tests/lib/test_colordiff.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `colordiff.rgb_to_lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]`
  and `colordiff.ciede2000(lab1, lab2) -> tuple[float, float, float, float]`
  returning `(dE00, dL_prime, dC_prime, dH_prime)`.

- [ ] **Step 1: Write the failing test**

Create `tests/lib/test_colordiff.py`. The 21 pairs below are from the published
CIEDE2000 test data (Sharma, Wu & Dalal); they include the discontinuity cases
the formula's `R_T` and mean-hue terms exist to handle, which is why a naive
implementation passes the easy rows and fails these.

```python
"""The colour-difference primitive (design docs/specs/2026-08-28-grade-delta-sensors-design.md §2.1)."""
import pytest

from scripts.lib import colordiff


# Published CIEDE2000 reference pairs (Sharma/Wu/Dalal): (lab1, lab2, expected dE00).
# The 1.0000 rows are the deliberate near-discontinuity cases; the 7.1792 row
# straddles the a'-axis where the mean-hue term has to pick the right branch.
REFERENCE = [
    ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
    ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
    ((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
    ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -1.1848, -84.8006), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -0.9009, -85.5211), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0009), 7.1792),
    ((50.0000, 2.5000, 0.0000), (73.0000, 25.0000, -18.0000), 27.1492),
    ((50.0000, 2.5000, 0.0000), (61.0000, -5.0000, 29.0000), 22.8977),
    ((50.0000, 2.5000, 0.0000), (56.0000, -27.0000, -3.0000), 31.9030),
    ((50.0000, 2.5000, 0.0000), (58.0000, 24.0000, 15.0000), 19.4535),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.1736, 0.5854), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2972, 0.0000), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 1.8634, 0.5757), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2592, 0.3350), 1.0000),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
    ((61.2901, 3.7196, -5.3901), (61.4292, 2.2480, -4.9620), 1.8731),
    ((35.0831, -44.1164, 3.7933), (35.0232, -40.0716, 1.5901), 1.8645),
    ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
]


@pytest.mark.parametrize("lab1,lab2,expected", REFERENCE)
def test_ciede2000_matches_the_published_reference(lab1, lab2, expected):
    assert colordiff.ciede2000(lab1, lab2)[0] == pytest.approx(expected, abs=1e-4)


def test_ciede2000_is_symmetric_in_total_and_signed_in_components():
    a, b = (50.0, 2.5, 0.0), (58.0, 24.0, 15.0)
    fwd, rev = colordiff.ciede2000(a, b), colordiff.ciede2000(b, a)
    assert fwd[0] == pytest.approx(rev[0], abs=1e-9)      # the total is symmetric
    for i in (1, 2, 3):                                   # the components are not
        assert fwd[i] == pytest.approx(-rev[i], abs=1e-9)


def test_identical_colours_have_zero_difference():
    assert colordiff.ciede2000((42.0, -3.0, 7.0), (42.0, -3.0, 7.0)) == (0.0, 0.0, 0.0, 0.0)


def test_rgb_to_lab_anchors():
    """Black, white and mid-grey pin the transfer curve and the white point."""
    assert colordiff.rgb_to_lab((0.0, 0.0, 0.0)) == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)
    L, a, b = colordiff.rgb_to_lab((255.0, 255.0, 255.0))
    assert L == pytest.approx(100.0, abs=1e-4) and abs(a) < 1e-3 and abs(b) < 1e-3
    L, a, b = colordiff.rgb_to_lab((128.0, 128.0, 128.0))
    assert L == pytest.approx(53.585, abs=0.01) and abs(a) < 1e-3 and abs(b) < 1e-3


def test_a_pure_luma_lift_lands_in_dL_only():
    """The component split is the report's whole explanatory value: a grey lift
    must not leak into chroma or hue."""
    _, dL, dC, dH = colordiff.ciede2000(colordiff.rgb_to_lab((100.0, 100.0, 100.0)),
                                        colordiff.rgb_to_lab((128.0, 128.0, 128.0)))
    # 1e-5, not 0: the sRGB->XYZ matrix rows do not sum to the D65 white point in
    # double precision, so a pure grey lands at a* = -8.4e-06 and the lift carries
    # dC = 2.50e-06 through. Measured, not guessed — and still four orders of
    # magnitude under any real chroma leak.
    assert dL > 10.0 and abs(dC) < 1e-5 and abs(dH) < 1e-5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_colordiff.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.colordiff'` (collection error).

- [ ] **Step 3: Write the implementation**

Create `scripts/lib/colordiff.py`:

```python
"""sRGB -> CIE Lab and CIEDE2000 (design docs/specs/2026-08-28-grade-delta-sensors-design.md §2.1).

Colour-difference arithmetic and nothing else: no sampling, no thresholds, no
ffmpeg. `math` only — the caller already has numpy for pixels, but a difference
between two colours is scalar work and adding an array dependency here would
buy nothing.

Why CIEDE2000 and not the hue angle it replaces: a grade moves exposure and
saturation, and hue is invariant to both by construction, so the metric that was
here reported ~0 for every real grade and threw the sample away entirely when
the subject came near grey (design §0.2). dE00 keeps all three components and
weighs a near-grey hue term down through its own S_H rather than by discarding
the sample."""
import math

# sRGB D65 white point, the reference white the Lab transfer is defined against.
_XN, _YN, _ZN = 0.95047, 1.0, 1.08883
_DELTA = 6.0 / 29.0        # the Lab transfer's linear/cubic knee


def _linearize(c: float) -> float:
    """One sRGB channel (0-255) to linear light (0-1)."""
    v = c / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _f(t: float) -> float:
    return t ** (1.0 / 3.0) if t > _DELTA ** 3 else t / (3 * _DELTA ** 2) + 4.0 / 29.0


def rgb_to_lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    """(R, G, B) in 0-255 to (L*, a*, b*). sRGB primaries, D65."""
    r, g, b = (_linearize(v) for v in rgb)
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    fx, fy, fz = _f(x / _XN), _f(y / _YN), _f(z / _ZN)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def ciede2000(lab1: tuple[float, float, float],
              lab2: tuple[float, float, float]) -> tuple[float, float, float, float]:
    """(dE00, dL', dC', dH') between two Lab colours, k_L = k_C = k_H = 1.

    The three components are returned alongside the total because they are the
    report's explanation — which of luma, chroma and hue the grade moved — and
    recomputing them in the caller would duplicate every intermediate below.
    They are SIGNED (lab1 -> lab2); the total is symmetric, the components are not.
    """
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    cbar = (c1 + c2) / 2.0
    # G expands a* near the neutral axis so a small chroma difference there is not
    # swamped; at cbar = 0 the radical is 0 and G is exactly 0.5.
    g = 0.5 * (1.0 - math.sqrt(cbar ** 7 / (cbar ** 7 + 25.0 ** 7))) if cbar > 0 else 0.5
    a1p, a2p = (1.0 + g) * a1, (1.0 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360.0 if (a1p or b1) else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360.0 if (a2p or b2) else 0.0

    dlp = l2 - l1
    dcp = c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180.0:
        dhp = h2p - h1p
    elif h2p - h1p > 180.0:
        dhp = h2p - h1p - 360.0
    else:
        dhp = h2p - h1p + 360.0
    dHp = 2.0 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp) / 2.0)

    lbar, cbarp = (l1 + l2) / 2.0, (c1p + c2p) / 2.0
    if c1p * c2p == 0:
        hbar = h1p + h2p
    elif abs(h1p - h2p) <= 180.0:
        hbar = (h1p + h2p) / 2.0
    elif h1p + h2p < 360.0:
        hbar = (h1p + h2p + 360.0) / 2.0
    else:
        hbar = (h1p + h2p - 360.0) / 2.0

    t = (1.0
         - 0.17 * math.cos(math.radians(hbar - 30.0))
         + 0.24 * math.cos(math.radians(2.0 * hbar))
         + 0.32 * math.cos(math.radians(3.0 * hbar + 6.0))
         - 0.20 * math.cos(math.radians(4.0 * hbar - 63.0)))
    dtheta = 30.0 * math.exp(-(((hbar - 275.0) / 25.0) ** 2))
    rc = 2.0 * math.sqrt(cbarp ** 7 / (cbarp ** 7 + 25.0 ** 7)) if cbarp > 0 else 0.0
    sl = 1.0 + (0.015 * (lbar - 50.0) ** 2) / math.sqrt(20.0 + (lbar - 50.0) ** 2)
    sc = 1.0 + 0.045 * cbarp
    sh = 1.0 + 0.015 * cbarp * t
    rt = -math.sin(math.radians(2.0 * dtheta)) * rc

    de = math.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dHp / sh) ** 2
                   + rt * (dcp / sc) * (dHp / sh))
    return (de, dlp, dcp, dHp)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_colordiff.py -q`
Expected: PASS (25 tests — 21 parametrized reference rows + 4).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/colordiff.py tests/lib/test_colordiff.py
git commit -m "feat: colour-difference arithmetic, pinned to the published reference"
```

---

## Task 1: the metric swap — `color_fidelity`, `CheckSpec`, `check_episode`

The check stays **advisory** (`passed is None`) in this task; Task 3 makes it
blocking. Splitting them keeps the metric change and the governance change on
separate reviewable commits.

**Files:**
- Modify: `scripts/lib/color_fidelity.py` (full rewrite)
- Modify: `scripts/lib/models.py` — `CheckSpec`, around line 961 and 970-973
- Modify: `scripts/check_episode.py` — `_colour_fidelity`, around lines 80-104
- Test: `tests/lib/test_color_fidelity.py` (full rewrite)
- Test: `tests/lib/test_models.py` — `test_checkspec_hue_drift_max`, around line 257
- Test: `tests/integration/test_color_fidelity.py` — the two assertion blocks

**Interfaces:**
- Consumes: `colordiff.rgb_to_lab`, `colordiff.ciede2000` (Task 0).
- Produces:
  - `color_fidelity.sample_deltas(pairs: list[tuple]) -> list[tuple[float, float, float, float]]`
  - `color_fidelity.evaluate(pairs: list[tuple], delta_max: float) -> dict`
  - `CheckSpec.grade_delta_max: float = 5.0`

- [ ] **Step 1: Write the failing tests**

Replace the whole of `tests/lib/test_color_fidelity.py`:

```python
"""The subject grade-delta verdict (design docs/specs/2026-08-28-grade-delta-sensors-design.md §2.3)."""
import pytest

from scripts.lib import color_fidelity as cf


def test_an_identical_pair_is_zero_and_passes():
    d = cf.evaluate([((150.0, 90.0, 60.0), (150.0, 90.0, 60.0))], delta_max=5.0)
    assert d["delta_e"] == 0.0 and d["exceeded"] is False and d["samples"] == 1


def test_a_hue_rotation_exceeds():
    d = cf.evaluate([((150.0, 90.0, 60.0), (60.0, 150.0, 90.0))], delta_max=5.0)
    assert d["exceeded"] is True and d["dominant"] == "hue"


def test_a_luma_lift_exceeds_and_names_luma():
    d = cf.evaluate([((100.0, 100.0, 100.0), (128.0, 128.0, 128.0))], delta_max=5.0)
    assert d["exceeded"] is True and d["dominant"] == "luma" and d["delta_l"] > 10.0


def test_a_desaturation_names_chroma():
    """The component that must NOT be the largest here is luma: pulling a colour
    toward its own mean keeps L* nearly fixed."""
    src = (200.0, 80.0, 40.0)
    m = sum(src) / 3
    d = cf.evaluate([(src, tuple(m + (c - m) * 0.4 for c in src))], delta_max=5.0)
    assert d["dominant"] == "chroma" and d["delta_c"] < 0


def test_a_near_grey_subject_still_gets_a_number():
    """The old grey floor discarded 9 of 24 real samples (design §0.2). A near-grey
    pair must now report a value, and a near-grey pair that barely moved must PASS
    rather than reporting a wild hue swing."""
    d = cf.evaluate([((128.0, 130.0, 129.0), (129.0, 130.0, 128.0))], delta_max=5.0)
    assert "status" not in d
    assert d["delta_e"] < 5.0 and d["exceeded"] is False


def test_the_verdict_is_the_median_not_the_worst():
    """Three samples, one of them wildly off. The median ignores it; a max would not.
    This is the statistic the design measured (§0.4) — a worst-sample rule does not
    separate the shipped grade from the recorded damage."""
    same = ((150.0, 90.0, 60.0), (150.0, 90.0, 60.0))
    wild = ((150.0, 90.0, 60.0), (60.0, 150.0, 90.0))
    d = cf.evaluate([same, same, wild], delta_max=5.0)
    assert d["delta_e"] == 0.0 and d["exceeded"] is False


def test_threshold_is_strict_greater_than():
    """A delta exactly at the bar passes: the bar is the largest acceptable value."""
    pairs = [((100.0, 100.0, 100.0), (128.0, 128.0, 128.0))]
    at = cf.evaluate(pairs, delta_max=1000.0)
    assert at["exceeded"] is False
    exact = cf.evaluate(pairs, delta_max=at["delta_e"])
    assert exact["exceeded"] is False


def test_no_samples_is_not_checked():
    d = cf.evaluate([], delta_max=5.0)
    assert d["status"] == "not-checked" and "no samples" in d["reason"]


def test_sample_deltas_is_one_row_per_pair():
    rows = cf.sample_deltas([((10.0, 20.0, 30.0), (11.0, 21.0, 31.0)),
                             ((10.0, 20.0, 30.0), (90.0, 20.0, 30.0))])
    assert len(rows) == 2 and all(len(r) == 4 for r in rows)
    assert rows[1][0] > rows[0][0]


def test_the_old_hue_api_is_gone():
    """The grey floor and the hue angle are deleted, not deprecated — a caller still
    reaching for them must break loudly rather than get a silently different answer."""
    assert not hasattr(cf, "hue")
    assert not hasattr(cf, "hue_drift")
    assert not hasattr(cf, "GREY_EPS")
```

In `tests/lib/test_models.py`, replace `test_checkspec_hue_drift_max` with:

```python
def test_checkspec_grade_delta_max():
    assert m.CheckSpec(composition="center", grid="thirds", target_dur=3.0).grade_delta_max == 5.0
    with pytest.raises(ValueError, match="positive dE00 ceiling"):
        m.CheckSpec(composition="center", grid="thirds", target_dur=3.0, grade_delta_max=-1)
    with pytest.raises(ValueError, match="positive dE00 ceiling"):
        m.CheckSpec(composition="center", grid="thirds", target_dur=3.0, grade_delta_max=True)  # bool-reject
    assert not hasattr(m.CheckSpec(composition="center", grid="thirds", target_dur=3.0),
                       "hue_drift_max")
```

(`m` is `scripts.lib.models`, already imported at the top of that file; the old
test's local `from scripts.lib.models import CheckSpec` goes with it.)

In `tests/integration/test_color_fidelity.py`, update the two assertion blocks
only — the fixtures and `_sidecar` stay exactly as they are:

```python
def test_faithful_grade_does_not_exceed(tmp_path, source_clip, faithful_clip):
    rp, pp = _sidecar(tmp_path)
    spec = CheckSpec(composition="center", grid="thirds", target_dur=DUR)
    report = check_episode.run(str(faithful_clip), rp, pp, spec,
                               str(tmp_path / "report.json"), source=str(source_clip))
    cf = report.checks["color_fidelity"]
    assert cf.passed is None                     # still advisory in this task
    assert cf.detail.get("status") != "not-checked", cf.detail
    assert cf.detail["exceeded"] is False
    assert cf.detail["delta_e"] < 5.0
    assert report.overall is True


def test_hue_broken_grade_is_flagged(tmp_path, source_clip, broken_clip):
    rp, pp = _sidecar(tmp_path)
    spec = CheckSpec(composition="center", grid="thirds", target_dur=DUR)
    report = check_episode.run(str(broken_clip), rp, pp, spec,
                               str(tmp_path / "report.json"), source=str(source_clip))
    cf = report.checks["color_fidelity"]
    assert cf.passed is None                     # Task 3 flips this
    assert cf.detail["exceeded"] is True
    assert cf.detail["delta_e"] > 20.0           # hue=h=120 on a saturated orange
    assert cf.detail["dominant"] == "hue"
    assert report.overall is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_color_fidelity.py tests/lib/test_models.py::test_checkspec_grade_delta_max -q`
Expected: FAIL — `AttributeError: module 'scripts.lib.color_fidelity' has no attribute 'evaluate'` with the new signature / `TypeError: CheckSpec.__init__() got an unexpected keyword argument 'grade_delta_max'`.

- [ ] **Step 3: Rewrite `scripts/lib/color_fidelity.py`**

Replace the file entirely:

```python
"""Subject grade-delta (design docs/specs/2026-08-28-grade-delta-sensors-design.md §2.3):
how far the grade moved the tracked subject's colour, source vs delivered.

Pure — the sampling lives in check_episode, the arithmetic in colordiff. What
this module owns is the verdict: which statistic over the samples, and what the
numbers are called in the report.

This replaces a hue-angle metric that could not see its own subject. Hue is
invariant to exposure and saturation, which is what a grade moves, and the
metric additionally discarded any sample whose chroma fell under a fixed floor —
on the reference run that was 9 of 24 samples, including one where the grade
HALVED the subject's chroma and one where it quadrupled it (design §0.2)."""
import statistics

from scripts.lib import colordiff

# Report names for the three signed components, in ciede2000's own order.
_COMPONENTS = ("luma", "chroma", "hue")


def sample_deltas(pairs: list[tuple]) -> list[tuple[float, float, float, float]]:
    """One (dE00, dL*, dC*, dH*) row per (source_rgb, graded_rgb) pair."""
    return [colordiff.ciede2000(colordiff.rgb_to_lab(src), colordiff.rgb_to_lab(graded))
            for src, graded in pairs]


def evaluate(pairs: list[tuple], delta_max: float) -> dict:
    """The episode's verdict: the MEDIAN of its samples against `delta_max`.

    Median, not worst: measured over the reference run and the damage magnitudes
    its retro recorded, the per-episode median separates (healthy 0.89-4.29,
    damage from 5.04) while the worst sample does not — a single near-grey sample
    swings far under any grade (design §0.4).

    The three components are reported but do not vote. They are the explanation:
    `dominant` names whichever moved most, so a report reads as "the grade lifted
    exposure" rather than "the colour changed by 6"."""
    if not pairs:
        return {"status": "not-checked", "reason": "no samples to compare"}
    rows = sample_deltas(pairs)
    comps = tuple(statistics.median(r[i] for r in rows) for i in (1, 2, 3))
    dominant = _COMPONENTS[max(range(3), key=lambda i: abs(comps[i]))]
    # Round once, then judge the ROUNDED value against delta_max — not the raw
    # median. `exceeded` must agree with the `delta_e` the report actually shows;
    # comparing the unrounded median instead can flag a report that reads
    # "delta_e: 11.07, threshold: 11.07, exceeded: true", which is a
    # contradiction no reader can act on.
    de = round(statistics.median(r[0] for r in rows), 2)
    return {"delta_e": de,
            "delta_l": round(comps[0], 2),
            "delta_c": round(comps[1], 2),
            "delta_h": round(comps[2], 2),
            "threshold": delta_max,
            "samples": len(rows),
            "dominant": dominant,
            "exceeded": de > delta_max}
```

- [ ] **Step 4: Rename the `CheckSpec` field**

In `scripts/lib/models.py`, in `CheckSpec`, replace the `hue_drift_max` field
and its validation:

```python
    # The largest median subject dE00 (source vs delivered) an episode may carry.
    # 5.0 is measured, not chosen: on the reference run the eight shipped episodes
    # reach 4.29 and the retro's own recorded damage magnitudes start at 5.04
    # (design 2026-08-28 §0.4/§2.4).
    grade_delta_max: float = 5.0
```

```python
        if (isinstance(self.grade_delta_max, bool)
                or not isinstance(self.grade_delta_max, (int, float))
                or self.grade_delta_max <= 0):
            raise ValueError(f"CheckSpec.grade_delta_max must be a positive dE00 ceiling, "
                             f"got {self.grade_delta_max!r}")
```

- [ ] **Step 5: Point `check_episode` at the new evaluate**

In `scripts/check_episode.py`, change the last two lines of `_colour_fidelity`
(the sampling itself is Task 2's job — this task changes only the call):

```python
    return CheckResult("color_fidelity", None,
                       color_fidelity.evaluate(pairs, spec.grade_delta_max))
```

and update that function's docstring's last sentence to:

```
    to the pure color_fidelity.evaluate for the median-dE00 verdict. `passed` is
    always None for now — Task 3 of the grade-delta slice makes it blocking.
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_color_fidelity.py tests/lib/test_colordiff.py tests/lib/test_models.py -q`
Expected: PASS.

Run: `.venv/bin/python -m pytest tests/integration/test_color_fidelity.py -q`
Expected: PASS (3 tests).

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/python -m pytest -q -x`
Expected: PASS. If anything else referenced `hue_drift_max` or the deleted hue
API, it fails here — fix the reference; do not reintroduce the old names.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/color_fidelity.py scripts/lib/models.py scripts/check_episode.py tests/
git commit -m "feat: the subject verdict becomes a median dE00, not a hue angle"
```

---

## Task 2: batched five-point sampling

**Files:**
- Modify: `scripts/check_episode.py` — delete `_region_mean_rgb`, add
  `_box_mean_rgb` and `SAMPLE_FRACS`, rewrite `_colour_fidelity`'s body
- Test: `tests/integration/test_color_fidelity.py` — replace
  `test_region_mean_rgb_reads_the_synthesized_colour`

**Interfaces:**
- Consumes: `assembly.frames_rgb(src, times, fps)`, `assembly.probe_stream`,
  `assembly.probe_duration`, `color_fidelity.evaluate` (Task 1).
- Produces: `check_episode.SAMPLE_FRACS = (0.1, 0.3, 0.5, 0.7, 0.9)` and
  `check_episode._box_mean_rgb(frame, box) -> tuple[float, float, float]`.

- [ ] **Step 1: Write the failing test**

In `tests/integration/test_color_fidelity.py`, replace
`test_region_mean_rgb_reads_the_synthesized_colour` with:

```python
def test_box_mean_rgb_reads_the_synthesized_colour(source_clip):
    """One decode, five frames, box means — the production sampling path.
    SUBJECT_COLOR 0xC85028 = (200, 80, 40); sampled well inside the box."""
    fps = assembly.probe_stream(str(source_clip)).fps
    frames = assembly.frames_rgb(str(source_clip), [0.5, 1.0, 1.5], fps)
    assert len(frames) == 3
    r, g, b = check_episode._box_mean_rgb(frames[1], (240, 120, 400, 240))
    assert abs(r - 200) < 15 and abs(g - 80) < 15 and abs(b - 40) < 15


def test_the_check_takes_five_samples(tmp_path, source_clip, faithful_clip):
    """The sample count is the statistic's own denominator — the median of five is
    what the design's thresholds were measured on (§0.4/§2.2)."""
    rp, pp = _sidecar(tmp_path)
    spec = CheckSpec(composition="center", grid="thirds", target_dur=DUR)
    report = check_episode.run(str(faithful_clip), rp, pp, spec,
                               str(tmp_path / "report.json"), source=str(source_clip))
    assert report.checks["color_fidelity"].detail["samples"] == 5


def test_sampling_survives_a_route_that_reaches_the_last_frame(tmp_path, source_clip,
                                                               faithful_clip):
    """frames_rgb raises past the stream end; a route whose last point sits at the
    clip's duration must be clamped, not crash. Without the clamp this raises
    RuntimeError from frames_rgb."""
    n = 5
    route = [dict(t=round(i * DUR / (n - 1), 3), x=SUBJECT_X, y=SUBJECT_Y,
                  w=SUBJECT_W, h=SUBJECT_H) for i in range(n)]
    (tmp_path / "route.json").write_text(json.dumps(route))
    (tmp_path / "path.json").write_text(json.dumps([CROP_X] * n))
    PathMeta(mode="fill", crop_w=CROP_W, crop_h=H, crop_y=0, src_dims=(W, H),
             canvas=(CROP_W, H), out_dims=(CROP_W, H), rect_px=(0, 0, CROP_W, H),
             freedom=W - CROP_W).write(tmp_path / "path.meta.json")
    spec = CheckSpec(composition="center", grid="thirds", target_dur=DUR)
    report = check_episode.run(str(faithful_clip), str(tmp_path / "route.json"),
                               str(tmp_path / "path.json"), spec,
                               str(tmp_path / "report.json"), source=str(source_clip))
    assert report.checks["color_fidelity"].detail["samples"] == 5
```

Add `assembly` to that file's imports:

```python
from scripts.lib import assembly, ffbin, proc
```

and drop the now-dead `from scripts.check_episode import _region_mean_rgb`.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_color_fidelity.py -q`
Expected: FAIL — `AttributeError: module 'scripts.check_episode' has no attribute '_box_mean_rgb'`.

- [ ] **Step 3: Implement**

In `scripts/check_episode.py`, add `import numpy as np` to the imports and
`assembly` to the `scripts.lib` import list. Delete `_region_mean_rgb` entirely
(`tempfile`, `Image` and `ImageStat` stay — `_frame_lumas` still uses all three).
Add, above `_colour_fidelity`:

```python
# Where in the route's own span the subject is sampled. Five, not three: the
# batched decode below makes the marginal cost of a sample one PNG, and every
# threshold in the design was measured through exactly these fractions (§2.2).
SAMPLE_FRACS = (0.1, 0.3, 0.5, 0.7, 0.9)


def _box_mean_rgb(frame: np.ndarray, box: tuple[int, int, int, int]) -> tuple[float, float, float]:
    """Mean (R, G, B) of a pixel box in one HxWx3 uint8 RGB frame. box = (x0,y0,x1,y1),
    clamped into the frame and never empty — a route point can sit partly outside the
    frame it was measured on, and an empty slice would mean() to NaN in silence."""
    x0, y0, x1, y1 = box
    h, w = frame.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, max(x1, x0 + 1)), min(h, max(y1, y0 + 1))
    px = frame[y0:y1, x0:x1].reshape(-1, 3)
    return tuple(float(px[:, c].mean()) for c in range(3))


def _last_sampleable_t(*clips: str) -> tuple[list[float], float]:
    """Per-clip fps, and the latest time every one of `clips` can still decode.
    frames_rgb selects frame round(t*fps) and raises when that frame is past the
    stream end, so the times are clamped ONCE against the shortest clip, before the
    geometry is projected — clamping afterwards would sample the pixels at one time
    and the crop rect at another."""
    fpses, lasts = [], []
    for c in clips:
        fps = assembly.probe_stream(c).fps
        fpses.append(fps)
        lasts.append(max(0.0, assembly.probe_duration(c) - 1.0 / fps))
    return fpses, min(lasts)
```

Replace `_colour_fidelity`'s body (keep the early-return arm unchanged):

```python
def _colour_fidelity(clip: str, source: str | None, route_pts: list[RoutePoint] | None,
                     path_obj: CropPath, meta: PathMeta, spec: CheckSpec) -> CheckResult:
    """Advisory subject grade-delta, source vs graded (design 2026-08-28 §2).

    Sample the tracked subject's mean RGB in the SOURCE (pre-grade segment, at the
    route bbox in source px) and in the graded `clip` (at the subject's projected
    location, via geometry.extent_at_times) at SAMPLE_FRACS of the route's span, and
    delegate to the pure color_fidelity.evaluate for the median-dE00 verdict.

    One decode per file, not one per sample: assembly.frames_rgb batches the whole
    set through a single select pass, so five samples cost two decodes where three
    used to cost six. `passed` is always None for now — Task 3 makes it blocking.
    """
    if source is None or not route_pts:
        return CheckResult("color_fidelity", None,
                           {"status": "not-checked",
                            "reason": "no source clip or no tracked subject"})
    ts = [p.t for p in route_pts]
    (s_fps, g_fps), last = _last_sampleable_t(source, clip)
    times = [min(ts[0] + (ts[-1] - ts[0]) * f, last) for f in SAMPLE_FRACS]
    extents = geometry.extent_at_times(route_pts, path_obj, meta, times)   # output fractions
    out_w, out_h = meta.out_dims
    s_frames = assembly.frames_rgb(source, times, s_fps)
    g_frames = assembly.frames_rgb(clip, times, g_fps)
    pairs = []
    for t, (fx0, fy0, fx1, fy1), sf, gf in zip(times, extents, s_frames, g_frames):
        p = min(route_pts, key=lambda q: abs(q.t - t))          # nearest source bbox
        sbox = (round(p.x - p.w / 2), round(p.y - p.h / 2),
                round(p.x + p.w / 2), round(p.y + p.h / 2))
        gbox = (round(fx0 * out_w), round(fy0 * out_h), round(fx1 * out_w), round(fy1 * out_h))
        pairs.append((_box_mean_rgb(sf, sbox), _box_mean_rgb(gf, gbox)))
    return CheckResult("color_fidelity", None,
                       color_fidelity.evaluate(pairs, spec.grade_delta_max))
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/integration/test_color_fidelity.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. `tests/integration/test_process_episode.py` and
`tests/integration/test_check_episode.py` both drive this path; if either moved,
read the failure before touching it — a changed sample count is expected, a
changed verdict is not.

- [ ] **Step 6: Commit**

```bash
git add scripts/check_episode.py tests/integration/test_color_fidelity.py
git commit -m "perf: one decode per file for the colour samples, and five of them"
```

---

## Task 3: the check becomes blocking, and the ladder learns it cannot fix it

**Files:**
- Modify: `scripts/check_episode.py` — the return of `_colour_fidelity`
- Modify: `scripts/lib/orchestration.py:147` `_UNFIXABLE`, and `escalation`
  around lines 207-221
- Test: `tests/lib/test_orchestration.py`
- Test: `tests/integration/test_color_fidelity.py` — the two verdict assertions

**Interfaces:**
- Consumes: `color_fidelity.evaluate`'s `exceeded` key (Task 1).
- Produces: `orchestration._UNFIXABLE` gains `"color_fidelity"`;
  `escalation(...)["reason"]` is `"grade-damage"` for a colour failure.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_orchestration.py`:

```python
def test_a_colour_failure_escalates_immediately_with_its_own_reason():
    """Reframe params are geometry knobs; no value of max_speed or smooth_window_s
    moves a colour. Without this the episode is re-rendered at full resolution three
    times before escalating, and then escalates naming only what cannot fix it."""
    esc = orchestration.escalation(attempt=1, fail_reasons=["color_fidelity"])
    assert esc is not None
    assert esc["reason"] == "grade-damage"
    assert esc["escalate_to"] == "edit-plan"


def test_an_upstream_failure_still_outranks_the_colour_reason():
    """A segment that is the wrong length is the more upstream fault; reporting
    'grade-damage' there would send the author to the colour block for a problem
    the colour block cannot fix. The order of _UNFIXABLE decides, not the order the
    checks happened to run in."""
    esc = orchestration.escalation(attempt=1, fail_reasons=["color_fidelity", "length"])
    assert esc["reason"] == "unfixable-by-reframe"


def test_colour_is_listed_as_unfixable():
    assert "color_fidelity" in orchestration._UNFIXABLE
```

(Use whatever import alias the file already has for the module.)

In `tests/integration/test_color_fidelity.py`, change the two verdict
assertions:

```python
    cf = report.checks["color_fidelity"]
    assert cf.passed is True                     # blocking, and this grade is clean
    assert cf.detail.get("status") != "not-checked", cf.detail
    assert cf.detail["exceeded"] is False
    assert cf.detail["delta_e"] < 5.0
    assert report.overall is True
```

```python
    cf = report.checks["color_fidelity"]
    assert cf.passed is False                    # a damaged grade now stops the episode
    assert cf.detail["exceeded"] is True
    assert cf.detail["delta_e"] > 20.0
    assert cf.detail["dominant"] == "hue"
    assert report.overall is False
    assert "color_fidelity" in report.fail_reasons
```

Rename that second test to `test_hue_broken_grade_fails_the_episode`.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_orchestration.py -q -k colour`
Expected: FAIL — `assert None is not None` (escalation returns None at attempt 1).

- [ ] **Step 3: Implement the orchestration change**

In `scripts/lib/orchestration.py`, replace the `_UNFIXABLE` line:

```python
# reframe can't fix these by re-cropping — the fault is upstream (window/segment),
# or, for color_fidelity, in the episode's colour block: max_speed and
# smooth_window_s are geometry knobs and no value of either moves a colour, so
# without this entry the ladder re-renders 4K three times before giving up
# (design 2026-08-28 §3). Order matters — see _UNFIXABLE_REASON.
_UNFIXABLE = ("length", "continuity", "black_frames", "color_fidelity")

# The escalation reason for a specific unfixable failure, where the generic one
# would name only what CANNOT fix the problem. The first entry of _UNFIXABLE
# present in fail_reasons wins, so an upstream fault outranks a colour one.
_UNFIXABLE_REASON = {"color_fidelity": "grade-damage"}
```

and replace the first arm of `escalation`:

```python
    hit = next((r for r in _UNFIXABLE if r in fail_reasons), None)
    if hit:
        return {"escalate_to": "edit-plan",
                "reason": _UNFIXABLE_REASON.get(hit, "unfixable-by-reframe"),
                "fail_reasons": fail_reasons}
```

Extend the docstring's second paragraph:

```
    Escalate immediately when the failure can't be fixed by reframe params
    (unfixable reasons, or a line-lag + jitter combo which pull speed in
    opposite directions); otherwise after max_attempts (§4.1: 3× → up). An
    unfixable reason with an entry in _UNFIXABLE_REASON reports that instead of
    the generic "unfixable-by-reframe", which names only what cannot help.
```

- [ ] **Step 4: Make the check blocking**

In `scripts/check_episode.py`, replace `_colour_fidelity`'s final return:

```python
    d = color_fidelity.evaluate(pairs, spec.grade_delta_max)
    return CheckResult("color_fidelity", not d["exceeded"], d)
```

and change the docstring's last sentence to:

```
    `passed` is False when the median dE00 exceeds CheckSpec.grade_delta_max —
    the episode stops and escalates to edit-plan as `grade-damage`, because the
    remedy is its colour block and no reframe parameter can reach it.
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_orchestration.py tests/integration/test_color_fidelity.py -q`
Expected: PASS.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

This was de-risked before the plan was written: `sample_clip` rendered through
`reframe` with the standard `color_means=(105, 122, 137)` spec — the recipe
`tests/integration/test_episode_qc.py` uses — measures a **median dE00 of 0.96**
against the bar of 5.0. So the ordinary fixture render is nowhere near the gate,
and a suite that goes red here is reporting something real.

If a test does fail, read it rather than relaxing the threshold. Two different
things can have happened, and they have opposite remedies: a fixture whose
synthetic "grade" genuinely moves the subject past 5.0 dE00 should be updated to
expect the stop — that is the feature working — while an ordinary render
tripping the bar means the bug is in this task's code, not in the test.

- [ ] **Step 7: Commit**

```bash
git add scripts/check_episode.py scripts/lib/orchestration.py tests/
git commit -m "feat: a damaged grade stops the episode, and escalates as grade-damage"
```

---

## Task 4: `naturalness` — two absolute flags, three source-relative ones

**Files:**
- Modify: `scripts/lib/naturalness.py` — constants block and both evaluate paths
- Test: `tests/lib/test_naturalness.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `naturalness.evaluate(stats) -> dict` with exactly the keys
  `blown_highlights`, `crushed_blacks`; and
  `naturalness.evaluate_delta(src: dict, grd: dict) -> dict` with exactly
  `cast_shift`, `saturation_shift`, `contrast_drop`. Constants
  `CAST_DELTA_MAX = 0.08`, `SAT_DELTA_MAX = 0.12`, `CONTRAST_DROP_MAX = 20.0`.

- [ ] **Step 1: Write the failing tests**

In `tests/lib/test_naturalness.py`, delete
`test_a_red_frame_reads_as_a_cast_and_oversaturated` and
`test_a_single_tone_frame_reads_flat_and_a_full_ramp_does_not`, change
`test_a_neutral_mid_grey_frame_reads_clean` to assert only the two surviving
flags, and add:

```python
def test_evaluate_reports_only_the_two_absolute_flags():
    """A cast, a flat frame and a saturated one are properties of the FOOTAGE, not of
    the grade: on the reference run 6 of 8 SOURCES already exceeded the old CAST_MAX
    before any grade ran (design §0.5). Only destroyed information stays absolute."""
    flags = naturalness.evaluate(naturalness.measure([_flat(220, 40, 40)]))
    assert set(flags) == {"blown_highlights", "crushed_blacks"}


def _stats(cast, saturation, contrast):
    return {"cast": cast, "saturation": saturation, "contrast": contrast}


def test_a_grade_that_changed_nothing_raises_no_delta_flag():
    d = naturalness.evaluate_delta(_stats(0.30, 0.45, 100.0), _stats(0.30, 0.45, 100.0))
    assert d == {"cast_shift": False, "saturation_shift": False, "contrast_drop": False}


def test_a_strong_source_cast_alone_raises_nothing():
    """0.30 is four times the old absolute bar and is simply what a seascape looks
    like. The grade left it where it was, so nothing fires."""
    d = naturalness.evaluate_delta(_stats(0.30, 0.45, 100.0), _stats(0.32, 0.45, 100.0))
    assert d["cast_shift"] is False


def test_cast_shift_is_two_sided_and_bars_at_the_measured_value():
    hi = naturalness.evaluate_delta(_stats(0.10, 0.30, 100.0), _stats(0.19, 0.30, 100.0))
    lo = naturalness.evaluate_delta(_stats(0.19, 0.30, 100.0), _stats(0.10, 0.30, 100.0))
    assert hi["cast_shift"] is True and lo["cast_shift"] is True
    near = naturalness.evaluate_delta(_stats(0.10, 0.30, 100.0), _stats(0.177, 0.30, 100.0))
    assert near["cast_shift"] is False           # 0.077 — the shipped run's own maximum
    assert naturalness.CAST_DELTA_MAX == 0.08


def test_saturation_shift_is_two_sided_and_catches_a_desaturation():
    assert naturalness.SAT_DELTA_MAX == 0.12
    lost = naturalness.evaluate_delta(_stats(0.10, 0.40, 100.0), _stats(0.10, 0.24, 100.0))
    gained = naturalness.evaluate_delta(_stats(0.10, 0.24, 100.0), _stats(0.10, 0.40, 100.0))
    assert lost["saturation_shift"] is True and gained["saturation_shift"] is True
    ok = naturalness.evaluate_delta(_stats(0.10, 0.40, 100.0), _stats(0.10, 0.297, 100.0))
    assert ok["saturation_shift"] is False       # 0.103 — the shipped run's own maximum


def test_contrast_drop_is_signed_because_a_gain_is_not_a_defect():
    """The reference run's ep6 GAINED 24.5 of luma spread legitimately; testing the
    magnitude would flag it. Only a loss counts."""
    assert naturalness.CONTRAST_DROP_MAX == 20.0
    lost = naturalness.evaluate_delta(_stats(0.1, 0.3, 120.0), _stats(0.1, 0.3, 90.0))
    gained = naturalness.evaluate_delta(_stats(0.1, 0.3, 90.0), _stats(0.1, 0.3, 120.0))
    assert lost["contrast_drop"] is True
    assert gained["contrast_drop"] is False
    near = naturalness.evaluate_delta(_stats(0.1, 0.3, 120.0), _stats(0.1, 0.3, 103.4))
    assert near["contrast_drop"] is False        # 16.6 — the shipped run's own maximum


def test_the_absolute_style_bars_are_gone():
    """Deleted, not lowered: each measured either the scene rather than the grade, or
    sat where its own footage could never reach (design §0.5)."""
    for name in ("CAST_MAX", "SAT_MAX", "FLAT_SPREAD"):
        assert not hasattr(naturalness, name)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_naturalness.py -q`
Expected: FAIL — `AttributeError: module 'scripts.lib.naturalness' has no attribute 'evaluate_delta'`.

- [ ] **Step 3: Implement**

In `scripts/lib/naturalness.py`, replace the constants block:

```python
# Absolute bars, for destroyed information only. A blown sky is blown whatever the
# source held, so these two do not need a source to compare against. Still first
# cuts: BLOWN_FRAC fired once on the reference run and plausibly; CRUSHED_FRAC never
# fired on footage that never crushed.
CLIP_HIGH = 250       # a channel value at/above this counts as "at white"
CLIP_LOW = 5          # ...and at/below this as "at black"
BLOWN_FRAC = 0.02     # >2% of pixels at white in ANY channel → blown_highlights
CRUSHED_FRAC = 0.05   # >5% at black → crushed_blacks (shadows legitimately cover more area)

# Source-relative bars (design docs/specs/2026-08-28-grade-delta-sensors-design.md §4).
# The absolute versions of these three were DELETED, not retuned: CAST_MAX read the
# ocean (6 of 8 SOURCES exceeded it before any grade), and SAT_MAX/FLAT_SPREAD sat at
# 0.60 and 40.0 against footage measuring 0.11-0.50 and 86-189 — unreachable. Each bar
# below is set where the reference run's OWN source-to-graded range stops, so nothing
# the shipped grade did would fire it.
CAST_DELTA_MAX = 0.08        # |Δ grey-world deviation|; run's max was 0.0766
SAT_DELTA_MAX = 0.12         # |Δ mean relative saturation|; run's range −0.1026…+0.0316
CONTRAST_DROP_MAX = 20.0     # LOSS of p95−p5 luma only; run's worst loss was 16.61
```

Replace `evaluate` and add `evaluate_delta`:

```python
def evaluate(stats: dict) -> dict:
    """The absolute flags: information the grade destroyed. Never a pass/fail — the
    judge weighs them against the episode's intent (a deliberately crushed night shot
    is not a defect)."""
    return {"blown_highlights": max(stats["clip_high"]) > BLOWN_FRAC,
            "crushed_blacks": max(stats["clip_low"]) > CRUSHED_FRAC}


def evaluate_delta(src: dict, grd: dict) -> dict:
    """What the grade DID: `src` and `grd` are two `measure` readings, pre- and
    post-grade. Advisory in both directions.

    `contrast_drop` is signed and the other two are not: a gain in luma spread is not
    a defect (the reference run's ep6 gained 24.5 legitimately), while a cast or a
    saturation move is worth reporting whichever way it went."""
    return {"cast_shift": abs(grd["cast"] - src["cast"]) > CAST_DELTA_MAX,
            "saturation_shift": abs(grd["saturation"] - src["saturation"]) > SAT_DELTA_MAX,
            "contrast_drop": (src["contrast"] - grd["contrast"]) > CONTRAST_DROP_MAX}
```

Update the module docstring's second paragraph to name the split:

```
check_episode's color_fidelity answers "how far did the grade move the SUBJECT's
colour" and says nothing about the frame around it. This measures the frame: two
absolute flags for information the grade destroyed (blown highlights, crushed
blacks) and three source-relative ones for what it changed (cast, saturation,
contrast), so the QC judge argues from numbers instead of impressions.
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_naturalness.py -q`
Expected: PASS.

- [ ] **Step 5: Fix the other readers**

`scripts/probe.py` calls `naturalness.evaluate(stats)` and needs no change — the
signature is unchanged and it has no pre-grade side to compare against.

One known caller asserts on the deleted flags. In
`tests/integration/test_episode_qc.py`, inside
`test_pack_gives_the_judge_pixels_and_numbers`, replace:

```python
    assert set(ev["naturalness"]["flags"]) == {"blown_highlights", "crushed_blacks",
                                               "colour_cast", "oversaturated", "flat"}
```

with:

```python
    assert set(ev["naturalness"]["flags"]) == {"blown_highlights", "crushed_blacks"}
```

Then run: `.venv/bin/python -m pytest -q`

Expected: PASS. Any other test that asserted on the three deleted flags fails
here; delete those assertions rather than reinstating the flags.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/naturalness.py tests/
git commit -m "feat: the frame sensor measures the grade, not the footage"
```

---

## Task 5: the evidence packet carries both readings

**Files:**
- Modify: `scripts/episode_qc.py` — `pack`, around lines 66-88
- Test: `tests/integration/test_episode_qc.py`

**Interfaces:**
- Consumes: `naturalness.measure`, `naturalness.evaluate`,
  `naturalness.evaluate_delta` (Task 4).
- Produces: each `evidence.json`'s `naturalness` object gains `source` (a
  `measure` reading or `None`) and `delta` (an `evaluate_delta` result or
  `None`).

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_episode_qc.py` (reusing whatever fixture that
file already uses to build a manifest — the assertions below are what matters):

Both use the file's existing `_episodes_json` helper, whose `_episode` already
puts `"segment": str(sample_clip)` in each manifest — a real pre-grade file
distinct from the reframed `ep.clip`.

```python
@pytest.mark.integration
def test_the_evidence_packet_carries_the_pre_grade_reading(tmp_path, sample_clip):
    """R2.5: the judge must be able to see what the GRADE did, not only what the
    footage is. The segment has always been in the manifest and was never read."""
    p, _ = _episodes_json(tmp_path, sample_clip)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    nat = json.loads((tmp_path / "qc" / "ep0" / "evidence.json").read_text())["naturalness"]
    assert set(nat) == {"stats", "flags", "source", "delta"}
    assert nat["source"]["frames"] == episode_qc.SENSOR_FRAMES
    assert set(nat["delta"]) == {"cast_shift", "saturation_shift", "contrast_drop"}


@pytest.mark.integration
def test_a_manifest_with_no_segment_reports_absent_not_empty(tmp_path, sample_clip):
    """Absent is reported as absent, never as a clean reading — the same rule the rest
    of _evidence already applies to the sidecars."""
    p, rm = _episodes_json(tmp_path, sample_clip)
    for ep in rm.episodes:
        ep.manifest.pop("segment")
    rm.write(p)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    nat = json.loads((tmp_path / "qc" / "ep0" / "evidence.json").read_text())["naturalness"]
    assert nat["source"] is None and nat["delta"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_episode_qc.py -q -k evidence_packet`
Expected: FAIL — `AssertionError` on the key set (`source`/`delta` missing).

- [ ] **Step 3: Implement**

In `scripts/episode_qc.py`, add `from pathlib import Path` if it is not already
imported (it is), and replace the body of `pack`'s per-episode loop between the
strip build and the `write_text`:

```python
        times = [dur * (k + 0.5) / SENSOR_FRAMES for k in range(SENSOR_FRAMES)]
        stats = naturalness.measure(assembly.frames_rgb(ep.clip, times, info.fps))
        clip_stats = {"stats": stats, "flags": naturalness.evaluate(stats),
                      **_source_reading(ep, stats)}
        (d / "evidence.json").write_text(json.dumps(_evidence(ep, i, clip_stats), indent=2))
```

and add above `pack`:

```python
def _source_reading(ep, graded: dict) -> dict:
    """The pre-grade segment's own naturalness, and the delta against the delivered
    clip. The segment has always been in the manifest and was never read, so the judge
    was shown what the FOOTAGE is and asked about what the GRADE did (design §5).

    A manifest with no segment on disk reports both as None — absent is reported as
    absent, never as a clean reading, the same rule the rest of _evidence applies to
    the sidecars."""
    seg = ep.manifest.get("segment")
    if not seg or not Path(seg).exists():
        return {"source": None, "delta": None}
    info = assembly.probe_stream(seg)
    dur = assembly.probe_duration(seg)
    times = [dur * (k + 0.5) / SENSOR_FRAMES for k in range(SENSOR_FRAMES)]
    src = naturalness.measure(assembly.frames_rgb(seg, times, info.fps))
    return {"source": src, "delta": naturalness.evaluate_delta(src, graded)}
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/integration/test_episode_qc.py -q`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/episode_qc.py tests/integration/test_episode_qc.py
git commit -m "feat: the QC judge sees the pre-grade reading it was always owed"
```

---

## Task 6: skills, docs and the version bump

**Files:**
- Modify: `skills/episode-qc/SKILL.md`, `skills/episode-qc/episode-reviewer.md`
- Modify: `CLAUDE.md` — two new Quick Reference rows
- Modify: `docs/build-status.md`, `docs/backlog.md`
- Modify: `CHANGELOG.md`, `.claude-plugin/plugin.json`

- [ ] **Step 1: Update the judge's two skill files**

In `skills/episode-qc/SKILL.md` and `skills/episode-qc/episode-reviewer.md`,
find every mention of the naturalness flags and replace the five-flag list with
the new shape. The judge must be told, in its own words:

- `naturalness.flags` now carries only `blown_highlights` and `crushed_blacks`
  — information the grade destroyed, true regardless of the source.
- `naturalness.delta` carries `cast_shift`, `saturation_shift` and
  `contrast_drop` — what the grade **changed**, measured against the pre-grade
  segment. `naturalness.source` is that segment's own reading.
- A strong cast, a flat frame or a saturated one in `naturalness.stats` alone is
  a fact about the footage, not a defect. Only the `delta` flags say the grade
  did something.
- The `colour` axis's mechanical companion is now `report.json`'s
  `color_fidelity`, which reports `delta_e` plus `dominant`
  (`luma`/`chroma`/`hue`) — and which now **stops** the episode above its
  threshold, so an episode that reached the judge passed it.

- [ ] **Step 2: Add the Quick Reference rows**

In `CLAUDE.md`, add two rows to the Quick Reference table, next to the other
colour rows:

```markdown
| Grade-damage sensors design | [2026-08-28-grade-delta-sensors-design.md](docs/specs/2026-08-28-grade-delta-sensors-design.md) | R2.2+R2.5: `color_fidelity` swaps a hue angle for a **median CIEDE2000** over five batched samples and becomes **blocking** (`CheckSpec.grade_delta_max = 5.0`, escalating as `grade-damage` because no reframe knob moves a colour); `naturalness` keeps only its two absolute clipping flags and gains source-relative `evaluate_delta`. **§0 is the load-bearing half:** the row's own numbers came from a **stale artifact set** (shipped readings were 1.2–13.4°, not 175°), the grey floor discarded **9 of 24** real samples including a halved and a quadrupled chroma, and 6 of 8 **sources** already exceeded `CAST_MAX` before any grade. §0.6: there is **no clean negative class** for "washed out" — the shipped reel IS the complaint — which is why two of the three frame deltas stay advisory. |
| Grade-damage sensors plan | [2026-08-28-grade-delta-sensors.md](docs/plans/2026-08-28-grade-delta-sensors.md) | Tasks 0–7: `lib/colordiff.py` pinned to 21 published CIEDE2000 pairs, the `color_fidelity` rewrite + `CheckSpec` rename, batched five-point sampling (two decodes per episode where three samples cost six), the blocking flip + `_UNFIXABLE`/`_UNFIXABLE_REASON`, `naturalness`'s two-and-three split, the QC evidence packet's `source`/`delta`, docs, and a 14-row mutation battery. |
```

- [ ] **Step 3: Update `docs/build-status.md`**

Add a Done entry in the file's own established format, naming: the two backlog
rows closed, the stale-artifact-set correction, the measured threshold and its
17% gap, and the fact that the blocking flip required the `orchestration` change
to avoid three full-resolution re-renders per damaged episode.

- [ ] **Step 4: Update `docs/backlog.md`**

- Mark **R2.2** `✅`, appending the correction from design §0.1 (the row's
  quoted numbers come from the stale `work/reel/ep*` set; the shipped readings
  were 1.2–13.4°, all under threshold, with 2 of 8 not-checked; "28 codes" does
  not reproduce — the largest whole-frame per-channel change is 18.3 and the
  largest subject-box change 9.6).
- Mark **R2.5** `✅`, appending that `colour_cast` fired on **6** of 8 by the
  run's own packed evidence (the retro says 7), that 6 of 8 sources exceeded
  the bar before any grade, and that two of the five flags were unreachable.
- Add the five deferred rows from design §10:

| priority | row |
|---|---|
| P2 | Re-derive `SAT_DELTA_MAX`/`CONTRAST_DROP_MAX` on a run whose baseline is not the complaint (design §9.4) — blocked on R1.1. |
| P3 | Measure the right sample count and placement (§9.5); the batched decode makes each extra sample one PNG. |
| P3 | A second calibration shoot for `grade_delta_max` (§9.1) — the whole healthy-to-damage gap is 0.75 dE00. |
| P3 | `BLOWN_FRAC`/`CRUSHED_FRAC` remain uncalibrated — one data point and zero (§6). |
| P3 | The subject box is mostly background (§6); the inner-50% candidate was measured and rejected. Folded into R2.1. |

- [ ] **Step 5: Bump the version**

MINOR — an episode can now stop on colour, a `CheckSpec` field is renamed, and
three documented judge flags are removed. Set `.claude-plugin/plugin.json` to
`"version": "0.4.0"` and add the matching `## 0.4.0 — 2026-08-28` entry at the
top of `CHANGELOG.md`, written for someone installing it: what now stops a run,
what the judge sees instead of the old flags, and that nothing that was correct
before has changed verdict.

- [ ] **Step 6: Verify the manifest test**

Run: `.venv/bin/python -m pytest tests/test_plugin_manifests.py -q`
Expected: PASS (it asserts the changelog's top heading matches `plugin.json`).

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md CHANGELOG.md .claude-plugin/plugin.json docs skills
git commit -m "docs: the grade sensors, and the row corrections they forced"
```

---

## Task 7: the mutation battery

Every row below removes or weakens one guarantee and names the test that must go
**red**. A row that stays green is a coverage hole: add a test, never soften the
row. Run each mutation, record the result, then restore the file with an edit
(never `git checkout --`) and confirm with `git diff` that the restore is exact —
replacing an empty string prepends, and a bad restore reads as a passing row.

**Run every row with `PYTHONDONTWRITEBYTECODE=1`.** A one-byte edit can match
the previous file's size and mtime-second, and CPython then serves a stale
`.pyc` — a green row that proves nothing.

In zsh, `${=VAR}` is required to word-split a variable holding a test selection;
an unquoted `$VAR` arrives as one argument and pytest prints `no tests ran`,
which reads exactly like a non-discriminating row.

| # | mutation | must turn red |
|---|---|---|
| 1 | `colordiff.ciede2000`: drop the `rt` term from the final sqrt | `tests/lib/test_colordiff.py` — the 7.1792 row |
| 2 | `colordiff.ciede2000`: use `(h1p + h2p) / 2` unconditionally for `hbar` | the 1.0000 discontinuity rows |
| 3 | `colordiff._linearize`: use `v ** 2.2` instead of the piecewise curve | `test_rgb_to_lab_anchors` (mid-grey) |
| 4 | `colordiff.rgb_to_lab`: swap the R and B columns of the XYZ matrix | `test_a_pure_luma_lift_lands_in_dL_only` stays green (grey is symmetric) — `test_ciede2000_matches_the_published_reference` does not cover it either. **Expected to need a new test**: add one asserting a saturated red's `a*` is strongly positive and its `b*` positive, and re-run. |
| 5 | `color_fidelity.evaluate`: `statistics.median` → `max` | `test_the_verdict_is_the_median_not_the_worst` |
| 6 | `color_fidelity.evaluate`: `de > delta_max` → `de >= delta_max` | `test_threshold_is_strict_greater_than` |
| 7 | `color_fidelity.evaluate`: return early with `not-checked` when every sample's chroma is small (reintroduce the grey floor) | `test_a_near_grey_subject_still_gets_a_number` |
| 8 | `color_fidelity.evaluate`: `dominant` picks `max(comps)` instead of `max(abs(comps))` | `test_a_desaturation_names_chroma` |
| 9 | `models.CheckSpec`: drop the `isinstance(..., bool)` guard from `grade_delta_max` | `test_checkspec_grade_delta_max` (the bool-reject line) |
| 10 | `check_episode.SAMPLE_FRACS` → `(0.25, 0.5, 0.75)` | `test_the_check_takes_five_samples` |
| 11 | `check_episode._colour_fidelity`: drop the `min(..., last)` clamp | `test_sampling_survives_a_route_that_reaches_the_last_frame` |
| 12 | `check_episode._colour_fidelity`: `CheckResult(..., not d["exceeded"], ...)` → `CheckResult(..., None, ...)` | `test_hue_broken_grade_fails_the_episode` |
| 13 | `orchestration._UNFIXABLE`: remove `"color_fidelity"` | `test_a_colour_failure_escalates_immediately_with_its_own_reason` and `test_colour_is_listed_as_unfixable` |
| 14 | `orchestration._UNFIXABLE`: move `"color_fidelity"` to the front of the tuple | `test_an_upstream_failure_still_outranks_the_colour_reason` |
| 15 | `naturalness.evaluate`: re-add a `colour_cast` key computed from `stats["cast"]` | `test_evaluate_reports_only_the_two_absolute_flags` |
| 16 | `naturalness.evaluate_delta`: `contrast_drop` uses `abs(...)` | `test_contrast_drop_is_signed_because_a_gain_is_not_a_defect` |
| 17 | `naturalness.evaluate_delta`: `saturation_shift` drops the `abs(...)` (one-sided, like the old `SAT_MAX`) | `test_saturation_shift_is_two_sided_and_catches_a_desaturation` |
| 18 | `naturalness.CAST_DELTA_MAX` → `0.20` | `test_cast_shift_is_two_sided_and_bars_at_the_measured_value` |
| 19 | `episode_qc._source_reading`: return `{"source": None, "delta": None}` unconditionally | `test_the_evidence_packet_carries_the_pre_grade_reading` |
| 20 | `episode_qc._source_reading`: drop the `Path(seg).exists()` guard | `test_a_manifest_with_no_segment_reports_absent_not_empty` |

- [ ] **Step 1: Record the baseline**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q 2>&1 | tail -3 | tee /tmp/battery.log
```

- [ ] **Step 2: Run every row**

For each row: apply the mutation with an edit, run only the named tests, append
the row number and the observed result to `/tmp/battery.log` **as you go** (a
crashed session loses everything held only in memory), restore with an edit, and
run `git diff --stat` to confirm the file is back.

- [ ] **Step 3: Close every hole**

Row 4 is expected to need a new test — write it. Any other row that stays green
is a hole: write the test that discriminates it, then re-run that row.

- [ ] **Step 4: Full suite**

```bash
find . -name __pycache__ -type d -prune -exec rm -rf {} +
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
```
Expected: PASS, with no test skipped that was not skipped at baseline.

- [ ] **Step 5: Commit**

```bash
git add tests
git commit -m "test: the mutation battery, and the holes it found"
```

---

## Self-Review notes

**Spec coverage.** §2.1 → Task 0. §2.2 → Task 2. §2.3 → Task 1. §2.4 → Task 1
(the constant) and Task 3 (the verdict). §3 → Task 3. §4 → Task 4. §5 → Task 5.
§6 → nothing to build, recorded in Task 6's backlog rows. §7's contract table →
Tasks 1, 3, 4, 5. §8's six proofs → Task 0 step 1 (proof 1), Task 3 step 1
(proof 2, both arms), Task 1 step 1 (proof 3), Task 3 step 1 (proof 4, rows 13
and 14 of the battery guard it), Task 4 step 1 (proof 5), Task 5 step 1
(proof 6). §9 → design-only. §10 → Task 6 step 4.

**The one place to be careful.** Task 3 turns a check that has never failed into
one that can. The whole-suite run in Task 3 step 6 is where an existing fixture
with a strong synthetic "grade" will surface; the instruction there is to read
each failure rather than to relax the threshold, because the threshold is the
measured artifact of this slice.
