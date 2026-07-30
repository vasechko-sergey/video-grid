# Match-grade conductor (slice 4) — design

> Status: approved 2026-07-30 (brainstorm), pre-implementation.

The last deferred item from the colour-as-a-stage design
([2026-07-26-colour-stage-design.md](2026-07-26-colour-stage-design.md), its
"Deferred" list): montage design §10's *"final match-grade pass for consistency
across episodes."* Colour-as-a-stage landed the per-episode **actuator** (the
`tone_arg` curve that carries one source's profile onto a common one, plus the
`measure_profile` authoring aid). This slice lands the **conductor** on top of
that foundation: the stage that measures every episode, computes **one** common
reel target, and auto-authors the `tone_src`/`tone_dst` pairs the actuator
consumes — so a reel cut from mixed cameras and light reads as one grade.

It is the twin of the mood LUT, which stays deferred: the conductor is about
**consistency** (pull the episodes to each other), never about imposing an
external look.

## 0. What exists, and what this changes

Already built (colour-as-a-stage, slice F):

- `color.tone_arg(src, dst)` — the actuator. A `curves` fragment that maps one
  source's `(p5, p50, p95)` luma profile onto a common target. Refuses anchors
  not strictly increasing by `color.TONE_MIN_GAP` (6) units, or outside 0-255.
- `color.percentiles(hist256)` — pure `(p5, p50, p95)` from a luma histogram.
- `color_measure.measure_profile(clip, at)` — the driver: decodes one 160-wide
  grey still at time `at` (default 1s), histograms it, calls `color.percentiles`.
  Its docstring already names the conductor as its future reuse.
- `EDLEpisode.tone_src` / `.tone_dst` (and the `ReframeSpec` twins reached via
  the manifest bridge). Today these are authored **ad hoc** by a human pasting
  `measure_profile` output — nothing computes them across a reel.

This slice adds the stage that **computes and authors** those pairs across all
episodes. It touches **only** the tone pair; every other grade knob
(`white_balance`, `black_point`, `saturation`, …) stays hand/agent-authored.

## Scope decisions (locked in brainstorming)

- **Common target = the per-anchor median** of every episode's measured profile
  (chosen over a reference-episode or a SPEC.mood target). Median so one
  blown-out or crushed episode cannot drag the reel's target off the group it
  should represent; no privileged-episode selection rule to get wrong. A
  reference-episode target and a mood target are future refinements (§8).
- **Approach A — a standalone post-EDL stage.** `match_grade.py` reads
  `EDL.json`, measures each source, authors tone pairs back into `EDL.json`, and
  writes a `MATCH.md` report. It runs **after** edit-plan (and after pacing, §7),
  **before** `edl_to_reel`. Rejected: measuring inside `edl_to_reel` after
  extract (couples conductor to driver, hides the grade from the EDL a human
  reviews) and measuring the shipped crop inside `build_reel` (needs a
  measure-then-regrade loop = a second encode, breaks "one encode"). The EDL
  stays the single source of truth; the authored tone is visible and tweakable
  before any pixel is rendered.
- **Opt-in.** The conductor **changes the look** (it pulls episodes together), so
  it is never on the autonomous path — like `white_balance`, `dip`, and the SFX
  whoosh, it is an optional stage a human chooses. A reel that deliberately mixes
  looks simply does not run it.
- **Pure core / thin driver**, the `color.percentiles` / `pacing` / `offset`
  pattern: `lib/matchgrade.py` decides (no ffmpeg, no numpy); `match_grade.py`
  measures (reuses `measure_profile`) and does the EDL IO.
- **Identity-off is preserved.** An episode already within `MATCH_EPS` of the
  target gets **no** tone pair — the reframe fast path stays byte-identical for
  it. Only deviating episodes are pulled in.

## 1. Data flow

```
   EDL.json  (edit-plan, then pacing — the settled cut)
        │
        ▼
   match_grade.conduct(edl, footage_root, eps, force)
        │  measure_profile(source, at = start + dur/2)  ← whole frame, per episode
        │           │ (p5, p50, p95) per episode
        │           ▼
        │  matchgrade.common_target(profiles)  → median + gap-repair → TARGET
        │  matchgrade.plan(profiles, has_tone, TARGET, eps, force) → [ToneDecision]
        ▼
   EDL.json  (enriched: tone_src = own profile, tone_dst = TARGET, on deviating eps)
   MATCH.md  (per-episode: measured profile · target · delta · action/reason)
        │
        ▼
   edl_to_reel → to_manifest_dict copies tone_src/dst → ReframeSpec → reframe grade
                 (one encode, as before — the conductor added no pass)
```

## 2. The pure core — `scripts/lib/matchgrade.py`

No ffmpeg, no numpy — the driver measures; this only decides. `statistics.median`
is stdlib.

```python
"""The match-grade conductor's pure core (design 2026-07-30, montage §10). Given
every episode's measured (p5,p50,p95) luma profile, compute ONE common reel target
(the per-anchor median) and decide, per episode, whether a tone pair is worth
authoring. Mirrors color.percentiles / pacing / offset: pure decision here, IO in
the driver (match_grade.py)."""
import statistics
from dataclasses import dataclass
from scripts.lib import color

Profile = tuple[float, float, float]

MATCH_EPS = 4.0        # luma units (0-255). An episode whose every anchor is within
                       # this of the target gets NO tone pair: below color.TONE_MIN_GAP
                       # (6), the mapping is a near-identity the eye cannot see, so
                       # authoring it would spend the byte-identical fast path for nothing.


@dataclass(frozen=True)
class ToneDecision:
    """Per-episode planning outcome — what to author, and (when not) why, for MATCH.md."""
    index: int
    action: str                    # "author" | "skip"
    reason: str                    # "authored" | "within-eps" | "flat-source" | "hand-authored"
    tone_src: Profile | None = None
    tone_dst: Profile | None = None


def common_target(profiles: list[Profile]) -> Profile:
    """The reel's common tone target: the per-anchor MEDIAN across episodes, then
    gap-repaired so color.tone_arg accepts it. Every episode votes (a flat clip is a
    real exposure data point) even if it cannot itself receive a tone (§valid_src)."""
    if not profiles:
        raise ValueError("common_target: no profiles — measure at least one episode")
    t = tuple(statistics.median(p[k] for p in profiles) for k in range(3))
    return _repair_gaps(t)


def _repair_gaps(t: Profile, gap: float = color.TONE_MIN_GAP) -> Profile:
    """Push a target's anchors to >= `gap` around the median anchor, clamped to 0-255.
    The target is SYNTHETIC — no episode need match it — so widening a too-narrow gap is
    honest, unlike doing so to a measured source. A reel whose median carries no usable
    range (every anchor collapsed) cannot be spread inside 0-255 and is REFUSED, not
    silently flattened — there is nothing to match-grade."""
    p5, p50, p95 = t
    p5, p95 = min(p5, p50 - gap), max(p95, p50 + gap)
    if not (0 <= p5 and p95 <= 255 and p50 - p5 >= gap and p95 - p50 >= gap):
        raise ValueError(
            f"common_target: the reel's median profile {t} carries no usable tonal range "
            f"(cannot spread to {gap}-unit gaps inside 0-255) — match-grade has nothing to "
            "normalize; check the footage is not all flat or black")
    return (p5, p50, p95)


def valid_src(profile: Profile, gap: float = color.TONE_MIN_GAP) -> bool:
    """Can this measured profile be a tone_src? color.tone_arg needs strictly increasing
    anchors >= `gap` apart. A low-contrast clip cannot, and its contrast cannot be
    invented — so the conductor SKIPS it (flat-source) rather than fabricate a source."""
    return all(b - a >= gap for a, b in zip(profile, profile[1:]))


def needs_tone(profile: Profile, target: Profile, eps: float = MATCH_EPS) -> bool:
    """True iff the max per-anchor distance to the target exceeds `eps` — far enough to
    be worth a curve. Within eps: leave the episode byte-identical."""
    return max(abs(a - b) for a, b in zip(profile, target)) > eps


def plan(profiles: list[Profile], has_tone: list[bool], target: Profile,
         *, eps: float = MATCH_EPS, force: bool = False) -> list[ToneDecision]:
    """Decide each episode's tone pair against `target`. Guard ORDER is the contract:
    a hand-authored pair is respected first (unless `force`), then a flat source is
    skipped (cannot be a valid src), then a within-eps episode is left untouched, else
    author (its own profile -> the common target)."""
    out = []
    for i, (p, ht) in enumerate(zip(profiles, has_tone)):
        if ht and not force:
            out.append(ToneDecision(i, "skip", "hand-authored"))
        elif not valid_src(p):
            out.append(ToneDecision(i, "skip", "flat-source"))
        elif not needs_tone(p, target, eps):
            out.append(ToneDecision(i, "skip", "within-eps"))
        else:
            out.append(ToneDecision(i, "author", "authored", tone_src=p, tone_dst=target))
    return out
```

## 3. The driver — `scripts/match_grade.py`

Measures (reuses `measure_profile`), applies the pure decisions with
`dataclasses.replace` (which re-runs `EDLEpisode.__post_init__`, re-coercing the
tone pair to tuples — validity is a downstream `ReframeSpec` check, §7), and does
the EDL IO. Mirror of `pacing.py`.

```python
def conduct(edl: EDL, footage_root: str, *, eps=matchgrade.MATCH_EPS,
            force=False) -> tuple[EDL, matchgrade.Profile, list[matchgrade.ToneDecision]]:
    """Measure each episode's source at its window MIDPOINT (start + dur/2 — a settled,
    representative frame of the shipped window), compute the common target, and return
    (enriched EDL, target, decisions). Whole-frame measure — see §5."""
    profiles = [measure_profile(str(Path(footage_root) / e.source), at=e.start + e.dur / 2)
                for e in edl.episodes]
    target = matchgrade.common_target(profiles)
    has_tone = [e.tone_src is not None for e in edl.episodes]
    decisions = matchgrade.plan(profiles, has_tone, target, eps=eps, force=force)
    # apply: author -> set the pair; within-eps/flat -> CLEAR to None (removes a stale
    # pair on a --force re-conduct); hand-authored -> leave the episode untouched.
    new_episodes = tuple(
        e if d.reason == "hand-authored"
        else replace(e, tone_src=d.tone_src, tone_dst=d.tone_dst)
        for e, d in zip(edl.episodes, decisions))
    return replace(edl, episodes=new_episodes), target, decisions
```

- **`write_match(edl_path, footage_root, eps, force)`** — `EDL.from_json` →
  `conduct` → write `EDL.json` **back in place** (the stage enriches the EDL) and
  a sibling `MATCH.md`. Returns a status dict
  `{"status": "written", "target": [...], "authored": n, "skipped": {...}, ...}`.
- **CLI:** `match_grade build --edl EDL.json --footage-root DIR [--eps 4.0]
  [--force]`. In-place by design; `--force` re-measures and re-authors (and clears
  now-stale pairs). `measure_profile` already seeks `-ss` **after** `-i` (§12);
  the conductor issues no new ffmpeg of its own.
- **`MATCH.md`** — header (target triple, eps, counts) + one row per episode:
  `# | source | measured (p5/p50/p95) | target | max Δ | action · reason`. The
  human-readable half a reviewer reads at CP-time.

## 4. Router + skill wiring

- **`montage.py`:** a new optional stage after `pacing`, before `assemble-draft`:
  `Stage("match-grade", "MATCH.md", "optional", "match-grade SKILL -> match_grade
  CLI", None)`. `checkpoint=None` — the tone is reviewed on the final reel (CP3),
  like pacing. The `next_action` inspector treats it as any optional stage (never
  blocks). One `montage.py` test extends the stage-count / ordering assertions.
- **`skills/match-grade/SKILL.md`:** run after the cut is settled (edit-plan +
  pacing), opt-in, when episodes come from mixed cameras/light; invoke the CLI;
  read `MATCH.md`; note it touches only tone and that a per-episode override
  (a hand-authored pair) is respected. Small stage-skill, twin of `pacing`.
- **`using-montage` SKILL:** name match-grade in the conveyor order
  (`… → [pacing] → [match-grade] → [assemble-draft] → …`) as an optional stage,
  and state the ordering rule (§7).

## 5. Honest limitations (the load-bearing half)

- **Whole frame, not the shipped crop.** The conductor runs before tracking, so
  there is no crop to measure; it samples the **whole source frame** at the
  window midpoint. A crop centred on a rider has a different histogram from the
  frame around it (the `tone_arg` docstring says so). This is the same boundary
  `measure_profile` already ships with, and the honest MVP: crop-accurate
  measuring needs a post-tracking pass (Approach C, rejected for the second
  encode it costs). Recorded, not hidden.
- **One frame, not K.** A single midpoint still, not a temporal average — one odd
  frame (a flash, a whip-pan blur) can skew an episode's profile. The median
  target absorbs one bad *episode*, not one bad *frame within* an episode.
  K-frame sampling is a cheap future refinement (§8).
- **Tone only.** The conductor does not touch white balance, black point,
  saturation, or any other knob — it cannot fix a colour **cast** across episodes,
  only their tonal (luma) shape. A cross-episode cast stays a hand/agent job.
- **Not a scene-cut flattener.** It pulls episodes toward one *reel* target; it
  does not detect that a reel deliberately cuts between two exposures (open water
  → bright beach). That editorial signal stays with `edl_to_reel
  --color-delta-max`, unchanged.
- **In-place rewrite is not re-add-idempotent.** The conductor cannot tell its
  own authored pair from a human's; a second run without `--force` sees the pair
  and skips (`hand-authored`). Re-conducting after adding footage needs
  `--force`. Documented in the skill.

## 6. Testing

**Unit — `tests/lib/test_matchgrade.py`** (pure, no ffmpeg):

- `common_target`: median over odd and even episode counts (even → the mean of
  the two middles, per `statistics.median`); gap-repair widens a too-narrow
  median; the degenerate all-collapsed median **raises** (whole-object message).
- `valid_src`: a contrasty profile passes; a flat one (gaps < 6) fails.
- `needs_tone`: within-eps False, beyond-eps True; boundary at exactly eps.
- `plan`: each of the four branches; `force` overrides `hand-authored` (and only
  that guard — a within-eps episode is still skipped under force); the apply-time
  contract that a within-eps/flat decision carries `None` pair (clears stale)
  while a hand-authored decision carries none (driver leaves the episode).

**Integration — `tests/integration/test_matchgrade.py`** (real ffmpeg, marked):

- Build 2-3 real clips of deliberately different exposure (ffmpeg `color`/`geq`
  gradients), an `EDL.json` over them, run `conduct`; assert the target is the
  per-anchor median, the off-target clip got a tone pair and the near-median clip
  did not (within-eps → byte-identical), and — the real proof — deliver the reel
  through `edl_to_reel` and assert the delivered episodes' measured profiles have
  **converged** toward the target (spread shrinks) and the `tone_arg` `curves`
  fragment is present in the graded chain.

## 7. Landmines / invariants

- **Run after pacing.** Pacing re-runs edit-plan with `--pacing`, which
  regenerates `EDL.json` and would **wipe** any tone the conductor wrote. The
  stage order (match-grade *after* pacing) and the skill both state this; it is
  the same "settle the cut first" rule pacing itself carries.
- **The target is synthetic; a source is not.** `_repair_gaps` widens the target
  (honest — no episode must match it); a measured `tone_src` is **never** widened
  — a flat source is skipped instead. Never invent a source's contrast.
- **Every episode votes; not every episode receives.** A flat clip contributes
  its exposure to the median but is skipped as a `tone_src`. Named in `MATCH.md`,
  not silent.
- **`measure_profile` seek order** — `-ss` after `-i` (§12). The conductor adds
  no new ffmpeg call; it reuses the audited one.
- **`dataclasses.replace` re-coerces, it does not validate.** Applying a decision
  through `replace` re-runs `EDLEpisode.__post_init__`, which only coerces the
  tone pair to tuples. Tone-pair VALIDITY (ordering, gap, 0-255 range) is a
  hard-engine check in `ReframeSpec` (the soft-manifest / hard-engine split), so
  a malformed pair fails at episode processing, not here — `EDLEpisode`
  deliberately does not gate it, matching `hero`/`pan`/`layout`.

## 8. What this does NOT do (deferred)

- **Crop-accurate / K-frame measuring** — §5. The whole-frame midpoint still is
  the MVP; both refinements are additive and can land later without moving this
  baseline.
- **Reference-episode target** — match everyone to a chosen real shot instead of
  the synthetic median. Needs a defensible pick rule; a future option alongside
  the median.
- **The §10 mood LUT** — impose an external look from `SPEC.mood`. Explicitly a
  separate slice (the colour-stage design lists it apart from the conductor); the
  conductor is consistency, not imposition.
- **Cross-episode white-balance / cast matching** — the conductor is tone (luma)
  only; a shared cast correction is its own future actuator+conductor pair.
- **Per-part fidelity** (skin vs gear) — that is `color_fidelity`'s future
  refinement, unrelated to authoring the tone target.
