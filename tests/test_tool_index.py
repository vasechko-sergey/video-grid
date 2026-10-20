"""The tool index is generated, and the committed copy is pinned to it.

A stale index is worse than no index: it reads as authority. The precedent is
tests/test_plugin_manifests.py, whose own comment records the cost — a
version-keyed install path let episode-qc stay missing for 316 commits.
"""
import importlib.util
from pathlib import Path

from scripts import montage
from scripts.lib import toolindex

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "references/tools.md"


def _load_cli_help():
    """Load the sibling test module by PATH, not by name.

    `import tests.test_cli_help` cannot work: ultralytics ships its own
    top-level `tests/__init__.py` into site-packages, which shadows this
    repo's tests package no matter the sys.path order. Loading by path keeps
    the fix inside this one file — adding `tests/__init__.py` breaks
    tests/integration/test_grade_shipped_pixels.py, and a conftest shim is a
    repo-wide workaround for a one-file need."""
    spec = importlib.util.spec_from_file_location(
        "_cli_help_for_index", ROOT / "tests/test_cli_help.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cli_help = _load_cli_help()


def test_the_committed_index_matches_what_the_renderer_produces():
    assert INDEX.read_text() == toolindex.render_index(), (
        "references/tools.md is stale — regenerate it:\n"
        '    "$VG" scripts.montage tools > references/tools.md')


def test_every_help_surface_has_a_row():
    """Enumerated by test_cli_help's OWN walk, never toolindex's.

    Asking toolindex which surfaces exist and then checking it rendered those
    is circular: a walk that missed every subparser would render no subcommand
    rows and report none missing. The second copy of the four-line walk is what
    makes this assertion mean anything."""
    text = INDEX.read_text()
    expected = [label for name in cli_help.CLI
                for label, _ in cli_help.surfaces(
                    importlib.import_module(f"scripts.{name}").build_parser(), name)]
    assert len(expected) == 49, f"expected 49 help surfaces, the walk found {len(expected)}"
    for label in expected:
        assert f"`{label}`" in text, f"{label} is a help surface with no index row"


def test_the_index_has_no_argument_column():
    """--help answers 'how'; the index answers 'which'. An arguments column
    would duplicate --help, and duplication is how an index starts lying
    (design §2.4).

    This replaces a first draft that scanned rows for a ` --` token. Measured:
    that heuristic fires on legitimate content — `montage tools`'s own
    description names `--help`, and `match_grade build`'s names `--eps`. A
    check that fails on correct input is worse than none, so the claim is
    made structurally."""
    header = [ln for ln in INDEX.read_text().splitlines() if ln.startswith("| surface")]
    assert header == ["| surface | stage | writes | purpose |"], (
        f"the index's columns changed: {header}. It names which tool, never "
        f"which flag — regenerate with "
        f'`"$VG" scripts.montage tools > references/tools.md`')


def test_the_script_to_stage_map_names_only_real_stages():
    """STAGES_OF_SCRIPT is hand-written — the one thing in this slice that is.

    A script's module name is not its stage key for four of them (`intake` is
    `footage-intake`, `beats` is `music-and-mood`, `draft` is
    `assemble-draft`) and `edl_to_reel` runs three stages. That mapping cannot
    be derived, so it is typed — and therefore pinned."""
    from scripts import montage
    real = {s.key for s in montage.V1_STAGES}
    named = {k for keys in toolindex.STAGES_OF_SCRIPT.values() for k in keys}
    assert named <= real, (
        f"{sorted(named - real)} are in STAGES_OF_SCRIPT but not in V1_STAGES")
    scripts = {p.stem for p in (ROOT / "scripts").glob("*.py")}
    assert set(toolindex.STAGES_OF_SCRIPT) <= scripts, (
        f"{sorted(set(toolindex.STAGES_OF_SCRIPT) - scripts)} are mapped to a "
        f"stage but are not scripts")


def test_every_built_stage_is_claimed_by_some_script():
    """A stage nobody runs would show as an index row that never appears."""
    from scripts import montage
    built = {s.key for s in montage.V1_STAGES}
    claimed = {k for keys in toolindex.STAGES_OF_SCRIPT.values() for k in keys}
    assert built - claimed == set(), (
        f"{sorted(built - claimed)} are built stages that no script claims in "
        f"STAGES_OF_SCRIPT — either the map is stale or the stage has no runner")


def test_every_mapped_script_is_named_by_its_own_stage_runner():
    """Membership is not pairing. The two existing map pins hold under ANY
    permutation — transposing intake and contact_sheet passes both, and the
    byte-pin passes too because the renderer regenerates a transposed index.
    Stage.runner already names the script for every built stage, so the
    pairing has a second source to be checked against.

    One-directional on purpose: `assemble` appears in deliver's runner,
    `montage` in contact-sheet's and `track` in episodes-geometry's, so the
    reverse check would fire on prose that is correct."""
    from scripts import montage
    runner = {s.key: s.runner for s in montage.V1_STAGES}
    wrong = [(script, key) for script, keys in toolindex.STAGES_OF_SCRIPT.items()
             for key in keys if script not in runner[key]]
    assert wrong == [], (
        f"{wrong} are mapped script->stage but the stage's own Stage.runner does "
        f"not name that script — one of the two is wrong, and references/tools.md "
        f"is rendered from the map")


SKILL = ROOT / "skills/using-montage/SKILL.md"


def _generated_block(text: str) -> str:
    """The bytes between the markers, exclusive, with the marker lines' own
    newlines excluded. Raises rather than returning '' when a marker is
    missing: an empty string would compare unequal to the renderer and report
    as staleness, hiding the real fault (the markers were deleted)."""
    begin, end = text.index(toolindex.STAGES_BEGIN), text.index(toolindex.STAGES_END)
    return text[begin + len(toolindex.STAGES_BEGIN):end].strip("\n") + "\n"


def test_the_router_table_matches_what_the_renderer_produces():
    assert _generated_block(SKILL.read_text()) == toolindex.render_stages(), (
        "the stage table in skills/using-montage/SKILL.md is stale — regenerate:\n"
        '    "$VG" scripts.montage stages\n'
        "and replace the block between the two markers")


def test_the_router_table_covers_every_live_stage_once():
    """Enumerated from V1_STAGES directly, never from stage_steps().

    Asking the renderer which stages exist and then checking it rendered those
    is circular — the identical mistake test_every_help_surface_has_a_row
    exists to avoid."""
    from scripts import montage
    live = [s.key for s in montage.V1_STAGES]
    table = _generated_block(SKILL.read_text())
    rows = [l for l in table.splitlines() if l.startswith("| ") and "---" not in l][1:]
    assert len(rows) == len(live) == 15
    for key, row in zip(live, rows):
        assert f"`{key}`" in row, f"row for {key} missing or out of order: {row}"


def test_the_removed_trend_stage_gets_no_row():
    """trend-scan was removed on 2026-10-20 (backlog U1): no row, and no stage
    under that name for a row to come from."""
    assert "trend-scan" not in toolindex.render_stages()
    assert "trend-scan" not in [s.key for s in montage.V1_STAGES]
