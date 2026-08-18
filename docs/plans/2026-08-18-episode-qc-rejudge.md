# Episode-QC re-judge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No reel is delivered over an episode that was re-rendered after its QC
verdict — and where that cannot be prevented, the delivery's inspector says so.

**Architecture:** One pure decision (`lib/episode_qc.reprocess_gate`) called by
`build_reel` at the top of its deliver arm; one new arm in
`provenance._episode_qc_state`; the router's "offer to re-judge" prose becomes a
routed stop with a fixed remedy. No new artifact, no new stage, no ffmpeg change.

**Tech Stack:** Python 3, pytest, the existing `scripts/lib/episode_qc.py`
contract and `scripts/build_reel.py` driver.

**Design:** [docs/specs/2026-08-18-episode-qc-rejudge-design.md](../specs/2026-08-18-episode-qc-rejudge-design.md)

---

## Global Constraints

- **Fail-loud contract.** No waiver, no flag, no threshold on the judged path
  (design §2.1). If you find yourself adding a `force=` or an env var, stop.
- **`QC_STOPS` stays three entries.** Its docstring refuses a fourth and the
  refusal is correct — `QC_REPROCESSED` is a *driver-side* reason discovered by
  bookkeeping, not a `gate()` outcome. Put it beside the tuple, not in it.
- **The `absent` path must keep delivering.** `build_reel`'s own CLI and the
  single-command `edl_to_reel` are the SP1 front door (episode-qc §10). Every task
  that touches the refusal must keep a test proving `absent` + reprocess still
  delivers.
- **Whole-object asserts** where the project already uses them (`seen[...] == {…}`).
- Scripts run as modules (`pythonpath = .`); Python is `.venv/bin/python`.
- Commit after each task. Do not amend; post-review fixes are separate commits.

---

### Task 0: `reprocess_gate` — the pure decision

**Files:**
- Modify: `scripts/lib/episode_qc.py` (beside `QC_STOPS`, and beside `gate`)
- Test: `tests/lib/test_episode_qc.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_reprocess_gate_refuses_a_judged_reel_that_re_rendered():
    reason, problems = qc.reprocess_gate("judged", [1, 3])
    assert reason == qc.QC_REPROCESSED
    assert len(problems) == 2
    assert problems[0].startswith("episode 1 was re-rendered after it was judged")
    assert "episode 3" in problems[1]


def test_reprocess_gate_passes_a_judged_reel_that_did_not():
    assert qc.reprocess_gate("judged", []) == (None, [])


def test_reprocess_gate_passes_an_unjudged_reel_whatever_it_re_rendered():
    """design §2.1: with no verdict there is nothing for a reprocess to invalidate,
    and refusing here would break the SP1 front door episode-qc §10 keeps open."""
    assert qc.reprocess_gate("absent", [0]) == (None, [])
    assert qc.reprocess_gate("unknown", [0]) == (None, [])


def test_reprocess_gate_names_the_remedy_not_just_the_problem():
    _, problems = qc.reprocess_gate("judged", [2])
    assert "episode_qc build" in problems[0]      # the fix, in the message
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_episode_qc.py -k reprocess_gate -q`
Expected: FAIL with `AttributeError: module 'scripts.lib.episode_qc' has no attribute 'reprocess_gate'`

- [ ] **Step 3: Implement**

In `scripts/lib/episode_qc.py`, directly after the `QC_STOPS` definition:

```python
# NOT a fourth QC_STOPS entry, and the tuple's own docstring above says why: those
# three are outcomes of comparing verdicts to digests inside gate(). This one is
# discovered by BOOKKEEPING — build_reel knows which clips its retry loop rewrote —
# and it is raised by a different caller at a different moment (design §2).
QC_REPROCESSED = "episode-qc-reprocessed"
```

and, after `gate`:

```python
def reprocess_gate(state: str, reprocessed) -> tuple:
    """(reason, problems) — reason is None iff this reel may be DELIVERED.

    gate() runs once, before assembly. This runs at the other end, before delivery,
    and answers the one question the retry loop can change in between: did loop-2
    re-render a clip after its verdict was stamped? The reprocess overwrites the very
    file the digest was taken from, so the verdict is about bytes that no longer
    exist (design §1.2).

    Only on `state == "judged"`. With no verdict — build_reel's own CLI, or the
    single-command edl_to_reel — there is nothing to invalidate, and refusing would
    close the SP1 front door episode-qc §10 deliberately keeps open (design §2.1).
    No waiver on the judged side: there is no flag that lets one through."""
    if state != "judged" or not reprocessed:
        return None, []
    return QC_REPROCESSED, [
        f"episode {i} was re-rendered after it was judged — its verdict describes the "
        f"previous render's bytes; re-judge it (episode_qc pack, dispatch a judge for "
        f"episode {i} only, episode_qc build) and re-run edl_to_reel --from-episodes"
        for i in sorted(reprocessed)]
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_episode_qc.py -q`
Expected: PASS, all.

- [ ] **Step 5: Mutation check — this is a step, not a suggestion**

Change `if state != "judged" or not reprocessed:` to `if not reprocessed:` and re-run.
Expected: `test_reprocess_gate_passes_an_unjudged_reel_whatever_it_re_rendered` FAILS.
Restore the line by editing it back — never `git checkout`/`git restore`/`git stash`.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/episode_qc.py tests/lib/test_episode_qc.py && git commit -m "feat(episode-qc): the gate gets a twin at the other end of the loop"
```

---

### Task 1: `build_reel` stops instead of delivering

**Files:**
- Modify: `scripts/build_reel.py` (the `action.kind == "deliver"` arm, and the import)
- Test: `tests/lib/test_build_reel.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_a_judged_reel_refuses_to_deliver_over_a_re_rendered_episode(monkeypatch, tmp_path):
    """design §2: the retry loop rewrote ep1's bytes AFTER episode_qc digested them,
    so the verdict is one render out of date and the reel must not ship."""
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]), _pass()]
    seen = _wire(monkeypatch, reports)
    rm = _rm()
    rm.provenance = {"episode_qc": {"state": "judged", "judged": {"0": "aa", "1": "bb"}}}
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "episode-qc-reprocessed"
    assert res["reprocessed"] == [1]
    assert "episode 1" in res["finding"]["problems"][0]
    assert res["report"]["checks"]["length"]["pass"] is True   # the PICTURE passed
    assert seen["deliver"] == []                               # nothing was delivered


def test_the_stop_costs_no_mix(monkeypatch, tmp_path):
    """The refusal sits at the TOP of the deliver arm, before the stem is built —
    a reel that is not going to ship must not pay for an audio pass first."""
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]), _pass()]
    _wire(monkeypatch, reports)
    mixed = []
    monkeypatch.setattr(build_reel.mix, "mix",
                        lambda *a, **k: mixed.append(a) or "stem.m4a")
    monkeypatch.setattr(build_reel.MusicSpec, "from_json",
                        classmethod(lambda cls, p: MusicSpec(
                            path="m.mp3", tempo=120.0, beats=(0.0, 0.5), duration=60.0)))
    rm = _rm()
    rm.music = "MUSIC.json"
    rm.provenance = {"episode_qc": {"state": "judged"}}
    res = build_reel.build_reel(rm, str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["finding"]["reason"] == "episode-qc-reprocessed"
    assert mixed == []                                          # no stem was built


def test_an_unjudged_reel_still_delivers_after_a_reprocess(monkeypatch, tmp_path):
    """The other side of §2.1 — build_reel's own CLI has no verdict to invalidate,
    and the SP1 front door must keep working exactly as before this slice."""
    reports = [_color_fail(1, [120.0, 120.0, 120.0], [150.0, 120.0, 120.0]), _pass()]
    _wire(monkeypatch, reports)
    res = build_reel.build_reel(_rm(), str(tmp_path / "out"), str(tmp_path / "w"))
    assert res["status"] == "delivered"
    assert res["reprocessed"] == [1]
```

`MusicSpec` is already imported in this test module's header; add nothing.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_build_reel.py -k "re_rendered or costs_no_mix or unjudged_reel_still" -q`
Expected: FAIL — the first two deliver instead of stopping.

- [ ] **Step 3: Implement**

Add to `scripts/build_reel.py`'s imports:

```python
from scripts.lib import assembly, episode_qc as qc_lib, reel_orchestration
```

At the very top of the `if action.kind == "deliver":` block, **before** the
music/audio branch:

```python
        if action.kind == "deliver":
            # design §2: the picture has converged, but loop-2 may have rewritten a
            # clip AFTER episode_qc stamped its digest — and it overwrites the very
            # file the verdict names, so that verdict is about bytes that are gone.
            # Refuse HERE, at the top of the arm: before the stem, before deliver,
            # before a version number is spent. The remedy is a re-judge of exactly
            # the named episodes, and the second pass delivers because the corrected
            # clips are already on disk where EPISODES.json points (§2.2).
            reason, problems = qc_lib.reprocess_gate(
                (rm.provenance.get("episode_qc") or {}).get("state", ""),
                sorted(reprocessed))
            if reason:
                return {"status": "stop_and_report",
                        "finding": {"reason": reason, "episode_idx": None,
                                    "problems": problems},
                        "report": report.to_dict(), "reprocessed": sorted(reprocessed)}
            if music is not None and audio is None:
                ...   # unchanged from here down
```

- [ ] **Step 4: Run to verify**

Run: `.venv/bin/python -m pytest tests/lib/test_build_reel.py -q`
Expected: PASS, all — including the two pre-existing provenance tests
(`..._threads_the_manifest_provenance_into_deliver`,
`..._does_not_clobber_an_already_judged_qc_state`), which pass a clean first report
and therefore never reprocess.

- [ ] **Step 5: Mutation checks — steps, not suggestions**

1. Move the refusal block to AFTER the `if music is not None and audio is None:`
   branch. Expected: `test_the_stop_costs_no_mix` FAILS.
2. Replace `sorted(reprocessed)` in the `reprocess_gate` call with `[]`.
   Expected: `test_a_judged_reel_refuses_to_deliver_over_a_re_rendered_episode` FAILS.

Restore by editing the lines back.

- [ ] **Step 6: Commit**

```bash
git add scripts/build_reel.py tests/lib/test_build_reel.py && git commit -m "feat(build-reel): a judged reel does not ship over a render nobody judged"
```

---

### Task 2: the backstop — a fourth `episode_qc` state

**Files:**
- Modify: `scripts/lib/provenance.py` (`_episode_qc_state`, `verify_delivery` docstring)
- Test: `tests/lib/test_provenance.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_a_judged_delivery_that_re_rendered_after_the_verdict_reads_stale(tmp_path):
    """design §3: build_reel's own CLI can hand-stamp a judged manifest and reprocess
    anyway. The record was always in the sidecar; the inspector used to drop it."""
    att = _attestation(episode_qc={"state": "judged", "judged": {"0": "aa"},
                                   "reprocessed_after": [0]})
    assert provenance._episode_qc_state(att) == "stale"


def test_a_judged_delivery_that_re_rendered_nothing_stays_judged(tmp_path):
    att = _attestation(episode_qc={"state": "judged", "judged": {"0": "aa"},
                                   "reprocessed_after": []})
    assert provenance._episode_qc_state(att) == "judged"


def test_an_unjudged_delivery_cannot_be_stale(tmp_path):
    """A reel with no verdict has no stale one — `absent` is the honest answer and
    must not be upgraded to a QC word it never earned."""
    att = _attestation(episode_qc={"state": "absent", "reprocessed_after": [0, 1]})
    assert provenance._episode_qc_state(att) == "absent"
```

Build `_attestation` with whatever constructor the surrounding module already uses
for an `Attestation` — read the file first and match it; do not invent a new helper
if one exists.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_provenance.py -k "stale or re_rendered or unjudged" -q`
Expected: FAIL — the first returns `"judged"`.

- [ ] **Step 3: Implement**

```python
def _episode_qc_state(att: "Attestation") -> str:
    """Returns judged / stale / absent / unknown — the design §10 vocabulary plus the
    2026-08-18 fourth arm, derived rather than trusted verbatim: an old sidecar
    predating this field, or one whose block holds none of the words (a producer bug
    — see build_reel's own-CLI bypass), must read as unknown, never silently as
    whichever real state looks closest.

    `stale` is judged-but-not-about-these-bytes: the delivery re-rendered an episode
    AFTER its verdict. build_reel refuses that combination outright on the router's
    two-phase path (design §2), so reaching this arm means a producer that bypassed
    it — which is exactly what a backstop is for. The word is the gate's own: a stale
    verdict describes other bytes. `absent` never becomes `stale`: a reel with no
    verdict has no stale one to report."""
    state = att.episode_qc.get("state")
    if state == "judged" and att.episode_qc.get("reprocessed_after"):
        return "stale"
    return state if state in ("judged", "absent") else "unknown"
```

Update `verify_delivery`'s docstring line listing the vocabulary to name all four.

- [ ] **Step 4: Run to verify**

Run: `.venv/bin/python -m pytest tests/lib/test_provenance.py tests/lib/test_montage.py -q`
Expected: PASS, all.

- [ ] **Step 5: Mutation check**

Drop the `state == "judged"` conjunct (leave only the `reprocessed_after` test).
Expected: `test_an_unjudged_delivery_cannot_be_stale` FAILS. Restore by editing back.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/provenance.py tests/lib/test_provenance.py && git commit -m "feat(provenance): a judged reel that re-rendered after the verdict reads stale"
```

---

### Task 3: the end-to-end proof, with a control that must not move

**Files:**
- Modify: `tests/integration/test_episode_qc.py`

`process_episode` is faked here — the real one runs YOLO, and this proof is about
the QC loop, not the tracker. The precedent is the speed-ramp slice's SP3→SP1 proof.
Everything else is real: real reframed clips, real digests, real `episode_qc
pack`/`build`, real `assemble_reel`, real assemble + check_reel + deliver.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.integration
def test_a_reprocess_after_the_verdict_stops_the_delivery_and_a_re_judge_clears_it(
        tmp_path, sample_clip, monkeypatch):
    """design §2/§2.2 end to end: a colour outlier makes loop-2 rewrite ep1's bytes
    after episode_qc digested them → the delivery is refused; re-judging exactly ep1
    → the same command delivers, with an empty reprocessed list."""
    p, rm = _episodes_json(tmp_path, sample_clip)
    episode_qc.pack(str(p), str(tmp_path / "qc"))
    _judge(tmp_path / "qc", 0)
    _judge(tmp_path / "qc", 1)
    episode_qc.build(str(p), str(tmp_path / "qc"), str(p.parent))

    # loop-2's reprocess, faked at the boundary: it rewrites ep1's clip in place,
    # exactly as the real process_episode does (its out_path IS ReelEpisode.clip).
    def fake_pe(manifest, project_dir, route_path=None, color_correct=None):
        Path(rm.episodes[1].clip).write_bytes(
            Path(rm.episodes[1].clip).read_bytes())   # same bytes, rewritten file
        return {"status": "mechanical_pass", "clip": rm.episodes[1].clip}
    monkeypatch.setattr(build_reel.process_episode, "process_episode", fake_pe)
    # one colour failure on ep1, then a clean report — the real check_reel would need
    # a real tint; the loop's ARM is what this proves, not the colour sensor.
    reports = iter([_color_fail(1), None])
    real_run = check_reel.run

    def run_once(*a, **k):
        canned = next(reports)
        return canned if canned is not None else real_run(*a, **k)
    monkeypatch.setattr(build_reel.check_reel, "run", run_once)

    res = edl_to_reel.assemble_reel(str(p), str(tmp_path / "work"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "episode-qc-reprocessed"
    assert res["reprocessed"] == [1]
    assert list(p.parent.glob("REEL_v*")) == []        # no version spent

    # the re-judge: ONLY ep1's findings are rewritten; ep0's verdict is untouched
    _judge(tmp_path / "qc", 1)
    episode_qc.build(str(p), str(tmp_path / "qc"), str(p.parent))
    monkeypatch.setattr(build_reel.check_reel, "run", real_run)
    again = edl_to_reel.assemble_reel(str(p), str(tmp_path / "work2"))
    assert again["status"] == "delivered"
    assert again["reprocessed"] == []
    att = json.loads(Path(str(provenance.attest_path(again["output"]))).read_text())
    assert att["episode_qc"]["state"] == "judged"
    assert att["episode_qc"]["reprocessed_after"] == []
```

The control that must not move is the module's existing
`test_a_clean_run_delivers_and_the_attestation_names_the_judged_bytes` — a reel with
no reprocess must deliver in one pass, unchanged. Run it in the same command and
say so in the test's docstring.

Add the imports this needs (`build_reel`, `check_reel`) and a local `_color_fail`
helper built from `ReelReport`/`ReelFailure`/`CheckResult`, mirroring
`tests/lib/test_build_reel.py`'s.

- [ ] **Step 2: Run and watch it fail**

Run: `.venv/bin/python -m pytest tests/integration/test_episode_qc.py -q`
Expected: the new test FAILS at `res["status"] == "stop_and_report"` if Tasks 0-1
were skipped; with them in place it should pass — so run it BEFORE writing them only
if you are executing out of order. Otherwise confirm it fails when you stub
`reprocess_gate` to always return `(None, [])`, then restore.

- [ ] **Step 3: Run the whole integration module**

Run: `.venv/bin/python -m pytest tests/integration/test_episode_qc.py -q`
Expected: PASS, all — the four pre-existing tests plus the new one.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_episode_qc.py && git commit -m "test(episode-qc): the stop and the re-judge, proven on real bytes"
```

---

### Task 4: the router loop and the phase-1 landmine

**Files:**
- Modify: `skills/using-montage/SKILL.md` (step 13's second-pass note, step 14)
- Modify: `skills/episode-qc/SKILL.md` (the §8 honest-limit bullet)

- [ ] **Step 1: Rewrite `using-montage` step 14's reprocessed paragraph**

Today it says the delivered result "carries a non-empty `reprocessed` list … name
those episodes at Checkpoint 3 … and offer to re-run the episode-qc skill". That
described a post-delivery courtesy. Replace it with the routed stop:

- Phase 2 can now stop with `episode-qc-reprocessed` — the picture passed every
  check and the reel was NOT delivered, because the retry loop re-rendered the named
  episodes after they were judged.
- The remedy, in order: re-run `episode_qc pack` (safe — it preserves existing
  `findings.json`), dispatch **one fresh judge for the named indices only**, run
  `episode_qc build`, then re-run `edl_to_reel --from-episodes`.
- **Do not re-run phase 1.** State the landmine plainly (design §4.1):
  `build_reel`'s compounded per-channel colour factor lives only in the clip bytes
  on disk — not on `Manifest`, not on `PathMeta`, not in `EPISODES.json` — so
  `--stop-after-episodes` re-renders from the manifest and silently discards the
  correction the retry loop just converged on.
- A delivered reel's `reprocessed` list is now always empty on this path; keep the
  CP3 sentence that names it, but as a should-never-happen.

- [ ] **Step 2: Add `stale` to CP3's `montage verify` paragraph**

The paragraph currently lists `absent` and `unknown` as the states that must be
named plainly. Add `stale`: judged, but an episode was re-rendered after its
verdict — which on this router's path means something bypassed phase 2's own
refusal, and the reel must not be called final.

- [ ] **Step 3: Correct `episode-qc` SKILL's honest-limit bullet**

The bullet "**A reprocessed episode ships judged one render out of date (design
§8).**" is now false on the two-phase path. Rewrite it: `build_reel` refuses to
deliver over a re-rendered episode on the judged path, the router re-judges exactly
those and delivers on the second pass, and the attestation still records
`reprocessed_after` — with a `stale` reading in `montage verify` for any producer
that bypasses the refusal. Keep it in the honest-limits list rather than deleting
it: the `absent` paths still ship unjudged, and that is the surviving limit.

- [ ] **Step 4: Verify no skill-convention test broke**

Run: `.venv/bin/python -m pytest tests/test_skill_convention.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/ && git commit -m "docs(skills): the re-judge is a routed stop, not a courtesy offer"
```

---

### Task 5: mutation battery, full suite, docs sync

**Files:**
- Modify: `docs/backlog.md`, `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`
- Modify: `docs/specs/2026-08-08-episode-qc-design.md` (§8 gets an as-built note)

- [ ] **Step 1: Run the battery**

Each row is a step. Apply the mutation by editing the line, run the named command,
record the result, then edit the line back. Never `git checkout`/`restore`/`stash`.

| # | Mutation | Must fail |
|---|----------|-----------|
| 1 | `reprocess_gate`: drop the `state != "judged"` conjunct | `test_reprocess_gate_passes_an_unjudged_reel_whatever_it_re_rendered` |
| 2 | `reprocess_gate`: return `QC_STOPS[1]` instead of `QC_REPROCESSED` | `test_reprocess_gate_refuses_a_judged_reel_that_re_rendered` |
| 3 | `build_reel`: move the refusal below the music/audio branch | `test_the_stop_costs_no_mix` |
| 4 | `build_reel`: pass `[]` for `reprocessed` into the gate | `test_a_judged_reel_refuses_to_deliver_over_a_re_rendered_episode` |
| 5 | `build_reel`: read `state` from a literal `"judged"` instead of `rm.provenance` | `test_an_unjudged_reel_still_delivers_after_a_reprocess` |
| 6 | `_episode_qc_state`: drop the `state == "judged"` conjunct | `test_an_unjudged_delivery_cannot_be_stale` |
| 7 | `_episode_qc_state`: return `"judged"` instead of `"stale"` | `test_a_judged_delivery_that_re_rendered_after_the_verdict_reads_stale` |
| 8 | `build_reel`: drop `"reprocessed"` from the stop dict | the integration test's `res["reprocessed"] == [1]` |

A row that does NOT discriminate is a coverage hole: write the test that closes it
before moving on, and say in the commit message which row found it.

- [ ] **Step 2: Full suite**

```bash
find . -name __pycache__ -type d -prune -exec rm -rf {} + && .venv/bin/python -m pytest -q
```

Expected: the pre-slice count plus the new tests, 2 skipped, no golden moved.

- [ ] **Step 3: Docs sync**

- `docs/backlog.md` — flip the "Close the episode-QC loop" row to `✅` for the
  re-judge half with the measurements that shaped it (§1.1's dropped record, §1.2's
  overwrite, §1.4's zero cost on the real run), and keep the P3 auto-route row open.
  The three-items-span-buckets note near the top says "The **episode-QC loop** is P2
  for the re-judge and P3 for the auto-route" — it stays accurate, do not delete it.
  File the two §8 deferrals (outer-loop bound P3, `pack --only` P4).
- `docs/build-status.md` — a Done entry naming what was measured, not just what was
  built.
- `docs/pipeline-map.md` — stage 5.14's sentence "a reprocessed episode still ships
  judged one render out of date (design §8)" is now wrong on the two-phase path.
  Correct it.
- `CLAUDE.md` — two Quick Reference rows for this design and plan, in the registry's
  existing style.
- `docs/specs/2026-08-08-episode-qc-design.md` §8 — an as-built note pointing at
  this design, saying the hole it describes is closed on the judged path and what
  survives.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "docs(episode-qc): close the re-judge half, and file what it could not do"
```

---

## Self-Review

**Spec coverage.** §2 → Tasks 0-1. §2.1 → Task 0's third test and Task 1's third.
§2.2 → Task 3's second half. §3 → Task 2. §4/§4.1 → Task 4. §7 → Tasks 0-3.
§8 → Task 5's backlog rows. §9's limits are documentation, carried in Task 4's
honest-limit rewrite.

**The weak point, named.** Task 3 fakes both `process_episode` **and** the first
`check_reel.run`. So the integration proof shows that *the loop's arms are wired* —
reprocess → stop → re-judge → deliver — not that a real colour outlier drives it
there. That is deliberate: the real reprocess needs YOLO weights and a real tint,
and `tests/integration/test_reel_retry.py` already proves separately that a real
`color_correct` moves real pixels. But the two proofs are not joined, and no test in
this repo watches a real colour failure travel all the way to this stop. Record it
in the design's honest limits rather than pretending Task 3 is stronger than it is.

**Type consistency.** `reprocess_gate(state: str, reprocessed) -> tuple` returns
`(str | None, list[str])`, the same shape as `gate`. `build_reel` passes
`sorted(reprocessed)` (a list) both to the gate and into the result dict, matching
the `"reprocessed": sorted(reprocessed)` the deliver arm already returns.
`_episode_qc_state` keeps returning a bare `str`.
