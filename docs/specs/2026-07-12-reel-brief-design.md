# Reel-brief spine (stage 5.3) — design

**Date:** 2026-07-12
**Status:** approved (brainstorming) → plan next
**Stage:** 5.3 `reel-brief` → `SPEC.md` (+ `SPEC.json`)

## 1. Intent

`reel-brief` is the montage conveyor's **editorial layer** — the "= brainstorming"
skill (design §5.3, §14): a one-question-at-a-time dialogue about the reel's idea
that produces `SPEC.md`, the brief the user approves at the §4.1 **CP1** checkpoint.

It sits **on top of** `project-init`'s machine subset: `project.json` already fixes
`canvas`/`delivery` (aspect + output resolution). `reel-brief` reads that
`canvas` and adds the editorial fields the machine subset does not carry — reel
count, target length, mood, hook, music intent, on-screen text, ending, style-lean,
and cast. It does **not** re-ask or duplicate canvas/delivery.

The only downstream consumer today is the **edit-plan agent**, which already reads
`SPEC.md` as optional guidance (`SKILLS/edit-plan/SKILL.md`: "read as guidance when
present … target length from `SPEC.md`"). Nothing parses SPEC fields mechanically
in v1 — the artifact is an agent-and-human editorial contract. It is typed anyway,
because (a) the repo convention is **never hand-write an artifact** (every one —
`project.json`, `FOOTAGE.json`, `EDL.json`, `cast.json`, `MUSIC.json` — is a typed
config-spec written by code), and (b) the §5.3 **gate** ("mood + platform/canvas +
length + hook locked") is only enforceable if those fields are validated.

**Shape:** a straight mirror of `project-init` — a typed config-spec
(`scripts/lib/spec.py`), a thin deterministic writer + CLI (`scripts/reel_brief.py`),
and an interrogating SKILL (`SKILLS/reel-brief/SKILL.md`). **No ffmpeg** — a
text-only stage, exactly like `project-init`; therefore no real-ffmpeg golden.

## 2. The contract — `scripts/lib/spec.py`

A hard config-spec in the `project.py`/`edl.py` mould: `@dataclass`,
validate-and-raise in `__post_init__` (ValueError-with-remedy, never a bare
`KeyError`/`TypeError`), JSON round-trip, `to_markdown()` render.

```python
MUSIC_MODES = ("local", "free", "any")          # rights lane (design §5.5) — default "free"
STYLE_LEANS = ("classic", "balanced", "trend")   # classic ↔ trend axis — default "balanced"

@dataclass
class Spec:
    canvas: tuple            # from project.json; positive [w, h]      (gate)
    length_s: float          # target length per reel, seconds, > 0    (gate)
    mood: str                # non-empty                               (gate)
    hook: str                # non-empty                               (gate)
    reel_count: int = 1      # >= 1
    music: str = "auto"      # track name / "auto" / "none" (free, non-empty)
    music_mode: str = "free" # ∈ MUSIC_MODES
    style_lean: str = "balanced"  # ∈ STYLE_LEANS
    platform: str = ""       # free label (reel / tiktok / youtube / …)
    text: str = ""           # on-screen-text intent (free)
    ending: str = ""         # ending intent (free)
    cast: tuple = ()         # names → cast.json (free non-empty strings)
    notes: str = ""
```

**Validation (`__post_init__`, raises ValueError):**
- `canvas` — `[w, h]`, len 2, both numeric `> 0` (mirror `ProjectConfig.canvas`); normalise `list → tuple`.
- `length_s` — numeric (not `bool`), `> 0`.
- `mood`, `hook` — non-empty `str` (the §5.3 gate).
- `reel_count` — `int` (not `bool`), `>= 1`.
- `music` — non-empty `str`.
- `music_mode ∈ MUSIC_MODES`; `style_lean ∈ STYLE_LEANS` (ValueError names the allowed set).
- `platform`, `text`, `ending`, `notes` — `str` (may be empty).
- `cast` — list/tuple of non-empty `str`; normalise to `tuple`.

**The gate** = `canvas` positive ∧ `length_s > 0` ∧ `mood ≠ "" ` ∧ `hook ≠ ""` — all
raised inside `__post_init__`, so an ungated `Spec` cannot be constructed.

**Methods** (mirror `ProjectConfig`): `from_dict` (pass raw values through so
`__post_init__` yields the clean remedy for missing/None; supply defaults for
absent optional keys), `to_dict` (tuples → lists), `from_json` (JSONDecodeError →
"… is corrupt, re-run reel-brief"), `write(path)` (SPEC.json), `to_markdown()`.

### `to_markdown()` → `SPEC.md`

The human-and-agent-facing brief. A titled doc, not a table (unlike `EDL.md` — a
brief is prose): heading with canvas + length + reel_count, then labelled lines for
mood, hook, music (+ mode), style-lean, platform, cast, text, ending, notes.
Empty free fields render as `–`. This is the artifact the edit-plan agent reads.

## 3. The writer — `scripts/reel_brief.py`

Thin mechanical half (mirror `edit_plan.py`): projection + write, no judgment.

```python
def build_spec(project_path: str, *, length_s, mood, hook, reel_count=1,
               music="auto", music_mode="free", style_lean="balanced",
               platform="", text="", ending="", cast=(), notes="") -> Spec:
    """Read canvas from project.json (fail-loud if absent — reel-brief FOLLOWS
    project-init), then construct+validate a Spec. build_spec supplies no canvas of
    its own; the project is the single source of aspect."""
    cfg = ProjectConfig.from_json(project_path)
    return Spec(canvas=cfg.canvas, length_s=length_s, mood=mood, hook=hook,
                reel_count=reel_count, music=music, music_mode=music_mode,
                style_lean=style_lean, platform=platform, text=text,
                ending=ending, cast=tuple(cast), notes=notes)

def write_reel_brief(spec: Spec, out_dir: str) -> dict:
    """Write SPEC.json + SPEC.md together. Returns {"status": "written", ...}."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    sj, sm = Path(out_dir) / "SPEC.json", Path(out_dir) / "SPEC.md"
    spec.write(sj)
    sm.write_text(spec.to_markdown())
    return {"status": "written", "spec": str(sj), "md": str(sm)}
```

**CLI** (mirror `edit_plan.py`'s `build` subcommand): `reel_brief build --project <project.json>
--length 30 --mood "…" --hook "…" [--reel-count N] [--music …] [--music-mode free]
[--style-lean balanced] [--platform …] [--text …] [--ending …] [--cast NAME
(repeatable)] [--notes …] --out-dir <dir>`. Parse → `build_spec` → `write_reel_brief`
→ print JSON result → `SystemExit(0)`. `--cast` uses `action="append"`. The user
never types flags — the SKILL parses the dialogue into them (design §4 line 185).

## 4. The SKILL — `SKILLS/reel-brief/SKILL.md`

Copies the brainstorming approach (design §5.3, §14): announce on entry; **context
recon** (read `project.json` for canvas, `cast.json` for real cast names if intake
has run); **one question at a time** — reel count, platform, length, mood, hook,
music + mode, style-lean, text, ending, cast; **HARD-GATE** — do not write until
mood + canvas + length + hook are locked; **self-review** the assembled brief; then
call the CLI (never hand-write SPEC.md). Read the resolved `SPEC.md` back and get
the user's CP1 approval before proceeding to edit-plan.

`music.mode` default is `free` (safe for distribution); the user can override in
free text ("without music" → `music none`; "any source" → `music_mode any`).

## 5. Router wiring

`reel-brief` graduates from **deferred → optional** (the user's call: enrich when
present, never a mandatory interrogation; the autonomous path off `project.json`
stays intact — mirrors `music-and-mood`).

- **`scripts/montage.py`** — the `V1_STAGES` row changes from
  `Stage("reel-brief", "SPEC.md", "deferred", "5.3 - not built", None)` to
  `Stage("reel-brief", "SPEC.json", "optional", "reel-brief SKILL -> reel_brief CLI", "spec")`.
  Artifact glob `SPEC.json` (the machine form, mirroring `edit-plan`'s `EDL.json`
  glob). `checkpoint="spec"` — SPEC.md is CP1's richer artifact when present; when
  absent, `project-init`'s `project.json` still anchors CP1. Two stages sharing
  `"spec"` is fine (`next_action` makes no uniqueness assumption).
- **`tests/lib/test_montage.py`** — patch the now-stale assertions: the deferred
  set becomes `["trend-scan", "pacing"]`; add `reel-brief` to the optional
  assertions and an absent→`"optional"` / present→`"done"` case. (An optional stage
  never becomes `next`, so the project→footage→edit-plan `next` sequence is
  unchanged — the existing flow tests still pass.)
- **`SKILLS/using-montage/SKILL.md`** — add reel-brief as an **optional** step after
  footage-intake and before edit-plan (offered proactively, like music — `montage
  status` never points `next` at an optional stage); fold SPEC.md into the CP1 note;
  drop reel-brief from the "deferred stages are named" line (now `trend-scan` +
  `pacing` only).

## 6. Testing

Pure unit/integration — no media, no ffmpeg (like `project-init`).

- **`tests/lib/test_spec.py`** — each validation branch raises (bad canvas,
  `length_s <= 0`, empty mood, empty hook, `reel_count < 1`, empty music, bad
  `music_mode`, bad `style_lean`, non-str cast entry); a good `Spec` accepts;
  whole-object `to_dict` round-trip (`from_dict(to_dict()) == original` field-wise);
  `from_json` on corrupt JSON raises with remedy; `to_markdown` contains the gate
  fields and renders empty frees as `–`.
- **`tests/test_reel_brief.py`** — `build_spec` reads canvas from a written
  `project.json`; `build_spec` with a missing project path raises (fail-loud
  "follows project-init"); `write_reel_brief` emits **both** SPEC.json and SPEC.md
  and the JSON reloads to an equal `Spec`; the CLI (monkeypatch `sys.argv`) writes
  the files and exits 0; `--cast` repeats into a list.
- **`tests/lib/test_montage.py`** — the patches from §5.

## 7. Non-goals (v1)

- **Music sourcing / mood-match (Phase B3)** — SPEC only *records* `music` +
  `music_mode`; nothing consumes them yet (`music_find.py`/`music_fetch.py` unbuilt).
- **cast.json cross-validation** — `cast[]` are free strings; checking them against
  `cast.json` descriptors is deferred (cast.json may not exist when brief runs).
- **trend-scan (5.4)** — `style_lean` is recorded; `TRENDS.md` is not read.
- **Multi-reel fan-out** — `reel_count` is written as recorded intent, but
  `edl_to_reel` stays single-reel; the mechanical path honours one reel. Building
  N distinct reels (different clips/endings) is a later slice.
- **assemble-draft (5.9)** — separate.

## 8. Docs to sync (final task)

- `docs/pipeline-map.md` — 5.3 `◐ → ✅` in both the 15-stage table and the
  remaining-work table; tally `8 ✅ · 4 ◐ · 3 ❌ → 9 ✅ · 3 ◐ · 3 ❌`; the
  front-half narrative.
- `docs/build-status.md` — append the reel-brief DONE entry; narrow the Next-action;
  update "Front-half authoring ◐" (5.3 done; remaining SP1b draft + trend-scan).
- `docs/specs/2026-07-05-montage-skillset-design.md` — a `> Built (2026-07-12)` note
  under §5.3.
- `CLAUDE.md` — registry rows for this design + its plan.
