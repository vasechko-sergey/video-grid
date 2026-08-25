# Backlog — the queue

**This is the only document that holds priority.** Everything else records
*reasoning* (each design's `§Deferred`), *detail*
([fixes-backlog.md](fixes-backlog.md)), *history*
([build-status.md](build-status.md)) or *stage status*
([pipeline-map.md](pipeline-map.md)). When they disagree with this file about
what happens next, this file is right.

It exists because on 2026-08-12 an audit of all 28 design `§Deferred` sections
against the code found **four items that had left every list** — and three of
them were live defects shipping in every run. Deferrals were being *archived*,
never *scheduled*. See
[the housekeeping design](specs/2026-08-12-housekeeping-backlog-design.md).

> **The rule:** a slice is not finished until every item in its design's
> `§Deferred` has a row here. It is a convention, not a gate — nothing machine-
> checks it (design §6).

## Legend

| | |
|---|---|
| **Status** | `○` open · `◐` partial · `✅` done · `⊘` won't do |
| **Priority** | `P0` live defect · `P1` next · `P2` soon · `P3` someday · `P4` only on request |
| **Size** | `S` a task or two · `M` a slice · `L` several slices |

Priorities are one person's judgement on one day. P2 and below will not survive
contact with the next real run — they are a starting order, not a measurement.

**P0 is empty.** The four live defects the 2026-08-12 audit found are fixed (last
section). A P0 row means something ships wrong today, so an empty P0 is the
normal state and a populated one interrupts whatever is in P1.

**Three items span buckets** rather than sitting in one, and each says so where
it appears: **#9** (cinematic look) was split P1/P2/P3 — the **P1 look half
landed 2026-08-13** (cinematic-look: vignette + bookend fade, each with a
measured visibility proof) and its **P2 grade half landed 2026-08-17**
(mood-grade: `MoodPreset.tone_bias` displaces the conductor's common target);
**P3 (the image-treatment tail, now incl. grain) stays open, so #9 itself is
still not closed**. The
**episode-QC loop** is P2 for the re-judge and P3 for the auto-route; and
**reel length** is P2 for the diagnosis and P3 for the enforcement. Do not
close either of those two on its first row alone.

---

## P1 — next

| | Item | Size | Source |
|---|------|------|--------|
| ○ | **R2.6 · `build_reel`'s colour-convergence retry loop wrecked the grade twice, unnoticed.** 08-20: warm beach shots pushed +43 B−R into blue. 08-22: ep6 went R−B +12.7 → −21.1 — "the red board reads brick, skin reads grey". The mechanical gate passed both. The same re-render then invalidated the QC verdicts it had just earned, and the `episode-qc-stale`/`episode-qc-reprocessed` stop fired at least **three** times, each costing a full cycle. A corrector that can make the picture worse needs a before/after it must beat, not a threshold it must clear. | M | [retro](retro/2026-08-25-first-real-run.md) R2 |
| ○ | **R7.2 · `pacing` reported a perfect fit — `dev: 0.0` on all 8 slots — while the cut rhythm inverted the music's energy curve.** Reporting only grid deviation makes a wrong-but-aligned cut indistinguishable from a right one. | M | [retro](retro/2026-08-25-first-real-run.md) R7 |
| ○ | **R5.3 · A 10-minute Bash timeout killed `deliver` mid-write and left the delivery directory half-corrected**, with no marker saying so. Delivery must be atomic or must record that it was interrupted. | S | [retro](retro/2026-08-25-first-real-run.md) R5 |
| ○ | **R9.1 · The run directory has no notion of lifetime — scheduled as its own minor release (0.3.0).** Proposed: `montage/footage/` (survives every re-cut), `montage/reels/<name>/` holding the editorial files plus `deliveries/` (append-only, never auto-cleaned), `judged/` (digest-bound) and `build/` (wiped at the start of every render). Measured today: **17** `work/ep*` dirs and **17** segments for an **8**-episode reel, nine of each from abandoned cuts and indistinguishable by name; **two competing per-episode metadata sets** four days apart with the same filenames and different md5s, nothing marking which is authoritative; **1.09 GB** of artifacts for a 33-second reel with no cleanup anywhere. Variants get structure instead of suffixes, retiring `MUSIC_A/B/alt` and `pacing_A/B`. | L | [retro](retro/2026-08-25-first-real-run.md) R9 |
| ○ | **R2.0 · Bring the sources to one range before anything compares or grades them.** Measured 2026-08-25: the drone is `yuv420p` / `color_range=tv` (16–235), the Canon is `yuvj420p` / `color_range=pc` (0–255) — same bt709 primaries, transfer, space, resolution and fps, **different range**. So the conductor computes a common target from percentiles taken with two different rulers, and `tone_arg`'s `lutyuv` (`TV_LO=16, TV_SPAN=219`) treats the Canon's 0–255 material as 16–235, collapsing everything above code 235. `assembly` already normalises a foreign `pc` (colour-stage §8/§9) — `measure_profile` and `match_grade` read the source file directly and bypass it. R2.1 and R2.3 are downstream of this. | M | [retro](retro/2026-08-25-first-real-run.md) R2 |
| ○ | **R2.1 · Grade against named subjects, not the frame mean.** The operator's own three anchors: skin, the black wetsuit, the water. `color_across_cuts` compares whole-frame means, so on ep5 — a frame that is mostly dark water — the correction lifted Lena's face to **156 luma, above her own ungraded plate**. Five of the run's six days went here. | L | [retro](retro/2026-08-25-first-real-run.md) R2 |
| ○ | **R2.2 · `color_fidelity` cannot see the damage it exists to catch.** It scored a **28-code** shift as **0.8° of drift against a 25° threshold**, returned `null` on 2 of the 8 shipped episodes and 129.4° on another — false negative, absent, and false positive — with `overall: true` throughout. Re-derive it or delete it; a gate that is blind on 25% of episodes and still passes is worse than none. | M | [retro](retro/2026-08-25-first-real-run.md) R2 |
| ○ | **R2.3 · The `lutyuv` range bug.** With full-range input everything above code 235 collapses onto a constant. Downstream of R2.0 but worth its own fix and its own test. | S | [retro](retro/2026-08-25-first-real-run.md) R2 |
| ○ | **R2.5 · The naturalness sensor can only advise, and its thresholds were never calibrated.** `lib/naturalness.py` measures blown highlights, crushed blacks, colour cast and oversaturation — exactly the operator's complaint — and says so in its own header: *"Nothing here fails an episode … calibrate on the first real run that uses them."* On the shipped reel it flagged **`colour_cast` on 7 of 8 episodes** and `blown_highlights` on ep7. The first real run has happened and its frames are on disk: calibrate, then give it the right to stop. | M | [retro](retro/2026-08-25-first-real-run.md) R2 |
| ○ | **R1.1 · Split pace from look.** A mood word must not silently order a grade. `SPEC.mood` "light, summery, easy … relaxed but alive" resolves to `nostalgic`, whose `tone_bias` is `(+20, 0, −18)` — lifted blacks, faded — which is precisely the "washed out, shadows gone" the operator complained about. | M | [retro](retro/2026-08-25-first-real-run.md) R1 |
| ○ | **R1.2 · The length band needs a floor, a wider ceiling, and measured numbers.** `MoodPreset.asl` binds length, but every preset's band is a ceiling with no floor, and **all four ceil at ≤ 5.0 s** — a calm reel with six-second shots is not expressible. `nostalgic` is (2.0, 4.0), which is the pull toward two seconds the operator kept naming. The right numbers are unknown and genre-dependent; they must be measured, not typed. | M | [retro](retro/2026-08-25-first-real-run.md) R1 |
| ○ | **R1.3 · `variety` recorded an out-of-band `asl` and did nothing.** Realized 4.37 s against its own declared (2.0, 4.0). Either it gates or it stops declaring a band. | S | [retro](retro/2026-08-25-first-real-run.md) R1 |
| ○ | **R3.1 · A crop-accurate still after tracking, before any encode.** `probe grade` is the right tool — it calls `reframe.plan_render(spec, src, ep.route)`, the same function the real render uses — but its CLI needs `EPISODES.json`, which exists only after every episode has been encoded. `scripts.track` already produces `route.json` standalone. Missing: a stage taking source + route + colour block and emitting stills. This is the operator's "draft 2". | M | [retro](retro/2026-08-25-first-real-run.md) R3 |
| ○ | **R4.1 · Every CLI and every skill line states what the tool is FOR.** 56 Bash calls in the run grepped the product's own source to find out. A name is not a purpose. | M | [retro](retro/2026-08-25-first-real-run.md) R4 |
| ○ | **R4.2 · Skills must name the tool at the moment of need.** `scripts.probe` was invoked **0** times and `CONSTRAINTS` mentioned **0** times in 831 tool inputs, although the 0.2.0 plugin cache was stamped two hours before the run and shipped both, and `using-montage` names "no repeated episodes" as its own worked example. The agent did not skip them — it **rebuilt** them, as a 2.0 GB / 676-file private colour lab. | M | [retro](retro/2026-08-25-first-real-run.md) R4 |
| ○ | **R5.1 · Deliveries and their log leave the wipeable directory.** `VERSIONS.md` and the attestations live in `out/`, which the workflow `rm -rf`'d **47 times**; `_next_version` counts surviving `REEL_v*` files instead of reading the log, so numbering restarted and **three different reels shipped as `REEL_v1.mp4`**. 14 delivering runs, 2 surviving records. | S | [retro](retro/2026-08-25-first-real-run.md) R5 |
| ○ | **R5.2 · Extend digest binding to every report.** `episode_qc` stamps a `clip_digest` from disk and refuses a stale verdict — the one binding that held all week. Nothing else has one: `MATCH.md` claimed 8/8 authored tone pairs against an `EDL.json` written an hour later carrying 5; `REVIEW.json` was two days and two reel versions stale (reviewed 37.1 s, shipped 34.93 s). | M | [retro](retro/2026-08-25-first-real-run.md) R5 |
| ○ | **R7.1 · A stage that did nothing must say so and escalate.** `MUSIC.json` carried `bars: []`, so the whole outro-fit feature reported `"n/a"` and silently did nothing; `outro.brief_len 45.0` against `reel_dur 34.93` is 22% short and escalated nowhere; `vocal_spans` showed the reel both starting and ending inside vocals against the operator's belief. | M | [retro](retro/2026-08-25-first-real-run.md) R7 |
| ○ | **R10.1 · The QC judge is nearly blind.** The evidence strip is **200×406 px per frame** with no zoom helper; three judges reached for tools absent from their harness and one hit `magick not found`. Judging is a required stage with no waiver. | S | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ✅ | **Music ends mid-phrase** — **fixed 2026-08-14.** Investigated the same day against the 2026-08-03 run's own artifacts (findings below); demucs made a REQUIRED runtime component as the first step. The out-point fix itself landed hours later: the reel's length becomes `bar_line + fade` (`lib/outro.fit_outro`'s pure three-rung ladder — `gap` → `no-gap` (a longer fade) → `unchanged`), applied by `edit_plan` to the closing episode after pacing binds, because `mix` already fades over `[dur - fade, dur]` — so that length starts the fade exactly on the bar line with **no ffmpeg stage changed at all**. `MusicSpec` gained `bars` (from the **bass band**, not onset strength — see the measurements below) and `vocal_spans` (from the demucs stem at ~23ms resolution, not the 2 Hz energy curve that fooled the first pass of this very investigation — §8.1 below). **What this does NOT claim.** The gate proves the reel ends on a *detected* bar line with a *measured* vocal-free tail — not that the phrase sounds resolved, and not that the line is a phrase boundary rather than merely a bar. **No automated check anywhere hears the delivered reel** (§11.5); CP3 is the first place a human does. And the **`no-gap` rung ships a known-imperfect ending** by design (§11.6) — it is this slice's answer to material with no vocal-free space, not a claim the result sounds good. What remains open, already filed: meter beyond 4/4, real section detection, a check that hears the delivered audio, fitting a ramped closing episode instead of skipping it (all P3), plus two found by the final review — pacing's round trip is no longer a fixed point after a fit (§11.8) and `build_reel`'s length re-time can silently defeat the fit (§11.10), both P2. | M | [#2](fixes-backlog.md#2-music-is-cut-in-the-middle-of-a-phrase), pacing §10, [music-outro-fit design](specs/2026-08-14-music-outro-fit-design.md) |

**What the 2026-08-14 investigation measured** (scripts under the session scratchpad;
every number is from the delivered `out/REEL_v1.mp4` and its own track):

- **Root cause confirmed, and it is structural, not a bug.** `MUSIC.json` records
  tempo, a flat beat list and a 2 Hz energy curve — *no downbeats, no bars, no
  sections*. `mix.py` trims the music to the master's length. So no stage in the
  pipeline is *able* to end on a phrase; the out-point is whatever the picture's
  length happens to be. In the run: reel 34.051s, out-point at track 80.044s,
  **0.96s past a bar line**.
- **The fade is not the problem.** It fires correctly — 18.1 dB over the last
  ~800ms, final 200ms at −33 dBFS — but the song is at full energy there (6.1× the
  gap threshold), so 0.5s ducks the chop without resolving the phrase.
- **Bars ARE recoverable, but not by the obvious detector.** Onset strength per beat
  phase: 4.313 / 4.285 / 4.267 / 4.309 — no signal, all four within 1%. Low-band
  (<150 Hz kick) peak per beat: phase 3 at 79.31 vs phase 2 at 42.03, ratio **1.89**,
  and the phase-3 beat is the loudest of its bar in **14/18 bars** (78% against 25%
  by chance). Any section detector should use the bass band, not novelty.
- **The triage hypothesis in [fixes-backlog #2](fixes-backlog.md) was wrong.** It
  assumed `--auto-start` had already placed the in-point in a vocal pause. Run
  `best_offset` on that track and it returns **0.000** for every plausible duration
  (25/30/33/34/42/45); `MUSIC.json` records 46.0. The in-point was hand-set, and the
  auto path would have started the reel at second 0 of the song.
- **There is headroom.** The analysed window is 42s and only 34.04s was used —
  **7.96s of already-analysed music**, so moving the out-point to a bar line needs no
  `beats` re-run. Nearest bar up is +1.22s; but the reel is already **+4.04s** over
  `SPEC.length_s` (30.0), and the only candidate landing *under* the brief is a 4-bar
  step down to 28.73s. "End on a musical line" and "hit the brief's length" pull
  against each other, and the stage must **report** that tension rather than resolve
  it silently.
- **A vocal-free half-second after the boundary exists, and there is exactly one
  usable place for it.** This was measured twice; only the second measurement is
  right. With no demucs installed the mix-silence proxy found **2** vocal-free spans
  in 228s and none in the window, which is what made the fallback's deletion
  obviously correct — but it is not evidence about the music. Re-run with real
  demucs (installed 2026-08-14): **19** spans in the track, **5** overlapping the
  reel's 42s music window. A first pass on demucs' own 2 Hz envelope still said "one
  usable bar line", and that was an artifact — a 2 Hz envelope has **0.5s bins** and
  the rule asks for 0.5s, so it cannot resolve the answer. At the vocal stem's full
  11.6 ms resolution: **2 of the window's 18 bar lines** can end the music with
  ≥0.5s of silence after, and the useful one is **bar 15 at stem 35.26s — +1.22s
  from the reel's current end, with 1.50s of vocal-free after it**. Stable across
  threshold fractions 0.10–0.30 (0.05 drops it to 1). Any gap sensor built for this
  must measure at frame resolution, not on the 2 Hz curve `MusicSpec.energy` stores.
- **The 1.22s is available, and the in-point lever cannot pay it instead.** The
  closing clip has **11.53s** of unused source after its episode, so extending is
  cheap in footage terms (35.26s reel = +5.26s over the brief's 30.0s, against
  +4.04s today — the tension to report, not resolve). Moving `start_offset` instead
  looks free but is not: the shift needed is **2.235 beats**, and only a whole-beat
  shift keeps the existing cuts on the grid — 2 beats leaves the end 0.128s off the
  bar line, and a whole-*bar* shift maps the grid onto itself and changes nothing.
  So the P3 row "re-pick `MUSIC.start_offset` at the back-edge" is **measured
  insufficient on its own**: it can only work as part of re-fitting the whole spine
  (pacing's two-axis search), never as a back-edge tweak.
- **`--auto-start` now answers.** With real vocal gaps `best_offset` returns
  **147.772s** for every duration tried (30/34/42), against the proxy's 0.000.
- **Cost of the requirement:** htdemucs separation measured **62.1s and 46.2s** on
  two runs over this 229s track — roughly **0.2–0.27× realtime**, paid once per
  `--auto-start`.

Two run-hygiene observations, neither the cause: `PACING.json` was stale from the
previously-chosen Manson track (tempo 140.625 vs the actual 110.294) — harmless,
because `check_reel` shows the cuts land on `MUSIC.json`'s own beats at 0.017s worst
deviation, so the EDL was re-bound after the swap; and `MUSIC_SHORTLIST` was built
from an explicitly-passed mood ("aggressive driving energetic industrial") rather than
`SPEC.mood` ("Fun and playful"), which the file mtimes confirm was already on disk —
an override, not a bug.

## P2 — soon

| | Item | Size | Source |
|---|------|------|--------|
| ○ | **R10.6 · The findings validator rejects a judge only after it has spent its entire budget.** Validate the shape early, or state it in the template — see R10.7. | S | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R10.7 · `suggestion` is required by the validator but appears only inside a JSON example** in `episode-reviewer.md:84`. | S | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R10.8 · A judge's "clean pass" means "nothing I was told to look for".** Coverage tracked the prompt, not the episode: an episode passed clean, one sentence was added to the brief, and the next judge found something. | M | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R10.9 · A stale evidence packet was dispatched to three judges**; only a judge's blocking verdict caught it. The packet needs the same digest binding the verdict already has. | S | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R2.7 · An always-on advisory flag carries no information.** `colour_cast` fired on 6 of 8 episodes and every judge saw it, which trains judges to ignore it. Calibration (R2.5) must be judged by whether the flag ever means anything. | S | [retro](retro/2026-08-25-first-real-run.md) R2 |
| ○ | **R2.8 · `color.grade_chain` composes pre-built fragments under a three-way comma convention and validates none of it** — it produced 1.5 KB of ffmpeg garbage during the run. | S | [retro](retro/2026-08-25-first-real-run.md) R2 |
| ○ | **R10.10 · The `_review/` stills packet is mis-indexed** — the reviewer noticed and it was never fixed. | S | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R8.2 · The pool was never widened after day 1.** The delivered reel uses 8 windows out of 1508, and the required contact-sheet "look at the pixels" stage ran **once**, for 177 seconds, on day 1, and was never re-run against a revised cut. | S | [retro](retro/2026-08-25-first-real-run.md) R8 |
| ○ | **R10.11 · "(silent reel)" in the pre-mix loudness check made the agent conclude the music had been lost.** A diagnostic message that reads as a failure. | S | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R10.12 · Eight of 22 `AskUserQuestion` turns were the human arbitrating a per-episode sensor failure** — the clearest measure of where a person's attention was actually spent. | S | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R2.4 · `color_delta_max` was widened by hand to silence a correct complaint** — 12 → 44 → **56** across the run. The knob needs a reason attached, not a larger number. | S | [retro](retro/2026-08-25-first-real-run.md) R2 |
| ○ | **R4.3 · Survive a compaction.** After one context compaction, **12 of 13 `--help` calls** fall in the next 2 h 17 min — and `probe` still was not found. | S | [retro](retro/2026-08-25-first-real-run.md) R4 |
| ○ | **R6.1 · A passing check throws its measurement away.** `check_reel.py:180` assigns `worst` only inside the failure branch, so a passing `color_across_cuts` reports `{"pass": true}` and nothing else (`variety` is identical). The worst-junction delta was re-derived by hand on three separate days. | S | [retro](retro/2026-08-25-first-real-run.md) R6 |
| ○ | **R8.1 · The score bought no part of the delivered reel.** Of 1508 windows the selection reaches rank **1338**; **zero** of the top-8 are used; 8 of 30 chosen windows are `best=False`. `cull` only marks `best`, so nothing was unreachable — but the CV time spent ranking contributed nothing. Either it earns its cost or it stops being presented as authority. | M | [retro](retro/2026-08-25-first-real-run.md) R8 |
| ○ | **R10.2 · Cast candidates shown too small to identify**, and better one at a time than tiled — the operator asked for this during the run. | S | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R10.3 · 95% of conveyor calls were piped through `tail`/`grep`/`head`**, twice losing the answer — once costing a 173-second re-render to read output already produced. | S | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R10.4 · `episode_qc build` dies with a bare traceback naming no episode.** | S | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R10.5 · QC has no "judge only what changed" and no memory between rounds** — ~14 rounds, **97 judges, 160 MB, 8 episodes**, two blocking verdicts, one of them a false alarm from a stale evidence packet. | M | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R11.1 · Infrastructure ate 16 of 98 subagents** — 11 killed by the machine sleeping (episodes 0, 4 and 7 each needed three dispatches), 5 stopped deliberately. Incremental writing belongs in every subagent brief by default; it was proven necessary twice again while writing this retro. | S | [retro](retro/2026-08-25-first-real-run.md) R11 |
| ○ | **R11.2 · The project's memory was empty after six days**, so the same corrections were repeated on different days. | S | [retro](retro/2026-08-25-first-real-run.md) R11 |
| ○ | **R12.1 · A film look: grain, gate weave, a soft edge falloff.** The look layer today is two knobs — a vignette and a bookend fade. Grain was measured and priced out in the cinematic-look design; unfreeze it. | M | [retro](retro/2026-08-25-first-real-run.md) R12 |
| ○ | **R12.2 · Visual transitions between episodes.** Hard cuts only today; the audio side already synthesises whooshes on major cuts and has no picture counterpart. | M | [retro](retro/2026-08-25-first-real-run.md) R12 |
| ○ | **R12.3 · Survey what effects are worth having, and encode WHEN to apply each.** `MoodPreset.look` is the routing hook that already exists and should carry it — otherwise this repeats the `probe grade` story: built, shipped, never reached. | M | [retro](retro/2026-08-25-first-real-run.md) R12 |
| ✅ | **The authoring skill documents every knob it has — done 2026-08-17.** Measured before writing, and the row was smaller than it read: `EDLEpisode` carries 35 fields and the skill already named **30**. The five it never named — `crop_aspect`, `crop_scale`, `border_px`, `border_color`, `color_means` — were authorable from `selection.json` and documented nowhere, which makes them equivalent to fields that do not exist. The row's other half also got its answer: scanning every backticked identifier against `EDLEpisode`/`EDL`/`ReframeSpec`/`LayoutSpec` found **no named-but-missing tool** (the grade-ish suspects — curves, shadows, contrast, gamma, lift, gain — return nothing), so there was no build-or-not decision hiding in it. The prose stays (it carries the refusals); a new table at the end of step 2 is the "one place". A table nobody maintains re-opens the gap silently, so `tests/test_skill_convention.py` now asserts every `EDLEpisode` field name appears in the SKILL — watched red first, then red again under a mutated field name. | S | [#5](fixes-backlog.md#5-the-authoring-skill-must-document-every-modification-tool-it-has), [cheap-P2-chores](specs/2026-08-17-cheap-p2-chores-design.md) §2 |
| ✅ | **Cheap 3-frame probe — built and landed 2026-08-15 (`frame-probe-look-gate`).** `scripts/probe.py grade` renders 3 frames of one episode through `reframe`'s own chain over its frozen route, skipping tracking/storyboard/check/encode — dropping the encode alone buys 1.34–1.84×, but the tracking pass it also skips costs **5.00s** against the encode's 0.59–2.41s on the same 1080p/3s clip: one grade attempt today is track+encode ≥7.4s against the probe's 1.31s (**≈5.7×**), paid per episode via `edl_to_reel`. Probe frames vs. shipped, on the worst (grain, crf 18) source: mean \|Δ\| 1.07–1.39 codes, and the statistic the grade decision actually reads — mean luma — agrees to **0.14 codes**. The visibility half generalized as designed: `deliver`'s post-encode look gate (`lib/lookcheck.py`) samples the delivered reel against its master and hard-refuses a declared vignette/fade that did not reach the pixels — calibrated: a declared vignette of 0.10/0.30/0.60 drops the corner-over-centre ratio 0.0844/0.2576/0.5209 (0.84–0.87× of declared); a 0.5s fade took a 75.28-mean opening frame to 0.00. No waiver, per governance #8. Titles still carry no pixel check (filed below), and the constants are calibrated on synthetic patterns, not real footage (also filed below). | M | [#10](fixes-backlog.md#10-cheap-3-frame-preview-to-converge-the-colour-grade-before-a-full-episode-re-render), cinematic-look §11.1/§12, [frame-probe-look-gate](specs/2026-08-15-frame-probe-look-gate-design.md) |
| ○ | **Calibrate the look** — `LOOK_VIGNETTE_MAX` (0.6), the 0.55/0.45 plateau/falloff split, and every row of `MoodPreset.look` are hand-picked on synthetic test patterns; no real footage has graded against them yet. | S | cinematic-look §11.3/§12 |
| ✅ | **`outro.TAIL_MIN` — measured 2026-08-18, and deleted rather than re-tuned.** The row asked whether 0.5s is the right value; the answer is that the constant was wrong in **kind**. The reel is `line + fade` long and `mix` fades over `[line, line + fade]`, so `max(TAIL_MIN, fade)` at `fade < 0.5` demanded vocal-free space in audio the stem never contains — and when it bit, the `no-gap` rung it fell to checks no tail at all: measured, it traded a clean 0.30s fade sitting entirely inside a gap for a **1.50s fade over 1.15s of singing**. It also disqualified the whole `[0.35, 0.5)` band that `offset.vocal_gaps`' own `min_gap = 0.35` declares valid — **4 of the real track's 25 gaps**, costing the `fun` preset **10.3%** of its legal landing zone and an authored `fade: 0` **23.1%**. Replaced by `need = fade + TAIL_MARGIN`, `TAIL_MARGIN = 0.05` **derived** as two bins of the vocal envelope at `vocals._SPAN_HZ` and machine-checked against it. `OutroFit.need` came with it, because the constant was also what `EDL.md` quoted — already wrong for `epic`/`moody`/`nostalgic`. | S | music-outro-fit §11.1, [deferred-measurements](specs/2026-08-18-deferred-measurements-design.md) §1 |
| ✅ | **Calibrate the downbeat detector on more than one track — done 2026-08-17, and the answer was not a re-tuned constant.** Four unmeasured tracks were already beside the measured one in the 2026-08-03 run's music cache, so the "cheapest next evidence" cost only decode time. Three findings, none of them the one the row anticipated. **(1) The row named three first-cut constants and only two existed** — `_downbeat_phase` was a bare `argmax` with no confidence margin anywhere, so it always returned a phase however flat the four means were. **(2) The shipped 150 Hz sits on a knife edge on the very track it was tuned on**: across ±0.05/0.10/0.15 the control scores 32/88/59%, where 60 Hz holds a plateau at 91/93/93% and a higher margin (2.04 vs 1.67) — re-tuned to 60, and a plateau existing at all is what distinguishes signal from fit. **(3) Four of the five tracks carry no downbeat signal at any of 32 sweep cells** — 38–50% against a 25% chance level, margins 1.00–1.03, and their optima scatter across the grid, which is the signature of fitting noise. For house the premise fails structurally: four-on-the-floor puts a kick on every beat, so "the downbeat carries the kick" has nothing to discriminate. Also corrected: the design's headline `max/min = 1.887` **does not discriminate** (one failing track scores 1.782 at 36% hit-rate — its spread is high because a phase is quiet, not because its winner is loud); the ranked gap `max/2nd` does. `_PHASE_MARGIN = 1.5`, calibrated over **124 sliding 30s+42s windows** at the sizes `analyze` actually uses: of **97** windows from the four signal-less tracks none reaches 1.5, while five reach 1.31–1.35 — so 1.3, the obvious round number, passes noise. Honest limits: the positive class is still **one song**, no ground truth was used anywhere (none is on disk), and no test in this repo can defend 1.5 over 1.3 — the evidence is five real tracks that will never live here. | S | music-outro-fit §11.3, [downbeat-confidence](specs/2026-08-17-downbeat-confidence-design.md) |
| ✅ | **`color.shadow_red_arg` had `highlight_red_arg`'s pre-fix sparse-anchor defect — worse. Fixed 2026-08-15.** Re-measured with the same lossless ramp probe: the three hardcoded anchors sagged **−6** codes at the shipped `ret=0.25`/`SHADOW_RED_MAX`, worst at code 79 (x≈0.31, in the gap right after the return point), and up to **−14** across the legal `(lift, ret)` domain. Fix: identity anchors every `SHADOW_RED_STEP=0.05` derived from `ret` (not hardcoded) — exactly identity at the shipped `ret` for every legal lift. **The same probe found a second, worse defect the queued row never named**: at `lift >= ret` the toe's slope `1 − lift/ret` goes non-positive and the mapping inverts, banding the shadows — now refused with a `ValueError`. It is this refusal, not the densification, that removes every non-monotone cell in the scanned domain. | S | [shadow-red-length-reconcile](specs/2026-08-15-shadow-red-length-reconcile-design.md) §1, cinematic-look §12 |
| ✅ | **Mood → grade — done 2026-08-17.** `MoodPreset.tone_bias` displaces the common tone target in the direction `SPEC.mood` asks for, riding the tone pair the conductor already authors: **no second colour stage, no LUT asset, no extra encode**. Three measurements shaped it. **(1) The carrier.** `EDL.variety.preset` looked ideal and lost: it is `None` on the only real run on disk, so the mood arrives by `--spec` — the same flag and file `edit_plan` takes, resolved through the same `moodpreset.resolve`. No `--spec` → no bias → the plain median, pinned as an anti-regression test. **(2) The floor, which is not small.** Rendering a real episode through the curve the conductor authors lands **6.5–11.5 luma units** from the target it asked for — against a `MATCH_EPS` of 4.0 that decides whether to correct at all. So the reel is matched to about ten units, not four, and a *subtle* mood table cannot work: the vectors are 15–20 units because anything less disappears into the conductor's own error. **(3) Out of headroom.** A bias that leaves 0–255 scales the WHOLE vector rather than clamping one anchor (clamping `epic`'s highlight lift leaves "crush the blacks", a different mood). Scanned over eight plausible medians: `k = 1.00` on five, nothing refused, and scaling fires only on bright targets for the two presets pushing p95 up — at a median of (110, 170, 250) `epic` keeps **31%**, i.e. 5 units, **under the floor and therefore invisible**, so `MATCH.md` names it `mood-bias-ineffective` rather than hiding it. Honest limits: the four vectors are a first cut nobody has looked at (the mechanism is proven, the taste is not), the floor is two clips of one shoot, and `check_reel`'s colour gate compares episodes to *each other* — they all move together, so nothing checks the reel now matches the mood. | M | colour-stage §11, matchgrade §8, [#9](fixes-backlog.md#9-cinematic-effects-library--mood-oriented-palettes), [mood-grade](specs/2026-08-17-mood-grade-design.md) |
| ✅ | **The conductor's 6.5–11.5-unit residual — diagnosed 2026-08-18, and it is none of the three candidates the row named.** Separated over one frame from each of the run's two cameras, decoded to lossless FFV1 first. **Spline: exactly 0.0** at all three anchors (a 256-code ramp returns `T(73)=50`, `T(137)=100`, `T(196)=195`; worst deviation anywhere −1.0). **Encode: ≤2 units.** **Measurement's 160-wide downscale: real (9 units at the drone's p95) but not the cause** — see the trap below. **The cause is `curves=all` being a per-CHANNEL transfer against a LUMA target** (Jensen: `luma(T(R),T(G),T(B)) ≠ T(luma(R,G,B))`). The control is the proof — same frame, same curve, same measurement, grayscale vs colour: DJI colour `[0, +5, −7]`, DJI **grayscale `[0, 0, 0]`**; Canon colour `[0, +1, −3]`, grayscale `[0, 0, −1]`. So "6.5–11.5" is **content, not a system constant**. **The trap:** dropping the downscale makes p95 *worse* (−1 → −7) because the two independent errors currently cancel. Fix identified, filed below as its own row (it carries a taste trade-off); `tone_bias`'s 15–20-unit vectors are unchanged. | M | [mood-grade](specs/2026-08-17-mood-grade-design.md) §3/§8, [deferred-measurements](specs/2026-08-18-deferred-measurements-design.md) §3 |
| ✅ | **§6.1a layer 3 vs track-stitch — re-assessed 2026-08-18. Remainder real, build deferred on evidence.** The two are **inverse**, so neither subsumes the other: stitch handles *one person, two ids* and **joins**; layer 3 handles *two people, one id* and **splits**. The remainder over what ships is narrower than the row assumed — `checks.continuity` is already the geometric half of layer 3's detection and already stops the episode (`orchestration._UNFIXABLE`); what is missing is descriptor/area corroboration and the repair. The run says wait: **7 routes, 0 `continuity` failures, `stitched: []` everywhere**, closest approach 5.5× under the gate, and exactly **one** episode across the shoot offered two comparable people (ep3, 75% of the hero's area, `border: 1.0` for all 53 of its frames). Honest weakness recorded: the `4%-of-src_w` cap is a *teleport* gate (4603 px/s here), so it cannot see a swap between adjacent people — filed as its own row. **Build trigger:** a real run producing a `continuity` stop or an episode-QC `hero` finding. | S | cast-hero-pin §11, [deferred-measurements](specs/2026-08-18-deferred-measurements-design.md) §2 |
| ○ | **Calibrate the first-cut identity thresholds** — `CAST_MATCH` / `CLUSTER_COS` / `MAX_CAST` are declared guesses; the distance distribution needed to derive them is already on disk in any real cache. | S | hero-reid §11, cast-hero-pin §11 |
| ✅ | **Confirm the torchreid dep list on a clean install — done 2026-08-19.** torchreid 0.2.5 declares **no runtime requirements at all** while importing seven packages, so `pip install torchreid` succeeds and `import torchreid` raises (measured 2026-08-14: `gdown` missing, and `tabulate`/`Cython`/`h5py`/`imageio`/`yacs` absent too). `setup.sh` installs them explicitly and verifies on **import** rather than `pip show`. **A second real install, 2026-08-19, found the list still incomplete** — `ModuleNotFoundError: No module named 'tensorboard'` — and it is the member that no scan of torchreid's OWN imports can reach: `reid/engine/engine.py` says `from torch.utils.tensorboard import SummaryWriter`, so the root name torchreid imports is `torch`, which is present, and it is *torch's* submodule that needs the separate `tensorboard` distribution. Walking all 189 torchreid modules and importing each of their 63 external dotted names confirmed tensorboard as the only genuine gap left; added to the list. The corrected list was then watched to succeed — `verify_runtime` reports `reid: installed` on this machine, which is what the row was waiting for. Residual, harmless: torchreid warns that its compiled `rank_cylib` is absent and falls back to Python ranking; `lib/reid` uses only `FeatureExtractor`, so no path this repo takes reaches that code. | S | demucs-required slice 2026-08-14; second install 2026-08-19 |
| ✅ | **Close the episode-QC loop — the re-judge half done 2026-08-18.** `build_reel` refuses to deliver (`episode-qc-reprocessed`) when its retry loop re-rendered an episode and the manifest says `episode_qc.state == "judged"`; the router re-judges exactly the named indices and the second pass delivers. **The other half stays open in P3** (auto-routing a blocking finding into a re-render), so this row is not the whole item. Four measurements shaped it and two changed the design. **(1) The record existed and the inspector dropped it** — `deliver` has written `reprocessed_after` into the attestation since the episode-qc slice, but `provenance._episode_qc_state` read only `state`, so `montage verify` reported a clean `judged` for a delivery carrying unjudged renders, at the one place CP3's own text tells a human to look. Fourth arm added: `stale`. **(2) The gate already knew how to catch this; nobody asked it twice** — the reprocess writes to the episode manifest's `out_path`, which IS the file `ReelEpisode.clip` names and the file `episode_qc build` digested, so a *second* phase-2 run would fire the existing `episode-qc-stale` unaided. The hole was only that the FIRST run delivers first. **(3) A partial re-judge needed no new code**: `build_qc` re-reads every `findings.json` and re-digests every clip from disk, so overwriting one judge's file and re-running `build` is the whole mechanism — which is why this was M and not L. **(4) The cost is zero on a clean reel** — the 2026-08-03 run's `reel_report.json` has `fail_reasons: []`, so the retry loop never engaged; the stop costs one QC round exactly when an episode was re-rendered. Also corrected: episode-qc §8's claim that "the router re-runs QC on exactly those episodes after delivery" was never built (the skill said *offer to*, and after delivery is too late to stop anything). Honest limits: the `absent` paths still ship unjudged by design, the gate still proves presence not diligence, and the end-to-end proof fakes both the reprocess and the first `check_reel` round — no test joins a real colour failure to this stop. | M | episode-qc §8/§13, [re-judge design](specs/2026-08-18-episode-qc-rejudge-design.md) |
| ✅ | **Surface the active editorial constraints in `montage status` — done 2026-08-17.** `next_action` gains a `constraints` key with three named states: absent, authored, or present-and-unreadable. The third is what needed deciding — `Constraints.from_json` refuses hard (correctly), but this is the inspector the router calls constantly, so letting the refusal escape replaces the status report with a traceback over a typo, and catching it into `rules: []` answers "nothing binds this cut" when the truth is "nobody can tell". Caught, with the message in `error`. The enforcement point does not move: `write_edit_plan` still loads through the same refusing constructor with no waiver, and a fourth test pins that so nobody later mistakes this for a softening. | S | constraints §11, [cheap-P2-chores](specs/2026-08-17-cheap-p2-chores-design.md) §3 |
| ✅ | **Auto-place a ramp's `at` — measured 2026-08-18, and it is not buildable on this sensor.** Not deferred on cost: the anchors do not carry the information. `anchors.measure_curve` is *global* frame-to-frame difference, so on a moving camera the camera's own motion is the signal and it is roughly constant — across the run's eight episodes **seven have 100% of their samples above `ANCHOR_REL * peak`** (peak/min 1.23–1.64), so the relative floor selects nothing and `anchors_from_curve` returns its `min_gap` thinning grid. On ep5, **the one episode of the run that actually carries a ramp** (`MVI_3998`, `at: 3.42`), it returned five "anchors" in 7s, four inside the legal band; the nearest is 0.42s from the human's pick, which is guaranteed by the density, not earned — at that spacing every point in the band is within ~0.5s of one. **What the measurement did find is live:** `pacing --anchors` was already printing that noise into `PACING.md` as editorial advice. Built instead: `curve_contrast` + `ANCHOR_FLAT_FRAC = 0.5` (7-vs-1 separation at 100% vs 33%, so anything in [0.34, 0.99] works), the flat guard, and a contrast column that says *flat — no moment is distinguishable*. | M | speed-ramp §13, [cheap-P2-chores](specs/2026-08-17-cheap-p2-chores-design.md) §5, [deferred-measurements](specs/2026-08-18-deferred-measurements-design.md) §4 |
| ✅ | **A `sample_clip` fixture longer than `WIN_MAX` — done 2026-08-17.** New sibling `multi_window_clip`, NOT a change to `sample_clip` (27 test files consume it; every golden would move for an unrelated reason). 12s, three segments with hard cuts, measured on the real bytes rather than assumed: ffprobe gives 12.0s / 30fps and PySceneDetect returns exactly `[5.0, 9.5]`, so the spans are 5.0 / 4.5 / 2.5 — two past `WIN_MAX` into `units_for_span`'s peak branch, one in-band — and the carve yields **9** windows against `CLIP_POOL_MIN = 5`. The old fixture's shape yields exactly **1**, confirmed by running the carve over it. The vacuity check ran: pointed at `sample_clip`, the new test fails immediately. | S | intake-motion-scoring §9, [cheap-P2-chores](specs/2026-08-17-cheap-p2-chores-design.md) §4 |
| ✅ | **LICENSE + its `plugin.json` field — done 2026-08-17, AGPL-3.0.** Constrained by a dependency rather than chosen: `ultralytics` is AGPL-3.0 and `scripts/intake.py` imports it on the main path, so a permissive licence over this tree would be internally inconsistent. The weights are **not** redistributed (`git ls-files` finds zero tracked `.pt`; `setup.sh` downloads them), which removes the redistribution question and leaves only linking. The text is copied verbatim from ultralytics' own dist-info — the same 661-line / 34523-byte AGPL the dependency ships — rather than retyped. The test pins the text's identity, not the file's existence. | S | plugin-packaging §6, [cheap-P2-chores](specs/2026-08-17-cheap-p2-chores-design.md) §1 |
| ✅ | **The length figures do not reconcile — diagnosed and fixed 2026-08-15.** Read off the 2026-08-03 run's own artifacts, not the summary that queued the row: `EDL.target_dur` 34.072 equals `sum(play_dur())` to **0.0004s**, and the delivered `out/REEL_v1.mp4` is 34.051 — **21ms** off `EDL.target_dur`, under one frame at 30fps. Those two never disagreed. What disagreed was `PACING.json`: written **nine hours** before `MUSIC.json`, fitted at **140.625** BPM against the shipped track's **110.294** — it belonged to a track that was swapped out. `EDL.md`'s "32.4s" (sum of `dur`, ignoring the ramp) was **already fixed**: `edl.to_markdown` sums `play_dur()`; the run's markdown just predates the speed-ramp slice. And **"30.317" is not reproducible from any artifact** in the run — not `EDL.json`, not `PACING.json`, not `reel_report.json`, no `.md`/`.txt`/`.log`. Fix: `build_edl` now refuses when `pacing.tempo` and `music.tempo` differ by more than `_TEMPO_TOL = 0.5` BPM. | S | [#20 second pass](fixes-backlog.md), length-retime §9, [shadow-red-length-reconcile](specs/2026-08-15-shadow-red-length-reconcile-design.md) §2 |
| ✅ | **Make pacing's round trip a fixed point again — fixed 2026-08-17 (`pacing-fixed-point`).** `EDLEpisode.base_dur` records the footage-projected length ONCE, at projection; `pacing.build_pacing`/`_bounds` and `edit_plan._bind_pacing`'s half-beat guard all read it through `base_play_dur()` instead of the already-bound `dur`, so the spine becomes a pure function of `(base, music)` and fit → apply → fit → apply reproduces the same `EDL.json` (proven byte-identical, five real driver calls, no ffmpeg needed). **The measurement found more than the queued deadlock**: re-fitting an already-fitted EDL against a DIFFERENT music window landed every cut a beat early even with NO outro anywhere near it — a scenario `[5.77, 3.41, 6.02, 4.88]` fit to 128 BPM then re-fit to 110 BPM lands on beats 10/16/27, where fitting the scenario straight to 110 BPM lands on 11/17/28, the whole reel 0.5455s short — and it fires on the stage's own recommended remedy ("Try another window"). The folded-in digest idea shipped too: `Spine.music_digest` + `music_identity()` binds a spine to the analysed music WINDOW, not just its tempo, closing the case a tempo-only check cannot see — the same track at a different `start_offset`. | M | music-outro-fit §11.8, final review I-1, shadow-red-length-reconcile §6/§7, [pacing-fixed-point design](specs/2026-08-16-pacing-fixed-point-design.md) |
| ✅ | **Reconcile `build_reel`'s length re-time with the outro fit — fixed 2026-08-17 (`pacing-fixed-point`).** `ReelManifest.outro` carries `EDL.outro.to_dict()` (round-tripped through `OutroFit.from_dict`, so a malformed outro fails loud rather than reading as `"unchanged"` and silently restoring the absorb); `reel_orchestration.next_action` gains `outro_fixed`, and a within-band shortfall now escalates to `pacing` (reason `outro-length-chosen`) instead of silently absorbing — `length_retime_max` (1.0s) is as wide as the 0.96s miss the whole outro slice exists to fix. | S | music-outro-fit §11.10, [pacing-fixed-point design](specs/2026-08-16-pacing-fixed-point-design.md) |

## P3 — someday

Grouped by area. One line each; the source carries the reasoning.

**Front half / authoring**
`split` — the last genuine layout, two sources into two rects (misc-engine, fit-solid §9, pan §12) ·
trend-scan SP4 (§5.4), which also unblocks reel-review's `trend_flavor` ·
shot-order grammar, "never two same-size shots back to back" (mood-preset §14) ·
real window dedup for the variety census's `available` (mood-preset §14) ·
carrying editorial constraints through `edl_to_reel`'s hand-authored front door (constraints §11) ·
more constraint kinds — `no_adjacent`, visual-similarity repeats (constraints §11) ·
a semantic version marker on `FOOTAGE.json` so `from_dict` can refuse a stale artifact (intake-motion-scoring §9)

**Front-half sensors**
a **subject-motion** anchor sensor — global frame difference cannot place a ramp
(measured: 7 of 8 real episodes are a flat plateau to it). Two candidate sensors are
already BUILT AND RUNNING, just not reachable from here: `carve.track_displacements`
(median displacement across shared track ids — identity-consistent by construction)
and a vidstab-subtracted curve, both of which `intake.py` calls today. What is
missing is not the code, it is a route from intake's tracking data to `lib/anchors`,
which runs at pacing time over an episode's source and has none. (This row said
"exist unwired" until 2026-08-19, which read as dead code and is the opposite of the
truth — it is a subsystem boundary.) Only with a route does auto-placing a ramp's
`at` become a question about wire format and clamping rather than about whether
there is any signal (deferred-measurements §4.5)

**Identity**
hero-conditioned re-scan — re-measure windows holding a named hero after cast naming; **blocked on a face detector** (mood-preset §14, playbook P3) ·
auto-register a chosen hero back into the cast (cast-hero-pin §11) ·
sharpness/blur metric — the cv2 blocker is gone, the cost is now measurement work plus a `CACHE_VERSION` bump (footage-intake §8)

**Colour**
a range-relative mood displacement instead of the additive one — it would fix the
headroom collapse the additive table measurably suffers on bright footage (`epic`
keeps 31% of its vector at a median p95 of 250), at the cost of "moody" meaning
something different on every reel. Only worth it if the `mood-bias-ineffective`
note fires often on real briefs (mood-grade §2/§8) ·
mood as **chroma**, not only luma — a mood is warmth as much as contrast, and the
2026-08-17 slice moves only the luma triple the conductor owns; the warm/cool half
needs the cross-episode white-balance actuator already deferred below (mood-grade §8) ·
✅ make the tone transfer **luma-only** AND ✅ fix the **160-wide** measurement —
**both landed 2026-08-19, together, and the row's premise was wrong.** It claimed
the per-channel transfer was the cause of the conductor's whole residual. Measured
end to end on the run's two cameras, worst \|residual\|: shipped **9.0**/3.0, transfer
alone 8.0/2.0, ruler alone 5.0/3.0, **both 2.0/1.0**. The transfer buys one unit of
the nine; the ruler buys four; only the pair closes it — so the rows really were
inseparable, for the opposite reason to the one recorded. deferred-measurements
§3.4's warning (fixing the ruler alone made p95 go −1 → −7) does **not** reproduce:
it changed the verification while leaving the authoring at 160 wide, comparing a
curve built for one ruler against a reading taken with another. Two findings the
row did not anticipate: the real "not a free swap" is a **range** mismatch, not
saturation (`format=gray` is full range, the Y plane `lutyuv` writes is 16–235, and
`curves` never had to know because swscale converted for it); and dropping the
spline deleted half the function, since dense sampling, anchor-joining and the
minimum gap were three defences against a cubic that a LUT does not fit
([luma-tone-transfer](specs/2026-08-19-luma-tone-transfer-design.md)) ·
reconcile the two neutralizers, white-balance vs normalize-gain, into one authority (colour-stage §11) ·
crop-accurate / K-frame tone measuring instead of the whole frame at the midpoint (matchgrade §8) ·
cross-episode white-balance / cast matching (matchgrade §8) ·
`highlight_red_arg`'s shoulder (`hi`) formula is monotonicity-fragile near
`pull ≈ 1 − knee` for `knee ≥ 0.7` — a knee×pull grid scan found the
pre-existing code already broken there; unreachable today (the one production
call site never passes `knee=`), reported not fixed (cinematic-look §12) ·
`shadow_red_arg`'s densified curve keeps a one-code wobble near `lift ≈
ret` — **15** cells at `ret` step 0.01, not three: that count was a
`ret`-step-0.05 reading, and the three it named (0.15/0.14, 0.20/0.18,
0.20/0.19) are exactly the subset that coarser grid could see, up to 0.03
from `ret` (not "within 0.02"); step 0.1 has one, uncounted at the finer
step; the shipped `ret` has none (shadow-red-length-reconcile §1.2/§6) ·
`highlight_red_arg`'s sub-knee loop carries the same `1e-9`-bound-vs-`.4f`-
emission mismatch `shadow_red_arg` fixed on 2026-08-15 with
`SHADOW_RED_FMT_EPS`: a `knee` landing in a ~5e-5 band would emit a
duplicated control point and ffmpeg refuses the filter (exit 234).
Unreachable today — the one production call site never passes `knee=`, and
the default 0.60 is an exact 0.1 multiple — so it is filed, not fixed; the
one-line fix is the constant that already exists (shadow-red-length-reconcile
§1.2 M-2, found by that slice's whole-branch review)

the `lutrgb` ban rests on a symptom with no recorded mechanism, and it does not
reproduce — measured 2026-08-19, every spelling renders correctly and identity is
exact to the code. The ban **stays** (one synthetic probe on one ffmpeg build does
not overturn a landmine written from a real corrupted render), but a candidate
misdiagnosis is on record: `check_episode.py` calls it "the seek/lutrgb
corruption", so the two were seen together, and the `-ss`-after-`-i` landmine
produces black frames on its own. Closing this needs the original render, which
nobody kept (luma-tone-transfer §5) ·
the tone shoulder's slope (`TONE_TOP_SLOPE = 0.35`) is what the remaining 1–2 units
of residual are made of — the output's top percentile is not the map of the input's
because the segment above the shoulder anchor is deliberately gentle. Working as
written, and nobody has asked whether 0.35 is right (luma-tone-transfer §8) ·
**nobody has looked at the new grade on a screen.** Chroma no longer rides the tone
curve, so a graded reel is visibly different — more saturated where the curve
compresses, less where it lifts. Correct for an operation named "tone", and still a
change no human has judged (luma-tone-transfer §8) ·
calibrate the luma transfer beyond two frames of one shoot — every number in its
design comes from one drone frame and one Canon frame (luma-tone-transfer §8) ·

**Moves — geometry and time.** These move the frame or the clock, ride the
tracked route, and are judged by `check_episode` like any crop.
scenery zoom, Ken Burns over a subject-less shot (subject-anchored-moves §11) ·
easing for zoom and pan travel (subject-anchored-moves §11, pan §12) ·
`minterpolate` interpolated slow-mo — real intermediate frames instead of duplicates (speed-ramp §13) ·
speed-**up**, `factor > 1` (speed-ramp §13) ·
pan tilt (Y motion) and a pan over part of a clip (pan §12)

**Look — image treatment. The tail of #9, whose vignette + bookend fade half
landed 2026-08-13 (cinematic-look).**
Nothing here moves the frame; it tints, darkens or textures it, so none of it
touches the route or the composition checks. **Grain** (`noise`) joins this
line rather than the landed half — measured and priced out, not merely
deferred for time: at the delivery profile's own crf 18, `noise=alls=8` (the
first setting with any real presence) costs **×4.36** the file size, `alls=12`
**×8.82**, `alls=20` **×14.08** — a 30s reel goes from ~37MB to ~160MB at the
cheapest useful strength, and the platform re-encodes on upload anyway, so the
cost is paid and the grain is then destroyed by someone else's encoder
(cinematic-look §11.2/§12). Also here: film LUTs (need licensed asset files —
a distribution question before a code one), halation/bloom, light leaks,
chromatic aberration, letterbox bars (wrong on a 9:16 reel, where the `fit`
layout's background already does the job).

> **#9 is one item split across three buckets** — P1 built the vignette +
> bookend fade, each with a measured visibility proof (2026-08-13,
> cinematic-look — closing #18 alongside it), P2 biases the grade by mood
> (the long-deferred "mood LUT", still open), and this line holds the rest,
> now joined by grain. Landing P1 does not close #9 — it stays open until P2
> and this P3 line land too.

**Music**
a real downbeat detector — madmom or a trained model instead of a bass-band
heuristic. This is the honest fix for the 2026-08-17 finding that the current
one works on **one real track in five** and cannot be made to work on the other
four; the confidence gate that shipped only makes it say so. **M**, and it
brings a new dependency (downbeat-confidence §9) ·
calibrate the positive class on more than one song — everything the gate's
threshold rests on separates **one** positive track from four negatives; the
negatives are well sampled (97 windows), the positive is 27 windows from one
song (downbeat-confidence §9/§10) ·
meter beyond 4/4 — the downbeat detector assumes it, so a 3/4 track silently gets a wrong bar grid. **One of two known premise failures since 2026-08-17**, and the smaller one: the kick-marks-the-bar assumption fails on more music than 3/4 does (music-outro-fit §10/§11.3, downbeat-confidence §3) ·
real librosa **section** detection — the outro fitter approximates a phrase boundary with a bar line; segmentation would find the real ones (music-outro-fit §10) ·
a check that HEARS the delivered audio — the same hole the cinematic look has, now with a second occupant (music-outro-fit §11.5, cinematic-look §11.1) ·
whole-spine re-fit across in-point candidates — the surviving half of the "re-pick `MUSIC.start_offset`" row below, now that its back-edge form is measured dead (music-outro-fit §0) ·
fit a RAMPED closing episode instead of skipping it — `play_dur()` is non-linear in `dur` once a ramp is present, so the outro fit refuses to move it; inverting `ramp_extra` the way `_bind_pacing` does would close it (music-outro-fit §5/§12) ·
adaptive hook length instead of a fixed `HOOK_BEATS` (pacing §10) ·
per-section mood arc (mood-match §9, pacing §10) ·
beat as a hard gate, once a cut can be re-trimmed (music-spine §9) ·
⊘ re-pick `MUSIC.start_offset` at the back-edge (length-retime §9) — **measured dead 2026-08-14 and superseded** by the "whole-spine re-fit across in-point candidates" row above: the shift the 2026-08-03 reel needed was 2.235 beats, and only a whole-*beat* shift keeps the existing cuts on the grid (two beats leaves the end 0.128s off; a whole-*bar* shift maps the grid onto itself and changes nothing). Kept as a line so nobody re-derives it (music-outro-fit §0) ·
✅ measure the delivered fade's real distance from `EDL.outro.line` — **closed for free 2026-08-17** by `check_reel`'s new advisory `outro` check (pacing-fixed-point §6): `total` was already probed for the length gate, so the residual costs no extra I/O. **Correction on the way out**: the "fraction of a frame" framing above was optimistic — `check_reel._LENGTH_TOL` is **0.5s**, so the length gate itself had been passing a master half a second off the chosen length without a word (music-outro-fit §11.9, [pacing-fixed-point design](specs/2026-08-16-pacing-fixed-point-design.md) §6) ·
a migration for `EDL.json` files with no `base_dur` — they keep the old fixed-point deadlock forever; no auto-migration and no refusal were added on purpose, since either would touch the hand-authored SP1 front door this project keeps deliberately open. A one-shot re-projection from `selection.json` could fill the field, or the three-command detour stays the answer for these artifacts forever (pacing-fixed-point §9/§10) ·
the digest's audio-unreadable rung falls back to a check that cannot see a window change — when `MUSIC.json`'s track cannot be read, `build_edl`'s identity ladder falls back to comparing tempo alone, which is named as not-checked but still blind to the SAME track re-analysed at a different `start_offset`; recording `start_offset`/`duration` on `Spine` beside the digest would let the fallback compare those too (pacing-fixed-point §4.1/§9/§10) ·
calibrate the outro residual against perception — `check_reel`'s advisory `outro` check keys `passed` on `_LENGTH_TOL` (0.5s), a reporting boundary borrowed from the length gate, not a measured answer to how far a fade may start from a bar line before the ending stops resolving; same open class of question as `outro.TAIL_MIN` above (pacing-fixed-point §6/§10) ·
a real-ffmpeg proof of the length absorb's outro refusal — design §7 asks for a reel short by more than `_LENGTH_TOL` and less than `length_retime_max`, delivering with `outro` absent and stopping-and-reporting with it present; the branch proved both only against a monkeypatched `check_reel.run` (pacing-fixed-point §7/§9, final-review Finding 6) ·
enforce `SPEC.length_s` rather than only logging the cross-check —
**unblocked 2026-08-15**: the length diagnosis found the target this would
gate (`EDL.target_dur`) already equals what the master delivers, and only a
stale `PACING.json` ever disagreed (length-retime §9,
shadow-red-length-reconcile §2) ·
music-less dual-emit + trending-sound sidecar, §5.14 (music-spine §9, using-montage §5) ·
a SPEC field for ambient / SFX instead of only `ReelManifest` flags (ambient §9, sfx §9) ·
per-episode ambient level or mute (ambient §9)

**Reel / QC / delivery**
secondary-aspect re-reframe on deliver — *the item that pointed at a "Phase F" which never existed* (reel-back-half §9) ·
`variety` auto-fix in loop-2, needs a front-half fixer (reel-retry-loop §8) ·
resumability / run-state persistence for the reel loop and the EDL run — deferred by four separate designs; only intake ever got it (reel-back-half §9, extract-spine §7, reel-retry-loop §8, edit-plan §7) ·
horizon-level detection (episode-qc §13) ·
auto-route a blocking QC finding into a re-render (episode-qc §13) ·
bound the outer re-judge loop — nothing caps how many stop → re-judge → phase-2
cycles a reel can take; `rm.cap` bounds attempts *within* one `build_reel` call and
nothing bounds them across calls. Each cycle needs a human or an agent to dispatch
judges, so it cannot spin unattended. Name a real case before inventing a constant
(re-judge §8) ·
pixel/CV subject detection for safe zones, and a hard gate with a re-frame actuator (safe-zones §11) ·
a reviewer panel instead of one subagent, and judging real playback rather than stills (reel-review §7) ·
stamp the other six run artifacts with provenance (attested-run §12) ·
multi-reel fan-out — `reel_count > 1` now refuses loudly instead of silently making one (reel-brief §7, reel-review §7) ·
calibrate the look gate's constants (`VIGNETTE_MIN_FRACTION`/`FADE_BLACK_MAX`/`FADE_SOURCE_MIN`/`VIGNETTE_FLOOR` in `lib/lookcheck.py`) on real footage — measured, but on synthetic patterns and one encode profile (frame-probe-look-gate §11) ·
generalize the frame probe to the other QC axes, composition and path smoothness — `RenderPlan` + `with_tail` are axis-agnostic, only colour is wired this slice (frame-probe-look-gate §11) ·
record the applied `color_correct` on `PathMeta` so `probe_grade` can see and reproduce (or refuse against) a reel-level colour retry — its no-`--edl` baseline is silently wrong for any episode `build_reel`'s retry touched, because the pull lives only in `build_reel`'s own in-memory dict and `EPISODES.json` never carries it forward, so no later re-probe can recover the shipped grade either (frame-probe-look-gate, whole-branch review) ·
a titles-only delivery — and even an explicitly EMPTY `TITLES.json` (the predicate `_verify_look`/`lookcheck.evaluate` use is `titles is not None`, a path was passed, never "the parsed `Titles` has items" — filed at this slice's own Task 5 but never promoted to this file) — still pays the full 3-frame decode (5 subprocess calls) that `evaluate` never reads for anything but a permanent `not-checked` finding; gate the sampling in `_verify_look`/`probe_look` on `vig or fade` (frame-probe-look-gate, whole-branch review) ·
`provenance.verify_delivery`'s detail for an unattested file reads "this file was not produced by deliver()" — literally false for the look-gate-withheld case (`deliver` DID run and DID write `REEL_v{n}` before refusing); and `look_checks` (the gate's own findings, present in a WRITTEN attestation) is never surfaced by `montage status`/`verify`, so a `not-checked` vignette or fade reads no differently from a passing one at either command (frame-probe-look-gate, whole-branch review)

**Titles**
libass/ASS rendering · per-episode titles · the full pixel-level safe-zone gate for
the **subject** — the titles half landed 2026-08-19 (`titles.zone_overflow` refuses a
staircase that would render into the app's chrome, measured at 244px on the reels
table), and what remains is **the same capability the Reel/QC group's "pixel/CV
subject detection for safe zones" needs; one measurement, two consumers, so build it
once** · `x`-axis containment for titles — the gate's band is rows only, so a very
long line at a large `scale` can overflow the left/right margins unchecked
(titles-pixel-gate §9) · the gate reads no TEXT: proving ink appeared is not proving
the words are the author's, and any font puts ink in the band, so a WRONG FONT passes
(§9; the glyph metrics `_layers` already computes would close the font half) · titles
in the frame probe — they are burned at `deliver`, so converging a title's position
still costs a reel encode (§9) · a ONE-CHARACTER title clears the evidence floor by
only 1.9x, the thinnest legitimate margin in the table (§3.4) · calibrate
`TITLE_INK_DELTA`/`TITLE_MIN_FRACTION`/`TITLE_BAND_PAD` on a second shoot — all three
are measured against one delivered reel plus a synthetic corpus (§10) ·
cross-platform font install (titles §7)

**Docs / test scaffolding**
the edit-plan knob-coverage test proves a field NAME is present, never that the
explanation beside it is correct or current — it stops the silent half of the
drift, and a word pasted into a table cell passes it (cheap-P2-chores §2.2) ·
`montage status` surfaces the editorial rules without checking them against the
current cut — it never sees an EDL, so it can say which rules exist and not
whether they hold; and a DELETED `CONSTRAINTS.json` still passes everything
everywhere, exactly as constraints §10 already recorded (cheap-P2-chores §3.2) ·
`multi_window_clip`'s detection stream is faked like every other intake
integration test, so the new window-pool proof covers the carve and pool-scoring
plumbing on real bytes, NOT the motion sensor's judgement — the sensor still has
no real-footage proof, which is the calibration row's territory
(cheap-P2-chores §4.1)

**Packaging / runtime**
migrating a **pre-convention run** into `montage/` — not a `mv`: measured 2026-08-25,
artifacts carry absolute paths to OTHER artifacts, not only to footage
(`out/EPISODES.json` 57, `cast_candidates.json` 15, `cast.json` 10,
`out/EPISODE_QC.json` 8, each `.intake_cache/*/clip.json` 52 — every crop PNG), so a
move breaks the QC digest bindings and the delivery attestation built to notice
exactly that. A path rewrite, if ever wanted; until then such a run stays readable
where it is, because every driver takes explicit paths (run-dir-separation §5) ·
a rendered video **hand-copied among the footage** is still scanned — the run-dir
gate proves the run dir is not the footage dir, never that no `.mp4` beside the
clips is pipeline output, because an `.mp4` is an `.mp4`. Would need content
provenance at scan time (an attestation lookup, or a digest check against `out/`),
which is a slice and not a guard (run-dir-separation §6) ·
GitHub-remote marketplace (plugin-packaging §6) ·
a leaner plugin root and relocating the ~12 MB of weights out of the tree (plugin-runtime-resolution §6) ·
dependency **version** assertions in preflight (verify-runtime §9)

**Contact sheets**
a platform crop guide on each cell · a contact sheet of the delivered reel for CP3 · per-window multi-frame cells (contact-sheet §10)

## P4 — only on request

Real but low-value, or explicitly priced and found not worth it.

build **§6.1a layer 3** (descriptor continuity re-match) — deferred on measured
evidence, not on doubt that it is needed: the remainder over `stitch_ids` is real and
inverse, but seven real routes produced zero `continuity` failures and the shoot
offered one two-person opportunity, which did not swap. **Trigger:** a run producing
a `continuity` stop or an episode-QC `hero` finding naming a mid-episode swap
(deferred-measurements §2.5) ·
`checks.continuity` cannot see an ID switch between **adjacent** people — its
`4%-of-src_w` cap is a physically-impossible-teleport gate (4603 px/s on the run's
1920×1080@60 footage, the subject crossing frame in 0.42s), so a swap fires it only
when the two bodies are more than 4% of the frame apart. Nothing in code claims
otherwise; now nothing in the docs does either (deferred-measurements §2.4) ·
a per-episode mood override for the grade — the reel's grade is reel-level by
construction, exactly as its `look` is, and no request for it exists (mood-grade §8) ·
carry the measured phase margin on `MusicSpec` rather than only acting on it —
`_downbeat_phase` computes the winner-over-runner-up ratio and then discards it,
so a skill can say "this track has no bar grid" but never "and here is how close
it came". Not built because no consumer asked (downbeat-confidence §9) ·
`episode_qc pack --only <idx>` — re-packing all N episodes to re-judge one costs N
strip builds; measured at 8 episodes that is seconds, so this is convenience, not a
fix, and `pack` already preserves the `findings.json` being kept (re-judge §8) ·
no licence audit of the transitive dependency tree — the AGPL-3.0 declaration
(2026-08-17) was driven by ONE dependency checked by hand, `ultralytics`; nobody
walked the rest, and no lawyer read any of it (cheap-P2-chores §1.1) ·
`build_reel`'s reprocess loop stays sequential — batches are one or two culprits, so the fan-out's measured 1.70× has little to bite on (cap3 §9) ·
auto-sizing `jobs` from `cpu_count`, a GPU-aware cap, peak-memory measurement — no GPU box was available to measure (cap3 §9, intake-parallel §11) ·
caching CV intermediates and parallelising intake's Phase 2 (intake-parallel §11) ·
a user-tunable proxy scale beyond the fixed 960 (analysis-proxy §11) ·
per-track motion carried on `FootageWindow` (intake-motion-scoring §9) ·
multi-crop-per-track reID averaging (hero-reid §11) ·
per-part colour fidelity, skin vs gear, and an auto-fix for the advisory drift check (colour-stage §11, matchgrade §8) ·
a reference-episode tone target instead of the per-anchor median (matchgrade §8) ·
a check surface reading `TrackMeta.stitched`, and tuning the stitch thresholds — no synthetic case exists (track-stitch §8) ·
a vertical component for zoom (subject-anchored-moves §11) ·
a multi-plateau ramp, two slow moments in one shot (speed-ramp §13) ·
a true pitch-sweep whoosh, and per-episode SFX cues (sfx §9) ·
ducking-depth and SFX advisories in `check_reel` — the −14 LUFS hard gate already covers level (ambient §9, sfx §9) ·
per-track music feature caching, and ML-embedding mood (mood-match §9, sourcing §13) ·
merge-all-catalogs as the `any` default (sourcing §13) ·
draft-stage polish: creative crop/colour, ducked ambient, beat-accurate pacing, a segment cache, a standalone SKILL (assemble-draft §7) ·
gradient and auto-derived background colours (fit-solid §9) ·
the chroma-preserving vignette — a luma-plane blend or `geq` — if the corner
desaturation reads wrong on real footage; 26× the cost or a five-node graph,
for a difference that may be an improvement (cinematic-look §11.4/§12) ·
a per-episode look override — the reel's finish is reel-level by
construction, and no request for it exists (cinematic-look §12) ·
network reachability probes in preflight (verify-runtime §9) ·
cross-platform `setup.sh` and `bin/vg` — macOS/Homebrew is a stated project boundary (ffmpeg-baseline §9, plugin-packaging §4) ·
implementation plans must not hand a task a literal one-line `git commit -m` subject while the plan's own Global Constraints ask for a message that says *why* — five of this slice's six commits were generated exactly that way and shipped subject-only, and none of the five can be repaired now since amending is forbidden (shadow-red-length-reconcile, whole-branch review 2026-08-15) ·
a one-step re-render of a converged episode — `process_episode --route <frozen>` already skips tracking, so this is possible today, just not one command: the agent materializes the regraded manifest by hand (skill guidance, `edit-plan` colour-grade section) rather than a driver doing it in one call (frame-probe-look-gate §11) ·
`lookcheck.evaluate`'s vignette check reads only the MIDDLE of the three sampled mid-frames (`mid_master[mid]`/`mid_delivered[mid]`) — four of the six frames `_verify_look`/`probe_look` decode for it are never read, while the design's own §5/§6 cost tables price three frames as the unit of work (frame-probe-look-gate, whole-branch review) ·
`probe._render` does not dedupe frame numbers the way its sibling `assembly.frames_rgb` does (`uniq = sorted(set(nums))`) — two `times` that round to the same `n` make the `select` expression request that frame twice but ffmpeg emit it once, so `len(pngs) != len(nums)` fires the generic "a frame number is past the stream's end" message even though every requested time is well inside the stream (frame-probe-look-gate, whole-branch review) ·
no import-time assert that `probe._COLOUR_KEYS` is a subset of `Manifest`'s dataclass field names (filed at this slice's own Task 4 but never promoted to this file) — a colour field added to `EDLEpisode`/`edl.to_manifest_dict` later but forgotten from `_COLOUR_KEYS` is silently dropped by `regrade` (its drop-then-reapply reads only the named keys) rather than caught at import time; nothing machine-checks the set stays complete (frame-probe-look-gate, whole-branch review) ·
`ReelEpisode.path` defaults to `""` — a manifest entry missing it collapses `probe_grade`'s `epdir = Path(ep.path).parent` to `.` (cwd) and fails with an opaque `IsADirectoryError` out of `CropPath.from_json("")` (reproduced: `Path("").read_text()` raises `Is a directory: '.'`) rather than a named refusal pointing at the missing field (frame-probe-look-gate, whole-branch review) ·
`tests/lib/test_edit_plan.py` has a mid-file `from scripts.lib.pacing import Slot, Spine` (line ~250) — pre-existing and untouched by this slice, but every task that extended the file inherited the imports-at-top violation rather than fixing it in passing (pacing-fixed-point, Task 1 review) ·
when BOTH `Spine.music_digest` and `MusicSpec.track` are unreadable, `build_edl`'s logged `why` names only the spine ("this PACING.json records no music_digest") and never says the track was *also* unreadable — the fallback still runs correctly, only the diagnostic is incomplete (pacing-fixed-point, Task 3 review) ·
several new tests (`test_reel_orchestration.py`'s two outro-refusal tests, `test_check_reel.py`'s `test_an_unchanged_rung_reports_n_a_not_a_measurement` and `test_a_residual_past_the_reporting_tolerance_is_flagged_but_advisory`) still assert a subset of the returned object/detail rather than the whole thing, against this project's own whole-object-assert convention — inherited verbatim from the plan's literal test snippets, not an implementer choice; `test_the_residual_is_the_master_against_the_length_the_fit_asked_for` was fixed to a whole-`CheckResult` equality by the final review (pacing-fixed-point, Tasks 4/5 review; Finding 5)

## ⊘ Won't do

| Item | Why |
|------|-----|
| Face **recognition** for hero identity | Excluded by the montage design: faces are small, wet and turned away in this footage. **Not the same thing as the face *detector* the P3 hero-conditioned re-scan is blocked on** — that one only needs to find *a* face to say "this window has a person facing camera", and never matches one person against another. The identity work is what is refused here |
| A `verify_runtime --fix` that runs `setup.sh` | Rejected on principle — no autonomous system mutation (verify-runtime §4) |
| A signed rather than merely digested attestation | Pointless against a local adversary who holds the key (attested-run §12) |
| A per-episode `.attest.json` **sidecar** | Per-episode *binding* already exists and this row is not it — see the note below (attested-run §12) |
| Spotify `audio-features` for mood | Deprecated for new apps since Nov 2024 (sourcing §13) |
| A 4th "dynamism" mood axis | YAGNI — three axes already order the shortlist (mood-match §9) |
| The analysis proxy for delivery-time track/reframe | They run on short *original* segments; the proxy would cost fidelity for nothing (analysis-proxy §11) |
| Reducing the proxy's fps | Measured to break vidstab's inter-frame motion (analysis-proxy §8) |
| Re-tuning `_motion_fit` | Superseded — P3 slice S3 replaced the sensor and `score_window` outright rather than re-tuning them |

**Note on "per-episode attestation".** attested-run §12 deferred it on 2026-08-04
with the reason *"the reel is the delivered unit; episodes are intermediates"* —
true when written, and half-false four days later. episode-qc (2026-08-08) landed
`EpisodeVerdict.clip_digest`: the sha256 of each judged clip, **computed by
`episode_qc build` from the file on disk rather than taken from the judge's
claim**, a staleness gate that refuses when a verdict's digest no longer matches
the rendered clip, and an `episode_qc` block carried into the reel's
`REEL_v{n}.attest.json`. So an episode *is* bound to the pixels it was judged on.
What is still absent is only a separate attestation sidecar per clip, which buys
little on top of that — hence the row stays a won't-do, but under a reason that
is currently true. This one was caught by a reader of this queue on the day it
was written, which is the second stale-reason deferral the housekeeping audit
turned up after the three it set out to fix.

---

## Real-run findings — the #1–#20 list at a glance

The detail for each lives in [fixes-backlog.md](fixes-backlog.md); this is the
status column that file does not have.

| # | Finding | Status |
|---|---------|--------|
| 1 | Hero identity — colour-histogram descriptor → OSNet re-ID embedding | ✅ 2026-08-04 (the hero-conditioned re-scan remains, P3) |
| 2 | Music is cut in the middle of a phrase | ✅ 2026-08-14 — the outro-fit ladder (`lib/outro.fit_outro`, see the P1 row above) grows or shrinks the closing episode so the reel ends `bar_line + fade`; meter beyond 4/4, real section detection, an audio-hearing check, and fitting a ramped closing episode all stay open in P3 |
| 3 | Per-episode rendering and QC in subagents | ✅ 2026-08-08 |
| 4 | `setup.sh` installs everything; unavailable components warn and continue | ✅ 2026-08-04 |
| 5 | The authoring skill must document every modification tool it has | ✅ 2026-08-17 — 30 of `EDLEpisode`'s 35 fields were already named; the five that were not (`crop_aspect`, `crop_scale`, `border_px`, `border_color`, `color_means`) are documented, a reference table indexes all 35, and a test keeps the next one from going missing silently. The reverse scan found no named-but-missing tool |
| 6 | The router never asked about titles / effects | ✅ 2026-08-04 |
| 7 | Slow-mo is a first-class effect, and it changes the reel length | ✅ 2026-08-09 |
| 8 | Subagents must not be able to disable quality control | ✅ 2026-08-04 |
| 9 | Cinematic effects library + mood-oriented palettes | ◐ P1 look half ✅ 2026-08-13 (vignette + bookend fade, cinematic-look); P2 grade half ✅ 2026-08-17 (mood-grade — `MoodPreset.tone_bias` displaces the conductor's common target, riding the tone pair that already exists); P3 tail ○ open (incl. grain, measured and priced out) |
| 10 | Cheap 3-frame preview to converge the grade | ✅ 2026-08-15 — `probe.py grade` renders 3 frames through `reframe`'s own chain over the frozen route (≈5.7× against a track+encode attempt), and `deliver`'s look gate refuses a declared vignette/fade that never reached the pixels; titles pixel coverage and real-footage calibration stay open in P3 |
| 11 | Freeze the engine during a run | ✅ 2026-08-04 |
| 12 | "Look, don't guess" — examine real frames | ✅ both halves (2026-08-05 selection, 2026-08-08 per-episode) |
| 13 | A quality gate must not be bypassable by manual assembly | ✅ 2026-08-04 |
| 14 | Editorial-constraint memory across iterations | ✅ 2026-08-07 |
| 15 | CP3 reel-review must not be silently skipped | ✅ 2026-08-04 |
| 16 | `VERSIONS.md` note bug — path logged instead of the reason | ✅ 2026-08-04 |
| 17 | Frame-moving effects stay subject-anchored and inside QC | ✅ 2026-08-08 |
| 18 | Cinematic effects were born as live patches — land them, verify they show | ✅ 2026-08-13 — zoom ✅ 2026-08-08, ramp ✅ 2026-08-09, look filters (vignette + bookend fade) + `highlight_red` + `outline-bold` ✅ 2026-08-13 (cinematic-look), each with a measured visibility proof |
| 19 | Shot-type variety + brief fidelity | ✅ 2026-08-06 |
| 20 | Off-pipeline manual EDL editing | ✅ 2026-08-04 |

## Housekeeping — what the 2026-08-12 audit found and fixed

Four deferrals had left every list. Three were shipping as live defects.

| | Item | Landed |
|---|------|--------|
| ✅ | `platform` never reached the reel — the brief recorded it, `check_reel`'s safe-zone gate and `titles.y_exprs` both silently took the generic table | `EDL.platform`, carried by `edit_plan --spec` into `edl_to_reel` |
| ✅ | `EDLEpisode.smooth_window_s` could not be authored though `ReframeSpec` had the field — deferred by colour-stage §11, rediscovered by speed-ramp §9 | authored, and the retry ladder's lag branch now floors at the authored value instead of walking it back to 0.25 |
| ✅ | `draft.py` rendered an **8×16-pixel** video — it spent the canvas *aspect* as pixels. Two tests protected it: the unit test hand-passed the right pixels, and the integration fixture hand-wrote pixels where an aspect belonged | 8×16 → 606×1078, proven by probing the real output file |
| ✅ | `Spec.reel_count > 1` was accepted, printed as "3 reels", and produced one | refuses with the remedy; the field stays for the day fan-out lands |

All four landed 2026-08-12 on `chore/housekeeping-backlog`. The
`Delivery.dims(native)` trap is worth remembering: it returns `(even(w), even(h))`
and nothing else, so the obvious one-line fix for the draft would have reproduced
the same 8×16 output one call deeper.

Three pointers had gone stale and were corrected in the same pass: a "Phase F"
that never existed, a cv2 blocker that disappeared when the tracking ladder
landed, and three build-status entries about §6.1a layer 3 written as though
track-stitch had not shipped.

_Last updated: 2026-08-17._
