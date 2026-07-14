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


def _get_json(url: str):
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
