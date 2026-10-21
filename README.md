# video-grid

**A folder of raw footage and a few sentences in, a finished vertical reel out.**

video-grid is a skill set for [Claude Code](https://claude.com/claude-code). You
describe the video you want in plain language. Claude then works through the edit:
it watches the footage, finds the moments, cuts them to the music, reframes each
shot for the platform, grades it, adds titles and checks its own work. It asks
you questions along the way (who is who, what the reel is for) and waits for
your approval at three checkpoints. The agent decides what goes in the cut, and
a deterministic Python + ffmpeg engine does every render and every measurement,
so each decision leaves a file you can read.

> **Example.** The second real run: 20 drone clips (7 min of 1080p60) of two
> longboard surfers, turned into
> [a 45-second Instagram Reel](https://www.instagram.com/p/DeshltIBIST/). The
> first cut was delivered 1 h 49 min after the first message, 1 h 21 min of it
> active. The three
> re-cuts the operator asked for took 16, 15 and 64 minutes; about 45 minutes of
> the last went on finding a track. The run's own retrospective is in
> [docs/retro/2026-10-16-second-real-run.md](docs/retro/2026-10-16-second-real-run.md).

## What a run looks like

You say something like:

> "make a 45-second Instagram reel from ~/Movies/srilanka — calm, two surfers,
> open on the silhouette against the sun"

and the `using-montage` skill conducts the conveyor. Stages marked *optional*
run when the reel asks for them:

1. **Project.** The platform sets the aspect: 9:16 for Reels, Shorts and TikTok,
   16:9 for YouTube, 1:1, 21:9, or any custom ratio. By default the delivery keeps
   the crop's own pixels; a smaller social size or 4K are there if you ask.
2. **Footage intake.** Every clip is scanned once. Scene cuts are found with
   PySceneDetect, people are detected and tracked with YOLO11-seg and ByteTrack,
   camera shake is measured with vidstab, and each clip is carved into scored
   moment windows. The people who recur are clustered by appearance (OSNet re-ID)
   and shown to you as cards so you can name them. Photos (JPEG, PNG, HEIC) in
   the same folder come in too: upright, colour-managed to sRGB, framed on the
   people in them and given a slow sub-pixel push instead of a still frame.
3. **Contact sheets.** The agent looks at the frames of every window rather than
   trusting the scores alone.
4. **Brief** *(optional; checkpoint 1)*. One question at a time: length, mood, the
   opening shot, the ending, on-screen text, music, shot length, and how screen
   time is split between the people. The answers become `SPEC.md` for you to
   approve.
5. **Edit plan** *(checkpoint 2)*. The agent picks the windows and writes an edit
   decision list. A shot-variety gate checks it against the mood. Rules you state
   out loud of four kinds — never repeat a shot, open with, close with, exclude —
   are saved to `CONSTRAINTS.json` and bind every re-cut.
6. **Music** *(optional)*. A local track is matched to the mood, or one is
   searched for: ccMixter needs no key, Jamendo needs a free one, and with your
   opt-in yt-dlp can fetch from anywhere. librosa finds the beats and, when the
   track has a clear downbeat, the bars; demucs separates the vocals so the music
   can start in a pause rather than mid-word.
7. **Pacing** *(optional)*. The cuts are fitted to the coarsest musical grid they
   can reach (beat, half-bar, bar, two bars or phrase). When there is a bar grid
   and the closing shot has room, the reel's length is chosen so the closing fade
   starts on a bar line.
8. **Geometry and grade.** Each shot follows its subject: the tracked route drives
   a smoothed crop path that reframes 16:9 footage to 9:16. Optional per shot are
   a subject-anchored zoom, a pan, a speed ramp into slow motion, stabilization
   and a colour grade. A match-grade stage measures every shot's tracked crop and
   pulls them to one common tone, so footage from two cameras reads as one reel.
9. **Draft and titles** *(optional)*. A rough draft shows the cut before the
   real render, and titles (with icons) are authored for the final encode.
10. **Episodes.** Every shot is rendered and passes mechanical checks (framing,
    path smoothness, continuity, length, black frames, grade damage), then a fresh
    AI judge that sees only that one episode.
11. **Delivery and review** *(checkpoint 3)*. The assembled reel is checked for
    length and loudness (−14 LUFS), and whether the vignette, fades and titles
    actually reached the pixels; whether the subject stays inside the platform's
    safe zone is reported. It is delivered as `REEL_v{n}.mp4` with an attestation
    recording what passed. Last, an editorial reviewer compares the reel against
    your brief, and you decide.

Every artifact lands in one `montage/` folder beside your clips, organised by how
long it lives: `footage/` survives every re-cut, `reels/<name>/` holds one cut,
its `build/` is scratch the next render clears, and its `deliveries/` only ever
grows.

## Requirements

- **macOS with [Homebrew](https://brew.sh).** Linux and Windows are not supported
  yet.
- **Claude Code.**
- Disk and network for the install (Python 3.13, a full ffmpeg build, PyTorch,
  the YOLO weights) and on first use (the OSNet and demucs weights).

## Install

Everything happens inside Claude Code; there is nothing to clone.

**1. The plugin.**

```
/plugin marketplace add vasechko-sergey/video-grid
/plugin install video-grid@video-grid
```

Then restart Claude Code.

**2. The runtime.**

```
/video-grid:setup
```

The plugin carries the code; `setup` installs what it runs on, after telling you
what and asking: a Python 3.13 venv, `ffmpeg-full` (drawtext and vidstab; installed
beside any ffmpeg you already have and never replacing it), the title fonts,
demucs, yt-dlp and the YOLO weights. The first run takes 10–20 minutes, mostly
downloads. Nothing lands inside the plugin: the venv and the weights go to
`~/.local/share/video-grid/`, the recorded ffmpeg path to `~/.config/video-grid/`,
so every plugin version shares them. The OSNet and demucs weights download the first
time they are needed.

Check the install at any time with `/video-grid:verify-runtime`, which names each
missing piece and the command that fixes it.

**3. Make a reel.** From any directory, describe what you want and give the
absolute path to the footage folder. Most stages also have their own skill if you
want to re-run just one: `project-init`, `footage-intake`, `reel-brief`,
`edit-plan`, `music-match`, `music-source`, `pacing`, `match-grade`, `titles`,
`episode-qc`, `reel-review`.

**Updating.** In a terminal:

```bash
claude plugin update video-grid@video-grid
```

(or `/plugin` → Installed → video-grid → Update now), then restart Claude Code. If
the new version changed the Python dependencies, `verify-runtime` blocks on
`deps_stamp` and names the fix: run `/video-grid:setup` again.

**Upgrading from a clone install (before 0.27.0).** The old install registered the
clone itself as the `video-grid` marketplace, and Claude Code keeps one marketplace
per name, so `/plugin marketplace add vasechko-sergey/video-grid` is refused while
that one exists. Two ways forward:

- **Keep the clone as the marketplace.** `git pull` in the clone, then
  `claude plugin marketplace update video-grid` and
  `claude plugin update video-grid@video-grid`, restart, and run
  `/video-grid:setup` once.
- **Switch to GitHub.** `claude plugin marketplace remove video-grid` — this also
  uninstalls the plugin — then install as above and run `/video-grid:setup`.

Either way, setup carries over your Jamendo key and the YOLO weights from the old
clone (it reads the path 0.26.0 recorded) and records ffmpeg in
`~/.config/video-grid/`. After that the clone is only needed to work on the code.

## Honest limits

- **Tested on two real shoots so far**, both of people on boards over water.
  The thresholds that cannot yet be justified from data say so in the code and
  in [docs/backlog.md](docs/backlog.md), and are re-measured when a run supplies
  the data.
- **The agent is the editor.** The engine refuses what it can prove is wrong, such
  as a broken frame, a subject out of frame, or a fade that never rendered. It
  cannot prove a cut is good. That is what the three checkpoints are for.
- **Music rights are yours.** The `free` lane searches Creative Commons
  libraries. The `any` lane downloads with yt-dlp and records the source and an
  "unknown" licence beside the file. Whether you may publish that track is your
  responsibility.
- **It is slow on a laptop.** Intake of 20 clips took 14 minutes. A full re-cut
  with re-render, re-judging and review takes about 15 minutes.

## Develop

Start at **[CLAUDE.md](CLAUDE.md)**, a registry that points to the
[design spec](docs/specs/2026-07-05-montage-skillset-design.md), the
[coding standards](docs/coding-standards.md), the
[testing guide](docs/testing-guide.md), the
[development workflow](docs/development-workflow.md), the
[build status](docs/build-status.md) and the [pipeline map](docs/pipeline-map.md).

To work on the code, clone it and set the runtime up from the clone — the same
`setup.sh` the setup skill runs, sharing the same venv:

```bash
git clone https://github.com/vasechko-sergey/video-grid.git
cd video-grid
bash setup.sh
```

To have your reels run the clone's code, install the plugin from it instead of
from GitHub (`/plugin marketplace add ./` from inside the clone, then
`/plugin install video-grid@video-grid`) and update it after each change: the
skills always run the copy Claude Code installed. Running a script straight from
the clone — `.venv/bin/python -m scripts.X` in its root — is for tests and quick
checks: unlike `bin/vg`, it works in the clone root, not the shared models
directory.

The code is laid out in three places:

- `scripts/` holds the engine and its CLIs, run as modules: `bin/vg scripts.X …`.
- `scripts/lib/` holds the typed contracts.
- `skills/*/SKILL.md` holds the editorial judgment.

New work goes design → plan → test-first implementation with review. Every merged
change bumps the version in [CHANGELOG.md](CHANGELOG.md).

```bash
.venv/bin/python -m pytest -q                  # the whole suite
.venv/bin/python -m pytest -q -m integration   # the real-ffmpeg / real-weights proofs
```

## Licence

AGPL-3.0, see [LICENSE](LICENSE). This licence was not a free choice:
`ultralytics`, the YOLO11 runtime that footage intake imports on its main path, is
AGPL-3.0. The model weights are not redistributed here: they are downloaded from
their own publishers at install or first use. This declares a licence; it is not
an audit of the transitive dependency tree.
