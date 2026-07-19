# `pan` — a generated x(t) motion source

_Design · 2026-07-19 · §7 misc-engine slice B (the `fit-solid` slice's successor)._

**Status:** built (2026-07-19, branch `feat/pan`). Implements the design spec's
§7 `pan` row, re-read through the [layouts model](2026-07-10-layouts-design.md)
(crop × rect × filler) and the [fit-solid slice](2026-07-18-fit-solid-design.md)
(a preset is a parameter, not a branch). Verified by an 18-check mutation
battery over the finished single-episode tree (§10–§11); suite 1400 passed / 8
skipped at that point. **Reel-level support landed after, as three follow-up
commits** — an EDL-authored pan surviving `edl_to_reel` → `build_reel` →
`check_reel` was not exercised until then (§2.2, §11 landmine 5); final suite
1415 passed / 8 skipped.

---

## 1. `pan` is not a layout — its preset row is literally `fill`

The design spec's §7 lists five layout names, and `pan` is one of them. The
layouts design already re-read that list as three parameters and, in doing so,
quietly refuted the classification. Its preset table gives `pan` this row:

| Layout | crop aspect | rect | background |
|---|---|---|---|
| `fill` (built) | canvas | whole canvas | none |
| `pan` (later) | canvas | whole canvas | none |

The two rows are **identical**. Every parameter a layout has, `pan` shares with
`fill`. Nothing about the geometry distinguishes them, so nothing about the
geometry can implement them differently — a `pan` mode would be a name with no
parameters behind it, the exact failure the layouts design was written to
prevent.

What actually distinguishes a pan is **where the crop's x(t) comes from**. Today
there is exactly one source: a tracked route. A pan wants a second, declared one.
That is a motion-source question, not a layout question, and it is why this slice
adds no layout mode and touches `LayoutSpec` not at all.

The layouts design half-said this already — "tracking is not a property of the
layout" — but stated it only about *whether* tracking happens (a consequence of
`freedom = src_w − crop_w`). The stronger form this slice needs: **the SOURCE of
the crop path is not a property of the layout either.**

`manifest.LAYOUTS_SUPPORTED`'s trailing comment `# split/pan → their own plans`
becomes `# split → its own plan`. `split` really is a layout (two sources, two
rects, a changed manifest shape). `pan` never was.

## 2. A generated path is not an observation

`route.json` is read by **five** consumers, and every one of them treats it as
*evidence about the world*:

| Consumer | What it does with the route |
|---|---|
| `orchestration.detect_contradictions` | compares the manifest's declared `motion` against `classify(route)`; an empty route is `no-track` → `stop_and_report` |
| `reframe.compute_path` | aims the crop at the subject |
| `check_episode.run` | judges composition (`checks.centered` / `checks.on_line`) by comparing the path against the route; `checks.continuity` looks for subject teleports |
| `storyboard.build` | draws the §6.1a hero marker at the route's positions |
| `check_reel.run`'s geometry section | `safe_zones`/`key_action` project the route through the crop to check subject framing — route-dependent; `pad_bars`/`transitions` read only the meta sidecars and never touch the route |

(§2.2 below: the fifth row was missing from this table until the whole-slice
review that closed this design — see there before trusting this count on any
future slice.)

A pan has no subject to observe. The cheap move is to **synthesize a route** —
a list of `RoutePoint`s tracing the intended crop centre — so every consumer
keeps working untouched, and this slice becomes a twenty-line generator.

That is the wrong move, and it is worth naming exactly what breaks, because each
failure is silent:

1. **The contradiction gate would fire on every pan episode.** `classify()` reads
   a synthetic left-to-right route as `lateral:right`. A manifest that honestly
   declares `motion: static` — a static subject being revealed, which is the
   *entire premise* of a pan — would collide with it and `stop_and_report` a
   motion-mismatch that describes nothing real.

2. **The composition check would pass by construction.** `checks.centered`
   measures how well the crop centre tracks the subject. If the "subject" was
   derived *from the crop*, the comparison is circular and scores perfectly, every
   time. A green verdict that measured nothing is worse than a red one.

3. **The storyboard would mark a hero who does not exist**, and the §6.1a
   editorial gate ("is this the right person?") would be answering about a
   fabricated point.

So the path gets a second, *declared* source, and the artifacts record **which
source produced it**. No fabricated observations, anywhere.

### 2.1 The silent pass that is already there

Confirmed by reading, not assumed: `checks.continuity([])` returns
`{"pass": True, "worst_dx": 0.0, "cap": …}`. Its loop is
`for a, b in zip(route, route[1:])`, which over an empty route never executes, so
`worst` stays `0.0` and `0.0 <= cap` is `True`.

An empty route therefore does not crash continuity — it **passes** it. Any design
that reaches `check_episode` with no route and no marker gets a green
`continuity` verdict on a check that examined nothing. This is the concrete
reason the provenance bit in §5 is load-bearing rather than decorative.

### 2.2 The fifth consumer, missed

The table above counted **four**. There is a **fifth**: `check_reel.run`'s
geometry section, added by two slices that had already landed before this one
was written — safe-zones (2026-07-16, `safe_zones`/`key_action`) and
reel-final-editorial-checks (2026-07-17, `pad_bars`/`transitions`). Neither
this design's own audit nor Task 10's 18-check mutation battery (§10, §11)
re-verified `route.json`'s callers against the tree as it actually stood —
both are scoped to a single episode, and the gap only exists one level up.

The consequence: `edl_to_reel` (the one multi-episode driver this slice's own
authoring path builds) sent every reel containing a pan episode into
`check_reel.run` opening a `route.json` no episode had written. Every such
reel crashed with `FileNotFoundError`. Found only by a final whole-slice
review, after this slice's own tests — and check_reel's — were already green.
Fixed across two commits: `caa6505` (check_reel reads the meta's provenance
bit before it will touch a route, and states an all-pan reel's coverage rather
than passing it vacuously) and the `edl_to_reel` contract fix that followed —
plan `docs/plans/2026-07-19-pan.md` Tasks 11-13.

**The lesson:** an audit of consumers is only true as of the date it was
*actually re-checked*, not the date stamped on the document that carries it. A
slice that lands anywhere in that gap — before the audit was written or after
— invalidates it exactly as silently as one landing later. Recorded as
landmine 5, §11.

## 3. Surface: `pan` is a sibling of `motion`, not a layout and not a hero

A new optional manifest/EDL field, beside `motion` and `hero`:

```json
{"pan": {"from": 0.0, "to": 1.0}}
```

**Not a `hero` kind.** `HeroPin` answers "which *observed track* do I follow?".
A pan follows nobody. Adding a synthetic kind to the resolver whose own slice
([cast → hero-pin](2026-07-16-cast-hero-pin-design.md)) deleted every silent
fallback would undo that slice's point: `hero.resolve` is built so that a pin
matching nothing is `hero-unmatched`, never a fallback. A pin matching *nobody by
design* does not belong in it.

**Not folded into `motion`.** `motion` is a claim about the **subject**
(`lateral:right` / `head-on` / `static`), consumed by the contradiction gate as
something to verify against observation. `pan` is a statement about the
**camera**, and there is nothing to verify it against. Overloading one field with
both would make `detect_contradictions` unable to tell a checkable claim from an
uncheckable instruction. They also legitimately co-occur: the canonical pan is
`motion: static` **and** a `pan` — a still subject, a moving frame.

### 3.1 `from` / `to` are fractions of freedom

Both are fractions of the **available horizontal freedom**,
`freedom = src_w − crop_w`, not of the source width:

- `0.0` → the crop sits hard left (`x = 0`)
- `1.0` → the crop sits hard right (`x = src_w − crop_w`)

Freedom is the right denominator because it is *what actually exists to travel*,
and because it is already the number the layouts model uses to decide whether
anything is composable at all (`freedom == 0` → `editorial-only`). Expressing the
pan in the same units keeps one concept, not two.

**Direction is the sign of `to − from`.** `{"from": 1.0, "to": 0.0}` is a
right-to-left pan. No direction vocabulary (`"left-to-right"`, `"ltr"`, …) is
introduced — that would be a second spelling for information the numbers already
carry, and this repo has just spent a slice deleting a name that duplicated a
parameter (`fit-blur`). A partial reveal (`0.2 → 0.7`) costs nothing extra.

### 3.2 `PanSpec` (new, `scripts/lib/models.py`)

A config-spec by the repo convention — validates in `__post_init__`, raises
`ValueError` with a remedy. Frozen, beside `LayoutSpec`:

```python
@dataclass(frozen=True)
class PanSpec:
    start: float          # fraction of freedom, [0, 1]
    end: float            # fraction of freedom, [0, 1]
```

The dataclass fields are `start`/`end`; the JSON keys are `from`/`to`.
`from` is a Python keyword and cannot be a field name, and inventing a
`from_`-with-trailing-underscore field would leak that constraint into the wire
contract. The JSON spelling is what an author writes and reads, so it wins; the
`from_dict`/`to_dict` pair carries the two-name mapping in one place. This is the
only field in the repo whose wire name and field name differ — say so at the
dataclass, so the next reader does not "fix" it.

Validation, each with a remedy:

- both finite real numbers (not `bool` — `isinstance(True, int)` is `True` in
  Python, and `{"from": true}` must not silently mean `1.0`)
- both within `[0.0, 1.0]`
- `start != end` — a pan that does not move is not a pan. The remedy says to
  give it an extent, or drop the `pan` field rather than write a degenerate
  one — dropping it is **not** the same as a static crop, though: it hands the
  crop back to the tracked route (§2), which follows the subject if one moves.
  A genuinely static frame is what a *static subject* under a tracked route
  produces, not what omitting `pan` produces by itself.

## 4. The generator: two deliberate refusals

`ReframeSpec` gains `pan: PanSpec | None = None`. Inside `reframe()`:

- **`pan is None`** → today's code path, byte-for-byte. The route is read,
  `compute_path` runs, `pathsmooth.smooth` runs. Regression-pinned (§10).
- **`pan` set** → **the route is not read at all**, and the path is generated.

### 4.1 The arithmetic

```
freedom = rl.freedom                       # src_w − crop_w, from the resolved layout
x0      = round(spec.pan.start * freedom)
x1      = round(spec.pan.end   * freedom)
n       = max(2, round(dur * fps))         # frame count
t_i     = i / fps                          for i in 0 … n−1
x_i     = round(x0 + (x1 − x0) * i / (n − 1))
```

`n` is floored at 2 so the `i / (n − 1)` denominator can never be zero. A clip
short enough to round to a single frame is degenerate anyway; two knots at the
same instant produce a constant expression, which is the honest rendering of
"there was no time to travel".

**The pan always spans the whole episode**, start to end — `dur` is the clip's
duration, and there is no third parameter for when the move begins or stops. A
pan over part of the clip (hold, then travel) is a different feature: it needs a
time envelope, which is a *pacing* concern and would want to align to the beat
grid rather than to the crop. Out of scope (§12). Stating the invariant here
because §4.3's speed gate divides by `dur`, and that division is only correct
while the invariant holds.

Vertical placement is the canvas centre:

```
cy = max(0, (src_h − crop_h) // 2)
```

The tracked path uses `geometry.crop_y(mean_y, …)`, which places the subject at
`0.45 * crop_h` — the headroom canon (§6.4). With no subject there is no
`mean_y`, and a headroom rule with nothing to give headroom *to* is arbitrary.
Centre is the neutral choice, and it coincides with today's value in the dominant
case anyway (`crop_h == src_h` → both are `0`).

### 4.2 It does not smooth

`pathsmooth.smooth` exists to tame **observation noise** — it rate-limits, then
runs a Savitzky-Golay filter over a jittery tracker output. A generated straight
line has no noise, and passing it through the smoother can only do two things,
both bad:

- **the rate limiter can only make the pan land short.** `_rate_limit` caps each
  per-frame delta at `max_step = max_speed / fps`. A pan asked to travel faster
  than that is silently slowed, never reaches `x1`, and the reveal the author
  asked for does not happen — with nothing in the report saying so.
- **savgol distorts the ends.** A polynomial fit over a window straddling the
  path's first and last samples bends a line that was exactly right.

So the generated path goes to `_xexpr` **raw**. This is a rule about provenance,
not about shape: a path nobody observed needs no noise removal.

### 4.3 It validates the speed instead of clamping it

Dropping the rate limiter means an absurd pan (a `crop_scale` typo turning a
gentle reveal into a whip across 1920px of 4K freedom in 1.5s) would render
exactly as written. So the cap becomes a **gate**, not a silent correction:

```
v = abs(x1 − x0) / dur                     # px/s
if v > spec.max_speed:  raise ValueError(...)
```

`max_speed` (default 750 px/s ≡ 25 px/frame at 30fps) is **reused as a ceiling,
not a target**. It is not a cinematic pan speed — a slow reveal is far below it —
and no new threshold is invented. Its job here is to catch the absurd, not to
express taste. The message names `v`, `max_speed`, and the three exits: shrink
the extent, lengthen the episode, or raise `max_speed`.

### 4.4 One more gate: a pan needs somewhere to go

```
if freedom == 0:  raise ValueError(...)
```

A pan at zero freedom clamps to a constant `x = 0` and renders a **static
frame**. Nothing crashes; the output simply is not a pan, and it looks like an
ffmpeg bug rather than a manifest one. The remedy names the actual lever:
`crop_scale < 1.0` (a `fill` at `crop_scale = 1.0` cuts the full source width, so
there is nothing left to travel).

### 4.5 Why a dense path and not two knots

A constant-velocity pan is one linear segment, so `_xexpr` could be handed two
knots directly. The dense per-frame path is generated anyway because:

- `path.json` keeps the same artifact shape, so nothing downstream special-cases
  a two-element path;
- `checks.jitter` has something real to measure;
- `_simplify` (Douglas-Peucker, `eps = 2.0`) collapses the line back to exactly
  **2 knots** on its own — every intermediate point lies on the line, and integer
  rounding deviates by at most 0.5px, well under `eps`. The dense path costs
  nothing in the emitted expression. §10 pins that "exactly 2 knots" expectation
  so a future change to `_simplify` cannot quietly inflate a pan's expression.

## 5. The sidecar carries the provenance

`PathMeta` gains one field, appended **last**:

```python
pan: bool = False
```

Last because a defaulted field cannot precede non-defaulted ones, and
`from_dict` reads it with `.get("pan", False)` — the same **one-key exemption**
`background` took in the fit-solid slice, for the same reason: an older sidecar
predates the field and its absence honestly means "not a pan". Every other key
stays a hard `d["…"]` integrity check.

That one bit is what stops §2's three lies:

| Consumer | `pan = False` (today) | `pan = True` |
|---|---|---|
| `check_episode` framing | `centered` / `on_line`, numeric | `passed=None`, `{"status": "editorial-only", "reason": "generated path — no tracked subject"}` |
| `check_episode` continuity | route teleport check | `passed=None`, `{"status": "not-checked", "reason": "generated path — no tracked subject"}` |
| `check_episode` jitter direction | `classify(route)`, defaulting to `"right"` | the sign of the generated path itself |
| `check_episode` jitter / length / black_frames | run | **run unchanged** — they judge the rendered clip, not an observation |
| `storyboard` hero marks | drawn | **no change needed** (§6.2) |

Note the shape of the framing change: it **widens an existing rule** rather than
adding a parallel one. `check_episode` already answers `editorial-only` when
`meta.freedom == 0` ("nobody controls the composition"). The rule was "geometry
decides, not the layout name"; it becomes **"geometry and provenance decide"**.
The pan arm goes first — at `freedom == 0` a pan cannot exist (§4.4 raises before
any render), so the order is unreachable in practice, but the more specific
reason belongs first for anyone reading the branch.

`continuity` moving to `not-checked` rather than `editorial-only` is deliberate:
`editorial-only` means "a human must judge this", and there is nothing here for a
human to judge either. `not-checked` is the vocabulary `check_reel` already uses
for a check whose input is absent (`beat`/`loudness` on a silent reel), and this
is the same situation one stage down.

## 6. The shell skips tracking

### 6.1 `process_episode`

With `m.pan` set:

- **step 1 (`track.build_route`) is skipped.** `timings["track"] = 0.0`. This is
  a real saving — a whole YOLO pass over the segment — and, more importantly, the
  honest statement that nobody is being tracked.
- **step 2 (`detect_contradictions`) is skipped.** Its entire job is to compare a
  manifest *claim* against a tracker *observation*. With no observation there is
  nothing to contradict, and running it against an empty route would fire
  `no-track` — a diagnosis ("hero never detected; check the segment, model size,
  or hero pin") that misdescribes a deliberate choice, which is exactly the
  misdiagnosis class the cast → hero-pin slice fixed for `hero-unmatched`.
- `route_path` stays `None` through the loop.

**No empty `route.json` is written.** Writing one would be the smallest diff —
every consumer keeps its file — but an empty route already *means* something in
this pipeline: "the tracker ran and found nobody." Writing one to mean "the
tracker never ran" is precisely the fabricated-observation class §2 exists to
refuse. `None` means "there is no route", which is true.

### 6.2 What that costs the three call sites

- **`reframe(spec, src, route_path, out, path_out)`** — `route_path` becomes
  `str | None`. Under a pan it is unused; passing `None` is refused only when
  `spec.pan is None` (a missing route with no pan is still the loud error it is
  today).
- **`check_episode.run(clip, route_path, path_path, spec, out)`** — `route_path`
  becomes `str | None`. The body already reads the sidecar; the change is a
  **reorder** (read `meta` before touching the route) plus one branch, not a
  rewrite.
- **`storyboard.build(...)`** — **no change at all.** Verified by reading: it
  already guards with `if None not in (route, path, meta)`, so `route=None` skips
  `marks_at_times` and falls through to `spec.marks`, which `process_episode`
  leaves at its `None` default. The hero marker simply is not drawn. This design
  originally claimed a change here; the code was already right.

## 7. Two refusals at the manifest gate

Soft gate (accumulated problem strings → `needs_input`), per the standing
validation boundary; everything below it raises.

1. **`pan` + `composition` in (`lead`, `break`)**. Those are *subject-relative
   framing rules* — put the subject on the left third, or deliberately break the
   rule. A pan positions the crop by its own law and consults no subject, so the
   two instructions fight, and silently honouring one would discard an explicit
   editorial statement. `composition` is a REQUIRED field and cannot be omitted,
   so `center` is the one legal value alongside a pan, read as "no framing rule".
   The problem string says so.

2. **`pan` + `hero`**. A hero pin says "follow this person"; a pan says "follow
   nobody". The problem string names both and asks which was meant.

**`motion` + `pan` is explicitly NOT refused** (§3). The canonical pan carries
`motion: static`.

## 8. The authoring path

`pan` rides the same rails `background_color` rode one slice ago:

```
EDLEpisode.pan  →  EDL.to_dict / from_dict
                →  edl.to_manifest_dict
                →  Manifest.pan (OPTIONAL) + validate()
                →  process_episode builds PanSpec
                →  ReframeSpec.pan
                →  reframe generates the path
                →  PathMeta.pan
                →  check_episode reads the bit
```

- `manifest.OPTIONAL` gains `"pan"`; `Manifest.pan: dict | None = None`, built
  into a `PanSpec` by `process_episode` exactly where `LayoutSpec` is built —
  once, outside the retry loop, because a pan is editorial intent and not a retry
  parameter.
- `validate()` constructs the `PanSpec` as its **oracle** and turns a raise into
  a problem string — the same soft-gate-over-hard-constructor pattern
  `LayoutSpec` and `hero.resolve` already use. Validation and behaviour cannot
  drift apart because they run the same constructor.
- `EDL.to_markdown` renders it in the existing motion column as `pan 0.0→1.0`, so
  no column is added to a table an author reads.
- `edit_plan.window_to_episode` does **not** derive it. A pan is editorial
  judgment, so it arrives from the agent's `selection.json`, alongside
  `composition` and `grid` — never copied from `FOOTAGE.json`.

## 9. Edge cases

| Case | Behaviour |
|---|---|
| `from == to` | `PanSpec` raises (§3.2) — remedy: drop the field |
| `freedom == 0` | `reframe` raises (§4.4) — remedy: `crop_scale < 1.0` |
| implied `v > max_speed` | `reframe` raises (§4.3) — three remedies |
| clip rounds to < 2 frames | `n` floored at 2 → constant expression, no divide-by-zero |
| `pan` + `layout: insert` | legal. The card's content pans inside its rect; freedom is the crop's, and the rect is unaffected |
| `pan` + `layout: fit` at `crop_scale = 1.0` | `freedom == 0` → raises. Correct: `fit` cuts nothing, so there is nothing to travel |
| `pan` + `color_correct` (reel retry loop) | orthogonal — a colour reprocess re-runs `reframe` with the same `pan`, regenerating an identical path |
| `pan` on a reprocess | deterministic. The generated path depends only on `(PanSpec, freedom, fps, dur)`, all frozen, so loop-2 gets the same pixels' geometry every round |
| older `path.meta.json` with no `pan` key | `.get("pan", False)` → not a pan (§5) |

## 10. Testing

Test placement follows the repo's existing split, verified by reading rather
than assumed: pure config-specs live in `tests/lib/` (`test_models.py`,
`test_manifest.py`, `test_edl.py`), and everything reframe-related — including
its *pure* `_filter_args`/`compute_path`/`_simplify` tests — lives in
`tests/integration/test_reframe.py`. There is **no `tests/unit/` directory**;
new pan tests join the files their neighbours are already in.

**`PanSpec` validation** (`tests/lib/test_models.py`): the table, one case per
rule, each asserting the *informative* part of the message (the offending value
and the enumeration), not one word of it. Includes `{"from": True}` → refused,
since `isinstance(True, int)` is `True`.

**The generator** (`tests/integration/test_reframe.py`):
- exact x values for a known `(freedom, dur, fps, start, end)`
- both directions (`0→1` and `1→0`)
- a partial extent (`0.2 → 0.7`) lands on exactly `0.2*freedom` and `0.7*freedom`
- `n < 2` guard
- the four raises: `freedom <= 0` (§4.4), `dur <= 0` (a public pure function
  must guard the division even though `reframe._probe` already refuses
  `dur <= 0` upstream), `v > max_speed` (§4.3), and `x0 == x1` — a span that
  rounds to the same pixel on both ends (§11 landmine 3) — plus the degenerate
  `PanSpec(start=end)` refusal one level up

**The no-smoothing proof — and it is not the endpoint-exactness tests.** The
generated path's first and last elements equal exactly `round(start*freedom)`
and `round(end*freedom)`, and that is worth pinning, but it does **not** prove
no-smoothing: `pathsmooth`'s rate limiter only bites near `max_speed`, so a
realistic slow reveal (1920px over 10s = 192 px/s, the dominant case) survives a
full `smooth()` pass with **byte-identical endpoints**. Measured: routing the
generator's output through the real smoother left 11 of 12 tests in the file
green, including the one whose comment claimed to be the proof. The actual proof
has to assert the **branch**, not an outcome the other branch can also produce —
`test_generate_pan_path_never_calls_the_smoother` monkeypatches
`pathsmooth.smooth` to fail the test if it is ever called, then runs the
generator at that dominant, sub-ceiling speed. Only a test shaped this way goes
red when someone re-routes the generator through the smoother; name it for what
it protects, not for what it calls.

**The 2-knot expectation.** `_simplify` over a generated path returns exactly 2
knots (§4.5).

**`check_episode` under a pan sidecar:** framing is `editorial-only` with the
generated-path reason, continuity is `not-checked`, jitter/length/black_frames
still run and can still fail, and jitter's direction follows the path's sign (a
`1→0` pan is not reported as reversing).

**Regression pin — and it is NOT the filtergraph.** A pan changes `xexpr`, which
`_filter_args` merely interpolates; the emitted chain shape is untouched, and
`test_filter_args_fill_is_pinned_to_todays_chain`
(`tests/integration/test_reframe.py:269`) already pins that whole string. So the
pin this slice owes is one level up: **with `pan=None`, `reframe` still reads the
route and produces the same path it does today** — the assertion that catches a
refactor accidentally routing every episode through the generator. Pinning the
filtergraph again would restate a guarantee that already holds and prove nothing
about this change.

**Real-ffmpeg pixel proof** — the one thing no unit test can show: *the crop
actually traveled*. A wide synthetic clip carrying a distinctly coloured marker
near its left edge and a different one near its right, cropped narrow enough that
no single frame can contain both. Render a `0→1` pan; assert the **first** frame
contains the left marker's colour and not the right's, and the **last** frame the
reverse. Control: the same clip rendered with a centre-pinned route and no pan
shows **neither** marker in either frame — without the control, the proof would
also pass if the markers were simply always visible.

**Mutation checks are plan steps, not suggestions** (this repo's standing
evidence bar — the last slice found nine green-but-hollow tests, every one caught
by mutation and none by the suite going red). At minimum:

| Mutation | Must turn red |
|---|---|
| route the generated path through `pathsmooth.smooth` | the no-smoothing proof |
| delete `pan` from `PathMeta.to_dict` | the `check_episode`-under-pan tests |
| make `check_episode`'s pan arm fall through to `centered` | the framing test |
| delete the `composition in (lead, break)` refusal | the validate test |
| delete the `freedom == 0` raise | the zero-freedom test |
| change the speed gate from `>` to `>=` (or delete it) | the speed-gate test |

This table is the floor, not the whole battery: Task 10's final run over the
complete tree grew it to **18 checks**, adding the ones two more rungs of
review found (the rounding mutations, the `dur <= 0` guard, the `x0 == x1`
guard, both escalation-guard shapes, the `is not None`-vs-truthiness pair) —
see the plan's Task 10 and `docs/build-status.md`.

## 11. Landmines (design spec §12)

Five, all of the silent-corruption class this repo keeps in always-loaded
context. The first two were anticipated before implementation; the third and
fourth were found by mutation during execution; the fifth was found by a final
whole-slice review, after this slice's own tests — and the tests of the two
slices that had unknowingly created it — were already green.

1. **Never smooth a generated path — and the endpoints cannot prove it.**
   `pathsmooth.smooth` is for observation noise. Its rate limiter only bites
   near `max_speed`, so a realistic slow reveal (1920px over 10s = 192 px/s,
   the case this design calls dominant) survives a full `smooth()` pass with
   **byte-identical endpoints** — measured: routing the generator's output
   through the real smoother left 11 of 12 tests in the file green, including
   the one whose comment claimed to be the proof. The failure is a reveal that
   silently does not happen, with a green report. Closed only by a test that
   asserts the *branch* — monkeypatching `pathsmooth.smooth` to fail if it is
   ever called, then running the generator at that dominant, sub-ceiling
   speed — not by any tolerance on the output.

2. **Never synthesize a route to keep a consumer working.** An empty or
   fabricated `route.json` is not a neutral placeholder — an empty route
   already means "the tracker found nobody", and a fabricated one turns
   `check_episode`'s composition check circular (it scores the crop against a
   subject derived from that crop) and makes the storyboard mark a hero who
   does not exist. `checks.continuity([])` returns `pass=True`, so the absence
   is not even loud.

3. **A validator that checks a ratio cannot see the quantity it will be
   multiplied by.** `PanSpec` honestly refuses `start == end` — but it
   validates *fractions of freedom*, not pixels, and cannot see the `freedom`
   those fractions get multiplied by. A span under half a pixel (e.g.
   `0.5 → 0.5004` at `freedom=875`) rounds both ends onto the same integer,
   and the render is a static frame nobody asked for — the same
   silent-static-frame failure the `freedom <= 0` guard (§4.4) exists to
   prevent, reached by a different road. Closed by `generate_pan_path`'s own
   `x0 == x1` raise, downstream of `PanSpec`, at the one point where the
   actual pixel arithmetic is visible.

4. **`is not None` versus truthiness on a dict-valued optional.** An empty
   dict is falsy, so code written as `if m.pan:` (rather than
   `if m.pan is not None:`) silently treats `{}` the same as absent. In
   `manifest.validate()` that skips the whole pan validation block, handing a
   clean gate to a pan that cannot construct; in `edl.to_manifest_dict` it
   drops the `pan` key entirely, so `Manifest.from_dict` never even sees a
   pan was intended. Both mutations left the **whole suite green**. Absent and
   empty are different statements, and only one of them is a mistake:
   `pan: {}` means an author started to write a pan and stopped; `pan` absent
   means no pan was ever intended.

5. **An audit of consumers is only true as of the date it was actually
   re-checked.** §2's table counted four readers of `route.json`. A fifth —
   `check_reel.run`'s geometry section — had already landed via two unrelated
   slices (safe-zones, 2026-07-16; reel-final-editorial-checks, 2026-07-17)
   before this design was written, and the audit never re-verified against the
   tree as it stood: it was wrong on the day it was written, not invalidated
   later. `edl_to_reel` is the only multi-episode driver this slice's own
   authoring path builds, and it is what reached the missed consumer — every
   reel containing a pan episode crashed with `FileNotFoundError`. Neither this
   slice's own tests nor the two other slices' caught it, because none of the
   three exercises a pan through a multi-episode driver. Found only by a final
   whole-slice review; fixed by `caa6505` (branch on the meta's provenance bit,
   not on file existence or a route value a caller happened to pass) and the
   `edl_to_reel` contract fix that followed — plan `docs/plans/2026-07-19-pan.md`
   Tasks 11-13. The fix for the class of mistake is not "audit harder, once" —
   it is either re-grep the consumer list at the point of use, or make the
   check structural, as `caa6505` now is.

**A related lesson, not itself a landmine.** An ordering constraint between two
guards is invisible to any test that exercises only one of them. Hoisting the
`pan-not-retryable` guard (§6.1) above `orch.escalation` turned **zero** tests
red — every existing scenario happened to hand the two guards the same
answer — until a test was written that gives `orch.escalation` a reason of its
own (an unfixable `length` failure) specifically to prove which one must win.

## 12. Non-goals

Each its own slice, if ever:

- **tilt (Y motion)** — `cy` stays constant. On the dominant geometry (9:16 from
  landscape) `crop_h == src_h` and there is no vertical freedom to use.
- **zoom / Ken Burns** — `crop_w`/`crop_h` would become expressions of `t`, which
  breaks `PathMeta`'s `crop_w: int` contract and every consumer that reads it as
  the width that was cut. A genuinely larger change.
- **easing** — constant velocity only, per the design spec's §7 wording ("slow
  constant-velocity pan"). Ease-in/out would be a curve parameter on `PanSpec`,
  additive later.
- **a pan combined with tracking** — the two x(t) sources are alternatives, not
  layers.
- **a pan over part of the clip** (hold, then travel) — needs a time envelope,
  which belongs with pacing and the beat grid, not with the crop (§4.1).
- **`split`** — the one real remaining layout; two sources, two rects, a changed
  manifest shape.

## 13. Doc sync

- design spec §7: the `pan` row → **built**, and the paragraph under the table
  gains the §1 finding (a pan is a motion source, not a preset — its preset row
  was `fill`'s).
- design spec §12: the four landmines from §11 (plus the ordering-constraint
  note).
- `docs/pipeline-map.md`: the misc-engine roadmap bullet — `pan` done, remaining
  list narrowed to `split`, stabilization's apply half, and the tracking
  degradation ladder.
- `docs/build-status.md`: a Done entry; the "remaining layouts" Next-action
  bullet loses `pan`.
- `CLAUDE.md`: two registry rows (this design + its plan).
- `SKILLS/edit-plan/SKILL.md`: `pan` as an authorable editorial field.
