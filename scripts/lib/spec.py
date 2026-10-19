"""Reel brief: the editorial SPEC atop project-init's machine subset (design
docs/specs/2026-07-12-reel-brief-design.md, stage 5.3). A hard config-spec —
validate-and-raise in __post_init__, JSON round-trip — like project.py's
ProjectConfig / edl.py's EDL. canvas comes from project.json (reel-brief FOLLOWS
project-init); this module never sources aspect itself. No ffmpeg — a text stage.
"""
import json
import math
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
    tone_bias: tuple | None = None   # (p5, p50, p95) luma displacement, or None
    # Screen-time weights per cast name ({"Lena": 1, "Sergei": 1} = equal), or None = not
    # asked. The second real run's brief answered "both equally" and kept it only in
    # `notes`, which nothing reads; REEL_v3 shipped 55/45 (retro 2026-10-16 S9). edit_plan
    # carries it onto the EDL and reports screen time against it — a report, not a gate.
    cast_share: dict | None = None
    # The brief's average-shot-length band (lo, hi) seconds, or None = take the mood
    # preset's. Outranks MoodPreset.asl the way tone_bias outranks its colour. The
    # second real run's "calm" resolved to `nostalgic` (2.0–4.0 s) and the first plan cut
    # longboard rides into 13 pieces of 3.3 s; the operator rejected it at CP2 — "rides
    # of 2 seconds again" — and wanted whole rides of up to 10 s (retro 2026-10-16 S5).
    asl: tuple | None = None

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
        if self.reel_count > 1:
            raise ValueError(
                f"Spec.reel_count {self.reel_count} — multi-reel fan-out is not built, and "
                "accepting it here produced ONE reel with no word said. Run the conveyor "
                "one reel at a time (a project directory per reel). The field stays in the "
                "contract for the day fan-out lands (design 2026-08-12 §1.4)")
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
        if self.tone_bias is not None:
            if not (isinstance(self.tone_bias, (tuple, list)) and len(self.tone_bias) == 3
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                            for v in self.tone_bias)):
                raise ValueError(
                    f"Spec.tone_bias must be three numbers — a (p5, p50, p95) luma "
                    f"displacement, the same shape as MoodPreset.tone_bias — or null to "
                    f"take the mood preset's own. Got {self.tone_bias!r}. Write [0, 0, 0] "
                    f"to keep the mood and leave the colour alone")
            self.tone_bias = tuple(float(v) for v in self.tone_bias)
        if self.asl is not None:
            if not (isinstance(self.asl, (tuple, list)) and len(self.asl) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                            and math.isfinite(v) for v in self.asl)
                    and 0 < self.asl[0] < self.asl[1]):
                raise ValueError(
                    f"Spec.asl must be a (lo, hi) band of seconds with 0 < lo < hi — the "
                    f"brief's average shot length, e.g. (6, 10) for whole rides — or null to "
                    f"take the mood preset's. Got {self.asl!r}")
            self.asl = (float(self.asl[0]), float(self.asl[1]))
        if self.cast_share is not None:
            self.cast_share = validate_cast_share(self.cast_share, "Spec.cast_share")
            stray = [n for n in self.cast_share if self.cast and n not in self.cast]
            if stray:
                raise ValueError(
                    f"Spec.cast_share names {stray} not in Spec.cast {list(self.cast)} — a "
                    f"share is screen time for a named hero, so name them with --cast too")

    @classmethod
    def from_dict(cls, d: dict) -> "Spec":
        # The top level is checked FIRST, before any d.get — __post_init__ can only clean up
        # values it was handed, and a non-dict `d` never reaches it: d.get raised a bare
        # AttributeError instead, out of a boundary that reads user JSON. One documented type.
        if not isinstance(d, dict):
            raise ValueError(f"Spec.from_dict: expected a SPEC.json object with 'canvas'/'length_s'/"
                             f"'mood'/'hook' fields, got {type(d).__name__} — re-run reel-brief to "
                             f"regenerate SPEC.json")
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
            ending=opt("ending", ""), cast=opt("cast", ()), notes=opt("notes", ""),
            tone_bias=d.get("tone_bias"), cast_share=d.get("cast_share"),
            asl=d.get("asl"))

    def to_dict(self) -> dict:
        return {"canvas": list(self.canvas), "length_s": self.length_s,
                "mood": self.mood, "hook": self.hook, "reel_count": self.reel_count,
                "music": self.music, "music_mode": self.music_mode,
                "style_lean": self.style_lean, "platform": self.platform,
                "text": self.text, "ending": self.ending, "cast": list(self.cast),
                "notes": self.notes,
                "tone_bias": None if self.tone_bias is None else list(self.tone_bias),
                "cast_share": None if self.cast_share is None else dict(self.cast_share),
                "asl": None if self.asl is None else list(self.asl)}

    @classmethod
    def from_json(cls, path: str | Path) -> "Spec":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is corrupt ({e}) — re-run reel-brief to regenerate it") from e
        return cls.from_dict(d)

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    def to_markdown(self) -> str:
        w, h = self.canvas
        # The plural arm is unreachable today and deliberately kept: __post_init__ refuses
        # reel_count > 1 (multi-reel fan-out is not built), and every construction path —
        # __init__, from_dict, from_json, dataclasses.replace — runs it. It becomes live
        # again the day fan-out lands, which is the same day the refusal comes out.
        reels = f"{self.reel_count} reel" + ("s" if self.reel_count != 1 else "")
        cast = ", ".join(self.cast) if self.cast else "–"
        # (M-2, final-findings.md): every other Spec field reaches SPEC.md — this slice's
        # own headline field must too, or an authored colour displacement is invisible at
        # Checkpoint 1, the point using-montage's SKILL names as where the user approves
        # SPEC.md. "–" (unauthored) reads exactly like every other optional field above;
        # a signed triple (p5/p50/p95) shows the mood preset's own taste is being overridden.
        tone_bias = ("–" if self.tone_bias is None
                     else "/".join(f"{v:+.0f}" for v in self.tone_bias))
        lines = [
            f"# Reel brief — {reels}, {self.length_s:.0f}s, {w}:{h}",
            "",
            f"- **Mood:** {self.mood}",
            f"- **Tone bias:** {tone_bias}",
            f"- **Hook:** {self.hook}",
            f"- **Music:** {self.music} (mode: {self.music_mode})",
            f"- **Style-lean:** {self.style_lean}",
            f"- **Platform:** {self.platform or '–'}",
            f"- **Cast:** {cast}",
            f"- **Cast share:** {share_line(self.cast_share) if self.cast_share else '–'}",
            f"- **Shot length:** "
            f"{f'{self.asl[0]:.1f}–{self.asl[1]:.1f}s' if self.asl else '–'}",
            f"- **Text:** {self.text or '–'}",
            f"- **Ending:** {self.ending or '–'}",
            f"- **Notes:** {self.notes or '–'}",
        ]
        return "\n".join(lines)


def validate_cast_share(share: object, where: str) -> dict:
    """{name: positive weight} → the same dict with float weights, or ValueError.

    One validator for the two carriers (Spec, EDL), so the brief and the cut cannot
    disagree about what a legal share is."""
    if not (isinstance(share, dict) and share):
        raise ValueError(f"{where} must be a non-empty {{name: weight}} object, got {share!r}")
    out = {}
    for name, w in share.items():
        if not (isinstance(name, str) and name.strip()):
            raise ValueError(f"{where} names must be non-empty strings, got {name!r}")
        if (isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w)
                or w <= 0):
            raise ValueError(f"{where}[{name!r}] must be a positive number (a weight), "
                             f"got {w!r}")
        out[name] = float(w)
    return out


def share_line(share: dict) -> str:
    """'Lena 50% · Sergei 50%' — weights as percentages, in the brief's own order."""
    total = sum(share.values())
    return " · ".join(f"{n} {100 * w / total:.0f}%" for n, w in share.items())
