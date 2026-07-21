# The tracking-degradation ladder — three rungs, one route contract

**Date:** 2026-07-21
**Slice:** design spec §6.1 "Degradation ladder (tracking)" / §6 follow algorithm
**Status:** design approved, not yet built

Since the engine-hardening slice, `track.py` has authored the route with exactly
one tracker: Ultralytics YOLOv11-seg + ByteTrack. When that tracker is **absent**
(no `ultralytics`/`torch` in the environment) the import raises on attempt 1 and
`process_episode` dies with a traceback. When it runs but **detects nobody**, the
empty route becomes a `no-track` stop-and-report. `process_episode` has carried a
reserved `"degraded": None` in its `mechanical_pass` result since the orchestrator
slice, waiting for this.

Design spec §6.1 names the fallback: "ultralytics unavailable or the track is
garbage → optical-flow centroid tracker (OpenCV, no ML deps) → manual storyboard
keyframes + interpolation (the session's proven method). Each step down is recorded
in the episode report as `degraded: <level>` — the pipeline still delivers."

This slice builds the two lower rungs and the provenance that names them. It is
**standalone**: §6.1a layer 3 (descriptor continuity re-match) is a different
mechanism against a different failure and stays its own slice. The route-provenance
"envelope" the two were once imagined to share turned out to already exist —
`TrackMeta`, the sidecar `track.py` writes beside `route.json` — so there is nothing
to co-design.

---

## 1. The load-bearing decision: fall only on *nothing*, never on *bad*

Spec §6.1 reads "unavailable **or garbage** → optical-flow." Taken literally that
says: when the strong tracker produces a **bad-but-non-empty** route (teleports, an
ID switch, a subject held for only a fraction of the window), drop to optical-flow.
That is the one reading this design rejects, and the rejection is the spine of the
slice.

Optical-flow centroid tracking is a **weaker** sensor than YOLO+ByteTrack. It has no
person model — it follows whatever moves most. So when a strong tracker returns a bad
route, a weak one will almost never return a better one; it will return a *different*
bad route, and we will have stamped `degraded: flow` on something no more trustworthy
than what we replaced, hiding the failure instead of surfacing it. Auto-downgrade on
a quality failure trades a visible problem for an invisible one.

**So the ladder auto-falls only when a rung produced *nothing usable*:**

- **Rung 1 → 2** on: YOLO **unavailable** (import fails), **or** YOLO ran and returned
  an **empty** route (nobody detected).
- A **bad-but-non-empty** route is *not* a ladder trigger. It is a real observation
  and flows to `check_episode` exactly as today; the existing retry/escalation ladder
  in `orchestration.py` owns quality failures, and `checks.continuity` already flags
  the teleports. If that ends in a stop-and-report, the human's answer is rung 3 — but
  the machine never silently swaps trackers on a route it merely dislikes.

### 1.1 Optical-flow is identity-blind — so a pinned hero never enters it

The second half of the load-bearing decision. A hero pin (`bbox` / `cast` name /
`rule` / `track-id`, §5.10) is a claim about **which person**. Optical-flow tracks the
dominant *motion blob*; it cannot honor "the person in the red rashguard" or "track
id 3." Running it for a pinned episode would answer an identity question with a motion
answer — the exact silent substitution the hero-pin slice (2026-07-16) exists to
delete.

Therefore the rung-1→2 trigger is **empty AND unpinned**. An empty route under a pin
is already `hero-unmatched` today (`orchestration.detect_contradictions`, keyed on
`pin_matched=False`), and that stays: the pinned person is simply not in this segment,
and the remedy is a human re-check, never a motion-blob stand-in. The ladder changes
the **unpinned** empty case only — the case that is `no-track` today.

---

## 2. The ladder, precisely

```
Unpinned episode, no supplied --route:

  rung 1  track.build_route (YOLOv11-seg + ByteTrack)
    ├─ ultralytics unavailable ───────────────► rung 2
    ├─ empty route (nobody detected) ─────────► rung 2
    └─ non-empty ────────────► degraded=None,   proceed

  rung 2  flow.build_route (optical-flow centroid; cv2, no ML)
    ├─ cv2 unavailable ───────────────────────► rung 3
    ├─ empty route (no motion blob) ──────────► rung 3
    └─ non-empty ────────────► degraded="flow", proceed

  rung 3  manual keyframes
    ├─ keyframes.json supplied ─► interpolate ─► degraded="manual", proceed
    └─ none supplied ─────────► stop_and_report("supply keyframes / --route / a pin")
```

**Pinned episode, or a supplied `--route`, or a `pan`:** no ladder. A pin runs rung 1
only (empty → `hero-unmatched`). A supplied route and a pan already bypass tracking
entirely (a pan writes no route at all — 2026-07-19 §6.1). All three keep
`degraded=None`.

### 2.1 Where in `process_episode`

The seam is the tracking branch (today `scripts/process_episode.py:185-195`, the
`elif route_path is None:` arm). The rung attempts are I/O — spawn a tracker, read the
route back — so they stay imperative in the shell. Each rung, on success, leaves the
**same two artifacts** the shell already reads one line later:
`route.json` + `route.meta.json`. The shell then reads `track_meta["degraded"]` into
the result (replacing the literal `None` at the `mechanical_pass` return).

The ladder sits **after** the stabilization pre-stage, so every rung tracks the *same*
pixels `reframe` will cut — `src`, which is the stabilized copy when `stabilize: true`,
the raw segment otherwise. The 2026-07-20 §1 invariant (tracker and reframe read one
file) holds for all three rungs by construction, because they all receive `src`.

### 2.2 The one pure decision worth extracting

Everything else is I/O, but "is this empty route eligible for flow, or is it
`hero-unmatched`?" is a §4.1 judgment and gets a named, unit-tested predicate in
`orchestration.py`:

```python
def flow_eligible(pinned: bool, route_empty: bool) -> bool:
    """An empty route falls to optical-flow ONLY when nobody was pinned. Optical-flow
    follows the dominant motion blob and makes no identity claim, so it cannot honor a
    §5.10 hero pin — an empty route under a pin is hero-unmatched (the pinned person is
    not in this segment), and answering it with a motion blob is the silent identity
    substitution the hero-pin slice deleted. See design 2026-07-21 §1.1."""
    return route_empty and not pinned
```

---

## 3. `scripts/lib/flow.py` — the optical-flow centroid rung

A new module, the first runtime consumer of OpenCV as a *tracker* (intake never
tracks; it probes). Public surface:

- **`available() -> bool`** — `try: import cv2` → `True`/`False`. The rung-2 gate,
  mirroring how the shell will gate rung 1 on `track.available()`. cv2 is undeclared
  in `requirements.txt` (it arrives transitively under `ultralytics`), so when
  ultralytics is the thing that is absent, cv2 may be gone with it — the gate makes
  that a clean fall to rung 3, not a second traceback.
- **`build_route(src, out, fps, dims) -> list[RoutePoint]`** — decode the source with
  `cv2.VideoCapture` (cv2's own decoder — this is not an ffmpeg argv, so none of the
  §12 ffmpeg landmines apply), downscale each frame so the long side is ≈480 px
  (centroid precision is coarse by nature and the route is smoothed downstream), and
  between consecutive gray frames run dense Farneback optical flow
  (`cv2.calcOpticalFlowFarneback`). Per frame: magnitude field → threshold at a fixed
  fraction of the frame's own max magnitude → largest connected component → its
  centroid and bounding box, rescaled to source `dims`, become one `RoutePoint`
  (`t = idx/fps`). Frame 0 has no predecessor and is seeded from frame 1's result.
- It writes `route.json` (`route_to_json`) **and** a `TrackMeta` sidecar with
  `degraded="flow"`, `ambiguous=False`, `pin_matched=None`, `features={}` — the same
  pair `track.build_route` writes, so `_load_route` and every downstream reader are
  unchanged.

**Empty is honest.** A clip with no motion above threshold (a static subject, or a
subject smaller than the flow noise floor) yields an empty route → rung 3. Flow needs
motion; saying so beats inventing a centroid.

`fps`/`dims` are **passed in**, never re-probed. `process_episode` already probed them
(`_fps`, `src_w`, `src_h`); `track.build_route` re-probes only because its CLI can run
standalone, and flow has the caller's numbers in hand.

---

## 4. `scripts/lib/keyframes.py` — the manual rung, sparse in, dense out

Rung 3 is the human, and the human's channel is a **sparse** `keyframes.json`: a few
`RoutePoint`-shaped marks (`[{t, x, y, w, h}, …]`), "the session's proven method." A
full frame-by-frame `--route` is already accepted and is brutal to author by hand;
sparse keyframes plus interpolation is the point.

- **`interpolate(sparse, fps, dur) -> list[RoutePoint]`** — pure, no I/O. Marks sorted
  by `t`; each output field (`x, y, w, h`) is `numpy.interp`'d across the marks' `t`
  values onto the per-frame grid `t = i/fps` for `i` in `[0, round(dur*fps)]`. Before
  the first mark it holds the first; after the last it holds the last (numpy.interp's
  own edge behavior — named, not accidental). One mark is a legal static hold; **zero
  marks raises** a remedy-bearing `ValueError`. Marks with `t` outside `[0, dur]` or
  non-increasing `t` raise (the config-spec discipline — a bad answer channel fails
  loud, it does not silently clamp).
- A thin `write_route(keyframes_path, out, fps, dur)` wrapper reads the sparse file,
  calls `interpolate`, and writes the same `route.json` + `TrackMeta(degraded="manual")`
  pair. `RoutePoint.from_dict` already guards a bare-scalar file (engine-hardening) —
  a human hand-authoring keyframes is exactly who benefits from that guard.

`keyframes_path` rides into `process_episode` beside `route_path` — a new optional
parameter and CLI flag (`--keyframes`), at the same answer-channel level as `--route`.
It is **not** an EDL field: keyframes are a recovery response to a stop-and-report, not
an editorial authoring choice, so `edl.py` / `build_reel` are untouched.

---

## 5. `TrackMeta.degraded` — route-side provenance

The provenance bit lives on `TrackMeta`, the sidecar beside `route.json`, because
**which tracker produced the route** is a fact about the route:

```python
degraded: str | None = None     # None = clean (YOLO) | "flow" | "manual"
```

`DEGRADED_LEVELS = ("flow", "manual")` is the vocab (a `None` default is always legal);
`to_dict`/`from_dict` carry it, defaulting absent → `None` so any sidecar written
before this slice reads as clean. This mirrors, on the **route** side, what `pan` and
`stabilized` do on the **path** side (`PathMeta`): both are one-bit answers to "how was
this artifact made," read by a downstream consumer that has no other way to know.

`process_episode` copies it into the result: `report["degraded"] = track_meta.get("degraded")`.
Because the three no-ladder cases (pin, supplied route, pan) never set it, they report
`None` — honest, they used the clean tracker or none at all.

Nothing downstream *branches* on `degraded` in v1. `check_episode` judges a flow or a
manual route exactly as it judges a YOLO route — all three are real observations (this
is the sharp line against `pan`, whose *generated* path `check_episode` must **not**
judge as composition; a degraded route is observed, not generated, so no
`PathMeta`-style suppression applies). `degraded` is a report stamp and a signal to the
human at the editorial gate, paired with the storyboard marker that already draws the
followed subject.

---

## 6. Contracts touched

- **`scripts/lib/models.py`** — `TrackMeta.degraded` field + `DEGRADED_LEVELS`;
  `to_dict`/`from_dict` updated.
- **`scripts/track.py`** — add `available() -> bool` (try-import ultralytics), the
  symmetric gate to `flow.available()`. `build_route` already writes `TrackMeta` with
  no `degraded` → defaults to `None`, correct with no change.
- **`scripts/lib/orchestration.py`** — `flow_eligible(pinned, route_empty)` (§2.2).
- **`scripts/process_episode.py`** — the ladder wiring in the `route_path is None`
  arm; `keyframes_path` parameter + CLI `--keyframes`; `report["degraded"]` fed from
  the winning rung's sidecar.
- **New `scripts/lib/flow.py`**, **new `scripts/lib/keyframes.py`** (§3, §4).

`detect_contradictions`'s `no-track` finding is **kept** — it is still correct for a
*supplied* empty route (`route_path` given, empty), which the ladder does not touch.

---

## 7. What this slice honestly does not do

- **The wade-in landmine, one rung down.** Optical-flow on a wade-in/out shot
  ("rolling ground") locks onto the water, not the subject — flow is least trustworthy
  on exactly the shot stabilization must never touch (§12). This is **not** a new
  silent-corruption class: the route is stamped `degraded="flow"` and the storyboard
  marker shows the human what it followed, so the failure is visible, not silent. But
  it earns a §12 line, and it keeps **no machine predicate** — consistent with the
  wade-in rule already there (auto-detecting "this is a wade-in" is the same
  unsolved problem, and guessing would fire hardest on this shot).
- **No reel-level surfacing.** `degraded` is an episode-report field. Whether a reel
  built from degraded episodes should carry an advisory (the safe-zones pattern) is a
  later question; v1 stops at the episode.
- **No flow auto-tuning.** The Farneback parameters and the magnitude threshold are
  fixed constants. Tuning them per-clip is a weaker tracker chasing a stronger one's
  job — out of scope by the same §1 logic.
- **§6.1a layer 3** (descriptor continuity re-match) — a different mechanism against
  mid-episode ID switch, still its own slice.

---

## 8. Testing

- **Pure — `keyframes.interpolate`.** Whole-object assert: two marks
  (`t=0 x=100`, `t=1 x=200`) at `fps=10`, `dur=1` → 11 points, `x` stepping 100→200 by
  10, `y/w/h` interpolated likewise. One mark → constant hold. Zero marks → `ValueError`.
  Out-of-range / non-increasing `t` → `ValueError`.
- **Pure-ish — `flow.build_route`** on a synthetic moving-blob clip (a bright square
  translating across a dark frame, written with cv2 or ffmpeg): the route's `x` tracks
  the blob left→right. Real cv2, no mock.
- **Pure — `orchestration.flow_eligible`** decision table: `(pinned, empty)` →
  `{(F,T):True, (T,T):False, (F,F):False, (T,F):False}`.
- **Integration, real ffmpeg — the rung-1→2 trigger with real pixels.** `sample_clip`
  is a box, not a person, so YOLO-seg detects nobody → empty route → the exact
  `empty AND unpinned` trigger, with **no new person fixture**. Assert: `report["degraded"]`
  is `"flow"` (or, if the sample box is static and gives flow no motion, `"manual"` via
  a supplied `keyframes.json`; the plan confirms whether `sample_clip`'s box moves and,
  if static, adds a minimal moving-blob clip using the `testsrc2`-crop-offset trick from
  `test_stabilize.py`). A second case supplies `keyframes.json` and asserts
  `degraded="manual"` and a `mechanical_pass`.

---

## 9. Doc sync

- **Design spec §6.1** — the degradation-ladder paragraph gains a "built 2026-07-21"
  note and the honest amendment: auto-fall on *empty*, not on *garbage* (§1), and
  optical-flow is identity-blind so pinned heroes never reach it (§1.1).
- **§12 landmine registry** — the wade-in-plus-optical-flow line (§7).
- **`docs/build-status.md`** and **`docs/pipeline-map.md`** — flip the
  tracking-degradation ladder from unbuilt to built; the `"degraded": None` placeholder
  is now fed.
- **`CLAUDE.md`** Quick Reference — a row for this design + its plan.
