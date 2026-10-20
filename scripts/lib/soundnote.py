"""The sound note beside a music-less delivery (design 2026-10-20 §4): which track to
attach in the app, where in it the reel's music starts, and how to check it by ear.
Pure: build_reel hands it what it already has and writes the text."""
from pathlib import Path

from scripts.lib.models import MusicSpec

# The platform label `safezones` resolved, spoken as the app the user opens.
_APP = {"reels": "Instagram", "tiktok": "TikTok", "shorts": "YouTube Shorts"}


def clock(seconds: float) -> str:
    """49.0 → '0:49.0', 125.25 → '2:05.2' — how an app's start slider reads."""
    m, s = divmod(round(seconds, 1), 60)
    return f"{int(m)}:{s:04.1f}"


def _kept(ambient: bool, sfx: bool) -> str:
    if ambient and sfx:
        return "with the natural sound and the transition whooshes kept"
    if ambient:
        return "with the natural sound kept"
    if sfx:
        return "with the transition whooshes kept"
    return "and silent: the reel had no natural sound to keep"


def render(music: MusicSpec, meta: dict | None, reel_name: str, reel_digest: str,
           reel_dur: float, cuts: list[float], platform: str = "", *,
           ambient: bool = True, sfx: bool = False, linear: bool = True,
           fitted: bool = True) -> str:
    """The note's text. `meta` is fetch.track_meta(music.track) or None; `cuts` are the
    reel's internal cut times in seconds; `platform` is the brief's zone name.
    `ambient`/`sfx` say what the music-less stem holds and `linear` whether its level is
    the music version's exactly (mix's record); `fitted` whether the cuts were fitted to
    this music (an outro fit exists only after the pacing pass), since only then is
    "the first cut lands on a beat" a check rather than a hope."""
    app = _APP.get(platform, "the app")
    if meta is not None:
        track = f"{meta['artist']} — {meta['title']}"
        source = (f"{meta.get('source', '?')} · {meta.get('source_url', '?')} · licence: "
                  f"{meta.get('license', '?')}")
        search = f"{meta['artist']} {meta['title']}"
    else:
        track = Path(music.track).stem
        source = "a local file (no music_fetch record beside it)"
        search = track
    start = clock(music.start_offset)
    cut_line = " · ".join(f"{t:.1f}" for t in cuts) + " s" if cuts else "none (one shot)"
    if fitted:
        check = (f"5. Check by ear that the first cut ({cuts[0]:.1f} s) lands on a beat."
                 if cuts else "5. Check by ear that the music's first beat sits where you "
                              "expect it.")
    else:
        check = ("5. The cuts were not fitted to this song's beats (no pacing pass), so "
                 "the start is only where the reel's music was taken from — move it if "
                 "another part of the song suits the cut better.")
    audio = (["4. Keep the original audio on — it carries the natural sound — and lower "
              "it under the music to taste."] if ambient
             else ["4. The file has no natural sound, so the original-audio level does "
                   "not matter."])
    if ambient and not linear:
        audio.append("   The version with the music was levelled dynamically, so the "
                     "natural sound here can sit a few dB from where it was under the "
                     "music: set its level by ear.")
    return "\n".join([
        f"# Sound for {reel_name} — attach it in {app}",
        "",
        f"`{reel_name}` in this folder is the delivered reel with the song removed: the "
        f"same picture, titles and look, {_kept(ambient, sfx)}.",
        "",
        "| | |",
        "|---|---|",
        f"| Track | {track} |",
        f"| Source | {source} |",
        f"| Start in the track | {start} |",
        f"| Length | {reel_dur:.1f} s (the whole reel) |",
        f"| Cuts | {cut_line} |",
        "",
        f"## In {app}",
        "",
        f"1. Upload this file, not `../{reel_name}`.",
        f"2. Add the sound: search \"{search}\".",
        f"3. Set its start to {start}.",
        *audio,
        check,
        "",
        "## The one thing to check",
        "",
        f"The start was measured on the downloaded file (`{Path(music.track).name}`). An "
        f"app's version of a song can begin earlier or later than a music video's audio, "
        f"and a sped-up or remixed edit has another beat grid."
        + (" If the first cut is off the beat, nudge the start until it lands."
           if fitted else ""),
        "",
        f"The source reel is `{reel_name}`, sha256 `{reel_digest}`. This file is not "
        f"attested: `check_reel` judged the version with the music.",
        "",
    ])
