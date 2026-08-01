import pytest

from scripts.lib import preflight
from scripts.lib.preflight import CHECKS, Check, CheckResult, Report


def _all_ok_raw():
    return {c.key: (True, "ok") for c in CHECKS}


def test_registry_keys_unique_and_expected_split():
    keys = [c.key for c in CHECKS]
    assert len(keys) == len(set(keys))
    assert [c.key for c in CHECKS if c.required] == [
        "deps", "ffmpeg", "drawtext", "vidstab", "font", "weights"]
    assert [c.key for c in CHECKS if not c.required] == ["demucs"]


def test_report_partition():
    results = tuple(
        CheckResult(key=c.key, label=c.label, required=c.required,
                    ok=(c.key not in ("drawtext", "demucs")),
                    detail="", remedy=c.remedy)
        for c in CHECKS)
    r = Report(results=results)
    assert r.ok is False                                  # a required miss (drawtext)
    assert [f.key for f in r.failures] == ["drawtext"]
    assert [a.key for a in r.advisories] == ["demucs"]


def test_report_ok_when_only_advisory_fails():
    results = tuple(
        CheckResult(key=c.key, label=c.label, required=c.required,
                    ok=(c.key != "demucs"), detail="", remedy=c.remedy)
        for c in CHECKS)
    assert Report(results=results).ok is True             # advisory never blocks
