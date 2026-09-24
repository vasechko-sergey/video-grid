# The retry loop's record — design

**Date:** 2026-09-24
**Backlog rows:** P2 · "`EPISODES.json` does not record the retry-adjusted reframe
params" (S) · "`build_reel`'s automatic retry loop writes a reprocessed episode's
scratch one level deeper than `EPISODES.json` records" (M)
**Status:** design

Two rows, one thesis: **a retry changes what shipped, and the record does not
follow the change.** One row loses a number the render used; the other leaves the
record in a directory the render stopped writing to.

---

## §0 Measurements

### §0.1 The ladder fires, at both levels — and the last slice's "never" is wrong

The real run's phase-1 report for ep1 (`work/ep1/report.json`) records
`attempt: 2`. One of eight.

At reel level, `work/reel/` holds **nine** per-episode directories, `ep0` through
`ep8`, each containing `path.json`, `path.meta.json`, `report.json` and
`storyboard.jpg` and no `.mp4` (the clip goes to the manifest's absolute
`out_path`). `edl_to_reel` hands `build_reel` `<work_dir>/reel`
(`edl_to_reel.py:349`, `:614`) and `build_reel` creates `ep{i}` **only** in its
reprocess arm (`build_reel.py:201`) — nothing else in the tree writes that shape.
Their mtimes span three dates (2026-08-20, -21, -25); three of the nine record
`attempt: 2`.

So the reel retry loop engaged, repeatedly. [The episode-QC re-judge
design](2026-08-18-episode-qc-rejudge-design.md) §1.4 states the opposite — "**The
retry loop never engaged.**" — and names its evidence: `work/reel/reel_report.json`
with `overall: true`, `fail_reasons: []`. That file describes the **last round** of
the last invocation, not the history. Its §1.4 conclusion ("a stop-before-delivery
costs nothing on a clean reel") survives; the sentence that the loop never fires
does not. Corrected here rather than left standing, because the next slice to
price a retry-path change would read it and conclude the path is dead.

### §0.2 The manifest has no `max_speed` field at all

`manifest.Manifest` carries `smooth_window_s` (authored, nullable, validated into
`(0, 2.0]`) and **nothing** for `max_speed`. On the real run seven of eight
episodes carry `smooth_window_s: null`; ep7 carries `1.2`.

So the backlog row's "the manifest keeps the authored values" is true for one knob
and vacuous for the other: for `max_speed` there is no authored value anywhere in
the contract, and every reconstruction reads `orch.DEFAULT_PARAMS`
(`process_episode._plan_parts`).

### §0.3 Three consumers of the reconstruction, and one of them is silent

| consumer | drift guard | effect on a retried episode |
|---|---|---|
| `build_reel._predict` (`build_reel.py:63`) | `probe._refuse_on_drift` | contributes `None`; `check_reel` names it in `not_checked`. The episode that had trouble is the episode that loses its `grade_faithful` gate. |
| `probe.probe_grade` (`probe.py:206`) | `probe._refuse_on_drift` | refuses loudly, with a remedy — *"Re-render this episode, then probe the render you got"* — that cannot restore the params the previous render used. |
| `episode_qc._source_reading` (`episode_qc.py:121`) | **none** | plans at `DEFAULT_PARAMS`, reads the source through a crop the episode never shipped, and reports it to the judge as this episode's own source. |

`probe`'s geometry mode (`probe.py:307`) also plans from the manifest and has no
drift guard — correctly: it runs before any render, so there is nothing frozen to
disagree with. It is not a fourth instance.

The mechanism is already written down, in the code, in its own words
(`build_reel.py:41`–52):

> An episode whose accepted attempt was not attempt 1 shipped with
> `orch.adjust_reframe_params`'s rescaled `max_speed`/`smooth_window_s` instead,
> **which nothing records**.

### §0.4 The row's cited evidence is no longer reproducible

The row's source is [grade-shipped-pixels](2026-08-30-grade-shipped-pixels-design.md)
§0.9, which quotes the oracle refusing ep1: *"378 points vs 378, first difference
at index 0"*.

Re-running that oracle over the real `EPISODES.json` on this tree, 2026-09-24:

```
ep0: OK          ep4: OK
ep1: LOST — color_range is pc …          ep5: LOST — color_range is pc …
ep2: OK          ep6: LOST — color_range is pc …
ep3: LOST — color_range is pc …          ep7: OK
```

All four losses are `plan_render`'s depth/range guard
(`reframe.py:468` → `color.refuse_ungradeable_plane`) refusing `yuvj420p`/pc
segments — the four episodes named by the open "re-extract the real run's
segments" row, extracted 2026-08-25, before the 0.3.1 range contract. ep1 is
refused **before** the drift oracle runs. The four that pass all rendered at
`attempt: 1`, so nothing on this run reaches the drift arm at all.

The defect is unchanged; its harvest is gone. Every proof in §4 is therefore built
on committed footage, not lifted off the run.

### §0.5 One ladder step moves the path — and it is almost entirely one knob

Measured on the suite's own `golden_ride_segment` (the committed `golden_ride.mp4`
through the range conversion, 95 route samples) over `tests/fixtures/golden_route.json`:

| params | samples moved | max |Δx| |
|---|---|---|
| attempt 1 → one `jitter` step (`max_speed` 750→450, `smooth_window_s` 0.25→0.5) | **74 of 95** | **5 px** |
| `max_speed` 750→450 alone | 1 of 95 | 1 px |
| `smooth_window_s` 0.25→0.5 alone | 74 of 95 | 5 px |

The drift is the smoothing window. `max_speed` moves one sample by one pixel —
consistent with `adjust_reframe_params`'s own comment that speed alone never
converges a jitter failure. Both are still recorded, because `_refuse_on_drift`
compares the path **exactly** and one pixel refuses just as loudly as five; but a
reader should not be told the two knobs matter equally.

### §0.6 Only three fail reasons move a knob

`adjust_reframe_params` nudges on `_lags_line(fail_reasons)` — which is
`"on_line" in … or "centered" in …` — and on `"jitter"`. Every other fail reason
returns the params unchanged, so a retry for any other reason re-renders the same
geometry and creates no unrecorded state. Measured: a `["composition"]` retry
leaves `params` identical, hence the path bit-identical by construction.

That bounds the defect exactly: **`on_line`, `centered`, `jitter`.**

### §0.7 Row B's harm lands on the re-judge slice's own sanctioned remedy

`episode_qc._evidence` derives the episode's scratch directory as
`Path(ep.path).parent` (`episode_qc._epdir`) and reads four artifacts out of it —
`storyboard.jpg`, `report.json` → `checks`, `route.meta.json` → `track`,
`path.meta.json` → `geometry` — while taking the frame strip, the naturalness
stats and the `clip_digest` from `ep.clip`.

A reel-level reprocess writes fresh sidecars into `<work_dir>/reel/ep{i}` and
overwrites the clip **in place** at its absolute `out_path`. So a re-pack after an
automatic retry produces a **mixed** packet: fresh pixels, stale mechanics.

And the binding built to stop exactly this — the packet `clip_digest` added
2026-09-09, after a stale packet reached three judges — **cannot see it**, because
the stale half is not the clip. The digest agrees; the report, the storyboard, the
geometry and the track record are the previous render's.

The re-judge slice ([design](2026-08-18-episode-qc-rejudge-design.md)) makes
`build_reel` refuse to deliver over a reprocessed-but-judged episode and routes the
operator to a partial re-judge. That remedy runs `episode_qc pack`. So the stop
works and hands the judge a mixed packet.

### §0.8 The two directories genuinely diverge

Comparing the run's `work/ep{i}` against `work/reel/ep{i}` as they stand:
**7 of 8 `path.json` differ, 8 of 8 `report.json` differ**, 3 of 8 `path.meta.json`
differ.

Caveat, stated because it bounds what this number proves: those retry directories
are from earlier EDL revisions — several differ in sample *count*, which a params
change cannot cause. This measures that the two directories hold genuinely
different content, not the size of one retry's drift. §0.5 is the number for that.

---

## §1 The rule

**The record of what rendered is written by the renderer, beside what it
rendered.**

Two corollaries, one per row:

1. A value the render consumed and no one recorded is not reconstructible from the
   declaration, because a declaration is what the author asked for and a render is
   what happened. The renderer holds both; only it can write the second down.
2. **One episode, one scratch directory.** A second directory is a second record,
   and nothing keeps two records in step. The clip already has this property — it
   is overwritten in place — which is why the clip is the one artifact a re-pack
   reads correctly today.

---

## §2 The contract

### §2.1 `PathMeta` gains the two knobs

```python
max_speed: float | None = None          # the crop-x speed cap this render used, px/s
smooth_window_s: float | None = None    # the savgol span this render used, seconds
```

Written by `reframe.path_meta(plan, spec, *, stabilized)`, which already receives
the `ReframeSpec` that carries both — no plumbing, two constructor arguments.

**Emitted only when they differ from `ReframeSpec`'s own defaults** (750.0 / 0.25),
following the zoom arrays' precedent in the same `to_dict`: an episode that was
neither authored nor retried writes a sidecar byte-identical to the one it writes
today, so no golden moves. Checked: no test pins `PathMeta.to_dict`'s key set —
`test_pathmeta_reads_an_older_sidecar_as_not_a_pan` and its sibling delete a key
each rather than comparing the whole dict — and of 54 `PathMeta(` construction
sites exactly one is production, the rest tests, all of which stay valid under
optional fields. The one whole-dict comparison of a `path.meta.json` in the suite
(`tests/test_fake_render.py:32`) asserts against the **fake** render's hand-written
sidecar, which already omits `background`/`pan`/`stabilized`, so it is not a pin on
`to_dict` either.

`from_dict` reads both with the same `.get` exemption idiom `background`, `pan`,
`stabilized` and the zoom arrays already use — but **defaulting to `None`, an
absence, where every existing exemption substitutes a provable truth**. That
difference is the honest part and must be written at the site: absence here means
either "this sidecar predates the field" or "this render used the defaults", and
nothing distinguishes them.

The conflation is harmless because both resolve to the same reader behaviour, and
it is worth stating why for each case rather than asserting it once:

| sidecar | manifest | render used | reader at `params=None` |
|---|---|---|---|
| no key (pre-slice) | authored 1.2, retried to 0.6 | 0.6 | 1.2 → drifts → the guard refuses, named |
| no key (defaults) | unauthored | 0.25 | 0.25 → correct |
| key present | authored 1.2, no retry | 1.2 | reads 1.2 → correct |
| key present | any, retried | the retried value | reads it → correct |

### §2.2 One reader turns a sidecar into params

```python
def rendered_params(meta: PathMeta) -> dict | None
```

in `process_episode`, beside `plan_for`. Returns `{"max_speed", "smooth_window_s"}`
filled from the sidecar over `orch.DEFAULT_PARAMS`, or `None` when the sidecar
records neither — the named absence, so a caller can tell "the render used the
defaults, as recorded" from "nobody wrote it down".

`plan_for` and `plan_ungraded` gain a keyword-only `params: dict | None = None`.
`None` keeps today's behaviour exactly — `DEFAULT_PARAMS` plus the manifest's
authored `smooth_window_s` — and `plan_for`'s docstring, which currently states
that the retry loop deliberately does not come through here, is corrected rather
than deleted: the retry loop still does not, and a caller reconstructing a *past*
render now can.

### §2.3 The three readers

All three build the plan with the recorded params where the sidecar has them:

- **`build_reel._predict`** — reads `PathMeta.from_json(e.meta)`, passes
  `rendered_params(...)` to `plan_for`. A retried episode keeps its
  `grade_faithful` reading instead of losing the gate.
- **`probe.probe_grade`** — same, before `_refuse_on_drift`. The probe becomes
  usable on a retried episode, which is the whole point of `probe grade`.
- **`episode_qc._source_reading`** — same, **and gains the drift guard it never
  had**. Without a guard, an episode whose sidecar predates this field — which is
  every episode rendered before this slice — still silently reads its source
  through the wrong crop. The guard converts that into the named absence the
  function already returns (`{"source": None, "delta": None}`).

  The guard's `RuntimeError` is caught at the `_refuse_on_drift` call itself, not
  by widening the existing `except (FileNotFoundError, KeyError, ValueError)`:
  that clause's docstring gives a measured reason for excluding `RuntimeError`
  (`proc.run` raises it for a broken ffmpeg install), and widening it would
  reinstate the swallow it was written to prevent.

### §2.4 The reprocess writes beside the record it replaces

`build_reel`'s reprocess arm derives the episode directory the same way
`episode_qc._epdir` already does:

```python
epdir = str(Path(ep.path).parent) if ep.path else str(Path(work_dir) / f"ep{item.idx}")
```

Then `report.json`, `path.json`, `path.meta.json`, `route.meta.json` and
`storyboard.jpg` are overwritten in place — exactly as the clip already is — and
there is one directory per episode with nothing to keep in step.

**This writes outside `--work-dir`, and that is the point.** In the normal
two-phase run, phase 1's directory is `build/ep{i}` and `build_reel`'s work dir is
`build/reel`, so "beside the record" is always outside it. A guard refusing that
would refuse the only case that matters.

The empty-`path` fallback keeps today's behaviour for a hand-authored reel
manifest. `episode_qc._epdir` refuses such a manifest by name; `build_reel`
accepts it (the SP1 front door), and there is nothing to keep in step because
nothing points anywhere.

---

## §3 What does not change

- **No new contract field on `ReelEpisode`**, and `EPISODES.json` is not rewritten
  after a reprocess. Its paths stay correct because the files move to where the
  paths already point — not because anything re-checks them.
- **The retry ladder itself.** No threshold, no branch, no rung moves.
- **`_refuse_on_drift` stays a pure oracle.** It is not taught to forgive a
  recorded param; the callers build the right plan and it passes on its own.
- **`probe`'s geometry mode** keeps planning from the manifest at defaults. It
  runs before any render; there is no sidecar to read and nothing frozen to drift
  from.
- **`check_reel`, `check_episode`, `deliver`, `match_grade`, the QC gate's
  arithmetic.** Untouched.
- **Un-retried, unauthored episodes.** Byte-identical sidecar, byte-identical
  packet, byte-identical plan.

---

## §4 Proofs

1. **A ladder step moves the path.** `golden_ride_segment` + `golden_route.json`:
   one `jitter` step moves 74 of 95 samples by up to 5 px; `max_speed` alone moves
   1 sample by 1 px; a `["composition"]` retry leaves the params — and therefore
   the path — identical. (§0.5, §0.6.)
2. **The sidecar round-trips, and stays still.** `PathMeta.from_dict(to_dict())`
   preserves both fields; a spec at the defaults emits neither key, and the
   resulting dict equals the one today's code produces.
3. **An old sidecar reads as absence, not as a default.** A `path.meta.json` with
   no `max_speed` key yields `rendered_params(...) is None`, and `plan_for` with
   `params=None` produces exactly the plan it produces today.
4. **The round trip closes.** Render an episode through `reframe` at attempt-2
   params; `plan_for(..., params=rendered_params(meta))` reproduces the frozen
   path exactly and `_refuse_on_drift` passes, while the same call with
   `params=None` refuses. Real ffmpeg, real route.
5. **The reprocess writes into the phase-1 directory.** After a reel-level
   reprocess with a work dir that is not the phase-1 dir, `Path(ep.path).parent`
   holds the fresh `report.json`/`path.meta.json`/`storyboard.jpg`, and
   `<work_dir>/ep{i}` does not exist. Control: with `ep.path` empty, the old
   location is used.
6. **The packet stops being mixed.** `episode_qc.pack` after a reprocess yields an
   `evidence.json` whose `checks` and `geometry` come from the reprocess, beside a
   `clip_digest` of the reprocessed clip.
7. **The unguarded reading is guarded.** `_source_reading` on an episode whose
   frozen path disagrees with the recomputed one returns `{"source": None,
   "delta": None}` rather than a reading. Control: an agreeing episode still
   returns its two readings, and a genuinely broken source still raises rather
   than reporting absence.
8. **Controls that must not move.** An un-retried episode's `path.meta.json` is
   byte-identical to the pre-slice one; its packet's four sidecar-derived keys are
   unchanged; `build_reel._predict` returns the same profiles.

---

## §5 Honest limits

1. **The record proves which params were used, never that they were right.** A
   ladder that converges on a bad geometry now records the bad geometry
   faithfully.
2. **`max_speed` is recorded for exactness, not because it is known to matter.**
   On the one fixture measured it moves a single sample by a single pixel (§0.5).
   The oracle compares exactly, so that pixel is sufficient to refuse — but no
   measurement here shows `max_speed` mattering to any picture.
3. **The real run can no longer demonstrate either defect** (§0.4). Every proof is
   constructed on committed footage. The run contributes the *frequency* evidence
   (§0.1) and the divergence evidence (§0.8), not a reproduction.
4. **A stabilized episode's reprocess now overwrites the frozen `route.json`.**
   `build_reel` passes `route_path=None` for a stabilized episode and re-tracks
   (design 2026-07-20 §1). Under §2.4 the new route lands on the frozen one that
   `ReelEpisode.route` names. That is the route that shipped — correct — but the
   previous round's route is gone, and nothing records that it was replaced.
5. **Nothing verifies that `EPISODES.json`'s paths still resolve after a
   reprocess.** §2.4 makes them correct by construction; no check asserts it.
6. **The guard added to `_source_reading` covers drift from any cause, and names
   none of them.** It reports absence, not diagnosis. The diagnosis lives in
   `_refuse_on_drift`'s message, which this call site swallows.
7. **`PathMeta` now carries two fields no reader is obliged to use.** A future
   consumer that plans from the manifest alone will be as wrong as today's are,
   and nothing gates that it asked the sidecar.

---

## §6 Deferred

1. **R2.4 — a threshold widened by hand needs a reason attached.** Same
   impression, different mechanism: `provenance.spec_overrides` records that a
   field moved and never why. That is a gate on authoring, not a value carried
   forward. Stays its own row.
2. **Recording the accepted attempt *number* in `EPISODES.json`.** Not needed
   once §2.4 lands: the mechanical `report.json` already carries `attempt`, and
   after the fix the report a re-pack reads is the reprocess's own.
3. **A machine check that every `ReelEpisode` sidecar path resolves.** §5.5. Would
   turn "correct by construction" into "checked".
4. **Recording that a reprocess replaced a frozen route.** §5.4. `TrackMeta`
   already carries provenance bits (`degraded`, `stitched`); a "re-tracked at
   round N" bit would live there, and nothing reads it today.
