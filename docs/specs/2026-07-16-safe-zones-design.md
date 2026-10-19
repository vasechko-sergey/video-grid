# Safe-zones — the §5.13 subject-placement check (design)

**Related:** montage §5.13 `reel-final-check` (the mechanical gate this completes);
§5.16 `titles` (the first margin consumer — its `_Y_EXPR` presets fold into the same
table); §6.1a hero marks + the `path.meta.json` sidecar (the projection this reuses).

**Intent:** close §5.13's last unbuilt check. `check_reel.safe_zones` reports
`passed=None` (`"not-implemented"`) today. This makes it a real, deterministic,
**advisory** check: each episode's tracked subject is projected into canvas
fractions (reusing `storyboard.marks_at_times`) and tested against a
platform-keyed safe-margin table. A subject that lands under the platform's UI
chrome (bottom caption bar, right action rail) is flagged — reported, never
blocking. Closes **§5.13's mechanical gate** — the stage itself stays ◐ until its
editorial half lands, since the spec's gate is "both parts green"; the pipeline
tally stays **14 ✅ · 1 ◐ · 1 ❌** (5.13 ◐ plus 5.4 trend-scan ❌, YAGNI).

## Scope decisions (locked in brainstorming)

- **Route-geometry, not pixel-CV.** The subject position comes from the frozen
  per-episode route + crop-mapping (`route.json` + `path.json` + `path.meta.json`),
  projected through the exact composite placement already implemented in
  `storyboard.marks_at_times`. No face/person detector runs at check time.
  Deterministic, unit-testable by pure geometry, and it reuses data the reel
  already carries.
- **Advisory, never a gate.** `safe_zones` joins `_ADVISORY_CHECKS` (with `beat`):
  measured and reported, but excluded from `ReelReport.overall`, and it emits **no**
  `ReelFailure`. Rationale: there is no auto-fix actuator — a reprocess reuses the
  **frozen** route, so it cannot move the subject; a hard gate would only stall to
  the cap and escalate. Subject-in-safe-zone is also editorial-leaning, so a
  false positive must not refuse an otherwise-good reel. `reel_orchestration` /
  `next_action` are untouched (zero blast radius on loop-2).
- **Built-in `SAFE_ZONES` table + generic default.** A typed `SafeZone` config-spec
  keyed by platform label (`generic`/`tiktok`/`reels`/`shorts`), margins as canvas
  fractions. New platforms are new table entries, not new code (mirrors
  `ExportProfile`). `platform` flows from `Spec.platform` through `ReelManifest`;
  unset → `generic` (conservative). The check is **not** gated on platform.
- **Titles rewire to the same table.** `titles._Y_EXPR` derives its top/bottom
  margins from `safezones.default_zone()` instead of the hardcoded `0.08`/`0.12`,
  so there is one margin authority. (v1 uses the generic zone; platform-aware
  titles is a trivial later extension — titles render at deliver, which does not
  carry `platform` today.)

## §1 Architecture

Data already on disk per episode after loop-1 (`process_episode` writes them into
each `epdir`, deterministic products of `track`/`reframe`):

| Sidecar | Contract | Carries |
|---------|----------|---------|
| `route.json` | `list[RoutePoint]` | tracked subject bbox `(t,x,y,w,h)` in **source** px |
| `path.json` | `CropPath` | per-frame crop-window left-x in source px (the tracking) |
| `path.meta.json` | `PathMeta` | crop `w/h/y`, `src_dims`, `canvas`, `out_dims`, `rect_px`, `freedom` |

The projection subject→canvas is **already written and tested** as
`storyboard.marks_at_times(route, path, meta, times)`. This slice extracts it to
`lib/geometry.py` (a script must not import a sibling driver), reuses it in a new
`lib/safezones.py`, and threads the three sidecar paths into `check_reel`.

```
                 lib/geometry.marks_at_times (moved from storyboard.py)
                          ▲                        ▲
     scripts/storyboard.py                 lib/safezones.subject_marks
                                                   │
   ReelEpisode(route,path,meta) ──► check_reel.run(geometry=, platform=)
                                                   │
                              safezones.evaluate(marks_per_ep, zone) → CheckResult
                                                   │  (advisory: no ReelFailure)
                                          ReelReport.checks["safe_zones"]
```

**Files:**
- `scripts/lib/safezones.py` **(new)** — `SafeZone`, `SAFE_ZONES`, `safe_zone_for`,
  `subject_marks`, `evaluate`, `default_zone`.
- `scripts/lib/geometry.py` — gains `marks_at_times` + `_interp` (moved).
- `scripts/storyboard.py` — imports `marks_at_times` from `lib/geometry` (thin change).
- `scripts/lib/models.py` — `ReelEpisode` gains `path`/`meta`; `ReelManifest` gains
  `platform`; `_ADVISORY_CHECKS` gains `"safe_zones"`.
- `scripts/check_reel.py` — `run(..., geometry=None, platform="")`; safe_zones
  computed-or-not-checked; leaves `_NOT_IMPL`.
- `scripts/build_reel.py` — assembles the geometry list + passes `platform`.
- `scripts/edl_to_reel.py` — wires `path`/`meta` into each `ReelEpisode`.
- `scripts/lib/titles.py` — `_Y_EXPR` from `safezones.default_zone()`.

## §2 `SafeZone` + the table

```python
@dataclass(frozen=True)
class SafeZone:
    """Platform UI-chrome margins as canvas fractions. The SAFE region is the
    rectangle [left, 1-left'] ... i.e. keep the subject inside
    [left, 1-right] x [top, 1-bottom]. Values are conservative, tunable
    estimates of where each app draws its overlays — they shift across app
    versions, so they live in a table, not in a pixel spec."""
    top: float
    bottom: float
    left: float
    right: float

    def __post_init__(self) -> None:
        for name in ("top", "bottom", "left", "right"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0.0 <= v < 0.5:
                raise ValueError(f"SafeZone.{name} must be a fraction in [0.0, 0.5), got {v!r} "
                                 "— a margin at/over half the frame leaves no safe region")

    def contains(self, fx: float, fy: float) -> bool:
        """Is the point (canvas fractions) inside the safe region?"""
        return self.left <= fx <= 1.0 - self.right and self.top <= fy <= 1.0 - self.bottom
```

> **Amended 2026-10-19 (retro 2026-10-16 S4).** `reels` top is now **0.14**, not the
> 0.08 below: at 0.08 a top title sat under the Reels header on the second real run,
> and the published guidance keeps the top 14% clear (13% measured off ad
> previews). The bottom stays 0.16 — the sources disagree (23–35%).

```python
SAFE_ZONES: dict[str, SafeZone] = {
    "generic": SafeZone(top=0.08, bottom=0.12, left=0.05, right=0.05),   # == titles presets
    "tiktok":  SafeZone(top=0.08, bottom=0.18, left=0.04, right=0.12),   # tall caption + right rail
    "reels":   SafeZone(top=0.08, bottom=0.16, left=0.04, right=0.11),   # instagram
    "shorts":  SafeZone(top=0.10, bottom=0.14, left=0.04, right=0.11),   # youtube
}
_ALIASES = {"instagram": "reels", "ig": "reels", "reel": "reels",
            "youtube": "shorts", "yt": "shorts"}

def safe_zone_for(platform: str) -> SafeZone:
    """Resolve a free-text platform label to its zone; unknown/empty → generic."""
    key = (platform or "").strip().lower()
    key = _ALIASES.get(key, key)
    return SAFE_ZONES.get(key, SAFE_ZONES["generic"])

def default_zone() -> SafeZone:
    return SAFE_ZONES["generic"]
```

The `generic` top/bottom (`0.08`/`0.12`) equal titles' current `_Y_EXPR` presets by
construction, so the rewire in §7 is behaviour-preserving for titles.

## §3 Projection + decision

**Projection (moved verbatim to `lib/geometry.marks_at_times`, unchanged):**

```python
fx = (rx + rw * (x - cx) / meta.crop_w) / out_w      # rx,rw = rect_px x,w ; cx = crop-window left-x at t
fy = (ry + rh * (y - meta.crop_y) / meta.crop_h) / out_h
```

For a `fill` layout `rect_px` is the whole output, so this reduces to the plain
`(x - cropx)/crop_w`; for an `insert`/`split` card it correctly maps the subject
inside the card's canvas rect. `x`, `y`, `cx` are interpolated on `t` so a mark
lands on the right frame even on a gappy route.

**Per-episode marks (`safezones.subject_marks`):**

```python
_SAFE_SAMPLES = 5

def _sample_times(dur: float) -> list[float]:
    return [(k + 0.5) * dur / _SAFE_SAMPLES for k in range(_SAFE_SAMPLES)]

def subject_marks(route, path, meta, dur: float) -> list[tuple[float, float]]:
    return marks_at_times(route, path, meta, _sample_times(dur))
```

**Decision (pure — `safezones.evaluate`):** flag if the subject center at any
sampled time in any episode falls outside its safe region. The report names the
worst offender (episode index + mark + which edge), so a human sees where.

```python
def evaluate(marks_per_ep: list[list[tuple[float, float]]], zone: SafeZone) -> tuple[bool, dict]:
    worst = None                                    # (episode_idx, fx, fy)
    for i, marks in enumerate(marks_per_ep):
        for fx, fy in marks:
            if not zone.contains(fx, fy):
                # rank by how far outside — max over the four signed overshoots
                over = max(zone.left - fx, fx - (1 - zone.right),
                           zone.top - fy, fy - (1 - zone.bottom))
                if worst is None or over > worst[0]:
                    worst = (over, i, round(fx, 4), round(fy, 4))
    if worst is None:
        return True, {"episodes": len(marks_per_ep), "advisory": True}
    _, idx, fx, fy = worst
    return False, {"worst_episode": idx, "worst_mark": [fx, fy],
                   "zone": {"top": zone.top, "bottom": zone.bottom,
                            "left": zone.left, "right": zone.right}, "advisory": True}
```

## §4 `check_reel` wiring

```python
def run(master, episodes, spec, out_report, music=None, audio=None,
        geometry: list[tuple[str, str, str]] | None = None, platform: str = "") -> ReelReport:
```

`geometry` is a list of `(route_json, path_json, meta_json)` paths, parallel to
`episodes`. When present, `safe_zones` is computed; when absent (silent unit path,
legacy hand-authored manifests), it stays `passed=None`.

```python
if geometry is not None:
    zone = safezones.safe_zone_for(platform)
    marks_per_ep = [safezones.subject_marks(route_from_json(r), CropPath.from_json(p),
                                            PathMeta.from_json(m), dur)
                    for (r, p, m), dur in zip(geometry, durations)]
    passed, detail = safezones.evaluate(marks_per_ep, zone)
    checks["safe_zones"] = CheckResult("safe_zones", passed, detail)
```

`safe_zones` was the **only** `_NOT_IMPL` entry, so `_NOT_IMPL` and its fill-loop
are **removed**. Its fallback joins `_UNCHECKED`
(`"not-checked — no per-episode geometry supplied"`) so a geometry-less reel reports
`not-checked`, exactly like `beat`/`loudness` on a silent reel — never a silent
pass, never a fake "not-implemented" now that it is implemented.

Because `safe_zones ∈ _ADVISORY_CHECKS`, a `False` here never drops
`ReelReport.overall`, and no `ReelFailure` is appended.

## §5 Contract changes (`models.py`)

- **`ReelEpisode`** gains `path: str = ""` and `meta: str = ""` (the `path.json` /
  `path.meta.json` sidecar paths, peers of `route`). Default `""` = geometry
  absent for that episode → backward compatible; existing manifests and tests keep
  working, `safe_zones` simply stays `not-checked`. `from_dict` reads
  `e.get("path","")` / `e.get("meta","")`. Validation: if one of `path`/`meta` is
  set, both must be (a lone sidecar cannot project).
- **`ReelManifest`** gains `platform: str = ""` (free label; `from_dict` reads
  `d.get("platform","")`). No validation beyond `isinstance str`.
- **`_ADVISORY_CHECKS`** becomes `("beat", "safe_zones")`.

## §6 Drivers

**`edl_to_reel`** — wire the two new sidecar paths (siblings of `route.json` in each
`epdir`):

```python
episodes.append(ReelEpisode(manifest=md, clip=res["clip"],
                            route=str(Path(epdir) / "route.json"),
                            path=str(Path(epdir) / "path.json"),
                            meta=str(Path(epdir) / "path.meta.json")))
```

**`build_reel`** — build the geometry list from the (frozen) episode sidecars and
pass it plus `platform`:

```python
geometry = ([(e.route, e.path, e.meta) for e in rm.episodes]
            if all(e.path and e.meta for e in rm.episodes) else None)
report = check_reel.run(master, clips, rm.check_spec, report_path,
                        music=music, audio=audio, geometry=geometry, platform=rm.platform)
```

**Reprocess invariance (why the original sidecars stay valid every round):** the
only loop-2 actuators are colour and black, both of which reuse the **frozen**
route; the crop geometry is deterministic from that route, so `path.meta.json` is
geometrically identical across rounds. `build_reel` therefore keeps using the
original `e.path`/`e.meta` — the subject's canvas position (and hence `safe_zones`)
does not change between rounds. This is the same invariant that makes the check
advisory: a reprocess cannot fix it.

## §7 Titles rewire

`titles._Y_EXPR` currently hardcodes `"top": "h*0.08"`, `"bottom": "h-th-h*0.12"`.
Rebuild it from the generic zone so the margin lives in one place:

```python
from scripts.lib import safezones
_Z = safezones.default_zone()
_Y_EXPR = {"top": f"h*{_Z.top}", "center": "(h-th)/2", "bottom": f"h-th-h*{_Z.bottom}"}
```

`_Z.top == 0.08` and `_Z.bottom == 0.12` → the rendered expressions are unchanged.
A regression test pins `titles`' bottom margin to `SAFE_ZONES["generic"].bottom`.

## §8 Edge cases

- **Single-episode reel** — safe_zones still runs (it is per-episode, not per-cut,
  unlike beat/color/variety); one episode, one marks list.
- **Geometry partially present** — if any episode lacks `path`/`meta`, `build_reel`
  passes `geometry=None` and the whole check is `not-checked` (no half-answers).
- **`fill` (full-frame) episode** — `rect_px` = whole output; projection reduces to
  the plain crop mapping; a low `crop_y` framing is what makes fy fall into the
  bottom band.
- **Empty/short route** — `marks_at_times` already raises on a non-parallel or
  empty route/path; that surfaces as a loud error, not a silent pass.
- **Unknown platform label** — `safe_zone_for` falls back to `generic`, no error.

## §9 Landmine / interaction notes (§12)

- No new ffmpeg. `check_reel`'s existing `-ss`-after-`-i` still-frame sampling is
  untouched; safe_zones reads sidecar JSON, not pixels.
- The projection move to `lib/geometry` is byte-preserving (same code); storyboard's
  golden output must not change — the storyboard tests are the guard.
- `safe_zones` staying advisory is load-bearing: were it hard with
  `escalate_to="reprocess"`, the frozen-route invariant (§6) would loop it to the
  cap every time. Do not "promote" it to a gate without first building a
  re-frame actuator.

## §10 Testing (TDD)

- **`lib/safezones.py`** (pure): `SafeZone` validation (margin ≥ 0.5 or non-numeric
  raises); `contains` at corners; `safe_zone_for` known/alias/unknown-empty→generic;
  `evaluate` — all-inside → `(True, …)`, a mark in the bottom band → `(False, worst…)`,
  worst-of-many ranking, `advisory:True` in every detail.
- **`lib/geometry.py`**: the moved `marks_at_times`/`_interp` keep their behaviour
  (a projection unit test; storyboard's own tests still pass unchanged).
- **`check_reel`**: `safe_zones=None` (`not-checked`) when `geometry=None`; computed
  `pass`/`False` with tiny real sidecar JSONs written to `tmp_path`; a `False`
  safe_zones leaves `overall` `True` (advisory); `safe_zones` no longer in `_NOT_IMPL`.
- **`build_reel`**: geometry list + `platform` reach `check_reel.run` (widen the
  existing mock lambdas; assert the new kwargs); geometry omitted when a sidecar
  path is empty.
- **`titles`**: bottom margin expression derives from `SAFE_ZONES["generic"].bottom`
  (regression-pins the `0.12`, and that the rendered expr is unchanged).
- **integration (real-ffmpeg)**, mirroring `test_ambient`/`test_sfx`: assemble a
  real 2-episode master with hand-written sidecars where one episode frames the
  subject low → `report.safe_zones.pass is False`, `report.overall is True`, and
  `build_reel` still delivers (advisory does not block).

## §11 Non-goals (v1)

- **Pixel/CV subject detection** — route-geometry only.
- **"key action not clipped" (bbox extent), "pad bars clean", "transitions not
  jarring"** — the subject **center** vs the safe region is the v1 mechanic; bbox
  edges, filler-bar validation, and transition smoothness are editorial follow-ons.
- **Platform-aware titles** — titles use the generic zone; threading `platform`
  into deliver is deferred.
- **A hard gate / re-frame actuator** — advisory until a fixer exists.

## §12 Doc sync

`docs/pipeline-map.md` (5.13 ◐→✅, tally 15✅·0◐·1❌, roadmap Editorial-reel-final
line), `docs/build-status.md` (new DONE entry; safe_zones no longer
not-implemented; test count), master `docs/specs/2026-07-05-montage-skillset-design.md`
§5.13/§584 (safe-zones built), `docs/specs/2026-07-10-reel-back-half-design.md` +
`docs/specs/2026-07-11-music-spine-design.md` + `docs/specs/2026-07-13-titles-design.md`
(flip the safe_zones-deferred notes), `CLAUDE.md` (registry rows for this design +
its plan).
