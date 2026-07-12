import pytest
from scripts.lib.footage import FootageWindow, FootageClip, Footage


def _win(**kw):
    d = dict(start=1.0, dur=2.0, shot_type="medium", people=1, motion=0.4, shake=0.01)
    d.update(kw)
    return FootageWindow(**d)


def test_window_roundtrips():
    w = _win(description="1 person, medium, dynamic", score=0.7, best=True)
    assert FootageWindow(**w.to_dict()).to_dict() == w.to_dict()


@pytest.mark.parametrize("kw,msg", [
    (dict(start=-1), "start"), (dict(dur=0), "dur"), (dict(shot_type=""), "shot_type"),
    (dict(people=-1), "people"), (dict(people=True), "people"),
    (dict(motion=1.5), "motion"), (dict(shake=-0.1), "shake"), (dict(score=2.0), "score"),
])
def test_window_rejects_bad(kw, msg):
    with pytest.raises(ValueError, match=msg):
        _win(**kw)


def test_clip_roundtrips_and_wraps_windows():
    c = FootageClip(source="a.mp4", dur=22.0, res=(1920, 1080), fps=59.94,
                    shaky=False, scene_cuts=[3.0], windows=[_win()])
    back = FootageClip.from_dict(c.to_dict())
    assert back.to_dict() == c.to_dict()
    assert isinstance(back.windows[0], FootageWindow)


def test_clip_from_dict_names_bad_window():
    with pytest.raises(ValueError, match=r"windows\[0\]"):
        FootageClip.from_dict(dict(source="a.mp4", dur=1.0, res=[10, 10], fps=30,
                                   windows=[dict(start=1.0, dur=2.0, shot_type="x", people=1,
                                                 motion=0.4, shake=0.0, bogus=1)]))


def test_clip_rejects_bad_res():
    with pytest.raises(ValueError, match="res"):
        FootageClip(source="a.mp4", dur=1.0, res=(0, 10), fps=30)


def _footage():
    return Footage(clips=[FootageClip(source="a.mp4", dur=22.0, res=(1920, 1080), fps=30,
                                      scene_cuts=[3.0],
                                      windows=[_win(score=0.8, best=True),
                                               _win(start=5.0, score=0.3)])])


def test_footage_roundtrips():
    f = _footage()
    assert Footage.from_dict(f.to_dict()).to_dict() == f.to_dict()


def test_footage_from_json_bad_syntax(tmp_path):
    p = tmp_path / "FOOTAGE.json"; p.write_text("{ not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        Footage.from_json(p)


def test_ranked_windows_is_score_descending():
    f = _footage()
    ranked = f.ranked_windows()
    assert [w.score for _, w in ranked] == [0.8, 0.3]


def test_to_markdown_renders_header_and_star():
    md = _footage().to_markdown()
    assert "# Footage — 1 clips, 2 windows (1 best)" in md
    assert "## a.mp4" in md and "★" in md
    assert "| start | dur | shot | people | motion | shake | score | best | description |" in md
