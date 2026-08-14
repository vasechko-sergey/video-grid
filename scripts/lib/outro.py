"""Outro fit — where the reel's music stops (design
docs/specs/2026-08-14-music-outro-fit-design.md).

Pure: numbers in, one OutroFit out. No audio IO, no ffmpeg, no librosa. The whole
slice reduces to picking ONE number, the reel's length, because mix already fades
over [dur - fade, dur] — so a reel of `line + fade` starts its fade exactly on the
bar line and no ffmpeg stage changes at all (design §1)."""
from collections.abc import Sequence
from dataclasses import dataclass

BAR_BEATS = 4       # 4/4 assumed — beats.py's downbeat detector reads this too (§11.3)
TAIL_MIN = 0.5      # vocal-free seconds a boundary must leave. THE PROJECT OWNER'S
                    # ASSUMPTION, not a measurement or a citation (§11.1) — one constant
                    # in one place precisely so re-tuning is a one-line change.
NO_GAP_FADE = 1.5   # the longer fade rung 2 falls back to. Taste, not a measurement (§11.2)
MIN_LAST = 1.0      # the last episode may not be shrunk below this. A floor, not a
                    # finding (§11.7): without it a one-bar step down can leave a 2.5s
                    # closing shot at 0.3s, which is a glitch, not an ending.
RUNGS = ("gap", "no-gap", "unchanged")
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

    def __post_init__(self) -> None:
        if self.rung not in RUNGS:
            raise ValueError(f"OutroFit.rung must be one of {RUNGS}, got {self.rung!r}")

    def to_dict(self) -> dict:
        return {"reel_dur": self.reel_dur, "line": self.line, "fade": self.fade,
                "tail": self.tail, "rung": self.rung, "moved": self.moved,
                "brief_len": self.brief_len}

    @classmethod
    def from_dict(cls, d: dict) -> "OutroFit":
        if not isinstance(d, dict):
            raise ValueError(f"OutroFit.from_dict: expected an object, got "
                             f"{type(d).__name__} — re-run edit_plan build")
        return cls(reel_dur=d.get("reel_dur", 0.0), line=d.get("line"),
                   fade=d.get("fade", 0.0), tail=d.get("tail", 0.0),
                   rung=d.get("rung", "unchanged"), moved=d.get("moved", 0.0),
                   brief_len=d.get("brief_len"))


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

    The ladder (design §5): a line with `max(TAIL_MIN, fade)` of vocal-free space after
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
    unchanged = OutroFit(reel_dur=reel_dur, line=None, fade=float(fade), tail=0.0,
                         rung="unchanged", moved=0.0, brief_len=brief_len)
    if not bars:
        return unchanged

    def pick(cands, f):
        ref = brief_len if brief_len is not None else reel_dur
        return min(cands, key=lambda line: (abs((line + f) - ref), line))

    need = max(TAIL_MIN, float(fade))
    gapped = [line for line in _candidates(bars, reel_dur, bar_s, fade, music_dur,
                                           grow_max, shrink_max)
              if free_after(vocal_spans, line) >= need - _EPS]
    if gapped:
        line = pick(gapped, fade)
        return OutroFit(reel_dur=line + fade, line=line, fade=float(fade),
                        tail=free_after(vocal_spans, line), rung="gap",
                        moved=(line + fade) - reel_dur, brief_len=brief_len)
    long_fade = max(float(fade), NO_GAP_FADE)
    nearest = _candidates(bars, reel_dur, bar_s, long_fade, music_dur,
                          grow_max, shrink_max)
    if nearest:
        line = pick(nearest, long_fade)
        return OutroFit(reel_dur=line + long_fade, line=line, fade=long_fade,
                        tail=free_after(vocal_spans, line), rung="no-gap",
                        moved=(line + long_fade) - reel_dur, brief_len=brief_len)
    return unchanged
