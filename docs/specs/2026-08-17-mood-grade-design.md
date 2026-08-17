# Mood → grade — design (2026-08-17)

**Slice:** backlog P2, "Mood → grade" — the grade half of real-run finding #9,
and the last of colour-as-a-stage §10 / matchgrade §8's "mood LUT" deferral.
**Size:** M.

## 0 · What the row asks

`match_grade` computes ONE common reel tone target — the per-anchor median of
every episode's measured `(p5, p50, p95)` luma profile — and authors a
`tone_src`/`tone_dst` pair into each episode that deviates. It is **consistency**:
it makes eight cameras read as one, and it has no opinion about what that one
should look like.

The brief does have an opinion. `SPEC.mood` already drives shot selection, pace
and the reel's vignette/fade through `moodpreset`. This slice makes it drive the
grade too: the same common target, displaced in the direction the mood asks for.

The conductor stays a conductor. There is no second grade stage, no LUT file and
no extra encode — the displaced target rides the tone pair that already exists.

## 1 · Where the mood comes from: `--spec`, measured

Two carriers were available and the measurement picked between them.

`EDL.variety.preset` is already on the EDL that `match_grade` reads, and it
records the preset the *cut* was planned against — attractive on paper. But on
the one real run on disk, `EDL.variety` is **`None`**: the run predates the
variety slice and was authored without `--spec`. A carrier that is absent on real
artifacts is a bad carrier.

So `match_grade build` gains `--spec SPEC.json`, the same flag and the same file
`edit_plan build` already takes, and resolves the preset through the same
`moodpreset.resolve(spec.mood)`. **No `--spec` → no bias → byte-identical to
today.** That is not a fallback ladder, it is the off switch.

`BALANCED` gets **no bias**, for the reason its own docstring already gives about
`look`: a skipped or unrecognised brief must not silently impose a taste.
`resolve(t).name == "balanced"` is the exact test, exactly as `write_edit_plan`
uses it.

## 2 · The shape: an additive displacement of the target

`MoodPreset` gains `tone_bias: tuple[float, float, float]` — luma-unit offsets on
`(p5, p50, p95)`, applied to the common target before it is handed to `plan`.

The triple is already the vocabulary of the thing being changed, and the four
classical mood grades are exactly statements about it: crush the blacks, lift
them, widen the gap, raise the middle. Nothing else needs inventing.

Rejected alternatives:

- **A mood LUT** (the original §10 phrasing) — a second colour stage, a second
  filter, an asset to license or generate. The conductor's whole economy is that
  ONE tone pair rides reframe's existing encode.
- **A displacement proportional to the reel's own range** — more robust where the
  additive one runs out of headroom (§5), but it makes "moody" mean something
  different on every reel, and the failure it avoids is measurable and reportable
  instead (§5). Filed as a deferral rather than dismissed.

## 3 · The floor is measured, and it is not small

The conductor does not hit its own target. Measured on the real run's darkest and
brightest episodes, rendering each through the exact curve `color.tone_arg`
authors and re-measuring the result:

| bias | asked | delivered (darkest ep) | error |
|---|---|---|---|
| **none** | (49.5, 100, 194.5) | (51, 106, 185) | **9.5** |
| fun | (53.5, 110, 198.5) | (55, 114, 190) | 8.5 |
| epic | (37.5, 100, 206.5) | (40, 106, 195) | 11.5 |
| moody | (34.5, 88, 188.5) | (36, 94, 178) | 10.5 |
| nostalgic | (67.5, 100, 176.5) | (67, 105, 169) | 7.5 |

The `none` row is the finding: **the existing conductor lands 6.5–11.5 luma units
from the target it authored**, against a `MATCH_EPS` of 4.0 that decides whether
to correct at all. The correction still does the bulk of the work — the darkest
episode's p95 travels 106 → 185 toward a target of 194.5 — but the reel is
matched to about ten units, not four.

**This sets the bias floor.** A displacement under ~10 units disappears into the
conductor's own error, so a subtle table cannot work here. That is a measurement,
not a preference. (The residual's cause — spline fitting through `TONE_SAMPLES`
control points, the encode, the measurement itself — is not diagnosed here; it is
a backlog row of its own, and if it shrinks, this table can get finer.)

## 4 · The table

Hand-authored FIRST CUT, in the same one place and with the same declared-guess
honesty as `MoodPreset.look` and intake's `CLUSTER_COS`. Chosen at ~15–20 units:
above the §3 floor with margin, below the point where the grade stops reading as
the footage.

| preset | `tone_bias` (p5, p50, p95) | what it says |
|---|---|---|
| **fun** | `(+10, +18, +8)` | brighter and airier — lifted middle, open shadows |
| **epic** | `(-16, 0, +16)` | wider contrast — deep blacks against bright highs |
| **moody** | `(-18, -16, -8)` | darker and crushed — low key, weight in the shadows |
| **nostalgic** | `(+20, 0, -18)` | faded — lifted blacks, pulled highlights |
| balanced | `(0, 0, 0)` | never applied; see §1 |

Measured separation against the unbiased grade on the real footage: nostalgic
moves the delivered p5/p95 by **+16/−16**, moody by **−15/−7**, epic by
**−11/+10**, fun by **+4/+5**. `fun` is the weakest — its dominant component is
`p50` (+8 delivered), and its p5/p95 moves sit at the floor. That is inherent to
what "fun" asks for (brightness, not contrast) and is recorded, not hidden.

## 5 · Running out of headroom: scale the whole vector, and say so

A bias can push an anchor outside 0–255. Three routes were considered and the
measurement picked one:

- **Refuse** — wrong. The preset is not an authoring error, and refusing a
  delivery because the footage is bright and the brief says "epic" is absurd.
- **Clamp the offending anchor** — wrong. `epic` without its highlight lift is
  just "crush the blacks", which is a different mood. Clamping silently changes
  the *shape* the preset asked for.
- **Scale the whole vector by one factor `k` until it fits** — keeps the
  direction, loses only magnitude. This is the rule.

Scanned across eight plausible reel medians, dark to bright, narrow to wide:

- `k = 1.00` on **5 of 8**; no target was refused by `_repair_gaps` anywhere.
- Scaling fires only on **bright** targets and only for the two presets that push
  `p95` up. At `(110, 170, 250)`: `fun` k=0.62 (11.2 of 18 survives), **`epic`
  k=0.31 — 5.0 of 16**.
- `moody` and `nostalgic` never scale: both pull inward or down.

**Five units is below §3's floor**, so on a reel whose median highlights already
sit near 250, `epic`'s bias is not merely weakened — it is invisible. The cause is
physical, not a defect: `epic` is the only preset asking for *more* highlight
headroom, and that reel has none.

### 5.1 · Two bounds, not one (as-built, found by this branch's review)

The first cut scaled against the 0–255 ceiling alone and missed the second bound:
`color.TONE_MIN_GAP` between neighbouring anchors. On a **low-contrast** reel
median, `nostalgic`'s +20 on `p5` pushes past `p50`; `_repair_gaps` then quietly
clamps it back to `p50 − 6` — and `k` still reported **1.00**. Measured: 12–16
luma units lost while the report claimed the displacement survived whole. That is
precisely the failure `k` exists to prevent, arriving through the door the design
had not looked at.

The pair constraint is one line of algebra. For adjacent anchors `(a₀, a₁)` with
biases `(d₀, d₁)`, the displaced gap is `(a₁ − a₀) + k·(d₁ − d₀)`, so only a pair
whose bias *narrows* it can bind, at `k ≤ ((a₁ − a₀) − gap) / −(d₁ − d₀)`.

Scanned over twelve medians (the eight of §5 plus four low-contrast ones) × four
presets: **0 of 48 cells lose anything silently.** Where the gap binds, `k` falls
and `bias_ineffective` fires — on `(49.5, 60, 194.5)` `nostalgic` scales to 0.225,
i.e. 4.5 units, and is correctly reported invisible. A reel with no contrast to
spend cannot be given a faded look, and now it says so.

Because it is invisible in the pixels, it must be visible in the report.
`MATCH.md` gains the bias, the scale `k`, and — when `k` scales the largest
component below the floor — a named `mood-bias-ineffective` note. The stage does
not refuse; it says what it could not do.

## 6 · What does not change

`common_target` keeps its signature and its meaning: the median is still the
median. The displacement is a separate pure function, `matchgrade.biased_target`,
returning `(Profile, k)` — so `plan`, `needs_tone`, `valid_src`, `ToneDecision`,
the EDL contract, `ReframeSpec`, `reframe` and every downstream check are
untouched. No new field on `EDLEpisode`, no `CACHE_VERSION`, no stage order
change, no extra ffmpeg pass.

`match_grade` remains opt-in and remains after pacing, before `edl_to_reel`.

## 7 · Testing

- `biased_target` — direction, the `k` scale, and that `k` is reported not
  swallowed; the mutation is clamping one anchor instead of scaling the vector.
- `MoodPreset.tone_bias` validation, and that `BALANCED`'s is the zero vector.
- The driver: `--spec` absent → the target is byte-identical to today's median
  (the off switch is the anti-regression pin); `--spec` naming a mood → the
  target moves by the preset's vector.
- A `balanced`-resolving brief → no bias, and the report says the mood was
  recognised as none.
- Real-ffmpeg: one episode rendered through the biased pair delivers percentiles
  closer to the biased target than to the unbiased one — the visibility proof
  this project asks of every look change.

## 8 · Deferred (each gets a backlog row)

- **A range-relative displacement** instead of an additive one — §2. It would fix
  §5's headroom collapse at the cost of "moody" meaning something different per
  reel. Only worth it if §5's note fires often on real briefs. **P3.**
- **Diagnose the conductor's 6.5–11.5-unit residual** — §3. It bounds how fine
  any grade table can be, and its cause is unknown. **P2, its own slice.**
- **Per-episode mood override** — the reel's grade is reel-level by construction,
  same as `look`. No request exists. **P4.**
- **Chroma, not just luma** — a mood is warmth as much as contrast, and this
  slice moves only the luma triple the conductor already owns. The warm/cool
  half needs the cross-episode white-balance actuator matchgrade §8 already
  defers. **P3.**

## 9 · Honest limits

- **The table is a first cut and nobody has looked at it.** §3 and §5 prove the
  mechanism — the curve delivers what it asks, within the conductor's own error,
  and the scale rule behaves across the range. Neither proves the four vectors
  are what those four words should mean. That judgement needs a human at CP3 on
  real footage, and this slice does not provide one.
- **The floor is two clips.** 6.5–11.5 units is measured on the darkest and
  brightest episode of one shoot, at one midpoint frame each.
- **`epic` on bright footage is measurably ineffective**, and the design's answer
  is a report line, not a fix.
- **Nothing checks the reel now matches the mood.** `check_reel`'s colour gate
  compares episodes to *each other*; they all move together, so it passes exactly
  as before, which is correct and is also the reason it cannot notice.
- **`fun` sits closest to the floor** of the four (§4), so it is the preset most
  likely to read as "nothing happened".
