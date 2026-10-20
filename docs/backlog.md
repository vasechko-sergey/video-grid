# Backlog — the queue

**This is the only document that holds priority.** Everything else records
*reasoning* (each design), *history* ([build-status.md](build-status.md)) or
*stage status* ([pipeline-map.md](pipeline-map.md)).

> **The rule (since 2026-10-13):** a row enters only when a real run showed it or the
> user asked for it. A design's `§Deferred`, its honest limits and a reviewer's
> Minor findings stay where they were written. A deferral that ships a wrong
> result *today* is the one exception — a live defect, filed at once as P0.
> Why: [development-workflow.md](development-workflow.md#closing-a-slice--what-enters-the-backlog).

A row that closes leaves for [backlog-closed.md](backlog-closed.md) with its
closure note. Everything filed under the old rule — every P3 and P4 entry as of
2026-10-13 — sits in [backlog-parked.md](backlog-parked.md): kept, not deleted, and not
a queue. Reopen a parked entry only when a run shows it.

| | |
|---|---|
| **Status** | `○` open · `◐` partial · `✅` done · `⊘` won't do |
| **Size** | `S` a task or two · `M` a slice · `L` several slices |

A P0 row means something ships wrong today and interrupts everything below.
Rows S1–S17 come from the second real run — evidence and measurements in
[retro 2](retro/2026-10-16-second-real-run.md).

---

## P0 — ships wrong today

**P0 is empty** — S1–S4 closed 2026-10-19 (0.15.2), see the archive.

## P1 — the reel: what the operator asked for, or every review flagged

| | Item | Size | Source |
|---|------|------|--------|
| ○ | **U2 · Shot length is a recommendation, not a mood rule** — the brief's shot-length question shows what the mood suggests and how long the footage's actions run, and the answer is recorded as `SPEC.asl`; a mood's band never refuses a build (`reconcile_band` becomes a log line for it) and only a band the user chose can. | S | user, 2026-10-20 |

## P2 — friction

S14–S17 closed 2026-10-19 (0.21.2, 0.22.0), see the archive.

| | Item | Size | Source |
|---|------|------|--------|
| ○ | **U3 · A music-less delivery plus a sound note** — a second delivery with the track removed and the ambient bed re-mixed (today it is ducked against the music, so cutting the music leaves it pumping to a song that is not there, and −14 LUFS would lift wind noise), plus a note naming the track, the start offset and the length, so the licensed sound is attached in the app. Why: rights, not trends — a `yt-dlp` track baked into the file can be muted; the second run's reel is exactly that case. This is the parked §5.14 row. | M | user, 2026-10-20 |

## Photos — asked 2026-10-20

From the photo-reel research of 2026-10-20: photos are a main material of memory and travel reels, and in 2025–2026 they move. Order: U4+U5+U6 is the first slice, U7+U8 the second, U9 the third; U10 waits for a real run with photos.

| | Item | Size | Source |
|---|------|------|--------|
| ○ | **U4 · Ingest photos** — intake sees HEIC/JPEG (it scans only `.mp4/.mov/.m4v/.avi` today, so photos are skipped silently); EXIF and HEIF orientation, ICC/Display P3 → sRGB (ffmpeg ignores ICC without `iccdetect`), the SDR base of an HDR gain-map photo, a size cap; a still becomes a clip on the exact contract of a video segment (fps, timebase, SAR, pix_fmt, range, matrix). Declare `opencv-python`, which arrives only through ultralytics today. | M | user, 2026-10-20 |
| ○ | **U5 · Fit a photo to 9:16 by its subject** — YOLO on the still gives the subject box; a portrait photo fills, a landscape one fits with a background. No consumer tool documents how it does this, and the engine already tracks subjects. | S | user, 2026-10-20 |
| ○ | **U6 · A sub-pixel Ken Burns** — a float warp rendered in Python and piped as rawvideo instead of `zoompan`, whose crop is truncated to whole pixels and stair-steps on a still; log-scale zoom with eased ends, toward the subject, 5–10 % by default. The same renderer removes the integer residual of today's video zoom. | M | user, 2026-10-20 |
| ○ | **U7 · A photo's length comes from the music grid** — holds in whole beats, deliberately varied, accelerating into a drop. The inverse of video, where the footage owns the length. | M | user, 2026-10-20 |
| ○ | **U8 · Photos among video, and choosing which** — one segment contract, a freeze-frame with a shutter accent, burst and near-duplicate grouping (pHash exists) before ranking. | M | user, 2026-10-20 |
| ○ | **U9 · Live Photos and Motion Photos** — pair an iPhone still with its MOV by `ContentIdentifier` (today the MOV enters as an unrelated 3-second clip), slice an Android Motion Photo's embedded MP4 by `Item:Length`; ~1.5 s of real motion around the still. | M | user, 2026-10-20 |
| ○ | **U10 · Polaroid, cards, collage** — an asymmetric frame, a shadow, a rotation and grids; lower value, and the look reads as a template. After a real run with photos. | M | user, 2026-10-20 |

## Still waiting on a run

Run 2 answered what it could ([retro 2](retro/2026-10-16-second-real-run.md) §4); these need data it did not have.

| | Item | Size | Source |
|---|------|------|--------|
| ○ | **Calibrate the look** — `LOOK_VIGNETTE_MAX` (0.6), the 0.55/0.45 plateau/falloff split, and every row of `MoodPreset.look` are hand-picked on synthetic test patterns; no real footage has graded against them yet. **Run 2 (2026-10-16):** the vignette (0.25) drew no remark; the fade drew one in all four reviews — now row S6. | S | cinematic-look §11.3/§12 |
| ○ | **Calibrate the first-cut identity thresholds** — `CAST_MATCH` / `CLUSTER_COS` / `MAX_CAST` are declared guesses; the distance distribution needed to derive them is already on disk in any real cache. **Run 2 (2026-10-16):** **measured 2026-10-19: no threshold can separate this run's two people** — the OSNet descriptor tracked viewpoint more than person: the closest man/woman pair (the two largest crops, face-on) sat at a cosine DISTANCE of 0.13, while the man's own front and back sat at 0.25 and the woman's angles at 0.16–0.21 (the other man/woman pairs 0.14–0.38). Calibration needs footage where the descriptor carries identity at all; until then the human's naming is the identity, and the skill says so. | S | hero-reid §11, cast-hero-pin §11 |
| ○ | **Re-derive `SAT_DELTA_MAX`/`CONTRAST_DROP_MAX` on a run whose baseline is not the complaint.** Both bars are set to zero false positives against the shipped reel — the very "washed out" run the operator complained about — so they are, if anything, too loose. **Unblocked 2026-09-03**: R1.1 shipped, so a mood no longer orders a grade silently and a reel graded without one is now authorable (`--tone-bias 0,0,0` keeps the mood and leaves colour alone). What is still needed is the reel itself. **Run 2 (2026-10-16):** this IS the reel the row waited for (graded with `tone_bias (0,0,0)`, colour approved) — not yet measured. | S | [grade-delta-sensors](specs/2026-08-28-grade-delta-sensors-design.md) §9.4 |
| ○ | **Re-derive `entropy_floor` on a run whose negative class is real footage, not synthesized knob extremes.** `CheckSpec.entropy_floor = 0.90` is measured against two real classes — eight shipped episodes and eight synthesized conductor pairs — but its NEGATIVE class (six deliberate damages at legal knob extremes) is entirely synthetic, so the floor's 1.2% margin (design §0.4) has never been tested against a grade an author actually pushed too far, only against ones pushed there on purpose for the measurement. Blocked on a run graded after R1.1 (mood no longer silently ordering a grade), so the run's own damaged episodes, if any, are a real negative class rather than noise from an unrelated defect. **Run 2 (2026-10-16):** still no real negative class — no episode damaged its grade. | S | [grade-sensor-references design](specs/2026-08-31-grade-sensor-references-design.md) §10 row 1, §9.1 |
| ○ | **Re-derive `W_PRESENT`/`W_MOTION`/`W_STABLE` against a pool where presence varies.** The three weights are first cuts calibrated on one drone shoot, and the largest of them (`W_PRESENT`, 0.44) separated **3 windows of 1508** on the only real pool — which shows the term is currently harmless, not that it is well-weighted. Re-weighting needs a pool with real presence variance, which does not exist yet. **Run 2 (2026-10-16):** still unmeasurable — people in every window again, `present` separated 0 of 416. | S | [unmeasured-named design](specs/2026-09-10-unmeasured-named-design.md) §7 |

## Decide from run 2 — simplification

| | Item | Size | Source |
|---|------|------|--------|
| ○ | **R10.8 · A judge's "clean pass" means "nothing I was told to look for".** Coverage tracked the prompt, not the episode: an episode passed clean, one sentence was added to the brief, and the next judge found something. **Run 2 (2026-10-16):** 24 of 25 judges passed clean; the run's one real error (a stranger in the ending) was outside every judge's brief and `reel-review` caught it — [retro 2](retro/2026-10-16-second-real-run.md) §3. | M | [retro](retro/2026-08-25-first-real-run.md) R10 |
| ○ | **R10.5 · QC has no "judge only what changed" and no memory between rounds** — ~14 rounds, **97 judges, 160 MB, 8 episodes**, two blocking verdicts, one of them a false alarm from a stale evidence packet. **Run 2 (2026-10-16):** each re-cut moved every cut, so re-judging all was correct: 25 judges, ~10 min. Open question is whether per-episode judging earns its place beside `reel-review` (4 runs, ~24 min, every important finding). | M | [retro](retro/2026-08-25-first-real-run.md) R10 |

## After run 2 — the picture

The only rows that make a reel look better rather than make the tool more sure
of itself.

| | Item | Size | Source |
|---|------|------|--------|
| ○ | **R12.1 · A film look: grain, gate weave, a soft edge falloff.** The look layer today is two knobs — a vignette and a bookend fade. Grain was measured and priced out in the cinematic-look design; unfreeze it. | M | [retro](retro/2026-08-25-first-real-run.md) R12 |
| ○ | **R12.2 · Visual transitions between episodes.** Hard cuts only today; the audio side already synthesises whooshes on major cuts and has no picture counterpart. | M | [retro](retro/2026-08-25-first-real-run.md) R12 |
| ○ | **R12.3 · Survey what effects are worth having, and encode WHEN to apply each.** `MoodPreset.look` is the routing hook that already exists and should carry it — otherwise this repeats the `probe grade` story: built, shipped, never reached. | M | [retro](retro/2026-08-25-first-real-run.md) R12 |

## ⊘ Won't do

| Item | Why |
|------|-----|
| Face **recognition** for hero identity | Excluded by the montage design: faces are small, wet and turned away in this footage. **Not the same thing as the face *detector* the P3 hero-conditioned re-scan is blocked on** — that one only needs to find *a* face to say "this window has a person facing camera", and never matches one person against another. The identity work is what is refused here |
| A `verify_runtime --fix` that runs `setup.sh` | Rejected on principle — no autonomous system mutation (verify-runtime §4) |
| A signed rather than merely digested attestation | Pointless against a local adversary who holds the key (attested-run §12) |
| A per-episode `.attest.json` **sidecar** | Per-episode *binding* already exists and this row is not it — see the note below (attested-run §12) |
| Spotify `audio-features` for mood | Deprecated for new apps since Nov 2024 (sourcing §13) |
| A trend scanner (TikTok Creative Center, a cached `TRENDS.md` of style directives) | No measured reach gain, a ~5-day regional life, no legal machine source for formats (user decision, 2026-10-20 — U1 removes what was built for it) |
| 2.5D parallax on photos | Three new heavy dependencies (depth, mask, inpainting) for an effect that peaked in 2021, with halo and stretch artifacts that only a motion too small to read hides; only Depth Anything V2 Small is licence-clean; iOS 26 does it on the phone (user decision, 2026-10-20) |
| AI image-to-video for photos | About an hour per 2 s on an M1 Max, and the licence-clean model (Wan) is the slowest (2026-10-20) |
| Stop-motion from burst photos | Little value; no 2024–2026 evidence the format is used (2026-10-20) |
| A 4th "dynamism" mood axis | YAGNI — three axes already order the shortlist (mood-match §9) |
| The analysis proxy for delivery-time track/reframe | They run on short *original* segments; the proxy would cost fidelity for nothing (analysis-proxy §11) |
| Reducing the proxy's fps | Measured to break vidstab's inter-frame motion (analysis-proxy §8) |
| Re-tuning `_motion_fit` | Superseded — P3 slice S3 replaced the sensor and `score_window` outright rather than re-tuning them |
| Re-picking `MUSIC.start_offset` at the back-edge (length-retime §9) | **Measured dead 2026-08-14** and superseded by the "whole-spine re-fit across in-point candidates" row in P3: the shift the 2026-08-03 reel needed was 2.235 beats, and only a whole-*beat* shift keeps the existing cuts on the grid (two beats leaves the end 0.128s off; a whole-*bar* shift maps the grid onto itself and changes nothing). Kept as a row so nobody re-derives it (music-outro-fit §0) |

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

_Last updated: 2026-10-19._
