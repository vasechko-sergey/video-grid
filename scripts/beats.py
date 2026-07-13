"""music-and-mood (montage §5.5, lean B1): analyse a local track → MusicSpec
(tempo + reel-relative beat grid + coarse RMS energy). librosa imports lazily
(§5.5 — heavy, keep test collection fast). CLI writes MUSIC.json."""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from scripts.lib import offset, vocals
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


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def choose_offset(track: str, duration: float, *, use_vocals: bool = True) -> float:
    """Auto-pick MusicSpec.start_offset (design §4): the strongest duration-window
    whose start lands in a vocal pause. demucs vocal path when available+use_vocals,
    else a logged full-mix silence proxy. Emits one stderr info line."""
    import librosa                                    # lazy import: heavy optional dep (librosa)
    y, sr = librosa.load(track, sr=None, mono=True)
    track_dur = len(y) / sr
    if track_dur <= duration:
        _log(f"choose_offset: 0.00s (track {track_dur:.1f}s <= reel {duration:.1f}s — whole track)")
        return 0.0
    mix_rms = librosa.feature.rms(y=y, hop_length=offset.HOP)[0]
    mix_energy, mix_hz = offset.downsample(mix_rms, sr, offset.HOP, 2.0)
    if use_vocals and vocals.has_demucs():
        env, hz = vocals.separate_vocal_energy(track)
        gaps, path = offset.vocal_gaps(env, hz), "vocal"
    else:
        gaps, path = offset.vocal_gaps(mix_energy, mix_hz), "mix-proxy"
    off = offset.best_offset(mix_energy, mix_hz, gaps, duration, track_dur)
    extra = "" if path == "vocal" else " (demucs absent — setup.sh --with-demucs for vocal-accurate)"
    _log(f"choose_offset: {off:.2f}s via {path}{extra}")
    return off


def main() -> None:
    ap = argparse.ArgumentParser(description="analyse a track → MUSIC.json (tempo + beats + energy)")
    ap.add_argument("track")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--start-offset", type=float, default=0.0)
    g.add_argument("--auto-start", action="store_true",
                   help="auto-pick the in-point (strongest fragment, vocal-pause start); needs --duration")
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--out", required=True, help="MUSIC.json output path")
    a = ap.parse_args()
    if a.auto_start:
        if a.duration is None:
            ap.error("--auto-start needs --duration (the reel length) to size the window")
        start = choose_offset(a.track, a.duration)
    else:
        start = a.start_offset
    ms = analyze(a.track, start, a.duration)
    Path(a.out).write_text(json.dumps(ms.to_dict(), indent=2))
    print(a.out)


if __name__ == "__main__":
    main()
