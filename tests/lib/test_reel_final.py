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
