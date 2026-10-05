# deliver — router stage 15

**deliver (edl_to_reel, phase 2).**

No `--out-dir` here — phase 2 takes none and refuses one if given: it
derives the delivery dir from `EPISODES.json`'s OWN path — the episodes
directory's SIBLING `deliveries/` (`<run>/reels/<reel>/deliveries/`), never
the episodes directory itself, so clearing the render scratch can never take
a delivered reel with it (design 2026-08-25 §0) — so do not re-add the flag
by analogy with phase 1.
Gates on `<run>/reels/<reel>/episodes/EPISODE_QC.json` beside `EPISODES.json` (missing /
incomplete / stale / blocking all refuse before a single ffmpeg call —
episode-qc having just run should make this a formality, not a surprise),
then runs assemble -> check_reel -> deliver. When `TITLES.json` is
passed, `deliver` burns its drawtext chain into the ONE encode it already
runs — no second pass; `deliver` also writes a `REEL_v{n}.attest.json`
sidecar beside the encode (design 2026-08-04). The reel's **look** (a
plateau vignette and/or a bookend fade — `EDL.look`, authored in
`selection.json` at step 6 or defaulted from the mood preset) rides this
SAME one encode, exactly like titles. Because `check_reel` runs on the
assembled master *before* `deliver` applies either, the look is invisible
in `draft.mp4` and in every check that ran before this point — Checkpoint
3, right here, is the first place anyone actually sees it (design
2026-08-13 §11.1).

**Authored bars (`GATES.json`) are shown here, not decided here.** Phase 2 judges
the reel by the set phase 1b froze into `EPISODES.json` and never re-reads
`GATES.json`: that set is the record of which bars judged these clips, and
re-reading it would let a bar move between the judging and the attestation that
binds it. Every bar an author moved is written into `REEL_v{n}.attest.json`'s
`gates` — field, value, default, scope, whether the bar can block, and the written
reason — and `montage verify` shows them. Name each one beside the reel at
Checkpoint 3: a moved blocking bar is a waiver, and this is where a human reads it.
The sidecar's `overrides` is a different list (a diff of the reel spec, no reason,
computed once in phase 1) and reads `[]` on a sanctioned run, so an empty
`overrides` is not evidence that no bar moved — read `gates`.

**`episode-qc-reprocessed` is a stop, not a warning.** Phase 2 refuses to deliver when `build_reel`'s retry loop
re-rendered an episode AFTER episode-qc judged it (design 2026-08-18 §2):
the reprocess overwrites the very `ep{i}.mp4` the verdict was stamped
against, so that verdict is about bytes that are gone. The picture passed
every check — the report comes back with the stop — and no version number
was spent. The remedy, in order:

1. `"$VG" scripts.episode_qc pack --episodes <run>/reels/<reel>/episodes/EPISODES.json
   --out-dir <run>/reels/<reel>/episodes/qc` — safe to re-run: it rewrites `strip.jpg` and
   `evidence.json` and never touches a judge's `findings.json`.
2. Dispatch **one fresh judge for the named indices only**. The other
   episodes' verdicts are about bytes that did not change; re-judging them
   spends context for nothing.
3. `"$VG" scripts.episode_qc build …` — unchanged; it re-digests every clip
   from disk, so the untouched verdicts stay valid and the re-judged one
   binds the new bytes.
4. Re-run this step. The corrected clips are already on disk where
   `EPISODES.json` points, so `check_reel` finds the picture fixed, nothing
   reprocesses, and the reel delivers with an empty `reprocessed` list.

**Do NOT re-run phase 1 to clear this stop.** The reason this was first
written for — `build_reel`'s compounded per-channel colour factor living
only in the clip bytes on disk (design 2026-08-18 §4.1) — is gone along
with the colour retry loop itself (design 2026-08-29,
colour-convergence-retire): there is no unpersisted correction left for a
fresh phase 1 to discard. The instruction still holds, on a plainer
ground: a fresh phase 1 (`--from-geometry`, or `--stop-after-episodes` on a
hand-driven run) re-renders **every** episode, not only the one this stop
names, so it pays the full
N-episode render cost again and invalidates every OTHER episode's
still-good QC verdict along with the stale one — exactly the waste the
remedy above (steps 1-4, re-judge the named indices only) exists to avoid.
Use that remedy; reach for phase 1 only when you are already re-cutting
the EDL for other reasons.

A delivered reel's `reprocessed` list is therefore always empty on this
path; if one ever comes back non-empty, something bypassed the refusal —
name it at Checkpoint 3 rather than passing over it.

**`grade_faithful` is also a stop here, and its remedy is a re-render, not
an EDL edit.** In the same phase, `check_reel`'s blocking `grade_faithful`
check (design 2026-08-31 §2) can name one episode whose delivered pixels
disagree with what its OWN declared colour chain predicts by more than
`grade_residual_max` luma units. Its finding's `escalate_to` reads
`process-episode`, not `match-grade` or `edit-plan`: the declaration is
fine, the render did not get it, so the fix is re-rendering that episode —
never touching its colour block, which would just be faithfully re-applied
and fail the same way again. `edl_to_reel` has no flag that re-renders a
single episode: `--from-geometry` (step 13) is the only render entry
point, and it always renders every episode over the current
`GEOMETRY.json`, which invalidates every episode's `EPISODE_QC.json`
verdict, not only the named one's. Pay that cost — there is no cheaper
mechanical path today (backlog) — rather than hand-editing `EPISODES.json`
to splice in one clip, which is a generated artifact like any other:
re-run `edl_to_reel --from-geometry` (step 13, the whole reel), then
**episode-qc** (step 14, every episode — every digest just changed), then
this step again.
