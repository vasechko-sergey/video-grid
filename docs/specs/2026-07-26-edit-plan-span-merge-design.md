# Edit-plan span merge (feedback #3, slice 3b) — design

Slice 3a (2026-07-25 activity-units) replaced equal-interval carving with
activity-anchored units: intake now emits units that are each an activity peak
plus its lead-in. It **deferred** the other half of feedback #3 to its own slice
(3a design §0, §9):

> **3b: `edit_plan` gains `span [i..j]`** — an episode that merges several
> adjacent units plus the connective footage between them ("turn + drive + turn"
> → one episode).

This design is 3b. It lets one EDL episode reference a **range** of adjacent
footage windows instead of a single window, and projects that range onto one
continuous episode spanning from the first window's start to the last window's
end — carrying the connective footage between them.

Companion to the edit-plan spine design
([2026-07-12-edit-plan-spine-design.md](2026-07-12-edit-plan-spine-design.md),
stage 5.7), whose `selection.json → window_to_episode → EDL` projection this
slice extends, and to the 3a design
([2026-07-25-intake-activity-units-design.md](2026-07-25-intake-activity-units-design.md)),
whose §9 invariant ("units never cross a scene cut") is what makes 3b cheap.

---

## 0. Why 3b is thin

The single fact 3a promised to preserve makes the merge validation **already
written**: a scene cut is a span boundary at carve time, so every window lives
strictly inside one continuous shot, and `FootageClip.room_after(start)` already
returns the seconds available before the next scene cut. A merge that would
straddle a scene cut therefore fails the *existing* `room_after` check in
`window_to_episode` — 3b adds no new geometric rule, only a clearer message.

The merge is expressed as **one synthesized `FootageWindow`** covering the range,
fed to the **unchanged** `window_to_episode`. So:

- No `EDLEpisode`/`EDL` contract change — a merged episode is an ordinary episode
  with a longer `dur`.
- No intake / `footage.py` / `intake_cache.py` change — 3a already added
  `track_ids` (which the merge unions) and the no-scene-cut invariant.
- No pacing change — scenario-first `fit_spine` (2026-07-24) already fits the
  music to whatever length each episode has; a merged episode is just longer.

3b touches **`scripts/edit_plan.py`** (the projection), the **`edit-plan`
SKILL** (authoring guidance), and docs. Nothing else.

## Scope decisions (locked in brainstorming)

- **The `window` reference is overloaded, not a new key.** A `selection.json`
  episode's `window` field accepts an integer (one window, unchanged) **or** a
  two-element list `[i, j]` (merge windows `i..j`). One reference point into the
  footage, minimal API surface.
- **The merge reuses `window_to_episode` + `room_after`.** A pure
  `_merge_windows(clip, i, j)` builds one `FootageWindow` covering the range; the
  existing projection does the rest, including the scene-cut refusal. No second
  validation site for "may this cut exist here" — `room_after` is the single
  authority, as 3a promised.
- **No float transcription.** `start`/`dur` of the merged window come from the
  windows in `FOOTAGE.json` by reference (`min` start, `max` end), never retyped —
  the same silent-wrong-cut guard the single-window path already gives (montage
  §12).
- **The merged episode carries no provenance in the contract.** `EDL.md` shows
  the real merged `start–end (dur)` (honest — that is the cut). Which windows were
  merged is recorded in `selection.json` itself, the generated-not-hand-edited
  source. Threading a window-range into `EDLEpisode` would be contract weight for
  a human-map nicety; out of scope.

## 1. Goal & data flow

```
FOOTAGE.json (5.2/3a: activity-unit windows, each inside one shot) ─┐
project.json ──────────────────────────────────────────────────────┤  agent reads
                          │
               edit-plan SKILL  (authoring by judgment)
                          │  writes
                          ▼
   selection.json   episode.window is an int (one window)  OR  [i, j] (merge i..j)
                          │
   edit_plan.py build ────┤  int  → window_to_episode(clip, clip.windows[w])
                          │  list → _merge_windows(clip, i, j) → window_to_episode(clip, merged)
                          ▼
                    EDL.json  +  EDL.md      (merged episode = one longer EDLEpisode)
                          │
          (existing SP1)  edl_to_reel ──► REEL_v1.mp4
```

A merged episode is one continuous segment `[min start … max end]` over the
range — the same shape the reel back half already consumes for any episode. The
"drive between" the two peaks is simply the footage that lies between the windows
inside the same shot; it rides along because the segment spans the whole range.

## 2. `selection.json` — the `window` overload

Today an episode references one window:

```json
{"source": "MVI_3739.mp4", "window": 2, "composition": "lead", "grid": "thirds"}
```

3b adds the span form — the value becomes a two-element list:

```json
{"source": "MVI_3739.mp4", "window": [2, 4], "composition": "lead", "grid": "thirds"}
```

`window: [2, 4]` means "one episode from the start of window 2 to the end of
window 4, including windows 3 and the footage between." Editorial fields
(`composition`/`grid`/`layout`/`motion`/`hero`/…) and `start_offset` apply to the
merged episode exactly as to a single-window episode. Everything else in
`selection.json` (the `episodes` list, top-level `music`/`cap`/`target_dur`)
is unchanged.

## 3. The merge — `_merge_windows(clip, i, j) -> FootageWindow`

A new pure helper in `scripts/edit_plan.py`, beside `window_to_episode` (all
"window → episode" projection lives in one file). It assumes `0 <= i < j <
len(clip.windows)` (validated by the caller, §4) and builds the envelope:

```python
_MERGE_TOL = 1e-3   # s: FOOTAGE rounds start and dur independently, so a merged envelope end can
                    # sit up to ~1ms past its true cut/clip-end boundary; tolerate + clamp that slop.


def _merge_windows(clip: FootageClip, i: int, j: int) -> FootageWindow:
    wins = clip.windows[i:j + 1]
    start = min(w.start for w in wins)
    end = max(w.start + w.dur for w in wins)
    tids = sorted({t for w in wins for t in w.track_ids})
    room = clip.room_after(start)
    if end - start > room + _MERGE_TOL:
        inside = [c for c in clip.scene_cuts if start < c < end]
        if inside:
            raise ValueError(
                f"_merge_windows: span [{i}, {j}] runs {end - start:.2f}s from {start:.2f}s in "
                f"{clip.source}, but a scene cut at {min(inside):.2f}s lies inside it — a span cannot "
                f"cross a scene cut (it would splice two shots into one episode). Split it into two "
                f"episodes, one on each side of the cut")
        raise ValueError(
            f"_merge_windows: span [{i}, {j}] envelope ends at {end:.2f}s, past the end of "
            f"{clip.source} ({clip.dur:.2f}s) — the last window extends beyond the clip; re-run "
            f"footage-intake to regenerate FOOTAGE.json")
    return dataclasses.replace(clip.windows[i], start=start,
                               dur=min(end - start, room), track_ids=tids)
```

- **`start`/`dur`** — `min` start, `max` end over the range; `dur = end - start`
  is guaranteed positive (`j > i`, every window has `dur > 0`). `dur` is clamped to
  `room` (`min(end - start, room)`) so a sub-`_MERGE_TOL` rounding overshoot lands
  exactly on the boundary rather than ~1ms past it.
- **`track_ids`** — the union across the range (§5 of 3a: who is in the unit),
  so the merged episode annotates everyone who appears across the whole arc.
- **`shot_type` / `description`** — inherited from window `i` (via
  `dataclasses.replace`), the seed defaults `window_to_episode` reads; an
  editorial `shot_type`/`processing_notes` still overrides. A merged span may
  change shot scale mid-arc, but an episode carries one advisory `shot_type` tag;
  window `i`'s is the honest default (the arc's opening), and the agent overrides
  when the merge warrants it.
- **`people`/`motion`/`shake`/`score`/`best`** — inherited from window `i` and
  never read by the projection; they exist only to satisfy
  `FootageWindow.__post_init__` (which `replace` re-runs).

**Scene-cut refusal.** The `room_after` check is the same rule
`window_to_episode` applies; naming the offending cut here gives a
span-specific fail-loud message (the single-window path's message speaks of a
`start_offset`, which a span rarely uses). `window_to_episode` re-checks
`room_after` after applying any `start_offset` — a backstop for the rare
span+offset case, not a second authority. Crossing a **presence transition**
inside one shot is *allowed*: `scene_cuts` holds only real cuts, so
`room_after` stops only at cuts — which is exactly the "turn → drive → turn"
case (the drive is people-less, a presence transition, not a cut).

**Rounding tolerance (why `_MERGE_TOL`).** `FOOTAGE.json` stores `round(start, 3)`
and `round(dur, 3)` **independently**, so a window's reconstructed `start + dur`
can land up to ~1ms past its true boundary — the clip end, or a scene cut a span
ends on. That is intake's own output, not corruption, and a span whose arc ends on
a cut or the clip end is exactly the natural case. So the refusal fires only when
the envelope overshoots `room` by **more than** `_MERGE_TOL`; a within-slop
overshoot is clamped to `room` (above) and accepted. Beyond the tolerance with **no
cut inside** the envelope, the last window genuinely lies past the clip — a corrupt
`FOOTAGE.json` — and the merge fails loud with the re-run remedy (never an empty
`min()` crash). This keeps `_merge_windows` fail-loud like `window_to_episode`
rather than crashing, while not falsely refusing a legitimate clip-end span.

## 4. `build_edl` wiring

The per-episode loop in `build_edl` gains a branch on the type of `window`. The
source→clip resolution is unchanged and happens first (a clip is needed to
bounds-check either form). Then:

```python
if isinstance(window, list):
    if len(window) != 2 or any(isinstance(v, bool) or not isinstance(v, int) for v in window):
        raise ValueError(f"selection episode {k}: a span 'window' must be [i, j] — two "
                         f"integer indices, got {window!r}")
    i, jj = window
    if not (0 <= i < jj < len(clip.windows)):
        raise ValueError(f"selection episode {k}: span window {window} is out of range for "
                         f"{source} (need 0 <= i < j < {len(clip.windows)}; for a single "
                         f'window use "window": i)')
    fw = _merge_windows(clip, i, jj)
elif isinstance(window, bool) or not isinstance(window, int):
    raise ValueError(f"selection episode {k}: 'window' must be an integer index or a "
                     f"[i, j] span into FOOTAGE")
else:
    if not 0 <= window < len(clip.windows):
        raise ValueError(f"selection episode {k}: window {window} out of range for {source} "
                         f"(has {len(clip.windows)})")
    fw = clip.windows[window]
episodes.append(window_to_episode(clip, fw, start_offset=start_offset, **ed))
```

- `i < jj` **strict** — `i == j` is refused with the "use a single window" remedy
  (a one-window "span" is just a window), and `j < i` (a typo) is refused the same
  way. `len != 2` and non-int / bool elements are refused before indexing.
- The single-window path is byte-for-byte the current behaviour (its bounds check
  and error string are unchanged), so every existing `build_edl` test stays green.
- `window` defaulting to `None` (missing) still falls into the
  `not isinstance(window, int)` arm and raises — unchanged.

## 5. What does not change (and why it just works)

- **Pacing.** `_bind_pacing`/`_back_edge_target` operate on episode `dur`s; a
  merged episode simply has a larger `dur`. Scenario-first pacing fits the grid
  to the episodes (music cut to the reel, 2026-07-24), so a longer merged episode
  widens its slot, it does not truncate — the very thing the 2/4/8 ladder used to
  do. No pacing code changes.
- **`EDL` / `EDLEpisode`.** No new field. A merged episode is an ordinary
  `EDLEpisode`; `EDL.to_markdown` renders its merged `start–end (dur)` in the
  `window` column. `edl_to_reel`, `preflight`, `check_reel`, the `path.meta`
  sidecar — all consume it as any other episode (one route over one segment).
- **`FootageWindow` / intake / cache.** Untouched; 3b only *reads* `track_ids`
  and `start`/`dur`.

## 6. SKILL (`skills/edit-plan/SKILL.md`)

The authoring guidance gains the span move: when adjacent windows form **one
arc** — an approach into an action, or "turn → drive → turn" — reference them as
a span `[i, j]` in a single episode, rather than emitting separate episodes for
each. One continuous segment reads as one beat and lets the music fall on its
true length; separate episodes would hard-cut between windows that are really one
motion. Constraints to state: a span is within **one clip**, its windows must be
**adjacent indices**, and it **cannot cross a scene cut** (the build refuses it
with the cut named). The SKILL already teaches `start_offset` as the in-point
fine-tune; span is its companion for the out-point / length.

## 7. Testing

- **`tests/lib/test_edit_plan.py`** (extend; fake `Footage`/`FootageClip`, no
  ffmpeg):
  - `_merge_windows` envelope — two adjacent windows → `start = min`,
    `dur = max_end − min_start`, `track_ids` = the sorted union; a middle window's
    footage is inside the span (`dur` covers the gap between non-touching
    windows).
  - `_merge_windows` scene-cut refusal — a range whose envelope contains a
    `scene_cut` → `ValueError` naming the cut; a range that crosses only a
    presence transition (no cut in `scene_cuts`) → **succeeds**.
  - `_merge_windows` inheritance — `shot_type`/`description` come from window `i`;
    an editorial `shot_type`/`processing_notes` on the episode overrides.
  - `build_edl` span path — `window: [i, j]` yields one `EDLEpisode` with the
    merged `dur`; editorial fields forwarded; the merged episode round-trips
    through `EDL.to_dict`.
  - `build_edl` span validation — `j < i`, `i == j`, out-of-range `j`, a
    three-element list, a non-int / bool element → `ValueError` each, naming
    episode `k`.
  - Regression — the single-window path (`window: 2`) is unchanged.
- **`tests/integration/test_edit_plan.py`** (extend the real-ffmpeg SP3→SP1
  golden): the hand-written `FOOTAGE.json` gains a clip with ≥2 adjacent windows
  inside one shot (no scene cut between); `selection.json` references them as
  `window: [i, j]`; assert the built `EDL.json` has one episode whose `dur` is the
  envelope, then feed the `EDL.json` to `edl_to_reel` on the synthesized source
  and assert `status == "delivered"` and `REEL_v1.mp4` exists. Proves a span
  survives the whole SP3→SP1 seam.

## 8. Landmines (montage §12)

- **No float transcription** — the merged `start`/`dur` are `min`/`max` over the
  windows' own values, read by reference; `selection.json` holds only the integer
  pair `[i, j]`. A retyped timestamp remains structurally impossible.
- **Scene-cut refusal is fail-loud with the cut named** — a span that would
  splice two shots dies in `build_edl` (milliseconds, before any ffmpeg) with the
  offending cut and a split remedy, not a silent mid-episode hard cut.
- **`room_after` stays the single geometric authority** — `_merge_windows` calls
  it rather than re-deriving "is a cut in this range"; the message is new, the
  rule is not.
- **Generated, not hand-edited** — `EDL.json` is regenerated from
  `selection.json`; the span lives in the source, so an edit re-runs the build
  rather than hand-patching a longer `dur` into the EDL.

## 9. Non-goals

- **No cross-clip merge.** A span is within one clip; two clips are two episodes
  (an episode is one continuous source segment). Adjacency is by window index
  within one `FootageClip.windows`.
- **No overlap-into-one across a scene cut.** Refused by construction (§3). A
  cut means two shots; merging across it is a cross-fade / two episodes, not this.
- **No auto-merge / merge suggestion in Python.** *Which* windows form an arc is
  editorial judgment (the SKILL's job), exactly like *which* windows to pick was
  in 5.7. `edit_plan.py` stays the thin mechanical half.
- **No provenance field on `EDLEpisode`.** `selection.json` is the record of what
  was merged (§0).
