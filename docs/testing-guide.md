# Testing Guide

Testing philosophy and the patterns that matter for video-grid. Adapted from the
anna-auth testing guide to a pytest + real-ffmpeg codebase.

_Last updated: 2026-08-13._

## Philosophy

- **TDD, always.** Write the failing test first, run it, watch it fail for the
  right reason, then write the minimal code to pass. This is enforced per task by
  the execution protocol (see [development-workflow.md](./development-workflow.md)).
- **A unit test for every feature and every bug fix** — never "verified by
  running it once by hand." A bug fix starts with the test that reproduces it.
- Tests guard behavior; the type hints and dataclasses guard shape. A refactor
  (e.g. the type-hint pass) is correct when the suite stays green untouched.

## Key Patterns

- **Assert the whole object, not field-by-field.** One
  `assert result == Report(...)` (or `== expected_dict`) is clearer than a column
  of `assert result.x == ...` lines and catches unexpected changes the field
  asserts would miss. Our dataclasses have value equality — use it.
- **Test the wire round-trip for every contract.** For each
  `from_dict`/`to_dict` (and `from_json`/`to_json`), assert that a round-trip
  reproduces the on-disk schema exactly — this is the contract other scripts and
  future readers depend on.
- **Test both sides of the validation boundary** (see
  [coding-standards.md](./coding-standards.md)): the manifest gate returns
  problems softly (`validate()` → list → `needs_input`); a config-spec raises
  (`pytest.raises(ValueError)`), and the raised message carries a remedy — assert
  on the remedy text, not just the exception type.
- **Golden fixtures run real ffmpeg.** The engine's end-to-end behavior is proven
  on actual footage (`tests/fixtures/golden_ride.mp4`, 1280×720 @ 59.94fps)
  through the real ffmpeg/ffprobe binaries — not mocked. A geometry/aspect change
  is proven cheaply with a mocked-engine shell test; a "does ffmpeg actually
  produce these pixels/dims" claim needs the golden.
- **ffmpeg `drawbox` position expressions are inert under ffmpeg 8.1.1.**
  `drawbox=x='...t...'` evaluates `t` as a constant (`INT32_MAX`), not the frame
  time, so the box never moves/renders — the clip comes out flat. The shared
  `sample_clip` fixture (`tests/conftest.py`) therefore composites its moving box
  with `overlay` (whose position expressions DO evaluate per-frame). Don't
  reintroduce the `drawbox` form. This is a test-fixture issue only; the
  production pipeline doesn't use `drawbox`.
- **Assert on delivered dimensions, not on a hardcoded resolution.** The engine
  is aspect/resolution-agnostic; a delivery test pins the *derived* dims
  (e.g. native 9:16-from-720 → `404×720`), never a stale `1080×1920`.

## Mutation batteries

Plans in `docs/plans/` routinely close with a mutation battery: break the
production code one specific way per row, confirm the named test goes red,
revert by hand, confirm green — "steps, not suggestions" (per each battery's
own framing). A row where nothing goes red is a coverage hole to close with a
new test, not a battery to weaken.

**The `.pyc` hazard.** A mutation that edits a literal to another of the
**same byte length** (e.g. one number for another, `,;]` for `,;\[`) and is
reverted inside the same filesystem second can leave a stale `__pycache__`
entry whose recorded mtime *and* size still validate against the reverted
source file. Python then trusts the cached bytecode, the mutant silently
survives the revert, and every later `pytest` run in that session passes
against code that is no longer on disk — a false "confirmed green" that
proves nothing. Hit during the 2026-08-13 cinematic-look final review.

**Remedy:** clear `__pycache__` before trusting a "reverted, green" result,
and again before the battery's final full-suite run:

```bash
find . -name __pycache__ -exec rm -rf {} +
```

## Markers & Layout

- `tests/lib/` — pure unit tests (no ffmpeg). `tests/integration/` — real ffmpeg,
  the golden ride, and SKILL structural checks.
- Real-ffmpeg tests carry `@pytest.mark.integration`. Iterate fast with
  `-m "not integration"`; **always run the full suite before commit.**
- `pytest.ini` keeps `pythonpath = .` and there is **no `tests/__init__.py`** —
  do not add one (it breaks module resolution).

## Running

```bash
.venv/bin/python -m pytest -q                    # full suite (run before every commit)
.venv/bin/python -m pytest -q -m "not integration"   # fast: skip real-ffmpeg
.venv/bin/python -m pytest tests/lib/test_models.py -v   # one file
```

## Related

- [coding-standards.md](./coding-standards.md) — the fail-loud / validation contract under test.
- [development-workflow.md](./development-workflow.md) — the TDD-per-task execution protocol.
