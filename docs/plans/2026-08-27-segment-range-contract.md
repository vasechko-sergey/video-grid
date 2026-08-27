# The segment format contract — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the extracted segment obey the colour range the whole pipeline
already declares, stop the tone map flattening the superwhite band, and refuse
pixels whose depth or range the colour maths cannot read.

**Architecture:** One filter pair in `extract` (`scale=in_range=auto:out_range=tv`
+ `-color_range tv`) turns "the footage is heterogeneous" into a property of the
original files rather than of everything downstream. `color.tone_arg`'s final
fall-through becomes the shoulder's own extrapolation instead of a constant, and
`color._lerp` — its independent reference implementation — gets the same rule
written out separately. A pure predicate in `color.py`, reading depth and range
and nothing else, is called by `reframe.plan_render` right after the ffprobe it
already makes.

**Tech Stack:** Python 3, pytest, ffmpeg/ffprobe via `scripts.lib.ffbin`.

**Design:** [docs/specs/2026-08-27-segment-range-contract-design.md](../specs/2026-08-27-segment-range-contract-design.md)

## Global Constraints

- **Scripts run as modules.** `pythonpath = .` in pytest config; run tests with
  `.venv/bin/python -m pytest`, never by invoking a script file directly.
- **Fail loud.** No silent fallback, no defensive `try/except` that swallows a
  contract violation. A refusal names what is wrong AND the remedy.
- **Imports at top of file.** No function-local imports.
- **ffmpeg binaries come from `scripts.lib.ffbin`** (`ffbin.ffmpeg()` /
  `ffbin.ffprobe()`) — never the bare string `"ffmpeg"`. The landmine lint's AST
  scan enforces this.
- **`-ss` goes AFTER `-i`** in every ffmpeg command (design spec §12). Adding
  `-vf` must not move it.
- **Every new real-ffmpeg proof carries a control that must not move.** A test
  that only shows the new behaviour cannot tell a fix from a no-op.
- **A mutation battery runs under `PYTHONDONTWRITEBYTECODE=1`.** A one-byte edit
  can match the previous file's size and mtime-second, and CPython will then
  serve a stale `.pyc`.
- **A surviving mutation row is a coverage hole**, never a row to soften.
- **Do not run installers** (`brew`, `pip install`, `setup.sh`, `npm`). The
  runtime is already installed; verification is read-only plus pytest.
- **Do not run `git checkout --`, `git restore`, `git reset --hard`, or
  `git stash`.** They destroy uncommitted work. Restore a mutated line by
  re-typing it.
- **Never touch `/Users/serg/Downloads/untitled folder/`.** It is a preserved
  real run kept for open calibration rows. This plan needs nothing from it.
- **Post-review fixes are separate follow-up commits, never `git commit --amend`.**

## File Structure

| File | Responsibility | Task |
|------|----------------|------|
| `scripts/lib/color.py` | gains `plane_depth` + `refuse_ungradeable_plane`; `tone_arg` and `_lerp` continue the shoulder past the top knot | 0, 2 |
| `scripts/extract.py` | `extract()` normalizes the range — the one chokepoint where footage becomes segment | 1 |
| `scripts/reframe.py` | `_probe` returns two more fields from the call it already makes; `plan_render` calls the predicate | 3 |
| `tests/conftest.py` | two session fixtures (`pc_ramp_clip`, `tenbit_clip`) and one control helper (`extract_unnormalized`) | 1 |
| `tests/lib/test_color.py` | unit tests for the predicate and the extrapolation | 0, 2 |
| `tests/lib/test_extract.py` | argv-level test that the filter and tag are emitted and `-ss` stays after `-i` | 1 |
| `tests/integration/test_extract.py` | the three real-ffmpeg byte-identity controls + the pc→tv conversion + resolution | 1 |
| `tests/integration/test_matchgrade.py` | the superwhite proof, through the `_ramp_y` harness already in the file | 2 |
| `tests/lib/test_reframe.py`, `tests/integration/test_reframe.py`, `tests/integration/test_process_episode.py` | 15 `_probe` stubs widened; four new guard tests | 3 |
| `tests/integration/test_segment_range.py` (new) | the slice's four end-to-end proofs | 4 |
| `docs/backlog.md`, `docs/build-status.md`, `CLAUDE.md` | R2.0/R2.3 closed, three deferrals filed, two registry rows, one landmine | 5 |

---

### Task 0: the pure predicate — `plane_depth` and `refuse_ungradeable_plane`

**Files:**
- Modify: `scripts/lib/color.py` (beside `TV_LO`/`TV_SPAN`, currently line 225)
- Test: `tests/lib/test_color.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `color.plane_depth(pix_fmt: str) -> int`
  - `color.refuse_ungradeable_plane(pix_fmt: str, color_range: str, src: str) -> None`
    — raises `ValueError`, returns `None` on success. Task 3 calls it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/lib/test_color.py`:

```python
@pytest.mark.parametrize("pix_fmt, depth", [
    ("yuv420p", 8), ("yuvj420p", 8), ("yuv422p", 8), ("yuv444p", 8), ("nv12", 8),
    ("gray", 8),
    ("yuv420p10le", 10), ("yuv420p10be", 10), ("p010le", 10),
    ("yuv444p12le", 12), ("yuv420p16le", 16),
])
def test_plane_depth_reads_the_pixel_format_name(pix_fmt, depth):
    assert color.plane_depth(pix_fmt) == depth


def test_an_eight_bit_limited_plane_is_gradeable():
    assert color.refuse_ungradeable_plane("yuv420p", "tv", "seg.mp4") is None


def test_an_untagged_eight_bit_plane_is_gradeable():
    # "unknown" is the mp4/h264 convention for limited and assembly.matches
    # already reads it that way. A full-range file that lost its tag is
    # therefore still misread — a KNOWN gap (design §7), pinned here so nobody
    # later "fixes" it into a refusal that would reject every fixture in this
    # repo and every episode reframe writes.
    assert color.refuse_ungradeable_plane("yuv420p", "unknown", "seg.mp4") is None


def test_a_full_range_plane_is_refused_and_names_extract():
    with pytest.raises(ValueError) as e:
        color.refuse_ungradeable_plane("yuvj420p", "pc", "/f/MVI_3678.MP4")
    msg = str(e.value)
    assert "pc" in msg and "/f/MVI_3678.MP4" in msg
    assert "extract" in msg          # the remedy, not just the complaint


def test_a_ten_bit_plane_is_refused_and_names_the_depth():
    with pytest.raises(ValueError) as e:
        color.refuse_ungradeable_plane("yuv420p10le", "tv", "/f/DJI_0548.MP4")
    msg = str(e.value)
    assert "10 bits" in msg and "yuv420p10le" in msg
    assert "extract" in msg


def test_depth_is_reported_before_range_when_both_are_wrong():
    # A 10-bit full-range source is broken twice over, and the depth is the worse
    # of the two — measured, 99.26% of pixels come back on one code — so it is
    # the half the message must lead with.
    with pytest.raises(ValueError, match="10 bits"):
        color.refuse_ungradeable_plane("yuv420p10le", "pc", "x.mp4")
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py -k "plane_depth or gradeable or refused or reported_before" -v`
Expected: FAIL — `AttributeError: module 'scripts.lib.color' has no attribute 'plane_depth'`

- [ ] **Step 3: Implement**

`scripts/lib/color.py` currently has **no imports at all** — its first line is the
module docstring. Add `import re` on the line after the docstring.

Then, immediately after the `TV_LO, TV_SPAN = 16.0, 219.0` line:

```python
_DEPTH_SUFFIX = re.compile(r"(\d+)(le|be)$")


def plane_depth(pix_fmt: str) -> int:
    """Bits per sample carried by an ffmpeg pixel-format name.

    Read from the NAME, deliberately. ffprobe also reports `bits_per_raw_sample`
    and it is not trustworthy here: measured 2026-08-27 against the footage this
    slice was designed on, the one real 10-bit clip in the pool
    (`DJI_20260625083848_0548_D.MP4`, HEVC) reports `N/A` for that field while
    its `pix_fmt` says `yuv420p10le` — the exact file the guard exists to catch
    is the file that field cannot describe.

    An 8-bit format carries no depth marker at all (`yuv420p`, `yuvj420p`,
    `nv12`, `gray`), so the ABSENCE of one is eight bits, not an unknown.
    """
    m = _DEPTH_SUFFIX.search(pix_fmt)
    return int(m.group(1)) if m else 8


def refuse_ungradeable_plane(pix_fmt: str, color_range: str, src: str) -> None:
    """Refuse pixels this module's colour maths cannot read (design §4.3).

    TV_LO/TV_SPAN are constants of BOTH bit depth and range — together they say
    "the stored luma plane runs 16..235 in eight bits" — and every knob in
    grade_chain is written against that plane. Neither half is negotiable, and
    both fail SILENTLY when violated:

      * wrong range: measured, a full-range source lands 8.5 luma codes from the
        target it was given, against a MATCH_EPS of 4.0;
      * wrong depth: measured on a real 10-bit clip, tone_arg returns a plane
        with 99.26% of its pixels pinned to a single code.

    Only these two properties. Codec and resolution are nobody's assumption here,
    and refusing on them would block legitimate hand runs for no reason.

    An "unknown" range PASSES: untagged is the mp4/h264 convention for limited
    and assembly.matches already reads it that way. A full-range file that lost
    its tag is therefore still misread — a known gap, design §7, not an oversight.
    """
    depth = plane_depth(pix_fmt)
    if depth != 8:
        raise ValueError(
            f"{src}: pixel format {pix_fmt} carries {depth} bits per sample, and this "
            f"pipeline's colour maths is written for 8 (TV_LO={TV_LO:.0f}, "
            f"TV_SPAN={TV_SPAN:.0f} describe an 8-bit limited luma plane). Rendering it "
            f"anyway does not shift the picture, it destroys it — measured on a real "
            f"10-bit clip, 99% of the pixels come back on one code. Cut this source "
            f"through scripts.extract first: it re-encodes to 8-bit yuv420p at the "
            f"source's own resolution.")
    if color_range == "pc":
        raise ValueError(
            f"{src}: color_range is pc (full, 0-255) and this pipeline's colour maths "
            f"is written for tv (limited, {TV_LO:.0f}-{TV_LO + TV_SPAN:.0f}). The grade "
            f"would be evaluated at the wrong place on its own curve, and everything "
            f"above code {TV_LO + TV_SPAN:.0f} would collapse onto one value — measured, "
            f"8.5 luma codes off target against a MATCH_EPS of 4.0, with nothing "
            f"failing. Cut this source through scripts.extract first: it normalizes "
            f"the range.")
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py -v`
Expected: PASS, including every pre-existing test in the file.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/color.py tests/lib/test_color.py
git commit -m "feat: name the plane the colour maths is written for"
```

---

### Task 1: `extract` normalizes the range

**Files:**
- Modify: `scripts/extract.py:13-24` (`extract()`)
- Modify: `tests/conftest.py` (two fixtures + one control helper)
- Test: `tests/lib/test_extract.py`, `tests/integration/test_extract.py`

**Interfaces:**
- Consumes: nothing from Task 0.
- Produces:
  - `extract.extract(src, start, dur, out, crf=18)` — same signature; its output
    is now always `color_range` tv-or-untagged. Task 4's proofs depend on that.
  - `pc_ramp_clip` (session fixture) → `Path` to a 640x360 / 2s / 30fps
    `yuvj420p`+`pc` horizontal luma ramp. Used by Tasks 1 and 4.
  - `tenbit_clip` (session fixture) → `Path` to a 320x180 / 1s / 30fps
    `yuv420p10le` luma ramp. Used by Tasks 1, 3 and 4.
  - `extract_unnormalized` (function fixture) → a callable
    `(src, start, dur, out) -> out` running `extract`'s command as it stood
    before this task. Used by Tasks 1 and 4.

- [ ] **Step 1: Add the fixtures**

In `tests/conftest.py`, after the `ramp_clip` fixture:

```python
@pytest.fixture(scope="session")
def pc_ramp_clip(tmp_path_factory):
    """2s 640x360 30fps FULL-RANGE clip: a horizontal luma ramp, tagged
    yuvj420p / color_range=pc.

    A ramp and not a flat field, because the defect it must reproduce is a tone
    transfer landing on the wrong place of a curve — a fixture with one luma
    value has no curve to be wrong about. MEASURED that it discriminates, which
    is the only reason it is worth having: cut with extract's arguments as they
    stood before 2026-08-27 and graded to a common target, the achieved profile
    misses by (-38.1, 0.0, -9.0); cut through the normalizing extract it misses
    by (-2.1, -0.5, -1.0).

    The bt709 description is NOT decoration. Measured 2026-08-27: ffmpeg writes
    the VUI's range flag only when it also writes a colour description, so a
    range-only source normalizes to `color_range=unknown` and no tag assertion
    can discriminate. Real footage always carries the description — the Canon
    this was designed against is bt709/bt709/bt709/pc — so a fixture without one
    was the unrealistic thing, not the test.
    """
    try:
        binary = ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    out = tmp_path_factory.mktemp("media") / "pc_ramp.mp4"
    proc.run([binary, "-y", "-f", "lavfi", "-i", "nullsrc=s=640x360:d=2:r=30",
              "-vf", "format=gray,geq=lum='X*255/W',format=yuvj420p",
              "-c:v", "libx264", "-crf", "18", "-preset", "medium",
              "-color_range", "pc", "-color_primaries", "bt709",
              "-color_trc", "bt709", "-colorspace", "bt709",
              "-pix_fmt", "yuvj420p", str(out)])
    return out


@pytest.fixture(scope="session")
def tenbit_clip(tmp_path_factory):
    """1s 320x180 30fps TEN-BIT clip (yuv420p10le): a horizontal luma ramp.

    Carries no range tag, on purpose. The pool this slice was designed against
    holds three 10-bit HEVC clips and the real one reports
    `bits_per_raw_sample=N/A` with an unremarkable range — so depth is the only
    property that can catch it, and the fixture is shaped to make that the only
    property under test.
    """
    try:
        binary = ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    out = tmp_path_factory.mktemp("media") / "tenbit.mp4"
    proc.run([binary, "-y", "-f", "lavfi", "-i", "nullsrc=s=320x180:d=1:r=30",
              "-vf", "format=gray,geq=lum='X*255/W',format=yuv420p10le",
              "-c:v", "libx264", "-crf", "18", "-preset", "medium",
              "-pix_fmt", "yuv420p10le", str(out)])
    return out


@pytest.fixture
def extract_unnormalized():
    """extract.extract's command as it stood BEFORE the range normalization.

    A deliberate duplicate of production argv, and the only kind this repo
    allows, because it is the CONTROL: without it the byte-identity proofs would
    assert that two runs of the same command agree, which proves nothing, and the
    transfer-error proof would have no broken path to compare against.

    Do not "DRY" this against extract.extract. The day it tracks the production
    command is the day every proof built on it stops discriminating.
    """
    def _run(src, start, dur, out):
        proc.run([ffbin.ffmpeg(), "-y", "-i", str(src), "-ss", f"{start}", "-t", f"{dur}",
                  "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                  "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out)])
        return out
    return _run
```

- [ ] **Step 2: Write the failing argv test**

Add to `tests/lib/test_extract.py`:

```python
def test_extract_normalizes_the_range_and_keeps_the_seek_order(monkeypatch, tmp_path):
    """Both halves are emitted. Converting without tagging leaves a player
    re-expanding an already-expanded image; tagging without converting IS the
    corruption this exists to stop. And -ss still lands after -i (§12)."""
    seen = {}
    monkeypatch.setattr(extract.proc, "run", lambda cmd, **kw: seen.setdefault("cmd", cmd))
    extract.extract("a.mp4", 1.0, 2.0, str(tmp_path / "o.mp4"))
    cmd = seen["cmd"]
    assert cmd[cmd.index("-vf") + 1] == "scale=in_range=auto:out_range=tv"
    assert cmd[cmd.index("-color_range") + 1] == "tv"
    assert cmd.index("-ss") > cmd.index("-i")
    # The equality above is what pins "no dimensions in the scale" — resolution
    # stays native because reframe crops from native pixels (design §3). Do not
    # replace it with a looser digit scan: `"scale=640:360:in_range=auto:out_range=tv"
    # .split("=")` yields no element for which `.isdigit()` is true, so a scan
    # like that reads as a guard and catches nothing.
```

- [ ] **Step 3: Write the failing real-ffmpeg tests**

Add to `tests/integration/test_extract.py` (it needs `import hashlib`,
`from pathlib import Path` and `proc` added to its `from scripts.lib import ...`
line):

```python
def _md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def _stream(path, field):
    out = subprocess.run(
        [ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0",
         "-show_entries", f"stream={field}", "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    return json.loads(out.stdout)["streams"][0].get(field)


@pytest.mark.integration
def test_normalizing_is_byte_identical_on_an_untagged_source(
        sample_clip, extract_unnormalized, tmp_path):
    """Control 1 of 3, and the one that protects every golden in this repo:
    every fixture here is untagged, ffmpeg reads untagged as limited, so the
    conversion is a no-op and the bytes must not move."""
    old = extract_unnormalized(sample_clip, 0.5, 1.0, tmp_path / "old.mp4")
    new = tmp_path / "new.mp4"
    extract.extract(src=str(sample_clip), start=0.5, dur=1.0, out=str(new))
    assert _md5(new) == _md5(old)


@pytest.mark.integration
def test_normalizing_is_byte_identical_on_an_explicitly_limited_source(
        sample_clip, extract_unnormalized, tmp_path):
    """Control 2 of 3: an untagged source and a tv-TAGGED source are different
    inputs to `in_range=auto`, and only one of them is covered above."""
    tagged = tmp_path / "tagged.mp4"
    # the bt709 description is required for the tag to be written at all — see
    # pc_ramp_clip's docstring; `-color_range tv` alone leaves ffprobe at "unknown"
    proc.run([ffbin.ffmpeg(), "-y", "-i", str(sample_clip), "-c:v", "libx264",
              "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
              "-color_range", "tv", "-color_primaries", "bt709",
              "-color_trc", "bt709", "-colorspace", "bt709", str(tagged)])
    assert _stream(tagged, "color_range") == "tv", "the control source is not tagged"

    old = extract_unnormalized(tagged, 0.5, 1.0, tmp_path / "old.mp4")
    new = tmp_path / "new.mp4"
    extract.extract(src=str(tagged), start=0.5, dur=1.0, out=str(new))
    assert _md5(new) == _md5(old)


@pytest.mark.integration
def test_normalizing_is_byte_identical_on_a_ten_bit_source(
        tenbit_clip, extract_unnormalized, tmp_path):
    """Control 3 of 3: the depth conversion `-pix_fmt yuv420p` already performs
    must not change because a range filter joined the chain."""
    old = extract_unnormalized(tenbit_clip, 0.2, 0.5, tmp_path / "old.mp4")
    new = tmp_path / "new.mp4"
    extract.extract(src=str(tenbit_clip), start=0.2, dur=0.5, out=str(new))
    assert _stream(new, "pix_fmt") == "yuv420p"
    assert _md5(new) == _md5(old)


@pytest.mark.integration
def test_a_full_range_source_comes_out_limited(
        pc_ramp_clip, extract_unnormalized, tmp_path):
    """The change itself. Note what the control proves: today's command READS as
    a normalization and is not one — libx264 keeps full range for a full-range
    input. That is the entire defect."""
    old = extract_unnormalized(pc_ramp_clip, 0.2, 1.0, tmp_path / "old.mp4")
    new = tmp_path / "new.mp4"
    extract.extract(src=str(pc_ramp_clip), start=0.2, dur=1.0, out=str(new))
    assert (_stream(old, "color_range"), _stream(old, "pix_fmt")) == ("pc", "yuvj420p")
    assert (_stream(new, "color_range"), _stream(new, "pix_fmt")) == ("tv", "yuv420p")
    assert _md5(new) != _md5(old)


@pytest.mark.integration
def test_normalizing_leaves_the_resolution_alone(sample_clip, tmp_path):
    """The scale filter carries no dimensions on purpose: reframe crops from
    native pixels, so a downscale here would discard exactly the detail a 4K
    source was shot for (design §3)."""
    out = tmp_path / "seg.mp4"
    extract.extract(src=str(sample_clip), start=0.5, dur=1.0, out=str(out))
    assert (_stream(out, "width"), _stream(out, "height")) == (1920, 1080)
```

- [ ] **Step 4: Run them and watch the right ones fail**

Run: `.venv/bin/python -m pytest tests/lib/test_extract.py tests/integration/test_extract.py -v`
Expected:
- `test_extract_normalizes_the_range_and_keeps_the_seek_order` FAILS with
  `ValueError: '-vf' is not in list`
- `test_a_full_range_source_comes_out_limited` FAILS on
  `('pc', 'yuvj420p') == ('tv', 'yuv420p')`
- the **three byte-identity controls PASS already** — they are controls, and a
  control that fails before the change is not a control. If one of them is red
  here, stop and report.

- [ ] **Step 5: Implement**

In `scripts/extract.py`, replace the `cmd` list inside `extract()`:

```python
    cmd = [
        ffbin.ffmpeg(), "-y", "-i", src,
        "-ss", f"{start}", "-t", f"{dur}",
        # The segment is the pipeline's canonical form and its range is part of
        # that contract (design 2026-08-27 §2). `-pix_fmt yuv420p` alone READS as
        # a normalization and is not one: measured, libx264 keeps full range for
        # a full-range input, so a Canon window — 67 of the 99 clips this was
        # designed against — shipped `yuvj420p`/pc the whole way into reframe's
        # lutyuv, whose TV_LO/TV_SPAN are written for 16..235.
        # in_range=auto reads the source's own tag (and ffmpeg's yuvj=>full
        # default when it has none), so this CONVERTS the samples; -color_range
        # writes the matching tag. Both halves are needed, and it is the same
        # pair assembly._normalize already uses at concat — moved to where it can
        # still save the grade instead of arriving after it.
        # The scale carries NO dimensions: resolution stays native because
        # reframe crops from native pixels (design §3). Measured byte-identical
        # on untagged, tv-tagged and 10-bit sources, so no golden moves.
        "-vf", "scale=in_range=auto:out_range=tv", "-color_range", "tv",
        "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out,
    ]
```

- [ ] **Step 6: Run the tests and watch them all pass**

Run: `.venv/bin/python -m pytest tests/lib/test_extract.py tests/integration/test_extract.py -v`
Expected: PASS, all of them, controls included.

- [ ] **Step 7: Run the whole suite — this is the golden check**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q`

The branch's baseline, measured on the merge that opened it, is **3140 passed,
1 skipped**. The rule is not "the number matches" — this task adds tests, so the
count must rise — it is that **no test which passed before now fails**. Read the
failure list, not the total.

If ANY golden moved, stop and report. The design's central byte-identity claim
would then be wrong, and it is the design that needs revising, not the test.

- [ ] **Step 8: Commit**

```bash
git add scripts/extract.py tests/conftest.py tests/lib/test_extract.py tests/integration/test_extract.py
git commit -m "fix: the segment was the one link that never said tv"
```

---

### Task 2: the tone map continues its shoulder instead of flattening

**Files:**
- Modify: `scripts/lib/color.py` — `tone_arg` (the expression tail) and `_lerp`
- Test: `tests/lib/test_color.py`, `tests/integration/test_matchgrade.py`

**Interfaces:**
- Consumes: `color.TV_LO`, `TV_SPAN`, `_segments`, `TONE_TOP_SLOPE` — all already
  in the file.
- Produces: no signature changes. `tone_arg(src, dst) -> str` and
  `_lerp(knots, x) -> float` keep their shapes; only the value above the last
  knot changes.

**No new fixture.** `tests/integration/test_matchgrade.py::_ramp_y` already feeds
a raw `yuv444p` plane with one sample per input code 0..255 and reads the raw
plane back, with no format conversion anywhere — so it reaches the superwhite
band directly. `reframe.verify_tone` cannot: it feeds **rgb24**, and rgb
255,255,255 converts to stored Y 235, so the region this task changes is
structurally invisible to it. Do not build the proof on `verify_tone`.

- [ ] **Step 1: Write the failing unit tests**

Add to `tests/lib/test_color.py`:

```python
def test_lerp_continues_the_last_segment_above_the_final_knot():
    knots = [(0.0, 0.0), (100.0, 50.0), (200.0, 100.0)]      # last slope 0.5
    assert color._lerp(knots, 200.0) == pytest.approx(100.0)
    assert color._lerp(knots, 240.0) == pytest.approx(120.0)
    assert color._lerp(knots, 278.3) == pytest.approx(139.15, abs=0.01)


def test_lerp_stays_flat_above_a_zero_width_final_segment():
    # p95 == 255 makes the final segment zero-width: there is no shoulder to
    # continue, so the map ends at its value rather than dividing by zero.
    knots = [(0.0, 0.0), (100.0, 50.0), (255.0, 120.0), (255.0, 120.0)]
    assert color._lerp(knots, 270.0) == pytest.approx(120.0)


def test_tone_arg_extends_the_shoulder_in_the_emitted_expression():
    frag = color.tone_arg((30.0, 100.0, 200.0), (40.0, 110.0, 190.0))
    # The final else-branch is now an expression anchored at the TOP knot
    # (x = 255) instead of a bare constant. No other segment subtracts 255 —
    # they subtract their own left anchor (0, 30, 100, 200) — so this substring
    # exists only when the extension is emitted.
    assert "-255.0000)*" in frag, frag


def test_tone_arg_keeps_a_constant_tail_when_p95_is_255():
    # zero-width final segment: the extension must not divide by zero, and must
    # not emit a slope it does not have
    frag = color.tone_arg((30.0, 100.0, 255.0), (40.0, 110.0, 200.0))
    assert "-255.0000)*" not in frag, frag
    assert frag.startswith("lutyuv=y='") and frag.endswith("',")
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py -k "lerp or shoulder or p95_is_255" -v`
Expected: FAIL — `test_lerp_continues...` returns 100.0 where it wants 120.0;
`test_tone_arg_extends...` finds no `-255.0000)*`. The two "stays flat" /
"constant tail" tests PASS already; they are the zero-width controls.

- [ ] **Step 3: Implement `_lerp`**

Replace `_lerp` in `scripts/lib/color.py`:

```python
def _lerp(knots: list[tuple[float, float]], x: float) -> float:
    """Piecewise-linear interpolation through sorted (in, out) knots, CONTINUING
    the final segment's slope above the last knot.

    No production caller since 2026-08-19, and kept deliberately: it is the tone
    map's reference definition, and tone_arg's emitted expression is a SECOND,
    independent implementation of the same arithmetic. The real-ffmpeg proof
    renders through one and compares against the other, which is only a proof
    because they are not the same code — a shared bug would cancel. Do not
    "simplify" by having tone_arg call this, and do not factor the extrapolation
    below into a helper both call: that is the same mistake wearing a hat.
    """
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    (x0, y0), (x1, y1) = knots[-2], knots[-1]
    if x1 == x0:
        return y1
    return y1 + (x - x1) * (y1 - y0) / (x1 - x0)
```

- [ ] **Step 4: Implement `tone_arg`'s tail**

In `tone_arg`, replace these three lines:

```python
    v = f"(val-{TV_LO})*255/{TV_SPAN}"
    segs = _segments(src, dst)
    expr = f"{segs[-1][1]:.4f}"
```

with:

```python
    v = f"(val-{TV_LO})*255/{TV_SPAN}"
    segs = _segments(src, dst)
    # ABOVE the top knot the map CONTINUES at the shoulder's own slope instead of
    # flattening onto a constant. Measured 2026-08-27 through the per-code ramp
    # harness: the constant put every stored code 236..255 onto ONE output (202)
    # — twenty codes to one, which is exactly the plate TONE_TOP_SLOPE's own
    # docstring exists to prevent — while continuing the slope spreads them over
    # 202..209 and leaves 200..235 untouched (14 distinct codes either way).
    # Bounded without clipping in every legal case: the largest `v` a stored code
    # can produce is (255-16)*255/219 = 278.3, `top` is at most 255 and this
    # slope at most TONE_TOP_SLOPE = 0.35 by construction of _segments, so the
    # extended output tops out at 242 — thirteen codes below the ceiling.
    # A zero-width final segment (p95 == 255) has no shoulder to continue and
    # keeps the constant, which is what "the map ends here" means.
    (xt0, yt0), (xt1, yt1) = segs[-2], segs[-1]
    expr = (f"{yt1:.4f}" if xt1 == xt0 else
            f"({yt1:.4f}+({v}-{xt1:.4f})*{(yt1 - yt0) / (xt1 - xt0):.6f})")
```

The `for` loop below it is unchanged.

- [ ] **Step 5: Run the unit tests and watch them pass**

Run: `.venv/bin/python -m pytest tests/lib/test_color.py -v`
Expected: PASS, including every pre-existing test in the file.

- [ ] **Step 6: Widen the existing render-vs-`_lerp` proof**

`tests/integration/test_matchgrade.py::test_the_tone_map_renders_within_a_code_of_itself`
compares the rendered LUT against `_lerp` over `[16:236]` only, and its trailing
comment says the expression "holds a constant above the shoulder" — which is
precisely what stopped being true. Widen the window and correct the comment:

```python
    worst = max(abs(g - w) for g, w in zip(got[16:256], want[16:256]))
    assert worst <= 1.0, f"the LUT is {worst:.2f} codes off its own map"
    # Monotone over the WHOLE 0-255 plane, not only the legal 16-235: the
    # expression extrapolates below the toe and CONTINUES THE SHOULDER'S SLOPE
    # above it (2026-08-27), and a wrap at either end would be real corruption in
    # sub-black or super-white pixels. Measured on the shipped map: outputs span
    # 2-205 and never step backwards.
    assert all(b >= a for a, b in zip(got, got[1:])), "the transfer bands somewhere"
```

The window moves to 256 and NOT to 0: below code 16 the emitted expression's
output can fall under 0, where `lutyuv` clamps and `_lerp` does not, so the two
would disagree for a reason that is not a defect. Measured over `[16:256]`, the
worst disagreement is **0.98 codes** — identical to the legal range's, i.e.
integer rounding and nothing else.

- [ ] **Step 7: Add the superwhite proof**

Add to `tests/integration/test_matchgrade.py`, beside the test above:

```python
def test_the_shoulder_carries_the_superwhite_band():
    """Above the top knot the map continues instead of flattening — and the band
    BELOW it does not move, which is what separates a fix from a rescale.

    Measured 2026-08-27 on this exact (src, dst): codes 236..255 came back as ONE
    output value and now come back as eight. reframe.verify_tone cannot see any
    of this — it feeds rgb24 and rgb 255 converts to stored Y 235."""
    src, dst = (71.0, 133.0, 203.0), (61.0, 123.0, 198.5)
    lut = _ramp_y(color.tone_arg(src, dst).rstrip(","))

    tail = lut[236:256]
    assert len(set(tail)) == 8, sorted(set(tail))          # was 1
    assert (min(tail), max(tail)) == (202, 209)

    band = lut[200:236]                                     # the control
    assert (len(set(band)), min(band), max(band)) == (14, 189, 202)
```

- [ ] **Step 8: Run the integration proofs and watch them pass**

Run: `.venv/bin/python -m pytest tests/integration/test_matchgrade.py -v`
Expected: PASS.

If `len(set(tail))` comes back as anything but 8, do NOT edit the number to
match. The figure came from this exact harness and this exact `(src, dst)` pair,
so a different answer means something else changed — re-measure by hand and
report.

- [ ] **Step 9: Run the whole suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q`
Expected: same counts as after Task 1.

- [ ] **Step 10: Commit**

```bash
git add scripts/lib/color.py tests/lib/test_color.py tests/integration/test_matchgrade.py
git commit -m "fix: twenty highlight codes were arriving as one"
```

---

### Task 3: `reframe` refuses pixels its colour maths cannot read

**Files:**
- Modify: `scripts/reframe.py:205-238` (`_probe`) and `:454` (`plan_render`)
- Modify: `tests/lib/test_reframe.py` (5 stubs + 4 new tests),
  `tests/integration/test_reframe.py` (7 stubs),
  `tests/integration/test_process_episode.py` (3 stubs)

**Interfaces:**
- Consumes: `color.refuse_ungradeable_plane(pix_fmt, color_range, src)` (Task 0).
  No fixture: every test here stubs `_probe`, and the proof over REAL files —
  the only thing that shows `_probe` actually reports the two new fields — is
  Task 4's, which is where `tenbit_clip` is used.
- Produces: `reframe._probe(src) -> tuple[int, int, float, float, str, str]` —
  `(width, height, fps, duration, pix_fmt, color_range)`. **Every test that stubs
  `_probe` must return six values.**

- [ ] **Step 1: Write the failing tests**

Add to `tests/lib/test_reframe.py`. The file already imports `ReframeSpec`,
`Delivery` and `PanSpec` (used at line 260); reuse those imports.

```python
def _guard_spec(**kw):
    base = dict(composition="lead", grid="thirds", canvas=(9, 16),
                color_means=(110.0, 120.0, 130.0),
                delivery=Delivery.from_spec("short_edge:540"),
                pan=PanSpec(start=0.0, end=0.2))
    return ReframeSpec(**{**base, **kw})


def test_plan_render_refuses_a_full_range_source(monkeypatch):
    monkeypatch.setattr(reframe, "_probe",
                        lambda src: (1920, 1080, 30.0, 2.0, "yuvj420p", "pc"))
    with pytest.raises(ValueError, match="pc"):
        reframe.plan_render(_guard_spec(), "src.mp4", None)


def test_plan_render_refuses_a_ten_bit_source(monkeypatch):
    monkeypatch.setattr(reframe, "_probe",
                        lambda src: (1920, 1080, 30.0, 2.0, "yuv420p10le", "tv"))
    with pytest.raises(ValueError, match="10 bits"):
        reframe.plan_render(_guard_spec(), "src.mp4", None)


def test_plan_render_accepts_an_untagged_eight_bit_source(monkeypatch):
    monkeypatch.setattr(reframe, "_probe",
                        lambda src: (1920, 1080, 30.0, 2.0, "yuv420p", "unknown"))
    assert reframe.plan_render(_guard_spec(), "src.mp4", None).fps == 30.0


def test_the_guard_runs_even_with_no_colour_knob_set(monkeypatch):
    """The contract is about the segment, not about whether this episode happens
    to grade: every knob in grade_chain reads the same plane, and check_episode
    compares episodes to each other, so a pc episode is the wrong pixels even
    ungraded."""
    monkeypatch.setattr(reframe, "_probe",
                        lambda src: (1920, 1080, 30.0, 2.0, "yuvj420p", "pc"))
    spec = ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                       delivery=Delivery.from_spec("short_edge:540"),
                       pan=PanSpec(start=0.0, end=0.2))     # no color_means, no tone
    with pytest.raises(ValueError, match="pc"):
        reframe.plan_render(spec, "src.mp4", None)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_reframe.py -k "refuses or untagged or no_colour_knob" -v`
Expected: all four FAIL with
`ValueError: too many values to unpack (expected 4)` — `plan_render` still
unpacks four values from these six-value stubs. That is the right failure: it
proves the stubs reach the production unpack.

- [ ] **Step 3: Widen `_probe`**

In `scripts/reframe.py`, change the signature, the docstring's opening, the
`-show_entries` string and the `return`:

```python
def _probe(src: str) -> tuple[int, int, float, float, str, str]:
    """(width, height, fps, duration, pix_fmt, color_range) — one ffprobe call.

    The duration is load-bearing engine input, not diagnostics: the `solid` filler
    bounds its synthesized background with `color=:d=<duration>` (design §4). Both
    the stream's and the container's duration are asked for in the same call, since
    some containers carry only the latter; the stream's is preferred.

    pix_fmt and color_range ride the SAME call (design 2026-08-27 §4.3) — they are
    what plan_render's colour guard reads, and asking for them here costs nothing.
    color_range is "unknown" when the stream carries no tag, the same word
    assembly.probe_stream uses for the same condition.
    """
    out = proc.run(
        [ffbin.ffprobe(), "-v", "error", "-select_streams", "v:0",
         "-show_entries",
         "stream=width,height,avg_frame_rate,duration,pix_fmt,color_range:format=duration",
         "-of", "json", src], text=True)
```

and the final line of the function:

```python
    return (int(s["width"]), int(s["height"]), fps, dur,
            s.get("pix_fmt") or "", s.get("color_range") or "unknown")
```

- [ ] **Step 4: Wire the guard into `plan_render`**

At `scripts/reframe.py:454`, replace:

```python
    src_w, src_h, fps, dur = _probe(src)
```

with:

```python
    src_w, src_h, fps, dur, pix_fmt, color_range = _probe(src)
    # Before any geometry: the colour maths downstream is written for an 8-bit
    # limited luma plane, and both halves of that fail SILENTLY when violated
    # (design 2026-08-27 §4.3). Refused here rather than beside the grade because
    # every knob reads the same plane and check_episode compares episodes to each
    # other — an ungraded pc episode is still the wrong pixels.
    color.refuse_ungradeable_plane(pix_fmt, color_range, src)
```

`scripts/reframe.py:6` already imports `color`; no import change is needed.

- [ ] **Step 5: Widen every `_probe` stub**

Fifteen sites. The rule: a stub returning `(w, h, fps, dur)` returns
`(w, h, fps, dur, "yuv420p", "tv")`. Find them all with:

```bash
grep -rn '"_probe"' tests/
```

Twelve are plain literals. Three are not, and need reading rather than a blind
edit:

- `tests/integration/test_process_episode.py:62` — `_stub_engine`'s
  `dims=(1920, 1080, 30.0, 3.0)` default. Widen the default; the helper takes
  `dims[:2]` for `sw, sh`, which is unaffected.
- `tests/integration/test_process_episode.py:124` — a caller passing
  `dims=(3840, 2160, 59.94, 1.584917)`; widen it the same way.
- `tests/integration/test_process_episode.py:859` — `dims = (1920, 1080, 30.0, 3.0)`
  feeding both `_stub_engine` and a local `spy_probe`; widen that one tuple.

Keeping the stubs hermetic is the point. A stub still returning four values would
raise on the unpack; a stub *removed* would send `plan_render` into a real
ffprobe on a path like `"src.mp4"` that does not exist.

- [ ] **Step 6: Run the affected suites**

Run: `.venv/bin/python -m pytest tests/lib/test_reframe.py tests/integration/test_reframe.py tests/integration/test_process_episode.py tests/integration/test_probe.py -q`
Expected: PASS.

- [ ] **Step 7: Run the whole suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q`
Expected: same counts as after Task 2. Watch
`tests/integration/test_stabilize.py` in particular — the stabilize pre-stage
feeds its own output to reframe, and if that output were tagged anything but
tv-or-unknown the guard would now fire. It should not. If it does, report rather
than weakening the guard: it would mean the pre-stage is itself off-contract,
which is a finding, not an inconvenience.

- [ ] **Step 8: Commit**

```bash
git add scripts/reframe.py tests/lib/test_reframe.py tests/integration/test_reframe.py tests/integration/test_process_episode.py
git commit -m "feat: refuse pixels the colour maths cannot read"
```

---

### Task 4: the end-to-end proofs

**Files:**
- Create: `tests/integration/test_segment_range.py`

**Interfaces:**
- Consumes: `extract.extract` (Task 1), `color.tone_arg` (Task 2),
  `reframe.plan_render` (Task 3), the `pc_ramp_clip` / `tenbit_clip` /
  `extract_unnormalized` fixtures (Task 1).
- Produces: nothing other tasks read.

- [ ] **Step 1: Write the four proofs**

```python
"""End-to-end proofs for the segment format contract (design 2026-08-27).

Each carries its own control. The central claim — that normalizing the range at
extract fixes the grade — is only a claim if the un-normalized path is shown to
break on the same bytes, so every proof here builds both paths.
"""
import numpy as np
import pytest

from scripts import extract, reframe
from scripts.lib import assembly, color, ffbin, proc
from scripts.lib.models import Delivery, PanSpec, ReframeSpec

pytestmark = pytest.mark.integration

W, H = 640, 360                 # pc_ramp_clip's dimensions
DST = (40.0, 120.0, 200.0)      # a plausible common target for that ramp


def _profile(clip, vf=None):
    """(p5, p50, p95) exactly the way measure_profile reads them: `format=gray`,
    which honours the source's range tag and converts."""
    chain = f"{vf},format=gray" if vf else "format=gray"
    raw = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", str(clip), "-ss", "0.500",
                    "-frames:v", "1", "-vf", chain,
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    a = np.frombuffer(raw[:W * H], dtype=np.uint8)
    return tuple(round(float(np.percentile(a, q)), 1) for q in (5, 50, 95))


def _both_ways(pc_ramp_clip, extract_unnormalized, tmp_path):
    old = extract_unnormalized(pc_ramp_clip, 0.2, 1.0, tmp_path / "old.mp4")
    new = tmp_path / "new.mp4"
    extract.extract(src=str(pc_ramp_clip), start=0.2, dur=1.0, out=str(new))
    return old, new


def test_normalizing_the_range_lands_the_grade_on_its_target(
        pc_ramp_clip, extract_unnormalized, tmp_path):
    """The slice's central claim, with its own control.

    Measured 2026-08-27 on this fixture: the un-normalized path misses by
    (-38.1, 0.0, -9.0) and the normalized one by (-2.1, -0.5, -1.0). The bars
    below sit far from both, so an encoder nudge cannot flip the verdict.
    """
    old, new = _both_ways(pc_ramp_clip, extract_unnormalized, tmp_path)
    errs = {}
    for name, seg in (("old", old), ("new", new)):
        src = _profile(seg)
        got = _profile(seg, color.tone_arg(src, DST).rstrip(","))
        errs[name] = [g - d for g, d in zip(got, DST)]

    assert max(abs(e) for e in errs["old"]) > 20.0, errs      # the defect reproduces
    assert max(abs(e) for e in errs["new"]) <= 5.0, errs      # and the fix closes it
    assert max(abs(e) for e in errs["new"]) < max(abs(e) for e in errs["old"]) / 4


def test_normalizing_does_not_move_the_profile_the_grade_is_measured_from(
        pc_ramp_clip, extract_unnormalized, tmp_path):
    """match_grade measures the RAW source and reframe grades the SEGMENT. That
    only works because `format=gray` reports the same profile either side of the
    normalization — measured (51, 113, 194) both ways on the real Canon frame.
    Load-bearing, so pinned rather than left to luck."""
    old, new = _both_ways(pc_ramp_clip, extract_unnormalized, tmp_path)
    for a, b in zip(_profile(old), _profile(new)):
        assert abs(a - b) <= 1.0, (_profile(old), _profile(new))


def test_a_normalized_segment_no_longer_reads_as_a_concat_outlier(
        pc_ramp_clip, extract_unnormalized, tmp_path):
    """The quiet win: assembly.matches classified a full-range episode as an
    outlier and re-encoded it whole before concat — a full extra generation for
    two thirds of the pool. It matches now, and concat copies it."""
    old, new = _both_ways(pc_ramp_clip, extract_unnormalized, tmp_path)
    assert not assembly.matches(assembly.probe_stream(str(old)), (W, H), 30.0)
    assert assembly.matches(assembly.probe_stream(str(new)), (W, H), 30.0)


def test_the_guard_stops_raw_footage_and_passes_an_extracted_segment(
        pc_ramp_clip, tenbit_clip, tmp_path):
    """plan_render over REAL files — no stubbed probe anywhere, which is the only
    way to prove _probe actually reports the two fields the guard reads."""
    spec = ReframeSpec(composition="lead", grid="thirds", canvas=(9, 16),
                       delivery=Delivery.from_spec("short_edge:180"),
                       pan=PanSpec(start=0.0, end=0.2))
    with pytest.raises(ValueError, match="pc"):
        reframe.plan_render(spec, str(pc_ramp_clip), None)
    with pytest.raises(ValueError, match="10 bits"):
        reframe.plan_render(spec, str(tenbit_clip), None)

    seg = tmp_path / "seg.mp4"
    extract.extract(src=str(pc_ramp_clip), start=0.2, dur=1.0, out=str(seg))
    assert reframe.plan_render(spec, str(seg), None).fps == pytest.approx(30.0)
```

- [ ] **Step 2: Run them and watch them pass**

Run: `.venv/bin/python -m pytest tests/integration/test_segment_range.py -v`
Expected: PASS, all four.

- [ ] **Step 3: Prove each proof discriminates**

A proof that would pass both before and after the change proves nothing. For each
of the four, mutate deliberately, confirm RED, then restore the line by
**re-typing it** (`git checkout --` and `git stash` are forbidden by the global
constraints) and confirm GREEN again.

| # | mutation | must go RED |
|---|----------|-------------|
| 1 | in `extract.extract`, delete `"-color_range", "tv"` | `test_normalizing_the_range_lands_the_grade_on_its_target` |
| 2 | in `extract.extract`, change `out_range=tv` to `out_range=auto` | proofs 1 and 3 |
| 3 | in `plan_render`, delete the `refuse_ungradeable_plane` call | `test_the_guard_stops_raw_footage_and_passes_an_extracted_segment` |
| 4 | in `_probe`, return `"tv"` for `color_range` unconditionally | proof 4's `pc` arm |

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_segment_range.py
git commit -m "test: the un-normalised path breaks on the same bytes"
```

---

### Task 5: the mutation battery, and the docs

**Files:**
- Modify: `docs/backlog.md`, `docs/build-status.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing code reads.

- [ ] **Step 1: Run the mutation battery**

Every row: apply the mutation, run the named test selection, record RED or GREEN,
restore by re-typing the line, re-run, confirm GREEN. All under
`PYTHONDONTWRITEBYTECODE=1`. **A row that stays GREEN is a coverage hole — write
the missing test, do not soften the row.**

| # | file | mutation | must go RED |
|---|------|----------|-------------|
| 1 | `color.py` | `plane_depth` returns `8` always | `tests/lib/test_color.py -k plane_depth` |
| 2 | `color.py` | `plane_depth`'s regex drops the `be` alternative: `r"(\d+)le$"` | `tests/lib/test_color.py -k plane_depth` |
| 3 | `color.py` | `refuse_ungradeable_plane` drops the depth branch | `tests/lib/test_color.py`, `tests/lib/test_reframe.py -k ten_bit` |
| 4 | `color.py` | `refuse_ungradeable_plane` drops the range branch | `tests/lib/test_color.py`, `tests/integration/test_segment_range.py` |
| 5 | `color.py` | `refuse_ungradeable_plane` also refuses `"unknown"` | `tests/lib/test_color.py -k untagged`, and the whole suite |
| 6 | `color.py` | `tone_arg`'s tail reverts to `f"{segs[-1][1]:.4f}"` | `tests/integration/test_matchgrade.py -k superwhite`, `tests/lib/test_color.py -k shoulder` |
| 7 | `color.py` | `tone_arg`'s tail drops the `xt1 == xt0` arm | `tests/lib/test_color.py -k p95_is_255` |
| 8 | `color.py` | `_lerp` reverts to `return knots[-1][1]` | `tests/lib/test_color.py -k lerp`, `tests/integration/test_matchgrade.py -k within_a_code` |
| 9 | `color.py` | `_lerp`'s extrapolation uses `knots[0]`/`knots[1]`'s slope | `tests/lib/test_color.py -k lerp` |
| 10 | `extract.py` | drop `"-vf", "scale=..."`, keep the tag | `tests/lib/test_extract.py`, `tests/integration/test_segment_range.py` |
| 11 | `extract.py` | drop `"-color_range", "tv"`, keep the filter | `tests/lib/test_extract.py`, `tests/integration/test_segment_range.py` |
| 12 | `extract.py` | `out_range=tv` → `out_range=pc` | `tests/integration/test_extract.py -k full_range` |
| 13 | `extract.py` | add dimensions: `scale=640:360:in_range=auto:out_range=tv` | `tests/lib/test_extract.py`, `tests/integration/test_extract.py -k resolution` |
| 14 | `extract.py` | move `-ss` before `-i` | `tests/lib/test_extract.py -k seek_order` |
| 15 | `reframe.py` | `plan_render` drops the guard call | `tests/lib/test_reframe.py -k refuses`, `tests/integration/test_segment_range.py` |
| 16 | `reframe.py` | `_probe` returns `"yuv420p"` for `pix_fmt` unconditionally | `tests/integration/test_segment_range.py -k guard` |
| 17 | `reframe.py` | `_probe` returns `"tv"` for `color_range` unconditionally | `tests/integration/test_segment_range.py -k guard` |
| 18 | `reframe.py` | `_probe` drops `pix_fmt,color_range` from `-show_entries` | `tests/integration/test_segment_range.py -k guard` |
| 19 | `test_matchgrade.py` | narrow the widened window back to `got[16:236]` | nothing — **expected GREEN**, and the row exists to say so: the widened window is coverage, and no test can defend its own boundary. Record the result. |

Rows 16–18 exist because every other guard test stubs `_probe`; without a proof
over real files, `_probe` could stop reporting either field and only
`test_segment_range.py` would notice.

Row 5 goes red in two places, which is the point: it is the one row asserting the
guard's deliberate blind spot (§7) rather than its reach.

- [ ] **Step 2: Record the battery's outcome**

The table and its results go into step 5's commit message. If any row stayed
GREEN (other than 19, which is expected to), add the test that closes it in this
task, re-run the row, and say so explicitly — the hole and its fix both belong in
the record.

- [ ] **Step 3: Update `docs/backlog.md`**

- Flip **R2.0** to `✅` with a summary carrying the measured numbers: 67 of 99
  clips full-range; the fix is one filter pair in `extract`; transfer error
  8.5 → 1.5 codes against a `MATCH_EPS` of 4.0; byte-identical on untagged,
  tv-tagged and 10-bit sources; the quantization price of 1 code, mean 0.141,
  36 of 256 levels; and the correction that `measure_profile` was **never**
  broken — the retro's own claim is wrong, `format=gray` reads the source tag
  (DJI mean |Δ| 4.59, Canon 0.41).
- Flip **R2.3** to `✅`, noting it had two halves and both landed: the range
  (subsumed by R2.0's fix) and the superwhite band (20 codes to 1, now 1 to 8),
  plus the depth hole the row never named — a real 10-bit clip returns 99.26% of
  its pixels on one code, now refused at `plan_render`.
- Add to **P2**: *Colour matrix / primaries / transfer are not in the segment
  contract.* All 99 clips of the only real pool are bt709, so there is no
  evidence to build against; a bt601 or HLG source is misread silently. Source:
  this design §8.
- Add to **P2**: *Nothing gates that the authored tone actually reached its
  target.* Adjacent to R2.2 and R2.6 but neither of them — those judge drift and
  regression, not whether the pair the conductor authored was reached. Source:
  this design §7.
- Add to **P3**: *Nobody has looked at the extended shoulder.* Eight codes
  instead of one is strictly more information; whether it looks better is
  unmeasured, and it touches 0.1247% of pixels on the frame it was measured on.

- [ ] **Step 4: Update `docs/build-status.md` and `CLAUDE.md`**

- `docs/build-status.md`: a Done entry dated 2026-08-27 naming the three changes,
  the measured before/after, and the two surprises — the retro's
  measurement-side claim was wrong, and the depth hole was in no row at all.
- `CLAUDE.md`: two rows in the Quick Reference table, one for the design and one
  for this plan, matching the existing rows' shape and density. The design row
  must carry the load-bearing half: that `-pix_fmt yuv420p` reads as a
  normalization and is not one, and that `TV_LO`/`TV_SPAN` are constants of depth
  as well as range.
- `CLAUDE.md` **Known troubles**: add one bullet. This is a silent-corruption
  landmine and belongs in always-loaded context:

  > `-pix_fmt yuv420p` on an encode does **not** normalize the colour range —
  > libx264 keeps full range for a full-range input, and ffprobe then reports the
  > output as `yuvj420p`/`pc`. Converting takes
  > `scale=in_range=auto:out_range=tv` **and** `-color_range tv`: the filter
  > without the tag leaves a player re-expanding an already-expanded image, and
  > the tag without the filter is the corruption itself. `TV_LO`/`TV_SPAN` are
  > constants of **bit depth** as well as range — a 10-bit plane through the same
  > LUT comes back with 99% of its pixels on one code.

- [ ] **Step 5: Run the whole suite one last time and commit**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q`
Expected: PASS; report the exact counts in the commit message.

```bash
git add docs/backlog.md docs/build-status.md CLAUDE.md
git commit -m "docs: the range the delivery always declared"
```

---

## Notes for the implementer

- **`reframe.verify_tone` cannot see Task 2's change.** It feeds an rgb24 ramp
  and rgb 255,255,255 converts to stored Y 235, so the extended region is
  unreachable through it. `_ramp_y` in `tests/integration/test_matchgrade.py`
  hands ffmpeg a raw `yuv444p` plane with one sample per code 0..255 and reads
  the plane straight back — that is the harness the superwhite proof uses. Do not
  "simplify" the proof onto `verify_tone`, and do not route `_ramp_y` through
  `format=gray`, which would expand tv to full and hide the very band it measures
  (its own docstring records that trap).
- **No test pins `tone_arg`'s exact fragment string.** Checked: the three that
  touch it assert `startswith("lutyuv=y='")` / `endswith("',")`. Task 2 will not
  move a golden for that reason.
- **The landmine lint passes the new `extract` argv** — confirmed by running
  `lint.check_argv` over the proposed command, which returned `[]`. If it starts
  reporting, something else changed.
- **`scripts/lib/color.py` has no imports today.** `import re` goes on the line
  after the module docstring, and it is the file's only import.
