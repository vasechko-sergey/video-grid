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


def render(music: MusicSpec, meta: dict | None, reel_name: str, reel_digest: str,
           reel_dur: float, cuts: list[float], platform: str = "") -> str:
    """The note's text. `meta` is fetch.track_meta(music.track) or None; `cuts` are the
    reel's internal cut times in seconds; `platform` is the brief's zone name."""
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
    first = (f"the first cut ({cuts[0]:.1f} s) lands on a beat" if cuts
             else "the music's first beat sits where you expect it")
    return "\n".join([
        f"# Sound for {reel_name} — attach it in {app}",
        "",
        f"`{reel_name}` in this folder is the delivered reel with the song removed: the "
        f"same picture, titles and look, with the natural sound and the transition "
        f"whooshes kept.",
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
        "4. Keep the original audio on — it carries the natural sound — and lower it "
        "under the music to taste.",
        f"5. Check by ear that {first}.",
        "",
        "## The one thing to check",
        "",
        f"The start was measured on the downloaded file (`{Path(music.track).name}`). An "
        f"app's version of a song can begin earlier or later than a music video's audio, "
        f"and a sped-up or remixed edit has another beat grid. If the first cut is off "
        f"the beat, nudge the start until it lands.",
        "",
        f"The source reel is `{reel_name}`, sha256 `{reel_digest}`. This file is not "
        f"attested: `check_reel` judged the version with the music.",
        "",
    ])
