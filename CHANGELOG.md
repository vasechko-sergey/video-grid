# Changelog

Releases of the **plugin** — the skills you install and the runtime they drive.
The top entry must match `.claude-plugin/plugin.json`; a test enforces that,
because the install path is version-keyed and an unbumped version lets a
reinstall keep serving the old snapshot.

Versioning rules are in
[docs/development-workflow.md](docs/development-workflow.md#versioning).
Per-subsystem detail lives in [docs/build-status.md](docs/build-status.md); this
file is the short "what changed for someone who installs it" list.

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
