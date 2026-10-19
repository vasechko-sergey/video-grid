# video-grid

**A folder of raw footage plus a few sentences in, a finished vertical reel out.**

video-grid is a skill set for [Claude Code](https://claude.com/claude-code). You
describe the video you want in plain language. Claude then works through the edit:
it watches the footage, finds the moments, cuts them to the music, reframes each
shot for the platform, grades it, adds titles and checks its own work. It asks
you questions along the way (who is who, what the reel is for) and waits for
your approval at three checkpoints. The agent decides what goes in the cut, and
a deterministic Python + ffmpeg engine does every render and every measurement,
so each decision leaves a file you can read.

> **Example.** The second real run: 20 drone clips (7 min of 1080p60) of two
> longboard surfers, turned into a 45-second Instagram Reel. The first cut was
> delivered 1 h 49 min after the first message, 1 h 21 min of it active. The three
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
   the crop's own pixels; a smaller social size or 4K are one flag away.
2. **Footage intake.** Every clip is scanned once. Scene cuts are found with
   PySceneDetect, people are detected and tracked with YOLO11-seg and ByteTrack,
   camera shake is measured with vidstab, and each clip is carved into scored
   moment windows. The people who recur are clustered by appearance (OSNet re-ID)
   and shown to you as cards so you can name them.
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
   can reach (beat, half-bar, bar, two bars or phrase). When there is a bar grid,
   the reel's length is chosen so the closing fade starts on a bar line.
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

The plugin distributes the skills, and `setup.sh` installs the runtime they drive.
You need both. A plugin install alone cannot make a reel.

**1. The runtime.**

```bash
git clone https://github.com/vasechko-sergey/video-grid.git
cd video-grid
bash setup.sh
```

`setup.sh` installs everything with no opt-in flags: a Python 3.13 venv,
`ffmpeg-full` (drawtext and vidstab), the title fonts, demucs, yt-dlp and the
YOLO weights. The OSNet and demucs weights download the first time they are
needed. Keep the clone where it is: the skills run its
`bin/vg`, whose path `setup.sh` records.

**2. The plugin**, from inside Claude Code in the clone:

```
/plugin marketplace add ./
/plugin install video-grid@video-grid
```

Then restart Claude Code. Check the install at any time with
`/video-grid:verify-runtime`, which names each missing piece and the command
that fixes it.

**3. Make a reel.** From any directory, describe what you want and give the
absolute path to the footage folder. Most stages also have their own skill if you
want to re-run just one: `project-init`, `footage-intake`, `reel-brief`,
`edit-plan`, `music-match`, `music-source`, `pacing`, `match-grade`, `titles`,
`episode-qc`, `reel-review`.

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

The code is laid out in three places:

- `scripts/` holds the engine and its CLIs, run as modules: `bin/vg scripts.X …`
  or `.venv/bin/python -m scripts.X`.
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
their own publishers at install or first use. This declares a licence. It is not an audit of the transitive
dependency tree.
