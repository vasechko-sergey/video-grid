# scripts/lib/fetch.py
"""Download boundary for music sourcing (design §5). Resolves a chosen Candidate to a
cached audio file + a metadata sidecar, per rights lane: `free` (Jamendo/ccMixter) is a
direct HTTP GET; `any` (YouTube / iTunes / Deezer name) goes through yt-dlp and logs a
responsibility line. Mirrors vocals.py — the opt-in heavy tool (yt-dlp) sits behind
catalog.has_ytdlp() with a fail-loud remedy. The driver stamps `date` (no ambient clock)."""
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.lib import catalog


@dataclass(frozen=True)
class FetchedTrack:
    path: str
    title: str
    artist: str
    source: str
    source_url: str
    license: str
    date: str

    def __post_init__(self) -> None:
        for name in ("path", "title", "artist", "source", "source_url", "license", "date"):
            v = getattr(self, name)
            if not (isinstance(v, str) and v.strip()):
                raise ValueError(f"FetchedTrack.{name} must be a non-empty string, got {v!r}")

    def sidecar(self) -> dict:
        return {"title": self.title, "artist": self.artist, "source": self.source,
                "source_url": self.source_url, "license": self.license, "date": self.date}


def track_meta(track: str) -> dict | None:
    """The record `download` wrote beside `track` — {title, artist, source, source_url,
    license, date} — or None when there is none, or the `.json` beside it is not one
    (a local file can sit next to anything). Descriptive only: without a record the
    file's own name is still true, just less said. One reader for the sidecar format
    this module owns, shared by the reel review's prompt and the sound note."""
    meta = Path(track).with_suffix(".json")
    try:
        t = json.loads(meta.read_text()) if meta.is_file() else None
    except json.JSONDecodeError:
        return None
    return t if isinstance(t, dict) and t.get("artist") and t.get("title") else None


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _cached(cache: Path, slug: str) -> Path | None:
    hits = sorted(p for p in cache.glob(f"{slug}.*") if p.suffix != ".json")
    return hits[0] if hits else None


def _cache_key(candidate: catalog.Candidate) -> str:
    """Cache filename stem: the slug plus a short hash of the source-native ref, so two
    distinct tracks that share source+artist+title (same slug) never collide in the cache
    (design §5.3 — keyed by source+id, not just source+title)."""
    ref_hash = hashlib.sha1(candidate.ref.encode("utf-8")).hexdigest()[:8]
    return f"{candidate.slug()}-{ref_hash}"


def download(candidate: catalog.Candidate, mode: str, cache_dir: str, date: str) -> FetchedTrack:
    """Download `candidate` to `cache_dir` and write its sidecar. `free` → direct HTTP;
    `any` → yt-dlp (+ responsibility log). A cached key (sidecar present) is reused."""
    if mode not in ("free", "any"):
        raise ValueError(f"fetch mode {mode!r} not in (free, any)")
    if mode == "free" and candidate.source not in ("jamendo", "ccmixter"):
        raise ValueError(f"free lane cannot fetch a {candidate.source} source — rights invariant")
    cache = Path(cache_dir); cache.mkdir(parents=True, exist_ok=True)
    key = _cache_key(candidate)
    sidecar = cache / f"{key}.json"
    if sidecar.exists() and (hit := _cached(cache, key)) is not None:
        meta = json.loads(sidecar.read_text())
        _log(f"music_fetch: reusing cached {hit.name}")
        return FetchedTrack(path=str(hit), title=meta["title"], artist=meta["artist"],
                            source=meta["source"], source_url=meta["source_url"],
                            license=meta["license"], date=meta["date"])
    if candidate.source in ("jamendo", "ccmixter"):
        dest = cache / f"{key}.mp3"
        catalog.http_download(candidate.ref, dest)
        path = dest
    else:                                        # youtube / itunes / deezer → yt-dlp (any lane)
        target = candidate.ref if candidate.source == "youtube" else f"ytsearch1:{candidate.ref}"
        _log(f"music_fetch: mode=any: downloading COPYRIGHTED audio via yt-dlp from "
             f"{target!r}. Licensing/rights are the user's responsibility and "
             f"jurisdiction-dependent (recorded in {sidecar.name}).")
        proc = subprocess.run(
            catalog.ytdlp_cmd() + ["-f", "bestaudio", "-o", str(cache / f"{key}.%(ext)s"),
                                   "--no-warnings", target],
            capture_output=True, text=True)
        if proc.returncode != 0:
            raise ValueError(f"music sourcing: yt-dlp download failed ({proc.stderr.strip()})")
        path = _cached(cache, key)
        if path is None:
            raise ValueError(f"music sourcing: yt-dlp produced no file for {target}")
    track = FetchedTrack(path=str(path), title=candidate.title, artist=candidate.artist,
                         source=candidate.source, source_url=candidate.ref,
                         license=candidate.license, date=date)
    sidecar.write_text(json.dumps(track.sidecar(), indent=2))
    return track
