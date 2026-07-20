"""Assemble-draft (montage §5.9): render a QA-preview draft.mp4 from an EDL.json +
project.json — the extracted raw segments, scale-fit into the SPEC canvas, labelled
with each episode's processing_notes, over a rough music bed. The human eyeballs
layout / order / length / beat-landing at the §4.1 CP2 checkpoint before the
expensive process-episode pass. The draft sibling of scripts/assemble.py, over the
shared lib/assembly concat core; the pure label/fit helpers live in lib/draft.py."""
import argparse
import json
from pathlib import Path

from scripts import extract, mix
from scripts.lib import assembly, ffbin, proc
from scripts.lib.draft import label_text, resolve_font, segment_filter
from scripts.lib.edl import EDL
from scripts.lib.models import MusicSpec
from scripts.lib.project import ProjectConfig


def ensure_drawtext() -> None:
    """Fail loud if the resolved ffmpeg lacks drawtext — the draft label burn needs
    it, and a missing filter otherwise surfaces as a cryptic 'No such filter:
    drawtext' mid-render."""
    ffbin.require_filter(
        "drawtext",
        "the draft labels need it. Run `bash setup.sh`, which installs ffmpeg-full "
        "(libfreetype included)")


def build_draft(edl_path: str, project_path: str, footage_root: str, work_dir: str,
                out: str, *, music: str | None = None, font: str | None = None) -> dict:
    """EDL.json + project.json -> a QA-preview draft.mp4. Extract each window, burn a
    canvas-fit + processing_notes label into every segment, concat, then mux a rough
    music bed (reusing mix.mix — one source of truth for laying music; absent -> a
    silent draft). Returns {"status": "written", "draft", "episodes", "music"}."""
    ensure_drawtext()
    edl = EDL.from_json(edl_path)
    cfg = ProjectConfig.from_json(project_path)
    dims = cfg.canvas
    fontfile = resolve_font(font)
    work = Path(work_dir)
    seg_dir = str(work / "segments")
    segments = extract.extract_edl(edl, footage_root, seg_dir)
    fps = assembly.probe_stream(segments[0]).fps

    labels_dir, burn_dir = work / "labels", work / "burned"
    labels_dir.mkdir(parents=True, exist_ok=True)
    burn_dir.mkdir(parents=True, exist_ok=True)
    burned: list[str] = []
    for i, (ep, seg) in enumerate(zip(edl.episodes, segments)):
        tf = labels_dir / f"label_{i}.txt"
        tf.write_text(label_text(i, ep.shot_type, ep.processing_notes))
        vf = segment_filter(dims, fps, fontfile, str(tf))
        bout = str(burn_dir / f"ep{i}_draft.mp4")
        proc.run(["ffmpeg", "-y", "-i", seg, "-vf", vf,
                  "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-an", bout])
        burned.append(bout)

    master = str(work / "draft_master.mp4")
    assembly.concat(burned, master)
    Path(out).parent.mkdir(parents=True, exist_ok=True)

    src = music or edl.music
    if src is None:
        proc.run(["ffmpeg", "-y", "-i", master, "-c", "copy", out])
    else:
        dur = assembly.probe_duration(master)
        audio = mix.mix(MusicSpec.from_json(src), str(work / "audio"), dur)
        proc.run(["ffmpeg", "-y", "-i", master, "-i", audio,
                  "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "copy",
                  "-shortest", out])
    return {"status": "written", "draft": out,
            "episodes": len(edl.episodes), "music": src is not None}


def main() -> None:
    ap = argparse.ArgumentParser(description="render a QA-preview draft.mp4 (montage §5.9)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build draft.mp4 from an EDL.json + project.json")
    b.add_argument("--edl", required=True)
    b.add_argument("--project", required=True, help="project.json — the SPEC canvas")
    b.add_argument("--footage-root", required=True, help="dir the EDL 'source' paths resolve against")
    b.add_argument("--work-dir", required=True, help="scratch for segments / labels / burned / master")
    b.add_argument("--out", required=True, help="draft.mp4 path (using-montage: <run-dir>/draft.mp4)")
    b.add_argument("--music", default=None, help="MUSIC.json path; overrides the EDL's music field")
    b.add_argument("--font", default=None, help="drawtext .ttf/.ttc/.otf (default: first system candidate)")
    a = ap.parse_args()
    result = build_draft(a.edl, a.project, a.footage_root, a.work_dir, a.out,
                         music=a.music, font=a.font)
    print(json.dumps(result, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
