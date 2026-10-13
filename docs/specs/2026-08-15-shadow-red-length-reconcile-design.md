# Two P2 fixes — the shadow_red toe, and the length figures that never disagreed

_Last updated: 2026-08-15._

## 0. Why this slice exists

Two `S` rows from [backlog.md](../backlog.md)'s P2, taken as one slice because they are the
same kind of work: something already shipped is not what its own documentation says it is,
and the answer comes from a measurement rather than from a design.

- **`color.shadow_red_arg` has `highlight_red_arg`'s pre-fix sparse-anchor defect — worse.**
  Queued 2026-08-13 by the cinematic-look slice, which fixed the twin and measured — but did
  not fix — the mirror. §1.
- **The length figures do not reconcile.** The 2026-08-03 run showed a fitted spine of 27.7s,
  a `target_dur` of 30.317s and a rebuilt reel at 34.05s. The row exists to diagnose that
  before the P3 row "enforce `SPEC.length_s`" tries to gate a number three stages disagree
  about. §2.

Both halves overturned part of their own row. The probe found a **second** defect in
`shadow_red_arg` that the queued row does not mention and that the queued fix does not cure
(§1.3), and the length diagnosis found that **two of the three stages already agree** — the
third was stale, and nothing detects staleness (§2). §2 is therefore longer than the one
machine check it justifies.

---

## 1. `color.shadow_red_arg`

### 1.1 What was queued, and what the probe measured

`shadow_red_arg` lifts the red toe and returns to identity at `ret` (0.25 by default). Above
`ret` it pins identity with three anchors — `SHADOW_RED_ANCHORS = (0.50, 0.70, 0.85)` — plus
`1/1`. Three anchors pin the fitted spline **at three points, not the curve it draws between
them**; the twin `highlight_red_arg` learned this on 2026-08-13 and densified, and its
docstring recorded that `shadow_red_arg` had the identical sparseness, measured at **−6**.

Re-measured here with the same lossless method (a 256-step `R=G=B=x` rawvideo ramp pushed
through the bare fragment, no encode — `tests/integration/test_reframe.py::_ramp_r_lut`):

| `lift` at the shipped `ret=0.25` | identity-region deviation | worst at |
|---|---|---|
| 0.05 | +0 / −1 | code 70 |
| 0.10 | +1 / −3 | code 78 |
| 0.20 (`SHADOW_RED_MAX`) | +1 / **−6** | code 79 (x = 0.310) |

The −6 is confirmed, and its location is the point: **code 79 is x ≈ 0.31**, inside the gap
between `ret = 0.25` and the first anchor at 0.50. It is not a diffuse sag, it is the spline
diving into the unpinned hole immediately after the kink.

Scanned across the whole currently-accepted domain (`lift ∈ [0, 0.20]`, `ret ∈ (0, 0.45]`) the
same deviation reaches **−66** at `ret = 0.05, lift = 0.20`. The shipped configuration is the
mild end of this defect, not the typical one. §1.3 narrows that domain; the numbers this slice
is judged against are the post-refusal ones in §1.2.

### 1.2 The fix — density derived from `ret`

Replace the three hardcoded anchors with identity anchors every **0.05** from `ret` up to and
including 1.0, derived from `ret` rather than written down, so a caller passing a non-default
`ret` gets a dense region too instead of silently falling back to sparsity. This is exactly
the shape `highlight_red_arg` uses below its `knee`, transposed to the other side.

Measured over the domain that survives §1.3's refusal — `lift` 0.01…0.20 step 0.01, `ret`
0.05…0.45 step 0.05, every pair with `lift < ret`:

| anchors above `ret` | worst \|dev\| | at the shipped `ret = 0.25` | non-monotone cells |
|---|---|---|---|
| three sparse (today) | **14** | +1 / −6 at `lift` 0.20 | none |
| step 0.10 | 3 | +0 / −2 at `lift` 0.20 | 1, a single −1 code |
| **step 0.05** | **1** | **+0 / −0 at every legal `lift`** | 3, a single −1 code each |

At the shipped `ret` the densified curve is exactly identity above the return point for every
legal lift from 0.01 to `SHADOW_RED_MAX` — not "small", zero.

**Fix 1 (whole-branch review, 2026-08-15): the row above is a `ret`-step-0.05 grid, and its
"1"/"3 cells" read as domain absolutes rather than what that grid could see.** Re-measured at
`ret` step **0.01** (same `lift` step 0.01, same domain, same real-ffmpeg ramp probe) — the
resolution the shipped `ret = 0.25` is not privileged against:

| grid | worst \|dev\| | at the shipped `ret = 0.25` | non-monotone cells |
|---|---|---|---|
| `ret` step 0.05 (table above) | 1 | +0 / −0 at every legal `lift` | 3 |
| **`ret` step 0.01** | **2** (`ret`=0.04/`lift`=0.03; also `ret`=0.11/`lift`=0.10) | **+0 / −0 at every legal `lift`** | **15** |

Both grids agree on the number that matters — the shipped `ret` is exactly identity at every
legal `lift` — because 0.25 is on both grids. They disagree on the domain-wide worst case
because the coarser grid only ever tested `ret` at multiples of 0.05: the three non-monotone
cells it found (`ret`/`lift` 0.15/0.14, 0.20/0.18, 0.20/0.19) are exactly the subset of the 15
whose `ret` happens to land on that grid. The other 12 cells carry a `ret` the 0.05-step grid
never tried at all (0.13, 0.14, 0.16, 0.17, 0.18, 0.19, 0.21, 0.22, 0.23). The widest
`ret − lift` gap among all 15 is **0.03**, not the "within 0.02" the coarser grid implied.
Every cell is still a single-code drop in the near-flat toe, and it is still the case that the
shipped `ret` carries none of them.

### 1.3 The second defect — `lift >= ret` inverts the toe

The same grid scan showed the curve is **non-monotone** in 8 of 45 cells. A non-monotone
transfer curve bands. Densifying does **not** fix it: the same 8 cells stay non-monotone at
step 0.10, and step 0.05 adds a ninth (`ret = 0.10, lift = 0.10`). Anchors above `ret` cannot
reach it, because it does not live above `ret`.

It is not a spline artifact at all. The toe maps

```
x ↦ x + lift · (1 − x / ret)
```

whose slope is `1 − lift/ret`. Once `lift > ret` that slope is **negative** — the mapping
literally decreases, by construction, before ffmpeg fits anything. Every non-monotone cell
has `lift ≥ ret`, and no cell with `lift < ret` is non-monotone. At `lift == ret` the toe is
exactly flat and 8-bit rounding decides.

A kink-free toe does not rescue it either: a cosine taper arriving at `ret` with zero slope
measures **worse** — 11 non-monotone cells, worst drop −6 codes — because the flattened
approach makes the early slope steeper still. Rejected.

So the fix is a refusal, not an anchor: require `lift < ret`. The existing bounds allow
`ret = 0.10` with `lift = 0.20`, which inverts. At the shipped `ret = 0.25` and
`SHADOW_RED_MAX = 0.20` the refusal **can never fire** — it guards only a caller passing a
non-default `ret`, the same reachability class as the twin's `knee`.

The refusal alone is what makes the curve monotone: swept at 1% lift resolution over
`lift < ret`, the **shipped** sparse curve has **no** non-monotone cell. It is the refusal,
not the densification, that closes this one.

### 1.4 Why the step is 0.05 here and 0.10 there

`highlight_red_arg` steps 0.1 and accepts a +2/−1 residual. This curve's kink is steeper — it
returns from a lift to identity over a range of `ret` rather than easing across a wide
shoulder — so 0.1 still leaves −2 where it ships, and −3 at the domain's worst, while 0.05
leaves exactly nothing at the shipped `ret`. (At `ret` step 0.05 that last figure also read as
"at most one code anywhere legal" domain-wide; §1.2's `ret`-step-0.01 addendum found the true
worst is 2.) Fifteen control points instead of four cost nothing; they are characters in a
filter string.

The trade is not free and the coarse first scan hid it further than it first appeared: at
`ret` step 0.05, **0.05 has three single-code non-monotone cells to 0.10's one.** At `ret`
step 0.01 (§1.2, the resolution the shipped `ret` is not privileged against) 0.05's own count
is **fifteen** — the 0.10 comparison was not re-run at that finer step, so it stays at "1" here
on purpose, cited only at the resolution it was actually measured at. All fifteen sit where
`lift` is within 0.01–0.03 of `ret` (not "0.01–0.02"), i.e. where the toe's slope `1 −
lift/ret` is already near zero, so the output is flat over several input codes and one
rounding step reads as a drop — quantization at a deliberately flat region, not spline
banding. Chosen 0.05 for the 3× better identity fidelity in the region the defect is actually
about, with the wobble recorded in §6 rather than hidden.

The divergence from the twin is deliberate and recorded in both docstrings so the next reader
does not "fix" the inconsistency back.

---

## 2. The three length figures

### 2.1 What the run's own artifacts say

Every number below is read out of `~/Downloads/untitled folder`, the 2026-08-03 run, not out
of the summary that queued the row.

| figure | value | what it actually measures |
|---|---|---|
| `SPEC.length_s` | 30.0 | the brief |
| `PACING.target_dur` | 27.7047 | a spine fitted at tempo **140.625** |
| `EDL.md` header | "32.4s · target 30.7s" | sum of `dur` (source consumed) |
| `EDL.target_dur` | 34.072 | sum of `play_dur()` (screen time) |
| `out/REEL_v1.mp4` | 34.051 | the delivered master |

Two decisive checks:

- `sum(play_dur())` over the EDL's episodes is **34.0724** against `EDL.target_dur` of
  **34.072** — a difference of **0.0004s**, which is the rounding applied when the field is
  written. Episode 5 carries a ramp (`at 3.42, factor 0.5, ease 1.0, hold 0.8`) whose
  `ramp.ramp_extra` is **1.628427s**; source-consumed 32.444 + 1.628 = the played total. The
  EDL is internally consistent.
- `work/reel/reel_report.json` records its own length check as `dur 34.051 / target 34.072 /
  pass`. Master and EDL agree to **21ms** — under one frame at 30fps (33.3ms).

So the reel and its EDL never disagreed. What disagreed was `PACING.json`, and the file
mtimes say why:

| artifact | written | tempo |
|---|---|---|
| `EDL.md` | Aug 3 **11:28** | — |
| `PACING.json` | Aug 3 **13:14** | **140.625** |
| `MUSIC.json` | Aug 3 **22:29** | **110.294** |
| `EDL.json` | Aug 3 **22:40** | — |
| `out/REEL_v1.mp4` | Aug 3 **22:48** | — |

The spine is **nine hours older than the music** and was fitted to the Marilyn Manson track
that was later swapped out. Its slots miss their episodes by up to **+1.28s** (deltas
+0.70 / +0.49 / −0.10 / +0.21 / +0.99 / +1.16 / +1.28 / +0.00), far past the half-beat snap,
so the EDL that shipped was never bound to this spine at all.

### 2.2 The one live defect

`edit_plan build` is now handed **both** `--pacing` and `--music` — the outro fit put them in
the same call — and it does not compare them. `Spine.tempo` 140.625 against `MusicSpec.tempo`
110.294 is a contradiction any stage could have caught for free, and none does.
`_bind_pacing`'s half-beat guard is a *duration* guard: it fires only when a stale spine is
actually bound, and it never says anything about which track the spine came from.

`scripts/pacing.py` builds the spine straight from `MusicSpec.tempo`, so a freshly-run pacing
agrees by construction. The hole is only in the consumer.

**The fix:** `build_edl` refuses when both are supplied and the tempi differ by more than
`_TEMPO_TOL = 0.5` BPM, naming the remedy (re-run pacing against this MUSIC.json). Half a BPM
is far below any musically meaningful difference and far above float round-trip noise — a
matching pair is bit-identical, because the spine copies the number.

### 2.3 What was already fixed, and what was never in the comparison

- **`EDL.md`'s "32.4s"** is the sum of `dur`, which ignores the ramp and is 1.6s short of the
  reel. It is **already fixed**: `edl.to_markdown` sums `play_dur()`
  ([edl.py:351](../../scripts/lib/edl.py:351)). The run's markdown is eleven hours older than
  its own `EDL.json` and predates the speed-ramp slice entirely. Historical, not live.
- **`SPEC.length_s` = 30.0** was never one of the disagreeing figures — nothing enforces it,
  which is its own P3 row. The reel overran the brief by 4.05s with no gate. That row is the
  fix; this one is its diagnosis, and the diagnosis says the row is **unblocked**: the target
  the enforcement would gate (`EDL.target_dur`) is already the same number the master
  delivers.

### 2.4 "30.317" is not in the artifacts

The queued row cites a `target_dur` of 30.317s. It is not in `EDL.json` (34.072), not in
`PACING.json` (27.7047), not in `reel_report.json`, and no `.md`, `.txt` or `.log` in the run
contains the string `30.3`. `EDL.md` prints `target 30.7s`, one decimal, so the figure it
rounded was ≈30.7 at 11:28 — not 30.317. The number most likely came from a `_log` line in
the session transcript. Recorded as unreproducible rather than quietly replaced with a
figure that *was* found.

---

## 3. What this slice builds

1. `color.shadow_red_arg`: identity anchors derived from `ret` at step 0.05; a `lift < ret`
   refusal; `SHADOW_RED_ANCHORS` deleted; the docstring rewritten onto the measured numbers
   and the deliberate 0.05-vs-0.10 divergence.
2. `edit_plan.build_edl`: a `_TEMPO_TOL` cross-check that refuses a spine fitted to a
   different track, placed beside the existing `--music`-without-`--pacing` log so both
   pacing/music consistency concerns live in one place.
3. Docs: both backlog rows closed with the measurements above; the P3 `SPEC.length_s` row
   annotated as unblocked; new rows for what §6 leaves open.

## 4. Testing

- A real-ffmpeg ramp probe mirroring
  `test_highlight_red_sub_knee_residual_is_small_and_monotone`: at `ret`'s default and at
  `SHADOW_RED_MAX`, the identity region stays inside a bound strictly tighter than the −6 it
  ships with today, so a regression to sparse anchors fails.
- Unit refusals for `lift >= ret` at both the `>` and `==` boundaries.
- Unit refusal for a tempo mismatch, plus the paired proof that a matching pair still builds
  — a refusal with no partner test is a refusal nobody has watched *not* fire.

## 5. Out of scope

- Enforcing `SPEC.length_s` (its own P3 row, now unblocked).
- Making pacing's round trip a fixed point (its own P2 row, M-sized, and it rewrites
  `Spine`/`PACING.json` — the music-digest idea in §6 belongs with it, not here).
- `highlight_red_arg`'s shoulder monotonicity near `pull ≈ 1 − knee` for `knee ≥ 0.7` — a
  different function, already a P3 row, still unreachable.

## 6. Honest limits

- **Equal tempo does not prove the same track.** Two tracks can sit within 0.5 BPM of each
  other; the check catches a swap, not an identity. The strong version records the music
  file's digest on `Spine` — a contract and format change, deferred to the pacing-fixed-point
  row that already rewrites that file.
- **The check only fires when both flags are passed.** `edit_plan build --pacing` alone has
  nothing to compare against, and the hand-authored `edl_to_reel` front door never sees this
  stage at all — the same "no silent bypass, not no bypass" boundary the rest of the pipeline
  carries.
- **The refusal `lift < ret` cannot fire in the shipped configuration.** It is a guard for a
  caller that does not exist yet. Its value is that the function can no longer emit an
  inverting curve, not that anything today would have.
- **The densified curve keeps a one-code wobble as `lift` approaches `ret`.** At `ret` step
  0.01 (design Fix 1, 2026-08-15) there are **15** such cells, not three — the three first
  named (`ret/lift` 0.15/0.14, 0.20/0.18, 0.20/0.19) are exactly the subset whose `ret` lands
  on the coarser 0.05-step grid the original scan used. They span `ret` 0.13–0.23, up to
  **0.03** away from `lift` (not "within 0.02"), where the toe's slope is near zero. Step 0.10
  has one such cell (not re-measured at the finer step); neither step removes them, and the
  shipped `ret = 0.25` has none at any legal lift. Not fixed, measured (§1.2/§1.4).
- **The anchor step is measured on a synthetic ramp, not on footage.** The probe reads the
  transfer curve exactly, which is the right instrument for "does the spline sag" — but
  whether −6 codes in the shadows was visible on this reel was never measured, and is not
  measured here either.
- **Nothing rechecks the length agreement on the next run.** §2 establishes that EDL and
  master agreed *in that run*; the reel's own length check already compares them every time,
  which is why no new gate is added — but the diagnosis is a snapshot, not a monitor.

## 7. Deferred → backlog rows

Per [the deferral rule](../development-workflow.md#closing-a-slice--what-enters-the-backlog), every
item in §5 and §6 that is not already queued gets a row:

- Record the music file's digest on `Spine` so a stale spine is caught by identity rather
  than by tempo — folded into the existing P2 "make pacing's round trip a fixed point" row.
- No new row for `SPEC.length_s` enforcement or the pacing fixed point: both already exist.

## 8. Files

- `scripts/lib/color.py` — `shadow_red_arg`, `SHADOW_RED_ANCHORS` (deleted).
- `scripts/edit_plan.py` — `_TEMPO_TOL`, the cross-check in `build_edl`.
- `tests/lib/test_color.py`, `tests/integration/test_reframe.py`, `tests/lib/test_edit_plan.py`.
- `docs/backlog.md`, `docs/build-status.md`, `CLAUDE.md`.
