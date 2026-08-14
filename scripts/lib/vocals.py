"""Vocal-separation boundary for start-offset intelligence (design §3). The only
module that imports demucs/torch (lazily). Turns a track into a coarse
vocal-activity envelope; the decision (offset.py) stays audio-agnostic."""
import importlib

import numpy as np

from scripts.lib import offset


def has_demucs() -> bool:
    """True iff demucs actually IMPORTS. Mirrors verify_runtime._importable, so the
    two probes for the same required capability cannot disagree.

    It was a `find_spec` check until 2026-08-14, which is a weaker question — does a
    module of that name exist on disk — and on that very day torchreid 0.2.5 proved
    the difference matters: pip installs it, `find_spec` finds it, and importing it
    raises ModuleNotFoundError because it under-declares `gdown`. A spec-only probe
    reports the capability present, the gate passes, and the run dies later at the
    first real call. Now that demucs is REQUIRED that is not survivable, so the probe
    pays the import. It costs one module import, not a torch/weights load — demucs'
    own heavy machinery still comes in lazily inside separate_vocal_energy."""
    try:
        importlib.import_module("demucs")
        return True
    except Exception:            # ImportError, or a broken C-extension raising other
        return False


def separate_vocal_energy(track: str, target_hz: float = 2.0) -> tuple[list[float], float]:
    """Whole-track demucs → vocal stem → mono RMS → downsample to ~target_hz.
    Returns (env, hz). Lazy demucs+torch import (heavy). demucs is a REQUIRED
    runtime component since 2026-08-14 — `preflight` blocks a run without it and
    `choose_offset` no longer has a proxy to fall back to, so this guard is the
    only remaining gate on the direct call path and it must name the remedy.
    demucs≥4 API; the real separation is exercised only by the skip-if-absent
    integration test."""
    if not has_demucs():
        raise ValueError("separate_vocal_energy needs demucs, which is REQUIRED — "
                         "run `bash setup.sh` (an absence means its install failed; "
                         "the ERROR line names why). There is no fallback: the "
                         "mix-silence proxy was deleted for answering wrongly "
                         "rather than failing (see beats.choose_offset)")
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
