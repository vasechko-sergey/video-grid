"""music-and-mood (montage §5.5, lean B1): analyse a local track → MusicSpec
(tempo + reel-relative beat grid + coarse RMS energy). librosa imports lazily
(§5.5 — heavy, keep test collection fast). CLI writes MUSIC.json."""
import argparse
import json
from pathlib import Path

import numpy as np

from scripts.lib import offset
from scripts.lib.models import MusicSpec

_HOP = offset.HOP                                     # kept as a module name for analyze() below
_downsample = offset.downsample                       # relocated to scripts/lib/offset.py


def analyze(track: str, start_offset: float = 0.0, duration: float | None = None) -> MusicSpec:
    """Analyse track's [start_offset, start_offset+duration] window → MusicSpec.
    Beats come out reel-relative (0.0 = window start) so they compare directly to
    reel cut times. duration=None analyses to the end of the track."""
    import librosa                                    # lazy import: heavy optional dep (librosa)
    y, sr = librosa.load(track, sr=None, offset=start_offset, duration=duration)
    dur = float(len(y) / sr)
    tempo, frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=_HOP, units="frames")
    tempo = float(np.atleast_1d(tempo)[0])            # librosa >=0.10 returns tempo as an array
    beats = tuple(float(t) for t in librosa.frames_to_time(frames, sr=sr, hop_length=_HOP)
                  if 0.0 <= t <= dur)
    rms = librosa.feature.rms(y=y, hop_length=_HOP)[0]
    energy, energy_hz = _downsample(rms, sr, _HOP, target_hz=2.0)   # ~2 Hz coarse curve — small MUSIC.json, B4-ready (design §3)
    return MusicSpec(track=track, start_offset=float(start_offset), duration=dur,
                     tempo=tempo, beats=beats, energy=tuple(energy), energy_hz=energy_hz)


def main() -> None:
    ap = argparse.ArgumentParser(description="analyse a track → MUSIC.json (tempo + beats + energy)")
    ap.add_argument("track")
    ap.add_argument("--start-offset", type=float, default=0.0)
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--out", required=True, help="MUSIC.json output path")
    a = ap.parse_args()
    ms = analyze(a.track, a.start_offset, a.duration)
    Path(a.out).write_text(json.dumps(ms.to_dict(), indent=2))
    print(a.out)


if __name__ == "__main__":
    main()
