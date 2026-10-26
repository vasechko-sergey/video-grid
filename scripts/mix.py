"""audio-mix (montage §5.12): build the reel's audio stem from a MusicSpec — seek the
chosen fragment, fade, two-pass loudnorm to −14 LUFS → aac. Given `segments` and
`ambient`, each clip's preserved nat-sound is ducked under the music
(sidechaincompress); with `sfx`, a synthesized whoosh is placed on the reel's major
transitions and mixed in on top, and with `shutters` a synthesized shutter click on
the accented cuts, in the same layer. All bake into the one stem before the final
loudnorm, so deliver/check_reel see a single pre-normalized signal."""
import argparse
import json
import os
import re
import statistics
import tempfile
from collections.abc import Sequence
from pathlib import Path

from scripts.lib import assembly, ffbin, proc
from scripts.lib.models import MUSIC_OVERRUN_TOL, MusicSpec

_TARGET_LUFS = -14.0                                  # EBU R128 (montage §5.12). The gate's copy is
                                                      # ReelCheckSpec.loudness_target and the two must
                                                      # agree — tests/test_gates.py pins it, and GATES.json
                                                      # refuses to move either (design 2026-09-30 §0.2a)
_TP_MAX = -1.5                                         # true-peak ceiling (dBTP)
_LRA_TARGET = 11                                       # loudness range target
_FADE = 0.5     # default bookend fade, seconds per end. The DEFAULT, not a fixed
                # value: build_reel overrides it with EDL.look's fades so the audio and
                # video bookends agree (design 2026-08-13 §5).
ANTICLICK = 0.02  # the opening's floor: the music is cut mid-track at its start_offset,
                  # and with no opening fade (every mood preset since retro 2026-10-16
                  # S6) a hard first sample is a click. 20 ms is under any audible fade.


def _measure(audio: str) -> dict[str, str]:
    """loudnorm analysis pass → the measured stats the accurate second pass needs."""
    r = proc.run([ffbin.ffmpeg(), "-i", audio, "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    err = (r.stderr or b"").decode("utf-8", errors="replace")
    stats = {}
    for k in ("input_i", "input_tp", "input_lra", "input_thresh"):
        m = re.search(rf'"{k}"\s*:\s*"?(-?\d+\.?\d*)"?', err)
        if not m:
            raise RuntimeError(f"loudnorm printed no {k} for {audio} — cannot run the accurate "
                               "second pass; the chosen fragment may be silent")
        stats[k] = m.group(1)
    return stats


_AR = 48000            # ambient bed sample rate (uniform for -c copy concat)

# --- SFX: whoosh on major transitions (§5.12) — tunable in one place --------
_MAJOR_FACTOR = 1.0     # a cut is "major" when max(neighbour durs) > factor * median(durs)
_MIN_GAP = 0.6          # min seconds between kept whooshes (throttle)
_SFX_DUR = 0.35         # whoosh length (s)
_SFX_FREQ = 1200        # whoosh bandpass centre (Hz)
_SFX_Q = 0.7            # whoosh bandpass width (Q; smaller = wider)
_SFX_ATTACK = 0.08      # whoosh rise time (s); its peak lands here
_SFX_LEAD = 0.2         # whoosh starts this many seconds before the cut so its peak sits near it
_SFX_MIX = 1.0          # whoosh volume entering the final amix (relative punch)
_AMB_MIX = 0.6          # ambient bed volume entering the duck — shared by both graphs so the
                        # music-less stem keeps the weight the music stem gave it
_SFX_SEED = 42          # anoisesrc seed → a deterministic whoosh

# --- SFX: the shutter accent's click (design 2026-10-21 §4) — conventions from the
# 2026-10-20 research, not measured on a real run: a camera shutter reads as two short
# clicks, the curtain opening and closing.
_CLICK_DUR = 0.015      # each burst's length (s)
_CLICK_GAP = 0.07       # from the first burst's start to the second's (s)
_CLICK_HP = 1800        # high-pass corner (Hz): a click, not a thud
_CLICK_AMP = 0.5        # anoisesrc amplitude of each burst
_CLICK_SEEDS = (7, 11)  # one seed per burst → two different, deterministic clicks


def _has_audio(path: str) -> bool:
    """True iff `path` has at least one audio stream (a video-only segment does not)."""
    r = proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", "a",
                  "-show_entries", "stream=codec_name", "-of", "default=nk=1:nw=1", path])
    return bool(r.stdout.decode("utf-8", errors="replace").strip())


def _build_ambient(segments: list[tuple[str, float]], tmp_dir: str) -> str | None:
    """Concatenate each raw segment's audio, trimmed/padded to its final episode dur
    and ordered as given (EDL order), into one reel-length ambient bed. A segment with
    no audio stream contributes anullsrc silence so the bed stays in sync with the
    picture. Returns the bed wav path, or None when EVERY segment is silent (→ mix
    falls back to the music-only stem). Uniform 48 kHz stereo s16 so assembly.concat
    (-c copy) joins them losslessly."""
    beds: list[str] = []
    any_audio = False
    for i, (seg, dur) in enumerate(segments):
        bed = os.path.join(tmp_dir, f"amb_{i:03d}.wav")
        if _has_audio(seg):
            any_audio = True
            # audio seek exempt from the -ss-after-i rule; re-encode from 0, apad the
            # tail then -t caps → exactly `dur`, uniform 48k/stereo/s16.
            proc.run([ffbin.ffmpeg(), "-y", "-i", seg, "-t", f"{dur}", "-vn", "-ac", "2",
                      "-ar", str(_AR), "-af", "apad", "-c:a", "pcm_s16le", bed])
        else:
            proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i",
                      f"anullsrc=r={_AR}:cl=stereo", "-t", f"{dur}",
                      "-c:a", "pcm_s16le", bed])
        beds.append(bed)
    if not any_audio:
        return None
    return assembly.concat(beds, os.path.join(tmp_dir, "ambient.wav"))


def _major_cuts(durs: list[float]) -> list[float]:
    """Cumulative offsets of the reel's MAJOR internal cuts (EDL order). A cut between
    ep[k] and ep[k+1] sits at T[k]=sum(durs[:k+1]); it is major when max(durs[k],
    durs[k + 1]) > _MAJOR_FACTOR * median(durs) — i.e. it touches a held/hero shot on
    either side — and is kept only if at least _MIN_GAP past the previous kept cut
    (throttle). Empty when the reel has fewer than two clips or none exceed the median
    (uniform pacing → no accent)."""
    if len(durs) < 2:
        return []
    med = statistics.median(durs)
    kept: list[float] = []
    t = 0.0
    for k in range(len(durs) - 1):
        t += durs[k]                                    # T[k] = end of ep k = the cut time
        if max(durs[k], durs[k + 1]) > _MAJOR_FACTOR * med:
            if not kept or t - kept[-1] >= _MIN_GAP:
                kept.append(t)
    return kept


def _whoosh(tmp_dir: str) -> str:
    """Synthesize one transition whoosh → wav (48 kHz stereo s16): seeded pink noise
    through a resonant bandpass, a fast attack then a decay — a swell that reads as a
    whoosh. No asset, deterministic (fixed seed)."""
    out = os.path.join(tmp_dir, "whoosh.wav")
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i",
              f"anoisesrc=color=pink:r={_AR}:d={_SFX_DUR}:a=0.9:seed={_SFX_SEED}",
              "-af", (f"bandpass=f={_SFX_FREQ}:width_type=q:w={_SFX_Q},"
                      f"afade=t=in:st=0:d={_SFX_ATTACK},"
                      f"afade=t=out:st={_SFX_ATTACK}:d={_SFX_DUR - _SFX_ATTACK}"),
              "-ac", "2", "-ar", str(_AR), "-c:a", "pcm_s16le", out])
    return out


def _shutter(tmp_dir: str) -> str:
    """Synthesize one shutter click → wav (48 kHz stereo s16, like _whoosh): two
    _CLICK_DUR bursts of seeded white noise _CLICK_GAP apart, each high-passed and
    faded out over its own length — a fast decay. No asset, deterministic (fixed
    seeds)."""
    out = os.path.join(tmp_dir, "shutter.wav")
    shape = f"highpass=f={_CLICK_HP},afade=t=out:st=0:d={_CLICK_DUR}"
    gap_ms = int(round(_CLICK_GAP * 1000))
    proc.run([ffbin.ffmpeg(), "-y",
              *(x for seed in _CLICK_SEEDS for x in (
                  "-f", "lavfi", "-i",
                  f"anoisesrc=color=white:r={_AR}:d={_CLICK_DUR}:a={_CLICK_AMP}:seed={seed}")),
              "-filter_complex",
              (f"[0:a]{shape}[c0];[1:a]{shape},adelay={gap_ms}:all=1[c1];"
               "[c0][c1]amix=inputs=2:duration=longest:normalize=0[shutter]"),
              "-map", "[shutter]", "-ac", "2", "-ar", str(_AR), "-c:a", "pcm_s16le", out])
    return out


def _build_sfx(durs: list[float], tmp_dir: str, *, whoosh: bool = True,
               shutters: Sequence[float] = ()) -> str | None:
    """Render one sfx-bed wav: with `whoosh`, a whoosh at each major internal cut (see
    _major_cuts); and a shutter click at each `shutters` time (the master's real cut
    times of the accented episodes, design 2026-10-21 §4). None when the bed would be
    empty. Each sound is synthesized once and placed by adelay — a whoosh started
    _SFX_LEAD early so its attack peaks near the cut, a click with no lead so its
    first burst is on the cut. amix normalize=0 keeps each at its own level. The bed
    is truncated/padded to the music length by mix's own amix=duration=first.

    Without shutters the argv is exactly the whoosh-only bed's (pinned by a test), so
    a reel without accents sounds as it did."""
    cuts = _major_cuts(durs) if whoosh else []
    shutters = list(shutters)
    if not cuts and not shutters:
        return None
    out = os.path.join(tmp_dir, "sfx.wav")
    total = sum(durs)
    inputs: list[str] = []
    fc: list[str] = []
    terms = "[0:a]"
    # (copy label, placed label, times, lead, synthesizer) per sound; input 0 is the
    # silent base and each sound present takes the next input index
    for src, dst, times, lead, make in (("w", "d", cuts, _SFX_LEAD, _whoosh),
                                        ("s", "c", shutters, 0.0, _shutter)):
        if not times:
            continue
        idx = 1 + len(inputs) // 2
        inputs += ["-i", make(tmp_dir)]
        fc.append(f"[{idx}:a]asplit={len(times)}"
                  + "".join(f"[{src}{i}]" for i in range(len(times))))
        for i, t in enumerate(times):
            ms = max(0, int(round((t - lead) * 1000)))
            fc.append(f"[{src}{i}]adelay={ms}:all=1[{dst}{i}]")
        terms += "".join(f"[{dst}{i}]" for i in range(len(times)))
    fc.append(f"{terms}amix=inputs={1 + len(cuts) + len(shutters)}:duration=first:"
              f"normalize=0[sfx]")
    proc.run([ffbin.ffmpeg(), "-y", "-t", f"{total}", "-f", "lavfi", "-i",
              f"anullsrc=r={_AR}:cl=stereo", *inputs,
              "-filter_complex", ";".join(fc), "-map", "[sfx]",
              "-c:a", "pcm_s16le", out])
    return out


def _mix_graph(has_ambient: bool, has_sfx: bool) -> str:
    """filter_complex composing the optional ambient (ducked under the music) and sfx
    (un-ducked, on top) layers over the music fragment (input 0). Inputs after 0 are,
    in order: ambient (if any) then sfx (if any). The music-only path never calls this;
    the ambient-only string is byte-identical to the pre-SFX mixer (regression-pinned)."""
    idx = 1
    parts: list[str] = []
    terms: list[str] = []
    if has_ambient:
        parts.append("[0:a]asplit=2[msum][mkey]")
        terms.append("[msum]")
        parts.append(f"[{idx}:a]volume={_AMB_MIX}[amb]")
        parts.append("[amb][mkey]sidechaincompress=threshold=0.03:ratio=4:attack=20:release=300[duck]")
        terms.append("[duck]")
        idx += 1
    else:
        terms.append("[0:a]")
    if has_sfx:
        parts.append(f"[{idx}:a]volume={_SFX_MIX}[sfx]")
        terms.append("[sfx]")
        idx += 1
    parts.append(f"{''.join(terms)}amix=inputs={len(terms)}:duration=first[mixed]")
    return ";".join(parts)


def _nomusic_graph(has_ambient: bool, has_sfx: bool, gain_db: float, fades: list[str],
                   dur: float) -> str:
    """filter_complex for the music-less stem (design 2026-10-20 §2): what the music stem
    sounds like with the track muted. Inputs: ambient (if any) then sfx (if any).

    - No key, no sidechaincompress: with the music gone the duck would pump to nothing.
    - The weights the music mix gave each layer — amix's default normalize=1 scaled every
      input by 1/N, N counting the music — reproduced with normalize=0, so the layers keep
      their level relative to each other and to the picture.
    - The music stem's own loudnorm gain as a plain `volume`, never a second loudnorm: an
      ambient bed normalized to −14 LUFS alone would lift the wind noise.
    - The same bookend fades, then a sample-peak ceiling at the stem's true-peak target:
      an un-ducked wave crash can peak higher than it did under the duck. It is not a
      true-peak limiter — inter-sample peaks can still pass it. alimiter's `level` defaults to
      an AUTO LEVEL that normalizes its output up — level=0 is load-bearing — and latency=1
      keeps its lookahead from shifting the sound against the picture."""
    n = 1 + has_ambient + has_sfx                       # the MUSIC mix's amix input count
    layers = [(w, name) for on, w, name in ((has_ambient, _AMB_MIX, "amb"),
                                             (has_sfx, _SFX_MIX, "sfx")) if on]
    if not layers:
        raise ValueError("_nomusic_graph: no ambient and no sfx — the stem is silence, "
                         "which _render_without_music renders without a graph")
    parts = [f"[{i}:a]volume={w / n:.6f}[{name}]" for i, (w, name) in enumerate(layers)]
    if len(layers) == 2:
        parts.append("[amb][sfx]amix=inputs=2:duration=longest:normalize=0[nm]")
        src = "[nm]"
    else:
        src = f"[{layers[0][1]}]"
    ceiling = 10 ** (_TP_MAX / 20)
    parts.append(f"{src}apad,atrim=0:{dur},volume={gain_db:.3f}dB,{','.join(fades)},"
                 f"alimiter=limit={ceiling:.4f}:level=0:latency=1[out]")
    return ";".join(parts)


def mix(music: MusicSpec, out_dir: str, dur: float,
        segments: list[tuple[str, float]] | None = None,
        ambient: bool = True, sfx: bool = False, fade: float = _FADE,
        fade_in: float | None = None, without_music: str | None = None,
        shutters: Sequence[float] = ()) -> str:
    """Audio stem for a `dur`-second reel → out_dir/audio.m4a (aac, −14 LUFS). With
    `segments` ([(raw_segment_path, episode_dur), …] in reel order) and `ambient`,
    each clip's nat-sound is ducked under the music; with `sfx`, a synthesized whoosh
    is placed on the reel's major transitions and mixed in on top. Both bake into the
    one stem before the final loudnorm; without them the stem is music-only, exactly
    as before.

    `fade` is the bookend fade at each end, in seconds, and it is applied to the
    MIXED stem rather than to the music fragment — design 2026-08-13 §5. On the
    fragment it faded only the music, and since _mix_graph's sidechaincompress is
    keyed on the music, the duck RELEASED as the music fell and the nat-sound got
    louder exactly as the picture went to black. build_reel passes EDL.look's fades
    here so the audio and video bookends agree.

    `fade` is the CLOSING fade and, unless `fade_in` sets it apart, the opening one too
    (LookSpec's own convention). The opening never drops below ANTICLICK.

    `shutters` are the master's real cut times of the episodes that carry the shutter
    accent (design 2026-10-21 §4): a click on each, in the same un-ducked bed as the
    whooshes, so it reaches everything the sfx input reaches. It needs `segments` — the
    bed's length comes from them — and is refused without them rather than dropped.

    `without_music`, when given, is a second path: the same reel with the track muted
    (design 2026-10-20 §2, see _nomusic_graph), rendered here from the same beds and the
    same measurement so the two stems cannot drift apart. With neither ambient nor sfx
    it is silence of the reel's length — still the deliverable a picture needs."""
    if dur <= 0:
        raise ValueError(f"mix: dur must be positive, got {dur}")
    if shutters and not segments:
        raise ValueError(f"mix: shutters {list(shutters)} were given without segments — a "
                         f"click rides the SFX bed, which is cut to the segments' lengths, "
                         f"so without them it would be dropped in silence. Pass segments "
                         f"([(raw_segment, episode_dur), …] in reel order), as build_reel "
                         f"does")
    if dur > music.duration + MUSIC_OVERRUN_TOL:
        raise ValueError(f"mix: reel dur {dur}s exceeds the analyzed music window {music.duration}s "
                         f"(track={music.track}, start_offset={music.start_offset}) — analyze a longer "
                         "window or shorten the reel; a shorter stem would silently desync from the video")
    head = fade if fade_in is None else fade_in
    for name, v in (("fade", fade), ("fade_in", head)):
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
            raise ValueError(f"mix: {name} must be a non-negative number of seconds, got {v!r}")
    head = max(head, ANTICLICK)
    if dur < head + fade:
        raise ValueError(f"mix: a {head}s opening and a {fade}s closing fade on a {dur}s reel "
                         f"would overlap — lower the look's fades to at most {dur:.2f}s "
                         f"together or cut a longer reel")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "audio.m4a")
    with tempfile.TemporaryDirectory() as d:
        frag = os.path.join(d, "frag.wav")
        # accurate-seek the fragment (audio seek is exempt from the frame-accurate-video
        # landmine, but placed exactly), trim to the reel length — the fade below runs on
        # the MIXED stem instead, so it reaches the ambient duck and the sfx too
        proc.run([ffbin.ffmpeg(), "-y", "-accurate_seek", "-ss", f"{music.start_offset}",
                  "-i", music.track, "-t", f"{dur}", frag])
        amb = _build_ambient(segments, d) if (segments and ambient) else None
        sfx_bed = (_build_sfx([du for _, du in segments], d, whoosh=sfx, shutters=shutters)
                   if (segments and (sfx or shutters)) else None)
        norm_src = frag
        if amb is not None or sfx_bed is not None:
            inputs = ["-i", frag]
            if amb is not None:
                inputs += ["-i", amb]
            if sfx_bed is not None:
                inputs += ["-i", sfx_bed]
            mixed = os.path.join(d, "mixed.wav")
            proc.run([ffbin.ffmpeg(), "-y", *inputs, "-filter_complex",
                      _mix_graph(amb is not None, sfx_bed is not None),
                      "-map", "[mixed]", mixed])
            norm_src = mixed
        # AFTER the mix and BEFORE the measurement: everything in the stem fades
        # together, and loudnorm still measures the signal that actually ships. The
        # opening always runs (ANTICLICK at least); the closing only when non-zero.
        fades = [f"afade=t=in:st=0:d={head}"]
        if fade:
            fades.append(f"afade=t=out:st={max(0.0, dur - fade)}:d={fade}")
        faded = os.path.join(d, "faded.wav")
        proc.run([ffbin.ffmpeg(), "-y", "-i", norm_src, "-af", ",".join(fades), faded])
        norm_src = faded
        st = _measure(norm_src)
        proc.run([ffbin.ffmpeg(), "-y", "-i", norm_src, "-af",
                  (f"loudnorm=I={_TARGET_LUFS}:TP={_TP_MAX}:LRA={_LRA_TARGET}:"
                   f"measured_I={st['input_i']}:measured_TP={st['input_tp']}:"
                   f"measured_LRA={st['input_lra']}:measured_thresh={st['input_thresh']}"),
                  "-c:a", "aac", "-b:a", "192k", out])
        if without_music is not None:
            gain = _TARGET_LUFS - float(st["input_i"])
            _render_without_music(without_music, amb, sfx_bed, dur, fades, gain, _layout(out))
            # What the stem holds, and whether `gain` IS what the music stem received:
            # loudnorm only stays linear when the measured range and the lifted true peak
            # both fit its targets (af_loudnorm's own test). Otherwise it rode a dynamic
            # gain and the music-less ambient sits several dB from the music version's —
            # measured 4.9 and 6.3 dB on wide-range fixtures — so the note says so.
            linear = (float(st["input_lra"]) <= _LRA_TARGET
                      and float(st["input_tp"]) + gain <= _TP_MAX)
            # The bed by what it holds, not by whether it exists: `sfx` is the whooshes
            # (the flag's own meaning, and all a bed held before the accent) and
            # `clicks` the shutter accent's, present only when placed — so the note
            # never calls a bed of clicks "the transition whooshes", and a record with
            # no accent is the one it always was.
            whooshes = sfx_bed is not None and sfx and bool(
                _major_cuts([du for _, du in segments]))
            Path(without_music).with_suffix(".json").write_text(json.dumps(
                {"ambient": amb is not None, "sfx": whooshes,
                 "gain_db": round(gain, 3), "linear": linear,
                 **({"clicks": True} if sfx_bed is not None and shutters else {})}))
    return out


def _layout(path: str) -> tuple[int, int]:
    """(channels, sample rate) of an encoded stem. The music stem takes the TRACK's
    layout through amix, so a music-less stem rendered in any other layout would sit
    at a different level: measured, a stereo bed beside a mono track lands 3 dB apart."""
    r = proc.run([ffbin.ffprobe(), "-v", "error", "-select_streams", "a:0",
                  "-show_entries", "stream=channels,sample_rate", "-of", "csv=p=0", path])
    rate, ch = r.stdout.decode("utf-8", errors="replace").strip().split(",")
    return int(ch), int(rate)


def _render_without_music(path: str, amb: str | None, sfx_bed: str | None, dur: float,
                          fades: list[str], gain_db: float, layout: tuple[int, int]) -> None:
    """Write the music-less stem in the music stem's own layout (see _layout)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    ch, rate = layout
    fmt = ["-ac", str(ch), "-ar", str(rate), "-c:a", "aac", "-b:a", "192k", path]
    if amb is None and sfx_bed is None:
        proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i", f"anullsrc=r={rate}:cl=stereo",
                  "-t", f"{dur}", *fmt])
        return
    inputs = [x for b in (amb, sfx_bed) if b is not None for x in ("-i", b)]
    proc.run([ffbin.ffmpeg(), "-y", *inputs, "-filter_complex",
              _nomusic_graph(amb is not None, sfx_bed is not None, gain_db, fades, dur),
              "-map", "[out]", "-t", f"{dur}", *fmt])


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="build the reel audio stem from MUSIC.json")
    ap.add_argument("music", help="MUSIC.json path")
    ap.add_argument("--out-dir", required=True, help="where the audio stem goes")
    ap.add_argument("--dur", type=float, required=True, help="reel length (seconds)")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    print(mix(MusicSpec.from_json(a.music), a.out_dir, a.dur))


if __name__ == "__main__":
    main()
