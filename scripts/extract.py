"""Cut an EDL window into a standalone fragment (spec §5.8, §12) — or, for a photo,
render its move into one (design docs/specs/2026-10-20-photos-design.md §4)."""
import argparse
import json
from pathlib import Path

from scripts import track
from scripts.lib import assembly, ffbin, kenburns, proc, ramp, runlayout, still
from scripts.lib import layout as layout_lib
from scripts.lib.assembly import probe_duration as _probe_dur   # keep the local name its callers use
from scripts.lib.edl import EDL, EDLEpisode, to_manifest_dict
from scripts.lib.manifest import Manifest
from scripts.lib.models import Delivery, LayoutSpec, RampSpec, StillSpec
from scripts.lib.project import ProjectConfig, resolve_manifest

PHOTO_RATE = ("30/1", 15360)   # a reel of photos alone: 30 fps, ffmpeg's own mp4 timescale
                               # for it. With any video in the EDL its first segment's clock
                               # is used instead (design 2026-10-20 §4).

_LEN_EPS = 0.05    # seconds of slack beyond one frame — a re-encoded window lands ±1 frame


def extract(src: str, start: float, dur: float, out: str, crf: int = 18) -> str:
    # output-seek (-ss after -i) + re-encode → frame-accurate, no black frames.
    # Audio is PRESERVED (spec §5.8): segments are the ambient bed for audio-mix;
    # sources without an audio stream simply produce video-only segments.
    cmd = [
        ffbin.ffmpeg(), "-y", "-i", src,
        "-ss", f"{start}", "-t", f"{dur}",
        # The segment is the pipeline's canonical form and its range is part of
        # that contract (design 2026-08-27 §2). `-pix_fmt yuv420p` alone READS as
        # a normalization and is not one: measured, libx264 keeps full range for
        # a full-range input, so a Canon window — 67 of the 99 clips this was
        # designed against — shipped `yuvj420p`/pc the whole way into reframe's
        # lutyuv, whose TV_LO/TV_SPAN are written for 16..235.
        # in_range=auto reads the source's own tag (and ffmpeg's yuvj=>full
        # default when it has none), so this CONVERTS the samples; -color_range
        # writes the matching tag. It is the same pair assembly._normalize already
        # uses at concat — moved to where it can still save the grade instead of
        # arriving after it. Measured 2026-08-27 over all seven combinations:
        # `-pix_fmt yuv420p` is individually NECESSARY and not sufficient (alone it
        # converts nothing, and without it neither the filter nor the tag nor both
        # convert anything either); the filter/tag pair is sufficient GIVEN it, and
        # either half of the pair is byte-identical to both. Both halves are kept
        # because it costs nothing — but the redundancy inside the pair means no
        # check over rendered pixels can notice one of them going missing or going
        # wrong, so the argv test in tests/lib/test_extract.py is the sole guard
        # there.
        # The scale carries NO dimensions: resolution stays native because
        # reframe crops from native pixels (design §3). Measured byte-identical
        # on untagged, tv-tagged and 10-bit sources, so no golden moves.
        "-vf", "scale=in_range=auto:out_range=tv", "-color_range", "tv",
        "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out,
    ]
    proc.run(cmd)
    return out


def _layout_of(m: Manifest) -> LayoutSpec:
    return LayoutSpec(mode=m.layout, crop_aspect=m.crop_aspect, crop_scale=m.crop_scale,
                      rect=m.rect, background=m.background,
                      background_color=m.background_color, border_px=m.border_px,
                      border_color=m.border_color)


def _manifest(ep: EDLEpisode, segment: str, project: ProjectConfig) -> Manifest:
    return Manifest.from_dict(resolve_manifest(to_manifest_dict(ep, segment, segment), project))


def _photo_delivery(edl: EDL, photos: list[int], segments: dict[int, str],
                    footage_root: str, project: ProjectConfig) -> Delivery | None:
    """The delivery a photo segment is sized against, when the project's own does not
    fix a size (the 2026-10-20 review's I3). `native` keeps a crop's own pixels, and a
    photo's own pixels are thousands wide — while the reel takes its size from its
    FIRST episode, so a photo there would set a 4032-wide canvas and every video
    episode would be upscaled to it. Under native a photo is therefore sized to the
    canvas the first video episode delivers at, or, in a reel of photos alone, to the
    canvas a fill crop of the first photo gives. None: the project's delivery already
    fixes the size, and every photo resolves to the same canvas through it."""
    if Delivery.from_spec(project.delivery).mode != "native":
        return None
    native = Delivery.from_spec("native")
    if segments:
        j = min(segments)
        m = _manifest(edl.episodes[j], segments[j], project)
        info = assembly.probe_stream(segments[j])
        rl = layout_lib.resolve(_layout_of(m), m.canvas, (info.w, info.h), native)
    else:
        first = edl.episodes[photos[0]]
        m = _manifest(first, "", project)
        rl = layout_lib.resolve(LayoutSpec(mode="fill"), m.canvas,
                                still.load(str(Path(footage_root) / first.source)).dims,
                                native)
    return Delivery.from_spec(f"exact:{rl.out_w}x{rl.out_h}")


def render_photo(ep: EDLEpisode, src: str, out: str, project: ProjectConfig,
                 rate: tuple[str, int], delivery: Delivery | None = None) -> dict:
    """One photo episode into `out` (design 2026-10-20 §2-§4), and the record of it.

    The layout comes through the SAME bridge every episode's manifest does
    (to_manifest_dict + resolve_manifest), so the frame cut here is the frame reframe
    will find: the segment is sized to what reframe would scale it to — the delivered
    canvas for fill, the content rect for fit/insert — and shaped to the layout's crop
    aspect, so reframe's crop is the whole segment. `delivery` overrides the project's
    for the sizing only (_photo_delivery)."""
    m = _manifest(ep, out, project)
    st = still.load(src)
    rl = layout_lib.resolve(_layout_of(m), m.canvas, st.dims,
                            delivery or Delivery.from_spec(m.delivery))
    out_dims = (rl.out_w, rl.out_h) if rl.mode == "fill" else rl.rect_px[2:]
    boxes = still.people(st.rgb, track.MODEL)
    subject = still.subject(boxes)
    move = StillSpec.from_dict(ep.still) if ep.still is not None else kenburns.DEFAULT_MOVE
    num, den = (float(v) for v in rate[0].split("/"))
    pl = kenburns.plan(st.dims, rl.crop_aspect, m.crop_scale, subject, m.composition,
                       m.grid, move, max(1, round(ep.dur * num / den)))
    facts = still.render(st, pl.frames, tuple(out_dims), rate[0], out, timescale=rate[1])
    return {"source": ep.source, "decode": st.record, "people": len(boxes),
            "canvas_px": [rl.out_w, rl.out_h],
            "subject": None if subject is None else subject.to_list(),
            "layout": rl.mode, "aspect": list(rl.crop_aspect), "out_dims": list(out_dims),
            "rate": rate[0], "frames": len(pl.frames), "base": pl.base.to_list(),
            "anchor": [round(v, 3) for v in pl.anchor],
            "first": pl.frames[0].to_list(), "last": pl.frames[-1].to_list(),
            "move": {"planned": pl.planned.to_dict(), "applied": pl.applied.to_dict(),
                     "note": pl.note},
            **facts}


def extract_edl(edl: EDL, footage_root: str, seg_dir: str,
                project: ProjectConfig | None = None) -> list[str]:
    """Cut every EDL window into seg_dir/ep{i}_raw.mp4 (reel order). Gate (§5.8):
    each segment's probed duration matches its window within one frame, else raise
    — a short segment is the silent-truncation class (design §12).

    A photo episode is RENDERED into the same name (render_photo), with its record
    beside it as ep{i}_raw.still.json. It needs `project` for the canvas and the
    delivery, and takes the clock of the EDL's first video segment, so the videos are
    cut first."""
    Path(seg_dir).mkdir(parents=True, exist_ok=True)
    photos = [i for i, ep in enumerate(edl.episodes) if runlayout.is_photo(ep.source)]
    if photos and project is None:
        raise ValueError(f"EDL episode {photos[0]} is a photo ({edl.episodes[photos[0]].source}) "
                         f"and a photo's segment is sized for the canvas and the delivery — "
                         f"pass the project to extract_edl")
    for i in photos:
        if not (Path(footage_root) / edl.episodes[i].source).exists():
            raise ValueError(f"EDL episode {i} source not found: "
                             f"{str(Path(footage_root) / edl.episodes[i].source)!r} "
                             f"(footage_root={footage_root!r} + "
                             f"source={edl.episodes[i].source!r})")
    segments: dict[int, str] = {}
    for i, ep in enumerate(edl.episodes):
        if i in photos:
            continue
        src = str(Path(footage_root) / ep.source)
        if not Path(src).exists():
            raise ValueError(f"EDL episode {i} source not found: {src!r} "
                             f"(footage_root={footage_root!r} + source={ep.source!r})")
        out = str(Path(seg_dir) / f"ep{i}_raw.mp4")
        extract(src, ep.start, ep.dur, out)
        probed, fps = _probe_dur(out), assembly.probe_stream(out).fps
        if probed + 1.0 / fps + _LEN_EPS < ep.dur:
            raise ValueError(
                f"EDL episode {i} segment is {probed:.3f}s — shorter than its {ep.dur}s window "
                f"(source {src!r} start={ep.start}); the window runs past the clip. Trim the window "
                "or fix the in-point.")
        if ep.ramp is not None:
            # A PRE-STAGE writing a file, exactly like vidstab.stabilize and for
            # the same reason (design §4): the route must be measured on the
            # pixels that ship. A route tracked on un-retimed time and applied to
            # retimed pixels would place the crop at the wrong moment, and
            # check_episode would confirm the framing — path and route would
            # agree with each other while only the pixels disagreed.
            #
            # It replaces ep{i}_raw.mp4 IN PLACE because draft.py and the reel
            # manifest built by preflight both reference that exact name; a ramp
            # written beside it would simply be ignored, leaving reframe the
            # un-ramped cut.
            ramped = str(Path(seg_dir) / f"ep{i}_ramped.mp4")
            ramp.retime(out, ramped, RampSpec.from_dict(ep.ramp), ep.dur, fps)
            Path(ramped).replace(out)
        segments[i] = out
    if photos:
        rate = assembly.probe_rate(segments[min(segments)]) if segments else PHOTO_RATE
        delivery = _photo_delivery(edl, photos, segments, footage_root, project)
        track.ensure_model(track.MODEL)     # the subject pass needs the weights on disk
        for i in photos:
            ep = edl.episodes[i]
            out = str(Path(seg_dir) / f"ep{i}_raw.mp4")
            record = render_photo(ep, str(Path(footage_root) / ep.source), out, project, rate,
                                  delivery)
            Path(out).with_suffix(runlayout.STILL_SIDECAR).write_text(json.dumps(record, indent=2))
            probed = _probe_dur(out)
            num, den = (float(v) for v in rate[0].split("/"))
            if probed + den / num + _LEN_EPS < ep.dur:
                raise ValueError(f"EDL episode {i}: the photo segment rendered {probed:.3f}s "
                                 f"against its {ep.dur}s hold — the encode lost frames")
            segments[i] = out
    return [segments[i] for i in range(len(edl.episodes))]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="cut one EDL window out of a source clip into a standalone "
                    "segment, normalized to tv range — the pipeline's canonical "
                    "form. edl_to_reel runs it per episode before any tracking.")
    ap.add_argument("src", help="source clip the EDL window refers to")
    ap.add_argument("out", help="segment .mp4 output path")
    ap.add_argument("--start", type=float, required=True,
                    help="window start in the source, seconds")
    ap.add_argument("--dur", type=float, required=True, help="window length, seconds")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    extract(a.src, a.start, a.dur, a.out)


if __name__ == "__main__":
    main()
