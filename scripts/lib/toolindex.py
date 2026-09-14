"""Render the tool index, each skill's conveyor position, and the router's chain.

Pure — no I/O, no argv. Three readers: `montage tools`, tests/test_tool_index.py
and tests/test_skills_contract.py. Most facts come from two places that already
exist: each script's own build_parser() and montage.V1_STAGES — which is why
the router's hand-written chain had already drifted from the registry it
describes (design §0.6). The one exception is STAGES_OF_SCRIPT below: a
script's module name is not its stage key for four of them, and edl_to_reel
runs three stages, so the map cannot be derived from either source — it is the
one hand-written table here, and it is checked against Stage.runner
(tests/test_tool_index.py) rather than trusted."""
import argparse
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

STAGES_OF_SCRIPT: dict[str, tuple[str, ...]] = {
    # A script's module name is NOT its stage key: four of them differ, and one
    # script runs three stages. Measured — `intake` is the `footage-intake`
    # stage, `beats` is `music-and-mood`, `draft` is `assemble-draft`, and
    # `edl_to_reel` runs `episodes-geometry`, `episodes` and `deliver`. A
    # name.replace("_", "-") lookup silently reports "—" for all four.
    "project_init": ("project-init",),
    "intake": ("footage-intake",),
    "contact_sheet": ("contact-sheet",),
    "reel_brief": ("reel-brief",),
    "edit_plan": ("edit-plan",),
    "beats": ("music-and-mood",),
    "pacing": ("pacing",),
    "edl_to_reel": ("episodes-geometry", "episodes", "deliver"),
    "match_grade": ("match-grade",),
    "draft": ("assemble-draft",),
    "titles": ("titles",),
    "episode_qc": ("episode-qc",),
    "reel_review": ("reel-review",),
}

#: Skills that are not conveyor stages, and what they are instead (design §0.7).
#: The mapping is not 1:1 in either direction: 9 of 14 skills are stage keys,
#: 5 are not, and 7 stages have no same-named skill. Inventing a predecessor
#: for verify-runtime would be worse than omitting one.
SKILL_ROLES: dict[str, str] = {
    "using-montage": "the router itself — it conducts every stage",
    "verify-runtime": "step 0, before every stage",
    "music-match": "serves the music-and-mood stage",
    "music-source": "serves the music-and-mood stage",
    "process-episode": "a per-episode worker under the episodes stage",
}


def cli_names() -> list[str]:
    return sorted(p.stem for p in (ROOT / "scripts").glob("*.py") if p.stem != "__init__")


def _surfaces(parser: argparse.ArgumentParser, name: str):
    yield name, parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for key, sub in action.choices.items():
                yield f"{name} {key}", sub


def surface_labels() -> list[str]:
    out = []
    for name in cli_names():
        mod = importlib.import_module(f"scripts.{name}")
        out.extend(label for label, _ in _surfaces(mod.build_parser(), name))
    return out


def _one_line(text: str) -> str:
    """Collapse a wrapped description to one cell, and cut at the first full stop
    so a row is a row. The full text stays in --help, which is the point."""
    flat = " ".join((text or "").split())
    head = flat.split(". ", 1)[0]
    return head.rstrip(".") if head else ""


def _cell(text: str) -> str:
    """A markdown table cell cannot hold a bare pipe. `build_reel`'s own
    description carries one ('delivered reel | stop-and-report'), so this is
    reached by real content, not defensive."""
    return text.replace("|", "\\|")


def render_index() -> str:
    from scripts import montage
    stage_of = {s.key: s for s in montage.V1_STAGES}
    lines = [
        "# Tool index",
        "",
        "**Generated — do not edit.** Regenerate with:",
        "",
        "    python -m scripts.montage tools > references/tools.md",
        "",
        "One row per `--help` surface. It answers *which tool*; `--help` answers",
        "*how do I run it*, and this file deliberately lists no arguments.",
        "",
        "| surface | stage | writes | purpose |",
        "|---|---|---|---|",
    ]
    for name in cli_names():
        mod = importlib.import_module(f"scripts.{name}")
        keys = STAGES_OF_SCRIPT.get(name, ())
        stage = ", ".join(f"`{k}`" for k in keys) or "—"
        writes = ", ".join(f"`{stage_of[k].artifact}`" for k in keys) or "—"
        for label, parser in _surfaces(mod.build_parser(), name):
            purpose = _cell(_one_line(parser.description))
            lines.append(f"| `{_cell(label)}` | {_cell(stage)} | {_cell(writes)} | {purpose} |")
    return "\n".join(lines) + "\n"


def position(stage_key: str) -> str:
    """The generated sentence a stage skill's description carries verbatim.

    Names the DECLARED order, not what a given run executes — an optional stage
    is skipped and only the router's chain shows which (design §2.5, §5)."""
    from scripts import montage
    live = [s.key for s in montage.V1_STAGES if s.kind != "deferred"]
    i = live.index(stage_key)
    if i == 0:
        return f"Conveyor position: first, before {live[1]}."
    if i == len(live) - 1:
        return f"Conveyor position: after {live[i - 1]}, last."
    return f"Conveyor position: after {live[i - 1]}, before {live[i + 1]}."


def chain() -> str:
    """The router's whole path. Brackets come from Stage.kind, never typed."""
    from scripts import montage
    parts = [s.key if s.kind == "required" else f"[{s.key}]"
             for s in montage.V1_STAGES if s.kind != "deferred"]
    return "Conveyor: " + " -> ".join(parts) + "."


#: Steps 0 and 1 of the router are the runtime gate and locating the run —
#: neither is a stage, so the first stage is step 2. The table owns these
#: numbers and tests/test_skill_convention.py binds the hand-written stubs to
#: them, which is what stops the drift design 2026-09-14 §0.5 measured: fifteen
#: live stages, fourteen numbered blocks, and `reel-review` — required — with
#: no number at all.
FIRST_STAGE_STEP = 2

#: Stage.checkpoint is the registry's own name for the three §4.1 user gates.
CHECKPOINT_LABEL: dict[str | None, str] = {
    None: "—", "spec": "CP1", "edl": "CP2", "final": "CP3"}

STAGES_BEGIN = "<!-- generated: stages — \"$VG\" scripts.montage stages -->\n"
STAGES_END = "<!-- /generated -->"

ROUTER_PAGES = "references/using-montage"


def stage_steps() -> list[tuple[int, object]]:
    """(step number, Stage) for every live stage, in conveyor order."""
    from scripts import montage
    live = [s for s in montage.V1_STAGES if s.kind != "deferred"]
    return list(enumerate(live, start=FIRST_STAGE_STEP))


def render_stages() -> str:
    """The router's stage table. One generated block: it owns the set, the
    order and the step numbers; the stubs beneath it own the commands, which
    carry run-directory paths no registry knows."""
    lines = ["| step | stage | kind | gate | writes | page |",
             "|---|---|---|---|---|---|"]
    for n, s in stage_steps():
        lines.append(f"| {n} | `{s.key}` | {s.kind} | {CHECKPOINT_LABEL[s.checkpoint]} "
                     f"| `{s.artifact}` | `{ROUTER_PAGES}/{s.key}.md` |")
    return "\n".join(lines) + "\n"
