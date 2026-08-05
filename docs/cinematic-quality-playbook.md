# Cinematic Quality Playbook — video-grid

**Working document.** How to push the montage from "competent but generic" toward
**professional / CapCut-level** output. It fuses three inputs: the 2026-08-03 real-run
session review, the itemized [fixes-backlog.md](fixes-backlog.md) (#1–#20), and
researched editing craft. This is the doc we work from; the backlog stays as the
detailed itemized source, this is the synthesis + the "why".

---

## 0. Where we are — the core gap

The first real run (surf footage → 9:16 reel) proved the **engine core is genuinely
strong**: intake was rock-solid (99/99 clips, 0 failures on 4K), reframe/composition
places the subject on a third with lead-room/headroom in nearly every frame,
match-grade converged a two-camera cut to one tone, and scenario-first pacing landed
cuts exactly on the half-bar. That is a real foundation.

Yet the reel came out **competent but generic** — one shot type repeated (medium-wide
side-on surfer), no faces/close-ups/personality, invisible effects, a music out-point
cut mid-phrase. And the agent driving it **cut corners** (bypassed a gate once, patched
the engine live ~40×, guessed at footage instead of looking).

**Conclusion:** the leap to cinematic is mostly **editorial intelligence + shot variety
+ mood coherence + trustworthy process**, not raw engine capability. The machine can
already cut, track, grade and pace; it does not yet *direct*.

---

## 1. What "cinematic" is made of (craft principles + why)

### 1.1 Shot variety & coverage grammar
The grammar of an edited sequence: **establishing/wide (master) → medium → close-up →
detail/insert → cutaway/reaction.** Shot *size* sets the emotional distance between
viewer and subject; a mix of sizes is the baseline difference between "edited" and
"raw." Pros open wide to establish geography, cut tighter for emotion, and punctuate
with details/cutaways. A montage that stays one size reads amateur — which is exactly
what our run did.
→ Backlog #19. Intake already tags `shot_type` (close/medium/wide) per window, but
variety is **not a selection objective** — edit-plan fills length, not a shot-size mix.

### 1.2 Rhythm & pacing
Shot length sets tempo; the **average shot length (ASL)** sets the viewer's
expectation. Short shots build tension/energy; long shots read calm/contemplative.
Cut **on emotion or action** (a reaction, an impact, a turn), not on an arbitrary
grid. Music is the rhythmic spine a montage is built on.
→ We already do the mechanical half well (beat-fit on the half-bar). The missing half:
**vary shot length by energy** (longer in the build, rapid at the drop), cut on the
action peak, and set ASL from the mood.

### 1.3 Mood → recipe (the unifying idea)
A mood is **not one knob** — it is a coherent recipe across colour + pace + shot
selection + music + effects. General rules from the craft: **contrast → tension,
saturation → energy, temperature → psychology (warm = comfort, cool = unease), tint →
era.** A starter matrix:

| Mood | Colour grade | Contrast / Sat / Temp | Pace / ASL | Shot emphasis | Effects | Music |
|------|--------------|-----------------------|-----------|---------------|---------|-------|
| **Fun / playful** | Vivid Pop / Warm Golden | mid contrast, high sat, warm | fast, short ASL, on-beat | faces, close-ups, reactions, motion | quick zoom/whip, light | upbeat, bright |
| **Epic / adventure** | Teal & Orange | high contrast, warm skin vs cool world | build slow→fast | wide establish + hero CU | slow-mo at peak, push-in | driving, big drop |
| **Moody / dramatic** | Dark & Moody / Bleach Bypass | crushed shadows, desat, cool | slow, long ASL | silhouettes, tight, negative space | slow push-in, minimal | ominous / industrial |
| **Nostalgic** | Vintage Film / Creamy Haze | low contrast, faded, warm, grain | medium, gentle | details, hands, light | grain, soft fade | melodic, warm |

→ Today mood exists only as a **music-search string** + a match-grade tone target. It
does **not** drive colour palette, pace, shot-mix, or effects. The `fun/playful` brief
produced a dark industrial reel — user-chosen in this case, but the **system had no
mood-coherence guardrail** to even notice the contradiction. Ties #9 (palettes) + #19
(variety) + pacing + #3 (QC needs a mood to judge against).

### 1.4 Cinematic move techniques
- **Speed-ramp into a beat; slow-mo at the musical peak** — the signature "hit the
  drop in slow-mo" move (we have `ramp`, #7).
- **Hero-anchored camera moves** (push-in / zoom, pan) that keep the subject composed
  by the rules — **not** route-less crop animations (#17).
- **Effects serve the subject and composition, stay inside QC, and must be visible**
  (#17, #18 — our vignette came out invisible).

---

## 2. Gap map — the backlog, grouped by theme, with the "why"

Each cluster below is "what to fix" and why it matters against §1.

**A. Identity (highest leverage).**
- **#1 — hero re-ID embedding** (design approved). The colour-histogram descriptor
  cannot tell surfers apart; the whole cast→hero-pin machinery went **unused** in the
  run (`pin=None` everywhere, `hero:largest`). Without reliable identity the reel
  cannot feature *this person* — the entire "personality-forward" axis is dead.

**B. Editorial intelligence (turns "raw" into "directed").**
- **#19 shot variety + brief-fidelity** — select a shot-size mix, judge the cut against
  the brief's mood.
- **#3 per-episode QC subagent** — composition rules, colour naturalness, overall
  impression, hero-path smoothness.
- **#12 look-don't-guess** — extract and actually view frames before deciding (hero,
  slow-mo peak); the run's biggest recurring error.
- **#14 editorial-rule memory** — honour user rules (bookend heroes, no repeated
  passes) across every re-cut.
- **#2 music phrase-aware out-point** — end on a phrase, not a mid-phrase chop.

**C. Mood coherence (the big idea — see §3).**
- **#9 mood palettes + cinematic effects library**, bound into a mood preset.

**D. Cinematic effects vocabulary (done right).**
- **#7 speed ramp** (first-class, length-aware), **zoom in/out**, **#9
  vignette/grain/fade/LUTs**, all **#17 subject-anchored & inside QC**, **#18 built via
  TDD with an "is it visible on the frame" check.**

**E. Governance / trustworthy process (so runs are believable).**
- **#8 gates the worker cannot disable**, **#11 freeze the engine during a run**
  (no live `scripts/` edits), **#13 no manual-concat bypass of the reel gate**,
  **#20 no off-pipeline raw-EDL edits**, **#15 CP3 reel-review enforced**,
  **#6 proactively ask about titles/effects.**

**F. Iteration cost & bookkeeping.**
- **#10 cheap 3-frame preview** to converge colour/effects before a full re-encode
  (the run did ~29 full re-encodes), **#16 VERSIONS.md note bug**, and the
  version-management anomaly (rm-rf of `out/` nukes history, leaving one stray
  version).

**G. Setup.**
- **#4 install everything, no optional flags** (warn-and-continue on the unavailable).

---

## 3. The unifying design: **mood presets**

The single idea that ties the editorial half together: make a **mood preset** a
first-class config object. A mood resolves to a coherent bundle:

```
mood → {
  shot_mix:   target distribution of shot sizes + an ASL band,
  colour:     grade/palette (maps to our white_balance/black/contrast/tone knobs or a LUT),
  effects:    the effect set + intensity (ramp, zoom, grain, vignette…),
  music:      energy/brightness/pace target (already have this via mood.py),
  pace:       the energy curve shape (build/drop) for the spine,
}
```

Everything downstream reads it: music search (already), edit-plan **selection**
(variety + shot-mix targets — new), pacing (energy curve), colour/match-grade (palette
bias, not just source median), effects, and — crucially — **the per-episode and reel
QC judge the result against the preset** (#3). This is what makes "build reels for
different moods" real and *coherent* instead of a music string plus an unrelated grade,
and it gives the QC something concrete to check "does this feel `fun/playful`?" against.

Starter preset set (v1 candidates): `fun/playful`, `epic/adventure`, `moody/dramatic`,
`nostalgic` — per the §1.3 matrix. Number and exact parameters to decide together.

---

## 4. Proposed priority order (to detail together)

1. **#1 hero re-ID — ✅ LANDED 2026-08-04** (`docs/plans/2026-08-04-hero-reid.md`)
   — unblocks identity/personality; revives the hero-pin slice.
2. **Governance hardening — ✅ LANDED 2026-08-04**
   (`docs/plans/2026-08-04-attested-run.md`) — #8/#11/#13/#15/#20/#6 (+ rider
   #16) landed behind a provenance chain (`scripts/lib/provenance.py`) that
   refuses a tampered EDL or an unbound reel report and stamps every delivery
   with an attestation; the dirty-tree question is resolved (the live tree is
   clean, one parked branch deleted). #7/#18's speed-ramp/effects work stays
   open — its only copy still lives on the parked `wip/montage-run-patches`
   branch — and priority 3 below is otherwise unblocked.
3. **Editorial intelligence** — #12 look-don't-guess, the **selection** half,
   **✅ LANDED 2026-08-05** (design
   `docs/specs/2026-08-05-footage-contact-sheet-design.md` + plan
   `docs/plans/2026-08-05-footage-contact-sheet.md`): `contact_sheet`'s
   `build`/`strip` give the edit-plan agent its first look at actual pixels,
   wired as a **required** conveyor stage between footage-intake and
   edit-plan — it gates the sensor's presence, never proof that anyone
   looked (design §9). Open: #19 shot variety + #3 per-episode QC (the
   per-episode half of #12) + #14 editorial-rule memory, on top of the
   **mood-preset spine (§3)**.
4. **Cinematic effects done right** — #7/#9/#17/#18, with #10 cheap-preview to keep
   iteration affordable.
5. **Polish** — #2 music phrase-out, #16 versioning, #4 setup.

Rationale: identity and trust are foundational; editorial intelligence + mood presets
are where the "generic → cinematic" jump actually happens; effects are the visible
finish; polish last.

---

## 5. Open questions for the detailed session

- **Mood presets:** how many named moods in v1, and how rigid vs. agent-tunable are
  their parameters?
- **reID model:** OSNet primary (chosen) — confirm install path on arm64, CLIP as the
  documented fallback behind `lib/reid.py`.
- **Editorial judgement split:** how much stays with the agent's taste vs. encoded
  rules/QC (the run showed unguided taste drifts and guesses).
- ~~**Dirty tree:**~~ resolved 2026-08-04 — the live tree is clean;
  `wip/montage-run-hardening` was fully ported and deleted, and
  `wip/montage-run-patches` stays parked (deliberately, not deferred) as the
  only copy of the still-open #7/#18 speed-ramp/effects work.
- **Effect QC:** what "visible on the frame" and "composition-respecting" checks look
  like concretely (the 3-frame probe, #10, extended beyond colour).

---

## Sources (craft research, 2026-08-03)

- StudioBinder — [camera shot types](https://www.studiobinder.com/blog/ultimate-guide-to-camera-shots/) · [how editors control rhythm & pacing](https://www.studiobinder.com/blog/how-does-an-editor-control-the-rhythm-of-a-film/)
- Morphic — [coverage in filmmaking](https://morphic.com/ai-glossary/Coverage)
- LWKS — [rhythm & pace](https://lwks.com/blog/rhythm-and-pace-crafting-the-tempo-of-film)
- Skillman — [rhythmic editing & viewer emotion](https://www.skillmanvideogroup.com/rhythmic-editing/)
- VideoLens — [14 cinematic colour grades by mood](https://videolens.cc/en/blog/cinematic-color-grading-guide)
- Pixflow — [teal & orange grading](https://pixflow.net/blog/teal-and-orange-color-grading/) · [cinematic b-roll techniques](https://pixflow.net/blog/what-is-cinematic-b-roll-premiere-pro-techniques-for-stunning-video-sequences/)
- Beat2Cut — [beat-sync editing guide](https://beat2cut.com/blog/beat-sync-video-editing-complete-guide/)
- Kapwing — [speed-ramp effect](https://www.kapwing.com/resources/how-to-use-the-speed-ramp-effect/)
