import json
from pathlib import Path

import imagehash
import pytest

from scripts import check_reel
from scripts.lib import models, provenance, reel_orchestration
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


# --- grade-shipped-pixels Task 6: the convergence gate (design 2026-08-30 §5) ---
# tone_target/tone_dsts are PARALLEL lists, the same idiom `geometry=` already uses —
# check_reel.run must stay callable from its own CLI, which supplies neither. The ruler
# (color_measure.clip_percentiles_batch, fix round 1 minor 1 — ONE decode across every
# BOUND episode's span, not one clip_percentiles call per episode) is stubbed per test
# with the master-relative sample times it was asked for, so these prove the SPAN
# arithmetic too, not just the compare.

TGT = (20.0, 100.0, 200.0)


def _ruler(monkeypatch, profiles):
    """Stub the one ruler. `profiles` is the list of per-BOUND-episode triples the one
    batched call returns, in bound order. `calls` records every invocation's
    (clip, spans) — spans is a list of this call's per-episode sample-time lists — so a
    test can assert WHICH pixels were read, and confirm there is exactly ONE call no
    matter how many episodes it covers (a regression back to one-call-per-episode would
    still pass every value assertion below; only counting/inspecting `calls` catches it)."""
    calls = []

    def fake(clip, spans):
        calls.append((clip, [[round(t, 4) for t in s] for s in spans]))
        return list(profiles)
    monkeypatch.setattr(check_reel.color_measure, "clip_percentiles_batch", fake)
    return calls


def test_tone_match_passes_when_every_episode_lands_on_the_target(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    seen = _ruler(monkeypatch, [(22.0, 104.0, 197.0), (20.0, 100.0, 200.0)])
    master = _master(tmp_path)
    rep = check_reel.run(master, ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), tone_target=TGT, tone_dsts=[list(TGT), list(TGT)])
    assert rep.checks["tone_match"] == CheckResult("tone_match", True, {
        "target": [20.0, 100.0, 200.0], "residuals": {"0": 4.0, "1": 0.0},
        "not_checked": {}, "max": 12.0, "worst": 4.0})
    assert rep.overall is True and not rep.fail_reasons
    # the MASTER, at each episode's own span, at (k+0.5)/3 of it — never the delivered
    # reel — and in exactly ONE call carrying BOTH spans (fix round 1 minor 1: the
    # decode is batched, not one clip_percentiles_batch call per episode).
    assert seen == [(master, [[0.5, 1.5, 2.5], [3.5, 4.5, 5.5]])]


def test_tone_match_fails_and_routes_to_match_grade(tmp_path, monkeypatch):
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    # ep0 landed; ep1's p50 is 30 units off the target — the ungraded shape of §0.6
    _ruler(monkeypatch, [(22.0, 104.0, 197.0), (20.0, 130.0, 200.0)])
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), tone_target=TGT, tone_dsts=[list(TGT), list(TGT)])
    assert rep.checks["tone_match"].passed is False and rep.overall is False
    f = [x for x in rep.fail_reasons if x.check == "tone_match"][0]
    assert f.escalate_to == "match-grade"
    assert f.episode_idx == 1                       # the WORST episode, by name
    assert f.detail == {"residual": 30.0, "max": 12.0}


def test_tone_match_is_not_checked_without_a_target(tmp_path, monkeypatch):
    # match-grade was never run. Absence is not tampering — the same rule the
    # attestation lives by — so the reel does not fail, and the ruler never runs.
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    seen = _ruler(monkeypatch, [])
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"))
    assert rep.checks["tone_match"].passed is None
    assert rep.checks["tone_match"].detail["status"] == "not-checked"
    assert rep.checks["tone_match"].detail["reason"] == "no-target"
    assert "not_checked" not in rep.checks["tone_match"].detail   # nothing to index
    assert rep.overall is True and seen == []
    assert "already carry" not in rep.checks["tone_match"].detail["remedy"]   # nothing graded either


def test_a_graded_reel_with_no_target_says_so_in_the_remedy(tmp_path, monkeypatch):
    """fix round 1, minor 2: the no-target arm used to return early without even
    looking at tone_dsts, so an EDL graded before tone_target existed (or hand-authored
    per-episode pairs with no reel-wide target ever stamped) reported the exact same
    'ship it ungraded' remedy as a reel with NO grading at all — hiding the one fact a
    reader most needs when a reel looks washed out. Does not change the verdict
    (still passed=None, still not-checked): absence of a reel-wide target is not
    tampering, this only makes the remedy honest about what IS on disk."""
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    seen = _ruler(monkeypatch, [])
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), tone_dsts=[[20.0, 100.0, 200.0], None])
    assert rep.checks["tone_match"].passed is None
    assert rep.checks["tone_match"].detail["reason"] == "no-target"
    assert "not_checked" not in rep.checks["tone_match"].detail    # still absent — no target exists
    assert "1/2 episode(s) already carry a tone_dst" in rep.checks["tone_match"].detail["remedy"]
    assert rep.overall is True and seen == []                      # the verdict does not change


def test_tone_match_skips_an_episode_the_conductor_skipped(tmp_path, monkeypatch):
    # ep1 carries no pair at all (flat-source / within-eps) → NAMED, not silently passed.
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    seen = _ruler(monkeypatch, [(20.0, 100.0, 200.0)])
    master = _master(tmp_path)
    rep = check_reel.run(master, ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), tone_target=TGT, tone_dsts=[list(TGT), None])
    assert rep.checks["tone_match"].detail["not_checked"] == {"1": "not-bound"}
    assert rep.checks["tone_match"].detail["residuals"] == {"0": 0.0}
    assert rep.checks["tone_match"].passed is True
    # one call, carrying ONLY ep0's span — the skipped episode's pixels were never read,
    # not merely "read but discarded" (a bare len(seen)==1 cannot tell those apart once
    # the ruler is batched: a bug that fed BOTH spans into one call would also produce
    # exactly one call).
    assert seen == [(master, [[0.5, 1.5, 2.5]])]


def test_a_hand_authored_pair_is_not_bound_to_the_reels_common_target(tmp_path, monkeypatch):
    # The other skip shape: ep1 HAS a pair, but it is the human's, not the reel's.
    # Judging it against the common target would report a failure its grade never claimed.
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    seen = _ruler(monkeypatch, [(20.0, 100.0, 200.0)])
    master = _master(tmp_path)
    rep = check_reel.run(master, ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), tone_target=TGT,
                         tone_dsts=[list(TGT), [30.0, 110.0, 210.0]])
    assert rep.checks["tone_match"].detail["not_checked"] == {"1": "not-bound"}
    assert seen == [(master, [[0.5, 1.5, 2.5]])]     # ep1's span never read


def test_a_target_with_no_episode_bound_to_it_says_so_instead_of_passing(tmp_path, monkeypatch):
    # The conductor skipped EVERY episode. pass=True here would be a green tick for
    # having examined nothing — the same vacuous shape the all-pan safe_zones branch
    # refuses. The `reason` separates it from "no target was ever authored".
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    seen = _ruler(monkeypatch, [])
    rep = check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                         str(tmp_path / "r.json"), tone_target=TGT, tone_dsts=[None, None])
    assert rep.checks["tone_match"].passed is None
    assert rep.checks["tone_match"].detail["reason"] == "no-episode-bound"
    assert rep.checks["tone_match"].detail["not_checked"] == {"0": "not-bound", "1": "not-bound"}
    assert rep.overall is True and seen == []


def test_a_tone_dst_that_only_round_tripped_through_json_is_still_bound(tmp_path, monkeypatch):
    # The manifest's pair is a LIST of ints; the reel target is a tuple of floats. They
    # are the same numbers — an equality that type-sniffs would skip every episode and
    # report a vacuously green reel.
    _Stub([3.0], hashes={1.5: 0}).install(monkeypatch)
    _ruler(monkeypatch, [(20.0, 100.0, 200.0)])
    rep = check_reel.run(_master(tmp_path), ["a.mp4"], ReelCheckSpec(target_dur=3.0),
                         str(tmp_path / "r.json"), tone_target=TGT, tone_dsts=[[20, 100, 200]])
    assert rep.checks["tone_match"].detail["residuals"] == {"0": 0.0}
    assert rep.checks["tone_match"].detail["not_checked"] == {}


def test_one_luma_code_of_difference_is_a_different_target(tmp_path, monkeypatch):
    # The binding tolerance must not swallow a real difference: 1 code is the smallest
    # color.percentiles can report, and color.TONE_MIN_GAP is 6. Guards _TONE_BIND_EPS
    # against being widened into a threshold.
    _Stub([3.0], hashes={1.5: 0}).install(monkeypatch)
    seen = _ruler(monkeypatch, [])
    rep = check_reel.run(_master(tmp_path), ["a.mp4"], ReelCheckSpec(target_dur=3.0),
                         str(tmp_path / "r.json"), tone_target=TGT, tone_dsts=[[20.0, 101.0, 200.0]])
    assert rep.checks["tone_match"].detail["not_checked"] == {"0": "not-bound"}
    assert seen == []


def test_a_non_numeric_tone_dst_refuses_loud_instead_of_crashing_bare(tmp_path, monkeypatch):
    """fix round 1, minor 4: reframe refuses a malformed tone pair long before a reel is
    assembled, but ONLY on the edl_to_reel path — build_reel's own CLI reads an
    arbitrary reel-manifest JSON with no such validation upstream, so a hand-edited or
    corrupt manifest CAN hand a non-numeric tone_dst to this check. Before this fix,
    the right-length-but-wrong-content shape below reached `abs(a - b)` and raised a
    bare, unattributed TypeError; it must now name the episode, the value, and the fix."""
    _Stub([3.0], hashes={1.5: 0}).install(monkeypatch)
    seen = _ruler(monkeypatch, [])
    with pytest.raises(ValueError, match="tone_dst") as e:
        check_reel.run(_master(tmp_path), ["a.mp4"], ReelCheckSpec(target_dur=3.0),
                       str(tmp_path / "r.json"), tone_target=TGT,
                       tone_dsts=[["a", "b", "c"]])
    assert "not a triple of luma numbers" in str(e.value)
    assert seen == []                          # refused before any pixel was ever read


def test_tone_match_passes_at_exactly_the_threshold(tmp_path, monkeypatch):
    # residual == tone_match_max must PASS; guards the > boundary
    _Stub([3.0], hashes={1.5: 0}).install(monkeypatch)
    _ruler(monkeypatch, [(20.0, 112.0, 200.0)])
    rep = check_reel.run(_master(tmp_path), ["a.mp4"], ReelCheckSpec(target_dur=3.0),
                         str(tmp_path / "r.json"), tone_target=TGT, tone_dsts=[list(TGT)])
    assert rep.checks["tone_match"].passed is True
    assert rep.checks["tone_match"].detail["worst"] == 12.0


def test_a_narrowly_failing_residual_is_distinguishable_from_the_max(tmp_path, monkeypatch):
    """fix round 1, minor 3: `ok` is decided on the UNROUNDED worst, but the reported
    residual used to round to 1 decimal — a worst of 12.04 fails (12.04 > 12.0) while
    the JSON showed residual 12.0, max 12.0, and a reader could not tell why it failed.
    2 decimals (matching _loudness_check; length already uses 3) is enough to show the
    difference that actually decided the verdict."""
    _Stub([3.0], hashes={1.5: 0}).install(monkeypatch)
    _ruler(monkeypatch, [(20.0, 112.04, 200.0)])
    rep = check_reel.run(_master(tmp_path), ["a.mp4"], ReelCheckSpec(target_dur=3.0),
                         str(tmp_path / "r.json"), tone_target=TGT, tone_dsts=[list(TGT)])
    assert rep.checks["tone_match"].passed is False              # 12.04 > 12.0 — a genuine fail
    assert rep.checks["tone_match"].detail["worst"] == 12.04      # not 12.0 — must not round to the ceiling
    assert rep.checks["tone_match"].detail["residuals"] == {"0": 12.04}
    f = [x for x in rep.fail_reasons if x.check == "tone_match"][0]
    assert f.detail == {"residual": 12.04, "max": 12.0}


def test_a_target_without_the_per_episode_pairs_refuses_instead_of_passing_vacuously(tmp_path, monkeypatch):
    # tone_target and tone_dsts are parallel lists. A target with no dsts would make
    # EVERY episode read "not-bound" — a check that examined nothing while looking like
    # it ran. Refuse, and name the call that fixes it.
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    with pytest.raises(ValueError) as e:
        check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                       str(tmp_path / "r.json"), tone_target=TGT)
    assert "parallel lists" in str(e.value) and "tone_dst" in str(e.value)


def test_a_short_tone_dsts_list_refuses_rather_than_zipping_the_tail_away(tmp_path, monkeypatch):
    # zip() truncates silently: a 1-entry list against 2 episodes would drop episode 1
    # from BOTH residuals and not_checked, so nothing in the report would show the gap.
    _Stub([3.0, 3.0], hashes={1.5: 0, 4.5: 1000}).install(monkeypatch)
    with pytest.raises(ValueError, match="parallel lists"):
        check_reel.run(_master(tmp_path), ["a.mp4", "b.mp4"], ReelCheckSpec(target_dur=6.0),
                       str(tmp_path / "r.json"), tone_target=TGT, tone_dsts=[list(TGT)])


def test_tone_match_is_blocking(tmp_path, monkeypatch):
    """A property of ANOTHER module this check silently depends on: models._ADVISORY_CHECKS
    is what ReelReport.overall excludes, so adding "tone_match" there would leave every
    assertion above passing while the gate stopped blocking anything."""
    assert "tone_match" not in models._ADVISORY_CHECKS


def test_tone_match_escalates_and_is_never_reprocessed():
    """Also another module's property. A re-render cannot fix a colour — the grade rides
    the SAME manifest — so widening _REPROCESS_CLASS would turn one match-grade escalation
    into `cap` wasted full-resolution re-renders that change nothing."""
    assert "tone_match" not in reel_orchestration._REPROCESS_CLASS
    f = ReelFailure("tone_match", "match-grade", 1, {"residual": 30.0, "max": 12.0})
    action = reel_orchestration.next_action([f], attempts={}, cap=3)
    assert action.kind == "escalate"
    assert action.finding["escalate_to"] == "match-grade" and action.finding["episode_idx"] == 1
