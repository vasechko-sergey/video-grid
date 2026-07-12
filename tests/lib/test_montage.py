import json
import sys

import pytest

from scripts import montage
from scripts.montage import Stage, V1_STAGES, next_action


def _touch(d, name):
    (d / name).write_text("{}")


# ---- Stage config-spec ----

def test_stage_rejects_bad_kind():
    with pytest.raises(ValueError, match="kind"):
        Stage("x", "x.json", "bogus", "runs it", None)


def test_stage_rejects_bad_checkpoint():
    with pytest.raises(ValueError, match="checkpoint"):
        Stage("x", "x.json", "required", "runs it", "bogus")


def test_stage_accepts_good():
    s = Stage("x", "x.json", "required", "runs it", "spec")
    assert s.kind == "required" and s.checkpoint == "spec" and s.in_out is False


# ---- V1_STAGES table ----

def test_v1_stages_order_and_keys():
    assert [s.key for s in V1_STAGES] == [
        "project-init", "footage-intake", "reel-brief", "trend-scan",
        "music-and-mood", "pacing", "edit-plan", "deliver"]


def test_v1_stages_kinds_and_flags():
    by = {s.key: s for s in V1_STAGES}
    assert [s.key for s in V1_STAGES if s.kind == "deferred"] == [
        "reel-brief", "trend-scan", "pacing"]
    assert by["music-and-mood"].kind == "optional"
    assert by["deliver"].in_out is True and by["deliver"].artifact == "REEL_v*.*"
    assert by["project-init"].checkpoint == "spec"
    assert by["edit-plan"].checkpoint == "edl"
    assert by["deliver"].checkpoint == "final"
