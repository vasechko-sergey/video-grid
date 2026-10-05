"""Real-ffmpeg proofs for the threshold-surface slice (design
docs/specs/2026-09-30-threshold-surface-design.md §5).

Everything under tests/lib argues this slice with fakes; these are the tests that run the
real thing. The episodes are the committed `golden_ride.mp4` re-exposed (the
`test_grade_shipped_pixels` fixture, imported and not copied), so `process_episode`,
`reframe`, `check_episode`, `build_reel`, `check_reel` and `deliver` all run for real. Only
the tracker is stubbed, with the committed `golden_route.json`, exactly as there.

Why not `fake_render`: its fake `process_episode` takes no `gates=` and never runs
`check_episode`, so there would be no report for an `authored` row to land in. A proof of
THIS slice needs the real check on the real pixels.

Every proof drives **phase 1b** (`edl_to_reel.render_from_geometry`, `--from-geometry`). It is
the arm the router renders through, and it does not go through `_phase_one_setup`, so a slice
wired only into the single-pass and geometry arms would pass every test that never reaches it
while doing nothing on the real path (design §2.3: `_run_pool` has three callers, and this is
the third). GATES.json is written AFTER phase 1a has run, in every proof: the file is found at
RUN time (design §2.3), and a document frozen into GEOMETRY.json at 1a would pass a test that
wrote it first.

Each proof carries the control that must not move. A verdict alone cannot tell "the authored
value arrived" from "it passed anyway", so the proofs that judge a verdict move the bar in the
FAILING direction and then show the same pixels passing at the default — and read the bar back
off the check's own detail, which echoes the one it judged by.
"""
import dataclasses
import json
from pathlib import Path

import pytest
from scripts import build_reel, edl_to_reel, match_grade
from scripts.lib import provenance as prov_lib
from scripts.lib.models import ReelCheckSpec, ReelManifest
# `tests/` is what pytest puts on sys.path (tests/integration is a package, tests/ is not), so
# this is the sibling module's import path. Imported and not copied, as test_grade_shipped_pixels
# itself does with `_banded_episode`: a second copy of `_run` would drift from the fixture whose
# route, canvas and window geometry every number below was measured on.
from integration.test_grade_shipped_pixels import DARK, BRIGHT, _geometry, _render, _run

pytestmark = pytest.mark.integration

# A legal, mild grade whose luma-entropy ratio sits BETWEEN the default floor (0.90) and the
# authored one (0.999) — which is the whole reason a floor of 0.999 can fail it. An ungraded
# episode CANNOT be failed that way: its graded and plain renders are the same render, so the
# ratio is exactly 1.0 and `1.0 < floor` is false for every floor in (0, 1]. Measured on this
# footage: highlight 0.7 reads 0.963 — 0.063 clear of the default and 0.036 clear of the
# authored floor, so neither side is a rounding call. The proof asserts that the ratio lands
# between the two floors instead of assuming it, so a drifted fixture fails loudly.
_MILD_GRADE = {"highlight": 0.7}

_WHY_FLOOR = "deliberately unreachable, to prove the bar moved"
_WHY_TIGHT = "tighter than the 1-code residual the conductor's own pairs leave, to prove the bar moved"
_WHY_LOOSE = "loosened to a bar this reel clears, to see the reason beside a PASS"


def _gates(tmp_path: Path, doc: dict | str) -> Path:
    """GATES.json beside project.json — where `edl_to_reel` finds it, with no flag."""
    p = tmp_path / "GATES.json"
    p.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    return p


def _report(ctx: dict, i: int = 0) -> dict:
    """Episode `i`'s report.json as it sits on disk — not as a driver returned it. A row
    attached after `Report.write` is in memory and nowhere a reader looks."""
    return json.loads((Path(ctx["work"]) / f"ep{i}" / "report.json").read_text())


def _phase_1b(ctx: dict) -> tuple[ReelManifest | None, dict | None]:
    """`edl_to_reel --from-geometry`, as the router runs it: (rm, None) or (None, the stop)."""
    return edl_to_reel.render_from_geometry(ctx["geometry"], ctx["project"],
                                            ctx["work"], ctx["out"])


def _two_exposure_reel(tmp_path, monkeypatch) -> dict:
    """The reel the reel-scope proof and the control both start from: two exposures, geometry
    frozen (phase 1a), the conductor's tone pair authored on each. The pairs are what give
    `grade_faithful` something to measure — an ungraded episode's residual is exactly 0.0,
    which no positive bar can fail."""
    ctx = _run(tmp_path, monkeypatch, [(DARK, {}), (BRIGHT, {})])
    _geometry(ctx)
    assert match_grade.write_match(ctx["geometry"])["authored"] == 2
    return ctx


def _episodes_json(ctx: dict, rm: ReelManifest) -> Path:
    """EPISODES.json, written the way the CLI's --from-geometry arm writes it (`rm.write`)."""
    p = Path(ctx["out"]) / "EPISODES.json"
    rm.write(p)
    return p


# --- Proof 1: the episode scope, through phase 1b, to the report on disk -------------

def test_an_authored_entropy_floor_changes_the_bar_end_to_end(tmp_path, monkeypatch):
    """design §5, first bullet. GATES.json authors `entropy_floor`; the episode the render
    just produced is judged against it, and the report on disk names the bar and the reason
    beside the verdict they bought.

    CONTROL, and it carries the weight: the SAME episode, the SAME geometry, rendered first with
    no GATES.json. It passes at the default 0.90 with the very ratio the authored run then
    fails — so the verdict flipped because the bar moved and for no other reason, which a run
    that only existed in the authored form could never show."""
    ctx = _run(tmp_path, monkeypatch, [(DARK, dict(_MILD_GRADE))])
    _geometry(ctx)                                       # phase 1a: no GATES.json exists yet

    _render(ctx)                                         # the control; asserts the episode passed
    ok = _report(ctx)["checks"]["grade_damage"]
    assert ok["pass"] is True and ok["floor"] == 0.90 and "authored" not in ok, ok
    assert 0.90 < ok["ratio"] < 0.999, ok                # between the two floors: the precondition

    _gates(tmp_path, {"entropy_floor": {"value": 0.999, "why": _WHY_FLOOR}})
    rm, stop = _phase_1b(ctx)
    # same footage, same grade, a bar moved the WRONG way
    assert rm is None
    assert stop["finding"] == {"reason": "episode-failed", "episode_idx": 0,
                               "sub_status": "escalate"}, stop
    assert stop["sub"]["reason"] == "grade-damage", stop["sub"]
    assert stop["sub"]["fail_reasons"] == ["grade_damage"], stop["sub"]   # and nothing else failed

    checks = _report(ctx)["checks"]
    gd = checks["grade_damage"]
    assert gd["pass"] is False
    assert gd["floor"] == 0.999                          # the bar the check judged by
    assert gd["ratio"] == ok["ratio"]                    # the pixels did not move; only the bar
    # NOTE: CheckResult.to_dict FLATTENS the detail ({**detail, "pass": ...}), so on disk the
    # keys are checks[name]["authored"] and checks[name]["pass"], not nested under "detail".
    assert gd["authored"] == [{"field": "entropy_floor", "value": 0.999, "default": 0.90,
                               "why": _WHY_FLOOR}]
    # the reason sits beside the verdict it bought and beside no other
    assert [n for n, c in checks.items() if "authored" in c] == ["grade_damage"]


# --- Proof 2: the reel scope, across the EPISODES.json round trip into build_reel -----

def test_an_authored_reel_bar_survives_the_episodes_json_round_trip(tmp_path, monkeypatch):
    """design §5, second bullet. Phase 1b writes EPISODES.json; `build_reel` is then handed
    ONLY that file — it never sees project.json — so a bar that did not ride the manifest is
    gone. `grade_residual_max` is the bar judged here, on real pixels: each conductor-graded
    episode reads a 1-code residual against the profile its own declared chain predicts.

    The one document also carries an episode-scope bar and a reel-scope bar this silent reel
    never judges (`loudness` is not-checked without audio). The first proves the WHOLE set
    rides the manifest and reaches every episode, not just the reel subset (§2.3); the second
    that a bar no check read reports as having shaped nothing.

    Three legs on one frozen EPISODES.json. (1) The authored bar fails the reel, with the
    reason beside the verdict. (2) CONTROL: the same manifest with its gates emptied, through
    the same `build_reel` — it delivers at the default 4.0 with the SAME residual, so the
    verdict moved with the bar and the pixels did not. (3) The bar loosened to one the reel
    clears: it delivers, the reason sits beside a PASS, and the attestation records the gate
    with its scope — the one place this file reads that record when it is present, which is
    what lets proof 4 assert it absent."""
    ctx = _two_exposure_reel(tmp_path, monkeypatch)
    doc = {"grade_residual_max": {"value": 0.5, "why": _WHY_TIGHT},
           "loudness_tol": {"value": 2.0, "why": "carrier only: a silent reel never judges it"},
           "entropy_floor": {"value": 0.85, "why": "episode scope, rides the same document"}}
    _gates(tmp_path, doc)
    rm, stop = _phase_1b(ctx)
    assert stop is None, stop

    for i in (0, 1):                                     # the episode-scope half, on EVERY episode
        gd = _report(ctx, i)["checks"]["grade_damage"]
        assert gd["floor"] == 0.85, (i, gd)
        assert gd["authored"] == [{"field": "entropy_floor", "value": 0.85, "default": 0.90,
                                   "why": doc["entropy_floor"]["why"]}], (i, gd)

    episodes = _episodes_json(ctx, rm)
    raw = json.loads(episodes.read_text())
    assert raw["gates"] == doc                                   # the whole set, both scopes
    assert all("gates" not in e["manifest"] for e in raw["episodes"])   # a run policy, not a cut
    assert {o["field"]: o for o in raw["provenance"]["overrides"]} == {
        "loudness_tol": {"field": "loudness_tol", "value": 2.0, "default": 1.0},
        "grade_residual_max": {"field": "grade_residual_max", "value": 0.5, "default": 4.0}}

    reloaded = ReelManifest.from_json(episodes)
    assert reloaded.gates == doc
    assert reloaded.check_spec.grade_residual_max == 0.5
    assert reloaded.check_spec.loudness_tol == 2.0

    # leg 1: the authored bar, from the file alone
    reel_work = str(Path(ctx["work"]) / "reel")
    res = build_reel.build_reel(reloaded, ctx["deliveries"], reel_work)
    assert res["status"] == "stop_and_report", res
    assert res["finding"]["check"] == "grade_faithful", res["finding"]
    assert not list(Path(ctx["deliveries"]).glob("REEL_v*.mp4"))   # nothing shipped
    checks = json.loads((Path(reel_work) / "reel_report.json").read_text())["checks"]
    gf = checks["grade_faithful"]
    assert gf["pass"] is False
    assert gf["max"] == 0.5                                      # the bar it judged by
    assert gf["worst"] > 0.5
    assert gf["authored"] == [{"field": "grade_residual_max", "value": 0.5, "default": 4.0,
                               "why": _WHY_TIGHT}]
    assert "authored" not in checks["loudness"]                  # authored, never judged

    # leg 2: the control
    ok = build_reel.build_reel(dataclasses.replace(reloaded, gates={}), ctx["deliveries"],
                               reel_work)
    assert ok["status"] == "delivered", ok
    gf0 = ok["report"]["checks"]["grade_faithful"]
    assert gf0["pass"] is True and gf0["max"] == 4.0 and "authored" not in gf0, gf0
    assert gf0["worst"] == gf["worst"]

    # leg 3: the reason beside a PASS, and the attestation of the reel that bar judged. The
    # manifest is the loaded one with a looser bar, so its `provenance.overrides` is still the
    # tight run's — and the attestation's gates must follow the manifest that judged the reel,
    # not provenance, which is how build_reel derives them (see its `prov["gates"]` site).
    loosened = {**doc, "grade_residual_max": {"value": 3.0, "why": _WHY_LOOSE}}
    lax = build_reel.build_reel(dataclasses.replace(reloaded, gates=loosened),
                                ctx["deliveries"], reel_work)
    assert lax["status"] == "delivered", lax
    gf3 = lax["report"]["checks"]["grade_faithful"]
    assert gf3["pass"] is True and gf3["max"] == 3.0, gf3
    assert gf3["authored"] == [{"field": "grade_residual_max", "value": 3.0, "default": 4.0,
                                "why": _WHY_LOOSE}]
    attested = json.loads(prov_lib.attest_path(lax["output"]).read_text())["gates"]
    assert {g["field"]: g for g in attested} == {
        "grade_residual_max": {"field": "grade_residual_max", "value": 3.0, "default": 4.0,
                               "scope": "reel", "blocking": True, "why": _WHY_LOOSE},
        "loudness_tol": {"field": "loudness_tol", "value": 2.0, "default": 1.0,
                         "scope": "reel", "blocking": True,
                         "why": "carrier only: a silent reel never judges it"},
        "entropy_floor": {"field": "entropy_floor", "value": 0.85, "default": 0.90,
                          "scope": "episode", "blocking": True,
                          "why": "episode scope, rides the same document"}}


# --- Proof 3: the six refusals, through the real entry point -------------------------

def test_every_refusal_fires_end_to_end_with_the_path_in_the_message(tmp_path, monkeypatch):
    """design §5, third bullet: each §2.2 refusal reaches the operator through phase 1b with
    the file's own path in it. There is no waiver and no fallback to defaults, and the refusal
    comes AHEAD of the work: a broken file only noticed after the pool had rendered would still
    raise and still name its path, so the raise alone cannot show that.

    What carries the weight is the disk. A real geometry exists and nothing has encoded; after
    six refusals there is still no ep*.mp4, which is what separates "refused ahead of the
    render" from "rendered, then refused".

    CONTROL: the same call with the file gone. It renders — so the six refusals were the file's
    and nothing else's, and the glob that read empty above is shown able to see a clip."""
    ctx = _run(tmp_path, monkeypatch, [(DARK, {})])
    _geometry(ctx)
    for doc, needle in [('[]', 'must be an object'),
                        ('{"nope": {"value": 1, "why": "x"}}', 'not a gate threshold'),
                        ('{"variety_min": {"value": 4, "why": "x"}}', 'ReelManifest.variety_min'),
                        ('{"entropy_floor": 0.85}', "'value' and 'why'"),
                        ('{"entropy_floor": {"value": 0.85, "why": "  "}}', 'non-empty'),
                        ('{"entropy_floor": {"value": 1.5, "why": "x"}}', 'ratio in (0, 1]')]:
        gates_path = _gates(tmp_path, doc)
        with pytest.raises(ValueError) as e:
            _phase_1b(ctx)
        msg = str(e.value)
        assert str(gates_path) in msg and needle in msg, (doc, msg)
        assert not list(Path(ctx["out"]).glob("ep*.mp4")), doc

    gates_path.unlink()
    _, stop = _phase_1b(ctx)
    assert stop is None, stop
    assert list(Path(ctx["out"]).glob("ep*.mp4"))


# --- Proof 4: the control that must not move -----------------------------------------

def test_with_no_gates_file_the_run_is_identical(tmp_path, monkeypatch):
    """The slice's acceptance constraint (design §3, §5 last bullet): a run that authors
    nothing writes what it always wrote. Same inputs as the reel-scope proof, GATES.json
    absent, and not one artifact the slice could have touched carries a trace of it — no
    `gates` in EPISODES.json or the attestation, no `authored` row in any episode or reel
    report, every bar at its default.

    Each key asserted absent here is one proof 2 reads present (`gates` and the overrides in
    EPISODES.json, `authored` in the episode and reel reports, `gates` in the attestation), so
    none of these absences is the absence of an instrument that cannot see.

    Byte-identity against an engine that predates the slice cannot be asserted from inside this
    tree. What is pinned is the property it rests on: every key the slice adds is conditional
    on something having been authored. To re-derive the stronger claim, run this scenario at the
    commit before `scripts/lib/gates.py` first landed and at HEAD, then diff EPISODES.json, both
    episode reports and the clips after normalising the temp directory."""
    ctx = _two_exposure_reel(tmp_path, monkeypatch)
    rm = _render(ctx)
    episodes = _episodes_json(ctx, rm)

    raw = json.loads(episodes.read_text())
    assert "gates" not in raw
    assert raw["provenance"]["overrides"] == []
    reloaded = ReelManifest.from_json(episodes)
    assert reloaded.gates == {}
    assert reloaded.check_spec == ReelCheckSpec(reloaded.target_dur)     # every bar at default

    reel_work = str(Path(ctx["work"]) / "reel")
    res = build_reel.build_reel(reloaded, ctx["deliveries"], reel_work)
    assert res["status"] == "delivered", res

    reports = [_report(ctx, 0), _report(ctx, 1), res["report"],
               json.loads((Path(reel_work) / "reel_report.json").read_text())]
    for rep in reports:
        assert rep["checks"], rep                                # not vacuous: something was judged
        assert [n for n, c in rep["checks"].items() if "authored" in c] == []
    assert _report(ctx, 0)["checks"]["grade_damage"]["floor"] == 0.90
    assert res["report"]["checks"]["grade_faithful"]["max"] == 4.0

    attestation = json.loads(prov_lib.attest_path(res["output"]).read_text())
    assert "gates" not in attestation
    assert attestation["overrides"] == []
