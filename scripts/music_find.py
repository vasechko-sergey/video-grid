# scripts/music_find.py
"""music sourcing — find (design §4): query a catalog by SPEC.mood, mood-analyse each
candidate's preview locally (beats.mood_features + the pure mood.rank core), write
MUSIC_SHORTLIST.{json,md} for the agent to pick from. A thin driver over scripts/lib/catalog
(the network boundary) + scripts/lib/mood (the pure scorer) — the same ranking as the local
lane, candidates just come from the network instead of a folder."""
import argparse
import json
import sys
import tempfile
from pathlib import Path

from scripts import beats
from scripts.lib import catalog, mood
from scripts.lib.spec import Spec


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def build_shortlist(mode: str, mood_text: str, out_dir: str, *, n: int = 8,
                    query: str | None = None, cat: str | None = None,
                    popular: bool = False) -> dict:
    """Discover n candidates (per rights lane), rank by fit to mood_text, write
    MUSIC_SHORTLIST.{json,md} in out_dir. Zero candidates raises (in catalog.search); an
    unknown mood logs and falls back to drive-ranking (never silent)."""
    if query is not None:
        search_query = query                         # --query overrides verbatim
    elif mode == "free":
        search_query = f"{mood_text} instrumental"   # §4.1 free-lane stylistic hint
    else:
        search_query = mood_text
    if popular and mode == "any" and cat is None:
        # Known tracks: Deezer orders a search by its own ranking and ships 30 s previews.
        # The second real run's brief asked for "any" music and got niche artists, ranked
        # by mood fit alone (retro 2026-10-16 S8).
        cat = "deezer"
    cands = catalog.search(mode, search_query, n, catalog=cat, popular=popular)
    with tempfile.TemporaryDirectory() as clips:
        pairs = []
        for i, c in enumerate(cands):
            sub = Path(clips) / str(i)      # per-candidate subdir: same-slug previews never collide
            sub.mkdir()
            pairs.append((i, beats.mood_features(catalog.preview_clip(c, str(sub)))))
    target = mood.mood_target(mood_text)
    if target is None:
        _log(f"music-source: '{mood_text}' matched no mood anchor "
             f"({', '.join(sorted(mood.MOOD_ANCHORS))}) — ranking by drive (energy+pace)")
        ranked = mood.rank_by_drive(pairs)
        head = {"target": None, "fallback": "drive"}
    else:
        ranked = mood.rank(pairs, target)
        head = {"target": target.to_dict(), "fallback": None}
    rows = []
    for i, score, v in ranked:      # key by index, not slug — dup-slug rows must not cross-attribute
        c = cands[i]
        row = {"title": c.title, "artist": c.artist, "source": c.source, "ref": c.ref,
               "license": c.license, "preview_url": c.preview_url, "vector": v.to_dict(),
               "popularity": c.popularity}
        if head["fallback"] == "drive":
            row["drive"] = round(score, 4)
        else:
            row["distance"] = round(score, 4)
            row["fit"] = round(1.0 / (1.0 + score), 4)
        rows.append(row)
    if popular and not any(r["popularity"] is not None for r in rows):
        # the free lane and iTunes carry no popularity — say so rather than label a fit
        # order "sorted by popularity" over a column of dashes
        _log(f"music-source: --popular asked, but this {mode}/{cat or 'default'} search "
             f"carries no popularity number — the list stays in mood-fit order")
        popular = False
    if popular:
        # most popular first; the mood fit stays in every row so the agent can weigh both
        rows.sort(key=lambda r: -(r["popularity"] if r["popularity"] is not None else -1.0))
    payload = {"mood_text": mood_text, "mode": mode, **head,
               "sort": "popularity" if popular else "fit", "candidates": rows}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out / "MUSIC_SHORTLIST.json", out / "MUSIC_SHORTLIST.md"
    json_path.write_text(json.dumps(payload, indent=2))
    md_path.write_text(_to_markdown(payload))
    return {"json": str(json_path), "md": str(md_path), "ranked": ranked}


def _to_markdown(payload: dict) -> str:
    if payload["fallback"] == "drive":
        sub = "_no mood anchor matched — ranked by drive (energy+pace)_"
    else:
        t = payload["target"]
        sub = (f"_target: energy {t['energy']:.2f} · brightness {t['brightness']:.2f} "
               f"· pace {t['pace']:.2f}_")
    lines = [f"# Music shortlist — mood: {payload['mood_text']} (mode: {payload['mode']})",
             "", sub, "",
             f"_sorted by {payload.get('sort', 'fit')}_", "",
             "| # | title | artist | source | fit | popularity | energy | brightness | pace | license |",
             "|--:|-------|--------|--------|----:|-----------:|-------:|-----------:|-----:|---------|"]
    for i, c in enumerate(payload["candidates"], 1):
        v = c["vector"]
        fit = f"{c['fit']:.2f}" if "fit" in c else f"drive {c['drive']:.2f}"
        pop = f"{c['popularity']:,.0f}" if c.get("popularity") is not None else "–"
        lines.append(f"| {i} | {c['title']} | {c['artist']} | {c['source']} | {fit} | {pop} | "
                     f"{v['energy']:.2f} | {v['brightness']:.2f} | {v['pace']:.2f} | {c['license']} |")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="source candidate tracks by mood → MUSIC_SHORTLIST.{json,md}")
    ap.add_argument("--mode", required=True, choices=("free", "any"),
                    help="rights lane (free = CC; any = incl. copyrighted via yt-dlp)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--spec", help="SPEC.json — reads its mood, and music_known "
                                  "(which implies --popular)")
    g.add_argument("--mood", help="mood text directly (e.g. 'energetic')")
    ap.add_argument("--query", help="override the catalog search query (default: the mood text)")
    ap.add_argument("--n", type=int, default=8, help="candidate count (default 8)")
    ap.add_argument("--catalog", choices=("youtube", "itunes", "deezer"),
                    help="any-lane catalog (default youtube)")
    ap.add_argument("--popular", action="store_true",
                    help="known tracks first: search Deezer by its own ranking (the any "
                         "lane's default catalog when this is set) and sort by popularity. "
                         "Implied by SPEC.music_known with --spec")
    ap.add_argument("--out-dir", required=True, help="where to write MUSIC_SHORTLIST.{json,md}")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    sp = Spec.from_json(a.spec) if a.spec else None
    mood_text = sp.mood if sp else a.mood
    res = build_shortlist(a.mode, mood_text, a.out_dir, n=a.n, query=a.query, cat=a.catalog,
                          popular=a.popular or bool(sp and sp.music_known))
    print(res["json"])
    print(res["md"])


if __name__ == "__main__":
    main()
