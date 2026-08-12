# Housekeeping — the four orphaned deferrals, and a backlog that is a queue

**Date:** 2026-08-12 · **Status:** design approved

## 0. Why this slice exists

Asked "is the deferred work carried into future phases?", the honest answer
turned out to be: **recorded in four places, scheduled in none of them.** Every
design carries a `§Deferred`; `build-status.md` keeps a short *Deferred / open*;
`fixes-backlog.md` keeps real-run findings; `pipeline-map.md` keeps a phase
roadmap. None of them is a queue, so an item leaves a design's deferred list only
when a human happens to re-read that design.

The mechanism demonstrably works sometimes: colour-as-a-stage deferred the
match-grade conductor and it landed 2026-07-30. It demonstrably fails too: the
*same* deferred list named `smooth_window_s`, and the speed-ramp slice
rediscovered it three weeks later as an accidental finding, not as a queue item.

A sweep of all 28 `§Deferred`/`Non-goals` sections against the code found four
items that fell out entirely — and three of the four are not "unbuilt features",
they are **live defects shipping today**. That is what this slice fixes, plus the
missing queue and the rule that keeps it filled.

## 1. The four orphans

### 1.1 `platform` never reaches the reel — P0

`Spec.platform` is written by `reel_brief`, validated, and rendered into
`SPEC.md`. Nothing that builds a reel reads it. `edl_to_reel` has no `platform`
parameter at all, so `ReelManifest.platform` is always its `""` default.

Two live consumers silently take the generic table:

- `check_reel`'s safe-zone section, via `safezones.safe_zone_for(platform)`
- `titles.y_exprs(platform)`, which lays a bottom title out against that same
  table (titles-animations, 2026-07-29, deliberately coupled the two)

So a reel whose brief says `platform: tiktok` is checked and typeset as if no
platform were known. `deliver` and `reel_review` each accept `--platform` on
their own CLI, which means the value exists in the system and a human can retype
it — the conveyor just never carries it.

Recorded as deferred in exactly one line of CLAUDE.md's colour-stage row
("`edl_to_reel` `platform`"), and nowhere else.

**Fix.** A new top-level `EDL.platform: str = ""`. `edit_plan build --spec` (the
flag already exists — the variety gate uses it) copies `Spec.platform` into it.
`edl_to_reel` passes `edl.platform` into the `ReelManifest`. Default `""` keeps
every existing EDL byte-identical.

The EDL is the right home rather than a CLI flag: it is the attested artifact, so
the platform a reel was checked against is recorded with the cut instead of
living in a shell history.

### 1.2 `EDLEpisode.smooth_window_s` cannot be authored — P1

`ReframeSpec.smooth_window_s` landed with colour-as-a-stage; the EDL row that
would set it did not. Deferred by colour-stage §11, named again by speed-ramp §9
as "a real gap", absent from `edl.py` and `manifest.py` today.

**Fix.** `EDLEpisode.smooth_window_s: float | None = None` → `to_manifest_dict`
→ `Manifest.smooth_window_s` → the `params` seed in `process_episode`.

**The coupled decision the plan must not skip.** `smooth_window_s` is not a plain
pass-through: it is a **retry-ladder knob**. `orchestration.adjust_reframe_params`
widens it on `jitter` and halves it on a lag, and the lag branch floors at
`DEFAULT_PARAMS["smooth_window_s"]` (0.25). An authored 0.6 would therefore be
walked back to 0.25 by the first lag retry — the author's instruction discarded
silently, which is precisely the failure mode this repo refuses elsewhere.

So `adjust_reframe_params` gains `floor: float | None = None`; `None` keeps
today's exact behaviour, and `process_episode` passes the authored seed when the
episode sets one. The ladder may still raise the window and may still bring it
back down — but never below what the author asked for.

### 1.3 `draft.py` renders an 8×16-pixel video — P0

```python
dims = cfg.canvas          # (9, 16) — an ASPECT, not pixels
...
vf = segment_filter(dims, fps, fontfile, str(tf))
```

`PURPOSE_CANVAS` maps every purpose to an aspect tuple (`reel → (9, 16)`), and
`segment_filter` spends it as pixels: `scale=9:16,pad=9:16`. Measured, real
bytes: **8×16** (`force_divisible_by=2` rounds the 9 down). The QA-preview draft
is a postage stamp.

It survived because the unit test hand-passes `(1080, 1920)` — it exercises the
string builder with a value the caller never supplies. The stage is optional and
rarely run, so nobody looked at the output.

Named in speed-ramp §9 as a correct fix present on the parked branch and not
ported. No owner since.

**Fix.** Resolve delivery pixels the way the rest of the engine does —
`Delivery.from_spec(cfg.delivery).dims(...)` against the canvas aspect — and add
the test that would have caught it: run `build_draft` and `ffprobe` the real
output dimensions. A test that asserts on a hand-supplied argument cannot fail on
a caller that supplies the wrong one.

### 1.4 `Spec.reel_count` is accepted and ignored — P1

Validated (`>= 1`), rendered into `SPEC.md` ("3 reels"), consumed by nothing.
reel-brief §7 deferred multi-reel fan-out; reel-review §7 deferred multi-reel
batch. A brief asking for three reels produces one, with no word said.

**Fix.** Refuse `reel_count > 1` at `Spec.__post_init__` with the remedy: run the
conveyor once per reel. The recorded intent stays expressible in the contract
(the field survives for the day fan-out is built) and stops being a silent lie
today. Deleting the field was the alternative and is rejected: two designs
explicitly park multi-reel as intended future work, and a refusal keeps that
intent visible while a deletion erases it.

## 2. Three stale pointers (documentation only)

- **"Secondary-aspect re-reframe on deliver — Phase F"** (reel-back-half §9).
  There is no Phase F. The only "slice F" in this repo is colour-as-a-stage,
  unrelated. The deferral points at a phase that was never created; it becomes a
  backlog row instead.
- **"Sharpness/blur metric — deferred (would add cv2)"** (footage-intake §8).
  `lib/flow.py` imports cv2 today (tracking-ladder, 2026-07-21). The stated
  blocker is gone; the item may still be a *no*, but not for that reason.
- **§6.1a layer 3, descriptor continuity re-match.** `build-status.md` still
  reads "unblocked… the natural follow-on", written before track-stitch landed
  2026-07-28 against the same failure — a mid-episode hero ID switch — by a
  different mechanism (geometric overlap-vs-gap evidence, not descriptor
  continuity). Whether stitch subsumes layer 3 or leaves a real remainder has
  never been re-assessed. The entry is rewritten to say exactly that, rather than
  to describe a world where track-stitch did not happen.

## 3. `docs/backlog.md` — the queue

One file, the **only** place that holds priority and status. Every open item is a
row:

| field | meaning |
|-------|---------|
| status | `✅ done` · `◐ partial` · `○ open` · `⊘ won't do` (with the reason) |
| priority | `P0` live defect · `P1` next slice · `P2` soon · `P3` someday · `P4` on request only |
| size | a rough slice count, so a reader can tell a two-task fix from a two-week one |
| source | the design `§`, the `fixes-backlog` number, or the playbook priority it came from |

The other documents stop owning priority and keep what they are good at:

- `fixes-backlog.md` — the detail store for real-run findings. Rows link into it;
  it keeps its rich per-item write-ups.
- `build-status.md` — the changelog and the next action. Its *Deferred / open*
  section collapses to a pointer.
- `pipeline-map.md` — per-stage status and the phase view; its roadmap links to
  the queue.
- each design's `§Deferred` — the reasoning, which the one-line row cannot carry.

Nothing is deleted. What changes is that exactly one file answers "what is left
and in what order".

## 4. The rule that makes it a planner

A queue nobody appends to is the archive again in three weeks. So:

> **A slice is not finished until every item in its design's `§Deferred` has a
> row in `docs/backlog.md`.**

It lands in two places that are actually read during a slice: the
slice-completion checklist in `development-workflow.md`, and the docs-sync task
that every plan already ends with.

This is a convention, not a gate — see §6.

## 5. Scope

**In:** the four fixes (§1), the three doc corrections (§2), the queue (§3), the
rule (§4).

**Out:** building anything the queue lists. Multi-reel fan-out, secondary-aspect
re-reframe, the sharpness metric and layer 3 all get rows, not code.

## 6. Honest limits

- **The rule is unenforced.** No test asserts that a design's `§Deferred` has
  matching rows; a lint that parsed prose deferrals and matched them to rows
  would be guessing at both ends. What this slice buys is a queue that exists and
  a checklist step that names it — not a mechanism that cannot be forgotten. The
  next audit will still be a human reading 28 sections; it will just have
  somewhere to write the answer down.
- **Priorities are one person's judgement** on one day, and P2/P3 in particular
  will not survive contact with the next real run. They are a starting order, not
  a measurement.
- **The audit that produced the rows is a snapshot.** It swept `docs/specs/*.md`
  for deferral-shaped headings; a deferral phrased mid-paragraph in some other
  section was not found. Four orphans is a lower bound.
- **`draft.py` gets a real-output test, the other three do not need one** —
  `platform` and `smooth_window_s` are contract plumbing whose absence a unit test
  catches, and `reel_count`'s fix is a refusal. Only the draft failed *because* its
  test asserted on the wrong thing, so only the draft's proof has to reach pixels.
- **Fixing the platform pipe can change a verdict.** A reel whose brief names a
  platform will now be judged against that platform's safe zone instead of the
  generic one, and a bottom title moves accordingly. That is the point, and it is
  also a behaviour change for anyone mid-run: an EDL authored before this slice
  carries no `platform` and keeps the old verdict, but re-running `edit_plan
  build --spec` will adopt it.
