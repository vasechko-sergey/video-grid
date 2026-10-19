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
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

# Measured: a declared vignette of 0.10 / 0.30 / 0.60 dropped the corner-over-centre
# ratio by 0.0844 / 0.2576 / 0.5209 — 0.84 to 0.87 of what was asked for. Requiring
# half the declared depth leaves a 1.7x margin below the worst measured case, which is
# the point: this proves the effect is THERE, it does not grade it.
VIGNETTE_MIN_FRACTION = 0.5
# Measured: a 0.5s fade took the master's 75.28-mean first frame to exactly 0.00. Valid
# ONLY for fade-IN's t=0, which is frame-exact — n=0 always sits exactly at t=0, so the
# ramp has not started and the frame must read black with no slack for quantization.
FADE_BLACK_MAX = 2.0
# fade-OUT's LAST frame is NOT exact at the ramp's true end the way fade-in's t=0 is
# exact at its start: unless the file's duration happens to land precisely on a frame
# boundary, there is no frame AT the end, so the last decodable one keeps a real
# residual even on a correctly-rendered fade. Measured on the reel fixture (fade=0.5s,
# 30fps, master ~52.47 mean luma, tests/integration/test_look.py's own reference):
# last frame 3.303, a residual FRACTION of 0.063 against a linear ramp's own
# prediction of (1/fps)/fade = 0.067 (agrees to within 6%) — so FADE_BLACK_MAX reused
# unchanged here refuses that CORRECT render (reproduced directly against this
# fixture), and it gets worse at a shorter fade or a lower fps, where the SAME
# one-frame shortfall is a larger share of the ramp (a legal 0.3s fade at 24fps: ~14%
# residual by the same formula). Checked dynamically instead of against a fixed pixel
# value: at most one delivered-fps frame period of the ramp can be missing, so the
# residual cannot exceed roughly `master * (1/fps)/fade` — this margin multiplies
# that bound for curve-shape and encoder-rounding slack, while a genuine non-render
# (residual ~= the full master brightness) still fails by a wide margin at any legal
# fade/fps combination.
FADE_OUT_RESIDUAL_MARGIN = 3.0
# Below this, the bar computed from FADE_OUT_RESIDUAL_MARGIN has lost its
# discriminating power (coordinator re-review, found on the shipped code): at
# residual_frac == 1.0 the bar IS the master's own brightness, and d0 <= m0 holds
# for any fade-out at all — a delivery cannot be brighter than its master — so a
# COMPLETELY UNRENDERED fade-out (d0 == m0) would report "pass". Reproduced:
# fade=0.1s/30fps clamps residual_frac to 1.0 (fade <= 3/fps triggers the outer
# min in _fade_edge), and an unrendered delivery passes. Same "half" reasoning
# VIGNETTE_MIN_FRACTION already uses two constants up: a bar demanding the
# delivered frame lose at least half the master's brightness is still a real
# predicate (a genuine non-render, d0 ~= m0, fails it by a wide margin); a bar
# above that is not. Algebraically this fires whenever fade <= 6/fps, at ANY fps —
# comfortably below every mood preset's own fade (>= 0.3s: at fps=24, the worst
# realistic floor, the switch-over is 0.25s), so it changes nothing for a
# realistically-authored reel and only guards a hand-authored fade shorter than
# that. Does NOT change FADE_OUT_RESIDUAL_MARGIN itself, or any pass/fail verdict
# where the bar still discriminates.
FADE_OUT_MIN_POWER = 0.5
# Below these the source cannot discriminate: a reel that opens on black is already
# black at t=0, and corners that are already dark cannot be darkened. Both report
# not-checked and pass — an honest hole, named in design §10.4.
FADE_SOURCE_MIN = 8.0
VIGNETTE_FLOOR = 8.0
# The vignette's sampling boxes, as a divisor of each dimension. look.VIGNETTE_PLATEAU
# is 0.55 of the CORNER radius, so a box 1/10 of each side sits well outside the
# plateau and the 2/10 centre box well inside it — neither straddles the falloff.
BOX_DIV = 10
# Titles. The per-pixel bar, in codes, is what does the discriminating: measured over
# 110 ordered frame pairs of a real delivered reel re-encoded with NO title, the worst
# single pixel reached 30 without a look and 24 under a max-depth (0.60) vignette, and
# not one pair produced a qualifying pixel. 40 sits 1.33x above that worst observation.
# Real footage deliberately — the synthetic corpus peaked at 2, which would have
# justified a far lower bar and a far weaker gate (design 2026-08-19 §3.1).
TITLE_INK_DELTA = 40
# With the no-title side at exactly zero, this floor is not separating signal from
# noise — TITLE_INK_DELTA already did. It absorbs a stray cluster on footage rougher
# than any measured. 0.02% is 51 pixels of the measured band; the smallest legitimate
# title (one period) produced 0.0384%, "hi" 0.1717%, a full line 2.9966% (§3.2).
TITLE_MIN_FRACTION = 0.0002
# Padding around titles.ink_extent, in font sizes each side. Measured to contain every
# style: bold-box's box and outline-bold's stroke run 9 rows above and 15 below the
# predicted text box, well inside 0.6 font sizes. A band too TALL only dilutes the
# fraction; a band that misses the ink is a false fail on a no-waiver gate (§3.3).
TITLE_BAND_PAD = 0.6


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


@dataclass(frozen=True)
class TitleProbe:
    """One title's sampling material, or `skipped` naming why there is none.

    `inside` is the (master, delivered) pair at a time inside the title's window;
    each `witnesses` entry is the same pair at a time NO title covers. Both come from
    deliver, which owns the timestamps — this module never touches a path.

    `band` is (lo, hi) row indices in the delivered frame, from titles.ink_extent
    padded by TITLE_BAND_PAD. Rows and not fractions because by this point the frame's
    real height is known and the arrays are about to be sliced by it."""
    label: str
    band: tuple[int, int]
    inside: tuple[np.ndarray, np.ndarray] | None = None
    witnesses: tuple[tuple[np.ndarray, np.ndarray], ...] = ()
    skipped: str = ""


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


def _fade_edge(m: np.ndarray, d: np.ndarray, *, check: str, edge: str,
               fade: float = 0.0, fps: float = 0.0) -> LookFinding:
    """One end of the bookend fade. `edge` is "first" (t=0, fade-in) or "last" (the
    delivery's own final decodable frame, fade-out).

    Split into two checks, one per edge (design §7, amended — final review I-3): a
    single "fade" finding that only ever looked at t=0 read as "the fade rendered"
    when only half the bookend had been proven. The two edges are NOT
    interchangeable evidence — a fade-out can fail while fade-in passes cleanly:
    `deliver` computes the fade-out's start from the MASTER's duration, but the
    audio mux's `-shortest` can truncate the DELIVERED file short of that point, so
    the fade-out never reaches black in what actually shipped while fade-in (which
    none of that touches) still does.

    The two edges are NOT judged by the same predicate, either (a second amendment
    to design §7, found only by running this against a real render): `fade` and
    `fps` are unused for `edge == "first"` (t=0 is frame-exact, so FADE_BLACK_MAX
    alone is correct) but size the fade-out's own quantization slack for
    `edge == "last"` — see FADE_OUT_RESIDUAL_MARGIN.

    `edge == "last"` carries a THIRD not-checked arm beyond the FADE_SOURCE_MIN one
    below (design §7/§10, amended — coordinator re-review): at a short enough fade
    relative to fps, the relative bar FADE_OUT_RESIDUAL_MARGIN computes approaches
    the master's own brightness, and `d0 <= expected` would then hold for ANY
    fade-out — rendered or not — since a delivery cannot be brighter than its
    master. See FADE_OUT_MIN_POWER.
    """
    m0 = float(_rgb(m, f"{edge}_master").mean())
    d0 = float(_rgb(d, f"{edge}_delivered").mean())
    _same_shape(m, d)
    if m0 < FADE_SOURCE_MIN:
        return LookFinding(
            check=check, status="not-checked",
            detail=(f"the master's own {edge} frame averages {m0:.2f}, under the "
                    f"{FADE_SOURCE_MIN} this check needs — the reel already "
                    f"{'opens' if edge == 'first' else 'ends'} on black, so a black "
                    f"{edge} delivered frame proves nothing"),
            measured=m0, expected=FADE_SOURCE_MIN)
    if edge == "first":
        ok, expected = d0 <= FADE_BLACK_MAX, FADE_BLACK_MAX
        detail = (f"a fade-in must start from black, but the delivery's first frame "
                  f"averages {d0:.2f} against the master's {m0:.2f} — the fade did "
                  f"not render" if not ok else f"first frame {m0:.2f} -> {d0:.2f}")
        return LookFinding(check=check, status="pass" if ok else "fail", detail=detail,
                           measured=d0, expected=expected)
    # edge == "last": no frame sits exactly at the ramp's true end unless the file's
    # duration happens to land on a frame boundary, so the last decodable frame keeps
    # a real residual — bounded by at most one frame period of unfinished ramp,
    # `master * (1/fps)/fade`, with FADE_OUT_RESIDUAL_MARGIN of slack above it.
    if not (fade > 0 and fps > 0):
        raise ValueError(f"lookcheck._fade_edge: the last edge needs fade > 0 and "
                         f"fps > 0 to size its quantization slack, got fade={fade!r} "
                         f"fps={fps!r}")
    residual_frac = min(1.0, (1.0 / fps) / fade * FADE_OUT_RESIDUAL_MARGIN)
    if residual_frac >= FADE_OUT_MIN_POWER:
        # The bar itself has no discriminating power left (coordinator re-review):
        # at residual_frac == 1.0 it is the master's own brightness, and d0 <= m0
        # holds for ANY fade-out — a delivery cannot be brighter than its master —
        # so a completely unrendered one would report "pass". Reported as
        # not-checked instead, the same shape FADE_SOURCE_MIN's arm above already
        # uses for a different reason a bar cannot discriminate.
        return LookFinding(
            check=check, status="not-checked",
            detail=(f"at {fade}s and {fps:.4g}fps, one frame period is "
                    f"{residual_frac:.2f} of the master's own last-frame "
                    f"brightness — too large a share of the ramp for the last "
                    f"decodable frame to prove anything either way (needs under "
                    f"{FADE_OUT_MIN_POWER}); lengthen the fade or deliver at a "
                    f"higher rate"),
            measured=residual_frac, expected=FADE_OUT_MIN_POWER)
    expected = m0 * residual_frac
    ok = d0 <= expected
    detail = (f"a fade-out must reach black, but the delivery's last frame averages "
              f"{d0:.2f} against the master's {m0:.2f} (allowing up to {expected:.2f} "
              f"for one {fps:.4g}fps frame period of unfinished {fade}s ramp) — the "
              f"fade did not render" if not ok else
              f"last frame {m0:.2f} -> {d0:.2f} (within {expected:.2f})")
    return LookFinding(check=check, status="pass" if ok else "fail", detail=detail,
                       measured=d0, expected=expected)


def title_evidence(inside: tuple[np.ndarray, np.ndarray],
                   witness: tuple[np.ndarray, np.ndarray],
                   band: tuple[int, int]) -> float:
    """Share of the band's pixels carrying ink the MASTER does not explain.

    The delivered file is compared against ITSELF at two times, minus the master's own
    change between the same two — not against the master at one time. That is not a
    style choice, it is the only version that works: measured, a max-depth vignette
    alone moves 9.58% of a bottom band's pixels past a 60-code master-vs-delivered bar,
    MORE than a real title does (design 2026-08-19 §2.1/§2.2). Here a transform applied
    at both times cancels, picture motion cancels, and ink present at one time and
    absent at the other has no counterpart in the master and survives.

    Worst channel, not their mean: a title in a saturated colour moves one channel hard
    and the others barely, and averaging would divide that evidence by three."""
    lo, hi = band
    (m_in, d_in), (m_out, d_out) = inside, witness
    for f, what in ((m_in, "a master frame"), (d_in, "a delivered frame"),
                    (m_out, "a master frame"), (d_out, "a delivered frame")):
        _rgb(f, what)
    _same_shape(m_in, d_in)
    _same_shape(m_out, d_out)
    _same_shape(m_in, m_out)
    if not 0 <= lo < hi <= m_in.shape[0]:
        raise ValueError(f"lookcheck: a title band must be a non-empty row range inside "
                         f"the frame's {m_in.shape[0]} rows, got {band}")
    a = np.abs(d_in[lo:hi].astype(np.int16) - d_out[lo:hi].astype(np.int16))
    b = np.abs(m_in[lo:hi].astype(np.int16) - m_out[lo:hi].astype(np.int16))
    return float(((a - b).max(axis=2) > TITLE_INK_DELTA).mean())


def evaluate_titles(probes: Sequence[TitleProbe]) -> list[LookFinding]:
    """One finding per declared title. `not-checked` is a real outcome here for the
    same reason it is for the vignette's black-corner floor: a reel whose titles cover
    every instant has no witness frame, and a title lying entirely inside a bookend
    fade has no in-window frame bright enough to read — measured, a sample at alpha
    0.10 scores 0.0000% on a correctly rendered title (design 2026-08-19 §4). Saying so
    beats a bar that pretends."""
    out: list[LookFinding] = []
    for p in probes:
        if p.skipped or p.inside is None or not p.witnesses:
            out.append(LookFinding(
                check=f"titles:{p.label}", status="not-checked",
                detail=(p.skipped or "no usable frame pair was sampled for this title"),
                measured=0.0, expected=TITLE_MIN_FRACTION))
            continue
        # Best of the witnesses, not the first: measured, one bold-box title scored
        # 3.53% against a dark witness frame and 18.94% against a bright one. Any
        # title-free moment is a valid witness, so one that sees the ink is enough.
        frac = max(title_evidence(p.inside, w, p.band) for w in p.witnesses)
        ok = frac >= TITLE_MIN_FRACTION
        out.append(LookFinding(
            check=f"titles:{p.label}", status="pass" if ok else "fail",
            detail=(f"{100 * frac:.4f}% of the title's band rows {p.band[0]}-{p.band[1]} "
                    f"carry ink the master does not explain"
                    + ("" if ok else
                       f", under the {100 * TITLE_MIN_FRACTION:.2f}% floor — the title "
                       f"did not render, or rendered where this band is not looking")),
            measured=frac, expected=TITLE_MIN_FRACTION))
    return out


def evaluate(mid_master: list[np.ndarray], mid_delivered: list[np.ndarray],
             first_master: np.ndarray | None, first_delivered: np.ndarray | None,
             last_master: np.ndarray | None, last_delivered: np.ndarray | None,
             *, vignette: float = 0.0, fade: float = 0.0, fps: float = 0.0,
             titles: Sequence[TitleProbe] = (),
             fade_in: float | None = None) -> list[LookFinding]:
    """Judge a delivery against its master. Empty list = nothing was declared, so
    there is nothing to prove and no ffmpeg was worth spending.

    `mid_*` are paired frames from the reel's interior. `first_*`/`last_*` are the
    frames at t=0 and the delivery's own last decodable frame respectively, needed
    only when a fade was declared — the fade is a BOOKEND (`look.fade_args` emits
    both `fade=t=in` and `fade=t=out`), so both ends must be supplied together or
    not at all; see `_fade_edge`. `fps` is the DELIVERED file's own frame rate,
    needed only alongside `fade`: it sizes how much of the fade-out's ramp the last
    decodable frame can still be short of (`FADE_OUT_RESIDUAL_MARGIN`) — fade-in's
    t=0 needs no such slack, since it is frame-exact regardless of fps.

    `titles` is one TitleProbe per declared title, each carrying its own frames: a
    title occupies a band and a window nothing else here shares, so it cannot be
    judged from the interior samples the other two checks reuse. Empty = no titles
    were declared, which is not the same as a title that could not be sampled — that
    one arrives as a probe with `skipped` set and reports not-checked.

    `fade` is the closing fade and, unless `fade_in` sets it apart, the opening one
    (LookSpec's convention). Each end is judged — and its two frames required — only
    when it is declared: a reel that opens on picture has no fade-in to prove (retro
    2026-10-16 S6).
    """
    head = fade if fade_in is None else fade_in
    if not (vignette or fade or head or titles):
        return []
    if not mid_master or len(mid_master) != len(mid_delivered):
        raise ValueError(f"lookcheck.evaluate needs the same number of master and "
                         f"delivered frames, got {len(mid_master)} and "
                         f"{len(mid_delivered)}")
    for m, d in zip(mid_master, mid_delivered):
        _same_shape(_rgb(m, "a master frame"), _rgb(d, "a delivered frame"))
    out: list[LookFinding] = []

    out.extend(evaluate_titles(titles))

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

    if head or fade:
        need = {}
        if head:
            need.update(first_master=first_master, first_delivered=first_delivered)
        if fade:
            need.update(last_master=last_master, last_delivered=last_delivered)
        missing = [n for n, v in need.items() if v is None]
        if missing or not fps:
            raise ValueError(
                f"lookcheck.evaluate needs both frames of every DECLARED fade end AND fps "
                f"(the delivered file's own rate) — the master's and the delivery's first "
                f"frame (t=0) for a fade-in, their last frames for a fade-out: checking "
                f"only one end of a bookend would report 'pass' while the other never "
                f"reached black. fps sizes the fade-out's own quantization slack (§7, "
                f"amended) — without it a correctly-rendered short fade cannot be told "
                f"from a genuine miss. Missing: {missing}" + ("" if fps else " + fps"))
        if head:
            out.append(_fade_edge(first_master, first_delivered, check="fade-in",
                                  edge="first", fade=head, fps=fps))
        if fade:
            out.append(_fade_edge(last_master, last_delivered, check="fade-out",
                                  edge="last", fade=fade, fps=fps))
    return out
