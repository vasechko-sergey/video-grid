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
(design §2.2)."""
from dataclasses import dataclass

LOOK_VIGNETTE_MAX = 0.6      # past this the corners read as a black border, not a vignette
LOOK_FADE_MAX = 2.0          # seconds per end; a 2.0s bookend already needs a >=4s reel
VIGNETTE_PLATEAU = 0.55      # identity radius, as a fraction of the corner distance
VIGNETTE_FALLOFF = 0.45      # 1 - PLATEAU: the rest of the ramp. Named, not inlined,
                             # because the mask expression divides by it and a 0 here
                             # would be a division by zero rather than "no falloff".
_CORNER = 1.41421356         # sqrt(2) — normalizes the corner distance to 1


def _num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@dataclass
class LookSpec:
    """The reel's finish. Both fields are 0 at their identity, and 0 means the
    filter is NOT EMITTED — the same convention color.white_balance uses, so a
    LookSpec() renders exactly what this repo rendered before looks existed.

    Distinct from None on its carriers: `EDL.look is None` means never authored
    (the mood preset fills it), `EDL.look == LookSpec()` means authored as no look
    (the preset does not get to override it)."""
    vignette: float = 0.0    # corner darkening as a fraction, 0 = off
    fade: float = 0.0        # bookend fade seconds per end, 0 = off

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
        self.vignette, self.fade = float(self.vignette), float(self.fade)

    @property
    def has_vignette(self) -> bool:
        """Whether deliver needs a second input. The one predicate that decides
        between the -vf and the -filter_complex shape."""
        return self.vignette > 0.0

    def to_dict(self) -> dict:
        return {"vignette": self.vignette, "fade": self.fade}

    @classmethod
    def from_dict(cls, d: dict) -> "LookSpec":
        if not isinstance(d, dict):
            raise ValueError(f"look must be an object with vignette/fade fields, got "
                             f"{type(d).__name__} — see the edit-plan skill for the shape")
        return cls(vignette=d.get("vignette", 0.0), fade=d.get("fade", 0.0))


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


def fade_args(fade: float, dur: float) -> list[str]:
    """The bookend pair, or [] at 0. Refuses a fade that would meet itself in the
    middle — two overlapping ramps multiply into a reel that never reaches full
    brightness, which looks like a broken encode rather than a style."""
    # Type check BEFORE the zero shortcut: False == 0 in Python, so an `if fade == 0`
    # placed first would accept a bool and return [] instead of refusing it. color.py's
    # black_point/shadow_red/dip all order these two the same way, for the same reason.
    if not _num(fade) or not 0.0 <= fade <= LOOK_FADE_MAX:
        raise ValueError(
            f"fade_args needs a fade in [0, {LOOK_FADE_MAX}] seconds — the same band "
            f"LookSpec enforces, re-checked here because this function is public and a "
            f"direct caller does not go through the dataclass. Got {fade!r}")
    if fade == 0:
        return []
    if not _num(dur) or dur <= 0:
        raise ValueError(f"fade_args needs a positive reel duration, got {dur!r}")
    if 2 * fade > dur:
        raise ValueError(
            f"a {fade}s fade at each end of a {dur}s reel would overlap in the middle — "
            f"lower EDL.look.fade to at most {dur / 2:.2f}s or cut a longer reel")
    return [f"fade=t=in:st=0:d={fade:.3f}",
            f"fade=t=out:st={dur - fade:.3f}:d={fade:.3f}"]


def chain(spec: "LookSpec | None", dur: float, titles: str = "") -> list[str]:
    """The video filters deliver applies AFTER the vignette overlay, in the ONE
    correct order: the title drawtext, then the bookend fade.

    The fade is last and that is MEASURED, not a preference: with it last the first
    delivered frame reads 0.0 — the title goes to black with the picture. Put it
    before the drawtext and the title burns on at full brightness over a black
    frame (design §4).

    The vignette overlay is deliberately NOT in this list: it needs a second input,
    so deliver wires it by label and prepends it. An empty list means deliver emits
    no video-filter slot at all, which is what keeps a look-less delivery's argv
    byte-identical to what it was before this module existed."""
    parts: list[str] = []
    if titles:
        parts.append(titles)
    if spec is not None:
        parts.extend(fade_args(spec.fade, dur))
    return parts
