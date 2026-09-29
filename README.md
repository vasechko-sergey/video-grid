# video-grid

Turn a folder of raw footage plus a one-line brief into a finished reel, for any
platform. An AI-assisted montage **skill set** for Claude Code — you describe the
video in plain language; the skills conduct the pipeline (project setup →
footage intake → edit plan → per-episode reframing → assembly → checks →
delivery), stopping only at three review checkpoints.

> **Two halves, both required.** The **plugin** distributes the skills; a one-time
> **`bash setup.sh`** provisions the runtime it drives (a Python venv, a
> full-featured `ffmpeg`, YOLO weights). A plugin install alone cannot make a reel.
> macOS + Homebrew for now.

## Use

**1. Get the runtime.**

```bash
git clone git@github.com:vasechko-sergey/video-grid.git
cd video-grid
bash setup.sh          # venv + ffmpeg-full (drawtext + vidstab) + fonts; weights on first run
```

`bash setup.sh` installs the **whole** runtime — including demucs (vocal separation
for the phrase-aware music in/out-point) and yt-dlp (fetch tracks from the internet).
No opt-in flags. Where a platform genuinely cannot provide a piece, setup warns and
continues — **except that demucs is required**: setup still finishes, but
`verify_runtime` blocks every run until demucs is present. It is the only sensor that
can tell where the singing stops, and the mix-loudness proxy that used to stand in for
it was deleted for answering wrongly instead of failing.

Verify the install any time with `/video-grid:verify-runtime` (or
`"$VG" scripts.verify_runtime`) — it reports each missing piece with the exact
command to fix it.

**2. Install the plugin** (from inside the clone):

```
/plugin marketplace add ./
/plugin install video-grid@video-grid
```

Restart Claude Code so it picks up the skills. The plugin distributes the skills;
they run this checkout's `bin/vg` (its path is recorded by `setup.sh`), so keep the
clone in place after installing.

**3. Make a reel.** From *any* project directory, describe what you want:

> "make a 9:16 reel from ~/Movies/trip — upbeat, no titles"

The `using-montage` skill takes over: it sets the project aspect, scans the
footage, plans the edit, renders and checks the reel, and stops at the three
checkpoints (SPEC → EDL → final review) for your approval. Point it at any
footage folder by absolute path; every artifact lands in one `montage/` folder
beside the clips, organised by lifetime: `footage/` survives every re-cut,
`reels/<name>/` holds one cut, and the finished reel sits in
`reels/<name>/deliveries/`, which nothing ever deletes.

Individual stages have their own skills if you want to re-run just one
(`project-init`, `footage-intake`, `edit-plan`, `process-episode`, `music-match`,
`music-source`, `pacing`, `reel-brief`, `titles`, `reel-review`).

## Develop

Working on the code? Start at the **[CLAUDE.md](CLAUDE.md)** registry — it maps to
the [design spec](docs/specs/2026-07-05-montage-skillset-design.md), the
[coding standards](docs/coding-standards.md), the
[testing guide](docs/testing-guide.md), the
[development workflow](docs/development-workflow.md), the
[build status](docs/build-status.md), and the
[pipeline map](docs/pipeline-map.md).

Layout: engine code and CLIs in `scripts/` (run as modules: `bin/vg scripts.X …`,
or `.venv/bin/python -m scripts.X` from the repo root); the interactive/editorial
judgment in `skills/*/SKILL.md`; typed wire-contracts and config-specs in
`scripts/lib/`. New work is design → plan → subagent-driven TDD; every change
keeps the design spec and `docs/build-status.md` in sync.

```bash
.venv/bin/python -m pytest -q            # the whole suite
.venv/bin/python -m pytest -q -m integration   # the real-ffmpeg / real-weights proofs
```

## Licence

AGPL-3.0 — see [LICENSE](LICENSE).

Not a preference. `ultralytics` (the YOLO11 runtime footage-intake depends on)
is AGPL-3.0, and `scripts/intake.py` imports it on the main path, so a
permissive licence over this tree would be internally inconsistent. The model
weights themselves are *not* redistributed here — `.gitignore` excludes
`yolo11*.pt` and `setup.sh` downloads them at install time, which narrows the
question to linking rather than redistribution.

This declares a licence; it is not a licence audit. The transitive dependency
tree has not been walked.
