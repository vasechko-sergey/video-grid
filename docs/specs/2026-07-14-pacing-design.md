# Pacing (energy spine) — Design Spec (§5.6, Phase B4)

> **Superseded in part (2026-07-24).** The generator half of this design — a slot's
> length derived from local energy via a 2/4/8 beat ladder — is replaced by
> [scenario-first pacing](2026-07-24-scenario-first-pacing-design.md): the footage owns
> the cut and this stage fits a grid to it. The energy curve, the `Slot`/`Spine`
> contracts and the beat-alignment goal all survive.

Closes the montage §5.6 stage **`pacing → PACING.md`** — the last real feature-❌
of the conveyor (5.4 trend-scan is YAGNI). Given the reel's `MUSIC.json` (beat
grid + RMS energy curve + duration), derive an **energy spine**: an ordered list
of beat-aligned **slots**, each with a target length and an energy level, cut
density rising with the music's energy, hook first. `edit-plan` (§5.7) then binds
its selected episodes to the slots (`beat_slot` + per-episode target length), so
"the mood matches, not two glued halves" becomes **structural**, not eyeballed
(§5.6). Pure, deterministic, no network, no new heavy dep — the sibling of
mood-match (`docs/specs/2026-07-13-mood-match-design.md`) and start-offset
intelligence (`docs/specs/2026-07-13-start-offset-intelligence-design.md`): a pure
numeric core + a thin driver + a SKILL + a real-fixture golden.

## Scope decisions (from brainstorming, 2026-07-14)

1. **Authoring spine only.** B4 = role (1): `music → PACING → edit-plan binds
   episodes to slots`. Role (2), the **retry-time auto-fix** (`build_reel`'s
   `length` failure re-times the spine), stays deferred — it touches
   `build_reel`/`reel_orchestration` and is a separate slice (landed
   2026-07-18 as its own slice — see `docs/specs/2026-07-18-length-retime-design.md`);
   the existing `escalate_to="pacing"` stop-and-report is **unchanged**. §5's
   pacing-gate **back-edge** (spine won't fit → auto re-pick
   `MUSIC.start_offset`) is also deferred; v1 **reports** the misfit, never
   silently re-times. (Also landed 2026-07-18, in the same slice — but as a pure
   `min(realized, fragment)` re-time in `edit_plan.build_edl`, **not** the literal
   `start_offset` re-pick above, which stays the manual `beats --auto-start` rung.)
2. **Sections derived from the energy curve.** `MUSIC.json` stores an `energy[]`
   RMS curve + `energy_hz` but **no** section boundaries; `pacing.py` segments the
   energy curve itself (min-max normalized within the track, beat-aligned bands) —
   **zero** change to `beats.py`/`MusicSpec`, one code path. `energy[]` is the exact
   B4 consumer the music spine reserved ("recorded now but unread"; `analyze`'s own
   comment reads "B4-ready"). Librosa novelty/recurrence section detection stays
   deferred (music-spine §9 explicitly parked it "added when B3/B4 consume them").
3. **Structural slot contract, not advisory markdown.** `PACING.json` is a typed
   `Spine` of `Slot`s (a config-spec, deterministic, golden-pinned), which
   `edit-plan` **binds to**. (Rejected: an advisory `PACING.md` of loose directives
   the agent reads softly — untestable, leaves `beat_slot` fuzzy, against the repo's
   config-spec + fail-loud + golden ethos.)
4. **`target_dur = MUSIC.duration`.** The chosen track fragment is the canvas; the
   spine covers `[0, duration]` exactly (so the length gate passes by construction).
   `SPEC.length_s` is a **cross-check** only — a disagreement is logged with the
   remedy (re-pick `start_offset`), the spine still follows the fragment.
5. **Cut density ∝ energy, hook first.** High-energy beats → **short** slots (fast
   cuts); low-energy → **long** slots (a maneuver shown fully) — the §5.6 wording
   verbatim. The first slot is a short attention-grab `hook` regardless of its band.
   The **number** of slots is emergent from the music, never hand-set.
6. **Pacing owns length/energy per position; selection still owns which footage.**
   The spine is footage-blind (music only, runs before edit-plan). `edit-plan`'s
   `selection.json` (agent judgment) still decides **which** window fills each slot;
   pacing supplies the beat-aligned **target length + energy hint** per slot. A
   slot-vs-episode **count** mismatch is zip-to-min + a logged over/underflow report
   (never a silent drop).

## §1 — Architecture & files

Mirrors the mood-match / start-offset split: a pure numeric core (`pacing.py`, the
`offset.py`/`mood.py` analog — stdlib only, no numpy/librosa), a thin driver
(`scripts/pacing.py`), a binding into the already-shipped `edit_plan.py`, a SKILL,
and docs. The spine's inputs are all **already in `MUSIC.json`**, so the core takes
no audio dep — it is bit-exact and its golden pins **exact** slots (unlike mood's
tolerance goldens).

```
scripts/lib/pacing.py   NEW  pure   Slot (index/start/dur/energy/kind, validate + JSON);
                                    Spine (slots/target_dur/tempo, validate contiguity +
                                    hook-first + sum, to_dict/from_dict/from_json/to_markdown);
                                    band constants; build_spine(beats,energy,energy_hz,duration,
                                    tempo)→Spine + _beat_energy/_kind/_beats_per_slot helpers.
                                    stdlib only (statistics.fmean) — NO numpy, NO librosa.
scripts/pacing.py       NEW  driver build_pacing(music_json, out_dir, spec_json=None): MusicSpec.
                                    from_json → build_spine → write PACING.{json,md}; SPEC.length_s
                                    cross-check log. CLI mirrors scripts/mood.py.
scripts/lib/edit_plan.py EDIT add   build_edl(..., pacing=None): when a Spine is supplied, bind the
                                    i-th selected episode to slot i (beat_slot=i, dur←slot.dur);
                                    zip-to-min; log over/underflow. Default None → today's behavior.
scripts/edit_plan.py    EDIT  add   --pacing PACING.json (optional) → build_edl(pacing=...).
scripts/montage.py      EDIT  flip  Stage("pacing", "PACING.md", "deferred"→"optional", …).
SKILLS/pacing/SKILL.md  NEW  SKILL  run the driver → present the spine table → pass PACING.json to
                                    edit-plan. + using-montage step-6 wiring (optional, enriches).
docs                    EDIT        this spec + plan + build-status + pipeline-map + CLAUDE.md +
                                    montage §5.6 blockquote + music-spine §9 + using-montage design.
```

**Dependency DAG (no cycle):** `pacing.py` → stdlib only (owns the spine space,
exactly as `offset.py` owns the envelope space and `mood.py` the vector space);
`scripts/pacing.py` → `models` (MusicSpec), `spec` (Spec), `pacing`;
`edit_plan.py` → `pacing` (for the optional `Spine` type + `from_json`).
`beats.py`, `MusicSpec`, `mix.py`, `check_reel` are **untouched**.

## §2 — The pure core: `scripts/lib/pacing.py`

Operates on numbers only — no audio IO, no librosa, no numpy (the `mood.py`
discipline). Every branch unit-tested deterministically.

### `Slot` — one beat-aligned span of the spine

```python
KINDS = ("hook", "build", "peak", "release")

@dataclass(frozen=True)
class Slot:
    index: int          # 0-based position in the spine
    start: float        # reel-relative sec; slot 0 starts at 0.0
    dur: float          # slot length (→ the bound episode's target window length)
    energy: float       # [0,1] mean normalized RMS over the slot
    kind: str           # ∈ KINDS

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise ValueError(f"Slot.index must be a non-negative int, got {self.index!r}")
        for name in ("start", "dur", "energy"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"Slot.{name} must be a number, got {v!r}")
            object.__setattr__(self, name, float(v))
        if self.start < 0:
            raise ValueError(f"Slot.start must be >= 0, got {self.start}")
        if self.dur <= 0:
            raise ValueError(f"Slot.dur must be > 0 (a zero-width slot means two beats "
                             f"coincide — the beat grid is malformed), got {self.dur}")
        if not 0.0 <= self.energy <= 1.0:
            raise ValueError(f"Slot.energy must be in [0, 1], got {self.energy}")
        if self.kind not in KINDS:
            raise ValueError(f"Slot.kind {self.kind!r} not in {KINDS}")

    def to_dict(self) -> dict: ...           # {"index","start","dur","energy","kind"}
    @classmethod
    def from_dict(cls, d: dict) -> "Slot": ...
```

### `Spine` — the ordered energy skeleton (`PACING.json`)

```python
_TOL = 1e-6

@dataclass(frozen=True)
class Spine:
    slots: tuple[Slot, ...]
    target_dur: float       # = MUSIC.duration; the spine covers [0, target_dur] exactly
    tempo: float

    def __post_init__(self) -> None:
        if not isinstance(self.slots, tuple) or not self.slots:
            raise ValueError("Spine.slots must be a non-empty tuple of Slot — build_spine "
                             "found no beats; check the track/window")
        for want, s in enumerate(self.slots):
            if not isinstance(s, Slot):
                raise ValueError(f"Spine.slots[{want}] must be a Slot, got {s!r}")
            if s.index != want:
                raise ValueError(f"Spine.slots must be index-ordered 0..N-1; slot {want} "
                                 f"has index {s.index}")
        if self.slots[0].kind != "hook":
            raise ValueError(f"Spine.slots[0].kind must be 'hook' (hook first, §5.6), "
                             f"got {self.slots[0].kind!r}")
        if abs(self.slots[0].start) > _TOL:
            raise ValueError(f"Spine.slots[0].start must be 0.0 (the reel starts at 0), "
                             f"got {self.slots[0].start}")
        for a, b in zip(self.slots, self.slots[1:]):
            if abs((a.start + a.dur) - b.start) > _TOL:
                raise ValueError(f"Spine slots must be contiguous: slot {a.index} ends at "
                                 f"{a.start + a.dur} but slot {b.index} starts at {b.start}")
        total = sum(s.dur for s in self.slots)
        if abs(total - self.target_dur) > 1e-3:
            raise ValueError(f"Spine slot durations sum to {total}, not target_dur "
                             f"{self.target_dur} — the spine must cover the fragment exactly")
        if not isinstance(self.tempo, (int, float)) or self.tempo <= 0:
            raise ValueError(f"Spine.tempo must be a positive BPM, got {self.tempo!r}")

    def to_dict(self) -> dict:
        return {"target_dur": self.target_dur, "tempo": self.tempo,
                "slots": [s.to_dict() for s in self.slots]}

    @classmethod
    def from_dict(cls, d: dict) -> "Spine": ...        # rebuild Slots; missing key → remedy
    @classmethod
    def from_json(cls, path: str | Path) -> "Spine": ...
    def to_markdown(self) -> str: ...                  # header + a `# | start–end | dur | energy | kind` table
```

### Band constants + helpers (tunable in one place)

```python
LOW_BAND, HIGH_BAND = 0.33, 0.66          # normalized-energy band thresholds
SLOW_BEATS, MID_BEATS, FAST_BEATS = 8, 4, 2   # beats per slot by band (cut density ∝ energy)
HOOK_BEATS = 2                            # the first slot: short, attention-grab
_FLAT_EPS = 1e-9                          # energy range below this → treat as uniform

def _kind(n: float) -> str:               # normalized energy → band label
    return "peak" if n >= HIGH_BAND else "build" if n >= LOW_BAND else "release"

def _beats_per_slot(n: float) -> int:     # normalized energy → slot span in beats
    return FAST_BEATS if n >= HIGH_BAND else MID_BEATS if n >= LOW_BAND else SLOW_BEATS

def _beat_energy(beats, energy, energy_hz, duration) -> list[float]:
    """Per-beat mean RMS, MIN-MAX normalized within the track → [0,1]. Beat i spans
    [beats[i], beats[i+1]) (last → duration). A flat track (range < _FLAT_EPS) → all
    0.5 (uniform 'build'). Relative, not absolute — §12 loudness discipline."""
    edges = list(beats) + [duration]
    raw = []
    for i in range(len(beats)):
        i0 = max(0, round(edges[i] * energy_hz))
        i1 = max(i0 + 1, round(edges[i + 1] * energy_hz))
        seg = energy[i0:i1] or energy[i0:i0 + 1] or energy[-1:]
        raw.append(fmean(seg))
    lo, hi = min(raw), max(raw)
    return [0.5 if (hi - lo) < _FLAT_EPS else (r - lo) / (hi - lo) for r in raw]
```

### `build_spine`

```python
def build_spine(beats: Sequence[float], energy: Sequence[float], energy_hz: float,
                duration: float, tempo: float) -> Spine:
    """Fold the beat grid + energy curve into a beat-aligned energy spine (§5.6).
    Greedy left-to-right: the first slot is a HOOK_BEATS hook; thereafter each slot
    spans _beats_per_slot(local energy) beats — fewer when loud (fast cuts), more when
    quiet. Slot boundaries snap to beat times; slot 0 starts at 0.0 and the last slot
    ends at `duration`, so the spine covers [0, duration] exactly. Deterministic."""
    if not beats:
        raise ValueError("build_spine got no beats — MUSIC.json analyze() found none; "
                         "check the track/window (a spine needs a beat grid)")
    n = _beat_energy(beats, energy, energy_hz, duration)
    slots, i = [], 0
    while i < len(beats):
        first = not slots
        span = HOOK_BEATS if first else _beats_per_slot(n[i])
        j = min(i + span, len(beats))
        start = 0.0 if first else beats[i]
        end = duration if j >= len(beats) else beats[j]
        e = fmean(n[i:j])
        slots.append(Slot(len(slots), start, end - start, e, "hook" if first else _kind(e)))
        i = j
    return Spine(tuple(slots), float(duration), float(tempo))
```

`fmean` is `statistics.fmean` (stdlib, float). No numpy — the core stays wheels-free
and bit-exact.

## §3 — The derivation, worked

Input `MUSIC.json` (a 120 BPM, 12 s fragment; `energy_hz≈2.0`, beats every 0.5 s):
the first third is quiet (intro), the middle third loud (drop), the last third
mid (release). `build_spine`:

1. `_beat_energy` → one normalized value per beat, min-max scaled so the drop reads
   ≈1.0 and the intro ≈0.0 **relative to this track** (a quiet master is not read as
   globally low — §12).
2. Slot 0 = **hook**: `HOOK_BEATS=2` beats (~1 s), `start=0.0`.
3. The intro beats fall in the **low** band → `SLOW_BEATS=8` per slot (long, one cut
   holds a maneuver). The drop beats → **high** band → `FAST_BEATS=2` (rapid cuts).
   The release → **mid** → `MID_BEATS=4`. So the drop yields **more, shorter** slots
   than the intro: cut density rises with energy, exactly §5.6.
4. Boundaries land on beat times (the cuts fall on beats — the §5.5 cut-map / ±60 ms
   beat gate); the last slot runs to `duration=12.0`; `sum(dur)=12.0`.

`kind` is an **energy-band label** (`peak`/`build`/`release` by RMS), **not a
temporal role** — a quiet intro and a quiet outro both read `release`; positional
semantics (a true build→drop→outro arc) are a §10 non-goal. `hook` is the sole
position-driven label (always slot 0).

The spine is footage-blind — it is the **skeleton**; edit-plan hangs footage on it.

## §4 — Driver: `scripts/pacing.py`

```python
_LEN_TOL = 0.5      # s; SPEC.length_s vs MUSIC.duration cross-check band

def build_pacing(music_json: str, out_dir: str, spec_json: str | None = None) -> dict:
    m = models.MusicSpec.from_json(music_json)
    spine = pacing.build_spine(m.beats, m.energy, m.energy_hz, m.duration, m.tempo)
    if spec_json:
        want = spec.Spec.from_json(spec_json).length_s
        if abs(want - m.duration) > _LEN_TOL:
            _log(f"pacing: SPEC.length_s {want:.1f}s != MUSIC.duration {m.duration:.1f}s — "
                 f"the spine follows the chosen track fragment ({m.duration:.1f}s); "
                 f"re-run beats --auto-start --duration {want:.0f} to re-pick the fragment")
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "PACING.json").write_text(json.dumps(spine.to_dict(), indent=2))
    (out / "PACING.md").write_text(spine.to_markdown())
    return {"json": str(out / "PACING.json"), "md": str(out / "PACING.md"), "spine": spine}
```

- **CLI** `python -m scripts.pacing --music MUSIC.json [--spec SPEC.json] --out-dir DIR`.
  `--music` + `--out-dir` required; `--spec` optional (cross-check only). Prints the
  two written paths (the `scripts/mood.py` precedent).
- `_log` → stderr (the `beats._log` pattern) — the length disagreement is **never
  silent**.

**`PACING.json`** (the §3 fragment, algorithm-exact — 24 beats, `HOOK_BEATS=2`,
`SLOW/MID/FAST = 8/4/2`):
```json
{ "target_dur": 12.0, "tempo": 120.0,
  "slots": [
    {"index": 0, "start": 0.0,  "dur": 1.0, "energy": 0.05, "kind": "hook"},
    {"index": 1, "start": 1.0,  "dur": 4.0, "energy": 0.28, "kind": "release"},
    {"index": 2, "start": 5.0,  "dur": 1.0, "energy": 0.95, "kind": "peak"},
    {"index": 3, "start": 6.0,  "dur": 1.0, "energy": 0.95, "kind": "peak"},
    {"index": 4, "start": 7.0,  "dur": 1.0, "energy": 0.95, "kind": "peak"},
    {"index": 5, "start": 8.0,  "dur": 2.0, "energy": 0.50, "kind": "build"},
    {"index": 6, "start": 10.0, "dur": 2.0, "energy": 0.50, "kind": "build"} ] }
```
The loud third (beats 8–15, `5–8 s`) yields **three** 1 s `peak` slots; the quiet
intro is **one** long `release` slot — cut density ∝ energy. (Slot 1 bleeds across
the intro→drop boundary because `SLOW_BEATS=8` is coarse relative to a 8-beat third
— honest v1 behavior, not a bug; phrase-aware grouping is §10-deferred.)
**`PACING.md`** — a one-line header (`target_dur`, `tempo`, slot count) + a table:
`#` · `start–end` · `dur` · `energy` · `kind`. The agent reads it, sanity-checks
the arc, and passes `PACING.json` to edit-plan.

## §5 — edit-plan binding (`edit_plan.build_edl`)

The spine is worthless unbound (the "built-but-unused artifact" smell). `build_edl`
gains an optional `pacing` parameter — a `Spine` (or `None`, today's behavior):

- **Bind by position, zip-to-min.** For `i in range(min(len(episodes), len(slots)))`:
  set `episode[i].beat_slot = i` and **re-time the window to the slot**:
  `episode[i].dur = slot[i].dur`, window **start preserved** (selection's in-point).
  Cuts then fall on beats and `sum(episode.dur) = MUSIC.duration` by construction —
  the length gate passes.
- **Shortfall.** If a selected window is **shorter** than its slot, keep the window's
  own `dur` (can't invent footage) and `_log` a shortfall — the length gate sees it
  honestly; pacing never stretches a clip.
- **Over/underflow.** More episodes than slots → the tail keeps `beat_slot=None`,
  `dur` unchanged, and a report line names the count ("N episodes beyond the M-slot
  spine — extend the fragment or drop episodes"). More slots than episodes → the
  unfilled tail slots are logged. Never a silent drop (§4.1).
- **`pacing=None`** → **unchanged**: `beat_slot` stays `None`, windows keep their
  selection lengths (the no-pacing v1 path, edit-plan-spine §"soft inputs optional").

`scripts/edit_plan.py` gains `--pacing PACING.json`; when present it loads
`Spine.from_json` and threads it into `build_edl`. This is the only edit-plan change
— `window_to_episode`, the preflight, and the EDL contract are untouched (the
`beat_slot`/`target_dur` fields already exist, waiting since SP1/SP3).

## §6 — SKILL: `pacing` + router wiring

`SKILLS/pacing/SKILL.md`, a thin pass mirroring `music-match`:
1. Read context (`MUSIC.json` from music-and-mood; optionally `SPEC.json` for the
   length cross-check).
2. `python -m scripts.pacing --music <run>/MUSIC.json --spec <run>/SPEC.json --out-dir <run>`.
3. Present the `PACING.md` slot table (the energy arc — hook, the drop's fast slots,
   the release) as a sanity check; a wrong-looking arc means re-pick the fragment.
4. Pass `<run>/PACING.json` to edit-plan (`--pacing`).

Announce on entry: **"Using pacing to derive the reel's energy spine from the music."**

**using-montage wiring:** the router's stage 6 (`pacing`) flips `deferred → optional`
(the reel-brief/titles precedent). When `MUSIC.json` exists, run `pacing`, then
edit-plan with `--pacing`; when it doesn't (a music-less reel), skip — named, not
silent — and edit-plan runs pacing-less (`beat_slot=None`). Pacing **enriches** the
edit; it never blocks the pipeline.

## §7 — Edge cases & fail-loud

- **No beats** → `build_spine` raises with the remedy (a spine needs a grid);
  `MusicSpec` already guarantees ≥1 beat, so this is defense-in-depth.
- **One / very few beats** (`len(beats) ≤ HOOK_BEATS`) → a single `hook` slot
  covering `[0, duration]`. Valid (`sum=duration`, hook first).
- **Flat energy** (`max-min < _FLAT_EPS`) → every beat reads `0.5` → uniform `build`
  slots (`MID_BEATS`). No divide-by-zero, no noise amplified into fake bands.
- **Coincident beats** (a zero-width slot) → `Slot.__post_init__` raises (the beat
  grid is malformed) — loud, not a silent zero-length cut.
- **`SPEC.length_s` ≠ `MUSIC.duration`** → logged with the re-pick remedy; the spine
  still follows the fragment (scope 4) — never a silent re-time.
- **Slot/episode count mismatch** → zip-to-min + an over/underflow report (§5) — the
  reel is built from what matches, the excess is named.
- **Malformed `PACING.json`** (gap, wrong sum, non-hook first, out-of-range energy)
  → `Spine`/`Slot` `from_dict`→`__post_init__` raises with the remedy — a corrupt
  spine fails loud, never mis-binds the edit.

## §8 — Testing

**Unit (fast, pure — no librosa/numpy):** `tests/lib/test_pacing.py`
- `Slot` — round-trip `to_dict`/`from_dict`; raises on `dur<=0`, `energy>1`, a bad
  `kind`, a `bool` index, a negative `start`.
- `Spine` — round-trip; raises on a gap between slots, a wrong duration sum, a
  non-`hook` slot 0, `start!=0`, misordered indices, empty slots, a non-positive
  tempo.
- `_beat_energy` — a known (beats, energy, energy_hz) → the hand-computed per-beat
  means, min-max normalized; a flat curve → all `0.5`; a coarse (`2 Hz`) curve with
  fewer samples than beats still yields one value per beat (the empty-segment guard).
- `_kind` / `_beats_per_slot` — band boundaries exact (`0.33`, `0.66` inclusive on
  the upper band); below/above map to the right label + span.
- `build_spine` — the load-bearing cases, **exact** asserts (bit-exact core):
  - uniform energy → uniform `MID_BEATS` slots after the hook; slot 0 is `hook`,
    `HOOK_BEATS` long, `start==0.0`.
  - a loud middle third yields **more, shorter** slots there than a quiet third
    (cut density ∝ energy) — assert the peak region's slot count > the release
    region's.
  - `sum(dur) == duration` exactly; every interior boundary equals a beat time; the
    last slot ends at `duration`.
  - degenerate: 1 beat → a single `hook` slot; `HOOK_BEATS`-only track → one slot.
- `to_markdown` — renders one row per slot + the header; the hook row is first.

**Driver (pure core, real `MusicSpec.from_json` — no librosa):** `tests/test_pacing_driver.py`
- `build_pacing` on a synthetic `MUSIC.json` (hand-written dict → temp file) writes
  `PACING.json` + `PACING.md`, both round-trip, and the returned `spine` validates.
- `--spec` with a mismatched `length_s` → the stderr cross-check log fires; a
  matching one → silent. CLI prints the two paths.

**edit-plan binding:** `tests/lib/test_edit_plan.py` (extend)
- `build_edl(pacing=spine)` → `episode[i].beat_slot == i` and `episode[i].dur ==
  slot[i].dur` for the zipped range; a short window keeps its own `dur` + logs; more
  episodes than slots → the tail `beat_slot is None` + the overflow report; `pacing=
  None` → `beat_slot is None` and windows unchanged (the regression guard).

**Integration (real librosa, `@pytest.mark.integration`):** `tests/integration/test_pacing.py`
- Synthesize a WAV with a **quiet half then a loud half** (numpy → temp WAV), run
  `beats.analyze` → a real `MUSIC.json`, then `build_spine` → assert the loud half
  carries **more** slots than the quiet half (the end-to-end energy→density proof the
  unit test's hand-built curve stands in for) and `sum(dur)≈duration`. The
  `test_mood`/`test_beats` synthetic-known-answer ethos.

## §9 — Landmines touched (montage §12)

- **Relative, not absolute, energy** — per-beat energy is **min-max normalized within
  the track** (`_beat_energy`), the §12 relative-gate discipline (the black-frame gate,
  `vocal_gaps`, mood's peak-norm). The drop is "loud **for this track**"; a quiet
  master still gets a real arc, a hot master isn't all-`peak`.
- **Determinism** — the core is pure stdlib (`statistics.fmean`), **no librosa/numpy**,
  so `build_spine` is bit-exact and the goldens pin **exact** slots (stronger than
  mood's tolerance goldens). Bands + beats-per-slot are fixed constants in one place.
- **Beat-aligned cuts** — slot boundaries **are** beat times, so the cuts edit-plan
  places land on beats (the §5.5 cut-map, the `check_reel` ±60 ms advisory). Pacing
  adds no `-ss`, `lutrgb`, `scale`, or colour op — it is timing metadata; extract's
  frame-accurate seek (§12 `-ss` after `-i`) is unchanged (pacing only sets `dur`
  numbers, extract cuts them as before).
- **Never a silent degrade** — length disagreement *logs*, count mismatch *reports*,
  a malformed spine *raises*, a coincident-beat slot *raises*. No plausible-looking
  wrong spine escapes.

## §10 — Non-goals / deferred

- **Retry-time auto-fix** (role 2: `build_reel`'s `length` failure re-times the spine)
  — **landed 2026-07-18**, `docs/specs/2026-07-18-length-retime-design.md`: a
  within-band shortfall re-times the target to the reel's real length and
  re-checks; an over-length reel and a shortfall past the band still escalate
  to pacing exactly as before.
- **Pacing-gate back-edge** (spine won't fit the fragment → auto re-pick
  `MUSIC.start_offset`, §5) — **landed 2026-07-18** as a pure re-time, not the
  literal re-pick: `docs/specs/2026-07-18-length-retime-design.md` §4 sets a
  paced EDL's `target_dur = min(realized footage, spine.target_dur)`.
  Re-picking `MUSIC.start_offset` via librosa stays **deferred** — `choose_offset`
  already exists to re-pick manually.
- **Librosa section detection** (`sections[]` in `MUSIC.json` via novelty/recurrence)
  — deferred (scope 2); energy-curve banding is the v1 section source.
- **Musical-phrase-aware grouping** (downbeats, 4/8-bar phrases) — v1 groups by
  fixed beats-per-band; phrase detection is a later refinement.
- **Pacing driving episode selection / order** — no; `selection.json` (edit-plan
  judgment) still owns *which* footage and its order; pacing owns the per-slot length
  + energy target (scope 6).
- **Per-section mood arc** — the mood-match §9 parked it here; still deferred (a slot
  carries an energy scalar, not a mood vector, in v1).
- **Adaptive hook length** — `HOOK_BEATS` is a fixed constant; a brief-driven hook
  length (`SPEC.hook`) is a later nicety.

## §11 — Doc-sync (updated on completion)

- `docs/build-status.md` — a "Done" entry (pacing/energy-spine, B4 authoring) + the
  "Next action" refresh (B4 authoring done; remaining Phase B = ambient/SFX 5.12 +
  the retry-time length auto-fix).
- `docs/pipeline-map.md` — the 5.6 row `❌ → ✅`; tally `12✅ → 13✅ · 2◐ · 1❌`
  (only 5.4 trend-scan ❌); the Phase B roadmap line (B4 authoring landed).
- `CLAUDE.md` — two registry rows (this spec + its plan).
- `docs/specs/2026-07-05-montage-skillset-design.md` — a §5.6 "Built" blockquote
  (energy-spine from the RMS curve; retry auto-fix + librosa sections deferred).
- `docs/specs/2026-07-11-music-spine-design.md` — the §9 B4 bullet: **landed**
  2026-07-14 (this spec/plan), `energy[]` now has its consumer.
- `docs/specs/2026-07-12-using-montage-design.md` — stage 6 `pacing` `deferred →
  optional`, wired before edit-plan.
