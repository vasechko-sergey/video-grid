from dataclasses import replace

from scripts import match_grade
from scripts.lib.edl import EDLEpisode, EDL


def _ep(source, start=0.0, dur=2.0, **kw):
    return EDLEpisode(source=source, start=start, dur=dur, shot_type="wide",
                      composition="center", grid="thirds", **kw)


def _edl(*eps):
    return EDL(episodes=tuple(eps))


def test_conduct_measures_at_the_window_midpoint(monkeypatch):
    seen = []
    monkeypatch.setattr(match_grade, "measure_profile",
                        lambda clip, at=None: seen.append((clip, at)) or (10.0, 100.0, 150.0))
    edl = _edl(_ep("a.mp4", start=4.0, dur=2.0))
    match_grade.conduct(edl, "/foot")
    assert seen == [("/foot/a.mp4", 5.0)]           # start + dur/2, resolved under footage_root


def test_conduct_authors_deviating_and_leaves_near_median(monkeypatch):
    # ep0 dark, ep1 bright → median between; ep2 sits on the median (within eps)
    profs = {"d.mp4": (10.0, 90.0, 150.0), "b.mp4": (40.0, 130.0, 240.0),
             "m.mp4": (25.0, 110.0, 195.0)}
    monkeypatch.setattr(match_grade, "measure_profile", lambda clip, at=None: profs[clip.split("/")[-1]])
    edl = _edl(_ep("d.mp4"), _ep("b.mp4"), _ep("m.mp4"))
    out, target, decisions = match_grade.conduct(edl, "/foot")
    assert target == (25.0, 110.0, 195.0)            # per-anchor median of the three
    assert out.episodes[0].tone_src == (10.0, 90.0, 150.0) and out.episodes[0].tone_dst == target
    assert out.episodes[1].tone_src == (40.0, 130.0, 240.0)
    assert out.episodes[2].tone_src is None          # within eps → no pair, byte-identical
    assert out.episodes[0] == replace(edl.episodes[0], tone_src=(10.0, 90.0, 150.0), tone_dst=target)


def test_conduct_leaves_a_hand_authored_pair(monkeypatch):
    monkeypatch.setattr(match_grade, "measure_profile", lambda clip, at=None: (10.0, 90.0, 150.0))
    edl = _edl(_ep("d.mp4", tone_src=(5.0, 80.0, 140.0), tone_dst=(20.0, 110.0, 210.0)))
    out, _, _ = match_grade.conduct(edl, "/foot")
    assert out.episodes[0].tone_src == (5.0, 80.0, 140.0)     # untouched
    assert out.episodes[0] == edl.episodes[0]      # whole episode untouched, not just tone_src


def test_conduct_force_clears_a_now_within_eps_pair(monkeypatch):
    # a previously-authored episode now sits on the median → force removes the stale pair
    profs = {"d.mp4": (25.0, 110.0, 195.0), "b.mp4": (25.0, 110.0, 195.0)}
    monkeypatch.setattr(match_grade, "measure_profile", lambda clip, at=None: profs[clip.split("/")[-1]])
    edl = _edl(_ep("d.mp4", tone_src=(5.0, 80.0, 140.0), tone_dst=(20.0, 110.0, 210.0)), _ep("b.mp4"))
    out, _, _ = match_grade.conduct(edl, "/foot", force=True)
    assert out.episodes[0].tone_src is None and out.episodes[0].tone_dst is None
