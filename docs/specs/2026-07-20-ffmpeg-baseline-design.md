# ffmpeg baseline — one build, all libraries, resolved from a generated constant

_Last updated: 2026-07-20._

Install once, get every library the pipeline needs. No capability flags, no second install
step, no `setup.sh` branch that uninstalls a working binary to get a filter back.

Related: [landmine lint](2026-07-20-landmine-lint-design.md) (the AST scan this slice extends),
[footage intake](2026-07-12-footage-intake-design.md) (the repo's first vidstab consumer),
[assemble-draft](2026-07-13-assemble-draft-design.md) and [titles](2026-07-13-titles-design.md)
(the drawtext consumers).

## 1. What is broken

Measured on the development machine, 2026-07-20.

The installed `ffmpeg` is homebrew-core 8.1.2_1, configured with 13 `--enable-*` switches.
It carries **neither `libfreetype` nor `libvidstab`**:

```
$ ffmpeg -hide_banner -filters | grep -c drawtext   # 0
$ ffmpeg -hide_banner -filters | grep -c vidstab    # 0
```

So two shipped stages are dead on this box — §5.9 assemble-draft (drawtext labels) and
§5.16 titles — and footage-intake's shake measurement cannot run. Three integration tests
skip permanently.

Three separate defects follow from how `setup.sh` tries to fix that.

**The drawtext branch is destructive and not opt-in.** `setup.sh:53-61` fires whenever
drawtext is missing — which is now — and runs `brew uninstall --ignore-dependencies ffmpeg`
before installing a tap build. `brew uses --installed ffmpeg` reports `openai-whisper` and
`summarize`; the build is `--enable-shared`. Removing it with `--ignore-dependencies` leaves
both dependents linked against libraries that no longer exist. **A bare `bash setup.sh` on
this machine today would break two unrelated tools and swap the ffmpeg the goldens were
pinned against.**

**The pin never took.** `setup.sh:119` runs `brew pin ffmpeg 2>/dev/null || true`.
`brew list --pinned` is empty. The comment above that line claims the pin exists to stop
version drift from moving the goldens; it has never once applied. A pin that cannot fail is
not a pin — the `|| true` swallowed whatever went wrong, forever.

**The vidstab branch repeats the same destructive dance** under `--with-vidstab`, so a user
following the documented remedy pays the uninstall twice.

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
library.

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
