# Plugin runtime resolution — fix the cache-copy break + lean the install

**Status:** design · 2026-07-22 (follow-up to
[plugin-packaging](2026-07-22-plugin-packaging-design.md), found by the first real
`/plugin install`)
**Scope:** make the installed plugin actually run the pipeline, and stop the
install from copying a 1.1 GB venv into the plugin cache.

## 0. The break (found by installing it)

`/plugin install` on the `source: "./"` marketplace does a literal `cp -R` of the
whole repo into `~/.claude/plugins/cache/video-grid/video-grid/0.1.0/` — including
`.venv`, `models/`, the weights, `.pytest_cache`, `.DS_Store`. Two consequences,
both confirmed by running it:

1. **A Python venv does not survive a copy** (its `bin/python` is a symlink and
   `pyvenv.cfg` carries absolute paths). The cache's `.venv/bin/python` is broken.
   A skill loaded from the cache derives ROOT from its own base dir = the cache,
   calls `<cache>/bin/vg`, and `bin/vg` fails loud: *"no venv … run setup.sh"*.
   So neither the CLI nor the desktop app can run the pipeline as installed.
2. **1.1 GB is copied** (the venv) on every install / version bump.

The packaging design's §2.2 — "a skill resolves ROOT from its own harness-given
base directory" — is **wrong**, because the install *copies* the skills to a cache
that has no working runtime. §4 flagged this as the deferred "decoupled" case and
assumed only the *remote* GitHub marketplace copied to a cache; the **local**
`directory` marketplace does too. The deferred recorded-root anchor is therefore
required now, not later.

## 1. The load-bearing correction — the skill resolves the *clone*, which only `setup.sh` knows

The runtime (venv, `config/ffmpeg.env`, weights, `models/`, the real `scripts/`)
lives in the clone and is produced by `setup.sh`. The cache copy is a frozen,
runtime-less snapshot. So a skill must run the **clone's** `bin/vg`, and the only
component that knows the clone's absolute path is `setup.sh` at install time.

`setup.sh` records that path; skills read it. This sidesteps *every*
cache-vs-clone divergence at once (broken venv, absent per-machine
`config/ffmpeg.env`, frozen vs live code, missing weights) — one indirection
instead of patching each.

## 2. Recorded-root (correctness)

- `setup.sh` writes the clone's absolute path to
  `${XDG_CONFIG_HOME:-$HOME/.config}/video-grid/root` (the twin of
  `config/ffmpeg.env`, but **outside** the tree because the skills may run from a
  different directory than the runtime).
- The 6 runner skills' `**Launcher.**` preamble changes from "derive ROOT from
  this skill's base dir" to: read the clone path from that file and use
  `"$ROOT/bin/vg"`. If the file is absent → the user has not run `setup.sh`; fail
  loud with that remedy.
- `bin/vg` is **unchanged** — it still self-resolves its own ROOT (now always the
  clone, because that is the `bin/vg` the skill invokes) and guards the venv.

## 3. External venv + a `.venv` symlink (lean)

- `setup.sh` builds the venv at `${XDG_DATA_HOME:-$HOME/.local/share}/video-grid/
  venv` and points `<clone>/.venv` at it with a symlink
  (`ln -sfn <external> <clone>/.venv`). An existing real `<clone>/.venv` is
  replaced by the symlink (migration).
- **Every `.venv/bin/python` reference stays valid** (dev workflow, `bin/vg`,
  tests, docs) — they follow the symlink. No ref churn, and `bin/vg` needs no edit.
- `cp -R` **preserves a symlink** (measured: the copied `.venv` is a 0-byte
  symlink to the external absolute path and still resolves), so the plugin cache
  copy carries a symlink, not 1.1 GB. Leanness holds as long as the installer
  copies with `cp -R` semantics — the first real install copied a *real* `.venv`
  only because it *was* a real dir; a symlink should copy as a symlink. This is
  the one claim that needs the user's actual `/plugin install` to confirm (§5).

## 4. What stays, what remains (honest)

- **`bin/vg` unchanged**; its two contract tests stay green.
- **Residual copy weight:** `models/` + weights (~12 MB) and transient
  `.pytest_cache`/`.superpowers`/`.DS_Store` still ride the `cp -R` (it ignores
  `.gitignore`). ~12 MB is tolerable; chasing it (relocating weights, an ignore
  mechanism) is out of scope. Only the 1.1 GB venv mattered.
- **README `.` → `./`.** The first install hit *"Invalid marketplace source
  format"* on `/plugin marketplace add .` — the accepted local form is `./` (or an
  absolute path). Fix the README command.
- **The cache copy of `scripts/`/`bin/vg` is now dead** (skills always exec the
  clone). That is the honest shape of a heavy-runtime tool wearing a plugin: the
  plugin distributes *discoverable skills*; the clone is the runtime.

## 5. Testing

**Automated:**
- Skill lint: the 6 runners read the recorded-root file and reference `bin/vg`;
  none derive ROOT from a base dir any more (the old wording is gone).
- `bin/vg` unchanged — `tests/test_launcher.py` still passes (cwd-independence +
  fail-loud). A `.venv` symlink is transparent to it.
- `setup.sh` behaviour is shell, not pytest — a focused check that after a run the
  recorded-root file holds the clone path and `<clone>/.venv` is a symlink into the
  external venv. Runnable without a network install by pointing setup.sh's venv
  builder at a tmp external dir; if that is impractical to isolate, it is a
  user-run proof (below), not skipped silently.

**User-run proof (needs their Claude Code + `/plugin install`, like the ffmpeg
baseline proof):** reinstall, then from a foreign directory a montage brief reaches
`out/REEL_v1.mp4`; and `du -sh` the cache install shows no venv. Documented in the
plan as a user proof, not asserted by the suite.

## 6. Out of scope

- Relocating weights/`models/` out of the tree (the remaining ~12 MB).
- A leaner plugin root (skills-only subdir as the marketplace `source`) — a bigger
  restructure; recorded-root + external venv already make the install correct and
  ~1.1 GB lighter.
- The GitHub-remote marketplace (still deferred; recorded-root now makes it
  mechanically possible, but the venv-per-checkout story is unchanged).
