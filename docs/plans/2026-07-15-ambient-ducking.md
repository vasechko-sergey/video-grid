# Ambient Ducking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a ducked ambient bed — each clip's preserved nat-sound, ordered per the EDL and compressed under the music — to the reel's audio stem, baked in before the final loudnorm so `deliver`/`check_reel` stay untouched.

**Architecture:** `mix()` grows one optional `segments` argument. A new `_build_ambient` helper concatenates each raw segment's audio (trimmed/padded to its final episode duration, silent-padded when a segment has no audio) into a reel-length bed; `mix()` then sidechain-compresses that bed under the music and `amix`es the two before the existing two-pass loudnorm. `build_reel` gathers the segment paths + durations from the episode manifests and passes them when `ReelManifest.ambient` is set (default True). Nothing downstream of the single `audio.m4a` stem changes.

**Tech Stack:** Python 3 (stdlib + `dataclasses`), ffmpeg (`sidechaincompress`, `amix`, `anullsrc`, two-pass `loudnorm`), pytest, scipy/numpy for the real-ffmpeg synth proofs. Scripts run as modules (`pythonpath = .`, `.venv/bin/python -m ...`).

---

## Spec

Design: [docs/specs/2026-07-15-ambient-ducking-design.md](../specs/2026-07-15-ambient-ducking-design.md).

## Repo conventions (apply to every task)

- **Fail loud with a remedy.** A `ValueError`/`RuntimeError` names the offending value and the fix. No silent fallbacks (the one deliberate graceful path is all-segments-silent → music-only stem, which logs a note).
- **Imports at top of file. Every `def` fully typed. Config-specs validate in `__post_init__`.**
- **Never pipe pytest through `tail`** (it makes `$?` reflect `tail`). End every run with `; echo "EXIT: $?"` and read that line.
- **Real-ffmpeg tests are `@pytest.mark.integration` and skip when ffmpeg is absent** (the `sample_clip` fixture in `tests/conftest.py` already `pytest.skip`s without ffmpeg; new synth tests guard with `shutil.which`).
- **Landmine — the ambient bed must equal the master length exactly.** `amix=inputs=2:duration=first` with the music (already exactly `dur`) as the first input pins the stem length; a stem that drifts from the picture silently desyncs (`deliver`'s `-shortest` only absorbs sub-second jitter).
- **Landmine — audio seek is exempt** from the frame-accurate `-ss`-after-`-i` video rule; `_build_ambient` re-encodes each segment from 0 with `-t dur` (no seek).

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `scripts/lib/models.py` | modify | `ReelManifest.ambient: bool = True` field + `__post_init__` bool guard + `from_dict` reads `d.get("ambient", True)` |
| `scripts/mix.py` | modify | `mix(music, out_dir, dur, segments=None)`; new module-level `_build_ambient(segments, tmp_dir) -> str \| None`; new `from scripts.lib import assembly` import |
| `scripts/build_reel.py` | modify | stem hook gathers `(segment, target_dur)` from each episode manifest and passes `segments` when `rm.ambient` |
| `tests/lib/test_models.py` | modify | 3 tests for the `ambient` field (default, from_dict, non-bool reject) |
| `tests/test_mix.py` | create | unit tests (mock `proc.run`) for `_build_ambient` branches + `mix` music-only regression + ambient-graph insertion |
| `tests/lib/test_build_reel.py` | modify | patch the music mocks/manifests for the new `segments=` kwarg; add segment-passing + ambient-false tests |
| `tests/integration/test_ambient.py` | create | real-ffmpeg proofs: stem hits −14 LUFS with a bed; ducking attenuates the ambient band under loud music |
| `tests/integration/test_music_spine.py` | modify | give the build_reel golden real segment manifests so the default (ambient=True) path runs end-to-end |
| `docs/build-status.md`, `docs/pipeline-map.md`, `docs/specs/2026-07-05-montage-skillset-design.md`, `docs/specs/2026-07-11-music-spine-design.md`, `CLAUDE.md` | modify | doc sync (Task 5) |

---

### Task 0: `ReelManifest.ambient` field

**Files:**
- Modify: `scripts/lib/models.py` (the `ReelManifest` dataclass — field list ~700-704, `__post_init__` ~706-725, `from_dict` ~731-750)
- Test: `tests/lib/test_models.py` (append after `test_reel_manifest_rejects_non_dict_manifest_direct`, ~line 578; helper `_reel_dict` is at ~511)

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_models.py`:

```python
def test_reel_manifest_ambient_defaults_true():
    assert m.ReelManifest.from_dict(_reel_dict()).ambient is True


def test_reel_manifest_ambient_false_from_dict():
    assert m.ReelManifest.from_dict(_reel_dict(ambient=False)).ambient is False


def test_reel_manifest_rejects_non_bool_ambient():
    with pytest.raises(ValueError, match="ambient"):
        m.ReelManifest.from_dict(_reel_dict(ambient="yes"))
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k ambient -v ; echo "EXIT: $?"`
Expected: FAIL — `test_reel_manifest_ambient_defaults_true` errors with `AttributeError: 'ReelManifest' object has no attribute 'ambient'` (the field does not exist yet).

- [x] **Step 3: Add the field, guard, and from_dict wiring**

In `scripts/lib/models.py`, add the field to the `ReelManifest` dataclass right after the `music` field:

```python
    music: str | None = None           # MUSIC.json path (design §6); None → a silent reel, as Phase A.5
    ambient: bool = True               # duck each clip's nat-sound under the music (§5.12); False → pure-music stem
```

In `ReelManifest.__post_init__`, add the guard just before the final `self.check_spec` line:

```python
        if not isinstance(self.ambient, bool):
            raise ValueError(f"ReelManifest.ambient must be a bool (True → duck ambient under "
                             f"music, False → pure-music stem), got {self.ambient!r}")
        self.check_spec  # forces ReelCheckSpec validation of target_dur/variety_min/color_delta_max
```

In `ReelManifest.from_dict`, add `ambient` to the returned constructor call:

```python
        return cls(episodes=eps, target_dur=d.get("target_dur"),
                   variety_min=d.get("variety_min", 8),
                   color_delta_max=d.get("color_delta_max", 12.0),
                   cap=d.get("cap", 3), changelog=d.get("changelog", ""),
                   music=d.get("music"), ambient=d.get("ambient", True))
```

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k ambient -v ; echo "EXIT: $?"`
Expected: PASS (3 passed).

- [x] **Step 5: Run the whole models suite (nothing regressed)**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -q ; echo "EXIT: $?"`
Expected: PASS, EXIT 0.

- [x] **Step 6: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: ReelManifest.ambient flag (default True) — the audio-mix ambient on/off switch"
```

---

### Task 1: `mix._build_ambient` — the reel-length ambient bed

Builds one pcm wav per segment (real audio trimmed/padded to its episode dur, or `anullsrc` silence when a segment has no audio stream), concatenates them in order via `assembly.concat`, and returns the bed path — or `None` when **every** segment was silent (the caller then makes a music-only stem).

**Files:**
- Modify: `scripts/mix.py` (add `from scripts.lib import assembly` to the imports at top; add `_build_ambient` after `_measure`, before `mix`)
- Test: `tests/test_mix.py` (create)

- [x] **Step 1: Write the failing tests**

Create `tests/test_mix.py`:

```python
"""mix ambient path — unit level, proc.run mocked (the real ffmpeg proof lives in
tests/integration/test_ambient.py). Asserts branch selection + command shape only."""
from scripts import mix
from scripts.lib.models import MusicSpec


class _R:
    def __init__(self, stdout=b"", stderr=b""):
        self.stdout, self.stderr = stdout, stderr


def _probe_says_audio(cmd, present):
    """True when cmd is the ffprobe audio-stream probe."""
    return "-select_streams" in cmd


def test_build_ambient_all_silent_returns_none(tmp_path, monkeypatch):
    # every ffprobe audio probe returns empty → no segment has audio → None
    calls = []
    monkeypatch.setattr(mix.proc, "run", lambda cmd, **k: (calls.append(cmd), _R())[1])
    monkeypatch.setattr(mix.assembly, "concat", lambda entries, out: out)
    res = mix._build_ambient([("s0.mp4", 3.0), ("s1.mp4", 2.0)], str(tmp_path))
    assert res is None
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "anullsrc" in joined                       # silent segments synth silence


def test_build_ambient_audio_present_concats_one_wav_per_segment_in_order(tmp_path, monkeypatch):
    def fake_run(cmd, **k):
        stdout = b"aac\n" if "-select_streams" in cmd else b""   # probe → audio present
        return _R(stdout=stdout)
    monkeypatch.setattr(mix.proc, "run", fake_run)
    seen = {}
    monkeypatch.setattr(mix.assembly, "concat",
                        lambda entries, out: (seen.setdefault("entries", list(entries)), out)[1])
    res = mix._build_ambient([("s0.mp4", 3.0), ("s1.mp4", 2.0)], str(tmp_path))
    assert res is not None
    assert len(seen["entries"]) == 2                  # one bed wav per segment, EDL order


def test_build_ambient_mixed_returns_bed_when_any_has_audio(tmp_path, monkeypatch):
    def fake_run(cmd, **k):
        # only s0's probe reports audio; s1 is video-only
        stdout = b"aac\n" if ("-select_streams" in cmd and "s0.mp4" in cmd) else b""
        return _R(stdout=stdout)
    monkeypatch.setattr(mix.proc, "run", fake_run)
    monkeypatch.setattr(mix.assembly, "concat", lambda entries, out: out)
    res = mix._build_ambient([("s0.mp4", 3.0), ("s1.mp4", 2.0)], str(tmp_path))
    assert res is not None                            # one real audio stream → a bed (s1 = silence)
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mix.py -v ; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: module 'scripts.mix' has no attribute '_build_ambient'` (and `assembly` not importable from `mix` yet).

- [x] **Step 3: Implement `_build_ambient`**

In `scripts/mix.py`, add to the imports at top:

```python
from scripts.lib import assembly, proc
```

(replacing the existing `from scripts.lib import proc`).

Add after `_measure` and before `mix`:

```python
_AR = 48000            # ambient bed sample rate (uniform for -c copy concat)


def _has_audio(path: str) -> bool:
    """True iff `path` has at least one audio stream (a video-only segment does not)."""
    r = proc.run(["ffprobe", "-v", "error", "-select_streams", "a",
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
            proc.run(["ffmpeg", "-y", "-i", seg, "-t", f"{dur}", "-vn", "-ac", "2",
                      "-ar", str(_AR), "-af", "apad", "-c:a", "pcm_s16le", bed])
        else:
            proc.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                      f"anullsrc=r={_AR}:cl=stereo", "-t", f"{dur}",
                      "-c:a", "pcm_s16le", bed])
        beds.append(bed)
    if not any_audio:
        return None
    return assembly.concat(beds, os.path.join(tmp_dir, "ambient.wav"))
```

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_mix.py -v ; echo "EXIT: $?"`
Expected: PASS (3 passed).

- [x] **Step 5: Commit**

```bash
git add scripts/mix.py tests/test_mix.py
git commit -m "feat: mix._build_ambient — reel-length ducked-ambient bed from raw segments"
```

---

### Task 2: `mix(segments=...)` — the sidechaincompress graph

Insert one filtergraph pass between the existing seek→`frag.wav` and measure→`audio.m4a` passes. Music-only behaviour (`segments=None`, or a bed that came back `None`) is byte-for-byte unchanged.

**Files:**
- Modify: `scripts/mix.py` (the `mix` function, signature at ~line 33 and body ~44-60)
- Test: `tests/test_mix.py` (append)

- [x] **Step 1: Write the failing tests**

Append to `tests/test_mix.py`:

```python
def _ms(tmp_path):
    return MusicSpec(track=str(tmp_path / "t.wav"), start_offset=0.0, duration=6.0,
                     tempo=120.0, beats=(0.0, 0.5), energy=(0.3,), energy_hz=2.0)


def _loudnorm_stderr():
    # _measure scrapes these four keys from ffmpeg's stderr; feed a valid set
    return (b'"input_i" : "-20.0", "input_tp" : "-3.0", '
            b'"input_lra" : "5.0", "input_thresh" : "-30.0"')


def test_mix_music_only_makes_no_sidechain(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    out = mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0)           # segments=None
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "sidechaincompress" not in joined and "asplit" not in joined  # unchanged path
    assert out.endswith("audio.m4a")


def test_mix_with_ambient_inserts_sidechain_and_pins_length(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    monkeypatch.setattr(mix, "_build_ambient", lambda segs, d: d + "/ambient.wav")
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0, segments=[("s0.mp4", 3.0)])
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "sidechaincompress" in joined                              # ambient graph inserted
    assert "amix=inputs=2:duration=first" in joined                   # length pinned to the music


def test_mix_all_silent_bed_falls_back_to_music_only(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    monkeypatch.setattr(mix, "_build_ambient", lambda segs, d: None)  # every segment silent
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0, segments=[("s0.mp4", 3.0)])
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "sidechaincompress" not in joined                          # None → music-only
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mix.py -k "music_only or ambient or silent" -v ; echo "EXIT: $?"`
Expected: FAIL — `test_mix_with_ambient_inserts_sidechain_and_pins_length` fails because `mix()` takes no `segments` argument yet (`TypeError: mix() got an unexpected keyword argument 'segments'`).

- [x] **Step 3: Extend `mix()`**

In `scripts/mix.py`, change the `mix` signature and body. New signature:

```python
def mix(music: MusicSpec, out_dir: str, dur: float,
        segments: list[tuple[str, float]] | None = None) -> str:
    """Audio stem for a `dur`-second reel → out_dir/audio.m4a (aac, −14 LUFS). With
    `segments` ([(raw_segment_path, episode_dur), …] in reel order), each clip's
    nat-sound is ducked under the music and mixed in (design §5.12); without them (or
    when every segment is silent) the stem is music-only, exactly as before."""
```

Keep the three guards unchanged. Then in the `with tempfile.TemporaryDirectory() as d:` block, after the `frag` seek+fade `proc.run(...)` that produces `frag`, insert the ambient pass and normalize from `norm_src`:

```python
        norm_src = frag
        if segments:
            ambient = _build_ambient(segments, d)
            if ambient is not None:
                mixed = os.path.join(d, "mixed.wav")
                # duck the ambient under the music (sidechaincompress: main=ambient,
                # key=music), keep the ambient below the music (volume=0.6), then amix
                # with duration=first so the stem is EXACTLY the music length (= dur).
                proc.run(["ffmpeg", "-y", "-i", frag, "-i", ambient, "-filter_complex",
                          ("[0:a]asplit=2[msum][mkey];"
                           "[1:a]volume=0.6[amb];"
                           "[amb][mkey]sidechaincompress=threshold=0.03:ratio=4:"
                           "attack=20:release=300[duck];"
                           "[msum][duck]amix=inputs=2:duration=first[mixed]"),
                          "-map", "[mixed]", mixed])
                norm_src = mixed
        st = _measure(norm_src)
        proc.run(["ffmpeg", "-y", "-i", norm_src, "-af",
                  (f"loudnorm=I={_TARGET_LUFS}:TP={_TP_MAX}:LRA={_LRA_TARGET}:"
                   f"measured_I={st['input_i']}:measured_TP={st['input_tp']}:"
                   f"measured_LRA={st['input_lra']}:measured_thresh={st['input_thresh']}"),
                  "-c:a", "aac", "-b:a", "192k", out])
```

(The only change to the final loudnorm pass is its input: `frag` → `norm_src`.)

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_mix.py -v ; echo "EXIT: $?"`
Expected: PASS (6 passed).

- [x] **Step 5: Commit**

```bash
git add scripts/mix.py tests/test_mix.py
git commit -m "feat: mix(segments=) ducks the ambient bed under the music before loudnorm"
```

---

### Task 3: `build_reel` wiring + music-test fixups

The stem hook gathers `(segment, target_dur)` from each episode manifest and passes them when `rm.ambient`. The existing music unit tests must learn the new `segments=` kwarg (their `mix.mix` mocks) and carry `segment`/`target_dur` in their manifests (they exercise the default ambient=True path).

**Files:**
- Modify: `scripts/build_reel.py:47-49` (the stem hook)
- Test: `tests/lib/test_build_reel.py` (patch `_rm_music` ~170-173, `_wire_music` ~194-201, the inline mocks in `test_build_reel_music_delivers_after_full_reprocess_budget` ~248-261; add two new tests)

- [x] **Step 1: Patch the music-test fixtures for the new kwarg (they currently break)**

In `tests/lib/test_build_reel.py`, update `_rm_music` to carry real manifests:

```python
def _rm_music(music, ambient=True):
    ep0 = ReelEpisode(manifest={"segment": "s0.mp4", "target_dur": 3.0}, clip="c0.mp4", route="r0.json")
    ep1 = ReelEpisode(manifest={"segment": "s1.mp4", "target_dur": 3.0}, clip="c1.mp4", route="r1.json")
    return ReelManifest(episodes=[ep0, ep1], target_dur=6.0, variety_min=4,
                        music=music, ambient=ambient)
```

Update the `mix.mix` mock in `_wire_music` to accept `segments=`:

```python
    monkeypatch.setattr(build_reel.mix, "mix",
                        lambda mus, wd, dur, segments=None: (mixed.append((wd, dur)), "stem.m4a")[1])
```

Update the inline manifest + `mix.mix` mock in `test_build_reel_music_delivers_after_full_reprocess_budget`:

```python
    ep = ReelEpisode(manifest={"segment": "s0.mp4", "target_dur": 6.0}, clip="c0.mp4", route="r0.json")
    rm = ReelManifest(episodes=[ep], target_dur=6.0, cap=3, music=str(tmp_path / "MUSIC.json"))
```

```python
    monkeypatch.setattr(build_reel.mix, "mix",
                        lambda mus, wd, dur, segments=None: (mixed.append(dur), "stem.m4a")[1])
```

- [x] **Step 2: Write the failing new tests**

Append to `tests/lib/test_build_reel.py`:

```python
def test_build_reel_passes_segments_when_ambient(tmp_path, monkeypatch):
    # ambient defaults True → build_reel hands mix the (segment, target_dur) list, EDL order
    mixed, delivered, got = [], [], {}
    _wire_music(monkeypatch, [_passing(), _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.mix, "mix",
                        lambda mus, wd, dur, segments=None: (got.setdefault("segments", segments), "stem.m4a")[1])
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    build_reel.build_reel(_rm_music(music=str(tmp_path / "MUSIC.json")),
                          str(tmp_path / "out"), str(tmp_path / "work"))
    assert got["segments"] == [("s0.mp4", 3.0), ("s1.mp4", 3.0)]


def test_build_reel_ambient_false_passes_no_segments(tmp_path, monkeypatch):
    mixed, delivered, got = [], [], {}
    _wire_music(monkeypatch, [_passing(), _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.mix, "mix",
                        lambda mus, wd, dur, segments=None: (got.setdefault("segments", segments), "stem.m4a")[1])
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    build_reel.build_reel(_rm_music(music=str(tmp_path / "MUSIC.json"), ambient=False),
                          str(tmp_path / "out"), str(tmp_path / "work"))
    assert got["segments"] is None            # ambient=False → pure-music stem
```

- [x] **Step 3: Run to verify the new tests fail**

Run: `.venv/bin/python -m pytest tests/lib/test_build_reel.py -k "segments or ambient_false" -v ; echo "EXIT: $?"`
Expected: FAIL — `test_build_reel_passes_segments_when_ambient` fails: `got["segments"]` is `None` because build_reel does not pass `segments` yet.

- [x] **Step 4: Wire the stem hook**

In `scripts/build_reel.py`, replace the stem-build block (currently lines 47-49):

```python
            if music is not None and audio is None:  # picture passed → build the stem once, re-check with it
                segments = ([(e.manifest["segment"], e.manifest["target_dur"]) for e in rm.episodes]
                            if rm.ambient else None)
                audio = mix.mix(music, work_dir, check_reel._probe_dur(master), segments=segments)
                continue                             # need_assemble stays False — clips unchanged, no re-assemble
```

- [x] **Step 5: Run to verify all build_reel tests pass**

Run: `.venv/bin/python -m pytest tests/lib/test_build_reel.py -q ; echo "EXIT: $?"`
Expected: PASS, EXIT 0 (the patched music tests + the two new ones + all A.5 tests).

- [x] **Step 6: Commit**

```bash
git add scripts/build_reel.py tests/lib/test_build_reel.py
git commit -m "feat: build_reel passes per-episode (segment, target_dur) to mix when rm.ambient"
```

---

### Task 4: real-ffmpeg proofs

Two integration proofs: the stem still hits −14 LUFS with a real audio bed, and the sidechaincompress genuinely ducks — the ambient's frequency band is quieter where the music is loud. Plus: point the existing build_reel golden's manifests at real segments so the default path runs end-to-end (the golden's clips are silent, so this exercises the all-silent → music-only fallback without crashing on `manifest["segment"]`).

**Files:**
- Create: `tests/integration/test_ambient.py`
- Modify: `tests/integration/test_music_spine.py` (the `ReelEpisode(...)` manifests at ~61-62)

- [x] **Step 1: Write `test_ambient.py`**

Create `tests/integration/test_ambient.py`:

```python
"""Real-ffmpeg proofs for the ambient bed (design §8): (A) mix with a bed still hits
−14 LUFS; (B) sidechaincompress ducks — the ambient band is quieter under loud music.
Synthetic known-answer signals, mirroring tests/integration/test_mood.py / test_offset.py."""
import shutil

import numpy as np
import pytest
from scipy.io import wavfile

from scripts import check_reel, mix
from scripts.lib import proc
from scripts.lib.models import MusicSpec

_SR = 22050


def _tone_wav(path, secs, freq, amp, first_half_only=False):
    """A sine at `freq`. first_half_only → loud for [0, secs/2), silent after (a
    music envelope that makes ducking differential and measurable)."""
    t = np.arange(int(secs * _SR)) / _SR
    y = amp * np.sin(2 * np.pi * freq * t)
    if first_half_only:
        y[t >= secs / 2] = 0.0
    wavfile.write(path, _SR, y.astype(np.float32))
    return str(path)


def _music(path, secs, freq=220.0, amp=0.6, first_half_only=False):
    _tone_wav(path, secs, freq, amp, first_half_only)
    beats = tuple(round(k * 0.5, 3) for k in range(int(secs / 0.5)))
    return MusicSpec(track=str(path), start_offset=0.0, duration=float(secs), tempo=120.0,
                     beats=beats, energy=(0.3,), energy_hz=2.0)


def _band_rms(samples, sr, freq):
    """RMS magnitude at `freq` via a single-bin DFT — isolates the ambient tone."""
    n = len(samples)
    k = np.exp(-2j * np.pi * freq * np.arange(n) / sr)
    return abs(np.dot(samples, k)) / n


@pytest.mark.integration
def test_mix_with_ambient_hits_target_loudness(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    ms = _music(tmp_path / "m.wav", secs=6)
    seg = _tone_wav(tmp_path / "seg.wav", secs=6, freq=880, amp=0.5)
    stem = mix.mix(ms, str(tmp_path / "out"), dur=6.0, segments=[(seg, 6.0)])
    measured = check_reel._loudnorm_measure(stem)
    assert abs(measured - (-14.0)) <= 1.0            # check_reel's real loudness gate (±1 of −14)


@pytest.mark.integration
def test_ambient_ducks_under_loud_music(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    # music (220 Hz) loud for the first half, silent after; ambient (880 Hz) constant.
    ms = _music(tmp_path / "m.wav", secs=6, first_half_only=True)
    seg = _tone_wav(tmp_path / "seg.wav", secs=6, freq=880, amp=0.5)
    stem = mix.mix(ms, str(tmp_path / "out"), dur=6.0, segments=[(seg, 6.0)])
    dec = str(tmp_path / "dec.wav")
    proc.run(["ffmpeg", "-y", "-i", stem, "-ac", "1", "-ar", str(_SR), dec])
    sr, y = wavfile.read(dec)
    y = y.astype(np.float64)
    half = len(y) // 2
    loud = _band_rms(y[:half], sr, 880)              # music loud here → ambient ducked
    quiet = _band_rms(y[half:], sr, 880)             # music silent here → ambient full
    assert loud < quiet * 0.9                        # the duck attenuates the ambient band
```

- [x] **Step 2: Run the ambient integration proofs**

Run: `.venv/bin/python -m pytest tests/integration/test_ambient.py -v ; echo "EXIT: $?"`
Expected: PASS (2 passed), or SKIPPED if ffmpeg is unavailable. If it fails on the duck ratio, the sidechaincompress params in `mix` are the tuning surface — but with `threshold=0.03:ratio=4` and a 0.6-amplitude music key the 0.9 margin holds.

- [x] **Step 3: Point the build_reel golden at real segment manifests**

In `tests/integration/test_music_spine.py`, the `test_build_reel_delivers_reel_with_audio_stream` builds a `ReelManifest` with stub manifests (`manifest={"_": 0}`). With `ambient=True` (now the default) the stem hook reads `manifest["segment"]`/`["target_dur"]`, so give them real values (the reframed clips `ep0`/`ep1` are silent, so `_build_ambient` returns `None` → the stem stays music-only — this proves the default path survives real, audioless segments):

```python
    d0 = check_reel._probe_dur(ep0)
    d1 = check_reel._probe_dur(ep1)
    rm = ReelManifest(
        episodes=[ReelEpisode(manifest={"segment": ep0, "target_dur": d0}, clip=ep0, route=str(tmp_path / "r0.json")),
                  ReelEpisode(manifest={"segment": ep1, "target_dur": d1}, clip=ep1, route=str(tmp_path / "r1.json"))],
        target_dur=dur, variety_min=4, color_delta_max=40.0, music=str(music_json))
```

- [x] **Step 4: Run the music-spine golden (still delivers with audio)**

Run: `.venv/bin/python -m pytest tests/integration/test_music_spine.py -v ; echo "EXIT: $?"`
Expected: PASS (3 passed), or SKIPPED without ffmpeg. The delivered reel still carries an aac stem and the loudness gate is green — the ambient path returned `None` (silent clips) and fell through to the music-only stem.

- [x] **Step 5: Commit**

```bash
git add tests/integration/test_ambient.py tests/integration/test_music_spine.py
git commit -m "test: real-ffmpeg ambient proofs (-14 LUFS + ducking) + default-path golden"
```

---

### Task 5: docs sync + registry

**Files:**
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`, `docs/specs/2026-07-05-montage-skillset-design.md`, `docs/specs/2026-07-11-music-spine-design.md`, `CLAUDE.md`

- [x] **Step 1: Run the full suite and capture the number**

Run: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`
Expected: PASS, EXIT 0. Note the `N passed` count for build-status.

- [x] **Step 2: Update `docs/build-status.md`**

Add a Done entry dated 2026-07-15 describing the ambient sub-slice (mix.segments + `_build_ambient`, `ReelManifest.ambient`, build_reel wiring, the two real-ffmpeg proofs), update the test count to the number from Step 1, and update the Next-action line (SFX whoosh is the remaining 5.12 piece).

- [x] **Step 3: Update `docs/pipeline-map.md`**

- Row 5.12 (line ~28): change the note to `music-only mix ✅ + ambient ducking ✅ (nat-sound ducked under music, ReelManifest.ambient); SFX ❌`. Status stays `◐` (SFX remains).
- The blocker table row 5.12 (line ~64): drop the stale `extract per-ep audio passthrough` blocker; change "Left to build" to `SFX whoosh (asset + transition placement)` with `Blocked by` = `none — extract preserves segment audio today`.
- Tally line (~71): unchanged (`13 ✅ · 2 ◐ · 1 ❌`) — 5.12 is still ◐.
- The "What's still missing" prose (~104): drop "ambient ducking" from the missing list; leave SFX.

- [x] **Step 4: Update the design specs**

- `docs/specs/2026-07-05-montage-skillset-design.md` §5.12 (the deferred blockquote at lines ~359-362): note that ambient ducking landed 2026-07-15 (source = preserved raw segments; `ReelManifest.ambient` default on); SFX whoosh remains the open piece.
- `docs/specs/2026-07-11-music-spine-design.md` §5 (the "Music-only mix v1. Ambient ducking … deferred" note, ~line 49-51): mark ambient ducking landed 2026-07-15, SFX still deferred.

- [x] **Step 5: Update `CLAUDE.md` registry**

Add two rows to the Quick Reference table pointing at `docs/specs/2026-07-15-ambient-ducking-design.md` and `docs/plans/2026-07-15-ambient-ducking.md`, one-line descriptions matching the existing style (e.g. "§5.12 ambient sub-slice: duck each clip's preserved nat-sound under the music inside mix's stem — `mix(segments=)` + `_build_ambient` + `ReelManifest.ambient`; SFX deferred").

- [x] **Step 6: Verify the whole suite once more, then commit**

Run: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`
Expected: PASS, EXIT 0.

```bash
git add docs/ CLAUDE.md
git commit -m "docs: sync build-status/pipeline-map/specs/registry — ambient ducking landed (5.12)"
```

---

## Self-Review

**1. Spec coverage** — every spec section maps to a task:
- §Scope 1 (ambient only) → whole plan; SFX absent by construction (Task 5 notes it deferred). ✓
- §Scope 2 (ON default + off switch) → Task 0 (`ambient=True` default) + Task 3 (`ambient=False` → `segments=None`). ✓
- §Scope 3 (ducked ambient, not music) → Task 2 graph (`sidechaincompress` main=ambient, key=music). ✓
- §Scope 4 (source = raw segments) → Task 3 (`manifest["segment"]`), Task 1 (`_build_ambient`). ✓
- §Scope 5 (one stem, deliver unchanged) → no deliver/check_reel task; Task 4 proves the stem still gates at −14. ✓
- §2 filtergraph → Task 2 (realized with `volume=0.6` instead of `amix weights='1 0.6'` to avoid the filtergraph space-in-option; equivalent — ambient sits below the music before the duck; spec §2 updated to match). ✓
- §3 `_build_ambient` (audio→wav, video-only→anullsrc, all-silent→None, concat order) → Task 1. ✓
- §4 contract (`ReelManifest.ambient`) → Task 0. ✓
- §5 build_reel wiring → Task 3. ✓
- §6 edge cases (missing path raises, all-silent→None, apad, amix=first pins length) → Task 1 (apad, None) + Task 2 (amix=first) + Task 4 golden (real silent segments). ✓
- §7 landmines (sync via amix=first, audio-seek-exempt) → Task 2 + Task 1 comments + the conventions block. ✓
- §8 testing (unit + real-ffmpeg + golden) → Tasks 1-4. ✓
- §10 doc sync → Task 5. ✓

**2. Placeholder scan** — no TBD/TODO; every code step shows complete code; every test has real assertions; every run command has an expected result. ✓

**3. Type consistency** — `mix(music, out_dir, dur, segments=None)` and `_build_ambient(segments, tmp_dir) -> str | None` are used identically in Tasks 1-4; `segments` is `list[tuple[str, float]]` everywhere (build_reel builds `[(e.manifest["segment"], e.manifest["target_dur"]), …]`); `ReelManifest.ambient: bool` used consistently in Tasks 0/3. The `mix.mix` mock signature `lambda mus, wd, dur, segments=None` matches the real signature in every patched/added build_reel test. ✓

**Note for the implementer:** Task 3 Step 1 *must* run before Task 3's new tests — the pre-existing music tests break the moment `build_reel` passes `segments=` (their mocks reject the kwarg), so patch the fixtures in the same task. Task 4 Step 3 is likewise mandatory: the golden's stub manifest would `KeyError` on `manifest["segment"]` under the new default.
