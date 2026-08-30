# The run gets its own folder, because the conveyor scans the one it writes into

**Date:** 2026-08-25
**Status:** design
**Sources:** user request ("убрать все артефакты в одну папку") ·
[using-montage](2026-07-12-using-montage-design.md) §5.1 ·
[footage-intake](2026-07-12-footage-intake-design.md) §5.2 ·
[assemble-draft](2026-07-13-assemble-draft-design.md) §5.9

---

## 0. The request was tidiness. The measurement says correctness.

The ask was to stop littering the footage folder. Measured on the 2026-06 run,
the folder holds **138 entries: 100 video files and 38 artifacts** — `EDL.json`,
`FOOTAGE.json`, `SHEETS.md`, `cast.json`, `selection.json`, `out/`, `work/`,
`qc/`, `sheets/`, `.intake_cache/` and the rest, sitting among `DJI_*.MP4`.

That is the visible half. The load-bearing half is that one of those artifacts is
a **video**, and intake discovers footage by extension over a flat listing —
[intake.py:473](../../scripts/intake.py):

```python
paths = sorted(p for p in root.iterdir() if p.suffix.lower() in _VIDEO_EXTS)
```

No exclusion of any kind. `draft.mp4` — the QA preview the conveyor itself writes
into the run dir (§5.9) — sits in that listing today.

**It escaped by timing, not by design.** `FOOTAGE.json` carries **99** clips and
is dated 2026-08-19 13:07; `draft.mp4` is dated 2026-08-20 11:31. The scan
finished before the draft existed. The folder now holds 100 videos, and a
re-scan would take all 100 — carving windows out of a montage of the user's own
cuts, scoring them, and offering them for selection. Nothing refuses it, nothing
reports it, and the trigger is the documented remedy: *shot more, re-run intake*.

So this slice is not housekeeping with a correctness footnote. It is a
silent-corruption fix whose side effect is a clean folder.

---

## 1. The architecture already supports the split

Nothing needs re-plumbing, and that was worth checking before designing
anything:

| checked | finding |
|---|---|
| driver path arguments | every one is explicit — `intake <footage_root> <out_dir>`, `--out-dir`, `--footage-root`, `--work-dir`, `--project` |
| defaults on those arguments | five exist and **none names the footage root** — three derive from another explicit path (`<run>/out` twice, `<epdir>/probe`), and two are `edl_to_reel` phase-2 markers, required in phase 1 and derived from `Path(episodes_path).parent` in phase 2 |
| `project.json` | does **not** record a footage root |
| `montage.next_action` | already takes `run_dir` and `out_dir` as separate inputs |
| `using-montage` SKILL | already says "point **every** stage's output at one **run dir**" and writes `<run>` throughout |

The one thing missing is the only thing that matters: **nowhere is it written
that `<run>` must not be the footage folder.** The agent is handed a footage path
and no rule against reusing it, so it reuses it. The 38 artifacts are that gap's
visible consequence and `draft.mp4` is its sharp edge.

This is why the slice is small. The separation exists; only its *value* is wrong.

---

## 2. The layout

```
<footage_root>/                 ← 100 clips, plus exactly ONE new entry
  DJI_*.MP4  MVI_*.MP4
  montage/                      ← the whole run
    project.json  FOOTAGE.json  SHEETS.md  SPEC.json  EDL.json  …
    .intake_cache/  cast_crops/  sheets/  work/  qc/
    out/REEL_v1.mp4
```

Chosen over a hidden `.montage/` (the delivered reel must be findable in Finder),
a sibling `<footage>-montage/` (two folders to keep together; move the footage and
the artifacts orphan), and a central `~/Movies/video-grid/<project>/` (looking at
the material would not reveal that a montage exists).

One property of this choice is load-bearing rather than cosmetic: **`<run>/..` is
the footage root**. The run knows structurally where its material is, so the
resume path needs no recorded `footage_root` field on `project.json` — a
wire-contract change this slice therefore does not make.

---

## 3. The gate

One rule: **the conveyor never writes into the folder it scans.**

Three stages can enforce it — the ones that know the footage root and write into
a directory the caller chooses:

| stage | refuses when |
|---|---|
| `intake` | `out_dir` resolves to `footage_root` |
| `draft` | the parent of `--out` resolves to `footage_root` |
| `edl_to_reel` | `out_dir` **or** `work_dir` resolves to `footage_root` |

`draft` is not symmetry for its own sake — it is the stage that actually fired.

**The third row is a review finding against this section's first version, and the
error is worth keeping.** That version listed two call sites and justified the
closure with "none of the others scans a directory, so none can produce this
collision". Wrong predicate. Scanning is not what causes the corruption — *writing
an `.mp4` where intake will later scan* is, and the scanner and the writer are
different stages by construction. Re-asked correctly — **which stages know the
footage root and write a video into a caller-chosen directory?** — `edl_to_reel`
joins immediately: `out_dir` receives every `ep{i}.mp4` and `REEL_v{n}.mp4`, and
`work_dir` receives the extracted segments and the reel master.

Both guards sit in `_build_manifest`, the private chokepoint `edl_to_reel()` and
`process_episodes()` both route through, so one placement covers phase 1's two
public entries. Phase 2 (`--from-episodes`) needs none: it derives `out_dir` from
the `EPISODES.json` path phase 1 already validated.

Every remaining driver writes to a path derived from `<run>` or to an explicit
file the caller names, and none of those files is a video. One predicate, four
call sites, one message — the shape `titles.refuse_zone_overflow` already uses.

**Refusal, not a warning.** The advisory version of this rule has been in the
router skill since §5.1 ("point every stage's output at one run dir") and it did
not prevent a single one of the 38 artifacts. A rule that has already failed as
prose does not get re-stated as prose.

Comparison is on `Path(...).resolve()` at both ends, so a symlinked or
trailing-slash or `..`-bearing spelling of the same directory cannot slip past.
The condition is **equality**, never containment: `<footage>/montage` is *inside*
the footage root and must pass, or the gate would forbid the convention it exists
to protect.

---

## 4. What this slice builds

| # | Where | What |
|---|---|---|
| 1 | `scripts/lib/runlayout.py` (new) | `RUN_DIRNAME = "montage"` and the shared refusal |
| 2 | `scripts/intake.py` | the refusal at the top of `intake()` |
| 3 | `scripts/draft.py` | the refusal at the top of `build_draft()` |
| 3b | `scripts/edl_to_reel.py` | both refusals at the top of `_build_manifest()` (review finding) |
| 4 | `skills/using-montage/SKILL.md` | `<run>` is defined as `<footage_root>/montage`, plus the resume note in §6 |
| 5 | `skills/footage-intake/SKILL.md` | binds its `<out_dir>` to the same value |
| 6 | `README.md:54`, `CLAUDE.md` | the convention, and the registry rows for this design + plan |

Two skills, not nine. `<run>` appears in nine `SKILL.md` files but only
`using-montage` **defines** it — the other eight substitute a placeholder and stay
correct for free. `footage-intake` is the exception because it writes an unbound
`<out_dir>` instead, and it is the stage the gate refuses.

Tens of lines of code; most of the diff is text.

**Not in this slice:** migrating the existing run (below), a recorded
`footage_root` on `project.json` (§2 makes it unnecessary), and any change to
what the stages write — only *where* the caller is allowed to point them.

---

## 5. The existing run is out of scope, and would not have been a `mv`

Excluded by decision, but the cost was measured first, because "just move it"
was the obvious assumption and it is wrong. Artifacts carry absolute paths to
**other artifacts**, not only to footage:

| file | absolute paths inside |
|---|---|
| `out/EPISODES.json` | 57 |
| `cast_candidates.json` | 15 |
| `cast.json` | 10 |
| `out/EPISODE_QC.json` | 8 |
| `.intake_cache/*/clip.json` | 52 each — every crop PNG |

Moving the tree would break the QC digest bindings and the delivery attestation,
which exist precisely to notice that kind of change. A migration is a path
rewrite, not a rename — its own slice, if it is ever wanted.

Leaving it costs nothing: every driver takes explicit paths, so that run stays
readable exactly where it is, which is what the two open P2 calibration rows
need.

---

## 6. Honest limits

**The gate proves the run dir is not the footage dir. It does not prove no
rendered video sits among the footage.** Copy a finished reel next to the
material by hand and intake will scan it, same as before. That case has no
machine predicate here — an `.mp4` is an `.mp4` — and it is named rather than
closed.

**A hand-driven `deliver`, `build_reel` or `mix` has nothing to compare against.**
Those three write video but take no `--footage-root`, so pointed at the footage
folder by hand they cannot refuse. Audited: they are the only such stages, and all
three are driven by `edl_to_reel`, which is guarded — while the stages that DO know
the footage root but are not guarded (`contact_sheet`, `pacing`) write only `.jpg`,
`.json` and `.md`, which intake never reads. So the three guarded sites are exact
coverage of "knows the footage root and writes a video", and this residual is the
hand-driven path outside it. **Amended 2026-08-30**: `match_grade` dropped out of
that parenthetical — grade-shipped-pixels made it read `GEOMETRY.json`'s own
per-episode `source` paths instead of taking a `--footage-root` argument, so it no
longer belongs to the "knows the footage root" set at all, guarded or not.

**One entry still appears in the footage folder.** `montage/` is the price of
keeping the run self-contained and the deliverable findable.

**A run started under the old convention stops resuming.** With `<run>` moved,
the router looking at `<footage>/montage/` sees an empty run and starts over —
re-scanning 99 4K clips. Mitigated by one line in the skill: when `project.json`
sits in the footage root itself, say so and ask, rather than silently starting
fresh. That is a prompt, not a guarantee.

**`montage` is an ordinary name.** A user folder already called `montage` beside
the footage would be adopted as the run dir. Low-consequence and not guarded.

**Nothing here makes a reel better.** It stops one way of making a worse one.
