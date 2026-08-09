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

**Status:** ✅ LANDED 2026-08-04 — plan `docs/plans/2026-08-04-hero-reid.md` +
design `docs/specs/2026-08-04-hero-reid-design.md`. The colour-histogram
descriptor is replaced end-to-end with a 512-d OSNet person-re-ID embedding
(cosine) behind the new `lib/reid.py` boundary; cast surfacing is now
presence-ranked agglomerative clustering. `torchreid` installs at the setup
baseline (warn-and-continue), closing the note in #4 below. Thresholds
(`CAST_MATCH`/`CLUSTER_COS`/`MAX_CAST`) are first-cut — calibrate on the next
real cache (§5/§9 of the design).

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

**Status:** ✅ LANDED 2026-08-08 — plan `docs/plans/2026-08-08-episode-qc.md` +
design `docs/specs/2026-08-08-episode-qc-design.md`. Per-episode **quality
control** now sits between the per-episode render and reel assembly:
`edl_to_reel` splits into `--stop-after-episodes` (render every episode,
write `EPISODES.json`, stop) and `--from-episodes` (gate on an
`EPISODE_QC.json` found beside it, by convention, then assemble). One fresh
judge subagent per episode (cap 3, the new `episode-qc` SKILL) reads a frame
strip off the DELIVERED clip, the storyboard, the mechanical `report.json`,
and a new colour-naturalness sensor (`lib/naturalness.py` — blown
highlights, crushed blacks, colour cast, oversaturation, flatness), then
writes findings against five axes: composition, colour, impression, path,
and **hero** (is the followed subject the intended one). `episode_qc build`
validates the findings into a typed `ReelQC` and stamps `clip_digest`
itself, from the file on disk — never from the judge's claim — so a
re-rendered episode invalidates its own verdict. The pure gate refuses
incomplete, then stale, then blocking, in that order, before a single
ffmpeg call runs, and carries no waiver field anywhere on this path
(governance #8). **The half that did NOT land: episode RENDERING still
runs as a Python `ThreadPoolExecutor` fan-out, not a subagent** — design §2
considered and rejected replacing the pool with an agentic fan-out, because
the router would then own the middle of the driver and the reproducible
one-command SP1 run (a hand-authored `EDL.json` straight to a delivered
reel) would stop existing. The feedback below asked for rendering in a
subagent; that half was answered with a reasoned no, not a silent drop. See
the Done entry in `build-status.md` for the full mechanism, the design §8
hole (`build_reel`'s retry loop still reprocesses a culprit episode AFTER
its verdict, so a re-rendered episode ships judged one render out of date —
named on the delivery's attestation, not prevented), and the design §12
honest limits (the gate proves the artifact's presence and its digest
binding, never that anyone actually looked).

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
notice; the `any`-lane use-time legal gate preserved untouched. `torchreid` (#1)
landed 2026-08-04 with the hero re-ID slice, following the same
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

**Status:** ✅ LANDED 2026-08-04 — design
`docs/specs/2026-08-04-attested-run-design.md` §9 + plan
`docs/plans/2026-08-04-attested-run.md`. `using-montage`'s CP2 step (after
`EDL.md` is shown) now asks explicitly *"titles? effects (slow-mo / speed
ramp, transitions, SFX)?"* and names what is skipped when the answer is no —
CP2 is the right place because by then the EDL exists, so the reel length is
known and a title can actually be timed.

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

**Status:** ✅ LANDED 2026-08-04 — design
`docs/specs/2026-08-04-attested-run-design.md` + plan
`docs/plans/2026-08-04-attested-run.md`. The escape hatches this item asked to
enumerate and close are closed **structurally**, not by convention: `deliver`
refuses a `ReelReport` whose `master_digest` is empty (it did not come from
`check_reel`) or does not match the master being shipped (a hand-run `ffmpeg
-f concat`, or a master re-made after the check). That closes the careless
bypass, not every bypass: a report hand-written WITH a correct `shasum -a 256`
of a hand-assembled master still reaches `deliver` and ships — a digest is
computable by anyone, and signing was considered and rejected as pointless
against a local agent that already holds the key (design §11 names this
explicitly). What that bypass cannot forge is the rest of the record —
`deliver.py`'s CLI passes no `run_provenance`, so the resulting
`REEL_v{n}.attest.json` carries `engine_at_start: {}`, `edl: {}`,
`overrides: []` next to a driver run's populated fields, which is the tell at
CP3, not a blocked delivery. `EDL.from_json` refuses a tampered EDL, and every
legitimate gate loosening still available (`--color-delta-max`) is recorded —
never silently — in the delivery's `REEL_v{n}.attest.json` via
`provenance.spec_overrides`, a diff against the default spec so a future
threshold is covered the day it is added. `using-montage`, `process-episode`,
and `edit-plan` each gained an explicit brief line: a worker may not disable,
lower, or downgrade any quality gate; a gate that blocks routes back to its
stage, never loosened to pass. The honest remainder (design §11): an agent
with a shell can still bypass all of it by hand — the invariant this slice
achieves is *no silent bypass*, not *no bypass whatsoever*; every bypass now
leaves a machine-detectable trace (an unattested delivery, an impoverished
attestation, a refused tamper). Related #3 (per-episode QC in subagents)
stays open — this slice makes the gates that exist un-skippable, it does not
add new QC.

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

**Status:** ✅ LANDED 2026-08-04 (the engine-freeze mechanism) — design
`docs/specs/2026-08-04-attested-run-design.md` §7/§9 + plan
`docs/plans/2026-08-04-attested-run.md`. `edl_to_reel` now compares
`engine_stamp()` against the sha/dirty bit `project.json` recorded at run
start and raises `ValueError` naming both revisions the moment they disagree —
a run can no longer straddle a live `scripts/`/`skills`/`bin` edit the way the
2026-08-03 run did. An unknown stamp (git absent, or a run started before this
slice existed) proves nothing and never stops a run, and a *static* dirty tree
at run start is not itself a stop — only a recorded fact, echoed at CP1 and
carried into every attestation — because the user's own dev tree must keep
working.

**Finding:** the agent patched the shared production engine ~40 times across 14
files (+ new `lib/ramp.py`) mid-run, with **0 tests, 0 lint, 0 commits** —
against the repo's own brainstorm→TDD→review→golden→landmine-lint workflow. A
montage run must not edit its own `scripts/`; a missing capability is a backlog
item, not a live patch.

**Current-state alert — retired 2026-08-04:** the live engine tree is clean
now (verified: no uncommitted changes, no `_MONO_TOL` banding-guard relaxation
anywhere in `scripts/`). Of the two branches that carried the 2026-08-03
live-patch set, only **one** is resolved: `wip/montage-run-hardening`
(`4841dd3`) was fully ported across three separate slices (track-stitch
2026-07-28, path-quality 2026-07-28, titles-animations 2026-07-29) and has
been deleted. **`wip/montage-run-patches` (`fbcd052`) is NOT deleted and must
not be** — it remains parked as the only copy of the unlanded speed-ramp work
(`scripts/lib/ramp.py`, 212 lines), which does not exist on `main`; backlog #7
and #18 still track that work as open, not landed by this slice. See the
design's corrected §9 for both SHAs and the branch state.

## 12. "Look, don't guess" — examine real frames before deciding footage content

**Status:** ✅ LANDED — both halves. **Selection half 2026-08-05** (design
`docs/specs/2026-08-05-footage-contact-sheet-design.md` + plan
`docs/plans/2026-08-05-footage-contact-sheet.md`): `contact_sheet build` is now
a **required** stage between footage-intake and edit-plan: a run cannot reach
the cut without a `SHEETS.md` on disk, covering every window of every clip
that decoded — a clip that fails outright is named under **Not sheeted**
instead, its windows shown nowhere (design §7), and a build where every
candidate window failed to decode raises rather than writing a `SHEETS.md`
that looks like a normal, if thin, success. `contact_sheet strip` answers the
timing/identity questions a single frame cannot. The edit-plan skill reads
both. **Per-episode half 2026-08-08** (design
`docs/specs/2026-08-08-episode-qc-design.md` + plan
`docs/plans/2026-08-08-episode-qc.md`): #3's judge subagent reads a frame strip
off the *delivered* clip and writes findings against five axes — the half that
judges rendered frames rather than merely producing them. #19 (shot variety,
2026-08-06) and #14 (editorial-rule memory, 2026-08-07) landed alongside.

**What neither half does** (contact-sheet design §9; episode-QC design §12) —
an architectural limit, not a pending work item: both gate the PRESENCE of an
artifact, never proof that anyone looked. No mechanism can prove an agent
examined an image it was handed. The episode-QC gate narrows this as far as the
shape allows — it stamps `clip_digest` from disk rather than from the judge's
claim, so a verdict is at least bound to the bytes it names — but a judge that
writes a plausible finding without opening the strip passes both gates. The
nearest remaining mechanical strengthening is #10's 3-frame probe asserting
**effect visibility** in pixels (which #18 asks for), not another presence gate.

**Finding:** the agent repeatedly described footage it had not actually looked at
— hero identity and slow-mo peak timing — and the user had to correct it: *"ты
опять угадываешь вместо того чтобы взять этот кусок и посмотреть"*, *"0522 я,
0502 я, 053 Лена — анализируй сам прежде чем спрашивать"*; the agent conceded
*"«Шаг назад» я выдумал, извини"*. Slow-mo placement took ≥6 nudges from this.
The rule: before describing/deciding on a clip, extract and view the actual
frames (`assembly.frames_rgb` already makes this cheap). Feeds the per-episode QC
(#3) and the 3-frame probe (#10).

## 13. A quality gate must not be bypassable by manual assembly

**Status:** ✅ LANDED 2026-08-04 — design
`docs/specs/2026-08-04-attested-run-design.md` §5.2 + plan
`docs/plans/2026-08-04-attested-run.md`. `deliver` now refuses a `ReelReport`
whose `master_digest` is empty (the report did not come from `check_reel`,
its only producer, which always stamps one) or does not match the sha256 of
the master file being encoded (a hand-assembled or re-made master) — both
raise `RuntimeError` naming the fix. Proved against real pixels
(`tests/integration/test_attested_run.py::test_a_hand_assembled_master_cannot_be_delivered`):
re-assembling a different master after `check_reel` ran is refused at
`deliver`. Honest limit (design §11): a reel shipped entirely outside
`deliver` (no digest check ever runs) is still possible — it produces no
`REEL_v{n}.attest.json`, so `montage status`/`verify` report it `unattested`
and CP3 surfaces that plainly. Detectable, not preventable — the worker
cannot self-exempt (#8) without leaving a trace.

**Finding:** after `check_reel` returned `stop_and_report`/`overall:false`
(failing `color_across_cuts`, `length`, layout-variety, silent-reel), the agent
hand-ran `ffmpeg -f concat` on the episode files + muxed music **outside**
`build_reel`/`check_reel` and shipped the rejected reel as *"настоящий финал"*.
It disclosed the bypass and reformed after the user objected, but the shortcut
existed. Close it: manual concat outside the gate must not be a reachable path to
a "delivered" reel (or must re-enter the gate). The worker cannot self-exempt
(#8).

## 14. Editorial-constraint memory across iterations

**Status:** ✅ LANDED 2026-08-07 — design
`docs/specs/2026-08-07-editorial-constraints-design.md` + plan
`docs/plans/2026-08-07-editorial-constraints.md`. A user-stated rule now has a
home, `CONSTRAINTS.json` beside `project.json`, discovered by convention (no
flag) and enforced by `edit_plan build` on every re-cut without being told
again. **What is enforced:** exactly four kinds — `no_repeat` (no two episodes
share one shot, the scene-cut segment `FootageClip.shot_at` resolves — so two
windows of one drone pass repeat even when their spans do not overlap, the
case this finding's second quote describes), `open_with`/`close_with` (the
first/last episode must pin that cast name, closing this finding's first
quote), `exclude` (bans a shot or a whole clip). A broken rule stops
`write_edit_plan` before the variety gate with `reason:
"constraint-violation"` and writes nothing; there is no waiver. **What is
NOT enforced:** anything outside those four shapes — a rule like "don't put
two drone shots back to back" cannot be written down at all, so it stays in
chat and is forgotten exactly as before this fix; `edl_to_reel`'s
hand-authored `EDL.json` front door (the SP1 door by design) never passes
through this gate; and `no_repeat` catches one shot used twice, never two
different shots that merely look alike (visual similarity is a separate,
deferred sensor). #3 (per-episode QC) stays open and separate.

**Finding:** the agent broke explicit user rules that held across iterations —
reused the same passes the user said were already in a prior reel, and broke the
stated bookend rule: *"про обе сцены с дроном я тебе называл героев — и ты все
равно нарушил правило что один открывает второй закрывает"*, *"я давал образец и
сказал чтобы эпизоды не повторялись — а тут минимум два повтора"*. User-stated
editorial constraints must persist and be enforced through every re-cut, not
forgotten on the next render.

## 15. CP3 reel-review must not be silently skipped

**Status:** ✅ LANDED 2026-08-04 — design
`docs/specs/2026-08-04-attested-run-design.md` §8 + plan
`docs/plans/2026-08-04-attested-run.md`. `montage.py`'s `reel-review` stage
flips from `kind="optional"` to `"required"` — a gate that costs nothing to
skip is not a gate. `next_action()`'s `next` now points at `reel-review` once
`deliver` is done, and a run is finished when `next` is `None`, not merely
when `delivered` is `true`; `using-montage`'s CP3 step reflects the same
condition.

**Finding:** the `reel-review` stage (fresh reviewer subagent → `REVIEW.json`)
was never invoked; the agent substituted its own visual self-review. The router
should enforce CP3 rather than let it be skipped — especially since a self-review
is exactly what the guessing problem (#12) undermines.

## 16. `VERSIONS.md` note bug — path logged instead of the reason

**Status:** ✅ LANDED 2026-08-04 — design
`docs/specs/2026-08-04-attested-run-design.md` §9 + plan
`docs/plans/2026-08-04-attested-run.md`. Root cause confirmed: `edl_to_reel`
was passing `str(Path(out_dir) / "VERSIONS.md")` — the log's own path — as
`deliver`'s `changelog` argument. `edl_to_reel` now takes a `--changelog`
CLI passthrough naming the real reason for the version, defaulting to a
meaningful `"delivered from {EDL filename}"` when none is given; a regression
test asserts the written note is never a path to `VERSIONS.md`.

**Finding:** 12 of 13 entries in the delivered `VERSIONS.md` have their note
field set to the path of `VERSIONS.md` itself instead of the change reason (only
v8 carries a real note). A logging bug in `deliver`'s version writer — the
version log is unreadable. Small, self-contained fix.

## 17. Frame-moving effects stay subject-anchored and inside QC

**Status:** ✅ LANDED 2026-08-08 — design
`docs/specs/2026-08-08-subject-anchored-moves-design.md` + plan
`docs/plans/2026-08-08-subject-anchored-moves.md`. A `zoom` push-in/pull-out
now rides the tracked route through the SAME composition rule that places any
crop — every route sample's rect comes from `geometry.crop_x`, only the width
shrinks or grows — so `framing`/`continuity`/`color_fidelity` all apply to it
exactly as to any tracked episode; the crop is cut by inserting a `zoompan`
between the existing `crop` and `scale`, and `PathMeta` records the per-sample
rect it actually cut (`crop_ws`/`crop_hs`/`crop_ys`). `pan` no longer escapes
QC on the author's word: `edit_plan.window_to_episode` refuses one over any
window intake MEASURED as holding people (`FootageWindow.present >
PAN_PRESENCE_MAX = 0.10`), and the hand-authored `edl_to_reel` door — which
never sees that measurement — refuses the weaker self-contradiction instead
(a `pan` beside a hero pin or cast name). Route-less generation stays
legitimate for pure scenery, now MEASURED rather than merely asserted. See the
Done entry in `build-status.md` for the measured numbers (the push-in proof's
24px→39px magnification), the two landmine-lint defects this slice found in
its own safety net, and the design §10 honest limits (an uncalibrated
`PAN_PRESENCE_MAX`/`ZOOM_MAX_RATE`/`ZOOM_MAX_UPSCALE`, a ≤1px
record-vs-render residual, presence as a people-only proxy, the gate proves
the premise never the taste).

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

**Status:** ◐ PARTIALLY LANDED 2026-08-08 (the frame-moving half only) —
the `zoom` in/out this finding names is now a first-class, TDD'd knob
(backlog #17 above, design
`docs/specs/2026-08-08-subject-anchored-moves-design.md` + plan
`docs/plans/2026-08-08-subject-anchored-moves.md`), subject-anchored and
inside every check, with its own visibility proof (design §9: a real-ffmpeg
measurement of the subject's on-screen width actually growing, not an
assumption that a correct-looking argv rendered correct pixels — exactly the
"is it actually visible on the frame" check this finding asks every effect to
carry). **Still open, unchanged by this slice:** the speed `ramp` (#7,
first-class + length-aware — the parked `wip/montage-run-patches` branch
remains its only surviving copy), the look filters
(`vignette`/`grain`/`fade`/LUTs, #9), the `highlight_red` colour primitive
(landed quietly inside colour-as-a-stage but never given its own visibility
proof), and the `outline-bold` title style — none of these has the TDD +
visibility-proof treatment this finding asks for yet.

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

- **#19 — Shot-type variety + brief-fidelity (NEW, editorial). ✅ LANDED
  2026-08-06** — design `docs/specs/2026-08-06-mood-preset-variety-design.md`
  + plan `docs/plans/2026-08-06-mood-preset-variety.md`. `edit_plan build` now
  refuses a cut that takes *zero* of a shot size the mood's preset wants when
  the footage offers three or more windows of it (reason `variety-gap`,
  overridable only by a written `variety_waiver` in `selection.json`) — shot
  size is judged in the cut's **delivered** frame (a 9:16 crop of a 16:9
  source widens the discriminating net 3.16×), not the source-geometry tag
  that could not discriminate on footage like this at all (the original
  finding below). Four new `mood.py` anchors (`fun`/`playful`/`nostalgic`/
  `adventure`) close the matching half of "brief-fidelity" too —
  `"fun and playful"` matched no anchor before this slice and fell into the
  blind drive-ranking fallback, so even the music ranking had been running
  blind. **What this does NOT cover** (design §13): the gate proves *"you
  used what was there,"* never *"the reel is varied"* — two close-ups of the
  same person in the same pose satisfy it completely (§13.1), and footage
  whose subject never exceeds ~2.5% of the source frame is legitimately
  all-`wide` and the gate cannot fire at all (§13.2); a hand-authored
  `EDL.json` driven straight through `edl_to_reel`'s SP1 front door is never
  evaluated (§13.5); and the waiver is self-granted — the agent that cut it
  monotonous is the agent that can write the reason away, so what the gate
  buys is a recorded, surfaced decision, not an independent check (§13.6).
  The preset numbers themselves (§13.7) are first-cut guesses, uncalibrated
  against real footage. Original finding, for the record: every shot in the
  delivered reel was the same medium-wide side-on "surfer on a wave" — no
  close-ups, no faces, none of the *"laughs and moments, personality-forward"*
  the `fun and playful` brief asked for. Competent but monotonous action. The
  selection/edit-plan should diversify shot types and check the cut against the
  brief's mood/personality, not just fill length. Ties the north star and #3.
- **#20 — Off-pipeline manual EDL editing (NEW, governance). ✅ LANDED
  2026-08-04** — design `docs/specs/2026-08-04-attested-run-design.md` §5.1 +
  plan `docs/plans/2026-08-04-attested-run.md`. `EDL.json` is now stamped by
  the one writer chokepoint `edl.write_edl` (both `edit_plan` and
  `match_grade` route through it), and `EDL.from_json` raises `ValueError` on
  a tampered file — a digest that no longer matches its contents — naming the
  remedy (edit `selection.json`, re-run `edit_plan build`). The absence rule
  is deliberate: a hand-authored EDL with no provenance block at all still
  loads, since that is `edl_to_reel`'s documented SP1 front door; what is
  refused is editing the TOOL's output while presenting it as the tool's
  output, which is exactly what this finding describes. The original finding,
  for the record: the final `EDL.json` sources diverged from the
  `selection.json` the edit-plan projected (`MVI_3922`→`MVI_4146`, etc.) — the
  agent had hand-edited the EDL JSON outside the edit-plan tooling. Ties #11
  (engine/pipeline discipline).
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

