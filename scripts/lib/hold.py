"""Held episodes — the conventions (design docs/specs/2026-10-21-photo-rhythm-design.md §1).

A held episode is one whose length nothing in the footage fixes: a photo, or a freeze
of a video frame (`EDLEpisode.held()`). These are the numbers its length is drawn from.
Pure and stdlib-only. Every value is a convention from the 2026-10-20 photo research,
not a measurement on a real photo run (design §7).
"""
import math

HOLD_DEFAULT = 2.0   # s a held episode plays when no music binds it (intake's old PHOTO_HOLD).
                     # A convention: the research's 1-2 s per photo in a reel.

HOLD_ROOM = 8.0      # s, the longest hold — the room the grid and the outro fit may grow a
                     # held episode into (intake's old PHOTO_ROOM). A convention.

HOLD_MIN = 1 / 3     # s, the shortest hold. A convention from WCAG 2.3.1 (at most three
                     # flashes a second): a hard cut between two stills is the same event.

BAND_HOLD = {"release": 2.0, "build": 1.0, "peak": 0.5}   # target seconds per energy band,
                     # keyed by pacing's band names — the research's three working modes.
                     # A convention; the planner that reads it is the grid's (design §2.1).


def _positive(name: str, v: object, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0:
        raise ValueError(f"hold.{where}: {name} must be a positive number of seconds, got {v!r}")
    return float(v)


def count_range(period: float, lo: float, hi: float) -> tuple[int, int]:
    """The whole beat counts a hold may take at this beat `period` — [⌈lo/period⌉,
    ⌊hi/period⌋], never below one beat (design §2.1). The 1e-9 slack keeps a hold of
    exactly `lo` or `hi` legal against float division: 1/3 s at 180 BPM is one beat, not
    two. Refused when no whole count fits — a beat longer than `hi`."""
    period = _positive("period", period, "count_range")
    lo, hi = _positive("lo", lo, "count_range"), _positive("hi", hi, "count_range")
    if lo > hi:
        raise ValueError(f"hold.count_range: lo {lo} exceeds hi {hi} — the hold range is empty")
    k_lo = max(1, math.ceil(lo / period - 1e-9))
    k_hi = math.floor(hi / period + 1e-9)
    if k_lo > k_hi:
        raise ValueError(f"hold.count_range: no whole number of beats of {period:.3f}s lies in "
                         f"[{lo:.3f}, {hi:.3f}]s — one beat is longer than the longest hold; "
                         f"check the track's tempo")
    return k_lo, k_hi


def beats_for(seconds: float, period: float, lo: float, hi: float) -> int:
    """A target length as beats: the power of two nearest `seconds / period` in log2
    (1, 2, 4, 8 — musical lengths), clamped to count_range (design §2.1). At 120 BPM the
    three bands are 4 / 2 / 1 beats; the floor binds only above 180 BPM."""
    seconds = _positive("seconds", seconds, "beats_for")
    k_lo, k_hi = count_range(period, lo, hi)
    k = 2 ** max(0, round(math.log2(seconds / period)))   # under one beat → 1, then the floor
    return min(k_hi, max(k_lo, k))


def vary(k: int, run: tuple[int, ...], k_lo: int, k_hi: int) -> int:
    """Never the same count three times in a row inside one run of held episodes
    (design §2.1): the third takes double if that stays under the ceiling, else half if
    that stays over the floor, else it stays. A build then reads 2, 2, 4, 2, 2, 4 — when
    every cut follows the same pulse the edit reads as a template (the research's CapCut
    finding). A convention, like the bands."""
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError(f"hold.vary: k must be a whole number of beats >= 1, got {k!r}")
    if tuple(run[-2:]) != (k, k):
        return k
    if 2 * k <= k_hi:
        return 2 * k
    if k % 2 == 0 and k // 2 >= k_lo:
        return k // 2
    return k
