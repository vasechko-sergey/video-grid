# Cinematic look — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a reel-level `EDL.look` (a plateau vignette + a bookend fade) rendered in
`deliver`'s one encode with a measured visibility proof each, plus the three
remaining #18 leftovers — the audio half of the fade, `highlight_red`, and
`outline-bold`.

**Architecture:** the look rides the `EDL → ReelManifest → deliver` wire that
`platform` already uses. A new pure `scripts/lib/look.py` owns the mask
expression, the fade filters and the chain **order**; `deliver` owns the mask
*file* and picks between `-vf` (no vignette, byte-identical argv to today) and
`-filter_complex` (vignette — the mask is a second input). The audio bookend
moves off `mix`'s music fragment onto the mixed stem so ambient and SFX fade with
the picture.

**Tech Stack:** Python 3 stdlib + dataclasses, ffmpeg via `scripts/lib/ffbin` +
`scripts/lib/proc`, pytest. No new dependencies.

**Design:** [docs/specs/2026-08-13-cinematic-look-design.md](../specs/2026-08-13-cinematic-look-design.md)
— read §1–§5 and §8 before starting. Section references below point into it.

## Global Constraints

- **Python is `.venv/bin/python`.** Scripts run as modules (`pythonpath = .` in
  `pytest.ini`): `.venv/bin/python -m scripts.deliver`, never `python scripts/deliver.py`.
- **Never call `ffmpeg`/`ffprobe` by bare name.** Always `ffbin.ffmpeg()` /
  `ffbin.ffprobe()`. An AST scan (`tests/lib/test_landmine_scan.py`) fails the
  build on a bare binary literal.
- **Always run ffmpeg through `proc.run`**, never `subprocess.run` directly —
  `proc.run` is the always-on landmine guard. Only `scripts/lib/proc.py` may
  import `subprocess` (machine-checked).
- **Fail loud with a remedy.** Every `raise ValueError` says what was wrong AND
  what to do about it. See `docs/coding-standards.md`.
- **Imports at the top of the file.** No function-local imports.
- **Whole-object asserts** in tests where a dataclass is involved
  (`assert spec == LookSpec(vignette=0.3, fade=0.5)`), not field-by-field. See
  `docs/testing-guide.md`.
- **Do not commit with `--amend`.** Post-review fixes are separate follow-up commits.
- **Do not run installers** (`brew`, `pip install`, `setup.sh`). The runtime is
  already installed. Verification is read-only plus `pytest`.
- **Do not run `git checkout --`, `git restore`, `git reset --hard`, or `git stash`.**
- **Do not push.** Commit to the current branch only.
- §12 landmines that bind this slice: a filtergraph value containing a comma must
  be single-quoted *inside* the `-vf`/`-filter_complex` string; `-ss` goes AFTER
  `-i` for frame-accurate video cuts; `lutrgb` is banned.

**Branch:** `feat/cinematic-look` (already created, off `main` at `d422525`).

---

## File structure

| file | responsibility |
|---|---|
| `scripts/lib/look.py` | **new.** `LookSpec`, the four constants, `mask_expr`, `fade_args`, `chain`. Pure — no IO, no ffmpeg. Owns the §4 chain order. |
| `scripts/lib/lint.py` | +`_blend_multiply`, the sixth argv check (§8.1) |
| `scripts/lib/edl.py` | `EDL.look` carrier + round-trip + markdown row; `EDLEpisode.highlight_red` |
| `scripts/lib/models.py` | `ReelManifest.look` carrier; `ReframeSpec.highlight_red` |
| `scripts/lib/color.py` | `highlight_red_arg` + its two constants; `grade_chain(highlight_red=)` |
| `scripts/lib/titles.py` | `outline-bold` in `STYLES` + `_STYLE_FRAGMENTS` |
| `scripts/lib/moodpreset.py` | `MoodPreset.look` + the five preset rows |
| `scripts/deliver.py` | the mask render + the `-vf` / `-filter_complex` branch |
| `scripts/mix.py` | the fade moves onto the mixed stem; `_FADE` becomes `mix(fade=)` |
| `scripts/build_reel.py` | thread `rm.look` into `deliver` and its fade into `mix` |
| `scripts/edl_to_reel.py` | copy `edl.look` onto the `ReelManifest` |
| `scripts/edit_plan.py` | resolve the preset's look when unauthored; log which won |
| `scripts/process_episode.py` | pass `highlight_red` into the grade |
| `tests/lib/test_look.py` | **new.** the pure core |
| `tests/integration/test_look.py` | **new.** the six real-ffmpeg visibility proofs |

---

## Task 0: `scripts/lib/look.py` — the pure core

**Files:**
- Create: `scripts/lib/look.py`
- Test: `tests/lib/test_look.py` (new)

**Interfaces:**
- Produces: `LookSpec(vignette: float = 0.0, fade: float = 0.0)` with
  `.has_vignette -> bool`, `.to_dict() -> dict`, `LookSpec.from_dict(d) -> LookSpec`;
  `mask_expr(vignette: float) -> str`; `fade_args(fade: float, dur: float) -> list[str]`;
  `chain(spec: LookSpec | None, dur: float, titles: str = "") -> list[str]`;
  constants `LOOK_VIGNETTE_MAX = 0.6`, `LOOK_FADE_MAX = 2.0`,
  `VIGNETTE_PLATEAU = 0.55`, `VIGNETTE_FALLOFF = 0.45`.

- [x] **Step 1: Write the failing tests**

Create `tests/lib/test_look.py`:

```python
import pytest

from scripts.lib.look import (LOOK_FADE_MAX, LOOK_VIGNETTE_MAX, LookSpec, chain,
                              fade_args, mask_expr)


def test_default_is_no_look():
    s = LookSpec()
    assert s == LookSpec(vignette=0.0, fade=0.0)
    assert s.has_vignette is False


def test_has_vignette_is_the_second_input_predicate():
    assert LookSpec(vignette=0.35).has_vignette is True
    assert LookSpec(fade=0.5).has_vignette is False


def test_round_trip():
    s = LookSpec(vignette=0.3, fade=0.8)
    assert LookSpec.from_dict(s.to_dict()) == s
    assert s.to_dict() == {"vignette": 0.3, "fade": 0.8}


def test_from_dict_rejects_a_non_object():
    with pytest.raises(ValueError, match="look must be an object"):
        LookSpec.from_dict([0.3, 0.8])


@pytest.mark.parametrize("v", [-0.1, 0.61, True, False, "0.3"])
def test_vignette_refuses_out_of_band(v):
    # False is the discriminating bool case here: False == 0, which IS inside
    # [0, 0.6], so only the bool exclusion rejects it. True == 1 is outside the band
    # and would be refused by the range check alone.
    with pytest.raises(ValueError, match="vignette"):
        LookSpec(vignette=v)


@pytest.mark.parametrize("f", [-0.1, 2.1, True, "0.5"])
def test_fade_refuses_out_of_band(f):
    with pytest.raises(ValueError, match="fade"):
        LookSpec(fade=f)


def test_mask_expr_carries_the_measured_plateau_and_the_strength():
    e = mask_expr(0.35)
    assert e.startswith("format=rgba,geq=r=0:g=0:b=0:a='")
    assert "-0.5500" in e          # VIGNETTE_PLATEAU, the identity radius
    assert "/0.4500" in e          # VIGNETTE_FALLOFF, the rest of the ramp
    assert "255*0.3500*" in e      # the corner alpha cap
    assert e.endswith("'")


def test_mask_expr_refuses_zero_because_the_caller_must_skip_it():
    with pytest.raises(ValueError, match="mask_expr"):
        mask_expr(0.0)


def test_mask_expr_refuses_past_the_ceiling():
    with pytest.raises(ValueError, match=str(LOOK_VIGNETTE_MAX)):
        mask_expr(0.7)


def test_fade_args_are_a_bookend_pair():
    assert fade_args(0.5, 30.0) == ["fade=t=in:st=0:d=0.500",
                                    "fade=t=out:st=29.500:d=0.500"]


def test_fade_args_off_at_zero():
    assert fade_args(0.0, 30.0) == []


def test_fade_args_refuse_overlapping_fades():
    with pytest.raises(ValueError, match="would overlap"):
        fade_args(0.8, 1.5)


def test_chain_puts_the_fade_after_the_titles():
    # design §4: measured — fade last is what takes the TITLE to black with the
    # picture. Reversing these two lines is a real defect, not a style choice.
    assert chain(LookSpec(fade=0.5), 30.0, "drawtext=x=1") == [
        "drawtext=x=1", "fade=t=in:st=0:d=0.500", "fade=t=out:st=29.500:d=0.500"]


def test_chain_is_empty_with_no_look_and_no_titles():
    assert chain(None, 30.0) == []
    assert chain(LookSpec(), 30.0) == []


def test_chain_carries_titles_alone_when_the_look_is_absent():
    assert chain(None, 30.0, "drawtext=x=1") == ["drawtext=x=1"]


def test_chain_does_not_carry_the_overlay():
    # the vignette needs a SECOND INPUT, so deliver wires it by label; a chain
    # that emitted `overlay` would produce a graph with a dangling input
    assert "overlay" not in ",".join(chain(LookSpec(vignette=0.4, fade=0.5), 30.0))


def test_fade_ceiling_is_two_seconds():
    assert LOOK_FADE_MAX == 2.0
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_look.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.look'`

- [x] **Step 3: Write the implementation**

Create `scripts/lib/look.py`:

```python
"""The reel's cinematic look — a plateau vignette and a bookend fade, applied in
deliver's ONE encode (design docs/specs/2026-08-13-cinematic-look-design.md).

Pure: validation and string assembly. No IO, no ffmpeg. This module owns the mask
EXPRESSION and the chain ORDER; deliver owns the mask FILE and the second input it
rides on.

Why a mask and not ffmpeg's `vignette` filter: the built-in is a cos^4 lens model
with NO plateau, so on a 9:16 canvas it is a top-and-bottom dimmer, not a vignette
— measured, the sky band above a subject sits at 0.637 of centre at the default
angle while the corner is only at 0.413 (design §2.1). The mask below holds an
untouched plateau to 55% of the corner radius and darkens only past it, and a
one-shot mask + overlay renders it 26x cheaper than the equivalent per-frame geq
(design §2.2)."""
from dataclasses import dataclass

LOOK_VIGNETTE_MAX = 0.6      # past this the corners read as a black border, not a vignette
LOOK_FADE_MAX = 2.0          # seconds per end; a 2.0s bookend already needs a >=4s reel
VIGNETTE_PLATEAU = 0.55      # identity radius, as a fraction of the corner distance
VIGNETTE_FALLOFF = 0.45      # 1 - PLATEAU: the rest of the ramp. Named, not inlined,
                             # because the mask expression divides by it and a 0 here
                             # would be a division by zero rather than "no falloff".
_CORNER = 1.41421356         # sqrt(2) — normalizes the corner distance to 1


def _num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@dataclass
class LookSpec:
    """The reel's finish. Both fields are 0 at their identity, and 0 means the
    filter is NOT EMITTED — the same convention color.white_balance uses, so a
    LookSpec() renders exactly what this repo rendered before looks existed.

    Distinct from None on its carriers: `EDL.look is None` means never authored
    (the mood preset fills it), `EDL.look == LookSpec()` means authored as no look
    (the preset does not get to override it)."""
    vignette: float = 0.0    # corner darkening as a fraction, 0 = off
    fade: float = 0.0        # bookend fade seconds per end, 0 = off

    def __post_init__(self) -> None:
        if not _num(self.vignette) or not 0.0 <= self.vignette <= LOOK_VIGNETTE_MAX:
            raise ValueError(
                f"LookSpec.vignette must be a number in [0, {LOOK_VIGNETTE_MAX}] — it is how "
                f"far the CORNERS are darkened (0 = no vignette), and past the ceiling they "
                f"read as a black border rather than a falloff. Got {self.vignette!r}")
        if not _num(self.fade) or not 0.0 <= self.fade <= LOOK_FADE_MAX:
            raise ValueError(
                f"LookSpec.fade must be a number of seconds in [0, {LOOK_FADE_MAX}] — it is "
                f"the bookend fade at EACH end (0 = no fade), and a 2s bookend already needs "
                f"a 4s reel. Got {self.fade!r}")
        self.vignette, self.fade = float(self.vignette), float(self.fade)

    @property
    def has_vignette(self) -> bool:
        """Whether deliver needs a second input. The one predicate that decides
        between the -vf and the -filter_complex shape."""
        return self.vignette > 0.0

    def to_dict(self) -> dict:
        return {"vignette": self.vignette, "fade": self.fade}

    @classmethod
    def from_dict(cls, d: dict) -> "LookSpec":
        if not isinstance(d, dict):
            raise ValueError(f"look must be an object with vignette/fade fields, got "
                             f"{type(d).__name__} — see the edit-plan skill for the shape")
        return cls(vignette=d.get("vignette", 0.0), fade=d.get("fade", 0.0))


def mask_expr(vignette: float) -> str:
    """The geq that fills a one-frame RGBA vignette mask: black pixels whose ALPHA
    ramps from 0 on the plateau to 255*vignette at the corners, smoothstepped.

    Alpha and not luma: `overlay` composites through alpha and leaves the plateau
    exactly untouched, while `blend=all_mode=multiply` with a single-plane mask
    multiplies CHROMA as well and moves U/V by a measured mean of 63 (design §8.1).

    Refuses 0 rather than returning "": a caller with no vignette must not render a
    mask file at all, and a silently-empty expression would produce a fully
    transparent PNG plus a pointless second input."""
    if not _num(vignette) or not 0.0 < vignette <= LOOK_VIGNETTE_MAX:
        raise ValueError(
            f"mask_expr needs a vignette in (0, {LOOK_VIGNETTE_MAX}] — 0 means there is no "
            f"mask to render and the caller must skip it (LookSpec.has_vignette is that "
            f"test). Got {vignette!r}")
    ramp = (f"st(1,clip((hypot((X-W/2)/(W/2),(Y-H/2)/(H/2))/{_CORNER}"
            f"-{VIGNETTE_PLATEAU:.4f})/{VIGNETTE_FALLOFF:.4f},0,1))")
    return (f"format=rgba,geq=r=0:g=0:b=0:"
            f"a='{ramp};255*{vignette:.4f}*ld(1)*ld(1)*(3-2*ld(1))'")


def fade_args(fade: float, dur: float) -> list[str]:
    """The bookend pair, or [] at 0. Refuses a fade that would meet itself in the
    middle — two overlapping ramps multiply into a reel that never reaches full
    brightness, which looks like a broken encode rather than a style."""
    # Type check BEFORE the zero shortcut: False == 0 in Python, so an `if fade == 0`
    # placed first would accept a bool and return [] instead of refusing it. color.py's
    # black_point/shadow_red/dip all order these two the same way, for the same reason.
    if not _num(fade) or not 0.0 <= fade <= LOOK_FADE_MAX:
        raise ValueError(
            f"fade_args needs a fade in [0, {LOOK_FADE_MAX}] seconds — the same band "
            f"LookSpec enforces, re-checked here because this function is public and a "
            f"direct caller does not go through the dataclass. Got {fade!r}")
    if fade == 0:
        return []
    if not _num(dur) or dur <= 0:
        raise ValueError(f"fade_args needs a positive reel duration, got {dur!r}")
    if 2 * fade > dur:
        raise ValueError(
            f"a {fade}s fade at each end of a {dur}s reel would overlap in the middle — "
            f"lower EDL.look.fade to at most {dur / 2:.2f}s or cut a longer reel")
    return [f"fade=t=in:st=0:d={fade:.3f}",
            f"fade=t=out:st={dur - fade:.3f}:d={fade:.3f}"]


def chain(spec: "LookSpec | None", dur: float, titles: str = "") -> list[str]:
    """The video filters deliver applies AFTER the vignette overlay, in the ONE
    correct order: the title drawtext, then the bookend fade.

    The fade is last and that is MEASURED, not a preference: with it last the first
    delivered frame reads 0.0 — the title goes to black with the picture. Put it
    before the drawtext and the title burns on at full brightness over a black
    frame (design §4).

    The vignette overlay is deliberately NOT in this list: it needs a second input,
    so deliver wires it by label and prepends it. An empty list means deliver emits
    no video-filter slot at all, which is what keeps a look-less delivery's argv
    byte-identical to what it was before this module existed."""
    parts: list[str] = []
    if titles:
        parts.append(titles)
    if spec is not None:
        parts.extend(fade_args(spec.fade, dur))
    return parts
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_look.py -q`
Expected: PASS, 15 tests.

- [x] **Step 5: Commit**

```bash
git add scripts/lib/look.py tests/lib/test_look.py
git commit -m "feat(look): LookSpec + the plateau mask expression + the chain order"
```

---

## Task 1: the sixth lint check — `blend=all_mode=multiply`

**Files:**
- Modify: `scripts/lib/lint.py` (add `_blend_multiply`, wire into `check_argv`)
- Test: `tests/lib/test_lint.py`

**Interfaces:**
- Consumes: nothing from Task 0.
- Produces: `lint._blend_multiply(cmd: list[str]) -> list[str]`, and
  `lint.check_argv` now runs six checks. Every later ffmpeg call in this slice is
  guarded by it through `proc.run`.

**Why first:** the measured landmine (design §8.1) is the exact mistake the rest of
this slice could make. The guard goes in before the code it guards.

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_lint.py`:

```python
def test_blend_all_mode_multiply_is_flagged():
    out = lint.check_argv(["ffmpeg", "-i", "a.mp4", "-loop", "1", "-i", "m.png",
                           "-filter_complex",
                           "[1:v]format=gray[m];[0:v][m]blend=all_mode=multiply:shortest=1[v]",
                           "out.mp4"])
    assert len(out) == 1
    assert "all_mode=multiply" in out[0]
    assert "chroma" in out[0]
    assert "overlay" in out[0]        # the message must name the working alternative


def test_per_plane_blend_multiply_is_legal():
    # c0_mode targets ONE plane, which is the correct way to multiply luma only
    assert lint.check_argv(["ffmpeg", "-i", "a.mp4", "-filter_complex",
                            "[0][1]blend=c0_mode=multiply[v]", "out.mp4"]) == []


def test_other_blend_modes_are_legal():
    assert lint.check_argv(["ffmpeg", "-i", "a.mp4", "-filter_complex",
                            "[0][1]blend=all_mode=screen[v]", "out.mp4"]) == []


def test_the_overlay_route_is_clean():
    assert lint.check_argv(["ffmpeg", "-y", "-i", "a.mp4", "-loop", "1", "-i", "m.png",
                            "-filter_complex", "[0:v][1:v]overlay=shortest=1[v]",
                            "-map", "[v]", "out.mp4"]) == []
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_lint.py -x -q -k blend`
Expected: FAIL — the first test gets `[]` where it wants one violation.

- [x] **Step 3: Implement**

In `scripts/lib/lint.py`, after the `SYNTH_SOURCES` block, add the pattern
constant:

```python
# design §12 (2026-08-13 §8.1): `blend=all_mode=multiply` against a single-plane
# mask multiplies the CHROMA planes too. U and V sit at 128 for neutral, so scaling
# them by mask/255 drags every pixel toward 0 — measured mean |dU| 63.44, |dV| 62.76
# against the same darkening done through alpha. The luma looks right, which is what
# makes it silent. `all_mode` only: `c0_mode`/`c1_mode` name ONE plane and are the
# correct spelling when a per-plane multiply is really what you want.
_BLEND_MULT_RE = re.compile(r"(?:^|[,;\]])blend=[^,;\[]*\ball_mode=multiply\b")
```

Then, next to the other checkers, add:

```python
def _blend_multiply(cmd: list[str]) -> list[str]:
    """Flag an all-plane multiply blend — it destroys chroma silently."""
    # lowercase "chroma" in the MESSAGE on purpose: the Step-1 test asserts
    # `"chroma" in out[0]` and Python's `in` is case-sensitive, so a capitalised
    # word here fails this task's own test. The comment above may shout; the
    # user-facing string matches its five neighbours and does not.
    return [f"blend=all_mode=multiply in {a!r} — design §12: an all-plane multiply "
            "scales the chroma planes as well as luma (measured mean |dU| 63 against "
            "the same darkening through alpha), so the picture keeps roughly the right "
            "brightness and loses its colour. Composite an RGBA mask with `overlay` "
            "instead, or name one plane with c0_mode=multiply."
            for a in cmd if _BLEND_MULT_RE.search(a)]
```

Wire it into the tuple in `check_argv`:

```python
    for check in (_banned_filters, _seek_order, _unbounded_source, _drawtext_font,
                  _zoompan_defaults, _blend_multiply):
```

- [x] **Step 4: Run to verify they pass, and that nothing else moved**

Run: `.venv/bin/python -m pytest tests/lib/test_lint.py tests/lib/test_proc.py tests/lib/test_landmine_scan.py -q`
Expected: PASS, all of them.

- [x] **Step 5: Commit**

```bash
git add scripts/lib/lint.py tests/lib/test_lint.py
git commit -m "feat(lint): sixth check — blend=all_mode=multiply destroys chroma"
```

---

## Task 2: the carriers — `EDL.look` and `ReelManifest.look`

**Files:**
- Modify: `scripts/lib/edl.py` (`EDL.look`, validation, `from_dict`, `to_dict`, `to_markdown`)
- Modify: `scripts/lib/models.py` (`ReelManifest.look`, validation, `from_dict`, `to_dict`)
- Test: `tests/lib/test_edl.py`, `tests/lib/test_models.py`

**Interfaces:**
- Consumes: `scripts.lib.look.LookSpec` (Task 0).
- Produces: `EDL.look: LookSpec | None = None` and
  `ReelManifest.look: LookSpec | None = None`, both round-tripping through
  `to_dict`/`from_dict` as a nested object or `null`.

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_edl.py` (reuse whatever episode factory the file already
has; the snippet below assumes a local helper named `_ep()` — if the file names it
differently, use that name):

```python
def test_edl_look_defaults_to_none_meaning_never_authored():
    e = EDL(episodes=(_ep(),))
    assert e.look is None
    assert e.to_dict()["look"] is None


def test_edl_look_round_trips():
    e = EDL(episodes=(_ep(),), look=LookSpec(vignette=0.3, fade=0.8))
    assert EDL.from_dict(e.to_dict()).look == LookSpec(vignette=0.3, fade=0.8)


def test_edl_look_accepts_an_authored_no_look():
    # LookSpec() is NOT None: it means "the author said no look", which the mood
    # preset must not override
    e = EDL.from_dict({"episodes": [_ep().to_dict()], "look": {"vignette": 0, "fade": 0}})
    assert e.look == LookSpec()


def test_edl_look_refuses_a_wrong_type():
    with pytest.raises(ValueError, match="EDL.look must be a LookSpec"):
        EDL(episodes=(_ep(),), look={"vignette": 0.3})


def test_edl_markdown_prints_the_look_only_when_set():
    assert "Look" not in EDL(episodes=(_ep(),)).to_markdown()
    md = EDL(episodes=(_ep(),), look=LookSpec(vignette=0.3, fade=0.8)).to_markdown()
    assert "- **Look:** vignette 0.30 · fade 0.80s" in md
```

Add `from scripts.lib.look import LookSpec` to the test file's imports.

Append to `tests/lib/test_models.py`:

```python
def test_reel_manifest_look_round_trips():
    rm = ReelManifest(episodes=[_reel_ep()], target_dur=10.0,
                      look=LookSpec(vignette=0.25, fade=0.5))
    assert ReelManifest.from_dict(rm.to_dict()).look == LookSpec(vignette=0.25, fade=0.5)


def test_reel_manifest_look_defaults_to_none():
    rm = ReelManifest(episodes=[_reel_ep()], target_dur=10.0)
    assert rm.look is None
    assert rm.to_dict()["look"] is None


def test_reel_manifest_look_refuses_a_wrong_type():
    with pytest.raises(ValueError, match="ReelManifest.look must be a LookSpec"):
        ReelManifest(episodes=[_reel_ep()], target_dur=10.0, look=0.3)
```

(`_reel_ep()` stands for whatever `ReelEpisode` factory `tests/lib/test_models.py`
already uses; keep the file's existing helper.)

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py tests/lib/test_models.py -x -q -k look`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'look'`

- [x] **Step 3: Implement**

`scripts/lib/edl.py` — add the import at the top:

```python
from scripts.lib.look import LookSpec
```

Add the field to `EDL`, after `platform`:

```python
    look: LookSpec | None = None   # design 2026-08-13 §1. None = NEVER AUTHORED, so
                                   # edit_plan fills it from the mood preset; LookSpec()
                                   # means the author said "no look" and the preset must
                                   # not override it. Spent by edl_to_reel on
                                   # ReelManifest.look and rendered in deliver's one
                                   # encode — no gate ever sees it (design §11.1).
```

Add validation in `__post_init__`, beside the `variety` check:

```python
        if self.look is not None and not isinstance(self.look, LookSpec):
            raise ValueError(f"EDL.look must be a LookSpec or None, got "
                             f"{type(self.look).__name__} — re-run edit_plan build")
```

In `from_dict`, beside `variety`:

```python
                   look=LookSpec.from_dict(d["look"]) if d.get("look") is not None else None,
```

Note the explicit `is not None` and **not** a truthiness test. Get the reason
right, because the obvious one is wrong: `{"vignette": 0, "fade": 0}` is a
NON-EMPTY dict and therefore truthy, so it survives either spelling. The input
that actually discriminates is `"look": {}` — an empty object, which is falsy.
Under `is not None` it resolves to `LookSpec()` (authored, no look); under
truthiness it collapses to `None` (never authored) and the mood preset then
overrides a decision the author made. `EDL.from_json` is a documented
hand-authored front door, so `{}` is reachable.

In `to_dict`, beside `"variety"`:

```python
             "look": self.look.to_dict() if self.look is not None else None,
```

In `to_markdown`, right after the `platform` line:

```python
        if self.look is not None and (self.look.vignette or self.look.fade):
            lines.append(f"- **Look:** vignette {self.look.vignette:.2f} · "
                         f"fade {self.look.fade:.2f}s")
```

`scripts/lib/models.py` — add `from scripts.lib.look import LookSpec` at the top,
then the field on `ReelManifest` after `platform`:

```python
    look: LookSpec | None = None       # reel finish rendered in deliver (design 2026-08-13);
                                       # None = none authored
```

Validation in `__post_init__`, after the `platform` check:

```python
        if self.look is not None and not isinstance(self.look, LookSpec):
            raise ValueError(f"ReelManifest.look must be a LookSpec or None, got "
                             f"{type(self.look).__name__} — edl_to_reel builds it from "
                             f"EDL.look")
```

`from_dict`, after `platform=`:

```python
                   look=LookSpec.from_dict(d["look"]) if d.get("look") is not None else None,
```

`to_dict`, after `"platform"`:

```python
                "look": self.look.to_dict() if self.look is not None else None,
```

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py tests/lib/test_models.py tests/lib/test_edl_to_reel.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/lib/edl.py scripts/lib/models.py tests/lib/test_edl.py tests/lib/test_models.py
git commit -m "feat(look): EDL.look and ReelManifest.look carriers"
```

---

## Task 3: `deliver` renders the look

**Files:**
- Modify: `scripts/deliver.py`
- Test: `tests/test_deliver.py`

**Interfaces:**
- Consumes: `look.LookSpec`, `look.mask_expr`, `look.chain` (Task 0);
  `assembly.probe_stream`, `assembly.probe_duration`.
- Produces: `deliver(..., look: LookSpec | None = None)`; the mask is written to
  `<out_dir>/look_mask.png`.

**The two shapes, and the input-index trap.** Without a vignette the video filters
stay in `-vf` and the argv is byte-for-byte what it is today. With one, the mask is
`-loop 1 -i <mask>` — **input 1** — which pushes the audio stem to **input 2**. The
`-map` for audio must follow.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_deliver.py`. The file already monkeypatches `proc.run` to
capture argv — reuse that pattern; the snippet below assumes a `calls` list
fixture named `run_calls` and a `_report()` helper that builds a passing
`ReelReport` with a matching `master_digest`. Use whatever the file already has.

```python
def test_no_look_argv_is_unchanged(tmp_path, run_calls, ...):
    deliver.deliver(master, REEL_H264, str(tmp_path), "note", report)
    cmd = run_calls[-1]
    assert "-filter_complex" not in cmd
    assert "-vf" not in cmd
    assert not (tmp_path / "look_mask.png").exists()


def test_fade_only_look_stays_on_the_vf_slot(tmp_path, run_calls, ...):
    deliver.deliver(master, REEL_H264, str(tmp_path), "note", report,
                    look=LookSpec(fade=0.5))
    cmd = run_calls[-1]
    assert "-filter_complex" not in cmd
    assert cmd[cmd.index("-vf") + 1].startswith("fade=t=in:st=0:d=0.500")
    assert not (tmp_path / "look_mask.png").exists()


def test_vignette_renders_a_mask_and_moves_to_filter_complex(tmp_path, run_calls, ...):
    deliver.deliver(master, REEL_H264, str(tmp_path), "note", report,
                    look=LookSpec(vignette=0.35))
    mask_cmd, enc = run_calls[-2], run_calls[-1]
    # the mask is rendered at the MASTER's probed dims, one frame
    assert "nullsrc=s=1080x1920:d=1:r=1" in mask_cmd
    assert "format=rgba,geq=r=0:g=0:b=0:a=" in mask_cmd[mask_cmd.index("-vf") + 1]
    assert mask_cmd[mask_cmd.index("-frames:v") + 1] == "1"
    # the encode takes the mask as input 1 and reads the video from a label
    assert enc[enc.index("-loop") + 1] == "1"
    assert enc[enc.index("-loop") + 2] == "-i"
    assert enc[enc.index("-loop") + 3].endswith("look_mask.png")
    assert enc[enc.index("-filter_complex") + 1].startswith("[0:v][1:v]overlay=shortest=1")
    assert enc[enc.index("-filter_complex") + 1].endswith("[v]")
    assert "-vf" not in enc


def test_audio_input_index_shifts_when_a_mask_is_present(tmp_path, run_calls, ...):
    deliver.deliver(master, REEL_H264, str(tmp_path), "note", report,
                    audio=str(stem), look=LookSpec(vignette=0.35))
    enc = run_calls[-1]
    # master=0, mask=1, audio=2 — mapping 1:a:0 here would mux the PNG
    assert "2:a:0" in enc
    assert "1:a:0" not in enc


def test_audio_input_index_is_one_without_a_mask(tmp_path, run_calls, ...):
    deliver.deliver(master, REEL_H264, str(tmp_path), "note", report, audio=str(stem))
    assert "1:a:0" in run_calls[-1]


def test_titles_and_fade_share_one_slot_in_the_right_order(tmp_path, run_calls, ...):
    # titles first, fade last — the chain order look.chain owns
    deliver.deliver(master, REEL_H264, str(tmp_path), "note", report,
                    titles=str(titles_json), look=LookSpec(fade=0.5))
    graph = run_calls[-1][run_calls[-1].index("-vf") + 1]
    assert graph.index("drawtext") < graph.index("fade=t=in")
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_deliver.py -x -q -k look`
Expected: FAIL — `deliver() got an unexpected keyword argument 'look'`

- [x] **Step 3: Implement**

In `scripts/deliver.py`, extend the imports:

```python
from scripts.lib import assembly, ffbin, look as look_lib, proc, provenance
from scripts.lib.look import LookSpec
```

Add a helper above `deliver`:

```python
def _render_mask(master: str, out_dir: str, vignette: float) -> str:
    """Render the one-frame RGBA vignette mask at the MASTER's real pixels.

    Probed, never derived from a config: the delivery's dimensions are what the
    episodes actually produced, and a mask built at a config's idea of the canvas
    would letterbox the whole reel silently. No cache — this is one frame, and a
    stale mask keyed to the wrong dimensions is exactly the failure not caching
    avoids (design §11.6)."""
    si = assembly.probe_stream(master)
    mask = str(Path(out_dir) / "look_mask.png")
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", f"nullsrc=s={si.w}x{si.h}:d=1:r=1",
              "-vf", look_lib.mask_expr(vignette), "-frames:v", "1", mask])
    return mask
```

Change the signature:

```python
def deliver(master: str, profile: ExportProfile, out_dir: str, changelog: str,
            report: ReelReport, *, audio: str | None = None, titles: str | None = None,
            platform: str = "", look: LookSpec | None = None,
            run_provenance: dict | None = None) -> str:
```

Add to the docstring, after the `platform` sentence:

```
    With `look` (design 2026-08-13), a plateau vignette and/or a bookend fade ride
    this same encode. A vignette needs a second input (the mask), so the video
    filters move from -vf into -filter_complex and the audio stem — when there is
    one — becomes input 2 rather than input 1. Without a vignette the argv is
    byte-for-byte what it was before looks existed.
```

Replace the `vf` block and the two `proc.run` calls with:

```python
    # Titles and the look share ONE video-filter slot (§5.16 + design 2026-08-13 §4):
    # build_filterchain writes each title's text to a title_i.txt sidecar in out_dir
    # and returns a drawtext chain; look.chain appends the bookend fade AFTER it, so
    # a title goes to black with the picture. ExportProfile.args() emits no -vf/scale,
    # so nothing clobbers this (last -vf wins in ffmpeg — the §12 silent-drop flavor).
    title_chain = ""
    if titles is not None:
        title_chain = build_filterchain(Titles.from_json(titles), out_dir, platform=platform)
    dur = assembly.probe_duration(master) if (look is not None and look.fade) else 0.0
    parts = look_lib.chain(look, dur, title_chain)
    mask_in: list[str] = []
    graph: list[str] = []
    vmap: list[str] = []
    if look is not None and look.has_vignette:
        mask_in = ["-loop", "1", "-i", _render_mask(master, out_dir, look.vignette)]
        graph = ["-filter_complex",
                 ",".join(["[0:v][1:v]overlay=shortest=1", *parts]) + "[v]"]
        vmap = ["-map", "[v]"]
    elif parts:
        graph = ["-vf", ",".join(parts)]
    n = _next_version(out_dir, profile.container)
    out = str(Path(out_dir) / f"REEL_v{n}.{profile.container}")
    if audio is None:
        proc.run([ffbin.ffmpeg(), "-y", "-i", master, *mask_in, *graph, *vmap,
                  *profile.args(), out])
    else:
        # mux the pre-normalized aac stem: profile audio settings don't apply — we
        # stream-copy to preserve the stem's −14 LUFS — so use video-only args + copy.
        # The stem's input index is 1 normally and 2 behind the mask: `-loop 1 -i mask`
        # occupies index 1, and mapping 1:a:0 there would look for an audio stream in
        # a PNG.
        aidx = 2 if mask_in else 1
        proc.run([ffbin.ffmpeg(), "-y", "-i", master, *mask_in, "-i", audio, *graph,
                  *_video_only_args(profile), *(vmap or ["-map", "0:v:0"]),
                  "-map", f"{aidx}:a:0", "-c:a", "copy", "-shortest", out])
```

Add the CLI flags in `main()`:

```python
    ap.add_argument("--vignette", type=float, default=0.0,
                    help="corner darkening 0..0.6 (0 = off) — the reel's plateau vignette")
    ap.add_argument("--fade", type=float, default=0.0,
                    help="bookend fade seconds per end 0..2.0 (0 = off)")
```

and in the `deliver(...)` call:

```python
                  titles=a.titles, platform=a.platform,
                  look=LookSpec(vignette=a.vignette, fade=a.fade),
```

Note: the CLI always passes a `LookSpec`, and `LookSpec()` at the defaults produces
no filters at all — so the CLI's argv is unchanged when neither flag is given.

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_deliver.py -q`
Expected: PASS, including the pre-existing tests (the byte-identity one is the
regression pin).

- [x] **Step 5: Commit**

```bash
git add scripts/deliver.py tests/test_deliver.py
git commit -m "feat(look): deliver renders the vignette mask and the bookend fade"
```

---

## Task 4: the audio bookend moves onto the mixed stem

**Files:**
- Modify: `scripts/mix.py`
- Test: `tests/test_mix.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (`mix` must not import `look` — it takes a
  number, not a spec).
- Produces: `mix(music, out_dir, dur, segments=None, ambient=True, sfx=False, fade=_FADE)`.

**The defect this fixes.** `_mix_graph` ducks the ambient with
`sidechaincompress` **keyed on the music**. With the fade on the music fragment,
the key falls at the reel's end, the compressor releases, and the nat-sound gets
*louder* exactly as the picture goes black. The SFX whoosh is not faded at all.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_mix.py` (reuse the file's existing `proc.run` capture):

```python
def test_the_fragment_extract_no_longer_carries_the_fade(run_calls, ...):
    mix.mix(music, str(tmp_path), 10.0)
    frag_cmd = run_calls[0]
    assert "afade" not in " ".join(frag_cmd)


def test_the_fade_runs_on_the_mixed_stem_before_loudnorm(run_calls, ...):
    mix.mix(music, str(tmp_path), 10.0, segments=[(seg, 5.0), (seg, 5.0)])
    joined = [" ".join(c) for c in run_calls]
    fade_i = next(i for i, c in enumerate(joined) if "afade=t=in" in c)
    mix_i = next(i for i, c in enumerate(joined) if "sidechaincompress" in c)
    norm_i = next(i for i, c in enumerate(joined) if "loudnorm=I=" in c and "print_format" not in c)
    assert mix_i < fade_i < norm_i     # ambient is ducked, THEN faded, THEN normalized


def test_the_fade_is_a_parameter_and_zero_emits_none(run_calls, ...):
    mix.mix(music, str(tmp_path), 10.0, fade=0.0)
    assert not any("afade" in " ".join(c) for c in run_calls)


def test_a_custom_fade_reaches_both_ends(run_calls, ...):
    mix.mix(music, str(tmp_path), 10.0, fade=0.8)
    af = next(" ".join(c) for c in run_calls if "afade=t=in" in " ".join(c))
    assert "afade=t=in:st=0:d=0.8" in af
    assert "afade=t=out:st=9.2:d=0.8" in af


def test_overlapping_fades_are_refused_with_the_authored_number():
    with pytest.raises(ValueError, match="1.5s"):
        mix.mix(music, str(tmp_path), 2.0, fade=1.5)
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mix.py -x -q`
Expected: FAIL — the fragment extract still carries `afade`.

- [x] **Step 3: Implement**

In `scripts/mix.py`, change the signature and the guard:

```python
def mix(music: MusicSpec, out_dir: str, dur: float,
        segments: list[tuple[str, float]] | None = None,
        ambient: bool = True, sfx: bool = False, fade: float = _FADE) -> str:
```

Docstring addition:

```
    `fade` is the bookend fade at each end, in seconds, and it is applied to the
    MIXED stem rather than to the music fragment — design 2026-08-13 §5. On the
    fragment it faded only the music, and since _mix_graph's sidechaincompress is
    keyed on the music, the duck RELEASED as the music fell and the nat-sound got
    louder exactly as the picture went to black. build_reel passes EDL.look.fade
    here so the audio and video bookends are the same number.
```

Replace the `dur < 2 * _FADE` guard:

```python
    if not isinstance(fade, (int, float)) or isinstance(fade, bool) or fade < 0:
        raise ValueError(f"mix: fade must be a non-negative number of seconds, got {fade!r}")
    if dur < 2 * fade:
        raise ValueError(f"mix: a {fade}s fade at each end of a {dur}s reel would overlap — "
                         f"lower the look's fade to at most {dur / 2:.2f}s or cut a longer reel")
```

Drop the `-af` from the fragment extract:

```python
        proc.run([ffbin.ffmpeg(), "-y", "-accurate_seek", "-ss", f"{music.start_offset}",
                  "-i", music.track, "-t", f"{dur}", frag])
```

and add the fade step after `norm_src` is settled, before `_measure`:

```python
        if fade:
            # AFTER the mix and BEFORE the measurement: everything in the stem fades
            # together, and loudnorm still measures the signal that actually ships.
            faded = os.path.join(d, "faded.wav")
            proc.run([ffbin.ffmpeg(), "-y", "-i", norm_src, "-af",
                      f"afade=t=in:st=0:d={fade},"
                      f"afade=t=out:st={max(0.0, dur - fade)}:d={fade}", faded])
            norm_src = faded
        st = _measure(norm_src)
```

Leave `_FADE = 0.5` where it is — it is now the default, not a constant nobody can
reach. Update its comment:

```python
_FADE = 0.5     # default bookend fade, seconds per end. The DEFAULT, not a fixed
                # value: build_reel overrides it with EDL.look.fade so the audio and
                # video bookends are one number (design 2026-08-13 §5).
```

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_mix.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/mix.py tests/test_mix.py
git commit -m "fix(mix): fade the mixed stem, not the music — the duck released on the tail"
```

---

## Task 5: the drivers thread it

**Files:**
- Modify: `scripts/edl_to_reel.py` (copy `edl.look` onto the manifest)
- Modify: `scripts/build_reel.py` (pass `rm.look` to `deliver`, its fade to `mix`)
- Test: `tests/lib/test_edl_to_reel.py`, `tests/lib/test_build_reel.py`

**Interfaces:**
- Consumes: `EDL.look`, `ReelManifest.look` (Task 2); `deliver(look=)` (Task 3);
  `mix(fade=)` (Task 4).
- Produces: nothing new — this is wiring.

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_edl_to_reel.py`:

```python
def test_the_edls_look_reaches_the_reel_manifest(...):
    # mirrors the platform pipe (2026-08-12): the EDL is the attested artifact, so
    # the look a reel was delivered with is recorded with the cut
    edl = EDL(episodes=(_ep(),), look=LookSpec(vignette=0.3, fade=0.8))
    rm = edl_to_reel._manifest_from_edl(edl, ...)   # use the file's existing helper name
    assert rm.look == LookSpec(vignette=0.3, fade=0.8)


def test_an_unauthored_look_stays_none_on_the_manifest(...):
    rm = edl_to_reel._manifest_from_edl(EDL(episodes=(_ep(),)), ...)
    assert rm.look is None
```

Append to `tests/lib/test_build_reel.py`:

```python
def test_build_reel_hands_the_look_to_deliver(monkeypatch, ...):
    seen = {}
    monkeypatch.setattr(build_reel.deliver, "deliver",
                        lambda *a, **k: seen.update(k) or "out.mp4")
    build_reel.build_reel(_rm(look=LookSpec(vignette=0.4, fade=0.6)), ...)
    assert seen["look"] == LookSpec(vignette=0.4, fade=0.6)


def test_build_reel_gives_mix_the_looks_fade(monkeypatch, ...):
    seen = {}
    monkeypatch.setattr(build_reel.mix, "mix",
                        lambda *a, **k: seen.update(k) or "audio.m4a")
    build_reel.build_reel(_rm(look=LookSpec(fade=0.8), music=str(music_json)), ...)
    assert seen["fade"] == 0.8


def test_a_reel_with_no_look_keeps_mixs_own_default(monkeypatch, ...):
    # absence of a look must not switch the audio bookend off
    seen = {}
    monkeypatch.setattr(build_reel.mix, "mix",
                        lambda *a, **k: seen.update(k) or "audio.m4a")
    build_reel.build_reel(_rm(music=str(music_json)), ...)
    assert "fade" not in seen
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edl_to_reel.py tests/lib/test_build_reel.py -x -q -k look`
Expected: FAIL.

- [x] **Step 3: Implement**

In `scripts/edl_to_reel.py`, where the `ReelManifest` is built (the call that
already passes `platform=edl.platform`), add `look=edl.look`:

```python
                      changelog=note, music=music or edl.music, platform=edl.platform,
                      look=edl.look, **extra)
```

In `scripts/build_reel.py`, in the `deliver.deliver(...)` call:

```python
            out = deliver.deliver(master, REEL_H264, out_dir, rm.changelog, report,
                                  audio=audio, titles=titles, platform=rm.platform,
                                  look=rm.look, run_provenance=prov)
```

and at the `mix.mix(...)` call, pass the fade only when a look authored one — an
absent look must keep mix's own 0.5s default rather than switching the audio
bookend off:

```python
            # A look's fade is the ONE number both bookends use. No look → mix keeps
            # its own default; a look with fade=0 → the author asked for no bookend at
            # all, in the picture and in the sound (design 2026-08-13 §5).
            fade_kw = {} if rm.look is None else {"fade": rm.look.fade}
            audio = mix.mix(music, work_dir, dur, segments=segs, ambient=rm.ambient,
                            sfx=rm.sfx, **fade_kw)
```

(Match the existing `mix.mix` call's positional/keyword shape in the file — only the
`**fade_kw` is new.)

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_edl_to_reel.py tests/lib/test_build_reel.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/edl_to_reel.py scripts/build_reel.py tests/lib/test_edl_to_reel.py tests/lib/test_build_reel.py
git commit -m "feat(look): thread EDL.look through edl_to_reel and build_reel"
```

---

## Task 6: `MoodPreset.look` and the `edit_plan` resolution

**Files:**
- Modify: `scripts/lib/moodpreset.py` (`MoodPreset.look` + five rows)
- Modify: `scripts/edit_plan.py` (`build_edl(look=)`, `write_edit_plan` resolution + log)
- Test: `tests/lib/test_moodpreset.py`, `tests/lib/test_edit_plan.py`

**Interfaces:**
- Consumes: `LookSpec` (Task 0), `EDL.look` (Task 2).
- Produces: `MoodPreset.look: LookSpec`; `build_edl(..., look: LookSpec | None = None)`.

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_moodpreset.py`:

```python
def test_every_preset_carries_a_look():
    for p in (*PRESETS, BALANCED):
        assert isinstance(p.look, LookSpec)


def test_the_fallback_applies_no_vignette():
    # skipping the optional brief must not silently apply a TASTE. (It must not
    # disable a quality GATE either — that is why BALANCED's shot_mix keeps a real
    # close share. The two rows read opposite because a gate and a look are
    # different kinds of thing.)
    assert BALANCED.look == LookSpec(vignette=0.0, fade=0.5)


def test_moody_is_the_heaviest_look():
    assert resolve("dark and moody").look == LookSpec(vignette=0.40, fade=1.0)


def test_look_must_be_a_lookspec():
    with pytest.raises(ValueError, match="MoodPreset.look must be a LookSpec"):
        MoodPreset("x", None, {"close": 0.3, "medium": 0.4, "wide": 0.3}, (1.0, 2.0),
                   look={"vignette": 0.3})
```

Append to `tests/lib/test_edit_plan.py`:

```python
def test_an_unauthored_look_comes_from_the_preset(...):
    edl = edit_plan.build_edl(footage, selection, preset=moodpreset.resolve("moody"),
                              look=moodpreset.resolve("moody").look, aspect=(9, 16))
    assert edl.look == LookSpec(vignette=0.40, fade=1.0)


def test_selection_json_overrides_the_preset(...):
    sel = {**selection, "look": {"vignette": 0.1, "fade": 0.2}}
    edl = edit_plan.build_edl(footage, sel, preset=moodpreset.resolve("moody"),
                              look=moodpreset.resolve("moody").look, aspect=(9, 16))
    assert edl.look == LookSpec(vignette=0.1, fade=0.2)


def test_an_authored_no_look_beats_the_preset(...):
    # the author said "no look" explicitly; the preset must not override a decision
    sel = {**selection, "look": {"vignette": 0, "fade": 0}}
    edl = edit_plan.build_edl(footage, sel, preset=moodpreset.resolve("moody"),
                              look=moodpreset.resolve("moody").look, aspect=(9, 16))
    assert edl.look == LookSpec()
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_moodpreset.py tests/lib/test_edit_plan.py -x -q -k look`
Expected: FAIL — `MoodPreset.__init__() got an unexpected keyword argument 'look'`

- [x] **Step 3: Implement**

`scripts/lib/moodpreset.py` — import `from scripts.lib.look import LookSpec`, add
the field to `MoodPreset`:

```python
    look: LookSpec = field(default_factory=LookSpec)   # the reel's finish (design 2026-08-13 §6)
```

(add `field` to the `dataclasses` import), validate it in `__post_init__`:

```python
        if not isinstance(self.look, LookSpec):
            raise ValueError(f"MoodPreset.look must be a LookSpec, got "
                             f"{type(self.look).__name__}")
```

and correct the module docstring's "exactly the two fields its one consumer reads"
sentence — it has three consumers now:

```python
A mood is not one knob: it is a recipe across shot selection, pace, colour, music
and effects. Today it wires the SELECTION half (`shot_mix`, `asl` — edit_plan) and
the LOOK half (`look` — the reel's vignette and bookend fade, spent in deliver).
Colour and QC are named follow-ups in the 2026-08-06 design's §14, not fields
nothing reads.
```

Fill the five rows (design §6 — first cuts, declared guesses alongside the numbers
already there):

```python
PRESETS: tuple[MoodPreset, ...] = (
    MoodPreset("fun", mood.MoodVector(0.74, 0.84, 0.72),
               {"close": 0.35, "medium": 0.40, "wide": 0.25}, (1.2, 2.5),
               look=LookSpec(vignette=0.00, fade=0.3)),
    MoodPreset("epic", mood.MoodVector(0.80, 0.55, 0.55),
               {"close": 0.25, "medium": 0.35, "wide": 0.40}, (1.5, 3.5),
               look=LookSpec(vignette=0.30, fade=0.8)),
    MoodPreset("moody", mood.MoodVector(0.48, 0.22, 0.42),
               {"close": 0.30, "medium": 0.35, "wide": 0.35}, (2.5, 5.0),
               look=LookSpec(vignette=0.40, fade=1.0)),
    MoodPreset("nostalgic", mood.MoodVector(0.32, 0.45, 0.34),
               {"close": 0.35, "medium": 0.40, "wide": 0.25}, (2.0, 4.0),
               look=LookSpec(vignette=0.25, fade=0.8)),
)
```

and `BALANCED`, with the reason it differs from its own shot_mix row:

```python
# The no-match fallback. Its close share is deliberately above WANT_FLOOR (a skipped
# brief must not disable a quality GATE), and its look is deliberately EMPTY of
# vignette (a skipped brief must not silently apply a TASTE). The 0.5s fade is what
# mix already did before looks existed, so the autonomous path delivers exactly
# today's reel.
BALANCED = MoodPreset("balanced", None,
                      {"close": 0.25, "medium": 0.40, "wide": 0.35}, (1.5, 4.0),
                      look=LookSpec(vignette=0.0, fade=0.5))
```

`scripts/edit_plan.py` — add `look: LookSpec | None = None` to `build_edl`'s
keyword-only parameters, document it beside `platform` in the docstring, and
resolve it before constructing the `EDL`:

```python
    # selection.json wins over the preset's default, and an authored {"vignette": 0,
    # "fade": 0} is a DECISION, not an absence — `is not None`, never truthiness.
    sel_look = selection.get("look")
    resolved_look = LookSpec.from_dict(sel_look) if sel_look is not None else look
```

then pass `look=resolved_look` into the `EDL(...)` construction.

In `write_edit_plan`, after the preset is resolved, hand it down and log which
source won:

```python
    sel_look = selection.get("look")
    _log(f"look: vignette {(LookSpec.from_dict(sel_look) if sel_look is not None else preset.look).vignette:.2f}"
         f" · fade {(LookSpec.from_dict(sel_look) if sel_look is not None else preset.look).fade:.2f}s"
         f" — from {'selection.json' if sel_look is not None else preset.name + ' preset'}")
```

Prefer a local variable over evaluating that twice:

```python
    sel_look = selection.get("look")
    eff_look = LookSpec.from_dict(sel_look) if sel_look is not None else preset.look
    _log(f"look: vignette {eff_look.vignette:.2f} · fade {eff_look.fade:.2f}s — from "
         f"{'selection.json' if sel_look is not None else preset.name + ' preset'}")
```

and pass `look=preset.look` into `build_edl` (which re-applies the same
selection-wins rule; the log line above only reports it).

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_moodpreset.py tests/lib/test_edit_plan.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/lib/moodpreset.py scripts/edit_plan.py tests/lib/test_moodpreset.py tests/lib/test_edit_plan.py
git commit -m "feat(look): MoodPreset.look supplies the brief's default"
```

---

## Task 7: `highlight_red` — the parked colour primitive

**Files:**
- Modify: `scripts/lib/color.py` (`highlight_red_arg` + two constants + `grade_chain`)
- Modify: `scripts/lib/models.py` (`ReframeSpec.highlight_red`)
- Modify: `scripts/lib/edl.py` (`EDLEpisode.highlight_red` + `to_manifest_dict`)
- Modify: `scripts/lib/manifest.py` (`Manifest.highlight_red` — the OPTIONAL tuple, the
  field, the `from_dict` line, mirroring `shadow_red`'s three parts)
- Modify: `scripts/process_episode.py` (pass it into the spec)
- Modify: `scripts/reframe.py` (forward `spec.highlight_red` into `grade_chain`)
- Test: `tests/lib/test_color.py`, `tests/lib/test_models.py`, `tests/lib/test_edl.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `color.highlight_red_arg(pull: float, knee: float = HIGHLIGHT_RED_KNEE) -> str`,
  `color.HIGHLIGHT_RED_MAX = 0.35`, `color.HIGHLIGHT_RED_KNEE = 0.60`;
  `grade_chain(..., highlight_red: float = 0.0, ...)`.

**Source:** the code already exists on `wip/montage-run-patches`. Read it with
`git show wip/montage-run-patches:scripts/lib/color.py` and port the
`HIGHLIGHT_RED_*` constants, `highlight_red_arg`, and the `grade_chain` change
verbatim — including the docstrings, which carry the reasons. Do **not** port
anything else from that branch.

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_color.py`:

```python
def test_highlight_red_is_identity_at_zero():
    assert color.highlight_red_arg(0.0) == ""


def test_highlight_red_pins_everything_below_the_knee_to_identity():
    arg = color.highlight_red_arg(0.2)
    assert arg.startswith(",curves=r='")
    lo = arg.split("'")[1].split()[:3]
    assert lo == ["0.0000/0.0000", "0.3000/0.3000", "0.6000/0.6000"]


def test_highlight_red_pulls_white_by_the_full_amount():
    # the top anchor is x=1.0 mapped to 1-pull: that IS the pull, at white
    arg = color.highlight_red_arg(0.2)
    assert arg.split("'")[1].split()[-1] == "1.0000/0.8000"


@pytest.mark.parametrize("pull", [-0.01, 0.36, True, "0.2"])
def test_highlight_red_refuses_out_of_band(pull):
    with pytest.raises(ValueError, match="highlight_red"):
        color.highlight_red_arg(pull)


@pytest.mark.parametrize("knee", [0.29, 0.91])
def test_highlight_red_refuses_a_knee_outside_its_band(knee):
    with pytest.raises(ValueError, match="knee"):
        color.highlight_red_arg(0.2, knee=knee)


def test_grade_chain_places_highlight_red_after_the_shoulder():
    # the shoulder lift, then the red shoulder pull, then the timeline dip LAST
    # highlight must be IN highlight_arg's [0.6, 1.0] band and NOT at its identity:
    # out of band it raises before the test runs, and at identity it returns "",
    # whose .index() is 0 and would make the ordering assertion pass vacuously.
    out = color.grade_chain((1.0, 1.0, 1.0), highlight=0.8, highlight_red=0.2,
                            dip=0.1, dur=3.0)
    hi = color.highlight_arg(0.8).lstrip(",")
    hr = color.highlight_red_arg(0.2).lstrip(",")
    dip = color.dip_arg(0.1, 3.0).lstrip(",")
    assert out.index(hi) < out.index(hr) < out.index(dip)


def test_grade_chain_is_unchanged_at_the_highlight_red_default():
    assert (color.grade_chain((1.1, 1.0, 0.9), dur=3.0)
            == color.grade_chain((1.1, 1.0, 0.9), highlight_red=0.0, dur=3.0))
```

Append to `tests/lib/test_models.py`:

```python
def test_reframe_spec_highlight_red_defaults_off():
    assert ReframeSpec(...).highlight_red == 0.0


def test_reframe_spec_highlight_red_refuses_out_of_band():
    with pytest.raises(ValueError, match="highlight_red"):
        ReframeSpec(..., highlight_red=0.5)
```

Append to `tests/lib/test_edl.py`:

```python
def test_episode_highlight_red_reaches_the_manifest():
    ep = _ep(highlight_red=0.2)
    assert ep.to_manifest_dict(...)["highlight_red"] == 0.2


def test_episode_highlight_red_is_omitted_at_its_default():
    assert "highlight_red" not in _ep().to_manifest_dict(...)
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py tests/lib/test_models.py tests/lib/test_edl.py -x -q -k highlight_red`
Expected: FAIL — `AttributeError: module 'scripts.lib.color' has no attribute 'highlight_red_arg'`

- [x] **Step 3: Implement**

Port from the parked branch. In `scripts/lib/color.py`, after `highlight_arg`, add
the two constants and the function exactly as they stand there:

```python
HIGHLIGHT_RED_MAX = 0.35     # past this the whites lose their body and read cyan, not just de-pinked
HIGHLIGHT_RED_KNEE = 0.60    # identity at/below this — the pull acts only on the shoulder (specular
                             # foam), so a red board and skin (both below it) keep their red


def highlight_red_arg(pull: float, knee: float = HIGHLIGHT_RED_KNEE) -> str:
    ...   # verbatim from `git show wip/montage-run-patches:scripts/lib/color.py`
```

Change `grade_chain` to take and apply it, in the parked branch's position (after
the shoulder, before the dip):

```python
def grade_chain(gains: tuple[float, ...], *, wb: str = "", tone: str = "",
                black_point: float = 0.0, shadow_red: float = 0.0,
                mid_blue: float = 1.0, saturation: float = 1.0,
                highlight: float = 1.0, highlight_red: float = 0.0,
                dip: float = 0.0, dur: float) -> str:
```

and in the docstring's order sentence, extend
`... → highlight (shoulder) → dip (timeline, last)` to
`... → highlight (shoulder) → highlight_red (the red shoulder) → dip (timeline, last)`,
then:

```python
    return (wb + tone + black_point_arg(black_point) + mixer_arg(*gains)
            + shadow_red_arg(shadow_red) + mid_blue_arg(mid_blue)
            + saturation_arg(saturation) + highlight_arg(highlight)
            + highlight_red_arg(highlight_red) + dip_arg(dip, dur))
```

In `scripts/lib/models.py`, add `highlight_red: float = 0.0` to `ReframeSpec`
beside the other colour fields, validated against `color.HIGHLIGHT_RED_MAX` in the
same style as its neighbours. In `scripts/lib/edl.py`, add
`highlight_red: float = 0.0` to `EDLEpisode` with the parked comment:

```python
    highlight_red: float = 0.0  # red SHOULDER pull; de-pinks specular foam a bright red
                                # board throws its reflection into. The mirror of
                                # shadow_red. See color.highlight_red_arg.
```

and emit it conditionally in `to_manifest_dict` alongside the other conditional
colour fields. In `scripts/process_episode.py`, carry it into the `ReframeSpec`
the same way `shadow_red` is carried.

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py tests/lib/test_models.py tests/lib/test_edl.py tests/lib/test_manifest.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/lib/color.py scripts/lib/models.py scripts/lib/edl.py scripts/process_episode.py tests/
git commit -m "feat(color): land the parked highlight_red shoulder pull"
```

---

## Task 8: `outline-bold` — the fourth title style

**Files:**
- Modify: `scripts/lib/titles.py` (`STYLES`, `_STYLE_FRAGMENTS`)
- Test: `tests/test_titles.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `"outline-bold"` accepted by `Title.style`.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_titles.py`:

```python
def test_outline_bold_is_a_style():
    assert "outline-bold" in STYLES
    assert Title(text="hi", start=0.0, dur=1.0, style="outline-bold").style == "outline-bold"


def test_outline_bold_draws_a_heavier_border_than_outline(tmp_path):
    bold = build_filterchain(Titles(items=(Title(text="hi", start=0.0, dur=1.0,
                                                 style="outline-bold"),)), str(tmp_path))
    thin = build_filterchain(Titles(items=(Title(text="hi", start=0.0, dur=1.0,
                                                 style="outline"),)), str(tmp_path))
    assert "borderw=7" in bold and "borderw=4" in thin
    assert "shadowx=3" in bold and "shadow" not in thin
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_titles.py -x -q -k outline_bold`
Expected: FAIL — `'outline-bold' not in STYLES`

- [x] **Step 3: Implement**

In `scripts/lib/titles.py`:

```python
STYLES: tuple[str, ...] = ("bold-box", "outline", "outline-bold", "plain")
```

```python
_STYLE_FRAGMENTS: dict[str, str] = {
    "bold-box": "box=1:boxcolor=black@0.5:boxborderw=16",
    "outline": "borderw=4:bordercolor=black",
    # a heavier outline PLUS an offset shadow: `outline` alone disappears against
    # bright water, which is what the 2026-08-03 run hit
    "outline-bold": "borderw=7:bordercolor=black:shadowcolor=black@0.55:shadowx=3:shadowy=3",
    "plain": "",
}
```

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_titles.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/lib/titles.py tests/test_titles.py
git commit -m "feat(titles): outline-bold, the fourth style"
```

---

## Task 9: the real-ffmpeg visibility proofs

**Files:**
- Create: `tests/integration/test_look.py`
- Test: itself

**Interfaces:**
- Consumes: everything above.
- Produces: the #18 evidence — six measurements on rendered pixels.

**This is the point of the slice.** #18 exists because a live-added vignette came
out invisible and no test noticed. Each proof below measures the pixels, and each
also measures a control that must NOT move.

Use `sample_clip` (the session fixture: 3s, 1920×1080, 30fps) and the `need_filter`
fixture. Decode with ffmpeg to `rawvideo`/`gray` and compute with numpy, as
`tests/integration/test_zoom.py` and `test_ramp.py` already do — follow whichever
of those two files reads more cleanly and reuse its helpers rather than writing new
ones.

- [x] **Step 1: Write the tests**

Create `tests/integration/test_look.py` with these six, in this order:

```python
def test_the_vignette_darkens_the_corners_and_leaves_the_centre_alone(tmp_path, sample_clip):
    """design §9 row 1. The corner/centre ratio must FALL, and the plateau must not
    move — a vignette that dims the whole frame is the built-in filter's failure
    (§2.1), not this one's."""
    plain = _deliver(tmp_path / "a", sample_clip, look=None)
    vig = _deliver(tmp_path / "b", sample_clip, look=LookSpec(vignette=0.4))
    fp, fv = _gray(plain, 15), _gray(vig, 15)
    assert _corner_ratio(fv) < _corner_ratio(fp) - 0.15
    centre_delta = np.abs(_centre(fv) - _centre(fp)).mean()
    assert centre_delta < 1.0, f"the plateau moved by {centre_delta:.2f} luma"


def test_the_bookend_fade_blacks_both_ends_and_not_the_middle(tmp_path, sample_clip):
    """design §9 row 2. Both ends near zero, the middle untouched. §11.5: the last
    frame lands near 0, not at 0 — it is quantized to the frame grid."""
    out = _deliver(tmp_path / "c", sample_clip, look=LookSpec(fade=0.5))
    plain = _deliver(tmp_path / "d", sample_clip, look=None)
    frames = _all_gray(out)
    assert frames[0].mean() < 2.0
    assert frames[-1].mean() < 12.0
    assert abs(frames[len(frames) // 2].mean() - _all_gray(plain)[len(frames) // 2].mean()) < 1.0


def test_no_look_delivers_a_byte_identical_file(tmp_path, sample_clip):
    """design §9 row 3. The off path must not have moved at all."""
    a = _deliver(tmp_path / "e", sample_clip, look=None)
    b = _deliver(tmp_path / "f", sample_clip, look=LookSpec())
    assert Path(a).read_bytes() == Path(b).read_bytes()


def test_a_vignette_and_a_muxed_stem_pick_the_right_audio_input(tmp_path, sample_clip, ...):
    """The mask is input 1 and the stem is input 2 — mapping 1:a:0 there would look
    for audio inside a PNG. Proven by probing the delivered file for an audio stream
    of the right duration, not by reading the argv."""
    out = _deliver(tmp_path / "g", sample_clip, look=LookSpec(vignette=0.35), audio=stem)
    assert _has_audio(out)
    assert abs(_audio_dur(out) - _video_dur(out)) < 0.2


def test_the_audio_bookend_falls_with_ambient_on(tmp_path, ...):
    """design §9 row 4 + §5. The tail must FALL. Before this slice the duck released
    as the music faded and the ambient rose here."""
    stem = mix.mix(music, str(tmp_path), 6.0, segments=[(seg, 3.0), (seg, 3.0)],
                   ambient=True, fade=0.5)
    rms = _rms_windows(stem, 0.1)
    assert rms[-1] < rms[len(rms) // 2] * 0.35


def test_highlight_red_pulls_the_highlights_and_leaves_the_shadows(tmp_path, sample_clip):
    """design §9 row 5. R−B must fall where the pull acts and hold where it does not."""
    plain = _reframe_graded(tmp_path / "h", sample_clip, highlight_red=0.0)
    pulled = _reframe_graded(tmp_path / "i", sample_clip, highlight_red=0.3)
    assert _rb_in_band(pulled, lo=200, hi=255) < _rb_in_band(plain, lo=200, hi=255) - 2.0
    assert abs(_rb_in_band(pulled, lo=0, hi=80) - _rb_in_band(plain, lo=0, hi=80)) < 1.0
```

Write the helpers (`_deliver`, `_gray`, `_all_gray`, `_corner_ratio`, `_centre`,
`_rms_windows`, `_rb_in_band`, `_has_audio`, `_audio_dur`, `_video_dur`,
`_reframe_graded`) at the top of the file. `_deliver` must build a real passing
`ReelReport` with the master's digest — copy that setup from
`tests/integration/test_reel_backhalf.py`, which already does it.

`sample_clip` is 1920×1080; the vignette measurements do not depend on the aspect,
only on the plateau, so no vertical fixture is needed for these proofs.

- [x] **Step 2: Run them**

Run: `.venv/bin/python -m pytest tests/integration/test_look.py -q`
Expected: PASS, 6 tests. If a threshold is close, **measure and adjust the
threshold to the measured value with margin — do not weaken an assertion to
"something changed"**. Record the measured numbers in the commit message.

- [x] **Step 3: Commit**

```bash
git add tests/integration/test_look.py
git commit -m "test(look): six real-ffmpeg visibility proofs (#18's actual demand)"
```

---

## Task 10: the mutation battery

**Files:**
- Test only — no production change unless the battery finds a hole.

**These are steps, not suggestions.** Each row breaks the production code in one
specific way and names the test that must go red. A row where nothing goes red is a
coverage hole: **close it with a new test in the same task**, then revert the
mutation.

- [x] **Step 1: Run each mutation, record the result**

| # | mutation | expected red |
|---|---|---|
| 1 | `look.chain`: swap the two appends so the fade precedes the titles | `test_chain_puts_the_fade_after_the_titles` |
| 2 | `look.chain`: return `parts` even when `spec is None` and `titles` is empty (return `[""]`) | `test_chain_is_empty_with_no_look_and_no_titles` |
| 3 | `look.mask_expr`: change `VIGNETTE_PLATEAU` to `0.0` | `test_mask_expr_carries_the_measured_plateau_and_the_strength`, and `test_the_vignette_darkens_the_corners_and_leaves_the_centre_alone` on the centre delta |
| 4 | `look.fade_args`: drop the `2 * fade > dur` guard | `test_fade_args_refuse_overlapping_fades` |
| 5 | `deliver`: use `aidx = 1` unconditionally | `test_audio_input_index_shifts_when_a_mask_is_present` **and** `test_a_vignette_and_a_muxed_stem_pick_the_right_audio_input` |
| 6 | `deliver`: emit `-vf` even when a mask exists (drop the `-filter_complex` branch) | `test_vignette_renders_a_mask_and_moves_to_filter_complex` |
| 6b | `deliver`: drop `*parts` from the **`-filter_complex` branch only**, keeping the overlay | the Task 9 vignette+fade proof. **This row already fired once**: before it existed, that mutation passed the WHOLE suite (2759 passed). `deliver` builds the graph in two branches over the same `parts` list, and `parts` carries the titles chain as well as the fade — so a refactor touching one branch silently deleted the bookend AND every on-screen title for `epic`, `moody` and `nostalgic`, which are 3 of the 4 mood presets and ship vignette+fade together. |
| 6c | `deliver`: drop every `drawtext` from the **`-filter_complex` branch only** (`[p for p in parts if not p.startswith("drawtext")]`), keeping the overlay AND the fade | `test_vignette_renders_a_mask_and_moves_to_filter_complex`'s `"drawtext" in g` assertion. **This row already fired once** — the final whole-branch review found that this narrower sibling of 6b passed the WHOLE suite (2761 passed): 6b was closed with a *fade* assertion only, and no test anywhere exercised titles and a vignette together, so a mutation that keeps the fade but drops only the titles slipped past it. Every on-screen title vanished for `epic`/`moody`/`nostalgic`. Verified red under the mutation, then reverted by hand and re-verified green (final-fix-report.md). |
| 7 | `deliver`: build the mask at a hardcoded `1080x1920` instead of the probed dims, and make `_render_mask` never call `probe_stream` at all | the Task 3 probe-recording test. **This row already fired once** — the Task 3 review demonstrated that the first round of tests passed under exactly this mutation, because the `probe_stream` stub discarded its argument. The fix added a call-recording assertion; this row re-checks it. |
| 8 | `deliver`: replace `overlay=shortest=1` with `blend=all_mode=multiply` | `lint`'s new check fires through `proc.run` — any deliver test with a vignette |
| 9 | `EDL.from_dict`: use `if d.get("look")` instead of `is not None` | `test_edl_look_empty_object_is_authored_not_absent`. **Not** `test_edl_look_accepts_an_authored_no_look`, which this row named until Task 10 ran it and watched it pass: that test authors `{"vignette": 0, "fade": 0}`, a NON-EMPTY and therefore truthy dict, so it survives either spelling. Only the empty object discriminates. |
| 10 | `mix`: move the `afade` back onto the fragment extract | `test_the_fade_runs_on_the_mixed_stem_before_loudnorm` and `test_the_audio_bookend_falls_with_ambient_on` |
| 11 | `build_reel`: pass `fade=0.0` when `rm.look is None` | `test_a_reel_with_no_look_keeps_mixs_own_default` |
| 12 | `moodpreset.BALANCED`: give it `vignette=0.3` | `test_the_fallback_applies_no_vignette` |
| 13 | `color.grade_chain`: move `highlight_red_arg` before `mixer_arg` | `test_grade_chain_places_highlight_red_after_the_shoulder` |
| 14 | `titles._STYLE_FRAGMENTS["outline-bold"]`: copy `outline`'s value | `test_outline_bold_draws_a_heavier_border_than_outline` |

- [x] **Step 1b: Re-sync `test_lint.py`'s `REAL_SITES` fixture**

Task 4 moved `mix.py`'s bookend `afade` off the music-fragment extract and onto the
mixed stem. `tests/lib/test_lint.py` carries a `REAL_SITES` fixture of hand-copied
production argv literals, and its `"mix.py:193 — input seek on a window,
accurate_seek"` entry now pins a command that **no longer exists** — the real call
moved and dropped its `-af`. The battery still passes, because the fixtures are
literals rather than being derived from the source, which is exactly what makes
this dishonest: a safety fixture that describes code that is gone proves nothing
about the code that is there.

Update that entry to the argv `mix.py` actually emits now, and add an entry for
the new post-mix pre-measure fade call. Then confirm the whole of
`tests/lib/test_lint.py` is green.

One more of the same class, in **production** rather than test code:
`scripts/lib/lint.py`'s own error message still cites `scripts/mix.py:193` as an
example call site. That line moved with the fade. Correct it here — it is the
same drift, and a lint message that points at the wrong line teaches the next
reader the wrong thing.

Separately, and less seriously: the Task 4 review found that several other
labels (`"mix.py:72"`, `"75"`, `"109"`, `"137"`, `"207"`) now carry stale line
numbers because the insertions shifted the file. Their pinned **argv values are
still correct** — those call sites were not touched — so this is cosmetic label
drift, not the stale-content problem above. Re-sync them in the same pass so
nobody rediscovers them.

Worth knowing while you do this: the review confirmed `proc.run` calls
`lint.check_argv` on **every** command unconditionally, independent of anything
in `REAL_SITES`. So the new fade call is already guarded live; `REAL_SITES` is a
regression-documentation layer on top of the enforcement path, not the
enforcement path itself. That is why nothing is broken today, and also why a
fixture that lies is worth fixing rather than deleting.

- [x] **Step 1c: One false comment to correct**

`tests/lib/test_manifest.py`'s new `highlight_red=0.15` carries a comment saying
the value is distinguishable "from `shadow_red`'s own test value elsewhere in
this file". Grep says `shadow_red` never appears as a value anywhere in that
file — the colliding value (`0.05`) lives in the *other* file,
`tests/integration/test_process_episode.py`. The choice of 0.15 is right; the
sentence explaining it is not. Correct it to name the real neighbour.

- [x] **Step 2: Close any hole the battery found**

For each row where nothing went red, write the missing test, verify it goes red
under the mutation and green without it, and note it in the commit message.

- [x] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green. Record the exact pass/skip counts.

- [x] **Step 4: Commit**

```bash
git add tests/
git commit -m "test(look): 14-row mutation battery + the holes it found"
```

---

## Task 11: docs, skills, and the backlog rows

**Files:**
- Modify: `docs/specs/2026-07-05-montage-skillset-design.md` (§12 landmine registry)
- Modify: `docs/backlog.md` (the five deferral rows + #9/#18 status)
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`
- Modify: `docs/fixes-backlog.md` (#9 and #18 status headers)
- Modify: `skills/edit-plan/SKILL.md`, `skills/titles/SKILL.md`, `skills/using-montage/SKILL.md`

- [x] **Step 1: Add the five landmines to §12**

In `docs/specs/2026-07-05-montage-skillset-design.md` §12, add one entry each,
with the measured numbers, for design §8.1–§8.5: the chroma-destroying
`blend=all_mode=multiply` (mean |dU| 63.44), `movie=` in `-vf` without `loop`
(exit 0, `nb_frames=1`), `movie=…:loop=0` (hangs), `color=c=white` reading 253,
and the built-in `vignette` on a vertical canvas (sky at 0.637 of centre at the
default angle; `aspect=16/9` drives corners and sky to 0.000).

Also add the first of these to `CLAUDE.md`'s always-loaded "Known troubles" list —
it is the one a future author is most likely to reach for, and it is machine-checked
now, so the entry can say so.

- [x] **Step 2: Add the backlog rows**

Per the 2026-08-12 rule, every row of the design's §12 table goes into
`docs/backlog.md`:

- **P2:** calibrate `LOOK_VIGNETTE_MAX`, the plateau/falloff and `MoodPreset.look`
  on real footage (first cuts on synthetic patterns).
- **P2:** fold "does the look actually render" into #10's 3-frame probe — no gate
  runs after `deliver`.
- **P3, in the look tail:** grain, carrying the measured cost table (×4.36 file
  size at `alls=8`, ×8.82 at 12, ×14.08 at 20, all at crf 18) so nobody re-measures.
- **P4:** the chroma-preserving vignette (luma-plane blend or `geq`), if the
  corner desaturation reads wrong on real footage.
- **P4:** a per-episode look override.
- **P2, found by this slice, not caused by it:** `color.shadow_red_arg` has the
  **identical sparse-anchor defect** `highlight_red_arg` was fixed for here, and
  worse — measured **−6** at `SHADOW_RED_MAX` against `highlight_red`'s pre-fix
  −3. It is the mirror function, and `highlight_red`'s docstring cited "the
  shadow_red lesson" for a lesson `shadow_red` itself never learned. The fix is
  the same one-line densification, plus a probe test.
- **P3, pre-existing, unreachable today:** `highlight_red_arg`'s **shoulder**
  (`hi`) formula is monotonicity-fragile near `pull ≈ 1 − knee` for
  `knee ≥ 0.7`. A knee × pull grid scan found the old code already broken across
  a swath there; the sub-knee fix moves 2 of 63 grid points, both on that
  boundary. The only production call site never passes `knee=`, so nothing
  reaches it — but the formula, not the anchors, is what needs rethinking.

Update the P1 row for #9: the look half is done, the P2 grade half and the P3 tail
remain — **do not mark #9 closed**. Update #18's row: all four pieces have landed,
so it closes.

- [x] **Step 3: Update the skills**

- `skills/edit-plan/SKILL.md`: `selection.json` may carry a top-level `"look"`
  (`{"vignette": 0.0–0.6, "fade": 0.0–2.0}`); absent means the mood preset decides;
  `{"vignette": 0, "fade": 0}` means "no look" and beats the preset. Note that
  `edit_plan build` logs which source won.
- `skills/titles/SKILL.md`: `outline-bold` as the fourth style, and when to reach
  for it (bright backgrounds where `outline` disappears).
- `skills/using-montage/SKILL.md`: the look is delivery-time, so it is invisible in
  the draft and in every check — CP3 is the first place a human sees it.

- [x] **Step 4: Status docs**

Add a Done entry to `docs/build-status.md` dated 2026-08-13 carrying the measured
numbers (the §2.2 cost table, the corner/sky ratios, the grain cost table, the
mask-chroma |dU| 63.44, the `movie=` one-frame and hang results), the five
landmines, and every §11 honest limit. Update **Next action**. Add the two registry
rows (design + plan) to `CLAUDE.md`'s Quick Reference and the look row to
`docs/pipeline-map.md`'s §5.14/§5.16 lines.

- [x] **Step 5: Full suite + commit**

Run: `.venv/bin/python -m pytest -q`
Expected: all green.

```bash
git add docs skills CLAUDE.md
git commit -m "docs(look): §12 landmines, backlog rows, skills, and the build-status entry"
```

---

## Self-review

**Spec coverage.** §1 → Tasks 2, 3, 5. §2 → Task 0 (`mask_expr`) + Task 9 (proof
1). §3.1 → Task 0. §3.2 → Task 3. §3.3 → Task 5. §4 → Task 0 (`chain`) + Task 3
(order in the graph) + Task 9. §5 → Task 4 + Task 5 + Task 9 (proof 5). §6 → Task
6. §7 → Tasks 7 and 8. §8.1 → Task 1. §8.2–§8.5 → Task 11 step 1 (registry entries;
they are findings, not code). §9 → Task 9. §10 → nothing to build, by definition.
§11 → Task 11 step 4. §12 → Task 11 step 2.

**Gaps found and closed while reviewing:**
- §8.4 (`color=c=white` reads 253) had no task. It is not a bug in this slice's
  code — `_render_mask` uses `nullsrc` with an explicit `255*(…)` alpha, which is
  the fix — but the *reason* it uses `nullsrc` was only in the design. Task 0's
  `mask_expr` docstring and Task 11's §12 entry now carry it.
- The `deliver` CLI had no way to author a look. Added the two flags in Task 3.
- Task 6's log line was written twice-evaluated; replaced with a local.

**Type consistency.** `LookSpec` is the one type crossing every boundary:
`look.LookSpec` (Task 0) → `EDL.look` / `ReelManifest.look` (Task 2) →
`deliver(look=)` (Task 3) → `MoodPreset.look` / `build_edl(look=)` (Task 6). `mix`
deliberately takes `fade: float`, not a `LookSpec` — it is an audio module and must
not import the video look. `has_vignette` is spelled the same in Task 0, Task 3 and
the design.

**Placeholder scan.** The `...` markers in Tasks 3, 7 and 9 are pytest fixture
arguments and one verbatim port pointer, not unwritten content: Task 7 names the
exact `git show` command for the port, and Task 9 names the exact file to copy the
`ReelReport` setup from. Every other step carries its literal code.
