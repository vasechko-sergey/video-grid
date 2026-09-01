"""Subject grade-delta (design docs/specs/2026-08-28-grade-delta-sensors-design.md §2.3):
how far the grade moved the tracked subject's colour, source vs delivered.

Pure — the sampling lives in check_episode, the arithmetic in colordiff. What
this module owns is the DESCRIPTION: which statistic over the samples, and what
the numbers are called in the report. It no longer owns a verdict (design
2026-08-31 §3): a grade IS movement, so a threshold on this number cannot tell
a grade from damage — on the reference run a real conductor pair puts five of
eight episodes over the old 5.0 ceiling, two at over twice it, and none of them
is damage. check_episode.grade_damage's luma-entropy ratio carries the verdict
now; this module's dE00 rides along as an advisory description of WHAT the
grade did, read by check_episode._subject_delta_advisory and the QC judge.

This replaces a hue-angle metric that could not see its own subject. Hue is
invariant to exposure and saturation, which is what a grade moves, and the
metric additionally discarded any sample whose chroma fell under a fixed floor —
on the reference run that was 9 of 24 samples, including one where the grade
HALVED the subject's chroma and one where it quadrupled it (design §0.2)."""
import statistics

from scripts.lib import colordiff

# Report names for the three signed components, in ciede2000's own order.
_COMPONENTS = ("luma", "chroma", "hue")


def sample_deltas(pairs: list[tuple]) -> list[tuple[float, float, float, float]]:
    """One (dE00, dL*, dC*, dH*) row per (source_rgb, graded_rgb) pair."""
    return [colordiff.ciede2000(colordiff.rgb_to_lab(src), colordiff.rgb_to_lab(graded))
            for src, graded in pairs]


def evaluate(pairs: list[tuple]) -> dict:
    """The episode's DESCRIPTION: the MEDIAN of its samples. Does not vote —
    see the module docstring for why (design 2026-08-31 §3).

    Median, not worst: measured over the reference run and the damage magnitudes
    its retro recorded, the per-episode median separates (healthy 0.89-4.29,
    damage from 5.04) while the worst sample does not — a single near-grey sample
    swings far under any grade (design §0.4).

    The three components are reported but do not vote. They are the explanation:
    `dominant` names whichever moved most, so a report reads as "the grade lifted
    exposure" rather than "the colour changed by 6"."""
    if not pairs:
        return {"status": "not-checked", "reason": "no samples to compare"}
    rows = sample_deltas(pairs)
    comps = tuple(statistics.median(r[i] for r in rows) for i in (1, 2, 3))
    dominant = _COMPONENTS[max(range(3), key=lambda i: abs(comps[i]))]
    de = round(statistics.median(r[0] for r in rows), 2)
    return {"delta_e": de,
            "delta_l": round(comps[0], 2),
            "delta_c": round(comps[1], 2),
            "delta_h": round(comps[2], 2),
            "samples": len(rows),
            "dominant": dominant}
