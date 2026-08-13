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


@pytest.mark.parametrize("v", [-0.1, 0.61, True, "0.3"])
def test_vignette_refuses_out_of_band(v):
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
