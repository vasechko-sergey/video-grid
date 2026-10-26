"""pacing core — pure stdlib, no librosa/numpy; exact-slot asserts (bit-exact)."""
import dataclasses

import pytest

from scripts.lib import gridfit, pacing
from scripts.lib.pacing import Slot, Spine, music_identity


def test_slot_round_trips():
    s = Slot(index=0, start=0.0, dur=1.5, energy=0.4, kind="hook")
    assert Slot.from_dict(s.to_dict()) == s
    assert s.to_dict() == {"index": 0, "start": 0.0, "dur": 1.5, "energy": 0.4, "kind": "hook",
                           "line": None, "dev": 0.0, "beats_in": -1}


def test_slot_coerces_ints_to_float():
    s = Slot(index=1, start=2, dur=3, energy=1, kind="peak")
    assert s.start == 2.0 and s.dur == 3.0 and s.energy == 1.0
    assert isinstance(s.start, float) and isinstance(s.dur, float)


@pytest.mark.parametrize("kw, match", [
    (dict(index=0, start=0.0, dur=0.0, energy=0.5, kind="hook"), "dur"),
    (dict(index=0, start=0.0, dur=1.0, energy=1.5, kind="hook"), "energy"),
    (dict(index=0, start=-1.0, dur=1.0, energy=0.5, kind="hook"), "start"),
    (dict(index=0, start=0.0, dur=1.0, energy=0.5, kind="bogus"), "kind"),
    (dict(index=True, start=0.0, dur=1.0, energy=0.5, kind="hook"), "index"),
    (dict(index=-1, start=0.0, dur=1.0, energy=0.5, kind="hook"), "index"),
])
def test_slot_rejects_bad(kw, match):
    with pytest.raises(ValueError, match=match):
        Slot(**kw)


def test_slot_from_dict_missing_key_raises():
    # Only "kind" is absent (line/dev supplied) so this still isolates a SINGLE missing
    # key being named, same as it always did — not conflated with the new fit fields
    # (that conflated case is test_slot_from_dict_names_the_missing_fit_fields below).
    with pytest.raises(ValueError, match="missing"):
        Slot.from_dict({"index": 0, "start": 0.0, "dur": 1.0, "energy": 0.5,
                        "line": None, "dev": 0.0})


def _spine():
    return Spine(slots=(
        Slot(0, 0.0, 1.0, 0.05, "hook"),
        Slot(1, 1.0, 4.0, 0.28, "release"),
        Slot(2, 5.0, 1.0, 0.95, "peak")), target_dur=6.0, tempo=120.0)


def test_spine_round_trips():
    sp = _spine()
    assert Spine.from_dict(sp.to_dict()) == sp
    assert sp.to_dict()["target_dur"] == 6.0 and len(sp.to_dict()["slots"]) == 3


def test_spine_to_markdown_has_row_per_slot_hook_first():
    md = _spine().to_markdown()
    assert md.count("\n|") >= 4                     # header sep + 3 rows
    assert "hook" in md.splitlines()[4]             # first data row is the hook
    assert "120" in md.splitlines()[0]              # header names the tempo


@pytest.mark.parametrize("slots, match", [
    ((Slot(0, 0.0, 1.0, 0.5, "build"),), "hook"),                     # slot 0 not hook
    ((Slot(0, 0.5, 1.0, 0.5, "hook"),), "0.0"),                       # slot 0 start != 0
    ((Slot(0, 0.0, 1.0, 0.5, "hook"), Slot(1, 2.0, 1.0, 0.5, "peak")), "contiguous"),  # gap
    ((), "non-empty"),                                                # empty
])
def test_spine_rejects_bad_shape(slots, match):
    with pytest.raises(ValueError, match=match):
        Spine(slots=slots, target_dur=10.0, tempo=120.0)


def test_spine_rejects_wrong_duration_sum():
    with pytest.raises(ValueError, match="sum"):
        Spine(slots=(Slot(0, 0.0, 1.0, 0.5, "hook"),), target_dur=9.0, tempo=120.0)


def test_spine_rejects_misordered_index():
    with pytest.raises(ValueError, match="index-ordered"):
        Spine(slots=(Slot(0, 0.0, 1.0, 0.5, "hook"), Slot(5, 1.0, 1.0, 0.5, "peak")),
              target_dur=2.0, tempo=120.0)


def test_kind_bands():
    assert pacing._kind(0.0) == "release" and pacing._kind(0.32) == "release"
    assert pacing._kind(0.33) == "build" and pacing._kind(0.65) == "build"
    assert pacing._kind(0.66) == "peak" and pacing._kind(1.0) == "peak"


def test_beat_energy_min_max_normalizes_within_track():
    # 4 beats every 1s over 4s; energy 2 Hz => 8 samples; quiet first half, loud second
    beats = [0.0, 1.0, 2.0, 3.0]
    energy = [0.1, 0.1, 0.1, 0.1, 0.9, 0.9, 0.9, 0.9]   # samples at 0.0,0.5,...,3.5s
    n = pacing._beat_energy(beats, energy, energy_hz=2.0, duration=4.0)
    assert len(n) == 4
    assert n[0] == 0.0 and n[3] == 1.0                  # min-max: quietest→0, loudest→1
    assert n[2] == 1.0                                  # beat 2 spans [2,3): loud samples


def test_beat_energy_flat_curve_is_mid():
    n = pacing._beat_energy([0.0, 1.0], [0.5, 0.5, 0.5, 0.5], energy_hz=2.0, duration=2.0)
    assert n == [0.5, 0.5]                              # range < _FLAT_EPS → uniform 0.5


def test_beat_energy_fewer_samples_than_beats_uses_fallback():
    # spec §8: a COARSE curve with fewer energy samples than beats still yields one
    # value per beat — exercises the empty-segment fallback (the i0>=len guard the
    # 2 Hz-vs-slower-curve case relies on). 2 samples (0.5 Hz → t=0s, 2s) for 4 beats.
    n = pacing._beat_energy([0.0, 1.0, 2.0, 3.0], [0.2, 0.8], energy_hz=0.5, duration=4.0)
    assert len(n) == 4                                  # one value per beat, no crash on the tail
    assert n[0] == 0.0 and n[-1] == 1.0                 # min-max over the resolved per-beat means


@pytest.mark.parametrize("d,name", [([], "list"), ([1, 2], "list"), ("str", "str"), (42, "int"),
                                    (4.5, "float"), (True, "bool"), (None, "NoneType")])
def test_slot_from_dict_rejects_a_non_object_top_level(d, name):
    # `k not in d` raised a bare TypeError on a scalar top level and mis-reported a list/str
    # one as "missing key(s)". Slot is read via Spine.from_dict (which now guards its own top
    # level), but from_dict is public contract surface and owes ValueError-with-remedy.
    with pytest.raises(ValueError) as ei:
        Slot.from_dict(d)
    msg = str(ei.value)
    assert "expected a slot object" in msg
    assert f"got {name}" in msg
    assert "re-run pacing" in msg
    for bad in ("has no attribute", "not iterable", "not subscriptable", "indices must be"):
        assert bad not in msg


@pytest.mark.parametrize("d,name", [([], "list"), ([1, 2], "list"), ("str", "str"), (42, "int"),
                                    (4.5, "float"), (True, "bool"), (None, "NoneType")])
def test_spine_from_dict_rejects_a_non_object_top_level(d, name):
    # `k not in d` raised a bare TypeError on a scalar top level and mis-reported a list/str
    # one as "missing key". edit_plan.py:127 reads Spine.from_json with no except, so the bare
    # TypeError crashed the driver on a wrong-shaped PACING.json.
    with pytest.raises(ValueError) as ei:
        Spine.from_dict(d)
    msg = str(ei.value)
    assert "expected a PACING.json object" in msg
    assert f"got {name}" in msg
    assert "re-run pacing" in msg
    for bad in ("has no attribute", "not iterable", "not subscriptable", "indices must be"):
        assert bad not in msg


@pytest.mark.parametrize("body", ["[]", '"str"', "42", "true", "null"])
def test_spine_from_json_non_object_top_level_names_a_remedy(body, tmp_path):
    p = tmp_path / "PACING.json"; p.write_text(body)
    with pytest.raises(ValueError, match="re-run pacing"):
        Spine.from_json(p)


def test_slot_carries_the_line_it_was_matched_to_and_its_deviation():
    s = pacing.Slot(0, 0.0, 2.0, 0.5, "hook", line=2.0, dev=0.0)
    assert (s.line, s.dev) == (2.0, 0.0)
    assert s.to_dict()["line"] == 2.0
    assert s.to_dict()["dev"] == 0.0


def test_slot_roundtrips_line_and_dev():
    s = pacing.Slot(1, 2.0, 3.0, 0.4, "peak", line=5.0, dev=0.02)
    assert pacing.Slot.from_dict(s.to_dict()) == s


def test_slot_tail_has_no_line():
    s = pacing.Slot(2, 5.0, 4.0, 0.2, "release", line=None, dev=0.0)
    assert s.line is None
    assert pacing.Slot.from_dict(s.to_dict()) == s


def test_slot_refuses_a_negative_deviation():
    with pytest.raises(ValueError, match="dev"):
        pacing.Slot(0, 0.0, 2.0, 0.5, "hook", line=2.0, dev=-0.1)


@pytest.mark.parametrize("bad", ["2.0", True, [2.0]])
def test_slot_refuses_a_nonnumeric_line(bad):
    with pytest.raises(ValueError, match="line"):
        pacing.Slot(0, 0.0, 2.0, 0.5, "hook", line=bad, dev=0.0)


def test_slot_from_dict_names_the_missing_fit_fields():
    d = {"index": 0, "start": 0.0, "dur": 2.0, "energy": 0.5, "kind": "hook"}
    with pytest.raises(ValueError, match="line"):
        pacing.Slot.from_dict(d)


def test_markdown_shows_the_line_and_deviation():
    spine = pacing.Spine((pacing.Slot(0, 0.0, 2.0, 0.5, "hook", line=2.0, dev=0.004),
                          pacing.Slot(1, 2.0, 2.0, 0.4, "peak", line=None, dev=0.0)),
                         4.0, 120.0)
    md = spine.to_markdown()
    assert "| line | dev |" in md
    assert "2.00 | 0.004" in md
    assert "| – | – |" in md


def test_fit_spine_keeps_every_episode_s_own_length_when_it_already_lands():
    beats = [i * 0.5 for i in range(40)]
    energy = [0.5] * 40
    spine, fit, rejected = pacing.fit_spine([2.0, 2.0, 2.0], beats, energy, 1.0, 120.0,
                                            [(-0.25, 0.25)] * 3)
    assert [s.dur for s in spine.slots] == pytest.approx([2.0, 2.0, 2.0])
    assert fit.level == "bar"
    assert spine.target_dur == pytest.approx(6.0)
    # fit_spine re-derives each cut's nearest grid line; the cuts land on 2.0 and 4.0 and
    # the tail (the reel's end, not a cut) has none. Locks the re-derivation's current
    # behaviour — Fit does not yet carry the per-cut line (that refactor is deferred).
    assert spine.slots[0].line == pytest.approx(2.0)
    assert spine.slots[1].line == pytest.approx(4.0)
    assert spine.slots[2].line is None


def test_fit_spine_moves_an_out_point_within_the_allowance():
    beats = [i * 0.5 for i in range(40)]
    energy = [0.5] * 40
    spine, fit, _ = pacing.fit_spine([1.9, 2.1], beats, energy, 1.0, 120.0,
                                     [(-0.25, 0.25)] * 2)
    assert spine.slots[0].dur == pytest.approx(2.0)
    assert spine.slots[1].dur == pytest.approx(2.1)   # the tail never moves
    assert spine.slots[0].dev == pytest.approx(0.0, abs=1e-9)


def test_fit_spine_slot_zero_is_the_hook_and_the_rest_are_energy_labels():
    beats = [i * 0.5 for i in range(40)]
    energy = [0.1] * 20 + [0.9] * 20
    spine, _, _ = pacing.fit_spine([2.0, 2.0, 2.0], beats, energy, 1.0, 120.0,
                                   [(-0.25, 0.25)] * 3)
    assert spine.slots[0].kind == "hook"
    assert {s.kind for s in spine.slots[1:]} <= {"build", "peak", "release"}


def test_fit_spine_covers_the_fitted_length_exactly():
    beats = [i * 0.5 for i in range(40)]
    energy = [0.5] * 40
    spine, _, _ = pacing.fit_spine([1.9, 2.1, 1.8], beats, energy, 1.0, 120.0,
                                   [(-0.25, 0.25)] * 3)
    assert sum(s.dur for s in spine.slots) == pytest.approx(spine.target_dur)
    assert spine.slots[0].start == 0.0


def test_fit_spine_refuses_an_empty_beat_grid():
    with pytest.raises(ValueError, match="no beats"):
        pacing.fit_spine([2.0], [], [0.5], 1.0, 120.0, [(0.0, 0.0)])


def test_the_ladder_is_gone():
    for dead in ("build_spine", "_beats_per_slot", "HOOK_BEATS", "SLOW_BEATS",
                 "MID_BEATS", "FAST_BEATS"):
        assert not hasattr(pacing, dead), (
            f"{dead} survived: the 2/4/8 ladder generated cut LENGTHS, which the "
            "material now owns (design 2026-07-24 §5)")


# --- music_digest: bind a spine to the music WINDOW it was fitted to (design
# 2026-08-16-pacing-fixed-point-design.md §4) -----------------------------------------


def test_spine_music_digest_defaults_to_empty_and_round_trips():
    s = Spine(slots=(Slot(0, 0.0, 4.0, 0.5, "hook"),), target_dur=4.0, tempo=120.0)
    assert s.music_digest == ""
    assert s.to_dict()["music_digest"] == ""
    s2 = dataclasses.replace(s, music_digest="abc")
    assert Spine.from_dict(s2.to_dict()) == s2


def test_spine_from_dict_accepts_a_pacing_json_written_before_the_digest():
    d = Spine(slots=(Slot(0, 0.0, 4.0, 0.5, "hook"),), target_dur=4.0, tempo=120.0).to_dict()
    d.pop("music_digest")
    assert Spine.from_dict(d).music_digest == ""


def test_spine_refuses_a_non_string_digest():
    with pytest.raises(ValueError, match="music_digest must be a string"):
        Spine(slots=(Slot(0, 0.0, 4.0, 0.5, "hook"),), target_dur=4.0, tempo=120.0,
              music_digest=7)


def test_music_identity_separates_two_windows_of_the_same_track(tmp_path):
    t = tmp_path / "t.wav"
    t.write_bytes(b"same bytes both times")
    a = music_identity(str(t), 46.0, 42.0)
    b = music_identity(str(t), 147.772, 42.0)
    assert a and b and a != b
    assert music_identity(str(t), 46.0, 42.0) == a          # deterministic


def test_music_identity_is_empty_when_the_track_cannot_be_read(tmp_path):
    assert music_identity(str(tmp_path / "missing.wav"), 0.0, 42.0) == ""


def test_the_anchor_table_reports_the_curve_contrast_beside_the_anchors():
    """design 2026-08-18 §4. The anchors table was advice with nothing qualifying it,
    and on the real run seven of eight shots produced anchors that were the min_gap
    thinning grid rather than events. The contrast column is what lets a reader tell
    the two cases apart, and a flat row says so in words instead of printing an empty
    cell that reads as "measured, nothing found".

    Found by the mutation battery: hardcoding the driver's contrast to 0.0 changed no
    test, because nothing called _report at all."""
    from scripts import pacing as driver
    from scripts.lib.gridfit import Fit
    spine = Spine(slots=(Slot(index=0, start=0.0, dur=2.0, energy=0.5, kind="hook"),),
                  target_dur=2.0, tempo=120.0)
    fit = Fit(level="beat", level_n=1, phase=0, shifts=(0.0,), devs=(), needs=(),
              worst=0.0, total=0.0, fits=True)
    md = driver._report(spine, fit, [], "track.mp3",
                        {0: ([1.5, 3.0], 0.08), 1: ([], 1.0), 2: ([], 0.10)})
    assert "| 0 | 8% | 1.50, 3.00 |" in md
    assert "| 1 | 100% | flat — no moment is distinguishable |" in md   # the plateau
    assert "| 2 | 10% | – |" in md      # low contrast, genuinely no local maximum


def test_a_slot_no_beat_reaches_records_that_its_energy_is_a_fallback():
    """fit_spine's `or [0.5]` is not a measurement, and _kind labels the slot from it.
    On the real run four slots of pacing_B read energy 0.500 / kind 'build' because
    that window's first beat is at 9.74s (design 2026-09-07 §0.4)."""
    beats = [4.0 + i * 0.5 for i in range(40)]      # nothing before t=4.0
    energy = [0.5] * 60
    spine, _, _ = pacing.fit_spine([2.0, 2.0, 2.0], beats, energy, 1.0, 120.0,
                                   [(-0.25, 0.25)] * 3)
    assert spine.slots[0].beats_in == 0             # [0.0, 2.0) holds no beat
    assert spine.slots[0].energy == pytest.approx(0.5)   # the value is unchanged
    assert spine.slots[2].beats_in > 0


def test_a_measured_slot_counts_the_beats_it_contains():
    beats = [i * 0.5 for i in range(40)]
    energy = [0.5] * 40
    spine, _, _ = pacing.fit_spine([2.0, 2.0], beats, energy, 1.0, 120.0,
                                   [(-0.25, 0.25)] * 2)
    # slot 0 spans [0.0, 2.0): beats at 0.0, 0.5, 1.0, 1.5
    assert spine.slots[0].beats_in == 4


def test_beats_in_round_trips_and_defaults_to_not_recorded():
    s = pacing.Slot(0, 0.0, 2.0, 0.5, "hook", line=2.0, dev=0.0, beats_in=4)
    assert pacing.Slot.from_dict(s.to_dict()) == s
    old = {"index": 0, "start": 0.0, "dur": 2.0, "energy": 0.5, "kind": "hook",
           "line": 2.0, "dev": 0.0}          # a PACING.json written before this slice
    assert pacing.Slot.from_dict(old).beats_in == -1


@pytest.mark.parametrize("bad", [-2, 1.5, True, "4"])
def test_a_malformed_beats_in_is_refused(bad):
    with pytest.raises(ValueError, match="Slot.beats_in must be"):
        pacing.Slot(0, 0.0, 2.0, 0.5, "hook", line=2.0, dev=0.0, beats_in=bad)


def test_the_markdown_shows_a_dash_where_nothing_was_measured():
    beats = [4.0 + i * 0.5 for i in range(40)]
    energy = [0.5] * 60
    spine, _, _ = pacing.fit_spine([2.0, 2.0, 2.0], beats, energy, 1.0, 120.0,
                                   [(-0.25, 0.25)] * 3)
    md = spine.to_markdown()
    # slot 0's own out-point (t=2.0) is far from the first beat (t=4.0), so gridfit's
    # snap moves it by the full +0.25s allowance trying to reach that line anyway —
    # dur is 2.25, not the un-shifted 2.0 (confirmed against fit_spine's actual output;
    # test_fit_spine_keeps_every_episode_s_own_length_when_it_already_lands is the
    # sibling case where the grid starts at 0.0 and no shift is needed).
    assert "| 0 | 0.00–2.25 | 2.25 | – | – |" in md
    assert "contain no beat of the analysed window" in md


def test_the_markdown_of_a_fully_measured_spine_carries_no_footnote():
    beats = [i * 0.5 for i in range(40)]
    energy = [0.5] * 40
    spine, _, _ = pacing.fit_spine([2.0, 2.0], beats, energy, 1.0, 120.0,
                                   [(-0.25, 0.25)] * 2)
    assert "contain no beat" not in spine.to_markdown()


# --- energy_agreement: does the cut agree with the music's energy? (design
# 2026-09-07-named-absence-design.md §6) -----------------------------------------------


def _slot(i, start, dur, energy, beats_in=4):
    return pacing.Slot(i, start, dur, energy, "hook" if i == 0 else "build",
                       line=None, dev=0.0, beats_in=beats_in)


def test_energy_agreement_is_negative_when_short_shots_sit_where_it_is_loud():
    slots = (_slot(0, 0.0, 4.0, 0.2), _slot(1, 4.0, 3.0, 0.5),
             _slot(2, 7.0, 2.0, 0.9))
    rho, used, total, why = pacing.energy_agreement(slots)
    assert rho == pytest.approx(-1.0)
    assert (used, total, why) == (3, 3, "")


def test_energy_agreement_is_positive_when_the_cut_inverts_the_curve():
    slots = (_slot(0, 0.0, 2.0, 0.2), _slot(1, 2.0, 3.0, 0.5),
             _slot(2, 5.0, 4.0, 0.9))
    rho, _, _, _ = pacing.energy_agreement(slots)
    assert rho == pytest.approx(1.0)


def test_energy_agreement_excludes_slots_whose_energy_was_never_measured():
    """Including them moves the number: measured on the real run's pacing_B, the
    Pearson correlation is +0.276 over all 18 slots and +0.160 over the 14 measured
    ones (design §0.4). The hole in the report biases the statistic that describes
    the report."""
    slots = (_slot(0, 0.0, 4.0, 0.5, beats_in=0), _slot(1, 4.0, 4.0, 0.2),
             _slot(2, 8.0, 3.0, 0.5), _slot(3, 11.0, 2.0, 0.9))
    rho, used, total, why = pacing.energy_agreement(slots)
    assert (used, total, why) == (3, 4, "")
    assert rho == pytest.approx(-1.0)     # the three measured slots agree perfectly


def test_a_pre_slice_spine_is_included_rather_than_reported_unmeasurable():
    """beats_in == -1 means the count was not recorded, not that it was zero.
    Excluding every slot of an old spine would report "not measurable" for a spine
    that is merely unlabelled."""
    slots = (_slot(0, 0.0, 4.0, 0.2, beats_in=-1), _slot(1, 4.0, 3.0, 0.5, beats_in=-1),
             _slot(2, 7.0, 2.0, 0.9, beats_in=-1))
    rho, used, total, why = pacing.energy_agreement(slots)
    assert (used, total, why) == (3, 3, "")
    assert rho == pytest.approx(-1.0)


def test_too_few_measured_slots_names_the_reason_instead_of_returning_zero():
    slots = (_slot(0, 0.0, 4.0, 0.5, beats_in=0), _slot(1, 4.0, 3.0, 0.5, beats_in=0),
             _slot(2, 7.0, 2.0, 0.9))
    rho, used, total, why = pacing.energy_agreement(slots)
    assert rho is None and (used, total) == (1, 3)
    assert "1 of 3" in why and "needed to rank" in why


def test_too_few_slots_when_every_one_was_measured_names_slot_count_not_measurement():
    """len(usable) == total == 2: the shortfall is slot count, not measurement — the
    prior single-arm message rendered "only 2 of 2 slots carry a measured energy",
    telling a reader the energy measurement fell short when both slots WERE measured
    (final review I-4). This is the default rendering for every two-episode reel."""
    slots = (_slot(0, 0.0, 4.0, 0.2), _slot(1, 4.0, 3.0, 0.5))
    rho, used, total, why = pacing.energy_agreement(slots)
    assert rho is None and (used, total) == (2, 2)
    assert why == "the spine has only 2 slots and 3 are needed to rank"


def test_a_constant_series_names_the_reason_instead_of_raising():
    """statistics.correlation raises StatisticsError on a constant input; the function
    owns that refusal rather than letting it escape into the report builder."""
    slots = (_slot(0, 0.0, 3.0, 0.5), _slot(1, 3.0, 3.0, 0.5), _slot(2, 6.0, 3.0, 0.5))
    rho, used, total, why = pacing.energy_agreement(slots)
    assert rho is None and (used, total) == (3, 3)
    assert "no ordering to correlate" in why


# --- held slots: the grid authored their length (design 2026-10-21 §2) ----------------

def test_a_slot_is_footage_unless_held_and_says_so_only_when_held():
    s = Slot(0, 0.0, 1.5, 0.4, "hook")
    assert s.held is False and "held" not in s.to_dict()
    h = Slot(1, 1.5, 1.0, 0.4, "build", line=2.5, dev=0.0, beats_in=2, held=True)
    assert h.to_dict() == {"index": 1, "start": 1.5, "dur": 1.0, "energy": 0.4,
                           "kind": "build", "line": 2.5, "dev": 0.0, "beats_in": 2,
                           "held": True}
    assert Slot.from_dict(h.to_dict()) == h
    assert Slot.from_dict(s.to_dict()) == s


def test_a_held_slot_records_the_authored_count_it_was_fitted_with_only_when_there_is_one():
    h = Slot(1, 1.5, 1.5, 0.4, "build", line=3.0, dev=0.0, beats_in=3, held=True, hold=3)
    assert h.to_dict() == {"index": 1, "start": 1.5, "dur": 1.5, "energy": 0.4,
                           "kind": "build", "line": 3.0, "dev": 0.0, "beats_in": 3,
                           "held": True, "hold": 3}
    assert Slot.from_dict(h.to_dict()) == h
    planned = dataclasses.replace(h, hold=None)
    assert "hold" not in planned.to_dict() and Slot.from_dict(planned.to_dict()) == planned


@pytest.mark.parametrize("kw, match", [
    (dict(held=True, hold=0), "Slot.hold must be a whole number"),
    (dict(held=True, hold=True), "Slot.hold must be a whole number"),
    (dict(held=True, hold=2.0), "Slot.hold must be a whole number"),
    (dict(held=False, hold=2), "slot 1 is not held"),
])
def test_a_slot_refuses_a_hold_that_is_not_a_held_slots_count(kw, match):
    with pytest.raises(ValueError, match=match):
        Slot(1, 1.5, 1.0, 0.4, "build", **kw)


def test_fit_spine_records_each_held_slots_authored_count():
    h = gridfit.Held(None, 1 / 3, 8.0)
    spine, _, _ = pacing.fit_spine([8.0, 2.0, 2.0, 3.0], _STEP_BEATS, _STEP_ENERGY, 2.0,
                                   120.0, [(-0.25, 0.25)] * 4,
                                   held=[None, gridfit.Held(3, 1 / 3, 8.0), h, None])
    assert [s.hold for s in spine.slots] == [None, 3, None, None]


@pytest.mark.parametrize("bad", [1, "yes", None])
def test_a_slot_refuses_a_non_bool_held(bad):
    with pytest.raises(ValueError, match="Slot.held"):
        Slot(0, 0.0, 1.0, 0.5, "hook", held=bad)


_STEP_BEATS = [i * 0.5 for i in range(48)]             # 120 BPM, 24 s
_STEP_ENERGY = [0.0] * 16 + [0.5] * 16 + [1.0] * 16    # one sample per beat: quiet, mid, loud


def test_the_planner_shortens_holds_into_the_loud_part():
    plan = pacing.hold_planner(_STEP_BEATS, _STEP_ENERGY, 2.0, 120.0)
    # release 2.0 s, build 1.0 s, peak 0.5 s at a 0.5 s beat (design §2.1)
    assert (plan(0.0, ()), plan(8.0, ()), plan(16.0, ())) == (4, 2, 1)


def test_the_planner_reads_the_next_bar_from_the_in_point():
    plan = pacing.hold_planner(_STEP_BEATS, _STEP_ENERGY, 2.0, 120.0)
    # [7.0, 9.0) holds two quiet beats and two mid ones: 0.25, still release
    assert plan(7.0, ()) == 4
    # [7.5, 9.5): one quiet, three mid — 0.375, build
    assert plan(7.5, ()) == 2
    # past the last beat nothing falls in the bar: the nearest beat's energy, peak
    assert plan(40.0, ()) == 1


def test_the_planner_never_gives_one_count_three_times_in_a_run():
    plan = pacing.hold_planner(_STEP_BEATS, _STEP_ENERGY, 2.0, 120.0)
    assert plan(8.0, (2, 2)) == 4
    assert plan(16.0, (1, 1)) == 2


def test_fit_spine_marks_held_slots_and_authors_their_lengths_in_whole_beats():
    h = gridfit.Held(None, 1 / 3, 8.0)
    held = [None] + [h] * 6 + [None]
    durs = [12.0] + [2.0] * 6 + [3.0]
    spine, fit, _ = pacing.fit_spine(durs, _STEP_BEATS, _STEP_ENERGY, 2.0, 120.0,
                                     [(-0.25, 0.25)] * 8, held=held)
    assert [s.held for s in spine.slots] == [False] + [True] * 6 + [False]
    counts = [s.dur / 0.5 for s in spine.slots[1:7]]
    assert counts == [round(c) for c in counts]          # whole beats, exactly
    # the run opens at 12.0 in the mid part: 2, 2, then the third doubles; at 16.0 the
    # music turns loud and the holds shorten to one beat, and the third of those doubles
    # too. The run's LAST hold reaches a line only inside [k/2, 2k] beats of that plan:
    # the bar line at 18.0 is on it, so the cut back to footage lands on a bar like the
    # cut into the run did. The phrase line at 20.0 is 6 beats on — out of the band, and
    # reaching it used to be how phrase "fit" (design §2.2)
    assert counts == [2, 2, 4, 1, 1, 2]
    assert (fit.level, fit.fits) == ("bar", True)
    assert spine.slots[6].line == 18.0 and spine.slots[6].dev == 0.0
    assert sum(s.dur for s in spine.slots) == pytest.approx(spine.target_dur)


def test_the_runs_last_hold_keeps_its_length_class_instead_of_reaching_a_far_line():
    # Task 2's own measured case — the fixed-point fixture's cut (a video, a freeze, two
    # photos, a video closer) on its quiet -> mid -> loud track. Searching all of
    # [HOLD_MIN, HOLD_ROOM] for a line, the last photo (planned at 2 beats) was bound to
    # 10 to reach the phrase line at 14.0, and phrase "fit". Inside [k/2, 2k] it keeps
    # its 2 beats and the reel fits a finer level instead (design §2.2).
    h = gridfit.Held(None, 1 / 3, 8.0)
    spine, fit, rejected = pacing.fit_spine(
        [6.0, 2.0, 2.0, 2.0, 4.0], [i * 0.5 for i in range(40)],
        [0.1] * 16 + [0.5] * 12 + [0.9] * 12, 2.0, 120.0,
        [(-0.25, 0.25), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (-0.25, 0.25)],
        held=[None, h, h, h, None])
    assert [s.dur / 0.5 for s in spine.slots] == [12, 4, 2, 2, 8]
    assert (fit.level, fit.fits) == ("2-bar", True)
    assert [(f.level, f.fits) for f in rejected] == [("phrase", False)]


def test_a_held_slot_inside_a_run_is_matched_to_the_beat_it_landed_on():
    h = gridfit.Held(None, 1 / 3, 8.0)
    spine, _, _ = pacing.fit_spine([8.0, 2.0, 2.0, 3.0], _STEP_BEATS, _STEP_ENERGY, 2.0,
                                   120.0, [(-0.25, 0.25)] * 4, held=[None, h, h, None])
    inside = spine.slots[1]
    assert inside.line == pytest.approx(inside.start + inside.dur) and inside.dev == 0.0


def test_fit_spine_without_held_is_the_fit_it_always_was():
    beats, energy = [i * 0.5 for i in range(40)], [0.5] * 40
    plain = pacing.fit_spine([1.9, 2.1, 1.8], beats, energy, 1.0, 120.0, [(-0.25, 0.25)] * 3)
    listed = pacing.fit_spine([1.9, 2.1, 1.8], beats, energy, 1.0, 120.0, [(-0.25, 0.25)] * 3,
                              held=[None, None, None])
    assert plain == listed


def test_energy_agreement_leaves_out_held_slots():
    """A held length is derived FROM the energy, so ranking it would report the planner
    agreeing with itself."""
    slots = (_slot(0, 0.0, 4.0, 0.2), _slot(1, 4.0, 3.0, 0.5),
             dataclasses.replace(_slot(2, 7.0, 4.0, 0.95), held=True),
             _slot(3, 11.0, 2.0, 0.9))
    rho, used, total, why = pacing.energy_agreement(slots)
    assert (used, total, why) == (3, 4, "")
    assert rho == pytest.approx(-1.0)        # the held 4.0 s at 0.95 would have broken it


def test_too_few_footage_slots_names_the_held_ones_as_the_reason():
    slots = (_slot(0, 0.0, 4.0, 0.2), dataclasses.replace(_slot(1, 4.0, 1.0, 0.9), held=True),
             dataclasses.replace(_slot(2, 5.0, 0.5, 0.95), held=True), _slot(3, 5.5, 2.0, 0.5))
    rho, used, total, why = pacing.energy_agreement(slots)
    assert rho is None and (used, total) == (2, 4)
    assert "2 are held" in why and "planner agreeing with itself" in why
    assert "3 are needed to rank" in why


def test_the_markdown_names_a_held_slots_beats_and_leaves_footage_rows_alone():
    sp = Spine(slots=(Slot(0, 0.0, 2.0, 0.1, "hook", line=2.0, dev=0.0, beats_in=4),
                      Slot(1, 2.0, 1.0, 0.6, "build", line=3.0, dev=0.0, beats_in=2,
                           held=True),
                      Slot(2, 3.0, 0.5, 0.9, "peak", line=3.5, dev=0.0, beats_in=1,
                           held=True),
                      Slot(3, 3.5, 1.5, 0.9, "peak", line=None, dev=0.0, beats_in=3)),
               target_dur=5.0, tempo=120.0)
    assert sp.to_markdown() == (
        "# Pacing — fitted spine (4 slots, 5.0s @ 120 BPM)\n"
        "\n"
        "| # | start–end | dur | energy | kind | line | dev |\n"
        "|--:|-----------|----:|-------:|------|-----:|----:|\n"
        "| 0 | 0.00–2.00 | 2.00 | 0.10 | hook | 2.00 | 0.000 |\n"
        "| 1 | 2.00–3.00 | 1.00 | 0.60 | build · held 2 beats | 3.00 | 0.000 |\n"
        "| 2 | 3.00–3.50 | 0.50 | 0.90 | peak · held 1 beat | 3.50 | 0.000 |\n"
        "| 3 | 3.50–5.00 | 1.50 | 0.90 | peak | – | – |\n"
        "\n"
        "*A held slot's kind is the energy band of its own span; its beat count was planned "
        "from the bar that opens it (or authored), so the two can disagree.*\n")


def test_a_spine_with_no_held_slot_carries_no_held_note():
    sp = Spine(slots=(Slot(0, 0.0, 2.0, 0.1, "hook", line=2.0, dev=0.0, beats_in=4),
                      Slot(1, 2.0, 1.5, 0.9, "peak", line=None, dev=0.0, beats_in=3)),
               target_dur=3.5, tempo=120.0)
    assert "held" not in sp.to_markdown()
