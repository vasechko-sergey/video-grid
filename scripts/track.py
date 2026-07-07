"""Track the primary subject → route.json (spec §6.1)."""
import argparse, json
from pathlib import Path

# Ultralytics resolves bare model NAMES (auto-download on first use); an absolute
# path would NOT auto-download (landmine, design §12). setup.sh redirects the
# weight cache into models/.
MODEL = "yolo11n-seg.pt"


def _iter_detections(src, model_path=MODEL):
    """Yield (frame_index, [boxes]) using Ultralytics YOLO+ByteTrack.

    Isolated for testability; boxes expose .xywh, .id, .cls like ultralytics.
    """
    from ultralytics import YOLO
    model = YOLO(model_path)
    # imgsz=960: detect on downscaled frames (~10x faster on 4K); ultralytics
    # rescales box coords back to source resolution itself.
    for i, res in enumerate(model.track(src, stream=True, persist=True,
                                        classes=[0], tracker="bytetrack.yaml",
                                        imgsz=960, verbose=False)):
        yield i, (res.boxes if res.boxes is not None else [])


def _seed_track(per_frame, seed, first_n=5):
    """Track id with max IoU vs the seed bbox (centre-format) over first frames.

    The manifest's hero-pin (spec §5.10): resolves "which person" explicitly.
    """
    sx, sy, sw, sh = seed
    sl, st = sx - sw / 2, sy - sh / 2
    best, best_iou = None, 0.0
    for _, dets in per_frame[:first_n]:
        for tid, x, y, w, h in dets:
            l, t = x - w / 2, y - h / 2
            ix = max(0.0, min(sl + sw, l + w) - max(sl, l))
            iy = max(0.0, min(st + sh, t + h) - max(st, t))
            inter = ix * iy
            union = sw * sh + w * h - inter
            if union > 0 and inter / union > best_iou:
                best, best_iou = tid, inter / union
    return best


def _track_features(per_frame):
    """Per-track: frame count, first→last displacement, mean bbox area."""
    feats = {}
    for _, dets in per_frame:
        for tid, x, y, w, h in dets:
            f = feats.setdefault(tid, {"n": 0, "x0": x, "x1": x, "area": 0.0})
            f["n"] += 1
            f["x1"] = x
            f["area"] += w * h
    for f in feats.values():
        f["disp"] = abs(f["x1"] - f["x0"])
        f["area"] /= max(1, f["n"])
    return feats


def _pick_hero(feats, intent):
    """Intent-conditioned scoring (spec §6.1a) — NOT most-frames: the subject
    of an action shot crosses the frame in seconds while a bystander stands in
    frame the whole clip, so raw frame count is biased the wrong way.

    intent: "action" (motion dominates) | "static" (size + duration dominate).
    Returns (hero_id, ambiguous) — ambiguous when top-2 scores within 20%.
    """
    if not feats:
        return None, False
    mx = {k: (max(f[k] for f in feats.values()) or 1.0)
          for k in ("disp", "n", "area")}
    wd, wn, wa = (2.0, 0.5, 0.3) if intent == "action" else (0.0, 1.0, 1.0)

    def score(f):
        return (wd * f["disp"] / mx["disp"] + wn * f["n"] / mx["n"]
                + wa * f["area"] / mx["area"])

    ranked = sorted(feats.items(), key=lambda kv: score(kv[1]), reverse=True)
    ambiguous = (len(ranked) > 1
                 and score(ranked[1][1]) >= 0.8 * score(ranked[0][1]))
    return ranked[0][0], ambiguous


def build_route(src, fps, out, model_path=MODEL, seed_bbox=None,
                intent="action"):
    # hero priority: explicit seed pin (spec §5.10) > intent-conditioned scoring
    per_frame = []
    for idx, boxes in _iter_detections(src, model_path=model_path):
        dets = []
        for b in boxes:
            x, y, w, h = [float(v) for v in b.xywh[0]]
            tid = int(b.id[0]) if b.id is not None else -1
            dets.append((tid, x, y, w, h))
        per_frame.append((idx, dets))

    feats = _track_features(per_frame)
    hero, ambiguous = None, False
    if seed_bbox is not None:
        hero = _seed_track(per_frame, seed_bbox)
    if hero is None:
        hero, ambiguous = _pick_hero(feats, intent)
    # sidecar meta: the orchestrator reads `ambiguous` to fire the §4.1
    # stop-and-report (margin rule) with both candidates' crops
    meta = {"hero": hero, "ambiguous": ambiguous, "intent": intent,
            "features": {str(k): {kk: f[kk] for kk in ("n", "disp", "area")}
                         for k, f in feats.items()}}
    Path(out).with_suffix(".meta.json").write_text(json.dumps(meta))

    route = []
    for idx, dets in per_frame:
        # hero only — NO largest-in-frame fallback: it would splice strangers'
        # coordinates into the route (false teleports for the continuity check);
        # a frame gap is fine, smoothing bridges it
        pick = next((d for d in dets if d[0] == hero), None)
        if pick:
            _, x, y, w, h = pick
            route.append(dict(t=idx / fps, x=x, y=y, w=w, h=h))
    Path(out).write_text(json.dumps(route))
    return route


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--model", default=MODEL,
                    help="yolo11n-seg.pt (default) / yolo11s-seg.pt / "
                         "yolo11m-seg.pt for small/far subjects")
    ap.add_argument("--seed", default=None,
                    help="hero pin: first-frame centre bbox 'x,y,w,h' in source px")
    ap.add_argument("--intent", default="action", choices=["action", "static"],
                    help="hero scoring mode (spec §6.1a)")
    a = ap.parse_args()
    seed = tuple(float(v) for v in a.seed.split(",")) if a.seed else None
    build_route(a.src, a.fps, a.out, model_path=a.model, seed_bbox=seed,
                intent=a.intent)
