"""Design 2026-08-31 §7 — the six proofs, each with a control.

Real ffmpeg throughout. These are the claims the slice stands on; a green unit
suite over stubbed renders proves none of them. Task 9's audit (see
.superpowers/sdd/2026-08-31-grade-sensor-references/task-9-report.md) found
Proofs 2 and 3's FAILING arms and Proof 4's advisory-logic claim already covered
elsewhere in the suite; every test below is either new coverage or adds the
specific control/ingredient the existing coverage was missing.
"""
import dataclasses
from pathlib import Path

import pytest

from scripts import build_reel, color_measure, process_episode, reframe
from scripts.lib import assembly, color, gradedamage
from scripts.lib import manifest as manifest_lib
from scripts.lib import orchestration as orch
from scripts.lib.manifest import Manifest
from scripts.lib.models import CheckSpec, Delivery, ReelEpisode, ReelManifest

pytestmark = pytest.mark.integration

ROUTE = "tests/fixtures/golden_route.json"

# CheckSpec's own default — referenced, not re-typed as a bare "0.90" literal, so
# these proofs stay correct if the floor is ever re-tuned.
_ENTROPY_FLOOR = CheckSpec(composition="center", grid="thirds", target_dur=1.0).entropy_floor


def _md(src: str, out_path: str, **extra) -> dict:
    md = {"segment": src, "out_path": out_path, "target_dur": 1.5,
          "composition": "center", "grid": "thirds", "layout": "fill",
          "canvas": [9, 16], "delivery": "short_edge:480"}
    md.update(extra)
    return md


def _render(md: dict, src: str, out: str, path_out: str) -> None:
    """Render `md` through the SAME manifest -> spec -> reframe path
    process_episode.process_episode uses on attempt 1 with default params —
    used directly (bypassing the retry loop) wherever a proof needs the clip
    or its sidecars without the loop's own checks running."""
    m = Manifest.from_dict(md)
    spec = process_episode.build_reframe_spec(m, Delivery.from_spec(m.delivery),
                                              dict(orch.DEFAULT_PARAMS))
    reframe.reframe(spec, src, ROUTE, out, path_out)


# --- Proof 1 — the deadlock, demonstrated and removed -------------------------

def test_a_conductor_pair_crosses_the_old_bar_but_not_the_new_one(
        golden_ride_segment, tmp_path):
    """design §7.1. A conductor-shaped tone pair — a uniform +30-luma-unit lift of
    this crop's own measured profile, the shape a common-target correction takes
    when a shot is uniformly darker than the pool it is being matched to — must
    pass the NEW `grade_damage` gate while its `delta_e` (the OLD, now-advisory
    statistic, riding in the same detail dict) crosses the OLD 5.0 ceiling that
    used to block it. Driven through the full `process_episode.process_episode`,
    not a hand-built plan pair, so the proof is of the wired gate, not the sensor
    in isolation.

    MEASURED on this fixture: ratio 0.977 (floor 0.90), delta_e 9.63 — comfortably
    on both sides of the two ceilings this proof straddles. A pull magnitude was
    searched for empirically (task report): a small pull (Task 3/5's own
    +12/-10/-18) passes both gates and proves nothing about the deadlock; several
    larger MIXED-sign pulls fail entropy outright. A uniform translation turned
    out to be the shape that clears the new floor with room (0.977) while still
    moving the tracked subject's own colour past the old bar (9.63) — entropy is
    a whole-frame, largely bijective-invariant statistic, so a pure shift costs it
    little, while a shift this size still reads as a big subject-relative dE00.

    Control: the same episode ungraded passes both gates, and its delta_e (a
    residual of re-encode/crop resampling only) stays under 5.0 — without this,
    a bug that always reported delta_e > 5 would make the main assertion vacuous.
    """
    src = str(golden_ride_segment)
    base = _md(src, str(tmp_path / "unused.mp4"))
    prof = color_measure.measure_crop(base, src, ROUTE)
    target = [round(v + 30, 1) for v in prof]

    graded = dict(base, out_path=str(tmp_path / "graded.mp4"),
                  tone_src=list(prof), tone_dst=target)
    result = process_episode.process_episode(
        graded, project_dir=str(tmp_path / "graded_dir"), route_path=ROUTE)
    assert result["status"] == "mechanical_pass", result
    gd = result["report"]["checks"]["grade_damage"]
    print(f"\nMEASURED proof 1 (graded): ratio={gd['ratio']} delta_e={gd['delta_e']}")
    assert gd["frames"] == 3, gd    # pins the sample count check_episode actually used —
                                    # a silently reduced/enlarged N would move the ratio by
                                    # about as much as proof 5's own headline finding (fix
                                    # round 1) without tripping any OTHER assertion here
    assert gd["pass"] is True, gd                 # NEW gate: not damage
    assert gd["delta_e"] > 5.0, gd                 # OLD gate: would have blocked here

    ctrl = dict(base, out_path=str(tmp_path / "ctrl.mp4"))
    ctrl_result = process_episode.process_episode(
        ctrl, project_dir=str(tmp_path / "ctrl_dir"), route_path=ROUTE)
    assert ctrl_result["status"] == "mechanical_pass", ctrl_result
    cgd = ctrl_result["report"]["checks"]["grade_damage"]
    print(f"MEASURED proof 1 (ungraded control): ratio={cgd['ratio']} delta_e={cgd['delta_e']}")
    assert cgd["frames"] == 3, cgd
    assert cgd["pass"] is True, cgd
    assert cgd["delta_e"] < 5.0, cgd


# --- Proof 2 — damage still fails, and a benign value of the SAME knob passes -

def test_black_point_at_its_legal_max_fails_and_a_benign_value_passes(
        golden_ride_segment, tmp_path):
    """design §7.2. `black_point = 0.35` (the legal maximum, design §0.5's measured
    damaging value) fails `grade_damage`, escalates via
    `orchestration._UNFIXABLE`/`_UNFIXABLE_REASON` as `'grade-damage'`, on attempt
    1 — not after two retries a colour knob can never fix. The end-to-end failing
    path (through `process_episode.process_episode`, escalation reason, attempt
    number) is already covered by
    `tests/integration/test_process_episode.py::test_grade_damage_escalates_a_damaging_grade_on_attempt_one`
    (task report audit); reproduced here as one self-contained assertion so this
    proof stands on its own, and PAIRED with the control the audit found missing
    everywhere else: `black_point = 0.02`, the SAME knob at a legal, gentle value,
    on the SAME fixture, must pass — the existing suite's healthy control uses an
    unrelated tone pair, never this knob at a benign magnitude, so nothing
    currently distinguishes "grade_damage rejects black_point" from "grade_damage
    rejects any black_point at all".

    MEASURED: damaging ratio 0.753 (floor 0.90); benign ratio 1.005.
    """
    src = str(golden_ride_segment)
    base = _md(src, str(tmp_path / "unused.mp4"))

    damaging = dict(base, out_path=str(tmp_path / "damaging.mp4"), black_point=0.35)
    result = process_episode.process_episode(
        damaging, project_dir=str(tmp_path / "damaging_dir"), route_path=ROUTE)
    assert result["status"] == "escalate", result
    assert result["reason"] == "grade-damage", result
    assert result["attempt"] == 1, result
    gd = result["report"]["checks"]["grade_damage"]
    print(f"\nMEASURED proof 2 (black_point=0.35): ratio={gd['ratio']}")
    assert gd["frames"] == 3, gd
    assert gd["pass"] is False, gd

    benign = dict(base, out_path=str(tmp_path / "benign.mp4"), black_point=0.02)
    ok = process_episode.process_episode(
        benign, project_dir=str(tmp_path / "benign_dir"), route_path=ROUTE)
    assert ok["status"] == "mechanical_pass", ok
    ogd = ok["report"]["checks"]["grade_damage"]
    print(f"MEASURED proof 2 (black_point=0.02): ratio={ogd['ratio']}")
    assert ogd["frames"] == 3, ogd
    assert ogd["pass"] is True, ogd


# --- Proofs 3 and 4 share one real render pair --------------------------------

def _faithfulness_pair(tmp_path: Path, src: str, prof, target):
    """Two real episodes over the SAME crop/tone pair, ep0 additionally carrying
    a post-tone `black_point` — the ingredient §7.3/§7.4 need: `grade_faithful`
    predicts from the FULL declared chain, so a knob riding after the tone curve
    moves the prediction and the delivery TOGETHER (faithful) while moving the
    prediction away from the bare tone-only target (a big advisory `target_dev`).
    Returns a hand-built `ReelManifest` — no geometry/EDL/conductor plumbing,
    mirroring `test_a_drifted_manifest_becomes_not_checked_not_a_bogus_residual`'s
    house style for a build_reel proof that does not need one."""
    def episode(name: str, extra_colour: dict):
        d = tmp_path / name
        d.mkdir(parents=True)
        clip = str(d / "ep.mp4")
        path_json = str(d / "path.json")
        md = _md(src, clip, tone_src=list(prof), tone_dst=list(target), **extra_colour)
        _render(md, src, clip, path_json)
        return md, clip, path_json

    md0, clip0, path0 = episode("ep0", dict(black_point=0.05))
    md1, clip1, path1 = episode("ep1", {})
    total_dur = round(assembly.probe_duration(clip0) + assembly.probe_duration(clip1), 3)
    ep0 = ReelEpisode(manifest=md0, clip=clip0, route=ROUTE, path=path0,
                      meta=str(Path(path0).with_suffix(".meta.json")))
    ep1 = ReelEpisode(manifest=md1, clip=clip1, route=ROUTE, path=path1,
                      meta=str(Path(path1).with_suffix(".meta.json")))
    return ReelManifest(episodes=[ep0, ep1], target_dur=total_dur, variety_min=0,
                        tone_target=tuple(target))


def test_grade_faithful_survives_a_post_tone_knob_and_fails_a_dropped_block(
        golden_ride_segment, tmp_path):
    """design §7.3. Render two episodes with a conductor-shaped tone pair — ep0
    ALSO carries `black_point = 0.05` beside it, the exact ingredient design §2's
    "a post-tone knob moves prediction and delivery together and cancels" is
    about. Assemble the master through `build_reel.build_reel`'s own prediction
    path (`build_reel._predict`, never a hand-built `predicted=`) and assert
    `grade_faithful.passed is True` with `worst` under `grade_residual_max`.

    Then the colour block goes missing between authoring and render — ep1's
    DECLARED manifest (what `rm` still carries) is untouched, but its RENDERED
    pixels lose the tone pair, the "declared but never rendered" case. Re-running
    `build_reel.build_reel` on that reel must fail and route to `process-episode`.

    MEASURED: pass 1 worst=1.0 (ceiling 4.0), residuals {0: 1.0, 1: 0.0}; pass 2
    residuals {0: 1.0 (unchanged), 1: 22.0} — episode 0's own reading does not
    move, so the failure is attributed to the one episode that lost its grade.

    This closes a real gap the audit found: the existing
    `test_the_gate_fires_when_the_grade_never_reached_the_pixels`
    (test_grade_shipped_pixels.py) proves the SAME failure shape, but with NO
    post-tone knob anywhere in its fixture — every bound episode's prediction
    equals the bare tone target there, so a regression back to the OLD
    `tone_match` reference (the reel's common target, not each episode's own full
    chain) would satisfy that test by accident. Here predicted and target
    genuinely disagree (§7.4 below measures by how much), so only a prediction
    built from the FULL declared chain can pass this one.

    Control: the SAME master, correctly predicted, passes — so the second run's
    failure is the stale reference, not a broken master.
    """
    src = str(golden_ride_segment)
    prof = color_measure.measure_crop(_md(src, str(tmp_path / "unused.mp4")), src, ROUTE)
    target = [round(v + 20, 1) for v in prof]
    rm = _faithfulness_pair(tmp_path / "base", src, prof, target)

    ok = build_reel.build_reel(rm, str(tmp_path / "deliveries1"), str(tmp_path / "work1"))
    assert ok["status"] == "delivered", ok
    gf = ok["report"]["checks"]["grade_faithful"]
    print(f"\nMEASURED proof 3 (healthy, post-tone knob on ep0): {gf}")
    assert gf["pass"] is True, gf
    assert gf["worst"] <= rm.check_spec.grade_residual_max, gf

    d = tmp_path / "ep1_dropped"
    d.mkdir()
    dropped_clip = str(d / "ep.mp4")
    dropped_path = str(d / "path.json")
    dropped_md = dict(rm.episodes[1].manifest, tone_src=None, tone_dst=None)   # actually rendered ungraded
    _render(dropped_md, src, dropped_clip, dropped_path)
    # rm.episodes[1].manifest is UNCHANGED below — it still DECLARES the tone pair,
    # which is the whole point: the record says graded, the pixels say otherwise.
    bad_ep1 = dataclasses.replace(rm.episodes[1], clip=dropped_clip, path=dropped_path,
                                  meta=str(Path(dropped_path).with_suffix(".meta.json")))
    bad_rm = dataclasses.replace(rm, episodes=[rm.episodes[0], bad_ep1])

    bad = build_reel.build_reel(bad_rm, str(tmp_path / "deliveries2"), str(tmp_path / "work2"))
    assert bad["status"] == "stop_and_report", bad
    assert bad["finding"]["check"] == "grade_faithful", bad["finding"]
    assert bad["finding"]["escalate_to"] == "process-episode", bad["finding"]
    bad_gf = bad["report"]["checks"]["grade_faithful"]
    print(f"MEASURED proof 3 (ep1's grade dropped from the render): {bad_gf}")
    assert bad_gf["pass"] is False, bad_gf
    assert bad_gf["residuals"]["0"] == gf["residuals"]["0"], (bad_gf, gf)


def test_target_dev_is_large_yet_a_faithful_render_still_passes(
        golden_ride_segment, tmp_path):
    """design §7.4 (the advisory does not block) — real pixels, not the stubbed
    `tests/lib/test_check_reel.py::test_target_dev_is_advisory_and_only_for_bound_episodes`.
    That test is judged sufficient on its own for the CONTROL-FLOW half of this
    claim ("target_dev never enters the pass/fail decision" is pure logic,
    independent of where the RGB numbers come from, and the reviewer there already
    proved it discriminates a gating mutant by hand — see the task report). What
    it cannot show is that a real render, on real footage, actually PRODUCES a
    target_dev past the ceiling while staying faithful — that needs a real
    post-tone knob moving real pixels, which is what this test adds.

    ep0 (from `_faithfulness_pair`) declares a tone pair equal to the reel's
    common target (bound) plus `black_point = 0.05` riding after it — the full
    chain's prediction lands ~10 luma units from the bare target (`target_dev`),
    well past `grade_residual_max` (4.0), while the render is faithful to its OWN
    prediction (worst 1.0) and the WHOLE report still passes.

    Control: the SAME declared chain (tone_target/tone_dsts unchanged, so
    target_dev is UNCHANGED too), but ep0's rendered pixels now come from a
    render that quietly dropped the `black_point` knob while the manifest still
    declares it — genuinely unfaithful, and the gate must fail. Isolating the
    control this way (same target_dev both times, only faithfulness differs)
    is what proves target_dev's SIZE has no say in the verdict, not merely that
    some other reel fails for some other reason.

    MEASURED: pass 1 target_dev {0: 10.0, 1: 2.0}, worst 1.0, pass True; pass 2
    (ep0 corrupted) target_dev UNCHANGED at {0: 10.0, 1: 2.0}, worst 12.0, pass
    False.
    """
    src = str(golden_ride_segment)
    prof = color_measure.measure_crop(_md(src, str(tmp_path / "unused.mp4")), src, ROUTE)
    target = [round(v + 20, 1) for v in prof]
    rm = _faithfulness_pair(tmp_path / "base", src, prof, target)

    ok = build_reel.build_reel(rm, str(tmp_path / "deliveries1"), str(tmp_path / "work1"))
    assert ok["status"] == "delivered", ok
    gf = ok["report"]["checks"]["grade_faithful"]
    print(f"\nMEASURED proof 4 (large target_dev, faithful render): {gf}")
    assert gf["pass"] is True, gf
    dev0 = gf["target_dev"]["0"]
    assert dev0 > rm.check_spec.grade_residual_max, gf     # LARGE: would fail as a gate

    d = tmp_path / "ep0_corrupted"
    d.mkdir()
    corrupted_clip = str(d / "ep.mp4")
    corrupted_path = str(d / "path.json")
    render_md = dict(rm.episodes[0].manifest, black_point=0.0)   # actually rendered WITHOUT the knob
    _render(render_md, src, corrupted_clip, corrupted_path)
    # rm.episodes[0].manifest is UNCHANGED below — still DECLARES black_point=0.05,
    # so _predict's reference does not move; only the pixels underneath it did.
    bad_ep0 = dataclasses.replace(rm.episodes[0], clip=corrupted_clip, path=corrupted_path,
                                  meta=str(Path(corrupted_path).with_suffix(".meta.json")))
    bad_rm = dataclasses.replace(rm, episodes=[bad_ep0, rm.episodes[1]])

    bad = build_reel.build_reel(bad_rm, str(tmp_path / "deliveries2"), str(tmp_path / "work2"))
    assert bad["status"] == "stop_and_report", bad
    bad_gf = bad["report"]["checks"]["grade_faithful"]
    print(f"MEASURED proof 4 (control: ep0's own knob dropped from the render): {bad_gf}")
    assert bad_gf["pass"] is False, bad_gf
    assert bad_gf["target_dev"] == gf["target_dev"], (
        "target_dev must not move when only faithfulness changes — otherwise this "
        f"control cannot separate 'target_dev is large' from 'something else broke': {bad_gf}")


# --- Proof 5 — the x264 entropy bias, measured (the task's real deliverable) --

def test_the_x264_entropy_bias_is_measured_not_assumed(golden_ride_segment, tmp_path):
    """design §7.5/§3 — the reason both sides of `gradedamage.evaluate`'s ratio are
    renders, and never one render plus the shipped clip.

    Computed twice for the SAME graded episode: once as two renders (plain and
    graded both via `reframe.plan_frames_rgb` — the shipped `check_episode`/
    `process_episode` path), and once with the GRADED side swapped for a real
    decode of the delivered clip (`assembly.frames_rgb` on the `ep.mp4` that
    `reframe.reframe` itself writes, at production's own CRF 18/preset medium —
    the same encode settings `reframe.py`'s one encoder call always uses).

    MEASURED here (conductor-shaped pull, the same +12/-10/-18 shape Task 3/5
    calibrated `entropy_floor` against, reproduced twice with byte-identical
    results): render-pair ratio 0.933, clip-read ratio 0.940 — bias
    (render - clip) of -0.007.

    THIS IS THE OPPOSITE of the direction design §3 states. §3's prose says
    libx264 quantization LOWERS entropy and "would bias the ratio toward false
    damage" — i.e. it predicts the CLIP-READ ratio should be LOWER than the
    render-pair one. Measured, the clip-read ratio is HIGHER, not lower — on
    this fixture, at this operating point, x264 makes a genuinely graded episode
    look slightly LESS damaging when read from the shipped clip, not more.
    Reproduced: at both 3 and 9 sample frames, on a genuinely damaging grade
    (black_point=0.35: render-pair 0.753, clip-read 0.765) and on the identity
    control below — five independent measurements, all the same direction, all
    exactly reproducible run to run (bit-identical libx264 output).

    A frame-difference audit explains the mechanism (task report has the full
    numbers): render-vs-clip per-pixel deltas at one sample frame are
    essentially zero-mean (-0.02) with real spread (std ~2.1 codes, individual
    pixels up to +/-30) — the shape of x264's own quantization/deblocking/
    psy-optimization noise at a fairly high quality (CRF 18), not a colour-
    matrix mismatch (which would show a non-zero MEAN, not spread) and not a
    frame-index misalignment (both paths select the identical frame numbers off
    matching fps, checked directly). Symmetric near-zero-mean noise SPREADS a
    histogram; it does not concentrate it — so at this specific operating point
    x264 nudges the marginal luma-histogram entropy UP, not down.

    This does not overturn the design's ACTUAL decision: comparing two renders
    is still the only way to keep `gradedamage`'s statistic uncontaminated by an
    encoder artifact, and an artifact whose direction depends on operating point
    (arguably true here — a lower-quality CRF or a different codec could easily
    push the other way) is, if anything, a STRONGER reason to keep the
    comparison symmetric than a fixed one-directional bias would be. It DOES
    mean design §3's specific sentence should be corrected to state the
    measurement rather than the untested assumption — flagged in the task
    report for the controller to act on; not changed here, since Task 9 is
    proofs, not a design edit.

    Control: on an ungraded episode (plain plan == graded plan by construction)
    both readings sit within 0.01 of each other and of 1.0 — the same small
    residual noise, with no grade underneath it to amplify.
    """
    src = str(golden_ride_segment)
    base = _md(src, str(tmp_path / "unused.mp4"))
    prof = color_measure.measure_crop(base, src, ROUTE)
    target = [round(prof[0] + 12, 1), round(prof[1] - 10, 1), round(prof[2] - 18, 1)]

    def measure(label: str, extra_colour: dict) -> tuple[dict, dict]:
        d = tmp_path / label
        d.mkdir()
        clip = str(d / "ep.mp4")
        md = _md(src, clip, **extra_colour)
        _render(md, src, clip, str(d / "path.json"))

        graded_plan = process_episode.plan_for(md, src, ROUTE)
        plain_plan = process_episode.plan_ungraded(md, src, ROUTE)
        times = color.sample_times(graded_plan.dur)
        plain_frames = reframe.plan_frames_rgb(plain_plan, src, times)
        render_graded_frames = reframe.plan_frames_rgb(graded_plan, src, times)
        render_pair = gradedamage.evaluate(plain=plain_frames, graded=render_graded_frames,
                                           floor=_ENTROPY_FLOOR)

        clip_fps = assembly.probe_stream(clip).fps
        clip_graded_frames = assembly.frames_rgb(clip, times, clip_fps)
        clip_read = gradedamage.evaluate(plain=plain_frames, graded=clip_graded_frames,
                                         floor=_ENTROPY_FLOOR)
        # Pin the sample count on BOTH readings: fix round 1 measured that a silent
        # change to N moves the ratio by about as much as this proof's own headline
        # bias (0.0115 spread over N=1..15 against a 0.007 bias) — undetectable by any
        # OTHER assertion here, since both sides of a given reading always share the
        # same `times`.
        assert render_pair["frames"] == len(times) == 3, (render_pair, times)
        assert clip_read["frames"] == len(times) == 3, (clip_read, times)
        return render_pair, clip_read

    render_pair, clip_read = measure("graded", dict(tone_src=list(prof), tone_dst=target))
    print(f"\nMEASURED x264 entropy bias (graded episode): render-pair ratio="
          f"{render_pair['ratio']}  clip-read ratio={clip_read['ratio']}  "
          f"bias(render-clip)={render_pair['ratio'] - clip_read['ratio']:.4f}")
    # The measured direction is the render-pair ratio being the LOWER of the two —
    # opposite of design §3's stated hypothesis. See the docstring above.
    assert clip_read["ratio"] > render_pair["ratio"], (render_pair, clip_read)
    # Sanity bound, not a tight pin: the effect is quantization-scale noise (measured
    # 0.007), not a gross methodology error. A frame-index misalignment or a wrong
    # clip being read would show a bias an order of magnitude bigger than this —
    # this bound would catch that class of bug without pinning today's exact figure.
    assert abs(render_pair["ratio"] - clip_read["ratio"]) < 0.05, (render_pair, clip_read)

    ctrl_render_pair, ctrl_clip_read = measure("ungraded", {})
    print(f"MEASURED x264 entropy bias (ungraded control): render-pair ratio="
          f"{ctrl_render_pair['ratio']}  clip-read ratio={ctrl_clip_read['ratio']}")
    assert abs(ctrl_render_pair["ratio"] - ctrl_clip_read["ratio"]) <= 0.01, \
        (ctrl_render_pair, ctrl_clip_read)
    assert abs(ctrl_render_pair["ratio"] - 1.0) <= 0.01, ctrl_render_pair
    assert abs(ctrl_clip_read["ratio"] - 1.0) <= 0.01, ctrl_clip_read


# --- Proof 6 — byte-identity, the honest weaker form --------------------------

def test_an_ungraded_render_is_byte_identical_by_two_routes(golden_ride_segment, tmp_path):
    """design §7.6. The plan concedes the strong claim — "unchanged by this
    slice" against the PARENT commit's own binary — needs a checkout the global
    constraints forbid. Asserted instead, from inside this commit: two DIFFERENT
    routes to a colour-identity render land on the SAME bytes.

    Route 1: author a manifest with NO colour block at all, and render it the
    ordinary way (`process_episode.plan_for` -> `reframe.reframe`).
    Route 2: author a SEPARATE manifest carrying every one of
    `manifest.COLOUR_KEYS` at a non-identity value, strip it with
    `process_episode.plan_ungraded` (`manifest.strip_colour` underneath), and
    render THAT.

    If `plan_ungraded`'s stripping ever missed one of the eleven colour fields,
    or `Manifest.from_dict` treated an omitted field differently from one
    explicitly set to its own identity default (`manifest.COLOUR_IDENTITY`), the
    two plans — and the two renders — would disagree. Every colour key is
    populated in the "WITH a colour block" manifest for exactly this reason: a
    field-coverage gap in `strip_colour` only shows up if the test actually sets
    that field to something non-identity.

    Control: the SAME manifest, rendered WITH its colour block (not stripped),
    must differ in bytes from the other two — otherwise this fixture's colour
    block would not be doing anything and the identity above would be vacuous.
    """
    src = str(golden_ride_segment)
    base = _md(src, "")   # out_path filled in per-render below

    manifest_a = dict(base, out_path=str(tmp_path / "unused_a.mp4"))          # no colour block
    manifest_b = dict(base, out_path=str(tmp_path / "unused_b.mp4"),          # every colour key set
                      color_means=[100.0, 110.0, 120.0], white_balance=0.5,
                      black_point=0.1, highlight=0.9, highlight_red=0.15,
                      saturation=1.1, shadow_red=0.05, mid_blue=0.95, dip=0.2,
                      tone_src=[30, 100, 148], tone_dst=[35, 110, 150])

    plan_a = process_episode.plan_for(manifest_a, src, ROUTE)
    plan_b_ungraded = process_episode.plan_ungraded(manifest_b, src, ROUTE)
    assert plan_a == plan_b_ungraded, (plan_a, plan_b_ungraded)

    out_a = str(tmp_path / "render_a.mp4")
    out_b_stripped = str(tmp_path / "render_b_stripped.mp4")
    out_b_graded = str(tmp_path / "render_b_graded.mp4")

    _render(manifest_a, src, out_a, str(tmp_path / "a_path.json"))
    _render(manifest_lib.strip_colour(manifest_b), src, out_b_stripped,
           str(tmp_path / "b_stripped_path.json"))
    _render(manifest_b, src, out_b_graded, str(tmp_path / "b_graded_path.json"))   # control

    bytes_a = Path(out_a).read_bytes()
    bytes_b_stripped = Path(out_b_stripped).read_bytes()
    bytes_b_graded = Path(out_b_graded).read_bytes()
    print(f"\nMEASURED proof 6: len(no-colour-block)={len(bytes_a)}  "
          f"len(plan_ungraded-of-graded)={len(bytes_b_stripped)}  "
          f"len(graded-control)={len(bytes_b_graded)}")
    assert bytes_a == bytes_b_stripped, \
        "no colour block vs plan_ungraded of a graded manifest must match byte-for-byte"
    assert bytes_a != bytes_b_graded, \
        "the WITH-colour-block control must differ, or this fixture proves nothing"
