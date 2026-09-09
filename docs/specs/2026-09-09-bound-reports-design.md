# Bound reports — an artifact that says what it read

**Rows:** R5.2 (extend digest binding to every report), R5.3 (a killed `deliver`
leaves no marker), R10.9 (a stale evidence packet was dispatched to three judges).

**Thesis.** Four artifacts state a conclusion and record nothing about what they
concluded *from*. A reader — human or machine — cannot tell a current report from
one describing a file that has since moved. The binding that would fix this is not
a new idea in this codebase: it exists five times, and it held every time. What is
missing is coverage at three named spots, plus one write that is not atomic.

---

## §0 The measurements

Every number below is read off the 2026-06 run at
`/Users/serg/Downloads/untitled folder/` (read-only; nothing was written there).

### §0.1 `MATCH.md` claims 8/8; the shipped EDL carries 5

`MATCH.md` (written `Aug 24 20:57`) says, verbatim:

> 8/8 episodes authored a tone pair.

`EDL.json` (written `Aug 24 22:00`, an hour later) carries a tone pair on **five**
of eight episodes. Episodes 0, 2 and 7 carry `tone_src: null` / `tone_dst: null`.

The three empty ones are not legitimate `within-eps` skips: `MATCH.md`'s own table
gives them a max Δ of **10, 6 and 49** against an `eps` of 4, and records
`author · authored` for each. The sources agree row-for-row with the EDL's episode
order (`…0485`, `…0522`, `…0053`), so the report and the EDL describe the same cut.
Something rewrote the EDL after the conductor and dropped three pairs — which is
exactly what the `match-grade` skill warns about ("a pacing re-run wipes authored
tone"). Nothing anywhere noticed.

### §0.2 `REVIEW.json` names a path, and the file it named is gone

`REVIEW.json` (`Aug 23 10:55`) records:

```json
{"reel": "…/out/REEL_v1.mp4", "verdict": "approve", "findings": [7 findings]}
```

`out/REEL_v1.mp4` on disk is dated `Aug 24 20:23` — **a day and a half after** the
review that approved it. `VERSIONS.md` logs v1 as delivered `2026-08-24`. Both
surviving reels are 34.918 s; the retro records the reviewed reel at 37.1 s. The
file the reviewer judged does not exist any more, and `REVIEW.json` has no way to
say so: `Review.reel` is a path, and a path is not an identity.

### §0.3 The QC packet is the unbound half of a bound stage

`episode_qc build` computes `EpisodeVerdict.clip_digest` from the file on disk,
never from the judge's claim, and the gate refuses a verdict whose digest no longer
matches. That binding held all week.

`episode_qc pack` — the other half of the same stage — writes `evidence.json` with
the frame strip, the naturalness stats and the source reading, and records **no
digest of the clip it packed from**. So a re-render between `pack` and the judge
leaves the judge reading one set of pixels while its verdict is stamped against
another. The run hit this: a stale packet went to three judges and only a judge's
own blocking verdict caught it.

### §0.4 `deliver` hands ffmpeg the delivered name

`scripts/deliver.py` computes `out = out_dir / f"REEL_v{n}.{container}"` and passes
that path straight to ffmpeg. The version log entry and the attestation are both
written afterwards. A process killed mid-encode therefore leaves a **truncated file
under the delivered name**, with:

- no `VERSIONS.md` entry,
- no `REEL_v{n}.attest.json`,
- a permanently consumed version number (`_next_version`'s glob floor sees the
  truncated file and bumps past it),
- and a `montage status` line reading `unattested`, whose detail says *"this file
  was not produced by deliver()"* — which is false here, and already known to be
  false for the look-gate-withheld case.

### §0.5 The idiom exists five times; its generic half has no reader

Binding is not new work in this tree:

| binding | producer | consumer | shape |
|---|---|---|---|
| `ReelReport.master_digest` | `check_reel.py:502` | `deliver` refuses | digest |
| `EpisodeVerdict.clip_digest` | `episode_qc.build_qc` | `episode_qc.gate` refuses | digest |
| `Attestation.reel_digest` | `deliver` | `montage verify --rehash` | digest |
| `Spine.music_digest` | `pacing` | `build_edl`'s identity ladder | digest of a window |
| `ReelGeometry.provenance.cuts` | `edl_to_reel` phase 1a | `--from-geometry` refuses | structural |

Against that, the *generic* facility is dead. `provenance.stamp(inputs=...)` is
written at exactly one site (`scripts/lib/edl.py:530`, `EDL.json` recording its
`selection.json`) and read in production at **none** — a grep for `"inputs"` over
`scripts/` finds only the writer; every reader is a test. `provenance.check()`
verifies an artifact's *self*-digest and never looks at `inputs`.

Of the run's 13 JSON artifacts, three carry a provenance block at all
(`project.json`, `EDL.json`, `out/EPISODES.json`) and one of those three records
an input.

### §0.6 Two of R5's four bullets are already closed

The retro's R5 lists four failures. Two of them — *"three different reels were
delivered as `REEL_v1.mp4`"* and *"`VERSIONS.md` lives inside that same wiped
directory"* — were closed by run-layout-lifetimes (0.3.0, 2026-08-26):
`_next_version` reads the log as its source with the file glob only as a floor, and
the deliveries bucket is separate from `build` with a structural wipe predicate.
The live remainder of R5 is §0.1 and §0.2, both of which are here.

R5.2's own wording — *"`episode_qc` … is the one binding that held all week.
Nothing else has one"* — was true when written and is now wrong by four (§0.5).
This slice reports the idiom into three more places; it does not invent it.

---

## §1 The shape: bind to what the report asserts

The obvious instrument — record the digest of the file you read — is wrong for one
of the three cases, and this codebase already knows it. `ReelGeometry` does not
digest the EDL it names; it records `cuts`, a per-episode `{source, start, dur,
ramp}`, because `match_grade` **legitimately rewrites that EDL** between the two
halves of phase 1 and a whole-file digest would fire on the sanctioned rewrite as
loudly as on an unsanctioned one. A gate that cries wolf gets its ceiling raised —
that is R2.4's mechanism, measured on this project's own `color_delta_max`
(12 → 44 → 56).

So the rule is: **bind to what the report asserts, not to the file it read.**
Applied to the three:

| report | asserts | mutable? | binding |
|---|---|---|---|
| `REVIEW.json` | a verdict about a reel's pixels | no — a delivered reel is immutable | digest of the reel |
| QC `evidence.json` | "these are the pixels" | no — immutable per render | digest of the clip |
| `MATCH.md` | "these episodes carry these pairs" | **yes** — the EDL is rewritten by design | the pairs themselves |

Two consequences follow. Where the asserted thing is immutable, a digest is exact
and cheap to check. Where it is not, the check must compare the *claim* against the
current file, which means the claim has to be machine-readable — hence §2.

---

## §2 `MATCH.json` — the twin the stage never got

`MATCH.md` and `SHEETS.md` are the only two run artifacts that are markdown with no
JSON twin; every other stage writes `X.json` + `X.md` (EDL, PACING, REVIEW,
EPISODE_QC, FOOTAGE, SPEC, TITLES, MUSIC_SHORTLIST). `match-grade` is a **required**
stage whose `montage status` row keys on the markdown.

`match_grade.write_match` gains a `MATCH.json` beside `MATCH.md`, carrying what it
already computes and currently throws away:

```json
{
  "target": [76.0, 108.0, 176.0],
  "eps": 4.0,
  "bias": [20.0, 0.0, -18.0],
  "bias_source": "the nostalgic preset",
  "bias_scale": 1.0,
  "mood": "nostalgic",
  "edl": "<the EDL path this was written back into>",
  "decisions": [
    {"index": 0, "action": "author", "reason": "authored",
     "measured": [71.0, 102.0, 166.0],
     "tone_src": [20.0, 137.4, 255.0], "tone_dst": [20.0, 146.0, 255.0]}
  ]
}
```

(one object per episode; the run's eight are elided above.)

`ToneDecision` is already exactly this record — index, action, reason, measured,
tone_src, tone_dst — so the twin is a serialization, not a new contract. `MATCH.md`
becomes its rendered view: `_report_md` keeps its current signature and its output
byte-for-byte, so the report a human reads does not change. There is no golden on
`MATCH.md` today — the claim is about not moving what a reader already relies on,
not about a fixture.

**The freshness check** (`matchgrade.tone_drift(decisions, pairs)`, pure — `pairs`
is the caller's own read of the EDL's tone fields today, not the EDL object itself,
so the function keeps no IO and montage's inspector need not import the EDL
contract): for every decision with `action == "author"`, is that episode's
`tone_src`/`tone_dst` in the EDL *today* equal to what the decision recorded? A
legitimate rewrite that does not touch tone changes nothing. A `--pacing` re-run
that wipes tone is caught on the first wiped episode. The check needs no digest and
no timestamp.

The `V1_STAGES` row for `match-grade` moves from `MATCH.md` to `MATCH.json`,
matching every other stage.

## §3 `Review.reel_digest`

`Review` gains one field, stamped by `reel_review.build_review` from the file on
disk — never from the reviewer's claim, which is `episode_qc`'s idiom verbatim and
for the same reason.

```python
reel_digest: str = ""   # sha256 of the reviewed file, stamped from disk by build_review
```

It is defaulted, not required: an existing `REVIEW.json` from before this slice
loads and reads as *unbound*, which is a true statement about it, rather than
failing to load. The hand-authored front door this project keeps open stays open.

**Two readers, at two costs**, mirroring the split `montage` already declares for
deliveries ("status answers *is there a record*; verify answers *is this file the
one the record describes*"):

- `montage status` — free. Does `Review.reel`'s filename name the newest delivered
  `REEL_v{n}`? A review of v1 while v2 exists is stale. No hashing.
- `montage verify` — re-hashes the named reel against `reel_digest`, alongside the
  delivery re-hash it already does.

A `Review.reel` naming an older or now-superseded version reads as stale, and the
reason names both what the review judged and what is newest — because the
comparison is `Path(judged).name` against the newest delivery's name, not the full
path or its location. That leaves a hand-pointed path outside the deliveries bucket
unclosed when it happens to share the newest delivery's filename: nothing here
checks that the reviewed file actually lives in the bucket, only that its name
matches (backlog, whole-branch review M-2).

The cheap check is what catches the run's actual failure (two versions stale). It
is blind to a file replaced in place under the same name — which 0.3.0 made
impossible through the pipeline, and which `verify` proves anyway.

## §4 The QC evidence packet — a gate, not a report

`episode_qc.pack` records `clip_digest` in each episode's `evidence.json`, computed
from the clip it just decoded.

`episode_qc.build_qc` already computes `provenance.digest_file(ep.clip)` for the
verdict. It reads the packet's recorded digest and refuses on a mismatch, collected
into the same one-pass complaint list every other packet failure uses (the shape
Task 4 of the previous slice established), with an addressed remedy: **re-pack, then
re-judge** — never "ignore it".

This one is a gate and the other two are reports, and the difference is not
severity, it is what the artifact does. A stale MATCH.md misleads a human who can
open the EDL. A stale evidence packet makes a judge's verdict claim to bind pixels
it never saw — the binding asserts something false, which is worse than an absent
binding.

## §5 `deliver` — an atomic rename, and the partial as the marker

ffmpeg writes to `<out_dir>/.REEL_v{n}.part.{container}`; on success
`os.replace()` moves it onto `REEL_v{n}.{container}`.

Three details are load-bearing:

1. **Same directory**, so the rename is a same-filesystem operation and therefore
   atomic. `scratch_dir` cannot be used: a caller may point it at another mount.
2. **A leading dot**, which takes the partial out of all three existing globs —
   `_next_version`'s `REEL_v*.{container}`, `montage._deliveries`' `REEL_v*`, and
   `Stage("deliver", "REEL_v*.*")`. Verified: `Path.glob` does not match a leading
   dot against a pattern beginning with `REEL_v`, and `_next_version`'s
   `re.match(r"REEL_v(\d+)\.mp4$")` fails on the first character.
3. **The container extension last**, because ffmpeg infers its muxer from the
   output filename. `.REEL_v3.part` would fail to guess a muxer; `.REEL_v3.part.mp4`
   resolves normally.

The consequences answer both halves of R5.3 with no new state. A killed encode
consumes no version, is not visible as a delivery, and does not make
`deliver: done`; and the leftover `.part` file **is** the record that a delivery was
interrupted — `montage status` reports it. `-y` stays, so a retry overwrites a
leftover partial rather than accumulating them.

The look gate stays **after** the rename. Its contract is about a complete delivered
file, and its deliberate behaviour on failure (the file stays on disk, only the
attestation is withheld, no waiver) is pinned by tests and is not changed here.

## §6 `montage status` — the fifth state

`next_action`'s per-stage state is existence and nothing else: `_exists` globs, and
`done` means a file matched. That is why the router reads `reel-review: done` for a
REVIEW.json that judged a reel two versions ago.

A fifth state joins `done`/`next`/`pending`/`optional`/`skip`:

```
stale — the artifact exists, but what it asserts no longer describes what is on disk
```

Two stages can be stale: `match-grade` (§2) and `reel-review` (§3). A required
stage that is `stale` is not `done`, so `next` points at it again — that is
sufficient teeth, and no separate refusal is added. Every stale row carries a
`stale_reason` string naming what moved, because a state with no reason is the
`no-episode-bound` collapse this project has already filed once.

Both checks must stay cheap: `status` is called constantly by the router. §2 reads
two small JSON files; §3 compares filenames. Neither hashes.

Riding along, because §5 makes it more wrong rather than less:
`provenance.verify_delivery`'s detail for an unattested file currently reads *"this
file was not produced by deliver()"*. That is already false for a look-gate-withheld
reel (deliver ran and wrote the file), and after §5 it is false for a delivery
interrupted after the rename too. It is corrected to name all three possibilities
rather than assert the one that is least often true.

---

## §7 The honest half

**A window remains, and it is not closed here.** §5 makes the *encode* atomic. A
process killed between the rename and the attestation — during the look gate's six
frame decodes, the version-log append, or the sha256 of a 100 MB file — leaves a
complete, unattested reel that is indistinguishable from a look-gate-withheld one.
Both read as `unattested`, with a detail that (after §6) says so honestly instead of
guessing. Closing it properly needs a marker with a lifetime, which introduces a
stale-marker state of its own; not worth it for a window of seconds when the
window it replaces was minutes.

**The cheap freshness checks are cheap on purpose, and are therefore weaker than
the digests beside them.** §3's status check compares version names, not bytes. It
answers the failure that actually happened and is blind to a file swapped in place;
`verify` is where bytes are proven, and it is already the CP3 command.

**Nothing proves a human read `stale`.** This is the same limit the contact-sheet
stage and the episode-QC gate both record: the stage can refuse to call itself done,
and cannot make anyone look. `next` pointing back at a stale stage is the strongest
mechanical statement available.

**`stamp(inputs=)` stays dead.** Three bindings are placed at the point of
assertion, which is where §1 argues they belong; the generic input-digest block is
not given a reader by this slice, and the eight unstamped artifacts stay unstamped.
Both are filed below rather than quietly left out.

**§0.1 diagnoses a symptom, not a cause.** This slice makes the contradiction
*visible*; it does not establish what rewrote that EDL and dropped three pairs, and
it does not stop a future `edit_plan build` from doing it again. The remedy a stale
`match-grade` row prints is "re-run the conductor", which is correct and is not the
same as preventing the wipe.

---

## §8 What this does not touch

No pixel, filter chain or encode setting changes. `extract` / `reframe` /
`check_episode` / `check_reel` contracts are untouched. `_report_md`'s output is
byte-identical, so no golden moves. `Review.reel_digest` and the EDL are read, never
rewritten, by any check added here.

### Deferred

| | Item | Size | Why not here |
|---|------|------|--------------|
| ○ | Give `provenance.stamp(inputs=)` a reader, or delete it. Written once, read in production never (§0.5). Either wire it into a freshness report for the eight unstamped artifacts, or drop the field so the block stops implying a check that does not exist. | S | §1 places bindings at the point of assertion; a generic input-digest reader is a different instrument and would want the eight stamps first (existing P3 row "stamp the other six run artifacts"). |
| ○ | Find what rewrote the run's EDL and dropped three authored tone pairs an hour after the conductor. §0.1 measures the contradiction; the cause is unestablished, and the `match-grade`-wipes-on-`--pacing` warning in the skill is a hypothesis, not a finding. | S | Needs the run's tool transcript, which was deleted before the retro. Reproducing it means re-running the two stages in sequence on a fixture. |
| ○ | A marker with a lifetime for the post-rename delivery window (§7). | S | Buys seconds of coverage and introduces a stale-marker state; the window it would cover is orders of magnitude smaller than the one §5 closes. |
| ○ | `SHEETS.md` is the second markdown-only artifact (§2) and its stage is required too. Nothing here asserts anything checkable about another file, so it has no binding to gain — but it also has no machine-readable form for any future reader. | S | No measured failure. Filed so the census in §2 is not re-derived. |
| ○ | Extend the staleness reader to the optional stages (`pacing` against `MUSIC.json`, `titles` against the delivered reel). `Spine.music_digest` already makes the first one answerable. | M | Both are optional stages that never blocked the run; no measured failure yet. |

