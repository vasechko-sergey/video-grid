# Changelog

Releases of the **plugin** — the skills you install and the runtime they drive.
The top entry must match `.claude-plugin/plugin.json`; a test enforces that,
because the install path is version-keyed and an unbumped version lets a
reinstall keep serving the old snapshot.

Versioning rules are in
[docs/development-workflow.md](docs/development-workflow.md#versioning).
Per-subsystem detail lives in [docs/build-status.md](docs/build-status.md); this
file is the short "what changed for someone who installs it" list.

## 0.4.0 — 2026-08-28

- **A damaged colour grade now stops an episode instead of shipping it
  unnoticed.** `color_fidelity` replaces its old hue-angle metric — blind to
  exposure and saturation, the two things a grade actually moves, and prone to
  discarding a sample outright near grey — with the median CIEDE2000 colour
  difference over five source-vs-delivered samples of the tracked subject. It
  now **fails the episode** above `CheckSpec.grade_delta_max = 5.0` (the field
  replaces `hue_drift_max`), and a colour failure escalates immediately to
  `edit-plan` as `grade-damage` instead of burning three full-resolution
  re-renders on reframe knobs that cannot move a colour. Measured on one
  reference shoot: every episode that graded cleanly stayed under the bar
  (4.29 at most), with simulated damage starting at 5.04 — a gap of 0.75 dE00,
  17% of that healthy maximum.
- **The per-episode QC judge now sees what the grade changed, not what the
  footage already was.** The colour-naturalness sensor drops three flags that
  were measuring the scene rather than the grade — one fired on most source
  clips before any grade touched them, two never reached their own bars on
  real footage. In their place: two flags for information a grade can destroy
  (`blown_highlights`, `crushed_blacks`), plus a new source-relative reading
  (`cast_shift` / `saturation_shift` / `contrast_drop`) measured against the
  pre-grade footage, which the QC evidence packet now carries alongside the
  delivered clip's own numbers.
- Both checks answer whether the colour moved and by how much — neither says
  the result looks good. That judgment still belongs to the QC judge and the CP3
  reviewer.

## 0.3.1 — 2026-08-28

- **Two thirds of the footage was being graded in the wrong colour range, silently.**
  `extract` re-encoded with `-pix_fmt yuv420p`, which reads as a normalization and
  is not one — libx264 keeps full range for a full-range input. Of the 99 clips in
  the reference shoot **67 are full-range**, so most of the footage reached the tone
  transfer, whose constants describe a *limited* 8-bit plane, in a range those
  constants are not written for. Measured against one common target, the transfer
  missed by **8.5 luma codes** on a full-range source and **1.5** on a limited one,
  against a threshold of 4.0 that decides whether to correct at all. Segments are
  now normalized at the cut, and the two land on the same numbers. Byte-identical
  on everything already correct, so nothing that looked right has moved.
- **The tone map no longer flattens the highlights.** Above its top anchor the curve
  fell through to a constant, so twenty stored codes arrived as one — a plate
  exactly where the shoulder exists to prevent one. It now continues the shoulder's
  own slope.
- **Raw camera footage is refused where it cannot be graded.** A 10-bit source
  through the same transfer came back with **99.26 %** of its pixels on a single
  code — destroyed, not shifted — and nothing said so. `reframe` now refuses a
  source whose bit depth or colour range its colour maths cannot read, naming the
  remedy. It caught this repo's own test fixture on its first day.

## 0.3.0 — 2026-08-27

- **The run directory gets an interior, organised by lifetime.** `montage/footage/`
  survives every re-cut, `montage/reels/<name>/` holds one editorial variant, and
  inside it `episodes/` is one render generation, `deliveries/` is append-only and
  `build/` is wiped at the start of every render. Measured on the 2026-06 run:
  **52.8 %** of 1119 MB was scratch nothing had ever deleted — 17 `work/ep*`
  directories for an 8-episode reel — while the **16.0 %** that cannot be rebuilt
  lived in the one directory the workflow `rm -rf`'d **47 times**.
- **Version numbering survives.** `deliver` reads `VERSIONS.md` instead of counting
  surviving files, so an archived or deleted reel no longer renumbers the next one —
  three different reels had shipped as `REEL_v1.mp4`. Its scratch (the vignette mask,
  the title sidecars) now takes an explicit `--scratch-dir` and never lands beside
  the deliveries.
- **A second cut is a directory, not a filename suffix.** `--reel <name>` forks the
  120 KB editorial layer and shares the 194 MB footage layer, retiring `MUSIC_A/B/alt`
  and `pacing_A/B`.
- **`montage status` takes `--reel` in place of `--out-dir`** and returns each stage's
  resolved path, the whole layout, the reels that exist, and whether the run predates
  this layout. That resolution is also the enforcement: an artifact written outside
  the layout is not seen, so the router runs its stage again into the canonical path.

## 0.2.2 — 2026-08-25

- **Retro of the first real run** — six days, 99 clips, one delivered reel — written
  to `docs/retro/2026-08-25-first-real-run.md` before the session transcripts are
  deleted, and **42 backlog rows** filed from it (18 at P1). No behaviour change;
  this release is the record.
- The headline is that capability was not the problem. `scripts.probe grade` ran
  **0** times and `CONSTRAINTS` was mentioned **0** times in 831 tool calls, though
  the installed plugin shipped both two hours before the run started — while the
  agent rebuilt the colour probe by hand as a 2.0 GB private lab.
- Four of the first pass's six findings were refuted on re-reading, and the wrong
  versions are recorded beside the right ones.

## 0.2.1 — 2026-08-25

- **Run artifacts move to `<footage_root>/montage/`.** The footage folder gets one
  entry instead of the 38 a real run left in it. `intake`, `draft` and
  `edl_to_reel` now refuse an output directory that resolves to the footage root.
  Not tidiness: intake discovers clips by extension over a flat listing with no
  exclusion, so a rendered `.mp4` written beside the source — `draft.mp4` did
  exactly this — is taken as footage by the next scan.
- **A run from before this convention no longer resumes on its own.** It lives
  directly in the footage folder; the router now asks instead of silently starting
  fresh and re-scanning every clip. Moving such a run is not a `mv` — its artifacts
  carry absolute paths to each other.

## 0.2.0 — 2026-08-19

- **Cast identity works for the first time.** `lib/reid` reached
  `FeatureExtractor` through an import path torchreid 0.2.5's layout does not
  have, so every real embedding died one line below the availability gate. The
  boundary had never executed anywhere — its proof was the suite's one skip.
- **`setup.sh` installs `tensorboard`.** torchreid declares no runtime
  requirements at all and reaches it through `torch.utils.tensorboard`, so
  `pip install torchreid` succeeded and `import torchreid` raised.
- **Version bumped so a reinstall actually replaces the plugin.** The install path
  is version-keyed; at an unchanged `0.1.0` the cache had served a 316-commit-old
  snapshot, which is why the required `episode-qc` stage was missing from the
  installed skill set.

## 0.1.0 — 2026-07-22

- First packaged plugin: `skills/` distributed through a self dev-marketplace,
  with `bin/vg` as the launch chokepoint and `setup.sh` provisioning the runtime
  it drives.
