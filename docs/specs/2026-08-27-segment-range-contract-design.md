# The segment format contract — design

**Date:** 2026-08-27 · **Backlog:** R2.0, R2.3 (both closed here) · **Size:** M

## 0. What was measured

Every number below comes from the preserved 2026-06 run's own footage and from
this repo's own `color.tone_arg`. Nothing here is reasoned from documentation.

### 0.1 The pool varies on three axes, not one

`ffprobe` over all **99** clips in the footage folder:

| clips | codec | pix_fmt | range | matrix/prim/trc | dims | fps | audio |
|------:|-------|---------|-------|-----------------|------|-----|-------|
| **67** | h264 | `yuvj420p` | **pc** | bt709 | 1920x1080 | 60000/1001 | aac 48k/2 |
| 29 | h264 | `yuv420p` | tv | bt709 | 1920x1080 | 60000/1001 | none |
| **3** | **hevc** | **`yuv420p10le`** | tv | bt709 | **3840x2160** | 60000/1001 | none |

So **two thirds of the pool is full-range**, which is a larger fact than "the
Canon is pc" sounds. Colour matrix, primaries and transfer are bt709 on all 99.
No rotation side-data anywhere. Frame rate is uniform. **32 clips carry no audio
stream at all.**

### 0.2 The measurement side was never broken — the retro is wrong about it

The retro's R2 chain lists `measure_profile` as a defect: "reads the raw source
file … no range handling". Measured, it handles range correctly, because
`format=gray` reads the source's own tag and swscale converts:

| source | stored Y plane vs `format=gray` |
|--------|--------------------------------|
| DJI (tv) | mean \|Δ\| **4.59**, max 20 — the tv→full expansion |
| Canon (pc) | mean \|Δ\| **0.41**, max 6 — chroma-subsampling noise, no conversion |

Both cameras therefore arrive at `color.percentiles` in one common full-range
domain. There is nothing to fix on the measurement side, and a "fix" there would
have broken the one half that worked.

### 0.3 The real cause is `extract`, and it is invisible in its own command

`extract` re-encodes with `-pix_fmt yuv420p`, which reads as a normalization and
is not one: **libx264 keeps full range for a full-range input.** Measured on a
1-second cut of `MVI_3678.MP4` with `extract`'s own arguments, the segment comes
out `yuvj420p` / `color_range=pc`. Running reframe's real chain shape over it
(`crop,scale,fps,format=yuv420p`) the episode comes out `yuvj420p,pc` as well.

So the whole Canon lineage reaches `color.tone_arg` in a range its constants —
`TV_LO = 16`, `TV_SPAN = 219` — are not written for.

### 0.4 The cost, end to end

One common target `(61.0, 123.0, 198.5)`, computed the way `matchgrade` computes
it, applied through the real `tone_arg` to both cameras, measured through
`measure_profile`'s own `format=gray` path:

| segment | achieved − target (p5, p50, p95) |
|---------|----------------------------------|
| DJI (tv, the assumption holds) | (−1.0, −1.0, **−1.5**) |
| Canon (pc, the assumption is violated) | (−4.0, −2.0, **−8.5**) |
| Canon, normalized to tv at extract | (−1.0, −1.0, **−1.5**) |

`matchgrade.MATCH_EPS` is **4.0** — the threshold that decides whether an episode
needs correcting at all. The Canon's shoulder misses by more than twice that,
and the DJI beside it does not. Normalizing the range makes the two cameras
identical, to the digit.

This also revises a number this repo has been carrying. The mood-grade design
recorded a **6.5–11.5 luma** floor between what the conductor asks for and what
lands, and deferred-measurements diagnosed it as `curves=all` being a per-channel
transfer against a luma target. That diagnosis was correct *for the code of the
day*; the luma-tone-transfer slice then replaced `curves` with `lutyuv`. What is
left after that slice is **1.5 codes when the range is right and 8.5 when it is
not** — the residual is no longer content, it is the range.

### 0.5 The 10-bit hole the backlog row never named

`TV_LO`/`TV_SPAN` are constants of **bit depth** as much as of range: 10-bit
limited black is 64 and white 940. Fed a real 10-bit clip from the pool
(`DJI_20260625083848_0548_D.MP4`, stored Y spanning 41..974 over 927 distinct
values), `tone_arg` returns a plane spanning 45..191 with **138** distinct values
and **99.26 % of all pixels pinned to a single code**. The picture is destroyed,
not shifted.

The conveyor is safe from this today *only* because `extract` requests
`-pix_fmt yuv420p`: measured, that clip extracts to `h264, 3840x2160, yuv420p, tv`
— eight bits, limited range, native resolution. What is unprotected is a direct
`reframe` / `process_episode` run over raw footage, which the skills document as
an authoring path.

### 0.6 The superwhite band collapses even when the range is right

Above the map's top knot the emitted expression falls through to a constant.
With everything in tv that still catches the superwhite band. Measured after a
real `tone_arg` render:

| segment | stored Y > 235 | input codes | distinct outputs |
|---------|---------------:|-------------|-----------------:|
| DJI (tv) | **0.1247 %** | 236..253 | **1** (code 202) |
| Canon, normalized | 0.0001 % | 236..240 | 1 (code 204) |

Eighteen input codes become one. That is exactly the plate `TONE_TOP_SLOPE`'s own
docstring says it exists to prevent — the shoulder does its job up to 235 and
then throws the rest away.

## 1. The rule

**A segment is the pipeline's canonical form, so make it canonical in fact.**

Everything downstream of `extract` — the tracker, `reframe`'s crop and grade, the
stabilize and ramp pre-stages, `check_episode`, `assemble`, `deliver` — consumes
segments and never the original footage. `extract` is therefore the one place
where "the footage is heterogeneous" can stop being true, and the only place
where fixing it costs nothing: that function already re-encodes.

The rule is not "normalize everything". It is: **each property is either in the
contract with a reason, or out of it with a reason.** A property nobody decided
about is how the range got here.

## 2. The contract

After `extract`, a segment is:

| property | value | why |
|----------|-------|-----|
| codec | `h264` (libx264, crf 18, preset medium) | unchanged; concat and every downstream probe expect it |
| pixel format | `yuv420p`, **8-bit** | unchanged in spelling, and it is what makes §0.5 unreachable through the sanctioned path |
| **colour range** | **`tv`** (or untagged, which is `tv` by mp4/h264 convention) | **the change.** `TV_LO`/`TV_SPAN`, `assembly.DELIVERY_RANGE` and the delivered reel all already say tv; the segment was the one link that did not |
| matrix / primaries / transfer | passthrough | bt709 on all 99 clips — nothing to normalize, and an unmeasured conversion would be a new landmine (§3) |
| resolution | **native** | `reframe` crops from native pixels; a downscale here would discard exactly the detail 4K was shot for (§3) |
| frame rate | native | uniform 59.94 in this pool; `reframe`'s tail already emits the source's own rate |
| audio | `aac 192k` when the source has a stream | unchanged; 32 of 99 clips have none and produce video-only segments, which `mix`'s ambient bed already tolerates |

`assembly.DELIVERY_RANGE` is `"tv"` and always was. This slice does not choose a
range — it makes the segment obey the one the delivery already declared.

## 3. What is deliberately NOT in the contract

**Resolution.** Normalizing it would be a regression, not a simplification.
`reframe` cuts a crop rect out of the source plane; a 4K source downscaled to
1080 at extract loses the crop's detail permanently. The intake-analysis-proxy
design already drew this exact line for the same reason — the proxy is
analysis-only and `extract`/`reframe`/`deliver` are untouched. Measured
confirmation that the change respects it: the filter carries no dimensions, and
the 10-bit 4K clip still extracts to 3840x2160.

**Colour matrix, primaries, transfer.** All 99 clips are bt709, so there is no
measurement to build against, and `scale`'s matrix conversion is exactly the kind
of silent transform this repo files as a landmine when it is not proven. A bt601
or HLG source would be misread with no signal today — recorded in §10, not built.

**Frame rate.** Uniform here. Resampling at extract would move frames before
tracking, which is the same class of mistake as stabilizing after measuring a
route (2026-07-20 §1).

## 4. The three changes

### 4.1 `extract.extract()` normalizes the range

Add `-vf "scale=in_range=auto:out_range=tv"` and `-color_range tv`. `in_range=auto`
reads the source's own tag (and ffmpeg's yuvj⇒full default when it has none), so
this **converts samples** rather than relabelling them; `-color_range` writes the
matching tag. This is the identical recipe `assembly._normalize` already uses at
concat — moved to where it can still save the grade instead of arriving after it.

**"Both halves are needed" is what this section first said, and it is not true on
the shipped ffmpeg.** Measured 2026-08-27 while a mutation row refused to go red:
the filter alone, the tag alone, and both together all produce **byte-identical**
output carrying the same `tv` tag (md5 `deb09207…`, four ways, on the pc fixture
and on the real Canon); `out_range=auto` beside the tag lands there too. Only
removing **both** reverts (`82f376b8…`, tag `pc`).

**Every one of those measurements held `-pix_fmt yuv420p` fixed, and the first
version of this correction did not say so.** Caught by the final whole-branch
review, which varied the one argument nobody had varied. Over all **seven**
combinations on this repo's own pc fixture: without `-pix_fmt yuv420p` **nothing
converts** — filter alone, tag alone and both together all return `yuvj420p`/`pc`,
byte-identical (`a6ca8b59…`) — and `-pix_fmt yuv420p` alone returns those same
bytes. With it, all three spellings converge on `yuv420p`/`tv` (`fc9ea33a…`). The
true relation is **`-pix_fmt yuv420p` AND (filter OR tag)**: the pix_fmt is
individually necessary and not sufficient, the pair is sufficient given it, and
either half of the pair will do. Saying "the filter or the tag converts" without
that clause is itself the silent-corruption shape this repo files as a landmine —
a reader drops the pix_fmt, keeps the pair, and ships an unconverted `pc` file
believing it normalized.

Both are kept anyway — it costs nothing, it is the spelling `assembly._normalize`
already uses, and the redundancy is cheap insurance against an ffmpeg where the
auto-inserted path behaves differently. But the honest consequence is recorded in
§6: no assertion over rendered bytes can pin either half individually, so the
argv-level unit test is the only thing that does.

**Measured byte-identical on everything that was already right**, three ways:

| source | md5 with and without the change |
|--------|--------------------------------|
| DJI, tagged tv, 1080 | `0195fb45…` = `0195fb45…` |
| the `sample_clip` fixture, untagged | `49d6d2e7…` = `49d6d2e7…` (tag stays `unknown` both ways) |
| the 10-bit HEVC clip, tagged tv, 4K | `58e3f9a1…` = `58e3f9a1…` |

So no golden moves. Only the 67 pc clips change, which is the point.

The price is real and permanent: pc→tv at 8 bits is a pure integer round trip of
**max 1 code, mean 0.141, and 36 of 256 levels lost**. One code, to remove eight
and a half.

### 4.2 `color.tone_arg()` continues the shoulder instead of clamping

The final fall-through stops being the constant `top` and becomes the last
segment's linear extrapolation. Codes 236..253 then land on 202..209 instead of
all on 202 — monotone, and bounded without clipping in every legal case, because
the input is bounded too. The largest `v` a stored code can produce is
(255−16)·255/219 = **278.3**, `top` is at most 255, and the extension's slope is
at most `TONE_TOP_SLOPE` = 0.35 by construction of `_segments`, so the extended
output is at most 255 + 23.3·0.35 = 263.2 in the full domain, which stores as
**242** — thirteen codes below the ceiling.

`_lerp` is already an independent second implementation of the same arithmetic,
kept deliberately so the real-ffmpeg ramp proof compares one against the other.
It needs the matching change, made **independently** — sharing the code would
make the proof compare a bug against itself.

### 4.3 `reframe` refuses pixels its colour maths cannot read

`_probe` adds `pix_fmt` and `color_range` to the `-show_entries` list of the
ffprobe call it already makes — zero extra cost. `plan_render` then refuses a
source that is not 8-bit, or that is explicitly tagged `pc`, naming the remedy
(run it through `extract`).

**Those two properties and no others.** Codec and resolution are nobody's
assumption; refusing on them would block legitimate hand runs for no reason.
Depth and range are literally what `TV_LO`/`TV_SPAN` encode, which is what makes
this a predicate for *wrong* rather than a preference — the test the run-layout
slice's §5 set for any refusal.

An untagged source passes, because untagged is the mp4/h264 convention for
limited and `assembly.matches` already treats it that way. This is a gap by
construction: a full-range file that lost its tag is indistinguishable from a
limited one and will be read as limited. Recorded in §9.

## 5. Why extract, and not a range-aware `tone_arg`

The alternative is to thread the source's range into `ReframeSpec` and pick
`TV_LO`/`TV_SPAN` per episode. Rejected on three counts, all measurable:

1. **The pixels stay heterogeneous.** The Canon episode still ships `pc` to
   `assemble`, where `matches()` classifies it as an outlier and re-encodes it
   whole — a full extra generation that normalizing at extract removes for 67 of
   99 clips.
2. **The surface is larger for less.** A new field on `ReframeSpec`, the EDL and
   the manifest, carried through every driver, versus one filter in one function.
3. **It fixes one consumer.** Range is not only `tone_arg`'s problem — it is
   every future comparison between episodes. A contract fixes the class; a
   parameter fixes the caller.

Keeping `assembly`'s normalization as the only line of defence (today's state) is
not an option at all: it runs after the grade, so it can make the concat uniform
and can never make the grade right.

## 6. Proofs

Five real-ffmpeg proofs, each with a control that must not move.

0. **The argv-level unit test is load-bearing in a way the other proofs are not.**
   Because either half of the pair produces byte-identical pixels (§4.1), it is
   the only check that can notice one of them going missing. Treat it as a proof,
   not a spelling test.
1. **The three byte-identity controls** of §4.1 — tv 1080, untagged fixture, tv
   4K 10-bit. The fix has no right to move what was already correct.
2. **A pc source's transfer error, before and after.** The central claim. The
   synthetic pc fixture must first **reproduce the defect** — a fixture that does
   not discriminate is this repo's recurring review finding, most recently three
   tests that passed on the resampler rather than on the frame.
3. **Normalizing does not move the profile `format=gray` reports.** Measured on
   the same Canon cut: (51, 113, 194) before the change and (51, 113, 194) after.
   This is what makes measuring the raw source (`match_grade`) and grading the
   segment (`reframe`) commensurable at all, so it is now load-bearing and must
   be pinned rather than left to luck. It is a claim about the *normalization*,
   not about raw-vs-segment agreement in general — that one is also affected by
   the re-encode and by which timestamp each side samples.
4. **The superwhite band** — distinct output codes in the >235 band go from 1 to
   eight, with a control below the band that must not move.
5. **The guard** — a 10-bit source and a pc source refused, an 8-bit tv source
   accepted.

Plus a mutation battery under `PYTHONDONTWRITEBYTECODE=1`. A surviving row is a
coverage hole, never a row to soften.

One behaviour change is worth its own test because it is a silent improvement:
after the fix, `assembly.matches` accepts a Canon-lineage episode and concat
copies it instead of re-encoding it.

## 7. Honest limits

- **The 8.5 → 1.5 improvement is two frames of one shoot.** The direction is
  structural — the range assumption is either true or false — but the magnitude
  is content-dependent and nobody has measured a second shoot.
- **Nothing checks that the grade landed on target.** After this the miss is
  ~1.5 codes on both cameras, but no gate anywhere compares a delivered episode
  against the target it was given: `color_fidelity` is blind to exposure by
  construction (its own docstring says so) and `check_reel`'s `color_across_cuts`
  compares episodes to *each other*, so a uniformly wrong reel passes.
- **The quantization loss is permanent and is paid by two thirds of the pool.**
  36 of 256 levels, on every render from now on, irreversibly inside the segment.
- **The guard proves the premise, never the picture.** It can say the pixels are
  in the range the arithmetic assumes. It can never say the grade looks right.
- **An untagged full-range file is still misread**, by construction (§4.3).
- **Nobody has looked at the extended shoulder.** Eight codes instead of one is
  strictly more information; whether it looks better is unmeasured, and it
  touches 0.1247 % of pixels on the frame it was measured on.
- **The preserved run is not re-graded.** Its eight episodes went through the
  broken range and stay that way — which is precisely why R2.2's calibration was
  deferred to a slice after this one, rather than folded into it.

## 8. Deferred

- **Matrix / primaries / transfer are not in the contract.** A bt601 or HLG
  source is misread silently. No evidence in this pool; own row.
- **A gate that the tone converged to its target.** Adjacent to R2.2 (the fidelity
  metric) and R2.6 (the retry loop that can make the grade worse), but neither of
  them — those judge drift and regression, not whether the authored pair was
  reached.
- **R2.2 — `color_fidelity` re-derived or deleted.** Deliberately the next slice:
  its threshold has to be calibrated on a run, and every run on disk was graded
  through the range this slice fixes.
