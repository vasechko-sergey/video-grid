from scripts import process_episode
from scripts.lib import orchestration as orch
from scripts.lib.manifest import Manifest
from scripts.lib.models import Delivery


def test_build_reframe_spec_carries_every_colour_field():
    """The probe renders from this map. A field that falls out here is a field the
    probe shows unchanged while the real render changes it."""
    m = Manifest.from_dict({
        "segment": "s.mp4", "out_path": "o.mp4", "target_dur": 2.0,
        "composition": "lead", "grid": "thirds", "canvas": [9, 16],
        "color_means": [110.0, 120.0, 130.0], "delivery": "short_edge:540",
        "white_balance": 0.4, "black_point": 0.1, "highlight": 0.8,
        "highlight_red": 0.2, "saturation": 1.2, "shadow_red": 0.05,
        "mid_blue": 0.95, "dip": 0.3,
        "tone_src": [18.0, 110.0, 220.0], "tone_dst": [26.0, 118.0, 210.0]})
    spec = process_episode.build_reframe_spec(
        m, Delivery.from_spec(m.delivery), dict(orch.DEFAULT_PARAMS))
    assert (spec.white_balance, spec.black_point, spec.highlight, spec.highlight_red,
            spec.saturation, spec.shadow_red, spec.mid_blue, spec.dip) == (
        0.4, 0.1, 0.8, 0.2, 1.2, 0.05, 0.95, 0.3)
    assert spec.tone_src == (18.0, 110.0, 220.0)
    assert spec.tone_dst == (26.0, 118.0, 210.0)
    assert spec.color_correct is None
