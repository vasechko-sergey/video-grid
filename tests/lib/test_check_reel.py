import json
from pathlib import Path

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


def test_beat_loudness_safe_zones_not_checked_when_silent(tmp_path, monkeypatch):
    # distinct hashes so the variety check passes (see the color/variety tests).
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    # all three now read "not-checked" — beat/loudness lack audio, safe_zones lacks geometry.
    for name in ("beat", "loudness", "safe_zones"):
        assert rep.checks[name].passed is None
        assert rep.checks[name].detail["status"] == "not-checked"
    assert rep.overall is True
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


def _write_geom(dir_path, x, y):
    """Write route.json / path.json / path.meta.json (fill 1000x2000; subject centre
    (x,y) source px, crop-x 0) and return the (route, path, meta) path triple."""
    d = Path(dir_path)
    d.mkdir(parents=True, exist_ok=True)
    (d / "route.json").write_text(json.dumps(
        [{"t": 0.0, "x": x, "y": y, "w": 100.0, "h": 200.0},
         {"t": 3.0, "x": x, "y": y, "w": 100.0, "h": 200.0}]))
    (d / "path.json").write_text(json.dumps([0, 0]))
    (d / "path.meta.json").write_text(json.dumps(
        {"mode": "fill", "crop_w": 1000, "crop_h": 2000, "crop_y": 0, "src_dims": [1000, 2000],
         "canvas": [1000, 2000], "out_dims": [1000, 2000], "rect_px": [0, 0, 1000, 2000], "freedom": 0}))
    return (str(d / "route.json"), str(d / "path.json"), str(d / "path.meta.json"))


def test_safe_zones_passes_when_every_subject_is_framed_safely(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    geom = [_write_geom(tmp_path / "ep0", 500.0, 900.0),      # fy 0.45 safe
            _write_geom(tmp_path / "ep1", 500.0, 900.0)]
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["safe_zones"].passed is True
    assert rep.checks["safe_zones"].detail["advisory"] is True


def test_safe_zones_flags_low_subject_but_stays_advisory(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    geom = [_write_geom(tmp_path / "ep0", 500.0, 900.0),      # safe
            _write_geom(tmp_path / "ep1", 500.0, 1960.0)]     # fy 0.98 → under tiktok caption band
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["safe_zones"].passed is False
    assert rep.checks["safe_zones"].detail["worst_episode"] == 1
    assert rep.overall is True          # advisory — a False safe_zones never blocks the reel
    assert not [f for f in rep.fail_reasons if f.check == "safe_zones"]   # no ReelFailure emitted


def _write_geom_layout(d, mode, rect_px):
    # a non-fill episode: subject centred, but the content rect is a card/letterbox
    d.mkdir(parents=True, exist_ok=True)
    (d / "route.json").write_text(json.dumps(
        [{"t": 0.0, "x": 500.0, "y": 900.0, "w": 100.0, "h": 200.0},
         {"t": 3.0, "x": 500.0, "y": 900.0, "w": 100.0, "h": 200.0}]))
    (d / "path.json").write_text(json.dumps([0, 0]))
    (d / "path.meta.json").write_text(json.dumps(
        {"mode": mode, "crop_w": 1000, "crop_h": 2000, "crop_y": 0, "src_dims": [1000, 2000],
         "canvas": [1000, 2000], "out_dims": [1000, 2000], "rect_px": list(rect_px), "freedom": 0}))
    return (str(d / "route.json"), str(d / "path.json"), str(d / "path.meta.json"))


def test_editorial_checks_report_and_stay_advisory(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    # ep0 fills; ep1's subject (x=980, w=100 via _write_geom) pokes past the right edge → key_action False
    geom = [_write_geom(tmp_path / "ep0", 500.0, 900.0),
            _write_geom(tmp_path / "ep1", 980.0, 900.0)]
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["key_action"].passed is False           # clipped subject flagged
    assert rep.checks["key_action"].detail["advisory"] is True
    assert rep.checks["pad_bars"].passed is None              # both fill → n/a
    assert rep.checks["transitions"].passed is True           # fill→fill, no layout jump
    assert rep.overall is True                                # all three advisory — none block
    assert not rep.fail_reasons                               # no ReelFailure emitted


def test_editorial_checks_flag_padbars_and_transitions(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    # ep0 fill; ep1 an asymmetric letterbox AND a fill→insert-ish layout jump
    geom = [_write_geom(tmp_path / "ep0", 500.0, 900.0),
            _write_geom_layout(tmp_path / "ep1", "insert", (0, 300, 400, 800))]
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["pad_bars"].passed is False and rep.checks["pad_bars"].detail["worst_episode"] == 1
    assert rep.checks["transitions"].passed is False and rep.checks["transitions"].detail["worst_cut"] == 0
    assert rep.overall is True and not rep.fail_reasons


def test_editorial_checks_not_checked_when_silent(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))            # no geometry
    for name in ("key_action", "pad_bars", "transitions"):
        assert rep.checks[name].passed is None
        assert rep.checks[name].detail["status"] == "not-checked"


def _write_geom_pan(dir_path, mode="fill", rect_px=(0, 0, 1000, 2000)):
    """A GENERATED (pan) episode's sidecars — and deliberately NO route.json, which
    is exactly what process_episode leaves on disk for a pan. The returned triple
    still names a route path, because edl_to_reel builds that path unconditionally
    for every episode; the file at the end of it simply never exists."""
    d = Path(dir_path)
    d.mkdir(parents=True, exist_ok=True)
    (d / "path.json").write_text(json.dumps([0, 0]))
    (d / "path.meta.json").write_text(json.dumps(
        {"mode": mode, "crop_w": 1000, "crop_h": 2000, "crop_y": 0, "src_dims": [1000, 2000],
         "canvas": [1000, 2000], "out_dims": [1000, 2000], "rect_px": list(rect_px),
         "freedom": 400, "pan": True}))       # pan written EXPLICITLY, never left to the default
    return (str(d / "route.json"), str(d / "path.json"), str(d / "path.meta.json"))


def test_pan_episode_does_not_crash_on_the_route_file_it_never_wrote(tmp_path, monkeypatch):
    # THE REGRESSION. check_reel opened route.json for every episode; a pan writes
    # none, so every reel containing one died with FileNotFoundError — and
    # edl_to_reel is the only multi-episode driver.
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    geom = [_write_geom_pan(tmp_path / "ep0"), _write_geom_pan(tmp_path / "ep1")]
    assert not Path(geom[0][0]).exists()      # the fixture really is the production situation
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.episode_count == 2 and rep.overall is True


def test_all_pan_reel_states_the_absence_instead_of_passing_vacuously(tmp_path, monkeypatch):
    # evaluate() over a list of empty lists returns pass=True — a green tick for
    # having examined nothing, the same shape checks.continuity([]) has one level
    # down. It must be stated, not fallen through.
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    geom = [_write_geom_pan(tmp_path / "ep0"), _write_geom_pan(tmp_path / "ep1")]
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    for name in ("safe_zones", "key_action"):
        assert rep.checks[name].passed is None
        assert rep.checks[name].detail["status"] == "not-checked"
        # the reason names the PROVENANCE — not _UNCHECKED's "no per-episode
        # geometry supplied", which is a different absence entirely (geometry WAS
        # supplied here; it just has no observation behind it)
        assert "every episode is a generated pan" in rep.checks[name].detail["reason"]


def test_all_pan_reel_still_runs_the_meta_only_checks(tmp_path, monkeypatch):
    # pad_bars and transitions read the metas alone, so a generated path is no
    # excuse to skip them — the same reason check_episode keeps running
    # jitter/length/black_frames under a pan.
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    geom = [_write_geom_pan(tmp_path / "ep0", "fit", (0, 500, 1000, 1000)),
            _write_geom_pan(tmp_path / "ep1", "fit", (0, 500, 1000, 1000))]
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    # the counts prove the checks ACTUALLY RAN over both episodes — a not-checked
    # fall-through carries a "status" key and neither of these
    assert rep.checks["pad_bars"].passed is True
    assert rep.checks["pad_bars"].detail["bars"] == 2
    assert rep.checks["transitions"].passed is True
    assert rep.checks["transitions"].detail["cuts"] == 1


def test_mixed_reel_checks_the_tracked_episodes_and_names_the_skipped_ones(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    geom = [_write_geom(tmp_path / "ep0", 500.0, 900.0),      # tracked, safe
            _write_geom_pan(tmp_path / "ep1")]                # generated
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["safe_zones"].passed is True            # the tracked one was examined
    assert rep.checks["key_action"].passed is True
    # naming what was NOT examined is what stops "episodes: 2" overstating coverage
    assert rep.checks["safe_zones"].detail["skipped_episodes"] == [1]
    assert rep.checks["key_action"].detail["skipped_episodes"] == [1]


def test_a_pan_at_a_lower_index_does_not_renumber_the_episode_that_is_blamed(tmp_path, monkeypatch):
    # THE INDEX-ATTRIBUTION TEST. A generated episode contributes an EMPTY mark list
    # rather than being dropped: evaluate() enumerates the list it is handed, so
    # FILTERING the pans out would renumber every later episode and send a human to
    # the wrong clip — silently. Here the pan sits BELOW the offender, so a filtered
    # list would report worst_episode 0 for a violation that is episode 1's.
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    geom = [_write_geom_pan(tmp_path / "ep0"),                # generated
            _write_geom(tmp_path / "ep1", 500.0, 1960.0)]     # tracked, fy 0.98 → violates
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["safe_zones"].passed is False
    assert rep.checks["safe_zones"].detail["worst_episode"] == 1      # 0 under a filtering impl
    assert rep.checks["safe_zones"].detail["skipped_episodes"] == [0]
    assert rep.checks["key_action"].detail["skipped_episodes"] == [0]


def test_provenance_not_file_existence_decides_whether_a_route_is_read(tmp_path, monkeypatch):
    # The branch is PathMeta.pan — reframe's own record of what it did — not
    # os.path.exists(route). A stale route.json left beside a generated path is not
    # an observation of THIS crop, so reading it would judge the pan against a
    # subject the pan never followed.
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    geom = [_write_geom_pan(tmp_path / "ep0"),
            _write_geom(tmp_path / "ep1", 500.0, 900.0)]      # tracked, safe
    Path(geom[0][0]).write_text(json.dumps(                   # stray route beside the pan
        [{"t": 0.0, "x": 500.0, "y": 1960.0, "w": 100.0, "h": 200.0},
         {"t": 3.0, "x": 500.0, "y": 1960.0, "w": 100.0, "h": 200.0}]))   # would violate if read
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["safe_zones"].passed is True            # False if the stray file were read
    assert rep.checks["safe_zones"].detail["skipped_episodes"] == [0]


def test_an_all_tracked_reel_is_untouched_by_the_pan_branch(tmp_path, monkeypatch):
    # pins that this fix changed nothing for a reel with no pan in it: the offender
    # is still named by its own index, and no skipped_episodes key appears at all.
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    geom = [_write_geom(tmp_path / "ep0", 500.0, 900.0),      # safe
            _write_geom(tmp_path / "ep1", 500.0, 1960.0)]     # violates
    rep = check_reel.run("m.mp4", ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["safe_zones"].passed is False
    assert rep.checks["safe_zones"].detail["worst_episode"] == 1
    assert "skipped_episodes" not in rep.checks["safe_zones"].detail
    assert "skipped_episodes" not in rep.checks["key_action"].detail
