import json

import pytest
from scripts.lib import manifest as mf
from scripts.lib import vidstab
from scripts.lib.footage import DESCRIPTOR_LEN, Cast, CastMember


def _ok_dict(**over):
    d = dict(segment="seg.mp4", out_path="out.mp4", composition="lead",
             grid="thirds", canvas=[9, 16], target_dur=3.0)
    d.update(over)
    return d


def test_from_dict_defaults():
    m = mf.Manifest.from_dict(_ok_dict())
    assert m.layout == "fill"
    assert m.stabilize is False
    assert m.color_means == (105, 122, 137)
    assert m.canvas == (9, 16)           # list coerced to tuple
    assert m.model == "yolo11n-seg.pt"


def test_from_dict_missing_required_raises():
    d = _ok_dict(); del d["composition"]
    with pytest.raises(KeyError, match="composition"):
        mf.Manifest.from_dict(d)


def test_validate_ok():
    assert mf.validate(mf.Manifest.from_dict(_ok_dict())) == []


def test_validate_unknown_composition():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(composition="Lead")))
    assert any("composition" in p for p in problems)


def test_validate_unknown_grid():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(grid="golden-canon")))
    assert any("grid" in p for p in problems)


def test_validate_unsupported_layout_refused():
    # fit/insert are first-class layouts now; a genuinely unknown one still
    # fails the soft gate, with a message that names what IS supported.
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(layout="pan")))
    # the FULL enumeration, not a bare "fit": "fit" is a substring of "fit-blur",
    # so the loose form would pass against the pre-rename spelling too and let a
    # revert of that message regress silently. This is the only test that reads it.
    assert any("pan" in p and "fill/fit/insert" in p for p in problems)


def test_validate_nonpositive_duration():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(target_dur=0)))
    assert any("target_dur" in p for p in problems)


def test_validate_bad_canvas():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(canvas=[9, 16, 1])))
    assert any("canvas" in p for p in problems)


def test_validate_bad_motion_string():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(motion="sideways")))
    assert any("motion" in p for p in problems)


def test_validate_accepts_known_motion():
    for good in ("lateral:right", "lateral:left", "head-on", "static"):
        assert mf.validate(mf.Manifest.from_dict(_ok_dict(motion=good))) == []


def test_explicit_null_required_raises():
    d = _ok_dict(canvas=None)
    with pytest.raises(KeyError, match="canvas"):
        mf.Manifest.from_dict(d)


def test_explicit_null_optional_uses_default_not_crash():
    m = mf.Manifest.from_dict(_ok_dict(color_means=None, model=None, layout=None))
    assert m.color_means == (105, 122, 137)
    assert m.model == "yolo11n-seg.pt"
    assert m.layout == "fill"          # explicit null → default, not a needs_input


def test_unknown_key_raises():
    with pytest.raises(KeyError, match="stablize"):
        mf.Manifest.from_dict(_ok_dict(stablize=True))   # typo of stabilize


def test_hero_list_coerced_to_tuple():
    m = mf.Manifest.from_dict(_ok_dict(hero=[900, 500, 120, 300]))
    assert m.hero == (900, 500, 120, 300)
    assert isinstance(m.hero, tuple)


def test_hero_string_rule_kept():
    m = mf.Manifest.from_dict(_ok_dict(hero="largest"))
    assert m.hero == "largest"


def test_validate_bad_model():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(model="yolo11n-set.pt")))
    assert any("model" in p for p in problems)


def test_validate_color_means_wrong_length():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(color_means=[255, 10])))
    assert any("color_means" in p for p in problems)


def test_validate_canvas_nonpositive():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(canvas=[0, 16])))
    assert any("canvas" in p for p in problems)


def test_validate_empty_segment():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(segment="")))
    assert any("segment" in p for p in problems)


def test_delivery_defaults_native():
    m = mf.Manifest.from_dict(_ok_dict())
    assert m.delivery == "native"


def test_delivery_passthrough():
    m = mf.Manifest.from_dict(_ok_dict(delivery="short_edge:1080"))
    assert m.delivery == "short_edge:1080"
    assert mf.validate(m) == []


def test_validate_bad_delivery():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(delivery="huge:9999x")))
    assert any("delivery" in p for p in problems)


def test_validate_color_means_nonpositive():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(color_means=[0, 122, 137])))
    assert any("color_means" in p for p in problems)


# --- Task 9: fit / insert layouts, JSON array coercion, zero-freedom gate ---

def _base(**over):
    d = dict(segment="a.mp4", out_path="o.mp4", composition="lead", grid="thirds",
             canvas=[9, 16], target_dur=3.0)
    d.update(over)
    return d


def test_fit_and_insert_are_now_supported():
    m = mf.Manifest.from_dict(_base(layout="fit", crop_aspect="source",
                                    composition="break"))
    assert mf.validate(m) == []
    m = mf.Manifest.from_dict(_base(layout="insert", crop_aspect=[1, 1],
                                    rect=[0.05, 0.25, 0.9]))
    assert mf.validate(m) == []


def test_json_arrays_become_tuples():
    m = mf.Manifest.from_dict(_base(layout="insert", crop_aspect=[1, 1],
                                    rect=[0.05, 0.25, 0.9]))
    assert m.crop_aspect == (1, 1)
    assert m.rect == (0.05, 0.25, 0.9)


def test_lead_at_zero_freedom_is_refused_with_a_remedy():
    m = mf.Manifest.from_dict(_base(layout="fit", crop_aspect="source",
                                    composition="lead"))
    problems = mf.validate(m)
    assert len(problems) == 1
    assert "crop_scale" in problems[0] and "break" in problems[0]


def test_lead_with_a_scaled_crop_is_allowed():
    m = mf.Manifest.from_dict(_base(layout="fit", crop_aspect="source",
                                    composition="lead", crop_scale=0.9))
    assert mf.validate(m) == []


def test_a_bad_layout_field_becomes_a_problem_not_a_crash():
    m = mf.Manifest.from_dict(_base(layout="insert", crop_aspect=[1, 1]))
    problems = mf.validate(m)
    assert any("insert needs a rect" in p for p in problems)


def test_split_is_still_refused():
    m = mf.Manifest.from_dict(_base(layout="split"))
    assert any("split" in p for p in mf.validate(m))


def test_insert_border_fields_round_trip_and_validate_clean():
    # border_px/border_color ride the manifest onto the Manifest and pass the gate.
    m = mf.Manifest.from_dict(_base(layout="insert", crop_aspect=[1, 1],
                                    rect=[0.05, 0.25, 0.9], border_px=8,
                                    border_color="black"))
    assert m.border_px == 8
    assert m.border_color == "black"
    assert mf.validate(m) == []


def test_fill_with_a_border_is_a_problem_not_a_crash():
    # LayoutSpec raises for a bordered fill; the soft gate must catch it, not die.
    m = mf.Manifest.from_dict(_base(layout="fill", border_px=8))
    problems = mf.validate(m)
    assert any("border" in p for p in problems)


def test_manifest_carries_the_background_colour_to_the_gate():
    m = mf.Manifest.from_dict({
        "segment": "a.mp4", "out_path": "o.mp4", "target_dur": 2.0,
        "composition": "break", "grid": "thirds", "canvas": [9, 16],
        "layout": "fit", "crop_aspect": "source",
        "background": "solid", "background_color": "#101820"})
    assert (m.background, m.background_color) == ("solid", "#101820")
    assert mf.validate(m) == []


def test_manifest_gate_reports_a_bad_background_colour_as_a_problem():
    # The gate is SOFT: LayoutSpec's ValueError becomes a problem string, never a raise.
    m = mf.Manifest.from_dict({
        "segment": "a.mp4", "out_path": "o.mp4", "target_dur": 2.0,
        "composition": "break", "grid": "thirds", "canvas": [9, 16],
        "layout": "fit", "crop_aspect": "source",
        "background": "solid", "background_color": "bla:ck"})
    # Pins the FIELD NAME and the OFFENDING VALUE in one substring. The phrase
    # "break the ffmpeg filtergraph" alone is verbatim in border_color's raise too,
    # so it survives both erasing the message down to that phrase and the realistic
    # copy-paste bug where this raise names border_color and prints self.border_color.
    assert any("background_color 'bla:ck'" in p for p in mf.validate(m))


# --- Task 5: cast field + hero.resolve as validate()'s oracle ---

def _cast():
    # a descriptor is DESCRIPTOR_LEN floats — CastMember rejects any other length
    return Cast(members=[CastMember(name="Lena", descriptor=[0.5, 0.5] + [0.0] * (DESCRIPTOR_LEN - 2))])


def test_cast_path_round_trips():
    m = mf.Manifest.from_dict(_ok_dict(cast="proj/cast.json"))
    assert m.cast == "proj/cast.json"


def test_cast_defaults_to_empty():
    assert mf.Manifest.from_dict(_ok_dict()).cast == ""


def test_hero_track_id_survives_from_dict():
    assert mf.Manifest.from_dict(_ok_dict(hero=3)).hero == 3


def test_validate_accepts_a_rule_hero_without_a_cast():
    assert mf.validate(mf.Manifest.from_dict(_ok_dict(hero="largest"))) == []


def test_validate_accepts_a_known_cast_name():
    m = mf.Manifest.from_dict(_ok_dict(hero="Lena", cast="proj/cast.json"))
    assert mf.validate(m, cast=_cast()) == []


def test_validate_flags_a_cast_name_with_no_registry():
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(hero="Lena")))
    assert any("cast.json" in p for p in problems)


def test_validate_flags_an_unknown_cast_name():
    m = mf.Manifest.from_dict(_ok_dict(hero="Lna", cast="proj/cast.json"))
    assert any("Lena" in p for p in mf.validate(m, cast=_cast()))


def test_validate_flags_a_malformed_hero():
    # Strengthened beyond a bare truthiness check: each of these must name the hero
    # field specifically, not merely produce SOME problem. All three otherwise-valid
    # dicts pass validate() clean (see test_validate_ok), so a bare `assert problems`
    # would still pass today even if the message were about something else entirely —
    # this pins the message content, not just the list's non-emptiness.
    for bad in ([1, 2, 3], True, 4.2):
        problems = mf.validate(mf.Manifest.from_dict(_ok_dict(hero=bad)))
        assert any("hero" in p for p in problems), (bad, problems)


def test_validate_flags_an_unrepresentable_hero_bbox_softly():
    """The soft gate must NEVER raise — it returns problems a human answers.

    Both of these are what json.loads produces from a hand-authored manifest, and
    both used to defeat the gate: a 400-digit int reached float() and came back as
    OverflowError (which validate() does not catch, so it escaped as a crash), and
    Infinity/NaN passed clean and were misdiagnosed downstream as hero-unmatched.
    Driven through json.loads rather than a Python literal because that is the only
    way the values arrive here — and because json.loads accepting bare Infinity/NaN
    at all is precisely the surprise.
    """
    for hero_json in ("9" * 400, "Infinity", "-Infinity", "NaN"):
        d = json.loads('{"hero": [%s, 500, 120, 300]}' % hero_json)
        problems = mf.validate(mf.Manifest.from_dict(_ok_dict(hero=tuple(d["hero"]))))
        assert any("hero" in p for p in problems), (hero_json, problems)


def test_validate_flags_a_non_str_cast():
    # cast is the one path field from_dict passes through raw (`d.get("cast") or ""`
    # coerces nothing), so the gate is the only thing standing between a manifest
    # typo and Cast.from_json's Path(123) — a bare TypeError, deep in the shell.
    # Every OTHER field of these dicts is valid (see test_validate_ok), so the
    # problem named here can only be the cast one.
    for bad in (123, ["proj/cast.json"], {"path": "x"}, 4.2):
        problems = mf.validate(mf.Manifest.from_dict(_ok_dict(cast=bad)))
        assert any("cast" in p for p in problems), (bad, problems)


def test_validate_accepts_an_absent_cast():
    # "" is the documented "no registry" default — it must not be a problem, or
    # every cast-less manifest (the overwhelming majority) would fail the gate
    assert mf.validate(mf.Manifest.from_dict(_ok_dict())) == []
    assert mf.validate(mf.Manifest.from_dict(_ok_dict(cast=None))) == []


@pytest.mark.parametrize("d,name", [([], "list"), ([1, 2], "list"), ("str", "str"), (42, "int"),
                                    (4.5, "float"), (True, "bool"), (None, "NoneType")])
def test_manifest_from_dict_rejects_a_non_object_top_level(d, name):
    # Manifest.from_dict is already HARD (KeyError for missing/unknown fields); the SOFT gate
    # lives at its two callers, which turn every raise into needs_input / stop_and_report
    # (process_episode.py:52 and edl.py:205 both catch (KeyError, TypeError, ValueError)).
    # So a ValueError here needs no call-site change — it flows into the soft channel already.
    # Before the guard, `for k in REQUIRED: d.get(k)` raised AttributeError, which NEITHER
    # caller catches: the one exception that would crash the gate that promises never to.
    with pytest.raises(ValueError) as ei:
        mf.Manifest.from_dict(d)
    msg = str(ei.value)
    assert "expected a manifest object" in msg
    assert f"got {name}" in msg
    assert "segment" in msg                      # names the required fields
    assert "has no attribute" not in msg


@pytest.mark.parametrize("d", [[], "str", 42, None])
def test_manifest_non_dict_reaches_the_soft_gate_as_needs_input_not_a_crash(d, tmp_path):
    # The end-to-end proof of the paragraph above: process_episode's gate must report softly.
    from scripts import process_episode
    res = process_episode.process_episode(d, str(tmp_path / "out"))
    assert res["status"] == "needs_input"
    assert any("expected a manifest object" in p for p in res["problems"])


# --- Task 6: Manifest.pan + the gate's two refusals ---
#
# _base()'s own default composition is "lead" (see above), not "center" — every
# test below that expects a CLEAN validate() (or a single, isolated problem)
# pins composition="center" explicitly, or the pre-existing lead/break refusal
# would ride along uninvited and either fail the clean-validate assertion or
# inflate a len(problems) == 1 count. See the task report for the full audit.

def test_manifest_carries_a_pan():
    m = mf.Manifest.from_dict(_base(composition="center", pan={"from": 0.2, "to": 0.7}))
    assert m.pan == {"from": 0.2, "to": 0.7}
    assert mf.validate(m) == []


def test_manifest_defaults_to_no_pan():
    assert mf.Manifest.from_dict(_base()).pan is None


def test_validate_reports_a_malformed_pan_as_a_problem_not_a_raise():
    # the soft gate uses PanSpec as its ORACLE: one constructor for validation
    # and for the shell's real build, so the two cannot drift apart
    m = mf.Manifest.from_dict(_base(composition="center", pan={"from": 0.0, "to": 3.0}))
    problems = mf.validate(m)
    assert len(problems) == 1
    assert "[0.0, 1.0]" in problems[0] and "3.0" in problems[0]


def test_validate_reports_a_pan_missing_a_key():
    m = mf.Manifest.from_dict(_base(composition="center", pan={"from": 0.0}))
    problems = mf.validate(m)
    assert any("to" in p for p in problems)


def test_validate_reports_an_empty_pan_as_a_problem():
    # `if m.pan is not None:` must not become `if m.pan:` — an empty dict is
    # FALSY, so truthiness would skip the whole block and return a clean gate for
    # a pan that cannot construct. process_episode then builds PanSpec.from_dict
    # bare, trusting "validate() already proved it constructs", and raises out of
    # a shell whose job is to never raise.
    m = mf.Manifest.from_dict(_base(composition="center", pan={}))
    problems = mf.validate(m)
    assert any("from" in p and "to" in p for p in problems), problems


@pytest.mark.parametrize("comp", ["lead", "break"])
def test_validate_refuses_a_pan_with_a_subject_relative_composition(comp):
    m = mf.Manifest.from_dict(_base(composition=comp, pan={"from": 0.0, "to": 1.0}))
    problems = mf.validate(m)
    assert any("pan" in p and comp in p and "center" in p for p in problems), problems


def test_validate_allows_a_pan_with_center():
    m = mf.Manifest.from_dict(_base(composition="center", pan={"from": 0.0, "to": 1.0}))
    assert mf.validate(m) == []


def test_validate_refuses_a_pan_that_also_pins_a_hero():
    # "largest" is a HERO_RULES rule pin — hero.resolve accepts it with cast=None
    # (see test_validate_accepts_a_rule_hero_without_a_cast above), so it isolates
    # the pan+hero refusal instead of also collecting a malformed-pin problem.
    m = mf.Manifest.from_dict(_base(composition="center", pan={"from": 0.0, "to": 1.0},
                                    hero="largest"))
    problems = mf.validate(m)
    assert any("pan" in p and "hero" in p for p in problems), problems


def test_validate_allows_a_pan_beside_a_static_motion():
    # motion describes the SUBJECT, pan describes the CAMERA. The canonical pan
    # is a still subject and a moving frame — both true at once.
    m = mf.Manifest.from_dict(_base(composition="center", pan={"from": 0.0, "to": 1.0},
                                    motion="static"))
    assert mf.validate(m) == []


# --- stabilize-apply Task 6: the gate checks vidstab instead of refusing it ---
#
# _ok_dict() at the top of this file already builds a manifest that validates
# clean (see test_validate_ok), so `_ok_dict(stabilize=True)` isolates exactly
# the stabilize problem — no separate builder needed here.

def test_stabilize_true_is_no_longer_refused(monkeypatch):
    monkeypatch.setattr(vidstab, "require", lambda: None)
    assert mf.validate(mf.Manifest.from_dict(_ok_dict(stabilize=True))) == []


def test_stabilize_true_on_a_build_without_the_filter_is_a_problem(monkeypatch):
    """A missing filter is an environment fault, and every other manifest fault
    reaches the caller as a problem string → needs_input. Letting ffbin's
    ValueError escape validate() would make this the one that arrives as a
    traceback."""
    def _no(_=None):
        raise ValueError("/opt/slim/ffmpeg has no vidstabtransform filter — run `bash setup.sh`")
    monkeypatch.setattr(vidstab, "require", _no)
    problems = mf.validate(mf.Manifest.from_dict(_ok_dict(stabilize=True)))
    assert len(problems) == 1
    assert "vidstabtransform" in problems[0] and "setup.sh" in problems[0]


def test_a_manifest_without_stabilize_never_probes_ffmpeg(monkeypatch):
    """validate() runs in a great many tests and the probe is a real subprocess
    (ffbin.has_filter is uncached by design). Gating on the flag keeps the cost
    on the manifests that asked for it."""
    monkeypatch.setattr(vidstab, "require",
                        lambda: pytest.fail("validate() probed ffmpeg for a manifest "
                                            "that never asked to stabilize"))
    assert mf.validate(mf.Manifest.from_dict(_ok_dict())) == []


# --- colour-as-a-stage Task 9: Manifest carries the nine colour fields ---

def test_manifest_from_dict_reads_colour():
    m = mf.Manifest.from_dict(_ok_dict(white_balance=0.5, dip=0.2,
                                       tone_src=[30, 100, 148], tone_dst=[35, 110, 150]))
    assert m.white_balance == 0.5 and m.dip == 0.2 and m.tone_src == (30, 100, 148)


def test_manifest_colour_defaults_identity():
    m = mf.Manifest.from_dict(_ok_dict())
    assert (m.white_balance, m.black_point, m.saturation, m.dip) == (0.0, 0.0, 1.0, 0.0)
    assert m.tone_src is None
