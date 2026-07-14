# scripts/music_fetch.py
"""music sourcing — fetch (design §5): resolve a picked shortlist row (or an explicit
--track name) to a cached audio file + sidecar via scripts/lib/fetch. Prints the cached
path; the SKILL then runs `beats --auto-start` on it for MUSIC.json."""
import argparse
from pathlib import Path
import json

from scripts.lib import catalog, fetch


def fetch_pick(shortlist: str, pick: int, mode: str, cache_dir: str, date: str) -> fetch.FetchedTrack:
    """Fetch row `pick` (1-based) from a MUSIC_SHORTLIST.json."""
    rows = json.loads(Path(shortlist).read_text()).get("candidates", [])
    if not 1 <= pick <= len(rows):
        raise ValueError(f"--pick {pick} out of range 1..{len(rows)} for {shortlist}")
    r = rows[pick - 1]
    cand = catalog.Candidate(title=r["title"], artist=r["artist"], source=r["source"],
                             ref=r["ref"], license=r["license"], preview_url=r.get("preview_url"))
    return fetch.download(cand, mode, cache_dir, date)


def fetch_named(name: str, mode: str, cache_dir: str, date: str) -> fetch.FetchedTrack:
    """Fetch an explicit track name directly (no shortlist) — resolve the top-1 in the lane."""
    return fetch.download(catalog.search(mode, name, 1)[0], mode, cache_dir, date)


def main() -> None:
    ap = argparse.ArgumentParser(description="download a sourced track → cache + sidecar")
    ap.add_argument("--mode", required=True, choices=("free", "any"))
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--from-shortlist", help="MUSIC_SHORTLIST.json to pick from")
    g.add_argument("--track", help="explicit track name to resolve directly")
    ap.add_argument("--pick", type=int, help="1-based row of --from-shortlist")
    ap.add_argument("--cache-dir", required=True, help="cache dir (e.g. <run>/music/cache)")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD stamp for the sidecar")
    a = ap.parse_args()
    if a.from_shortlist:
        if a.pick is None:
            ap.error("--from-shortlist needs --pick <row>")
        track = fetch_pick(a.from_shortlist, a.pick, a.mode, a.cache_dir, a.date)
    else:
        track = fetch_named(a.track, a.mode, a.cache_dir, a.date)
    print(track.path)


if __name__ == "__main__":
    main()
