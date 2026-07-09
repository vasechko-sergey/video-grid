# Project-init: purpose→aspect/delivery + episode inheritance — Design

**Date:** 2026-07-09
**Status:** approved (brainstorming) → next: writing-plans
**Scope:** The project-level "front door" that drives the now-aspect/resolution-agnostic engine (design `docs/2026-07-08-engine-dataclass-hardening-design.md`). One plan, one subsystem.

## Context

The engine is resolution/aspect-agnostic: `reframe`/`check_episode` take any `canvas` and a `Delivery` (native/short_edge/long_edge/exact), no 9:16/1080×1920 hardcode. But nothing yet *drives* that generality — every episode manifest must repeat `canvas`/`delivery`, and there is no step that learns "what is this video for" and derives the aspect. This plan adds that step: a project config learned once at project start (purpose→aspect, quality→delivery), which episode manifests inherit.

**Source-of-truth reconciliation:** the montage design (`docs/2026-07-05-montage-skillset-design.md`) puts platform+canvas in `SPEC.md` (the human reel-brief, §-line 96) and defines the "ingestion plan" as `cast.json` + interactive naming (§-line 287). This plan builds neither of those: it delivers a **minimal machine config** (`project.json`) carrying just `{purpose, canvas, delivery}`. When the fuller `SPEC.md` brief phase is later built, its platform+canvas populates (or supersedes) `project.json` — they reconcile, they do not conflict. Hero identity (`cast.json`) is a separate axis and a separate plan.

## Goals

1. **`project.json` + `ProjectConfig`** — a typed, validated project config (purpose, canvas, delivery), written once at project start.
2. **Deterministic resolution maps** — `purpose→canvas` and `quality→delivery` (delivery **defaults to `native`** — no silent downscale; the engine's whole point is to preserve source resolution).
3. **Episode inheritance** — `resolve_manifest(episode, config)` fills `canvas`/`delivery` when an episode omits them; explicit episode fields override. `process_episode` gains an optional `project=` that applies this.
4. **`project-init` SKILL + CLI** — the deterministic map is a Python script/lib (TDD'd); a thin SKILL asks the user purpose+quality and writes `project.json`.

## Non-goals (separate plans)

- **`cast.json` / hero-identity ingestion** (interactive naming, seg-mask descriptors, descriptor-based hero pins) — the montage design's "ingestion plan" (§-line 287). Different axis (identity, not aspect).
- **The full `SPEC.md` reel-brief** (length, mood, music, hook, text, ending, cast). This plan is the machine `{canvas, delivery}` subset only.
- **Router / cap-3 parallel fan-out** — the dispatch layer that would iterate episodes. This plan makes inheritance available (`process_episode(project=)`); it does not build the fan-out.
- **Footage reading / segment extraction / `extract` orchestration** — upstream intake, unchanged.

## Design principle (matches the codebase)

Determinism in Python (TDD'd exactly like the engine); judgment in the SKILL. The `purpose→canvas`/`quality→delivery` maps and the inheritance merge are pure and unit-tested; the interactive "what's this video for" asking is a thin agent layer.

---

## A. Data model — `scripts/lib/project.py`

```python
@dataclass
class ProjectConfig:
    purpose: str          # a key in PURPOSE_CANVAS, or "custom"
    canvas: tuple         # (w, h), positive
    delivery: str         # a Delivery spec string; validated via Delivery.from_spec
    notes: str = ""

    def __post_init__(self):
        # purpose in PURPOSES; canvas is a positive 2-tuple; delivery parses
        # (Delivery.from_spec raises on bad) — raise ValueError-with-remedy, like the models specs
    @classmethod
    def from_dict(cls, d): ...      # coerce canvas list→tuple; explicit null → default where sensible
    def to_dict(self): ...          # {"purpose","canvas":[w,h],"delivery","notes"}
    @classmethod
    def from_json(cls, path): ...
    def write(self, path): ...      # project.json in the project root
```

`ProjectConfig` follows the **hard-validation** half of the engine's principle: it raises on bad construction (unknown purpose, non-positive canvas, unparseable delivery). It is not the user-facing soft gate — the SKILL/CLI is where a human's ambiguous answer becomes a re-ask.

## B. Resolution maps + constructor — `scripts/lib/project.py`

```python
PURPOSE_CANVAS = {
    "reel": (9, 16), "shorts": (9, 16), "tiktok": (9, 16),
    "youtube": (16, 9), "landscape": (16, 9),
    "square": (1, 1), "feed": (1, 1),
    "cinema": (21, 9), "wide": (21, 9),
    "custom": None,                       # explicit canvas required
}
QUALITY_DELIVERY = {
    "native": "native",                   # DEFAULT — crop's own pixels, no scale, no loss
    "social": "short_edge:1080",          # deliberate downscale for social / small file
    "4k": "long_edge:2160",               # normalize/upscale to 4K delivery
    # "custom" → explicit delivery string
}

def resolve_project(purpose, quality="native", canvas=None, delivery=None, notes=""):
    """Deterministic purpose+quality → ProjectConfig. `custom` purpose requires an
    explicit `canvas=(w,h)`; `custom`/explicit `delivery` overrides the quality map.
    Raises ValueError-with-remedy on unknown purpose/quality or a missing custom canvas."""
    cv = PURPOSE_CANVAS.get(purpose, "MISS")
    if cv == "MISS":
        raise ValueError(f"purpose {purpose!r} unknown — one of {sorted(PURPOSE_CANVAS)}")
    if purpose == "custom":
        if canvas is None:
            raise ValueError("purpose 'custom' needs an explicit canvas=(w, h)")
        cv = tuple(canvas)
    dv = delivery if delivery is not None else QUALITY_DELIVERY.get(quality, "MISS")
    if dv == "MISS":
        raise ValueError(f"quality {quality!r} unknown — one of {sorted(QUALITY_DELIVERY)} or pass delivery=")
    return ProjectConfig(purpose=purpose, canvas=cv, delivery=dv, notes=notes)
```

**Quality defaults to `native`** — for general montage (TVs, large screens) we never silently downscale; a 4K source's crop is delivered at its own high resolution. `social` (1080 cap) / `4k` / explicit are deliberate opt-ins.

## C. Episode inheritance — `scripts/lib/project.py`

```python
def resolve_manifest(episode_dict, config):
    """Fill canvas/delivery from the project when the episode omits them (missing
    OR explicit JSON null → inherit, matching the manifest's null-is-absent rule);
    an explicit episode value wins (override). Returns a NEW dict; never mutates."""
    out = dict(episode_dict)
    if out.get("canvas") is None:
        out["canvas"] = list(config.canvas)
    if out.get("delivery") is None:
        out["delivery"] = config.delivery
    return out
```

The manifest contract is **unchanged** — a *resolved* manifest still carries `canvas` (required by `Manifest.from_dict`). Inheritance is purely upstream: the episode *author* may omit `canvas` when a project exists; `resolve_manifest` fills it before the manifest is validated.

## D. Wiring into the shell — `scripts/process_episode.py`

`process_episode` gains a trailing optional `project=None`:
```python
def process_episode(manifest_dict, project_dir, route_path=None, max_attempts=3, project=None):
    if project is not None:
        cfg = project if isinstance(project, ProjectConfig) else ProjectConfig.from_json(project)
        manifest_dict = resolve_manifest(manifest_dict, cfg)
    # ... existing body unchanged (try/except from_dict → needs_input, validate, loop) ...
```
`project` accepts a `ProjectConfig` **or** a path to `project.json` (loaded). Applied before the existing manifest construction, so a bad project.json surfaces the same way as a bad manifest input. Everything downstream is unchanged — the shell still receives one complete manifest.

## E. Agent + CLI layers

- **`scripts/project_init.py` (CLI, deterministic)** — `python -m scripts.project_init --purpose reel --quality native --project-dir <dir>` (with `--canvas W:H` / `--delivery <spec>` for custom) → calls `resolve_project`, writes `project.json`. Fails loud on bad args (via `resolve_project`'s raises).
- **`SKILLS/project-init/SKILL.md` (judgment)** — first step of a project: asks the user the purpose ("what's this video for — reel / youtube / square / cinema / custom?") and quality ("native/best (default) / social-1080 / 4K / custom?"), then runs the CLI to write `project.json`. One pass. Announces on entry; relays the resolved `{canvas, delivery}` back so the user can confirm. Genuinely ambiguous / mixed-delivery reels → ask; never guess an aspect.

## F. Testing

- **Pure (`tests/lib/test_project.py`):** `resolve_project` for every purpose→canvas and quality→delivery; `custom` with/without explicit canvas; unknown purpose/quality raise; explicit `delivery=` overrides the quality map. `ProjectConfig` validation (bad purpose/canvas/delivery raise). `resolve_manifest`: fills absent canvas/delivery, explicit episode value overrides, JSON `null` inherits, never mutates the input. `from_dict`/`to_dict`/`write`/`from_json` round-trip.
- **Shell (`tests/integration/test_process_episode.py`, mocked engine):** `process_episode(project=cfg)` — this is where **non-9:16 threading** is proven cheaply and robustly (no real ffmpeg, so the crop geometry never has to satisfy the mechanical checks): a `youtube` (16:9) or `square` (1:1) project + an episode omitting `canvas` → the fake `reframe` sees the inherited non-9:16 `ReframeSpec.canvas` and the fake `check` still passes (mocked) → `mechanical_pass`. Also: an episode WITH an explicit `canvas` + a project → the explicit one wins (assert the captured canvas); an episode omitting `delivery` → inherits the project delivery (assert the captured `ReframeSpec.delivery`).
- **Integration (real ffmpeg):** a **`reel` (9:16) project with `native` delivery** + an episode omitting `canvas`/`delivery` → resolved → the golden ride through `process_episode` → `mechanical_pass` (the checks are geometry-space and hold at 9:16, unchanged from today's golden) + assert the delivered clip's dims equal the golden source's native 9:16 crop (1280×720 source → 9:16 crop 405×720 → even `404×720`), NOT the old pinned `1080×1920`. This proves the project front-door drives the engine end-to-end through real ffmpeg and that `native` delivery is honored; the *aspect* generality (non-9:16 canvas actually reaching `reframe`) is proven by the mocked shell test above, which doesn't need the checks to pass on a re-shaped crop.
- **SKILL (`tests/integration/test_skill_project_init.py`):** structural — frontmatter name/description, the CLI invocation shape, the ask-then-write flow.

## Acceptance criteria

1. `project.json` + `ProjectConfig` (raises on bad); `purpose→canvas` + `quality→delivery` maps with `native` default.
2. `resolve_manifest` inherits absent canvas/delivery, episode explicit wins, null inherits, no mutation.
3. `process_episode(project=)` applies inheritance before manifest validation; contract otherwise unchanged.
4. A non-9:16 project drives an episode end-to-end through real ffmpeg with correct output dims.
5. `project-init` CLI writes the config deterministically; the SKILL asks + writes + confirms.
6. Out of scope stays out: no cast.json, no full SPEC.md brief, no router, no footage intake.
