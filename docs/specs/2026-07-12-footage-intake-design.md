# Footage-intake (5.2) Design

Stage **5.2** of the montage conveyor (design spec
[§5.2](2026-07-05-montage-skillset-design.md)). Turns a folder of raw clips into
a machine contract of **scored candidate moment-windows** plus an interactive
**hero registry**, so the rest of the front half (5.7 edit-plan, 5.3 reel-brief)
has something typed to select from instead of raw footage.

**Produces:** `FOOTAGE.json` (typed) + `FOOTAGE.md` (rendered) + `cast.json`.
**Consumed by:** 5.7 edit-plan (window selection → `EDL`), 5.3 reel-brief
(`SPEC.cast` ← `cast.json`), and later hero-pin resolution (§6.1a).

---

## Scope decisions (locked)

1. **Whole 5.2 in one spec** — the mechanical scan *and* the interactive cast
   pass, one branch, one merge. Not split scan/cast.
2. **FOOTAGE is typed JSON *and* rendered Markdown** — `intake.py` emits both:
   `FOOTAGE.json` is the machine truth (mirrors `EDL.json`/`MusicSpec`), and
   `FOOTAGE.md` is a human/LLM-readable render the edit-plan author can skim.
3. **Shake = `vidstabdetect` magnitude** (spec §5.2 verbatim). Consequence:
   intake becomes the **first runtime consumer of libvidstab** in the repo — so
   it carries a hard preflight (`_require_vidstab`) with the `setup.sh
   --with-vidstab` remedy, and its real-ffmpeg tests **skip when vidstab is
   absent**. Everywhere else vidstab stays optional (manifest still soft-refuses
   `stabilize`).

**Intake ranks and flags; it never finalizes the reel.** Final episode
selection and order are 5.7 edit-plan + the §4.1 episode-choice human loop — out
of scope here (see §8).

---

## §1 Data flow

```
footage_root/*.{MP4,mov,...}
  │
  ▼  intake.py  — mechanical CV, once per clip
  ├─ probe            assembly.probe_stream (w/h/fps) + extract._probe_dur (dur)
  ├─ scene bounds     PySceneDetect ContentDetector → scene_cuts[]
  ├─ people/tracks    ONE YOLO11-seg + ByteTrack pass @~SAMPLE_FPS →
  │                     people-timeline (count + primary bbox per sample)
  │                     + per-track best crops & seg-masks (for cast)
  ├─ shake            vidstabdetect once per clip → per-frame transforms,
  │                     aggregated per window (magnitude)
  ├─ carve_windows    scene_cuts ∪ presence-transitions, length-capped
  │                     into the episode band [WIN_MIN, WIN_MAX]
  └─ score_window     present · motion-fit · stability · dur-fit → 0..1
  │
  ▼  cull across ALL clips
  rank by score → dedup near-dupes by phash (image, not filename) → mark best
  │
  ├──► FOOTAGE.json         Footage.to_dict()
  └──► FOOTAGE.md           Footage.to_markdown()

  ▼  cast pass — SKILL (interactive)
  surface_crops (top-N distinct tracks) → HUMAN names heroes →
  build_descriptor (color hist over seg-mask pixels, 1–3 ref crops) → cast.json
```

Every clip is logged even with zero people (windows scored on motion/stability
only) — scenery is not dropped.

---

## §2 Contracts — `scripts/lib/footage.py`

Config-specs in the house style: dataclasses that **validate and raise in
`__post_init__`** (hard, like `models.py`'s `TrackSpec`/`MusicSpec`, *not* the
soft manifest gate), with `from_dict`/`from_json` round-trip. A `TypeError` from
an unknown key or wrong arity is caught and re-raised as a `ValueError` naming
the offending index (mirrors `EDL.from_dict`). They are **mutable** (not
`frozen`) on purpose: `cull` sets `FootageWindow.best` after construction (`best`
is a plain bool — no revalidation needed).

### `FootageWindow`
One scored moment. **Projects onto an `EDLEpisode`** — it carries exactly the
fields the edit-plan needs to promote a window to an episode
(`source`+`start`+`dur`+`shot_type`+`description`); composition/grid/motion/
layout are *editorial* decisions 5.7 adds later, deliberately absent here.

| field | type | rule |
|-------|------|------|
| `start` | `float` | `≥ 0` |
| `dur` | `float` | `> 0` |
| `shot_type` | `str` | non-empty (`"close"`/`"medium"`/`"wide"`) |
| `people` | `int` | `≥ 0` |
| `motion` | `float` | `∈ [0, 1]` (normalized subject motion) |
| `shake` | `float` | `≥ 0` (vidstab magnitude; higher = shakier) |
| `description` | `str` | may be empty |
| `score` | `float` | `∈ [0, 1]` |
| `best` | `bool` | set by `cull` |

`source` is **not** on the window — it lives on the parent `FootageClip`; the
render and any window→episode projection read it from there.

### `FootageClip`
| field | type | rule |
|-------|------|------|
| `source` | `str` | non-empty (path relative to `footage_root`) |
| `dur` | `float` | `> 0` |
| `res` | `tuple[int, int]` | both `> 0` |
| `fps` | `float` | `> 0` |
| `shaky` | `bool` | clip-level flag: median window shake `> SHAKY_CLIP` |
| `scene_cuts` | `list[float]` | sorted timestamps |
| `windows` | `list[FootageWindow]` | may be empty (clip logged regardless) |

`from_dict` wraps each `windows[i]` in `FootageWindow(**w)`, re-raising a
`TypeError` as `ValueError` naming `windows[i]`.

### `Footage`
- `clips: list[FootageClip]`
- `from_dict` / `from_json` (corrupt JSON → `ValueError` with a fix-the-syntax
  remedy, mirroring `EDL.from_json`), `to_dict`.
- `to_markdown() -> str` — renders `FOOTAGE.md`:
  ```
  # Footage — N clips, M windows (K best)

  ## <source>  (<dur>s · <w>×<h> @<fps>[ · shaky])
  scene cuts: t1, t2, …
  | # | start | dur | shot | people | motion | shake | score | best | description |
  |---|-------|-----|------|--------|--------|-------|-------|:----:|-------------|
  | 0 | 9.08  | 1.6 | med  | 1      | 0.42   | 0.11  | 0.78  |  ★   | 1 person, medium, dynamic |
  ```
  The leading `#` is the 0-based position in that clip's `windows` list — the
  index the 5.7 `selection.json` references and `build_edl` indexes into.
- `ranked_windows() -> list[tuple[FootageClip, FootageWindow]]` — all windows,
  score-descending; the helper cull and the render share.

### `CastMember` / `Cast`
`CastMember`: `name: str` (non-empty), `descriptor: list[float]` (non-empty,
the normalized color histogram — a fixed bin count, see §4), `notes: str = ""`,
`ref_crops: list[str] = []` (paths to saved reference-crop PNGs). `Cast`:
`members: list[CastMember]`, `from_dict`/`from_json`/`to_dict` → `cast.json`.

> Kept in `footage.py` with the footage contracts for now. When hero-pin
> resolution wires descriptors into manifests (a later plan, see §8), `Cast`
> can move to its own `cast.py` — the consumers diverge there.

---

## §3 `scripts/intake.py` — the mechanical CV driver

Module-level tunable constants (named, not magic): `SAMPLE_FPS = 3`,
`WIN_MIN = 1.2`, `WIN_MAX = 4.0`, `WIN_TARGET = 2.5` (seconds); scoring weights
`W_PRESENT = 0.40`, `W_MOTION = 0.25`, `W_STABLE = 0.25`, `W_DUR = 0.10`;
`DEDUP_DIST = 8` (phash Hamming), `BEST_FLOOR = 0.50`, `SHAKY_CLIP = 0.02`
(shake as a **fraction of frame width** — see §3.4; tune on real footage),
`MOTION_GAIN = 10.0`, `MOTION_PEAK = 0.35`; shot-type area thresholds
`CLOSE_AREA = 0.30`, `MEDIUM_AREA = 0.08`.

### §3.1 Probe
Reuse `assembly.probe_stream(path)` for `(w, h, fps)`. Duration needs
`format=duration`, which `StreamInfo` lacks — **promote** `extract._probe_dur`
to a public `assembly.probe_duration(path)` (its natural home; `assembly`
already owns ffprobe glue), and have `extract.py` import it from there. One
duration probe, shared by extract and intake; no new copy.

### §3.2 Scene bounds — `scene_bounds(path) -> list[float]`
PySceneDetect `ContentDetector` (default threshold) → boundary timestamps. One
continuous take returns `[]` (no cuts) — that is expected and handled by carving.

### §3.3 People / tracks / masks — one YOLO-seg pass
`_iter_seg(path)` mirrors `track.py`'s ultralytics config
(`MODEL = "yolo11n-seg.pt"`, `classes=[0]`, `tracker="bytetrack.yaml"`,
`imgsz=960`, `stream=True`, `persist=True`) but **yields masks too**
(`res.masks`), which `track._iter_detections` deliberately omits for speed.
`track.py` stays untouched (its goldens stay green); the small duplication is the
price of not perturbing the tracker. Sampling: step frames to ≈`SAMPLE_FPS` (a
scan, not per-frame). Per sample record `(t, people_count, primary_bbox)` where
primary = the **largest person by bbox area** (single, unambiguous criterion —
the same bbox `shot_type` reads); retain per **track id** the highest-confidence
crop + its seg-mask for the cast pass.

### §3.4 Shake — `shake_by_window(path, windows) -> list[float]`
`_require_vidstab()` first: `ffmpeg -hide_banner -filters | grep vidstabdetect`;
absent → raise `ValueError("footage-intake needs a vidstab-enabled ffmpeg — run
bash setup.sh --with-vidstab")`. Then run `vidstabdetect` **once per clip**
(`-vf vidstabdetect=result=<tmp.trf> -f null -`), parse the `.trf` (VID.STAB text
format: per-frame localmotion vectors). Per frame take the **upper-median**
localmotion magnitude `sqrt(vx²+vy²)` (`vecs[len//2]` — slightly conservative);
per window, **average** those magnitudes over the window's frame span and
**normalize by frame width** so `shake` is a width-fraction comparable across
resolutions (hence `SHAKY_CLIP = 0.02`, not a raw-pixel bar). The parser is
**version-guarded**: an empty `.trf` and an unrecognized header each raise a
distinct fail-loud `ValueError` (never a silent `shake = 0`). The golden pins the
format against the installed libvidstab. No per-window cutting → no `-ss` seek
landmine here.

### §3.5 Carve — `carve_windows(scene_cuts, timeline, dur) -> list[(start, dur)]`
Scenes alone do **not** split a long single take (grounding: MVI_3739 = one 22s
ride → `lena_ride` + `lena_ride2` + `lena_nose`). Algorithm:
1. Boundaries = `scene_cuts` ∪ **presence-transitions** (people count crosses
   `0 ↔ >0` in the timeline), plus `0` and `dur`.
2. Each resulting span is an *activity segment*.
3. Length-cap: a span longer than `WIN_MAX` is divided into equal chunks nearest
   `WIN_TARGET`; a span shorter than `WIN_MIN` is dropped **unless** it is the
   clip's only span (a very short clip still yields one window).
4. Each surviving span → one candidate window. People=0 spans are kept (scenery),
   scored on motion/stability alone.

### §3.6 Score — `score_window(window, timeline, shake) -> float`
Blend, clamped `[0, 1]`:
- `present` = fraction of the window with a confident, roughly-centered person
  (`0` if none). `W_PRESENT`.
- `motion_fit` = triangular peak on subject displacement — `0` static, `1` at
  moderate, decaying when chaotic. `W_MOTION`.
- `stability` = `1 − min(1, shake / SHAKY_CLIP)`. `W_STABLE`.
- `dur_fit` = `1` at `WIN_TARGET`, falling toward `WIN_MIN`/`WIN_MAX`. `W_DUR`.
`description` is auto-generated (`"1 person, medium, dynamic"`).

### §3.7 shot_type — `shot_type(primary_bbox, res) -> str`
`area = bbox_w·bbox_h / (w·h)`: `> CLOSE_AREA` → `"close"`, `≥ MEDIUM_AREA` →
`"medium"`, else `"wide"`; no person → `"wide"` (scenery). Free string, matches
`EDLEpisode.shot_type`.

### §3.8 Cull — `cull(clips) -> None` (mutates `best`)
Flatten `ranked_windows()`; walk score-descending; drop a window whose phash
(imagehash `phash` at the window midpoint frame) Hamming distance `< DEDUP_DIST`
to an already-kept higher-scored window — **compare by image, never by filename**
(spec §variety: several windows of one clip are fine if visually distinct). Mark
`best = True` on dedup survivors with `score ≥ BEST_FLOOR`.

### §3.9 Driver + CLI
`intake(footage_root, out_dir) -> Footage` loops the clips, builds `Footage`,
culls, writes `FOOTAGE.json` + `FOOTAGE.md`. CLI:
`python -m scripts.intake <footage_root> <out_dir> [--sample-fps N]`.

---

## §4 Cast pass

Mechanical helpers in `intake.py`; the **naming is interactive** and lives in the
SKILL (§5), never in the Python — the Python cannot ask a human. The crops come
from `intake()`'s **single** YOLO-seg pass (no second pass): `intake()`
accumulates each clip's retained crops keyed `(source, track_id)` — ByteTrack ids
restart at 1 per clip, so the raw id alone would collide across clips.
- `build_descriptor(crop, mask) -> list[float]` — a color histogram over the
  **segmentation-mask pixels only** (background removed — §6.1a: HSV failed as a
  *tracker* but is the right *identity descriptor* over a mask). Fixed bins
  (3 channels × 8 = 24), L1-normalized. numpy + Pillow, **no cv2**.
- `surface_crops(crops_by_track, top_n) -> list` — cluster the accumulated crops
  by descriptor L1 distance (`> CAST_DEDUP` = distinct) across *all* footage,
  highest-confidence first, returning the `top_n` distinct identities as
  `(key, conf, crop_rgb, mask, descriptor)`.
- `save_cast_candidates(crops_by_track, out_dir, top_n) -> list[dict]` — the
  reachability bridge: runs `surface_crops`, **saves** each candidate's crop PNG
  under `out_dir/cast_crops/candidate_{i}.png`, and writes
  `cast_candidates.json` (`id, source, conf, crop, descriptor`). `intake()` calls
  it, so the SKILL reads candidates off disk (crops to show + descriptors already
  computed) instead of re-running YOLO.
- `write_cast(named, out_dir) -> Cast` — `named` is
  `[(name, notes, descriptor, ref_crops)]`: the SKILL maps the human's names onto
  the candidates' **persisted** descriptors (no array marshalling across the
  `intake()` boundary), and this writes `cast.json`.

---

## §5 `SKILLS/footage-intake/SKILL.md`

The subagent that owns the human-in-the-loop, mirroring `process-episode`'s
discipline (ask-before-proceeding, stop-and-report, never improvise):
1. Ensure env (`setup.sh --with-vidstab` if vidstab missing).
2. Run `intake.py` → `FOOTAGE.json`/`FOOTAGE.md`.
3. If people matter to the reel: `surface_crops` → **show crops, ask the human
   to name the heroes** (any domain — family, athletes, friends). Skip cleanly
   when the footage has no people or the reel is scenery.
4. `write_cast` → `cast.json`.
5. Report the **gate**: every clip logged, people tagged, windows carved +
   scored, cast named (when applicable).

---

## §6 Testing

- **Unit** (`tests/lib/test_footage.py`): every contract's raise-on-bad rows +
  round-trip + `to_markdown` whole-string; `Cast` round-trip.
- **Unit** (`tests/lib/test_intake.py`): `carve_windows` (the long-take →
  multiple windows case, the presence-transition case, the short-clip fallback),
  `score_window` (each factor moves the score the right way), `shot_type`
  buckets, `cull` dedup (two visually-identical windows → one survives; two
  distinct windows of one source → both survive), `build_descriptor`
  normalization — all with **mocked YOLO** (a synthetic person-timeline; YOLO
  returns empty on synthetic footage — design §12).
- **Integration golden** (`tests/integration/test_intake.py`): the synthetic
  `sample_clip` fixture (real ffmpeg bytes — a box on a field) with `_iter_seg`
  **monkeypatched** to a synthetic person-timeline, but **real** PySceneDetect
  and **real** vidstabdetect. Asserts the clip is logged with `≥ 1` window, a
  sane `shot_type`, a measured `shake ≥ 0`, `FOOTAGE.json`/`FOOTAGE.md` written,
  and `to_markdown` renders. **Skips when vidstab is absent**
  (`@pytest.mark.integration` + `_require_vidstab` guard).

  Why faked `_iter_seg`: YOLO returns an empty route on synthetic footage (a box
  is not a person — design §12, same reason `test_front_spine` fakes
  `process_episode`), so real YOLO here would prove nothing. Real YOLO exercises
  only when a human points intake at real footage (`footage_root` = the external
  fixture folder) — a manual validation, not an automated milestone (mirrors the
  core engine's MVI_3739 golden, which is not in the CI suite either).

**What the golden proves:** the CV *wiring* on real bytes (probe → scenes →
vidstabdetect + `.trf` parse → carve → score → cull → contract → render).
**What it does not:** tuned scoring/carving quality (judgment the human/edit-plan
applies downstream) or YOLO detection on real people — the unit tests pin each
factor's *mechanics* against a mocked timeline.

---

## §7 Landmines / consequences

- **vidstab is now a hard intake dependency** — `_require_vidstab` fails loud
  with the tap-install remedy; integration tests skip without it; the SKILL's
  setup step brings it up. This is the repo's first real vidstab consumer.
- **`.trf` parsing is version-fragile** — guard the header, raise on an
  unrecognized format (never a silent `shake = 0`); the golden pins it.
- **YOLO returns empty on synthetic footage** (§12) — unit tests *and* the
  integration golden mock the seg-timeline; only a manual real-footage run
  exercises real YOLO.
- **Sub-scene carving is the real work** — scene cuts ≠ moment windows; a long
  take with no cuts must still split.
- **Dedup by image, not filename** — several windows of one clip are legitimate.
- **`FootageWindow → EDLEpisode` projection** keeps 5.7 a mechanical mapping.

---

## §8 Non-goals (explicit)

- **Final episode selection + order** — 5.7 edit-plan + §4.1 episode-choice loop.
- **Mood-match / autonomous music** — 5.5 B3.
- **Descriptor → manifest hero-pin wiring** — landed 2026-07-16 as its own
  plan, cast → hero-pin (`orch.is_seed_pin` deleted there, not merely
  extended); 5.2's own scope stayed just *producing* `cast.json`.
- **Trend-scan** — 5.4.
- **Vocal-aware in-points / demucs** — §5.8 optional upgrade.
- **Sharpness/blur metric** — deferred (would add cv2); shake covers stability
  for v1.

---

## §9 Reused (existing code leveraged)

- `assembly.probe_stream` (w/h/fps); `assembly.probe_duration` (duration —
  promoted from `extract._probe_dur`, built SP1, now shared).
- `track.py` ultralytics config (`MODEL`, `imgsz=960`, `classes=[0]`, bytetrack)
  — mirrored in `_iter_seg` (adds masks); `track.py` untouched.
- `imagehash.phash` for dedup (as `check_reel`'s variety check uses).
- `proc.run` for ffprobe/ffmpeg.
- Config-spec conventions from `models.py` / `edl.py` (raise-on-bad, `from_dict`
  TypeError→ValueError, `from_json` corrupt→ValueError).
