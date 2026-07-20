# Montage Skill Set — Design Spec

**Date:** 2026-07-05
**Author:** Sergei (vasechkoss@gmail.com) + Claude
**Status:** design approved, ready for `writing-plans`
**Amended:** 2026-07-06 — hardening round: env (python 3.13, single requirements, pypi index), librosa-first music, §4.1 questions/go-back protocol, golden fixture, degradation ladders
**Deliverable of this document:** specification only (no code; implementation in a separate session)

---

## 1. Goal

A full skill set (modeled on [superpowers](https://github.com/obra/superpowers)) for editing **one video reel out of a pile of raw footage** — for any platform. Not surf-specific: surfing is the first proven use case, but the pipeline is general (travel, sports, vlog, promo).

The pipeline mirrors the superpowers flow: **idea → spec → plan → draft → per-episode processing → checks**. Each stage is a separate skill with a clear input/output (an artifact) and a hard gate at its exit.

The design was reverse-engineered from a real session (Jul 3–5 2026) that produced two reels: Reel A (ODESZA "Say My Name", v10 final) and Reel B (Billie Eilish "Birds of a Feather", v18). Every technical parameter, formula, and "landmine" below comes from that session — not invented.

### Principles

1. **Scripts do the heavy lifting; the agent fills a tiny manifest.** Each stage is a deterministic python/ffmpeg script. The agent doesn't reason over every ffmpeg call — it prepares parameters, the script executes. Saves context and removes errors.
2. **Artifacts are the contracts between skills.** Plain markdown/json in `docs/montage/<project>/`, under git. Raw footage is never touched.
3. **Every parameter is a tunable default, not a hardcode.** Canvas, layout, composition, motion, style-lean, thresholds, trend sources.
4. **Rules = classic canon as base ⊕ trend as a light lean.** Strict where consistency is needed; flexible where taste is needed.
5. **Per-episode processing runs in subagents.** Episodes are independent → parallel; the main thread never loads per-episode detail.
6. **Two checks at every level:** mechanical (numeric thresholds) + editorial (matches the original idea, like code review).
7. **Self-contained environment.** The skill installs its own venv; it never pollutes the shared environment.
8. **Fail loud with a remedy.** Every script exits non-zero with an actionable message ("ffmpeg not found → brew install ffmpeg") — no silent fallbacks, no half-results.
9. **Explicit project dir.** Every script receives the project directory as an explicit argument; nothing resolves against the caller's cwd.

---

## 2. Skill layout

Runs in Claude Code mode (environment access available). The skill is isolated via a local venv.

```
video-grid/                             # the skill-set repo (github.com/vasechko-sergey/video-grid)
├── SKILLS/                             # skill entry points (follow-on plans)
│   ├── using-montage/SKILL.md          # router ("1% → invoke" rule)
│   ├── footage-intake/  reel-brief/  trend-scan/  music-and-mood/  pacing/
│   ├── edit-plan/  extract/  assemble-draft/
│   ├── process-episode/SKILL.md        # subagent, crown jewel
│   ├── episode-postcheck/SKILL.md      # gate
│   ├── audio-mix/  reel-final-check/  deliver/
│   └── ffmpeg-recipes/SKILL.md         # reference + landmine registry
├── docs/                               # this repo's own design + implementation plans
│   └── plans/
├── references/
│   ├── editing-canon.md                # classic editing rules + grid library (thirds/phi/golden-canon-grid)
│   ├── landmines.md                    # pointer to §12 (was a drifting copy)
│   └── montage-debugging.md            # phased stage-failure debugging (patterned on systematic-debugging)
├── scripts/
│   ├── lib/                            # pure logic, unit-tested: geometry, motion, pathsmooth, color, checks
│   ├── extract.py  track.py  reframe.py  storyboard.py  check_episode.py    # core engine (current plan)
│   ├── intake.py  beats.py  music_find.py  music_fetch.py  trends.py        # follow-on plans
│   └── check_reel.py  mix.py  assemble.py  deliver.py                       # follow-on plans
├── tests/                              # unit (lib/) + integration + golden fixtures (real clip + frozen route)
├── requirements.txt                    # ONE file — the full pipeline set (§ Environment)
├── pytest.ini                          # pythonpath = . (landmine §12)
├── setup.sh                            # venv (python 3.13) + preflights, idempotent
├── models/                             # YOLO weight cache (downloaded once, by model name)
└── .venv/                              # local, gitignored
```

### Environment (venv, no system pollution)

```bash
# setup.sh (idempotent)
PYTHON="${PYTHON:-python3.13}"                                     # explicit version, fail loud if absent
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"   # corporate mirrors time out off-VPN
"$PYTHON" -m venv "$SKILL_DIR/.venv"
"$SKILL_DIR/.venv/bin/pip" install -r "$SKILL_DIR/requirements.txt"
# preflight AND self-install: missing python3.13 is brew-installed automatically.
# ffmpeg = ONE keg-only `ffmpeg-full` beside core ffmpeg, carrying drawtext AND
# vidstab as BASELINE (2026-07-20). The old `--with-vidstab`/`--with-fonts` flags
# and the homebrew-ffmpeg tap build that REPLACED core ffmpeg are both deleted —
# so is the claim that "core never calls vidstab", false since §5.2 intake became
# its first runtime consumer. keg-only means the binaries never reach PATH, so
# setup.sh records them in config/ffmpeg.env and scripts/lib/ffbin.py resolves
# through it ($FFMPEG → that file → PATH). Every brew block warns-and-continues
# without brew, so a non-macOS box still builds its venv.
# YOLO weights into models/ if missing
```

- All scripts run **only** via `.venv/bin/python`, never system python, and **as modules** — `.venv/bin/python -m scripts.<name>` (plain `python scripts/<name>.py` breaks `scripts.lib` imports). Python **3.13** (`PYTHON` env overrides).
- `using-montage` step 0 = ensure-env: if `.venv` is missing → run `setup.sh`. Self-healing.
- **One `requirements.txt` for the whole pipeline** (tests mock the heavy parts, but the conveyor needs everything installed): `numpy`, `scipy`, `Pillow`, `pytest`, `librosa` (beats/sections/energy, §5.5), `ultralytics` (YOLOv11 + ByteTrack), `scenedetect`, `imagehash`, `yt-dlp`, `requests`. ffmpeg/ffprobe are system (external); setup.sh INSTALLS missing system deps itself via brew (python@3.13, ffmpeg) — skill setup must bring the machine up, not just print remedies; hard fail only when brew is absent. `vidstab` filters are a **warning**, not a blocker: current homebrew-core ffmpeg bottles ship **without** libvidstab, the core engine never invokes vidstab, and stabilization arrives with process-episode — remedy when needed: `brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-libvidstab`. process-episode's own preflight re-checks vidstab as a hard requirement before any `stabilize: true` episode.
- **Lazy heavy imports:** `ultralytics`/`librosa` import inside functions, never at module top — test collection stays fast, the detector stays mockable.

---

## 3. Artifacts (docs/ folder, separate from raw footage)

Everything in `docs/montage/<project>/` — under git, raw footage untouched:

| File | Written by | Contents |
|------|-----------|----------|
| `FOOTAGE.md` | footage-intake | per clip: who, what, quality, shaky flag, scene-cuts; **list of moments** (one clip → several windows), each window with its own shot-type guess, description, score |
| `cast.json` | footage-intake | hero registry (§6.1a): name → appearance descriptor (color hist over seg-mask pixels from 1–3 reference crops) + notes; one interactive naming pass; referenced by `SPEC.cast` and episode manifests |
| `SPEC.md` | reel-brief | reel count, platform+canvas, length, mood, music, **music.mode** (local/free/any, default free), hook, text, ending, style-lean, **cast** (who the reel is about, → `cast.json`) |
| `TRENDS.md` | trend-scan | trend cache (fetch date, TTL 7–10d): cut-style, transitions, hook patterns, text-style, composition deviations, trending-sound candidates |
| `MUSIC.json` | music-and-mood | beat-grid, downbeats, drop, **energy-curve** (RMS), mood-vector, cut-map, **start_offset** (chosen track fragment), **vocal-map** (phrase boundaries for start snapping), **source** (url/artist/title/license), **delivery** (baked/platform-sound) |
| `PACING.md` | pacing | **energy spine**: episode order + target length + energy level, pinned to music sections, hook first |
| `EDL.md` | edit-plan | ordered episodes: source+window, shot-type, layout, composition, grid, motion, processing-notes, beat-slot |
| `SOURCES.md` | process-episode | lock file (🔒 per episode) — the session's `REEL_SOURCES.md` promoted to a contract; **one source may feed multiple episodes** (different windows) |
| `segments/<ep>_raw.mp4` | extract | **cut fragments** per EDL window, video + original audio (the ambient bed for §5.12) — input for draft and process-episode (not full clips) |
| `work/<ep>/{route,path,report}.json` | process-episode | tracker route, smoothed crop path, check report (`attempt`, `fail_reasons[]` — feeds the §4.1 escalation) |
| `checks/*.json` | *-check | mechanical-check reports |
| `storyboards/*.jpg` | storyboard | contact sheets with a grid (thirds + phi; for hero/static — the full golden-canon armature) — **verification artifact** |
| `TITLES.json` | titles | hook/ending/caption text, timing, font, position, style |
| `out/*.mp4` | process/assemble/deliver | locked episodes 🔒, audio, final |

---

## 4. Pipeline flow

```
using-montage (router, ensure-env)
      │
      ▼
footage-intake ──► FOOTAGE.md
      │
      ▼
reel-brief ──────► SPEC.md            (brainstorming for reels)
      │
      ▼
trend-scan ──────► TRENDS.md          (cache TTL 7–10d)
      │
      ▼
music-and-mood ──► MUSIC.json         (mood-match + energy + beats)
      │
      ▼
pacing ──────────► PACING.md          (energy spine — shared by music and edit-plan)
      │
      ▼
edit-plan ───────► EDL.md             (writing-plans for reels; source+window map, no cutting)
      │
      ▼
extract ─────────► segments/<ep>_raw.mp4   (cut windows into files — ONCE, correct seek args)
      │
      ▼
assemble-draft ──► draft.mp4 + burnt-in "process here" labels  (concat of segments)
      │
      ▼   (after plan/draft approval, segments are the working input)
      ▼
process-episode ×N  ◄── SUBAGENTS, parallel, one per episode
   (input = segments/<ep>_raw.mp4 → track → reframe → storyboard → episode-postcheck → retry/lock 🔒)
      │
      ▼
audio-mix ───────► audio (music + ducked ambient + loudnorm −14 LUFS)
      │
      ▼
reel-final-check ──► mechanical + editorial review (like code review)
      │
      ▼
deliver ─────────► out/REEL_*.mp4  (codec/fps/bitrate per platform)
```

Gates are hard: a stage does not exit until its exit conditions are met. A failed check → loop back, not forward. Built-in back-edge: when the pacing gate can't fit the spine onto the chosen track fragment, it first re-picks `MUSIC.start_offset`; only if that loop dries out does music selection itself reopen.

> **Built (2026-07-18):** the back-edge ships as a pure re-time — see the
> table row below and `docs/specs/2026-07-18-length-retime-design.md`.

### 4.1 Questions and going back (adapted from superpowers)

**When to ask questions:**
- **reel-brief** is the only stage that interrogates the user — one question at a time (brainstorming pattern).
- **process-episode subagents** ask clarifying questions **before starting** if the manifest is ambiguous — never mid-encode guesses. When mid-task reality contradicts the manifest (EDL says "moving right", tracker sees left; two people, unclear hero; stabilize flag on a wade shot) → **stop and return a structured finding** to the orchestrator. No improvising past the manifest.
- Other stages never ask the user directly; questions travel up the escalation ladder. **User-facing checkpoints are exactly three: SPEC approval, EDL+draft approval, final review.** Everything else is machine gates.

**Going back (fail → backward, never forward):**
- A failed gate retries in its own stage first.
- **The same failure 3× → escalate one level UP the artifact chain** — question the input artifact, not the implementation (systematic-debugging: repeated fixes failing means the approach is wrong):

| Failure | Retry in place | 3× → escalate to |
|---------|----------------|------------------|
| episode-postcheck | reframe params | edit-plan: that episode's composition/grid/window is wrong |
| pacing gate (spine won't fit) | re-pick `start_offset` | music-and-mood: different fragment/track |
| draft gate (beats don't land) | segment trims | pacing/EDL |
| reel-final mechanical | the failing episode | that episode's EDL row |
| reel-final editorial (structural) | — | pacing/EDL directly |
| top of the ladder | — | reel-brief + the user |

- **No fixing forward:** a bad crop is never masked in assemble; bad pacing is never rescued in deliver.
- Check reports carry `attempt` and machine-readable `fail_reasons[]` so the orchestrator can count retries and route escalation.

> **Built (2026-07-18):** the pacing-gate row's back-edge ships as a pure
> re-time, not the literal `start_offset` re-pick — `edit_plan.build_edl` sets
> a paced EDL's `target_dur = min(realized footage, spine.target_dur)`, so an
> under-filled spine re-times DOWN before ever reaching this ladder row; a
> residual shortfall inside `build_reel`'s 1.0s band also re-times and
> re-checks rather than escalating. Re-picking `MUSIC.start_offset` stays the
> manual rung (`beats --auto-start`). See
> `docs/specs/2026-07-18-length-retime-design.md`.

---

## 5. Skills — in detail

### 5.1 using-montage (router)
Entry point. The "if there's a 1% chance a skill applies → invoke it" rule. Step 0: ensure-env (venv). Routes through stages 1–13. Analogous to `using-superpowers`.
**Natural-language overrides:** the user passes options as free text in the invocation ("make it without music", "music.mode any", "9:16", "more classic"); `using-montage`/`reel-brief` parse intent into `SPEC` params (music.mode, delivery, style-lean, canvas, default grid, …). The scripts receive explicit args internally — the user never types CLI flags. Scripts always get the project dir explicitly (`--project-dir`); nothing assumes the caller's cwd.

> **Built (2026-07-12, entry-skill):** `SKILLS/using-montage/SKILL.md` conducts the
> built stages (project-init → footage-intake → [music] → edit-plan → edl_to_reel)
> with the three §4.1 checkpoints, backed by `scripts/montage.py` — a deterministic
> stage-status **inspector** (`next_action`) so resume-for-free (line 510) is
> testable. Inspector, not runner: judgment steps stay in the sub-skills. ~~The cap-3
> **parallel** episode fan-out (§5.10) is deferred — `edl_to_reel` is sequential.~~
> **Built 2026-07-18** — `edl_to_reel` fans out across a bounded thread pool
> (`jobs`, default 3), closing 5.1's last open sub-item; see
> `docs/specs/2026-07-18-cap3-fanout-design.md`.
> See `docs/plans/2026-07-12-using-montage.md`.

### 5.2 footage-intake → `FOOTAGE.md`
`intake.py`: ffprobe (duration/resolution/fps) + PySceneDetect (scene boundaries) + YOLO sample (who/how many people) + shake estimate (vidstabdetect magnitude). **One clip → several moment-windows**, not one: a long ride/take contains distinct fragments (grounding: MVI_3739 = one 22s ride → `lena_ride` + `lena_ride2` + `lena_nose`; MVI_3998 → two hang-fives). intake segments each clip into candidate windows (sub-scenes + motion/people) and **scores each window separately**. Cull/selection step: rank windows across all footage, mark the best moments — several may come from one source.
**Cast pass (when people matter to the reel):** intake surfaces top-N person crops across the footage; the user names the heroes once — any domain (family, athletes, friends, a vlogger). Each name stores an appearance descriptor into `cast.json` (§6.1a); `SPEC.cast` lists who the reel is about.
**Gate:** every clip logged, faces/people tagged, moment-windows carved out and scored, cast named (when applicable).

> **Built (2026-07-12, SP2):** `scripts/intake.py` scans a footage folder → typed
> `FOOTAGE.json` + rendered `FOOTAGE.md` of scored candidate moment-windows —
> ffprobe + PySceneDetect scene bounds + one YOLO11-seg/ByteTrack pass
> (people/tracks/masks) + `vidstabdetect` shake → **sub-scene carve** into the
> episode band → present/motion/stability/dur **score** → phash **cull** marking
> the best. Contracts in `scripts/lib/footage.py`
> (`FootageWindow`/`FootageClip`/`Footage` + `to_markdown`, `CastMember`/`Cast`);
> a `FootageWindow` projects onto an `EDLEpisode` (§5.7's input). The **cast
> pass** persists top-N candidate crops + `cast_candidates.json` from the single
> seg pass; the `footage-intake` SKILL names them → `write_cast` → `cast.json`.
> Intake is the first runtime **vidstab** consumer (hard preflight). Descriptor →
> manifest hero-pin wiring is deferred. See
> `docs/plans/2026-07-12-footage-intake.md`.

### 5.3 reel-brief → `SPEC.md` (= brainstorming)
Our own skill that copies the brainstorming approach (context recon first, one question at a time, HARD-GATE before processing, spec self-review) — see §14. Dialogue about the idea: reel count, platform(s)+canvas, length, mood, track, hook intent, text, ending, **style-lean** (classic↔trend). Different reels = different clips (minimal repeats), different endings.
**Gate:** mood + platform/canvas + length + hook locked.

> **Built (2026-07-12):** `scripts/lib/spec.py` (`Spec` config-spec + `to_markdown`)
> + `scripts/reel_brief.py` (`build_spec` reads canvas from `project.json`,
> `write_reel_brief` → `SPEC.md`+`SPEC.json`) + `SKILLS/reel-brief`. Router treats it
> as **optional** (enriches CP1; the autonomous path runs off `project.json`). Music
> sourcing/mood-match (B3), cast.json cross-validation, and multi-reel fan-out are
> deferred — `SPEC` records `music`/`music_mode`/`reel_count` but nothing consumes
> them yet. See `docs/plans/2026-07-12-reel-brief.md`.

### 5.4 trend-scan → `TRENDS.md` (cache TTL 7–10d)
`trends.py`. Layered source (see §8). Cache stamped with fetch date: fresh → reuse; older than 7–10d → refetch. Output is a **short list of checkable directives**, not a blob. Manual override: user writes lines in, the agent treats them as locked.
**Gate:** fresh cache or manual input.

### 5.5 music-and-mood → `MUSIC.json`
`beats.py`: **librosa** (v1 primary — clean wheels on every platform): beat grid + tempo, section boundaries (recurrence/novelty), RMS energy-curve, spectral features; downbeats v1 = strong-beat estimate from the beat grid + onset strength. **Mood-match v1**: tempo + energy curve + spectral stats → coarse mood vector matched against the reel's mood; the agent makes the final mood call on the shortlist — numbers narrow, judgment picks. The track's energy sections (build/drop/release) are aligned to the visual energy — music and picture are **one arc**, not two glued halves. Cut-map: cut points ↔ beats/downbeats. Loudness measurement stays ffmpeg (`ebur128`). **Optional upgrades — documented, NOT wired in v1 (one code path = simple tests):** madmom for RNN+DBN downbeats (git master only; the 2018 PyPI release is broken on modern python/numpy), demucs for true vocal stems. essentia is **out of v1** entirely (no macOS arm64 wheels).
**Track-fragment selection:** the track **need not start at 0:00** — pick the strongest segment of the melody (by sections/energy/drop) for the reel length, don't force 0:00 (session: ODESZA `-ss 15`, Billie `-ss 13`). Record `start_offset`.
**Vocal-aware start:** if the chosen window has vocals, the in-point must never land mid-word. **v1 rule:** snap the in-point to a section boundary's downbeat — section starts almost never begin mid-word; no vocals → any downbeat. **Optional upgrade (not v1):** demucs vocal stem → RMS phrase gaps → snap to the nearest phrase boundary.
**Autonomous find + download** — the skill can source the track itself, in three stages:
- **Discovery** (`music_find.py`): trend-sound candidates from `TRENDS.md` (TikTok/IG trending sounds) + mood-match against catalog metadata (Spotify `audio-features` valence/energy/tempo — ideal for the mood cosine; iTunes Search API needs no key; Deezer) → rank = mood-cosine × tempo-fit × trend-presence → shortlist. Metadata + 30s previews only at this stage.
- **Resolve + download** (`music_fetch.py`): `yt-dlp` resolves the chosen track to an audio source (YouTube/YT Music/SoundCloud/Bandcamp) → `bestaudio` → cache `music/cache/` with metadata (title/artist/source-url/date). Beats/mood then run on the **real file**, not the preview. Cache → reuse across runs.
- **`SPEC.music.mode` (default `free`, overridable at skill invocation)** — the rights lane: `local` (user's own folder) · `free` (royalty-free APIs: YouTube Audio Library, Pixabay, Uppbeat, Free Music Archive, ccMixter — legal search+download; safe default for distribution) · `any` (full autonomous discovery+download incl. copyrighted via yt-dlp; user accepts responsibility — auto-downloading copyrighted audio is legally gray and jurisdiction-dependent, so this is a responsibility switch, not a baked-in default). Beat detection is **always local**.

**Delivery interaction** (see §5.14): default is `baked` — the with-music export; saying it in the invocation (e.g. "without music") additionally emits a music-less version + a sidecar note (trending-sound name + in/out offset) so the user adds the platform-licensed sound in-app — cleaner on rights, avoids Content-ID mutes.
**Gate:** mood matches SPEC, cut-map built, `start_offset` chosen, start doesn't break a word, track sourced (per `music.mode`).

> **Built (2026-07-11, B1+B2):** `scripts/beats.py` — librosa `analyze(track,
> start_offset, duration) → MusicSpec`: tempo + reel-relative beat grid + coarse
> RMS energy; CLI writes `MUSIC.json`. This is the **lean subset** — section
> boundaries/downbeats, spectral features, and mood-match are deferred, as is
> autonomous sourcing (`music_find.py`/`music_fetch.py`, `music.mode`) — see
> `docs/plans/2026-07-11-music-spine.md` (Phase B3).

> **Built (2026-07-13, start-offset intelligence):** `start_offset` (the "chosen
> track fragment") and the `vocal-map` phrase-boundary start-snap now ship — a
> peak-energy `duration`-window whose start lands in a vocal pause (opt-in demucs
> vocal stem, librosa mix-silence proxy fallback), via `beats --auto-start`.
> Mood-match and autonomous sourcing (B3) remain deferred. See
> `docs/specs/2026-07-13-start-offset-intelligence-design.md`.

> **Built (2026-07-14, mood-match):** the §5.5 mood-match (local lane) now ships —
> `scripts/lib/mood.py` scores a track's energy/brightness/pace (loudness-robust)
> against a curated mood lexicon and `scripts/mood.py` ranks a local folder vs
> `SPEC.mood` into `MUSIC_SHORTLIST.md` for the agent to pick from (`music-match`
> SKILL). ~~Autonomous **sourcing** (`music_find`/`music_fetch`, `music.mode`
> free/any) stays deferred (B3).~~ **Built by sourcing — see below.** See
> `docs/specs/2026-07-13-mood-match-design.md`.

> **Built (2026-07-14, sourcing):** autonomous sourcing (B3) now ships too,
> closing §5.5's last gap. `scripts/lib/catalog.py` (per-source discovery over
> stdlib `urllib` or an opt-in `yt-dlp` module invocation — Jamendo/ccMixter for
> the `free` lane, YouTube/iTunes/Deezer for `any`) + `scripts/lib/fetch.py`
> (download/cache/sidecar/responsibility log) back `scripts/music_find.py` /
> `scripts/music_fetch.py`, which reuse the same mood engine
> (`beats.mood_features` + `mood.rank`) that ranks a local folder to rank
> sourced previews instead — sourcing is plumbing, not new scoring. All three
> `music.mode` rights lanes (`local`/`free`/`any`) are now complete; the
> `music-source` SKILL conducts find→pick→fetch; `setup.sh --with-sourcing`
> installs the opt-in `yt-dlp` dep and interactively configures a Jamendo key.
> See `docs/specs/2026-07-14-music-sourcing-design.md`.

### 5.6 pacing → `PACING.md` (energy spine)
A shared artifact read by **both** music-and-mood **and** edit-plan. Episode order + each episode's target length + energy level, pinned to music sections. Hook first. This makes "the mood matches, not two halves" **structural**, not eyeballed. Episode length is variable (short cutaways where rhythm is needed, long ones where a maneuver/ride must be shown fully).
**Gate:** order+length+energy pinned to the music.

> **Built (2026-07-14, B4 authoring):** `scripts/lib/pacing.py` — `Slot`/`Spine`
> config-specs (validate hook-first/contiguous/duration-sum, JSON round-trip,
> `to_markdown`) + `build_spine`: folds `MUSIC.json`'s beat grid + RMS energy
> curve into a beat-aligned energy spine, **min-max normalized within the
> track** (§12 relative-gate discipline), cut density rising with energy, hook
> first. `scripts/pacing.py` (the driver) writes `PACING.{json,md}`;
> `edit_plan.build_edl(pacing=)` binds the selected episodes to the spine's
> slots (`beat_slot` + re-timed `dur`), so "the mood matches, not two glued
> halves" is now structural, not eyeballed. stdlib-only core (no numpy/librosa)
> — bit-exact, goldens pin exact slots. The **retry-time auto-fix**
> (`build_reel`'s `length` failure re-timing the spine) and **librosa section
> detection** stay deferred. See `docs/specs/2026-07-14-pacing-design.md`.

### 5.7 edit-plan → `EDL.md` (= writing-plans)
Our own skill that copies the writing-plans format (checkbox steps, exact file lists, no placeholders) — see §14. Each episode binds to a slot in `PACING`: source+window, **shot-type**, **layout**, **composition**, **grid** (thirds/phi), **motion**, processing-notes, beat-slot. See §6 (composition) and §7 (layout). This is a **map** (which file holds what and from which timestamp to view) — no cutting yet.
**Gate:** every episode has source+window+shot-type+beat-slot.

> **Built (2026-07-11, SP1):** `scripts/lib/edl.py` — typed `EDLEpisode`/`EDL`
> config-specs (`EDL.json`, JSON round-trip) + the `to_manifest_dict` bridge
> (EDL row → process-episode manifest dict; omits canvas/delivery so they
> inherit from the project). ~~The **markdown render** (`EDL.md`) and
> **interactive authoring** are deferred — see
> `docs/plans/2026-07-11-extract-spine.md` (SP3).~~ **Built by SP3 — see below.**

> **Built (2026-07-12, SP3):** `scripts/edit_plan.py` + `SKILLS/edit-plan`
> author an `EDL.json` + `EDL.md` from `FOOTAGE.json` via an agent-written
> `selection.json` — **selection is judgment, code projects by reference**:
> `window_to_episode` copies a scored `FootageWindow`'s mechanical fields
> (source/start/dur/shot_type/description) straight through, never retyped,
> while the agent supplies only the editorial fields (composition/grid/
> layout/motion/hero/…). `EDL.to_markdown` renders the `EDL.md` map;
> `edl.preflight` (shared with `edl_to_reel`) gates the assembled `EDL`
> against the project before anything is written. See
> `docs/plans/2026-07-12-edit-plan-spine.md`.

### 5.8 extract → `segments/<ep>_raw.mp4`
`extract.py`: using the windows from `EDL`, **cut each episode into a standalone file** — once, with **correct seek arguments** (see §12; the bug was in the call args, not in 4K). Frame-accurate cut (re-encode of the short window). **Audio is preserved** in the segment (`aac`) — it is the ambient bed for §5.12; dropping it at extract would orphan the mix. From here on both the draft and `process-episode` work on these small fragments — no seeking through 300MB, no scanning the whole file. 4K is cut natively (no proxy/downscale — quality preserved).
**Gate:** every episode from `EDL` has its own `segments/<ep>_raw.mp4`, length matches the window.

> **Built (2026-07-11, SP1):** `scripts/extract.py` — `extract_edl(edl,
> footage_root, seg_dir)` loops the untouched single-window `extract()` over
> every EDL episode, plus the §5.8 length gate (segment duration must match
> its window, else raise) — see `docs/plans/2026-07-11-extract-spine.md`.

### 5.9 assemble-draft → `draft.mp4`
`assemble.py`: concat of the **segments** (`segments/*_raw.mp4`) into the **whole draft at once**, almost no processing, with **burnt-in labels** — what will be processed and where (from the EDL processing-notes). A check of the whole shape before polishing. After plan/draft approval the segments are locked as the working input.
"Almost no processing" = no *creative* processing; concat still demands uniform streams, so assemble scale-fits every segment into the SPEC canvas and unifies fps/codec first (§12). Labels via `drawtext` with an explicit `fontfile=` — macOS has no reliable fontconfig default. The draft muxes a **rough music bed** — the chosen fragment from `MUSIC.json` at `start_offset` — otherwise the "lands on beats" gate has nothing to land on; segment audio stays out of the draft (it returns as ducked ambient in §5.12).
**Gate:** full length, lands on beats, plays.

> **Built (2026-07-13, SP1b):** `scripts/draft.py` `build_draft` — extract each EDL
> window, burn a canvas-fit (letterbox) + `processing_notes` label into every
> segment (`scripts/lib/draft.py`: `resolve_font`/`label_text`/`segment_filter`,
> the explicit-`fontfile=` landmine caught in a unit test), concat via the shared
> `assembly.concat`, and mux a rough music bed by reusing `mix.mix`. An optional
> `assemble-draft` router Stage (CP2, `draft.mp4`) — never the autonomous `next`.
> An `ensure_drawtext` preflight + `setup.sh` guard the drawtext dependency. No
> creative crop/track (process-episode), no ducked ambient (§5.12). See
> `docs/plans/2026-07-13-assemble-draft.md`.

### 5.10 process-episode → `out/<ep>.mp4` 🔒 (subagent, crown jewel)
See §6. Runs **as a subagent, one per episode**, in parallel (via `dispatching-parallel-agents`). The subagent's context = only `{segment: segments/<ep>_raw.mp4, shot-type, layout, composition, grid, motion, hero?, line/center-target, color-target, stabilize?, canvas, out-path}` + `reframe.py` + `ffmpeg-recipes`.
**`hero?`** — optional subject pin for multi-person frames: a first-frame seed bbox (centre-format `[x,y,w,h]`, source px), a rule (`largest` / `leftmost`), an explicit track id, or a **cast name** resolved through `cast.json` descriptors (§6.1a) — all four forms built (2026-07-16, see below). `hero.resolve()` turns whichever form the manifest carries into one typed pin at a single boundary, and `track.py` dispatches it to the matching rung: a bbox pin picks the track with max IoU against the seed over the first frames, a rule picks mechanically (no identity claim), a track id is looked up directly, and a cast name picks the closest appearance descriptor. No pin → intent-conditioned scoring (§6.1a). A pin that matches nobody in the segment is a stop-and-report, never a silent fallback to scoring. This is also the **answer channel** for the §4.1 "who is the hero" stop-and-report: the orchestrator (or the user at the top of the ladder) fills `hero`, the episode retries. Input is the **cut fragment**, not the full clip (small file, no seeking through 300MB). Loop: track → reframe → storyboard → episode-postcheck → (fail? retry) → return 🔒 clip + report. The main thread never loads episode detail. **Concurrency cap: 3 episode subagents at once** (default, tunable) — one machine; YOLO + ffmpeg saturate it. **Built 2026-07-18** — and the 3 turned out to be right, but for a reason worth recording: it ships as an in-process `ThreadPoolExecutor` inside `edl_to_reel` (`jobs`, default 3), **not** as subagents, because the fan-out is mechanical and this repo puts mechanics in code. Measured on six real 2.5 s windows through the full `process_episode`: 41.1 s sequential → 24.2 s at 3 (**1.70×**), and 24.4 s at 4 — nothing, while per-episode latency keeps climbing. The win is one episode's YOLO overlapping another's ffmpeg; past three, torch instances contend 1:1. See `docs/specs/2026-07-18-cap3-fanout-design.md` §2. Manifest ambiguous → ask before starting; mid-task contradiction → stop and report, never improvise (§4.1).
**Gate:** episode-postcheck passes.

> **Built (2026-07-08, orchestrator-first slice):** `scripts/process_episode.py` drives the loop for one episode (`fill`/9:16), threading the probed `canvas`/`src_dims` into `check_episode` (closes the core-plan contract note) and wiring the §6.1a hero marks onto the storyboard; `SKILLS/process-episode/SKILL.md` is the subagent (ask-before-start, editorial gate, stop-and-report). The deterministic loop/escalation is pure Python (`scripts/lib/{manifest,orchestration}.py`, TDD); judgment lives in the SKILL. Layouts/stab, the optical-flow/manual degradation rungs, descriptor continuity re-match, and the cap-3 parallel fan-out are their own follow-on plans (see `docs/plans/2026-07-08-process-episode-orchestrator.md`).

> **Built (2026-07-16, cast → hero-pin):** `scripts/lib/hero.resolve` is the one
> boundary that turns a manifest's raw `hero` (tuple/str/int) into a typed
> `HeroPin`, raising with a remedy on anything unresolvable rather than
> returning `None` (which means "no pin, score by intent" and nothing else —
> quietly returning it for an unresolvable pin was the exact silent fallback
> this closed). `track.py` gained a rung per pin kind (`_rule_track`/
> `_id_track`/`_descriptor_track`, siblings of the existing `_seed_track`); a
> pin given means the rung decides, with no fallback to intent scoring — a
> rung that matches nobody reports `pin_matched=False`, which
> `orchestration.py` turns into a `hero-unmatched` stop-and-report (fired
> **before** `no-track`, since the unmatched pin is what produced the empty
> route). `manifest.validate()` finally gates `hero`, using `hero.resolve` as
> its oracle, so a malformed pin or an unknown cast name is a `needs_input`
> problem string instead of quietly validating clean. `is_seed_pin` is
> **deleted** — the rungs consume the pin, so there is no longer a predicate to
> share between the ambiguity gate and the shell's seed gate. See
> `docs/specs/2026-07-16-cast-hero-pin-design.md`. **§6.1a layer 3**
> (descriptor continuity re-match) is a separate mechanism, now unblocked —
> see §6.1a below.

### 5.11 episode-postcheck (gate)
Mandatory step. Two parts:
- **Mechanical** (`check_episode.py`): thresholds §9 — against the episode's declared composition intent (not against a global rule-of-thirds law).
- **Editorial**: "does this episode read well?" — matches the episode's intent.
Both must pass. Fail → back to reframe.

### 5.12 audio-mix → `out/audio`
`mix.py`: music + **ambient ducking** (sidechaincompress) + SFX (whoosh on transitions) + **loudnorm −14 LUFS** (EBU R128). afade in/out. **Ambient source:** the original audio of `segments/<ep>_raw.mp4` (preserved by extract, §5.8), trimmed and ordered per the EDL so it stays in sync with the final picture.
**Gate:** loudness in range.

> **Built (2026-07-11, B1+B2):** `scripts/mix.py` — **music-only** stem: accurate
> seek + afade + two-pass loudnorm −14 LUFS → aac; `scripts/deliver.py` muxes it
> (stream-copy, preserving the measured loudness). ~~**Ambient ducking**
> (sidechaincompress) and **SFX** are deferred until `extract` (§5.8) preserves
> per-episode audio to duck against~~ — see `docs/plans/2026-07-11-music-spine.md`.
> **Ambient built 2026-07-15; SFX built 2026-07-15 — see below. §5.12 is complete.**

> **Built (2026-07-15, ambient sub-slice):** `mix(segments=)` ducks each clip's
> preserved nat-sound — the raw `ep{i}_raw.mp4` segments `extract` already keeps
> (§5.8 needed no change), never the silent locked clips — under the music via
> `sidechaincompress` before the loudnorm pass; `ReelManifest.ambient` defaults
> on. See `docs/specs/2026-07-15-ambient-ducking-design.md`.

> **Built (2026-07-15, SFX sub-slice):** `mix(sfx=)` synthesizes a whoosh
> (ffmpeg pink-noise → bandpass → fade envelope, no assets, deterministic seed)
> and places it on the reel's **major transitions** — a cut where
> `max(neighbour dur) > median(durs)`, throttled by a minimum gap — mixed
> **un-ducked** on top of the music(+ambient) stem before the final −14
> loudnorm. `ReelManifest.sfx` defaults **off** (a deliberate stylistic accent,
> unlike the ambient bed which defaults on). This closes §5.12 — see
> `docs/specs/2026-07-15-transition-sfx-design.md`.

### 5.13 reel-final-check (gate) — mandatory whole-reel check
Two parts:
- **Mechanical** (`check_reel.py`): black frames (blackdetect), loudness (loudnorm measure), cuts-on-beat, color deltas across cuts, **variety-guard** (perceptual hash — no near-duplicates back to back), length, safe-zones, key-action-not-clipped, pad-bars-clean, layout-transitions-not-jarring (the last three **advisory**, built 2026-07-17 — see below).
- **Editorial** (agent, like `requesting-code-review`): does the reel deliver SPEC's original idea? Mood/story? Hook strong? Ending right? Pacing along the spine? Anything from EDL missing/weak? Classic base **and** trend flavor (not bland, not gimmicky). → findings → fix loop → re-check. **Built 2026-07-18 (Slice B) — see below.**
**Gate:** both parts green.

> **Built (2026-07-17, the still-mechanical trio — Slice A):**
> `scripts/lib/reel_final.py` (new) — `evaluate_key_action` (tracked-subject
> bbox vs frame edge, via a new `geometry.extent_at_times` corner projection +
> `safezones.subject_extents`), `evaluate_pad_bars` (non-`fill` filler bars
> well-formed — content rect inside frame, bars symmetric; **structural**, read
> from the `path.meta` sidecar only, no pixels), `evaluate_transitions`
> (adjacent-episode layout-jump proxy — |Δcoverage| + centre-shift + a
> mode-change penalty, read from `PathMeta` only). All three are **advisory**
> (`_ADVISORY_CHECKS` widened) — measured, reported into the `ReelReport`,
> excluded from `overall`, never a `ReelFailure`: zero blast radius on
> loop-2/`reel_orchestration`/`build_reel`/`deliver`. `ReelCheckSpec` gains
> `clip_tol`/`bar_symmetry_tol`/`layout_jump_max`; `check_reel.run` wires them
> into the existing `geometry` block used by `safe_zones`. **This closes the
> mechanical enumeration under §5.13's editorial half — the stage stays ◐**
> (the spec's gate is "both parts green"); the **agent editorial review (Slice
> B)** is the only part of §5.13 still open. See
> `docs/specs/2026-07-17-reel-final-editorial-checks-design.md`.

> **Built (2026-07-18, the editorial half — Slice B):** `scripts/lib/review.py`
> (`Finding` + `Review` config-specs, `Review.verdict` = revise-iff-any-blocking) +
> `scripts/reel_review.py` (validate the reviewer's raw findings → `REVIEW.json`+
> `REVIEW.md`) + `SKILLS/reel-review/` (a fresh reviewer subagent judges the reel
> against `SPEC` — idea/mood/hook/ending/spine/edl_completeness/trend_flavor — and
> emits routed findings; the human disposes at CP3). **Human-gated (§4.1)** — no
> auto-fix; `check_reel`/`build_reel`/`deliver`/loop-2 untouched. `trend_flavor` is
> judged at forced low confidence (no source until §5.4). **§5.13 is now ✅ — both
> parts green.** See `docs/specs/2026-07-18-reel-review-editorial-design.md`.

### 5.14 deliver → `out/REEL_*.mp4`
`deliver.py`: export per platform (codec/bitrate/fps/resolution/container). SPEC picks the **primary canvas**; deliver optionally **re-reframes** to secondary aspects (a good 9:16 ≠ a good 16:9 → re-run, not just letterbox). Default: primary only; extra aspects on request. **Delivery mode** (`MUSIC.json.delivery`, **set from the invocation text**): `baked` (default) muxes the audio — the with-music export; saying it in the prompt (e.g. "without music" / "без музыки" / "platform sound") emits a music-less version (music stem removed, ambient/SFX kept) + a sidecar note (trending-sound + in/out offset) for adding the platform-licensed sound in-app. Can emit both in one run. (The scripts take explicit args; the user just says it in natural language — `using-montage` parses intent into params, see §5.1.)
**Gate:** platform params correct.

### 5.15 ffmpeg-recipes (reference)
Not a stage — a library. Snippets for crop/color/vidstab/seek/concat + the **landmine registry** (§12). Used by extract, assemble-draft, process-episode, audio-mix, deliver. Goal: "don't reinvent ffmpeg."

### 5.16 titles → `TITLES.json` (optional, on-screen text)
Agent-authored hook / mid-caption / ending text, drawn from `SPEC.hook/text/ending` (§5.3). A typed `TITLES.json` (text, start/dur, font, position, style) is the stage's own artifact — the **render rides `deliver`'s single encode** (§5.14): `drawtext` cannot ride `-c copy`, so titles never get a second-pass intermediate. Positions are **safe-by-construction** presets (top/center/bottom margins), now drawn from the same `SafeZone` table that `check_reel.safe_zones` (§5.13, built 2026-07-16) checks the tracked subject against — an advisory route-geometry check, not pixel-level CV. Fonts resolve by name through a curated library that plain `bash setup.sh` installs (**baseline since 2026-07-20**; the `--with-fonts` flag is deleted); the `drawtext`/`fontfile=` landmine (§12) already covers the failure mode.
**Gate:** every title's text/timing/position/style validates; deliver's encode carries the burned text.

> **Built (2026-07-13, §5.16):** `scripts/lib/fonts.py` (`resolve_font` extracted
> from `draft.py`, +name-mode resolution against a curated cask set) +
> `scripts/lib/titles.py` (`Title`/`Titles` config-specs + `build_filterchain` —
> one `drawtext` per title, `enable='between(t,...)'` windows, per-title
> `textfile=`) + `scripts/titles.py` (`build_titles` projects `SPEC.hook/text/
> ending` into a starting `Titles`; CLI writes `TITLES.json`+`TITLES.md`).
> `deliver.py` gains `titles=` — burns the chain into the one encode it already
> runs (silent and music-muxed paths both covered); `build_reel`/`edl_to_reel`
> thread `titles=` through. Optional `montage.py` Stage (checkpoint `final`);
> `titles` SKILL + `using-montage` CP3 wiring; `setup.sh --with-fonts` installs
> Montserrat/Inter/Bebas Neue/Oswald. Real-ffmpeg golden confirms the encode
> changes pixels inside a title window, both silent and muxed. See
> `docs/plans/2026-07-13-titles.md`.

---

## 6. Follow and composition algorithm (crown jewel)

### 6.1 Following: the tracker authors, the storyboard verifies

The manual 0.1s storyboard from the session was a **workaround for having no reliable tracker**. With YOLO+ByteTrack we flip it:

1. **Tracking** — `track.py`: Ultralytics **YOLOv11-seg (person) + ByteTrack** on the **cut fragment** (`segments/<ep>_raw.mp4`, not the full clip) → `subject_x(t), y(t)` **per frame** (not a 0.1s sample). Robust to foam/other surfers (person class + ID retention) — where the OpenCV HSV blob failed. Detection runs on **downscaled frames** (`imgsz≈960`; ultralytics rescales boxes to source coords) — ~10× faster on 4K, negligible loss for a person-sized subject. Model size is a parameter: `yolo11n-seg` default, `s`/`m` when the subject is small/far. Hero selection: intent-conditioned candidate scoring with a margin rule — §6.1a; an explicit `hero` pin from the manifest overrides (§5.10).
2. **The thirds/direction rule** applies **continuously** (see 6.2).
3. **Non-linear path = damped velocity following.** A path optimizer (Savitzky-Golay smoothing + a crop-speed cap in **px/sec** — frame-rate independent, so 60fps sources get the same on-screen speed; the session's 25 px/frame @30fps ≡ 750 px/s) **naturally** holds the frame on a slow start and accelerates with the subject — exactly what was hand-tuned ("slow start → hold longer, not linear"). The optimizer replaces manual keyframing; the path is clamped to the frame **after** smoothing (savgol overshoots on ramps), then simplified (Douglas-Peucker) into a few linear segments for a short, smooth ffmpeg crop expression.
4. **The 0.1s thirds-grid storyboard is demoted to verification** — `check_episode.py` reads `subject_x(t)` against the target line numerically. The contact sheet is an artifact for the gate and for human review.

**Net:** the manual bottleneck is gone, but **the composition rules become the optimizer's parameters** — no taste lost.

**Degradation ladder (tracking):** ultralytics unavailable or the track is garbage → optical-flow centroid tracker (OpenCV, no ML deps) → manual storyboard keyframes + interpolation (the session's proven method). Each step down is recorded in the episode report as `degraded: <level>` — the pipeline still delivers.

### 6.1a Hero identity — who exactly is being followed

Identity errors were real in the source session, and they have **four distinct failure modes**: (1) intake mislabels who is in a clip (similar outfits, distance, backlight); (2) the most-frames heuristic picks a **loitering bystander over the actual subject** — the subject of an action shot crosses the frame in seconds while a bystander stands in frame the whole clip, so the bias points exactly the wrong way; (3) tracker ID switches on occlusion silently swap the followed person mid-episode — and the postcheck can't see it (it verifies crop vs route, not route vs the right human); (4) nothing ties "the person picked in clip A" to "the person picked in clip B" across the reel. Domain-agnostic: the "subject" is any person — a surfer, a runner, a kid, a dancer. Four layers close the modes:

1. **Cast registry (`cast.json`)** — one interactive pass at intake: the user names the heroes from surfaced crops, once per project. Each name stores an **appearance descriptor**: a color histogram over the person's **segmentation-mask pixels** (clothing/gear only — the mask cuts the background away; YOLO-seg masks are already in the stack). Closes modes 1 and 4. Note the inversion vs the session: HSV failed as a *tracker* (grabbed sea foam), but over a seg mask it is the right *identity descriptor*.
2. **Candidate scoring** — replaces bare most-frames. Per track: frame count, mean area, lateral displacement, mean speed, border share, descriptor. The score is conditioned on the episode's intent: action/follow → **motion dominates** (static bystanders penalized — closes mode 2); static/atmospheric → size + centrality + duration; a cast name in the manifest → **descriptor similarity outranks kinematics**. **Margin rule:** top-2 scores within ~20% → ambiguity → stop-and-report **with both candidates' crops** — this makes §4.1 concrete: *when* to ask = the margin; *what* to show = the crops; the answer = a `hero` pin, optionally saved into the cast.
3. **Continuity guard** — along the chosen track: a descriptor jump + an x-teleport (per-frame |Δx| above a physical cap) + an area jump ⇒ suspected ID switch at time t → split the route, re-match the pieces against the descriptor; unresolved → stop-and-report with the storyboard around t (closes mode 3). The cheap numeric side is a §9 check: **route-continuity** (no teleports in the followed route).
4. **Storyboard marker** — the contact sheet draws a marker on the followed subject in every sampled frame; the editorial gate confirms "right person" at a glance. The human eye stays the final identity oracle, at zero added review cost.

Out of scope, documented: face recognition (faces are small/wet/blurred in action footage; heavy dependency — the layers above make it unnecessary).

**Plan split:** core plan = intent-conditioned scoring + margin flag, route-continuity check, storyboard marker. Ingestion plan = cast registry + interactive naming + descriptor wiring into manifests — **landed 2026-07-16** (`docs/specs/2026-07-16-cast-hero-pin-design.md`): every §5.10 pin form now resolves through `cast.json`, and a pin matching nobody stops and reports rather than falling back to scoring. process-episode plan = descriptor-based continuity re-match (layer 3 above) — a different mechanism against a different failure mode (mid-episode ID switch, not "who is the hero" at all), **now unblocked** since the cast wiring it needs has landed; still its own slice.

**Reuse:** take the stack (YOLO/ByteTrack/PySceneDetect/madmom/essentia/ffmpeg), write our own glue (`reframe.py`) for our rules + color + stabilization. [auto-vertical-reframe](https://github.com/KazKozDev/auto-vertical-reframe) (MIT) is a reference/fallback (its path optimizer, but we don't bend its CLI: it can't do thirds-bias or our color).

### 6.2 Composition = per-episode intent (canon ⊕ trend, overridable)

Composition is a **default, not a law**. Each episode gets `composition` + `grid` + `motion`:

| `composition` | When | reframe.py path | postcheck |
|---|---|---|---|
| `lead` (default, lateral action) | a ride — subject on the "trailing" line, air ahead in the direction of travel | tracked crop + directional lead offset to the grid line | numeric: on the correct line |
| `center` | atmospheric / symmetric / **moving toward camera** / **wade in-out of water** | subject centered, no lateral lead | numeric: near center ±tol |
| `break` | intentional departure from the standard for beauty | tracked, but the rule is relaxed / extreme framing allowed | **editorial only**, no numeric fail |

**`grid` = line-target for `lead`/`center`** (see §6.5 "grid library"):
- **`thirds` (default)** — lines at 0.333/0.667. The line-target for continuous tracking of a moving subject.
- **`phi`** — lines at 0.382/0.618 (golden ratio), a per-episode option where refinement is wanted.
- **Why thirds is the tracking default** (my call): proven in the session (produced a result the user called perfect); matches platform safe-zones; phi sits ~5% closer to center → less air at the leading edge, and the direction rule specifically wants air ahead. phi is available explicitly; golden-canon-grid is a separate static layer (§6.5), not a tracking line-target.

`motion` (auto-classified from the track, overridable):
- **lateral L/R** → the direction rule applies
- **toward camera** (bbox grows, x stable) → direction rule **N/A**; hold center, track scale/zoom, not X
- **static** → fixed frame / slow pan

v1 classifier (`lib/motion.py`): lateral = net |dx| ≥ 15% of source width AND bbox-area growth < 1.6x; head-on = growth ≥ 1.6x AND |dx| below the lateral bar; everything else → static. **Diagonal movers (large dx AND large growth) deliberately fall through to static/center** — centered crop is the safe framing; MVI_3739 (golden fixture source) is exactly this case. Editorial correctness of center-vs-lead for diagonals = open question (§13).

`break` in v1 center-tracks (relaxed = no line target); extreme framing is editorial territory — postcheck stays editorial-only.

**Key:** postcheck verifies against the episode's **declared grid+intent**, not against a global law. `break` = human judgment only — the mechanical check steps aside, an intentional departure never fails the gate.

Defaults from shot-type (overridable): action-follow→`lead`+`thirds` · establishing/atmospheric/wade→`center` · anything you flag→`break`.

### 6.3 Rules = classic canon ⊕ trend lean

- **Base — `references/editing-canon.md`** (in the skill): thirds, headroom, lead room, the 180° rule, cut-on-action, match cut, J/L cuts, continuity, contrast. Read by edit-plan, process-episode, the checks.
- **Trend layer — `TRENDS.md`** (composition section): current deviations (center punch-ins, jump cuts, extreme crops, whip transitions, hook patterns, text style).
- **Blend:** the episode's intent = canon default → nudged by trend directives → overridable by you. Lightly ("a slight lean") — controlled by one knob: **`SPEC.style-lean`** (classic↔trend, e.g. 70/30).
- **The editorial check judges both:** "a solid classic base **and** trend flavor" — all-canon reads dated, all-trend reads gimmicky; the review flags either failure.

Grounding: the session already did this — classic thirds/lead as base, but hard-cuts vs crossfades were verified against 2026 trends and the trend was chosen.

### 6.4 Crop formulas (from the session, generalized)

- 9:16 width from a 1920-wide source = 607px (`int(H×9/16)`). **Generalize**: crop size = a function of `canvas` and source aspect, not a hardcode.
- lead offset **emerges from the grid line, not a separate parameter**: moving right → subject pinned to the LEFT line of the chosen `grid` (thirds 0.333/0.667 or phi 0.382/0.618) → `crop_x = subject_x − line·crop_w`, air ahead = `(1 − line)·crop_w`. The session's hand-tuned +91/−97px offsets ≈ the thirds-line placement (`crop_w/6` from centre) — the grid formalizes what was tuned by eye.
- `crop_x = center − crop_w/2`, clamped to `[0, W−crop_w]`.
- **Y axis (v1):** when the crop uses full source height (vertical canvas from horizontal source — the main case), `y = 0`, nothing to decide. When the crop has Y freedom (canvas wider than the source aspect: 16:9 out of vertical footage, 1:1 out of 9:16), Y is **static per episode** — no y-tracking; the §9 vertical-bounce check guards. Rule: headroom canon — the subject's head near the upper-third line (`head_y ≈ 0.30·crop_h`); no head data → subject centre at `0.45·crop_h`; clamped to `[0, H−crop_h]`.

### 6.5 Composition-grid library (`references/editing-canon.md`)

Three tools of increasing complexity, split across layers — **a line for motion, an armature for static**:

| Grid | What | Where it's used |
|------|------|-----------------|
| `thirds` | 2+2 lines at 0.333/0.667 | **line-target for continuous tracking** (default) |
| `phi` | 2+2 lines at 0.382/0.618 (golden ratio) | tracking line-target, per-episode option |
| `golden-canon-grid` | **dynamic-symmetry armature**: root rectangle + 2 diagonals (baroque/sinister) + 4 reciprocals (⊥ to the diagonals) + horizontals/verticals through the "eyes" of the intersections + phi divisions | **static/editorial layer**, not a line-target |

**Golden Canon Grid is not a per-frame tracking target** (the armature is aspect-locked and static; you can't smoothly pan a moving subject onto a baroque diagonal frame-by-frame). Three static uses:
1. **Hero/static/`center`/`break` frames** — frame to honor the armature: subject on an "eye", horizon/wave lines along the reciprocals, motion along a diagonal.
2. **Editorial overlay** — `storyboard.py` draws the full armature (diagonals + reciprocals + eyes + phi); the editorial check judges the strongest frames against it.
3. **Selection scoring** — intake/edit-plan bonus for moments whose natural composition already lands on an armature diagonal (a wave line along the baroque diagonal).

The storyboard overlay for motion verification draws **thirds + phi** lines (horizontals at each grid's own fractions — phi's at 0.382/0.618, not 1/3); for hero/static — plus the full armature. The armature overlay ships with the process-episode plan; the core engine draws the line grids. `check_episode` verifies against the episode's **chosen** `grid`.

---

## 7. Aspect and layout (platforms differ)

Aspect is a **parameter**, not a hardcoded 9:16. Layout is **per-episode** (horizontal footage can go into a vertical canvas if it fits the story/visual).

- **`SPEC.canvas`** = target WxH per platform (9:16 reel, 4:5 feed, 1:1, 16:9 YouTube…).
- **`EDL.layout`** per episode:

| Layout | When | reframe.py | Status |
|--------|------|-----------|--------|
| `fill` | action, subject moves — a ride | YOLO-tracked crop-to-fill (algorithm §6) | **built** |
| `fit` | a wide/horizontal frame worth keeping whole | scale-inside + **blurred background pad** | **built** |
| `insert` | a horizontal clip as a framed card in a vertical canvas | scale into a placed rectangle over a background, optional border | **built** |
| `fit-solid` | clean/graphic look | scale-inside + solid pad | **built** (2026-07-18) |
| `split` | two clips stacked | stack + pad | planned |
| `pan` | static subject, slow reveal | slow constant-velocity pan | **built** (2026-07-19) |

Proven in the session: the wade-in = `fit-blur` ("wide frame + blurred background top/bottom"), the rides = `fill`.

**These names are presets, not code branches.** A layout is three parameters: a
crop (aspect + scale), a rectangle placed in the canvas, and a background filler.
`fill` is "crop to the canvas aspect, rect = the whole canvas, no filler";
`fit-blur` is "crop nothing, rect = full width, filler = blur"; `insert` is the
same with a smaller rect. Adding `fit-solid` means adding a filler, not a branch.
`fit-blur` is the preset `(fit, blur)` and `fit-solid` is `(fit, solid)` — the
mode names the geometry, `background` names the filler; `fit-solid` landed
2026-07-18 as exactly this (see
[the fit-solid design](2026-07-18-fit-solid-design.md)).

**`pan` is not a layout mode at all, and landed 2026-07-19 on that basis.** Its
row above reads like a fifth preset, but the layouts model already refutes
that: `pan`'s crop/rect/background are `fill`'s, exactly — canvas-aspect crop,
whole-canvas rect, no filler. What a pan actually adds is a second, *declared*
source for the crop's x(t) — a constant-velocity path generated from two
fractions of horizontal freedom (`{"from": f, "to": f}`), used *instead of* a
tracked route, never alongside one. So this slice touches `LayoutSpec` not at
all: no new mode, no new branch in `reframe`'s layout resolution — only a new
motion source next to the existing tracked one. See
[the pan design](2026-07-19-pan-design.md).

**Whether the subject is tracked follows from geometry, not from the layout's
name.** Horizontal freedom is `freedom = src_w − crop_w`. At zero freedom the
crop is as wide as the source, nobody controls the composition, and the check
reports `editorial-only` rather than failing a rule nobody can obey or silently
passing it. Drop `crop_scale` below 1.0 and freedom returns — a `fit-blur` at
`crop_scale=0.9` crops for composition and tracks like any `fill`.

See [the layouts design](2026-07-10-layouts-design.md) for the geometry, the
`path.meta.json` sidecar, and the two silent-corruption defects it retires.

- **Composition rules apply to the visible frame region** — the same math relative to the framed rectangle, not the whole canvas.
- **Safe-zones** keyed to platform+canvas (IG UI bottom/right).
- **reel-final-check:** mixed aspect/layout is **intentional**, not a defect. It checks: pad bars clean (`check_reel.pad_bars` — advisory, structural from the `path.meta` sidecar, built 2026-07-17), subject in safe-zone (`check_reel.safe_zones` — advisory route-geometry vs a platform `SafeZone` table, built 2026-07-16), key action not clipped (`check_reel.key_action` — advisory, frame-edge clip tolerance via `geometry.extent_at_times`, built 2026-07-17), layout transitions not jarring (`check_reel.transitions` — advisory, a layout-jump proxy read from PathMeta, built 2026-07-17) — all four now built (mechanical, advisory); the agent editorial review (§5.13's idea/mood/hook/pacing judgment, Slice B) is built too (2026-07-18) — §5.13 is fully closed.
- **deliver:** primary canvas + optional secondary aspects via re-reframe.

---

## 8. Trend sources (default, overridable)

The user is unsure where to look → a proposed default, layered, cached in `TRENDS.md` (TTL 7–10d):

1. **Primary — TikTok Creative Center** (public: trending sounds, hashtags, top videos; region-settable → Indonesia). Best signal for trending audio + format.
2. **Secondary — monthly roundups** via WebSearch (Metricool / Buffer / Later "Reels trends {month}") → editing conventions (hook, cut-style, transitions, text).
3. **Niche** — WebSearch "{topic} reels {year}" (e.g. surf edits).
4. **Manual override** — lines in `TRENDS.md` are treated as locked.

Output = checkable directives: `hook ≤Xs`, cut-style, transition set, target length band, text-style, trending-sound candidates, composition deviations. Consumed by pacing/edit-plan; verified by reel-final-check. Source unreachable → fall back to manual / last cache.

---

## 9. Check thresholds (starting defaults, tunable)

Numbers make the mandatory checks **automatic** rather than eyeballed. Against the episode's declared composition intent:

| Check | Pass rule |
|-------|-----------|
| On-line (composition=lead) | subject center within ±5% of frame width from the chosen `grid` line (thirds 0.333/0.667 or phi 0.382/0.618), correct side for the direction, on **≥90% of frames** |
| Centered (composition=center) | subject center near frame center ±5% of width, on **≥90% of frames** |
| Head power-point | head in the upper third, ±8% |
| Horizon | tilt < 1.5°; vertical bounce between frames < 1% of height |
| Jitter | no crop-center reversal > max(2px, 0.5% of **crop** width) against the direction of travel — the 2px floor absorbs int-rounding flicker (crop width, not source width: consistent with on-line normalization, keeps the floor meaningful) |
| Route continuity | no x-teleport in the followed route: per-frame \|Δx\| ≤ ~4% of source width; descriptor/area jumps flag a suspected ID switch (§6.1a) |
| break | numeric composition checks skipped (editorial) |
| Color (in-episode) | mean RGB within ±8 of target R105/G122/B137 |
| Color (across cuts) | mean-RGB delta across a cut < 12 |
| Black frames | mean luma > 8 on the first/last 3 frames of each episode |
| Length | within ±0.5s of the SPEC target |
| Beat | each hard cut within ±60ms of a detected beat |
| Loudness | integrated −14 LUFS ±1 |
| Variety | no pair of adjacent episodes with perceptual-hash distance < threshold. **Same source ≠ duplicate**: several windows of one clip are fine if visually distinct (guard by image, not by filename) |

**Status (which plan implements what):**
- **Core plan (`check_episode`):** on-line/centered, jitter, route-continuity (teleport side), length, black frames — implemented; **head power-point** and **horizon** are `planned` (need pose keypoints / line detection) — reports print `not-implemented`, **never** a silent pass.
- **process-episode plan:** color (in-episode) — reframe applies the gain; its verification lands with that plan.
- **Reel back half (`check_reel`):** black, color-across-cuts (median-attributed culprit), variety (phash), length, **loudness** (hard gate) and **beat** (advisory) — implemented (loudness hard, beat advisory; built 2026-07-11); a silent reel (no music/audio supplied) reports `not-checked` for those two, never a silent pass. **safe-zones** is now an advisory route-geometry subject check against a platform `SafeZone` table (built 2026-07-16): the tracked subject, projected into canvas coordinates, is tested against the zone, reporting an advisory pass/False, or `not-checked` when a reel carries no per-episode geometry.

---

## 10. Color / stabilization (from the session)

- **Color:** normalize "softly to the middle". Target R105/G122/B137. `gain = 1 + 0.55×(target/measured − 1)`, clamped `[0.7, 1.5]`. Via `colorchannelmixer=rr=R:gg=G:bb=B`. **`lutrgb` is banned** (produced black frames). A final match-grade pass for consistency across episodes; optional mood LUT.
- **Stabilization:** vidstab two-pass on the **source before crop**: `vidstabdetect=shakiness=8:accuracy=15:result=FILE.trf` → `vidstabtransform=input=FILE.trf:smoothing=40:optzoom=1:zoom=2:crop=black,unsharp=5:5:0.4`. **Do not stabilize the wade in/out shots** — it produces "rolling ground". `stabilize?` flag per episode.

---

## 11. Base effects palette + nice-to-have

**Base effects palette (soft baseline, not a hard constraint).** A small starting toolbox available from the start — shipped in `ffmpeg-recipes` + `editing-canon`. The default is still the hard-cut (the verified 2026 trend), but these are on the table from day one and picked by trend/taste per episode:

- **hard-cut** — default, on-beat (§5.5).
- **crossfade** — `xfade` / audio `acrossfade`, short; for soft/atmospheric joins.
- **slow-mo when apt** — `setpts=SLOW*PTS` (output length = srcdur×slow); punch on drops / to stretch a peak moment.
- **whip / match-cut** — a couple of dynamic transitions for energy/continuity.
- **J/L audio cuts** — audio leads/lags the picture across a cut.

The palette is a floor to build from, not a ceiling — `TRENDS.md` can add more, the editor can override. `reel-final-check` doesn't fail a reel for using or not using any of these; it only flags jarring/overused transitions.

**Nice-to-have:**
- **Speed-ramp to beat**: ramped slow-mo timed to the drop (extends the slow-mo palette item).

**Requirements for the follow-on plans (binding, not nice-to-have):**
- **Version log** (assembly/deliver plan): `REEL_v{n}` naming + one-line changelog per version, lock registry — the session ran v2→v18; iteration is the norm.
- **Resumability** (router plan): every stage skips itself when its artifact exists and the input hash is unchanged — a dead session resumes for free.
- **Executable landmine lint** (recipes plan): lint generated ffmpeg commands — grep for `lutrgb`, for `-ss` before `-i`. Machine-checked landmines don't recur. **Landed 2026-07-20** — `scripts/lib/lint.py`, enforced by `proc.run` at runtime and by an AST scan of `scripts/` statically; see [the landmine lint design](2026-07-20-landmine-lint-design.md), whose §5 lists what it does **not** cover. Two corrections to this charter's own shorthand, both measured: "`-ss` before `-i`" is not by itself a violation (it takes **five** conditions together — a naive positional check false-positives four times out of seven on a clean tree), and a **grep** cannot do this job, because it cannot tell a filtergraph from a comment documenting the ban.
- **Wall-time per stage** (checks plans): recorded in every check report — where the minutes burn stays visible.

---

## 12. Landmine registry (canonical — `references/landmines.md` points *here*; from the session)

- `lutrgb` → black frames. Use `colorchannelmixer`.
- Black frames on cut — the **landmine is in the seek-argument order, NOT in 4K**. Fix: correct seek-arg order (`-ss` after `-i` / output seek, `-accurate_seek`, re-encode the window for frame accuracy), **not** a downscale to 1080. Cut and process 4K natively.
- The **relative** black-frame gate (Bug #3: `worst < black_rel × ref`, so a dark-night clip passes) silently passes a **fully-black** clip — body median `ref → 0` collapses the compare to `0 < 0` (False). Keep the relative gate, but **OR in an absolute body-black floor** (`ref < black_floor`): a body median below the floor is never a legitimate delivery, only the seek/`lutrgb` corruption this check exists to catch. `check_episode._black_frames_check`.
- OpenCV HSV auto-tracker catches foam/other surfers → YOLO person + ByteTrack.
- Stabilizing the wade-in → "rolling ground". Don't stabilize.
- ImageMagick `montage` reorders tiles → false "sawtooth" motion readings. Verify order.
- Loading all frames into memory → OOM. Process frame by frame.
- `vidstabdetect` warning "cannot read frame local motions… got 255" — cosmetic, stabilization still works.
- pip behind a corporate mirror (`nexus.*`) times out off-VPN → `setup.sh` pins `PIP_INDEX_URL=https://pypi.org/simple` (env-overridable).
- `drawtext` without an explicit `fontfile=` fails or picks garbage on macOS → always pass a font path.
- concat of non-uniform segments (size/fps/codec) breaks or desyncs → normalize before concat (§5.9).
- pytest without `pythonpath = .` in `pytest.ini` can't import `scripts.*` (no `tests/__init__.py`) → keep it set.
- ultralytics downloads weights by model **name** (`yolo11n-seg.pt`), not into an arbitrary path → pass names. ~~cache lives in `models/`~~ — **that part was never true**: `setup.sh` only `mkdir -p models` and never points ultralytics at it, so with `weights_dir` unset (or set to a directory that does not exist) the download falls back to the **CWD** — i.e. straight into the repo root. Hence `.gitignore` carries `yolo11*.pt` as well as `models/`. Corrected 2026-07-18; the underlying config gap is not fixed, only contained.
- That same auto-download is a **concurrency landmine**: N workers starting a fan-out on a cold cache each begin the *same* download into the *same* path — concurrent writers to one file. It does not raise; it corrupts. Any code running `track.build_route` in parallel MUST call `track.ensure_model(model)` for every distinct model **before** the pool starts (`scripts/edl_to_reel.py` does). Built 2026-07-18 with the cap-3 fan-out.
- A **unit-tier** test that fakes `process_episode` does **not** thereby avoid ultralytics: `edl_to_reel` calls `ensure_model` itself, above the pool, so the fake never intercepts it. Left real, `tests/lib/` imports torch and, on a cold cache, downloads weights over the network — invisible on a developer box that already has them. Fixtures must stub `ensure_model` too; `tests/integration/` is the only tier whose marker declares weights allowed.
- madmom 0.16.1 from PyPI is broken on python ≥3.10 / numpy ≥1.24 → git master only, and only as an optional extra.
- **`color` is an infinite source, and BOTH obvious remedies for bounding it are
  wrong.** An `overlay` composited against a synthesized `color` background never
  sees end-of-stream on either input, so the encode does not terminate — measured,
  4m12s of output from a 2s source in 20s of wall clock, still going.
  `overlay=…:shortest=1` (or `eof_action=endall`) does terminate, but truncates
  **exactly one frame** off every render, at any rate — measured on the golden
  fixture (source 95 frames, blur 95, solid **94**) and reproduced on synthetic
  1s/3s/5s sources, so it is not a rounding artifact. That one frame is not
  negligible: it accumulates straight into `check_reel`'s 0.5s length band, so
  ~30 solid episodes at 59.94fps (or ~15 at 30fps) consume the whole band from
  this artifact alone. Bounding the *source* instead with `color=…:d={duration}`
  is necessary but **not sufficient**: `color`'s timebase is `1/r` while a decoded
  source carries its **container's** (`1/15360` at 30fps), `overlay` inherits the
  **first** input's timebase — the synthesized background — and the tail's `fps`
  filter reads the mismatch as a stream longer by exactly `container_tb / fps`
  (15360/30 = 512, turning a 3s/90-frame clip into 1536s / 46080 frames). The fix
  is to bound the **output**: `-t {duration}` on the ffmpeg command, applied
  unconditionally to every layout (measured a no-op for `fill`/`blur`, so no
  future filler can forget it). **The trigger is an exact rate match, NOT a
  particular frame rate** — this is the part that misleads: it fires whenever the
  emitted `r=` reproduces the source's rational rate *exactly*, so integer rates
  (24/25/30/50/60) blow up while NTSC fractional ones do not. The 59.94fps golden
  fixture blows up too when handed `r=60000/1001`; it survives only because
  `f"{fps:.6g}"` mangles that to `59.9401`, which no longer matches — a
  **formatting accident**, not a tested safety margin. A maintainer adding a
  29.97fps fixture to "cover another rate" would prove nothing, since NTSC never
  triggers this class of failure at all — cover an integer rate, or cover
  nothing. One more consequence follows directly: a filtergraph capable of
  running forever turns a test failure into a hung suite (measured 90s-and-killed
  against a 0.8s normal run, on a machine with no `timeout`/`gtimeout` binary to
  bound it from outside) — `proc.run` now carries a default timeout
  (`DEFAULT_TIMEOUT_S`) and raises instead of hanging, because an unbounded wait
  is not a test result. `scripts/reframe.py` (`_background_args`/`reframe`),
  `scripts/lib/proc.py`. See
  [the fit-solid design](2026-07-18-fit-solid-design.md) §4/§8.
- **`background_color` reaches an ffmpeg argument.** It carries the same
  injection surface as `border_color` and gets the same guard (refuses
  `,:;'[]\` and an empty string) — a colour string is not a safe literal just
  because it is short. `scripts/lib/models.py` (`LayoutSpec.__post_init__`). See
  [the fit-solid design](2026-07-18-fit-solid-design.md) §3/§8.
- essentia has no macOS arm64 wheels → out of v1 (§5.5).
- ffmpeg expression parser chokes on long crop-x expressions ("Missing ')' or too many args") — a realistic-length noisy path can produce 1000+ Douglas-Peucker knots → cap knots (~80) by doubling eps; never emit per-frame if() chains.
- odd output dimensions + yuv420p → libx264 "width not divisible by 2" → force even scale targets for EVERY canvas, not just 9:16 (floor-truncated crop widths are odd half the time). `Delivery` evens native/short_edge/long_edge in `dims()`; `exact` must **not** silently round (the mode is *exact* — shipping 404x720 for a requested 405x721 is the corruption we forbid) → it raises in `Delivery.__post_init__` on odd dims with a fix-it remedy, so a bad exact size cannot be constructed at all.
- ByteTrack unconfirmed detections carry `id=None` → bucketing them under one sentinel id splices different people into a fake track that can win hero scoring → drop id=None detections; the gap is bridged by smoothing.
- **Never smooth a generated path, and the endpoints alone cannot prove it.** `pathsmooth.smooth` is for observation noise; its rate limiter only bites near `max_speed`, so a realistic slow reveal (1920px/10s = 192 px/s, the dominant case) survives a full `smooth()` pass with **byte-identical endpoints** — measured: routing `generate_pan_path`'s output through the real smoother left 11 of 12 tests green, including the one whose comment claimed to be the proof. Only a test that monkeypatches the smoother to fail if called at all — asserting the branch, not an outcome the other branch can also produce — catches it. `scripts/reframe.py` (`generate_pan_path`). See [the pan design](2026-07-19-pan-design.md) §4.2/§10/§11.
- **Never synthesize a route to keep a consumer working.** An empty or fabricated `route.json` is not a neutral placeholder: an empty route already means "the tracker found nobody" (fires `no-track` if run through the contradiction gate), and a fabricated one turns `check_episode`'s composition check circular (scores the crop against a subject derived from that same crop) and makes the storyboard mark a hero who does not exist. `checks.continuity([])` returns `pass=True` — its `zip` over an empty route never iterates — so the absence is not even loud. `scripts/process_episode.py`, `scripts/check_episode.py`. See [the pan design](2026-07-19-pan-design.md) §2/§2.1/§6.1.
- **A validator that checks a ratio cannot see the quantity it will be multiplied by.** `PanSpec` honestly refuses `start == end`, but it validates *fractions of freedom*, not pixels — a span under half a pixel (e.g. `0.5 → 0.5004` at `freedom=875`) rounds both ends onto the same integer, and the render is a static frame nobody asked for, the same silent-static-frame failure a `freedom <= 0` guard exists to prevent, reached by a different road. `scripts/reframe.py` (`generate_pan_path`'s `x0 == x1` raise, downstream of `PanSpec`, where the pixel arithmetic is actually visible). See [the pan design](2026-07-19-pan-design.md) §11.
- **`is not None` is not truthiness on a dict-valued optional.** An empty dict is falsy, so `if m.pan:` (instead of `if m.pan is not None:`) silently treats `{}` the same as absent — skipping validation in `manifest.validate()` (a clean gate for a pan that cannot construct) or dropping the key entirely in `edl.to_manifest_dict` (so `Manifest.from_dict` never even sees it). Both mutations left the whole suite green. `pan: {}` means an author started a pan and stopped; `pan` absent means none was intended — only one of those is a mistake, and truthiness cannot tell them apart. `scripts/lib/manifest.py`, `scripts/lib/edl.py`. See [the pan design](2026-07-19-pan-design.md) §11.
- **`cmd | grep -q pattern` under `set -o pipefail` can only ever report "not found".**
  `grep -q` exits 0 at its first match, so a producer with output still to write loses its
  reader, takes `SIGPIPE` and exits **141**; `pipefail` promotes that to the pipeline's
  status. When the pattern is genuinely absent, `grep` reads to EOF and exits 1. Both arms
  are non-zero, so the test is a tautology — and `if ! …` around it makes the guarded
  branch unconditional. `setup.sh` gated `brew uninstall --ignore-dependencies ffmpeg` on
  exactly this shape, so it ran that uninstall on machines where the filter it was checking
  for was **present** (measured 141 on 5 of 5 runs against a build carrying `drawtext`, and
  0 on the same command without `pipefail`); the branch's own post-install verification used
  the same idiom without the `!`, so it aborted with "drawtext still missing" on a build that
  had it. It needs a producer whose output outruns the pipe buffer — a ~36KB
  `ffmpeg -filters` with the match ~15.8KB in does, a short one may not — which is why the
  idiom survives casual testing and reads as obviously correct. In any script with `pipefail`
  set: capture once and match in-shell (`OUT="$(cmd)"` then `case`), never `| grep -q`.
  `setup.sh`. See [the ffmpeg baseline design](2026-07-20-ffmpeg-baseline-design.md) §1/§6.

---

## 13. Open questions (resolve at implementation)

1. ~~Model weights~~ **Resolved (2026-07-06):** model size is a runtime parameter — `yolo11n-seg` default, `s`/`m` for small/far subjects; weights auto-download by name, cached in `models/`; detection at `imgsz≈960`.
2. ~~madmom vs librosa~~ **Resolved (2026-07-06):** librosa is the v1 stack; madmom (git master) documented as an optional upgrade, not wired in.
3. **TikTok Creative Center** — how stable is public access without an API; scraping fallback is fragile.
4. **style-lean default** — 70/30 proposed, calibrate on real runs.
5. ~~essentia mood models~~ **Resolved (2026-07-06):** essentia dropped from v1; mood v1 = librosa features + agent judgment (§5.5).
6. **Thresholds §9** — starting values, calibrate on the first reels.
7. ~~Vocal detection for start snapping~~ **Resolved for v1 (2026-07-06):** snap to a section-boundary downbeat; demucs phrase-boundary snapping is the documented upgrade.
8. **Music discovery APIs** — Spotify needs client creds (optional; iTunes/Deezer keyless); how to degrade gracefully when no creds.
9. **yt-dlp fragility** — source availability/format churn; retry + fallback source order for `music_fetch.py`.

---

## 14. Conventions adapted from superpowers (independent set)

video-grid installs as a **self-contained, independent** skill set — no runtime dependency on the superpowers plugin. But the superpowers *approach* is excellent, so we **copy the conventions and process patterns into our own montage skills** and credit the inspiration (each skill's description + the README: "approach adapted from superpowers"). Survey of superpowers v5.1.0 below; §14.2–14.6 are the concrete patterns we replicate.

### 14.1 Which superpowers patterns we replicate (baked into our own skills)

| superpowers skill | Pattern we copy | Lands in our skill |
|---|---|---|
| `brainstorming` | context recon → one-question-at-a-time → HARD-GATE → spec self-review → user-review gate | `reel-brief` |
| `writing-plans` | Goal/Arch/Stack header, checkbox steps, exact file lists, no placeholders | `edit-plan` |
| `subagent-driven-development` | per-episode dispatch, full task inline, self-review, two-stage review | `process-episode` + `episode-postcheck` |
| `dispatching-parallel-agents` | independent-domains → parallel fan-out | `process-episode ×N` |
| `verification-before-completion` | no claim without fresh evidence (Iron Law) + claim table | `episode-postcheck`, `reel-final-check` |
| `systematic-debugging` | phased root-cause; 3+ fails → escalate | `montage-debugging` reference (§14.6) |
| `requesting`/`receiving-code-review` | editorial review loop | the editorial half of both checks |
| `using-superpowers` | "1% → invoke" router + announce + TodoWrite | `using-montage` |

Cross-skill refs point to **our own** skills (`video-grid:<skill>`), never to superpowers — the set stands alone.

### 14.2 SKILL.md authoring conventions (mirror exactly)

- **Frontmatter:** `name: kebab-case`; `description: "Use when <triggers/symptoms only — NEVER the workflow>"` (≤500 chars). Ref `writing-skills/SKILL.md:95–102`.
- **Section order:** Overview (core principle 1–2 lines) → When to Use (+ small flowchart if a decision is non-obvious) → The Process (flowchart or numbered steps) → Red Flags → Rationalization table → domain sections. Ref `writing-skills/SKILL.md:113–137`.
- **Flowcharts in Graphviz dot:** `shape=box` action, `shape=diamond` decision, `shape=doublecircle` terminal; edge labels for branches. Ref `test-driven-development/SKILL.md:48–69`.
- **Announce on entry:** `"Using <skill> to <purpose>."` then, if the skill has a checklist, **one TodoWrite item per checklist item, done in order**. Ref `using-superpowers/SKILL.md:56–60`.
- **Cross-skill refs:** `**REQUIRED SUB-SKILL:** Use video-grid:<skill>` — name only, **never `@`-links** (force-load burns context). Ref `writing-skills/SKILL.md:282–287`.
- **No placeholders** in plans/specs: no "TBD", "tweak later", "optimize bitrate later". Ref `writing-plans/SKILL.md:106`.

### 14.3 Gates, terminal states, hand-off

- Each skill names its **ONE official next skill** — no branching hand-offs. `brainstorming`'s "the ONLY next skill is writing-plans" (`brainstorming/SKILL.md:65`) → mirror per stage in the §4 flow.
- **HARD-GATE blocks** wrap the no-go rule + explicit loophole closure. Ref `brainstorming/SKILL.md:12–18`. For montage: *no episode processing / encoding until the EDL + draft are approved.*
- **Two-stage review** (already our two-layer checks): spec/editorial compliance ✓ **before** technical quality ✓. Ref `subagent-driven-development/SKILL.md:42–87` → maps to `episode-postcheck` (editorial then mechanical) and `reel-final-check`.

### 14.4 Subagent prompt discipline (for `process-episode`)

From `subagent-driven-development/implementer-prompt.md:6–98`:
- **Full task text inline** in the subagent prompt — never "read the plan file". Our episode manifest (§5.10) already does this; keep it self-contained.
- **Self-review gate** before returning: completeness / quality / discipline / verification — the subagent fixes issues before reporting. Add this to the `process-episode` loop.
- Ask clarifying questions **before** starting if the manifest is ambiguous.

### 14.5 Verification Iron Law (adopt in both checks)

`verification-before-completion/SKILL.md:17–61`: **no completion claim without fresh evidence** — IDENTIFY→RUN→READ→VERIFY→CLAIM. Add a montage claim table to `reel-final-check`:

| Claim | Requires (fresh evidence) | Not sufficient |
|-------|---------------------------|----------------|
| Reel complete | ffprobe: exit 0 + duration = SPEC ±0.5s | "script finished" |
| On beat | cut timestamps vs detected beats, all within ±60ms | "feels on beat" |
| No black frames | `blackdetect` output empty | "looked fine on scrub" |
| Loudness ok | `loudnorm` measured −14 LUFS ±1 | "sounds loud enough" |
| Subject framed | `check_episode` numeric pass per grid | "looks centered" |

### 14.6 Stage-failure debugging

A `montage-debugging` reference (patterned on superpowers `systematic-debugging`, copied in, not depended on) drives stage failures (encode error, sync drift, black frames, tracker loss): root-cause → pattern → single hypothesis → minimal fix; **3+ fixes fail → question the approach / escalate**, don't brute-force. Ref `systematic-debugging/SKILL.md:46–213`. The `landmines.md` registry (§12) is the "working examples / known differences" input for the pattern phase.

---

## 15. What's next

The deliverable is this specification only. Next step: `writing-plans` → a detailed implementation plan (per skill/script, with TDD where applicable). Implementation in a separate session. Flagship for the first implementation if we trim scope: `extract` + `process-episode` + `reframe.py` + `ffmpeg-recipes` + `episode-postcheck` — the core; everything else as scaffolding.

Real-footage validation is user-driven: the Jul 3–5 footage gets re-edited with the pipeline when its owner re-montages — a natural acceptance run, not a blocking milestone. The core plan instead carries a small committed **golden fixture** (2–3s real clip + frozen route) so the engine is never synthetic-only.
