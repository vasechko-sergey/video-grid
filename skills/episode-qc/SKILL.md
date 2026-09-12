---
name: episode-qc
description: "Conveyor stage — the per-episode quality gate between rendering and delivery: pack an evidence directory per episode, dispatch one judge subagent each, and validate their findings into EPISODE_QC.json. Required; no waiver. Conveyor position: after episodes, before deliver. Tool index: references/tools.md."
---

# episode-qc (per-episode QC gate)

## Overview

The **per-episode quality gate**. `check_episode` already judged each episode
*mechanically* (six checks, plus two more it reports `not-implemented`);
episode-qc judges it the other way — **against pixels**, by a fresh judge
that never rendered the clip. It sits in the seam `edl_to_reel` splits itself
around: every episode already exists as delivered-geometry pixels
(`<run>/reels/<reel>/episodes/ep{i}.mp4`), and the reel does not exist yet. **A reel is never
assembled over an episode that failed this gate.**

**Core principle:** fresh eyes, one episode at a time, no waiver. Each judge
sees exactly one episode's own evidence — never another episode's packet,
never the EDL as a whole — and is scored against what THAT episode declared it
would be (`intent.composition`), never a global rule. Nowhere in this stage is
there a field for lowering the bar: a blocking finding is answered by fixing
the episode, never by re-judging until it passes (design §7).

## When to Use

Between the render phase that writes `<run>/reels/<reel>/episodes/EPISODES.json` —
`edl_to_reel --from-geometry` on the conveyor since 2026-08-30, or
`--stop-after-episodes` when a run is driven by hand from a plain EDL — and
`edl_to_reel --from-episodes` (assembles and delivers). `using-montage`
invokes it there on every conveyor run — it is **required**, but it is not one
of the three §4.1 checkpoints: a clean verdict passes through with no approval
asked, and only a blocking finding stops the run. Re-run it (from `pack`,
step 1) after any fix that changes an episode's rendered bytes — a reprocess,
a re-cut, a re-grade — because a verdict is bound to the clip's digest at
judgment time and goes stale the moment the clip changes (`episode-qc-stale`).

Do NOT use this to judge the assembled reel (adjacency, rhythm, whether cuts
read together) — that is **reel-review**, after delivery. Do NOT use it in
place of `check_episode`'s mechanical gates — those already ran, inside
`process_episode`, before this stage ever sees the clip.

## Inputs

- **`<run>/reels/<reel>/episodes/EPISODES.json`** (required) — a serialized `ReelManifest`,
  written by `edl_to_reel --from-geometry` (or `--stop-after-episodes`, driven by
  hand). Its schema IS `ReelManifest`;
  there is no separate contract. Each episode's `path` field names a file
  inside that episode's own scratch dir (`<run>/reels/<reel>/build/ep{i}/`), which is where
  `pack` finds `report.json` / `route.meta.json` / `path.meta.json` /
  `storyboard.jpg` — a manifest with no `path` sidecar (legal in the contract;
  what a hand-built reel manifest may carry) is refused by name, not guessed
  at.
- Nothing else. No `FOOTAGE.json`, no `SPEC.json` — each episode's own
  manifest already carries its declared intent (`composition`/`grid`/`hero`/
  `target_dur`/`layout`/`pan`/`stabilize`/`canvas`), and `pack` puts it
  straight into that episode's `evidence.json`.

## The Process

Announce on entry: **"Using episode-qc to judge every episode before the reel
is assembled."**

**Launcher.** Run every pipeline step through the repo's launcher `bin/vg`, never a
bare venv `python` binary. Resolve it once: `setup.sh` records the runtime's location
at `${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root`, so set
`VG="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")/bin/vg"` and run every
step as `"$VG" scripts.X`, passing **absolute** paths for every footage / run / output
directory. If that file is missing, the user has not run `bash setup.sh` — stop and
say so rather than guessing a path.

1. **Pack the evidence.**

       "$VG" scripts.episode_qc pack --episodes <run>/reels/<reel>/episodes/EPISODES.json --out-dir <run>/reels/<reel>/episodes/qc

   Writes `<run>/reels/<reel>/episodes/qc/ep{i}/` for every episode: `strip.jpg` (a frame strip
   sampled across the DELIVERED clip, in timeline order) and `evidence.json`
   (the episode's declared intent, the mechanical `report.json`, the tracker
   provenance, the `path.meta` geometry, and the naturalness sensor's
   stats/flags plus its source-relative delta).

   **Since 2026-09-09, `evidence.json` also records the digest of the clip it
   just decoded** (`clip_digest`), and `build` (step 4) refuses a packet whose
   digest no longer matches the clip on disk — "packed from a different
   render", remedy named inline. **Pack AGAIN, after any re-render, before
   dispatching judges** — not only before `build`: a judge reading a stale
   `strip.jpg`/`storyboard.jpg` off an old render forms a verdict about
   pixels that no longer exist, and `build`'s refusal only catches this once
   you get to step 4, after every judge has already spent a turn on the
   wrong pixels. This is a **gate**, not merely a staler report: a packet
   with no recorded digest at all (one from before this binding existed)
   is refused the same way, by name, not read as if it were still current.

   `evidence.json` also records what each pixel artifact actually rendered at
   (`strip_px`, `storyboard_px`) — reported, never gated. A judge that needs a
   closer look pulls its own frames with `contact_sheet strip`; the template
   tells it how.

   This refuses in milliseconds, before any decode, if some episode has no
   scratch dir to read.

2. **Dispatch one fresh judge per episode — at most 3 concurrently.** For each
   episode `i`, fill `skills/episode-qc/episode-reviewer.md` with THAT
   episode's own `<run>/reels/<reel>/episodes/qc/ep{i}/evidence.json` — which now names its
   own artifacts: `strip`, `strip_px`, `storyboard`, `storyboard_px`. Fill
   `{STRIP_PATH}`/`{STRIP_PX}` and `{STORYBOARD_PATH}`/`{STORYBOARD_PX}` from
   those four keys, writing `none recorded` for either storyboard key that is
   null — the same substitution the CHECKS/TRACK/GEOMETRY placeholders already
   ask for, and what the template's no-storyboard branch keys on. Pass nothing
   else. A judge reads only its own episode:
   never another's packet, never the EDL as a whole, never a comparison
   across episodes (adjacency and rhythm are reel-review's question, not
   this one). Dispatch with the Task tool (`general-purpose`), batching up
   to 3 calls in a single turn so they run concurrently, then wait for that
   batch before dispatching the next. The cap matches the per-episode
   render's own thread pool (design §9) for a related but distinct reason:
   one judge walking every episode in sequence accumulates the earlier ones
   in context and starts grading episode 10 relative to episodes 1-9 instead
   of against its own declared intent.

3. **Each judge writes its own verdict.** `<run>/reels/<reel>/episodes/qc/ep{i}/findings.json`,
   shape `{"summary": str, "reviewer": str, "findings": [...]}`. Nothing else
   is expected there — in particular, never an `idx`, `clip`, or
   `clip_digest` (see Boundaries).

4. **Validate + stamp.**

       "$VG" scripts.episode_qc build --episodes <run>/reels/<reel>/episodes/EPISODES.json --packets <run>/reels/<reel>/episodes/qc --out-dir <run>/reels/<reel>/episodes

   Refuses (before writing anything) if any episode has no `findings.json`.
   Otherwise validates every finding and writes `EPISODE_QC.json` + `.md`
   into `<run>/reels/<reel>/episodes` — beside `EPISODES.json`, by convention, which is where
   phase 2 looks for it (no flag to forget).

5. **Report the verdict.**
   - **`approve`** — say so plainly, and name what that proves: the
     artifact's presence and its binding to these exact bytes — not that a
     judge truly opened every strip (see Boundaries). The router proceeds to
     `edl_to_reel --from-episodes`.
   - **`revise`** — surface EVERY blocking finding (episode, axis, evidence,
     suggestion, route) and **stop**. Do not call `--from-episodes`: it gates
     on the same artifact and will refuse with `episode-qc-blocking` anyway.
     The fix belongs to the finding's routed stage (`reprocess` /
     `edit-plan` / `match-grade`) — never to re-judging in place. Once the
     fix lands and the episode(s) are re-rendered, re-run this whole process
     from step 1: the verdict is bound to the clip's digest, and a changed
     clip makes the old verdict `episode-qc-stale` even where it once said
     `approve`.

## Boundaries

- **You may not lower this gate.** No waiver exists here by design (§7) —
  not an oversight, the point. A waiver is a field a subagent could fill, and
  the whole reason this stage exists is that quality control must not be
  disableable from inside the run. A blocking finding is answered by fixing
  the episode (re-run the routed stage), or by a fresh judgment after that
  fix — never by re-judging the same bytes until one comes back green.
- **You never write `clip_digest`.** `episode_qc build` stamps every
  verdict's digest from the file it finds on disk at build time, and ignores
  whatever a judge's `findings.json` claims. That is what turns "this episode
  was judged" into "**this render** was judged" — a verdict survives a
  re-render only if nobody rebuilds the clip; if someone does,
  `episode-qc-stale` catches it before delivery.
- **Two bindings, not one.** The verdict's digest (above) says WHICH render
  was judged; the packet's `clip_digest` (stamped by `pack`, from the file it
  just decoded — never handed in) says which render the JUDGE LOOKED AT.
  `build` refuses when they disagree — a packet made before a re-render lets
  a judge form an opinion about pixels that are no longer what ships, and a
  verdict claiming to bind pixels nobody actually saw is worse than no
  binding at all. The remedy is always the same: `pack` again, then
  re-dispatch the judge for that episode — never argue the old packet is
  close enough.
- **An empty findings list is a claim, not proof.** The stage gates the
  artifact's presence and its digest binding — never proof that anyone
  looked (design §12). A judge can write an empty list without opening the
  strip, and the file is indistinguishable from a diligent one. Say this out
  loud when you report an `approve` — a green tick here does not carry the
  same weight as `check_episode`'s mechanical gates.
- **`reviewer` is a record, not a prohibition.** An agent with a shell can
  re-run the judge until it comes back green; naming who judged does not
  stop that, it only makes the run auditable.
- **A reprocessed episode no longer ships — but only on the judged path
  (design §8, closed 2026-08-18).** `build_reel`'s retry loop can still
  re-render a culprit episode after this gate has run, and its verdict is
  stale the moment that happens. Since 2026-08-18 the driver REFUSES to
  deliver in that state (`episode-qc-reprocessed`): the router re-judges
  exactly the named episodes and the second pass delivers. The attestation
  still records `reprocessed_after`, and `montage verify` reads a judged
  delivery with a non-empty one as **`stale`** — the backstop for any
  producer that bypasses the refusal. **What survives:** the refusal fires
  only when the manifest says `episode_qc.state == "judged"`. A reel with no
  verdict has nothing to invalidate, so the `absent` paths below still
  reprocess and still ship unjudged.
- **The single-command `edl_to_reel` path ships with no QC at all (design
  §10).** This skill only gates a run that stops at the episodes seam
  (`--from-geometry` or `--stop-after-episodes`, then `--from-episodes`). A
  hand-authored EDL run
  through `edl_to_reel` in one shot is still the SP1 front door, and it
  ships unjudged — its attestation says `episode_qc: {"state": "absent"}`
  rather than pretend otherwise.
- **`naturalness`'s flags are two, not five (design 2026-08-28 §4).** `flags`
  carries only `blown_highlights` and `crushed_blacks` — information the
  grade destroyed, true regardless of the source. `delta` carries
  `cast_shift` / `saturation_shift` / `contrast_drop` — what the grade
  **changed**, measured against the pre-grade segment; `source` is that
  segment's own reading. Both `source` and `delta` are `null` when the
  manifest has no `segment` or the file is gone. A strong cast, a flat frame
  or a saturated one in `stats` alone is a fact about the footage, not a
  defect — a `delta` flag is the one that can say the grade did something.
  **`contrast_drop` used to be an exception that could not be read that way**
  (design 2026-08-28 §9.7): the source was measured over the WHOLE segment
  frame while the graded side was a reframed crop of it, so the difference
  between two REGIONS read as a grade — one real fixture showed source
  contrast 0.0 against graded 123.6 with no grade at all. **Closed 2026-09-02
  (grade-sensor-references §5)**: `source` now reads through the episode's
  OWN crop geometry (the ungraded render this slice adds, via
  `process_episode.plan_ungraded` + `reframe.plan_frames_rgb`), so `delta` —
  `contrast_drop` included — is finally a same-geometry, grade-only
  comparison. Still advisory in both directions: ground a finding in them,
  never defer to them.
- **The colour axis's mechanical companion now stops the episode.**
  `report.json`'s `grade_damage` (in the mechanical checks; renamed from
  `color_fidelity`, design 2026-08-31) renders the episode's OWN declared
  grade against an identity twin of itself and fails the episode when the
  declared map DESTROYED information (an entropy-ratio floor), before this
  gate ever sees it — so an episode that reached you already passed the
  mechanical colour check, **unless `grade_damage` itself reports
  `{"status": "not-checked"}` with `passed: null`** (its render plans were
  unavailable — rare). The check's advisory `delta_e`/`dominant` describe how
  far the grade moved the tracked subject's colour, a DESCRIPTION of the
  grade's intent, not a threshold — a large `delta_e` is not itself a
  finding. A scenery pan has no tracked subject, so `delta_e` reads `null`
  with `delta_reason: "no source clip or no tracked subject"`, but the
  whole-frame entropy check itself still ran and still gated the episode; you
  are only the sole colour check for what that check structurally cannot see
  (chroma, and whether the natural-looking pixels are also the RIGHT ones).
  Judge the pixels regardless; a passing number is not a verdict on taste.
- **QC is per-episode and blind to neighbours.** Never comment on how one
  episode sits next to another, on pacing, or on repetition — that is
  reel-review's question, asked after delivery, over the assembled reel.
- **Under a `pan`, `hero` has nothing to stand on.** `intent.pan` set means a
  generated path following nobody — no tracked subject, no marker. Report
  the axis as not-judgeable (a real finding, `route: "none"`), never as a
  silent pass.
- **N judges per run is the accepted cost of this gate.** A 20-episode reel
  dispatches 20 subagents. Sampling was rejected — an unjudged episode is
  exactly what the run this stage answers for shipped.

## References

- Design: `docs/specs/2026-08-08-episode-qc-design.md` — §4 the five axes,
  §6 the packet, §7 the gate's four refusals, §9 the router, §12 the honest
  limits above.
- Contract: `scripts/lib/episode_qc.py` (`EpisodeFinding`/`EpisodeVerdict`/
  `ReelQC`/`gate`). Driver: `scripts/episode_qc.py` (`pack`/`build`). Sensor:
  `scripts/lib/naturalness.py`.
- The reel-level twin: `skills/reel-review/SKILL.md` +
  `skills/reel-review/reel-reviewer.md` — same fresh-judge, typed-findings
  shape, one whole reel instead of one episode, human-gated instead of
  gate-blocking.
