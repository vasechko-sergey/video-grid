# Assemble-draft (stage 5.9) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render `draft.mp4` — a QA preview of the whole reel (concat of the extracted raw segments, scale-fit into the SPEC canvas, with burnt-in `processing_notes` labels and a rough music bed) that a human eyeballs at the §4.1 CP2 checkpoint before the expensive process-episode pass.

**Architecture:** The repo's contract-in-lib / driver-here split. Pure, unit-testable helpers (font resolution, caption text, the per-segment filter string) in `scripts/lib/draft.py`; the ffmpeg driver + CLI in `scripts/draft.py`, proven by a real-ffmpeg golden. A small refactor extracts the shared concat-demuxer step out of `scripts/lib/assembly.py` so the draft and the final assembler reuse it. The draft is muxed with a music bed by reusing `mix.mix` (one source of truth for laying music). Router: an **optional** `assemble-draft` Stage in `montage.py` (never becomes `next`, so the autonomous chain is untouched); no standalone judgment SKILL.

**Tech Stack:** Python 3, ffmpeg/ffprobe (drawtext, concat demuxer, scale/pad), pytest (`pytest.mark.integration` for real-ffmpeg goldens). Scripts run as modules (`pythonpath = .`, `.venv/bin/python -m ...`).

**Spec:** `docs/specs/2026-07-13-assemble-draft-design.md`.

**Conventions (read `docs/coding-standards.md` + `docs/testing-guide.md` first):** module docstring; imports at top; every module-level def fully typed; fail loud with a remedy (`ValueError` naming the value + fix, never a bare `KeyError`/`TypeError`); config-specs validate in `__post_init__`. Do **not** pipe pytest through `tail` (masks the exit code) — append `; echo "EXIT: $?"` (zsh: `$pipestatus[1]`). Commit bodies end with the `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` trailer.

**Landmines in play (design §12):** `drawtext` needs an explicit `fontfile=` (macOS has no fontconfig default — an unset font silently renders no text); free-text in a filtergraph must use `textfile=` not `text=` (a `:`/`'` in notes mis-tokenizes); even output dims (`force_divisible_by=2` on the scale). `-ss` after `-i` is already handled inside `extract.extract`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `scripts/lib/draft.py` (create) | Pure helpers: `FONT_CANDIDATES`, `resolve_font`, `label_text`, `segment_filter`. No ffmpeg, no writes. |
| `scripts/lib/assembly.py` (modify) | Extract `concat(entries, out_master)` from `assemble()`; `assemble()` calls it. |
| `scripts/draft.py` (create) | Driver `build_draft(...)` + `main()` CLI. Extract → per-segment label-burn → concat → music mux. |
| `scripts/assemble.py` (modify) | Docstring: point the "draft sibling" at `scripts/draft.py`. |
| `scripts/montage.py` (modify) | Add the optional `assemble-draft` Stage between `edit-plan` and `deliver`. |
| `SKILLS/using-montage/SKILL.md` (modify) | Offer the draft as an optional CP2 preview step after edit-plan. |
| `tests/lib/test_draft.py` (create) | Unit tests for the three pure helpers. |
| `tests/lib/test_assembly.py` (modify) | A direct `concat()` test; existing tests stay green. |
| `tests/integration/test_draft.py` (create) | Real-ffmpeg golden: canvas-fit + music mux + silent variant + CLI. |
| `tests/lib/test_montage.py` (modify) | Patch the stage-table assertions; add an optional absent→present case. |
| `docs/pipeline-map.md`, `docs/build-status.md`, `docs/specs/2026-07-05-montage-skillset-design.md`, `CLAUDE.md` (modify) | Docs sync. |

---

## Task 0: `scripts/lib/draft.py` — pure helpers

**Files:**
- Create: `scripts/lib/draft.py`
- Test: `tests/lib/test_draft.py`

- [x] **Step 1: Write the failing tests**

Create `tests/lib/test_draft.py`:

```python
import pytest

from scripts.lib import draft


def test_resolve_font_returns_first_existing_candidate(tmp_path, monkeypatch):
    f = tmp_path / "F.ttf"
    f.write_text("x")
    monkeypatch.setattr(draft, "FONT_CANDIDATES",
                        (str(tmp_path / "missing.ttf"), str(f)))
    assert draft.resolve_font() == str(f)


def test_resolve_font_override_wins(tmp_path):
    f = tmp_path / "over.ttf"
    f.write_text("x")
    assert draft.resolve_font(str(f)) == str(f)


def test_resolve_font_missing_override_fails_loud(tmp_path):
    with pytest.raises(ValueError, match="--font"):
        draft.resolve_font(str(tmp_path / "nope.ttf"))


def test_resolve_font_none_found_fails_loud(monkeypatch):
    monkeypatch.setattr(draft, "FONT_CANDIDATES", ())
    with pytest.raises(ValueError, match="fontfile"):
        draft.resolve_font()


def test_label_text_without_notes_is_header_only():
    assert draft.label_text(0, "wide", "") == "#0 wide"
    assert draft.label_text(2, "close", "   ") == "#2 close"


def test_label_text_with_notes_adds_second_line():
    assert draft.label_text(1, "medium", "track surfer") == "#1 medium\ntrack surfer"


def test_segment_filter_carries_fit_and_label_pieces():
    vf = draft.segment_filter((1080, 1920), 30.0, "/f.ttf", "/tmp/l.txt")
    for piece in ("scale=1080:1920", "force_divisible_by=2", "pad=1080:1920",
                  "fps=30.0", "format=yuv420p", "drawtext=",
                  "fontfile='/f.ttf'", "textfile='/tmp/l.txt'"):
        assert piece in vf, piece
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_draft.py -q ; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.draft'`.

- [x] **Step 3: Implement the helpers**

Create `scripts/lib/draft.py`:

```python
"""Draft-preview helpers (montage §5.9): font resolution, the burnt caption text,
and the per-segment scale-fit + label filter string. Pure — no ffmpeg, no writes;
the ffmpeg driver is scripts/draft.py. Split out so these fail fast in unit tests
(the drawtext fontfile landmine — design §12 — is caught here, not at render)."""
from pathlib import Path

FONT_CANDIDATES: tuple[str, ...] = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",     # macOS
    "/System/Library/Fonts/Helvetica.ttc",              # macOS
    "/Library/Fonts/Arial.ttf",                         # macOS (older installs)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Debian/Ubuntu
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",           # Fedora/Arch
)


def resolve_font(override: str | None = None) -> str:
    """First existing font path for drawtext. `override` wins (must exist). None
    found → ValueError with the --font remedy. drawtext needs an explicit fontfile=
    (design §5.9, §12): macOS has no reliable fontconfig default, so an unset font
    silently renders no text — fail loud instead."""
    if override is not None:
        if not Path(override).exists():
            raise ValueError(
                f"--font {override!r} does not exist — pass a path to a .ttf/.ttc/.otf")
        return override
    for cand in FONT_CANDIDATES:
        if Path(cand).exists():
            return cand
    raise ValueError(
        f"no usable draft-label font found among {FONT_CANDIDATES} — pass --font "
        "PATH to a .ttf/.ttc/.otf (drawtext needs an explicit fontfile=; there is no "
        "fontconfig default on macOS)")


def label_text(idx: int, shot_type: str, processing_notes: str) -> str:
    """The burnt caption for episode `idx`: a '#idx shot_type' header, plus a second
    line with processing_notes when the author gave any. Written to a textfile so
    drawtext's textfile= sidesteps filtergraph escaping of ':' / apostrophes."""
    head = f"#{idx} {shot_type}"
    notes = processing_notes.strip()
    return f"{head}\n{notes}" if notes else head


def segment_filter(dims: tuple[int, int], fps: float, font: str, textfile: str) -> str:
    """The -vf string for one draft segment: scale-fit + letterbox pad into the SPEC
    canvas `dims` (no creative crop — that is process-episode), fps-normalize,
    yuv420p, then the drawtext label (semi-opaque box, bottom-left). force_divisible_by=2
    keeps the scaled intermediate even (the even-dims landmine, design §12)."""
    w, h = dims
    label = (f"drawtext=fontfile='{font}':textfile='{textfile}':fontsize=h/24:"
             f"fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=12:x=40:y=h-th-40")
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p,{label}")
```

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_draft.py -q ; echo "EXIT: $?"`
Expected: PASS (7 passed).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/draft.py tests/lib/test_draft.py
git commit -m "feat: lib/draft.py — font resolve + label text + segment filter (5.9)"
```

---

## Task 1: `scripts/lib/assembly.py` — extract `concat()`

**Files:**
- Modify: `scripts/lib/assembly.py:73-95` (the `assemble()` function)
- Test: `tests/lib/test_assembly.py` (add one test)

**Context:** `assemble()` currently inlines the concat-demuxer step (write `_concat.txt`, run `ffmpeg -f concat -c copy`). Extract it into a public `concat()` so the draft driver reuses it. Behaviour must stay identical — the existing `test_assembly.py` asserts on the listfile contents and the `-c copy` command.

- [x] **Step 1: Write the failing test**

Add to `tests/lib/test_assembly.py` (the file already imports `json`, `Path`, `SimpleNamespace`, `pytest`, `assembly`):

```python
def test_concat_writes_resolved_escaped_listfile_and_copies(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(assembly.proc, "run",
                        lambda cmd, **k: calls.append(cmd) or SimpleNamespace(stdout=b""))
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    assembly.concat([str(a), str(b)], str(tmp_path / "w" / "m.mp4"))
    listtext = (tmp_path / "w" / "_concat.txt").read_text()
    assert f"file '{a.resolve()}'" in listtext and f"file '{b.resolve()}'" in listtext
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "concat" in joined and "-c copy" in joined
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_assembly.py::test_concat_writes_resolved_escaped_listfile_and_copies -q ; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: module 'scripts.lib.assembly' has no attribute 'concat'`.

- [x] **Step 3: Refactor — add `concat()`, make `assemble()` call it**

In `scripts/lib/assembly.py`, replace the entire `assemble()` function (lines 73-95) with these two functions (order matters — `concat` uses `_concat_quote`, defined above; `assemble` uses `concat`):

```python
def concat(entries: list[str], out_master: str) -> str:
    """Concat pre-uniform files losslessly (-c copy) via the concat demuxer. Writes
    the list file next to out_master, resolving + escaping each entry path. Shared by
    assemble() (final reel, after normalizing outliers) and the draft driver
    (scripts/draft.py, over already-burned segments)."""
    work = Path(out_master).parent
    work.mkdir(parents=True, exist_ok=True)
    listfile = work / "_concat.txt"
    listfile.write_text("".join(
        f"file '{_concat_quote(str(Path(p).resolve()))}'\n" for p in entries))
    proc.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
              "-c", "copy", out_master])
    return out_master


def assemble(episodes: list[str], dims: tuple[int, int], fps: float, out_master: str) -> str:
    """Concat locked episodes into one silent master. Reference = the caller's
    intended (dims, fps) — the same delivery process-episode rendered to. All
    match → lossless -c copy; an outlier is normalized alone, then copy-concat."""
    if len(episodes) < 1:
        raise RuntimeError("assemble needs >= 1 locked episode, got none — the EDL "
                           "produced no episodes for this reel")
    work = Path(out_master).parent
    work.mkdir(parents=True, exist_ok=True)
    entries: list[str] = []
    for i, ep in enumerate(episodes):
        info = probe_stream(ep)
        if matches(info, dims, fps):
            entries.append(ep)
        else:
            norm = str(work / f"_norm_{i:03d}.mp4")
            _normalize(ep, dims, fps, norm)
            entries.append(norm)
    return concat(entries, out_master)
```

- [x] **Step 4: Run the whole assembly suite to verify green**

Run: `.venv/bin/python -m pytest tests/lib/test_assembly.py -q ; echo "EXIT: $?"`
Expected: PASS (all existing tests + the new `concat` test). The three key existing tests still hold because `concat()` resolves each entry (so `test_concat_list_escapes_single_quotes_in_paths` still sees `file '{ep.resolve()-escaped}'`), writes `_concat.txt` in `out_master.parent`, and runs `-c copy`; `assemble()` still calls `_normalize` only for the outlier.

- [x] **Step 5: Commit**

```bash
git add scripts/lib/assembly.py tests/lib/test_assembly.py
git commit -m "refactor: extract assembly.concat() for the draft to share (5.9)"
```

---

## Task 2: `scripts/draft.py` — `build_draft` + CLI + real-ffmpeg golden

**Files:**
- Create: `scripts/draft.py`
- Test: `tests/integration/test_draft.py`

**Context:** This is a media stage, so the driver is proven end-to-end by a real-ffmpeg golden (like `tests/integration/test_front_spine.py`), not a mocked unit test. The `sample_clip` session fixture (a 3s 1920×1080 clip) lives in `tests/conftest.py`. Because process-episode is **not** faked here, the draft's letterbox fit is real — so the golden additionally proves the draft dims equal the project canvas.

- [x] **Step 1: Write the failing golden**

Create `tests/integration/test_draft.py`:

```python
"""Real-ffmpeg golden for assemble-draft (montage §5.9, design docs/specs/
2026-07-13-assemble-draft-design.md): a project.json + a hand EDL.json + a sine-tone
MUSIC.json over the synthetic sample_clip -> build_draft -> a labelled, canvas-fit
draft.mp4 with a muxed music bed. Unlike test_front_spine, process_episode is NOT in
the loop, so the draft's scale-fit is real: this also proves crop-to-canvas
(the draft dims == the project canvas) on real bytes."""
import json

import pytest

from scripts import draft
from scripts.lib import assembly, proc
from scripts.lib.models import MusicSpec


def _project(tmp_path):
    p = tmp_path / "project.json"
    p.write_text(json.dumps({"purpose": "reel", "canvas": [1080, 1920], "delivery": "native"}))
    return str(p)


def _edl(tmp_path, source, music=None):
    row = lambda s, d, n: dict(source=source, start=s, dur=d, shot_type="wide",
                               composition="lead", grid="thirds", crop_scale=0.8,
                               processing_notes=n)
    doc = {"episodes": [row(0.2, 1.0, "track surfer, punch-in"), row(1.8, 1.0, "stabilize")]}
    if music:
        doc["music"] = music
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps(doc))
    return str(p)


def _dims(path):
    out = proc.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                    "stream=width,height", "-of", "csv=p=0:s=x", str(path)]).stdout.decode().strip()
    w, h = out.split("x")
    return int(w), int(h)


def _has_aac(path):
    return "aac" in proc.run(["ffprobe", "-v", "error", "-select_streams", "a",
                              "-show_entries", "stream=codec_name", "-of", "csv=p=0",
                              str(path)]).stdout.decode()


@pytest.mark.integration
def test_draft_fits_canvas_and_muxes_music(sample_clip, tmp_path):
    tone = tmp_path / "tone.wav"
    proc.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
              "-ac", "2", str(tone)])
    music = tmp_path / "MUSIC.json"
    music.write_text(json.dumps(
        MusicSpec(str(tone), 0.0, 2.0, 120.0, (0.0, 0.5, 1.0, 1.5), (0.3,), 2.0).to_dict()))
    out = tmp_path / "draft.mp4"
    res = draft.build_draft(
        _edl(tmp_path, sample_clip.name, str(music)), _project(tmp_path),
        footage_root=str(sample_clip.parent), work_dir=str(tmp_path / "w"), out=str(out))
    assert res == {"status": "written", "draft": str(out), "episodes": 2, "music": True}
    assert out.exists()
    assert _dims(out) == (1080, 1920)                       # real letterbox -> canvas dims
    assert abs(assembly.probe_duration(str(out)) - 2.0) < 0.2
    assert _has_aac(out)


@pytest.mark.integration
def test_draft_without_music_is_silent(sample_clip, tmp_path):
    out = tmp_path / "draft.mp4"
    res = draft.build_draft(
        _edl(tmp_path, sample_clip.name), _project(tmp_path),
        str(sample_clip.parent), str(tmp_path / "w"), str(out))
    assert res["music"] is False and res["episodes"] == 2
    assert out.exists() and _dims(out) == (1080, 1920)
    assert not _has_aac(out)


@pytest.mark.integration
def test_draft_cli_builds_and_exits_0(sample_clip, tmp_path, monkeypatch):
    out = tmp_path / "draft.mp4"
    monkeypatch.setattr("sys.argv",
                        ["draft", "build", "--edl", _edl(tmp_path, sample_clip.name),
                         "--project", _project(tmp_path), "--footage-root", str(sample_clip.parent),
                         "--work-dir", str(tmp_path / "w"), "--out", str(out)])
    with pytest.raises(SystemExit) as e:
        draft.main()
    assert e.value.code == 0 and out.exists()
```

- [x] **Step 2: Run the golden to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_draft.py -q ; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.draft'` (collection error).

- [x] **Step 3: Implement the driver**

Create `scripts/draft.py`:

```python
"""Assemble-draft (montage §5.9): render a QA-preview draft.mp4 from an EDL.json +
project.json — the extracted raw segments, scale-fit into the SPEC canvas, labelled
with each episode's processing_notes, over a rough music bed. The human eyeballs
layout / order / length / beat-landing at the §4.1 CP2 checkpoint before the
expensive process-episode pass. The draft sibling of scripts/assemble.py, over the
shared lib/assembly concat core; the pure label/fit helpers live in lib/draft.py."""
import argparse
import json
import tempfile
from pathlib import Path

from scripts import extract, mix
from scripts.lib import assembly, proc
from scripts.lib.draft import label_text, resolve_font, segment_filter
from scripts.lib.edl import EDL
from scripts.lib.models import MusicSpec
from scripts.lib.project import ProjectConfig


def build_draft(edl_path: str, project_path: str, footage_root: str, work_dir: str,
                out: str, *, music: str | None = None, font: str | None = None) -> dict:
    """EDL.json + project.json -> a QA-preview draft.mp4. Extract each window, burn a
    canvas-fit + processing_notes label into every segment, concat, then mux a rough
    music bed (reusing mix.mix — one source of truth for laying music; absent -> a
    silent draft). Returns {"status": "written", "draft", "episodes", "music"}."""
    edl = EDL.from_json(edl_path)
    cfg = ProjectConfig.from_json(project_path)
    dims = cfg.canvas
    fontfile = resolve_font(font)
    work = Path(work_dir)
    seg_dir = str(work / "segments")
    segments = extract.extract_edl(edl, footage_root, seg_dir)
    fps = assembly.probe_stream(segments[0]).fps

    labels_dir, burn_dir = work / "labels", work / "burned"
    labels_dir.mkdir(parents=True, exist_ok=True)
    burn_dir.mkdir(parents=True, exist_ok=True)
    burned: list[str] = []
    for i, (ep, seg) in enumerate(zip(edl.episodes, segments)):
        tf = labels_dir / f"label_{i}.txt"
        tf.write_text(label_text(i, ep.shot_type, ep.processing_notes))
        vf = segment_filter(dims, fps, fontfile, str(tf))
        bout = str(burn_dir / f"ep{i}_draft.mp4")
        proc.run(["ffmpeg", "-y", "-i", seg, "-vf", vf,
                  "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-an", bout])
        burned.append(bout)

    master = str(work / "draft_master.mp4")
    assembly.concat(burned, master)
    Path(out).parent.mkdir(parents=True, exist_ok=True)

    src = music or edl.music
    if src is None:
        proc.run(["ffmpeg", "-y", "-i", master, "-c", "copy", out])
    else:
        dur = assembly.probe_duration(master)
        with tempfile.TemporaryDirectory() as d:
            audio = mix.mix(MusicSpec.from_json(src), d, dur)
            proc.run(["ffmpeg", "-y", "-i", master, "-i", audio,
                      "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "copy",
                      "-shortest", out])
    return {"status": "written", "draft": out,
            "episodes": len(edl.episodes), "music": src is not None}


def main() -> None:
    ap = argparse.ArgumentParser(description="render a QA-preview draft.mp4 (montage §5.9)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build draft.mp4 from an EDL.json + project.json")
    b.add_argument("--edl", required=True)
    b.add_argument("--project", required=True, help="project.json — the SPEC canvas")
    b.add_argument("--footage-root", required=True, help="dir the EDL 'source' paths resolve against")
    b.add_argument("--work-dir", required=True, help="scratch for segments / labels / burned / master")
    b.add_argument("--out", required=True, help="draft.mp4 path (using-montage: <run-dir>/draft.mp4)")
    b.add_argument("--music", default=None, help="MUSIC.json path; overrides the EDL's music field")
    b.add_argument("--font", default=None, help="drawtext .ttf/.ttc/.otf (default: first system candidate)")
    a = ap.parse_args()
    result = build_draft(a.edl, a.project, a.footage_root, a.work_dir, a.out,
                         music=a.music, font=a.font)
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Run the golden to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_draft.py -q ; echo "EXIT: $?"`
Expected: PASS (3 passed). If ffmpeg is absent the `sample_clip` fixture skips — run on a machine with ffmpeg.

- [x] **Step 5: Commit**

```bash
git add scripts/draft.py tests/integration/test_draft.py
git commit -m "feat: scripts/draft.py — build_draft + CLI, real-ffmpeg golden (5.9)"
```

---

## Task 2b: drawtext preflight + golden skip-guard + setup

**Context:** `drawtext` (the label-burn filter) is not in every ffmpeg build — some ship without libfreetype, and then `build_draft` dies mid-render with a cryptic `No such filter: 'drawtext'`. Add a fail-loud runtime preflight, skip the golden when the filter is absent (so the suite is green on any machine), and make `setup.sh` install a drawtext-capable ffmpeg by default so a user never hits the runtime error.

**Files:**
- Modify: `scripts/draft.py` (add `ensure_drawtext`; call it in `build_draft`)
- Create: `tests/test_draft.py` (driver unit — monkeypatched, no real render)
- Modify: `tests/integration/test_draft.py` (autouse skip-guard)
- Modify: `setup.sh`
- Modify: `docs/development-workflow.md`

- [x] **Step 1: Write the failing unit tests** — Create `tests/test_draft.py`:

```python
from types import SimpleNamespace

import pytest

from scripts import draft


def _fake_filters(text):
    return lambda cmd, **k: SimpleNamespace(stdout=text.encode())


def test_ensure_drawtext_passes_when_present(monkeypatch):
    monkeypatch.setattr(draft.proc, "run",
                        _fake_filters(" T.. drawtext   V->V   Draw text on top of video.\n"))
    draft.ensure_drawtext()   # no raise


def test_ensure_drawtext_fails_loud_when_absent(monkeypatch):
    monkeypatch.setattr(draft.proc, "run",
                        _fake_filters(" T.. scale       V->V   Scale the input video.\n"))
    with pytest.raises(ValueError, match="drawtext"):
        draft.ensure_drawtext()
```

- [x] **Step 2: Run to verify fail** — `.venv/bin/python -m pytest tests/test_draft.py -q ; echo "EXIT: $?"` — Expected FAIL: `AttributeError: module 'scripts.draft' has no attribute 'ensure_drawtext'`.

- [x] **Step 3: Add `ensure_drawtext` + call it** — In `scripts/draft.py`, add this function above `build_draft`:

```python
def ensure_drawtext(ffmpeg: str = "ffmpeg") -> None:
    """Fail loud if `ffmpeg` lacks the drawtext filter — the draft label burn needs
    it, and a missing filter otherwise surfaces as a cryptic 'No such filter:
    drawtext' mid-render. setup.sh installs a drawtext-capable ffmpeg; this is the
    runtime backstop (a different ffmpeg may be on PATH)."""
    filters = proc.run([ffmpeg, "-hide_banner", "-filters"]).stdout.decode("utf-8", errors="replace")
    if "drawtext" not in filters:
        raise ValueError(
            f"{ffmpeg} has no drawtext filter — the draft labels need it. Install a "
            "drawtext-capable ffmpeg (libfreetype): run `bash setup.sh`, or "
            "`brew install ffmpeg`.")
```

And make it the first statement in `build_draft` (before `edl = EDL.from_json(...)`):

```python
    ensure_drawtext()
    edl = EDL.from_json(edl_path)
```

- [x] **Step 4: Run unit tests → pass** — `.venv/bin/python -m pytest tests/test_draft.py -q ; echo "EXIT: $?"` — Expected PASS (2 passed).

- [x] **Step 5: Add the golden skip-guard** — In `tests/integration/test_draft.py`, add `import shutil` at the top and this autouse fixture (after the imports, before `_project`):

```python
@pytest.fixture(autouse=True)
def _need_drawtext():
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    filters = proc.run(["ffmpeg", "-hide_banner", "-filters"]).stdout.decode(errors="replace")
    if "drawtext" not in filters:
        pytest.skip("ffmpeg built without the drawtext filter (run: bash setup.sh)")
```

- [x] **Step 6: Run the golden** — `.venv/bin/python -m pytest tests/integration/test_draft.py -q ; echo "EXIT: $?"` — Expected: 3 passed where ffmpeg has drawtext, or 3 skipped where it does not — either way `EXIT: 0`.

- [x] **Step 7: `setup.sh` drawtext block** — Add this block **after** the existing `vidstab` block (after its closing `fi`, before the `# --- venv + python deps ---` line):

```bash
# drawtext: the assemble-draft stage (§5.9) burns labels via drawtext, which needs
# libfreetype. Most homebrew ffmpeg builds carry it; some don't. The homebrew-ffmpeg
# tap full build has drawtext (and vidstab). Unlike vidstab this is a baseline
# requirement (the draft stage needs it), so ensure it by default — the branch only
# fires, and only replaces ffmpeg, when drawtext is genuinely missing.
if ! ffmpeg -hide_banner -filters 2>/dev/null | grep -q drawtext; then
  need_brew ffmpeg
  echo "ffmpeg lacks drawtext (needed for draft labels) -> installing drawtext-capable ffmpeg (homebrew-ffmpeg tap, replaces core ffmpeg)..."
  brew tap homebrew-ffmpeg/ffmpeg
  brew uninstall --ignore-dependencies ffmpeg 2>/dev/null || true
  brew install homebrew-ffmpeg/ffmpeg/ffmpeg
  ffmpeg -hide_banner -filters 2>/dev/null | grep -q drawtext || { echo "ERROR: drawtext still missing after tap install"; exit 1; }
fi
```

- [x] **Step 8: `docs/development-workflow.md` note** — In §Environment, change the ffmpeg requirement bullet from:

```markdown
- Requires `ffmpeg` + `ffprobe` on PATH. Every script fails loud with a remedy if
  a binary is missing (`brew install ffmpeg`).
```

to:

```markdown
- Requires `ffmpeg` + `ffprobe` on PATH, and the `ffmpeg` must include the
  `drawtext` filter (libfreetype) — the assemble-draft stage (§5.9) burns labels
  with it. `setup.sh` ensures a drawtext-capable ffmpeg. Every script fails loud
  with a remedy if a binary or filter is missing (`brew install ffmpeg`).
```

- [x] **Step 9: Commit** — do NOT run `setup.sh` (it mutates the machine's Homebrew — the user runs it themselves).

```bash
git add scripts/draft.py tests/test_draft.py tests/integration/test_draft.py setup.sh docs/development-workflow.md
git commit -m "feat: drawtext preflight + golden skip-guard + setup ensures it (5.9)"
```

Append the `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` trailer.

---

## Task 3: `scripts/montage.py` — optional `assemble-draft` Stage

**Files:**
- Modify: `scripts/montage.py:47-51` (the `V1_STAGES` tuple)
- Test: `tests/lib/test_montage.py`

**Context:** The draft is off the critical path. As an **optional** stage it is never chosen as `next` (`next_action` advances `next` only past *required* stages), so the autonomous `project → footage → edit-plan → deliver` sequence is unchanged. `checkpoint="edl"` because the draft is CP2's richer artifact — it shares `"edl"` with `edit-plan`, exactly as `project-init` and `reel-brief` share `"spec"`. `in_out=False` → `draft.mp4` is looked for in the run dir.

- [x] **Step 1: Write the failing test patches**

In `tests/lib/test_montage.py`:

(a) In `test_v1_stages_order_and_keys`, change the expected key list to insert `"assemble-draft"` between `"edit-plan"` and `"deliver"`:

```python
def test_v1_stages_order_and_keys():
    assert [s.key for s in V1_STAGES] == [
        "project-init", "footage-intake", "reel-brief", "trend-scan",
        "music-and-mood", "pacing", "edit-plan", "assemble-draft", "deliver"]
```

(b) In `test_v1_stages_kinds_and_flags`, add after the `reel-brief` assertions:

```python
    assert by["assemble-draft"].kind == "optional"
    assert by["assemble-draft"].artifact == "draft.mp4"
    assert by["assemble-draft"].checkpoint == "edl"
    assert by["assemble-draft"].in_out is False
```

(c) Add a new test (mirrors `test_reel_brief_optional_absent_then_present`):

```python
def test_assemble_draft_optional_absent_then_present(tmp_path):
    for n in ("project.json", "FOOTAGE.json", "EDL.json"):
        _touch(tmp_path, n)
    res = next_action(str(tmp_path))
    assert _state(res, "assemble-draft") == "optional"   # absent optional never blocks
    assert res["next"] == "deliver"                       # next unaffected by an optional stage
    _touch(tmp_path, "draft.mp4")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "assemble-draft") == "done"
    assert res2["next"] == "deliver"
```

- [x] **Step 2: Run the montage suite to verify the new/changed assertions fail**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q ; echo "EXIT: $?"`
Expected: FAIL — `test_v1_stages_order_and_keys` (list mismatch), `test_v1_stages_kinds_and_flags` (`KeyError: 'assemble-draft'`), `test_assemble_draft_optional_absent_then_present`.

- [x] **Step 3: Add the Stage row**

In `scripts/montage.py`, in the `V1_STAGES` tuple, insert the `assemble-draft` row between the `edit-plan` and `deliver` rows:

```python
    Stage("edit-plan", "EDL.json", "required",
          "edit-plan SKILL -> edit_plan build CLI", "edl"),
    Stage("assemble-draft", "draft.mp4", "optional",
          "draft CLI (optional QA preview)", "edl"),
    Stage("deliver", "REEL_v*.*", "required",
          "edl_to_reel CLI", "final", in_out=True),
```

- [x] **Step 4: Run the montage suite to verify green**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q ; echo "EXIT: $?"`
Expected: PASS (all montage tests, including the unchanged `test_edl_present_next_is_deliver` — an optional stage between `edit-plan` and `deliver` does not change `next`).

- [x] **Step 5: Commit**

```bash
git add scripts/montage.py tests/lib/test_montage.py
git commit -m "feat: router — optional assemble-draft stage (draft.mp4, CP2) (5.9)"
```

---

## Task 4: Wiring — `using-montage` SKILL + `assemble.py` docstring

**Files:**
- Modify: `SKILLS/using-montage/SKILL.md`
- Modify: `scripts/assemble.py:1-3` (docstring)

**Context:** No standalone SKILL for the draft — it is mechanical. `using-montage` offers it as an optional preview at CP2, after edit-plan produces the EDL and before `edl_to_reel` commits the expensive render.

- [x] **Step 1: Add the optional draft step to using-montage**

Read `SKILLS/using-montage/SKILL.md`. Find the step where edit-plan produces the `EDL.json` / the CP2 (EDL/plan approval) checkpoint is described, immediately before the `edl_to_reel` render step. Insert an **optional** step with this content (match the file's existing numbering/heading style):

> **Optional — assemble-draft (§5.9, CP2 preview).** Before the expensive
> process-episode render, offer a rough draft: "Want to see a rough cut first?"
> If yes, run `draft build --edl <EDL.json> --project <project.json>
> --footage-root <dir> --work-dir <work> --out <run-dir>/draft.mp4
> [--music <MUSIC.json>]`. `draft.mp4` concats the raw segments, scale-fit into
> the canvas, with `processing_notes` labels and a rough music bed — the human
> eyeballs layout / order / length / beat-landing and approves (or goes back to
> edit-plan) at CP2. This stage is optional: `montage status` never points `next`
> at it, and the autonomous path skips it.

Also, wherever the CP2 checkpoint artifact is named (`EDL.md`), add that `draft.mp4` is CP2's richer artifact when the user asked for a preview.

- [x] **Step 2: Update the `assemble.py` docstring**

In `scripts/assemble.py`, replace the docstring sentence:

```python
"""Final reel assembler (чистовик, design §3): ordered locked episodes → one
silent master via lib.assembly. The draft assembler is a later sibling over the
same core."""
```

with:

```python
"""Final reel assembler (чистовик, design §3): ordered locked episodes → one
silent master via lib.assembly. Its draft sibling is scripts/draft.py — a labelled
QA preview over the same lib.assembly.concat core (montage §5.9)."""
```

- [x] **Step 3: Verify nothing broke**

Run: `.venv/bin/python -m pytest tests/lib/test_assembly.py tests/lib/test_montage.py -q ; echo "EXIT: $?"`
Expected: PASS (the docstring change is inert; this confirms no accidental edit).

- [x] **Step 4: Commit**

```bash
git add SKILLS/using-montage/SKILL.md scripts/assemble.py
git commit -m "docs: using-montage offers the optional CP2 draft; assemble sibling pointer (5.9)"
```

---

## Task 5: Docs sync + final review

**Files:**
- Modify: `docs/pipeline-map.md`
- Modify: `docs/build-status.md`
- Modify: `docs/specs/2026-07-05-montage-skillset-design.md`
- Modify: `CLAUDE.md`

- [x] **Step 1: `docs/pipeline-map.md`**

Make these edits:
- The `_Last updated:_` line → `2026-07-13`.
- 15-stage table, the `5.9  | assemble-draft` row: `Status` `❌ → ✅`; replace the note with: `draft CLI + typed helpers (scripts/draft.py, scripts/lib/draft.py) — concat of raw segments, canvas-fit, processing_notes labels + music bed (SP1b, 5.9)`.
- Remaining-work table, the `5.9 | assemble-draft` row: `St` `❌ → ✅`; `Left to build` → `— (2026-07-13)`.
- Tally line: `9 ✅ · 3 ◐ · 3 ❌` → `10 ✅ · 3 ◐ · 2 ❌`.
- Front-half narrative (the "What produces a reel today" paragraph and/or the "Front-half authoring" roadmap bullet): drop `SP1b (draft.mp4)` from the "Remaining" list — the front-half remaining is now `SP4 (trend-scan)` (plus the parallel-quality items already listed).

- [x] **Step 2: `docs/build-status.md`**

Read it, then: append a DONE entry for assemble-draft mirroring the format of the prior entries (e.g. the reel-brief one), naming `scripts/draft.py` + `scripts/lib/draft.py` + the `assembly.concat` refactor + the optional `montage.py` Stage + the real-ffmpeg golden; and narrow the "Next action" line (5.9 done — the front-half remaining is trend-scan (5.4, YAGNI) and the real-footage end-to-end v1 gate; audio B3/B4 and 5.12/5.13 stay as parallel quality).

- [x] **Step 3: `docs/specs/2026-07-05-montage-skillset-design.md`**

Under the `### 5.9 assemble-draft → draft.mp4` section, add a Built note (mirror the other `> **Built (...)**` blocks):

```markdown
> **Built (2026-07-13, SP1b):** `scripts/draft.py` `build_draft` — extract each EDL
> window, burn a canvas-fit (letterbox) + `processing_notes` label into every
> segment (`scripts/lib/draft.py`: `resolve_font`/`label_text`/`segment_filter`,
> the explicit-`fontfile=` landmine caught in a unit test), concat via the shared
> `assembly.concat`, and mux a rough music bed by reusing `mix.mix`. An optional
> `assemble-draft` router Stage (CP2, `draft.mp4`) — never the autonomous `next`.
> No creative crop/track (process-episode), no ducked ambient (§5.12). See
> `docs/plans/2026-07-13-assemble-draft.md`.
```

- [x] **Step 4: `CLAUDE.md`**

In the Quick Reference table, add two rows (mirror the reel-brief design/plan rows) — one for the design, one for the plan:

```markdown
| Assemble-draft spine design | [2026-07-13-assemble-draft-design.md](docs/specs/2026-07-13-assemble-draft-design.md) | Stage 5.9: `draft.mp4` QA preview — concat of raw segments, canvas-fit + `processing_notes` labels (drawtext `fontfile=`/`textfile=` landmines) + rough music bed (reuse `mix.mix`); thin `lib/draft.py` helpers + `scripts/draft.py` driver, shared `assembly.concat`, optional router Stage (CP2). |
| Assemble-draft spine plan | [2026-07-13-assemble-draft.md](docs/plans/2026-07-13-assemble-draft.md) | Tasks 0–5: `lib/draft.py` helpers, `assembly.concat` refactor, `draft.py` `build_draft`+CLI+real-ffmpeg golden, optional `montage.py` Stage + test patch, using-montage wiring, docs. |
```

- [x] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`
Expected: PASS — the pre-existing count (592 passed, 1 skipped as of the reel-brief merge) plus the new tests (Task 0: 7; Task 1: 1; Task 2: 3 integration; Task 3: 1 new + 2 patched). Confirm `EXIT: 0`.

- [x] **Step 6: Commit**

```bash
git add docs/pipeline-map.md docs/build-status.md docs/specs/2026-07-05-montage-skillset-design.md CLAUDE.md
git commit -m "docs: sync pipeline-map/build-status/spec/registry for assemble-draft (5.9)"
```

- [x] **Step 7: Final whole-slice review**

Dispatch a final code-quality reviewer over the whole branch diff (`git diff main...HEAD`) against the spec `docs/specs/2026-07-13-assemble-draft-design.md`. Confirm: the drawtext landmines (explicit `fontfile=`, `textfile=` for free-text) are honoured; `assembly.concat` behaviour is identical (existing tests green); the draft Stage is optional (never `next`); the golden proves canvas-fit + music mux + silent variant. Then use superpowers:finishing-a-development-branch.

---

## Self-Review

**1. Spec coverage:**
- §1 intent / shape (lib + driver + assembly refactor, no SKILL) → Tasks 0–4. ✓
- §2 driver `build_draft` (read → extract → probe fps → burn → concat → music mux → dict) → Task 2. ✓
- §3 helpers `resolve_font` / `label_text` / `segment_filter` (+ `textfile=` rationale, fontfile landmine) → Task 0. ✓
- §4 `assembly.concat` refactor → Task 1. ✓
- §5 router optional Stage (`draft.mp4`, `optional`, `checkpoint="edl"`, `in_out=False`) + test patches + using-montage wiring + assemble docstring → Tasks 3–4. ✓
- §6 testing (unit helpers, `concat` test, montage patches, real-ffmpeg golden with canvas-dims + music + silent) → Tasks 0–3. ✓
- §7 non-goals — nothing to build. ✓
- §8 docs to sync → Task 5. ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows complete code; the `force_divisible_by=2` / `textfile=` details are concrete. The using-montage insert (Task 4) is prose into a prose SKILL — the exact block is given; the subagent places it by the described anchor (the file is not reproduced here because it is not code). ✓

**3. Type consistency:** `build_draft(edl_path, project_path, footage_root, work_dir, out, *, music=None, font=None) -> dict` is used identically in the golden and the CLI. `segment_filter(dims, fps, font, textfile)`, `label_text(idx, shot_type, processing_notes)`, `resolve_font(override=None)`, `concat(entries, out_master)` match between definition and callers. `MusicSpec(track, start_offset, duration, tempo, beats, energy, energy_hz)` matches the golden literal. The router Stage tuple matches `Stage(key, artifact, kind, runner, checkpoint, in_out=False)`. ✓
