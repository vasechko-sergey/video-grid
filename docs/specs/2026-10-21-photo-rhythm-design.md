# Photos on the beat, among video — held episodes, the freeze, the shutter, the burst

**Status:** designed 2026-10-21. Backlog U7 + U8, the photo epic's second slice
(the first: [photos design](2026-10-20-photos-design.md), 0.26.0).

## §0 · Why

0.26.0 gave a photo the road a video window takes, and two things it left out are this
slice:

- **U7 · its length.** Scenario-first pacing assumes the footage owns an episode's length
  and the grid only picks which line its cut lands on (±half a beat). A photo has no
  length of its own: it took intake's 2.0 s placeholder and the fitter nudged it, so every
  photo in a reel held about two seconds whatever the music did. The research (2026-10-20,
  "Ритм") is the inverse rule: for a still the grid AUTHORS the length — whole beats,
  deliberately varied (1, 2, 4), shorter where the music is louder, so a run of photos
  speeds up into a drop the way every slot template does.
- **U8 · living among video.** Three things: (a) the one documented technique that makes
  a still inside video read as intended — the **freeze-frame "like a photograph"**: hold
  the frame, a minimal white dip on the cut, a shutter sound; (b) the same **shutter
  accent** on a photo cut in among video; (c) **choosing which**: a phone shoots bursts
  and near-identical retakes, and a scorer that ranks them one by one picks three of the
  same frame. The research's rule is to group before ranking. And the 0.26.0 limit that a
  photo's score is meaningless beside video's (motion 0 ranks it lowest, shake 0 highest)
  is closed by ranking photos among photos.

The segment contract itself (rate, timescale, SAR, range, BT.709 tags) shipped in
0.26.0; what was missing is a reel that proves it with video, a photo and a freeze in
one master, which §6 adds.

## §1 · Held episodes

A **held** episode is one whose length nothing in the footage fixes: a photo, or a
freeze (§3). `EDLEpisode.held()` is the one predicate. Two optional fields ride on held
episodes only, and are refused by name on video:

- `hold` — an authored length in **beats** (int ≥ 1). It outranks the planner (§2.1),
  e.g. for a hero photo the brief wants held longer.
- `shutter` — the accent of §4 (bool).

`lib/hold.py` owns the conventions, pure and stdlib-only:

| name | value | meaning |
|---|---|---|
| `HOLD_DEFAULT` | 2.0 s | a held episode's length when no music binds it (intake's old `PHOTO_HOLD`) |
| `HOLD_ROOM` | 8.0 s | the longest hold (intake's old `PHOTO_ROOM`) |
| `HOLD_MIN` | 1/3 s | the shortest: WCAG 2.3.1 allows at most three flashes a second, and a hard cut between two stills is the same event |
| `BAND_HOLD` | release 2.0 / build 1.0 / peak 0.5 s | the research's three working modes, keyed by pacing's energy bands |

`intake.PHOTO_HOLD`/`PHOTO_ROOM` stay as aliases of the first two.

## §2 · U7 — the grid authors a held length

### §2.1 · How many beats

At a held episode's in-point `pos` the planner reads the music's per-beat energy
(pacing's own min-max normalisation) over the next bar — the four beats from `pos` — and
labels it with pacing's bands. The band's target seconds become beats as the **power of
two nearest in log2** (1, 2, 4, 8 — musical lengths), then clamped to
`[⌈HOLD_MIN/beat⌉, ⌊HOLD_ROOM/beat⌋]`. At 120 BPM that is 4 / 2 / 1 beats (2.0 / 1.0 /
0.5 s); at 90 BPM 4 / 2 / 1 (2.67 / 1.33 / 0.67 s); at 170 BPM 8 / 4 / 2 (2.82 / 1.41 /
0.71 s). The floor binds only above 180 BPM, where one beat is under 1/3 s. A rising
build therefore shortens the holds by itself: "accelerating into a drop" is read through
the energy bands, not through a separate drop detector.

**Variation.** Inside one run of consecutive held episodes, the planner never gives the
same count three times in a row: the third takes double (if that stays under the
ceiling), else half (if that stays over the floor) — so a build reads 2, 2, 4, 2, 2, 4
rather than a metronome. The CapCut finding the research quotes: when every cut follows
the same peak the edit reads as a template.

### §2.2 · Where the cut lands

`gridfit.fit_level` walks the cuts left to right as today. A held episode does not snap;
its out-point is **chosen**:

- target = `pos + k·beat`; candidates are the DETECTED beats in `[pos + lo, pos + hi]`
  (`lo = HOLD_MIN`, `hi = HOLD_ROOM`); the one nearest the target wins. Inside a run the
  cut is therefore on a beat by construction and its deviation is 0.
- **The run's last hold** (the next episode is video) chooses among the LEVEL's lines
  instead, so the cut back to footage is as musical as every other cut of the reel — but
  only inside `[k/2, 2k]` beats of its plan (within `[lo, hi]`). Across the whole
  `[lo, hi]` a phrase line is almost always reachable, so every coarse level would "fit"
  by stretching the last photo, and coarsest-that-fits would pick it: Task 2 measured a
  planned 2-beat photo bound to 10 beats. No line in the band: it keeps the beat and its
  deviation counts against the level — which then may not fit, and the rule falls to a
  finer level, as for any cut.
- An authored `hold` is placed the same way but never moved for the level.
- A held tail (the reel's last episode) is placed on a beat; the outro fit then owns the
  reel's end as before, growing it into `HOLD_ROOM`.
- Past the last detected beat (music shorter than the reel) the target itself is used.

gridfit stays repo-import-free: it gets per-episode `Held(beats, lo, hi)` records and a
`plan(pos, run) -> beats` callable, which `pacing.fit_spine` builds from the energy curve
and `lib/hold.py`. The beat period is `2 · allow` (the allowance is half a beat by
definition).

### §2.3 · Binding

`Slot.held` marks a slot whose length the grid authored (emitted only when true, so a
video-only PACING.json is byte-identical). `_bind_pacing`'s half-beat guard exists to
catch a spine fitted to a different edit; for a held episode it cannot apply (the length
legitimately moves by seconds), so the identity check becomes kind-against-kind: a held
episode needs a held slot and a video episode a video slot, either mismatch refused. The
fit stays a fixed point: a held length is a function of the music and of the positions
the scenario's own lengths produce.

`scripts/pacing.py` refuses an authored `hold` outside `[HOLD_MIN, HOLD_ROOM]` at the
window's tempo, naming both. Anchors skip held episodes. PACING.md prints a held slot's
beat count. `_apply_outro` grows a held closer into `HOLD_ROOM`, not into the clip's room
(for a freeze the clip's room means nothing).

Without music nothing binds, and a held episode plays `HOLD_DEFAULT`; an authored `hold`
is then logged as unused, since beats need a tempo.

## §3 · U8a — the freeze

A selection entry `{"freeze": true}` (optionally with `shutter` and `hold`, nothing else)
holds **the previous episode's last frame**. It must follow a video episode. The episode
copies the previous one's editorial fields — layout, crop, composition, hero, colour —
and drops what addresses time (`ramp`, `pan`, `zoom`, `stabilize`, `motion`,
`smooth_window_s`); `EDLEpisode.freeze` refuses those by name, and `still` too. A freeze
defaults `shutter: true` (§4): without the accent a held frame reads as a stalled player.

`start` records the frozen frame's source time, `prev.start + prev.dur − 1/fps`, resolved
last in `build_edl` because pacing and the outro fit move the previous cut. It is a
label (the cut identity, EDL.md). The PIXELS come from the previous episode's own
segment: `extract` takes its **last decoded frame** by count
(`trim=start_frame=n−1,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop=N−1` plus the
segment's range pair, no audio — the research: the sound stopping on a freeze deepens
it). A formula over source time cannot promise that: off the frame grid, which frame
output-side `-ss`/`-t` keeps last depends on ffmpeg's trim internals. Measured over 28
random off-grid cuts at 30 fps, the formula's frame was a neighbour of the segment's real
last frame in 5, in both directions (0.152 s / 1.209 s one early, 0.482 s / 1.592 s one
late); counting the segment's frames was right in 28 of 28.
A ramped predecessor's segment is already retimed by then, so its last frame is the one
that plays.

A freeze is a **video episode** in every other respect — framed, graded and checked like
any window — except that it is **not tracked**. Re-tracking one cloned frame loses what
the previous episode was following (the Task 1 review): with no motion an unpinned pick
falls back to size and may take another person or tie, a frame left empty stops on
`no-track`, flow builds a route out of encode noise, and a motion-keyed composition reads
a direction from nothing. So `edl_to_reel` renders freezes in a second wave, after their
predecessors, each handed a **held route**: the predecessor's last route sample repeated
over the freeze's frames — the same person, where the previous episode left them. The
held route is what GEOMETRY.json records, so phase 1b and the reprocess loop need nothing
new. A freeze composes `center` (a held route has no travel to lead with) at the
predecessor's crop scale times its zoom's end width when it had a zoom, so a push-in
freezes pushed in. A freeze after a `pan` is refused: a pan has no route, and its window
holds nobody to freeze on. `zoom` on the freeze itself is refused because `zoompan`
stair-steps on a still (photos design §0); a pushed freeze would be the float warp, not
this slice.

The cut identity carries `freeze`, and edit-plan leaves a freeze out of the variety
census and the constraint projection: it is not a new use of footage, and `no_repeat`
would otherwise refuse every freeze as a repeat of its own shot. The constraint messages
still name EDL indices.

## §4 · U8b — the shutter accent

`shutter: true` on a held episode puts two things on its cut, both reel-level and both
at the master's real cut time (the probed clip durations `check_reel` already sums):

- **a white flash** in `deliver`'s one encode: three frames of full-frame white at 0.85,
  0.5, 0.2 opacity (`drawbox … t=fill:enable='between(t,a,b)'`), placed before the
  titles and the bookend fade so a fade still darkens it. In deliver and not in the
  episode, because every colour sensor (match-grade's measurement, `grade_damage`,
  `grade_faithful`) reads the episode or the master, and a white frame under any of their
  samples would read as a grade. Deliver's own look gate compares the delivered file
  against the master, so its samples are moved out of every flash window (the vignette's
  mid sample, the titles' in-window times and witnesses).
- **a shutter click** in mix's SFX bed: two seeded 15 ms high-passed noise bursts 70 ms
  apart, at the cut, un-ducked, through the bed the whooshes already use (the stem is
  built when there is music; a reel without music has no stem and so no click).

`ReelManifest.shutters` lists the accented episodes' indices (omitted when empty);
`edl_to_reel` fills it from the EDL.

## §5 · U8c — groups, and photos ranked among photos

- `still.load` records the capture time (EXIF `DateTimeOriginal` + `SubSecTimeOriginal`,
  with `OffsetTimeOriginal` when present; absent → no time). Intake stores it and a
  **sharpness** (variance of the Laplacian of the luma at the analysis proxy's long side,
  960) in the cached photo result. `CACHE_VERSION` 9 → 10.
- Phase 2 **groups** photos: two photos are one group when their capture times are
  within `BURST_GAP = 2.0` s of each other (chained through time order), or their pHash
  distance is under `DEDUP_DIST`. A group of two or more gets an id (`g1`, … in path
  order) on `FootageClip.group`, omitted for a lone photo.
- **Photos rank among photos.** `score_pool` splits the pool by kind: video windows rank
  exactly as before among video windows only (a video-only set is byte-identical), and a
  photo's score is its percentile among photos of `W_PRESENT·presence + (1−W_PRESENT)·
  sharpness`. `Footage.scoring` gains a `photos` report with the same separated counts.
- **One per group.** `cull` marks best at most one photo per group, the highest scored —
  the sharpest when presence ties, which is a burst's usual case.
- FOOTAGE.md names each photo's group and size; the edit-plan skill says to use one
  photo per group unless the cut means the sequence.

## §6 · Proof: one reel

A real-ffmpeg reel of a video window, a photo with a shutter, a freeze and a second
video window, with music: delivered; every episode clip on one rate; the flash in the
delivered file at the photo's and the freeze's cuts and not in the master; the click in
the stem at those times against a control without accents; the freeze's frame is the
previous segment's last frame (nearer it than the frame before); the held lengths whole
beats of the music.

## §7 · Honest limits

- `BAND_HOLD`, `HOLD_MIN`, the variation rule, `BURST_GAP`, the photo blend's weights and
  the flash's three opacities are conventions from the research, not measured on a real
  photo run.
- The drop is read through energy bands; a track whose energy curve is flat gives every
  hold the same band and only the variation rule moves them.
- Capture time without an offset is read as UTC: differences inside one camera are right,
  across two cameras with different clocks they are not, and a burst split across them is
  two groups.
- Sharpness is focus and motion blur, not taste; there is no aesthetic model.
- A freeze re-centres its subject: after a `lead` episode the subject moves from the
  third line to the centre on the cut. The flash covers it; nothing reproduces the lead.
- A freeze after a stabilized episode holds the raw frame under a route measured on
  stabilized pixels, a few pixels off; the flash covers the cut, nothing corrects it.
- The flash is not in `draft.mp4`, and nothing checks that it rendered beyond the proof.
