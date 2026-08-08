import json
import sys
import threading
import pytest
from pathlib import Path
from scripts import edl_to_reel
from scripts.lib import provenance
from scripts.lib.edl import EDL, write_edl
from scripts.lib.episode_qc import EpisodeFinding, EpisodeVerdict, ReelQC
from scripts.lib.footage import DESCRIPTOR_LEN
from scripts.lib.models import ReelEpisode, ReelManifest
from scripts.lib.project import ProjectConfig


def _project(tmp_path):
    p = tmp_path / "project.json"
    p.write_text(json.dumps({"purpose": "reel", "canvas": [1080, 1920], "delivery": "native"}))
    return str(p)


def _edl_file(tmp_path, episodes=None, **reel):
    ep = dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
              composition="lead", grid="thirds", crop_scale=0.8)
    doc = {"episodes": episodes or [ep, {**ep, "start": 2.0}], **reel}
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps(doc))
    return str(p)


def _cast_json(tmp_path, name="Lena"):
    """A cast.json carrying one 512-d OSNet descriptor — the real shape, so preflight
    RESOLVES the cast-name pin instead of stopping on a stale-length descriptor (which
    would make the cast-pin tests below pass for the wrong reason)."""
    p = tmp_path / "cast.json"
    p.write_text(json.dumps({"members": [{"name": name, "descriptor": [0.1] * DESCRIPTOR_LEN}]}))
    return str(p)


def _cast_edl(tmp_path, cast_path, hero="Lena"):
    """An EDL whose one episode pins a cast-name hero, with the reel-level cast path —
    the ONE shape that resolves to a cast (identity) pin, the OSNet weight-race trigger."""
    ep = dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
              composition="lead", grid="thirds", crop_scale=0.8, hero=hero)
    return _edl_file(tmp_path, episodes=[ep], cast=cast_path)


def _wire(monkeypatch, pe_results=None, build_result=None):
    """Fake extract_edl / process_episode / build_reel; record what the driver builds.

    pe_results is a {episode_idx: result} dict — canned results are addressed by
    episode, never by call order (design §7.1), so a test stays correct under the
    thread pool. An episode with no entry gets a mechanical_pass."""
    seen = {"segments": [], "pe": [], "rm": None, "build": [], "build_titles": None,
            "warm": [], "order": []}

    def fake_extract(edl, footage_root, seg_dir):
        segs = [str(Path(seg_dir) / f"ep{i}_raw.mp4") for i in range(len(edl.episodes))]
        seen["segments"] = segs
        return segs
    monkeypatch.setattr(edl_to_reel.extract, "extract_edl", fake_extract)

    def fake_ensure_model(model_path):
        # Stubbed HERE, not per-test: edl_to_reel calls ensure_model itself, above the
        # pool, so faking process_episode does NOT intercept it. Left real, this fast-tier
        # file would import torch and construct a YOLO — and on a cold cache download the
        # weights over the network, which design §7.3 explicitly keeps out of this tier.
        # (tests/integration/ may reach weights; pytest.ini's marker says so. tests/lib/ may not.)
        seen["warm"].append(model_path)
        seen["order"].append(("warm", model_path))
    monkeypatch.setattr(edl_to_reel.track, "ensure_model", fake_ensure_model)

    # Refuse the old list shape LOUDLY. dict([{"status": s, "problems": p}]) does not
    # raise — a one-element list holding an exactly-2-key dict (the canned-result shape
    # used throughout this file) coerces to {"status": "problems"}, after which every
    # canned.get(idx, ...) falls through to mechanical_pass and the test passes having
    # verified nothing. A fixture whose whole job is to be trustworthy must not accept
    # a wrong-shaped argument in silence.
    if pe_results is not None and not isinstance(pe_results, dict):
        raise TypeError(f"_wire: pe_results must be a {{episode_idx: result}} dict, got "
                        f"{type(pe_results).__name__} — a list coerces silently and "
                        f"hollows out the test; write {{0: result}}, not [result]")
    canned = dict(pe_results or {})     # {episode_idx: result}; absent → mechanical_pass

    def fake_pe(manifest, project_dir, route_path=None, color_correct=None):
        # key off project_dir's ep{i} suffix — the one per-call value that names the
        # episode. Call ORDER is not usable: under the pool (design §7.1) it is a race.
        idx = int(Path(project_dir).name.removeprefix("ep"))
        seen["pe"].append({"manifest": manifest, "project_dir": project_dir, "idx": idx})
        seen["order"].append(("pe", project_dir))   # list.append is atomic under the GIL;
                                                    # only the order AMONG workers is undefined
        return canned.get(idx, {"status": "mechanical_pass", "clip": manifest["out_path"]})
    monkeypatch.setattr(edl_to_reel.process_episode, "process_episode", fake_pe)

    def fake_build(rm, out_dir, work_dir, titles=None):
        # titles= is captured into seen["build_titles"] so a test can assert edl_to_reel
        # forwards it here (a silent drop would else pass CI) — not otherwise the subject
        # of this fixture, which mainly checks the extract→episodes→build hand-off.
        seen["rm"] = rm
        seen["build"].append((out_dir, work_dir))
        seen["build_titles"] = titles
        return build_result or {"status": "delivered", "output": f"{out_dir}/REEL_v1.mp4", "report": {}}
    monkeypatch.setattr(edl_to_reel.build_reel, "build_reel", fake_build)
    return seen


def test_happy_path_drives_extract_then_episodes_then_build_reel(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path),
                                  footage_root=str(tmp_path), work_dir=str(tmp_path / "w"),
                                  out_dir=str(tmp_path / "out"))
    assert res["status"] == "delivered"
    assert len(seen["pe"]) == 2
    assert all(m["manifest"]["canvas"] == [1080, 1920] for m in seen["pe"])
    rm = seen["rm"]
    assert len(rm.episodes) == 2 and rm.target_dur == 4.0
    assert rm.episodes[0].manifest["canvas"] == [1080, 1920]
    assert rm.episodes[0].route.endswith("ep0/route.json")
    assert rm.episodes[0].path.endswith("ep0/path.json")
    assert rm.episodes[0].meta.endswith("ep0/path.meta.json")
    assert rm.cap == 3


def test_edl_music_and_target_override_reach_the_reel_manifest(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path, music="M.json", cap=2, target_dur=9.0),
                            _project(tmp_path), str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"),
                            music="OVERRIDE.json")
    rm = seen["rm"]
    assert rm.music == "OVERRIDE.json"
    assert rm.target_dur == 9.0 and rm.cap == 2


def test_color_delta_max_override_reaches_the_reel_manifest(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path), str(tmp_path),
                            str(tmp_path / "w"), str(tmp_path / "out"), color_delta_max=20.0)
    rm = seen["rm"]
    assert rm.color_delta_max == 20.0
    assert rm.check_spec.color_delta_max == 20.0    # the value actually enforced by check_reel


def test_color_delta_max_omitted_keeps_the_reel_check_spec_default(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path), str(tmp_path),
                            str(tmp_path / "w"), str(tmp_path / "out"))
    rm = seen["rm"]
    assert rm.color_delta_max == 12.0               # ReelCheckSpec's own default, untouched
    assert rm.check_spec.color_delta_max == 12.0


def test_titles_forwarded_to_build_reel(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path), str(tmp_path),
                            str(tmp_path / "w"), str(tmp_path / "out"), titles="TITLES.json")
    assert seen["build_titles"] == "TITLES.json"    # titles= forwarded edl_to_reel -> build_reel


def test_bad_episode_preflights_before_any_ffmpeg(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    bad = dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
               composition="lead", grid="thirds", crop_scale=1.0, crop_aspect="source")
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path, episodes=[bad]), _project(tmp_path),
                                  str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert res["status"] == "stop_and_report" and res["finding"]["reason"] == "edl-invalid"
    assert res["finding"]["episode_idx"] == 0
    assert seen["segments"] == [] and seen["pe"] == []


def test_episode_failure_stops_and_reports_without_building(monkeypatch, tmp_path):
    seen = _wire(monkeypatch, pe_results={0: {"status": "needs_input", "problems": ["ambiguous hero"]}})
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path),
                                  str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert res["status"] == "stop_and_report" and res["finding"]["reason"] == "episode-failed"
    assert res["finding"]["episode_idx"] == 0 and res["finding"]["sub_status"] == "needs_input"
    assert seen["rm"] is None and seen["build"] == []


def test_build_reel_stop_is_passed_through(monkeypatch, tmp_path):
    _wire(monkeypatch, build_result={"status": "stop_and_report", "finding": {"reason": "variety"}})
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path),
                                  str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert res["status"] == "stop_and_report" and res["finding"]["reason"] == "variety"


def test_a_canned_result_lands_on_its_own_episode(monkeypatch, tmp_path):
    # The fixture keys canned results by EPISODE INDEX, not by call order. Under the
    # thread pool (design §7.1) call order is a race, so targeting episode 1 by
    # padding a list would silently retarget episode 0 on an unlucky schedule.
    seen = _wire(monkeypatch, pe_results={1: {"status": "needs_input", "problems": ["x"]}})
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path),
                                  str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert res["finding"]["episode_idx"] == 1
    assert res["finding"]["sub_status"] == "needs_input"
    assert sorted(m["idx"] for m in seen["pe"]) == [0, 1]


def test_wire_refuses_the_old_list_shape(monkeypatch):
    # The guard exists because dict([{"status": s, "problems": p}]) does NOT raise:
    # a 2-key result dict coerces to {"status": "problems"} and every episode then
    # gets the default mechanical_pass, so a test written with a list would pass
    # without its canned failure ever landing.
    with pytest.raises(TypeError, match="must be a .*dict"):
        _wire(monkeypatch, pe_results=[{"status": "needs_input", "problems": ["x"]}])


def test_default_jobs_is_the_measured_knee():
    # 3 is measured, not guessed: design §2 clocks 1.70x at cap 3 on six real
    # episodes and +0.99x (nothing) at cap 4. Pinned so a later edit to the
    # constant has to argue with the measurement.
    assert edl_to_reel.DEFAULT_JOBS == 3


@pytest.mark.parametrize("bad", [0, -1, True, "3", 3.0])
def test_jobs_must_be_a_positive_int(monkeypatch, tmp_path, bad):
    # True is in the list on purpose: isinstance(True, int) is True, so an
    # unguarded check would read it as jobs=1 and silently serialize the fan-out.
    _wire(monkeypatch)
    with pytest.raises(ValueError, match="jobs must be an integer >= 1"):
        edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path), str(tmp_path),
                                str(tmp_path / "w"), str(tmp_path / "out"), jobs=bad)


def _six(tmp_path):
    """Six episodes — divisible by 3, so a jobs=3 pool fills exactly twice with no
    ragged tail. Fewer than 6 would let a lucky schedule fake the concurrency."""
    ep = dict(source="a.mp4", dur=2.0, shot_type="wide",
              composition="lead", grid="thirds", crop_scale=0.8)
    return _edl_file(tmp_path, episodes=[{**ep, "start": float(i) * 2.0} for i in range(6)])


def test_the_pool_reaches_the_cap_and_never_exceeds_it(monkeypatch, tmp_path):
    # One fake proves both halves. The barrier forces `jobs` workers to be inside
    # fake_pe simultaneously: a sequential driver never assembles 3 parties, so
    # barrier.wait() times out and raises BrokenBarrierError. Because the barrier
    # HOLDS all three, peak == jobs is forced rather than hoped for — a bare counter
    # could observe 2 on an unlucky schedule and flake.
    jobs = 3
    barrier = threading.Barrier(jobs, timeout=10)     # deadlock backstop, not a timing assumption
    lock = threading.Lock()
    state = {"live": 0, "peak": 0}

    def fake_pe(manifest, project_dir, route_path=None, color_correct=None):
        with lock:
            state["live"] += 1
            state["peak"] = max(state["peak"], state["live"])
        barrier.wait()
        with lock:
            state["live"] -= 1
        return {"status": "mechanical_pass", "clip": manifest["out_path"]}

    _wire(monkeypatch)
    monkeypatch.setattr(edl_to_reel.process_episode, "process_episode", fake_pe)
    res = edl_to_reel.edl_to_reel(_six(tmp_path), _project(tmp_path), str(tmp_path),
                                  str(tmp_path / "w"), str(tmp_path / "out"), jobs=jobs)
    assert res["status"] == "delivered"
    assert state["peak"] == jobs


def test_every_episode_gets_its_own_scratch_and_output(monkeypatch, tmp_path):
    # The load-bearing precondition for parallelising at all: process_episode's
    # docstring warns that a shared project_dir clobbers a sibling's route/path/
    # report. Pin it rather than trust the comment.
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_six(tmp_path), _project(tmp_path), str(tmp_path),
                            str(tmp_path / "w"), str(tmp_path / "out"), jobs=3)
    dirs = [m["project_dir"] for m in seen["pe"]]
    outs = [m["manifest"]["out_path"] for m in seen["pe"]]
    assert len(set(dirs)) == 6 and len(set(outs)) == 6
    assert sorted(Path(d).name for d in dirs) == [f"ep{i}" for i in range(6)]


def test_every_episode_runs_even_after_an_earlier_one_fails(monkeypatch, tmp_path):
    # The deliberate behaviour change (design §4): the sequential loop returned at
    # the first failure and never processed episodes after it. The pool runs them
    # all. Pinned so a future reader sees this was chosen, not leaked.
    seen = _wire(monkeypatch, pe_results={0: {"status": "needs_input", "problems": ["x"]}})
    res = edl_to_reel.edl_to_reel(_six(tmp_path), _project(tmp_path), str(tmp_path),
                                  str(tmp_path / "w"), str(tmp_path / "out"), jobs=3)
    assert res["finding"]["episode_idx"] == 0
    assert sorted(m["idx"] for m in seen["pe"]) == [0, 1, 2, 3, 4, 5]


def test_the_lowest_failing_index_is_reported(monkeypatch, tmp_path):
    seen = _wire(monkeypatch, pe_results={1: {"status": "needs_input", "problems": ["x"]},
                                          4: {"status": "escalate", "escalate_to": "edit-plan"}})
    res = edl_to_reel.edl_to_reel(_six(tmp_path), _project(tmp_path), str(tmp_path),
                                  str(tmp_path / "w"), str(tmp_path / "out"), jobs=3)
    assert res["finding"]["episode_idx"] == 1          # not 4, and not scheduler-dependent
    assert res["finding"]["sub_status"] == "needs_input"
    assert seen["rm"] is None and seen["build"] == []


def test_jobs_1_reports_the_same_finding_as_the_default(monkeypatch, tmp_path):
    # The regression guard AND the debugging escape hatch: one semantics at every
    # jobs value. A jobs=1 run that behaved differently would lie about the thing
    # being debugged.
    fails = {1: {"status": "needs_input", "problems": ["x"]},
             4: {"status": "escalate", "escalate_to": "edit-plan"}}
    _wire(monkeypatch, pe_results=fails)
    one = edl_to_reel.edl_to_reel(_six(tmp_path), _project(tmp_path), str(tmp_path),
                                  str(tmp_path / "w1"), str(tmp_path / "out1"), jobs=1)
    _wire(monkeypatch, pe_results=fails)
    three = edl_to_reel.edl_to_reel(_six(tmp_path), _project(tmp_path), str(tmp_path),
                                    str(tmp_path / "w3"), str(tmp_path / "out3"), jobs=3)
    assert one["finding"] == three["finding"]
    assert one["status"] == three["status"] == "stop_and_report"


def test_the_weights_are_warmed_before_any_worker_starts(monkeypatch, tmp_path):
    # A warm-up that runs after the pool starts is no warm-up (design §5). The fixture
    # records both fakes into one seen["order"], so this test reads the ordering the same
    # way every other test reads seen["pe"] — no per-test patching, and therefore no
    # patch-order trap between this test and the fixture's own ensure_model stub.
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_six(tmp_path), _project(tmp_path), str(tmp_path),
                            str(tmp_path / "w"), str(tmp_path / "out"), jobs=3)
    # entry 0 is deterministic: ensure_model runs on the main thread before any submit,
    # so it strictly happens-before every worker's append.
    assert seen["order"][0] == ("warm", edl_to_reel.track.MODEL)   # the manifest default, by name
    assert seen["warm"] == [edl_to_reel.track.MODEL]               # one distinct model → warmed once
    assert all(kind == "pe" for kind, _ in seen["order"][1:])
    assert len(seen["order"]) == 7                                 # 1 warm + 6 episodes


def test_reid_weights_are_warmed_before_the_pool_when_a_cast_pin_is_present(monkeypatch, tmp_path):
    # The OSNet twin of the YOLO warm-up above (design 2026-08-04 §3.1/§10). A
    # cast-identity pin drives process_episode -> track.build_route -> reid.embed ->
    # a cold OSNet weight download; N cold pool workers would race it into the same
    # path (the repo's highest-priority silent-corruption class). So edl_to_reel MUST
    # materialize the weights ONCE, on the main thread, before any worker submits.
    seen = _wire(monkeypatch)
    monkeypatch.setattr(edl_to_reel.reid, "available", lambda: True)
    monkeypatch.setattr(edl_to_reel.reid, "ensure_model",
                        lambda: seen["order"].append(("reid", "warm")))
    edl_to_reel.edl_to_reel(_cast_edl(tmp_path, _cast_json(tmp_path)), _project(tmp_path),
                            str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"), jobs=3)
    assert ("reid", "warm") in seen["order"]                       # warmed at all
    reid_i = seen["order"].index(("reid", "warm"))
    assert all(reid_i < i for i, (k, _) in enumerate(seen["order"]) if k == "pe")  # before any worker


def test_reid_weights_are_not_warmed_for_a_scenery_reel(monkeypatch, tmp_path):
    # No episode pins a cast identity, so building OSNet would be a needless heavy
    # model download. available() is left TRUE on purpose: this pins that the guard
    # keys on the cast pin, not merely on availability.
    seen = _wire(monkeypatch)
    monkeypatch.setattr(edl_to_reel.reid, "available", lambda: True)
    warmed = []
    monkeypatch.setattr(edl_to_reel.reid, "ensure_model", lambda: warmed.append(True))
    edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path), str(tmp_path),
                            str(tmp_path / "w"), str(tmp_path / "out"))
    assert warmed == []                                            # not warmed — no cast pin


def test_reid_weights_are_not_warmed_when_reid_is_unavailable(monkeypatch, tmp_path):
    # A cast pin IS present, but torchreid is absent — process_episode itself will
    # stop that episode with reid-unavailable (design §6); warming here could not run
    # and would only pay the torchreid import for nothing. available() False -> skip.
    seen = _wire(monkeypatch)
    monkeypatch.setattr(edl_to_reel.reid, "available", lambda: False)
    warmed = []
    monkeypatch.setattr(edl_to_reel.reid, "ensure_model", lambda: warmed.append(True))
    edl_to_reel.edl_to_reel(_cast_edl(tmp_path, _cast_json(tmp_path)), _project(tmp_path),
                            str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert warmed == []                                            # not warmed — reID unavailable


def test_the_lowest_raising_episode_escapes_with_its_own_type(monkeypatch, tmp_path):
    # Two episodes raise; the one that escapes must be the LOWER index — the same
    # one the sequential loop would have hit first — and it must keep its type,
    # because edl_to_reel's docstring contracts setup failures as ValueError.
    def fake_pe(manifest, project_dir, route_path=None, color_correct=None):
        idx = int(Path(project_dir).name.removeprefix("ep"))
        if idx in (1, 4):
            raise ValueError(f"boom {idx}")
        return {"status": "mechanical_pass", "clip": manifest["out_path"]}

    _wire(monkeypatch)
    monkeypatch.setattr(edl_to_reel.process_episode, "process_episode", fake_pe)
    with pytest.raises(ValueError) as ei:
        edl_to_reel.edl_to_reel(_six(tmp_path), _project(tmp_path), str(tmp_path),
                                str(tmp_path / "w"), str(tmp_path / "out"), jobs=3)
    assert "boom 1" in str(ei.value)                       # not "boom 4"
    assert any("episode 1" in n for n in ei.value.__notes__)


def test_a_raise_beats_a_failing_status_from_a_later_episode(monkeypatch, tmp_path):
    # A raise at a LOWER index than the failing status wins — not because the
    # exception channel has priority (it does not; see the inverted twin below),
    # but because 2 < 5. The sequential loop aborted at 2 for the same reason.
    def fake_pe(manifest, project_dir, route_path=None, color_correct=None):
        idx = int(Path(project_dir).name.removeprefix("ep"))
        if idx == 2:
            raise RuntimeError("ffmpeg died")
        if idx == 5:
            return {"status": "needs_input", "problems": ["x"]}
        return {"status": "mechanical_pass", "clip": manifest["out_path"]}

    _wire(monkeypatch)
    monkeypatch.setattr(edl_to_reel.process_episode, "process_episode", fake_pe)
    with pytest.raises(RuntimeError, match="ffmpeg died"):
        edl_to_reel.edl_to_reel(_six(tmp_path), _project(tmp_path), str(tmp_path),
                                str(tmp_path / "w"), str(tmp_path / "out"), jobs=3)


def test_cli_threads_jobs(monkeypatch, tmp_path):
    import sys
    seen_jobs = {}

    def fake_driver(*a, **kw):
        seen_jobs["jobs"] = kw.get("jobs")
        return {"status": "delivered", "output": "REEL_v1.mp4"}
    monkeypatch.setattr(edl_to_reel, "edl_to_reel", fake_driver)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel", _edl_file(tmp_path),
                                      "--project", _project(tmp_path),
                                      "--footage-root", str(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out"),
                                      "--jobs", "2"])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 0
    assert seen_jobs["jobs"] == 2          # int, not the string "2"


def test_cli_jobs_defaults_to_the_knee(monkeypatch, tmp_path):
    import sys
    seen_jobs = {}

    def fake_driver(*a, **kw):
        seen_jobs["jobs"] = kw.get("jobs")
        return {"status": "delivered", "output": "REEL_v1.mp4"}
    monkeypatch.setattr(edl_to_reel, "edl_to_reel", fake_driver)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel", _edl_file(tmp_path),
                                      "--project", _project(tmp_path),
                                      "--footage-root", str(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out")])
    with pytest.raises(SystemExit):
        edl_to_reel.main()
    assert seen_jobs["jobs"] == edl_to_reel.DEFAULT_JOBS


def test_cli_threads_color_delta_max(monkeypatch, tmp_path):
    import sys
    seen_kw = {}

    def fake_driver(*a, **kw):
        seen_kw["color_delta_max"] = kw.get("color_delta_max")
        return {"status": "delivered", "output": "REEL_v1.mp4"}
    monkeypatch.setattr(edl_to_reel, "edl_to_reel", fake_driver)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel", _edl_file(tmp_path),
                                      "--project", _project(tmp_path),
                                      "--footage-root", str(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out"),
                                      "--color-delta-max", "20.0"])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 0
    assert seen_kw["color_delta_max"] == 20.0        # float, not the string "20.0"


def test_cli_color_delta_max_defaults_to_none(monkeypatch, tmp_path):
    import sys
    seen_kw = {}

    def fake_driver(*a, **kw):
        seen_kw["color_delta_max"] = kw.get("color_delta_max")
        return {"status": "delivered", "output": "REEL_v1.mp4"}
    monkeypatch.setattr(edl_to_reel, "edl_to_reel", fake_driver)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel", _edl_file(tmp_path),
                                      "--project", _project(tmp_path),
                                      "--footage-root", str(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out")])
    with pytest.raises(SystemExit):
        edl_to_reel.main()
    assert seen_kw["color_delta_max"] is None        # unset CLI flag -> ReelCheckSpec's own default


# --- Task 6 fix round 1: the two-phase CLI dispatch itself -----------------------
#
# Everything above patches edl_to_reel.edl_to_reel and only ever exercises the
# no-flags branch of main(). None of it touches --stop-after-episodes,
# --from-episodes, the mutual-exclusion group, or either manual `ap.error` — and
# once the router lands, this CLI is production's ONLY way to reach
# process_episodes/assemble_reel. A wiring bug here (say --from-episodes falling
# through to edl_to_reel) would silently defeat a gate whose entire stated purpose
# is that it cannot be skipped silently, and nothing above would notice.

def _no_dispatch(monkeypatch):
    """Patch all three phase entry points to record whether main() called ANY of
    them, so a refusal test proves argparse/ap.error fired BEFORE any dispatch —
    not merely that main() eventually raised SystemExit for some reason."""
    called = []
    monkeypatch.setattr(edl_to_reel, "edl_to_reel", lambda *a, **k: called.append("edl_to_reel"))
    monkeypatch.setattr(edl_to_reel, "process_episodes",
                        lambda *a, **k: called.append("process_episodes"))
    monkeypatch.setattr(edl_to_reel, "assemble_reel", lambda *a, **k: called.append("assemble_reel"))
    return called


def test_cli_stop_after_episodes_and_from_episodes_are_mutually_exclusive(monkeypatch, tmp_path):
    # Deliberately NO edl/--project/--footage-root/--out-dir here — the realistic
    # resume shape (--from-episodes never re-reads the front half, per its own help
    # text, and does not take an out dir at all). With any of them present the
    # independent "--from-episodes resumes a run..." refusal fires on its own and
    # this test would pass even with the mutex deleted, because a.stop_after_episodes
    # is read NOWHERE except inside the else arm's ternary — ungrouping the two flags
    # would then silently let --stop-after-episodes be ignored and fall through to a
    # real assemble_reel dispatch.
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel",
                                      "--stop-after-episodes",
                                      "--from-episodes", str(tmp_path / "EPISODES.json"),
                                      "--work-dir", str(tmp_path / "w")])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2            # argparse's own mutually_exclusive_group, not ap.error
    assert called == []


def test_cli_from_episodes_refuses_a_positional_edl(monkeypatch, tmp_path):
    # Isolates the `a.edl` operand of the "resumes a run..." refusal's `or` — a
    # bug that dropped this operand (or wrote `and` instead) would only surface
    # when exactly this combination, alone, is given. No --out-dir here either:
    # it is its own operand now (see test_cli_from_episodes_refuses_an_out_dir_flag)
    # and including it would stop this test from isolating `a.edl` alone.
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel", _edl_file(tmp_path),
                                      "--from-episodes", str(tmp_path / "EPISODES.json"),
                                      "--work-dir", str(tmp_path / "w")])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


def test_cli_from_episodes_refuses_a_project_flag(monkeypatch, tmp_path):
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel",
                                      "--from-episodes", str(tmp_path / "EPISODES.json"),
                                      "--project", _project(tmp_path),
                                      "--work-dir", str(tmp_path / "w")])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


def test_cli_from_episodes_refuses_a_footage_root_flag(monkeypatch, tmp_path):
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel",
                                      "--from-episodes", str(tmp_path / "EPISODES.json"),
                                      "--footage-root", str(tmp_path),
                                      "--work-dir", str(tmp_path / "w")])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


def test_cli_from_episodes_refuses_an_out_dir_flag(monkeypatch, tmp_path):
    # Isolates the `a.out_dir` operand — phase 2 derives its out dir from the
    # EPISODES.json path (design §3) and never reads --out-dir, so accepting it
    # silently here would let a caller point it at the wrong place with no
    # complaint while the reel actually lands beside EPISODES.json regardless.
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel",
                                      "--from-episodes", str(tmp_path / "EPISODES.json"),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out")])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


# --- Final review fix: the four phase-1-only flags --from-episodes silently dropped ---
#
# Before this fix only edl/--project/--footage-root/--out-dir were refused on
# --from-episodes; --music/--jobs/--color-delta-max/--changelog were parsed and simply
# never passed to assemble_reel — accepted, and silently discarded, exactly the class
# the mutex/out-dir refusals above exist to prevent for the other four flags.

def test_cli_from_episodes_refuses_a_music_flag(monkeypatch, tmp_path):
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel",
                                      "--from-episodes", str(tmp_path / "EPISODES.json"),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--music", "MUSIC.json"])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


def test_cli_from_episodes_refuses_a_jobs_flag(monkeypatch, tmp_path):
    # --jobs defaults to None on the CLI now (resolved to DEFAULT_JOBS only in the
    # non-resume arm) precisely so this refusal can tell "not given" from "given the
    # default value" — see test_cli_jobs_defaults_to_the_knee below for the other half.
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel",
                                      "--from-episodes", str(tmp_path / "EPISODES.json"),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--jobs", "2"])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


def test_cli_from_episodes_refuses_a_color_delta_max_flag(monkeypatch, tmp_path):
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel",
                                      "--from-episodes", str(tmp_path / "EPISODES.json"),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--color-delta-max", "20.0"])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


def test_cli_from_episodes_refuses_a_changelog_flag(monkeypatch, tmp_path):
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel",
                                      "--from-episodes", str(tmp_path / "EPISODES.json"),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--changelog", "regraded ep1"])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


def test_cli_refuses_titles_combined_with_stop_after_episodes(monkeypatch, tmp_path):
    # Titles are burned in at delivery (phase 2) — process_episodes (phase 1) has no
    # titles parameter at all, so --titles here used to be silently discarded (the
    # skill invited exactly this combination by an ambiguous cross-reference).
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel", _edl_file(tmp_path),
                                      "--project", _project(tmp_path),
                                      "--footage-root", str(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out"),
                                      "--stop-after-episodes",
                                      "--titles", "TITLES.json"])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


def test_cli_requires_edl_without_from_episodes(monkeypatch, tmp_path):
    # Isolates the `edl` entry of the "required unless --from-episodes" check —
    # --project and --footage-root are both present, so only a missing `edl`
    # can be what trips this.
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel",
                                      "--project", _project(tmp_path),
                                      "--footage-root", str(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out")])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


def test_cli_requires_project_without_from_episodes(monkeypatch, tmp_path):
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel", _edl_file(tmp_path),
                                      "--footage-root", str(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out")])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


def test_cli_requires_footage_root_without_from_episodes(monkeypatch, tmp_path):
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel", _edl_file(tmp_path),
                                      "--project", _project(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out")])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


def test_cli_requires_out_dir_without_from_episodes(monkeypatch, tmp_path):
    # --out-dir dropped its argparse required=True (it must NOT be required on the
    # --from-episodes path), so this is now the only thing enforcing it on the
    # non-resume paths — the "missing" list in main()'s else arm, same as
    # edl/--project/--footage-root above.
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel", _edl_file(tmp_path),
                                      "--project", _project(tmp_path),
                                      "--footage-root", str(tmp_path),
                                      "--work-dir", str(tmp_path / "w")])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


def test_cli_from_episodes_dispatches_to_assemble_reel(monkeypatch, tmp_path):
    # No --out-dir: this IS the realistic invocation (phase 2 takes none — design §3),
    # and it must dispatch and exit 0 without it. The refusal when --out-dir IS given
    # is test_cli_from_episodes_refuses_an_out_dir_flag, above.
    seen = {}

    def fake_assemble_reel(episodes_path, work_dir, *, titles=None):
        seen["episodes_path"] = episodes_path
        seen["work_dir"] = work_dir
        seen["titles"] = titles
        return {"status": "delivered", "output": "REEL_v1.mp4"}
    monkeypatch.setattr(edl_to_reel, "assemble_reel", fake_assemble_reel)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel",
                                      "--from-episodes", str(tmp_path / "EPISODES.json"),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--titles", "TITLES.json"])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 0
    assert seen["episodes_path"] == str(tmp_path / "EPISODES.json")
    assert seen["work_dir"] == str(tmp_path / "w")
    assert seen["titles"] == "TITLES.json"


def test_cli_stop_after_episodes_dispatches_to_process_episodes_without_titles(monkeypatch, tmp_path):
    # No --titles on this argv at all: combining it with --stop-after-episodes is now
    # its own refusal (test_cli_refuses_titles_combined_with_stop_after_episodes) —
    # this test isolates the OTHER half, that process_episodes is dispatched with no
    # titles kwarg when the CLI simply never carried one.
    seen = {}

    def fake_process_episodes(edl_path, project_path, footage_root, work_dir, out_dir, *,
                              music=None, jobs=edl_to_reel.DEFAULT_JOBS,
                              color_delta_max=None, changelog=""):
        # NO titles= parameter at all: if main() leaked titles= through on the
        # --stop-after-episodes arm (the real difference between the two dispatch
        # kwargs the coordinator flagged), Python raises TypeError right here,
        # before this body ever runs — the assertion never gets a chance to lie.
        seen["called"] = "process_episodes"
        seen["out_dir"] = out_dir
        return {"status": "episodes_ready", "episodes": "x", "count": 1, "clips": []}
    monkeypatch.setattr(edl_to_reel, "process_episodes", fake_process_episodes)
    monkeypatch.setattr(edl_to_reel, "edl_to_reel",
                        lambda *a, **k: seen.setdefault("wrong_fn", "edl_to_reel"))
    monkeypatch.setattr(sys, "argv", ["edl_to_reel", _edl_file(tmp_path),
                                      "--project", _project(tmp_path),
                                      "--footage-root", str(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out"),
                                      "--stop-after-episodes"])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 0
    assert seen["called"] == "process_episodes"
    assert "wrong_fn" not in seen                # edl_to_reel (the default arm) was NOT called
    assert seen["out_dir"] == str(tmp_path / "out")


def test_cli_default_dispatches_to_edl_to_reel_with_titles(monkeypatch, tmp_path):
    seen = {}

    def fake_edl_to_reel(edl_path, project_path, footage_root, work_dir, out_dir, *,
                         music=None, titles=None, jobs=edl_to_reel.DEFAULT_JOBS,
                         color_delta_max=None, changelog=""):
        seen["called"] = "edl_to_reel"
        seen["titles"] = titles
        return {"status": "delivered", "output": "REEL_v1.mp4"}
    monkeypatch.setattr(edl_to_reel, "edl_to_reel", fake_edl_to_reel)
    monkeypatch.setattr(edl_to_reel, "process_episodes",
                        lambda *a, **k: seen.setdefault("wrong_fn", "process_episodes"))
    monkeypatch.setattr(sys, "argv", ["edl_to_reel", _edl_file(tmp_path),
                                      "--project", _project(tmp_path),
                                      "--footage-root", str(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out"),
                                      "--titles", "TITLES.json"])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 0
    assert seen["called"] == "edl_to_reel"
    assert "wrong_fn" not in seen                # process_episodes (the stop-after arm) was NOT called
    assert seen["titles"] == "TITLES.json"


def test_a_routable_finding_at_a_lower_index_beats_a_raise_above_it(monkeypatch, tmp_path):
    # The inverted twin of the test above, and the case that actually diverged: the
    # two failure channels must be ordered AGAINST EACH OTHER, not each within itself.
    # Draining every exception first would surface ep2's raise and lose ep0's routable
    # stop_and_report — which the sequential loop returned before it ever reached ep2.
    # A caller branching on result["status"] would get a traceback instead of a finding.
    def fake_pe(manifest, project_dir, route_path=None, color_correct=None):
        idx = int(Path(project_dir).name.removeprefix("ep"))
        if idx == 2:
            raise RuntimeError("ffmpeg died")
        if idx == 0:
            return {"status": "needs_input", "problems": ["ambiguous hero"]}
        return {"status": "mechanical_pass", "clip": manifest["out_path"]}

    _wire(monkeypatch)
    monkeypatch.setattr(edl_to_reel.process_episode, "process_episode", fake_pe)
    res = edl_to_reel.edl_to_reel(_six(tmp_path), _project(tmp_path), str(tmp_path),
                                  str(tmp_path / "w"), str(tmp_path / "out"), jobs=3)
    assert res["status"] == "stop_and_report"          # NOT a raised RuntimeError
    assert res["finding"]["episode_idx"] == 0 and res["finding"]["sub_status"] == "needs_input"


# --- Task 4: engine-drift stop, run provenance, real changelog -------------------

def test_a_run_that_straddles_an_engine_change_is_refused(tmp_path, monkeypatch):
    # #11: project.json records the engine at run start; if the code moved since, the
    # stages already finished were produced by different code.
    project = tmp_path / "project.json"
    ProjectConfig(purpose="reel", canvas=(9, 16), delivery="native",
                  provenance={"v": 1, "engine": {"sha": "aaaaaaa", "dirty": False},
                              "self": "x", "inputs": {}}).write(project)
    monkeypatch.setattr(edl_to_reel.provenance, "engine_stamp",
                        lambda: {"sha": "bbbbbbb", "dirty": False})
    with pytest.raises(ValueError, match="must not straddle an engine change"):
        edl_to_reel.edl_to_reel(_edl_file(tmp_path), str(project), str(tmp_path),
                                str(tmp_path / "w"), str(tmp_path / "o"))


def test_an_unknown_engine_stamp_never_stops_the_run(tmp_path, monkeypatch):
    project = tmp_path / "project.json"
    ProjectConfig(purpose="reel", canvas=(9, 16), delivery="native",
                  provenance={"v": 1, "engine": {"sha": "", "dirty": None},
                              "self": "x", "inputs": {}}).write(project)
    monkeypatch.setattr(edl_to_reel.provenance, "engine_stamp",
                        lambda: {"sha": "bbbbbbb", "dirty": False})
    _wire(monkeypatch)
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path), str(project), str(tmp_path),
                                  str(tmp_path / "w"), str(tmp_path / "o"))
    assert res["status"] == "delivered"


def test_a_known_start_stamp_with_an_unknown_current_stamp_never_stops_the_run(tmp_path, monkeypatch):
    # Mirror image of test_an_unknown_engine_stamp_never_stops_the_run above: this time
    # project.json recorded a REAL sha at run start, but engine_stamp() cannot answer NOW
    # (e.g. git unavailable at delivery time) — an unknown stamp on EITHER side cannot
    # prove drift (design §7), so this arm of the guard must not raise either.
    project = tmp_path / "project.json"
    ProjectConfig(purpose="reel", canvas=(9, 16), delivery="native",
                  provenance={"v": 1, "engine": {"sha": "aaaaaaa", "dirty": False},
                              "self": "x", "inputs": {}}).write(project)
    monkeypatch.setattr(edl_to_reel.provenance, "engine_stamp",
                        lambda: {"sha": "", "dirty": None})
    _wire(monkeypatch)
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path), str(project), str(tmp_path),
                                  str(tmp_path / "w"), str(tmp_path / "o"))
    assert res["status"] == "delivered"


def test_a_run_started_before_this_existed_never_stops(tmp_path, monkeypatch):
    # project.json with NO provenance block at all — absence, not tampering
    _wire(monkeypatch)
    monkeypatch.setattr(edl_to_reel.provenance, "engine_stamp",
                        lambda: {"sha": "bbbbbbb", "dirty": False})
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path), str(tmp_path),
                                  str(tmp_path / "w"), str(tmp_path / "o"))
    assert res["status"] == "delivered"


def test_the_run_provenance_reaches_build_reel(tmp_path, monkeypatch):
    seen = {}
    _wire(monkeypatch)
    monkeypatch.setattr(edl_to_reel.build_reel, "build_reel",
                        lambda rm, o, w, titles=None: seen.setdefault("rm", rm) and None
                        or {"status": "delivered"})
    project = tmp_path / "project.json"
    ProjectConfig(purpose="reel", canvas=(9, 16), delivery="native",
                  provenance={"v": 1, "engine": {"sha": "aaaaaaa", "dirty": False},
                              "self": "x", "inputs": {}}).write(project)
    monkeypatch.setattr(edl_to_reel.provenance, "engine_stamp",
                        lambda: {"sha": "aaaaaaa", "dirty": False})   # == recorded -> no drift
    ep = dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
              composition="lead", grid="thirds", crop_scale=0.8)
    edl = EDL.from_dict({"episodes": [ep, {**ep, "start": 2.0}]})
    edl_path = tmp_path / "EDL.json"
    write_edl(edl, edl_path)
    edl_to_reel.edl_to_reel(str(edl_path), str(project), str(tmp_path),
                            str(tmp_path / "w"), str(tmp_path / "o"), color_delta_max=20.0)
    prov = seen["rm"].provenance
    assert prov["edl"]["state"] == "intact"
    assert prov["overrides"] == [{"field": "color_delta_max", "value": 20.0, "default": 12.0}]
    assert prov["engine_at_start"] == {"sha": "aaaaaaa", "dirty": False}


def test_an_unstamped_edl_is_recorded_as_unstamped(tmp_path, monkeypatch):
    # the hand-authored SP1 front door still works, and says so on the record
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path), str(tmp_path),
                            str(tmp_path / "w"), str(tmp_path / "out"))
    assert seen["rm"].provenance["edl"] == {"digest": "", "state": "unstamped"}


def test_a_provenance_block_with_no_self_key_is_recorded_as_unstamped(tmp_path, monkeypatch):
    # provenance.check() (the predicate EDL.from_json uses to refuse TAMPERING) treats a
    # block as stamped only when block["self"] is truthy — a hand-authored EDL.json
    # carrying a non-empty provenance object with no valid "self" is "unstamped" to
    # check(), and from_json rightly admits it (absence, not tampering). The attestation
    # must record that SAME judgement: re-deriving "intact" from plain dict truthiness
    # (the bug) would invert design §5.1's guarantee that a reel cut from a
    # hand-authored EDL says so on the record.
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(
        _edl_file(tmp_path, provenance={"v": 1, "engine": {"sha": "", "dirty": None}, "inputs": {}}),
        _project(tmp_path), str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert seen["rm"].provenance["edl"] == {"digest": "", "state": "unstamped"}


def test_the_changelog_is_a_reason_not_the_log_path(tmp_path, monkeypatch):
    # #16 root cause: edl_to_reel passed str(out_dir/"VERSIONS.md") as the NOTE — 12 of 13
    # entries in a real run's VERSIONS.md then logged the file's own path.
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path), str(tmp_path),
                            str(tmp_path / "w"), str(tmp_path / "out"))
    assert seen["rm"].changelog == "delivered from EDL.json"
    assert "VERSIONS.md" not in seen["rm"].changelog


def test_an_explicit_changelog_wins(tmp_path, monkeypatch):
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path), str(tmp_path),
                            str(tmp_path / "w"), str(tmp_path / "out"), changelog="regraded ep1")
    assert seen["rm"].changelog == "regraded ep1"


# --- Task 6: the two-phase edl_to_reel and the gate -------------------------------

def _manifest(tmp_path, n=2):
    """A ReelManifest whose clips are REAL files on disk: assemble_reel hashes each
    one (provenance.digest_file) to run the gate, so a fixture that only fakes the
    path would crash every digest-dependent test on a missing file instead of
    exercising the gate itself."""
    eps = []
    for i in range(n):
        clip = tmp_path / f"ep{i}.mp4"
        clip.write_bytes(f"clip-{i}".encode())
        eps.append(ReelEpisode(manifest={"segment": f"s{i}.mp4"}, clip=str(clip),
                               route=f"r{i}.json"))
    return ReelManifest(episodes=eps, target_dur=4.0)


def _blocking_finding():
    return EpisodeFinding(axis="composition", severity="blocking",
                          evidence="ep0 @1.2s, head clipped", route="reprocess",
                          suggestion="raise the crop by 6% of frame height")


def _qc(rm, findings_by_idx=None):
    """A ReelQC bound to rm's REAL clip bytes: clip_digest is computed the same way
    episode_qc.build stamps it (provenance.digest_file off the file on disk), so the
    gate reads these verdicts as judging THIS reel's clips, not stale ones."""
    findings_by_idx = findings_by_idx or {}
    verdicts = [EpisodeVerdict(idx=i, clip=ep.clip, clip_digest=provenance.digest_file(ep.clip),
                               findings=tuple(findings_by_idx.get(i, ())))
                for i, ep in enumerate(rm.episodes)]
    return ReelQC(episodes=tuple(verdicts))


def test_phase_two_refuses_a_reel_with_no_qc_artifact(tmp_path):
    rm = _manifest(tmp_path)                     # this file's existing helper style
    rm.write(tmp_path / "EPISODES.json")
    res = edl_to_reel.assemble_reel(str(tmp_path / "EPISODES.json"), str(tmp_path / "work"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "episode-qc-missing"


def test_phase_two_refuses_a_blocking_verdict_before_any_ffmpeg(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(edl_to_reel.build_reel, "build_reel",
                        lambda *a, **k: called.append(1))
    rm = _manifest(tmp_path)
    rm.write(tmp_path / "EPISODES.json")
    _qc(rm, {0: (_blocking_finding(),)}).write(tmp_path / "EPISODE_QC.json")
    res = edl_to_reel.assemble_reel(str(tmp_path / "EPISODES.json"), str(tmp_path / "work"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "episode-qc-blocking"
    assert called == []                          # nothing was assembled


def test_phase_two_passes_the_qc_state_into_the_run_provenance(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(edl_to_reel.build_reel, "build_reel",
                        lambda rm, *a, **k: seen.update(rm.provenance) or {"status": "delivered"})
    rm = _manifest(tmp_path)
    rm.write(tmp_path / "EPISODES.json")
    _qc(rm).write(tmp_path / "EPISODE_QC.json")                       # clean QC — no findings
    edl_to_reel.assemble_reel(str(tmp_path / "EPISODES.json"), str(tmp_path / "work"))
    assert seen["episode_qc"]["state"] == "judged"
    assert set(seen["episode_qc"]["judged"]) == {"0", "1"}


def test_the_single_command_path_records_that_nothing_judged_it(tmp_path, monkeypatch):
    """The SP1 hand-authored front door still ships unjudged — and says so (design §10)."""
    seen = {}
    _wire(monkeypatch)
    monkeypatch.setattr(edl_to_reel.build_reel, "build_reel",
                        lambda rm, *a, **k: seen.update(rm.provenance) or {"status": "delivered"})
    edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path), str(tmp_path),
                            str(tmp_path / "w"), str(tmp_path / "out"))
    assert seen["episode_qc"] == {"state": "absent"}


# --- Final review fix: #11's engine-drift guard now covers phase 2 too --------------
#
# _build_manifest (phase 1) already refused a straddling engine change; assemble_reel
# (phase 2) checked nothing. On the router's default path, N judge subagents (plus any
# fix round they trigger) sit between the two phases — exactly where the engine moves.

def test_phase_two_refuses_when_the_engine_drifted_since_phase_one(tmp_path, monkeypatch):
    rm = _manifest(tmp_path)
    rm.provenance = {"engine_at_start": {"sha": "aaaaaaa", "dirty": False}}
    rm.write(tmp_path / "EPISODES.json")
    _qc(rm).write(tmp_path / "EPISODE_QC.json")
    monkeypatch.setattr(edl_to_reel.provenance, "engine_stamp",
                        lambda: {"sha": "bbbbbbb", "dirty": False})
    with pytest.raises(ValueError, match="must not straddle an engine change"):
        edl_to_reel.assemble_reel(str(tmp_path / "EPISODES.json"), str(tmp_path / "work"))


def test_phase_two_does_not_stop_on_an_unknown_engine_stamp(tmp_path, monkeypatch):
    # Mirror image: an UNKNOWN stamp (here, engine_at_start — a run started before this
    # existed, or a box where git could not answer) cannot prove drift and must never
    # stop the run, exactly as the sibling guard in phase 1 (design §7).
    seen = []
    rm = _manifest(tmp_path)
    rm.provenance = {"engine_at_start": {"sha": "", "dirty": None}}
    rm.write(tmp_path / "EPISODES.json")
    _qc(rm).write(tmp_path / "EPISODE_QC.json")
    monkeypatch.setattr(edl_to_reel.provenance, "engine_stamp",
                        lambda: {"sha": "bbbbbbb", "dirty": False})
    monkeypatch.setattr(edl_to_reel.build_reel, "build_reel",
                        lambda *a, **k: seen.append(1) or {"status": "delivered"})
    res = edl_to_reel.assemble_reel(str(tmp_path / "EPISODES.json"), str(tmp_path / "work"))
    assert res["status"] == "delivered"
    assert seen == [1]


def test_phase_two_with_no_recorded_engine_at_start_never_stops(tmp_path, monkeypatch):
    # A manifest with no provenance at all (rm.provenance left at its {} default) — the
    # "absent" twin of the unknown-stamp case; same non-stopping guarantee.
    seen = []
    rm = _manifest(tmp_path)
    rm.write(tmp_path / "EPISODES.json")
    _qc(rm).write(tmp_path / "EPISODE_QC.json")
    monkeypatch.setattr(edl_to_reel.provenance, "engine_stamp",
                        lambda: {"sha": "bbbbbbb", "dirty": False})
    monkeypatch.setattr(edl_to_reel.build_reel, "build_reel",
                        lambda *a, **k: seen.append(1) or {"status": "delivered"})
    res = edl_to_reel.assemble_reel(str(tmp_path / "EPISODES.json"), str(tmp_path / "work"))
    assert res["status"] == "delivered"
    assert seen == [1]


# --- Final review fix: a cleaned-out out dir stops with a routed finding -----------

def test_phase_two_refuses_when_a_clip_is_gone_instead_of_crashing(tmp_path):
    # A cleaned out dir that kept EPISODES.json but lost the ep{i}.mp4 clips it names
    # used to crash provenance.digest_file with a bare FileNotFoundError traceback.
    rm = _manifest(tmp_path)
    rm.write(tmp_path / "EPISODES.json")
    Path(rm.episodes[0].clip).unlink()
    res = edl_to_reel.assemble_reel(str(tmp_path / "EPISODES.json"), str(tmp_path / "work"))
    assert res["status"] == "stop_and_report"
    assert res["finding"]["reason"] == "episode-clips-missing"
    assert "episode 0" in res["finding"]["problems"][0]


# --- Final review fix: phase 1's real body was only ever exercised through a fake --

def test_process_episodes_real_body_writes_episodes_json_into_the_out_dir(monkeypatch, tmp_path):
    # Everywhere else in this file, process_episodes is either the subject via a
    # monkeypatched process_episode.process_episode (the per-episode worker, faked by
    # _wire) or is itself monkeypatched out entirely (the CLI dispatch tests). This is
    # the one test that calls the REAL edl_to_reel.process_episodes end to end: it pins
    # that EPISODES.json lands IN the out dir — the location assemble_reel's
    # by-convention EPISODE_QC.json discovery rests on — and that the real returned
    # status is the "episodes_ready" the CLI's exit-0 set names, not a fake's string.
    seen = _wire(monkeypatch)
    captured = {}
    real_write = ReelManifest.write

    def spy_write(self, path):
        captured["rm"] = self
        real_write(self, path)
    monkeypatch.setattr(ReelManifest, "write", spy_write)
    out_dir = tmp_path / "out"
    res = edl_to_reel.process_episodes(_edl_file(tmp_path), _project(tmp_path),
                                       str(tmp_path), str(tmp_path / "w"), str(out_dir))
    assert res["status"] == "episodes_ready"          # the real string, not a fake's
    assert res["episodes"] == str(out_dir / "EPISODES.json")
    assert res["count"] == 2
    assert res["clips"] == [e.clip for e in captured["rm"].episodes]
    written = out_dir / "EPISODES.json"
    assert written.exists()                            # landed IN the out dir
    assert ReelManifest.from_json(written).to_dict() == captured["rm"].to_dict()
    assert seen["build"] == []                         # phase 1 never calls build_reel
