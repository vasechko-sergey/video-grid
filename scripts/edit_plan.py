"""Edit-plan authoring (design docs/specs/2026-07-12-edit-plan-spine-design.md, stage 5.7).

The 5.7 driver: an agent-authored selection.json (window references + editorial
fields) → a typed EDL.json + a human EDL.md map, which the existing edl_to_reel
(SP1) takes to a delivered reel. Selection lives in the agent's judgment; this
module is the thin mechanical half — projection + preflight + render. Contract
vs. logic split mirrors footage.py (contract) ↔ intake.py (logic).

The mechanical window fields (source/start/dur/shot_type/description) reach the
EDL BY REFERENCE through window_to_episode — never retyped by the agent, because
a retyped start/dur is the silent-wrong-cut class (montage §12). selection.json
carries only integer window indices + editorial enums/notes.
"""
import argparse
import json
from pathlib import Path

from scripts.lib.edl import EDL, EDLEpisode, preflight
from scripts.lib.footage import Footage, FootageClip, FootageWindow
from scripts.lib.project import ProjectConfig


def window_to_episode(clip: FootageClip, window: FootageWindow, **editorial: object) -> EDLEpisode:
    """Project a scored FootageWindow onto an EDLEpisode. Mechanical fields come
    from the clip/window by reference; editorial fields (composition/grid required;
    layout/motion/hero/crop_*/rect/background/border_*/color_means/beat_slot
    optional) are forwarded to EDLEpisode, whose __post_init__ is the single
    value-validation site. shot_type/processing_notes default to the window's
    shot_type/description but an editorial value overrides. An unknown or missing
    editorial field raises ValueError naming it."""
    defaults = {"shot_type": window.shot_type, "processing_notes": window.description}
    try:
        return EDLEpisode(source=clip.source, start=window.start, dur=window.dur,
                          **{**defaults, **editorial})
    except TypeError as ex:
        raise ValueError(f"window_to_episode: unknown or missing editorial field — {ex}") from ex
