"""Subject grade-delta (design docs/specs/2026-08-28-grade-delta-sensors-design.md §2.3):
how far the grade moved a named region's colour, plain render vs graded render.

"source vs delivered" until 2026-09-16: the caller compared the pre-grade source
clip against the shipped CRF-18 one. It now hands over the two halves of
check_episode._grade_damage's own (graded, plain) RenderPlan pair, so the encode
is on neither side and the two readings share one baseline (design 2026-09-16
§0.3/§0.4).

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


def sample_deltas(pairs: list[tuple]) -> list[tuple[float, float, float, float]]:
    """One (dE00, dL*, dC*, dH*) row per (plain_rgb, graded_rgb) pair.

    The order is the sign convention and it is load-bearing: colordiff.ciede2000's
    three components are signed lab1 -> lab2, so a caller that passes the graded
    side first inverts all three while leaving dE00 itself identical. Measured,
    40.34/+39.29 becomes 40.34/-39.29."""
    return [colordiff.ciede2000(colordiff.rgb_to_lab(src), colordiff.rgb_to_lab(graded))
            for src, graded in pairs]


def evaluate(pairs: list[tuple]) -> dict:
    """The episode's DESCRIPTION: the MEDIAN of its samples. Does not vote —
    see the module docstring for why (design 2026-08-31 §3).

    Median, not worst: measured over the reference run and the damage magnitudes
    its retro recorded, the per-episode median separates (healthy 0.89-4.29,
    damage from 5.04) while the worst sample does not — a single near-grey sample
    swings far under any grade (design §0.4).

    The three signed components are reported but do not vote. They are the
    explanation — "the grade lifted exposure" rather than "the colour changed by
    6" — and they are reported as three numbers, not as a winner among them: the
    `dominant` field this returned until 2026-09-16 flipped on three of the four
    real episodes when the sample count moved from 5 to 3, with the top two
    components within 0.5 in every flip and one exact tie at 1.22 broken by the
    order of a tuple (design 2026-09-16 §0.5)."""
    if not pairs:
        return {"status": "not-checked", "reason": "no samples to compare"}
    rows = sample_deltas(pairs)
    comps = tuple(statistics.median(r[i] for r in rows) for i in (1, 2, 3))
    de = round(statistics.median(r[0] for r in rows), 2)
    return {"delta_e": de,
            "delta_l": round(comps[0], 2),
            "delta_c": round(comps[1], 2),
            "delta_h": round(comps[2], 2),
            "samples": len(rows)}
