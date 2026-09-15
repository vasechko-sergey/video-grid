"""End-to-end proofs for the mood contract (design
docs/specs/2026-09-03-mood-contract-design.md §6, proofs 2/3/4) — the three
claims that need more than the unit tests in tests/lib/test_match_grade.py,
tests/lib/test_moodpreset.py and tests/lib/test_edit_plan.py (proofs 1, 5, 6)
already give. Each proof carries a control that must NOT move — named
inline — because a proof whose control also moves proves nothing about the
change.

Fix round 1 (Critical + 3 Important, all against the brief this file
originally transcribed, none against a design claim): the same-band-twice
test asserted only output equality, which cannot tell "the cache hit" apart
from "the pipeline is deterministic even on two independent misses" — proof
3's own data below (8 windows, real vidstab-driven peaks) already showed two
independent real misses land byte-identical, so that version could not have
failed for the one thing it existed to catch. The default-run test was
vacuous (intake()'s own default parameter IS carve.DEFAULT_BAND — there is
no separate code path a real run could catch drifting). The zero-bias test
duplicated existing, STRONGER unit coverage in tests/lib/test_match_grade.py
and never called conduct/write_match, which is what design §6 proof 2 names.
And every real intake() call here ran genuine YOLO+ByteTrack+OSNet inference
that the claims under test do not depend on, unlike every other real-bytes
intake test in tests/integration/test_intake.py, which fakes exactly this
layer and says why in its own header.
"""
import inspect
import json
import shutil
from pathlib import Path

import pytest

from scripts import intake, match_grade
from scripts.lib import carve, matchgrade, moodpreset
from scripts.lib.edl import EDL, EDLEpisode
from scripts.lib.models import EpisodeGeometry, ReelGeometry
from scripts.lib.spec import Spec

pytestmark = pytest.mark.integration


class _FakeRes:
    """Mirrors tests/integration/test_intake.py's own _FakeRes: the shape
    intake._people_timeline reads off an ultralytics tracking result."""
    def __init__(self, boxes):
        self.boxes = boxes; self.orig_img = None; self.masks = None


def _fake_intake_cv(monkeypatch, n_frames: int = 360) -> None:
    """Fake the heavy ML collaborators _process_clip calls (YOLO+ByteTrack detection,
    vidstabdetect, OSNet re-ID), leaving real ffprobe/proxy-transcode/phash/cache IO
    untouched — the exact convention tests/integration/test_intake.py's module
    docstring states: "YOLO is faked because YOLO returns an empty route on the
    synthetic sample_clip (a box is not a person)". `multi_window_clip` has no person
    either, and the two claims these tests carry (a changed band re-carves; a cache
    hit skips recompute) are decided by carve.units_for_span's L-vs-win_max branch
    and by intake_cache's key, neither of which reads the detection signal's
    CONTENT — only whether a span exceeds the band. n_frames=360 matches the fixture's
    real 12s @ 30fps frame count (test_intake.py's own test_a_long_clip_carves_a_real_
    window_pool uses the same number against the same fixture)."""
    monkeypatch.setattr(intake, "_iter_seg",
                        lambda src, **k: iter(enumerate(_FakeRes([]) for _ in range(n_frames))))
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    monkeypatch.setattr(intake.vidstab, "require", lambda: None)
    monkeypatch.setattr(intake.vidstab, "detect", lambda src, trf, dur: [])
    monkeypatch.setattr(intake.reid, "embed", lambda crops: [[0.0] * 512 for _ in crops])


def test_a_changed_band_misses_the_cache_and_recarves(multi_window_clip, tmp_path, monkeypatch):
    root = tmp_path / "footage"; root.mkdir()
    shutil.copy(multi_window_clip, root / "clip.mp4")
    _fake_intake_cv(monkeypatch)
    out = tmp_path / "run"
    a = intake.intake(str(root), str(out), band=(1.2, 4.0))
    b = intake.intake(str(root), str(out), band=(1.2, 6.0))
    wins_a = [(w.start, w.dur) for c in a.clips for w in c.windows]
    wins_b = [(w.start, w.dur) for c in b.clips for w in c.windows]
    assert wins_a != wins_b, "a changed band must re-carve, not serve cached boundaries"


def test_the_same_band_twice_hits_the_cache_and_is_identical(multi_window_clip, tmp_path, monkeypatch):
    """The control: without this, the test above would pass even for a cache that
    NEVER hits — modelled on test_intake.py's own
    test_intake_resumes_from_cache_byte_identical (fix round 1, Critical). Output
    equality alone cannot tell "the cache hit" apart from "the pipeline is
    deterministic on two independent misses too" (proof 3 above already shows two
    independent real misses land byte-identical), so run 2 additionally breaks
    _process_clip itself: if the second intake() call ever recomputes instead of
    loading from disk, the test fails right there, by construction, not by luck."""
    root = tmp_path / "footage"; root.mkdir()
    shutil.copy(multi_window_clip, root / "clip.mp4")
    _fake_intake_cv(monkeypatch)
    out = tmp_path / "run"
    a = intake.intake(str(root), str(out), band=(1.2, 4.0))
    assert (out / ".intake_cache" / "clip.mp4" / "clip.json").exists()

    monkeypatch.setattr(intake, "_process_clip",
                        lambda *a, **k: pytest.fail("resume recomputed a cached clip"))
    b = intake.intake(str(root), str(out), band=(1.2, 4.0))   # must be all cache hits → no CV
    assert a.to_dict() == b.to_dict()


def test_the_default_band_parameter_is_carve_default_band():
    """Fix round 1 (Important): the original version of this test called intake()
    twice — once with no band, once with band=carve.DEFAULT_BAND — over a real
    12s clip and asserted the two Footage results were byte-identical. That is
    vacuous: intake()'s own signature declares
    `band: tuple[float, float] = carve.DEFAULT_BAND` (scripts/intake.py), so the two
    calls bind the IDENTICAL value through the IDENTICAL code path — there is no
    sentinel, no was-it-passed branch, nothing a real run could observe diverging.
    The only failure it could ever have caught is a typo in that default, which
    this signature check settles directly, in microseconds, instead of ~30s of real
    YOLO + vidstab work that never touched the claim. Do NOT "restore" the
    expensive two-real-run version — it discriminates nothing the signature
    inspection does not already discriminate, and design §6 proof 4's actual claim
    ("intake with no band flags produces the windows the current code produces")
    is exactly what a default PARAMETER means in Python."""
    assert inspect.signature(intake.intake).parameters["band"].default == carve.DEFAULT_BAND


# ---------------------------------------------------------------------------
# Design §6 proof 2, rewritten at the driver level (fix round 1, Important):
# the original version asserted only match_grade._resolve_bias(...)[0] triples,
# which tests/lib/test_match_grade.py already asserts as whole (bias, source)
# tuples three times over (test_resolve_bias_honours_an_authored_zero_against_
# a_biased_preset, ..._falls_back_to_the_preset_when_unauthored,
# ..._is_zero_with_no_spec_and_no_preset) — so the old version here was both
# redundant AND weaker than what it duplicated (a regression that returns the
# right bias with the wrong SOURCE label would pass it and fail those). Design
# §6 proof 2 itself names conduct/write_match ("[0, 0, 0] CONDUCTS to the
# unbiased median, byte-identical to a run with no --spec at all"), which
# _resolve_bias alone cannot exercise. Rewritten using the same
# monkeypatch.setattr(match_grade, "measure_crop", ...) + write_match(...)
# pattern tests/lib/test_match_grade.py already uses (e.g.
# test_write_match_prefers_an_authored_tone_bias_over_the_mood_preset).
# ---------------------------------------------------------------------------

# Two measured profiles whose per-anchor median matchgrade.common_target computes
# as (25.0, 110.0, 195.0) — the same fixture test_match_grade.py's own
# test_write_match_stamps_the_mood_biased_target_not_the_median uses, so the
# numbers here are known to already sit well clear of ReelCheckSpec.grade_residual_max
# once biased.
_PROFILES = {"d.mp4": (10.0, 90.0, 150.0), "b.mp4": (40.0, 130.0, 240.0)}


def _write_geometry(run_dir: Path) -> str:
    """A minimal 2-episode GEOMETRY.json + EDL.json under run_dir, entirely in
    ABSOLUTE paths so no chdir is needed — EpisodeGeometry.require_inputs only
    calls Path.exists(). measure_crop is monkeypatched by every caller below, so
    the touched source/route files exist only to satisfy that existence guard and
    are never decoded (mirrors test_match_grade.py's own _touch/_write_geometry).

    `project=str(run_dir / "project.json")`, and the file is WRITTEN: since
    whole-branch review finding 2, `_find_regions` tests the project FILE and not
    its parent directory, so an unwritten project now reads as "unreachable". This
    module's proof is about tone_bias resolution, not the regions feature, so it
    lands on the ordinary "no REGIONS.json" state.

    Returns the GEOMETRY.json path, as a str."""
    run_dir.mkdir(parents=True)
    episodes, geoms = [], []
    for i, source in enumerate(_PROFILES):
        (run_dir / source).touch()
        route = run_dir / f"r{i}.json"; route.touch()
        episodes.append(EDLEpisode(source=source, start=0.0, dur=2.0, shot_type="wide",
                                   composition="center", grid="thirds"))
        geoms.append(EpisodeGeometry(manifest={}, route=str(route),
                                     source=str(run_dir / source), project_dir=str(run_dir / f"p{i}")))
    edl_path = run_dir / "EDL.json"
    edl_path.write_text(json.dumps(EDL(episodes=tuple(episodes)).to_dict(), indent=2))
    (run_dir / "project.json").write_text(json.dumps({"canvas": [9, 16],
                                                      "delivery": "native"}))
    geometry_path = run_dir / "GEOMETRY.json"
    ReelGeometry(episodes=tuple(geoms), edl=str(edl_path),
                project=str(run_dir / "project.json")).write(geometry_path)
    return str(geometry_path)


def test_an_authored_zero_bias_conducts_like_no_spec_at_all(tmp_path, monkeypatch):
    """Design §6 proof 2: "[0, 0, 0] conducts to the unbiased median, byte-identical
    to a run with no --spec at all. The control that must not move: None still
    takes the preset's taste." Three independent write_match runs (each its own
    GEOMETRY/EDL — write_match rewrites the EDL in place, so reusing one across
    calls would let the second call see the first's authored tone pair)."""
    monkeypatch.setattr(match_grade, "measure_crop",
                        lambda md, src, route, **k: (_PROFILES[Path(src).name], ()))
    preset = moodpreset.resolve("nostalgic warm")
    assert preset.tone_bias != (0.0, 0.0, 0.0)           # the preset really would bias

    none_status = match_grade.write_match(_write_geometry(tmp_path / "none"))

    zero_spec = tmp_path / "zero_spec.json"
    zero_spec.write_text(json.dumps(Spec(canvas=(9, 16), length_s=30.0, mood="nostalgic warm",
                                         hook="open", tone_bias=(0, 0, 0)).to_dict()))
    zero_status = match_grade.write_match(_write_geometry(tmp_path / "zero"), spec=str(zero_spec))
    assert zero_status["target"] == none_status["target"]
    assert zero_status["bias_source"] == "SPEC.tone_bias"

    # The control that must NOT move: unauthored (tone_bias=None) still takes the
    # preset's taste — a resolver that always returns zero would pass everything
    # above and only be caught here.
    unauthored_spec = tmp_path / "unauthored_spec.json"
    unauthored_spec.write_text(json.dumps(Spec(canvas=(9, 16), length_s=30.0, mood="nostalgic warm",
                                               hook="open").to_dict()))
    unauth_status = match_grade.write_match(_write_geometry(tmp_path / "unauthored"), spec=str(unauthored_spec))
    assert unauth_status["target"] != none_status["target"]
    assert unauth_status["bias_source"] == "the nostalgic preset"
    expected_biased, _ = matchgrade.biased_target(tuple(none_status["target"]), preset.tone_bias)
    assert unauth_status["target"] == list(expected_biased)
