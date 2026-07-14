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
                    query: str | None = None, cat: str | None = None) -> dict:
    """Discover n candidates (per rights lane), rank by fit to mood_text, write
    MUSIC_SHORTLIST.{json,md} in out_dir. Zero candidates raises (in catalog.search); an
    unknown mood logs and falls back to drive-ranking (never silent)."""
    cands = catalog.search(mode, query or mood_text, n, catalog=cat)
    by_slug = {c.slug(): c for c in cands}
    with tempfile.TemporaryDirectory() as clips:
        pairs = [(c.slug(), beats.mood_features(catalog.preview_clip(c, clips))) for c in cands]
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
    for slug, score, v in ranked:
        c = by_slug[slug]
        row = {"title": c.title, "artist": c.artist, "source": c.source, "ref": c.ref,
               "license": c.license, "preview_url": c.preview_url, "vector": v.to_dict()}
        if head["fallback"] == "drive":
            row["drive"] = round(score, 4)
        else:
            row["distance"] = round(score, 4)
            row["fit"] = round(1.0 / (1.0 + score), 4)
        rows.append(row)
    payload = {"mood_text": mood_text, "mode": mode, **head, "candidates": rows}
    out = Path(out_dir)
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
             "| # | title | artist | source | fit | energy | brightness | pace | license |",
             "|--:|-------|--------|--------|----:|-------:|-----------:|-----:|---------|"]
    for i, c in enumerate(payload["candidates"], 1):
        v = c["vector"]
        fit = f"{c['fit']:.2f}" if "fit" in c else f"drive {c['drive']:.2f}"
        lines.append(f"| {i} | {c['title']} | {c['artist']} | {c['source']} | {fit} | "
                     f"{v['energy']:.2f} | {v['brightness']:.2f} | {v['pace']:.2f} | {c['license']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="source candidate tracks by mood → MUSIC_SHORTLIST.{json,md}")
    ap.add_argument("--mode", required=True, choices=("free", "any"),
                    help="rights lane (free = CC; any = incl. copyrighted via yt-dlp)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--spec", help="SPEC.json — reads its mood field")
    g.add_argument("--mood", help="mood text directly (e.g. 'energetic')")
    ap.add_argument("--query", help="override the catalog search query (default: the mood text)")
    ap.add_argument("--n", type=int, default=8, help="candidate count (default 8)")
    ap.add_argument("--catalog", choices=("youtube", "itunes", "deezer"),
                    help="any-lane catalog (default youtube)")
    ap.add_argument("--out-dir", required=True, help="where to write MUSIC_SHORTLIST.{json,md}")
    a = ap.parse_args()
    mood_text = Spec.from_json(a.spec).mood if a.spec else a.mood
    res = build_shortlist(a.mode, mood_text, a.out_dir, n=a.n, query=a.query, cat=a.catalog)
    print(res["json"])
    print(res["md"])


if __name__ == "__main__":
    main()
