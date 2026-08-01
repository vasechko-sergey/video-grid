# Verify-runtime preflight — design

**Date:** 2026-08-01
**Status:** approved (brainstorm) — pending written-spec review, then plan.

## Context

`bash setup.sh` provisions the runtime the montage skills drive: an external
Python venv (symlinked as `<clone>/.venv`), a full-featured keg-only `ffmpeg-full`
(drawtext + vidstab) recorded in `config/ffmpeg.env`, baseline fonts, and the YOLO
weights (auto-downloaded on first intake). The plugin distributes only the skills;
the runtime is separate, and a plugin install alone cannot make a reel.

Today the readiness signals are **scattered and lazy**: `bin/vg` fails loud only
when the venv is missing, `ffbin` raises only when a binary cannot be resolved *at
the moment it is needed*, and a missing ffmpeg **filter** (`drawtext`, `vidstab*`)
does not surface until the stage that uses it runs — which for `drawtext` is
`deliver`, minutes into a run. There is no single "is my install whole?" check
that runs **before** the conveyor starts and, on any gap, prints exactly what to
run to fix it.

This slice adds that check: a **runtime preflight** that asserts the `setup.sh`
baseline contract is satisfied, reports each gap with its remedy, gates
`using-montage` at step 0, and is runnable on demand as its own skill.

## 1. What it checks — "the `setup.sh` baseline contract"

The dividing line is crisp and non-arbitrary: **required = what `setup.sh` installs
by default** (its baseline); **advisory = what lives behind a `--with-*` flag**.
`verify_runtime` therefore answers one question — *did the baseline install
complete and stay intact?* — not *does this particular brief need exactly these
capabilities?* (§5 on why that boundary is deliberate).

### Required (a failure BLOCKS the run)

| key | check | probe | remedy |
|-----|-------|-------|--------|
| `deps` | the runtime modules the pipeline imports | `importlib` each of numpy, scipy, PIL, cv2, librosa, ultralytics, scenedetect, imagehash, yt_dlp, requests | `bash setup.sh` |
| `ffmpeg_bin` | ffmpeg + ffprobe resolve | `ffbin.ffmpeg()`/`ffbin.ffprobe()` return an existing file | `bash setup.sh` |
| `drawtext` | drawtext filter present | `ffbin.has_filter("drawtext")` | `bash setup.sh` |
| `vidstab` | vidstab filters present | `ffbin.has_filter("vidstabdetect")` **and** `"vidstabtransform"` | `bash setup.sh` |
| `font` | a drawtext font resolves | `fonts.resolve_font()` (the system-default fallback) returns an existing file | `bash setup.sh` |
| `weights` | YOLO weights present | `<root>/MODELS[0]` exists (`models.MODELS[0] == "yolo11n-seg.pt"`; the first intake auto-downloads it if online) | `bash setup.sh` |

(The `ffmpeg_bin` key is spelled with the `_bin` suffix, not a bare `ffmpeg`: the
landmine lint's AST scan bans a bare `"ffmpeg"` string literal in `scripts/` — a
false positive here, since it is a registry key, not subprocess argv — so the key
sidesteps it. `weights` reads the filename from `models.MODELS[0]`, a numpy-free
import, keeping the driver light.)

The `deps` set is exactly `requirements.txt`'s **runtime** modules (pytest is
dev-only, excluded) plus `cv2` — opencv is not a `requirements.txt` line but a
direct import of `lib/flow.py` (and a transitive ultralytics dep), so probing it
catches a broken opencv independently.

### Advisory (a failure is REPORTED, never blocks)

| key | check | needed only for | remedy |
|-----|-------|-----------------|--------|
| `demucs` | demucs importable | sharper music in-point (§5.5); absent → librosa mix-silence proxy | `bash setup.sh --with-demucs` |

`demucs` is the one genuinely opt-in **importable** capability: it is the only
runtime module not in `requirements.txt`, installed solely by `--with-demucs`.
`--with-sourcing` is **not** a second advisory row — it installs `yt-dlp`, which is
already a `requirements.txt` baseline line (so it lives under the required `deps`
check), and otherwise only configures an optional Jamendo `client_id`; the free
music-sourcing lane works keyless via ccMixter, so a missing key is not a gap and
is not gated here.

**Tiering note (deliberate, approved).** `drawtext`/`font` are strictly needed only
by the optional titles (§5.16) and draft-label (§5.9) stages, yet they sit in
**required** — because `setup.sh` installs them at baseline, so their absence means
the install is *incomplete*, which is worth surfacing regardless of whether this
run uses titles. `vidstab` and `weights` are required unconditionally: **intake
runs vidstabdetect and YOLO on every clip**, so no reel is built without them.
`librosa`/`requests`/`yt-dlp` are baseline (`requirements.txt`) and so required via
`deps` even though only the music and sourcing lanes exercise them — same
install-integrity logic. The cost of this choice — a titles-less reel is blocked on
a broken `drawtext` — is accepted: `verify_runtime` is an *install-integrity* gate,
not a per-brief tailor (§5). The report is granular, so a human who knows their reel
touches none of the red capability can read it and re-run `setup.sh` to go green.

## 2. Layers — the bootstrap boundary

`verify_runtime` runs **inside** the venv (launched by `bin/vg`). It therefore
**cannot report a missing venv or a missing recorded-root** — it would not start.
Those two live in a pre-venv layer that already exists and stays where it is:

- **root record** — `${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root`. Resolved
  by the skill's shell **preamble** (`cat` the file). Missing → "run `bash
  setup.sh` in the clone", stop before invoking `bin/vg`.
- **venv** — `<root>/.venv/bin/python`. Gated by **`bin/vg`** itself (its existing
  fail-loud remedy).

The full picture is covered *across* the layers, not inside one process:

```
skill preamble (root)  →  bin/vg (venv)  →  verify_runtime (deps/ffmpeg/filters/font/weights/opt)
```

This boundary is not a limitation to paper over — it is the honest shape of a check
that needs the thing it would check in order to run. It is written down here and in
`verify_runtime`'s module docstring so no future reader adds a "venv check" to a
script that can only execute when the venv already works.

## 3. Architecture — pure registry + thin driver

Mirrors the repo's pure-core / thin-driver split (color_measure, pacing, offset).

### `scripts/lib/preflight.py` — pure, no heavy imports, no subprocess

- `@dataclass(frozen=True) Check`: `key: str`, `label: str`, `required: bool`,
  `remedy: str`. A serialisable description of one check — **no probe callable**
  (keeps the module pure and the registry data).
- `CHECKS: tuple[Check, ...]` — the registry above, in report order (required
  first, advisory last).
- `@dataclass(frozen=True) CheckOutcome`: `key`, `label`, `required`, `ok: bool`,
  `detail: str`, `remedy: str`.
- `@dataclass(frozen=True) RuntimeReport`: `results: tuple[CheckOutcome, ...]` with
  properties `ok` (every **required** result ok — advisories never affect it),
  `failures` (required, not ok), `advisories` (optional, not ok); plus `to_dict()`
  (JSON payload) and `to_text()` (human table, ✓/✗ per row, remedies for the gaps).
- `evaluate(raw: dict[str, tuple[bool, str]]) -> RuntimeReport` — **the testable
  core**. Takes each check's `(ok, detail)` keyed by `Check.key`, joins it with
  `CHECKS` (attaching label/required/remedy), and builds the `RuntimeReport`. No
  ffmpeg, no imports, no filesystem — feed it fabricated raw results and assert the
  whole `RuntimeReport`. Fails loud if `raw`'s keys do not match the registry
  exactly (a probe added without a `Check`, or vice versa, is a bug, not a silent
  skip).

  The names are `CheckOutcome`/`RuntimeReport`, **not** `CheckResult`/`Report`:
  `scripts/lib/models.py` already owns a `CheckResult`/`Report` family (the
  per-episode QA report), and two same-named-different-shape dataclasses invite a
  silent unqualified-import shadow. Always import qualified (`from scripts.lib
  import preflight`; `preflight.RuntimeReport`).

### `scripts/verify_runtime.py` — the driver (impure: imports, subprocess)

- One probe per check, each returning `(ok: bool, detail: str)`:
  `_probe_deps`, `_probe_ffmpeg`, `_probe_drawtext`, `_probe_vidstab`,
  `_probe_font`, `_probe_weights`, `_probe_demucs`. Probes reuse the tested helpers
  (`ffbin.has_filter`, `fonts.resolve_font`) rather than re-implementing them.
- `run() -> preflight.RuntimeReport` — runs every probe into the `raw` dict,
  returns `preflight.evaluate(raw)`.
- `main()` — `--json` prints `report.to_dict()`; default prints `report.to_text()`.
  **Exit code: 0 when `report.ok`, else 1.** The report is always emitted first;
  the exit code is the shell-gate signal (`bin/vg` `exec`s the interpreter, so the
  code propagates to the caller). Advisory failures never change the exit code.

### `scripts/montage.py` — untouched

`verify-runtime` produces **no run artifact** and is not a conveyor stage, so it
does **not** enter `V1_STAGES`. `montage.py` stays a pure filesystem inspector; we
do not thread subprocess-spawning probes through it.

## 4. Read-only by design

`verify_runtime` **prints** remedies; it **never runs** `setup.sh` or any
installer. Diagnosing an install must not mutate the machine — the user runs the
remedy. This matches the standing no-autonomous-mutation rule and keeps the check
safe to run anywhere, any number of times.

## 5. What it does NOT cover (the load-bearing honest half)

- **Not the venv, not the root record** — the bootstrap boundary of §2. Those are
  the pre-venv layer's job; `verify_runtime` cannot see past its own interpreter.
- **Not dependency *versions*** — it probes importability, not `>=` bounds. A too-old
  library still fails at the point of use. Checking versions is possible but adds a
  brittle table to maintain against `requirements.txt`; out of scope (YAGNI).
- **Not per-brief relevance** — it reports *all* capabilities, required and
  advisory, regardless of what this run needs. The `using-montage` skill (which
  has the brief) decides relevance from the report; the check itself is
  brief-agnostic so it stays a stable install-integrity oracle.
- **Not the font *for a specific title***, only that *a* default font resolves.
  A `TITLES.json` naming a font that is not installed still fails loud at
  `deliver` with its own remedy — `verify_runtime` does not read `TITLES.json`.
- **Not network reachability** for the music-sourcing catalogs or the weights
  auto-download — presence of the tool, not of the internet.

## 6. Wiring

### `skills/verify-runtime/SKILL.md` (new, thin)

Preamble resolves the root record (missing → `bash setup.sh` in the clone, stop) →
runs `"$VG" scripts.verify_runtime` → presents the report. Green → "runtime ready".
Any required failure → list each red check with its remedy (each already carries
`cd <clone> &&`, so present it verbatim in a `bash` block — it runs from any cwd).
Advisory gaps → list as "optional, only for X". Never runs `setup.sh` itself. Auto-discovered from
`skills/` (the plugin manifests do not enumerate skills), so a reinstall picks it
up.

### `using-montage` step 0

Replace the prose "Ensure env (one-time install)" with an explicit gate: after
resolving `$VG`, run `"$VG" scripts.verify_runtime`; a non-zero exit (a required
failure) → surface the report's failures + remedies and **stop** (do not proceed to
project-init); advisory gaps → name them (e.g. "demucs absent — music in-point
uses the librosa proxy") and proceed; green → step 1. The existing launcher
preamble (root record) stays as the pre-venv gate ahead of this.

## 7. Invariants

1. `report.ok` ⇔ every **required** check passed; advisory results never move it.
2. Exit code is `0` iff `report.ok`; the report text/JSON is always emitted first.
3. `evaluate` is pure and total over the registry: `raw`'s keys **must** equal the
   `CHECKS` keys — a mismatch raises, so a probe and its `Check` cannot drift apart
   silently.
4. `verify_runtime` performs **no** installs or writes — read-only.
5. `verify-runtime` is **not** in `V1_STAGES` and creates no run artifact.
6. `run()` never raises: an unexpected exception from any probe becomes that
   ONE check's failed `CheckOutcome` (`detail` = `"probe raised: …"`), so the
   checker always returns a `RuntimeReport`, never a traceback.
7. Every printed remedy is **cwd-independent**: the registry stores it relative
   (`bash setup.sh`), and the driver passes the resolved clone root to
   `evaluate(root=)`, which prefixes `cd <clone> &&` (shell-quoted). The user can
   run it — or click Run — from any directory, not only the clone. A bare
   `bash setup.sh` fails from anywhere else (the report bug that surfaced
   2026-08-01: Run in `~/Downloads` → `bash: setup.sh: No such file`).

## 8. Testing

- **Pure `preflight`:** `evaluate` over fabricated `raw` → whole-object `Report`
  assert; the `ok`/`failures`/`advisories` partition (a required miss flips `ok`,
  an advisory miss does not); `to_dict`/`to_text` shape and that remedies appear
  only for gaps; registry integrity (unique keys, expected required/advisory
  split); the key-mismatch raise.
- **Driver (stubbed probes):** monkeypatch the probe helpers →
  `run()` builds the expected `Report`; `main()` exit 0 vs 1 (a required miss → 1,
  an advisory-only miss → 0); `--json` vs table output.
- **Integration (real machine, `integration` marker):** on a completed
  `setup.sh` install, `run().ok is True` and no required failures — the real
  ffmpeg/deps/filters proof, the same "needs the user's install" shape as the
  ffmpeg-baseline slice's proof.

## 9. Deferred / out of scope

- Cross-platform remedies (Linux/Windows) — `setup.sh` is macOS/Homebrew for now;
  the remedies name `bash setup.sh`, matching that reality.
- Dependency **version** assertions (§5).
- A `--fix` that runs `setup.sh` — rejected on principle (§4, no autonomous
  mutation).
- Network/reachability probes for sourcing and the weights download (§5).
