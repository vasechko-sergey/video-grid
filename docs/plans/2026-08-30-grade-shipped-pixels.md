# Grade the pixels that ship — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `match_grade` measures each episode's tracked crop instead of its whole
source frame, which requires the route to exist first — so `edl_to_reel`'s phase 1
splits at the geometry boundary, `probe grade` gains a pre-encode mode, and a
blocking `tone_match` check puts a number on the result.

**Architecture:** One reordering, no new instrument. `lib/matchgrade.py`'s pure
core does not change. `edl_to_reel` phase 1 becomes geometry → (conduct) → render,
with `GEOMETRY.json` between them. `process_episode` gains a `stop_after="geometry"`
early return and a `prepared_source` parameter that lets a driver honestly pair a
frozen route with the stabilized file it was measured on.

**Tech stack:** Python 3, ffmpeg via `lib/ffbin` + `lib/proc`, numpy for
histograms, pytest.

**Spec:** [docs/specs/2026-08-30-grade-shipped-pixels-design.md](../specs/2026-08-30-grade-shipped-pixels-design.md)

---

## Global Constraints

These bind every task. A reviewer checks each diff against them.

1. **`lib/matchgrade.py` does not change.** If a task edits it, that task is
   wrong. The decision maths is already correct; only its input moves.
2. **One ruler.** After Task 0, `color.percentiles` is reached from exactly two
   places: `color_measure.measure_profile` (a whole clip) and
   `color_measure._percentiles_from_gray` (everything else). `probe._tone` is
   deleted, not kept beside them.
3. **`-ss` never appears in a frame-selection command.** Frames are selected with
   `select=`, appended at the END of a chain via `RenderPlan.with_tail` (§12's
   `select`-before-`fps=` landmine; the landmine lint's seventh check enforces it
   for planned chains).
4. **Fail loud with a remedy.** Every new refusal names what to do next, in the
   style of the refusals already in the file being edited.
5. **Whole-object asserts.** Tests compare whole dataclasses/dicts where the
   codebase already does; see `docs/testing-guide.md`.
6. **Scripts are modules.** `pythonpath = .`; run tests with `.venv/bin/python -m
   pytest`. Never `python scripts/foo.py`.
7. **A mutation check is a step, not a suggestion.** Where a task says "revert X
   and confirm test Y goes RED", run it and record the outcome in the report.
8. **Mutation batteries run under `PYTHONDONTWRITEBYTECODE=1`** — a one-byte edit
   can match the previous file's size and mtime-second, and CPython then serves a
   stale `.pyc`.
9. **Do not install anything.** No `brew`, `pip install`, `npm`, `uv`, no
   `setup.sh`. Verification is read-only plus pytest.
10. **Never `git checkout --`, `git restore`, `git reset --hard` or `git stash`.**
    Undo a mutation by re-applying the inverse edit, then `git diff` to confirm
    the tree is clean.
11. **The preserved run at `/Users/serg/Downloads/untitled folder/` is read-only.**
    Nothing is written there, ever. Scratch goes to the session scratchpad.

---

## File structure

| File | Change |
|---|---|
| `scripts/lib/manifest.py` | +`COLOUR_KEYS`, +`COLOUR_IDENTITY`, +`strip_colour` |
| `scripts/color_measure.py` | +`FRAMES`, `sample_times`, `_percentiles_from_gray`, `crop_percentiles`, `clip_percentiles`, `measure_crop` |
| `scripts/lib/models.py` | +`EpisodeGeometry`, +`ReelGeometry`, +`ReelCheckSpec.tone_match_max`, +`ReelManifest.tone_target` |
| `scripts/lib/edl.py` | +`EDL.tone_target` (+ `to_dict`/`from_dict`/`to_markdown`) |
| `scripts/process_episode.py` | +`stop_after`, +`prepared_source` |
| `scripts/edl_to_reel.py` | +`build_geometry`, +`render_from_geometry`, +2 CLI flags |
| `scripts/match_grade.py` | `--geometry` replaces `--edl`+`--footage-root` |
| `scripts/probe.py` | +`--geometry`; `_tone` deleted |
| `scripts/check_reel.py` | +`tone_match` |
| `scripts/build_reel.py` | thread `tone_target` into `check_reel.run` |
| `scripts/montage.py` | +`episodes-geometry`; `match-grade` → required |
| `skills/match-grade/SKILL.md`, `skills/using-montage/SKILL.md` | the new order |

---

## Task 0: the ruler, in one place

**Files:**
- Modify: `scripts/lib/manifest.py`
- Modify: `scripts/color_measure.py`
- Modify: `scripts/probe.py` (imports only — `_COLOUR_KEYS`/`_COLOUR_IDENTITY` move out)
- Test: `tests/integration/test_color_measure.py`

- [ ] **Step 1: move the colour-key registry to `lib/manifest.py`**

Cut `_COLOUR_KEYS` and `_COLOUR_IDENTITY` out of `scripts/probe.py` (with their
comments — they are about `Manifest`'s dataclass fields, which is what this file
owns) and paste them at the end of `scripts/lib/manifest.py`, renamed public,
plus one helper:

```python
# The colour block, as it crosses edl.to_manifest_dict. A CLOSED set, because a
# caller that re-applies a fresh block must DROP these first: to_manifest_dict
# omits highlight_red, tone_src and tone_dst at their identity, so a plain merge
# would keep a value the author has just deleted from the EDL.
COLOUR_KEYS = ("color_means", "white_balance", "black_point", "highlight",
               "highlight_red", "saturation", "shadow_red", "mid_blue", "dip",
               "tone_src", "tone_dst")

# The value Manifest.from_dict falls back to for each of COLOUR_KEYS when the JSON
# key is absent or explicitly null. DERIVED from Manifest's dataclass fields rather
# than hand-copied, so this cannot drift the day someone edits a default above.
# Safe only because every Manifest field uses a plain `= value` default, never
# `field(default_factory=...)` — a default_factory field's own .default is
# dataclasses.MISSING and would poison this map silently. Re-check that invariant
# before ever widening COLOUR_KEYS.
COLOUR_IDENTITY = {f.name: f.default for f in dataclasses.fields(Manifest)
                   if f.name in COLOUR_KEYS}


def strip_colour(md: dict) -> dict:
    """`md` with every colour field at its identity value — the same episode,
    ungraded. The measuring path plans a render from this so the reading is of the
    footage, not of a grade already applied; the geometry path stores it so a
    changed CUT can be told from a changed GRADE (design 2026-08-30 §2.2)."""
    out = {k: v for k, v in md.items() if k not in COLOUR_KEYS}
    out.update(COLOUR_IDENTITY)
    return out
```

Add `import dataclasses` at the top of `manifest.py` if absent. In `probe.py`,
replace both constants with `from scripts.lib.manifest import COLOUR_IDENTITY, COLOUR_KEYS`
and rename the ~8 use sites.

- [ ] **Step 2: write the failing tests for the new readers**

Append to `tests/integration/test_color_measure.py`:

```python
def test_clip_percentiles_reads_a_finished_file(tmp_path):
    """Two bands, 50/50: p5 lands in the dark one, p95 in the bright one."""
    clip = _two_band_clip(tmp_path, dark=40, bright=200)      # helper below
    p5, p50, p95 = color_measure.clip_percentiles(str(clip), [0.5])
    assert p5 < 60 and p95 > 180


def test_crop_percentiles_reads_the_crop_not_the_frame(tmp_path):
    """The design's §0.1 finding, as a test: a frame whose TOP half is blown out
    and whose bottom half is mid-grey reads very differently once the crop
    excludes the top. If these ever agree, the measuring path has stopped going
    through the render plan."""
    src, md, route = _banded_episode(tmp_path)                # helper below
    whole = color_measure.measure_profile(str(src), at=0.5)
    crop = color_measure.measure_crop(md, str(src), str(route))
    assert max(abs(a - b) for a, b in zip(whole, crop)) > matchgrade.MATCH_EPS


def test_sample_times_never_touches_the_ends():
    assert color_measure.sample_times(3.0, 3) == [0.5, 1.5, 2.5]
    assert color_measure.sample_times(1.0, 1) == [0.5]
```

Run: `.venv/bin/python -m pytest tests/integration/test_color_measure.py -v`
Expected: FAIL — `module 'scripts.color_measure' has no attribute 'clip_percentiles'`.

The two helpers build real files with ffmpeg (this is an `integration` test, and
real bytes are the point). `_two_band_clip` stacks two `color=` sources with
`vstack` at 640x640, 1s, 30fps, `-pix_fmt yuv420p -color_range tv`.
`_banded_episode` returns `(src, manifest_dict, route_json)` where the manifest is
a minimal `fill` episode at a 1:1 delivery whose crop covers only the bottom half,
and `route.json` is a constant centre in the bottom band. Copy the shape of the
existing episode fixtures in `tests/integration/test_reframe*.py`.

- [ ] **Step 3: implement**

Append to `scripts/color_measure.py` (and add the imports it needs:
`from scripts import process_episode, reframe`, `from scripts.lib import manifest as manifest_lib`,
`from scripts.lib.models import Delivery`, `from scripts.lib import orchestration as orch`):

```python
FRAMES = 3          # start / middle / end of a span, at (i+0.5)/N — never the first
                    # or last frame, which a dip or a bookend can own. Measured
                    # (design 2026-08-30 §0.4): 5 and 9 frames give the same residual
                    # median and a slightly worse maximum, because the residual is not
                    # sampling noise.


def sample_times(dur: float, frames: int = FRAMES) -> list[float]:
    """`frames` sample times spread over `dur`, at (k+0.5)/frames of it."""
    if not isinstance(frames, int) or isinstance(frames, bool) or frames < 1:
        raise ValueError(f"frames must be an integer >= 1, got {frames!r}")
    return [((k + 0.5) / frames) * dur for k in range(frames)]


def _select(times: list[float], fps: float) -> str:
    nums = [round(t * fps) for t in times]
    return "select='" + "+".join(rf"eq(n\,{n})" for n in nums) + "'"


def _percentiles_from_gray(raw: bytes, want: int, dims: tuple[int, int],
                           where: str) -> tuple[float, float, float]:
    """(p5, p50, p95) of a pooled gray rawvideo buffer — the ONE ruler.

    Pooled, not averaged per frame: the three frames describe one distribution,
    which is what a tone profile is. Exactly `want` frames are demanded so a select
    that silently returned fewer fails here instead of reporting a profile of
    whatever arrived (§12's select landmine, in the form it takes when nothing
    crashes).

    The count is checked against the frame SIZE, not by divisibility. `len(raw) %
    want` reads as a frame-count check and is not one: len(raw) is always
    N_actual * frame_bytes, so whenever frame_bytes divides `want` the test passes
    for every N_actual — and at want=3 a 1920x1080 frame, this project's own
    default delivery, does exactly that. Both callers hold the real dimensions
    (StreamInfo.w/h; ResolvedLayout.out_w/out_h), so the exact check is free."""
    if not raw:
        raise RuntimeError(f"{where}: ffmpeg decoded no frames")
    w, h = dims
    got, rem = divmod(len(raw), w * h)
    if got != want or rem:
        raise RuntimeError(f"{where}: asked for {want} frames and got {got}"
                           f"{' plus a partial frame' if rem else ''} at {w}x{h} — "
                           f"a frame is missing or duplicated; check the select "
                           f"expression sits at the END of the chain, after any fps=")
    hist = np.bincount(np.frombuffer(raw, dtype=np.uint8), minlength=256)[:256]
    return color.percentiles([int(c) for c in hist])


def clip_percentiles(clip: str, times: list[float]) -> tuple[float, float, float]:
    """The ruler over a FINISHED file — what check_reel reads off the master."""
    info = assembly.probe_stream(clip)
    out = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", clip,
                    "-vf", f"{_select(times, info.fps)},format=gray",
                    "-vsync", "0", "-frames:v", str(len(times)),
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    return _percentiles_from_gray(out, len(times), (info.w, info.h),
                                  f"clip_percentiles({clip})")


def crop_percentiles(plan: "reframe.RenderPlan", src: str,
                     times: list[float]) -> tuple[float, float, float]:
    """The ruler over the pixels a RenderPlan would encode — the crop, scaled to
    the delivery, with whatever colour the plan carries. The select is appended at
    the END through with_tail: before the chain's own `fps=` it would emit one
    frame N times (§12)."""
    out = proc.run([ffbin.ffmpeg(), "-v", "error", "-i", src,
                    *plan.with_tail(f"{_select(times, plan.fps)},format=gray"),
                    "-t", f"{plan.dur:.6f}", "-vsync", "0",
                    "-frames:v", str(len(times)),
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    return _percentiles_from_gray(out, len(times),
                                  (plan.rl.out_w, plan.rl.out_h),
                                  f"crop_percentiles({src})")


def plan_ungraded(manifest_dict: dict, src: str,
                  route: str | None) -> "reframe.RenderPlan":
    """The render this episode would get with NO grade — the plan a measurement
    reads through, and the plan probe renders stills from when it is showing the
    footage rather than a grade."""
    m = manifest_lib.Manifest.from_dict(manifest_lib.strip_colour(manifest_dict))
    params = dict(orch.DEFAULT_PARAMS)
    if m.smooth_window_s is not None:
        params["smooth_window_s"] = m.smooth_window_s
    spec = process_episode.build_reframe_spec(m, Delivery.from_spec(m.delivery), params)
    return reframe.plan_render(spec, src, route)


def measure_crop(manifest_dict: dict, src: str, route: str | None, *,
                 frames: int = FRAMES) -> tuple[float, float, float]:
    """(p5, p50, p95) of the episode's own tracked crop, ungraded — the reading
    `color.tone_arg`'s docstring has always asked its callers for.

    Measured (design 2026-08-30 §0.1) against the whole source frame at the window
    midpoint, which is what match_grade read before this: seven of eight real
    episodes differ by more than matchgrade.MATCH_EPS, median 14 and max 36 luma
    units. Costs 0.65s per episode."""
    plan = plan_ungraded(manifest_dict, src, route)
    return crop_percentiles(plan, src, sample_times(plan.dur, frames))
```

Run the tests: PASS.

- [ ] **Step 4: mutation check — the ruler is the crop's**

Change `plan_ungraded` to pass `route=None`... it will raise (a non-pan episode
needs a route), which is the wrong mutation. Instead: in `measure_crop`, replace
`crop_percentiles(plan, src, ...)` with `measure_profile(src, at=plan.dur / 2)`.
`test_crop_percentiles_reads_the_crop_not_the_frame` MUST go RED. Re-apply the
inverse edit and confirm `git diff` is clean.

- [ ] **Step 5: full file suite + commit**

```bash
.venv/bin/python -m pytest tests/integration/test_color_measure.py tests/lib/test_probe.py -q
git add -A && git commit -m "feat: one gray ruler, and a crop reading to use it"
```

---

## Task 1: the contracts

**Files:**
- Modify: `scripts/lib/models.py`
- Modify: `scripts/lib/edl.py`
- Test: `tests/lib/test_models.py`, `tests/lib/test_edl.py`

- [ ] **Step 1: failing tests**

`tests/lib/test_models.py`:

```python
def test_reel_geometry_round_trips():
    g = ReelGeometry(episodes=(EpisodeGeometry(manifest={"segment": "a.mp4"},
                                               route="r.json", source="s.mp4",
                                               project_dir="build/ep0"),),
                     edl="EDL.json", provenance={"engine": {"rev": "abc"}})
    assert ReelGeometry.from_dict(g.to_dict()) == g


def test_episode_geometry_refuses_an_empty_source():
    with pytest.raises(ValueError, match="source"):
        EpisodeGeometry(manifest={}, route=None, source="", project_dir="d")


def test_episode_geometry_allows_a_routeless_pan():
    EpisodeGeometry(manifest={}, route=None, source="s.mp4", project_dir="d")


def test_reel_check_spec_tone_match_max_defaults_to_12():
    assert ReelCheckSpec(target_dur=10.0).tone_match_max == 12.0


def test_reel_check_spec_refuses_a_non_positive_tone_match_max():
    with pytest.raises(ValueError, match="tone_match_max"):
        ReelCheckSpec(target_dur=10.0, tone_match_max=0.0)


def test_reel_manifest_carries_the_tone_target(_reel_dict):
    d = dict(_reel_dict); d["tone_target"] = [52.0, 103.5, 191.5]
    assert ReelManifest.from_dict(d).tone_target == (52.0, 103.5, 191.5)


def test_reel_manifest_tone_target_defaults_to_none(_reel_dict):
    d = dict(_reel_dict); d.pop("tone_target", None)
    assert ReelManifest.from_dict(d).tone_target is None
```

**The vacuity guard for the last one:** check the shared `_reel_dict` fixture and
make sure it does NOT already carry `tone_target` — if it does, `d.pop` is what
makes the test real and the assertion would otherwise pass for the wrong reason.
State in the report which it was.

`tests/lib/test_edl.py`: the same pair for `EDL.tone_target` — a round trip
through `to_dict`/`from_dict`, and `None` when the key is absent.

- [ ] **Step 2: implement**

`models.py`, beside `ReelEpisode`:

```python
@dataclass(frozen=True)
class EpisodeGeometry:
    """One episode's geometry, decided and frozen before any colour is measured
    (design 2026-08-30 §2.2).

    `manifest` is stored with its COLOUR BLOCK STRIPPED, and that is the guard,
    not a space saving: --from-geometry re-derives the same stripped manifest from
    the current EDL and refuses any difference, so a cut edited under a frozen
    route is refused while a re-authored grade passes — which is the entire point
    of the seam.

    `route` is None under a pan, exactly as on ReelEpisode: a generated path has no
    observation to freeze. `source` is the file reframe will consume — the segment
    normally, the stabilize pre-stage's output when stabilize is set — recorded by
    the stage that knows rather than inferred from a filename later.
    """
    manifest: dict
    route: str | None
    source: str
    project_dir: str

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, dict):
            raise ValueError("EpisodeGeometry.manifest must be a dict")
        if self.route is not None and not (isinstance(self.route, str) and self.route):
            raise ValueError("EpisodeGeometry.route must be a route.json path or None "
                             "(None = a generated pan path, which has no route)")
        for name in ("source", "project_dir"):
            v = getattr(self, name)
            if not (isinstance(v, str) and v):
                raise ValueError(f"EpisodeGeometry.{name} is empty — it names the file "
                                 f"reframe will consume and the scratch dir holding the "
                                 f"frozen route; both are written by --stop-after-geometry")

    def to_dict(self) -> dict:
        return {"manifest": dict(self.manifest), "route": self.route,
                "source": self.source, "project_dir": self.project_dir}

    @classmethod
    def from_dict(cls, d: dict) -> "EpisodeGeometry":
        if not isinstance(d, dict):
            raise ValueError("EpisodeGeometry.from_dict: expected an object")
        return cls(manifest=d.get("manifest") or {}, route=d.get("route"),
                   source=d.get("source", ""), project_dir=d.get("project_dir", ""))


@dataclass(frozen=True)
class ReelGeometry:
    """GEOMETRY.json — phase 1a's output and match_grade's input."""
    episodes: tuple[EpisodeGeometry, ...]
    edl: str
    provenance: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.episodes:
            raise ValueError("ReelGeometry.episodes is empty — run "
                             "edl_to_reel --stop-after-geometry first")
        for k, e in enumerate(self.episodes):
            if not isinstance(e, EpisodeGeometry):
                raise ValueError(f"ReelGeometry.episodes[{k}] must be an EpisodeGeometry")
        if not (isinstance(self.edl, str) and self.edl):
            raise ValueError("ReelGeometry.edl is empty — it names the EDL this "
                             "geometry was derived from, and match_grade writes it back")

    def to_dict(self) -> dict:
        d = {"episodes": [e.to_dict() for e in self.episodes], "edl": self.edl}
        if self.provenance:
            d["provenance"] = dict(self.provenance)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ReelGeometry":
        if not isinstance(d, dict):
            raise ValueError("ReelGeometry.from_dict: expected a GEOMETRY.json object "
                             "with an 'episodes' list — produce it with "
                             "edl_to_reel --stop-after-geometry")
        eps = d.get("episodes")
        if not isinstance(eps, list):
            raise ValueError("ReelGeometry.from_dict: 'episodes' must be a list")
        return cls(episodes=tuple(EpisodeGeometry.from_dict(e) for e in eps),
                   edl=d.get("edl", ""), provenance=d.get("provenance") or {})

    @classmethod
    def from_json(cls, path: str | Path) -> "ReelGeometry":
        return cls.from_dict(json.loads(Path(path).read_text()))

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))
```

`ReelCheckSpec`: add the field after `length_retime_max` —

```python
    tone_match_max: float = 12.0       # max per-anchor luma distance from the reel's
                                       # common tone target an episode may land at.
                                       # Measured (design 2026-08-30 §0.6) mid-gap
                                       # between a healthy maximum of 8.0 and an
                                       # ungraded minimum of 19.5, both on one shoot.
```

and in `__post_init__`, beside `length_retime_max`'s check:

```python
        if not isinstance(self.tone_match_max, (int, float)) or self.tone_match_max <= 0:
            raise ValueError(f"ReelCheckSpec.tone_match_max must be a positive number of "
                             f"luma units, got {self.tone_match_max!r}")
```

`ReelManifest`: add `tone_target: tuple[float, float, float] | None = None` after
`outro`, validate it (three numbers in 0-255, non-decreasing, or None), carry it
through `from_dict` (`tuple(d["tone_target"]) if d.get("tone_target") else None`),
`to_dict` (`list(...) if not None`), and **`check_spec`**:

```python
    @property
    def check_spec(self) -> ReelCheckSpec:
        return ReelCheckSpec(self.target_dur, self.variety_min)
```

leave `check_spec` alone — `tone_match_max` keeps its default; the target itself
travels as a separate argument to `check_reel.run` (Task 6), because it is data
about this reel, not a threshold.

`edl.py`: `EDL.tone_target: tuple[float, float, float] | None = None`, same
validation, carried in `to_dict`/`from_dict`, and one line in `to_markdown` when
set:

```python
        if self.tone_target is not None:
            lines.append("- **Tone target:** "
                         + "/".join(f"{v:.0f}" for v in self.tone_target)
                         + " (p5/p50/p95 luma, measured on each episode's crop)")
```

placed beside the existing `look` line so an unset target moves no golden.

- [ ] **Step 3: run + commit**

```bash
.venv/bin/python -m pytest tests/lib/test_models.py tests/lib/test_edl.py -q
git add -A && git commit -m "feat: geometry contracts, the reel's tone target, the gate's ceiling"
```

---

## Task 2: `process_episode` stops at geometry, and can be handed one

**Files:**
- Modify: `scripts/process_episode.py`
- Test: `tests/lib/test_process_episode.py`

- [ ] **Step 1: failing tests**

```python
def test_stop_after_geometry_returns_the_route_and_the_source(tmp_path, monkeypatch):
    """The seam: tracking ran, nothing was encoded."""
    md = _episode_manifest(tmp_path)
    calls = []
    monkeypatch.setattr(process_episode.reframe, "reframe",
                        lambda *a, **k: calls.append("reframe"))
    res = process_episode.process_episode(md, tmp_path / "ep0", stop_after="geometry")
    assert res["status"] == "geometry"
    assert res["route"] == str(tmp_path / "ep0" / "route.json")
    assert res["source"] == md["segment"]
    assert calls == []                       # the encode never ran


def test_stop_after_geometry_refuses_an_unknown_value(tmp_path):
    res = process_episode.process_episode(_episode_manifest(tmp_path), tmp_path / "ep0",
                                          stop_after="colour")
    assert res["status"] == "needs_input"
    assert "stop_after" in res["problems"][0]


def test_prepared_source_unlocks_stabilize_with_a_frozen_route(tmp_path, monkeypatch):
    """The pairing --from-geometry asserts, and the ONLY way to assert it."""
    md = _episode_manifest(tmp_path); md["stabilize"] = True
    prepared = tmp_path / "ep0" / "stabilized.mp4"
    ...                                       # write the file, fake reframe/check
    monkeypatch.setattr(process_episode.vidstab, "stabilize",
                        lambda *a, **k: pytest.fail("the pre-stage must not re-run"))
    res = process_episode.process_episode(md, tmp_path / "ep0",
                                          route_path=str(route), prepared_source=str(prepared))
    assert res["status"] == "mechanical_pass"


def test_stabilize_still_refuses_a_bare_route(tmp_path):
    md = _episode_manifest(tmp_path); md["stabilize"] = True
    res = process_episode.process_episode(md, tmp_path / "ep0", route_path="r.json")
    assert res["status"] == "needs_input"
    assert "stabilize=true cannot be combined" in res["problems"][0]


def test_prepared_source_without_a_route_is_refused(tmp_path):
    res = process_episode.process_episode(_episode_manifest(tmp_path), tmp_path / "ep0",
                                          prepared_source="s.mp4")
    assert res["status"] == "needs_input"
    assert "prepared_source" in res["problems"][0]
```

Run: FAIL — `process_episode() got an unexpected keyword argument 'stop_after'`.

- [ ] **Step 2: implement**

Signature:

```python
def process_episode(manifest_dict: dict, project_dir: str | Path, route_path: str | None = None,
                    max_attempts: int = 3,
                    project: ProjectConfig | str | Path | None = None,
                    keyframes_path: str | None = None,
                    stop_after: str | None = None,
                    prepared_source: str | None = None) -> dict:
```

Docstring addition:

```
    `stop_after="geometry"` returns after the contradiction gate, before any
    encode: the split edl_to_reel's phase 1 takes so a colour measurement can be
    made on the crop that will ship (design 2026-08-30 §2.1). Every refusal above
    the seam behaves exactly as it does in a full run.

    `prepared_source` is that split's other half — the caller asserting "the
    frozen route in route_path was measured on THIS file", which is the one thing
    the stabilize refusal below cannot know. Not on the CLI: only a driver that
    produced both halves can honestly assert it.
```

Immediately after the `max_attempts` check:

```python
    if stop_after not in (None, "geometry"):
        return {"status": "needs_input", "attempt": 0, "problems": [
            f"stop_after must be None or 'geometry', got {stop_after!r} — 'geometry' "
            f"returns after tracking and the contradiction gate, before any encode"]}
    if prepared_source is not None and route_path is None:
        return {"status": "needs_input", "attempt": 0, "problems": [
            "prepared_source needs route_path: it exists to assert that a frozen route "
            "was measured on that file, and with no route there is nothing to assert. "
            "Pass both, or neither."]}
```

The stabilize refusal gains one condition and one sentence:

```python
    if m.stabilize and route_path is not None and prepared_source is None:
        return {"status": "needs_input", "attempt": 0, "problems": [
            "stabilize=true cannot be combined with a supplied --route: the frozen "
            "route was measured against unknown pixels, and applying it to the "
            "stabilized segment would re-inject the shake vidstab removed. Drop "
            "--route (a pan ignores it; a tracked episode re-tracks on the "
            "stabilized segment), or turn stabilize off for this episode."]}
```

The pre-stage block becomes:

```python
    src = m.segment
    stabilize_report = None
    if prepared_source is not None:
        # The caller has already produced these pixels and measured the route on
        # them (design §2.3). Re-running the pre-stage would spend two 4K passes to
        # recreate a file we were handed, and — because vidstabtransform is not
        # bit-reproducible across runs of a different length — could produce pixels
        # the frozen route no longer matches.
        src = prepared_source
    elif m.stabilize:
        src = str(Path(project_dir) / "stabilized.mp4")
        before, after = _timed("stabilize", lambda: vidstab.stabilize(
            m.segment, src, (src_w, src_h), _fps, _dur))
        stabilize_report = {"before": before, "after": after}
```

Immediately after the contradiction gate's `if findings:` block (before the
`# 3. reframe → check retry loop` comment):

```python
    if stop_after == "geometry":
        result = {"status": "geometry", "route": rp, "source": src,
                  "timings": timings, "degraded": degraded}
        if stabilize_report is not None:
            result["stabilize"] = stabilize_report
        return result
```

- [ ] **Step 3: run, then two mutation checks**

Both are steps:

1. Delete `and prepared_source is None` from the stabilize refusal.
   `test_prepared_source_unlocks_stabilize_with_a_frozen_route` MUST go RED.
2. Change `elif m.stabilize:` back to `if m.stabilize:` (so the pre-stage re-runs
   even when a prepared source was handed over). The same test MUST go RED via
   its `pytest.fail` monkeypatch.

Re-apply both inverses, `git diff` clean.

- [ ] **Step 4: commit**

```bash
.venv/bin/python -m pytest tests/lib/test_process_episode.py -q
git add -A && git commit -m "feat: process_episode stops at geometry, and accepts a prepared source"
```

---

## Task 3: the driver's third seam

**Files:**
- Modify: `scripts/edl_to_reel.py`
- Test: `tests/lib/test_edl_to_reel.py`

- [ ] **Step 1: failing tests**

```python
def test_build_geometry_writes_routes_and_no_clips(tmp_path, monkeypatch):
    """Phase 1a: GEOMETRY.json exists, out_dir holds no ep{i}.mp4."""
    ...
    g = ReelGeometry.from_json(str(out / "GEOMETRY.json"))
    assert len(g.episodes) == 2
    assert g.edl == str(edl_path)
    assert not list(Path(out).glob("ep*.mp4"))


def test_geometry_stores_the_manifest_without_its_colour_block(tmp_path, monkeypatch):
    g = _geometry_for(tmp_path, tone_src=[20.0, 100.0, 200.0])
    assert g.episodes[0].manifest["tone_src"] is None


def test_from_geometry_accepts_a_re_authored_grade(tmp_path, monkeypatch):
    """The seam's whole purpose: the EDL's colour block changed between the phases."""
    g = _geometry_for(tmp_path)
    _rewrite_edl_tone(edl_path, index=0, src=[20.0, 100.0, 200.0], dst=[30.0, 110.0, 210.0])
    rm, stop = edl_to_reel.render_from_geometry(str(geo_path), work, out)
    assert stop is None
    assert rm.episodes[0].manifest["tone_dst"] == [30.0, 110.0, 210.0]


def test_from_geometry_refuses_a_changed_cut(tmp_path, monkeypatch):
    g = _geometry_for(tmp_path)
    _rewrite_edl_window(edl_path, index=0, start=9.0)      # a different cut entirely
    with pytest.raises(ValueError, match="geometry was frozen"):
        edl_to_reel.render_from_geometry(str(geo_path), work, out)


def test_from_geometry_does_not_wipe_the_build_dir(tmp_path, monkeypatch):
    """The routes live there. Wiping between the phases destroys the input."""
    g = _geometry_for(tmp_path)
    marker = Path(work) / "ep0" / "route.json"
    before = marker.read_bytes()
    edl_to_reel.render_from_geometry(str(geo_path), work, out)
    assert marker.read_bytes() == before
```

- [ ] **Step 2: implement**

Refactor the existing pool loop into one helper both phases call:

```python
def _run_pool(mds: list[dict], work_dir: str, jobs: int, *,
              stop_after: str | None = None,
              prepared: list[tuple[str | None, str | None]] | None = None
              ) -> tuple[list[dict], dict | None]:
    """One process_episode per episode over a bounded pool, results in index order.

    `prepared[i]` is (route_path, prepared_source) for episode i — the frozen pair
    phase 1b hands back (design §2.3). The lowest-index problem wins whatever kind
    it is, exactly as the sequential loop returned: draining exceptions first would
    let a raise at episode 2 beat a routable stop at episode 0.
    """
```

Move the two `ensure_model` warm-ups into it (they belong to whichever phase
actually tracks — under `prepared` they are a no-op and can be skipped).

```python
def build_geometry(edl_path: str, project_path: str, footage_root: str,
                   work_dir: str, out_dir: str, *, jobs: int = DEFAULT_JOBS
                   ) -> tuple[ReelGeometry | None, dict | None]:
    """Phase 1a: extract, stabilize, track, gate — then STOP, before any encode.

    Writes GEOMETRY.json into out_dir (the episodes bucket, NOT build/, which the
    next phase must not wipe). The colour block is stripped from every stored
    manifest: what phase 1b re-derives from the EDL and compares against is the
    CUT, so a changed grade passes and a changed cut is refused (design §2.2)."""
```

Body: everything `edl_to_reel` does through step 3's pool, with
`stop_after="geometry"`, then

```python
    geo = ReelGeometry(
        episodes=tuple(EpisodeGeometry(manifest=manifest_lib.strip_colour(md),
                                       route=res["route"], source=res["source"],
                                       project_dir=str(Path(work_dir) / f"ep{i}"))
                       for i, (md, res) in enumerate(zip(mds, results))),
        edl=str(edl_path),
        provenance={"engine_at_start": started})
    geo.write(Path(out_dir) / "GEOMETRY.json")
```

```python
def render_from_geometry(geometry_path: str, work_dir: str, out_dir: str, *,
                         jobs: int = DEFAULT_JOBS, **reel_kwargs
                         ) -> tuple[ReelManifest | None, dict | None]:
    """Phase 1b: render every episode over its frozen route, with the EDL's CURRENT
    colour block. Does NOT wipe build/ — the routes it needs live there."""
    geo = ReelGeometry.from_json(geometry_path)
    edl = EDL.from_json(geo.edl)
    cfg = ProjectConfig.from_json(project_path)
    _refuse_on_engine_drift(geo.provenance.get("engine_at_start") or {},
                            provenance.engine_stamp())
    mds, stop = preflight(edl, cfg, seg_dir, out_dir)
    if stop:
        return None, stop
    for i, (md, eg) in enumerate(zip(mds, geo.episodes, strict=True)):
        if manifest_lib.strip_colour(md) != eg.manifest:
            raise ValueError(
                f"episode {i}'s cut changed after its geometry was frozen: the "
                f"GEOMETRY.json in hand was built from a different window, layout "
                f"or hero, and its route no longer describes this episode. Re-run "
                f"edl_to_reel --stop-after-geometry, or restore the EDL. (Only the "
                f"colour block may change between the phases — that is the seam.)")
```

then the pool with `stop_after=None` and

```python
    prepared = [(eg.route,
                 eg.source if (md.get("stabilize") and eg.route is not None) else None)
                for md, eg in zip(mds, geo.episodes, strict=True)]
```

then the same `ReelEpisode`/`ReelManifest` assembly the current `edl_to_reel` does
after its pool.

`prepared_source` is passed **only** when the episode declares `stabilize`: for an
unstabilized episode the source is `md["segment"]`, which `process_episode` already
resolves, and passing it would add a second, redundant assertion path.

**And only when the episode HAS a route** — found by Task 2's review before Task 3
ran. A pan is stabilizable (`pan` and `stabilize` are independent `EDLEpisode`
fields and nothing refuses the pair) and a pan has `route=None`, so the naive
tuple hands `(None, "…/stabilized.mp4")` to `process_episode`'s
`prepared_source`-needs-`route_path` refusal and the whole `--from-geometry` run
returns `needs_input` on a manifest the validator accepts. A pan+stabilize episode
therefore re-runs its own pre-stage in phase 2 — wasteful but correct, since a
generated path is not measured against pixels at all. **Test it:** a pan+stabilize
episode must complete `--from-geometry`.

Wire `ReelManifest.tone_target=edl.tone_target` into BOTH assembly sites (here and
in the existing `edl_to_reel`).

- [ ] **Step 3: CLI**

```python
    ph.add_argument("--stop-after-geometry", action="store_true",
                    help="stabilize, track and gate every episode, write GEOMETRY.json "
                         "and stop — the seam match_grade measures the crop in, before "
                         "any encode (design 2026-08-30 §2)")
    ph.add_argument("--from-geometry", default=None, metavar="GEOMETRY.json",
                    help="render every episode over the routes that file froze, with the "
                         "EDL's CURRENT colour block. Refuses a changed cut.")
```

Refuse `--stop-after-geometry` together with `--from-geometry` or
`--from-episodes`, in the style of the existing mutual-exclusion messages.

- [ ] **Step 4: mutation check**

Delete the `strip_colour(md) != eg.manifest` guard.
`test_from_geometry_refuses_a_changed_cut` MUST go RED, and
`test_from_geometry_accepts_a_re_authored_grade` MUST stay green — if the second
also goes red, the guard is comparing the colour block too and the strip is not
being applied on both sides. Re-apply, `git diff` clean.

- [ ] **Step 5: commit**

```bash
.venv/bin/python -m pytest tests/lib/test_edl_to_reel.py -q
git add -A && git commit -m "feat: edl_to_reel splits phase 1 at the geometry boundary"
```

---

## Task 4: the conductor measures the crop

**Files:**
- Modify: `scripts/match_grade.py`
- Test: `tests/lib/test_match_grade.py`, `tests/integration/test_matchgrade.py`

- [ ] **Step 1: failing tests**

```python
def test_conduct_measures_every_episode_crop(tmp_path, monkeypatch):
    """One measure_crop call per episode, with that episode's own route."""
    seen = []
    monkeypatch.setattr(match_grade, "measure_crop",
                        lambda md, src, route, **k: seen.append((src, route)) or (20.0, 100.0, 200.0))
    ...
    assert seen == [("s0.mp4", "r0.json"), ("s1.mp4", "r1.json")]


def test_write_match_stamps_the_tone_target_on_the_edl(tmp_path, monkeypatch):
    ...
    assert EDL.from_json(str(edl_path)).tone_target == (20.0, 100.0, 200.0)


def test_conduct_no_longer_reads_the_footage_root(tmp_path):
    with pytest.raises(TypeError):
        match_grade.write_match("EDL.json", footage_root="/anywhere")
```

- [ ] **Step 2: implement**

`conduct(geo: ReelGeometry, edl: EDL, ...)`:

```python
    profiles = [measure_crop(eg.manifest, eg.source, eg.route)
                for eg in geo.episodes]
```

Docstring's first paragraph becomes:

```
    """Measure each episode's own tracked CROP (design 2026-08-30 §1) — the pixels
    that ship, read through the same RenderPlan the render will use, with the
    colour block at identity — compute the common target, and return (enriched
    EDL, target, decisions, bias scale).

    Measured against the whole source frame this stage read until 2026-08-30:
    seven of eight real episodes differ by more than MATCH_EPS, median 14, max 36
    — so the pairs authored from the frame moved five episodes' midpoints by ~10
    units each while their p5 and p95 anchors, pinned by sky and specular water,
    were identical on both sides of every pair.
```

`write_match(geometry_path, *, eps, force, spec)` reads the geometry, takes
`geo.edl` as the EDL path, and adds `tone_target=target` to the returned EDL via
`replace`. `MATCH.md`'s header gains the sample count:

```python
    head = (f"# Match-grade — target {_triple(target)} (p5/p50/p95), eps {eps:g}\n\n"
            f"Measured on each episode's own tracked crop, "
            f"{color_measure.FRAMES} frames per episode "
            f"(design 2026-08-30 §1) — not the whole source frame.")
```

CLI: delete `--edl` and `--footage-root`, add
`b.add_argument("--geometry", required=True, help="GEOMETRY.json from edl_to_reel --stop-after-geometry; it names the EDL this writes back")`.

- [ ] **Step 3: run + commit**

```bash
.venv/bin/python -m pytest tests/lib/test_match_grade.py tests/integration/test_matchgrade.py -q
git add -A && git commit -m "feat: the conductor measures the crop that ships"
```

---

## Task 5: probe, before the encode

**Files:**
- Modify: `scripts/probe.py`
- Test: `tests/lib/test_probe.py`

- [ ] **Step 1: failing tests**

```python
def test_probe_grade_from_geometry_needs_no_episodes_json(tmp_path, monkeypatch):
    r = probe.probe_grade_geometry(str(geo_path), 0, out_dir=str(tmp_path / "p"))
    assert r["frames"] == 3 and "drift" not in r


def test_probe_reports_the_gray_ruler(tmp_path, monkeypatch):
    """probe.json's tone must be the number the conductor authored and the gate
    reads — measured, the RGB/BT.601 ruler differs by up to 6 codes (design §0.5)."""
    calls = []
    monkeypatch.setattr(probe.color_measure, "crop_percentiles",
                        lambda *a, **k: calls.append(a) or (1.0, 2.0, 3.0))
    r = probe.probe_grade(...)
    assert r["tone"] == [1.0, 2.0, 3.0] and calls


def test_probe_tone_is_gone():
    assert not hasattr(probe, "_tone")
```

- [ ] **Step 2: implement**

- Delete `_tone`; `report["tone"]` becomes one `color_measure.crop_percentiles(plan, src, times)`
  call (a single pooled reading for the episode, not one per frame — say so in the
  report key's name if it changes shape; keep the per-frame RGB numbers OUT).
  The `sheet.Cell` labels lose their per-frame tone line and gain `t=…s` only.
- Add `probe_grade_geometry(geometry_path, index, *, out_dir=None, frames=FRAMES)`:
  reads `ReelGeometry`, takes `eg.manifest` + the EDL's current colour block
  through the existing `regrade` (whose `md["segment"]`/`md["out_path"]` arguments
  come from `eg.manifest`), plans, renders, measures. **No `_refuse_on_drift`** —
  and the report says so:

```python
        "drift_checked": False,     # there is no path.json yet: the plan IS the
                                    # source of truth before the encode. The
                                    # --episodes mode keeps the oracle.
```
- CLI: `grade` gains `--geometry` as an alternative to `--episodes`; exactly one
  is required.

- [ ] **Step 3: commit**

```bash
.venv/bin/python -m pytest tests/lib/test_probe.py -q
git add -A && git commit -m "feat: probe grade before any encode, on the grade's own ruler"
```

---

## Task 6: the convergence gate

**Files:**
- Modify: `scripts/check_reel.py`, `scripts/build_reel.py`
- Test: `tests/lib/test_check_reel.py`

- [ ] **Step 1: failing tests**

```python
def test_tone_match_passes_when_every_episode_lands_on_the_target(...)
def test_tone_match_fails_and_routes_to_match_grade(...):
    f = [x for x in rep.fails if x.check == "tone_match"][0]
    assert f.escalate_to == "match-grade"
def test_tone_match_is_not_checked_without_a_target(...):
    assert rep.checks["tone_match"].detail["reason"] == "no-target"
def test_tone_match_skips_an_episode_the_conductor_skipped(...):
    assert rep.checks["tone_match"].detail["not_checked"] == {"1": "not-bound"}
def test_tone_match_is_blocking(...):
    assert "tone_match" not in models._ADVISORY_CHECKS
```

- [ ] **Step 2: implement**

`check_reel.run` gains `tone_target: tuple[float, float, float] | None = None` and,
after the variety check:

```python
    # tone_match — did the declared grade reach the pixels (design 2026-08-30 §5)?
    #
    # Read off the MASTER, not the delivered reel: the look's vignette and the
    # bookend fade ride deliver's one encode and both move percentiles, so the
    # master is the last artifact whose pixels are the episodes'. mids/_boundaries
    # already give every episode's span, so this is one select over one file.
    #
    # Only episodes BOUND to the reel's common target are judged. An episode the
    # conductor skipped (flat-source, hand-authored, within-eps) carries a
    # different tone_dst or none at all and is named, not silently passed.
    starts = [0.0] + cuts
    checked, not_checked, worst, worst_i = {}, {}, 0.0, None
    for i, (st, dur, ep) in enumerate(zip(starts, durations, episodes)):
        dst = _tone_dst_of(i)                      # from the per-episode manifest
        if tone_target is None:
            not_checked = {"reason": "no-target"}
            break
        if dst is None or not _same_target(dst, tone_target):
            not_checked[str(i)] = "not-bound"
            continue
        got = color_measure.clip_percentiles(
            master, [st + t for t in color_measure.sample_times(dur)])
        d = max(abs(a - b) for a, b in zip(got, tone_target))
        checked[str(i)] = round(d, 1)
        if d > worst:
            worst, worst_i = d, i
    ok = worst <= spec.tone_match_max
    checks["tone_match"] = CheckResult(ok=ok if checked else None, value=worst,
                                       detail={"target": list(tone_target or ()),
                                               "residuals": checked,
                                               "not_checked": not_checked,
                                               "max": spec.tone_match_max})
    if checked and not ok:
        fails.append(ReelFailure("tone_match", "match-grade", worst_i,
                                 {"residual": worst, "max": spec.tone_match_max}))
```

Adjust to the file's own idioms for `CheckResult`/`ReelFailure` — the shape above
is the contract, not the spelling. `_tone_dst_of` reads
`ReelManifest.episodes[i].manifest.get("tone_dst")`, so `run` needs the manifests:
pass the `ReelManifest` in, or a parallel `tone_dsts: list` — choose whichever
matches how `geometry=` is already threaded, and say which in the report.

`build_reel` passes `manifest.tone_target` through to `check_reel.run`.

**No `_REPROCESS_CLASS` change.** It is `("black",)`, so `tone_match` escalates by
construction — add a test asserting that, because it is a property of another
module that this check depends on.

- [ ] **Step 3: mutation check**

Raise `tone_match_max` to `100.0` in `models.py`;
`test_tone_match_fails_and_routes_to_match_grade` MUST go RED. Re-apply.

- [ ] **Step 4: commit**

---

## Task 7: the router and the skills

**Files:**
- Modify: `scripts/montage.py`
- Modify: `skills/match-grade/SKILL.md`, `skills/using-montage/SKILL.md`
- Test: `tests/lib/test_montage.py`

- [ ] **Step 1: the stage row**

Insert **after** `pacing` and **before** `match-grade`:

```python
    Stage("episodes-geometry", "GEOMETRY.json", "required",
          "edl_to_reel --stop-after-geometry (stabilize, track and gate every "
          "episode; no encode) — the seam match-grade measures the shipped crop in",
          None, "episodes"),
```

and flip `match-grade` to `required`, replacing its runner text:

```python
    Stage("match-grade", "MATCH.md", "required",
          "match-grade SKILL -> match_grade build --geometry (measures each episode's "
          "own crop; run AFTER episodes-geometry, before the render)", None, "reel"),
```

Test that `V1_STAGES` order is `... pacing, episodes-geometry, match-grade, ...`
and that `next_action` names `episodes-geometry` on a run with an EDL and no
GEOMETRY.json.

- [ ] **Step 2: the skills**

`skills/match-grade/SKILL.md`: the command becomes
`bin/vg -m scripts.match_grade build --geometry <run>/reels/<name>/episodes/GEOMETRY.json`,
the front-matter description says the reading is of the crop, and the "when to
run" line moves to *after* `episodes-geometry`. Delete every `--footage-root`
mention.

`skills/using-montage/SKILL.md`: the stage list gains `episodes-geometry`, and
`match-grade` moves out of the bracketed optional group. Add the convergence loop:

> Before the render, look: `probe grade --geometry … --index N` renders three
> crop-accurate frames of one episode with the grade the EDL currently declares.
> Edit `selection.json`, re-run `edit_plan build`, re-run `match_grade build`,
> probe again. Nothing is encoded until you stop.

- [ ] **Step 3: commit**

---

## Task 8: the proofs

**Files:**
- Create: `tests/integration/test_grade_shipped_pixels.py`

Real ffmpeg throughout, `@pytest.mark.integration`. Each proof carries a control
that must NOT move.

- [ ] **Proof 1 — the central claim, end to end.** A two-episode fixture whose
  segments differ in exposure by ~40 luma: geometry → `write_match` → render →
  every delivered clip within `MATCH_EPS` of `EDL.tone_target`.
  **Control:** a one-episode reel authors nothing (`plan` returns `within-eps`
  against its own profile, which IS the median) and its clip is byte-identical to
  the ungraded render.
- [ ] **Proof 2 — frame and crop disagree.** The `_banded_episode` fixture from
  Task 0, asserted through `conduct` rather than through `measure_crop`, so the
  disagreement is proven at the stage that acts on it.
- [ ] **Proof 3 — the cut guard.** `render_from_geometry` accepts a rewritten
  colour block and refuses a rewritten window, on the same GEOMETRY.json.
- [ ] **Proof 4 — stabilize.** An episode with `stabilize: true` renders through
  `--from-geometry`; the same route passed by hand to `process_episode` refuses.
  Needs `vidstab` — use the shared `need_filter` fixture.
- [ ] **Proof 5 — the gate fires.** Render the two-episode reel with episode 1's
  `tone_src`/`tone_dst` dropped from its manifest; `check_reel` reports
  `tone_match` failing and routed to `match-grade`. **Control:** the same reel
  with the pair present passes.
- [ ] **Proof 6 — the gate reads the master.** Deliver the passing reel with
  `LookSpec(vignette=0.6)`; `check_reel`'s `tone_match` still passes, and a
  direct `clip_percentiles` of the DELIVERED file is measurably further from the
  target than the master's — the number that shows the choice of file matters.
- [ ] **Proof 7 — probe agrees with the encode.** `probe_grade_geometry` on
  episode 0, then the real render, then `clip_percentiles` of the clip: the two
  agree within 1.5 codes on every anchor (§0.8 measured 1.0; the margin is for
  the fixture's own quantization).
- [ ] **Proof 8 — the whole suite.**

```bash
.venv/bin/python -m pytest -q
```

Record the count in the report. Note any golden that moved and why; **no golden
should move** — nothing in this slice changes an existing render's pixels.

---

## Task 9: the mutation battery, the bump, the docs

- [ ] **Step 1: the battery.** One row per load-bearing decision. Run each under
  `PYTHONDONTWRITEBYTECODE=1`, record RED/GREEN, and treat a GREEN row as a
  coverage hole to close with a new test before moving on.

| # | Mutation | Must go RED |
|---|---|---|
| 1 | `measure_crop` reads `measure_profile(src)` instead of the plan | Task 0 crop-vs-frame |
| 2 | `strip_colour` returns `md` unchanged | Task 3 cut guard (and Task 0's measure) |
| 3 | `_percentiles_from_gray`'s exact size check becomes `len(raw) % want` | the short-buffer test at dims divisible by `want` |
| 4 | `crop_percentiles` uses `plan.filter_args` + a leading `select` instead of `with_tail` | Proof 7 (one frame three times) |
| 5 | the stabilize refusal loses `and prepared_source is None` | Task 2 |
| 6 | `elif m.stabilize` → `if m.stabilize` | Task 2 |
| 7 | `stop_after` returns after the encode instead of before | Task 2's prepared-source test — it RAISES (check_episode.run is real and the faked reframe wrote no clip) before `calls == []` is reached |
| 7b | `src = prepared_source` becomes `src = m.segment` | Task 2's pinned `src`/`source` assertions |
| 8 | `render_from_geometry` calls `_wipe_scratch` | Task 3 no-wipe |
| 9 | the cut guard compares the FULL manifest | Task 3 re-authored-grade (green→red) |
| 10 | `conduct` measures `eg.source` with `route=None` | Proof 2 |
| 11 | `write_match` stops writing `tone_target` | Task 4 + Task 6 no-target |
| 12 | `tone_match_max` → 100.0 | Task 6 |
| 13 | `tone_match` added to `_ADVISORY_CHECKS` | Task 6 blocking |
| 14 | `tone_match` reads the delivered reel, not the master | Proof 6 |
| 15 | `tone_match` judges every episode, bound or not | Task 6 not-bound |
| 16 | `sample_times` returns `[0, dur/2, dur]` | Task 0 ends test |
| 17 | `match-grade` Stage back to `optional` | Task 7 |
| 18 | `episodes-geometry` moved after `match-grade` | Task 7 order |

- [ ] **Step 2: version 0.6.0.** `.claude-plugin/plugin.json` and a `CHANGELOG.md`
  entry naming the breaking change (`match_grade build --edl/--footage-root` is
  gone) and the measured before/after (44/64/120 → 11/6/2).
  `tests/test_plugin_manifests.py` enforces the pair.

- [ ] **Step 3: docs.**
  - `CLAUDE.md`: two registry rows (design + plan).
  - `docs/build-status.md`: a Done entry with the numbers.
  - `docs/pipeline-map.md`: the new stage.
  - `docs/backlog.md`: close "Grade the pixels that ship", R2.1 and R3.1; add
    §10's four rows.
  - Sweep for prose, not identifiers: `grep -rniE 'whole source frame|window midpoint|footage-root|footage_root' docs/ skills/ scripts/` and fix
    every hit that still describes the old measurement in the present tense.
    (The last slice's final review found nine such lines because the sweep matched
    symbols and the prose uses English.)

- [ ] **Step 4: commit + full suite.**

---

## Self-Review

**Spec coverage.** §1 → Task 0. §2 → Tasks 2, 3. §2.2 guard → Task 3 + battery 2,
9. §2.3 → Task 2 + battery 5, 6 + Proof 4. §3 → Task 4. §4 → Task 5. §5 → Task 6
+ Proofs 5, 6. §6 contracts → Task 1. §7 → Task 0's placement. §8's eight proofs →
Task 8 one-for-one. §9 is prose, carried into the docs in Task 9. §10 → Task 9's
backlog rows.

**Placeholders.** Task 3's test bodies use `...` where the fixture plumbing is
ordinary and the existing file's helpers already show it; every assertion that
discriminates is written out. Task 6's `_tone_dst_of` threading is left to the
implementer with an explicit instruction to match the file's existing `geometry=`
idiom and to report which it chose — that is a judgement about an existing
convention, not a gap.

**Type consistency.** `EpisodeGeometry.route` is `str | None` (pan), matching
`ReelEpisode.route`. `tone_target` is `tuple[float, float, float] | None`
everywhere: `EDL`, `ReelManifest`, `check_reel.run`. `sample_times`/`FRAMES` live
in `color_measure`; `probe.FRAMES` is deleted and imported from there — **check
this in Task 5**, since probe defines its own today.

**Two risks worth naming up front.**

1. **Task 3 is the big one.** It refactors the pool loop that `edl_to_reel` and
   `process_episodes` share, and that loop carries a load-bearing ordering
   guarantee (the lowest-index problem wins, whatever kind it is). The existing
   tests for that ordering must stay green without being touched; if they need
   editing, the refactor changed behaviour.
2. **`check_spec` deliberately does not carry `tone_target`.** A threshold is
   config; the target is data about this reel. Task 1 says so and Task 6 threads
   the target separately. An implementer who "tidies" it onto `ReelCheckSpec` will
   make `ReelManifest.check_spec` lossy and the gate will silently stop checking.
