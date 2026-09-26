import pytest

from scripts.lib import preflight
from scripts.lib.preflight import CHECKS, CheckOutcome, RuntimeReport


def _all_ok_raw():
    return {c.key: (True, "ok") for c in CHECKS}


def test_registry_keys_unique_and_expected_split():
    keys = [c.key for c in CHECKS]
    assert len(keys) == len(set(keys))
    assert [c.key for c in CHECKS if c.required] == [
        "plugin", "deps", "ffmpeg_bin", "drawtext", "vidstab", "font",
        "weights", "demucs"]
    assert [c.key for c in CHECKS if not c.required] == ["reid"]


def test_the_plugin_check_is_first_so_a_stale_install_is_the_first_line():
    """CHECKS's order is the report's order. The plugin question is outermost —
    'are you running the instructions you think you are?' — and cheapest (two
    file reads, no subprocess), so it leads."""
    assert CHECKS[0].key == "plugin"


def test_demucs_alone_blocks_the_run():
    """2026-08-14: demucs went advisory → REQUIRED. It is the only sensor that can
    say where the vocals stop, and choose_offset's mix-silence proxy — which used to
    make an absence survivable — was deleted for answering wrongly rather than
    failing. A demucs-only miss must now block, not warn."""
    results = tuple(
        CheckOutcome(key=c.key, label=c.label, required=c.required,
                     ok=(c.key != "demucs"), detail="", remedy=c.remedy)
        for c in CHECKS)
    r = RuntimeReport(results=results)
    assert r.ok is False
    assert [f.key for f in r.failures] == ["demucs"] and r.advisories == ()


def test_report_partition():
    results = tuple(
        CheckOutcome(key=c.key, label=c.label, required=c.required,
                     ok=(c.key not in ("drawtext", "reid")),
                     detail="", remedy=c.remedy)
        for c in CHECKS)
    r = RuntimeReport(results=results)
    assert r.ok is False                                  # a required miss (drawtext)
    assert [f.key for f in r.failures] == ["drawtext"]
    assert [a.key for a in r.advisories] == ["reid"]


def test_report_ok_when_only_advisory_fails():
    results = tuple(
        CheckOutcome(key=c.key, label=c.label, required=c.required,
                     ok=(c.key != "reid"), detail="", remedy=c.remedy)
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
        "key": "plugin", "label": "installed plugin matches the clone",
        "required": True, "ok": True, "detail": "ok",
        "remedy": "claude plugin update video-grid@video-grid"}


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
                     ok=(c.key not in ("font", "reid")),
                     detail=("no system font" if c.key == "font" else
                             "not installed" if c.key == "reid" else "ok"),
                     remedy=c.remedy)
        for c in CHECKS)
    text = RuntimeReport(results=results).to_text()
    assert "runtime NOT ready" in text
    assert "[FAIL] font" in text and "font: bash setup.sh" in text
    assert "[warn] reid" in text and "reid: bash setup.sh" in text


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
    # Generic over the registry (not hardcoded to one check's remedy text) so a
    # new row's own remedy string cannot make this test collateral damage: the
    # invariant is "no cd prefix", not "every remedy says bash setup.sh".
    r = preflight.evaluate(_all_ok_raw())
    assert all(x.remedy == c.remedy for x, c in zip(r.results, CHECKS))


def test_evaluate_root_prefixes_cd_so_remedy_runs_from_any_cwd():
    raw = _all_ok_raw()
    raw["deps"] = (False, "x")
    dep = next(x for x in preflight.evaluate(raw, root="/x/clone").results
               if x.key == "deps")
    assert dep.remedy == "cd /x/clone && bash setup.sh"


def test_evaluate_root_shell_quotes_a_spaced_path():
    raw = _all_ok_raw()
    raw["reid"] = (False, "x")
    adv = preflight.evaluate(raw, root="/a b/clone").advisories[0]
    assert adv.remedy == "cd '/a b/clone' && bash setup.sh"


# --- plugin staleness (design 2026-09-25 §2.2). Four states, each named: the
# check must distinguish "there is no install to be stale" from "the install
# agrees" from "the install disagrees", because only the last is a defect and the
# first two are ordinary, legitimate configurations.

def test_no_record_file_passes_and_says_so():
    ok, detail = preflight.plugin_staleness(None, "0.14.0")
    assert ok is True
    assert "no install record" in detail


def test_record_without_this_plugin_passes_with_a_different_reason():
    """Distinct from None on purpose. Both mean 'nothing installed to be stale',
    but one means Claude Code has installed no plugins at all and the other means
    it has installed others and not this one. A single shared message would throw
    away a distinction the inputs carry."""
    ok, detail = preflight.plugin_staleness((), "0.14.0")
    assert ok is True
    assert "not installed as a plugin" in detail
    assert "no install record" not in detail


def test_matching_single_record_passes_and_names_the_version():
    ok, detail = preflight.plugin_staleness((("user", "0.14.0"),), "0.14.0")
    assert ok is True and "0.14.0" in detail


def test_a_behind_record_fails_and_names_both_versions():
    ok, detail = preflight.plugin_staleness((("user", "0.2.1"),), "0.14.0")
    assert ok is False
    assert "0.2.1" in detail and "0.14.0" in detail


def test_an_ahead_record_fails_too():
    """Direction is not interpreted (design §4) — a clone checked out behind its
    own install is still two things that disagree, and the one remedy fixes it
    either way because the marketplace IS the clone."""
    ok, _ = preflight.plugin_staleness((("user", "0.14.0"),), "0.2.1")
    assert ok is False


def test_every_mismatching_scope_is_named_not_only_the_first():
    """installed_plugins.json maps a plugin id to a LIST of records (user,
    project, local, managed). Reading only the first is the unvalidated-shapes
    defect: a reader defending itself with a guarantee the producer does not
    make."""
    ok, detail = preflight.plugin_staleness(
        (("user", "0.2.1"), ("project", "0.9.2")), "0.14.0")
    assert ok is False
    assert "user" in detail and "project" in detail
    assert "0.2.1" in detail and "0.9.2" in detail


def test_one_matching_record_does_not_excuse_a_mismatching_sibling():
    ok, detail = preflight.plugin_staleness(
        (("user", "0.14.0"), ("project", "0.2.1")), "0.14.0")
    assert ok is False
    assert "project" in detail
