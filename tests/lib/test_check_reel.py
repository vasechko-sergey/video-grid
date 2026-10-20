import json
from pathlib import Path

import imagehash
import pytest

from scripts import check_reel
from scripts.lib import color_fidelity, models, provenance, reel_orchestration
from scripts.lib import outro as outro_mod
from scripts.lib.models import CheckResult, ReelCheckSpec, ReelFailure


class _Stub:
    """Stub the ffmpeg-touching helpers so check_reel logic is unit-testable.
    durations: per-episode seconds. blacks: black_start times on the master.
    hashes: {t: int} used as a fake ImageHash distance base."""
    def __init__(self, durations, blacks=(), hashes=None):
        self.durations = durations
        self.blacks = list(blacks)
        self.hashes = hashes or {}

    def install(self, monkeypatch):
        eps_dur = iter(self.durations + [sum(self.durations)])  # episodes..., then master
        monkeypatch.setattr(check_reel, "_probe_dur", lambda v: next(eps_dur))
        monkeypatch.setattr(check_reel, "_black_hits", lambda m: self.blacks)
        monkeypatch.setattr(check_reel, "_phash_bits",
                            lambda v, t: self.hashes.get(round(t, 3), 0), raising=False)
        monkeypatch.setattr(check_reel, "_hamming", lambda a, b: abs(a - b), raising=False)


def _master(tmp_path):
    """A real (dummy-content) master file. `run` now hashes the master for
    ReelReport.master_digest (design §4) — a literal "m.mp4" that names no real file
    no longer works here, unlike every other path `run` takes (those stay fake
    strings because `_Stub` reroutes every function that would touch them)."""
    p = tmp_path / "m.mp4"
    p.write_bytes(b"master-bytes")
    return str(p)


def test_length_passes_within_half_second(tmp_path, monkeypatch):
    _Stub([3.0, 3.0]).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["length"].passed is True
    assert rep.checks["black"].passed is True


def test_length_fails_and_attributes_to_pacing(tmp_path, monkeypatch):
    _Stub([3.0, 4.0]).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["length"].passed is False and rep.overall is False
    f = [x for x in rep.fail_reasons if x.check == "length"][0]
    assert f.escalate_to == "pacing" and f.episode_idx is None


def test_black_hit_attributes_to_the_owning_episode(tmp_path, monkeypatch):
    # a black frame at t=4.0 lands in episode 1 (spans 3.0..6.0)
    _Stub([3.0, 3.0], blacks=[4.0]).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["black"].passed is False
    f = [x for x in rep.fail_reasons if x.check == "black"][0]
    assert f.episode_idx == 1 and f.escalate_to == "reprocess"


def test_beat_loudness_safe_zones_not_checked_when_silent(tmp_path, monkeypatch):
    # distinct hashes so the variety check passes (see the color/variety tests).
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    # all three now read "not-checked" — beat/loudness lack audio, safe_zones lacks geometry.
    for name in ("beat", "loudness", "safe_zones"):
        assert rep.checks[name].passed is None
        assert rep.checks[name].detail["status"] == "not-checked"
    assert rep.overall is True
    assert rep.wall_s >= 0.0 and rep.episode_count == 2


def test_the_loudness_reason_does_not_call_a_pre_mix_reel_silent(tmp_path, monkeypatch):
    """build_reel checks the picture BEFORE it mixes, so a reel WITH music reads this
    reason on its first round. "(silent reel)" there made a real run's agent conclude
    the music had been lost (retro R10.11)."""
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    reason = rep.checks["loudness"].detail["reason"]
    assert "silent reel" not in reason
    assert "mixed after the picture passes" in reason


def test_no_across_cut_colour_check_is_reported(tmp_path, monkeypatch):
    """The across-cut colour check is retired (design 2026-08-29 §2). It compared two
    frames straddling a cut — two different SHOTS — so six of the only real reel's
    seven cuts exceeded the 12.0 default and the operator raised the ceiling to 56.0
    to switch it off. Its absence is pinned here: re-adding the key would make this
    fail, and would also silently re-arm a corrector that can only damage the grade."""
    # distinct hashes so the variety check passes — this test's overall=True is about
    # the retired colour check, not an incidental variety failure (see the identical
    # fix, with the same comment, on test_beat_loudness_safe_zones_not_checked_when_silent).
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0), str(tmp_path / "r.json"))
    assert "color_across_cuts" not in rep.checks
    assert not [f for f in rep.fail_reasons if f.check == "color_across_cuts"]
    assert rep.overall is True


def test_variety_flags_a_near_duplicate_pair(tmp_path, monkeypatch):
    # ep0 and ep1 identical hash (distance 0 < variety_min) → fail, blame ep1
    _Stub([3.0, 3.0], hashes={1.5: 100, 4.5: 100}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0, variety_min=8), str(tmp_path / "r.json"))
    assert rep.checks["variety"].passed is False
    f = [x for x in rep.fail_reasons if x.check == "variety"][0]
    assert f.episode_idx == 1 and f.escalate_to == "edit-plan"


def test_variety_passes_for_distinct_episodes(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0, variety_min=8), str(tmp_path / "r.json"))
    assert rep.checks["variety"].passed is True


def test_variety_passes_at_exactly_the_threshold(tmp_path, monkeypatch):
    # distance == variety_min must PASS (spec: Hamming >= variety_min); guards the < boundary
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 8}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0, variety_min=8), str(tmp_path / "r.json"))
    assert rep.checks["variety"].passed is True


def test_variety_failure_report_is_json_serializable_with_real_hamming(tmp_path, monkeypatch):
    # regression: the REAL _hamming (numpy.int64) must survive rep.write()'s json.dumps.
    # Stub everything EXCEPT _hamming, and feed real ImageHash objects via _phash_bits.
    durs = iter([3.0, 3.0, 6.0])                       # ep0, ep1, then master
    monkeypatch.setattr(check_reel, "_probe_dur", lambda v: next(durs))
    monkeypatch.setattr(check_reel, "_black_hits", lambda m: [])
    same = imagehash.hex_to_hash("0000000000000000")   # identical → distance 0 < variety_min → fail
    monkeypatch.setattr(check_reel, "_phash_bits", lambda v, t: same)
    # _hamming is intentionally NOT stubbed → the real numpy-returning path runs
    out = tmp_path / "r.json"
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0), str(out))
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
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["safe_zones"].passed is True
    assert rep.checks["safe_zones"].detail["advisory"] is True


def test_safe_zones_flags_low_subject_but_stays_advisory(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    geom = [_write_geom(tmp_path / "ep0", 500.0, 900.0),      # safe
            _write_geom(tmp_path / "ep1", 500.0, 1960.0)]     # fy 0.98 → under tiktok caption band
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
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
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
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
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["pad_bars"].passed is False and rep.checks["pad_bars"].detail["worst_episode"] == 1
    assert rep.checks["transitions"].passed is False and rep.checks["transitions"].detail["worst_cut"] == 0
    assert rep.overall is True and not rep.fail_reasons


def test_editorial_checks_not_checked_when_silent(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
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
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.episode_count == 2 and rep.overall is True


def test_all_pan_reel_states_the_absence_instead_of_passing_vacuously(tmp_path, monkeypatch):
    # evaluate() over a list of empty lists returns pass=True — a green tick for
    # having examined nothing, the same shape checks.continuity([]) has one level
    # down. It must be stated, not fallen through.
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    geom = [_write_geom_pan(tmp_path / "ep0"), _write_geom_pan(tmp_path / "ep1")]
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
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
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
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
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
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
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
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
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["safe_zones"].passed is True            # False if the stray file were read
    assert rep.checks["safe_zones"].detail["skipped_episodes"] == [0]


def test_an_all_tracked_reel_is_untouched_by_the_pan_branch(tmp_path, monkeypatch):
    # pins that this fix changed nothing for a reel with no pan in it: the offender
    # is still named by its own index, and no skipped_episodes key appears at all.
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    geom = [_write_geom(tmp_path / "ep0", 500.0, 900.0),      # safe
            _write_geom(tmp_path / "ep1", 500.0, 1960.0)]     # violates
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["safe_zones"].passed is False
    assert rep.checks["safe_zones"].detail["worst_episode"] == 1
    assert "skipped_episodes" not in rep.checks["safe_zones"].detail
    assert "skipped_episodes" not in rep.checks["key_action"].detail


def test_check_reel_names_the_tracked_episode_missing_its_route(tmp_path, monkeypatch):
    # THE GUARD's missing twin, one level up. check_episode has refused a
    # route_path of None against a pan=false sidecar since the pan slice landed
    # (scripts/check_episode.py ~line 96); check_reel's geometry section never
    # grew the symmetric check, so a hand-authored (or agent-authored) reel
    # manifest whose route/pan fields contradict each other — sidecar says
    # tracked, but ReelEpisode.route is None — fell through to
    # route_from_json(None) and died inside pathlib, naming neither the episode
    # nor a remedy. Unreachable via edl_to_reel (it derives both values from the
    # same manifest field so they cannot diverge there); reachable via
    # build_reel's own CLI on a manifest carrying an inconsistent "route": null.
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    ep0 = _write_geom(tmp_path / "ep0", 500.0, 900.0)         # tracked, fine
    _, p1, m1 = _write_geom(tmp_path / "ep1", 500.0, 900.0)   # tracked (pan=false)...
    geom = [ep0, (None, p1, m1)]                              # ...but its route is None
    with pytest.raises(ValueError) as e:
        check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                       str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    msg = str(e.value)
    assert "episode 1" in msg                  # names the OFFENDING episode, not "an episode"
    assert "pan=false" in msg                  # the sidecar's own provenance phrasing
    assert "route_path is None" in msg
    assert "re-render with a pan" in msg       # the remedy, not just the complaint


def test_run_stamps_the_master_digest(tmp_path, monkeypatch):
    # design §4: check_reel is ReelReport.master_digest's only producer, and it always
    # stamps — deliver (Task 3) refuses a report with no digest as proof it did not
    # come from check_reel. A real file (not _master's fixed dummy bytes) so the
    # digest is unambiguously tied to THIS master's own content.
    master = tmp_path / "master.mp4"
    master.write_bytes(b"master-bytes")
    _Stub([3.0, 3.0]).install(monkeypatch)
    rep = check_reel.run(str(master), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    assert rep.master_digest == provenance.digest_file(master)


# --- pacing-fixed-point Task 5: the advisory `outro` residual (design 2026-08-16 §6) ---
# One episode is enough for all four: _Stub's install rule is master == sum(durations), so
# a single-episode _Stub([X]) puts the master at exactly X seconds with no second number to
# reconcile. No real ffmpeg — outro is a plain dict, untouched by any of the probes _Stub
# reroutes. target_dur is pinned to the same X in every case so the (unrelated) length gate
# stays trivially true and `overall` reflects only what each test means to exercise.

GAP = {"reel_dur": 10.7, "line": 10.2, "fade": 0.5, "tail": 1.8,
       "rung": "gap", "moved": 0.7, "brief_len": None}


def test_no_outro_key_at_all_when_no_fit_ran(tmp_path, monkeypatch):
    _Stub([10.7]).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4"], ReelCheckSpec(target_dur=10.7),
                         str(tmp_path / "r.json"), outro=None)
    assert "outro" not in rep.checks


def test_an_unchanged_rung_reports_n_a_not_a_measurement(tmp_path, monkeypatch):
    _Stub([10.7]).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4"], ReelCheckSpec(target_dur=10.7),
                         str(tmp_path / "r.json"),
                         outro={**GAP, "rung": "unchanged", "line": None})
    assert rep.checks["outro"].passed is None
    assert rep.checks["outro"].detail["status"] == "n/a"


def test_the_residual_is_the_master_against_the_length_the_fit_asked_for(tmp_path, monkeypatch):
    _Stub([10.68]).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4"], ReelCheckSpec(target_dur=10.68),
                         str(tmp_path / "r.json"), outro=GAP)
    # Whole-object equality (project convention), not a subset of asked/delivered/
    # residual — line/fade/rung/tol/advisory are real fields of the same detail dict
    # and deserve the same protection against a silent regression.
    assert rep.checks["outro"] == CheckResult("outro", True, {
        "line": 10.2, "fade": 0.5, "rung": "gap", "asked": 10.7, "delivered": 10.68,
        "residual": -0.02, "tol": check_reel._LENGTH_TOL, "advisory": True})


def test_a_residual_past_the_reporting_tolerance_is_flagged_but_advisory(tmp_path, monkeypatch):
    _Stub([9.9]).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4"], ReelCheckSpec(target_dur=9.9),
                         str(tmp_path / "r.json"), outro=GAP)
    assert rep.checks["outro"].passed is False
    assert rep.overall is True


# --- named-absence Task 3: the outro reason names WHICH absence (design
# 2026-09-07-named-absence-design.md §3) ----------------------------------------


def test_the_outro_check_does_not_claim_a_fit_ran_when_none_did(tmp_path, monkeypatch):
    """The one sentence check_reel printed for every unchanged fit — "the fit chose no
    bar line" — is true only for 'no-reachable-line'. On the real run the cause was
    'no-bars' and no fit had run (design §0.1)."""
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0), str(tmp_path / "r.json"),
                         outro={"rung": "unchanged", "cause": "no-bars"})
    assert rep.checks["outro"] == CheckResult("outro", None, {
        "status": "n/a", "cause": "no-bars",
        "reason": outro_mod.CAUSE_WHY["no-bars"], "advisory": True})
    assert rep.overall is True


def test_an_outro_with_no_recorded_cause_reads_as_not_recorded(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0), str(tmp_path / "r.json"),
                         outro={"rung": "unchanged"})
    assert rep.checks["outro"].detail["cause"] == ""
    assert rep.checks["outro"].detail["reason"] == outro_mod.CAUSE_WHY[""]


# --- named-absence Task 5: `brief_length`, the one length not derived from the cut
# (design 2026-09-07-named-absence-design.md §4) --------------------------------


def test_brief_length_measures_the_reel_against_the_length_that_was_asked_for(tmp_path, monkeypatch):
    """The real run: a 45.0s brief delivered as 34.93s, past every gate, because the
    only length anything compared against came from the cut (design §0.2)."""
    # the two episode midpoints are 17.465/2=8.7325 and 17.465*1.5=26.1975; _Stub's
    # lookup does round(t, 3) (8.732 / 26.197), so the hash keys are given at THAT
    # precision — keying at the unrounded 4-decimal midpoint would never match and
    # both episodes would silently collide on the fallback 0, failing variety on a
    # test that has nothing to do with variety.
    _Stub([17.465, 17.465], hashes={8.732: 0, 26.197: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=34.93), str(tmp_path / "r.json"),
                         brief_len=45.0)
    assert rep.checks["brief_length"] == CheckResult("brief_length", False, {
        "brief": 45.0, "delivered": 34.93, "gap": -10.07, "gap_frac": -0.2238,
        "budget": 1.5, "advisory": True})
    # length itself still passes — it is measured against the cut's own target
    assert rep.checks["length"].passed is True


def test_brief_length_is_advisory_and_cannot_block(tmp_path, monkeypatch):
    # see the identical hash-precision note on the test above
    _Stub([17.465, 17.465], hashes={8.732: 0, 26.197: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=34.93), str(tmp_path / "r.json"),
                         brief_len=45.0)
    assert rep.checks["brief_length"].passed is False
    assert rep.overall is True
    assert not [f for f in rep.fail_reasons if f.check == "brief_length"]


def test_brief_length_passes_inside_the_budget_the_pipeline_already_absorbs(tmp_path, monkeypatch):
    """_LENGTH_TOL (0.5) + length_retime_max (1.0) is what the conveyor already says
    it absorbs without comment. Not a measured answer to how far a reel may drift
    from its brief — the least-invented number available (design §4.3)."""
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0), str(tmp_path / "r.json"),
                         brief_len=7.5)
    assert rep.checks["brief_length"].passed is True     # gap -1.5, exactly the budget


def test_brief_length_treats_over_and_under_alike(tmp_path, monkeypatch):
    """The borrowed budget is one-sided — reel_orchestration absorbs a shortfall only,
    because mix.mix refuses dur > music.duration. That reason is a mixer constraint
    and says nothing about a brief, so it is deliberately not carried over (§4.3)."""
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0), str(tmp_path / "r.json"),
                         brief_len=4.4)
    assert rep.checks["brief_length"].passed is False    # gap +1.6, past the budget
    assert rep.checks["brief_length"].detail["gap"] == 1.6


def test_no_brief_reads_as_not_checked_never_as_on_target(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                         ReelCheckSpec(target_dur=6.0), str(tmp_path / "r.json"))
    assert rep.checks["brief_length"].passed is None
    assert rep.checks["brief_length"].detail["status"] == "not-checked"


# --- grade-sensor-references Task 6: grade_faithful, judged against the DECLARED
# chain (design 2026-08-31 §2) ---
# predicted/tone_target/tone_dsts are PARALLEL lists, the same idiom `geometry=`
# already uses — check_reel.run must stay callable from its own CLI, which supplies
# none of them. The ruler (color_measure.clip_percentiles_batch) is stubbed directly
# per test, at the master-relative sample times it was asked for.


def _run_reel(tmp_path, predicted=None, tone_target=None, tone_dsts=None, chroma=None):
    """Two-episode grade_faithful harness. `_Stub(...).install(...)` needs a
    monkeypatch of its own — a bare `pytest.MonkeyPatch.context()` rather than the
    fixture — so a caller's OWN `monkeypatch.setattr(check_reel.color_measure, ...)`
    (applied directly to the module before this runs) stays in effect for the
    `check_reel.run` call below, while this helper's stub of the unrelated
    ffmpeg-touching functions cleans itself up the moment the call returns.

    chroma= (fix round 1, FINDING 1): threaded through the same way as
    predicted/tone_target/tone_dsts above, so a chroma-spread test can drive
    the real run() wiring instead of calling _chroma_spread_check directly."""
    with pytest.MonkeyPatch.context() as mp:
        _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(mp)
        return check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"],
                              ReelCheckSpec(target_dur=6.0), str(tmp_path / "r.json"),
                              predicted=predicted, tone_target=tone_target, tone_dsts=tone_dsts,
                              chroma=chroma)


def test_grade_faithful_passes_when_the_master_matches_every_prediction(monkeypatch, tmp_path):
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2)
    c = rep.checks["grade_faithful"]
    assert c.passed is True
    assert c.detail["worst"] == 0.0
    assert "tone_match" not in rep.checks


def test_grade_faithful_judges_EVERY_episode_not_only_the_bound_ones(monkeypatch, tmp_path):
    """Faithfulness is a property of any declaration, including an empty one. The
    old not-bound skip is gone (design §2.1)."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2,
                    tone_target=(52.0, 104.0, 192.0), tone_dsts=[None, None])
    assert rep.checks["grade_faithful"].detail["residuals"] == {"0": 0.0, "1": 0.0}
    assert rep.checks["grade_faithful"].detail["not_checked"] == {}


def test_grade_faithful_fails_and_routes_to_process_episode(monkeypatch, tmp_path):
    """A dropped colour block is a render that did not get its declaration; the
    remedy is a re-render, not a re-authoring."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0), (20.0, 104.0, 192.0)])
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2)
    assert rep.checks["grade_faithful"].passed is False
    f = [x for x in rep.fail_reasons if x.check == "grade_faithful"][0]
    assert f.escalate_to == "process-episode"
    assert f.episode_idx == 1


def test_grade_faithful_is_not_checked_without_predictions(tmp_path):
    rep = _run_reel(tmp_path, predicted=None)
    c = rep.checks["grade_faithful"]
    assert c.passed is None
    assert c.detail["reason"] == "no-predictions"


def test_grade_faithful_is_not_checked_when_every_prediction_fails_to_build(tmp_path):
    """fix round 1, Important 1: the vacuous-check guard — every episode's prediction
    failed to build, so the check examined zero pixels. passed=True here would be a
    green tick for having looked at nothing, the same shape the all-pan safe_zones
    branch refuses. This is a DIFFERENT absence than `predicted=None` above (that one
    never even reaches the per-episode loop): here `predicted` exists but names no
    episode as plannable, so `not_checked` is populated for every index and `reason`
    is `no-episode-predicted`, not `no-predictions`. This survived the tone_match ->
    grade_faithful rename (`no-episode-bound` -> `no-episode-predicted`) with no test
    at all — `clip_percentiles_batch` need not even be stubbed, since `spans` stays
    empty and the ruler is never called."""
    rep = _run_reel(tmp_path, predicted=[None, None])
    c = rep.checks["grade_faithful"]
    assert c.passed is None
    assert c.detail["reason"] == "no-episode-predicted"
    assert c.detail["not_checked"] == {"0": "no-prediction", "1": "no-prediction"}


def test_grade_faithful_passes_at_exactly_the_threshold(monkeypatch, tmp_path):
    """fix round 1, Important 2: residual == grade_residual_max must PASS — guards the
    <= vs < boundary. Nothing else in the suite puts `worst` anywhere near 4.0."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0), (56.0, 104.0, 192.0)])
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2)
    c = rep.checks["grade_faithful"]
    assert c.passed is True
    assert c.detail["worst"] == 4.0


def test_a_narrowly_failing_residual_is_distinguishable_from_the_max(monkeypatch, tmp_path):
    """fix round 1, Important 3: `ok` is decided on the UNROUNDED worst, but the
    reported residual is rounded to 2 decimals — a worst of 4.04 must still fail
    (4.04 > 4.0), and a reader must be able to see WHY from the report alone instead
    of a residual that rounds to look identical to the ceiling it just missed. The
    routed `ReelFailure.detail` must carry the same two numbers the report does, so
    whoever reads process-episode's remedy sees the same evidence."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0), (56.04, 104.0, 192.0)])
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2)
    c = rep.checks["grade_faithful"]
    assert c.passed is False
    assert c.detail["worst"] == 4.04
    assert c.detail["residuals"] == {"0": 0.0, "1": 4.04}
    f = [x for x in rep.fail_reasons if x.check == "grade_faithful"][0]
    assert f.detail == {"residual": 4.04, "max": 4.0}


def test_a_missing_prediction_is_NAMED_never_silently_passed(monkeypatch, tmp_path):
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0), None])
    d = rep.checks["grade_faithful"].detail
    assert d["not_checked"] == {"1": "no-prediction"}
    assert "1" not in d["residuals"]


def test_target_dev_is_advisory_and_only_for_bound_episodes(monkeypatch, tmp_path):
    """The agreement signal survives as a number, not a gate — design §2.1's own
    worked example: the conductor authored tone_dst = target for episode 0 (BOUND),
    but its full declared chain — tone plus whatever post-tone knobs ride beside it —
    predicts (52.0, 104.0, 179.5), 12.5 off the (52.0, 104.0, 192.0) target on the p95
    anchor alone. The render is completely FAITHFUL to that prediction (the master's
    own pixels match it exactly), so the BLOCKING check passes with worst=0.0 — 12.5
    shows up ONLY in target_dev, and must not touch `passed`. Episode 1 is unbound
    (tone_dst is None) and stays out of target_dev entirely regardless of its own
    residual.

    fix round 1, Important 4: the PREVIOUS fixture here used a bound episode whose
    target_dev happened to be 0.0 — indistinguishable from a WRONG implementation
    that folds target_dev into the gate (`ok = worst <= max and all(v <= max for v in
    target_dev.values())` also passes a 0.0-target_dev fixture). This one's
    target_dev (12.5) is past grade_residual_max (4.0), so a gating implementation
    would flip `passed` to False here and this test would catch it — verified by
    making exactly that mutation, confirming this test goes RED, and reverting it."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 179.5), (52.0, 104.0, 192.0)])
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 179.5), (52.0, 104.0, 192.0)],
                    tone_target=(52.0, 104.0, 192.0),
                    tone_dsts=[[52.0, 104.0, 192.0], None])
    d = rep.checks["grade_faithful"].detail
    assert d["target_dev"] == {"0": 12.5}
    assert d["worst"] == 0.0
    assert rep.checks["grade_faithful"].passed is True     # advisory never blocks


def test_predicted_must_be_parallel_to_the_episodes(tmp_path):
    with pytest.raises(ValueError, match="parallel"):
        _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)])   # 1 for 2 episodes


# `_same_target`/`_TONE_BIND_EPS` are unchanged carryovers from tone_match — they now
# decide target_dev's bound-ness instead of the blocking check's — so their own edge
# cases (carried from the old block) still need a test, even though target_dev itself
# no longer gates anything.

def test_a_non_numeric_tone_dst_refuses_loud_instead_of_crashing_bare(monkeypatch, tmp_path):
    """`_same_target` still runs for EVERY tone_target'd reel, computing target_dev.
    reframe refuses a malformed tone pair long before a reel is assembled, but ONLY on
    the edl_to_reel path — build_reel's own CLI reads an arbitrary reel-manifest JSON
    with no such validation upstream, so a hand-edited or corrupt manifest CAN hand a
    non-numeric tone_dst here. Refusing it loud, with a remedy, beats letting
    `abs(a - b)` inside _same_target raise a bare, unattributed TypeError."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    with pytest.raises(ValueError, match="tone_dst") as e:
        _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2,
                 tone_target=(52.0, 104.0, 192.0), tone_dsts=[["a", "b", "c"], None])
    assert "not a triple of luma numbers" in str(e.value)


def test_one_luma_code_of_difference_excludes_an_episode_from_target_dev(monkeypatch, tmp_path):
    """The binding tolerance _TONE_BIND_EPS must not swallow a real difference: 1 code
    is the smallest color.percentiles can report, and color.TONE_MIN_GAP (the gap two
    anchors must keep to stay orderable at all) is 6 — so a 1-code-off tone_dst is NOT
    the reel's target, and must not appear in target_dev."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2,
                    tone_target=(52.0, 104.0, 192.0),
                    tone_dsts=[[52.0, 105.0, 192.0], None])
    assert rep.checks["grade_faithful"].detail["target_dev"] == {}


def test_a_tone_dst_that_only_round_tripped_through_json_still_lands_in_target_dev(monkeypatch, tmp_path):
    """The manifest's pair may be a LIST OF INTS; the reel target is a tuple of floats.
    They are the same numbers — an equality that type-sniffed would wrongly exclude a
    genuinely bound episode from target_dev."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2,
                    tone_target=(52.0, 104.0, 192.0), tone_dsts=[[52, 104, 192], None])
    assert rep.checks["grade_faithful"].detail["target_dev"] == {"0": 0.0}


def test_target_dev_refuses_a_missing_tone_dsts_list_instead_of_going_silent(monkeypatch, tmp_path):
    """fix round 1, Important 5: a caller who passes tone_target but forgets the
    parallel tone_dsts list entirely used to get a silently-empty target_dev, reading
    exactly like "the conductor skipped every episode" — a fact about the reel, not
    about a caller's own bug. Refuse loud instead, matching the old tone_match's own
    guard (this rename had dropped it)."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    with pytest.raises(ValueError, match="parallel lists"):
        _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2,
                 tone_target=(52.0, 104.0, 192.0))    # tone_dsts omitted


def test_target_dev_refuses_a_short_tone_dsts_list_rather_than_crashing_bare(monkeypatch, tmp_path):
    """fix round 1, Important 5: without a length guard, a too-short tone_dsts list
    raises a bare, unattributed IndexError at dsts[i] instead of naming the caller's
    mistake and the fix — the exact class of bug _same_target's own docstring
    (three lines above) says this module refuses rather than lets happen."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    with pytest.raises(ValueError, match="parallel lists"):
        _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2,
                 tone_target=(52.0, 104.0, 192.0), tone_dsts=[[52.0, 104.0, 192.0]])   # 1 for 2


# --- final review I-3: an empty target_dev must say WHY (design §9.7) ---------

def test_target_dev_names_no_target_when_none_was_supplied(monkeypatch, tmp_path):
    """With no EDL.tone_target at all, target_dev is empty for the obvious reason —
    there is no common target to compare against. A wrong implementation that never
    set target_dev_reason (the bug final review I-3 found: this state was
    indistinguishable from "a target exists but nothing is bound to it") would leave
    the key missing or always None here."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2)   # tone_target omitted
    d = rep.checks["grade_faithful"].detail
    assert d["target_dev"] == {}
    assert d["target_dev_reason"] == "no-target"


def test_target_dev_names_no_episode_bound_when_the_target_exists_but_nothing_binds(
        monkeypatch, tmp_path):
    """A target exists, but every episode's tone_dst is either None or off by more
    than _TONE_BIND_EPS — the SAME empty {} a missing target produces, but a
    different fact about the reel (a conductor that ran and skipped everyone, or a
    hand-authored pair, rather than a conductor that never ran at all). An
    implementation that special-cased only `tone_target is None` (fixing the test
    above by hardcoding target_dev_reason from that one condition, never checking
    whether target_dev actually ended up populated) would still report None or the
    wrong string here."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2,
                    tone_target=(52.0, 104.0, 192.0),
                    tone_dsts=[[52.0, 105.0, 192.0], None])   # 1 code off; None
    d = rep.checks["grade_faithful"].detail
    assert d["target_dev"] == {}
    assert d["target_dev_reason"] == "no-episode-bound"


def test_target_dev_reason_is_none_once_something_is_bound(monkeypatch, tmp_path):
    """The control for the two tests above: once at least one episode really is
    bound, target_dev is non-empty and target_dev_reason must go back to None — an
    implementation that always names a reason whenever tone_target is not None
    (ignoring whether target_dev ended up empty) would fail this one instead."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2,
                    tone_target=(52.0, 104.0, 192.0),
                    tone_dsts=[[52.0, 104.0, 192.0], None])
    d = rep.checks["grade_faithful"].detail
    assert d["target_dev"] == {"0": 0.0}
    assert d["target_dev_reason"] is None


def test_grade_faithful_is_blocking(tmp_path, monkeypatch):
    """A property of ANOTHER module this check silently depends on: models._ADVISORY_CHECKS
    is what ReelReport.overall excludes, so adding "grade_faithful" there would leave every
    assertion above passing while the gate stopped blocking anything."""
    assert "grade_faithful" not in models._ADVISORY_CHECKS


def test_grade_faithful_escalates_and_is_never_reprocessed():
    """Also another module's property. A re-render cannot fix what a re-render broke by
    itself here — but it CAN fix a render that dropped its own declaration, which is
    exactly why this escalates to process-episode rather than looping: a re-render IS
    the remedy, just not one reel_orchestration should retry on its own without a human
    noticing (_REPROCESS_CLASS stays ("black",) — see orchestration's own docstring)."""
    assert "grade_faithful" not in reel_orchestration._REPROCESS_CLASS
    f = ReelFailure("grade_faithful", "process-episode", 1, {"residual": 30.0, "max": 4.0})
    action = reel_orchestration.next_action([f], attempts={}, cap=3)
    assert action.kind == "escalate"
    assert action.finding["escalate_to"] == "process-episode" and action.finding["episode_idx"] == 1


def test_a_passing_variety_reports_the_nearest_pair_it_measured(tmp_path, monkeypatch):
    """A pass used to report `{}` — every distance computed and none kept, so the
    worst junction was re-derived by hand on three separate days of the only real
    run (retro R6). The measurement now survives the pass (design 2026-09-07 §2)."""
    # ep0..ep2 at hashes 0, 1000, 1020 → pair distances 1000 and 20; both clear a
    # variety_min of 8, and the nearest pair is (1, 2) at 20.
    _Stub([3.0, 3.0, 3.0], hashes={1.5: 0, 4.5: 1000, 7.5: 1020}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4", "c.mp4"],
                         ReelCheckSpec(target_dur=9.0, variety_min=8),
                         str(tmp_path / "r.json"))
    assert rep.checks["variety"] == CheckResult(
        "variety", True, {"min_distance": 20, "pair": [1, 2], "min": 8})


def test_a_failing_variety_still_reports_the_global_minimum(tmp_path, monkeypatch):
    """The value is unchanged wherever a failure exists, and that is provable: if any
    pair is below variety_min then the global minimum IS that pair. Pinned so a later
    reader can see the fail path was not quietly re-specified (design §2.1)."""
    # pair (0,1) distance 4 fails; pair (1,2) distance 1000 passes.
    _Stub([3.0, 3.0, 3.0], hashes={1.5: 0, 4.5: 4, 7.5: 1004}).install(monkeypatch)
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4", "c.mp4"],
                         ReelCheckSpec(target_dur=9.0, variety_min=8),
                         str(tmp_path / "r.json"))
    assert rep.checks["variety"] == CheckResult(
        "variety", False, {"min_distance": 4, "pair": [0, 1], "min": 8})
    f = [x for x in rep.fail_reasons if x.check == "variety"][0]
    assert f == ReelFailure("variety", "edit-plan", 1, {"pair": [0, 1], "distance": 4})


def test_a_passing_variety_report_survives_json(tmp_path, monkeypatch):
    """rep.write() json.dumps the detail. The failing path already had this guard;
    the passing path now carries values too and needs its own."""
    _Stub([3.0, 3.0, 3.0], hashes={1.5: 0, 4.5: 1000, 7.5: 1020}).install(monkeypatch)
    out = tmp_path / "r.json"
    check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4", "c.mp4"],
                   ReelCheckSpec(target_dur=9.0, variety_min=8), str(out))
    d = json.loads(out.read_text())
    # CheckResult.to_dict() flattens the detail dict into the result alongside "pass";
    # a whole-object assertion catches regressions in the "pass" key and stray extra keys.
    assert d["checks"]["variety"] == {"min_distance": 20, "pair": [1, 2], "min": 8, "pass": True}


# --- sensor-provenance Task 4: grade_faithful records the sample count it read
# over (design 2026-09-16 §2.5) ------------------------------------------------

def test_grade_faithful_records_the_sample_count_it_read(monkeypatch):
    """Not color.FRAMES echoed back — the count that actually ran. Changing the
    call must move the field, which is the whole point of recording it: seven
    here, against a color.FRAMES of three."""
    seen = {}

    def fake_batch(master, spans):
        seen["n"] = len(spans[0])
        return [(10.0, 100.0, 200.0) for _ in spans]

    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch", fake_batch)
    monkeypatch.setattr(check_reel.color, "sample_times",
                        lambda dur, frames=7: [dur * (k + 0.5) / 7 for k in range(7)])
    cr, fail = check_reel._grade_faithful_check(
        "master.mp4", [4.0], [], ReelCheckSpec(target_dur=4.0),
        [(10.0, 100.0, 200.0)], None, None)
    assert seen["n"] == 7
    assert cr.detail["frames"] == 7
    assert fail is None


def test_grade_faithful_records_zero_frames_when_nothing_could_be_predicted(monkeypatch):
    """`0` is a true statement that nothing was read — the check examined no
    pixels, and the report says so beside its own not-checked status."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda master, spans: (_ for _ in ()).throw(
                            AssertionError("nothing to read")))
    cr, fail = check_reel._grade_faithful_check(
        "master.mp4", [4.0], [], ReelCheckSpec(target_dur=4.0), [None], None, None)
    assert cr.passed is None
    assert cr.detail["frames"] == 0


# --- chroma-spread Task 5: check_reel.chroma_spread (design
# docs/specs/2026-09-17-chroma-spread-design.md §2.4/§2.5) ---

from scripts.check_reel import _chroma_spread_check


def _reading(c, h):
    # No `region` key (final whole-branch review, FIX 1): ReelEpisode.chroma's
    # reading shape carries only delta_c/delta_h — see its own docstring in
    # scripts/lib/models.py and color_fidelity.shift_from_report's.
    return {"delta_c": c, "delta_h": h}


def test_the_spread_is_the_widest_gap_across_the_reel():
    cr = _chroma_spread_check([_reading(-4.18, -1.22), _reading(-2.72, -0.51),
                               _reading(-0.66, -0.53)], 5.0)
    assert cr.detail["spread_c"] == pytest.approx(3.52)
    assert cr.detail["spread_h"] == pytest.approx(0.71)
    assert cr.detail["worst"] == pytest.approx(3.52)
    assert cr.passed is True


def test_one_episode_graded_the_other_way_fails_the_bar():
    """ep0 of the only real reel: the sole episode whose grade RAISED chroma, 8.35
    dH* from its three siblings, on the opening shot (design §0.6).

    design §2.5 quotes this reel's cross-episode spread as "6.90 / 9.07" — the
    full-precision figure behind §0.6's 2-decimal display table. Recomputing
    max(hs) - min(hs) from the TABLE's own rounded literals (7.84 and -1.22, as
    used below) gives 9.06, not 9.07: verified directly (`7.84 - (-1.22)` is
    9.06 to 20 decimal places, not a float-representation artifact near a
    rounding boundary). ep0's own per-frame noise is called out in §0.6 as far
    higher than its three siblings' (1.81/1.91 vs 0.06-0.19), consistent with a
    full-precision median that doesn't survive 2-decimal display rounding
    without shifting this subtraction by a cent. 9.06 is what this exact
    algorithm computes from these exact literals — pinned here, not loosened."""
    cr = _chroma_spread_check([_reading(2.72, 7.84), _reading(-4.18, -1.22),
                               _reading(-2.72, -0.51), _reading(-0.66, -0.53)], 5.0)
    assert cr.detail["worst"] == pytest.approx(9.06)
    assert cr.passed is False


def test_the_bar_is_inclusive_at_the_boundary():
    """Task 7's mutation battery, row 14: `worst <= bar` must PASS a worst that
    lands EXACTLY on the bar, not only strictly under it — nothing before this
    test pinned that side of the boundary (every other case here is comfortably
    clear of its own bar). A `worst < bar` mutant fails only the '<=' arm; this
    is what would go red against it.

    Strengthened, final whole-branch review, FIX 3: the original version of this
    test used _reading(0.0, 0.0) / _reading(5.0, 0.0), whose subtraction is EXACT
    in floating point — 5.0 - 0.0 == 5.0 to the bit — so it stayed green even
    while `_chroma_spread_check` compared the UNROUNDED spread against `bar` and
    only rounded the value afterward for display. -6.97 / -11.97 is the reviewer's
    own reproduction of the bug that boundary hid: their difference is
    5.000000000000001, a hair over the bar in raw floating point even though it
    is exactly 5.0 once rounded to 2 decimals, the precision the report actually
    shows. Verified RED against the unrounded comparison (`worst = max(spread_c,
    spread_h)` computed and compared before either was rounded) before this slice
    rounded first and judged the rounded value; see check_reel._chroma_spread_check."""
    cr = _chroma_spread_check([_reading(-6.97, 0.0), _reading(-11.97, 0.0)], 5.0)
    assert cr.detail["spread_c"] == pytest.approx(5.0)
    assert cr.detail["worst"] == pytest.approx(5.0)
    assert cr.passed is True


def test_the_detail_names_every_episode_and_every_absence():
    cr = _chroma_spread_check(
        [_reading(-1.0, -1.0), {"status": "not-checked", "reason": "no render pair"},
         None], 5.0)
    assert cr.detail["per_episode"] == {"0": [-1.0, -1.0]}
    assert cr.detail["not_checked"]["1"] == "no render pair"
    assert "older" in cr.detail["not_checked"]["2"]


def test_one_reading_is_not_a_spread():
    cr = _chroma_spread_check([_reading(-1.0, -1.0), None], 5.0)
    assert cr.passed is None
    assert cr.detail["status"] == "not-checked"


def test_exactly_two_readings_is_a_real_spread():
    """Fix round 1, RIDER: the multi-reading tests above use three and four
    readings, and the one-reading boundary test immediately above this one
    only pins the "fewer than two" side. A mutation tightening
    `len(per) < 2` to `len(per) <= 2` would treat two real readings as
    not-checked too, and nothing before this test would notice — this pins the
    boundary from the other side, at exactly two."""
    cr = _chroma_spread_check([_reading(-4.18, -1.22), _reading(-2.72, -0.51)], 5.0)
    assert cr.detail["spread_c"] == pytest.approx(1.46)
    assert cr.detail["spread_h"] == pytest.approx(0.71)
    assert cr.detail["worst"] == pytest.approx(1.46)
    assert isinstance(cr.passed, bool)


def test_no_chroma_at_all_is_named_not_zero():
    cr = _chroma_spread_check(None, 5.0)
    assert cr.passed is None
    assert cr.detail["reason"]


def test_a_not_checked_chroma_carrying_a_stray_component_lands_among_the_absences():
    """ReelEpisode.__post_init__ returns at status == "not-checked" once it has a
    non-empty reason, so it ADMITS {"status", "reason", "delta_c"}. The reader used
    to test `"delta_c" in c` first, take that as its reading branch, and subscript
    c["delta_h"]: KeyError (design §0.3, reproduced). Keying on the same
    discriminator the validator uses puts the dict where the validator filed it."""
    mixed = {"status": "not-checked", "reason": "no grade_damage block", "delta_c": 1.0}
    cr = _chroma_spread_check([mixed, _reading(-4.18, -1.22)], 5.0)
    assert cr.detail["not_checked"]["0"] == "no grade_damage block"
    assert "0" not in cr.detail["per_episode"]


def test_a_clean_reading_still_reaches_per_episode():
    """The control for the reorder: the reading branch must not have moved."""
    cr = _chroma_spread_check([_reading(-4.18, -1.22), _reading(-2.72, -0.51)], 5.0)
    assert cr.detail["per_episode"] == {"0": [-4.18, -1.22], "1": [-2.72, -0.51]}


def test_a_reprocessed_episodes_reading_reaches_the_reel_check_without_a_reelepisode(monkeypatch, tmp_path):
    """build_reel builds `chroma` as a plain list and overwrites one entry with
    shift_from_report's output before handing it to check_reel.run — so one of the
    reader's two inlets never touches ReelEpisode.__post_init__ (design 2026-09-21
    §0.3). Since design 2026-09-29 §2.1 that inlet is gated anyway, at the
    producer: shift_from_report validates what it returns through the same
    color_fidelity.validate_chroma the carrier calls. This drives the real run()
    wiring with exactly the value that path produces, so the seam itself — a
    producer's output reaching the reader with no carrier between them — is pinned
    end to end, not only each half.

    Not a build_reel integration test: it pins the shape contract at the seam
    build_reel writes to, not build_reel's own indexing. The driver's wiring is
    tests/lib/test_build_reel.py's business."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    report = {"checks": {"grade_damage": {"region": "crop",
                                          "delta_c": -3.0, "delta_h": 0.5}}}
    fresh = color_fidelity.shift_from_report(report)     # what the reprocess arm writes
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2,
                    chroma=[fresh, _reading(-4.18, -1.22)])
    c = rep.checks["chroma_spread"]
    assert c.detail["per_episode"]["0"] == [-3.0, 0.5]
    assert c.detail["not_checked"] == {}


def test_a_failing_chroma_spread_does_not_fail_the_reel():
    """Advisory end to end: overall is what it would have been (design §3).

    ReelReport's real constructor takes `fail_reasons` (default []) and `wall_s`
    (default 0.0) — the brief's snippet named these `fails`/`duration_s`, which
    do not exist on the dataclass; both already default to a value that makes
    this test's claim true, so they are simply omitted here rather than passed
    under invented names."""
    from scripts.lib.models import CheckResult, ReelReport
    rep = ReelReport(checks={
        "black": CheckResult("black", True, {}),
        "chroma_spread": CheckResult("chroma_spread", False, {"worst": 9.07})})
    assert rep.overall is True


def test_chroma_spread_fails_through_the_real_run_but_never_fails_the_reel(monkeypatch, tmp_path):
    """Fix round 1, FINDING 1: every chroma assertion above either calls the
    private `_chroma_spread_check` directly or hand-builds a `ReelReport` (like
    the test immediately above) — nothing drives check_reel.run()'s own
    chroma_spread wiring. Concrete regression this closes: someone changes
    `_chroma_spread_check` to return a `(CheckResult, fail)` tuple like its
    neighbour `_grade_faithful_check`, and adds a matching
    `if fail is not None: fails.append(fail)` beside the wiring line in run() —
    a reel whose only problem is chroma_spread would silently stop shipping,
    and nothing above this test would notice. Mirrors
    test_grade_faithful_fails_and_routes_to_process_episode's `_run_reel`
    idiom, but for a check that must NEVER escalate: three separate
    assertions, each catching a different way that could go wrong (the check
    not firing at all; `chroma_spread` falling out of `_ADVISORY_CHECKS` so a
    real failure blocks `overall`; and a `ReelFailure` reaching `fail_reasons`,
    which `overall` itself would NOT catch, since it reads only `checks`)."""
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch",
                        lambda m, spans: [(52.0, 104.0, 192.0)] * len(spans))
    chroma = [_reading(2.72, 7.84), _reading(-4.18, -1.22)]   # worst 9.06, well past bar=5.0
    rep = _run_reel(tmp_path, predicted=[(52.0, 104.0, 192.0)] * 2, chroma=chroma)
    assert rep.checks["chroma_spread"].passed is False
    assert rep.overall is True
    assert not any(f.check == "chroma_spread" for f in rep.fail_reasons)


# --- 2026-09-30 threshold surface Task 5: the reason rides the verdict it bought ---
# (design §2.4 item 1.) A bar an author moved is a waiver in numeric clothing, and a waiver whose
# reason is not recorded is how color_delta_max went 12 -> 44 -> 56. The row has to sit in the
# artifact that says PASS, and the artifact is the report ON DISK — the assertions below read the
# file, because a row attached after rep.write() is in memory and nowhere a later reader looks.


def _loudness_run(tmp_path, monkeypatch, spec, measured, **kw):
    """Two episodes, a stem measured at `measured` LUFS, and run()'s own report path."""
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    monkeypatch.setattr(check_reel, "_loudnorm_measure", lambda audio: measured)
    return check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], spec,
                          str(tmp_path / "r.json"), audio="stem.aac", **kw)


def test_an_authored_loudness_band_is_named_in_the_checks_own_detail(tmp_path, monkeypatch):
    rep = _loudness_run(tmp_path, monkeypatch,
                        ReelCheckSpec(target_dur=6.0, loudness_tol=2.0), -14.0,
                        gate_reasons={"loudness_tol": "live room"})
    row = {"field": "loudness_tol", "value": 2.0, "default": 1.0, "why": "live room"}
    assert rep.checks["loudness"].detail["authored"] == [row]
    on_disk = json.loads((tmp_path / "r.json").read_text())
    assert on_disk["checks"]["loudness"]["authored"] == [row]


def test_a_check_whose_bars_were_not_authored_carries_no_authored_key(tmp_path, monkeypatch):
    """Both ways a check can have nothing to name, and neither writes `authored: []`: no set at
    all, and a set that holds a reason for a bar sitting at its DEFAULT — legal, because the
    loader refuses nothing about a value that equals the default, and not a bar that moved."""
    for reasons in ({}, {"loudness_tol": "pinned at the default on purpose"}):
        rep = _loudness_run(tmp_path, monkeypatch, ReelCheckSpec(target_dur=6.0), -14.0,
                            gate_reasons=reasons)
        assert all("authored" not in c.detail for c in rep.checks.values())


def test_the_authored_record_rides_a_PASS_not_only_a_failure(tmp_path, monkeypatch):
    # The whole point: a moved bar that let the reel through is exactly the case a later
    # reader must be able to see. -10 LUFS is 4 off the target — a FAIL at the default band,
    # which the control inside this test shows, and a pass only because the band was moved.
    widened = ReelCheckSpec(target_dur=6.0, loudness_tol=6.0)
    rep = _loudness_run(tmp_path, monkeypatch, widened, -10.0,
                        gate_reasons={"loudness_tol": "live room"})
    assert rep.checks["loudness"].passed is True
    assert rep.checks["loudness"].detail["authored"][0]["value"] == 6.0
    at_default = _loudness_run(tmp_path, monkeypatch, ReelCheckSpec(target_dur=6.0), -10.0)
    assert at_default.checks["loudness"].passed is False


def _write_geom_still(dir_path):
    """A photo episode's sidecars: `still` true, `pan` false, and no route.json."""
    d = Path(dir_path)
    d.mkdir(parents=True, exist_ok=True)
    (d / "path.json").write_text(json.dumps([0, 0]))
    (d / "path.meta.json").write_text(json.dumps(
        {"mode": "fill", "crop_w": 1000, "crop_h": 2000, "crop_y": 0, "src_dims": [1000, 2000],
         "canvas": [1000, 2000], "out_dims": [1000, 2000], "rect_px": [0, 0, 1000, 2000],
         "freedom": 0, "pan": False, "still": True}))
    return (str(d / "route.json"), str(d / "path.json"), str(d / "path.meta.json"))


def test_a_photo_beside_a_tracked_episode_is_named_skipped_not_read_for_a_route(
        tmp_path, monkeypatch):
    """design 2026-10-20 §5: a photo is route-less like a pan — before, check_reel
    raised for a sidecar that said pan=false with no route."""
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    geom = [_write_geom(tmp_path / "ep0", 500.0, 900.0), _write_geom_still(tmp_path / "ep1")]
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["safe_zones"].passed is True
    assert rep.checks["safe_zones"].detail["skipped_episodes"] == [1]
