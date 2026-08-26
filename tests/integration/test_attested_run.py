"""The provenance chain against real pixels (design docs/specs/2026-08-04-attested-run-design.md).

Fixtures prove the pieces; this proves the CHAIN: a master that check_reel actually
measured, delivered through the real encode, produces an attestation that verifies —
and stops verifying the moment the shipped file changes."""
import pytest

from scripts import check_reel, deliver, montage
from scripts.lib import assembly, provenance, runlayout
from scripts.lib.models import REEL_H264, ReelCheckSpec

from .test_reel_backhalf import _episode


def _synth_clip(tmp_path, sample_clip, i):
    """Two crops of the shared `sample_clip` at the SAME x-offsets
    `test_backhalf_assembles_checks_and_delivers` already proves pass every
    mechanical gate: the moving box lands at a different in-frame position at
    each episode's midpoint (distinct phash -> `variety` passes) while both
    cut-boundary frames show pure background (equal mean -> `color_across_cuts`
    passes). Reuses `_episode` verbatim rather than a second clip synthesizer."""
    x_const = 645 if i == 0 else 1045
    return _episode(sample_clip, tmp_path, x_const, f"ep{i}")


def _total(eps: list[str]) -> float:
    return sum(check_reel._probe_dur(e) for e in eps)


def _assemble(tmp_path, sample_clip):
    eps = [_synth_clip(tmp_path, sample_clip, i) for i in range(2)]
    dims = (assembly.probe_stream(eps[0]).w, assembly.probe_stream(eps[0]).h)
    fps = assembly.probe_stream(eps[0]).fps
    master = str(tmp_path / "master.mp4")
    assembly.assemble(eps, dims, fps, master)
    return eps, dims, fps, master


@pytest.mark.integration
def test_the_chain_holds_end_to_end(tmp_path, sample_clip):
    eps, dims, fps, master = _assemble(tmp_path, sample_clip)
    spec = ReelCheckSpec(target_dur=_total(eps))
    rep = check_reel.run(master, eps, spec, str(tmp_path / "report.json"))
    assert rep.overall is True
    assert rep.master_digest == provenance.digest_file(master)

    run = tmp_path / "run"
    lay = runlayout.RunLayout(run)
    deliver.deliver(master, REEL_H264, str(lay.deliveries), "golden first cut", rep,
                    scratch_dir=str(lay.build),
                    run_provenance={"engine_at_start": provenance.engine_stamp(),
                                    "edl": {"digest": "", "state": "unstamped"},
                                    "overrides": []})
    assert montage.verify(str(run))["deliveries"][0]["state"] == "attested"


@pytest.mark.integration
def test_a_hand_assembled_master_cannot_be_delivered(tmp_path, sample_clip):
    # #13, against real pixels: assemble a DIFFERENT master by hand after the check
    eps, dims, fps, master = _assemble(tmp_path, sample_clip)
    rep = check_reel.run(master, eps, ReelCheckSpec(target_dur=_total(eps)),
                         str(tmp_path / "report.json"))
    assembly.assemble(list(reversed(eps)), dims, fps, master)   # re-made after the check
    with pytest.raises(RuntimeError, match="different file"):
        deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "x", rep,
                        scratch_dir=str(tmp_path / "scratch"))


@pytest.mark.integration
def test_a_reel_swapped_after_delivery_stops_verifying(tmp_path, sample_clip):
    eps, dims, fps, master = _assemble(tmp_path, sample_clip)
    rep = check_reel.run(master, eps, ReelCheckSpec(target_dur=_total(eps)),
                         str(tmp_path / "report.json"))
    run = tmp_path / "run"
    lay = runlayout.RunLayout(run)
    out = deliver.deliver(master, REEL_H264, str(lay.deliveries), "x", rep,
                          scratch_dir=str(lay.build))

    with open(out, "ab") as f:
        f.write(b"\x00")                 # the reel changed after delivery

    assert montage.verify(str(run))["deliveries"][0]["state"] == "digest-mismatch"
