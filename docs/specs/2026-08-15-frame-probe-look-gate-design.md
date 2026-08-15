# Frame probe + look gate — design

**Date:** 2026-08-15
**Backlog:** P2 · [#10](../fixes-backlog.md#10-cheap-3-frame-preview-to-converge-the-colour-grade-before-a-full-episode-re-render),
folded with cinematic-look §11.1/§12.
**Status:** designed, not built.

## §0 Why

Two complaints, one primitive.

**A — converging a grade costs a whole reel.** The 2026-08-03 run spent ~29 full
re-encodes. Today the only way to see a new grade on an episode is to re-run
`edl_to_reel`, which re-extracts, re-tracks, re-encodes, re-storyboards and
re-checks **every** episode — to look at one episode's colour.

**B — nothing ever sees the look that shipped.** `check_reel` measures the
**master**. `deliver` then encodes the vignette, the bookend fade and the titles
into a file no gate reads. The cinematic-look slice's own review caught a filter-list
drop that would have silently killed the bookend and every title for three of four
mood presets — the class of bug is "the effect was declared and did not render", and
it is invisible to everything currently in the pipeline.

Both are answered by the same unit: **render these exact frames through this exact
filter chain and measure them**. A does it before the encode, on an episode; B does
it after the encode, on the delivered reel.

## §1 What is already on disk

After `edl_to_reel --stop-after-episodes`, `EPISODES.json` (a `ReelManifest`) holds,
per episode: the fully-resolved `manifest` dict, the locked `clip`, and the frozen
`route` / `path` / `meta` paths. That is everything a re-render needs. The probe
reads it and adds nothing to the run.

This is deliberately the same seam episode-QC opened: render episodes → judge →
fix → assemble. The probe is what "fix" costs.

**One trap found by reading, not by testing.** Under `stabilize`, the file
`reframe` actually consumed is `<epdir>/stabilized.mp4`, **not**
`manifest["segment"]`. A probe that reaches for `segment` renders different pixels
than shipped, and says nothing about it. The probe therefore resolves its source the
way `process_episode` does, and **refuses** when `stabilize` is declared but
`stabilized.mp4` is missing, rather than falling back to the raw segment.

## §2 The invariant, and why it is checkable

In `reframe()` the geometry block (`reframe.py:438-478`) and the colour block
(`reframe.py:480-492`) do not touch. `compute_path`, `generate_pan_path`, the crop
rect, `cy` and `xexpr` take no colour input; `grade_chain` takes no geometry. **A
grade change cannot move the crop.** That is what makes a probe over a frozen route
legitimate: at those timestamps its pixels are the pixels the next full render will
ship.

An invariant that is only asserted rots. This one is **checked**, and against the
strongest oracle available: the probe recomputes the crop path and compares it
**element by element** against the frozen `path.json`, then compares its resolved
geometry against `path.meta.json` (`mode`, `crop_w`, `crop_h`, `out_dims`). The path
comparison is the load-bearing half — it also catches a retry-adjusted `max_speed` or
`smooth_window_s`, which move every x but leave the recorded rect identical, so the
meta alone would wave them through. Any disagreement means the frozen route/segment no
longer describe this manifest, and the probe **refuses** rather than showing pixels
that will not ship.

## §3 One chain, two sinks

**Rejected:** rebuilding the render from `path.meta.json`'s recorded rect. That is a
second implementation of the chain; it drifts from `reframe`, and the day it drifts
is the day the probe lies about exactly the thing it exists to answer.

**Built:** the middle of `reframe()` becomes `plan_render(spec, src, route_path)`,
returning a `RenderPlan` — the filter args, `dur`, `fps`, the crop path and the
geometry `PathMeta` needs. `reframe()` = that plan + the x264 sink + the sidecar
writes. The probe = the same plan + a `select` sink into PNGs.

A sink filter is added through exactly one method, `RenderPlan.with_tail(extra)`,
which appends to the end of the chain string. `_filter_args` is not touched at all, so
every existing argv stays byte-identical — which is what the golden fixtures pin — and
§3.1's ordering rule has one place to live rather than one per caller.

`verify_tone` stays inside `plan_render`, so the probe refuses a banding spline with
the same loud error the real render does.

### §3.1 The `select` must be LAST — measured

The obvious optimization is to put `select` **first**, so crop/scale/grade run on 3
frames instead of 90. It is wrong, and it fails silently.

Measured on a 1080p/3s grainy clip, requesting frames 15/45/75:

| where | wall | sha256 of the three PNGs (first 16) |
|---|---|---|
| after the chain | 1.08s | `4b56…`, `38c0…`, `74fb…` |
| before the chain | 0.76s | `4b56…`, `4b56…`, `4b56…` |

Select-first emitted **the same frame three times**, with no error and the right file
count. The tail's `fps={fps}` filter re-interpolates the dropped frames back up to
rate by duplication, and `-frames:v 3` then takes three copies of the first. The 30%
saving buys a probe that shows one frame and claims it is three.

This is a §12-class landmine and is recorded there. `with_tail` appends after the
`fps=`, so the correct position is the only reachable one, and the lint gains a check
that refuses a `select` emitted ahead of an `fps=` in the same chain.

## §4 What the probe does

`probe grade --episodes EPISODES.json --index N [--edl EDL.json]`

- Without `--edl`: renders the grade **as it was rendered** — the baseline.
- With `--edl`: rebuilds that episode's manifest from the (edited) EDL through the
  same `edl.to_manifest_dict` bridge the real run uses, so what converges is exactly
  what ships. No transcription step, no second authoring surface.

Frames: `--frames N` (default 3), placed at `(i + 0.5)/N · dur` — interior, never the
first or last frame, which a dip or a bookend can own.

Outputs into `<epdir>/probe/` (overridable with `--out-dir`), overwritten each run —
the probe is a scratchpad, and a directory of `probe_7.jpg` nobody prunes is how a
run ends up unable to say which attempt it is looking at:

- `probe.json` — per frame: `naturalness.measure` stats and flags, and the (p5, p50,
  p95) luma percentiles via `color.percentiles`; plus the exact grade fragment used
  and the colour block in EDL field names, ready to paste.
- `probe.jpg` — the frames tiled by `sheet.tile`, which already takes HxWx3 uint8 RGB
  cells. Pixels, because the sensors do not have taste.

The agent looks, edits the EDL, probes again. **No auto-search**: the naturalness
thresholds are declared first cuts calibrated on nothing, and a solver over an
uncalibrated taste function invents a target. `match_grade` remains the deterministic
lane, unchanged.

## §5 What it costs — measured

Synthetic 3s clips, `testsrc2` (flat) and `testsrc2 + noise=alls=40` (grain, the
worst case for x264 at crf 18); real footage sits between them.

| source | full encode | 3-frame probe | ratio |
|---|---|---|---|
| flat 1080p | 0.59s | 0.37s | 1.57× |
| flat 4K | 0.66s | 0.49s | 1.35× |
| grain 1080p | 2.41s | 1.31s | 1.84× |
| grain 4K | 3.83s | 2.86s | 1.34× |

**The encode is not the prize.** The probe still decodes the whole segment, so
dropping the encode alone buys 1.34–1.84×. What it actually skips is the rest of the
loop: a tracking pass on the same 1080p/3s clip costs **5.00s** — 2–8× the encode it
sits beside. One grade attempt on one episode today is track + encode ≥ 7.4s against
the probe's 1.31s (**≈5.7×**), and via `edl_to_reel` it is that, plus extract,
storyboard and check, **times every episode in the reel**.

## §6 Whether the probe's pixels are the shipped pixels — measured

The probe cannot be byte-identical to the delivered clip: crf 18 is lossy. What
matters is the size of the gap. Probe PNGs against the same frame numbers decoded
back out of `reframe`'s real output, on the **grain** source:

| | mean \|Δ\| | p99 | max | mean luma probe → shipped |
|---|---|---|---|---|
| 1080p, 3 frames | 1.065 – 1.303 | 9 | 43–46 | 79.80→79.66, 94.93→94.82, 110.31→110.25 |
| 4K, 3 frames | 1.090 – 1.386 | 9 | 60–79 | 79.37→79.29, 94.65→94.61, 109.89→109.88 |

Per pixel they differ by about one code of encoder noise. The **statistics the grade
decision is made from** — mean luma — agree to **0.14 codes or better**, on the
hardest source there is.

## §7 The look gate (half B)

Runs inside `deliver`, **after** the encode, before the attestation. Samples the
delivered `REEL_v{n}` and the master at the same timestamps and compares. With no
look and no titles declared there is nothing to prove and the gate makes no ffmpeg
call at all — a look-less delivery costs exactly what it costs today.

Calibrated on a real deliver-shaped encode of the grain master.

### §7.1 The catch-all that measurement killed

The first design carried a third, general check: *any declared effect that leaves
every sampled frame within encode noise of the master did not render*. The noise floor
is real — a look-less delivery sits **0.638 / 0.727 / 0.779** codes from its master —
but the predicate built on it is not, and two measurements say so:

| delivery | whole-frame mean \|Δ\| vs master | against a 2.0 floor |
|---|---|---|
| no look | 0.638 / 0.727 / 0.779 | — |
| vignette 0.10 | 1.754 / 1.955 / **2.063** | passes by 3% |
| vignette 0.30 | 4.592 / 5.134 / 5.344 | passes |
| vignette 0.60 | 8.919 / 9.987 / 10.355 | passes |
| **fade 0.5s** | 0.639 / 0.726 / **0.780** | **fails — always** |

A fade touches only the first and last half-second; the three samples sit at 25/50/75%
of the reel, outside both ramps, so a fade-only delivery is **indistinguishable from a
look-less one** by this measure and the catch-all would refuse every one of them. And
a shallow vignette clears the floor by 3%, which on a darker picture it would not.

The premise was wrong: only a **vignette** changes the whole frame everywhere. So the
catch-all is deleted, and with it `LOOK_NOISE_MAX`. Nothing is lost — a dropped filter
still fails the effect's OWN check: a vignette that did not render drops the corner
ratio by ~0, and a fade that did not render leaves the first frame at the master's
brightness. Both are decisive with a real margin, which the catch-all was not.

What the catch-all would uniquely have caught is **titles**, whose own check is
deferred (§11). A titles-only delivery therefore reports one `not-checked` finding
rather than nothing at all: the absence is recorded, not silent.

**Vignette.** Mean luma of four corner boxes over a centre box, delivered against
master — content cancels in the ratio. The boxes are `h//10 × w//10` at each corner
and `2·(h//10) × 2·(w//10)` centred: the mask's plateau reaches 55% of the corner
radius, so a corner box at 10% of each dimension sits well outside it and the centre
box well inside, with neither straddling the falloff. Measured:

| declared | master ratio | delivered ratio | drop |
|---|---|---|---|
| 0.10 | 1.3670 | 1.2516 | 0.0844 |
| 0.30 | 1.3670 | 1.0149 | 0.2576 |
| 0.60 | 1.3670 | 0.6550 | 0.5209 |

The drop tracks the declared depth at 0.84–0.87×. `VIGNETTE_MIN_FRACTION = 0.5` — a
1.7× margin below the measured floor.

**Fade.** First delivered frame's mean luma. Measured: master **75.28** → delivered
**0.00**. `FADE_BLACK_MAX = 2.0`.

**Not-checked arms, and they are real holes.** A titles-only delivery has no check at
all this slice (§7.1). A master whose own first frame is
already dark (`< FADE_SOURCE_MIN = 8.0`) cannot discriminate a fade; a master whose
corners are already black (`< VIGNETTE_FLOOR = 8.0`) cannot discriminate a vignette.
Those report `not-checked` and pass. Reporting them as proven would be the lie this
gate exists to stop.

**On failure** `deliver` raises. `REEL_v{n}` is already on disk and stays there —
deleting output nobody asked to delete is worse than leaving evidence — but no
attestation is written, which `montage status` already reads as an unattested
delivery. Consistent with `deliver`'s existing `master_digest` refusals. **No
waiver**, per governance #8.

## §8 Thresholds live in the module

Every constant above lives at module level in `lib/lookcheck.py` and is **not** a
parameter. Same reason `naturalness.py` states: a threshold a caller can pass is a
threshold a subagent can pass, and a no-waiver gate whose bar is an argument has no
bar.

## §9 Files

| File | Change |
|---|---|
| `scripts/lib/lookcheck.py` | new — pure: the vignette and fade measurements, the titles not-checked placeholder, the constants, `evaluate` → findings. numpy in, verdict out |
| `scripts/probe.py` | new — driver: `grade` (§4), `look` (a manual re-check of §7) |
| `scripts/reframe.py` | `plan_render` extraction; `_filter_args(tail_extra="")` |
| `scripts/deliver.py` | the post-encode gate |
| `scripts/lib/lint.py` | a seventh check: a `select` emitted before a chain that ends in `fps=` (§3.1) |
| `skills/…` | the convergence loop, and how to re-render ONE episode with its frozen route |
| `docs/…` | CLAUDE.md registry row, build-status, pipeline-map, backlog |

## §10 Honest limits

1. The probe does not x264-encode. A grade defect that only appears after
   compression will not show. §6 bounds how much that hides: ~1 code per pixel, 0.14
   codes of mean luma, on the worst source available.
2. The probe is bound to the **frozen** route. Re-tracking invalidates its result;
   §2's meta oracle catches the mismatch, but only once the mismatch exists on disk.
3. The look gate proves an effect **changed pixels**, not that it looks right. Depth,
   placement and taste are outside it.
4. The two not-checked arms (§7) pass without evidence, by construction.
5. The cost figures in §5 are synthetic. No real 4K/60 surf footage has been probed;
   the tracking-share argument is structural, the ratios are not.
6. The naturalness thresholds the probe reports against remain uncalibrated first
   cuts (episode-qc §5). The probe surfaces them; it does not fix them.
7. Nothing forces anyone to run the grade probe. It removes the *cost* excuse for
   iterating, not the possibility of shipping without looking. The look gate, by
   contrast, cannot be skipped without skipping `deliver`.

## §11 Deferred — must reach the backlog

- **Titles in the look gate.** Titles carry no pixel coverage at all this slice — the
  only thing recorded is the `titles` `not-checked` finding from §7.1, which says a
  title was declared, not that it rendered. Closing the gap needs the title's band
  geometry from `titles.y_exprs` plus the safe-zone table, to know where in the frame
  to diff.
- **Auto re-render of one converged episode.** Already possible —
  `process_episode --route <frozen>` skips tracking — so this is skill guidance in
  this slice, not machinery. A driver that does it in one step is a separate row.
- **Calibrate §7's constants on real footage.** They are measured, but on synthetic
  patterns and one encode profile.
- **Generalize the probe to the other QC axes** (composition, path smoothness). The
  primitive is axis-agnostic; only colour is wired here.
