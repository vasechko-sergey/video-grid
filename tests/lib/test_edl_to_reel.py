import json
import threading
import pytest
from pathlib import Path
from scripts import edl_to_reel


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
    # The exception channel is read before the status channel, matching the
    # sequential loop where a raise aborted the function outright.
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
