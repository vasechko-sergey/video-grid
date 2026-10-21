"""The reel's cinematic look — a plateau vignette and a bookend fade, applied in
deliver's ONE encode (design docs/specs/2026-08-13-cinematic-look-design.md).

Pure: validation and string assembly. No IO, no ffmpeg. This module owns the mask
EXPRESSION and the chain ORDER; deliver owns the mask FILE and the second input it
rides on.

Why a mask and not ffmpeg's `vignette` filter: the built-in is a cos^4 lens model
with NO plateau, so on a 9:16 canvas it is a top-and-bottom dimmer, not a vignette
— measured, the sky band above a subject sits at 0.637 of centre at the default
angle while the corner is only at 0.413 (design §2.1). The mask below holds an
untouched plateau to 55% of the corner radius and darkens only past it, and a
one-shot mask + overlay renders it 26x cheaper than the equivalent per-frame geq
(design §2.2).

It also owns the shutter accent's white flash (design 2026-10-21 §4): the filters,
and the windows around each one the look gate must not sample."""
import math
from collections.abc import Sequence
from dataclasses import dataclass

from scripts.lib.color import TV_LO, TV_SPAN

LOOK_VIGNETTE_MAX = 0.6      # past this the corners read as a black border, not a vignette
LOOK_FADE_MAX = 2.0          # seconds per end; a 2.0s bookend already needs a >=4s reel
VIGNETTE_PLATEAU = 0.55      # identity radius, as a fraction of the corner distance
VIGNETTE_FALLOFF = 0.45      # 1 - PLATEAU: the rest of the ramp. Named, not inlined,
                             # because the mask expression divides by it and a 0 here
                             # would be a division by zero rather than "no falloff".
_CORNER = 1.41421356         # sqrt(2) — normalizes the corner distance to 1
FLASH_ALPHA = (0.85, 0.5, 0.2)   # the shutter flash's white, one frame at each opacity:
                                 # a convention from the 2026-10-20 research (a minimal
                                 # dip on the cut), not measured on a real run (design
                                 # 2026-10-21 §7)
FLASH_FRAMES = len(FLASH_ALPHA)
# White in the planes a master carries — 8-bit tv yuv420p (extract's range contract,
# color.refuse_ungradeable_plane): luma 235, chroma at its neutral 128.
_WHITE_Y, _NEUTRAL_C = TV_LO + TV_SPAN, 128


def _num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@dataclass
class LookSpec:
    """The reel's finish. Every number is 0 at its identity, and 0 means the
    filter is NOT EMITTED — the same convention color.white_balance uses, so a
    LookSpec() renders exactly what this repo rendered before looks existed.

    Distinct from None on its carriers: `EDL.look is None` means never authored,
    `EDL.look == LookSpec()` means authored as no look (the preset does not get to
    override it). A mood that MATCHES a preset fills the None from it; a mood that
    matches nothing leaves it None on purpose, because None is the only value that
    changes neither half of a brief-less run — filling it would either impose a
    picture fade nobody asked for or, at fade=0, switch off mix's audio bookend."""
    vignette: float = 0.0    # corner darkening as a fraction, 0 = off
    fade: float = 0.0        # closing fade seconds (and the opening one, unless fade_in), 0 = off
    # The OPENING fade, apart from the closing one. None = the same as `fade`, which is
    # what every LookSpec meant before the field existed — so an old EDL.json renders
    # unchanged. The second real run's hook opened on black under one shared `fade`
    # and all four reviews flagged it (retro 2026-10-16 S6).
    fade_in: float | None = None

    def __post_init__(self) -> None:
        if not _num(self.vignette) or not 0.0 <= self.vignette <= LOOK_VIGNETTE_MAX:
            raise ValueError(
                f"LookSpec.vignette must be a number in [0, {LOOK_VIGNETTE_MAX}] — it is how "
                f"far the CORNERS are darkened (0 = no vignette), and past the ceiling they "
                f"read as a black border rather than a falloff. Got {self.vignette!r}")
        if not _num(self.fade) or not 0.0 <= self.fade <= LOOK_FADE_MAX:
            raise ValueError(
                f"LookSpec.fade must be a number of seconds in [0, {LOOK_FADE_MAX}] — it is "
                f"the bookend fade at EACH end (0 = no fade), and a 2s bookend already needs "
                f"a 4s reel. Got {self.fade!r}")
        if self.fade_in is not None and (not _num(self.fade_in)
                                         or not 0.0 <= self.fade_in <= LOOK_FADE_MAX):
            raise ValueError(
                f"LookSpec.fade_in must be None (= the same as fade) or a number of seconds "
                f"in [0, {LOOK_FADE_MAX}] — the OPENING fade (0 = the reel opens on "
                f"picture). Got {self.fade_in!r}")
        self.vignette, self.fade = float(self.vignette), float(self.fade)
        if self.fade_in is not None:
            self.fade_in = float(self.fade_in)

    @property
    def head(self) -> float:
        """The opening fade's seconds."""
        return self.fade if self.fade_in is None else self.fade_in

    @property
    def tail(self) -> float:
        """The closing fade's seconds."""
        return self.fade

    @property
    def has_fade(self) -> bool:
        return self.head > 0.0 or self.tail > 0.0

    def describe(self) -> str:
        """One line for EDL.md and the edit_plan log. The opening is named apart only
        when it differs, so a look written before fade_in reads exactly as it did."""
        fades = (f"fade {self.tail:.2f}s" if self.head == self.tail
                 else f"fade in {self.head:.2f}s · out {self.tail:.2f}s")
        return f"vignette {self.vignette:.2f} · {fades}"

    @property
    def has_vignette(self) -> bool:
        """Whether deliver needs a second input. The one predicate that decides
        between the -vf and the -filter_complex shape."""
        return self.vignette > 0.0

    def to_dict(self) -> dict:
        d = {"vignette": self.vignette, "fade": self.fade}
        if self.fade_in is not None:       # absent when unauthored: old files stay byte-identical
            d["fade_in"] = self.fade_in
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "LookSpec":
        if not isinstance(d, dict):
            raise ValueError(f"look must be an object with vignette/fade fields, got "
                             f"{type(d).__name__} — see the edit-plan skill for the shape")
        return cls(vignette=d.get("vignette", 0.0), fade=d.get("fade", 0.0),
                   fade_in=d.get("fade_in"))


def mask_expr(vignette: float) -> str:
    """The geq that fills a one-frame RGBA vignette mask: black pixels whose ALPHA
    ramps from 0 on the plateau to 255*vignette at the corners, smoothstepped.

    Alpha and not luma: `overlay` composites through alpha and leaves the plateau
    exactly untouched, while `blend=all_mode=multiply` with a single-plane mask
    multiplies CHROMA as well and moves U/V by a measured mean of 63 (design §8.1).

    Refuses 0 rather than returning "": a caller with no vignette must not render a
    mask file at all, and a silently-empty expression would produce a fully
    transparent PNG plus a pointless second input."""
    if not _num(vignette) or not 0.0 < vignette <= LOOK_VIGNETTE_MAX:
        raise ValueError(
            f"mask_expr needs a vignette in (0, {LOOK_VIGNETTE_MAX}] — 0 means there is no "
            f"mask to render and the caller must skip it (LookSpec.has_vignette is that "
            f"test). Got {vignette!r}")
    ramp = (f"st(1,clip((hypot((X-W/2)/(W/2),(Y-H/2)/(H/2))/{_CORNER}"
            f"-{VIGNETTE_PLATEAU:.4f})/{VIGNETTE_FALLOFF:.4f},0,1))")
    return (f"format=rgba,geq=r=0:g=0:b=0:"
            f"a='{ramp};255*{vignette:.4f}*ld(1)*ld(1)*(3-2*ld(1))'")


def fade_args(fade: float, dur: float, fade_in: float | None = None) -> list[str]:
    """The fade pair, or [] at 0. `fade` is the closing fade and — unless `fade_in` sets
    the opening one apart — the opening fade too; each end is emitted only when it is
    non-zero. Refuses ends that would meet in the middle — two overlapping ramps
    multiply into a reel that never reaches full brightness, which looks like a broken
    encode rather than a style."""
    head = fade if fade_in is None else fade_in
    # Type check BEFORE the zero shortcut: False == 0 in Python, so an `if fade == 0`
    # placed first would accept a bool and return [] instead of refusing it. color.py's
    # black_point/shadow_red/dip all order these two the same way, for the same reason.
    for name, v in (("fade", fade), ("fade_in", head)):
        if not _num(v) or not 0.0 <= v <= LOOK_FADE_MAX:
            raise ValueError(
                f"fade_args needs {name} in [0, {LOOK_FADE_MAX}] seconds — the same band "
                f"LookSpec enforces, re-checked here because this function is public and a "
                f"direct caller does not go through the dataclass. Got {v!r}")
    if fade == 0 and head == 0:
        return []
    if not _num(dur) or dur <= 0:
        raise ValueError(f"fade_args needs a positive reel duration, got {dur!r}")
    if head + fade > dur:
        raise ValueError(
            f"a {head}s opening fade and a {fade}s closing fade on a {dur}s reel would "
            f"overlap in the middle — lower EDL.look's fades to at most {dur:.2f}s together "
            f"or cut a longer reel")
    out = []
    if head > 0:
        out.append(f"fade=t=in:st=0:d={head:.3f}")
    if fade > 0:
        out.append(f"fade=t=out:st={dur - fade:.3f}:d={fade:.3f}")
    return out


def _flash_inputs(times: Sequence[float], fps: float) -> None:
    """The shared refusal of flash_args and flash_windows: both turn a cut time into
    frame instants, and neither can do that without a real rate and a real time."""
    if not times:
        return
    if not _num(fps) or not math.isfinite(fps) or fps <= 0:
        raise ValueError(
            f"a shutter flash needs the reel's fps — a positive number, the flash being "
            f"{FLASH_FRAMES} frames long — got {fps!r}; deliver probes it off the master")
    for t in times:
        if not _num(t) or not math.isfinite(t) or t < 0:
            raise ValueError(
                f"a shutter flash's time must be a non-negative number of seconds on the "
                f"master (the cut it sits on), got {t!r}; build_reel derives it from the "
                f"probed clip durations")


def flash_args(times: Sequence[float], fps: float) -> list[str]:
    """The shutter accent's white flash (design 2026-10-21 §4): for each cut time,
    one `lutyuv` per frame of FLASH_ALPHA, moving every sample of every plane the
    opacity's fraction of the way to white: `a·white + (1−a)·picture`.

    A per-plane LUT and not `drawbox ... color=white@a:t=fill`, because drawbox blends
    a 4:2:0 chroma sample once per LUMA pixel it covers — four times — so its chroma
    alpha is 1−(1−a)^4. Measured over flat patches of seven colours, decoded to RGB:
    drawbox missed the blend by up to 67 codes in one channel (yellow's blue at
    a=0.5) where luma moved by `a`, and this LUT lands within 3.4 codes on every
    channel. `round` because lutyuv truncates the expression, which put every frame a
    code or two low (the proof: tests/integration/test_shutter.py).

    Frame k of a flash at `t` is the frame in [t + k/fps, t + (k+1)/fps). `between`
    is closed at both ends, so that window written as-is enables two frames when `t`
    sits on the frame grid; it is written shifted back half a frame instead —
    [t + (k-0.5)/fps, t + (k+0.5)/fps] — whose edges fall half a frame from any
    frame, so a cut time a hair off the grid (it is a sum of probed float durations)
    still enables exactly that one frame. The enable value is single-quoted because
    it carries commas, which would otherwise split the filter chain (CLAUDE.md); the
    plane expressions carry none and are quoted anyway, so an edit that adds one
    cannot split it either.

    [] with no times: no filter, so a delivery with no accent keeps its argv."""
    _flash_inputs(times, fps)
    out = []
    for t in times:
        for k, a in enumerate(FLASH_ALPHA):
            lo, hi = max(0.0, t + (k - 0.5) / fps), t + (k + 0.5) / fps
            y, c = (f"'round(val+({w:g}-val)*{a:g})'" for w in (_WHITE_Y, _NEUTRAL_C))
            out.append(f"lutyuv=y={y}:u={c}:v={c}:"
                       f"enable='between(t,{lo:.6f},{hi:.6f})'")
    return out


def flash_windows(times: Sequence[float], fps: float) -> list[tuple[float, float]]:
    """The span around each flash that a delivered-vs-master comparison must not
    sample: [t - 1/fps, t + (FLASH_FRAMES + 1)/fps), a whole frame of margin either
    side of the flashed frames, because the look gate picks frames by rounding a time
    to a frame number and the flash exists only in the delivered file."""
    _flash_inputs(times, fps)
    return [(t - 1 / fps, t + (FLASH_FRAMES + 1) / fps) for t in times]


def clear_of_flash(t: float, windows: Sequence[tuple[float, float]]) -> float:
    """`t` itself when no window holds it, else the end of the window that does —
    repeated, since that end can sit inside the next flash's window. The one
    membership rule (lo <= t < hi) every look-gate sample is judged by: a time is
    clear exactly when this returns it unchanged."""
    moved = True
    while moved:
        moved = False
        for lo, hi in windows:
            if lo <= t < hi:
                t, moved = hi, True
    return t


def flash_free(lo: float, hi: float,
               windows: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """The parts of [lo, hi] no window holds, in time order — the same membership
    rule as clear_of_flash. Empty when flashes cover the whole span."""
    parts, at = [], lo
    for w_lo, w_hi in sorted(windows):
        if w_hi <= at or w_lo >= hi:
            continue
        if w_lo > at:
            parts.append((at, w_lo))
        at = max(at, w_hi)
    if at < hi:
        parts.append((at, hi))
    return parts


def chain(spec: "LookSpec | None", dur: float, titles: str = "",
          flashes: Sequence[str] = ()) -> list[str]:
    """The video filters deliver applies AFTER the vignette overlay, in the ONE
    correct order: the shutter flashes (flash_args' filters), the title drawtext,
    then the bookend fade.

    The fade is last and that is MEASURED, not a preference: with it last the first
    delivered frame reads 0.0 — the title goes to black with the picture. Put it
    before the drawtext and the title burns on at full brightness over a black
    frame (design §4). The flashes come first for the same reason: a fade after them
    still darkens a flash at t=0, and a title drawn after them stays legible through
    the white.

    The vignette overlay is deliberately NOT in this list: it needs a second input,
    so deliver wires it by label and prepends it. An empty list means deliver emits
    no video-filter slot at all, which is what keeps a look-less delivery's argv
    byte-identical to what it was before this module existed."""
    parts: list[str] = list(flashes)
    if titles:
        parts.append(titles)
    if spec is not None:
        parts.extend(fade_args(spec.fade, dur, fade_in=spec.fade_in))
    return parts
