# Music sourcing (B3) — design

**Stage:** montage §5.5, network lane. The last piece of stage 5.5 (music-and-mood).

**Goal:** when the brief asks for music but the user names no track and points at no
local folder, **source candidate tracks from the internet**, rank them by fit to
`SPEC.mood` exactly as the local lane does, and (after the agent/user picks) download
the pick to a cache for the rest of the pipeline. Closes the montage §5.5 gate
"track sourced (per `music.mode`)" for the `free` and `any` rights lanes.

**Relationship to what ships:** the `local` lane (mood-match — rank a user folder)
already ships (`docs/specs/2026-07-13-mood-match-design.md`). This adds the two
**networked** lanes. Discovery **reuses the entire mood engine** — `beats.mood_features`
+ `mood.rank` — so sourcing is mostly plumbing (catalog query + download), not new
scoring.

---

## §1 — Scope

**Build:** autonomous **find** (`scripts/music_find.py`) + **fetch**
(`scripts/music_fetch.py`), the two network boundaries they sit on
(`scripts/lib/catalog.py`, `scripts/lib/fetch.py`), the `music-source` SKILL, the
`setup.sh --with-sourcing` opt-in dep, and docs. The rights lanes are `free`
(royalty-free) and `any` (full autonomous incl. copyrighted).

**Do not build** (see §13): trend-presence ranking (blocked on 5.4 trend-scan),
Spotify `audio-features` (deprecated Nov-2024 for new apps), catalog-metadata mood
(we measure mood locally from previews), a merge-all-catalogs default, per-track
feature caching beyond the basic download cache.

---

## §2 — Trigger & contract (already in `Spec`)

`scripts/lib/spec.py` already carries the contract — this stage is a **consumer**, it
adds no `Spec` field:

- `Spec.music: str` — a **track name** / `"auto"` / `"none"`.
- `Spec.music_mode: str ∈ ("local", "free", "any")` — the rights lane, default `"free"`.

Routing (the `music-source` SKILL, §11 of the router):

| `music` | `music_mode` | action |
|---------|--------------|--------|
| `"none"` | — | skip music entirely |
| any | `"local"` | **music-match** (folder lane, already ships) — not this stage |
| `"auto"` | `"free"` \| `"any"` | **this stage**: discovery → shortlist → pick → fetch |
| `"<track name>"` | `"free"` \| `"any"` | **this stage**: resolve the named track directly → fetch (no ranking) |

Beat/mood analysis is **always local** (`beats.py`) regardless of lane — sourcing only
changes where the audio file comes from.

---

## §3 — Rights lanes

The lane decides **which catalog** discovery queries and **how** fetch downloads.

- **`free`** — royalty-free only, and it **never dead-ends on a missing key**. Two
  Creative-Commons catalogs, resolved at runtime by `catalog._free_source()`:
  **ccMixter** (`dig.ccmixter.org`, **no key**) is the zero-config default; **Jamendo**
  (richer catalog + genre/tags) is an automatic **upgrade** when a free
  `JAMENDO_CLIENT_ID` is present. Both return a preview URL + a **direct legal download
  URL** + the license string; download is a **direct HTTP GET** — never yt-dlp. Safe
  default for a distributed skill-set: every file carries a recorded CC license.
- **`any`** — full autonomous, includes copyrighted. Catalog default: **YouTube** via
  `yt-dlp ytsearch`; optional `--catalog itunes|deezer` for clean canonical-metadata
  search. Download: **yt-dlp** `bestaudio`. Legally gray and jurisdiction-dependent —
  so `any` is **never the default**, requires an explicit `music_mode=any`, logs a
  responsibility line on every fetch, and records `license="unknown (any lane)"` in the
  metadata sidecar. The **tool author accepts responsibility** for how the output is
  used; the tool cannot know the publishing jurisdiction, so it provides the lane with
  transparency rather than a value judgment.

**`any` default source = YouTube** for a concrete reason: the clip we mood-analyze and
the file we finally download come from the **same source** (`analyze == fetch`).
iTunes/Deezer previews are a different master from whatever yt-dlp later resolves by
name (cover / live / "sped up"), so their preview-vs-fetch mismatch makes them an
**opt-in** refinement, not the default.

---

## §4 — Discovery (`music_find.py`)

Lane-agnostic once candidates exist — the ranking is identical to the local lane.

1. **Query.** Derive a search query from `SPEC.mood` (default: the mood text + a
   stylistic hint — `"instrumental"` for `free`, none forced for `any`). `--query`
   overrides; `--n` sets the candidate count (default 8, capped small because YouTube
   previews cost a section-download each).
2. **Catalog.** `catalog.search(mode, query, n) -> list[Candidate]` (§7). `free` →
   `_free_source()` (ccMixter no-key default / Jamendo when keyed); `any` → YouTube (`yt-dlp ytsearch{n}:{query}` with flat
   metadata extraction — no download at this step), or iTunes/Deezer when `--catalog`
   is set.
3. **Preview clip.** `preview_clip(candidate, cache) -> str` materialises a ~30 s clip
   per candidate, source-appropriately, so the ranker never sees the difference:
   - `preview_url` present (iTunes/Deezer/Jamendo) → **HTTP GET** the preview mp3.
   - YouTube (no preview URL) → `yt-dlp --download-sections "*0:00-0:30" -f bestaudio`.
4. **Score locally.** `beats.mood_features(clip) -> MoodVector` on each clip (the same
   extractor the local lane uses), then `mood.rank(candidates, mood.mood_target(SPEC.mood))`.
   A zero-match mood **logs and falls back to `mood.rank_by_drive`** — identical to the
   local lane, never a silent wrong shortlist.
5. **Write `MUSIC_SHORTLIST.json` + `.md`.** Same schema as the local lane, with the
   sourcing columns added: `rank · title · artist · fit · energy/brightness/pace ·
   source · license · ref`. `ref` (Jamendo id / YouTube url / iTunes trackId) is what
   fetch resolves against — the shortlist is self-contained.

The mood analysis runs on a lossy 30 s clip — fine, it only **orders** the shortlist;
the final `MUSIC.json` analysis runs on the fetched full file.

---

## §5 — Fetch (`music_fetch.py`)

1. **Input.** Either `--from-shortlist <MUSIC_SHORTLIST.json> --pick <rank>` (the agent
   surfaced the list, the user chose), or `--track "<name>"` (an explicit
   `Spec.music` track name — skips discovery: `free` → Jamendo name search top-1;
   `any` → `yt-dlp ytsearch1:"<name>"`).
2. **Download.** `fetch.download(candidate, mode, cache_dir) -> FetchedTrack` (§7). Each
   candidate resolves to a cache key `<key>` = `<slug>-<id8>` — the candidate's `slug()`
   plus an 8-hex-char hash of its source-native `ref` — so two distinct tracks that share
   source+artist+title (same slug) never collide in the cache:
   - `free` (Jamendo/ccMixter) → HTTP GET the `download_url` → `music/cache/<key>.mp3`.
   - `any`/YouTube → `yt-dlp -f bestaudio -o <cache>/<key>.%(ext)s <ref>`.
   - Writes a **metadata sidecar** `music/cache/<key>.json`
     (`title, artist, source, source_url, license, date`). `date` is passed in by the
     driver (scripts cannot call `Date.now()`-equivalents freely — the driver stamps it).
   - On `any`, logs the **responsibility line** to stderr and records
     `license="unknown (any lane)"`.
3. **Cache reuse.** A cached `<key>` with its sidecar present is **reused** — no
   re-download across runs (mirrors intake's per-run reuse ethos; keyed by source+id, via
   the ref-hash folded into `<key>`).
4. **Hand-off.** The `music-source` SKILL then runs the existing
   `beats <cached-file> --auto-start --duration <length_s> --out <run>/MUSIC.json`
   on the **real full file** — start-offset intelligence + the beat grid, unchanged.

---

## §6 — End-to-end data flow

```
SPEC.mood + music_mode=free|any
        │
  music_find.py ──catalog.search──▶ [Candidate…]
        │           preview_clip (HTTP GET | yt-dlp section)
        │           beats.mood_features → mood.rank
        ▼
  MUSIC_SHORTLIST.json/.md   ── agent/user picks (§4.1 music checkpoint) ──┐
                                                                            ▼
                                                              music_fetch.py
                                                    fetch.download → music/cache/<key>.*
                                                              + <key>.json sidecar
                                                                            │
                                            beats --auto-start (real file)  ▼
                                                                     MUSIC.json
```

The pick stays a **human/agent decision** — `music_find` never auto-locks a track, it
surfaces the mood-sorted shortlist (the §4.1 music checkpoint stays human-influenced),
exactly like the local lane.

---

## §7 — Wire-contracts (typed)

Two frozen dataclasses (`scripts/lib/catalog.py`), validated in `__post_init__` (the
repo's config-spec discipline):

```
@dataclass(frozen=True)
class Candidate:
    title: str            # non-empty
    artist: str           # non-empty — sources that omit it default to "unknown"
    source: str           # ∈ SOURCES = ("jamendo","ccmixter","youtube","itunes","deezer")
    ref: str              # non-empty — source-native id/url fetch resolves against
    license: str          # non-empty — CC string (free) | "unknown (any lane)"
    preview_url: str | None   # HTTP-fetchable 30s clip, or None (→ yt-dlp section)
```

```
@dataclass(frozen=True)
class FetchedTrack:        # scripts/lib/fetch.py
    path: str             # cached audio file (exists)
    title: str
    artist: str
    source: str
    source_url: str
    license: str
    date: str             # YYYY-MM-DD, passed in by the driver
```

`source` values are validated against a module tuple `SOURCES`; `free`-lane search
**must never** return a `youtube` source (a rights-lane invariant asserted in tests).

---

## §8 — File structure / units

**Create:**
- `scripts/lib/catalog.py` — `Candidate`, `SOURCES`, `search(mode, query, n)`,
  `preview_clip(candidate, cache_dir)`, `has_ytdlp()`. Per-source private helpers
  (`_search_jamendo`, `_search_ccmixter`, `_search_youtube`, `_search_itunes`,
  `_search_deezer`) each isolate one network call behind stdlib `urllib`
  (iTunes/Deezer/Jamendo/ccMixter JSON) or a `yt-dlp` subprocess (YouTube).
  `_free_source()` resolves the free catalog (key → Jamendo, else ccMixter). **No
  `requests` dependency** — `urllib.request` suffices.
- `scripts/lib/fetch.py` — `FetchedTrack`, `download(candidate, mode, cache_dir, date)`,
  `has_ytdlp()` (shared gate), the responsibility log. Mirrors `vocals.py`'s
  boundary shape (opt-in heavy tool behind `has_*` + fail-loud remedy).
- `scripts/music_find.py` — thin driver + CLI (`--mode --mood/--spec --query --n
  --catalog --out-dir`). Mirrors `scripts/mood.py`.
- `scripts/music_fetch.py` — thin driver + CLI (`--from-shortlist --pick | --track,
  --mode --cache-dir`).
- `SKILLS/music-source/SKILL.md`.
- Tests: `tests/lib/test_catalog.py`, `tests/lib/test_fetch.py`,
  `tests/lib/test_music_find_driver.py`, `tests/lib/test_music_fetch_driver.py`,
  `tests/integration/test_sourcing.py`.

**Modify:**
- `SKILLS/music-match/SKILL.md` — the "Not this skill / Sourcing" note now points to
  `music-source` (no longer "deferred (B3)").
- `SKILLS/using-montage/SKILL.md` — step 5: mood + no track + no folder +
  `music_mode∈{free,any}` → `music-source`.
- `setup.sh` — `--with-sourcing` (installs `yt-dlp` + the interactive free-lane key
  step, §9), added to the arg-scan comment and the install section.
- `.gitignore` — `config/sourcing.env` (the per-user Jamendo client_id; never committed).
- docs (§14).

---

## §9 — Dependencies & setup

- **`free` lane** needs **no new pip dep and no required key** — stdlib `urllib` for the
  JSON + the direct download, and it works **out of the box** via ccMixter (no key). A
  free **Jamendo `client_id`** (env `JAMENDO_CLIENT_ID`, or a gitignored
  `config/sourcing.env` that `setup.sh` writes and `catalog.py` loads) is an optional
  **upgrade** to the richer catalog — absent just means the ccMixter fallback, never an
  error.
- **`setup.sh --with-sourcing`** (opt-in, mirrors `--with-demucs`/`--with-fonts`)
  installs `yt-dlp` **and** runs an interactive free-lane step: with no
  `JAMENDO_CLIENT_ID` configured it asks — **[1]** paste a client_id (persisted to
  gitignored `config/sourcing.env`), **[2]** open the Jamendo devportal to create one,
  or **[3]** use ccMixter (no key). Minimum movements, no dead-end. (The Jamendo
  client_id is a public read-only app identifier, not a secret — but it is per-user, so
  the config file is gitignored.)
- **`any` lane** needs **`yt-dlp`** (installed by `--with-sourcing`). `catalog`/`fetch`
  gate on `has_ytdlp()` and raise a remedy-bearing `ValueError` when it is absent
  (defense-in-depth, like `vocals.py`).
- Beat/mood analysis deps (librosa) are unchanged and already installed.

---

## §10 — Fail-loud & safety

Every failure names the value **and** the fix (repo fail-loud contract):

- `has_ytdlp()` false on an `any` call → `ValueError("... needs yt-dlp — install it
  with 'bash setup.sh --with-sourcing'")`.
- `free` lane with no `JAMENDO_CLIENT_ID` → **soft fallback to ccMixter** (logged, not an
  error — the free lane never dead-ends on a missing key); it raises only on a catalog
  transport error.
- Zero candidates from the catalog → `ValueError` (no plausible-looking empty shortlist).
- `music_mode=any` reached without the mode being explicitly `any` → refuse (the `any`
  lane is opt-in, never inferred).
- Network error → surfaced, not swallowed (no silent degrade to a wrong result).
- **`any` responsibility log** — every `any` fetch prints to stderr:
  `mode=any: downloading COPYRIGHTED audio via yt-dlp from <url>. Licensing/rights are
  the user's responsibility and jurisdiction-dependent (recorded in <sidecar>).`
- **No pixel/render ops** — sourcing is audio IO + analysis only; it adds no `-ss` cut,
  `lutrgb`, `scale`, or colour op, so none of the §12 render-graph landmines apply. The
  one `-ss`-adjacent op is yt-dlp `--download-sections` (its own preview machinery, not
  an ffmpeg frame-cut).

---

## §11 — Testing

Network is **always mocked** in unit tests (mirrors the `vocals.py`/demucs boundary);
ranking is already covered by the mood suite, so tests here prove **plumbing**, not
scoring:

- `test_catalog.py` — monkeypatch `urllib.request.urlopen` with fixture JSON
  (iTunes/Deezer/Jamendo/ccMixter bodies) and the `yt-dlp` subprocess (flat-playlist
  JSON) → assert `search()` parses each into `Candidate` with the right fields and
  `source`; assert `_free_source()` resolves to `jamendo` when `JAMENDO_CLIENT_ID` is set
  and `ccmixter` when it is absent; assert the **rights invariant**: `free` never yields a
  `youtube` source; assert `preview_clip` routes HTTP vs yt-dlp by `preview_url`.
- `test_fetch.py` — monkeypatch the `yt-dlp` subprocess and `urllib` (Jamendo direct)
  → assert `download()` writes the cache file + sidecar (with the license) and returns
  `FetchedTrack`; assert the **responsibility log** fires on `any` and not on `free`;
  assert `has_ytdlp()`-gate raises the remedy when yt-dlp is absent; assert cache reuse
  (second call with the sidecar present does **not** re-download).
- `test_music_find_driver.py` — mock `catalog.search` + `preview_clip` +
  `beats.mood_features` → assert the shortlist ranking and `MUSIC_SHORTLIST` write, with
  **no network and no librosa** (mirrors `test_mood_driver.py`).
- `test_music_fetch_driver.py` — mock `fetch.download` → assert the printed path +
  metadata and the explicit `--track` path.
- `test_sourcing.py` (integration) — **skip-if-no-network**: a real keyless **iTunes**
  search smoke (stable, no key) returning ≥1 candidate with a preview; **plus** a fully
  local variant that feeds a fixture WAV as the "preview" and proves
  find → mood_features → rank → `MUSIC_SHORTLIST` end-to-end **offline**. Real yt-dlp and
  the Jamendo key are **never** required in CI (skip-if-absent / skip-if-no-key).

---

## §12 — Landmines / discipline

- **Rights invariant** — the `free` lane must be provably royalty-free: `free` search
  returns only CC sources, `free` download never touches yt-dlp, every `free` file
  records its CC license. Asserted in tests; a regression here silently ships
  unlicensed audio under a "free" label.
- **`analyze == fetch` on YouTube** — the ranked clip and the downloaded file come from
  the same `ref`, so the mood the user picked is the mood they get. Do not "optimise" by
  ranking an iTunes preview and fetching a yt-dlp name-search — that reintroduces the
  master-mismatch.
- **`any` is opt-in, always** — never infer `any` from a missing folder; the mode must be
  explicit. The responsibility log and license sidecar are non-negotiable transparency.
- **Driver stamps the date** — `fetch` takes `date` as a parameter; no ambient clock in
  library code (keeps it deterministic and testable).

---

## §13 — Non-goals / deferred

- **Trend-presence ranking** — the spec's `rank = mood × tempo × trend-presence` third
  factor reads `TRENDS.md` (5.4 trend-scan, **unbuilt**). Deferred **with 5.4**; the rank
  is `mood.rank` (mood+tempo already live in `MoodVector.pace`) until a trend source
  exists. Repo YAGNI precedent: "added when a consumer exists."
- **Spotify `audio-features`** — deprecated (Nov-2024) for new apps; not built. Mood is
  measured locally from previews instead.
- **Catalog-metadata mood** (tempo/valence tags from an API) — we analyse the audio
  locally; more robust and key-free.
- **Merge-all-catalogs default** for `any` — YouTube is the default single source;
  iTunes/Deezer are an opt-in `--catalog`. A merged+deduped multi-catalog shortlist is a
  later nicety.
- **Per-track feature-cache sidecar** (`.mood.json`) — re-analysing previews per run is
  acceptable for v1 (mirrors intake); only the downloaded audio is cached.
- **Music-less delivery interaction** (§5.14 sidecar-note mode) — unchanged, out of scope.

---

## §14 — Doc-sync (updated on completion)

- `docs/build-status.md` — a "Done" entry + the "Next action" refresh.
- `docs/pipeline-map.md` — the 5.5 row flips to **✅** (all lanes sourced); the tally
  `11 ✅` → `12 ✅`, `3 ◐` → `2 ◐`; bump the `_Last updated_` line.
- `CLAUDE.md` — two registry rows (this spec + its plan).
- `docs/specs/2026-07-05-montage-skillset-design.md` — a §5.5 "Built" blockquote
  (autonomous sourcing lands; the three lanes now complete).
- `docs/specs/2026-07-11-music-spine-design.md` — §9: B3 no longer deferred.
- `docs/specs/2026-07-13-mood-match-design.md` — §9: B3 sourcing landed (cross-ref).
