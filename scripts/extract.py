"""Cut an EDL window into a standalone fragment (spec §5.8, §12)."""
import argparse, subprocess


def extract(src, start, dur, out, crf=18):
    # output-seek (-ss after -i) + re-encode → frame-accurate, no black frames.
    # Audio is PRESERVED (spec §5.8): segments are the ambient bed for audio-mix;
    # sources without an audio stream simply produce video-only segments.
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-ss", f"{start}", "-t", f"{dur}",
        "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--dur", type=float, required=True)
    a = ap.parse_args()
    extract(a.src, a.start, a.dur, a.out)
