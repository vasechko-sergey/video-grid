# The second real run — what one afternoon of montage measured

**Date:** 2026-10-16 (written 2026-10-19)
**Subject:** a DJI drone shoot, 20 clips, 432 s of 1920×1080 at 59.94 fps, two
longboard surfers. Delivered as `REEL_v5.mp4` (45.66 s), approved by the operator
as final.
**Engine:** `216f535` (0.15.1), clean, the installed plugin up to date
(`verify_runtime` all OK).
**Corpus:** the session transcript (2356 records, 715 assistant turns, 29
subagents), the run directory `Downloads/1/montage/`, and the operator's own
remarks after reading the run.

---

## 0. Why this document exists

Since 2026-10-13 a backlog row enters only when a real run showed it or the user
asked for it ([development-workflow.md](../development-workflow.md#closing-a-slice--what-enters-the-backlog)).
This is that run. It answers the two "run 2" lists the backlog held, and it files
what the run showed — nothing else. It is also the data the post-run-2
simplification is decided from.

The method is the first retro's §2: every claim below was read off an artifact or
a transcript record, not off the shape of the activity.

## 1. What the run cost

**4 h 15 min wall, five deliveries.** The first reel (`REEL_v1`) was delivered
1 h 49 min after the first message — 1 h 21 min of it active, the rest the
operator away. Everything after was three re-cuts the operator asked for.

| Stage | Wall | Note |
|---|---:|---|
| project-init | 3 min | written into the footage folder first (§S10) |
| footage-intake | 14 min | 20/20 clips, 416 windows, 0 failed |
| cast naming | 15 min | 16 questions for 2 people (§S12) |
| contact sheet | 2 min | all 14 sheets read |
| reel-brief | 6 min | 14 questions, no complaint |
| edit-plan | 8 min | CP2 rejected: "rides of 2 seconds again" (§S5) |
| music + pacing | 11 min | track with no bar grid (§S7) |
| geometry, match-grade, probe, draft | 7 min | one legal gate stop (`lead` on a static subject) |
| titles, render, episode QC, deliver, review | 17 min | `REEL_v1`, then `v2` for a title fix |
| re-cut: the ending was not the heroine | 16 min | `REEL_v3` |
| re-cut: hero balance 55/45 → 50/50 | 15 min | `REEL_v4` (§S9) |
| re-cut: a track whose music ends on a bar | 64 min | `REEL_v5`; ~45 min of it the music search (§S8) |

A re-cut with full re-render, re-judging and re-review costs ~15 minutes; ~9 of
them are judges (§3).

## 2. What worked

- **The conveyor ran end to end without an engine fault.** The one stop was a gate
  doing its job: `composition-motion-mismatch` on an episode authored `lead` over
  a subject the tracker saw as static. The agent switched it to `center`.
- **Colour did not repeat run 1's complaint.** The brief asked "natural or faded"
  outright, the operator chose natural, `SPEC.tone_bias` carried `(0, 0, 0)`, and
  every reviewer round called the colour good.
- **`probe grade` was used** (run 1: zero times in 831 calls) and caught the
  conductor lifting the hook's silhouette from p5 38 to 60 — the agent pinned that
  episode's tone pair by hand (§S17).
- **The agent looked at pixels.** All 14 contact sheets; a frame strip of each
  candidate span before choosing it; a strip of the draft and of every delivered
  reel.
- **Zero questions spent arbitrating a sensor failure** (run 1: 8 of 22). All 36
  `AskUserQuestion` turns were cast names, the brief, checkpoints and music.
- **Run-1 ergonomics fixes held:** long output went to `logs/`, every render ran
  under `caffeinate -i`.
- **`reel-review` paid for itself every round** (§3).
- **The outro fit works when it has a bar grid:** `REEL_v5` ends on a bar line
  0.013 s off, under the `no-gap` rung's 1.5 s fade.

## 3. Episode QC and reel review — the simplification data

| | Runs | Wall | Found |
|---|---:|---:|---|
| per-episode QC judges | 25 (7 + 6 + 6 + 6) | ~10 min | one minor (a board tip touching the frame edge); 24 clean passes |
| reel-review | 4 | ~24 min | the woman in the ending was not the heroine; the black first frame; the title under the Reels header; the music cut mid-phrase; the 1:1 ending's layout jump |

The one real editorial error of the run — the "shared wave" ending showed a
stranger in a pink two-piece, not the heroine in her red one-piece — passed its
episode judge, whose brief named the episode's pinned hero (the man) and nothing
about the second person; the judge even described "a woman in pink" and passed.
`reel-review` caught it by comparing the frames against the cast reference crops.

Not used at all: `GATES.json`, `REGIONS.json`, `CONSTRAINTS.json`. The variety
gate could not fire (the footage offers close 0, medium 45, wide 371). The agent
read engine source about 13 times — `Delivery`, cast surfacing, mood presets,
titles, fonts, the beat tracker — each a question the docs did not answer.

## 4. The run-2 lists, answered

**What the run had to measure**

| Row | Answer |
|---|---|
| Calibrate the look | The vignette (0.25, `nostalgic`) drew no remark. The **fade** drew a remark in all four reviews: one value serves the picture's head, its tail and the audio (§S6). |
| Identity thresholds | Not yet computed. The data is on disk and the run gave a second data point: 15 candidates for 2 people, one hero split in two clusters and the other in three (§S12). |
| `SAT_DELTA_MAX` / `CONTRAST_DROP_MAX` | The run is the reel the row was waiting for — graded with `tone_bias (0,0,0)`, colour approved. Not yet measured. |
| `entropy_floor` | Still no real negative class: no episode damaged its grade. |
| Length band | Answered by genre: for longboard the operator wants whole rides of 6–10 s; the carved windows are 1.2–4.0 s, so every chosen episode is a span of 4–10 windows (§S5). |
| "Pull toward two seconds" | **Explained** (§S5). |
| `W_PRESENT` weights | Still unmeasurable: people in every window again, `present` separated 0 of 416. |

**What to watch the agent do**

| Row | Answer |
|---|---|
| R10.8 · a clean pass means "nothing I was told to look for" | Confirmed again, at lower cost: 24 clean passes of 25, and the one real error was outside every judge's brief (§3). |
| R8.2 · the pool was never widened | Answered: the contact sheet ran once, but frame strips ran for the selection and again for every revision (e.g. the replacement ending). |
| R10.12 · questions spent on sensor failures | Answered: 0 of 36. |
| R8.1 · the score bought nothing | Answered for this pool: 6 of the top 10 windows and 15 of the top 30 sit inside the delivered spans. The score is `motion` + `shake`; `present` contributes nothing here. |
| R10.5 · QC has no "judge only what changed" | Each re-cut moved every cut (pacing re-fits the grid), so every episode re-rendered and re-judging all of them was correct. 25 judges / ~10 min, not run 1's 97. What stays open is whether per-episode judging earns its place at all (§3). |

## 5. What the run showed — the rows

### P0 — ships wrong today

**S1 · A 9:16 reel from 1080p footage ships at 1080×1922.** `Delivery.dims`
derives the output height from the integer crop: the 9:16 crop of a 1080-tall
source is 607 px wide (607.5 rounded), and `1080 × 1080 / 607 = 1921.6` evens to
**1922**. Every `fill` episode came out 1080×1922 while the one `fit` episode came
out 1080×1920, and all five deliveries are 1080×1922. Run 1's 4K source divided
exactly (1215 × 2160 → 1920), which is why it never showed.

**S2 · `titles build` puts the brief's prose on screen.** Its draft copies
`SPEC.hook` / `.text` / `.ending` — editorial notes — into the title text
verbatim, file names and window numbers included: *"Лена силуэтом против солнца
идёт по доске… (DJI_20260403111456_0196_D.MP4, окна #26–29)"*. The agent noticed
and rewrote `TITLES.json` by hand.

**S3 · Music sourcing fails TLS out of the box.** Every Deezer request failed with
`CERTIFICATE_VERIFY_FAILED`. The agent recovered by prefixing every music command
with `SSL_CERT_FILE="$(python -c 'import certifi; print(certifi.where())')"` —
on every call, for the rest of the run.

**S4 · The Reels safe zone lets a top title sit under the app's header.**
`safezones` gives `reels` a top margin of 8%, so `pos: top` lays a title at
y 151–357 of 1922. All four reviews flagged it, citing Meta's guidance of about
14% at the top; with only `top`/`center`/`bottom` the agent could not move it.
First step: check the table against Meta's published Reels guidance.

### P1 — what the operator complained about

**S5 · The plan cuts long rides into 2–4 s pieces — "rides of 2 seconds again".**
The first EDL had 13 episodes at an ASL of 3.33 s; the operator rejected it at
CP2 and the agent rebuilt it at 5.5–9 s. The brief resolved "calm" to the
`nostalgic` preset, whose `asl` band is 2.0–4.0 s; that band is "reported, not
enforced", yet the agent sized every span to it — while the operator had chosen
the style *"Classic: clean cuts, long takes"*, which no field connects to shot
length. This explains the run-2 row: mood-contract §0.4 ruled the preset band out
by measuring the run-1 reel's delivered median (4.10 s) — a reel already
lengthened after the operator's complaints. The pull lives in the first plan,
not the last one.

**S6 · One fade value serves three ends.** `LookSpec.fade` (0.80 s from the
preset) fades the picture in, fades it out, and is the audio's bookend fade. So
the hook's first frame is black (YAVG 16 at t=0; all four reviews), and with no
bar grid the music's own ending gets only 0.8 s. Nothing can set them apart.

**S7 · Without a bar grid the music ends mid-phrase.** The chosen track had no
bar grid (the downbeat gate refused it), so the outro fit stayed `unchanged` and
the reel cut the song mid-phrase; three reviews in a row called it important. In
the follow-up search, by the agent's count, 6 of 32 candidates had a bar grid —
on calm music the gate refuses most tracks, so a fallback ending is needed, not a
track swap. The swap cost 64 minutes.

**S8 · The music search finds niche tracks, not known ones — "again".**
`music_find` queries the catalogs with a mood string, so they return mood-tagged
tracks, and it ranks by mood fit alone; Deezer's `rank` and YouTube's view count
are available and unused (`music-source` defers trend presence to trend-scan).
The brief's answer "any" became the licence lane `music_mode=any`; nothing asks
whether the operator wants a known track. Two more gaps in the same hour: no
preview of the exact window that will play under the reel (the agent cut 45 s
excerpts with ffmpeg; the Deezer preview links expire in an hour), and the agent
re-raised music rights the brief had settled.

**S9 · "Both heroes equally" was never checked.** The brief's answer is free text
in `SPEC.notes`; `EDL.md` shows no screen time per hero, though every episode
carries `hero` and a played length. `REEL_v3` shipped 55/45 (24.7 s / 20.4 s);
the agent computed it only when the operator asked, and `REEL_v4` re-cut it.

**S10 · `project.json` was written into the footage folder.** The run began with
`/video-grid:project-init`, whose skill says `--project-dir <dir>` without naming
`<footage>/montage`; the agent passed the footage root. `using-montage` later
re-wrote it under `montage/`, diffed the two and deleted the first. `project_init`
lacks the refusal `intake`, `draft` and `edl_to_reel` already carry.

**S11 · `VERSIONS.md` cannot tell one version from another.** All five lines read
`- vN | 2026-10-16 | delivered from EDL.json`. The #16 fix replaced the log's own
path with a constant default; `edl_to_reel --changelog` exists, and no skill
mentions it.

**S12 · Cast naming costs 16 questions for 2 people.** 15 candidates: the man
split into 2 clusters, the woman into 3, and 10 background figures of 43–88 px.
The candidate sheet was too small to recognise anyone (*"the pictures are tiny"*)
and the agent wrote its own card renderer. Ties to the identity-threshold row.

**S13 · Titles cannot carry an icon.** The brief asked for a map pin and a
calendar before the place and date. The agent downloaded Noto Emoji from GitHub
and merged it into Montserrat with its own fontTools script.

### P2 — friction

**S14 · The judge and reviewer prompts are filled by hand.** `episode_qc pack`
and `reel-review` leave template placeholders; the agent wrote
`fill_qc_prompts.py` and `fill_review_prompt.py` to fill them.

**S15 · `reel_brief` accepts any platform string.** "Instagram Reels" was stored,
and `edit_plan` judged against the generic zone until the agent re-ran the brief
with `reels`.

**S16 · Two small refusals.** `crop_aspect "1:1"` is refused (only `[1, 1]` is
legal), and `music_find --out-dir` does not create its directory.

**S17 · The conductor lifts an intentional silhouette.** match-grade measured the
backlit hook at p5 38 and authored a pair to the reel target of 60; the agent saw
it in `probe grade` and froze the episode with an identity pair. Today that takes
the agent noticing.

---

## Rows this produced

17 rows, filed in [../backlog.md](../backlog.md): 4 at P0, 9 at P1, 4 at P2.
Five run-2 rows closed and two folded into new rows; the rest stay open with
this run's answer recorded.
