"""music-and-mood (montage §5.5, lean B1): analyse a local track → MusicSpec
(tempo + reel-relative beat grid + coarse RMS energy). librosa imports lazily
(§5.5 — heavy, keep test collection fast). CLI writes MUSIC.json."""
import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from scripts.lib import ffbin, mood, offset, outro, proc, vocals
from scripts.lib.models import MusicSpec

_HOP = offset.HOP                                     # kept as a module name for analyze() below
_downsample = offset.downsample                       # relocated to scripts/lib/offset.py

_LOW_HZ = 60.0                 # kick band edge. 2026-08-14 measured 150 on one cell of one
                               # track; 2026-08-17 swept 8 edges x 4 windows over 5 tracks and
                               # found 150 sits on a knife edge (hit-rate 32/88/59% across
                               # +/-0.05/0.10/0.15) where 60 holds a plateau (91/93/93%) at a
                               # higher margin (2.04 vs 1.67). Still tuned on ONE track — the
                               # other four have no downbeat signal to vote with (design §2).
_BAR_WIN = 0.10                # +/- seconds sampled around each beat
_PHASE_MARGIN = 1.5            # winner/runner-up below this -> no bar grid. Measured over 124
                               # sliding 30s+42s windows (design §5): of 97 windows from four
                               # tracks with NO downbeat, none reaches 1.5 — but five reach
                               # 1.31-1.35, so 1.3 would pass noise. Costs ~1 control window
                               # in 6, which is the right side of the trade.
_MIN_BEATS_FOR_BARS = 8        # below this a per-phase mean is one or two samples
_NFFT = 2048


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
    phase = _downbeat_phase(y, sr, beats)
    bars = tuple(beats[phase::outro.BAR_BEATS]) if phase is not None else ()
    return MusicSpec(track=track, start_offset=float(start_offset), duration=dur,
                     tempo=tempo, beats=beats, energy=tuple(energy), energy_hz=energy_hz,
                     bars=bars)


def _downbeat_phase(y: np.ndarray, sr: int, beat_times: Sequence[float]) -> int | None:
    """Which of the four beat phases carries the bar's kick — the downbeat, or None.

    Peak STFT energy below _LOW_HZ in a +/-_BAR_WIN window around each beat, averaged
    per phase. The winner is returned only when it leads the runner-up by
    _PHASE_MARGIN; otherwise the four phases are too close to tell apart and None is
    the honest answer, which analyze() turns into an empty bar grid — and the outro
    fit then falls back to the beat grid under a longer fade (retro 2026-10-16 S7).

    THE GATE IS THE POINT (design 2026-08-17 §5). Measured across five real tracks,
    this detector finds a downbeat on ONE: the other four score 38-50% against a 25%
    chance level at their own best sweep cell, with margins of 1.00-1.03, and no band
    edge or window in a 32-cell sweep recovers a signal. Four-on-the-floor house puts
    a kick on every beat, so the premise — the downbeat carries the kick, the other
    beats do not — is false by construction for a whole genre family. Ungated, argmax
    returned a phase for all four, confidently.

    MEASURE THE RANKED GAP, NOT THE SPREAD. max/min does not discriminate: one track
    scored 1.782 against the control's 1.887 while landing 36% hit-rate, because one
    of its phases was quiet rather than its winner loud (§4).

    ONSET STRENGTH DOES NOT WORK HERE EITHER — the control scored 4.313 / 4.285 /
    4.267 / 4.309, all four phases inside 1%. A detector built on novelty picks a
    phase out of noise and looks like it works. Do not 'simplify' this to
    librosa.onset.

    THE TWO ZERO CORNERS ARE OPPOSITES, and the first cut of this gate collapsed
    them: a lone loud phase against three silent ones is an INFINITE lead — the
    strongest evidence there is — while all four silent is no evidence at all. Only
    the second is None. Exact zeros are reachable, not theoretical: digital silence
    gives exactly 0.0 STFT magnitude.

    None when there are fewer than _MIN_BEATS_FOR_BARS beats. Assumes 4/4 (§11.3).
    `beat_times` are relative to the START of `y`, which is what analyze() passes."""
    import librosa                                    # lazy import: heavy optional dep (librosa)
    if len(beat_times) < _MIN_BEATS_FOR_BARS:
        return None
    spec = np.abs(librosa.stft(y, n_fft=_NFFT, hop_length=_HOP))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=_NFFT)
    low = spec[freqs < _LOW_HZ].sum(axis=0)
    hz = sr / _HOP

    def peak(t: float) -> float:
        a, b = int((t - _BAR_WIN) * hz), int((t + _BAR_WIN) * hz)
        seg = low[max(a, 0):b]
        return float(seg.max()) if len(seg) else 0.0

    vals = [peak(float(t)) for t in beat_times]
    means = [float(np.mean(vals[p::outro.BAR_BEATS])) for p in range(outro.BAR_BEATS)]
    ranked = sorted(means, reverse=True)
    if ranked[0] <= 0.0:               # no bass anywhere — nothing to rank
        return None
    if ranked[1] > 0.0 and ranked[0] / ranked[1] < _PHASE_MARGIN:
        return None                    # ranked[1] == 0 is an INFINITE lead, not an absent one
    return int(np.argmax(means))


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def choose_offset(track: str, duration: float) -> float:
    """Auto-pick MusicSpec.start_offset (design §4): the strongest duration-window
    whose start lands in a vocal pause. Emits one stderr info line.

    The pauses come from the demucs vocal stem and from nothing else. Until
    2026-08-14 an absent demucs silently fell back to a full-mix silence proxy —
    deleted, because it does not fail, it answers WRONG: measured on the 2026-08-03
    run's own track (228s of dense pop), the mix envelope never drops to 15% of its
    peak mid-song, so vocal_gaps found 2 gaps (the lead-in and the fade-out) and
    every candidate collapsed to 0.0. A confident wrong in-point is exactly the §12
    silent-corruption shape. demucs is a REQUIRED runtime component (preflight
    gates it); separate_vocal_energy raises with the remedy when it is missing.

    The mix envelope still RANKS the surviving candidates — it measures loudness,
    which it can do; only the gap-finding moved to the stem.

    Since 2026-08-14 the spans come from vocals.vocal_spans at ~23 ms resolution
    rather than from a 2 Hz envelope. That is a deliberate change of ANSWER as well
    as of precision: finer bins find short gaps the coarse binning smeared away and
    drop ones binning invented. One sensor serves the in-point and the out-point, so
    the two cannot disagree about the same track (design 2026-08-14 §4)."""
    import librosa                                    # lazy import: heavy optional dep (librosa)
    y, sr = librosa.load(track, sr=None, mono=True)
    track_dur = len(y) / sr
    if track_dur <= duration:
        _log(f"choose_offset: 0.00s (track {track_dur:.1f}s <= reel {duration:.1f}s — whole track)")
        return 0.0
    mix_rms = librosa.feature.rms(y=y, hop_length=offset.HOP)[0]
    mix_energy, mix_hz = offset.downsample(mix_rms, sr, offset.HOP, 2.0)
    gaps = vocals.vocal_spans(track)
    off = offset.best_offset(mix_energy, mix_hz, gaps, duration, track_dur)
    _log(f"choose_offset: {off:.2f}s via vocal ({len(gaps)} vocal-free spans found)")
    return off


def mood_features(track: str) -> mood.MoodVector:
    """Map a track into the mood.py vector space (design §3): tempo → pace,
    spectral-centroid mean → brightness, peak-normalized RMS mean → energy (loudness-
    robust: divide by max|y| before RMS, so mastering gain cancels). Lazy librosa,
    like analyze()/choose_offset()."""
    import librosa                                    # lazy import: heavy optional dep (librosa)
    y, sr = librosa.load(track, sr=None, mono=True)
    tempo = float(np.atleast_1d(librosa.beat.beat_track(y=y, sr=sr, hop_length=_HOP)[0])[0])
    centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=_HOP)))
    peak = float(np.max(np.abs(y))) or 1.0           # silent track → guard /0
    rms_mean = float(np.mean(librosa.feature.rms(y=y / peak, hop_length=_HOP)[0]))
    return mood.MoodVector(energy=mood.norm01(rms_mean, *mood.ENERGY_RMS),
                           brightness=mood.norm01(centroid, *mood.BRIGHT_HZ),
                           pace=mood.norm01(tempo, *mood.PACE_BPM))


def write_preview(track: str, start: float, duration: float, out: str) -> str:
    """The analysed window as an mp3 — exactly what will play under the reel, so the
    user listens to that and not to a catalog's own 30 s clip from somewhere else in the
    song. The second real run's operator asked "where is the preview?" and the agent cut
    the excerpts by hand (retro 2026-10-16 S8). Audio seeks after -i like every cut here."""
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    proc.run([ffbin.ffmpeg(), "-y", "-i", track, "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
              "-vn", "-c:a", "libmp3lame", "-q:a", "4", out])
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="analyse a track → MUSIC.json (tempo + beats + energy)")
    ap.add_argument("track", help="the audio file to analyse")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--start-offset", type=float, default=0.0,
                   help="in-point in the track, seconds (default 0)")
    g.add_argument("--auto-start", action="store_true",
                   help="auto-pick the in-point (strongest fragment, vocal-pause start); needs --duration")
    ap.add_argument("--duration", type=float, default=None,
                    help="window length, seconds (default: the whole track)")
    ap.add_argument("--out", required=True, help="MUSIC.json output path")
    ap.add_argument("--preview", default=None,
                    help="also write the analysed window as an mp3 here — exactly what will "
                         "play under the reel, for the user to listen to before choosing")
    return ap


def main() -> None:
    ap = build_parser()
    a = ap.parse_args()
    if a.auto_start:
        if a.duration is None:
            ap.error("--auto-start needs --duration (the reel length) to size the window")
        start = choose_offset(a.track, a.duration)
    else:
        start = a.start_offset
    ms = analyze(a.track, start, a.duration)
    # Always measured, with or without --auto-start: vocal_spans is part of MUSIC.json's
    # contract now, and the outro fit cannot run without it. When --auto-start already
    # ran, vocals.vocal_spans is memoized and this call is free (design §4).
    ms = dataclasses.replace(
        ms, vocal_spans=outro.window_spans(vocals.vocal_spans(a.track),
                                           ms.start_offset, ms.duration))
    Path(a.out).write_text(json.dumps(ms.to_dict(), indent=2))
    print(a.out)
    if a.preview:
        print(write_preview(a.track, ms.start_offset, ms.duration, a.preview))


if __name__ == "__main__":
    main()
