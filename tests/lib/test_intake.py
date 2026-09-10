import json
import shutil
import threading
import types
import numpy as np
import pytest
from scripts import intake
from scripts.lib import carve, footage, reid
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
    assert all(carve.DEFAULT_BAND[0] <= d <= carve.DEFAULT_BAND[1] + 1e-6 for _, d in spans)
    assert len({round(d, 3) for _, d in spans}) > 1                 # NOT one uniform tile size


def test_carve_splits_on_presence_transition():
    # empty 0–3, person 3–6 → boundary at 3
    tl = _line([(0, 0), (1, 0), (2, 0), (3, 1), (4, 1), (5, 1)])
    spans = intake.carve_windows([], tl, [], 1.0, 6.0)
    assert any(abs(s - 3.0) < 1e-6 for s, _ in spans)


def test_carve_short_clip_yields_one_window():
    spans = intake.carve_windows([], _line([(0, 1)]), [], 1.0, 0.8)   # < carve.DEFAULT_BAND[0]
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


def _w(motion, shake, present=1.0, dur=2.0, people=1):
    return footage.FootageWindow(start=0.0, dur=dur, shot_type="wide", people=people,
                                 motion=motion, shake=shake, present=present)


def _clip(source, windows):
    return footage.FootageClip(source=source, dur=60.0, res=(1920, 1080), fps=30.0,
                               windows=windows)


def test_percentile_rank_is_uniform_tie_aware_and_bounded():
    assert intake._percentile_rank([]) == []
    assert intake._percentile_rank([7.0]) == [0.5]
    assert intake._percentile_rank([10.0, 0.0, 5.0]) == [1.0, 0.0, 0.5]
    assert intake._percentile_rank([3.0, 3.0]) == [0.5, 0.5]      # a tie shares its mid-rank


def test_score_is_a_percentile_not_an_absolute_blend():
    # five windows differing only in motion: their scores must span [0, 1] evenly.
    # The old absolute blend put all five inside a 0.09-wide band above 0.61 (§1.1).
    ws = [_w(motion=m, shake=0.001) for m in (0.01, 0.02, 0.03, 0.04, 0.05)]
    intake.score_pool([_clip("a.mp4", ws)])
    assert [w.score for w in ws] == [0.0, 0.25, 0.5, 0.75, 1.0]


def test_score_ignores_a_factor_that_is_constant_across_the_pool():
    # present is constant BY CONSTRUCTION (carve splits on presence transitions,
    # §1.1). Halving it for every window must not reorder anything.
    a = [_w(motion=m, shake=0.001, present=1.0) for m in (0.01, 0.05, 0.03)]
    b = [_w(motion=m, shake=0.001, present=0.5) for m in (0.01, 0.05, 0.03)]
    intake.score_pool([_clip("a.mp4", a)])
    intake.score_pool([_clip("b.mp4", b)])
    assert [w.score for w in a] == [w.score for w in b]


def test_motion_ranks_within_its_own_clip_when_the_clip_is_big_enough():
    # calm clip and busy clip, CLIP_POOL_MIN windows each. The calm clip's best
    # moment must outscore the busy clip's worst, which pool-wide ranking forbids.
    calm = [_w(motion=m, shake=0.001) for m in (0.001, 0.002, 0.003, 0.004, 0.010)]
    busy = [_w(motion=m, shake=0.001) for m in (0.020, 0.030, 0.040, 0.050, 0.060)]
    intake.score_pool([_clip("calm.mp4", calm), _clip("busy.mp4", busy)])
    assert calm[-1].score > busy[0].score


def test_a_clip_below_clip_pool_min_falls_back_to_the_pool():
    # 2 windows is no distribution; ranking them within the clip would hand the
    # stronger one a flat 1.0 — tying the shoot's genuinely busiest window — no
    # matter how weak it is against the rest of the shoot.
    small = [_w(motion=0.001, shake=0.001), _w(motion=0.002, shake=0.001)]
    big = [_w(motion=m, shake=0.001) for m in (0.10, 0.20, 0.30, 0.40, 0.50)]
    intake.score_pool([_clip("small.mp4", small), _clip("big.mp4", big)])
    assert small[1].score < big[-1].score         # pool-ranked, so it cannot tie the top
    assert small[0].score != small[1].score       # ...but the two are still ordered


def test_score_penalises_shake_across_the_pool():
    ws = [_w(motion=0.02, shake=s) for s in (0.001, 0.009)]
    intake.score_pool([_clip("a.mp4", ws)])
    assert ws[0].score > ws[1].score


def test_equal_motion_and_stability_weights_make_a_swapped_pair_tie():
    """W_MOTION == W_STABLE, so a window with (motion rank 1.0, stability rank 0.25) must score
    exactly as one with the pair SWAPPED — that equality IS the trade-off design §4.4 says the
    weights set, and nothing else in the suite pins it.

    That equality is NOT free. score_pool's blend is the three-term left-associative sum
    `(W_PRESENT*present + W_MOTION*m) + W_STABLE*s`, so swapping m and s RE-ASSOCIATES the sum
    rather than merely commuting two operands, and re-association is not bit-equal in general:
    on this fixture's own rank grid {0, .25, .5, .75, 1}, 6 of the 20 off-diagonal (m, s) pairs
    break on swap (e.g. m=.25/s=.5 gives 0x1.4cccccccccccdp-1 against 0x1.4cccccccccccep-1 —
    different bits, same real value 0.65). _percentile_rank ties on exact ==, so a broken pair
    would land on adjacent ranks instead of sharing one. This fixture's pair, (1.0, 0.25), is
    deliberately one that DOES survive re-association — checked by direct computation, not
    assumed. Re-picking the fixture's shake values can land on a pair that breaks; whoever does
    that must re-check bit-equality against the new pair, not assume it holds."""
    ws = [_w(motion=m, shake=s) for m, s in
          ((0.05, 0.007), (0.02, 0.001), (0.03, 0.005), (0.04, 0.003), (0.01, 0.009))]
    intake.score_pool([_clip("a.mp4", ws)])
    assert ws[0].score == ws[1].score


def test_score_pool_fills_description_from_the_motion_rank():
    ws = [_w(motion=m, shake=0.001, people=p)
          for m, p in ((0.001, 0), (0.002, 1), (0.003, 2), (0.004, 2), (0.900, 2))]
    intake.score_pool([_clip("a.mp4", ws)])
    assert ws[0].description == "no people, wide, calm"
    assert ws[1].description == "1 person, wide, calm"
    assert ws[2].description == "2 people, wide, dynamic"   # rank EXACTLY DYNAMIC_RANK — pins >=
    assert ws[-1].description == "2 people, wide, dynamic"


def test_describe_reads_a_rank_not_a_raw_motion():
    assert intake._describe(1, "medium", 0.9) == "1 person, medium, dynamic"
    assert intake._describe(0, "wide", 0.1) == "no people, wide, calm"
    # 0.4 straddles the two thresholds: >= the deleted MOTION_PEAK (0.35) but < DYNAMIC_RANK
    # (0.5), so the old code said "dynamic" and the new one says "calm". The two assertions
    # above cannot tell the constants apart (Global Constraint 8).
    assert intake._describe(1, "medium", 0.4) == "1 person, medium, calm"


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


def test_the_representative_crop_is_the_largest_not_the_medoid():
    # Three members of ONE identity. The medoid (closest to the centroid) carries a
    # tiny crop; another member carries a big one. Presence and crop area are
    # anti-correlated on real footage (Spearman -0.486, design §0.4), so the pick
    # must be by pixels, not by embedding centrality.
    from scripts.lib.intake_cache import CastEntry
    tiny = np.zeros((12, 13, 3), "uint8")            # 13x12 -- the run's worst
    big = np.full((373, 535, 3), 200, "uint8")
    mid = np.zeros((80, 60, 3), "uint8")
    d = _desc(1.0)
    entries = [CastEntry("a.mp4", 1, 0.9, list(d), presence=9.0, crop_rgb=tiny),
               CastEntry("a.mp4", 2, 0.9, list(d), presence=1.0, crop_rgb=big),
               CastEntry("a.mp4", 3, 0.9, list(d), presence=1.0, crop_rgb=mid)]
    picked = intake.surface_crops(entries, max_cast=8)
    assert len(picked) == 1
    assert picked[0].crop_rgb.shape[:2] == (373, 535)


def test_the_representative_descriptor_is_still_the_centroid():
    # The picture changes; the identity mathematics does not. Every downstream
    # consumer (hero.resolve, track.build_route, cast.json) reads `descriptor`.
    from scripts.lib.intake_cache import CastEntry
    big = np.full((300, 300, 3), 200, "uint8")
    entries = [CastEntry("a.mp4", 1, 0.9, _emb(0), presence=5.0,
                         crop_rgb=np.zeros((4, 4, 3), "uint8")),
               CastEntry("a.mp4", 2, 0.9, _emb(0), presence=5.0, crop_rgb=big)]
    picked = intake.surface_crops(entries, max_cast=8)
    assert picked[0].descriptor == _emb(0)           # the re-L2-normed mean, unchanged
    assert picked[0].presence == 10.0                # summed, unchanged
    assert picked[0].crop_rgb.shape[:2] == (300, 300)


def test_the_representative_descriptor_is_recomputed_not_the_largest_members_own():
    # The sibling test above gives both members the SAME embedding, so the centroid
    # and either member's own descriptor are bit-identical and the assertion cannot
    # tell "recompute the centroid" apart from "just take the largest member's own
    # descriptor" (task-8 mutation battery row 13, design 2026-09-08). These two
    # differ (3-4-5 triangle, cosine distance 0.04 < CLUSTER_COS so they still
    # cluster), and the mean of (3, 4) and (4, 3) lands EXACTLY on the diagonal, so
    # the re-L2-normed centroid is provably neither raw vector.
    from scripts.lib.intake_cache import CastEntry
    v_small, v_big = _desc(3.0, 4.0), _desc(4.0, 3.0)
    small = np.zeros((4, 4, 3), "uint8")
    big = np.full((300, 300, 3), 200, "uint8")
    entries = [CastEntry("a.mp4", 1, 0.9, v_small, presence=5.0, crop_rgb=small),
               CastEntry("a.mp4", 2, 0.9, v_big, presence=5.0, crop_rgb=big)]
    picked = intake.surface_crops(entries, max_cast=8)
    assert len(picked) == 1
    assert picked[0].crop_rgb.shape[:2] == (300, 300)      # the largest crop still wins
    assert picked[0].descriptor != v_small and picked[0].descriptor != v_big
    diag = 1 / 2 ** 0.5
    assert picked[0].descriptor[0] == pytest.approx(diag)
    assert picked[0].descriptor[1] == pytest.approx(diag)
    assert all(x == 0.0 for x in picked[0].descriptor[2:])


def test_a_member_with_no_crop_never_wins_the_representative_slot():
    from scripts.lib.intake_cache import CastEntry
    small = np.zeros((4, 4, 3), "uint8")
    entries = [CastEntry("a.mp4", 1, 0.9, _desc(1.0), presence=9.0),   # no crop at all
               CastEntry("a.mp4", 2, 0.9, _desc(1.0), presence=1.0, crop_rgb=small)]
    picked = intake.surface_crops(entries, max_cast=8)
    assert picked[0].crop_rgb is not None            # the 4x4 wins over nothing


def test_a_cached_form_crop_is_sized_from_its_png(tmp_path):
    from scripts.lib.intake_cache import CastEntry
    wide = tmp_path / "wide.png"
    _Img.fromarray(np.full((200, 400, 3), 180, "uint8")).save(wide)
    entries = [CastEntry("a.mp4", 1, 0.9, _desc(1.0), presence=9.0,
                         crop_rgb=np.zeros((10, 10, 3), "uint8")),
               CastEntry("a.mp4", 2, 0.9, _desc(1.0), presence=1.0, crop=str(wide))]
    picked = intake.surface_crops(entries, max_cast=8)
    assert picked[0].crop == str(wide)               # the cached PNG's header decided it


def test_save_cast_candidates_refuses_an_entry_with_no_crop_at_all(tmp_path):
    # surface_crops never RAISES on a crop-less member (it just never wins the
    # representative slot, test_a_member_with_no_crop_never_wins_the_representative_slot
    # above) — but when EVERY member of a cluster carries neither crop form, the pick
    # itself has none, and save_cast_candidates must refuse it BY NAME rather than
    # reach Image.fromarray(None.astype(...)) as a bare AttributeError. This is the
    # refusal _crop_area's own comment already claimed existed (design 2026-09-08
    # task 5 — the final whole-branch review).
    from scripts.lib.intake_cache import CastEntry
    e = CastEntry("a.mp4", tid=7, conf=0.9, descriptor=_desc(1.0))   # crop=None, crop_rgb=None
    with pytest.raises(ValueError, match="a.mp4") as exc:
        intake.save_cast_candidates([e], str(tmp_path))
    assert "7" in str(exc.value)


def test_save_cast_candidates_records_each_crops_pixel_size(tmp_path):
    from scripts.lib.intake_cache import CastEntry
    red = np.zeros((19, 16, 3), "uint8"); red[:, :, 0] = 255      # 16x19, the run's ep1
    blue = np.zeros((373, 535, 3), "uint8"); blue[:, :, 2] = 255
    entries = [CastEntry("a.mp4", 1, 0.9, _desc(1.0), crop_rgb=red),
               CastEntry("b.mp4", 1, 0.8, _desc(0.0, 1.0), crop_rgb=blue)]
    manifest = intake.save_cast_candidates(entries, str(tmp_path))
    by_source = {m["source"]: m for m in manifest}
    assert by_source["a.mp4"]["crop_px"] == [16, 19]
    assert by_source["b.mp4"]["crop_px"] == [535, 373]
    # read from the file the human will actually open, not from the entry
    for m in manifest:
        assert _Img.open(m["crop"]).size == tuple(m["crop_px"])

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
    # Phase 2 ran: description is pool-derived, never a Phase-1 default
    assert all(w.description for c in result.clips for w in c.windows)


def test_cache_version_is_9_for_the_carve_band_key():
    from scripts.lib import intake_cache
    assert intake_cache.CACHE_VERSION == 9


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
    monkeypatch.setattr(intake, "carve_windows", lambda *a, **k: [(0.0, 2.0)])
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


def _scored_result(name):
    """A fake ClipResult with windows whose motion differs BETWEEN clips — the pool
    must have something to order for a percentile to be observable at all.

    `_fake_result` above carries NO windows, which is why the three existing
    byte-identity proofs cannot see a scoring bug: with nothing to rank, any
    score_pool agrees with any other. 3 windows/clip is deliberately below
    CLIP_POOL_MIN (5), so motion ranks across the WHOLE pool and clip a's score
    genuinely depends on clip b's windows."""
    from scripts.lib.footage import FootageClip, FootageWindow
    base = 0.01 if name == "a.mp4" else 0.05
    ws = [FootageWindow(start=float(i), dur=2.0, shot_type="wide", people=1,
                        motion=base + i / 1000, shake=0.001, present=1.0)
          for i in range(3)]
    return intake.ClipResult(clip=FootageClip(source=name, dur=10.0, res=(100, 100),
                                              fps=30.0, windows=ws),
                             phashes=["0" * 16] * 3, cast=[])


@pytest.mark.parametrize("bad", [0, -1, True, "3", 3.0])
def test_jobs_validation_rejects(tmp_path, bad):
    root = _two_clip_root(tmp_path)
    with pytest.raises(ValueError, match="jobs"):
        intake.intake(str(root), str(tmp_path / "out"), jobs=bad)


@pytest.mark.parametrize("bad", [(1.2,), (4.0, 1.2), (True, 4.0), ("1.2", 4.0)])
def test_band_validation_rejects(tmp_path, bad):
    # each `bad` trips a DIFFERENT clause of the compound check: a non-2-element
    # band, an inverted (win_min > win_max) band, a bool element, and a non-number.
    root = _two_clip_root(tmp_path)
    with pytest.raises(ValueError, match="band"):
        intake.intake(str(root), str(tmp_path / "out"), band=bad)


def test_ensure_model_runs_before_any_worker(monkeypatch, tmp_path):
    root = _two_clip_root(tmp_path)
    monkeypatch.setattr(intake.intake_cache, "load", lambda *a, **k: None)
    monkeypatch.setattr(intake.intake_cache, "store", lambda o, p, s, r, *a, **k: r)
    seen = []
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: seen.append("ensure"))
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS, embed_cast=True, band=carve.DEFAULT_BAND:
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

    def fake_pe(path, sf=intake.SAMPLE_FPS, embed_cast=True, band=carve.DEFAULT_BAND):
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
                        lambda path, sf=intake.SAMPLE_FPS, embed_cast=True, band=carve.DEFAULT_BAND:
                        _fake_result(intake.Path(path).name))
    intake.intake(str(root), str(tmp_path / "o1"), jobs=1)
    intake.intake(str(root), str(tmp_path / "o3"), jobs=3)
    assert (tmp_path / "o1" / "FOOTAGE.json").read_text() == (tmp_path / "o3" / "FOOTAGE.json").read_text()


def test_only_cache_misses_reach_the_pool(monkeypatch, tmp_path):
    root = _two_clip_root(tmp_path); out = tmp_path / "out"
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    submitted = []
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS, embed_cast=True, band=carve.DEFAULT_BAND:
                        (submitted.append(intake.Path(path).name),
                         _fake_result(intake.Path(path).name))[1])
    intake.intake(str(root), str(out))                 # first run: both are misses
    assert sorted(submitted) == ["a.mp4", "b.mp4"]
    submitted.clear()
    intake.intake(str(root), str(out))                 # second run: both cached
    assert submitted == []                             # nothing re-submitted
    submitted.clear()
    shutil.rmtree(out / ".intake_cache" / "b.mp4")     # invalidate just b
    intake.intake(str(root), str(out))
    assert submitted == ["b.mp4"]                       # only the miss reruns


def test_output_is_byte_identical_across_a_cache_mix(monkeypatch, tmp_path):
    """score is a percentile over the WHOLE pool, so every window's number depends
    on every other window's. A resume that ranked only the clips it re-scanned
    would differ here — and would pass the all-cold and all-cached proofs above,
    which is why this arm exists (design 2026-08-06-intake-motion-scoring §4.5)."""
    root = _two_clip_root(tmp_path); out = tmp_path / "out"
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS, embed_cast=True, band=carve.DEFAULT_BAND:
                        _scored_result(intake.Path(path).name))
    intake.intake(str(root), str(out))
    cold = (out / "FOOTAGE.json").read_text()
    # load-bearing: without it a score_pool writing ONE number everywhere would
    # satisfy the byte-identity check below and prove nothing.
    assert len({json.loads(cold)["clips"][0]["windows"][i]["score"] for i in range(3)}) > 1
    shutil.rmtree(out / ".intake_cache" / "b.mp4")     # a stays cached, b re-scans
    intake.intake(str(root), str(out))
    assert (out / "FOOTAGE.json").read_text() == cold


def test_fresh_bypasses_the_cache(monkeypatch, tmp_path):
    root = _two_clip_root(tmp_path); out = tmp_path / "out"
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: None)
    submitted = []
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS, embed_cast=True, band=carve.DEFAULT_BAND:
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
                        lambda path, sf=intake.SAMPLE_FPS, embed_cast=True, band=carve.DEFAULT_BAND:
                        _fake_result(intake.Path(path).name))
    intake.intake(str(root), str(out))
    a = (out / "FOOTAGE.json").read_text()
    intake.intake(str(root), str(out))                 # all cache hits
    b = (out / "FOOTAGE.json").read_text()
    assert a == b


def test_a_bad_clip_is_quarantined_not_fatal(monkeypatch, tmp_path):
    root = _two_clip_root(tmp_path); out = tmp_path / "out"
    _stub_cache(monkeypatch)

    def flaky(path, sf=intake.SAMPLE_FPS, embed_cast=True, band=carve.DEFAULT_BAND):
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

    def flaky(path, sf=intake.SAMPLE_FPS, embed_cast=True, band=carve.DEFAULT_BAND):
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

    def fake_process(path, sample_fps=intake.SAMPLE_FPS, embed_cast=True, band=carve.DEFAULT_BAND):
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
    def fake_process(path, sample_fps=intake.SAMPLE_FPS, embed_cast=True, band=carve.DEFAULT_BAND):
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
    def spy_load(out, p, sf, model, proxy, *, reid_model, band):
        seen["load"].append(reid_model); return None                   # force a miss -> the pool runs
    def spy_store(out, p, sf, r, model, proxy, *, reid_model, band):
        seen["store"].append(reid_model); return r
    monkeypatch.setattr(intake.intake_cache, "load", spy_load)
    monkeypatch.setattr(intake.intake_cache, "store", spy_store)
    monkeypatch.setattr(intake, "_process_clip",
                        lambda path, sf=intake.SAMPLE_FPS, embed_cast=True, band=carve.DEFAULT_BAND:
                        _fake_result(intake.Path(path).name))
    root = _two_clip_root(tmp_path)
    intake.intake(str(root), str(tmp_path / "out"))
    assert reid.MODEL == "osnet_x1_0"                                   # the value the key carries
    assert seen["load"] == [reid.MODEL, reid.MODEL]                     # real model on every load probe
    assert seen["store"] == [reid.MODEL, reid.MODEL]                    # ...and every store


def test_intake_refuses_an_out_dir_equal_to_the_footage_root(tmp_path):
    with pytest.raises(ValueError, match="footage folder itself"):
        intake.intake(str(tmp_path), str(tmp_path))


def test_intake_refuses_before_fetching_the_model(tmp_path, monkeypatch):
    """The guard sits above ensure_model(), so the refusal costs no weights fetch.

    ensure_model is the first step with a real cost, and therefore the only one
    whose ordering a test can see: the out.mkdir() above it is UNOBSERVABLE for
    this input, because out_dir IS the footage root, which already exists, so
    exist_ok=True does nothing. The mutation battery caught that — the earlier
    version of this test asserted the directory was unchanged and stayed green
    with the guard moved below the mkdir."""
    root = tmp_path / "footage"
    root.mkdir()
    called = []
    monkeypatch.setattr(intake, "ensure_model", lambda *a, **k: called.append(a))
    with pytest.raises(ValueError):
        intake.intake(str(root), str(root))
    assert called == []
    assert set(p.name for p in root.iterdir()) == set()   # and no artifact written


def test_default_band_has_exactly_one_definition():
    # intake must not re-declare the numbers: one constant, imported.
    assert carve.DEFAULT_BAND == (1.2, 4.0)
    assert not hasattr(intake, "WIN_MIN") and not hasattr(intake, "WIN_MAX")


def test_carve_windows_honours_a_wider_band():
    # A 6s span with no interior peak is one flat unit sized by win_max: at the
    # default band that is 4.0s, at a (1.2, 6.0) band it is the whole 6.0s.
    times = [i * 0.5 for i in range(13)]                   # 0.0 .. 6.0
    line = [(t, 0, None, [], {}) for t in times]
    mags = [1.0] * len(times)
    narrow = intake.carve_windows([], line, mags, 2.0, 6.0)
    wide = intake.carve_windows([], line, mags, 2.0, 6.0, band=(1.2, 6.0))
    assert max(d for _, d in narrow) <= 4.0
    assert max(d for _, d in wide) > 4.0


def test_intake_records_the_band_it_carved_with(sample_clip, tmp_path):
    out = tmp_path / "run"
    f = intake.intake(str(sample_clip.parent), str(out), band=(1.0, 3.0))
    assert f.band == (1.0, 3.0)
    assert json.loads((out / "FOOTAGE.json").read_text())["band"] == [1.0, 3.0]


def test_intake_records_the_default_band_when_none_is_given(sample_clip, tmp_path):
    f = intake.intake(str(sample_clip.parent), str(tmp_path / "run"))
    assert f.band == carve.DEFAULT_BAND


def test_separated_is_the_pool_minus_its_largest_tie_group():
    assert intake._separated([]) == 0
    assert intake._separated([0.5, 0.5, 0.5, 0.5]) == 0        # one tie group: nothing told apart
    assert intake._separated([0.0, 1.0]) == 1                   # two groups of one
    assert intake._separated([0.5, 0.5, 0.5, 0.9]) == 1         # the outlier alone


def test_score_pool_reports_a_presence_term_that_separated_nothing():
    # every window holds people for its whole span — the 2026-06 run's shape (99.8%).
    # shake varies (independently of motion) too, so a bug that mislabelled or
    # zeroed the "shake" key would not hide behind an all-constant fixture the way
    # the original version of this test did (review follow-up, MINOR 1).
    ws = [_w(dur=2.0, people=1, motion=m, shake=s, present=1.0)
          for m, s in zip((0.1, 0.2, 0.3, 0.4, 0.5, 0.6), (0.6, 0.5, 0.4, 0.3, 0.2, 0.1))]
    rep = intake.score_pool([_clip("a.mp4", ws)])
    assert rep["windows"] == 6
    assert rep["separated"]["present"] == 0
    assert rep["separated"]["motion"] == 5      # six distinct motions, largest tie 1
    assert rep["separated"]["shake"] == 5       # six distinct shakes, largest tie 1


def test_score_pool_reports_a_presence_term_that_did_separate():
    ws = [_w(dur=2.0, people=1, motion=0.5, shake=0.0, present=p)
          for p in (0.0, 0.25, 0.5, 0.75, 1.0, 1.0)]
    rep = intake.score_pool([_clip("a.mp4", ws)])
    assert rep["separated"]["present"] == 4     # six windows, largest tie group is the two 1.0s


def test_score_pool_on_an_empty_pool_reports_zero_windows_not_none():
    # an empty pool is a MEASUREMENT (zero windows), not an absent one. Footage.scoring
    # is None only on an artifact written before this slice. Folded in the old
    # "...is_a_no_op" test's other empty shape (a clip that carved zero windows) --
    # that test passed only because it discarded score_pool's return value, which is
    # no longer a no-op's `None` but this same report (review follow-up, MINOR 2).
    empty = {"windows": 0, "separated": {"present": 0, "motion": 0, "shake": 0}}
    assert intake.score_pool([]) == empty
    assert intake.score_pool([_clip("a.mp4", [])]) == empty


def test_presence_is_ranked_across_the_pool_not_summed_absolutely():
    # Reverting `presence` to a raw absolute fraction (W_PRESENT * w.present, summed
    # straight into the blend instead of through _percentile_rank) must change the
    # ORDERING it produces, not just its bit pattern. Three windows, deliberately
    # mixed presence (0.0 / 0.9 / 1.0) so the raw and ranked scales genuinely
    # disagree -- not two separate all-constant pools compared against each other,
    # which the original version of this test did: that comparison is mathematically
    # invariant to swapping "ranked" for "raw absolute" (both are still a per-call
    # CONSTANT shift of every window alike, and the final _percentile_rank(blend) is
    # shift-invariant), so it could only ever fail by a float re-association accident
    # of its specific numbers -- confirmed by hand: swapping in either
    # ((0.0,1.0),(0.25,0.75),(0.75,0.25)) or ((0.1,0.6),(0.3,0.3),(0.6,0.1)) for the
    # (motion, shake) pairs makes the OLD absolute code pass too, silently losing all
    # discriminating power (review follow-up, IMPORTANT 1).
    #
    # Here the divergence is a real value, not a coincidence of bit re-association:
    # w1 has no subject at all but the best motion+shake in the pool; w2 has a
    # subject for 90% of its span but the worst motion; w3 is fully present with
    # middling motion+shake. Hand-verified (and cross-checked against a live run of
    # score_pool, not just this assertion):
    #   ranked   presence = [0.0, 0.5, 1.0]  -> blend = [.49, .43, .58] -> score [.5, 0, 1]
    #   raw/old  presence = [0.0, 0.9, 1.0]  -> blend = [.49, .606, .58] -> score [0, 1, .5]
    # w1 and w2 fully swap rank (w1 last under the old code, first under the new one)
    # -- an order flip of ~0.12 in blend terms, three orders of magnitude past any
    # float rounding noise, so this discriminates for the reason the design gives,
    # not by luck (design 2026-09-10 §3.1).
    w1 = _w(dur=2.0, people=0, motion=0.9, shake=0.5, present=0.0)   # no subject, best motion+shake
    w2 = _w(dur=2.0, people=1, motion=0.1, shake=0.5, present=0.9)   # subject 90%, worst motion
    w3 = _w(dur=2.0, people=1, motion=0.5, shake=0.9, present=1.0)   # fully present, middling rest
    ws = [w1, w2, w3]
    intake.score_pool([_clip("a.mp4", ws)])
    assert [w.score for w in ws] == [0.5, 0.0, 1.0]


def test_a_middling_peopleless_window_can_outrank_the_worst_peopled_one():
    # Task 2's own commit message: under the deleted absolute code, a people-free
    # window needed a mean rank of W_PRESENT / (W_MOTION + W_STABLE) ~= 0.786 across
    # motion and shake merely to TIE the worst window that had people in it -- a
    # fixed bar, the SAME on every pool, because a raw present of 0 or 1 contributes
    # 0 or 0.44 to the blend with no reference to the rest of the shoot. That claim
    # was never asserted anywhere (review follow-up, IMPORTANT 2) -- the two tests
    # that vary `present` within a pool assert only on rep["separated"]["present"],
    # never on `w.score`.
    #
    # This pool is shaped like the real one (mostly present, one absent window, per
    # the design's 1505-of-1508 real ratio): 9 of 10 windows fully present, 1 not.
    # Ranking that ratio makes "present" and "absent" only ~0.556 apart (not the raw
    # scale's full 1.0), so the peopleless window needs nowhere near the old 0.786
    # bar -- a middling rank (~0.56 on each of motion and shake, not the extreme
    # 1.0 the earlier test used) already beats the worst peopled window outright,
    # which the deleted absolute code could never do at ANY pool shape, since its
    # 0.786 bar did not move with the pool (design 2026-09-10 §3, §0.1).
    assert round(intake.W_PRESENT / (intake.W_MOTION + intake.W_STABLE), 3) == 0.786
    worst_present = _w(dur=2.0, people=2, motion=0.01, shake=0.99, present=1.0)  # bottom of both
    peopleless = _w(dur=2.0, people=0, motion=0.5, shake=0.5, present=0.0)       # middling, not extreme
    padding = [_w(dur=2.0, people=2, motion=m, shake=m, present=1.0)
               for m in (0.1, 0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 0.9)]   # fills out "mostly present"
    ws = [worst_present, peopleless] + padding
    intake.score_pool([_clip("a.mp4", ws)])
    assert peopleless.score > worst_present.score


def test_presence_ranks_pool_wide_even_when_every_clip_is_big_enough_to_rank_alone():
    # `motion` ranks per-clip once a clip reaches CLIP_POOL_MIN windows (lines
    # 179-184) precisely because motion is a within-shot question. `present` is
    # deliberately NOT given that override -- "does this window hold the subject"
    # is a whole-shoot comparison (design 2026-09-10 §3) -- but nothing in the
    # existing suite would notice if a future edit mirrored motion_fit's override
    # onto presence: every pre-existing fixture gives every window in one
    # score_pool call the SAME present value, so a per-clip presence rank and a
    # pool-wide one produce an identical constant shift either way (review
    # follow-up, CRITICAL).
    #
    # Both clips here carry exactly CLIP_POOL_MIN windows -- big enough that a
    # per-clip override on `presence`, if one existed, would actually fire (not
    # silently no-op below the floor). Clip A is present the whole time, clip B
    # never. Pool-wide, that is two same-size tie groups: separated ==
    # 2*n - n == n. A per-clip rank instead ties each clip's own CONSTANT present
    # value at ITS OWN mid-rank (0.5) -- both clips collapse to the identical
    # constant across the whole pool and separated collapses to 0.
    n = intake.CLIP_POOL_MIN
    assert n == 5     # the fixture below assumes clips of exactly this size
    a = [_w(dur=2.0, people=1, motion=0.1 * i, shake=0.0, present=1.0) for i in range(1, n + 1)]
    b = [_w(dur=2.0, people=1, motion=0.1 * i, shake=0.0, present=0.0) for i in range(1, n + 1)]
    rep = intake.score_pool([_clip("a.mp4", a), _clip("b.mp4", b)])
    assert rep["separated"]["present"] == n


def test_intake_builds_footage_with_the_scoring_report_through_validation():
    # The report must pass Footage.__post_init__, not be assigned onto a built object:
    # a field that skips its own validation is a field nothing checks.
    ws = [_w(dur=2.0, people=1, motion=m, shake=0.0, present=1.0) for m in (0.1, 0.9)]
    clips = [_clip("a.mp4", ws)]
    scoring = intake.score_pool(clips)
    f = footage.Footage(clips=clips, band=(1.2, 4.0), scoring=scoring)
    assert f.scoring["windows"] == 2
    assert set(f.scoring["separated"]) == set(footage.SCORE_TERMS)
