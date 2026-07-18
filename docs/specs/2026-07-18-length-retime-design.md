# Length re-time (Phase B tail) — Design Spec

Closes the **two auto-fixes** the pacing design parked together in its scope
decision 1 ([§10](2026-07-14-pacing-design.md)) — the last open items of
**Phase B — music spine**:

1. the **retry-time length auto-fix** — `build_reel`'s `length` failure re-times
   instead of escalating to a human
   ([reel-retry-loop §deferred](2026-07-11-reel-retry-loop-design.md)), and
2. the **pacing-gate back-edge** — the spine won't fit the footage → re-time
   rather than report (montage §4.1's back-edge row: "pacing gate (spine won't
   fit) → re-pick `start_offset`").

Both are the same move at two different edges: **the reel's target length
re-times DOWN to what the footage actually delivers** — once at authoring (so
the plan is coherent before a frame is cut) and once at retry (so residual
frame-rounding drift doesn't wake a human). Neither ever re-times *up*: §2
explains why the physics forbids it.

## Scope decisions (from brainstorming, 2026-07-18)

1. **Both edges in one slice.** They are complementary and each is small: the
   back-edge stops the mismatch from ever reaching `build_reel`; the retry
   absorb catches the residual drift authoring cannot predict.
2. **`build_reel` absorbs drift, escalates beyond a band.** Within a bounded
   shortfall the target re-times to the reel's real length and the reel
   delivers; beyond the band — and for **any** over-length reel — it escalates
   exactly as today. Loop-2 stays **mechanical**: locked clips, frozen routes,
   no re-cut. (Rejected: widening loop-2 to reach back into `extract`/`edit-plan`
   and re-cut footage — it would break the frozen-route invariant that makes a
   reprocess deterministic, and turn the reel driver into a second authoring
   stage.)
3. **The back-edge is a pure re-time, not a librosa re-pick.** When the bound
   footage under-fills the spine, the reel's target becomes the realized total —
   stdlib arithmetic over durations the binder already computed, no audio IO, no
   heavy dep in the authoring path. (Rejected for v1: re-picking
   `MUSIC.start_offset` via `beats.choose_offset` — the design's literal wording,
   but it needs librosa and a re-analysis to answer a question the realized
   durations already answer. It stays the manual rung, §9.)
4. **Pacing owns the paced reel's length.** When a `Spine` is supplied,
   `EDL.target_dur` comes from the spine and the footage, not from
   `selection.target_dur` — the pacing design's scope 6 ("pacing owns
   length/energy per position") taken to its conclusion. Un-paced authoring is
   untouched.

## §1 — Architecture & files

No new module: both fixes are small, surgical edits to code that already owns
the decision. The pure decision core (`reel_orchestration.next_action`) keeps
its "one report → exactly one action" shape; the shell (`build_reel`) keeps
executing what it is told.

```
scripts/lib/models.py            EDIT  ReelCheckSpec + length_retime_max: float = 1.0 (§3.1)
scripts/check_reel.py            EDIT  promote the inline 0.5 length gate to _LENGTH_TOL (§3.1)
scripts/lib/reel_orchestration.py EDIT ReelAction + retime; _shortfall(); next_action(..., 
                                       length_retime_max) absorbs a within-band shortfall,
                                       new kind "retime" (§3.2)
scripts/build_reel.py            EDIT  mutable spec across rounds; adopt action.retime + _log;
                                       "retime" → re-check; loop bound +2 → +3 (§3.3)
scripts/edit_plan.py             EDIT  build_edl: when paced, target_dur = min(realized,
                                       spine.target_dur) + the two back-edge logs (§4)
tests                            EDIT  test_reel_orchestration (7), test_models, test_edit_plan (4),
                                       integration/test_reel_retry (2 real-ffmpeg proofs) (§7)
docs                             EDIT  this spec + plan + pacing §10 + reel-retry + montage §4.1
                                       + build-status + pipeline-map + CLAUDE.md (§10)
```

**Dependency DAG (unchanged, no new edges):** `reel_orchestration` still imports
only `models`; `build_reel` gains `dataclasses` + `sys` (stdlib) and nothing
else; `edit_plan` already imports `pacing` for the `Spine` type. No module
learns about a stage it did not already know.

## §2 — The physics: why the target only ever shrinks

`mix.mix` refuses to build a stem longer than the analyzed fragment:

```python
    if dur > music.duration + 0.1:
        raise ValueError(f"mix: reel dur {dur}s exceeds the analyzed music window {music.duration}s "
                         ... "a shorter stem would silently desync from the video")
```

and `build_reel` builds the stem at the master's **real** duration
(`mix.mix(music, work_dir, check_reel._probe_dur(master), …)`), not at
`target_dur`. Three consequences shape this whole slice:

- **The audio is never the thing that fails.** The stem already fits whatever
  the master turned out to be, so a `length` failure is purely the *gate*
  disagreeing with the plan — nothing is out of sync.
- **A shorter reel is safe to accept.** `master < target ≈ music.duration` ⇒
  `mix` is comfortably inside its guard. Re-timing the target down to the real
  length costs nothing and loses nothing.
- **A longer reel must not be accepted.** `master > music.duration` ⇒ `mix`
  raises. Today an over-length reel escalates at the `length` gate and therefore
  never reaches the stem; if the absorb were symmetric it would trade that clean
  stop-and-report for a hard raise deep in the mixer. So the band is
  **one-sided**: shortfall only.

This is not a tuning choice — you cannot invent music. An over-length reel is an
editorial decision ("extend the fragment or drop episodes"), and both edges keep
it human.

## §3 — Fix A: `build_reel` absorbs a within-band shortfall

### §3.1 — The band

`ReelCheckSpec` gains one threshold, alongside the advisory tolerances it
already carries:

```python
    length_retime_max: float = 1.0     # max shortfall (target − dur) build_reel absorbs by
                                       # re-timing the target to the reel's real length (§3)
```

validated in the established shape:

```python
        if not isinstance(self.length_retime_max, (int, float)) or self.length_retime_max <= 0:
            raise ValueError(f"ReelCheckSpec.length_retime_max must be a positive number of "
                             f"seconds, got {self.length_retime_max!r}")
```

`check_reel`'s inline `0.5` becomes a named constant so the two numbers can be
read against each other:

```python
_LENGTH_TOL = 0.5      # the length gate's own ± band; build_reel absorbs a further
                       # (_LENGTH_TOL, spec.length_retime_max] of SHORTFALL on top (§3)
...
    length_ok = abs(total - spec.target_dur) <= _LENGTH_TOL
```

So the absorb window is the half-open `(0.5, 1.0]` of shortfall: at or under
0.5 s the gate already passes and there is nothing to absorb; past 1.0 s the reel
is short enough to be a real editorial miss. `ReelManifest.check_spec` builds
`ReelCheckSpec(target_dur, variety_min, color_delta_max)` and leaves the rest at
their defaults, so nothing needs plumbing through the manifest.

**Why 1.0 s.** On the paced path the back-edge (§4) has already set
`target_dur` to the planned realized total, so the only residual is
extract/encode frame-rounding accumulating across episodes — ~1 frame each,
≈0.33 s over ten episodes at 30 fps, and sub-second for any plausible reel. One
second absorbs that with headroom while still escalating a missing beat's worth
of footage.

### §3.2 — The decision (`reel_orchestration`)

`ReelAction` gains a field and a kind:

```python
@dataclass(frozen=True)
class ReelAction:
    kind: str                          # "deliver" | "reprocess" | "escalate" | "retime"
    reprocess: tuple[ReprocessItem, ...] = ()
    finding: dict | None = None
    retime: float | None = None        # new target_dur when a within-band shortfall is absorbed (§3)
```

```python
def _shortfall(f: ReelFailure) -> float | None:
    """target − dur for a length failure, or None when the reel is LONGER than target.
    An over-length reel is never absorbed: the stem is cut from a fixed music fragment
    and mix.mix refuses dur > music.duration, so re-timing UP would trade a clean
    escalate for a hard raise at the mixer (§2)."""
    gap = f.detail["target"] - f.detail["dur"]
    return gap if gap > 0 else None
```

```python
def next_action(fail_reasons: list[ReelFailure], attempts: dict[int, int], cap: int,
                length_retime_max: float = 0.0) -> ReelAction:
    """One decision for the whole reel (design §3). Escalate wins the round: any
    non-auto-fixable or capped failure returns Escalate immediately, so we never spend
    reprocess rounds on a reel that also carries an unfixable fault. `length` is
    auto-fixable in exactly one shape — a shortfall inside length_retime_max, absorbed
    by re-timing the target DOWN to the reel's real length; an over-length reel and a
    shortfall past the band still escalate to pacing. The default 0.0 keeps a caller
    that does not pass a band on the pre-slice behaviour (length always escalates)."""
    if not fail_reasons:
        return ReelAction("deliver")
    items: dict[int, ReprocessItem] = {}
    retime: float | None = None
    for f in fail_reasons:
        if f.check == "length":
            gap = _shortfall(f)
            if gap is not None and gap <= length_retime_max:
                retime = f.detail["dur"]        # the reel IS this long — make it the target
                continue
            return ReelAction("escalate", finding={
                "reason": "not-auto-fixable", "check": f.check,
                "episode_idx": f.episode_idx, "escalate_to": f.escalate_to,
                "detail": f.detail})
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
    if items:
        return ReelAction("reprocess", reprocess=tuple(items[k] for k in sorted(items)), retime=retime)
    if retime is not None:
        return ReelAction("retime", retime=retime)
    return ReelAction("deliver")
```

**Escalate-wins is preserved exactly.** An absorbed length is `continue`d rather
than returned, so a capped colour fail or a `variety` fail later in the list
still short-circuits to Escalate and the pending `retime` is discarded with it —
the reel never delivers on a round that also carries an unfixable fault.

**The re-time rides along with a reprocess.** When a within-band shortfall
co-occurs with a fixable colour fail, the action is `reprocess` *carrying*
`retime`: the shell adopts the new target and then reprocesses, so `length` stops
firing on every subsequent round instead of blocking the colour convergence it
has nothing to do with.

### §3.3 — The shell (`build_reel`)

Three changes. First, the check spec becomes a round-scoped local rather than a
property read, so a re-time can persist:

```python
    spec = rm.check_spec          # mutable across rounds: a length re-time replaces target_dur
```

Second, the loop adopts the re-time before dispatching on `kind`:

```python
        report = check_reel.run(master, clips, spec, report_path,
                                music=music, audio=audio, geometry=geometry, platform=rm.platform)
        action = reel_orchestration.next_action(report.fail_reasons, attempts, rm.cap,
                                                spec.length_retime_max)
        if action.retime is not None:
            _log(f"build_reel: reel is {action.retime:.2f}s against a {spec.target_dur:.2f}s target "
                 f"— inside the {spec.length_retime_max:.2f}s band, re-timing the target to the "
                 f"reel's real length (the stem is already cut to the master, so audio stays in sync)")
            spec = dataclasses.replace(spec, target_dur=action.retime)
        if action.kind == "retime":
            continue              # re-check with the re-timed target; clips unchanged, no re-assemble
```

Third, the defensive bound grows by one to leave room for that `continue`:

```python
    for _ in range(rm.cap * len(rm.episodes) + 3):   # +3: the once-after-picture mix `continue`,
                                                     # one length-retime `continue`, the deliver pass
```

`_log` is added to `build_reel` in the established shape (`print(msg,
file=sys.stderr)`, the `beats._log`/`edit_plan._log` pattern) — the re-time is
**never silent**.

**Why re-check instead of patching the report.** `deliver` gates hard on
`report.overall is False`, so the delivered report must genuinely pass. Editing
the written `reel_report.json` in place would duplicate `check_reel`'s length
arithmetic in the driver and ship a report that says something the checker never
said. Re-running `check_reel` with the new target costs one pass on the terminal
round and yields a report that is true: `target` is the length the reel actually
is, and `length.passed` is `True` because it genuinely is.

**The re-time fires at most once.** A colour or black reprocess re-grades a
locked window against a frozen route; it never re-times. So the master's
duration is invariant across rounds, and once the target equals it the gate
cannot fire again. The adopted value is `check_reel`'s `round(total, 3)` rather
than the raw probe — a ≤0.5 ms difference the re-check absorbs inside its own
0.5 s tolerance, so the rounding cannot cost the reel a second round.

## §4 — Fix B: the authoring back-edge (`edit_plan.build_edl`)

`_bind_pacing` already re-times each episode to `min(ep.dur, slot.dur)` and logs
a shortfall ("the length gate will see the shortfall") or an over/underflow. What
it does **not** do is tell anyone downstream, so `EDL.target_dur` keeps whatever
optimistic number `selection.json` carried — typically `MUSIC.duration` per the
pacing design's scope 4 — and the mismatch surfaces a whole pipeline later as a
`length` escalation. The back-edge closes that gap where the numbers are already
in hand:

```python
    if pacing is not None:
        episodes = _bind_pacing(episodes, pacing)
    cap = selection.get("cap")
    target = selection.get("target_dur")
    if pacing is not None:
        realized = sum(e.dur for e in episodes)
        target = min(realized, pacing.target_dur)   # the paced reel is never planned longer
                                                    # than the fragment it is cut to (§2)
        if realized < pacing.target_dur - _BACK_EDGE_TOL:
            _log(f"pacing back-edge: the bound footage realizes {realized:.2f}s of the "
                 f"{pacing.target_dur:.2f}s spine — re-timing the reel target to {realized:.2f}s; "
                 f"for a tighter cut re-pick a shorter fragment "
                 f"(beats --auto-start --duration {realized:.0f}) and re-derive the spine")
        elif realized > pacing.target_dur + _BACK_EDGE_TOL:
            _log(f"pacing back-edge: the bound footage realizes {realized:.2f}s against a "
                 f"{pacing.target_dur:.2f}s spine — the target stays at the fragment length; the "
                 f"excess {realized - pacing.target_dur:.2f}s escalates at the reel gate "
                 f"(extend the fragment or drop episodes — music cannot be invented)")
    return EDL(episodes=tuple(episodes), music=selection.get("music"), cast=cast,
               cap=cap if cap is not None else 3, target_dur=target)
```

with `_BACK_EDGE_TOL = 1e-6` beside the module's other constants. `realized` sums
**every** bound episode, including an over-flow tail that `_bind_pacing` left at
`beat_slot=None` with its own `dur` — the reel is as long as everything in it,
not as long as the slotted part.

**Three cases, one expression.**

| Case | `realized` vs `spine.target_dur` | `EDL.target_dur` | Downstream |
|------|----------------------------------|------------------|------------|
| under-fill (short window, unfilled tail slots) | `<` | `realized` — the back-edge re-time | `length` passes by construction |
| exact fill | `==` | `spine.target_dur` (same number) | unchanged |
| over-flow (more footage than fragment) | `>` | `spine.target_dur` — clamped | `length` fails long → **escalates** (§2) |

**Blast radius.** `pacing is None` is untouched — `target_dur` stays
`selection.get("target_dur")`, the un-paced regression guard. On the paced path
the numbers coincide with today's in the exact-fill case (whether `selection`
supplied `MUSIC.duration` or nothing at all, since `edl_to_reel` falls back to
`sum(ep.dur)`), so only the two genuinely-broken shapes change behaviour: the
under-fill stops lying about its length, and the over-flow stops relying on
`mix`'s raise as its error path (§6).

## §5 — Worked

A 15.0 s fragment, a 6-slot spine, and a selection whose episode 3 has only
1.2 s of footage where its slot wants 2.0 s.

**Authoring.** `_bind_pacing` binds five slots at their full length and episode 3
at 1.2 s, logging the shortfall as it always did. `realized = 14.2 s <
15.0 s` ⇒ the back-edge re-times `EDL.target_dur` to **14.2**, logging the
re-time and the "re-pick a shorter fragment" remedy. The EDL now describes a
reel it can actually produce.

**Reel.** `extract` cuts the windows, `process_episode` locks them,
`assemble` produces a master that ffprobe reports at 14.61 s — 0.41 s of
frame-rounding spread over six episodes. `|14.61 − 14.2| = 0.41 ≤ 0.5` ⇒ the
length gate never fires. `build_reel` builds the stem at 14.61 s (inside `mix`'s
guard, since 14.61 < 15.0) and delivers.

**Without the back-edge** (today): `EDL.target_dur` stays 15.0, the master is
14.61, `|14.61 − 15.0| = 0.39 ≤ 0.5` — this one still squeaks through. Push the
shortfall to a full 2.0 s slot and the master is 13.0 against a 15.0 target:
today that escalates to a human for a reel that was always going to be 13 s.
With **both** fixes: the back-edge re-times the target to 13.0 at authoring, and
if extract drift then puts the master at 12.4 (0.6 s short, past the 0.5 gate),
Fix A absorbs it — 0.6 ≤ 1.0 — re-times to 12.4, re-checks clean, delivers. A
master at 11.5 (1.5 s short) escalates: that is a missing episode, not drift.

## §6 — Edge cases & fail-loud

- **Over-length reel, any size** → `_shortfall` returns `None` → escalate, exactly
  as today. Never absorbed, never padded, looped, or stretched (§2).
- **Shortfall past the band** → escalate with the unchanged `not-auto-fixable`
  finding carrying `check="length"`, `escalate_to="pacing"` and the
  `{dur, target}` detail — a human sees the same report they see today.
- **Absorb + a capped colour fail** → escalate; the pending `retime` is dropped
  with the round (escalate-wins, §3.2).
- **Absorb + a fixable colour fail** → `reprocess` carrying `retime`; the target
  is adopted first so `length` stops re-firing while colour converges.
- **`length_retime_max` below the gate's 0.5** → nothing is ever absorbed (the
  gate passes first). A no-op, not an error — validation only refuses
  non-positive values.
- **A caller that does not pass a band** → `next_action`'s `length_retime_max=0.0`
  default reproduces the pre-slice behaviour exactly; the opt-in lives in the
  spec the driver threads.
- **Paced over-flow with no `selection.target_dur`** → before this slice,
  `EDL.target_dur` fell through to `sum(ep.dur)`, the length gate passed, and the
  failure surfaced as `mix`'s hard raise ("reel dur Xs exceeds the analyzed music
  window Ys") after the whole picture pass. The §4 clamp turns that into the
  clean stop-and-report it should always have been. `mix`'s guard stays as the
  backstop.
- **Un-paced authoring** → `pacing is None` changes nothing; a manual
  `target_dur` mismatch still meets Fix A's band at the reel gate.
- **Malformed length detail** → `_shortfall` reads the `{dur, target}` keys
  `check_reel` always writes for a length failure; a `KeyError` here would mean
  the checker and the ladder disagree about the contract, which is a caller bug,
  not a runtime condition to swallow.

## §7 — Testing

**Unit — `tests/lib/test_reel_orchestration.py`** (pure, exhaustive):

- a within-band shortfall as the sole failure → `ReelAction("retime", retime=dur)`
- a within-band shortfall + a colour fail → `kind == "reprocess"`, items present,
  `retime == dur`
- a shortfall past the band → `escalate`, `finding["check"] == "length"`
- an over-length reel inside the band's magnitude → `escalate` (the one-sided
  proof — the same absolute gap that absorbs as a shortfall must escalate long)
- a within-band shortfall + a capped colour fail → `escalate` (escalate-wins)
- `length_retime_max` left at its `0.0` default → `escalate` (pre-slice guard)
- no failures → `deliver` (regression guard, unchanged)

**Unit — `tests/lib/test_models.py`:** `ReelCheckSpec.length_retime_max` defaults
to 1.0, round-trips through the spec, and raises with a remedy on `0`, a negative,
and a non-number.

**Unit — `tests/lib/test_edit_plan.py`** (the §4 table, one test per row):

- paced, a window shorter than its slot → `EDL.target_dur == realized <
  spine.target_dur`, and the back-edge line reaches stderr
- paced, footage fills the spine → `EDL.target_dur == spine.target_dur`, no
  back-edge line
- paced, more footage than the fragment → `EDL.target_dur == spine.target_dur`
  (clamped) + the over-flow line
- `pacing=None` → `EDL.target_dur == selection["target_dur"]` (regression guard)

**Integration — `tests/integration/test_reel_retry.py`** (real ffmpeg, silent
reel — the absorb is independent of the stem, and the music path is already
proven by `test_music_spine.py`):

- a `ReelManifest` whose assembled master lands 0.7 s under `target_dur` →
  `status == "delivered"`, and the written `reel_report.json` shows
  `checks.length.passed is True` with `detail.target` equal to the reel's real
  duration — the proof it re-timed rather than escalated
- the same manifest with the target 3 s high → `status == "stop_and_report"`,
  `finding["check"] == "length"`

## §8 — Landmines touched (montage §12)

- **Never a silent degrade.** Every re-time prints its remedy to stderr — the
  back-edge names the shorter fragment to re-pick, the absorb names the band it
  fell inside. The delivered `reel_report.json` states the re-timed target
  honestly because the report is **re-checked**, not patched (§3.3).
- **One-sided by physics, not by preference.** The target only shrinks. A reel
  longer than its music escalates at both edges; `mix`'s own guard remains the
  backstop rather than the error path (§2, §6).
- **Determinism.** A reprocess re-grades a locked window against a frozen route
  and never re-times, so the master duration is invariant across rounds and an
  absorbed re-time is stable and fires once. The pure core takes numbers only —
  no audio IO, no librosa, on either edge.
- **No pixel or timing op added.** This slice writes no ffmpeg arguments: no
  `-ss` (the frame-accurate seek landmine is untouched — `extract` still cuts
  the same windows), no `lutrgb`, no `scale`, no colour op. It changes one
  number and one decision.

## §9 — Non-goals / deferred

- **Re-picking `MUSIC.start_offset` at the back-edge** (the montage §4.1 row's
  literal wording) — the pure re-time answers v1's question from durations
  already in hand; `beats.choose_offset` stays the manual rung when a human wants
  a genuinely better fragment rather than a shorter target.
- **Re-cutting footage inside loop-2** — would need `footage_root` + `extract` +
  a re-bind inside the reel driver and would break the frozen-route invariant
  (scope 2).
- **Auto-fixing an over-length reel** — escalated by design; music cannot be
  invented (§2).
- **Re-deriving a truncated `Spine` for `PACING.json`** — `PACING.json` is written
  by `scripts/pacing.py` before edit-plan runs, so re-writing it from the binder
  is out of edit-plan's lane. The re-time lands on `EDL.target_dur`, which is
  what the length gate and the mixer actually read.
- **Enforcing `SPEC.length_s`** — still the cross-check log the pacing design
  made it (scope 4); the spine follows the fragment.
- **Librosa section detection / phrase-aware slot grouping** — pacing §10, still
  deferred; unrelated to either edge.

## §10 — Doc-sync (updated on completion)

- `docs/specs/2026-07-14-pacing-design.md` §10 — the first two deferred bullets
  (retry-time auto-fix, pacing-gate back-edge) flip to **landed 2026-07-18**,
  pointing here; scope decision 1's "stays deferred" sentence is reconciled.
- `docs/specs/2026-07-11-reel-retry-loop-design.md` — the ladder row
  `length → Escalate(pacing)` gains the within-band shortfall re-time; the
  "`variety`/`length` auto-fix needs the front-half stages" deferred bullet
  records that `length` landed (and `variety` did not).
- `docs/specs/2026-07-05-montage-skillset-design.md` — the §4.1 back-edge row
  ("pacing gate (spine won't fit) → re-pick `start_offset`") gains a **built**
  note: the pure re-time ships, the `start_offset` re-pick stays the manual rung.
- `docs/build-status.md` — a Done entry + the next-action refresh.
- `docs/pipeline-map.md` — the Phase B roadmap line: both auto-fixes land ⇒
  **Phase B — music spine ◐ → ✅**; the critical-path section's "genuinely open
  on the quality side: the two pacing auto-fixes" sentence retires.
- `CLAUDE.md` — two registry rows (this spec + its plan).
