import json

import imagehash
import pytest

from scripts import check_reel
from scripts.lib.models import ReelCheckSpec


class _Stub:
    """Stub the ffmpeg-touching helpers so check_reel logic is unit-testable.
    durations: per-episode seconds. blacks: black_start times on the master.
    means: {t: (r,g,b)}. hashes: {t: int} used as a fake ImageHash distance base."""
    def __init__(self, durations, blacks=(), means=None, hashes=None):
        self.durations = durations
        self.blacks = list(blacks)
        self.means = means or {}
        self.hashes = hashes or {}

    def install(self, monkeypatch):
        eps_dur = iter(self.durations + [sum(self.durations)])  # episodes..., then master
        # raising=False: _frame_mean/_phash_bits/_hamming do not exist on the module
        # until Tasks 6-7, but _Stub is written once in Task 5 and reused there.
        monkeypatch.setattr(check_reel, "_probe_dur", lambda v: next(eps_dur))
        monkeypatch.setattr(check_reel, "_black_hits", lambda m: self.blacks)
        monkeypatch.setattr(check_reel, "_frame_mean",
                            lambda v, t: self.means.get(round(t, 3), (100.0, 120.0, 130.0)),
                            raising=False)
        monkeypatch.setattr(check_reel, "_phash_bits",
                            lambda v, t: self.hashes.get(round(t, 3), 0), raising=False)
        monkeypatch.setattr(check_reel, "_hamming", lambda a, b: abs(a - b), raising=False)


def test_length_passes_within_half_second(tmp_path, monkeypatch):
    _Stub([3.0, 3.0]).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["length"].passed is True
    assert rep.checks["black"].passed is True


def test_length_fails_and_attributes_to_pacing(tmp_path, monkeypatch):
    _Stub([3.0, 4.0]).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["length"].passed is False and rep.overall is False
    f = [x for x in rep.fail_reasons if x.check == "length"][0]
    assert f.escalate_to == "pacing" and f.episode_idx is None


def test_black_hit_attributes_to_the_owning_episode(tmp_path, monkeypatch):
    # a black frame at t=4.0 lands in episode 1 (spans 3.0..6.0)
    _Stub([3.0, 3.0], blacks=[4.0]).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["black"].passed is False
    f = [x for x in rep.fail_reasons if x.check == "black"][0]
    assert f.episode_idx == 1 and f.escalate_to == "reprocess"


def test_audio_and_safezone_checks_are_not_implemented(tmp_path, monkeypatch):
    # distinct hashes: this test is about beat/loudness/safe_zones, not variety —
    # without them the _Stub default (identical hash 0 at both midpoints) trips
    # the variety check (distance 0 < variety_min) and overall flips to False.
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    for name in ("beat", "loudness", "safe_zones"):
        assert rep.checks[name].passed is None
    assert rep.overall is True          # None never fails the reel
    assert rep.wall_s >= 0.0 and rep.episode_count == 2


def test_color_across_cuts_passes_when_neighbours_match(tmp_path, monkeypatch):
    # one cut at t=3.0; both sides ~equal → delta 0 → pass
    _Stub([3.0, 3.0], means={2.95: (100.0, 120.0, 130.0), 3.05: (101.0, 121.0, 131.0),
                             1.5: (100.0, 120.0, 130.0), 4.5: (101.0, 121.0, 131.0)}
          ).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["color_across_cuts"].passed is True


def test_color_across_cuts_blames_the_episode_farther_from_the_reel_median(tmp_path, monkeypatch):
    # 3 episodes, cut 1 at t=6.0 has a big jump; ep2 (span mid t=7.5) is the outlier
    means = {5.95: (100.0, 120.0, 130.0), 6.05: (160.0, 120.0, 130.0),  # cut 1 sides
             2.95: (100.0, 120.0, 130.0), 3.05: (100.0, 120.0, 130.0),  # cut 0 sides (match)
             1.5: (100.0, 120.0, 130.0), 4.5: (100.0, 120.0, 130.0), 7.5: (160.0, 120.0, 130.0)}
    _Stub([3.0, 3.0, 3.0], means=means).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4", "c.mp4"], ReelCheckSpec(target_dur=9.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["color_across_cuts"].passed is False
    f = [x for x in rep.fail_reasons if x.check == "color_across_cuts"][0]
    assert f.episode_idx == 2 and f.escalate_to == "reprocess"


def test_color_across_cuts_is_not_applicable_for_a_single_episode(tmp_path, monkeypatch):
    _Stub([3.0]).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4"], ReelCheckSpec(target_dur=3.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["color_across_cuts"].passed is None      # no cut to judge


def test_color_across_cuts_two_episode_tie_blames_the_later_episode(tmp_path, monkeypatch):
    # N=2: the 2-value median is equidistant from both spans, so attribution is a
    # defined default — blame the later episode (episode 1), matching variety.
    means = {2.95: (100.0, 120.0, 130.0), 3.05: (200.0, 120.0, 130.0),   # cut sides: delta 33.3 → fail
             1.5: (100.0, 120.0, 130.0), 4.5: (200.0, 120.0, 130.0)}     # span midpoints
    _Stub([3.0, 3.0], means=means).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["color_across_cuts"].passed is False
    f = [x for x in rep.fail_reasons if x.check == "color_across_cuts"][0]
    assert f.episode_idx == 1


def test_color_across_cuts_uses_median_not_mean_so_a_far_outlier_does_not_mislead(tmp_path, monkeypatch):
    # 5 episodes; failing cut 0 is between ep0(100) and ep1(200). ep4 is a far,
    # unrelated outlier (9999). A MEAN center is dragged by ep4 and would mis-blame
    # ep0; the MEDIAN center keeps ep1 (the truly-shifted span) as the culprit.
    means = {2.95: (100.0, 120.0, 130.0), 3.05: (200.0, 120.0, 130.0),   # cut 0 sides → delta 33.3, fail
             5.95: (100.0, 120.0, 130.0), 6.05: (100.0, 120.0, 130.0),   # cut 1 sides → pass
             8.95: (100.0, 120.0, 130.0), 9.05: (100.0, 120.0, 130.0),   # cut 2 sides → pass
             11.95: (100.0, 120.0, 130.0), 12.05: (100.0, 120.0, 130.0),  # cut 3 sides → pass
             1.5: (100.0, 120.0, 130.0), 4.5: (200.0, 120.0, 130.0),      # span mids 0,1
             7.5: (100.0, 120.0, 130.0), 10.5: (100.0, 120.0, 130.0),     # span mids 2,3
             13.5: (9999.0, 120.0, 130.0)}                                # span mid 4 — far outlier
    _Stub([3.0, 3.0, 3.0, 3.0, 3.0], means=means).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4", "c.mp4", "d.mp4", "e.mp4"],
                         ReelCheckSpec(target_dur=15.0), str(tmp_path / "r.json"))
    assert rep.checks["color_across_cuts"].passed is False
    f = [x for x in rep.fail_reasons if x.check == "color_across_cuts" and x.detail["cut"] == 0][0]
    assert f.episode_idx == 1     # median → ep1 (correct); a mean would say ep0


def test_color_fail_detail_carries_target_and_culprit_mean(tmp_path, monkeypatch):
    # ep0 grey ~(100,120,130), ep1 warm ~(160,120,130): the cut delta trips the
    # ceiling. ep0/ep1 are equidistant from the median (100/160 straddle 130), so
    # the later-episode tie-break picks ep1 (see the two-episode tie test above). The
    # driver reads detail["target"] (reel median) and detail["culprit_mean"] to build med/d_i.
    _Stub([3.0, 3.0],
          means={2.95: (100.0, 120.0, 130.0), 3.05: (160.0, 120.0, 130.0),
                 1.5: (100.0, 120.0, 130.0), 4.5: (160.0, 120.0, 130.0)}
          ).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0, color_delta_max=12.0),
                         str(tmp_path / "r.json"))
    f = [x for x in rep.fail_reasons if x.check == "color_across_cuts"][0]
    assert f.episode_idx == 1
    # median of the two span means, per channel
    assert f.detail["target"] == [130.0, 120.0, 130.0]
    # ep1 (the culprit) span mean
    assert f.detail["culprit_mean"] == [160.0, 120.0, 130.0]


def test_variety_flags_a_near_duplicate_pair(tmp_path, monkeypatch):
    # ep0 and ep1 identical hash (distance 0 < variety_min) → fail, blame ep1
    _Stub([3.0, 3.0], hashes={1.5: 100, 4.5: 100}).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0, variety_min=8), str(tmp_path / "r.json"))
    assert rep.checks["variety"].passed is False
    f = [x for x in rep.fail_reasons if x.check == "variety"][0]
    assert f.episode_idx == 1 and f.escalate_to == "edit-plan"


def test_variety_passes_for_distinct_episodes(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0, variety_min=8), str(tmp_path / "r.json"))
    assert rep.checks["variety"].passed is True


def test_variety_passes_at_exactly_the_threshold(tmp_path, monkeypatch):
    # distance == variety_min must PASS (spec: Hamming >= variety_min); guards the < boundary
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 8}).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0, variety_min=8), str(tmp_path / "r.json"))
    assert rep.checks["variety"].passed is True


def test_variety_failure_report_is_json_serializable_with_real_hamming(tmp_path, monkeypatch):
    # regression: the REAL _hamming (numpy.int64) must survive rep.write()'s json.dumps.
    # Stub everything EXCEPT _hamming, and feed real ImageHash objects via _phash_bits.
    durs = iter([3.0, 3.0, 6.0])                       # ep0, ep1, then master
    monkeypatch.setattr(check_reel, "_probe_dur", lambda v: next(durs))
    monkeypatch.setattr(check_reel, "_black_hits", lambda m: [])
    monkeypatch.setattr(check_reel, "_frame_mean", lambda v, t: (100.0, 120.0, 130.0))
    same = imagehash.hex_to_hash("0000000000000000")   # identical → distance 0 < variety_min → fail
    monkeypatch.setattr(check_reel, "_phash_bits", lambda v, t: same)
    # _hamming is intentionally NOT stubbed → the real numpy-returning path runs
    out = tmp_path / "r.json"
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0), str(out))
    assert rep.checks["variety"].passed is False
    reloaded = json.loads(out.read_text())             # must parse → proves json.dumps didn't crash
    assert reloaded["checks"]["variety"]["pass"] is False
    assert isinstance(rep.fail_reasons[0].detail["distance"], int)


def test_probe_dur_fails_loud_on_a_durationless_probe(monkeypatch):
    monkeypatch.setattr(check_reel.proc, "run",
                        lambda cmd, **k: type("C", (), {"stdout": b"N/A\n"})())
    with pytest.raises(RuntimeError, match="no usable duration"):
        check_reel._probe_dur("x.mp4")


def test_beat_check_on_beat():
    cr = check_reel._beat_check([1.0, 2.0], (0.0, 1.02, 1.98, 3.0), 0.05)
    assert cr.passed is True and cr.detail["worst_dev"] == 0.02 and cr.detail["n_cuts"] == 2
    assert cr.detail["advisory"] is True


def test_beat_check_off_beat():
    cr = check_reel._beat_check([1.0], (0.0, 0.5, 1.3), 0.05)   # nearest beat 1.3 → dev 0.30
    assert cr.passed is False and cr.detail["worst_dev"] == 0.3


def test_beat_check_single_episode_na():
    cr = check_reel._beat_check([], (0.0, 0.5), 0.05)
    assert cr.passed is None and cr.detail["status"] == "n/a"


def test_loudness_check_in_range():
    cr, fail = check_reel._loudness_check(-14.4, ReelCheckSpec(target_dur=30.0))
    assert cr.passed is True and fail is None


def test_loudness_check_out_of_range_escalates_to_audio_mix():
    cr, fail = check_reel._loudness_check(-9.0, ReelCheckSpec(target_dur=30.0))
    assert cr.passed is False
    assert fail is not None and fail.check == "loudness" and fail.escalate_to == "audio-mix"
