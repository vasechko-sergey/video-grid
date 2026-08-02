"""Footage-intake checkpoint (design docs/specs/2026-07-25-intake-parallel-checkpoint-design.md §3).

Persists one clip's CV result so a long scan resumes instead of restarting, and
so a bad clip can be quarantined without losing the batch. `ClipResult`/`CastEntry`
are internal shapes (worker → cache → driver), NOT on-disk contracts a foreign
tool reads, so they are plain dataclasses without a from_dict gate — the on-disk
clip.json embeds FootageClip.to_dict(), which already round-trips. numpy is not
imported: the crop arrives as an ndarray whose .astype method is all `store` needs.

The `model` that produced a result is the DRIVER's fact, so it is passed in, not
imported: a lib module must not depend on a driver (scripts.track), and the
"yolo11n-seg.pt" literal already lives once in track.MODEL — a copy here would be
a third (cap-3 design §5's registered drift landmine).
"""
import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from PIL import Image

from scripts.lib.footage import FootageClip

# Bump when Phase-1 logic changes shape (carve/score/descriptor/phash-point): it
# invalidates every cached clip in one move, so a re-run recomputes rather than
# trusting a result the new code would not produce. The #3 window-band slice bumps
# this (v1 → v2: activity-unit carving + FootageWindow.track_ids); the analysis-proxy
# slice bumps it again (v2 → v3: analysis runs on a downscaled proxy, so a v2 result
# — computed on full-res — must miss, design 2026-08-01). The cast-mask-symmetry
# follow-up bumps it once more (v3 → v4: the cast descriptor is masked again — the
# proxy seg mask upsampled onto the original crop — so a v3 maskless descriptor must
# miss, design §5a). An all-or-nothing version beats a per-field logic hash nobody
# can audit.
CACHE_VERSION = 4


@dataclass
class CastEntry:
    """One surfaced track. Two forms: the worker builds it with a live `crop_rgb`
    array; `store` writes that array as a PNG and returns the cached form carrying
    `crop` (the on-disk path) instead. Phase 2 only ever sees the cached form."""
    source: str
    tid: int
    conf: float
    descriptor: list[float]
    crop: str | None = None
    crop_rgb: object | None = None


@dataclass
class ClipResult:
    clip: FootageClip
    phashes: list[str] = field(default_factory=list)   # hex, parallel to clip.windows
    cast: list[CastEntry] = field(default_factory=list)


def clip_key(path: str, sample_fps: float, model: str, proxy_long_side: int) -> dict:
    """Everything that changes a ClipResult. A mismatch on load → recompute. `model`
    is supplied by the driver (the fact is its), never imported from track.
    `proxy_long_side` is the analysis-proxy scale: change it and every result must
    miss, because the CV ran on differently downscaled pixels (design 2026-08-01)."""
    st = os.stat(path)
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns,
            "sample_fps": float(sample_fps), "model": model,
            "proxy_long_side": int(proxy_long_side), "version": CACHE_VERSION}


def _dir(out_dir: str, path: str) -> Path:
    # keyed on the file NAME (not stem): a.mp4 and a.mov must not collide
    return Path(out_dir) / ".intake_cache" / Path(path).name


def store(out_dir: str, path: str, sample_fps: float, result: ClipResult,
          model: str, proxy_long_side: int) -> ClipResult:
    """Write the crop PNGs, then commit clip.json atomically (os.replace), and
    return the result in cached form (crop_rgb arrays replaced by their PNG paths)
    so a just-scanned clip and a loaded one present one shape to Phase 2 (§2/§3).
    Every write lands via a .tmp sibling + os.replace, so no half-written file is
    ever visible — a crash leaves the previous complete file, never a torn one."""
    d = _dir(out_dir, path)
    crops = d / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    cached = []
    for e in result.cast:
        png = crops / f"t{e.tid}.png"
        tmp_png = crops / f"t{e.tid}.png.tmp"
        Image.fromarray(e.crop_rgb.astype("uint8")).save(tmp_png, format="PNG")
        os.replace(tmp_png, png)                   # atomic; a torn crop never outlives the write
        cached.append(replace(e, crop=str(png), crop_rgb=None))
    payload = {"key": clip_key(path, sample_fps, model, proxy_long_side),
               "clip": result.clip.to_dict(),
               "phashes": list(result.phashes),
               "cast": [{"source": e.source, "tid": e.tid, "conf": e.conf,
                         "descriptor": e.descriptor, "crop": e.crop} for e in cached]}
    tmp = d / "clip.json.tmp"
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, d / "clip.json")               # atomic commit; presence == committed
    return ClipResult(clip=result.clip, phashes=list(result.phashes), cast=cached)


def load(out_dir: str, path: str, sample_fps: float, model: str,
         proxy_long_side: int) -> ClipResult | None:
    """Return the cached-form ClipResult on a key match, else None. Any problem —
    absent, stale, truncated, wrong-shape, or a source file that has since moved —
    reads as a miss, never a crash: the cache is regenerable, and a corrupt entry
    must route the clip back through the worker (where quarantine covers it), not
    abort the scan."""
    f = _dir(out_dir, path) / "clip.json"
    try:
        payload = json.loads(f.read_text())
        if not isinstance(payload, dict):
            return None
        if payload.get("key") != clip_key(path, sample_fps, model, proxy_long_side):
            return None
        clip = FootageClip.from_dict(payload["clip"])
        cast = [CastEntry(source=c["source"], tid=c["tid"], conf=c["conf"],
                          descriptor=c["descriptor"], crop=c["crop"]) for c in payload["cast"]]
        return ClipResult(clip=clip, phashes=payload["phashes"], cast=cast)
    except (FileNotFoundError, OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
