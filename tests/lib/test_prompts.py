"""The judge/reviewer prompt filler (retro 2026-10-16 S14): the second real run's agent
wrote two scripts to fill these templates by hand, so the fill moves into the tools."""
from pathlib import Path

import pytest

from scripts.lib import prompts

ROOT = Path(__file__).resolve().parents[2]


def test_body_is_the_one_fenced_block():
    text = "# Title\n\nFill nothing.\n\n```\nYou are {WHO}.\n```\n"
    assert prompts.body(text) == "You are {WHO}.\n"


@pytest.mark.parametrize("text", ["no fence at all", "```\na\n```\n```\nb\n```\n", "```\nopen"])
def test_body_refuses_a_template_without_exactly_one_block(text):
    with pytest.raises(ValueError, match="fenced block"):
        prompts.body(text)


def test_fill_substitutes_every_token_once_and_never_rescans_a_value():
    # The injecting value comes FIRST, so a sequential replace loop would re-read it.
    out = prompts.fill("a {A} b {B} {A}", {"B": "{A} stays", "A": "x"})
    assert out == "a x b {A} stays x"


def test_fill_leaves_json_braces_alone():
    out = prompts.fill('{"axis": "hero"} {A}', {"A": "1"})
    assert out == '{"axis": "hero"} 1'


def test_fill_refuses_a_token_with_no_value():
    with pytest.raises(ValueError, match=r"\{B\}"):
        prompts.fill("{A} {B}", {"A": "1"})


def test_fill_refuses_a_value_the_template_never_asks_for():
    with pytest.raises(ValueError, match="EXTRA"):
        prompts.fill("{A}", {"A": "1", "EXTRA": "2"})


@pytest.mark.parametrize("name, tokens", [
    ("episode-qc/episode-reviewer.md", prompts.JUDGE_TOKENS),
    ("reel-review/reel-reviewer.md", prompts.REVIEWER_TOKENS),
])
def test_each_template_asks_for_exactly_the_tokens_its_filler_supplies(name, tokens):
    body = prompts.body((ROOT / "skills" / name).read_text())
    assert prompts.tokens(body) == set(tokens)


def test_the_templates_are_found_where_the_skills_ship_them():
    assert prompts.JUDGE_TEMPLATE == ROOT / "skills/episode-qc/episode-reviewer.md"
    assert prompts.REVIEWER_TEMPLATE == ROOT / "skills/reel-review/reel-reviewer.md"
