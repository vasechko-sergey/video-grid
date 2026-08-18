# Titles: the pixel gate, the staircase that leaves the frame, and three orphans

**Date:** 2026-08-19
**Status:** design
**Sources:** backlog P3 "titles in the look gate" · backlog P3 Titles "the full
pixel-level safe-zone gate" · [frame-probe-look-gate](2026-08-15-frame-probe-look-gate-design.md)
§7/§11 · [titles-animations](2026-07-29-titles-animations-design.md) · a dead-code
audit run 2026-08-19

---

## 0. What this closes, and what it found on the way

The queued row was one sentence: *titles ride `deliver`'s encode and no gate reads
the result.* Everything below the first section is what measuring that produced.

| # | Question | Answer |
|---|---|---|
| §1 | Is the titles hole real, or is the `!=`-bytes golden enough? | Real. The golden proves *something* changed in one synthetic frame; nothing checks the shipped reel |
| §2 | What metric survives a vignette, a fade and a moving picture? | Not the one the deferral assumed. Master-vs-delivered **cannot** work at depth — §2.2 measures a max-depth vignette scoring **higher** than a real title. The delivered file's own frame-to-frame change, minus the master's, does (§2.3) |
| §3 | Where are the constants? | `TITLE_INK_DELTA = 40`, `TITLE_MIN_FRACTION = 0.0002`, `TITLE_BAND_PAD = 0.6` — each from a measurement, and §3.4 names the one title the gate cannot prove |
| §4 | Does a sample inside a fade ramp still work? | **No, in both directions**, and it was not on the queue. A `t_in` at alpha 0.10 scores **0.0000%** (false fail); a `t_out` inside the fade-out inflates to **30.69%** (false pass). Both ends must be clamped |
| §5 | A found defect: does the safe-zone layout hold for every title? | **No.** A 4-step bottom `stair` renders **244 px** into the app chrome, measured. Nothing refuses it today |
| §6 | Are the two "unwired candidates" the backlog names actually dead? | **No** — both are called from `intake.py`. The audit found three *real* orphans instead |

Two of the six changed the shape of the slice. §2's metric is not the one this
was queued as, and §5 is a live defect the queue never named.

---

## 1. The hole, stated exactly

`deliver` burns titles into its one encode ([deliver.py:182](../../scripts/deliver.py)),
then calls `_verify_look`, which calls `lookcheck.evaluate(..., titles=True)`, which
returns this and nothing else:

```
LookFinding(check="titles", status="not-checked",
            detail="titles were declared and this slice has no check for them ...")
```

`not-checked` does not fail the gate. So a run where the font name is wrong, the
text file is empty, a filtergraph value split on a bare comma, or the drawtext
stage was dropped from the filter list delivers a reel with **no text**, writes
the attestation, and reports success. The first thing that notices is a human at
CP3.

That is not hypothetical for this repo: the cinematic-look review caught exactly
that bug class by hand — `deliver` dropping a filter from the list, which would
have silently killed the bookend fade and every title for three of four mood
presets. The look gate exists because that happened. Titles were left out of it.

**What exists today.** [tests/integration/test_titles.py:58](../../tests/integration/test_titles.py)
asserts `_frame_bytes(titled) != _frame_bytes(plain)` on the synthetic fixture.
Non-vacuous — it would catch a chain that produced nothing at all — but it is one
frame of one fixture at build time, and it says nothing about the reel that ships.

**What this slice does NOT claim.** The gate proves ink appeared in the band the
title declared. It does not read the text, does not check the words are the
author's, does not judge legibility, and cannot see a title rendered in the wrong
font. §10 is the full list.

---

## 2. The metric

### 2.1 The obvious one, and why it is wrong

The natural move — the one every other check in `lookcheck` makes — is
master-vs-delivered at one timestamp: `|m − d|` inside the title's band. The
vignette check does it, the fade check does it.

Measured on a 1080×1920 synthetic master, band = the bottom title zone padded
0.6 font sizes each side, counting pixels whose worst-channel difference exceeds
60:

| delivery | `|m − d| > 60`, band |
|---|---|
| plain title, no look | 5.71% |
| **vignette 0.45, no title** | **5.82%** |
| **vignette 0.60, no title** | **9.58%** |

A max-depth vignette scores **higher than a real title**. The metric does not
separate — it measures "the delivery differs from the master", and every
declared filter differs from the master.

The neighbour-strip control (band vs the rows above and below) does better but
not enough: with a title the margin is `+1.08` percentage points at vignette
0.60, against `−4.62` without — and a two-letter title under that vignette lands
on the wrong side of zero. A no-waiver gate cannot ship a 1-point margin.

### 2.2 What the vignette actually does

`LOOK_VIGNETTE_MAX` is 0.6 and the mask is radial, so its per-pixel effect is
**largest exactly where a bottom title sits**. Measured worst-channel change from
the vignette alone, inside the bottom band:

| depth | max per-pixel Δ | band pixels > 60 |
|---|---|---|
| 0.10 | 21 | 0.0000% |
| 0.30 | 57 | 0.0000% |
| 0.45 | 85 | 5.82% |
| 0.60 | 113 | 9.58% |

At 0.30 the vignette stops one code short of a 60 threshold. That is luck, not
headroom — the same table at 0.45 crosses it. Any absolute master-vs-delivered
threshold is a bet on the author's vignette depth.

### 2.3 The metric that works

A vignette is a fixed transform of the picture. It applies identically at every
timestamp. So compare the **delivered file against itself** at two times — one
inside the title's window, one outside — and subtract the master's own change
between those same two times:

```
ev(pixel) = max over RGB of ( |d_in − d_out| − |m_in − m_out| )
fraction  = share of band pixels with ev > TITLE_INK_DELTA
```

Why it separates, in one line each:

- **A static filter** (vignette) darkens both frames the same way, so it can only
  *shrink* `|d_in − d_out|` relative to `|m_in − m_out|`. Its evidence is ≤ 0.
- **Picture motion** moves both terms together and cancels.
- **Ink present in one frame and absent in the other** has no counterpart in the
  master and survives at full strength.

Measured on the 2026-08-03 run's own delivered reel (1080×1920, 59.94 fps,
34.05s) re-encoded with and without each treatment, threshold 40, best of five
witness times spread across the reel:

| delivery | evidence fraction | worst `ev` pixel |
|---|---|---|
| re-encode only, no title | **0.0000%** | 27 |
| vignette **0.60**, no title | **0.0000%** | 19 |
| plain title, bottom | 2.9966% | 188 |
| plain title, top | 7.0493% | 242 |
| bold-box title, bottom | 18.9443% | 189 |
| plain title + vignette 0.60 | 3.2455% | 191 |
| two-letter title ("go") | 0.3498% | 113 |

The vignette column is the point: **0.60 changes the answer by 0.25 percentage
points** (2.9966 → 3.2455), where the naive metric moved by more than the whole
signal.

### 2.4 The witness barely matters

The out-of-window time is a free parameter, so it had to be shown not to be a
tuning knob. Five witnesses at t = 1.0 / 12.0 / 20.0 / 28.0 / 33.0 against the
same in-window frame:

| delivery | t=1.0 | t=12 | t=20 | t=28 | t=33 |
|---|---|---|---|---|---|
| plain bottom | 2.9966% | 2.9645% | 2.9705% | 2.9653% | 2.9673% |
| two-letter | 0.3328% | 0.3443% | 0.3280% | 0.3320% | 0.3498% |
| no title | 0.0000% | 0.0000% | 0.0000% | 0.0000% | 0.0000% |

Spread across witnesses is under 1% of the value for a single-shot title. The
bold-box row is the exception (3.53%–18.94%) because its black box against a
bright witness frame scores far higher than against a dark one — which only ever
*helps*, so the rule is **best of the available witnesses**, not the first one.

---

## 3. The three constants

### 3.1 `TITLE_INK_DELTA = 40` — per-pixel evidence, in codes

The threshold, not the fraction, is what does the discriminating. It must sit
above every code a title-free delivery can produce.

Measured over **110 ordered frame pairs** of the run's own reel re-encoded with
no title, sampling eleven times spread across its 34s:

| delivery | worst fraction over 110 pairs | worst single-pixel `ev` |
|---|---|---|
| re-encode only | **0.00000%** | 30 |
| vignette 0.60 | **0.00000%** | 24 |

40 sits **1.33× above** the worst noise pixel ever observed, and no pair in
either sweep produced a single qualifying pixel. Real footage was used
deliberately: the synthetic corpus peaked at `ev = 2`, which would have justified
a far lower threshold and a far weaker gate.

### 3.2 `TITLE_MIN_FRACTION = 0.0002` — 0.02% of the band

With the no-title side at exactly zero across 110 pairs, the fraction floor is
not separating signal from noise — the threshold already did that. It exists to
absorb a stray cluster on footage rougher than any measured here. In the measured
band (234 rows × 1080 px) 0.02% is 51 pixels.

Against it, the ladder of legitimate titles on real footage:

| title | evidence fraction | margin over the floor |
|---|---|---|
| `"."` (one character) | 0.0384% | 1.9× |
| `"hi"` | 0.1717% | 8.6× |
| `"yes"` | 0.3443% | 17× |
| `"salt sun and you"` | 2.9966% | 150× |
| the same at `scale=0.5` | 1.7039% | 85× |

### 3.3 `TITLE_BAND_PAD = 0.6` — font sizes of padding, each side

The band is computed, not found, so it must be shown to contain the ink for
every style the repo can author. `inside` below is the measured ink extent
against the computed band, on real footage at the `reels` zone:

| title | band rows | measured ink rows | contained |
|---|---|---|---|
| one character | 1442–1676 | 1603–1612 | yes |
| two characters | 1442–1676 | 1536–1612 | yes |
| full line, bottom | 1442–1676 | 1514–1612 | yes |
| full line at `scale=0.5` | 1527–1644 | 1564–1612 | yes |
| full line, top | 89–324 | 153–252 | yes |
| full line, centre | 842–1077 | 911–1009 | yes |
| **4-step `stair`, bottom** | 1442–1676 | **1535–1857** | **no** — see §5 |

A padded band that is too tall only dilutes the fraction; a band that misses the
ink is a false fail, so the padding is deliberately generous. `bold-box`'s box
and `outline-bold`'s stroke extend 9 rows above and 15 below the predicted text
box on the synthetic corpus — well inside 0.6 font sizes (64 rows at this
resolution).

### 3.4 What the floor cannot prove

A **one-character title** clears the floor by 1.9×. That is the thinnest margin
in the table and it is recorded rather than engineered away: stretching the floor
down to widen it would spend the only margin protecting against a stray cluster,
to serve a title (`"."`, `"3"`) that `SPEC`'s hook/text/ending vocabulary does not
produce. If a countdown reel ever wants one, this row is where to look.

---

## 4. The fade, in both directions

Not on the queue, and it decides two code branches. Same reel, a 1.0s bookend
fade, a title over `[0.0, 3.0]`:

| `t_in` | `t_out` | fraction | what it means |
|---|---|---|---|
| 1.50 | 12.00 | 6.6896% | both clear of the ramps — the reference |
| 0.25 | 12.00 | 2.8676% | `t_in` at alpha ≈ 0.25: degraded, still passes |
| **0.10** | 12.00 | **0.0000%** | `t_in` at alpha ≈ 0.10: **false fail** on a correctly rendered title |
| 1.50 | **33.80** | **30.6937%** | `t_out` inside the fade-out: **inflated 4.6×** |
| 1.50 | 33.95 | 7.3156% | deeper into the ramp |

The first hazard is obvious in hindsight: a title inside a fade-in is *drawn*
faint, so there is little ink to find. The second is the dangerous one — a
witness frame faded toward black makes `|d_in − d_out|` large for reasons that
have nothing to do with a title, which is a **false pass** on a delivery whose
drawtext never ran.

So both ends are clamped into `[fade, dur − fade]`, and a title whose whole
window lies inside a ramp reports `not-checked` with that reason named, rather
than being sampled at a moment where the answer is known to be wrong.

---

## 5. The staircase that leaves the frame

Found while checking §3.3's band containment, and it is not a gate problem — it
ships today.

`build_filterchain` lays a title out against `y_exprs(platform)`, which is keyed
off `safe_zone_for(platform)`: a bottom title's ink box sits exactly at the
zone's inner edge. Correct for one line. But `_layers` gives a `reveal="stair"`
title an extra per-step drop of `j * line_spacing * scale / FONTSIZE_DIV * h`,
and nothing subtracts that from the base `y`.

Measured, `reels` zone, 1080×1920, four steps at the default `line_spacing`:

- the zone's inner bottom edge is at row **1613** (`1920 − 1920 × 0.16`)
- the rendered ink reaches row **1857**
- so the last step sits **244 px inside the app's caption/button chrome**

`Title.__post_init__` validates eleven things — text, timing, fade against the
window, reveal steps against the window, scale, line spacing, colour, position,
style. It does not know the platform, so it cannot check this, and
`build_filterchain`, which does know, never looked.

**The fix is a refusal, not a clamp.** Moving the base `y` up to fit the
staircase would silently relocate a title the author positioned; shrinking it
would silently resize it. Both are the invisible-creative-change class this repo
refuses elsewhere (`Title.fade`'s own two-ramp check is the precedent). The
author shortens the staircase, lowers `line_spacing`, moves to `pos="top"`, or
scales down.

**One geometry function, two readers.** `titles.band_rows(title, h, platform)`
returns the `(top, bottom)` rows the title's ink can occupy. The refusal in
`build_filterchain` compares it against the zone; `lookcheck` uses it as the
band. They cannot disagree, for the same reason `y_exprs` replaced the frozen
`_Y_EXPR` constant in the titles-animations slice.

The estimate is deliberately conservative — it predicts `[1506, 1981]` where the
ink reached `[1535, 1857]`, because `th` is approximated by the font size and the
step drop is summed at its maximum. Over-estimating dilutes a band (harmless) and
refuses a title that would have *just* fitted (a false refusal with an obvious
remedy in its message). Under-estimating would ship the defect, which is what
happens now.

---

## 6. The orphans, and a backlog line that says the wrong thing

An AST audit over all of `scripts/` — public functions, public classes, module
constants, and dataclass fields — asking which have no production reader:

| kind | orphans |
|---|---|
| public functions with no production caller | **2** |
| public classes | 0 |
| module constants | **1** |
| dataclass fields written but never read | **0** |

Zero orphan contract fields is the notable number: the wire contracts are fully
consumed. The three that are not:

1. **`geometry.crop_size`** — a one-line wrapper over `crop_for`, called by four
   tests and nothing else. Delete; the tests move to `crop_for`.
2. **`safezones.default_zone`** — its docstring says *"titles' single margin
   source (§5.16)"*. That stopped being true when titles-animations replaced the
   frozen `_Y_EXPR` with `y_exprs(platform)`. The function survived the slice
   that obsoleted it, and its docstring now names a caller that does not exist.
   Delete.
3. **`models.DEGRADED_LEVELS`** — a declared vocabulary that nothing validates
   against: `TrackMeta.degraded` accepts any string, and the only reference is a
   test asserting the tuple equals its own literal. It is the odd one out —
   `HERO_RULES`, `HERO_KINDS`, `POSITIONS`, `STYLES`, `REVEALS` are all enforced
   by a `__post_init__`. So this one gets **wired, not deleted**: `TrackMeta`
   refuses a `degraded` outside it. That is the constant doing the job its
   siblings do, and it closes the path where a typo'd rung name rides onto every
   post-tracking result unchallenged.

**And the backlog line that is wrong.** [backlog.md:161](../backlog.md) says
`carve.track_displacements` and a vidstab-subtracted curve "already exist
unwired". `track_displacements` is called at
[intake.py:380](../../scripts/intake.py) and `carve.subject_curve` at
[intake.py:88](../../scripts/intake.py) — both have been the intake motion
sensor since the 2026-08-06 slice. What the row means is that neither is
available to `lib/anchors`, which runs at pacing time over an episode's source
and has no tracking data. That is a subsystem boundary, not dead code, and the
sentence reads as the opposite. Reworded.

---

## 7. What this slice builds

| # | Where | What |
|---|---|---|
| 1 | `scripts/lib/titles.py` | `band_rows(title, h, platform)` — the one geometry spelling; `build_filterchain` refuses a title whose extent leaves the zone |
| 2 | `scripts/lib/lookcheck.py` | `TITLE_INK_DELTA` / `TITLE_MIN_FRACTION`, `title_evidence()` pure metric, `evaluate_titles()` replacing the `not-checked` stub |
| 3 | `scripts/lib/lookcheck.py` | `evaluate()` takes the per-title frame pairs instead of a `titles: bool` flag |
| 4 | `scripts/deliver.py` | `_verify_look` picks `t_in` per title and one witness, clamped out of the fade ramps; samples and wires the findings into the existing no-waiver refusal |
| 5 | `scripts/lib/geometry.py`, `scripts/lib/safezones.py`, `scripts/lib/models.py` | the two deletions and the one wiring from §6 |
| 6 | `docs/backlog.md` | the reworded §6 line, the closed rows, the new deferrals |

**Not in this slice, on purpose:** libass/ASS rendering and per-episode titles
(both features, neither a pre-run risk), and generalizing the gate to read the
text itself (§10).

---

## 8. Testing

- **Unit, pure.** `band_rows` against each position, scale, and a stair; the
  zone refusal (a stair that fits vs one that does not); `title_evidence` on
  hand-built arrays — ink present, ink absent, a multiplicative darkening,
  a shifted picture.
- **Real ffmpeg, with a control that must not move.** Encode the shared fixture
  twice, with and without a title, and assert the gate passes one and refuses the
  other. Add the vignette-0.60-no-title case explicitly: §2.1 is the measurement
  that says the obvious metric passes it, so that case is the anti-regression pin
  for the metric choice itself.
- **The fade pair.** Both §4 hazards get a test: a title whose window sits
  entirely inside a fade-in reports `not-checked` rather than failing, and the
  witness is never drawn from a ramp.
- **Mutation battery.** Every constant, both clamps, the best-of-witnesses rule,
  the sign of the master subtraction, and the zone refusal — each mutated, each
  required to redden a named test. Run under `PYTHONDONTWRITEBYTECODE=1`
  (2026-08-18's finding: a one-byte edit can match the previous row's size and
  mtime-second, and CPython then serves the stale `.pyc`).

---

## 9. Deferred — these become backlog rows

- **Titles in the probe.** `probe.py` renders episode frames through reframe's
  chain; titles are burned at `deliver`, so there is no cheap way to preview
  them. Converging a title's position still costs a reel encode.
- **The gate reads no text.** Proving ink appeared is not proving the words are
  the author's. OCR would close it and brings a dependency; nothing asks yet.
- **A wrong font passes.** Any font puts ink in the band. Detecting the *wrong*
  font needs the rendered glyph metrics compared against the resolved face —
  possible with the PIL metrics `_layers` already computes, filed not built.
- **The one-character hole** (§3.4).
- **`x`-axis containment.** The band is rows only. A title wider than the safe
  zone's left/right margins is not checked here — `(w−tw)/2` centres it, so it
  overflows only on a very long line at a large `scale`, and the horizontal
  margins are the narrowest part of the `tiktok`/`reels` tables.
- **Real-footage calibration of the constants beyond one reel.** All three are
  measured against the 2026-08-03 run's delivered reel plus one synthetic corpus.
  A second shoot is the cheapest next evidence.

---

## 10. Honest limits

**The gate proves ink, not text.** It answers one question — *did the drawtext
stage put marks where this title said it would?* — and it answers it well: 110
title-free frame pairs produced exactly zero evidence, at a max-depth vignette
and a re-encode. It does not read the words, judge the font, judge legibility, or
notice a title that is correct but ugly.

**It cannot see a title over matching pixels.** A white `plain` title over a
white sky produces almost no per-pixel change and would fail — correctly in the
sense that nobody can read it either, but the gate would report "did not render"
when the truth is "rendered invisibly". The message says which measurement was
taken so the difference is recoverable; the `bold-box` style, which carries its
own background, is immune.

**The `not-checked` arms are real holes, and they are named.** A reel whose
titles cover every instant has no witness; a title entirely inside a fade ramp
has no usable in-window frame. Both report `not-checked` and pass, exactly as
`FADE_SOURCE_MIN` and `VIGNETTE_FLOOR` already do — an honest hole beats a
threshold that pretends.

**The safe-zone refusal is geometry, not perception.** It proves a title's
predicted extent stays inside a *table of estimates* of where each app draws its
chrome. The table's own docstring already says those values shift with app
versions. Nothing here has looked at a real Instagram screen.

**One reel, one shoot.** Every number in §2–§4 comes from the 2026-08-03 run's
delivered reel and a synthetic corpus built for this slice. The separation is
wide — zero against 0.35% at the worst legitimate title — but wide separation on
one source is still one source.
