# Editing canon

Classic composition/editing rules (spec §6.3) + the composition-grid library
(spec §6.5). A working reference for `edit-plan`, `process-episode`, and the
checks — not an essay. Read alongside `TRENDS.md` (current trend lean,
blended per `SPEC.style-lean`).

## Classic canon

- **Rule of thirds** — place points of interest on lines/intersections at
  1/3 and 2/3 of the frame, not dead center (unless `center` composition).
- **Headroom** — don't crowd the top of frame; leave air above the head, but
  not so much the subject sinks low. v1 rule: head near the upper-third line
  (`head_y ≈ 0.30·crop_h`); no head data → subject centre at `0.45·crop_h`.
- **Lead room (nose room)** — leave space in front of a subject facing or
  moving in a direction, not behind. This is where the `lead` composition's
  grid-line offset comes from (§6.4): moving right → subject on the LEFT
  grid line → air ahead on the right.
- **180° rule** — keep the camera on one side of the action axis between two
  subjects/motion so left/right screen direction stays consistent across
  cuts.
- **Cut-on-action** — cut while a subject is mid-motion (not before/after)
  so the cut reads as continuous rather than a jump.
- **Match cut** — cut between two shots that share a shape, motion, or
  composition, carrying visual continuity across the cut.
- **J-cut / L-cut** — audio leads (J) or lags (L) the picture across a cut;
  used for soft/atmospheric joins and continuity of sound across a scene
  change.
- **Continuity** — consistent direction, position, and pace of action across
  cuts; a viewer shouldn't be jarred by a subject "teleporting" or reversing
  direction without motivation.
- **Contrast** — vary shot scale/pace/energy between adjacent episodes so
  the edit doesn't flatten out (also underlies the §9 "variety" check —
  perceptual-hash distance between adjacent episodes).

**Blend with trend:** canon is the default; `TRENDS.md`'s composition
section (center punch-ins, jump cuts, extreme crops, whip transitions, hook
patterns) nudges it per `SPEC.style-lean` (classic↔trend, e.g. 70/30). The
editorial check judges both — all-canon reads dated, all-trend reads
gimmicky.

## Composition-grid library

Three tools of increasing complexity, split by role — a line for motion, an
armature for static.

| Grid | What | Where it's used |
|------|------|-----------------|
| `thirds` | 2+2 lines at 0.333/0.667 | **line-target for continuous tracking** (default) |
| `phi` | 2+2 lines at 0.382/0.618 (golden ratio) | tracking line-target, per-episode option |
| `golden-canon-grid` | dynamic-symmetry armature: root rectangle + 2 diagonals (baroque/sinister) + 4 reciprocals (⊥ to the diagonals) + horizontals/verticals through the intersection "eyes" + phi divisions | **static/editorial layer**, not a line-target |

**Why thirds is the tracking default:** proven in the source session; matches
platform safe-zones; phi sits ~5% closer to center → less air at the leading
edge, and the direction rule specifically wants air ahead. phi is available
explicitly per episode.

**Golden Canon Grid is not a per-frame tracking target** — the armature is
aspect-locked and static; you can't smoothly pan a moving subject onto a
baroque diagonal frame-by-frame. Three static uses instead:

1. **Hero/static/`center`/`break` frames** — frame to honor the armature:
   subject on an "eye", horizon/wave lines along the reciprocals, motion
   along a diagonal.
2. **Editorial overlay** — `storyboard.py` draws the full armature
   (diagonals + reciprocals + eyes + phi); the editorial check judges the
   strongest frames against it.
3. **Selection scoring** — intake/edit-plan bonus for moments whose natural
   composition already lands on an armature diagonal.

The storyboard overlay for motion verification draws thirds + phi lines
(horizontals at each grid's own fractions — phi's at 0.382/0.618, not 1/3);
for hero/static frames, plus the full armature. The armature overlay ships
with the process-episode plan; the core engine draws the line grids only.
`check_episode` verifies against the episode's **chosen** `grid` — canon is
a default, not a global law (§6.2).
