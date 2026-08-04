# Attested run — provenance chain + gates out of the worker's reach

**Status:** design approved 2026-08-04 (brainstorm this session).
**Closes:** fixes-backlog #8, #11, #13, #15, #20 (+ riders #6, #16, wip-branch triage).
**Phase:** cinematic-quality-playbook §4 priority 2 — *governance hardening*.

---

## 1. The problem, in code coordinates

The 2026-08-03 real run produced a reel the pipeline had **rejected**, on an engine
that changed ~40 times while the run was in flight, from an `EDL.json` edited by
hand outside the tooling, with the editorial review never invoked. Every one of
those was reachable because nothing the run wrote could be checked against
anything else. The specific holes:

| # | Hole | Where |
|---|------|-------|
| 13 | `deliver` accepts **any** `ReelReport`. A hand-written `{"overall": true}` ships a reel that never met a gate; a hand-run `ffmpeg -f concat` master is indistinguishable from an assembled one. | [deliver.py:63](../../scripts/deliver.py) — the gate reads `report.overall` and nothing binds `report` to `master` |
| 20 | `EDL.json` carries no link to the `selection.json` it was projected from, so a raw-JSON edit is indistinguishable from a tool-authored file. | [edit_plan.py:282](../../scripts/edit_plan.py), [match_grade.py:66](../../scripts/match_grade.py) — two writers, `json.dumps(edl.to_dict())`, no stamp |
| 11 | No artifact records which engine revision produced it, so "the engine changed mid-run" is undetectable after the fact. | nothing anywhere |
| 15 | `reel-review` is `kind="optional"`, so `next_action` never points at it — skipping CP3 costs nothing. | [montage.py:60](../../scripts/montage.py) |
| 8 | `--color-delta-max` raises a **hard** gate's ceiling with no record. It is the only such flag today; the class is what matters. | [edl_to_reel.py:134](../../scripts/edl_to_reel.py) |
| 6 | Titles/effects are optional stages the autonomous path skips without ever asking. | [skills/using-montage/SKILL.md](../../skills/using-montage/SKILL.md) step 10 |
| 16 | `VERSIONS.md` logs the **path** of `VERSIONS.md` as every entry's note. Root cause found: `edl_to_reel` passes the log path as the changelog **text**. | [edl_to_reel.py:117](../../scripts/edl_to_reel.py) `changelog=str(Path(out_dir) / "VERSIONS.md")` |

The unifying diagnosis: **the pipeline's claims are unverifiable.** A delivered
reel asserts "I passed check_reel" and nothing can confirm or refute it.

## 2. Locked decisions

1. **Refuse **and** record** (user, this session). A forged artifact is refused
   outright, with no escape flag. A *legitimate* gate loosening (`--color-delta-max`)
   stays available but is recorded in the delivery's attestation and surfaced at
   CP3. The invariant is not "a gate cannot be loosened" — it is **"a gate cannot
   be loosened silently."**
2. **Engine drift inside a run is a hard stop** (user, this session). A *statically*
   dirty tree at run start is recorded and mentioned once at CP1 — the user develops
   in this clone and that must keep working. A SHA/dirty **change between stages of
   one run** is precisely the #11 failure and stops the run.
3. **Refusal fires on tampering, never on absence.** See §5 — this is the decision
   that keeps the designed hand-authored-EDL path (SP1) alive.
4. **One module owns git and hashing:** `scripts/lib/provenance.py`.
5. Riders in scope: #6 (router asks about titles/effects), #16 (`VERSIONS.md` note),
   wip-branch triage.

## 3. Module boundary — `scripts/lib/provenance.py`

Pure except for two effects: it shells out to `git` (through `proc.run`, like every
other subprocess in this repo — `lib/lint.py`'s AST scan bans a bare `subprocess`
import outside its allowlist) and it reads files to hash them.

```python
ENGINE_PATHS = ("scripts", "skills", "bin")   # what "the engine is dirty" is measured over
PROV_KEY = "provenance"
PROV_V = 1

def engine_stamp() -> dict          # {"sha": "083df1a…", "dirty": False}
def digest_file(path) -> str        # streaming sha256, hex
def digest_obj(d: dict) -> str      # sha256 of canonical JSON of d WITHOUT PROV_KEY
def stamp(d: dict, *, inputs: dict[str, str] | None = None) -> dict
def check(d: dict) -> tuple[str, str]        # ("unstamped"|"intact"|"tampered", detail)
def spec_overrides(spec, *, exempt=("target_dur",)) -> list[dict]

@dataclass
class Attestation: ...              # §6
```

**`engine_stamp()` is best-effort and honest.** `git -C <repo root> rev-parse HEAD`
plus `git status --porcelain -- scripts skills bin`. Git missing, not a repo, or a
non-zero exit → `{"sha": "", "dirty": None}` — recorded as *unknown*, never guessed.
The repo root is derived from `__file__` (`parents[2]`), not `cwd`: `bin/vg` already
`cd`s to the clone root, but a library must not depend on that (the plugin-packaging
§1.1 rule).

**Dirty is measured over `scripts/`, `skills/`, `bin/` only.** A doc edit, an
untracked run artifact, or a scratch file is not an engine change; treating it as
one would make the §7 stop fire constantly and train everyone to ignore it.

**`digest_obj` excludes `PROV_KEY`,** so a block can be recomputed over the object
that carries it without chasing its own tail. Canonical form is
`json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.

**No timestamp in the artifact block.** A `written_at` would make every stamped
artifact byte-unstable between runs and churn the edit-plan goldens for nothing;
the digest and the engine SHA are what enforcement reads. Time lives in the
attestation (§6), which has no golden.

The block written into an artifact:

```json
"provenance": {"v": 1,
               "engine": {"sha": "083df1a…", "dirty": false},
               "self": "<sha256 of this object minus provenance>",
               "inputs": {"selection": "<sha256 of selection.json>"}}
```

## 4. Three stamp points

| Artifact | Written by | Carries |
|---|---|---|
| `project.json` | `project_init` | `provenance` — **the run's start stamp**, the reference §7 compares against |
| `EDL.json` | `edit_plan.write_edit_plan`, `match_grade.write_match` | `provenance` + `inputs.selection` digest |
| `reel_report.json` | `check_reel.run` | `ReelReport.master_digest` — sha256 of the master it actually measured |

`ProjectConfig` gains `provenance: dict = field(default_factory=dict)`, round-tripped
through `to_dict`/`from_dict`. `EDL` gains the same field. Both default empty, so
every existing artifact and every test fixture stays valid. Carrying the block as a
**field** (rather than stamping the dict on the way out and forgetting it) is what
lets `edl_to_reel` fill the attestation's `edl` block from `edl.provenance` without
re-hashing: by then `from_json` has already refused anything tampered, so what
survives is `intact` (block present) or `unstamped` (block absent).

**Both EDL writers go through one new chokepoint** `edl.write_edl(edl, path, *,
selection=None)` — it stamps and writes. Two writers stamping independently is the
shape that drifts; one is the shape that cannot. (`match_grade` rewrites `EDL.json`
in place; it re-stamps, because it is a legitimate tool and its output is the tool's
output.)

`ReelReport` gains `master_digest: str = ""` in `to_dict`/`from_dict`. `check_reel.run`
sets it from `digest_file(master)`.

Deliberately **not** stamped in v1: `FOOTAGE.json`, `SPEC.json`, `MUSIC.json`,
`PACING.json`, `TITLES.json`, `REVIEW.json`. `project.json` (start) and the
attestation (end) already bracket the whole run for drift detection, and `EDL.json`
splits it in half; more stamp points would only narrow *where* a drift happened, which
nothing acts on. Named here so the omission is a decision, not an oversight.

## 5. Two refusal points — and the absence-vs-tamper rule

**The rule:** a **missing** provenance block is legal; a **present but mismatched**
one is refused.

This is not leniency, it is the correct distinction. `edl_to_reel`'s designed front
door is *"a hand-authored EDL.json → a delivered REEL_v1.mp4"* (extract-spine, SP1) —
the repo's own integration tests author EDLs by hand, and refusing an unstamped EDL
would delete a designed capability to punish nobody. The #20 offence was never
"an EDL a human wrote"; it was **editing the tool's output while presenting it as the
tool's output**. A self-digest that no longer matches its object is exactly that, and
nothing else.

### 5.1 `EDL.from_json` — tampered EDL

Verification lives at the **read** chokepoint, so all four consumers (`edl_to_reel`,
`draft`, `pacing`, `match_grade`) inherit it from one place. `check(d)` on the raw
loaded dict — the file is `json.dumps(to_dict(), indent=2)`, so `json.loads(file)`
is `to_dict()` exactly and the digests are comparable.

- `unstamped` → proceed, record the state.
- `intact` → proceed.
- `tampered` → `ValueError`: *"EDL.json was edited after edit_plan wrote it (its
  provenance digest no longer matches its contents). Editorial changes belong in
  selection.json — edit that and re-run `edit_plan build`; raw-JSON surgery
  bypasses the manifest preflight that catches a window running past EOF, a
  scene-cut straddle, and an unresolved cast pin."*

The state (`unstamped`/`intact`) rides into the attestation, so a reel cut from a
hand-authored EDL says so on the record.

### 5.2 `deliver` — report not bound to this master

`deliver` re-digests the `master` it is about to encode and compares to
`report.master_digest`:

- empty → refuse. `check_reel.run` **always** sets it, so an empty digest means the
  report did not come from `check_reel` — which is #13 exactly.
- mismatched → refuse. The report describes a different file than the one being
  shipped: a hand-assembled master, or a master re-made after the check.

Empty-refuses is the **deliberate exception** to §5's absence rule, and the reason
the two differ is worth stating: an unstamped EDL has a legitimate producer (a human,
via the documented SP1 front door), so absence there carries no information. An
unstamped report has no legitimate producer at all — `check_reel` is the only thing
that writes one, and it always stamps. Absence there *is* the signal.

Both raise `RuntimeError` beside the existing `report.overall` gate, with the remedy
*"run `check_reel` on this master and deliver with the report it writes"*.

This is an **atomic swap**: every existing test that hands `deliver` a
hand-constructed `ReelReport` must now bind it, and the plan updates them all in
the same task. A default-tolerant version of this check protects nothing.

## 6. The attestation

`deliver` writes `out/REEL_v{n}.attest.json` beside the encode:

```json
{"v": 1, "reel": "REEL_v3.mp4", "reel_digest": "…", "master_digest": "…",
 "report_digest": "…", "overall": true,
 "engine_at_start": {"sha": "083df1a…", "dirty": false},
 "engine_at_deliver": {"sha": "083df1a…", "dirty": false},
 "edl": {"digest": "…", "state": "intact"},
 "overrides": [{"field": "color_delta_max", "value": 20.0, "default": 12.0}],
 "delivered_at": "2026-08-04T13:22:41"}
```

`reel_digest` binds the attestation to the **shipped file**, not only to the master,
so a delivered reel swapped afterwards is detectable.

`ReelManifest` gains `provenance: dict = field(default_factory=dict)`: `edl_to_reel`
fills it (EDL digest + state, the start stamp read from `project.json`, the override
list), `build_reel` threads it through unchanged, `deliver` merges in what only it
knows (both digests, `overall`, the deliver-time stamp, the timestamp) and writes the
sidecar. One field, one direction of flow, no new plumbing between modules that do not
already talk.

**Overrides need no registry.** `spec_overrides(spec)` diffs the effective
`ReelCheckSpec` against a default-constructed one field by field, exempting
`target_dur` (legitimately per-reel). Any threshold added to the spec in the future is
covered the day it is added, with no second place to remember.

**`montage status` reports, `montage verify` proves.** `next_action` gains a
`deliveries` list — one entry per `out/REEL_v*` with its attestation's presence and
recorded `overall`, read from JSON only (cheap; the router calls `status` constantly).
A hand-concatenated reel has no attestation at all and shows as `unattested`. The new
`montage verify --run-dir` subcommand re-hashes each delivered file against its
attestation — run once at CP3, where the cost is irrelevant and the answer matters.

Both report the same per-delivery shape, `status` filling `state` from JSON alone and
`verify` from the re-hash:

```json
{"file": "REEL_v3.mp4", "state": "attested", "overall": true,
 "overrides": [...], "engine_drift": false, "detail": ""}
```

`state` ∈ `attested` · `unattested` (no sidecar — the manual-concat signature) ·
`failed-gate` (a sidecar recording `overall: false`) · `digest-mismatch` (`verify`
only — the shipped file is not the file that was delivered).

## 7. Engine freeze (#11)

One enforcement point, chosen where the run is expensive: **`edl_to_reel`** already
reads `project.json`. It compares `engine_stamp()` now against
`project.json`'s recorded stamp and raises `ValueError` on any difference in `sha`
or `dirty`, naming both revisions:

> *the engine changed since this run started (project.json records
> `083df1a` clean, now `6e9293a` dirty) — a montage run must not straddle an engine
> change, because the stages already finished were produced by different code. Start a
> fresh run dir, or re-run `project_init` against the current engine to re-baseline.*

A raise, not a routed `stop_and_report`: `edl_to_reel`'s own contract puts setup
errors (the environment changed under the run) in the exception channel and reserves
findings for editorial problems routed back to a stage's skill. There is no culprit
stage here.

An **unknown** stamp on either side (`sha == ""`, git unavailable) cannot prove drift
and does not stop the run — it is recorded as unknown in the attestation. A run
started before this slice has no recorded stamp at all: unstamped, no comparison, no
stop (§5's absence rule again).

Static dirt at run start is **not** a stop: it is recorded in `project.json`, echoed
once at CP1 by the router, and rides into every attestation. The user's own tree is
the user's business; the engine changing *mid-run* is not.

## 8. CP3 stops being free (#15)

`montage.py`: `Stage("reel-review", "REVIEW.json", "optional", …)` → **`"required"`**.
`next_action` then points `next` at `reel-review` once `deliver` is done, and the
router's finish condition becomes `next is None` rather than `delivered`. One word in
the stage table, the tests that pin the table, and the SKILL text that says the run is
over.

## 9. Riders

- **#6 — the router asks.** `using-montage` gains an explicit question at **CP2**
  (not CP1: by CP2 the EDL exists, so the reel length is known and titles can
  actually be timed): *"titles? effects (slow-mo, transitions, SFX)?"* — and names
  what it skipped when the answer is no. Text-only change.
- **#16 — the VERSIONS.md note.** `edl_to_reel` stops passing the log's own path as
  the note text; a `--changelog` passthrough carries a real reason, defaulting to a
  meaningful one (`"delivered from EDL.json"`). A test asserts the written note is not
  a path to `VERSIONS.md`.
- **#8's doc half.** The gates cannot be self-exempted *structurally* (§5), but the
  briefs must say so too: `using-montage`, `process-episode` and `edit-plan` gain one
  explicit line — *you may not disable, lower, or downgrade any quality gate; a gate
  that blocks is routed back to its stage, never loosened to pass.* The memory rule
  that subagents do not inherit their dispatcher's prohibitions is why this must be
  written in each brief, not assumed.
- **wip-branch triage (#11's current-state alert).** `wip/montage-run-hardening`
  (`4841dd3`) was fully ported in three slices (track-stitch 2026-07-28,
  path-quality 2026-07-28, titles-animations 2026-07-29). `wip/montage-run-patches`
  (`fbcd052`) is superseded — its diff against `main` is now mostly the *removal* of
  work `main` has since landed. Both branches are deleted; **their SHAs are recorded
  here** so the commits stay reachable via `git reflog`/`git show` if anything is ever
  wanted back. The `#11` alert about the dirty live tree is retired: the tree is clean
  and the patches are landed or superseded.

## 10. Testing

- **Unit** (`tests/lib/test_provenance.py`): `digest_obj` ignores the `provenance`
  key and key order but not values; `stamp`+`check` round-trip → `intact`; a mutated
  field → `tampered`; a missing block → `unstamped`; `engine_stamp` on a non-repo path
  → `{"sha": "", "dirty": None}` (no raise); `spec_overrides` returns `[]` for a
  default spec and the changed field for a loosened one, and **automatically covers a
  field added to `ReelCheckSpec`** (the test constructs the diff generically, not
  against a hard-coded list).
- **Refusals** (`tests/lib/test_edl.py`, `tests/lib/test_deliver.py`): a tampered EDL
  raises with the `selection.json` remedy; an unstamped one loads; an empty and a
  mismatched `master_digest` both refuse; a bound one delivers.
- **Drift** (`tests/lib/test_edl_to_reel.py`): a project stamped with a different SHA
  raises naming both; an unknown stamp on either side does not.
- **Real-ffmpeg integration** (`tests/integration/`): one end-to-end run
  EDL → `edl_to_reel` → delivered reel whose `attest.json` verifies, plus the
  negative — re-encode the delivered file (or swap the master) and `montage verify`
  reports the mismatch. This is the proof that the chain holds against real pixels
  rather than only against fixtures.
- **Router** (`tests/lib/test_montage.py`): after `deliver`, `next == "reel-review"`.

## 11. What this does NOT do — the honest half

**An agent with a shell can bypass all of it.** It can run `ffmpeg` by hand, write
its own JSON, and hand the user a file. Nothing in this design — nothing in *any*
design short of taking the shell away — prevents that. What it achieves is narrower
and worth stating exactly:

> No delivered reel can claim a gate it did not pass, and every bypass leaves a
> machine-detectable trace.

Concretely, the bypasses that remain and what they now cost:

- **Hand-assembled reel, delivered outside `deliver`.** Still possible; produces no
  `attest.json`, so `montage status` reports the delivery as `unattested` and CP3
  shows it. Detectable, not preventable.
- **A gate-weakening knob outside `ReelCheckSpec`/`CheckSpec`.** `spec_overrides`
  diffs those two dataclasses; a future flag that weakens a gate some other way
  (a new `--skip-x`, a threshold living elsewhere) would not appear in the override
  list. There is **no machine predicate for "this flag weakens a gate"** — the
  mitigation is the convention that thresholds live in the spec dataclasses, plus the
  §9 brief line. Named as a real gap, in the tradition of the wade-in landmine.
- **`assemble.py` stays.** Making a master is not the offence; delivering an unchecked
  one is, and §5.2 closes that. Removing the standalone assembler would cost a useful
  tool and close nothing.
- **A tampered EDL that is also re-stamped.** Anyone who reads this document can
  recompute a valid digest by hand. The stamp defeats *casual* raw-JSON surgery —
  the actual observed failure — not a deliberate forgery. Honest scope.
- **Engine drift within a stage.** The §7 comparison happens when `edl_to_reel`
  starts. Patching the engine *during* the back half is not caught until the next
  run's comparison. One point, chosen for cost; more points would narrow this.
- **`dirty` is a boolean over three directories.** It does not say *what* changed and
  does not distinguish a whitespace fix from a loosened threshold.

## 12. Deferred / non-goals

- Stamping the other six run artifacts (§4) — deferred, named.
- A signed (rather than merely digested) attestation — pointless against a local
  agent with the key.
- Per-episode attestation. The reel is the delivered unit; episodes are intermediates.
- #3 (per-episode QC subagent) and #12 (look-don't-guess) are the *editorial* half of
  governance and belong to playbook priority 3, not here. This slice makes the QC that
  already exists un-skippable; it does not add new QC.
- #19/#14 (shot variety, editorial-rule memory) — priority 3.
