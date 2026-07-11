# Reel Back Half (Phase A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **STATUS: COMPLETE (2026-07-11)** — all tasks landed on branch `feat/reel-back-half`.

**Goal:** Turn N locked `process-episode` outputs into one delivered silent reel — `assemble` (lossless master) → `check_reel` (mechanical gate + failure attribution) → `deliver` (one encode, versioned).

**Architecture:** Three thin entry scripts over one shared `scripts/lib/assembly.py` concat core, plus typed contracts in `scripts/lib/models.py` (`ExportProfile`, `ReelCheckSpec`, `ReelFailure`, `ReelReport`). Exactly one encode, at deliver; a hard gate refuses a failed reel. Silent phase — audio/safe-zone checks report `passed=None`, never a silent pass. The retry *loop* is the Phase A.5 follow-on, not this plan.

**Tech Stack:** Python 3.13, ffmpeg/ffprobe (via `scripts/lib/proc.run`), Pillow + numpy (frame means), imagehash (variety phash), pytest. Design: `docs/specs/2026-07-10-reel-back-half-design.md`.

---

## File Structure

| File | Create/Modify | Responsibility |
|------|---------------|----------------|
| `scripts/lib/models.py` | Modify | + `ExportProfile`/`REEL_H264`, `ReelCheckSpec`, `ReelFailure`, `ReelReport` (typed, raise-on-bad, JSON round-trip) |
| `scripts/lib/assembly.py` | Create | `probe_stream`/`StreamInfo`/`matches`, `assemble()` — probe uniformity → concat-copy \| normalize-outlier; fail loud |
| `scripts/assemble.py` | Create | CLI over `lib.assembly.assemble` |
| `scripts/check_reel.py` | Create | Whole-reel mechanical gate on the master → `ReelReport` with attributed `fail_reasons` |
| `scripts/deliver.py` | Create | master → `out/REEL_v{n}.mp4` per `ExportProfile` + `out/VERSIONS.md`; refuses a failed report |
| `references/ffmpeg-recipes.md` | Modify | + final-concat + deliver-encode recipes |
| `tests/lib/test_models.py` | Modify | `ExportProfile`/`ReelCheckSpec`/`ReelFailure`/`ReelReport` unit tests |
| `tests/lib/test_assembly.py` | Create | uniformity/concat decision logic (mocked proc/ffprobe) |
| `tests/lib/test_check_reel.py` | Create | boundaries/black/length/color/variety + attribution (mocked ffmpeg) |
| `tests/lib/test_deliver.py` | Create | version naming, VERSIONS.md, gate-refuses-failed (mocked proc) |
| `tests/integration/test_reel_backhalf.py` | Create | real-ffmpeg golden: 2 episodes → assemble → check_reel → deliver |
| `docs/build-status.md`, `docs/specs/2026-07-05-montage-skillset-design.md`, `CLAUDE.md` | Modify | docs sync (Task 11) |

---

### Task 0: `ExportProfile` + `REEL_H264`

**Files:**
- Modify: `scripts/lib/models.py` (append after `StoryboardSpec`)
- Test: `tests/lib/test_models.py`

- [x] **Step 1: Write the failing test**

Append to `tests/lib/test_models.py`:

```python
from scripts.lib.models import ExportProfile, REEL_H264


def test_export_profile_defaults_are_the_silent_reel():
    p = REEL_H264
    assert (p.vcodec, p.crf, p.pix_fmt, p.container) == ("libx264", 18, "yuv420p", "mp4")
    assert p.faststart is True and p.acodec is None


def test_export_profile_silent_args_use_an_and_faststart():
    a = REEL_H264.args()
    assert "-an" in a
    assert a[a.index("-movflags") + 1] == "+faststart"
    assert "-c:v" in a and a[a.index("-c:v") + 1] == "libx264"
    assert "scale=" not in " ".join(a)          # deliver never re-scales


def test_export_profile_maxrate_adds_bufsize():
    a = ExportProfile(maxrate_kbps=9000).args()
    assert a[a.index("-maxrate") + 1] == "9000k"
    assert a[a.index("-bufsize") + 1] == "18000k"


def test_export_profile_audio_args_when_voiced():
    a = ExportProfile(acodec="aac", abitrate_kbps=192).args()
    assert "-an" not in a
    assert a[a.index("-c:a") + 1] == "aac" and a[a.index("-b:a") + 1] == "192k"


@pytest.mark.parametrize("kw, msg", [
    (dict(crf=60), "0..51"),
    (dict(crf=-1), "0..51"),
    (dict(pix_fmt=""), "pixel format"),
    (dict(vcodec=""), "codec name"),
    (dict(container=""), "container"),
    (dict(fps=0), "positive number or None"),
    (dict(maxrate_kbps=0), "positive int or None"),
    (dict(abitrate_kbps=192), "acodec is None"),
])
def test_export_profile_rejects_bad_construction(kw, msg):
    with pytest.raises(ValueError, match=msg):
        ExportProfile(**kw)
```

`import pytest` is already at the top of `tests/lib/test_models.py`.

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k export_profile -q`
Expected: FAIL — `ImportError: cannot import name 'ExportProfile'`.

- [x] **Step 3: Write minimal implementation**

Append to `scripts/lib/models.py`:

```python
@dataclass
class ExportProfile:
    """One typed export profile (design §2). New platforms are new instances,
    not new code. Silent by default (acodec None → -an); Phase B sets acodec."""
    vcodec: str = "libx264"
    crf: int = 18
    preset: str = "medium"
    pix_fmt: str = "yuv420p"
    container: str = "mp4"
    faststart: bool = True
    fps: float | None = None
    maxrate_kbps: int | None = None
    acodec: str | None = None
    abitrate_kbps: int | None = None

    def __post_init__(self) -> None:
        if not (isinstance(self.vcodec, str) and self.vcodec):
            raise ValueError("ExportProfile.vcodec must be a non-empty codec name")
        if isinstance(self.crf, bool) or not isinstance(self.crf, int) or not 0 <= self.crf <= 51:
            raise ValueError(f"ExportProfile.crf must be an int in 0..51, got {self.crf!r}")
        if not (isinstance(self.pix_fmt, str) and self.pix_fmt):
            raise ValueError("ExportProfile.pix_fmt must be a non-empty pixel format")
        if not (isinstance(self.container, str) and self.container):
            raise ValueError("ExportProfile.container must be a non-empty container name")
        if self.fps is not None and not (isinstance(self.fps, (int, float)) and self.fps > 0):
            raise ValueError(f"ExportProfile.fps must be a positive number or None, got {self.fps!r}")
        if self.maxrate_kbps is not None and not (isinstance(self.maxrate_kbps, int)
                                                  and not isinstance(self.maxrate_kbps, bool)
                                                  and self.maxrate_kbps > 0):
            raise ValueError(f"ExportProfile.maxrate_kbps must be a positive int or None, got {self.maxrate_kbps!r}")
        if self.acodec is not None and not (isinstance(self.acodec, str) and self.acodec):
            raise ValueError("ExportProfile.acodec must be a non-empty codec name or None")
        if self.abitrate_kbps is not None:
            if self.acodec is None:
                raise ValueError("ExportProfile.abitrate_kbps is set but acodec is None — a bitrate "
                                 "with no audio codec cannot be applied; set acodec or clear abitrate_kbps")
            if isinstance(self.abitrate_kbps, bool) or not isinstance(self.abitrate_kbps, int) \
                    or self.abitrate_kbps <= 0:
                raise ValueError(f"ExportProfile.abitrate_kbps must be a positive int or None, got {self.abitrate_kbps!r}")

    def args(self) -> list[str]:
        """ffmpeg OUTPUT args (no -i, no output path). The one place the encode
        landmines live — yuv420p, faststart; deliver adds no scale (even dims come
        in from the master by construction)."""
        a = ["-c:v", self.vcodec, "-crf", str(self.crf), "-preset", self.preset,
             "-pix_fmt", self.pix_fmt]
        if self.maxrate_kbps is not None:
            a += ["-maxrate", f"{self.maxrate_kbps}k", "-bufsize", f"{2 * self.maxrate_kbps}k"]
        if self.fps is not None:
            a += ["-r", str(self.fps)]
        if self.acodec is None:
            a += ["-an"]
        else:
            a += ["-c:a", self.acodec]
            if self.abitrate_kbps is not None:
                a += ["-b:a", f"{self.abitrate_kbps}k"]
        if self.faststart:
            a += ["-movflags", "+faststart"]
        return a


REEL_H264 = ExportProfile()
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k export_profile -q`
Expected: PASS (12 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: ExportProfile typed delivery profile (reel back half Task 0)"
```

---

### Task 1: `ReelCheckSpec`

**Files:**
- Modify: `scripts/lib/models.py`
- Test: `tests/lib/test_models.py`

- [x] **Step 1: Write the failing test**

```python
from scripts.lib.models import ReelCheckSpec


def test_reel_check_spec_defaults():
    s = ReelCheckSpec(target_dur=6.0)
    assert s.variety_min == 8 and s.color_delta_max == 12.0


@pytest.mark.parametrize("kw, msg", [
    (dict(target_dur=0), "target_dur"),
    (dict(target_dur=6.0, variety_min=-1), "variety_min"),
    (dict(target_dur=6.0, color_delta_max=0), "color_delta_max"),
])
def test_reel_check_spec_rejects_bad(kw, msg):
    with pytest.raises(ValueError, match=msg):
        ReelCheckSpec(**kw)
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k reel_check_spec -q`
Expected: FAIL — `ImportError: cannot import name 'ReelCheckSpec'`.

- [x] **Step 3: Write minimal implementation**

Append to `scripts/lib/models.py`:

```python
@dataclass
class ReelCheckSpec:
    """Thresholds for the whole-reel mechanical gate (design §4), mirrors CheckSpec."""
    target_dur: float
    variety_min: int = 8               # min phash Hamming distance between adjacent episodes
    color_delta_max: float = 12.0      # §9 across-cut mean-RGB delta ceiling

    def __post_init__(self) -> None:
        if not isinstance(self.target_dur, (int, float)) or self.target_dur <= 0:
            raise ValueError(f"ReelCheckSpec.target_dur must be a positive number, got {self.target_dur!r}")
        if isinstance(self.variety_min, bool) or not isinstance(self.variety_min, int) or self.variety_min < 0:
            raise ValueError(f"ReelCheckSpec.variety_min must be a non-negative int, got {self.variety_min!r}")
        if not isinstance(self.color_delta_max, (int, float)) or self.color_delta_max <= 0:
            raise ValueError(f"ReelCheckSpec.color_delta_max must be a positive number, got {self.color_delta_max!r}")
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k reel_check_spec -q`
Expected: PASS (4 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: ReelCheckSpec thresholds (reel back half Task 1)"
```

---

### Task 2: `ReelFailure` + `ReelReport`

**Files:**
- Modify: `scripts/lib/models.py`
- Test: `tests/lib/test_models.py`

- [x] **Step 1: Write the failing test**

```python
from scripts.lib.models import ReelFailure, ReelReport, CheckResult


def _rr():
    return ReelReport(
        checks={"black": CheckResult("black", True, {"black_start": []}),
                "length": CheckResult("length", False, {"dur": 7.0, "target": 6.0}),
                "beat": CheckResult("beat", None, {"status": "not-implemented"})},
        fail_reasons=[ReelFailure("length", "pacing", None, {"dur": 7.0})],
        episode_count=2, wall_s=1.5)


def test_reel_report_overall_false_on_a_failed_check():
    assert _rr().overall is False


def test_reel_report_none_check_never_fails():
    rr = ReelReport(checks={"beat": CheckResult("beat", None, {"status": "x"})})
    assert rr.overall is True


def test_reel_report_round_trips():
    rr = _rr()
    back = ReelReport.from_dict(rr.to_dict())
    assert back.to_dict() == rr.to_dict()
    assert back.episode_count == 2 and back.wall_s == 1.5
    assert back.fail_reasons[0].check == "length" and back.fail_reasons[0].escalate_to == "pacing"


def test_reel_report_writes_json(tmp_path):
    p = tmp_path / "reel.json"
    _rr().write(p)
    assert ReelReport.from_dict(json.loads(p.read_text())).overall is False
```

`import json` is already at the top of `tests/lib/test_models.py`.

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k reel_report -q`
Expected: FAIL — `ImportError: cannot import name 'ReelFailure'`.

- [x] **Step 3: Write minimal implementation**

Append to `scripts/lib/models.py`:

```python
@dataclass
class ReelFailure:
    """One attributed reel-check failure (design §177 machine-readable). The
    Phase A.5 driver reads escalate_to/episode_idx straight off this."""
    check: str
    escalate_to: str                        # "reprocess" | "edit-plan" | "pacing"
    episode_idx: int | None = None
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"check": self.check, "escalate_to": self.escalate_to,
                "episode_idx": self.episode_idx, "detail": self.detail}

    @classmethod
    def from_dict(cls, d: dict) -> "ReelFailure":
        return cls(check=d["check"], escalate_to=d["escalate_to"],
                   episode_idx=d.get("episode_idx"), detail=d.get("detail", {}))


@dataclass
class ReelReport:
    """Whole-reel check artifact (design §2). Reuses CheckResult; overall is a
    property (a None check never fails), mirroring the episode Report."""
    checks: dict[str, CheckResult]
    fail_reasons: list[ReelFailure] = field(default_factory=list)
    episode_count: int = 0
    wall_s: float = 0.0                      # §11 binding: wall-time in every check report

    @property
    def overall(self) -> bool:
        return all(c.passed is not False for c in self.checks.values())

    def to_dict(self) -> dict:
        return {"checks": {n: c.to_dict() for n, c in self.checks.items()},
                "overall": self.overall,
                "fail_reasons": [f.to_dict() for f in self.fail_reasons],
                "episode_count": self.episode_count, "wall_s": self.wall_s}

    @classmethod
    def from_dict(cls, d: dict) -> "ReelReport":
        checks = {}
        for n, cd in d["checks"].items():
            if "pass" in cd:
                checks[n] = CheckResult(n, cd["pass"], {k: v for k, v in cd.items() if k != "pass"})
            else:
                checks[n] = CheckResult(n, None, dict(cd))
        return cls(checks=checks,
                   fail_reasons=[ReelFailure.from_dict(f) for f in d.get("fail_reasons", [])],
                   episode_count=d.get("episode_count", 0), wall_s=d.get("wall_s", 0.0))

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k reel_report -q`
Expected: PASS (4 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: ReelFailure + ReelReport wire-contracts (reel back half Task 2)"
```

---

### Task 3: `lib/assembly` — probe + uniformity

**Files:**
- Create: `scripts/lib/assembly.py`
- Test: `tests/lib/test_assembly.py`

- [x] **Step 1: Write the failing test**

Create `tests/lib/test_assembly.py`:

```python
import json
import pytest
from scripts.lib import assembly
from scripts.lib.assembly import StreamInfo


def test_matches_is_true_only_when_all_fields_agree():
    ref = dict(dims=(606, 1080), fps=30.0)
    assert assembly.matches(StreamInfo(606, 1080, 30.0, "yuv420p", "h264"), **ref)
    assert not assembly.matches(StreamInfo(606, 1080, 59.94, "yuv420p", "h264"), **ref)
    assert not assembly.matches(StreamInfo(608, 1080, 30.0, "yuv420p", "h264"), **ref)
    assert not assembly.matches(StreamInfo(606, 1080, 30.0, "yuv444p", "h264"), **ref)


def test_probe_stream_missing_file_fails_loud(tmp_path):
    with pytest.raises(RuntimeError, match="missing"):
        assembly.probe_stream(str(tmp_path / "nope.mp4"))


def test_probe_stream_no_video_stream_fails_loud(tmp_path, monkeypatch):
    f = tmp_path / "audio_only.mp4"
    f.write_text("x")
    monkeypatch.setattr(assembly.proc, "run",
                        lambda cmd, **k: type("C", (), {"stdout": b'{"streams": []}'})())
    with pytest.raises(RuntimeError, match="no video stream"):
        assembly.probe_stream(str(f))


def test_probe_stream_parses_fps_ratio(tmp_path, monkeypatch):
    f = tmp_path / "e.mp4"
    f.write_text("x")
    payload = json.dumps({"streams": [{"width": 606, "height": 1080,
                                       "r_frame_rate": "30000/1001", "pix_fmt": "yuv420p",
                                       "codec_name": "h264"}]}).encode()
    monkeypatch.setattr(assembly.proc, "run",
                        lambda cmd, **k: type("C", (), {"stdout": payload})())
    info = assembly.probe_stream(str(f))
    assert info.w == 606 and info.h == 1080 and abs(info.fps - 29.97) < 0.01
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_assembly.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.assembly'`.

- [x] **Step 3: Write minimal implementation**

Create `scripts/lib/assembly.py`:

```python
"""Normalize-and-concat core for reel assembly (design 2026-07-10 §3). Shared by
the final assembler and, later, the draft assembler."""
import json
from dataclasses import dataclass
from pathlib import Path

from scripts.lib import proc


@dataclass(frozen=True)
class StreamInfo:
    w: int
    h: int
    fps: float
    pix_fmt: str
    vcodec: str                     # ffprobe codec_name, e.g. "h264" for libx264 output


def probe_stream(path: str) -> StreamInfo:
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"{p} is missing — assemble needs every locked episode on disk; "
                           "check the EDL paths or re-run process-episode for it")
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height,r_frame_rate,pix_fmt,codec_name",
           "-of", "json", str(p)]
    out = proc.run(cmd).stdout.decode("utf-8", errors="replace")
    streams = json.loads(out).get("streams", [])
    if not streams:
        raise RuntimeError(f"{p} has no video stream — assemble cannot place it in the reel")
    s = streams[0]
    num, den = s["r_frame_rate"].split("/")
    if float(den) == 0:
        raise RuntimeError(f"{p} reports r_frame_rate {s['r_frame_rate']!r} — unusable, re-render it")
    return StreamInfo(int(s["width"]), int(s["height"]), float(num) / float(den),
                      s["pix_fmt"], s["codec_name"])


def matches(info: StreamInfo, dims: tuple[int, int], fps: float,
            pix_fmt: str = "yuv420p", vcodec: str = "h264") -> bool:
    return (info.w == dims[0] and info.h == dims[1] and abs(info.fps - fps) < 0.01
            and info.pix_fmt == pix_fmt and info.vcodec == vcodec)
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_assembly.py -q`
Expected: PASS (4 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/assembly.py tests/lib/test_assembly.py
git commit -m "feat: assembly.probe_stream + uniformity match (reel back half Task 3)"
```

---

### Task 4: `lib/assembly.assemble()` + `scripts/assemble.py` CLI

**Files:**
- Modify: `scripts/lib/assembly.py`
- Create: `scripts/assemble.py`
- Test: `tests/lib/test_assembly.py`

- [x] **Step 1: Write the failing test**

Append to `tests/lib/test_assembly.py`:

```python
from types import SimpleNamespace


def _capture(monkeypatch, infos):
    """Mock probe_stream (per-path StreamInfo) + proc.run (record cmds)."""
    calls = []
    monkeypatch.setattr(assembly, "probe_stream", lambda p: infos[str(Path(p).name)])
    monkeypatch.setattr(assembly.proc, "run",
                        lambda cmd, **k: calls.append(cmd) or SimpleNamespace(stdout=b""))
    return calls


def _uniform():
    return StreamInfo(606, 1080, 30.0, "yuv420p", "h264")


def test_uniform_episodes_concat_copy_without_reencode(tmp_path, monkeypatch):
    from pathlib import Path
    eps = [str(tmp_path / f"e{i}.mp4") for i in range(3)]
    calls = _capture(monkeypatch, {f"e{i}.mp4": _uniform() for i in range(3)})
    assembly.assemble(eps, (606, 1080), 30.0, str(tmp_path / "w" / "master.mp4"))
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "scale=" not in joined                    # nothing re-encoded
    assert "concat" in joined and "-c copy" in joined


def test_one_fps_outlier_is_normalized_alone(tmp_path, monkeypatch):
    eps = [str(tmp_path / f"e{i}.mp4") for i in range(3)]
    infos = {f"e{i}.mp4": _uniform() for i in range(3)}
    infos["e1.mp4"] = StreamInfo(606, 1080, 59.94, "yuv420p", "h264")
    calls = _capture(monkeypatch, infos)
    assembly.assemble(eps, (606, 1080), 30.0, str(tmp_path / "w" / "master.mp4"))
    scale_cmds = [c for c in calls if any("scale=606:1080" in str(x) for x in c)]
    assert len(scale_cmds) == 1                       # only the outlier


def test_assemble_zero_episodes_fails_loud(tmp_path):
    with pytest.raises(RuntimeError, match=">= 1 locked episode"):
        assembly.assemble([], (606, 1080), 30.0, str(tmp_path / "m.mp4"))
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_assembly.py -k "assemble or outlier or uniform" -q`
Expected: FAIL — `AttributeError: module 'scripts.lib.assembly' has no attribute 'assemble'`.

- [x] **Step 3: Write minimal implementation**

Append to `scripts/lib/assembly.py`:

```python
def _normalize(src: str, dims: tuple[int, int], fps: float, out: str) -> str:
    # the landmine (§12): concat of non-uniform streams desyncs. Normalize the
    # outlier ONLY — matched episodes are copied untouched.
    vf = f"scale={dims[0]}:{dims[1]},fps={fps},format=yuv420p"
    proc.run(["ffmpeg", "-y", "-i", src, "-vf", vf,
              "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-an", out])
    return out


def assemble(episodes: list[str], dims: tuple[int, int], fps: float, out_master: str) -> str:
    """Concat locked episodes into one silent master. Reference = the caller's
    intended (dims, fps) — the same delivery process-episode rendered to. All
    match → lossless -c copy; an outlier is normalized alone, then copy-concat."""
    if len(episodes) < 1:
        raise RuntimeError("assemble needs >= 1 locked episode, got none — the EDL "
                           "produced no episodes for this reel")
    work = Path(out_master).parent
    work.mkdir(parents=True, exist_ok=True)
    entries: list[str] = []
    for i, ep in enumerate(episodes):
        info = probe_stream(ep)
        if matches(info, dims, fps):
            entries.append(str(Path(ep).resolve()))
        else:
            norm = str(work / f"_norm_{i:03d}.mp4")
            _normalize(ep, dims, fps, norm)
            entries.append(str(Path(norm).resolve()))
    listfile = work / "_concat.txt"
    listfile.write_text("".join(f"file '{p}'\n" for p in entries))
    proc.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
              "-c", "copy", out_master])
    return out_master
```

Create `scripts/assemble.py`:

```python
"""Final reel assembler (чистовик, design §3): ordered locked episodes → one
silent master via lib.assembly. The draft assembler is a later sibling over the
same core."""
import argparse
from scripts.lib import assembly


def main() -> None:
    ap = argparse.ArgumentParser(description="Concat locked episodes into a reel master.")
    ap.add_argument("episodes", nargs="+", help="ordered locked out/<ep>.mp4 paths")
    ap.add_argument("--out", required=True, help="master output path")
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--fps", type=float, required=True)
    a = ap.parse_args()
    assembly.assemble(a.episodes, (a.width, a.height), a.fps, a.out)


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_assembly.py -q`
Expected: PASS (7 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/lib/assembly.py scripts/assemble.py tests/lib/test_assembly.py
git commit -m "feat: assemble() concat-copy | normalize-outlier + CLI (reel back half Task 4)"
```

---

### Task 5: `check_reel` — boundaries + black + length

**Files:**
- Create: `scripts/check_reel.py`
- Test: `tests/lib/test_check_reel.py`

- [x] **Step 1: Write the failing test**

Create `tests/lib/test_check_reel.py`:

```python
import pytest
from scripts import check_reel
from scripts.lib.models import ReelCheckSpec


class _Stub:
    """Stub the ffmpeg-touching helpers so check_reel logic is unit-testable.
    durations: per-episode seconds. blacks: black_start times on the master.
    means: {t: (r,g,b)}. hashes: {t: int} used as a fake ImageHash distance base."""
    def __init__(self, durations, blacks=(), means=None, hashes=None):
        self.durations = durations
        self.blacks = list(blacks)
        self.means = means or {}
        self.hashes = hashes or {}

    def install(self, monkeypatch):
        eps_dur = iter(self.durations + [sum(self.durations)])  # episodes..., then master
        # raising=False: _frame_mean/_phash_bits/_hamming do not exist on the module
        # until Tasks 6-7, but _Stub is written once in Task 5 and reused there.
        monkeypatch.setattr(check_reel, "_probe_dur", lambda v: next(eps_dur))
        monkeypatch.setattr(check_reel, "_black_hits", lambda m: self.blacks)
        monkeypatch.setattr(check_reel, "_frame_mean",
                            lambda v, t: self.means.get(round(t, 3), (100.0, 120.0, 130.0)),
                            raising=False)
        monkeypatch.setattr(check_reel, "_phash_bits",
                            lambda v, t: self.hashes.get(round(t, 3), 0), raising=False)
        monkeypatch.setattr(check_reel, "_hamming", lambda a, b: abs(a - b), raising=False)


def test_length_passes_within_half_second(tmp_path, monkeypatch):
    _Stub([3.0, 3.0]).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["length"].passed is True
    assert rep.checks["black"].passed is True


def test_length_fails_and_attributes_to_pacing(tmp_path, monkeypatch):
    _Stub([3.0, 4.0]).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["length"].passed is False and rep.overall is False
    f = [x for x in rep.fail_reasons if x.check == "length"][0]
    assert f.escalate_to == "pacing" and f.episode_idx is None


def test_black_hit_attributes_to_the_owning_episode(tmp_path, monkeypatch):
    # a black frame at t=4.0 lands in episode 1 (spans 3.0..6.0)
    _Stub([3.0, 3.0], blacks=[4.0]).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["black"].passed is False
    f = [x for x in rep.fail_reasons if x.check == "black"][0]
    assert f.episode_idx == 1 and f.escalate_to == "reprocess"


def test_audio_and_safezone_checks_are_not_implemented(tmp_path, monkeypatch):
    _Stub([3.0, 3.0]).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    for name in ("beat", "loudness", "safe_zones"):
        assert rep.checks[name].passed is None
    assert rep.overall is True          # None never fails the reel
    assert rep.wall_s >= 0.0 and rep.episode_count == 2
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.check_reel'`.

- [x] **Step 3: Write minimal implementation**

Create `scripts/check_reel.py`:

```python
"""Whole-reel mechanical gate (design §4, montage §5.13 mechanical half). Silent
phase: audio/safe-zone checks report passed=None, never a silent pass. Returns a
ReelReport with attributed fail_reasons for the Phase A.5 driver."""
import re
import time

from scripts.lib import proc
from scripts.lib.models import CheckResult, ReelCheckSpec, ReelFailure, ReelReport

_NOT_IMPL = {"beat": "silent reel — lands in Phase B (music)",
             "loudness": "silent reel — lands in Phase B (audio-mix)",
             "safe_zones": "needs per-episode route + a platform safe-margin table"}


def _probe_dur(video: str) -> float:
    out = proc.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nk=1:nw=1", video]).stdout.decode().strip()
    return float(out)


def _black_hits(master: str) -> list[float]:
    # blackdetect prints "black_start:<t>" to stderr; any hit fails (spec §9 gate)
    r = proc.run(["ffmpeg", "-i", master, "-vf", "blackdetect=d=0.05:pic_th=0.98",
                  "-an", "-f", "null", "-"])
    err = (r.stderr or b"").decode("utf-8", errors="replace")
    return [float(m) for m in re.findall(r"black_start:(\d+\.?\d*)", err)]


def _span_of(t: float, durations: list[float]) -> int:
    edge = 0.0
    for i, d in enumerate(durations):
        edge += d
        if t < edge:
            return i
    return len(durations) - 1


def run(master: str, episodes: list[str], spec: ReelCheckSpec, out_report: str) -> ReelReport:
    t0 = time.monotonic()
    durations = [_probe_dur(e) for e in episodes]
    total = _probe_dur(master)
    checks: dict[str, CheckResult] = {}
    fails: list[ReelFailure] = []

    hits = _black_hits(master)
    checks["black"] = CheckResult("black", not hits, {"black_start": hits})
    for h in hits:
        fails.append(ReelFailure("black", "reprocess", _span_of(h, durations), {"t": h}))

    length_ok = abs(total - spec.target_dur) <= 0.5
    checks["length"] = CheckResult("length", length_ok,
                                   {"dur": round(total, 3), "target": spec.target_dur})
    if not length_ok:
        fails.append(ReelFailure("length", "pacing", None,
                                 {"dur": round(total, 3), "target": spec.target_dur}))

    for name, reason in _NOT_IMPL.items():
        checks[name] = CheckResult(name, None, {"status": "not-implemented", "reason": reason})

    rep = ReelReport(checks=checks, fail_reasons=fails, episode_count=len(episodes),
                     wall_s=round(time.monotonic() - t0, 3))
    rep.write(out_report)
    return rep
```

Note: `_frame_mean`, `_phash_bits`, `_hamming` are stubbed by the test now and added in Tasks 6–7; the boundary/mid helpers arrive with them.

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py -q`
Expected: PASS (4 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/check_reel.py tests/lib/test_check_reel.py
git commit -m "feat: check_reel black + length + not-implemented stubs (reel back half Task 5)"
```

---

### Task 6: `check_reel` — color across cuts + attribution

**Files:**
- Modify: `scripts/check_reel.py`
- Test: `tests/lib/test_check_reel.py`

- [x] **Step 1: Write the failing test**

Append to `tests/lib/test_check_reel.py`:

```python
def test_color_across_cuts_passes_when_neighbours_match(tmp_path, monkeypatch):
    # one cut at t=3.0; both sides ~equal → delta 0 → pass
    _Stub([3.0, 3.0], means={2.95: (100.0, 120.0, 130.0), 3.05: (101.0, 121.0, 131.0),
                             1.5: (100.0, 120.0, 130.0), 4.5: (101.0, 121.0, 131.0)}
          ).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["color_across_cuts"].passed is True


def test_color_across_cuts_blames_the_episode_farther_from_the_reel_median(tmp_path, monkeypatch):
    # 3 episodes, cut 1 at t=6.0 has a big jump; ep2 (span mid t=7.5) is the outlier
    means = {5.95: (100.0, 120.0, 130.0), 6.05: (160.0, 120.0, 130.0),  # cut 1 sides
             2.95: (100.0, 120.0, 130.0), 3.05: (100.0, 120.0, 130.0),  # cut 0 sides (match)
             1.5: (100.0, 120.0, 130.0), 4.5: (100.0, 120.0, 130.0), 7.5: (160.0, 120.0, 130.0)}
    _Stub([3.0, 3.0, 3.0], means=means).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4", "c.mp4"], ReelCheckSpec(target_dur=9.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["color_across_cuts"].passed is False
    f = [x for x in rep.fail_reasons if x.check == "color_across_cuts"][0]
    assert f.episode_idx == 2 and f.escalate_to == "reprocess"


def test_color_across_cuts_is_not_applicable_for_a_single_episode(tmp_path, monkeypatch):
    _Stub([3.0]).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4"], ReelCheckSpec(target_dur=3.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["color_across_cuts"].passed is None      # no cut to judge
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py -k color -q`
Expected: FAIL — `KeyError: 'color_across_cuts'`.

- [x] **Step 3: Write minimal implementation**

In `scripts/check_reel.py`, add a `tempfile`/`os` import block and the helpers, then wire the check.

Add to the imports at the top (`accumulate` is first used here):

```python
import os
import tempfile
from itertools import accumulate
```

Add these helpers above `run`:

```python
def _sample_frame(video: str, t: float, dst: str) -> str:
    # output-seek (-ss AFTER -i) keeps the landmine lint clean; clips are short so
    # decoding to t is cheap. One still frame at t.
    proc.run(["ffmpeg", "-y", "-i", video, "-ss", f"{t}", "-frames:v", "1", dst])
    return dst


def _frame_mean(video: str, t: float) -> tuple[float, float, float]:
    import numpy as np
    from PIL import Image
    with tempfile.TemporaryDirectory() as d:
        f = _sample_frame(video, t, os.path.join(d, "f.png"))
        a = np.asarray(Image.open(f).convert("RGB"), dtype=float)
    return float(a[..., 0].mean()), float(a[..., 1].mean()), float(a[..., 2].mean())


def _rgb_dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / 3.0


def _boundaries(durations: list[float]) -> list[float]:
    return list(accumulate(durations))[:-1]            # internal cut times


def _midpoints(durations: list[float]) -> list[float]:
    starts = [0.0] + list(accumulate(durations))[:-1]
    return [s + d / 2 for s, d in zip(starts, durations)]


def _channel_median(means: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    import statistics
    return tuple(statistics.median(m[c] for m in means) for c in range(3))
```

Inside `run`, after the length block and **before** the `_NOT_IMPL` loop, insert:

```python
    cuts = _boundaries(durations)
    mids = _midpoints(durations)
    if cuts:
        span_means = [_frame_mean(master, m) for m in mids]
        median = _channel_median(span_means)
        color_ok = True
        worst = None
        for i, bt in enumerate(cuts):
            left = _frame_mean(master, max(0.0, bt - 0.05))
            right = _frame_mean(master, bt + 0.05)
            delta = _rgb_dist(left, right)
            if delta >= spec.color_delta_max:
                color_ok = False
                culprit = i if _rgb_dist(span_means[i], median) >= _rgb_dist(span_means[i + 1], median) else i + 1
                fails.append(ReelFailure("color_across_cuts", "reprocess", culprit,
                                         {"cut": i, "delta": round(delta, 2)}))
                worst = round(delta, 2) if worst is None else max(worst, round(delta, 2))
        checks["color_across_cuts"] = CheckResult("color_across_cuts", color_ok,
                                                  {"worst_delta": worst} if worst else {})
    else:
        checks["color_across_cuts"] = CheckResult("color_across_cuts", None,
                                                  {"status": "n/a", "reason": "single episode, no cut"})
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py -q`
Expected: PASS (7 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/check_reel.py tests/lib/test_check_reel.py
git commit -m "feat: check_reel color-across-cuts + median attribution (reel back half Task 6)"
```

---

### Task 7: `check_reel` — variety (phash) + CLI

**Files:**
- Modify: `scripts/check_reel.py`
- Create: (CLI at the tail of `scripts/check_reel.py`)
- Test: `tests/lib/test_check_reel.py`

- [x] **Step 1: Write the failing test**

Append to `tests/lib/test_check_reel.py`:

```python
def test_variety_flags_a_near_duplicate_pair(tmp_path, monkeypatch):
    # ep0 and ep1 identical hash (distance 0 < variety_min) → fail, blame ep1
    _Stub([3.0, 3.0], hashes={1.5: 100, 4.5: 100}).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0, variety_min=8), str(tmp_path / "r.json"))
    assert rep.checks["variety"].passed is False
    f = [x for x in rep.fail_reasons if x.check == "variety"][0]
    assert f.episode_idx == 1 and f.escalate_to == "edit-plan"


def test_variety_passes_for_distinct_episodes(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0, variety_min=8), str(tmp_path / "r.json"))
    assert rep.checks["variety"].passed is True
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py -k variety -q`
Expected: FAIL — `KeyError: 'variety'`.

- [x] **Step 3: Write minimal implementation**

Add helpers above `run` in `scripts/check_reel.py`:

```python
def _phash_bits(video: str, t: float):
    import imagehash
    from PIL import Image
    with tempfile.TemporaryDirectory() as d:
        f = _sample_frame(video, t, os.path.join(d, "f.png"))
        return imagehash.phash(Image.open(f))


def _hamming(a, b) -> int:
    return a - b               # imagehash defines __sub__ as Hamming distance
```

Inside `run`, after the color block and before `_NOT_IMPL`, insert:

```python
    if len(episodes) > 1:
        hashes = [_phash_bits(master, m) for m in mids]
        var_ok = True
        worst = None
        for i in range(len(hashes) - 1):
            dist = _hamming(hashes[i], hashes[i + 1])
            if dist < spec.variety_min:
                var_ok = False
                fails.append(ReelFailure("variety", "edit-plan", i + 1,
                                         {"pair": [i, i + 1], "distance": dist}))
                worst = dist if worst is None else min(worst, dist)
        checks["variety"] = CheckResult("variety", var_ok,
                                        {"min_distance": worst} if worst is not None else {})
    else:
        checks["variety"] = CheckResult("variety", None,
                                        {"status": "n/a", "reason": "single episode"})
```

Add the CLI at the tail of `scripts/check_reel.py`:

```python
def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Whole-reel mechanical check.")
    ap.add_argument("master")
    ap.add_argument("episodes", nargs="+", help="ordered locked episode paths")
    ap.add_argument("--target-dur", type=float, required=True)
    ap.add_argument("--report", required=True)
    a = ap.parse_args()
    rep = run(a.master, a.episodes, ReelCheckSpec(target_dur=a.target_dur), a.report)
    raise SystemExit(0 if rep.overall else 1)


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_check_reel.py -q`
Expected: PASS (9 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/check_reel.py tests/lib/test_check_reel.py
git commit -m "feat: check_reel variety phash + CLI (reel back half Task 7)"
```

---

### Task 8: `deliver` — version naming + VERSIONS.md

**Files:**
- Create: `scripts/deliver.py`
- Test: `tests/lib/test_deliver.py`

- [x] **Step 1: Write the failing test**

Create `tests/lib/test_deliver.py`:

```python
import pytest
from scripts import deliver


def test_next_version_is_1_on_empty_dir(tmp_path):
    assert deliver._next_version(str(tmp_path), "mp4") == 1


def test_next_version_is_max_plus_one(tmp_path):
    (tmp_path / "REEL_v1.mp4").write_text("x")
    (tmp_path / "REEL_v2.mp4").write_text("x")
    (tmp_path / "notes.txt").write_text("x")
    assert deliver._next_version(str(tmp_path), "mp4") == 3


def test_log_version_creates_header_then_appends(tmp_path):
    deliver._log_version(str(tmp_path), 1, "first cut")
    deliver._log_version(str(tmp_path), 2, "regraded ep1")
    text = (tmp_path / "VERSIONS.md").read_text()
    assert text.startswith("# Reel versions")
    assert "| first cut" in text and "- v2 |" in text and "| regraded ep1" in text
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_deliver.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.deliver'`.

- [x] **Step 3: Write minimal implementation**

Create `scripts/deliver.py`:

```python
"""Deliver a checked reel master → out/REEL_v{n}.<container> per an ExportProfile,
with a version log (design §5, montage §5.14 + §11 version-log binding). The one
encode of the back half; a hard gate refuses a failed reel."""
import re
from datetime import datetime
from pathlib import Path

from scripts.lib import proc
from scripts.lib.models import ExportProfile, ReelReport


def _next_version(out_dir: str, container: str) -> int:
    rx = re.compile(rf"REEL_v(\d+)\.{re.escape(container)}$")
    ns = [int(m.group(1)) for p in Path(out_dir).glob(f"REEL_v*.{container}")
          if (m := rx.match(p.name))]
    return max(ns) + 1 if ns else 1


def _log_version(out_dir: str, n: int, changelog: str) -> None:
    vf = Path(out_dir) / "VERSIONS.md"
    if not vf.exists():
        vf.write_text("# Reel versions\n\n")
    stamp = datetime.now().strftime("%Y-%m-%d")
    with vf.open("a") as f:
        f.write(f"- v{n} | {stamp} | {changelog}\n")
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_deliver.py -q`
Expected: PASS (3 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/deliver.py tests/lib/test_deliver.py
git commit -m "feat: deliver version naming + VERSIONS.md log (reel back half Task 8)"
```

---

### Task 9: `deliver()` — encode + gate + CLI

**Files:**
- Modify: `scripts/deliver.py`
- Test: `tests/lib/test_deliver.py`

- [x] **Step 1: Write the failing test**

Append to `tests/lib/test_deliver.py`:

```python
from types import SimpleNamespace
from scripts.lib.models import CheckResult, ReelReport, REEL_H264


def _green():
    return ReelReport(checks={"length": CheckResult("length", True, {})}, episode_count=2)


def _red():
    return ReelReport(checks={"length": CheckResult("length", False, {})}, episode_count=2)


def test_deliver_refuses_a_failed_reel(tmp_path):
    with pytest.raises(RuntimeError, match="does not ship a failed reel"):
        deliver.deliver("m.mp4", REEL_H264, str(tmp_path), "x", _red())


def test_deliver_encodes_v1_and_logs(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(deliver.proc, "run",
                        lambda cmd, **k: calls.append(cmd) or SimpleNamespace(stdout=b""))
    out = deliver.deliver("master.mp4", REEL_H264, str(tmp_path), "first cut", _green())
    assert out.endswith("REEL_v1.mp4")
    cmd = calls[0]
    assert "-an" in cmd and cmd[-1].endswith("REEL_v1.mp4") and "master.mp4" in cmd
    assert "scale=" not in " ".join(map(str, cmd))          # no re-scale
    assert (tmp_path / "VERSIONS.md").read_text().count("- v1 |") == 1


def test_deliver_second_run_is_v2(tmp_path, monkeypatch):
    monkeypatch.setattr(deliver.proc, "run",
                        lambda cmd, **k: SimpleNamespace(stdout=b""))
    deliver.deliver("m.mp4", REEL_H264, str(tmp_path), "a", _green())
    (tmp_path / "REEL_v1.mp4").write_text("x")               # simulate the file the mock skipped
    out2 = deliver.deliver("m.mp4", REEL_H264, str(tmp_path), "b", _green())
    assert out2.endswith("REEL_v2.mp4")
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_deliver.py -k "refuses or encodes or v2" -q`
Expected: FAIL — `AttributeError: module 'scripts.deliver' has no attribute 'deliver'`.

- [x] **Step 3: Write minimal implementation**

Append to `scripts/deliver.py`:

```python
def deliver(master: str, profile: ExportProfile, out_dir: str, changelog: str,
            report: ReelReport) -> str:
    """Encode the checked master to the next REEL_v{n} and log the version.
    Hard gate: a failed reel is never shipped (no fix-forward, montage §176)."""
    if not report.overall:
        raise RuntimeError("reel failed check_reel — fix the flagged episodes and re-check; "
                           "deliver does not ship a failed reel (no fix-forward)")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    n = _next_version(out_dir, profile.container)
    out = str(Path(out_dir) / f"REEL_v{n}.{profile.container}")
    proc.run(["ffmpeg", "-y", "-i", master, *profile.args(), out])
    _log_version(out_dir, n, changelog)
    return out


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Deliver a checked reel master.")
    ap.add_argument("master")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--report", required=True, help="ReelReport JSON from check_reel")
    ap.add_argument("--changelog", default="")
    a = ap.parse_args()
    import json
    report = ReelReport.from_dict(json.loads(Path(a.report).read_text()))
    out = deliver(a.master, ExportProfile(), a.out_dir, a.changelog, report)
    print(out)


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_deliver.py -q`
Expected: PASS (6 tests).

- [x] **Step 5: Commit**

```bash
git add scripts/deliver.py tests/lib/test_deliver.py
git commit -m "feat: deliver() encode + hard gate + CLI (reel back half Task 9)"
```

---

### Task 10: Integration golden — the whole slice

**Files:**
- Create: `tests/integration/test_reel_backhalf.py`

- [x] **Step 1: Write the failing test**

Create `tests/integration/test_reel_backhalf.py`:

```python
"""Real-ffmpeg whole-slice proof: 2 distinct episodes (via the real reframe
encoder, the stage inside process-episode that writes the locked clip) →
assemble → check_reel → deliver. Design §7."""
import json
import pytest
from scripts import check_reel, deliver, reframe
from scripts.lib import assembly
from scripts.lib.models import (Delivery, LayoutSpec, ReframeSpec, ReelCheckSpec, REEL_H264)


def _episode(sample_clip, tmp, x_const, name):
    # center composition (no lateral requirement); a constant route x fixes a
    # static crop window. The moving box (white, src-x≈845 at clip t=1.5) lands at
    # a DIFFERENT in-frame position in ep0 vs ep1 → distinct phash (variety passes),
    # while both cut-boundary frames are pure grey → equal mean (color passes).
    route = [dict(t=i / 10, x=float(x_const), y=540.0, w=140.0, h=320.0) for i in range(30)]
    rp = tmp / f"{name}.route.json"
    rp.write_text(json.dumps(route))
    spec = ReframeSpec(composition="center", grid="thirds", canvas=(9, 16),
                       color_means=(105.0, 122.0, 137.0), delivery=Delivery("native"),
                       layout=LayoutSpec(mode="fill"))
    out = str(tmp / f"{name}.mp4")
    reframe.reframe(spec, str(sample_clip), str(rp), out, str(tmp / f"{name}.path.meta.json"))
    return out


@pytest.mark.integration
def test_backhalf_assembles_checks_and_delivers(tmp_path, sample_clip):
    # two crops that frame the moving box at different in-frame positions
    ep0 = _episode(sample_clip, tmp_path, 645, "ep0")    # box on the right of frame
    ep1 = _episode(sample_clip, tmp_path, 1045, "ep1")   # box on the left of frame
    dims = (assembly.probe_stream(ep0).w, assembly.probe_stream(ep0).h)
    fps = assembly.probe_stream(ep0).fps

    master = str(tmp_path / "work" / "master.mp4")
    assembly.assemble([ep0, ep1], dims, fps, master)
    minfo = assembly.probe_stream(master)
    assert (minfo.w, minfo.h) == dims
    assert minfo.w % 2 == 0 and minfo.h % 2 == 0

    total = check_reel._probe_dur(master)
    spec = ReelCheckSpec(target_dur=total, variety_min=4)
    rep = check_reel.run(master, [ep0, ep1], spec, str(tmp_path / "reel.json"))
    assert rep.overall is True
    assert rep.checks["black"].passed is True
    assert rep.checks["length"].passed is True
    assert rep.checks["color_across_cuts"].passed is True
    assert rep.checks["variety"].passed is True
    for name in ("beat", "loudness", "safe_zones"):
        assert rep.checks[name].passed is None

    out_dir = str(tmp_path / "out")
    v1 = deliver.deliver(master, REEL_H264, out_dir, "golden first cut", rep)
    assert v1.endswith("REEL_v1.mp4")
    assert (assembly.probe_stream(v1).w, assembly.probe_stream(v1).h) == dims
    assert "- v1 |" in (tmp_path / "out" / "VERSIONS.md").read_text()

    v2 = deliver.deliver(master, REEL_H264, out_dir, "golden second cut", rep)
    assert v2.endswith("REEL_v2.mp4")
```

- [x] **Step 2: Run test to verify it fails, then passes**

Run: `.venv/bin/python -m pytest tests/integration/test_reel_backhalf.py -q`
Expected: PASS (the scripts exist by now). If `variety` flakes (both grey-dominant crops hash close), the crops differ by box position — but if it fails, confirm the two `_episode` x-values produce visibly different frames before lowering `variety_min`.

If it fails on import or a helper name, reconcile against Tasks 3–9 (this task adds no production code — it only exercises it).

- [x] **Step 3: Commit**

```bash
git add tests/integration/test_reel_backhalf.py
git commit -m "test: real-ffmpeg reel back-half golden (reel back half Task 10)"
```

---

### Task 11: Recipes + docs sync

**Files:**
- Modify: `references/ffmpeg-recipes.md`
- Modify: `docs/build-status.md`
- Modify: `docs/specs/2026-07-05-montage-skillset-design.md` (§9 status line)
- Modify: `CLAUDE.md` (Quick Reference)

- [x] **Step 1: Add ffmpeg recipes**

Append to `references/ffmpeg-recipes.md`:

```markdown
## Final concat (`scripts/lib/assembly.py`)

```
# probe each locked episode; all match (dims,fps,pix_fmt=yuv420p,codec=h264)? →
ffmpeg -y -f concat -safe 0 -i <concat.txt> -c copy <master.mp4>
# an outlier → normalize ONLY it, then concat-copy:
ffmpeg -y -i <outlier> -vf "scale=W:H,fps=FPS,format=yuv420p" \
  -c:v libx264 -crf 18 -preset medium -an <norm.mp4>
```

**Why:** locked episodes share a delivery, so the common path is lossless
`-c copy` (no re-encode). The landmine (landmines.md) is concat of non-uniform
streams — the probe makes normalization surgical, touching only a mismatched
clip. `concat.txt` uses absolute paths with `-safe 0`.

## Deliver encode (`scripts/deliver.py`)

```
ffmpeg -y -i <master.mp4> -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
  [-maxrate Kk -bufsize 2Kk] [-r FPS] -an -movflags +faststart <REEL_v{n}.mp4>
```

**Why:** the ONE encode of the back half — `ExportProfile.args()` is the single
place these flags live, so they cannot drift across callers. No `scale`: the
master's dims are already even by construction, so deliver cannot reintroduce the
odd-dim landmine. `-an` while the reel is silent (Phase A); Phase B sets an audio
codec. `+faststart` moves the moov atom for social streaming.
```

- [x] **Step 2: Sync build-status, montage §9, and CLAUDE.md**

In `docs/build-status.md`, add a `## Done` bullet (dated 2026-07-10) recording
the reel back half: `assemble`/`check_reel`/`deliver`, the typed contracts
(`ExportProfile`/`ReelReport`/`ReelFailure`/`ReelCheckSpec`), the lossless-master
→ one-encode-at-deliver design, the silent-phase `passed=None` checks, the
version log, and the real-ffmpeg golden. Note the retry loop is the Phase A.5
follow-on. Update **Next action** to point at Phase A.5 (`build_reel` +
`reel_orchestration` + the reframe color override) then Phase B (music).

In `docs/specs/2026-07-05-montage-skillset-design.md` §9, update the "Status"
line under the check table: `color across cuts`, `variety`, `length` are now
**implemented** in `check_reel`; `beat`, `loudness`, `safe-zones` remain
`planned` (report `not-implemented`, never a silent pass).

In `CLAUDE.md` Quick Reference, add two rows:
- Reel back-half design → `docs/specs/2026-07-10-reel-back-half-design.md`
- Reel back-half plan → `docs/plans/2026-07-10-reel-back-half.md`

- [x] **Step 3: Verify the whole suite is green**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 286 prior + the new unit tests + 1 integration golden, no regressions.

- [x] **Step 4: Commit**

```bash
git add references/ffmpeg-recipes.md docs/build-status.md \
  docs/specs/2026-07-05-montage-skillset-design.md CLAUDE.md
git commit -m "docs: sync recipes, build-status, montage §9, registry (reel back half Task 11)"
```

---

## Notes for the executor

- **Scripts run as modules:** `.venv/bin/python -m pytest …`; never `python scripts/x.py`.
- **Fail loud with a remedy** — every raise names what to do next (see existing `models.py`/`proc.py`).
- **Landmines:** deliver adds no `scale` (even dims come from the master); `-ss` in `check_reel._sample_frame` is output-seek (after `-i`) to stay lint-clean; concat normalizes non-uniform streams.
- **Out of scope (do not build):** the `build_reel` driver + `reel_orchestration` + reframe color override (Phase A.5); `beat`/`loudness`/`safe_zones` numeric checks + audio-mix (Phase B); the draft assembler; secondary-aspect re-reframe (Phase F).
- **Final review:** after Task 11, a whole-slice review + a mutation spot-check on the attribution logic (the one place a silent wrong-culprit could hide), matching the layouts plan's close-out.
```

