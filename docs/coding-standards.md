# Coding Standards

Coding principles, imports, typing, dataclasses, and the fail-loud contract for
video-grid. Adapted from the anna-auth standards to a single-package Python
skill set (no web/DB layer). The safety landmines live in the design spec §12;
this doc is the everyday how-we-write-code reference.

_Last updated: 2026-07-09._

## Core Principles

1. **Fail loud with a remedy** — never swallow an error, never silently fall
   back. A failure raises (or `needs_input`s at the soft gate) and the message
   tells the caller how to fix it: `"ffmpeg not found → brew install ffmpeg"`.
   Fallbacks hide real failures; a montage that quietly ships black frames is
   worse than one that stops and says why.
2. **Less is more** — rewrite an existing function rather than bolt a second one
   beside it. Flag obsolete files/paths for removal instead of leaving them.
3. **Full code output** — when editing, produce the whole changed unit; never
   `# ... unchanged`.
4. **Think first** — the black-frames bug was argument order, not 4K. Clear
   reasoning up front prevents the landmine.
5. **Determinism in Python, judgment in the SKILL** — pure, unit-tested logic in
   `scripts/lib/`; the interactive/ambiguous decisions in `SKILLS/*/SKILL.md`.

## Fail-Loud Contract

- Every script and lib raises on bad state with an actionable remedy. Grep test:
  a raised message a stranger could act on without reading the source.
- **Validation boundary (hard rule):** the manifest gate is **soft** —
  `manifest.validate()` returns a list of problems that the shell turns into a
  `needs_input` result (a human answers). **Everything below the manifest is
  hard** — config-specs and engine functions raise `ValueError` on bad
  construction. Do not soften an engine raise into a return code, and do not
  harden the manifest gate into a crash. See
  [testing-guide.md](./testing-guide.md) for how each side is tested.
- Raise `ValueError` (not `TypeError`) for wrong-type/wrong-value construction of
  a spec, with the remedy in the message.

## Imports

- **All imports at module top.** No imports inside functions.
- **Sole exception: a heavy, optional third-party dependency**, lazy-loaded on
  purpose so the module stays importable (and testable) without it. Today the
  sanctioned cases are `from ultralytics import YOLO` inside `scripts/track.py`
  and `scripts/intake.py` (ultralytics pulls in torch), `import librosa` inside
  `scripts/beats.py` (librosa is heavy; montage §5.5), and `scenedetect` inside
  `scripts/intake.py` (pulls in opencv; §5.2). Mark such a case with a
  one-line `# lazy import: heavy optional dep (...)` comment. Stdlib (`json`,
  `tempfile`) and already-required deps (Pillow) are never lazy — put them at
  the top.
- Group: stdlib, then third-party, then `scripts.*`. One import per concern.

## Typing

- **Every module-level function is fully typed** — all parameters and the return
  type (`-> ...`). This is documentation and error-surface: an untyped boundary
  hides the contract the dataclasses exist to make explicit.
- Prefer precise builtin generics: `list[RoutePoint]`, `dict[str, float]`,
  `tuple[int, int]`, `int | None`. Paths that accept either form are `str | Path`.
- Nested closures are annotated when cheap; module-level defs are mandatory.
- Keyword-only arguments where a call site would otherwise be a row of bare
  positionals whose meaning is unclear.

## Dataclasses

The engine is built on two families of dataclasses in `scripts/lib/models.py`
(design [spec](./specs/2026-07-08-engine-dataclass-hardening-design.md)). No ad-hoc
dict parsing across module boundaries — a dict becomes a typed object at the edge
and travels typed.

- **Config-specs** (`TrackSpec`, `ReframeSpec`, `CheckSpec`, `StoryboardSpec`,
  `Delivery`, `ProjectConfig`): **validate in `__post_init__` and raise
  `ValueError`-with-remedy** on bad construction. They are the hard boundary.
- **Wire-contracts** (`RoutePoint`, `TrackMeta`, `CropPath`, `CheckResult`,
  `Report`): own their JSON round-trip via `from_dict`/`to_dict`
  (`from_json`/`to_json` for the file-backed ones). The on-disk schema is a
  contract — a round-trip must reproduce it byte-for-key. A field that is
  computed/derived must not leak a stale key on `to_dict` (see
  `CheckResult.to_dict` stripping a stale `pass`).
- Prefer `@dataclass(frozen=True)` for pure value types (e.g. `RoutePoint`).
  Do not blanket-apply `slots`/`kw_only` — adopt per type only when it earns its
  keep, since both change the construction/attribute API.
- Field annotations are precise (`hero: int | None`, `xs: list[int]`), not `object`.

## Banned / mandated patterns (safety — full registry: design spec §12)

- `lutrgb` is **banned** (produces black frames) — use `colorchannelmixer` only.
- ffmpeg seek: `-ss` **after** `-i` for frame-accurate cuts.
- Never stabilize wade-in / wade-out shots ("rolling ground").
- Scripts run as modules: `.venv/bin/python -m scripts.<name>`; explicit paths
  always, never rely on cwd.

## Related

- [testing-guide.md](./testing-guide.md) — TDD, whole-object asserts, golden fixtures.
- [development-workflow.md](./development-workflow.md) — env, execution protocol, commits.
- [spec/2026-07-05-montage-skillset-design.md](./specs/2026-07-05-montage-skillset-design.md) §12 — the full landmine registry.
