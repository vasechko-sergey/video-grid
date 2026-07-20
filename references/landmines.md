# Landmine registry — pointer

_Last updated: 2026-07-20._

**The registry lives in design spec §12**, in the
[montage skillset design spec][spec]. It is the single canonical list; add
entries there.

This file used to carry a copy that claimed to be verbatim and was not — it had
drifted to 17 entries against §12's 28, and still asserted an `ultralytics` detail
§12 had struck through as never true. A second copy of a safety-critical list is a
second thing to forget to update, so it is now a pointer rather than a duplicate.

## Four entries are machine-checked

`lutrgb`, an input-side `-ss` on a re-encoded window, an unbounded synthesized
lavfi source, and `drawtext` without `fontfile=` can no longer re-enter the
codebase silently. The predicate is [scripts/lib/lint.py](../scripts/lib/lint.py),
enforced at two layers:

- **`proc.run`'s runtime guard** — always on, raises before `subprocess.run`, and
  sees the *assembled* argv including graphs that arrive through a splat.
- **an AST scan of `scripts/`** (`tests/lib/test_landmine_scan.py`) — it reads
  string *literals*, so it measures what a module **emits**, not what it mentions.
  Naming a banned filter in a comment or docstring stays legal at exactly the site
  that documents the ban, which a line-level scan could not allow.

**The rules are narrower than the slogans.** "`-ss` after `-i`" is not the rule
this codebase lives by: a violation needs **five** conditions together (an
input-side seek, a `-t`/`-to` window, no `-accurate_seek`, no `-frames:v`, and not
a stream copy). A naive positional check produces four false positives out of
seven hits on a clean tree — and this guard raises in production, so a false
positive breaks a live render.

**What the lint does not cover is written down.** Ten test-side sites bypass
`proc.run`; runtime coverage equals test coverage; `SYNTH_SOURCES` is a five-entry
denylist that misses at least a dozen other infinite lavfi sources; and the
`drawtext` check has no real-argv corroboration on a machine whose ffmpeg lacks
libfreetype. The full list is [the landmine lint design][lint] §5 — read it
before trusting the lint with anything.

## The rest stays human

Entries like "never stabilize a wade-in shot" are judgment about content, and
nothing in the codebase classifies a wade shot. §12's entries on route synthesis,
path smoothing and ratio-vs-quantity validation are discipline invariants, guarded
by targeted tests rather than by a lint.

[spec]: ../docs/specs/2026-07-05-montage-skillset-design.md
[lint]: ../docs/specs/2026-07-20-landmine-lint-design.md
