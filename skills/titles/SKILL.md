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
   `font`. Default `font="system"` — it always renders, no setup required. A
   named font (Montserrat / Inter / Bebas Neue / Oswald) needs the curated set,
   which `bash setup.sh` installs as baseline; a named-but-uninstalled font is
   not a silent fallback — `deliver` fails loud instead (Landmines, below).
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

## Motion & colour

Six more `Title` fields — `fade`, `reveal`, `reveal_step`, `color`, `scale`,
`line_spacing` — go beyond the static on/off window `build_titles` drafts.
Every one defaults to that historical behaviour (a hard cut on, then a hard
cut off, white text at the default size), so an existing `TITLES.json` — or
one `build_titles` just wrote — renders unchanged. Sizing them is your
judgment, same as `pos`/`style`/`font`: there's no flag for it, you set them
by editing `TITLES.json` directly (Procedure step 3).

- **`fade`** — seconds to ramp opacity in AND out (default `0.0`, a hard
  cut). Both ramps sit inside the one `[start, start+dur]` window, so
  `2 * fade` must not exceed `dur` — past that the in-ramp is still
  climbing while the out-ramp already falls, and the title never once
  reaches full opacity. A `Title` that crosses this line is REFUSED at
  load, naming the largest `fade` that still fits `dur`.
- **`reveal`** — `"none"` (default: one static layer), `"word"` (one word
  at a time, each landing at its FINAL position so later arrivals never
  shove earlier ones sideways), or `"stair"` (the same, plus every step
  also drops a line, staircase-style). `"word"` splits `text` on
  **spaces**; `"stair"` splits on **newlines** — you group the words into
  lines yourself, e.g. `"salt,\nsun\n& you"` is three stair steps, not
  three words.
- **`reveal_step`** — seconds between one step's entrance and the next
  (default `0.35`; ignored when `reveal="none"`). Must be a positive
  number.
- **the reveal fit rule.** With `reveal` set, the last step must still
  fully arrive, hold, and leave inside the window — otherwise the one
  thing a reveal builds up to (the whole line, complete, at least once)
  never happens:

      (#steps - 1) * reveal_step + 2 * fade <= dur

  `#steps` is the word count for `"word"`, the line count for `"stair"`.
  Fail this and the `Title` is REFUSED at load (naming the seconds it
  needed against the window it got) — never silently compressed. Fix it
  by shortening `reveal_step`, shortening `fade`, lengthening `dur`, or
  trimming the text to fewer steps.
- **`color`** — any drawtext colour: a name (`"white"`, `"gold"`),
  `0xRRGGBB`, or either with `@alpha` (`"yellow@0.9"`, `"0xFFD700@0.9"`).
  Must be non-empty; ffmpeg is the one that actually parses it, so a typo'd
  colour surfaces at `deliver`, not here.
- **`scale`** — multiplies the default fontsize (`h/18`); a number in
  `(0, 5]`.
- **`line_spacing`** — multiples of the font size between staircase
  lines, a number in `[0.5, 3]` (default `1.15`). Tighten it for a script
  face, whose own letterforms already read tall.

A faded, word-revealed hook — copy this `Title` into `TITLES.json`'s
`items` list and adjust `text`/timing to fit your reel:

    {
      "text": "One more summer with you",
      "start": 0.0,
      "dur": 3.5,
      "pos": "top",
      "fade": 0.25,
      "reveal": "word",
      "reveal_step": 0.3,
      "color": "0xFFD700@0.9"
    }

Check the math before saving it: 5 words means 4 gaps between entrances —
`4 * 0.3 + 2 * 0.25 = 1.7s`, inside the `3.5s` `dur` (the reveal fits), and
`2 * 0.25 = 0.5s` is inside `3.5s` too (the fade fits). `font`/`style`/
`scale`/`line_spacing` are left at their defaults (`"system"`/
`"bold-box"`/`1.0`/`1.15`).

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
  installed (`bash setup.sh`, which installs the curated set as baseline).
  `Title.font` accepts any non-empty string at write time — a typo'd or
  uninstalled name still writes cleanly — but `deliver` fails loud the moment it
  tries to resolve it, naming the missing font and the installer remedy. It
  never silently substitutes a different font
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
- **No continuous motion, no karaoke fill, no per-character reveal.** `fade`
  (opacity) and `reveal` (`word`/`stair`, Motion & colour above) are the two
  animations on offer, each still built from `drawtext`'s static layers —
  nothing slides across the frame, no letter lights up mid-word, and a
  Title's `color` is fixed for its whole window; every layer is on,
  unchanged, for its own `[appears, end]`.
