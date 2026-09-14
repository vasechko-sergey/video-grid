# episodes-geometry — router stage 9

**episodes-geometry (required, design 2026-08-30 §2 — the geometry seam).**
`edl_to_reel --stop-after-geometry` runs everything process-episode does
short of the actual encode — extract, stabilize, track, gate — for every
episode, then stops:

```bash
"$VG" scripts.edl_to_reel <run>/reels/<reel>/EDL.json --project <run>/project.json \
  --footage-root <footage_root> --work-dir <run>/reels/<reel>/build \
  --out-dir <run>/reels/<reel>/episodes --stop-after-geometry
```

Writes `<run>/reels/<reel>/episodes/GEOMETRY.json` — every episode's frozen
route and the crop it will actually ship, colour block stripped. No
`ep{i}.mp4` exists yet; no `--music`/`--titles` here either (both are
refused — they belong to the render and the delivery, not this seam). This
is the seam **match-grade** (next) measures the shipped crop in, instead of
the whole source frame it read before 2026-08-30. A `stop_and_report` here
(a tracker contradiction, a hero pin matching nobody) is the same
mechanical gate that used to surface only after a full render — now caught
one phase earlier, before a single pixel is encoded.
