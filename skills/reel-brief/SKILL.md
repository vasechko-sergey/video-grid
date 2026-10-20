---
name: reel-brief
description: "Conveyor stage — the editorial brief: interrogate the idea one question at a time and write SPEC.md + SPEC.json (mood, hook, length, music intent, cast). Approved by the user at CP1. Optional — the autonomous path skips it. Conveyor position: after contact-sheet, before edit-plan. Tool index: references/tools.md."
---

# reel-brief (stage 5.3)

Turn a rough idea into a locked **reel brief** — `SPEC.md`, the editorial layer on
top of `project-init`'s machine subset. This is the **brainstorming of reels**: a
one-question-at-a-time dialogue, a hard gate before anything is written, and a
deterministic writer (you never hand-write `SPEC.md`). No ffmpeg here.

**The brief is judgment; the write is mechanical.** You collect the answers; the
`reel_brief` CLI validates them and renders both files. `canvas` is **not** yours to
choose — it comes from `project.json` (reel-brief FOLLOWS project-init); never
re-ask aspect.

## Inputs

- **`project.json`** (required, from project-init) — the canvas the brief inherits.
  If it is missing, run project-init first; reel-brief will not source aspect itself.
- **`cast.json`** (optional, from footage-intake) — real cast names to reference in
  the brief's `cast`. Absent → enter names free-hand.

**Launcher and references.** Run every pipeline step through the repo's launcher
`bin/vg`, never a bare `python`, and resolve every `references/…` read the same
way. `setup.sh` records the runtime's location at
`${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root`, so resolve it once:

    ROOT="$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root")"
    VG="$ROOT/bin/vg"

Then run every step as `"$VG" scripts.X`, read every reference as
`"$ROOT/references/…"`, and pass **absolute** paths for every footage / run /
output directory. Nothing here is relative to your working directory — a skill
runs from the user's footage project, not from the clone. If that file is
missing, the user has not run `bash setup.sh` — stop and say so rather than
guessing a path.

## Procedure

Announce on entry: **"Using reel-brief to lock the reel's SPEC."**

1. **Recon.** Read `<run>/project.json` (note the canvas) and `<run>/footage/cast.json` if present — they sit in different buckets: the project's canvas outlives every re-cut, the cast is a function of the footage.
2. **Ask one question at a time** — do not batch. Cover: reel count · platform ·
   target length (seconds) · mood · hook (the opening) · music (a track / "auto" /
   "none") + `music.mode` (local / free / any — default free, the safe distribution
   lane) · shot length · on-screen text · ending · cast.

   **Shot length** is its own question, asked in the genre's terms (quick cuts
   1–3 s · medium 3–6 s · whole actions 6–10 s), and the mood only *suggests* an
   answer. Once the mood is known, run

       "$VG" scripts.reel_brief hint --mood "…" --footage <run>/footage/FOOTAGE.json

   It prints the band that mood suggests (`suggested_asl`, `null` when no mood
   matched) and the shortest shot the footage can give (`carved`). Offer that
   suggestion beside your own estimate of how long one action runs — a ride, a
   wave — from the contact sheets you read, since nothing in `FOOTAGE.json`
   measures it. Record the user's answer with `--asl LO,HI`, the suggestion
   included when they take it, so it becomes their decision; omit `--asl` when they
   would rather not choose. A mood band nobody chose never refuses a build; a
   `--asl` floor under `carved` does.
   `hook` and `ending` describe **shots** for the editor; `--text` is the **literal
   words** the reel shows (the titles stage drafts exactly them) — ask for the
   exact wording, never record a description of it. When the reel has more than one
   hero, ask how screen time should split and record it with `--cast-share`
   (`equal`, or `NAME=WEIGHT` per hero) — not in `--notes`, which nothing reads:
   `edit_plan` reports the cut's screen time against it at CP2.
   **Platform** is the app (`reels` / `tiktok` / `shorts`, or the app's own name —
   "Instagram Reels" works); the brief stores the safe zone it resolves to and
   refuses a label no zone answers to. Leave it unset only when there is no app.
   Ask separately whether the music should be a **known** track (a hit, a popular song) or
   anything that fits the mood: `--music-known` — `--music-mode` is the licence lane
   only, and the second real run read "any" as rights and searched niche artists.
   Prefer the user's free text ("without music" → `--music none`; "any source" →
   `--music-mode any`). When the reel has music, ask whether the user will attach the
   track **in the app** (Instagram, TikTok, Shorts) — recommend it for the `any` lane,
   whose `yt-dlp` file can be muted when baked in — and record a yes with
   `--music-in-app`: deliver then also writes the reel without the song and a note
   naming the track and where the reel's music starts in it.
3. **HARD-GATE.** Do not write until **mood + canvas + length + hook** are locked.
   If any is vague, keep asking.
4. **Self-review** the assembled answers, then **build** (explicit args; the user
   never types flags):

       "$VG" scripts.reel_brief build --project <run>/project.json \
         --length 30 --mood "…" --hook "…" \
         [--reel-count 1] [--music …] [--music-mode free] \
         [--platform …] [--text …] [--ending …] [--cast NAME]... \
         [--cast-share equal | --cast-share NAME=WEIGHT ...] [--asl LO,HI] \
         [--music-known] [--notes …] \
         --out-dir <run>/reels/<reel>

   It validates the fields and writes `SPEC.json` + `SPEC.md`. A `ValueError` names
   the offending field — fix it and re-run; never hand-write `SPEC.md`.
5. **Review — CP1.** Show the user `SPEC.md` and get approval before edit-plan.

## Gate

`mood`, `canvas`, `length`, `hook` locked; `SPEC.json` + `SPEC.md` written. The
edit-plan agent reads `SPEC.md` as guidance (mood / hook / length / shot length).

## Boundaries

- **Optional stage.** The brief enriches the reel; the autonomous path runs off
  `project.json` alone. Run reel-brief when the idea deserves shaping.
- **No trend lane.** Trend scanning was removed on 2026-10-20 (no measured reach
  gain, a trend lives about five days and is regional, and no legal machine source
  exposes formats), and `style_lean` went with it — no code ever read it. An older
  `SPEC.json` that carries the key still loads. A wish for a popular song is
  `--music-known`, which sorts by catalogue popularity, never by "trending".
- **`reel_count` stays 1.** `Spec` refuses `reel_count > 1` outright — the field
  stays in the contract for the day multi-reel fan-out is built, but the CLI will
  not silently produce one reel for a brief that asked for more. If the user
  wants several reels, run the conveyor one reel at a time (a project directory
  per reel).
- **`tone_bias` is a brief-level colour field match-grade reads** (design
  2026-09-03 §2) — `Spec.tone_bias: tuple | None`, authored with
  `--tone-bias p5,p50,p95` (one comma-separated value, e.g. `--tone-bias
  20,0,-18`). Ask for it only when the user says something about colour; it is
  not one of the standing questions. **Omitting the flag and passing `0,0,0`
  are different answers, and the difference is the point:** omitted leaves it
  `None`, which takes the mood preset's own displacement, while `0,0,0` says
  *this mood, but leave my colour alone*. A malformed triple is refused by
  `Spec` with a message naming the value, so a typo stops the brief rather than
  reaching `match_grade`. Never hand-edit `SPEC.json` to add it — re-run
  `build` with the flag, the same rule as the line below.
- You never hand-edit `SPEC.json`/`SPEC.md` — the CLI regenerates them from answers.
