"""Discovery boundary for music sourcing (design docs/specs/2026-07-14-music-sourcing-design.md,
§4). Turns a mood query into Candidates across rights lanes — `free` (ccMixter no-key /
Jamendo when keyed) and `any` (YouTube via yt-dlp, iTunes/Deezer opt-in). All network is
isolated in per-source helpers (stdlib urllib for JSON, a yt-dlp module subprocess for
YouTube) so the ranking driver and the mood engine never touch the transport."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

SOURCES = ("jamendo", "ccmixter", "youtube", "itunes", "deezer")

_UA = "video-grid/1.0 (music sourcing)"       # some catalog APIs 403 an empty User-Agent
_TIMEOUT = 20
_SOURCING_ENV = Path(__file__).resolve().parents[2] / "config" / "sourcing.env"  # repo-root/config


@dataclass(frozen=True)
class Candidate:
    title: str
    artist: str
    source: str                 # ∈ SOURCES
    ref: str                    # source-native id/url fetch resolves against
    license: str
    preview_url: str | None     # HTTP-fetchable 30s clip, or None → yt-dlp section

    def __post_init__(self) -> None:
        for name in ("title", "artist", "source", "ref", "license"):
            v = getattr(self, name)
            if not (isinstance(v, str) and v.strip()):
                raise ValueError(f"Candidate.{name} must be a non-empty string, got {v!r}")
        if self.source not in SOURCES:
            raise ValueError(f"Candidate.source {self.source!r} not in {SOURCES}")
        if self.preview_url is not None and not (isinstance(self.preview_url, str)
                                                 and self.preview_url.strip()):
            raise ValueError(f"Candidate.preview_url must be a non-empty string or None, "
                             f"got {self.preview_url!r}")

    def slug(self) -> str:
        raw = f"{self.source}-{self.artist}-{self.title}".lower()
        return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:80] or "track"

    def to_dict(self) -> dict:
        return {"title": self.title, "artist": self.artist, "source": self.source,
                "ref": self.ref, "license": self.license, "preview_url": self.preview_url}

    @classmethod
    def from_dict(cls, d: dict) -> "Candidate":
        missing = [k for k in ("title", "artist", "source", "ref", "license") if k not in d]
        if missing:
            raise ValueError(f"Candidate.from_dict missing key(s) {missing} — a candidate "
                             f"needs title, artist, source, ref, license")
        return cls(title=d["title"], artist=d["artist"], source=d["source"], ref=d["ref"],
                   license=d["license"], preview_url=d.get("preview_url"))


def has_ytdlp() -> bool:
    """True if the yt-dlp module is importable in this interpreter (the any-lane gate).
    Mirrors vocals.has_demucs — a spec probe, invoked as a module so the venv's copy is
    found regardless of PATH."""
    return importlib.util.find_spec("yt_dlp") is not None


def ytdlp_cmd() -> list[str]:
    """The base yt-dlp invocation ([python, -m, yt_dlp]); raises the fail-loud remedy when
    yt-dlp is absent (callers may gate on has_ytdlp() first — defense-in-depth)."""
    if not has_ytdlp():
        raise ValueError("yt-dlp is not installed — install it with "
                         "`bash setup.sh --with-sourcing` (opt-in; the any lane needs it)")
    return [sys.executable, "-m", "yt_dlp"]


def _jamendo_client_id() -> str | None:
    """The Jamendo client_id from $JAMENDO_CLIENT_ID, else the gitignored config/sourcing.env
    that setup.sh writes. A public read-only app id, not a secret — but per-user."""
    cid = os.environ.get("JAMENDO_CLIENT_ID")
    if cid:
        return cid
    if _SOURCING_ENV.exists():
        for line in _SOURCING_ENV.read_text().splitlines():
            if line.startswith("JAMENDO_CLIENT_ID="):
                return line.split("=", 1)[1].strip() or None
    return None


def _free_source() -> str:
    """Resolve the free-lane catalog: Jamendo when a client_id is configured, else the
    no-key ccMixter fallback. Never a hard fail — the free lane must not dead-end."""
    return "jamendo" if _jamendo_client_id() else "ccmixter"


def _get_json(url: str) -> dict | list:
    """GET a URL → parsed JSON (dict or list). Raises ValueError on any transport/parse
    error (fail loud — the driver surfaces it; never a silent empty shortlist)."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        raise ValueError(f"music sourcing: request to {url} failed ({e}) — "
                         f"check the network / that the catalog is reachable") from e


def http_download(url: str, dest: Path) -> None:
    """Stream a URL to `dest` (the free-lane direct download + the HTTP preview path)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp, open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
    except (urllib.error.URLError, TimeoutError) as e:
        raise ValueError(f"music sourcing: download of {url} failed ({e})") from e


def _search_itunes(query: str, n: int) -> list[Candidate]:
    url = ("https://itunes.apple.com/search?"
           + urllib.parse.urlencode({"term": query, "entity": "song", "limit": n}))
    out = []
    for r in _get_json(url).get("results", []):
        title, artist = r.get("trackName"), r.get("artistName")
        if not (title and artist):
            continue
        out.append(Candidate(title=title, artist=artist, source="itunes",
                             ref=f"{artist} - {title}", license="unknown (any lane)",
                             preview_url=r.get("previewUrl")))
    return out


def _search_deezer(query: str, n: int) -> list[Candidate]:
    url = "https://api.deezer.com/search?" + urllib.parse.urlencode({"q": query, "limit": n})
    out = []
    for r in _get_json(url).get("data", []):
        title, artist = r.get("title"), (r.get("artist") or {}).get("name")
        if not (title and artist):
            continue
        out.append(Candidate(title=title, artist=artist, source="deezer",
                             ref=f"{artist} - {title}", license="unknown (any lane)",
                             preview_url=r.get("preview")))
    return out


def _search_jamendo(query: str, n: int) -> list[Candidate]:
    cid = _jamendo_client_id()
    if not cid:
        raise ValueError("_search_jamendo needs a Jamendo client_id — set JAMENDO_CLIENT_ID "
                         "or run `bash setup.sh --with-sourcing` (else the ccMixter fallback runs)")
    url = ("https://api.jamendo.com/v3.0/tracks/?"
           + urllib.parse.urlencode({"client_id": cid, "format": "json", "limit": n,
                                     "fuzzytags": query, "audioformat": "mp32",
                                     "include": "musicinfo licenses"}))
    out = []
    for r in _get_json(url).get("results", []):
        title, artist = r.get("name"), r.get("artist_name")
        dl = r.get("audiodownload") or r.get("audio")
        if not (title and artist and dl):
            continue
        out.append(Candidate(title=title, artist=artist, source="jamendo", ref=dl,
                             license=r.get("license_ccurl") or "Creative Commons (Jamendo)",
                             preview_url=r.get("audio")))
    return out


def _search_ccmixter(query: str, n: int) -> list[Candidate]:
    url = ("http://dig.ccmixter.org/api/query?"
           + urllib.parse.urlencode({"f": "json", "limit": n, "tags": query}))
    data = _get_json(url)
    out = []
    for r in (data if isinstance(data, list) else []):
        title, artist = r.get("upload_name"), r.get("user_name")
        files = r.get("files") or []
        dl = files[0].get("download_url") if files else None
        if not (title and artist and dl):
            continue
        out.append(Candidate(title=title, artist=artist, source="ccmixter", ref=dl,
                             license=r.get("license_name") or "Creative Commons (ccMixter)",
                             preview_url=dl))
    return out


def _search_youtube(query: str, n: int) -> list[Candidate]:
    proc = subprocess.run(
        ytdlp_cmd() + [f"ytsearch{n}:{query}", "--flat-playlist", "--dump-json", "--no-warnings"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise ValueError(f"music sourcing: yt-dlp search failed ({proc.stderr.strip()})")
    out = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        title = r.get("title")
        ref = r.get("webpage_url") or r.get("url") or r.get("id")
        if not (title and ref):
            continue
        out.append(Candidate(title=title, artist=r.get("channel") or r.get("uploader") or "unknown",
                             source="youtube", ref=ref, license="unknown (any lane)",
                             preview_url=None))
    return out


def search(mode: str, query: str, n: int, catalog: str | None = None) -> list[Candidate]:
    """Discovery across rights lanes (design §4). `free` → _free_source() (ccMixter / Jamendo);
    `any` → YouTube by default, or `catalog` in {itunes, deezer}. Rights invariant: the free
    branch only ever calls the CC catalogs, never YouTube. Zero results raises."""
    if mode == "free":
        if catalog is not None:
            raise ValueError(f"--catalog {catalog!r} is an any-lane option; the free lane "
                             f"uses the CC catalogs — drop --catalog, or use --mode any")
        cands = (_search_jamendo(query, n) if _free_source() == "jamendo"
                 else _search_ccmixter(query, n))
    elif mode == "any":
        if catalog == "itunes":
            cands = _search_itunes(query, n)
        elif catalog == "deezer":
            cands = _search_deezer(query, n)
        elif catalog in (None, "youtube"):
            cands = _search_youtube(query, n)
        else:
            raise ValueError(f"--catalog {catalog!r} not in (youtube, itunes, deezer)")
    else:
        raise ValueError(f"music sourcing mode {mode!r} not in (free, any) — "
                         f"local is the music-match lane, not sourcing")
    if not cands:
        raise ValueError(f"music sourcing: no candidates for {query!r} (mode={mode}) — "
                         f"try a different --query or --mood")
    return cands


def preview_clip(candidate: Candidate, cache_dir: str) -> str:
    """Materialise a ~30 s clip for mood analysis, source-appropriately (design §4): an
    HTTP preview_url via GET, else a yt-dlp 0:00–0:30 section. Returns the clip path."""
    cache = Path(cache_dir); cache.mkdir(parents=True, exist_ok=True)
    slug = candidate.slug()
    if candidate.preview_url:
        dest = cache / f"{slug}.preview.mp3"
        http_download(candidate.preview_url, dest)
        return str(dest)
    proc = subprocess.run(
        ytdlp_cmd() + ["-f", "bestaudio", "--download-sections", "*0:00-0:30",
                       "-o", str(cache / f"{slug}.preview.%(ext)s"), "--no-warnings",
                       candidate.ref],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise ValueError(f"music sourcing: yt-dlp preview failed ({proc.stderr.strip()})")
    hits = sorted(cache.glob(f"{slug}.preview.*"))
    if not hits:
        raise ValueError(f"music sourcing: yt-dlp produced no preview for {candidate.ref}")
    return str(hits[0])
