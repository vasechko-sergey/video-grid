# ffmpeg baseline — one build, all libraries, resolved from a generated constant

_Last updated: 2026-07-20._

Install once, get every library the pipeline needs. No capability flags, no second install
step, no `setup.sh` branch that uninstalls a working binary to get a filter back.

Related: [landmine lint](2026-07-20-landmine-lint-design.md) (the AST scan this slice extends),
[footage intake](2026-07-12-footage-intake-design.md) (the repo's first vidstab consumer),
[assemble-draft](2026-07-13-assemble-draft-design.md) and [titles](2026-07-13-titles-design.md)
(the drawtext consumers).

## 1. What is broken

Measured on the development machine, **2026-07-20, before this slice landed**. Two of these
measurements have since moved — see [what has changed](#what-has-changed-since) at the end
of the section; the findings they support have not.

The installed `ffmpeg` is homebrew-core 8.1.2_1, configured with 13 `--enable-*` switches.
It carries **neither `libfreetype` nor `libvidstab`**:

```bash
$ ffmpeg -hide_banner -filters | grep -c drawtext   # 0
$ ffmpeg -hide_banner -filters | grep -c vidstab    # 0
```

So two shipped stages are dead on this box — §5.9 assemble-draft (drawtext labels) and
§5.16 titles — and footage-intake's shake measurement cannot run. Three integration tests
skip permanently.

Three separate defects follow from how `setup.sh` tries to fix that.

### The drawtext branch is destructive, and its condition is a tautology

`setup.sh:53` guards the branch that runs `brew uninstall --ignore-dependencies ffmpeg`
(line 58):

```bash
if ! ffmpeg -hide_banner -filters 2>/dev/null | grep -q drawtext; then
```

The obvious reading — "fires when drawtext is missing" — is wrong, and the correct reading
is worse. **That condition is true on every build, including builds that have drawtext.**
The cause is the script's first line: `set -euo pipefail`.

`grep -q` exits 0 the instant it matches. `drawtext` sits ~15.8KB into a ~36KB filter list,
so ffmpeg still has 20KB to write when the read end disappears; it takes `SIGPIPE` and exits
**141**. `pipefail` promotes 141 to the pipeline's status, and `!` inverts it to true.
Measured against a build that *does* carry drawtext, five runs out of five:

```bash
$ FF=/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg    # a build that HAS drawtext
$ for i in 1 2 3 4 5; do
    bash -c "set -o pipefail; $FF -hide_banner -filters 2>/dev/null | grep -q drawtext; echo -n \"\$? \""
  done
141 141 141 141 141
```

Drop `pipefail` and the same command reports 0. The failure is **asymmetric**: when the
filter is genuinely absent, `grep` reads to EOF and exits 1 — also non-zero, also inverted
to true. Both arms take the branch, so the check can never report "present" and the guard
is decoration.

**`brew uninstall --ignore-dependencies ffmpeg` therefore ran on any machine that reached
that line, not only ones missing the filter.** `brew uses --installed ffmpeg` reports
`openai-whisper` and `summarize`; the build is `--enable-shared`. Removing it with
`--ignore-dependencies` leaves both dependents linked against libraries that are gone.

The branch could not have completed either. Its own post-install verification
(`setup.sh:60`) carried the identical idiom, without even the `!` to disguise it:

```bash
ffmpeg -hide_banner -filters 2>/dev/null | grep -q drawtext || { echo "ERROR: drawtext still missing after tap install"; exit 1; }
```

141 is falsy, so `||` fires on a build that has the filter. The old script's **guaranteed**
path was: uninstall the working ffmpeg, compile a tap build, then abort with a false
"drawtext still missing". `setup.sh:102`/`:110` are the same two lines again for vidstab.

This is why the branches are deleted rather than repaired, and why §6's replacement captures
the filter list **once** into a variable and matches in-shell — no pipeline, no exit status
to misread. It is also a §12 landmine in its own right (a check that reports the opposite of
reality while looking obviously correct), and is registered there.

### The pin never took

`setup.sh:119` runs `brew pin ffmpeg 2>/dev/null || true`, and `brew list --pinned` was
empty. The comment above that line credits the pin with stopping version drift from moving
the goldens; it had never once applied. A pin that cannot fail is not a pin — the `|| true`
swallowed whatever went wrong, forever, which is why §6's replacement drops the idiom.

### The vidstab branch repeats the destructive dance

...under `--with-vidstab`, so a user following the documented remedy pays the uninstall
twice — and, by the tautology above, pays it whether or not vidstab was actually missing.

### What has changed since

Two of the measurements above no longer reproduce. Both are stated here rather than edited
away, because each is the evidence for a decision this slice made.

- **`brew list --pinned` is no longer empty.** The user has since installed `ffmpeg-full`
  8.1.2_1 by hand and pinned both `ffmpeg` and `ffmpeg-full`. The finding stands as dated:
  the pin the old comments relied on had never applied, and that is precisely why §6 removes
  the `2>/dev/null || true` instead of keeping a pin that cannot report failure.
- **`config/ffmpeg.env` now exists.** `bash setup.sh` has since been run against the
  rewritten script: it installed nothing new (`ffmpeg-full` was already present), verified
  both filters, recorded the paths and pinned. Core `ffmpeg` is untouched —
  `/opt/homebrew/bin/ffmpeg` still resolves to `Cellar/ffmpeg/8.1.2_1`, and `openai-whisper`
  and `summarize` are still installed. §10's proof ran; see [§12](#12-what-the-proof-actually-found-2026-07-20-after-bash-setupsh).

## 2. The version: `ffmpeg-full` from homebrew-core

`ffmpeg-full` is a homebrew-**core** formula, not a tap.

| | installed `ffmpeg` | `ffmpeg-full` |
|---|---|---|
| tap | `homebrew/core` | `homebrew/core` |
| version | 8.1.2 revision 1 | **8.1.2 revision 1** |
| build | 13 `--enable-*` | 47 dependencies |
| `libfreetype` / `fontconfig` / `libass` | ✗ | ✓ |
| `libvidstab` | ✗ | ✓ |
| bottle | — | ✓ `arm64_tahoe` |
| keg-only | no | **yes** (`:versioned_formula`) |

Two properties decide it.

**Identical version and revision.** Same upstream source, same homebrew patch level. The
golden-drift hazard `setup.sh` was written to guard against — 8.1.2 changed `boxblur`
argument validation and moved a golden — lives in ffmpeg's core, not in the optional
libraries. Swapping the *build* while holding the *version* is the smallest move that
gets the filters. It is not a proof that no pixel changes; the goldens are the test of
that, and this slice runs them.

**keg-only.** `ffmpeg-full` does not symlink into `/opt/homebrew/bin`. It installs beside
core `ffmpeg` rather than replacing it, so `openai-whisper` and `summarize` keep working
and nothing needs uninstalling. This is the property that lets the destructive branches die
outright rather than be made safer.

Cost: 18 new formulae (29 of the 47 deps are already installed), all bottled.

### Why not the tap

`homebrew-ffmpeg/ffmpeg --with-libvidstab` — what `setup.sh` does today — loses on every
axis. Option-flag builds are not covered by bottles, so it compiles from source. It
*replaces* core ffmpeg, which is the whole destructive-branch problem. And its version
tracks the tap rather than core, which reintroduces exactly the drift the pin was meant to
stop.

## 3. Resolution: a constant written at install time

`setup.sh` resolves the binary once and records it; the code reads the record. The call
site then passes the real path, so `argv[0]` is the binary that actually ran — the lint's
argv inspection sees the truth, and `proc.run`'s error messages echo a command you can
paste into a shell.

New module `scripts/lib/ffbin.py` — "the ffmpeg binaries". Named for the binaries rather
than the tool so the accessors read as `ffbin.ffmpeg()` and `ffbin.ffprobe()`; a module
called `ffmpeg` would force `ffmpeg.ffmpeg()` at every call site.

Three rungs:

```
$FFMPEG / $FFPROBE     explicit override (CI, non-macOS, bisecting a build)
config/ffmpeg.env      what setup.sh wrote (gitignored, per-machine)
PATH                   shutil.which fallback
```

This mirrors an existing pattern rather than inventing one: `catalog.py:23` already keys a
module constant to a generated, gitignored `config/sourcing.env` and reads it with an
environment-variable override, and its tests monkeypatch the module constant. `ffmpeg.env`
is the same shape with the same test seam.

The PATH rung is not decoration. `setup.sh` is macOS/homebrew-only, while the runtime code
is deliberately portable (`fonts.py` `FONT_CANDIDATES` carries Linux paths). On a box where
setup never ran there is no config file, and import must not explode — it should fall
through to PATH and let the capability probes fail loud with a remedy.

**Resolution always yields an absolute path.** The PATH rung goes through `shutil.which`,
not a bare `"ffmpeg"`. Two payoffs: error messages name the exact binary, and a mixed
pipeline (extract with one build, encode with another) becomes visible in the logs instead
of inferred.

## 4. Freeze the path, probe the capabilities

The tempting next step is to have `setup.sh` also record what it verified — `vidstab=yes`,
`drawtext=yes` — and let the runtime read that instead of shelling out. **Rejected**, and
the reason is the distinction this repo already cares about.

A stale **path** fails loud: the file is gone, `subprocess` raises `FileNotFoundError`, and
`proc.run` already converts that into a `RuntimeError` carrying a remedy.

A stale **capability** fails quietly. If the record says `vidstab=yes` and the binary was
since replaced, the code skips its own gate and proceeds on a false premise. That is a
§12-shaped failure — bad output, not a crash — manufactured by an optimisation worth
roughly 30ms.

So: the path is frozen at install, the filters are probed at runtime, every time.

Memoizing the probe was considered and dropped. A process-lifetime cache is *defensible*
— the binary genuinely cannot change under a live process — but it buys back only the
~50ms of an `ffmpeg -filters` spawn, against encodes measured in minutes, and it pays for
that with a stateful trap: any test that forgets `cache_clear()` reads a stale answer and
can pass for the wrong reason. This repo has already shipped four hollow tests found only
by review; adding a mechanism whose failure mode is *a test that passes when it should
not* is a bad trade at any price, let alone this one.

## 5. One capability chokepoint, and the trap it closes

Today three call sites ask the same question four different ways: `draft.ensure_drawtext`
shells out and greps, `intake._require_vidstab` shells out and greps, and three test guards
(`tests/integration/test_intake.py:21`, `test_draft.py:22`, `test_titles.py:21`) each run
their own `subprocess`.

This slice gives them one implementation — `ffbin.has_filter(name) -> bool` — and the
production gates become thin wrappers that add their own remedy text.

**This is the load-bearing part of the slice, not tidiness.** Move production onto
`ffmpeg-full` and leave the three test guards probing PATH, and they will probe the *slim*
binary, find no vidstab and no drawtext, and skip forever — while production works fine.
A green suite, three integration tests silently uncovered. That failure is quiet, which
puts it in the same class as everything in §12, and it is introduced *by* this slice if the
guards are treated as an afterthought. `tests/conftest.py:17`, which builds the shared
sample clip with a direct `subprocess.run(["ffmpeg", ...])`, has the same exposure.

One implementation means one thing to get right and one thing to unit-test, instead of four
copies that can drift apart one at a time.

## 6. `setup.sh` stops being destructive

Both `brew uninstall --ignore-dependencies ffmpeg` branches are deleted outright — not
guarded, not made conditional. With a keg-only formula there is no reason to remove
anything, so the safest version of that code is none of it.

The replacement:

1. `brew install ffmpeg-full` when the binary is absent (idempotent; no-op on rerun).
2. **Verify** `drawtext` and `vidstabdetect` are actually present in the installed binary,
   and that `ffprobe` shipped alongside. Fail loud otherwise.
3. Write `config/ffmpeg.env`.
4. `brew pin ffmpeg-full` — **without** `2>/dev/null || true`. §1 is what that idiom buys.

Step 2 is not ceremony. The formula's dependency list names `freetype` and `libvidstab`,
which is strong evidence but not observation — the binary is not installed yet and has not
been inspected. A setup script that assumes its own success is how §1's silent pin failure
happened. It checks, or it has not finished.

## 7. The literal ban — and what it is honestly worth

`"ffmpeg"` appears as a string literal 27 times and `"ffprobe"` 8 times across 11 files.
(`proc.py` names them twice more, but inside comments — Python never sees those, and
neither does an AST scan, so the guard file needs no exemption.) Once the resolver exists,
a new call site can still type the literal and quietly go back to PATH.
The landmine-lint slice already built an AST scan over `scripts/`, so a fifth check costs
little: **a string literal equal to exactly `"ffmpeg"` or `"ffprobe"` is banned.**

Exact equality, not substring, is what makes the predicate usable. Error messages and
docstrings say the word "ffmpeg" constantly and must stay legal; no prose string is ever
exactly those six characters. This is the same distinction the lint slice already had to
draw between *mentioning* a ban and *emitting* one.

**Classification — this is a convention check, not a §12 landmine, and the spec says so
deliberately.** The tempting story is "wrong binary → silent corruption", but tracing it
through says otherwise: run a drawtext filtergraph on a build without libfreetype and
ffmpeg exits with `No such filter: drawtext`, which `proc.run` turns into a loud
`RuntimeError`. The genuinely quiet failure in this area is the skipping-tests trap, and
§5 closes that at the chokepoint rather than here.

So the check earns its place as regression prevention — it stops a slow drift back to PATH
across future slices — and it belongs in the **AST scan only**. It is deliberately *not*
added to `check_argv`. `check_argv` is chartered for patterns that corrupt output silently,
it runs on every command in production, and widening it with a rule that does not meet that
bar would dilute what a `check_argv` refusal means. Filing this correctly matters more than
filing it impressively: a future reader who believes this check guards against silent
corruption will trust it to do something it does not do.

`ffbin.py` is exempt, because it is the one file that must name the binaries. That is the
same shape as the existing scan's `lint.py` exemption — a hole by construction, pinned to
exactly one file by its own test, so nothing else can hide behind it.

Scope: `scripts/` only, as the existing scan already is.

`tests/` needs a different instrument, and the original version of this section got it
wrong by treating the whole tree as one thing. Three zones, three answers:

- **`tests/integration/`** must run the *same* binary production runs — 37 argv literals
  across 16 files build fixtures and probe outputs. Leaving them on PATH would make the
  suite exercise a configuration no user has, and would specifically hollow out §10's
  golden proof: a golden whose fixture came from one build and whose output came from
  another cannot answer whether the build swap moved pixels. Banned, by a check in
  `test_ffbin.py`.
- **`tests/lib/`** is exempt. `test_lint.py`'s `REAL_SITES` fixtures are *printed output
  from the real builders* — the literals **are** the test data, and resolving them would
  destroy the fixture. `test_proc.py` tests the wrapper's timeout and error handling, not
  the pipeline.
- **Nowhere under `tests/`** may spell ffmpeg's `-filters` flag in an argv, since an
  independent capability probe is precisely §5's trap. `has_filter` is the only way to ask.

That last check had to be built as an **emission** test, not a line scan, for a reason
worth recording: the first draft asserted in its own docstring that the file "never spells
the flag", and that claim was false as written — two docstrings in the same file name
`ffmpeg -filters` in prose, at exactly the place a reader looks to understand the probe.
A scan that banned the characters would have made its own rule undocumentable at its own
site, and could never have gone green.

## 8. Flags

`--with-vidstab` and `--with-fonts` are deleted; both become baseline.

Fonts are the judgment call, since `.ttf` files are not ffmpeg libraries. They fold in
anyway: four small casks, and without them the titles stage fails loud — which is precisely
the "install a second thing later with a flag" this slice removes.

`--with-demucs` stays opt-in. torch is 2–3 GB; that is a real cost axis, not a missing
library. **Superseded twice:** folded into baseline on 2026-08-04 (setup-install-all),
then made **required** on 2026-08-14 (`1871c48`) when the librosa mix-silence fallback
was deleted for answering wrong rather than failing. The flag no longer exists.

`--with-sourcing` keeps the Jamendo key prompt at install time. The **rights/responsibility
choice moves to per-run** — a user can move between jurisdictions, so a decision frozen at
install time is a decision made in the wrong place. That is its own slice (§9), not this
one.

## 9. Out of scope

- **Per-run music rights responsibility.** Touches `catalog.py`, `fetch.py`, and both
  sourcing drivers. Own slice.
- **Applying stabilization** (`vidstabtransform`). `manifest.py:184` still refuses
  `stabilize=true`; this slice only removes the `--with-vidstab` string from its remedy.
  Making vidstab baseline is what *unblocks* that work — it is not that work.
- **Cross-platform `setup.sh`.** Still macOS/homebrew. The PATH rung keeps the runtime
  portable, which is the existing posture.

## 10. Testing

- `lib/ffbin.py` unit tests: each resolution rung in isolation, precedence between them,
  absolute-path guarantee, missing-config fallback, `has_filter` true/false, and the
  fail-loud remedy when nothing resolves.
- The three integration guards and `conftest` move to `has_filter`. On a machine with
  `ffmpeg-full` installed they must **stop skipping**. Measured before the slice: 1512
  passed, 8 skipped — of which 3 `test_draft` + 2 `test_titles` (drawtext) and 1
  `test_intake` (vidstab) are this slice's, and must turn green. The remaining two are
  not: `test_offset` needs demucs, which stays opt-in (§8), and `test_sourcing` fails an
  SSL certificate verification, which is an environment defect unrelated to ffmpeg.
  **The target is 2 skips, and specifically those two.** The passed count is deliberately
  not a criterion: every task adds tests, so it moves, and a figure picked in advance can
  match by coincidence while proving nothing. Check the `-rs` list by identity — a run
  still reporting a drawtext or vidstab skip means the guards are probing the wrong
  binary, the exact trap §5 exists to close, and a count alone cannot see it.
  **As of the code slice landing this is still 8, and that is expected, not a failure:**
  `config/ffmpeg.env` is written by `setup.sh`, which nobody has run yet, so `ffbin`
  resolves the slim PATH build (§1, "what has changed since"). The 2-skip proof is gated
  on the install, not on code.
- Full suite green against `ffmpeg-full`, which is the real test of §2's version argument.
  The goldens are the instrument: if the build swap moves pixels, they say so.
- Mutation checks on the new AST rule: substring-instead-of-equality must fail (it would
  flag every docstring), and deleting the rule must fail.

## 11. Risks

**A filter behaves differently across the two builds.** Same version and revision makes it
unlikely but not impossible — 34 extra libraries change which encoders and scalers exist.
The goldens are the detector, and they run before the slice closes. If one moves, the
finding is a real pixel difference and gets recorded, not re-pinned away.

**The recorded path goes stale** after a `brew upgrade` or cleanup. Fails loud through
`FileNotFoundError`; `proc.run`'s remedy text needs updating to say `bash setup.sh` rather
than `brew install ffmpeg`.

**The user's machine keeps two ffmpeg builds.** Intended, and the reason nothing needs
uninstalling — but `ffmpeg` on their interactive PATH stays the slim one. Anyone debugging
by hand must use the recorded path to reproduce what the pipeline did. The absolute-path
resolution in §3 is what makes that discoverable from a log.

## 12. What the proof actually found (2026-07-20, after `bash setup.sh`)

**Result: 1539 passed, 2 skipped** — exactly the two §10 predicted, `test_offset` (demucs,
opt-in) and `test_sourcing` (an SSL certificate failure unrelated to this slice). The six
drawtext and vidstab skips are gone. §5's trap is closed and, more importantly, *proven*
closed: the guards flipped from skipping to running the moment the resolver found a capable
build, which is exactly what a guard still probing PATH could not have done.

**No golden moved.** §2's "same version, same revision" argument survives its only real
test, and §11's first risk did not materialise.

**What did break was better than a moved golden.** `test_intake_real_vidstab_shake` failed
on its first-ever execution — not a regression, but a bug that had been unobservable since
the shake path was written. `_parse_trf` reads libvidstab's ASCII serializer
(`VID.STAB` header); libvidstab **writes binary by default** (magic `TRF1`). Every machine
this project has ever run on lacked libvidstab, so the only test covering the path was
skipped everywhere, forever, and the disagreement could not surface.

Three things are worth keeping from it.

*The fix is the filter's own option, not a binary reader.* `vidstabdetect` exposes
`fileformat` (`ascii`=1, `binary`=2, default binary). Reverse-engineering the `TRF1` layout
from 104 bytes of a synthetic clip would have risked silently wrong shake magnitudes — the
§12 failure class this repo is built around — to save one filter argument.

*A fail-loud promise can be unreachable.* `_parse_trf`'s docstring promised to refuse an
unrecognized header rather than report `shake=0`, and could not keep it: `read_text()`
raised `UnicodeDecodeError` several frames earlier, naming a byte offset instead of a
remedy. `_read_trf` checks the magic on bytes first so the intended error is reachable.
A guard placed downstream of the thing that actually fails is not a guard.

*This is the argument for the slice, stated as a result.* Making a capability baseline does
not only enable a feature — it makes the tests that cover it **run**, and a test that has
never executed carries no evidence whatsoever, however green the suite looked. Six tests
were in that state; one of them was covering broken code.
