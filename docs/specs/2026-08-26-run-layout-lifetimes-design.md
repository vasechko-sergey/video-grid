# A folder is a lifetime: the run directory learns what survives what

**Date:** 2026-08-26
**Status:** design
**Sources:** [backlog](../backlog.md) R9.1 (L, scheduled as 0.3.0) · R5.1 (S) ·
[retro](../retro/2026-08-25-first-real-run.md) R5, R9 ·
[run-dir separation](2026-08-25-run-dir-separation-design.md) (0.2.1, the parent slice)

---

## 0. The run kept the wrong half

0.2.1 gave the run its own folder. It did not give the folder any interior. Measured
on the 2026-06 run — 8 delivered episodes, one 33-second reel, **1119 MB** of
artifacts:

| bucket | bytes | share | what wiped it |
|---|---|---|---|
| scratch (`work/`, plus `deliver`'s mask and title sidecars) | 591M | **52.8 %** | nothing, ever |
| footage-derived (`FOOTAGE`, `sheets/`, `cast*`, `.intake_cache/`) | 194M | 17.4 % | nothing |
| **deliveries** (`REEL_v*.mp4`, attestations, `VERSIONS.md`) | 179M | **16.0 %** | `rm -rf out/`, **47 times** |
| per-episode renders + their QC verdicts | 97M | 8.7 % | `rm -rf out/` |
| `draft.mp4` | 39M | 3.5 % | nothing |
| agent-invented (`_review/`, `pacing_A/B`, `MUSIC_A/B/alt`) | 14M | 1.3 % | nothing |
| **editorial** (`EDL`, `SPEC`, `selection`, `MUSIC`, `PACING`, `MATCH`, `TITLES`, `REVIEW`) | **120 KB** | 0.0 % | `rm -rf out/` never reached it |

Two numbers carry this design.

**The run auto-deleted nothing and hand-deleted the one bucket that cannot be
rebuilt.** There is not a single `shutil.rmtree` anywhere in the production code, so
half a gigabyte of scratch accumulated untouched — 17 `work/ep*` directories and 17
extracted segments for an 8-episode reel, nine of each left by abandoned cuts and
indistinguishable by name. Meanwhile the workflow's own remedy for a bad render was
`rm -rf out/`, which it ran 47 times, and `out/` was where the deliveries lived. Of 14
delivering runs, **2** survived in `VERSIONS.md`, and because `deliver._next_version`
counts surviving `REEL_v*` files instead of reading the log, numbering restarted every
time: **three different reels shipped as `REEL_v1.mp4`**.

**A reel variant costs 120 KB.** The editorial layer is 0.0 % of the run; the footage
layer it reads is 194M. That ratio — 1600× — is the whole argument for putting the
variant boundary between them rather than at the top: two cuts of one shoot should
share the expensive half and duplicate the free half. The run did the opposite,
disambiguating variants with filename suffixes (`MUSIC_A.json`, `MUSIC_B.json`,
`MUSIC_alt.json`, `pacing_A/`, `pacing_B/`, `MATCH_nostalgic.md`) inside one flat
directory, where nothing records which is current and nothing ties a pacing fit to the
music it was fitted to.

---

## 1. The organizing rule

**A folder is a lifetime.** Not a stage, not a file type, not a producer — how long
the thing inside stays true.

Seven lifetimes exist in this conveyor, and every artifact has exactly one:

| lifetime | invalidated by | bucket |
|---|---|---|
| the project | nothing (canvas, delivery, standing rules) | run root |
| the raw clips | shooting more, or replacing footage | `footage/` |
| the sourced audio | nothing — a download cache, shared by every reel | `music/` |
| the editorial choices | re-cutting | `reels/<name>/` |
| one render generation | re-rendering | `reels/<name>/episodes/` |
| never — append-only | nothing; deliberately unreachable by any wipe | `reels/<name>/deliveries/` |
| the current render only | the next render, automatically | `reels/<name>/build/` |

The rule decides every placement below, including the four that are not obvious.

---

## 2. The layout

```
<footage_root>/                    ← the user's raw clips, untouched
  DJI_*.MP4  MVI_*.MP4
  montage/                         ← the run (0.2.1)
    project.json                   ← project level: canvas / delivery
    CONSTRAINTS.json               ← beside project.json — a code fact, not a choice
    footage/
      FOOTAGE.json  FOOTAGE.md
      SHEETS.md  sheets/
      cast.json  cast_candidates.json  cast_crops/
      intake_report.json  .intake_cache/
    music/
      cache/                       ← fetched tracks, shared by every reel
    reels/
      main/                        ← one editorial variant
        SPEC.json  SPEC.md
        selection.json
        EDL.json  EDL.md
        MUSIC.json
        PACING.json  PACING.md
        MATCH.md
        TITLES.json  TITLES.md
        REVIEW.json  REVIEW.md
        draft.mp4
        episodes/
          ep0.mp4 … ep7.mp4
          EPISODES.json
          EPISODE_QC.json  EPISODE_QC.md
          qc/ep0/ … ep7/
        deliveries/
          VERSIONS.md
          REEL_v1.mp4  REEL_v1.attest.json
          REEL_v2.mp4  REEL_v2.attest.json
        build/
          segments/  ep0/ … ep7/  reel/  audio/  labels/  burned/
          draft_master.mp4  look_mask.png  title_*.txt
```

The reel name defaults to `main`. A variant is `--reel <name>` — a directory, never a
filename suffix. This is what retires `MUSIC_A/B/alt`, `pacing_A/B` and
`MATCH_nostalgic.md`: a pacing fit and the music it was fitted to sit in the same
folder, so they cannot drift apart silently.

---

## 3. Four placements that are decisions, not translations

**`.intake_cache/` moves for free.** `intake_cache._dir` derives it as
`Path(out_dir) / ".intake_cache" / …`, so pointing intake's `out_dir` at
`montage/footage/` relocates 93M of cache with no code change and no cache-key change.

**`episodes/`, not `judged/`.** The clips exist before anyone judges them, so the
lifetime name would be wrong — but the bucket is right, because `episode_qc` stamps
each verdict's `clip_digest` from the clip on disk. Verdict and artifact are bound;
they must live and die together. Wiping the clips while keeping `EPISODE_QC.json`
leaves verdicts pointing at nothing, and the digest binding — the one binding that
held all week — would have nothing left to bind to.

**`draft.mp4` is editorial, not scratch.** The predicate for `build/` is sharp:
**nothing a human is meant to open lives there.** The draft is opened by a human, at
checkpoint CP2 — that is its entire purpose. Its scratch (`draft_master.mp4`,
`labels/`, `burned/`) is not, and goes to `build/`.

**`deliver` currently writes scratch into the delivery directory.** `_render_mask`
writes `look_mask.png` into `out_dir`, and `build_filterchain` writes a `title_i.txt`
sidecar per title into the same `out_dir`. With `deliveries/` append-only that is a
leak, so `deliver` takes a scratch path distinct from its output path. This is the one
placement that is a code change rather than a move.

---

## 4. What becomes code

| # | Where | What |
|---|---|---|
| 1 | `scripts/lib/runlayout.py` | `RunLayout` — one authority computing every path from `(footage_root, reel)`; 0.2.1's `refuse_output_in_footage` stays |
| 2 | `scripts/montage.py` | `Stage.artifact` becomes a run-relative path; `next_action` resolves through `RunLayout` and reports each stage's resolved path; the `out_dir` parameter retires |
| 3 | `scripts/deliver.py` | `_next_version` reads `VERSIONS.md`; a `scratch_dir` parameter for the mask and title sidecars |
| 4 | `scripts/edl_to_reel.py` | the guarded `build/` wipe at `_build_manifest` |
| 5 | 9 × `SKILL.md` | the buckets; `using-montage` defines the layout, plus the old-run discriminator |
| 6 | `CLAUDE.md`, `README.md`, `CHANGELOG.md`, `docs/backlog.md` | registry row, convention, 0.3.0 entry, R9.1/R5.1 → ✅ |

Every driver already takes explicit path arguments — measured in 0.2.1 §1 and
unchanged — so **no driver signature changes** except `deliver`'s new scratch path.
The layout was never in the code to begin with; it lived as 74 `<run>` strings across
nine skills, 16 of them naming `<run>/out`. That is the second, unchecked copy this
slice removes.

### 4.1 `_next_version` reads the log

```python
def _next_version(out_dir: str, container: str) -> int:
    """max(the log, the files) + 1.

    The log is the source: it survives a delivery being moved, renamed or archived,
    and it is what makes `REEL_v{n}` a monotone identity rather than a count of
    what happens to be in one directory today. The file glob stays as a FLOOR, for
    a log deleted by hand — the failure it cannot cover is both being gone, which
    §8 names rather than closes.
    """
```

Measured consequence of the glob-only version in use today: 14 delivering runs, 2
surviving log records, three distinct reels named `REEL_v1.mp4`.

---

## 5. The enforcement is the inspector, not a refusal

0.2.1's lesson was that a rule which has already failed as prose does not get
re-stated as prose — its gate is a hard refusal in three drivers. That shape does not
transfer here, and the reason is worth writing down: a refusal needs a predicate for
*wrong*, and `edit_plan --out-dir` is legitimately free-form. `edl_to_reel` with a
hand-authored EDL and a scratch directory of the caller's choosing is a documented
front door (SP1), not drift.

So the enforcement is inverted. `montage.next_action` resolves every stage's artifact
through `RunLayout`, which means **an artifact written outside the layout simply does
not count**: the router sees the stage as not done and runs it again, into the
canonical path. Self-correcting rather than refusing, and it needs no new discipline —
the router already calls `status` at every step, and the resolved path now comes back
in that same answer, at exactly the moment the agent is asking where to write.

Two mechanisms back it up, and both are physical rather than advisory:

- **`build/` is wiped at every render**, so anything stashed there does not survive to
  confuse the next one. The 17-vs-8 directory count cannot recur.
- **`deliveries/` is reachable by no wipe in the codebase**, so the version log
  accumulates whatever else is deleted.

---

## 6. The build wipe's predicate is structural

The wipe lives in `edl_to_reel._build_manifest` — the private chokepoint both phase-1
entries (`edl_to_reel()` and `process_episodes()`) already route through, and where
0.2.1's footage-root guard already sits.

**Phase 1 only, never between phases.** `EPISODES.json` carries absolute paths into
the scratch tree — `route`, `path` and `meta` under `build/ep{i}/`, the extracted
`segment` under `build/segments/` — and phase 2's retry loop reads the frozen route
from there. A wipe between the phases would break the reprocess path.

**Wiping loses nothing.** Phase 1 has no resume: every run re-renders every episode
from scratch, so no completed work is discarded.

**The predicate is `work_dir == out_dir.parent / "build"`**, both resolved. Not "the
directory is named `build`" — under that rule a hand-driven `--work-dir ~/build` is a
grenade. The structural form asks a different question: *do these two paths belong to
the same canonical reel?* Under the layout, `out_dir` is `reels/<name>/episodes` and
its sibling is `reels/<name>/build`, so the canonical run always matches and no other
arrangement can.

When it does not match, the wipe does not happen and one line says so. That keeps SP1's
hand-driven door open at the cost named in §8.

---

## 7. The old run does not migrate

Unchanged from 0.2.1 §5, and for the same measured reason: `out/EPISODES.json` alone
carries **57** absolute paths, and moving the tree would break the QC digest bindings
and the delivery attestation that exist to notice exactly that kind of change.

What this slice adds is the discriminator. A 0.2.x run has `montage/FOOTAGE.json` and
no `montage/footage/`; the router recognises that, says so, and asks — rather than
seeing an empty run and re-scanning 99 4K clips.

---

## 8. Honest limits

**The inspector enforces the layout only for an agent that asks it.** An agent that
composes its own paths and never calls `montage status` drifts exactly as before. The
invariant is *no silent drift* — the router's own answer is always canonical — not *no
drift*. The same shape as 0.2.1 §6 and the attested-run §11.

**The wipe covers the canonical path only.** A hand-driven run with scratch elsewhere
accumulates forever, exactly as today. Named, not closed — and deliberately, because
the alternative refuses SP1.

**Both version records can still be lost.** `_next_version` reads the log with the
file glob as a floor; delete both and numbering restarts at 1 with no way to know a v1
already shipped. `deliveries/` is append-only by convention — nothing in the codebase
writes to it destructively — not by permission bits.

**`episodes/` holds one generation.** A re-render replaces it wholesale; there is no
history of past episode renders and no way to diff two. Deliberate: that history is
what `deliveries/` is for, and keeping every generation is how 591M accumulated.

**A variant shares `footage/` and `music/`, which is the point and also the ceiling.**
Two reels cut from different footage sets need two run directories, not two reel
directories. `CONSTRAINTS.json` is likewise project-level — `edit_plan` finds it beside
`project.json` — so two variants cannot hold different standing rules. That follows
today's code rather than choosing anything, and if a per-reel constraint is ever
wanted it is a slice, not a flag.

**Nothing here makes a reel better.** It stops the run from losing the half worth
keeping.

---

## 9. Deferred

| what | why not now |
|---|---|
| migrating the 2026-06 run | §7 — a path rewrite, not a move; its own slice if ever wanted |
| per-reel `CONSTRAINTS.json` | §8 — follows `edit_plan`'s existing discovery; no demand yet |
| a `montage clean` command for `footage/` or `episodes/` | the automatic wipe covers the bucket that actually grew; a manual one for the rest is prose until something measures a need |
| digest-binding the other reports (R5.2) | its own backlog row — `MATCH.md`, `REVIEW.json` staleness is a binding problem, not a layout one |
