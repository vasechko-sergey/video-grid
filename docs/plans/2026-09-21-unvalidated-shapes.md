# Unvalidated shapes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace three comments that assert an invariant with constructions that
enforce it, and close a fourth backlog row whose premise its own measurement
refutes.

**Architecture:** Four independent single-site changes, no shared machinery. Each
converts a reader's unenforced assumption into either a refusal with a remedy or a
discriminator the producer actually guarantees. No report key is added, renamed or
removed; no contract field, threshold or check changes; no golden moves.

**Tech Stack:** Python 3.13, pytest, numpy, ffmpeg/ffprobe via `scripts/lib/ffbin.py`.
Interpreter `.venv/bin/python`. Scripts run as modules (`pythonpath = .`).

**Design:** [docs/specs/2026-09-21-unvalidated-shapes-design.md](../specs/2026-09-21-unvalidated-shapes-design.md).
Read §0 before changing anything — two of the four rows were re-scoped by
measurement and one was overturned outright.

## Global Constraints

- **Never install anything.** No `brew`, `pip`, `uv`, `npm`, `apt`, no `setup.sh`.
  Verification is read-only plus `pytest`. If a dependency seems missing, report it
  and stop.
- **Never run `git checkout --`, `git restore`, `git reset --hard`, or `git stash`.**
  To undo a mutation to a *committed* file use `git show HEAD:<path> > <path>`; when
  the file being mutated is *uncommitted*, save your own copy first
  (`cp <path> <path>.bak`); run any mutation on an otherwise-clean tree and re-check
  `git diff --stat` after restoring.
- **`git add` named paths only.** Never `git add -A` or `git add .`.
- **Mutation batteries run under `PYTHONDONTWRITEBYTECODE=1`.** A one-byte edit can
  match the previous file's size and mtime-second, and CPython then serves a stale
  `.pyc`.
- **zsh does not word-split an unquoted variable.** A pytest selection held in a
  shell variable arrives as ONE argument and the run prints `no tests ran`, which
  reads exactly like a non-discriminating mutation row. Quote or expand explicitly.
- **Do not touch `/Users/serg/Downloads/untitled folder/`.** Read-only probing only;
  it is an existing real run.
- **No report key is added, renamed or removed** (design §3). If a change you are
  making would move one, stop and report — you are on the wrong fix.
- **Comments are part of the deliverable here.** Three of the four sites ship a
  corrected comment alongside the code, and a corrected comment that still overclaims
  is a failed task. Say what the construction guarantees, and no more.
- Docs and code in English; commit messages in English.
- Do not push. The branch is `docs/unvalidated-shapes`.

---

## File Structure

| File | Task | Responsibility after the change |
|---|---|---|
| `scripts/check_episode.py` | 1 | The advisory cannot return an absence; the verdict reads its own dict |
| `tests/test_check_episode.py` | 1 | Unit proofs for both halves |
| `scripts/lib/color.py` | 2, 4 | The plane guard refuses an absent `pix_fmt`; `grade_chain` states its comma discipline |
| `tests/lib/test_color.py` | 2, 4 | Guard clause unit proof; the composition enumeration |
| `tests/conftest.py` | 2 | `undescribable_plane` session fixture derived from `golden_ride_segment` |
| `tests/integration/test_unvalidated_shapes.py` | 2 | The reachability proof: real ffprobe, real `_probe`, real `plan_render` |
| `scripts/check_reel.py` | 3 | The chroma reader keys on `status`, and its comment names both inlets |
| `tests/lib/test_check_reel.py` | 3 | The mixed-dict proof and the `build_reel`-inlet proof |
| `docs/backlog.md`, `docs/backlog-closed.md`, `docs/build-status.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json`, `CLAUDE.md` | 5 | Four rows closed, version 0.12.1, registry rows |

---

## Task 1: The advisory cannot produce an absence, and the verdict reads its own dict

**Files:**
- Modify: `scripts/check_episode.py:159-169` (the `out = {...}` build) and
  `scripts/check_episode.py:241-245` (the merge and the branch)
- Test: `tests/test_check_episode.py`

**Interfaces:**
- Consumes: `check_episode._region_pairs(plain, graded, mask) -> list[tuple]`,
  `regions.subject_mask(extents, n, h, w) -> tuple[np.ndarray, float]`,
  `regions.refuse(kind, *, located, fraction) -> str | None`,
  `color_fidelity.evaluate(pairs) -> dict`,
  `gradedamage.evaluate(*, plain, graded, floor) -> dict`
- Produces: nothing new. `_subject_delta_advisory`'s return keys and
  `_grade_damage`'s `CheckResult` shape are byte-identical to today for every input
  the real producers emit.

**Context.** `_grade_damage` merges the entropy verdict and the dE00 advisory into
one flat dict and then branches on `"status" in d`. Both halves can contribute
`status` — that is the whole of the defect (design §0.1). It is unreachable today,
because the region the advisory reads always holds pixels: on the fallback arm it is
an all-ones mask over `n >= 1` frames, and on the subject arm `regions.refuse`
returning `None` *is* the statement that the mask is non-empty. The fix makes both
of those facts enforced rather than merely true.

Read design §2.1 before starting. It explains why the report's flat shape is
deliberately preserved and why namespacing the advisory was rejected.

- [ ] **Step 1: Write the failing test for the advisory's refusal**

Append to `tests/test_check_episode.py`. It uses the file's existing `_stacks()` and
`_sidecar()` helpers (defined at the top of that file).

```python
def test_a_region_that_refused_nothing_but_holds_no_pixels_is_a_contract_break(monkeypatch):
    """The advisory's ONLY absence shape is {status, reason}, and _grade_damage
    merges it flat into the verdict where `status` is the discriminator (design
    §0.1). It cannot happen: a crop read is the whole frame, and a subject read
    only runs when regions.refuse declined to refuse, which is the statement that
    the mask holds pixels. So a lying producer — a mask with no pixels reported at
    a fraction above MIN_REGION_FRAC — must RAISE here rather than describe itself
    as not-checked."""
    plain, graded = _stacks()
    route, path, meta = _sidecar()
    empty = np.zeros((N, H, W), dtype=bool)
    monkeypatch.setattr(regions, "subject_mask", lambda extents, n, h, w: (empty, 0.5))
    with pytest.raises(ValueError) as e:
        check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                              route, path, meta)
    msg = str(e.value)
    assert "subject" in msg                    # names the region it was reading
    assert "regions.subject_mask" in msg       # names where the break is
    assert "not-checked" in msg                # names the shape it refuses to emit


def test_an_ordinary_subject_read_still_carries_its_five_fidelity_keys():
    """The control for the refusal above: the guard must not fire on a real read."""
    plain, graded = _stacks()
    route, path, meta = _sidecar()
    d = check_episode._subject_delta_advisory(plain, graded, [0.0, 0.5, 1.0],
                                              route, path, meta)
    assert {"delta_e", "delta_l", "delta_c", "delta_h", "samples"} <= set(d)
    assert "status" not in d and "reason" not in d
```

- [ ] **Step 2: Run both to verify the first fails**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest "tests/test_check_episode.py::test_a_region_that_refused_nothing_but_holds_no_pixels_is_a_contract_break" "tests/test_check_episode.py::test_an_ordinary_subject_read_still_carries_its_five_fidelity_keys" -v
```

Expected: the first FAILS (`DID NOT RAISE`), the second PASSES.

- [ ] **Step 3: Write the failing test for the verdict's own branch**

Append to `tests/test_check_episode.py`. This one stubs the advisory deliberately —
after Step 5 the advisory cannot emit that shape, so a stub is the only way to pin
that the branch reads the verdict and not the merge.

```python
def test_the_verdict_is_read_from_the_verdict_not_from_the_merge(monkeypatch):
    """A flat merge puts the advisory second, so an advisory `status` overwrites
    into the dict the branch reads. Step 5 of Task 1 makes that shape impossible
    to produce; this pins that the BRANCH no longer depends on it, so a future
    advisory key cannot silently reopen the coupling (design §2.1).

    The stub is a lying advisory, not a reachable state — which is exactly why
    the assertion is about `passed`, and why this test would be meaningless if it
    also asserted the merged dict's keys."""
    monkeypatch.setattr(check_episode, "_subject_delta_advisory",
                        lambda *a, **k: {"status": "stubbed", "reason": "stubbed"})
    monkeypatch.setattr(check_episode.gradedamage, "evaluate",
                        lambda **k: {"ratio": 0.5, "plain_bits": 7.0, "graded_bits": 3.5,
                                     "floor": 0.9, "frames": 3, "below": True})
    monkeypatch.setattr(check_episode.reframe, "plan_frames_rgb",
                        lambda plan, src, times: list(np.zeros((3, 4, 4, 3), np.uint8)))
    route, path, meta = _sidecar()
    monkeypatch.setattr(check_episode.color, "sample_times", lambda dur, *a, **k: [0.0, 0.5, 1.0])

    class _Plan:
        dur = 1.0

    res = check_episode._grade_damage("src.mp4", (_Plan(), _Plan()), route, path, meta,
                                      CheckSpec(composition="center", grid="thirds",
                                                target_dur=1.5))
    assert res.passed is False          # the entropy verdict, not the advisory's status
    assert res.detail["below"] is True
```

- [ ] **Step 4: Run it to verify it fails**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest "tests/test_check_episode.py::test_the_verdict_is_read_from_the_verdict_not_from_the_merge" -v
```

Expected: FAIL — `assert None is False`. On today's build the advisory's `status`
reaches the merged dict and the branch returns `passed=None`.

- [ ] **Step 5: Make the advisory's absence impossible**

In `scripts/check_episode.py`, replace lines 159-169 — the block from
`fallback = regions.refuse(...)` through the `**color_fidelity.evaluate(...)` line —
with:

```python
    fallback = regions.refuse("subject", located=located, fraction=frac)
    whole = np.ones((n, h, w), dtype=bool)
    read = whole if fallback else mask
    # A bare read, never an absence: `whole` holds pixels in every one of n >= 1
    # frames (color.sample_times returns FRAMES >= 1 times), and a subject read
    # only runs when regions.refuse DECLINED to refuse, which is the statement
    # that the mask holds pixels. So an empty pair list is a broken producer, not
    # an input to describe. It must raise, because the alternative shape
    # color_fidelity.evaluate would return here is {status, reason} — and
    # _grade_damage merges this dict flat into the entropy verdict, where until
    # 2026-09-21 `status` was the discriminator that decided whether a BLOCKING
    # verdict counted (design §0.1). The background arm below has followed this
    # rule since 2026-09-16; this is the read it was asymmetric with.
    pairs = _region_pairs(p, g, read)
    if not pairs:
        raise ValueError(
            f"check_episode: the {'crop' if fallback else 'subject'} read came back "
            f"with no sample pairs over {n} frames. A crop read is the whole frame "
            f"and a subject read only happens when regions.refuse declined to "
            f"refuse, so both hold pixels by construction — an empty read is a "
            f"contract break in regions.subject_mask or _region_pairs, not an "
            f"input to report as a not-checked advisory.")
    out = {"advisory_delta_e": True,
           "region": "crop" if fallback else "subject",
           # the fraction of the region ASKED for — on a too-small row it is the
           # small number that is the evidence, never the crop's 1.0 it fell back
           # to. regions.AnchorReading.fraction's own convention (design §2.3).
           "region_fraction": round(frac, 4),
           "region_fallback": fallback,
           **color_fidelity.evaluate(pairs)}
```

The three comment lines describing `region_fraction` stay exactly where they are
today — between `"region"` and `"region_fraction"`. They describe the fraction, and
keeping them attached to it is the point. Only the `**color_fidelity.evaluate(...)`
argument changes, from the inline `_region_pairs(...)` call to the `pairs` local the
refusal above has already checked.

- [ ] **Step 6: Make the branch read the verdict**

In `scripts/check_episode.py`, replace lines 241-245 with:

```python
    verdict = gradedamage.evaluate(plain=p_frames, graded=g_frames, floor=spec.entropy_floor)
    # The discriminator belongs to the dict it judges. `d` below is a FLAT merge of
    # this verdict and the advisory description, and both halves can spell
    # {status, reason} — so reading `"status" in d` made a blocking verdict depend
    # on a key the advisory could contribute (design §0.1/§2.1). The advisory can
    # no longer emit that shape at all, which is what closes the defect; branching
    # here keeps it closed against a future advisory key.
    unchecked = "status" in verdict
    d = dict(verdict)
    d.update(_subject_delta_advisory(p_frames, g_frames, times, route_pts, path_obj, meta))
    if unchecked:
        return CheckResult("grade_damage", None, d)
    return CheckResult("grade_damage", not d["below"], d)
```

- [ ] **Step 7: Run the four new tests and the two whole files**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_check_episode.py tests/integration/test_check_episode.py -v
```

Expected: all PASS, including the four new tests. No existing test changes.

- [ ] **Step 8: Run every module that reads the grade_damage block**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/integration/test_color_fidelity.py tests/integration/test_grade_sensor_references.py tests/integration/test_grade_shipped_pixels.py tests/integration/test_chroma_spread.py tests/test_episode_qc.py -v
```

Expected: all PASS. This is the proof that the report shape did not move (design §3).

- [ ] **Step 9: Commit**

```bash
git add scripts/check_episode.py tests/test_check_episode.py
git commit -m "fix(check_episode): the verdict reads its own dict, and the advisory cannot return an absence"
```

---

## Task 2: An undescribable plane is refused by name

**Files:**
- Modify: `scripts/lib/color.py` — `refuse_ungradeable_plane`, at line 249
- Test: `tests/lib/test_color.py` (unit), `tests/integration/test_unvalidated_shapes.py`
  (new, reachability), `tests/conftest.py` (new session fixture)

**Interfaces:**
- Consumes: `color.plane_depth(pix_fmt: str) -> int` (unchanged),
  `reframe._probe(src) -> tuple[int, int, float, float, str, str]` (unchanged),
  `reframe.plan_render(spec, src, route_path) -> RenderPlan` (unchanged)
- Produces: `color.refuse_ungradeable_plane(pix_fmt, color_range, src) -> None`
  gains a third refusal. Same signature.
- Produces: `undescribable_plane` — a session-scoped pytest fixture returning a
  `pathlib.Path` to an mp4 whose codec this ffmpeg build cannot open.

**Context.** Of the five values `_probe` derives, four raise or carry a documented
absence word; `pix_fmt`'s `""` alone becomes the number 8 through `plane_depth`, and
the guard then passes a stream nobody can describe. Read design §0.2 for the measured
reachability and §2.2 for why the clause goes in the guard rather than in
`plane_depth` — that function has exactly one production caller and its documented
contract ("the absence of a depth marker in a NAME is eight bits") is true and must
not be weakened.

**The clause must sit before `depth = plane_depth(pix_fmt)`.** Placed after, it is
reached only once `plane_depth` has already given the wrong answer this clause exists
to prevent.

- [ ] **Step 1: Write the failing unit test**

Append to `tests/lib/test_color.py`, immediately after
`test_depth_is_reported_before_range_when_both_are_wrong`:

```python
def test_a_stream_with_no_pix_fmt_is_refused_rather_than_assumed_eight_bit():
    """plane_depth answers 8 for a NAME with no depth marker (yuv420p, nv12,
    gray) and that is correct. An ABSENT name is not such a name — measured, a
    container whose codec this ffmpeg build cannot open reports width, height,
    frame rate and duration from its own boxes and omits pix_fmt, so the other
    four probed values look healthy while the depth is unknown (design §0.2)."""
    with pytest.raises(ValueError) as e:
        color.refuse_ungradeable_plane("", "tv", "/f/unknown_codec.mp4")
    msg = str(e.value)
    assert "pix_fmt" in msg and "/f/unknown_codec.mp4" in msg
    assert "extract" in msg          # the remedy, not just the complaint


def test_the_missing_pix_fmt_is_refused_before_the_range():
    """Order matters twice. The clause must run before plane_depth, or it is
    reached only after the wrong answer is already in hand — and an undescribable
    plane on a pc source must name the pix_fmt, not the range, because re-tagging
    the range would not make the depth knowable."""
    with pytest.raises(ValueError, match="pix_fmt"):
        color.refuse_ungradeable_plane("", "pc", "x.mp4")
```

- [ ] **Step 2: Run to verify both fail**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest "tests/lib/test_color.py::test_a_stream_with_no_pix_fmt_is_refused_rather_than_assumed_eight_bit" "tests/lib/test_color.py::test_the_missing_pix_fmt_is_refused_before_the_range" -v
```

Expected: the first FAILS with `DID NOT RAISE`; the second FAILS because the `pc`
clause raises with a message that does not contain `pix_fmt`.

- [ ] **Step 3: Add the clause**

In `scripts/lib/color.py`, inside `refuse_ungradeable_plane`, insert this
immediately before the existing `depth = plane_depth(pix_fmt)` line:

```python
    if not pix_fmt:
        raise ValueError(
            f"{src}: ffprobe reported no pix_fmt for this stream, so its bit depth "
            f"is unknown — and an unknown depth reads as 8 through plane_depth, "
            f"which answers 8 for a NAME carrying no depth marker (yuv420p, nv12, "
            f"gray). An absent name is not such a name. A container whose codec "
            f"this ffmpeg build cannot open still reports width, height, frame rate "
            f"and duration from its own boxes, so the other four probed values look "
            f"healthy while this one is missing. Cut this source through "
            f"scripts.extract first: it re-encodes to 8-bit yuv420p at the source's "
            f"own resolution.")
```

Then extend the docstring's list of the two silent failures with a third bullet,
directly after the `wrong depth` bullet:

```
      * unknown depth: an absent pix_fmt reads as 8 through plane_depth, which is
        the right answer for a NAME with no depth marker and the wrong one for no
        name at all — measured 2026-09-21 against a container this build has no
        decoder for (design §0.2).
```

- [ ] **Step 4: Run to verify both pass, and the existing guard tests still pass**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/lib/test_color.py -v
```

Expected: all PASS, including the five pre-existing guard tests and the
`plane_depth` parametrization. **`plane_depth` gains no `""` row** — the empty
string is refused one layer up, not redefined (design §4 proof 4).

- [ ] **Step 5: Add the reachability fixture**

Append to `tests/conftest.py`, after the `golden_ride_segment` fixture:

```python
@pytest.fixture(scope="session")
def undescribable_plane(golden_ride_segment, tmp_path_factory):
    """A tv-range segment whose codec this ffmpeg build has no decoder for.

    Built by patching the `stsd` visual sample entry's fourcc from `avc1` to
    `zzzz` — a pure byte edit, no re-encode, nothing committed. The FIRST `avc1`
    in the file is the `ftyp` brand list and must be left alone; the second is
    the sample entry.

    Measured 2026-09-21: ffprobe still reports width, height, avg_frame_rate,
    duration and color_range for this file, because all five come from container
    boxes rather than from the codec — and omits pix_fmt. That is the whole
    negative class for color.refuse_ungradeable_plane's third clause (design
    §0.2), and it is constructed rather than captured: no real file of this kind
    is on this machine (design §5.2).
    """
    data = bytearray(golden_ride_segment.read_bytes())
    first = data.find(b"avc1")
    i = data.find(b"avc1", first + 4)
    if first < 0 or i < 0:
        pytest.skip("golden_ride_segment carries no stsd avc1 sample entry to patch")
    data[i:i + 4] = b"zzzz"
    out = tmp_path_factory.mktemp("media") / "undescribable_plane.mp4"
    out.write_bytes(bytes(data))
    return out
```

- [ ] **Step 6: Write the failing reachability test**

Create `tests/integration/test_unvalidated_shapes.py`:

```python
"""Real-bytes proofs for the 2026-09-21 unvalidated-shapes slice.

Only one of the four items in that slice has a claim that real bytes can settle:
that a stream ffprobe cannot describe actually reaches color's depth guard. The
other three are pure-Python shape defects and are proven in tests/lib and
tests/test_check_episode.py, which need no ffmpeg.
"""
import pytest

from scripts import reframe
from scripts.lib import color

pytestmark = pytest.mark.integration


def test_ffprobe_omits_pix_fmt_for_a_codec_this_build_cannot_open(undescribable_plane):
    """The premise of color.refuse_ungradeable_plane's third clause, measured
    rather than assumed: four of the five values survive and the fifth is gone."""
    w, h, fps, dur, pix_fmt, color_range = reframe._probe(str(undescribable_plane))
    assert (w, h) == (1280, 720)          # from the stsd box, not the codec
    assert fps > 0 and dur > 0            # from stts and mvhd
    assert color_range == "tv"            # from the colr box
    assert pix_fmt == ""                  # the codec's, and the codec did not open


def test_the_depth_guard_refuses_that_stream_instead_of_calling_it_eight_bit(undescribable_plane):
    _, _, _, _, pix_fmt, color_range = reframe._probe(str(undescribable_plane))
    assert color.plane_depth(pix_fmt) == 8      # the wrong answer the guard prevents
    with pytest.raises(ValueError, match="pix_fmt"):
        color.refuse_ungradeable_plane(pix_fmt, color_range, str(undescribable_plane))


def test_the_control_the_same_segment_unpatched_passes_the_guard(golden_ride_segment):
    """Without this the test above proves only that SOMETHING about the file is
    refused. The segment fixture differs from the patched one by four bytes."""
    _, _, _, _, pix_fmt, color_range = reframe._probe(str(golden_ride_segment))
    assert pix_fmt == "yuv420p" and color_range == "tv"
    assert color.refuse_ungradeable_plane(pix_fmt, color_range,
                                          str(golden_ride_segment)) is None
```

- [ ] **Step 7: Run the reachability tests**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/integration/test_unvalidated_shapes.py -v
```

Expected: all three PASS. If `test_ffprobe_omits_pix_fmt_for_a_codec_this_build_cannot_open`
fails with a non-empty `pix_fmt`, this ffmpeg build resolves the format anyway —
report that as a finding and do not weaken the assertion; the fixture's premise is
what is being measured.

- [ ] **Step 8: Run the files that own the guard's call path**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/integration/test_segment_range.py tests/integration/test_reframe.py tests/lib/test_color.py -v
```

Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add scripts/lib/color.py tests/lib/test_color.py tests/conftest.py tests/integration/test_unvalidated_shapes.py
git commit -m "fix(color): refuse a stream with no pix_fmt instead of grading it as 8-bit"
```

---

## Task 3: The chroma reader keys on the same discriminator as its validator

**Files:**
- Modify: `scripts/check_reel.py:355-369` (the `for i, c in enumerate(chroma)` loop)
- Modify: `scripts/lib/color_fidelity.py` — `shift_from_report`'s docstring says
  `_chroma_spread_check` "keys only on `delta_c`/`delta_h`", which this task makes
  false. Correct that clause and nothing else; leave the surrounding argument for
  why the reading carries no `region` key intact.
- Test: `tests/lib/test_check_reel.py`

**Interfaces:**
- Consumes: `check_reel._chroma_spread_check(chroma: list | None, bar: float) -> CheckResult`
  (unchanged signature), `color_fidelity.shift_from_report(report) -> dict` (unchanged)
- Produces: nothing new. The detail dict's keys are unchanged.

**Context.** `ReelEpisode.__post_init__` discriminates on `status == "not-checked"`
and returns early once it sees a non-empty `reason`, never reaching the clause that
requires both numeric components. `_chroma_spread_check` discriminates on
`"delta_c" in c` and then subscripts `c["delta_h"]`. A dict carrying both — reproduced
directly (design §0.3) — constructs fine and raises `KeyError: 'delta_h'` on read.

**Fix the reader, not the validator, and the reason is measured.** `build_reel` builds
`chroma = [e.chroma for e in rm.episodes]`, overwrites `chroma[item.idx]` with
`color_fidelity.shift_from_report(...)` in the reprocess arm, and hands that **plain
list** to `check_reel.run(chroma=...)`. Those values never pass through the dataclass.
Tightening `__post_init__` would close the hand-authored inlet and leave that one
open — the exact shape of half-defence this slice exists to stop shipping.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_check_reel.py`, at the end of the chroma-spread section
(after `test_no_chroma_at_all_is_named_not_zero`):

```python
def test_a_not_checked_chroma_carrying_a_stray_component_lands_among_the_absences():
    """ReelEpisode.__post_init__ returns at status == "not-checked" once it has a
    non-empty reason, so it ADMITS {"status", "reason", "delta_c"}. The reader used
    to test `"delta_c" in c` first, take that as its reading branch, and subscript
    c["delta_h"]: KeyError (design §0.3, reproduced). Keying on the same
    discriminator the validator uses puts the dict where the validator filed it."""
    mixed = {"status": "not-checked", "reason": "no grade_damage block", "delta_c": 1.0}
    cr = _chroma_spread_check([mixed, _reading(-4.18, -1.22)], 5.0)
    assert cr.detail["not_checked"]["0"] == "no grade_damage block"
    assert "0" not in cr.detail["per_episode"]


def test_a_clean_reading_still_reaches_per_episode():
    """The control for the reorder: the reading branch must not have moved."""
    cr = _chroma_spread_check([_reading(-4.18, -1.22), _reading(-2.72, -0.51)], 5.0)
    assert cr.detail["per_episode"] == {"0": [-4.18, -1.22], "1": [-2.72, -0.51]}


def test_a_reprocessed_episodes_reading_reaches_the_reel_check_without_a_reelepisode(monkeypatch, tmp_path):
    """build_reel builds `chroma` as a plain list and overwrites one entry with
    shift_from_report's output before handing it to check_reel.run — so one of the
    reader's two inlets never touches ReelEpisode.__post_init__ (design §0.3). The
    reader's comment claims that validator as its guarantee; this drives the real
    run() wiring with exactly the value that path produces, so the inlet the
    validator does not cover is covered by a test instead.

    Not a build_reel integration test: it pins the shape contract at the seam
    build_reel writes to, not build_reel's own indexing. The driver's wiring is
    tests/lib/test_build_reel.py's business.

    CORRECTION (task review, fix round 1): this test first shipped in the plan as
    `test_the_reprocess_inlet_reaches_the_reader_without_passing_the_validator`,
    calling the PRIVATE `_chroma_spread_check` directly — a name that claimed the
    inlet while the body proved only shift_from_report's output shape. Design §4
    proof 6 asked for `check_reel.run(chroma=...)`, and in a slice about claims
    needing constructions behind them, a test name outrunning its body is the same
    defect in test form. `_run_reel` is the harness that was already there for it.
    """
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    report = {"checks": {"grade_damage": {"region": "crop",
                                          "delta_c": -3.0, "delta_h": 0.5}}}
    fresh = color_fidelity.shift_from_report(report)     # what the reprocess arm writes
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2,
                    chroma=[fresh, _reading(-4.18, -1.22)])
    c = rep.checks["chroma_spread"]
    assert c.detail["per_episode"]["0"] == [-3.0, 0.5]
    assert c.detail["not_checked"] == {}
```

- [ ] **Step 2: Run to verify the first fails**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest "tests/lib/test_check_reel.py::test_a_not_checked_chroma_carrying_a_stray_component_lands_among_the_absences" "tests/lib/test_check_reel.py::test_a_clean_reading_still_reaches_per_episode" "tests/lib/test_check_reel.py::test_the_reprocess_inlet_reaches_the_reader_without_passing_the_validator" -v
```

Expected: the first FAILS with `KeyError: 'delta_h'`; the other two PASS.

- [ ] **Step 3: Swap the branches and correct the comment**

In `scripts/check_reel.py`, replace the loop body at lines 355-369 with:

```python
    for i, c in enumerate(chroma):
        # Keyed on `status` — the SAME discriminator ReelEpisode.__post_init__
        # uses. Keying on `"delta_c" in c` instead made the reader disagree with
        # its own validator: that validator returns early at status ==
        # "not-checked" once it has a non-empty reason, so it admits a dict
        # carrying BOTH a not-checked status and a stray numeric component, and
        # the reading branch then subscripted c["delta_h"] and raised KeyError
        # (design 2026-09-21 §0.3).
        if isinstance(c, dict) and c.get("status") == "not-checked":
            # A bare subscript, never .get: __post_init__ refuses a not-checked
            # chroma whose 'reason' is missing or empty.
            missing[str(i)] = c["reason"]
        elif isinstance(c, dict):
            # Bare subscripts again, and this reader has TWO inlets, so both are
            # named. Through ReelEpisode, __post_init__'s numeric clause requires
            # delta_c and delta_h together. Through build_reel — which builds a
            # plain list and overwrites one entry per reprocessed episode, never
            # constructing a ReelEpisode — every branch of
            # color_fidelity.shift_from_report returns a clean two-key reading or
            # a clean two-key absence. The second inlet is the one the comment
            # here used to omit.
            per[str(i)] = [c["delta_c"], c["delta_h"]]
        else:
            missing[str(i)] = ("the reel manifest is older than this field — "
                               "re-run phase 1 to record it")
```

- [ ] **Step 4: Run to verify all three pass**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/lib/test_check_reel.py -v
```

Expected: all PASS, including the nine pre-existing chroma-spread tests.

- [ ] **Step 5: Run the rest of the chroma carrier**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/integration/test_chroma_spread.py tests/lib/test_models.py tests/lib/test_build_reel.py tests/lib/test_edl_to_reel.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/check_reel.py scripts/lib/color_fidelity.py tests/lib/test_check_reel.py
git commit -m "fix(check_reel): key the chroma reader on status, the discriminator its validator uses"
```

---

## Task 4: grade_chain's comma discipline is written down and machine-checked

**Files:**
- Modify: `scripts/lib/color.py` — `grade_chain`'s docstring, at line 559
- Test: `tests/lib/test_color.py`

**Interfaces:**
- Consumes: `color.grade_chain(gains, *, wb, tone, black_point, shadow_red, mid_blue,
  saturation, highlight, highlight_red, dip, dur) -> str` (unchanged),
  `color.white_balance_arg(means, strength) -> str`,
  `color.tone_arg(src, dst) -> str`, and the eight per-knob builders
- Produces: nothing new. Docstring and tests only — no behaviour change anywhere.

**Context and scope.** Backlog row R2.8 said `grade_chain` "composes pre-built
fragments under a three-way comma convention and validates none of it — it produced
1.5 KB of ffmpeg garbage during the run". Design §0.4 refutes all three claims: a
maximal **legal** chain is 1206 bytes across 23 filters (a real-run-shaped one is
842, and `tone_arg` alone is a 437-byte 32-point LUT expression), every builder does
validate its own argument and raises with a remedy, and a comma error is a loud
ffmpeg parse failure rather than silent corruption. The row closes ⊘ in Task 5.

**Do not add argument validation to `grade_chain`.** That is what was measured away.
This task ships only what survived: the discipline stated, and a property test over
the composition.

- [ ] **Step 1: Write the failing enumeration test**

Append to `tests/lib/test_color.py`:

```python
def test_the_grade_chain_is_well_formed_for_every_combination_of_knobs():
    """The comma discipline, as a property over the composition rather than a
    restatement of the docstring: every fragment before mixer_arg is empty or ends
    with a comma, mixer_arg is never empty and carries none at either end, and every
    fragment after it is empty or begins with one. The whole expression therefore
    never has an empty filter slot.

    Enumerated over all 1024 combinations of the ten knobs at identity versus one
    legal non-identity value. Pure string construction — no ffmpeg. The discipline
    rests entirely on mixer_arg being unconditional, which is one plausible "the
    gains are 1.0, emit nothing" edit away from breaking; this is the test that
    would catch it (design §0.4/§2.4)."""
    import itertools
    wb_on = color.white_balance_arg((100.0, 110.0, 120.0), 1.0)
    tone_on = color.tone_arg((40.0, 120.0, 200.0), (52.0, 103.5, 191.5))
    axes = [
        ("wb", "", wb_on),
        ("tone", "", tone_on),
        ("gains", (1.0, 1.0, 1.0), (1.05, 1.0, 0.95)),
        ("black_point", 0.0, color.BLACK_POINT_MAX),
        ("shadow_red", 0.0, color.SHADOW_RED_MAX),
        ("mid_blue", 1.0, 1.2),
        ("saturation", 1.0, 0.5),
        ("highlight", 1.0, 0.6),
        ("highlight_red", 0.0, color.HIGHLIGHT_RED_MAX),
        ("dip", 0.0, 0.5),
    ]
    seen = 0
    for combo in itertools.product(*[(off, on) for _, off, on in axes]):
        kw = {name: value for (name, _, _), value in zip(axes, combo)}
        gains = kw.pop("gains")
        out = color.grade_chain(gains, dur=4.0, **kw)
        assert ",," not in out, f"empty filter slot with {kw}"
        assert not out.startswith(","), f"leading comma with {kw}"
        assert not out.endswith(","), f"trailing comma with {kw}"
        assert out, f"empty chain with {kw}"
        seen += 1
    assert seen == 1024        # the enumeration ran; a silent product() bug would not


def test_each_builder_sits_on_its_own_side_of_the_mixer_pivot():
    """The per-builder half of the discipline, so a new builder added on the wrong
    side fails with a message saying which side it belongs on."""
    before = [("white_balance_arg", color.white_balance_arg((100.0, 110.0, 120.0), 1.0)),
              ("tone_arg", color.tone_arg((40.0, 120.0, 200.0), (52.0, 103.5, 191.5))),
              ("black_point_arg", color.black_point_arg(color.BLACK_POINT_MAX))]
    after = [("shadow_red_arg", color.shadow_red_arg(color.SHADOW_RED_MAX)),
             ("mid_blue_arg", color.mid_blue_arg(1.2)),
             ("saturation_arg", color.saturation_arg(0.5)),
             ("highlight_arg", color.highlight_arg(0.6)),
             ("highlight_red_arg", color.highlight_red_arg(color.HIGHLIGHT_RED_MAX)),
             ("dip_arg", color.dip_arg(0.5, 4.0))]
    for name, frag in before:
        assert frag.endswith(","), f"{name} runs BEFORE mixer_arg: end with a comma"
        assert not frag.startswith(","), f"{name} runs BEFORE mixer_arg: no leading comma"
    for name, frag in after:
        assert frag.startswith(","), f"{name} runs AFTER mixer_arg: begin with a comma"
        assert not frag.endswith(","), f"{name} runs AFTER mixer_arg: no trailing comma"
    pivot = color.mixer_arg(1.0, 1.0, 1.0)
    assert pivot, "mixer_arg is the pivot and is never empty — the whole discipline rests on it"
    assert not pivot.startswith(",") and not pivot.endswith(",")
```

- [ ] **Step 2: Run to verify both pass**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest "tests/lib/test_color.py::test_the_grade_chain_is_well_formed_for_every_combination_of_knobs" "tests/lib/test_color.py::test_each_builder_sits_on_its_own_side_of_the_mixer_pivot" -v
```

Expected: **both PASS immediately.** This is a characterization test of behaviour that
is already correct — that is the finding, not a failure of TDD. If either fails, the
design's §0.4 measurement is wrong and you must report that before changing any code.

- [ ] **Step 3: Prove the enumeration discriminates**

Temporarily make `mixer_arg` return `""` at unit gains. `scripts/lib/color.py` is
committed, so the safe restore is `git show HEAD:scripts/lib/color.py > scripts/lib/color.py`;
run this on an otherwise-clean tree and re-check `git diff --stat` afterwards.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest "tests/lib/test_color.py::test_the_grade_chain_is_well_formed_for_every_combination_of_knobs" -q
git show HEAD:scripts/lib/color.py > scripts/lib/color.py
git diff --stat
```

Expected: RED before the restore (an empty filter slot with a wb or tone fragment
present), and an empty `git diff --stat` after. Record the failure message in the
task report.

- [ ] **Step 4: State the discipline in the docstring**

In `scripts/lib/color.py`, append to `grade_chain`'s docstring, after the sentence
ending "...before it reaches here.":

```
    The comma discipline, stated because nothing else states it: every fragment
    BEFORE mixer_arg (`wb`, `tone`, black_point_arg) is either "" or ends with a
    comma; mixer_arg is the pivot, is NEVER "" and carries a comma at neither end;
    every fragment AFTER it is either "" or begins with a comma and does not end
    with one. That is what makes any subset of knobs compose into a filtergraph
    with no empty slot. It rests entirely on mixer_arg being unconditional — an
    identity branch there would fuse a wb/tone trailing comma against a
    shadow_red leading one. Pinned by
    tests/lib/test_color.py::test_the_grade_chain_is_well_formed_for_every_combination_of_knobs,
    which enumerates all 1024 on/off combinations (design 2026-09-21 §2.4).
```

- [ ] **Step 5: Run the colour suite**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/lib/test_color.py tests/integration/test_colour_stage.py tests/integration/test_reframe.py -v
```

Expected: all PASS, no golden moved.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/color.py tests/lib/test_color.py
git commit -m "test(color): pin grade_chain's comma discipline over all 1024 knob combinations"
```

---

## Task 5: Mutation battery, docs, and the four backlog closures

**Files:**
- Modify: `docs/backlog.md`, `docs/backlog-closed.md`, `docs/build-status.md`,
  `CHANGELOG.md`, `.claude-plugin/plugin.json`, `CLAUDE.md`
- Test: the whole suite

**Interfaces:**
- Consumes: everything Tasks 1-4 produced.
- Produces: version `0.12.1`.

**Context.** Every mutation below is a one-line edit to a committed file. The safe
restore for each is `git show HEAD:<path> > <path>`; run each mutation on an
otherwise-clean tree and re-check `git diff --stat` after restoring. Run the whole
battery under `PYTHONDONTWRITEBYTECODE=1`. Quote every pytest selection — zsh does
not word-split an unquoted variable, and an unquoted selection arrives as one
argument and prints `no tests ran`, which reads exactly like a non-discriminating row.

- [ ] **Step 1: Run the 10-row mutation battery**

| # | File | Mutation | Must go RED |
|---|---|---|---|
| 1 | `check_episode.py` | delete the `if not pairs: raise` block | `test_a_region_that_refused_nothing_but_holds_no_pixels_is_a_contract_break` |
| 2 | `check_episode.py` | change the refusal's `f"...{'crop' if fallback else 'subject'}..."` to a bare `"region"` | same test (it asserts `"subject" in msg`) |
| 3 | `check_episode.py` | drop `regions.subject_mask` from the refusal message | same test (it asserts the break's location is named) |
| 4 | `check_episode.py` | revert the branch: `unchecked = "status" in d` computed after the update | `test_the_verdict_is_read_from_the_verdict_not_from_the_merge` |
| 5 | `color.py` | delete the `if not pix_fmt:` clause | `test_a_stream_with_no_pix_fmt_is_refused_rather_than_assumed_eight_bit` and `test_the_depth_guard_refuses_that_stream_instead_of_calling_it_eight_bit` |
| 6 | `color.py` | move the `if not pix_fmt:` clause below the `color_range == "pc"` clause | `test_the_missing_pix_fmt_is_refused_before_the_range` |
| 7 | `color.py` | drop `extract` from the new refusal's message | `test_a_stream_with_no_pix_fmt_is_refused_rather_than_assumed_eight_bit` |
| 8 | `check_reel.py` | revert the two branches to their old order (`"delta_c" in c` first) | `test_a_not_checked_chroma_carrying_a_stray_component_lands_among_the_absences` |
| 9 | `check_reel.py` | change `c.get("status") == "not-checked"` to `"status" in c` | **expected GREEN** — every shape either inlet produces spells the status exactly that way, so the two predicates are indistinguishable on reachable input. Record the non-discrimination; do NOT add a test that constructs an unreachable third status value purely to make a row red. |
| 10 | `color.py` | make `mixer_arg` return `""` at unit gains | `test_the_grade_chain_is_well_formed_for_every_combination_of_knobs` |

Rows 1-8 and 10 must go RED. Row 9 is expected GREEN and its silence is the finding.
For any other row that comes back GREEN: the row is a real coverage hole. Report it,
then close it with a NEW test that discriminates — never by weakening the mutation.

Record the roll-call (row, mutation, test, RED/GREEN) for `docs/build-status.md`.

- [ ] **Step 2: Run the whole suite**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
```

Expected: PASS, with the count up by the new tests: **3** in Task 1, **5** in Task 2
(two unit, three integration), **3** in Task 3, **2** in Task 4 — **13** in total. Record the exact before/after counts; the pre-slice baseline is
**3956 passed / 1 skipped**.

- [ ] **Step 3: Bump the version**

`.claude-plugin/plugin.json` and the new `CHANGELOG.md` entry must both read
`0.12.1`. PATCH, not MINOR: no contract field, no check and no threshold changed
(design §3). `tests/test_plugin_manifests.py` enforces that the top CHANGELOG entry
matches the manifest.

Add to `CHANGELOG.md` above the `0.12.0` entry:

```markdown
## 0.12.1 — unvalidated shapes

Three latent defects closed and one backlog row closed by measurement. A reader
may no longer rely on an invariant that only a comment asserts.

- `check_episode._grade_damage` reads its verdict from the verdict's own dict
  instead of from the flat merge with the dE00 advisory, and the advisory can no
  longer return a `{status, reason}` absence at all — it raises, because the region
  it reads holds pixels by construction. Until now an advisory absence would have
  overwritten the discriminator and turned a BLOCKING entropy verdict into
  `passed=None`. Unreachable then; impossible now.
- `color.refuse_ungradeable_plane` refuses a stream whose `pix_fmt` ffprobe did not
  report, instead of grading it as 8-bit. Measured: a container whose codec this
  build cannot open still reports width, height, frame rate, duration and range
  from its own boxes, so four of the five probed values look healthy while
  `plane_depth("")` answers 8.
- `check_reel._chroma_spread_check` keys on `status`, the same discriminator
  `ReelEpisode.__post_init__` uses. A dict carrying both a `not-checked` status and
  a stray `delta_c` constructed fine and raised `KeyError` on read. Fixed in the
  reader, not the validator: `build_reel` hands the reader a plain list the
  validator never sees.
- `color.grade_chain`'s comma discipline is stated and pinned over all 1024 knob
  combinations. Backlog row R2.8 closes ⊘: a maximal LEGAL chain is 1206 bytes
  across 23 filters, every builder validates its own argument, and a comma error is
  a loud ffmpeg parse failure — so "1.5 KB of ffmpeg garbage" is not evidence of
  anything, and the retro section the row cites mentions none of it.
```

- [ ] **Step 4: Close the four backlog rows**

Move all four P2 rows out of `docs/backlog.md` into `docs/backlog-closed.md` under
*Closed from P2*, each with the closure note its own measurement earned:

- the `_grade_damage` flat-merge row — closed by construction, and note that the
  collision surface was measured at exactly `{status, reason}` and that
  `check_episode.py:242` was the only one of 17 dict-merge sites in `scripts/` that
  both merges two independently produced mappings and then discriminates on a shared
  key.
- the `_probe` fail-open row — closed, and note the constructed negative class and
  that reachability was established with real bytes rather than by inspection.
- the `ReelEpisode.chroma` discriminator row — closed in the reader, and note the
  measured reason: `build_reel`'s plain-list inlet does not pass the validator, so
  tightening the validator would have closed one of two paths.
- **R2.8 — closed ⊘**, with §0.4's numbers (1206 / 842 / 437 bytes, 23 filters), the
  fact that the cited retro section contains no mention of `grade_chain`, 1.5 KB or
  garbage, that the only "1.5" in the colour record is a luma-code residual in an
  archived row, and that a comma error is loud. Say plainly what was NOT proven:
  that the run's chain was correct (design §5.3).

Then file design §6's three deferrals as new rows in `docs/backlog.md`:
one validator for `check_reel.run(chroma=...)`'s inlets (S); a real `pix_fmt`-less
camera source (S, blocked on footage); a note on the other two two-producer merges
(S).

**Re-count the archive.** `docs/backlog-closed.md`'s header and `CLAUDE.md`'s registry
row both carry a count that was **63** at 2026-09-17. Recount by hand — `grep -c` is
wrong in two directions, as that header itself explains — and update both.

- [ ] **Step 5: Update build-status, pipeline-map and the registry**

- `docs/build-status.md`: a Done entry naming the slice, the mutation-battery
  roll-call from Step 1, the suite count from Step 2, and the one non-discriminating
  row with its reason.
- `CLAUDE.md`: two new Quick Reference rows (design and plan), in the same style as
  the chroma-spread pair above them, plus the corrected archive count.
- `docs/pipeline-map.md`: only if a stage's status changed. It did not — check and
  say so rather than editing for the sake of it.

- [ ] **Step 6: Final whole-suite run and commit**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
```

```bash
git add docs/backlog.md docs/backlog-closed.md docs/build-status.md CHANGELOG.md .claude-plugin/plugin.json CLAUDE.md
git commit -m "docs: close three latent-defect rows and R2.8, bump to 0.12.1"
```

---

## Self-Review

**Spec coverage.** §2.1 → Task 1. §2.2 → Task 2. §2.3 → Task 3. §2.4 → Task 4. §3
(nothing changes) → Task 1 Step 8, Task 2 Step 8, Task 3 Step 5, Task 4 Step 5, all
of which run the modules that would notice. §4 proofs 1-2 → Task 1 Steps 1 and 3;
proof 3 → Task 2 Steps 5-7; proof 4 → Task 2 Step 4's explicit "no `""` row"; proofs
5-6 → Task 3 Step 1; proof 7 → Task 4 Steps 1 and 3. §6 deferrals → Task 5 Step 4.
§0.4's closure numbers → Task 5 Step 4. No section is unimplemented.

**Placeholder scan.** Every code step carries the code, and every path in every
command was resolved against the tree before this plan was written — including
`tests/integration/test_segment_range.py`, `tests/lib/test_build_reel.py` and the
`CheckSpec(composition=, grid=, target_dur=)` signature Task 1 Step 3 uses.

**Type consistency.** `_subject_delta_advisory(plain_frames, graded_frames, times,
route_pts, path_obj, meta) -> dict` and `_chroma_spread_check(chroma, bar) ->
CheckResult` keep their signatures in every task that names them.
`refuse_ungradeable_plane(pix_fmt, color_range, src) -> None` is unchanged.
`undescribable_plane` is introduced in Task 2 Step 5 and consumed in Step 6 of the
same task and nowhere else.

**One known asymmetry, stated deliberately.** Task 4's tests pass on the unmodified
build. That is not a TDD violation to be worked around — the code is already correct
and the measurement said so; Step 3's mutation is what earns the test its place.
