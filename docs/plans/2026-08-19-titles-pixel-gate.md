# Titles Pixel Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `deliver` hard-refuses a delivered reel whose declared titles never
reached the pixels, and `build_filterchain` refuses a title whose ink would land
outside the platform's safe zone — closing the last `not-checked` arm of the look
gate and a measured 244-px overflow that ships today.

**Architecture:** One pure geometry function in `titles.py` returning **fractions
of frame height** (so the module keeps knowing nothing about the canvas), read by
two consumers — the authoring refusal and the gate's band. One pure metric in
`lookcheck.py` comparing the delivered file **against itself** at two times, minus
the master's own change between them, so a vignette and picture motion both
cancel. `deliver` picks the timestamps, clamped out of the bookend fade's ramps,
and feeds the existing no-waiver refusal.

**Tech Stack:** numpy, ffmpeg via `lib/ffbin` + `lib/assembly.frames_rgb`, pytest.

**Design:** [docs/specs/2026-08-19-titles-pixel-gate-design.md](../specs/2026-08-19-titles-pixel-gate-design.md)

---

## Global Constraints

- **Fail loud.** Every new refusal raises `ValueError`/`RuntimeError` with the
  measurement and the remedy in the message. No clamping, no waiver
  (governance #8).
- **Imports at top of file.** No function-local imports in `scripts/`.
- **Scripts run as modules** (`pythonpath = .`); the interpreter is
  `.venv/bin/python`.
- **`lookcheck` stays pure** — numpy arrays in, findings out. No paths, no
  ffmpeg, no `titles` import. `deliver` computes the bands and passes them in.
- **`titles.py` stays canvas-agnostic** — `ink_extent` returns fractions of `h`,
  never pixels. This is the same invariant `build_filterchain`'s docstring
  already states.
- **Thresholds are module constants, not parameters** — the reason
  `naturalness.py` and the rest of `lookcheck` already state: a bar a caller can
  pass is a bar a subagent can pass.
- **Whole-object asserts** where a dataclass is returned.
- Do **not** run installers (`brew`, `pip install`, `setup.sh`). Verification is
  read-only plus pytest.
- Do **not** use `git checkout --`, `git restore`, `git reset --hard`, or
  `git stash`. Undo a mutation by rewriting the file content.
- Mutation batteries run under `PYTHONDONTWRITEBYTECODE=1` — a one-byte edit can
  match the previous row's size and mtime-second, and CPython then serves the
  stale `.pyc` (2026-08-18's finding).

---

## File Structure

| File | Responsibility |
|------|----------------|
| `scripts/lib/titles.py` | **+** `ink_extent`, `zone_overflow`, `ZONE_EPS`; `build_filterchain` refuses an overflowing title |
| `scripts/lib/lookcheck.py` | **+** `TITLE_INK_DELTA`/`TITLE_MIN_FRACTION`/`TITLE_BAND_PAD`, `TitleProbe`, `title_evidence`, `evaluate_titles`; `evaluate`'s `titles` becomes a probe sequence |
| `scripts/deliver.py` | `_verify_look` builds the probes (timestamps clamped out of the fade), batches the frame grabs, wires the findings |
| `scripts/titles.py` | **+** `build --platform`, an authoring-time preflight through the same `zone_overflow` |
| `scripts/lib/geometry.py` | **−** `crop_size` |
| `scripts/lib/safezones.py` | **−** `default_zone` |
| `scripts/lib/models.py` | `TrackMeta.__post_init__` enforces `DEGRADED_LEVELS` |
| `tests/lib/test_titles.py` | extent + overflow units; `default_zone` reference retargeted |
| `tests/lib/test_lookcheck.py` | metric + finding units |
| `tests/lib/test_deliver.py` | probe construction, the fade clamps, the witness rule |
| `tests/lib/test_geometry.py`, `tests/lib/test_layout.py`, `tests/lib/test_safezones.py`, `tests/lib/test_models.py` | orphan fallout |
| `tests/integration/test_look.py` | the real-ffmpeg proofs |

---

### Task 0: `titles.ink_extent` — the one geometry spelling

**Files:**
- Modify: `scripts/lib/titles.py`
- Test: `tests/lib/test_titles.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_titles.py`:

```python
def test_ink_extent_bottom_sits_on_the_zone_edge():
    # a single-line bottom title's ink box ends EXACTLY at the safe zone's inner
    # edge — that is what y_exprs' `h-th-h*z.bottom` means, and the extent must
    # agree or the overflow check below refuses every ordinary title.
    t = Title("salt sun and you", 0.0, 3.0, pos="bottom")
    top, bottom = titles_mod.ink_extent(t, "reels")
    assert bottom == pytest.approx(1.0 - 0.16)
    assert top == pytest.approx(1.0 - 0.16 - 1.0 / titles_mod.FONTSIZE_DIV)


def test_ink_extent_top_and_center():
    top_t = Title("hi", 0.0, 1.0, pos="top")
    assert titles_mod.ink_extent(top_t, "reels")[0] == pytest.approx(0.08)
    mid = Title("hi", 0.0, 1.0, pos="center")
    lo, hi = titles_mod.ink_extent(mid, "reels")
    assert (lo + hi) / 2 == pytest.approx(0.5)
    assert hi - lo == pytest.approx(1.0 / titles_mod.FONTSIZE_DIV)


def test_ink_extent_scales_with_the_titles_own_scale():
    small = Title("hi", 0.0, 1.0, pos="center", scale=0.5)
    lo, hi = titles_mod.ink_extent(small, "reels")
    assert hi - lo == pytest.approx(0.5 / titles_mod.FONTSIZE_DIV)


def test_ink_extent_adds_the_staircases_drop():
    # measured 2026-08-19: four steps at the default line_spacing drop the last
    # one 3*1.15/18 of the frame below the base box (design §5).
    t = Title("salt\nsun\nand\nyou", 0.0, 4.0, reveal="stair", reveal_step=0.4)
    base_bottom = 1.0 - 0.16
    assert titles_mod.ink_extent(t, "reels")[1] == pytest.approx(
        base_bottom + 3 * 1.15 / titles_mod.FONTSIZE_DIV)


def test_ink_extent_word_reveal_stays_on_one_line():
    # a word reveal lays every step at the SAME y — only a stair drops lines, so
    # a word reveal's extent must equal the plain title's.
    plain = Title("salt sun and you", 0.0, 3.0, pos="bottom")
    word = Title("salt sun and you", 0.0, 3.0, pos="bottom", reveal="word",
                 reveal_step=0.3)
    assert titles_mod.ink_extent(word, "reels") == titles_mod.ink_extent(plain, "reels")


def test_ink_extent_unknown_platform_takes_the_generic_zone():
    t = Title("hi", 0.0, 1.0, pos="bottom")
    assert titles_mod.ink_extent(t, "nope") == titles_mod.ink_extent(t, "")
```

Add at the top of the file, beside the existing imports:

```python
import pytest

from scripts.lib import safezones, titles as titles_mod
```

(If `pytest` / `safezones` are already imported there, do not duplicate them.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_titles.py -k ink_extent -q`
Expected: FAIL — `AttributeError: module 'scripts.lib.titles' has no attribute 'ink_extent'`

- [ ] **Step 3: Implement**

In `scripts/lib/titles.py`, after `y_exprs`, add:

```python
def ink_extent(t: Title, platform: str = "") -> tuple[float, float]:
    """(top, bottom) of the rows this title's ink can occupy, as FRACTIONS of frame
    height. Fractions and not pixels for the reason build_filterchain gives: the
    drawtext chain is resolution-agnostic, and so is everything derived from it.

    Two readers, one spelling (design 2026-08-19 §5): zone_overflow compares this
    against the platform's safe zone, and deliver multiplies it by the delivered
    frame's own height to get the band lookcheck measures. They cannot disagree.

    The estimate is deliberately CONSERVATIVE — `th` (drawtext's own rendered text
    height, which Python cannot know without rendering) is approximated by the font
    size, and a staircase's drop is taken at its maximum step. Measured on real
    footage it predicts [0.784, 1.032] where the ink reached [0.799, 0.967] of
    frame height: over-estimating widens a band (harmless — it only dilutes the
    evidence fraction) and refuses a title that would have just fitted (a loud
    refusal with an obvious remedy). Under-estimating would ship the defect."""
    z = safezones.safe_zone_for(platform)
    fs = t.scale / FONTSIZE_DIV                     # font size as a fraction of h
    if t.pos == "top":
        top = z.top
    elif t.pos == "center":
        top = 0.5 - fs / 2
    else:
        top = 1.0 - z.bottom - fs
    drop = 0.0
    if t.reveal == "stair":
        # _layers pushes step j down by j * line_spacing * scale / FONTSIZE_DIV of h,
        # and NOTHING lifts the base y to make room — the last step is the extent.
        drop = (len(_steps(t)) - 1) * t.line_spacing * t.scale / FONTSIZE_DIV
    return top, top + fs + drop
```

Add `from scripts.lib import safezones` to the imports if `y_exprs` does not
already import it that way (it calls `safezones.safe_zone_for`, so it does).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_titles.py -k ink_extent -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/titles.py tests/lib/test_titles.py
git commit -m "$(cat <<'EOF'
feat(titles): the ink's predicted extent, in fractions of the frame

The gate needs to know which rows a title's ink can occupy, and so does the
safe-zone refusal that follows. One function answers both, in fractions of h
rather than pixels, because the drawtext chain it describes is itself
resolution-agnostic — titles.py has never known the canvas and does not start
here.

The estimate is conservative on purpose: `th` is approximated by the font size
and a staircase's drop is taken at its last step. Over-estimating dilutes a
band and refuses a title that would just have fitted; under-estimating ships
the defect the next commit is about.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 1: the safe-zone refusal

**Files:**
- Modify: `scripts/lib/titles.py`
- Test: `tests/lib/test_titles.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_zone_overflow_passes_an_ordinary_bottom_title():
    # the ordinary case sits EXACTLY on the zone edge — an off-by-an-epsilon
    # comparison here would refuse every title this repo authors.
    assert titles_mod.zone_overflow(Title("hi", 0.0, 1.0, pos="bottom"), "reels") == ""
    assert titles_mod.zone_overflow(Title("hi", 0.0, 1.0, pos="top"), "reels") == ""
    assert titles_mod.zone_overflow(Title("hi", 0.0, 1.0, pos="center"), "reels") == ""


def test_zone_overflow_names_a_staircase_that_leaves_the_zone():
    t = Title("salt\nsun\nand\nyou", 0.0, 4.0, pos="bottom", reveal="stair",
              reveal_step=0.4)
    why = titles_mod.zone_overflow(t, "reels")
    assert "below" in why and "reels" in why
    assert "0.16" in why                      # the zone it broke, quoted


def test_zone_overflow_a_top_staircase_fits():
    # the same four steps at the TOP have the whole frame to fall into.
    t = Title("salt\nsun\nand\nyou", 0.0, 4.0, pos="top", reveal="stair",
              reveal_step=0.4)
    assert titles_mod.zone_overflow(t, "reels") == ""


def test_zone_overflow_a_huge_centred_title_leaves_both_edges():
    t = Title("hi", 0.0, 1.0, pos="center", scale=5.0)
    assert titles_mod.zone_overflow(t, "") == ""     # 5/18 of h still fits centred
    tall = Title("a\nb\nc\nd\ne", 0.0, 5.0, pos="center", reveal="stair",
                 reveal_step=0.5, scale=3.0)
    assert "below" in titles_mod.zone_overflow(tall, "")


def test_build_filterchain_refuses_a_title_that_leaves_the_zone(tmp_path):
    t = Title("salt\nsun\nand\nyou", 0.0, 4.0, pos="bottom", reveal="stair",
              reveal_step=0.4)
    with pytest.raises(ValueError, match="leaves the reels safe zone"):
        build_filterchain(Titles(items=(t,)), str(tmp_path), resolve=_fake_resolve,
                          platform="reels")


def test_build_filterchain_still_builds_the_ordinary_titles(tmp_path):
    # the anti-regression pin for the refusal: everything that used to build must
    # still build, at every position.
    ts = Titles(items=tuple(Title("hi", 0.0, 1.0, pos=p) for p in POSITIONS))
    vf = build_filterchain(ts, str(tmp_path), resolve=_fake_resolve, platform="reels")
    assert vf.count("drawtext=") == len(POSITIONS)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_titles.py -k "zone_overflow or leaves_the_zone or still_builds" -q`
Expected: FAIL — `AttributeError: ... has no attribute 'zone_overflow'`

- [ ] **Step 3: Implement**

In `scripts/lib/titles.py`, after `ink_extent`:

```python
# The ordinary bottom title's ink box ends EXACTLY on the zone's inner edge, so the
# comparison needs slack for float arithmetic or the refusal fires on every title
# this repo authors. Sized at the arithmetic's own noise, not at a real margin.
ZONE_EPS = 1e-9


def zone_overflow(t: Title, platform: str = "") -> str:
    """"" if the title's ink stays inside the platform's safe zone, else the remedy.

    A title is laid out AGAINST the zone (y_exprs), so a single line is inside by
    construction. What is not: a `reveal="stair"`, whose per-step drop `_layers`
    adds below the base y with nothing lifting the base to make room. Measured
    2026-08-19 on the reels table — a four-step bottom staircase renders 244 px
    into the app's caption/button chrome, and nothing refused it (design §5).

    A string and not a bool so both readers can quote the same sentence: the
    chokepoint refusal in build_filterchain and the authoring preflight in
    scripts/titles.py."""
    z = safezones.safe_zone_for(platform)
    top, bottom = ink_extent(t, platform)
    name = platform.strip().lower() or "generic"
    if top < z.top - ZONE_EPS:
        return (f"a {t.pos!r} title at scale {t.scale:g} reaches {top:.4f} of frame "
                f"height, above the {name} safe zone's {z.top:g} top margin")
    if bottom > 1.0 - z.bottom + ZONE_EPS:
        return (f"a {t.pos!r} title{' staircase' if t.reveal == 'stair' else ''} at "
                f"scale {t.scale:g} reaches {bottom:.4f} of frame height, below the "
                f"{name} safe zone's inner edge at {1.0 - z.bottom:.4f} "
                f"(bottom margin {z.bottom:g}) — the app draws its caption and "
                f"buttons there")
    return ""
```

In `build_filterchain`, immediately after `y_expr = y_exprs(platform)`:

```python
    for i, t in enumerate(titles.items):
        why = zone_overflow(t, platform)
        if why:
            raise ValueError(
                f"TITLES.json item {i} ({t.text.splitlines()[0]!r}) leaves the "
                f"{platform.strip().lower() or 'generic'} safe zone: {why}. Shorten the "
                f"staircase, lower line_spacing, use pos='top', or reduce scale — the "
                f"layout is not moved for you, because relocating a title the author "
                f"positioned is an invisible creative change")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_titles.py -q`
Expected: PASS, whole file green

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/titles.py tests/lib/test_titles.py
git commit -m "$(cat <<'EOF'
fix(titles): a staircase may not render into the app's chrome

Measured on the reels table at 1080x1920: a four-step bottom `stair` puts its
last line 244 px past the safe zone's inner edge, into exactly the strip
Instagram draws its caption and buttons over. `_layers` adds the per-step drop
below the base y and nothing lifts the base to make room, so the layout that is
correct for one line is wrong for four — and eleven other things
Title.__post_init__ validates never included this one, because the title does
not know its platform and the chain builder that does never looked.

Refused at the chokepoint every render passes through, not clamped: moving the
base y up would silently relocate a title the author positioned, and shrinking
it would silently resize one. Title.fade's own two-ramp refusal is the
precedent.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `lookcheck` — the metric

**Files:**
- Modify: `scripts/lib/lookcheck.py`
- Test: `tests/lib/test_lookcheck.py`

- [ ] **Step 1: Write the failing tests**

```python
def _flat(h, w, v):
    return np.full((h, w, 3), v, dtype=np.uint8)


def test_title_evidence_finds_ink_the_master_does_not_explain():
    m_in = m_out = _flat(100, 50, 80)
    d_out = _flat(100, 50, 80)
    d_in = _flat(100, 50, 80)
    d_in[40:60, 10:40] = 255                    # ink in the band's middle
    frac = lookcheck.title_evidence((m_in, d_in), (m_out, d_out), (30, 70))
    assert frac == pytest.approx(20 * 30 / (40 * 50))


def test_title_evidence_is_zero_without_ink():
    m = _flat(100, 50, 80)
    assert lookcheck.title_evidence((m, m), (m, m), (30, 70)) == 0.0


def test_title_evidence_ignores_a_multiplicative_darkening():
    # the vignette case, and the reason this metric exists: a static transform
    # applied at BOTH times can only shrink the delivery's own frame-to-frame
    # change relative to the master's, so it scores <= 0 (design 2026-08-19 2.3).
    m_in, m_out = _flat(100, 50, 200), _flat(100, 50, 60)
    d_in, d_out = _flat(100, 50, 100), _flat(100, 50, 30)      # halved everywhere
    assert lookcheck.title_evidence((m_in, d_in), (m_out, d_out), (30, 70)) == 0.0


def test_title_evidence_ignores_picture_motion():
    m_in, m_out = _flat(100, 50, 20), _flat(100, 50, 220)      # a hard cut
    assert lookcheck.title_evidence((m_in, m_in), (m_out, m_out), (30, 70)) == 0.0


def test_title_evidence_reads_only_the_band():
    m = _flat(100, 50, 80)
    d_in = _flat(100, 50, 80); d_in[0:20] = 255                # ink ABOVE the band
    assert lookcheck.title_evidence((m, d_in), (m, m), (30, 70)) == 0.0


def test_evaluate_titles_passes_a_rendered_title():
    m = _flat(100, 50, 80)
    d_in = _flat(100, 50, 80); d_in[40:60, 10:40] = 255
    p = lookcheck.TitleProbe(label="hook", band=(30, 70),
                             inside=(m, d_in), witnesses=((m, m),))
    f, = lookcheck.evaluate_titles([p])
    assert (f.check, f.status) == ("titles:hook", "pass")
    assert f.expected == pytest.approx(lookcheck.TITLE_MIN_FRACTION)


def test_evaluate_titles_fails_a_title_that_never_rendered():
    m = _flat(100, 50, 80)
    p = lookcheck.TitleProbe(label="hook", band=(30, 70), inside=(m, m),
                             witnesses=((m, m),))
    f, = lookcheck.evaluate_titles([p])
    assert f.status == "fail"
    assert "did not render" in f.detail


def test_evaluate_titles_takes_the_best_witness():
    # measured: a bold-box title scores 3.5% against one witness and 18.9% against
    # another, purely on what the witness frame happened to show. ANY title-free
    # frame may witness, so the rule is best-of, not first-of.
    m = _flat(100, 50, 80)
    d_in = _flat(100, 50, 80); d_in[40:60, 10:40] = 255
    dead, live = (m, m), (m, m)
    p = lookcheck.TitleProbe(label="hook", band=(30, 70), inside=(m, d_in),
                             witnesses=((_flat(100, 50, 255), _flat(100, 50, 255)),
                                        live))
    assert lookcheck.evaluate_titles([p])[0].status == "pass"


def test_evaluate_titles_reports_a_skipped_probe_as_not_checked():
    p = lookcheck.TitleProbe(label="hook", band=(30, 70),
                             skipped="every instant carries a title")
    f, = lookcheck.evaluate_titles([p])
    assert f.status == "not-checked" and "every instant" in f.detail


def test_evaluate_routes_title_probes_through(): 
    m = _flat(100, 50, 80)
    p = lookcheck.TitleProbe(label="hook", band=(30, 70), inside=(m, m),
                             witnesses=((m, m),))
    out = lookcheck.evaluate([m], [m], None, None, None, None, titles=[p])
    assert [f.check for f in out] == ["titles:hook"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_lookcheck.py -k "title" -q`
Expected: FAIL — `AttributeError: module 'scripts.lib.lookcheck' has no attribute 'title_evidence'`

- [ ] **Step 3: Implement**

In `scripts/lib/lookcheck.py`, add to the imports:

```python
from collections.abc import Sequence
```

Add the constants after `BOX_DIV`:

```python
# Titles. The per-pixel bar, in codes, is what does the discriminating: measured over
# 110 ordered frame pairs of a real delivered reel re-encoded with NO title, the worst
# single pixel reached 30 without a look and 24 under a max-depth (0.60) vignette, and
# not one pair produced a qualifying pixel. 40 sits 1.33x above that worst observation.
# Real footage deliberately: the synthetic corpus peaked at 2, which would have
# justified a far lower bar and a far weaker gate (design 2026-08-19 3.1).
TITLE_INK_DELTA = 40
# With the no-title side at exactly zero, this floor is not separating signal from
# noise — TITLE_INK_DELTA already did. It absorbs a stray cluster on footage rougher
# than any measured. 0.02% is 51 pixels of the measured band; the smallest legitimate
# title (one period) produced 0.0384%, "hi" 0.1717%, a full line 2.9966% (3.2).
TITLE_MIN_FRACTION = 0.0002
# Padding around titles.ink_extent, in font sizes each side. Measured to contain every
# style: bold-box's box and outline-bold's stroke run 9 rows above and 15 below the
# predicted text box, well inside 0.6 font sizes. A band too TALL only dilutes the
# fraction; a band that misses the ink is a false fail on a no-waiver gate (3.3).
TITLE_BAND_PAD = 0.6
```

Add the probe contract after `LookFinding`:

```python
@dataclass(frozen=True)
class TitleProbe:
    """One title's sampling material, or `skipped` naming why there is none.

    `inside` is the (master, delivered) pair at a time inside the title's window;
    each `witnesses` entry is the same pair at a time NO title covers. Both come
    from deliver, which owns the timestamps — this module never touches a path.

    `band` is (lo, hi) row indices in the delivered frame, from titles.ink_extent
    padded by TITLE_BAND_PAD. Rows and not fractions because by this point the
    frame's real height is known and the arrays are about to be sliced by it."""
    label: str
    band: tuple[int, int]
    inside: tuple[np.ndarray, np.ndarray] | None = None
    witnesses: tuple[tuple[np.ndarray, np.ndarray], ...] = ()
    skipped: str = ""
```

Add the metric and the evaluator before `evaluate`:

```python
def title_evidence(inside: tuple[np.ndarray, np.ndarray],
                   witness: tuple[np.ndarray, np.ndarray],
                   band: tuple[int, int]) -> float:
    """Share of the band's pixels carrying ink the MASTER does not explain.

    The delivered file is compared against ITSELF at two times, minus the master's
    own change between the same two — not against the master at one time. That is
    not a style choice, it is the only version that works: measured, a max-depth
    vignette alone moves 9.58% of a bottom band's pixels past a 60-code bar, more
    than a real title does (design 2026-08-19 2.1/2.2). A transform applied at both
    times cancels here; picture motion cancels here; ink present at one time and
    absent at the other has no counterpart in the master and survives."""
    lo, hi = band
    (m_in, d_in), (m_out, d_out) = inside, witness
    for f, what in ((m_in, "a master frame"), (d_in, "a delivered frame"),
                    (m_out, "a master frame"), (d_out, "a delivered frame")):
        _rgb(f, what)
    _same_shape(m_in, d_in)
    _same_shape(m_out, d_out)
    _same_shape(m_in, m_out)
    if not 0 <= lo < hi:
        raise ValueError(f"lookcheck: a title band must be a non-empty row range "
                         f"inside the frame, got {band}")
    a = np.abs(d_in[lo:hi].astype(np.int16) - d_out[lo:hi].astype(np.int16))
    b = np.abs(m_in[lo:hi].astype(np.int16) - m_out[lo:hi].astype(np.int16))
    return float(((a - b).max(axis=2) > TITLE_INK_DELTA).mean())


def evaluate_titles(probes: Sequence[TitleProbe]) -> list[LookFinding]:
    """One finding per declared title. `not-checked` is a real outcome here for the
    same reason it is for the vignette's black-corner floor: a reel whose titles
    cover every instant has no witness frame, and a title lying entirely inside a
    bookend fade has no in-window frame bright enough to read — measured, a sample
    at alpha 0.10 scores 0.0000% on a correctly rendered title (design 2026-08-19
    4). Saying so beats a bar that pretends."""
    out: list[LookFinding] = []
    for p in probes:
        if p.skipped or p.inside is None or not p.witnesses:
            out.append(LookFinding(
                check=f"titles:{p.label}", status="not-checked",
                detail=(p.skipped or "no usable frame pair was sampled for this title"),
                measured=0.0, expected=TITLE_MIN_FRACTION))
            continue
        # Best of the witnesses, not the first: measured, one bold-box title scored
        # 3.53% against a dark witness frame and 18.94% against a bright one. Any
        # title-free frame is a valid witness, so one that sees the ink is enough.
        frac = max(title_evidence(p.inside, w, p.band) for w in p.witnesses)
        ok = frac >= TITLE_MIN_FRACTION
        out.append(LookFinding(
            check=f"titles:{p.label}", status="pass" if ok else "fail",
            detail=(f"{100 * frac:.4f}% of the title's band rows {p.band[0]}-{p.band[1]} "
                    f"carry ink the master does not explain"
                    + ("" if ok else
                       f", under the {100 * TITLE_MIN_FRACTION:.2f}% floor — the title "
                       f"did not render, or rendered where this band is not looking")),
            measured=frac, expected=TITLE_MIN_FRACTION))
    return out
```

Change `evaluate`'s signature and body. The parameter becomes:

```python
             titles: Sequence[TitleProbe] = (),
```

and the two `titles` uses become:

```python
    if not (vignette or fade or titles):
        return []
```

```python
    out.extend(evaluate_titles(titles))
```

replacing the whole `if titles:` stub block. Update `evaluate`'s docstring
paragraph about `titles` to describe the probes.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_lookcheck.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/lookcheck.py tests/lib/test_lookcheck.py
git commit -m "$(cat <<'EOF'
feat(lookcheck): titles get a measurement instead of a not-checked

The stub this replaces said the quiet part out loud: titles were declared, and
nothing checked them. The obvious fix does not work — measured, a max-depth
vignette alone moves 9.58% of a bottom band's pixels past a 60-code bar against
a real title's 5.71%, so master-vs-delivered at one timestamp cannot separate
the two. Every declared filter differs from the master.

What separates is the delivered file against ITSELF at two times, minus the
master's own change between them. A static transform cancels, picture motion
cancels, and ink present in one frame and absent in the other survives. Over
110 title-free frame pairs of a real reel, at a 0.60 vignette and a plain
re-encode, the evidence is exactly zero; the smallest title measured scores
0.0384%.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `deliver` samples the frames

**Files:**
- Modify: `scripts/deliver.py`
- Test: `tests/lib/test_deliver.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_title_times_clamps_both_ends_out_of_the_fade():
    # measured (design 2026-08-19 4): a t_in at alpha 0.10 scores 0.0000% on a
    # correctly rendered title (false FAIL) and a witness inside the fade-out
    # inflates to 30.69% (false PASS). Both ends are clamped.
    items = (Title("hook", 0.0, 3.0), )
    t_in, witnesses, skipped = deliver._title_times(items, 0, dur=34.0, fade=1.0)
    assert skipped == ""
    assert t_in >= 1.0
    assert all(1.0 <= w <= 33.0 for w in witnesses)


def test_title_times_skips_a_title_buried_in_the_fade():
    items = (Title("hook", 0.0, 0.5), )
    _, _, skipped = deliver._title_times(items, 0, dur=34.0, fade=1.0)
    assert "bookend fade" in skipped


def test_title_times_skips_when_no_instant_is_title_free():
    items = (Title("a", 0.0, 20.0), Title("b", 19.0, 15.0))
    _, _, skipped = deliver._title_times(items, 0, dur=34.0, fade=0.0)
    assert "title-free" in skipped


def test_title_times_witness_avoids_every_titles_window():
    items = (Title("a", 0.0, 5.0), Title("b", 20.0, 5.0))
    _, witnesses, skipped = deliver._title_times(items, 0, dur=34.0, fade=0.0)
    assert skipped == "" and witnesses
    for w in witnesses:
        assert not (0.0 <= w <= 5.0) and not (20.0 <= w <= 25.0)


def test_title_band_pads_the_extent_and_clamps_to_the_frame():
    t = Title("hi", 0.0, 1.0, pos="bottom")
    lo, hi = deliver._title_band(t, h=1920, platform="reels")
    top, bottom = titles_mod.ink_extent(t, "reels")
    assert lo < top * 1920 and hi > bottom * 1920
    assert 0 <= lo < hi <= 1920
    tall = Title("a\nb\nc\nd", 0.0, 4.0, pos="bottom", reveal="stair", reveal_step=0.4)
    assert deliver._title_band(tall, h=1920, platform="")[1] == 1920      # clamped
```

Add `from scripts.lib import titles as titles_mod` and
`from scripts.lib.titles import Title` to the test file's imports if absent.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_deliver.py -k "title_times or title_band" -q`
Expected: FAIL — `AttributeError: module 'scripts.deliver' has no attribute '_title_times'`

- [ ] **Step 3: Implement**

Add to `scripts/deliver.py`'s imports: `from scripts.lib import titles as titles_lib`
(keep the existing `from scripts.lib.titles import Titles, build_filterchain`).

Add above `_verify_look`:

```python
# How many title-free moments to compare a title against. Measured, the witness
# barely matters for a single-shot title (2.9645%-2.9966% across five), but a
# bold-box one swings 3.53%-18.94% on what the witness frame happens to show — so
# a handful, best-of. Each costs one frame from each file (design 2026-08-19 2.4).
_TITLE_WITNESSES = 3
_WITNESS_GRID = 24          # candidate instants scanned across the legal window


def _title_band(t: "Title", h: int, platform: str) -> tuple[int, int]:
    """The delivered rows lookcheck measures for this title: titles.ink_extent
    padded by lookcheck.TITLE_BAND_PAD font sizes each side, in pixels, clamped."""
    top, bottom = titles_lib.ink_extent(t, platform)
    pad = lookcheck.TITLE_BAND_PAD * t.scale / titles_lib.FONTSIZE_DIV
    return (max(0, int((top - pad) * h)), min(h, int(math.ceil((bottom + pad) * h))))


def _title_times(items: "tuple[Title, ...]", i: int, dur: float,
                 fade: float) -> tuple[float, tuple[float, ...], str]:
    """(in-window time, witness times, skip reason) for item `i`.

    Both ends are clamped into [fade, dur - fade] because BOTH ends break inside a
    ramp, in opposite directions and for different reasons (design 2026-08-19 §4):
    a title sampled at alpha 0.10 has almost no ink to find, and a witness faded
    toward black makes |d_in - d_out| large with no title involved at all — a false
    fail and a false pass respectively."""
    lo, hi = float(fade), float(dur) - float(fade)
    t = items[i]
    if hi - lo <= 0:
        return 0.0, (), (f"the {fade:g}s bookend fade covers the whole {dur:g}s reel, "
                         f"so there is no frame outside a ramp to measure")
    w_lo, w_hi = max(t.start, lo), min(t.start + t.dur, hi)
    if w_hi - w_lo <= 0:
        return 0.0, (), (f"the title's window [{t.start:g}, {t.start + t.dur:g}] lies "
                         f"entirely inside the {fade:g}s bookend fade, where a "
                         f"correctly rendered title is drawn too faint to measure")
    covered = [(it.start, it.start + it.dur) for it in items]
    free = [lo + (hi - lo) * (k + 0.5) / _WITNESS_GRID for k in range(_WITNESS_GRID)]
    free = [x for x in free if not any(a <= x <= b for a, b in covered)]
    if not free:
        return 0.0, (), ("every instant of the reel carries a title, so there is no "
                         "title-free frame to compare against")
    step = max(1, len(free) // _TITLE_WITNESSES)
    return (w_lo + w_hi) / 2, tuple(free[::step][:_TITLE_WITNESSES]), ""
```

Add `import math` to the imports if absent.

Rewrite `_verify_look` to build the probes. Replace its body's tail:

```python
    vig = look.vignette if look is not None else 0.0
    fade = look.fade if look is not None else 0.0
    if not (vig or fade or titles is not None):
        return []
    out_dur = assembly.probe_duration(out)
    ts = [out_dur * f for f in (0.25, 0.5, 0.75)]
    m_si, d_si = assembly.probe_stream(master), assembly.probe_stream(out)
    m_fps, d_fps = m_si.fps, d_si.fps
    first_m = first_d = last_m = last_d = None
    if fade:
        first_m = assembly.frames_rgb(master, [0.0], m_fps)[0]
        first_d = assembly.frames_rgb(out, [0.0], d_fps)[0]
        last_m = assembly.last_frame_rgb(master, m_fps)
        last_d = assembly.last_frame_rgb(out, d_fps)
    # Titles: one in-window time per title plus a shared pool of title-free
    # witnesses, all collected into ONE extra frames_rgb per file — frames_rgb
    # selects them in a single decode, so N titles do not cost N decodes.
    probes: list[lookcheck.TitleProbe] = []
    if titles is not None:
        items = Titles.from_json(titles).items
        plan = [_title_times(items, i, out_dur, fade) for i in range(len(items))]
        extra = sorted({t for t_in, ws, why in plan if not why
                        for t in (t_in, *ws)})
        m_extra = dict(zip(extra, assembly.frames_rgb(master, extra, m_fps))) if extra else {}
        d_extra = dict(zip(extra, assembly.frames_rgb(out, extra, d_fps))) if extra else {}
        for i, (t_in, ws, why) in enumerate(plan):
            band = _title_band(items[i], d_si.h, platform)
            label = items[i].text.splitlines()[0][:24] or f"item{i}"
            probes.append(lookcheck.TitleProbe(
                label=label, band=band, skipped=why,
                inside=None if why else (m_extra[t_in], d_extra[t_in]),
                witnesses=() if why else tuple((m_extra[w], d_extra[w]) for w in ws)))
    return lookcheck.evaluate(assembly.frames_rgb(master, ts, m_fps),
                              assembly.frames_rgb(out, ts, d_fps),
                              first_m, first_d, last_m, last_d,
                              vignette=vig, fade=fade, fps=d_fps, titles=probes)
```

`_verify_look` needs `platform`, so add it to the signature
(`def _verify_look(master, out, look, titles, platform="")`) and pass
`platform` at the call site in `deliver()`.

Update `_verify_look`'s docstring to describe the titles branch.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_deliver.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/deliver.py tests/lib/test_deliver.py
git commit -m "$(cat <<'EOF'
feat(deliver): sample the frames the titles gate needs, clear of the fade

One in-window moment per title plus a shared pool of title-free witnesses, all
collected in one extra frames_rgb per file so N titles do not cost N decodes.

Both ends are clamped out of the bookend fade's ramps, and that is measured in
both directions rather than assumed: a title sampled at alpha 0.10 scores
0.0000% though it rendered correctly, and a witness taken inside the fade-out
inflates the evidence 4.6x on a delivery whose drawtext never ran. One is a
false fail, the other a false pass, and a no-waiver gate can afford neither.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: the authoring preflight

**Files:**
- Modify: `scripts/titles.py`
- Test: `tests/lib/test_titles_driver.py` (or the existing driver test file)

- [ ] **Step 1: Write the failing test**

```python
def test_build_titles_refuses_a_zone_overflow_at_authoring_time(tmp_path, ...):
    # the chokepoint refusal lives in build_filterchain, which runs at DELIVER —
    # after every episode is rendered and the master assembled. The same check
    # here costs nothing and tells the author at the stage they can fix it.
    ...
    with pytest.raises(ValueError, match="leaves the reels safe zone"):
        titles_drv.build_titles(..., platform="reels")
```

Shape the fixture on whatever `build_titles`' existing tests already build; the
new assertion is the `platform=` argument and the refusal.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ -k "build_titles and zone" -q`
Expected: FAIL — unexpected keyword argument `platform`

- [ ] **Step 3: Implement**

Give `build_titles` a `platform: str = ""` parameter; after the `Titles` object is
assembled and before it is written, run the same loop:

```python
    for i, t in enumerate(ts.items):
        why = titles_lib.zone_overflow(t, platform)
        if why:
            raise ValueError(
                f"TITLES.json item {i} ({t.text.splitlines()[0]!r}) leaves the "
                f"{platform.strip().lower() or 'generic'} safe zone: {why}. deliver "
                f"refuses this at render time; refusing here saves the encode")
```

Add the CLI flag mirroring `deliver`'s wording:

```python
    b.add_argument("--platform", default="",
                   help="tiktok|reels|shorts — the safe-zone table titles lay out "
                        "against; unset takes the generic margins")
```

and thread `platform=a.platform`.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/ -k "titles" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/titles.py tests/
git commit -m "$(cat <<'EOF'
feat(titles): refuse a zone overflow at authoring, not only at deliver

build_filterchain is the chokepoint and keeps the refusal that matters, but it
runs at deliver — after every episode is rendered and the master assembled, so
the author learns at the most expensive possible moment. The same pure check
behind `titles build --platform` costs nothing and fires at the stage where the
fix is a one-line edit.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: the three orphans

**Files:**
- Modify: `scripts/lib/geometry.py`, `scripts/lib/safezones.py`, `scripts/lib/models.py`
- Test: `tests/lib/test_geometry.py`, `tests/lib/test_layout.py`, `tests/lib/test_safezones.py`, `tests/lib/test_titles.py`, `tests/lib/test_models.py`

- [ ] **Step 1: Write the failing test (the one that WIRES rather than deletes)**

```python
def test_track_meta_refuses_a_degraded_rung_outside_the_vocabulary():
    from scripts.lib.models import TrackMeta
    for good in (None, "flow", "manual"):
        assert TrackMeta(degraded=good).degraded == good
    with pytest.raises(ValueError, match="degraded"):
        TrackMeta(degraded="optical-flow")
    with pytest.raises(ValueError, match="degraded"):
        TrackMeta.from_dict({"degraded": "manual "})
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k degraded -q`
Expected: FAIL — `DID NOT RAISE`

- [ ] **Step 3: Implement all three**

`scripts/lib/models.py` — give `TrackMeta` a `__post_init__`:

```python
    def __post_init__(self) -> None:
        # DEGRADED_LEVELS existed from the tracking-ladder slice and nothing read it:
        # `degraded` accepted any string, so a typo'd rung name rode onto every
        # post-tracking result unchallenged. Its siblings (HERO_RULES, POSITIONS,
        # STYLES, REVEALS) are all enforced by a __post_init__; this one now is too.
        if self.degraded is not None and self.degraded not in DEGRADED_LEVELS:
            raise ValueError(f"TrackMeta.degraded {self.degraded!r} not in "
                             f"{DEGRADED_LEVELS} (None = a clean YOLO route)")
```

`scripts/lib/geometry.py` — delete `crop_size`. Retarget its callers in tests:
`tests/lib/test_geometry.py` lines 7-13 become `crop_for((9, 16), 1.0, 1920, 1080)`
style calls, and the redundant
`test_crop_for_canvas_aspect_matches_crop_size` is deleted (it compared a
function to its own one-line wrapper). `tests/lib/test_layout.py:144` calls
`geometry.crop_for((canvas[0], canvas[1]), 1.0, src[0], src[1])`.

`scripts/lib/safezones.py` — delete `default_zone`. Its four test references
become `safezones.SAFE_ZONES["generic"]` (`tests/lib/test_safezones.py:36,100`,
`tests/lib/test_titles.py:159`).

- [ ] **Step 4: Run the affected files**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py tests/lib/test_geometry.py tests/lib/test_layout.py tests/lib/test_safezones.py tests/lib/test_titles.py -q`
Expected: PASS

- [ ] **Step 5: Prove the audit is clean again**

Re-run the audit from design §6 and confirm zero orphan public functions and zero
orphan module constants. Record the output in the commit body.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/geometry.py scripts/lib/safezones.py scripts/lib/models.py tests/
git commit -m "$(cat <<'EOF'
chore: the three orphans an AST audit found, two deleted and one wired

geometry.crop_size was a one-line wrapper over crop_for with four test callers
and no production one. safezones.default_zone outlived the slice that obsoleted
it — its docstring still claims to be "titles' single margin source", which
stopped being true when titles-animations replaced the frozen _Y_EXPR with
y_exprs(platform).

models.DEGRADED_LEVELS is the odd one out and gets wired instead of deleted: it
is a declared vocabulary that nothing validated against, so TrackMeta.degraded
accepted any string while every sibling vocabulary in the module is enforced by
a __post_init__. A typo'd rung name rode onto every post-tracking result
unchallenged.

The audit that found them reports zero orphan contract fields, which is the
number worth keeping.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: the real-ffmpeg proofs

**Files:**
- Modify: `tests/integration/test_look.py`

- [ ] **Step 1: Write the tests**

Three, each with a control that must not move:

```python
@pytest.mark.integration
def test_the_gate_refuses_a_reel_whose_titles_never_rendered(sample_clip, tmp_path, need_filter):
    """deliver ships the master unchanged while claiming a title — the exact bug
    class this gate exists for (a dropped filter, a bad font, a split filtergraph).
    The control is the SAME call with the drawtext chain intact, which must deliver."""
    need_filter("drawtext")
    ...
    # sabotage: monkeypatch build_filterchain to "" so the encode carries no title
    with pytest.raises(RuntimeError, match="does not carry the look it declared"):
        deliver_mod.deliver(..., titles=str(tjson))
    # control — unpatched, the same titles file delivers
    out = deliver_mod.deliver(..., titles=str(tjson))
    assert Path(out).exists()


@pytest.mark.integration
def test_a_max_depth_vignette_alone_does_not_read_as_a_title(sample_clip, tmp_path, need_filter):
    """The anti-regression pin for the METRIC choice. Measured (design 2.1): a
    0.60 vignette moves 9.58% of a bottom band's pixels past a 60-code
    master-vs-delivered bar — MORE than a real title. If anyone ever simplifies
    title_evidence back to that comparison, this reddens."""
    ...


@pytest.mark.integration
def test_a_title_inside_the_bookend_fade_reports_not_checked(sample_clip, tmp_path, need_filter):
    """Measured (design §4): a sample at alpha 0.10 scores 0.0000% on a title that
    rendered perfectly. The gate says so instead of failing it."""
    ...
```

Fill each in against `test_look.py`'s existing `deliver()` scaffolding
(`_passing_report`, the `ReelReport` binding, the `LookSpec` construction).

- [ ] **Step 2: Run them**

Run: `.venv/bin/python -m pytest tests/integration/test_look.py -q -m integration`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_look.py
git commit -m "$(cat <<'EOF'
test(look): real-ffmpeg proofs for the titles gate, each with a control

Three, and the middle one is the load-bearing one: a max-depth vignette with no
title at all, pinned to keep reading as "no title". That is the case the obvious
metric gets wrong — 9.58% of the band past a 60-code master-vs-delivered bar,
more than a real title scores — so the pin is against the simplification, not
against a regression in the code as written.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: mutation battery, full suite, docs

**Files:**
- Modify: `docs/backlog.md`, `docs/build-status.md`, `CLAUDE.md`,
  `skills/titles/SKILL.md`
- Verify only: everything else

- [ ] **Step 1: Run the mutation battery**

Each row: apply the mutation by rewriting the file content, run the named test,
confirm it reddens, restore by rewriting. **`PYTHONDONTWRITEBYTECODE=1` on every
invocation.**

| # | Mutation | Must redden |
|---|---|---|
| 1 | `TITLE_INK_DELTA` 40 → 200 | the real-ffmpeg pass case |
| 2 | `TITLE_INK_DELTA` 40 → 2 | `test_title_evidence_ignores_a_multiplicative_darkening` |
| 3 | `TITLE_MIN_FRACTION` → 0.5 | the real-ffmpeg pass case |
| 4 | `TITLE_MIN_FRACTION` → 0.0 | `test_evaluate_titles_fails_a_title_that_never_rendered` |
| 5 | `TITLE_BAND_PAD` 0.6 → 0.0 | a band-containment test |
| 6 | `title_evidence` drops the `- b` master term | `test_title_evidence_ignores_picture_motion` |
| 7 | `title_evidence` uses `.mean(axis=2)` not `.max` | a metric unit (worst channel matters) |
| 8 | `evaluate_titles` takes `min` not `max` over witnesses | `test_evaluate_titles_takes_the_best_witness` |
| 9 | `evaluate_titles` reports a skipped probe as `"pass"` | `test_evaluate_titles_reports_a_skipped_probe_as_not_checked` |
| 10 | `_title_times` drops the fade clamp on `lo` | `test_title_times_clamps_both_ends_out_of_the_fade` |
| 11 | `_title_times` drops the fade clamp on `hi` | the same |
| 12 | `_title_times` witnesses ignore `covered` | `test_title_times_witness_avoids_every_titles_window` |
| 13 | `ink_extent` drops the stair `drop` term | `test_ink_extent_adds_the_staircases_drop` |
| 14 | `zone_overflow`'s `>` becomes `>=` | `test_zone_overflow_passes_an_ordinary_bottom_title` |
| 15 | `zone_overflow` returns `""` unconditionally | `test_build_filterchain_refuses_a_title_that_leaves_the_zone` |
| 16 | `TrackMeta.__post_init__` deleted | `test_track_meta_refuses_a_degraded_rung_outside_the_vocabulary` |

Row 14 is the one to watch: the ordinary bottom title sits **exactly** on the
zone edge, so a `>=` must be shown to refuse it. If any row survives, that is a
coverage hole — write the test that closes it, do not soften the row.

- [ ] **Step 2: Full suite**

Run: `find . -name __pycache__ -prune -exec rm -rf {} + ; .venv/bin/python -m pytest -q`
Expected: green, no golden moved.

- [ ] **Step 3: Docs sync**

- `docs/backlog.md` — close "titles in the look gate"; move the Titles group's
  "full pixel-level safe-zone gate" to `◐` (the titles half lands, the subject
  half is still the Reel/QC row); **reword line 161's "already exist unwired"**
  per design §6; file the six §9 deferrals.
- `docs/build-status.md` — the Done entry with the measured numbers.
- `CLAUDE.md` — two Quick Reference rows (design + plan).
- `skills/titles/SKILL.md` — the staircase refusal and its remedies; the gate's
  existence and what `not-checked` means when the author sees it.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
docs: the titles gate's queue, and a backlog line that said the opposite

Closes "titles in the look gate" and files the six holes the slice leaves named
rather than closed — the gate reads no text, a wrong font passes, a
one-character title clears the floor by only 1.9x.

Also corrects docs/backlog.md's claim that carve.track_displacements and
subject_curve "already exist unwired". Both are called from intake.py and have
been the motion sensor since 2026-08-06. What the row meant is that neither is
reachable from lib/anchors, which runs at pacing time with no tracking data —
a subsystem boundary, not dead code, and the sentence read as the opposite.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage.** §1 → Tasks 2-3 and 6. §2's metric → Task 2. §3's constants →
Task 2, each with its measurement in the comment. §4's fade clamps → Task 3,
proven by rows 10-11. §5's staircase → Tasks 0-1 and 4. §6's orphans → Task 5.
§9's deferrals → Task 7.

**Placeholder scan.** Tasks 4 and 6 carry `...` in their test bodies. That is
deliberate and bounded: both must be shaped against scaffolding already in those
files (`build_titles`' existing fixture, `test_look.py`'s `_passing_report` and
`ReelReport` binding), and inventing a second copy of it here would be the
"verbatim duplication" the review rubric treats as a defect. Every assertion
that carries meaning is written out. No other step has one.

**Type consistency.** `ink_extent` returns fractions everywhere; only
`_title_band` multiplies by `h`. `TitleProbe.band` is rows, and its docstring
says why the unit changes there. `zone_overflow` returns `str` in both readers.
`evaluate`'s `titles` parameter changes type from `bool` to
`Sequence[TitleProbe]` — grep for every caller before Task 2's commit; there is
one in `deliver` and some in tests.

**The weak point.** Task 3's `_verify_look` rewrite is the largest single diff
and it touches a function whose docstring is already load-bearing (three
separate review findings are recorded in it). The risk is dropping one of those
behaviours while adding the titles branch — specifically `last_frame_rgb` rather
than a computed timestamp, and the two files' fps being probed separately. Both
survive verbatim in the replacement above; a reviewer should check them by name.
