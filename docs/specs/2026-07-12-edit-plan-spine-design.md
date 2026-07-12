# Edit-plan spine (Front-half SP3) — design

**Front-half authoring · SP3** of the montage conveyor, stage **5.7 edit-plan**.
Turns the scored candidate windows of `FOOTAGE.json` (5.2) into a typed
`EDL.json` + a human-facing `EDL.md` map — the edit decision list the already-built
extract spine (`edl_to_reel`, SP1) drives to a delivered reel. This is the
critical-path head to autonomous v1: 5.2 → **5.7** → 5.1 router.

Companion to the montage design spec
([2026-07-05-montage-skillset-design.md](2026-07-05-montage-skillset-design.md))
§5.7. Sibling of the extract-spine spec
([2026-07-11-extract-spine-design.md](2026-07-11-extract-spine-design.md)), which
built the EDL contract + bridge + driver and **deferred the markdown render and
interactive authoring to this slice**. The full reel-brief (`SPEC.md`, §5.3),
pacing (`PACING.md`, §5.6), and the cast→hero-pin descriptor wiring are separate
sub-projects, each its own spec → plan → execute.

---

## Scope decisions (locked in brainstorming)

- **Selection lives in the agent's judgment, not in Python.** 5.2 already scored,
  culled, and `best`-marked the windows; what remains — *which* best moments, in
  *what order*, with *what* layout/composition/grid/motion — is editorial. Code
  stays thin: a `FootageWindow → EDLEpisode` projection, the `EDL.md` render, and
  the preflight gate. No Python window-scorer (that would duplicate 5.2 and bake
  editorial taste into code). Faithful to montage §5.7's "edit-plan = writing-plans".
- **Authoring mechanic = `selection.json` → projection.** The agent writes a
  compact `selection.json` — window references (`source` + integer index into
  `FOOTAGE.json`) plus the editorial fields per episode — and `edit_plan.py`
  **projects** each reference through `window_to_episode`, copying the mechanical
  fields (`source`/`start`/`dur`/`shot_type`/`description`) straight from
  `FOOTAGE.json` **by reference**. The agent never retypes a float timestamp — a
  retyped `start`/`dur` is the silent-wrong-cut class (montage §12); validation
  catches a malformed value, not a valid-but-wrong one. `selection.json` carries
  only integer indices and editorial enums/notes.
- **SKILL posture = autonomous draft + review** (writing-plans style, not a
  per-episode dialogue). The agent reads `FOOTAGE.md` (+ any soft inputs), authors
  the whole `selection.json` → `EDL.json` + `EDL.md`, and presents `EDL.md` for a
  single review gate; edits round-trip through `selection.json` + a re-render.
  Autonomous authoring is what lets the 5.1 router later drive this headless.
- **Soft inputs are optional.** `SPEC.md` (5.3), `PACING.md` (5.6), `MUSIC.json`
  (5.5) enrich the authoring when present but are **not** build prerequisites. The
  minimum input is `FOOTAGE.json` + `project.json`. With no pacing, `beat_slot`
  stays `None` (montage §5.7's beat-slot gate is relaxed for the no-pacing v1).

## 1. Goal & data flow

```
FOOTAGE.json (5.2: scored / culled / best-marked windows) ─┐
project.json (canvas / target_dur / delivery) ─────────────┤  agent reads
SPEC.md · PACING.md · MUSIC.json  (soft, optional) ────────┘  as guidance
                          │
               edit-plan SKILL  (authoring by judgment)
                          │  writes
                          ▼
                   selection.json   (window refs source+idx + editorial per episode + reel knobs)
                          │
   edit_plan.py build ────┤  load Footage → resolve refs → window_to_episode → EDL → preflight(project)
                          ▼
                    EDL.json  +  EDL.md      (typed contract + human map)
                          │
          (existing SP1)  edl_to_reel ──► REEL_v1.mp4
```

One `FOOTAGE.json` + one `selection.json` + one `project.json` in; one `EDL.json`
+ its `EDL.md` render out — which the unchanged SP1 driver takes to a delivered
reel. SP3 only *produces* the EDL; it never cuts or encodes.

## 2. Contract additions (`scripts/lib/edl.py`)

The `EDL`/`EDLEpisode` config-specs + `to_manifest_dict` bridge exist (SP1). This
slice adds two functions to the same module — the render belongs on the contract
(symmetric with `Footage.to_markdown` on `footage.py`), and the preflight is the
shared EDL↔project validation both the driver and the authoring path need.

### 2.1 `EDL.to_markdown() -> str`

Renders the EDL to the human-facing `EDL.md` **map** (montage §5.7: "which file
holds what and from which timestamp to view — no cutting yet"). Mirrors
`Footage.to_markdown`'s shape:

```
# Edit plan — {N} episodes, {Σ dur:.1f}s[ · target {target_dur:.1f}s]

| # | source | window | shot | layout | comp | grid | motion | beat | notes |
|---|--------|--------|------|--------|------|------|--------|:----:|-------|
| 0 | MVI_3739.mp4 | 2.10–6.10 (4.00s) | close | fill | lead | thirds | lateral:right | – | lena nose |
| 1 | MVI_3998.mp4 | 0.00–2.50 (2.50s) | wide | fit-blur | center | phi | – | – | |
```

Header shows episode count + summed duration; if `target_dur` is set it is
appended (a visible reconciliation — a target that disagrees with Σ dur is a real
pacing signal, faithful to the SP1 length-gate note). `window` column is
`start–end (dur)`; `motion`/`beat`/`notes` render `–`/empty when absent. Pure
string build, no IO — unit-testable on key substrings like `test_footage`'s
`to_markdown` test.

### 2.2 `preflight(edl, cfg, seg_dir, out_dir) -> tuple[list[dict], dict | None]`

Extracted verbatim from `edl_to_reel`'s current step-1 loop (that inline block is
deleted and replaced by a call). For each episode `i`: build the segment/out
placeholder paths (`seg_dir/ep{i}_raw.mp4`, `out_dir/ep{i}.mp4`),
`md = resolve_manifest(to_manifest_dict(ep, seg, out), cfg)`, then
`Manifest.from_dict(md)` + `validate(m)`. Returns `(mds, None)` when every episode
is clean, or `(mds_so_far, stop)` where
`stop = {"status": "stop_and_report", "finding": {"reason": "edl-invalid",
"episode_idx": i, "problems": [...]}}` on the first bad episode. `validate` never
touches the filesystem (it checks layout params/dims, not file existence — this is
what lets it "fail in ms, before any ffmpeg"), so the placeholder paths are
harmless for the authoring path, which discards `mds` and uses only `stop`.

**Consumers:**
- `edl_to_reel` replaces its inline preflight loop with
  `mds, stop = preflight(edl, cfg, seg_dir, out_dir); if stop: return stop` —
  keeps `mds` (the resolved dicts with real paths) for its `process_episode` fan-out.
  Behaviour is identical; its existing tests stay green.
- `edit_plan.write_edit_plan` calls it purely for `stop`.

**Import direction:** `edl.py` adds `from scripts.lib.project import
resolve_manifest` (and `Manifest`/`validate` from `manifest`, already imported).
`project.py` does **not** import `edl` (verified), and neither does `manifest` or
`models` — so `edl → {manifest, models, project}` stays acyclic. The module
docstring's "no cycle" note is extended to cover `project`.

## 3. Authoring logic (`scripts/edit_plan.py`, new)

The 5.7 driver — contract vs. logic split, mirroring `footage.py` (contract) ↔
`intake.py` (logic). Imports `Footage`/`FootageClip`/`FootageWindow` from
`footage`, `EDL`/`EDLEpisode`/`preflight` from `edl`, `ProjectConfig` from `project`.

### 3.1 `window_to_episode(clip, window, **editorial) -> EDLEpisode`

The mechanical projection. Mechanical fields come from the clip/window; editorial
fields are forwarded to `EDLEpisode(**)`:

| `EDLEpisode` field | source | note |
|---|---|---|
| `source` | `clip.source` | the parent clip's path (windows don't carry it) |
| `start`, `dur` | `window.start`, `window.dur` | **by reference** — never retyped |
| `shot_type` | `window.shot_type` | default; an editorial `shot_type` override wins |
| `processing_notes` | `window.description` | default seed; an editorial override wins |
| `composition`, `grid` | **editorial (required)** | ∈ `COMPOSITIONS` / `GRIDS` — no contract default, so the agent must supply them |
| `layout`, `motion`, `hero`, `crop_aspect`, `crop_scale`, `rect`, `background`, `border_px`, `border_color`, `color_means`, `beat_slot` | editorial (optional) | fall through to `EDLEpisode` defaults when omitted |

Implementation: `defaults = {"shot_type": window.shot_type, "processing_notes":
window.description}`; `return EDLEpisode(source=clip.source, start=window.start,
dur=window.dur, **{**defaults, **editorial})`. An unknown editorial key raises
`TypeError` from `EDLEpisode.__init__` → caught and re-raised as a `ValueError`
naming the offending key + episode (same idiom as `EDL.from_dict`). All value
validation (enum membership, ranges) is `EDLEpisode.__post_init__`'s job — not
duplicated here.

### 3.2 `build_edl(footage, selection) -> EDL`

`selection` is the parsed `selection.json` dict. Its shape:

```json
{
  "episodes": [
    {"source": "MVI_3739.mp4", "window": 2, "composition": "lead", "grid": "thirds",
     "layout": "fill", "motion": "lateral:right", "hero": "lena"},
    {"source": "MVI_3998.mp4", "window": 1, "composition": "center", "grid": "phi"}
  ],
  "music": null, "cap": 3, "target_dur": null
}
```

For each `episodes[k]`:
1. Pop `source` (str) and `window` (int). Missing/wrong-typed → `ValueError`
   naming episode `k`.
2. Resolve the clip: `clip = {c.source: c for c in footage.clips}.get(source)`;
   `None` → `ValueError(f"selection episode {k}: source {source!r} not in FOOTAGE
   — have {sorted(sources)}")`. (A typo'd source would otherwise surface as a
   FileNotFound deep in `extract` — montage §12 fail-loud-with-remedy.)
3. Resolve the window: bounds-check `window` against `clip.windows`; OOB →
   `ValueError(f"selection episode {k}: window {window} out of range for {source}
   (has {len(clip.windows)})")`.
4. `ep = window_to_episode(clip, clip.windows[window], **remaining_editorial_kwargs)`.

Reel knobs (`music`, `cap`, `target_dur`) pass from `selection`'s top level to
`EDL(...)` (defaults `None`/`3`/`None` when absent). `EDL.__post_init__` validates
the assembled list (non-empty, knob types). Returns the `EDL`.

### 3.3 `write_edit_plan(footage_path, selection_path, project_path, out_dir) -> dict`

The one-call entry the SKILL/CLI drives:
1. `footage = Footage.from_json(footage_path)`; `selection = json.loads(...)`
   (bad JSON → `ValueError` with the path, like the config-specs);
   `cfg = ProjectConfig.from_json(project_path)`.
2. `edl = build_edl(footage, selection)`.
3. `mds, stop = preflight(edl, cfg, str(Path(out_dir)/"segments"), out_dir)`; if
   `stop` → return it (nothing written — a bad EDL never reaches disk as a
   half-valid artifact).
4. Write `out_dir/EDL.json` (`json.dumps` of the EDL's dict form) and
   `out_dir/EDL.md` (`edl.to_markdown()`).
5. Return `{"status": "written", "edl": ".../EDL.json", "md": ".../EDL.md",
   "episodes": len(edl.episodes)}`.

*(`EDL` needs a `to_dict` for step 4 — it currently has `from_dict`/`from_json`
but no `to_dict`. Add the symmetric `to_dict` (episodes → per-field dicts + knobs)
so `EDL.from_json(write…)` round-trips. This closes an existing asymmetry the
contract needs anyway.)*

### 3.4 CLI

```
edit_plan build --footage FOOTAGE.json --selection selection.json \
                --project project.json --out-dir DIR
```

Prints the result JSON; exits `0` on `written`, `1` on `stop_and_report` (mirrors
`edl_to_reel`). Scripts take explicit args — the SKILL supplies them; the user
never types flags (montage §5.1).

## 4. SKILL (`SKILLS/edit-plan/SKILL.md`, new)

The writing-plans-style authoring subagent (montage §5.7, §14). Autonomous draft +
single review gate:

1. **Context recon** — read `FOOTAGE.md` (the ranked windows) + `project.json`
   (canvas/`target_dur`/delivery) + any `SPEC.md`/`PACING.md`/`MUSIC.json`
   present + `references/editing-canon.md` (thirds/headroom/lead room/180°/
   cut-on-action — the editorial base).
2. **Author `selection.json`** — pick the best windows (already ranked by 5.2),
   dedup across sources so one clip doesn't dominate, fit the running sum to
   `target_dur`, order them (hook first), and assign per episode:
   `composition` (lead/center/break), `grid` (thirds/phi), `layout`, `motion`,
   `hero` (a rule/bbox/cast-name), `processing_notes`. `beat_slot` stays `None`
   without `PACING.md`; `music` is the `MUSIC.json` path when one exists.
3. **Build** — run `edit_plan build …` → `EDL.json` + `EDL.md` (+ preflight).
4. **Review** — present `EDL.md`; on user edits, revise `selection.json` and
   re-run (never hand-edit `EDL.json` — `selection.json` is the source, the EDL
   is generated).
5. **Gate** (montage §5.7) — every episode has source + window + shot-type; a
   preflight `stop_and_report` is surfaced verbatim (episode idx + problems), not
   worked around.

## 5. Testing

- **`tests/lib/test_edl.py`** (extend): `EDL.to_markdown` renders the header
  (count + Σ dur, and `target …` when set) and a per-episode row (source, window
  `start–end (dur)`, comp/grid, `–` for absent motion/beat) — key-substring
  asserts. `EDL.to_dict` round-trips (`EDL.from_dict(edl.to_dict()) == edl`
  field-wise). `preflight` returns `(mds, None)` on a valid EDL+project and
  `(_, stop)` with `reason="edl-invalid"` + the offending idx on a bad-layout
  episode (e.g. `fill` + `border_px>0`, which `LayoutSpec` rejects).
- **`tests/lib/test_edit_plan.py`** (new): `window_to_episode` — mechanical fields
  exact from a `FootageWindow`/`FootageClip`, editorial forwarded, `shot_type`/
  `processing_notes` overridable, unknown key → `ValueError` naming it. `build_edl`
  — resolves by source+index; unknown source raises listing available sources;
  OOB window raises with the count; knobs (`music`/`cap`/`target_dur`) reach the
  `EDL`. `write_edit_plan` — writes both files and they round-trip; a bad episode
  → `stop_and_report` (idx + problems), **no files written**. Fake `Footage`/
  `ProjectConfig` fixtures; no ffmpeg.
- **`tests/integration/test_edit_plan.py`** (new, real-ffmpeg golden): a
  hand-written `FOOTAGE.json` (real shape, two clips) + a `selection.json` + a
  `project.json` → `edit_plan build` → assert `EDL.json` round-trips and `EDL.md`
  renders → **feed the `EDL.json` to the existing `edl_to_reel`** on synthesized
  source clips (moving box + tone, as `test_front_spine`) → assert
  `status == "delivered"` and `REEL_v1.mp4` exists. Proves the SP3→SP1 seam:
  `selection.json` ultimately yields a delivered reel.

## 6. Landmines (montage §12)

- **No float transcription** — `start`/`dur` reach the EDL from `FOOTAGE.json` by
  reference through `window_to_episode`; `selection.json` holds only integer
  window indices + editorial. A retyped timestamp is the silent-wrong-cut class;
  the projection makes it structurally impossible.
- **Preflight before extract** — `write_edit_plan` runs the manifest gate so a bad
  EDL fails in milliseconds and never reaches disk, let alone `edl_to_reel`'s
  ffmpeg. Same posture as the driver's step-1.
- **Source resolution fail-loud** — a `selection` `source` that doesn't match a
  `FootageClip.source` raises with the list of available sources, not a deep
  FileNotFound in `extract`.
- **Generated, not hand-edited** — `EDL.json` is regenerated from `selection.json`
  on every edit; the SKILL never hand-patches the EDL (which would desync the two
  and re-open the transcription risk).

## 7. Non-goals (SP3 / 5.7)

- Full reel-brief `SPEC.md` authoring (§5.3) → its own slice; here `SPEC.md` is a
  soft, optional guidance input.
- `PACING.md` / `beat_slot` binding (§5.6 / Phase B4) → `beat_slot` stays `None`.
- Window **scoring / ranking** → already built in 5.2; 5.7 consumes ranked windows.
- cap-3 **parallel** router + episode-choice curation (§5.1) → wraps this later.
- **Interactive** per-episode dialogue → autonomous draft + single review only.
- **cast → hero-pin** descriptor wiring → separate. `hero` here rides as today
  (a bbox/rule/name string through the existing `EDLEpisode.hero`); *resolving* a
  cast name through `cast.json` descriptors is the deferred hero-pin task.
- No resumability / selection-run state persistence (same posture as `build_reel`
  / `edl_to_reel`).

## 8. Reused as-is (no change)

`Footage`/`FootageClip`/`FootageWindow` + `from_json` (5.2), `EDLEpisode`/`EDL` +
`to_manifest_dict` (SP1), `edl_to_reel`/`extract_edl` (SP1), `ProjectConfig`/
`resolve_manifest`, the `Manifest` gate + `validate`, `references/editing-canon.md`.
SP3 adds two functions to `edl.py` (`EDL.to_markdown`, `preflight`) + one
(`EDL.to_dict`), one new module (`edit_plan.py`), and one new SKILL
(`edit-plan`); it deletes `edl_to_reel`'s inline preflight in favour of the
shared `edl.preflight`.
