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


_SPAN_HZ = 40.0                  # ~23 ms bins after downsample's integer step. NOT 2.0:
                                 # a 2 Hz envelope has 0.5s bins and the outro rule asks
                                 # about 0.5s, so it cannot resolve its own question — the
                                 # first pass of the 2026-08-14 investigation reported the
                                 # feature impossible because of exactly this (design §8.1).
_SPANS: dict[str, tuple[tuple[float, float], ...]] = {}   # per-process memo, keyed on the
                                 # track path: choose_offset and beats.main both want the
                                 # spans inside one beats.py run, and the separation costs
                                 # 46-62s on a 229s track (measured 2026-08-14).
                                 # TEST HAZARD: this dict outlives any single test. A test
                                 # that populates _SPANS["t.wav"] and never clears it can
                                 # silently shadow a LATER test's guard — e.g. a has_demucs
                                 # stub never gets exercised because the cache answers first,
                                 # so separate_vocal_energy is never called at all (found
                                 # 2026-08-14 in test_choose_offset_refuses_without_demucs).
                                 # tests/lib/conftest.py's autouse _reset_vocal_spans fixture
                                 # clears this before/after every tests/lib/ test for exactly
                                 # this reason — a new test here does not need its own clear().


def vocal_spans(track: str) -> tuple[tuple[float, float], ...]:
    """TRACK-relative (start, end) spans where the vocal stem is quiet.

    The one sensor both the music IN-point (choose_offset) and the OUT-point (the
    outro fit) read, so the two cannot disagree about where the singing stops. The
    decision stays pure — this only supplies the envelope offset.vocal_gaps judges.

    Times are track-relative because that is what separate_vocal_energy measures;
    outro.window_spans converts them to the stem-relative form MusicSpec stores."""
    if track not in _SPANS:
        env, hz = separate_vocal_energy(track, target_hz=_SPAN_HZ)
        _SPANS[track] = offset.vocal_gaps(env, hz)
    return _SPANS[track]


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
