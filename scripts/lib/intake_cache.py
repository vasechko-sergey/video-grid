"""Footage-intake checkpoint (design docs/specs/2026-07-25-intake-parallel-checkpoint-design.md §3).

Persists one clip's CV result so a long scan resumes instead of restarting, and
so a bad clip can be quarantined without losing the batch. `ClipResult`/`CastEntry`
are internal shapes (worker → cache → driver), NOT on-disk contracts a foreign
tool reads, so they are plain dataclasses without a from_dict gate — the on-disk
clip.json embeds FootageClip.to_dict(), which already round-trips. numpy is not
imported: the crop arrives as an ndarray whose .astype method is all `store` needs.
"""
import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from PIL import Image

from scripts.lib.footage import FootageClip
from scripts.track import MODEL

# Bump when Phase-1 logic changes shape (carve/score/descriptor/phash-point): it
# invalidates every cached clip in one move, so a re-run recomputes rather than
# trusting a result the new code would not produce. The #3 window-band slice bumps
# this. An all-or-nothing version beats a per-field logic hash nobody can audit.
CACHE_VERSION = 1


@dataclass
class CastEntry:
    """One surfaced track. Two forms: the worker builds it with a live `crop_rgb`
    array; `store` writes that array as a PNG and returns the cached form carrying
    `crop` (the on-disk path) instead. Phase 2 only ever sees the cached form."""
    source: str
    tid: int
    conf: float
    descriptor: list
    crop: str | None = None
    crop_rgb: object | None = None


@dataclass
class ClipResult:
    clip: FootageClip
    phashes: list = field(default_factory=list)   # hex strings, parallel to clip.windows
    cast: list = field(default_factory=list)       # list[CastEntry]


def clip_key(path: str, sample_fps: float, model: str = MODEL) -> dict:
    """Everything that changes a ClipResult. A mismatch on load → recompute."""
    st = os.stat(path)
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns,
            "sample_fps": float(sample_fps), "model": model, "version": CACHE_VERSION}


def _dir(out_dir: str, path: str) -> Path:
    # keyed on the file NAME (not stem): a.mp4 and a.mov must not collide
    return Path(out_dir) / ".intake_cache" / Path(path).name


def store(out_dir: str, path: str, sample_fps: float, result: ClipResult,
          model: str = MODEL) -> ClipResult:
    """Write the crop PNGs, then commit clip.json atomically (os.replace), and
    return the result in cached form (crop_rgb arrays replaced by their PNG paths)
    so a just-scanned clip and a loaded one present one shape to Phase 2 (§2/§3)."""
    d = _dir(out_dir, path)
    crops = d / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    cached = []
    for e in result.cast:
        png = crops / f"t{e.tid}.png"
        Image.fromarray(e.crop_rgb.astype("uint8")).save(png)
        cached.append(replace(e, crop=str(png), crop_rgb=None))
    payload = {"key": clip_key(path, sample_fps, model),
               "clip": result.clip.to_dict(),
               "phashes": list(result.phashes),
               "cast": [{"source": e.source, "tid": e.tid, "conf": e.conf,
                         "descriptor": e.descriptor, "crop": e.crop} for e in cached]}
    tmp = d / "clip.json.tmp"
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, d / "clip.json")               # atomic commit; presence == committed
    return ClipResult(clip=result.clip, phashes=list(result.phashes), cast=cached)


def load(out_dir: str, path: str, sample_fps: float,
         model: str = MODEL) -> ClipResult | None:
    """Return the cached-form ClipResult on a key match, else None. Absent, stale,
    truncated, or corrupt all read as a miss — never a crash."""
    f = _dir(out_dir, path) / "clip.json"
    try:
        payload = json.loads(f.read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if payload.get("key") != clip_key(path, sample_fps, model):
        return None
    clip = FootageClip.from_dict(payload["clip"])
    cast = [CastEntry(source=c["source"], tid=c["tid"], conf=c["conf"],
                      descriptor=c["descriptor"], crop=c["crop"]) for c in payload["cast"]]
    return ClipResult(clip=clip, phashes=payload["phashes"], cast=cast)
