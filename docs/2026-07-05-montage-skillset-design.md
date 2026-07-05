# Montage Skill Set — Design Spec

**Date:** 2026-07-05
**Author:** Sergei (vasechkoss@gmail.com) + Claude
**Status:** design approved, ready for `writing-plans`
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

---

## 2. Skill layout

Runs in Claude Code mode (environment access available). The skill is isolated via a local venv.

```
montage/
├── SKILLS/
│   ├── using-montage/SKILL.md          # router ("1% → invoke" rule)
│   ├── footage-intake/SKILL.md
│   ├── reel-brief/SKILL.md
│   ├── trend-scan/SKILL.md
│   ├── music-and-mood/SKILL.md
│   ├── pacing/SKILL.md
│   ├── edit-plan/SKILL.md
│   ├── extract/SKILL.md                # cuts EDL windows into standalone fragments
│   ├── assemble-draft/SKILL.md
│   ├── process-episode/SKILL.md        # subagent, crown jewel
│   ├── episode-postcheck/SKILL.md      # gate
│   ├── audio-mix/SKILL.md
│   ├── reel-final-check/SKILL.md       # gate
│   ├── deliver/SKILL.md
│   └── ffmpeg-recipes/SKILL.md         # reference + landmine registry
├── references/
│   ├── editing-canon.md                # classic editing rules + grid library (thirds/phi/golden-canon-grid)
│   ├── landmines.md                    # learned failures (see §12)
│   └── montage-debugging.md            # phased stage-failure debugging (patterned on systematic-debugging)
├── scripts/
│   ├── intake.py  beats.py  track.py  extract.py  reframe.py  storyboard.py
│   ├── check_episode.py  check_reel.py  mix.py  assemble.py  deliver.py  trends.py
├── requirements.txt
├── setup.sh                            # creates .venv, installs deps, downloads weights
├── models/                             # YOLO weight cache (downloaded once)
└── .venv/                              # local, gitignored
```

### Environment (venv, no system pollution)

```bash
# setup.sh (idempotent)
python3 -m venv "$SKILL_DIR/.venv"
"$SKILL_DIR/.venv/bin/pip" install -r "$SKILL_DIR/requirements.txt"
# download YOLO weights into models/ if missing
```

- All scripts run **only** via `.venv/bin/python`, never system python.
- `using-montage` step 0 = ensure-env: if `.venv` is missing → run `setup.sh`. Self-healing.
- `requirements.txt`: `ultralytics` (YOLOv11 + ByteTrack), `pyscenedetect`, `madmom`, `essentia`, `numpy`, `scipy`, `imagehash`, `Pillow`. ffmpeg/ffprobe are system (external).

---

## 3. Artifacts (docs/ folder, separate from raw footage)

Everything in `docs/montage/<project>/` — under git, raw footage untouched:

| File | Written by | Contents |
|------|-----------|----------|
| `FOOTAGE.md` | footage-intake | per clip: who, what, quality, shaky flag, scene-cuts; **list of moments** (one clip → several windows), each window with its own shot-type guess, description, score |
| `SPEC.md` | reel-brief | reel count, platform+canvas, length, mood, music, hook, text, ending, style-lean |
| `TRENDS.md` | trend-scan | trend cache (fetch date, TTL 7–10d): cut-style, transitions, hook patterns, text-style, composition deviations, trending-sound candidates |
| `MUSIC.json` | music-and-mood | beat-grid, downbeats, drop, **energy-curve** (RMS), mood-vector, cut-map, **start_offset** (chosen track fragment), **vocal-map** (phrase boundaries for start snapping) |
| `PACING.md` | pacing | **energy spine**: episode order + target length + energy level, pinned to music sections, hook first |
| `EDL.md` | edit-plan | ordered episodes: source+window, shot-type, layout, composition, grid, motion, processing-notes, beat-slot |
| `SOURCES.md` | process-episode | lock file (🔒 per episode) — the session's `REEL_SOURCES.md` promoted to a contract; **one source may feed multiple episodes** (different windows) |
| `segments/<ep>_raw.mp4` | extract | **cut fragments** per EDL window — input for draft and process-episode (not full clips) |
| `checks/*.json` | *-check | mechanical-check reports |
| `storyboards/*.jpg` | storyboard | contact sheets with a grid (thirds + phi; for hero/static — the full golden-canon armature) — **verification artifact** |
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

Gates are hard: a stage does not exit until its exit conditions are met. A failed check → loop back, not forward.

---

## 5. Skills — in detail

### 5.1 using-montage (router)
Entry point. The "if there's a 1% chance a skill applies → invoke it" rule. Step 0: ensure-env (venv). Routes through stages 1–13. Analogous to `using-superpowers`.

### 5.2 footage-intake → `FOOTAGE.md`
`intake.py`: ffprobe (duration/resolution/fps) + PySceneDetect (scene boundaries) + YOLO sample (who/how many people) + shake estimate (vidstabdetect magnitude). **One clip → several moment-windows**, not one: a long ride/take contains distinct fragments (grounding: MVI_3739 = one 22s ride → `lena_ride` + `lena_ride2` + `lena_nose`; MVI_3998 → two hang-fives). intake segments each clip into candidate windows (sub-scenes + motion/people) and **scores each window separately**. Cull/selection step: rank windows across all footage, mark the best moments — several may come from one source.
**Gate:** every clip logged, faces/people tagged, moment-windows carved out and scored.

### 5.3 reel-brief → `SPEC.md` (= brainstorming)
Our own skill that copies the brainstorming approach (context recon first, one question at a time, HARD-GATE before processing, spec self-review) — see §14. Dialogue about the idea: reel count, platform(s)+canvas, length, mood, track, hook intent, text, ending, **style-lean** (classic↔trend). Different reels = different clips (minimal repeats), different endings.
**Gate:** mood + platform/canvas + length + hook locked.

### 5.4 trend-scan → `TRENDS.md` (cache TTL 7–10d)
`trends.py`. Layered source (see §8). Cache stamped with fetch date: fresh → reuse; older than 7–10d → refetch. Output is a **short list of checkable directives**, not a blob. Manual override: user writes lines in, the agent treats them as locked.
**Gate:** fresh cache or manual input.

### 5.5 music-and-mood → `MUSIC.json`
`beats.py`: **madmom** (RNN+DBN) → beats + downbeats + drop; **essentia** → sections, RMS energy-curve, mood-vector (valence/arousal). **Mood-match**: the track's mood is matched against the reel's mood (cosine distance between mood-vectors), and the track's energy sections (build/drop/release) are aligned to the visual energy — music and picture are **one arc**, not two glued halves. Cut-map: cut points ↔ beats/downbeats.
**Track-fragment selection:** the track **need not start at 0:00** — pick the strongest segment of the melody (by sections/energy/drop) for the reel length, don't force 0:00 (session: ODESZA `-ss 15`, Billie `-ss 13`). Record `start_offset`.
**Vocal-aware start:** if the chosen window has vocals, the in-point **snaps to a vocal phrase boundary**, never mid-word. Detection: stem separation (demucs, optional) or VAD → RMS of the vocal stem → phrase gaps = valid in-points; the start snaps to the nearest boundary. No vocals → snap to a downbeat.
Mode D: online — the agent searches/downloads the track; offline — a local track folder + `TRENDS.md`. Beat detection is **always local**.
**Gate:** mood matches SPEC, cut-map built, `start_offset` chosen, start doesn't break a word.

### 5.6 pacing → `PACING.md` (energy spine)
A shared artifact read by **both** music-and-mood **and** edit-plan. Episode order + each episode's target length + energy level, pinned to music sections. Hook first. This makes "the mood matches, not two halves" **structural**, not eyeballed. Episode length is variable (short cutaways where rhythm is needed, long ones where a maneuver/ride must be shown fully).
**Gate:** order+length+energy pinned to the music.

### 5.7 edit-plan → `EDL.md` (= writing-plans)
Our own skill that copies the writing-plans format (checkbox steps, exact file lists, no placeholders) — see §14. Each episode binds to a slot in `PACING`: source+window, **shot-type**, **layout**, **composition**, **grid** (thirds/phi), **motion**, processing-notes, beat-slot. See §6 (composition) and §7 (layout). This is a **map** (which file holds what and from which timestamp to view) — no cutting yet.
**Gate:** every episode has source+window+shot-type+beat-slot.

### 5.8 extract → `segments/<ep>_raw.mp4`
`extract.py`: using the windows from `EDL`, **cut each episode into a standalone file** — once, with **correct seek arguments** (see §12; the bug was in the call args, not in 4K). Frame-accurate cut (re-encode of the short window). From here on both the draft and `process-episode` work on these small fragments — no seeking through 300MB, no scanning the whole file. 4K is cut natively (no proxy/downscale — quality preserved).
**Gate:** every episode from `EDL` has its own `segments/<ep>_raw.mp4`, length matches the window.

### 5.9 assemble-draft → `draft.mp4`
`assemble.py`: concat of the **segments** (`segments/*_raw.mp4`) into the **whole draft at once**, almost no processing, with **burnt-in labels** — what will be processed and where (from the EDL processing-notes). A check of the whole shape before polishing. After plan/draft approval the segments are locked as the working input.
**Gate:** full length, lands on beats, plays.

### 5.10 process-episode → `out/<ep>.mp4` 🔒 (subagent, crown jewel)
See §6. Runs **as a subagent, one per episode**, in parallel (via `dispatching-parallel-agents`). The subagent's context = only `{segment: segments/<ep>_raw.mp4, shot-type, layout, composition, grid, motion, line/center-target, color-target, stabilize?, canvas, out-path}` + `reframe.py` + `ffmpeg-recipes`. Input is the **cut fragment**, not the full clip (small file, no seeking through 300MB). Loop: track → reframe → storyboard → episode-postcheck → (fail? retry) → return 🔒 clip + report. The main thread never loads episode detail.
**Gate:** episode-postcheck passes.

### 5.11 episode-postcheck (gate)
Mandatory step. Two parts:
- **Mechanical** (`check_episode.py`): thresholds §9 — against the episode's declared composition intent (not against a global rule-of-thirds law).
- **Editorial**: "does this episode read well?" — matches the episode's intent.
Both must pass. Fail → back to reframe.

### 5.12 audio-mix → `out/audio`
`mix.py`: music + **ambient ducking** (sidechaincompress) + SFX (whoosh on transitions) + **loudnorm −14 LUFS** (EBU R128). afade in/out.
**Gate:** loudness in range.

### 5.13 reel-final-check (gate) — mandatory whole-reel check
Two parts:
- **Mechanical** (`check_reel.py`): black frames (blackdetect), loudness (loudnorm measure), cuts-on-beat, color deltas across cuts, **variety-guard** (perceptual hash — no near-duplicates back to back), length, safe-zones.
- **Editorial** (agent, like `requesting-code-review`): does the reel deliver SPEC's original idea? Mood/story? Hook strong? Ending right? Pacing along the spine? Anything from EDL missing/weak? Classic base **and** trend flavor (not bland, not gimmicky). → findings → fix loop → re-check.
**Gate:** both parts green.

### 5.14 deliver → `out/REEL_*.mp4`
`deliver.py`: export per platform (codec/bitrate/fps/resolution/container). SPEC picks the **primary canvas**; deliver optionally **re-reframes** to secondary aspects (a good 9:16 ≠ a good 16:9 → re-run, not just letterbox). Default: primary only; extra aspects on request.
**Gate:** platform params correct.

### 5.15 ffmpeg-recipes (reference)
Not a stage — a library. Snippets for crop/color/vidstab/seek/concat + the **landmine registry** (§12). Used by extract, assemble-draft, process-episode, audio-mix, deliver. Goal: "don't reinvent ffmpeg."

---

## 6. Follow and composition algorithm (crown jewel)

### 6.1 Following: the tracker authors, the storyboard verifies

The manual 0.1s storyboard from the session was a **workaround for having no reliable tracker**. With YOLO+ByteTrack we flip it:

1. **Tracking** — `track.py`: Ultralytics **YOLOv11-seg (person) + ByteTrack** on the **cut fragment** (`segments/<ep>_raw.mp4`, not the full clip) → `subject_x(t), y(t)` **per frame** (not a 0.1s sample). Robust to foam/other surfers (person class + ID retention) — where the OpenCV HSV blob failed.
2. **The thirds/direction rule** applies **continuously** (see 6.2).
3. **Non-linear path = damped velocity following.** A path optimizer (Savitzky-Golay / min-jerk smoothing + max-step-per-frame damping) **naturally** holds the frame on a slow start and accelerates with the subject — exactly what was hand-tuned ("slow start → hold longer, not linear"). The optimizer replaces manual keyframing.
4. **The 0.1s thirds-grid storyboard is demoted to verification** — `check_episode.py` reads `subject_x(t)` against the target line numerically. The contact sheet is an artifact for the gate and for human review.

**Net:** the manual bottleneck is gone, but **the composition rules become the optimizer's parameters** — no taste lost.

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
- lead offset: moving right → left grid line → `center = subject_x + lead`; moving left → right line → `subject_x − lead`. The target line = the line of the chosen `grid` (thirds 0.333/0.667 or phi 0.382/0.618). **Generalize**: `lead` as a **fraction of frame width**, not pixels (the session used +91/−97 on a 1080-wide frame ≈ 0.084/−0.090·W).
- `crop_x = center − crop_w/2`, clamped to `[0, W−crop_w]`.

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

The storyboard overlay for motion verification draws **thirds + phi** lines; for hero/static — plus the full armature. `check_episode` verifies against the episode's **chosen** `grid`.

---

## 7. Aspect and layout (platforms differ)

Aspect is a **parameter**, not a hardcoded 9:16. Layout is **per-episode** (horizontal footage can go into a vertical canvas if it fits the story/visual).

- **`SPEC.canvas`** = target WxH per platform (9:16 reel, 4:5 feed, 1:1, 16:9 YouTube…).
- **`EDL.layout`** per episode:

| Layout | When | reframe.py |
|--------|------|-----------|
| `fill` | action, subject moves — a ride | YOLO-tracked crop-to-fill (algorithm §6) |
| `fit-blur` | a wide/horizontal frame worth keeping whole | scale-inside + **blurred background pad** |
| `fit-solid` | clean/graphic look | scale-inside + solid/gradient pad |
| `insert` | a horizontal clip as a framed card in a vertical canvas | scale into a placed rectangle over a background |
| `split` | two clips stacked | stack + pad |
| `pan` | static subject, slow reveal | slow constant-velocity pan |

Proven in the session: the wade-in = `fit-blur` ("wide frame + blurred background top/bottom"), the rides = `fill`.

- **Composition rules apply to the visible frame region** — the same math relative to the framed rectangle, not the whole canvas.
- **Safe-zones** keyed to platform+canvas (IG UI bottom/right).
- **reel-final-check:** mixed aspect/layout is **intentional**, not a defect. It checks: pad bars clean, subject in safe-zone, key action not clipped, layout transitions not jarring.
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
| On-line (composition=lead) | subject center within ±5% of frame width from the chosen `grid` line (thirds 0.333/0.667 or phi 0.382/0.618), correct side for the direction |
| Centered (composition=center) | subject center near frame center ±5% of width |
| Head power-point | head in the upper third, ±8% |
| Horizon | tilt < 1.5°; vertical bounce between frames < 1% of height |
| Jitter | no crop-center reversal > ~0.5% of width against the direction of travel |
| break | numeric composition checks skipped (editorial) |
| Color (in-episode) | mean RGB within ±8 of target R105/G122/B137 |
| Color (across cuts) | mean-RGB delta across a cut < 12 |
| Black frames | mean luma > 8 on the first/last 3 frames of each episode |
| Length | within ±0.5s of the SPEC target |
| Beat | each hard cut within ±60ms of a detected beat |
| Loudness | integrated −14 LUFS ±1 |
| Variety | no pair of adjacent episodes with perceptual-hash distance < threshold. **Same source ≠ duplicate**: several windows of one clip are fine if visually distinct (guard by image, not by filename) |

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
- **Version log**: changelog of versions (the session ran v2→v18); diff between versions, lock registry.

---

## 12. Landmine registry (`references/landmines.md`, from the session)

- `lutrgb` → black frames. Use `colorchannelmixer`.
- Black frames on cut — the **landmine is in the seek-argument order, NOT in 4K**. Fix: correct seek-arg order (`-ss` after `-i` / output seek, `-accurate_seek`, re-encode the window for frame accuracy), **not** a downscale to 1080. Cut and process 4K natively.
- OpenCV HSV auto-tracker catches foam/other surfers → YOLO person + ByteTrack.
- Stabilizing the wade-in → "rolling ground". Don't stabilize.
- ImageMagick `montage` reorders tiles → false "sawtooth" motion readings. Verify order.
- Loading all frames into memory → OOM. Process frame by frame.
- `vidstabdetect` warning "cannot read frame local motions… got 255" — cosmetic, stabilization still works.

---

## 13. Open questions (resolve at implementation)

1. **Model weights** — which exact YOLOv11-seg version to ship/download; size (n/s/m) for speed vs accuracy.
2. **madmom vs librosa** — madmom is more accurate on downbeats but heavier to install (needs old numpy). Possibly librosa as a light default + madmom optional.
3. **TikTok Creative Center** — how stable is public access without an API; scraping fallback is fragile.
4. **style-lean default** — 70/30 proposed, calibrate on real runs.
5. **essentia mood models** — which ones exactly (valence/arousal regressors) and their weight in mood-match.
6. **Thresholds §9** — starting values, calibrate on the first reels.
7. **Vocal detection for start snapping** — demucs (more accurate, heavier) vs a light spectral VAD; is a stem needed at all or is vocal-activity enough.

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
