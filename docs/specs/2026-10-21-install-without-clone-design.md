# Install without a clone — the plugin is the runtime's code

**Status:** built 2026-10-21 (0.27.0). Asked by the user 2026-10-20.

## §0 · Why

The README asked for three steps: `git clone`, `bash setup.sh` in the clone, then
`/plugin marketplace add ./` from inside it. The clone was there for one reason —
the runtime-resolution fix of 2026-07-22 made `setup.sh` record the clone's path
(`~/.config/video-grid/root`) and every skill run `<clone>/bin/vg` — and that reason
no longer holds:

- `/plugin install` already copies the whole repository, `scripts/`, `setup.sh` and
  `bin/vg` included, into `~/.claude/plugins/cache/video-grid/video-grid/<version>/`.
  The code a run needs is on disk without a clone.
- What made the copy unusable in July was state inside the tree: the venv (moved out
  then, behind a `.venv` symlink), `config/ffmpeg.env`, `config/sourcing.env`, and
  the YOLO weights ultralytics downloads into `bin/vg`'s working directory.
- Claude Code fills `${CLAUDE_PLUGIN_ROOT}` into a plugin skill's text when it loads
  it. Observed on this machine: a plugin skill whose file says `${CLAUDE_PLUGIN_ROOT}`
  arrives in the conversation carrying the absolute cache path of its own version.

So the code and the instructions can come from one directory, the installed plugin,
and the clone becomes a developer's tool.

## §1 · State lives outside the plugin

| What | Was | Now |
|---|---|---|
| venv | `${XDG_DATA_HOME:-~/.local/share}/video-grid/venv` behind `<clone>/.venv` | the same path, read by `bin/vg` directly |
| ffmpeg path | `<clone>/config/ffmpeg.env` | `${XDG_CONFIG_HOME:-~/.config}/video-grid/ffmpeg.env` |
| Jamendo key | `<clone>/config/sourcing.env` | `…/video-grid/sourcing.env` (setup moves an old one over) |
| YOLO weights | `<clone>/yolo11n-seg.pt` | `${XDG_DATA_HOME}/video-grid/models/` |
| runtime root | `~/.config/video-grid/root` | not written; nothing reads it |

`lib/userdirs.py` is the one place that names these directories. `ffbin` and
`catalog` read the new files first and the old in-tree file second, so a clone set
up before this slice keeps working until `setup.sh` runs again.

`bin/vg` resolves the venv from the data directory, `cd`s into the models directory
and puts its own root on `PYTHONPATH`. The `cd` stays mandatory for the reason it
always was (packaging design §1.1: ultralytics downloads a bare model name into the
working directory); it now lands the weights where every installed version shares
them instead of in one version's copy. Every repo-relative read in `scripts/` is
already `__file__`-relative, so nothing else depends on the working directory.

## §2 · Skills read their own root

The resolution preamble in all skills becomes `ROOT="${CLAUDE_PLUGIN_ROOT}"`. When a
harness does not fill the variable in, the line evaluates to empty and the preamble
says what to use instead: the directory two levels above the skill's base directory,
which the harness always shows. Nothing reads the recorded root any more.

The instructions and the code are now one version by construction. The plugin
staleness check (design 2026-09-25) stays: run from an installed plugin it compares
the install record with itself and passes; run from a clone it still says when the
installed plugin is older than the checkout.

## §3 · Installing and updating

A new `setup` skill runs the plugin's own `setup.sh`, after saying what it installs
and asking. `setup.sh` runs from any directory it is copied to: the plugin cache, or
a clone.

`setup.sh` stamps the venv with `userdirs.requirements_digest`: `requirements.txt`
plus `setup.sh`'s own `pip" install` lines, since demucs and torchreid with its named
extras are installed outside the file (a failed torch wheel must not abort the venv).
`verify_runtime` gains a required `deps_stamp` check calling the same function, so an
update that changes the dependencies says "run setup again" instead of failing on the
first import that moved.

Coming from a clone install, the old `~/.config/video-grid/root` is read ONCE, by
setup, to carry the Jamendo key and the YOLO weights over from that clone: a plugin
installed from GitHub carries no `config/` of its own. Nothing else reads it. The
README names the two marketplace paths, because Claude Code keeps one marketplace per
name and the old install registered the clone itself as `video-grid`.

## §4 · The engine stamp without git

`provenance.engine_stamp` answered from `git` in the code's root, and the plugin
cache is not a git checkout, so every run from an installed plugin would have
recorded an unknown engine — and an unknown stamp never stops a run, so the guard
against a run straddling an engine change (design 2026-08-04 §3) would have gone
quiet for every user who installs the plugin. Without git it now digests the files of
`ENGINE_PATHS` (`tree:<12 hex>`); a git checkout still reports its commit — but only
when the work tree's top IS the code's root. git walks up, and the review found a
plugin cache inside a dotfiles repo stamped with that repo's HEAD, which a plugin
update never moves.

## §5 · Honest limits

- Substitution of `${CLAUDE_PLUGIN_ROOT}` into skill text is documented for plugin
  skills and observed here; the fallback covers a harness that does not do it.
- `setup.sh` is still macOS/Homebrew and installs system packages; the skill asks
  first, and verify-runtime still never installs.
- Claude Code marks a replaced version directory orphaned and deletes it 14 days
  later. A run is not that long, but a `judge_prompt.md` packed by the old version
  names that version's `bin/vg`.
- The venv, weights and config are shared by every version and by a clone: a
  developer whose branch changes the dependencies and runs setup from the clone makes
  the installed plugin's `deps_stamp` fail until setup runs from it again — accurate,
  since the venv no longer matches it.
- A run started through a clone (a git sha) and finished through the installed
  plugin (a tree digest) is refused as drift even at the same commit. It fails safe.
- A developer who wants runs to use their clone's code installs the plugin from the
  clone (`/plugin marketplace add ./`) and updates it after each change, as before.
