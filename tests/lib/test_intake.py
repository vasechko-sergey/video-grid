import json
import threading
import types
import numpy as np
import pytest
from scripts import intake
from scripts.lib import footage, reid
from scripts.lib.footage import DESCRIPTOR_LEN, Cast


def _desc(*head: float) -> list[float]:
    """A registry-valid descriptor: DESCRIPTOR_LEN floats — `head`, zero-padded."""
    return list(head) + [0.0] * (DESCRIPTOR_LEN - len(head))


def test_shot_type_buckets():
    w, h = 1000, 1000
    assert footage.shot_type(700 / w, 700 / h) == "close"    # area 0.49 > CLOSE_AREA
    assert footage.shot_type(300 / w, 300 / h) == "medium"   # area 0.09 in [0.08, 0.30)
    assert footage.shot_type(100 / w, 100 / h) == "wide"     # area 0.01 < MEDIUM_AREA
    assert footage.shot_type(0.0, 0.0) == "wide"


def _line(n_from_to):   # helper: timeline [(t, people, bbox, track_ids, boxes_by_tid)] at 1s steps
    return [(float(t), n, (500, 500, 200, 300) if n else None, [1] if n else [],
             {1: (500.0, 500.0, 200.0, 300.0)} if n else {})
            for t, n in n_from_to]


def test_carve_long_take_is_activity_units_not_equal_tiling():
    # a 12s take with two isolated, ASYMMETRIC activity peaks (t=3, t=8): a big jump
    # then a slow settle, so the subject curve has strict maxima (not an equal-value
    # plateau). Equal-interval tiling would emit N windows of ONE duration; activity
    # units vary — restoring _split_span would collapse the duration set to a single value.
    pos = [500, 500, 500, 800, 810, 815, 815, 815, 1115, 1125, 1130, 1130, 1130]
    tl = [(float(t), 1, (pos[t], 500, 200, 300), [1], {1: (float(pos[t]), 500.0, 200.0, 300.0)})
          for t in range(13)]
    spans = intake.carve_windows([], tl, [], 1.0, 12.0)
    assert spans                                                     # carved something
    assert all(intake.WIN_MIN <= d <= intake.WIN_MAX + 1e-6 for _, d in spans)
    assert len({round(d, 3) for _, d in spans}) > 1                 # NOT one uniform tile size


def test_carve_splits_on_presence_transition():
    # empty 0–3, person 3–6 → boundary at 3
    tl = _line([(0, 0), (1, 0), (2, 0), (3, 1), (4, 1), (5, 1)])
    spans = intake.carve_windows([], tl, [], 1.0, 6.0)
    assert any(abs(s - 3.0) < 1e-6 for s, _ in spans)


def test_carve_short_clip_yields_one_window():
    spans = intake.carve_windows([], _line([(0, 1)]), [], 1.0, 0.8)   # < WIN_MIN
    assert spans == [(0.0, 0.8)]


def test_carve_all_short_spans_yields_no_windows():
    spans = intake.carve_windows([1.0, 2.0, 3.0, 4.0, 5.0], _line([(t, 1) for t in range(7)]),
                                 [], 1.0, 6.0)
    assert spans == []


def test_carve_peopleless_span_uses_camera_motion(monkeypatch):
    # no people the whole 8s take → the curve comes from vidstab mags; a mid-clip
    # camera surge (frame 4 at fps 1 → t=4) should anchor a unit that contains t=4
    tl = [(float(t), 0, None, [], {}) for t in range(9)]
    mags = [0, 0, 0, 1, 9, 1, 0, 0, 0]
    spans = intake.carve_windows([], tl, mags, 1.0, 8.0)
    # strict right bound: a subject-only regression → all-zero curve → flat (0.0, 4.0),
    # which touches 4.0 only at its edge; the camera-driven tight window straddles it.
    assert any(s <= 4.0 < s + d for s, d in spans)


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


def test_process_clip_detects_shake_once_before_carving(monkeypatch):
    monkeypatch.setattr(intake.assembly, "probe_stream",
                        lambda s: types.SimpleNamespace(w=1000, h=1080, fps=1.0))
    monkeypatch.setattr(intake.assembly, "probe_duration", lambda s: 8.0)
    monkeypatch.setattr(intake.assembly, "make_proxy", lambda *a, **k: False)   # analyse the original
    monkeypatch.setattr(intake, "scene_bounds", lambda s: [])
    monkeypatch.setattr(intake.vidstab, "require", lambda: None)
    tl = [(float(i), 1, (500, 500, 300, 300), [1], {1: (500.0, 500.0, 300.0, 300.0)}) for i in range(9)]
    monkeypatch.setattr(intake, "_people_timeline",
                        lambda s, fps, res, sample_fps=intake.SAMPLE_FPS: (tl, {}, {}))
    seen = []

    def fake_detect(src, trf, dur):
        seen.append((src, dur))
        return [0.0] * 8

    monkeypatch.setattr(intake.vidstab, "detect", fake_detect)
    monkeypatch.setattr(intake.assembly, "frames_rgb",
                        lambda s, times, fps: [np.zeros((8, 8, 3), dtype="uint8") for _ in times])
    intake._process_clip("/foot/a.mp4", intake.SAMPLE_FPS)
    assert seen == [("/foot/a.mp4", 8.0)]     # detect once, with the clip's OWN length


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

def test_people_timeline_samples_counts_and_track_ids(monkeypatch):
    # 6 frames @ fps 6, SAMPLE_FPS 3 → step 2 → sample frames 0,2,4. subject slides right.
    frames = [_FakeRes([_FakeBox([300 + i * 40, 500, 200, 300], 1)]) for i in range(6)]
    monkeypatch.setattr(intake, "_iter_seg", lambda src, **k: iter(enumerate(frames)))
    tl, best, presence = intake._people_timeline("x.mp4", fps=6.0, res=(1920, 1080))
    assert [n for _, n, _, _, _ in tl] == [1, 1, 1]     # one person each sampled frame
    assert tl[0][0] == 0.0 and abs(tl[1][0] - 2/6) < 1e-6
    assert tl[0][2][2] == 200                           # primary bbox width threaded through
    assert tl[0][3] == [1]                              # track id present at the sample
    assert presence[1] == pytest.approx(1.0)            # 3 sampled frames × step/fps (2/6)


def test_people_timeline_records_best_crop_ref_per_track(monkeypatch):
    from scripts import intake
    class _Box:
        def __init__(s, tid, conf, xywh): s.id=[tid]; s.conf=[conf]; s.xywh=[xywh]
    class _Res:
        def __init__(s, boxes): s.boxes=boxes
    frames = [(0, _Res([_Box(1, 0.5, (10,10,4,8))])),
              (1, _Res([_Box(1, 0.9, (12,10,4,8))]))]   # frame 1 is the better crop
    monkeypatch.setattr(intake, "_iter_seg", lambda src: iter(frames))
    timeline, best, presence = intake._people_timeline("proxy.mp4", fps=30.0, res=(960,540), sample_fps=3.0)
    assert set(best) == {1}
    conf, t, box = best[1]                              # 3-tuple now: (conf, t, bbox) — no mask
    assert conf == 0.9 and abs(t - 1/30.0) < 1e-6 and box == (12,10,4,8)


def test_people_timeline_row_carries_boxes_by_track_id(monkeypatch):
    class _B:
        def __init__(self, tid, xywh, conf=0.9):
            self.id = [tid] if tid is not None else None
            self.xywh = [xywh]
            self.conf = [conf]

    frames = [types.SimpleNamespace(boxes=[_B(1, (10, 20, 30, 40)),
                                           _B(2, (50, 60, 70, 80)),
                                           _B(None, (90, 90, 10, 10))])]
    monkeypatch.setattr(intake, "_iter_seg", lambda s, model_path=intake.MODEL: enumerate(frames))
    tl, _, _ = intake._people_timeline("x.mp4", fps=1.0, res=(1920, 1080), sample_fps=1.0)
    t, people, primary, tids, by_tid = tl[0]
    assert people == 3                       # the untracked detection still counts as a person
    assert tids == [1, 2]                    # ...but cannot be differenced, so it is not in by_tid
    assert by_tid == {1: (10.0, 20.0, 30.0, 40.0), 2: (50.0, 60.0, 70.0, 80.0)}
    assert primary == (50.0, 60.0, 70.0, 80.0)      # largest area, unchanged


def test_motion_measures_a_tracks_own_displacement():
    res = (1000, 1000)
    samples = [(0.0, 1, (100, 100, 50, 90), [1], {1: (100.0, 100.0, 50.0, 90.0)}),
               (1.0, 1, (110, 100, 50, 90), [1], {1: (110.0, 100.0, 50.0, 90.0)})]
    assert intake._motion(samples, res) == pytest.approx(0.01)   # 10px / 1000px, no gain


def test_motion_is_zero_when_only_the_largest_person_changes():
    # both people stationary; the larger box swaps. The old primary-bbox difference
    # reported a full-frame jump here (design §1.2) — the whole bug in one assert.
    res = (1000, 1000)
    a = {1: (100.0, 100.0, 50.0, 90.0), 2: (900.0, 100.0, 30.0, 60.0)}
    b = {1: (100.0, 100.0, 30.0, 60.0), 2: (900.0, 100.0, 50.0, 90.0)}
    samples = [(0.0, 2, (100, 100, 50, 90), [1, 2], a),
               (1.0, 2, (900, 100, 50, 90), [1, 2], b)]
    assert intake._motion(samples, res) == 0.0


def test_motion_needs_two_samples():
    assert intake._motion([(0.0, 1, (1, 1, 1, 1), [1], {1: (1.0, 1.0, 1.0, 1.0)})], (100, 100)) == 0.0


def test_build_window_unions_track_ids():
    # disjoint ids per sample → a last-sample-only bug would drop id 2; the union keeps both
    tl = [(0.0, 1, (500, 500, 10, 10), [2], {2: (500.0, 500.0, 10.0, 10.0)}),
          (1.0, 1, (500, 500, 10, 10), [5], {5: (500.0, 500.0, 10.0, 10.0)})]
    w = intake._build_window((0.0, 2.0), tl, shake=0.0, res=(1000, 1000))
    assert w.track_ids == [2, 5]


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


def _emb(i):
    v = [0.0] * 512; v[i] = 1.0
    return v


def test_surface_clusters_by_identity_and_ranks_by_presence():
    from scripts.lib.intake_cache import CastEntry
    # two people: id A (emb slot 0) with 3 near-identical tracks & lots of presence,
    # id B (emb slot 5) with 1 track & little presence
    A = [CastEntry("c.mp4", tid=i, conf=0.9, descriptor=_emb(0), presence=p)
         for i, p in ((1, 2.0), (2, 3.0), (3, 1.0))]
    B = [CastEntry("c.mp4", tid=9, conf=0.99, descriptor=_emb(5), presence=0.5)]
    picked = intake.surface_crops(A + B)
    assert len(picked) == 2
    assert picked[0].presence == 6.0 and picked[0].descriptor == _emb(0)   # A first, summed
    assert picked[1].presence == 0.5 and picked[1].descriptor == _emb(5)   # B second


def test_surface_adaptive_cap_logs_the_drop(capsys):
    from scripts.lib.intake_cache import CastEntry
    entries = [CastEntry("c.mp4", tid=i, conf=0.9, descriptor=_emb(i), presence=float(i))
               for i in range(intake.MAX_CAST + 3)]
    picked = intake.surface_crops(entries)
    assert len(picked) == intake.MAX_CAST
    assert "dropped 3" in capsys.readouterr().err


def test_surface_empty_is_empty():
    assert intake.surface_crops([]) == []


def test_surface_crops_dedups_identities():
    # clustering (average-linkage, cosine, cut at CLUSTER_COS) collapses two
    # IDENTICAL embeddings into one cluster (cosine dist 0 < CLUSTER_COS); an
    # orthogonal one (cosine dist 1.0) forms its own, distinct cluster.
    from scripts.lib.intake_cache import CastEntry
    red = np.zeros((8, 8, 3), "uint8"); red[:, :, 0] = 255
    blue = np.zeros((8, 8, 3), "uint8"); blue[:, :, 2] = 255
    dr = _desc(1.0)                    # the "red" identity embedding
    db = _desc(0.0, 1.0)              # orthogonal → cosine dist 1.0 > CLUSTER_COS 0.30
    entries = [CastEntry("a.mp4", 1, 0.9, dr, crop_rgb=red),
               CastEntry("a.mp4", 2, 0.8, list(dr), crop_rgb=red.copy()),
               CastEntry("b.mp4", 3, 0.7, db, crop_rgb=blue)]
    picked = intake.surface_crops(entries, max_cast=8)
    assert len(picked) == 2                            # the two identical embeddings collapse to one

def test_save_cast_candidates_saves_and_manifests(tmp_path):
    from scripts.lib.intake_cache import CastEntry
    red = np.zeros((8, 8, 3), "uint8"); red[:, :, 0] = 255
    blue = np.zeros((8, 8, 3), "uint8"); blue[:, :, 2] = 255
    entries = [CastEntry("a.mp4", 1, 0.9, _desc(1.0), crop_rgb=red),
               CastEntry("b.mp4", 1, 0.8, _desc(0.0, 1.0), crop_rgb=blue)]
    manifest = intake.save_cast_candidates(entries, str(tmp_path))
    assert len(manifest) == 2
    assert (tmp_path / "cast_candidates.json").exists()
    assert (tmp_path / "cast_crops" / "candidate_0.png").exists()
    assert manifest[0]["source"] in {"a.mp4", "b.mp4"} and "descriptor" in manifest[0]

def test_save_cast_candidates_copies_a_cached_form_crop(tmp_path):
    # the RESUME path: a cache-loaded CastEntry carries its crop as an on-disk PNG
    # path (crop_rgb=None); save_cast_candidates must COPY it into the candidate slot
    from scripts.lib.intake_cache import CastEntry
    red = np.zeros((8, 8, 3), "uint8"); red[:, :, 0] = 255
    src = tmp_path / "cached_crop.png"
    _Img.fromarray(red).save(src)
    e = CastEntry("a.mp4", 1, 0.9, _desc(1.0), crop=str(src))
    out = tmp_path / "out"
    manifest = intake.save_cast_candidates([e], str(out))
    dest = out / "cast_crops" / "candidate_0.png"
    assert dest.exists() and manifest[0]["crop"] == str(dest)
    assert np.asarray(_Img.open(dest))[0, 0, 0] == 255      # copied, still red

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


def test_write_cast_rejects_two_crops_named_the_same(tmp_path):
    # THE birth site of a duplicate name: surface_crops clusters by descriptor at a
    # cosine cut (CLUSTER_COS=0.30, design 2026-08-04), so one person in two
    # lightings can still surface twice and the human naming both "Lena" is the
    # obvious move. Cast's uniqueness check fires
    # during the naming pass — where the human is standing and can actually fix it —
    # and cast.json never reaches disk broken.
    with pytest.raises(ValueError, match="duplicate"):
        intake.write_cast([("Lena", "red jacket", _desc(1.0), []),
                           ("Lena", "blue wetsuit", _desc(0.0, 1.0), [])], str(tmp_path))
    assert not (tmp_path / "cast.json").exists()


def test_intake_builds_footage_and_writes(monkeypatch, tmp_path):
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    root = tmp_path / "footage"; root.mkdir()
    (root / "a.mp4").write_bytes(b"x")
    monkeypatch.setattr(intake.assembly, "probe_stream",
                        lambda s: types.SimpleNamespace(w=1920, h=1080, fps=6.0))
    monkeypatch.setattr(intake.assembly, "probe_duration", lambda s: 8.0)
    monkeypatch.setattr(intake.assembly, "make_proxy", lambda *a, **k: False)   # analyse the original (all readers stubbed)
    monkeypatch.setattr(intake, "scene_bounds", lambda s: [])
    tl = [(float(i), 1, (500, 500, 300, 300), [1], {1: (500.0, 500.0, 300.0, 300.0)}) for i in range(9)]
    monkeypatch.setattr(intake, "_people_timeline",
                        lambda s, fps, res, sample_fps=intake.SAMPLE_FPS: (tl, {}, {}))
    monkeypatch.setattr(intake.vidstab, "require", lambda: None)
    monkeypatch.setattr(intake.vidstab, "detect", lambda src, trf, dur: [0.0] * 8)
    monkeypatch.setattr(intake.assembly, "frames_rgb",
                        lambda s, times, fps:
                        [np.full((8, 8, 3), int(t) % 256, dtype="uint8") for t in times])
    out = tmp_path / "out"
    result = intake.intake(str(root), str(out))
    assert (out / "FOOTAGE.json").exists() and (out / "FOOTAGE.md").exists()
    assert len(result.clips) == 1 and result.clips[0].source == "a.mp4"
    assert result.clips[0].windows                       # carved ≥1 window
    assert any(w.best for w in result.clips[0].windows)  # cull marked best
    assert (out / "cast_candidates.json").exists()       # empty crops → empty manifest, still written


def test_process_clip_returns_clip_phashes_and_cast(monkeypatch):
    from scripts.lib.footage import DESCRIPTOR_LEN
    orig = np.full((1080, 1920, 3), 128, dtype="uint8")      # ORIGINAL-res frame
    monkeypatch.setattr(intake.assembly, "probe_stream",
                        lambda s: types.SimpleNamespace(w=1920, h=1080, fps=6.0))
    monkeypatch.setattr(intake.assembly, "probe_duration", lambda s: 8.0)
    monkeypatch.setattr(intake.assembly, "make_proxy", lambda *a, **k: True)   # 1920 > 960 → a proxy
    monkeypatch.setattr(intake.assembly, "frames_rgb", lambda s, times, fps: [orig for _ in times])
    monkeypatch.setattr(intake, "scene_bounds", lambda s: [])
    tl = [(float(i), 1, (240, 270, 100, 200), [1], {1: (240.0, 270.0, 100.0, 200.0)})
          for i in range(9)]                                                   # proxy-space bboxes
    monkeypatch.setattr(intake, "_people_timeline",
                        lambda s, fps, res, sample_fps=intake.SAMPLE_FPS:
                        (tl, {1: (0.9, 0.0, (240, 270, 100, 200))}, {1: 3.0}))  # best 3-tuple + presence
    monkeypatch.setattr(intake.vidstab, "require", lambda: None)
    monkeypatch.setattr(intake.vidstab, "detect", lambda src, trf, dur: [0.0] * 8)
    monkeypatch.setattr(reid, "embed", lambda crops: [[1.0] + [0.0] * 511 for _ in crops])
    res = intake._process_clip("/foot/a.mp4", intake.SAMPLE_FPS)
    assert res.clip.source == "a.mp4" and res.clip.windows
    assert res.clip.res == (1920, 1080)                     # ORIGINAL stored on FootageClip
    assert len(res.phashes) == len(res.clip.windows)
    assert all(isinstance(h, str) for h in res.phashes)     # hex, cache-serializable
    assert len(res.cast) == 1
    assert res.cast[0].source == "a.mp4" and res.cast[0].tid == 1
    assert len(res.cast[0].descriptor) == DESCRIPTOR_LEN
    assert res.cast[0].presence == 3.0                       # presence carried from _people_timeline
    assert res.cast[0].crop_rgb is not None                  # worker-form array, cropped from ORIGINAL


def test_process_clip_analyses_proxy_and_crops_from_original(monkeypatch, tmp_path):
    import numpy as np
    from scripts import intake
    from scripts.lib import assembly, vidstab, footage

    calls = {"analysed": []}
    class _Info:  w, h, fps = 3840, 2160, 30.0
    monkeypatch.setattr(assembly, "probe_stream", lambda p: _Info())
    monkeypatch.setattr(assembly, "probe_duration", lambda p: 2.0)
    monkeypatch.setattr(intake, "PROXY_LONG_SIDE", 960)
    def _mk(src, dst, long_side): calls["proxy"] = (src, dst, long_side); return True
    monkeypatch.setattr(assembly, "make_proxy", _mk)
    monkeypatch.setattr(intake, "scene_bounds", lambda src: calls["analysed"].append(("scene", src)) or [])
    def _tl(src, fps, res, sf):
        calls["analysed"].append(("yolo", src, res))       # res must be the PROXY dims
        return ([(0.0, 1, (480, 270, 40, 80), [1], {1: (480.0, 270.0, 40.0, 80.0)})],
                {1: (0.9, 0.0, (480, 270, 40, 80))}, {1: 2.0})
    monkeypatch.setattr(intake, "_people_timeline", _tl)
    monkeypatch.setattr(vidstab, "require", lambda: None)
    monkeypatch.setattr(vidstab, "detect", lambda src, trf, dur: calls["analysed"].append(("vidstab", src)) or [1.0])
    monkeypatch.setattr(intake, "carve_windows", lambda *a: [(0.0, 2.0)])
    monkeypatch.setattr(reid, "embed", lambda crops: [[1.0] + [0.0] * 511 for _ in crops])
    orig_frame = np.full((2160, 3840, 3), 128, dtype="uint8")
    monkeypatch.setattr(assembly, "frames_rgb", lambda src, times, fps: (calls.__setitem__("crop_src", src), [orig_frame for _ in times])[1])

    res = intake._process_clip(str(tmp_path / "DJI.MP4"))
    assert res.clip.res == (3840, 2160)                    # ORIGINAL stored
    proxy = calls["proxy"][1]
    assert ("scene", proxy) in calls["analysed"]
    assert ("vidstab", proxy) in calls["analysed"]
    assert any(c[0] == "yolo" and c[1] == proxy and c[2] == (960, 540) for c in calls["analysed"])
    assert calls["crop_src"] == str(tmp_path / "DJI.MP4")  # cast crop from the ORIGINAL
    assert res.cast and len(res.cast[0].descriptor) == footage.DESCRIPTOR_LEN


def _two_clip_root(tmp_path):
    root = tmp_path / "footage"; root.mkdir()
    (root / "a.mp4").write_bytes(b"x")
    (root / "b.mp4").write_bytes(b"y")
    return root


def _stub_cache(monkeypatch):
    # isolate the pool tests from the real filesystem cache
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    monkeypatch.setattr(intake.intake_cache, "load", lambda *a, **k: None)
    monkeypatch.setattr(intake.intake_cache, "store", lambda o, p, s, r, *a, **k: r)


def _fake_result(name):
    from scripts.lib.footage import FootageClip
    return intake.ClipResult(clip=FootageClip(source=name, dur=1.0, res=(2, 2), fps=1.0,
                                              windows=[]), phashes=[], cast=[])


@pytest.mark.parametrize("bad", [0, -1, True, "3", 3.0])
def test_jobs_validation_rejects(tmp_path, bad):
    root = _two_clip_root(tmp_path)
    with pytest.raises(ValueError, match="jobs"):
        intake.intake(str(root), str(tmp_path / "out"), jobs=bad)


def test_ensure_model_runs_before_any_worker(monkeypatch, tmp_path):
    root = _two_clip_root(tmp_path)
    monkeypatch.setattr(intake.intake_cache, "load", lambda *a, **k: None)
    monkeypatch.setattr(intake.intake_cache, "store", lambda o, p, s, r, *a, **k: r)
    seen = []
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: seen.append("ensure"))
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS, embed_cast=True:
                        (seen.append("pe"), _fake_result(intake.Path(path).name))[1])
    intake.intake(str(root), str(tmp_path / "out"), jobs=2)
    assert seen[0] == "ensure" and seen.count("ensure") == 1 and "pe" in seen


def test_pool_reaches_the_cap_and_never_exceeds_it(monkeypatch, tmp_path):
    root = tmp_path / "footage"; root.mkdir()
    for i in range(4):
        (root / f"c{i}.mp4").write_bytes(b"x")
    _stub_cache(monkeypatch)
    jobs = 2
    live = {"n": 0, "peak": 0}
    lock = threading.Lock()
    barrier = threading.Barrier(jobs, timeout=10)

    def fake_pe(path, sf=intake.SAMPLE_FPS, embed_cast=True):
        with lock:
            live["n"] += 1; live["peak"] = max(live["peak"], live["n"])
        barrier.wait()                       # forces `jobs` workers to co-exist; times out if serial
        with lock:
            live["n"] -= 1
        return _fake_result(intake.Path(path).name)

    monkeypatch.setattr(intake, "_process_clip", fake_pe)
    intake.intake(str(root), str(tmp_path / "out"), jobs=jobs)
    assert live["peak"] == jobs              # reached (barrier) and never exceeded


def test_output_is_byte_identical_across_jobs(monkeypatch, tmp_path):
    root = _two_clip_root(tmp_path)
    _stub_cache(monkeypatch)
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS, embed_cast=True: _fake_result(intake.Path(path).name))
    intake.intake(str(root), str(tmp_path / "o1"), jobs=1)
    intake.intake(str(root), str(tmp_path / "o3"), jobs=3)
    assert (tmp_path / "o1" / "FOOTAGE.json").read_text() == (tmp_path / "o3" / "FOOTAGE.json").read_text()


def test_only_cache_misses_reach_the_pool(monkeypatch, tmp_path):
    root = _two_clip_root(tmp_path); out = tmp_path / "out"
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    submitted = []
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS, embed_cast=True:
                        (submitted.append(intake.Path(path).name),
                         _fake_result(intake.Path(path).name))[1])
    intake.intake(str(root), str(out))                 # first run: both are misses
    assert sorted(submitted) == ["a.mp4", "b.mp4"]
    submitted.clear()
    intake.intake(str(root), str(out))                 # second run: both cached
    assert submitted == []                             # nothing re-submitted
    submitted.clear()
    import shutil as _sh
    _sh.rmtree(out / ".intake_cache" / "b.mp4")        # invalidate just b
    intake.intake(str(root), str(out))
    assert submitted == ["b.mp4"]                       # only the miss reruns


def test_fresh_bypasses_the_cache(monkeypatch, tmp_path):
    root = _two_clip_root(tmp_path); out = tmp_path / "out"
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    submitted = []
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS, embed_cast=True:
                        (submitted.append(intake.Path(path).name),
                         _fake_result(intake.Path(path).name))[1])
    intake.intake(str(root), str(out))
    submitted.clear()
    intake.intake(str(root), str(out), fresh=True)     # ignore the populated cache
    assert sorted(submitted) == ["a.mp4", "b.mp4"]


def test_output_is_byte_identical_scanned_vs_cached(monkeypatch, tmp_path):
    root = _two_clip_root(tmp_path); out = tmp_path / "out"
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS, embed_cast=True: _fake_result(intake.Path(path).name))
    intake.intake(str(root), str(out))
    a = (out / "FOOTAGE.json").read_text()
    intake.intake(str(root), str(out))                 # all cache hits
    b = (out / "FOOTAGE.json").read_text()
    assert a == b


def test_a_bad_clip_is_quarantined_not_fatal(monkeypatch, tmp_path):
    root = _two_clip_root(tmp_path); out = tmp_path / "out"
    _stub_cache(monkeypatch)

    def flaky(path, sf=intake.SAMPLE_FPS, embed_cast=True):
        name = intake.Path(path).name
        if name == "b.mp4":
            raise RuntimeError("corrupt moov atom")
        return _fake_result(name)

    monkeypatch.setattr(intake, "_process_clip", flaky)
    result = intake.intake(str(root), str(out))        # does NOT raise
    assert [c.source for c in result.clips] == ["a.mp4"]        # good clip survives
    report = json.loads((out / "intake_report.json").read_text())
    assert report["failed"] == [{"source": "b.mp4", "error": "corrupt moov atom"}]
    assert "## Failed clips" in (out / "FOOTAGE.md").read_text()
    assert (out / "FOOTAGE.json").exists()             # a valid artifact was produced


def test_report_counts_a_mixed_run(monkeypatch, tmp_path):
    # 4 clips: a,b are cache HITS; c,d are misses; d fails.
    # → scanned=1 (c), cached=2 (a,b), failed=1 (d); survivors a,b,c in sorted order.
    root = tmp_path / "footage"; root.mkdir()
    for n in ("a.mp4", "b.mp4", "c.mp4", "d.mp4"):
        (root / n).write_bytes(b"x")
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    hits = {"a.mp4", "b.mp4"}
    monkeypatch.setattr(intake.intake_cache, "load",
                        lambda o, p, s, m, *a, **k: _fake_result(intake.Path(p).name)
                        if intake.Path(p).name in hits else None)
    monkeypatch.setattr(intake.intake_cache, "store", lambda o, p, s, r, *a, **k: r)

    def flaky(path, sf=intake.SAMPLE_FPS, embed_cast=True):
        name = intake.Path(path).name
        if name == "d.mp4":
            raise RuntimeError("boom")
        return _fake_result(name)

    monkeypatch.setattr(intake, "_process_clip", flaky)
    result = intake.intake(str(root), str(tmp_path / "out"))
    report = json.loads((tmp_path / "out" / "intake_report.json").read_text())
    assert report == {"scanned": 1, "cached": 2,
                      "failed": [{"source": "d.mp4", "error": "boom"}]}
    assert [c.source for c in result.clips] == ["a.mp4", "b.mp4", "c.mp4"]   # sorted, d dropped


def test_cast_from_original_embeds_unmasked_crops(monkeypatch, tmp_path):
    # the raw bbox crop (RGB, UNMASKED — a silhouette is OOD for OSNet) is what
    # reaches reid.embed; the returned 512-d row becomes the descriptor
    frame = np.zeros((40, 40, 3), np.uint8); frame[10:30, 10:30] = (250, 0, 0)
    monkeypatch.setattr(intake.assembly, "frames_rgb", lambda *a, **k: [frame])
    seen = {}
    def fake_embed(crops):
        seen["n"] = len(crops); seen["shape"] = crops[0].shape
        return [[1.0] + [0.0] * 511]
    monkeypatch.setattr(reid, "embed", fake_embed)
    best = {1: (0.9, 0.0, (20.0, 20.0, 20.0, 20.0))}     # NB: 3-tuple now — no mask
    cast = intake._cast_from_original("a.mp4", best, (40, 40), (40, 40), 30.0)
    assert seen["n"] == 1 and seen["shape"] == (20, 20, 3)   # one unmasked crop embedded
    assert cast[0].descriptor == [1.0] + [0.0] * 511
    assert cast[0].presence >= 0.0


def test_cast_from_original_carries_presence(monkeypatch):
    # presence (on-screen seconds) is threaded from _people_timeline through to the
    # CastEntry — the surfacing rank Task 3 clusters on
    frame = np.zeros((40, 40, 3), np.uint8); frame[10:30, 10:30] = (250, 0, 0)
    monkeypatch.setattr(intake.assembly, "frames_rgb", lambda *a, **k: [frame])
    monkeypatch.setattr(reid, "embed", lambda crops: [[1.0] + [0.0] * 511 for _ in crops])
    best = {1: (0.9, 0.0, (20.0, 20.0, 20.0, 20.0))}
    cast = intake._cast_from_original("a.mp4", best, (40, 40), (40, 40), 30.0, {1: 7.5})
    assert cast[0].presence == 7.5


def test_cast_from_original_grabs_all_tracks_in_one_call(monkeypatch, tmp_path):
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    calls = {"n": 0, "times": None}
    def fake(src, times, fps):
        calls["n"] += 1; calls["times"] = list(times)
        return [frame for _ in times]
    monkeypatch.setattr(intake.assembly, "frames_rgb", fake)
    monkeypatch.setattr(reid, "embed", lambda crops: [[1.0] + [0.0] * 511 for _ in crops])
    best = {1: (0.9, 1.0, (10.0, 10.0, 8.0, 8.0)),
            2: (0.8, 2.0, (10.0, 10.0, 8.0, 8.0))}
    intake._cast_from_original("orig.mp4", best, res=(20, 20), pres=(20, 20), fps=30.0)
    assert calls["n"] == 1 and calls["times"] == [1.0, 2.0]   # ONE decode, both times


def test_intake_flushes_each_clip_as_its_worker_finishes(monkeypatch, tmp_path, capsys):
    """store() runs as each future completes (inside the pool) — freeing that clip's
    crop arrays and writing its cache immediately — not batched after every worker
    drains. Proven by holding clip b's worker until clip a is stored: under a
    store-after-the-pool shape, store(a) can only run once every worker (incl. b) has
    finished, so a_stored never sets while b waits and b's guard trips."""
    from scripts.lib import intake_cache
    from scripts.lib.footage import FootageClip
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    root = tmp_path / "f"; root.mkdir()
    (root / "a.mp4").write_bytes(b"x"); (root / "b.mp4").write_bytes(b"x")
    a_stored = threading.Event()

    def fake_process(path, sample_fps=intake.SAMPLE_FPS, embed_cast=True):
        if str(path).endswith("b.mp4"):
            assert a_stored.wait(timeout=10), \
                "store(a) never ran while b was in flight — intake is not flushing per clip"
        return intake_cache.ClipResult(
            clip=FootageClip(source=str(path).split("/")[-1], dur=1.0, res=(1920, 1080), fps=30.0))

    real_store = intake_cache.store
    def spy_store(out_dir, path, *a, **k):
        r = real_store(out_dir, path, *a, **k)
        if str(path).endswith("a.mp4"):
            a_stored.set()
        return r

    monkeypatch.setattr(intake, "_process_clip", fake_process)
    monkeypatch.setattr(intake.intake_cache, "store", spy_store)
    intake.intake(str(root), str(tmp_path / "out"), jobs=2)

    assert (tmp_path / "out" / ".intake_cache" / "a.mp4" / "clip.json").exists()
    assert (tmp_path / "out" / ".intake_cache" / "b.mp4" / "clip.json").exists()
    assert "✓ a.mp4" in capsys.readouterr().err        # per-clip progress line


def test_intake_without_reid_warns_and_skips_cast(monkeypatch, tmp_path, capsys):
    # The producer half of the §6 split: reID absent must NOT block the scan — windows
    # and scoring still run, the cast embed is skipped (_process_clip gets embed_cast=
    # False), and ONE stderr warning names the remedy. No clip is quarantined for it.
    from scripts.lib import reid
    monkeypatch.setattr(reid, "available", lambda: False)
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)   # no real YOLO (mirrors sibling tests)
    seen = {}
    def fake_process(path, sample_fps=intake.SAMPLE_FPS, embed_cast=True):
        seen["embed_cast"] = embed_cast
        from scripts.lib.footage import FootageClip
        from scripts.lib.intake_cache import ClipResult
        return ClipResult(clip=FootageClip(source="a.mp4", dur=2.0, res=(64, 64), fps=30.0),
                          phashes=[], cast=[])
    monkeypatch.setattr(intake, "_process_clip", fake_process)
    src = tmp_path / "src"; src.mkdir(); (src / "a.mp4").write_bytes(b"x")
    intake.intake(str(src), str(tmp_path / "out"), jobs=1)
    assert seen["embed_cast"] is False
    assert "torchreid" in capsys.readouterr().err


def test_intake_threads_the_real_reid_model_into_the_cache_key(monkeypatch, tmp_path):
    # The companion to the reID-absent test above: when torchreid IS available, intake
    # must thread the REAL reid.MODEL ("osnet_x1_0") into the cache key on BOTH load and
    # store — a scan run WITH reID must not share a key with one run without it (that
    # absent case keys on reid_model=""). The sibling tests cover embed_cast and the ""
    # branch; none pins that the value threaded through IS the public model name.
    from scripts.lib import reid
    monkeypatch.setattr(reid, "available", lambda: True)
    monkeypatch.setattr(reid, "ensure_model", lambda: None)             # no real OSNet build/download
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)   # no real YOLO
    seen = {"load": [], "store": []}
    def spy_load(out, p, sf, model, proxy, *, reid_model):
        seen["load"].append(reid_model); return None                   # force a miss -> the pool runs
    def spy_store(out, p, sf, r, model, proxy, *, reid_model):
        seen["store"].append(reid_model); return r
    monkeypatch.setattr(intake.intake_cache, "load", spy_load)
    monkeypatch.setattr(intake.intake_cache, "store", spy_store)
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS, embed_cast=True: _fake_result(intake.Path(path).name))
    root = _two_clip_root(tmp_path)
    intake.intake(str(root), str(tmp_path / "out"))
    assert reid.MODEL == "osnet_x1_0"                                   # the value the key carries
    assert seen["load"] == [reid.MODEL, reid.MODEL]                     # real model on every load probe
    assert seen["store"] == [reid.MODEL, reid.MODEL]                    # ...and every store
