"""Reel brief: the editorial SPEC atop project-init's machine subset (design
docs/specs/2026-07-12-reel-brief-design.md, stage 5.3). A hard config-spec —
validate-and-raise in __post_init__, JSON round-trip — like project.py's
ProjectConfig / edl.py's EDL. canvas comes from project.json (reel-brief FOLLOWS
project-init); this module never sources aspect itself. No ffmpeg — a text stage.
"""
import json
from dataclasses import dataclass
from pathlib import Path

MUSIC_MODES = ("local", "free", "any")            # rights lane (design §5.5); default "free"
STYLE_LEANS = ("classic", "balanced", "trend")    # classic ↔ trend axis; default "balanced"


@dataclass
class Spec:
    canvas: tuple            # from project.json; positive [w, h]      (gate)
    length_s: float          # target length per reel, seconds, > 0    (gate)
    mood: str                # non-empty                               (gate)
    hook: str                # non-empty                               (gate)
    reel_count: int = 1
    music: str = "auto"      # track name / "auto" / "none" (free, non-empty)
    music_mode: str = "free"
    style_lean: str = "balanced"
    platform: str = ""
    text: str = ""
    ending: str = ""
    cast: tuple = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not (isinstance(self.canvas, (tuple, list)) and len(self.canvas) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
                        for v in self.canvas)):
            raise ValueError(f"Spec.canvas must be [w, h] positive, got {self.canvas!r}")
        self.canvas = tuple(self.canvas)
        if (isinstance(self.length_s, bool) or not isinstance(self.length_s, (int, float))
                or self.length_s <= 0):
            raise ValueError(f"Spec.length_s must be a positive number (seconds), got {self.length_s!r}")
        if not (isinstance(self.mood, str) and self.mood.strip()):
            raise ValueError("Spec.mood must be a non-empty string (the §5.3 gate)")
        if not (isinstance(self.hook, str) and self.hook.strip()):
            raise ValueError("Spec.hook must be a non-empty string (the §5.3 gate)")
        if isinstance(self.reel_count, bool) or not isinstance(self.reel_count, int) or self.reel_count < 1:
            raise ValueError(f"Spec.reel_count must be an int >= 1, got {self.reel_count!r}")
        if not (isinstance(self.music, str) and self.music.strip()):
            raise ValueError("Spec.music must be a non-empty string (track name / 'auto' / 'none')")
        if self.music_mode not in MUSIC_MODES:
            raise ValueError(f"Spec.music_mode {self.music_mode!r} not in {MUSIC_MODES}")
        if self.style_lean not in STYLE_LEANS:
            raise ValueError(f"Spec.style_lean {self.style_lean!r} not in {STYLE_LEANS}")
        for name in ("platform", "text", "ending", "notes"):
            v = getattr(self, name)
            if not isinstance(v, str):
                raise ValueError(f"Spec.{name} must be a string, got {v!r}")
        if not (isinstance(self.cast, (tuple, list))
                and all(isinstance(c, str) and c.strip() for c in self.cast)):
            raise ValueError(f"Spec.cast must be a list of non-empty name strings, got {self.cast!r}")
        self.cast = tuple(self.cast)

    @classmethod
    def from_dict(cls, d: dict) -> "Spec":
        # Pass required raw values through so __post_init__ yields the clean
        # ValueError-with-remedy for missing/None/garbage; supply defaults for
        # absent optional keys (None → default, matching the manifest null rule).
        def opt(key: str, default: object) -> object:
            v = d.get(key)
            return default if v is None else v
        return cls(
            canvas=d.get("canvas"), length_s=d.get("length_s"),
            mood=d.get("mood"), hook=d.get("hook"),
            reel_count=opt("reel_count", 1), music=opt("music", "auto"),
            music_mode=opt("music_mode", "free"), style_lean=opt("style_lean", "balanced"),
            platform=opt("platform", ""), text=opt("text", ""),
            ending=opt("ending", ""), cast=opt("cast", ()), notes=opt("notes", ""))

    def to_dict(self) -> dict:
        return {"canvas": list(self.canvas), "length_s": self.length_s,
                "mood": self.mood, "hook": self.hook, "reel_count": self.reel_count,
                "music": self.music, "music_mode": self.music_mode,
                "style_lean": self.style_lean, "platform": self.platform,
                "text": self.text, "ending": self.ending, "cast": list(self.cast),
                "notes": self.notes}

    @classmethod
    def from_json(cls, path: str | Path) -> "Spec":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is corrupt ({e}) — re-run reel-brief to regenerate it") from e
        return cls.from_dict(d)

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))
