"""audio-mix (montage §5.12): build the reel's audio stem from a MusicSpec — seek the
chosen fragment, fade, two-pass loudnorm to −14 LUFS → aac. Given `segments` and
`ambient`, each clip's preserved nat-sound is ducked under the music
(sidechaincompress); with `sfx`, a synthesized whoosh is placed on the reel's major
transitions and mixed in on top. Both bake into the one stem before the final
loudnorm, so deliver/check_reel see a single pre-normalized signal."""
import argparse
import os
import re
import statistics
import tempfile

from scripts.lib import assembly, ffbin, proc
from scripts.lib.models import MusicSpec

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
_SFX_SEED = 42          # anoisesrc seed → a deterministic whoosh


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


def _build_sfx(durs: list[float], tmp_dir: str) -> str | None:
    """Render a whoosh at each major internal cut (see _major_cuts) into one sfx-bed
    wav, or None when the reel has no major cut. The whoosh is synthesized once and
    placed by adelay onto the cut offsets (started _SFX_LEAD early so its attack peaks
    near the cut); amix normalize=0 keeps each whoosh at its own level. The bed is
    truncated/padded to the music length by mix's own amix=duration=first."""
    cuts = _major_cuts(durs)
    if not cuts:
        return None
    whoosh = _whoosh(tmp_dir)
    out = os.path.join(tmp_dir, "sfx.wav")
    total = sum(durs)
    k = len(cuts)
    fc = ["[1:a]asplit=%d%s" % (k, "".join(f"[w{i}]" for i in range(k)))]
    for i, t in enumerate(cuts):
        ms = max(0, int(round((t - _SFX_LEAD) * 1000)))
        fc.append(f"[w{i}]adelay={ms}:all=1[d{i}]")
    terms = "[0:a]" + "".join(f"[d{i}]" for i in range(k))
    fc.append(f"{terms}amix=inputs={k + 1}:duration=first:normalize=0[sfx]")
    proc.run([ffbin.ffmpeg(), "-y", "-t", f"{total}", "-f", "lavfi", "-i",
              f"anullsrc=r={_AR}:cl=stereo", "-i", whoosh,
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
        parts.append(f"[{idx}:a]volume=0.6[amb]")
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


def mix(music: MusicSpec, out_dir: str, dur: float,
        segments: list[tuple[str, float]] | None = None,
        ambient: bool = True, sfx: bool = False, fade: float = _FADE,
        fade_in: float | None = None) -> str:
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
    (LookSpec's own convention). The opening never drops below ANTICLICK."""
    if dur <= 0:
        raise ValueError(f"mix: dur must be positive, got {dur}")
    if dur > music.duration + 0.1:
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
        sfx_bed = _build_sfx([du for _, du in segments], d) if (segments and sfx) else None
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
    return out


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
