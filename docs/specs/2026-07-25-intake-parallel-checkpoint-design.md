# Intake — parallel scan + resumable per-clip checkpoint

**Status:** design · 2026-07-25 (slice B, part 1 of the footage-intake feedback;
window-band rework #3 is a **separate** slice)
**Scope:** turn `intake()`'s one sequential clip loop into two phases — a
parallel, checkpointed CV pass and a cheap, deterministic assembly pass — so a
long scan resumes instead of restarting, and one bad clip is quarantined rather
than lost.

_Last updated: 2026-07-25._

## 0. What the first real run proved

The 2026-07-22..24 surf run scanned 99 clips (16 GB) in **2 h 14 m** (21:05 →
23:19), and `intake()` writes `FOOTAGE.json` exactly **once, at the very end**
(`scripts/intake.py:311`). Those two facts compound: a crash — a corrupt clip, an
ffmpeg failure, an OOM, a Ctrl-C — at clip 80 of 99 throws away two hours of YOLO
and vidstab work, because nothing before the final write is on disk. The loop is
also strictly sequential, so a 14-core box runs one clip at a time.

This is feedback #4 (**slow scan**) and #5 (**each clip is a known, resumable
unit**). The fix is one structural change: make the clip the checkpoint unit and
the parallel unit at once.

Feedback #3 (the equal-interval window band, `_split_span`) is **out of scope
here** — it is editorial carving logic that the just-landed scenario-first work
(`FootageClip.room_after`, `start_offset`) already partly absorbed, and it earns
its own design. This slice does not touch `carve_windows`, `_split_span`, or
`score_window`.

## 1. The two phases

```
was:  for clip in clips: probe → scene → YOLO → vidstab → carve → score   (sequential)
      cull(all) ; save_cast(all) ; write FOOTAGE            (once, at the end)

is:   Phase 1 (parallel, checkpointed):  per-clip CV → cache entry per clip
      Phase 2 (sequential, cheap, pure): load all → cull → cast → write FOOTAGE
```

The split falls on a seam that already exists. The per-clip work
(`intake.py:293-306`) is independent across clips: each reads one file and
produces one `FootageClip` plus its cast crops. The tail (`cull`,
`save_cast_candidates`, the `FOOTAGE.json`/`.md` write) is **global** — it ranks
and dedups across every clip's windows and crops — so it cannot run until all
clips are in, and it must run in a fixed order to be reproducible.

Phase 1 is the only expensive part (YOLO seg + vidstabdetect per clip) and the
only part worth parallelising and caching. Phase 2 is cheap enough to re-run in
full on every invocation (§3), which is what keeps its output independent of how
Phase 1 was scheduled or cached.

## 2. Phase 1 — the per-clip worker

`_process_clip(path, sample_fps)` is exactly today's loop body, lifted into a
function and given two extra jobs so Phase 2 can be pure:

- **phash per window.** Today `cull` reads a frame from disk per window through an
  injected `phash_of` closure (`intake.py:308`). The worker computes each
  window's midpoint phash *while it already has the clip open* and returns them,
  so Phase 2's `cull` reads hashes from the cache instead of re-opening 300
  frames with ffmpeg.
- **descriptor per track.** Today `surface_crops` builds the colour-histogram
  descriptor from `(crop_rgb, mask)` at the global cast pass. The worker builds it
  where it already holds the mask, and returns `(source, conf, descriptor,
  crop_rgb)` per surviving track. Phase 2 then needs only floats and a PNG — no
  numpy, no mask.

Return value (in memory, before caching):

```
ClipResult:
    clip:    FootageClip            # unchanged contract
    phashes: list[str]             # hex, parallel to clip.windows (imagehash str())
    cast:    list[CastEntry]       # one per surviving track
CastEntry:
    source: str                    # clip filename (the composite-key half that survives)
    tid:    int
    conf:   float
    descriptor: list[float]        # DESCRIPTOR_LEN floats, already built
    crop_rgb:  ndarray             # worker-form only; the cache turns it into a PNG path
```

The worker's `CastEntry` carries the crop as a live `ndarray`; the **cached**
form (what `store` and `load` return, §3) carries it as an on-disk PNG path
instead. Phase 2 only ever sees the cached form (§4), so it handles one uniform
shape whether a clip was scanned or loaded.

The worker raises on a bad clip (corrupt file, ffmpeg/YOLO failure) exactly as
the code does today; the driver catches it (§5). It performs **no** global
operation, so two workers never touch shared state.

## 3. The checkpoint cache — `scripts/lib/intake_cache.py` (new)

A small module with one responsibility: persist and reload a `ClipResult`, and
decide whether a cached one is still valid. It is filesystem code (like
`assembly`, `vidstab`, `ffbin`), unit-testable without any CV.

### Layout

```
<out_dir>/.intake_cache/<clip-stem>/
    crops/t<tid>.png        # the RGB crop, written first
    clip.json               # written LAST, atomically → this file's presence == "committed"
```

`clip.json`:

```json
{
  "key":     {"size": 12345678, "mtime_ns": 1721..., "sample_fps": 3.0,
              "model": "yolo11n-seg.pt", "version": 1},
  "clip":    { ...FootageClip.to_dict()... },
  "phashes": ["8f3c...", ...],
  "cast":    [{"source": "MVI_3739.MP4", "tid": 4, "conf": 0.91,
               "descriptor": [ ... ]}]
}
```

`FootageWindow.best` is written into `clip.json` as `False`: it is a **Phase-2
output**, set by the global `cull`, which the worker never runs, and which Phase 2
always re-runs after load. Its cached value carries no meaning and must never be
trusted as a shortcut — the byte-identical invariant (§4) depends on `cull`
re-deriving it every run.

The crop PNGs are written under `crops/` first; `clip.json` is written to a temp
file and `os.replace`d into place last. `os.replace` is atomic on one filesystem,
so a reader either sees a complete `clip.json` or none. A crash mid-write leaves
crops but no `clip.json` → the entry reads as a miss → the clip recomputes and
overwrites. **`clip.json`'s presence-and-validity is the sole commit marker**; a
half-written entry can never be mistaken for a good one.

### Validity key

`key = (size, mtime_ns, sample_fps, model, CACHE_VERSION)`.

- **size + mtime_ns** — the source file's identity. A re-export or trim
  invalidates.
- **sample_fps** — changes `_people_timeline`'s sampling, hence the carve and the
  windows.
- **model** — `track.MODEL`; a different weights file is a different result.
- **`CACHE_VERSION`** (an int constant in `intake_cache`) — bumped by hand
  whenever Phase-1 logic changes shape (carve, score, descriptor, phash-point).
  This is the escape valve for the #3 slice: when it reworks carving it bumps the
  version, and every clip recomputes once. A cheap, explicit, all-or-nothing
  invalidation — not a per-field logic hash nobody can audit.

### The two functions

- `store(out_dir, path, sample_fps, result) -> ClipResult` — writes the crop
  PNGs, then atomically commits `clip.json`, and **returns the result in its
  cached form**: the `CastEntry.crop_rgb` arrays replaced by their on-disk PNG
  paths. The driver uses this return value, so a just-scanned clip and a
  cache-loaded clip present the identical shape to Phase 2 (§2).
- `load(out_dir, path, sample_fps) -> ClipResult | None` — returns the cached-form
  `ClipResult` on a key match, `None` on a miss (absent, stale, or unreadable — a
  corrupt or truncated cache file is a miss, never a crash).

`--fresh` makes the driver skip `load` entirely (every clip a miss), forcing a
full recompute without deleting the directory.

## 4. Phase 2 — the driver, the pool, the invariant

```python
DEFAULT_JOBS = 3     # cap-3's measured knee (2026-07-18 §2); see §7 for the honest caveat

def intake(footage_root, out_dir, sample_fps=SAMPLE_FPS, *,
           jobs=DEFAULT_JOBS, fresh=False):
    paths = sorted(...)                          # the fixed order EVERYTHING below respects
    track.ensure_model(track.MODEL)             # §7 weights-race landmine, BEFORE the pool
    results, misses = {}, []
    for p in paths:
        hit = None if fresh else cache.load(out_dir, p, sample_fps)
        if hit is not None: results[p] = hit     # cheap JSON+PNG read, main thread
        else:               misses.append(p)
    log(f"{len(results)} cached, {len(misses)} to scan")
    failed = []
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {p: ex.submit(_process_clip, str(p), sample_fps) for p in misses}
    for p in misses:                             # join order irrelevant; read in sorted order below
        try:
            res = futs[p].result()
            results[p] = cache.store(out_dir, p, sample_fps, res)   # store returns cached-form (§3)
        except Exception as e:
            failed.append({"source": p.name, "error": str(e)})      # §5 quarantine
    # ---- Phase 2 proper: everything in sorted(paths) order ----
    ok = [results[p] for p in paths if p in results]
    footage = Footage(clips=[r.clip for r in ok])
    phash_by = {(r.clip.source, w.start, w.dur): imagehash.hex_to_hash(h)
                for r in ok for w, h in zip(r.clip.windows, r.phashes)}
    cull(footage.clips, phash_of=lambda c, w: phash_by[(c.source, w.start, w.dur)])
    save_cast_candidates([e for r in ok for e in r.cast], out_dir)   # refactored (§6)
    write FOOTAGE.json / FOOTAGE.md (+ failed section) ; intake_report.json
```

**The load-bearing invariant, and it is tested (§9):** `intake()`'s output —
`FOOTAGE.json`, `FOOTAGE.md`, `cast_candidates.json`, `cast_crops/` — is
**byte-identical for the same footage + sample_fps, at any `jobs`, and whether a
clip was freshly scanned or loaded from cache.** It holds because:

- Per-clip CV is deterministic (CPU torch inference and ByteTrack are; the
  existing integration golden already relies on it), so a `ClipResult` does not
  depend on which thread produced it, or on the round-trip through the cache.
- Every global step reads `results` in **`sorted(paths)` order**, never in
  future-completion order. `cull`'s `sorted(..., reverse=True)` is stable, so
  score ties break by (clip, window) order; `surface_crops`' conf sort is stable
  over the same order. No `as_completed`, no scheduling dependence anywhere.

`ensure_model` runs **before** the pool because `track.MODEL` is a bare name that
ultralytics auto-downloads on first construction; N cold workers would each write
the same weights file — silent corruption, the same §12 landmine cap-3 fixed for
`edl_to_reel`. `intake._iter_seg` is a live second consumer of that hazard.

## 5. Failure — quarantine and report

A worker exception is caught in the join loop and recorded as `{source, error}`;
the scan **continues**. Phase 2 builds `Footage` from the clips that succeeded.

- **The report.** `FOOTAGE.md` gains a `## Failed clips (N)` section listing each
  source and its error, and a machine-readable `intake_report.json`
  (`{"failed": [{"source", "error"}], "scanned": M, "cached": K}`) is written
  beside `FOOTAGE.json`. `main()` prints a loud `⚠ N clip(s) failed — see
  intake_report.json` to stderr.
- **Exit code stays 0.** A valid `FOOTAGE.json` was produced from the good
  clips; the failures are named, not swallowed. The `footage-intake` SKILL reads
  the report and surfaces it to the human. (This is "fail-loud" in the sense that
  matters — nothing is lost silently — without halting a 99-clip batch on one
  file.)
- **Retry-only-failed falls out of the design.** A quarantined clip wrote no
  `clip.json` (it raised before `cache.store`), so a re-run finds it a cache miss
  and re-submits *exactly* the failed clips, while every good clip is a hit. No
  separate retry list, no special path — the checkpoint is the retry state.

`Footage`'s contract is **unchanged** (`{clips: [...]}`); the failure list lives
in `FOOTAGE.md` + `intake_report.json`, not inside `FOOTAGE.json`, so no reader
of the footage contract learns a new field.

## 6. What is refactored (and what is not)

- **`cull` is unchanged.** It still takes an injected `phash_of`; the driver just
  closes it over the cached hashes instead of over `_phash_at`'s ffmpeg read. Its
  unit tests keep passing verbatim.
- **`_phash_at` survives** as the worker's phash source (called once per window in
  Phase 1 instead of once per window in the global cull).
- **`surface_crops` and `save_cast_candidates` change input shape.** They consumed
  `crops_by_track = {tid: (conf, crop_rgb, mask)}` and built descriptors inline.
  They now consume the precomputed `CastEntry` list (`source, conf, descriptor`,
  plus the crop already on disk as a cache PNG) and `save_cast_candidates`
  **copies** the cache crop PNG to `cast_crops/candidate_{i}.png` rather than
  `Image.fromarray`-ing a live array. Their two unit tests move to the new shape.
  Descriptor *values* are identical — `build_descriptor` is pure and just runs in
  the worker now — so the byte-identical invariant holds across the move.

## 7. `jobs`, memory — the honest caveat

`DEFAULT_JOBS = 3` reuses cap-3's measured knee, but that measurement
(2026-07-18 §2) was six **2.5 s segments** through `process_episode`. Phase 1's
unit is a **whole clip**: a full-length YOLO-seg pass plus a full-clip
`vidstabdetect`, heavier per worker and holding more in memory (N concurrent YOLO
model instances — `_iter_seg` constructs one per clip — plus N ffmpeg
processes). This was **not** re-measured; the 99-clip / 16 GB set is not a
spike-able workload here. The constant is a reasonable default with a flag, not a
claim.

`--jobs` tunes it: lower on a memory-constrained box, raise it with a GPU. The
failure mode of over-subscription is swap (slow), not corruption. `jobs` is a
driver parameter with a default, never a field on `Footage` — concurrency is a
property of the machine, not of the footage — validated in the established shape:

```python
if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 1:
    raise ValueError(f"intake: jobs must be an integer >= 1, got {jobs!r} ...")
```

The `bool` exclusion is not pedantry: `True` is an `int` and would silently mean
`jobs=1`.

## 8. Contracts touched

| File | Change |
|------|--------|
| `scripts/lib/intake_cache.py` (new) | `CACHE_VERSION`, `clip_key`, `store`, `load` (miss on stale/absent/corrupt), crop-PNG (de)serialization |
| `scripts/intake.py` | `intake()` → `_process_clip` worker + two-phase driver; `DEFAULT_JOBS`, `jobs`/`fresh` params + validation; `ensure_model` before the pool; `ThreadPoolExecutor`; quarantine + `intake_report.json`; per-clip progress log; descriptor moves into the worker; `surface_crops`/`save_cast_candidates` take precomputed entries; `--jobs`/`--fresh` CLI |
| `tests/lib/test_intake_cache.py` (new) | the cache unit battery (§9) |
| `tests/lib/test_intake.py` | jobs validation, quarantine, resume, byte-identical, ensure_model-before-pool ordering, pool-cap barrier; `surface_crops`/`save_cast` new shape |
| `tests/integration/test_intake.py` | second run resumes from cache → identical output on real data |
| docs | `build-status`, `pipeline-map`, `CLAUDE.md` (this spec + its plan), footage-intake design note |

`ClipResult`/`CastEntry` are **internal** shapes (worker → cache → driver), not
on-disk contracts a foreign tool reads, so they are plain dataclasses/dicts, not
`config-spec`s with `from_dict` gates. The on-disk contracts — `FootageClip`,
`Cast`, `cast_candidates.json` — are unchanged.

## 9. Testing

Concurrency is tested with **fakes and a barrier, never `sleep`** (a
sleep-calibrated concurrency test is a flake with a countdown), mirroring cap-3
§7.

**Cache unit (`tests/lib/test_intake_cache.py`):**
- key derivation over (size, mtime_ns, sample_fps, model, version);
- `store` → `load` round-trip returns an equal `ClipResult` (FootageClip,
  phashes, cast all identical; crop PNG bytes round-trip);
- staleness: a changed mtime / sample_fps / model / `CACHE_VERSION` each → `load`
  returns `None`;
- **atomicity: crops present but no `clip.json` → miss** (the commit-marker
  contract); a truncated/corrupt `clip.json` → miss, not a raise;
- `--fresh` semantics: a valid entry still loads as `None` when `fresh=True`.

**Driver unit (`tests/lib/test_intake.py`), `_process_clip` faked:**
- `jobs` validation: `0, -1, True, "3", 3.0` each raise with the remedy;
- **quarantine**: a worker that raises on one clip → that clip in `failed`, the
  others in `FOOTAGE.json`, exit 0, `intake_report.json` names it;
- **resume**: pre-seed the cache for some clips → only the misses reach the pool
  (a recorder proves the cached clips were never submitted);
- **byte-identical**: `jobs=1` vs `jobs=3`, and `fresh` vs cached, produce
  identical `FOOTAGE.json` / `cast_candidates.json` for the same fake footage;
- **ensure_model before the pool**: a recorder asserts `ensure_model` ran before
  the first `_process_clip` submit;
- **pool reaches cap and never exceeds it**: a fake increments a lock-guarded live
  counter and waits on `threading.Barrier(jobs, timeout=10)` — with more clips
  than `jobs` the barrier trips and the recorded peak is exactly `jobs` (reaches
  proves parallelism happens; `Barrier` makes the equality deterministic, not
  hoped-for).

**Integration (`tests/integration/test_intake.py`, real ffmpeg + YOLO):**
- the existing golden stays byte-identical at `DEFAULT_JOBS`;
- **a second `intake()` on the same footage + out_dir resumes from cache (zero CV)
  and produces byte-identical output** — one real CV pass plus one cache-hit pass,
  proving cache correctness on real pixels without doubling CV time.

## 10. Landmines (montage §12)

- **New: none original to this slice, one re-touched.** The concurrent
  weight-download (cap-3 §8) now has a **second** consumer — `intake._iter_seg`
  constructs `YOLO` per clip, so N cold workers race. `ensure_model` before the
  pool is the same fix, and this slice registers intake as a consumer so the next
  parallel author knows.
- **No pixel or timing op added.** This slice writes no new ffmpeg arguments —
  no `-ss`, no `lutrgb`, no colour op. It changes *when* and *how many* existing
  passes run, never what they compute. The `-ss`-after-`-i` seek discipline in
  `_phash_at`/`shake_by_window` is untouched.
- **Determinism is a tested contract, not a hope (§4 invariant).**
- **Cache staleness is the one silent risk, and the key is its guard.** A cache
  that returned a stale result would corrupt silently; every input that changes a
  `ClipResult` is in the key, and `CACHE_VERSION` covers logic changes the key
  cannot see. Getting a *new* Phase-1 input out of the key is the mistake to guard
  against in review.

## 11. Out of scope

- **#3, the window band** (`_split_span`'s equal-interval carve) — a separate
  slice, with its own design; scenario-first already absorbed its length half.
- **Caching CV *intermediates*** (scene cuts, YOLO timeline, vidstab mags) so #3
  could re-carve without re-running YOLO — considered and deferred (brainstorm
  2026-07-25, "Approach 3"): bigger, more complex, and buys nothing until #3
  exists. The #3 slice may extend the cache then; `CACHE_VERSION` makes the
  transition clean.
- **Measuring intake's own `jobs` knee / peak memory** — a documented residual
  (§7); the mitigation is the flag.
- **A GPU-aware cap** — no GPU box to measure; §7 records the expectation.
- **Parallelising Phase 2** — cull/cast are cheap and order-dependent; a second
  concurrency surface would buy nothing and threaten the invariant.
