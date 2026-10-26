# edit-plan — every authorable episode field

**The reel's finish is `"look"`, a top-level key, not a per-episode one.**
`{"vignette": 0.0-0.6, "fade": 0.0-2.0, "fade_in": 0.0-2.0}` — corner darkening, the
closing fade in seconds, and (optional) the opening fade when it differs: omit
`fade_in` and the opening equals `fade`. Every mood preset opens on picture
(`fade_in: 0`) — the first frame is the hook, and the second real run's hook
opened on black. Applied once over the whole reel at `deliver`, never per episode.
Omit it and the mood's preset (`MoodPreset.look`, resolved from `SPEC.mood`
the same way the variety gate resolves its shot-mix) decides — unless
nothing matches: a skipped or mood-less brief leaves `EDL.look`
**unauthored** (`None`), never filled from `balanced`'s own preset row,
because filling it with any concrete value would itself be a taste nobody
chose (a real fade) or a silent change to the audio bookend every reel has
had since the music spine (see the next paragraph). Unauthored, `deliver`
applies no vignette or fade and `mix` keeps its own 0.5s audio default — so
an autonomous run with no brief looks exactly as it did before looks
existed.

Write `{}` or `{"vignette": 0, "fade": 0}` to mean *no look, and the preset
does not get to override that* — but know this is **not** the same as
omitting the key. An authored `{"vignette": 0, "fade": 0}` sets `EDL.look`
to a real `LookSpec`, and `build_reel` then passes its `fade=0.0` to `mix`
explicitly, switching OFF the 0.5s audio bookend every other reel keeps (the
music still opens on a 20 ms anti-click ramp, and a reel whose length the outro
fit chose still closes on the fit's own fade). An
authored zero is a decision with an audible consequence, not the same
no-op as leaving the key out — they render the same silent picture but not
the same audio. A hand-picked `{"vignette": 0.4, "fade": 1.0}` overrides
the preset the same way. `edit_plan build` logs which source won
(`selection.json`, the `<mood>` preset, or "left unauthored" when nothing
matched) on every run — read that line rather than assuming.

Dedup across sources so one clip doesn't dominate, fit the running sum to the
target length, and order them **hook first**. For each episode assign:
- `composition` ∈ `lead` / `center` / `break` (required)
- `grid` ∈ `thirds` / `phi` (required)
- `layout` ∈ `fill` / `fit` / `insert` (default `fill`)
- `background` ∈ `blur` / `solid` (default `blur`; `fill` accepts only `blur` —
  it covers the canvas edge to edge, so there is nothing else to fill) +
  optional `background_color` (an ffmpeg colour name or hex, default `black`,
  `solid` only)
- `crop_aspect` (optional) — the crop rectangle's aspect, `"9:16"` or
  `[9, 16]`. Omit it and the manifest picks: the canvas for `fill`, the
  source's own aspect for `fit`/`insert`. Author it only to take a crop
  shaped like neither.
- `crop_scale` (optional, default `1.0`) — the crop's size as a fraction of
  the largest one that fits. Below `1.0` tightens the framing and buys the
  tracker freedom to move within the source. A **still** choice, unlike
  `zoom`, which changes the crop's width over time.
- `border_px` / `border_color` (optional, `insert` only, default `0` /
  `white`) — the card's border in delivered pixels and its colour. `0` draws
  none.
- `motion` ∈ `lateral:right` / `lateral:left` / `head-on` / `static` (optional)
- `hero` (optional) — a first-frame seed bbox `[x,y,w,h]` (centre-format,
  source px), a rule (`largest`/`leftmost`), an integer track id, or a cast
  name resolved through `cast.json` (§6.1a). A cast name needs the registry:
  pass `--cast` (the edit-plan skill's step 3) and the name must exist in
  `cast.json` — an
  unresolvable name is a preflight `edl-invalid` (fix `selection.json` and
  re-run), and a pin that matches nobody in the episode's segment is a
  `hero-unmatched` stop-and-report at process-episode time — never a silent
  fallback to intent scoring.
- `zoom` (optional) — `{"from": 1.0, "to": 0.7}`, a **subject-anchored**
  push-in/pull-out: two fractions of the layout's crop WIDTH (`1.0` the
  whole crop, `0.7` a 1.43x push-in; direction is the sign of `to - from`,
  same convention as `pan`). Unlike `pan` it does NOT replace the tracked
  route — the rect's position still comes from the SAME composition rule
  as any tracked episode, only its width shrinks or grows, which is what
  keeps every `check_episode` check (framing/continuity/`grade_damage`)
  applying to it in full, exactly as it does to a still crop. It therefore
  **needs a tracked subject** — there is no route to ride without one —
  and `zoom` together with `pan` on one episode is refused (one anchors to
  a subject, the other declares there is none). Both fractions must be in
  `(0, 1]`; a push-in tightened past `ZOOM_MAX_UPSCALE` (1.5x, an
  unresolved-upsample ceiling) or faster than `ZOOM_MAX_RATE` (0.5
  crop-widths/second, a whip-zoom guard) is refused, not silently clamped.
- `still` (optional, a **photo** only) — `{"from": 1.0, "to": 0.92}`, the move
  over a photo (design 2026-10-20): a push toward the people YOLO finds in it,
  two fractions of the photo's base frame width, equal ends allowed for a photo
  held without a move. Absent means that default 8.7 % push-in; `{"from": 0.92,
  "to": 1.0}` pulls out. It is rendered sub-pixel into the segment at extract,
  so nothing is tracked and framing reads `editorial-only`. A photo's default
  `layout` is `fill` when a canvas-shaped crop keeps 60 % of it (portrait 3:4,
  4:5) and `fit` with the blurred field otherwise (square, landscape); author
  `layout` to override. A photo refuses `zoom`, `pan`, `ramp`, `stabilize`,
  `hero`, `motion`, `smooth_window_s` and any `start_offset`, and a move faster
  than `ZOOM_MAX_RATE` for its hold. With `--pacing` the music grid authors its `dur`
  in whole beats — 1/3 s to 8.0 s, shorter where the music is louder (design 2026-10-21
  §2); `hold` (below) asks for a count. The move keeps the TOP half of the people whole
  (heads), shortening itself rather than cut it.
- `freeze` (a selection entry of its own) — `{"freeze": true}` holds **the previous
  episode's last frame**, "like a photograph" (design 2026-10-21 §3). It carries only
  `freeze`, `shutter` and `hold`; source, window, layout, crop, hero and colour it
  inherits from the episode before it, which must be a played video window that is not
  a `pan` — a freeze cannot open the cut or follow a photo, another freeze or a pan
  (a pan follows nobody). It composes `center` at the crop the previous episode ends
  on (a `zoom` there: its end width). It is **not tracked**: it is framed over the
  previous episode's last route sample, held — the same person, where that episode
  left them — so after a `lead` the subject moves from the third line to the centre on
  the cut. It drops what addresses time (`ramp`, `pan`, `zoom`, `still`, `motion`,
  `smooth_window_s`, `stabilize`), plays 2.0 s when no music binds it, and its segment
  is silent. Its `shutter` is on unless the entry says `"shutter": false`. It is not a
  new use of footage: the variety census and `CONSTRAINTS.json`'s `no_repeat` both skip
  it. It follows wherever the previous cut lands, after pacing and the outro fit.
- `shutter` (optional, a photo or a freeze only) — the shutter accent on the
  episode's cut: a white flash and a shutter click (design 2026-10-21 §4). A freeze
  defaults it to `true` — without it a held frame reads as a stalled player; a photo
  defaults to `false`. Refused on a played video window.
- `hold` (optional, a photo or a freeze only) — a length in whole **beats** (an int
  ≥ 1) that outranks the music grid's own pick (design 2026-10-21 §2.1), e.g. for a
  hero photo the brief wants held longer. Without it the grid plans the count from the
  music's energy over the bar that opens the hold — at 120 BPM 4, 2 or 1 beats as that
  bar is quiet, mid or loud, never the same count three times in a row inside a run of
  holds — and the run's last hold before a video ends on a line of the reel's level
  when one lies within half to twice its plan. Beats need a tempo: without `--pacing` it is
  unused — `edit_plan build` says so — and the episode plays 2.0 s. Pacing refuses a
  count that cannot last 1/3 s to 8.0 s at the window's tempo. An authored count is
  never moved to reach a line, and the grid level is the whole reel's: when the hold is
  the last before a video, the cut back stays on the level's lines only if the count is
  a whole number of them — 4 or 8 beats keep a bar grid, 8 a 2-bar one, 2 only a
  half-bar, an odd count only the beat — so one odd `hold` there can cost every cut in
  the reel its bar alignment. Changing a `hold` means re-running pacing.
- `pan` (optional) — `{"from": f, "to": f}`, a **generated** constant-velocity
  camera move: two fractions of the crop's horizontal freedom (`0.0` hard
  left, `1.0` hard right; direction is the sign of `to - from`). It replaces
  tracked motion for the episode — no route is read, no hero is followed.
  May be authored **only over a window `FOOTAGE.md`/`SHEETS.md` show as
  empty of people** — intake's own measured `present` fraction, not your
  read of the frame. `edit_plan build` refuses a `pan` over a window
  holding people (`FootageWindow.present` above `PAN_PRESENCE_MAX`, 10% of
  samples): a route-less move turns off framing and continuity, which is
  only legitimate for a shot with no subject to check in the first place —
  not an editorial choice `pan` gets to make on your word. (`grade_damage`
  left that list on 2026-09-16: a pan now GAINS a full colour reading over
  the whole delivered frame, named `region: "crop"` with
  `region_fallback: "no-route"`, where it used to report nothing at all.)
  The gate enforces two further constraints: `composition` must be
  `center` (a pan positions the crop by its own law, so `lead`/`break`'s
  subject-relative framing has nothing to consult — a preflight
  `edl-invalid` names the conflict), and no `hero` pin may be set alongside
  it (the pin says "follow this person", the pan says "follow nobody").
  `motion` may still be set — it describes the *subject*, the pan describes
  the *camera*, and the canonical pan is `motion: static` with a moving
  frame, both at once.
- `ramp` (optional) — `{"at": 2.0, "factor": 0.4, "ease": 0.5, "hold": 1.0}`,
  a **speed ramp**: playback eases down to a slow plateau around one moment
  and back up — the "hit the drop in slow-mo" move, not a whole-shot
  slowdown. All four numbers are seconds (or a plain multiplier) measured
  from the **window's own start**, never the clip's: `at` is the plateau's
  centre, `factor` is the minimum speed as a literal multiplier (`0.4`
  means 2.5x slower, not "40% speed"), `ease` is the cosine ramp-in/
  ramp-out length each side, and `hold` is the plateau's own length at
  `factor`. The region `[at − hold/2 − ease, at + hold/2 + ease]` must sit
  entirely inside the window — a ramp that pokes past either edge is
  refused, naming the overhang, not clamped. The slowest legal `factor` is
  capped by `MIN_RAMP_FPS = 24.0`: slowing DUPLICATES frames rather than
  creating them, so a plateau below 24 unique frames per second reads as
  stutter — the floor is `24 / clip fps`, i.e. `0.4` on 60 fps footage but
  only `0.8` on 30 fps (`FOOTAGE.md` prints each clip's rate; a deeper
  ramp needs higher-fps footage, not a lower floor). **Author the ramp
  before running pacing** — the beat grid is fitted to each episode's
  PLAYED length, and a ramp added afterwards makes the binding guard
  refuse, naming the pacing re-run as the fix. A ramped episode therefore
  plays longer than its window; `EDL.md` shows both numbers on its row. The
  segment loses its audio entirely (slowed sound is pitch garbage) — say so
  in `processing_notes` when the shot had nat sound worth keeping, and
  weigh leaving it unramped instead.
- `processing_notes` — a short note for the draft labels (optional)
- **colour** (all optional, per episode; every episode carries an identity-default
  grade, so omit these unless a clip needs correcting): `white_balance` ∈ `[0, 1]`
  neutralizes a cast first (grey-world; `0` = off); `black_point` ∈ `[0, 0.35]`
  lifts a washed toe; `highlight` ∈ `[0.6, 1.0]` tames blown whites; `saturation`
  ∈ `[0.5, 1.5]` scales chroma; `shadow_red` ∈ `[0, 0.20]` neutralizes a green/cyan
  black; `highlight_red` ∈ `[0, 0.35]` pulls only the red **shoulder** down — de-pinks
  specular foam/spray carrying a bright red object's reflection, leaving everything
  below the 0.60 knee (water, skin, the object itself) alone; `mid_blue` ∈
  `[0.80, 1.20]` fixes sky-bounce on skin; `dip` ∈ `[0, 0.5]`s
  fades the episode in/out to dark grey. `tone` matches a clip's tonal profile to
  the reel: set `tone_src` to that clip's measured `[p5, p50, p95]` luma and
  `tone_dst` to the reel's common target. **You will rarely author this pair by
  hand**: **match-grade** authors it for every episode from the tracked CROP, and
  that is the reading the reel is judged against (`check_reel`'s blocking
  `grade_faithful`, which predicts from your FULL declared chain, not the
  bare tone pair — a post-tone knob moves the prediction and the delivery
  together and cancels). If you do author one, read `tone_src` off the crop — `probe grade
  --geometry ... --index N` prints `tone_profile`, ONE pooled `(p5, p50, p95)` of
  the pixels that ship. `"$VG" scripts.color_measure <clip>` measures a WHOLE
  source frame instead, which on real footage differs from the crop by a median of
  14 and a maximum of 36 luma units — useful for a quick look at a file, wrong as
  the source anchor of a pair. A banding `tone` curve fails loud at render
  (`verify_tone`), so trust the error and widen the anchors.
- `color_means` (optional) — the target channel means `[r, g, b]` that
  `check_episode`'s colour check measures the DELIVERED clip against. Not a
  grade: it changes what "correct" means, never how a pixel looks. Leave it
  at its default unless a shot must match a specific reference — reach for
  the grade knobs above to change how a clip looks, and for `tone_src`/
  `tone_dst` to make several clips agree.

**Every knob, in one place.** The prose above is the explanation — it carries
the refusals and the reasons, and it is what you read before authoring. This
is the index into it. Anything absent from this table is not authorable from
`selection.json`.

| knob | what it sets |
|---|---|
| `source` / `start` / `dur` | which clip, from where, for how long |
| `base_dur` | the footage-projected length, recorded once at projection — never author it |
| `shot_type` | the label; the variety gate measures delivered geometry, not this |
| `composition` / `grid` | `lead`/`center`/`break` × `thirds`/`phi` |
| `layout` | `fill` / `fit` / `insert` |
| `background` / `background_color` | the filler behind a `fit`/`insert` frame |
| `crop_aspect` / `crop_scale` | the crop rectangle's shape and its size |
| `border_px` / `border_color` | the `insert` card's border |
| `motion` | the SUBJECT's travel, for intent scoring |
| `hero` | who to follow — bbox, rule, track id, or cast name |
| `pan` | a generated camera move; refused over a window holding people |
| `zoom` | a subject-anchored push-in/pull-out along the tracked route |
| `still` | a photo's move — a push toward its people, rendered into the segment |
| `freeze` | a selection entry of its own: hold the previous episode's last frame |
| `shutter` / `hold` | a photo's or a freeze's cut accent / its length in beats |
| `ramp` | a speed ramp down to a slow plateau and back |
| `stabilize` | the vidstab pre-stage; never on a wade-in/out shot |
| `smooth_window_s` | seconds of path smoothing |
| `white_balance` · `black_point` · `highlight` · `highlight_red` · `shadow_red` · `mid_blue` · `saturation` · `dip` | the colour grade, applied in that order |
| `tone_src` / `tone_dst` | the match-grade pair; `match_grade` authors these |
| `color_means` | the colour CHECK's reference means, not a grade |
| `processing_notes` | free text, rendered into `EDL.md` and the draft's labels |
| `beat_slot` | which grid line the cut lands on; `--pacing` writes it |

Two keys are **reel-level** and sit beside `episodes`, never inside one:
`look` and `variety_waiver`.
