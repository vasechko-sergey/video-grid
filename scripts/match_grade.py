"""The match-grade conductor (design 2026-07-30, montage §10): measure every EDL episode's
source, compute one common reel tone target (the median), and author tone_src/tone_dst into
the episodes that deviate — so the reel reads as one grade. Reads EDL.json, writes it back
enriched + a MATCH.md report. Opt-in: it CHANGES the look, so it is never on the autonomous
path. matchgrade owns the decisions; this driver owns the ffmpeg measuring (measure_profile)
and the EDL IO. Mirror of pacing.py: pure core in lib, driver here."""
from dataclasses import replace
from pathlib import Path

from scripts.color_measure import measure_profile
from scripts.lib import matchgrade
from scripts.lib.edl import EDL


def conduct(edl: EDL, footage_root: str, *, eps: float = matchgrade.MATCH_EPS,
            force: bool = False) -> tuple[EDL, matchgrade.Profile, list[matchgrade.ToneDecision]]:
    """Measure each episode's source at its window MIDPOINT (start + dur/2 — a settled,
    representative frame of the shipped window; a WHOLE frame, not the crop — see design §5),
    compute the common target, and return (enriched EDL, target, decisions). The decisions
    carry each measured profile, so write_match writes the report with no second measure.
    Applying through dataclasses.replace rebuilds each EDLEpisode (re-coercing the tone
    pair to tuples). The pair's VALIDITY — ordering, gap, 0-255 range — is not gated here:
    EDLEpisode carries tone as data (like hero/pan/layout), and the check lives downstream
    in ReframeSpec (the soft-manifest / hard-engine split), so a malformed pair fails when
    the episode is processed, not in this driver."""
    profiles = [measure_profile(str(Path(footage_root) / e.source), at=e.start + e.dur / 2)
                for e in edl.episodes]
    target = matchgrade.common_target(profiles)
    has_tone = [e.tone_src is not None for e in edl.episodes]
    decisions = matchgrade.plan(profiles, has_tone, target, eps=eps, force=force)
    new_episodes = tuple(
        e if d.reason == "hand-authored"                       # respect the human's pair
        else replace(e, tone_src=d.tone_src, tone_dst=d.tone_dst)  # set, or clear (None) a stale one
        for e, d in zip(edl.episodes, decisions))
    return replace(edl, episodes=new_episodes), target, decisions
