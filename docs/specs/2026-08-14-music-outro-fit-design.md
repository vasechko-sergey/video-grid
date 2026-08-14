# Music outro fit — the reel ends where the phrase does

**Status:** design · 2026-08-14 · backlog **#2** (P1), the last P1 row
**Supersedes nothing.** Closes the deferral that pacing §10, length-retime §9 and
music-spine §9 each pushed forward in turn: librosa **section detection**.

---

## §0 Why

The 2026-08-03 run's music stops mid-word. Not a bug in any one stage — a hole in
the contract. Measured against that run's own artifacts:

| | |
|---|---|
| delivered reel | 34.051s (audio stream 34.044s) |
| music out-point | track 80.044s |
| where that lands | **0.956s past a bar line**, 1.216s short of the next |
| the bookend fade | fires correctly — 18.1 dB over the last ~800ms, final 200ms at −33 dBFS |
| the song at that instant | full energy: **6.1×** the mix envelope's gap threshold |

The fade is not the problem. It ducks the chop; it does not resolve the phrase.

**The root cause is structural.** `MUSIC.json` records tempo, a flat beat list and a
2 Hz energy curve — no downbeats, no bars, no sections. `mix.py` trims the music to
the master's probed length. So no stage in the pipeline is *able* to end on a
musical boundary; the out-point is wherever the picture's length happens to fall.

Two premises died during the investigation and are recorded here so nobody rebuilds
on them:

- **The triage note in [fixes-backlog #2](../fixes-backlog.md) was wrong** to assume
  `--auto-start` had placed the in-point in a vocal pause. Run `best_offset` on that
  track and it returns **0.000** for every plausible duration (25/30/33/34/42/45);
  `MUSIC.json` records 46.0. The in-point was hand-set. (The blind sensor behind
  that 0.000 is fixed separately — demucs became required on 2026-08-14, commit
  `1871c48`.)
- **Moving `start_offset` cannot fix the out-point.** It looks free — shifting the
  in-point shifts every bar line in stem time at no length cost — but the shift this
  reel needs is **2.235 beats**, and only a whole-beat shift keeps the existing cuts
  on the grid. Two beats leaves the end 0.128s off the line; a whole-*bar* shift maps
  the grid onto itself and changes nothing. The P3 row "re-pick `MUSIC.start_offset`
  at the back-edge" is therefore **measured insufficient on its own** — it can only
  work as part of re-fitting the whole spine, never as a back-edge tweak.

---

## §1 The load-bearing simplification: `mix.py` does not change

`mix` already places the bookend as `afade=t=out:st=dur-fade:d=fade`. So if the
reel's length is chosen as

```
reel_dur = line + fade
```

the fade begins **exactly on the bar line**, with no change to `mix`, `deliver`,
`check_reel` or `build_reel`. The music keeps playing through the fade region — that
is the instrumental tail the whole design is about, and it is why the ≥0.5s
vocal-free requirement is a requirement and not a nicety: the fade has to live
somewhere that is not mid-word.

Everything below therefore reduces to **one decision: what number is `reel_dur`.**

This shape was chosen over the alternative (fade *ending* on the line) because the
alternative is what ships today and is exactly what sounds chopped — it starts
ducking the phrase before the phrase resolves.

---

## §2 What the contract is missing

Two new fields on `MusicSpec`, both in **stem-relative seconds** like `beats`:

```python
bars: tuple[float, ...] = ()                        # downbeat times
vocal_spans: tuple[tuple[float, float], ...] = ()   # (start, end) with no vocal
```

Both default to `()` so an artifact written before this slice still loads; a fit
against an empty `bars` yields the `unchanged` rung (§5) rather than an exception.

demucs is a required runtime component since 2026-08-14, so on any current run both
fields are always computable.

---

## §3 Bars — measured, and not by the obvious detector

The naive detector **does not work**. Onset strength averaged over each of the four
beat phases, on the run's own track:

```
phase 0: 4.313   phase 1: 4.285   phase 2: 4.267   phase 3: 4.309
```

All four within 1%. There is no downbeat signal there at this resolution, and an
implementation that trusted it would pick a phase out of noise.

The bass band does work. Peak STFT energy below 150 Hz in a ±0.10s window around
each beat, grouped by phase:

```
phase 0: 48.01   phase 1: 54.65   phase 2: 42.03   phase 3: 79.31
```

Ratio max/min **1.887**, and the winning phase's beat is the loudest of its own bar
in **14 of 18 bars** — 78% against 25% by chance.

So: `downbeat_phase = argmax over p of mean(low_band_peak(beats[p::4]))`, and
`bars = beats[phase::4]`.

**This assumes 4/4.** A 3/4 or 6/8 track gets a wrong grid, silently. That is a
recorded limit (§11), not a hidden one — the alternative is meter detection, which
is a slice of its own and which nothing here needs.

Fewer than 8 beats → `bars = ()`, because a phase argmax over one or two samples per
group is noise, and the `unchanged` rung is the honest answer.

---

## §4 Vocal spans — and the resolution mistake this design already made

`vocals.separate_vocal_energy(track, target_hz=2.0)` downsamples the vocal stem's RMS
to a **2 Hz** envelope — bins of 0.5 seconds. The rule asks for 0.5 seconds of
silence. A 2 Hz envelope cannot resolve its own question.

This is not hypothetical: the first pass of this investigation ran real demucs at
2 Hz and reported "one usable bar line in the window, and it is at 4.71s" — i.e. no
usable ending. At the stem's own 11.6 ms frame resolution the same track has **two**,
and the useful one is exactly the ending this design ships. A coarse sensor reported
the feature as impossible.

So a new boundary function:

```python
vocals.vocal_spans(track) -> tuple[tuple[float, float], ...]
```

separates once, builds the envelope at `_SPAN_HZ = 40.0` (≈43 Hz after
`downsample`'s integer step, ≈23 ms bins), and runs the existing pure
`offset.vocal_gaps` over it. The pure decision core is unchanged and stays
unit-tested; only the resolution fed to it moves.

**One sensor, two consumers.** `choose_offset` switches to `vocal_spans` too, so the
in-point and the out-point are judged by the same measurement. Consequence, stated
rather than discovered later: **the in-point's answer moves**, because 23 ms bins
find short gaps that 0.5s bins smeared away and drop ones that binning invented.
Finer is better, and one answer beats two, but this is a deliberate behaviour change
with a golden to re-pin.

An in-process memo keyed on the track path makes the second call free — both
consumers run inside one `beats.py` process, and the separation costs 46–62s.

---

## §5 The fitter — `scripts/lib/outro.py`, pure

```python
TAIL_MIN = 0.5          # seconds of vocal-free space a boundary must leave (§11.1)
NO_GAP_FADE = 1.5       # the longer fade rung 2 falls back to (§11.2)
MIN_LAST = 1.0          # the last episode may not be shrunk below this (§11.7)

@dataclass(frozen=True)
class OutroFit:
    reel_dur: float           # the reel length this fit asks for
    line: float | None        # the bar line the music resolves on; None on "unchanged"
    fade: float               # the fade that follows the line
    tail: float               # measured vocal-free seconds after the line
    rung: str                 # "gap" | "no-gap" | "unchanged"
    moved: float              # reel_dur - the input reel_dur (signed)

def fit_outro(bars, vocal_spans, reel_dur, bar_s, fade, *,
              music_dur, grow_max, shrink_max, brief_len=None) -> OutroFit
```

**`fade` is the reel's own bookend**, `EDL.look.fade` — the same number `build_reel`
already hands `mix`, so the audio and the picture keep resolving together. A brief
with no look leaves it at `mix`'s 0.5s default. A `fade` of 0 is legal: the reel then
ends exactly on the line and the tail requirement is `TAIL_MIN` alone.

**Candidates.** A bar line `L` is a candidate for a given fade `f` when all of:

1. `abs((L + f) - reel_dur) <= bar_s` — the ±one-bar band. It scales with tempo
   instead of being a magic number of seconds; on this track it is ±2.176s.
2. `L + f <= music_dur` — the reel cannot outrun the analysed music window. `mix`
   already refuses that, and refusing here turns a late crash into a rejected
   candidate.
3. `(L + f) - reel_dur <= grow_max` — the footage can pay an extension.
   `grow_max` is `clip.room_after(last.start) - last.dur`: the room left in the
   closing shot before its next scene cut (§6).
4. `reel_dur - (L + f) <= shrink_max` — and it can pay a shortening.
   `shrink_max` is `last.play_dur() - MIN_LAST`, clamped at 0. Shrinking is **not**
   free: without this bound a one-bar step down can leave a 2.5s closing shot at 0.3s,
   which is not an ending, it is a glitch.

**A ramped closing episode is skipped, not fitted.** Once an episode carries a
`RampSpec`, `play_dur()` is a non-linear function of `dur` (speed-ramp §2), so the
caller cannot pay a move by adding `moved` to `dur` — it would need the ramp's own
arithmetic, and the two would disagree by exactly the amount the ramp stretches. The
fit reports `unchanged` and logs the reason, with the remedy: move the ramp off the
last episode. Solving it properly means inverting `ramp_extra` against a new `dur`,
which speed-ramp already does for `_bind_pacing` — reusing that here is a real option
and a deferred one (§12), not an oversight.

**The ladder.**

| rung | rule | fade used |
|---|---|---|
| `gap` | candidates whose `tail >= max(TAIL_MIN, fade)` | `fade` |
| `no-gap` | no rung-1 candidate: re-filter candidates with the longer fade, take the nearest line | `max(fade, NO_GAP_FADE)` |
| `unchanged` | still nothing in band | `fade`, `line=None`, `reel_dur` unmoved |

`tail` is the continuous vocal-free time starting **at** the line — zero if the line
itself is inside a vocal.

Rung 2 re-filters rather than reusing rung 1's candidate set, so the longer fade
cannot smuggle length past the band.

**Tie-break** is `abs(reel_dur - brief_len)` when `SPEC.length_s` is known, else
`abs(reel_dur - input reel_dur)` — the smallest move. Both directions are searched:
shortening to the previous line is as valid as extending, and usually lands closer to
the brief.

The reel is always buildable. There is no refusal rung — an awkward music tail is not
worth blocking a delivery over, and rung 3 is always reachable.

**On this run** the fitter picks rung `gap`, line 35.26s, tail 1.50s, `reel_dur`
35.76s, `moved` +1.72s. (Bar 15 is +1.22s from the current end; the fade adds its
0.5s on top.) The last clip offers **11.53s** of `room_after`, so the footage pays
it easily.

---

## §6 Where it lives — `edit_plan`, not `pacing`

The length is paid by the last episode, and whether that episode may grow is a
**footage** fact (`FootageClip.room_after`). `edit_plan` already reads the footage,
the pacing spine and the spec; `pacing` reads neither the footage nor `SPEC`. Putting
the fit in `edit_plan` keeps all three inputs in one place and leaves `pacing` about
the grid the cuts sit on.

New flag `edit_plan build --music MUSIC.json`, available exactly when `--pacing` is —
the stage order is edit-plan → music → pacing → re-run edit-plan.

**The fit is applied AFTER `_bind_pacing`, and never through a slot.** `_bind_pacing`
refuses a slot that differs from its episode by more than half a beat, and that guard
is load-bearing: it catches a spine fitted to a *different* edit, which used to
truncate a 7.3s ride into a 4.6s slot in silence. An outro extension of 2.24 beats
would trip it. So the extension is an explicit, logged adjustment to the last
episode's duration, made after binding and before `_back_edge_target`.

**Correction (Task 5b, forced by Task 6's end-to-end proof).** This section
originally claimed `_back_edge_target` "then reports the new total the ordinary
way" after the extension. That sentence was wrong, and it was wrong in a way a unit
test could not catch: Task 6's real-ffmpeg proof of this same design, run against a
spine with as many slots as episodes (`fit_spine`'s own shape, `target_dur` equal to
the pre-fit total exactly), found `edl_to_reel` refuse to deliver at all —
`stop_and_report` on the `length` check. `_back_edge_target`'s over-flow branch
clamps `target_dur` to the PRE-fit total whenever the realized footage exceeds the
spine, precisely so that footage the music cannot cover escalates at the reel gate
instead of reaching `mix`, which refuses a stem longer than its fragment. But an
outro-fit growth is never that case: `fit_outro` has already bounded its answer by
`music_dur` (condition 2 of `_candidates`, §5), so the length it returns is one the
music provably covers. The clamp cannot tell the two apart, so it discarded a length
the fitter had already proven safe. The fit's length is authoritative: `build_edl`
replaces `_back_edge_target`'s answer with `fit.reel_dur` whenever `_apply_outro`
chose a line (`fit.rung != "unchanged"`), and leaves `_back_edge_target`'s own
under-fill/over-flow answer in charge otherwise. "Ordinary way" undersold this by a
wide margin — it only held when the spine happened to carry slack past the pre-fit
total, and no `PACING.json` that `pacing.fit_spine` actually produces carries any.

**Cuts do not move.** Only the last episode's end does. `check_reel`'s beat check
measures cut times, so it stays green by construction (worst deviation on this run:
0.017s against a 0.05s tolerance).

**The length tension is reported, never resolved silently.** This reel is already
+4.04s over `SPEC.length_s` (30.0) and rung `gap` takes it to +5.76s. The log and
`EDL.md` state the move, the rung, and the distance from the brief; the human decides
whether to accept it.

---

## §7 Carriers and reporting

- `EDL.outro: OutroFit | None` — round-trips through `to_dict`/`from_json` like every
  other carrier.
- `EDL.md` gains a short **Music outro** section: rung, line, tail, the move, and the
  distance from `SPEC.length_s`.
- `edit_plan` logs one line naming the rung and the move.

Nothing downstream reads `EDL.outro`. It is provenance — the record of which rung
decided the reel's length, which is otherwise invisible in a bare duration.

---

## §8 Landmines

1. **A 2 Hz envelope cannot answer a 0.5s question.** This design's own first pass
   got it wrong. Any future gap sensor reads the stem, not `MusicSpec.energy`.
2. **Onset strength carries no downbeat signal** on this material (all four phases
   within 1%). A detector built on it picks a phase from noise and looks like it
   works.
3. **`_bind_pacing`'s half-beat guard will refuse an outro extension** routed through
   the last slot. It must not be routed there.
4. **`mix` refuses `dur > music.duration + 0.1`.** An extension that leaves the
   analysed window turns into a crash three stages later unless the fitter refuses
   the candidate (§5 condition 2).
5. **A whole-bar shift of `start_offset` is a no-op** on the out-point — it maps the
   bar grid onto itself. Anyone reaching for the in-point lever needs §0's arithmetic
   first.

---

## §9 Testing

- **Pure:** `fit_outro`'s ladder, the band at both edges, both directions, the
  music-window / `grow_max` / `shrink_max` refusals, the brief tie-break, the
  empty-`bars` path, `fade=0`. `bars` detection on a synthesized 4/4 click with a
  loud kick on one phase.
- **Real-bytes:** `vocal_spans` over a synthesized two-tone wav (the existing
  `test_offset` fixture shape) proving the spans land where the loud tone is not, at
  a resolution the 2 Hz path could not have produced.
- **End-to-end, real ffmpeg:** an EDL + a MusicSpec whose bar grid makes exactly one
  line qualify; assert the delivered reel's duration equals `line + fade`, and that
  its audio is quiet at the end and loud at `line - 0.1`.
- **Mutation battery**, minimum: flip `>=` to `>` in the tail test; delete the
  music-window condition; delete `grow_max`; delete `shrink_max`; route the extension
  through the last slot (must trip `_bind_pacing`); drop the rung-2 re-filter (must
  let a candidate past the band); return `bars = beats[0::4]` unconditionally; build
  the span envelope at 2.0 Hz instead of `_SPAN_HZ` (must lose the qualifying line —
  this is §8.1, and it is the mutation that already fooled this design once).

---

## §10 Out of scope

Meter detection beyond 4/4 · librosa section/segment boundaries (a phrase is
approximated here by a bar line, not by a detected section) · moving the in-point as
part of a whole-spine re-fit (§0 shows the back-edge version cannot work; the
two-axis version is pacing's, not this slice's) · any check on the delivered audio.

---

## §11 Honest limits

**§11.1 `TAIL_MIN = 0.5` is an assumption, not a measurement.** It came from the
project owner's ear, not from the editing literature, and nothing here validates it.
It is one named constant in one module precisely so re-tuning is a one-line change,
and a backlog row (§12) carries the check.

**§11.2 `NO_GAP_FADE = 1.5` is taste.** No measurement says a 1.5s fade disguises a
mid-vocal cut better than a 0.5s one.

**§11.3 The downbeat detector is calibrated on one track.** 14/18 bars, ratio 1.887,
one song, one genre. The 150 Hz band edge and the ±0.10s window are first cuts.

**§11.4 The threshold behind the spans is inherited.** `vocal_gaps`' 15%-of-peak
relative bar is `offset.py`'s existing choice. Measured sensitivity on this track:
0.05 → 1 usable line, 0.10/0.15/0.20/0.30 → 2. Stable across the useful range, on one
track.

**§11.5 The gate proves placement, never taste.** It proves the reel ends on a
detected bar line with a measured vocal-free tail. It does not prove the phrase
sounds resolved, that the line is a *phrase* boundary rather than merely a bar, or
that a listener hears anything different. As with the cinematic look, **no automated
check ever hears the delivered reel** — CP3 is the first place a human does.

**§11.6 The `no-gap` rung ships a known-imperfect ending** and says so in the report.
That is the design's answer to material with no vocal-free space; it is not a claim
that the result sounds good.

**§11.7 `MIN_LAST = 1.0` is a floor, not a finding.** It stops the shrink direction
turning a closing shot into a flash; a real minimum would come from how long a
viewer needs to read a shot, which nobody here has measured.

**§11.8 A fitted EDL breaks pacing's round trip** *(final review I-1, measured)*.
`scripts/pacing.py` fits its spine to `[ep.play_dur() for ep in edl.episodes]`, read
from `EDL.json`. After a fit the closing episode's `dur` is a number footage
re-projection cannot reproduce, so the round trip stops being a fixed point.
Measured on a 120 BPM fixture with the real `pacing.fit_spine` and the real
`write_edit_plan`/`build_pacing` drivers (clip `a.mp4`, windows 6.0s + 4.0s, one bar
line at 10.2s):

| pass | EDL durs | refit spine | re-apply |
|---|---|---|---|
| no fit (pre-slice) | `[6.0, 4.0]` | `[6.0, 4.0]` | binds ✓ |
| with fit | `[6.0, 4.70]` | `[6.0, 4.70]` | **raises**: `slot 1 is 4.70s against a 4.00s episode — further apart than the 0.25s snap allows` |

The refusal is in `_bind_pacing`, so dropping `--music` does not avoid it. **The
escape is verified**: rebuild the EDL *without* `--pacing` (durs return to
`[6.0, 4.0]`), re-run pacing against that (`[6.0, 4.0]`, target 10.0), then re-apply
with `--pacing --music` — the fit lands again at `[6.0, 4.70]`, target 10.70. That
sequence is now named in `_bind_pacing`'s own refusal message and in the **pacing**,
**edit-plan** and **reel-review** skills. It is a documentation fix, not a structural
one: making `pacing` read footage-projected durs (or subtract the recorded
`outro.moved`) is its own slice, queued in §12.

**§11.9 The fade lands on the line only to the master's render accuracy.** The whole
design turns on `reel_dur = line + fade`, but `mix` is handed
`check_reel._probe_dur(master)` — the length of the master that ffmpeg actually
produced, not the `target_dur` this fitter chose. Frame quantization and concat
rounding put those a fraction of a frame apart, so the fade starts a fraction of a
frame off the line. Nothing measures the residual.

**§11.10 `build_reel`'s shortfall absorb silently defeats the fit.** When the
assembled master comes out short of `target_dur` but inside
`ReelCheckSpec.length_retime_max`, `build_reel` replaces the target with the master's
real length (`spec = dataclasses.replace(spec, target_dur=action.retime)`) and
re-checks. That is right for the case it was built for — the reel *is* that long —
but it also means a reel whose length was chosen as `line + fade` can ship at a
different length entirely, with the fade no longer starting on the line. `build_reel`
logs the re-time; nothing anywhere connects it back to the outro fit, and `EDL.outro`
still records the length that was *asked* for. Queued in §12.

---

## §12 Deferred → backlog

Every row below must exist in [backlog.md](../backlog.md) before this slice is
finished — the rule that exists because four deferrals once left every list.

- **Validate `TAIL_MIN` against editing practice** (§11.1) — the number is one
  person's assumption; check it against the literature on cutting to music. P2, S.
- **Calibrate the downbeat detector on more than one track** (§11.3) — the band edge,
  the window and the phase-confidence margin. P2, S.
- **Meter beyond 4/4** (§10) — a 3/4 track silently gets a wrong bar grid. P3, M.
- **Real section detection** (§10) — a bar line approximates a phrase boundary; the
  long-deferred librosa segmentation would find the real ones. P3, M.
- **A check that hears the delivered audio** (§11.5) — the same hole the cinematic
  look has, now with a second occupant. P3, M.
- **Whole-spine re-fit across in-point candidates** (§0, §10) — the surviving half of
  the P3 "re-pick `MUSIC.start_offset`" row, now that its back-edge form is measured
  dead. P3, M.
- **Fit a ramped closing episode** (§5) — invert `ramp_extra` against the new `dur`
  the way `_bind_pacing` already does, instead of skipping. P3, S.
- **Make pacing's round trip a fixed point again** (§11.8) — `scripts/pacing.py`
  should fit against footage-projected durs (or subtract the recorded `outro.moved`)
  so a fitted EDL can be re-fitted in place instead of needing the rebuild-without-
  `--pacing` detour. P2, M.
- **Reconcile `build_reel`'s length re-time with the fit** (§11.10) — a within-band
  absorb replaces the fitted `line + fade` target with the master's real length and
  reports nothing about the outro; at minimum say so, at best re-derive. P2, S.
- **Measure the fade's real distance from the line** (§11.9) — the delivered stem's
  fade start against `EDL.outro.line`, so the central claim has a residual instead of
  an argument. P3, S.

---

## §13 Files

| File | Change |
|---|---|
| `scripts/lib/models.py` | `MusicSpec.bars`, `MusicSpec.vocal_spans` |
| `scripts/lib/vocals.py` | `vocal_spans(track)` + `_SPAN_HZ` + the in-process memo |
| `scripts/lib/outro.py` | **new** — `TAIL_MIN`, `NO_GAP_FADE`, `MIN_LAST`, `OutroFit`, `fit_outro` |
| `scripts/beats.py` | `analyze` detects `bars`; the driver fills `vocal_spans`; `choose_offset` moves onto `vocal_spans` |
| `scripts/lib/edl.py` | `EDL.outro` carrier + the `EDL.md` section |
| `scripts/edit_plan.py` | `--music`, `_apply_outro` after `_bind_pacing` |
| `skills/edit-plan/SKILL.md`, `skills/pacing/SKILL.md` | the new flag and what the rung means |
| `docs/backlog.md`, `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md` | sync |

`mix.py`, `deliver.py`, `check_reel.py`, `build_reel.py`, `edl_to_reel.py` are
**untouched** (§1).
