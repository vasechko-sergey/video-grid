import pytest

from scripts.lib import preflight
from scripts.lib.preflight import CHECKS, CheckOutcome, RuntimeReport


def _all_ok_raw():
    return {c.key: (True, "ok") for c in CHECKS}


def test_registry_keys_unique_and_expected_split():
    keys = [c.key for c in CHECKS]
    assert len(keys) == len(set(keys))
    assert [c.key for c in CHECKS if c.required] == [
        "deps", "ffmpeg_bin", "drawtext", "vidstab", "font", "weights"]
    assert [c.key for c in CHECKS if not c.required] == ["demucs"]


def test_report_partition():
    results = tuple(
        CheckOutcome(key=c.key, label=c.label, required=c.required,
                     ok=(c.key not in ("drawtext", "demucs")),
                     detail="", remedy=c.remedy)
        for c in CHECKS)
    r = RuntimeReport(results=results)
    assert r.ok is False                                  # a required miss (drawtext)
    assert [f.key for f in r.failures] == ["drawtext"]
    assert [a.key for a in r.advisories] == ["demucs"]


def test_report_ok_when_only_advisory_fails():
    results = tuple(
        CheckOutcome(key=c.key, label=c.label, required=c.required,
                     ok=(c.key != "demucs"), detail="", remedy=c.remedy)
        for c in CHECKS)
    assert RuntimeReport(results=results).ok is True             # advisory never blocks


def test_to_dict_shape():
    results = tuple(
        CheckOutcome(key=c.key, label=c.label, required=c.required, ok=True,
                     detail="ok", remedy=c.remedy)
        for c in CHECKS)
    d = RuntimeReport(results=results).to_dict()
    assert d["ok"] is True
    assert d["results"][0] == {
        "key": "deps", "label": "Python runtime deps import", "required": True,
        "ok": True, "detail": "ok", "remedy": "bash setup.sh"}


def test_to_text_ready_header_when_ok():
    results = tuple(
        CheckOutcome(key=c.key, label=c.label, required=c.required, ok=True,
                     detail="ok", remedy=c.remedy)
        for c in CHECKS)
    text = RuntimeReport(results=results).to_text()
    assert text.startswith("runtime ready")
    assert "BLOCKED" not in text and "Optional" not in text


def test_to_text_lists_failures_and_advisories_with_remedies():
    results = tuple(
        CheckOutcome(key=c.key, label=c.label, required=c.required,
                     ok=(c.key not in ("font", "demucs")),
                     detail=("no system font" if c.key == "font" else
                             "not installed" if c.key == "demucs" else "ok"),
                     remedy=c.remedy)
        for c in CHECKS)
    text = RuntimeReport(results=results).to_text()
    assert "runtime NOT ready" in text
    assert "[FAIL] font" in text and "font: bash setup.sh" in text
    assert "[warn] demucs" in text and "demucs: bash setup.sh" in text


def test_evaluate_all_ok_is_ready():
    r = preflight.evaluate(_all_ok_raw())
    assert r.ok is True and r.failures == () and r.advisories == ()


def test_evaluate_joins_label_and_remedy_from_registry():
    raw = _all_ok_raw()
    raw["drawtext"] = (False, "absent from build")
    dt = next(x for x in preflight.evaluate(raw).results if x.key == "drawtext")
    assert dt == CheckOutcome(
        key="drawtext", label="ffmpeg drawtext filter (titles, draft labels)",
        required=True, ok=False, detail="absent from build", remedy="bash setup.sh")


def test_evaluate_raises_on_missing_key():
    raw = _all_ok_raw()
    del raw["demucs"]
    with pytest.raises(ValueError, match="keys"):
        preflight.evaluate(raw)


def test_evaluate_raises_on_extra_key():
    raw = _all_ok_raw()
    raw["bogus"] = (True, "x")
    with pytest.raises(ValueError, match="keys"):
        preflight.evaluate(raw)


def test_evaluate_orders_results_by_registry_not_raw():
    # raw inserted in REVERSED registry order → results must still follow CHECKS
    # (to_text's determinism depends on this, not on raw's incidental dict order)
    raw = {c.key: (True, "ok") for c in reversed(CHECKS)}
    assert [r.key for r in preflight.evaluate(raw).results] == [c.key for c in CHECKS]


def test_evaluate_without_root_leaves_remedies_relative():
    r = preflight.evaluate(_all_ok_raw())
    assert all(x.remedy.startswith("bash setup.sh") for x in r.results)


def test_evaluate_root_prefixes_cd_so_remedy_runs_from_any_cwd():
    raw = _all_ok_raw()
    raw["deps"] = (False, "x")
    dep = next(x for x in preflight.evaluate(raw, root="/x/clone").results
               if x.key == "deps")
    assert dep.remedy == "cd /x/clone && bash setup.sh"


def test_evaluate_root_shell_quotes_a_spaced_path():
    raw = _all_ok_raw()
    raw["demucs"] = (False, "x")
    adv = preflight.evaluate(raw, root="/a b/clone").advisories[0]
    assert adv.remedy == "cd '/a b/clone' && bash setup.sh"
