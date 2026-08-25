import pytest

from scripts.lib import runlayout


def test_the_run_dirname_is_montage():
    """Pinned because three places must agree on it: the refusal's remedy text,
    the using-montage skill, and the README. A rename is a deliberate act."""
    assert runlayout.RUN_DIRNAME == "montage"


def test_writing_into_the_footage_root_itself_is_refused(tmp_path):
    with pytest.raises(ValueError) as e:
        runlayout.refuse_output_in_footage(str(tmp_path), str(tmp_path), "the out dir")
    assert "the out dir" in str(e.value)


def test_the_refusal_names_the_remedy_path(tmp_path):
    with pytest.raises(ValueError) as e:
        runlayout.refuse_output_in_footage(str(tmp_path), str(tmp_path), "the out dir")
    assert str(tmp_path / "montage") in str(e.value)


def test_the_convention_itself_passes(tmp_path):
    """<footage>/montage is INSIDE the footage root. A containment check instead of
    equality would forbid the very layout this gate exists to protect."""
    runlayout.refuse_output_in_footage(str(tmp_path), str(tmp_path / "montage"), "x")


def test_a_deeper_path_under_the_footage_root_passes(tmp_path):
    runlayout.refuse_output_in_footage(str(tmp_path), str(tmp_path / "montage" / "out"), "x")


def test_a_sibling_directory_passes(tmp_path):
    runlayout.refuse_output_in_footage(str(tmp_path / "a"), str(tmp_path / "b"), "x")


@pytest.mark.parametrize("spell", ["trailing_slash", "dot_dot", "symlink"])
def test_the_same_directory_spelled_differently_is_still_refused(tmp_path, spell):
    """Both ends resolve(), so no spelling of the footage root slips past."""
    root = tmp_path / "footage"
    root.mkdir()
    if spell == "trailing_slash":
        other = str(root) + "/"
    elif spell == "dot_dot":
        other = str(root / "sub" / "..")
    else:
        link = tmp_path / "link"
        link.symlink_to(root)
        other = str(link)
    with pytest.raises(ValueError):
        runlayout.refuse_output_in_footage(str(root), other, "x")
