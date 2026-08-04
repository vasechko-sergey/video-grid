import builtins
import numpy as np
import pytest

from scripts.lib import reid


def test_embed_dim_is_512():
    assert reid.EMBED_DIM == 512


def test_available_false_when_torchreid_absent(monkeypatch):
    real_import = builtins.__import__

    def fake(name, *a, **k):
        if name == "torchreid" or name.startswith("torchreid."):
            raise ImportError("no torchreid")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    assert reid.available() is False


def test_require_raises_with_remedy_when_absent(monkeypatch):
    monkeypatch.setattr(reid, "available", lambda: False)
    with pytest.raises(RuntimeError, match="bash setup.sh"):
        reid.require()


def test_embed_empty_is_empty_without_touching_torch(monkeypatch):
    # [] must short-circuit BEFORE require(), so an empty batch never needs the dep
    monkeypatch.setattr(reid, "available", lambda: False)
    assert reid.embed([]) == []


def test_embed_l2_normalizes_the_extractor_output(monkeypatch):
    # inject a fake extractor returning a raw (unnormalized) 2x512 "tensor"
    class _FakeTensor:
        def __init__(self, arr): self._a = arr
        def detach(self): return self
        def cpu(self): return self
        def numpy(self): return self._a

    raw = np.tile(np.arange(1.0, 513.0), (2, 1))          # two identical rows, norm != 1
    monkeypatch.setattr(reid, "available", lambda: True)
    monkeypatch.setattr(reid, "_get_extractor", lambda: (lambda crops: _FakeTensor(raw)))
    out = reid.embed([np.zeros((4, 4, 3), np.uint8), np.zeros((4, 4, 3), np.uint8)])
    assert len(out) == 2 and len(out[0]) == 512
    assert abs(sum(v * v for v in out[0]) - 1.0) < 1e-9   # L2-normalized


def test_embed_forces_a_contiguous_copy_of_a_negative_stride_crop(monkeypatch):
    # appearance.crop_from_result/crop_bbox slice BGR->RGB with `[..., ::-1]` — a
    # negative-stride, non-contiguous view (design §10). The weights-gated real-OSNet
    # test's synthetic crops are already contiguous, so it never exercises the
    # np.ascontiguousarray fix; this test captures exactly what embed() hands the
    # extractor and proves the fix actually runs.
    class _FakeTensor:
        def __init__(self, arr): self._a = arr
        def detach(self): return self
        def cpu(self): return self
        def numpy(self): return self._a

    captured = []

    def fake_extractor(crops):
        captured.extend(crops)
        return _FakeTensor(np.tile(np.arange(1.0, 513.0), (len(crops), 1)))

    monkeypatch.setattr(reid, "available", lambda: True)
    monkeypatch.setattr(reid, "_get_extractor", lambda: fake_extractor)
    non_contiguous = np.zeros((8, 8, 3), np.uint8)[..., ::-1]
    assert non_contiguous.flags["C_CONTIGUOUS"] is False   # sanity: the input IS the landmine shape
    reid.embed([non_contiguous])
    assert captured[0].flags["C_CONTIGUOUS"] is True
