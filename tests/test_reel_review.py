import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import reel_review
from scripts.lib import look as look_lib, provenance
from scripts.lib.look import LookSpec
from scripts.lib.models import CheckResult, ReelEpisode, ReelManifest, ReelReport
from scripts.lib.review import Review
from scripts.reel_review import build_review, write_review

RAW = [
    {"axis": "hook", "severity": "important", "evidence": "ep0 is a slow pan",
     "route": "edit-plan", "suggestion": "open on the jump-cut in ep2"},
    {"axis": "mood", "severity": "minor", "evidence": "track brighter than SPEC.mood",
     "route": "music", "suggestion": "pick a warmer cue", "confidence": "medium"},
]


def test_build_review_validates_and_sets_verdict():
    r = build_review(RAW, "out/REEL_v1.mp4", summary="delivers the calm idea")
    assert isinstance(r, Review) and r.verdict == "approve"   # no blocking finding
    assert len(r.findings) == 2 and r.findings[0].axis == "hook"
    assert r.summary == "delivers the calm idea"


def test_build_review_blocking_gives_revise():
    raw = [{"axis": "idea", "severity": "blocking", "evidence": "reel is a different story",
            "route": "edit-plan", "suggestion": "reselect windows to the SPEC idea"}]
    assert build_review(raw, "out/REEL_v1.mp4").verdict == "revise"


def test_build_review_rejects_bad_finding_writes_nothing():
    bad = [{"axis": "bogus", "severity": "minor", "evidence": "x", "route": "none", "suggestion": "y"}]
    with pytest.raises(ValueError, match="axis"):
        build_review(bad, "out/REEL_v1.mp4")


def test_build_review_names_every_bad_finding_inside_one_raise():
    # Modeled on test_episode_qc.py's test_build_names_every_bad_finding_inside_one_packet:
    # the reviewer has already exited by the time build_review runs, so raising on the
    # first bad finding buys nothing about the second and costs a whole round to learn
    # about it (design 2026-09-08 §6, task 1b).
    bad = [
        {"axis": "framing", "severity": "minor", "evidence": "e", "route": "none",
         "suggestion": "s"},                                    # bad axis
        {"axis": "colour", "severity": "minor", "evidence": "e", "route": "none"},   # no suggestion
    ]
    with pytest.raises(ValueError) as e:
        build_review(bad, "out/REEL_v1.mp4")
    msg = str(e.value)
    assert "finding 0" in msg and "finding 1" in msg


def test_build_review_rejects_non_list_findings():
    with pytest.raises(ValueError, match="list"):
        build_review({"axis": "hook"}, "out/REEL_v1.mp4")


def test_build_review_empty_findings_approves():
    r = build_review([], "out/REEL_v1.mp4")
    assert r.verdict == "approve" and r.findings == ()


def test_write_review_emits_both_files(tmp_path):
    r = build_review(RAW, "out/REEL_v1.mp4", platform="tiktok")
    res = write_review(r, str(tmp_path))
    assert res["status"] == "written" and res["verdict"] == "approve" and res["findings"] == 2
    assert (tmp_path / "REVIEW.json").exists() and (tmp_path / "REVIEW.md").exists()
    assert Review.from_json(tmp_path / "REVIEW.json").to_dict() == r.to_dict()
    assert (tmp_path / "REVIEW.md").read_text().startswith("# Reel review —")


import json
import sys


def _write_findings(tmp_path, obj):
    p = tmp_path / "review_findings.json"
    p.write_text(json.dumps(obj))
    return str(p)


def test_cli_build_writes_and_exits_0(tmp_path, monkeypatch, capsys):
    from scripts import reel_review
    findings = _write_findings(tmp_path, {"summary": "good", "findings": RAW})
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"delivered-bytes")
    monkeypatch.setattr(sys, "argv",
                        ["reel_review", "build", "--findings", findings,
                         "--reel", str(reel), "--platform", "tiktok",
                         "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        reel_review.main()
    assert e.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "written" and payload["findings"] == 2
    r = Review.from_json(tmp_path / "REVIEW.json")
    assert r.verdict == "approve" and r.summary == "good" and r.platform == "tiktok"


def test_cli_accepts_bare_list_findings(tmp_path, monkeypatch, capsys):
    from scripts import reel_review
    findings = _write_findings(tmp_path, RAW)   # bare list, no summary object
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"delivered-bytes")
    monkeypatch.setattr(sys, "argv",
                        ["reel_review", "build", "--findings", findings,
                         "--reel", str(reel), "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        reel_review.main()
    assert e.value.code == 0
    assert Review.from_json(tmp_path / "REVIEW.json").summary == ""


def test_cli_bad_findings_json_fails_loud(tmp_path, monkeypatch):
    from scripts import reel_review
    p = tmp_path / "review_findings.json"
    p.write_text("{not json")
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"delivered-bytes")
    monkeypatch.setattr(sys, "argv",
                        ["reel_review", "build", "--findings", str(p),
                         "--reel", str(reel), "--out-dir", str(tmp_path)])
    with pytest.raises(ValueError, match="valid JSON"):
        reel_review.main()


def test_build_review_stamps_the_digest_from_disk(tmp_path):
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"delivered-bytes")
    r = build_review(RAW, str(reel), summary="ok")
    assert r.reel_digest == provenance.digest_file(reel)


def test_build_review_ignores_a_digest_nobody_computed_from_disk(tmp_path):
    """The episode_qc idiom verbatim: the digest is computed HERE, so a reviewer
    cannot hand one in. There is no parameter to pass one through."""
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"delivered-bytes")
    with pytest.raises(TypeError):
        build_review(RAW, str(reel), reel_digest="deadbeef")


def test_build_review_leaves_the_digest_empty_when_the_file_is_absent():
    assert build_review(RAW, "out/REEL_v1.mp4").reel_digest == ""


def test_the_cli_refuses_a_reel_that_names_no_file(tmp_path, monkeypatch, capsys):
    findings = tmp_path / "f.json"
    findings.write_text(json.dumps(RAW))
    monkeypatch.setattr(sys, "argv",
                        ["reel_review", "build", "--findings", str(findings),
                         "--reel", str(tmp_path / "nope.mp4"), "--out-dir", str(tmp_path)])
    with pytest.raises(ValueError, match="names no file"):
        reel_review.main()


# --- second real run S14: pack grabs the stills and writes the reviewer's prompt ---

def test_still_times_clamp_every_grab_out_of_the_bookend_fade():
    look = LookSpec(fade=1.5, fade_in=0.0)
    t = reel_review.still_times([4.0, 4.0, 4.0], 12.0, look)
    assert t == {"hook": 0.5, "ending": 12.0 - 1.6, "mid0": 2.0, "mid1": 6.0, "mid2": 10.0}
    short = reel_review.still_times([1.0, 10.0, 1.0], 12.0, look)
    assert short["mid2"] == 12.0 - 1.6          # the last mid would sit in the fade-out


def test_still_times_read_the_head_off_a_look_with_one_fade():
    """The real run's look shape: one `fade`, no `fade_in` — the opening fades too."""
    t = reel_review.still_times([0.4, 5.6], 6.0, LookSpec(fade=0.8))
    assert t["hook"] == 0.8 + 0.1                # past the fade-in, not the bare 0.5
    assert t["mid0"] == t["hook"]                # a mid inside the fade-in is pulled out


def test_still_times_without_a_look_use_the_bare_margins():
    assert reel_review.still_times([3.0], 3.0, None) == {"hook": 0.5, "ending": 2.0,
                                                         "mid0": 1.5}


def test_still_times_step_back_off_a_flash_on_an_accented_closer():
    """Review I1: a 1.0 s accented photo closing the reel. The ending still is the
    latest frame clear of the fade-out, which is exactly the photo's cut — the flash's
    0.85 frame. Past the flash is the fade, so the still steps back a frame before the
    flash's window; the last mid, clamped onto the same instant, steps back with it."""
    durs, look = [3.0, 2.5, 1.0], LookSpec(fade=0.5)
    blind = reel_review.still_times(durs, 6.5, look)
    assert blind["ending"] == blind["mid2"] == 5.5          # on the cut that flashes
    t = reel_review.still_times(durs, 6.5, look, shutters=(2,), fps=30.0)
    w = look_lib.flash_windows([5.5], 30.0)
    assert t["ending"] == t["mid2"] == pytest.approx(5.5 - 2 / 30)
    assert all(look_lib.clear_of_flash(x, w) == x for x in t.values())
    assert {k: t[k] for k in ("hook", "mid0", "mid1")} == {
        k: blind[k] for k in ("hook", "mid0", "mid1")}      # the clear ones never move


def test_still_times_step_past_a_flash_on_an_accented_opener():
    """A run of short photos at the head clamps the hook onto the second one's cut."""
    t = reel_review.still_times([0.5, 0.5, 2.0], 3.0, None, shutters=(1,), fps=30.0)
    assert t["hook"] == pytest.approx(0.5 + 4 / 30)          # the window's end
    assert t["mid1"] == pytest.approx(0.75)                  # clear: untouched


def test_still_times_refuse_a_still_with_no_clear_frame_either_side():
    with pytest.raises(ValueError, match=r"shutter flash.*drop a `shutter`"):
        reel_review.still_times([0.5, 1.1], 1.6, None, shutters=(1,), fps=30.0)


def _run(tmp_path, *, music=True, spec=True, manifest_music=True, shutters=()):
    reel_dir = tmp_path / "montage" / "reels" / "main"
    for sub in ("episodes", "deliveries", "build/reel"):
        (reel_dir / sub).mkdir(parents=True)
    clips = []
    for i in range(2):
        c = reel_dir / "episodes" / f"ep{i}.mp4"
        c.write_bytes(b"x")
        clips.append(ReelEpisode(manifest={"segment": "s.mp4", "target_dur": 3.0},
                                 clip=str(c), route=None, path="", meta=""))
    music_path = reel_dir / "MUSIC.json"
    ReelManifest(episodes=clips, target_dur=6.0,
                 music=str(music_path) if music and manifest_music else None,
                 shutters=shutters).write(reel_dir / "episodes" / "EPISODES.json")
    reel = reel_dir / "deliveries" / "REEL_v1.mp4"
    reel.write_bytes(b"reel")
    (reel_dir / "EDL.md").write_text("# EDL\n\n| 0 | a.mp4 |\n")
    report = {"overall": True, "checks": {"length": {"passed": True}}}
    (reel_dir / "build" / "reel" / "reel_report.json").write_text(json.dumps(report))
    if spec:
        (reel_dir / "SPEC.md").write_text("# SPEC\n\nmood: calm\n")
        (reel_dir / "SPEC.json").write_text(json.dumps({"mood": "calm"}))
    if music:
        track = tmp_path / "montage" / "music" / "cache" / "t.webm"
        track.parent.mkdir(parents=True)
        track.write_bytes(b"a")
        track.with_suffix(".json").write_text(json.dumps(
            {"title": "Polar Onion", "artist": "Allah Las", "source": "youtube",
             "source_url": "u", "license": "unknown (any lane)", "date": "2026-10-16"}))
        music_path.write_text(json.dumps(
            {"track": str(track), "start_offset": 49.0, "duration": 6.0, "tempo": 117.0,
             "beats": [0.5, 1.0, 1.5], "energy": [0.1, 0.2], "energy_hz": 2.0,
             "bars": [0.5], "vocal_spans": []}))
        (reel_dir / "PACING.md").write_text("Verdict: fits at bar.\n")
    return reel_dir, reel, report


def _fake_media(monkeypatch):
    monkeypatch.setattr(reel_review.assembly, "probe_duration",
                        lambda p: 6.0 if "REEL" in str(p) else 3.0)
    monkeypatch.setattr(reel_review.assembly, "probe_stream",
                        lambda p: SimpleNamespace(fps=30.0, w=8, h=16))
    monkeypatch.setattr(reel_review.assembly, "frames_rgb",
                        lambda src, times, fps: [np.full((16, 8, 3), 100, np.uint8)
                                                 for _ in times])


def test_pack_writes_the_stills_and_a_filled_prompt(tmp_path, monkeypatch):
    _fake_media(monkeypatch)
    reel_dir, reel, _ = _run(tmp_path)
    res = reel_review.pack(str(reel), str(reel_dir))
    review = reel_dir / "build" / "_review"
    assert res["prompt"] == str(review / "reviewer_prompt.md")
    assert sorted(Path(p).name for p in res["stills"]) == [
        "ending.png", "hook.png", "mid0.png", "mid1.png"]
    assert all(Path(p).is_file() for p in res["stills"])
    text = (review / "reviewer_prompt.md").read_text()
    assert "{" + "SPEC}" not in text and "mood: calm" in text and '"mood": "calm"' in text
    assert "Stated intent" not in text            # nothing said, nothing added
    assert "| 0 | a.mp4 |" in text and '"overall": true' in text
    assert "Track: Allah Las — Polar Onion" in text and "from 49s" in text
    assert "Verdict: fits at bar." in text
    assert f"The reel is at {reel.resolve()}." in text
    assert str((review / "hook.png").resolve()) in text
    assert f"Write your output to {(reel_dir / 'review_findings.json').resolve()}" in text


def test_pack_grabs_its_stills_off_the_flashes_the_manifest_names(tmp_path, monkeypatch):
    """ep0 4 s and an accented ep1 of 1 s: the ending still (and the last mid) would sit
    on the flash at 4 s. pack hands still_times EPISODES.json's shutters and the
    reel's own fps, and grabs what it returns."""
    _fake_media(monkeypatch)
    monkeypatch.setattr(reel_review.assembly, "probe_duration",
                        lambda p: 5.0 if "REEL" in str(p) else (4.0 if "ep0" in str(p) else 1.0))
    grabbed = []
    monkeypatch.setattr(reel_review.assembly, "frames_rgb",
                        lambda src, times, fps: (grabbed.append((tuple(times), fps)),
                                                 [np.full((16, 8, 3), 100, np.uint8)
                                                  for _ in times])[1])
    reel_dir, reel, _ = _run(tmp_path, shutters=(1,))
    reel_review.pack(str(reel), str(reel_dir))
    want = reel_review.still_times([4.0, 1.0], 5.0, None, shutters=(1,), fps=30.0)
    assert grabbed == [(tuple(want.values()), 30.0)]
    assert 4.0 not in want.values()


def test_pack_names_a_silent_reel_and_a_missing_brief(tmp_path, monkeypatch):
    _fake_media(monkeypatch)
    reel_dir, reel, _ = _run(tmp_path, music=False, spec=False)
    text = Path(reel_review.pack(str(reel), str(reel_dir))["prompt"]).read_text()
    assert "silent reel" in text and "no SPEC" in text


def test_pack_refuses_a_report_from_a_different_render(tmp_path, monkeypatch):
    """The report sits in build/, which the next render rewrites; the delivery's own
    attestation records which report passed it."""
    _fake_media(monkeypatch)
    reel_dir, reel, report = _run(tmp_path)
    provenance.Attestation(reel=reel.name, reel_digest="r", master_digest="m",
                           report_digest=provenance.digest_obj({**report, "overall": False}),
                           overall=True).write(provenance.attest_path(reel))
    with pytest.raises(ValueError, match="different render"):
        reel_review.pack(str(reel), str(reel_dir))


def test_pack_accepts_the_report_the_attestation_names(tmp_path, monkeypatch):
    _fake_media(monkeypatch)
    reel_dir, reel, report = _run(tmp_path)
    provenance.Attestation(reel=reel.name, reel_digest="r", master_digest="m",
                           report_digest=provenance.digest_obj(report),
                           overall=True).write(provenance.attest_path(reel))
    assert reel_review.pack(str(reel), str(reel_dir))["report_bound"] is True


def test_pack_refuses_a_reel_dir_outside_the_run_layout(tmp_path, monkeypatch):
    _fake_media(monkeypatch)
    _, reel, _ = _run(tmp_path)
    with pytest.raises(ValueError, match="reels/<reel>"):
        reel_review.pack(str(reel), str(tmp_path))


def test_pack_describes_the_music_the_reel_was_built_with(tmp_path, monkeypatch):
    """Review finding: a leftover MUSIC.json beside a silent reel is not its music."""
    _fake_media(monkeypatch)
    reel_dir, reel, _ = _run(tmp_path, manifest_music=False)
    text = Path(reel_review.pack(str(reel), str(reel_dir))["prompt"]).read_text()
    assert "silent reel" in text and "Polar Onion" not in text


def test_pack_names_vocal_free_spans_as_such(tmp_path, monkeypatch):
    _fake_media(monkeypatch)
    reel_dir, reel, _ = _run(tmp_path)
    text = Path(reel_review.pack(str(reel), str(reel_dir))["prompt"]).read_text()
    assert "0 vocal-free spans" in text and "(MUSIC.json)" in text


def test_pack_carries_the_stated_intent_when_there_is_no_brief(tmp_path, monkeypatch):
    _fake_media(monkeypatch)
    reel_dir, reel, _ = _run(tmp_path, spec=False)
    res = reel_review.pack(str(reel), str(reel_dir), intent="a calm surf morning")
    text = Path(res["prompt"]).read_text()
    assert "no SPEC — judge against the EDL and the intent below" in text
    assert "Stated intent, in the user's words: a calm surf morning" in text


def test_pack_binds_the_report_exactly_as_deliver_attests_it(tmp_path, monkeypatch):
    """deliver digests report.to_dict(); pack digests the bytes ReelReport.write left on
    disk. If the two ever drift, every correct reel would be refused."""
    _fake_media(monkeypatch)
    reel_dir, reel, _ = _run(tmp_path)
    rep = ReelReport(checks={"length": CheckResult("length", True, {"dur": 6.04})},
                     episode_count=2, wall_s=1.25, master_digest="abc")
    rep.write(reel_dir / "build" / "reel" / "reel_report.json")
    provenance.Attestation(reel=reel.name, reel_digest="r", master_digest="abc",
                           report_digest=provenance.digest_obj(rep.to_dict()),
                           overall=rep.overall).write(provenance.attest_path(reel))
    assert reel_review.pack(str(reel), str(reel_dir))["report_bound"] is True


def test_pack_refuses_a_corrupt_report_with_a_remedy(tmp_path, monkeypatch):
    _fake_media(monkeypatch)
    reel_dir, reel, _ = _run(tmp_path)
    (reel_dir / "build" / "reel" / "reel_report.json").write_text("{")
    with pytest.raises(ValueError, match="re-deliver"):
        reel_review.pack(str(reel), str(reel_dir))


def test_pack_adds_a_stated_intent_beside_the_brief(tmp_path, monkeypatch):
    _fake_media(monkeypatch)
    reel_dir, reel, _ = _run(tmp_path)
    text = Path(reel_review.pack(str(reel), str(reel_dir), intent="more waves")["prompt"]
                ).read_text()
    assert "mood: calm" in text and "Stated intent, in the user's words: more waves" in text


def test_the_cli_forwards_the_stated_intent(tmp_path, monkeypatch, capsys):
    """The CLI is the skill's only path for the user's words; dropping the flag there
    would lose them without a sound."""
    _fake_media(monkeypatch)
    reel_dir, reel, _ = _run(tmp_path, spec=False)
    monkeypatch.setattr(sys, "argv", ["reel_review", "pack", "--reel", str(reel),
                                      "--reel-dir", str(reel_dir), "--intent", "calm surf"])
    with pytest.raises(SystemExit) as e:
        reel_review.main()
    assert e.value.code == 0
    prompt = json.loads(capsys.readouterr().out)["prompt"]
    assert "Stated intent, in the user's words: calm surf" in Path(prompt).read_text()
