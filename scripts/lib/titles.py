"""Titles: on-screen text (hook / ending / captions) rendered into the reel at
deliver (design docs/specs/2026-07-13-titles-design.md, §5.16). A hard config-spec —
Title/Titles validate-and-raise in __post_init__, JSON round-trip, markdown preview —
like edl.py's EDL / spec.py's Spec. build_filterchain (Task 2) is the drawtext chain
deliver injects into its one encode. drawtext only; explicit fontfile= + per-title
textfile dodge the filtergraph-escaping landmines (§12)."""
import json
import math
from dataclasses import dataclass
from pathlib import Path

from scripts.lib.fonts import resolve_font

POSITIONS: tuple[str, ...] = ("top", "center", "bottom")
STYLES: tuple[str, ...] = ("bold-box", "outline", "plain")


@dataclass(frozen=True)
class Title:
    text: str
    start: float
    dur: float
    font: str = "system"      # "system" -> resolve_font default; else a name/path (fonts.py)
    pos: str = "bottom"       # one of POSITIONS (safe-margin preset)
    style: str = "bold-box"   # one of STYLES

    def __post_init__(self) -> None:
        if not (isinstance(self.text, str) and self.text.strip()):
            raise ValueError(f"Title.text must be a non-empty string, got {self.text!r}")
        for name in ("start", "dur"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"Title.{name} must be a number (seconds), got {v!r}")
            if not math.isfinite(v):
                raise ValueError(f"Title.{name} must be a finite number (seconds), got {v!r}")
        if self.start < 0:
            raise ValueError(f"Title.start must be >= 0 seconds, got {self.start!r}")
        if self.dur <= 0:
            raise ValueError(f"Title.dur must be > 0 seconds, got {self.dur!r}")
        if not (isinstance(self.font, str) and self.font.strip()):
            raise ValueError(f"Title.font must be a non-empty name/path, got {self.font!r}")
        if self.pos not in POSITIONS:
            raise ValueError(f"Title.pos {self.pos!r} not in {POSITIONS}")
        if self.style not in STYLES:
            raise ValueError(f"Title.style {self.style!r} not in {STYLES}")

    def to_dict(self) -> dict:
        return {"text": self.text, "start": self.start, "dur": self.dur,
                "font": self.font, "pos": self.pos, "style": self.style}

    @classmethod
    def from_dict(cls, d: dict) -> "Title":
        if not isinstance(d, dict):
            raise ValueError(f"Title.from_dict: expected an object, got {type(d).__name__}")
        try:
            return cls(**d)            # missing-required / unknown key → TypeError → remedy below
        except TypeError as ex:
            raise ValueError(f"Title.from_dict: {d!r} has a missing or unknown field — {ex}") from ex


@dataclass(frozen=True)
class Titles:
    items: tuple[Title, ...] = ()

    def __post_init__(self) -> None:
        if not all(isinstance(t, Title) for t in self.items):
            raise ValueError("Titles.items must all be Title instances")
        object.__setattr__(self, "items", tuple(self.items))

    def to_dict(self) -> dict:
        return {"items": [t.to_dict() for t in self.items]}

    @classmethod
    def from_dict(cls, d: dict) -> "Titles":
        items_in = d.get("items", ())
        if not isinstance(items_in, (list, tuple)):
            raise ValueError(
                f"Titles.from_dict: 'items' must be a list, got {type(items_in).__name__}")
        items = []
        for i, t in enumerate(items_in):
            if not isinstance(t, dict):
                raise ValueError(
                    f"Titles.from_dict: items[{i}] must be an object, got {type(t).__name__}")
            items.append(Title.from_dict(t))
        return cls(items=tuple(items))

    @classmethod
    def from_json(cls, path: str | Path) -> "Titles":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is corrupt ({e}) — re-run titles to regenerate it") from e
        return cls.from_dict(d)

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    def to_markdown(self) -> str:
        lines = ["# Titles", "",
                 "| # | text | start→end | pos | style | font |",
                 "|---|------|-----------|-----|-------|------|"]
        for i, t in enumerate(self.items):
            lines.append(f"| {i} | {t.text.replace(chr(10), ' ')} | "
                         f"{t.start:.1f}→{t.start + t.dur:.1f} | {t.pos} | {t.style} | {t.font} |")
        if not self.items:
            lines.append("| – | (none) | – | – | – | – |")
        return "\n".join(lines)


_STYLE_FRAGMENTS: dict[str, str] = {
    "bold-box": "box=1:boxcolor=black@0.5:boxborderw=16",
    "outline": "borderw=4:bordercolor=black",
    "plain": "",
}
_Y_EXPR: dict[str, str] = {          # safe-margin presets (design §4); ffmpeg h/th exprs
    "top": "h*0.08",
    "center": "(h-th)/2",
    "bottom": "h-th-h*0.12",
}


def build_filterchain(titles: Titles, work_dir: str, resolve=resolve_font) -> str:
    """The drawtext chain deliver injects into its encode -vf: one drawtext per Title,
    shown only in [start, start+dur] via enable=. Positions use ffmpeg's own w/h/tw/th
    expressions (resolution-agnostic — no python dims). Each title's free text goes to
    a per-title textfile (textfile= dodges filtergraph escaping of ':'/apostrophes —
    draft's trick, generalized to N titles, hence work_dir). Empty Titles -> "" (deliver
    then encodes with no -vf). font/textfile are single-quoted; a resolved system/cask
    font and a skill-controlled work-dir path carry no apostrophe (draft's assumption)."""
    if not titles.items:
        return ""
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    for i, t in enumerate(titles.items):
        tf = work / f"title_{i}.txt"
        tf.write_text(t.text)
        font = resolve(t.font)
        style = _STYLE_FRAGMENTS[t.style]
        piece = (f"drawtext=fontfile='{font}':textfile='{tf}':fontsize=h/18:"
                 f"fontcolor=white:x=(w-tw)/2:y={_Y_EXPR[t.pos]}:"
                 f"{style + ':' if style else ''}"
                 f"enable='between(t,{t.start},{t.start + t.dur})'")
        parts.append(piece)
    return ",".join(parts)
