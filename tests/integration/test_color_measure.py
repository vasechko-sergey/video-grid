import json

import pytest
from scripts import color_measure
from scripts.color_measure import measure_profile
from scripts.lib import color, ffbin, manifest as manifest_lib, matchgrade, proc

pytestmark = pytest.mark.integration


def _flat_gray(path, level):
    # a 2s flat-gray clip at a known luma level (0-255)
    hexv = f"0x{level:02x}{level:02x}{level:02x}"
    proc.run([ffbin.ffmpeg(), "-y", "-f", "lavfi", "-i", f"color=c={hexv}:s=320x240:d=2:r=25",
              "-frames:v", "50", "-pix_fmt", "yuv420p", str(path)])


def test_measure_profile_flat_gray(tmp_path):
    clip = tmp_path / "gray.mp4"
    _flat_gray(clip, 120)
    p5, p50, p95 = measure_profile(str(clip))
    # a flat field → all three percentiles near the known level (allow codec/round slop)
    assert abs(p50 - 120) <= 8 and abs(p5 - 120) <= 12 and abs(p95 - 120) <= 12


def test_measure_profile_three_bands(tmp_path):
    """dark | mid | bright at 1:2:1 → p5 low, p50 in the middle band, p95 high.

    THREE bands and not two, found when the 160-wide downscale came out on
    2026-08-19: a 50/50 two-band frame has p5 == p50 by construction, because half
    its pixels sit at the dark value. The old two-band version passed only on the
    downscale's own edge blur, which invented intermediate values at the boundary
    and pulled p50 off p5 — the assertion was reading the resampler, not the
    frame. Same 1:2:1 shape test_matchgrade.py's `_three_band` already uses, and
    for the same reason it documents."""
    clip = tmp_path / "bands.mp4"
    proc.run([ffbin.ffmpeg(), "-y",
              "-f", "lavfi", "-i", "color=c=0x202020:s=80x240:d=2:r=25",
              "-f", "lavfi", "-i", "color=c=0x808080:s=160x240:d=2:r=25",
              "-f", "lavfi", "-i", "color=c=0xE0E0E0:s=80x240:d=2:r=25",
              "-filter_complex", "hstack=inputs=3", "-frames:v", "50",
              "-pix_fmt", "yuv420p", str(clip)])
    p5, p50, p95 = measure_profile(str(clip))
    assert p5 < 80 and p95 > 180 and p5 < p50 < p95


def _two_band_clip(tmp_path, dark=40, bright=200):
    """640x640, 1s, 30fps: a dark band over a bright one, tv range — the shape
    clip_percentiles reads off a FINISHED file (no crop, no manifest)."""
    clip = tmp_path / "two_band.mp4"
    proc.run([ffbin.ffmpeg(), "-y",
              "-f", "lavfi", "-i", f"color=c=0x{dark:02x}{dark:02x}{dark:02x}:s=640x320:d=1:r=30",
              "-f", "lavfi", "-i", f"color=c=0x{bright:02x}{bright:02x}{bright:02x}:s=640x320:d=1:r=30",
              "-filter_complex", "vstack=inputs=2", "-frames:v", "30",
              "-pix_fmt", "yuv420p", "-color_range", "tv", str(clip)])
    return clip


def _banded_episode(tmp_path, top=240, bottom=100):
    """(src, manifest_dict, route_json): a 640x1280 source stacking a bright
    band over a darker one, plus a minimal `fill` episode at a 1:1 canvas whose
    route sits in the bottom (darker) band.

    layout `fill` + crop_aspect "canvas" (fill's own default) + canvas [1, 1] crops
    the largest SQUARE that fits the 640x1280 source — 640x640 — and geometry.crop_y
    places it against the route's mean y. A route pinned at y=960 (the bottom
    band's own centre) lands the crop at y=640..1280 exactly: the top band is
    excluded, not merely down-weighted, which is what makes the two readings
    (whole frame vs. crop) disagree.

    Defaults (240/100) are the design's own dramatic case — the top band blown
    out, the bottom mid-grey. A caller can pass a smaller, realistic gap (e.g.
    top=120, bottom=100 — near the 14-unit median and 36-unit maximum the design
    measured against real footage) to prove the discrimination survives at
    production scale, not only at a 35x margin."""
    src = tmp_path / "banded.mp4"
    proc.run([ffbin.ffmpeg(), "-y",
              "-f", "lavfi", "-i", f"color=c=0x{top:02x}{top:02x}{top:02x}:s=640x640:d=2:r=30",
              "-f", "lavfi", "-i", f"color=c=0x{bottom:02x}{bottom:02x}{bottom:02x}:s=640x640:d=2:r=30",
              "-filter_complex", "vstack=inputs=2", "-frames:v", "60",
              "-pix_fmt", "yuv420p", "-color_range", "tv", str(src)])
    md = {"segment": str(src), "out_path": "ep.mp4", "composition": "center",
          "grid": "thirds", "canvas": [1, 1], "target_dur": 2.0}
    route = [dict(t=0.0, x=320.0, y=960.0, w=100.0, h=100.0),
             dict(t=2.0, x=320.0, y=960.0, w=100.0, h=100.0)]
    route_path = tmp_path / "route.json"
    route_path.write_text(json.dumps(route))
    return str(src), md, str(route_path)


def test_clip_percentiles_reads_a_finished_file(tmp_path):
    """Two bands, 50/50: p5 lands in the dark one, p95 in the bright one."""
    clip = _two_band_clip(tmp_path, dark=40, bright=200)      # helper below
    p5, p50, p95 = color_measure.clip_percentiles(str(clip), [0.5])
    assert p5 < 60 and p95 > 180


def _three_phase_clip(tmp_path, levels=(40, 120, 220), dur=1.0, fps=30):
    """A clip whose flat luma level changes over TIME, once per phase (video concat,
    not hstack/vstack): a spatial-band clip (like _two_band_clip) reads identically at
    ANY t, so it cannot discriminate whether a batched read attributed the right
    span's bytes to the right slot — only a clip whose content actually differs
    between spans can."""
    clip = tmp_path / "phases.mp4"
    inputs = []
    for level in levels:
        hexv = f"0x{level:02x}{level:02x}{level:02x}"
        inputs += ["-f", "lavfi", "-i", f"color=c={hexv}:s=320x240:d={dur}:r={fps}"]
    n = len(levels)
    filt = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    proc.run([ffbin.ffmpeg(), "-y", *inputs, "-filter_complex", filt, "-map", "[v]",
              "-frames:v", str(round(dur * fps) * n), "-pix_fmt", "yuv420p", str(clip)])
    return str(clip)


def test_clip_percentiles_batch_matches_the_per_span_calls(tmp_path):
    """fix round 1, minor 1: check_reel used to call clip_percentiles once per bound
    episode, each re-decoding the master from t=0 through only that episode's own last
    sample — summed over N episodes, roughly N/2 full-master decodes. Batched into ONE
    ffmpeg call across every span, the raw buffer is sliced back into per-span groups;
    this proves that slicing reconstructs EXACTLY what N separate clip_percentiles
    calls would have read, on the SAME real fixture — not merely that both readings are
    equally wrong, since clip_percentiles is the existing, independently-trusted ruler
    every other test in this file already exercises."""
    levels = (40, 120, 220)
    dur = 1.0
    clip = _three_phase_clip(tmp_path, levels=levels, dur=dur)
    spans = [[i * dur + t for t in color.sample_times(dur)] for i in range(len(levels))]
    singles = [color_measure.clip_percentiles(clip, s) for s in spans]
    batched = color_measure.clip_percentiles_batch(clip, spans)
    assert batched == singles                      # byte-for-byte the same ruler, batched or not
    # and not merely self-consistent: each phase's own p50 actually lands near its level
    for (p5, p50, p95), level in zip(batched, levels):
        assert abs(p50 - level) <= 8


def test_crop_percentiles_reads_the_crop_not_the_frame(tmp_path):
    """The design's §0.1 finding, as a test: a frame whose TOP half is blown out
    and whose bottom half is mid-grey reads very differently once the crop
    excludes the top. If these ever agree, the measuring path has stopped going
    through the render plan.

    Asserts the crop's exact value too (whole-object assert, docs/testing-guide.md):
    a bare `> MATCH_EPS` diff alone cannot tell "excludes the top band" from "reads
    the wrong band" — a sign flip in geometry.crop_y that read the TOP band instead
    would show the same ~140-unit difference and pass a diff-only assertion."""
    src, md, route = _banded_episode(tmp_path)                # helper below
    whole = color_measure.measure_profile(str(src), at=0.5)
    crop, _ = color_measure.measure_crop(md, str(src), str(route))
    assert crop == pytest.approx((100.0, 100.0, 100.0))
    assert max(abs(a - b) for a, b in zip(whole, crop)) > matchgrade.MATCH_EPS


def test_crop_percentiles_discriminates_at_a_realistic_gap(tmp_path):
    """The design measured a 14-unit median and 36-unit maximum gap between the
    whole-frame and crop readings on real footage — a test that only passes at the
    240/100 fixture's 35x margin does not exercise the threshold that actually
    matters in production. 20 units, near that median, is not a margin any
    resampling or codec noise could manufacture by accident."""
    src, md, route = _banded_episode(tmp_path, top=120, bottom=100)
    whole = color_measure.measure_profile(str(src), at=0.5)
    crop, _ = color_measure.measure_crop(md, str(src), str(route))
    assert crop == pytest.approx((100.0, 100.0, 100.0))
    assert max(abs(a - b) for a, b in zip(whole, crop)) > matchgrade.MATCH_EPS


def test_measure_crop_reads_the_footage_not_a_grade_already_authored(tmp_path, monkeypatch):
    """`plan_ungraded` strips the colour block before planning, so a second
    match-grade run measures the FOOTAGE and not its own previous output.

    The invariant strip_colour's docstring states, and the one thing in this slice
    with no test of its own until now: the conductor derives a common target from
    what it measures, so measuring an already-graded crop would compound the pull
    on every re-run — silently, since a grade that reads back as the target is
    exactly what a converged reel looks like.

    Today the real caller is safe by a second mechanism (build_geometry stores the
    manifest colour-STRIPPED, so `conduct` never sees a pair), which is why the
    whole suite stayed green with the strip deleted. That makes this a guard on
    `measure_crop`'s own contract rather than on today's only call site: the tone
    pair below lifts the crop's midpoint from 100 to 160, so a graded reading is
    off by 60 luma units — 15x MATCH_EPS, not a margin any resampling can produce.

    `measure_crop` now returns (profile, rows) (design 2026-09-15); this test's
    business is the profile only, so the region rows are discarded with `_`."""
    src, md, route = _banded_episode(tmp_path)
    plain, _ = color_measure.measure_crop(md, src, route)
    graded = dict(md, tone_src=[40, 100, 200], tone_dst=[40, 160, 200])
    graded_profile, _ = color_measure.measure_crop(graded, src, route)
    assert graded_profile == pytest.approx(plain)
    assert plain == pytest.approx((100.0, 100.0, 100.0))
    # The control that MUST move: the same manifest through the same render with the
    # strip disabled. Without it the first assertion is satisfied by a tone pair too
    # weak to change any pixel, and this test would pass with strip_colour deleted.
    monkeypatch.setattr(manifest_lib, "strip_colour", dict)
    with_grade, _ = color_measure.measure_crop(graded, src, route)
    assert abs(with_grade[1] - plain[1]) > 10 * matchgrade.MATCH_EPS, (with_grade, plain)


def _pan_episode(tmp_path, left=40, right=220):
    """(src, manifest_dict): a 640x360 (16:9) source split left/right, cropped by a
    9:16 `fill` layout — crop_w = 360*9/16 = 202 against a 640-wide source, so
    freedom (640-202=438px) exists for generate_pan_path to travel across (design
    2026-07-19 §4). `pan` replaces the route: reframe.plan_render's pan branch
    GENERATES the path and never reads route_path (design §2.1)."""
    src = tmp_path / "pan_src.mp4"
    proc.run([ffbin.ffmpeg(), "-y",
              "-f", "lavfi", "-i", f"color=c=0x{left:02x}{left:02x}{left:02x}:s=320x360:d=2:r=30",
              "-f", "lavfi", "-i", f"color=c=0x{right:02x}{right:02x}{right:02x}:s=320x360:d=2:r=30",
              "-filter_complex", "hstack=inputs=2", "-frames:v", "60",
              "-pix_fmt", "yuv420p", "-color_range", "tv", str(src)])
    md = {"segment": str(src), "out_path": "ep.mp4", "composition": "center",
          "grid": "thirds", "canvas": [9, 16], "target_dur": 2.0,
          "pan": {"from": 0.0, "to": 1.0}}
    return str(src), md


def test_measure_crop_works_on_a_pan_episode(tmp_path):
    """A pan episode's route is legitimately None (design 2026-07-19): reframe.
    plan_render GENERATES the crop path instead of reading one. match_grade's
    conductor measures every EDL episode's crop, so a pan riding the reel must
    not crash the whole stage — nothing exercised measure_crop(route=None) before
    this (design 2026-08-30 task 4).

    The two bands are far enough apart (40 vs 220) that a crop sweeping across
    the boundary over the clip's 2s reads BOTH — proof this went through the
    generated pan path and actually sampled moving content, not a frozen crop
    that happened not to crash."""
    src, md = _pan_episode(tmp_path)
    (p5, p50, p95), _ = color_measure.measure_crop(md, src, None)
    assert p5 < 100 and p95 > 160, f"expected the pan to cross both bands, got {(p5, p50, p95)}"


def test_percentiles_from_gray_refuses_a_short_buffer_the_old_check_missed():
    """60x60 makes w*h (3600) divisible by 3, so the OLD `len(raw) % want` guard
    would have silently accepted two frames' worth of bytes while three were
    asked for — exactly the failure mode production frame sizes (1920x1080,
    1080x1920: frame_bytes % 3 == 0 for both) hit for want=3. The new guard checks
    the byte count against want*w*h exactly, so a short buffer is caught here
    regardless of whether it happens to be divisible by the frame count."""
    raw = bytes(60 * 60 * 2)          # two frames' worth, not the three asked for
    with pytest.raises(RuntimeError, match="asked for 3"):
        color_measure._percentiles_from_gray(raw, 3, 60, 60, "test")


def test_crop_region_frames_refuses_a_short_buffer_the_old_check_missed(tmp_path, monkeypatch):
    """crop_region_frames' own sibling to the _percentiles_from_gray test above: the
    exact-byte guard is the only thing that catches the select-before-fps= landmine
    in the form where nothing crashes, and it had no regression test of its own.

    A real plan (from _banded_episode), its rl overridden via dataclasses.replace
    to a 60x60 out size — the same 3600-divisible-by-3 trap the sibling test's
    fixture uses, so a RELAXED guard that only checked the byte count was a whole
    number of FRAMES (len(raw) % 3, the OLD form _percentiles_from_gray's own
    docstring names) would also silently accept two frames' worth here: any whole
    multiple of a 3-divisible frame size is itself divisible by 3, so the frame
    COUNT check cannot tell 2 apart from 3. proc.run is monkeypatched to return
    exactly that short buffer for the three frames requested.

    Proven to discriminate (recorded in the task report, not re-asserted here on
    every run): relaxing crop_region_frames' guard to `len(raw) % (w * h) != 0`
    makes this test fail, then scripts/color_measure.py was restored via
    `git show HEAD:scripts/color_measure.py > scripts/color_measure.py`."""
    from scripts import process_episode
    import dataclasses
    src, md, route = _banded_episode(tmp_path)
    plan, _, _ = process_episode.plan_and_meta_ungraded(md, src, route)
    small_plan = dataclasses.replace(
        plan, rl=dataclasses.replace(plan.rl, out_w=60, out_h=60))
    times = color.sample_times(small_plan.dur)
    assert len(times) == 3
    short = bytes(2 * 60 * 60)          # two frames' worth, not the three asked for

    class _Result:
        stdout = short

    monkeypatch.setattr(color_measure.proc, "run", lambda *a, **k: _Result())
    with pytest.raises(RuntimeError, match="asked for 3"):
        color_measure.crop_region_frames(small_plan, src, times)


def test_sample_times_never_touches_the_ends():
    # sample_times itself now lives in scripts.lib.color (moved 2026-08-31, design
    # grade-sensor-references §6 — check_episode needs it and cannot import
    # color_measure without a cycle); this pins that color_measure's own callers
    # still reach the same function through the new path.
    assert color.sample_times(3.0, 3) == [0.5, 1.5, 2.5]
    assert color.sample_times(1.0, 1) == [0.5]


def _subject_episode(tmp_path):
    """(src, manifest_dict, route_json): a crop with real tonal spread AND a dark
    subject inside it, so the toe can move while p50 stays inside its own band and
    p95 is untouched entirely.

    640x1280. The top 640 rows are excluded by the crop exactly as in
    _banded_episode (canvas [1,1] over a 640x1280 source crops 640x640, and
    geometry.crop_y places it against the route's mean y of 960). The cropped half
    is three sub-bands — 80 / 140 / 200 — so the crop's own profile is
    (80, 140, 200): ordered, gaps far above color.TONE_MIN_GAP. A 120x120 box at
    luma 20 sits inside the MIDDLE sub-band (140, absolute rows 854-1067) at the
    route's bbox — NOT the darkest one (80, absolute rows 640-853): the box's own
    absolute y-range (900-1019) falls entirely inside 854-1067.

    The box is 14400 px of the crop's 409600 — 3.52%, above MIN_REGION_FRAC and
    below 5%, which is what makes the two readings differ: the crop's p5 is 80
    (only 3.52% of it is darker) while the subject region is entirely the box, so
    its p5 is 20.

    p50 is NOT untouched "by construction": the box removes its 3.52% from the
    140 band, moving that band's cumulative range from [33.44%, 66.72%) to
    [36.95%, 66.72%) (the box only ever removes from the LOW end of a band's
    range, never the high end, so the upper edge is invariant). The 50% mark
    still lands inside the shrunk range — 13.05 points clear of its new lower
    edge — so p50 stays 140 on HEADROOM, not by construction: a box more than
    roughly 3.7x this one's area (13.05/3.52) would have pushed that edge past
    50% and flipped p50 into the 80 band. p95 genuinely IS untouched, for a
    different reason: the box sits entirely inside the 140 band, well below the
    200 band it can never reach."""
    src = tmp_path / "subject.mp4"
    proc.run([ffbin.ffmpeg(), "-y",
              "-f", "lavfi", "-i", "color=c=0x303030:s=640x640:d=2:r=30",
              "-f", "lavfi", "-i", "color=c=0x505050:s=640x214:d=2:r=30",
              "-f", "lavfi", "-i", "color=c=0x8c8c8c:s=640x213:d=2:r=30",
              "-f", "lavfi", "-i", "color=c=0xc8c8c8:s=640x213:d=2:r=30",
              "-filter_complex",
              "[0][1][2][3]vstack=inputs=4,"
              "drawbox=x=260:y=900:w=120:h=120:color=0x141414@1:t=fill",
              "-frames:v", "60", "-pix_fmt", "yuv420p", "-color_range", "tv", str(src)])
    md = {"segment": str(src), "out_path": "ep.mp4", "composition": "center",
          "grid": "thirds", "canvas": [1, 1], "target_dur": 2.0}
    route_path = tmp_path / "subject_route.json"
    route_path.write_text(json.dumps(
        [dict(t=0.0, x=320.0, y=960.0, w=120.0, h=120.0),
         dict(t=2.0, x=320.0, y=960.0, w=120.0, h=120.0)]))
    return str(src), md, str(route_path)


def test_the_crop_region_reading_equals_crop_percentiles_exactly(tmp_path):
    """The byte-identical default path, pinned. If the region ruler and the
    pooled-histogram ruler ever disagree there are two rulers, which is the one
    thing this module's docstring forbids."""
    from scripts import process_episode
    from scripts.lib import regions
    src, md, route = _subject_episode(tmp_path)
    plan, _, _ = process_episode.plan_and_meta_ungraded(md, src, route)
    times = color.sample_times(plan.dur)
    pooled = color_measure.crop_percentiles(plan, src, times)
    stack = color_measure.crop_region_frames(plan, src, times)
    assert regions.measure(stack, None)["crop"].profile == pooled


def test_measure_crop_with_no_declaration_returns_the_old_profile(tmp_path):
    from scripts import process_episode
    src, md, route = _subject_episode(tmp_path)
    plan, _, _ = process_episode.plan_and_meta_ungraded(md, src, route)
    profile, rows = color_measure.measure_crop(md, src, route)
    assert profile == color_measure.crop_percentiles(
        plan, src, color.sample_times(plan.dur))
    # Pinned exactly (not just agreement between the two rulers, which the
    # assertion above already covers): the toe test's whole ±30 margin rests on
    # this 80, and nothing here holds it to a concrete value otherwise — mirrors
    # test_crop_percentiles_reads_the_crop_not_the_frame's own (100, 100, 100) pin.
    assert profile == pytest.approx((80.0, 140.0, 200.0))
    assert [r.used for r in rows] == ["crop", "crop", "crop"]
    assert all(r.fallback is None for r in rows)


def test_a_subject_declaration_moves_the_toe_and_nothing_else(tmp_path):
    from scripts.lib import regions
    src, md, route = _subject_episode(tmp_path)
    plain, _ = color_measure.measure_crop(md, src, route)
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]})
    toned, rows = color_measure.measure_crop(md, src, route, decl=decl)
    # A pin, not a control: toe is the only declared anchor here, so mid/shoulder
    # resolve to the implicit crop row exactly as `plain`'s do — nothing this
    # assembly could get wrong would move them under THIS declaration alone.
    assert toned[1:] == plain[1:]
    assert toned[0] < plain[0] - 30, (toned, plain)
    assert rows[0].of == "subject" and rows[0].used == "subject"
    assert rows[0].fallback is None
    assert 0.02 < rows[0].fraction < 0.06

    # The real control: declare a DIFFERENT anchor (shoulder) over a DIFFERENT
    # region (background) and check the UNDECLARED toe does not move. This one
    # CAN fail — if assemble ever let one anchor's declaration leak into
    # another's value, or read the wrong region for the wrong anchor, toe would
    # shift here even though nothing declared it.
    shoulder_decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "shoulder", "name": "water", "of": "background"}]})
    background_toned, background_rows = color_measure.measure_crop(
        md, src, route, decl=shoulder_decl)
    assert background_toned[0] == plain[0]
    assert background_rows[0].of == "crop" and background_rows[0].used == "crop"
    assert background_rows[2].of == "background" and background_rows[2].used == "background"


def test_a_pan_episode_has_no_route_and_falls_back_named(tmp_path):
    from scripts import process_episode
    from scripts.lib import regions
    src, md = _pan_episode(tmp_path)
    decl = regions.Regions.from_dict({"anchors": [
        {"anchor": "toe", "name": "wetsuit", "of": "subject"}]})
    profile, rows = color_measure.measure_crop(md, src, None, decl=decl)
    assert rows[0].fallback == "no-route"
    assert profile == color_measure.measure_crop(md, src, None)[0]

    # The pan crop is NOT square (unlike _subject_episode's and _banded_episode's
    # 640x640), so a reshape(n, w, h) — the transposed axis order — would produce
    # a DIFFERENT shape than reshape(n, h, w) here. A square crop cannot
    # discriminate the two; this one can.
    plan, _, _ = process_episode.plan_and_meta_ungraded(md, src, None)
    times = color.sample_times(plan.dur)
    stack = color_measure.crop_region_frames(plan, src, times)
    assert stack.shape == (len(times), plan.rl.out_h, plan.rl.out_w)
