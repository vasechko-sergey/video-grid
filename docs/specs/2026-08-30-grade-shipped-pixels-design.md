# Grade the pixels that ship — design

**Backlog: "Grade the pixels that ship" (P1/L), absorbing R2.1 and R3.1.**

`match_grade` measures each episode's **whole source frame at its window
midpoint** and authors a tone pair from that reading. The reel ships the
**tracked crop**. Those are different pixels, and the measurements below say the
difference is larger than the tolerance the conductor uses to decide whether to
grade at all — so the one stage that exists to make a reel read as one grade has
been aiming at a frame nobody sees.

The fix is a reordering, not a new instrument: tracking already runs exactly once
per episode, and it runs *after* the conductor only because it used to run later
for unrelated reasons. Move the seam, measure the crop, and the pure core of
`matchgrade` — `common_target`, `biased_target`, `plan` — does not change a line.

`color.tone_arg`'s own docstring already states the contract:

> The caller measures `src` on the episode's OWN crop (the pixels that ship, not
> the full frame), because a crop centred on a rider has a different histogram
> from the frame around it.

It has exactly one caller, and that caller does not.

---

## §0 — What was measured

Every number comes from the preserved 2026-06 run
(`/Users/serg/Downloads/untitled folder/`), read-only, through this repo's own
primitives: `out/EPISODES.json`, the eight `work/ep{i}/route.json`, the eight
`work/segments/ep{i}_raw.mp4`, and the eight delivered `out/ep{i}.mp4`.

**One preparation was required, and it is itself a finding.** `reframe.plan_render`
refuses the run's own segments:

> `ep1_raw.mp4`: color_range is pc (full, 0-255) and this pipeline's colour maths
> is written for tv (limited, 16-235).

That is the 0.3.1 range guard working on footage cut before the range contract
existed. Every measurement below was therefore taken on segments re-normalized
with `extract`'s own filter pair (`scale=in_range=auto:out_range=tv` +
`-color_range tv` + `-pix_fmt yuv420p`) into a scratch directory — so these are
numbers for **today's** engine, not for the engine that shipped the reel.

### §0.1 The conductor measures pixels that do not ship

One ruler on both sides (`format=gray`, the ruler `tone_arg` speaks): the whole
source frame at the window midpoint, which is what `match_grade` reads today,
against the tracked crop pooled over three frames, which is what ships.

| ep | whole frame (p5/p50/p95) | tracked crop (p5/p50/p95) | max \|Δ\| |
|---:|---|---|---:|
| 0 | 72 / 102 / 166 | 66 / 89 / 162 | **13** |
| 1 | 41 / 106 / 177 | 35 / 102 / 141 | **36** |
| 2 | 71 / 114 / 173 | 66 / 105 / 172 | **9** |
| 3 | 57 / 112 / 228 | 54 / 111 / 226 | 3 |
| 4 | 77 / 115 / 230 | 71 / 110 / 215 | **15** |
| 5 | 30 / 77 / 113 | 27 / 70 / 123 | **10** |
| 6 | 51 / 103 / 215 | 22 / 100 / 211 | **29** |
| 7 | 58 / 133 / 227 | 50 / 132 / 242 | **15** |

**Seven of eight exceed `matchgrade.MATCH_EPS = 4.0`**; median 14, max 36. The
measurement error is three and a half times the tolerance that decides whether an
episode is graded at all — so the conductor's `needs_tone` verdict is not
trustworthy either, in both directions.

### §0.2 The shipped reel does not converge

Three frames of each delivered `out/ep{i}.mp4`, per-episode median:

| ep | p5 | p50 | p95 | tone pair? |
|---:|---:|---:|---:|---|
| 0 | 71 | 88 | 160 | — |
| 1 | 35 | 109 | 170 | yes |
| 2 | 66 | 104 | 172 | — |
| 3 | 58 | 115 | 224 | yes |
| 4 | 68 | 103 | 215 | yes |
| 5 | 31 | 70 | 124 | yes |
| 6 | 27 | 109 | 221 | yes |
| 7 | 52 | 134 | 244 | — |

Spread across the reel: **p5 44, p50 64, p95 120**, against a `MATCH_EPS` of 4.0.
Five episodes carried an authored pair whose declared `tone_dst` was
`[20, 146, 255]`; **not one delivered episode is within 12 of that p50**, and the
closest (ep7, 134) is one of the three that were never graded.

The grade did exactly what it was told. It was told the wrong thing. ep6's pair
was `137 → 146` on the whole frame; its crop sat at 101, so the same curve
carried 101 to 109 — which is precisely what shipped.

Note also what the whole-frame ruler did to the pairs themselves: every one of
the five reads `p5 = 20` and `p95 = 255` on **both** sides. Sky and specular
water pin the outer anchors for every episode alike, so the conductor could only
ever move the midpoint. Measuring the frame does not merely mis-aim the grade —
it collapses two of its three anchors.

### §0.3 Measuring the crop converges it

Same footage, same frozen routes, same pure core. `tone_src` measured on each
episode's own crop (three frames, gray ruler), the common target recomputed from
those readings, every episode rendered through `plan_render`'s chain:

crop-based common target **52.0 / 103.5 / 191.5**

| ep | measured crop | delivered crop | residual |
|---:|---|---|---:|
| 0 | 66 / 89 / 162 | 60 / 104 / 187 | 8.0 |
| 1 | 35 / 102 / 141 | 50 / 108 / 189 | 4.5 |
| 2 | 66 / 105 / 172 | 53 / 105 / 187 | 4.5 |
| 3 | 54 / 111 / 226 | 51 / 102 / 189 | 2.5 |
| 4 | 71 / 110 / 215 | 53 / 102 / 188 | 3.5 |
| 5 | 27 / 70 / 123 | 53 / 105 / 188 | 3.5 |
| 6 | 22 / 100 / 211 | 51 / 103 / 189 | 2.5 |
| 7 | 50 / 132 / 242 | 49 / 102 / 188 | 3.5 |

**Residual max 8.0, median 3.5.** Delivered spread **44 / 64 / 120 → 11 / 6 / 2**.

This is not a lucky fit. Percentiles commute with a monotone map, and `tone_arg`
builds one — so the delivered crop's p5/p50/p95 land on the target *by
construction*. The residual is what quantization and the crop's own content
variation leave behind, which is why it is small and why a large one means
something actually broke.

### §0.4 Three frames is enough, and it costs nothing

| frames | residual max | residual median | measure pass, 8 episodes |
|---:|---:|---:|---|
| 3 | 8.0 | 3.5 | 5.2 s (0.65 s/ep) |
| 5 | 9.0 | 3.5 | 5.4 s |
| 9 | 9.0 | 3.5 | 5.7 s |

More frames buys nothing, because the residual is not sampling noise. `probe`'s
existing `FRAMES = 3` stands, and the barrier this design adds to phase 1 costs
five seconds on a run whose phase 1 costs minutes.

### §0.5 There are two rulers, and only one is the grade's

`probe._tone` computes luma in numpy from RGB with BT.601 weights.
`color_measure.measure_profile` reads ffmpeg's `format=gray`. `tone_arg` writes
the Y plane in tv range, which is what `format=gray` reads. probe's docstring
says the two "can differ by a code or so on the same frame". Measured on the same
eight crops:

| ep | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| \|Δ\| between rulers | 6 | 5 | 3 | 1 | 1 | 5 | 1 | 1 |

Up to **6 codes**, one and a half times `MATCH_EPS`. An operator converging a
grade by hand off `probe.json`'s numbers is reading a different instrument from
the one the conductor and the check use.

### §0.6 The negative class, and where the bar goes

What does the residual look like when something *is* broken? The cheapest real
failure is a grade that never reached the pixels — a stale target, an episode the
conductor skipped, a colour block dropped between authoring and render. That
residual is just the raw crop's distance to the target:

per-episode **29.5 · 50.5 · 19.5 · 34.5 · 23.5 · 68.5 · 30.0 · 50.5**, min **19.5**.

So the positive class tops out at **8.0** and the negative class starts at
**19.5**. `ReelCheckSpec.tone_match_max = 12.0` sits mid-gap: 1.5x above the
worst healthy reading and 1.6x below the best broken one. Both bounds come from
one shoot (§9.1).

### §0.7 The retry ladder moves the crop and does not move the tone

The reframe retry loop re-renders with adjusted `max_speed` / `smooth_window_s`
*after* the grade was authored, which looked like a way for the measured crop and
the shipped crop to disagree. Measured on four episodes, both ladder branches:

| ep | base | `max_speed x0.6` | `smooth_window_s x2` |
|---:|---|---|---|
| 0 | 60/104/187 | 60/104/187 | 60/104/187 |
| 2 | 53/105/187 | 53/105/187 | 53/105/187 |
| 5 | 53/105/188 | 53/105/188 | 53/105/188 |
| 6 | 51/103/189 | 51/103/189 | 51/103/189 |

Identical, every cell. The tone profile is a property of the **shot**, not of the
crop's exact offset — the ladder shifts the rect by tens of pixels within the
same content, where §0.1's difference is a 0.72-scale crop excluding sky and
water. This removes the worry and names the blind spot in one measurement: the
check of §6 cannot see a crop move, and does not need to.

### §0.8 The frame probe predicts the encode

The check reads finished x264 clips; §0.3's calibration came from raw frames
through `plan_render`. Four episodes rendered for real through `reframe.reframe`
and read with the same ruler:

| ep | encoded residual | frame-probe residual |
|---:|---:|---:|
| 0 | 8.0 | 8.0 |
| 2 | 4.5 | 4.5 |
| 5 | 2.5 | 3.5 |
| 7 | 2.5 | 3.5 |

Within **1 code**. What `probe grade` shows before any encode is what the gate
reads after it — which is the claim `probe grade` exists to make, now verified
for a crop-measured grade specifically.

### §0.9 The geometry oracle already works, and caught a real gap

`probe._refuse_on_drift` recomputes the crop path and compares it to the frozen
`path.json`. It passed on seven of eight episodes and refused ep1:

> the recomputed crop path does not match the frozen `work/ep1/path.json` (378
> points vs 378, first difference at index 0) — a re-track, a retry-adjusted
> `max_speed`/`smooth_window_s`, or a different source file.

ep1 went through the retry ladder, and **`EPISODES.json` does not record the
adjusted params**, so its manifest can no longer reproduce its own render. That
is a separate hole — filed in §10, not fixed here — but it is also the proof that
the oracle this design leans on discriminates.

---

## §1 The rule

**A colour measurement is taken on the pixels that ship.**

Concretely: `tone_src` is the (p5, p50, p95) luma of the episode's own tracked
crop, rendered through `reframe.plan_render`'s chain with the colour block at
identity, read with `format=gray` at three frames — the same chain, the same
route, and the same ruler the render and the gate use.

Everything below follows from needing a route before the grade.

---

## §2 The seam

`edl_to_reel`'s phase 1 splits at the **geometry boundary** — the line inside
`process_episode` between the contradiction gate and the reframe retry loop.
Everything above it is colour-independent; everything below it consumes the
colour block.

```
edit-plan → pacing
   ↓
edl_to_reel --stop-after-geometry     stabilize · track · contradiction gate
   ↓                                   → GEOMETRY.json   (no encode)
match_grade build --geometry           measure each crop · common target
   ↓                                   → EDL.json + MATCH.md
   ↓  (probe grade --geometry — look, edit selection.json, re-conduct, look again)
edl_to_reel --from-geometry            render over the frozen routes
   ↓                                   → EPISODES.json
episode-qc → edl_to_reel --from-episodes → deliver
```

The human's review point moves **earlier**, which is the whole value: `MATCH.md`
and crop-accurate stills are readable before a single episode is encoded.

### §2.1 `process_episode(stop_after="geometry")`

A new keyword, accepting only `"geometry"`. The function runs its validation, the
stabilize pre-stage, the tracking ladder and the contradiction gate exactly as
today — every refusal, every escalation, every `stop_and_report` unchanged — and
then returns

```python
{"status": "geometry", "route": rp | None, "source": src,
 "degraded": ..., "timings": ..., "stabilize": ...}
```

`source` is the file reframe will consume: the segment normally, the stabilize
pre-stage's output when `stabilize` is set. This is `probe.source_for`'s question
answered by the stage that knows, instead of inferred from a filename afterwards.

### §2.2 `GEOMETRY.json`

New contracts in `models.py`, beside `ReelEpisode`/`ReelManifest`:

```python
@dataclass(frozen=True)
class EpisodeGeometry:
    manifest: dict          # the resolved manifest with the COLOUR BLOCK STRIPPED
    route: str | None       # None for a pan — it follows nobody
    source: str             # the file reframe will consume
    project_dir: str        # build/ep{i}

@dataclass(frozen=True)
class ReelGeometry:
    episodes: tuple[EpisodeGeometry, ...]
    edl: str                # the EDL this geometry was derived from
    provenance: dict        # engine stamp — the same drift guard EPISODES.json carries
```

The manifest is stored **without** its colour block, and that is half the guard,
not a space saving: `--from-geometry` re-reads the EDL, re-derives each episode's
stripped manifest, and refuses on any difference. The drop-and-reapply is
`probe.regrade`'s, unchanged and already proven — `COLOUR_KEYS` with
`COLOUR_IDENTITY` filling what `to_manifest_dict` omits at identity.

**Amended during execution (Task 3), because one half is not enough.** The stored
manifest cannot see a changed *window*. `to_manifest_dict` carries neither
`source` nor `start` — those are `extract`'s inputs, and the manifest only names
the segment `extract` already wrote — and `dur` crosses only as
`target_dur = ep.play_dur()`. Since phase 1b deliberately does **not** re-extract,
a changed `start` would ship phase 1a's OLD segment under the NEW colour block,
silently, and the manifest comparison would see nothing.

**The `ramp` case is the one that settles it**: `play_dur() = dur + ramp_extra`,
and `ramp_extra` is by design a `dur`-independent constant of the ramp region
(2026-08-09 §2) — so at the `at` values where it comes out exactly equal, moving
a ramp leaves `target_dur` **bit-identical** while the pixels on disk are phase
1a's, and no manifest field moves at all.

Measured afterwards over 14 sampled `at` values (Task 8's review): exactly 3 are
bit-identical; the interior ones differ by 1–3 ULP and the ones near the window's
edges by 0.05–0.094 s, which the manifest half *would* catch. So the manifest half
is not blind to every moved ramp — it is blind to a real, reachable subset of
them, and a guard that catches a cut change only at most `at` values is not a
guard. Proof 3 deliberately picks one of the exact three, so a half-built guard
cannot pass it by arithmetic luck.

So `ReelGeometry` records a second half: a per-episode **cut identity**
`{source, start, dur, ramp}` — exactly the four fields `extract_edl` reads — and
`--from-geometry` checks both, naming which fields moved. A changed cut is
refused; a changed colour block is exactly what this seam is for.

### §2.3 The stabilize/route reconciliation

`process_episode` refuses `stabilize=True` together with a supplied `route_path`:

> the frozen route was measured against unknown pixels, and applying it to the
> stabilized ones re-injects the shake

In the split, the pixels are not unknown — the route was measured on this same
run's stabilize output. The refusal was right and had no way to express the one
case it should allow.

New internal parameter `prepared_source: str | None`. Supplying it asserts *this
route was measured on this file*: the stabilize pre-stage is skipped and the
named file feeds both `reframe` and `check_episode`. It is refused without
`route_path` (alone it is an unrelated knob), and it is **not exposed on
`process_episode`'s CLI** — only a driver that produced both halves can honestly
assert the pairing. A hand-supplied `--route` with `stabilize` refuses exactly as
today.

`m.stabilize` stays true in the manifest, so `reframe(..., stabilized=...)` and
every report still say what happened.

---

## §3 The conductor

`match_grade build --geometry GEOMETRY.json` replaces
`--edl X --footage-root Y`. The geometry names its own EDL, so the two halves
cannot be mispaired.

`lib/matchgrade.py` **does not change**: `common_target`, `_repair_gaps`,
`biased_target`, `bias_ineffective`, `valid_src`, `needs_tone`, `plan` and
`ToneDecision` all take profiles and return decisions. Only where the profiles
come from changes. `--eps`, `--force` and `--spec` (the mood bias) keep their
meaning; `MATCH.md` gains the sample times and says the reading is of the crop.

New: the conductor writes `EDL.tone_target` — the reel's one common target, after
the mood bias. The gate of §6 needs one number for the reel, and deriving it from
the episodes' `tone_dst` would fail on the reel where every episode was skipped.

**The whole-frame mode is deleted.** `write_match`'s `footage_root` parameter and
the `--footage-root` flag go; `measure_profile`'s window-midpoint call site goes
with them. Keeping it as a fallback would keep a second answer to the same
question, and §0.1 says which of the two is wrong. `measure_profile` itself stays
— it is the `color_measure` CLI's authoring aid, and `color.percentiles`' only
other caller.

---

## §4 The probe — R3.1's "draft 2"

`probe grade --geometry GEOMETRY.json --index N` renders and measures N frames of
one episode over its frozen route, before any encode. That is the row's ask
verbatim — "a stage taking source + route + colour block and emitting stills" —
and it needs no new machinery: `probe_grade`'s body already does this from
`EPISODES.json`, which only exists after everything has been encoded.

Two differences from the `--episodes` mode, both stated in the report:

- `_refuse_on_drift` does **not** run. There is no `path.json` yet, so there is
  nothing to drift from; the plan *is* the source of truth. The `--episodes`
  mode keeps the check.
- `source` comes from `EpisodeGeometry.source` rather than `source_for`'s
  filename inference.

And `probe`'s reported tone moves to the gray ruler (§0.5), so what an operator
converges by hand is the number the conductor authored and the gate will read.
The RGB frames stay — `probe.jpg` and `naturalness.measure` need them.

---

## §5 The convergence gate

`check_reel` gains a **blocking** `tone_match` check.

**What it measures.** For each episode whose `tone_dst` equals the reel's
`tone_target`, three frames inside that episode's own span — at `(k + 0.5) / 3`
of it, the same rule `probe` samples by, so a bookend or a dip never owns a
sample — read with the gray ruler; residual = max per-anchor distance to the
target. The check's value is the
worst residual across the checked episodes, against
`ReelCheckSpec.tone_match_max = 12.0` (§0.6).

**It reads the MASTER, not the delivered reel.** The look's vignette and the
bookend fade ride `deliver`'s one encode, and both move percentiles; the master
is the last artifact whose pixels are the episodes'. `check_reel` already
computes `_boundaries(durations)`, so the per-episode sample times cost nothing
new, and one `select` over the master is one decode for the whole reel.

**What it does not check, by name.** An episode the conductor deliberately
skipped is not bound to the target and is reported `not-checked` with its reason:
`flat-source` (its contrast cannot be invented), `hand-authored` (the human's
target is not the common one), `within-eps` (no pair, and within 4.0 by
definition). A reel with no target at all — `match-grade` was never run — reports
`not-checked: no-target` and does not fail. Absence is not tampering; the same
rule the attestation lives by.

**Where it escalates.** `ReelFailure("tone_match", "match-grade", ...)`, and it
escalates for free: `reel_orchestration._REPROCESS_CLASS` is `("black",)` since
2026-08-29, so every reel failure that is not a black frame already escalates
rather than re-rendering. There is no list to join — the retire slice's narrowing
is what makes a new non-reprocessable reel check cost one tuple entry in
`check_reel` and nothing else. The route is `match-grade` because no reframe knob
moves a colour.

**What it proves.** That the grade the EDL declares reached the pixels. Never
that the target is the right target — no statistic can say that, which is why the
`colour` axis on `reel-review` (0.5.0) stays exactly where it is and reads the
same reel.

---

## §6 Contract changes

| Contract | Change |
|---|---|
| `models.EpisodeGeometry` | new |
| `models.ReelGeometry` | new — its `provenance` carries the per-episode cut identity beside the engine stamp (§2.2, amended) |
| `models.ReelCheckSpec.tone_match_max` | new, `12.0` |
| `models.ReelManifest.tone_target` | new, `tuple[float,float,float] \| None` |
| `edl.EDL.tone_target` | new, written by `match_grade`, carried to `ReelManifest` |
| `process_episode.process_episode` | `stop_after`, `prepared_source` parameters |
| `edl_to_reel` | `--stop-after-geometry`, `--from-geometry` |
| `match_grade` | `--geometry` replaces `--edl` + `--footage-root` (**breaking**) |
| `probe` | `grade --geometry` alternative to `--episodes` |
| `color_measure.measure_crop` | new — the crop reading |
| `color_measure._percentiles_from_gray` | new — the ruler's one chokepoint |
| `probe._tone` | deleted; `_percentiles_from_gray` replaces it |
| `montage.V1_STAGES` | `episodes-geometry` inserted after `pacing`, ahead of `match-grade` |
| `montage.V1_STAGES` | `match-grade` `optional` → `required` (the router leads through it) |

A pre-0.6.0 `EDL.json` carries no `tone_target`; the gate reports
`not-checked: no-target` rather than refusing, so an old EDL still delivers.

`match-grade` becomes a **required** stage, so `montage status` names it as the
next action on every reel rather than listing it among the skippable ones. That
is the answer to R4.2's finding — a stage nobody is told to run at the moment of
need is a stage that gets rebuilt by hand — and it is cheap to obey: on a
single-camera reel the conductor measures eight crops in five seconds and writes
a `MATCH.md` saying every episode was within eps. The driver itself stays
separately runnable and a human can still decline to run it; what changes is that
the router no longer walks silently past the only stage that converges colour.

---

## §7 Where the code goes

`measure_crop` needs `plan_render` (in `reframe`) and `build_reframe_spec` (in
`process_episode`) and ffmpeg and numpy — so it is driver work, not `lib` work,
and it lands in `scripts/color_measure.py` beside `measure_profile`, which is
already the file that "produces the histogram from a decoded still". `match_grade`
and `probe` both import it; the decision maths stays pure in `lib/matchgrade.py`,
the ruler stays in one function, and `color.percentiles` remains the only place
percentiles are computed.

---

## §8 Proofs

1. **The central claim, end to end (real ffmpeg).** A two-episode fixture reel
   with deliberately different exposure: geometry → conduct → render, and every
   episode's delivered crop lands within `MATCH_EPS` of the target — with a
   control that must NOT move (a single-episode reel authors nothing).
2. **The whole-frame reading and the crop reading disagree** on a fixture whose
   crop excludes a bright band, by more than `MATCH_EPS` — the mutation guard on
   §0.1's finding.
3. **`--from-geometry` refuses a changed cut** and accepts a changed colour block,
   on the same geometry file.
4. **`stabilize` + a geometry-supplied route renders**, and `stabilize` + a
   hand-supplied `--route` still refuses.
5. **The gate fires** on an episode rendered with its tone pair dropped, and
   passes the same reel with it applied.
6. **The gate reads the master, not the delivered reel** — a reel with a
   max-depth vignette passes, and would not if it sampled the delivery.
7. **`probe grade --geometry` and `--episodes` agree** on the same episode to
   within a code, which is §0.8 as a test.
8. **A mutation battery**, one row per deletion and per threshold.

---

## §9 Honest limits

### §9.1 Every threshold is one shoot

`tone_match_max = 12.0` sits between a positive maximum of 8.0 and a negative
minimum of 19.5, both measured on **eight episodes of one day's footage, two
cameras**. The gap is wide and the bar is mid-gap, but a genre with harder
within-shot exposure changes than a beach at 9 a.m. will push the positive class
up, and nothing here would notice until it fires.

### §9.2 The gate proves arrival, never aim

A reel every one of whose episodes lands exactly on a **badly chosen** target
passes with residual 0. The gate answers "did the declared grade reach the
pixels", which is a question with a right answer; "is this the right grade" is
not, and stays with the human at CP3 and the `colour` axis of `reel-review`.

### §9.3 Luma only

The transfer, the target and the gate are all (p5, p50, p95) of **luma**. The
drone and the Canon can still disagree on white balance after this slice, and
**nothing measures that** — `color_fidelity` compares an episode against its own
source (damage), not episodes against each other (agreement). Filed in §10.

### §9.4 A skipped episode is not checked at all

`flat-source`, `hand-authored` and `within-eps` episodes are reported and passed
over. A reel where the human authored every pair by hand is entirely unchecked by
`tone_match` — correctly, since there is no common target to check against, but
the reel is then exactly as unmeasured as it was before this slice.

### §9.5 Three frames of a shot with a big internal change

ep0's residual of 8.0 — the worst in the healthy class — is its third frame
disagreeing with its first two (p95 spread 39 across the episode). Three frames
pooled give one profile for the whole shot, and a shot that genuinely changes
exposure inside itself gets a compromise. §0.4 says more frames do not help. The
right answer for such a shot is probably to cut it, and nothing here says so.

### §9.6 The retry ladder still runs after the grade

Measured (§0.7) not to move the tone at all, on four episodes and both ladder
branches. That is an empirical result on one shoot, not a guarantee, and the
architecture still authors a grade against a crop that a later stage is allowed
to move.

### §9.7 The seam adds a third stop point

Phase 1 now has `--stop-after-geometry` / `--from-geometry` on top of
`--stop-after-episodes` / `--from-episodes`. Every combination is legitimate and
the router drives the ordinary one, but the driver's CLI is now four flags of
phase control, and a human running it by hand has four ways to pair the wrong two
artifacts. The refusals of §2.2 cover the pairing; the count is still real.

### §9.8 This feature can stop a real run, on a gate with no waiver

The one limit that is not about precision. `check_episode`'s `color_fidelity` has
been **blocking** since 2026-08-28 at `CheckSpec.grade_delta_max = 5.0` dE00: it
measures the tracked subject in the source segment against the same subject in the
graded clip, it sits in `orchestration._UNFIXABLE`, it escalates on attempt 1 as
`grade-damage`, and it has **no waiver anywhere** — no CLI flag, no manifest field.
A conductor-authored tone pair *is* grade movement to that sensor.

Measured two ways, independently, during Task 8:

- Sweeping a two-exposure fixture, the gate crosses at a **max-anchor pull between
  34.5 and 39.5** luma units (dE00 2.98 at a 34.5 pull, **5.48** at 39.5).
- Computing dE00 through this repo's own `color._segments`/`_lerp` and
  `lib/colordiff`, modelling the subject as a *neutral* patch — a lower bound, since
  a chromatic subject adds dC\* and dH\* in quadrature — the gate's entire headroom
  is **~14–20 codes** of subject-luma movement. Against the §0.3 real-run pairs, **all
  eight episodes have a subject-luma band over 5.0 dE00**, three of eight trip at the
  crop's own median, and two reach **2.3× the ceiling**.

The **old** whole-frame conductor did not collide with it: its pulls could only move
the midpoint (sky and specular water pinned p5 and p95 on both sides, §0.2), and the
same measurement reads **3.10 dE00 at every code** — comfortably under. So this slice
is what makes the collision unavoidable, and §6 flipping `match-grade` to **required**
is what carries it to every reel rather than an opt-in few.

`grade-damage` routes to `edit-plan`'s colour block, whose remedy is the very pair
`match-grade` just authored on purpose. That is a loop with no exit that does not
involve a human lowering a gate which has no lever to lower.

**Nothing here changes a threshold**, because the fix is a design decision and not a
patch: *should `color_fidelity` measure damage against identity, or against the
**declared** transform?* Measuring against identity asks "did the pixels move", and a
declared, converged, reel-wide grade is supposed to move them. Measuring against the
declared transform asks "did anything move that the grade did not ask for", which is
the question the sensor was built to answer — but it needs the transform threaded to
it, and it stops noticing a transform that is itself wrong. Filed **P1** in
`docs/backlog.md`; distinct from the P2 visibility row beside it (`probe grade`
cannot predict this gate), which is about seeing the stop coming, not about the
deadlock once it arrives.

### §9.9 The gate's own justification is conditional, and a legal knob breaks it

`_tone_match_check` was written on the claim that percentiles commute with a
monotone map, so a graded episode's delivered p5/p50/p95 land on the target **by
construction**. That is true only while the tone curve is the **last** luma
operation in the chain, and it is not. `color.grade_chain`'s order is

    wb → tone → black_point → gain → shadow_red → mid_blue → saturation
       → highlight → highlight_red → dip

— six luma-moving filters after `tone` — while the conductor solves the curve
against `color_measure.measure_crop`, which plans through `manifest.strip_colour`,
i.e. with **every** knob at identity. So the curve is fitted to pixels that carry
none of the post-tone knobs, and each one that moves luma displaces the reading
this gate takes.

Measured on a 3-band tv-range clip, ungraded `(40, 120, 200)` onto target
`(52, 103.5, 191.5)`, against `tone_match_max = 12.0`:

| chain | delivered | residual |
|---|---|---:|
| tone only | 51 / 102 / 191 | 1.5 |
| tone + `black_point=0.05` | 40 / 93 / 187 | **12.0** |
| tone + `black_point=0.10` | 27 / 84 / 183 | **25.0** |
| tone + `highlight=0.8` | 56 / 107 / 172 | **19.5** |
| tone + non-default `color_means` | 48 / 98 / 183 | 8.5 |
| `white_balance=0.6` then tone | 52 / 106 / 192 | 2.5 |

Two knobs are safe, and it is worth saying why: `white_balance` runs **before**
tone, so the conductor's own measurement already carries it (2.5, the last row);
`saturation` is `eq=saturation`, a chroma scale that never touches the luma plane.
The rest — `black_point`, a non-default `color_means`, `shadow_red`, `mid_blue`,
`highlight`, `highlight_red`, `dip` — all move luma after the curve.

Stated plainly: **a correctly graded episode that carries a second luma knob fails
a blocking gate.** `black_point ∈ [0, 0.35]` and `highlight ∈ [0.6, 1.0]` are
documented, in-range, per-episode fields, and `black_point_arg`'s own docstring
names a real production case for them (DJI's flat profile put the darkest 1% at
65.7/255 against 23.1 on the telephoto beside it). At `black_point = 0.10` the
residual of 25.0 is past §0.6's **negative-class minimum of 19.5**, so the two
classes overlap and the gate cannot separate "the grade never reached the pixels"
from "the author lifted a toe". The failure escalates to `match-grade`, which
re-measures at identity and re-authors the identical pair: a second no-exit loop,
the same shape as §9.8's and by a different mechanism.

**Nothing here changes a threshold**, for the same reason §9.8 changes none — the
open question is a design decision, not a patch: *should the residual be measured
**through** the non-tone part of the chain (measure what the episode actually
renders, at the cost of the gate no longer being a statement about the tone
transfer alone), or should post-tone luma knobs be **excluded** from it (keep the
clean claim, at the cost of the gate examining nothing on an episode that carries
one)?* Filed **P1** in `docs/backlog.md`, cross-referenced to the §9.8 row: two
different mechanisms reaching the same deadlock.

**Corroborated on real footage, not only on the bands above.** The pin
`test_a_black_point_beside_the_tone_pair_misses_the_target_RECORDED_LIMITATION`
(`tests/integration/test_grade_shipped_pixels.py`) runs the whole conductor →
`--from-geometry` path over the same re-exposed `golden_ride.mp4` every other proof
in that file uses. Tone alone lands **1.0** from the target; the same episode with
`black_point = 0.05` added afterwards lands **13.0** — past `MATCH_EPS` (4.0) *and*
past `tone_match_max` (12.0). So the blocking gate does not merely lose its
justification on a legal second knob, it fails on one, at the smallest legal lift
this repo documents. The test asserts against `MATCH_EPS` rather than the gate
ceiling because 13.0 sits one unit above 12.0 and that margin is too fine to pin.
It records the limitation; it does not endorse it — when the design question above
is answered the test should go red and be rewritten, not deleted.

### §9.10 Three places where the seam reads the manifest, not the file

Carried from the per-task reviews and routed here rather than fixed. All three are
the same shape: phase 1b is handed a `prepared_source`, and the code around it
still asks the manifest — or the raw segment — what that file is.

1. **The preflight probes the wrong file.** `process_episode` opens with
   `reframe._probe(m.segment)` and threads `src_w`/`src_h` into the layout
   preflight, while the pixels that are actually rendered come from `src`, which
   under `prepared_source` is the stabilized file. They agree today, and by
   construction: `vidstab.stabilize` runs `crop=keep`, so the dimensions and the
   frame rate are preserved. But the agreement is a property of the pre-stage, not
   something this call checks, and the *same* probe's `_fps`/`_dur` are what
   `vidstab.stabilize` is called with on the non-prepared branch — which is why
   moving the probe onto `src` is not a one-line change.

2. **`reframe(..., stabilized=m.stabilize)` asks the manifest, not the file.** The
   flag tells `reframe` whether its input has already been through the pre-stage.
   Under `prepared_source` the two agree, because the driver only supplies a
   prepared source for an episode whose manifest declares `stabilize` (§2.3 makes
   `m.stabilize` staying true a deliberate property, so the reports still say what
   happened). The honest predicate is nonetheless "was the file I am being handed
   stabilized", and nothing at this call site can answer it.

3. **A stabilized PAN re-runs its own pre-stage in phase 1b.** `prepared` is gated
   on the ROUTE as well as on `stabilize` (`render_from_geometry`), because
   `prepared_source` is refused without `route_path` — and a pan has no route. So a
   stabilized pan is handed neither half and `process_episode` calls
   `vidstab.stabilize` again, writing to the same `<project_dir>/stabilized.mp4`
   the conductor measured its crop through. Two things are worth separating. The
   **cost is certain**: two extra full-resolution passes per such episode. The
   **risk is not**: this repo's own claim is that `vidstabtransform` is not
   bit-reproducible *across runs of a different length*, and a phase-1b re-run is
   the same segment at the same length, so the second file is probably identical to
   the first — and even where it is not, the difference is a slightly different warp
   of the same shot, which a (p5, p50, p95) reading over a whole crop should not
   see. **Neither half of that has been measured**, and this section does not claim
   it has. Today the whole case lives as a code comment beside the `prepared` list
   in `edl_to_reel.py`.

---

## §10 Deferred → backlog

1. **Chroma convergence across episodes** (§9.3). Nothing measures whether the
   episodes agree in colour, only in luma. The instrument probably exists —
   `colordiff`'s CIEDE2000 over the same three crops against a common chroma
   target — but the target itself needs designing, and a mean chroma is exactly
   the kind of whole-frame statistic the 2026-08-29 slice deleted. **P2/M.**
2. **`EPISODES.json` does not record the retry-adjusted reframe params** (§0.9),
   so a retried episode cannot reproduce its own render and `_refuse_on_drift`
   refuses it. Found on ep1 of the real run. **P2/S.**
3. **A one-step converged re-render.** The frame-probe design deferred this; the
   geometry seam makes it cheap, since the routes are already frozen and only the
   colour block would change. **P3/M.**
4. **The conductor reports no within-episode outlier** (§9.5). It pools three
   frames into one profile and never says that they disagreed. **P3/S.**
