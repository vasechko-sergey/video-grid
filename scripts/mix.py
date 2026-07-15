"""audio-mix (montage §5.12, music-only B2): build the reel's audio stem from a
MusicSpec — seek the chosen fragment, fade, two-pass loudnorm to −14 LUFS → aac.
Ambient ducking + SFX arrive when extract preserves per-episode audio (§5.8);
this signature is the stable seam for them."""
import argparse
import os
import re
import tempfile

from scripts.lib import assembly, proc
from scripts.lib.models import MusicSpec

_TARGET_LUFS = -14.0                                  # EBU R128 (montage §5.12)
_TP_MAX = -1.5                                         # true-peak ceiling (dBTP)
_LRA_TARGET = 11                                       # loudness range target
_FADE = 0.5


def _measure(audio: str) -> dict[str, str]:
    """loudnorm analysis pass → the measured stats the accurate second pass needs."""
    r = proc.run(["ffmpeg", "-i", audio, "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    err = (r.stderr or b"").decode("utf-8", errors="replace")
    stats = {}
    for k in ("input_i", "input_tp", "input_lra", "input_thresh"):
        m = re.search(rf'"{k}"\s*:\s*"?(-?\d+\.?\d*)"?', err)
        if not m:
            raise RuntimeError(f"loudnorm printed no {k} for {audio} — cannot run the accurate "
                               "second pass; the chosen fragment may be silent")
        stats[k] = m.group(1)
    return stats


_AR = 48000            # ambient bed sample rate (uniform for -c copy concat)


def _has_audio(path: str) -> bool:
    """True iff `path` has at least one audio stream (a video-only segment does not)."""
    r = proc.run(["ffprobe", "-v", "error", "-select_streams", "a",
                  "-show_entries", "stream=codec_name", "-of", "default=nk=1:nw=1", path])
    return bool(r.stdout.decode("utf-8", errors="replace").strip())


def _build_ambient(segments: list[tuple[str, float]], tmp_dir: str) -> str | None:
    """Concatenate each raw segment's audio, trimmed/padded to its final episode dur
    and ordered as given (EDL order), into one reel-length ambient bed. A segment with
    no audio stream contributes anullsrc silence so the bed stays in sync with the
    picture. Returns the bed wav path, or None when EVERY segment is silent (→ mix
    falls back to the music-only stem). Uniform 48 kHz stereo s16 so assembly.concat
    (-c copy) joins them losslessly."""
    beds: list[str] = []
    any_audio = False
    for i, (seg, dur) in enumerate(segments):
        bed = os.path.join(tmp_dir, f"amb_{i:03d}.wav")
        if _has_audio(seg):
            any_audio = True
            # audio seek exempt from the -ss-after-i rule; re-encode from 0, apad the
            # tail then -t caps → exactly `dur`, uniform 48k/stereo/s16.
            proc.run(["ffmpeg", "-y", "-i", seg, "-t", f"{dur}", "-vn", "-ac", "2",
                      "-ar", str(_AR), "-af", "apad", "-c:a", "pcm_s16le", bed])
        else:
            proc.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                      f"anullsrc=r={_AR}:cl=stereo", "-t", f"{dur}",
                      "-c:a", "pcm_s16le", bed])
        beds.append(bed)
    if not any_audio:
        return None
    return assembly.concat(beds, os.path.join(tmp_dir, "ambient.wav"))


def mix(music: MusicSpec, out_dir: str, dur: float) -> str:
    """Music-only audio stem for a `dur`-second reel → out_dir/audio.m4a (aac, −14 LUFS)."""
    if dur <= 0:
        raise ValueError(f"mix: dur must be positive, got {dur}")
    if dur > music.duration + 0.1:
        raise ValueError(f"mix: reel dur {dur}s exceeds the analyzed music window {music.duration}s "
                         f"(track={music.track}, start_offset={music.start_offset}) — analyze a longer "
                         "window or shorten the reel; a shorter stem would silently desync from the video")
    if dur < 2 * _FADE:
        raise ValueError(f"mix: dur {dur}s is shorter than the two {_FADE}s fades (they would overlap) — "
                         "use a longer reel or a shorter _FADE")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "audio.m4a")
    with tempfile.TemporaryDirectory() as d:
        frag = os.path.join(d, "frag.wav")
        # accurate-seek the fragment (audio seek is exempt from the frame-accurate-video
        # landmine, but placed exactly), trim to the reel length, fade in/out
        proc.run(["ffmpeg", "-y", "-accurate_seek", "-ss", f"{music.start_offset}",
                  "-i", music.track, "-t", f"{dur}",
                  "-af", f"afade=t=in:st=0:d={_FADE},afade=t=out:st={max(0.0, dur - _FADE)}:d={_FADE}",
                  frag])
        st = _measure(frag)
        proc.run(["ffmpeg", "-y", "-i", frag, "-af",
                  (f"loudnorm=I={_TARGET_LUFS}:TP={_TP_MAX}:LRA={_LRA_TARGET}:"
                   f"measured_I={st['input_i']}:measured_TP={st['input_tp']}:"
                   f"measured_LRA={st['input_lra']}:measured_thresh={st['input_thresh']}"),
                  "-c:a", "aac", "-b:a", "192k", out])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="build the reel audio stem from MUSIC.json")
    ap.add_argument("music", help="MUSIC.json path")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--dur", type=float, required=True, help="reel length (seconds)")
    a = ap.parse_args()
    print(mix(MusicSpec.from_json(a.music), a.out_dir, a.dur))


if __name__ == "__main__":
    main()
