"""Fill a judge or reviewer prompt template from its packet (retro 2026-10-16 S14).

The two dispatched judges — episode-qc's per-episode judge and reel-review's reviewer —
read prompts kept as templates beside their skills. Both used to say "fill in the
placeholders", and the placeholders were instructions to the filler ("paste
evidence.json's intent object, or 'none recorded' if..."), so every run filled them by
hand: the second real run's agent wrote `fill_qc_prompts.py` and
`fill_review_prompt.py` to do it. The fill is mechanical, so it lives here; a
template carries exact `{NAME}` tokens and the tools that build each packet write the
filled prompt beside it.
"""
import re
from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[2] / "skills"
JUDGE_TEMPLATE = _SKILLS / "episode-qc" / "episode-reviewer.md"
REVIEWER_TEMPLATE = _SKILLS / "reel-review" / "reel-reviewer.md"

# What each filler supplies — a template that asks for anything else, or stops asking
# for one of these, is refused at fill time rather than shipping a raw `{TOKEN}`.
JUDGE_TOKENS = ("INTENT", "CHECKS", "TRACK", "GEOMETRY", "NATURALNESS", "STRIP_PATH",
                "STRIP_PX", "STORYBOARD_PATH", "STORYBOARD_PX", "CLIP", "FINDINGS_PATH",
                "VG")
REVIEWER_TOKENS = ("SPEC", "EDL_MD", "REPORT_JSON", "MUSIC", "REEL_PATH", "STILL_PATHS",
                   "FINDINGS_PATH")

# Upper-case only, so the JSON examples a template carries (`{"axis": ...}`) are not
# tokens.
_TOKEN = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")


def body(text: str) -> str:
    """The prompt itself: the template's one fenced block, without the fence. The text
    around it is for whoever maintains the template, not for the judge."""
    parts = text.split("```")
    if len(parts) != 3:
        raise ValueError(f"a prompt template carries exactly one fenced block; this one "
                         f"splits into {len(parts)} parts on ``` — the prompt itself may "
                         f"not contain a fence (indent code by four spaces instead)")
    return parts[1].lstrip("\n")


def tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text))


def fill(text: str, values: dict[str, str]) -> str:
    """Substitute every `{NAME}` in ONE pass, so a pasted value that itself contains a
    brace-word is never re-read as a token. A token with no value, and a value with no
    token, are both refused: either means the template and its filler disagree."""
    wanted = tokens(text)
    missing, unused = sorted(wanted - set(values)), sorted(set(values) - wanted)
    if missing or unused:
        raise ValueError(
            "the prompt template and its filler disagree — "
            + "; ".join(([f"no value for {', '.join('{' + m + '}' for m in missing)}"]
                         if missing else [])
                        + ([f"the template never asks for {', '.join(unused)}"]
                           if unused else [])))
    return _TOKEN.sub(lambda m: values[m.group(1)], text)


def render(template: Path, values: dict[str, str]) -> str:
    return fill(body(template.read_text()), values)
