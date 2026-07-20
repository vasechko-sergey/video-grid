# Stabilization, applied — a pre-stage, not a filter in the chain

**Date:** 2026-07-20
**Slice:** design spec §5.2 / §10 — the apply half of stabilization
**Status:** design approved, not yet built

The measure half shipped with footage-intake (2026-07-12): `intake.shake_by_window`
runs `vidstabdetect` over a raw clip and lands a per-window `shake` number in
`FOOTAGE.json`/`FOOTAGE.md`. Nothing ever consumed it. `stabilize: true` was refused
in two places, and `vidstabtransform` was unavailable anyway until the ffmpeg-baseline
slice (2026-07-20) put `ffmpeg-full` behind `lib/ffbin.py`.

This slice makes the flag work.

---

## 1. The load-bearing decision: stabilization cannot live in `reframe`'s chain

The obvious implementation is one line: prefix `vidstabtransform` onto the `-vf`
chain `reframe` already builds, ahead of `crop`. It is wrong, and wrong in the
§12 way — it produces a plausible file with a defect no gate catches.

`reframe` places its crop from a **route**, and the route was measured by
`track.build_route` on the **unstabilized** segment. A route point at time `t`
says the subject's centre is at source-x `1200`. After `vidstabtransform`, the
subject at time `t` is at `1200 + dx(t)`, where `dx(t)` is the correction vidstab
applied. The crop is still placed from `1200`.

So the subject sits at offset `dx(t)` inside the crop, frame after frame — a
residual wobble whose amplitude is **exactly the shake vidstab just removed**.
The delivered clip has a rock-steady background and a jittering subject, which
reads worse than the untouched shot. `compute_path`'s `max_speed` damping does
not save it: damping smooths the crop's *travel*, it cannot correct a systematic
frame-to-frame offset between two coordinate systems.

`check_episode` cannot catch it either, and for a reason worth naming: the
on-line/centred check verifies the *path* against the *route*. Both are in
source coordinates. Both agree. Only the pixels disagree. The check would confirm
the framing while the framing is wrong — the same circularity the pan design
found in `route.json`'s consumers (2026-07-19 §2).

### 1.1 The tempting fix is worse

The natural repair is to shift each route point by the frame's correction — we
already parse `.trf` files, so the numbers are right there.

It does not work. The `.trf` records the **detected inter-frame motion**, not the
**applied transform**. `vidstabtransform` computes the applied transform by
low-pass filtering the detected camera path (`smoothing`, `optalgo`) and taking
the difference, then adds zoom and, on rotation, an angle. Back-projecting a
route through that means reimplementing libvidstab's smoothing in Python and
keeping it bit-compatible across libvidstab versions. Every drift between the two
implementations is a silent framing error.

### 1.2 So: a pre-stage, producing a file

```
probe(m.segment)  →  layout preflight  →  pan preflight
   →  [NEW]  if m.stabilize:  src = vidstab.stabilize(m.segment, <project_dir>/stabilized.mp4)
   →  track(src)  →  contradiction gate  →  loop: reframe(src) → check
```

Route and pixels are in one coordinate system **by construction**, because the
tracker sees the same file the crop indexes. That property is what this slice
buys, and it is worth the extra encode.

Design spec §10 already said it — "vidstab two-pass on the **source before
crop**" — but "before crop" reads as "earlier in the filter chain" and means
"before the thing that consumes the coordinates". The distinction was never
written down. It is now.

---

## 2. Where in `process_episode`, precisely

Three sites hold `m.segment` today (`scripts/process_episode.py`):

| line | site | after this slice |
|---|---|---|
| 100 | `reframe._probe(m.segment)` | **stays on the original** |
| 156 | `TrackSpec(src=m.segment, …)` | the stabilized file |
| 186 | `reframe.reframe(rspec, m.segment, …)` | the stabilized file |

The probe stays on the original deliberately. It exists so a manifest the layout
cannot satisfy "fails in milliseconds, not after YOLO has walked the whole
segment" (the comment at line 98). Stabilization is two ffmpeg passes over 4K —
moving the probe after it would spend them before the cheap refusal, defeating the
preflight's whole purpose.

That creates one obligation: **re-probe the stabilized file and fail loud if the
geometry moved.** `vidstabtransform` preserves dimensions, frame rate and duration
— `zoom` is internal to the transform, the output frame is the input frame's size
— but "preserves" is a promise from a library, and if it were ever false the
layout preflight's numbers would be stale while everything downstream carried on
computing with them. A cheap comparison turns that into a raise.

Stabilization sits **outside** the retry loop. It runs once; retries re-render
`reframe` against the same stabilized file. That is both correct (the input to
the loop does not change between attempts) and cheap.

### 2.1 It composes with `pan`

A pan tracks nobody, so §1's coordinate argument does not apply to it — but a pan
over shaky footage is still shaky footage. Both flags may be set. The stabilized
file simply becomes `reframe`'s `src`, and `generate_pan_path` is unaffected: it
reads `freedom` from the resolved layout, which the geometry guard above has just
proven unchanged.

---

## 3. `scripts/lib/vidstab.py` — new module, mostly by extraction

`intake.py` is the repo's only vidstab consumer today and holds the primitives as
privates. Two consumers means they move out, the same way `lib/appearance.py` was
extracted from `intake.py` in the cast → hero-pin slice (2026-07-16).

**Moves out of `intake.py`:** `_LM_RE`, `_read_trf`, `_parse_trf`,
`_require_vidstab`, `SHAKE_TIMEOUT_REALTIME_MULTIPLE`.

**Stays in `intake.py`:** `_windowed_shake` and `shake_by_window` — windowing a
clip into scored moments is intake's concern, not the library's. It imports the
primitives.

**The new module's surface:**

| name | does |
|---|---|
| `require()` | `ffbin.require_filter` on **both** `vidstabdetect` **and** `vidstabtransform` |
| `read_trf(path) -> str` | the binary-magic guard, unchanged |
| `parse_trf(text) -> list[float]` | per-frame median localmotion magnitudes, unchanged |
| `detect(src, trf, dur) -> list[float]` | one detect pass → parsed magnitudes |
| `mean_shake(mags, width) -> float` | mean magnitude ÷ frame width — the shared normalisation |
| `stabilize(src, out, dims, fps, dur) -> tuple[float, float]` | the whole pre-stage; returns `(before, after)` |

The geometry is **passed in, not re-probed**, and that is the point: `dims`/`fps`/
`dur` are exactly the numbers the preflight probe produced and the layout
resolution already computed with. Handing them to `stabilize` states the belief
the guard in §2 then proves still holds. `dims[0]` is also the width `mean_shake`
normalises by, and `dur` scales the timeout in §3.1.

`stabilize` cannot call `reframe._probe`, the obvious source of all four numbers:
`scripts.reframe` imports from `scripts.lib`, so a library reaching back for it
would close an import cycle. The guard's re-probe uses `assembly.probe_stream` and
`assembly.probe_duration`, which already live in `lib/`.

`require()` widening is not cosmetic. Today's `_require_vidstab` checks
`vidstabdetect` only, which was honest when detect was the only pass. A build
carrying detect but not transform is not a real homebrew configuration, but the
gate should say what it means.

### 3.1 The timeout constant's comment goes stale on the move

`SHAKE_TIMEOUT_REALTIME_MULTIPLE = 10.0` carries a derivation worth keeping (a
`mestimate=epzs` proxy measured 13.6 fps on 4K/30 → ~2.2× realtime, ~4.4× worst
case at 4K/60, 10× leaves >2× headroom). But the sentence introducing it says the
pass "runs over the WHOLE raw clip — **the one** analysis in this repo whose input
is unbounded raw footage". After this slice that is false: `stabilize()` uses the
same multiple on an extracted segment. The comment must be corrected in the same
commit that moves it, not left to read as a fact about a module it no longer lives
in.

---

## 4. The recipe

```
pass 1   vidstabdetect=shakiness=8:accuracy=15:result=T.trf:fileformat=ascii
pass 2   vidstabtransform=input=T.trf:smoothing=40:zoom=2:crop=keep,unsharp=5:5:0.4
pass 3   vidstabdetect=<same params as pass 1>   over the OUTPUT → residual
```

Probed from the installed binary (`ffmpeg -h filter=…`), not from memory:

| option | binary default | §10 recipe | this slice |
|---|---|---|---|
| `crop` | `keep` | `black` | **`keep`** |
| `optzoom` | `1` | `1` | omitted |
| `accuracy` | `15` | `15` | omitted |
| `shakiness` | `5` | `8` | `8` |
| `smoothing` | `15` | `40` | `40` |
| `zoom` | `0` | `2` | `2` |

`optzoom=1` and `accuracy=15` are dropped because writing a value identical to the
default performs a choice that was never made — a later reader cannot tell a
deliberate setting from transcription.

`crop=keep` is *also* the binary default, and is written anyway. It is the one
place the recorded recipe says the opposite, so relying on the default would leave
the decision documented nowhere and contradicted in §10.

### 4.1 Why `crop=keep` — the black gate does not cover `crop=black`

`crop=black` fills the uncovered border with black. Under a `fill` layout the crop
takes the full source height, so a black band at the top or bottom of the
stabilized frame lands in the delivered frame whole.

`check_episode._black_frames_check` will not see it. That gate compares **frame
medians** against an absolute floor and a relative fraction of the body median — it
exists to catch a fully-black or near-black frame from the seek-order or `lutrgb`
landmines. A band occupying a few percent of the frame does not move a median.
There is no other geometry gate on the episode's edges.

So `crop=black` opens a silent-corruption path with no machine guard, and the
alternatives were (a) build an edge-scan check, or (b) never introduce the black.
`crop=keep` fills the border from the previous frame instead: the failure class
stops existing rather than being detected. The cost is a slight smear at the very
edge, largely hidden by `zoom=2`.

**Consequence for docs:** design spec §10's recipe is wrong on this point and is
corrected in this slice, with the reason recorded — not silently edited.

### 4.2 The intermediate is encoded at crf 12, not 18

`stabilized.mp4` is consumed twice — by YOLO and by `reframe` — and then thrown
away. `reframe` re-encodes at crf 18, and `deliver` encodes again after that. At
crf 18 the intermediate would spend a full generation that nothing can recover.
crf 12 is visually lossless at a size that is irrelevant for a 1.2–4.0 s window
(the `WIN_MIN`/`WIN_MAX` band).

### 4.3 `unsharp` is kept, with its caveat named

§10 records `unsharp=5:5:0.4` as proven on real footage, countering the softening
from `vidstabtransform`'s bilinear interpolation. It is kept.

But it is the one parameter whose **position changed** relative to where it was
proven: in the session it ran in the same chain as the crop, at delivery scale;
here it runs on a 4K intermediate that a crop and a scale then consume. For the
common case (4K source → ~1080-wide 9:16 crop → 1080×1920) that is still roughly
1:1, so the sharpening lands near delivery scale — but this is reasoning, not
measurement, and it is flagged rather than asserted. If real footage later shows
haloing, `unsharp` moves or goes; the constant is named so that change is one edit.

---

## 5. One detect recipe, shared with intake — and the golden it moves

`intake.shake_by_window` detects with **no** `shakiness`, i.e. the binary default
`5`. §10's recipe raises it to `8`.

Left alone, that produces two different measurements wearing the same name:
`FOOTAGE.md` shows the author `shake 0.031` for a window, and `process_episode`
reports `stabilize.before = 0.045` for the segment cut from it. Nothing in either
document says they are incomparable. A reader would compare them, because they are
the same word in the same units on the same footage. That is precisely the §12
shape — a plausible number that is quietly measuring something else.

**So both use one constant**, at §10's `shakiness=8`. `intake` adopts it.

This **moves intake's shake numbers** and therefore its golden
(`test_intake_real_vidstab_shake`, first executed 2026-07-20). That is accepted:
a changed number with a recorded cause is not corruption, and the alternative —
two incomparable numbers sharing a name — is the failure mode this repo exists to
avoid.

`SHAKY_CLIP = 0.02` is already annotated "tune on real footage" and is not
re-tuned here; no real footage has been through the pipeline yet, so any new value
would be invented. The threshold's *inputs* changing while the threshold stays put
is noted in the intake constant's comment.

---

## 6. Contracts

| contract | change |
|---|---|
| `Manifest.stabilize` | kept. The `validate()` **refusal is deleted**; a capability gate replaces it — `stabilize=true` on a build without `vidstabtransform` appends a remedy-bearing problem, so it surfaces as `needs_input` like every other manifest problem, not as a traceback |
| `ReframeSpec.stabilize` | **deleted**, along with its `__post_init__` refusal. `reframe` never sees stabilization; a field it cannot act on is a lie in the type. Its replacement is a `stabilized=` **parameter** — see §6.2 |
| `PathMeta.stabilized` | new `bool` provenance bit, exact mirror of `pan` (2026-07-19 §5), fed by that parameter |
| `EDLEpisode.stabilize` | new `bool` field, default `False`; `to_dict` carries it; `to_manifest_dict` copies it **only when True**, the same shape `pan`/`motion`/`hero` use, so an absent flag leaves the key out rather than carrying an explicit `false` |
| `process_episode` result | new key `"stabilize": {"before": …, "after": …}`, beside `"timings"` |

**No `StabilizeSpec`.** The recipe is constants, not authored data. The retry
ladder tunes exactly one thing (`max_speed`, via `adjust_reframe_params`) and
stabilization is not in it — it is editorial intent, the same category as `layout`
and `pan`, which `process_episode` builds once outside the loop.

### 6.1 The capability gate spawns ffmpeg only when the flag is set

`manifest.validate()` runs in a great many tests. The gate calls
`ffbin.has_filter` — a real subprocess — so it is guarded by `if m.stabilize:`.
Only stabilize-bearing manifests pay, and those tests monkeypatch it. The hard
backstop stays in the engine (`vidstab.require()`), the same soft-manifest /
hard-engine pairing the layout preflight uses.

### 6.2 Where `PathMeta.stabilized` comes from

`reframe()` writes the sidecar, but does not stabilize — so, unlike `pan`, it
cannot derive the bit from its own spec. Deleting `ReframeSpec.stabilize` (an
instruction `reframe` cannot carry out) and then asking `reframe` to record
stabilization looks contradictory. It is not, and the distinction is the tense:

- **`stabilize`** is imperative — "perform this". `reframe` cannot, so the field
  is a lie in the type and goes.
- **`stabilized`** is declarative — "the `src` you were handed already is". That
  is a true fact about an argument, and recording facts about its input in the
  sidecar is exactly `PathMeta`'s job.

So it arrives as a **parameter**, not a spec field:
`reframe(spec, src, route_path, out, path_out, stabilized=False)`. `reframe`'s own
docstring already draws that line — "src/route_path/out/path_out stay explicit
per-call I/O paths, not config" — and `stabilized` describes `src`, so it belongs
on the same side of it. The only thing `reframe` does with the flag is pass it to
`PathMeta`.

The alternative, having `process_episode` re-read and rewrite the sidecar after
`reframe` returns, would give one file two writers for no gain.

### 6.3 The numbers go in the result, not in `Report`

`check_episode.Report` is read by `check_reel` and the storyboard path. Adding
stabilization figures there would invite a consumer to gate on them, and this
slice deliberately ships no threshold (§7). `process_episode`'s returned dict is
where stage-level facts already live — `timings` sets the precedent.

---

## 7. What this slice honestly does not do

**The wade-in landmine keeps no machine predicate.** §12 says stabilizing a
wade-in/out-of-water shot produces "rolling ground". No code in this repo can
identify such a shot: `intake.shot_type` classifies by subject *size*
(`close`/`medium`/`wide`), not content, and the design's `wade → center`
composition mapping also catches `establishing` and `atmospheric`, so refusing on
it would block innocent episodes.

Three options were weighed for who sets the flag. **Auto-enabling on
`window.shake > SHAKY_CLIP` was rejected outright**: a wade shot is handheld in
moving water and is therefore *noisy by construction*, so a shake threshold fires
most confidently on exactly the shot §12 forbids touching. The flag is
**explicit** — authored by a human or agent in the EDL — and the rule stays
editorial, in the SKILL text, where the rest of the judgment already lives.

The signal is not lost: `FootageWindow.shake` is already printed in `FOOTAGE.md`'s
window table, so whoever authors the EDL sees the number when they decide. This
slice adds no auto-suggestion on top of that.

**The before/after measurement does not catch the wade case either**, and saying
so is the point of writing it down: "rolling ground" is a *warp*, and a
successfully-flattened wade shot reports a *low* residual. The measurement proves
stabilization ran and did something; it does not prove it should have.

**No threshold on the drop.** Gating "residual must fall by X%" needs a calibrated
X, and no real footage has been through this pipeline. An invented X would be a
gate that fails for reasons unrelated to quality. The number is reported; the
judgment stays with the reviewer until there is material to calibrate on.

**Not in scope:** the tracking degradation ladder (optical-flow / manual rungs)
and §6.1a layer 3 descriptor continuity re-match. Both need a route-provenance
design and share one; that is its own slice.

---

## 8. Testing

Unit, against stubbed `proc.run`:
- `require()` names both filters; missing transform fails loud with the remedy.
- `parse_trf` / `read_trf` behaviour survives the move byte-for-byte (the existing
  intake tests move with the code).
- `mean_shake` normalisation.
- `stabilize()` emits the exact argv of §4 — both passes — and the crf-12 encode.
- the geometry guard raises when the re-probe disagrees.
- `Manifest.validate` no longer refuses; refuses when the filter is absent.
- `ReframeSpec(stabilize=…)` is a `TypeError` (the field is gone, not falsified).
- `to_manifest_dict` omits the key when False, carries it when True.
- `process_episode` threads the stabilized path into `TrackSpec` **and**
  `reframe`, and leaves the preflight probe on the original.

Real-ffmpeg integration (the proof, marked like the other real-pixel tests):
- a synthetic shaky clip through `stabilize()` reports `after < before`. This is
  the one assertion that cannot be faked by a stub and is the slice's charter.
- a full `process_episode` run with `stabilize: true` reaches
  `mechanical_pass`, and `path.meta.json` carries `stabilized: true`.
- the output of a `crop=keep` transform has **no** black band at any edge — the
  positive control for §4.1, since that decision is otherwise only prose.

Mutation checks (steps, not suggestions):
- flip `crop=keep` → `crop=black` and confirm the edge test fails. A test that
  passes under both values is testing nothing.
- point `TrackSpec.src` back at `m.segment` while `reframe` keeps the stabilized
  file, and confirm a test fails. §1's whole argument is that this combination is
  wrong; if the suite tolerates it, the argument is unguarded.

---

## 9. Doc sync

- **Design spec §10** — correct `crop=black` → `crop=keep` with the reason;
  drop `optzoom=1` as a default; note that "on the source before crop" means a
  separate file, not filter order.
- **Design spec §12** — three entries: the route/pixel coordinate-frame trap
  (§1), `crop=black`'s band being invisible to the median-based black gate (§4.1),
  and the two-measurements-one-name hazard that §5 closes.
- **§5.2 / pipeline-map** — the apply half lands; the stage's status moves.
- **`CLAUDE.md`** registry row, **`docs/build-status.md`**, and the plan's
  checkboxes, in the same commits.
