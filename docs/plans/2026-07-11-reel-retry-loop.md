# Reel Retry Loop (Phase A.5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate the reel back half — a driver that loops `assemble → check_reel → auto-fix the culprit episode → reassemble → recheck` until the reel passes and delivers, or stops with a precise machine-readable finding.

**Architecture:** A pure decision module (`scripts/lib/reel_orchestration.py`, the §4.1 ladder one level up) under a thin deterministic shell (`scripts/build_reel.py`), mirroring the `orchestration.py`/`process_episode.py` split. The shell consumes a `ReelManifest` of already-locked episode clips (loop-1 produced them), reprocesses a flagged culprit by calling `process_episode()` with a per-episode `color_correct` override, and delivers once the whole-reel gate passes. Only `black`/`color_across_cuts` auto-close; `variety`/`length` stop-and-report.

**Tech Stack:** Python 3.13, ffmpeg/ffprobe (external), pytest. Reuses the shipped `assembly`, `check_reel`, `deliver`, `process_episode`, `color`, and `models` modules.

**Design spec:** [docs/specs/2026-07-11-reel-retry-loop-design.md](../specs/2026-07-11-reel-retry-loop-design.md). Read §3 (decision table), §4 (the color-correction rule — the one subtle part), and §5 (the driver) before starting.

**Standards:** [docs/coding-standards.md](../coding-standards.md) — fail loud WITH a remedy, imports at module top, every module-level def fully typed, config-specs raise `ValueError` in `__post_init__`, scripts run as modules (`pythonpath = .`). Landmines ([CLAUDE.md](../../CLAUDE.md)): `colorchannelmixer` only (`lutrgb` banned), even output dims, `-ss` after `-i`.

---

## File Structure

Six touches, the established thin-shell-over-lib split:

- **Modify** `scripts/lib/color.py` — add `corrected()`: compose an external per-channel factor onto grade gains, re-clamp.
- **Modify** `scripts/lib/models.py` — add `ReframeSpec.color_correct` field; add `ReelEpisode` + `ReelManifest` config-specs.
- **Modify** `scripts/reframe.py` — apply `spec.color_correct` after the base grade.
- **Modify** `scripts/check_reel.py` — the `color_across_cuts` fail `detail` carries `target` (reel median) + `culprit_mean`.
- **Modify** `scripts/process_episode.py` — new `color_correct=` param threaded into every `ReframeSpec` it builds.
- **Create** `scripts/lib/reel_orchestration.py` — `next_action()` + the `ReprocessItem`/`ReelAction` result types.
- **Create** `scripts/build_reel.py` — the driver shell + CLI.
- **Create** `tests/lib/test_reel_orchestration.py`, `tests/lib/test_build_reel.py`, `tests/integration/test_reel_retry.py`; extend `tests/lib/test_color.py`, `tests/lib/test_models.py`, `tests/lib/test_check_reel.py`, `tests/integration/test_process_episode.py`.

Dependency order: Task 0 (color/reframe seam) → 1 (check_reel detail) → 2 (ReelManifest) → 3 (decision core) → 4 (process_episode param) → 5 (driver) → 6 (real-ffmpeg) → 7 (docs).

---

## Task 0: `color.corrected()` + `ReframeSpec.color_correct` + reframe applies it

**Files:**
- Modify: `scripts/lib/color.py`
- Modify: `scripts/lib/models.py:381-411` (`ReframeSpec`)
- Modify: `scripts/reframe.py:177`
- Test: `tests/lib/test_color.py`, `tests/lib/test_models.py`, `tests/integration/test_reframe.py`

- [ ] **Step 1: Write the failing `color.corrected` test**

Append to `tests/lib/test_color.py`:

```python
def test_corrected_composes_and_leaves_unit_factor_alone():
    # base gains unchanged where the correction is 1.0; scaled where it is not
    assert c.corrected((1.0, 1.0, 1.0), (1.2, 1.0, 0.9)) == (1.2, 1.0, 0.9)


def test_corrected_clamps_high():
    # 1.4 * 1.4 = 1.96 → clamped to the grade ceiling HI=1.5
    assert c.corrected((1.4, 1.0, 1.0), (1.4, 1.0, 1.0)) == (1.5, 1.0, 1.0)


def test_corrected_clamps_low():
    # 0.8 * 0.8 = 0.64 → clamped to the grade floor LO=0.7
    assert c.corrected((0.8, 1.0, 1.0), (0.8, 1.0, 1.0)) == (0.7, 1.0, 1.0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/lib/test_color.py -v`
Expected: FAIL — `AttributeError: module 'scripts.lib.color' has no attribute 'corrected'`

- [ ] **Step 3: Implement `corrected`**

Append to `scripts/lib/color.py`:

```python
def corrected(gains: tuple[float, ...], correction: tuple[float, ...],
              lo: float = LO, hi: float = HI) -> tuple[float, ...]:
    """Compose an external per-channel correction onto base grade gains and
    re-clamp to [lo, hi] (design §4). The reel retry loop passes an absolute
    factor here to pull one episode's delivered mean toward the reel median;
    the clamp keeps the total correction inside the same soft band as the grade."""
    return tuple(max(lo, min(hi, g * corr)) for g, corr in zip(gains, correction))
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/lib/test_color.py -v`
Expected: PASS (all, including the three new)

- [ ] **Step 5: Write the failing `ReframeSpec.color_correct` test**

Append to `tests/lib/test_models.py`:

```python
def test_reframe_spec_accepts_color_correct():
    s = m.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                      color_means=(105.0, 122.0, 137.0), delivery=m.Delivery("native"),
                      color_correct=(1.1, 1.0, 0.9))
    assert s.color_correct == (1.1, 1.0, 0.9)


def test_reframe_spec_color_correct_defaults_none():
    s = m.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                      color_means=(105.0, 122.0, 137.0), delivery=m.Delivery("native"))
    assert s.color_correct is None


def test_reframe_spec_rejects_nonpositive_color_correct():
    with pytest.raises(ValueError, match="color_correct"):
        m.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                      color_means=(105.0, 122.0, 137.0), delivery=m.Delivery("native"),
                      color_correct=(0.0, 1.0, 1.0))


def test_reframe_spec_rejects_wrong_length_color_correct():
    with pytest.raises(ValueError, match="color_correct"):
        m.ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                      color_means=(105.0, 122.0, 137.0), delivery=m.Delivery("native"),
                      color_correct=(1.1, 1.0))
```

(`test_models.py` already imports `models as m` and `pytest`.)

- [ ] **Step 6: Run to verify it fails**

Run: `pytest tests/lib/test_models.py -k color_correct -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'color_correct'`

- [ ] **Step 7: Add the field + validation**

In `scripts/lib/models.py`, add the field to `ReframeSpec` (after `stabilize: bool = False`, line 390):

```python
    color_correct: tuple | None = None
```

And add this validation at the end of `ReframeSpec.__post_init__` (after the `stabilize` block, line 411):

```python
        if self.color_correct is not None and not _positive_seq(self.color_correct, 3):
            raise ValueError(f"ReframeSpec.color_correct must be 3 positive per-channel "
                             f"factors or None, got {self.color_correct!r}")
```

(`_positive_seq` already exists at `models.py:265`.)

- [ ] **Step 8: Run to verify it passes**

Run: `pytest tests/lib/test_models.py -k color_correct -v`
Expected: PASS (4 tests)

- [ ] **Step 9: Write the failing reframe-applies test**

Append to `tests/integration/test_reframe.py` (NOT marked integration — it mocks ffmpeg):

```python
def test_reframe_applies_color_correct_onto_the_grade(tmp_path, monkeypatch):
    # color_means == TARGET → base gains are all 1.0, so the emitted mixer shows
    # the color_correct factors verbatim. Proves the override reaches the filter.
    import json
    from scripts import reframe
    from scripts.lib.models import ReframeSpec, Delivery, LayoutSpec
    route = [dict(t=i / 30, x=900.0, y=540.0, w=140.0, h=320.0) for i in range(10)]
    rp = tmp_path / "r.json"; rp.write_text(json.dumps(route))
    cmd = {}
    monkeypatch.setattr(reframe, "_probe", lambda src: (1920, 1080, 30.0))
    monkeypatch.setattr(reframe.proc, "run", lambda c, **k: cmd.setdefault("v", c))
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=(105.0, 122.0, 137.0), delivery=Delivery("native"),
                       layout=LayoutSpec(mode="fill"), color_correct=(1.2, 1.0, 0.9))
    reframe.reframe(spec, "src.mp4", str(rp), str(tmp_path / "o.mp4"), str(tmp_path / "p.json"))
    joined = " ".join(cmd["v"])
    assert "colorchannelmixer=rr=1.200:gg=1.000:bb=0.900" in joined


def test_reframe_without_color_correct_is_unit_grade(tmp_path, monkeypatch):
    import json
    from scripts import reframe
    from scripts.lib.models import ReframeSpec, Delivery, LayoutSpec
    route = [dict(t=i / 30, x=900.0, y=540.0, w=140.0, h=320.0) for i in range(10)]
    rp = tmp_path / "r.json"; rp.write_text(json.dumps(route))
    cmd = {}
    monkeypatch.setattr(reframe, "_probe", lambda src: (1920, 1080, 30.0))
    monkeypatch.setattr(reframe.proc, "run", lambda c, **k: cmd.setdefault("v", c))
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=(105.0, 122.0, 137.0), delivery=Delivery("native"),
                       layout=LayoutSpec(mode="fill"))
    reframe.reframe(spec, "src.mp4", str(rp), str(tmp_path / "o.mp4"), str(tmp_path / "p.json"))
    assert "colorchannelmixer=rr=1.000:gg=1.000:bb=1.000" in " ".join(cmd["v"])
```

- [ ] **Step 10: Run to verify it fails**

Run: `pytest tests/integration/test_reframe.py -k color_correct -v`
Expected: FAIL — the first asserts `rr=1.200` but reframe emits `rr=1.000` (color_correct ignored)

- [ ] **Step 11: Apply the correction in reframe**

In `scripts/reframe.py`, replace line 177 (`gains = color.gains_for_means(spec.color_means)`) with:

```python
    gains = color.gains_for_means(spec.color_means)
    if spec.color_correct is not None:                # reel retry loop pulls one episode toward the reel median (§4)
        gains = color.corrected(gains, spec.color_correct)
```

- [ ] **Step 12: Run to verify it passes + full reframe suite**

Run: `pytest tests/integration/test_reframe.py -k color_correct -v && pytest tests/lib/test_color.py tests/lib/test_models.py -q`
Expected: PASS

- [ ] **Step 13: Commit**

```bash
git add scripts/lib/color.py scripts/lib/models.py scripts/reframe.py \
        tests/lib/test_color.py tests/lib/test_models.py tests/integration/test_reframe.py
git commit -m "$(cat <<'EOF'
feat: reframe applies an external color_correct factor onto the grade

The reel retry loop (Phase A.5) needs to pull one off-median episode toward
the reel's colour consensus. color.corrected() composes an absolute per-channel
factor onto the base grade gains and re-clamps to [LO,HI]; ReframeSpec grows a
validated color_correct field; reframe applies it after gains_for_means. None =
today's behaviour (base grade only).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 1: `check_reel` color fail carries `target` + `culprit_mean`

**Files:**
- Modify: `scripts/check_reel.py:130-131`
- Test: `tests/lib/test_check_reel.py`

The `color_across_cuts` `ReelFailure.detail` must carry the reel median (`target`) and the culprit span's delivered mean (`culprit_mean`) so the driver computes the correction ratio `med/d_i` with no re-probe (design §4).

- [ ] **Step 1: Write the failing test**

Append to `tests/lib/test_check_reel.py` (reuses the module-level `_Stub`):

```python
def test_color_fail_detail_carries_target_and_culprit_mean(tmp_path, monkeypatch):
    # ep0 grey ~(100,120,130), ep1 warm ~(160,120,130): the cut delta trips the
    # ceiling and ep1 (farther from the 2-value median) is the culprit. The driver
    # reads detail["target"] (reel median) and detail["culprit_mean"] to build med/d_i.
    _Stub([3.0, 3.0],
          means={2.95: (100.0, 120.0, 130.0), 3.05: (160.0, 120.0, 130.0),
                 1.5: (100.0, 120.0, 130.0), 4.5: (160.0, 120.0, 130.0)}
          ).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0, color_delta_max=12.0),
                         str(tmp_path / "r.json"))
    f = [x for x in rep.fail_reasons if x.check == "color_across_cuts"][0]
    assert f.episode_idx == 1
    # median of the two span means, per channel
    assert f.detail["target"] == [130.0, 120.0, 130.0]
    # ep1 (the culprit) span mean
    assert f.detail["culprit_mean"] == [160.0, 120.0, 130.0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/lib/test_check_reel.py -k target_and_culprit -v`
Expected: FAIL — `KeyError: 'target'` (detail has only `cut`/`delta`)

- [ ] **Step 3: Add target + culprit_mean to the fail detail**

In `scripts/check_reel.py`, replace the color `fails.append(...)` (lines 130-131):

```python
                fails.append(ReelFailure("color_across_cuts", "reprocess", culprit,
                                         {"cut": i, "delta": round(delta, 2),
                                          "target": [round(x, 2) for x in median],
                                          "culprit_mean": [round(x, 2) for x in span_means[culprit]]}))
```

- [ ] **Step 4: Run to verify it passes + the whole check_reel suite**

Run: `pytest tests/lib/test_check_reel.py -q`
Expected: PASS (the new test + all existing — the extra detail keys don't disturb the other assertions)

- [ ] **Step 5: Commit**

```bash
git add scripts/check_reel.py tests/lib/test_check_reel.py
git commit -m "$(cat <<'EOF'
feat: check_reel colour fail carries the reel median + culprit mean

The Phase A.5 driver computes the correction ratio med/d_i for a reprocess. Put
both operands in the machine-readable fail detail — target (the reel median RGB
already computed for attribution) and culprit_mean (the flagged span's delivered
mean) — so the driver never re-probes the master.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `ReelEpisode` + `ReelManifest` config-specs

**Files:**
- Modify: `scripts/lib/models.py` (after `ReelReport`, end of file)
- Test: `tests/lib/test_models.py`

The typed input to `build_reel` (design §2): an ordered list of `{episode manifest, locked clip, frozen route}` plus the reel params. Validates on construction; `check_spec` yields the existing `ReelCheckSpec`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_models.py`:

```python
def _reel_dict(**over):
    d = dict(episodes=[{"manifest": {"segment": "s0.mp4"}, "clip": "c0.mp4", "route": "r0.json"},
                       {"manifest": {"segment": "s1.mp4"}, "clip": "c1.mp4", "route": "r1.json"}],
             target_dur=6.0, variety_min=4, color_delta_max=10.0, cap=3, changelog="cut")
    d.update(over)
    return d


def test_reel_manifest_from_dict_round_trip():
    rm = m.ReelManifest.from_dict(_reel_dict())
    assert len(rm.episodes) == 2
    assert rm.episodes[0].clip == "c0.mp4" and rm.episodes[0].route == "r0.json"
    assert rm.episodes[1].manifest == {"segment": "s1.mp4"}
    cs = rm.check_spec
    assert isinstance(cs, m.ReelCheckSpec)
    assert cs.target_dur == 6.0 and cs.variety_min == 4 and cs.color_delta_max == 10.0


def test_reel_manifest_defaults():
    rm = m.ReelManifest.from_dict(dict(
        episodes=[{"manifest": {}, "clip": "c.mp4", "route": "r.json"}], target_dur=3.0))
    assert rm.cap == 3 and rm.changelog == ""
    assert rm.check_spec.variety_min == 8 and rm.check_spec.color_delta_max == 12.0


def test_reel_manifest_rejects_empty_episodes():
    with pytest.raises(ValueError, match="episodes is empty"):
        m.ReelManifest.from_dict(_reel_dict(episodes=[]))


def test_reel_manifest_rejects_missing_clip():
    with pytest.raises(ValueError, match=r"episodes\[0\].clip"):
        m.ReelManifest.from_dict(_reel_dict(
            episodes=[{"manifest": {}, "clip": "", "route": "r.json"}]))


def test_reel_manifest_rejects_missing_route():
    with pytest.raises(ValueError, match=r"episodes\[0\].route"):
        m.ReelManifest.from_dict(_reel_dict(
            episodes=[{"manifest": {}, "clip": "c.mp4", "route": ""}]))


def test_reel_manifest_rejects_bad_cap():
    with pytest.raises(ValueError, match="cap"):
        m.ReelManifest.from_dict(_reel_dict(cap=0))
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/lib/test_models.py -k reel_manifest -v`
Expected: FAIL — `AttributeError: module 'scripts.lib.models' has no attribute 'ReelManifest'`

- [ ] **Step 3: Implement the config-specs**

Append to `scripts/lib/models.py` (after `ReelReport`). `json`, `Path`, `dataclass`, `field` are already imported at the top of the file:

```python
@dataclass(frozen=True)
class ReelEpisode:
    """One entry in a ReelManifest: the per-episode manifest (so a reprocess can
    rebuild it), the locked clip loop-1 produced, and the frozen route.json (a
    reprocess reuses it — colour/black fixes never move the track)."""
    manifest: dict
    clip: str
    route: str


@dataclass
class ReelManifest:
    """Typed input to build_reel (design §2). Episodes are already locked by
    loop-1 (process_episode); build_reel loops assemble/check/reprocess over them.
    Validates hard — an empty list or a missing clip/route is a caller bug."""
    episodes: list
    target_dur: float
    variety_min: int = 8
    color_delta_max: float = 12.0
    cap: int = 3
    changelog: str = ""

    def __post_init__(self) -> None:
        if not self.episodes:
            raise ValueError("ReelManifest.episodes is empty — a reel needs at least one "
                             "locked episode; produce them with process_episode first")
        for k, e in enumerate(self.episodes):
            if not isinstance(e, ReelEpisode):
                raise ValueError(f"ReelManifest.episodes[{k}] must be a ReelEpisode")
            if not (isinstance(e.clip, str) and e.clip):
                raise ValueError(f"ReelManifest.episodes[{k}].clip is empty — the locked clip path")
            if not (isinstance(e.route, str) and e.route):
                raise ValueError(f"ReelManifest.episodes[{k}].route is empty — the frozen route.json "
                                 "path; a reprocess reuses it to skip tracking")
        if not isinstance(self.target_dur, (int, float)) or self.target_dur <= 0:
            raise ValueError(f"ReelManifest.target_dur must be a positive number, got {self.target_dur!r}")
        if isinstance(self.cap, bool) or not isinstance(self.cap, int) or self.cap < 1:
            raise ValueError(f"ReelManifest.cap must be an int >= 1, got {self.cap!r}")

    @property
    def check_spec(self) -> ReelCheckSpec:
        return ReelCheckSpec(self.target_dur, self.variety_min, self.color_delta_max)

    @classmethod
    def from_dict(cls, d: dict) -> "ReelManifest":
        eps = [ReelEpisode(manifest=_load_manifest(e["manifest"]), clip=e["clip"], route=e["route"])
               for e in d["episodes"]]
        return cls(episodes=eps, target_dur=d["target_dur"],
                   variety_min=d.get("variety_min", 8),
                   color_delta_max=d.get("color_delta_max", 12.0),
                   cap=d.get("cap", 3), changelog=d.get("changelog", ""))

    @classmethod
    def from_json(cls, path: str | Path) -> "ReelManifest":
        return cls.from_dict(json.loads(Path(path).read_text()))


def _load_manifest(m: dict | str) -> dict:
    """A reel-manifest episode's `manifest` is either an inline dict or a path to
    an episode manifest JSON (both forms are valid; §2)."""
    return m if isinstance(m, dict) else json.loads(Path(m).read_text())
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/lib/test_models.py -k reel_manifest -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "$(cat <<'EOF'
feat: ReelManifest / ReelEpisode config-specs — the build_reel input

The typed reel-loop input (design §2): ordered locked episodes (manifest + clip
+ frozen route) plus reel params. Validates hard (empty list / missing clip or
route / bad cap raise with a remedy); check_spec yields the existing
ReelCheckSpec. An episode's manifest may be inline or a path.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `reel_orchestration.next_action` — the decision core

**Files:**
- Create: `scripts/lib/reel_orchestration.py`
- Test: `tests/lib/test_reel_orchestration.py`

Pure, deterministic, no ffmpeg — the reel-level twin of `orchestration.escalation` (design §3). Maps a `check_reel` report's `fail_reasons` to exactly one `ReelAction`.

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/test_reel_orchestration.py`:

```python
from scripts.lib import reel_orchestration as ro
from scripts.lib.models import ReelFailure


def _color(idx, target, culprit):
    return ReelFailure("color_across_cuts", "reprocess", idx,
                       {"target": target, "culprit_mean": culprit})


def test_no_failures_delivers():
    a = ro.next_action([], {}, cap=3)
    assert a.kind == "deliver"


def test_black_fail_reprocesses_with_no_correction():
    a = ro.next_action([ReelFailure("black", "reprocess", 1, {"t": 4.0})], {}, cap=3)
    assert a.kind == "reprocess"
    assert len(a.reprocess) == 1
    assert a.reprocess[0].idx == 1 and a.reprocess[0].color_correct is None


def test_color_fail_reprocesses_with_the_ratio():
    a = ro.next_action([_color(1, [120.0, 120.0, 120.0], [150.0, 120.0, 100.0])], {}, cap=3)
    item = a.reprocess[0]
    assert item.idx == 1
    # per-channel med/d_i
    assert item.color_correct[0] == 120.0 / 150.0
    assert item.color_correct[1] == 1.0
    assert item.color_correct[2] == 120.0 / 100.0


def test_variety_escalates_to_edit_plan():
    f = ReelFailure("variety", "edit-plan", 1, {"pair": [0, 1], "distance": 2})
    a = ro.next_action([f], {}, cap=3)
    assert a.kind == "escalate"
    assert a.finding["escalate_to"] == "edit-plan" and a.finding["episode_idx"] == 1


def test_length_escalates_to_pacing():
    f = ReelFailure("length", "pacing", None, {"dur": 7.0, "target": 6.0})
    a = ro.next_action([f], {}, cap=3)
    assert a.kind == "escalate" and a.finding["escalate_to"] == "pacing"


def test_capped_episode_escalates():
    # episode 1 already reprocessed `cap` times → escalate, don't loop forever
    a = ro.next_action([_color(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0])],
                       {1: 3}, cap=3)
    assert a.kind == "escalate"
    assert a.finding["reason"] == "reprocess-capped" and a.finding["episode_idx"] == 1


def test_escalate_beats_reprocess_in_a_mixed_round():
    # a fixable colour fail AND an unfixable variety fail in the same report →
    # escalate immediately (fixing colour won't fix the near-duplicate)
    fails = [_color(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]),
             ReelFailure("variety", "edit-plan", 2, {"distance": 1})]
    a = ro.next_action(fails, {}, cap=3)
    assert a.kind == "escalate" and a.finding["check"] == "variety"


def test_two_distinct_culprits_batch():
    fails = [ReelFailure("black", "reprocess", 0, {"t": 1.0}),
             _color(2, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0])]
    a = ro.next_action(fails, {}, cap=3)
    assert a.kind == "reprocess"
    assert sorted(i.idx for i in a.reprocess) == [0, 2]


def test_black_and_colour_same_episode_dedupe_to_colour():
    # a colour reprocess also re-encodes, so it subsumes the bare black re-encode
    fails = [ReelFailure("black", "reprocess", 1, {"t": 1.0}),
             _color(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0])]
    a = ro.next_action(fails, {}, cap=3)
    assert len(a.reprocess) == 1
    assert a.reprocess[0].idx == 1 and a.reprocess[0].color_correct is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/lib/test_reel_orchestration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.reel_orchestration'`

- [ ] **Step 3: Implement the module**

Create `scripts/lib/reel_orchestration.py`:

```python
"""Pure reel-loop decisions (design §3, §4) — the montage §4.1 escalation ladder
one level up from process-episode. `next_action` maps a check_reel report's
`fail_reasons` to exactly one action; build_reel (the shell) executes it. No
ffmpeg, no state: the driver owns per-episode attempt counts and the compounded
colour factor. Mirrors scripts/lib/orchestration.py."""
from dataclasses import dataclass

from scripts.lib.models import ReelFailure

_REPROCESS_CLASS = ("black", "color_across_cuts")


@dataclass(frozen=True)
class ReprocessItem:
    """Reprocess one episode. color_correct is the per-round ratio med/d_i for a
    colour fail (the driver compounds + clamps it), or None for a black clean
    re-encode."""
    idx: int
    color_correct: tuple | None


@dataclass(frozen=True)
class ReelAction:
    kind: str                          # "deliver" | "reprocess" | "escalate"
    reprocess: tuple = ()              # tuple[ReprocessItem]
    finding: dict | None = None


def _correction(f: ReelFailure) -> tuple:
    """Per-channel per-round ratio med/d_i from the colour fail detail (§4). Raw
    ratio only — the driver compounds onto the stored factor and clamps."""
    target = f.detail["target"]
    culprit = f.detail["culprit_mean"]
    return tuple(t / d if d > 0 else 1.0 for t, d in zip(target, culprit))


def next_action(fail_reasons: list, attempts: dict, cap: int) -> ReelAction:
    """One decision for the whole reel (design §3). Escalate wins the round: any
    non-auto-fixable or capped failure returns Escalate immediately, so we never
    spend reprocess rounds on a reel that also carries an unfixable fault."""
    if not fail_reasons:
        return ReelAction("deliver")
    items: dict = {}                   # idx → ReprocessItem; colour wins over a bare black re-encode
    for f in fail_reasons:
        if f.check not in _REPROCESS_CLASS:
            return ReelAction("escalate", finding={
                "reason": "not-auto-fixable", "check": f.check,
                "episode_idx": f.episode_idx, "escalate_to": f.escalate_to,
                "detail": f.detail})
        if attempts.get(f.episode_idx, 0) >= cap:
            return ReelAction("escalate", finding={
                "reason": "reprocess-capped", "check": f.check, "episode_idx": f.episode_idx,
                "escalate_to": "edit-plan",
                "detail": (f"episode {f.episode_idx} still fails {f.check} after {cap} "
                           "reprocesses — the source window or grade is wrong; fix the segment/EDL")})
        corr = _correction(f) if f.check == "color_across_cuts" else None
        if f.episode_idx not in items or corr is not None:
            items[f.episode_idx] = ReprocessItem(f.episode_idx, corr)
    return ReelAction("reprocess", reprocess=tuple(items[k] for k in sorted(items)))
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/lib/test_reel_orchestration.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/reel_orchestration.py tests/lib/test_reel_orchestration.py
git commit -m "$(cat <<'EOF'
feat: reel_orchestration.next_action — the reel retry decision core

Pure §4.1 ladder one level up: maps check_reel fail_reasons to Deliver |
Reprocess[...] | Escalate. Only black/colour auto-close; variety/length and a
capped episode escalate with a precise finding. Escalate wins a mixed round.
Colour reprocess carries the raw med/d_i ratio; the driver compounds it.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `process_episode` accepts `color_correct`

**Files:**
- Modify: `scripts/process_episode.py:36-38` (signature), `:118-120` (ReframeSpec build)
- Test: `tests/integration/test_process_episode.py`

The driver passes a per-episode colour override to a reprocess; `process_episode` threads it into every `ReframeSpec` it builds (constant across retry attempts, like `layout`).

- [ ] **Step 1: Add the capture to the shared engine stub**

In `tests/integration/test_process_episode.py`, inside `_stub_engine`'s `fake_reframe`, add one line (after `calls["reframe_canvas"] = spec.canvas`):

```python
        calls["reframe_color_correct"] = spec.color_correct
```

- [ ] **Step 2: Write the failing test**

Append to `tests/integration/test_process_episode.py`:

```python
def test_color_correct_is_threaded_into_the_reframe_spec(monkeypatch, tmp_path):
    calls = _stub_engine(monkeypatch, tmp_path)
    result = pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path),
                                color_correct=(1.2, 1.0, 0.9))
    assert result["status"] == "mechanical_pass"
    assert calls["reframe_color_correct"] == (1.2, 1.0, 0.9)


def test_color_correct_defaults_to_none(monkeypatch, tmp_path):
    calls = _stub_engine(monkeypatch, tmp_path)
    pe.process_episode(_manifest(tmp_path), project_dir=str(tmp_path))
    assert calls["reframe_color_correct"] is None
```

(`_stub_engine` returns its `calls` dict — confirm it ends with `return calls`; if it does not, add `return calls` to the fixture.)

- [ ] **Step 3: Run to verify it fails**

Run: `pytest tests/integration/test_process_episode.py -k color_correct -v`
Expected: FAIL — `TypeError: process_episode() got an unexpected keyword argument 'color_correct'`

- [ ] **Step 4: Add the param + thread it**

In `scripts/process_episode.py`, add the param to the signature (after `project=...`, line 38):

```python
def process_episode(manifest_dict: dict, project_dir: str | Path, route_path: str | None = None,
                    max_attempts: int = 3,
                    project: ProjectConfig | str | Path | None = None,
                    color_correct: tuple | None = None) -> dict:
```

And add `color_correct=color_correct` to the `ReframeSpec(...)` built in the retry loop (lines 118-120):

```python
        rspec = ReframeSpec(composition=m.composition, grid=m.grid, canvas=m.canvas,
                            color_means=m.color_means, delivery=delivery, layout=lspec,
                            max_speed=params["max_speed"], color_correct=color_correct)
```

- [ ] **Step 5: Run to verify it passes + the whole process_episode suite**

Run: `pytest tests/integration/test_process_episode.py -q`
Expected: PASS (the two new + all existing — the default None preserves current behaviour)

- [ ] **Step 6: Commit**

```bash
git add scripts/process_episode.py tests/integration/test_process_episode.py
git commit -m "$(cat <<'EOF'
feat: process_episode threads a color_correct override into reframe

The reel retry loop reprocesses an off-median episode with a per-channel colour
correction. Add an optional color_correct param, threaded into every ReframeSpec
the retry loop builds (constant across attempts, like layout). None = unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `build_reel.py` — the driver shell + CLI

**Files:**
- Create: `scripts/build_reel.py`
- Test: `tests/lib/test_build_reel.py`

The deterministic shell (design §5). All stages are mocked here — this task proves the loop *logic* (deliver / reprocess+compound / escalate / propagate). Real ffmpeg is Task 6.

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/test_build_reel.py`:

```python
import pytest
from scripts import build_reel
from scripts.lib.assembly import StreamInfo
from scripts.lib.models import (ReelEpisode, ReelManifest, ReelReport, ReelFailure,
                                CheckResult)


def _rm(cap=3, n=2):
    eps = [ReelEpisode(manifest={"segment": f"s{i}.mp4"}, clip=f"c{i}.mp4", route=f"r{i}.json")
           for i in range(n)]
    return ReelManifest(episodes=eps, target_dur=6.0, color_delta_max=12.0, cap=cap)


def _pass():
    return ReelReport(checks={"length": CheckResult("length", True, {})}, episode_count=2)


def _color_fail(idx, target, culprit):
    return ReelReport(
        checks={"color_across_cuts": CheckResult("color_across_cuts", False, {})},
        fail_reasons=[ReelFailure("color_across_cuts", "reprocess", idx,
                                  {"target": target, "culprit_mean": culprit})],
        episode_count=2)


def _wire(monkeypatch, reports, pe_results=None):
    """Feed check_reel.run a queue of canned reports; record deliver + the
    color_correct passed to each process_episode reprocess."""
    seen = {"deliver": [], "reprocess": []}
    rq = list(reports)
    monkeypatch.setattr(build_reel.assembly, "probe_stream",
                        lambda p: StreamInfo(1080, 1920, 30.0, "yuv420p", "h264"))
    monkeypatch.setattr(build_reel.assembly, "assemble", lambda clips, dims, fps, out: out)
    monkeypatch.setattr(build_reel.check_reel, "run", lambda m, e, s, o: rq.pop(0))
    monkeypatch.setattr(build_reel.deliver, "deliver",
                        lambda m, prof, od, cl, rep: seen["deliver"].append(od) or f"{od}/REEL_v1.mp4")
    results = iter(pe_results or [])

    def fake_pe(manifest, project_dir, route_path=None, color_correct=None):
        seen["reprocess"].append({"correct": color_correct, "route": route_path})
        return next(results, {"status": "mechanical_pass", "clip": project_dir + "/ep.mp4"})
    monkeypatch.setattr(build_reel.process_episode, "process_episode", fake_pe)
    return seen


def test_clean_reel_delivers_without_reprocess(monkeypatch, tmp_path):
    seen = _wire(monkeypatch, [_pass()])
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert res["output"].endswith("REEL_v1.mp4")
    assert seen["reprocess"] == []          # no fix needed


def test_color_fail_then_pass_reprocesses_then_delivers(monkeypatch, tmp_path):
    # round 0: ep1 warm → reprocess with med/d_i; round 1: passes → deliver
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]), _pass()]
    seen = _wire(monkeypatch, reports)
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert len(seen["reprocess"]) == 1
    assert seen["reprocess"][0]["correct"][0] == pytest.approx(120.0 / 150.0)
    assert seen["reprocess"][0]["route"] == "r1.json"     # frozen route reused


def test_color_correct_compounds_across_rounds(monkeypatch, tmp_path):
    # two failing rounds then pass: the 2nd reprocess factor is compounded onto
    # the 1st and clamped — the reversion bug (per-round-relative) would NOT compound
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]),   # ratio1 = .8
               _color_fail(1, [120.0, 120.0, 120.0], [130.0, 120.0, 120.0]),   # ratio2 = .923
               _pass()]
    seen = _wire(monkeypatch, reports)
    build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    r0 = seen["reprocess"][0]["correct"][0]
    r1 = seen["reprocess"][1]["correct"][0]
    assert r0 == pytest.approx(0.8)
    assert r1 == pytest.approx(0.8 * (120.0 / 130.0))     # compounded, not 120/130 alone


def test_variety_fail_stops_and_reports_without_delivering(monkeypatch, tmp_path):
    rep = ReelReport(checks={"variety": CheckResult("variety", False, {})},
                     fail_reasons=[ReelFailure("variety", "edit-plan", 1, {"distance": 1})],
                     episode_count=2)
    seen = _wire(monkeypatch, [rep])
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["escalate_to"] == "edit-plan"
    assert seen["deliver"] == []            # a failed reel is never delivered


def test_reprocess_failure_propagates(monkeypatch, tmp_path):
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0])]
    seen = _wire(monkeypatch, reports,
                 pe_results=[{"status": "needs_input", "problems": ["bad manifest"]}])
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "reprocess-failed" and res["finding"]["episode_idx"] == 1


def test_capped_episode_escalates(monkeypatch, tmp_path):
    # cap=1: round 0 reprocesses ep1 (attempts→1); round 1 still fails → capped escalate
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]),
               _color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0])]
    seen = _wire(monkeypatch, reports)
    res = build_reel.build_reel(_rm(cap=1), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "reprocess-capped"
    assert seen["deliver"] == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/lib/test_build_reel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.build_reel'`

- [ ] **Step 3: Implement the driver**

Create `scripts/build_reel.py`:

```python
"""Reel retry-loop driver (design §5, Phase A.5). Consumes a ReelManifest of
locked episode clips and loops assemble → check_reel → reprocess the culprit via
process_episode → until the reel passes and delivers, or stops with a precise
machine-readable finding. Mirrors process_episode.py: the editorial judgment ran
per-episode in loop-1; this shell owns only the mechanical reel loop.
Deterministic — a reprocess reuses the episode's frozen route, so the only thing
that changes between rounds is the compounded colour factor."""
import argparse
import json
from pathlib import Path

from scripts import check_reel, deliver, process_episode
from scripts.lib import assembly, reel_orchestration
from scripts.lib.color import LO, HI
from scripts.lib.models import ReelManifest, REEL_H264


def _compound(prev: tuple, ratio: tuple) -> tuple:
    """Compound a per-round colour ratio onto the stored absolute factor and
    clamp to the grade's soft band [LO, HI] (design §4). Compounding (not
    per-round-relative) is what makes the correction converge instead of revert."""
    return tuple(max(LO, min(HI, p * r)) for p, r in zip(prev, ratio))


def build_reel(rm: ReelManifest, out_dir: str, work_dir: str) -> dict:
    """Drive rm's locked clips to a delivered reel or a stop-and-report finding."""
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    clips = [e.clip for e in rm.episodes]
    si = assembly.probe_stream(clips[0])          # actual delivered dims/fps (episodes uniform by construction)
    dims, fps = (si.w, si.h), si.fps
    master = str(Path(work_dir) / "master.mp4")
    report_path = str(Path(work_dir) / "reel_report.json")
    attempts: dict = {}
    cc: dict = {}
    for _ in range(rm.cap * len(rm.episodes) + 1):   # defensive bound; next_action is the real terminator
        assembly.assemble(clips, dims, fps, master)
        report = check_reel.run(master, clips, rm.check_spec, report_path)
        action = reel_orchestration.next_action(report.fail_reasons, attempts, rm.cap)
        if action.kind == "deliver":
            out = deliver.deliver(master, REEL_H264, out_dir, rm.changelog, report)
            return {"status": "delivered", "output": out, "report": report.to_dict()}
        if action.kind == "escalate":
            return {"status": "stop_and_report", "finding": action.finding,
                    "report": report.to_dict(), "attempts": dict(attempts)}
        for item in action.reprocess:                # sequential — one process_episode saturates the box
            if item.color_correct is not None:
                cc[item.idx] = _compound(cc.get(item.idx, (1.0, 1.0, 1.0)), item.color_correct)
            epdir = str(Path(work_dir) / f"ep{item.idx}")
            res = process_episode.process_episode(
                rm.episodes[item.idx].manifest, epdir,
                route_path=rm.episodes[item.idx].route, color_correct=cc.get(item.idx))
            if res["status"] != "mechanical_pass":
                return {"status": "stop_and_report",
                        "finding": {"reason": "reprocess-failed", "episode_idx": item.idx,
                                    "sub_status": res["status"]},
                        "sub": res, "attempts": dict(attempts)}
            clips[item.idx] = res["clip"]
            attempts[item.idx] = attempts.get(item.idx, 0) + 1
    return {"status": "stop_and_report",             # defensive: next_action escalates a capped reel first
            "finding": {"reason": "reel-cap-exhausted"}, "attempts": dict(attempts)}


def main() -> None:
    ap = argparse.ArgumentParser(description="drive the reel retry loop → delivered reel | stop-and-report")
    ap.add_argument("reel_manifest", help="path to a reel manifest JSON (design §2)")
    ap.add_argument("--out-dir", required=True, help="delivery dir for REEL_v{n}")
    ap.add_argument("--work-dir", required=True, help="scratch for master/report + per-episode reprocess")
    a = ap.parse_args()
    rm = ReelManifest.from_json(a.reel_manifest)
    result = build_reel(rm, a.out_dir, a.work_dir)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "delivered" else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/lib/test_build_reel.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/build_reel.py tests/lib/test_build_reel.py
git commit -m "$(cat <<'EOF'
feat: build_reel driver — assemble/check/reprocess loop + CLI

The Phase A.5 shell (design §5). Consumes a ReelManifest of locked clips, loops
assemble → check_reel → next_action, reprocesses a culprit via process_episode
with a compounded per-episode colour correction (frozen route reused), and
delivers on pass. Escalate / reprocess-failure / capped all stop-and-report with
a machine-readable finding; a failed reel is never delivered.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Real-ffmpeg proof — color moves pixels, build_reel delivers

**Files:**
- Create: `tests/integration/test_reel_retry.py`

Two `@pytest.mark.integration` tests (design §6). Following the Phase A golden's precedent (`test_reel_backhalf.py` builds clips via the real `reframe` encoder, not the whole `process_episode`), these keep the stage golden robust; the reprocess-loop logic is already unit-proven in Task 5.

- [ ] **Step 1: Write the two tests**

Create `tests/integration/test_reel_retry.py`:

```python
"""Real-ffmpeg proof for the reel retry loop (design §6). (A) color_correct moves
real pixels toward the target; (B) build_reel wires probe → assemble → check_reel
→ deliver end-to-end on real files. Clips are built with the real reframe encoder,
matching test_reel_backhalf.py's precedent."""
import json
import pytest
from scripts import build_reel, check_reel, reframe
from scripts.lib import assembly, proc
from scripts.lib.models import (Delivery, LayoutSpec, ReframeSpec, ReelEpisode, ReelManifest)


def _tinted(sample_clip, tmp):
    """A warm copy of the grey sample clip — its red channel is boosted so its
    delivered mean sits off any neutral reference."""
    out = str(tmp / "warm.mp4")
    proc.run(["ffmpeg", "-y", "-i", str(sample_clip),
              "-vf", "colorchannelmixer=rr=1.4", "-pix_fmt", "yuv420p",
              "-c:v", "libx264", "-crf", "18", "-an", out])
    return out


def _reframe(src, tmp, x_const, name, color_correct=None):
    route = [dict(t=i / 10, x=float(x_const), y=540.0, w=140.0, h=320.0) for i in range(30)]
    rp = tmp / f"{name}.route.json"; rp.write_text(json.dumps(route))
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=(105.0, 122.0, 137.0), delivery=Delivery("native"),
                       layout=LayoutSpec(mode="fill"), color_correct=color_correct)
    out = str(tmp / f"{name}.mp4")
    reframe.reframe(spec, str(src), str(rp), out, str(tmp / f"{name}.path.meta.json"))
    return out


@pytest.mark.integration
def test_color_correct_pulls_delivered_mean_toward_target(tmp_path, sample_clip):
    warm = _tinted(sample_clip, tmp_path)
    uncorrected = _reframe(warm, tmp_path, 900, "u")
    corrected = _reframe(warm, tmp_path, 900, "c", color_correct=(0.75, 1.0, 1.0))
    r_u = check_reel._frame_mean(uncorrected, 1.0)[0]
    r_c = check_reel._frame_mean(corrected, 1.0)[0]
    assert r_c < r_u - 5          # the correction visibly lowered the red channel on real pixels


@pytest.mark.integration
def test_build_reel_delivers_a_passing_reel(tmp_path, sample_clip):
    # two uniform clips off the same source → pass on the first assemble → deliver,
    # no reprocess (proves the driver's real probe/assemble/check/deliver wiring)
    ep0 = _reframe(sample_clip, tmp_path, 645, "ep0")
    ep1 = _reframe(sample_clip, tmp_path, 1045, "ep1")
    target = sum(check_reel._probe_dur(e) for e in (ep0, ep1))
    rm = ReelManifest(
        episodes=[ReelEpisode(manifest={"segment": str(sample_clip)}, clip=ep0,
                              route=str(tmp_path / "ep0.route.json")),
                  ReelEpisode(manifest={"segment": str(sample_clip)}, clip=ep1,
                              route=str(tmp_path / "ep1.route.json"))],
        target_dur=target, variety_min=4, changelog="retry golden")
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert res["output"].endswith("REEL_v1.mp4")
    v1 = res["output"]
    assert (assembly.probe_stream(v1).w % 2 == 0) and (assembly.probe_stream(v1).h % 2 == 0)
    assert "- v1 |" in (tmp_path / "out" / "VERSIONS.md").read_text()
```

- [ ] **Step 2: Run to verify the tests pass on real ffmpeg**

Run: `pytest tests/integration/test_reel_retry.py -v -m integration`
Expected: PASS (2 tests).
- Test A tuning: if `r_c < r_u - 5` is too tight/loose, adjust the `color_correct` (stronger → 0.7) or the margin; the invariant that must hold is `r_c < r_u` (the correction lowered red). `rr=1.4` on the grey 0x30=48 gives warm red ≈67, so a 0.75 factor drops it well clear of the margin.
- Test B: if `variety` fails (the two crops too similar), widen the `x_const` gap or lower `variety_min` — mirror the value `test_reel_backhalf.py` uses (`variety_min=4`).

- [ ] **Step 3: Run the whole suite to confirm no regression**

Run: `pytest -q`
Expected: PASS (all — prior count + the new unit and integration tests). Note the integration count grows by 2.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_reel_retry.py
git commit -m "$(cat <<'EOF'
test: real-ffmpeg proof for the reel retry loop

(A) color_correct measurably lowers a warm clip's delivered red channel on real
pixels — §4's composition works, not just the pure-gain unit test. (B) build_reel
drives probe → assemble → check_reel → deliver end-to-end on real files and writes
REEL_v1.mp4. The reprocess-loop logic is unit-proven in test_build_reel.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Docs sync + registry + final review

**Files:**
- Modify: `docs/build-status.md`, `CLAUDE.md`, `docs/specs/2026-07-10-reel-back-half-design.md`, `docs/plans/2026-07-11-reel-retry-loop.md`

- [ ] **Step 1: Update `docs/build-status.md`**

Add a Done entry (after the reel-back-half entry) naming the branch `feat/reel-retry-loop`, the commit range, the final test count, and what shipped: `color.corrected` + `ReframeSpec.color_correct`; `check_reel` colour detail (`target`/`culprit_mean`); `ReelEpisode`/`ReelManifest`; `reel_orchestration.next_action`; `process_episode` `color_correct`; `build_reel` driver + CLI; the two real-ffmpeg proofs. Change the **Next action** from "Phase A.5" to Phase B (music spine — unblocks `beat`/`loudness`) and, if desired, the deferred reel-loop items (variety/length auto-fix, parallel reprocess, resumability).

- [ ] **Step 2: Update `CLAUDE.md` Quick Reference**

Add two rows to the table:

```markdown
| Reel retry loop design | [2026-07-11-reel-retry-loop-design.md](docs/specs/2026-07-11-reel-retry-loop-design.md) | Phase A.5: build_reel driver (assemble→check→reprocess→deliver), reel_orchestration ladder, delivered-space color_correct convergence. |
| Reel retry loop plan | [2026-07-11-reel-retry-loop.md](docs/plans/2026-07-11-reel-retry-loop.md) | Tasks 0–7: color_correct seam, check_reel detail, ReelManifest, next_action, build_reel, real-ffmpeg proofs. |
```

- [ ] **Step 3: Mark the reel-back-half §6 sketch as built**

In `docs/specs/2026-07-10-reel-back-half-design.md`, at the top of §6 (line 182), add a one-line note that Phase A.5 is now built and point to the new design:

```markdown
> **Built (2026-07-11)** — see [2026-07-11-reel-retry-loop-design.md](2026-07-11-reel-retry-loop-design.md); the sketch below is the original outline.
```

- [ ] **Step 4: Mark this plan COMPLETE**

At the top of `docs/plans/2026-07-11-reel-retry-loop.md`, add `**STATUS: COMPLETE (2026-07-11)**` under the header, and tick every `- [ ]` checkbox to `- [x]`.

- [ ] **Step 5: Verify the whole suite green**

Run: `pytest -q`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add docs/build-status.md CLAUDE.md docs/specs/2026-07-10-reel-back-half-design.md docs/plans/2026-07-11-reel-retry-loop.md
git commit -m "$(cat <<'EOF'
docs: sync build-status, registry, reel-back-half §6 for Phase A.5

Record the reel retry loop as built; add the design+plan registry rows; point
the reel-back-half §6 sketch at the shipped design; mark the plan COMPLETE.
Next action → Phase B (music spine).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Final whole-slice review**

Dispatch a final code-review subagent over the whole branch diff (`git diff main...feat/reel-retry-loop`) against the design spec. Focus: the compounding-vs-reverting colour math (§4), the escalate-wins ordering (§3), no silent pass (a failed reel never reaches `deliver`), landmines (colorchannelmixer only, even dims), and that every new module-level def is typed. Address findings before finishing.

---

## Self-Review (against the spec)

**Spec coverage:** §1 files → Tasks 0-5; §2 ReelManifest → Task 2; §3 decision table → Task 3 (every row has a test); §4 color rule → Task 0 (compose/clamp) + Task 3 (`_correction` ratio) + Task 5 (`_compound` + the compound-not-revert test); §5 driver → Task 5; §6 testing → unit across 0-5 + real-ffmpeg Task 6; §7 landmines → Task 0 (colorchannelmixer), Task 6 (even dims assert); §8 non-goals → not built (correct). No gaps.

**Type consistency:** `ReelAction.kind` ("deliver"/"reprocess"/"escalate") and `.reprocess`/`.finding` used identically in Task 3 (defined) and Task 5 (consumed). `ReprocessItem(idx, color_correct)` fields match. `build_reel.build_reel(rm, out_dir, work_dir)` and the `{"status": "delivered"|"stop_and_report", ...}` return shape are consistent between Task 5's tests and impl. `color.corrected(gains, correction)`, `ReframeSpec.color_correct`, `process_episode(..., color_correct=)`, `ReelManifest.check_spec` all named identically across tasks.

**Placeholder scan:** none — every code and test step is complete.
