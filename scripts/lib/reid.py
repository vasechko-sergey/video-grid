"""The only importer of torchreid — person re-ID embeddings (design 2026-08-04).

Isolated exactly like lib/vidstab isolates libvidstab: one module owns the heavy
optional dep, exposes available()/require()/ensure_model()/embed(), and every
consumer goes through it. torch/torchreid are imported LAZILY inside the functions
that need them (mirrors track._iter_detections' lazy ultralytics) so importing
this module — which the manifest gate never does, but the producers do — costs
nothing until an embedding is actually computed.
"""
import numpy as np

EMBED_DIM = 512                     # OSNet osnet_x1_0 feature width; footage.DESCRIPTOR_LEN mirrors it
_MODEL = "osnet_x1_0"
_REMEDY = ("run `bash setup.sh`, which installs torchreid (person re-ID) and "
           "fetches its OSNet weights")
_extractor = None                   # built once, reused; ensure_model() warms it before a pool


def available() -> bool:
    """True iff torchreid imports. The gate the cast paths consult; mirrors
    track.available()/flow.available()."""
    try:
        import torchreid  # noqa: F401  — lazy: the whole point is to not require it
        return True
    except ImportError:
        return False


def require() -> None:
    """Fail loud with a remedy unless torchreid is installed. Called at the entry
    of a path that CANNOT degrade — an explicit cast pin (mirrors vidstab.require)."""
    if not available():
        raise RuntimeError(f"torchreid is not installed — a cast/descriptor hero pin needs "
                           f"person re-ID to match an identity, and guessing from colour is "
                           f"exactly the failure this replaced. {_REMEDY}")


def _device() -> str:
    import torch
    return "mps" if torch.backends.mps.is_available() else "cpu"


def _get_extractor():
    global _extractor
    if _extractor is None:
        from torchreid.utils import FeatureExtractor
        _extractor = FeatureExtractor(model_name=_MODEL, device=_device())
    return _extractor


def ensure_model() -> None:
    """Materialize the OSNet weights ONCE before any concurrent embedding.

    Building the FeatureExtractor performs the one-time weight download; N pool
    workers starting cold would otherwise race the same download into the same
    path — the concurrent-writer landmine track.ensure_model already closes for
    YOLO (design §12/§10). Callers that fan out MUST call this first."""
    require()
    _get_extractor()


def embed(crops: list[np.ndarray]) -> list[list[float]]:
    """Batch RGB HxWx3 crops → L2-normalized 512-d vectors (one per crop).

    Empty in → empty out, short-circuited BEFORE require() so an all-scenery clip
    never needs the dep. FeatureExtractor accepts a list of ndarrays and applies
    its own resize/normalize; it treats an ndarray as RGB (design §10: we MUST
    hand it RGB — ultralytics orig_img is BGR and is converted upstream)."""
    if not crops:
        return []
    require()
    feats = _get_extractor()(list(crops))          # torch.Tensor (N, 512)
    arr = np.asarray(feats.detach().cpu().numpy(), dtype="float64")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (arr / norms).tolist()
