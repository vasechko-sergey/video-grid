import pytest

from scripts.lib import lint
from scripts.lib.look import (FLASH_ALPHA, FLASH_FRAMES, LOOK_FADE_MAX, LOOK_VIGNETTE_MAX,
                              LookSpec, chain, clear_of_flash, fade_args, flash_args,
                              flash_free, flash_windows, mask_expr)


def test_default_is_no_look():
    s = LookSpec()
    assert s == LookSpec(vignette=0.0, fade=0.0)
    assert s.has_vignette is False


def test_has_vignette_is_the_second_input_predicate():
    assert LookSpec(vignette=0.35).has_vignette is True
    assert LookSpec(fade=0.5).has_vignette is False


def test_round_trip():
    s = LookSpec(vignette=0.3, fade=0.8)
    assert LookSpec.from_dict(s.to_dict()) == s
    assert s.to_dict() == {"vignette": 0.3, "fade": 0.8}


def test_from_dict_rejects_a_non_object():
    with pytest.raises(ValueError, match="look must be an object"):
        LookSpec.from_dict([0.3, 0.8])


@pytest.mark.parametrize("v", [-0.1, 0.61, True, False, "0.3"])
def test_vignette_refuses_out_of_band(v):
    # False is the discriminating bool case here: False == 0, which IS inside
    # [0, 0.6], so only the bool exclusion rejects it. True == 1 is outside the band
    # and would be refused by the range check alone.
    with pytest.raises(ValueError, match="vignette"):
        LookSpec(vignette=v)


@pytest.mark.parametrize("f", [-0.1, 2.1, True, "0.5"])
def test_fade_refuses_out_of_band(f):
    with pytest.raises(ValueError, match="fade"):
        LookSpec(fade=f)


def test_mask_expr_carries_the_measured_plateau_and_the_strength():
    e = mask_expr(0.35)
    assert e.startswith("format=rgba,geq=r=0:g=0:b=0:a='")
    assert "-0.5500" in e          # VIGNETTE_PLATEAU, the identity radius
    assert "/0.4500" in e          # VIGNETTE_FALLOFF, the rest of the ramp
    assert "255*0.3500*" in e      # the corner alpha cap
    assert e.endswith("'")


def test_mask_expr_refuses_zero_because_the_caller_must_skip_it():
    with pytest.raises(ValueError, match="mask_expr"):
        mask_expr(0.0)


def test_mask_expr_refuses_past_the_ceiling():
    with pytest.raises(ValueError, match=str(LOOK_VIGNETTE_MAX)):
        mask_expr(0.7)


def test_fade_args_are_a_bookend_pair():
    assert fade_args(0.5, 30.0) == ["fade=t=in:st=0:d=0.500",
                                    "fade=t=out:st=29.500:d=0.500"]


def test_fade_args_off_at_zero():
    assert fade_args(0.0, 30.0) == []


def test_fade_args_refuse_overlapping_fades():
    with pytest.raises(ValueError, match="would overlap"):
        fade_args(0.8, 1.5)


def test_fade_args_refuses_a_bool_rather_than_reading_it_as_zero():
    # False == 0, so a zero-shortcut placed before the type guard would return []
    with pytest.raises(ValueError, match="fade_args"):
        fade_args(False, 30.0)


def test_fade_args_re_checks_the_ceiling_on_its_own():
    # public function: a direct caller does not pass through LookSpec's validation
    with pytest.raises(ValueError, match=str(LOOK_FADE_MAX)):
        fade_args(3.0, 100.0)


def test_chain_puts_the_fade_after_the_titles():
    # design §4: measured — fade last is what takes the TITLE to black with the
    # picture. Reversing these two lines is a real defect, not a style choice.
    assert chain(LookSpec(fade=0.5), 30.0, "drawtext=x=1") == [
        "drawtext=x=1", "fade=t=in:st=0:d=0.500", "fade=t=out:st=29.500:d=0.500"]


def test_chain_is_empty_with_no_look_and_no_titles():
    assert chain(None, 30.0) == []
    assert chain(LookSpec(), 30.0) == []


def test_chain_carries_titles_alone_when_the_look_is_absent():
    assert chain(None, 30.0, "drawtext=x=1") == ["drawtext=x=1"]


def test_chain_does_not_carry_the_overlay():
    # the vignette needs a SECOND INPUT, so deliver wires it by label; a chain
    # that emitted `overlay` would produce a graph with a dangling input
    assert "overlay" not in ",".join(chain(LookSpec(vignette=0.4, fade=0.5), 30.0))


def test_fade_ceiling_is_two_seconds():
    assert LOOK_FADE_MAX == 2.0


# --- the head fade is its own number (retro 2026-10-16 S6) ---------------------------
# The second real run's hook opened on a black frame: one `fade` served the picture's
# head, its tail and the audio, and all four reviews flagged it.

def test_the_head_fade_defaults_to_the_tail_and_can_be_set_apart():
    assert (LookSpec(fade=0.8).head, LookSpec(fade=0.8).tail) == (0.8, 0.8)
    s = LookSpec(fade=0.8, fade_in=0.0)
    assert (s.head, s.tail) == (0.0, 0.8)
    assert s.has_fade and LookSpec(fade_in=0.4).has_fade and not LookSpec().has_fade


def test_fade_in_rides_the_dict_only_when_authored():
    # an EDL.json written before the field must round-trip byte-identically
    assert LookSpec(vignette=0.25, fade=0.8).to_dict() == {"vignette": 0.25, "fade": 0.8}
    assert LookSpec(fade=0.8, fade_in=0.0).to_dict() == {"vignette": 0.0, "fade": 0.8,
                                                         "fade_in": 0.0}
    assert LookSpec.from_dict({"fade": 0.8, "fade_in": 0.2}) == LookSpec(fade=0.8, fade_in=0.2)
    assert LookSpec.from_dict({"fade": 0.8}).fade_in is None


@pytest.mark.parametrize("f", [-0.1, True, LOOK_FADE_MAX + 0.1, "0.3", float("nan")])
def test_fade_in_refuses_out_of_band(f):
    with pytest.raises(ValueError, match="fade_in"):
        LookSpec(fade_in=f)


def test_a_head_of_zero_emits_only_the_fade_out():
    assert chain(LookSpec(fade=0.8, fade_in=0.0), 10.0) == ["fade=t=out:st=9.200:d=0.800"]


def test_a_tail_of_zero_emits_only_the_fade_in():
    assert chain(LookSpec(fade=0.0, fade_in=0.5), 10.0) == ["fade=t=in:st=0:d=0.500"]


def test_a_head_and_tail_that_meet_are_refused():
    with pytest.raises(ValueError, match="overlap"):
        fade_args(0.8, 1.0, fade_in=0.4)


def test_a_long_close_fits_a_reel_that_opens_on_picture():
    # the old rule (2 * fade > dur) refused this; only the ends that render count
    assert fade_args(0.8, 1.2, fade_in=0.0) == ["fade=t=out:st=0.400:d=0.800"]


# --- the shutter accent's flash (design 2026-10-21 §4) ---------------------------------

def test_the_flash_is_three_frames_white_at_the_conventions_opacities():
    assert FLASH_ALPHA == (0.85, 0.5, 0.2) and FLASH_FRAMES == 3


def test_flash_args_writes_one_full_frame_white_box_per_frame_of_each_flash():
    """Each frame's window is centred on the frame's own instant, half a frame either
    side, so a cut time a hair off the frame grid still enables that frame and only
    it. The first window of a flash at 0 starts at 0, not at a negative time."""
    box = "drawbox=x=0:y=0:w=iw:h=ih:color=white@{a}:t=fill:enable='between(t,{lo},{hi})'"
    assert flash_args([0.0, 2.0], 25.0) == [
        box.format(a="0.85", lo="0.000000", hi="0.020000"),
        box.format(a="0.5", lo="0.020000", hi="0.060000"),
        box.format(a="0.2", lo="0.060000", hi="0.100000"),
        box.format(a="0.85", lo="1.980000", hi="2.020000"),
        box.format(a="0.5", lo="2.020000", hi="2.060000"),
        box.format(a="0.2", lo="2.060000", hi="2.100000")]


def test_flash_args_is_empty_with_no_flash():
    assert flash_args([], 30.0) == []
    assert flash_args((), 0.0) == []        # nothing to place, so no rate is needed


def test_a_flash_passes_the_landmine_guard_because_its_commas_are_quoted():
    """CLAUDE.md: a bare comma inside a filter value splits the chain. The between()
    carries two, so the enable value is single-quoted inside the -vf string."""
    vf = ",".join(flash_args([1.0, 3.5], 30.0))
    assert lint.check_argv(["ffmpeg", "-i", "m.mp4", "-vf", vf, "out.mp4"]) == []
    assert vf.count("'") == 2 * 2 * FLASH_FRAMES


@pytest.mark.parametrize("times, fps, what", [
    ([1.0], 0.0, "fps"), ([1.0], -30.0, "fps"), ([1.0], True, "fps"),
    ([1.0], float("nan"), "fps"), ([-0.1], 30.0, "time"), ([True], 30.0, "time"),
    (["1.0"], 30.0, "time"), ([float("inf")], 30.0, "time")])
def test_flash_args_refuses_a_rate_or_time_it_cannot_place(times, fps, what):
    with pytest.raises(ValueError, match=what):
        flash_args(times, fps)
    with pytest.raises(ValueError, match=what):
        flash_windows(times, fps)


def test_the_flash_rides_first_then_the_titles_then_the_fade():
    """The fade last is what still darkens a flash at t=0 — and the titles above the
    flash, so a title over a photo cut stays legible through the white."""
    flashes = flash_args([1.0], 30.0)
    assert chain(LookSpec(fade=0.5), 30.0, "drawtext=x=1", flashes=flashes) == [
        *flashes, "drawtext=x=1", "fade=t=in:st=0:d=0.500", "fade=t=out:st=29.500:d=0.500"]
    assert chain(None, 30.0, flashes=flashes) == flashes


def test_a_chain_with_no_flash_is_the_chain_it_was():
    for spec, titles in ((None, ""), (LookSpec(fade=0.5), "drawtext=x=1"),
                         (LookSpec(vignette=0.3), "")):
        assert chain(spec, 30.0, titles, flashes=()) == chain(spec, 30.0, titles)


def test_a_flash_window_is_a_frame_before_it_to_a_frame_after_its_last():
    w = flash_windows([1.0, 2.0], 25.0)
    assert [x for pair in w for x in pair] == pytest.approx([0.96, 1.16, 1.96, 2.16])
    assert flash_windows([], 0.0) == []


def test_clear_of_flash_leaves_a_clear_time_alone_and_moves_one_in_a_window_to_its_end():
    w = flash_windows([1.0], 25.0)                       # [0.96, 1.16)
    lo, hi = w[0]
    assert clear_of_flash(0.5, w) == 0.5
    assert clear_of_flash(0.959, w) == 0.959             # just before: clear
    assert clear_of_flash(lo, w) == hi                   # the window's start is inside it
    assert clear_of_flash(1.0, w) == hi
    assert clear_of_flash(hi, w) == hi                   # its end is the first clear instant
    assert clear_of_flash(2.0, []) == 2.0


def test_clear_of_flash_walks_through_windows_that_overlap():
    """A window's end can sit inside another flash's window (two accented cuts a few
    frames apart): one step would land the sample on the second flash. In either order
    of the windows — one pass in time order would get there, deliver's caller is not
    obliged to hand them sorted."""
    for times in ([1.0, 1.12], [1.12, 1.0]):             # [0.96, 1.16), [1.08, 1.28)
        assert clear_of_flash(1.0, flash_windows(times, 25.0)) == pytest.approx(1.28)


def test_flash_free_is_every_part_of_a_span_outside_the_windows():
    w = flash_windows([1.0, 3.0], 25.0)                  # [0.96, 1.16), [2.96, 3.16)
    free = flash_free(0.0, 4.0, w)
    assert [x for part in free for x in part] == pytest.approx(
        [0.0, 0.96, 1.16, 2.96, 3.16, 4.0])
    assert flash_free(1.0, 1.1, w) == []                 # the whole span is one flash
    assert flash_free(0.5, 0.9, w) == [(0.5, 0.9)]       # no flash touches it
    assert flash_free(0.0, 4.0, []) == [(0.0, 4.0)]
