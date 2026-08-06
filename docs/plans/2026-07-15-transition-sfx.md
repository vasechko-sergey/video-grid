# Transition SFX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close stage §5.12 by placing an ffmpeg-synthesized whoosh on the reel's major transitions, mixed un-ducked into the one audio stem before the final loudnorm.

**Architecture:** `mix()` grows two optional layers over the music fragment — the existing ducked ambient bed and a new SFX bed. The SFX bed is a seeded synthesized whoosh (`_whoosh`) placed by `adelay` at each **major** internal cut (`_major_cuts`: `max(neighbour dur) > factor·median`, min-gap throttled) via `_build_sfx`. `mix` composes the filter_complex over whichever beds exist (four cases; the music-only and ambient-only strings stay byte-identical to today → regression-pinned). `ReelManifest.sfx` (default `False`) is the opt-in switch; `build_reel` passes the episode `segments` and the `ambient`/`sfx` flags when either layer is on. `deliver`/`check_reel` are untouched — one pre-normalized −14 LUFS stem in, as with the ambient slice.

**Tech Stack:** Python 3, ffmpeg (`anoisesrc`/`bandpass`/`afade`/`adelay`/`amix`/`sidechaincompress`/`loudnorm`), `statistics.median`, pytest (`scipy.io.wavfile` + numpy for the real-ffmpeg golden), the repo's `proc.run` shell + `MusicSpec`/`ReelManifest` config-specs.

Design spec: [docs/specs/2026-07-15-transition-sfx-design.md](../specs/2026-07-15-transition-sfx-design.md).

---

## File Structure

| File | Δ | Responsibility |
|------|---|----------------|
| `scripts/lib/models.py` | EDIT | `ReelManifest.sfx: bool = False` + `__post_init__` bool guard + `from_dict` `d.get("sfx", False)` |
| `scripts/mix.py` | EDIT | `import statistics`; SFX constants; `_major_cuts(durs)` (pure), `_whoosh(tmp_dir)`, `_build_sfx(durs, tmp_dir)`; `_mix_graph(has_ambient, has_sfx)`; `mix(..., ambient=True, sfx=False)` composes the layers |
| `scripts/build_reel.py` | EDIT | stem hook: `want = rm.ambient or rm.sfx`; pass `segments`+`ambient=`+`sfx=` |
| `tests/lib/test_models.py` | EDIT | 3 `sfx` tests (default False / true from_dict / non-bool raises) |
| `tests/test_mix.py` | EDIT | `import pytest`; `_major_cuts` (pure) + `_build_sfx` (mocked) + `mix` graph-case tests |
| `tests/lib/test_build_reel.py` | EDIT | patch the 4 `mix.mix` mock signatures + `_rm_music(sfx=)`; 2 new flag-flow tests |
| `tests/integration/test_sfx.py` | CREATE | real-ffmpeg −14 + whoosh-placement proofs (skip-if-no-ffmpeg) |
| `docs/*`, `CLAUDE.md` | EDIT | doc sync (Task 5): 5.12 ◐→✅ |

`deliver.py`, `check_reel.py`, `draft.py`, `assembly.py` — **no change** (one stem in; SFX uses `adelay`+`amix`, not `concat`).

---

## Task 0: `ReelManifest.sfx` contract

**Files:**
- Modify: `scripts/lib/models.py:705` (field), `:726-728` (guard), `:754` (from_dict)
- Test: `tests/lib/test_models.py` (after the `sfx`-adjacent ambient tests, ~`:647`)

- [x] **Step 1: Write the failing tests**

Append to `tests/lib/test_models.py` (mirrors the existing `ambient` trio at `:637-647`; `_reel_dict(**over)` is already defined at `:511`):

```python
def test_reel_manifest_sfx_defaults_false():
    assert m.ReelManifest.from_dict(_reel_dict()).sfx is False


def test_reel_manifest_sfx_true_from_dict():
    assert m.ReelManifest.from_dict(_reel_dict(sfx=True)).sfx is True


def test_reel_manifest_rejects_non_bool_sfx():
    with pytest.raises(ValueError, match="sfx"):
        m.ReelManifest.from_dict(_reel_dict(sfx="yes"))
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -k sfx -q ; echo "EXIT: $?"`
Expected: FAIL (`AttributeError: 'ReelManifest' object has no attribute 'sfx'` / `TypeError` on the `sfx=` kwarg).

- [x] **Step 3: Add the field**

In `scripts/lib/models.py`, after the `ambient` field (`:705`):

```python
    ambient: bool = True               # duck each clip's nat-sound under the music (§5.12); False → pure-music stem
    sfx: bool = False                  # whoosh on major transitions (§5.12); default off (opt-in stylistic accent)
```

- [x] **Step 4: Add the guard**

After the `ambient` bool guard (`:726-728`), before `self.check_spec`:

```python
        if not isinstance(self.sfx, bool):
            raise ValueError(f"ReelManifest.sfx must be a bool (True → whoosh on major "
                             f"transitions, False → no SFX), got {self.sfx!r}")
```

- [x] **Step 5: Thread `from_dict`**

In `from_dict`'s `return cls(...)` (`:754`), add `sfx`:

```python
                   music=d.get("music"), ambient=d.get("ambient", True),
                   sfx=d.get("sfx", False))
```

- [x] **Step 6: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_models.py -q ; echo "EXIT: $?"`
Expected: PASS (all model tests green — the new trio + the untouched rest).

- [x] **Step 7: Commit**

```bash
git add scripts/lib/models.py tests/lib/test_models.py
git commit -m "feat: ReelManifest.sfx flag (default off) — the transition-SFX switch"
```

---

## Task 1: `_major_cuts` + `_whoosh` + `_build_sfx` (the SFX bed)

**Files:**
- Modify: `scripts/mix.py` (imports, constants after `_AR` at `:33`, three new module funcs)
- Test: `tests/test_mix.py` (add `import pytest`; new tests)

- [x] **Step 1: Write the failing tests**

At the top of `tests/test_mix.py` add `import pytest` (currently absent). Then append (the `_R` stub at `:7` is reused):

```python
# --- transition SFX (§5.12) -------------------------------------------------

def test_major_cuts_needs_two_clips():
    assert mix._major_cuts([5.0]) == []


def test_major_cuts_uniform_pacing_has_none():
    assert mix._major_cuts([2.0, 2.0, 2.0]) == []          # nothing exceeds the median → no accent


def test_major_cuts_one_held_shot():
    assert mix._major_cuts([3.0, 0.5, 0.5]) == pytest.approx([3.0])   # cut after the 3.0s hold


def test_major_cuts_throttle_drops_close_second():
    # majors fall at 4.0, 4.3, 8.3; 4.3 is within _MIN_GAP (0.6) of 4.0 → dropped
    assert mix._major_cuts([4.0, 0.3, 4.0, 0.3, 0.3]) == pytest.approx([4.0, 8.3])


def test_build_sfx_no_major_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(mix.proc, "run", lambda *a, **k: _R())
    monkeypatch.setattr(mix, "_whoosh", lambda d: d + "/w.wav")
    assert mix._build_sfx([2.0, 2.0, 2.0], str(tmp_path)) is None


def test_build_sfx_places_a_whoosh_at_each_major_cut(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run", lambda cmd, **k: (calls.append(cmd), _R())[1])
    monkeypatch.setattr(mix, "_whoosh", lambda d: d + "/w.wav")
    res = mix._build_sfx([3.0, 0.5, 0.5], str(tmp_path))
    assert res is not None and res.endswith("sfx.wav")
    joined = " ".join(map(str, calls[-1]))
    assert "asplit=1" in joined                                   # one major cut → one whoosh copy
    assert "adelay=2800:all=1" in joined                          # t=3.0 − _SFX_LEAD(0.2) = 2.8s
    assert "amix=inputs=2:duration=first:normalize=0" in joined   # base + 1 whoosh, levels kept
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mix.py -k "major_cuts or build_sfx" -q ; echo "EXIT: $?"`
Expected: FAIL (`AttributeError: module 'scripts.mix' has no attribute '_major_cuts'`).

- [x] **Step 3: Add the import + constants**

In `scripts/mix.py`, add `import statistics` to the stdlib imports (`:5-8`, keep them sorted):

```python
import argparse
import os
import re
import statistics
import tempfile
```

After the `_AR = 48000` line (`:33`), add the SFX constant block:

```python
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
```

- [x] **Step 4: Add the three functions**

After `_build_ambient` (`:67`), add:

```python
def _major_cuts(durs: list[float]) -> list[float]:
    """Cumulative offsets of the reel's MAJOR internal cuts (EDL order). A cut between
    ep[k] and ep[k+1] sits at T[k]=sum(durs[:k+1]); it is major when max(durs[k],
    durs[k+1]) > _MAJOR_FACTOR * median(durs) — i.e. it touches a held/hero shot on
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
    proc.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
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
    proc.run(["ffmpeg", "-y", "-t", f"{total}", "-f", "lavfi", "-i",
              f"anullsrc=r={_AR}:cl=stereo", "-i", whoosh,
              "-filter_complex", ";".join(fc), "-map", "[sfx]",
              "-c:a", "pcm_s16le", out])
    return out
```

- [x] **Step 5: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_mix.py -k "major_cuts or build_sfx" -q ; echo "EXIT: $?"`
Expected: PASS (7 passed).

- [x] **Step 6: Commit**

```bash
git add scripts/mix.py tests/test_mix.py
git commit -m "feat: mix._build_sfx — synth whoosh placed on major transitions"
```

---

## Task 2: `mix()` composes the ambient/sfx layers

**Files:**
- Modify: `scripts/mix.py` (module docstring `:1-4`; new `_mix_graph`; `mix()` signature `:70-71` + body `:95-110`)
- Test: `tests/test_mix.py`

- [x] **Step 1: Write the failing tests**

Append to `tests/test_mix.py` (`_ms`/`_loudnorm_stderr` helpers at `:47-55` already exist):

```python
def test_mix_sfx_only_makes_no_sidechain(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    monkeypatch.setattr(mix, "_build_sfx", lambda durs, d: d + "/sfx.wav")
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0,
            segments=[("s0.mp4", 3.0), ("s1.mp4", 3.0)], ambient=False, sfx=True)
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "sidechaincompress" not in joined and "asplit" not in joined  # no ambient duck
    assert "[sfx]" in joined and "amix=inputs=2:duration=first" in joined  # music + sfx on top


def test_mix_ambient_and_sfx_compose_three_inputs(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    monkeypatch.setattr(mix, "_build_ambient", lambda segs, d: d + "/ambient.wav")
    monkeypatch.setattr(mix, "_build_sfx", lambda durs, d: d + "/sfx.wav")
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0,
            segments=[("s0.mp4", 3.0), ("s1.mp4", 3.0)], ambient=True, sfx=True)
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert "sidechaincompress" in joined                              # ambient still ducked
    assert "[sfx]" in joined                                          # sfx term present
    assert "amix=inputs=3:duration=first" in joined                  # music + ducked ambient + sfx


def test_mix_sfx_false_leaves_ambient_graph_unchanged(tmp_path, monkeypatch):
    # regression: sfx defaults off → the ambient-only graph is byte-identical to today
    calls = []
    monkeypatch.setattr(mix.proc, "run",
                        lambda cmd, **k: (calls.append(cmd), _R(stderr=_loudnorm_stderr()))[1])
    monkeypatch.setattr(mix, "_build_ambient", lambda segs, d: d + "/ambient.wav")
    mix.mix(_ms(tmp_path), str(tmp_path / "out"), 6.0, segments=[("s0.mp4", 6.0)])
    joined = " ".join(" ".join(map(str, c)) for c in calls)
    assert ("[0:a]asplit=2[msum][mkey];[1:a]volume=0.6[amb];"
            "[amb][mkey]sidechaincompress=threshold=0.03:ratio=4:attack=20:release=300[duck];"
            "[msum][duck]amix=inputs=2:duration=first[mixed]") in joined
    assert "[sfx]" not in joined
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mix.py -k "sfx_only or ambient_and_sfx or sfx_false" -q ; echo "EXIT: $?"`
Expected: FAIL (`mix()` has no `sfx`/`ambient` kwargs → `TypeError`).

- [x] **Step 3: Update the module docstring**

Replace `scripts/mix.py:1-4`:

```python
"""audio-mix (montage §5.12): build the reel's audio stem from a MusicSpec — seek the
chosen fragment, fade, two-pass loudnorm to −14 LUFS → aac. Given `segments` and
`ambient`, each clip's preserved nat-sound is ducked under the music
(sidechaincompress); with `sfx`, a synthesized whoosh is placed on the reel's major
transitions and mixed in on top. Both bake into the one stem before the final
loudnorm, so deliver/check_reel see a single pre-normalized signal."""
```

- [x] **Step 4: Add `_mix_graph`**

After `_build_sfx`, before `mix()`:

```python
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
```

- [x] **Step 5: Grow `mix()`**

Signature (`:70-71`):

```python
def mix(music: MusicSpec, out_dir: str, dur: float,
        segments: list[tuple[str, float]] | None = None,
        ambient: bool = True, sfx: bool = False) -> str:
    """Audio stem for a `dur`-second reel → out_dir/audio.m4a (aac, −14 LUFS). With
    `segments` ([(raw_segment_path, episode_dur), …] in reel order) and `ambient`,
    each clip's nat-sound is ducked under the music; with `sfx`, a synthesized whoosh
    is placed on the reel's major transitions and mixed in on top. Both bake into the
    one stem before the final loudnorm; without them the stem is music-only, exactly
    as before."""
```

Replace the body block that today runs from `norm_src = frag` through the ambient `if segments:` branch (`:95-110`) with:

```python
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
            proc.run(["ffmpeg", "-y", *inputs, "-filter_complex",
                      _mix_graph(amb is not None, sfx_bed is not None),
                      "-map", "[mixed]", mixed])
            norm_src = mixed
```

(The `dur` guards, the seek+fade `frag` pass above, and the `_measure` + loudnorm pass below stay exactly as they are.)

- [x] **Step 6: Run the mix suite**

Run: `.venv/bin/python -m pytest tests/test_mix.py -q ; echo "EXIT: $?"`
Expected: PASS — the three new graph tests **and** the pre-existing ambient/music-only tests (`test_mix_music_only_makes_no_sidechain`, `test_mix_with_ambient_inserts_sidechain_and_pins_length`, `test_mix_all_silent_bed_falls_back_to_music_only`) stay green.

- [x] **Step 7: Commit**

```bash
git add scripts/mix.py tests/test_mix.py
git commit -m "feat: mix() composes optional ambient+sfx layers (ambient-only graph byte-identical)"
```

---

## Task 3: `build_reel` wiring

**Files:**
- Modify: `scripts/build_reel.py:47-51` (stem hook)
- Test: `tests/lib/test_build_reel.py` (patch 4 `mix.mix` mocks + `_rm_music`; 2 new tests)

- [x] **Step 1: Patch the mock signatures + add failing tests**

In `tests/lib/test_build_reel.py`, every `build_reel.mix.mix` monkeypatch lambda must accept the new kwargs (build_reel will pass `ambient=`/`sfx=` → the current `segments=None`-only lambdas would `TypeError`). Update all four:

- `_wire_music` (`:200-201`):
  ```python
  monkeypatch.setattr(build_reel.mix, "mix",
                      lambda mus, wd, dur, segments=None, ambient=True, sfx=False:
                      (mixed.append((wd, dur)), "stem.m4a")[1])
  ```
- `test_build_reel_music_delivers_after_full_reprocess_budget` (`:259-260`):
  ```python
  monkeypatch.setattr(build_reel.mix, "mix",
                      lambda mus, wd, dur, segments=None, ambient=True, sfx=False:
                      (mixed.append(dur), "stem.m4a")[1])
  ```
- `test_build_reel_passes_segments_when_ambient` (`:274-275`):
  ```python
  monkeypatch.setattr(build_reel.mix, "mix",
                      lambda mus, wd, dur, segments=None, ambient=True, sfx=False:
                      (got.setdefault("segments", segments), "stem.m4a")[1])
  ```
- `test_build_reel_ambient_false_passes_no_segments` (`:285-286`):
  ```python
  monkeypatch.setattr(build_reel.mix, "mix",
                      lambda mus, wd, dur, segments=None, ambient=True, sfx=False:
                      (got.setdefault("segments", segments), "stem.m4a")[1])
  ```

Extend the `_rm_music` helper (`:170-174`) with a `sfx` param:

```python
def _rm_music(music, ambient=True, sfx=False):
    ep0 = ReelEpisode(manifest={"segment": "s0.mp4", "target_dur": 3.0}, clip="c0.mp4", route="r0.json")
    ep1 = ReelEpisode(manifest={"segment": "s1.mp4", "target_dur": 3.0}, clip="c1.mp4", route="r1.json")
    return ReelManifest(episodes=[ep0, ep1], target_dur=6.0, variety_min=4,
                        music=music, ambient=ambient, sfx=sfx)
```

Append two tests (after `test_build_reel_ambient_false_passes_no_segments`, `:291`):

```python
def test_build_reel_passes_sfx_flag_when_set(tmp_path, monkeypatch):
    # sfx=True → build_reel hands mix the flag AND the (segment, target_dur) list (durs drive placement)
    mixed, delivered, got = [], [], {}
    _wire_music(monkeypatch, [_passing(), _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.mix, "mix",
                        lambda mus, wd, dur, segments=None, ambient=True, sfx=False:
                        (got.update(segments=segments, sfx=sfx), "stem.m4a")[1])
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    build_reel.build_reel(_rm_music(music=str(tmp_path / "MUSIC.json"), sfx=True),
                          str(tmp_path / "out"), str(tmp_path / "work"))
    assert got["sfx"] is True
    assert got["segments"] == [("s0.mp4", 3.0), ("s1.mp4", 3.0)]


def test_build_reel_sfx_only_still_passes_segments(tmp_path, monkeypatch):
    # ambient OFF but sfx ON → segments still handed over (sfx needs the durations)
    mixed, delivered, got = [], [], {}
    _wire_music(monkeypatch, [_passing(), _passing()], mixed, delivered)
    monkeypatch.setattr(build_reel.mix, "mix",
                        lambda mus, wd, dur, segments=None, ambient=True, sfx=False:
                        (got.update(segments=segments, ambient=ambient, sfx=sfx), "stem.m4a")[1])
    monkeypatch.setattr(build_reel.MusicSpec, "from_json", staticmethod(lambda p: _fake_music()))
    build_reel.build_reel(_rm_music(music=str(tmp_path / "MUSIC.json"), ambient=False, sfx=True),
                          str(tmp_path / "out"), str(tmp_path / "work"))
    assert got["ambient"] is False and got["sfx"] is True
    assert got["segments"] == [("s0.mp4", 3.0), ("s1.mp4", 3.0)]
```

- [x] **Step 2: Run to verify (some fail)**

Run: `.venv/bin/python -m pytest tests/lib/test_build_reel.py -q ; echo "EXIT: $?"`
Expected: the two new tests FAIL (`got["sfx"]`/`got["ambient"]` not set — build_reel doesn't pass the flags yet). The mock-signature edits keep the rest green.

- [x] **Step 3: Wire the stem hook**

Replace `scripts/build_reel.py:47-51`:

```python
            if music is not None and audio is None:  # picture passed → build the stem once, re-check with it
                want = rm.ambient or rm.sfx
                segments = ([(e.manifest["segment"], e.manifest["target_dur"]) for e in rm.episodes]
                            if want else None)
                audio = mix.mix(music, work_dir, check_reel._probe_dur(master),
                                segments=segments, ambient=rm.ambient, sfx=rm.sfx)
                continue                             # need_assemble stays False — clips unchanged, no re-assemble
```

- [x] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_build_reel.py -q ; echo "EXIT: $?"`
Expected: PASS (all — the two new flag-flow tests + the pre-existing A.5/music tests).

- [x] **Step 5: Commit**

```bash
git add scripts/build_reel.py tests/lib/test_build_reel.py
git commit -m "feat: build_reel passes segments+ambient/sfx flags when either audio layer is on"
```

---

## Task 4: real-ffmpeg proofs (`tests/integration/test_sfx.py`)

**Files:**
- Create: `tests/integration/test_sfx.py`

- [x] **Step 1: Write the tests**

```python
"""Real-ffmpeg proofs for transition SFX (design §8): (A) mix with a whoosh layer
still hits −14 LUFS; (B) the whoosh lands on the major cut and only there. Synthetic
known-answer signals, mirroring tests/integration/test_ambient.py."""
import shutil

import numpy as np
import pytest
from scipy.io import wavfile

from scripts import check_reel, mix
from scripts.lib import proc
from scripts.lib.models import MusicSpec

_SR = 22050


def _music(path, secs, amp=0.3):
    """A steady 220 Hz tone + a MusicSpec describing it (a beat every 0.5s)."""
    n = int(secs * _SR)
    y = (amp * np.sin(2 * np.pi * 220 * np.arange(n) / _SR)).astype(np.float32)
    wavfile.write(path, _SR, y)
    beats = tuple(round(k * 0.5, 3) for k in range(int(secs / 0.5)))
    return MusicSpec(track=str(path), start_offset=0.0, duration=float(secs), tempo=120.0,
                     beats=beats, energy=(0.3,), energy_hz=2.0)


def _win_rms(y, sr, t0, t1):
    seg = y[int(t0 * sr):int(t1 * sr)]
    return float(np.sqrt(np.mean(seg * seg))) if len(seg) else 0.0


@pytest.mark.integration
def test_mix_with_sfx_hits_target_loudness(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    ms = _music(tmp_path / "m.wav", secs=6)
    seg = str(tmp_path / "m.wav")                          # ambient off → seg path unused; durs drive sfx
    segments = [(seg, 3.0), (seg, 0.5), (seg, 0.5)]        # median 0.5 → one major cut at t≈3.0
    stem = mix.mix(ms, str(tmp_path / "out"), dur=4.0, segments=segments, ambient=False, sfx=True)
    measured = check_reel._loudnorm_measure(stem)
    assert abs(measured - (-14.0)) <= 1.0                 # loudnorm still lands with the whoosh layer


@pytest.mark.integration
def test_sfx_lands_on_the_major_cut_only(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    ms = _music(tmp_path / "m.wav", secs=6, amp=0.1)       # quiet steady music; the whoosh is the transient
    seg = str(tmp_path / "m.wav")
    segments = [(seg, 3.0), (seg, 0.5), (seg, 0.5)]        # only the cut after ep0 (max(3,0.5)>0.5) is major
    stem = mix.mix(ms, str(tmp_path / "out"), dur=4.0, segments=segments, ambient=False, sfx=True)
    dec = str(tmp_path / "dec.wav")
    proc.run(["ffmpeg", "-y", "-i", stem, "-ac", "1", "-ar", str(_SR), dec])
    sr, y = wavfile.read(dec)
    y = y.astype(np.float64)
    at_cut = _win_rms(y, sr, 2.85, 3.25)                  # the whoosh straddles t=3.0
    control = _win_rms(y, sr, 1.30, 1.70)                 # steady music only, no cut here
    assert at_cut > control * 2.0                         # the whoosh transient dominates the cut window
```

- [x] **Step 2: Run the integration tests**

Run: `.venv/bin/python -m pytest tests/integration/test_sfx.py -q ; echo "EXIT: $?"`
Expected: PASS (2 passed), or SKIP if ffmpeg is absent. If `test_sfx_lands_on_the_major_cut_only` is marginal (loudnorm's true-peak limiter can clamp the transient), first confirm the whoosh is present, then, if needed, lower the control `amp` or raise `_SFX_MIX` — do **not** loosen the assertion below a clear margin. Report the measured `at_cut`/`control` ratio.

- [x] **Step 3: Commit**

```bash
git add tests/integration/test_sfx.py
git commit -m "test: real-ffmpeg SFX proofs — −14 LUFS + whoosh lands on the major cut"
```

---

## Task 5: docs sync + registry

**Files:** `docs/build-status.md`, `docs/pipeline-map.md`, `docs/specs/2026-07-05-montage-skillset-design.md`, `docs/specs/2026-07-11-music-spine-design.md`, `CLAUDE.md`

- [x] **Step 1: Run the full suite for the real count**

Run: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`
Expected: all green. Note the `<N> passed / <M> skipped` — use the real numbers in build-status below.

- [x] **Step 2: `docs/pipeline-map.md`**

- `_Last updated:_` line — keep `2026-07-15`.
- Stage 5.12 row (`:28`) → status ✅, note SFX built:
  ```
  | 5.12 | audio-mix | ✅ | music-only mix ✅ + ambient ducking ✅ + SFX whoosh ✅ (synth whoosh on major transitions, `ReelManifest.sfx`); §5.12 complete | **Phase B — music spine** |
  ```
- Remaining-work row (`:64`):
  ```
  | 5.12 | audio-mix | ✅ | — (2026-07-15) | — | richer mix |
  ```
- Tally (`:71`): `13 ✅ · 2 ◐ · 1 ❌` → `14 ✅ · 1 ◐ · 1 ❌`.
- Critical-path note (`:88`): `(B4 pacing, 5.9 draft, 5.12 ambient)` → `(B4 pacing, 5.9 draft, 5.12 ambient+SFX)`.
- "What produces a reel today" (`:104-105`): drop `SFX (5.12)` from the "rest of audio" list.
- Phase roadmap Upcoming (`:125`): drop `SFX (5.12),` from Remaining; note 5.12 is complete (music-only + ambient + SFX).

- [x] **Step 3: `docs/specs/2026-07-05-montage-skillset-design.md` §5.12**

In the §5.12 block (`:355-369`), flip the "SFX still deferred" note to built: SFX (whoosh on major transitions) landed 2026-07-15 — synth whoosh, `ReelManifest.sfx` (off by default), placed on `max(neighbour dur) > median` cuts, mixed un-ducked before loudnorm; cross-reference `docs/specs/2026-07-15-transition-sfx-design.md`. §5.12 is now complete.

- [x] **Step 4: `docs/specs/2026-07-11-music-spine-design.md`**

Where the music-only decision and non-goals mention SFX deferred (`:49-53`, `:170-172`, `:337`, `:357`): note SFX landed 2026-07-15 (`docs/specs/2026-07-15-transition-sfx-design.md`), so the only remaining Phase-B open item is the pacing retry-time auto-fix.

- [x] **Step 5: `docs/build-status.md`**

Add a Done entry (use the real suite count from Step 1) and update the "next action" pointer so SFX is no longer next:

```
- **Transition SFX (stage 5.12, whoosh sub-slice) — 2026-07-15.** ffmpeg-synthesized
  whoosh (seeded pink-noise → bandpass → fade swell, no assets) placed on the reel's
  major transitions (`max(neighbour dur) > _MAJOR_FACTOR·median`, `_MIN_GAP`-throttled)
  and mixed un-ducked on top of the music+ambient stem before the final −14 loudnorm —
  `mix(music, out, dur, segments=, ambient=, sfx=)` grows `_major_cuts`/`_whoosh`/
  `_build_sfx` and composes the filtergraph over the optional ambient/sfx layers
  (music-only and ambient-only graphs byte-identical, regression-pinned); `ReelManifest.sfx`
  (off by default) is the opt-in switch; `build_reel` passes `segments`+flags when either
  audio layer is on. deliver/check_reel unchanged (one pre-normalized stem). **Closes §5.12.**
  Suite <N> passed / <M> skipped.
```

- [x] **Step 6: `CLAUDE.md` registry**

Add two rows after the Ambient-ducking plan row, and extend the Music-spine row's tail (`… ambient ducking landed 2026-07-15`) with `; SFX whoosh landed 2026-07-15`:

```
| Transition-SFX design | [2026-07-15-transition-sfx-design.md](docs/specs/2026-07-15-transition-sfx-design.md) | §5.12 SFX sub-slice: ffmpeg-synth whoosh (pink-noise→bandpass→swell, no assets, seeded) on major transitions (`max(neighbour dur) > median`, min-gap throttled), mixed un-ducked atop music+ambient in mix's stem — `mix(sfx=)` + `_major_cuts`/`_whoosh`/`_build_sfx` + `ReelManifest.sfx` (off by default); deliver/check_reel unchanged. Closes 5.12. |
| Transition-SFX plan | [2026-07-15-transition-sfx.md](docs/plans/2026-07-15-transition-sfx.md) | Tasks 0-5: `ReelManifest.sfx`, `_major_cuts`/`_whoosh`/`_build_sfx`, mix filtergraph compose (4 cases, ambient-only byte-identical), build_reel wiring, real-ffmpeg −14/placement proofs, docs sync. |
```

- [x] **Step 7: Verify + commit**

Run: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`
Expected: all green (unchanged from Step 1 — docs only).

```bash
git add docs/ CLAUDE.md
git commit -m "docs: sync build-status/pipeline-map/specs/registry — SFX landed, 5.12 complete"
```

---

## Self-Review

**1. Spec coverage** — every §-section of the design maps to a task:
- §1/§4 contract (`ReelManifest.sfx`) → Task 0.
- §3 `_build_sfx`/`_whoosh`/`_major_cuts` + §4 constants → Task 1.
- §2 filtergraph (four cases, ambient-only byte-identical) → Task 2.
- §5 build_reel wiring → Task 3.
- §8 testing (unit in Tasks 0-2, real-ffmpeg in Task 4).
- §10 doc sync → Task 5.
- §6 edge cases: `<2` clips / no-major → `None` (Task 1 tests); `sfx=True` but `segments=None` → `_build_sfx` never called (mix gate `segments and sfx`); adelay clamped `≥0` (Task 1 impl). §9 non-goals carry no task by design.

**2. Placeholder scan** — no TBD/TODO; every code step shows complete code. The only intentional runtime substitutions are the real suite counts `<N>/<M>` in Task 5 (Step 1 computes them) — not placeholders in code.

**3. Type/name consistency** — `_major_cuts(durs) -> list[float]`, `_whoosh(tmp_dir) -> str`, `_build_sfx(durs, tmp_dir) -> str | None`, `_mix_graph(has_ambient, has_sfx) -> str`, `mix(..., ambient=True, sfx=False) -> str`, `ReelManifest.sfx: bool` — used identically across tasks and tests. Constants (`_MAJOR_FACTOR`, `_MIN_GAP`, `_SFX_DUR/FREQ/Q/ATTACK/LEAD/MIX/SEED`) referenced only where defined (mix.py). `_SFX_LEAD=0.2` ↔ the `adelay=2800` test (`(3.0−0.2)·1000`). The composed ambient-only graph string in the Task 2 regression test is char-for-char the current `mix.py` literal.

**4. Float-equality guard** — `_major_cuts` offsets accumulate floats, so the Task 1 tests compare with `pytest.approx` (added `import pytest`); the `adelay` ms assertion is exact because `int(round(...))` collapses the drift.
