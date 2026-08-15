"""Did the delivered reel actually carry the look it declared? (design
docs/specs/2026-08-15-frame-probe-look-gate-design.md §7)

check_reel measures the MASTER. deliver then encodes the vignette, the bookend fade
and the titles into a file no gate reads — so a filter that silently fails to reach
the chain ships. This measures the delivered pixels against the master's at the same
timestamps and says whether the declared effect is in them.

Pure: numpy arrays in, findings out. No ffmpeg, no paths — deliver samples the frames
and deliver decides what to do with the verdict.

Every threshold below is a module constant and NOT a parameter, for the reason
naturalness.py states: a threshold a caller can pass is a threshold a subagent can
pass, and a no-waiver gate whose bar is an argument has no bar.
"""
from dataclasses import dataclass

import numpy as np

# Measured: a declared vignette of 0.10 / 0.30 / 0.60 dropped the corner-over-centre
# ratio by 0.0844 / 0.2576 / 0.5209 — 0.84 to 0.87 of what was asked for. Requiring
# half the declared depth leaves a 1.7x margin below the worst measured case, which is
# the point: this proves the effect is THERE, it does not grade it.
VIGNETTE_MIN_FRACTION = 0.5
# Measured: a 0.5s fade took the master's 75.28-mean first frame to exactly 0.00.
FADE_BLACK_MAX = 2.0
# Below these the source cannot discriminate: a reel that opens on black is already
# black at t=0, and corners that are already dark cannot be darkened. Both report
# not-checked and pass — an honest hole, named in design §10.4.
FADE_SOURCE_MIN = 8.0
VIGNETTE_FLOOR = 8.0
# The vignette's sampling boxes, as a divisor of each dimension. look.VIGNETTE_PLATEAU
# is 0.55 of the CORNER radius, so a box 1/10 of each side sits well outside the
# plateau and the 2/10 centre box well inside it — neither straddles the falloff.
BOX_DIV = 10


@dataclass(frozen=True)
class LookFinding:
    """One check's verdict. `status` is "pass" | "fail" | "not-checked" — the third is
    a real outcome, not a synonym for pass: it says the source could not discriminate
    and nothing was proven."""
    check: str
    status: str
    detail: str
    measured: float
    expected: float

    def to_dict(self) -> dict:
        return {"check": self.check, "status": self.status, "detail": self.detail,
                "measured": round(self.measured, 4), "expected": round(self.expected, 4)}


def _rgb(f: object, what: str) -> np.ndarray:
    if not (isinstance(f, np.ndarray) and f.ndim == 3 and f.shape[2] == 3
            and f.dtype == np.uint8):
        got = f"shape={f.shape}, dtype={f.dtype}" if isinstance(f, np.ndarray) else type(f).__name__
        raise ValueError(f"lookcheck: {what} must be an HxWx3 uint8 RGB array, got {got} "
                         f"— sample frames with assembly.frames_rgb before calling")
    return f


def _same_shape(a: np.ndarray, b: np.ndarray) -> None:
    """Refuse a delivery that is not the master's geometry — the two checks below both
    compare paired frames, and a resized delivery would compare different pictures."""
    if a.shape != b.shape:
        raise ValueError(f"lookcheck: frames must be the same shape to compare, got "
                         f"{a.shape} and {b.shape} — the delivery was resized relative "
                         f"to the master, which no ExportProfile should do")


def corner_centre(f: np.ndarray) -> tuple[float, float]:
    """(mean of the four corner boxes, mean of the centre box). Their RATIO is what
    the vignette check compares between master and delivery, so picture content
    cancels and only the darkening survives."""
    _rgb(f, "frame")
    h, w = f.shape[:2]
    bh, bw = max(1, h // BOX_DIV), max(1, w // BOX_DIV)
    corners = [f[:bh, :bw], f[:bh, -bw:], f[-bh:, :bw], f[-bh:, -bw:]]
    centre = f[h // 2 - bh:h // 2 + bh, w // 2 - bw:w // 2 + bw]
    return float(np.mean([float(c.mean()) for c in corners])), float(centre.mean())


def evaluate(mid_master: list[np.ndarray], mid_delivered: list[np.ndarray],
             first_master: np.ndarray | None, first_delivered: np.ndarray | None,
             *, vignette: float = 0.0, fade: float = 0.0,
             titles: bool = False) -> list[LookFinding]:
    """Judge a delivery against its master. Empty list = nothing was declared, so
    there is nothing to prove and no ffmpeg was worth spending.

    `mid_*` are paired frames from the reel's interior; `first_*` are the frames at
    t=0, needed only when a fade was declared.
    """
    if not (vignette or fade or titles):
        return []
    if not mid_master or len(mid_master) != len(mid_delivered):
        raise ValueError(f"lookcheck.evaluate needs the same number of master and "
                         f"delivered frames, got {len(mid_master)} and "
                         f"{len(mid_delivered)}")
    for m, d in zip(mid_master, mid_delivered):
        _same_shape(_rgb(m, "a master frame"), _rgb(d, "a delivered frame"))
    out: list[LookFinding] = []

    if titles:
        # Titles have no check this slice (design §11). Returning nothing would read as
        # "the gate looked and was satisfied" — this records the absence instead.
        # Unconditional, NOT `titles and not (vignette or fade)`: titles ride beside a
        # vignette or a fade in the common case, and a defect that killed only the
        # drawtext stage while the vignette still rendered would otherwise ship attested
        # with no trace that titles were ever declared. That is the exact bug class this
        # gate exists for.
        out.append(LookFinding(
            check="titles", status="not-checked",
            detail="titles were declared and this slice has no check for them: locating "
                   "a title's band needs titles.y_exprs plus the safe-zone table (design "
                   "§11). Nothing here says whether the text rendered",
            measured=0.0, expected=0.0))

    if vignette:
        mid = len(mid_master) // 2
        mc, mp = corner_centre(mid_master[mid])
        dc, dp = corner_centre(mid_delivered[mid])
        if mc < VIGNETTE_FLOOR:
            out.append(LookFinding(
                check="vignette", status="not-checked",
                detail=(f"the master's own corners average {mc:.2f}, under the "
                        f"{VIGNETTE_FLOOR} this check needs — you cannot darken black, "
                        f"so nothing here proves the vignette rendered either way"),
                measured=mc, expected=VIGNETTE_FLOOR))
        else:
            mr = mc / mp if mp else 0.0
            dr = dc / dp if dp else 0.0
            drop = 1.0 - (dr / mr) if mr else 0.0
            need = VIGNETTE_MIN_FRACTION * vignette
            out.append(LookFinding(
                check="vignette",
                status="pass" if drop >= need else "fail",
                detail=(f"a vignette of {vignette} should drop the corner-over-centre "
                        f"ratio by about {0.85 * vignette:.4f} (measured 0.84-0.87x of "
                        f"the declared depth); the delivery dropped it {drop:.4f}, under "
                        f"the {need:.4f} floor — the vignette did not render, or rendered "
                        f"far shallower than declared"
                        if drop < need else
                        f"corner-over-centre ratio {mr:.4f} -> {dr:.4f}, a drop of {drop:.4f}"),
                measured=drop, expected=need))

    if fade:
        if first_master is None or first_delivered is None:
            raise ValueError("lookcheck.evaluate needs the master's and the delivery's "
                             "first frame to judge a fade — sample t=0 from both and "
                             "pass them, or do not declare a fade")
        m0 = float(_rgb(first_master, "first_master").mean())
        d0 = float(_rgb(first_delivered, "first_delivered").mean())
        _same_shape(first_master, first_delivered)
        if m0 < FADE_SOURCE_MIN:
            out.append(LookFinding(
                check="fade", status="not-checked",
                detail=(f"the master's own first frame averages {m0:.2f}, under the "
                        f"{FADE_SOURCE_MIN} this check needs — the reel already opens on "
                        f"black, so a black first delivered frame proves nothing"),
                measured=m0, expected=FADE_SOURCE_MIN))
        else:
            out.append(LookFinding(
                check="fade",
                status="pass" if d0 <= FADE_BLACK_MAX else "fail",
                detail=(f"a {fade}s fade-in must start from black, but the delivery's "
                        f"first frame averages {d0:.2f} against the master's {m0:.2f} "
                        f"— the fade did not render"
                        if d0 > FADE_BLACK_MAX else
                        f"first frame {m0:.2f} -> {d0:.2f}"),
                measured=d0, expected=FADE_BLACK_MAX))
    return out
