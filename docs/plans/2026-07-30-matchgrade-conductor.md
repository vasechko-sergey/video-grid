# Match-grade conductor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `match-grade` stage that measures every EDL episode's luma profile, computes one common reel target (the per-anchor median), and auto-authors `tone_src`/`tone_dst` into the episodes that deviate — so a reel cut from mixed cameras/light reads as one grade.

**Architecture:** Pure decision core in `scripts/lib/matchgrade.py` (median target + gap-repair + eps-gate + a per-episode planner; no ffmpeg, no numpy) driven by a thin `scripts/match_grade.py` (reuses `color_measure.measure_profile`, does the EDL IO). A standalone post-EDL stage: reads `EDL.json`, writes it back enriched + a `MATCH.md` report. Opt-in optional router stage after pacing. Design: [docs/specs/2026-07-30-matchgrade-conductor-design.md](../specs/2026-07-30-matchgrade-conductor-design.md).

**Tech Stack:** Python 3.13, `statistics` (stdlib), pytest. Reuses `scripts/lib/color.py` (`TONE_MIN_GAP`, `tone_arg`), `scripts/color_measure.py` (`measure_profile`), `scripts/lib/edl.py` (`EDL`/`EDLEpisode`), `scripts/montage.py` (`Stage`/`V1_STAGES`).

---

## File Structure

- **Create** `scripts/lib/matchgrade.py` — pure core: `Profile`, `MATCH_EPS`, `common_target`, `_repair_gaps`, `valid_src`, `needs_tone`, `ToneDecision`, `plan`.
- **Create** `scripts/match_grade.py` — driver: `conduct`, `write_match`, `_report_md`, `main` (CLI).
- **Modify** `scripts/montage.py:37` — insert the `match-grade` optional stage.
- **Create** `skills/match-grade/SKILL.md` — the stage skill.
- **Modify** `skills/using-montage/SKILL.md` — name match-grade in the conveyor order.
- **Create** `tests/lib/test_matchgrade.py` — core unit tests (Tasks 0-2).
- **Create** `tests/lib/test_match_grade.py` — driver unit tests (Tasks 3-4).
- **Modify** `tests/lib/test_montage.py` — stage-list/kind assertions (Task 5).
- **Create** `tests/integration/test_matchgrade.py` — real-ffmpeg convergence proof (Task 6).
- **Modify** `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`, `docs/specs/2026-07-26-colour-stage-design.md` — docs sync (Task 7).

---

### Task 0: `matchgrade` core — the common target

**Files:**
- Create: `scripts/lib/matchgrade.py`
- Test: `tests/lib/test_matchgrade.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/lib/test_matchgrade.py
import pytest

from scripts.lib import matchgrade


def test_common_target_is_the_per_anchor_median_odd_count():
    profiles = [(10.0, 100.0, 200.0), (30.0, 120.0, 210.0), (20.0, 110.0, 220.0)]
    assert matchgrade.common_target(profiles) == (20.0, 110.0, 210.0)


def test_common_target_median_even_count_averages_the_two_middles():
    # statistics.median of an even column averages the two middle values
    profiles = [(10.0, 100.0, 200.0), (30.0, 120.0, 240.0)]
    assert matchgrade.common_target(profiles) == (20.0, 110.0, 220.0)


def test_common_target_widens_a_too_narrow_median_to_the_gap():
    # every episode almost flat around 128 → median (126,128,130) has 2-unit gaps;
    # the SYNTHETIC target is spread to >= TONE_MIN_GAP (6) around the middle anchor.
    profiles = [(126.0, 128.0, 130.0), (126.0, 128.0, 130.0)]
    p5, p50, p95 = matchgrade.common_target(profiles)
    assert p50 == 128.0 and p50 - p5 >= 6.0 and p95 - p50 >= 6.0


def test_common_target_refuses_a_reel_with_no_tonal_range():
    # a median pinned at an edge cannot be spread inside 0-255 → fail loud
    with pytest.raises(ValueError, match="no usable tonal range"):
        matchgrade.common_target([(2.0, 3.0, 4.0), (2.0, 3.0, 4.0)])


def test_common_target_empty_is_refused():
    with pytest.raises(ValueError, match="no profiles"):
        matchgrade.common_target([])
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_matchgrade.py -x -q`
Expected: FAIL — `ModuleNotFoundError: scripts.lib.matchgrade`.

- [ ] **Step 3: Write the implementation**

```python
# scripts/lib/matchgrade.py
"""The match-grade conductor's pure core (design 2026-07-30, montage §10). Given every
episode's measured (p5,p50,p95) luma profile, compute ONE common reel target (the
per-anchor median) and decide, per episode, whether a tone pair is worth authoring.
No ffmpeg, no numpy — the driver (match_grade.py) measures; this only decides. Mirrors
color.percentiles / pacing / offset: pure decision here, IO in the driver."""
import statistics
from dataclasses import dataclass

from scripts.lib import color

Profile = tuple[float, float, float]

MATCH_EPS = 4.0        # luma units (0-255). An episode whose every anchor is within this
                       # of the target gets NO tone pair: below color.TONE_MIN_GAP (6) the
                       # mapping is a near-identity the eye cannot see, so authoring it would
                       # spend the reframe byte-identical fast path for nothing.


def common_target(profiles: list[Profile]) -> Profile:
    """The reel's common tone target: the per-anchor MEDIAN across episodes, gap-repaired
    so color.tone_arg accepts it. Median (not mean) so one blown-out or crushed episode
    cannot drag the target off the group it should represent. Every episode votes — even
    a flat clip that cannot itself receive a tone (valid_src) is a real exposure sample.
    Because each row is ordered (p5<=p50<=p95), the column medians are ordered too, so the
    target is always non-decreasing; only narrow gaps need repair, never an inversion."""
    if not profiles:
        raise ValueError("common_target: no profiles — measure at least one episode")
    t = tuple(statistics.median(p[k] for p in profiles) for k in range(3))
    return _repair_gaps(t)


def _repair_gaps(t: Profile, gap: float = color.TONE_MIN_GAP) -> Profile:
    """Push a target's anchors to >= `gap` around the middle anchor, clamped to 0-255. The
    target is SYNTHETIC — no episode must match it — so widening a too-narrow gap is honest,
    unlike doing so to a measured source. A reel whose median carries no usable range
    (anchors collapsed at an edge) cannot be spread inside 0-255 and is REFUSED, not
    silently flattened: there is nothing to match-grade."""
    p5, p50, p95 = t
    p5, p95 = min(p5, p50 - gap), max(p95, p50 + gap)
    if not (0 <= p5 and p95 <= 255 and p50 - p5 >= gap and p95 - p50 >= gap):
        raise ValueError(
            f"common_target: the reel's median profile {t} carries no usable tonal range "
            f"(cannot spread to {gap}-unit gaps inside 0-255) — match-grade has nothing to "
            "normalize; check the footage is not all flat or black")
    return (p5, p50, p95)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_matchgrade.py -x -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Mutation check the refusal guard**

Temporarily change `_repair_gaps`'s condition to `if False:` (neutralize the refusal). Run `tests/lib/test_matchgrade.py::test_common_target_refuses_a_reel_with_no_tonal_range` — it MUST flip to FAIL (it would return a bad target instead of raising). Restore the guard; confirm green.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/matchgrade.py tests/lib/test_matchgrade.py
git commit -m "feat: matchgrade.common_target — per-anchor median + gap-repair"
```

Commit body ends with:
```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

---

### Task 1: `valid_src` + `needs_tone`

**Files:**
- Modify: `scripts/lib/matchgrade.py`
- Test: `tests/lib/test_matchgrade.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_valid_src_true_for_a_contrasty_profile():
    assert matchgrade.valid_src((10.0, 100.0, 200.0)) is True


def test_valid_src_false_for_a_flat_profile():
    # gaps below TONE_MIN_GAP (6): color.tone_arg would reject it as a source
    assert matchgrade.valid_src((126.0, 128.0, 130.0)) is False


def test_valid_src_boundary_exactly_the_gap_is_valid():
    assert matchgrade.valid_src((100.0, 106.0, 112.0)) is True


def test_needs_tone_false_within_eps():
    # every anchor within MATCH_EPS (4) of the target
    assert matchgrade.needs_tone((102.0, 128.0, 200.0), (100.0, 128.0, 203.0)) is False


def test_needs_tone_true_when_one_anchor_exceeds_eps():
    assert matchgrade.needs_tone((100.0, 128.0, 210.0), (100.0, 128.0, 200.0)) is True


def test_needs_tone_boundary_exactly_eps_is_not_enough():
    # distance == eps is NOT "beyond" — strict >
    assert matchgrade.needs_tone((104.0, 128.0, 200.0), (100.0, 128.0, 200.0),
                                 eps=4.0) is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_matchgrade.py -x -q -k "valid_src or needs_tone"`
Expected: FAIL — `AttributeError: module 'scripts.lib.matchgrade' has no attribute 'valid_src'`.

- [ ] **Step 3: Write the implementation** (append to `matchgrade.py`)

```python
def valid_src(profile: Profile, gap: float = color.TONE_MIN_GAP) -> bool:
    """Can this measured profile be a tone_src? color.tone_arg needs strictly increasing
    anchors >= `gap` apart. A low-contrast clip cannot, and its contrast cannot be invented
    — so the conductor SKIPS it (flat-source) rather than fabricate a source."""
    return all(b - a >= gap for a, b in zip(profile, profile[1:]))


def needs_tone(profile: Profile, target: Profile, eps: float = MATCH_EPS) -> bool:
    """True iff the max per-anchor distance to `target` exceeds `eps` — far enough to be
    worth a curve. Within eps: leave the episode byte-identical."""
    return max(abs(a - b) for a, b in zip(profile, target)) > eps
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_matchgrade.py -x -q`
Expected: PASS (11 tests).

- [ ] **Step 5: Mutation check the two boundaries**

(a) Change `needs_tone`'s `> eps` to `>= eps`; `test_needs_tone_boundary_exactly_eps_is_not_enough` MUST fail. Restore.
(b) Change `valid_src`'s `>= gap` to `> gap`; `test_valid_src_boundary_exactly_the_gap_is_valid` MUST fail. Restore. Confirm green.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/matchgrade.py tests/lib/test_matchgrade.py
git commit -m "feat: matchgrade.valid_src + needs_tone — the flat-source and eps gates"
```

---

### Task 2: `ToneDecision` + `plan`

**Files:**
- Modify: `scripts/lib/matchgrade.py`
- Test: `tests/lib/test_matchgrade.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
TARGET = (20.0, 110.0, 210.0)


def test_plan_authors_a_deviating_valid_episode():
    p = (10.0, 100.0, 150.0)                      # far from TARGET, contrasty
    [d] = matchgrade.plan([p], [False], TARGET)
    assert d.action == "author" and d.reason == "authored"
    assert d.measured == p and d.tone_src == p and d.tone_dst == TARGET


def test_plan_skips_within_eps_with_no_pair_but_keeps_measured():
    p = (21.0, 111.0, 211.0)                      # within eps of TARGET
    [d] = matchgrade.plan([p], [False], TARGET)
    assert d.action == "skip" and d.reason == "within-eps"
    assert d.measured == p                         # measured is carried even on a skip
    assert d.tone_src is None and d.tone_dst is None


def test_plan_skips_a_flat_source():
    p = (126.0, 128.0, 130.0)                     # gaps < 6 → cannot be a src
    [d] = matchgrade.plan([p], [False], TARGET)
    assert d.action == "skip" and d.reason == "flat-source"


def test_plan_respects_a_hand_authored_pair_by_default():
    p = (10.0, 100.0, 150.0)                      # would otherwise author
    [d] = matchgrade.plan([p], [True], TARGET)
    assert d.action == "skip" and d.reason == "hand-authored"
    assert d.tone_src is None and d.tone_dst is None


def test_plan_force_overrides_hand_authored_and_re_authors():
    p = (10.0, 100.0, 150.0)
    [d] = matchgrade.plan([p], [True], TARGET, force=True)
    assert d.action == "author" and d.tone_src == p and d.tone_dst == TARGET


def test_plan_force_still_skips_a_within_eps_episode():
    # force only bypasses the hand-authored guard, never authors an imperceptible curve
    p = (21.0, 111.0, 211.0)
    [d] = matchgrade.plan([p], [True], TARGET, force=True)
    assert d.action == "skip" and d.reason == "within-eps"


def test_plan_preserves_index_order():
    ps = [(10.0, 100.0, 150.0), (21.0, 111.0, 211.0)]
    ds = matchgrade.plan(ps, [False, False], TARGET)
    assert [d.index for d in ds] == [0, 1]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_matchgrade.py -x -q -k plan`
Expected: FAIL — `AttributeError: ... has no attribute 'plan'`.

- [ ] **Step 3: Write the implementation** (append to `matchgrade.py`)

```python
@dataclass(frozen=True)
class ToneDecision:
    """Per-episode planning outcome — the measured profile (always, for MATCH.md), what to
    author, and (when not) why. author -> tone_src/tone_dst carry the pair; within-eps/flat
    -> None (the driver CLEARS a stale pair on a --force re-conduct); hand-authored -> the
    driver leaves the episode as-is. `measured` is carried so the report and the driver need
    no second measure pass."""
    index: int
    action: str                    # "author" | "skip"
    reason: str                    # "authored" | "within-eps" | "flat-source" | "hand-authored"
    measured: Profile
    tone_src: Profile | None = None
    tone_dst: Profile | None = None


def plan(profiles: list[Profile], has_tone: list[bool], target: Profile,
         *, eps: float = MATCH_EPS, force: bool = False) -> list[ToneDecision]:
    """Decide each episode's tone pair against `target`. Guard ORDER is the contract:
    a hand-authored pair is respected first (unless `force`), then a flat source is skipped
    (cannot be a valid src), then a within-eps episode is left untouched, else author (its
    own profile -> the common target). Every decision carries its measured profile."""
    out = []
    for i, (p, ht) in enumerate(zip(profiles, has_tone)):
        if ht and not force:
            out.append(ToneDecision(i, "skip", "hand-authored", measured=p))
        elif not valid_src(p):
            out.append(ToneDecision(i, "skip", "flat-source", measured=p))
        elif not needs_tone(p, target, eps):
            out.append(ToneDecision(i, "skip", "within-eps", measured=p))
        else:
            out.append(ToneDecision(i, "author", "authored", measured=p, tone_src=p, tone_dst=target))
    return out
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_matchgrade.py -x -q`
Expected: PASS (18 tests).

- [ ] **Step 5: Mutation check the guard order**

Move the `ht and not force` branch to LAST (after the else authors). `test_plan_respects_a_hand_authored_pair_by_default` MUST fail (a hand-authored deviating episode would author instead of being respected). Restore; confirm green.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/matchgrade.py tests/lib/test_matchgrade.py
git commit -m "feat: matchgrade.plan — per-episode tone decisions with guard order"
```

---

### Task 3: driver `conduct`

**Files:**
- Create: `scripts/match_grade.py`
- Test: `tests/lib/test_match_grade.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/lib/test_match_grade.py
from scripts import match_grade
from scripts.lib.edl import EDLEpisode, EDL


def _ep(source, start=0.0, dur=2.0, **kw):
    return EDLEpisode(source=source, start=start, dur=dur, shot_type="wide",
                      composition="center", grid="thirds", **kw)


def _edl(*eps):
    return EDL(episodes=tuple(eps))


def test_conduct_measures_at_the_window_midpoint(monkeypatch):
    seen = []
    monkeypatch.setattr(match_grade, "measure_profile",
                        lambda clip, at=None: seen.append((clip, at)) or (10.0, 100.0, 150.0))
    edl = _edl(_ep("a.mp4", start=4.0, dur=2.0))
    match_grade.conduct(edl, "/foot")
    assert seen == [("/foot/a.mp4", 5.0)]           # start + dur/2, resolved under footage_root


def test_conduct_authors_deviating_and_leaves_near_median(monkeypatch):
    # ep0 dark, ep1 bright → median between; ep2 sits on the median (within eps)
    profs = {"d.mp4": (10.0, 90.0, 150.0), "b.mp4": (40.0, 130.0, 240.0),
             "m.mp4": (25.0, 110.0, 195.0)}
    monkeypatch.setattr(match_grade, "measure_profile", lambda clip, at=None: profs[clip.split("/")[-1]])
    edl = _edl(_ep("d.mp4"), _ep("b.mp4"), _ep("m.mp4"))
    out, target, decisions = match_grade.conduct(edl, "/foot")
    assert target == (25.0, 110.0, 195.0)            # per-anchor median of the three
    assert out.episodes[0].tone_src == (10.0, 90.0, 150.0) and out.episodes[0].tone_dst == target
    assert out.episodes[1].tone_src == (40.0, 130.0, 240.0)
    assert out.episodes[2].tone_src is None          # within eps → no pair, byte-identical


def test_conduct_leaves_a_hand_authored_pair(monkeypatch):
    monkeypatch.setattr(match_grade, "measure_profile", lambda clip, at=None: (10.0, 90.0, 150.0))
    edl = _edl(_ep("d.mp4", tone_src=(5.0, 80.0, 140.0), tone_dst=(20.0, 110.0, 210.0)))
    out, _, _ = match_grade.conduct(edl, "/foot")
    assert out.episodes[0].tone_src == (5.0, 80.0, 140.0)     # untouched


def test_conduct_force_clears_a_now_within_eps_pair(monkeypatch):
    # a previously-authored episode now sits on the median → force removes the stale pair
    profs = {"d.mp4": (25.0, 110.0, 195.0), "b.mp4": (25.0, 110.0, 195.0)}
    monkeypatch.setattr(match_grade, "measure_profile", lambda clip, at=None: profs[clip.split("/")[-1]])
    edl = _edl(_ep("d.mp4", tone_src=(5.0, 80.0, 140.0), tone_dst=(20.0, 110.0, 210.0)), _ep("b.mp4"))
    out, _, _ = match_grade.conduct(edl, "/foot", force=True)
    assert out.episodes[0].tone_src is None and out.episodes[0].tone_dst is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_match_grade.py -x -q`
Expected: FAIL — `ModuleNotFoundError: scripts.match_grade`.

- [ ] **Step 3: Write the implementation**

```python
# scripts/match_grade.py
"""The match-grade conductor (design 2026-07-30, montage §10): measure every EDL episode's
source, compute one common reel tone target (the median), and author tone_src/tone_dst into
the episodes that deviate — so the reel reads as one grade. Reads EDL.json, writes it back
enriched + a MATCH.md report. Opt-in: it CHANGES the look, so it is never on the autonomous
path. matchgrade owns the decisions; this driver owns the ffmpeg measuring (measure_profile)
and the EDL IO. Mirror of pacing.py: pure core in lib, driver here."""
import argparse
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

from scripts.color_measure import measure_profile
from scripts.lib import matchgrade
from scripts.lib.edl import EDL


def conduct(edl: EDL, footage_root: str, *, eps: float = matchgrade.MATCH_EPS,
            force: bool = False) -> tuple[EDL, matchgrade.Profile, list[matchgrade.ToneDecision]]:
    """Measure each episode's source at its window MIDPOINT (start + dur/2 — a settled,
    representative frame of the shipped window; a WHOLE frame, not the crop — see design §5),
    compute the common target, and return (enriched EDL, target, decisions). The decisions
    carry each measured profile, so write_match writes the report with no second measure.
    Applying through dataclasses.replace re-runs EDLEpisode.__post_init__, so a malformed
    pair fails loud here."""
    profiles = [measure_profile(str(Path(footage_root) / e.source), at=e.start + e.dur / 2)
                for e in edl.episodes]
    target = matchgrade.common_target(profiles)
    has_tone = [e.tone_src is not None for e in edl.episodes]
    decisions = matchgrade.plan(profiles, has_tone, target, eps=eps, force=force)
    eps_out = tuple(
        e if d.reason == "hand-authored"                       # respect the human's pair
        else replace(e, tone_src=d.tone_src, tone_dst=d.tone_dst)  # set, or clear (None) a stale one
        for e, d in zip(edl.episodes, decisions))
    return replace(edl, episodes=eps_out), target, decisions
```

(The rest of the driver — `write_match`, `_report_md`, `main` — lands in Task 4; this task ships `conduct` and its import head only.)

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_match_grade.py -x -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Mutation check the apply branch**

Change the apply comprehension's `e if d.reason == "hand-authored"` to `e if False` (always replace). `test_conduct_leaves_a_hand_authored_pair` MUST fail (the hand pair would be overwritten). Restore; confirm green.

- [ ] **Step 6: Commit**

```bash
git add scripts/match_grade.py tests/lib/test_match_grade.py
git commit -m "feat: match_grade.conduct — measure, target, apply tone decisions to the EDL"
```

---

### Task 4: driver `write_match` + `MATCH.md` + CLI

**Files:**
- Modify: `scripts/match_grade.py`
- Test: `tests/lib/test_match_grade.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
import sys


def _write_edl(path, *eps):
    path.write_text(json.dumps(_edl(*eps).to_dict(), indent=2))
    return str(path)


def test_write_match_rewrites_the_edl_and_writes_md(tmp_path, monkeypatch):
    monkeypatch.setattr(match_grade, "measure_profile",
                        lambda clip, at=None: (10.0, 90.0, 150.0) if "d.mp4" in clip
                        else (40.0, 130.0, 240.0))
    edl_path = _write_edl(tmp_path / "EDL.json", _ep("d.mp4"), _ep("b.mp4"))
    status = match_grade.write_match(edl_path, "/foot")
    assert status["status"] == "written" and status["authored"] == 2
    back = EDL.from_json(edl_path)                    # the EDL was rewritten in place
    assert back.episodes[0].tone_src == (10.0, 90.0, 150.0)
    assert back.episodes[0].tone_dst == tuple(status["target"])
    md = (tmp_path / "MATCH.md").read_text()
    assert md.startswith("# Match-grade") and "d.mp4" in md and "author" in md


def test_write_match_reports_skips(tmp_path, monkeypatch):
    monkeypatch.setattr(match_grade, "measure_profile", lambda clip, at=None: (126.0, 128.0, 130.0)
                        if "flat.mp4" in clip else (10.0, 90.0, 150.0))
    edl_path = _write_edl(tmp_path / "EDL.json", _ep("d.mp4"), _ep("flat.mp4"))
    status = match_grade.write_match(edl_path, "/foot")
    assert status["skipped"].get("flat-source") == 1


def test_cli_build_threads_eps_and_force(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(match_grade, "write_match",
                        lambda edl, footage_root, **k: seen.update(edl=edl, footage_root=footage_root, **k)
                        or {"status": "written", "target": [0, 0, 0], "authored": 0, "skipped": {}})
    monkeypatch.setattr(sys, "argv",
                        ["match_grade", "build", "--edl", "E.json", "--footage-root", "F",
                         "--eps", "6", "--force"])
    with pytest.raises(SystemExit) as e:
        match_grade.main()
    assert e.value.code == 0
    assert seen == {"edl": "E.json", "footage_root": "F", "eps": 6.0, "force": True}
```

Add `import pytest` at the top of the test file if not already present.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_match_grade.py -x -q -k "write_match or cli"`
Expected: FAIL — `AttributeError: ... has no attribute 'write_match'`.

- [ ] **Step 3: Write the implementation** (append to `match_grade.py`)

```python
def _report_md(sources: list[str], target: matchgrade.Profile,
               decisions: list[matchgrade.ToneDecision], eps: float) -> str:
    """The human-readable half a reviewer reads at CP-time: the target, and one row per
    episode with its measured profile (carried on the decision — no second measure), its
    distance to the target, and what was decided."""
    def _triple(t):
        return "/".join(f"{v:.0f}" for v in t)
    n_auth = sum(1 for d in decisions if d.action == "author")
    lines = [f"# Match-grade — target {_triple(target)} (p5/p50/p95), eps {eps:g}", "",
             f"{n_auth}/{len(decisions)} episodes authored a tone pair.", "",
             "| # | source | measured (p5/p50/p95) | max Δ | action · reason |",
             "|---|--------|-----------------------|:-----:|-----------------|"]
    for src, d in zip(sources, decisions):
        delta = max(abs(a - b) for a, b in zip(d.measured, target))
        lines.append(f"| {d.index} | {src} | {_triple(d.measured)} | {delta:.0f} | {d.action} · {d.reason} |")
    return "\n".join(lines) + "\n"


def write_match(edl_path: str, footage_root: str, *, eps: float = matchgrade.MATCH_EPS,
                force: bool = False) -> dict:
    """Read EDL.json → conduct → write the enriched EDL BACK IN PLACE (the stage enriches the
    EDL a human then reviews) + a sibling MATCH.md. One measure pass (inside conduct); the
    decisions carry the measured profiles the report needs. Returns a status dict."""
    edl = EDL.from_json(edl_path)
    out, target, decisions = conduct(edl, footage_root, eps=eps, force=force)
    Path(edl_path).write_text(json.dumps(out.to_dict(), indent=2))
    md_path = Path(edl_path).parent / "MATCH.md"
    md_path.write_text(_report_md([e.source for e in edl.episodes], target, decisions, eps))
    skipped = Counter(d.reason for d in decisions if d.action == "skip")
    return {"status": "written", "edl": str(edl_path), "md": str(md_path),
            "target": list(target), "eps": eps,
            "authored": sum(1 for d in decisions if d.action == "author"),
            "skipped": dict(skipped)}
```

```python
def main() -> None:
    ap = argparse.ArgumentParser(
        description="match-grade conductor — author tone_src/tone_dst across an EDL (§10)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="measure every episode → common target → author tone pairs")
    b.add_argument("--edl", required=True, help="EDL.json — enriched IN PLACE with tone pairs")
    b.add_argument("--footage-root", required=True, help="dir the EDL 'source' paths resolve against")
    b.add_argument("--eps", type=float, default=matchgrade.MATCH_EPS,
                   help=f"skip an episode within this many luma units of the target "
                        f"(default {matchgrade.MATCH_EPS})")
    b.add_argument("--force", action="store_true",
                   help="re-author even hand-authored/previously-conducted episodes")
    a = ap.parse_args()
    result = write_match(a.edl, a.footage_root, eps=a.eps, force=a.force)
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_match_grade.py -x -q`
Expected: PASS. Then run the whole core+driver: `.venv/bin/python -m pytest tests/lib/test_matchgrade.py tests/lib/test_match_grade.py -q`.

- [ ] **Step 5: Commit**

```bash
git add scripts/match_grade.py tests/lib/test_match_grade.py
git commit -m "feat: match_grade write_match + MATCH.md report + build CLI"
```

---

### Task 5: router — the optional `match-grade` stage

**Files:**
- Modify: `scripts/montage.py:37` (`V1_STAGES`)
- Test: `tests/lib/test_montage.py`

- [ ] **Step 1: Write the failing test changes**

Edit `tests/lib/test_montage.py::test_v1_stages_order_and_keys` to insert `"match-grade"` after `"pacing"`:

```python
def test_v1_stages_order_and_keys():
    assert [s.key for s in V1_STAGES] == [
        "project-init", "footage-intake", "reel-brief", "trend-scan",
        "edit-plan", "music-and-mood", "pacing", "match-grade", "assemble-draft", "titles",
        "deliver", "reel-review"]
```

Append to `test_v1_stages_kinds_and_flags`:

```python
    assert by["match-grade"].kind == "optional"
    assert by["match-grade"].artifact == "MATCH.md"
    assert by["match-grade"].checkpoint is None
    assert by["match-grade"].in_out is False
```

Add a next_action test:

```python
def test_match_grade_optional_absent_then_present(tmp_path):
    (tmp_path / "EDL.json").write_text("{}")
    res = next_action(str(tmp_path))
    assert _state(res, "match-grade") == "optional"      # absent optional never blocks
    (tmp_path / "MATCH.md").write_text("x")
    res2 = next_action(str(tmp_path))
    assert _state(res2, "match-grade") == "done"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -x -q`
Expected: FAIL — the order list and `by["match-grade"]` lookups fail (stage absent).

- [ ] **Step 3: Write the implementation**

In `scripts/montage.py`, insert into `V1_STAGES` between the `pacing` and `assemble-draft` entries:

```python
    Stage("match-grade", "MATCH.md", "optional",
          "match-grade SKILL -> match_grade build CLI (opt-in; run AFTER pacing settles "
          "the cut, before deliver)", None),
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/montage.py tests/lib/test_montage.py
git commit -m "feat: montage — the optional match-grade stage after pacing"
```

---

### Task 6: real-ffmpeg convergence proof

**Files:**
- Create: `tests/integration/test_matchgrade.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_matchgrade.py
"""Real-ffmpeg proof of the conductor: two clips of different exposure, each with tonal
range, converge toward the median target once the authored tone_arg curve is rendered."""
from pathlib import Path

from scripts import match_grade
from scripts.color_measure import measure_profile
from scripts.lib import color, ffbin, proc
from scripts.lib.edl import EDL, EDLEpisode


def _two_band(path, lo, hi):
    """A clip whose left half is `lo`, right half `hi` — a real tonal range around a
    controllable exposure (mirrors tests/integration/test_color_measure.py)."""
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i", f"color=c={lo}:s=160x240:d=2:r=25",
              "-f", "lavfi", "-i", f"color=c={hi}:s=160x240:d=2:r=25",
              "-filter_complex", "hstack", "-pix_fmt", "yuv420p", str(path)])
    return path


def _ep(source):
    return EDLEpisode(source=source, start=0.0, dur=2.0, shot_type="wide",
                      composition="center", grid="thirds")


def _graded_profile(clip, src, dst, out):
    """Apply the real tone_arg curve (what reframe's grade_chain emits) and measure."""
    vf = color.tone_arg(src, dst).rstrip(",")            # strip the chain-joining comma
    proc.run([ffbin.ffmpeg(), "-y", "-i", str(clip), "-vf", vf, "-pix_fmt", "yuv420p", str(out)])
    return measure_profile(str(out))


def test_authored_tone_converges_two_exposures(tmp_path):
    dark = _two_band(tmp_path / "d.mp4", "0x101010", "0x808080")
    bright = _two_band(tmp_path / "b.mp4", "0x505050", "0xF0F0F0")
    edl = EDL(episodes=(_ep("d.mp4"), _ep("b.mp4")))

    out, target, decisions = match_grade.conduct(edl, str(tmp_path))
    assert all(d.action == "author" for d in decisions)   # both deviate from the median

    p_dark, p_bright = measure_profile(str(dark)), measure_profile(str(bright))
    src_spread = abs(p_dark[1] - p_bright[1])             # p50 gap before grading
    g_dark = _graded_profile(dark, *[out.episodes[0].tone_src, out.episodes[0].tone_dst],
                             tmp_path / "gd.mp4")
    g_bright = _graded_profile(bright, *[out.episodes[1].tone_src, out.episodes[1].tone_dst],
                               tmp_path / "gb.mp4")
    graded_spread = abs(g_dark[1] - g_bright[1])

    assert graded_spread < src_spread                     # the reel converged
    assert abs(g_dark[1] - target[1]) < abs(p_dark[1] - target[1])     # each moved toward target
    assert abs(g_bright[1] - target[1]) < abs(p_bright[1] - target[1])


def test_tone_arg_curve_is_actually_emitted(tmp_path):
    # the actuator the conductor feeds is a curves=all=... fragment
    frag = color.tone_arg((10.0, 90.0, 150.0), (20.0, 110.0, 210.0))
    assert frag.startswith("curves=all='") and frag.endswith("',")
```

- [ ] **Step 2: Run to verify it fails then passes**

Run: `.venv/bin/python -m pytest tests/integration/test_matchgrade.py -x -q`
Expected: PASS once Tasks 0-3 are in (this task adds no production code — it is the end-to-end proof over the real actuator).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_matchgrade.py
git commit -m "test: real-ffmpeg proof the authored tone converges two exposures"
```

---

### Task 7: skill + using-montage wiring + docs sync + final review

**Files:**
- Create: `skills/match-grade/SKILL.md`
- Modify: `skills/using-montage/SKILL.md`
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`
- Modify: `docs/specs/2026-07-26-colour-stage-design.md` (deferred → landed cross-ref)

- [ ] **Step 1: Write `skills/match-grade/SKILL.md`**

Frontmatter (mirror `skills/pacing/SKILL.md`) + body covering: what it is (montage §10, opt-in tone match across episodes); WHEN (after the cut settles — edit-plan + pacing — and only when episodes come from mixed cameras/light; a single-camera reel needs none); HOW (`bin/vg match_grade build --edl EDL.json --footage-root DIR [--eps 4.0] [--force]`); reading `MATCH.md`; the guarantees (touches only tone; respects a hand-authored pair unless `--force`; a within-eps episode stays byte-identical); the ordering landmine (run AFTER pacing — a pacing re-run regenerates EDL.json and wipes the tone); the honest limit (whole-frame midpoint, not the shipped crop). Resolve the runtime root via the recorded-root preamble the other runner skills use (see `skills/pacing/SKILL.md`).

- [ ] **Step 2: Wire `skills/using-montage/SKILL.md`**

Add `match-grade` to the conveyor order line as an optional stage after pacing:
`… → [music] → [pacing] → [match-grade] → [assemble-draft] → [titles] → edl_to_reel → …`,
with one sentence: optional, opt-in, runs after pacing settles the cut, authors tone consistency across episodes.

- [ ] **Step 3: Docs sync**

- `docs/build-status.md`: a DONE entry for the match-grade conductor (what landed, the files, the suite count after).
- `docs/pipeline-map.md`: note the match-grade stage under §10/colour (optional, after pacing).
- `CLAUDE.md`: two registry rows (design + plan) in the Quick Reference table, following the existing row style; and — since this closes the campaign — a one-line note in the colour row that the §10 conductor is no longer deferred.
- `docs/specs/2026-07-26-colour-stage-design.md`: in its **Deferred** list, mark the conductor bullet landed with a cross-ref to this slice's design (do not delete the text — annotate, per the house style).

- [ ] **Step 4: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green (prior baseline 1994 passed / 2 skipped, plus this slice's new tests; no golden moves — the conductor adds an opt-in stage and touches no existing render path).

- [ ] **Step 5: Commit**

```bash
git add skills/match-grade/SKILL.md skills/using-montage/SKILL.md docs/ CLAUDE.md
git commit -m "docs: match-grade conductor — SKILL, router wiring, registry, build-status"
```

- [ ] **Step 6: Final whole-slice review**

Dispatch a fresh code-quality reviewer over `git diff main...HEAD` against the design doc. Confirm: the five design invariants (§7) hold; the single-measure DRY fix landed (no double `measure_profile`); the byte-identical claim (within-eps → no pair) is real; scope held (tone only, opt-in, no golden moved). Fix any Critical/Important in a SEPARATE follow-up commit (never `--amend`).

---

## Self-Review

**Spec coverage:** design §2 core → Tasks 0-2; §3 driver → Tasks 3-4; §4 router+skill → Tasks 5,7; §5 honest limits → documented in skill (Task 7) + `conduct` docstring (Task 3); §6 testing → Tasks 0-6; §7 invariants → mutation checks in Tasks 0,1,2,3 + final review (Task 7); §8 deferred → untouched. All covered.

**Placeholder scan:** no TBDs. One measure pass only — `conduct` returns `(EDL, target, decisions)` and the decisions carry each `measured` profile, so `write_match`/`_report_md` never re-measure.

**Type consistency:** `Profile = tuple[float, float, float]` used throughout; `common_target`/`plan`/`conduct`/`write_match` signatures consistent across tasks; `ToneDecision` fields (`index/action/reason/measured/tone_src/tone_dst`) match between definition (Task 2), the plan() constructor calls (Task 2), driver apply (Task 3), and report (Task 4). `conduct`'s `(EDL, target, decisions)` return is unpacked consistently in the Task 3 unit tests, `write_match` (Task 4), and the integration proof (Task 6).
