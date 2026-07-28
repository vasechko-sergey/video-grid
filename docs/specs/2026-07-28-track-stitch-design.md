# Track ID-switch stitching — design (§6.1a)

**Goal:** when ByteTrack drops the hero through an occlusion and re-acquires it
under a new track id, splice the two ids back into ONE route so the crop keeps
following the subject instead of freezing on the last position of the truncated
id.

**Status:** landing the parked hot-patch from the first real montage run
(`wip/montage-run-hardening`, commit `4841dd3`) through the design → plan →
TDD-review cycle it skipped. The code ran green on that 99-clip run but never went
through review. This is the "track.py stitch → its own slice" bucket of the park —
landed 2026-07-28 (feat/track-stitch).

---

## 1. Why — the frozen crop

`build_route` builds the route from ONE track id (the hero). ByteTrack routinely
loses a subject through spray, a passing foreground object, or a frame the
detector misses, then re-acquires the same person under a fresh id. The route,
keyed to the original id, simply ends at the switch — and `reframe` then holds
the last crop position for the entire remainder of the shot.

Measured on the run: a 9.14 s drone ride where the hero track ended at 3.04 s and
the crop sat frozen for the other 6.10 s while the rider carried on to the frame
edge. That is not the single-frame gap the path smoother bridges — it is 67 % of
the shot delivered uncomposed.

The existing route loop already refuses the obvious wrong fix — a
"largest-in-frame" fallback — because that splices *strangers'* coordinates into
the route (false teleports the continuity check would then have to explain).
Stitching is the correct fix: extend the route only with ids that pass a
continuity test **against the hero's own trajectory**, which is the opposite of
picking whoever is biggest this frame.

## 2. Scope

**Port + provenance.** A faithful port of the parked `stitch_ids` and its helpers,
the route-loop change that consumes them, and the parked unit tests — **plus** one
addition: the route-altering decision records provenance in `TrackMeta`, matching
the repo convention where every route/pixel decision leaves a bit
(`PathMeta.pan` / `PathMeta.stabilized` / `PathMeta.background` /
`TrackMeta.degraded`).

**Not in scope:** a `check_episode` / `check_reel` surface that reads the
provenance (nothing consumes it as a gate — it is observability for a human
reading the sidecar and for debugging). Deferred, likely YAGNI (§8).

**Boundary:** the four functions live in `track.py`, beside the existing pure
track-analysis helpers (`_seed_track` / `_pick_hero` / `_track_features`), sharing
the `_Frame` type. They are pure, but they have a single consumer (`build_route`),
so they do not warrant a new `lib/` module — the repo extracts to `lib/` when a
pure unit has *multiple* consumers or a driver/pure split (`carve` → intake +
edit_plan; `color` → reframe + check + measure). One consumer stays put.

## 3. The stitch core

Four functions in `track.py` (plus the route-loop change in `build_route`, §5):

- `_segments(per_frame) -> dict[int, dict]` — per track id: first/last frame
  index, the bbox at each end (`head` / `tail`), frame count `n`, and an
  `at: {frame_idx: x}` map. The `at` map is what lets two OVERLAPPING segments be
  compared on the frames they share.
- `_median(xs) -> float` — plain median (no numpy in this pure core).
- `_joinable(a, b, gap, speed, src_w) -> bool` — is `b` the same subject as `a`,
  resuming `gap` frames later (§4)? `a` always precedes `b` in time.
- `stitch_ids(per_frame, hero_id, fps, src_w, feats) -> set[int]` — the hero id
  plus every id that is the hero re-acquired after a switch. Chains **forward and
  backward** from the hero, one hop at a time, so a subject dropped twice is
  followed twice; each candidate is judged against the segment it would attach to
  (`cur`), never against the original hero, because a real subject drifts across a
  shot. Nearest-in-time candidate wins; ties break on the lower id (deterministic).

**Thresholds** — ported verbatim, every one **measured** on the run (there is no
synthetic footage to tune against, so these are field values, not guesses):

| Constant | Value | Meaning |
|---|---|---|
| `STITCH_MAX_GAP_S` | 0.40 | a re-acquisition later than this is not a blink |
| `STITCH_MAX_OVERLAP_S` | 0.50 | a handover may also OVERLAP — ByteTrack confirms the new id before dropping the old (measured overlaps 2–29 frames) |
| `STITCH_MIN_FRAMES` | 5 | below this a "track" is detector noise, not a subject |
| `STITCH_SPEED_SLACK` | 3.0 | travel allowed = hero mean speed × gap × this |
| `STITCH_MIN_JUMP_FRAC` | 0.02 | …but never less than 2 % of frame width (a slow hero) |
| `STITCH_AREA_RATIO` | 2.5 | apparent size may not change by more than this factor |

The thresholds are deliberately **tight**: stitching too eagerly fails far worse
than not stitching. Splicing a stranger onto the hero's route teleports the crop
mid-shot and reads as a hard cut; an unstitched route is merely a frozen crop the
report already shows. A candidate must resume within a blink, from about where the
hero left off, at about the size the hero had.

## 4. Two regimes — different evidence

`_joinable` branches on whether the two segments share any frames, because the two
cases have different evidence available:

- **OVERLAP** (`shared` frames exist): ask the question directly — how far apart
  are the two boxes ON THE FRAMES THEY BOTH EXIST? The same rider handed between
  two ids sits a few px apart on every shared frame; two different surfers stay
  apart on all of them. `median(|a.x[i] − b.x[i]| for shared i) ≤ reach`. This is
  strictly stronger than any endpoint comparison, so it is used **alone** — the
  box-area gate is skipped, because a dying track's last boxes are degrading (that
  degradation is usually *why* it died), and comparing them against a fresh
  track's first boxes reads a healthy handover as a size change. Measured: a
  detector box collapsing 104×207 → 70×116 through spray, 3 px away, is one rider.
- **GAP** (nothing shared): fall back to the endpoints — the jump `|b.head.x −
  a.tail.x|` must fit the hero's own speed (`reach`), AND the box must be in the
  same size class (`1/RATIO ≤ area_b/area_a ≤ RATIO`, the distant-bystander guard).

`reach = max(STITCH_MIN_JUMP_FRAC · src_w, speed · max(1, |gap|) · STITCH_SPEED_SLACK)`.

## 5. Integration + the one deviation from the park

The parked patch called `stitch_ids` down at the route loop, *after* the
`TrackMeta` sidecar was already written. To carry provenance (§6), this slice
moves the call **before** the `TrackMeta` construction — all of its inputs
(`hero_id`, `feats`, `per_frame`, `src_w`, `fps`) are already computed by that
point, so the move is free.

```
hero_id, ambiguous, pin_matched = … (unchanged)
hero_ids = stitch_ids(per_frame, hero_id, fps, src_w, feats)   # NEW, before meta
stitched = sorted(hero_ids - {hero_id})                        # provenance
meta = TrackMeta(…, stitched=stitched)                         # carries it
… write sidecar …
for idx, dets in per_frame:
    matches = [d for d in dets if d[0] in hero_ids]
    if len(matches) > 1 and route:
        matches.sort(key=lambda d: abs(d[1] - route[-1].x))    # nearer to route
    pick = matches[0] if matches else None
    …
```

The route loop's overlap handling matters: during a handover BOTH the outgoing and
incoming id report the same person from slightly different boxes for a few frames.
Taking whichever comes first in detection order would flip between them and write a
small teleport into the route at the exact moment the crop is meant to be
continuous — so it follows the one **nearer to where the route already is**.

**Compatibility (verified against current `track.py`):** the integration point is
intact — `feats[hero_id]["speed"]` exists (`_track_features`), and the production
caller (`process_episode`) builds `TrackSpec` **without** `fps`, so `build_route`
probes and `src_w` IS populated — stitch fires in production. The `src_w is None`
branch (returns `{hero_id}`, no stitch) is a guard for a hypothetical fps-supplying
caller that skips the probe, not a production path. `stitch_ids` is orthogonal to
`TrackMeta.degraded`: `degraded` is set by the orchestration ladder (flow / manual
rungs) in `process_episode`, never by the base tracker; stitch runs inside
`build_route` (rung 1, YOLO) only. `flow` and `manual` routes have no track ids to
stitch, so stitching is rung-1 by nature.

`hero_id is None` (nobody picked) → `stitch_ids` returns `set()` → the route loop
picks nothing → empty route → the ladder's unpinned-empty trigger, exactly as
today. Stitch never resurrects a fallback hero.

## 6. Provenance contract

`TrackMeta.stitched: list[int]` — the ids merged onto the route **beyond** the
hero (`sorted(hero_ids − {hero_id})`), `[]` when the route is a clean single id.

- Default `field(default_factory=list)`.
- `to_dict`: `"stitched": self.stitched`.
- `from_dict`: `d.get("stitched", [])` (back-compatible with sidecars written
  before this slice).
- Written to the `<out>.meta.json` sidecar with the rest of `TrackMeta`.
- **No consumer gate.** Observability only — a human reading the sidecar sees
  "hero 1 was extended with [66, 91]"; nothing branches on it.

## 7. Testing

**Unit (`tests/lib/test_track.py`, adopt the parked +125 and extend):**
- `_segments` — head/tail/`at`/`n` over a hand-built `per_frame`.
- `_median` — even/odd.
- `_joinable` OVERLAP — same-subject boxes a few px apart on shared frames join;
  the area gate is NOT applied in the overlap regime (a collapsing box still
  joins).
- `_joinable` GAP — a jump within `reach` + same size class joins; a jump beyond
  `reach` refuses; a same-position box of a wildly different size (distant
  bystander) refuses on the area gate.
- `stitch_ids` — forward chain, backward chain, a subject dropped twice (two
  hops); a bystander whose track brackets the hero on both sides is refused (must
  EXTEND coverage, not sit inside it); `hero_id is None` → `set()`; `src_w is
  None` → `{hero_id}`; a track shorter than `STITCH_MIN_FRAMES` is ignored.
- Route loop — a synthetic `per_frame` with a simulated overlap switch: the route
  picks the match nearer the current route position (not detection order);
  `TrackMeta.stitched` records the merged ids and round-trips through
  `to_dict`/`from_dict`; a clean single-id `per_frame` → `stitched == []`.

**Integration (faked-detector harness, `tests/integration/test_track.py`):**
`build_route` is driven with the established `_FakeBox` / `_fake_iter` fake
detector (plus a monkeypatched `_probe_meta` for the probe path) — no real ffmpeg
/ YOLO, the convention every track test follows. A staged overlap switch proves
the wiring: the route builds, `meta.stitched` records the merged id, the route
follows past the outgoing id's end (no freeze), the overlap pick follows the
route-nearest box (not detection order), a clean single-id stream yields
`stitched == []`, and an fps-supplied spec (`src_w` None) does NOT stitch — the
anti-regression guard.

**Honest limitation (not tested end-to-end):** deterministically staging a REAL
ByteTrack ID switch is expensive and flaky — it needs real occlusion behaviour on
real pixels. The unit tests cover the stitch logic over synthetic `per_frame`
lists (where a switch is trivially constructed) and the integration tests prove
the `build_route` wiring over a faked detector; "a real switch, bridged,
delivered" over real YOLO is not a test this slice adds.

## 8. Non-goals / deferred

- **A check surface** reading `TrackMeta.stitched` — no gate consumes it; adding a
  `check_*` signal is deferred (YAGNI).
- **Stitching a `None` hero** — refused by construction (§5); guessing an anchor
  would resurrect the largest-in-frame fallback `build_route` deletes.
- **Stitching `flow` / `manual` routes** — they have no track ids; stitch is
  rung-1 (YOLO) only.
- **Tuning the thresholds** — they are field-measured; there is no synthetic
  footage to re-tune against, and loosening them trades a frozen crop (visible in
  the report) for a stranger teleport (reads as a cut). Kept tight.

## 9. Module / file map

| File | Change |
|---|---|
| `scripts/track.py` | +`STITCH_*` constants, `_segments`, `_median`, `_joinable`, `stitch_ids`; `build_route` calls `stitch_ids` before `TrackMeta`, records `stitched`, route loop picks the route-nearer overlap match |
| `scripts/lib/models.py` | `TrackMeta.stitched: list[int]` + `to_dict` / `from_dict` |
| `tests/lib/test_track.py` | the parked unit battery + provenance/round-trip + route-loop tests |
| `tests/integration/test_track.py` | faked-detector `build_route` integration — stitch + provenance + route-nearest pick + `src_w` guard |
| docs | this spec, the plan, build-status, pipeline-map, CLAUDE registry |

## 10. Landmine

Stitching is a silent-corruption risk of exactly the §12 kind if loosened: a
mis-stitch does not crash — it writes a stranger's coordinates into the route, and
the continuity check then confirms a smooth crop that is following the wrong
person. The defence is the tight, measured thresholds and the "must extend
coverage" guard, not a runtime assertion. Documented here so a future loosening is
a deliberate decision, not an accident.
