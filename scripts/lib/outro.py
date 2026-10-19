"""Outro fit — where the reel's music stops (design
docs/specs/2026-08-14-music-outro-fit-design.md).

Pure: numbers in, one OutroFit out. No audio IO, no ffmpeg, no librosa. The whole
slice reduces to picking ONE number, the reel's length, because mix already fades
over [dur - fade, dur] — so a reel of `line + fade` starts its fade exactly on the
bar line and no ffmpeg stage changes at all (design §1)."""
from collections.abc import Sequence
from dataclasses import dataclass, replace

BAR_BEATS = 4       # 4/4 assumed — beats.py's downbeat detector reads this too (§11.3)
TAIL_MARGIN = 0.05  # vocal-free seconds required ON TOP OF the fade. DERIVED, not
                    # taste: two bins of the vocal envelope at vocals._SPAN_HZ (40 Hz,
                    # ~23 ms each), which is the boundary quantization of the very
                    # sensor that produced the spans this is compared against.
                    # tests/lib/test_outro.py pins the identity so the two cannot drift;
                    # outro.py itself stays free of the vocals import.
                    #
                    # It replaced TAIL_MIN = 0.5 on 2026-08-18 (design
                    # docs/specs/2026-08-18-deferred-measurements-design.md §1). That
                    # constant was wrong in KIND, not in value: the reel is
                    # `line + fade` long, so `max(TAIL_MIN, fade)` at fade < 0.5
                    # demanded silence in audio the stem never contains — and when it
                    # bit, the no-gap rung it fell to checks no tail at all and shipped
                    # a 1.5s fade over 1.15s of singing (§1.3). It also disqualified
                    # every gap in [0.35, 0.5), a band offset.vocal_gaps' own
                    # min_gap=0.35 declares valid — 16% of the real track's gaps.
NO_GAP_FADE = 1.5   # the longer fade rung 2 falls back to. Taste, not a measurement (§11.2)
MIN_LAST = 1.0      # the last episode may not be shrunk below this. A floor, not a
                    # finding (§11.7): without it a one-bar step down can leave a 2.5s
                    # closing shot at 0.3s, which is a glitch, not an ending.
RUNGS = ("gap", "no-gap", "unchanged")

CAUSES = ("no-bars", "no-episodes", "ramped-closer",
          "closer-not-in-footage", "no-reachable-line")

# One wording table for both readers — check_reel's outro reason and EDL.md's outro
# section. Two readers writing their own sentences for the same five states is the
# shape that drifts, and the sentence they used to share was FALSE for four of them:
# it said "the fit chose no bar line" where no fit had run at all.
#
# Each clause is self-contained and does NOT end in its own "so ..." tail: edl.py's
# outro section APPENDS ", so the reel keeps its footage-derived length and the music
# ends mid-phrase" to whichever of these check_reel prints standalone, and a clause
# already ending in "so ..." produced "...so no fit ever ran, so the reel keeps..." —
# a reviewer-found defect, cosmetic but user-visible in every rendered EDL.md.
CAUSE_WHY = {
    "no-bars": "no fit ever ran, because the analysed music window carries no bar grid",
    "no-episodes": "there is no closing shot to move, because the cut has no episodes",
    "ramped-closer": "the fit is skipped rather than guessed, because the closing "
                     "episode carries a ramp, whose played length is not its source "
                     "length",
    "closer-not-in-footage": "the room the closing episode has left could not be "
                             "measured, because its source is not in FOOTAGE.json",
    "no-reachable-line": "the fit ran and no bar line within one bar of the cut's own "
                         "length was one the closing shot could reach",
    # Reworded (final review M-12): the original read "...became distinguishable, so
    # the reel keeps its footage-derived length" once edl.py's tail was appended —
    # attaching the CONSEQUENCE to the documentation history rather than to the
    # absence itself. This clause ends on the absence (no cause was ever recorded),
    # which is what the appended "so" actually follows from.
    "": "not recorded — this artifact predates 2026-09-07 and cannot say which of "
        "five causes applied",
}

_EPS = 1e-9


@dataclass(frozen=True)
class OutroFit:
    """What the fit decided, and on which rung. Carried on EDL.outro as provenance —
    nothing downstream reads it, but a bare duration cannot say why it is that length."""
    reel_dur: float           # the reel length this fit asks for
    line: float | None        # the bar line the music resolves on; None on "unchanged"
    fade: float               # the fade that follows the line
    tail: float               # measured vocal-free seconds after the line
    rung: str                 # one of RUNGS
    moved: float              # reel_dur minus the input reel_dur (signed)
    brief_len: float | None = None   # SPEC.length_s, the brief's asked-for length, carried so
                                     # the DURABLE artifact can state the distance from it
                                     # (design §6: "the length tension is reported, never
                                     # resolved silently"). Without it only the transient
                                     # stderr line could say how far the reel drifted, and
                                     # EDL.md — the thing a later reader actually has —
                                     # could not. None = no brief was supplied.
    need: float = 0.0                # vocal-free seconds the GAP rung required:
                                     # fade + TAIL_MARGIN, at the fade the CALLER asked
                                     # for. Recorded because on the "no-gap" rung `fade`
                                     # has already been replaced by NO_GAP_FADE, so
                                     # nothing else in the artifact can say what the
                                     # refusal was measured against — and the old
                                     # sentence quoted a module constant that was not
                                     # even the number that applied (design §1.6).
                                     # Defaults to 0.0 so an EDL written before
                                     # 2026-08-18 still loads.
                                     #
                                     # "unchanged" ALWAYS carries 0.0, and the reason is
                                     # worth stating because it is not uniform: the
                                     # early no-bars return never computed a need, while
                                     # the final one is reached AFTER the gap rung ran
                                     # and refused. Both report 0.0 deliberately — the
                                     # field's one consumer is the no-gap sentence, and
                                     # on "unchanged" a non-zero need would read as a
                                     # requirement that was applied and met, which is
                                     # the opposite of what happened. 0.0 there means
                                     # "not applicable", not "nothing was asked".
    cause: str = ""                  # WHY this fit is "unchanged" — one of CAUSES.
                                     # "" on every gap/no-gap fit (a fit that chose a
                                     # bar line has no absence to name) and on an
                                     # artifact written before 2026-09-07. FIVE
                                     # producers can reach "unchanged" and until this
                                     # field every one wrote a byte-identical record,
                                     # so check_reel asserted "the fit chose no bar
                                     # line" for a run whose music had no bar grid and
                                     # where no fit had run (design 2026-09-07 §3).

    def __post_init__(self) -> None:
        if self.rung not in RUNGS:
            raise ValueError(f"OutroFit.rung must be one of {RUNGS}, got {self.rung!r}")
        if self.rung == "unchanged":
            if self.cause != "" and self.cause not in CAUSES:
                raise ValueError(
                    f"OutroFit.cause must be one of {CAUSES}, or '' for an artifact "
                    f"written before 2026-09-07 which recorded none; got "
                    f"{self.cause!r}. Re-run edit_plan build --pacing --music")
        elif self.cause:
            raise ValueError(
                f"OutroFit.cause must be '' when rung is {self.rung!r} — a fit that "
                f"chose a bar line has no absence to name, so a cause beside a "
                f"'gap'/'no-gap' rung is a contradiction the record must not hold. "
                f"Got {self.cause!r}. Re-run edit_plan build --pacing --music")
        # A "gap"/"no-gap" fit always CHOSE a real length (line + fade, always > 0);
        # "unchanged" carries no such promise (from_dict defaults a missing key to
        # 0.0, which stays legitimate there — nothing downstream ever reads reel_dur
        # for that rung). Catching the other two here is what makes OutroFit.from_dict
        # the oracle ReelManifest.__post_init__ already relies on it being (design §5.1)
        # — without this, {"rung": "gap"} round-trips clean with reel_dur silently
        # defaulted to 0.0, and check_reel's bare `outro["reel_dur"]` KeyErrors three
        # stages later instead of failing loud where the malformed value was accepted.
        if self.rung != "unchanged" and (
                isinstance(self.reel_dur, bool)
                or not isinstance(self.reel_dur, (int, float))
                or self.reel_dur <= 0):
            raise ValueError(
                f"OutroFit.reel_dur must be a positive number of seconds when rung is "
                f"{self.rung!r} — a 'gap'/'no-gap' fit always chose a real length "
                f"(line + fade); got {self.reel_dur!r}. Re-run edit_plan build "
                f"--pacing --music to regenerate EDL.outro")

    def to_dict(self) -> dict:
        return {"reel_dur": self.reel_dur, "line": self.line, "fade": self.fade,
                "tail": self.tail, "rung": self.rung, "moved": self.moved,
                "brief_len": self.brief_len, "need": self.need, "cause": self.cause}

    @classmethod
    def from_dict(cls, d: dict) -> "OutroFit":
        if not isinstance(d, dict):
            raise ValueError(f"OutroFit.from_dict: expected an object, got "
                             f"{type(d).__name__} — re-run edit_plan build")
        fit = cls(reel_dur=d.get("reel_dur", 0.0), line=d.get("line"),
                   fade=d.get("fade", 0.0), tail=d.get("tail", 0.0),
                   rung=d.get("rung", "unchanged"), moved=d.get("moved", 0.0),
                   brief_len=d.get("brief_len"), need=d.get("need", 0.0),
                   cause=d.get("cause", ""))
        if fit.rung != "unchanged" and "fade" not in d:
            # Checked AFTER construction, so a bad rung or a missing reel_dur keeps its
            # own message. A fitted rung's fade is what mix closes the music on (retro
            # 2026-10-16 S18), so it cannot be defaulted to 0.0 the way an "unchanged"
            # record's fields can: that would silently cut the music dead.
            raise ValueError(
                f"OutroFit.from_dict: a {fit.rung!r} fit must record its 'fade' — the "
                f"music closes on it, starting on the bar line. Re-run edit_plan build "
                f"--pacing --music to regenerate EDL.outro")
        return fit


def bar_seconds(tempo: float) -> float:
    """One bar in seconds at `tempo` BPM, assuming 4/4."""
    if not isinstance(tempo, (int, float)) or isinstance(tempo, bool) or tempo <= 0:
        raise ValueError(f"outro.bar_seconds: tempo must be a positive BPM, got {tempo!r}")
    return BAR_BEATS * 60.0 / float(tempo)


def window_spans(spans: Sequence[tuple[float, float]], start_offset: float,
                 duration: float) -> tuple[tuple[float, float], ...]:
    """TRACK-relative spans -> STEM-relative, clipped to [0, duration].

    vocals.vocal_spans measures the whole track; MusicSpec stores the window. This is
    the ONE place the two coordinate systems meet. A span that does not intersect the
    window is dropped, not clamped to a zero-length pair."""
    out = []
    for a, b in spans:
        s, e = max(float(a) - start_offset, 0.0), min(float(b) - start_offset, duration)
        if e > s:
            out.append((s, e))
    return tuple(out)


def free_after(spans: Sequence[tuple[float, float]], t: float) -> float:
    """Continuous vocal-free seconds starting AT `t`; 0.0 when `t` is inside a vocal.

    Spans are ascending and disjoint (MusicSpec enforces it), so the first containing
    span is the answer."""
    for a, b in spans:
        if a - _EPS <= t <= b + _EPS:
            return max(0.0, b - t)
    return 0.0


def _candidates(bars, reel_dur, bar_s, fade, music_dur, grow_max, shrink_max):
    """Bar lines whose `line + fade` is a legal reel length (design §5)."""
    out = []
    for line in bars:
        end = line + fade
        move = end - reel_dur
        if abs(move) > bar_s + _EPS:            # 1. the +/- one-bar band
            continue
        if end > music_dur + _EPS:              # 2. inside the analysed music window
            continue
        if move > grow_max + _EPS:              # 3. the closing shot can grow this far
            continue
        if -move > shrink_max + _EPS:           # 4. ...and shrink this far
            continue
        out.append(float(line))
    return out


def fit_outro(bars: Sequence[float], vocal_spans: Sequence[tuple[float, float]],
              reel_dur: float, bar_s: float, fade: float, *, music_dur: float,
              grow_max: float, shrink_max: float,
              brief_len: float | None = None) -> OutroFit:
    """Pick the reel length that makes the music resolve on a bar line.

    The ladder (design §5): a line with `fade + TAIL_MARGIN` of vocal-free space after
    it; else the nearest line with NO_GAP_FADE, re-filtered through the band so the
    longer fade cannot smuggle length past it; else nothing moves. There is no refusal
    rung — an awkward music tail is not worth blocking a delivery over, and the caller
    reports which rung won.

    Ties resolve toward `brief_len` (SPEC.length_s) when it is known, else toward the
    smallest move, then toward the earlier line so the answer is deterministic."""
    if not isinstance(fade, (int, float)) or isinstance(fade, bool) or fade < 0:
        raise ValueError(f"outro.fit_outro: fade must be a non-negative number of "
                         f"seconds, got {fade!r}")
    if not isinstance(bar_s, (int, float)) or isinstance(bar_s, bool) or bar_s <= 0:
        raise ValueError(f"outro.fit_outro: bar_s must be a positive number of seconds "
                         f"(one bar) — got {bar_s!r}; derive it with outro.bar_seconds")
    reel_dur = float(reel_dur)
    # The FINAL return's cause: the ladder ran and rejected every candidate.
    unchanged = OutroFit(reel_dur=reel_dur, line=None, fade=float(fade), tail=0.0,
                         rung="unchanged", moved=0.0, brief_len=brief_len,
                         cause="no-reachable-line")
    if not bars:
        # A DIFFERENT absence: with no bar grid the ladder below never runs at all.
        # It must be its own object — returning the shared `unchanged` here would
        # label it "no-reachable-line" and re-create in one line exactly the collapse
        # this field exists to end (design 2026-09-07 §3).
        return replace(unchanged, cause="no-bars")

    def pick(cands, f):
        ref = brief_len if brief_len is not None else reel_dur
        return min(cands, key=lambda line: (abs((line + f) - ref), line))

    # The fade must land in silence — arithmetic, not taste: the stem is `line + fade`
    # long and mix fades over [line, line + fade], so a vocal inside that span is the
    # only one anyone hears. TAIL_MARGIN rides on top for the sensor's own +/-1-bin
    # boundary error, and at fade == 0 it is the ONLY thing keeping the line out of a
    # vocal: free_after returns 0.0 for a line outside every gap, and `0.0 >= 0.0 -
    # _EPS` would accept it (design §1.5). Hence the SUM, not a max.
    need = float(fade) + TAIL_MARGIN
    gapped = [line for line in _candidates(bars, reel_dur, bar_s, fade, music_dur,
                                           grow_max, shrink_max)
              if free_after(vocal_spans, line) >= need - _EPS]
    if gapped:
        line = pick(gapped, fade)
        return OutroFit(reel_dur=line + fade, line=line, fade=float(fade),
                        tail=free_after(vocal_spans, line), rung="gap",
                        moved=(line + fade) - reel_dur, brief_len=brief_len, need=need)
    long_fade = max(float(fade), NO_GAP_FADE)
    nearest = _candidates(bars, reel_dur, bar_s, long_fade, music_dur,
                          grow_max, shrink_max)
    if nearest:
        line = pick(nearest, long_fade)
        return OutroFit(reel_dur=line + long_fade, line=line, fade=long_fade,
                        tail=free_after(vocal_spans, line), rung="no-gap",
                        moved=(line + long_fade) - reel_dur, brief_len=brief_len,
                        need=need)
    return unchanged
