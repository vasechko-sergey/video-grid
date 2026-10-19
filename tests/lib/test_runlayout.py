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


def test_the_layout_places_every_bucket(tmp_path):
    lay = runlayout.RunLayout(tmp_path / "montage", "main")
    assert lay.to_dict() == {
        "run": str(tmp_path / "montage"),
        "footage": str(tmp_path / "montage" / "footage"),
        "music": str(tmp_path / "montage" / "music"),
        "reel": str(tmp_path / "montage" / "reels" / "main"),
        "episodes": str(tmp_path / "montage" / "reels" / "main" / "episodes"),
        "deliveries": str(tmp_path / "montage" / "reels" / "main" / "deliveries"),
        "build": str(tmp_path / "montage" / "reels" / "main" / "build"),
    }


def test_the_default_reel_is_main(tmp_path):
    assert runlayout.RunLayout(tmp_path).reel == "main"
    assert runlayout.DEFAULT_REEL == "main"


def test_a_variant_only_moves_the_reel_buckets(tmp_path):
    a = runlayout.RunLayout(tmp_path, "main")
    b = runlayout.RunLayout(tmp_path, "upbeat")
    assert a.footage == b.footage and a.music == b.music and a.project == b.project
    assert a.reel_dir != b.reel_dir and a.deliveries != b.deliveries


def test_for_footage_hangs_the_run_off_the_footage_root(tmp_path):
    lay = runlayout.RunLayout.for_footage(str(tmp_path), "main")
    assert lay.root == tmp_path.resolve() / "montage"


def test_project_json_sits_at_the_run_root(tmp_path):
    """CONSTRAINTS.json is found beside project.json by edit_plan — a code fact.
    Moving project.json into a bucket would silently move the rules with it."""
    assert runlayout.RunLayout(tmp_path).project == tmp_path / "project.json"


@pytest.mark.parametrize("bad", ["", "a/b", "a\\b", ".", "..", "  "])
def test_a_reel_name_that_is_not_one_path_segment_is_refused(tmp_path, bad):
    with pytest.raises(ValueError) as e:
        runlayout.RunLayout(tmp_path, bad)
    assert "reel name" in str(e.value)


def test_an_unknown_bucket_is_refused(tmp_path):
    with pytest.raises(ValueError) as e:
        runlayout.RunLayout(tmp_path).bucket("scratch")
    assert "scratch" in str(e.value)


def test_reel_names_lists_the_variants(tmp_path):
    for n in ("upbeat", "main"):
        (tmp_path / "reels" / n).mkdir(parents=True)
    (tmp_path / "reels" / "notes.txt").write_text("x")
    assert runlayout.reel_names(tmp_path) == ["main", "upbeat"]


def test_reel_names_is_empty_before_any_reel_exists(tmp_path):
    assert runlayout.reel_names(tmp_path) == []


def test_a_legacy_run_is_recognised_by_footage_json_at_the_root(tmp_path):
    (tmp_path / "FOOTAGE.json").write_text("{}")
    assert runlayout.is_legacy_run(tmp_path) is True


def test_a_current_run_is_not_legacy(tmp_path):
    (tmp_path / "footage").mkdir()
    (tmp_path / "footage" / "FOOTAGE.json").write_text("{}")
    assert runlayout.is_legacy_run(tmp_path) is False


def test_an_empty_run_is_not_legacy(tmp_path):
    assert runlayout.is_legacy_run(tmp_path) is False


def test_a_root_with_both_legacy_file_and_footage_dir_is_not_legacy(tmp_path):
    """Discriminates: without it, a mutant dropping the `not (r / "footage").is_dir()` clause passes all tests."""
    (tmp_path / "FOOTAGE.json").write_text("{}")
    (tmp_path / "footage").mkdir()
    assert runlayout.is_legacy_run(tmp_path) is False


def test_deliveries_is_the_sibling_of_episodes(tmp_path):
    eps = tmp_path / "reels" / "main" / "episodes"
    assert runlayout.deliveries_for(str(eps)) == (tmp_path / "reels" / "main"
                                                  / "deliveries").resolve()


def test_the_build_wipe_fires_on_the_canonical_pair(tmp_path):
    reel = tmp_path / "reels" / "main"
    build, eps = reel / "build", reel / "episodes"
    (build / "segments").mkdir(parents=True)
    (build / "segments" / "ep0_raw.mp4").write_text("x")
    eps.mkdir(parents=True)
    assert runlayout.wipe_build(str(build), str(eps)) == ["segments"]
    assert build.is_dir() and list(build.iterdir()) == []


def test_the_build_wipe_does_not_fire_on_a_hand_driven_scratch(tmp_path):
    """SP1's front door: edl_to_reel with a hand-authored EDL and --work-dir
    anywhere. Returning None (not []) is what lets the caller say WHY nothing
    was wiped."""
    scratch = tmp_path / "build"          # named build, but not the sibling
    scratch.mkdir()
    (scratch / "keep.txt").write_text("x")
    eps = tmp_path / "elsewhere" / "episodes"
    eps.mkdir(parents=True)
    assert runlayout.wipe_build(str(scratch), str(eps)) is None
    assert (scratch / "keep.txt").exists()


def test_the_build_wipe_on_a_canonical_pair_that_does_not_exist_yet(tmp_path):
    reel = tmp_path / "reels" / "main"
    eps = reel / "episodes"
    eps.mkdir(parents=True)
    assert runlayout.wipe_build(str(reel / "build"), str(eps)) == []


def test_the_build_wipe_matches_through_a_symlinked_spelling(tmp_path):
    reel = tmp_path / "reels" / "main"
    (reel / "build").mkdir(parents=True)
    (reel / "episodes").mkdir()
    link = tmp_path / "link"
    link.symlink_to(reel / "build")
    assert runlayout.wipe_build(str(link), str(reel / "episodes")) == []


def test_the_partial_ends_in_the_container_so_ffmpeg_can_pick_a_muxer(tmp_path):
    assert runlayout.partial_path(str(tmp_path), 3, "mp4").name.endswith(".mp4")
    assert runlayout.partial_path(str(tmp_path), 3, "mov").name == ".REEL_v3.part.mov"


def test_a_partial_is_invisible_to_every_delivery_glob(tmp_path):
    (tmp_path / "REEL_v1.mp4").write_text("x")
    (tmp_path / ".REEL_v2.part.mp4").write_text("half")
    assert sorted(p.name for p in tmp_path.glob("REEL_v*")) == ["REEL_v1.mp4"]
    assert sorted(p.name for p in tmp_path.glob("REEL_v*.*")) == ["REEL_v1.mp4"]
    assert sorted(p.name for p in tmp_path.glob(runlayout.PARTIAL_GLOB)) == [".REEL_v2.part.mp4"]


# --- retro 2026-10-16 S10: project.json does not belong in the footage folder ---------

def test_a_project_dir_that_holds_footage_is_refused_with_the_run_dir_as_remedy(tmp_path):
    (tmp_path / "DJI_0001_D.MP4").write_bytes(b"x")
    with pytest.raises(ValueError, match="montage"):
        runlayout.refuse_project_dir_holding_footage(str(tmp_path), "project-init")


def test_the_run_dir_and_a_new_dir_pass(tmp_path):
    (tmp_path / "DJI_0001_D.MP4").write_bytes(b"x")
    runlayout.refuse_project_dir_holding_footage(str(tmp_path / "montage"), "project-init")
    (tmp_path / "montage").mkdir()
    (tmp_path / "montage" / "reels" / "main").mkdir(parents=True)
    (tmp_path / "montage" / "reels" / "main" / "draft.mp4").write_bytes(b"x")   # deeper: fine
    runlayout.refuse_project_dir_holding_footage(str(tmp_path / "montage"), "project-init")


def test_intake_and_the_refusal_share_one_extension_list():
    from scripts import intake
    assert intake._VIDEO_EXTS is runlayout.VIDEO_EXTS
