"""Real-ffmpeg proof for §5.13 safe_zones: a low-framed subject is flagged (advisory)
on a genuinely assembled master, and the reel still passes overall (deliver's gate is
overall, which advisory checks never drop). Mirrors tests/integration/test_ambient.py."""
import json
from pathlib import Path

import pytest

from scripts import check_reel
from scripts.lib import assembly, ffbin, proc
from scripts.lib.models import ReelCheckSpec


def _solid(path, color, secs):
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i", f"color=c={color}:s=320x568:d={secs}:r=30",
              "-pix_fmt", "yuv420p", str(path)])
    return str(path)


def _write_geom(dir_path, y):
    """route/path/path.meta sidecars: fill 1000x2000, subject centre x=500 (crop-x 0),
    vertical y in source px. Returns the (route, path, meta) path triple."""
    d = Path(dir_path)
    d.mkdir(parents=True, exist_ok=True)
    (d / "route.json").write_text(json.dumps(
        [{"t": 0.0, "x": 500.0, "y": y, "w": 100.0, "h": 200.0},
         {"t": 1.0, "x": 500.0, "y": y, "w": 100.0, "h": 200.0}]))
    (d / "path.json").write_text(json.dumps([0, 0]))
    (d / "path.meta.json").write_text(json.dumps(
        {"mode": "fill", "crop_w": 1000, "crop_h": 2000, "crop_y": 0, "src_dims": [1000, 2000],
         "canvas": [1000, 2000], "out_dims": [1000, 2000], "rect_px": [0, 0, 1000, 2000], "freedom": 0}))
    return (str(d / "route.json"), str(d / "path.json"), str(d / "path.meta.json"))


@pytest.mark.integration
def test_safe_zones_flags_low_subject_without_blocking_delivery(tmp_path):
    try:
        ffbin.ffmpeg()
    except ValueError as e:
        pytest.skip(str(e))
    clips = [_solid(tmp_path / "c0.mp4", "red", 1.0), _solid(tmp_path / "c1.mp4", "blue", 1.0)]
    master = str(tmp_path / "master.mp4")
    assembly.assemble(clips, (320, 568), 30.0, master)               # a genuinely assembled master
    geom = [_write_geom(tmp_path / "ep0", 900.0),                    # fy 0.45 — safe
            _write_geom(tmp_path / "ep1", 1960.0)]                   # fy 0.98 — under the caption band
    # a flat-color fixture trips one HARD gate that is irrelevant to this test: phash
    # of any solid color collapses to the same hash (no texture to key on), so variety's
    # distance is always 0. Loosen just that one so only safe_zones — this test's
    # actual subject — can fail (mirrors test_reel_backhalf.py's variety_min override).
    # The reel-level colour ceiling this comment used to also loosen (`color_delta_max`,
    # default 12.0) is retired — there is no check left to raise it against (design
    # 2026-08-29, colour-convergence-retire).
    spec = ReelCheckSpec(target_dur=2.0, variety_min=0)
    rep = check_reel.run(master, clips, spec,
                         str(tmp_path / "r.json"), geometry=geom, platform="tiktok")
    assert rep.checks["safe_zones"].passed is False                 # ep1 subject under UI chrome
    assert rep.checks["safe_zones"].detail["worst_episode"] == 1
    assert rep.overall is True                                      # advisory → deliver's gate still opens
