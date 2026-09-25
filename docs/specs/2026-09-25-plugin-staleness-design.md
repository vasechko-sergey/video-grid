# Plugin staleness — the installed instructions against the running code

> Backlog P2 (reachable-instructions §0.7, §6 row 1): *nothing detects that the
> installed plugin is behind the repo.*

**Status:** design. Version 0.14.0 (MINOR — a new blocking runtime check).

---

## §0 What is on this machine

Every number below was read off this machine on 2026-09-25, before any code was
written. Two of them overturn the row's own framing, and one overturns the
instrument that produced it.

### §0.1 The cache is the live load path — measured, not inferred

`~/.claude/plugins/cache/video-grid/video-grid/0.2.1/.in_use` holds **six PID lock
files**, written 2026-09-25 11:51. Claude Code processes are holding that directory
open right now. The skills the agent reads come from the version-keyed cache, not
from the clone.

There is no `~/.claude/plugins/marketplaces/video-grid` directory: the marketplace
is a *directory* source, and the plugin content is still copied into the cache —
the behaviour the plugin-runtime-resolution design already recorded ("the install
`cp -R`s the repo into a runtime-less cache").

### §0.2 What is stale is the INSTRUCTIONS, not the code

`~/.config/video-grid/root` reads `/Users/serg/git/video-grid` — the live clone.
Every skill's preamble resolves `$ROOT` from that file and invokes
`"$ROOT/bin/vg"`. So the Python that runs is always the clone's, at whatever
version the clone is. The row's phrase "the installed plugin is behind the repo"
is true of the *text* and false of the *code*.

What is frozen at 0.2.1:

| | cache | clone | identical |
|---|---|---|---|
| skills present | 14 | 14 | same 14 names |
| `SKILL.md` bodies | 188 KB | 204 KB | **0 of 14** |
| always-resident `description:` | — | — | **0 of 14** |

Zero identical in either column. The always-resident description budget — the 4685
chars the re-derivable-purpose slice (0.9.2) cut and rewrote across all fourteen
skills — is entirely the 0.2.1 text.

### §0.3 The identity is recorded exactly, in two independent forms

`~/.claude/plugins/installed_plugins.json`, key `video-grid@video-grid`:

```json
{ "scope": "user",
  "installPath": ".../cache/video-grid/video-grid/0.2.1",
  "version": "0.2.1",
  "installedAt": "2026-08-02T08:24:51.633Z",
  "lastUpdated": "2026-08-25T11:05:17.772Z",
  "gitCommitSha": "f499e193d431b3b520fe740647d7b4fd5ec9cab2" }
```

That sha resolves in the clone: `f499e19 chore: version the plugin properly, and
bind the bump to a changelog entry`, 2026-08-25, `plugin.json` version `0.2.1` at
that commit, and **392 commits** from there to `HEAD`. So the record is not a
guess to be reconstructed — the installer already wrote down exactly what it
installed.

`known_marketplaces.json` gives the marketplace as
`{"source": "directory", "path": "/Users/serg/git/video-grid"}`. The clone is its
own marketplace. No network is involved in any of this, and no remote version
exists to consult.

The last reinstall was 2026-08-25, the day before 0.3.0 landed.

### §0.4 A REQUIRED stage does not exist in the instructions the agent reads

The word `geometry` appears **0 times** in the installed `using-montage` body and
**7 times** in the clone's. `--stop-after-geometry` / `--from-geometry`: **0**
against 2.

`montage.V1_STAGES` carries `episodes-geometry` with `kind: "required"` and the
runner note "the seam match-grade measures the shipped crop in". That stage — the
whole 0.6.0 grade-shipped-pixels split, which is what closed R2.1 — cannot be
invoked from the installed instructions, because they do not mention it.

The installed router *does* know the two-phase episode split
(`--stop-after-episodes` / `--from-episodes`, 7 mentions). It is precisely the
0.6.0 three-phase boundary that is missing.

### §0.5 Every artifact path in every installed skill is the pre-0.3.0 layout

`reels/` occurs **101 times** across the clone's fourteen skills and **0 times**
across the installed ones. Run-layout-lifetimes (0.3.0) moved every artifact into
`reels/<name>/{episodes,deliveries,build}`; the installed instructions name the
flat locations that slice retired.

### §0.6 The obvious instrument understates the problem — measured

A repo-wide sweep of long flags — every `--flag` mentioned in an installed skill
against every `--flag` defined anywhere in `scripts/` — reports **exactly one**
dead flag, `--color-delta-max` (deleted in 0.5.0 by colour-convergence-retire).
That reads as "one stale line".

It is the wrong instrument: it compares a flag against the *union* of all
commands. Per command:

```
installed:  scripts.match_grade build --edl <run>/EDL.json --footage-root <footage_root> ...
clone:      scripts.match_grade build --geometry <run>/reels/<reel>/episodes/GEOMETRY.json ...
live CLI:   --geometry  --eps  --force  --spec
```

`--edl` and `--footage-root` are gone from `match_grade` and survive the sweep
only because *other* commands still define them. The installed `match-grade` skill
issues a command the live CLI refuses outright.

That refusal is loud — argparse exits non-zero. That is luck, not design: the same
divergence in a *default* rather than a *flag name* would be silent, and §0.5 is
exactly that class (a path that no longer exists produces a different error, or on
a re-used name, none at all).

### §0.7 The fix is not self-blocking — and this is the only reason the row is closable

The installed `verify-runtime` skill is itself stale (2550 B against the clone's
3210 B), and it still works, because its step 1 reads the recorded root and its
step 2 runs `"$ROOT/bin/vg" scripts.verify_runtime` — the **clone's** code. Its
step 3 already says:

> list each `BLOCKED` required check with its remedy … Present it **verbatim in a
> ```bash block**

So a new `Check` row added to the clone's registry reaches a real run *with no
reinstall*, and its remedy is printed by instructions written eleven minor
versions before the check existed. Without this property the fix would be
unreachable by exactly the mechanism it reports.

### §0.8 The remedy is a real shell command

`claude plugin update <plugin>` exists in the `claude` CLI. So `Check.remedy`'s
documented contract — "the shell command the user runs to fix it" — holds
unchanged; no special case is needed for this row.

`claude plugin update --help` states *restart required to apply*. Recorded as a
limit in §6, not worked around.

---

## §1 The rule

**A runtime contract must cover every place the run's behaviour comes from.**

`verify_runtime` asserted one layer — what `setup.sh` installs into the clone. The
behaviour of a montage run comes from two: that code, and the instructions that
drive it. They are installed by different tools, into different directories, at
different times, and nothing compared them.

Corollary, and the reason this is a *blocking* check rather than a report: an
instruction set that predates a required stage does not degrade a run, it
misdirects one.

---

## §2 The contract

### §2.1 One new registry row, first

`preflight.CHECKS` gains, as its **first** element:

```python
Check("plugin", "installed plugin matches the clone", True,
      "claude plugin update video-grid@video-grid"),
```

First because it is the outermost question — *are you running the instructions you
think you are?* — and the cheapest: two file reads, no subprocess, no ffmpeg. The
tuple's order is the report's order, so a stale install is the first line printed.

### §2.2 The pure half

```python
def plugin_staleness(records: tuple[tuple[str, str], ...] | None,
                     clone_version: str) -> tuple[bool, str]:
```

`records` is one `(scope, version)` pair per install record, or `None` when there
is no install-record file at all. Four states, each named in the detail it
returns:

| input | result | why |
|---|---|---|
| `None` | PASS | no install record — running from the clone, there are no installed instructions to be stale |
| `()` | PASS | the record file exists and does not list this plugin — same conclusion, different cause, so it says a different thing |
| every version equals `clone_version` | PASS | detail names the version |
| any version differs | **FAIL** | detail names each mismatching scope and version, and the clone's |

`records` is a *sequence* because the producer's shape is a sequence:
`installed_plugins.json` maps a plugin id to a **list** of records (user, project,
local, managed scopes). There is one today. Reading it as one is the defect
unvalidated-shapes §1 names — a reader defending itself with a guarantee the
producer does not make — so every record is compared and every mismatch is named.

### §2.3 The impure half

`verify_runtime._probe_plugin()`:

1. Resolves the config dir as `$CLAUDE_CONFIG_DIR` when set, else `~/.claude`,
   and the record as `<config>/plugins/installed_plugins.json`.
2. File absent → `records = None`.
3. File present → parse, take `plugins[<id>]`, project each entry to
   `(scope, version)`. Key absent → `records = ()`. A record that is not a
   mapping, or that carries no `version`, is **not** skipped and does not become
   an empty string: it is an unreadable record, handled as below. The producer
   promises a list of records with a `version`; a record that is not one means
   the reader is looking at something it does not understand.
4. Reads the clone's `.claude-plugin/plugin.json` for `clone_version`. This is the
   tree the probe is executing from and `test_plugin_manifests.py` already gates
   its shape, so a failure here is not an expected state — but it is read with the
   same handling rather than being allowed to raise into a stack fragment.
5. Returns `plugin_staleness(records, clone_version)`.

**An unreadable record is a blocking, named failure** — not a pass, and not a raw
traceback. `verify_runtime.run()` already converts a raised probe into
`(False, "probe raised: …")`; this probe catches its own read/parse errors first
and returns a detail that names the path and the reason. Cannot-answer is not
allowed to read as fine (unvalidated-shapes §1); it is also not allowed to read as
a stack fragment.

### §2.4 The plugin id is derived, and the constant is pinned to it

`video-grid@video-grid` is `plugin.json`'s `name` @ `marketplace.json`'s `name`.
The probe derives it, because it needs it as a dict key regardless. The remedy
must stay a constant (`Check.remedy` is a frozen field, and widening that contract
for one row is not worth it), so the id appears twice.

A test pins the id inside `Check("plugin", …).remedy` against the id derived from
the two manifests. The two spellings cannot drift silently — the same idiom as the
four machine-checked path conventions and `test_plugin_manifests.py`.

### §2.5 The registry's own description changes

`preflight.py`'s module docstring says the registry is "what the `setup.sh`
baseline contract is". Every existing row's remedy is `bash setup.sh`; this row's
is not, and `setup.sh` does not install the plugin. Leaving the docstring is the
inert, now-false comment this repo deletes rather than qualifies
(sensor-provenance §1.4, unvalidated-shapes §1). It is rewritten to name both
layers.

---

## §3 What does not change

- `Check`, `CheckOutcome`, `RuntimeReport`, `to_dict`, `to_text`, `--json`, the
  exit codes.
- `evaluate(root=)`'s `cd <clone> && ` remedy prefix applies to the new row like
  any other. `claude plugin update` ignores its working directory, so the prefix
  is harmless, and a special case would cost more than it saves.
- `evaluate`'s keys-must-match invariant does the work it was built for: adding a
  `Check` without a probe raises. No wiring is needed to keep the two in step.
- **The installed skill needs no edit for the check to function** (§0.7). The
  clone's `verify-runtime` SKILL.md is updated for the *next* reinstall, not for
  this check to work.

---

## §4 Rejected: reporting the direction

"Behind" versus "ahead" requires parsing both versions as semver, which adds an
unparseable-version state to handle, and it changes nothing the code does.

The marketplace **is** the clone (§0.3), so `claude plugin update` re-copies the
clone whichever way the mismatch runs; one remedy serves both directions. Naming
both versions in the detail lets the reader see the direction without the code
claiming to know it.

This is the same ruling that deleted `color_fidelity.dominant` (flipped on three
of four episodes and no consumer acted on it) and `gradedamage.ENTROPY_BINS`
(mathematically inert): a number that changes no decision is not reported.

---

## §5 Acceptance is the user running the remedy

`tests/integration/test_verify_runtime.py::test_real_runtime_is_ready` asserts the
whole report is green on the machine running it. The moment this check lands, it
goes **RED** — correctly: 0.2.1 against the clone.

Its own docstring already sanctions this and prescribes the response:

> It is RED on purpose whenever the machine running it does not satisfy the
> contract, and it is deliberately NOT skip-gated on any single component:
> skipping is how an incomplete install stops being visible. … the suite is
> telling the truth about the machine, not about the code.

So nothing is bent: not the test, not the check, not the report. The sequence is

1. the slice lands and bumps to 0.14.0, with that one integration test expected
   red and every task review told so explicitly;
2. it merges to `main`;
3. **the user** runs `claude plugin update video-grid@video-grid` and restarts
   Claude Code;
4. the suite is re-run and goes green, because the machine is genuinely fixed.

Step 3 is a mutation of the user's system and is theirs to run, not the agent's.

---

## §6 Honest limits

- **It proves the versions agree, never that the instructions are right.** A
  matching install of a skill set with a wrong sentence in it passes.
- **It cannot see a clone edited without a version bump.** Deliberate: the version
  is the install key, and this repo bumps once per slice, so a content-level
  comparison would be red through every development session — the cry-wolf
  mechanism that took `color_delta_max` from 12 to 56.
- **The restart is invisible to it.** `update` fixes the cache; the running
  session keeps the skills it already loaded. Nothing here can detect that, and a
  green check immediately after an update can still be describing a session that
  is reading the old text.
- **Only the record is read, not the cache directory.** A cache directory deleted
  out from under a valid record reads as fine. The record is the installer's own
  statement of what it did; checking the bytes it names is a different question
  than the one this row asks.
- **`scope` is reported, never interpreted.** If two scopes disagree with the
  clone, both are named; nothing here knows which one Claude Code actually loaded.
- **This slice's own skill-text edit reaches a run only after the update** — the
  last thing to arrive, by exactly the mechanism it reports.

---

## §7 Deferred

To the backlog's P3:

- **Nothing gates that a run's instructions match its code at the content level.**
  This check reports a version disagreement; the fourteen stale bodies of §0.2 are
  not repaired by it, only counted. A content-level gate needs an answer to the
  cry-wolf problem in §6 first.
- **Nothing verifies that the recorded root is a checkout of the marketplace it
  claims.** `~/.config/video-grid/root` and `known_marketplaces.json`'s
  `installLocation` both name a directory today and are never compared; a
  `setup.sh` run from a second clone would point the skills at one tree while the
  plugin was installed from another, and every check here would still pass.
- **The `gitCommitSha` the installer records is not used.** §0.3 shows it resolves
  and yields an exact commit distance (392). It is strictly sharper than the
  version and strictly noisier (any docs commit moves it), so it is filed rather
  than built — with the measurement that makes it buildable already recorded here.
