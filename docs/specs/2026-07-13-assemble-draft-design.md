# Assemble-draft spine (stage 5.9) — design

**Date:** 2026-07-13
**Status:** approved (brainstorming) → plan next
**Stage:** 5.9 `assemble-draft` → `draft.mp4`

## 1. Intent

`assemble-draft` renders `draft.mp4`: a **QA preview of the whole reel before the
expensive process-episode pass**. It concats the extracted raw segments
(`segments/*_raw.mp4`) into the whole shape at once with **burnt-in labels** (what
each episode will be processed into, from the EDL's `processing_notes`) and a
**rough music bed** — so a human can eyeball layout / order / length / beat-landing
and decide go-or-back at the §4.1 **CP2** checkpoint, *before* committing YOLO +
per-episode ffmpeg to `edl_to_reel`.

"Almost no processing" (design §5.9) = no *creative* processing. Concat still
demands uniform streams, so the draft scale-fits every segment into the SPEC
canvas (letterbox — **no creative crop**; that is process-episode's job) and
unifies fps/codec first. Creative reframe, tracking, color, ducked ambient and
beat-accurate pacing all stay downstream.

The draft is **off the critical path**: the autonomous chain
`project.json → FOOTAGE.json → EDL.json → REEL` runs without it. It is an
*optional* stage — offered to a human, never a mandatory gate.

**Shape:** the contract-in-lib / driver-here split the repo already uses
(`lib/edl.py` + `scripts/edit_plan.py`; `lib/spec.py` + `scripts/reel_brief.py`):

- `scripts/lib/draft.py` — pure, unit-testable-without-ffmpeg helpers (font
  resolution, label text, the per-segment filter string).
- `scripts/draft.py` — the ffmpeg driver + CLI (`build_draft`), proven by a
  real-ffmpeg golden.
- `scripts/lib/assembly.py` — a small refactor: extract the shared concat-demuxer
  step so the draft and the final assembler both reuse it.

No standalone judgment SKILL — the draft is mechanical (concat + labels + music,
all read from the EDL). The judgment ("does this draft read right?") is the
human's at CP2, conducted by `using-montage`.

## 2. The driver — `scripts/draft.py`

```python
def build_draft(edl_path: str, project_path: str, footage_root: str,
                work_dir: str, out: str, *, music: str | None = None,
                font: str | None = None) -> dict:
    """Render a QA-preview draft.mp4 from an EDL.json + project.json. Concats the
    extracted raw segments — scale-fit into the SPEC canvas, labelled with each
    episode's processing_notes, over a rough music bed — for the CP2 human review
    before the expensive process-episode pass. Returns {"status": "written", ...}."""
```

Steps (mirrors `edl_to_reel` for the read/extract half):

1. `edl = EDL.from_json(edl_path)`; `cfg = ProjectConfig.from_json(project_path)`;
   `dims = cfg.canvas`.
2. `extract.extract_edl(edl, footage_root, seg_dir)` — the canonical frame-accurate
   cut (`seg_dir = <work_dir>/segments`). The draft may run as an early preview
   when no segments exist yet, so it extracts them itself; re-running a later
   `edl_to_reel` re-cuts (a few seconds for short windows — no segment cache in v1,
   same as `edl_to_reel`).
3. `fps = assembly.probe_stream(seg0).fps` — probe the first segment, normalize the
   rest to it (mirrors `build_reel`, which probes `clips[0]`). The draft target is
   `(cfg.canvas, fps)` — canvas from the project (segments carry source dims/fps,
   not the canvas), fps from the footage.
4. **Per-segment burn** — one ffmpeg per segment, `-an` (segment audio dropped;
   §5.9 — it returns as ducked ambient in §5.12):
   `-vf "scale=W:H:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=W:H:(ow-iw)/2:(oh-ih)/2,fps=F,format=yuv420p,drawtext=fontfile='{font}':textfile='{notes_i}':fontsize=…:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=…:x=…:y=…"`
   (`force_divisible_by=2` keeps the scaled intermediate even — the even-dims
   landmine, design §12; the padded canvas is even by construction anyway.)
   `-c:v libx264 -crf 20 -preset medium`. Every segment re-encodes (label + fit),
   so there is no `-c copy` fast path here (unlike the final assembler).
5. `assembly.concat(burned, master)` — the burned segments are uniform by
   construction (same canvas/fps/pix_fmt), so this is a lossless `-c copy` concat.
6. **Music bed.** `src = music or edl.music`. If set:
   `audio = mix.mix(MusicSpec.from_json(src), tmp_dir, dur=assembly.probe_duration(master))`,
   then mux `ffmpeg -i master -i audio -map 0:v:0 -map 1:a:0 -c:a copy -shortest out`
   (the `deliver` mux pattern — stream-copy preserves mix's −14 LUFS). If unset,
   the silent `master` is the draft (the silent-reel path, unchanged from A.5).
   Reusing `mix.mix` keeps **one source of truth** for laying music; `dur` beyond
   the analyzed window raises `mix`'s own remedy (same contract as the real reel).
7. Return `{"status": "written", "draft": out, "episodes": len(edl.episodes),
   "music": src is not None}`.

**CLI:** `draft build --edl EDL.json --project project.json --footage-root DIR
--work-dir DIR --out draft.mp4 [--music MUSIC.json] [--font PATH]`. Parse →
`build_draft` → print the JSON result → `SystemExit(0)`. `using-montage` passes
`--out <run-dir>/draft.mp4` so the router's `draft.mp4` marker lands in the run dir.

## 3. The contract helpers — `scripts/lib/draft.py`

Pure functions — no ffmpeg, no filesystem writes beyond the caller's temp files —
so they are fast unit tests.

```python
FONT_CANDIDATES: tuple[str, ...] = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",     # macOS
    "/System/Library/Fonts/Helvetica.ttc",              # macOS
    "/Library/Fonts/Arial.ttf",                         # macOS (older)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Debian/Ubuntu
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",           # Fedora/Arch
)

def resolve_font(override: str | None = None) -> str:
    """First existing font path. `override` wins (validated to exist). None found →
    ValueError naming the candidates + the --font remedy. Landmine (design §5.9,
    §12): drawtext needs an explicit fontfile= — macOS has no fontconfig default."""

def label_text(idx: int, shot_type: str, processing_notes: str) -> str:
    """The burnt caption: '#{idx} {shot_type}', plus a second line with
    processing_notes when non-empty. Written to a textfile so drawtext's textfile=
    dodges filtergraph escaping of ':' / apostrophes in free-text notes."""

def segment_filter(dims: tuple[int, int], fps: float, font: str, textfile: str) -> str:
    """The -vf string: scale-fit + letterbox pad into `dims`, fps normalize,
    yuv420p, then the drawtext label (box for legibility, bottom-left)."""
```

**Why `textfile=` not `text=`:** `processing_notes` is free author text — a `:` or
`'` inside a `text=` value mis-tokenizes the filtergraph (a silent-mangle or an
opaque ffmpeg error). Writing the caption to a temp file and pointing `textfile=`
at it sidesteps all filtergraph escaping.

## 4. The concat refactor — `scripts/lib/assembly.py`

`assemble()` currently inlines the concat-demuxer step (write `_concat.txt`, run
`ffmpeg -f concat -c copy`). Extract it:

```python
def concat(entries: list[str], out_master: str) -> str:
    """Concat pre-uniform files losslessly (-c copy) via the concat demuxer.
    Writes the list file next to out_master. Shared by assemble() (final reel) and
    the draft driver (already-burned segments)."""
```

`assemble()` keeps its normalize-the-outlier logic, then calls `concat(entries,
out_master)`. Behavior is identical — `test_assembly` stays green; a new direct
`concat()` test pins the extracted unit. `_concat_quote` (the apostrophe-in-path
escape) moves with it.

## 5. Router wiring — `scripts/montage.py`

Add one row to `V1_STAGES`, between `edit-plan` and `deliver`:

```python
Stage("assemble-draft", "draft.mp4", "optional", "draft CLI (optional QA preview)", "edl"),
```

- `kind="optional"` — like `music-and-mood` / `reel-brief`, an optional stage never
  becomes `next` (`next_action` only advances `next` past required stages), so the
  autonomous `project → footage → edit-plan → deliver` sequence is unchanged.
- `checkpoint="edl"` — the draft is CP2's richer artifact (the plan/draft review);
  it shares the `"edl"` checkpoint with `edit-plan`, exactly as `project-init` and
  `reel-brief` share `"spec"`. `next_action` makes no uniqueness assumption, so no
  new checkpoint value is needed.
- `in_out=False` — `draft.mp4` lands in the **run dir** (a working preview beside
  `EDL.json` / `segments/`), not the delivery `out/` dir.

**`tests/lib/test_montage.py`** patches: insert `assemble-draft` into the
order/keys list; add its kind/artifact/checkpoint assertions; add an
absent→`"optional"` / present→`"done"` case (mirror `reel-brief`); confirm `next`
stays `deliver` when `EDL.json` is present and `draft.mp4` is absent.

**`SKILLS/using-montage/SKILL.md`** — offer the draft as an **optional** step after
edit-plan and before `edl_to_reel` (the CP2 preview: "want to see a rough draft
before the full render?"); fold `draft.mp4` into the CP2 note.

**`scripts/assemble.py`** — update its docstring: the promised "draft assembler
sibling" is now `scripts/draft.py`, sharing the `lib/assembly` core.

## 6. Testing

- **`tests/lib/test_draft.py`** (pure, no ffmpeg): `resolve_font` finds a candidate
  / honors a valid override / raises with the `--font` remedy when none exist (and
  when a given override is missing); `label_text` with and without notes (the
  second line appears only when notes are non-empty); `segment_filter` contains
  `scale`, `pad`, `fps`, `drawtext`, `fontfile=`, `textfile=` and the canvas dims.
- **`tests/lib/test_assembly.py`**: a direct `concat()` test (two pre-uniform
  clips → one master, right duration); the existing `assemble()` tests stay green.
- **`tests/lib/test_montage.py`**: the §5 patches.
- **`tests/integration/test_draft.py`** (real-ffmpeg, `@pytest.mark.integration`,
  mirrors `test_front_spine`): a `project.json` (canvas `[1080, 1920]`) + a
  two-episode `EDL.json` carrying `processing_notes` + a sine-tone `MUSIC.json`,
  over the `sample_clip` fixture (1920×1080 source). `build_draft` →
  - `draft.mp4` exists;
  - probed dims **== the canvas `1080×1920`** — the draft's letterbox fit is real
    (process-episode is *not* faked here, unlike `test_front_spine`), so this
    golden additionally proves crop-to-canvas on real bytes;
  - duration ≈ the window sum (2.0s);
  - a music variant muxes an `aac` stream; a `music=None` variant has no audio
    stream.

  Window durations sum to 2.0s so `mix`'s guards hold (`dur ≤ music.duration` and
  `dur ≥ 2·fade`).

## 7. Non-goals (v1)

- **Creative crop / tracking / color** — the draft letterboxes; reframe is
  process-episode (§5.10).
- **Ducked ambient + SFX** — segment audio is dropped from the draft; it returns
  ducked in audio-mix (§5.12).
- **Beat-accurate pacing** — the draft lays the chosen fragment at `start_offset`;
  B4 pacing (§5.6) is separate.
- **Draft as a resume anchor** — it is an optional Stage, not part of the auto
  chain; `next_action` never points `next` at it.
- **Segment cache** — `build_draft` extracts every run (mirrors `edl_to_reel`); a
  shared/skip-if-present cache is a later optimization.
- **Standalone SKILL** — mechanical stage, conducted by `using-montage`.

## 8. Docs to sync (final task)

- `docs/pipeline-map.md` — 5.9 `❌ → ✅` in both tables; tally
  `9 ✅ · 3 ◐ · 3 ❌ → 10 ✅ · 3 ◐ · 2 ❌`; the front-half narrative (SP1b done).
- `docs/build-status.md` — the assemble-draft DONE entry; narrow the Next-action.
- `docs/specs/2026-07-05-montage-skillset-design.md` — a `> Built (2026-07-13)`
  note under §5.9.
- `CLAUDE.md` — registry rows for this design + its plan.
