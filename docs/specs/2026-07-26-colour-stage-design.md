# Colour-as-a-stage (slice F) — design

Slice F promotes colour grading from the single normalize-to-middle gain on
`main` to a rich **per-episode colour actuator**, plus an auto white-balance, a
tone-profile measurer, and an advisory colour-fidelity check.

**Source material.** The parked branch `wip/montage-run-hardening`, commit
`4841dd3`, holds colour hot-patches written live during the first real
99-clip / 16 GB montage run — `lib/color.py` (+303 lines: seven grade
primitives), the `ReframeSpec` colour fields, and the tv/pc colour-range
correctness in `assembly`/`ExportProfile`. That code is unit-green (1697 passed)
but never went through the design → plan → TDD-review cycle the rest of the repo
did. This slice lands it through that cycle, faithfully — and adds two things the
run did not have (white balance, fidelity check) and one the commit lacked (a
tone measurer, so `tone` is hand-authorable).

Companion to: the engine dataclass-hardening design
([2026-07-08-engine-dataclass-hardening-design.md](2026-07-08-engine-dataclass-hardening-design.md),
`ReframeSpec`/`ExportProfile`), the reel retry-loop design
([2026-07-11-reel-retry-loop-design.md](2026-07-11-reel-retry-loop-design.md),
the A.5 across-cut `color_correct` convergence this slice leaves intact), and the
montage design §10 "Color / stabilization" (the cross-cutting colour spec).

---

## 0. What exists, and what this changes

**On `main` today** colour is one operation: a soft normalize-to-middle
per-channel **gain** (`color.gains_for_means` → `TARGET=(105,122,137)`,
`STRENGTH=0.55`, clamp `[0.7,1.5]`), emitted as one `colorchannelmixer` in the
tail of `reframe`'s `-vf` chain. The only colour *gate* anywhere is
`check_reel.color_across_cuts` (reel level), driving the A.5 reprocess loop
(`compound-not-revert`, `cc[i] ← clamp(cc[i]·med/d_i, LO, HI)`). There is no
numbered colour stage — montage design §10 is a cross-cutting section, and its
line "a final match-grade pass for consistency across episodes; optional mood
LUT" is unbuilt.

**This slice adds**, all riding the existing single reframe encode (no second
pass):

1. **Seven per-episode grade knobs** (parked) — `black_point`, `highlight`,
   `saturation`, `shadow_red`, `mid_blue`, `dip`, and the non-linear `tone`
   profile transfer — each an ffmpeg fragment with a measured safe range and an
   identity no-op default, composed in one fixed order around the existing gain.
2. **An auto white-balance** (new) — a grey-world neutralize computed from the
   source, emitted **first**, **off by default** (identity-preserving).
3. **A tone measurer** (new) — a small per-clip `(p5,p50,p95)` luma reader so a
   human can author `tone`.
4. **A render-time banding guard** (parked, `reframe.verify_tone`).
5. **An advisory colour-fidelity check** (new) — subject-region hue drift,
   source vs graded, reported never blocking.
6. **Colour-range (tv/pc) correctness** (parked) end to end, so `-c copy` concat
   cannot stamp a `pc` tag onto `tv` data.

## Scope decisions (locked in brainstorming)

- **Actuator, not conductor.** Slice F lands the per-episode grade actuator. It
  does **not** build the design-§10 "final match-grade pass across episodes" —
  the stage that would measure every episode's profile, compute one common reel
  target, and auto-author `tone_src`/`tone_dst`. That conductor is a later slice;
  slice F is its foundation (the tone actuator + the per-clip measurer it will
  reuse).
- **Approach A: faithful port + tighten the colour boundary.** `color.py` becomes
  the single colour authority — it owns the fragment builders **and** the
  fixed-order `grade_chain` composer (moved out of `reframe._filter_args`, which
  should not carry the colour-domain knowledge "tone before gain before
  highlight"). `verify_tone` stays in `reframe` (the renderer owns a render-time
  guard). The `measure` and fidelity metrics split pure-core (`color.py` /
  `color_fidelity.py`) from ffmpeg driver, like offset/mood/pacing. **One encode
  is preserved** — colour is never a separate pass.
- **White balance is additive and identity-off.** A new op, OFF by default
  (`white_balance = 0.0` → identity), so today's output stays byte-identical and
  every colour golden holds. When enabled it neutralizes first; the existing
  normalize-gain stays after it (§6).
- **The fidelity check is advisory, in slice F.** Episode-level, subject-region,
  hue-only, reported and out of `overall` — zero blast radius, like `safe_zones`
  and the reel-final editorial checks. No auto-fix (§7).
- **Excluded from this slice.** `smooth_window_s` (rides the same parked
  `ReframeSpec` hunk but is pathsmooth, a different slice); the design-§9
  in-episode "mean RGB within ±8 of neutral" check (the richer grade obsoletes
  its near-neutral invariant — §7); the conductor and the §10 mood LUT.

## 1. Data flow

```
                          measure (new, per clip, authoring aid)
                               │  p5,p50,p95 luma
                               ▼
selection.json  (agent authors grade knobs + white_balance + tone_src/dst)
        │  edit_plan build
        ▼
   EDL.json / EDLEpisode  (9 colour fields) ──► manifest ──► process_episode
                                                                  │
                    ReframeSpec (9 colour fields) ────────────────┤
                                                                  ▼
   reframe:  wb = white_balance_arg(color_means, white_balance)
             tone = tone_arg(src, dst) → verify_tone(tone)      (banding guard)
             grade = color.grade_chain(gains, wb=, tone=, …)     (one fixed order)
             -vf … , {grade} , fps , format          ← single encode, no 2nd pass
                                                                  │
   check_episode:  hue-drift(subject region: ep_raw vs graded)  → ADVISORY
                                                                  ▼
   assemble (range-correct concat) ──► deliver (ExportProfile.color_range) ──► REEL
```

## 2. `color.py` — the pure colour authority

All builders return an ffmpeg **filter-fragment string** and `""` at their
identity value (so the fast path stays byte-identical). Every validator
**type-checks first** — rejecting `bool` (because `True == 1 == 1.0` would slip
the identity shortcut), then the identity shortcut, then range. `color.py` stays
**pure** (no ffmpeg, numpy-free): only string composition and integer/float
math.

### 2.1 The seven grade primitives (ported verbatim from `4841dd3`)

New module constants: `BLACK_POINT_MAX=0.35`, `HIGHLIGHT_KNEE=0.55`,
`HIGHLIGHT_MIN=0.6`, `SATURATION_MIN=0.5`, `SATURATION_MAX=1.5`,
`SHADOW_RED_MAX=0.20`, `SHADOW_RED_RETURN=0.25`,
`SHADOW_RED_ANCHORS=(0.50,0.70,0.85)`, `TONE_ANCHORS=3`, `TONE_MIN_GAP=6.0`,
`TONE_TOP_SLOPE=0.35`, `TONE_SAMPLES=13`, `MID_BLUE_MIN=0.80`,
`MID_BLUE_MAX=1.20`, `MID_BLUE_BAND=(0.45,0.65)`, `MID_BLUE_PINS=(0.25,0.85)`,
`DIP_MAX=0.5`, `DIP_COLOR="0x141414"`.

| Builder | Op | Position | Range (identity) | Why it exists |
|---|---|---|---|---|
| `black_point_arg(black)` | `colorlevels=rimin=gimin=bimin` | before the gain | `[0, 0.35]` (`0`) | subtract a lifted black floor; a multiply cannot move a floor |
| `highlight_arg(white, knee=0.55)` | `curves=all='0/0 knee/knee 1/white'` | after the gain | `[0.6, 1.0]` (`1.0`) | shoulder pulling whites down; knee `0.55` because a `0.70` knee bulges the spline **above** identity (mean 113→117) |
| `saturation_arg(sat)` | `eq=saturation` | after the gain | `[0.5, 1.5]` (`1.0`) | YUV chroma scale; the gain neutralizes a cast but cannot lower overall saturation |
| `shadow_red_arg(lift, ret=0.25)` | `curves=r=…` toe lift + `SHADOW_RED_ANCHORS` pins | after the gain | `[0, 0.20]` (`0`) | neutralize a green/cyan black without warming skin/red gear; the anchor pins are load-bearing (a red board lost 7 R−G without them) |
| `mid_blue_arg(scale)` | `curves=b=…` midtone band, `MID_BLUE_PINS` hold ends | after the gain | `[0.80, 1.20]` (`1.0`) | scale blue in the midtones only (sky-bounce on skin); trade is a less-blue sky |
| `tone_arg(src, dst)` + `_lerp` | sampled `curves=all` `(p5,p50,p95)` transfer | before the gain | anchors: 3 values, 0–255, strictly increasing by ≥`TONE_MIN_GAP` | the **non-linear** profile transfer a gain+levels provably cannot do (an affine map leaves histogram shape invariant) |
| `dip_arg(dip, dur)` | `fade=t=in:color=0x141414` + `fade=t=out` | last (timeline) | `(0, 0.5]` (`0`); raises if `dur ≤ 2·dip` | a zero-cost transition; grey `0x141414`, **not black**, so `check_reel`'s `blackdetect` stays silent |

`tone_arg` computes its top endpoint (`min(255, dst[2] + (255−src[2])·0.35)`),
builds knots `[(0,0), (src,dst)…, (255,top)]`, and emits a **sampled**
piecewise-linear map (`TONE_SAMPLES` grid points) so ffmpeg's spline cannot
wander; grid nodes within `TONE_MIN_GAP` of an anchor are dropped (near-coincident
control points make ffmpeg emit **no frame at all** — §8), and the anchors always
join the grid (sampling alone pulls the fitted toe ~5 codes off).

### 2.2 `grade_chain` (new — the one fixed order)

Moves the composition out of `reframe._filter_args`. `color.py` alone knows the
correct order:

```python
def grade_chain(gains: tuple[float, ...], *, wb: str = "", tone: str = "",
                black_point: float = 0.0, shadow_red: float = 0.0,
                mid_blue: float = 1.0, saturation: float = 1.0,
                highlight: float = 1.0, dip: float = 0.0, dur: float) -> str:
    """The colour portion of reframe's -vf tail, in the one correct order:
    white-balance → tone (profile) → black_point (toe) → gain (mixer) →
    shadow_red → mid_blue → saturation → highlight (shoulder) → dip (timeline).
    `wb`/`tone` are pre-built fragments (the caller builds + verifies them).
    Returns WITHOUT the trailing fps/format — reframe owns those."""
    return (wb + tone + black_point_arg(black_point) + mixer_arg(*gains)
            + shadow_red_arg(shadow_red) + mid_blue_arg(mid_blue)
            + saturation_arg(saturation) + highlight_arg(highlight)
            + dip_arg(dip, dur))
```

Each fragment carries its own joint comma (`black_point`/`tone`/`wb` trailing,
`mixer_arg` none, the rest leading), so concatenation is a valid chain; at all
defaults `grade_chain(gains, dur=…)` == today's lone `mixer_arg(*gains)`.

### 2.3 `percentiles` (new — pure, for the measurer)

```python
def percentiles(hist256: list[int]) -> tuple[float, float, float]:
    """(p5, p50, p95) of an 8-bit luma histogram (256 bin counts), by cumulative
    count. Pure integer math — no numpy — so color.py stays dependency-free."""
```

## 3. `ReframeSpec` + `reframe`

`ReframeSpec` (in `models.py`) gains **nine** colour fields, all
identity-default (so a pre-existing spec renders byte-identically), each
bool-rejected + range-checked in `__post_init__`:

| Field | Type | Default | Range |
|---|---|---|---|
| `white_balance` | `float` | `0.0` | `[0, 1]` (§6) |
| `black_point` | `float` | `0.0` | `[0, 0.35]` |
| `highlight` | `float` | `1.0` | `[0.6, 1.0]` |
| `saturation` | `float` | `1.0` | `[0.5, 1.5]` |
| `shadow_red` | `float` | `0.0` | `[0, 0.20]` |
| `mid_blue` | `float` | `1.0` | `[0.80, 1.20]` |
| `dip` | `float` | `0.0` | `[0, 0.5]` |
| `tone_src` | `tuple[float,float,float] \| None` | `None` | XOR-paired with `tone_dst`; validation delegates to `color.tone_arg` (one site) |
| `tone_dst` | `tuple[float,float,float] \| None` | `None` | — |

`reframe`, just before assembling the command (where it already computes
`gains`):

```python
gains = color.gains_for_means(spec.color_means)
if spec.color_correct is not None:      # the A.5 reel retry loop, unchanged
    gains = color.corrected(gains, spec.color_correct)
wb = color.white_balance_arg(spec.color_means, spec.white_balance)
tone = ""
if spec.tone_src is not None:
    tone = color.tone_arg(tuple(spec.tone_src), tuple(spec.tone_dst))
    verify_tone(tone)                   # a banding spline fails HERE, not in the reel
grade = color.grade_chain(gains, wb=wb, tone=tone, black_point=spec.black_point,
                          shadow_red=spec.shadow_red, mid_blue=spec.mid_blue,
                          saturation=spec.saturation, highlight=spec.highlight,
                          dip=spec.dip, dur=dur)
```

`_filter_args` replaces its inline `mixer = color.mixer_arg(*gains)` with the
passed-in `grade`, and `tail = f"{grade},fps={fps:.6g},format=yuv420p"`. Both the
fast (`fill`) and composite paths keep their shape; the composite path grades the
whole composited frame **after** the overlay (foreground crop *and* the
blurred/solid background together) — parked behaviour, kept, because a single
consistent look across the frame is right for a fit/insert card.

**`verify_tone`** (new in `reframe`, `RAMP_PROBE_W=256`): renders a 256-step RGB
ramp through the tone fragment via ffmpeg, reads the LUT back, and **refuses a
non-monotone transfer** (`lut[i+1] < lut[i]`) or empty output, naming the first
offending step. Fuzzing random anchor triples put ~⅓ of them 1–3 codes negative;
this is the guard that keeps a banding curve out of the delivered reel. It runs
only when `tone` is set (identity default → no probe, no cost).

## 4. Authoring path

The nine colour fields are **editorial** (agent-supplied, like
composition/grid), so they ride the same selection → EDL → manifest → spec route:

- **`EDLEpisode`** (`lib/edl.py`) gains the nine fields (identity defaults),
  `to_dict` (scalars always; tone pair only when set), and `to_manifest_dict`
  (forwards them). No validation here — the manifest gate / `ReframeSpec` owns it.
- **`Manifest`** (`lib/manifest.py`) gains the nine fields, the `OPTIONAL` tuple
  entries, and `from_dict` parsing (`float(d.get(k) or default)` for scalars,
  `tuple(d[k])` for the tone pair).
- **`edit_plan`** forwards the nine fields from a `selection.json` episode into
  `window_to_episode`/`build_edl` (the editorial passthrough — the fields join
  the same `**ed` editorial kwargs as `composition`/`layout`).
- **`process_episode`** threads `m.<field>` into the `ReframeSpec(...)` it builds
  (the load-bearing manifest→spec bridge).
- **`skills/edit-plan/SKILL.md`** gains grade/white-balance/tone guidance and
  names the `measure` helper (§5) as the way to obtain `tone_src`/`tone_dst`.

## 5. The tone measurer (new, tiny)

`scripts/color_measure.py` — the authoring aid that makes `tone` usable by a
human (nothing in the parked commit measured profiles; the live run authored them
ad hoc):

```python
def measure_profile(clip: str, at: float | None = None) -> tuple[float, float, float]:
    """(p5, p50, p95) luma of `clip` at sample time `at` (default: 1s in — a
    settled frame). Decodes a downscaled grayscale still via ffmpeg, bins to a
    256-entry histogram (numpy in the driver only), and calls color.percentiles."""
```

Pure-core (`color.percentiles`) + tool-driver (`measure_profile`), the
offset/mood/pacing pattern. CLI prints the triple so an author can paste
`tone_src` (per clip) and pick a `tone_dst` target. The future conductor slice
**reuses** `measure_profile` per episode — this is a foundation, not a throwaway.

## 6. White balance (new — additive, identity-off, grey-world)

Two new pure functions in `color.py`:

```python
def white_balance_gains(means, strength, lo=LO, hi=HI) -> tuple[float, ...]:
    """Grey-world neutral gains: pull each channel mean toward the common average
    (neutral) at `strength`. neutral = mean(means);
    g = clamp(1 + strength*(neutral/m - 1), lo, hi). strength 0 → (1,1,1)."""

def white_balance_arg(means, strength) -> str:
    """A leading colorchannelmixer neutralizing the source cast. "" at strength 0
    (NOT an identity mixer) so the fast path stays byte-identical."""
```

- **Grey-world**, targeting the **common average** of the three source means (so
  channels equalize toward true neutral, preserving overall brightness) — unlike
  the existing normalize-gain, which targets the fixed cool middle
  `(105,122,137)`.
- **Off by default.** `white_balance = 0.0` → `""` → no filter → today's output
  is byte-identical and every colour golden holds. This is why WB is *additive*,
  not a redefinition of the normalize-gain (which would move the baseline).
- **First in the chain** (`grade_chain`'s `wb` slot), before `tone`, so the
  neutralized image is what every later knob shapes.
- **Residual (landmine §8).** The existing soft normalize-gain runs **after** WB
  and pulls toward the cool `(105,122,137)`, so it re-introduces a slight cool
  cast — partially undoing WB. This is accepted (WB does the heavy neutralization
  at up to full strength; the normalize is soft at `0.55`) and recorded, not
  silently ignored. A future slice may reconcile the two neutralizers into one
  authority; that would move the baseline, so it is out of scope here.

## 7. Colour-fidelity check (new — advisory, episode-level)

A guard that the grade did not wreck important colours (skin, jersey, gear),
without fighting the *intended* look. New pure `scripts/lib/color_fidelity.py`,
wired into `check_episode`:

- **Metric = hue-angle drift.** For each of `K` sample times, sample the
  **subject region** (the route bbox at that time) mean RGB in the **source**
  (`ep_raw`, pre-grade) and in the **graded** clip, convert each to an HSV hue
  angle, and take the circular distance. Hue angle is invariant to exposure
  (scaling all channels) and to saturation (scaling chroma about grey), so it
  trips **only on a true hue shift** — skin turned green, a jersey hue flipped —
  and tolerates the exposure/saturation the grade deliberately applies.
- **Near-grey guard.** A region whose chroma (`max−min` of mean RGB) is below
  `GREY_EPS` has no defined hue; that sample is skipped. If every sample is
  near-grey, the check reports `not-checked` (honest — a grey subject cannot
  "drift").
- **Pure/driver split.** `color_fidelity.hue(rgb)`, `hue_drift(src, graded)`, and
  `evaluate(samples, threshold)` are pure (mirroring `safezones.evaluate` /
  `reel_final.evaluate_*`); `check_episode` does the ffmpeg sampling (it already
  samples frames for the black check) and the route-bbox lookup.
- **Advisory.** `check_episode.run` gains `source: str | None = None` (the
  `ep_raw` path); `process_episode` passes it. When `source` is `None` the check
  reports `not-checked`. The result is reported with `passed=None` (the
  episode-level advisory convention, as with the zero-freedom composition check),
  the measured worst drift + threshold + time in `detail`, and is **excluded from
  `overall`** — it never fails the episode, escalates nothing (no auto-fix). The
  threshold is `CheckSpec.hue_drift_max` (degrees).
- **MVP region = the whole subject bbox.** Separating skin / clothing / sport gear
  needs per-part segmentation the pipeline does not carry at check time; the
  bbox-region mean is the honest MVP, refined later (§10).

## 8. Colour-range (tv/pc) correctness (ported from `4841dd3`)

Files ship untagged `yuv420p` today; `-c copy` concat takes stream tags from the
**first** entry, so a `pc`-tagged episode among `tv` data (or the reverse)
silently stamps the wrong range on the rest — a ~12% contrast loss that reads as
milky, blown foam.

- **`ExportProfile`** (`models.py`) gains `color_range: str = "tv"` (validated
  `"tv"`|`"pc"`); `args()` appends `-color_range {color_range}` to the deliver
  encode.
- **`assembly.py`** gains `DELIVERY_RANGE="tv"`; `StreamInfo.color_range`
  (probed from ffprobe, `or "unknown"`); `matches(…, color_range)` treats a
  stream tagged the target range **or untagged (`"unknown"`) as compatible** — the
  pipeline's own reframe output is untagged `yuv420p`, which *is* limited-range by
  mp4 convention, so it must still take the lossless `-c copy` path; only a
  **different explicit** tag (a foreign `pc` among `tv`) is the real
  wrong-tag-stamping hazard and is normalized alone. (The parked port required
  `== color_range`, which silently re-encoded **every** self-produced episode —
  a review-caught regression, fixed with the `"unknown"`-compatible rule + an
  anti-regression test.) `_normalize` **converts** rather than relabels:
  `scale=…:in_range=auto:out_range={range}` + `-color_range {range}` — the sample
  conversion is the load-bearing half; note libx264 does **not** physically write
  the VUI range tag for the default `tv`, so files stay untagged-limited, the
  consistent convention (§9).
- **`edl_to_reel`** gains `color_delta_max: float | None = None` + a
  `--color-delta-max` CLI flag that overrides the **existing** across-cut ceiling
  (`ReelCheckSpec.color_delta_max`, default 12.0) via `ReelManifest`. It only
  tunes the pre-existing consistency gate — "raise ONLY for a reel that
  deliberately cuts between scenes of different exposure" — and adds no grading.

## 9. Landmines (montage §12)

- **`lutrgb` stays banned.** Every new fragment uses `colorlevels` / `curves` /
  `eq` / `fade` / `colorchannelmixer` — never `lutrgb`. The landmine-lint AST scan
  must stay green; `dip_arg`'s `fade=…:color=0x141414` is a fade **colour**, not a
  `color=` source, and `colorlevels` is not `colorchannelmixer` — confirm neither
  trips the lint's string-emission check.
- **`dip` is grey, not black.** `DIP_COLOR="0x141414"` so `check_reel`'s
  `blackdetect=d=0.05:pic_th=0.98` stays silent on an intended transition — "the
  difference between a transition and a reprocess loop". `dip_arg` raises when
  `dur ≤ 2·dip` (the two fades would overlap).
- **`verify_tone` is mandatory when `tone` is set.** ~⅓ of random anchor triples
  yield a non-monotone spline (banding); the ramp probe refuses it at render time,
  before the reel. Not optional, not deferrable.
- **Two colour knobs can pass the soft gate but raise at render.** `dip` (valid
  per `ReframeSpec` ∈ `[0, 0.5]`) raises in `dip_arg` when `dur ≤ 2·dip` — a `dur`
  the manifest gate cannot see; a banding `tone` pair (anchors valid but the spline
  dips) raises in `verify_tone`. Both are **caught by `edl_to_reel`'s worker loop**
  (`fut.result()` → `except Exception` → `stop_and_report`), so in a reel they
  surface as a routable finding, not a crash; a bare single-episode
  `process_episode` run surfaces the descriptive raise directly. This is the
  intended fail-loud (soft-manifest / hard-engine), not a silent trap — and the
  reason `verify_tone`/`dip_arg` carry remedy-bearing messages. (A future parity
  nicety: a post-probe `dip`-vs-`dur` preflight → `needs_input`, mirroring the
  layouts rect preflight; the tone ramp cannot be preflighted without rendering.)
- **Near-coincident tone anchors → ffmpeg emits no frame.** `TONE_MIN_GAP` drops
  grid nodes within 6 codes of an anchor and requires anchors to increase by ≥6;
  without it the render silently produces zero frames.
- **White-balance residual.** The normalize-gain after WB re-casts slightly toward
  the cool target (§6) — documented, bounded (soft `0.55`), not silent.
- **Untagged range must stay delivery-compatible.** `assemble()` sees only
  reframe's own untagged (`"unknown"`) output; the parked `matches` required an
  exact `tv` tag, which silently re-encoded **every** self-produced episode (a
  second lossy pass, defeating the "one encode, at deliver" invariant) with zero
  test signal. `matches` treats `"unknown"` as compatible with the delivery range;
  only a foreign **explicit** `pc` normalizes. Pinned by an anti-regression test
  (an untagged uniform reel takes `-c copy`, never a re-encode).
- **The fidelity metric must be hue-only.** A drift check on overall colour would
  fight the intentional grade (which changes exposure/saturation on purpose); hue
  angle is the exposure/saturation-invariant metric that flags only a broken hue.
- **The §9 in-episode "mean RGB ±8 of neutral" check is deliberately NOT added.**
  The richer grade makes a deliberate warm/saturated episode's mean legitimately
  far from neutral; that check would false-fail it. Recorded as superseded; a
  future editorial colour check may replace it.

## 10. Testing

- **Unit (`tests/lib/test_color.py`, extend):** each of the seven primitives —
  identity → `""`, range clamps, bool rejection, the emitted string at a known
  value; `grade_chain` — the whole-string order at defaults (== `mixer_arg`) and
  with several knobs set (fixed order pinned); `white_balance_gains`/`_arg` —
  `(1,1,1)`/`""` at strength 0, grey-world gains at strength 1, clamp; `percentiles`
  — a known histogram → known triple.
- **Unit (`tests/lib/test_models.py`, extend):** `ReframeSpec` — each field's range
  + bool rejection; the `tone_src`/`tone_dst` XOR pairing; `ExportProfile.color_range`
  tv/pc validation + `args()`.
- **Unit (`tests/lib/test_edl.py`, `test_manifest.py`):** the nine fields
  round-trip through `to_dict`/`from_dict`/`to_manifest_dict`.
- **Unit (`tests/lib/test_color_fidelity.py`, new):** `hue`/`hue_drift` — exposure
  and saturation scaling leave drift ~0, a real hue rotation raises it; near-grey →
  skipped; `evaluate` — worst-sample aggregation + threshold.
- **Unit (`tests/lib/test_assembly.py`):** `matches` treats a differing
  `color_range` as an outlier.
- **Integration (real ffmpeg):** `verify_tone` refuses a hand-picked banding
  triple and accepts a monotone one; a graded episode renders and the grade moves
  pixels (mean/hue differs from ungraded); `white_balance=0` renders
  byte-identical to today (fast-path pin); a `pc`+`tv` concat comes out
  range-correct (measured contrast preserved, not milky); `measure_profile` on a
  synthesized known-luminance clip returns the expected `(p5,p50,p95)` within tol;
  the fidelity check flags a deliberately hue-broken grade and passes a faithful
  one.

## 11. Non-goals / deferred

- **The conductor / auto match-grade** — measure every episode's profile, compute
  one common reel target, auto-author `tone_src`/`tone_dst` (design §10 "final
  match-grade pass"). Its own later slice; slice F is the foundation.
- **The §10 "optional mood LUT".**
- **Per-part fidelity** — skin vs clothing vs sport gear separately (needs
  segmentation at check time); MVP is the whole subject bbox.
- **Auto-fix for the fidelity check** — it is advisory only; no reprocess/escalate.
- **Reconciling the two neutralizers** (WB + normalize-gain) into one authority —
  would move the baseline; out of scope (§6).
- **`smooth_window_s`** — rides the same parked `ReframeSpec` hunk but is
  pathsmooth, a different slice.
- **A second encode / colour as a separate ffmpeg pass** — colour rides the one
  reframe encode.

## Module / file map

| File | Change |
|---|---|
| `scripts/lib/color.py` | +7 grade primitives + constants, `grade_chain`, `white_balance_gains`/`_arg`, `percentiles` (stays pure) |
| `scripts/lib/models.py` | `ReframeSpec` +9 colour fields & validation; `ExportProfile.color_range`; `CheckSpec.hue_drift_max` |
| `scripts/reframe.py` | `verify_tone`; `_filter_args` calls `grade_chain`; builds `wb`/`tone` |
| `scripts/lib/color_fidelity.py` | **new** — pure `hue`/`hue_drift`/`evaluate` |
| `scripts/check_episode.py` | `source=` param; advisory hue-drift check |
| `scripts/color_measure.py` | **new** — `measure_profile` + CLI |
| `scripts/lib/edl.py` | `EDLEpisode` +9 fields, `to_dict`, `to_manifest_dict` |
| `scripts/lib/manifest.py` | `Manifest` +9 fields, `OPTIONAL`, `from_dict` |
| `scripts/edit_plan.py` | editorial passthrough of the 9 fields |
| `scripts/process_episode.py` | manifest→`ReframeSpec` wiring; passes `ep_raw` as `source=` |
| `scripts/lib/assembly.py` | `StreamInfo.color_range` + probe + `matches` + `_normalize` convert |
| `scripts/edl_to_reel.py` | `--color-delta-max` override |
| `skills/edit-plan/SKILL.md` | grade / white-balance / tone guidance + `measure` |
| docs | this spec, the plan, build-status, pipeline-map, CLAUDE registry |
