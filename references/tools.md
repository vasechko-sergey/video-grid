# Tool index

**Generated — do not edit.** Regenerate with:

    python -m scripts.montage tools > references/tools.md

One row per `--help` surface. It answers *which tool*; `--help` answers
*how do I run it*, and this file deliberately lists no arguments.

| surface | stage | writes | purpose |
|---|---|---|---|
| `assemble` | — | — | Concat locked episodes into a reel master |
| `beats` | `music-and-mood` | `MUSIC.json` | analyse a track → MUSIC.json (tempo + beats + energy) |
| `build_reel` | — | — | drive the reel retry loop → delivered reel \| stop-and-report |
| `check_episode` | — | — | judge one rendered episode mechanically — composition, path quality, black frames, grade damage → report.json |
| `check_reel` | — | — | Whole-reel mechanical check |
| `color_measure` | — | — | measure a clip's (p5,p50,p95) luma for ReframeSpec.tone |
| `contact_sheet` | `contact-sheet` | `SHEETS.md` | footage contact sheets (stage 5.2b): look before you cut |
| `contact_sheet build` | `contact-sheet` | `SHEETS.md` | one frame per FOOTAGE.json window, tiled into sheets in timeline order → the sheets plus SHEETS.md |
| `contact_sheet strip` | `contact-sheet` | `SHEETS.md` | many frames from inside ONE window — or any file and time range — tiled into a single image |
| `deliver` | — | — | Deliver a checked reel master |
| `draft` | `assemble-draft` | `draft.mp4` | render a QA-preview draft.mp4 (montage §5.9) |
| `draft build` | `assemble-draft` | `draft.mp4` | concat the EDL's raw segments into draft.mp4 with processing-note labels and a rough music bed |
| `edit_plan` | `edit-plan` | `EDL.json` | author EDL.json + EDL.md from FOOTAGE + a selection (stage 5.7) |
| `edit_plan build` | `edit-plan` | `EDL.json` | project a selection.json over FOOTAGE.json's windows into EDL.json + EDL.md — the cut |
| `edl_to_reel` | `episodes-geometry`, `episodes`, `deliver` | `GEOMETRY.json`, `EPISODES.json`, `REEL_v*.*` | drive a hand-authored EDL.json → delivered REEL_v1.mp4 |
| `episode_qc` | `episode-qc` | `EPISODE_QC.json` | per-episode QC: pack the evidence, then validate the judges' findings |
| `episode_qc pack` | `episode-qc` | `EPISODE_QC.json` | write one evidence directory per episode — a frame strip of the delivered clip, its storyboard, its mechanical report, a colour reading, and the clip's own digest |
| `episode_qc build` | `episode-qc` | `EPISODE_QC.json` | validate every judge's findings.json into EPISODE_QC.json + .md, stamping each verdict with the clip digest read from disk |
| `extract` | — | — | cut one EDL window out of a source clip into a standalone segment, normalized to tv range — the pipeline's canonical form |
| `intake` | `footage-intake` | `FOOTAGE.json` | footage-intake (5.2): scan clips → FOOTAGE.json/.md |
| `match_grade` | `match-grade` | `MATCH.json` | match-grade conductor — author tone_src/tone_dst across an EDL (§10) |
| `match_grade build` | `match-grade` | `MATCH.json` | measure every episode's tracked crop, compute one common reel tone target, and author tone_src/tone_dst on the episodes that deviate past --eps → a rewritten EDL.json plus MATCH.json and MATCH.md |
| `mix` | — | — | build the reel audio stem from MUSIC.json |
| `montage` | — | — | montage router status inspector (stage 5.1) |
| `montage status` | — | — | report which conveyor stage is next in a run directory, and how far the artifacts on disk already reach |
| `montage verify` | — | — | re-hash every delivered reel against its attestation and report any that no longer match |
| `montage tools` | — | — | print the generated tool index — one row per --help surface, naming which tool does what and which conveyor stage it belongs to |
| `montage stages` | — | — | print the generated stage table the using-montage SKILL carries between its two generated: stages markers — one row per live conveyor stage, naming its step number, whether it is required, which of the three user checkpoints it sits at, the artifact whose presence marks it done, and the reference page carrying its detail |
| `mood` | — | — | rank a folder of tracks by mood-fit → MUSIC_SHORTLIST.{json,md} |
| `music_fetch` | — | — | download a sourced track → cache + sidecar |
| `music_find` | — | — | source candidate tracks by mood → MUSIC_SHORTLIST.{json,md} |
| `pacing` | `pacing` | `PACING.md` | fit the EDL's cuts onto a musical grid -> PACING.{json,md} |
| `probe` | — | — | cheap frame probes: converge a grade, or re-check a delivered look |
| `probe grade` | — | — | render and measure N frames of one episode over its frozen route, through the same chain the real encode uses → probe.jpg + probe.json |
| `probe look` | — | — | re-check a delivered reel against its master for a declared vignette, bookend fade and title ink — the same gate deliver runs after its encode, runnable by hand |
| `process_episode` | — | — | process one episode manifest → checked clip |
| `project_init` | `project-init` | `project.json` | write project.json (purpose→aspect/delivery) |
| `reel_brief` | `reel-brief` | `SPEC.json` | write SPEC.json + SPEC.md — the reel brief (stage 5.3) |
| `reel_brief build` | `reel-brief` | `SPEC.json` | write SPEC.json + SPEC.md from the brief's fields — mood, hook, length, music intent, cast |
| `reel_review` | `reel-review` | `REVIEW.json` | write REVIEW.json + REVIEW.md — the editorial reel review (§5.13 Slice B) |
| `reel_review build` | `reel-review` | `REVIEW.json` | validate the reviewer subagent's raw findings into REVIEW.json + REVIEW.md, stamping the reel's own digest read from disk |
| `reframe` | — | — | compose one episode — crop a segment over its route into the delivery canvas, applying layout, colour and any generated pan → the episode clip plus a path.meta.json sidecar |
| `storyboard` | — | — | render a grid-overlaid contact sheet of one clip for editorial verification → one .jpg |
| `titles` | `titles` | `TITLES.json` | write TITLES.json + TITLES.md — the reel titles (§5.16) |
| `titles build` | `titles` | `TITLES.json` | draft TITLES.json + TITLES.md from SPEC and the reel's length — hook, mid text and ending, positioned inside the platform's safe zone |
| `titles check` | `titles` | `TITLES.json` | refuse a TITLES.json whose rendered ink leaves the platform's safe zone |
| `track` | — | — | track the episode's subject through a segment → route.json, the per-frame subject box every later stage composes against |
| `verify_runtime` | — | — | verify the video-grid runtime is installed (design 2026-08-01) |
