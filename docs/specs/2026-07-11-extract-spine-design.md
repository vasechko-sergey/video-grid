# Extract spine (Front-half SP1) — design

**Front-half authoring · SP1** of the montage conveyor. Turns a hand-authored
`EDL.json` into a delivered `REEL_v1.mp4` with no hand-supplied segments or
per-episode manifests — closing the loop between "an edit decision list exists"
and the already-built back half (`process_episode` → `build_reel` → `deliver`).

Companion to the montage design spec
([2026-07-05-montage-skillset-design.md](2026-07-05-montage-skillset-design.md))
§5.7–5.9. This spec is the SP1 slice; SP2 (footage-intake), SP3 (reel-brief +
edit-plan authoring), SP4 (trend-scan) are separate sub-projects, each its own
spec → plan → execute.

---

## Scope decisions (locked in brainstorming)

- **EDL source of truth = typed `EDL.json`** (a config-spec, like `ReelManifest`).
  The human-facing `EDL.md` markdown render and the interactive edit-plan
  authoring skill defer to **SP3**. SP1 is purely mechanical: code reads the
  typed contract directly.
- **SP1 drives end-to-end** via a thin **sequential** driver: `EDL.json` →
  extract → `process_episode` per episode → assemble `ReelManifest` →
  `build_reel` → `REEL_v1`. The cap-3 **parallel** router + episode-choice
  curation (montage §5.1) is a later optimization that wraps this driver, not
  part of SP1.
- **assemble-draft (§5.9)** — `draft.mp4` with burnt-in `drawtext` labels and a
  rough music bed — defers to **SP1b**. SP1 verifies shape via the real
  `build_reel`/`deliver` output, not a pre-process draft.
- **`beat_slot` / `processing_notes`** ride in the contract as authoring
  metadata (faithful to montage §5.7) but SP1 does not act on them — pacing
  enforcement is B4, labels are SP1b.

## 1. Goal & data flow

```
EDL.json ─┬─► extract_edl ──► segments/ep{i}_raw.mp4      (extract() core + §5.8 length gate)
          │        │
          │        └─(bridge to_manifest_dict)─► ep{i} picture dict
          │                                            │  (driver resolve_manifest → concrete canvas/delivery)
          │                                            ▼
          │                              process_episode(md_resolved, epdir)
          │                                            │
          │                                            ▼
          │                              out/ep{i}.mp4  +  epdir/route.json
          │
          └─► reel-level {music?, cap?, target_dur?}
                                    │
   [ReelEpisode{manifest:md, clip, route} × N] ──► ReelManifest ──► build_reel ──► out/REEL_v1.mp4
```

One `EDL.json` + one `project.json` in; one delivered, versioned reel out. The
back half is unchanged — SP1 only *feeds* it.

## 2. The `EDL` contract (`scripts/lib/edl.py`)

New module, mirroring `scripts/lib/manifest.py` (config-spec + validation, JSON
round-trip, raise-on-bad-construction with a remedy). Lives in its own module
(not `models.py`) because the EDL is front-half authoring, distinct from the
reel wire-contracts; imports the shared vocab (`COMPOSITIONS`, `GRIDS`,
`MOTIONS`) from `models` and (`LAYOUTS_SUPPORTED`, `DEFAULT_COLOR`) from
`manifest` — `manifest` never imports `edl`, so no cycle.

### 2.1 `EDLEpisode`

```python
@dataclass
class EDLEpisode:
    source: str                 # clip path, resolved against the driver's footage-root
    start: float                # source-relative in-point, seconds
    dur: float                  # window length, seconds
    shot_type: str              # authoring tag (montage §5.7 gate); rides to SP3, not acted on
    composition: str            # ∈ COMPOSITIONS
    grid: str                   # ∈ GRIDS
    layout: str = "fill"        # ∈ LAYOUTS_SUPPORTED
    crop_aspect: str | tuple[int, int] | None = None  # None → manifest auto-picks canvas/source by layout
    crop_scale: float = 1.0
    rect: tuple[float, float, float] | None = None
    background: str = "blur"
    border_px: int = 0
    border_color: str = "white"
    motion: str | None = None   # ∈ MOTIONS or None
    hero: tuple | str | None = None
    color_means: tuple = DEFAULT_COLOR
    processing_notes: str = ""   # authoring metadata; rides to SP1b draft labels
    beat_slot: int | None = None # authoring metadata; rides to B4 pacing
```

`__post_init__` raises `ValueError`-with-remedy on: empty/non-str `source`;
`start < 0`; `dur <= 0`; empty/non-str `shot_type`; `composition ∉ COMPOSITIONS`;
`grid ∉ GRIDS`; `layout ∉ LAYOUTS_SUPPORTED`; `motion` not in `MOTIONS ∪ {None}`;
`beat_slot` a non-int (and not `None`). JSON arrays coerce to tuples for
`crop_aspect`/`rect`/`hero`/`color_means` (JSON has no tuples), matching
`manifest.from_dict`.

**Layout-parameter cross-validation** (crop_scale range, rect bounds,
fill-forbids-border, list-vs-tuple) is **not** duplicated here — it has one
source, `LayoutSpec`, exercised downstream by `manifest.validate` (§4 preflight).
`EDLEpisode` validates only the fields the manifest gate cannot see cheaply
(source/window/shot_type) plus the flat membership checks.

### 2.2 `EDL`

```python
@dataclass
class EDL:
    episodes: tuple[EDLEpisode, ...]
    music: str | None = None       # MUSIC.json path; None → silent reel (Phase A.5 path)
    cap: int = 3                   # build_reel reprocess cap
    target_dur: float | None = None  # reel total; None → Σ episode dur
```

`__post_init__`: episodes non-empty (raise "an EDL needs at least one episode");
each a coerced `EDLEpisode`; `cap` an int ≥ 1; `music` a non-empty str or None;
`target_dur` a positive number or None. `from_dict` / `from_json` (raw values
through `EDLEpisode`/`EDL` so `__post_init__` is the single coercion+validation
site, per house convention).

### 2.3 Bridge — `to_manifest_dict(ep, segment, out_path) -> dict`

A deliberate field **map** (not a dump — the manifest gate rejects unknown
keys), producing a `Manifest`-shaped dict:

| manifest key | source | note |
|---|---|---|
| `segment` | `segment` arg | the extracted `ep{i}_raw.mp4` |
| `out_path` | `out_path` arg | `out/ep{i}.mp4` (the locked clip) |
| `target_dur` | `ep.dur` | window length |
| `composition`,`grid`,`layout`,`crop_aspect`,`crop_scale`,`rect`,`background`,`border_px`,`border_color`,`motion`,`hero`,`color_means` | same-named `ep` field | picture params copied straight |
| `canvas`, `delivery` | **omitted** | the **driver** fills them from `project.json` via `resolve_manifest` (§4 step 2), then stores the *resolved* dict |
| `model`, `stabilize` | **omitted** | manifest defaults (`yolo11n-seg`, `False`) |

EDL-only fields (`source`, `start`, `dur`, `shot_type`, `processing_notes`,
`beat_slot`) are **not** forwarded — the map is the documented EDL↔manifest
boundary.

The bridge stays picture-only; **canvas/delivery resolution happens in the
driver**, not here — because the resolved dict is what gets stored in
`ReelEpisode.manifest`, and `build_reel`'s reprocess re-runs `process_episode`
on it **without** `project=` (so a canvas-less dict would raise there).

## 3. Extract loop + gate (`scripts/extract.py`)

Keep the existing single-window `extract(src, start, dur, out, crf=18)` core
untouched (output-seek `-ss` after `-i`, re-encode, audio preserved — §5.8, §12).
Add the EDL driver:

```python
def extract_edl(edl: EDL, footage_root: str, seg_dir: str) -> list[str]:
    """Cut every EDL window into segments/ep{i}_raw.mp4. Returns segment paths in
    reel order. Gate (§5.8): each segment's probed duration matches its window."""
```

For each `idx, ep`: resolve `src = footage_root / ep.source`, `out = seg_dir /
f"ep{idx}_raw.mp4"`, call `extract(src, ep.start, ep.dur, out)`, then **gate** —
probe the segment (`assembly.probe_stream`) and assert
`abs(probed_dur - ep.dur) <= 1/fps + EPS`; on drift raise `ValueError` naming the
episode, the window, and the measured length (a re-encode that lands short =
the silent-truncation class, §12). Missing source file raises with the resolved
path. Returns the segment list.

## 4. Driver (`scripts/edl_to_reel.py`)

The thin **sequential** loop-1 fan-out + hand-off to loop-2. Name open (parallel
to `build_reel.py`).

```python
def edl_to_reel(edl_path, project_path, footage_root, work_dir, out_dir,
                music: str | None = None) -> dict:
```

1. Load `edl = EDL.from_json(edl_path)`, `cfg = ProjectConfig.from_json(project_path)`.
2. **Bridge + resolve + preflight** (fail in ms, before any ffmpeg — mirrors the
   layouts plan). Segment paths are deterministic (`seg_dir/ep{i}_raw.mp4`), so
   the bridge runs *before* extract. For each episode `i`:
   `md = to_manifest_dict(ep, seg_dir/f"ep{i}_raw.mp4", out_dir/f"ep{i}.mp4")`;
   `md = resolve_manifest(md, cfg)` (**dict first**, per its signature — injects
   canvas/delivery from the project); `Manifest.from_dict(md)` + `validate`. Any
   problem → return `{"status": "stop_and_report", "finding":
   {"reason": "edl-invalid", "episode_idx": i, "problems": [...]}}` — nothing
   extracted. Keep the **resolved** `md` per episode.
3. `segments = extract.extract_edl(edl, footage_root, seg_dir)` — paths match the
   `seg_dir/ep{i}_raw.mp4` the bridge already used.
4. Per episode: `epdir = work_dir/f"ep{i}"`;
   `res = process_episode.process_episode(md[i], epdir)` — **no `project=`**, the
   manifest is already resolved. If `res["status"] != "mechanical_pass"` → return
   `{"status": "stop_and_report", "finding": {"reason": "episode-failed",
   "episode_idx": i, "sub_status": res["status"]}, "sub": res}` — no reel from a
   broken episode (mirrors `build_reel`). Else collect
   `ReelEpisode(manifest=md[i], clip=res["clip"], route=str(epdir/"route.json"))`.
   `md[i]` carries a **concrete** canvas/delivery — load-bearing, because
   `build_reel`'s reprocess re-runs `process_episode` on it without `project=`.
5. `rm = ReelManifest(episodes=[...], target_dur=edl.target_dur or sum(ep.dur for ep in edl.episodes),
   cap=edl.cap, changelog=str(out_dir/"VERSIONS.md"), music=music or edl.music)`.
6. `return build_reel.build_reel(rm, out_dir, str(work_dir/"reel"))` — `delivered`
   (with `output`, `report`) or a `build_reel` `stop_and_report` passed through.

CLI: `edl_to_reel EDL.json --project project.json --footage-root DIR --work-dir
DIR --out-dir DIR [--music MUSIC.json]`; prints the result JSON; exits 0 on
`delivered`, 1 otherwise (like `build_reel`). `route = epdir/route.json` is the
deterministic path `process_episode` writes when `route_path is None`.

## 5. Testing

- **`tests/lib/test_edl.py`** — `EDL`/`EDLEpisode` whole-object construction +
  one raising test per validation branch (bad source/start/dur/shot_type/
  composition/grid/layout/motion/beat_slot, empty episodes, bad cap/music/
  target_dur). Bridge: `to_manifest_dict` output, once merged with a project
  canvas, passes `Manifest.from_dict` + `validate` clean (round-trip proof) and
  carries **no** EDL-only keys (unknown-key rejection would else fire).
- **`tests/lib/test_extract.py`** — `extract_edl` gate: a stubbed short segment
  trips the length gate with a remedy; a missing source raises naming the path.
  (Loop wiring over a fake `extract`/probe; no ffmpeg.)
- **`tests/integration/test_front_spine.py`** — real-ffmpeg golden: one
  synthesized source clip (moving box + tone, like `test_reel_backhalf`) → a
  hand-written `EDL.json` of 2 windows + a `project.json` → `edl_to_reel` →
  assert `status == "delivered"`, `out/REEL_v1.mp4` exists, ffprobe confirms the
  video stream and (with `--music`) an `aac` audio stream. Proves the conveyor
  runs end-to-end from a hand-authored EDL.

## 6. Landmines (montage §12)

- **Seek order** — `extract()`'s `-ss` **after** `-i` (frame-accurate) must not
  regress; the loop adds no new seek.
- **Segment audio** — segments stay `aac` (the §5.12 ambient bed); the bridge/
  extract never strip it.
- **Length gate** — re-encoded windows can land ±1 frame; tolerance is
  `1/fps + EPS`, not zero, else a valid cut false-fails.
- **Dims** — `extract` does not scale; segments keep (even) source dims, so no
  odd-dimension libx264 failure is introduced. Canvas even-dims stay
  `process_episode`/`reframe`'s job.
- **Length vs target** — reel `target_dur` defaults to Σ window durs, so the
  `check_reel` length gate passes by construction; a user-set `target_dur` that
  disagrees fires the length check → `build_reel` escalates (length → pacing,
  not auto-fixable) → `stop_and_report`. Correct, not a bug.

## 7. Non-goals (SP1)

- `EDL.md` markdown render + interactive edit-plan authoring → **SP3**
  (built 2026-07-12, docs/specs/2026-07-12-edit-plan-spine-design.md).
- `draft.mp4` (labels + rough music bed) + its beats/plays gate → **SP1b**.
- cap-3 **parallel** fan-out + episode-choice curation → **router, montage §5.1**.
- footage-intake window discovery / `cast.json` → **SP2**.
- `beat_slot` pacing enforcement → **B4**; `processing_notes` labels → **SP1b**.
- No resumability / EDL-run state persistence (same posture as `build_reel`).

## 8. Reused as-is (no change)

`extract.extract()`, `process_episode` (deterministic `project_dir/route.json`),
`resolve_manifest(episode_dict, config)` (dict first), `build_reel`,
`ReelManifest` / `ReelEpisode` / `ReelCheckSpec`, `assembly.probe_stream`,
`ProjectConfig`. SP1 adds exactly one new module (`lib/edl.py`), one new driver
(`edl_to_reel.py`), and one function on `extract.py` (`extract_edl`).
