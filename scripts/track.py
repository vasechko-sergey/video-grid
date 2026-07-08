"""Track the primary subject → route.json (spec §6.1)."""
import argparse, json
from pathlib import Path

from scripts.lib import proc
from scripts.lib.models import RoutePoint, TrackMeta, TrackSpec, route_to_json

# Ultralytics resolves bare model NAMES (auto-download on first use); an absolute
# path would NOT auto-download (landmine, design §12). setup.sh redirects the
# weight cache into models/.
MODEL = "yolo11n-seg.pt"


def _probe_meta(src):
    """fps + dims from the source — never trust a caller-supplied default (4K/59.94 footage is the norm)."""
    import json as _j
    r = proc.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=width,height,avg_frame_rate",
                  "-of", "json", src], text=True)
    s = _j.loads(r.stdout)["streams"][0]
    num, den = s["avg_frame_rate"].split("/")
    den = float(den) or 1.0
    fps = float(num) / den
    if fps <= 0:
        raise ValueError(f"{src}: probed fps is {fps} — corrupt/streamed source? re-encode it first")
    return fps, int(s["width"]), int(s["height"])


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


def _track_features(per_frame, src_w=None, src_h=None):
    """Per-track: frame count, first→last displacement, mean bbox area,
    mean speed (px/frame), border share (spec §6.1a candidate discriminators).
    """
    feats = {}
    for _, dets in per_frame:
        for tid, x, y, w, h in dets:
            f = feats.setdefault(tid, {"n": 0, "x0": x, "x1": x, "area": 0.0,
                                        "_prev_x": None, "_speed_sum": 0.0,
                                        "_speed_n": 0, "_border_n": 0})
            f["n"] += 1
            f["x1"] = x
            f["area"] += w * h
            if f["_prev_x"] is not None:
                f["_speed_sum"] += abs(x - f["_prev_x"])
                f["_speed_n"] += 1
            f["_prev_x"] = x
            if src_w is not None and src_h is not None:
                l, t = x - w / 2, y - h / 2
                r, b = x + w / 2, y + h / 2
                margin_x, margin_y = 0.02 * src_w, 0.02 * src_h
                if (l <= margin_x or r >= src_w - margin_x
                        or t <= margin_y or b >= src_h - margin_y):
                    f["_border_n"] += 1
    for f in feats.values():
        f["disp"] = abs(f["x1"] - f["x0"])
        f["area"] /= max(1, f["n"])
        f["speed"] = f["_speed_sum"] / f["_speed_n"] if f["_speed_n"] else 0.0
        f["border"] = (f["_border_n"] / f["n"]) if (src_w is not None
                                                      and src_h is not None) else None
        for k in ("_prev_x", "_speed_sum", "_speed_n", "_border_n"):
            del f[k]
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


def build_route(spec, out):
    """Track the hero subject → list[RoutePoint] + a TrackMeta sidecar (spec §6.1).

    spec: a TrackSpec (scripts/lib/models.py) — carries src/model/seed_bbox/
    intent/fps so the orchestrator can pass a manifest-derived intent instead
    of always "action" (#1).
    """
    # hero priority: explicit seed pin (spec §5.10) > intent-conditioned scoring
    fps, src_w, src_h = spec.fps, None, None
    if fps is None:
        # never trust a caller-supplied default (4K/59.94 footage is the norm) —
        # a wrong fps silently desyncs route t, the crop expression's time axis
        fps, src_w, src_h = _probe_meta(spec.src)

    per_frame = []
    for idx, boxes in _iter_detections(spec.src, model_path=spec.model):
        dets = []
        for b in boxes:
            if b.id is None:
                # unconfirmed ByteTrack detection (normal in first frames /
                # after occlusion) — do NOT fabricate a shared tid=-1 track,
                # it would merge unrelated people into one fake "hero"
                continue
            x, y, w, h = [float(v) for v in b.xywh[0]]
            tid = int(b.id[0])
            dets.append((tid, x, y, w, h))
        per_frame.append((idx, dets))

    feats = _track_features(per_frame, src_w=src_w, src_h=src_h)
    hero, ambiguous = None, False
    if spec.seed_bbox is not None:
        hero = _seed_track(per_frame, spec.seed_bbox)
    if hero is None:
        hero, ambiguous = _pick_hero(feats, spec.intent)
    # sidecar meta: the orchestrator reads `ambiguous` to fire the §4.1
    # stop-and-report (margin rule) with both candidates' crops
    meta = TrackMeta(hero=hero, ambiguous=ambiguous, intent=spec.intent,
                     features={str(k): {kk: f[kk] for kk in
                                        ("n", "disp", "area", "speed", "border")}
                               for k, f in feats.items()})
    Path(out).with_suffix(".meta.json").write_text(json.dumps(meta.to_dict()))

    route = []
    for idx, dets in per_frame:
        # hero only — NO largest-in-frame fallback: it would splice strangers'
        # coordinates into the route (false teleports for the continuity check);
        # a frame gap is fine, smoothing bridges it
        pick = next((d for d in dets if d[0] == hero), None)
        if pick:
            _, x, y, w, h = pick
            route.append(RoutePoint(t=idx / fps, x=x, y=y, w=w, h=h))
    route_to_json(route, out)
    return route


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--fps", type=float, default=None,
                    help="override probed fps (default: probe the source — "
                         "never trust a caller-supplied default)")
    ap.add_argument("--model", default=MODEL,
                    help="yolo11n-seg.pt (default) / yolo11s-seg.pt / "
                         "yolo11m-seg.pt for small/far subjects")
    ap.add_argument("--seed", default=None,
                    help="hero pin: first-frame centre bbox 'x,y,w,h' in source px")
    ap.add_argument("--intent", default="action", choices=["action", "static"],
                    help="hero scoring mode (spec §6.1a)")
    a = ap.parse_args()
    seed = tuple(float(v) for v in a.seed.split(",")) if a.seed else None
    spec = TrackSpec(src=a.src, model=a.model, seed_bbox=seed, intent=a.intent, fps=a.fps)
    build_route(spec, a.out)
