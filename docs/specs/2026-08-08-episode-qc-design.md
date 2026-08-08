# Per-episode QC — design

**Date:** 2026-08-08
**Backlog:** [fixes-backlog.md](../fixes-backlog.md) #3 (per-episode rendering and
quality control in subagents), the per-episode half of #12 ("look, don't guess")
**Playbook:** [cinematic-quality-playbook.md](../cinematic-quality-playbook.md) §4
priority 3 — the last item of P3 that is not blocked on a new model
**Status:** design approved 2026-08-08

---

## 0. What the run showed

The 2026-08-03 real run shipped episodes nobody had looked at. The feedback that
came out of it (backlog #3) asks for two things:

- episode **rendering** must run in a subagent;
- each episode must pass **quality control** in a subagent, checking **composition
  rules**, **colour naturalness**, **overall impression**, and **smoothness of the
  hero's path**.

The orienting note filed with #3 guessed that the first half "may be partly
structural already", because `skills/process-episode/SKILL.md` describes one
subagent per episode and carries an editorial gate: on `mechanical_pass`, open the
storyboard and judge *right person* and *reads well*.

That guess was wrong, and the way it is wrong is the reason this slice exists.
`edl_to_reel` calls `process_episode.process_episode` **as a Python function**
inside a `ThreadPoolExecutor` ([edl_to_reel.py:91](../../scripts/edl_to_reel.py)).
No subagent is dispatched. Nothing reads the storyboard. The editorial gate in the
`process-episode` SKILL runs only when a human drives one episode by hand — which
the conveyor never does. In a router-driven run that skill's judgment half is
**dead text**, and has been since the SP1 driver landed.

So the honest statement of the gap is not "QC is too shallow". It is: **between the
EDL and the delivered reel, no judgment of any kind is applied to an episode.**
`check_episode` measures six mechanical things and reports two more as
`not-implemented`; everything the feedback asks for is in neither list.

## 1. What must be true

1. **A reel is not assembled over an episode that failed.** The user's criterion,
   stated in those words: there is no point cutting the full version if an episode
   fails quality. The gate therefore sits *after* the per-episode render and
   *before* reel assembly — not after delivery.
2. **The judge sees pixels.** #12's lesson. A verdict grounded in numbers alone
   re-runs the same blindness that produced the run; a verdict grounded in nothing
   is worse.
3. **The verdict is bound to the bytes it judged.** A verdict that names an episode
   but not *which render* of it is a verdict about a file that may no longer exist.
4. **The judge cannot lower the bar.** Governance #8: a subagent must not be able to
   disable quality control. The QC agent writes findings; it never writes the gate's
   inputs (the digest), and there is no waiver field for it to fill.
5. **Nothing is claimed that is not checked.** The stage proves the artifact exists,
   is complete, is bound to these clips, and carries no blocking finding. It does
   not prove that anyone looked — see §12.

## 2. Where the gate sits — the two-phase split

`edl_to_reel` today is one call: preflight → extract → `process_episode` fan-out →
`ReelManifest` → `build_reel` (assemble → check → reprocess → deliver). The gate
needs a seam in the middle of that, because the episode clips exist there and the
reel does not yet.

The driver gains two mutually exclusive flags:

| Flag | Does | Returns |
|------|------|---------|
| `--stop-after-episodes` | preflight, extract, the `process_episode` fan-out, then **write `EPISODES.json` and stop** | `{"status": "episodes_ready", "episodes": "<path>", "count": N}` |
| `--from-episodes PATH` | load `EPISODES.json`, **run the QC gate**, then `build_reel` | today's `delivered` / `stop_and_report` |
| *(neither)* | today's behaviour, end to end, in one command | unchanged |

`EPISODES.json` needs no new contract: its schema **is** `ReelManifest`, which
already has `from_dict`/`from_json` and is exactly what phase 2 must reconstruct.
It has no `to_dict` today (the type has only ever been built in memory or
hand-authored in tests), so this slice adds `ReelEpisode.to_dict` +
`ReelManifest.to_dict` and pins the round-trip. That closes an asymmetry that
already existed: `build_reel`'s CLI can *read* a reel manifest that nothing in the
codebase can *write*.

The episode clips are already delivered-geometry pixels at this seam:
`edl.preflight` assigns each episode `out_dir/ep{i}.mp4`, and `process_episode`
writes there. The judge looks at the same file the reel will be cut from — not at
a proxy, not at the source window.

### Alternatives rejected

- **QC after delivery (post-hoc).** Cheapest — no split, and it judges exactly what
  shipped, including episodes the retry loop re-rendered (§8). Rejected on the
  user's criterion in §1.1: it burns a full assemble + check + encode before anyone
  looks.
- **Replace the Python pool with an agentic fan-out** (what the `process-episode`
  SKILL currently describes). The router would own the middle of the driver, and
  the reproducible one-command SP1 run — a hand-authored `EDL.json` to a delivered
  reel, which is the front door §5.7 was built around — would stop existing.
- **Forbid the retry loop's auto-reprocess while QC is in force.** It would close
  §8's hole exactly, and it would also kill the colour-convergence loop that Phase
  A.5 exists for.
- **Mechanical-only QC.** Of the four asked dimensions, two (horizon level, overall
  impression) have no sensor today and `check_episode` already reports the closest
  two as `not-implemented`. A mechanical stand-in would report green on precisely
  the failures the run produced.

## 3. The artifacts

| File | Where | Written by | Schema |
|------|-------|-----------|--------|
| `EPISODES.json` | `<run>/out` | `edl_to_reel --stop-after-episodes` | `ReelManifest` |
| `EPISODE_QC.json` | `<run>/out` | `episode_qc build` | `ReelQC`, §4 |
| `EPISODE_QC.md` | `<run>/out` | `episode_qc build` | rendered |
| `qc/ep{i}/strip.jpg` | `<run>/qc` | `episode_qc pack` | image |
| `qc/ep{i}/evidence.json` | `<run>/qc` | `episode_qc pack` | the packet, §6 |

The two gate files live in the **out dir**, beside the `ep{i}.mp4` they are about —
the verdicts and the judged clips in one directory, so a run dir carried to another
machine cannot separate them. Both router rows are therefore `in_out=True`
(`REVIEW.json`, which judges the assembled reel rather than its parts, keeps living
in the run dir). The evidence packets are bulky and derived, so they go to their own
`<run>/qc` tree, named by an explicit `--out-dir` on `pack`.

`EPISODE_QC.json` is found **beside `EPISODES.json`, by convention** — there is no
flag for phase 2 to be launched without. This is the discovery rule the
editorial-constraints slice landed on for the same reason: a flag is a thing to
forget, and a gate that is skipped by forgetting is not a gate
([2026-08-07-editorial-constraints-design.md](2026-08-07-editorial-constraints-design.md) §6).
`pack`'s `--out-dir` is a producer flag and carries no such risk: forgetting it
cannot skip the gate, only fail to feed it.

## 4. The contract — `scripts/lib/episode_qc.py`

Pure, no ffmpeg, no IO beyond JSON round-trip. The per-episode twin of
`lib/review.py`, deliberately shaped the same so the two read alike:

```python
QC_AXES     = ("composition", "colour", "impression", "path", "hero")
QC_SEVERITY = ("blocking", "important", "minor")
QC_ROUTES   = ("reprocess", "edit-plan", "match-grade", "none")
QC_CONFIDENCE = ("high", "medium", "low")

@dataclass
class EpisodeFinding:
    axis: str; severity: str; evidence: str; route: str; suggestion: str
    confidence: str = "high"

@dataclass
class EpisodeVerdict:
    idx: int                  # episode index in the EDL / ReelManifest
    clip: str                 # the judged clip path
    clip_digest: str          # sha256 of that file AT BUILD TIME — see §7
    findings: tuple = ()
    summary: str = ""
    reviewer: str = ""
    @property
    def verdict(self) -> str: ...      # "revise" iff any blocking finding, else "approve"

@dataclass
class ReelQC:
    episodes: tuple = ()      # tuple[EpisodeVerdict, ...]
    @property
    def ok(self) -> bool: ...
    def to_markdown(self) -> str: ...

def gate(qc: ReelQC, digests: dict) -> tuple:
    """Pure. (reason, problems) — reason is None iff the reel may be assembled.

    `digests` maps EVERY episode index in the reel to its clip's sha256 NOW: the caller
    owns the filesystem, this owns the decision. The missing-artifact case has no ReelQC
    to pass, which is why QC_STOPS names three reasons where §7's table lists four."""
```

`verdict` is a computed property, never a stored field — the `Review.verdict`
rule, for the same reason: a hand-edited artifact must not be able to lie about
its own verdict.

**Why five axes and not the feedback's four.** The fifth is `hero` — *is the
followed subject the intended one*. It is the main job of the editorial gate this
slice resurrects, and it has its own failure mode: an episode can be beautifully
composed, naturally graded, smoothly tracked, and follow a stranger. Folding that
into "overall impression" would let a wrong-person episode pass on the strength of
its framing.

**Routes** name the stage that owns the fix: `reprocess` (re-render this episode —
colour, composition params), `edit-plan` (the window or the hero pin is wrong —
re-cut), `match-grade` (the tone pair across episodes), `none`.

## 5. The sensor — `scripts/lib/naturalness.py`

"Colour naturalness" has no sensor today. `check_episode`'s `color_fidelity` is a
subject **hue-drift vs the source** measure: it answers "did the grade move the
subject's hue", and is blind to blown highlights, crushed blacks, a global colour
cast, and oversaturation — the four things that actually make a graded frame read
as unnatural.

Pure module, numpy arrays in, one dict out:

```python
def measure(frames: list[np.ndarray]) -> dict:
    """Per-clip aggregate over sampled frames:
         clip_high / clip_low   fraction of pixels at/near 255 / 0, per channel
         cast                   grey-world channel-mean deviation (max |c/mean - 1|)
         saturation             mean HSV-S
         contrast               p95 - p5 luma spread"""

def evaluate(stats: dict) -> dict:
    """Named advisory flags: blown_highlights, crushed_blacks, colour_cast,
    oversaturated, flat. Never a pass/fail — the agent judges, these ground it."""
```

No spec object and no caller-tunable thresholds: they live as module constants in
this one file. A threshold a caller can pass is a threshold a subagent can pass, and
§7's no-waiver rule would be worth nothing if the sensor's own bar were an argument.

Frames come from `assembly.frames_rgb` — one decode per episode, the batched grab
the 2026-08-02 slice built. The grey-world arithmetic reuses `color.white_balance`'s
notion of a cast rather than inventing a second one.

**The thresholds are first cuts and are declared as such**, in one place, like
`moodpreset.PRESETS` and intake's `CLUSTER_COS`. No footage has been graded against
them. They exist to give the agent numbers instead of impressions, and the numbers
are advisory in both directions: nothing in this slice fails an episode on a
sensor reading alone.

## 6. The evidence packet — `scripts/episode_qc.py pack`

One directory per episode, holding exactly what one subagent needs and nothing
about any other episode:

- **`strip.jpg`** — N frames sampled across the **delivered** clip, tiled by
  `contact_sheet.build_strip`, which already does this over any source. The judge
  sees what shipped, at delivery geometry, in timeline order.
- **the storyboard** — `process_episode` already produces one per episode, with the
  composition grid and the hero marker drawn on it. The packet names its path; it
  is the evidence the `hero` axis stands on.
- **`evidence.json`** — the episode's declared intent (composition / grid / hero
  pin / target_dur, straight off the manifest), the mechanical `report.json` checks,
  the §5 sensor's numbers and flags, the tracker provenance (`degraded`,
  `stitched`), and the `path.meta` geometry (`freedom`, `pan`, `stabilized`).

The intent is in the packet deliberately: composition is judged **against what this
episode declared**, never against a global rule. A `break` episode that ignores the
thirds is correct; the same frame under `lead` is not.

The per-episode scratch dir is **derived, not passed**: `process_episode` writes
`route.json` / `path.json` / `path.meta.json` / `report.json` / the storyboard into
one directory per episode, and `ReelEpisode.path` names a file inside it, so
`Path(ep.path).parent` is that directory for every episode including a pan (whose
`route` is None but whose sidecars are written all the same). A `ReelEpisode` with
empty `path`/`meta` — legal in the contract, and what a hand-authored reel manifest
may carry — has no derivable scratch, so `pack` refuses it by name rather than
guessing a layout.

## 7. The gate — phase 2's four refusals

`--from-episodes` refuses before a single ffmpeg call, returning the existing
`stop_and_report` shape:

| `reason` | Fires when |
|----------|-----------|
| `episode-qc-missing` | no `EPISODE_QC.json` beside `EPISODES.json` |
| `episode-qc-incomplete` | some episode index carries no verdict |
| `episode-qc-stale` | a verdict's `clip_digest` ≠ the digest of that clip now |
| `episode-qc-blocking` | some verdict carries a `blocking` finding |

**The agent never writes `clip_digest`.** `episode_qc build` computes it with
`provenance.digest_file` from the clip it finds on disk, and overwrites whatever
the raw findings claimed — the same producer/consumer split that makes
`check_reel`'s `master_digest` binding meaningful. That is what turns "this
episode was judged" into "**this render** was judged", and it is why re-rendering
an episode after its verdict is caught rather than assumed away.

**There is no waiver.** The variety gate has one because that rule is the machine's
own inference; the editorial-constraints gate has none because the rule is the
user's own sentence. This gate has none for the third reason: #8. A waiver field
is a thing a subagent can fill, and the whole point of the governance slice was
that quality control must not be disableable from inside the run. A false positive
is answered by a fresh judgment or by the human visibly editing the artifact — not
by a field the pipeline offers for the purpose.

## 8. The hole this shape carries — reprocess after the verdict

`build_reel`'s loop-2 re-renders culprit episodes *after* the gate has run
([build_reel.py:94-125](../../scripts/build_reel.py)). It compounds a colour
correction; and for a **stabilized** episode it re-tracks, so the crop path — the
composition — can move too. Both are exactly what axes `colour`, `composition`,
and `path` were just judged on. A verdict on that episode is stale the moment its
clip is rebuilt.

This is not papered over:

- `build_reel` reports the episodes it re-rendered (`reprocessed: [idx, …]`) on its
  delivered result.
- `deliver` records the QC state in the delivery's attestation: which clip digests
  were judged, and which episodes were re-rendered after judgment.
- The router re-runs QC on **exactly those** episodes after delivery and routes any
  blocking finding as a fix. In a normal run that is one or two episodes, not N.

So the guarantee is precise, and smaller than "every shipped frame was judged":
**no reel is assembled over an unjudged episode, and every episode re-rendered
after its verdict is named in the delivery's record.** The alternative that would
make the stronger claim (§2, forbid auto-reprocess) trades away the colour
convergence loop, which is a worse deal.

## 9. The router

`montage.V1_STAGES`' single `deliver` row becomes three:

| key | artifact | kind | runner |
|-----|----------|------|--------|
| `episodes` | `EPISODES.json` | required | `edl_to_reel --stop-after-episodes` |
| `episode-qc` | `EPISODE_QC.json` | required | `episode-qc` SKILL → `episode_qc pack` + N subagents + `episode_qc build` |
| `deliver` | `REEL_v*.*` | required | `edl_to_reel --from-episodes` |

`using-montage` dispatches **one fresh judge per episode, at most 3 concurrently** —
the same cap the per-episode fan-out uses, and for a related reason: a single judge
walking all episodes accumulates the previous ones in context and starts grading
episode 10 relative to episodes 1-9 instead of against the brief.

`deliver` keeps checkpoint `final`; the two new rows carry none. No new checkpoint
is introduced — the design's three (§4.1) stay three. A clean QC does not interrupt
the run; a blocking finding stops it at `deliver` with a routed finding, which is
the same shape every other stage stop already has. The findings themselves surface beside the reel at CP3, with the
reel-review, where the human is already looking.

`skills/process-episode/SKILL.md` is corrected in the same slice: its editorial
gate is real only on a hand-driven single episode, and the text must say so
instead of describing a conveyor step that does not happen.

## 10. The record

`Attestation` gains one field, `episode_qc: dict`, defaulted — old sidecars stay
readable, `PROV_V` does not move:

```json
"episode_qc": {"state": "judged", "judged": {"0": "9f2c…", "1": "44ab…"},
               "reprocessed_after": [1]}
```

`state` is `"judged"` on the two-phase path and **`"absent"` on the single-command
path**. That is the honest half: `edl_to_reel` with neither flag is still the SP1
front door for a hand-authored EDL, and it ships a reel no judge saw. The
attestation makes such a reel *distinguishable* — `montage verify` can say it — but
it does not forbid it. No silent bypass; bypass exists.

A third door bypasses the gate even more directly than the single-command one:
`EPISODES.json` **is** a `ReelManifest`, so `scripts/build_reel.py`'s own CLI —
`build_reel <run>/out/EPISODES.json --out-dir <run>/out --work-dir w` — loads it and
delivers straight through, with no gate at all, whatever flag `edl_to_reel` was
given. A manifest reaching `build_reel` this way carries no `episode_qc` block at
all (phase 1 writes none), so the merge stamps it `state: "absent"` too — the same
honest word the single-command path uses, not a silent `{"reprocessed_after": []}`
that names neither state.

## 11. What proves it

- **Real-ffmpeg end to end.** A two-episode EDL through phase 1 → `EPISODES.json`
  round-trips into an identical `ReelManifest`; a clean `EPISODE_QC.json` lets
  phase 2 deliver; a blocking finding stops it with `episode-qc-blocking` and
  **nothing is written**; deleting the artifact stops it with `episode-qc-missing`.
- **The staleness proof.** Judge, then rewrite one episode clip's bytes, then run
  phase 2 → `episode-qc-stale`. This is the one that proves the digest binding is
  load-bearing rather than decorative.
- **The sensor.** Synthetic frames with known clipping / cast / saturation, plus one
  real graded clip, against `measure`; `evaluate`'s flags mutation-checked.
- **The contract.** Round-trip, every refusal, `verdict` recomputed on load,
  `gate`'s four problem classes.

## 12. Honest limits

- **The stage gates the artifact's presence and its binding, never proof that
  anyone looked.** Same limit the contact-sheet stage records in its own §9. A
  judge can return an empty findings list without opening the strip, and the file
  it writes is indistinguishable from a diligent one.
- **The judge is an agent, and an agent with a shell can re-run it until it comes
  back green.** The artifact records `reviewer`; that is a record, not a
  prohibition.
- **A reprocessed episode ships judged one render out of date** (§8).
- **The single-command `edl_to_reel` ships with no QC at all** (§10) — and neither
  does `build_reel`'s own CLI, run directly against the same `EPISODES.json` shape
  phase 2 gates. Both name themselves honestly on the record (`episode_qc.state`),
  neither is prevented.
- **The sensor's thresholds are uncalibrated first cuts** (§5). They have never
  been run against real graded footage.
- **QC is per-episode and blind to neighbours.** "Does this cut work next to the
  one before it" stays reel-review's question; nothing here judges adjacency,
  rhythm, or repetition.
- **Under a pan there is no marker and no route**, so the `hero` axis has nothing
  to stand on. The packet says so, and the axis is reported not-judgeable — never
  passed.
- **N judges per run is a real cost.** A 20-episode reel dispatches 20 subagents.
  Sampling was rejected (an unjudged episode is exactly what the run produced), so
  the cost is the price of the gate, not an oversight.

## 13. Deferred

- **Horizon-level detection.** The one asked composition rule with a plausible
  mechanical sensor (`check_episode` reports `horizon: not-implemented` today).
  cv2 is already a dependency, so this is a self-contained follow-up — but it is a
  new measurement with its own thresholds, and folding it in here would put an
  uncalibrated sensor inside a gate on its first day.
- **Auto-routing a blocking finding back into a re-render.** The findings carry a
  `route`; acting on one automatically is the front-half EDL fixer, still unbuilt
  (the same dependency `variety` auto-fix waits on).
- **Re-judging inside the retry loop** — the shape that would close §8 fully:
  `build_reel` pausing after each reprocess round for a fresh verdict. It needs the
  loop to become agent-drivable, which is the §2-rejected surgery in a smaller
  costume.
