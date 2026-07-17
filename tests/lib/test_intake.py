import types
import numpy as np
import pytest
from scripts import intake
from scripts.lib import appearance
from scripts.lib.footage import DESCRIPTOR_LEN, Cast


def _desc(*head: float) -> list[float]:
    """A registry-valid descriptor: DESCRIPTOR_LEN floats — `head`, zero-padded."""
    return list(head) + [0.0] * (DESCRIPTOR_LEN - len(head))


def test_shot_type_buckets():
    res = (1000, 1000)
    assert intake.shot_type((500, 500, 700, 700), res) == "close"    # area 0.49 > CLOSE_AREA
    assert intake.shot_type((500, 500, 300, 300), res) == "medium"   # area 0.09 in [0.08, 0.30)
    assert intake.shot_type((500, 500, 100, 100), res) == "wide"     # area 0.01 < MEDIUM_AREA
    assert intake.shot_type(None, res) == "wide"


def test_require_vidstab_raises_when_absent(monkeypatch):
    monkeypatch.setattr(intake.proc, "run",
                        lambda *a, **k: types.SimpleNamespace(stdout=b"... scale ... overlay ..."))
    with pytest.raises(ValueError, match="vidstab"):
        intake._require_vidstab()


def test_require_vidstab_ok_when_present(monkeypatch):
    monkeypatch.setattr(intake.proc, "run",
                        lambda *a, **k: types.SimpleNamespace(stdout=b"... vidstabdetect ..."))
    intake._require_vidstab()   # no raise


def _line(n_from_to):   # helper: build a timeline [(t, people, bbox)] at 1s steps
    return [(float(t), n, (500, 500, 200, 300) if n else None) for t, n in n_from_to]


def test_carve_long_take_splits_by_length():
    # one 8s take, person present throughout, NO scene cuts → several windows in the band
    tl = _line([(t, 1) for t in range(9)])
    spans = intake.carve_windows([], tl, 8.0)
    assert len(spans) >= 2
    assert all(intake.WIN_MIN <= d <= intake.WIN_MAX + 1e-6 for _, d in spans)
    assert abs(sum(d for _, d in spans) - 8.0) < 1e-6      # cover the take, no gaps


def test_carve_splits_on_presence_transition():
    # empty 0–3, person 3–6 → boundary at 3
    tl = _line([(0, 0), (1, 0), (2, 0), (3, 1), (4, 1), (5, 1)])
    spans = intake.carve_windows([], tl, 6.0)
    assert any(abs(s - 3.0) < 1e-6 for s, _ in spans)


def test_carve_short_clip_yields_one_window():
    spans = intake.carve_windows([], _line([(0, 1)]), 0.8)   # < WIN_MIN
    assert spans == [(0.0, 0.8)]


def test_carve_all_short_spans_yields_no_windows():
    # a clip shredded by scene cuts into sub-WIN_MIN shots → no usable moments (empty),
    # NOT one giant over-WIN_MAX window
    spans = intake.carve_windows([1.0, 2.0, 3.0, 4.0, 5.0], _line([(t, 1) for t in range(7)]), 6.0)
    assert spans == []


def test_score_rises_with_presence():
    lo = intake.score_window(present=0.0, motion=0.35, shake=0.0, dur=intake.WIN_TARGET)
    hi = intake.score_window(present=1.0, motion=0.35, shake=0.0, dur=intake.WIN_TARGET)
    assert hi > lo


def test_score_penalises_shake():
    steady = intake.score_window(present=1.0, motion=0.35, shake=0.0, dur=intake.WIN_TARGET)
    shaky = intake.score_window(present=1.0, motion=0.35, shake=intake.SHAKY_CLIP, dur=intake.WIN_TARGET)
    assert steady > shaky


def test_motion_fit_peaks_in_the_middle():
    assert intake._motion_fit(intake.MOTION_PEAK) > intake._motion_fit(0.0)
    assert intake._motion_fit(intake.MOTION_PEAK) > intake._motion_fit(1.0)


def test_dur_fit_peaks_at_target():
    assert intake._dur_fit(intake.WIN_TARGET) > intake._dur_fit(intake.WIN_MIN + 0.01)
    assert intake._dur_fit(intake.WIN_TARGET) > intake._dur_fit(intake.WIN_MAX - 0.01)


def test_describe():
    assert intake._describe(1, "medium", 0.5) == "1 person, medium, dynamic"
    assert intake._describe(0, "wide", 0.1) == "no people, wide, calm"


_TRF = "\n".join([
    "VID.STAB 1",
    "Frame 1 (List 0 [])",
    "Frame 2 (List 2 [(LM 3 4 100 100 0.5 0.9) (LM 6 8 200 200 0.5 0.9)])",  # mags 5, 10 → median 10
    "Frame 3 (List 1 [(LM 0 0 100 100 0.5 0.9)])",                            # mag 0
])


def test_parse_trf_median_magnitudes():
    mags = intake._parse_trf(_TRF)
    assert mags == [0.0, 10.0, 0.0]


def test_parse_trf_bad_header_raises():
    with pytest.raises(ValueError, match="unrecognized header"):
        intake._parse_trf("not a vidstab file\nFrame 1 (List 0 [])")


def test_windowed_shake_averages_and_normalises():
    # fps=1 → frame i at second i; window 1–3s covers frames [1,3) = mags[1:3] = [10, 0] → avg 5 / width 1000
    mags = [0.0, 10.0, 0.0, 0.0]
    out = intake._windowed_shake(mags, [(1.0, 2.0)], fps=1.0, w=1000)
    assert out == [5.0 / 1000]


class _FakeBox:
    def __init__(self, xywh, tid, conf=0.9):
        self.xywh = [xywh]; self.id = [tid]; self.cls = [0]; self.conf = [conf]

class _FakeRes:
    def __init__(self, boxes):
        self.boxes = boxes

def test_people_timeline_samples_and_counts(monkeypatch):
    # 6 frames @ fps 6, SAMPLE_FPS 3 → step 2 → sample frames 0,2,4. subject slides right.
    frames = [_FakeRes([_FakeBox([300 + i * 40, 500, 200, 300], 1)]) for i in range(6)]
    monkeypatch.setattr(intake, "_iter_seg", lambda src, **k: iter(enumerate(frames)))
    tl, crops = intake._people_timeline("x.mp4", fps=6.0, res=(1920, 1080))
    assert [n for _, n, _ in tl] == [1, 1, 1]          # one person each sampled frame
    assert tl[0][0] == 0.0 and abs(tl[1][0] - 2/6) < 1e-6
    assert tl[0][2][2] == 200                          # primary bbox width threaded through
    # crops stay empty here: the fakes carry no orig_img, so there is nothing to retain.


def test_crop_and_mask_rgb_and_aligned_mask():
    import types as _t
    frame_bgr = np.zeros((100, 200, 3), "uint8"); frame_bgr[:, :, 0] = 255   # blue in BGR
    masks = _t.SimpleNamespace(data=[np.ones((100, 200), "float32")])
    res = _t.SimpleNamespace(orig_img=frame_bgr, masks=masks)
    crop, mask = intake.crop_and_mask(res, 0, _FakeBox([100, 50, 40, 60], 1))
    assert crop is not None and crop.shape[2] == 3
    assert crop[0, 0, 2] == 255                          # BGR→RGB: blue is now channel index 2
    assert mask is not None and mask.shape[:2] == crop.shape[:2]   # crop and mask aligned HxW


import imagehash
from PIL import Image as _Img
from scripts.lib.footage import Footage, FootageClip, FootageWindow

def _h(_):   # all-zero average-hash; identical inputs collide (distance 0)
    return imagehash.average_hash(_Img.new("L", (8, 8), 0))

def _h_distinct(_):
    # NOTE: a flat/uniform image of ANY single value collides with every other
    # flat image under average_hash — every pixel equals the mean, so every bit
    # is 0 regardless of whether that flat value is black or white (verified:
    # hamming(flat-black, flat-white) == 0). A split image is needed for a
    # genuinely distinct hash (verified: hamming(flat-black, half/half) == 32).
    img = _Img.new("L", (8, 8), 0)
    px = img.load()
    for x in range(4, 8):
        for y in range(8):
            px[x, y] = 255
    return imagehash.average_hash(img)

def test_cull_marks_best_and_drops_duplicates():
    w_hi = FootageWindow(start=0, dur=2, shot_type="m", people=1, motion=0.4, shake=0.0, score=0.9)
    w_dup = FootageWindow(start=5, dur=2, shot_type="m", people=1, motion=0.4, shake=0.0, score=0.7)
    w_far = FootageWindow(start=9, dur=2, shot_type="m", people=1, motion=0.4, shake=0.0, score=0.6)
    clip = FootageClip(source="a.mp4", dur=20, res=(1920, 1080), fps=30,
                       windows=[w_hi, w_dup, w_far])
    hashes = {id(w_hi): _h("a"), id(w_dup): _h("a"),
              id(w_far): _h_distinct("b")}
    intake.cull([clip], phash_of=lambda c, w: hashes[id(w)])
    assert w_hi.best is True         # top score, survives
    assert w_dup.best is False       # duplicate of w_hi
    assert w_far.best is True        # distinct, above floor

def test_cull_low_score_not_best():
    w = FootageWindow(start=0, dur=2, shot_type="m", people=0, motion=0.1, shake=0.0, score=0.2)
    clip = FootageClip(source="a.mp4", dur=5, res=(100, 100), fps=30, windows=[w])
    intake.cull([clip], phash_of=lambda c, w: imagehash.average_hash(_Img.new("L", (8, 8), 0)))
    assert w.best is False           # below BEST_FLOOR even though unique


def test_build_descriptor_normalised_and_masked():
    crop = np.zeros((10, 10, 3), dtype="uint8"); crop[:, :, 0] = 255   # pure red
    mask = np.ones((10, 10), dtype="uint8")
    d = intake.build_descriptor(crop, mask)
    assert len(d) == 3 * appearance.HIST_BINS
    assert abs(sum(d) - 1.0) < 1e-6                    # L1-normalized
    assert d[appearance.HIST_BINS - 1] > 0            # red maxed → top R bin populated

def test_surface_crops_dedups_identities():
    red = (np.zeros((8, 8, 3), "uint8"), np.ones((8, 8), "uint8")); red[0][:, :, 0] = 255
    red2 = (red[0].copy(), red[1].copy())
    blue = (np.zeros((8, 8, 3), "uint8"), np.ones((8, 8), "uint8")); blue[0][:, :, 2] = 255
    crops = {1: (0.9, *red), 2: (0.8, *red2), 3: (0.7, *blue)}
    picked = intake.surface_crops(crops, top_n=8)
    assert len(picked) == 2                            # the two reds collapse to one identity

def test_save_cast_candidates_saves_and_manifests(tmp_path):
    red = np.zeros((8, 8, 3), "uint8"); red[:, :, 0] = 255
    blue = np.zeros((8, 8, 3), "uint8"); blue[:, :, 2] = 255
    crops = {("a.mp4", 1): (0.9, red, np.ones((8, 8), "uint8")),
             ("b.mp4", 1): (0.8, blue, np.ones((8, 8), "uint8"))}
    manifest = intake.save_cast_candidates(crops, str(tmp_path))
    assert len(manifest) == 2                                   # two distinct identities
    assert (tmp_path / "cast_candidates.json").exists()
    assert (tmp_path / "cast_crops" / "candidate_0.png").exists()
    assert manifest[0]["source"] in {"a.mp4", "b.mp4"} and "descriptor" in manifest[0]

def test_write_cast_writes_json(tmp_path):
    cast = intake.write_cast([("Lena", "green", _desc(0.1, 0.9), ["cast_crops/candidate_0.png"])],
                             str(tmp_path))
    assert (tmp_path / "cast.json").exists()
    assert cast.members[0].name == "Lena" and cast.members[0].descriptor == _desc(0.1, 0.9)
    assert Cast.from_json(tmp_path / "cast.json").members[0].ref_crops == ["cast_crops/candidate_0.png"]


def test_write_cast_rejects_a_stale_descriptor_before_writing_the_file(tmp_path):
    # write_cast builds the Cast BEFORE writing cast.json, so CastMember's shape
    # check fires while the human is still in the naming pass — the broken registry
    # never reaches disk to be discovered three stages later
    with pytest.raises(ValueError, match="descriptor"):
        intake.write_cast([("Lena", "green", [0.1, 0.9], [])], str(tmp_path))
    assert not (tmp_path / "cast.json").exists()


def test_intake_builds_footage_and_writes(monkeypatch, tmp_path):
    root = tmp_path / "footage"; root.mkdir()
    (root / "a.mp4").write_bytes(b"x")
    monkeypatch.setattr(intake.assembly, "probe_stream",
                        lambda s: types.SimpleNamespace(w=1920, h=1080, fps=6.0))
    monkeypatch.setattr(intake.assembly, "probe_duration", lambda s: 8.0)
    monkeypatch.setattr(intake, "scene_bounds", lambda s: [])
    tl = [(float(i), 1, (500, 500, 300, 300)) for i in range(9)]
    monkeypatch.setattr(intake, "_people_timeline",
                        lambda s, fps, res, sample_fps=intake.SAMPLE_FPS: (tl, {}))
    monkeypatch.setattr(intake, "shake_by_window",
                        lambda clip, spans, fps, res: [0.0 for _ in spans])
    import imagehash
    from PIL import Image as I
    monkeypatch.setattr(intake, "_phash_at",
                        lambda clip, t: imagehash.average_hash(I.new("L", (8, 8), int(t) % 256)))
    out = tmp_path / "out"
    result = intake.intake(str(root), str(out))
    assert (out / "FOOTAGE.json").exists() and (out / "FOOTAGE.md").exists()
    assert len(result.clips) == 1 and result.clips[0].source == "a.mp4"
    assert result.clips[0].windows                       # carved ≥1 window
    assert any(w.best for w in result.clips[0].windows)  # cull marked best
    assert (out / "cast_candidates.json").exists()       # empty crops → empty manifest, still written
