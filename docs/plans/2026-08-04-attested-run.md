# Attested Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every claim the montage pipeline makes verifiable — no delivered reel
can assert a gate it did not pass, no generated artifact can be edited in place
undetected, and no run can straddle an engine change.

**Architecture:** One new pure-ish module `scripts/lib/provenance.py` owns git and
sha256. Three artifacts gain a `provenance` block (`project.json`, `EDL.json`,
`reel_report.json` via `ReelReport.master_digest`); two consumers refuse a *tampered*
(never a merely *absent*) stamp — `EDL.from_json` and `deliver`. `deliver` writes a
`REEL_v{n}.attest.json` sidecar recording both engine stamps, both digests, the EDL's
state and every loosened threshold; `montage status` reports it and a new
`montage verify` re-hashes it.

**Tech Stack:** Python 3.13, stdlib only (`hashlib`, `json`, `dataclasses`), `git` via
the existing `scripts/lib/proc.run` wrapper, pytest.

**Design:** [docs/specs/2026-08-04-attested-run-design.md](../specs/2026-08-04-attested-run-design.md)

## Global Constraints

- **Refuse **and** record.** A forged artifact is refused outright with no escape
  flag. A legitimate gate loosening stays available but is recorded in the
  attestation. The invariant is "a gate cannot be loosened **silently**", not "a gate
  cannot be loosened".
- **Refusal fires on tampering, never on absence.** A missing `provenance` block is
  legal (a hand-authored `EDL.json` is `edl_to_reel`'s documented SP1 front door). A
  block present but not matching its object is refused. The ONE deliberate exception
  is `ReelReport.master_digest`: `check_reel` is its only producer and always stamps,
  so absence there IS the signal — see Task 3.
- **No `subprocess` import.** `tests/lib/test_landmine_scan.py::test_only_the_documented_sites_reach_subprocess_directly`
  pins the set of modules allowed to import `subprocess`. `provenance.py` shells out
  to git **through `scripts.lib.proc.run`**. Do not widen the allowlist.
- **`engine_stamp()` is best-effort and honest.** Git missing / not a repo / non-zero
  exit → `{"sha": "", "dirty": None}` — recorded as *unknown*, never guessed, and an
  unknown stamp never stops a run.
- **Dirty is measured over `("scripts", "skills", "bin")` only.** A doc edit or an
  untracked scratch file is not an engine change.
- **No timestamp in an artifact's provenance block.** It would make stamped artifacts
  byte-unstable run to run and churn the edit-plan goldens. Time lives only in the
  `Attestation`.
- **Fail loud with a remedy.** Every refusal raises `ValueError`/`RuntimeError` whose
  message names what is wrong AND the exact command that fixes it
  (`docs/coding-standards.md`).
- **Imports at top of file; scripts run as modules** (`pythonpath = .`; run with
  `.venv/bin/python -m scripts.X` or `-m pytest`). Type every signature.
- **Landmines still apply:** `-ss` AFTER `-i`; `lutrgb` banned; never stabilize
  wade-in shots. This slice adds no ffmpeg argv, but the integration test runs real
  ffmpeg through `proc.run`, whose lint guard is always on.
- **Test command:** `.venv/bin/python -m pytest <path> -v`. Full suite:
  `.venv/bin/python -m pytest -q`.
- **Commit style:** conventional commits; body ends with
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
|------|----------------|
| **Create** `scripts/lib/provenance.py` | The only module that shells to git or hashes a file. `engine_stamp` / `digest_file` / `digest_obj` / `stamp` / `check` / `spec_overrides` / `Attestation` / `attest_path` / `verify_delivery`. |
| **Create** `tests/lib/test_provenance.py` | Unit tests for all of the above. |
| **Create** `tests/integration/test_attested_run.py` | Real-ffmpeg proof: assemble → check_reel → deliver → attest verifies; tamper → `digest-mismatch`. |
| Modify `scripts/lib/project.py` | `ProjectConfig.provenance` field, round-tripped. |
| Modify `scripts/lib/edl.py` | `EDL.provenance` field; `EDL.from_json` verification; new `write_edl` chokepoint. |
| Modify `scripts/lib/models.py` | `ReelReport.master_digest`; `ReelManifest.provenance`. |
| Modify `scripts/project_init.py` | Stamp `project.json` at run start. |
| Modify `scripts/edit_plan.py`, `scripts/match_grade.py` | Both EDL writers route through `edl.write_edl`. |
| Modify `scripts/check_reel.py` | `run()` sets `master_digest`. |
| Modify `scripts/deliver.py` | Binding refusals + attestation write + `run_provenance` param. |
| Modify `scripts/build_reel.py` | Thread `rm.provenance` into `deliver`. |
| Modify `scripts/edl_to_reel.py` | Engine-drift stop; assemble the run provenance; `--changelog` (#16). |
| Modify `scripts/montage.py` | `reel-review` required (#15); `deliveries` in `next_action`; `verify` subcommand. |
| Modify skills + docs | #6 question, #8 brief lines, registry/status/backlog/playbook sync. |

---

### Task 0: `scripts/lib/provenance.py` — the module

**Files:**
- Create: `scripts/lib/provenance.py`
- Test: `tests/lib/test_provenance.py`

**Interfaces:**
- Consumes: `scripts.lib.proc.run` (existing).
- Produces (every later task depends on these exact names):
  - `PROV_KEY = "provenance"`, `PROV_V = 1`, `ENGINE_PATHS = ("scripts", "skills", "bin")`
  - `engine_stamp() -> dict` → `{"sha": str, "dirty": bool | None}`
  - `digest_file(path: str | Path) -> str`
  - `canonical(d: dict) -> bytes`
  - `digest_obj(d: dict) -> str`
  - `stamp(d: dict, *, inputs: dict[str, str] | None = None) -> dict`
  - `check(d: dict) -> tuple[str, str]` → state in `("unstamped", "intact", "tampered")`
  - `spec_overrides(spec, *, exempt: tuple[str, ...] = ("target_dur",)) -> list[dict]`
  - `attest_path(reel_path: str | Path) -> Path`
  - `class Attestation` with `to_dict/from_dict/write/from_json`
  - `verify_delivery(reel_path, *, rehash: bool = False) -> dict`

- [ ] **Step 1: Write the failing tests**

`tests/lib/test_provenance.py`:

```python
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.lib import provenance
from scripts.lib.models import ReelCheckSpec


def test_digest_obj_ignores_the_provenance_key_and_key_order():
    a = {"b": 2, "a": 1}
    b = {"a": 1, "b": 2, "provenance": {"anything": "at all"}}
    assert provenance.digest_obj(a) == provenance.digest_obj(b)


def test_digest_obj_sees_a_value_change():
    assert provenance.digest_obj({"a": 1}) != provenance.digest_obj({"a": 2})


def test_stamp_then_check_is_intact():
    d = {"episodes": [1, 2], "cap": 3}
    d["provenance"] = provenance.stamp(d)
    assert provenance.check(d)[0] == "intact"


def test_a_mutated_field_is_tampered_and_the_detail_names_both_digests():
    d = {"episodes": [1, 2], "cap": 3}
    d["provenance"] = provenance.stamp(d)
    d["cap"] = 9
    state, detail = provenance.check(d)
    assert state == "tampered"
    assert "recorded digest" in detail and "hash to" in detail


def test_a_missing_block_is_unstamped_not_tampered():
    assert provenance.check({"cap": 3})[0] == "unstamped"
    assert provenance.check({"cap": 3, "provenance": {}})[0] == "unstamped"


def test_stamp_records_inputs_verbatim(tmp_path):
    src = tmp_path / "selection.json"
    src.write_text('{"episodes": []}')
    block = provenance.stamp({"a": 1}, inputs={"selection": provenance.digest_file(src)})
    assert block["inputs"]["selection"] == provenance.digest_file(src)
    assert block["v"] == provenance.PROV_V


def test_stamp_carries_no_timestamp(tmp_path):
    # a written_at would make every stamped artifact byte-unstable run to run
    assert set(provenance.stamp({"a": 1})) == {"v", "engine", "self", "inputs"}


def test_digest_file_matches_a_known_sha256(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    assert provenance.digest_file(f) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_engine_stamp_on_a_non_repo_is_unknown_and_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(provenance, "_ROOT", tmp_path)     # a dir with no .git
    assert provenance.engine_stamp() == {"sha": "", "dirty": None}


def test_engine_stamp_on_this_repo_reports_a_sha():
    st = provenance.engine_stamp()
    assert isinstance(st["sha"], str) and len(st["sha"]) >= 7
    assert st["dirty"] in (True, False)


def test_spec_overrides_is_empty_for_a_default_spec():
    assert provenance.spec_overrides(ReelCheckSpec(target_dur=10.0)) == []


def test_spec_overrides_names_the_loosened_field():
    spec = ReelCheckSpec(target_dur=10.0, color_delta_max=20.0)
    assert provenance.spec_overrides(spec) == [
        {"field": "color_delta_max", "value": 20.0, "default": 12.0}]


def test_spec_overrides_covers_a_field_the_spec_gains_later():
    # the whole point of a diff over a registry: a threshold added to a spec is
    # covered the day it lands, with no second place to remember.
    @dataclass
    class Later:
        target_dur: float
        brand_new_gate: int = 5

    assert provenance.spec_overrides(Later(target_dur=1.0, brand_new_gate=9)) == [
        {"field": "brand_new_gate", "value": 9, "default": 5}]


def test_attest_path_sits_beside_the_reel():
    assert provenance.attest_path("/o/REEL_v3.mp4").name == "REEL_v3.attest.json"


def _att(**kw):
    base = dict(reel="REEL_v1.mp4", reel_digest="d" * 64, master_digest="m" * 64,
                report_digest="r" * 64, overall=True)
    return provenance.Attestation(**{**base, **kw})


def test_attestation_round_trips_through_json(tmp_path):
    a = _att(engine_at_start={"sha": "aaa", "dirty": False},
             engine_at_deliver={"sha": "aaa", "dirty": False},
             edl={"digest": "e", "state": "intact"},
             overrides=[{"field": "color_delta_max", "value": 20.0, "default": 12.0}],
             delivered_at="2026-08-04T10:00:00")
    p = tmp_path / "REEL_v1.attest.json"
    a.write(p)
    assert provenance.Attestation.from_json(p).to_dict() == a.to_dict()


def test_verify_delivery_without_a_sidecar_is_unattested(tmp_path):
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"hand-made")
    got = provenance.verify_delivery(reel)
    assert got["state"] == "unattested"
    assert "not produced by deliver" in got["detail"]


def test_verify_delivery_reads_state_without_rehashing(tmp_path):
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"one")
    _att(reel_digest=provenance.digest_file(reel)).write(provenance.attest_path(reel))
    reel.write_bytes(b"two")                       # swapped AFTER delivery
    assert provenance.verify_delivery(reel)["state"] == "attested"          # cheap read
    assert provenance.verify_delivery(reel, rehash=True)["state"] == "digest-mismatch"


def test_verify_delivery_flags_a_failed_gate(tmp_path):
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"one")
    _att(overall=False, reel_digest=provenance.digest_file(reel)).write(
        provenance.attest_path(reel))
    assert provenance.verify_delivery(reel, rehash=True)["state"] == "failed-gate"


def test_verify_delivery_engine_drift_flag(tmp_path):
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"one")
    _att(reel_digest=provenance.digest_file(reel),
         engine_at_start={"sha": "aaa", "dirty": False},
         engine_at_deliver={"sha": "bbb", "dirty": False}).write(provenance.attest_path(reel))
    assert provenance.verify_delivery(reel)["engine_drift"] is True


def test_verify_delivery_unknown_stamps_are_not_drift(tmp_path):
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"one")
    _att(reel_digest=provenance.digest_file(reel),
         engine_at_start={"sha": "", "dirty": None},
         engine_at_deliver={"sha": "bbb", "dirty": False}).write(provenance.attest_path(reel))
    assert provenance.verify_delivery(reel)["engine_drift"] is False


def test_verify_delivery_on_corrupt_json_is_unattested(tmp_path):
    reel = tmp_path / "REEL_v1.mp4"
    reel.write_bytes(b"one")
    provenance.attest_path(reel).write_text("{not json")
    got = provenance.verify_delivery(reel)
    assert got["state"] == "unattested" and "unreadable" in got["detail"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_provenance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.lib.provenance'`

- [ ] **Step 3: Write the module**

`scripts/lib/provenance.py`:

```python
"""Run provenance: what produced an artifact, and whether it still matches itself
(design docs/specs/2026-08-04-attested-run-design.md). The ONLY module that shells
out to git or hashes a file, so there is one definition of "the engine" and one
canonical JSON form for the whole pipeline.

Refusal fires on TAMPERING, never on ABSENCE (design §5): an artifact with no
provenance block has a legitimate producer — a hand-authored EDL.json is
edl_to_reel's documented front door — while an artifact whose block no longer
matches its own contents was edited after its tool wrote it. That distinction is
the design, not a leniency."""
import hashlib
import json
from dataclasses import dataclass, field, fields
from pathlib import Path

from scripts.lib import proc

PROV_KEY = "provenance"
PROV_V = 1
# What "the engine changed" is measured over. NOT the whole tree: a doc edit, an
# untracked run artifact or a scratch file is not an engine change, and a dirty bit
# that flips on those would make the edl_to_reel stop fire constantly — a guard
# everyone learns to ignore protects nothing (design §3).
ENGINE_PATHS = ("scripts", "skills", "bin")
_ROOT = Path(__file__).resolve().parents[2]     # scripts/lib/provenance.py -> repo root
_UNKNOWN = {"sha": "", "dirty": None}


def _git(*args: str) -> str | None:
    """git in the repo root, or None when git is absent / this is not a repo / the
    command failed. Through proc.run, never bare subprocess: the AST scan in
    tests/lib/test_landmine_scan.py pins which modules may import subprocess, and
    that choke point is what the whole runtime layer stands on."""
    try:
        r = proc.run(["git", "-C", str(_ROOT), *args], check=False)
    except RuntimeError:                        # git not on PATH — proc.run re-raises
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", errors="replace")


def engine_stamp() -> dict:
    """{"sha": <short HEAD>, "dirty": <bool>}, or {"sha": "", "dirty": None} when git
    cannot answer. Unknown is RECORDED, never guessed — and an unknown stamp cannot
    prove drift, so it never stops a run (design §7)."""
    sha = _git("rev-parse", "--short", "HEAD")
    if sha is None:
        return dict(_UNKNOWN)
    status = _git("status", "--porcelain", "--", *ENGINE_PATHS)
    if status is None:
        return dict(_UNKNOWN)
    return {"sha": sha.strip(), "dirty": bool(status.strip())}


def digest_file(path: str | Path) -> str:
    """Streaming sha256 — a reel master is hundreds of MB and must not be slurped."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(d: dict) -> bytes:
    """One byte-form for a dict, independent of key order and whitespace."""
    return json.dumps(d, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def digest_obj(d: dict) -> str:
    """sha256 of the object WITHOUT its own provenance block, so a block can be
    recomputed over the object that carries it without chasing its own tail."""
    return hashlib.sha256(canonical({k: v for k, v in d.items() if k != PROV_KEY})).hexdigest()


def stamp(d: dict, *, inputs: dict[str, str] | None = None) -> dict:
    """The block to store under d[PROV_KEY]. `inputs` maps a name to the digest of a
    file this artifact was derived from (EDL.json records its selection.json).

    Deliberately carries NO timestamp: a written_at would make every stamped artifact
    byte-unstable between runs and churn the edit-plan goldens for nothing. Time
    lives in Attestation, which has no golden."""
    return {"v": PROV_V, "engine": engine_stamp(), "self": digest_obj(d),
            "inputs": dict(inputs or {})}


def check(d: dict) -> tuple[str, str]:
    """(state, detail) with state in ("unstamped", "intact", "tampered")."""
    block = d.get(PROV_KEY)
    if not isinstance(block, dict) or not block.get("self"):
        return "unstamped", "no provenance block"
    want, got = block["self"], digest_obj(d)
    if want == got:
        return "intact", ""
    return "tampered", (f"recorded digest {want[:12]}… but the contents hash to {got[:12]}…")


def spec_overrides(spec, *, exempt: tuple[str, ...] = ("target_dur",)) -> list[dict]:
    """Every field of `spec` that differs from a default-constructed one of its own
    class — the machine-readable record of a loosened gate (design §6).

    A diff, NOT a registry: a threshold added to ReelCheckSpec later is covered the
    day it lands, with no second place to remember to update. `exempt` must name
    every field the class has no default for (that is how the baseline instance is
    built) plus any field that is legitimately per-reel rather than a loosening —
    target_dur is both."""
    base = type(spec)(**{n: getattr(spec, n) for n in exempt})
    return [{"field": f.name, "value": getattr(spec, f.name), "default": getattr(base, f.name)}
            for f in fields(spec)
            if f.name not in exempt and getattr(spec, f.name) != getattr(base, f.name)]


def attest_path(reel_path: str | Path) -> Path:
    """REEL_v3.mp4 -> REEL_v3.attest.json, beside it."""
    return Path(reel_path).with_suffix(".attest.json")


@dataclass
class Attestation:
    """A delivery's record: what was shipped, which gate it passed, on which engine,
    which EDL it came from, and every gate threshold loosened to let it through.
    Written by deliver beside the encode; read by montage status/verify (design §6)."""
    reel: str
    reel_digest: str
    master_digest: str
    report_digest: str
    overall: bool
    engine_at_start: dict = field(default_factory=dict)
    engine_at_deliver: dict = field(default_factory=dict)
    edl: dict = field(default_factory=dict)
    overrides: list = field(default_factory=list)
    delivered_at: str = ""
    v: int = PROV_V

    def to_dict(self) -> dict:
        return {"v": self.v, "reel": self.reel, "reel_digest": self.reel_digest,
                "master_digest": self.master_digest, "report_digest": self.report_digest,
                "overall": self.overall, "engine_at_start": dict(self.engine_at_start),
                "engine_at_deliver": dict(self.engine_at_deliver), "edl": dict(self.edl),
                "overrides": list(self.overrides), "delivered_at": self.delivered_at}

    @classmethod
    def from_dict(cls, d: dict) -> "Attestation":
        if not isinstance(d, dict):
            raise ValueError(f"Attestation.from_dict: expected an attestation object, got "
                             f"{type(d).__name__} — the sidecar is corrupt; re-deliver the reel")
        return cls(reel=d.get("reel", ""), reel_digest=d.get("reel_digest", ""),
                   master_digest=d.get("master_digest", ""),
                   report_digest=d.get("report_digest", ""), overall=bool(d.get("overall")),
                   engine_at_start=d.get("engine_at_start") or {},
                   engine_at_deliver=d.get("engine_at_deliver") or {},
                   edl=d.get("edl") or {}, overrides=d.get("overrides") or [],
                   delivered_at=d.get("delivered_at", ""), v=d.get("v", PROV_V))

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def from_json(cls, path: str | Path) -> "Attestation":
        try:
            return cls.from_dict(json.loads(Path(path).read_text()))
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON ({e}) — the attestation sidecar is "
                             f"corrupt; re-deliver the reel") from e


def verify_delivery(reel_path: str | Path, *, rehash: bool = False) -> dict:
    """One delivered file's state. rehash=False (montage status, called constantly)
    reads the sidecar only; rehash=True (montage verify, run once at CP3) re-hashes
    the shipped file to prove it is the one that was delivered."""
    p = Path(reel_path)
    out: dict = {"file": p.name, "state": "unattested", "overall": None, "overrides": [],
                 "engine_drift": False,
                 "detail": "no attestation sidecar — this file was not produced by deliver()"}
    ap = attest_path(p)
    if not ap.exists():
        return out
    try:
        att = Attestation.from_json(ap)
    except ValueError as e:
        out["detail"] = f"attestation unreadable ({e})"
        return out
    a, b = att.engine_at_start, att.engine_at_deliver
    out.update(overall=att.overall, overrides=list(att.overrides),
               engine_drift=bool(a.get("sha") and b.get("sha") and a != b), detail="")
    if not att.overall:
        return {**out, "state": "failed-gate",
                "detail": "the attestation records a reel that did not pass check_reel"}
    if rehash:
        actual = digest_file(p)
        if actual != att.reel_digest:
            return {**out, "state": "digest-mismatch",
                    "detail": (f"the shipped file hashes to {actual[:12]}… but the attestation "
                               f"records {att.reel_digest[:12]}… — it was replaced after delivery")}
    return {**out, "state": "attested"}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_provenance.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Prove the subprocess allowlist still holds**

Run: `.venv/bin/python -m pytest tests/lib/test_landmine_scan.py -v`
Expected: PASS — in particular
`test_only_the_documented_sites_reach_subprocess_directly`. If it FAILS naming
`provenance.py`, the module imported `subprocess` directly: route the git call
through `proc.run` instead of widening the allowlist.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/provenance.py tests/lib/test_provenance.py
git commit -m "feat(provenance): engine stamp, object digests, spec-override diff, attestation"
```

---

### Task 1: the four contract fields

**Files:**
- Modify: `scripts/lib/project.py` (`ProjectConfig`)
- Modify: `scripts/lib/edl.py` (`EDL`)
- Modify: `scripts/lib/models.py` (`ReelReport`, `ReelManifest`)
- Test: `tests/lib/test_project.py`, `tests/lib/test_edl.py`, `tests/lib/test_models.py`

**Interfaces:**
- Consumes: `provenance.PROV_KEY` (Task 0).
- Produces: `ProjectConfig.provenance: dict`, `EDL.provenance: dict`,
  `ReelReport.master_digest: str`, `ReelManifest.provenance: dict` — all defaulting
  empty, all round-tripped through `to_dict`/`from_dict`.

**Why all four in one task:** they are the same mechanical change to four
dataclasses and share one review lens (does it round-trip, does it default empty,
does an existing artifact still load). Splitting them would give a reviewer nothing
new to reject.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_project.py`:

```python
def test_project_config_round_trips_a_provenance_block(tmp_path):
    from scripts.lib.project import ProjectConfig
    cfg = ProjectConfig(purpose="reel", canvas=(9, 16), delivery="native",
                        provenance={"v": 1, "self": "abc"})
    p = tmp_path / "project.json"
    cfg.write(p)
    assert ProjectConfig.from_json(p).provenance == {"v": 1, "self": "abc"}


def test_project_config_without_provenance_emits_no_key(tmp_path):
    # an existing project.json must stay byte-comparable: no empty block noise
    from scripts.lib.project import ProjectConfig
    cfg = ProjectConfig(purpose="reel", canvas=(9, 16), delivery="native")
    assert "provenance" not in cfg.to_dict()
    assert cfg.provenance == {}
```

Append to `tests/lib/test_edl.py`:

```python
def test_edl_round_trips_a_provenance_block():
    from scripts.lib.edl import EDL
    e = EDL.from_dict({"episodes": [_ep()], "provenance": {"v": 1, "self": "abc"}})
    assert e.provenance == {"v": 1, "self": "abc"}
    assert e.to_dict()["provenance"] == {"v": 1, "self": "abc"}


def test_edl_without_provenance_emits_no_key():
    from scripts.lib.edl import EDL
    assert "provenance" not in EDL.from_dict({"episodes": [_ep()]}).to_dict()


def test_edl_refuses_a_non_dict_provenance():
    from scripts.lib.edl import EDL
    with pytest.raises(ValueError, match="EDL.provenance"):
        EDL.from_dict({"episodes": [_ep()], "provenance": "nope"})
```

`_ep()` is this file's existing episode-dict helper — reuse whatever it already
uses to build a minimal valid episode dict; do not invent a new one.

Append to `tests/lib/test_models.py`:

```python
def test_reel_report_round_trips_master_digest():
    from scripts.lib.models import CheckResult, ReelReport
    r = ReelReport(checks={"length": CheckResult("length", True, {})}, master_digest="a" * 64)
    assert r.to_dict()["master_digest"] == "a" * 64
    assert ReelReport.from_dict(r.to_dict()).master_digest == "a" * 64


def test_reel_report_defaults_master_digest_to_empty():
    from scripts.lib.models import CheckResult, ReelReport
    assert ReelReport(checks={"length": CheckResult("length", True, {})}).master_digest == ""
```

And, in the same file, one `ReelManifest` test (build it the way the existing
`ReelManifest` tests in this file do — reuse their episode helper):

```python
def test_reel_manifest_carries_a_provenance_dict():
    rm = _manifest()                      # this file's existing helper
    assert rm.provenance == {}
    rm.provenance = {"edl": {"state": "intact"}}
    assert rm.provenance["edl"]["state"] == "intact"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_project.py tests/lib/test_edl.py tests/lib/test_models.py -v`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'provenance'` /
`'master_digest'`.

- [ ] **Step 3: Add the fields**

`scripts/lib/project.py` — add the field, validate it, round-trip it:

```python
@dataclass
class ProjectConfig:
    purpose: str
    canvas: tuple
    delivery: str
    notes: str = ""
    # The run's START stamp (design §4): project_init writes it, edl_to_reel compares
    # against it. Empty = a run started before this existed, or git could not answer —
    # either way no comparison is possible and nothing is inferred.
    provenance: dict = field(default_factory=dict)
```

Add `from dataclasses import dataclass, field` to the imports. In `__post_init__`,
after the delivery check:

```python
        if not isinstance(self.provenance, dict):
            raise ValueError(f"ProjectConfig.provenance must be an object, got "
                             f"{type(self.provenance).__name__} — re-run project-init")
```

In `from_dict`, add `provenance=d.get("provenance") or {}` to the constructor call.
In `to_dict`:

```python
    def to_dict(self) -> dict:
        d = {"purpose": self.purpose, "canvas": list(self.canvas),
             "delivery": self.delivery, "notes": self.notes}
        if self.provenance:                  # omit when empty: an unstamped project.json
            d["provenance"] = dict(self.provenance)   # stays byte-identical to before
        return d
```

`scripts/lib/edl.py` — the same shape on `EDL`:

```python
    target_dur: float | None = None
    provenance: dict = field(default_factory=dict)   # design §4; empty = unstamped
```

In `EDL.__post_init__`, after the `target_dur` check:

```python
        if not isinstance(self.provenance, dict):
            raise ValueError(f"EDL.provenance must be an object, got "
                             f"{type(self.provenance).__name__} — re-run edit_plan build "
                             f"to regenerate EDL.json")
```

In `EDL.from_dict`'s return, add `provenance=d.get(provenance_mod.PROV_KEY) or {}` —
import the module as `from scripts.lib import provenance as provenance_mod` if `edl.py`
does not already have a name free; a plain `from scripts.lib import provenance` is
fine as long as no local variable shadows it. In `EDL.to_dict`:

```python
    def to_dict(self) -> dict:
        d = {"episodes": [e.to_dict() for e in self.episodes],
             "music": self.music, "cast": self.cast, "cap": self.cap,
             "target_dur": self.target_dur}
        if self.provenance:
            d[provenance.PROV_KEY] = dict(self.provenance)
        return d
```

`scripts/lib/models.py` — `ReelReport`:

```python
    wall_s: float = 0.0
    # sha256 of the master this report actually measured (design §4). deliver refuses
    # a report that does not bind to the file being shipped — check_reel is the only
    # producer and always sets it, so an empty value means the report was not written
    # by check_reel.
    master_digest: str = ""
```

`to_dict` gains `"master_digest": self.master_digest`; `from_dict` gains
`master_digest=d.get("master_digest", "")`.

`ReelManifest` — add after `platform`:

```python
    provenance: dict = field(default_factory=dict)   # run-level record threaded to deliver (§6)
```

and in `__post_init__`:

```python
        if not isinstance(self.provenance, dict):
            raise ValueError(f"ReelManifest.provenance must be an object, got "
                             f"{type(self.provenance).__name__}")
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_project.py tests/lib/test_edl.py tests/lib/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Prove nothing downstream broke**

Run: `.venv/bin/python -m pytest tests/lib -q`
Expected: PASS. Every field defaults empty, so existing artifacts and fixtures load
unchanged.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/project.py scripts/lib/edl.py scripts/lib/models.py \
        tests/lib/test_project.py tests/lib/test_edl.py tests/lib/test_models.py
git commit -m "feat(models): provenance fields on ProjectConfig/EDL/ReelManifest + ReelReport.master_digest"
```

---

### Task 2: the producers stamp, and `EDL.from_json` refuses a tampered EDL

**Files:**
- Modify: `scripts/lib/edl.py` (new `write_edl`; verification in `from_json`)
- Modify: `scripts/edit_plan.py:280-283`
- Modify: `scripts/match_grade.py:66`
- Modify: `scripts/project_init.py`
- Modify: `scripts/check_reel.py` (`run`'s `ReelReport(...)` construction)
- Test: `tests/lib/test_edl.py`, `tests/lib/test_edit_plan.py`,
  `tests/lib/test_match_grade.py`, `tests/lib/test_check_reel.py`

**Interfaces:**
- Consumes: Task 0's `stamp`/`check`/`digest_file`, Task 1's fields.
- Produces: `edl.write_edl(edl: EDL, path: str | Path, *, selection: str | Path | None = None) -> None`
  — the ONE place an `EDL.json` is written. `EDL.from_json` now raises `ValueError`
  on a tampered file.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_edl.py`:

```python
def test_write_edl_stamps_and_from_json_reads_it_back_intact(tmp_path):
    from scripts.lib import edl as edl_mod, provenance
    e = edl_mod.EDL.from_dict({"episodes": [_ep()]})
    p = tmp_path / "EDL.json"
    edl_mod.write_edl(e, p)
    assert provenance.check(json.loads(p.read_text()))[0] == "intact"
    assert edl_mod.EDL.from_json(p).provenance["self"]


def test_write_edl_records_the_selection_digest(tmp_path):
    from scripts.lib import edl as edl_mod, provenance
    sel = tmp_path / "selection.json"
    sel.write_text('{"episodes": []}')
    p = tmp_path / "EDL.json"
    edl_mod.write_edl(edl_mod.EDL.from_dict({"episodes": [_ep()]}), p, selection=sel)
    block = json.loads(p.read_text())["provenance"]
    assert block["inputs"]["selection"] == provenance.digest_file(sel)


def test_from_json_refuses_an_edl_edited_after_the_tool_wrote_it(tmp_path):
    from scripts.lib import edl as edl_mod
    p = tmp_path / "EDL.json"
    edl_mod.write_edl(edl_mod.EDL.from_dict({"episodes": [_ep()]}), p)
    d = json.loads(p.read_text())
    d["cap"] = 9                                   # raw-JSON surgery
    p.write_text(json.dumps(d, indent=2))
    with pytest.raises(ValueError, match="selection.json"):
        edl_mod.EDL.from_json(p)


def test_from_json_still_loads_a_hand_authored_unstamped_edl(tmp_path):
    # edl_to_reel's documented SP1 front door: absence is legal, tampering is not
    from scripts.lib import edl as edl_mod
    p = tmp_path / "EDL.json"
    p.write_text(json.dumps({"episodes": [_ep()]}, indent=2))
    assert edl_mod.EDL.from_json(p).provenance == {}


def test_a_rewritten_edl_restamps_rather_than_going_stale(tmp_path):
    from scripts.lib import edl as edl_mod, provenance
    p = tmp_path / "EDL.json"
    e = edl_mod.EDL.from_dict({"episodes": [_ep()]})
    edl_mod.write_edl(e, p)
    e2 = edl_mod.EDL.from_json(p)
    e2.cap = 5                                     # a TOOL changing the EDL
    edl_mod.write_edl(e2, p)
    assert provenance.check(json.loads(p.read_text()))[0] == "intact"
```

Append to `tests/lib/test_check_reel.py` (mock ffmpeg the way this file's existing
tests do — reuse their monkeypatching helper rather than inventing one):

```python
def test_run_stamps_the_master_digest(tmp_path, monkeypatch):
    master = tmp_path / "master.mp4"
    master.write_bytes(b"master-bytes")
    ...                                            # existing stubbing for probes/ffmpeg
    rep = check_reel.run(str(master), [...], spec, str(tmp_path / "r.json"))
    assert rep.master_digest == provenance.digest_file(master)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py tests/lib/test_check_reel.py -v`
Expected: FAIL — `AttributeError: module 'scripts.lib.edl' has no attribute 'write_edl'`
and `assert '' == '<digest>'`.

- [ ] **Step 3: Implement**

`scripts/lib/edl.py` — the writer chokepoint, at module level after the `EDL` class:

```python
def write_edl(edl: EDL, path: str | Path, *, selection: str | Path | None = None) -> None:
    """The ONE place an EDL.json is written. Both authoring tools route through it —
    edit_plan projects a selection, match_grade rewrites the tone pair in place — so
    the stamp cannot drift between them; two writers stamping independently is the
    shape that rots. `selection` is the judgment file this cut was projected from;
    its digest rides in the block so a later reader can tell WHICH selection produced
    this EDL."""
    d = edl.to_dict()
    inputs = {"selection": provenance.digest_file(selection)} if selection is not None else {}
    d[provenance.PROV_KEY] = provenance.stamp(d, inputs=inputs)
    Path(path).write_text(json.dumps(d, indent=2))
```

`EDL.from_json` — verify at the file boundary, so all four readers (`edl_to_reel`,
`draft`, `pacing`, `match_grade`) inherit the refusal from one place:

```python
    @classmethod
    def from_json(cls, path: str | Path) -> "EDL":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON ({e}) — fix the EDL syntax") from e
        # A MISSING block is legal — a hand-authored EDL.json is edl_to_reel's
        # documented front door (extract-spine SP1), and refusing it would delete a
        # designed capability to punish nobody. A block that no longer matches its own
        # contents is something else entirely: the tool's output, edited afterwards.
        if isinstance(d, dict):
            state, detail = provenance.check(d)
            if state == "tampered":
                raise ValueError(
                    f"{path} was edited after edit_plan wrote it ({detail}). Editorial "
                    f"changes belong in selection.json — edit that and re-run "
                    f"`edit_plan build`; raw-JSON surgery bypasses the manifest preflight "
                    f"that catches a window past EOF, a scene-cut straddle, and an "
                    f"unresolved cast pin")
        return cls.from_dict(d)
```

(The `isinstance` guard keeps the existing non-dict error path — `from_dict` already
owns that message.)

`scripts/edit_plan.py` — replace the direct write at `write_edit_plan`:

```python
    edl_path, md_path = Path(out_dir) / "EDL.json", Path(out_dir) / "EDL.md"
    write_edl(edl, edl_path, selection=selection_path)
    md_path.write_text(edl.to_markdown())
```

Import `write_edl` alongside the existing `edl` imports at the top of the file.

`scripts/match_grade.py:66` — replace `Path(edl_path).write_text(json.dumps(out.to_dict(), indent=2))`
with:

```python
    write_edl(out, edl_path)      # re-stamp: match_grade is a legitimate tool, and its
                                  # output is the tool's output (design §4)
```

`scripts/project_init.py` — stamp at run start, just before `cfg.write(out)`:

```python
    # The run's START stamp: edl_to_reel compares the engine against this and refuses a
    # run that straddles an engine change (design §7).
    cfg.provenance = provenance.stamp(cfg.to_dict())
    cfg.write(out)
```

with `from scripts.lib import provenance` at the top.

`scripts/check_reel.py` — in `run`, the `ReelReport(...)` construction near the end:

```python
    rep = ReelReport(checks=checks, fail_reasons=fails, episode_count=len(episodes),
                     wall_s=round(time.monotonic() - t0, 3),
                     master_digest=provenance.digest_file(master))
```

with `provenance` added to the `from scripts.lib import ...` line.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_edl.py tests/lib/test_edit_plan.py tests/lib/test_match_grade.py tests/lib/test_check_reel.py -v`
Expected: PASS.

- [ ] **Step 5: Mutation check — the refusal is load-bearing**

Temporarily change `if state == "tampered":` to `if False:` and re-run
`tests/lib/test_edl.py`. Expected: `test_from_json_refuses_an_edl_edited_after_the_tool_wrote_it`
FAILS. Restore the line. A refusal with no test that goes red when it is removed is
not a refusal.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/edl.py scripts/edit_plan.py scripts/match_grade.py \
        scripts/project_init.py scripts/check_reel.py tests/lib/
git commit -m "feat(provenance): one EDL writer stamps, from_json refuses a tampered EDL, check_reel binds the master"
```

---

### Task 3: `deliver` binds the report to the master, writes the attestation, and stops logging a path (#16)

**Files:**
- Modify: `scripts/deliver.py`
- Test: `tests/lib/test_deliver.py`, `tests/test_deliver.py`,
  `tests/integration/test_reel_backhalf.py`, `tests/integration/test_titles.py`

**Interfaces:**
- Consumes: Task 0's `digest_file`/`digest_obj`/`Attestation`/`attest_path`,
  Task 1's `ReelReport.master_digest`.
- Produces: `deliver.deliver(..., run_provenance: dict | None = None)`; a
  `REEL_v{n}.attest.json` beside every delivered reel.

**Note for the implementer — the test sweep is the bulk of this task.** ~15 existing
call sites hand `deliver` a report built by hand and a master path that does not
exist on disk (`"m.mp4"`). Binding requires reading the master, so those tests must
create a real file and bind the report to it. That is not incidental churn: a test
that "delivers" a master which does not exist was not testing delivery. Add one
helper per test file rather than repeating the two lines.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_deliver.py`:

```python
from scripts.lib import provenance


def _bound(tmp_path, *, passing=True):
    """A master that exists on disk plus a report bound to it — the only shape
    deliver accepts now."""
    master = tmp_path / "m.mp4"
    master.write_bytes(b"master-bytes")
    rep = ReelReport(checks={"length": CheckResult("length", passing, {})}, episode_count=2,
                     master_digest=provenance.digest_file(master))
    return str(master), rep


def _fake_encode(monkeypatch, calls=None):
    """ffmpeg stub that actually PRODUCES its output file — deliver now hashes the
    delivered reel for the attestation, so a stub that writes nothing is not a stub
    of ffmpeg."""
    def run(cmd, *a, **k):
        if calls is not None:
            calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"encoded-reel")
        return SimpleNamespace(stdout=b"")
    monkeypatch.setattr(deliver.proc, "run", run)


def test_deliver_refuses_a_report_with_no_master_digest(tmp_path, monkeypatch):
    _fake_encode(monkeypatch)
    master = tmp_path / "m.mp4"
    master.write_bytes(b"x")
    rep = ReelReport(checks={"length": CheckResult("length", True, {})})   # unbound
    with pytest.raises(RuntimeError, match="did not come from check_reel"):
        deliver.deliver(str(master), REEL_H264, str(tmp_path / "out"), "x", rep)


def test_deliver_refuses_a_report_bound_to_a_different_master(tmp_path, monkeypatch):
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    Path(master).write_bytes(b"hand-assembled-instead")        # the #13 bypass
    with pytest.raises(RuntimeError, match="different file"):
        deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "x", rep)


def test_deliver_writes_an_attestation_beside_the_reel(tmp_path, monkeypatch):
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    out = deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "first cut", rep,
                          run_provenance={"engine_at_start": {"sha": "aaa", "dirty": False},
                                          "edl": {"digest": "e", "state": "intact"},
                                          "overrides": [{"field": "color_delta_max",
                                                         "value": 20.0, "default": 12.0}]})
    att = provenance.Attestation.from_json(provenance.attest_path(out))
    assert att.reel == "REEL_v1.mp4"
    assert att.master_digest == rep.master_digest
    assert att.reel_digest == provenance.digest_file(out)
    assert att.overall is True
    assert att.engine_at_start == {"sha": "aaa", "dirty": False}
    assert att.engine_at_deliver["sha"] == provenance.engine_stamp()["sha"]
    assert att.edl == {"digest": "e", "state": "intact"}
    assert att.overrides == [{"field": "color_delta_max", "value": 20.0, "default": 12.0}]
    assert att.delivered_at                                     # non-empty ISO stamp
    assert provenance.verify_delivery(out, rehash=True)["state"] == "attested"


def test_deliver_attests_without_run_provenance(tmp_path, monkeypatch):
    # build_reel may deliver a manifest that carries none — the sidecar still lands
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    out = deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "x", rep)
    assert provenance.attest_path(out).exists()


def test_the_failed_reel_gate_still_fires_before_any_hashing(tmp_path, monkeypatch):
    # ordering matters: a failed reel must produce no out dir, no file, no hashing —
    # so the overall gate stays FIRST, before the master is even read
    calls = []
    monkeypatch.setattr(deliver.proc, "run", lambda cmd, *a, **k: calls.append(cmd))
    rep = ReelReport(checks={"length": CheckResult("length", False, {})})
    with pytest.raises(RuntimeError, match="does not ship a failed reel"):
        deliver.deliver("does-not-exist.mp4", REEL_H264, str(tmp_path / "out"), "x", rep)
    assert calls == [] and not (tmp_path / "out").exists()
```

Append to `tests/lib/test_deliver.py` the #16 regression test:

```python
def test_the_version_note_is_the_reason_not_a_path(tmp_path, monkeypatch):
    # #16: 12 of 13 entries in a real run's VERSIONS.md logged the path of
    # VERSIONS.md itself as the note. The bug was in the caller (Task 4), but the
    # log must never accept a value that is obviously the log's own path.
    _fake_encode(monkeypatch)
    master, rep = _bound(tmp_path)
    out_dir = tmp_path / "out"
    deliver.deliver(master, REEL_H264, str(out_dir), "regraded ep1", rep)
    text = (out_dir / "VERSIONS.md").read_text()
    assert "regraded ep1" in text
    assert "VERSIONS.md" not in text.split("\n", 2)[-1]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_deliver.py -v`
Expected: FAIL — `TypeError: deliver() got an unexpected keyword argument 'run_provenance'`
and no refusals raised.

- [ ] **Step 3: Implement**

`scripts/deliver.py` — add `from datetime import datetime` (already present) and
`from scripts.lib import ffbin, proc, provenance`. Signature:

```python
def deliver(master: str, profile: ExportProfile, out_dir: str, changelog: str,
            report: ReelReport, *, audio: str | None = None, titles: str | None = None,
            platform: str = "", run_provenance: dict | None = None) -> str:
```

Docstring gains:

> Two bindings guard the gate, in this order. `report.overall` refuses a reel that
> failed; then `report.master_digest` refuses a report that does not describe THIS
> file — an empty digest means the report was not written by `check_reel` (its only
> producer, which always stamps), a mismatched one means the master was re-made after
> the check or assembled outside the pipeline. `run_provenance` carries what only the
> driver knows (the run's start stamp, the EDL's digest and state, the loosened
> thresholds) into the `REEL_v{n}.attest.json` sidecar this writes.

Body — right after the existing `if not report.overall:` raise:

```python
    if not report.master_digest:
        raise RuntimeError(
            "this reel report carries no master digest, so it did not come from "
            "check_reel — nothing binds it to the file being shipped. check_reel is "
            "the only thing that writes a report and it always stamps one. Run "
            "`check_reel` on this master and deliver with the report it writes")
    actual = provenance.digest_file(master)
    if actual != report.master_digest:
        raise RuntimeError(
            f"this reel report describes a different file than the master being shipped "
            f"(report {report.master_digest[:12]}…, master {actual[:12]}…) — the master was "
            f"re-made after the check, or assembled outside the pipeline. Re-run "
            f"`check_reel` on THIS master and deliver with the report it writes")
```

At the end, after `_log_version(out_dir, n, changelog)` and before `return out`:

```python
    # The delivery's record (design §6). reel_digest binds it to the SHIPPED file, not
    # only to the master, so a reel swapped after delivery is detectable. A hand-run
    # ffmpeg produces no sidecar at all, which is what montage status reports.
    rp = run_provenance or {}
    provenance.Attestation(
        reel=Path(out).name, reel_digest=provenance.digest_file(out),
        master_digest=actual, report_digest=provenance.digest_obj(report.to_dict()),
        overall=report.overall,
        engine_at_start=rp.get("engine_at_start") or {},
        engine_at_deliver=provenance.engine_stamp(),
        edl=rp.get("edl") or {}, overrides=rp.get("overrides") or [],
        delivered_at=datetime.now().isoformat(timespec="seconds"),
    ).write(provenance.attest_path(out))
    return out
```

- [ ] **Step 4: Sweep the other call sites**

Update every remaining `deliver.deliver(...)` caller in tests so its master exists
and its report is bound, and every `proc.run` stub so it writes its output file:

- `tests/lib/test_deliver.py` — the pre-existing `_green()`/`_red()` helpers and the
  ~10 tests using them.
- `tests/test_deliver.py` — `_passing_report()` and `_capture()`.
- `tests/integration/test_titles.py` — its deliver call.
- `tests/integration/test_reel_backhalf.py:59,64` — real ffmpeg here, so the master
  already exists; only the report needs binding, and it comes from `check_reel.run`,
  which now stamps it (verify rather than patch).

- [ ] **Step 5: Run to verify everything passes**

Run: `.venv/bin/python -m pytest tests/lib/test_deliver.py tests/test_deliver.py -v`
Then: `.venv/bin/python -m pytest tests/integration/test_titles.py tests/integration/test_reel_backhalf.py -v`
Expected: PASS.

- [ ] **Step 6: Mutation check — both refusals are load-bearing**

Comment out the `if not report.master_digest:` block and re-run
`tests/lib/test_deliver.py`: `test_deliver_refuses_a_report_with_no_master_digest`
must FAIL. Restore it, then comment out the `actual != report.master_digest` block:
`test_deliver_refuses_a_report_bound_to_a_different_master` must FAIL. Restore.

- [ ] **Step 7: Commit**

```bash
git add scripts/deliver.py tests/lib/test_deliver.py tests/test_deliver.py \
        tests/integration/test_titles.py tests/integration/test_reel_backhalf.py
git commit -m "feat(deliver): bind the report to the master, write REEL_v{n}.attest.json"
```

---

### Task 4: `edl_to_reel` — engine-drift stop, run provenance, real changelog

**Files:**
- Modify: `scripts/edl_to_reel.py`
- Modify: `scripts/build_reel.py:87`
- Test: `tests/lib/test_edl_to_reel.py`, `tests/lib/test_build_reel.py`

**Interfaces:**
- Consumes: Task 0's `engine_stamp`/`spec_overrides`, Task 1's
  `ProjectConfig.provenance`/`EDL.provenance`/`ReelManifest.provenance`, Task 3's
  `deliver(..., run_provenance=)`.
- Produces: `edl_to_reel(..., changelog: str = "")`; `rm.provenance` populated;
  `build_reel` passes it through unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_edl_to_reel.py` (reuse this file's existing stubbing of
`preflight`/`extract`/`process_episode`/`build_reel` — do not re-invent it):

```python
def test_a_run_that_straddles_an_engine_change_is_refused(tmp_path, monkeypatch):
    # #11: project.json records the engine at run start; if the code moved since, the
    # stages already finished were produced by different code.
    project = tmp_path / "project.json"
    ProjectConfig(purpose="reel", canvas=(9, 16), delivery="native",
                  provenance={"v": 1, "engine": {"sha": "aaaaaaa", "dirty": False},
                              "self": "x", "inputs": {}}).write(project)
    monkeypatch.setattr(edl_to_reel.provenance, "engine_stamp",
                        lambda: {"sha": "bbbbbbb", "dirty": False})
    with pytest.raises(ValueError, match="must not straddle an engine change"):
        edl_to_reel.edl_to_reel(str(_edl(tmp_path)), str(project), str(tmp_path),
                                str(tmp_path / "w"), str(tmp_path / "o"))


def test_an_unknown_engine_stamp_never_stops_the_run(tmp_path, monkeypatch):
    project = tmp_path / "project.json"
    ProjectConfig(purpose="reel", canvas=(9, 16), delivery="native",
                  provenance={"v": 1, "engine": {"sha": "", "dirty": None},
                              "self": "x", "inputs": {}}).write(project)
    monkeypatch.setattr(edl_to_reel.provenance, "engine_stamp",
                        lambda: {"sha": "bbbbbbb", "dirty": False})
    ...                                    # existing happy-path stubs
    assert edl_to_reel.edl_to_reel(...)["status"] == "delivered"


def test_a_run_started_before_this_existed_never_stops(tmp_path, monkeypatch):
    # project.json with NO provenance block at all — absence, not tampering
    ...


def test_the_run_provenance_reaches_build_reel(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(edl_to_reel.build_reel, "build_reel",
                        lambda rm, o, w, titles=None: seen.setdefault("rm", rm) and None
                        or {"status": "delivered"})
    ...                                    # existing stubs; EDL written via edl.write_edl
    edl_to_reel.edl_to_reel(..., color_delta_max=20.0)
    prov = seen["rm"].provenance
    assert prov["edl"]["state"] == "intact"
    assert prov["overrides"] == [{"field": "color_delta_max", "value": 20.0, "default": 12.0}]
    assert prov["engine_at_start"] == {"sha": "aaaaaaa", "dirty": False}


def test_an_unstamped_edl_is_recorded_as_unstamped(tmp_path, monkeypatch):
    # the hand-authored SP1 front door still works, and says so on the record
    ...
    assert seen["rm"].provenance["edl"] == {"digest": "", "state": "unstamped"}


def test_the_changelog_is_a_reason_not_the_log_path(tmp_path, monkeypatch):
    # #16 root cause: edl_to_reel passed str(out_dir/"VERSIONS.md") as the NOTE
    ...
    assert seen["rm"].changelog == "delivered from EDL.json"
    assert "VERSIONS.md" not in seen["rm"].changelog


def test_an_explicit_changelog_wins(tmp_path, monkeypatch):
    ...
    edl_to_reel.edl_to_reel(..., changelog="regraded ep1")
    assert seen["rm"].changelog == "regraded ep1"
```

Append to `tests/lib/test_build_reel.py`:

```python
def test_build_reel_threads_the_manifest_provenance_into_deliver(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(build_reel.deliver, "deliver",
                        lambda *a, **k: seen.update(k) or "out/REEL_v1.mp4")
    ...                                    # this file's existing green-path stubs
    rm = _manifest(provenance={"edl": {"state": "intact"}})
    build_reel.build_reel(rm, str(tmp_path / "o"), str(tmp_path / "w"))
    assert seen["run_provenance"] == {"edl": {"state": "intact"}}
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_edl_to_reel.py tests/lib/test_build_reel.py -v`
Expected: FAIL — no drift check, `rm.provenance == {}`, `changelog` is a path.

- [ ] **Step 3: Implement `edl_to_reel`**

Add `provenance` to `from scripts.lib import ...`. Signature gains `changelog`:

```python
def edl_to_reel(edl_path: str, project_path: str, footage_root: str,
                work_dir: str, out_dir: str, *, music: str | None = None,
                titles: str | None = None, jobs: int = DEFAULT_JOBS,
                color_delta_max: float | None = None, changelog: str = "") -> dict:
```

Right after `cfg = ProjectConfig.from_json(project_path)`:

```python
    # #11 — a montage run must not straddle an engine change. project.json records the
    # engine at run START; if the code has moved since, the stages already finished were
    # produced by different code and this reel would be a chimera of two engines. An
    # UNKNOWN stamp on either side cannot prove drift and never stops the run (design §7);
    # neither does an absent one, which is a run started before this existed.
    started = cfg.provenance.get("engine") or {}
    now = provenance.engine_stamp()
    if started.get("sha") and now.get("sha") and started != now:
        raise ValueError(
            f"the engine changed since this run started (project.json records "
            f"{started['sha']} {'dirty' if started.get('dirty') else 'clean'}, now "
            f"{now['sha']} {'dirty' if now.get('dirty') else 'clean'}) — a montage run must "
            f"not straddle an engine change, because the stages already finished were "
            f"produced by different code. Start a fresh run dir, or re-run project_init "
            f"against the current engine to re-baseline")
```

At the manifest construction (step 4 in the file), replace the `changelog=` argument
and populate `rm.provenance`:

```python
    target = edl.target_dur if edl.target_dur is not None else sum(ep.dur for ep in edl.episodes)
    extra = {} if color_delta_max is None else {"color_delta_max": color_delta_max}
    # #16: this argument is the version-log NOTE, not the log's path. Passing
    # str(out_dir/"VERSIONS.md") here is what made 12 of 13 entries in a real run's
    # VERSIONS.md log the file's own path instead of the reason for the version.
    note = changelog or f"delivered from {Path(edl_path).name}"
    rm = ReelManifest(episodes=episodes, target_dur=target, cap=edl.cap,
                      changelog=note, music=music or edl.music, **extra)
    # The run's record, assembled where all three parts are in hand (design §6). The
    # override list is a DIFF of the effective check spec against a default one, so a
    # threshold added to ReelCheckSpec later is covered without touching this line.
    rm.provenance = {"edl": {"digest": edl.provenance.get("self", ""),
                             "state": "intact" if edl.provenance else "unstamped"},
                     "engine_at_start": started,
                     "overrides": provenance.spec_overrides(rm.check_spec)}
    return build_reel.build_reel(rm, out_dir, str(Path(work_dir) / "reel"), titles=titles)
```

CLI: add

```python
    ap.add_argument("--changelog", default="",
                    help="version-log note for this delivery — the REASON for the version "
                         "(e.g. 'regraded ep1'), not a path; defaults to 'delivered from <EDL>'")
```

and pass `changelog=a.changelog` in the `edl_to_reel(...)` call.

- [ ] **Step 4: Implement `build_reel` threading**

`scripts/build_reel.py:87`:

```python
            out = deliver.deliver(master, REEL_H264, out_dir, rm.changelog, report,
                                  audio=audio, titles=titles, platform=rm.platform,
                                  run_provenance=rm.provenance)
```

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_edl_to_reel.py tests/lib/test_build_reel.py -v`
Expected: PASS.

- [ ] **Step 6: Mutation check — the drift stop is load-bearing**

Change `if started.get("sha") and now.get("sha") and started != now:` to
`if False:` and re-run `tests/lib/test_edl_to_reel.py`:
`test_a_run_that_straddles_an_engine_change_is_refused` must FAIL. Restore.

- [ ] **Step 7: Commit**

```bash
git add scripts/edl_to_reel.py scripts/build_reel.py tests/lib/test_edl_to_reel.py \
        tests/lib/test_build_reel.py
git commit -m "feat(edl_to_reel): refuse a run that straddles an engine change; carry run provenance; fix the VERSIONS.md note"
```

---

### Task 5: the router — `reel-review` required, deliveries reported, `montage verify`

**Files:**
- Modify: `scripts/montage.py`
- Test: `tests/lib/test_montage.py`

**Interfaces:**
- Consumes: Task 0's `verify_delivery`.
- Produces: `next_action(...)["deliveries"]`; `montage verify --run-dir <d> [--out-dir <d>]`;
  `V1_STAGES`'s `reel-review` entry is `kind="required"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_montage.py`:

```python
def test_reel_review_is_next_after_delivery(tmp_path):
    # #15: CP3 must not be free. Every required artifact present except REVIEW.json.
    run = tmp_path / "run"
    out = run / "out"
    out.mkdir(parents=True)
    for name in ("project.json", "FOOTAGE.json", "EDL.json"):
        (run / name).write_text("{}")
    (out / "REEL_v1.mp4").write_text("x")
    got = montage.next_action(str(run))
    assert got["delivered"] is True
    assert got["next"] == "reel-review"


def test_a_run_is_only_finished_when_the_review_exists(tmp_path):
    run = tmp_path / "run"
    out = run / "out"
    out.mkdir(parents=True)
    for name in ("project.json", "FOOTAGE.json", "EDL.json", "REVIEW.json"):
        (run / name).write_text("{}")
    (out / "REEL_v1.mp4").write_text("x")
    assert montage.next_action(str(run))["next"] is None


def test_status_reports_an_unattested_delivery(tmp_path):
    run = tmp_path / "run"
    out = run / "out"
    out.mkdir(parents=True)
    (out / "REEL_v1.mp4").write_bytes(b"hand-concatenated")
    got = montage.next_action(str(run))["deliveries"]
    assert got == [{"file": "REEL_v1.mp4", "state": "unattested", "overall": None,
                    "overrides": [], "engine_drift": False,
                    "detail": "no attestation sidecar — this file was not produced by deliver()"}]


def test_status_does_not_list_the_sidecar_as_a_delivery(tmp_path):
    run = tmp_path / "run"
    out = run / "out"
    out.mkdir(parents=True)
    (out / "REEL_v1.mp4").write_bytes(b"x")
    (out / "REEL_v1.attest.json").write_text("{}")
    assert [d["file"] for d in montage.next_action(str(run))["deliveries"]] == ["REEL_v1.mp4"]


def test_verify_rehashes_and_catches_a_swapped_reel(tmp_path):
    from scripts.lib import provenance
    run = tmp_path / "run"
    out = run / "out"
    out.mkdir(parents=True)
    reel = out / "REEL_v1.mp4"
    reel.write_bytes(b"delivered")
    provenance.Attestation(reel="REEL_v1.mp4", reel_digest=provenance.digest_file(reel),
                           master_digest="m" * 64, report_digest="r" * 64,
                           overall=True).write(provenance.attest_path(reel))
    assert montage.verify(str(run))["deliveries"][0]["state"] == "attested"
    reel.write_bytes(b"swapped after delivery")
    assert montage.verify(str(run))["deliveries"][0]["state"] == "digest-mismatch"
```

Also update this file's existing whole-object assertions on the stage table and on
`next_action`'s return shape: `reel-review` is now `"required"`, and every
`next_action` result carries a `deliveries` key.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -v`
Expected: FAIL — `next` is `None` after delivery; `KeyError: 'deliveries'`;
`AttributeError: module 'scripts.montage' has no attribute 'verify'`.

- [ ] **Step 3: Implement**

`scripts/montage.py` — add `from scripts.lib import provenance`. Flip the stage:

```python
    Stage("reel-review", "REVIEW.json", "required",
          "reel-review SKILL -> reel_review build CLI (editorial CP3 review)", "final"),
```

Its docstring/comment gains: *required, not optional (design §8): the reviewer stage
was skipped outright on the 2026-08-03 run because `next` never pointed at it, and a
gate that costs nothing to skip is not a gate.*

Add the delivery scan and the `verify` entry point:

```python
def _deliveries(out: Path, *, rehash: bool = False) -> list[dict]:
    """One entry per delivered reel with its attestation state (design §6). The
    sidecars share the REEL_v* prefix, so they are filtered out by suffix — listing
    REEL_v1.attest.json as a delivery would double every reel."""
    return [provenance.verify_delivery(p, rehash=rehash)
            for p in sorted(out.glob("REEL_v*")) if p.suffix != ".json"]
```

In `next_action`, before the return, and in the returned dict:

```python
    return {"stages": stages, "next": next_key, "delivered": delivered,
            "deliveries": _deliveries(out)}
```

`next_action`'s docstring gains: *`deliveries` reports each delivered file's
attestation state from the sidecar alone — cheap, because the router calls status
constantly. `verify()` re-hashes.*

```python
def verify(run_dir: str, out_dir: str | None = None) -> dict:
    """Re-hash every delivered reel against its attestation (design §6). Run once at
    CP3, where the cost is irrelevant and the answer matters: status answers "is there
    a record", verify answers "is this file the one the record describes"."""
    out = Path(out_dir) if out_dir is not None else Path(run_dir) / "out"
    return {"deliveries": _deliveries(out, rehash=True)}
```

CLI — add the subparser beside `status`:

```python
    v = sub.add_parser("verify",
                       help="re-hash delivered reels against their attestations (CP3)")
    v.add_argument("--run-dir", required=True)
    v.add_argument("--out-dir", default=None, help="delivery dir (default <run-dir>/out)")
```

and dispatch on `a.cmd`:

```python
    result = next_action(a.run_dir, a.out_dir) if a.cmd == "status" else verify(a.run_dir, a.out_dir)
    print(json.dumps(result, indent=2))
    raise SystemExit(0)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/lib/test_montage.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/montage.py tests/lib/test_montage.py
git commit -m "feat(montage): reel-review becomes required; report delivery attestations; add verify"
```

---

### Task 6: the real-ffmpeg proof + wip-branch triage

**Files:**
- Create: `tests/integration/test_attested_run.py`
- (git) delete branches `wip/montage-run-hardening`, `wip/montage-run-patches`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing new — this is the end-to-end proof that the chain holds against
  real pixels, not only fixtures.

- [ ] **Step 1: Write the integration test**

`tests/integration/test_attested_run.py` — follow the conventions in
`tests/integration/test_reel_backhalf.py` (real ffmpeg through `proc.run`, synthesized
sources, the existing marker/fixture set; reuse its clip-synthesis helper rather than
writing a new one):

```python
"""The provenance chain against real pixels (design docs/specs/2026-08-04-attested-run-design.md).

Fixtures prove the pieces; this proves the CHAIN: a master that check_reel actually
measured, delivered through the real encode, produces an attestation that verifies —
and stops verifying the moment the shipped file changes."""
import json

import pytest

from scripts import check_reel, deliver, montage
from scripts.lib import assembly, provenance
from scripts.lib.models import REEL_H264, ReelCheckSpec


@pytest.mark.integration
def test_the_chain_holds_end_to_end(tmp_path):
    eps = [_synth_clip(tmp_path, i) for i in range(2)]      # reuse test_reel_backhalf's helper
    master = str(tmp_path / "master.mp4")
    assembly.assemble(eps, (128, 224), 24.0, master)
    spec = ReelCheckSpec(target_dur=_total(eps))
    rep = check_reel.run(master, eps, spec, str(tmp_path / "report.json"))
    assert rep.overall is True
    assert rep.master_digest == provenance.digest_file(master)

    out_dir = tmp_path / "out"
    out = deliver.deliver(master, REEL_H264, str(out_dir), "golden first cut", rep,
                          run_provenance={"engine_at_start": provenance.engine_stamp(),
                                          "edl": {"digest": "", "state": "unstamped"},
                                          "overrides": []})
    assert montage.verify(str(tmp_path), str(out_dir))["deliveries"][0]["state"] == "attested"


@pytest.mark.integration
def test_a_hand_assembled_master_cannot_be_delivered(tmp_path):
    # #13, against real pixels: assemble a DIFFERENT master by hand after the check
    eps = [_synth_clip(tmp_path, i) for i in range(2)]
    master = str(tmp_path / "master.mp4")
    assembly.assemble(eps, (128, 224), 24.0, master)
    rep = check_reel.run(master, eps, ReelCheckSpec(target_dur=_total(eps)),
                         str(tmp_path / "report.json"))
    assembly.assemble(list(reversed(eps)), (128, 224), 24.0, master)   # re-made after the check
    with pytest.raises(RuntimeError, match="different file"):
        deliver.deliver(master, REEL_H264, str(tmp_path / "out"), "x", rep)


@pytest.mark.integration
def test_a_reel_swapped_after_delivery_stops_verifying(tmp_path):
    ...                                    # deliver as above, then append a byte to the
                                           # delivered REEL_v1.mp4
    assert montage.verify(...)["deliveries"][0]["state"] == "digest-mismatch"
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/integration/test_attested_run.py -v`
Expected: PASS (3 tests, real ffmpeg).

- [ ] **Step 3: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. The only acceptable skips are the environmental ones this repo
already has (demucs absent, iTunes network, weights-gated `test_reid`). **A new skip
is a failure** — report it rather than accepting it.

- [ ] **Step 4: Triage the parked wip branches**

Confirm both are superseded before deleting, and record the SHAs (they are already in
the design doc §9 and stay reachable through `git reflog`):

```bash
git log --oneline main..wip/montage-run-hardening
git log --oneline main..wip/montage-run-patches
git branch -D wip/montage-run-hardening wip/montage-run-patches
git branch
```

Expected: `git branch` lists only `main` and this slice's feature branch.
`wip/montage-run-hardening` (`4841dd3`) was fully ported in the track-stitch,
path-quality and titles-animations slices; `wip/montage-run-patches` (`fbcd052`) is
superseded — its diff against `main` is now mostly the removal of work `main` has
since landed. If either check shows unported work, STOP and report it instead of
deleting.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_attested_run.py
git commit -m "test(provenance): real-ffmpeg proof that the attestation chain holds and breaks correctly"
```

---

### Task 7: docs + skills sync

**Files:**
- Modify: `CLAUDE.md` (two registry rows)
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`
- Modify: `docs/fixes-backlog.md` (#6, #8, #11, #13, #15, #16, #20 → landed)
- Modify: `docs/cinematic-quality-playbook.md` (§4 priority 2 landed)
- Modify: `skills/using-montage/SKILL.md`, `skills/process-episode/SKILL.md`,
  `skills/edit-plan/SKILL.md`

- [ ] **Step 1: `CLAUDE.md` — add two registry rows** after the hero re-ID rows,
  in the established one-row-per-doc style:

```markdown
| Attested-run design | [2026-08-04-attested-run-design.md](docs/specs/2026-08-04-attested-run-design.md) | Governance (backlog #8/#11/#13/#15/#20): a `provenance` block on `project.json`/`EDL.json` + `ReelReport.master_digest`, refused on **tampering, never on absence** (a hand-authored EDL stays `edl_to_reel`'s SP1 front door); `deliver` binds the report to the master and writes `REEL_v{n}.attest.json`; `edl_to_reel` refuses a run that straddles an engine change; `reel-review` becomes required. Overrides are a **diff** of the effective check spec vs the default — no registry to forget. §11 is the honest half: an agent with a shell still bypasses everything, so the invariant is *no silent bypass*, not *no bypass*. |
| Attested-run plan | [2026-08-04-attested-run.md](docs/plans/2026-08-04-attested-run.md) | Tasks 0–7: `lib/provenance.py`, the four contract fields, the `write_edl` chokepoint + `from_json` refusal, `deliver`'s binding + attestation (+ the #16 `VERSIONS.md` note fix), `edl_to_reel`'s drift stop + run provenance, `montage` required-review/`deliveries`/`verify`, the real-ffmpeg chain proof + wip triage, docs sync. |
```

- [ ] **Step 2: `docs/build-status.md`** — add a Done entry naming what landed and
  the honest limits (§11's remaining bypasses), in this file's existing format.

- [ ] **Step 3: `docs/fixes-backlog.md`** — flip #8, #11, #13, #15, #20, #6 and #16
  to `✅ LANDED 2026-08-04` with a one-paragraph summary each and a pointer to the
  spec. In #11, retire the current-state alert: the tree is clean, the parked branches
  are deleted, their SHAs recorded in the design's §9. Leave #3, #12, #14, #19 alone —
  they are the editorial half, playbook priority 3.

- [ ] **Step 4: `docs/cinematic-quality-playbook.md`** — mark §4 item 2 (governance
  hardening) landed with the date and the plan link, the way item 1 (hero re-ID) is
  already marked.

- [ ] **Step 5: `skills/using-montage/SKILL.md`** — three edits:

  1. **Step 11 / CP3**: the run is not finished until `montage status` reports
     `next: null`. `reel-review` is now a **required** stage; running
     `"$VG" scripts.montage verify --run-dir <run>` at CP3 and presenting its result
     alongside the reel is part of the checkpoint. An `unattested` delivery means the
     reel did not come out of `deliver` — say so plainly rather than presenting it as
     final.
  2. **Step 5 / CP2 (#6)**: after showing `EDL.md`, ask explicitly — *"titles?
     effects (slow-mo / speed ramp, transitions, SFX)?"* — and name what is skipped
     when the answer is no. CP2 is the right place: the EDL exists, so the reel length
     is known and a title can actually be timed.
  3. **Boundaries (#8)**: add — *You may not disable, lower, or downgrade any quality
     gate. A gate that blocks is routed back to its stage's skill, never loosened to
     pass. `--color-delta-max` exists for a reel that deliberately cuts between scenes
     of different exposure, with the measured delta in hand — never to silence a grade
     that is genuinely wrong, and every use of it is recorded in the delivery's
     attestation and shown at CP3.* Also fix the stale closing line that says the
     cap-3 parallel fan-out is "not built here" — it landed 2026-07-18.

- [ ] **Step 6: `skills/process-episode/SKILL.md` and `skills/edit-plan/SKILL.md`** —
  add the same gate line, plus for `edit-plan`: *never hand-edit `EDL.json`; it is
  stamped, and `edl_to_reel` refuses a stamped EDL whose contents no longer match.
  Editorial changes go in `selection.json` and re-run the build.*

- [ ] **Step 7: `docs/pipeline-map.md`** — reflect that `reel-review` is a required
  stage and that `deliver` now emits an attestation sidecar.

- [ ] **Step 8: Full suite + commit**

```bash
.venv/bin/python -m pytest -q
git add CLAUDE.md docs/ skills/
git commit -m "docs: attested-run registry rows, backlog/playbook sync, gate rules in the skill briefs"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §3 module boundary | 0 |
| §4 three stamp points | 1 (fields), 2 (writers) |
| §5.1 EDL refusal + absence rule | 2 |
| §5.2 deliver binding + the deliberate exception | 3 |
| §6 attestation, overrides diff, status/verify | 0 (`Attestation`/`verify_delivery`), 3 (write), 4 (assemble), 5 (report) |
| §7 engine freeze | 4 |
| §8 CP3 required | 5 |
| §9 riders (#6, #16, wip) | 4 (#16 caller), 3 (#16 regression test), 6 (wip), 7 (#6 + gate lines) |
| §10 testing | 0, 2, 3, 4, 5, 6 |
| §11 honest limits | 7 (docs record them) |

**Placeholder scan:** the `...` markers in Tasks 4 and 6 stand for *existing*
stubbing/helpers in those test files, and each is named explicitly ("reuse this
file's existing X"). They are pointers to real code, not deferred decisions. The one
stray test stub in Task 0 is called out for deletion in the same step.

**Type consistency:** `run_provenance` (deliver's parameter) vs `provenance` (the
module) vs `rm.provenance` (the field) are three distinct names on purpose — the
parameter cannot be called `provenance` inside `deliver.py`, which imports the module
under that name. `spec_overrides` returns `list[dict]` with keys `field`/`value`/`default`
everywhere it is asserted. `verify_delivery` returns the same six keys in every branch.
