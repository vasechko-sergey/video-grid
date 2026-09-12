"""Every CLI states what it is for, on the surface an agent can re-derive.

A skill body is context and context is spent; `--help` is one Bash call at any
context age (design 2026-09-12 §0.3). The retro measured an agent reaching for
it after a compaction — 12 of 13 `--help` calls in the following 2 h 17 min —
and finding 5 of 31 top-level parsers and 0 of 15 subcommands with anything to
say (§0.4).

Two instruments, because they answer different questions. The walk below is
EXACT: it reads the parser objects, so no line-wrapped help text has to be
scraped. The subprocess check measures EMISSION — that the real entry point
still routes through `build_parser()` — and asserts only the description,
because `intake` carries three `help` strings using `%(default)s` and argparse
expands them at format time, so raw containment would fail on a correct file.
"""
import argparse
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = sorted(p.stem for p in (ROOT / "scripts").glob("*.py") if p.stem != "__init__")


def surfaces(parser: argparse.ArgumentParser, name: str):
    """Yield (label, parser) for the parser and every subparser under it."""
    yield name, parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for key, sub in action.choices.items():
                yield f"{name} {key}", sub


def arguments(parser: argparse.ArgumentParser):
    """Every real argument — `-h` and the subcommand slot are argparse's, not ours."""
    return [a for a in parser._actions
            if not isinstance(a, (argparse._HelpAction, argparse._SubParsersAction))]


@pytest.mark.parametrize("name", CLI)
def test_every_script_exposes_build_parser(name):
    mod = importlib.import_module(f"scripts.{name}")
    assert hasattr(mod, "build_parser"), (
        f"scripts/{name}.py has no build_parser() — the parser is built and consumed "
        f"in one breath, so nothing outside can see its 'help' surface. "
        f"Extract it: `def build_parser() -> argparse.ArgumentParser: ... return ap`")
    assert isinstance(mod.build_parser(), argparse.ArgumentParser)


@pytest.mark.parametrize("name", CLI)
def test_the_real_entry_point_routes_through_build_parser(name):
    """`--help` through `python -m` must emit what build_parser() declares.

    This is what catches a correct build_parser() that main() no longer calls —
    the walk above would still pass on a parser nothing runs."""
    mod = importlib.import_module(f"scripts.{name}")
    declared = mod.build_parser().description
    run = subprocess.run([sys.executable, "-m", f"scripts.{name}", "--help"],
                         capture_output=True, text=True, cwd=ROOT)
    assert run.returncode == 0, (
        f"python -m scripts.{name} --help exited {run.returncode}: {run.stderr.strip()}")
    assert declared, f"scripts/{name}.py declares no description"
    assert " ".join(declared.split()) in " ".join(run.stdout.split()), (
        f"scripts/{name}.py declares a description in build_parser() that its "
        f"--help does not print — main() is not using build_parser()")


@pytest.mark.parametrize("name", CLI)
def test_every_help_surface_states_a_purpose(name):
    """A subparser's own --help shows `description`, never `help`.

    `help=` renders in the PARENT's subcommand listing. Passing only `help=` —
    the state of all 15 subcommands before this slice — leaves the surface an
    agent reaches by drilling in completely blank (design §0.4)."""
    mod = importlib.import_module(f"scripts.{name}")
    blank = [label for label, parser in surfaces(mod.build_parser(), name)
             if not (parser.description or "").strip()]
    assert blank == [], (
        f"{blank} print no description on their own --help. A subcommand needs "
        f"description=, not only help=: help= renders in the parent's listing.")
