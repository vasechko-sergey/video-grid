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
  `target_dur`/`layout`/`pan`/`stabilize`/`still`/`freeze`/`canvas`), and `pack`
  puts it straight into that episode's `evidence.json`, beside `shutter` —
  whether `EPISODES.json`'s `shutters` accents this episode's cut.

## The Process

Announce on entry: **"Using episode-qc to judge every episode before the reel
is assembled."**

**Launcher and references.** Run every pipeline step through the plugin's launcher
`bin/vg`, never a bare `python`, and resolve every `references/…` read the same
way. Claude Code writes this plugin's own directory into the line below when it
loads the skill, so resolve it once:

    ROOT="${CLAUDE_PLUGIN_ROOT}"
    VG="$ROOT/bin/vg"

If `ROOT` comes out empty, or `"$VG"` does not exist — a harness that did not fill
the line in — `ROOT` is the directory two levels above this skill's base directory.
Then run every step as
`"$VG" scripts.X`, read every reference as `"$ROOT/references/…"`, and pass
**absolute** paths for every footage / run / output directory. Nothing here is
relative to your working directory — a skill runs from the user's footage
project. If `"$VG"` says there is no runtime, it has not been set up yet: run the
`setup` skill (`/video-grid:setup`), which asks before installing anything.

1. **Pack the evidence.**

       "$VG" scripts.episode_qc pack --episodes <run>/reels/<reel>/episodes/EPISODES.json --out-dir <run>/reels/<reel>/episodes/qc

   Writes `<run>/reels/<reel>/episodes/qc/ep{i}/` for every episode: `strip.jpg` (a frame strip
   sampled across the DELIVERED clip, in timeline order) and `evidence.json`
   (the episode's declared intent, the mechanical `report.json`, the tracker
   provenance, the `path.meta` geometry, and the naturalness sensor's
   stats/flags plus its source-relative delta), and `judge_prompt.md` — the
   judge's prompt, already filled from that episode's own `evidence.json`.

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
   episode `i`, dispatch the contents of
   `<run>/reels/<reel>/episodes/qc/ep{i}/judge_prompt.md` verbatim. `pack` filled
   it from that episode's own `evidence.json` — strip and storyboard paths and
   sizes, the checks, the tracker and path records (with `none recorded` for a
   sidecar that was never written and `unreadable: <why>` for one that was and
   could not be parsed), the colour sensor, the clip and where to write. Never
   fill or edit it by hand: a template edit that breaks a token is refused at
   pack time. Pass nothing else. A judge reads only its own episode:
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
  unavailable — rare). Beside the verdict the check carries an advisory
  DESCRIPTION of what the grade did: `delta_e` plus three signed components
  (`delta_l` / `delta_c` / `delta_h`), and no ranking of them: a ranking of
  three numbers that tie cannot be made, so none is reported and you read the
  three (design 2026-09-16 §0.5). **Read `region` before `delta_e`** (design
  2026-09-16 §2.3): a reading whose `region` is
  `"crop"` is NOT a statement about the subject, and `region_fallback` says
  why — `"too-small"` means the tracked box covered under 1% of the frame
  (`region_fraction` is that small number, the evidence, never the crop's
  1.0), `"no-route"` means a scenery pan has no tracked subject at all, and
  it reads over the whole delivered frame instead. `region_fraction` is
  always the fraction of the region ASKED for, so on `"no-route"` it is
  `0.0` — that is a subject that was never located, not a crop covering none
  of the frame.
  **On a `region: "subject"` reading the block also carries
  `crop_delta_c`/`crop_delta_h`** (design 2026-09-17 §2.2): the same signed
  dC\*/dH\* measured over the whole crop instead of the subject, kept only so
  the reel-level advisory `chroma_spread` check has one pixel set every episode
  always has. It is the crop's own reading of the SAME grade, not a second
  colour finding about this episode — when `region` is already `"crop"`,
  `delta_c`/`delta_h` already ARE that reading and these two keys are absent,
  never repeated under a second name.
  `background_delta_e` is
  the contamination check and rides along only when the subject supplied the
  reading: close to `delta_e` means the grade moved everything, far from it
  means the grade moved the subject and its surroundings differently — worth
  a look at the pixels. **Three shapes, and `background_fallback` is present
  in two of them** — its presence alone separates nothing, so read it with
  `background_delta_e`. (1) On a `region: "crop"` reading BOTH background
  keys are missing and neither is named: the reading already IS the whole
  frame, so there is nothing left to contrast it with. (2) The everyday
  case is `background_fallback: null` BESIDE a real `background_delta_e` —
  a `null` there means the background was read, not that it is absent.
  (3) When the subject DID supply the reading but the background could not be
  read (a subject covering over 99% of the frame leaves less than 1% of it
  for the background),
  `background_fallback` names why and `background_delta_e` is the one that is
  missing. All three are correct reports, none is malformed.
  A large `delta_e` is still not itself a
  finding: the entropy ratio carries the verdict and a real regrade is
  SUPPOSED to move colour. The whole-frame entropy check ran and gated the
  episode in every one of these cases; you are only the sole colour check for
  what that check structurally cannot see (chroma, and whether the
  natural-looking pixels are also the RIGHT ones). Judge the pixels
  regardless; a passing number is not a verdict on taste.
- **QC is per-episode and blind to neighbours.** Never comment on how one
  episode sits next to another, on pacing, or on repetition — that is
  reel-review's question, asked after delivery, over the assembled reel.
- **Under a `pan` or on a photo, `hero` has nothing to stand on.** `intent.pan`
  set means a generated path following nobody, and `intent.still` a photo whose
  move was rendered with nothing tracked — no tracked subject, no marker. Report
  the axis as not-judgeable (a real finding, `route: "none"`), never as a
  silent pass.
- **A freeze is one frame held on purpose.** `intent.freeze` set means the
  previous episode's last frame, held "like a photograph" (design 2026-10-21
  §3): every frame of its strip is the same frame, which is the intent and not a
  stalled render. Its `path` and motion are not judgeable — report `path` as
  not-judgeable (a minor finding, `route: "none"`), as for a pan or a photo. Nothing
  re-renders a freeze — its framing and grade are the previous episode's — so a
  composition finding on it routes `edit-plan` (drop the freeze, or move the
  previous window's end), a colour finding routes as on the previous episode, and
  neither routes `reprocess`. With
  `intent.shutter` set, the white flash and the shutter click are added at
  delivery and are NOT in the clip the judge sees, so their absence is not a
  finding either.
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
