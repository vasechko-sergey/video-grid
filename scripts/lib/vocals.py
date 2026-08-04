"""Vocal-separation boundary for start-offset intelligence (design §3). The only
module that imports demucs/torch (lazily). Turns a track into a coarse
vocal-activity envelope; the decision (offset.py) stays audio-agnostic."""
import importlib.util

import numpy as np

from scripts.lib import offset


def has_demucs() -> bool:
    """True if demucs is importable — the gate the driver checks before the heavy
    path (a spec probe; no torch load)."""
    return importlib.util.find_spec("demucs") is not None


def separate_vocal_energy(track: str, target_hz: float = 2.0) -> tuple[list[float], float]:
    """Whole-track demucs → vocal stem → mono RMS → downsample to ~target_hz.
    Returns (env, hz). Lazy demucs+torch import (heavy). Raises ValueError naming
    bash setup.sh when demucs is absent (callers gate on has_demucs() first —
    defense-in-depth). demucs is a baseline install; an absence means setup.sh's
    warn-and-continue fired (no torch wheel for the platform). demucs≥4 API; the
    real separation is exercised only by the skip-if-absent integration test."""
    if not has_demucs():
        raise ValueError("separate_vocal_energy needs demucs — re-run "
                         "`bash setup.sh` (baseline; an absence means no torch "
                         "wheel for this platform)")
    import librosa                                    # lazy import: heavy optional dep (librosa)
    import torch                                      # lazy import: heavy optional dep (torch)
    from demucs.apply import apply_model              # lazy import: heavy optional dep (demucs/torch)
    from demucs.audio import AudioFile                # lazy import: heavy optional dep (demucs/torch)
    from demucs.pretrained import get_model           # lazy import: heavy optional dep (demucs/torch)

    model = get_model("htdemucs")
    model.eval()
    wav = AudioFile(track).read(streams=0, samplerate=model.samplerate,
                                channels=model.audio_channels)
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / (ref.std() + 1e-8)
    with torch.no_grad():
        est = apply_model(model, wav[None], overlap=0.25, progress=False)[0]
    vocal = est[model.sources.index("vocals")]        # (channels, samples)
    mono = vocal.mean(0).cpu().numpy().astype(np.float32)
    rms = librosa.feature.rms(y=mono, hop_length=offset.HOP)[0]
    return offset.downsample(rms, model.samplerate, offset.HOP, target_hz)
