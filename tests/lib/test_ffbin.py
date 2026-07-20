"""ffbin resolves the binaries the pipeline runs (design 2026-07-20 §3)."""
import ast
from pathlib import Path

import pytest

from scripts.lib import ffbin


def test_the_environment_variable_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("FFMPEG", "/from/env/ffmpeg")
    cfg = tmp_path / "ffmpeg.env"
    cfg.write_text("FFMPEG=/from/file/ffmpeg\n")
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", cfg)
    assert ffbin.ffmpeg() == "/from/env/ffmpeg"


def test_the_config_file_beats_PATH(monkeypatch, tmp_path):
    monkeypatch.delenv("FFMPEG", raising=False)
    cfg = tmp_path / "ffmpeg.env"
    cfg.write_text("FFMPEG=/from/file/ffmpeg\nFFPROBE=/from/file/ffprobe\n")
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", cfg)
    assert ffbin.ffmpeg() == "/from/file/ffmpeg"
    assert ffbin.ffprobe() == "/from/file/ffprobe"


def test_a_missing_config_falls_through_to_PATH(monkeypatch, tmp_path):
    # the portability rung: setup.sh is macOS-only, so a Linux box has no config
    # file and import must still work (design §3).
    monkeypatch.delenv("FFMPEG", raising=False)
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", tmp_path / "absent.env")
    monkeypatch.setattr(ffbin.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert ffbin.ffmpeg() == "/usr/bin/ffmpeg"


def test_a_relative_PATH_hit_is_made_absolute(monkeypatch, tmp_path):
    """shutil.which returns a RELATIVE path when PATH carries a relative entry —
    a bare "." is enough. The contract says absolute, so passing which's result
    straight through would make it false as soon as anything chdir'd.

    Replaces a `.startswith("/")` assertion that could not fail here: with an
    absolute mock it could not tell "returned which's result" from "returned
    something absolute", and the realistic mutation it claimed to guard is
    already pinned by test_a_missing_config_falls_through_to_PATH.
    """
    monkeypatch.delenv("FFMPEG", raising=False)
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", tmp_path / "absent.env")
    monkeypatch.setattr(ffbin.shutil, "which", lambda name: f"./{name}")
    assert ffbin.ffmpeg() == str(Path.cwd() / "ffmpeg")


def test_an_empty_value_in_the_file_is_not_a_path(monkeypatch, tmp_path):
    monkeypatch.delenv("FFMPEG", raising=False)
    cfg = tmp_path / "ffmpeg.env"
    cfg.write_text("FFMPEG=\n")
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", cfg)
    monkeypatch.setattr(ffbin.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert ffbin.ffmpeg() == "/usr/bin/ffmpeg"


def test_nothing_resolves_fails_loud_with_the_remedy(monkeypatch, tmp_path):
    monkeypatch.delenv("FFMPEG", raising=False)
    monkeypatch.setattr(ffbin, "_FFMPEG_ENV", tmp_path / "absent.env")
    monkeypatch.setattr(ffbin.shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="bash setup.sh"):
        ffbin.ffmpeg()


def _filters(monkeypatch, text: str):
    """Stand in for `ffmpeg -filters` output."""
    class _R:
        stdout = text.encode()
    monkeypatch.setattr(ffbin.proc, "run", lambda cmd, **kw: _R())


def test_has_filter_true_when_the_build_lists_it(monkeypatch):
    _filters(monkeypatch, " T.. drawtext   V->V   Draw text on top of video.\n")
    assert ffbin.has_filter("drawtext") is True


def test_has_filter_false_when_it_does_not(monkeypatch):
    _filters(monkeypatch, " ... scale   V->V   Scale the input video.\n")
    assert ffbin.has_filter("vidstabdetect") is False


def test_require_filter_is_silent_when_present(monkeypatch):
    _filters(monkeypatch, " T.. drawtext   V->V   Draw text.\n")
    assert ffbin.require_filter("drawtext", "run `bash setup.sh`") is None


def test_has_filter_re_probes_and_is_not_cached(monkeypatch):
    """Design §4 chose UNCACHED deliberately; this pins it instead of trusting prose.

    An lru_cache here would buy back one ~50ms `ffmpeg -filters` spawn against
    encodes measured in minutes, and pay for it with a stateful trap: any test that
    forgets cache_clear() reads a stale answer and passes for the wrong reason.
    Without this test that decision rests on review alone, and the next contributor
    to notice the repeated spawn will "optimise" it back.
    """
    answers = iter([b" T.. drawtext   V->V   Draw text.\n",
                    b" ... scale      V->V   Scale.\n"])

    class _R:
        def __init__(self, out: bytes) -> None:
            self.stdout = out

    monkeypatch.setattr(ffbin.proc, "run", lambda cmd, **kw: _R(next(answers)))
    assert ffbin.has_filter("drawtext") is True
    assert ffbin.has_filter("drawtext") is False    # asked the binary again, not a memo


def test_require_filter_fails_loud_carrying_binary_and_remedy(monkeypatch):
    _filters(monkeypatch, " ... scale   V->V   Scale.\n")
    monkeypatch.setenv("FFMPEG", "/opt/slim/ffmpeg")
    with pytest.raises(ValueError, match="/opt/slim/ffmpeg.*vidstabdetect.*setup.sh"):
        ffbin.require_filter("vidstabdetect", "run `bash setup.sh`")


# Assembled, never spelled. A line scan that occurs in its own search space matches
# its own source and can then never go green — which is how the version of this
# check proposed in the plan failed: it flagged itself plus the two docstrings above.
_PROBE_FLAG = "-" + "filters"
_QUOTES = ("'", '"')


def test_no_test_runs_its_own_filter_probe():
    """Design §5: a guard that probes PATH itself finds the slim build, skips
    forever, and reports green while three integration tests go uncovered. So no
    test may put the probe flag in an argv — ask ffbin.has_filter instead.

    The tell is universal: there is no way to ask ffmpeg what it supports without
    passing that flag. Pinning the property directly beats a meta-test per guard,
    which would cover only the guards that exist today while the failure mode is a
    FUTURE test file growing its own probe.

    EMISSION, not mention — the same line tests/lib/test_landmine_scan.py draws for
    scripts/, and for the same reason: this file's own docstrings name `ffmpeg
    -filters` twice in prose, at exactly the place a reader looks to understand the
    probe, so a scan that banned the characters would make the rule undocumentable
    at its own site. The flag counts only when QUOTED, i.e. when it is an argv
    element rather than a word in a sentence.

    The limit is real and worth naming: a probe whose flag is built from a variable
    or an f-string slips through. That is the same limit the AST scan documents for
    itself, and it costs little here — there is no reason to construct this flag
    dynamically, and ffbin.has_filter is the shorter path anyway.
    """
    root = Path(__file__).resolve().parents[1]
    files = sorted(root.rglob("*.py"))
    # A glob that matched nothing would make the assertion below pass vacuously —
    # the same trap tests/lib/test_landmine_scan.py guards with its own positive
    # control. Deriving the root from __file__ rather than a CWD-relative
    # Path("tests") is half of that: pytest invoked from elsewhere would sweep an
    # empty tree and report success.
    assert len(files) > 20, f"the sweep matched nothing under {root}"
    guilty = [f"{p.relative_to(root.parent)}:{i}"
              for p in files
              for i, line in enumerate(p.read_text().splitlines(), 1)
              if any(q + _PROBE_FLAG in line for q in _QUOTES)]
    assert guilty == [], (
        f"ask ffbin.has_filter instead of probing ffmpeg directly: {guilty}")


# Task 3b (design 2026-07-20-ffmpeg-baseline §"the integration suite runs the
# same binary production does"): the sibling of the check above, one layer
# down. That one bans the PROBE FLAG anywhere under tests/; this bans the bare
# BINARY NAME, but only under tests/integration/ — the fixture-building and
# codec/duration-reading argv that would otherwise run PATH's slim ffmpeg
# alongside a production that has moved to ffmpeg-full.
#
# tests/lib/ is deliberately OUT of the swept root, not merely skipped — the
# narrower root does the exempting by construction:
#   - test_lint.py's REAL_SITES fixtures are PRINTED OUTPUT from the real
#     builders; the literals ARE the test data, and resolving them would
#     destroy the fixture.
#   - test_proc.py tests the wrapper's timeout/error handling, not the
#     pipeline; several of its commands are deliberately fake ("a.mp4") and
#     never execute.
#
# EQUALITY on ast.Constant string values, not the substring/quote scan the
# flag check above uses. The probe flag is asymmetric enough that no other
# token in this codebase ends the same way, but "ffmpeg" is an ordinary word
# this very suite says constantly in prose ("ffmpeg not installed", a
# docstring explaining a skip guard, an error message) — a substring-plus-
# quote scan would flag every one of them. No skip reason or docstring is
# ever exactly "ffmpeg" or "ffprobe" and nothing longer, so comparing whole
# string-literal values for equality sidesteps the false positives without
# needing the docstring-subtraction tests/lib/test_landmine_scan.py's own
# literal scan uses for its substring form.
_BANNED_BARE_BINARIES = ("ffmpeg", "ffprobe")


def test_no_integration_test_names_a_binary_instead_of_resolving_it():
    """Post-install, ffmpeg-full never reaches PATH (design §3) — so a bare
    "ffmpeg"/"ffprobe" argv[0] anywhere under tests/integration/ builds a
    fixture or reads a codec with the SLIM PATH binary while production runs
    the full one. Nothing goes silently uncovered (none of this is a filter
    capability probe — that trap is test_no_test_runs_its_own_filter_probe's),
    but it does mean the golden fixtures and the pipeline that processes them
    were never proven against the SAME binary, which is exactly what design
    §2's "same version, same revision" argument needs to be checking.
    """
    root = Path(__file__).resolve().parents[1] / "integration"
    files = sorted(root.rglob("*.py"))
    assert len(files) > 10, f"the sweep matched nothing under {root}"
    guilty = [f"{p.relative_to(root.parent.parent)}:{node.lineno}"
              for p in files
              for node in ast.walk(ast.parse(p.read_text()))
              if isinstance(node, ast.Constant) and isinstance(node.value, str)
              and node.value in _BANNED_BARE_BINARIES]
    assert guilty == [], (
        f"use ffbin.ffmpeg()/ffbin.ffprobe() instead of a bare literal: {guilty}")
