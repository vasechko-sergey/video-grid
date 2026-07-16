"""Platform-keyed safe-zone check for §5.13 reel-final. A SafeZone is the UI-chrome
margin table for one platform (canvas fractions); the SAFE region is the rectangle
[left, 1-right] x [top, 1-bottom]. The subject (projected via lib.geometry) must sit
inside it. Advisory — check_reel reports it, never blocks on it. New platforms are
new table entries, not new code (mirrors ExportProfile)."""
from dataclasses import dataclass

from scripts.lib.geometry import marks_at_times
from scripts.lib.models import RoutePoint, CropPath, PathMeta


@dataclass(frozen=True)
class SafeZone:
    """Platform UI-chrome margins as canvas fractions. Values are conservative,
    tunable estimates of where each app draws overlays — they shift across app
    versions, so they live in a table, not a pixel spec."""
    top: float
    bottom: float
    left: float
    right: float

    def __post_init__(self) -> None:
        for name in ("top", "bottom", "left", "right"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 <= v < 0.5:
                raise ValueError(f"SafeZone.{name} must be a fraction in [0.0, 0.5), got {v!r} "
                                 "— a margin at/over half the frame leaves no safe region")

    def contains(self, fx: float, fy: float) -> bool:
        """Is the point (canvas fractions) inside the safe region?"""
        return self.left <= fx <= 1.0 - self.right and self.top <= fy <= 1.0 - self.bottom


SAFE_ZONES: dict[str, SafeZone] = {
    "generic": SafeZone(top=0.08, bottom=0.12, left=0.05, right=0.05),   # == titles presets
    "tiktok":  SafeZone(top=0.08, bottom=0.18, left=0.04, right=0.12),   # tall caption + right rail
    "reels":   SafeZone(top=0.08, bottom=0.16, left=0.04, right=0.11),   # instagram
    "shorts":  SafeZone(top=0.10, bottom=0.14, left=0.04, right=0.11),   # youtube
}
_ALIASES = {"instagram": "reels", "ig": "reels", "reel": "reels",
            "youtube": "shorts", "yt": "shorts"}


def safe_zone_for(platform: str) -> SafeZone:
    """Resolve a free-text platform label to its zone; unknown/empty → generic."""
    key = (platform or "").strip().lower()
    key = _ALIASES.get(key, key)
    return SAFE_ZONES.get(key, SAFE_ZONES["generic"])


def default_zone() -> SafeZone:
    """The generic zone — titles' single margin source (§5.16)."""
    return SAFE_ZONES["generic"]
