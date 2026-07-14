# Mood-Match — Design Spec (§5.5 sub-slice, local lane)

Closes the montage §5.5 headline gate **"mood matches SPEC"** for the `local`
music lane. Given a folder of candidate tracks and the reel's `SPEC.mood`, rank
the tracks by mood-fit → a shortlist; the agent picks the top one ("numbers
narrow, judgment picks", §5.5), then the existing `beats --auto-start` produces
the final `MUSIC.json` for the chosen track. Local, deterministic, no network,
no keys — the sibling of start-offset intelligence
(`docs/specs/2026-07-13-start-offset-intelligence-design.md`).

## Scope decisions (from brainstorming, 2026-07-13)

1. **Local lane only.** The candidate set is a **local folder** of the user's own
   tracks (`music.mode=local`). B3 autonomous sourcing (`music_find`/`music_fetch`,
   royalty-free/`any` catalogs, yt-dlp) stays deferred — networked and, in the
   `any` lane, legally gray (music-spine §9). Mood-match is the *selection* pass
   over tracks the user already has.
2. **Code lexicon (α), not an agent-supplied target.** A curated, synonym-rich
   `MOOD_ANCHORS` table maps mood words → a coarse target vector; `mood_target`
   parses free-text `SPEC.mood` into that space. Deterministic and exhaustively
   unit-testable — the true reading of §5.5's "coarse mood vector matched against
   the reel's mood". (Rejected: β, the SKILL emitting raw `{energy,brightness,pace}`
   numbers — thinner, but a non-deterministic target and it moves judgment off the
   shortlist; hybrid — YAGNI for v1.)
3. **Three coarse axes.** `energy` · `brightness` · `pace`, each `[0,1]`. A fourth
   "dynamism" axis (energy variance) is deferred (YAGNI). Numbers only need to
   *order* roughly — the agent makes the final call on the shortlist.
4. **Loudness-robust energy.** The energy axis is **peak-normalized** RMS mean, not
   raw RMS — the §12 relative-gate lesson (a quiet master must not read as
   "low-energy"). The pure core is feature-agnostic (it takes a `MoodVector`); the
   proxy lives in `mood_features` and is pinned by the integration test.
5. **Fixed normalization, not per-corpus.** Each axis maps raw librosa units → `[0,1]`
   by *fixed* reference ranges, so a track's vector is **absolute** — its rank does
   not depend on which other tracks happen to share the folder.
6. **Shortlist, not a picked track.** The artifact is `MUSIC_SHORTLIST.md`+`.json`
   (ranked candidates), mirroring `cast_candidates.json` → agent names → `cast.json`.
   The final `MUSIC.json` is still produced by `beats --auto-start` on the chosen
   track — mood-match adds no new picture/audio output.

## §1 — Architecture & files

Mirrors the start-offset split: a pure numeric core (`mood.py`, the `offset.py`
analog), a librosa extractor that maps a file into that space (`beats.mood_features`,
where librosa already lives — no second importer), and a thin driver. Five touches:

```
scripts/lib/mood.py   NEW  pure   MoodVector (3 axes, validate + JSON round-trip);
                                  MOOD_ANCHORS synonym-rich lexicon; mood_target(text)→
                                  MoodVector|None; norm01 + the three ref ranges; distance();
                                  rank(); rank_by_drive() (fallback). numpy + stdlib only.
scripts/beats.py      EDIT  add   mood_features(track)→MoodVector — lazy librosa: tempo,
                                  spectral-centroid mean, peak-normalized RMS mean → norm01.
scripts/mood.py       NEW  driver build_shortlist(folder, mood_text, out_dir): glob tracks →
                                  mood_features each → rank vs mood_target (or rank_by_drive on
                                  a zero-match) → MUSIC_SHORTLIST.{json,md}. CLI.
SKILLS/music-match/   NEW  SKILL  run the driver → present the shortlist → agent picks →
    SKILL.md                      beats <pick> --auto-start --duration <len> --out MUSIC.json.
docs                  EDIT        this spec + plan + build-status + pipeline-map + CLAUDE.md +
                                  montage §5.5 blockquote.
```

**Dependency DAG (no cycle):** `mood.py` → numpy only; `beats.py` → `offset`,
`vocals`, `mood`, `models` (librosa lazy); `scripts/mood.py` → `beats`, `mood`,
`spec`. `mood.py` imports nothing from the repo — it owns the vector space and is
pure, exactly as `offset.py` owns the envelope space.

## §2 — The pure core: `scripts/lib/mood.py`

Operates on `MoodVector`s and text only — no audio IO, no librosa. Every branch
unit-tested deterministically (the `offset.py` discipline).

### `MoodVector` — the value object

```python
@dataclass
class MoodVector:
    energy: float       # [0,1]  soft ↔ driving   (loudness-robust)
    brightness: float   # [0,1]  dark/warm ↔ airy/bright
    pace: float         # [0,1]  slow ↔ fast

    def __post_init__(self) -> None:
        for name in ("energy", "brightness", "pace"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 <= v <= 1.0:
                raise ValueError(f"MoodVector.{name} must be a number in [0, 1], got {v!r}")
            setattr(self, name, float(v))

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.energy, self.brightness, self.pace)

    def to_dict(self) -> dict: ...            # {"energy":.., "brightness":.., "pace":..}
    @classmethod
    def from_dict(cls, d: dict) -> "MoodVector": ...
```

### The lexicon + normalization refs (module constants)

```python
PACE_BPM   = (60.0, 180.0)     # tempo → pace
BRIGHT_HZ  = (500.0, 5000.0)   # spectral centroid → brightness
ENERGY_RMS = (0.0, 0.35)       # peak-normalized RMS mean → energy

# curated, synonym-rich — synonyms share their family's vector so unknowns are rare.
# Values are COARSE hand-tuned guesses (energy, brightness, pace); they only need to
# ORDER roughly — the agent picks the shortlist. All tunable in this one place.
MOOD_ANCHORS: dict[str, MoodVector] = {
    "energetic": MoodVector(0.90, 0.70, 0.85), "hype": MoodVector(0.92, 0.72, 0.88),
    "driving": MoodVector(0.85, 0.60, 0.80),   "intense": MoodVector(0.88, 0.55, 0.75),
    "chill": MoodVector(0.25, 0.50, 0.30),     "mellow": MoodVector(0.30, 0.50, 0.35),
    "calm": MoodVector(0.20, 0.45, 0.25),      "relaxed": MoodVector(0.25, 0.48, 0.30),
    "epic": MoodVector(0.80, 0.55, 0.55),      "cinematic": MoodVector(0.75, 0.50, 0.50),
    "triumphant": MoodVector(0.85, 0.65, 0.60),
    "dark": MoodVector(0.50, 0.20, 0.45),      "moody": MoodVector(0.45, 0.25, 0.40),
    "brooding": MoodVector(0.50, 0.18, 0.40),
    "happy": MoodVector(0.70, 0.85, 0.70),     "joyful": MoodVector(0.75, 0.88, 0.72),
    "upbeat": MoodVector(0.72, 0.80, 0.75),    "bright": MoodVector(0.68, 0.90, 0.68),
    "melancholic": MoodVector(0.30, 0.35, 0.35), "sad": MoodVector(0.28, 0.30, 0.30),
    "somber": MoodVector(0.30, 0.28, 0.32),
    "dreamy": MoodVector(0.30, 0.60, 0.30),    "ethereal": MoodVector(0.28, 0.65, 0.28),
    "ambient": MoodVector(0.25, 0.55, 0.25),
    "tense": MoodVector(0.75, 0.40, 0.60),     "dramatic": MoodVector(0.78, 0.45, 0.55),
    "urgent": MoodVector(0.80, 0.42, 0.70),
}
```

### Functions

```python
def norm01(x: float, lo: float, hi: float) -> float:
    """Map x from [lo, hi] onto [0, 1], clamped. hi>lo required (raise otherwise)."""

def mood_target(text: str) -> MoodVector | None:
    """Lowercase, tokenize on word boundaries, collect every token that is a
    MOOD_ANCHORS key, average their vectors axis-wise → the target. No known token
    → None (the driver then logs and falls back to rank_by_drive). Case-insensitive;
    'energetic and dark' averages the energetic + dark anchors."""

def distance(a: MoodVector, b: MoodVector,
             weights: tuple[float, float, float] = (1.0, 1.0, 1.0)) -> float:
    """Weighted Euclidean distance in the 3-axis space. Smaller = closer fit."""

def rank(candidates: Sequence[tuple[str, MoodVector]], target: MoodVector,
         weights: tuple[float, float, float] = (1.0, 1.0, 1.0)) -> list[tuple[str, float, MoodVector]]:
    """(name, vector) → sorted ascending by distance(vector, target). Returns
    (name, distance, vector). Stable on ties (input order preserved)."""

def rank_by_drive(candidates: Sequence[tuple[str, MoodVector]]) -> list[tuple[str, float, MoodVector]]:
    """Fallback when mood_target is None: sort by drive = energy + pace, DESCENDING
    (most-driving first — the most defensible order with no mood direction). Returns
    (name, drive, vector) with drive POSITIVE; the driver writes it under a `drive`
    key, not `distance`, so the two paths never conflate their score semantics."""
```

**Why Euclidean, not cosine.** The axes are already `[0,1]` and magnitude is
meaningful (energetic = *high* energy); cosine (direction-only, all vectors in the
positive orthant) would wash that out. Closest point in the cube is the right model.

## §3 — Feature extraction: `beats.mood_features`

Lives in `beats.py` because librosa already loads there (§5.5 lazy-import rule);
maps one file into the `mood.py` vector space.

```python
def mood_features(track: str) -> MoodVector:
    import librosa                                    # lazy — heavy optional dep
    y, sr = librosa.load(track, sr=None, mono=True)
    tempo = float(np.atleast_1d(
        librosa.beat.beat_track(y=y, sr=sr, hop_length=_HOP)[0])[0])
    centroid = float(np.mean(
        librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=_HOP)))
    peak = float(np.max(np.abs(y))) or 1.0            # silent track → guard /0
    rms_mean = float(np.mean(
        librosa.feature.rms(y=y / peak, hop_length=_HOP)[0]))   # peak-normalized → loudness-robust
    return MoodVector(
        energy=mood.norm01(rms_mean, *mood.ENERGY_RMS),
        brightness=mood.norm01(centroid, *mood.BRIGHT_HZ),
        pace=mood.norm01(tempo, *mood.PACE_BPM))
```

- **Peak-normalized RMS** (§Scope 4): `y / max|y|` before RMS, so mastering
  loudness cancels and the axis measures intrinsic drive, not gain.
- `_HOP` is the shared `offset.HOP` alias already in `beats.py`.
- `analyze()` is **untouched** — mood-match is orthogonal to the beat grid.

## §4 — Driver: `scripts/mood.py`

```python
AUDIO_EXT = (".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg")

def build_shortlist(folder: str, mood_text: str, out_dir: str) -> dict:
    tracks = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in AUDIO_EXT)
    if not tracks:
        raise ValueError(f"no audio files ({'/'.join(AUDIO_EXT)}) in {folder} — "
                         f"point --folder at a folder of candidate tracks")
    cands = [(p.name, beats.mood_features(str(p))) for p in tracks]
    target = mood.mood_target(mood_text)
    if target is None:
        _log(f"mood-match: '{mood_text}' matched no anchor "
             f"({', '.join(sorted(mood.MOOD_ANCHORS))}) — ranking by drive (energy+pace)")
        ranked, fallback = mood.rank_by_drive(cands), "drive"
    else:
        ranked, fallback = mood.rank(cands, target), None
    # write MUSIC_SHORTLIST.json + .md into out_dir, return {"json":..,"md":..,"ranked":..}
```

- **CLI** `python -m scripts.mood --folder DIR (--spec SPEC.json | --mood TEXT) --out-dir DIR`.
  `--spec` reads `Spec.from_json(path).mood`; `--mood` passes text directly. Exactly
  one of the two required (`ap.error` otherwise — the start-offset `--auto-start`
  precedent). Prints the shortlist paths.
- `_log` → stderr (the `beats._log` pattern), so a fallback is **never silent**.

**`MUSIC_SHORTLIST.json`:**
```json
{ "mood_text": "energetic",
  "target": {"energy": 0.9, "brightness": 0.7, "pace": 0.85},
  "fallback": null,
  "candidates": [
    {"track": "odesza.m4a", "distance": 0.08, "fit": 0.93,
     "vector": {"energy": 0.88, "brightness": 0.66, "pace": 0.82}},
    ... ] }
```
`fit = 1 / (1 + distance)` (a readable 0–1; ranking is still by `distance`).
On the **fallback** path `target` is `null`, `fallback` is `"drive"`, and each
candidate carries a positive `"drive"` key (energy+pace, sorted descending)
**instead of** `distance`/`fit` — the two score semantics never share a field. The
`.md` shows the three axes either way.

**`MUSIC_SHORTLIST.md`** — a ranked table: `#` · track · fit% · energy · brightness
· pace, plus a one-line header naming the mood text / target (or the fallback
notice). The agent reads this, picks a track, and runs `beats --auto-start`.

## §5 — SKILL: `music-match`

A thin selection pass (mirrors `footage-intake`'s cast surfacing):
1. Read context (`SPEC.json` for `mood` + `length_s`, the candidate folder path).
2. Run `python -m scripts.mood --folder <dir> --spec SPEC.json --out-dir <run>`.
3. Present the top few `MUSIC_SHORTLIST.md` rows; the human/agent picks (judgment
   on the shortlist — the §4.1 music checkpoint stays human-influenced).
4. `python -m scripts.beats <picked> --auto-start --duration <length_s> --out MUSIC.json`.

**using-montage wiring:** the music step (5) gains an *optional* pre-step — when a
candidate folder is available and `music.mode=local`, run `music-match` to pick,
then `beats --auto-start` as today. The autonomous path (an explicit track already
chosen) is unchanged: skip straight to `beats --auto-start`. Mood-match **enriches**
CP-music; it never blocks the pipeline.

## §6 — Edge cases & fail-loud

- **Empty / no-audio folder** → `ValueError` with the remedy (§4). Never an empty
  shortlist masquerading as "no good tracks".
- **Zero-match mood** → `mood_target` returns `None`; the driver logs the known
  anchors and falls back to `rank_by_drive` (a documented honest degrade, the
  `choose_offset` demucs-absent precedent) — never a crash, never a silent
  fake-match.
- **Silent track** (`max|y| == 0`) → the `or 1.0` guard avoids `/0`; energy reads
  `norm01(0,...) = 0.0`, a legitimate "no drive".
- **Out-of-range raw features** → `norm01` clamps (a 200 BPM track → pace 1.0, not
  >1), so `MoodVector.__post_init__` never rejects a real file.
- **Malformed `MoodVector` from JSON** (out-of-range / non-numeric) →
  `from_dict`→`__post_init__` raises with the remedy (a corrupt shortlist fails
  loud, not mis-ranks).

## §7 — Testing

**Unit (fast, pure — no librosa):** `tests/lib/test_mood.py`
- `MoodVector` — round-trip `to_dict`/`from_dict`; raises on `energy>1`,
  `brightness<0`, a `bool`, a non-number, a missing key.
- `MOOD_ANCHORS` — every value is a valid `MoodVector`; every key is lowercase; the
  synonym families exist (spot-check a few).
- `norm01` — endpoints (lo→0, hi→1), midpoint, below-lo clamps to 0, above-hi
  clamps to 1, `hi<=lo` raises.
- `mood_target` — single anchor; multi-word average (`"energetic dark"` → the mean
  of the two); case-insensitive (`"ENERGETIC"`); a synonym resolves; punctuation
  tolerated (`"energetic, driving!"`); zero-match → `None`; empty string → `None`.
- `distance` — identical vectors → 0; a known pair → the hand-computed value;
  weights scale one axis.
- `rank` — orders ascending by distance; a tie preserves input order; empty
  candidates → `[]`.
- `rank_by_drive` — orders by `energy+pace` descending; the score slot is the
  **positive** drive (`energy+pace`), which the driver writes under a `drive` key
  (never `distance`), so the two score semantics never share a field.

**Integration (real librosa, `@pytest.mark.integration`):** `tests/integration/test_mood.py`
- `mood_features` on synthetic known signals (numpy → temp WAV): a **bright** tone
  (high-freq sine) reads higher `brightness` than a **dark** one (low-freq); a
  **fast** click track reads higher `pace` than a slow one; a loud vs a quiet copy
  of the *same* tone read **equal** energy (proves peak-normalization). All ±tol —
  the `test_beats` synthetic-fixture ethos (a real dep, a known-answer input).
- **Golden** — a folder of 2–3 synthetic WAVs (one bright/fast "energetic", one
  dark/slow "chill") + `build_shortlist(folder, "energetic", …)` → the energetic
  track ranks first, `MUSIC_SHORTLIST.json` round-trips, `.md` renders. Proves the
  real driver wiring the unit test mocks.
- Driver unit-level (mocked `mood_features`, `@pytest.mark.integration` not needed):
  a fake folder → ranking order + both files written; empty folder → `ValueError`;
  an unrecognized mood → the `rank_by_drive` fallback + the logged notice.

## §8 — Landmines touched (montage §12)

- **Loudness / absolute-threshold** — the energy axis is **peak-normalized** RMS
  (§Scope 4), the same relative-bar discipline that fixed the black-frame gate and
  `vocal_gaps`. A quiet master does not read as low-energy.
- **Determinism** — librosa is not bit-exact on real audio, so the anchors +
  normalization refs are **fixed constants** and the tests pin **synthetic
  known-answer** fixtures with tolerances; a track's vector is absolute (fixed
  refs, not per-corpus) so ranking can't silently drift with the folder contents.
- **Never a silent degrade** — a zero-match mood *logs* and falls back to
  drive-ranking; an empty folder *raises*; neither returns a plausible-looking
  wrong shortlist.
- **No pixel/seek ops** — mood-match is audio-analysis only; it adds no `-ss`,
  `lutrgb`, `scale`, or colour op, so none of the render-graph landmines apply.

## §9 — Non-goals / deferred

- **B3 autonomous sourcing** — `music_find`/`music_fetch`, royalty-free (`free`)
  and copyrighted (`any`, legally gray) catalogs, yt-dlp, `music.mode` lanes,
  trend-presence ranking. Mood-match ranks a **local folder** the user supplies.
- **Catalog-metadata mood** — Spotify `audio-features` (valence/danceability),
  iTunes/Deezer. Needs network + keys; v1 measures mood from the **audio** locally.
- **A 4th "dynamism" axis** (energy variance / build-drop) — YAGNI; 3 axes order
  well enough for a shortlist.
- **Per-track feature caching** — re-analyzing a folder each run is acceptable for
  v1 (mirrors intake's per-run CV pass); a `.mood.json` sidecar cache is a later
  optimization.
- **ML-embedding mood** — no local text/audio embedding model in this stack; the
  curated lexicon is the deterministic, wheels-free choice.
- **Section/beat-aware mood** — a per-section mood arc belongs with B4 pacing (§5.6).
- **Raw-BPM column** in the shortlist — the axes are shown normalized `[0,1]`;
  surfacing the raw tempo is a cheap later nicety, not needed to pick.

## §10 — Doc-sync (updated on completion)

- `docs/build-status.md` — a "Done" entry + the "Next action" refresh.
- `docs/pipeline-map.md` — the 5.5 row: `mood-match ✅` (5.5 stays ◐ until B3).
- `CLAUDE.md` — two registry rows (this spec + its plan).
- `docs/specs/2026-07-05-montage-skillset-design.md` — a §5.5 "Built" blockquote
  (mood-match local, α lexicon; B3 sourcing still deferred).
- `docs/specs/2026-07-11-music-spine-design.md` — a §9 cross-ref (mood-match landed).
