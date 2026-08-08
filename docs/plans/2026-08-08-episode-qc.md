# Per-episode QC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reel is never assembled over an episode nobody judged — a QC gate
between the per-episode render and reel assembly, with a typed verdict bound to the
bytes it judged.

**Architecture:** `edl_to_reel` splits into two phases around the gate. Phase 1
writes `EPISODES.json` (a serialized `ReelManifest` — no new contract). A fan-out of
one fresh judge per episode reads an evidence packet (a frame strip from the
delivered clip, the storyboard, the mechanical report, a new colour-naturalness
sensor) and writes findings; `episode_qc build` validates them into
`EPISODE_QC.json`, stamping each verdict with the clip's sha256 itself. Phase 2
refuses on missing / incomplete / stale / blocking before any ffmpeg.

**Tech Stack:** Python 3.13, numpy + PIL (the sensor and the strip tiler), ffmpeg via
`lib/ffbin` + `lib/assembly`, pytest.

**Design:** [docs/specs/2026-08-08-episode-qc-design.md](../specs/2026-08-08-episode-qc-design.md)

---

## Global Constraints

These bind every task. A reviewer treats a violation as a defect even when the task
text does not repeat it.

- **Imports at top of file.** Never inside a function or a test body — see
  `docs/coding-standards.md`. This applies to test files too.
- **Fail loud.** No silent fallback, no `except: pass`, no defaulting around a
  missing input. A contract validates in `__post_init__` and raises `ValueError`
  with a remedy in the message.
- **Scripts run as modules** (`pythonpath = .`): `.venv/bin/python -m scripts.X`,
  and inside skills always `"$VG" scripts.X`, never a bare venv python.
- **ffmpeg landmines** (`CLAUDE.md`): `-ss` AFTER `-i`; `lutrgb` banned. This slice
  adds no new ffmpeg invocation — it reuses `assembly.frames_rgb` (select-based, no
  seek) and `contact_sheet.build_strip`.
- **No new tunable reaching a caller.** The sensor's thresholds are module
  constants. A threshold a caller can pass is a threshold a subagent can pass
  (design §5/§7).
- **The judge never writes the digest.** `episode_qc build` computes `clip_digest`
  from the file on disk and overwrites whatever the raw findings claimed.
- **Whole-object asserts** in tests where the object is small (`to_dict()` compared
  to a literal), per `docs/testing-guide.md`. Integration tests carry
  `@pytest.mark.integration`.
- **Do not install anything.** No `brew`, `pip install`, `uv`, or `bash setup.sh`.
  The runtime is already provisioned; verification is read-only plus pytest.
- **Commit per task**, message in English, `Co-Authored-By: Claude Opus 5
  <noreply@anthropic.com>` as the last line. Never `git commit --amend` a
  post-review fix — a fix is its own commit.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `scripts/lib/episode_qc.py` | **new** — the verdict contract + the pure gate |
| `scripts/lib/naturalness.py` | **new** — the colour sensor (pure, numpy in / dict out) |
| `scripts/episode_qc.py` | **new** — driver: `pack` (evidence) + `build` (validate/write) |
| `scripts/lib/models.py` | `ReelEpisode.to_dict` / `ReelManifest.to_dict` + `write` |
| `scripts/edl_to_reel.py` | the two-phase split + the gate |
| `scripts/build_reel.py` | report which episodes it re-rendered |
| `scripts/deliver.py` | thread the QC state into the attestation |
| `scripts/lib/provenance.py` | `Attestation.episode_qc` |
| `scripts/montage.py` | `deliver` row → `episodes` + `episode-qc` + `deliver` |
| `skills/episode-qc/SKILL.md` + `episode-reviewer.md` | **new** — the judge |
| `skills/using-montage/SKILL.md`, `skills/process-episode/SKILL.md` | wiring + the correction |
| `tests/lib/test_episode_qc.py`, `tests/lib/test_naturalness.py`, `tests/test_episode_qc.py` | **new** |
| `tests/integration/test_episode_qc.py` | **new** — the real-ffmpeg gate proof |

---

### Task 0: `ReelManifest` learns to write itself

`build_reel`'s CLI reads a reel manifest that nothing in the codebase can write.
Phase 1 has to write one, so close the asymmetry first.

**Files:**
- Modify: `scripts/lib/models.py` (`ReelEpisode` ~1043, `ReelManifest` ~1065)
- Test: `tests/lib/test_models.py`

- [x] **Step 1: Write the failing test**

```python
def test_reel_manifest_round_trips_through_json(tmp_path):
    rm = ReelManifest(
        episodes=[ReelEpisode(manifest={"segment": "a.mp4", "target_dur": 2.0},
                              clip="ep0.mp4", route="r0.json",
                              path="p0.json", meta="m0.json"),
                  ReelEpisode(manifest={"segment": "b.mp4", "target_dur": 3.0},
                              clip="ep1.mp4", route=None, path="p1.json", meta="m1.json")],
        target_dur=5.0, cap=2, changelog="first cut", music=None,
        platform="tiktok", provenance={"edl": {"state": "intact"}})
    p = tmp_path / "EPISODES.json"
    rm.write(p)
    back = ReelManifest.from_json(p)
    assert back.to_dict() == rm.to_dict()
    assert back.episodes[1].route is None          # a pan's absent route survives as null
    assert back.provenance == {"edl": {"state": "intact"}}


def test_reel_episode_to_dict_is_the_from_dict_shape():
    ep = ReelEpisode(manifest={"segment": "a.mp4"}, clip="c.mp4", route=None,
                     path="p.json", meta="m.json")
    assert ep.to_dict() == {"manifest": {"segment": "a.mp4"}, "clip": "c.mp4",
                            "route": None, "path": "p.json", "meta": "m.json"}
```

- [x] **Step 2: Run it, expect failure**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k reel_manifest_round -x -q`
Expected: `AttributeError: 'ReelManifest' object has no attribute 'write'`

- [x] **Step 3: Implement**

In `ReelEpisode` (it is `@dataclass(frozen=True)` — add the method, change no fields):

```python
    def to_dict(self) -> dict:
        """The shape from_dict reads back. `manifest` is emitted INLINE even when it
        was loaded from a path (_load_manifest accepts both): a reel manifest that
        names a file is only as reproducible as that file, and phase 2 may run after
        the scratch dir is gone."""
        return {"manifest": dict(self.manifest), "clip": self.clip,
                "route": self.route, "path": self.path, "meta": self.meta}
```

In `ReelManifest`:

```python
    def to_dict(self) -> dict:
        return {"episodes": [e.to_dict() for e in self.episodes],
                "target_dur": self.target_dur, "variety_min": self.variety_min,
                "color_delta_max": self.color_delta_max, "cap": self.cap,
                "changelog": self.changelog, "music": self.music,
                "ambient": self.ambient, "sfx": self.sfx, "platform": self.platform,
                "provenance": dict(self.provenance)}

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))
```

- [x] **Step 4: Green**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py && git commit -m "feat(models): ReelManifest.to_dict/write closes the read-without-write asymmetry"
```

---

### Task 1: the verdict contract

**Files:**
- Create: `scripts/lib/episode_qc.py`
- Test: `tests/lib/test_episode_qc.py`

- [x] **Step 1: Write the failing tests**

```python
"""The per-episode QC contract (design docs/specs/2026-08-08-episode-qc-design.md §4)."""
import json
import pytest

from scripts.lib.episode_qc import EpisodeFinding, EpisodeVerdict, ReelQC


def _finding(**over) -> dict:
    d = {"axis": "composition", "severity": "important", "evidence": "ep0 @1.2s, head clipped",
         "route": "reprocess", "suggestion": "raise the crop by 6% of frame height"}
    d.update(over)
    return d


def test_a_finding_round_trips():
    f = EpisodeFinding.from_dict(_finding())
    assert f.to_dict() == {**_finding(), "confidence": "high"}


@pytest.mark.parametrize("bad, msg", [
    ({"axis": "vibes"}, "axis"),
    ({"severity": "fatal"}, "severity"),
    ({"route": "re-shoot"}, "route"),
    ({"evidence": "  "}, "evidence"),
    ({"suggestion": ""}, "suggestion"),
    ({"confidence": "certain"}, "confidence"),
])
def test_a_malformed_finding_is_refused(bad, msg):
    with pytest.raises(ValueError, match=msg):
        EpisodeFinding.from_dict(_finding(**bad))


def test_a_verdict_is_revise_iff_something_blocks():
    ok = EpisodeVerdict(idx=0, clip="ep0.mp4", clip_digest="ab", findings=(
        EpisodeFinding.from_dict(_finding(severity="minor")),))
    bad = EpisodeVerdict(idx=0, clip="ep0.mp4", clip_digest="ab", findings=(
        EpisodeFinding.from_dict(_finding(severity="blocking")),))
    assert ok.verdict == "approve"
    assert bad.verdict == "revise"


def test_a_stored_verdict_cannot_lie_about_itself(tmp_path):
    p = tmp_path / "EPISODE_QC.json"
    p.write_text(json.dumps({"episodes": [
        {"idx": 0, "clip": "ep0.mp4", "clip_digest": "ab", "verdict": "approve",
         "findings": [_finding(severity="blocking")]}]}))
    assert ReelQC.from_json(p).episodes[0].verdict == "revise"   # recomputed, never read


def test_reel_qc_round_trips_and_renders(tmp_path):
    qc = ReelQC(episodes=(
        EpisodeVerdict(idx=0, clip="ep0.mp4", clip_digest="ab", summary="reads well"),
        EpisodeVerdict(idx=1, clip="ep1.mp4", clip_digest="cd", findings=(
            EpisodeFinding.from_dict(_finding(axis="hero", severity="blocking",
                                              route="edit-plan")),))))
    p = tmp_path / "EPISODE_QC.json"
    qc.write(p)
    back = ReelQC.from_json(p)
    assert back.to_dict() == qc.to_dict()
    assert back.ok is False
    md = back.to_markdown()
    assert "ep1" in md and "hero" in md and "blocking" in md


def test_duplicate_indices_are_refused():
    with pytest.raises(ValueError, match="twice"):
        ReelQC(episodes=(EpisodeVerdict(idx=0, clip="a.mp4", clip_digest="ab"),
                         EpisodeVerdict(idx=0, clip="b.mp4", clip_digest="cd")))
```

- [x] **Step 2: Run, expect ModuleNotFoundError**

Run: `.venv/bin/python -m pytest tests/lib/test_episode_qc.py -x -q`

- [x] **Step 3: Implement `scripts/lib/episode_qc.py`**

```python
"""Per-episode QC verdicts (design docs/specs/2026-08-08-episode-qc-design.md §4) —
the typed sink for the judge subagent dispatched by skills/episode-qc, and the pure
gate phase 2 refuses on. The per-episode twin of lib/review.py, deliberately the same
shape so the two read alike. No ffmpeg, no IO beyond JSON round-trip: judgment is the
agent's, validation is this module's."""
import json
from dataclasses import dataclass, field
from pathlib import Path

QC_AXES = ("composition", "colour", "impression", "path", "hero")
QC_SEVERITY = ("blocking", "important", "minor")     # blocking ⇒ the reel is not assembled
QC_ROUTES = ("reprocess", "edit-plan", "match-grade", "none")
QC_CONFIDENCE = ("high", "medium", "low")

# Stop reasons, in the order the gate applies them (design §7). An incomplete artifact
# means the run was never judged; a stale one means the verdicts describe other bytes,
# so their blocking-ness is not about THIS reel; only last does a verdict about these
# very bytes get to speak.
QC_STOPS = ("episode-qc-incomplete", "episode-qc-stale", "episode-qc-blocking")


@dataclass
class EpisodeFinding:
    axis: str                  # ∈ QC_AXES                                   (gate)
    severity: str              # ∈ QC_SEVERITY                               (gate)
    evidence: str              # non-empty — cite the frame / timestamp / number (gate)
    route: str                 # ∈ QC_ROUTES — the stage that owns the fix   (gate)
    suggestion: str            # non-empty — the concrete change             (gate)
    confidence: str = "high"   # ∈ QC_CONFIDENCE

    def __post_init__(self) -> None:
        if self.axis not in QC_AXES:
            raise ValueError(f"EpisodeFinding.axis {self.axis!r} not in {QC_AXES}")
        if self.severity not in QC_SEVERITY:
            raise ValueError(f"EpisodeFinding.severity {self.severity!r} not in {QC_SEVERITY}")
        if not (isinstance(self.evidence, str) and self.evidence.strip()):
            raise ValueError("EpisodeFinding.evidence must be a non-empty string (cite the "
                             "frame timestamp, the storyboard mark, or the measured number)")
        if self.route not in QC_ROUTES:
            raise ValueError(f"EpisodeFinding.route {self.route!r} not in {QC_ROUTES}")
        if not (isinstance(self.suggestion, str) and self.suggestion.strip()):
            raise ValueError("EpisodeFinding.suggestion must be a non-empty string (the change)")
        if self.confidence not in QC_CONFIDENCE:
            raise ValueError(f"EpisodeFinding.confidence {self.confidence!r} not in {QC_CONFIDENCE}")

    @classmethod
    def from_dict(cls, d: dict) -> "EpisodeFinding":
        # Top level checked FIRST, before any d.get — the Spec.from_dict rule, at a
        # boundary that reads an agent's JSON.
        if not isinstance(d, dict):
            raise ValueError(f"EpisodeFinding.from_dict: expected a finding object with "
                             f"'axis'/'severity'/'evidence'/'route'/'suggestion', got "
                             f"{type(d).__name__} — re-run the episode-qc judge")
        conf = d.get("confidence")
        return cls(axis=d.get("axis"), severity=d.get("severity"), evidence=d.get("evidence"),
                   route=d.get("route"), suggestion=d.get("suggestion"),
                   confidence="high" if conf is None else conf)

    def to_dict(self) -> dict:
        return {"axis": self.axis, "severity": self.severity, "evidence": self.evidence,
                "route": self.route, "suggestion": self.suggestion,
                "confidence": self.confidence}


@dataclass
class EpisodeVerdict:
    idx: int                   # episode index in the reel manifest          (gate)
    clip: str                  # the judged clip path                        (gate)
    clip_digest: str           # sha256 of that file, stamped by episode_qc build (gate)
    findings: tuple = ()
    summary: str = ""
    reviewer: str = ""         # free note — which agent/model judged

    def __post_init__(self) -> None:
        if isinstance(self.idx, bool) or not isinstance(self.idx, int) or self.idx < 0:
            raise ValueError(f"EpisodeVerdict.idx must be an episode index >= 0, got {self.idx!r}")
        if not (isinstance(self.clip, str) and self.clip.strip()):
            raise ValueError("EpisodeVerdict.clip must be the judged clip's path")
        if not (isinstance(self.clip_digest, str) and self.clip_digest.strip()):
            raise ValueError(
                "EpisodeVerdict.clip_digest must be the sha256 of the judged clip — "
                "episode_qc build stamps it from the file on disk; a verdict without one "
                "names an episode but not which render of it")
        if not (isinstance(self.findings, (tuple, list))
                and all(isinstance(f, EpisodeFinding) for f in self.findings)):
            raise ValueError("EpisodeVerdict.findings must be EpisodeFinding objects "
                             "(build them through episode_qc.build_qc, which validates each)")
        self.findings = tuple(self.findings)
        for name in ("summary", "reviewer"):
            v = getattr(self, name)
            if not isinstance(v, str):
                raise ValueError(f"EpisodeVerdict.{name} must be a string, got {v!r}")

    @property
    def verdict(self) -> str:
        """revise iff any blocking finding. Computed, never stored — a hand-edited
        artifact must not be able to lie about its own verdict (the Review rule)."""
        return "revise" if any(f.severity == "blocking" for f in self.findings) else "approve"

    @classmethod
    def from_dict(cls, d: dict) -> "EpisodeVerdict":
        if not isinstance(d, dict):
            raise ValueError(f"EpisodeVerdict.from_dict: expected an object with 'idx'/'clip'/"
                             f"'clip_digest', got {type(d).__name__} — re-run episode_qc build")
        raw = d.get("findings") or []
        if not isinstance(raw, (tuple, list)):
            raise ValueError(f"EpisodeVerdict.findings must be a JSON list, got {type(raw).__name__}")
        return cls(idx=d.get("idx"), clip=d.get("clip"), clip_digest=d.get("clip_digest"),
                   findings=tuple(EpisodeFinding.from_dict(f) for f in raw),
                   summary=d.get("summary") or "", reviewer=d.get("reviewer") or "")

    def to_dict(self) -> dict:
        # verdict is emitted for readers and recomputed on load (never trusted)
        return {"idx": self.idx, "clip": self.clip, "clip_digest": self.clip_digest,
                "verdict": self.verdict, "findings": [f.to_dict() for f in self.findings],
                "summary": self.summary, "reviewer": self.reviewer}


@dataclass
class ReelQC:
    episodes: tuple = ()       # tuple[EpisodeVerdict, ...] — one per reel episode

    def __post_init__(self) -> None:
        if not (isinstance(self.episodes, (tuple, list))
                and all(isinstance(e, EpisodeVerdict) for e in self.episodes)):
            raise ValueError("ReelQC.episodes must be EpisodeVerdict objects")
        self.episodes = tuple(self.episodes)
        seen: set[int] = set()
        for e in self.episodes:
            if e.idx in seen:
                raise ValueError(f"ReelQC judges episode {e.idx} twice — one verdict per "
                                 f"episode; re-run episode_qc build over the packet dirs")
            seen.add(e.idx)

    @property
    def ok(self) -> bool:
        return all(e.verdict == "approve" for e in self.episodes)

    @property
    def by_idx(self) -> dict:
        return {e.idx: e for e in self.episodes}

    @classmethod
    def from_dict(cls, d: dict) -> "ReelQC":
        if not isinstance(d, dict):
            raise ValueError(f"ReelQC.from_dict: expected an EPISODE_QC.json object with an "
                             f"'episodes' list, got {type(d).__name__} — re-run episode_qc build")
        raw = d.get("episodes") or []
        if not isinstance(raw, (tuple, list)):
            raise ValueError(f"ReelQC.episodes must be a JSON list, got {type(raw).__name__}")
        return cls(episodes=tuple(EpisodeVerdict.from_dict(e) for e in raw))

    def to_dict(self) -> dict:
        return {"episodes": [e.to_dict() for e in self.episodes]}

    @classmethod
    def from_json(cls, path: str | Path) -> "ReelQC":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is corrupt ({e}) — re-run episode_qc build") from e
        return cls.from_dict(d)

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    def to_markdown(self) -> str:
        icon = {True: "✅", False: "🔧"}[self.ok]
        lines = [f"# Episode QC — {icon} {len(self.episodes)} episodes, "
                 f"{'all approved' if self.ok else 'revise'}", ""]
        order = {"blocking": 0, "important": 1, "minor": 2}
        for e in sorted(self.episodes, key=lambda e: e.idx):
            mark = "✅" if e.verdict == "approve" else "🔧"
            lines.append(f"## {mark} ep{e.idx} — `{e.clip}`")
            if e.summary:
                lines += ["", e.summary]
            lines.append("")
            if not e.findings:
                lines += ["No findings.", ""]
                continue
            for f in sorted(e.findings, key=lambda f: order[f.severity]):
                lines.append(f"- **[{f.severity}] {f.axis}** → `{f.route}` "
                             f"(confidence: {f.confidence})")
                lines.append(f"  - {f.evidence}")
                lines.append(f"  - **Fix:** {f.suggestion}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"
```

- [x] **Step 4: Green + commit**

Run: `.venv/bin/python -m pytest tests/lib/test_episode_qc.py -q`

```bash
git add scripts/lib/episode_qc.py tests/lib/test_episode_qc.py && git commit -m "feat(episode-qc): the per-episode verdict contract"
```

---

### Task 2: the pure gate

**Files:**
- Modify: `scripts/lib/episode_qc.py`
- Test: `tests/lib/test_episode_qc.py`

- [x] **Step 1: Write the failing tests**

```python
from scripts.lib.episode_qc import gate     # add to the existing import line


def _verdict(idx, digest, severity=None):
    fs = () if severity is None else (EpisodeFinding.from_dict(_finding(severity=severity)),)
    return EpisodeVerdict(idx=idx, clip=f"ep{idx}.mp4", clip_digest=digest, findings=fs)


def test_a_fully_judged_reel_passes_the_gate():
    qc = ReelQC(episodes=(_verdict(0, "aa"), _verdict(1, "bb", "minor")))
    assert gate(qc, {0: "aa", 1: "bb"}) == (None, [])


def test_an_unjudged_episode_stops_the_reel():
    reason, problems = gate(ReelQC(episodes=(_verdict(0, "aa"),)), {0: "aa", 1: "bb"})
    assert reason == "episode-qc-incomplete"
    assert problems == ["episode 1 has no verdict"]


def test_a_verdict_for_an_episode_the_reel_does_not_have_stops_it():
    reason, problems = gate(ReelQC(episodes=(_verdict(0, "aa"), _verdict(4, "zz"))), {0: "aa"})
    assert reason == "episode-qc-incomplete"
    assert problems == ["verdict for episode 4, which this reel does not have"]


def test_a_moved_digest_stops_the_reel_before_any_blocking_finding():
    qc = ReelQC(episodes=(_verdict(0, "aa", "blocking"), _verdict(1, "OLD")))
    reason, problems = gate(qc, {0: "aa", 1: "NEW"})
    assert reason == "episode-qc-stale"          # staleness outranks the blocking finding
    assert problems == ["episode 1 was judged as OLD… but ep1.mp4 now hashes to NEW…"]


def test_a_blocking_finding_stops_the_reel():
    qc = ReelQC(episodes=(_verdict(0, "aa"), _verdict(1, "bb", "blocking")))
    reason, problems = gate(qc, {0: "aa", 1: "bb"})
    assert reason == "episode-qc-blocking"
    assert problems == ["episode 1: [blocking] composition — ep0 @1.2s, head clipped"]
```

- [x] **Step 2: Run, expect ImportError**

Run: `.venv/bin/python -m pytest tests/lib/test_episode_qc.py -k gate -x -q`

- [x] **Step 3: Implement (append to `scripts/lib/episode_qc.py`)**

```python
def _short(digest: str) -> str:
    return f"{digest[:12]}…"


def gate(qc: ReelQC, digests: dict) -> tuple:
    """(reason, problems) — reason is None iff the reel may be assembled.

    `digests` maps EVERY episode index in the reel to the sha256 of its clip NOW, so
    this stays pure: the caller owns the filesystem, this owns the decision. The
    missing-artifact case has no ReelQC to pass and is therefore the caller's
    (design §7).

    The three reasons are applied in QC_STOPS order and the FIRST one wins: an
    incomplete artifact means the run was never judged; a stale one means the
    verdicts are about other bytes, so their blocking-ness is not about this reel."""
    by_idx = qc.by_idx
    missing = [f"episode {i} has no verdict" for i in sorted(digests) if i not in by_idx]
    extra = [f"verdict for episode {i}, which this reel does not have"
             for i in sorted(by_idx) if i not in digests]
    if missing or extra:
        return QC_STOPS[0], missing + extra
    stale = [f"episode {i} was judged as {_short(by_idx[i].clip_digest)} but "
             f"{by_idx[i].clip} now hashes to {_short(digests[i])}"
             for i in sorted(digests) if by_idx[i].clip_digest != digests[i]]
    if stale:
        return QC_STOPS[1], stale
    blocking = [f"episode {i}: [{f.severity}] {f.axis} — {f.evidence}"
                for i in sorted(by_idx) for f in by_idx[i].findings
                if f.severity == "blocking"]
    if blocking:
        return QC_STOPS[2], blocking
    return None, []
```

- [x] **Step 4: Green + commit**

Run: `.venv/bin/python -m pytest tests/lib/test_episode_qc.py -q`

```bash
git add scripts/lib/episode_qc.py tests/lib/test_episode_qc.py && git commit -m "feat(episode-qc): the pure gate — incomplete, stale, blocking"
```

---

### Task 3: the colour-naturalness sensor

**Files:**
- Create: `scripts/lib/naturalness.py`
- Test: `tests/lib/test_naturalness.py`

- [x] **Step 1: Write the failing tests**

```python
"""The colour-naturalness sensor (design docs/specs/2026-08-08-episode-qc-design.md §5)."""
import numpy as np
import pytest

from scripts.lib import naturalness


def _flat(r, g, b, h=64, w=64):
    f = np.zeros((h, w, 3), dtype=np.uint8)
    f[:, :, 0], f[:, :, 1], f[:, :, 2] = r, g, b
    return f


def test_a_neutral_mid_grey_frame_reads_clean():
    stats = naturalness.measure([_flat(118, 120, 122)])
    flags = naturalness.evaluate(stats)
    assert stats["cast"] < 0.02
    assert flags["blown_highlights"] is False and flags["crushed_blacks"] is False
    assert flags["colour_cast"] is False and flags["oversaturated"] is False


def test_a_red_frame_reads_as_a_cast_and_oversaturated():
    flags = naturalness.evaluate(naturalness.measure([_flat(220, 40, 40)]))
    assert flags["colour_cast"] is True
    assert flags["oversaturated"] is True


def test_white_pixels_read_as_blown_and_black_ones_as_crushed():
    blown = np.concatenate([_flat(255, 255, 255, h=16), _flat(120, 120, 120, h=48)])
    crushed = np.concatenate([_flat(0, 0, 0, h=16), _flat(120, 120, 120, h=48)])
    assert naturalness.evaluate(naturalness.measure([blown]))["blown_highlights"] is True
    assert naturalness.evaluate(naturalness.measure([crushed]))["crushed_blacks"] is True


def test_a_single_tone_frame_reads_flat_and_a_full_ramp_does_not():
    flat = naturalness.measure([_flat(120, 120, 120)])
    ramp = np.repeat(np.arange(256, dtype=np.uint8).reshape(1, 256, 1), 3, axis=2)
    ramp = np.repeat(ramp, 64, axis=0)
    assert naturalness.evaluate(flat)["flat"] is True
    assert naturalness.evaluate(naturalness.measure([ramp]))["flat"] is False


def test_frames_are_averaged_not_concatenated():
    """Two frames, one blown and one clean: the reported fraction is their MEAN, so a
    single bad frame in a long episode does not read as a blown episode."""
    stats = naturalness.measure([_flat(255, 255, 255), _flat(120, 120, 120)])
    assert stats["clip_high"] == [0.5, 0.5, 0.5]
    assert stats["frames"] == 2


def test_no_frames_is_refused():
    with pytest.raises(ValueError, match="at least one frame"):
        naturalness.measure([])
```

- [x] **Step 2: Run, expect ModuleNotFoundError**

Run: `.venv/bin/python -m pytest tests/lib/test_naturalness.py -x -q`

- [x] **Step 3: Implement `scripts/lib/naturalness.py`**

```python
"""Colour-naturalness measurement (design docs/specs/2026-08-08-episode-qc-design.md §5).

check_episode's color_fidelity answers "did the grade move the SUBJECT's hue away from
the source" and is blind to the four things that actually make a graded frame read
unnatural: blown highlights, crushed blacks, a global colour cast, and oversaturation.
This measures those, so the QC judge argues from numbers instead of impressions.

Pure: numpy arrays in, one dict out. No ffmpeg, no file paths — the caller decodes
(assembly.frames_rgb) and the caller decides. Nothing here fails an episode: the flags
are advisory in both directions (design §5)."""
import numpy as np

# First cuts, declared as first cuts — no footage has been graded against them. They
# live here and ONLY here: a threshold a caller can pass is a threshold a subagent can
# pass, and the gate's no-waiver rule (§7) would be worth nothing if the sensor's bar
# were an argument. Calibrate on the first real run that uses them.
CLIP_HIGH = 250       # a channel value at/above this counts as "at white"
CLIP_LOW = 5          # ...and at/below this as "at black"
BLOWN_FRAC = 0.02     # >2% of pixels at white in ANY channel → blown_highlights
CRUSHED_FRAC = 0.05   # >5% at black → crushed_blacks (shadows legitimately cover more area)
CAST_MAX = 0.08       # grey-world channel deviation above this reads as a colour cast
SAT_MAX = 0.60        # mean relative saturation above this reads oversaturated
FLAT_SPREAD = 40.0    # p95-p5 luma below this reads flat


def _frame_stats(f: np.ndarray) -> dict:
    """One frame's numbers. Reductions only — no float copy of the whole frame is
    materialized, so a 4K frame costs its own bytes and not eight times them."""
    if not (isinstance(f, np.ndarray) and f.ndim == 3 and f.shape[2] == 3):
        raise ValueError(f"naturalness: each frame must be an HxWx3 RGB array, got "
                         f"{getattr(f, 'shape', type(f).__name__)}")
    px = f.reshape(-1, 3)
    means = [float(px[:, c].mean()) for c in range(3)]
    hi = [float((px[:, c] >= CLIP_HIGH).mean()) for c in range(3)]
    lo = [float((px[:, c] <= CLIP_LOW).mean()) for c in range(3)]
    mx = px.max(axis=1).astype(np.float32)
    mn = px.min(axis=1).astype(np.float32)
    sat = float(((mx - mn) / np.maximum(mx, 1.0)).mean())
    luma = (0.299 * px[:, 0] + 0.587 * px[:, 1] + 0.114 * px[:, 2]).astype(np.float32)
    p5, p95 = (float(v) for v in np.percentile(luma, [5, 95]))
    return {"means": means, "clip_high": hi, "clip_low": lo, "saturation": sat,
            "contrast": p95 - p5}


def measure(frames: list) -> dict:
    """Aggregate `frames` (HxWx3 uint8 RGB) into one clip-level reading.

    Averaged per frame, never pooled pixel-wise: a single blown frame in a 90-frame
    episode must read as 1/90 blown, and pooling would also cost a float copy of every
    pixel in the episode at once."""
    if not frames:
        raise ValueError("naturalness.measure needs at least one frame — sample the clip "
                         "with assembly.frames_rgb before calling")
    per = [_frame_stats(f) for f in frames]
    n = len(per)
    means = [sum(s["means"][c] for s in per) / n for c in range(3)]
    neutral = sum(means) / 3
    # A frame whose channels are all zero has no neutral to deviate from; report no
    # cast rather than divide by it. (A black episode is the black_frames gate's job.)
    cast = max(abs(m / neutral - 1.0) for m in means) if neutral > 0 else 0.0
    return {"frames": n,
            "means": [round(m, 2) for m in means],
            "clip_high": [round(sum(s["clip_high"][c] for s in per) / n, 4) for c in range(3)],
            "clip_low": [round(sum(s["clip_low"][c] for s in per) / n, 4) for c in range(3)],
            "cast": round(cast, 4),
            "saturation": round(sum(s["saturation"] for s in per) / n, 4),
            "contrast": round(sum(s["contrast"] for s in per) / n, 2)}


def evaluate(stats: dict) -> dict:
    """Named advisory flags. Never a pass/fail — the judge weighs them against the
    episode's intent (a deliberately crushed night shot is not a defect)."""
    return {"blown_highlights": max(stats["clip_high"]) > BLOWN_FRAC,
            "crushed_blacks": max(stats["clip_low"]) > CRUSHED_FRAC,
            "colour_cast": stats["cast"] > CAST_MAX,
            "oversaturated": stats["saturation"] > SAT_MAX,
            "flat": stats["contrast"] < FLAT_SPREAD}
```

- [x] **Step 4: Green + commit**

Run: `.venv/bin/python -m pytest tests/lib/test_naturalness.py -q`

```bash
git add scripts/lib/naturalness.py tests/lib/test_naturalness.py && git commit -m "feat(episode-qc): the colour-naturalness sensor"
```

---

### Task 4: the driver — `pack` and `build`

**Files:**
- Create: `scripts/episode_qc.py`
- Test: `tests/test_episode_qc.py`

- [x] **Step 1: Write the failing tests** (unit level — `pack`'s ffmpeg half is proved in Task 8)

```python
"""episode_qc driver — validation and stamping (design §6/§7)."""
import json
import pytest

from scripts import episode_qc
from scripts.lib import provenance
from scripts.lib.models import ReelEpisode, ReelManifest


def _rm(tmp_path, n=2):
    eps = []
    for i in range(n):
        clip = tmp_path / f"ep{i}.mp4"
        clip.write_bytes(f"clip-{i}".encode())
        eps.append(ReelEpisode(manifest={"segment": f"s{i}.mp4", "target_dur": 2.0},
                               clip=str(clip), route=None,
                               path=str(tmp_path / f"ep{i}" / "path.json"),
                               meta=str(tmp_path / f"ep{i}" / "path.meta.json")))
    return ReelManifest(episodes=eps, target_dur=4.0)


def _findings(packets, i, severity="minor"):
    d = packets / f"ep{i}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "findings.json").write_text(json.dumps({
        "summary": f"ep{i} reads well", "reviewer": "test-judge",
        "findings": [{"axis": "colour", "severity": severity, "evidence": "warm cast",
                      "route": "match-grade", "suggestion": "cool it by 4 units"}]}))


def test_build_stamps_the_digest_itself_and_ignores_what_the_judge_claimed(tmp_path):
    rm = _rm(tmp_path)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    packets = tmp_path / "qc"
    _findings(packets, 0)
    _findings(packets, 1)
    (packets / "ep0" / "findings.json").write_text(json.dumps({
        "clip_digest": "deadbeef", "findings": []}))          # the judge tries to set it
    res = episode_qc.build(str(ep_path), str(packets), str(tmp_path))
    qc = json.loads((tmp_path / "EPISODE_QC.json").read_text())
    assert res["status"] == "written" and res["verdict"] == "approve"
    assert qc["episodes"][0]["clip_digest"] == provenance.digest_file(rm.episodes[0].clip)
    assert (tmp_path / "EPISODE_QC.md").exists()


def test_build_refuses_an_unjudged_episode(tmp_path):
    rm = _rm(tmp_path)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    packets = tmp_path / "qc"
    _findings(packets, 0)
    with pytest.raises(ValueError, match="episode 1 has no findings.json"):
        episode_qc.build(str(ep_path), str(packets), str(tmp_path))


def test_build_reports_revise_when_a_finding_blocks(tmp_path):
    rm = _rm(tmp_path)
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    packets = tmp_path / "qc"
    _findings(packets, 0)
    _findings(packets, 1, severity="blocking")
    res = episode_qc.build(str(ep_path), str(packets), str(tmp_path))
    assert res["verdict"] == "revise" and res["blocking"] == 1


def test_pack_refuses_an_episode_with_no_sidecar_path(tmp_path):
    rm = ReelManifest(episodes=[ReelEpisode(manifest={"segment": "s.mp4"},
                                            clip=str(tmp_path / "ep0.mp4"))],
                      target_dur=2.0)
    (tmp_path / "ep0.mp4").write_bytes(b"x")
    ep_path = tmp_path / "EPISODES.json"
    rm.write(ep_path)
    with pytest.raises(ValueError, match="no path sidecar"):
        episode_qc.pack(str(ep_path), str(tmp_path / "qc"))
```

- [x] **Step 2: Run, expect ModuleNotFoundError**

Run: `.venv/bin/python -m pytest tests/test_episode_qc.py -x -q`

- [x] **Step 3: Implement `scripts/episode_qc.py`**

```python
"""Per-episode QC driver (design docs/specs/2026-08-08-episode-qc-design.md §6/§7).

Two commands, both mechanical:
  pack   — one evidence directory per episode: a frame strip from the DELIVERED clip,
           the storyboard, the mechanical report, and the naturalness sensor's numbers.
  build  — validate each judge's raw findings into EPISODE_QC.json + .md, stamping the
           clip digest HERE (never from the judge's file, design §7).

Judgment belongs to the subagents skills/episode-qc dispatches; this module is their
typed sink. Mirror of reel_review.py — contract in lib, driver here."""
import argparse
import json
from pathlib import Path

from scripts import contact_sheet
from scripts.lib import assembly, naturalness, provenance
from scripts.lib.episode_qc import EpisodeFinding, EpisodeVerdict, ReelQC
from scripts.lib.models import ReelManifest

FRAMES = 9           # strip cells per episode — enough to read a path across a 2-4s cut
SENSOR_FRAMES = 5    # frames the naturalness sensor averages over


def _epdir(ep, i: int) -> Path:
    """process_episode writes route/path/report/storyboard into ONE directory per
    episode, and ReelEpisode.path names a file inside it — so the scratch dir is
    derived, never passed. A manifest with no sidecar (legal in the contract, and what
    a hand-authored reel manifest may carry) has none to derive, and is refused by
    name rather than guessed at."""
    if not ep.path:
        raise ValueError(f"episode {i} has no path sidecar, so its per-episode scratch "
                         f"(report.json, storyboard.jpg) cannot be located — pack the "
                         f"EPISODES.json a two-phase edl_to_reel wrote, not a hand-built one")
    return Path(ep.path).parent


def _evidence(ep, i: int, clip_stats: dict) -> dict:
    """What the judge reads besides the pixels. The episode's declared INTENT is in
    here deliberately: composition is judged against what this episode asked for, never
    against a global rule (design §6)."""
    d = _epdir(ep, i)
    m = ep.manifest
    out: dict = {
        "idx": i, "clip": ep.clip,
        "intent": {k: m.get(k) for k in ("composition", "grid", "hero", "target_dur",
                                         "layout", "pan", "stabilize", "canvas")},
        "storyboard": str(d / "storyboard.jpg"),
        "naturalness": clip_stats,
    }
    for name, key in (("report.json", "checks"), ("route.meta.json", "track"),
                      ("path.meta.json", "geometry")):
        p = d / name
        # Absent is reported as absent, never as an empty reading: a judge must be able
        # to tell "the tracker said nothing" from "there was no tracker".
        out[key] = json.loads(p.read_text()) if p.exists() else None
    return out


def pack(episodes_path: str, out_dir: str, *, frames: int = FRAMES) -> dict:
    """Write one evidence directory per episode under out_dir. Returns a status dict."""
    rm = ReelManifest.from_json(episodes_path)
    for i, ep in enumerate(rm.episodes):
        _epdir(ep, i)          # every sidecar checked BEFORE any decode: a packet run that
                               # cannot finish must fail in ms, not after N episodes of ffmpeg
    packets = []
    for i, ep in enumerate(rm.episodes):
        d = Path(out_dir) / f"ep{i}"
        d.mkdir(parents=True, exist_ok=True)
        info = assembly.probe_stream(ep.clip)
        dur = assembly.probe_duration(ep.clip)
        contact_sheet.build_strip(ep.clip, str(d / "strip.jpg"), start=0.0, dur=dur,
                                  frames=frames, fps=info.fps)
        times = [dur * (k + 0.5) / SENSOR_FRAMES for k in range(SENSOR_FRAMES)]
        stats = naturalness.measure(assembly.frames_rgb(ep.clip, times, info.fps))
        (d / "evidence.json").write_text(json.dumps(
            _evidence(ep, i, {"stats": stats, "flags": naturalness.evaluate(stats)}), indent=2))
        packets.append(str(d))
    return {"status": "packed", "episodes": len(packets), "packets": packets}


def _raw(packets: str, i: int) -> dict:
    p = Path(packets) / f"ep{i}" / "findings.json"
    if not p.exists():
        raise ValueError(f"episode {i} has no findings.json in {p.parent} — every episode "
                         f"must be judged before the reel is assembled; dispatch the "
                         f"episode-qc judge for it, or delete the packet and re-pack")
    try:
        d = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{p} is not valid JSON ({e}) — the judge writes "
                         f"{{'summary','reviewer','findings'}}") from e
    if not isinstance(d, dict):
        raise ValueError(f"{p}: expected a {{'summary','reviewer','findings'}} object, "
                         f"got {type(d).__name__}")
    return d


def build_qc(episodes_path: str, packets: str) -> ReelQC:
    """Validate every episode's raw findings into a typed ReelQC. The clip digest is
    computed HERE from the file on disk — whatever `clip_digest` the judge's file
    carries is ignored, which is what turns "this episode was judged" into "this
    RENDER was judged" (design §7)."""
    rm = ReelManifest.from_json(episodes_path)
    verdicts = []
    for i, ep in enumerate(rm.episodes):
        raw = _raw(packets, i)                     # read once: three reads = three failure surfaces
        findings = raw.get("findings") or []
        if not isinstance(findings, (tuple, list)):
            raise ValueError(f"episode {i}: 'findings' must be a JSON list, got "
                             f"{type(findings).__name__}")
        verdicts.append(EpisodeVerdict(
            idx=i, clip=ep.clip, clip_digest=provenance.digest_file(ep.clip),
            findings=tuple(EpisodeFinding.from_dict(f) for f in findings),
            summary=raw.get("summary") or "", reviewer=raw.get("reviewer") or ""))
    return ReelQC(episodes=tuple(verdicts))


def build(episodes_path: str, packets: str, out_dir: str) -> dict:
    """build_qc + write EPISODE_QC.json/.md into out_dir (the dir phase 2 looks in)."""
    qc = build_qc(episodes_path, packets)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    qj, qm = Path(out_dir) / "EPISODE_QC.json", Path(out_dir) / "EPISODE_QC.md"
    qc.write(qj)
    qm.write_text(qc.to_markdown())
    blocking = sum(1 for e in qc.episodes for f in e.findings if f.severity == "blocking")
    return {"status": "written", "verdict": "approve" if qc.ok else "revise",
            "episodes": len(qc.episodes), "blocking": blocking,
            "qc": str(qj), "md": str(qm)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="per-episode QC: pack the evidence, then validate the judges' findings")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack", help="one evidence dir per episode (strip + storyboard + numbers)")
    p.add_argument("--episodes", required=True, help="EPISODES.json from edl_to_reel --stop-after-episodes")
    p.add_argument("--out-dir", required=True, help="dir for the ep{i}/ packet dirs")
    p.add_argument("--frames", type=int, default=FRAMES, help=f"strip cells per episode (default {FRAMES})")
    b = sub.add_parser("build", help="validate every judge's findings.json -> EPISODE_QC.json + .md")
    b.add_argument("--episodes", required=True, help="the same EPISODES.json")
    b.add_argument("--packets", required=True, help="the pack --out-dir holding ep{i}/findings.json")
    b.add_argument("--out-dir", required=True,
                   help="dir for EPISODE_QC.json/.md — must be the dir holding EPISODES.json")
    a = ap.parse_args()
    result = (pack(a.episodes, a.out_dir, frames=a.frames) if a.cmd == "pack"
              else build(a.episodes, a.packets, a.out_dir))
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Green + commit**

Run: `.venv/bin/python -m pytest tests/test_episode_qc.py -q`

```bash
git add scripts/episode_qc.py tests/test_episode_qc.py && git commit -m "feat(episode-qc): pack the evidence, build the verdicts"
```

---

### Task 5: the record — `reprocessed` and the attestation

**Files:**
- Modify: `scripts/lib/provenance.py` (`Attestation`), `scripts/deliver.py` (~line 121),
  `scripts/build_reel.py`
- Test: `tests/lib/test_build_reel.py`, `tests/test_deliver.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/lib/test_build_reel.py — with the module's existing fake-driver style
def test_a_delivered_reel_reports_which_episodes_were_reprocessed(monkeypatch, tmp_path):
    """build_reel's loop-2 re-renders culprits AFTER the QC gate ran, so which ones
    it touched has to leave the loop (design §8) — a verdict on ep1 is one render out
    of date the moment ep1 is rebuilt."""
    # ... drive build_reel with a stubbed check_reel that fails colour on episode 1
    # once and passes on the re-check, per this file's existing monkeypatch pattern ...
    assert result["status"] == "delivered"
    assert result["reprocessed"] == [1]


# tests/test_deliver.py
def test_the_attestation_carries_the_qc_state(tmp_path, ...):
    deliver.deliver(master, REEL_H264, str(out), "note", rep, run_provenance={
        "engine_at_start": {}, "edl": {}, "overrides": [],
        "episode_qc": {"state": "judged", "judged": {"0": "aa"}, "reprocessed_after": [1]}})
    att = json.loads((provenance.attest_path(...)).read_text())
    assert att["episode_qc"] == {"state": "judged", "judged": {"0": "aa"},
                                 "reprocessed_after": [1]}


def test_an_unjudged_delivery_says_so(tmp_path, ...):
    deliver.deliver(master, REEL_H264, str(out), "note", rep,
                    run_provenance={"episode_qc": {"state": "absent"}})
    assert json.loads(...)["episode_qc"] == {"state": "absent"}
```

- [x] **Step 2: Run, expect failures (`KeyError: 'reprocessed'`, missing attestation key)**

- [x] **Step 3: Implement**

`provenance.Attestation` — one new field, defaulted, so old sidecars stay readable and
`PROV_V` does not move:

```python
    overrides: list = field(default_factory=list)
    episode_qc: dict = field(default_factory=dict)   # §10: "judged" + digests, or "absent"
    delivered_at: str = ""
```

…mirrored in `to_dict` (`"episode_qc": dict(self.episode_qc)`) and `from_dict`
(`episode_qc=d.get("episode_qc") or {}`).

`deliver.deliver` — one line inside the `Attestation(...)` call:

```python
        edl=rp.get("edl") or {}, overrides=rp.get("overrides") or [],
        episode_qc=rp.get("episode_qc") or {},
```

`build_reel.build_reel` — track the set and report it; merge it into the provenance the
attestation is built from:

```python
    attempts: dict[int, int] = {}
    reprocessed: set[int] = set()          # design §8: which clips left the gate behind
```

in the reprocess loop, beside `attempts[item.idx] = ...`:

```python
            reprocessed.add(item.idx)
```

and at the deliver arm, before calling `deliver.deliver`:

```python
        if action.kind == "deliver":
            ...
            prov = dict(rm.provenance)
            qc = dict(prov.get("episode_qc") or {})
            qc["reprocessed_after"] = sorted(reprocessed)
            prov["episode_qc"] = qc
            out = deliver.deliver(master, REEL_H264, out_dir, rm.changelog, report,
                                  audio=audio, titles=titles, platform=rm.platform,
                                  run_provenance=prov)
            return {"status": "delivered", "output": out, "report": report.to_dict(),
                    "reprocessed": sorted(reprocessed)}
```

- [x] **Step 4: Green + commit**

Run: `.venv/bin/python -m pytest tests/lib/test_build_reel.py tests/test_deliver.py -q`

```bash
git add scripts/lib/provenance.py scripts/deliver.py scripts/build_reel.py tests/ && git commit -m "feat(episode-qc): the delivery records which clips left the gate behind"
```

---

### Task 6: the two-phase `edl_to_reel` and the gate

**Files:**
- Modify: `scripts/edl_to_reel.py`
- Test: `tests/lib/test_edl_to_reel.py`

- [x] **Step 1: Write the failing tests**

```python
def test_phase_two_refuses_a_reel_with_no_qc_artifact(tmp_path):
    rm = _manifest(tmp_path)                     # this file's existing helper style
    rm.write(tmp_path / "EPISODES.json")
    res = edl_to_reel.assemble_reel(str(tmp_path / "EPISODES.json"), str(tmp_path / "work"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "episode-qc-missing"


def test_phase_two_refuses_a_blocking_verdict_before_any_ffmpeg(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(edl_to_reel.build_reel, "build_reel",
                        lambda *a, **k: called.append(1))
    ... write EPISODES.json + an EPISODE_QC.json whose ep0 blocks ...
    res = edl_to_reel.assemble_reel(...)
    assert res["finding"]["reason"] == "episode-qc-blocking"
    assert called == []                          # nothing was assembled


def test_phase_two_passes_the_qc_state_into_the_run_provenance(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(edl_to_reel.build_reel, "build_reel",
                        lambda rm, *a, **k: seen.update(rm.provenance) or {"status": "delivered"})
    ... clean QC ...
    assert seen["episode_qc"]["state"] == "judged"
    assert set(seen["episode_qc"]["judged"]) == {"0", "1"}


def test_the_single_command_path_records_that_nothing_judged_it(tmp_path, monkeypatch):
    """The SP1 hand-authored front door still ships unjudged — and says so (design §10)."""
    ...
    assert seen["episode_qc"] == {"state": "absent"}
```

- [x] **Step 2: Run, expect `AttributeError: module has no attribute 'assemble_reel'`**

- [x] **Step 3: Implement**

Refactor `edl_to_reel` into a shared builder plus three entry points. The existing body
from `edl = EDL.from_json(edl_path)` down to the `rm.provenance = {...}` assignment
moves **verbatim** into `_build_manifest`, which returns `(rm, None)` or `(None, stop)`.
Nothing in that body changes — the whole point is that phase 1 and the single-shot path
stay the same code.

```python
from scripts.lib import episode_qc as qc_lib
from scripts.lib.episode_qc import ReelQC


def _build_manifest(edl_path, project_path, footage_root, work_dir, out_dir, *,
                    music=None, jobs=DEFAULT_JOBS, color_delta_max=None,
                    changelog="") -> tuple:
    """Everything up to the ReelManifest: preflight, extract, the loop-1 fan-out, the
    run provenance. Returns (rm, None) or (None, stop_and_report)."""
    ...                                   # the existing body, unchanged
    return rm, None


def edl_to_reel(edl_path, project_path, footage_root, work_dir, out_dir, *, music=None,
                titles=None, jobs=DEFAULT_JOBS, color_delta_max=None, changelog="") -> dict:
    """The SP1 front door: a hand-authored EDL.json -> a delivered REEL_v1.mp4 in one
    command. No per-episode QC runs on this path — the delivery's attestation records
    `episode_qc: absent` so an unjudged reel is DISTINGUISHABLE from a judged one, which
    is the honest half of the gate (design §10): no silent bypass, not no bypass."""
    rm, stop = _build_manifest(edl_path, project_path, footage_root, work_dir, out_dir,
                               music=music, jobs=jobs, color_delta_max=color_delta_max,
                               changelog=changelog)
    if stop:
        return stop
    rm.provenance["episode_qc"] = {"state": "absent"}
    return build_reel.build_reel(rm, out_dir, str(Path(work_dir) / "reel"), titles=titles)


def process_episodes(edl_path, project_path, footage_root, work_dir, out_dir, *,
                     music=None, jobs=DEFAULT_JOBS, color_delta_max=None,
                     changelog="") -> dict:
    """Phase 1: render every episode, then STOP. Writes EPISODES.json (a serialized
    ReelManifest) beside the ep{i}.mp4 it describes, so the verdicts and the judged
    clips cannot be separated (design §3)."""
    rm, stop = _build_manifest(edl_path, project_path, footage_root, work_dir, out_dir,
                               music=music, jobs=jobs, color_delta_max=color_delta_max,
                               changelog=changelog)
    if stop:
        return stop
    p = Path(out_dir) / "EPISODES.json"
    rm.write(p)
    return {"status": "episodes_ready", "episodes": str(p), "count": len(rm.episodes),
            "clips": [e.clip for e in rm.episodes]}


def assemble_reel(episodes_path: str, work_dir: str, *, titles: str | None = None) -> dict:
    """Phase 2: the QC gate, then build_reel. The out dir is EPISODES.json's own
    directory — one fewer flag to point at the wrong place, and the gate's artifact is
    found there BY CONVENTION (design §3/§7).

    Every refusal below happens before a single ffmpeg call and writes nothing."""
    rm = ReelManifest.from_json(episodes_path)
    out_dir = str(Path(episodes_path).parent)
    qc_path = Path(out_dir) / "EPISODE_QC.json"
    if not qc_path.exists():
        return {"status": "stop_and_report",
                "finding": {"reason": "episode-qc-missing", "episode_idx": None,
                            "problems": [
                                f"no EPISODE_QC.json beside {episodes_path} — every episode "
                                f"must be judged before the reel is assembled: run "
                                f"`episode_qc pack`, dispatch the episode-qc judges, then "
                                f"`episode_qc build`"]}}
    qc = ReelQC.from_json(qc_path)
    digests = {i: provenance.digest_file(ep.clip) for i, ep in enumerate(rm.episodes)}
    reason, problems = qc_lib.gate(qc, digests)
    if reason:
        return {"status": "stop_and_report",
                "finding": {"reason": reason, "episode_idx": None, "problems": problems}}
    prov = dict(rm.provenance)
    prov["episode_qc"] = {"state": "judged",
                          "judged": {str(i): d for i, d in sorted(digests.items())}}
    rm.provenance = prov
    return build_reel.build_reel(rm, out_dir, str(Path(work_dir) / "reel"), titles=titles)
```

CLI — the two flags are mutually exclusive, and `--from-episodes` needs none of the
front-half arguments, so the positional and its friends become conditional:

```python
    ap.add_argument("edl", nargs="?", default=None,
                    help="path to an EDL.json (omit with --from-episodes)")
    ap.add_argument("--project", default=None, help="project.json — episodes inherit canvas/delivery")
    ...
    phase = ap.add_mutually_exclusive_group()
    phase.add_argument("--stop-after-episodes", action="store_true",
                       help="render every episode, write EPISODES.json, and stop — the "
                            "seam the per-episode QC gate sits in (design 2026-08-08)")
    phase.add_argument("--from-episodes", default=None,
                       help="an EPISODES.json from --stop-after-episodes: gate on "
                            "EPISODE_QC.json beside it, then assemble and deliver")
    a = ap.parse_args()
    if a.from_episodes:
        if a.edl or a.project or a.footage_root:
            ap.error("--from-episodes resumes a run whose episodes are already rendered; "
                     "the EDL / --project / --footage-root are not read again")
        result = assemble_reel(a.from_episodes, a.work_dir, titles=a.titles)
    else:
        missing = [n for n, v in (("edl", a.edl), ("--project", a.project),
                                  ("--footage-root", a.footage_root)) if not v]
        if missing:
            ap.error(f"missing {', '.join(missing)} — required unless --from-episodes is given")
        fn = process_episodes if a.stop_after_episodes else edl_to_reel
        kw = {} if a.stop_after_episodes else {"titles": a.titles}
        result = fn(a.edl, a.project, a.footage_root, a.work_dir, a.out_dir,
                    music=a.music, jobs=a.jobs, color_delta_max=a.color_delta_max,
                    changelog=a.changelog, **kw)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] in ("delivered", "episodes_ready") else 1)
```

Keep `--work-dir` and `--out-dir` required for both paths (`--out-dir` is unused by
phase 2 — it derives the dir from `--from-episodes` — so *drop* it from the phase-2
call rather than pass a second, possibly different, directory).

- [x] **Step 4: Green + commit**

Run: `.venv/bin/python -m pytest tests/lib/test_edl_to_reel.py -q`

```bash
git add scripts/edl_to_reel.py tests/lib/test_edl_to_reel.py && git commit -m "feat(episode-qc): the two-phase edl_to_reel and its gate"
```

---

### Task 7: the router's three rows

**Files:**
- Modify: `scripts/montage.py` (`V1_STAGES` ~line 68)
- Test: `tests/lib/test_montage.py`

- [x] **Step 1: Write the failing test**

```python
def test_the_qc_stage_sits_between_the_episodes_and_the_reel():
    keys = [s.key for s in montage.V1_STAGES]
    assert keys.index("episodes") < keys.index("episode-qc") < keys.index("deliver")
    assert all(s.kind == "required" for s in montage.V1_STAGES
               if s.key in ("episodes", "episode-qc"))


def test_next_points_at_the_qc_stage_once_the_episodes_exist(tmp_path):
    """A run with rendered episodes and no verdicts is NOT ready to deliver."""
    ...                                   # touch the artifacts the earlier stages need
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "EPISODES.json").write_text("{}")
    assert montage.status(str(tmp_path))["next"] == "episode-qc"
```

- [x] **Step 2: Run, expect failure**

- [x] **Step 3: Implement** — replace the single `deliver` row with three:

```python
    Stage("episodes", "EPISODES.json", "required",
          "edl_to_reel --stop-after-episodes (renders every episode, then stops at the "
          "QC seam)", None, in_out=True),
    # required, not optional (design 2026-08-08 §1): a reel assembled over an episode
    # nobody judged is exactly what the 2026-08-03 run shipped. The stage gates the
    # artifact's presence and its digest binding — never proof that anyone looked (§12).
    Stage("episode-qc", "EPISODE_QC.json", "required",
          "episode-qc SKILL -> episode_qc pack, one judge per episode (cap 3), "
          "episode_qc build", None, in_out=True),
    Stage("deliver", "REEL_v*.*", "required",
          "edl_to_reel --from-episodes (gates on EPISODE_QC.json, then assembles)",
          "final", in_out=True),
```

`montage.status` keys the delivered flag off `st.key == "deliver"`, which still exists —
no change there.

- [x] **Step 4: Green + commit**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -q`

```bash
git add scripts/montage.py tests/lib/test_montage.py && git commit -m "feat(episode-qc): the router gains the episodes and QC stages"
```

---

### Task 8: the real-ffmpeg proof

**Files:**
- Create: `tests/integration/test_episode_qc.py`

- [x] **Step 1: Write the test**

```python
"""The QC gate against real pixels (design docs/specs/2026-08-08-episode-qc-design.md §11).

Fixtures prove the contract; this proves the GATE: a reel that is not fully judged, is
judged stale, or carries a blocking verdict does not get assembled — and a clean one
delivers with the QC state on its attestation."""
import json
from pathlib import Path

import pytest

from scripts import edl_to_reel, episode_qc, reframe
from scripts.lib import provenance
from scripts.lib.models import Delivery, LayoutSpec, ReframeSpec, ReelEpisode, ReelManifest


def _episode(sample_clip, tmp, x_const, name):
    """A real reframed episode with its sidecars named the way process_episode names
    them, so ReelEpisode.path/meta are coherent and pack can derive the scratch dir."""
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    route = [dict(t=i / 10, x=float(x_const), y=540.0, w=140.0, h=320.0) for i in range(30)]
    (d / "route.json").write_text(json.dumps(route))
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=(105.0, 122.0, 137.0), delivery=Delivery("native"),
                       layout=LayoutSpec(mode="fill"))
    clip = str(tmp / f"{name}.mp4")
    reframe.reframe(spec, str(sample_clip), str(d / "route.json"), clip, str(d / "path.json"))
    return ReelEpisode(manifest={"segment": str(sample_clip), "target_dur": 3.0,
                                 "composition": "center", "grid": "thirds"},
                       clip=clip, route=str(d / "route.json"),
                       path=str(d / "path.json"), meta=str(d / "path.meta.json"))


def _episodes_json(tmp_path, sample_clip):
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    eps = [_episode(sample_clip, tmp_path, 645, "ep0"),
           _episode(sample_clip, tmp_path, 1045, "ep1")]
    rm = ReelManifest(episodes=eps, target_dur=6.0, changelog="qc proof")
    p = out / "EPISODES.json"
    rm.write(p)
    return p, rm


def _judge(packets, i, severity=None):
    d = Path(packets) / f"ep{i}"
    d.mkdir(parents=True, exist_ok=True)
    fs = [] if severity is None else [
        {"axis": "hero", "severity": severity, "evidence": f"ep{i} follows a bystander",
         "route": "edit-plan", "suggestion": "pin the hero by cast name"}]
    (d / "findings.json").write_text(json.dumps(
        {"summary": f"ep{i}", "reviewer": "integration", "findings": fs}))


@pytest.mark.integration
def test_pack_gives_the_judge_pixels_and_numbers(tmp_path, sample_clip):
    p, rm = _episodes_json(tmp_path, sample_clip)
    res = episode_qc.pack(str(p), str(tmp_path / "qc"))
    assert res["episodes"] == 2
    ev = json.loads((tmp_path / "qc" / "ep0" / "evidence.json").read_text())
    assert (tmp_path / "qc" / "ep0" / "strip.jpg").exists()
    assert ev["intent"]["composition"] == "center"
    assert ev["naturalness"]["stats"]["frames"] == episode_qc.SENSOR_FRAMES
    assert set(ev["naturalness"]["flags"]) == {"blown_highlights", "crushed_blacks",
                                               "colour_cast", "oversaturated", "flat"}
    assert ev["geometry"] is not None          # the path.meta sidecar reframe wrote


@pytest.mark.integration
def test_a_clean_run_delivers_and_the_attestation_names_the_judged_bytes(tmp_path, sample_clip):
    p, rm = _episodes_json(tmp_path, sample_clip)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    _judge(tmp_path / "qc", 0)
    _judge(tmp_path / "qc", 1, "minor")
    episode_qc.build(str(p), str(tmp_path / "qc"), str(p.parent))
    res = edl_to_reel.assemble_reel(str(p), str(tmp_path / "work"))
    assert res["status"] == "delivered"
    att = json.loads(Path(str(provenance.attest_path(res["output"]))).read_text())
    assert att["episode_qc"]["state"] == "judged"
    assert att["episode_qc"]["judged"]["0"] == provenance.digest_file(rm.episodes[0].clip)
    assert att["episode_qc"]["reprocessed_after"] == []


@pytest.mark.integration
def test_a_blocking_verdict_stops_the_reel_and_writes_nothing(tmp_path, sample_clip):
    p, _ = _episodes_json(tmp_path, sample_clip)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    _judge(tmp_path / "qc", 0)
    _judge(tmp_path / "qc", 1, "blocking")
    episode_qc.build(str(p), str(tmp_path / "qc"), str(p.parent))
    res = edl_to_reel.assemble_reel(str(p), str(tmp_path / "work"))
    assert res["finding"]["reason"] == "episode-qc-blocking"
    assert list(p.parent.glob("REEL_v*")) == []


@pytest.mark.integration
def test_a_re_rendered_episode_invalidates_its_verdict(tmp_path, sample_clip):
    """The digest binding is load-bearing, not decorative: judge, then rebuild ep0's
    bytes, and the verdict no longer describes the clip that would be assembled."""
    p, rm = _episodes_json(tmp_path, sample_clip)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    _judge(tmp_path / "qc", 0)
    _judge(tmp_path / "qc", 1)
    episode_qc.build(str(p), str(tmp_path / "qc"), str(p.parent))
    Path(rm.episodes[0].clip).write_bytes(
        Path(rm.episodes[0].clip).read_bytes() + b"\x00")      # a different render
    res = edl_to_reel.assemble_reel(str(p), str(tmp_path / "work"))
    assert res["finding"]["reason"] == "episode-qc-stale"
    assert "episode 0" in res["finding"]["problems"][0]


@pytest.mark.integration
def test_an_unjudged_reel_never_reaches_assembly(tmp_path, sample_clip):
    p, _ = _episodes_json(tmp_path, sample_clip)
    res = edl_to_reel.assemble_reel(str(p), str(tmp_path / "work"))
    assert res["finding"]["reason"] == "episode-qc-missing"
```

- [x] **Step 2: Run**

Run: `.venv/bin/python -m pytest tests/integration/test_episode_qc.py -q`
Expected: PASS (5 tests). If `assemble_reel` cannot deliver because the two synthetic
clips fail a *reel* gate, use the x-offsets from `tests/integration/test_reel_backhalf.py`
(645 / 1045) exactly — they are the pair already proven to pass variety and colour.

- [x] **Step 3: Commit**

```bash
git add tests/integration/test_episode_qc.py && git commit -m "test(episode-qc): the gate against real pixels"
```

---

### Task 9: the judge — skill, template, wiring

**Files:**
- Create: `skills/episode-qc/SKILL.md`, `skills/episode-qc/episode-reviewer.md`
- Modify: `skills/using-montage/SKILL.md`, `skills/process-episode/SKILL.md`,
  `tests/test_skill_convention.py`

- [x] **Step 1: Write `skills/episode-qc/SKILL.md`**

Requirements the suite enforces (`tests/test_skill_convention.py`): the description
leads with `Conveyor stage`; every pipeline command goes through `"$VG" scripts.X`;
the launcher path comes from the recorded root
(`${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root`) — copy the preamble from
`skills/pacing/SKILL.md` verbatim. Add `"episode-qc"` to the test's `RUNNERS` set in
the same commit.

The skill's process:

1. `"$VG" scripts.episode_qc pack --episodes <run>/out/EPISODES.json --out-dir <run>/qc`
2. Dispatch **one fresh judge subagent per episode, at most 3 at a time**, each given
   its own packet dir and `episode-reviewer.md`. A judge reads ONLY its own episode —
   never another's packet, never the EDL as a whole.
3. Each judge writes `<run>/qc/ep{i}/findings.json`.
4. `"$VG" scripts.episode_qc build --episodes <run>/out/EPISODES.json --packets <run>/qc
   --out-dir <run>/out`
5. Report the verdict. On `revise`, surface every blocking finding with its route and
   stop — the fix belongs to the routed stage, and phase 2 will refuse anyway.

Boundaries to state explicitly:
- **You may not lower a gate.** No waiver exists here by design (§7). A blocking
  finding is answered by fixing the episode, not by re-judging until it passes.
- **You do not write `clip_digest`.** `build` stamps it.
- **An empty findings list is a claim**, and the artifact cannot distinguish a
  diligent judge from a lazy one (§12) — say so, so nobody reads the green tick as
  proof.

- [x] **Step 2: Write `skills/episode-qc/episode-reviewer.md`**

The dispatch template, modelled on `skills/reel-review/reel-reviewer.md`. It must:
- name the five axes and what each one is about (§4);
- require every finding to cite a frame timestamp, a storyboard mark, or a measured
  number in `evidence`;
- state the intent-relative rule: composition is judged against `intent.composition`
  (`center` / `lead` / `break`), never against a global thirds rule;
- state the sensor's status: the flags in `naturalness` are advisory first cuts — a
  `crushed_blacks` flag on a deliberate night shot is not a finding;
- state when the `hero` axis is **not judgeable**: `intent.pan` is set (a generated
  path has no tracked subject, so there is no marker), and say that not-judgeable is
  reported, never passed;
- reserve `blocking` for what makes the episode unusable in the reel, and say plainly
  that a blocking finding stops the whole reel;
- require the output shape `{"summary": str, "reviewer": str, "findings": [...]}`
  written to the packet's own `findings.json`.

- [x] **Step 3: Wire `using-montage`**

Replace step 12's single `edl_to_reel` call with the three stages, keeping the existing
`<run>` layout:

```bash
"$VG" scripts.edl_to_reel <run>/EDL.json --project <run>/project.json \
  --footage-root <footage_root> --work-dir <run>/work --out-dir <run>/out \
  [--music <run>/MUSIC.json] --stop-after-episodes
# then the episode-qc SKILL, then:
"$VG" scripts.edl_to_reel --from-episodes <run>/out/EPISODES.json \
  --work-dir <run>/work [--titles <run>/TITLES.json]
```

State that the QC stage is **required** and that a blocking verdict stops the run there
with the routed finding — it is not one of the three checkpoints, and the human is not
asked to approve a clean pass.

- [x] **Step 4: Correct `process-episode`**

Its "Editorial gate" section describes a per-episode judgment that the conveyor never
performs — `edl_to_reel` calls the orchestrator as a Python function. Rewrite the
section to say: this gate applies when you are driving ONE episode by hand; in a
router-driven run the per-episode judgment is the `episode-qc` stage, which judges the
delivered clip before the reel is assembled. Keep the `stabilize` and degraded-route
guidance unchanged.

- [x] **Step 5: Green + commit**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py tests/test_plugin_manifests.py -q`

```bash
git add skills tests/test_skill_convention.py && git commit -m "feat(episode-qc): the judge skill, its template, and the router wiring"
```

---

### Task 10: mutation battery, suite, docs

**Files:**
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`, `docs/fixes-backlog.md`
  (#3 status), `CLAUDE.md` (registry rows), `docs/plans/2026-08-08-episode-qc.md`
  (tick the boxes)

- [x] **Step 1: Run the mutation battery**

Each mutation is applied to the production source, the named tests are run, the source
is reverted. A mutation that survives is a **coverage hole to close in this task**, not
a note for later.

| # | Mutation | Must fail |
|---|----------|-----------|
| 1 | `gate` returns `(None, [])` when a verdict is missing | `test_an_unjudged_episode_stops_the_reel` |
| 2 | `gate` checks blocking BEFORE stale | `test_a_moved_digest_stops_the_reel_before_any_blocking_finding` |
| 3 | `gate` compares `clip_digest` with `!=` removed (always equal) | `test_a_re_rendered_episode_invalidates_its_verdict` |
| 4 | `build_qc` takes `clip_digest` from the judge's file | `test_build_stamps_the_digest_itself_…` |
| 5 | `_raw` returns `{}` instead of raising for a missing findings.json | `test_build_refuses_an_unjudged_episode` |
| 6 | `EpisodeVerdict.verdict` reads a stored `verdict` key | `test_a_stored_verdict_cannot_lie_about_itself` |
| 7 | `assemble_reel` runs `build_reel` before the gate | `test_a_blocking_verdict_stops_the_reel_and_writes_nothing` |
| 8 | `edl_to_reel` (single-shot) sets `episode_qc: {"state": "judged"}` | `test_the_single_command_path_records_that_nothing_judged_it` |
| 9 | `build_reel` reports `reprocessed: []` unconditionally | `test_a_delivered_reel_reports_which_episodes_were_reprocessed` |
| 10 | `naturalness.measure` pools pixels across frames instead of averaging | `test_frames_are_averaged_not_concatenated` |
| 11 | the `episode-qc` Stage kind flips to `optional` | `test_the_qc_stage_sits_between_the_episodes_and_the_reel` |

- [x] **Step 2: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: everything green, no test skipped that was not skipped before this branch.

- [x] **Step 3: Docs**

- `docs/build-status.md`: a Done entry (what landed, the §8 hole in plain words, the
  §12 limits, and what the mutation battery did and did not probe), and rewrite the
  **Next action** P3 paragraph — after this slice only the hero-conditioned re-scan
  remains open in P3.
- `docs/pipeline-map.md`: the deliver stage becomes three.
- `docs/fixes-backlog.md` #3: status → LANDED with the date, naming the half that did
  NOT land (rendering still runs as a Python fan-out, deliberately — design §2).
- `CLAUDE.md`: two registry rows (design + plan), in the established one-line style.
- Tick every `- [ ]` in this plan.

- [x] **Step 4: Commit**

```bash
git add -A && git commit -m "docs(episode-qc): status, pipeline map, backlog, registry"
```

---

## Self-review

**Spec coverage.** §2 the split → Task 6; §3 artifacts → Tasks 4/6; §4 contract →
Tasks 1-2; §5 sensor → Task 3; §6 packet → Task 4; §7 gate → Tasks 2/6; §8 staleness
record → Task 5; §9 router + skills → Tasks 7/9; §10 attestation → Task 5; §11 proofs
→ Task 8; §12 limits → stated in the SKILL (Task 9) and build-status (Task 10).

**Placeholders.** Production code is complete everywhere — the first draft's
`__import_finding` stub in Task 4 is gone, replaced by the real loop. What remains
elided is test *scaffolding* in Tasks 5 and 6, where a `...` stands for an existing
file's fixture pattern (`tests/lib/test_build_reel.py`'s monkeypatched driver,
`tests/lib/test_edl_to_reel.py`'s `_manifest` helper). Every assertion — the part
that must not drift — is written out. Task 8, which has no such precedent to lean on,
is complete top to bottom.

**Type consistency.** `gate(qc, digests) -> (reason, problems)` is used with that
signature in Tasks 2 and 6. `ReelQC.by_idx` is defined in Task 1 and consumed in Task
2. `episode_qc.build(episodes, packets, out_dir)` is called with three positional
arguments in Tasks 4, 8 and the SKILL. `ReelManifest.write` (Task 0) is used in Tasks
6 and 8.
