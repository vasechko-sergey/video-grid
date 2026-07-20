# Stabilization apply — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** make `stabilize: true` do something — a `vidstabdetect`/`vidstabtransform` pre-stage that produces a stabilized copy of the segment, which both the tracker and `reframe` then read.

**Architecture:** stabilization is a **pre-stage in `process_episode`, not a filter in `reframe`'s chain**. The route is measured on unstabilized pixels; placing a crop from it against transformed pixels leaves the subject offset by exactly the shake vidstab removed, and no gate catches it (design 2026-07-20 §1). Writing a separate file that both `track` and `reframe` read puts route and pixels in one coordinate system by construction. A new `scripts/lib/vidstab.py` holds the primitives, mostly extracted from `intake.py`, which becomes its second consumer.

**Tech Stack:** Python 3.13, ffmpeg (`ffmpeg-full`, libvidstab) via `scripts/lib/ffbin.py`, pytest.

**Design spec:** [docs/specs/2026-07-20-stabilize-apply-design.md](../specs/2026-07-20-stabilize-apply-design.md). Read §1 before Task 7 — the whole shape of that task follows from it.

---

## Ground rules (this repo)

- Run scripts as modules: `.venv/bin/python -m scripts.foo`. `pytest.ini` sets `pythonpath = .`.
- Python is `.venv/bin/python` (3.13.2). There is no `timeout(1)` on this machine.
- Never pipe pytest through `tail`; append `; echo "EXIT: $?"` instead.
- Config-specs validate in `__post_init__` and raise `ValueError` carrying a remedy.
- Whole-object asserts where practical (`assert x.to_dict() == {...}`), not field-by-field.
- Mutation checks in this plan are **steps, not suggestions**. Before each, purge stale bytecode:
  ```bash
  find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest <target> -p no:cacheprovider
  ```
- Commit after every task. Commit bodies end with:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- **Do not run installers** (`brew`, `pip install`, `setup.sh`). The environment is already provisioned: `ffmpeg-full` is installed and `config/ffmpeg.env` points at it.

## Baseline

Before Task 0, record the starting suite state:

```bash
.venv/bin/python -m pytest -q; echo "EXIT: $?"
```

Expected: `1539 passed, 2 skipped` (the two survivors are `test_offset`'s demucs opt-in and `test_sourcing`'s SSL certificate failure — both pre-existing and unrelated). Note the number; Task 10 compares against it.

---

## File Structure

| file | responsibility |
|---|---|
| **create** `scripts/lib/vidstab.py` | every vidstab interaction: the capability gate, `.trf` read/parse, the detect pass, the shake normalisation, and the two-pass `stabilize()` pre-stage |
| **create** `tests/lib/test_vidstab.py` | its unit tests, including the ones migrating out of `test_intake.py` |
| **create** `tests/integration/test_stabilize.py` | the real-ffmpeg proofs (residual falls; no black edge; end-to-end through `process_episode`) |
| modify `scripts/intake.py` | drops the `.trf` primitives, imports them; `shake_by_window` delegates to `vidstab.detect` |
| modify `tests/lib/test_intake.py` | the migrated tests leave; the two timeout tests re-point at `vidstab` |
| modify `scripts/lib/models.py` | `PathMeta.stabilized`; delete `ReframeSpec.stabilize` and its refusal |
| modify `scripts/reframe.py` | `reframe(..., stabilized=False)` → the sidecar |
| modify `scripts/lib/manifest.py` | delete the `stabilize=true` refusal; add the capability gate |
| modify `scripts/lib/edl.py` | `EDLEpisode.stabilize` + the `to_manifest_dict` bridge |
| modify `scripts/process_episode.py` | the pre-stage, the two re-pointed call sites, the result key |

---

## Task 0: `scripts/lib/vidstab.py` — extraction

Move the `.trf` primitives out of `intake.py` without changing behaviour. `intake` has been the only vidstab consumer; a second one arrives in Task 3. This is the same extraction `scripts/lib/appearance.py` got out of `intake.py` in the cast → hero-pin slice.

**Files:**
- Create: `scripts/lib/vidstab.py`
- Create: `tests/lib/test_vidstab.py`
- Modify: `scripts/intake.py` (delete `_LM_RE`, `_read_trf`, `_parse_trf`, `_require_vidstab`, `SHAKE_TIMEOUT_REALTIME_MULTIPLE`; import them)
- Modify: `tests/lib/test_intake.py` (five tests + `_TRF` move out; two re-point)

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/test_vidstab.py`:

```python
"""vidstab — the one place this repo talks to libvidstab (design 2026-07-20 §3)."""
import types

import pytest

from scripts.lib import ffbin, vidstab


def _filters(monkeypatch, text: str) -> None:
    """Stand in for `ffmpeg -filters` output. Patch the RESOLVER's proc, because
    that is where ffbin.has_filter issues the probe (design 2026-07-20 §5)."""
    monkeypatch.setattr(ffbin.proc, "run",
                        lambda *a, **k: types.SimpleNamespace(stdout=text.encode()))


def test_require_is_silent_when_both_filters_are_present(monkeypatch):
    _filters(monkeypatch, " .. vidstabdetect ...\n .. vidstabtransform ...\n")
    assert vidstab.require() is None


def test_require_raises_when_detect_is_absent(monkeypatch):
    _filters(monkeypatch, " .. scale ...\n .. overlay ...\n")
    with pytest.raises(ValueError, match="vidstabdetect"):
        vidstab.require()


def test_require_raises_when_only_transform_is_absent(monkeypatch):
    """The gate used to check vidstabdetect alone, which was honest while detect
    was the only pass. Now that stabilize() issues a transform, a build carrying
    one filter and not the other must not pass — libvidstab supplies both or
    neither, so this failing means something stranger than a missing library."""
    _filters(monkeypatch, " .. vidstabdetect ...\n .. scale ...\n")
    with pytest.raises(ValueError, match="vidstabtransform"):
        vidstab.require()


_TRF = "\n".join([
    "VID.STAB 1",
    "Frame 1 (List 0 [])",
    "Frame 2 (List 2 [(LM 3 4 100 100 0.5 0.9) (LM 6 8 200 200 0.5 0.9)])",  # mags 5, 10 → median 10
    "Frame 3 (List 1 [(LM 0 0 100 100 0.5 0.9)])",                            # mag 0
])


def test_parse_trf_median_magnitudes():
    assert vidstab.parse_trf(_TRF) == [0.0, 10.0, 0.0]


def test_parse_trf_bad_header_raises():
    with pytest.raises(ValueError, match="unrecognized header"):
        vidstab.parse_trf("not a vidstab file\nFrame 1 (List 0 [])")


def test_parse_trf_empty_raises():
    with pytest.raises(ValueError, match="empty .trf"):
        vidstab.parse_trf("")


def test_a_binary_trf_names_the_format_and_the_option(tmp_path):
    """libvidstab's DEFAULT serializer is binary and this parser reads the ASCII
    one, so this is the shape a caller hits when `fileformat=ascii` goes missing.
    Before the guard, Path.read_text() raised UnicodeDecodeError several frames
    up, naming a byte offset instead of a remedy."""
    trf = tmp_path / "t.trf"
    trf.write_bytes(b"TRF1\x0f\x00\x00\x00\x05\x00\x00\x00\xd0?")
    with pytest.raises(ValueError, match="BINARY .trf.*fileformat=ascii"):
        vidstab.read_trf(trf)


def test_an_undecodable_trf_with_no_known_magic_still_fails_loud(tmp_path):
    trf = tmp_path / "t.trf"
    trf.write_bytes(b"\xd0\xd0\xd0 not utf-8 and not TRF")
    with pytest.raises(ValueError, match="cannot trust the shake estimate"):
        vidstab.read_trf(trf)


def test_ascii_trf_decodes_unchanged(tmp_path):
    trf = tmp_path / "t.trf"
    trf.write_text(_TRF)
    assert vidstab.read_trf(trf) == _TRF
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_vidstab.py -q; echo "EXIT: $?"`
Expected: collection error — `ImportError: cannot import name 'vidstab'`.

- [ ] **Step 3: Create the module**

Create `scripts/lib/vidstab.py`:

```python
"""Every libvidstab interaction in this repo (design 2026-07-20 §3).

Two consumers: intake measures shake per candidate window (§5.2), and
process_episode stabilizes a segment before tracking it (§1 of the same design —
stabilization CANNOT be a filter in reframe's chain, because the route is
measured on unstabilized pixels).

Extracted from intake.py, which held these as privates while it was the only
consumer — the same move scripts/lib/appearance.py made in the cast slice.
"""
import re
from pathlib import Path

from scripts.lib import ffbin, proc

# vidstabdetect over a whole raw clip is the one analysis in this repo whose
# input is unbounded raw footage; everything else works on 15-60s reels or
# extracted windows. A same-class motion-estimation proxy (mestimate=epzs)
# measured 13.6 fps analysing 4K/30 footage — ~2.2x realtime — and 4K/60 doubles
# the per-second frame count, so ~4.4x realtime is the worst measured case. 10x
# leaves > 2x headroom above that for slower hardware or larger frames.
#
# stabilize() reuses the same multiple on a SHORT extracted segment, where it is
# simply generous rather than load-bearing. The floor below keeps both cases at
# proc's already-generous default when the input is short.
SHAKE_TIMEOUT_REALTIME_MULTIPLE = 10.0

_LM_RE = re.compile(r"\(LM\s+(-?\d+)\s+(-?\d+)")

_REMEDY = ("Run `bash setup.sh`, which installs ffmpeg-full (libvidstab included) "
           "and records where it landed")


def require() -> None:
    """Fail loud unless the resolved ffmpeg carries BOTH vidstab filters.

    Both, not just detect: libvidstab supplies the pair, so checking one and
    using the other would let a strange build through to a mid-encode failure.
    Called at the ENTRY points (intake's shake_by_window, and stabilize below) —
    deliberately not inside detect(), so one stabilize() does not pay three
    uncached `ffmpeg -filters` probes for one operation.
    """
    ffbin.require_filter("vidstabdetect", _REMEDY)
    ffbin.require_filter("vidstabtransform", _REMEDY)


def read_trf(path: Path) -> str:
    """Decode a .trf, turning the binary-format case into the loud error the parser
    already meant to raise.

    parse_trf promises to fail loud on an unrecognized header rather than report a
    silent shake=0 — but it could never keep that promise against a binary file,
    because `Path.read_text()` raises UnicodeDecodeError several frames earlier,
    naming a byte offset instead of a remedy. Checking the magic on bytes first puts
    the intended error back within reach.
    """
    raw = path.read_bytes()
    if raw.startswith(b"TRF"):
        raise ValueError(
            f"vidstabdetect wrote a BINARY .trf (magic {raw[:4]!r}) — this parser reads "
            "the ASCII serializer. `fileformat=ascii` on the vidstabdetect call selects "
            "it; libvidstab's own default is binary")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(
            f"vidstabdetect .trf at {path} is neither UTF-8 text nor a known binary "
            "format — cannot trust the shake estimate") from e


def parse_trf(text: str) -> list[float]:
    """Per-frame shake magnitude (median localmotion vector length, px) from a
    libvidstab VID.STAB transforms file. Fail loud on an unrecognized header —
    never a silent shake=0 (the format is libvidstab-version dependent)."""
    lines = text.splitlines()
    if not lines:
        raise ValueError("vidstabdetect produced an empty .trf (no transforms) — the analysis "
                         "failed; check the clip is readable")
    if not lines[0].startswith("VID.STAB"):
        raise ValueError("vidstabdetect .trf has an unrecognized header — libvidstab version mismatch? "
                         "cannot trust the shake estimate (run `bash setup.sh`)")
    mags: list[float] = []
    for line in lines[1:]:
        if not line.startswith("Frame"):
            continue
        lms = _LM_RE.findall(line)
        if lms:
            vecs = sorted((int(x) ** 2 + int(y) ** 2) ** 0.5 for x, y in lms)
            mags.append(vecs[len(vecs) // 2])          # upper-median localmotion magnitude
        else:
            mags.append(0.0)
    return mags
```

- [ ] **Step 4: Run the new tests**

Run: `.venv/bin/python -m pytest tests/lib/test_vidstab.py -q; echo "EXIT: $?"`
Expected: `9 passed`.

- [ ] **Step 5: Rewire `intake.py`**

In `scripts/intake.py`, add `vidstab` to the lib import:

```python
from scripts.lib import assembly, ffbin, footage, proc, vidstab
```

Delete these five definitions entirely: `SHAKE_TIMEOUT_REALTIME_MULTIPLE` (and its
comment block), `_LM_RE`, `_require_vidstab`, `_read_trf`, `_parse_trf`.

Replace the body of `shake_by_window` (keep its signature and docstring, updating
the docstring's last paragraph as shown):

```python
def shake_by_window(clip: str, windows: list[tuple[float, float]], fps: float,
                    res: tuple[int, int], dur: float) -> list[float]:
    """vidstabdetect once per clip → per-frame magnitudes → averaged per window,
    normalized by frame width. No per-window cutting → no -ss seek landmine.

    `dur` (the clip's own length, already probed by the caller) scales the timeout
    vidstab.detect hands to proc.run: this pass runs over the WHOLE raw clip, so
    proc's flat default is not generous enough for a long take. The detect recipe
    and the timeout derivation both live in scripts/lib/vidstab.py, shared with
    process_episode's stabilize pre-stage so the two report the same measurement
    (design 2026-07-20 §5).
    """
    vidstab.require()
    with tempfile.TemporaryDirectory() as d:
        mags = vidstab.detect(clip, str(Path(d) / "t.trf"), dur)
    return _windowed_shake(mags, windows, fps, res[0])
```

`vidstab.detect` does not exist yet — Task 2 builds it. For THIS task, leave
`shake_by_window`'s body as it is and only swap the primitives it calls:

```python
    vidstab.require()
    timeout = max(proc.DEFAULT_TIMEOUT_S, dur * vidstab.SHAKE_TIMEOUT_REALTIME_MULTIPLE)
    with tempfile.TemporaryDirectory() as d:
        trf = str(Path(d) / "t.trf")
        # fileformat=ascii is REQUIRED, not a preference: libvidstab defaults to a
        # BINARY .trf (magic "TRF1") while parse_trf reads the ASCII serializer's
        # "VID.STAB" text. Omitting it does not degrade gracefully — the read dies on
        # the first non-UTF-8 byte.
        proc.run([ffbin.ffmpeg(), "-y", "-i", clip, "-vf",
                  f"vidstabdetect=result={trf}:fileformat=ascii", "-f", "null", "-"],
                 timeout=timeout)
        mags = vidstab.parse_trf(vidstab.read_trf(Path(trf)))
    return _windowed_shake(mags, windows, fps, res[0])
```

- [ ] **Step 6: Migrate the tests out of `tests/lib/test_intake.py`**

Delete from `tests/lib/test_intake.py`: `test_require_vidstab_raises_when_absent`,
`test_require_vidstab_ok_when_present`, `_TRF`,
`test_parse_trf_median_magnitudes`, `test_parse_trf_bad_header_raises`,
`test_a_binary_trf_names_the_format_and_the_option`,
`test_an_undecodable_trf_with_no_known_magic_still_fails_loud`,
`test_ascii_trf_decodes_unchanged`.

In the two surviving timeout tests, re-point the two names that moved. Replace
`monkeypatch.setattr(intake, "_require_vidstab", lambda: None)` with
`monkeypatch.setattr(vidstab, "require", lambda: None)` in both, and
`intake.SHAKE_TIMEOUT_REALTIME_MULTIPLE` with
`vidstab.SHAKE_TIMEOUT_REALTIME_MULTIPLE`. Add `vidstab` to the import line:

```python
from scripts.lib import appearance, ffbin, vidstab
```

`monkeypatch.setattr(intake.proc, "run", ...)` in `_stub_vidstabdetect_run`
needs **no change**: Python caches modules, so `intake.proc is vidstab.proc` — one
object, and patching an attribute on it patches it for every importer. Do not
"fix" this into two patches.

If `ffbin` becomes unused in `tests/lib/test_intake.py` after the deletions, drop
it from the import; if `types` becomes unused, drop that too.

- [ ] **Step 7: Run both test files**

Run: `.venv/bin/python -m pytest tests/lib/test_vidstab.py tests/lib/test_intake.py -q; echo "EXIT: $?"`
Expected: all pass; `test_intake.py` has 8 fewer tests than before, `test_vidstab.py` has 9.

- [ ] **Step 8: Run the whole suite**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"`
Expected: same pass count as the Baseline (tests moved, none added or lost — the migrated 8 became 9 because `test_parse_trf_empty_raises` is new).

- [ ] **Step 9: Commit**

```bash
git add scripts/lib/vidstab.py scripts/intake.py tests/lib/test_vidstab.py tests/lib/test_intake.py
git commit -F - <<'EOF'
refactor: extract the vidstab primitives out of intake

intake has been the only libvidstab consumer, so the .trf reader, the
parser, the capability gate and the timeout derivation lived there as
privates. process_episode becomes the second consumer in this slice, so
they move to scripts/lib/vidstab.py — the same extraction appearance.py
made out of the same file in the cast slice.

require() now checks vidstabtransform as well as vidstabdetect. Checking
detect alone was honest while detect was the only pass; it is not once
something issues a transform, and libvidstab supplies both filters or
neither.

Behaviour is unchanged; the migrated tests move with the code.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Task 1: one detect recipe, shared with intake

Design §5. `intake` detects at the binary's default `shakiness=5`; the recipe in design spec §10 uses `8`. Left apart, `FOOTAGE.md` and `process_episode` would print two different measurements under the same word. Unify at `8`; intake's numbers move.

**Files:**
- Modify: `scripts/lib/vidstab.py`
- Modify: `scripts/intake.py`
- Modify: `tests/lib/test_vidstab.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_vidstab.py`:

```python
def test_the_detect_recipe_sets_shakiness_and_nothing_that_is_already_default():
    """Design §4/§5. `shakiness=8` is the one non-default detect option — accuracy
    is 15 by default, so writing it would perform a choice that was never made and
    a later reader could not tell the two apart. The transform pass's options are
    a different namespace and belong in TRANSFORM_ARGS, not here.

    This is pinned rather than left to review because the constant is SHARED with
    intake specifically so both report the same measurement (§5). Anyone adding a
    knob here silently re-scales FOOTAGE.md's shake column.
    """
    assert vidstab.DETECT_ARGS == "shakiness=8"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_vidstab.py::test_the_detect_recipe_sets_shakiness_and_nothing_that_is_already_default -q; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: module 'scripts.lib.vidstab' has no attribute 'DETECT_ARGS'`.

- [ ] **Step 3: Add the constant**

In `scripts/lib/vidstab.py`, below `SHAKE_TIMEOUT_REALTIME_MULTIPLE`:

```python
# The detect recipe, shared by BOTH consumers on purpose (design 2026-07-20 §5).
# intake used to detect at the binary's default shakiness=5 while the §10 recipe
# asked for 8; two different measurements would then have appeared under one word
# — "shake" in FOOTAGE.md and "before" in process_episode's result — with nothing
# saying they were incomparable. Changing this re-scales both.
#
# shakiness=8 is the only non-default here. The recipe's other detect option,
# accuracy=15, is the binary's own default (probed with `-h filter=vidstabdetect`),
# and spelling a default performs a choice that was never made. Nothing else in
# the recorded recipe belongs in this string: the transform pass has its own
# option namespace, and its knobs live in TRANSFORM_ARGS.
DETECT_ARGS = "shakiness=8"
```

**Corrected mid-slice.** This comment first said "accuracy=15 and optzoom=1 are
the binary's own defaults (probed with `ffmpeg -h filter=vidstabdetect`)". That
command lists no `optzoom` — it is a `vidstabtransform` option. Review caught it
against the real binary. The design spec's §4 table has been split by pass, which
is where the conflation came from.

- [ ] **Step 4: Use it in `intake.shake_by_window`**

In `scripts/intake.py`, change the `-vf` value:

```python
                  f"vidstabdetect={vidstab.DETECT_ARGS}:result={trf}:fileformat=ascii",
```

- [ ] **Step 5: Note the consequence at `SHAKY_CLIP`**

In `scripts/intake.py`, extend the `SHAKY_CLIP` comment:

```python
SHAKY_CLIP = 0.02   # shake (fraction of frame width) above which a clip is shaky — tune on real footage.
                    # Its INPUT changed on 2026-07-20: the detect pass moved from the binary's default
                    # shakiness=5 to vidstab.DETECT_ARGS' 8, so recorded shake values shifted. The
                    # threshold is deliberately NOT re-tuned to compensate — no real footage has been
                    # through this pipeline, so any new value would be invented (design §5).
```

- [ ] **Step 6: Run the suite and fix whatever the number move breaks**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"`

`tests/integration/test_intake.py::test_intake_real_vidstab_shake` may now assert
against a different magnitude. Read the failure, confirm the change is a **value**
shift and not a structural one (still a list of the right length, still finite,
still non-negative), and update the expected value with a comment naming this
task as the cause. If it does **not** fail, note that in the commit — it means
the assertion was loose enough not to see the change, which is worth knowing.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/vidstab.py scripts/intake.py tests/
git commit -F - <<'EOF'
fix: one detect recipe, so "shake" means one thing

intake detected at the binary's default shakiness=5 while the recorded
recipe asked for 8. Left alone that puts two different measurements
under one word: FOOTAGE.md shows the author a window's `shake`, and
process_episode's stabilize pre-stage would report a `before` for the
segment cut from that window. Nothing in either document says they are
incomparable, and a reader would compare them, because they are the same
word in the same units on the same footage.

Both now read vidstab.DETECT_ARGS. Intake's recorded values move as a
result; that is a number with a written cause, which is worth more than
two numbers sharing a name.

SHAKY_CLIP is deliberately not re-tuned to compensate — no real footage
has been through this pipeline, so a compensating value would be
invented.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Task 2: `detect()` + `mean_shake()`

**Files:**
- Modify: `scripts/lib/vidstab.py`
- Modify: `scripts/intake.py`
- Modify: `tests/lib/test_vidstab.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_vidstab.py`:

```python
def _stub_detect_run(seen: dict):
    """A proc.run stand-in that writes a minimal valid .trf wherever the real
    vidstabdetect command would have written one, and records the argv and kwargs."""
    def fake_run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        seen.update(kwargs)
        # the -vf value is `vidstabdetect=<args>:result=<path>:fileformat=ascii`,
        # so the path ends at the next option separator, not at end-of-string.
        trf_path = cmd[cmd.index("-vf") + 1].split("result=", 1)[1].split(":", 1)[0]
        with open(trf_path, "w") as f:
            f.write(_TRF)
        return types.SimpleNamespace(stdout=b"")
    return fake_run


def test_detect_emits_the_recipe_and_returns_parsed_magnitudes(monkeypatch, tmp_path):
    seen: dict = {}
    monkeypatch.setattr(vidstab.proc, "run", _stub_detect_run(seen))
    trf = str(tmp_path / "t.trf")
    assert vidstab.detect("in.mp4", trf, dur=2.0) == [0.0, 10.0, 0.0]
    vf = seen["cmd"][seen["cmd"].index("-vf") + 1]
    assert vf == f"vidstabdetect=shakiness=8:result={trf}:fileformat=ascii"
    assert "-f" in seen["cmd"] and seen["cmd"][seen["cmd"].index("-f") + 1] == "null"


def test_detect_scales_its_timeout_to_the_input_length(monkeypatch, tmp_path):
    seen: dict = {}
    monkeypatch.setattr(vidstab.proc, "run", _stub_detect_run(seen))
    vidstab.detect("in.mp4", str(tmp_path / "t.trf"), dur=500.0)
    assert seen["timeout"] == pytest.approx(500.0 * vidstab.SHAKE_TIMEOUT_REALTIME_MULTIPLE)


def test_detect_keeps_the_default_floor_for_a_short_input(monkeypatch, tmp_path):
    # A 2s segment must not get a 20s timeout — the floor keeps a short input at
    # proc's already-generous default rather than an unrealistically tight one.
    seen: dict = {}
    monkeypatch.setattr(vidstab.proc, "run", _stub_detect_run(seen))
    vidstab.detect("in.mp4", str(tmp_path / "t.trf"), dur=2.0)
    assert seen["timeout"] == vidstab.proc.DEFAULT_TIMEOUT_S


def test_mean_shake_normalises_by_frame_width():
    assert vidstab.mean_shake([0.0, 10.0, 0.0, 0.0], 1000) == pytest.approx(0.0025)


def test_mean_shake_of_nothing_is_zero_not_a_crash():
    # a .trf with a header and no Frame lines parses to []; dividing by len() there
    # would be a ZeroDivisionError inside an error path, hiding the real cause.
    assert vidstab.mean_shake([], 1000) == 0.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_vidstab.py -q; echo "EXIT: $?"`
Expected: 5 failures — `module 'scripts.lib.vidstab' has no attribute 'detect'` / `'mean_shake'`.

- [ ] **Step 3: Implement**

Append to `scripts/lib/vidstab.py`:

```python
def _timeout(dur: float) -> float:
    return max(proc.DEFAULT_TIMEOUT_S, dur * SHAKE_TIMEOUT_REALTIME_MULTIPLE)


def detect(src: str, trf: str, dur: float) -> list[float]:
    """One vidstabdetect pass over `src` writing `trf` → per-frame magnitudes.

    `fileformat=ascii` is REQUIRED, not a preference: libvidstab defaults to a
    BINARY .trf (magic "TRF1") while parse_trf reads the ASCII serializer's
    "VID.STAB" text. Omitting it does not degrade gracefully — the read dies on
    the first non-UTF-8 byte. That was invisible until 2026-07-20, because no
    machine in this project carried libvidstab and the one covering test was
    skipped everywhere it ever ran.

    Does NOT call require(): the gate belongs at the entry points, so one
    stabilize() does not pay three uncached `ffmpeg -filters` probes.
    """
    proc.run([ffbin.ffmpeg(), "-y", "-i", src, "-vf",
              f"vidstabdetect={DETECT_ARGS}:result={trf}:fileformat=ascii",
              "-f", "null", "-"], timeout=_timeout(dur))
    return parse_trf(read_trf(Path(trf)))


def mean_shake(mags: list[float], width: int) -> float:
    """Mean per-frame magnitude as a FRACTION OF FRAME WIDTH — the same unit
    FootageWindow.shake carries, so the two are directly comparable (design §5)."""
    if not mags:
        return 0.0
    return (sum(mags) / len(mags)) / (width or 1)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_vidstab.py -q; echo "EXIT: $?"`
Expected: `15 passed`.

- [ ] **Step 5: Collapse `intake.shake_by_window` onto `detect`**

In `scripts/intake.py`, replace the body of `shake_by_window` with the delegating
version, and update its docstring's final paragraph:

```python
def shake_by_window(clip: str, windows: list[tuple[float, float]], fps: float,
                    res: tuple[int, int], dur: float) -> list[float]:
    """vidstabdetect once per clip → per-frame magnitudes → averaged per window,
    normalized by frame width. No per-window cutting → no -ss seek landmine.

    `dur` (the clip's own length, already probed by the caller) scales the timeout
    vidstab.detect hands to proc.run: this pass runs over the WHOLE raw clip,
    unlike everything else in this repo, so proc's flat default is not generous
    enough for a long take. The detect recipe, the timeout derivation and the
    .trf parsing all live in scripts/lib/vidstab.py, shared with process_episode's
    stabilize pre-stage so both report the same measurement (design 2026-07-20 §5).
    """
    vidstab.require()
    with tempfile.TemporaryDirectory() as d:
        mags = vidstab.detect(clip, str(Path(d) / "t.trf"), dur)
    return _windowed_shake(mags, windows, fps, res[0])
```

Remove `ffbin` from `scripts/intake.py`'s lib import **only if** no other line in
the file still uses it (check with `grep -n 'ffbin' scripts/intake.py`).

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"`
Expected: all pass. The two `shake_by_window` timeout tests in
`tests/lib/test_intake.py` still pass — they assert on `proc.run`'s kwargs, and
`detect` is what calls `proc.run` now, through the same shared module object.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/vidstab.py scripts/intake.py tests/lib/test_vidstab.py
git commit -F - <<'EOF'
feat: vidstab.detect + mean_shake

detect() is the single detect pass — recipe, ascii fileformat, and the
length-scaled timeout in one place. shake_by_window collapses onto it and
keeps only its windowing, which is intake's own concern.

mean_shake normalises to a fraction of frame width, the unit
FootageWindow.shake already carries, so the pre-stage's before/after and
FOOTAGE.md's column are the same measurement.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Task 3: `stabilize()` — the two-pass pre-stage

**Files:**
- Modify: `scripts/lib/vidstab.py`
- Modify: `tests/lib/test_vidstab.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_vidstab.py` (add `from scripts.lib import assembly` to the
imports at the top of the file):

```python
def _stub_stabilize_run(cmds: list):
    """Records every argv and writes a valid .trf for each detect pass. The
    transform pass writes nothing — the geometry guard is stubbed separately."""
    def fake_run(cmd, **kwargs):
        cmds.append(list(cmd))
        vf = cmd[cmd.index("-vf") + 1] if "-vf" in cmd else ""
        if vf.startswith("vidstabdetect"):
            trf_path = vf.split("result=", 1)[1].split(":", 1)[0]
            with open(trf_path, "w") as f:
                f.write(_TRF)
        return types.SimpleNamespace(stdout=b"")
    return fake_run


def _stub_geometry(monkeypatch, w=1920, h=1080, fps=30.0, dur=2.0):
    """Patch `assembly` itself, not `vidstab.assembly` — Python caches modules, so
    `vidstab.assembly is assembly` is one object and setting an attribute on it is
    visible to every importer. Do not "fix" this into two patches."""
    monkeypatch.setattr(assembly, "probe_stream",
                        lambda p: assembly.StreamInfo(w, h, fps, "yuv420p", "h264"))
    monkeypatch.setattr(assembly, "probe_duration", lambda p: dur)


def test_stabilize_emits_detect_transform_detect(monkeypatch, tmp_path):
    monkeypatch.setattr(vidstab, "require", lambda: None)
    _stub_geometry(monkeypatch)
    cmds: list = []
    monkeypatch.setattr(vidstab.proc, "run", _stub_stabilize_run(cmds))

    out = str(tmp_path / "stabilized.mp4")
    before, after = vidstab.stabilize("seg.mp4", out, (1920, 1080), 30.0, 2.0)

    assert len(cmds) == 3
    # pass 1 reads the SOURCE, pass 3 reads the OUTPUT — measuring the output with
    # the source would report a residual that never fell, however broken the
    # transform was.
    assert cmds[0][cmds[0].index("-i") + 1] == "seg.mp4"
    assert cmds[2][cmds[2].index("-i") + 1] == out
    # both magnitudes come from the same stubbed .trf, so before == after here;
    # that they are equal is the stub's doing, that they are REPORTED is the point.
    assert before == pytest.approx(after)
    assert before == pytest.approx(vidstab.mean_shake([0.0, 10.0, 0.0], 1920))


def test_stabilize_transform_chain_is_the_recipe(monkeypatch, tmp_path):
    monkeypatch.setattr(vidstab, "require", lambda: None)
    _stub_geometry(monkeypatch)
    cmds: list = []
    monkeypatch.setattr(vidstab.proc, "run", _stub_stabilize_run(cmds))

    out = str(tmp_path / "stabilized.mp4")
    vidstab.stabilize("seg.mp4", out, (1920, 1080), 30.0, 2.0)

    vf = cmds[1][cmds[1].index("-vf") + 1]
    trf = cmds[0][cmds[0].index("-vf") + 1].split("result=", 1)[1].split(":", 1)[0]
    assert vf == (f"vidstabtransform=input={trf}:smoothing=40:zoom=2:crop=keep,"
                  "unsharp=5:5:0.4")
    assert cmds[1][cmds[1].index("-crf") + 1] == "12"    # intermediate, not a deliverable
    assert "-an" in cmds[1]


def test_stabilize_requires_the_filters_before_spending_two_passes(monkeypatch):
    def _no_filters():
        raise ValueError("/opt/slim/ffmpeg has no vidstabtransform filter — run `bash setup.sh`")

    def _must_not_run(*a, **k):
        pytest.fail("ffmpeg ran before the capability gate")

    monkeypatch.setattr(vidstab, "require", _no_filters)
    monkeypatch.setattr(vidstab.proc, "run", _must_not_run)
    with pytest.raises(ValueError, match="vidstabtransform"):
        vidstab.stabilize("seg.mp4", "out.mp4", (1920, 1080), 30.0, 2.0)


def test_stabilize_raises_when_the_transform_moved_the_geometry(monkeypatch, tmp_path):
    """The caller's layout resolution already computed with (dims, fps, dur). If
    vidstabtransform ever changed them, every number downstream would be stale
    while the pipeline carried on using it — silently. vidstab preserves
    dimensions today; this makes the day it does not a raise."""
    monkeypatch.setattr(vidstab, "require", lambda: None)
    _stub_geometry(monkeypatch, w=1918)          # two pixels narrower than promised
    monkeypatch.setattr(vidstab.proc, "run", _stub_stabilize_run([]))
    with pytest.raises(ValueError, match="geometry"):
        vidstab.stabilize("seg.mp4", str(tmp_path / "o.mp4"), (1920, 1080), 30.0, 2.0)


def test_stabilize_raises_when_the_transform_moved_the_duration(monkeypatch, tmp_path):
    monkeypatch.setattr(vidstab, "require", lambda: None)
    _stub_geometry(monkeypatch, dur=1.0)         # half a second short of 2.0
    monkeypatch.setattr(vidstab.proc, "run", _stub_stabilize_run([]))
    with pytest.raises(ValueError, match="duration"):
        vidstab.stabilize("seg.mp4", str(tmp_path / "o.mp4"), (1920, 1080), 30.0, 2.0)


def test_stabilize_tolerates_a_two_frame_duration_wobble(monkeypatch, tmp_path):
    # a re-encode can shift the container duration by a frame or two; that is not
    # the failure this guard exists for.
    monkeypatch.setattr(vidstab, "require", lambda: None)
    _stub_geometry(monkeypatch, dur=2.0 + 1.0 / 30.0)
    monkeypatch.setattr(vidstab.proc, "run", _stub_stabilize_run([]))
    vidstab.stabilize("seg.mp4", str(tmp_path / "o.mp4"), (1920, 1080), 30.0, 2.0)  # no raise
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_vidstab.py -q; echo "EXIT: $?"`
Expected: 6 failures — `module 'scripts.lib.vidstab' has no attribute 'stabilize'`.

- [ ] **Step 3: Implement**

In `scripts/lib/vidstab.py`, add `tempfile` to the imports and `assembly` to the
lib import:

```python
import re
import tempfile
from pathlib import Path

from scripts.lib import assembly, ffbin, proc
```

Add the recipe constants beside `DETECT_ARGS`:

```python
# The transform recipe (design 2026-07-20 §4). smoothing=40 and zoom=2 come from
# the session's proven recipe (design spec §10); crop=keep is stated explicitly
# even though it is the binary's default, because §10 says the opposite and a
# decision documented nowhere is a decision waiting to be reverted.
#
# crop=black is refused: it fills the uncovered border with black, and under a
# fill layout the crop takes the source's full height, so that band lands in the
# delivered frame whole. check_episode's black gate compares frame MEDIANS and a
# few percent of the frame does not move a median, so nothing would catch it.
# crop=keep fills from the previous frame instead — the failure class stops
# existing rather than being detected (§4.1).
TRANSFORM_ARGS = "smoothing=40:zoom=2:crop=keep"

# unsharp counters the softening from vidstabtransform's bilinear interpolation
# (design spec §10, proven on real footage). It is the one parameter whose
# POSITION changed relative to where it was proven — there it shared a chain with
# the crop at delivery scale, here it runs on an intermediate that a crop and a
# scale then consume (§4.3).
SHARPEN = "unsharp=5:5:0.4"

# The intermediate is consumed twice (YOLO, then reframe) and thrown away, and
# reframe re-encodes at 18 with deliver encoding again after that. At 18 this
# would spend a generation nothing can recover; 12 is visually lossless at a size
# that is irrelevant for a 1.2-4.0s window (§4.2).
INTERMEDIATE_CRF = "12"
```

Append the function:

```python
def stabilize(src: str, out: str, dims: tuple[int, int], fps: float,
              dur: float) -> tuple[float, float]:
    """Two-pass stabilization of `src` into `out`; returns (before, after) shake.

    A PRE-STAGE, not a filter in reframe's chain, and the distinction is the whole
    point (design 2026-07-20 §1): the route is measured on unstabilized pixels, so
    a crop placed from it against transformed pixels leaves the subject offset by
    exactly the shake vidstab removed — a steady background with a jittering
    subject. check_episode would not catch it either, because path and route are
    both in source coordinates and agree with each other; only the pixels disagree.
    Writing a file that BOTH track and reframe read makes route and pixels one
    coordinate system by construction.

    `dims`/`fps`/`dur` are the caller's already-probed numbers, not re-probed here.
    They are what the layout resolution computed with, so handing them in states
    the belief the geometry guard below then proves still holds. dims[0] is also
    the width the returned fractions are normalised by.

    The residual is a MEASUREMENT, not a gate. It proves stabilization ran and did
    something; it does not prove it should have. In particular it does NOT catch
    the §12 wade-in landmine — "rolling ground" is a warp, and a successfully
    flattened wade shot reports a LOW residual (§7).
    """
    require()
    with tempfile.TemporaryDirectory() as d:
        before = mean_shake(detect(src, str(Path(d) / "in.trf"), dur), dims[0])
        proc.run([ffbin.ffmpeg(), "-y", "-i", src, "-vf",
                  f"vidstabtransform=input={Path(d) / 'in.trf'}:{TRANSFORM_ARGS},{SHARPEN}",
                  "-c:v", "libx264", "-crf", INTERMEDIATE_CRF, "-preset", "medium",
                  "-an", out], timeout=_timeout(dur))
        _assert_geometry_held(out, dims, fps, dur)
        after = mean_shake(detect(out, str(Path(d) / "out.trf"), dur), dims[0])
    return before, after


def _assert_geometry_held(out: str, dims: tuple[int, int], fps: float, dur: float) -> None:
    """vidstabtransform preserves width/height/fps/duration — `zoom` is internal to
    the transform and the output frame is the input frame's size. But "preserves"
    is a promise from a library, and if it were ever false the caller's layout
    numbers would be stale while everything downstream kept computing with them.

    Uses assembly's probes rather than reframe._probe: scripts.reframe imports from
    scripts.lib, so reaching back for it would close an import cycle.
    """
    info = assembly.probe_stream(out)
    if (info.w, info.h) != tuple(dims) or abs(info.fps - fps) > 0.01:
        raise ValueError(
            f"vidstabtransform changed the geometry: asked to preserve {dims} @ {fps:.4g}fps, "
            f"{out} is {(info.w, info.h)} @ {info.fps:.4g}fps — the layout was already "
            "resolved against the original numbers, so every crop below this is stale. "
            "Re-check the vidstabtransform options (zoom must not resize the frame)")
    got = assembly.probe_duration(out)
    tol = 2.0 / fps          # two frames: a re-encode may shift the container slightly
    if abs(got - dur) > tol:
        raise ValueError(
            f"vidstabtransform changed the duration: expected {dur:.4f}s (±{tol:.4f}s, two "
            f"frames), {out} is {got:.4f}s — the episode's target_dur and the reel's length "
            "gate both key on the original")
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_vidstab.py -q; echo "EXIT: $?"`
Expected: `21 passed`.

- [ ] **Step 5: Mutation check — the recipe is actually asserted**

```bash
find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
sed -i '' 's/crop=keep/crop=black/' scripts/lib/vidstab.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/lib/test_vidstab.py -p no:cacheprovider -q; echo "EXIT: $?"
```
Expected: `test_stabilize_transform_chain_is_the_recipe` FAILS. Then revert:
```bash
sed -i '' 's/crop=black/crop=keep/' scripts/lib/vidstab.py
```
and re-run to confirm green. If the mutation did **not** fail a test, the
assertion is not covering the value — fix the test before continuing.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/vidstab.py tests/lib/test_vidstab.py
git commit -F - <<'EOF'
feat: vidstab.stabilize — detect, transform, measure the residual

The pre-stage itself. Three passes: detect the source, transform it into
a crf-12 intermediate, detect the output. Returns (before, after) as
fractions of frame width, the unit FootageWindow.shake already uses.

crop=keep, not the recorded recipe's crop=black. A black border band
lands whole in the delivered frame under a fill layout, and
check_episode's black gate compares frame medians, which a few percent of
the frame does not move — so nothing catches it. keep fills from the
previous frame and the failure class stops existing.

The geometry guard turns a library promise into a raise: vidstabtransform
preserves dimensions and duration, and if it ever stopped, the caller's
already-resolved layout numbers would go stale silently.

The residual is reported, not gated. It proves stabilization did
something; it does not prove it should have, and it specifically does not
catch the wade-in landmine.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Task 4: `PathMeta.stabilized` + `reframe(stabilized=)`

Design §6.2. `reframe` writes the sidecar but does not stabilize, so unlike `pan`
it cannot derive the bit from its own spec. It arrives as a parameter describing
`src`, on the same side of the line `reframe`'s docstring already draws.

**Files:**
- Modify: `scripts/lib/models.py` (`PathMeta`, around lines 125-190)
- Modify: `scripts/reframe.py` (`reframe`, around lines 312-395)
- Modify: `tests/lib/test_models.py`
- Modify: `tests/lib/test_reframe.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_models.py`:

```python
def test_path_meta_carries_the_stabilized_provenance_bit():
    m = models.PathMeta(mode="fill", crop_w=608, crop_h=1080, crop_y=0,
                        src_dims=(1920, 1080), canvas=(1080, 1920), out_dims=(1080, 1920),
                        rect_px=(0, 0, 1080, 1920), freedom=1312, stabilized=True)
    assert m.to_dict() == {
        "mode": "fill", "crop_w": 608, "crop_h": 1080, "crop_y": 0,
        "src_dims": [1920, 1080], "canvas": [1080, 1920], "out_dims": [1080, 1920],
        "rect_px": [0, 0, 1080, 1920], "freedom": 1312,
        "background": "blur", "pan": False, "stabilized": True}


def test_a_sidecar_written_before_this_slice_reads_as_not_stabilized():
    """Same one-key exemption background and pan already have: a sidecar with no
    `stabilized` key was written when stabilization could not happen at all, so
    False is provably the truth for those files rather than a guessed default."""
    d = {"mode": "fill", "crop_w": 608, "crop_h": 1080, "crop_y": 0,
         "src_dims": [1920, 1080], "canvas": [1080, 1920], "out_dims": [1080, 1920],
         "rect_px": [0, 0, 1080, 1920], "freedom": 1312}
    assert models.PathMeta.from_dict(d).stabilized is False
```

Append to `tests/lib/test_reframe.py` (match the file's existing style for stubbing
`_probe` and `proc.run`; if it already has a helper for that, reuse it):

```python
def test_reframe_records_that_its_source_was_stabilized(monkeypatch, tmp_path):
    """reframe does not stabilize — the flag is a FACT ABOUT ITS `src`, handed in
    by the caller that did. It flows to the sidecar and nowhere else; a
    ReframeSpec.stabilize would have been an instruction reframe cannot carry out
    (design 2026-07-20 §6.2)."""
    monkeypatch.setattr(reframe, "_probe", lambda src: (1920, 1080, 30.0, 2.0))
    monkeypatch.setattr(reframe.proc, "run", lambda *a, **k: None)
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(1080, 1920),
                       color_means=(105, 122, 137), delivery=Delivery())
    route = tmp_path / "route.json"
    route.write_text('[{"t": 0.0, "x": 960.0, "y": 540.0}, {"t": 1.0, "x": 960.0, "y": 540.0}]')
    path_out = str(tmp_path / "path.json")
    reframe.reframe(spec, "seg.mp4", str(route), str(tmp_path / "o.mp4"), path_out,
                    stabilized=True)
    meta = PathMeta.from_json(Path(path_out).with_suffix(".meta.json"))
    assert meta.stabilized is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py tests/lib/test_reframe.py -q; echo "EXIT: $?"`
Expected: FAIL — `PathMeta.__init__() got an unexpected keyword argument 'stabilized'` and
`reframe() got an unexpected keyword argument 'stabilized'`.

- [ ] **Step 3: Add the field**

In `scripts/lib/models.py`, in `PathMeta`, after the `pan` field:

```python
    pan: bool = False      # True ⇒ the path was GENERATED, not observed (design 2026-07-19 §5)
    stabilized: bool = False   # True ⇒ reframe's `src` was a vidstab pre-stage output, not the
                               # raw segment (design 2026-07-20 §6.2)
```

Extend the class docstring with a paragraph after the `pan` one:

```
    `stabilized` is the other provenance bit. It says the pixels reframe cut were
    already vidstab-corrected, which is what makes the route it cut them by
    trustworthy — that pairing is the load-bearing claim of design 2026-07-20 §1,
    and a reader of the sidecar has no other way to check it.
```

In `to_dict`, add `"stabilized": self.stabilized` after `"pan": self.pan`.

In `from_dict`, after the `pan=d.get("pan", False)` line:

```python
                       # Third and last key on the same exemption, same reasoning:
                       # a sidecar written before the stabilize slice has no
                       # `stabilized` key, and its absence honestly means the source
                       # was raw — stabilization was refused upstream until then.
                       stabilized=d.get("stabilized", False))
```

- [ ] **Step 4: Add the parameter**

In `scripts/reframe.py`, change the signature:

```python
def reframe(spec: ReframeSpec, src: str, route_path: str | None, out: str,
            path_out: str, stabilized: bool = False) -> str:
```

Add to the docstring, after the `route_path is OPTIONAL` paragraph:

```
    `stabilized` is a FACT ABOUT `src`, not an instruction: it says the caller
    already ran the vidstab pre-stage and handed us its output. reframe cannot
    stabilize — a ReframeSpec.stabilize would be a lie in the type — but it does
    write the sidecar, and whether the pixels were corrected is exactly the kind of
    thing PathMeta exists to record (design 2026-07-20 §6.2). It flows to PathMeta
    and nowhere else.
```

At the `PathMeta(...)` construction near the end:

```python
             pan=spec.pan is not None, stabilized=stabilized
             ).write(Path(path_out).with_suffix(".meta.json"))
```

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py tests/lib/test_reframe.py -q; echo "EXIT: $?"`
Expected: all pass.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"`
Expected: all pass. Any test doing a whole-object assert on a `PathMeta` dict now
needs the new key; add `"stabilized": False` to those expectations — they are
asserting the default, which is correct.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/models.py scripts/reframe.py tests/
git commit -F - <<'EOF'
feat: PathMeta.stabilized, fed by a reframe parameter

reframe writes the sidecar but does not stabilize, so unlike `pan` it
cannot derive the bit from its own spec. The distinction that resolves it
is tense: `stabilize` is imperative and reframe cannot carry it out, so
that field would be a lie in the type; `stabilized` is declarative, a
true fact about an argument, and recording facts about its input is what
PathMeta is for.

So it arrives as a parameter, beside src/route_path/out/path_out — the
line reframe's own docstring already draws between per-call I/O and
config. It flows to PathMeta and nowhere else. The alternative, having
process_episode rewrite the sidecar after reframe returns, gives one file
two writers for no gain.

from_dict defaults it to False for older sidecars on the same reasoning
background and pan already use: those files were written when
stabilization was refused upstream, so False is provably their truth
rather than a guess.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Task 5: delete `ReframeSpec.stabilize`

**Files:**
- Modify: `scripts/lib/models.py` (`ReframeSpec`, around lines 586-625)
- Modify: `tests/lib/test_models.py`
- Modify: `scripts/reframe.py` (the docstring line that mentions the refusal)

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_models.py`:

```python
def test_reframe_spec_has_no_stabilize_field_at_all():
    """Not "refuses True" — GONE. The field existed only to be refused, back when
    stabilization was unimplemented. Keeping a refused field once the feature
    exists invites someone to flip it to True and expect the pre-stage to run
    inside reframe, which is exactly the arrangement design 2026-07-20 §1 rules
    out. A TypeError says so at construction."""
    with pytest.raises(TypeError, match="stabilize"):
        models.ReframeSpec(composition="center", grid="thirds", canvas=(1080, 1920),
                           color_means=(105, 122, 137), delivery=models.Delivery(),
                           stabilize=True)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py::test_reframe_spec_has_no_stabilize_field_at_all -q; echo "EXIT: $?"`
Expected: FAIL — the constructor accepts the kwarg and raises `ValueError`, not `TypeError`.

- [ ] **Step 3: Delete the field and its refusal**

In `scripts/lib/models.py`, `ReframeSpec`: delete the line
`stabilize: bool = False` and the three-line `if self.stabilize:` block in
`__post_init__`.

- [ ] **Step 4: Fix the stale docstring in `reframe.py`**

In `scripts/reframe.py`'s `reframe` docstring, the sentence
"stabilize is refused upstream (manifest gate + ReframeSpec.__post_init__) — this
function never sees it." is now false in both halves. Replace it with:

```
    Stabilization is a PRE-STAGE, not part of this chain: process_episode runs
    vidstab.stabilize and hands the result in as `src` (design 2026-07-20 §1).
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -q; echo "EXIT: $?"`
Expected: pass. Delete any older test that asserted `ReframeSpec` **refuses**
`stabilize=True` — it is superseded by the new one, and would now fail for the
right reason with the wrong exception type.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/models.py scripts/reframe.py tests/lib/test_models.py
git commit -F - <<'EOF'
refactor: ReframeSpec.stabilize is deleted, not merely refused

The field existed to be refused, back when stabilization was
unimplemented. Now that it works, a refused field is worse than no field:
it invites flipping to True and expecting the pre-stage to run inside
reframe's chain, which is the one arrangement the design rules out — the
route is measured on unstabilized pixels, so a crop placed from it
against transformed pixels re-injects the shake it removed.

A TypeError at construction says that; a ValueError from __post_init__
said "not yet", which is no longer true.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Task 6: the manifest gate stops refusing and starts checking

**Files:**
- Modify: `scripts/lib/manifest.py` (`validate`, around lines 183-186)
- Modify: `tests/lib/test_manifest.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_manifest.py` (add `from scripts.lib import vidstab` to the
imports):

```python
def _m(**over) -> manifest.Manifest:
    d = {"segment": "s.mp4", "out_path": "o.mp4", "composition": "center",
         "grid": "thirds", "canvas": [1080, 1920], "target_dur": 2.0}
    d.update(over)
    return manifest.Manifest.from_dict(d)


def test_stabilize_true_is_no_longer_refused(monkeypatch):
    monkeypatch.setattr(vidstab, "require", lambda: None)
    assert manifest.validate(_m(stabilize=True)) == []


def test_stabilize_true_on_a_build_without_the_filter_is_a_problem(monkeypatch):
    """A missing filter is an environment fault, and every other manifest fault
    reaches the caller as a problem string → needs_input. Letting ffbin's
    ValueError escape validate() would make this the one that arrives as a
    traceback."""
    def _no(_=None):
        raise ValueError("/opt/slim/ffmpeg has no vidstabtransform filter — run `bash setup.sh`")
    monkeypatch.setattr(vidstab, "require", _no)
    problems = manifest.validate(_m(stabilize=True))
    assert len(problems) == 1
    assert "vidstabtransform" in problems[0] and "setup.sh" in problems[0]


def test_a_manifest_without_stabilize_never_probes_ffmpeg(monkeypatch):
    """validate() runs in a great many tests and the probe is a real subprocess
    (ffbin.has_filter is uncached by design). Gating on the flag keeps the cost
    on the manifests that asked for it."""
    monkeypatch.setattr(vidstab, "require",
                        lambda: pytest.fail("validate() probed ffmpeg for a manifest "
                                            "that never asked to stabilize"))
    assert manifest.validate(_m()) == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_manifest.py -q; echo "EXIT: $?"`
Expected: the first two fail — `validate` still returns the hardcoded
"not supported yet" string.

- [ ] **Step 3: Replace the refusal with the gate**

In `scripts/lib/manifest.py`, add `vidstab` to the lib import:

```python
from scripts.lib import hero as hero_lib   # aliased: ...
from scripts.lib import vidstab
```

Replace the `if m.stabilize:` block in `validate`:

```python
    # Stabilization is implemented (design 2026-07-20) — what is left to check is
    # whether THIS ffmpeg can do it. Same soft-manifest / hard-engine pairing the
    # layout uses: a problem string here so the shell returns needs_input with a
    # remedy, and vidstab.require() again in the engine as the hard backstop.
    #
    # Guarded on the flag because require() spawns a real `ffmpeg -filters`
    # (ffbin.has_filter is uncached on purpose), and validate() runs in a great
    # many tests that have nothing to do with vidstab.
    if m.stabilize:
        try:
            vidstab.require()
        except ValueError as e:
            problems.append(str(e))
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_manifest.py -q; echo "EXIT: $?"`
Expected: all pass. Delete any older test asserting the "not supported yet"
message — search with `grep -rn "not supported yet" tests/ scripts/`.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/manifest.py tests/lib/test_manifest.py
git commit -F - <<'EOF'
feat: the manifest gate checks vidstab instead of refusing it

stabilize=true has returned "not supported yet" since the manifest gate
was written. It is supported now, so what is left to check is whether
this ffmpeg can do it — the same soft-manifest / hard-engine pairing the
layout preflight uses: a problem string here so the shell answers
needs_input with a remedy, and vidstab.require() again in the engine.

Guarded on the flag: require() spawns a real `ffmpeg -filters`, since
ffbin.has_filter is deliberately uncached, and validate() runs in a great
many tests that have nothing to do with vidstab.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Task 7: `process_episode` runs the pre-stage

**Read design §1 and §2 before starting.** The two re-pointed call sites and the
one that stays are the substance of this task.

**Files:**
- Modify: `scripts/process_episode.py` (lines ~96-190)
- Modify: `tests/lib/test_process_episode.py`

- [ ] **Step 1: Write the harness**

Append to `tests/lib/test_process_episode.py`. Note the shape: every stub a test
wants to inspect is passed **into** the helper, never installed beside it. A test
that patched `process_episode.vidstab.stabilize` and then called a helper which
installs its own default would silently assert against the helper's stub —
`monkeypatch` applies in call order and the last one wins.

```python
import json
from pathlib import Path

from scripts.lib import vidstab
from scripts.lib.models import PathMeta


class _StubReport:
    def __init__(self, ok: bool) -> None:
        self.overall = ok
        self.fail_reasons = [] if ok else ["jitter"]

    def to_dict(self) -> dict:
        return {"overall": self.overall, "fail_reasons": self.fail_reasons}


def _run_episode(monkeypatch, tmp_path, *, stabilize: bool, fail_checks: bool = False,
                 stabilize_fn=None, track_fn=None, reframe_fn=None, probe_fn=None,
                 manifest_extra: dict | None = None):
    """Drive process_episode with every expensive stage stubbed, so these tests can
    assert on WIRING rather than pixels.

    The stubs write the files the shell reads back — route.json, path.json and its
    .meta.json sidecar — because process_episode loads all three before handing
    them to storyboard, so a stub that writes nothing fails on a missing file
    instead of on the thing under test.

    vidstab.require is stubbed too: the manifest gate calls it for any
    stabilize=true manifest, and it spawns a real `ffmpeg -filters` (has_filter is
    uncached by design). Without this a unit test would shell out.

    Every `*_fn` overrides that stage's default. Pass a spy there rather than
    patching around this helper.
    """
    proj = tmp_path / "proj"; proj.mkdir()
    seg = str(tmp_path / "seg.mp4")

    monkeypatch.setattr(vidstab, "require", lambda: None)
    monkeypatch.setattr(process_episode.reframe, "_probe",
                        probe_fn or (lambda src: (1920, 1080, 30.0, 2.0)))
    monkeypatch.setattr(process_episode.vidstab, "stabilize",
                        stabilize_fn or (lambda src, out, dims, fps, dur: (0.031, 0.004)))

    def _default_route(spec, rp):
        Path(rp).write_text(json.dumps([{"t": 0.0, "x": 960.0, "y": 540.0},
                                        {"t": 1.9, "x": 960.0, "y": 540.0}]))
    monkeypatch.setattr(process_episode.track, "build_route", track_fn or _default_route)

    def _default_reframe(spec, src, rp, out, path_out, stabilized=False):
        Path(path_out).write_text(json.dumps([656, 656]))
        PathMeta(mode="fill", crop_w=608, crop_h=1080, crop_y=0, src_dims=(1920, 1080),
                 canvas=(1080, 1920), out_dims=(1080, 1920), rect_px=(0, 0, 1080, 1920),
                 freedom=1312, stabilized=stabilized
                 ).write(Path(path_out).with_suffix(".meta.json"))
        return out
    monkeypatch.setattr(process_episode.reframe, "reframe", reframe_fn or _default_reframe)

    monkeypatch.setattr(process_episode.check_episode, "run",
                        lambda *a, **k: _StubReport(not fail_checks))
    monkeypatch.setattr(process_episode.storyboard, "build", lambda *a, **k: None)

    md = {"segment": seg, "out_path": str(tmp_path / "ep.mp4"), "composition": "center",
          "grid": "thirds", "canvas": [1080, 1920], "target_dur": 2.0,
          "stabilize": stabilize}
    md.update(manifest_extra or {})
    return process_episode.process_episode(md, str(proj))
```

- [ ] **Step 2: Write the failing tests**

Append to the same file:

```python
def test_stabilize_feeds_the_SAME_file_to_the_tracker_and_to_reframe(monkeypatch, tmp_path):
    """The load-bearing invariant (design 2026-07-20 §1). If the tracker reads the
    raw segment while reframe reads the stabilized one, the route is in the source
    coordinate system and the pixels are not, so the crop re-injects exactly the
    shake vidstab removed — and nothing catches it, because path and route agree
    with each other and only the pixels disagree."""
    seen: dict = {}

    def _track(spec, rp):
        seen["track_src"] = spec.src
        Path(rp).write_text(json.dumps([{"t": 0.0, "x": 960.0, "y": 540.0},
                                        {"t": 1.9, "x": 960.0, "y": 540.0}]))

    def _reframe(spec, src, rp, out, path_out, stabilized=False):
        seen.update(reframe_src=src, stabilized=stabilized)
        Path(path_out).write_text(json.dumps([656, 656]))
        PathMeta(mode="fill", crop_w=608, crop_h=1080, crop_y=0, src_dims=(1920, 1080),
                 canvas=(1080, 1920), out_dims=(1080, 1920), rect_px=(0, 0, 1080, 1920),
                 freedom=1312, stabilized=stabilized
                 ).write(Path(path_out).with_suffix(".meta.json"))
        return out

    _run_episode(monkeypatch, tmp_path, stabilize=True, track_fn=_track, reframe_fn=_reframe)
    assert seen["track_src"] == seen["reframe_src"]
    assert seen["track_src"].endswith("stabilized.mp4")
    assert seen["stabilized"] is True


def test_the_preflight_probe_stays_on_the_ORIGINAL_segment(monkeypatch, tmp_path):
    """The probe exists so a manifest the layout cannot satisfy fails in
    milliseconds. Moving it after stabilization would spend two 4K ffmpeg passes
    before the cheap refusal, defeating it."""
    probed: list = []
    _run_episode(monkeypatch, tmp_path, stabilize=True,
                 probe_fn=lambda src: (probed.append(src), (1920, 1080, 30.0, 2.0))[1])
    assert probed[0].endswith("seg.mp4")     # not stabilized.mp4


def test_the_before_and_after_reach_the_result(monkeypatch, tmp_path):
    result = _run_episode(monkeypatch, tmp_path, stabilize=True)
    assert result["stabilize"] == {"before": 0.031, "after": 0.004}


def test_an_unstabilized_episode_never_runs_the_pre_stage(monkeypatch, tmp_path):
    def _never(*a, **k):
        pytest.fail("stabilized an episode that did not ask for it")
    result = _run_episode(monkeypatch, tmp_path, stabilize=False, stabilize_fn=_never)
    assert "stabilize" not in result


def test_the_pre_stage_runs_once_not_once_per_retry(monkeypatch, tmp_path):
    """Stabilization is the loop's INPUT, not one of its parameters. Running it per
    attempt would spend two 4K passes to produce the same file three times, and the
    retry ladder tunes max_speed, which stabilization does not depend on."""
    calls: list = []

    def _spy(src, out, dims, fps, dur):
        calls.append(src)
        return 0.03, 0.03
    _run_episode(monkeypatch, tmp_path, stabilize=True, fail_checks=True, stabilize_fn=_spy)
    assert len(calls) == 1


def test_a_pan_episode_can_also_be_stabilized(monkeypatch, tmp_path):
    """Design §2.1. A pan tracks nobody, so §1's coordinate argument does not apply
    to it — but a pan over shaky footage is still shaky footage, and the two flags
    are independent. The pre-stage must run, its output must reach reframe, and the
    tracker must still be skipped."""
    seen: dict = {}

    def _reframe(spec, src, rp, out, path_out, stabilized=False):
        seen.update(reframe_src=src, route_path=rp)
        Path(path_out).write_text(json.dumps([656, 656]))
        PathMeta(mode="fill", crop_w=608, crop_h=1080, crop_y=0, src_dims=(1920, 1080),
                 canvas=(1080, 1920), out_dims=(1080, 1920), rect_px=(0, 0, 1080, 1920),
                 freedom=1312, pan=True, stabilized=stabilized
                 ).write(Path(path_out).with_suffix(".meta.json"))
        return out

    def _never_track(spec, rp):
        pytest.fail("tracked an episode whose path is generated")

    result = _run_episode(monkeypatch, tmp_path, stabilize=True,
                          track_fn=_never_track, reframe_fn=_reframe,
                          manifest_extra={"pan": {"from": 0.0, "to": 1.0}})
    assert result["status"] == "mechanical_pass", result
    assert seen["reframe_src"].endswith("stabilized.mp4")
    assert seen["route_path"] is None       # a pan reads no route and writes none
    assert result["stabilize"] == {"before": 0.031, "after": 0.004}
```

- [ ] **Step 3: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_process_episode.py -q; echo "EXIT: $?"`
Expected: FAIL — `module 'scripts.process_episode' has no attribute 'vidstab'`.

- [ ] **Step 4: Implement**

In `scripts/process_episode.py`, add `vidstab` to the lib import.

After the pan preflight block (the `if pan is not None: try: reframe.generate_pan_path(...)`)
and **before** the tracking step, insert:

```python
    # 0c. the stabilization pre-stage (design 2026-07-20 §1). NOT a filter in
    # reframe's chain: the route is measured on unstabilized pixels, so a crop
    # placed from it against transformed pixels leaves the subject offset by
    # exactly the shake vidstab removed — a steady background with a jittering
    # subject — and check_episode confirms the framing anyway, because path and
    # route are both in source coordinates and agree with each other. Only the
    # pixels disagree. Writing a file that BOTH the tracker and reframe read makes
    # route and pixels one coordinate system by construction.
    #
    # Runs AFTER the preflights so a manifest the layout cannot satisfy still fails
    # in milliseconds rather than after two 4K ffmpeg passes, and OUTSIDE the retry
    # loop because it is the loop's input, not one of its parameters.
    src = m.segment
    stabilize_report = None
    if m.stabilize:
        src = str(Path(project_dir) / "stabilized.mp4")
        before, after = _timed("stabilize", lambda: vidstab.stabilize(
            m.segment, src, (src_w, src_h), _fps, _dur))
        stabilize_report = {"before": before, "after": after}
```

Change the two call sites:

```python
        tspec = TrackSpec(src=src, model=m.model,
                          pin=hero_lib.resolve(m.hero, cast), intent=intent)
```

```python
        _timed("reframe", lambda: reframe.reframe(rspec, src, rp, m.out_path, path_out,
                                                  stabilized=m.stabilize))
```

Leave `reframe._probe(m.segment)` at line 100 **unchanged**.

Add the report key to the `mechanical_pass` return:

```python
            result = {"status": "mechanical_pass", "clip": m.out_path,
                      "report": report.to_dict(), "storyboard": sheet,
                      "attempt": attempt, "timings": timings, "degraded": None}
            if stabilize_report is not None:
                result["stabilize"] = stabilize_report
            return result
```

Do the same for the `escalate` return inside the loop, so a failing stabilized
episode still reports what stabilization measured:

```python
        if esc:
            result = {"status": "escalate", **esc, "report": report.to_dict(),
                      "attempt": attempt, "timings": timings}
            if stabilize_report is not None:
                result["stabilize"] = stabilize_report
            return result
```

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_process_episode.py -q; echo "EXIT: $?"`
Expected: all pass.

- [ ] **Step 6: Mutation check — the coordinate-frame invariant is guarded**

This is §1's whole argument; if the suite tolerates the broken pairing, the
argument is unguarded.

```bash
find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
```
Edit `scripts/process_episode.py` so the `TrackSpec` line reads `src=m.segment`
while `reframe` keeps `src`. Then:
```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/lib/test_process_episode.py -p no:cacheprovider -q; echo "EXIT: $?"
```
Expected: `test_stabilize_feeds_the_SAME_file_to_the_tracker_and_to_reframe` FAILS.
Revert the edit and re-run to confirm green.

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add scripts/process_episode.py tests/lib/test_process_episode.py
git commit -F - <<'EOF'
feat: process_episode runs the stabilization pre-stage

Between the preflights and tracking, a stabilize=true episode gets a
vidstab pass into <project_dir>/stabilized.mp4, and BOTH the tracker and
reframe read that file. Feeding the tracker the raw segment while reframe
reads the stabilized one is the failure this ordering exists to prevent:
the route would be in the source coordinate system and the pixels would
not, so the crop would re-inject exactly the shake vidstab removed, and
check_episode would confirm the framing regardless because path and route
agree with each other.

After the preflights, so a manifest the layout cannot satisfy still fails
in milliseconds rather than after two 4K passes. Outside the retry loop,
because stabilization is the loop's input and not one of its parameters —
retries re-render reframe against the same file.

before/after ride out on both the pass and the escalate results, beside
timings, where stage-level facts already live.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Task 8: the EDL authoring path

**Files:**
- Modify: `scripts/lib/edl.py` (`EDLEpisode`, `to_dict`, `to_manifest_dict`)
- Modify: `tests/lib/test_edl.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_edl.py`:

```python
def _ep(**over) -> edl.EDLEpisode:
    d = {"source": "c.mp4", "start": 0.0, "dur": 2.5, "shot_type": "wide",
         "composition": "center", "grid": "thirds"}
    d.update(over)
    return edl.EDLEpisode(**d)


def test_stabilize_defaults_to_false_and_rides_in_to_dict():
    assert _ep().to_dict()["stabilize"] is False
    assert _ep(stabilize=True).to_dict()["stabilize"] is True


def test_the_bridge_omits_stabilize_when_it_is_false():
    """Same shape pan/motion/hero use: an absent flag leaves the key out rather
    than carrying an explicit false, so Manifest.from_dict falls to its own
    default and the two never disagree about what "unset" means."""
    assert "stabilize" not in edl.to_manifest_dict(_ep(), "s.mp4", "o.mp4")


def test_the_bridge_carries_stabilize_when_it_is_true():
    assert edl.to_manifest_dict(_ep(stabilize=True), "s.mp4", "o.mp4")["stabilize"] is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -q; echo "EXIT: $?"`
Expected: FAIL — `EDLEpisode.__init__() got an unexpected keyword argument 'stabilize'`.

- [ ] **Step 3: Implement**

In `scripts/lib/edl.py`, add the field to `EDLEpisode` after `pan`:

```python
    stabilize: bool = False   # run the vidstab pre-stage before tracking (design
                              # 2026-07-20). EXPLICIT by design and never inferred:
                              # a wade-in shot is handheld in moving water and so is
                              # noisy BY CONSTRUCTION, which means any auto-enable
                              # keyed on measured shake fires most confidently on
                              # exactly the shot §12 forbids stabilizing. The signal
                              # is already in front of whoever authors this row —
                              # FOOTAGE.md prints the window's shake.
```

In `to_dict`, add `"stabilize": self.stabilize` after `"pan": self.pan`.

In `to_manifest_dict`, beside the other conditional copies:

```python
    if ep.stabilize:
        md["stabilize"] = True
```

Update `to_manifest_dict`'s docstring: it currently says the bridge "Omits
canvas/delivery (the driver fills them from the project via resolve_manifest) and
model/stabilize (manifest defaults)". Change `model/stabilize` to `model`, and add
`stabilize` to the sentence listing the conditionally-copied fields.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py -q; echo "EXIT: $?"`
Expected: all pass. Any existing whole-object assert on `EDLEpisode.to_dict()`
needs `"stabilize": False` added.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q; echo "EXIT: $?"`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/edl.py tests/lib/test_edl.py
git commit -F - <<'EOF'
feat: EDLEpisode.stabilize + the manifest bridge

The authoring surface. Explicit and never inferred: a wade-in shot is
handheld in moving water and therefore noisy by construction, so an
auto-enable keyed on measured shake would fire most confidently on
exactly the shot the landmine registry forbids stabilizing. The signal is
already in front of whoever writes this row — FOOTAGE.md prints the
window's shake — so the decision stays with the author.

The bridge omits the key when false, the shape pan/motion/hero already
use, so Manifest.from_dict falls to its own default rather than the two
sides disagreeing about what unset means.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Task 9: the real-ffmpeg proofs

Everything above runs against stubs. These are the assertions a stub cannot fake.

**Files:**
- Create: `tests/integration/test_stabilize.py`

- [ ] **Step 1: Write the tests**

```python
"""Stabilization apply (design 2026-07-20) — the proofs that need real pixels.

Everything in tests/lib/test_vidstab.py runs against a stubbed proc.run, so it
pins the ARGV. Whether that argv actually reduces shake, and whether crop=keep
actually leaves no black edge, only real libvidstab can say.
"""
import numpy as np
import pytest

from scripts.lib import ffbin, proc, vidstab

pytestmark = pytest.mark.integration


@pytest.fixture
def shaky_clip(tmp_path, need_filter):
    """A synthetic clip that genuinely shakes: a static test pattern pushed around
    by a per-frame crop offset. `sample_clip` is too still to measure against."""
    need_filter("vidstabdetect")
    need_filter("vidstabtransform")
    out = str(tmp_path / "shaky.mp4")
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi",
              "-i", "testsrc2=size=640x480:rate=30:duration=2",
              "-vf", ("crop=560:400:20+18*sin(n*1.7):20+18*cos(n*2.3),"
                      "scale=560:400,format=yuv420p"),
              "-c:v", "libx264", "-crf", "12", "-preset", "veryfast", "-an", out])
    return out


def test_stabilization_actually_reduces_the_shake(shaky_clip, tmp_path):
    """The slice's charter, and the one assertion no stub can fake."""
    out = str(tmp_path / "stabilized.mp4")
    before, after = vidstab.stabilize(shaky_clip, out, (560, 400), 30.0, 2.0)
    assert before > 0, "the fixture is not shaky — the comparison below is vacuous"
    assert after < before


def test_crop_keep_leaves_no_black_edge(shaky_clip, tmp_path):
    """The positive control for design §4.1. crop=black would put a band at the
    frame edge that check_episode's median-based black gate cannot see, so this
    decision is otherwise pinned by prose alone.

    Reads the outermost rows/columns of every frame as raw gray and asserts none
    of them is a black band. Rows, not the whole frame: a frame median would miss
    exactly the defect this is looking for — which is the reason crop=black was
    rejected in the first place.
    """
    out = str(tmp_path / "stabilized.mp4")
    vidstab.stabilize(shaky_clip, out, (560, 400), 30.0, 2.0)
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", out,
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 400, 560)
    assert len(frames) > 30, "too few frames decoded to be a real check"
    for i, f in enumerate(frames):
        for name, band in (("top", f[0]), ("bottom", f[-1]),
                           ("left", f[:, 0]), ("right", f[:, -1])):
            assert band.max() > 16, f"frame {i} has a black {name} edge — crop=keep regressed"


def test_a_stabilized_episode_reaches_mechanical_pass(shaky_clip, tmp_path, monkeypatch):
    """End to end through process_episode with a real vidstab pass, proving the
    wiring: the pre-stage runs, the tracker and reframe both read its output, and
    the sidecar records it. YOLO is faked — a test pattern is not a person, the
    same reason tests/integration/test_intake.py fakes it."""
    from scripts import process_episode, track
    from scripts.lib.models import PathMeta

    monkeypatch.setattr(track, "build_route", lambda spec, rp: __import__("pathlib").Path(rp)
                        .write_text('[{"t":0.0,"x":280.0,"y":200.0},'
                                    '{"t":1.9,"x":280.0,"y":200.0}]'))
    proj = tmp_path / "proj"; proj.mkdir()
    md = {"segment": shaky_clip, "out_path": str(tmp_path / "ep.mp4"),
          "composition": "center", "grid": "thirds", "canvas": [1080, 1920],
          "target_dur": 2.0, "stabilize": True}
    result = process_episode.process_episode(md, str(proj))

    assert result["status"] == "mechanical_pass", result
    assert result["stabilize"]["after"] < result["stabilize"]["before"]
    meta = PathMeta.from_json(proj / "path.meta.json")
    assert meta.stabilized is True
```

- [ ] **Step 2: Run them**

Run: `.venv/bin/python -m pytest tests/integration/test_stabilize.py -q; echo "EXIT: $?"`
Expected: `4 passed` (the fixture counts as none).

If `test_stabilization_actually_reduces_the_shake` fails with `after >= before`,
do **not** loosen the assertion. Either the fixture is not shaky in a way vidstab
recognizes (check `before` is well above zero) or `smoothing`/`zoom` are wrong.
Report it — a stabilizer that does not stabilize is the finding, not the test.

If `test_a_stabilized_episode_reaches_mechanical_pass` escalates instead of
passing, print `result` and read `report.fail_reasons`. A `black` fail there would
be real news and belongs in the design's §12 notes.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_stabilize.py
git commit -F - <<'EOF'
test: the real-ffmpeg proofs for the stabilize pre-stage

Three things stubs cannot say: that the argv actually reduces measured
shake, that crop=keep actually leaves no black edge, and that a
stabilize=true episode reaches mechanical_pass end to end with the
sidecar recording it.

The edge test reads the outermost rows and columns rather than a frame
median, deliberately — a median is exactly what cannot see a border band,
which is why crop=black was rejected.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Task 10: docs sync + the whole-suite proof

**Files:**
- Modify: `docs/specs/2026-07-05-montage-skillset-design.md` (§10, §12, the §5.2 status line)
- Modify: `docs/pipeline-map.md`
- Modify: `docs/build-status.md`
- Modify: `CLAUDE.md`
- Modify: `docs/plans/2026-07-20-stabilize-apply.md` (tick the boxes)
- Modify: `SKILLS/process-episode/SKILL.md` (the editorial wade rule)

- [ ] **Step 1: Correct design spec §10**

Replace the stabilization bullet in §10 with:

```markdown
- **Stabilization:** vidstab two-pass on the **source before crop** — and "before
  crop" means a **separate file**, not a place in the filter chain (see
  `docs/specs/2026-07-20-stabilize-apply-design.md` §1: the route is measured on
  unstabilized pixels, so stabilizing inside reframe's chain re-injects exactly
  the shake it removed, and no gate catches it).
  `vidstabdetect=shakiness=8:result=FILE.trf:fileformat=ascii` →
  `vidstabtransform=input=FILE.trf:smoothing=40:zoom=2:crop=keep,unsharp=5:5:0.4`.
  **Corrected 2026-07-20:** this bullet used to say `crop=black` and `optzoom=1`.
  `optzoom=1` is the binary's own default. `crop=black` is actively wrong here —
  it puts a border band in the delivered frame that check_episode's median-based
  black gate cannot see; `crop=keep` removes the failure class instead of
  detecting it. **Do not stabilize the wade in/out shots** — it produces "rolling
  ground", and no code can detect that shot, so the flag is explicit and the rule
  is editorial. `stabilize?` flag per episode; built 2026-07-20.
```

- [ ] **Step 2: Add the three §12 entries**

Append to the design spec's §12 registry:

```markdown
- Stabilizing **after** tracking, in reframe's own filter chain, silently
  re-injects the shake. The route is in source coordinates and the transformed
  pixels are not, so the subject sits at the correction offset inside every crop —
  a steady background with a jittering subject. `check_episode` confirms the
  framing regardless, because path and route are both in source coordinates and
  agree with each other; only the pixels disagree. Stabilization must be a
  pre-stage whose output BOTH the tracker and reframe read (2026-07-20 §1).
- `vidstabtransform`'s `crop=black` puts a border band in the frame that
  `check_episode`'s black gate **cannot see** — that gate compares frame MEDIANS
  against a floor, and a few percent of the frame does not move a median. Under a
  `fill` layout the crop takes the source's full height, so the band is delivered
  whole. Use `crop=keep` (which is also libvidstab's default).
- Two `vidstabdetect` calls with different `shakiness` produce two different
  numbers under one word. `intake` detected at the default 5 while the recipe used
  8, so `FOOTAGE.md`'s `shake` column and the stabilize pre-stage's `before` would
  have been silently incomparable on the same footage. One shared
  `vidstab.DETECT_ARGS` (2026-07-20 §5).
```

- [ ] **Step 3: Flip the status lines**

In the design spec, §5.2's status note and any "stabilization arrives with
process-episode" phrasing: mark the apply half **built 2026-07-20**. Search first:

```bash
grep -rn 'stabiliz' docs/specs/2026-07-05-montage-skillset-design.md docs/pipeline-map.md docs/build-status.md
```

Fix every hit that claims stabilization is unimplemented, unavailable, or
flag-gated behind a `setup.sh` option — `--with-vidstab` was folded into the
baseline on 2026-07-20 and no longer exists.

- [ ] **Step 4: Add the registry row**

In `CLAUDE.md`'s Quick Reference table, after the ffmpeg-baseline rows:

```markdown
| Stabilize-apply design | [2026-07-20-stabilize-apply-design.md](docs/specs/2026-07-20-stabilize-apply-design.md) | §5.2/§10 apply half: `vidstabtransform` as a **pre-stage writing a file**, never a filter in `reframe`'s chain — §1 is load-bearing (a route measured on unstabilized pixels re-injects the shake, and `check_episode` confirms the framing because path and route agree with each other while only the pixels disagree). `crop=black` → `crop=keep`, because a border band is invisible to a median-based black gate. §5 unifies the detect recipe with intake's, moving its golden. §7 is the honest half: the wade-in landmine keeps **no** machine predicate, auto-enable on measured shake is rejected (a wade shot is noisy by construction), and the before/after residual does not catch it either. |
| Stabilize-apply plan | [2026-07-20-stabilize-apply.md](docs/plans/2026-07-20-stabilize-apply.md) | Tasks 0–10: `lib/vidstab.py` extraction, the shared detect recipe, `detect`/`mean_shake`, `stabilize` + the geometry guard, `PathMeta.stabilized` + the `reframe` parameter, deleting `ReframeSpec.stabilize`, the manifest capability gate, the `process_episode` pre-stage, EDL authoring, the real-ffmpeg proofs, docs. Two mutation checks are steps, not suggestions. |
```

Also update the existing §12 "Known troubles" block in `CLAUDE.md`: the line
"Never stabilize wade-in/out shots" now has a home that can be pointed at. Extend
it to:

```markdown
- Never stabilize wade-in/out shots ("rolling ground"). **No machine predicate
  exists** — the flag is explicit by design, and auto-enabling on measured shake
  would fire hardest on exactly this shot (2026-07-20 §7).
```

- [ ] **Step 5: State the rule where the judgment lives**

In `SKILLS/process-episode/SKILL.md`, add to the editorial-gate section:

```markdown
- **`stabilize` is yours to set, and the pipeline will never set it for you.**
  A wade in/out-of-water shot must NOT be stabilized — it produces "rolling
  ground" (design §12). Nothing in the code can recognize such a shot: shot_type
  classifies by subject size, not content. The measured shake in `FOOTAGE.md` is
  a signal about the camera, not permission — a wade shot is handheld in moving
  water and reads as very shaky, which is exactly why the threshold is not wired
  to the flag. If the window is someone walking into or out of water, leave
  `stabilize` false however shaky the number looks.
```

- [ ] **Step 6: Tick this plan's boxes**

Mark every `- [ ]` in `docs/plans/2026-07-20-stabilize-apply.md` as `- [x]`, and
append an "As built" note under any task whose implementation diverged from what
is written here — divergences are findings, not embarrassments.

- [ ] **Step 7: Update build-status**

In `docs/build-status.md`, move the stabilization apply half to built, dated
2026-07-20, with the commit range. Record what the proof found, including
whether the intake shake golden moved in Task 1 and by how much.

- [ ] **Step 8: The whole-suite proof**

```bash
.venv/bin/python -m pytest -q; echo "EXIT: $?"
```

Expected: EXIT 0. The pass count is the Baseline plus the tests this plan added
(roughly 21 in `test_vidstab.py` net of the 8 that migrated, plus 4 integration,
plus the contract tests in Tasks 4–8), and **2 skipped** — the same two survivors
as the Baseline. If a new skip appears, find out which guard fired and why: a test
that skips is a test that proves nothing, and this slice exists partly because six
of them were doing that.

State the number rather than an identity like "same as before" — the pass count
is not stable across a slice that adds tests.

- [ ] **Step 9: Commit**

```bash
git add docs/ CLAUDE.md SKILLS/
git commit -F - <<'EOF'
docs: sync the stabilize-apply slice, and §10's recipe was wrong

§10 said crop=black and optzoom=1. optzoom=1 is the binary's own
default, so writing it performed a choice nobody made. crop=black is
actively wrong for this pipeline: it puts a border band in the frame that
check_episode's black gate compares medians against and therefore cannot
see, and under a fill layout the crop takes the full source height so the
band is delivered whole.

§12 gains three entries: the coordinate-frame trap that makes
stabilization a pre-stage rather than a filter, crop=black's invisibility
to the median gate, and two detect recipes producing two numbers under
one word.

The wade-in line in CLAUDE.md now says the part that was implicit — there
is no machine predicate, and that is why the flag is explicit. The
process-episode SKILL says the same where the judgment actually happens,
including that FOOTAGE.md's shake number is a signal about the camera and
not permission.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Final review

After Task 10, dispatch a whole-slice review (superpowers:requesting-code-review)
covering `f0350a6..HEAD`. Give the reviewer the design spec and this plan, and ask
specifically about:

1. **§1's invariant.** Is there any path — a retry, a pan, a supplied frozen
   route via `--route` — where the tracker's coordinate system and reframe's
   pixels can still diverge? The frozen-route case is worth real attention: a
   route supplied on the command line was measured against *something*, and
   nothing checks it was this segment, stabilized or not.
2. **The geometry guard's tolerance.** Two frames on duration, 0.01 on fps. Is
   either loose enough to pass a real regression?
3. **Whether `stabilize` should have reached `check_reel`.** This slice says no —
   stabilization does not change layout, and `PathMeta.stabilized` is provenance
   nothing gates on. Is that still true given `transitions` keys on
   `(mode, background)`?
