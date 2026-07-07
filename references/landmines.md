# Landmine registry

From the source montage session. Each entry: cause → symptom → fix. Copied
verbatim from design spec §12 — this is the canonical list; don't add new
entries without updating the spec first.

- `lutrgb` → black frames. Use `colorchannelmixer`.
- Black frames on cut — the **landmine is in the seek-argument order, NOT in
  4K**. Fix: correct seek-arg order (`-ss` after `-i` / output seek,
  `-accurate_seek`, re-encode the window for frame accuracy), **not** a
  downscale to 1080. Cut and process 4K natively.
- OpenCV HSV auto-tracker catches foam/other surfers → YOLO person +
  ByteTrack.
- Stabilizing the wade-in → "rolling ground". Don't stabilize.
- ImageMagick `montage` reorders tiles → false "sawtooth" motion readings.
  Verify order.
- Loading all frames into memory → OOM. Process frame by frame.
- `vidstabdetect` warning "cannot read frame local motions… got 255" —
  cosmetic, stabilization still works.
- pip behind a corporate mirror (`nexus.*`) times out off-VPN → `setup.sh`
  pins `PIP_INDEX_URL=https://pypi.org/simple` (env-overridable).
- `drawtext` without an explicit `fontfile=` fails or picks garbage on
  macOS → always pass a font path.
- concat of non-uniform segments (size/fps/codec) breaks or desyncs →
  normalize before concat (§5.9).
- pytest without `pythonpath = .` in `pytest.ini` can't import `scripts.*`
  (no `tests/__init__.py`) → keep it set.
- ultralytics downloads weights by model **name** (`yolo11n-seg.pt`), not
  into an arbitrary path → pass names; cache lives in `models/`.
- madmom 0.16.1 from PyPI is broken on python ≥3.10 / numpy ≥1.24 → git
  master only, and only as an optional extra.
- essentia has no macOS arm64 wheels → out of v1 (§5.5).
