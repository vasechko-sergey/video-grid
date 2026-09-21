# Unvalidated shapes — a comment is not a gate

**Date:** 2026-09-21 · **Rows:** four P2 rows, filed separately, measured together ·
**Version:** 0.12.1 (PATCH — three latent defects closed, no contract field added,
no check added or removed)

Four backlog rows were filed under one impression: *a shape nobody validates*.
Measured, three of them are one defect and the fourth is not a defect at all.

The three share a precise form. **A reader defends itself with a guarantee the
producer does not make** — and in all three the defence is written down, in a
comment, and the comment is what is wrong:

* `check_episode._grade_damage` branches on `"status" in d`, which is a claim that
  only the verdict half of a flat merge can contribute that key. Both halves can.
* `color.refuse_ungradeable_plane` reads `plane_depth(pix_fmt)` as a *measured*
  depth. `plane_depth` answers `8` for "this name carries no depth marker", and an
  absent `pix_fmt` is not a name at all.
* `check_reel._chroma_spread_check` cites `ReelEpisode.__post_init__` for the
  guarantee that a dict carrying `delta_c` also carries `delta_h`. The validator's
  early return does not promise that, and on one of the reader's two live inlets
  the validator is not present at all.

The rule this slice adds is the companion to the inert-surface doctrine
(2026-09-16 §1.4, *a field that cannot be decided is deleted, not qualified*):
**a claimed invariant either has a construction that enforces it, or it does not
exist.** Three fixes make the constructions real. The fourth row closes on its own
measurement.

---

## §0 What was measured

### §0.1 The flat merge collides on exactly two keys, and the site is the only one of its kind

`gradedamage.evaluate` returns one of three shapes — a reading
`{ratio, plain_bits, graded_bits, floor, frames, below}`, or
`{status, reason}` for "no frames to compare", or `{status, reason}` for "every
ungraded frame is flat". `_subject_delta_advisory` returns
`{advisory_delta_e, region, region_fraction, region_fallback}` plus, splatted from
`color_fidelity.evaluate`, either `{delta_e, delta_l, delta_c, delta_h, samples}`
or `{status, reason}` — and, on the subject arm only, `background_fallback`,
optionally `background_delta_e`, and `crop_delta_c`/`crop_delta_h`.

The intersection is `{status, reason}` and nothing else. `d.update(advisory)` puts
the advisory second, so an advisory absence **overwrites** — and the branch two
lines later reads the merged dict.

It is unreachable today, by accident rather than by construction. `color.sample_times`
returns `FRAMES >= 1` times, so the frame stacks are non-empty and the `whole`
all-ones mask yields at least one pair on the fallback arm; on the subject arm
`regions.refuse` has already returned `None`, which is exactly the statement that
the mask holds pixels. The tell is the asymmetry inside one function: the background
arm carries an explicit comment — *"A bare subscript, never `.get`… If that ever
stops holding, a KeyError is the right answer — a None here is the defect"* — about
precisely this hazard, and the primary read twelve lines above it carries a blind
`**` splat.

**The site is unique.** A sweep of `scripts/` finds **17** dict-merge expressions
(`.update(` or `{**`, excluding `hashlib`'s `h.update(chunk)`). Of those, **14**
merge a locally-built mapping with literal keys that win by position — deterministic
by construction. **Three** merge two independently produced mappings:
`edit_plan.py:129` (`{**defaults, **editorial}`) and `orchestration.py:194`
(`{**DEFAULT_PARAMS, **params}`), both deliberate overrides with no discriminator
downstream, and `check_episode.py:242`. **Only `check_episode.py:242` then branches
on a key either side can contribute.** `models.py:315` is the careful form of the
same operation and worth citing as the counter-example: it filters the colliding
key out of the left side before merging it back from the right.

So the fix is local. There is no pattern to sweep.

### §0.2 The depth guard is fail-open, and the file that reaches it is constructible

Of the five values `reframe._probe` derives, four either raise or carry a documented
absence word:

| value | on absence |
|---|---|
| `width`, `height` | bare subscript — `KeyError` |
| `avg_frame_rate` | bare subscript, then an explicit raise with a remedy at `fps <= 0` |
| `duration` | explicit raise with a remedy, and a comment saying why a fallback was rejected |
| `color_range` | `"unknown"` — a **documented legitimate value**: untagged is the mp4/h264 convention for limited, and `refuse_ungradeable_plane` passes it deliberately (colour-stage §8/§9) |
| `pix_fmt` | `""` — becomes the number **8** |

Reachability was established with a real file, not by inspection. Patching the
`stsd` visual sample entry's fourcc of `tests/fixtures/golden_ride.mp4` from `avc1`
to `zzzz` — a container whose codec this ffmpeg build has no decoder for — leaves
`width`, `height`, `avg_frame_rate`, `duration` and `color_range` intact, because
all five come from container boxes rather than from the codec, and **omits
`pix_fmt`**. Run through the real code path:

```
_probe  -> pix_fmt='' color_range='tv' depth=8
refuse_ungradeable_plane -> PASSED
```

On the unpatched `pc` fixture the range clause catches it for an unrelated reason;
on a `tv`-range build of the same patch (re-encoded through the segment range
contract, then patched identically) nothing refuses it at all. A stream ffprobe
could not describe is graded as an 8-bit limited plane.

The rhyme with `plane_depth`'s own docstring is the argument. That function reads
the *name* deliberately, because `bits_per_raw_sample` "reads `N/A` on the one real
10-bit clip it exists to catch". The name is absent on a different class of file —
one whose codec the build cannot open — and that class is where proprietary and
newer camera codecs live, which is where 10- and 12-bit sources live. That last
step is an inference, not a measurement; see §5.2.

### §0.3 The chroma KeyError reproduces, and the reader's cited guarantee misses an inlet

Direct reproduction:

```
ReelEpisode(chroma={'status': 'not-checked', 'reason': 'x', 'delta_c': 1.0})
  -> constructs
check_reel._chroma_spread_check([that, {'delta_c': 0.0, 'delta_h': 0.0}], 5.0)
  -> KeyError: 'delta_h'
```

`__post_init__` returns early at `status == "not-checked"` once it has seen a
non-empty `reason`, never reaching the clause that requires both numeric
components. `_chroma_spread_check` tests `"delta_c" in c` first, takes that as its
reading branch, and subscripts `c["delta_h"]` unconditionally.

The row filed this as reachable only from a hand-authored `EPISODES.json`. Measured,
the reader has **two** inlets and the validator sits on one:
`build_reel` builds `chroma = [e.chroma for e in rm.episodes]` once before the retry
loop, overwrites `chroma[item.idx] = color_fidelity.shift_from_report(...)` in the
reprocess arm, and passes that **plain list** to `check_reel.run(chroma=...)`. Those
values never pass through the dataclass. Nothing is wrong today — every branch of
`shift_from_report` returns a clean two-key reading or a clean two-key absence —
but the reader's stated reason for its bare subscript does not cover that path,
which decides the fix: the reader changes, not the validator. Tightening
`__post_init__` alone would leave an inlet it does not guard.

### §0.4 R2.8's premise does not survive its own measurement

The row reads: *"`color.grade_chain` composes pre-built fragments under a three-way
comma convention and validates none of it — it produced 1.5 KB of ffmpeg garbage
during the run."* Three claims, three results.

**Length is not evidence.** A maximal **legal** chain — every knob at a legal
extreme, a white-balance fragment and a real tone pair — is **1206 bytes across 11
filters**.

**Corrected 2026-09-21, during Task 4's review:** this design first said "23
filters", which was a miscount of the same kind it accuses R2.8 of. 23 is the
number of comma-separated TOKENS. `tone_arg` carries **12 commas inside its own
single-quoted `lutyuv=y='if(lte(...),...)'` expression** — the §12 landmine's
comma-bearing-value case — and `dip_arg` emits two `fade` filters separated by a
comma of its own. The 22 commas are therefore 10 separators plus 12 that are
inside a quoted value, and the filters are: `colorchannelmixer` (white balance),
`lutyuv`, `colorlevels`, `colorchannelmixer` (gain), `curves` x4, `eq`, and two
`fade`s. The byte counts were never wrong; the unit was. A chain shaped like the real run's (a tone pair plus the three knobs that
shipped: `saturation 0.92`, `shadow_red 0.1`, `mid_blue 1.2`) is **842**. Per
builder:

| fragment | bytes | lead | tail |
|---|---:|---|---|
| `white_balance_arg` | 45 | `c` | `,` |
| `tone_arg` | 437 | `l` | `,` |
| `black_point_arg` | 51 | `c` | `,` |
| `mixer_arg` | 44 | `c` | `0` |
| `shadow_red_arg` | 277 | `,` | `'` |
| `mid_blue_arg` | 63 | `,` | `'` |
| `saturation_arg` | 21 | `,` | `0` |
| `highlight_arg` | 36 | `,` | `'` |
| `highlight_red_arg` | 151 | `,` | `'` |
| `dip_arg` | 81 | `,` | `4` |

`tone_arg` alone is 437 bytes because it is a 32-point luma LUT expression, and
`shadow_red_arg` is 277 at `SHADOW_RED_STEP = 0.05`. A densely sampled curve is a
long string; that is what the luma-tone-transfer and shadow-red slices bought.
1.5 KB is the size of a correct chain, not of a broken one.

**The source does not corroborate.** The row cites the first-real-run retro's R2.
That section contains no mention of `grade_chain`, of 1.5 KB, or of garbage; its six
numbered mechanisms are the range mismatch, `measure_profile`'s raw-source read,
`tone_arg` on full-range material, `color_across_cuts`' whole-frame means,
`color_fidelity`'s 28-code miss, and the hand-widened ceiling. The only "1.5" in the
colour record is a **luma-code** residual, in the archived `tone_match` row ("tone
alone **1.5**"). This is the same species as legible-evidence §0.1, where
"200×406 px per frame" turned out to be a misreading of the sheet's own dimensions.

**"Validates none of it" is wrong at the knob level.** Every builder validates its
own argument and raises with a remedy: `mid_blue_arg(2.0)` refuses outside
`[0.8, 1.2]`, `dip_arg` refuses both an out-of-range dip and one whose fade-in and
fade-out would overlap in a short episode, `shadow_red_arg` refuses a return point
outside `(0, 0.45]`, and `reframe` additionally runs `verify_tone` on the tone
fragment before it reaches `grade_chain` at all.

**And the composition's failure mode is loud.** A missing comma fuses two filter
names into one unknown token; a doubled comma is an empty filter slot. Both are
ffmpeg parse errors at render time. The bar for the always-loaded landmine registry
is *silent* corruption — bad pixels, not a crash — and this does not meet it.

What does survive: `wb` and `tone` are the two slots `grade_chain` does not build
itself, and the discipline that keeps the whole expression well-formed is written
nowhere. Stated for the first time here: **every fragment before `mixer_arg` is
empty or ends with a comma; `mixer_arg` is never empty and carries no comma at
either end; every fragment after it is empty or begins with a comma and does not
end with one.** `mixer_arg` is the pivot, and the discipline rests entirely on its
being unconditional — it is an f-string with no identity branch, which is one
plausible future "the gains are 1.0, emit nothing" edit away from breaking.

### §0.5 What none of this is

No row here changes a number the pipeline reports, and no row here makes a reel
better. Three are latent defects found by whole-branch reviews, not by a run; the
fourth is a correction to the queue. This is the honest size of the slice and §5.1
says so again.

---

## §1 The rule

A reader may rely on an invariant only when one of these holds:

1. **A construction enforces it** — the producer cannot emit the other shape.
2. **A refusal enforces it** — the reader raises, loudly and with a remedy, when the
   shape is not the one it needs.

A comment asserting the invariant is neither. Where a comment is the only
enforcement, either promote it to a construction or a refusal, or the invariant is
not one.

Corollary, used three times below: **when a reader's cited guarantee comes from
another module, the citation must name every inlet the reader has.** A guarantee
that covers one of two paths is not a guarantee.

---

## §2 The contract

### §2.1 The verdict is read from the verdict's own dict, and the advisory cannot produce an absence

Two changes in `check_episode`, and both are needed for different reasons.

**The branch** moves off the merged dict:

```python
verdict = gradedamage.evaluate(plain=p_frames, graded=g_frames, floor=spec.entropy_floor)
unchecked = "status" in verdict
d = dict(verdict)
d.update(_subject_delta_advisory(p_frames, g_frames, times, route_pts, path_obj, meta))
if unchecked:
    return CheckResult("grade_damage", None, d)
return CheckResult("grade_damage", not d["below"], d)
```

**The advisory** stops being able to contribute the colliding pair at all. `read` is
either the all-ones `whole` mask or a subject mask `regions.refuse` has just
declined to refuse — both hold pixels in at least one frame — so an empty pair list
is a broken contract, not an input:

```python
pairs = _region_pairs(p, g, read)
if not pairs:
    raise ValueError(
        "check_episode: the region read came back with no sample pairs. "
        f"region={'crop' if fallback else 'subject'} over {n} frames: a crop read "
        "is the whole frame and a subject read only happens when regions.refuse "
        "declined to refuse, so both hold pixels by construction. An empty read "
        "is a contract break in regions.subject_mask or _region_pairs, not an "
        "input to describe as a not-checked advisory.")
out = {..., **color_fidelity.evaluate(pairs)}
```

This is the doctrine the background arm twelve lines below already states, applied
to the read above it — the asymmetry §0.1 names, removed.

**Neither half alone is the fix, and the design is explicit about which does what.**
The refusal is what closes the defect: with it, the merged dict cannot gain `status`
from the advisory. The branch is what makes the closure legible and keeps it closed
— it names which dict it judges, so a future advisory key cannot silently reopen the
coupling. The branch *alone* would be insufficient: `passed` would be right while
the report carried a `status: "not-checked"` describing only the advisory, beside a
live `ratio`/`below` pair — the contradiction surface this repo refuses everywhere
else.

**The report's shape does not change.** Namespacing the advisory under its own key
was considered and rejected: the flat keys are documented across two contiguous prose blocks — roughly 36 lines of
`skills/episode-qc/SKILL.md` and 42 of `skills/episode-qc/episode-reviewer.md` — read by
`color_fidelity.shift_from_report`, and carried in the QC evidence packet. The churn
buys no correctness the refusal does not already buy.

### §2.2 An undescribable plane is refused, by name, with a remedy

`color.refuse_ungradeable_plane` gains a third clause, **first**, ahead of the
`plane_depth` call it exists to protect:

```python
if not pix_fmt:
    raise ValueError(
        f"{src}: ffprobe reported no pix_fmt for this stream, so its bit depth is "
        f"unknown — and an unknown depth reads as 8 through plane_depth, which "
        f"answers 8 for a NAME carrying no depth marker (yuv420p, nv12, gray). "
        f"An absent name is not such a name. A container whose codec this ffmpeg "
        f"build cannot open still reports width, height, frame rate and duration "
        f"from its own boxes, so the other four probed values look healthy. Cut "
        f"this source through scripts.extract first: it re-encodes to 8-bit "
        f"yuv420p at the source's own resolution.")
```

Home chosen by measurement, not taste. `plane_depth` has exactly one production
caller — this guard — and one test; its documented contract (*"the ABSENCE of a
depth marker is eight bits, not an unknown"*) is **true for a pixel-format name**
and should not be weakened to accommodate a non-name. `refuse_ungradeable_plane`
already owns the two refusals with remedies and is reached from exactly one call
site, `reframe.plan_render`. `_probe` keeps returning `""`: it is a probe, not a
guard, and its one other consumer (`process_episode.py:216`) discards the value.

The clause must sit **before** `depth = plane_depth(pix_fmt)`. Placed after, it
would be reached only when `plane_depth` had already answered, which for `""` is the
wrong answer this clause exists to prevent.

### §2.3 The chroma reader keys on the same discriminator as its validator

`check_reel._chroma_spread_check`'s two dict branches swap order, so the absence —
the discriminated shape — is tested first, on `status`:

```python
if isinstance(c, dict) and c.get("status") == "not-checked":
    missing[str(i)] = c["reason"]
elif isinstance(c, dict):
    per[str(i)] = [c["delta_c"], c["delta_h"]]
else:
    missing[str(i)] = "the reel manifest is older than this field — re-run phase 1 to record it"
```

A dict carrying both a `not-checked` status and a stray numeric component now lands
where `ReelEpisode.__post_init__` already admitted it — among the absences — instead
of `KeyError`-ing in a branch that was never meant to hold it.

The bare subscripts stay, and the comment defending them is corrected to name **both**
inlets and what makes each safe: through `ReelEpisode`, `__post_init__`'s numeric
clause requires `delta_c` and `delta_h` together and its `not-checked` arm requires a
non-empty `reason`; through `build_reel`'s plain list, every branch of
`color_fidelity.shift_from_report` returns either a clean two-key reading or a clean
two-key absence. Stating the second inlet is the point — the comment as written cited
only the first, which is §0.3's finding.

The validator is deliberately **not** tightened. It would close the hand-authored
inlet and leave `build_reel`'s untouched, which is the shape of defence this slice
exists to stop shipping.

### §2.4 The comma discipline is written down and machine-checked

`grade_chain`'s docstring gains the discipline §0.4 states, named as a discipline
rather than described in passing, with `mixer_arg`'s unconditionality called out as
the pivot the whole expression rests on.

The machine check is a property over the composition, not a restatement of the
docstring: enumerate every knob at identity versus one legal non-identity value —
including `wb` and `tone` present versus absent — build `grade_chain` for all
combinations, and assert that no output contains `,,`, begins with `,`, or ends with
`,`. Pure string construction, no ffmpeg, 1024 combinations. A per-builder check of
lead/tail characters rides along, so a new builder added on the wrong side of the
pivot fails with a message that says which side it belongs on.

This is the only code R2.8 leaves behind, and the row itself closes ⊘ with §0.4's
numbers as its closure note.

---

## §3 What does not change

* **No report key is added, renamed or removed.** `grade_damage`'s block keeps its
  flat shape; `chroma_spread`'s detail keeps `per_episode`/`not_checked`/`max`/
  `advisory` and its three reading keys.
* **No contract field, no threshold, no check.** `ReelEpisode.chroma`,
  `ReelCheckSpec.chroma_spread_max`, `CheckSpec.entropy_floor` are untouched.
* **No skill body changes.** The ~78 lines of `episode-qc` prose describing the flat
  advisory keys stay correct because §2.1 keeps the shape.
* **No golden moves.** Every change is a refusal on a path no green test reaches, a
  branch reorder that agrees with the current branch on every shape the producers
  emit, or a new test.
* **`plane_depth`'s contract.** It still answers 8 for a name with no depth marker.

---

## §4 Proofs

1. **The advisory can no longer overwrite the verdict's discriminator.** Construct a
   frame stack and a mask that yields no pairs, call `_subject_delta_advisory`
   directly, assert `ValueError` naming the region and the frame count. Control: the
   ordinary subject read still returns its five `color_fidelity` keys.
2. **The verdict is read from the verdict.** With a stubbed
   `_subject_delta_advisory` returning `{"status": "x", "reason": "y"}`, a real
   below-floor `gradedamage` reading still yields `passed=False`, not `None`.
   This is the test that fails on today's build.
3. **An undescribable plane is refused.** A committed fixture built by patching the
   `stsd` fourcc of a tv-range segment; assert `plan_render` raises and that the
   message names `scripts.extract`. Control: the same file unpatched passes.
   The negative class is real bytes, not a stubbed `_probe`.
4. **`plane_depth`'s own contract is unchanged.** Its existing parametrized test
   still passes, including `plane_depth("yuv420p") == 8`, and gains no `""` row —
   the empty string is refused a layer up, not redefined here.
5. **The mixed chroma dict lands among the absences.** The §0.3 reproduction becomes
   a test: the same dict now yields `not_checked` carrying its reason, and no
   `KeyError`. Control: a clean reading still reaches `per_episode`.
6. **`build_reel`'s inlet is exercised, not assumed.** A reprocess round whose
   `shift_from_report` result reaches `check_reel.run(chroma=...)` without passing
   through `ReelEpisode` — the path §0.3 found uncovered.
7. **The comma discipline holds over the whole composition.** The 1024-combination
   enumeration of §2.4. Its own discriminating mutation: make `mixer_arg` return
   `""` at unit gains, and the enumeration must go red.

---

## §5 Honest limits

### §5.1 Nothing here fires today, and nothing here improves a reel

All three defects are latent. Two are unreachable from any sanctioned caller; the
third needs a hand-authored `EPISODES.json`. They were found by whole-branch reviews,
not by a run, and closing them changes no number any report prints. The value is
that the constructions now match the comments — which is worth a patch release and
not more.

### §5.2 Row 2's reachability is constructed, and the step to real footage is an inference

The `stsd` fourcc patch is a synthetic file. That a real proprietary or
next-generation camera codec would reach the same branch follows from the same
mechanism — width, height, frame rate and duration come from container boxes, the
pixel format comes from the codec — but no such file was measured, because none is
on this machine. The stronger claim in §0.2's last paragraph, that such codecs are
disproportionately the 10- and 12-bit sources the guard exists for, is an inference
about the camera market and is marked as one.

### §5.3 R2.8 closes without proving the run's chain was correct

§0.4 proves that 1206 bytes is a legal length and that the retro does not corroborate
the row's headline. It does **not** prove that what the run produced was a correct
chain — the artifact is gone. The claim is narrower and exact: *length is not
evidence of corruption, and the row offered no other evidence.* If a malformed chain
is ever captured, it will fail loud at ffmpeg and can be filed then, with the argv.

### §5.4 The comma enumeration proves well-formedness, not correctness

No combination producing `,,` or a dangling comma is the whole of what §2.4 checks.
It says nothing about whether the filters are in the right order, whether each one
does what its name says, or whether the composed grade is any good. The order is a
literal expression that only an edit can change; the check that an edit did not
change it is the existing `test_reframe` argv pins, not this one.

### §5.5 One inlet is documented, not gated

§2.3 corrects the comment to name `build_reel`'s plain-list inlet and what makes it
safe. Nothing *enforces* that a future third filler of `check_reel.run(chroma=...)`
goes through `shift_from_report`. Routing every inlet through the validator is the
construction that would close it; it is not built here because it would mean
constructing a throwaway `ReelEpisode` per reprocessed episode purely to validate a
two-key dict. Filed as a deferral rather than left unsaid.

---

## §6 Deferred

1. **Route `check_reel.run(chroma=...)` through one validator.** §5.5. The reader
   would stop needing a comment about its inlets at all. S.
2. **A `pix_fmt`-less source that a real camera produces.** §5.2. Would turn the
   constructed fixture into a measured one, and is the only way to test the
   inference about bit depth. S, blocked on footage.
3. **The other two two-producer merges.** `edit_plan.py:129` and
   `orchestration.py:194` are deliberate overrides today with no discriminator
   downstream (§0.1). Neither is a defect; both become one the day a key is read as
   a discriminator after the merge. Worth a note in each, not a slice. S.
