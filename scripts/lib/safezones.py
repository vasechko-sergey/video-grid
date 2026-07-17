"""Platform-keyed safe-zone check for §5.13 reel-final. A SafeZone is the UI-chrome
margin table for one platform (canvas fractions); the SAFE region is the rectangle
[left, 1-right] x [top, 1-bottom]. The subject (projected via lib.geometry) must sit
inside it. Advisory — check_reel reports it, never blocks on it. New platforms are
new table entries, not new code (mirrors ExportProfile)."""
from dataclasses import dataclass

from scripts.lib.geometry import marks_at_times, extent_at_times
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


_SAFE_SAMPLES = 5


def _sample_times(dur: float) -> list[float]:
    return [(k + 0.5) * dur / _SAFE_SAMPLES for k in range(_SAFE_SAMPLES)]


def subject_marks(route: list[RoutePoint], path: CropPath, meta: PathMeta,
                  dur: float) -> list[tuple[float, float]]:
    """The subject's (fx, fy) canvas fractions at _SAFE_SAMPLES points across the
    episode — the projection lib.geometry already implements, sampled by time."""
    return marks_at_times(route, path, meta, _sample_times(dur))


def subject_extents(route: list[RoutePoint], path: CropPath, meta: PathMeta,
                    dur: float) -> list[tuple[float, float, float, float]]:
    """The subject's bbox corners (fx0, fy0, fx1, fy1) at _SAFE_SAMPLES points —
    the extent counterpart of subject_marks, feeding reel_final.evaluate_key_action
    (§5.13). Same sampling, geometry.extent_at_times instead of marks_at_times."""
    return extent_at_times(route, path, meta, _sample_times(dur))


def evaluate(marks_per_ep: list[list[tuple[float, float]]],
             zone: SafeZone) -> tuple[bool, dict]:
    """Pure decision: flag if any subject mark in any episode falls outside its safe
    region. The report names the worst offender (deepest overshoot) so a human sees
    where. Advisory — the caller never turns this into a ReelFailure."""
    worst = None                                   # (overshoot, episode_idx, fx, fy)
    for i, marks in enumerate(marks_per_ep):
        for fx, fy in marks:
            if not zone.contains(fx, fy):
                over = max(zone.left - fx, fx - (1.0 - zone.right),
                           zone.top - fy, fy - (1.0 - zone.bottom))
                if worst is None or over > worst[0]:
                    worst = (over, i, round(fx, 4), round(fy, 4))
    if worst is None:
        return True, {"episodes": len(marks_per_ep), "advisory": True}
    _, idx, fx, fy = worst
    return False, {"worst_episode": idx, "worst_mark": [fx, fy],
                   "zone": {"top": zone.top, "bottom": zone.bottom,
                            "left": zone.left, "right": zone.right}, "advisory": True}
