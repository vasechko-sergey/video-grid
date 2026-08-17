# Cheap P2 chores — design

**Date:** 2026-08-17 · **Status:** design · **Size:** S (four rows)

Four P2 rows that need no real shoot to close, taken as one slice because each
is a task or two and none of them touches the render path. A fifth row was
considered and removed — §5.

## §0 Why these four together

P0 and P1 are empty. What P2 holds splits three ways: rows blocked on footage
this desk does not have (look calibration, a second track for the downbeat
detector, the identity thresholds, a clean torchreid install), two real slices
(mood → grade, the episode-QC re-judge), and these four, which are cheap and
mutually independent. Bundling them keeps four separate branches from costing
four separate review cycles.

They share nothing but their size. Each section below stands alone.

## §1 LICENSE — AGPL-3.0

The repo has no LICENSE file and `.claude-plugin/plugin.json` omits the
`license` field, which is a distribution blocker for something the project's own
CLAUDE.md describes as "built for distribution".

**The choice is constrained by a dependency, not by preference.**
`requirements.txt` pulls `ultralytics>=8.3`, which is **AGPL-3.0**, and
`scripts/intake.py` imports it on the main path — footage-intake does not run
without it. The YOLO weights themselves are **not** redistributed: `.gitignore`
carries `yolo11*.pt` and `git ls-files` finds zero tracked `.pt` files, so
`setup.sh` downloads them at install time. That removes the redistribution
question but not the linking one — a permissive licence declared over a tree
that imports AGPL code at runtime is internally inconsistent.

So: **AGPL-3.0**, matching the strongest copyleft already present. Nothing is
removed, nothing is relicensed, and the declaration says what the runtime
already is.

- `LICENSE` — the GNU AGPL-3.0 text, verbatim.
- `.claude-plugin/plugin.json` — `"license": "AGPL-3.0-only"` (the SPDX id).
  The field is real and in use: three of the installed marketplace plugins
  declare it.
- `README.md` — a short third-party note naming `ultralytics` as the AGPL
  dependency, so a reader learns *why* the licence is what it is without
  reverse-engineering it from `requirements.txt`.

**§1.1 What this does NOT claim.** It declares a licence; it is not a licence
audit. Nobody has walked the transitive dependency tree, and no lawyer has read
this. The one dependency whose licence drove the decision was checked by hand;
the rest were not.

## §2 The authoring skill enumerates every knob (#5)

**Measured before designing, and the row is smaller than it reads.**
`EDLEpisode` carries 35 fields. `skills/edit-plan/SKILL.md` already names
**30** of them. Missing: `crop_aspect`, `crop_scale`, `border_px`,
`border_color`, `color_means`. The first four are `insert`-card geometry, the
fifth is the composition colour target.

The row also asked to check for the reverse — a tool the skill *names* that
`ReframeSpec` does not have ("curves, shadows"), which would be a build-or-not
decision rather than a doc gap. `shadow_red` exists, so shadows are present.
The reverse scan is a step of the work, not an assumption of it.

**Two parts:**

1. The five missing knobs go into step 2's existing bullet list, beside the
   knobs they belong with. The prose carries the *why* and the refusals; that
   is what makes it worth 448 lines and it is not being replaced.
2. **One reference table** at the end of step 2 enumerating all 35 with a
   one-line meaning each. That is the "one place" the row asks for. The table
   is an index, not a substitute — each row points at the prose that explains
   it.

**§2.1 The table's own failure mode, machine-checked.** A 36th field added
later and forgotten from the table puts the skill right back where it started,
silently. That is exactly the class of drift `docs/backlog.md` exists to catch
and exactly the kind of convention nothing enforces. So this slice adds a test
asserting every `EDLEpisode` field name appears in `skills/edit-plan/SKILL.md`.
A new field then fails a test rather than quietly going undocumented.

**§2.2 What that test does NOT prove.** It proves a field's *name* appears in
the file. It cannot tell a real explanation from the word pasted into a table
cell, and it says nothing about whether the explanation is correct or current.
Presence, not quality — the same honest boundary the contact-sheet stage's §9
draws about its own gate.

## §3 Editorial constraints in `montage status`

A human should see which rules bind a re-cut without opening
`CONSTRAINTS.json`. `montage.next_action` already returns the stage table and
the deliveries; it gains a `constraints` key.

**Three states, all named**, because collapsing them would be the bug:

| state | shape | means |
|---|---|---|
| no file | `{"present": false, "rules": [], "error": null}` | never authored |
| authored | `{"present": true, "rules": [...], "error": null}` | these rules bind |
| broken | `{"present": true, "rules": [], "error": "<the refusal>"}` | a file exists and nothing can read it |

**§3.1 The decision that matters: a broken file must not crash the inspector,
and must not read as "no rules".** `Constraints.from_json` refuses hard — by
design, since a rule file that cannot be parsed must never be half-honoured.
But `next_action` is an inspector the router calls constantly, and letting that
refusal escape would replace the status report with a traceback for a run whose
only problem is a typo in a rule file. Worse, catching it and reporting an
empty rule list would tell the reader "nothing binds this cut" when the truth
is "nobody knows what binds this cut".

So the `ValueError` is caught and its message carried in `error`. **The
enforcement point does not move**: `write_edit_plan` still discovers the file,
still refuses, still has no waiver. Status reports; the gate gates.

**§3.2 What this does NOT do.** It surfaces the rules; it does not check them.
`status` never sees an EDL, so it cannot say whether the current cut satisfies
a rule — only which rules exist. And a *deleted* `CONSTRAINTS.json` still
passes everything everywhere, exactly as the constraints design §10 already
recorded: no silent bypass, not no bypass.

## §4 A fixture longer than `WIN_MAX`

`intake.WIN_MIN, WIN_MAX = 1.2, 4.0`, and `tests/conftest.py`'s `sample_clip`
is **3 s with no scene cut**. `carve.units_for_span` returns one whole unit for
any span inside the band, so that fixture can only ever carve **one** window —
which is why the pool-relative scoring and the window-boundary changes from the
2026-08-06 intake-motion-scoring slice shipped with **no real-bytes proof**
(that slice's own §8 says so).

**A new fixture, not a change to `sample_clip`.** 27 test files consume
`sample_clip`; changing its pixels would move goldens across the whole
integration suite for a reason unrelated to any of them. The new one is a
sibling.

`multi_window_clip` — session-scoped, ~12 s, three visually distinct segments
separated by hard cuts, each segment longer than `WIN_MAX` and carrying two
separated activity peaks. That fires **both** carve routes:

- scene cuts → several spans (`intake.carve_windows`),
- a span longer than `win_max` with interior peaks → several units per span
  (`carve.units_for_span`'s peak branch, rather than `_flat_unit`).

The proof it enables: real bytes through `intake()` yield enough windows to
clear `CLIP_POOL_MIN = 5`, so `score_pool` takes its clip-relative branch and
`score` can be asserted to behave as a percentile — the assertion the 3 s
fixture is structurally unable to support.

**§4.1 What this does NOT close.** It proves the carve and the pool scoring
*run* on real bytes and produce a sane distribution. It says nothing about
whether the scoring is *good* — that is the calibration row, still blocked on a
real shoot. Nor is the fixture real footage: it is coloured boxes, so it
exercises the code path, not the sensor's judgement.

## §5 Considered and removed: auto-placing a ramp's `at`

`docs/backlog.md` sizes "auto-place a ramp's `at` from the action anchors" as
**S**, on the reasoning that `lib/anchors` already computes the curve. Measured
while scoping this slice, that is wrong, and the row is corrected to **M**
rather than carried here.

`anchors` today feeds **nothing**: `pacing --anchors` measures the curve, prints
a table into `PACING.md`, and no code reads it. Auto-placement needs a wire
format for "you pick" (`RampSpec.at` must be a number — `"auto"` breaks the
type and its validation), a clamp into the enclosure-legal band that
`ramp.validate_window` enforces, an ffmpeg pass per ramped episode inside
`edit_plan` (which today decodes not one frame), and a re-check against the
`MIN_RAMP_FPS` judder floor. That is a slice with its own design.

The backlog row keeps its place and gains the corrected size plus the reason,
so the next reader does not re-derive it.

## §6 Testing

- **§1** — a test asserting `plugin.json` parses and its `license` is the SPDX
  id, beside the existing manifest tests.
- **§2** — the field-coverage test of §2.1.
- **§3** — `next_action` over three run dirs: no file, a valid file, a
  malformed one. The malformed case asserts the call **returns** rather than
  raises, that `error` is non-empty, and that `rules` is empty — so a future
  "just let it propagate" cannot pass.
- **§4** — the fixture builds through real ffmpeg; `intake()` over it yields
  `>= CLIP_POOL_MIN` windows and a `score` distribution inside `[0, 1]` with
  more than one distinct value.

## §7 Out of scope

Anything requiring real footage (the four calibration rows), the two M slices
(mood → grade, the episode-QC re-judge), and §5's ramp work. No render path,
no contract, no `CACHE_VERSION` bump — the new fixture is additive and no
existing golden moves.

## §8 Honest limits

The four rows close four queue entries. None of them makes a reel better.
§1 declares a licence without auditing one; §2's test proves a word is present,
never that it is true; §3 reports rules without checking them; §4 proves a code
path runs on real bytes without proving its answer is right. Each is worth
doing and none is worth mistaking for more than it is.
