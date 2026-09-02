"""The fixture's own invariant: one geometry, not two that agree.

This is the whole point of design 2026-09-02 — a test that renders through the fake
cannot declare a canvas the fake does not honour, because the declaration and the
sidecar are two renderings of one `src_dims`. If someone reintroduces a literal on
either side, this test is what notices.
"""
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("dims", [(1920, 1080), (640, 360)])
def test_the_project_canvas_is_the_dims_the_fake_writes(dims, tmp_path, monkeypatch, fake_render):
    from scripts import edl_to_reel

    fake = fake_render(monkeypatch, src_dims=dims)
    project = json.loads(Path(fake.project(tmp_path)).read_text())

    epdir = tmp_path / "ep0"
    edl_to_reel.process_episode.process_episode(
        {"segment": "unused.mp4", "out_path": str(tmp_path / "ep0.mp4")}, str(epdir))
    meta = json.loads((epdir / "path.meta.json").read_text())

    assert project["canvas"] == list(dims)
    assert meta["canvas"] == project["canvas"] == meta["src_dims"]


def test_pan_aware_writes_no_route_for_a_pan_episode(tmp_path, monkeypatch, fake_render):
    from scripts import edl_to_reel

    fake = fake_render(monkeypatch, src_dims=(1920, 1080), pan_aware=True)
    fake.project(tmp_path)
    epdir = tmp_path / "ep0"
    edl_to_reel.process_episode.process_episode(
        {"segment": "unused.mp4", "out_path": str(tmp_path / "ep0.mp4"),
         "pan": {"from": 0.0, "to": 1.0}}, str(epdir))

    assert not (epdir / "route.json").exists()
    assert json.loads((epdir / "path.meta.json").read_text())["pan"] is True
