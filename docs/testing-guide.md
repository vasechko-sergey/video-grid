# Testing Guide

Testing philosophy and the patterns that matter for video-grid. Adapted from the
anna-auth testing guide to a pytest + real-ffmpeg codebase.

_Last updated: 2026-07-09._

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
- **Assert on delivered dimensions, not on a hardcoded resolution.** The engine
  is aspect/resolution-agnostic; a delivery test pins the *derived* dims
  (e.g. native 9:16-from-720 → `404×720`), never a stale `1080×1920`.

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
