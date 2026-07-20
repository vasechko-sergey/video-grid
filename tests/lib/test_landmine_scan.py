"""Static half of the landmine lint: no banned filter LITERAL may be emitted from
scripts/, on any path, whether or not a test exercises it.

Scans scripts/ only, never tests/ — the existing ban assertions (e.g.
tests/integration/test_reframe.py:449 `assert "lutrgb" not in args[1]`)
legitimately contain the literal. Tests are covered at runtime through proc.run
instead. See docs/specs/2026-07-20-landmine-lint-design.md §6.

EMITTED, not merely mentioned — the distinction is load-bearing and the plan
missed it. On the current clean tree two files name `lutrgb` in PROSE:
scripts/lib/color.py:1 ("lutrgb is banned; use mixer") and
scripts/check_episode.py:56. Both document the ban at exactly the place a future
author would look, so a line-level scan would force the ban to be
undocumentable at its own site. The scan therefore reads string LITERALS out of
the AST: comments never enter it, and docstrings are subtracted. That is also
precisely the set design §2's completeness argument is about — "every filter
string is a constant, an f-string whose static portion carries the filter name,
or a join() over fragments that are themselves such strings."
"""
import ast
from pathlib import Path

import pytest

from scripts.lib import lint

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

# The one file that must be skipped: it DECLARES the banned tokens, in real
# string constants (BANNED_FILTERS, and the violation message that names the
# filter). The skip is a hole by construction, so it is exactly one file wide and
# pinned by test_the_self_exemption_is_one_file_wide below.
_DEFINES_THE_BAN = SCRIPTS / "lib" / "lint.py"


# Root and skip are PARAMETERS, not module globals reached by monkeypatch:
# `tests/` has no __init__.py (testing-guide.md forbids adding one), so
# "tests.lib.test_landmine_scan.SCRIPTS" is not an importable dotted path and a
# string-target monkeypatch would fail to resolve.
def _sources(root: Path = SCRIPTS, skip: Path | None = None) -> list[Path]:
    skip = _DEFINES_THE_BAN if skip is None else skip
    return [p for p in sorted(root.rglob("*.py")) if p != skip]


def _literals(src: str) -> list[tuple[int, str]]:
    """Every string literal in `src` that is not a docstring — (line, text).

    Docstrings reach the AST like any other string, so they are subtracted by
    identity; comments never reach it at all and need no handling. An f-string's
    STATIC portion does count: `f"crop={w}"` parses to a Constant('crop=') beside
    its FormattedValue, which is the shape every real filtergraph in this repo is
    built from (scripts/reframe.py:296).
    """
    tree = ast.parse(src)
    docs = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            docs.add(id(body[0].value))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docs]


def _guilty(banned: str, paths: list[Path]) -> list[str]:
    """`file:line` for every non-docstring literal carrying `banned`."""
    return [f"{p}:{line}" for p in paths
            for line, text in _literals(p.read_text()) if banned in text]


def test_the_scan_actually_finds_files():
    """A glob that silently matches nothing would make every scan below pass
    vacuously — the failure mode this whole file exists to prevent."""
    found = _sources()
    assert len(found) > 20
    assert any(p.name == "reframe.py" for p in found)


@pytest.mark.parametrize("banned", lint.BANNED_FILTERS)
def test_no_script_emits_a_banned_filter(banned):
    guilty = _guilty(banned, _sources())
    assert guilty == [], f"{banned!r} emitted from: {guilty}"


def test_prose_naming_the_ban_is_not_an_emission(tmp_path):
    """A docstring or comment that names the banned filter is documentation, not
    an emission — and it is live: scripts/lib/color.py:1 and
    scripts/check_episode.py:56 both say `lutrgb` today, correctly. Flagging them
    would make the ban undocumentable at its own site, so the fix is a scan that
    reads literals rather than lines. A real constant beside them still counts.
    """
    f = tmp_path / "renderer.py"
    f.write_text('"""lutrgb is banned; use mixer."""\n'
                 '# design §12: lutrgb renders black frames\n'
                 'def build():\n'
                 '    """Never emit lutrgb here."""\n'
                 '    return "colorchannelmixer=rr=1.0"\n')
    assert _guilty("lutrgb", [f]) == []
    f.write_text(f.read_text() + 'VF = "lutrgb=r=val*1.1"\n')
    assert _guilty("lutrgb", [f]) == [f"{f}:6"]


def test_an_fstring_filtergraph_is_covered(tmp_path):
    """Design §2's completeness claim rests on this case: no filter NAME in this
    repo is computed, but almost every one arrives inside an f-string whose
    static portion carries it. A scan that only saw plain constants would miss
    the shape reframe actually emits."""
    f = tmp_path / "renderer.py"
    f.write_text('def vf(v):\n    return f"lutrgb=r={v}:g={v}"\n')
    assert _guilty("lutrgb", [f]) == [f"{f}:2"]


def test_the_self_exemption_is_one_file_wide(tmp_path):
    """Plant a violation in a DIFFERENT file and prove the scan still catches it.
    Without this, widening the skip to a directory (or to lib/) would go unnoticed
    and the static layer would quietly stop covering anything."""
    fake = tmp_path / "scripts"
    (fake / "lib").mkdir(parents=True)
    (fake / "lib" / "lint.py").write_text('BANNED_FILTERS = ("lutrgb",)\n')
    (fake / "renderer.py").write_text('VF = "lutrgb=r=val*1.1"\n')
    guilty = _guilty("lutrgb", _sources(fake, fake / "lib" / "lint.py"))
    assert guilty == [f"{fake / 'renderer.py'}:1"]
