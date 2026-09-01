import numpy as np
import pytest
from scripts.lib import gradedamage


def _flat(v: int, h: int = 8, w: int = 8) -> np.ndarray:
    return np.full((h, w, 3), v, dtype=np.uint8)


def _ramp(h: int = 16, w: int = 16) -> np.ndarray:
    """A frame whose luma covers many distinct codes."""
    g = np.tile(np.linspace(20, 220, w, dtype=np.uint8), (h, 1))
    return np.dstack([g, g, g])


def test_entropy_of_a_flat_frame_is_zero():
    assert gradedamage.entropy(_flat(128)) == pytest.approx(0.0)


def test_entropy_of_a_ramp_is_positive():
    assert gradedamage.entropy(_ramp()) > 3.0


def test_entropy_is_invariant_under_a_bijective_relabeling():
    """The whole reason this statistic was chosen: a monotone bijection carries the
    histogram intact, so movement alone must not read as damage."""
    a = _ramp()
    b = (a.astype(np.int16) + 20).clip(0, 255).astype(np.uint8)   # +20 codes, no collisions
    assert gradedamage.entropy(b) == pytest.approx(gradedamage.entropy(a))


def test_entropy_falls_under_a_many_to_one_map():
    # w=64, not the fixture's default 16: at w=16 the ramp's codes are ~13.3 apart,
    # wider than the //8*8 quantization bin, so no two codes ever land in the same
    # bin and entropy does not move at all (measured: 4.0 -> 4.0). Widened so the
    # collapse this test exists to demonstrate actually happens (measured: 6.0 -> 4.671).
    a = _ramp(w=64)
    b = ((a.astype(np.int16) // 8) * 8).astype(np.uint8)          # 8:1 quantization
    assert gradedamage.entropy(b) < gradedamage.entropy(a) - 1.0


def test_evaluate_passes_a_relabeling():
    a = [_ramp(), _ramp(), _ramp()]
    b = [(f.astype(np.int16) + 20).clip(0, 255).astype(np.uint8) for f in a]
    d = gradedamage.evaluate(a, b, 0.90)
    assert d["ratio"] == pytest.approx(1.0, abs=1e-3)
    assert d["below"] is False
    assert d["frames"] == 3


def test_evaluate_fails_a_quantization():
    # w=64 — see test_entropy_falls_under_a_many_to_one_map for why the fixture's
    # default width does not exercise a many-to-one map at all.
    a = [_ramp(w=64), _ramp(w=64), _ramp(w=64)]
    b = [((f.astype(np.int16) // 8) * 8).astype(np.uint8) for f in a]
    d = gradedamage.evaluate(a, b, 0.90)
    assert d["below"] is True
    assert d["ratio"] < 0.90


def test_evaluate_judges_the_rounded_ratio_it_reports(monkeypatch):
    """A report reading 'ratio: 0.9, floor: 0.9, below: true' is a contradiction no
    reader can act on — color_fidelity.evaluate documents the same rule.

    Task 0 brief's own pre-authorized fallback, exercised: the brief's bisection
    searches for a quantization step whose raw ratio sits just under 0.90 but
    rounds to it, by bisecting on this fixture's default (w=16) ramp. Measured, it
    converges on ratio 0.906 — not a value that rounds to the floor at all, so it
    never reaches the contradiction this test exists to pin. Stubbing `entropy`
    to hand back two fixed values makes the boundary exact and deterministic
    instead of dependent on where this ramp's quantization steps happen to fall."""
    values = iter([1.0, 0.8996])              # raw ratio 0.8996 -> rounds to 0.900
    monkeypatch.setattr(gradedamage, "entropy", lambda frame: next(values))
    d = gradedamage.evaluate([_ramp()], [_ramp()], 0.90)
    assert d["ratio"] == 0.90
    assert d["below"] is (d["ratio"] < d["floor"])
    assert d["below"] is False   # the raw 0.8996 < 0.90 would say True — the rounded value must win


def test_evaluate_reports_not_checked_on_no_frames():
    d = gradedamage.evaluate([], [], 0.90)
    assert d["status"] == "not-checked"
    assert "below" not in d


def test_evaluate_refuses_mismatched_lists():
    with pytest.raises(ValueError, match="parallel"):
        gradedamage.evaluate([_ramp()], [_ramp(), _ramp()], 0.90)


def test_evaluate_reports_not_checked_when_the_ungraded_frame_is_flat():
    """A flat ungraded frame has zero entropy and no ratio exists. Reporting a
    division result would be inventing one."""
    d = gradedamage.evaluate([_flat(128)], [_flat(200)], 0.90)
    assert d["status"] == "not-checked"
