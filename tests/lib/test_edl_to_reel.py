import json
import sys
import threading
import pytest
from pathlib import Path
from scripts import edl_to_reel
from scripts.lib import provenance
from scripts.lib.edl import EDL, EDLEpisode, write_edl
from scripts.lib.episode_qc import EpisodeFinding, EpisodeVerdict, ReelQC
from scripts.lib.footage import DESCRIPTOR_LEN
from scripts.lib.look import LookSpec
from scripts.lib.models import (EpisodeGeometry, ReelEpisode, ReelGeometry,
                                ReelManifest)
from scripts.lib.outro import OutroFit
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

    def fake_extract(edl, footage_root, seg_dir, project=None):
        segs = [str(Path(seg_dir) / f"ep{i}_raw.mp4") for i in range(len(edl.episodes))]
        Path(seg_dir).mkdir(parents=True, exist_ok=True)
        for s in segs:
            Path(s).write_text("segment")   # a real file: the real extract leaves one,
                                            # and phase 1b's inputs check looks for it
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

    def fake_pe(manifest, project_dir, route_path=None, *, stop_after=None,
                prepared_source=None):
        # key off project_dir's ep{i} suffix — the one per-call value that names the
        # episode. Call ORDER is not usable: under the pool (design §7.1) it is a race.
        idx = int(Path(project_dir).name.removeprefix("ep"))
        seen["pe"].append({"manifest": manifest, "project_dir": project_dir, "idx": idx,
                           "route_path": route_path, "stop_after": stop_after,
                           "prepared_source": prepared_source})
        seen["order"].append(("pe", project_dir))   # list.append is atomic under the GIL;
                                                    # only the order AMONG workers is undefined
        if idx in canned:
            return canned[idx]
        if stop_after == "geometry":
            # Stand in for process_episode's geometry return (design 2026-08-30 §2.1),
            # writing the two artifacts the next phase reads off disk: a real route.json
            # where the tracker would have left one, and the stabilize pre-stage's output
            # when the episode asks for one. A pan gets neither — it follows nobody.
            Path(project_dir).mkdir(parents=True, exist_ok=True)
            rp = (None if manifest.get("pan") is not None
                  else str(Path(project_dir) / "route.json"))
            if rp is not None:
                Path(rp).write_text(json.dumps(
                    [{"t": 0.0, "x": 960, "y": 540, "w": 120, "h": 120, "id": 1}]))
            src = manifest["segment"]
            if manifest.get("stabilize"):
                src = str(Path(project_dir) / "stabilized.mp4")
                Path(src).write_text("stabilized")
            return {"status": "geometry", "route": rp, "source": src, "timings": {},
                    "degraded": None}
        return {"status": "mechanical_pass", "clip": manifest["out_path"]}
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


def test_edl_to_reel_passes_the_edl_platform_to_the_reel_manifest(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path, platform="tiktok"), _project(tmp_path),
                            str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert seen["rm"].platform == "tiktok"


def test_edl_to_reel_leaves_the_reel_manifest_platform_empty_by_default(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path),
                            str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert seen["rm"].platform == ""


def test_edl_to_reel_passes_the_edls_look_to_the_reel_manifest(monkeypatch, tmp_path):
    # mirrors the platform pipe (2026-08-12): the EDL is the attested artifact, so the
    # look a reel was delivered with is recorded with the cut
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path, look={"vignette": 0.3, "fade": 0.8}),
                            _project(tmp_path), str(tmp_path), str(tmp_path / "w"),
                            str(tmp_path / "out"))
    assert seen["rm"].look == LookSpec(vignette=0.3, fade=0.8)


def test_edl_to_reel_leaves_the_reel_manifest_look_none_by_default(monkeypatch, tmp_path):
    # None = never authored — distinct from LookSpec() (authored as explicitly no look)
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path),
                            str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert seen["rm"].look is None


def test_edl_to_reel_carries_the_outro_onto_the_reel_manifest(monkeypatch, tmp_path):
    # mirrors the look pipe (test_edl_to_reel_passes_the_edls_look_to_the_reel_manifest
    # above): the EDL is the attested artifact, so the fit that CHOSE this reel's length
    # is recorded with the cut, and the reel loop can tell a chosen length from a
    # derived one (design 2026-08-16 §5).
    seen = _wire(monkeypatch)
    fit = OutroFit(reel_dur=10.7, line=10.2, fade=0.5, tail=1.8, rung="gap", moved=0.7)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path, outro=fit.to_dict()), _project(tmp_path),
                            str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert seen["rm"].outro == fit.to_dict()


def test_edl_to_reel_leaves_the_reel_manifest_outro_none_by_default(monkeypatch, tmp_path):
    # mirrors the look default test above: a hand-authored EDL through this SP1 front
    # door has no outro fit — None must reach the manifest untouched, so build_reel's
    # within-band absorb behaves exactly as it did before this slice.
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path),
                            str(tmp_path), str(tmp_path / "w"), str(tmp_path / "out"))
    assert seen["rm"].outro is None


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

    def fake_pe(manifest, project_dir, route_path=None):
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
    def fake_pe(manifest, project_dir, route_path=None):
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
    def fake_pe(manifest, project_dir, route_path=None):
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
# --from-episodes; --music/--jobs/--changelog were parsed and simply
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


def test_cli_refuses_a_color_delta_max_flag(monkeypatch, tmp_path):
    """The flag is retired with the check it tuned (design 2026-08-29 §2). argparse
    fails loud on an unrecognised argument, so a stale script or skill line stops the
    run rather than silently setting a ceiling nothing reads."""
    monkeypatch.setattr(sys, "argv",
                        ["edl_to_reel", str(tmp_path / "e.json"),
                         "--project", str(tmp_path / "p.json"),
                         "--footage-root", str(tmp_path),
                         "--work-dir", str(tmp_path / "w"),
                         "--out-dir", str(tmp_path / "o"),
                         "--color-delta-max", "20.0"])
    with pytest.raises(SystemExit):
        edl_to_reel.main()


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

    def fake_assemble_reel(episodes_path, work_dir, *, deliveries_dir=None, titles=None):
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
                              changelog=""):
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
                         deliveries_dir=None, music=None, titles=None,
                         jobs=edl_to_reel.DEFAULT_JOBS, changelog=""):
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
    def fake_pe(manifest, project_dir, route_path=None):
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
                            str(tmp_path / "w"), str(tmp_path / "o"))
    prov = seen["rm"].provenance
    assert prov["edl"]["state"] == "intact"
    # --color-delta-max is gone (design 2026-08-29 §2) and nothing else on this path
    # overrides a ReelCheckSpec field, so a plain run's provenance carries none.
    assert prov["overrides"] == []
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
    # retro 2026-10-16 S11: five identical "delivered from EDL.json" lines could not
    # tell one version from the next — the note now states what this cut IS
    edl = EDL.from_json(_edl_file(tmp_path))
    n = len(edl.episodes)
    total = sum(e.play_dur() for e in edl.episodes)
    assert seen["rm"].changelog == f"{n} episodes · {total:.1f}s · no music"
    assert "VERSIONS.md" not in seen["rm"].changelog


def test_an_explicit_changelog_wins(tmp_path, monkeypatch):
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path), str(tmp_path),
                            str(tmp_path / "w"), str(tmp_path / "out"), changelog="regraded ep1")
    assert seen["rm"].changelog.startswith("regraded ep1 — ")      # the reason, then the facts
    assert "episodes ·" in seen["rm"].changelog


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


# --- speed-ramp Task 6: the reel target reads played time
# (design docs/specs/2026-08-09-speed-ramp-design.md §6) ---

def _ramped_episode(dur=4.0, factor=0.4, **kw):
    """An EDLEpisode with a speed ramp centered in its window — same region shape
    as test_edl.py's RAMP (ease=0.5, hold=1.0), scaled to any dur >= 2.0 — plus the
    crop_scale=0.8 this module's own fixtures use (see _edl_file's default episode
    and test_preflight_resolves_all_episodes_clean's note above) so a 'lead'
    composition on a 'fill' layout has horizontal freedom and preflight, called
    inside _build_manifest, resolves it clean instead of stopping."""
    base = dict(source="a.mp4", start=0.0, dur=dur, shot_type="wide",
                composition="lead", grid="thirds", crop_scale=0.8,
                ramp={"at": dur / 2.0, "factor": factor, "ease": 0.5, "hold": 1.0})
    return EDLEpisode(**{**base, **kw})


def _plain_episode(dur=2.0, **kw):
    """The unramped twin of _ramped_episode, same preflight-clean shape."""
    base = dict(source="a.mp4", start=0.0, dur=dur, shot_type="wide",
                composition="lead", grid="thirds", crop_scale=0.8)
    return EDLEpisode(**{**base, **kw})


def _manifest_for(monkeypatch, tmp_path, eps, **edl_kw):
    """Write the EDL/project this module's driver tests already build (_edl_file /
    _project), stub the extract + per-episode fan-out the same way _wire does for
    every edl_to_reel() test above, then call _build_manifest DIRECTLY — never
    edl_to_reel.edl_to_reel, which would go on to render a whole reel. The target
    arithmetic under test runs inside _build_manifest, after both stubs."""
    _wire(monkeypatch)
    edl_path = _edl_file(tmp_path, episodes=[e.to_dict() for e in eps], **edl_kw)
    rm, stop = edl_to_reel._build_manifest(edl_path, _project(tmp_path), str(tmp_path),
                                           str(tmp_path / "w"), str(tmp_path / "out"))
    assert stop is None, stop
    return rm


def test_the_reel_target_sums_played_lengths(monkeypatch, tmp_path):
    eps = [_ramped_episode(dur=4.0, factor=0.4), _plain_episode(dur=3.0)]
    want = eps[0].play_dur() + 3.0
    rm = _manifest_for(monkeypatch, tmp_path, eps)
    assert rm.target_dur == pytest.approx(want)


def test_an_explicit_edl_target_still_wins(monkeypatch, tmp_path):
    eps = [_ramped_episode(dur=4.0, factor=0.4)]
    rm = _manifest_for(monkeypatch, tmp_path, eps, target_dur=12.0)
    assert rm.target_dur == 12.0


def test_an_unramped_reel_target_is_unchanged_from_before_the_ramp_slice(monkeypatch, tmp_path):
    # Global constraint: play_dur() == dur without a ramp, so an all-unramped EDL's
    # summed target must still be the plain sum of dur — numerically identical to
    # what this line computed before the ramp slice landed, asserted explicitly
    # rather than left as an unstated side effect of the ramped tests above.
    eps = [_plain_episode(dur=2.0), _plain_episode(dur=3.0)]
    rm = _manifest_for(monkeypatch, tmp_path, eps)
    assert rm.target_dur == pytest.approx(5.0)


# --- named-absence Task 4: EDL.brief_len -> ReelManifest.brief_len (design
# docs/specs/2026-09-07-named-absence-design.md §4) ---
# NOTE: the task brief's literal test calls a `_build_manifest_for(tmp_path, monkeypatch,
# brief_len=...)` helper this file has never defined under that name. `_manifest_for`
# (monkeypatch, tmp_path, eps, **edl_kw), defined above and already used by the ramp
# target-duration tests just above to call the real `_build_manifest` directly, IS this
# file's existing manifest-building helper — reused here with one `_plain_episode()`
# rather than adding a second one.

def test_the_manifest_carries_the_brief_length_off_the_edl(monkeypatch, tmp_path):
    """check_reel's `length` gate measures against EDL.target_dur, which came from the
    footage — a tautology with respect to the brief. brief_len is the one length that
    is not derived from the cut, so it must reach the manifest (design §4)."""
    rm = _manifest_for(monkeypatch, tmp_path, [_plain_episode()], brief_len=45.0)
    assert rm.brief_len == 45.0
    assert ReelManifest.from_dict(rm.to_dict()).brief_len == 45.0


def test_edl_to_reel_refuses_an_out_dir_equal_to_the_footage_root(tmp_path):
    """deliver writes ep{i}.mp4 and REEL_v{n}.mp4 into out_dir. Pointed at the
    footage folder those become source clips for the next intake — the same
    exposure draft.mp4 had, found reviewing this slice's own design, which had
    reasoned about who SCANS a directory rather than who writes an .mp4 into one."""
    with pytest.raises(ValueError, match="footage folder itself"):
        edl_to_reel.edl_to_reel(str(tmp_path / "EDL.json"), str(tmp_path / "project.json"),
                                str(tmp_path), str(tmp_path / "work"), str(tmp_path))


def test_edl_to_reel_refuses_a_work_dir_equal_to_the_footage_root(tmp_path):
    """work_dir holds the extracted segments and the reel master — also .mp4."""
    with pytest.raises(ValueError, match="footage folder itself"):
        edl_to_reel.edl_to_reel(str(tmp_path / "EDL.json"), str(tmp_path / "project.json"),
                                str(tmp_path), str(tmp_path), str(tmp_path / "out"))


def test_process_episodes_is_guarded_by_the_same_chokepoint(tmp_path):
    """Phase 1 has two public entries; both route through _build_manifest, so one
    call guards both. Phase 2 needs no guard — it derives out_dir from the
    EPISODES.json path that phase 1 already validated."""
    with pytest.raises(ValueError, match="footage folder itself"):
        edl_to_reel.process_episodes(str(tmp_path / "EDL.json"),
                                     str(tmp_path / "project.json"),
                                     str(tmp_path), str(tmp_path / "work"), str(tmp_path))


# --- Task 3: the guarded build wipe, and the deliveries split ---------------------

def test_phase_one_wipes_the_canonical_build_dir(tmp_path, capsys, monkeypatch):
    """17 work/ep* directories and 17 segments survived for an 8-episode reel
    because nothing ever deleted scratch (design §0)."""
    reel = tmp_path / "montage" / "reels" / "main"
    build, eps = reel / "build", reel / "episodes"
    (build / "ep99").mkdir(parents=True)
    eps.mkdir(parents=True)
    edl_to_reel._wipe_scratch(str(build), str(eps))
    assert not (build / "ep99").exists()
    assert "wiped" in capsys.readouterr().err


def test_phase_one_leaves_a_hand_driven_scratch_alone_and_says_so(tmp_path, capsys):
    """SP1's front door stays open — the cost named in design §8."""
    scratch = tmp_path / "scratch"
    (scratch / "keep").mkdir(parents=True)
    eps = tmp_path / "somewhere" / "episodes"
    eps.mkdir(parents=True)
    edl_to_reel._wipe_scratch(str(scratch), str(eps))
    assert (scratch / "keep").exists()
    err = capsys.readouterr().err
    assert "not the canonical" in err


def test_the_deliveries_dir_defaults_to_the_episodes_sibling(tmp_path):
    eps = tmp_path / "montage" / "reels" / "main" / "episodes"
    eps.mkdir(parents=True)
    assert edl_to_reel._deliveries_dir(None, str(eps)) == str(
        (tmp_path / "montage" / "reels" / "main" / "deliveries").resolve())


def test_an_explicit_deliveries_dir_wins(tmp_path):
    eps = tmp_path / "episodes"
    eps.mkdir()
    assert edl_to_reel._deliveries_dir(str(tmp_path / "elsewhere"), str(eps)) == str(
        tmp_path / "elsewhere")


def test_the_deliveries_dir_is_never_the_episodes_dir(tmp_path):
    """A human clearing the render output must not take the deliveries with it —
    that is what 47 `rm -rf out/` did (design §0)."""
    eps = tmp_path / "montage" / "reels" / "main" / "episodes"
    eps.mkdir(parents=True)
    assert edl_to_reel._deliveries_dir(None, str(eps)) != str(eps)


# --- Task 3 review, fix round 1: closing three coverage gaps ----------------------
#
# Finding 1: the wipe/refusal ORDER was never exercised at the level where reordering
# would be observable — both _wipe_scratch tests above call the helper directly, and
# the two pre-existing footage-refusal tests (test_edl_to_reel_refuses_a_work_dir_
# equal_to_the_footage_root / test_process_episodes_is_guarded_by_the_same_chokepoint)
# use work_dir/out_dir pairs where work_dir is not out_dir.parent/"build", so
# wipe_build is a silent no-op there regardless of call order.
#
# Finding 2: the deliveries split itself — the reason this task exists — had no test
# that inspected what build_reel.build_reel was actually called WITH; every existing
# seen["build"] assertion in this file only checks == [] in stop-and-report scenarios.

def test_a_footage_root_work_dir_is_refused_before_anything_is_wiped(tmp_path):
    """The marker file surviving IS the whole assertion. footage_root == work_dir ==
    out_dir's own canonical build-sibling, so this one setup is simultaneously (a)
    something refuse_output_in_footage must reject and (b) something wipe_build would
    otherwise wipe. Under the shipped order (refuse before wipe, _build_manifest lines
    100-102) the ValueError fires first and the marker is untouched; if a future edit
    moved _wipe_scratch above the two refuse_output_in_footage calls, the marker would
    be gone before the refusal ever raised — and neither pre-existing footage-refusal
    test in this file could catch that reordering, because their work_dir is never
    out_dir.parent/"build", so wipe_build is a no-op for them no matter which line
    runs first."""
    footage_root = work_dir = tmp_path / "build"
    work_dir.mkdir()
    marker = work_dir / "keep.txt"
    marker.write_text("scratch that must not be wiped before the refusal fires")
    out_dir = tmp_path / "out"          # out_dir.parent/"build" == work_dir: canonical
    with pytest.raises(ValueError, match="footage folder itself"):
        edl_to_reel.process_episodes(str(tmp_path / "EDL.json"), str(tmp_path / "project.json"),
                                     str(footage_root), str(work_dir), str(out_dir))
    assert marker.exists()


def test_phase_one_refuses_the_same_dir_for_work_and_out(tmp_path):
    """The wipe's predicate is "work_dir is out_dir's sibling named build". One
    arrangement satisfies it destructively: pass the same path for both, and the wipe
    takes the episode output — a prior EPISODES.json included — before this run has
    written a byte. Refused above the wipe, so nothing is deleted on the way to the
    error."""
    both = tmp_path / "build"
    both.mkdir()
    victim = both / "EPISODES.json"
    victim.write_text("{}")
    with pytest.raises(ValueError, match="same directory"):
        edl_to_reel.process_episodes(str(tmp_path / "EDL.json"), str(tmp_path / "project.json"),
                                     str(tmp_path / "footage"), str(both), str(both))
    assert victim.exists()


def test_phase_one_actually_wipes_the_build_dir_it_was_given(tmp_path):
    """Deleting the `_wipe_scratch(work_dir, out_dir)` call from _build_manifest left
    the whole suite byte-identical — measured by the final whole-branch review, which
    is the only reader that could see it: both _wipe_scratch tests call the helper
    DIRECTLY, and the one test that reaches _build_manifest asserts a marker SURVIVES,
    which is exactly what a missing wipe produces. So the feature could stop shipping
    in silence.

    This drives the real _build_manifest with a canonical build/episodes pair and
    asserts the scratch is gone. It stops at the EDL load — the wipe runs first, and
    reaching further would need a whole valid project."""
    reel = tmp_path / "montage" / "reels" / "main"
    work_dir, out_dir = reel / "build", reel / "episodes"
    (work_dir / "ep99").mkdir(parents=True)
    stale = work_dir / "ep99" / "route.json"
    stale.write_text("{}")
    out_dir.mkdir()
    with pytest.raises(Exception):        # the EDL does not exist; the wipe already ran
        edl_to_reel.process_episodes(str(tmp_path / "EDL.json"), str(tmp_path / "project.json"),
                                     str(tmp_path / "footage"), str(work_dir), str(out_dir))
    assert not stale.exists(), "the build dir was not wiped — _build_manifest's _wipe_scratch call is gone"
    assert work_dir.is_dir(), "the wipe must leave the directory in place, empty"


def test_edl_to_reel_delivers_to_the_episodes_sibling_deliveries_dir(monkeypatch, tmp_path):
    """Finding 2, call site 1 (edl_to_reel()). Every seen["build"] assertion elsewhere
    in this file only checks == [] in a stop-and-report scenario, so a revert to
    passing raw out_dir instead of _deliveries_dir(deliveries_dir, out_dir) at this
    call site would pass the whole suite untouched. This is the delivered happy path
    that actually inspects the directory build_reel.build_reel was called with."""
    seen = _wire(monkeypatch)
    out_dir = tmp_path / "montage" / "reels" / "main" / "episodes"
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path), str(tmp_path),
                                  str(tmp_path / "w"), str(out_dir))
    assert res["status"] == "delivered"
    delivered_to = seen["build"][0][0]
    assert delivered_to == str(edl_to_reel.runlayout.deliveries_for(str(out_dir)))
    assert delivered_to != str(out_dir.resolve())


def test_assemble_reel_delivers_to_the_episodes_sibling_deliveries_dir(monkeypatch, tmp_path):
    """Finding 2, call site 2 (assemble_reel()) — a SEPARATE line that can regress
    independently of edl_to_reel()'s own call site above: that test never calls
    assemble_reel at all, so a revert here would slip past it untouched."""
    seen = _wire(monkeypatch)
    episodes_dir = tmp_path / "montage" / "reels" / "main" / "episodes"
    episodes_dir.mkdir(parents=True)
    rm = _manifest(tmp_path)
    episodes_path = episodes_dir / "EPISODES.json"
    rm.write(episodes_path)
    _qc(rm).write(episodes_dir / "EPISODE_QC.json")
    res = edl_to_reel.assemble_reel(str(episodes_path), str(tmp_path / "work"))
    assert res["status"] == "delivered"
    delivered_to = seen["build"][0][0]
    assert delivered_to == str(edl_to_reel.runlayout.deliveries_for(str(episodes_dir)))
    assert delivered_to != str(episodes_dir.resolve())


def test_edl_to_reel_threads_an_explicit_deliveries_dir_to_build_reel(monkeypatch, tmp_path):
    """The two tests above only prove the DEFAULT sibling path. An explicit
    deliveries_dir= must reach build_reel.build_reel too — _deliveries_dir's own unit
    test (test_an_explicit_deliveries_dir_wins) never calls the driver at all, so it
    cannot catch deliveries_dir being accepted by edl_to_reel() and then dropped
    before it reaches build_reel.build_reel."""
    seen = _wire(monkeypatch)
    explicit = str(tmp_path / "wherever-i-say")
    res = edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path), str(tmp_path),
                                  str(tmp_path / "w"), str(tmp_path / "out"),
                                  deliveries_dir=explicit)
    assert res["status"] == "delivered"
    assert seen["build"][0][0] == explicit


def test_cli_refuses_deliveries_dir_combined_with_stop_after_episodes(monkeypatch, tmp_path):
    # Finding 3: --titles already refuses this combination (see
    # test_cli_refuses_titles_combined_with_stop_after_episodes above) because
    # process_episodes (phase 1) never delivers; --deliveries-dir has exactly the same
    # property and was silently accepted-and-dropped via main()'s kw dict.
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel", _edl_file(tmp_path),
                                      "--project", _project(tmp_path),
                                      "--footage-root", str(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out"),
                                      "--stop-after-episodes",
                                      "--deliveries-dir", str(tmp_path / "elsewhere")])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


# --- grade-shipped-pixels Task 3: phase 1 splits at the geometry boundary ---------
#
# match_grade measures each episode's SOURCE at its window midpoint; the reel ships
# the tracked crop, and measuring that crop needs the route to exist first. So phase
# 1 gains a seam: track everything, stop before any encode, let the conductor measure
# and author, then render over the frozen routes (design 2026-08-30 §2).


def _ep(**over):
    """One EDL episode row, the same default shape _edl_file builds its pair from."""
    return {**dict(source="a.mp4", start=0.0, dur=2.0, shot_type="wide",
                   composition="lead", grid="thirds", crop_scale=0.8), **over}


def _reel_dirs(tmp_path):
    """The CANONICAL build/episodes pair, not two loose directories.

    wipe_build's predicate is "work_dir is out_dir's sibling named build", so only
    this arrangement makes the wipe real — with a loose --work-dir the wipe is a
    silent no-op and test_from_geometry_does_not_wipe_the_build_dir below would pass
    against a phase 1b that wiped on every run."""
    reel = tmp_path / "reels" / "main"
    return str(reel / "build"), str(reel / "episodes")


def _stamped_project(tmp_path, stamp):
    """A project.json that RECORDS an engine stamp — _project's plain one records
    none, and the drift guard cannot fire against an empty stamp on either side."""
    p = tmp_path / "project.json"
    ProjectConfig(purpose="reel", canvas=(9, 16), delivery="native",
                  provenance={"v": 1, "engine": stamp, "self": "x", "inputs": {}}).write(p)
    return str(p)


def _geometry_run(tmp_path, monkeypatch, episodes=None, project=None, **edl_kw):
    """Phase 1a over the standard fake. Returns (geo, ctx) where ctx names the EDL,
    the project, the GEOMETRY.json, both dirs and the _wire recorder this run used."""
    seen = _wire(monkeypatch)
    edl_path = _edl_file(tmp_path, episodes=episodes, **edl_kw)
    project = project or _project(tmp_path)
    work, out = _reel_dirs(tmp_path)
    geo, stop = edl_to_reel.build_geometry(edl_path, project, str(tmp_path), work, out)
    assert stop is None
    return geo, {"edl": edl_path, "project": project, "work": work, "out": out,
                 "geometry": str(Path(out) / "GEOMETRY.json"), "seen": seen}


def _render(ctx, **kw):
    return edl_to_reel.render_from_geometry(ctx["geometry"], ctx["project"],
                                            ctx["work"], ctx["out"], **kw)


def _rewrite_edl(edl_path, index, **fields):
    doc = json.loads(Path(edl_path).read_text())
    doc["episodes"][index].update(fields)
    Path(edl_path).write_text(json.dumps(doc))


def _no_vidstab_probe(monkeypatch):
    """manifest.validate() calls the real, uncached vidstab.require() (an
    `ffmpeg -filters` spawn) for any manifest with stabilize=true, and preflight runs
    validate() on every episode. tests/lib/ is pure unit, no ffmpeg — same convention
    as tests/lib/test_manifest.py and test_process_episode.py's _stub_probe."""
    from scripts.lib import vidstab
    monkeypatch.setattr(vidstab, "require", lambda: None)


def test_build_geometry_writes_routes_and_no_clips(tmp_path, monkeypatch):
    """Phase 1a: GEOMETRY.json exists, out_dir holds no ep{i}.mp4."""
    geo, ctx = _geometry_run(tmp_path, monkeypatch)
    g = ReelGeometry.from_json(ctx["geometry"])
    assert len(g.episodes) == 2
    assert g.edl == ctx["edl"]
    assert not list(Path(ctx["out"]).glob("ep*.mp4"))
    # every episode stopped at the seam — nothing below it ran
    assert [m["stop_after"] for m in ctx["seen"]["pe"]] == ["geometry"] * 2
    assert g.episodes[0].route == str(Path(ctx["work"]) / "ep0" / "route.json")
    assert g.episodes[0].project_dir == str(Path(ctx["work"]) / "ep0")
    assert g.episodes[0].source == str(Path(ctx["work"]) / "segments" / "ep0_raw.mp4")


def test_build_geometry_records_the_engine_stamp_it_started_from(tmp_path, monkeypatch):
    # the same #11 guard EPISODES.json carries, so a run cannot straddle an engine
    # change across the conductor's turn either. The stamp is NON-EMPTY here on
    # purpose: _project's plain project.json records none, and {} == {} would hold
    # against a build_geometry that recorded nothing at all.
    stamp = {"sha": "aaaaaaa", "dirty": False}
    monkeypatch.setattr(edl_to_reel.provenance, "engine_stamp", lambda: stamp)
    geo, ctx = _geometry_run(tmp_path, monkeypatch,
                             project=_stamped_project(tmp_path, stamp))
    assert geo.provenance["engine_at_start"] == stamp


def test_geometry_stores_the_manifest_without_its_colour_block(tmp_path, monkeypatch):
    geo, ctx = _geometry_run(tmp_path, monkeypatch, episodes=[
        _ep(tone_src=[20.0, 100.0, 200.0], tone_dst=[30.0, 110.0, 210.0], dip=0.4)])
    # the manifest phase 1a actually ran DID carry the grade — without this the strip
    # assertion below would hold just as well against an EDL that never set one
    assert ctx["seen"]["pe"][0]["manifest"]["tone_src"] == [20.0, 100.0, 200.0]
    assert ctx["seen"]["pe"][0]["manifest"]["dip"] == 0.4
    assert geo.episodes[0].manifest["tone_src"] is None
    assert geo.episodes[0].manifest["tone_dst"] is None
    assert geo.episodes[0].manifest["dip"] == 0.0


def test_from_geometry_accepts_a_re_authored_grade(tmp_path, monkeypatch):
    """The seam's whole purpose: the EDL's colour block changed between the phases."""
    geo, ctx = _geometry_run(tmp_path, monkeypatch)
    _rewrite_edl(ctx["edl"], 0, tone_src=[20.0, 100.0, 200.0],
                 tone_dst=[30.0, 110.0, 210.0])
    rm, stop = _render(ctx)
    assert stop is None
    assert rm.episodes[0].manifest["tone_dst"] == [30.0, 110.0, 210.0]
    # to_manifest_dict omits the pair at its identity, so "absent" is the untouched shape
    assert "tone_dst" not in rm.episodes[1].manifest


def test_from_geometry_refuses_a_changed_cut(tmp_path, monkeypatch):
    geo, ctx = _geometry_run(tmp_path, monkeypatch)
    _rewrite_edl(ctx["edl"], 0, start=9.0)      # a different cut entirely
    with pytest.raises(ValueError, match="geometry was frozen"):
        _render(ctx)


def test_from_geometry_refuses_a_changed_layout(tmp_path, monkeypatch):
    # the OTHER half of the guard: `start` is invisible to the manifest (extract's
    # input, never a manifest field), `layout` is invisible to the cut identity
    geo, ctx = _geometry_run(tmp_path, monkeypatch)
    _rewrite_edl(ctx["edl"], 1, layout="fit")
    with pytest.raises(ValueError, match="geometry was frozen"):
        _render(ctx)


def test_from_geometry_refuses_a_changed_episode_count(tmp_path, monkeypatch):
    geo, ctx = _geometry_run(tmp_path, monkeypatch)
    doc = json.loads(Path(ctx["edl"]).read_text())
    doc["episodes"].append(_ep(start=4.0))
    Path(ctx["edl"]).write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="3 episodes.*froze 2"):
        _render(ctx)


def test_from_geometry_refuses_a_malformed_cut_entry_not_a_bare_attributeerror(
        tmp_path, monkeypatch):
    """Whole-branch review, minor 11: the length/type guard above checked `frozen` was
    a list of the right length, then `_refuse_on_changed_cut` indexed into an element
    with `.get(k)` — a non-dict element (a hand-edited or truncated GEOMETRY.json)
    raised a bare AttributeError instead of the "not written by --stop-after-geometry"
    refusal one line above. The guard now widens to reject a non-dict element too."""
    geo, ctx = _geometry_run(tmp_path, monkeypatch)
    doc = json.loads(Path(ctx["geometry"]).read_text())
    doc["provenance"]["cuts"][0] = "not-a-dict"
    Path(ctx["geometry"]).write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="records no cut identity"):
        _render(ctx)


def test_from_geometry_does_not_wipe_the_build_dir(tmp_path, monkeypatch):
    """The routes live there. Wiping between the phases destroys the input."""
    geo, ctx = _geometry_run(tmp_path, monkeypatch)
    work, out = ctx["work"], ctx["out"]
    # the marker IS destructible: this is the canonical build dir, so a _wipe_scratch
    # call here would really delete it (see _reel_dirs)
    assert Path(work).resolve() == Path(out).resolve().parent / "build"
    marker = Path(work) / "ep0" / "route.json"
    before = marker.read_bytes()
    _render(ctx)
    assert marker.read_bytes() == before


def test_from_geometry_does_not_re_extract(tmp_path, monkeypatch):
    # phase 1a already cut the segments the frozen routes were measured against;
    # re-cutting them would be waste, and a lie about which pixels were tracked
    geo, ctx = _geometry_run(tmp_path, monkeypatch)
    ctx["seen"]["segments"] = []
    _render(ctx)
    assert ctx["seen"]["segments"] == []


def test_from_geometry_hands_each_episode_its_frozen_route(tmp_path, monkeypatch):
    geo, ctx = _geometry_run(tmp_path, monkeypatch)
    ctx["seen"]["pe"].clear()
    rm, stop = _render(ctx)
    assert stop is None
    calls = sorted(ctx["seen"]["pe"], key=lambda m: m["idx"])
    assert [m["route_path"] for m in calls] == [eg.route for eg in geo.episodes]
    assert [m["stop_after"] for m in calls] == [None, None]      # rendered, not stopped
    # an unstabilized episode's source is md["segment"], which process_episode already
    # resolves — a second, redundant assertion path is exactly what prepared_source is not
    assert [m["prepared_source"] for m in calls] == [None, None]
    assert [e.route for e in rm.episodes] == [eg.route for eg in geo.episodes]


def test_a_stabilized_episode_is_handed_its_prepared_source(tmp_path, monkeypatch):
    _no_vidstab_probe(monkeypatch)
    geo, ctx = _geometry_run(tmp_path, monkeypatch,
                             episodes=[_ep(stabilize=True), _ep(start=2.0)])
    assert geo.episodes[0].source.endswith("ep0/stabilized.mp4")
    ctx["seen"]["pe"].clear()
    rm, stop = _render(ctx)
    assert stop is None
    calls = sorted(ctx["seen"]["pe"], key=lambda m: m["idx"])
    assert calls[0]["prepared_source"] == geo.episodes[0].source
    assert calls[0]["route_path"] == geo.episodes[0].route
    assert calls[1]["prepared_source"] is None


def test_a_pan_and_stabilize_episode_completes_from_geometry(tmp_path, monkeypatch):
    """pan and stabilize are independent EDL fields and nothing refuses the pair, but
    a pan has no route — and process_episode refuses a prepared source without one.
    The pair must therefore be handed NEITHER half, and re-run its own pre-stage."""
    _no_vidstab_probe(monkeypatch)
    geo, ctx = _geometry_run(tmp_path, monkeypatch, episodes=[
        _ep(stabilize=True, pan={"from": 0.0, "to": 1.0}, composition="center"),
        _ep(start=2.0)])
    assert geo.episodes[0].route is None
    ctx["seen"]["pe"].clear()
    rm, stop = _render(ctx)
    assert stop is None
    calls = sorted(ctx["seen"]["pe"], key=lambda m: m["idx"])
    assert calls[0]["route_path"] is None and calls[0]["prepared_source"] is None
    assert rm.episodes[0].route is None            # still the truth: nothing was tracked


def test_from_geometry_warms_no_weights_when_every_route_is_frozen(tmp_path, monkeypatch):
    # the warm-ups exist to stop N cold workers racing one weights download; an
    # episode handed a frozen route never reaches either model
    geo, ctx = _geometry_run(tmp_path, monkeypatch)
    ctx["seen"]["warm"].clear()
    _render(ctx)
    assert ctx["seen"]["warm"] == []


def test_from_geometry_warms_for_every_route_less_episode(tmp_path, monkeypatch):
    # The warm-up set is "every episode with no frozen route", and under `prepared`
    # that set is exactly the pans — which do NOT track (process_episode short-circuits
    # to an empty route). So what this pins is a deliberate SUPERSET: the warm-up here
    # is unnecessary, and keeping it is what makes the rule identical to the pre-split
    # one instead of a second copy of process_episode's rung logic, free to drift.
    # An episode whose geometry recorded route=None for a NON-pan reason would really
    # track, and is covered by the same rule.
    _no_vidstab_probe(monkeypatch)
    geo, ctx = _geometry_run(tmp_path, monkeypatch, episodes=[
        _ep(pan={"from": 0.0, "to": 1.0}, composition="center"), _ep(start=2.0)])
    ctx["seen"]["warm"].clear()
    _render(ctx)
    assert ctx["seen"]["warm"] == [edl_to_reel.track.MODEL]


# --- fix round 1: phase 1b never checked that its own inputs still exist -----------
#
# The routes and segments live in build/, which this seam exists to keep un-wiped —
# but the gap between the phases is a HUMAN turn, and any plain edl_to_reel or
# --stop-after-episodes run on the same reel dirs in that window wipes them.
# GEOMETRY.json survives next door in episodes/, preflight passes, the cut guard
# passes (not one path changed), and the run then died inside reframe._probe with a
# bare ffprobe error carrying no remedy. Same class as assemble_reel's
# episode-clips-missing stop, same answer.

def test_from_geometry_refuses_when_the_frozen_route_was_wiped(tmp_path, monkeypatch):
    geo, ctx = _geometry_run(tmp_path, monkeypatch)
    (Path(ctx["work"]) / "ep0" / "route.json").unlink()
    ctx["seen"]["pe"].clear()
    rm, stop = _render(ctx)
    assert rm is None
    assert stop["status"] == "stop_and_report"
    assert stop["finding"]["reason"] == "geometry-inputs-missing"
    assert stop["finding"]["episode_idx"] is None
    problems = stop["finding"]["problems"]
    assert len(problems) == 1                      # episode 1 is intact, and says nothing
    assert "episode 0's frozen route is gone" in problems[0]
    assert "--stop-after-geometry" in problems[0]  # the remedy, named
    assert ctx["seen"]["pe"] == []                 # refused before any episode ran


def test_from_geometry_refuses_when_a_segment_was_wiped(tmp_path, monkeypatch):
    # the other input, and the one every episode has — a pan carries no route at all
    geo, ctx = _geometry_run(tmp_path, monkeypatch)
    Path(geo.episodes[1].source).unlink()
    ctx["seen"]["pe"].clear()
    rm, stop = _render(ctx)
    assert rm is None and stop["finding"]["reason"] == "geometry-inputs-missing"
    problems = stop["finding"]["problems"]
    # ONE problem, not two: source == segment for an unstabilized episode, and the
    # report is keyed by path so the same missing file is named once
    assert len(problems) == 1
    assert "episode 1's extracted segment is gone" in problems[0]
    assert ctx["seen"]["pe"] == []


def test_from_geometry_refuses_when_the_prepared_source_was_wiped(tmp_path, monkeypatch):
    # the stabilize pre-stage's output is its own input, and lives in build/ too
    _no_vidstab_probe(monkeypatch)
    geo, ctx = _geometry_run(tmp_path, monkeypatch,
                             episodes=[_ep(stabilize=True), _ep(start=2.0)])
    assert geo.episodes[0].source.endswith("ep0/stabilized.mp4")
    Path(geo.episodes[0].source).unlink()
    ctx["seen"]["pe"].clear()
    rm, stop = _render(ctx)
    assert rm is None and stop["finding"]["reason"] == "geometry-inputs-missing"
    assert "episode 0's source reframe would consume is gone" in \
        stop["finding"]["problems"][0]
    assert ctx["seen"]["pe"] == []


def test_from_geometry_refuses_an_engine_change_since_the_geometry_was_frozen(
        tmp_path, monkeypatch):
    stamp = {"sha": "aaaaaaa", "dirty": False}
    monkeypatch.setattr(edl_to_reel.provenance, "engine_stamp", lambda: stamp)
    geo, ctx = _geometry_run(tmp_path, monkeypatch,
                             project=_stamped_project(tmp_path, stamp))
    monkeypatch.setattr(edl_to_reel.provenance, "engine_stamp",
                        lambda: {"sha": "ffff", "dirty": False})
    with pytest.raises(ValueError, match="engine changed since this run started"):
        _render(ctx)


def test_from_geometry_passes_a_preflight_stop_through(tmp_path, monkeypatch):
    geo, ctx = _geometry_run(tmp_path, monkeypatch)
    _rewrite_edl(ctx["edl"], 0, crop_scale=99.0)
    rm, stop = _render(ctx)
    assert rm is None and stop["status"] == "stop_and_report"
    assert stop["finding"]["reason"] == "edl-invalid"


def test_from_geometry_reports_the_lowest_failing_episode(tmp_path, monkeypatch):
    geo, ctx = _geometry_run(tmp_path, monkeypatch)
    ctx["seen"]["pe"].clear()
    rm, stop = edl_to_reel.render_from_geometry(
        ctx["geometry"], _project(tmp_path), ctx["work"], ctx["out"])   # sanity: passes
    assert stop is None
    _wire(monkeypatch, pe_results={1: {"status": "needs_input", "problems": ["x"]}})
    rm, stop = _render(ctx)
    assert rm is None
    assert stop["finding"] == {"reason": "episode-failed", "episode_idx": 1,
                               "sub_status": "needs_input"}


# --- the reel's common tone target reaches BOTH assembly sites --------------------

def test_the_edls_tone_target_reaches_the_reel_manifest(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path, tone_target=[20.0, 100.0, 200.0]),
                            _project(tmp_path), str(tmp_path), str(tmp_path / "w"),
                            str(tmp_path / "out"))
    assert seen["rm"].tone_target == (20.0, 100.0, 200.0)


def test_the_reel_manifest_tone_target_is_none_by_default(monkeypatch, tmp_path):
    seen = _wire(monkeypatch)
    edl_to_reel.edl_to_reel(_edl_file(tmp_path), _project(tmp_path), str(tmp_path),
                            str(tmp_path / "w"), str(tmp_path / "out"))
    assert seen["rm"].tone_target is None


def test_from_geometry_carries_the_tone_target_too(tmp_path, monkeypatch):
    geo, ctx = _geometry_run(tmp_path, monkeypatch)
    doc = json.loads(Path(ctx["edl"]).read_text())
    doc["tone_target"] = [20.0, 100.0, 200.0]      # what match_grade writes back
    Path(ctx["edl"]).write_text(json.dumps(doc))
    rm, stop = _render(ctx)
    assert stop is None and rm.tone_target == (20.0, 100.0, 200.0)


# --- the CLI's two new phase flags -------------------------------------------------

def test_cli_stop_after_geometry_dispatches_to_build_geometry(monkeypatch, tmp_path):
    seen = {}

    def fake_build_geometry(edl_path, project_path, footage_root, work_dir, out_dir, *,
                            jobs=edl_to_reel.DEFAULT_JOBS):
        seen["called"] = "build_geometry"
        seen["out_dir"] = out_dir
        seen["jobs"] = jobs
        return ReelGeometry(episodes=(EpisodeGeometry(manifest={}, route=None,
                                                      source="s.mp4", project_dir="d"),),
                            edl="EDL.json"), None
    monkeypatch.setattr(edl_to_reel, "build_geometry", fake_build_geometry)
    monkeypatch.setattr(edl_to_reel, "edl_to_reel",
                        lambda *a, **k: seen.setdefault("wrong_fn", "edl_to_reel"))
    monkeypatch.setattr(sys, "argv", ["edl_to_reel", _edl_file(tmp_path),
                                      "--project", _project(tmp_path),
                                      "--footage-root", str(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out"),
                                      "--stop-after-geometry"])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 0
    assert seen["called"] == "build_geometry" and "wrong_fn" not in seen
    assert seen["out_dir"] == str(tmp_path / "out")


def test_cli_from_geometry_dispatches_to_render_from_geometry(monkeypatch, tmp_path):
    seen = {}

    def fake_render(geometry_path, project_path, work_dir, out_dir, *, music=None,
                    jobs=edl_to_reel.DEFAULT_JOBS, changelog=""):
        seen.update(geometry=geometry_path, project=project_path, work_dir=work_dir,
                    out_dir=out_dir, jobs=jobs)
        return ReelManifest(episodes=[ReelEpisode(
            manifest={"segment": "s.mp4", "out_path": str(tmp_path / "ep0.mp4")},
            clip=str(tmp_path / "ep0.mp4"), route=None, path="p.json",
            meta="m.json")], target_dur=2.0), None
    monkeypatch.setattr(edl_to_reel, "render_from_geometry", fake_render)
    monkeypatch.setattr(edl_to_reel, "edl_to_reel",
                        lambda *a, **k: seen.setdefault("wrong_fn", "edl_to_reel"))
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(sys, "argv", ["edl_to_reel",
                                      "--project", _project(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(out),
                                      "--from-geometry", str(tmp_path / "GEOMETRY.json"),
                                      "--jobs", "2"])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 0
    assert "wrong_fn" not in seen
    assert seen["geometry"] == str(tmp_path / "GEOMETRY.json") and seen["jobs"] == 2
    # it ends where --stop-after-episodes ends: EPISODES.json, ready for the QC gate
    assert (out / "EPISODES.json").exists()


def test_cli_from_geometry_refuses_a_positional_edl(monkeypatch, tmp_path):
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(edl_to_reel, "render_from_geometry",
                        lambda *a, **k: called.append("render_from_geometry"))
    monkeypatch.setattr(sys, "argv", ["edl_to_reel", _edl_file(tmp_path),
                                      "--project", _project(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out"),
                                      "--from-geometry", str(tmp_path / "GEOMETRY.json")])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


def test_cli_from_geometry_refuses_a_footage_root_flag(monkeypatch, tmp_path):
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(edl_to_reel, "render_from_geometry",
                        lambda *a, **k: called.append("render_from_geometry"))
    monkeypatch.setattr(sys, "argv", ["edl_to_reel",
                                      "--project", _project(tmp_path),
                                      "--footage-root", str(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out"),
                                      "--from-geometry", str(tmp_path / "GEOMETRY.json")])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


@pytest.mark.parametrize("other", [["--from-geometry", "g.json"],
                                   ["--from-episodes", "e.json"],
                                   ["--stop-after-episodes"]])
def test_cli_stop_after_geometry_is_exclusive_with_every_other_phase(monkeypatch, tmp_path,
                                                                    other):
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(edl_to_reel, "build_geometry",
                        lambda *a, **k: called.append("build_geometry"))
    monkeypatch.setattr(edl_to_reel, "render_from_geometry",
                        lambda *a, **k: called.append("render_from_geometry"))
    monkeypatch.setattr(sys, "argv", ["edl_to_reel",
                                      "--work-dir", str(tmp_path / "w"),
                                      "--stop-after-geometry", *other])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2            # argparse's own mutually_exclusive_group
    assert called == []


def test_cli_refuses_titles_combined_with_from_geometry(monkeypatch, tmp_path):
    called = _no_dispatch(monkeypatch)
    monkeypatch.setattr(edl_to_reel, "render_from_geometry",
                        lambda *a, **k: called.append("render_from_geometry"))
    monkeypatch.setattr(sys, "argv", ["edl_to_reel",
                                      "--project", _project(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out"),
                                      "--from-geometry", str(tmp_path / "GEOMETRY.json"),
                                      "--titles", "TITLES.json"])
    with pytest.raises(SystemExit) as ei:
        edl_to_reel.main()
    assert ei.value.code == 2
    assert called == []


# --- chroma-spread Task 4: the carrier, phase 1 (design
# docs/specs/2026-09-17-chroma-spread-design.md §2.3) ---
# NOTE: the task brief's literal test calls a `_build_manifest_with(results=...)`
# helper described as calling "the real _build_manifest" — but _build_manifest
# (edl_path, project_path, footage_root, work_dir, out_dir, ...) reads the EDL off
# disk and fans process_episode out across a real ThreadPoolExecutor, so a test
# with neither tmp_path nor monkeypatch (Step 1's tests, verbatim) cannot be
# driving it. The function whose signature the brief's own "Context you need"
# names — `_build_manifest(mds, results, routes, epdirs, ...)`, building the
# ReelEpisode list straight from results[i] — is `_reel_manifest`, the pure
# assembly step _build_manifest calls once its pool has already returned.
# Mirrors the same naming drift already logged above
# test_the_manifest_carries_the_brief_length_off_the_edl. mds/routes/epdirs are
# placeholders _reel_manifest only zips against results and never inspects, and
# edl is one _plain_episode() — target_dur resolves off it but neither test below
# asserts on target_dur.

def _build_manifest_with(results):
    n = len(results)
    mds = [{} for _ in range(n)]
    routes = [None] * n
    epdirs = [f"ep{i}" for i in range(n)]
    edl = EDL(episodes=(_plain_episode(),))
    return edl_to_reel._reel_manifest(mds, results, routes, epdirs, edl, "EDL.json",
                                      music=None, changelog="", started={})


def test_phase_one_records_each_episodes_chroma_displacement():
    """The pair is rendered once, in phase 1. The reel reads the number phase 1
    already produced rather than paying for a second pair (design §2.3).

    Two episodes with DIFFERENT readings (fix round 1, Minor rider): a single-
    episode results list cannot tell `chroma=color_fidelity.shift_from_report(
    res.get("report") or {})` (loop-bound `res`) apart from a bug that hardcoded
    `results[0]["report"]` while still correctly using the loop-bound `res` for
    `clip=` — both would report episode 0's reading at every index. Asserting
    both episodes land their OWN reading at their OWN index is what a one-episode
    fixture cannot exercise."""
    rm = _build_manifest_with(results=[
        {"status": "mechanical_pass", "clip": "ep0.mp4",
         "report": {"checks": {"grade_damage": {
             "region": "crop", "delta_c": -4.18, "delta_h": -1.22, "pass": True}}}},
        {"status": "mechanical_pass", "clip": "ep1.mp4",
         "report": {"checks": {"grade_damage": {
             "region": "crop", "delta_c": 7.50, "delta_h": 3.00, "pass": True}}}}])
    # No `region` key on the carried reading (final whole-branch review, FIX 1) —
    # the INPUT report above still carries it (that's check_episode's own report
    # shape, unaffected), but shift_from_report's output does not.
    assert rm.episodes[0].chroma == {"delta_c": -4.18, "delta_h": -1.22}
    assert rm.episodes[1].chroma == {"delta_c": 7.50, "delta_h": 3.00}


def test_phase_one_records_a_named_absence_when_the_pair_was_refused():
    rm = _build_manifest_with(results=[
        {"status": "mechanical_pass", "clip": "ep0.mp4",
         "report": {"checks": {"grade_damage": {
             "status": "not-checked", "reason": "no render pair"}}}}])
    assert rm.episodes[0].chroma["reason"] == "no render pair"


# --- threshold-surface Task 4: edl_to_reel is the one finder (design
# docs/specs/2026-09-30-threshold-surface-design.md §0.5/§2.3) ---
#
# GATES.json is found BY CONVENTION beside project.json, at RUN time, by every arm that
# drives the pool — and there are three of them, not two: the single-pass arm
# (_build_manifest), phase 1a (build_geometry), and phase 1b (render_from_geometry), which
# never goes through _phase_one_setup. Phase 1b is the arm the conveyor actually renders
# through (`--from-geometry`, since 2026-08-30), so a finder wired into the other two alone
# would have shipped this slice as a no-op on the only path that matters.

GATES_DOC = {"loudness_tol": {"value": 2.0, "why": "live room"},
             "entropy_floor": {"value": 0.85, "why": "log profile"}}
BROKEN_GATES = json.dumps({"entropy_floor": 0.85})        # a bare value: no written reason
ARMS = ["single-pass", "geometry", "from-geometry"]


def _spy_episode_kwargs(monkeypatch, passed):
    """Wrap the process_episode fake `_wire` installed, recording into `passed` the EXTRA
    keyword arguments each episode was handed.

    The fake takes no `gates`, exactly as the real call shape did before this slice, so the
    wrapper strips it before delegating: what is under test is what the pool PASSED, not what
    a fake tolerates. Everything else is forwarded untouched, so every other signature check
    in this file still bites."""
    inner = edl_to_reel.process_episode.process_episode

    def spy(md, project_dir, route_path=None, **kw):
        passed.append(dict(kw))
        return inner(md, project_dir, route_path,
                     **{k: v for k, v in kw.items() if k != "gates"})
    monkeypatch.setattr(edl_to_reel.process_episode, "process_episode", spy)


def _run_arm(arm, tmp_path, monkeypatch, gates_text, ran):
    """Drive one of phase 1's three pool-driving arms over the standard fakes, with
    `gates_text` written as GATES.json beside project.json (None = no file).

    `ran` is an out-parameter filled AS the arm progresses, so a test of a refusal still holds
    what ran before it: "seen" (the _wire recorder), "passed" (the kwargs each episode was
    handed — only the arm under test, never the geometry run the from-geometry arm needs
    first) and, when the arm assembles one, "rm".

    The from-geometry arm writes GATES.json AFTER its geometry run, on purpose: the file is
    found at RUN time, and the conveyor's real order is --stop-after-geometry, then the
    conductor, then --from-geometry (design §2.3). A finder only the first arm called, or a
    document frozen into GEOMETRY.json at 1a, would pass a test that wrote the file first."""
    def write_gates():
        if gates_text is not None:
            (tmp_path / "GATES.json").write_text(gates_text)

    if arm == "from-geometry":
        _, ctx = _geometry_run(tmp_path, monkeypatch)
        ran["seen"] = ctx["seen"]
        ran["passed"] = []
        _spy_episode_kwargs(monkeypatch, ran["passed"])
        write_gates()
        rm, stop = _render(ctx)
        assert stop is None, stop
        ran["rm"] = rm
        return
    ran["seen"] = _wire(monkeypatch)
    ran["passed"] = []
    _spy_episode_kwargs(monkeypatch, ran["passed"])
    write_gates()
    work, out = _reel_dirs(tmp_path)
    edl_path, project = _edl_file(tmp_path), _project(tmp_path)
    if arm == "geometry":
        _, stop = edl_to_reel.build_geometry(edl_path, project, str(tmp_path), work, out)
        assert stop is None, stop
        return
    rm, stop = edl_to_reel._build_manifest(edl_path, project, str(tmp_path), work, out)
    assert stop is None, stop
    ran["rm"] = rm


def test_gates_json_beside_project_json_is_found_with_no_flag(tmp_path, monkeypatch):
    _wire(monkeypatch)
    _spy_episode_kwargs(monkeypatch, [])       # _wire's fake takes no `gates`; the spy strips it
    (tmp_path / "GATES.json").write_text(json.dumps(GATES_DOC))
    rm, stop = edl_to_reel._build_manifest(
        _edl_file(tmp_path), project_path=_project(tmp_path), footage_root=str(tmp_path),
        work_dir=str(tmp_path / "w"), out_dir=str(tmp_path / "out"))
    assert stop is None, stop
    assert rm.gates == GATES_DOC                       # the WHOLE document, both scopes
    assert rm.check_spec.loudness_tol == 2.0           # and the reel half of it is applied


@pytest.mark.parametrize("arm", ARMS)
def test_the_pool_hands_the_authored_gates_to_every_episode(arm, tmp_path, monkeypatch, capsys):
    """Every episode, in every pool-driving arm, is judged against the WHOLE authored
    document — both scopes, unpartitioned: process_episode partitions where a spec is built,
    so no caller does (design §2.3). And the kwarg exists ONLY when a file does: the pool's
    kwargs are built 'only when it carries something', which keeps the call shape identical to
    the pre-gates one. That second half is a control INSIDE this test and not beside it, so the
    instrument has just been shown able to see a `gates` kwarg before it is trusted to report
    the absence of one.

    The announcement is pinned whole — the count, WHICH bars, and the project.json the file was
    found beside — because that line is the only sign a GATES.json beside the wrong project.json
    was or was not picked up: dropping the names or the path must not stay green."""
    (tmp_path / "with").mkdir()
    (tmp_path / "without").mkdir()

    ran = {}
    _run_arm(arm, tmp_path / "with", monkeypatch, json.dumps(GATES_DOC), ran)
    assert [c.get("gates") for c in ran["passed"]] == [GATES_DOC, GATES_DOC]
    if "rm" in ran:
        assert ran["rm"].gates == GATES_DOC
    err = capsys.readouterr().err
    assert "2 authored threshold(s) (loudness_tol, entropy_floor)" in err
    assert str(tmp_path / "with" / "project.json") in err

    ran = {}
    _run_arm(arm, tmp_path / "without", monkeypatch, None, ran)
    assert len(ran["passed"]) == 2
    assert all("gates" not in c for c in ran["passed"])
    if "rm" in ran:
        assert ran["rm"].gates == {}
        assert "gates" not in ran["rm"].to_dict()      # EPISODES.json stays byte-identical
    assert "authored threshold" not in capsys.readouterr().err


@pytest.mark.parametrize("arm", ["single-pass", "from-geometry"])
def test_a_broken_gates_file_stops_the_run_and_names_the_path(arm, tmp_path, monkeypatch):
    """No waiver and no fallback to defaults: a file that exists and cannot be loaded stops
    the run with its own path in the message (design §2.2/§6). It stops AHEAD of the work —
    the pool and, in the arm that extracts, the extract itself — because a refusal that comes
    after the encode is a refusal an encode late.

    Two arms, not three: build_geometry reads its gates through the SAME _phase_one_setup as
    the single-pass arm, so a third case would kill no mutation the first does not. Phase 1b
    has a read of its own, which is why it is here."""
    ran = {}
    with pytest.raises(ValueError) as e:
        _run_arm(arm, tmp_path, monkeypatch, BROKEN_GATES, ran)
    assert str(tmp_path / "GATES.json") in str(e.value)
    assert ran["passed"] == []
    if arm == "single-pass":                           # phase 1b extracts nothing to begin with
        assert ran["seen"]["segments"] == []


# --- retro 2026-10-16 S11: the version note on the router's own path ------------------

def test_the_render_step_records_the_reason_in_the_manifest(tmp_path, monkeypatch):
    geo, ctx = _geometry_run(tmp_path, monkeypatch)
    rm, stop = _render(ctx, changelog="ending: the other silhouette")
    assert stop is None and rm.changelog.startswith("ending: the other silhouette — ")


def test_the_cli_render_step_passes_its_changelog(monkeypatch, tmp_path):
    seen = {}

    def fake_render(geometry_path, project_path, work_dir, out_dir, *, music=None,
                    jobs=edl_to_reel.DEFAULT_JOBS, changelog=""):
        seen["changelog"] = changelog
        return None, {"status": "stop_and_report", "finding": {"reason": "x"}}
    monkeypatch.setattr(edl_to_reel, "render_from_geometry", fake_render)
    monkeypatch.setattr(sys, "argv", ["edl_to_reel", "--project", _project(tmp_path),
                                      "--work-dir", str(tmp_path / "w"),
                                      "--out-dir", str(tmp_path / "out"),
                                      "--from-geometry", str(tmp_path / "GEOMETRY.json"),
                                      "--changelog", "balance 50/50"])
    with pytest.raises(SystemExit):
        edl_to_reel.main()
    assert seen["changelog"] == "balance 50/50"


def test_the_cut_summary_names_the_track_and_its_offset(tmp_path):
    from scripts.lib.models import MusicSpec
    edl = EDL.from_json(_edl_file(tmp_path))
    mj = tmp_path / "MUSIC.json"
    mj.write_text(json.dumps(MusicSpec("/x/lets-go-surfing.webm", 49.0, 45.0, 117.0,
                                       (0.0, 0.5), (0.3,), 2.0).to_dict()))
    assert edl_to_reel._cut_summary(edl, 45.66, str(mj)).endswith(
        "45.7s · music: lets-go-surfing @ 49.0s")
    (tmp_path / "bad.json").write_text("{")
    assert "music: bad.json (unreadable)" in edl_to_reel._cut_summary(
        edl, 45.66, str(tmp_path / "bad.json"))


# --- backlog U3: EDL.music_in_app -> ReelManifest.music_in_app (design 2026-10-20 §1) ---

def test_the_manifest_carries_music_in_app_off_the_edl(monkeypatch, tmp_path):
    _wire(monkeypatch)
    music = tmp_path / "MUSIC.json"
    music.write_text("{}")
    edl_path = _edl_file(tmp_path, episodes=[_plain_episode().to_dict()], music_in_app=True)
    rm, stop = edl_to_reel._build_manifest(edl_path, _project(tmp_path), str(tmp_path),
                                           str(tmp_path / "w"), str(tmp_path / "out"),
                                           music=str(music))
    assert stop is None and rm.music_in_app is True


def test_music_in_app_without_music_is_refused_before_the_pool_renders(monkeypatch, tmp_path):
    _wire(monkeypatch)
    monkeypatch.setattr(edl_to_reel, "_run_pool",
                        lambda *a, **k: pytest.fail("the pool ran before the refusal"))
    edl_path = _edl_file(tmp_path, episodes=[_plain_episode().to_dict()], music_in_app=True)
    with pytest.raises(ValueError, match="edl_to_reel --music"):
        edl_to_reel._build_manifest(edl_path, _project(tmp_path), str(tmp_path),
                                    str(tmp_path / "w"), str(tmp_path / "out"))
