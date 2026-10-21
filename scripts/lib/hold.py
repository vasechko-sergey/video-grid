"""Held episodes — the conventions (design docs/specs/2026-10-21-photo-rhythm-design.md §1).

A held episode is one whose length nothing in the footage fixes: a photo, or a freeze
of a video frame (`EDLEpisode.held()`). These are the numbers its length is drawn from.
Pure and stdlib-only. Every value is a convention from the 2026-10-20 photo research,
not a measurement on a real photo run (design §7).
"""

HOLD_DEFAULT = 2.0   # s a held episode plays when no music binds it (intake's old PHOTO_HOLD).
                     # A convention: the research's 1-2 s per photo in a reel.

HOLD_ROOM = 8.0      # s, the longest hold — the room the grid and the outro fit may grow a
                     # held episode into (intake's old PHOTO_ROOM). A convention.

HOLD_MIN = 1 / 3     # s, the shortest hold. A convention from WCAG 2.3.1 (at most three
                     # flashes a second): a hard cut between two stills is the same event.

BAND_HOLD = {"release": 2.0, "build": 1.0, "peak": 0.5}   # target seconds per energy band,
                     # keyed by pacing's band names — the research's three working modes.
                     # A convention; the planner that reads it is the grid's (design §2.1).
