"""Real-OSNet weights-gated proof (design 2026-08-04 §10, Task 5).

Everything else in the reid slice runs against a FAKE embedder (test_cast_pin,
test_track, test_process_episode) because torchreid is a heavy optional dep not
installed on CI — mirrors the vidstab/demucs pattern (test_stabilize.py,
test_offset.py). This is the one test that proves the real thing: genuine OSNet
weights, loaded through the same `reid.embed` boundary every consumer calls,
actually separate two visually different people and agree with themselves.
Skips (does not fail) when torchreid is absent — do not install it to pass this.

The skip gate is `reid.available()`, the SAME probe the production path uses, not a
`find_spec` check. It was the latter until 2026-08-14, when a real install exposed the
difference: torchreid 0.2.5 under-declares `gdown`, so pip installs it, `find_spec`
finds it, and importing it raises. The gate said present, `reid.require()` said absent,
and this test failed instead of skipping — a test skip must never rest on a weaker
question than the code it guards.
"""
import numpy as np
import pytest

from scripts.lib import appearance, reid

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not reid.available(), reason="needs torchreid (bash setup.sh)")
def test_osnet_embeds_are_512d_l2normed_and_separate_two_people():
    # two visually different synthetic "people": a bright vertical bar vs a dark blob.
    a = np.zeros((256, 128, 3), np.uint8); a[:, 50:78] = (230, 200, 180)
    b = np.zeros((256, 128, 3), np.uint8); b[80:180, 40:90] = (40, 40, 60)
    ea, eb = reid.embed([a, b])
    assert len(ea) == 512 and abs(sum(v * v for v in ea) - 1.0) < 1e-4
    # same crop twice ≈ identical; different crops measurably farther apart
    same = reid.embed([a, a])
    assert appearance.descriptor_dist(same[0], same[1]) < 1e-4
    assert appearance.descriptor_dist(ea, eb) > appearance.descriptor_dist(same[0], same[1])
