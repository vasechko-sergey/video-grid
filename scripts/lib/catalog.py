"""Discovery boundary for music sourcing (design docs/specs/2026-07-14-music-sourcing-design.md,
§4). Turns a mood query into Candidates across rights lanes — `free` (ccMixter no-key /
Jamendo when keyed) and `any` (YouTube via yt-dlp, iTunes/Deezer opt-in). All network is
isolated in per-source helpers (stdlib urllib for JSON, a yt-dlp module subprocess for
YouTube) so the ranking driver and the mood engine never touch the transport."""
import re
from dataclasses import dataclass

SOURCES = ("jamendo", "ccmixter", "youtube", "itunes", "deezer")


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
