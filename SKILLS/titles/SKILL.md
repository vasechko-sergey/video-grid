---
name: titles
description: Stage 5.16 — the reel's on-screen text. Use after reel-brief (SPEC.json exists) to turn hook/text/ending into a timed, positioned titles track and write TITLES.json (+ TITLES.md), the on-screen text reviewed alongside the near-final reel at the CP3 checkpoint. Words, timing, position (top/center/bottom), style (bold-box/outline/plain), font — drawtext burns them into deliver's one encode, never a second pass. Optional: enriches the reel; the autonomous path runs without it.
---

# titles (stage 5.16)

Turn `SPEC`'s `hook`/`text`/`ending` into a timed, positioned **titles track** —
`TITLES.json`, the on-screen text `deliver` burns into the reel. This is the
**captioning of reels**: the words are already locked upstream, so this stage is a
mechanical starting draft plus room for your judgment — no ffmpeg here. The render
itself happens downstream, inside `deliver`'s one encode (5.14).

**Placement is your judgment.** `SPEC` already locked the words (reel-brief, 5.3);
your job is editorial — *when* each line appears, *where* (`top`/`center`/
`bottom`), in *what* `style`, in *what* `font`. The `titles` CLI turns those words
into a sensible starting draft; you never retype the hook/ending text by hand —
refining the draft's timing/position/style/font beyond that starting point is a
direct edit to the small `TITLES.json` it writes (no flag covers this — Procedure
step 3).

## Inputs

- **`SPEC.json`** (required, from reel-brief) — `hook` (gate, always set), `text`
  (optional mid-caption), `ending` (optional closing line). No `SPEC.json`, no
  titles: run reel-brief first, or skip this stage.
- **the reel length, in seconds** — sum `EDL.json`'s episode durations (its own
  `EDL.md` header already prints the total), or probe an existing master/draft
  (`draft.mp4`, a prior `out/REEL_v*.*`) with ffprobe. Whichever is at hand; never
  guess or hardcode it — `--total` drives every title's timing.

## Procedure

Announce on entry: **"Using titles to author the reel's on-screen text."**

1. **Recon.** Read `SPEC.json` — `hook`, `text`, `ending` are the words that
   belong on screen (they're locked already; you don't invent new copy here,
   that's reel-brief's call). Work out the reel length in seconds (Inputs,
   above) — the number `--total` needs below.
2. **Propose the titles.** For each line: its window (`start`/`dur`, seconds),
   `pos` (`top`/`center`/`bottom`), `style` (`bold-box`/`outline`/`plain`), and
   `font`. Default `font="system"` — it always renders, no setup required. Offer
   a named font (Montserrat / Inter / Bebas Neue / Oswald) ONLY if the user has
   run `bash setup.sh --with-fonts`; a named-but-uninstalled font is not a silent
   fallback — `deliver` fails loud instead (Landmines, below).
3. **Build.** Run the authoring script (explicit args; the user never types
   flags):

       python -m scripts.titles build --spec SPEC.json --total <reel-length-seconds> --out-dir <run-dir>

   `--spec`/`--total`/`--out-dir` are its only flags: it projects `hook`/`text`/
   `ending` straight into a **sensible starting draft** — hook opens top for its
   first ~2s, `text` (if set) becomes a bottom mid-caption around the midpoint,
   `ending` (if set) closes center over the last ~3s, all `font="system"`/
   `style="bold-box"` — and writes `TITLES.json` + `TITLES.md`. If that already
   matches your proposal, you're done. Otherwise — a different font, style, or a
   retimed window — there's no flag for it: tune `start`/`dur`/`pos`/`style`/`font`
   directly in the written `TITLES.json`, and leave `text` as the SPEC-sourced
   words (Gate). Editing this file by hand is deliberate, not a slip:
   `EDL.json`/`SPEC.json` stay hands-off because each is generated from a smaller
   upstream judgment file (`EDL.json` projects `selection.json`; `SPEC.json` is
   written from reel-brief's answers) — you edit that source and regenerate. Titles
   have no such upstream: `build_titles` emits only the fixed default above, so the
   placement judgment lives in `TITLES.json` itself — it *is* the source of record.
   Validate-on-load is the safety net (a bad edit fails loud at `deliver`, never
   silently), not the reason you may edit it.
4. **Review — CP3.** Titles are reviewed WITH the near-final reel, not
   standalone: show `TITLES.md` alongside `out/REEL_v*.*` and the `check_reel`
   report at the final-review checkpoint. On changes, edit `TITLES.json` (or
   re-run step 3 for a clean restart), then re-review.

## Gate

`TITLES.json` + `TITLES.md` written, every item's words sourced from `SPEC`'s
real `hook`/`text`/`ending` — never invented copy. `Title`/`Titles` validate on
every write and read: empty text, a negative/non-finite `start`, a `dur <= 0`, or
a `pos`/`style` outside the fixed enums all raise loud, naming the field and the
allowed set. A **font name** validates structurally the same way (non-empty
string) but is only *resolved* — checked against what's actually installed —
later, at `deliver` (Landmines, below).

## Hand-off

The render itself happens later, at `deliver` (5.14): pass `--titles
TITLES.json` to `edl_to_reel` — it threads the path to `build_reel` then
`deliver`, which burns the drawtext chain into the ONE encode it already runs. No
second pass, no titled intermediate file. Absent `--titles`, `deliver` encodes
exactly as it does without this stage.

## Landmines (design §12)

- `drawtext` needs an explicit `fontfile=` — there is no fontconfig default on
  macOS. `resolve_font` always supplies the path; a title never reaches the
  filtergraph with a bare, unresolved name.
- A **named** font (Montserrat / Inter / Bebas Neue / Oswald) must already be
  installed (`bash setup.sh --with-fonts`). `Title.font` accepts any non-empty
  string at write time — a typo'd or uninstalled name still writes cleanly — but
  `deliver` fails loud the moment it tries to resolve it, naming the missing font
  and the `--with-fonts` remedy. It never silently substitutes a different font
  (that would change the reel's look without telling anyone). Stick to the
  default `font="system"` unless the named set is confirmed installed.

## Boundaries

- **Optional stage, reel-level only.** `montage status` never points `next`
  here; the autonomous path (no `TITLES.json`) delivers a clean reel with no
  on-screen text — a complete, valid output on its own.
- **Depends on reel-brief** — without `SPEC.json` there are no locked words to
  author from. Run reel-brief first, or skip titles entirely.
- **No per-episode titles** — they render once, over the whole assembled reel,
  at `deliver`; they are not part of `process-episode`.
- **No animation, no karaoke, no per-word timing** — `drawtext` static windows
  only: a title is on, unchanged, for `[start, start+dur]`, then off.
