# The first real run — what six days of montage actually measured

**Date:** 2026-08-25
**Subject:** the 2026-06 surf shoot, 99 clips, delivered as `REEL_v2.mp4` (34.93 s)
**Corpus:** the session transcripts, **which are about to be deleted**

---

## 0. Why this document exists

Six days of real montage produced ~240 MB of session transcript and 1.09 GB of
artifacts beside 13 GB of footage. The operator is clearing all of it before the
next run, so this file is what remains. Every number below was re-derived by
streaming the raw JSONL; where a first pass got a number wrong, the wrong number
is recorded too, because the way it was wrong is itself a finding (§2).

**Corpus, for the record:**

| | |
|---|---|
| main transcript | 79 MB, 5488 records, 2026-08-19T06:32 → 2026-08-25T06:28 |
| subagent transcripts | 98 agents, 160 MB, all `general-purpose` |
| externalised tool results | 9 files, 464 KB |
| two minor transcripts | 336 KB (a `claude doctor` health-check), 20 KB (empty) |
| the project's `memory/` | **empty** |

---

## 1. What the run cost

**831 tool calls** — Bash 571, Agent 98, Read 90, SendUserFile 28,
AskUserQuestion 22, Skill 10, TaskStop 8, ToolSearch 3, SendMessage 1. Only
**13** results carried an error: nothing crashed. All friction was semantic.

**Stage invocations** (distinct Bash calls naming `scripts.<stage>`):

| stage | calls | | stage | calls |
|---|---|---|---|---|
| `edit_plan` | 91 | | `track` | 8 |
| `edl_to_reel` | 82 | | `montage` | 4 |
| `match_grade` | 40 | | `titles` / `reel_review` / `draft` | 2 each |
| `episode_qc` | 36 | | `intake` | 1 |
| `pacing` | 26 | | `contact_sheet` | 1 |
| `beats` | 24 | | **`probe`** | **0** |
| `process_episode` | 11 | | | |

The front half ran once and held. The back half — plan, render, judge, grade —
was ground through 91 / 82 / 36 / 40 times.

**`edl_to_reel` by phase:** 68 `--stop-after-episodes` (render all 8 episodes),
13 `--from-episodes`, 1 full run. So **14 delivering runs**, of which ~21 of the
69 episode-render rounds were pure colour iteration.

**Wall clock: 143.93 h span, of which 116.07 h (80.6 %) is human absence.**
Six gaps of 23.74 / 23.65 / 19.86 / 13.72 / 13.15 / 11.94 h, each closed by an
operator message. Machine-busy 22.49 h (15.6 %); render + judge together 11.36 h
(**7.9 % of the span**). The cost driver is not compute — it is the **number of
human-gated rounds**, six of which cost a night each.

---

## 2. The method correction: four of six first-pass hypotheses were wrong

A first pass over the same data produced six confident findings. An adversarial
re-reading killed four. This section exists so the next retro is run differently.

| first-pass claim | verdict | what was actually true |
|---|---|---|
| "no inspection surface — 346 of 571 Bash calls never touched the toolchain" | **refuted** | 100 of them *read pipeline artifacts* — the surface working. 89 are harness orchestration. The real residue is **56 calls grepping the product's own source** to find out what a tool does — a documentation gap, not a missing CLI |
| "mood does not bind episode length" | **refuted** | It binds, via `MoodPreset.asl`. The defect is the opposite shape — see R1 |
| "the score is deterministic, so re-runs always return the same pieces" | **refuted** | The run's own `selection.json` reaches rank **1338 of 1508**; **zero** of the top-8 scored windows are in the cut; 8 of 30 chosen windows are `best=False` |
| "six days because of the render→judge loop" | **refuted** | 80.6 % of the span is human absence (above) |
| "colour failed because the conductor measures the source frame, not the crop" | **refuted as the cause** | True as a fact, not as the cause — see R2 |
| "three purpose-built mechanisms were never called" | **survives, hardened** | `montage status/verify` was called 4×, not 1×. The other two survive and get worse — see R4 |

**The lesson.** Every refuted claim came from counting *shapes of activity*
instead of reading *what the activity achieved*. Counts locate a symptom; only
the artifacts say what caused it.

---

## R1. The mood vocabulary is four points, and "relaxed" silently orders a faded grade

`SPEC.mood` was *"light, summery, easy — sunlit morning surf, relaxed but
alive"*. It resolves to the **`nostalgic`** preset, pulled there by the word
*relaxed*. `nostalgic` carries:

- `asl = (2.0, 4.0)` — an average-shot-length band whose **4 s is a ceiling, and
  there is no floor in any preset**
- `tone_bias = (20.0, 0.0, -18.0)` — **+20 on shadows, −18 on highlights**: lifted
  blacks, faded

The operator's two loudest complaints across six days were *"the length kept
pulling toward two seconds"* and *"everything is washed out and the shadows are
gone"*. Both are the table doing exactly what it was told.

Every preset in the table ceils at ≤ 5.0 s:

| preset | asl band | tone bias |
|---|---|---|
| fun | 1.2 – 2.5 | +10 / +18 / +8 |
| epic | 1.5 – 3.5 | −16 / 0 / +16 |
| **nostalgic** | **2.0 – 4.0** | **+20 / 0 / −18** |
| moody | 2.5 – 5.0 | −18 / −16 / −8 |

**A calm reel with six-second shots cannot be expressed in this vocabulary**, and
a calm brief is routed to a faded look nobody asked for.

Corollary, measured: `variety` recorded the realized `asl = 4.37 s` — **outside
its own declared band** — and took no action.

---

## R2. Colour is measured, corrected and gated on whole-frame means

Five days of the six went to colour. The chain, end to end:

1. **The sources are not commensurable.** Drone `DJI_*`: `yuv420p`,
   `color_range=tv` (16–235). Camera `MVI_*`: `yuvj420p`, `color_range=pc`
   (0–255). Same bt709 primaries, transfer and space, same 1920×1080 at
   60000/1001 — **different range**. Nothing normalises them before comparison.
2. **`measure_profile` reads the raw source file** at full resolution with only
   `-vf format=gray` — no crop, no route, no range handling. `match_grade` feeds
   it `footage_root/<source>` directly, bypassing the `pc`-normalisation that
   `assembly` already implements (colour-stage §8/§9).
3. **`tone_arg` writes through `lutyuv` with `TV_LO=16, TV_SPAN=219`.** On the
   Canon's full-range material that treats 16 as black and 235 as white when the
   real values are 0 and 255 — everything above 235 collapses onto a constant.
4. **`color_across_cuts` compares whole-frame means.** On ep5, whose frame is
   mostly dark water, the correction lifted Lena's face to **156 luma — above her
   own ungraded plate**.
5. **The fidelity gate cannot see the damage.** `color_fidelity` scored a
   **28-code** shift as **0.8° of drift against a 25° threshold**; it returned
   `null` on 2 of the 8 shipped episodes and 129.4° on another — false negative,
   absent, and false positive — and every episode shipped with `overall: true`.
6. **So the ceiling was widened by hand**, 12 → 44 → **56**, to stop a correct
   complaint from firing.

**And the sensor that measures precisely the operator's complaint already exists
and already fired.** `lib/naturalness.py` measures blown highlights, crushed
blacks, colour cast and oversaturation. Its own header says *"Nothing here fails
an episode: the flags are advisory in both directions"*, and its thresholds are
*"first cuts … calibrate on the first real run that uses them."* On the shipped
reel it flagged **`colour_cast` on 7 of 8 episodes** and `blown_highlights` on
ep7. The first real run happened. Nothing was calibrated and nothing was stopped.

---

## R3. The crop cannot be seen before the encode is paid for

The operator's proposed order is: choose fragments (draft 1) → make crops
(draft 2) → tune colour on those pictures with no render → render last.

`probe grade` is the crop-accurate tool and it is the right one: it calls
`reframe.plan_render(spec, src, ep.route)` — literally the function the real
render calls — and hard-refuses if the recomputed path has drifted from the
frozen `path.json`. But its CLI requires `--episodes EPISODES.json`, which only
exists **after `edl_to_reel --stop-after-episodes` has encoded every episode**.

The seam is nearly there: `scripts.track` is a standalone CLI that produces
`route.json` (it ran 8 times). What is missing is a stage that takes
**source + route + the colour block** and emits stills, without `EPISODES.json`.

---

## R4. Built tools are not reached — and get rebuilt instead

`scripts.probe`: **0 invocations**. `CONSTRAINTS`: **0 mentions in 831 tool
inputs**, and no `CONSTRAINTS.json` on disk.

Neither is an availability problem. The plugin cache at version 0.2.0 was stamped
**two hours before the run began** and shipped both `probe.py` and
`constraints.py`; the `using-montage` skill text names **"no repeated
episodes"** as its own worked example and was in context at 06:37Z. The operator
stated exactly that rule at 08-20T04:33Z and again at 08-21T07:39Z — *"why has
the duplicate appeared again?"*

The agent did not merely skip these tools. It **outcompeted them**: 38 hand-rolled
frame grabs, 82 `edl_to_reel` runs, and a private colour laboratory of
**2.0 GB across 676 files** (511 PNGs, 49 Python modules) whose hand-written skin
sensor was wrong three separate ways — the mask caught red surfboards, skin was
re-detected on the already-graded frame, and the speed ramps de-synced the
before/after pair.

Two supporting measurements: **56 Bash calls grep the product's own source** to
learn what a tool does, and after one context compaction **12 of 13 `--help`
calls** fall in the following 2 h 17 min — and `probe` still was not found.

---

## R5. Reports do not bind to what they describe

`episode_qc` stamps a `clip_digest` from disk and refuses a stale verdict. It is
the one binding that held all week. Nothing else has one:

- `MATCH.md` claims *"8/8 episodes authored a tone pair"*; the `EDL.json` written
  an hour later carries **5**.
- `REVIEW.json` is **two days and two reel versions stale** — it reviewed a
  37.1 s reel; 34.93 s shipped — and was never re-run.
- **Three different reels were delivered as `REEL_v1.mp4`**, because
  `_next_version` counts `REEL_v*` files in `out/` and the workflow `rm -rf`s
  `out/` — **47 times** out of 64 `rm -rf` calls total.
- `VERSIONS.md` lives *inside* that same wiped directory: **14 delivering runs,
  2 surviving entries**, everything from 08-20 to 08-24 gone without a file, an
  attestation, or a log line.

---

## R6–R8. Reporting and selection

- **A passing check throws its measurement away.** `check_reel.py:180` assigns
  `worst` only inside the failure branch, so a passing `color_across_cuts`
  reports `{"pass": true}` and nothing else (`variety` is identical). The
  worst-junction delta was therefore re-derived by hand on three separate days.
- **Silent no-ops nobody was asked to read.** `MUSIC.json` carried `bars: []`, so
  the entire outro-fit feature reported `"n/a"` and did nothing. `vocal_spans`
  shows the reel both starts *and* ends inside vocals, against the operator's
  belief. `outro.brief_len 45.0` against `reel_dur 34.93` is **22 % short** and
  escalated nowhere.
- **The score contributed nothing to the cut.** Of 1508 windows, the selection
  reaches rank **1338**; **zero** of the top-8 are used; 8 of 30 chosen windows
  are `best=False`. Episode 0's own note records dropping rank #5 because a
  stranger in a white tee walked through it. `cull` only marks `best`, never
  deletes, so nothing was ever unreachable — but the CV time spent ranking bought
  no part of the delivered reel.

---

## R9. The run directory has no notion of lifetime

For an 8-episode reel, on disk: **17** `work/ep*` directories and **17**
`work/segments/ep*_raw.mp4`. Nine of each are from abandoned cuts and are
indistinguishable by name from the live ones.

Worse, there are **two competing per-episode metadata sets**: `work/ep0…ep16/`
(2026-08-25) and `work/reel/ep0…ep8/` (2026-08-21), same filenames
(`report.json`, `path.meta.json`, `storyboard.jpg`), **different content** — md5s
disagree. Nothing marks which is authoritative.

Total artifacts **1.09 GB** for a 33-second reel — `work` 592 MB, `out` 276 MB,
`sheets` 109 MB, `.intake_cache` 93 MB, `_review` 14 MB — and nothing is ever
cleaned.

---

## R10–R12. Ergonomics, infrastructure, and what the picture cannot do

- **The QC judge is nearly blind**: the evidence strip is **200×406 px per frame**
  with no zoom helper. Three judges reached for tools that do not exist in their
  harness; one hit `magick not found`. Judging is a *required* stage.
- **95 % of conveyor calls were piped through `tail`/`grep`/`head`**, twice losing
  the answer — once costing a 173-second re-render to read output that had
  already been produced.
- **QC has no "judge only what changed" and no memory between rounds**: ~14 rounds,
  **97 judges, 160 MB, for 8 episodes**, producing 2 blocking verdicts — one of
  them a false alarm from a stale evidence packet.
- **Infrastructure ate 16 of 98 subagents**: 11 killed by the Mac sleeping
  (episodes 0, 4 and 7 each needed three dispatches), 5 stopped deliberately. The
  operator hand-patched survival instructions into the brief.
- **The look layer is two knobs.** `LookSpec` carries a vignette and a bookend
  fade. There is **no grain** anywhere (measured and priced out in the
  cinematic-look design) and **no visual transition of any kind** — hard cuts
  only, while the audio side already synthesises whooshes on major cuts.

---

## What was looked for and NOT found

Recorded so the next retro does not re-spend the time: no rubber-stamped QC
verdicts (the judges did real pixel work); no judge-versus-judge contradiction on
identical bytes; no digest-binding failure — `episode_qc`'s binding held
throughout; no API or rate-limit trouble; no wasted polling; no second `intake`
or `contact_sheet` run; and no `process-episode` subagent at all.

---

## Rows this produced

29 backlog rows across R1–R12, filed in [../backlog.md](../backlog.md): 17 at P1,
11 at P2, and the run-directory restructure (R9) sized L and scheduled as its own
minor release. The single largest theme is R2 — one root, six mechanisms, five of
the six days.
