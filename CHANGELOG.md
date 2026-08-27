# Changelog

Releases of the **plugin** — the skills you install and the runtime they drive.
The top entry must match `.claude-plugin/plugin.json`; a test enforces that,
because the install path is version-keyed and an unbumped version lets a
reinstall keep serving the old snapshot.

Versioning rules are in
[docs/development-workflow.md](docs/development-workflow.md#versioning).
Per-subsystem detail lives in [docs/build-status.md](docs/build-status.md); this
file is the short "what changed for someone who installs it" list.

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
