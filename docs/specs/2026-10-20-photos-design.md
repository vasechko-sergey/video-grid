# Photos — ingest, fit to the canvas, a sub-pixel move

**Status:** built 2026-10-20 (0.26.0). Backlog U4 + U5 + U6, the photo epic's first slice.

## §0 · Why

Photos are a main material of memory and travel reels, and in 2025–2026 they move (the
2026-10-20 photo research). The engine did not see them: intake scanned only
`.mp4/.mov/.m4v/.avi`, so a folder of HEIC and JPEG was skipped without a word.

The slice gives a photo the same road a video window takes, from FOOTAGE.json to the
delivered reel, with three things a still needs and a video does not:

1. **decoding into honest pixels.** HEIC orientation, ICC profiles (Display P3), the SDR
   base of an HDR photo and a size cap. The P3 trap is silent: measured on a P3-tagged
   JPEG, sRGB (255, 0, 0) reads back as (234, 51, 35) when the profile is ignored;
2. **a frame for the canvas.** A portrait photo fills 9:16 and a landscape one fits
   with a background, aimed at the subject YOLO finds in the still;
3. **a move.** `zoompan` truncates its crop to whole source pixels every frame, so on
   a still (where nothing else moves to hide it) a slow push stair-steps. Measured by
   tracking a dot through the same 5 % push from a source 1.2× the output: it strays
   **0.46 px** RMS from a smooth curve through `zoompan`, with jumps to 1.6 px, and
   **0.02 px** through the float warp (0.28 against 0.03 at 2×). The repeated-frame
   count does not show it — zoompan's crop moves almost every frame, just unevenly.

## §1 · A photo enters intake

`runlayout.PHOTO_EXTS` = `.jpg .jpeg .png .heic .heif`; intake scans those beside the
video extensions, and `runlayout.is_photo(name)` is the one predicate everything else
asks. Files of other extensions are no longer dropped in silence: intake logs how many it
skipped, by extension. A photo and a video sharing a stem (an iPhone Live Photo's two
halves) both enter and intake says so; pairing them is U9.

`lib/still.load(path)` is the one decoder (intake, the contact sheet and extract all call
it), and returns an upright 8-bit sRGB array plus a record of what it changed:

- **Orientation.** JPEG/PNG: the EXIF tag, through `ImageOps.exif_transpose`. HEIF:
  libheif applies the `irot`/`imir` properties while decoding and `pi_heif` resets the
  EXIF tag to 1 (measured on a rotated HEIC), so the EXIF tag is never applied a second
  time. The HEIF spec makes the transformative properties authoritative.
- **Colour.** An embedded ICC profile is converted to sRGB through littlecms
  (`ImageCms`, relative colorimetric). No profile reads as sRGB, the web default.
- **HDR.** The decoders return the primary image, which is the SDR base of a gain-map
  photo (iPhone ISO 21496-1, Android Ultra HDR); a 10-bit HEIF is decoded to 8 bits.
- **Size.** The long side is capped at `MAX_LONG_SIDE = 4096` (Lanczos). A 9:16 crop of
  a capped 4:3 photo is still 2304×4096, 2.1× the width of a 1080 delivery.
- HEIC needs `pi_heif`; it ships with the runtime today (as a dependency) and is now
  declared in `requirements.txt`, beside `opencv-python`, which the renderer imports.

A photo becomes one `FootageClip(kind="photo")` with one window. `kind` is omitted from
JSON for video, so every existing FOOTAGE.json and cache entry is byte-identical.

- The window: `start 0`, `dur PHOTO_HOLD = 2.0` s (the research's 1–2 s per photo in a
  reel, 2–4 s in a post). `motion` and `shake` are 0; `people`, `subject_w/h` and
  `present` come from one YOLO pass on the still (the largest box, as for video).
- The clip: `dur PHOTO_ROOM = 8.0` s — how long the pacing fitter may hold it
  (`selection.json` had no field for a photo's length; U7 was that row, and the
  [2026-10-21 design](2026-10-21-photo-rhythm-design.md) added `hold`, in beats) —
  `fps 0.0` (a photo has no rate; video keeps `fps > 0`), no scene cuts.
- A photo surfaces no cast candidates in this slice.

## §2 · The frame (U5)

`edit_plan.window_to_episode` picks a photo episode's default layout from the photo's
aspect against the canvas: **fill** when the canvas-aspect crop keeps at least
`FILL_KEEP = 0.6` of the photo (3:4 keeps 75 % of a 9:16 frame, 4:5 70 %), otherwise
**fit** with the blurred background (1:1 keeps 56 %, 4:3 42 %, 16:9 32 %). An authored
layout wins; `insert` works too.

The subject is the union of the person boxes at least `SUBJECT_KEEP = 0.25` of the
largest one's area, so a couple is framed together and a stranger in the back is not.
No people: the frame's centre, the Final Cut default.

## §3 · The move (U6)

`EDLEpisode.still = {"from": a, "to": b}`: fractions of the base frame's width, both in
(0, 1], equal allowed (a still that does not move). Absent means the default push-in
`1.0 → 0.92`, 8.7 % over the hold — the 5–10 % the craft sources give. It is valid only
on a photo source, and a photo refuses `zoom`, `pan`, `ramp`, `stabilize`, `hero` and a
`start_offset`: the move is `still`, and there is no timeline or track to address.

`lib/kenburns.py` plans it, pure:

- **The base frame** is the largest rect of the layout's crop aspect inside the photo,
  times `crop_scale`, in float pixels. It is placed so the subject sits at the
  composition's x — centred for `center`, on the grid line nearer the subject's own
  position in the photo for `lead` (the photographer's composition is kept), the photo's
  centre for `break` — and vertically centred on it, clamped inside the photo.
- **What it aims at is the top half of the subject** (`HOLD_TOP = 0.5`): heads and
  faces, so a push toward a standing figure cuts the feet first. The review found the
  first rule — the whole box, plus a margin that gave up entirely whenever it crossed
  the photo's edge — cutting 65 px off the head of a person standing on the bottom edge.
- **The move is a homothety about P, the centre of that half.** Every frame is
  `P + (base − P)·s`, so P holds still on screen while the frame closes in around it,
  and every frame is a convex combination of the base frame and P, so it never leaves
  the photo.
- **Log-scale zoom with eased ends.** `s = a·(b/a)^q`, `q = 3p² − 2p³`: equal ratios of
  scale read as equal speed, and the move starts and stops without a jolt. Position and
  scale ride the same q, which the homothety gives for free.
- **The upper half stays whole.** Decided per side: a side the base frame already cuts
  sets no limit (nothing can give it back); on every other side the tightest frame keeps
  a gap of `SUBJECT_MARGIN = 0.05` of the held box's size or half the gap the base frame
  had, whichever is smaller — so a head 100 px under the top of the photo still lets the
  frame move, and one with no room left inside the picture does not. A side within
  `PHOTO_EDGE = 0.5 %` of the photo's own border is cut, not held: a detector box stops
  at the image edge, so the person goes on past it (the re-review found a selfie with
  the head at the top edge, and a person at the left edge, each freezing the move). A
  move that would break the rule is shortened — or, when no tighter frame works,
  cancelled — and the sidecar's note says which; a base frame or a photo edge that cuts
  the subject is noted as such.

`lib/still.render` draws it: the raster is pre-scaled once (`INTER_AREA`) so the
tightest frame lands at 1:1 — the pre-scale never throws away detail the tightest frame
could show — and a frame that would sample more than `MAX_DENSITY = 2` source pixels per
output pixel (an authored 1.0 → 0.3) is drawn from half-size levels instead, since a
cubic warp does no area filtering and would shimmer — blended between the two levels
around its density, because a hard switch read as one frame suddenly sharper than the
last (Laplacian variance up 6.4× between neighbours; 1.28× blended). Each output frame is one `cv2.warpAffine` with
a float matrix (`INTER_CUBIC`), and the frames stream as `rgb24` into one x264 encode
(`proc.feed`, the stdin twin of `proc.run`, with the same argv lint).

## §4 · The segment contract (U4)

`extract.extract_edl` renders a photo episode into the same `ep{i}_raw.mp4` a video
window is cut into, on the video segment's contract:

- **size**: what reframe would scale it to — the delivered canvas for `fill`, the content
  rect for `fit`/`insert` (`layout.resolve` over the photo's dims), so reframe's scale is
  the identity. Under the default `native` delivery a crop keeps its own pixels, and a
  photo's are thousands wide while the reel takes its size from its FIRST episode: the
  review measured a landscape photo first setting a 1600×2844 reel and the 1080p video
  beside it upscaled 2.6×. So under `native` a photo is sized to the canvas the first
  video episode delivers at, or, in a reel of photos alone, to a fill crop of the first
  photo. That canvas is written into the segment's record (`canvas_px`), and reframe lays
  a still out on it rather than re-deriving one from the segment's width: 606 ×
  even(606·16/9) is 606×1076, not the video's 606×1080, and the reel would have squashed
  every video to match;
- **rate and timebase**: the EDL's first video segment's exact `r_frame_rate` and track
  timescale (30/1 when there is no video), because `build_reel` takes the reel's rate from
  the first episode and `assemble` would otherwise conform;
- **pixels**: `yuv420p`, tv range, SAR 1:1, RGB→YUV through **BT.709**, and all four
  colour tags stamped on the frames by `setparams`. Two measurements on ffmpeg 8.1.2
  overturned the research's guess. The guessed trap — a `bt709` tag over swscale's
  BT.601 default — does not reproduce: ffmpeg negotiates the encoder's colourspace into
  `scale`. The real one is an **untagged** segment: ffmpeg decodes it as BT.601 and
  agrees with itself (1 code), while a player reading untagged HD as BT.709 moves the
  saturated patches **21 codes**. And `-color_primaries`/`-color_trc` given as output
  options never reach the file; only frame properties do. The proof decodes a patch
  chart back both ways, with the untagged pipe as its control;
- **length**: `round(dur·fps)` frames, inside extract's one-frame gate; no audio stream
  (mix already beds a silent segment with `anullsrc`).

`ep{i}_raw.still.json` beside it records the decode, the subject, both frames, the move
as planned and as applied, the pre-scale and the upscale over the original raster.
extract needs the project for the canvas and the delivery, so `edl_to_reel` and `draft`
pass it; a photo episode without one is refused.

## §5 · Downstream: a photo is route-less, like a pan

The camera lives in the segment's pixels, so the episode has nothing to track and the
crop must be the whole segment. `to_manifest_dict` sets `still: true` for a photo
source (by extension); it rides `Manifest` → `ReframeSpec` → `PathMeta.still` (written
only when true, so existing sidecars do not change):

- `reframe.plan_render` forces `crop_scale 1.0` (the move already consumed it). A fill
  still is resolved against its own shape, because the canvas a delivery evens is not
  the canvas aspect to the pixel (606×1080 under native, where a 9:16 crop would shave
  three rows), and refused past `STILL_ASPECT_TOL = 1 %`; a fit/insert still trims at
  most `STILL_TRIM = 2` px, centred. Either refusal means the segment was cut for
  another layout or canvas. A still refuses `pan` and `zoom` here too.
- `process_episode` skips tracking and the contradiction gate, refuses a supplied route
  or keyframes, and does not retry: a re-render of a fixed path is the same pixels.
- `check_episode` reports framing `editorial-only` and continuity `not-checked`, named
  "photo"; `check_reel`, `edl_to_reel`, `episode_qc` and the geometry stage treat it as a
  generated, route-less episode the way they treat a pan.

## §6 · Honest limits

- **Nothing checks the composition**, as for a pan: the subject's place is the planner's
  own decision, and a check reading the planner's box would grade it against itself. The
  safe-zone and key-action checks skip photo episodes by name.
- The subject is a person detector's union box. A photo of a dog, a dish or a landmark has
  no subject and gets a centred push; a crowd's union can be most of the frame.
- `PHOTO_HOLD`, `PHOTO_ROOM`, `FILL_KEEP`, `SUBJECT_KEEP`, `SUBJECT_MARGIN`,
  `HOLD_TOP`, `PHOTO_EDGE` and the default move are conventions from the research, not
  measured on a real photo run.
- Photo scoring: `motion` 0 ranks a photo lowest on motion and `shake` 0 highest on
  stability, so a photo lands mid-pool; choosing photos among video is U8, holding them on
  the music grid U7, Live Photos U9.
  *Closed by the [2026-10-21 design](2026-10-21-photo-rhythm-design.md) (0.28.0), U9
  excepted: photos rank among photos (§5) and the music grid authors their length (§2).*
- No cast from photos, no hero pin on a photo, no pan across a photo's long side.
- The YOLO pass runs twice on the same decoded still (intake, then extract), which is
  deterministic but not free (one model load per photo in each, a fraction of a second).
- A HEIC whose colour is described only by an `nclx` box with P3 primaries, and no ICC
  profile, reads as sRGB. Apple writes an ICC profile.
- The backlog row said the same renderer would remove the integer residual of the
  video zoom. It could, but this slice does not wire it into reframe: the video zoom
  still runs through `zoompan`, where the moving footage hides the steps.
- The fit layout's blurred field is reframe's own, made from the moving segment, so it
  zooms with the photo rather than holding still behind it.
- `HOLD_TOP` assumes upright people, which is what a person detector boxes; a lying or
  upside-down figure is held by the wrong half.
- A photo segment is always tagged BT.709, whatever the video beside it carries; after
  reframe's re-encode the measured difference is about 4 codes.
