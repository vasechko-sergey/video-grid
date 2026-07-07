# ffmpeg recipes

Exact command snippets used by the scripts, kept in sync with the source —
if a script's ffmpeg call changes, update the matching entry here. Each
recipe: command shape + one-line why. See `references/landmines.md` for the
failure modes these recipes are designed around.

## Output-seek extract (`scripts/extract.py`)

```
ffmpeg -y -i <src> -ss <start> -t <dur> \
  -c:v libx264 -crf <crf> -preset medium -pix_fmt yuv420p \
  -c:a aac -b:a 192k <out>
```

**Why:** `-ss` **after** `-i` (output seek) + re-encode of the short window
→ frame-accurate cut, no black frames. Landmine is the *arg order*, not
resolution — 4K is cut natively, never downscaled first. Audio is preserved
(`aac`) — it becomes the ambient bed for audio-mix.

## Crop + scale + color (`scripts/reframe.py`)

```
-vf "crop=<crop_w>:<crop_h>:x='<xexpr>':y=0,
     scale=<out_w>:<out_h>,
     colorchannelmixer=rr=<rr>:gg=<gg>:bb=<bb>,
     fps=<fps>,format=yuv420p"
```
```
ffmpeg -y -i <src> -vf "<above>" -c:v libx264 -crf 18 -preset medium -an <out>
```

**Why:** `x=` is a piecewise-linear expression over Douglas-Peucker-simplified
path knots (`if(lt(t,t1), x0+slope*(t-t0), …)`) — smooth crop motion from a
short expression instead of one `if()` per frame. `y=0` because v1 only
handles full-source-height crops (no Y freedom yet, spec §6.4). Color is
`colorchannelmixer=rr=:gg=:bb=` with gains from `scripts/lib/color.py`
(`gain = 1 + 0.55*(target/measured - 1)`, clamped `[0.7, 1.5]`) — **never
`lutrgb`**, which produces black frames (landmines.md).

## blackdetect (`scripts/check_episode.py`)

```
ffmpeg -i <clip> -vf "blackdetect=d=0.05:pic_th=0.98" -an -f null -
```

**Why:** cheap numeric black-frame check — count `black_start` matches in
stderr; any match fails the episode (spec §9 "mean luma > 8" gate).

## vidstab two-pass (process-episode plan, spec §10)

*Not yet wired into a script — process-episode, requires a vidstab-enabled
ffmpeg (see `setup.sh` warning: `brew install homebrew-ffmpeg/ffmpeg/ffmpeg
--with-libvidstab`).*

```
ffmpeg -i <src> -vf "vidstabdetect=shakiness=8:accuracy=15:result=<FILE>.trf" -f null -
ffmpeg -i <src> -vf "vidstabtransform=input=<FILE>.trf:smoothing=40:optzoom=1:zoom=2:crop=black,unsharp=5:5:0.4" <out>
```

**Why:** two-pass stabilization on the **source before crop**. Detect pass
warning `"cannot read frame local motions… got 255"` is cosmetic
(landmines.md). **Never run on wade-in/out shots** — produces "rolling
ground" (landmines.md). `stabilize?` is a per-episode flag.

## Concat (assemble-draft, spec §5.9 — follow-on to core)

*Not in the core plan's scripts — `assemble.py` in the assembly/deliver
follow-on plan.*

```
# normalize every segment to uniform size/fps/codec first, THEN concat
ffmpeg -i <seg_i> -vf "scale=<W>:<H>,fps=<fps>,format=yuv420p" -c:v libx264 -c:a aac <norm_i>
ffmpeg -f concat -safe 0 -i <segments.txt> -c copy <draft.mp4>
```

**Why:** concat demands uniform streams — mixed size/fps/codec segments
break or desync on straight concat (landmines.md); normalize first, copy on
concat. Draft labels use `drawtext` with an explicit `fontfile=` (macOS has
no reliable fontconfig default — landmines.md).

## Storyboard frame sampling (`scripts/storyboard.py`)

```
ffmpeg -y -i <src> -vf "fps=<rate>" -frames:v <n> <tmp>/f%02d.png
```

**Why:** `rate = n / duration` samples `n` frames evenly across the clip for
the contact sheet; `-frames:v` caps output count so rounding in `fps=` never
over/under-shoots. Frames get thirds/phi grid + hero-marker overlays drawn
in Pillow, not ffmpeg (spec §6.1a, §6.5).
