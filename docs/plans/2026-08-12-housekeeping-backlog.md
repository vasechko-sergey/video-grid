# Housekeeping + backlog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Fix the four deferrals that fell out of every queue (three of them live
defects), correct three stale doc pointers, and stand up `docs/backlog.md` as the
single prioritized queue plus the rule that keeps it filled.

**Architecture:** Four independent contract fixes, each landing in its own commit,
then documentation. Nothing shares state; tasks 0–3 may be implemented in any
order but are dispatched one at a time (single working tree).

**Tech Stack:** Python 3.13, pytest, real ffmpeg via `lib/ffbin`.

**Design:** [docs/specs/2026-08-12-housekeeping-backlog-design.md](../specs/2026-08-12-housekeeping-backlog-design.md)

---

## Global Constraints

- **Fail loud.** No silent clamps, no defaults that paper over a bad value. A
  refusal message names the offending value AND the remedy.
- **Defaults keep every existing artifact byte-identical.** `EDL.platform=""`,
  `EDLEpisode.smooth_window_s=None`, `adjust_reframe_params(floor=None)` must all
  reproduce today's exact behaviour. Any test that pins an existing command
  string or golden must still pass untouched.
- **Scripts are modules** (`pythonpath = .`); run them as `python -m scripts.x`.
  Python is `.venv/bin/python`.
- **Wire keys equal field names.** `to_dict`/`from_dict` round-trip.
- **Type checks before value checks**, and `bool` is rejected before `int`
  (`isinstance(v, bool)` first) — `True == 1` otherwise slips through.
- **TDD**: write the failing test, run it, see it fail for the stated reason,
  then implement.
- **Do NOT run installers** (`brew`, `pip install`, `npm`, `setup.sh`). The
  environment is already provisioned; verification is read-only plus `pytest`.
- **Never** `git checkout --`, `git restore`, `git reset --hard`, or `git stash`.
  Uncommitted work has been destroyed that way before.
- Commit at the end of each task. Do not amend a prior commit.

---

## Task 0: `EDL.platform` — the pipe from brief to reel

**Files:**
- Modify: `scripts/lib/edl.py` (the `EDL` dataclass, `from_dict`, `to_dict`, `to_markdown`)
- Modify: `scripts/edit_plan.py` (`build_edl`, `write_edit_plan`)
- Modify: `scripts/edl_to_reel.py` (the `ReelManifest` construction, ~line 154)
- Test: `tests/lib/test_edl.py`, `tests/lib/test_edit_plan.py`, `tests/lib/test_edl_to_reel.py`

Context: `Spec.platform` is written by `reel_brief` and read by nobody that builds
a reel. `ReelManifest.platform` (`models.py:1300`) is therefore always `""`, so
`check_reel`'s safe-zone section and `titles.y_exprs` both take the generic table.

- [x] **Step 1: Write the failing tests**

```python
def test_edl_platform_round_trips_and_defaults_empty():
    e = _edl()                                   # the module's existing EDL helper
    assert e.platform == ""
    d = e.to_dict()
    assert d["platform"] == ""
    assert EDL.from_dict({**d, "platform": "tiktok"}).platform == "tiktok"


def test_edl_platform_must_be_a_string():
    with pytest.raises(ValueError, match="platform"):
        EDL.from_dict({**_edl().to_dict(), "platform": 9})
```

In `tests/lib/test_edit_plan.py` — `--spec` already exists and is read for the
mood preset; it must now also carry the platform:

```python
def test_write_edit_plan_carries_spec_platform_into_the_edl(tmp_path, ...):
    # build a SPEC.json whose platform is "tiktok" (reuse the module's spec fixture
    # helper; Spec requires mood + hook), then run write_edit_plan(..., spec=spec_path)
    edl = EDL.from_json(str(tmp_path / "EDL.json"))
    assert edl.platform == "tiktok"


def test_write_edit_plan_without_spec_leaves_platform_empty(tmp_path, ...):
    edl = EDL.from_json(str(tmp_path / "EDL.json"))
    assert edl.platform == ""
```

In `tests/lib/test_edl_to_reel.py` — assert the value reaches the manifest. Follow
whatever seam that module's existing tests use to capture the `ReelManifest`
(a monkeypatched `build_reel.build_reel` capturing its `rm` argument is the
cheapest); do not invent a new one.

```python
def test_edl_to_reel_passes_the_edl_platform_to_the_reel_manifest(...):
    # EDL.json authored with "platform": "tiktok"
    assert captured_rm.platform == "tiktok"
```

- [x] **Step 2: Run them and watch them fail**

```bash
.venv/bin/python -m pytest tests/lib/test_edl.py -k platform -v
```

Expected: `TypeError: __init__() got an unexpected keyword argument 'platform'`
or a `KeyError`, not an assertion mismatch.

- [x] **Step 3: Add the field**

In `scripts/lib/edl.py`, on the `EDL` dataclass beside `cap`/`target_dur`:

```python
    platform: str = ""             # UI safe-zone table key (§5.13) — "" = the generic
                                   # zone. Copied from Spec.platform by edit_plan and
                                   # spent by edl_to_reel on ReelManifest.platform, which
                                   # check_reel's safe-zone section and titles.y_exprs
                                   # both read. It lives on the EDL rather than on a CLI
                                   # flag because the EDL is the attested artifact: the
                                   # platform a reel was checked against is recorded with
                                   # the cut (design 2026-08-12 §1.1).
```

Validate in `__post_init__` alongside the other top-level checks:

```python
        if not isinstance(self.platform, str):
            raise ValueError(f"EDL.platform must be a string label (e.g. 'tiktok') or "
                             f"'' for the generic safe zone, got {self.platform!r}")
```

`from_dict` (~line 251) gains `platform=d.get("platform", "")`; `to_dict`
(~line 281) gains `"platform": self.platform`.

In `to_markdown`, print it only when set, in whichever header/summary block that
method already uses for reel-level facts (`cap`, `music`) — one line, e.g.
`- **Platform:** tiktok`. Do not add a line when it is `""`; an unset platform is
not a fact worth printing and an always-present line would move every existing
golden markdown.

- [x] **Step 4: Thread it through `edit_plan`**

`build_edl` already receives `preset` derived from the spec. Add a keyword-only
`platform: str = ""` parameter and pass it into the `EDL(...)` it returns
(~line 385). In `write_edit_plan` (~line 423), the spec is already loaded once
for the preset — reuse that same object rather than reading the file twice:

```python
    sp = Spec.from_json(spec) if spec else None
    preset = moodpreset.resolve(sp.mood if sp else None)
    ...
    edl = build_edl(..., aspect=tuple(cfg.canvas), preset=preset, rules=rules,
                    platform=sp.platform if sp else "")
```

- [x] **Step 5: Spend it in `edl_to_reel`**

At the `ReelManifest(...)` construction (~line 154) add `platform=edl.platform`.

- [x] **Step 6: Run the tests, then the touched suites**

```bash
.venv/bin/python -m pytest tests/lib/test_edl.py tests/lib/test_edit_plan.py tests/lib/test_edl_to_reel.py -q
```

Expected: PASS, and no previously-passing test changes behaviour.

- [x] **Step 7: Commit**

```bash
git add -A && git commit -m "fix(edl): carry the brief's platform to the reel

Spec.platform was written by reel_brief and read by nothing that builds a
reel, so ReelManifest.platform stayed \"\" and both consumers -- check_reel's
safe-zone section and titles.y_exprs -- silently took the generic table.
EDL.platform now carries it from edit_plan --spec to edl_to_reel."
```

---

## Task 1: `EDLEpisode.smooth_window_s` — authorable, and not walked back

**Files:**
- Modify: `scripts/lib/edl.py` (`EDLEpisode` field, validation, `to_dict`, `to_manifest_dict`)
- Modify: `scripts/lib/manifest.py` (`Manifest.smooth_window_s`)
- Modify: `scripts/lib/orchestration.py` (`adjust_reframe_params` gains `floor`)
- Modify: `scripts/process_episode.py` (seed the params, pass the floor)
- Test: `tests/lib/test_edl.py`, `tests/lib/test_manifest.py`, `tests/lib/test_orchestration.py`, `tests/lib/test_process_episode.py`

Context: `ReframeSpec.smooth_window_s` exists; the EDL row that sets it does not.
It is **not** a plain pass-through — `orchestration.adjust_reframe_params` widens
it on `jitter` and halves it on a lag, flooring the lag branch at
`DEFAULT_PARAMS["smooth_window_s"]` (0.25). An authored 0.6 would be walked to
0.25 by the first lag retry, discarding the instruction. See design §1.2.

- [x] **Step 1: Write the failing tests**

```python
# tests/lib/test_edl.py
def test_episode_smooth_window_s_defaults_none_and_round_trips():
    ep = _ep()
    assert ep.smooth_window_s is None
    assert ep.to_dict()["smooth_window_s"] is None
    assert EDLEpisode.from_dict({**ep.to_dict(), "smooth_window_s": 0.6}).smooth_window_s == 0.6


@pytest.mark.parametrize("bad", [0.0, -0.1, 2.5, True, "0.5"])
def test_episode_smooth_window_s_refuses_out_of_band(bad):
    with pytest.raises(ValueError, match="smooth_window_s"):
        EDLEpisode.from_dict({**_ep().to_dict(), "smooth_window_s": bad})


def test_to_manifest_dict_omits_smooth_window_s_when_unset():
    assert "smooth_window_s" not in to_manifest_dict(_ep(), "s.mp4", "o.mp4")


def test_to_manifest_dict_carries_an_authored_smooth_window_s():
    ep = EDLEpisode.from_dict({**_ep().to_dict(), "smooth_window_s": 0.6})
    assert to_manifest_dict(ep, "s.mp4", "o.mp4")["smooth_window_s"] == 0.6
```

```python
# tests/lib/test_orchestration.py
def test_lag_halves_the_window_but_never_below_the_authored_floor():
    p = adjust_reframe_params({"smooth_window_s": 0.6}, ["on_line"], floor=0.6)
    assert p["smooth_window_s"] == 0.6          # 0.3 would discard the author's ask


def test_floor_none_keeps_todays_default_floor():
    p = adjust_reframe_params({"smooth_window_s": 0.3}, ["on_line"])
    assert p["smooth_window_s"] == 0.25         # DEFAULT_PARAMS floor, unchanged
```

Use whatever bound `EDLEpisode`'s band should be: mirror `ReframeSpec`'s own
`0 < v <= 2.0` exactly, so a value the EDL accepts can never be one `ReframeSpec`
rejects.

- [x] **Step 2: Run them and watch them fail**

```bash
.venv/bin/python -m pytest tests/lib/test_edl.py -k smooth -v
```

Expected: unexpected-keyword / KeyError, not an assertion mismatch.

- [x] **Step 3: The EDL field**

```python
    smooth_window_s: float | None = None   # savgol span in SECONDS over the tracked hero
                                           # path; raise above the 0.25 default to tame
                                           # jitter on a small/fast subject. None = the
                                           # ReframeSpec default. This is the retry
                                           # ladder's STARTING value and its lag-branch
                                           # floor, not a fixed setting — see
                                           # orchestration.adjust_reframe_params.
```

Validation in `__post_init__` (bool first):

```python
        if self.smooth_window_s is not None and (
                isinstance(self.smooth_window_s, bool)
                or not isinstance(self.smooth_window_s, (int, float))
                or not 0 < self.smooth_window_s <= 2.0):
            raise ValueError(
                f"EDLEpisode.smooth_window_s must be a span in seconds in (0, 2.0] or "
                f"null, got {self.smooth_window_s!r} — it is a filter cutoff, and a "
                "window longer than a couple of seconds stops following the subject")
```

`to_dict` gains `"smooth_window_s": self.smooth_window_s`.

In `to_manifest_dict`, add it to the **conditional** group beside `motion`/`pan`
(the `is not None` predicate), so an unset value leaves the key out and
`Manifest.from_dict` falls to its own default:

```python
    if ep.smooth_window_s is not None:
        md["smooth_window_s"] = ep.smooth_window_s
```

- [x] **Step 4: The manifest field**

`Manifest.smooth_window_s: float | None = None`, validated with the identical
band and message shape. Place it beside the other reframe-tuning fields.

- [x] **Step 5: The ladder gains a floor**

```python
def adjust_reframe_params(params: dict[str, float], fail_reasons: list[str],
                          floor: float | None = None) -> dict[str, float]:
```

Extend the existing docstring with one paragraph: `floor` is the authored
`smooth_window_s`, and `None` means the module default — an episode that never
asked for a window keeps today's exact ladder. In the lag branch:

```python
        lo = DEFAULT_PARAMS["smooth_window_s"] if floor is None else floor
        p["smooth_window_s"] = max(lo, p["smooth_window_s"] / 2)
```

The `jitter` branch is unchanged: widening past an authored value is the ladder
doing its job, and `SMOOTH_WINDOW_S_MAX` still caps it.

- [x] **Step 6: `process_episode` seeds and floors**

Where the starting `params` dict is built, override the seed when the manifest
authored one, and pass the same value as `floor` at every
`adjust_reframe_params` call site in that module. Read the surrounding code
first — do not guess the variable names.

- [x] **Step 7: Run the tests**

```bash
.venv/bin/python -m pytest tests/lib/test_edl.py tests/lib/test_manifest.py tests/lib/test_orchestration.py tests/lib/test_process_episode.py -q
```

- [x] **Step 8: Commit**

```bash
git add -A && git commit -m "feat(edl): authorable smooth_window_s, floored against the retry ladder

ReframeSpec has had the field since colour-as-a-stage; the EDL row that sets
it was deferred twice and never built. It is a ladder knob, so an authored
value also becomes the lag branch's floor -- otherwise the first lag retry
silently walked a deliberate 0.6 back to the 0.25 default."
```

---

## Task 2: `draft.py` renders a real frame, not 8×16 pixels

**Files:**
- Modify: `scripts/draft.py` (~line 38, `dims = cfg.canvas`)
- Test: `tests/integration/test_draft.py` (or wherever `build_draft`'s real-ffmpeg test lives — find it first)

Context: `ProjectConfig.canvas` is an **aspect** (`PURPOSE_CANVAS` maps `reel →
(9, 16)`), and `segment_filter` spends it as pixels: `scale=9:16,pad=9:16`.
Measured on real bytes, the draft comes out **8×16** (`force_divisible_by=2`
rounds 9 down). The existing unit test hand-passes `(1080, 1920)`, so it exercises
the string builder with a value the caller never supplies.

- [x] **Step 1: Write the failing test**

The proof must reach pixels — a test that asserts on a hand-supplied argument
cannot fail on a caller that supplies the wrong one. Extend the existing
real-ffmpeg draft test (do not create a parallel one) so that after
`build_draft(...)` it probes the output:

```python
    w, h = assembly.probe_stream(result["draft"]).dims   # or the module's existing probe
    assert (w, h) == (1080, 1920), f"draft rendered {w}x{h}"
```

Use the fixture project whose purpose gives a 9:16 canvas and a delivery that
resolves to 1080×1920; if the existing fixture's delivery is `native`, assert
against what `Delivery` resolves for it rather than hardcoding — but assert
**real numbers from the file**, and make sure the expectation is at least
`>= 100` on both axes so the postage-stamp failure can never pass.

- [x] **Step 2: Run it and watch it fail**

Expected: `draft rendered 8x16`.

- [x] **Step 3: Resolve delivery pixels**

Replace `dims = cfg.canvas` with the same resolution the rest of the engine uses
— `Delivery.from_spec(cfg.delivery).dims(...)` against the canvas aspect. Read
`lib/layout.py:62` and `Delivery.dims` first and follow that call exactly; the
canvas aspect goes in, delivered pixels come out. Add a short comment naming the
trap:

```python
    # cfg.canvas is an ASPECT (PURPOSE_CANVAS maps reel -> (9, 16)), never pixels.
    # Spending it directly rendered an 8x16 draft (design 2026-08-12 §1.3).
```

If `Delivery.dims` cannot produce pixels from an aspect alone for a `native`
delivery, derive them from the first segment's probed dimensions the way the
engine does, and say so in the comment. Report what you found either way.

- [x] **Step 4: Run the test, then the draft suites**

```bash
.venv/bin/python -m pytest tests/lib/test_draft.py tests/integration/test_draft.py -q
```

- [x] **Step 5: Commit**

```bash
git add -A && git commit -m "fix(draft): render delivery pixels, not the canvas aspect

cfg.canvas is an aspect tuple; draft spent it as pixels and produced an 8x16
postage stamp. The unit test hand-passed (1080, 1920), so it never saw the
value the caller actually supplies -- the new proof probes the real output."
```

---

## Task 3: `Spec.reel_count > 1` refuses instead of lying

**Files:**
- Modify: `scripts/lib/spec.py` (~line 44)
- Test: `tests/lib/test_spec.py`

Context: `reel_count` is validated as `>= 1`, rendered into `SPEC.md` ("3 reels"),
and consumed by nothing. reel-brief §7 and reel-review §7 both park multi-reel as
future work. A brief asking for three reels silently produces one.

- [x] **Step 1: Write the failing test**

```python
def test_reel_count_above_one_is_refused_with_the_remedy():
    with pytest.raises(ValueError, match="one reel at a time"):
        Spec(idea="i", mood="fun", hook="h", reel_count=3)


def test_reel_count_one_is_the_supported_value():
    assert Spec(idea="i", mood="fun", hook="h", reel_count=1).reel_count == 1
```

Match the module's own construction style for a valid `Spec` — read a neighbouring
test rather than assuming the required fields.

- [x] **Step 2: Run it and watch it fail** (no exception raised).

- [x] **Step 3: Extend the refusal**

```python
        if isinstance(self.reel_count, bool) or not isinstance(self.reel_count, int) or self.reel_count < 1:
            raise ValueError(f"Spec.reel_count must be an int >= 1, got {self.reel_count!r}")
        if self.reel_count > 1:
            raise ValueError(
                f"Spec.reel_count {self.reel_count} — multi-reel fan-out is not built, and "
                "accepting it here produced ONE reel with no word said. Run the conveyor "
                "one reel at a time (a project directory per reel). The field stays in the "
                "contract for the day fan-out lands (design 2026-08-12 §1.4)")
```

- [x] **Step 4: Grep for callers that would now break**

```bash
grep -rn "reel_count" scripts/ tests/ skills/
```

`reel_brief`'s CLI passes it through; a `--reel-count 3` invocation must now fail
loud rather than mislead. If any test constructs a `Spec` with `reel_count > 1`,
update it to assert the refusal. Report anything you changed.

- [x] **Step 5: Run the suites and commit**

```bash
.venv/bin/python -m pytest tests/lib/test_spec.py tests/lib/test_reel_brief.py -q
```

```bash
git add -A && git commit -m "fix(spec): refuse reel_count > 1 instead of silently making one reel

The field was validated, printed into SPEC.md and consumed by nothing. It
stays in the contract -- two designs park multi-reel as intended work -- but
asking for three reels now stops with the remedy instead of shipping one."
```

---

## Task 4: three stale pointers

**Files:**
- Modify: `docs/specs/2026-07-10-reel-back-half-design.md` (§9)
- Modify: `docs/specs/2026-07-12-footage-intake-design.md` (§8)
- Modify: `docs/build-status.md` (the §6.1a layer 3 entries — there are three, at
  roughly lines 2159, 2855 and 3139; fix all of them)

Documentation only. No code, no tests.

- [x] **Step 1: reel-back-half §9 — the phase that never existed**

"**Secondary-aspect re-reframe on deliver** — Phase F." There is no Phase F; the
only "slice F" in this repo is colour-as-a-stage, which is unrelated. Rewrite to
say the item is deferred with **no phase assigned**, and point at
`docs/backlog.md` (Task 5 creates it) as where it is now queued.

- [x] **Step 2: footage-intake §8 — the blocker that is gone**

"**Sharpness/blur metric** — deferred (would add cv2)". `scripts/lib/flow.py`
imports cv2 today (tracking-ladder, 2026-07-21). Rewrite so the stated reason is
true: cv2 is available, so the cost is the measurement work and a `CACHE_VERSION`
bump, not a new dependency. Do not change the verdict — it stays deferred.

- [x] **Step 3: build-status — layer 3 against track-stitch**

Every layer-3 entry is written as if track-stitch had not landed. Track-stitch
(2026-07-28) addresses the same failure — a mid-episode hero ID switch — by a
different mechanism: geometric overlap-vs-gap evidence, not descriptor
continuity. Read `docs/specs/2026-07-28-track-stitch-design.md` and
`stitch_ids` in the tracking module, then rewrite each entry to state (a) that
stitch now covers the occlusion-and-re-acquisition case, and (b) that whether a
real remainder is left has **not been re-assessed**. Do not claim it is closed
and do not claim it is untouched — say precisely what is known.

- [x] **Step 4: Commit**

```bash
git add -A && git commit -m "docs: correct three stale deferral pointers

A Phase F that never existed, a cv2 blocker that disappeared when the
tracking ladder landed, and three layer-3 entries written as though
track-stitch had not shipped."
```

---

## Task 5: `docs/backlog.md` + the rule (controller-owned)

**Files:**
- Create: `docs/backlog.md`
- Modify: `CLAUDE.md` (Quick Reference row + the source-of-truth section)
- Modify: `docs/build-status.md` (*Deferred / open* collapses to a pointer)
- Modify: `docs/pipeline-map.md` (roadmap links to the queue)
- Modify: `docs/fixes-backlog.md` (header notes that priority now lives in the queue)
- Modify: `docs/development-workflow.md` (the slice-completion rule)

This task is written by the controller, not dispatched: it is the output of an
audit of all 28 `§Deferred` sections that lives in the controller's context.

- [x] **Step 1:** Write `docs/backlog.md` — every open item as a row with
  status / priority / size / source, per design §3.
- [x] **Step 2:** Add the rule from design §4 to `development-workflow.md`'s
  slice-completion checklist, and to the docs-sync step every plan ends with.
- [x] **Step 3:** Point the four other documents at the queue; delete no content.
- [x] **Step 4:** Register the new doc in `CLAUDE.md`'s Quick Reference table.
- [x] **Step 5:** Full suite, then commit.

---

## Self-Review

**Spec coverage:** design §1.1 → Task 0; §1.2 → Task 1; §1.3 → Task 2; §1.4 →
Task 3; §2 → Task 4; §3 and §4 → Task 5. §5's "out" list is honoured — no task
builds anything the queue merely lists.

**Placeholder scan:** Tasks 0, 1, 3 carry the literal code. Tasks 2 and 4 name a
file and a specific edit but deliberately tell the implementer to read the
surrounding code first, because both depend on call sites this plan did not pin
down (`Delivery.dims`' exact signature for a native delivery; the three
build-status entries' wording). Each says so explicitly and asks for a report.

**Type consistency:** `smooth_window_s` uses the identical band `(0, 2.0]` in
`EDLEpisode`, `Manifest` and the existing `ReframeSpec`, so no layer can accept a
value the next one rejects. `platform` is `str` with `""` as unset at all three
layers (`EDL`, `ReelManifest`, `safe_zone_for`).
