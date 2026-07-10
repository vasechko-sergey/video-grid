# Reel Back Half — Design Spec (Phase A)

The back half of the montage conveyor: turn N locked `process-episode` outputs
into one delivered reel. **Silent** in this phase — music (beats, loudness,
audio-mix) is Phase B. This is the first slice that makes a *reel* exist rather
than a pile of per-episode clips.

Maps to montage design §5.9 (assemble), §5.13 (reel-final-check, mechanical
half), §5.14 (deliver), the §9 assembly-plan checks, and the §11 binding
version-log requirement.

## Goal

`[locked out/<ep>.mp4 …] → assemble → work/master.mp4 → check_reel → (pass) →
deliver → out/REEL_v{n}.mp4`. A hard gate between check and deliver: a failed
reel is never delivered. Exactly one encode, at deliver — episodes stay pristine
through assembly.

## Scope split (two adjacent slices, one subsystem)

Decided during brainstorming:

- **Phase A (this plan):** the three stages + typed contracts + failure
  **attribution**. `check_reel` emits machine-readable `fail_reasons[]` (which
  episode, what to escalate to) so the next slice's driver has its substrate.
  `deliver` refuses a failed report.
- **Phase A.5 (immediate follow-on, §6 here):** the retry *loop* —
  `reel_orchestration` (the §4.1 ladder) + `build_reel` driver (assemble →
  check → reprocess culprit via `process_episode` → reassemble → recheck →
  deliver | stop-and-report) + a per-episode `color_target` override in
  `reframe`. Recorded here so its design isn't lost; specified for build when we
  start it.

Two further decisions from brainstorming, both forward-looking (the whole engine
may later be refactored into a service the skills call):

1. **Draft and final assembly are separate entry scripts over one shared
   concat/normalize core.** Phase A builds the *final* assembler (чистовик) and
   the shared core; the *draft* assembler (черновик, montage §5.9 — labelled,
   music-bed, front-half) is a later `scripts/assemble_draft.py` reusing the same
   core.
2. **Deliver takes one typed `ExportProfile`,** not a platform registry and not
   raw args — new platforms become new instances, not new code (mirrors
   `Delivery`/`LayoutSpec`).

## §1 — Architecture & files

Thin entry scripts over `lib/` logic, the established split.

**Phase A:**

```
scripts/lib/assembly.py   NEW   probe uniformity → concat-copy | normalize-outlier+concat; fail loud. Shared by final + (future) draft.
scripts/lib/models.py     EDIT  + ExportProfile, ReelReport, ReelFailure, ReelCheckSpec (typed, raise on bad ctor).
scripts/assemble.py       NEW   final assembler: ordered [out/<ep>.mp4] + canvas + fps → work/master.mp4 via lib.assembly.
scripts/check_reel.py     NEW   whole-reel mechanical gate on the master → ReelReport (with attributed fail_reasons[]).
scripts/deliver.py        NEW   master → out/REEL_v{n}.mp4 per ExportProfile + out/VERSIONS.md; refuses a failed report.
references/ffmpeg-recipes.md  EDIT  + final-concat + deliver-encode recipes.
tests/lib/test_assembly.py    NEW   uniformity/concat logic (mocked proc/ffprobe).
tests/lib/test_models.py      EDIT  ExportProfile/ReelReport/ReelFailure/ReelCheckSpec.
tests/integration/test_reel_backhalf.py  NEW  real-ffmpeg golden: 2 windows → process_episode ×2 → assemble → check_reel → deliver.
```

**Data flow:** `[locked episodes] → assemble → work/master.mp4 → check_reel →
ReelReport → (overall True) → deliver → out/REEL_v{n}.mp4 + out/VERSIONS.md`.

## §2 — Data contracts (`models.py`)

All raise `ValueError` with a remedy on bad construction, matching
`Delivery`/`LayoutSpec`/`CheckSpec`.

```
ExportProfile                         # the one profile; new platforms = new instance
  vcodec: str = "libx264"
  crf: int = 18                       # primary quality lever
  preset: str = "medium"
  pix_fmt: str = "yuv420p"
  container: str = "mp4"
  faststart: bool = True              # -movflags +faststart (social streaming)
  fps: float | None = None            # None → inherit master fps
  maxrate_kbps: int | None = None     # optional platform cap; pure CRF when None
  acodec: str | None = None           # None → -an (Phase A silent); Phase B → "aac"
  abitrate_kbps: int | None = None
  __post_init__ raises: crf ∉ 0..51, empty vcodec/pix_fmt/container,
                        fps ≤ 0, maxrate_kbps ≤ 0, abitrate_kbps ≤ 0,
                        abitrate set while acodec is None (contradiction)
REEL_H264 = ExportProfile()           # module default the caller/skill uses

ReelCheckSpec                         # mirrors CheckSpec
  target_dur: float                   # SPEC reel length
  variety_min: int = 8                # min phash Hamming distance between adjacent episodes
  color_delta_max: float = 12.0       # §9 across-cut mean-RGB delta ceiling
  __post_init__ raises: target_dur ≤ 0, variety_min < 0, color_delta_max ≤ 0

ReelFailure                           # one attributed failure (§177 machine-readable)
  check: str                          # "black" | "color_across_cuts" | "variety" | "length"
  episode_idx: int | None             # culprit episode, when attributable
  escalate_to: str                    # "reprocess" | "edit-plan" | "pacing"
  detail: dict                        # the numbers (timestamp, delta, distance, …)

ReelReport                            # reel-level artifact; reuses CheckResult
  checks: dict[str, CheckResult]
  overall: bool                       # False if any check passed is False (passed=None never fails)
  fail_reasons: list[ReelFailure]     # empty when overall True
  episode_count: int
  wall_s: float                       # §11 binding: wall-time in every check report
  to_dict / from_dict / write         # JSON round-trip, like Report
```

`overall` is True when no check is `False` — a `None` (not-implemented) check
never fails the reel, matching the episode `Report` and the §430 "never a silent
pass" rule.

## §3 — `assemble` (concat strategy)

`assemble(episodes: list[str], canvas: tuple[int,int], fps: float, out_master:
str) -> str`. Reference = the caller's intended `(canvas, fps, yuv420p, h264)`
(it knows them from the project/delivery, the same values `process_episode`
rendered to).

1. **Fail loud** on `< 1` episode ("assemble needs ≥1 locked episode"), a missing
   file, or an episode with no video stream — never silently drop footage.
2. **Probe** each episode (ffprobe: `width,height,r_frame_rate,pix_fmt,
   codec_name`).
3. **All match the reference** (the by-construction happy path — every episode
   came from the same delivery) → `ffmpeg -f concat -safe 0 -i list.txt -c copy`
   → **lossless, fast** master. `list.txt` uses absolute paths (`-safe 0`).
4. **An outlier** (e.g. a source at a different fps that `reframe` carried
   through) → normalize *only that clip* (`scale=W:H,fps=FPS,format=yuv420p`,
   re-encode libx264, `-an`), then concat-copy. Episodes already correct are
   never re-encoded.
5. **Irreconcilable** (probe fails, zero-duration) → raise with a remedy.

Master is silent (episodes are `-an` from `reframe`; no audio streams to concat).

Landmine (montage §12): concat of non-uniform streams breaks/desyncs →
normalize before concat. This is that normalization, made surgical.

## §4 — `check_reel` (silent Phase A)

`run(master: str, episodes: list[str], spec: ReelCheckSpec, out_report: str) ->
ReelReport`. Deterministic whole-reel mechanicals that need no per-episode
subject data. Cut boundaries = cumulative episode durations (probe each).

| Check | Rule (§9) | Fail attribution |
|-------|-----------|------------------|
| `black` | `blackdetect=d=0.05:pic_th=0.98` on master; any `black_start` → fail | episode owning the black timestamp (via boundaries); `escalate_to="reprocess"` |
| `color_across_cuts` | mean-RGB Δ sampled each side of every cut < `color_delta_max` | of the two adjacent, the one whose mean deviates more from the reel median; `escalate_to="reprocess"` |
| `variety` | phash of one representative frame (episode midpoint) per episode; every adjacent pair Hamming ≥ `variety_min` (image, not filename — §427) | the second of the near-duplicate pair; `escalate_to="edit-plan"` |
| `length` | master duration within ±0.5s of `target_dur` | none (whole-reel); `escalate_to="pacing"` |
| `beat`, `loudness` | `CheckResult(passed=None, detail={"status":"not-implemented","reason":"silent reel — Phase B"})` | — |
| `safe_zones` | `passed=None`, `not-implemented` — needs per-episode route + a platform safe-margin table (§7/§432); honest defer | — |

`check_reel` is a **gate that returns a report**: legitimate failures land as
`CheckResult(passed=False)` + a `ReelFailure`, `overall=False` — it does **not**
raise on them. It raises only on infrastructure faults (missing master,
unprobeable episode). Attribution is computed here so Phase A.5's driver reads it
straight from `fail_reasons`.

## §5 — `deliver` (version log, §11 binding)

`deliver(master: str, profile: ExportProfile, out_dir: str, changelog: str,
report: ReelReport) -> str`.

1. **Hard gate:** `report.overall is False` → raise ("reel failed check_reel;
   fix the flagged episodes, do not deliver") — no fix-forward (montage §176:
   bad pacing is never rescued in deliver).
2. **Version naming:** scan `out_dir` for `REEL_v*.mp4` → next `n` = max+1 (empty
   → `v1`). Never overwrites a prior version — iteration is the norm (the session
   ran v2→v18).
3. **The one encode:** `master → out/REEL_v{n}.mp4` per profile —
   ```
   ffmpeg -y -i <master> -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
     [-maxrate {k}k -bufsize {2k}k] [-r {fps}] -an -movflags +faststart <out>
   ```
   `acodec None → -an` (silent); no `scale` (canvas is fixed, dims already even
   by construction — the odd-dim landmine is not reintroduced).
4. **Version log:** append `- v{n} | {ISO date} | {changelog}` to
   `out/VERSIONS.md` (create with a header if absent). `datetime.now()` at
   runtime — normal Python, available here.

## §6 — Follow-on: the reel retry loop (Phase A.5)

Recorded now, built next. The §4.1 escalation ladder one level up: a failed reel
check goes **back** to the culprit episode, never forward.

```
scripts/lib/reel_orchestration.py  NEW  next_action(fail_reasons, attempts) → Reprocess(episode_idx, hint) | Escalate(target) | Done. The §4.1 3×-then-escalate ladder, pure.
scripts/build_reel.py              NEW  driver: loop { assemble → check_reel → fail? reprocess culprits via process_episode → } ≤N, then deliver | stop_and_report. Mirrors process_episode.py.
scripts/reframe.py                 EDIT small per-episode color_target override so a reprocess can shift one episode's grade toward the reel median.
```

**Honest boundary** — only reprocess-class failures auto-close in this phase;
the rest stop-and-report a precise finding to the human (their escalation
targets, EDL/pacing, are the front half, not yet built):

| Reel failure | Auto-fix path | Phase A.5 |
|--------------|---------------|-----------|
| `black` | reprocess culprit (clean re-encode) | ✅ auto |
| `color_across_cuts` | re-grade the off-median episode (color_target override) | ✅ auto |
| `variety` | different window → EDL | ❌ stop-and-report |
| `length` | re-time spine → pacing | ❌ stop-and-report |

Loop cap `N` (default 3) per episode; the same failure 3× → escalate up the
ladder (montage §4.1: repeated fixes failing means the input artifact is wrong).

## §7 — Testing

**Unit (fast, mocked `proc`/ffprobe):**
- `ExportProfile` raises on crf 60 / empty pix_fmt / fps 0 / maxrate 0 /
  abitrate-without-acodec; `REEL_H264` defaults; `ReelReport` + `ReelFailure`
  round-trip identity; `overall` is False on a `False` check, True when the only
  non-True checks are `None`.
- `assembly`: all-uniform set → asserts the `-c copy` path, no normalize; one fps
  outlier → that clip normalized then concat; `<1` episode / missing file /
  unprobeable → RuntimeError with remedy.
- `check_reel`: color-Δ math, variety Hamming threshold, length window, boundary
  computation from durations, attribution rules (which episode, which
  `escalate_to`); not-implemented checks return `passed=None`.
- `deliver`: `v1` on empty dir / `v{max+1}` with existing; `VERSIONS.md`
  header+append; `-an` when silent; **raises on a failed report**.

**Integration golden (real ffmpeg, `@pytest.mark.integration`):**
`test_reel_backhalf.py` — the golden source → 2 distinct windows →
`process_episode` ×2 (fill, 9:16) → `assemble` (master duration ≈ sum, even
dims) → `check_reel` (`overall True`; `beat`/`loudness`/`safe_zones` `passed=
None`) → `deliver` (`REEL_v1.mp4` exists, ffprobe dims == canvas, `VERSIONS.md`
line; a second `deliver` → `v2`). The whole-slice proof, matching the golden
discipline of the engine-hardening and layouts plans.

## §8 — Landmines touched (montage §12)

- **Concat uniformity** — non-uniform streams break/desync; §3's probe →
  copy-or-normalize is the guard.
- **Even output dims** — deliver adds no `scale`, so it cannot reintroduce odd
  dims; the master inherits the episodes' already-even canvas.
- **`-ss` / `lutrgb`** — not in play here (no seek, no color op in the back
  half); the executable landmine lint that keeps them out is the recipes plan,
  not this one.
- **`drawtext` fontfile** — not in play (the *final* assembler burns no labels;
  the *draft* assembler that does is a later phase).
- **Never a silent pass** — audio/safe-zone checks report `passed=None`
  explicitly until Phase B/later wires them.

## §9 — Non-goals / deferred

- **Draft assembler** (labels, music bed) — later `scripts/assemble_draft.py`
  over the same `lib/assembly.py` core (front half).
- **`beat`, `loudness` checks + audio-mix** — Phase B (needs `MUSIC.json`).
- **`safe_zones` numeric check** — needs per-episode route data + a platform
  safe-margin table; lands with the editorial reel-final-check or a later phase.
- **Secondary-aspect re-reframe on deliver** — Phase F.
- **Resumability** (skip a stage when its artifact + input hash is unchanged) —
  the router's job (montage §11).
- **The retry loop itself** — Phase A.5 (§6), the immediate next slice.
