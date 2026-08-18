# The tone transfer goes luma-only, and the ruler gets fixed — together

**Date:** 2026-08-19
**Status:** design
**Sources:** backlog P3 Colour, two paired rows — "make the tone transfer
**luma-only**" and "`color_measure.measure_profile` histograms a **160-wide**
frame … **must not be changed alone**" ·
[mood-grade](2026-08-17-mood-grade-design.md) §3 ·
[deferred-measurements](2026-08-18-deferred-measurements-design.md) §3/§3.4 ·
[colour-stage](2026-07-26-colour-stage-design.md)

---

## 0. The row's premise is wrong, and the measurement says so

The queued row reads: *"the diagnosed cause of the conductor's whole residual is
that `curves=all` is per-CHANNEL while the target is a luma statistic."* It is
not. Measured end to end on the run's own two cameras, worst |residual| across
p5/p50/p95:

| instrument | transfer | drone frame | Canon frame |
|---|---|---|---|
| 160-wide (shipped) | `curves=all` (shipped) | **9.0** | 3.0 |
| 160-wide | luma-only | 8.0 | 2.0 |
| full width | `curves=all` | 5.0 | 3.0 |
| **full width** | **luma-only** | **2.0** | **1.0** |

The transfer alone buys **1 unit of the 9**. The ruler alone buys 4. Only the
pair closes it — 9.0 → 2.0 on the frame that was worst, 3.0 → 1.0 on the other.

So the rows really are inseparable, as the backlog insisted, but not for the
reason it gave. It expected the measurement fix to make things *worse* in
isolation (§3.4: "−1 → −7"). It does not — it improves 9.0 → 5.0. §3.4's
reading is explained in §4.

---

## 1. What the 160-wide downscale actually does

`measure_profile` decodes `scale=160:-2,format=gray` and histograms that.
Measured on the run's drone frame:

| | p5 | p50 | p95 |
|---|---|---|---|
| at 160 wide | 73 | 137 | **196** |
| at full width | 73 | 137 | **205** |

**9 units low at p95, and only at p95.** Specular highlights — sun on water —
are small and bright, so a 12× area reduction averages them into their
neighbours. p5 and p50 are bulk statistics and survive; p95 is exactly the
statistic that lives in the small bright places.

The cost of not downscaling, measured over three runs each on the same 4K clip:

| | per measure | samples histogrammed |
|---|---|---|
| `scale=160:-2` | 61.0 ms | 14 400 |
| full width | 66.9 ms | 2 073 600 |

**+5.9 ms, +10%.** The decode was always the cost; the scale filter never was.
144× the samples for a tenth more time.

---

## 2. Why `lutyuv` and not `curves`

Three reasons, in descending order of how much they matter.

**2.1 It is a luma transfer, and the target is a luma statistic.** `curves=all`
applies the same non-affine map to R, G and B separately, and
`luma(T(R),T(G),T(B)) ≠ T(luma(R,G,B))` for any non-affine T. `lutyuv=y=`
transforms the Y plane and leaves U and V untouched.

**2.2 Chroma comes out bit-identical.** Measured mean chroma radius
`sqrt((U−128)² + (V−128)²)`:

| frame | source | after `curves` | after `lutyuv` |
|---|---|---|---|
| drone | 30.19 | 29.47 | **30.19** |
| Canon | 5.96 | 5.25 | **5.96** |

Unchanged to the last decimal, because U and V are never written. The backlog
predicted this effect but named its direction wrong — it said a per-channel
curve "also raises saturation". On these frames the authored curves are
*compressive* (p95 196 → 192), so per-channel **lowers** it. The general claim
holds and the sign does not: per-channel moves saturation, and which way depends
on the curve.

**2.3 There is no spline to fight.** `curves` fits a natural cubic through the
points it is given, and `tone_arg` carries three separate defences against that
— dense sampling, joining the anchors to the grid, and a minimum gap so two
control points never nearly coincide (which makes ffmpeg emit **no frame at
all**). `lutyuv` evaluates its expression once per input code and stores a table.
The four segments **are** the map. Measured against the intended map over all 256
codes: worst deviation **0.98 codes**, mean 0.496 — pure integer rounding — and
monotone.

That deletes `TONE_SAMPLES` and the whole grid apparatus from the emitted
fragment. The knots stay; the scaffolding that protected them from the spline
goes.

---

## 3. The range mismatch — the real reason this is not a free swap

The backlog said luma-only "is not a free swap" because of saturation. The
saturation change is real (§2.2) but it is not the trap. This is:

| | black | white |
|---|---|---|
| `measure_profile`'s `format=gray` | **0** | **255** |
| the raw Y plane `lutyuv` sees | **16** | **235** |

Measured, on both a lavfi source and a real encoded yuv420p h264 file. A mid
grey reads 128 through the gray path and **126** on the Y plane.

`curves` never had to care: it operates on RGB, so swscale converts tv→full on
the way in and back on the way out, for free and invisibly. `lutyuv` operates on
the plane as stored. Feeding it anchors measured in full range would land every
anchor at the wrong Y, on every episode, with nothing failing.

So the emitted expression converts at both ends —
`v = (val − 16) × 255/219` in, `16 + result × 219/255` out — and the two
endpoints are pinned by a test against the measured 16 and 235, not against a
constant somebody typed.

---

## 4. Why §3.4's warning does not reproduce

deferred-measurements §3.4 recorded that removing the downscale in isolation made
the delivered p95 go from −1 to **−7**, and concluded the two errors cancel. This
slice measures 9.0 → **5.0** for the same change — an improvement.

The difference is which instrument each end used. The conductor **measures** the
source, **computes** a target from those measurements, **authors** a curve
against them, and the residual is then judged by measuring the output. §3.4
changed the verification while leaving the authoring at 160 wide, so it compared
a curve built for one ruler against a reading taken with another; the −7 is the
9-unit reading gap re-appearing with its sign flipped, not a property of the
transfer.

Changing the instrument means changing it **everywhere** — source, target and
verification — which is what §0's table does. The pairing conclusion survives;
the mechanism recorded under it does not.

---

## 5. A finding this slice did not go looking for: the `lutrgb` ban

`lutrgb` is banned repo-wide, machine-enforced by the landmine lint, on the
stated ground that it "produced black frames". No mechanism is recorded anywhere.
Since this slice adopts a sibling from the same filter family, the ban had to be
understood before it could be sidestepped. It does not reproduce:

| fragment | mean RGB out |
|---|---|
| no filter (control) | 95.00 |
| `lutrgb=r=val:g=val:b=val` | 95.00 |
| `lutrgb=r='val':g='val':b='val'` | 95.00 |
| `lutrgb=val` | 95.00 |
| `lutrgb=r=1.2*val:…` | 114.00 |
| `colorchannelmixer=rr=1.2:…` (the sanctioned op) | 114.00 |

Identity is exact in every spelling and the 1.2× matches the sanctioned filter
to the code.

**The ban stays.** One synthetic probe on one ffmpeg build does not overturn a
landmine that was written from a real corrupted render, and nothing in this slice
needs it lifted — `lutyuv` is a different filter and the lint's substring match
does not touch it. What is worth recording is a candidate for the original
misdiagnosis: [check_episode.py:56](../../scripts/check_episode.py) calls it "the
seek/lutrgb corruption", so the two were seen **together**, and the `-ss`-after-`-i`
landmine produces black frames on its own. Filed as its own backlog row, not
acted on here.

---

## 6. What this slice builds

| # | Where | What |
|---|---|---|
| 1 | `scripts/color_measure.py` | `measure_profile` drops `scale=160:-2` |
| 2 | `scripts/lib/color.py` | `TV_LO`/`TV_SPAN`, `tone_arg` emits `lutyuv=y=` over four segments with explicit range conversion; `TONE_SAMPLES` and the grid retire |
| 3 | `scripts/reframe.py` | `verify_tone` keeps its monotonicity refusal, re-aimed at the new fragment |
| 4 | goldens | every pinned tone fragment and every measured anchor moves — re-pinned, not loosened |

**Not in this slice:** lifting the `lutrgb` ban (§5); mood as chroma, which needs
the cross-episode white-balance actuator that is deferred elsewhere; and
crop-accurate tone measuring, which is a different row.

---

## 7. Testing

- **Pure.** The four-segment expression against `_lerp` over all 256 codes; the
  range conversion against the measured 16/235 endpoints; the degenerate
  `src[0] == 0` segment.
- **Real ffmpeg.** The ramp probe: worst deviation ≤ 1 code and monotone. The
  saturation invariance: chroma planes **byte-identical** before and after, which
  is a control `curves` provably fails.
- **The pairing, end to end.** Both frames, both instruments, both transfers —
  the §0 table as a test, so a future change that fixes one half alone reddens
  with the number that says which half.
- **Mutation battery** under `PYTHONDONTWRITEBYTECODE=1`.

---

## 8. Honest limits

**Two frames, one shoot, one ffmpeg.** Every number here comes from one drone
frame and one Canon frame out of the 2026-08-03 run, measured on
`config/ffmpeg.env`'s 8.1.1. The separation is wide and the mechanism is
arithmetic, but the calibration is not broad.

**The residual is not zero.** 2.0 and 1.0 units remain, and they sit at p95 —
the shoulder above the top anchor is a deliberate gentle slope
(`TONE_TOP_SLOPE`), so the output's top percentile is not the map of the input's.
That is the design working as written, not an error, and nobody has asked whether
the shoulder's slope is right.

**The grade changes visibly.** Chroma no longer rides the tone curve, so a
graded reel will look different — more saturated where the curve compresses, less
where it lifts. This is the correct behaviour for an operation named "tone" and
it is still a change nobody has looked at on a screen.

**Nothing checks the grade against a person.** `check_reel`'s colour gate
compares episodes to each other, and they all move together. The gate this slice
improves is the conductor's own arithmetic, not anyone's judgement of the
picture.

**The range constants assume tv.** `TV_LO`/`TV_SPAN` are correct for what
`reframe` emits today (untagged yuv420p, tv range, per colour-stage §8/§9). A
genuinely full-range source reaching this filter would be mapped through the
wrong conversion. The tests pin the endpoints against the pipeline's own output,
so a change in what reframe emits reddens — but nothing here inspects a *foreign*
file's range tag.
