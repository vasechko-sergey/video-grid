"""music-and-mood selection (design docs/specs/2026-07-13-mood-match-design.md, §5.5
local lane): rank a folder of candidate tracks by fit to SPEC.mood → MUSIC_SHORTLIST.
The agent picks the top row, then `beats --auto-start` produces MUSIC.json. A thin
driver over the pure scripts/lib/mood.py core + beats.mood_features (librosa extractor)."""
import argparse
import json
import sys
from pathlib import Path

from scripts import beats
from scripts.lib import mood
from scripts.lib.spec import Spec

AUDIO_EXT = (".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg")


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def build_shortlist(folder: str, mood_text: str, out_dir: str) -> dict:
    """Rank the audio files in `folder` by fit to `mood_text` → MUSIC_SHORTLIST.{json,md}
    in out_dir. Returns {"json": path, "md": path, "ranked": [...]}. Empty folder raises;
    a mood matching no anchor logs and falls back to drive-ranking (never silent)."""
    tracks = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in AUDIO_EXT)
    if not tracks:
        raise ValueError(f"no audio files ({'/'.join(AUDIO_EXT)}) in {folder} — "
                         f"point --folder at a folder of candidate tracks")
    cands = [(p.name, beats.mood_features(str(p))) for p in tracks]
    target = mood.mood_target(mood_text)
    if target is None:
        _log(f"mood-match: '{mood_text}' matched no mood anchor "
             f"({', '.join(sorted(mood.MOOD_ANCHORS))}) — ranking by drive (energy+pace)")
        ranked = mood.rank_by_drive(cands)
        head = {"target": None, "fallback": "drive"}
        cand_json = [{"track": n, "drive": round(s, 4), "vector": v.to_dict()}
                     for n, s, v in ranked]
    else:
        ranked = mood.rank(cands, target)
        head = {"target": target.to_dict(), "fallback": None}
        cand_json = [{"track": n, "distance": round(s, 4), "fit": round(1.0 / (1.0 + s), 4),
                      "vector": v.to_dict()} for n, s, v in ranked]
    payload = {"mood_text": mood_text, **head, "candidates": cand_json}
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
    lines = [f"# Music shortlist — mood: {payload['mood_text']}", "", sub, "",
             "| # | track | fit | energy | brightness | pace |",
             "|--:|-------|----:|-------:|-----------:|-----:|"]
    for i, c in enumerate(payload["candidates"], 1):
        v = c["vector"]
        fit = f"{c['fit']:.2f}" if "fit" in c else f"drive {c['drive']:.2f}"
        lines.append(f"| {i} | {c['track']} | {fit} | {v['energy']:.2f} | "
                     f"{v['brightness']:.2f} | {v['pace']:.2f} |")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="rank a folder of tracks by mood-fit → MUSIC_SHORTLIST.{json,md}")
    ap.add_argument("--folder", required=True, help="folder of candidate audio tracks")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--spec", help="SPEC.json — reads its mood field")
    g.add_argument("--mood", help="mood text directly (e.g. 'energetic')")
    ap.add_argument("--out-dir", required=True, help="where to write MUSIC_SHORTLIST.{json,md}")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    mood_text = Spec.from_json(a.spec).mood if a.spec else a.mood
    res = build_shortlist(a.folder, mood_text, a.out_dir)
    print(res["json"])
    print(res["md"])


if __name__ == "__main__":
    main()
