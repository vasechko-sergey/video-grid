"""Pure orchestration decisions for process-episode (§4.1).

Everything here is deterministic and unit-tested: what counts as a
manifest-vs-reality contradiction (stop-and-report), how to nudge reframe
params on a mechanical fail (retry-in-place), and when to stop retrying and
escalate up the artifact chain. The imperative shell (process_episode.py)
only wires these to the engine scripts.
"""
from scripts.lib.motion import classify


def derive_intent(composition: str, motion: str | None) -> str:
    """Hero-scoring intent from MANIFEST signal only (§6.1a). Must be manifest-
    only: intent picks the hero DURING tracking, before a hero route exists to
    classify(). center, or a declared static/head-on motion → 'static' (size +
    duration win); lateral, or infer with a lead/break composition → 'action'."""
    if composition == "center":
        return "static"
    if motion in ("static", "head-on"):
        return "static"
    return "action"


def flow_eligible(pinned: bool, route_empty: bool) -> bool:
    """An empty route falls to the optical-flow rung ONLY when nobody was pinned.

    Optical-flow follows the dominant motion blob and makes no identity claim, so it
    cannot honor a §5.10 hero pin — an empty route under a pin is hero-unmatched (the
    pinned person is simply not in this segment), and answering it with a motion blob
    is the silent identity substitution the hero-pin slice deleted. A non-empty route
    needs no fallback at all. See design 2026-07-21 §1.1."""
    return route_empty and not pinned


def detect_contradictions(motion: str | None, route: list[dict],
                          track_meta: dict, src_w: int, src_h: int,
                          composition: str | None = None) -> list[dict]:
    """Machine-detectable manifest-vs-reality conflicts (§4.1). Returns a list
    of {reason, detail} findings; non-empty ⇒ stop-and-report, never improvise."""
    findings = []
    meta = track_meta or {}
    # TrackMeta.features is per-CONFIRMED-track, so non-empty ⇔ the tracker saw
    # somebody. It is the only thing in the sidecar that tells the two empty-route
    # stories apart (`hero` is None under both), and the pre-emption below turns on
    # exactly that difference. Absent reads as empty — TrackMeta.to_dict always emits
    # the key and from_dict defaults it to {}, so the key is missing only from a meta
    # the pipeline never wrote.
    tracked = bool(meta.get("features"))
    if meta.get("pin_matched") is False and tracked:
        # ORDER IS LOAD-BEARING, AND SO IS THE `tracked` CONDITION ON IT: an
        # unmatched pin is what PRODUCED the empty route below, so no-track ("hero
        # never detected") would be the wrong diagnosis — it points at the segment or
        # the model, when the real answer is "the person you pinned is not in this
        # clip". That rationale holds only while somebody WAS tracked and the pin
        # missed them. With no tracks at all it is false: the DETECTOR produced the
        # empty route, there was nobody for ANY pin to match, and pre-empting here
        # misdirects instead — a rule pin names no person and claims no identity, so
        # "the pinned person may not be in this episode, or the cast descriptor may
        # not survive its lighting" answers a claim it never made. no-track is the
        # honest diagnosis there, and it already lists the pin among its three
        # suspects. Keyed on `features`, which the sidecar carries, rather than on the
        # pin KIND, which it does not.
        findings.append({"reason": "hero-unmatched",
                         "detail": "the manifest's hero pin matched no track in this segment — "
                                   "the pinned person may not be in this episode, or the cast "
                                   "descriptor may not survive its lighting; re-check the window, "
                                   "or pin a seed bbox instead"})
        return findings
    if not route:
        findings.append({"reason": "no-track",
                         "detail": "tracker produced an empty route — hero never "
                                   "detected; check the segment, model size, or hero pin"})
        return findings          # nothing else is meaningful without a route
    if meta.get("ambiguous"):
        # No pin check to FIRE the gate: the rungs consume the pin themselves, so
        # `ambiguous` is honest on its own. A pin that resolved cleanly sets it False;
        # a cast pin matching two look-alikes sets it True — and then the PIN is what
        # is ambiguous, so suppressing the gate (as is_seed_pin did) was backwards.
        #
        # The DETAIL, though, must still split on the pin: the remedy is the next
        # action an agent takes, and the two cases have opposite ones. pin_matched is
        # None ⇒ nobody pinned and the scoring tied ⇒ "pin a hero" IS the action.
        # pin_matched is True ⇒ the human pinned and the pin itself tied (only the
        # cast rung, _descriptor_track, can produce that pairing — every other rung
        # leaves ambiguous False), so "pin a hero and retry" would send them to re-run
        # the exact thing that just failed. Keyed on the meta, not on a pin kind the
        # sidecar does not carry.
        if meta.get("pin_matched"):
            detail = ("top-2 candidate scores within margin (§6.1a) — the hero pin itself "
                      "matched two candidates, so re-running it as-is changes nothing: a cast "
                      "descriptor that cannot separate two look-alikes will not separate them "
                      "on a retry either. Compare them in the route sidecar's `features` and "
                      "re-pin the one you mean by seed bbox [x,y,w,h] or track id — each names "
                      "one track outright, so neither can tie")
        else:
            detail = ("top-2 candidate scores within margin (§6.1a) — pin a hero (seed bbox "
                      "[x,y,w,h], a rule, a track id, or a cast name from cast.json) and retry")
        findings.append({"reason": "hero-ambiguous", "detail": detail})
    if composition == "lead":
        obs_type, _ = classify(route, src_w, src_h)
        if obs_type != "lateral":
            findings.append({"reason": "composition-motion-mismatch",
                             "detail": f"composition 'lead' needs lateral motion, but the "
                                       f"tracker sees {obs_type} — set composition to "
                                       f"'center', or fix the window/segment"})
    if motion:
        obs_type, obs_dir = classify(route, src_w, src_h)
        observed = obs_type + (f":{obs_dir}" if obs_dir else "")
        if _motion_conflicts(motion, observed):
            findings.append({"reason": "motion-mismatch",
                             "detail": f"manifest declares {motion}, tracker sees {observed}"})
    return findings


def _motion_conflicts(declared: str, observed: str) -> bool:
    """A hard conflict is a lateral DIRECTION reversal (right vs left) — the
    §4.1 example. Type drift (lateral vs static/head-on) is a soft mismatch we
    let the numeric gate judge, not a stop-and-report."""
    if declared.startswith("lateral:") and observed.startswith("lateral:"):
        return declared != observed          # right vs left
    return False


DEFAULT_PARAMS = {"max_speed": 750.0,             # px/s (§6.1: 25 px/frame @30fps)
                  "smooth_window_s": 0.25}        # savgol span, seconds (pathsmooth.DEFAULT_WINDOW_S)

SMOOTH_WINDOW_S_MAX = 0.7   # past this the crop stops following the subject at all and
                            # lags visibly through a real direction change

# reframe can't fix these by re-cropping — the fault is upstream (window/segment)
_UNFIXABLE = ("length", "continuity", "black_frames")


def _lags_line(fail_reasons: list[str]) -> bool:
    # centered is on_line at target_frac=0.5 (checks.centered) and reframe
    # rate-limits center/break identically to lead — same crop-lag signal
    return "on_line" in fail_reasons or "centered" in fail_reasons


def adjust_reframe_params(params: dict[str, float], fail_reasons: list[str]) -> dict[str, float]:
    """One documented nudge per mechanical fail (§4.1 retry-in-place).

    A partial `params` is filled from DEFAULT_PARAMS first, so a caller that knows
    about one knob still gets a complete, nudgeable set back rather than a KeyError
    on the knob it had never heard of."""
    p = {**DEFAULT_PARAMS, **params}
    if _lags_line(fail_reasons):
        p["max_speed"] = p["max_speed"] * 1.5      # crop lags the line → catch up
        # a wide window is exactly what makes the crop lag, so give it back the
        # responsiveness the same way it was taken — never below the default
        p["smooth_window_s"] = max(DEFAULT_PARAMS["smooth_window_s"],
                                   p["smooth_window_s"] / 2)
    if "jitter" in fail_reasons:
        p["max_speed"] = p["max_speed"] * 0.6      # crop too twitchy → damp harder
        # …and widen the averaging window, which is the knob that actually reaches
        # this failure. max_speed caps the SIZE of a step; the jitter check fires on
        # low-amplitude reversals that are already far under any speed cap the ladder
        # reaches, so speed alone never converges — measured on a 60fps drone ride:
        # 3 attempts of 750→450→270 px/s left worst_reversal unchanged at 4.0px.
        p["smooth_window_s"] = min(SMOOTH_WINDOW_S_MAX, p["smooth_window_s"] * 2)
    return p


def escalation(attempt: int, fail_reasons: list[str], max_attempts: int = 3) -> dict | None:
    """None ⇒ keep retrying; a finding dict ⇒ escalate up the artifact chain.

    Escalate immediately when the failure can't be fixed by reframe params
    (unfixable reasons, or a line-lag + jitter combo which pull speed in
    opposite directions); otherwise after max_attempts (§4.1: 3× → up)."""
    if any(r in _UNFIXABLE for r in fail_reasons):
        return {"escalate_to": "edit-plan", "reason": "unfixable-by-reframe",
                "fail_reasons": fail_reasons}
    if _lags_line(fail_reasons) and "jitter" in fail_reasons:
        return {"escalate_to": "edit-plan", "reason": "conflicting-framing-fails",
                "fail_reasons": fail_reasons}
    if attempt >= max_attempts:
        return {"escalate_to": "edit-plan", "reason": "max-retries",
                "fail_reasons": fail_reasons}
    return None
