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


def shift_from_report(report: dict) -> dict:
    """The episode's chroma displacement, in the shape ReelEpisode.chroma carries.

    One reader for a report's own description of what the grade did to its colour,
    so the two drivers that fill the carrier (edl_to_reel's phase 1 and build_reel's
    reprocess arm) cannot drift about which key holds it (design 2026-09-17 §2.3).

    The pair handed over is always the CROP's — the one pixel set defined identically
    on every episode — which is `crop_delta_c`/`crop_delta_h` when the subject
    supplied the primary reading and `delta_c`/`delta_h` when it fell back and the
    primary reading already IS the crop's (design §2.2).

    The reading carries no `region` key (final whole-branch review, FIX 1; design
    §2.3 amended): both arms hand over the SAME pixel set — the crop's — so a label
    naming which region supplied the numbers would either be constant ("crop",
    always) or, on the subject arm, would say "subject" while the numbers under it
    are the crop's, which is a reading naming pixels that are not the ones it
    describes. A field that cannot be decided is deleted, not qualified (design
    §1 rule 4) — nothing downstream reads it either: `_chroma_spread_check`
    discriminates on `status` to find the absence branch, and reads
    `delta_c`/`delta_h` only on the branch that remains (design 2026-09-21 §0.3).
    Do not add it back; a caller that needs to know which arm supplied
    `check_episode`'s own reading already has `region` on THAT report, at
    `report["checks"]["grade_damage"]["region"]` — unaffected by this function,
    which only renames two of that same dict's keys.

    Keys on `region`, never on the presence of a `status` key: the grade_damage block
    is a FLAT merge of a verdict dict and an advisory dict, and a predicate over
    `"status" in d` reads a key either half could contribute.
    """
    checks = report.get("checks") if isinstance(report, dict) else None
    d = checks.get("grade_damage") if isinstance(checks, dict) else None
    if not isinstance(d, dict):
        return {"status": "not-checked",
                "reason": "the report carries no grade_damage block"}
    region = d.get("region")
    if region == "subject":
        return {"delta_c": d["crop_delta_c"], "delta_h": d["crop_delta_h"]}
    if region == "crop":
        return {"delta_c": d["delta_c"], "delta_h": d["delta_h"]}
    # `d.get("status")` is not a second fallback leg here (final whole-branch review,
    # FIX 4): reaching this line at all needs a grade_damage block with no readable
    # region, and the only region-less shape production ever emits is
    # check_episode._grade_damage's early return, which always carries a `reason`
    # beside its `status` — so a `status`-only dict is not a shape this function is
    # ever handed in practice, and using it as a reason would report the literal
    # string "not-checked": an absence that names that it was not checked but not why.
    return {"status": "not-checked",
            "reason": d.get("reason")
            or f"grade_damage names no readable region (got {region!r})"}
