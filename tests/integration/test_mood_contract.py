"""End-to-end proofs for the mood contract (design
docs/specs/2026-09-03-mood-contract-design.md §6, proofs 2/3/4) — the three
claims only a real driver settles. Proofs 1, 5 and 6 are unit-level
(tests/lib/test_match_grade.py, tests/lib/test_moodpreset.py,
tests/lib/test_edit_plan.py); these three need real intake bytes (3, 4) or
wire Spec + moodpreset + match_grade together exactly as design §6 states the
claim (2). Each proof carries a control that must NOT move — named inline —
because a proof whose control also moves proves nothing about the change.
"""
import pytest

from scripts import intake, match_grade
from scripts.lib import carve, moodpreset
from scripts.lib.spec import Spec

pytestmark = pytest.mark.integration


def test_a_changed_band_misses_the_cache_and_recarves(multi_window_clip, tmp_path):
    root, out = multi_window_clip.parent, tmp_path / "run"
    a = intake.intake(str(root), str(out), band=(1.2, 4.0))
    b = intake.intake(str(root), str(out), band=(1.2, 6.0))
    wins_a = [(w.start, w.dur) for c in a.clips for w in c.windows]
    wins_b = [(w.start, w.dur) for c in b.clips for w in c.windows]
    assert wins_a != wins_b, "a changed band must re-carve, not serve cached boundaries"


def test_the_same_band_twice_hits_the_cache_and_is_identical(multi_window_clip, tmp_path):
    # The control: without this, the test above passes for a cache that never hits.
    root, out = multi_window_clip.parent, tmp_path / "run"
    a = intake.intake(str(root), str(out), band=(1.2, 4.0))
    b = intake.intake(str(root), str(out), band=(1.2, 4.0))
    assert a.to_dict() == b.to_dict()


def test_a_default_run_carves_what_the_explicit_default_carves(multi_window_clip, tmp_path):
    root = multi_window_clip.parent
    implicit = intake.intake(str(root), str(tmp_path / "a"))
    explicit = intake.intake(str(root), str(tmp_path / "b"), band=carve.DEFAULT_BAND)
    assert implicit.to_dict() == explicit.to_dict()


def test_an_authored_zero_bias_conducts_like_no_spec_at_all():
    preset = moodpreset.resolve("nostalgic warm")
    assert preset.tone_bias != (0.0, 0.0, 0.0)           # the preset really would bias
    spec_zero = Spec(canvas=(9, 16), length_s=30.0, mood="nostalgic warm",
                     hook="open", tone_bias=(0, 0, 0))
    assert match_grade._resolve_bias(spec_zero, preset)[0] == (0.0, 0.0, 0.0)
    assert match_grade._resolve_bias(None, None)[0] == (0.0, 0.0, 0.0)
    # the control that must NOT move: unauthored still takes the preset's taste
    spec_none = Spec(canvas=(9, 16), length_s=30.0, mood="nostalgic warm", hook="open")
    assert match_grade._resolve_bias(spec_none, preset)[0] == preset.tone_bias
