# Titles stage design — hook / ending / caption render + font library

**Status:** design · 2026-07-13
**Depends on:** reel-brief (§5.3, `Spec.hook/text/ending`), reel back-half
(`deliver` = one encode, §5.14), draft (`scripts/lib/draft.py` `resolve_font` +
the explicit-`fontfile=` landmine).
**Related:** §5.13 `reel-final-check` safe-zones (built 2026-07-16 — titles now
resolve their margins from the same `SafeZone` table via `safezones.default_zone()`).

> **Amended 2026-10-19 (retro 2026-10-16 S2).** §1's premise is wrong for two of its
> three fields: `hook` and `ending` name the opening and closing **shots** — notes for
> the editor — and the second real run's brief carried source file names and window
> numbers in them, which the §4 draft then put on screen. `build_titles` now drafts
> only `Spec.text`, the literal words, as one title opening the reel at the top for
> its first 3 s, and nothing when `text` is empty. The text below is history.

## §1 · Intent

`Spec` already captures the words that belong on screen — `hook` (gate), `text`,
`ending` — authored at CP1 (§5.3). What is missing is a stage that **renders**
them into the reel. This adds one:

- a typed `TITLES.json` contract, agent-authored from `SPEC` (judgment: which
  words, when, which style/position/font);
- a `drawtext` render **injected into `deliver`'s single encode** (§5.14 keeps
  one encode — `drawtext` cannot ride `-c copy`, so titles bake into the encode
  `deliver` already runs, never a second pass);
- an **opt-in curated font library** (`setup.sh --with-fonts`) with
  resolve-by-name, so a reel can use nice fonts (Montserrat/Inter/…), not only
  the system default.

Scope is deliberately narrow: `drawtext` only — **no** libass/ASS, animation,
karaoke, or per-word timing (see §6). Font install is **macOS-only for now**
(the same cross-platform TODO as `setup.sh`).

This folds in the currently-uncommitted font-guard fix (the DejaVu fallback the
guard installs when no system font is present) — that becomes the floor of the
same font subsystem.

## §2 · Contract — `scripts/lib/titles.py` config-specs

Mirrors `EDL`/`Spec`: frozen dataclasses that validate in `__post_init__` and
fail loud (`ValueError` naming the bad value + the fix), plus JSON + markdown.

```python
POSITIONS: tuple[str, ...] = ("top", "center", "bottom")
STYLES: tuple[str, ...] = ("bold-box", "outline", "plain")

@dataclass(frozen=True)
class Title:
    text: str
    start: float                 # seconds, >= 0
    dur: float                   # seconds, > 0
    font: str = "system"         # "system" -> the resolve_font default; else a name/path (§5)
    pos: str = "bottom"          # one of POSITIONS (safe-margin preset)
    style: str = "bold-box"      # one of STYLES
```

- `__post_init__` gates: `text.strip()` non-empty; `start >= 0`; `dur > 0`;
  `pos in POSITIONS`; `style in STYLES`; `font.strip()` non-empty. Each raises
  `ValueError` with the offending value and the allowed set / remedy.
- `Title.to_dict` / `from_dict`.

```python
@dataclass(frozen=True)
class Titles:
    items: tuple[Title, ...] = ()
```

- Empty `items` is legal — an explicit "no titles" (deliver no-ops). Overlapping
  time windows are legal (two titles at once, different positions) — no overlap
  gate.
- `from_json` / `to_dict` / `write`; `to_markdown()` renders a preview table
  (#, text, `start→start+dur`, pos, style, font) for the CP.

## §3 · Authoring — `scripts/titles.py` + `titles` SKILL

Judgment is the agent's; the code is thin (mirrors reel-brief).

- `build_titles(spec: Spec, total_s: float) -> Titles` — a sensible **starting**
  draft: hook at `[0, 2.0]` `pos="top"`; if `spec.ending` → a closing title at
  `[max(0, total_s - 3.0), total_s]` `pos="center"`; `spec.text`, when present,
  as a mid caption the agent re-times. `total_s` (reel length) comes from the EDL
  sum or a probe of the assembled master — `build_titles` does not guess it.
  Default `font="system"` so the draft always renders without `--with-fonts`.
- CLI `titles.py build --spec SPEC.json --total <s> --out-dir <dir>` — writes
  `TITLES.json` + `TITLES.md`, prints JSON, `SystemExit(0)`.
- `titles` SKILL (autonomous-draft, like edit-plan): read `SPEC.hook/text/ending`,
  propose titles (words / timing / pos / style / font), write the pair, surface
  `TITLES.md` at the reel-review checkpoint for approval.

## §4 · Render — `scripts/lib/titles.py :: build_filterchain`

```python
def build_filterchain(titles: Titles, work_dir: str, resolve=resolve_font) -> str: ...
```

- One `drawtext` per `Title`, comma-joined:
  - `fontfile='<resolve(title.font)>'` — explicit path (the §12 landmine); a
    resolved system font / cask path carries no apostrophe (same escaping
    assumption draft documents).
  - free text via a per-title **textfile** (`work_dir/title_{i}.txt`) →
    `textfile='…'` sidesteps filtergraph escaping of `:`/`'` (draft's trick,
    generalized to N titles — hence `work_dir`).
  - `enable='between(t,{start},{start+dur})'` — the title shows only in its
    window.
  - **position** uses ffmpeg's own `w/h/tw/th` expressions — **resolution-agnostic,
    no python dims needed**: `x=(w-tw)/2` (h-centered); `y` from the safe-margin
    preset — `top → h*0.08`, `center → (h-th)/2`, `bottom → h-th-h*0.12`. `h`/`w`
    resolve to the encode's output size (the canvas-sized master). Constants for
    v1; platform-keyed margins later.
  - **style**: `bold-box → box=1:boxcolor=black@0.5:boxborderw=16`; `outline →
    borderw=4:bordercolor=black`; `plain → ` (fontcolor only). All
    `fontcolor=white:fontsize=h/18` (titles read bigger than draft's `h/24`).
- Returns the chain string (empty `Titles` → `""`).

**`deliver` wiring** — `deliver` gains an optional `titles: str | None` (a
`TITLES.json` path). When set, it loads `Titles`, calls `build_filterchain` (no
dims — the expressions are resolution-agnostic; `work_dir = out_dir`), and
**appends the chain to its encode `-vf`**. The assembled master is already
canvas-sized, so `h`/`w` in the expressions are the final canvas — no probe.
Audio mux, version log, and the hard gate are unchanged. Absent/empty → deliver
behaves exactly as today. The drivers thread it through: `edl_to_reel(…,
titles=None) → build_reel(…, titles=None) → deliver(…, titles=titles)`, so the
router path renders titles when a `TITLES.json` is passed.

## §5 · Fonts — `resolve_font` by name + `setup.sh --with-fonts`

`resolve_font` + `FONT_CANDIDATES` + the new `FONT_NAMES` map move to a small
shared `scripts/lib/fonts.py` (both `draft` and `titles` need them — leaving them
in `draft` would make `titles` import the draft-preview module). `draft` re-imports
for back-compat; the currently-uncommitted `FONT_CANDIDATES` / DejaVu changes move
with it. `resolve_font` grows a third mode:

```python
def resolve_font(font: str | None = None) -> str:
    # None / "" / "system"  -> first existing FONT_CANDIDATES (today's default)
    # an existing path       -> that path (today's --font behavior)
    # a NAME (not a path)     -> ~/Library/Fonts/<mapped filename>, else ValueError
```

- `FONT_NAMES: dict[str, str]` maps friendly names to cask filenames —
  `"Montserrat" → "Montserrat-Regular.ttf"`, `"Inter" → "Inter-Regular.ttf"`,
  `"Bebas Neue"/"BebasNeue" → "BebasNeue-Regular.ttf"`, `"Oswald" →
  "Oswald-Regular.ttf"`. Resolution: `~/Library/Fonts/<filename>` (where casks
  land). Unknown name / not installed → `ValueError`: "run `bash setup.sh
  --with-fonts`, or pass `--font PATH`". **No silent fallback** to a different
  font — a named font that resolves to Arial would silently change the creative
  output. Default titles use `font="system"` (always present), so only an
  explicit nice-font pick can hit this, and it fails loud with the remedy.
- `setup.sh` learns `--with-fonts`: `brew install --cask font-montserrat
  font-inter font-bebas-neue font-oswald`. `setup.sh` today keys the vidstab
  branch off `$1` only — it must **scan all args** so `--with-vidstab` and
  `--with-fonts` compose (`bash setup.sh --with-vidstab --with-fonts`).
- The uncommitted DejaVu-fallback guard stays: no system font at all → install
  DejaVu (the floor); `--with-fonts` adds the nice set on top.

## §6 · Pipeline placement

- New **optional** stage `titles` (authoring, post-`SPEC`) — a `montage.py`
  `Stage(kind="optional")` like reel-brief / assemble-draft: it never becomes
  `next`, so the autonomous chain (project → FOOTAGE → EDL → REEL) is intact;
  `in_out=False` (`TITLES.json` in the run dir). Checkpoint: the reel-review CP
  (titles are reviewed with the near-final reel).
- Conveyor order: … §5.12 audio-mix → **titles (author `TITLES.json`)** → §5.13
  reel-final-check → §5.14 deliver (**renders** the titles into the one encode).
  The check validates title **coordinates** against safe-margins (geometry, not
  pixels) — consistent with how §5.13 safe-zones is specified.
- The render lives in `deliver`; the stage's own artifact is the authored
  `TITLES.json`. This matches "one encode": no titled intermediate is produced.

## §7 · Non-goals (YAGNI)

- libass / ASS, fades, animated position, karaoke, per-word timing — `drawtext`
  static windows only.
- Per-episode titles — titles are **reel-level** (rendered at deliver over the
  whole reel), not part of process-episode.
- The full pixel-level `check_reel.safe_zones` gate — titles are
  **safe-by-construction** (presets sit inside safe margins) and, since
  2026-07-16, those margins are drawn from the same `SafeZone` table
  `check_reel.safe_zones` checks against (`safezones.default_zone()`); a
  **pixel-level** gate remains a non-goal — safe_zones is advisory
  subject-route geometry, not pixel CV.
- Cross-platform font install — macOS/brew casks only for now (same TODO as the
  rest of `setup.sh`).

## §8 · Testing

- **Unit** (`tests/lib/test_titles.py`): whole-object `Title`/`Titles`
  validation (each gate rejects with a message; round-trip `to_dict`/`from_dict`;
  `to_markdown` shape); `build_filterchain` pieces (one `drawtext` per item, the
  `enable='between(...)'` windows, the three position `y` formulas, the three
  style fragments, empty → `""`); `build_titles` default projection (hook window,
  ending window from `total_s`, `font="system"`).
- **Unit** (`tests/lib/test_fonts.py`, with `resolve_font` now in `lib/fonts.py`):
  name mode — known name → mapped path (monkeypatched home), unknown/missing name
  → loud `ValueError` with the `--with-fonts` remedy, path and None modes
  unchanged; `draft`'s re-import still resolves.
- **Integration** (`tests/integration/test_titles.py`, real ffmpeg): author a
  `TITLES.json` → `deliver` renders it → ffprobe confirms the encode + a frame
  sampled inside a title window differs from the same frame with no titles
  (pixels moved). Autouse **skip-guard** on the `drawtext` filter (mirrors
  draft's golden — the machine's ffmpeg may lack it).

## §9 · Docs to sync (at the build's docs task, not now)

- master spec `docs/specs/2026-07-05-montage-skillset-design.md` §5 — add the
  `titles` stage; note the render rides deliver; §12 drawtext landmine already
  present.
- `docs/pipeline-map.md` — add the `titles` row (both tables) + retally.
- `docs/build-status.md` — built note + next action.
- `CLAUDE.md` — registry rows (this design + its plan).
- `docs/development-workflow.md` — `--with-fonts` + the font-name note (extends
  the font paragraph the guard fix already touched).
- `setup.sh` — `--with-fonts`; arg-scan for composing flags.
- `SKILLS/using-montage/SKILL.md` — optional titles step + the reel-review CP
  pointer (mirrors the assemble-draft / reel-brief optional wiring).
