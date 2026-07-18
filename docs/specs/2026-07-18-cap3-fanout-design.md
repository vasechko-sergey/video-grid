# cap-3 parallel episode fan-out — Design Spec

Closes the **last open sub-item of stage §5.1** (using-montage router): the
design's cap-3 **parallel** episode fan-out
([montage §5.10](2026-07-05-montage-skillset-design.md), the
[using-montage design](2026-07-12-using-montage-design.md) §deferred), deferred
since 2026-07-12 when the slice was scoped to the entry-skill instead.

`edl_to_reel`'s loop-1 fan-out — one `process_episode` per episode — runs
sequentially today. It becomes a bounded thread pool. Nothing else in the
conveyor changes.

## Scope decisions (from brainstorming, 2026-07-18)

1. **Measure before designing.** The repo's own docs disagreed about whether
   this pays at all: montage §5.10 says "cap 3 … YOLO + ffmpeg saturate it"
   (three saturate the box) while `build_reel.py:88` says "sequential — one
   `process_episode` saturates the box" (one does). A spike settled it on real
   footage (§2). The design cites measurements, not either claim.
2. **Threads, not processes.** Measured: threads deliver the full 1.70×.
   `process_episode` is torch plus `subprocess` ffmpeg, both of which release
   the GIL. (Rejected: a process pool — 3× the interpreter and torch import
   (~2 s each) and manifest pickling, to buy a win threads already banked.)
3. **Run every episode, report the lowest index.** A failing episode no longer
   short-circuits the ones after it. The reported finding is byte-for-byte
   what the sequential loop produces, because it is chosen by index rather than
   by which thread lost the race (§4). (Rejected: fail-fast — `process_episode`
   is not cancellable mid-ffmpeg, so only *queued* work could be skipped, which
   makes the set of episodes that ran depend on scheduler timing. A
   non-reproducible run is a bad trade for seconds on an already-doomed reel.)
4. **`edl_to_reel` only.** `build_reel`'s reprocess loop has the same shape but
   its batches are typically one or two episodes, and loop-2 was hardened only
   days ago (the length re-time slice). Its stale comment is corrected; its
   control flow is not touched (§9).

## §1 — Architecture & files

No new module. The fan-out is a bounded pool around the call the driver already
makes, plus one preflight in the module that owns the model.

```
scripts/edl_to_reel.py    EDIT  DEFAULT_JOBS; edl_to_reel(..., jobs=DEFAULT_JOBS) +
                                validation; step 3 becomes a ThreadPoolExecutor;
                                lowest-index result selection; --jobs CLI (§3, §4)
scripts/track.py          EDIT  ensure_model(model_path) — materialize weights once,
                                before any worker can race for them (§5)
scripts/build_reel.py     EDIT  correct the measurement-refuted "one process_episode
                                saturates the box" comment (§9)
tests/lib/test_edl_to_reel.py  EDIT  fixture: index results by episode, not a shared
                                iterator, and stub ensure_model (§7.1); +19 tests
tests/lib/test_track.py   NEW   ensure_model tests + the MODEL/DEFAULT_MODEL pin (§7.3)
tests/integration/test_front_spine.py,
tests/integration/test_edit_plan.py  EDIT  stub ensure_model — all three goldens fake
                                process_episode, so a real YOLO buys them nothing (§7.4)
.gitignore                EDIT  yolo11*.pt — ultralytics downloads into the CWD when its
                                configured weights_dir is absent, i.e. into the repo root
docs                      EDIT  this spec + plan + using-montage §deferred + montage
                                §5.10 + build-status + pipeline-map + CLAUDE.md (§10)
```

**Dependency DAG:** `edl_to_reel` gains `concurrent.futures` (stdlib) and
`scripts.track`. It already imports `build_reel`, `extract` and
`process_episode`, all of which import `track` transitively, so no module learns
about a stage it did not already know. `track`'s ultralytics import stays
**lazy and inside `track`** — the driver never imports ultralytics itself.

## §2 — The measurement: why 3, and why not 4

A spike ran six real 2.5 s windows cut from `MVI_3739.MP4` (1920×1080, 59.94 fps)
through the full `process_episode` — YOLO11-seg tracking, reframe, check,
storyboard — at each concurrency, on a 14-core (10 performance) M-series box
with warm weights:

| jobs | wall-clock | speedup | per-episode latency | marginal gain |
|-----:|-----------:|--------:|--------------------:|--------------:|
| 1 | 41.1 s | 1.00× | 1.00× | — |
| 2 | 27.4 s | 1.50× | 1.29× | +1.50× |
| **3** | **24.2 s** | **1.70×** | 1.71× | +1.13× |
| 4 | 24.4 s | 1.68× | 1.85× | +0.99× — **nothing** |

**The knee is exactly 3**, which is the number montage §5.10 named. Past it,
per-episode latency keeps climbing (1.85×) while throughput does not: the
signature of a saturated box.

**Where the win comes from.** Per episode, `track` is ≈5.3 s of ≈7 s — torch —
and the rest is ffmpeg. One episode's tracking overlaps another's encode, and
fills torch's own single-threaded gaps (frame decode, NMS, ByteTrack
bookkeeping). Beyond three, torch instances contend for the same cores 1:1 and
the overlap is exhausted.

**So `build_reel.py:88` is the comment that is wrong**, not §5.10 — hence the
correction in §9. Six episodes is also a realistic reel: a 30 s reel at ~2.5 s
per episode is ~12, where the same ratio saves roughly half the fan-out's
wall-clock.

**Honest limits of this measurement.** One machine; `yolo11n-seg`, the smallest
of the three `MODELS`; 2.5 s segments; `fill` layout. A heavier model shifts the
mix further toward torch and shrinks the win. A discrete GPU would change the
shape entirely (torch off-CPU, ffmpeg on it) and probably favour a higher cap.
**Peak memory was not measured** — three concurrent YOLO models plus three
ffmpeg processes. The failure mode there is swapping, i.e. slow, not corrupt,
and `--jobs` tunes down; this is a documented residual, not a silent risk.

## §3 — The fan-out

```python
DEFAULT_JOBS = 3      # measured knee (§2): cap 4 buys nothing and costs latency
```

`jobs` is a **driver parameter with a default**, mirroring
`process_episode(..., max_attempts: int = 3)` — deliberately *not* a field on
`EDL`/`ReelManifest`. Concurrency is a property of the machine doing the render,
not of the reel being rendered; an `EDL.json` that travels between boxes must not
carry one box's core count.

**The name is `jobs`, not `cap`.** `cap` is taken: `EDL.cap` → `ReelManifest.cap`
is loop-2's *reprocess* cap, and `edl_to_reel` reads it two statements below the
fan-out. Two different "cap"s in one function is a bug waiting to be written.

```python
def edl_to_reel(edl_path: str, project_path: str, footage_root: str,
                work_dir: str, out_dir: str, *, music: str | None = None,
                titles: str | None = None, jobs: int = DEFAULT_JOBS) -> dict:
```

validated at the top, in the established fail-loud shape:

```python
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 1:
        raise ValueError(f"edl_to_reel: jobs must be an integer >= 1, got {jobs!r} "
                         f"(default {DEFAULT_JOBS} is the measured knee; lower it on a "
                         f"memory-constrained box, raise it only with a GPU)")
```

The `bool` exclusion is not pedantry — `True` is an `int` and would silently mean
`jobs=1`.

Step 3 becomes:

```python
    # 3. loop-1 fan-out: one process_episode per episode, up to `jobs` concurrently.
    # Safe to parallelise because each episode owns its scratch (work_dir/ep{i}) and
    # its output (out_dir/ep{i}.mp4) — process_episode's docstring names the clobber
    # this would otherwise cause. preflight (step 1) built both paths per index.
    for model in sorted({(md.get("model") or track.MODEL) for md in mds}):
        track.ensure_model(model)          # §5 — before any worker can race the download
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futures = [ex.submit(process_episode.process_episode, md,
                             str(Path(work_dir) / f"ep{i}"))
                   for i, md in enumerate(mds)]
    # the `with` block joined every worker: each future is done, in index order below
    results: list[dict] = []
    for i, fut in enumerate(futures):
        try:
            results.append(fut.result())
        except Exception as e:             # a hard setup error stays an exception (§4)
            e.add_note(f"raised while processing episode {i} (segment {mds[i]['segment']})")
            raise
```

The bare `raise` re-raises the original exception with its **own type and
traceback**; `add_note` (3.11+) attaches the episode index without constructing
anything. Both matter: `edl_to_reel`'s docstring contracts setup failures as
`ValueError`, so re-wrapping in a different type would break that contract, and
`type(e)(f"...")` would not even construct for exceptions whose `__init__` takes
more than a message (`subprocess.CalledProcessError`). A bare
`RuntimeError: command failed (exit 1)` escaping a pool otherwise gives no clue
which of six episodes produced it.

`with` + `shutdown(wait=True)` is what makes "wait for all" structural rather
than a convention: by the time the `for` runs, every worker has finished, and the
loop then reads **in index order**. No `as_completed`, no completion-order
dependence anywhere.

## §4 — Failure semantics, and the behaviour change

`process_episode` reports failure through two channels, and they need different
handling.

**Channel 1 — a returned status.** `needs_input` / `stop_and_report` /
`escalate` come back as dicts. The existing selection loop, unchanged, already
picks the lowest index because it iterates in order and returns on the first
non-pass:

```python
    episodes: list[ReelEpisode] = []
    for i, res in enumerate(results):
        if res.get("status") != "mechanical_pass":
            return {"status": "stop_and_report",
                    "finding": {"reason": "episode-failed", "episode_idx": i,
                                "sub_status": res.get("status")}, "sub": res}
        episodes.append(ReelEpisode(...))
```

**Channel 2 — a raised exception.** Missing footage, a corrupt sidecar, an
ffmpeg failure: `edl_to_reel`'s docstring already contracts these as raises, not
findings. It is re-raised with the episode index attached, because a bare
`RuntimeError: command failed (exit 1)` from a pool gives no clue which of six
episodes produced it.

**One pass, not two — the channels are ordered against each other.** This is the
subtlety the first implementation got wrong, and it is worth stating plainly:
draining every future's exception first and *then* scanning statuses gives each
channel its own lowest-index rule but no rule *between* them. A raise at episode 2
would beat a routable `stop_and_report` at episode 0 — which the sequential loop
returned before it ever reached episode 2. The caller loses a machine-readable
finding and gets a traceback. So a single loop walks the indices once, and
whichever problem sits at the lowest index wins **whatever kind it is**. That,
not per-channel ordering, is what makes the finding identical to the sequential
one.

### The behaviour change, stated plainly

Today a failure at episode 2 means episodes 3..N are never processed. After this
slice they are — **at every `jobs` value, including 1**. One semantics, not two:
a `jobs=1` run that behaved differently from a `jobs=3` run would make the
debugging escape hatch lie about the thing being debugged.

**The reported finding is unchanged** — same `reason`, same `episode_idx`, same
`sub_status`, same `sub`. Only wasted work differs.

**And the cost is bounded by a gate that already exists.** `preflight` (step 1)
catches every manifest-shaped problem *before* a frame is cut — that is the
cheap, fast failure class, and it still short-circuits exactly as it does today
(`test_bad_episode_preflights_before_any_ffmpeg` pins it). What reaches the
fan-out is `escalate`/`stop_and_report` from real tracking and reframing, which
is expensive to arrive at in the first place. The regression is theoretical
where it would hurt and real only where it is already slow.

## §5 — The weights race (a §12 landmine, not an optimization)

`track.MODEL` is a bare name, and the comment above it records why:

```python
# Ultralytics resolves bare model NAMES (auto-download on first use); an absolute
# path would NOT auto-download (landmine, design §12).
```

On a cold cache, three workers each construct `YOLO("yolo11n-seg.pt")` within
milliseconds of one another and each begins downloading the same file to the
same path. That does not raise — it corrupts, which is precisely the class this
repo keeps in always-loaded context.

```python
def ensure_model(model_path: str = MODEL) -> None:
    """Materialize the weights ONCE, before any concurrent tracking starts.
    Ultralytics auto-downloads a bare model NAME on first use (see MODEL), so N
    workers starting on a cold cache would each begin the same download into the
    same path — concurrent writers to one file, silent corruption rather than a
    raise. Constructing the model here IS the fix: it performs the download, and
    every worker afterwards finds the file already on disk. Idempotent and cheap
    once warm."""
    from ultralytics import YOLO      # lazy: heavy optional dep, mirrors _iter_detections
    YOLO(model_path)
```

The driver warms **every distinct model across the resolved manifests**, not just
the default. **Today that set always has exactly one element** and the loop is
forward-compatible only: `EDLEpisode` has no `model` field, `to_manifest_dict`
deliberately omits one, and `resolve_manifest` fills only canvas/delivery — so
nothing reaching this driver can pin `yolo11s-seg.pt`/`yolo11m-seg.pt` from
`MODELS`. The loop is kept because the *cost* is one set comprehension and the
failure it guards against is silent: if the EDL contract ever gains `model`, a
driver that warmed only the default would leave three workers racing for the
pinned one. A second hazard is live right now and pinned by a test instead:
`track.MODEL` and `manifest.DEFAULT_MODEL` are independent literals, and the
driver warms the former while every worker constructs the latter — drift between
them is exactly this landmine with no loop to catch it.

This preflight is **required for correctness**, not a nicety: without it the
slice introduces a silent-corruption path that does not exist today.

## §6 — Edge cases & fail-loud

- **`jobs=1`** → a pool of one. Same code path, same semantics as `jobs=3`
  (§4); the regression guard and the debugging escape hatch.
- **`jobs` greater than the episode count** → the pool simply never fills. No
  guard needed; `ThreadPoolExecutor` handles it.
- **`jobs=0`, negative, `True`, `"3"`, `3.0`** → `ValueError` with the remedy
  (§3). `True` is called out because `isinstance(True, int)` is `True`.
- **A single episode** → one worker; identical to today.
- **Two episodes fail** → the lower index is reported and its result is what
  `sub` carries; the higher episode's result is discarded, exactly as in the
  sequential loop, which returned before it ever saw the second failure.
- **An episode raises while another returns a failing status** → **the lower index
  wins, whichever kind it is.** A raise at 2 with a `needs_input` at 0 returns the
  finding for 0 (the sequential loop returned there and never reached 2); a raise
  at 0 with a `needs_input` at 2 raises. Getting this wrong — ordering each channel
  only within itself — silently converts a routable finding into a traceback, so
  both orderings are tested.
- **ultralytics absent** → `ensure_model` raises `ImportError` at the preflight
  rather than three identical `ImportError`s from three threads. Strictly better
  than today, where the failure surfaced from inside the first episode.
- **Interleaved stderr** — ultralytics prints per-frame progress and `track`
  logs; under a pool these interleave. Noise, not corruption: no code reads
  another episode's stderr, and each episode's structured result comes back on
  its own future. Not worth serializing behind a lock.
- **Scratch/output collision** → *not* an edge case but the load-bearing
  precondition: `preflight` derives `ep{i}` scratch and `ep{i}.mp4` output per
  index, so no two workers share a path. §7 pins it rather than trusting it.

## §7 — Testing

Concurrency is tested with **fakes and a barrier**, never with `sleep` — a
sleep-calibrated test is a flake with a countdown.

### §7.1 — The fixture race (must land first)

`tests/lib/test_edl_to_reel.py::_wire` currently hands out canned results from a
**shared iterator**:

```python
    results = iter(pe_results or [])
    def fake_pe(manifest, project_dir, route_path=None, color_correct=None):
        seen["pe"].append(...)
        return next(results, {"status": "mechanical_pass", ...})
```

Under a pool, *which episode receives which canned result* becomes a race —
`test_episode_failure_stops_and_reports_without_building` would intermittently
attribute its `needs_input` to episode 1 and assert `episode_idx == 0`. The
fixture must index by episode instead, keyed off `project_dir`'s `ep{i}` suffix
(the one per-call value that identifies the episode). That is a **test-
infrastructure fix that precedes the feature**, not a consequence of it.

Two further fixture obligations, both found during implementation:

- **Refuse the old list shape.** `dict(pe_results or {})` does not reject a list,
  and the silent case is the shape this file uses: `dict([{"status": s,
  "problems": p}])` coerces a one-element list holding a two-key result dict into
  `{"status": "problems"}`, after which every lookup falls through to
  `mechanical_pass` and the test passes having verified nothing. The fixture
  raises `TypeError` instead.
- **The fixture must stub `track.ensure_model`, not just `process_episode`.** The
  driver calls `ensure_model` **itself**, above the pool, so faking
  `process_episode` does not intercept it — left real, this fast-tier file imports
  torch, constructs a YOLO, and on a cold cache downloads the weights over the
  network. `tests/lib/` must reach neither; `pytest.ini`'s `integration` marker is
  where weights are declared allowed. The stub belongs in `_wire` so every test
  gets it uniformly, recording into the same `seen` dict the other fakes use —
  which also avoids a patch-order trap with the warm-up ordering test below.

### §7.2 — New unit tests (`tests/lib/test_edl_to_reel.py`)

- **The pool reaches the cap, and never exceeds it.** One fake serves both
  halves: it increments a lock-guarded live counter, waits on a
  `threading.Barrier(jobs, timeout=10)`, then decrements. With 6 episodes at
  `jobs=3` the barrier trips twice and the recorded peak is **exactly** 3.
  - *Reaches* — a sequential implementation never assembles 3 parties, so the
    barrier times out and raises `BrokenBarrierError`. This proves parallelism
    *happens*, the "moves samples, not just wires the graph" standard the
    ambient/SFX slices set.
  - *Never exceeds* — `peak <= jobs`, and because the barrier holds all three
    workers simultaneously, `peak == jobs` is **forced rather than hoped for**.
    A bare counter without the barrier could observe a peak of 2 on an unlucky
    schedule and flake; sharing the barrier fake is what makes the equality
    deterministic.
  - The 10 s timeout is a deadlock backstop, not a timing assumption: the
    barrier trips as soon as the third worker arrives, so a healthy run never
    approaches it.
- **Lowest index wins on multiple failing statuses** — episodes 1 and 3 both
  return `needs_input`; the finding names 1.
- **Lowest index wins on multiple exceptions** — episodes 1 and 3 both raise
  distinct errors; the escaping one names 1.
- **Every episode runs past a failure** — episode 0 fails, and all N episodes
  still appear in `seen["pe"]` (the §4 behaviour change, pinned deliberately so
  a future reader sees it was chosen).
- **`jobs=1` is byte-identical in outcome** — same `finding` dict as `jobs=3`
  for the same failing fixture.
- **`jobs` validation** — `0`, `-1`, `True`, `"3"`, `3.0` each raise with the
  remedy text.
- **Path isolation** — every `project_dir` handed to `process_episode` is
  distinct and ends in `ep{i}`; every `out_path` is distinct.

### §7.3 — `tests/lib/test_track.py`

- `ensure_model` constructs `YOLO` exactly once with the requested path
  (ultralytics monkeypatched — no download, no weights in the suite).
- `edl_to_reel` calls it for **each distinct model** in the manifests, and
  **before** the first `process_episode` call (a recorder asserts the ordering —
  a warm-up that runs after the pool starts is no warm-up).

### §7.4 — Integration

The existing real-ffmpeg goldens `tests/integration/test_front_spine.py` and
`test_edit_plan.py` must stay green at the default `jobs` — they drive
`edl_to_reel` end-to-end, so they are the proof the fan-out did not disturb the
SP1/SP3 seam. No new integration test: the seam is already covered, and
re-proving ffmpeg concurrency in CI would buy a slow, machine-dependent test for
no new information.

**They do need one edit, and the reason generalises.** All three fake
`process_episode` but not `ensure_model`, which the driver calls itself — so each
was constructing a real YOLO for a tracking pass it never runs, turning
ffmpeg-only goldens into torch-required ones and, on a cold cache, downloading
6 MB into the **repo root** (ultralytics falls back to the CWD when its configured
`weights_dir` is absent — hence the `.gitignore` entry). Invisible on a developer
box that already has the weights; a fresh CI clone is where it shows. Stubbing
`ensure_model` costs one line per fixture and restores what the marker promises:
integration means ffmpeg, not a model download.

## §8 — Landmines touched (montage §12)

- **New entry: the concurrent weight download.** N workers on a cold ultralytics
  cache race to write one file. Silent corruption, not a raise. Fixed by
  `ensure_model` before the pool (§5); registered in §12 because the *next*
  parallel consumer must know.
- **No pixel or timing op added.** This slice writes no ffmpeg arguments: no
  `-ss` (the frame-accurate seek landmine is untouched), no `lutrgb`, no colour
  op. It changes *when* existing calls run, never what they do.
- **Determinism preserved where it is observable.** The reported finding is
  index-selected, so the machine-readable output does not depend on thread
  scheduling. What genuinely is non-deterministic — stderr interleaving,
  wall-clock — is not part of any contract.
- **Scratch isolation is the precondition, and it is pinned.**
  `process_episode`'s docstring already warns that a shared `project_dir`
  clobbers a sibling; §7.2's path-isolation test turns that warning into a test
  instead of a comment.

## §9 — Non-goals / deferred

- **`build_reel`'s reprocess loop** (scope 4). Its comment — "sequential — one
  `process_episode` saturates the box" — is **refuted by §2** and is corrected to
  say that the batch is typically one or two culprits and that parallelising it
  is deferred, so the next reader does not re-derive a wrong reason. The control
  flow is untouched.
- **Parallelising `extract_edl`** — pure ffmpeg, ~1 s per window, and it runs
  once before the fan-out. Not worth a second concurrency surface.
- **Agent-level fan-out via `dispatching-parallel-agents`** — montage §5.10
  describes "3 episode subagents", but the fan-out is *mechanical*, and this repo
  puts mechanics in code and judgment in SKILLs. The `process-episode` SKILL
  stays available for the interactive single-episode path.
- **Auto-sizing `jobs` from `os.cpu_count()`** — the knee is set by torch/ffmpeg
  contention and memory, not by core count alone (§2 measured 3 on 14 cores, not
  12). A guessed formula would be less honest than a measured constant with a
  flag.
- **Measuring peak memory** — a documented residual (§2); the failure mode is
  swap, and `--jobs` is the mitigation.
- **A GPU-aware cap** — no discrete-GPU box was available to measure; §2 records
  the expectation without encoding it.

## §10 — Doc-sync (updated on completion)

- `docs/specs/2026-07-12-using-montage-design.md` — the "cap-3 *parallel*
  fan-out (§5.10) — `edl_to_reel` stays sequential" deferred bullet flips to
  **landed 2026-07-18**, pointing here.
- `docs/specs/2026-07-05-montage-skillset-design.md` — §5.10's "Concurrency cap:
  3 episode subagents at once" gains a **built** note with the measured knee, and
  records that it ships as an in-process pool in `edl_to_reel`, not as subagents;
  the §5.1 blockquote's "The cap-3 **parallel** episode fan-out (§5.10) is
  deferred" retires. §12 gains the weight-download entry (§8).
- `docs/build-status.md` — a Done entry; the "cap-3 parallel fan-out" next-action
  bullet retires.
- `docs/pipeline-map.md` — stage 5.1 loses its "one open sub-item" qualifier in
  both tables; the "Router + curation" roadmap line ◐ → ✅; the critical-path
  paragraph's "Genuinely open on the quality side" sentence drops the fan-out.
- `CLAUDE.md` — two registry rows (this spec + its plan).
