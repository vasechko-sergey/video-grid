"""Edit-plan authoring (design docs/specs/2026-07-12-edit-plan-spine-design.md, stage 5.7).

The 5.7 driver: an agent-authored selection.json (window references + editorial
fields) → a typed EDL.json + a human EDL.md map, which the existing edl_to_reel
(SP1) takes to a delivered reel. Selection lives in the agent's judgment; this
module is the thin mechanical half — projection + preflight + render. Contract
vs. logic split mirrors footage.py (contract) ↔ intake.py (logic).

The mechanical window fields (source/start/dur/shot_type/description) reach the
EDL BY REFERENCE through window_to_episode — never retyped by the agent, because
a retyped start/dur is the silent-wrong-cut class (montage §12). selection.json
carries only integer window indices + editorial enums/notes.
"""
import argparse
import dataclasses
import json
import sys
from pathlib import Path

from scripts.lib import gridfit, moodpreset, outro, ramp as ramp_mod, safezones
from scripts.lib.constraints import Constraints, Placed, evaluate as check_constraints
from scripts.lib.edl import EDL, EDLEpisode, preflight, write_edl
from scripts.lib.footage import Footage, FootageClip, FootageWindow, SHOT_TYPES, delivered_shot
from scripts.lib.look import LookSpec
from scripts.lib.models import HERO_RULES, MusicSpec, RampSpec
from scripts.lib.moodpreset import MoodPreset
from scripts.lib.pacing import Spine
from scripts.lib.project import ProjectConfig
from scripts.lib.spec import Spec


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


PAN_PRESENCE_MAX = 0.10   # fraction of a window's samples holding >= 1 person. Above this a
                          # `pan` is refused: a pan DECLARES the shot has no subject, and that
                          # declaration turns off three of check_episode's checks (design
                          # 2026-08-08 §2). FIRST CUT, uncalibrated — it encodes a judgement
                          # about what "incidental" means, not a measurement.

_BACK_EDGE_TOL = 1e-6      # a realized total within this of the spine target "fills the spine"

_MIX_DEFAULT_FADE = 0.5    # mix._FADE — the bookend a reel gets when no look is authored.
                           # Duplicated rather than imported: edit_plan must not import a
                           # driver, and this slice does not touch mix.py at all (§1).


def window_to_episode(clip: FootageClip, window: FootageWindow, start_offset: float = 0.0,
                      **editorial: object) -> EDLEpisode:
    """Project a scored FootageWindow onto an EDLEpisode. Mechanical fields come
    from the clip/window by reference; editorial fields (composition/grid required;
    layout/motion/hero/crop_*/rect/background*/border_*/color_means/beat_slot/
    white_balance/black_point/highlight/saturation/shadow_red/mid_blue/dip/tone_*
    optional) are forwarded to EDLEpisode, whose __post_init__ is the single
    value-validation site. shot_type/processing_notes default to the window's
    shot_type/description but an editorial value overrides. An unknown or missing
    editorial field raises ValueError naming it.

    `start_offset` moves the in-point later inside the SAME shot — the fine-tune atop
    intake's activity units (2026-07-25 activity-units): a unit is anchored on an
    activity peak with its lead-in, but the exact frame to cut on can still sit a beat
    inside it, and an offset reaches it without re-carving. It shifts the in-point
    ONLY; `dur` still comes from the window
    (and then from the spine), so an offset can never silently lengthen an episode.
    Crossing a scene cut is refused: the in-point would land in a different shot than
    the one the window scored, so its shot_type/description would describe other footage.

    A `pan` is refused over a window intake measured as holding people
    (PAN_PRESENCE_MAX) — this is the one site that sees both the requested
    editorial fields and the measured window, which is why the gate lives here
    and not in EDLEpisode or the manifest (design 2026-08-08 §2.1).

    A `ramp` is gated here too, against `clip.fps` — the early half of the judder
    gate (design 2026-08-09 §5): FOOTAGE already knows this clip's frame rate, so a
    ramp that would stutter is refused before the pipeline spends anything on it.
    The extract pre-stage repeats the check against the PROBED rate, which is what
    a hand-authored EDL meets instead of this one.
    """
    if isinstance(start_offset, bool) or not isinstance(start_offset, (int, float)):
        raise ValueError(f"window_to_episode: start_offset must be a number of seconds, "
                         f"got {start_offset!r}")
    if start_offset < 0:
        raise ValueError(f"window_to_episode: start_offset must be >= 0 seconds, got "
                         f"{start_offset!r} — to start EARLIER, reference an earlier window")
    start = window.start + start_offset
    if start >= clip.dur:
        raise ValueError(
            f"window_to_episode: start_offset {start_offset}s puts the in-point at {start:.2f}s, "
            f"past the end of {clip.source} ({clip.dur:.2f}s)")
    crossed = [c for c in clip.scene_cuts if window.start < c <= start]
    if crossed:
        raise ValueError(
            f"window_to_episode: start_offset {start_offset}s crosses a scene cut at "
            f"{crossed[0]:.2f}s in {clip.source} — the in-point would land in a DIFFERENT shot "
            f"than the window scored. Reference the window that starts after the cut instead")
    room = clip.room_after(start)
    if window.dur > room:
        raise ValueError(
            f"window_to_episode: start_offset {start_offset}s puts the out-point at "
            f"{start + window.dur:.2f}s, past the {room:.2f}s of room the shot has after "
            f"{start:.2f}s in {clip.source} — the episode would cross a scene cut or run "
            f"past the clip. Pick an earlier in-point (a smaller start_offset) or a "
            f"shorter window")
    if editorial.get("pan") is not None and window.present > PAN_PRESENCE_MAX:
        raise ValueError(
            f"window_to_episode: this window holds people in {window.present:.0%} of its "
            f"samples, above the {PAN_PRESENCE_MAX:.0%} a `pan` may be authored over — a pan "
            "declares the shot has no subject to follow, and on that declaration "
            "check_episode reports framing editorial-only, continuity not-checked and "
            "colour-fidelity not-checked. Drop the `pan` and let the tracked route place the "
            "crop, or reference a window intake measured as empty")
    if editorial.get("ramp") is not None:
        # The early half of the judder gate (design §5): FOOTAGE already knows this
        # clip's frame rate, so a ramp that would stutter is refused before the
        # pipeline spends anything. The extract pre-stage repeats the check against
        # the PROBED rate, which is what a hand-authored EDL meets instead.
        ramp_mod.require_playable(RampSpec.from_dict(editorial["ramp"]), clip.fps,
                                  f"{clip.source} window at {start:.2f}s")
    defaults = {"shot_type": window.shot_type, "processing_notes": window.description}
    try:
        return EDLEpisode(source=clip.source, start=start, dur=window.dur,
                          **{**defaults, **editorial})
    except TypeError as ex:
        raise ValueError(f"window_to_episode: unknown or missing editorial field — {ex}") from ex


_MERGE_TOL = 1e-3   # s: FOOTAGE stores round(start, 3) and round(dur, 3) independently, so a
                    # merged envelope end can sit up to ~1ms past its true cut/clip-end boundary;
                    # tolerate (and clamp) that slop so a span ending on a cut or the clip end is
                    # not falsely refused as a straddle.


def _merge_windows(clip: FootageClip, i: int, j: int) -> FootageWindow:
    """Merge adjacent footage windows i..j (inclusive) into one FootageWindow covering
    [min start .. max end] — an episode spanning several activity units plus the connective
    footage between them (design 2026-07-26-edit-plan-span-merge §3, "turn -> drive -> turn").

    The merged window inherits window i's shot_type/description as the projection seed (an
    editorial override still wins in window_to_episode), unions the track_ids across the
    range, and MAX-aggregates `present` across the range too (design 2026-08-08 §2.3) — the
    busiest window's presence, not window i's, so a span that opens empty and fills with
    people cannot slip window_to_episode's pan gate on the strength of its own opening window.
    It refuses a range whose envelope straddles a scene cut — that would splice two
    shots into one episode; `room_after` is the single geometric authority (the same rule
    window_to_episode applies), naming the offending cut for a span-specific remedy. Crossing
    a presence transition inside one shot is allowed (scene_cuts holds only real cuts, and
    room_after stops only at cuts). An envelope end within _MERGE_TOL of a cut/clip-end
    boundary is a rounding artefact (FOOTAGE rounds start and dur independently), so it is
    clamped to the boundary rather than refused; beyond the tolerance with no cut inside, the
    last window lies past the clip and the merge fails loud. Assumes a valid
    0 <= i < j < len(clip.windows); build_edl bounds-checks."""
    wins = clip.windows[i:j + 1]
    start = min(w.start for w in wins)
    end = max(w.start + w.dur for w in wins)
    tids = sorted({t for w in wins for t in w.track_ids})
    # the busiest sample in the span, not window i's: a span that starts empty and fills
    # with people would otherwise report the empty window's presence and slip the pan gate
    # past a shot full of subjects (design 2026-08-08 §2.3)
    present = max(w.present for w in wins)
    room = clip.room_after(start)
    if end - start > room + _MERGE_TOL:
        inside = [c for c in clip.scene_cuts if start < c < end]
        if inside:
            raise ValueError(
                f"_merge_windows: span [{i}, {j}] runs {end - start:.2f}s from {start:.2f}s in "
                f"{clip.source}, but a scene cut at {min(inside):.2f}s lies inside it — a span cannot "
                f"cross a scene cut (it would splice two shots into one episode). Split it into two "
                f"episodes, one on each side of the cut")
        raise ValueError(
            f"_merge_windows: span [{i}, {j}] envelope ends at {end:.2f}s, past the end of "
            f"{clip.source} ({clip.dur:.2f}s) — the last window extends beyond the clip; re-run "
            f"footage-intake to regenerate FOOTAGE.json")
    return dataclasses.replace(clip.windows[i], start=start,
                               dur=min(end - start, room), track_ids=tids, present=present)


def _resolve_window(clip: FootageClip, window: object, source: str, k: int) -> FootageWindow:
    """Resolve a selection episode's `window` ref to one FootageWindow. An int is a single
    window (the 5.7 behaviour); a two-element [i, j] list is a span merged into one episode
    (§3b). Fail-loud on a bad shape, a bad type, or an out-of-range index — naming episode k."""
    if isinstance(window, list):
        if len(window) != 2 or any(isinstance(v, bool) or not isinstance(v, int) for v in window):
            raise ValueError(f"selection episode {k}: a span 'window' must be [i, j] — two "
                             f"integer indices, got {window!r}")
        i, j = window
        if not 0 <= i < j < len(clip.windows):
            raise ValueError(f"selection episode {k}: span window {window} out of range for "
                             f"{source} (need 0 <= i < j < {len(clip.windows)}; for a single "
                             f'window use "window": i)')
        return _merge_windows(clip, i, j)
    if isinstance(window, bool) or not isinstance(window, int):
        raise ValueError(f"selection episode {k}: 'window' must be an integer index or a "
                         f"[i, j] span into FOOTAGE")
    if not 0 <= window < len(clip.windows):
        raise ValueError(f"selection episode {k}: window {window} out of range for {source} "
                         f"(has {len(clip.windows)})")
    return clip.windows[window]


_SNAP_TOL = 1e-3      # s of float slack when comparing a slot against its episode


def _bind_pacing(episodes: list, spine: Spine) -> list:
    """Apply a FITTED spine: episode i's `play_dur()` — the PLAYED length, literally
    true only of `play_dur()` once an episode may carry a ramp — takes slot i's
    duration, and the episode gets `beat_slot=i`.

    The spine was fitted TO these episodes (scripts/pacing.py reads the same EDL), so a
    slot may differ from its episode only by the snap the fit was allowed — half a beat.
    A larger difference means this spine was fitted to a DIFFERENT edit, and copying its
    length across would truncate a shot exactly the way the generator used to: a 7.3s
    ride into a 4.6s slot, in silence. Refuse instead.

    Zip-to-min; an over/underflow is logged, never a silent drop (§4.1)."""
    allow = gridfit.allowance(spine.tempo) + _SNAP_TOL
    n = min(len(episodes), len(spine.slots))
    bound = []
    for i in range(n):
        slot, ep = spine.slots[i], episodes[i]
        # PLAYED time on both sides: the spine was fitted to play_dur (pacing.py),
        # so comparing the source window would refuse a correct fit on any ramped
        # episode by exactly the ramp's added time.
        played = ep.play_dur()
        if abs(slot.dur - played) > allow:
            raise ValueError(
                f"pacing: slot {i} is {slot.dur:.2f}s against a {played:.2f}s episode — "
                f"further apart than the {allow:.2f}s snap allows, so this PACING.json "
                f"was fitted to a different edit. Re-run pacing against the current "
                f"EDL.json before binding")
        # Assign the SOURCE window that plays for slot.dur. ramp_extra is constant
        # in dur while the region stays enclosed (design §2), so this is exact
        # rather than a solve — and dataclasses.replace re-runs __post_init__, so a
        # shrink that ate into the region raises instead of passing quietly.
        extra = played - ep.dur
        bound.append(dataclasses.replace(ep, beat_slot=i, dur=slot.dur - extra))
    if len(episodes) > len(spine.slots):
        _log(f"pacing: {len(episodes)} episodes exceed the {len(spine.slots)}-slot spine "
             f"— the {len(episodes) - len(spine.slots)} tail episode(s) keep beat_slot=None; "
             f"re-run pacing against the current EDL.json")
        bound.extend(episodes[n:])
    elif len(spine.slots) > len(episodes):
        _log(f"pacing: {len(spine.slots)} slots exceed the {len(episodes)} episodes — the "
             f"{len(spine.slots) - len(episodes)} tail slot(s) are unfilled")
    return bound


def _back_edge_target(episodes: list, spine: Spine) -> float:
    """The reel's target length: the realized footage, clamped to the fitted spine. This
    is now the ORDINARY way a target is computed (design 2026-07-24 §1) rather than a
    rescue for an under-fill — the music is cut to the reel, not the reel to the music.
    An under-fill re-times the target DOWN to what the footage actually
    delivers — the montage §4.1 pacing-gate back-edge — so the reel's length gate passes by
    construction instead of escalating a whole pipeline later. An over-flow keeps the
    fragment length, so the excess escalates at the reel gate rather than reaching mix,
    which refuses a stem longer than its fragment (§2). `realized` sums EVERY bound episode's
    PLAYED length, including an over-flow tail left at beat_slot=None — the reel is as long as
    everything in it. Both directions log; neither is silent."""
    realized = sum(e.play_dur() for e in episodes)
    if realized < spine.target_dur - _BACK_EDGE_TOL:
        _log(f"pacing back-edge: the bound footage realizes {realized:.2f}s of the "
             f"{spine.target_dur:.2f}s spine — re-timing the reel target to {realized:.2f}s; "
             f"for a tighter cut re-pick a shorter fragment "
             f"(beats --auto-start --duration {realized:.0f}) and re-derive the spine")
    elif realized > spine.target_dur + _BACK_EDGE_TOL:
        _log(f"pacing back-edge: the bound footage realizes {realized:.2f}s against a "
             f"{spine.target_dur:.2f}s spine — the target stays at the fragment length; the "
             f"excess {realized - spine.target_dur:.2f}s escalates at the reel gate "
             f"(extend the fragment or drop episodes — music cannot be invented)")
    return min(realized, spine.target_dur)


def _apply_outro(episodes: list, footage, music, fade: float,
                 brief_len: float | None) -> tuple[list, "outro.OutroFit"]:
    """Move the LAST episode's end so the music resolves on a bar line (design §6).

    The reel's length is the one number this whole slice decides: `line + fade`, which
    starts mix's existing bookend exactly on the line. Only the closing episode moves —
    every cut before it keeps the beat it was fitted to, so check_reel's beat gate stays
    green by construction.

    Applied AFTER _bind_pacing and never through a slot. That guard refuses a slot more
    than half a beat from its episode and exists to catch a spine fitted to a DIFFERENT
    edit; an outro extension is typically two beats and would trip it (§6).

    A ramped closing episode is skipped: `play_dur()` is a non-linear function of `dur`
    once a ramp is present, so growing it would need the ramp arithmetic. Skipped and
    logged, never guessed."""
    if not episodes or not music.bars:
        return episodes, outro.OutroFit(reel_dur=sum(e.play_dur() for e in episodes),
                                        line=None, fade=fade, tail=0.0,
                                        rung="unchanged", moved=0.0)
    last = episodes[-1]
    realized = sum(e.play_dur() for e in episodes)
    unchanged = outro.OutroFit(reel_dur=realized, line=None, fade=fade, tail=0.0,
                               rung="unchanged", moved=0.0)
    if last.ramp is not None:
        _log(f"outro: the closing episode carries a ramp — its played length is not its "
             f"source length, so the outro fit is skipped and the reel stays "
             f"{realized:.2f}s. Move the ramp off the last episode to fit the ending.")
        return episodes, unchanged
    clip = next((c for c in footage.clips if c.source == last.source), None)
    if clip is None:
        _log(f"outro: {last.source!r} is not in FOOTAGE — cannot measure the closing "
             f"shot's room, so the reel stays {realized:.2f}s")
        return episodes, unchanged
    grow_max = max(0.0, clip.room_after(last.start) - last.dur)
    shrink_max = max(0.0, last.play_dur() - outro.MIN_LAST)
    fit = outro.fit_outro(music.bars, music.vocal_spans, realized,
                          outro.bar_seconds(music.tempo), fade,
                          music_dur=music.duration, grow_max=grow_max,
                          shrink_max=shrink_max, brief_len=brief_len)
    if fit.rung == "unchanged":
        _log(f"outro: no bar line within one bar of {realized:.2f}s that the closing shot "
             f"can reach (grow {grow_max:.2f}s / shrink {shrink_max:.2f}s) — the reel "
             f"keeps its footage-derived length and the music will end mid-phrase")
        return episodes, fit
    out = list(episodes)
    out[-1] = dataclasses.replace(last, dur=last.dur + fit.moved)
    brief = "" if brief_len is None else f", {fit.reel_dur - brief_len:+.2f}s vs the brief's {brief_len:.1f}s"
    _log(f"outro: rung {fit.rung} — the music resolves on the bar line at {fit.line:.2f}s "
         f"with {fit.tail:.2f}s of vocal-free space after it; the reel moves "
         f"{fit.moved:+.2f}s to {fit.reel_dur:.2f}s (fade {fit.fade:.2f}s){brief}")
    return out, fit


def _available_census(footage: Footage, aspect: tuple[int, int]) -> dict[str, int]:
    """Every window the footage offers, bucketed in DELIVERED geometry (design §6).

    Every window, never only the `best` ones: `best` is a threshold on a score whose
    ordering leans toward motion (design §1.1), and a denominator drawn from it would
    inherit the very lean this gate exists to correct — that reason stands on its
    own. Windows are candidate SPANS, not distinct moments: `intake.cull` only
    demotes a duplicate's `best` flag, it never removes a window from FOOTAGE.json,
    and `carve.units_for_span` deliberately emits overlapping candidates — so one
    real moment can contribute several windows to this count (design §13.9)."""
    counts = {s: 0 for s in SHOT_TYPES}
    for clip in footage.clips:
        for w in clip.windows:
            counts[delivered_shot(w.subject_w, w.subject_h, clip.res, aspect)] += 1
    return counts


def _candidates(footage: Footage, aspect: tuple[int, int], want: str,
                limit: int = 3) -> list[tuple[str, int, float]]:
    """The strongest unused-size windows, as (source, window index, score), so a
    refusal names a mechanical fix instead of an abstract complaint."""
    rows = [(clip.source, i, w.score)
            for clip in footage.clips
            for i, w in enumerate(clip.windows)
            if delivered_shot(w.subject_w, w.subject_h, clip.res, aspect) == want]
    return sorted(rows, key=lambda r: r[2], reverse=True)[:limit]


def _placed(clip: FootageClip, ep: EDLEpisode) -> Placed:
    """Project one episode onto what an editorial rule can judge (design §4).

    A hero reaches the projection only when it is a cast NAME: a str that is not one
    of models.HERO_RULES. A bbox tuple, a track id, and "largest" all name a tracking
    target rather than a person, so they project to None — which a bookend rule reads
    as unsatisfied, never as satisfied."""
    hero = ep.hero if isinstance(ep.hero, str) and ep.hero not in HERO_RULES else None
    return Placed(source=ep.source, shot=clip.shot_at(ep.start), hero=hero)


def build_edl(footage: Footage, selection: dict, pacing: Spine | None = None,
              cast: str | None = None, *, aspect: tuple[int, int] | None = None,
              preset: MoodPreset | None = None,
              rules: Constraints | None = None, platform: str = "",
              look: LookSpec | None = None, music: MusicSpec | None = None,
              brief_len: float | None = None) -> EDL:
    """Assemble an EDL from a selection dict; when a pacing Spine is supplied, bind each
    episode to its slot (beat_slot + the FITTED dur, which is the episode's own length plus
    at most a half-beat snap — binding applies a fit, it does not re-time). Each selection
    episode references a
    window by (source, integer index) — or a two-element `[i, j]` span merged into one
    episode (§3b) — into FOOTAGE and supplies editorial fields;
    window_to_episode projects the mechanical fields. Reel knobs (music/cap/
    target_dur) ride at the top level — except target_dur is instead DERIVED from the spine
    (the pacing-gate back-edge, §4) when pacing is supplied, since pacing owns a paced reel's
    length; cast is the cast.json path (§6.1a) — a driver-level knob like pacing, not an
    editorial field in selection.json, since it names the registry an episode's hero *name*
    resolves against, not a per-episode choice. Fail-loud on a source not in FOOTAGE or an
    out-of-range window index (a typo would else surface as a FileNotFound deep in extract —
    montage §12).

    `aspect` and `preset` (design 2026-08-06, keyword-only) drive the shot-size variety
    census: when BOTH are given, every selected window is tallied by footage.delivered_shot
    into `used` as it is resolved, `_available_census` walks the whole footage pool the same
    way, and moodpreset.evaluate compares the two into the returned EDL.variety. A MISSING
    aspect or preset means the census was never run — EDL.variety stays None, which reads as
    "not evaluated", never as "passed" — the SP1 boundary for a hand-authored selection with
    no project geometry. build_edl only MEASURES here; it never refuses on a gap — that
    policy lives one level up, in write_edit_plan, so the report reaches the caller either
    way.

    `rules` (design 2026-08-07, keyword-only) are the project's editorial constraints.
    When supplied, every episode is projected onto a `Placed` as it is resolved and
    constraints.evaluate compares the cut against the rules into the returned
    EDL.constraints. Absent rules leave EDL.constraints None, which reads as "not
    evaluated", never as "passed". As with variety, build_edl only MEASURES; the
    refusal lives one level up in write_edit_plan, so a caller building an EDL in
    memory still gets the finding.

    `platform` (design 2026-08-12 §1.1, keyword-only) rides straight onto EDL.platform —
    build_edl does not resolve it from anything, write_edit_plan already reads SPEC.platform
    for the caller. A bare "" (the default) means the generic safe zone, same as omitting it.

    `look` (design 2026-08-13 §6, keyword-only) is the fallback LookSpec applied when
    selection.json authors none — write_edit_plan passes preset.look when a mood MATCHED,
    and None when nothing did (corrected post-review, final-findings.md I-2): the
    'balanced' fallback's own look is never applied, because filling it with any concrete
    value would itself be a silent change to a brief-less run's output (a real fade, or an
    authored fade=0.0 switching off mix's own audio bookend — see moodpreset.BALANCED's
    comment). selection.json's own "look" key wins when present regardless of which look
    was passed here: an author who writes {} or {"vignette": 0, "fade": 0} has DECIDED
    against a look, and neither the preset nor the fallback gets to overwrite that
    decision, so the check is `is not None`, never truthiness — {} is falsy, and a naive
    `if sel_look:` would silently fall through to `look` on exactly that spelling.
    Omitting `look` (passing None) with no selection.json override leaves EDL.look at
    None — the same "never authored" a hand-authored SP1 EDL.json carries.

    `music` (design 2026-08-14 §6/§7, keyword-only) is MUSIC.json's MusicSpec — supplying
    it lets `_apply_outro` move the LAST episode's end so the reel's length resolves on a
    bar line, but ONLY when `pacing` is also supplied: the fit runs after `_bind_pacing`
    and reads the fade `look` resolves to (never through a slot — see `_apply_outro`'s own
    docstring). Omitting `music` (the default) leaves EDL.outro at None, same as a
    hand-authored SP1 EDL. `brief_len` is SPEC.length_s, the tie-breaker `outro.fit_outro`
    prefers when two bar lines are equally reachable; None (no brief) breaks ties toward
    the smaller move instead."""
    eps_in = selection.get("episodes")
    if not isinstance(eps_in, list) or not eps_in:
        raise ValueError("selection.episodes must be a non-empty list of episode objects")
    by_source = {c.source: c for c in footage.clips}
    episodes: list[EDLEpisode] = []
    placed: list[Placed] = []
    used = {s: 0 for s in SHOT_TYPES}
    for k, sel in enumerate(eps_in):
        if not isinstance(sel, dict):
            raise ValueError(f"selection episode {k} must be an object, got {type(sel).__name__}")
        ed = dict(sel)
        source = ed.pop("source", None)
        window = ed.pop("window", None)
        # popped like source/window, not forwarded as editorial: it is a MECHANICAL
        # field (it moves the cut), and EDLEpisode would reject it as unknown.
        start_offset = ed.pop("start_offset", 0.0)
        if not (isinstance(source, str) and source):
            raise ValueError(f"selection episode {k}: 'source' must be a clip path string")
        clip = by_source.get(source)
        if clip is None:
            raise ValueError(f"selection episode {k}: source {source!r} not in FOOTAGE — "
                             f"have {sorted(by_source)}")
        fw = _resolve_window(clip, window, source, k)
        if aspect is not None:
            used[delivered_shot(fw.subject_w, fw.subject_h, clip.res, aspect)] += 1
        ep = window_to_episode(clip, fw, start_offset=start_offset, **ed)
        episodes.append(ep)
        placed.append(_placed(clip, ep))
    # the reel's bookend fade, resolved exactly as EDL.look is (selection.json wins over
    # the preset), because it is the number mix uses and therefore the number the outro
    # fit must add to the bar line. No look at all -> mix's own default.
    sel_look = selection.get("look")
    resolved_look = LookSpec.from_dict(sel_look) if sel_look is not None else look
    resolved_fade = resolved_look.fade if resolved_look is not None else _MIX_DEFAULT_FADE
    target = selection.get("target_dur")
    fit = None
    if pacing is not None:
        episodes = _bind_pacing(episodes, pacing)
        # AFTER the binding and BEFORE the back-edge target: _bind_pacing's half-beat
        # guard must keep guarding what it was built for, and _back_edge_target must
        # report the length the outro fit actually chose (design §6).
        if music is not None:
            episodes, fit = _apply_outro(episodes, footage, music,
                                         resolved_fade, brief_len)
        target = _back_edge_target(episodes, pacing)   # pacing owns a paced reel's length (§4)
    cap = selection.get("cap")
    variety = None
    if aspect is not None and preset is not None:
        asl = (sum(e.play_dur() for e in episodes) / len(episodes)) if episodes else 0.0
        variety = moodpreset.evaluate(_available_census(footage, aspect), used, asl,
                                      preset, waiver=selection.get("variety_waiver"))
    # After pacing: binding rewrites `dur` only, which none of the four rule kinds
    # reads — but evaluating the FINAL episode list keeps the report describing the
    # EDL that is actually written.
    cons = check_constraints(rules, tuple(placed), footage) if rules is not None else None
    return EDL(episodes=tuple(episodes), music=selection.get("music"), cast=cast,
               cap=cap if cap is not None else 3, platform=platform, look=resolved_look,
               target_dur=target, variety=variety, constraints=cons, outro=fit)


def write_edit_plan(footage_path: str, selection_path: str, project_path: str, out_dir: str,
                    pacing_path: str | None = None, cast: str | None = None,
                    spec: str | None = None, music: str | None = None) -> dict:
    """Author EDL.json + EDL.md from FOOTAGE + a selection, gated by the project's
    manifest preflight. Nothing is written when preflight fails — a bad EDL never
    lands as a half-valid artifact. cast is cast.json from intake — required if any
    episode pins a cast name (§6.1a); preflight below loads the registry and reports
    an unresolved name as part of its normal stop_and_report, not a raise. `spec` is
    SPEC.json (§5.3, optional) — its mood resolves the shot-mix preset the variety
    gate (design 2026-08-06) holds the cut to, and its platform (design 2026-08-12
    §1.1) rides onto EDL.platform, the UI safe-zone table key edl_to_reel later spends
    on ReelManifest.platform; without a spec the gate still runs against the `balanced`
    preset and the EDL's platform stays "" (the generic zone), since skipping the
    optional brief must not disable a quality gate or silently pick a platform. A cut
    that leaves an available, wanted shot size unused
    and unwaived stops here too, before preflight, with its own reason
    `variety-gap` (never `edl-invalid`, so the two failure classes stay
    attributable without parsing prose). Returns {"status": "written", ...} or a
    stop_and_report — from the variety gate or from preflight — verbatim.

    Editorial constraints (design 2026-08-07) are found BY CONVENTION beside
    project.json as CONSTRAINTS.json — there is no flag to forget. Absent means no
    rules; present means enforced on every invocation, which is what makes a stated
    rule survive a re-cut. A broken rule stops here with its own reason
    `constraint-violation`, before the variety gate and before preflight, and there is
    no waiver: the rule is the user's, not the agent's to overrule.

    `music` (design 2026-08-14 §7, optional) is MUSIC.json — supplying it, together with
    `--pacing`, fits the reel's end to a bar line with a vocal-free tail after it (see
    build_edl's `music` paragraph and `_apply_outro`). Absent, EDL.outro stays None and
    the reel's length is whatever the footage/pacing already decided, unchanged."""
    footage = Footage.from_json(footage_path)
    try:
        selection = json.loads(Path(selection_path).read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{selection_path} is not valid JSON ({e}) — fix the selection syntax") from e
    cfg = ProjectConfig.from_json(project_path)
    rules_path = Path(project_path).parent / "CONSTRAINTS.json"
    rules = Constraints.from_json(rules_path) if rules_path.exists() else None
    if rules is not None:
        _log(f"constraints: {len(rules.rules)} editorial rule(s) from {rules_path}")
    sp = Spec.from_json(spec) if spec else None
    preset = moodpreset.resolve(sp.mood if sp else None)
    if preset.name == "balanced":
        _log(f"variety: no SPEC mood matched a preset — using the 'balanced' shot mix "
             f"{preset.shot_mix} (a skipped brief must not disable the gate)")
    # Say out loud which safe-zone table the reel will be judged against. Silence here
    # is how the platform got lost in the first place: `--spec` is optional, this driver
    # is re-run WITH --pacing to apply the fit, and a dropped flag on that second run
    # rewrites EDL.platform back to "" — reverting check_reel's safe zone and the bottom
    # title's y layout to generic with no trace. An unknown label is worth saying too:
    # safezones.safe_zone_for falls back to the generic table for anything outside its
    # own vocabulary, so a typo reproduces the original defect quietly.
    plat = sp.platform if sp else ""
    if not plat:
        _log("platform: none (no --spec, or SPEC.platform empty) — check_reel's safe "
             "zone and the title layout both use the GENERIC table")
    elif not safezones.known(plat):
        _log(f"platform: {plat!r} has no safe zone of its own (known: "
             f"{sorted(safezones.SAFE_ZONES)}) — it is recorded on the EDL and attested, "
             "but the GENERIC zone is what check_reel will actually judge against")
    else:
        _log(f"platform: {plat} — its safe zone is what check_reel and the titles will use")
    # selection.json wins over the preset's default (build_edl re-applies the same
    # is-not-None rule below; this log line only reports which source won). When
    # NOTHING matched (preset is the 'balanced' fallback), the preset's own .look is
    # never what fills the gap: a skipped or mood-less brief must not silently apply a
    # TASTE (a real fade) or silently switch off mix's own audio bookend (an authored
    # fade=0.0 reaching build_reel does that — see LookSpec's docstring), so the
    # fallback handed to build_edl is None, the same "never authored" state a
    # hand-authored EDL.json carries and the only value that changes NOTHING about a
    # brief-less run's output (design 2026-08-13 §6, corrected post-review —
    # final-findings.md I-2; moodpreset.BALANCED's own comment carries the same
    # reasoning for a caller who reads that field directly).
    sel_look = selection.get("look")
    fallback_look = None if preset.name == "balanced" else preset.look
    if sel_look is not None:
        eff_look = LookSpec.from_dict(sel_look)
        _log(f"look: vignette {eff_look.vignette:.2f} · fade {eff_look.fade:.2f}s — "
             "from selection.json")
    elif fallback_look is not None:
        _log(f"look: vignette {fallback_look.vignette:.2f} · fade {fallback_look.fade:.2f}s "
             f"— from the {preset.name} preset")
    else:
        _log("look: left unauthored — no SPEC mood matched a preset, and the 'balanced' "
             "fallback's own look is never applied (it would itself be a silent change "
             "to a brief-less run's output); deliver renders no vignette/fade and mix "
             "keeps its own default 0.5s audio bookend")
    pacing = Spine.from_json(pacing_path) if pacing_path else None
    ms = MusicSpec.from_json(music) if music else None
    if ms is not None and not ms.bars:
        _log(f"outro: {music} has no bar grid (beats found fewer than 8 beats, or the "
             f"file predates the 2026-08-14 fields) — re-run beats to regenerate it; "
             f"the reel keeps its footage-derived length")
    edl = build_edl(footage, selection, pacing=pacing, cast=cast,
                    aspect=tuple(cfg.canvas), preset=preset, rules=rules,
                    platform=plat, look=fallback_look,
                    music=ms, brief_len=sp.length_s if sp else None)
    c = edl.constraints
    if c is not None and not c.ok:
        # The user's own stated rule outranks the preset's inference, so its finding is
        # the one the caller sees. No waiver exists by design: the only way past is the
        # user editing or deleting the rule (design §5).
        return {"status": "stop_and_report",
                "finding": {"reason": "constraint-violation", "episode_idx": None,
                            "problems": [f"{v.stated} ({v.kind}): {v.message}"
                                         for v in c.violations]}}
    v = edl.variety
    _log("variety: preset {} — footage offers {}".format(
        v.preset, ", ".join(f"{s} {v.available[s]}" for s in SHOT_TYPES)))
    if not v.ok:
        problems = []
        for s in v.gaps:
            cands = ", ".join(f"{src} #{i} (score {sc:.2f})"
                              for src, i, sc in _candidates(footage, tuple(cfg.canvas), s))
            problems.append(
                f"preset {v.preset!r} wants {s} (target {preset.shot_mix[s]:.0%}) and the "
                f"footage offers {v.available[s]} {s} windows in the delivered frame, but "
                f"the cut uses 0. Candidates: {cands}. Add one, or state why the cut stays "
                f'as it is in selection.json: "variety_waiver": "<reason>"')
        return {"status": "stop_and_report",
                "finding": {"reason": "variety-gap", "episode_idx": None,
                            "problems": problems}}
    _, stop = preflight(edl, cfg, str(Path(out_dir) / "segments"), out_dir)
    if stop:
        return stop
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    edl_path, md_path = Path(out_dir) / "EDL.json", Path(out_dir) / "EDL.md"
    write_edl(edl, edl_path, selection=selection_path)
    md_path.write_text(edl.to_markdown())
    return {"status": "written", "edl": str(edl_path), "md": str(md_path),
            "episodes": len(edl.episodes)}


def main() -> None:
    ap = argparse.ArgumentParser(description="author EDL.json + EDL.md from FOOTAGE + a selection (stage 5.7)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build EDL.json + EDL.md from a selection")
    b.add_argument("--footage", required=True, help="FOOTAGE.json from intake (stage 5.2)")
    b.add_argument("--selection", required=True, help="selection.json — window refs + editorial fields")
    b.add_argument("--project", required=True, help="project.json — canvas/delivery for the preflight")
    b.add_argument("--out-dir", required=True, help="dir for EDL.json + EDL.md")
    b.add_argument("--pacing", help="PACING.json — bind episodes to the energy spine (optional, §5.6)")
    b.add_argument("--cast", help="cast.json from intake — required if any episode pins a cast name (§6.1a)")
    b.add_argument("--spec", help="SPEC.json — its mood picks the shot-mix preset "
                                  "(optional; without it the 'balanced' preset applies)")
    b.add_argument("--music", help="MUSIC.json — fit the reel's end to a bar line "
                                   "with a vocal-free tail (optional, §5.5/backlog #2)")
    a = ap.parse_args()
    result = write_edit_plan(a.footage, a.selection, a.project, a.out_dir, a.pacing,
                             cast=a.cast, spec=a.spec, music=a.music)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "written" else 1)


if __name__ == "__main__":
    main()
