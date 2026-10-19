import pytest

from scripts.lib.look import (LOOK_FADE_MAX, LOOK_VIGNETTE_MAX, LookSpec, chain,
                              fade_args, mask_expr)


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
