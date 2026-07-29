# Reframe path-quality cluster — design (smoothing window · jitter check · lead-from-travel)

**Goal:** land the three coupled path-quality fixes the first real montage run
wrote live, so the crop is smoothed by a window that means the same thing at any
frame rate (**A**), the jitter check judges the crop against the subject it is
following instead of in a vacuum (**B**), and an authored `lead` composition is
honoured — not silently swapped to `center` — when the tracker lands in its
ambiguous zone (**C**).

**Status:** landing the parked hot-patch from the first real montage run
(`wip/montage-run-hardening`, commit `4841dd3`) through the design → plan →
TDD-review cycle it skipped. This is the "pathsmooth smooth_window_s → its own
slice" bucket of the park. The code ran green on that 99-clip run (1697 passed)
but never went through review; track-stitch — the sibling bucket of the same
park — proved that live-written code hides coverage holes that only mutation
testing surfaces, so this slice treats the port as *unverified* until the guards
have teeth — landed 2026-07-29 (feat/path-quality).

**Scope decision:** the parked bucket is three concerns that arrived together —
A (`smooth_window_s`), B (route-aware jitter), C (lead-from-travel). They land as
**one slice**: A and B are a matched pair (the knob is tuned against the check),
and C shares the same `reframe`→`check_episode`/`motion`/`orchestration` surface
and is too small to warrant its own full cycle. This matches the campaign's
"pathsmooth smooth_window_s" slot exactly.

---

## 1. Why — three defects from the montage run

### A. The smoothing window is specified in frames, but it is a filter cutoff

`pathsmooth.smooth` low-pass-filters the raw crop-x path with a Savitzky-Golay
window. The window governs the filter's **cutoff frequency**, so it has to be
expressed in **time**, not frames. `DEFAULT_WINDOW = 7` was tuned on 30 fps
footage, where it spans 0.23 s. Handed unchanged to a 60 fps source — the regime
this repo's drone and telephoto footage actually lives in — 7 frames spans
0.12 s and filters half as much motion.

Measured across four 60 fps rides: 7 frames left the crop's 2nd difference at
2–4× the integer-crop floor and one episode failed the jitter check outright. The
same 0.25 s expressed as 15 frames put all four on the floor, for 1–3 % of crop
width in added lag. The fix is to ask for the window **in seconds** and resolve
it against the clip's own fps at render time.

### B. The jitter check scores an unsmoothed, juddering crop *best*

`checks.jitter` measures crop-centre reversal against the direction of travel —
the §9 "rounding flicker" guard. It is the only composition check that judges the
path **in a vacuum**: `centered`/`on_line` both score the path *against the route*,
but `jitter` looks at the path alone. Two consequences, both measured on the run:

1. **It cannot tell chatter from following.** A crop faithfully following a surfer
   who carves back up the wave reverses because the *subject* did; judged in a
   vacuum that reads identical to a crop hitching over a subject who glides
   straight on. A noiseless route weaving ±150 px scored `worst = 6` while
   `on_line` was still 0.919 — the framing was correct and the jitter check
   called it broken.

2. **It scores the *worse* path better.** A raw route carries per-frame bbox noise
   of the same amplitude as the defect. Subtracting that route frame-to-frame
   cancels perfectly for a path that *copies* the noise (a visibly juddering crop)
   and not at all for a path that *filters* it (the smooth crop). Measured on a
   60 fps drone ride: the raw path (2nd-difference p95 = 8.9 output px — the
   judder you can see) scored `worst_reversal` 0.94 and **passed**, while a
   smoothed path at the 1-px quantization floor scored 4.00 and **failed**.

This is a §12-class silent corruption: a check that passes bad pixels and fails
good ones is worse than no check. B is also **load-bearing for A** — widening the
smoothing window (A's whole retry mechanism) is only safe once the check filters
the route it scores against, or a wider window would score *worse*.

### C. An authored `lead` is silently rendered as `center`

`motion.classify` answers "what kind of shot is this" and deliberately falls
through to `static` in its **ambiguous zone**: a subject that both crosses the
frame (large |dx|) *and* grows toward the camera (large area growth) — a surfer
riding across the frame and toward a beach-side telephoto. Measured on one such
shot: dx was 30 % of frame width (lateral needs 15 %) and the box grew 3.1×
(head-on needs 1.6×), so the shot was called `static` and an authored `lead`
composition rendered as a centred crop, with nothing in the report saying so.

Picking a safe default (`center`) for an *unstated* intent is correct; quietly
substituting a different composition for a *stated* one is the silent-swap class
this repo refuses everywhere else. The fix honours the request and takes the lead
direction from the route's own net travel — the one thing the ambiguous zone
never made ambiguous (it enters that zone only when |dx| is large).

---

## 2. Scope

A faithful port of the parked hunks onto current `main`, with the colour half of
the same park excluded because it already landed in slice F (colour-as-a-stage).
The parked `reframe.py` and `check_episode.py` diffs interleave colour and
path-quality edits against a pre-slice-F parent; this slice takes **only** the
path-quality edits and grafts them onto the post-slice-F files.

**In scope:** the three units A, B, C of §1, across `pathsmooth`, `models`,
`orchestration`, `motion`, `checks`, `reframe`, `check_episode`,
`process_episode`, plus their tests.

**Out of scope / non-goals:**

- **No provenance field.** track-stitch added `TrackMeta.stitched` because it
  marks a rare, discrete corrective event. The smoothing window is *always*
  present on every tracked path — it is a render parameter like `max_speed`,
  which is deliberately **not** recorded in `PathMeta`. Recording the resolved
  window would be dead weight with no consumer (`check_episode` derives its own
  `route_window` from the route's cadence, not from reframe's window). No
  `PathMeta` change.
- **No threshold re-derivation.** Every constant here (`DEFAULT_WINDOW_S = 0.25`,
  `SMOOTH_WINDOW_S_MAX = 0.7`, `ROUTE_SMOOTH_S = 0.08`, the ×2/÷2 ladder factors)
  is field-measured on the run. They are ported verbatim.
- **No re-render provenance for the pan branch.** `smooth_window_s` is never read
  on a generated pan (§4.4).

---

## 3. The three units

### A — the window in seconds

**`scripts/lib/pathsmooth.py`**

- `DEFAULT_WINDOW = 7` — the pure function's own frame fallback (direct callers /
  tests that pass frames).
- `DEFAULT_WINDOW_S = 0.25` — the width callers should ask for, in seconds. Chosen
  so a 30 fps clip resolves to exactly 7 — the historical value preserved where it
  came from, and only the frame rates it was never tuned for change.
- `window_frames(seconds, fps) -> int` — an odd Savitzky-Golay window spanning
  `seconds` at `fps`. `round(seconds*fps)`, rounded **down** to odd (0.25 s at
  30 fps is 7.5 → 7, the historical default, not 9), clamped to `max(5, n)` because
  savgol needs `window > polyorder` (2). Raises `ValueError` on `fps <= 0` (a
  window in seconds cannot be converted without one) and on `seconds <= 0` (pass
  `window=1` to `smooth()` to skip savgol entirely).
- `smooth(..., window: int | None = DEFAULT_WINDOW, ...)` — the literal `7` default
  becomes the named constant. No behaviour change.

**`scripts/lib/models.py` — `ReframeSpec`**

- `smooth_window_s: float = 0.25` — savgol span over the tracked path, in seconds.
  Not interchangeable with `max_speed`: `max_speed` caps how *far* the crop may
  move per frame, `smooth_window_s` sets over how *long* a wobble is averaged
  away. A low-amplitude, high-frequency hitch (the jitter check's whole subject)
  already sits under any `max_speed` the ladder reaches, so damping speed cannot
  touch it.
- Validation: a real number in `(0, 2.0]` (a filter cutoff; a window longer than a
  couple of seconds stops following the subject rather than smoothing it),
  `bool` rejected. Default 0.25 keeps every episode authored before this field
  byte-identical.
- `ReframeSpec` is constructed, not JSON-round-tripped, so no `from_dict`/`to_dict`
  change.

**`scripts/lib/orchestration.py` — the retry ladder**

- `DEFAULT_PARAMS` gains `"smooth_window_s": 0.25` alongside `"max_speed": 750.0`.
- `SMOOTH_WINDOW_S_MAX = 0.7` — past this the crop stops following the subject at
  all and lags visibly through a real direction change.
- `adjust_reframe_params` fills a partial `params` from `DEFAULT_PARAMS` first
  (`p = {**DEFAULT_PARAMS, **params}`), so a caller that knows only `max_speed`
  gets a complete, nudgeable set back rather than a `KeyError`.
  - **jitter fail** → `smooth_window_s = min(SMOOTH_WINDOW_S_MAX, s * 2)`. This is
    the knob that actually reaches this failure: `max_speed` caps step *size*, but
    the jitter check fires on low-amplitude reversals far under any speed cap the
    ladder reaches, so speed alone never converges (measured: 750→450→270 px/s
    left `worst_reversal` unchanged at 4.0 px). The existing `max_speed *= 0.6`
    stays.
  - **line-lag fail** (`on_line`/`centered`) → `smooth_window_s = max(DEFAULT, s / 2)`.
    A wide window is exactly what makes the crop lag, so give the responsiveness
    back the same way it was taken — never below the default. The existing
    `max_speed *= 1.5` stays.

**`scripts/reframe.py`**

- `compute_path(..., smooth_window: int = pathsmooth.DEFAULT_WINDOW)` — the new
  last parameter is threaded into `pathsmooth.smooth(raw, max_step=max_step,
  window=smooth_window)`. Default preserves current behaviour for direct callers.
- `reframe()` computes `pathsmooth.window_frames(spec.smooth_window_s, fps)` and
  passes it as `smooth_window` — the one place seconds become frames, at the one
  point that knows the clip's fps.

**`scripts/process_episode.py`**

- The `ReframeSpec` built inside the retry loop gains
  `smooth_window_s=float(params["smooth_window_s"])`. `params` starts from
  `DEFAULT_PARAMS` (so it carries the 0.25) and `adjust_reframe_params` tunes it
  each attempt — `smooth_window_s` is a **retry knob**, not an authored per-episode
  field (no manifest/EDL carrier).
- The `pan-not-retryable` comment is updated to name both knobs the ladder now
  tunes.

### B — route-aware jitter

**`scripts/lib/checks.py`**

- `_moving_average(xs, window) -> list[float]` — a centred box filter that shrinks
  at the ends so length is preserved. Pure — keeps `checks.py` free of scipy.
  `window <= 1` returns the input unchanged.
- `jitter(path, direction, max_reversal, route=None, route_window=1) -> dict`:
  - With `route`, the subject's own **negative** step is subtracted from each crop
    step before scoring (`step -= min(0.0, subj)`), forgiving only the reversal the
    subject actually performed — "following". A crop that chatters over a smooth
    subject still fails (the route contributes nothing to subtract); a crop that
    reverses further/faster than the subject still fails, by the excess.
  - `route_window` box-filters the route before differencing — the difference
    between measuring the **subject** and measuring the **detector** (§1.B.2).
  - Guard: `route` is used only when `bool(route) and len(route) >= len(path)`.
  - Returns `reversals` (count of steps below −1 px) alongside `pass` /
    `worst_reversal`. Diagnostic only — no consumer gates on it.
  - Validation: `route_window` must be an `int >= 1` (`bool` rejected).
  - `route=None`/`[]` keeps the exact historical vacuum-judged behaviour — a
    generated pan passes `None`.

**`scripts/check_episode.py`**

- `ROUTE_SMOOTH_S = 0.08` — the span over which a crop reversal becomes visible
  (~5 frames @ 60 fps).
- `_route_window(route) -> int` — frames spanning `ROUTE_SMOOTH_S` at the route's
  **own** cadence, derived from its timestamps (not an ffprobe fps: the route is
  what is being filtered, and a gappy or resampled one has a cadence of its own
  the container never states). `len(route) < 2` or non-positive span → 1 (the
  historical frame-to-frame behaviour, exactly right when there is nothing to
  filter).
- The `jitter` call passes `route=route or None, route_window=_route_window(route)`.
  Under a pan `route` is `[]`, so a generated path keeps the vacuum behaviour.

### C — lead-from-travel

**`scripts/lib/motion.py`**

- `travel_direction(route) -> str` — which way the subject **net** travels,
  whatever `classify` called the shot. `"right"` if `route[-1].x - route[0].x >= 0`
  else `"left"`; an empty/1-point route → `"right"` (matches `classify`'s own
  default, and the tracked check branch's default one arm down). **One spelling,
  two readers** — `reframe.compute_path` lays the crop out against it and
  `check_episode` scores the result against it; deriving it separately risks the
  two disagreeing on a left-moving subject.

**`scripts/lib/orchestration.py` — `detect_contradictions`**

- The `composition == "lead"` gate no longer refuses purely on `classify`'s label.
  `lead` needs somewhere to lead *to*, which is net travel: it is allowed when the
  subject travels (`abs(route[-1].x - route[0].x) >= LATERAL_FRAC * src_w`) even if
  `classify` reports non-lateral, because `reframe.compute_path` can now deliver
  that composition. A subject that genuinely does not travel still has no direction
  and is still refused, measured by the one threshold `classify` itself uses. The
  `composition-motion-mismatch` detail is reworded to name net travel and offer
  `center`/`break`.

**`scripts/reframe.py` — `compute_path`**

- Before the existing branch: when `composition == "lead"` and the classified
  `kind != "lateral"` and `len(route) >= 2`, set `kind, direction = "lateral",
  travel_direction(route)` (imported as `classify_direction`). Scoped to an
  **authored** lead only — `break`/`center` stay center-tracked, unchanged.

**`scripts/check_episode.py`**

- The tracked-branch direction default changes from `direction or "right"` to
  `direction or travel_direction(route)` — the same helper, the same answer, both
  sides. This closes the "two readers" gap: without it, `compute_path` leads a
  left-moving subject one way while the check grades the fixed-`"right"` line the
  other and reports a correct render as broken.

---

## 4. Invariants (each carried by a mutation-proven test)

1. **Byte-identical fast paths.** `window_frames(0.25, 30.0) == 7`;
   `smooth(window=DEFAULT_WINDOW)` unchanged; `smooth_window_s` default 0.25;
   `jitter(route=None)` equals the pre-slice output; `travel_direction([]) == "right"`
   equals `classify`'s default; `adjust_reframe_params({"max_speed": 750.0}, …)`
   returns without `KeyError`. Any episode authored before this slice renders the
   same argv on 30 fps footage (verified against the existing golden fixtures — no
   golden may move; the 59.94 fps fixtures are immune, see §7).
2. **Two-readers-one-spelling.** `reframe.compute_path` and `check_episode` both
   route direction through `travel_direction`. Test: a left-moving diagonal shot
   that `classify` calls `static` renders a `lead` crop *and* passes its own
   `on_line` check — a single helper, so they cannot diverge.
3. **A↔B coupling.** Widening the smoothing window is safe only because the jitter
   check filters the route it scores against. Test: a smoothed path over a noisy
   route **passes** at `route_window=5` and the raw-noise-copying path **fails** —
   the exact inversion §1.B.2 measured. Mutating the box-filter to a no-op flips
   the verdict.
4. **Ladder bounds and floors.** jitter widens toward `SMOOTH_WINDOW_S_MAX` and
   never past it; line-lag narrows toward `DEFAULT` and never below it. The ladder
   never runs on a pan (the `pan-not-retryable` guard already returns before
   `adjust_reframe_params`), and `smooth_window_s` is never read on the generated
   branch.

---

## 5. Testing

Faithful port of the parked tests, re-examined for teeth:

- **`test_pathsmooth.py`** — `window_frames` lands on 7 at 30 fps, doubles to 15 at
  59.94, is always odd ≥ 5 across a rate sweep, rejects degenerate input.
- **`test_motion.py`** — `travel_direction` reads net dx and defaults to right.
- **`test_checks.py`** — the eight jitter cases: forgives the subject's own
  backtrack, still fails chatter over a smooth subject, fails the excess beyond the
  backtrack, `route_window` filters detector noise (not subject motion) both ways,
  window-of-one is historical, rejects a bad window, reports the reversal count.
- **`test_orchestration.py`** — jitter widens the window, the ladder is bounded,
  line-lag narrows-but-not-below-default, a partial params dict is filled; and the
  lead-gate cases (allowed when the subject travels though `classify` says static,
  still refused when it does not, unchanged over a plain lateral).
- **`test_reframe.py`** (new file) — `classify` calls the diagonal shot static; an
  authored `lead` is honoured anyway and takes its direction from the route;
  `break`/`center` ignore the rescue.

**Mutation discipline** (track-stitch precedent): for every guard, neutralize the
guarded line and confirm a specific test flips red. The park's tests are the
starting point, not the finish line — if a guard has no discriminating test, that
is a coverage hole to close, not a test to trust.

Real behaviour where the pure functions allow it; no real YOLO — the direction /
jitter tests build routes as plain dicts. The existing real-ffmpeg golden fixtures
are the regression net for the byte-identical claim.

---

## 6. Landmine notes (design §12 adjacent)

- **B is a silent-corruption fix, not a feature.** A jitter check that scores the
  worse path better passes bad pixels — invisible until someone watches the reel.
  The route-window filter is the defense; its constant is field-measured and must
  not be re-tuned without new footage.
- **C is a silent-swap fix.** The old behaviour rendered a different composition
  than the author asked for and said nothing. The rescue is scoped to an *authored*
  `lead` precisely so it never overrides an *unstated* intent's safe default.

---

## 7. File map

| File | Change | Unit |
|------|--------|------|
| `scripts/lib/pathsmooth.py` | `DEFAULT_WINDOW`/`DEFAULT_WINDOW_S`/`window_frames`; `smooth` default | A |
| `scripts/lib/models.py` | `ReframeSpec.smooth_window_s` + validation | A |
| `scripts/lib/orchestration.py` | `DEFAULT_PARAMS`, `SMOOTH_WINDOW_S_MAX`, ladder, partial-fill; lead-gate | A, C |
| `scripts/lib/motion.py` | `travel_direction` | C |
| `scripts/lib/checks.py` | `_moving_average`, `jitter(route=, route_window=)`, `reversals` | B |
| `scripts/reframe.py` | `compute_path(smooth_window=)` + lead-rescue; `reframe()` resolves window | A, C |
| `scripts/check_episode.py` | `ROUTE_SMOOTH_S`, `_route_window`, jitter wiring; direction from travel | B, C |
| `scripts/process_episode.py` | `smooth_window_s=float(params[...])`; pan comment | A |
| `tests/lib/test_pathsmooth.py` | `window_frames` cases | A |
| `tests/lib/test_motion.py` | `travel_direction` cases | C |
| `tests/lib/test_checks.py` | route-aware jitter cases | B |
| `tests/lib/test_orchestration.py` | ladder + lead-gate cases | A, C |
| `tests/lib/test_reframe.py` | new — lead-from-travel over a diagonal shot | C |

No golden fixtures move — the render path changes only the smoothing window, and
`window_frames` resolves it to the historical 7 frames at the fixtures' 30 fps.
The exact-pixel fixtures that run at 59.94 fps are immune for one of two reasons:
the `process_episode` orchestrator golden uses a **frozen route** (a constant raw
path smooths to itself under any window), and the 60 fps `reframe._simplify` /
`_filter_args` cases call those helpers **directly** on a pre-built path, never
routing through `window_frames`. The implementer confirms this by running the full
real-ffmpeg battery and asserting no golden diff — the byte-identical claim is a
test result, not a promise.
