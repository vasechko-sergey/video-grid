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

**Violation ⟺ all four hold:**

1. the `-ss` is an *input-side* seek, **and**
2. `-t` or `-to` is present — the command is cutting a *window*, **and**
3. `-accurate_seek` is **not** present, **and**
4. `-frames:v` is **not** present — a still grab is not a cut.

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
`anullsrc`, `anoisesrc`, `sine=` — must be bounded, either by `-t`/`-to` on the output
or by `d=`/`duration=` on every synthesized source. Unbounded is a violation.

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

- **`tests/conftest.py:17` bypasses `proc.run`.** The shared `sample_clip` fixture
  calls `subprocess.run` directly, so the runtime guard never sees it. It is correct
  today (`d=` and `-t`), and it is a genuine blind spot.
- **Runtime coverage equals test coverage.** An unexercised path is unguarded at
  runtime.
- **A splat-assembled graph on an unexercised path is covered by neither layer.**
  Static is blind through the splat; runtime never reaches it. This is the residual
  hole and it is real.
- **The three yt-dlp `subprocess.run` sites** (`scripts/lib/catalog.py:197`, `:254`,
  `scripts/lib/fetch.py:80`) are out of reach — yt-dlp spawns its own ffmpeg child,
  and `catalog.py:255` passes `--download-sections`, an `-ss`-adjacent operation whose
  final argv no lint here can observe.
- **`scripts/draft.py:24` passes the binary as a parameter** (`proc.run([ffmpeg, …])`,
  default `"ffmpeg"`). Harmless today, but it is the template for a future bypass of
  any check keyed on argv[0] being the literal `"ffmpeg"`. The runtime guard therefore
  inspects **every** command it is handed rather than filtering on argv[0].
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
  against §12's 28, and its `ultralytics` entry still asserts something §12 has since
  struck through as "never true". Re-syncing creates a duplicate that will drift again;
  **it becomes a pointer to §12 instead of a copy.** A lint that read its ban list from
  the drifted file would silently under-enforce — the same failure
  `test_reframe.py:438` already confesses to.
