"""Pure decision core for mood-match (design docs/specs/2026-07-13-mood-match-design.md).
The MoodVector space + the anchor lexicon + scoring — numpy/stdlib only, no audio IO,
no librosa — so every branch is unit-tested deterministically (the offset.py discipline).
beats.mood_features maps an audio file into this space; scripts/mood.py ranks a folder."""
from dataclasses import dataclass

PACE_BPM = (60.0, 180.0)         # tempo → pace axis
BRIGHT_HZ = (500.0, 5000.0)      # spectral centroid → brightness axis
ENERGY_RMS = (0.0, 0.35)         # peak-normalized RMS mean → energy axis


@dataclass
class MoodVector:
    energy: float                # [0,1] soft ↔ driving (loudness-robust)
    brightness: float            # [0,1] dark/warm ↔ airy/bright
    pace: float                  # [0,1] slow ↔ fast

    def __post_init__(self) -> None:
        for name in ("energy", "brightness", "pace"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 <= v <= 1.0:
                raise ValueError(f"MoodVector.{name} must be a number in [0, 1], got {v!r}")
            setattr(self, name, float(v))

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.energy, self.brightness, self.pace)

    def to_dict(self) -> dict:
        return {"energy": self.energy, "brightness": self.brightness, "pace": self.pace}

    @classmethod
    def from_dict(cls, d: dict) -> "MoodVector":
        return cls(energy=d["energy"], brightness=d["brightness"], pace=d["pace"])


def norm01(x: float, lo: float, hi: float) -> float:
    """Map x from [lo, hi] onto [0, 1], clamped. hi>lo required (raise otherwise)."""
    if hi <= lo:
        raise ValueError(f"norm01 needs hi>lo, got lo={lo}, hi={hi}")
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


# curated, synonym-rich — synonyms share their family's vector so unknowns are rare.
# COARSE hand-tuned guesses (energy, brightness, pace); they only need to ORDER
# roughly — the agent picks the shortlist. All tunable in this one place.
MOOD_ANCHORS: dict[str, MoodVector] = {
    "energetic": MoodVector(0.90, 0.70, 0.85), "hype": MoodVector(0.92, 0.72, 0.88),
    "driving": MoodVector(0.85, 0.60, 0.80),   "intense": MoodVector(0.88, 0.55, 0.75),
    "chill": MoodVector(0.25, 0.50, 0.30),     "mellow": MoodVector(0.30, 0.50, 0.35),
    "calm": MoodVector(0.20, 0.45, 0.25),      "relaxed": MoodVector(0.25, 0.48, 0.30),
    "epic": MoodVector(0.80, 0.55, 0.55),      "cinematic": MoodVector(0.75, 0.50, 0.50),
    "triumphant": MoodVector(0.85, 0.65, 0.60),
    "dark": MoodVector(0.50, 0.20, 0.45),      "moody": MoodVector(0.45, 0.25, 0.40),
    "brooding": MoodVector(0.50, 0.18, 0.40),
    "happy": MoodVector(0.70, 0.85, 0.70),     "joyful": MoodVector(0.75, 0.88, 0.72),
    "upbeat": MoodVector(0.72, 0.80, 0.75),    "bright": MoodVector(0.68, 0.90, 0.68),
    "melancholic": MoodVector(0.30, 0.35, 0.35), "sad": MoodVector(0.28, 0.30, 0.30),
    "somber": MoodVector(0.30, 0.28, 0.32),
    "dreamy": MoodVector(0.30, 0.60, 0.30),    "ethereal": MoodVector(0.28, 0.65, 0.28),
    "ambient": MoodVector(0.25, 0.55, 0.25),
    "tense": MoodVector(0.75, 0.40, 0.60),     "dramatic": MoodVector(0.78, 0.45, 0.55),
    "urgent": MoodVector(0.80, 0.42, 0.70),
}
