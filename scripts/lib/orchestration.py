"""Pure orchestration decisions for process-episode (§4.1).

Everything here is deterministic and unit-tested: what counts as a
manifest-vs-reality contradiction (stop-and-report), how to nudge reframe
params on a mechanical fail (retry-in-place), and when to stop retrying and
escalate up the artifact chain. The imperative shell (process_episode.py)
only wires these to the engine scripts.
"""
from scripts.lib.motion import classify


def is_seed_pin(hero):
    """True iff `hero` is a hero value the tracker can ACTUALLY be seeded with
    this slice: a non-empty seed-bbox tuple. A cast name / rule / empty value is
    not applicable until the ingestion plan's cast.json lands — the shell only
    passes a tuple as `seed_bbox`, so only a tuple resolves §6.1a ambiguity. The
    ambiguity gate and the shell's seed gate MUST share this one predicate or a
    named-but-unseeded hero silently suppresses stop-and-report."""
    return isinstance(hero, tuple) and len(hero) > 0


def detect_contradictions(motion, hero, route, track_meta, src_w, src_h):
    """Machine-detectable manifest-vs-reality conflicts (§4.1). Returns a list
    of {reason, detail} findings; non-empty ⇒ stop-and-report, never improvise."""
    findings = []
    if not route:
        findings.append({"reason": "no-track",
                         "detail": "tracker produced an empty route — hero never "
                                   "detected; check the segment, model size, or hero pin"})
        return findings          # nothing else is meaningful without a route
    if (track_meta or {}).get("ambiguous") and not is_seed_pin(hero):
        # only an applicable seed pin resolves ambiguity — an empty pin ("" / ()
        # / []) OR a not-yet-supported cast name / rule is no seed at all
        findings.append({"reason": "hero-ambiguous",
                         "detail": "top-2 candidate scores within margin (§6.1a) — "
                                   "pin a hero (seed bbox [x,y,w,h]; cast name / rule "
                                   "needs the ingestion plan) and retry"})
    if motion:
        obs_type, obs_dir = classify(route, src_w, src_h)
        observed = obs_type + (f":{obs_dir}" if obs_dir else "")
        if _motion_conflicts(motion, observed):
            findings.append({"reason": "motion-mismatch",
                             "detail": f"manifest declares {motion}, tracker sees {observed}"})
    return findings


def _motion_conflicts(declared, observed):
    """A hard conflict is a lateral DIRECTION reversal (right vs left) — the
    §4.1 example. Type drift (lateral vs static/head-on) is a soft mismatch we
    let the numeric gate judge, not a stop-and-report."""
    if declared.startswith("lateral:") and observed.startswith("lateral:"):
        return declared != observed          # right vs left
    return False


DEFAULT_PARAMS = {"max_speed": 750.0}          # px/s (§6.1: 25 px/frame @30fps)

# reframe can't fix these by re-cropping — the fault is upstream (window/segment)
_UNFIXABLE = ("length", "continuity", "black_frames")


def _lags_line(fail_reasons):
    # centered is on_line at target_frac=0.5 (checks.centered) and reframe
    # rate-limits center/break identically to lead — same crop-lag signal
    return "on_line" in fail_reasons or "centered" in fail_reasons


def adjust_reframe_params(params, fail_reasons):
    """One documented nudge per mechanical fail (§4.1 retry-in-place)."""
    p = dict(params)
    if _lags_line(fail_reasons):
        p["max_speed"] = p["max_speed"] * 1.5      # crop lags the line → catch up
    if "jitter" in fail_reasons:
        p["max_speed"] = p["max_speed"] * 0.6      # crop too twitchy → damp harder
    return p


def escalation(attempt, fail_reasons, max_attempts=3):
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
