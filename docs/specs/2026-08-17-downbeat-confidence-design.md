# Downbeat confidence — design (2026-08-17)

**Slice:** backlog P2, "calibrate the downbeat detector on more than one track"
(music-outro-fit §11.3). **Size:** S.

## 0 · What the row asked, and what the measurement answered

The row asked for a second genre as "the cheapest next evidence" for three
first-cut constants. Four unmeasured tracks were already on disk beside the one
the detector was tuned on, so the evidence cost nothing but decode time.

The answer is not a re-tuned constant. **On four of the five tracks the detector
has no signal at all, and no setting in a 32-cell sweep recovers one.** The
detector does not need calibrating so much as it needs to know when it is
guessing — which is the third "first-cut constant" the row named and the code
never had.

So this slice is two things: a band edge moved onto a measured plateau, and the
confidence gate the queue has been describing as though it existed.

## 1 · The harness, and the control

Five tracks from the 2026-08-03 run's own music cache. The shipped track is
**Katrina & The Waves — Walking On Sunshine** (`MUSIC.json`: tempo 110.294,
`start_offset` 46.0, `duration` 42.0) — *not* a Manson track, which is what the
build-status prose reads like at a glance; Manson is the track the stale
`PACING.json` belonged to.

Re-running the design's own §3 measurement on that exact window reproduces it:

| | phase means | ratio | bars |
|---|---|---|---|
| music-outro-fit §3 | 48.01 / 54.65 / 42.03 / 79.31 | 1.887 | 14/18 |
| this slice | 49.61 / 55.39 / 41.46 / 88.89 | 2.144 | 15/18 |

Same winner (phase 3), same ordering, one bar apart — reproduced in kind, not to
the digit (the residual is decode start, not method). The harness is therefore
trustworthy for the four tracks that follow.

Throughout, two statistics: **margin** = the winning phase's mean over the
runner-up's, and **hit-rate** = how often the winning phase's beat is the loudest
of its own bar. Hit-rate has a known chance level (25% for 4/4), which is what
lets a cell be judged with no annotated downbeats — and none exist on disk.

## 2 · The band edge is mistuned on its own calibration track

At the shipped `_BAR_WIN = 0.10`, sweeping the band edge over the control:

| Hz | 60 | 80 | 100 | **150** | 200 | 250 | 350 | 500 |
|---|---|---|---|---|---|---|---|---|
| hit | **93%** | 92% | 86% | **88%** | 76% | 49% | 34% | 43% |
| margin | **2.04** | 1.87 | 1.84 | **1.67** | 1.24 | 1.09 | 1.02 | 1.07 |

But the decisive difference is not the 5 points of hit-rate — it is stability
across the *other* constant. At 60 Hz the detector holds a plateau; at 150 Hz it
sits on a knife edge one window-width from failing:

| `_BAR_WIN` | 0.05 | 0.10 | 0.15 | 0.20 |
|---|---|---|---|---|
| 60 Hz | 91% | 93% | 93% | 59% |
| 150 Hz | **32%** | 88% | **59%** | 49% |

A plateau is what a real signal looks like; a spike is what a fitted one looks
like. `_LOW_HZ` moves **150 → 60**.

(Every band edge collapses at `_BAR_WIN = 0.20`: a ±0.2s window is 0.4s wide
against a 0.544s beat period at 110 BPM, so each beat's window starts eating its
neighbours. That is arithmetic, not evidence about the band.)

**Honest**: this is still a constant tuned on one track. The four other tracks
cannot vote, because they have no signal to vote with. The improvement is in how
the number was measured (a plateau, over two axes), not in how much music it was
measured on.

## 3 · Four of five tracks carry no downbeat signal

Best cell in the whole 8×4 sweep, per track:

| Track | genre | best cell | hit-rate | margin |
|---|---|---|---|---|
| Walking On Sunshine | 60s pop | 60 / 0.10 | **93%** | **2.04** |
| Manson — God's Gonna Cut You Down | industrial | 80 / 0.20 | 48% | 1.00 |
| Manson — Tainted Love | industrial | 250 / 0.05 | 50% | 1.02 |
| Kygo — Firestone | tropical house | 200 / 0.20 | 41% | 1.03 |
| MGMT — Electric Feel | psych pop | 150 / 0.10 | 38% | 1.02 |

Chance is 25%. The four sit at 38–50% with margins of 1.00–1.03 — and their
optima scatter across the grid (80/0.20, 250/0.05, 200/0.20, 150/0.10), which is
the signature of fitting noise rather than finding signal. A real optimum sits in
a consistent place, as the control's does.

**For at least one genre the premise itself is false.** The detector assumes the
bar's downbeat carries the kick and the other beats do not. Four-on-the-floor
house puts a kick on *every* beat, so there is nothing for the band to
discriminate — Kygo's margin is 1.01 because all four phases are equally loud,
not because the measurement is bad. No band edge fixes a premise failure.

## 4 · The statistic the design quotes does not discriminate

music-outro-fit §3 offers **max/min = 1.887** as the evidence that the bass band
works. It does not carry that weight. God's Gonna Cut You Down scores max/min
**1.782** — within 6% of the control — while landing 36% hit-rate and a 1.032
margin. Its ratio is high because one phase is *quiet*, not because the winner is
*loud*.

**max/2nd** separates cleanly: control 2.04 against 1.01 / 1.03 / 1.07 / 1.09.
That is the statistic the gate is built on, and §5 measures how far the
separation holds.

## 5 · The gate, and where its threshold comes from

`_downbeat_phase` is a bare `argmax` today: it always returns a phase, however
flat the four means are. On the four tracks above it returns one confidently,
`analyze` fills `bars`, and `outro.fit_outro` lands the reel's end on a "bar
line" that is a beat picked out of noise. Nothing reports low confidence, which
is the §12 silent-corruption shape.

The gate: **below `_PHASE_MARGIN` the detector returns `None`**, `bars` stays
empty, and the outro fit takes its existing `unchanged` rung.

The threshold cannot be read off whole tracks, because `analyze` measures a
`duration`-long *window* and fewer beats make the per-phase means noisier — which
can push a no-signal track's margin **up** by luck. Measured directly: 30s and
42s windows slid across all five tracks at 60 Hz / 0.10, step 15s.

| | windows | min | median | max | ≥1.3 | ≥1.5 |
|---|---|---|---|---|---|---|
| **CONTROL** 30s | 14 | 1.122 | 2.258 | 2.753 | 11 | **10** |
| **CONTROL** 42s | 13 | 1.279 | 2.155 | 2.766 | 12 | **11** |
| four others, 30s | 50 | 1.003 | ~1.09 | **1.339** | 3 | **0** |
| four others, 42s | 47 | 1.002 | ~1.10 | **1.351** | 2 | **0** |

The worry was correct: **1.3 would let noise through** — three no-signal windows
reach 1.31–1.34 at 30s and two more at 42s. At **1.5** the separation is
complete: of **97** windows drawn from four tracks with no downbeat, **none**
reaches it; **21 of 27** control windows do.

`_PHASE_MARGIN = 1.5`.

**Its cost, measured, not estimated:** 2 of the control's 13 windows at 42s fall
below 1.5 (min 1.279), and 4 of 14 at 30s. So on music that genuinely has a
downbeat, roughly one window in six will be gated off and the outro fit will
honestly do nothing rather than fit. That is the trade this threshold buys, and
it is the right side of it: a missed fit costs the ending the slice was already
delivering before 2026-08-14; a false fit moves the reel's end onto a wrong line
and reports it as a bar.

### 5.1 · The two zero corners are opposites (as-built, found by this branch's review)

A ratio needs a divide-by-zero guard, and the first cut wrote it as
`ranked[1] <= 0.0 → None`. That is wrong in the direction that matters: a lone
loud phase against three silent ones is an **infinite** lead — the strongest
downbeat evidence the detector can see — and it was being refused, where the
ungated `argmax` it replaced got it right. A regression this slice introduced,
not one it inherited.

The corners are opposites and only one is `None`:

- `ranked[0] == 0` — no bass anywhere. No evidence. `None`.
- `ranked[1] == 0`, `ranked[0] > 0` — one phase, infinite lead. Return it.

**Reachable, not theoretical**: digital silence gives exactly 0.0 STFT magnitude,
measured — `ranked[1] == 0.0` compares true, so this is not a float-epsilon
argument. The mutation battery carries a row that reproduces the bug.

## 6 · What changes

- `beats._LOW_HZ`: 150.0 → 60.0, with §2's plateau recorded beside it.
- `beats._PHASE_MARGIN = 1.5`, new, with §5's separation recorded beside it.
- `beats._downbeat_phase`: returns `None` when `max/2nd < _PHASE_MARGIN`. The
  docstring's §3 numbers are replaced by this slice's, and its "onset strength
  does not work here" warning gains its sibling — the bass band does not work
  either on music whose kick does not mark the bar.
- `edit_plan`'s no-bars log names the third reason (low confidence) beside the
  two it already names (too few beats, an artifact predating the fields).

## 7 · What does not change

The empty-bars path already exists end to end and needs no work:
`fit_outro` returns its `unchanged` rung on `not bars`, `_apply_outro` returns
early, `edit_plan` logs. No contract field, no stage order, no ffmpeg stage, no
driver. `check_reel`'s advisory `outro` residual reads `EDL.outro`, not `bars`.

The synthetic unit test survives the re-tune unmodified — measured, not assumed:
its 60 Hz thump against a 1 kHz tick scores margin **35.36** at the new band edge
(6 STFT bins kept at 10.77 Hz each), winner unchanged. The test tone sitting
exactly on the new band edge is a coincidence worth naming, but not one that
needs a test edited to keep it green.

## 8 · Testing

- The gate returns `None` on a flat four-phase input, and a phase on a peaked
  one — the mutation check is flipping the comparison and watching a noise input
  produce bars.
- `analyze` leaves `bars` empty when the gate declines (the existing
  `test_analyze_leaves_bars_empty_when_the_phase_is_unknown` already covers the
  `None` contract; the new test is that a *low-margin real signal* reaches it).
- The existing synthetic bass-phase test runs unchanged at 60 Hz.
- The full suite, for the goldens the constant could move.

## 9 · Deferred (each gets a backlog row)

- **A real downbeat detector** — madmom or a trained model, instead of a
  bass-band heuristic. This is the honest fix for §3, and it is a slice with a
  new dependency, not a chore. **P3.**
- **Calibrate the positive class on more than one song** — §10's first limit.
  Everything here separates one positive track from four negatives. **P3.**
- **Report the margin rather than only acting on it** — `MusicSpec` could carry
  the measured confidence so a skill can say "this track has no bar grid, and
  here is how close it came". Not built: no consumer asked. **P4.**

## 10 · Honest limits

- **n = 1 for the positive class.** The negatives are well sampled (97 windows,
  four tracks, two genres-of-failure). The positive is 27 windows from **one
  song**. A threshold separating one positive from four negatives is a threshold
  fitted to one positive.
- **The gate proves the bass band has a phase preference, never that the phase is
  the musical downbeat.** On the control the two agree, checked by ear-free
  proxy (hit-rate) only. Nothing in this project verifies the bar grid against a
  human's reading of the song, and §9's first row is the only thing that would.
- **No ground truth was used anywhere**, because none is on disk. Hit-rate is a
  self-consistency statistic with a known chance level, which is weaker than an
  annotation and stronger than nothing.
- **`_LOW_HZ = 60` is still tuned on one track.** §2 improves the *method* of
  measuring it (a plateau over two axes rather than a single cell), not the
  breadth of the evidence.
- **Four-on-the-floor is diagnosed from one house track.** The reasoning is
  structural and convincing, and it is still n=1 for that claim too.
- **The gate makes the feature fire on less music, not more.** On this sample the
  outro fit would engage on 1 track of 5. That was already true on 2026-08-14 —
  what changes is that the other four now say so instead of silently landing the
  reel on a beat and calling it a bar line.
