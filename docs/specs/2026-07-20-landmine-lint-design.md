# Landmine lint — design

_Last updated: 2026-07-20._

Machine-check that the §12 silent-corruption patterns cannot re-enter the emitted
ffmpeg commands. Today the only thing holding them out is review discipline.

Related: design spec [§11 requirements](2026-07-05-montage-skillset-design.md) and
[§12 landmine registry](2026-07-05-montage-skillset-design.md); the run protocol in
[development-workflow.md](../development-workflow.md); test tiers in
[testing-guide.md](../testing-guide.md).

## 1. Why now, and what the charter actually asked for

Three places in the repo commit to building this and none of them did:

- design spec §11, under *"Requirements for the follow-on plans (binding, not
  nice-to-have)"* — "**Executable landmine lint** (recipes plan): lint generated
  ffmpeg commands — grep for `lutrgb`, for `-ss` before `-i`. Machine-checked
  landmines don't recur."
- [build-status.md](../build-status.md) — "a check that the banned patterns
  (`lutrgb`, `-ss` before `-i`) **cannot re-enter the filtergraphs**."
- [the core plan](../plans/2026-07-05-video-grid-core.md) — the same item.

**The two chartered descriptions disagree about mechanism, and the disagreement is
load-bearing.** The spec says "lint generated ffmpeg commands" — that is a *runtime*
scope, the assembled argv on its way to `subprocess`. build-status says "cannot
re-enter the filtergraphs" — that is a *static* scope, the source text. This design
resolves it as **both**, because measurement showed neither one is sufficient (§2).

What protects these patterns today: for `lutrgb`, exactly one test —
`tests/integration/test_reframe.py:436` — which walks five hand-enumerated
`LayoutSpec`s and asserts the literal is absent. Its own comment concedes the flaw:

> "The list is hand-enumerated, so it silently under-covers as the vocabulary
> grows — every filler needs its own entry, not just every mode."

That confession is this slice's charter restated. For `-ss` order, `drawtext`'s
`fontfile=`, and the unbounded-source hang: **nothing at all.**

## 2. Two layers, because neither subsumes the other

This is not hedging between two options. The layers have different completeness
zones, and each is complete exactly where the other is blind.

**Static is *complete* where it applies — not heuristic.** Filter *names* are never
computed anywhere in this repo. Every filter string is a constant, an f-string whose
static portion carries the filter name, or a `join()` over fragments that are
themselves such strings. No site builds a filter name from a variable. So a literal
scan of `scripts/` catches `lutrgb` on **every** emission path, including paths no
test exercises.

**The scan reads string literals out of the AST, not lines of text** — and that is not
a refinement, it is the difference between a scan that can ship and one that cannot.
A line-level scan **cannot distinguish documenting a ban from violating it**, and this
repo documents the ban in exactly the two places a future author would look:
`scripts/lib/color.py:1` ("lutrgb is banned; use mixer") and
`scripts/check_episode.py:56` ("only the seek/lutrgb corruption we're guarding"). Both
would be flagged. The escapes were a path allowlist — forbidden by §6, and rotten the
moment a third file documents the ban — or deleting the documentation, which makes a
landmine undocumentable at its own site. Both are worse than the problem.

Reading the AST dissolves it: comments never enter the AST at all, and docstrings are
subtracted. What remains is exactly the set the completeness argument above covers —
constants, f-strings' static portions, `join()` operands. **The check measures
*emission*, which is what its name always claimed.** Line-scanning measured *mention*,
and the two differ precisely where the codebase is most careful.

**Static is blind through splats.** Three sites hand `proc.run` the return value of a
builder:

- `scripts/reframe.py:381` — `*_filter_args(rl, xexpr, cy, gains, fps, dur)`
- `scripts/deliver.py:76` and `:80` — `*vf, *profile.args()`
- `scripts/mix.py:207` — `*inputs`

`_filter_args` returns `["-vf", …]` or `["-filter_complex", …]` depending on
`rl.fast_path`. Static analysis cannot see through that, and it sits on the crown-jewel
render path.

**Runtime sees the assembled truth.** `scripts/lib/proc.py` `run()` is a perfect choke
point: **all 35 ffmpeg/ffprobe invocations in `scripts/` funnel through it, with zero
exceptions.** Verified three ways — a literal-token sweep for `"ffmpeg"`/`"ffprobe"`,
a `subprocess` sweep, and a sweep for alternate exec paths (`os.system`, `Popen`,
`shell=True`, `check_output`, `check_call`, `os.exec`), the last returning nothing
across `scripts/` and `tests/`. `run()` currently performs **no validation whatsoever**
before `subprocess.run` — it goes straight from `kwargs.setdefault` to exec.

**Runtime's coverage equals test coverage.** A path no test exercises is unguarded at
runtime. That is precisely where static is complete.

## 3. Where the guard lives, and why it is always on

The runtime check goes in `proc.run`, immediately before `subprocess.run`
(`scripts/lib/proc.py:28`).

**It is not gated behind an environment variable.** The obvious argument for gating is
"keep production fast" — that argument is wrong here by two orders of magnitude. The
check is a handful of string scans over a ~20-element list; the command it guards runs
for seconds to minutes. The saving is unmeasurable, and a guard that is off in
production does not protect production. Always on.

**A violation raises.** This follows the repo's fail-loud contract: refusing to run a
command that will silently corrupt the output is strictly better than running it. The
error is a `ValueError` carrying the landmine's name and a remedy, matching the
config-spec convention (`ValueError` with a remedy, not a bare assert).

`ValueError` and not `RuntimeError` deliberately: `proc.run`'s existing `RuntimeError`s
describe *the environment failing* (binary missing, timeout, non-zero exit). A landmine
violation is *the caller being wrong* — a programming error, which is what every
config-spec in `scripts/lib/models.py` raises `ValueError` for.

The guard runs before the `try:` block, so it cannot disturb the existing
`FileNotFoundError` / `TimeoutExpired` / `CalledProcessError` handling.

## 4. The four checks

Scope decision: **the two chartered patterns plus two more of the same class.** All
four are silent-corruption — they produce bad pixels or a hang, not a traceback. The
wider mechanically-checkable set (even `scale=` dimensions, crop-expression length
ceiling, dependency pins) is deliberately **out** — see §7.

### 4.1 `lutrgb` is banned

Any emitted filter string containing `lutrgb` is a violation; `colorchannelmixer` is
the only permitted colour op (§12). Produced in exactly one place today —
`scripts/lib/color.py:24` — and correct there.

Statically complete, per §2.

### 4.2 `-ss` before `-i`, on a re-encoded window

The slogan "`-ss` after `-i`" is **not** the rule that lives in the code. On the
current, clean tree a naive positional check produces **four false positives out of
seven hits**. The real invariant is narrower, and until this design nobody had written
it down.

**Violation ⟺ all five hold:**

1. the `-ss` is an *input-side* seek, **and**
2. `-t` or `-to` is present — the command is cutting a *window*, **and**
3. `-accurate_seek` is **not** present, **and**
4. `-frames:v` is **not** present — a still grab is not a cut, **and**
5. the command is not a stream copy (`-c copy` / `-c:v copy`).

Condition 5 was added after the first implementation, because the message and
docstring both said *re-encoded* window while nothing checked for re-encoding —
a claim asserted but not verified. A `-c copy` fast trim cannot produce this
landmine: there is no re-encode for a boundary to be black at, and such a trim
gives up frame accuracy deliberately. No site combines `-ss` with `-c copy`
today, but `scripts/lib/assembly.py:84`, `scripts/draft.py:66`, `scripts/draft.py:71`
and `scripts/deliver.py:81` already stream-copy; the first one to gain a window
would have raised mid-render.

**Condition 1 is "some `-i` appears after this `-ss`", not "before the first `-i`".**
The two agree on every command in the tree today and diverge on multi-input commands,
where ffmpeg binds `-ss` to the input that follows it: in `-i a -ss 5 -i b` the seek is
input-side for `b`, and a "before the first `-i`" test would wrongly read it as an
output seek. That is a false negative — the direction a lint must never fail in.
`scripts/mix.py:207` already builds multi-input commands, so this is not hypothetical.

Condition 3 is not an invented escape hatch: §12's own entry lists three remedies for
this landmine — "correct seek-arg order (`-ss` after `-i` / output seek,
`-accurate_seek`, re-encode the window for frame accuracy)". `-accurate_seek` is one of
them, and `scripts/mix.py:193` uses it deliberately.

Condition 4 encodes the carve-out already written at `scripts/storyboard.py:30-31`:

> "The design §12 `-ss after -i` landmine is a different failure: black frames at a
> CUT/re-encode boundary. Grabbing one still deep inside a clip is not a cut."

Verified against every `-ss` site in the tree:

| Site | `-ss` before `-i` | `-t`/`-to` | `-accurate_seek` | `-frames:v` | Verdict |
|------|:-----------------:|:----------:|:----------------:|:-----------:|---------|
| `scripts/extract.py:18` | no | yes | — | — | clean |
| `scripts/check_reel.py:65` | no | — | — | yes | clean |
| `scripts/storyboard.py:36` | yes | **no** | no | yes | exempt — not a window |
| `scripts/mix.py:193` | yes | yes | **yes** | no | exempt — §12's own remedy |
| `scripts/check_episode.py:24` | `-sseof` | — | — | — | exempt — different option |
| `tests/integration/test_titles.py:36` | yes | **no** | no | yes | exempt — not a window |
| `tests/integration/test_pan.py:42` | `-sseof` | — | — | — | exempt — different option |

**Zero false positives, and every exemption is earned by a property of the command
itself — never by an allowlist of file paths.** An allowlist would rot the moment a
new call site appeared; a predicate over the argv does not.

**Token comparison must be exact, never substring.** `-sseof` contains `-ss`, must
precede `-i` by ffmpeg's own contract, and is a different option entirely. A substring
match flags it, which is a bug in the lint, not a finding.

### 4.3 An unbounded synthesized source

A command whose filtergraph contains a synthesized lavfi source — `color=`, `testsrc`,
`anullsrc`, `anoisesrc`, `sine=` — must be bounded, either by a `-t`/`-to` **anywhere in
the argv** or by `d=`/`duration=` on every synthesized source. Unbounded is a violation.

**"Anywhere in the argv", not "on the output" — and the loose reading is the correct
one.** ffmpeg binds `-t` to whatever follows it, so a `-t` ahead of an `-i` is an *input*
option. `scripts/mix.py:137` ships exactly that shape: `-t 18.0` sits before the lavfi
`-i`, binding to that input, and it bounds the source perfectly well. A predicate
insisting on an output `-t` would raise on a shipped command — the direction §6 forbids.
The price of the loose reading is a miss, recorded in §5: the check cannot tell *which*
input a `-t` binds to, so a multi-input command can satisfy it and still hang.

**This check closes the hang, not the length. Saying otherwise would overclaim.**

§12's entry carries two distinct failures:

- **The hang.** An unbounded synthesized source never sends end-of-stream, so the
  encode runs until something kills it — measured at 90s-and-killed against a 0.8s
  normal run, on a machine with no `timeout(1)` to bound it from outside. Prevented by
  either `d=` or `-t`.
- **The wrong length.** `d=` on a `color` source yields a frame count that need not
  match the real input's (96 rendered against a source's 95). Prevented only by
  bounding the *output* with `-t`.

Requiring `-t` unconditionally would fire on `scripts/mix.py:109`, where `anoisesrc`
carries `d={_SFX_DUR}` and that `d=` **is** the definition of the whoosh's length —
there is no real input for it to mismatch. That is a false positive on correct code.

So the lint takes the hang, and the length stays pinned where it already is:
`test_reframe_bounds_every_layout_to_the_source_length`. Two different failures, two
different guards, both kept. The existing test is **not** superseded and must not be
deleted.

Current sites, all clean under this rule: `scripts/reframe.py:257` (`d=` **and** an
output `-t`), `scripts/mix.py:75` (`anullsrc` with no `d=`, bounded by `-t`),
`scripts/mix.py:109` (`d=`), `tests/conftest.py:17` (`d=` and `-t`).

### 4.4 `drawtext` without `fontfile=`

Any emitted `drawtext=` fragment must carry `fontfile=`. §12: without an explicit font
path, drawtext fails or picks garbage on macOS — the filter and the font are decoupled.

Two producers, `scripts/lib/draft.py:28` and `scripts/lib/titles.py:148`, neither
guarded by anything but review today.

## 5. What this lint does NOT cover

Named here because a lint that is believed to cover more than it does is worse than no
lint — it converts an unexamined risk into a false sense of safety.

- **Ten test-side sites bypass `proc.run`**, calling `subprocess.run` directly, so the
  runtime guard never sees them: `tests/conftest.py:17`,
  `tests/integration/test_extract.py:8`, `test_intake.py:24`, `test_layouts.py:33`,
  `:49`, `:97`, `test_reframe.py:10`, `:18`, `test_verify.py:170`, `:196`.

  Most are read-only probes — ffprobe queries and raw-frame grabs — which cannot carry
  these landmines. The one that genuinely emits a filtergraph is **`conftest.py:17`**,
  the session-scoped `sample_clip` fixture that feeds roughly twenty tests: two `color=`
  lavfi sources composited through `overlay`. It is correct today (`d=` on both sources
  **and** an output `-t`), and it is a real blind spot — the fixture every pixel proof
  in the suite is measured against is the one command the guard cannot see.

  This is the production/test asymmetry stated plainly: `scripts/` funnels through one
  choke point, `tests/` does not have to.

  **That choke point is itself machine-checked** — `tests/lib/test_landmine_scan.py`
  refuses any module under `scripts/` that imports `subprocess`, except the allowlist
  `_MAY_IMPORT_SUBPROCESS` (`proc.py`, plus `catalog.py` and `fetch.py`, the documented
  yt-dlp sites below). Design §2's claim that all 35 invocations funnel through
  `proc.run` was hand-verified at design time; in a slice whose whole thesis is
  machine-checking, the assumption the runtime layer *stands on* should not have been
  the one thing left to prose.

  **`_MAY_IMPORT_SUBPROCESS` is the authority on that list, not this section.** Widening
  it widens what the runtime layer cannot see, so the constant carries the reasoning and
  this paragraph points at it. Two copies of "what the lint does not cover" would drift
  — which is precisely the failure §9 records `references/landmines.md` already
  committing, and there is no reason to repeat it inside the fix.

  The check is import-level by design: `os.system` cannot be caught this way, because
  `os` is imported legitimately almost everywhere. `subprocess` is the realistic bypass.
- **Runtime coverage equals test coverage.** An unexercised path is unguarded at
  runtime.
- **A splat-assembled graph on an unexercised path is covered by neither layer.**
  Static is blind through the splat; runtime never reaches it. This is the residual
  hole and it is real.

- **The static layer sees literals, not every route a name could take.** Because it
  reads AST string constants (§2), a filter name assembled by `%`, `.format()`, string
  concatenation of single characters, or `chr()` arithmetic would pass it. No such site
  exists — every filter string in `scripts/` is a constant, an f-string, or a `join()`
  over those — so the completeness claim holds *for this codebase as it stands*, which
  is the only claim worth making. It is not a claim about Python in general, and the
  day someone builds a filter name a new way, the static layer stops covering it
  silently. Runtime still would, on any path a test reaches.
- **The three yt-dlp `subprocess.run` sites** (`scripts/lib/catalog.py:197`, `:254`,
  `scripts/lib/fetch.py:80`) are out of reach — yt-dlp spawns its own ffmpeg child,
  and `catalog.py:255` passes `--download-sections`, an `-ss`-adjacent operation whose
  final argv no lint here can observe.
- **`scripts/draft.py:24` passes the binary as a parameter** (`proc.run([ffmpeg, …])`,
  default `"ffmpeg"`). Harmless today, but it is the template for a future bypass of
  any check keyed on argv[0] being the literal `"ffmpeg"`. The runtime guard therefore
  inspects **every** command it is handed rather than filtering on argv[0].
- **`SYNTH_SOURCES` is a five-entry denylist and it under-covers.** It names
  `color=`, `testsrc`, `anullsrc`, `anoisesrc`, `sine=` — the five this repo
  actually uses. ffmpeg has many more infinite sources, and every one of them
  reads clean: `nullsrc`, `aevalsrc`, `rgbtestsrc`, `yuvtestsrc`, `smptebars`,
  `gradients`, `cellauto`, `life`, `mandelbrot`, `allrgb`, `allyuv`,
  `haldclutsrc`. **`nullsrc` deserves singling out — it is one keystroke from
  `anullsrc`, which *is* covered.**

  Five is a defensible v1 and the direction is safe (a miss, never a false
  positive). Leaving this unsaid would not be: it is structurally the same flaw
  §1 quotes `test_reframe.py:438` confessing to — "silently under-covers as the
  vocabulary grows." A lint whose denylist is believed complete is exactly the
  false sense of safety this section exists to prevent.

- **A parameterless synthesized source is not detected.** `color=` and `sine=`
  carry a trailing `=` (to disambiguate `color=` from `colorchannelmixer` and
  friends), so the legal, infinite `-f lavfi -i color` and `-f lavfi -i sine`
  read clean. The asymmetry with the other three entries is a deliberate
  disambiguation trade-off, recorded here because the code cannot express it.
  The other three are anchored on their right-hand side instead — a name must be
  followed by `=`, an element separator, or nothing — which is what stops
  `-i testsrc.mp4` being read as a source.

- **One `-t` anywhere silences the check for the WHOLE command.** §4.3 explains
  why the reading has to be that loose. The consequence is a real miss: a command
  that bounds input #1 and leaves an unbounded lavfi input #2 reads clean —
  measured — and would still hang, because the `-t` never applied to the
  infinite source. Closing it needs argv-position parsing (which `-i` does this
  `-t` bind to?) that the predicate does not attempt. No site in the tree has
  that shape today, which is why this is recorded rather than fixed.

- **`drawtext` has no real-argv corroboration on this machine.** §8's "the real
  call sites are fixtures" reasoning does not transfer to §4.4 here: this
  machine's ffmpeg is built without `libfreetype`, so all five drawtext
  integration tests skip and **not one** `drawtext=` argv reaches the predicate
  across the whole suite. `_drawtext_font` is pinned by its unit tests and by
  reading both producers, not by measurement. A drawtext-capable ffmpeg
  (homebrew-core's `ffmpeg-full`, which also carries libvidstab) would close this.

- **A fontless `drawtext` is missed when a LATER filter in the same argv element
  carries `fontfile=`.** The check splits on `drawtext=` and asks whether the
  following segment contains `fontfile=`, but that segment runs to the end of the
  *argument*, not to the end of that filter — so a downstream
  `subtitles=…:force_style='fontfile=…'` answers on the fontless drawtext's
  behalf. Measured:
  `drawtext=text='a',subtitles=f.srt:force_style='fontfile=/f.ttf'` → **0
  violations**. A miss, so the safe direction, and not live — deliver's chain is
  the whole `-vf` and both producers put `fontfile=` first — but it is
  structurally the same "the segment is wider than the filter" defect §6 records
  for the `d=` bound test, which was a silent miss swallowing a false positive.

- **The converse is a false positive: a literal `drawtext=` inside a quoted
  `text=` value is counted as a second filter and flagged.** Measured:
  `drawtext=fontfile='/f.ttf':text='use drawtext=here'` → **1 violation** on a
  correct command. Unreachable today only because both producers
  (`scripts/lib/draft.py:28`, `scripts/lib/titles.py:148`) route free text through
  `textfile=` rather than `text=` — and they do that for filtergraph escaping, not
  for this. `_drawtext_font`'s own docstring already warns of it; it belongs here
  too, because §5 is the section a reader consults for what this thing gets wrong,
  and a false positive is the class §6 ranks worst. A producer that ever inlines
  `text=` needs a real parser, not a wider split.

- **The judgment-call landmines stay judgment calls.** "Never stabilize wade-in/out
  shots" cannot be mechanically checked — no static or runtime predicate can know which
  shot is a wade-in, and nothing in the codebase classifies one (`grep -rn wade
  scripts/ tests/` returns nothing). §12's entries on route synthesis, path smoothing,
  and ratio-vs-quantity validation are likewise discipline invariants; §12's own
  smoothing entry prescribes the only test shape that works, which is a targeted test,
  not a lint.

## 6. Landmines this slice must itself avoid

- **The lint module defines the banned tokens, so it would flag itself.** The static
  scan skips the file that declares the constants (`scripts/lib/lint.py`). That skip is
  a hole by construction, so it is pinned by a test that plants a violation in a
  *different* file and asserts the scan still catches it — the skip must be one file
  wide, not a wildcard.
- **The static scan covers `scripts/` only, not `tests/`.** Scanning tests would flag
  the existing ban assertions (`assert "lutrgb" not in args[1]`), which legitimately
  contain the literal. Tests are covered at runtime instead, through `proc.run`.
- **A false positive breaks a live render.** The guard raises in production. This is
  why §4.2's predicate was verified against all seven real sites before being written
  down rather than derived from the slogan.
- **Substring matching on option tokens is wrong** (§4.2). `-sseof` is the live
  example; `-ss` is a prefix of it.
- **Two bugs in one check can mask each other, and fixing either one alone makes
  things worse.** Found during implementation, and it is the sharpest lesson here.
  §4.3's first cut had two defects: the source-name boundary admitted `color=`
  after any non-word character (so `drawbox=…:color=red` and `pad=…:color=black`
  read as *sources*), and the bound test asked whether `d=` appeared anywhere in
  the **whole argument** rather than in the source's own element.

  The second bug hid the first. **`pad=` contains the substring `d=`** — so any
  argument carrying a letterbox filter looked "bounded" and was exempted wholesale,
  which is also why the predicate appeared to survive `pad=…:color=black` when it
  did not. The two failures pointed opposite ways: the boundary bug was a false
  positive, the bound bug a silent miss, and the miss was swallowing the false
  positive.

  Fixing only the bound test would have converted `pad` from a quiet miss into a
  **live raise on every letterbox render** — a new broken render shipped as a fix.
  The two corrections had to land together, boundary first, so that every commit
  is green on its own.

  The generalisable form: **when a check has an early exemption and a detector, a
  bug in the exemption can conceal a bug in the detector.** Neither unit tests nor
  the mutation battery caught this pair — both mutation rows passed against a
  predicate that was wrong in two places. What caught it was running the predicate
  over every argv the real suite issues (702 of them) and looking at what it
  flagged. **Measure the predicate against the codebase, not only against its own
  fixtures.**

## 7. Deliberately out of scope

The wider mechanically-checkable set from §12 — even `scale=` dimensions, the
crop-expression knot ceiling, `pythonpath = .` in `pytest.ini`, an AST rule against
truthiness on dict-valued optionals, dependency pins — is **not** in v1.

Rationale is not uniform, and that matters: the even-dimensions and crop-expression
entries fail **loud** (libx264 refuses an odd width; ffmpeg's parser rejects an
over-long expression). They are worth guarding eventually, but they are a different
class from the four here, none of which announce themselves. Adding them would dilute
the slice's claim: *this lint catches the landmines that do not fail loud.*

Also out: a check asserting stabilization's refusal layers stay in place. It was
considered and rejected — stabilization's shape is under active revision, and a guard
pinning refusals that are about to be removed would be born stale.

## 8. Testing

Per [testing-guide.md](../testing-guide.md), all of this is unit tier — the pure
functions take an argv list, and the source scan reads `.py` files. Neither needs
ffmpeg, so nothing here carries `@pytest.mark.integration`.

- **`tests/lib/test_lint.py`** — the pure predicate. Each of the four checks gets both
  a violating argv and a clean one. §4.2 gets one test per exemption condition, so a
  mutation removing any single condition turns exactly one test red.
- **The seven real sites are fixtures.** Their argv shapes are asserted clean. This is
  the regression guard that matters: it is what proves the predicate matches the
  codebase rather than the slogan.
- **`tests/lib/test_landmine_scan.py`** — the static scan over `scripts/`, plus the
  planted-violation test from §6 that pins the self-exemption to one file.
- **`proc.run`'s guard** is pinned by a test that hands it a violating argv and asserts
  it raises **before** reaching `subprocess.run` (a monkeypatched `subprocess.run` that
  fails if called at all — the same shape §12's smoothing entry prescribes, and for the
  same reason: asserting on the outcome would pass for the wrong cause).

## 9. In-scope corrections found while designing

Both are drift the lint would otherwise inherit or contradict.

- **`tests/integration/test_pan.py:41` states the rule backwards** — its comment says
  the banned pattern is "`-ss` AFTER `-i`", the reverse of every other source in the
  repo. Introduced by the pan slice (2026-07-19). A comment that inverts a landmine is
  worse than no comment.
- **`references/landmines.md` claims to be verbatim from §12 and is not** — 17 entries
  against §12's 26, and its `ultralytics` entry still asserts something §12 has since
  struck through as "never true". Re-syncing creates a duplicate that will drift again;
  **it becomes a pointer to §12 instead of a copy.** A lint that read its ban list from
  the drifted file would silently under-enforce — the same failure
  `test_reframe.py:438` already confesses to.
