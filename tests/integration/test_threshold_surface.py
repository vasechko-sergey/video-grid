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

That is half of it. A GATES.json exists to waive as much as to tighten, and a tightened bar
cannot tell one that arrived from one clamped back to the default: `max(floor, 0.90)` leaves
every tightening alone. So proofs 5 and 6 go the other way — a bar the default refuses is
released by an authored one, on pixels whose reading lies between the two bars — and proof 7
goes through `assemble_reel`, the entry the router actually delivers through, instead of
re-enacting it.
"""
import dataclasses
import json
from pathlib import Path

import pytest
from scripts import build_reel, edl_to_reel, episode_qc, match_grade
from scripts.lib import color, provenance as prov_lib
from scripts.lib.models import ReelCheckSpec, ReelManifest
# `tests/` is what pytest puts on sys.path (tests/integration is a package, tests/ is not), so
# these are the sibling modules' import path. Imported and not copied, as test_grade_shipped_pixels
# itself does with `_banded_episode`: a second copy of `_run` would drift from the fixture whose
# route, canvas and window geometry every number below was measured on, and a second copy of
# `_judge` from the findings schema it writes.
from integration.test_episode_qc import _judge
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

# The heaviest grade the engine accepts: all four knobs at their documented legal extremes
# (color.HIGHLIGHT_MIN, SATURATION_MIN, HIGHLIGHT_RED_MAX, SHADOW_RED_MAX). It is the waiver
# proof's subject because it is a LEGAL grade the default floor refuses — measured on this
# footage at ratio 0.884 against 0.90 — which is the case design §4 exists for: a bar calibrated
# on one shoot refusing correctly-made footage from another. A single mild knob stays well above
# it (highlight 0.7 alone reads 0.963, saturation 0.5 alone 0.993).
_HEAVY_GRADE = {"highlight": 0.60, "saturation": 0.5, "highlight_red": 0.35, "shadow_red": 0.2}

# A declaration the clip does not carry: written into episode 0's manifest AFTER it rendered
# without it, so `grade_faithful` predicts a frame the clip never had. Measured residual 45.0
# against the default 4.0 — the simplest way to put a reel's reading far above the default bar
# on committed footage, since an honestly graded episode reads 1.0. Machine-checked against the
# ceiling color.py itself publishes, so the declaration cannot quietly become illegal (an
# unplannable episode reads as not-checked, which would make the control below fail for the
# wrong reason).
_UNCARRIED_BLACK_POINT = 0.2

_WHY_FLOOR = "deliberately unreachable, to prove the bar moved"
_WHY_TIGHT = "tighter than the 1-code residual the conductor's own pairs leave, to prove the bar moved"
_WHY_LOOSE = "loosened to a bar this reel clears, to see the reason beside a PASS"
_WHY_ADVISORY = "tightened until its advisory check fails, to see the reason beside a FAIL that blocks nothing"
_WHY_WAIVE_FLOOR = "waived: a deliberately heavy grade, legal at every knob, that the default floor refuses"
_WHY_WAIVE_RESIDUAL = "waived: the declaration is known not to be carried by the clip"


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
    """The reel the reel-scope proofs and the control start from: two exposures, geometry
    frozen (phase 1a), the conductor's tone pair authored on each. The pairs are what give
    `grade_faithful` something to measure — an ungraded episode's residual is exactly 0.0,
    which no positive bar can fail."""
    ctx = _run(tmp_path, monkeypatch, [(DARK, {}), (BRIGHT, {})])
    _geometry(ctx)
    assert match_grade.write_match(ctx["geometry"])["authored"] == 2
    return ctx


def _episodes_json(ctx: dict, rm: ReelManifest) -> Path:
    """EPISODES.json, written by `_episodes_ready` — the function both phase-1 arms end with,
    and the one the CLI's --from-geometry arm calls. Not re-implemented here: a writer that
    stripped the gates would otherwise be invisible to every proof that wrote its own."""
    return Path(edl_to_reel._episodes_ready(rm, ctx["out"])["episodes"])


def _reel_checks(reel_work: str) -> dict:
    """The reel report's checks as they sit on disk, for the same reason `_report` reads the
    episode's from disk."""
    return json.loads((Path(reel_work) / "reel_report.json").read_text())["checks"]


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
    verdict moved with the bar and the pixels did not; and the attestation carries phase 1's
    overrides through. (3) The record of a moved bar on a reel that ships. The blocking bar is
    loosened to one this reel clears at the default too, so this leg shows the reason beside a
    PASS and in the attestation, NOT a waiver (proof 6 is that); and an ADVISORY bar is
    tightened until its check fails, which must not stop the reel — the reason sits beside the
    FAIL and the attestation row reads `blocking: False`. It is the one place this file reads
    the attestation's gates present, which is what lets proof 4 assert them absent."""
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
    checks = _reel_checks(reel_work)
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
    assert list(Path(ctx["deliveries"]).glob("REEL_v*.mp4"))     # the glob above CAN see a reel
    gf0 = ok["report"]["checks"]["grade_faithful"]
    assert gf0["pass"] is True and gf0["max"] == 4.0 and "authored" not in gf0, gf0
    assert gf0["worst"] == gf["worst"]
    # phase 1's overrides ride through deliver into the attestation: the twin that makes proof
    # 4's `overrides == []` a reading of an empty record and not of a dropped one
    delivered = json.loads(prov_lib.attest_path(ok["output"]).read_text())
    assert delivered["overrides"] == raw["provenance"]["overrides"]

    # leg 3: the record on a reel that ships, and the attestation of the reel those bars judged.
    # The manifest is the loaded one with different bars, so its `provenance.overrides` is still
    # the tight run's — and the attestation's gates must follow the manifest that judged the
    # reel, not provenance, which is how build_reel derives them (see its `prov["gates"]` site).
    loosened = {**doc, "grade_residual_max": {"value": 3.0, "why": _WHY_LOOSE},
                "chroma_spread_max": {"value": 0.1, "why": _WHY_ADVISORY}}
    lax = build_reel.build_reel(dataclasses.replace(reloaded, gates=loosened),
                                ctx["deliveries"], reel_work)
    assert lax["status"] == "delivered", lax
    lax_checks = lax["report"]["checks"]
    gf3 = lax_checks["grade_faithful"]
    assert gf3["pass"] is True and gf3["max"] == 3.0, gf3
    assert gf3["authored"] == [{"field": "grade_residual_max", "value": 3.0, "default": 4.0,
                                "why": _WHY_LOOSE}]
    cs = lax_checks["chroma_spread"]                             # advisory: fails, blocks nothing
    assert cs["pass"] is False and cs["max"] == 0.1 and cs["worst"] > 0.1, cs
    assert cs["authored"] == [{"field": "chroma_spread_max", "value": 0.1, "default": 5.0,
                               "why": _WHY_ADVISORY}]
    attested = json.loads(prov_lib.attest_path(lax["output"]).read_text())["gates"]
    assert {g["field"]: g for g in attested} == {
        "grade_residual_max": {"field": "grade_residual_max", "value": 3.0, "default": 4.0,
                               "scope": "reel", "blocking": True, "why": _WHY_LOOSE},
        "loudness_tol": {"field": "loudness_tol", "value": 2.0, "default": 1.0,
                         "scope": "reel", "blocking": True,
                         "why": "carrier only: a silent reel never judges it"},
        "chroma_spread_max": {"field": "chroma_spread_max", "value": 0.1, "default": 5.0,
                              "scope": "reel", "blocking": False, "why": _WHY_ADVISORY},
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
    for doc, needle in [('[]', 'must be an object mapping'),
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
    EPISODES.json, `authored` in the episode and reel reports, `gates` and the overrides in the
    attestation), so none of these absences is the absence of an instrument that cannot see.

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


# --- Proof 5: the waiver direction, episode scope ------------------------------------

def test_a_loosened_entropy_floor_releases_a_grade_the_default_refuses(tmp_path, monkeypatch):
    """The other direction of proof 1, and the one a GATES.json is for (design §4): a LEGAL
    grade the default floor refuses is released by an authored floor, with the reason beside
    the PASS. Proof 1 cannot see this. A clamp that only ever raises a bar back to its default
    (`max(floor, 0.90)`) leaves every tightening untouched and silently ignores every waiver, so
    a slice shipping it would pass proofs 1 to 4 and do nothing a waiver is for.

    CONTROL: the same episode, the same geometry, rendered first with no GATES.json. The default
    refuses it (ratio 0.884, under 0.90) and the authored run then releases it at that very
    ratio, so the release is the bar's and nothing else's."""
    ctx = _run(tmp_path, monkeypatch, [(DARK, dict(_HEAVY_GRADE))])
    _geometry(ctx)

    rm, stop = _phase_1b(ctx)                            # the control: no GATES.json, the default bar
    assert rm is None and stop["sub"]["reason"] == "grade-damage", stop
    assert stop["sub"]["fail_reasons"] == ["grade_damage"], stop["sub"]
    refused = _report(ctx)["checks"]["grade_damage"]
    assert refused["pass"] is False and refused["floor"] == 0.90, refused
    assert "authored" not in refused, refused
    assert 0.85 < refused["ratio"] < 0.90, refused       # between the two floors: the precondition

    _gates(tmp_path, {"entropy_floor": {"value": 0.85, "why": _WHY_WAIVE_FLOOR}})
    rm, stop = _phase_1b(ctx)
    assert stop is None, stop                            # released, and only because the bar moved

    checks = _report(ctx)["checks"]
    gd = checks["grade_damage"]
    assert gd["pass"] is True and gd["floor"] == 0.85, gd
    assert gd["ratio"] == refused["ratio"]               # the pixels did not move; only the bar
    assert gd["authored"] == [{"field": "entropy_floor", "value": 0.85, "default": 0.90,
                               "why": _WHY_WAIVE_FLOOR}]            # the reason beside the PASS
    assert [n for n, c in checks.items() if "authored" in c] == ["grade_damage"]


# --- Proof 6: the waiver direction, reel scope ---------------------------------------

def test_a_loosened_reel_bar_releases_a_reel_the_default_stops(tmp_path, monkeypatch):
    """The other direction of proof 2, for the reason proof 5 gives: `min(max, 4.0)` leaves every
    tightened bar alone and silently ignores every waiver. The reel's reading has to sit far from
    the default and inside the authored bar, which an honestly graded reel never does (its
    residual is 1.0). So the reel is made dishonest on purpose: after phase 1b rendered it, a
    `black_point` the clips do not carry is written into episode 0's manifest, and
    `grade_faithful` predicts a frame that was never shipped. It is a contrived waiver, and the
    simplest way to put a reel's reading between two bars on committed footage; what it proves
    is that an authored 60.0 arrives unclamped, which is all a clamp could take away.

    CONTROL: the same edited manifest with its gates emptied, through the same `build_reel`. It
    stops on `grade_faithful` at the default 4.0, with the SAME residual the authored run then
    ships at, so the release is the bar's and nothing else's."""
    assert 0 < _UNCARRIED_BLACK_POINT <= color.BLACK_POINT_MAX
    ctx = _two_exposure_reel(tmp_path, monkeypatch)
    _gates(tmp_path, {"grade_residual_max": {"value": 60.0, "why": _WHY_WAIVE_RESIDUAL}})
    rm, stop = _phase_1b(ctx)
    assert stop is None, stop

    episodes = _episodes_json(ctx, rm)
    raw = json.loads(episodes.read_text())
    raw["episodes"][0]["manifest"]["black_point"] = _UNCARRIED_BLACK_POINT
    episodes.write_text(json.dumps(raw, indent=2))
    reloaded = ReelManifest.from_json(episodes)
    assert reloaded.check_spec.grade_residual_max == 60.0        # the waiver rode the file

    reel_work = str(Path(ctx["work"]) / "reel")
    stopped = build_reel.build_reel(dataclasses.replace(reloaded, gates={}), ctx["deliveries"],
                                    reel_work)                   # the control: the default bar
    assert stopped["status"] == "stop_and_report", stopped
    assert stopped["finding"]["check"] == "grade_faithful", stopped["finding"]
    refused = _reel_checks(reel_work)["grade_faithful"]
    assert refused["pass"] is False and refused["max"] == 4.0, refused
    assert "authored" not in refused, refused
    assert 4.0 < refused["worst"] < 60.0, refused        # between the two bars: the precondition
    assert not list(Path(ctx["deliveries"]).glob("REEL_v*.mp4"))

    released = build_reel.build_reel(reloaded, ctx["deliveries"], reel_work)
    assert released["status"] == "delivered", released   # released, and only because the bar moved
    assert list(Path(ctx["deliveries"]).glob("REEL_v*.mp4"))
    gf = _reel_checks(reel_work)["grade_faithful"]
    assert gf["pass"] is True and gf["max"] == 60.0, gf
    assert gf["worst"] == refused["worst"]               # the pixels did not move; only the bar
    assert gf["authored"] == [{"field": "grade_residual_max", "value": 60.0, "default": 4.0,
                               "why": _WHY_WAIVE_RESIDUAL}]         # the reason beside the PASS


# --- Proof 7: phase 2, through the entry the router delivers through -----------------

def test_phase_2_judges_the_reel_by_the_set_phase_1b_froze(tmp_path, monkeypatch):
    """design §6: phase 2 carries the set frozen at phase 1b and never re-reads the file.
    Proofs 2 and 6 hand `build_reel` a manifest they loaded themselves, which re-enacts both ends
    of the handoff. This goes through them: `_episodes_ready` for the write, the QC gate (pack, a
    judge, build), and `assemble_reel` — the `--from-episodes` entry the router delivers through,
    which loads EPISODES.json itself and can look at nothing else, because it takes no project
    path.

    GATES.json is deleted before phase 2, so the only place the bar can come from is the file
    phase 1b wrote. With `grade_residual_max` 0.5 authored beforehand, phase 2 must stop on
    `grade_faithful` with the reason beside the verdict. A phase 2 that dropped the frozen set
    (`rm.gates = {}` in `assemble_reel` or in the writer) would judge at the default and deliver.

    CONTROL: the reading. This reel's residual sits between the two bars (asserted below), so
    the same phase 2 at the default bar delivers it — proof 2's leg 2 delivers this very reel at
    4.0 — and the stop is the authored bar's and nothing else's."""
    ctx = _two_exposure_reel(tmp_path, monkeypatch)
    _gates(tmp_path, {"grade_residual_max": {"value": 0.5, "why": _WHY_TIGHT}})
    rm, stop = _phase_1b(ctx)
    assert stop is None, stop
    episodes = _episodes_json(ctx, rm)

    packets = tmp_path / "qc"
    episode_qc.pack(str(episodes), str(packets))
    _judge(packets, 0)
    _judge(packets, 1)
    assert episode_qc.build(str(episodes), str(packets), ctx["out"])["verdict"] == "approve"

    (tmp_path / "GATES.json").unlink()                   # phase 2 must not need the file again
    res = edl_to_reel.assemble_reel(str(episodes), ctx["work"])
    assert res["status"] == "stop_and_report", res
    assert res["finding"]["check"] == "grade_faithful", res["finding"]
    gf = res["report"]["checks"]["grade_faithful"]
    assert gf["pass"] is False and gf["max"] == 0.5, gf
    assert 0.5 < gf["worst"] <= 4.0, gf                  # between the two bars: the precondition
    assert gf["authored"] == [{"field": "grade_residual_max", "value": 0.5, "default": 4.0,
                               "why": _WHY_TIGHT}]
