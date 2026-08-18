# Episode-QC re-judge — design (2026-08-18)

**Slice:** backlog P2, "Close the episode-QC loop" — the **re-judge half**. Closes
[episode-qc](2026-08-08-episode-qc-design.md) §8. The other half (auto-routing a
blocking finding back into a re-render) stays P3 and is untouched here.
**Size:** M.

## 0 · What the row asks

`build_reel`'s retry loop re-renders a culprit episode *after* the QC gate has run.
Both things it can change — a compounded colour correction, and (for a stabilized
episode) a re-track that moves the crop path — are exactly what axes `colour`,
`composition` and `path` were just judged on. So the episode ships **judged one
render out of date**, and episode-qc §8 chose to *record* that rather than prevent
it.

This slice prevents it.

## 1 · What is on disk today — four measurements

Every claim below was read off the code and the 2026-08-03 run before any of it was
designed. Two of them changed the shape.

### 1.1 · The record exists, and the inspector drops it

`build_reel` merges its `reprocessed` set into the delivery's attestation
([build_reel.py:116](../../scripts/build_reel.py)):

```json
"episode_qc": {"state": "judged", "judged": {"0": "9f2c…"}, "reprocessed_after": [1]}
```

But `provenance._episode_qc_state` reads **only** `state`:

```python
state = att.episode_qc.get("state")
return state if state in ("judged", "absent") else "unknown"
```

so `montage verify` reports `episode_qc: "judged"` for that delivery — and
`using-montage`'s CP3 text tells the human, in so many words, that a reel this
router delivered "should always read `judged`". **The gap is recorded in the JSON
and invisible at the one place the design promised a human would see it.** That is
not the §8 hole; it is a second, smaller one hiding inside the mitigation.

### 1.2 · The gate already knows how to catch this — nobody asks it twice

The reprocess calls `process_episode` with the episode's own manifest, whose
`out_path` is `out_dir/ep{i}.mp4` — **the same file** `ReelEpisode.clip` names and
the same file `episode_qc build` digested. So the re-render *overwrites the bytes
the verdict was stamped against*, and a second run of phase 2 would fire the
existing `episode-qc-stale` on its own.

The hole is not that the gate is too weak. It is that the **first** phase-2 run
delivers before anything asks a second time.

### 1.3 · A partial re-judge needs no new `episode_qc` code

`build_qc` re-reads every episode's `findings.json` and re-digests every clip from
disk. So re-judging exactly the reprocessed episodes is: overwrite *their*
`findings.json`, leave the others alone, run `episode_qc build` unchanged. `pack`
is idempotent — it writes `strip.jpg`/`evidence.json` and never touches
`findings.json` — so re-packing everything is safe and preserves the verdicts being
kept.

This is why the slice is M and not L: the expensive half already exists.

### 1.4 · The cost, measured: on the one real run it is zero

`work/reel/reel_report.json` from the 2026-08-03 run: `overall: true`,
`fail_reasons: []`. **The retry loop never engaged.** A stop-before-delivery costs
nothing on a clean reel and costs one QC round exactly when an episode was
re-rendered — which is exactly when the verdict is stale.

And it is **one** round per phase-2 invocation regardless of how many reprocess
rounds happened inside the loop: `build_reel` converges internally and only reaches
the deliver arm once.

## 2 · The shape: stop before delivering over an unjudged render

At the top of `build_reel`'s `deliver` arm — before the mix is built, before any
further ffmpeg — refuse when **both** hold:

- `reprocessed` is non-empty, and
- the manifest's own provenance says `episode_qc.state == "judged"`.

The result is the same `stop_and_report` shape every other reel-level refusal uses,
with the reel's passing report attached, so the human sees that the picture is fine
and only the verdict is stale:

```json
{"status": "stop_and_report",
 "finding": {"reason": "episode-qc-reprocessed", "episode_idx": null,
             "problems": ["episode 1 was re-rendered after it was judged — …"]},
 "report": {…}, "reprocessed": [1]}
```

**The decision is pure and lives beside the gate it belongs to.**
`lib/episode_qc.reprocess_gate(state, reprocessed) -> (reason, problems)`, the same
`(reason, problems)` shape `gate` returns, so the message text is testable without
a driver and the vocabulary stays in one module.

`QC_REPROCESSED` is **not** a fourth entry in `QC_STOPS`. That tuple is the pure
`gate`'s reasons — outcomes of comparing verdicts to digests — and its docstring
already refuses a fourth. This reason is discovered by bookkeeping, not by hashing,
and it is raised by a different caller at a different moment. It sits beside
`QC_STOPS` with a comment saying so.

### 2.1 · Why it fires only on the judged path

On `state == "absent"` — `build_reel`'s own CLI, or the single-command
`edl_to_reel` — there is no verdict for the reprocess to invalidate, and refusing
would break the SP1 front door for a hand-authored EDL, which episode-qc §10
deliberately keeps open. `absent` reels keep delivering, and keep saying `absent`.

**No waiver on the judged path** (governance #8, and episode-qc's own rule): there
is no flag, no threshold, and no override that lets a judged reel ship over a
re-rendered episode.

### 2.2 · Why the second phase-2 run delivers

Because §1.2's overwrite is what makes the loop converge rather than repeat:

1. The corrected clip is already on disk at the path `EPISODES.json` names.
2. `episode_qc build` re-digests from disk, so the new verdict binds the *new*
   bytes and `gate` passes.
3. `build_reel` re-runs over the corrected clips, `check_reel` finds the picture
   already fixed, so `reprocessed` stays empty and the deliver arm is clean.

No version is wasted: the first run stops **before** `deliver`, so no `REEL_v{n}`
and no attestation are written.

The corollary is worth stating, because it is the same fact §4.1 states as a
warning: `build_reel`'s compounded colour factor is not persisted anywhere, so the
*only* thing carrying the loop's convergence between the two passes is the clip
bytes. That is exactly why the second pass works — and exactly why re-running phase
1 destroys it. Note also that pass 2 begins from a state pass 1 already proved
passing, over the same bytes, and `check_reel` is deterministic on identical bytes:
so pass 2 reproduces pass 1's verdict, does not reprocess, and never reaches the
`cc`-reset that a fresh `build_reel` call would otherwise start from.

## 3 · The backstop: a fourth `episode_qc` state

`_episode_qc_state` gains one arm: `state == "judged"` **and** a non-empty
`reprocessed_after` → **`"stale"`**. Same word the gate already uses for the same
meaning — the verdict describes other bytes.

§2 makes this unreachable through the router, which is the point of having it: it
covers what §2 cannot — `build_reel`'s own CLI writing a hand-made judged manifest,
a future producer that forgets, and old sidecars already on disk. A backstop that
names the state is this project's idiom for "no silent bypass, not no bypass".

`using-montage`'s CP3 text is corrected in the same slice: `stale` joins `absent`
and `unknown` in the list of states that must be named plainly rather than passed
over.

## 4 · The router loop

`using-montage` step 14 today says to *offer* to re-run episode-qc after a delivery
with a non-empty `reprocessed` list — prose, unenforced, and offered **after** the
reel is already delivered and attested, so even a blocking finding arrives too late
to stop anything. It becomes a routed stop with a fixed remedy:

1. Phase 2 stops with `episode-qc-reprocessed` naming the episode indices.
2. Re-run `episode_qc pack` (safe: it preserves existing `findings.json`).
3. Dispatch **one fresh judge per named index only** — not all N. The verdicts for
   untouched episodes are about bytes that did not change.
4. `episode_qc build` — unchanged, re-digests everything from disk.
5. Re-run `edl_to_reel --from-episodes`.

### 4.1 · The landmine: do not re-run phase 1

`build_reel`'s compounded per-channel colour factor is **never persisted** — not on
`Manifest`, not on `PathMeta`, not in `EPISODES.json`, which phase 2 never
rewrites. It exists only in the clip bytes on disk. Re-running phase 1
(`--stop-after-episodes`) after this stop re-renders every episode from the
manifest and **silently discards the correction the retry loop just converged on**,
putting the reel back where it started.

The same fact `using-montage` already records about `probe grade`'s baseline, now
biting a second consumer. It goes in the skill text at the point where a reader is
most likely to reach for phase 1.

## 5 · Alternatives rejected

- **Re-run the real `gate()` inside `build_reel` before delivering.** Strictly
  stronger — it would also catch a clip mutated by something *other* than the retry
  loop. Rejected: it pulls `EPISODE_QC.json` reading into the reel driver, which
  the two-phase split deliberately keeps in `edl_to_reel` (and `build_reel`'s own
  CLI has no QC artifact at all), and it re-hashes N clips on every delivery to
  answer a question the driver already knows the answer to exactly. The extra
  coverage is a different threat model — concurrent mutation — with no evidence it
  happens.
- **Visibility only** (§3 without §2). Cheap and honest, but the reel still ships
  unjudged; it only says so louder. That is what §8 already chose, and the row asks
  to close it.
- **Re-judging inside the retry loop** (episode-qc §13's own phrasing for closing
  §8 "fully"): `build_reel` pausing after each reprocess round for a fresh verdict.
  Still rejected, and for a sharper reason now that §1.4 is measured: it needs the
  loop to become agent-drivable, and it buys nothing over stopping at the deliver
  arm — the loop's *intermediate* renders are never shipped, so only the last one
  needs a verdict.
- **Forbidding auto-reprocess on the judged path** (`cap=0`). Trades away the
  colour convergence loop entirely; episode-qc §2/§8 already priced that as a worse
  deal.

## 6 · What does not change

`gate`, `ReelQC`, `EpisodeVerdict`, `build_qc`, `pack`, the evidence packet, the
naturalness sensor, `check_reel`, `deliver`, the attestation's shape, and
`PROV_V`. No new artifact, no new stage, no new CLI flag, no ffmpeg change. The
`reprocessed_after` block `build_reel` already writes keeps being written — §3 just
stops throwing it away on the way to the human.

## 7 · Testing

- `reprocess_gate` — pure: judged + non-empty refuses and names every index;
  judged + empty passes; `absent`/`unknown` + non-empty passes (§2.1). Mutation:
  dropping the state check makes the `absent` case refuse.
- `build_reel` — a judged manifest whose loop reprocesses returns
  `stop_and_report` with the reason and no delivery; the same manifest with
  `absent` still delivers. Mutation: moving the refusal after the mix branch makes
  the stop cost an ffmpeg call it should not.
- `_episode_qc_state` — the fourth arm, and that `absent` + non-empty
  `reprocessed_after` stays `absent` (a reel with no verdict cannot have a stale
  one).
- End-to-end over real bytes: phase 1 → judge → phase 2 with a forced colour
  outlier → the stop; re-judge exactly that episode → phase 2 again → delivered,
  `reprocessed` empty, attestation `judged`. **With a control that must not move**:
  the same reel with no outlier delivers in one pass, unchanged.

## 8 · Deferred (each gets a backlog row)

- **Auto-routing a blocking finding into a re-render** — the P3 half of this row,
  unchanged. Still waits on the front-half EDL fixer.
- **Bounding the outer loop.** Nothing caps how many stop → re-judge → phase-2
  cycles a reel can take. Each one needs a human or an agent to dispatch judges, so
  it cannot spin unattended — but `rm.cap` bounds attempts *within* one
  `build_reel` call and nothing bounds them across calls. **P3**: name a real case
  before inventing a constant.
- **`episode_qc pack --only`.** Re-packing all N episodes to re-judge one costs N
  strip builds. Measured at 8 episodes it is seconds, so this is convenience, not a
  fix. **P4.**

## 9 · Honest limits

- **This closes the automatic hole, not the manual one.** An agent with a shell can
  still run `build_reel` directly, or `edl_to_reel` in one shot, and ship a reel no
  judge saw. Those paths report `absent`, which is the honest answer, and §3 makes
  a hand-forged `judged` visible — but neither is prevented. The invariant remains
  *no silent bypass*.
- **It proves the shipped render was judged, never that anyone looked.**
  episode-qc §12 is unchanged: an empty findings list is a claim. This slice
  strengthens *which bytes* a claim is about, not the claim's quality.
- **The re-judge is only as fresh as the judge dispatched for it.** Nothing
  prevents re-running the judge on the same packet until it comes back green;
  `reviewer` remains a record, not a prohibition.
- **§1.4's cost measurement is one run.** The retry loop firing zero times on one
  reel is evidence that the friction is rare, not that it is rare in general. A
  reel cut from genuinely mixed exposure will fire it, and will pay a QC round.
- **The end-to-end proof fakes both the reprocess and the first `check_reel`
  round.** The real reprocess runs YOLO and the real colour check needs a real
  tint, so §7's integration test shows that the loop's *arms* are wired —
  reprocess → stop → re-judge → deliver — not that a real colour outlier drives it
  there. `tests/integration/test_reel_retry.py` separately proves a real
  `color_correct` moves real pixels. **The two proofs are not joined**, and no test
  in this repo watches a real colour failure travel all the way to this stop.
- **Nothing verifies that the re-judged verdict is about the *corrected* render
  rather than an accidental third one.** It verifies the digest matches the bytes
  on disk at build time — which is exactly the guarantee `build_qc` already gives,
  and no more.
