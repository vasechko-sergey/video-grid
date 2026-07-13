# Start-Offset Intelligence — Design Spec (§5.5 sub-slice)

The slice that makes a reel's music **in-point** a decision, not a hand-typed
number. Today `MusicSpec.start_offset` is passed by the agent (`beats
--start-offset S`) or defaults to `0.0`; this adds `choose_offset(track,
duration)` — it scans the track for the strongest fragment **and** lands the
start in a vocal pause so the reel never opens mid-word.

Maps to montage design §5.5 (`MUSIC.json` `start_offset` = "chosen track
fragment"; `vocal-map` = "phrase boundaries for start snapping"). One new pure
decision module, one heavy-dependency boundary module, one driver edit, one
opt-in `setup.sh` flag. **Not a v1 blocker** — a hand-set `start_offset` still
works; this automates the choice.

## Goal

`track + reel duration → choose_offset → start_offset`, such that:

1. the `duration`-length window starting at `start_offset` is the **strongest**
   fragment of the track (max mean RMS energy — chorus/drop tends to be loudest); and
2. `start_offset` sits **inside a vocal pause** — the reel opens where no one is
   singing, so the first frames are not mid-word.

Then the existing `analyze(track, start_offset, duration)` runs unchanged and
`MUSIC.json` carries the chosen offset downstream (`mix.py` accurate-seeks to it).

## Scope decisions (from brainstorming, 2026-07-13)

1. **Strongest = peak mean RMS energy** (not onset-density, not rising-build).
   Reuses the RMS curve `beats` already computes; deterministic; simple.
2. **Vocal pause via true vocal separation (demucs)**, not a librosa silence
   proxy — the user wants a hard "never cut into words," and demucs is §5.5's
   named vocal-stem upgrade. The mix-energy silence proxy remains as the
   **fallback** when demucs is absent.
3. **demucs is opt-in** (`setup.sh --with-demucs`, mirroring `--with-vidstab`/
   `--with-fonts`), with a **logged** fallback to the mix-proxy when not
   installed. CI/tests stay green without torch; cross-platform friendly.
4. **Approach B — whole-track demucs.** Separate vocals over the whole track
   once, find every vocal gap, then pick the max-energy window whose start lands
   in a gap. Simplest logic and a real gap-start guarantee; the cost is a
   one-time whole-track demucs pass (minutes on CPU), amortised because the
   chosen offset is written into `MUSIC.json` and reused. (Rejected: A bounded
   snap — fast but gap-start only best-effort; C hybrid shortlist — bounded
   demucs but more moving parts. B's simplicity + guarantee won.)
5. **Candidate start = the gap's start** (clamped so the window fits the track).
   Energy is measured over the whole window, so a gap that leads *into* the
   chorus scores high — the reel opens clean and rolls into the loud part.
   **No beat-snap of the start in v1** (a chicken/egg with the beat grid
   `analyze` derives; the vocal gap is the guarantee, beat-alignment is polish).
6. **YAGNI.** Energy + vocal-gap only. No section detection, no downbeats, no
   mood vector. The fallback reuses the *same* gap logic on the mix curve — one
   code path, not two.

## §1 — Architecture & files

The established split: the pure decision in `lib/`, the heavy IO/dependency
behind its own module, the driver thin on top. Two new modules, four edits.

```
scripts/lib/offset.py   NEW  pure   vocal_gaps(env, hz, *, thresh_frac, min_gap) -> spans
                                     best_offset(mix_energy, mix_hz, gaps, duration, track_dur) -> float
                                     No IO, no torch, no ffmpeg — the real decision, 100% unit-tested.
scripts/lib/vocals.py   NEW         has_demucs() -> bool
                                     separate_vocal_energy(track, target_hz=2.0) -> (env, hz)
                                     Lazy `import demucs` (+torch). The heavy-dependency boundary.
scripts/beats.py        EDIT        choose_offset(track, duration, *, use_vocals=True) -> float driver;
                                     CLI `--auto-start` (mutually exclusive with --start-offset).
                                     analyze() UNCHANGED.
setup.sh                EDIT        --with-demucs opt-in: `pip install demucs` into the venv,
                                     idempotent (pip show || install). requirements.txt stays lean.
SKILLS/using-montage/SKILL.md  EDIT step 5: prefer `--auto-start` when the brief names a track but
                                     no explicit offset; note --with-demucs for the accurate path.
docs (pipeline-map, build-status, CLAUDE.md, montage §5.5, music-spine cross-ref)  EDIT
```

### Module responsibilities

- **`offset.py`** — knows nothing about audio files, librosa, or demucs. It
  takes numeric envelopes (lists/arrays + a sample rate) and returns times. This
  is where every branch of the decision is exercised deterministically.
- **`vocals.py`** — the only place `demucs`/`torch` is imported. It turns a track
  path into a coarse vocal-activity envelope. Swappable (a different separator,
  a stub in tests) without touching the decision.
- **`beats.choose_offset`** — orchestrates: load → mix RMS → (vocal env | proxy)
  → gaps → `best_offset`. Emits one info line naming the path taken.

## §2 — The decision core: `offset.py`

Pure functions on numeric envelopes. Times are **track seconds** (`index / hz`).

```python
def vocal_gaps(env: Sequence[float], hz: float, *,
               thresh_frac: float = 0.15, min_gap: float = 0.35) -> tuple[tuple[float, float], ...]:
    """Spans (start_s, end_s) where the activity envelope stays below
    thresh_frac * ref for at least min_gap seconds — ref = max(env) (a RELATIVE
    bar: a quiet mix must not read as all-silent; mirrors the relative black
    gate, design §12). A run shorter than min_gap is a between-words dip, not a
    phrase boundary, and is dropped. env all-zero (instrumental) -> one gap
    spanning the whole envelope (no vocals to avoid)."""
```

```python
def best_offset(mix_energy: Sequence[float], mix_hz: float,
                gaps: Sequence[tuple[float, float]],
                duration: float, track_dur: float) -> float:
    """start_offset (track seconds) of the duration-length window with the
    greatest mean mix-energy among windows whose start lies in a vocal gap.
    - track_dur <= duration -> 0.0 (the whole track is the reel).
    - candidate starts = each gap's start with gap_start <= track_dur - duration
      (a window cannot run past the track); a gap starting later is dropped.
    - mean energy over a window = mean of mix_energy samples in
      [start*mix_hz, (start+duration)*mix_hz].
    - no usable gap (none, or all too late) -> plain argmax: the max-mean-energy
      window over start in [0, track_dur - duration] (a coarse per-sample slide).
      Honest degraded case — the start may fall mid-phrase; choose_offset logs it."""
```

**Determinism.** Both functions are total, side-effect-free, and operate on
plain sequences — the full decision tree (gap found / no gap / track too short /
gap too late / all-silent) is covered by unit tests feeding synthetic arrays.

## §3 — Vocal separation: `vocals.py`

```python
def has_demucs() -> bool:
    """True if `demucs` is importable — the gate the driver checks before the
    heavy path (importlib.util.find_spec, no actual import/torch load)."""

def separate_vocal_energy(track: str, target_hz: float = 2.0) -> tuple[list[float], float]:
    """Whole-track demucs -> vocal stem -> mono RMS -> downsample to ~target_hz.
    Returns (env, hz). Lazy `import demucs` + torch (heavy, optional). Reuses
    beats._downsample for the bin step. Raises ValueError naming
    `setup.sh --with-demucs` if demucs is not importable — callers gate on
    has_demucs() first, so this raise is defense-in-depth, not the routine path."""
```

- **Which model / call:** `htdemucs` (demucs default, bundled weights auto-fetch
  on first run to the torch cache); vocal stem = `model.sources.index("vocals")`.
  The exact `apply_model`/audio-load calls are pinned in the plan.
- **Cost:** whole-track separation is the slow step (minutes on CPU). It runs
  **once** per `choose_offset`; the result rides `MUSIC.json` as the chosen
  `start_offset`, so downstream stages never re-separate. No separate cache file
  — the offset itself is the cache.
- **Opt-in:** installed only by `setup.sh --with-demucs`. Absent → the driver
  never calls this (uses the mix-proxy), so a stock install runs start-offset
  intelligence at reduced accuracy, never crashes.

## §4 — Driver: `beats.choose_offset` + CLI

```python
def choose_offset(track: str, duration: float, *, use_vocals: bool = True) -> float:
    import librosa
    y, sr = librosa.load(track, sr=None, mono=True)     # full track
    track_dur = len(y) / sr
    if track_dur <= duration:
        # whole track is shorter than the reel — nothing to choose
        return 0.0
    mix_rms = librosa.feature.rms(y=y, hop_length=_HOP)[0]
    mix_energy, mix_hz = _downsample(mix_rms, sr, _HOP, target_hz=2.0)
    if use_vocals and vocals.has_demucs():
        env, hz = vocals.separate_vocal_energy(track)
        gaps, path = offset.vocal_gaps(env, hz), "vocal"
    else:
        # fallback: full-mix silence dips as pseudo vocal gaps (same gap logic)
        gaps, path = offset.vocal_gaps(mix_energy, mix_hz), "mix-proxy"
    off = offset.best_offset(mix_energy, mix_hz, gaps, duration, track_dur)
    # info line (stderr): the path taken + the chosen offset (never silent about a degrade)
    extra = "" if path == "vocal" else " (demucs absent — setup.sh --with-demucs for vocal-accurate)"
    _log(f"choose_offset: {off:.2f}s via {path}{extra}")
    return off
```

- **CLI `--auto-start`** (`store_true`): when set, `start_offset =
  choose_offset(track, duration)` before `analyze`. Requires `--duration`
  (a window can't be sized without the reel length) → `parser.error` if absent.
  In a **mutually exclusive group** with `--start-offset` (can't both auto-pick
  and hand-set). Explicit `--start-offset S` path is unchanged.
- **`analyze` is untouched** — `choose_offset` is a pre-step that produces the
  number `analyze` already accepts. Clean seam.
- **`use_vocals=False`** forces the proxy (used by a no-demucs unit test and by a
  caller that wants the fast path).

## §5 — Thresholds & tunables

Defaults live in `offset.py` signatures; all overridable.

| tunable | default | why |
|---|---|---|
| `thresh_frac` | `0.15` | vocal "essentially off" = <15 % of the envelope's peak. **Relative**, not absolute — a quiet master otherwise reads as all-silent (design §12 relative-gate lesson). |
| `min_gap` | `0.35` s | a real breath/phrase boundary, not a between-syllable dip. |
| `target_hz` | `2.0` | envelope resolution (matches the existing energy curve; a 0.35 s gap spans ≥ ~0.7 bins). |

## §6 — Edge cases & fail-loud

- **`--auto-start` without `--duration`** → `parser.error` (can't size a window).
- **`track_dur <= duration`** → `0.0`, no separation attempted (whole track is
  the reel).
- **No vocal gaps** (continuous vocal / thresh too low) → `best_offset` returns
  the plain argmax-energy window; `choose_offset` logs "no vocal gap — start may
  begin mid-phrase." Honest, never a silent wrong-start.
- **demucs absent + `use_vocals=True`** → mix-proxy path, logged with the
  `--with-demucs` remedy (vidstab-style warning, not a blocker).
- **demucs present but fails** (torch/model error) → the exception propagates
  (fail loud). "Not installed → proxy" is graceful; "installed but broken" is a
  bug to fix, not to silently degrade past.
- **`best_offset` invariant:** the returned offset always satisfies
  `0 <= offset <= track_dur - duration`, so `analyze` and `mix.py`'s
  `dur <= music.duration` guard stay consistent (no change to `mix.py`).

## §7 — Testing

Repo ethos: the pure decision is exhaustively unit-tested; the heavy dependency
is smoke-tested only when present (skip-if-absent, mirroring vidstab).

**Unit (fast, pure / mocked):**
- `tests/lib/test_offset.py` — `vocal_gaps`: loud/quiet/loud envelope → the quiet
  span; sub-`min_gap` dip dropped; all-loud → `()`; all-zero → one full-span gap;
  relative threshold on a scaled-down envelope still finds the gap. `best_offset`:
  a peak plus a gap leading into it → the gap-start window (not the raw peak);
  gap start past `track_dur - duration` → dropped; no gaps → argmax fallback;
  `track_dur <= duration` → `0.0`. Whole-object asserts on returned floats/spans.
- `tests/lib/test_vocals.py` — `has_demucs` monkeypatched both ways;
  `separate_vocal_energy` with `demucs` patched to a stub stem → RMS + downsample
  wiring returns a non-empty envelope; absent import → `ValueError` naming
  `--with-demucs`.
- `tests/lib/test_beats.py` (extend) — `choose_offset` with `librosa` and
  `vocals.separate_vocal_energy` mocked: `has_demucs` true → vocal path used;
  false → proxy path + the logged remedy; `track_dur <= duration` → `0.0`.
  CLI `--auto-start` without `--duration` → `SystemExit` (parser.error).

**Integration (real, `@pytest.mark.integration`):**
- `tests/integration/test_offset.py` — **(a)** no-demucs path (monkeypatch
  `has_demucs` → False) on a synthetic click WAV → returns a valid offset in
  `[0, track_dur - duration]` via the mix proxy (always runnable). **(b)**
  skip-if-demucs-absent: a synthetic track with a "vocal" tone present only in
  known spans and silent in others → `choose_offset` (vocal path) → the offset
  falls in a vocal-silent region (loose bound; demucs is not bit-exact).

## §8 — Landmines touched (montage §12)

- **Relative, not absolute, threshold** — `vocal_gaps` keys off `thresh_frac *
  max(env)`, the same relative-gate discipline that fixed the black-frame check;
  an absolute dB bar would mis-read a quiet master as all-silent.
- **Never a silent pass** — every degrade (no gap, demucs absent) is logged; the
  chosen offset always fits the track window (the `mix.py` duration guard holds).
- **No new ffmpeg filtergraph** — this stage adds no `-ss`/`lutrgb`/`scale`; it
  only chooses a number. The `-ss` audio in-point in `mix.py` is unchanged.
- **Determinism** — demucs is a neural net (not bit-exact), so tests pin the
  deterministic pure core and treat the separator as skip-if-absent smoke; the
  production offset is written once into `MUSIC.json` and reused (a re-separation
  can't silently drift a shipped reel).

## §9 — Non-goals / deferred

- **Beat/downbeat-snap of the start** — v1 starts at the gap start; aligning it
  to the nearest beat is polish, blocked on the chicken/egg with `analyze`'s grid.
- **Section detection** (build/drop/release) and **energy-arc placement** — B4
  pacing territory (§5.6); this slice picks a single strongest window, not an arc.
- **Mood-match / autonomous sourcing** (B3) — unrelated; `choose_offset` still
  takes a local file path.
- **spleeter / other separators** — demucs only; the `vocals.py` seam allows a
  swap later without touching the decision core.
- **Per-track offset cache file** — the offset lives in `MUSIC.json`; no separate
  cache is built.

## §10 — Docs to sync (in the implementation commit series)

- `docs/pipeline-map.md` — 5.5 line: note start_offset intelligence built (still
  ◐ overall — B3 sourcing/mood-match remain).
- `docs/build-status.md` — a "start-offset intelligence DONE" entry + next-action
  refresh.
- `CLAUDE.md` — registry rows for this design + its plan.
- `docs/specs/2026-07-05-montage-skillset-design.md` §5.5 — mark `start_offset`
  ("chosen fragment") + `vocal-map` ("phrase boundaries") as built (librosa-mix
  proxy + opt-in demucs).
- `docs/specs/2026-07-11-music-spine-design.md` §9 — B3/B4 still deferred; note
  start-offset intelligence landed separately.
