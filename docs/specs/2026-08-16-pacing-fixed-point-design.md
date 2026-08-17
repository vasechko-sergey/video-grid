# The pacing fixed point — and the absorb that overwrites a chosen length

> Two P2 rows from [the music-outro-fit slice](2026-08-14-music-outro-fit-design.md)'s
> own final review (§11.8, §11.10), plus the music-digest idea folded in from
> [shadow-red-length-reconcile](2026-08-15-shadow-red-length-reconcile-design.md) §6/§7.

## 0. Why this slice exists

`scripts/pacing.py` fits its spine to `[ep.play_dur() for ep in edl.episodes]` — the
durations it reads out of `EDL.json`. Those durations are *outputs* of earlier stages
(the pacing binding, then the outro fit), not the scenario's own lengths. So the stage
fits its own previous output.

The queued row named the case where that becomes a hard refusal: after an outro fit the
closing episode's `dur` is a number footage re-projection cannot reproduce, `_bind_pacing`
refuses, and re-applying deadlocks. **A measurement taken while designing this slice
widened the row** — the same root causes a second, silent defect with no outro anywhere
near it, and it fires on precisely the workflow the stage's own report recommends (§1.2).

That measurement also settles the row's own "or": subtracting the recorded `outro.moved`
cannot be the fix, because the drift happens when nothing moved.

---

## 1. What the measurement found

### 1.1 The deadlock (already recorded, not re-measured here)

From music-outro-fit §11.8, measured on a 120 BPM fixture with the real `pacing.fit_spine`
and the real `write_edit_plan` / `build_pacing` drivers:

| pass | EDL durs | refit spine | re-apply |
|---|---|---|---|
| no fit | `[6.0, 4.0]` | `[6.0, 4.0]` | binds ✓ |
| with fit | `[6.0, 4.70]` | `[6.0, 4.70]` | **raises**: `slot 1 is 4.70s against a 4.00s episode — further apart than the 0.25s snap allows` |

The refusal is in `_bind_pacing`, so dropping `--music` does not avoid it. The documented
escape is a three-command detour (rebuild without `--pacing`, re-fit, re-apply), named in
the refusal message and in three skills.

### 1.2 The drift the row did not name

Re-fitting an already-fitted EDL against a **different** music window does not converge on
the answer the scenario's own cuts would have produced. Measured against the real
`pacing.fit_spine` (probe under the session scratchpad):

```
allowance @128 BPM = 0.2344s      @110 BPM = 0.2727s

scenario           [5.77,   3.41,   6.02,   4.88]
fit -> M1 (128)    [5.625,  3.2812, 6.0938, 4.88]

fitted   -> M2 (110)  [5.4545, 3.2727, 6.0, 4.88]   grid lines: beats 10 / 16 / 27
scenario -> M2 (110)  [6.0,    3.2727, 6.0, 4.88]   grid lines: beats 11 / 17 / 28
```

**This is not a rounding difference.** From the scenario's 5.77s, beat 11 (6.0s) is 0.23s
away — inside the 0.2727s allowance, so the fit reaches it. From the already-snapped
5.625s the same line is 0.375s away, past the allowance, so the best reachable line is
beat 10. The opening cut lands on a **different beat of the song**, and because the grid
is cumulative every later cut inherits the shift: the whole reel is one beat (0.5455s)
short.

Two properties matter for the fix:

- **Re-fitting the same window IS a fixed point today.** The cuts are already on that
  grid, so every shift is zero and the second fit reproduces the first. The defect is
  invisible until the window changes.
- **Changing the window is the stage's own recommended remedy.** `build_pacing` logs
  `"Try another window (beats --auto-start)"` when no level fits, and `PACING.md` prints
  the rejected levels so the user can go do exactly that. The drift fires on the
  workflow the report asks for.

### 1.3 Why `outro.moved` is not the fix

The backlog row offered two mechanisms: fit footage-projected durs, **or** subtract the
recorded `outro.moved`. §1.2 happens with no outro at all — `EDL.outro` is `None` and
`moved` is `0.0` — so subtracting it changes nothing there. It repairs the deadlock and
leaves the root in place. Rejected by measurement, not by taste.

A third mechanism was considered and rejected on structure: let `pacing.py` re-project the
episodes itself from `selection.json` + `FOOTAGE.json`. It needs no new EDL field, but it
duplicates `window_to_episode` — span merging, `start_offset`, the ramp gate — in a second
place, giving the project two sources of truth for how long an episode is.

---

## 2. `base_dur` — the scenario's length becomes a recorded fact

```python
base_dur: float | None = None   # the footage-projected source length, before any grid
                                # snap or outro move. Authoring metadata: nothing in the
                                # render path reads it.
```

- **Written once**, by `window_to_episode`, as the window's own `dur` — the same value it
  already passes to `EDLEpisode(dur=...)`. A span reference goes through `_merge_windows`
  first, so a merged envelope records its merged length, which is correct: the merge is
  part of the scenario, the snap is not.
- **Never rewritten.** `_bind_pacing` and `_apply_outro` both go through
  `dataclasses.replace(ep, dur=...)`, which carries `base_dur` across untouched.
- **`dur` cannot be authored**, so `base_dur` is unambiguous: `window_to_episode` passes
  `dur` positionally and forwards `**editorial`, so a `dur` in `selection.json` raises
  "unknown or missing editorial field" rather than overriding the projection.
- **Nothing in the render path reads it** — not `extract`, not `edl.to_manifest_dict`, not
  `check_reel`. It sits beside `beat_slot` and `processing_notes` as authoring metadata,
  and its docstring says so.

### 2.1 `base_play_dur()`

```python
def base_play_dur(self) -> float:
    """The PLAYED length the scenario projected — base_dur plus this episode's own
    ramp extra. Falls back to play_dur() when base_dur is absent."""
```

The ramp extra is `play_dur() - dur`, and it is **constant in `dur`** while the ramp
region stays enclosed in the window (speed-ramp design §2) — which is exactly the identity
`_bind_pacing` already relies on when it computes `extra = played - ep.dur` and assigns
`dur = slot.dur - extra`. So `base_dur + (play_dur() - dur)` is exact, not an
approximation.

The enclosure holds for `base_dur` as well as for `dur`: `EDLEpisode.__post_init__` runs
`ramp.validate_window` against `dur` at construction, and at construction `dur` **is**
`base_dur`. Later binds only move `dur`; the region never moves.

### 2.2 The absent arm

`base_dur is None` → `base_play_dur()` returns `play_dur()`, which is today's behaviour
exactly. Two populations reach it:

- **A hand-authored SP1 `EDL.json`** — the `edl_to_reel` front door, which has no scenario
  behind it. `dur` *is* the author's intent, so falling back to it is not a degradation.
- **An `EDL.json` written before this slice.** It keeps today's behaviour, deadlock
  included, and the documented detour keeps working.

No refusal is added for the absent case. A blanket refusal would break the hand-authored
front door, which is the one input this project has deliberately kept open.

**Where that population is warned, and where it is NOT** *(corrected by the final
whole-branch review, which reproduced it end to end)*. This section first said
`_bind_pacing`'s refusal "says which arm it is on, so a reader is never left guessing".
That was wrong, and wrong in a way worth recording: `_bind_pacing` is reached only from
`build_edl`, whose episodes always come from `window_to_episode`, which always sets
`base_dur` — so an episode with `base_dur is None` never arrives there in production, and
the arm-specific sentence is unreachable outside a hand-built unit-test episode.

The pre-slice population hits the deadlock through a **different door**. Measured on a
`[6.0, 4.70]` EDL with `base_dur` stripped:

```
refit spine slots:  [6.0, 4.70]        <- pacing read the stale EDL and fell back to play_dur
REFUSAL: pacing: slot 1 is 4.70s against a 4.00s episode …
```

`pacing` reads the stale artifact; `build_edl` then re-projects fresh episodes **with**
`base_dur = 4.00`, so the guard compares a stale spine against a correct projection. Both
sides are behaving as designed; only the diagnosis was in the wrong place.

So the warning lives where the pre-slice artifact is actually read — `build_pacing` logs a
named line when any episode lacks `base_dur` — and `_bind_pacing`'s refusal carries the
rebuild-without-`--pacing` escape **unconditionally**, not behind the dead predicate.

---

## 3. The readers that move

| reader | today | after |
|---|---|---|
| `pacing.build_pacing` | `[ep.play_dur() …]` | `[ep.base_play_dur() …]` |
| `pacing._bounds` grow | `min(allow, room − ep.dur)` | `min(allow, room − base)` |
| `pacing._bounds` shrink | `min(allow, ep.dur/2, tail_room(spec, ep.dur))` | same three, on `base` |
| `edit_plan._bind_pacing` guard | `abs(slot.dur − ep.play_dur())` | `abs(slot.dur − ep.base_play_dur())` |
| `edit_plan._bind_pacing` assign | `dur = slot.dur − extra` | unchanged |
| `edit_plan._apply_outro` | acts on the bound episodes | unchanged |
| `edit_plan._back_edge_target` | sums `play_dur()` | unchanged |

`_apply_outro` and `_back_edge_target` are deliberately untouched: they measure the reel
that is actually being written, which is the bound-and-fitted state, not the scenario.

### 3.1 Why this is a fixed point

After the change, the spine is a function of `(base, music)` alone, and the bound `dur` is
a function of `(spine, ramp extra)` alone. Neither reads the previous run's output. So:

- **fit → apply → fit → apply** reproduces the same `EDL.json`, for any number of
  repetitions and for any sequence of music windows.
- The **deadlock disappears**: the spine was fitted to `base`, the guard compares against
  `base`, and they agree by construction — including on the closing episode the outro fit
  moved.
- The **one-beat drift disappears**: every fit starts from the scenario's own cuts, so the
  answer no longer depends on which windows were tried before.

The three-command detour and the three skill paragraphs that teach it are deleted, not
rewritten.

---

## 4. `Spine.music_digest`

```python
music_digest: str = ""   # "" = not recorded (a PACING.json from before this slice)
```

Written by `build_pacing` from the winning window:

```python
digest_obj({"track": digest_file(m.track),
            "start_offset": m.start_offset, "duration": m.duration})
```

`build_edl` compares it against the same value computed from the supplied `MUSIC.json`,
and refuses a mismatch, naming both.

### 4.1 Why the window and not just the file

`_TEMPO_TOL` (0.5 BPM) catches a track swap — the 140.625-against-110.294 case that
shipped in the 2026-08-03 run. It cannot catch **the same track at a different
`start_offset`**, and neither can a digest of the audio file alone: the beat grid is
reel-relative, so moving the in-point moves every grid line while the BPM stays
bit-identical. A spine fitted to the window at 46.0s binds silently to the window at
147.772s — and `beats --auto-start` returning a different offset on a re-run is a routine
event, not an exotic one.

Hashing the file's **content** rather than its path keeps the check stable when a run
directory moves.

### 4.2 The ladder

1. Both digests available and equal → bound.
2. Both available and different → **refuse**, naming both digests and the remedy (re-run
   pacing against this `MUSIC.json`).
3. Either side missing — `music_digest` is `""` (old `PACING.json`), or `MusicSpec.track`
   does not resolve to a readable file → a named **not-checked** line, then fall back to
   the `_TEMPO_TOL` comparison, which is kept for exactly this rung.

The not-checked arm exists because the alternative is a check that silently reports
"same" when it measured nothing — the failure mode this project has now hit twice
(the look gate's fade-out bar, §7.1 of the frame-probe slice).

---

## 5. The absorb refuses a chosen length

When the assembled master is shorter than `target_dur` but inside
`ReelCheckSpec.length_retime_max`, `build_reel` replaces the target with the master's real
length and re-checks. Its justification is stated in the code: *the reel **is** that long,
so the target was wrong.*

**That premise is false when the target was chosen.** With an outro fit,
`target_dur = line + fade` is a decision about where the music resolves, not a prediction
about how long the picture came out. Absorbing the shortfall keeps the fade ending at the
reel's end — `mix` is handed the master's probed length, so the bookend always lands there
— and moves the **bar line** out from under it.

The magnitudes make this concrete: `length_retime_max` is **1.0s**, and the original
complaint the whole outro slice exists to fix was a reel ending **0.96s past a bar line**.
The absorb band is as wide as the bug.

### 5.1 The change

`reel_orchestration.next_action` gains `outro_fixed: bool = False`. When true, a within-
band shortfall no longer absorbs: it escalates to `pacing` like every other length
failure, with a finding that says the length was chosen as `line + fade` and that a
shortfall moves the fade off the line.

`ReelManifest` gains `outro: dict | None`, filled by `edl_to_reel` from
`EDL.outro.to_dict()`. It is a config-spec field like every other: a non-None value is
round-tripped through `outro.OutroFit.from_dict` at construction, whose `__post_init__`
already refuses a rung outside `RUNGS`. So a malformed outro fails loud instead of
reading as `"unchanged"` and silently restoring the absorb.

`build_reel` then derives
`outro_fixed = rm.outro is not None and rm.outro.get("rung", "unchanged") != "unchanged"`.
The `.get` default is deliberate: with validation in place a missing key cannot reach
here, and if it ever does, defaulting to `"unchanged"` degrades to today's behaviour
rather than to a stop.

The `False` default on `next_action` reproduces today's behaviour for every manifest with
no outro — including `build_reel`'s own CLI, which reads an `EPISODES.json` directly.

### 5.2 Why escalating is actionable, not a dead end

The closing episode is the one the fit moved, and `edit_plan._apply_outro` already
computes how far it can grow (`grow_max`, from `clip.room_after`). The escalation targets
`pacing`, which is the stage that can see that room. An over-length reel already escalates
the same way, for the same reason: the picture's length is not the reel loop's to invent.

### 5.3 What this does not do

It does not re-derive a length. `build_reel` holds locked clips; it cannot lengthen the
picture. The choice this slice makes is between shipping a silently-moved ending and
stopping with a finding — and stopping is what the rest of the length ladder already does.

---

## 6. The residual gets a number

`check_reel.run` gains an `outro: dict | None = None` parameter — the same shape
`ReelManifest.outro` carries, threaded by `build_reel` beside the `platform` it already
passes. `run` already probes the master's duration (`total`) for the length gate, so when
an outro is declared it emits an **advisory** check for free:

```python
residual = total - outro["reel_dur"]
checks["outro"] = CheckResult("outro", abs(residual) <= _LENGTH_TOL, {
    "line": outro["line"], "fade": outro["fade"], "rung": outro["rung"],
    "asked": outro["reel_dur"], "delivered": round(total, 3),
    "residual": round(residual, 3), "advisory": True})
```

`"outro"` joins `_ADVISORY_CHECKS`, so it is measured and reported but never blocks —
the `beat` check's pattern exactly. Cost: zero extra I/O; `total` is already in hand.

This closes the P3 row *"measure the delivered fade's real distance from
`EDL.outro.line`"* (music-outro-fit §11.9). That row exists because the design's central
claim is `reel_dur = line + fade` while `mix` is handed the master's *probed* length, so
the fade starts a fraction of a frame off the line and nothing measured the residual. Note
the fraction-of-a-frame framing was optimistic: `check_reel._LENGTH_TOL` is **0.5s**, so
the length gate itself passes a master half a second off the chosen length without a word.
The advisory check is what puts a number on that band.

**Advisory, not a gate.** The residual that matters perceptually is unknown — nobody has
measured how far a fade may start from a bar line before the ending stops resolving, and
inventing that threshold here would be inventing `TAIL_MIN` a second time (music-outro-fit
§11.1). The `passed` flag therefore keys on the same `_LENGTH_TOL` the length gate already
uses, which is a *reporting* boundary rather than a new claim, and §5's refusal is where
the actual teeth live.

---

## 7. Testing

- **The fixed-point proof.** Real drivers, real `fit_spine`, five steps:
  `edit_plan build` → `pacing` → `edit_plan build --pacing --music` (call this EDL **A**)
  → `pacing` again → `edit_plan build --pacing --music` (EDL **B**). **A** and **B** must
  be byte-identical apart from the provenance block, which digests the rest and so is
  identical too when they are. This is the claim of §3.1 and it must be proven end-to-end,
  not unit-asserted. Today step 4 or 5 raises, so the proof cannot even be written against
  the current code.
- **The one-beat drift, as a regression pin.** §1.2's case, asserting that a re-fit against
  a second window now reproduces the scenario's own answer (beats 11/17/28), where today it
  produces 10/16/27.
- **The deadlock, as a regression pin.** §1.1's fixture must bind instead of raising.
- **The absent arm.** An `EDL.json` with no `base_dur` behaves exactly as today — same
  spine, same bind. Two further pins the final review's correction added (§2.2): the
  refusal that the pre-slice population actually reaches carries the escape detour, and
  `build_pacing` emits its named warning when it reads a `base_dur`-less EDL.
- **The digest ladder.** Three cases: equal → bound; different → refuse; missing on either
  side → not-checked plus the tempo fallback, including the case where the tempo fallback
  then refuses.
- **The absorb.** A real-ffmpeg reel whose master is short by more than `_LENGTH_TOL` and
  less than `length_retime_max`: with `outro` absent it delivers (today's behaviour, a
  control that must not move); with `outro` present it stops-and-reports.
- **The advisory check.** Its `residual` matches the master's probed length minus
  `EDL.outro.reel_dur`, and a failing residual leaves `report.overall` true.
- **A mutation battery** over every guard added here. Each mutation must be watched going
  red; a green row is a coverage hole, not a pass.

---

## 8. Out of scope

- **Fitting a ramped closing episode** (music-outro-fit §5/§12) — still skipped, still its
  own P3 row. `base_dur` makes the *arithmetic* available (`base_play_dur()` inverts the
  ramp extra the same way `_bind_pacing` does), but the outro fit's grow/shrink search is
  what needs the inversion, and that is a different function.
- **Enforcing `SPEC.length_s`** — its own P3 row, unblocked but not claimed here.
- **A check that hears the delivered audio** — §6 measures the master's *length*, which is
  where the fade starts by construction. Nothing in this project listens to a reel.
- **Whole-spine re-fit across in-point candidates** (music-outro-fit §10) — this slice
  makes re-fitting *safe to repeat*, which is a precondition for that search, not the
  search.

---

## 9. Honest limits

- **`base_dur` absent means no fix.** An `EDL.json` written before this slice deadlocks
  exactly as it does today. The refusal message names the arm, so the failure is legible,
  but the artifact still needs the detour. There is no migration and no refusal — a
  refusal would close the hand-authored front door.
- **The digest binds the analysis window, not musical identity.** The same song re-encoded
  at a different bitrate reads as a different track and refuses. That is the safe direction
  of error, and the remedy (re-run pacing) is one command — but it is a false refusal, not
  a true one.
- **The digest's weakest rung is silent about `start_offset`.** When the audio file cannot
  be read, the ladder falls back to tempo, which cannot see a window change at all (§4.1).
  The fallback is named in the log; it is still weaker than what it replaces.
- **The advisory `outro` residual proves the master's length, never that the music
  resolved.** It cannot distinguish "the fade starts 0.4s early" from "the ending sounds
  wrong" — nothing here has an opinion about the second. The same hole music-outro-fit
  §11.5 records, now with a number beside it.
- **§5's escalation is only actionable if the closing shot has room.** `grow_max` is
  computed in `edit_plan` and is not visible at the reel level, so the finding points at
  the stage that can see it rather than carrying the number. A reel whose closing shot has
  no room left will bounce between the two stages until a human changes the cut.
- **§5's absorb refusal is proven at unit scope only.** §7 asks for a real-ffmpeg proof:
  a reel whose master is short by more than `_LENGTH_TOL` and less than
  `length_retime_max` — with `outro` absent it delivers (a control that must not move);
  with `outro` present it stops-and-reports. The branch proved both cases only against a
  monkeypatched `check_reel.run` in `tests/lib/test_build_reel.py`; no file under
  `tests/integration/` exercises this absorb through real ffmpeg. Building that
  integration test is its own slice (final-review Finding 6).
- **The measured drift is one synthetic case, not a survey.** §1.2 is a real
  `pacing.fit_spine` run over hand-picked durations and two tempos. It proves the defect
  exists and that the fix removes it; it does not say how often the workflow hits it on
  real material.
- **The hand-authored `edl_to_reel` front door is untouched.** No `base_dur`, no outro, no
  digest, no new check. The same "no silent bypass, not no bypass" boundary the rest of the
  pipeline carries.

---

## 10. Deferred → backlog rows

Per [the deferral rule](../development-workflow.md#closing-a-slice--the-deferral-rule),
every item in §8 and §9 that is not already queued gets a row:

- **A migration for `EDL.json` files without `base_dur`** (§9) — today they keep the
  deadlock. A one-shot re-projection from `selection.json` could fill the field, or the
  detour stays the answer forever. P3, S.
- **The digest's audio-unreadable rung falls back to a check that cannot see a window
  change** (§4.1, §9) — the fallback is honest but strictly weaker; recording
  `start_offset`/`duration` on `Spine` beside the digest would let the fallback at least
  compare those. P3, S.
- **Calibrate the outro residual against perception** (§6) — the advisory's `passed` flag
  keys on `_LENGTH_TOL`, a reporting boundary borrowed from another check, not a measured
  answer to "how far off the line stops resolving". Same class as `TAIL_MIN`. P3, S.

No new row for fitting a ramped closing episode, `SPEC.length_s` enforcement, an
audio-hearing check, or the whole-spine re-fit: all four already exist.

---

## 11. Files

- `scripts/lib/edl.py` — `EDLEpisode.base_dur`, `base_play_dur()`, `to_dict`/`from_dict`.
- `scripts/lib/pacing.py` — `Spine.music_digest`, its round trip and validation.
- `scripts/lib/models.py` — `ReelManifest.outro`, `_ADVISORY_CHECKS` gains `"outro"`.
- `scripts/lib/reel_orchestration.py` — `next_action(..., outro_fixed=)`.
- `scripts/pacing.py` — `build_pacing` fits `base_play_dur()`, `_bounds` on `base_dur`,
  the digest is computed and written.
- `scripts/edit_plan.py` — `window_to_episode` sets `base_dur`; `_bind_pacing` guards
  against `base_play_dur()`; `build_edl` runs the digest ladder.
- `scripts/edl_to_reel.py` — carries `EDL.outro` onto the `ReelManifest`.
- `scripts/build_reel.py` — derives `outro_fixed`, passes the outro to `check_reel`.
- `scripts/check_reel.py` — the advisory `outro` check.
- `skills/pacing/SKILL.md`, `skills/edit-plan/SKILL.md`, `skills/reel-review/SKILL.md` —
  the rebuild-without-`--pacing` detour is deleted.
