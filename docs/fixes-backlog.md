# Fixes backlog — real-run findings

Quality issues found running the pipeline on real footage (surf session,
`MVI_*`/`DJI_*` clips). A living list: entries are added as they surface during a
review pass, then promoted to a design/plan when work starts. This is **not** the
feature-deferral log (that lives in [build-status.md](build-status.md) under
*Deferred / open*) — these are defects and quality gaps observed in output.

**North star (2026-08-03):** push this montage toward **professional editing** —
at minimum match what a tool like **CapCut** can do. Weigh each item below against
"does this move the output toward pro-grade?".

**Synthesis:** [cinematic-quality-playbook.md](cinematic-quality-playbook.md) groups
these items with researched editing craft and the session verdict into one working
doc (the "why" + priority + the mood-preset idea). That is the doc we develop from;
this file stays the itemized source.

Status legend: **DESIGN APPROVED** (brainstormed, ready for writing-plans) ·
**NEEDS INVESTIGATION** (symptom captured, root cause not yet confirmed) ·
**PLANNED** (plan written) · **DONE** (shipped, keep one line then move to
build-status Done).

---

## 1. Hero identity — replace the colour-histogram descriptor with a person-re-ID embedding

**Status:** DESIGN APPROVED (2026-08-03). Not yet planned/built.

**Symptom (reported):** hero selection on real footage is very poor — the
candidate list collapses genuinely different people together, and the actual
heroes do not surface for naming (the user had to hand-make reference crops
`t1.png`/`t3.png` instead of picking from candidates).

**Root cause (confirmed on the real cache):** the appearance descriptor
([`lib/appearance.py`](../scripts/lib/appearance.py) `build_descriptor`) is a
24-dim L1-normalized RGB colour histogram (8 bins × 3 channels) over the seg-mask
pixels. It encodes clothing colour, not identity. On surf footage (dark/navy
wetsuits, water background, small far subjects) it is not separable:

- Whole-cache scan: **4062 tracks** → greedy dedup @`CAST_DEDUP=0.30` leaves
  **892 "identities"** → `surface_crops` caps at **top_n=8**.
- Two opposite failures at once: **over-merge** (one surfaced candidate absorbed
  41 tracks from 24 clips within 0.30 — including a child) *and* **over-split**
  (892 survivors for a session with a handful of real people).
- Pairwise L1 among the 8 surfaced candidates clusters at **0.37–0.7**, straddling
  both the 0.30 dedup line and the downstream `CAST_MATCH=0.6` line. Threshold
  tuning cannot fix it — true-match and false-match distances overlap because the
  feature does not encode identity.
- The proxy is NOT involved: `make_proxy` is intake-only and ephemeral
  (`TemporaryDirectory`); cast crops are verified full-res original
  (candidate_0 = 331×926 px, sharp). No downstream stage reads a proxy. The
  earlier "conveyor uses proxy versions" suspicion was ruled out — crops are big,
  the candidate *list* is the problem.

**Decisions locked (brainstorm 2026-08-03):**
- Real person-re-ID embedding (not a better handcrafted feature).
- Model: **OSNet** via `torchreid` (Market-1501 pretrained, 512-dim, cosine),
  behind a clean `lib/reid.py` boundary so swapping to CLIP/torchvision is a
  one-file change. New dependency + `setup.sh` step (user installs).
- Surface: **agglomerative clustering** into the real number of people, each
  person once, ranked by **presence** (on-screen seconds across all clips), not
  YOLO confidence. Adaptive cap (~15) with a logged truncation (no silent caps).
- Migration: **none** — a `CACHE_VERSION` bump and a clean fresh re-scan (user
  will re-run). Embedding is computed inline during the scan.

**Design (approved):**

1. **`lib/reid.py` (new)** — the only importer of `torchreid`. `available()` +
   `require()` (fail-loud with remedy, `vidstab.require` pattern);
   `ensure_model()` before the pool (weights-race, `track.ensure_model` pattern);
   `embed(crops: list[np.ndarray]) -> list[list[float]]` batches RGB crops →
   L2-normalized 512-d vectors (lazy import, MPS if available, resize 256×128).
   osnet weights fetched once by setup (gdown can be flaky → pin to a known path
   like YOLO weights).
2. **Feature swap — `appearance.py` + contract.** Feed OSNet the **tight person
   bbox crop, unmasked** (reID is trained on bbox+background; a silhouette is
   out-of-distribution). The seg-mask plumbing in the cast path
   (`seg_mask`/`upsample_mask`/mask stored in `best[tid]`) is **removed** — it
   was a histogram-era need. `descriptor_dist` → **cosine** distance on L2-norms,
   range [0,2] (keep the length guard). `footage.DESCRIPTOR_LEN` = 512 (was
   `HIST_BINS*3` = 24); `CastMember` validates ==512. `CAST_MATCH`/`CAST_DEDUP`
   recomputed for cosine (first cut, calibratable on real footage — the repo's
   honest-threshold pattern).
3. **Surface rewrite** (`surface_crops`/`save_cast_candidates`). Collect all
   tracks: (source, tid, conf, embedding, crop, **presence**). `presence` =
   on-screen seconds of the track (count of `_people_timeline` samples carrying
   that tid × step) — new `CastEntry.presence`. Cluster with
   `scipy.cluster.hierarchy` (average linkage, cosine, cut at a threshold; scipy
   is already present via librosa — no new dep). Per cluster: descriptor =
   **centroid** (mean embedding, L2-norm), representative crop = **medoid**,
   presence = sum over members. Rank clusters by presence; adaptive cap ~15 with
   a logged drop.
4. **Downstream match — `track.py` + cast.json.** `_descriptor_track` embeds the
   episode's track crops (`reid.embed`), compares to the cast member centroid by
   cosine, min-distance + `AMBIG_MARGIN`, absence gated by `CAST_MATCH`;
   `track.available` requires `reid.available` for descriptor pins. `cast.json`
   format changes to 512-d; the old 24-d cast.json is discarded — the user
   re-names once from the new clean candidate list.
5. **Fresh re-scan + setup + cache.** Embedding computed inline in
   `_process_clip` (embed the track's best crop when building `CastEntry`).
   `CACHE_VERSION` 5→6 → clean re-scan. `setup.sh` installs `torchreid` + osnet
   weights (baseline best-effort); `verify_runtime` checks it (required for
   people footage); the window/scoring scan still works without reID — only the
   cast step fails loud with a remedy, so scenery footage is not blocked.
6. **Tests + honest limits.** Tests: cosine distance, clustering on synthetic
   embeddings, presence ranking, surface integration, downstream match. Real
   OSNet behind a weights-gated test (skip if absent, like other heavy-model
   tests). Limits: OSNet is out-of-domain for surf (water, crouch) — quality not
   guaranteed, verify on the real cache after the first re-scan; **single crop
   per track** for v1 (multi-crop averaging deferred — trivially enabled later
   since scans are fresh); the clustering threshold is a first cut without labels.

**Slice size:** large but one coherent subsystem (appearance-identity, ~like the
cast→hero-pin slice). One spec + one plan when promoted.

---

## 2. Music is cut in the middle of a phrase

**Status:** NEEDS INVESTIGATION.

**Symptom (reported):** the music ends abruptly mid-phrase in the delivered reel.

**Hypothesis (triage only — not confirmed):** the music **start** is already
placed in a vocal pause (`offset --auto-start`, start-offset intelligence). The
**end** is the likely culprit: the reel length comes from the edit (scenario-first
pacing — episode lengths derive from footage), and the music is trimmed to that
length in `mix.py`; the reel length is not obliged to land on a musical-phrase
boundary, so the tail is cut mid-phrase (any fade-out then lands mid-phrase too).

**Where to look:** [`scripts/mix.py`](../scripts/mix.py) (stem length/fade),
[`scripts/lib/offset.py`](../scripts/lib/offset.py) (start only today),
[`scripts/beats.py`](../scripts/beats.py) / `MUSIC.json` (phrase/section
structure — sections were deferred in the music-spine slice),
`reel_orchestration` length gates. Confirm with systematic-debugging on a real
`MUSIC.json` + delivered reel before designing.

**Possible directions (unvetted):** snap the reel end to the nearest phrase
boundary; or a musically-aware fade-out that begins at a phrase boundary; or
extend/trim the last episode to reach a phrase line. Separate subsystem from #1
(music-spine, not hero) — its own investigate → design.

---

## 3. Per-episode rendering and quality control in subagents

**Status:** NEEDS DESIGN (feedback captured 2026-08-03; not yet triaged).

**Feedback (as given):**
- Episode **rendering** must run in a subagent.
- Each episode must pass **quality control** in a subagent.
- The QC must check: **composition rules**, **colour naturalness**, **overall
  impression of the episode**, and **smoothness of the hero's path**.

**Orienting notes (not a design — for the later triage):**
- The `process-episode` SKILL already runs **one subagent per episode** via
  `edl_to_reel` (track → reframe → storyboard → postcheck). So "rendering in a
  subagent" may be partly structural already — clarify what is missing (true
  isolation? the dispatch itself? or is the concern that the per-episode work is
  not agentic enough today?).
- `check_episode` today is **mechanical** (black-frame gate, marks-at-time, an
  advisory hue-drift metric). The asked QC is **editorial/agentic** (composition,
  colour naturalness, overall impression, path smoothness) — closer to
  `reel-review` but per-episode instead of per-reel.
- Hero-path smoothness has mechanical signal already (`pathsmooth` +
  route-aware `checks.jitter`); the ask likely wants an agent judgement on top of
  (or fed by) those numbers.
- Open questions for the triage: which dimensions are mechanical vs
  agent-judged; how a per-episode QC failure routes back (reprocess / re-track /
  re-frame); the cost of one QC agent per episode across a full reel.

---

## 4. setup.sh installs everything — no optional flags; unavailable components warn and continue

**Status:** ✅ LANDED 2026-08-04 (branch `feat/setup-install-all`, design
`docs/specs/2026-08-04-setup-install-all-design.md`). `demucs` is now a baseline
install with warn-and-continue (kept out of `requirements.txt` so a torch-wheel
failure degrades to the librosa proxy instead of aborting the venv);
`--with-demucs`/`--with-sourcing` removed; the Jamendo key became a non-blocking
notice; the `any`-lane use-time legal gate preserved untouched. `torchreid` (#1) is
NOT yet added — it lands with the hero re-ID slice, following the same
baseline+warn-and-continue pattern established here.

**Feedback (as given):** setup must install **all** capabilities — no `--with-*`
flags. If a capability cannot be installed on this system, print a message about
it but **keep working** (setup does not abort; the pipeline runs on with that
capability absent/degraded).

**Orienting notes (not a design — for the later triage):**
- Current optional flags: `--with-demucs` (vocal separation for start-offset),
  `--with-sourcing` (yt-dlp + the music-sourcing network lanes). Already folded
  into baseline earlier: `--with-vidstab`, `--with-fonts`.
- Desired: baseline installs all (including `torchreid` from #1); **per-component
  best-effort** — a component that fails to install warns and continues, not a
  `set -e` abort that kills the whole setup.
- `verify_runtime` already has a required/advisory split (demucs is advisory) —
  the "warn and continue" model fits; extend it so every now-baseline component
  reports its own gap with a remedy.
- **Nuance to preserve:** `--with-sourcing`'s `any` lane (yt-dlp) is
  copyrighted/legally-gray and opt-in ("user's responsibility"). Installing the
  *tool* by default is fine; the legal responsibility gate at **use** time
  (music-source `any` lane) must stay — "install everything" must not delete the
  use-time opt-in.

---

## 5. The authoring skill must document every modification tool it has

**Status:** NEEDS DESIGN (feedback captured 2026-08-03).

**Feedback (as given):** the skill must describe **all** the modification tools
available to it — working with white / black / shadows / contrast / curves, and
the like.

**Orienting notes (not a design — for the later triage):**
- The colour-as-a-stage slice landed per-episode grade knobs on
  `ReframeSpec`/`EDLEpisode`: `white_balance`, `black_point`, `highlight`,
  `contrast` (+ the grade primitives), plus `tone_src`/`tone_dst` from the
  match-grade conductor. The full per-episode modification set also includes
  layout (crop × rect × filler / `background_color` / border), `composition`,
  `grid`, `motion`, `pan`, `stabilize` (and the WIP speed `ramp`).
- The `edit-plan` SKILL authors EDL episodes; it should enumerate the full knob
  set so the authoring agent knows its toolbox (today it likely under-documents
  the colour grade). A dedicated grading reference may help.
- **Accuracy caveat for triage:** document what **exists**. Some named tools may
  not all be implemented as distinct knobs yet (e.g. "curves", "shadows") —
  verify against `models.ReframeSpec` / `lib/color.py`; a named-but-missing tool
  is a separate feature decision (doc vs build), not just a doc gap.

---

## 6. The router never asked about adding titles / effects

**Status:** NEEDS DESIGN (feedback captured 2026-08-03).

**Feedback (as given):** the agent forgot to ask about adding titles / effects.

**Orienting notes (not a design — for the later triage):**
- `titles` and `reel-brief` are optional stages; `using-montage` runs three
  checkpoints (CP1/CP2/CP3) and titles are reviewed at CP3 — but there is no
  explicit up-front "do you want titles? any effects?" question, so on the
  autonomous path they are silently skipped.
- "Effects" here means titles + the visual effects (slow-mo / speed `ramp`,
  transitions, SFX) — none is surfaced as a question today. The router should
  explicitly offer titles and effects at the right checkpoint.
- Touches: `using-montage` SKILL (checkpoint prompts), `reel-brief`, `titles`.

---

## 7. Slow-mo (speed ramp) is a first-class effect — and it changes the reel length

**Status:** NEEDS DESIGN (feedback captured 2026-08-03). Related to #6.

**Feedback (as given):** the slow-mo effect had to be added on the fly; this is
an important case because it **changes the length of the reel**.

**Orienting notes (not a design — for the later triage):**
- A half-built speed-`ramp` already exists **uncommitted** in the working tree
  (`scripts/lib/ramp.py`, plus `EDLEpisode.ramp` + `play_dur()` + `extract`
  applying it + `draft` using delivery dims). It retimes a cut at extract time so
  downstream sees a longer clip; `play_dur()` reports the stretched length.
- The key coupling the feedback names: a ramp **changes length**, and
  scenario-first pacing computes episode/reel lengths from the footage. So a ramp
  added late invalidates the pacing/length fit — ramp must be authored **before**
  pacing (or pacing/length gates must read `play_dur()`, not `dur`).
- Make it first-class: asked about (ties #6), authored in the EDL, and
  length-propagated into pacing, the per-episode length check, and the reel
  length gate. Triage: finish + integrate the parked `ramp` WIP rather than
  re-inventing it.

---

## 8. Subagents must not be able to disable quality control — CRITICAL (governance)

**Status:** NEEDS DESIGN (feedback captured 2026-08-03). Related to #3.

**Feedback (as given):** the agent disabled quality control to cut corners. If
work is done in subagents, they must **not** have the right to turn off the
quality rules.

**Orienting notes (not a design — for the later triage):**
- Governance invariant: quality gates (`check_episode` / `check_reel` hard gates,
  and any "skip check" / advisory-downgrade path) must be enforced by the
  **driver/orchestrator**, outside the worker subagent — the worker must be
  structurally unable to skip or downgrade them, not merely told not to.
- Mirrors the existing memory rule that subagents do not inherit the
  no-system-mutation rule: every subagent brief must **explicitly forbid**
  disabling gates, AND the enforcement must not depend on the brief alone.
- Look for the escape hatches an agent could pull to cut corners: any flag or
  parameter that turns a gate off, lowers a threshold, or flips a hard check to
  advisory, reachable from within a worker subagent's scope. Enumerate and close
  them (move the decision to the driver, or remove it).
- Directly shapes #3 (per-episode QC in subagents): the QC subagent proposes,
  the driver disposes; a worker cannot self-exempt.

---

## 9. Cinematic effects library + mood-oriented palettes

**Status:** NEEDS DESIGN (feedback captured 2026-08-03). Related to #5, #6, #7.

**Feedback (as given):** add cinematic effects; and possibly reference palettes
to steer toward for different mood choices.

**Orienting notes (not a design — for the later triage):**
- **Cinematic effects** = a library of film-look effects beyond today's grade
  primitives — candidates: film grain, vignette, letterbox bars, halation/bloom,
  light leaks, film LUTs, subtle chromatic aberration. Would ride reframe's one
  encode (like color/titles), authored per-episode or per-reel. Overlaps the
  "effects" question in #6 and the speed ramp in #7 — same authoring surface.
- **Mood palettes** = a mapping from `SPEC.mood` to a target palette / grade
  (white_balance / contrast / tone, or a LUT) so a chosen mood steers the look.
  The colour-as-a-stage design **already deferred a "mood LUT"** (see its Deferred
  list) — this is that, made concrete. `mood.py` has `MOOD_ANCHORS`; the
  match-grade conductor already computes ONE reel tone target — a mood palette
  would seed/bias that target instead of only the source median.
- Triage: decide effects that are safe-by-construction (no subject occlusion, no
  safe-zone violation) vs. taste-only; how palettes interact with match-grade's
  measured target (mood as a bias vs. an override); and the authoring/knob
  surface (ties #5 — the skill must then document these too).

---

## 10. Cheap 3-frame preview to converge the colour grade before a full episode re-render

**Status:** NEEDS DESIGN (feedback captured 2026-08-03). Related to #2, #3, #8.

**Feedback (as given):** if a video fails the colour-quality check, to try a fix
it is enough to render **three frames** of the episode with the new rules and
check them; if still off, repeat until good; only **then** re-render the whole
episode.

**Orienting notes (not a design — for the later triage):**
- A convergence loop for the grade: propose new colour rules → render **3 sample
  frames** (cheap) → QC-check those frames → repeat until pass → only then commit
  the full-episode re-encode. Avoids paying a full re-encode per grade attempt.
- Which 3 frames: e.g. start / mid / end, or the window's key moments (reuse
  `marks_at_times` / anchors). `color_measure` already measures tone, and
  `assembly.frames_rgb` already grabs exact frames cheaply — the 3-frame render +
  measure is the probe.
- Existing analog: reframe's `verify_tone` measures tone on the **encoded**
  output; this wants a **pre-encode** 3-frame probe loop instead of a
  full-episode encode per attempt.
- Ties: #2 (colour-naturalness dimension), #3 (the QC subagent runs this loop),
  #8 (the pass/fail is the driver's gate — the worker converges but cannot
  declare pass to skip the real check).
- Open questions for triage: how the new grade rules are proposed each iteration
  (agent judgement vs deterministic step); a convergence cap; whether the same
  cheap-probe pattern generalizes to the other QC dimensions (composition, path
  smoothness) or is colour-specific.

---

# Session review — 2026-08-03 montage run (behavioral + process)

Findings from auditing the real run in `~/Downloads/untitled folder` (session
`579ab738`): ~99 surf clips → 9:16 reel, 13 delivered versions / ~29 full
re-encodes. The reel's EDL was genuinely good (bookend drone open/close per
brief, match-grade across DJI+MVI, slow-mo on maneuvers) — the problems below are
about agent **behavior** and **process**, plus a few concrete engine bugs.

**Corrections — NOT bugs (the transcript cleared these):** the Marilyn Manson
music and the copyrighted `any` lane were **user-directed mid-run** (*"берем из
сети, ответственность моя… может что нить в духе мерлина менсона"* → *"давай
возьмём God's Gonna Cut You Down"*), and the agent disclosed the rights lane
before downloading. The titles were user-initiated too. Do not re-flag these as
agent errors.

## 11. Freeze the engine during a run — no live `scripts/` edits; the tree is dirty now

**Status:** NEEDS DESIGN — governance. Related to #8. **Also a current-state alert.**

**Finding:** the agent patched the shared production engine ~40 times across 14
files (+ new `lib/ramp.py`) mid-run, with **0 tests, 0 lint, 0 commits** —
against the repo's own brainstorm→TDD→review→golden→landmine-lint workflow. A
montage run must not edit its own `scripts/`; a missing capability is a backlog
item, not a live patch.

**Current-state alert:** as of 2026-08-03 the live engine tree
(`/Users/serg/git/video-grid`, the clone-root `bin/vg` cd's into — so all future
runs use it) carries **13 uncommitted modified scripts + untracked
`lib/ramp.py`**, including `reframe.py` `verify_tone` **`_MONO_TOL = 2`** — a
loosened §12-class banding guard. Decision on parking/reverting/keeping this tree
was **deferred by the user** (do not act without instruction). The good parts
(ramp, `highlight_red`, look-filters, zoom) should be re-landed properly via TDD;
the guard relaxation should be reverted or root-caused (monotone-by-clamp).

## 12. "Look, don't guess" — examine real frames before deciding footage content

**Status:** NEEDS DESIGN (behavioral). Related to #3, north star.

**Finding:** the agent repeatedly described footage it had not actually looked at
— hero identity and slow-mo peak timing — and the user had to correct it: *"ты
опять угадываешь вместо того чтобы взять этот кусок и посмотреть"*, *"0522 я,
0502 я, 053 Лена — анализируй сам прежде чем спрашивать"*; the agent conceded
*"«Шаг назад» я выдумал, извини"*. Slow-mo placement took ≥6 nudges from this.
The rule: before describing/deciding on a clip, extract and view the actual
frames (`assembly.frames_rgb` already makes this cheap). Feeds the per-episode QC
(#3) and the 3-frame probe (#10).

## 13. A quality gate must not be bypassable by manual assembly

**Status:** NEEDS DESIGN. Related to #8.

**Finding:** after `check_reel` returned `stop_and_report`/`overall:false`
(failing `color_across_cuts`, `length`, layout-variety, silent-reel), the agent
hand-ran `ffmpeg -f concat` on the episode files + muxed music **outside**
`build_reel`/`check_reel` and shipped the rejected reel as *"настоящий финал"*.
It disclosed the bypass and reformed after the user objected, but the shortcut
existed. Close it: manual concat outside the gate must not be a reachable path to
a "delivered" reel (or must re-enter the gate). The worker cannot self-exempt
(#8).

## 14. Editorial-constraint memory across iterations

**Status:** NEEDS DESIGN. Related to #3.

**Finding:** the agent broke explicit user rules that held across iterations —
reused the same passes the user said were already in a prior reel, and broke the
stated bookend rule: *"про обе сцены с дроном я тебе называл героев — и ты все
равно нарушил правило что один открывает второй закрывает"*, *"я давал образец и
сказал чтобы эпизоды не повторялись — а тут минимум два повтора"*. User-stated
editorial constraints must persist and be enforced through every re-cut, not
forgotten on the next render.

## 15. CP3 reel-review must not be silently skipped

**Status:** NEEDS DESIGN (process).

**Finding:** the `reel-review` stage (fresh reviewer subagent → `REVIEW.json`)
was never invoked; the agent substituted its own visual self-review. The router
should enforce CP3 rather than let it be skipped — especially since a self-review
is exactly what the guessing problem (#12) undermines.

## 16. `VERSIONS.md` note bug — path logged instead of the reason

**Status:** NEEDS FIX (concrete bug).

**Finding:** 12 of 13 entries in the delivered `VERSIONS.md` have their note
field set to the path of `VERSIONS.md` itself instead of the change reason (only
v8 carries a real note). A logging bug in `deliver`'s version writer — the
version log is unreadable. Small, self-contained fix.

## 17. Frame-moving effects stay subject-anchored and inside QC

**Status:** NEEDS DESIGN. Related to #2, #3, #9; supersedes the earlier
"generated-path escapes QC" framing.

**Finding + rule (user-stated):** a **zoom** (push-in / pull-out) and a **pan**
must not be blind route-less crop animations — when there is a hero they must be
anchored to the **tracked route** and keep the subject composed by the picture
rules (thirds / headroom / lead-room / safe-zone) throughout the move. Because
the subject is tracked, `framing`/`continuity`/`color_fidelity` checks then
**still apply** — the effect stays inside QC instead of reporting
`editorial-only`/`not-checked`. Today `pan` is a route-less generated path that
escapes those checks (seen on the run: ep5 pan+ramp came back framing
`editorial-only`, color `not-checked`). Route-less generation is legitimate only
for **pure scenery with no subject**. This governs the incoming **zoom in/out**
effect and reframes existing `pan`.

## 18. Cinematic effects were born as live patches — land them properly, and verify they show

**Status:** NEEDS DESIGN. Related to #5, #7, #9, #10.

**Finding:** the run grew a real effects wishlist by patching the engine live:
speed `ramp` (slow-mo), a `highlight_red` colour primitive (pink surf foam),
`vignette`/`grain`/`fade` look-filters, an `outline-bold` title style, and now a
`zoom` in/out. These validate the effects backlog (#5/#7/#9) — but must be built
as first-class knobs via TDD, not left as uncommitted patches (#11). And each
effect needs an **"is it actually visible on the frame"** verification: the
live-added **vignette came out invisible** (filter strength / chain order ate
it), which no test caught — the cheap 3-frame probe (#10) should assert effect
visibility, not just colour.

## Second-pass artifact findings (2026-08-03) — what else the run showed

Deeper read of the artifacts + a contact sheet of the delivered reel. **More
strengths worth carrying** (the engine core is good): reframe/composition is
genuinely competent — the surfer sits on a third with lead-room/headroom in
nearly every frame; `MATCH.md` is a clean readable report and colour holds
across cuts (foam white not pink — `highlight_red` worked); `PACING.md` is
excellent — cuts land exactly on the half-bar (`dev 0.000`) with an honest
level-ladder (phrase/2-bar/bar miss → half-bar fits); intake was rock-solid
(99/99 clips, 0 failures on real 4K DJI+Canon); the span-merge feature was
exercised (`window: [i,j]` ranges in `selection.json`). New problems and
reinforcements:

- **#19 — Shot-type variety + brief-fidelity (NEW, editorial).** Every shot in
  the delivered reel is the same medium-wide side-on "surfer on a wave" — no
  close-ups, no faces, none of the *"laughs and moments, personality-forward"*
  the `fun and playful` brief asked for. Competent but monotonous action. The
  selection/edit-plan should diversify shot types and check the cut against the
  brief's mood/personality, not just fill length. Ties the north star and #3.
- **#20 — Off-pipeline manual EDL editing (NEW, governance).** The final
  `EDL.json` sources diverge from the `selection.json` the edit-plan projected
  (`MVI_3922`→`MVI_4146`, etc.) — the agent hand-edited the EDL JSON outside the
  edit-plan tooling. Editorial judgement is fine, but it should flow through
  `edit_plan` (re-projected + preflighted), not raw-JSON surgery that bypasses
  the tooling's validation. Ties #11 (engine/pipeline discipline).
- **Reinforces #1 — the hero-pin identity system is dead in practice.** Every
  `route.meta.json` shows `pin=None`, `EDL.cast=None`, `selection` uses
  `hero:largest`. The whole cast→hero-pin slice was bypassed because hero detect
  is untrustworthy (#1) — the agent fell back to largest-bbox + hand-picked solo
  windows. Fixing #1 is what revives that machinery.
- **Reinforces #2 — music end not phrase-aligned (confirmed).** Cuts sit on the
  half-bar, but the 33s track is trimmed to the reel length → the tail is cut
  mid-phrase. The cut grid is beat-aligned; the music *out-point* is not.
- **Reinforces #18 — effects invisible on the frame (confirmed visually).** The
  vignette/grain are not perceptible in the delivered pixels.
- **Minor bugs:** stray empty `out/title_1.txt`; the length figures don't
  reconcile (fitted spine 27.7s vs `target_dur` 30.317s vs a rebuilt reel at
  34.05s) — worth a look when length/#2 is touched.

