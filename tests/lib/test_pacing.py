"""pacing core — pure stdlib, no librosa/numpy; exact-slot asserts (bit-exact)."""
import dataclasses

import pytest

from scripts.lib import pacing
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
