# The shared fake-renderer fixture — one geometry, not two that agree

_Last updated: 2026-09-02_

Closes the P3 row [`backlog.md`](../backlog.md) filed as "a fixture class, one row instead of
four one-offs". Four integration tests each declared a `project.json` canvas their own fake
renderer never honoured; all four were repaired by hand (`8c81fea`, `48eee61`), and nothing
stops a fifth from being written the same way. This slice removes the shape that makes a fifth
possible, rather than repairing a fifth later.

## §0 Why this exists — the defect is a duplicated constant, not a wrong value

The four repairs were each one line, and each was correct. What they did not touch is the
reason all four existed: a test that renders through a fake states its geometry **twice** —
once in the `project.json` it writes, once in the `path.meta.json` its fake writes — and
nothing makes the two agree.

The fake is a plain `-c:v copy`. It takes no crop, and it says so honestly in its own sidecar
(`"canvas": [W, H]`, matching `src_dims`). The `project.json` beside it declared `[1080, 1920]`,
a 9:16 crop nobody rendered. That declaration is not inert: it flows into every episode's
**manifest**, which is what a real `reframe` reads — and, since design 2026-08-31 Task 7, what
`build_reel._predict` reads to predict each episode's colour profile for `check_reel`'s
`grade_faithful` gate.

Two measurements from the repairs, both worth carrying into this design:

- **The declaration is what a gate compares against.** With the drift oracle bypassed to reach
  the comparison, the 9:16 declaration predicts a residual of **1.0** on `test_front_spine.py`'s
  fixture and the source aspect **0.0**. On `test_outro.py`'s fixture the same fiction cost
  **222** against a `grade_residual_max` of 4.0 — a real failure, in a real suite run.
- **Nothing structural separated the four.** `test_outro.py`'s failed and the other three did
  not, purely because of commit order: `8c81fea` is commit 21 of that branch and `9d0bd34`,
  which added `probe._refuse_on_drift` to `_predict`, is commit 22. `grade_faithful` existed for
  exactly one commit with no drift guard; `test_outro.py`'s fixture was rendered through that
  window. Today all four report `no-prediction` — the guard refuses `path.json = [0]` before the
  colour comparison is reached.

The second point is the one that decides the shape of this slice. A fifth copy written tomorrow
would be **born dormant**: green suite, silent gate, defect present. Detection after the fact is
therefore weak here, because the thing to detect does not fail. The fix has to be constructive.

## §1 The shape — the fake owns the geometry, the project reads it

`tests/conftest.py` gains one factory fixture. A test asks for a fake renderer at a given source
size, and gets back an object that both installs the fake and writes the matching project:

```python
def test_something(sample_clip, tmp_path, monkeypatch, fake_render):
    fake = fake_render(monkeypatch, src_dims=(1920, 1080))
    res = edl_to_reel.edl_to_reel(edl, fake.project(tmp_path), ...)
```

The object holds `src_dims` once. `fake.project(tmp_path)` writes `project.json` with
`canvas = list(src_dims)`; the installed fake writes `path.meta.json` from the same attribute;
the route point and crop rect are **derived** from it rather than typed. There is no second
number to keep in step — the declaration and the sidecar are two renderings of one value.

Parameters, one per axis the five existing copies actually vary on (§2):

| parameter | why it exists |
|---|---|
| `src_dims` | `(1920, 1080)` for `sample_clip`, `(640, 360)` for `ramp_clip`/`test_outro` |
| `delivery` | `"native"` or `"long_edge:240"` — carried into `project.json` (and so the manifest) and parsed/validated by `ProjectConfig`/`Delivery.from_spec`, but reaches no encode here: `Delivery.dims()` is called only from the real reframe path (`scripts/lib/layout.py`) and `scripts/draft.py`, never `scripts/deliver.py`, which just probes whatever dimensions the assembled episodes already carry. The fake skips reframe and stream-copies, so the speed these tests get comes from small `src_dims` plus the copy, not from this value (measured 2026-09-02, Task 4: 1.39s pytest-reported both with and without it) |
| `pan_aware` | one fake in `test_front_spine.py` must skip `route.json` for a pan episode |

`purpose` stays `"reel"` — every one of the four uses it, and it is what the router maps to a
platform. It is a constant in the fixture, not a parameter, until a test needs otherwise.

## §2 The census — what is actually duplicated

Measured over `tests/` on 2026-09-02, not estimated:

- **30** test files write a `project.json` carrying a `canvas`.
- **8** of those also install a fake `process_episode`.
- **4** of those call `ffmpeg` inside the fake, i.e. produce a real file whose geometry a real
  gate later reads: `test_front_spine.py`, `test_edit_plan.py`, `test_outro.py`, `test_ramp.py`.

Only the last group can hold this defect at all. The other four fakes (`tests/lib/`,
`tests/test_episode_qc.py`) return dicts and never decode a frame, so a declared-vs-rendered
mismatch is not observable by any gate — there are no rendered pixels to disagree with. They
stay as they are; converting them would be uniformity for its own sake, and would put a
`dict`-only mode into the fixture that no test exercises.

The four files carry **five** fake copies (`test_front_spine.py` has two: a plain one and a
pan-aware sibling). Diffed against each other, they vary on exactly the three axes in §1 and are
otherwise identical — including their prose comments, which have been copied along with the
code and now say "copied from X, dims adjusted" three levels deep.

## §3 What deliberately does NOT move — and why this is half the design

`test_edit_plan.py`'s `_project_json` serves **two incompatible purposes**, which is why
`48eee61` split that file's helper rather than changing it:

- two tests drive `edl_to_reel` behind the fake and need the honest source aspect;
- three pure-`edit_plan` gate tests — `variety-gap`, `delivered-geometry`, `constraints` —
  render no frame at all and need a declared canvas that **deliberately does not match** the
  source. `test_sp3_delivered_geometry_is_what_decides` exists precisely to prove the variety
  gate judges **delivered** geometry: it feeds the same footage a 16:9 project and a 9:16
  project and asserts the verdicts differ.

So the fixture is for tests that render through a fake. The three gate tests keep their local
9:16 `_project_json` and are named in the fixture's docstring as the reason it is not applied
everywhere. A future "let us unify all of these" sweep that ignores that note gets three red
tests — which is the good outcome, and the note is there so it does not get that far.

The asymmetry is worth stating in the same place: a **gate** test wrongly moved to the source
aspect fails loudly (`write_edit_plan` returns a different status, no render involved), while a
**driver** test wrongly left at 9:16 fails silently (`delivered`, with `grade_faithful` quietly
`not-checked`). A green suite is not evidence for the second direction.

## §4 Testing

The fixture is test infrastructure, so its proof is the existing suite: the four files must pass
unchanged in behaviour, and the full suite must stay at its current count (3398 passed, 1
skipped) — a drop means a test stopped running, which is exactly how a fixture refactor fails.

Two things get their own assertions, because both are load-bearing and neither is proven by the
suite going green:

1. **The single source of truth holds.** A test that reads the `project.json` the fixture wrote
   and the `path.meta.json` the fake wrote, and asserts the two canvases are equal — for both
   `src_dims` values. This is the invariant the whole slice buys; it should fail if someone
   later reintroduces a literal.
2. **`pan_aware` really suppresses the route.** `test_front_spine.py`'s two pan tests already
   assert `route is None` and the on-disk absence; those move onto the fixture and keep
   asserting it, so the parameter cannot silently become a no-op.

No new real-ffmpeg golden: this slice renders nothing new, it removes duplicated ways of
declaring the same geometry.

## §5 Out of scope

- The four `dict`-only fakes (§2) — no observable defect, and no consumer for the mode.
- The three gate tests' `_project_json` (§3) — the mismatch there is the point.
- Any change to `grade_faithful`, `_predict`, `probe._refuse_on_drift` or their thresholds. This
  slice touches test scaffolding only; no production file changes.
- The drift oracle's shielding effect itself. It is doing its job; that it also hides this class
  is a property worth knowing, not a defect to fix.

## §6 Honest limits

- **A fixture makes the honest path short, not mandatory.** Nothing prevents a new test from
  writing its own `project.json` beside its own fake, exactly as the four did. This slice
  removes the reason to, and removes the copy-paste source that made it the default move.
- **Nothing checks that a new test uses the fixture.** The row this closes asked for prevention
  of a fifth copy; what it gets is prevention *through* the fixture. A sixth copy written from
  scratch is still writable, and would still be born dormant behind the drift guard (§0).
- **The derived route point is a behaviour change, small but real.** Today's fakes write literal
  route coordinates (`960, 540, 120, 120` and `W//2, H//2, 40, 80`). Deriving them from
  `src_dims` produces the same values for the two existing sizes by construction, but a future
  size gets a computed point nobody has looked at. No current test asserts a route coordinate —
  they assert presence, absence, and file existence — so this is safe today and worth re-checking
  if one ever does.
- **This makes no reel better.** It is scaffolding. Its whole value is that the next person
  writing an integration test cannot cheaply state a geometry their fake does not honour.
