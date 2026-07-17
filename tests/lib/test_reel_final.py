from scripts.lib import reel_final


def test_key_action_passes_when_every_corner_is_inside():
    # two episodes, all corners within [0,1]
    extents = [[(0.1, 0.1, 0.3, 0.4)], [(0.4, 0.2, 0.6, 0.5)]]
    passed, detail = reel_final.evaluate_key_action(extents, clip_tol=0.02)
    assert passed is True and detail["advisory"] is True and detail["episodes"] == 2


def test_key_action_flags_the_worst_overshoot_with_edge_and_episode():
    # ep1 pokes 0.05 past the right edge (fx1 = 1.05) — beyond clip_tol 0.02
    extents = [[(0.1, 0.1, 0.3, 0.4)], [(0.9, 0.2, 1.05, 0.5)]]
    passed, detail = reel_final.evaluate_key_action(extents, clip_tol=0.02)
    assert passed is False
    assert detail["worst_episode"] == 1 and detail["edge"] == "right"
    assert detail["overshoot"] == 0.05 and detail["advisory"] is True


def test_key_action_tolerates_a_corner_just_touching_the_edge():
    # fx1 = 1.015 → overshoot 0.015 < clip_tol 0.02 → still safe
    extents = [[(0.0, 0.0, 1.015, 0.5)]]
    passed, _ = reel_final.evaluate_key_action(extents, clip_tol=0.02)
    assert passed is True


from scripts.lib.models import PathMeta


def _meta(mode="fill", rect_px=(0, 0, 1000, 2000), out=(1000, 2000)):
    return PathMeta(mode, 1000, 2000, 0, (1000, 2000), out, out, rect_px, 0)


def test_pad_bars_na_when_every_episode_is_fill():
    passed, detail = reel_final.evaluate_pad_bars([_meta("fill"), _meta("fill")], bar_symmetry_tol=0.02)
    assert passed is None and detail["status"] == "n/a" and detail["advisory"] is True


def test_pad_bars_passes_a_symmetric_letterbox():
    # fit-blur: 1000-wide content in a 1000x2000 frame, centred vertically (500px bars top+bottom)
    passed, detail = reel_final.evaluate_pad_bars([_meta("fit-blur", (0, 500, 1000, 1000))],
                                                  bar_symmetry_tol=0.02)
    assert passed is True and detail["bars"] == 1 and detail["advisory"] is True


def test_pad_bars_flags_a_rect_that_pokes_outside_the_frame():
    passed, detail = reel_final.evaluate_pad_bars([_meta("fit-blur", (0, 500, 1000, 1600))],
                                                  bar_symmetry_tol=0.02)
    assert passed is False and detail["issue"] == "rect_overflow" and detail["worst_episode"] == 0


def test_pad_bars_flags_asymmetric_bars():
    # top bar 300, bottom bar 700 → |300-700|/2000 = 0.2 > tol
    passed, detail = reel_final.evaluate_pad_bars([_meta("fit-blur", (0, 300, 1000, 1000))],
                                                  bar_symmetry_tol=0.02)
    assert passed is False and detail["issue"] == "asymmetric" and detail["worst_episode"] == 0


def test_transitions_na_for_a_single_episode():
    passed, detail = reel_final.evaluate_transitions([_meta("fill")], layout_jump_max=0.6)
    assert passed is None and detail["status"] == "n/a" and detail["advisory"] is True


def test_transitions_passes_two_identical_layouts():
    passed, detail = reel_final.evaluate_transitions([_meta("fill"), _meta("fill")], layout_jump_max=0.6)
    assert passed is True and detail["cuts"] == 1 and detail["advisory"] is True


def test_transitions_flags_a_fill_to_insert_jump():
    # fill (area 1.0, centre 0.5,0.5) → insert card (area 0.09, centre 0.25,0.25)
    metas = [_meta("fill"), _meta("insert", (0, 0, 300, 600))]
    passed, detail = reel_final.evaluate_transitions(metas, layout_jump_max=0.6)
    assert passed is False and detail["worst_cut"] == 0 and detail["modes"] == ["fill", "insert"]
    assert detail["advisory"] is True
