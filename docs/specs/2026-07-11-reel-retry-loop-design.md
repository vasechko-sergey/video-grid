# Reel Retry Loop — Design Spec (Phase A.5)

The loop that closes the reel back half: drive `assemble → check_reel →
auto-fix the culprit episode → reassemble → recheck` until the reel passes,
then `deliver` — or stop with a precise, machine-readable finding when the
fault is beyond auto-repair. **Still silent** — music (beats, loudness,
audio-mix) is Phase B; this only automates the loop over the Phase A stages.

Maps to montage design §4.1 (the escalation ladder — one level *up* from the
per-episode loop), §5.13 (reel-final-check, mechanical half), and the
`reel-back-half` design §6, which sketched this slice and is the source this
spec expands. It mirrors `process_episode.py` (§5.10): a pure decision module
(`reel_orchestration`) under a thin deterministic shell (`build_reel`).

## Goal

`ReelManifest [{episode manifest, locked clip, frozen route} …] → build_reel →
{ assemble → check_reel → next_action → reprocess culprit(s) via process_episode
→ }≤N → deliver → out/REEL_v{n}.mp4 | stop_and_report(finding)`.

The loop sits **downstream** of loop-1 (per-episode processing): episodes are
already produced, editorially gated, and 🔒 locked by `process_episode` *before*
A.5 runs. A.5 is purely the *reel* loop over those locked clips — it never
re-runs a first-time editorial pass, only a mechanical reprocess of a flagged
culprit.

## Scope decisions (from brainstorming, 2026-07-11)

1. **build_reel consumes locked clips; it does not produce them.** Input is a
   reel manifest pairing each episode's manifest with its already-locked clip
   and frozen route. Loop-1 (with its editorial / ask-before-start gate) stays a
   separate stage that runs first. A.5 stays a thin deterministic driver.
2. **Color correction is a relative gain in *delivered* space,** composed onto
   each episode's existing source→TARGET grade — not a target swap (which would
   mix source- and delivered-space means) and not a harder pull toward the fixed
   middle tone (which need not be the reel's own consensus). See §4.
3. **Only reprocess-class failures (`black`, `color_across_cuts`) auto-close.**
   `variety`→edit-plan and `length`→pacing stop-and-report a precise finding —
   their fixers are the front half, not yet built. Unchanged from `reel-back-half`
   §6's honest boundary.

## §1 — Architecture & files

Thin entry script over `lib/` logic, the established split. Five touches:

```
scripts/lib/reel_orchestration.py  NEW  pure  next_action(fail_reasons, attempts, cap) →
                                              Deliver | Reprocess[…] | Escalate(finding).
                                              The §4.1 3×-then-escalate ladder, one level up.
scripts/build_reel.py              NEW  shell  the driver: assemble → check_reel → next_action →
                                              reprocess culprits via process_episode → repeat → deliver
                                              | stop_and_report. Mirrors process_episode.py.
scripts/lib/models.py              EDIT  add ReelManifest config-spec (episodes + reel params,
                                              validates/raises) → yields the existing ReelCheckSpec.
                                              Add the small typed action results (Reprocess/Escalate).
scripts/reframe.py                 EDIT  ReframeSpec += color_correct: tuple|None; compose it onto
                                              the final mixer gains, re-clamp the product to [LO,HI].
scripts/check_reel.py              EDIT  color_across_cuts fail detail gains target (reel median RGB)
                                              + culprit_mean (culprit span's delivered mean) so the
                                              driver computes the correction with no re-probe.
scripts/process_episode.py         EDIT  new color_correct= param threaded into every ReframeSpec it
                                              builds in the retry loop (constant across attempts, like
                                              layout); already accepts a frozen route_path.
```

## §2 — Input contract: `ReelManifest`

A config-spec parallel to `Manifest` — validates on construction, raises with a
remedy on a bad episode list / missing field (hard, below the soft manifest
gate).

```json
{ "episodes": [
    {"manifest": "ep0.json", "clip": "clips/ep0.mp4", "route": "work/ep0/route.json"},
    {"manifest": "ep1.json", "clip": "clips/ep1.mp4", "route": "work/ep1/route.json"}
  ],
  "target_dur": 30.0, "variety_min": 8, "color_delta_max": 12.0,
  "cap": 3, "changelog": "reel v1" }
```

- `episodes[].manifest` — the per-episode manifest (path or inline), so a
  reprocess can rebuild that episode. `clip` — the locked output from loop-1.
  `route` — the **frozen** `route.json` from loop-1, passed to `process_episode`
  on reprocess so it skips YOLO (color/black fixes never move the track;
  reusing the route is both a large speed-up and determinism).
- `target_dur` / `variety_min` / `color_delta_max` → the existing `ReelCheckSpec`.
- `cap` (default 3) — per-episode reprocess ceiling.
- `changelog` — passed to `deliver` for the `VERSIONS.md` line.

Hand-authored (or emitted by a future front-half EDL/pacing stage). **A.5
defines the schema; it does not generate the manifest.**

## §3 — Decision core: `next_action(fail_reasons, attempts, cap)`

Pure, deterministic, unit-tested — the reel-level twin of
`orchestration.escalation`. `attempts` is a `{episode_idx: int}` count.

| `check_reel` result | class | action |
|---|---|---|
| `overall` True (no `False` check) | — | **Deliver** |
| `black`, ep `i`, `attempts[i] < cap` | reprocess | **Reprocess**(`i`, `color_correct=None`) — clean re-encode |
| `color_across_cuts`, ep `i`, `attempts[i] < cap` | reprocess | **Reprocess**(`i`, `color_correct` from §4) |
| any reprocess-class, `attempts[i] ≥ cap` | capped | **Escalate**(`edit-plan`, "same fail ×`cap` — window/EDL wrong") |
| `variety`, ep `i` | escalate | **Escalate**(`edit-plan`, "near-duplicate — different window") |
| `length` (whole-reel, no `episode_idx`), shortfall within `length_retime_max` | retime | **Retime**(target ← the reel's real length) |
| `length`, over-length or shortfall past the band | escalate | **Escalate**(`pacing`, "spine off target") |

> **Built (2026-07-18):** the `length` retime row above landed — see
> `docs/specs/2026-07-18-length-retime-design.md`. `build_reel` gained a
> `ReelCheckSpec.length_retime_max` band (default 1.0s, on top of
> `check_reel`'s own `_LENGTH_TOL = 0.5` gate): a shortfall inside the band
> re-times the target to the reel's real length and re-checks — the delivered
> report is genuinely re-checked, never patched. An over-length reel and a
> shortfall past the band still escalate exactly as this ladder always
> specified; the retime can also ride along with a `Reprocess`, adopted before
> the round's colour work.

**Escalate wins the round.** If any escalate-class or capped failure is
present, return `Escalate` immediately — do not spend reprocess rounds on a reel
that also carries an unfixable fault (fixing a color cut will not fix a length
miss). This mirrors `orchestration.escalation`'s "escalate immediately when the
failure can't be fixed in place." Otherwise, batch every reprocess-class
failure into `Reprocess[…]`. Otherwise `Deliver`.

Not-implemented checks (`beat`, `loudness`, `safe_zones`) report `passed=None`
and never contribute a failure — `ReelReport.overall` already treats a `None`
check as non-blocking, so they never enter `fail_reasons`.

## §4 — Color correction (delivered-space, absolute, bounded)

`check_reel` measures **delivered** (post-grade) pixels on the master. The
culprit span's mean `d_i` and the reel median `med` both live in that space.
`reframe`'s existing grade normalizes **source** means → the fixed
`TARGET=(105,122,137)` at strength 0.55. The correction bridges by composing a
per-channel factor onto that grade so the delivered mean moves toward `med`:

```
reframe:  gains = color.gains_for_means(spec.color_means)          # source → TARGET
          if spec.color_correct:
              gains = tuple(_clamp(g * c, color.LO, color.HI) for g, c in zip(gains, spec.color_correct))
          arg = color.mixer_arg(*gains)
```

**Absolute, compounded — not per-round-relative.** `process_episode` regrades
from source every reprocess (it does not stack), and delivered scales ≈ linearly
with the mixer factor. So the driver keeps per-episode state and *compounds* the
factor:

```
cc_i ← _clamp( cc_i * (med / d_i_observed), color.LO, color.HI )    # cc_i starts at (1,1,1)
```

The naïve alternative — recompute `med / d_current` and apply it on a fresh
source-grade — **reverts to baseline**: the ratio is measured relative to the
*corrected* clip but applied to the *uncorrected* grade, so the two cancel.
Compounding on the previous `cc_i` is self-consistent — it converges to
`med / d_i^baseline`, the correct absolute target, over rounds.

**Split of responsibility:** `next_action` is pure — it reads `target` and
`culprit_mean` off the fail detail and returns the *per-round ratio* `med / d_i`
on the `Reprocess` action. The stateful driver (`build_reel`) owns the
compounding — it multiplies that ratio onto the episode's stored `cc_i`, clamps,
and passes the resulting *absolute* factor to `process_episode`.

**Bounded & honest.** Total correction is clamped to `[LO,HI]=[0.7,1.5]` — the
same soft ceiling as the base grade. A tint the bound cannot close within `cap`
rounds caps the episode → the reprocess-class hits `attempts[i] ≥ cap` →
**Escalate** ("colour beyond in-grade repair — regrade source / different
window"). We never brute-force a grade past its honest range.

`black` reprocess carries **no new** `color_correct` — `next_action` returns
`color_correct=None` for it (a clean re-encode), and the driver computes no
fresh ratio. But the driver does **reuse** the episode's *standing* compounded
`cc_i` when it calls `process_episode` — a black fix must not revert whatever
colour correction that episode already earned, or it would flip-flop against
the colour check next round. If the black is in the source window rather than
a transient encode artifact, the re-encode (at that same standing grade) won't
clear it → 3× → escalate (the window is wrong), exactly the §4.1 rule.

## §5 — Driver: `build_reel.py`

```python
clips = [e.clip for e in rm.episodes]          # locked clips in
si = assembly.probe_stream(clips[0])           # actual delivered dims/fps — episodes are uniform by construction
dims, fps = (si.w, si.h), si.fps
attempts, cc = {}, {}                          # per-episode counts + compounded colour factor
for _ in range(rm.cap * len(rm.episodes) + 1): # defensive bound; next_action is the real terminator
    master = assembly.assemble(clips, dims, fps, master_path)
    report = check_reel.run(master, clips, rm.check_spec, report_path)
    action = reel_orchestration.next_action(report.fail_reasons, attempts, rm.cap)
    if action.kind == "deliver":
        out = deliver.deliver(master, REEL_H264, out_dir, rm.changelog, report)  # → out/REEL_v{n}.mp4 (hard gate = belt+suspenders)
        return {"status": "delivered", "output": out, "report": report.to_dict()}
    if action.kind == "escalate":
        return {"status": "stop_and_report", "finding": action.finding,
                "report": report.to_dict(), "attempts": attempts}
    for r in action.reprocess:                 # kind == "reprocess"; sequential — one process_episode saturates the box
        if r.color_correct is not None:        # per-round ratio med/d_i; compound onto stored absolute factor
            cc[r.idx] = _compound(cc.get(r.idx, (1.0, 1.0, 1.0)), r.color_correct)
        res = process_episode.process_episode(rm.episodes[r.idx].manifest, _epdir(r.idx),
                              route_path=rm.episodes[r.idx].route, color_correct=cc.get(r.idx))
        if res["status"] != "mechanical_pass":
            return {"status": "stop_and_report",
                    "finding": {"reason": "reprocess-failed", "episode_idx": r.idx}, "sub": res}
        clips[r.idx] = res["clip"]
        attempts[r.idx] = attempts.get(r.idx, 0) + 1
return {"status": "stop_and_report", "finding": {"reason": "reel-cap-exhausted"}, "attempts": attempts}
```

- **Sequential reprocess** — YOLO (skipped via frozen route) + ffmpeg already
  saturate one machine; parallelism is YAGNI here (loop-1's 3-subagent cap was
  for the *agent* layer, not this deterministic driver).
- **Return shape** mirrors `process_episode`: `{"status": "delivered", "output",
  "report"}` (the version is in the `REEL_v{n}` filename `deliver` returns) or
  `{"status": "stop_and_report", "finding", "report", "attempts"}`. A reprocess
  that itself returns `needs_input` /
  `stop_and_report` (a manifest problem surfaced mid-loop) propagates up, never
  papered over.
- **`deliver`'s hard gate is belt-and-suspenders** — `build_reel` only calls
  `deliver` on the `Deliver` action (i.e. `overall` True), so the gate that
  refuses a failed report can never actually trip here; it stays as the
  independent guarantee for any direct `deliver` caller.

## §6 — Testing

**Unit (fast, pure / mocked):**
- `reel_orchestration.next_action` — every §3 row; a two-episode batch of
  reprocess; escalate-beats-reprocess in a mixed round; capped→escalate;
  clean→deliver. The color `Reprocess` carries the `med/d_i` factor from the
  fail detail.
- `reframe` — `color_correct` composes onto the gains and re-clamps to `[LO,HI]`
  (mutation: drop the compose → gains unchanged → the test fails).
- `check_reel` — the `color_across_cuts` fail `detail` carries `target` and
  `culprit_mean`.
- `models.ReelManifest` — round-trips; raises with a remedy on an empty episode
  list, a missing `clip`/`route`, a non-positive `cap`.
- `build_reel` — mock `assemble`/`check_reel`/`process_episode`/`deliver`:
  fail→reprocess→pass→deliver; escalate→stop_and_report with `deliver` **never**
  called; a reprocess sub-failure propagates.

**Integration (real ffmpeg, `@pytest.mark.integration`, `test_reel_retry.py`):**
following the Phase A golden's precedent — it builds reel-stage clips via the
real `reframe` encoder, not the whole `process_episode`, to keep the stage
golden robust — the real-pixel proof is two focused tests, with the
reprocess-loop *logic* covered by the `build_reel` unit test above:
- **color correction moves real pixels** — `reframe` a deliberately warm-tinted
  source twice, once with `color_correct=None` and once with a reducing
  `color_correct`; assert the corrected clip's delivered channel mean drops
  toward the reference. Proves §4's composition works on real frames, not just
  in the pure-gain unit test.
- **build_reel delivers end-to-end** — two uniform `reframe`-built clips →
  `ReelManifest` → `build_reel`: they pass on the first assemble, so the driver
  runs `probe_stream → assemble → check_reel → deliver` with real files (no
  reprocess) and returns `{"status": "delivered", …}` with `REEL_v1.mp4` on
  disk. Proves the real wiring the unit test mocks.

## §7 — Landmines touched (montage §12)

- **`-ss` / `lutrgb`** — the color op is `colorchannelmixer` (already, via
  `color.py`); `lutrgb` stays banned. No new seek is introduced — reprocess
  reuses the frozen route and `reframe`'s existing (landmine-clean) seek.
- **Even output dims** — untouched: `assemble`/`deliver` add no `scale`; the
  reprocessed episode inherits the same even canvas as its first pass.
- **Never a silent pass** — a capped or unfixable reel *stops and reports*; it
  is never delivered. `beat`/`loudness`/`safe_zones` stay `passed=None`.
- **Determinism** — reprocess reuses the frozen route; the compounded
  `color_correct` is the only thing that changes between rounds, so a given
  reel manifest + tint yields a reproducible convergence path.

## §8 — Non-goals / deferred

- **`variety` / `length` auto-fix** — need the front-half EDL/pacing stages;
  A.5 stop-and-reports them with the precise `escalate_to` target. **`length`
  landed 2026-07-18** — see `docs/specs/2026-07-18-length-retime-design.md`
  (the within-band shortfall retime in the ladder table above); **`variety`
  did not** — a near-duplicate window still needs edit-plan to pick a
  different one, and stays a stop-and-report.
- **Parallel reprocess** — one machine, one `process_episode` at a time.
- **Resumability** (skip a stage when its inputs are unchanged) — the router's
  job (montage §11).
- **`beat`, `loudness`, `safe_zones` numeric checks + audio-mix** — Phase B.
- **Reel-manifest generation** — a future front-half emits it; A.5 only consumes
  it.
