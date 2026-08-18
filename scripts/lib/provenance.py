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
    episode_qc: dict = field(default_factory=dict)   # §10: "judged" + digests, or "absent"
    delivered_at: str = ""
    v: int = PROV_V
    look_checks: list[dict] = field(default_factory=list)   # deliver's post-encode
    # proof that the declared vignette/fade/titles reached the delivered pixels
    # (design 2026-08-15 §7). A "not-checked" row is a real outcome: the source could
    # not discriminate. An empty list means nothing was declared.

    def to_dict(self) -> dict:
        return {"v": self.v, "reel": self.reel, "reel_digest": self.reel_digest,
                "master_digest": self.master_digest, "report_digest": self.report_digest,
                "overall": self.overall, "engine_at_start": dict(self.engine_at_start),
                "engine_at_deliver": dict(self.engine_at_deliver), "edl": dict(self.edl),
                "overrides": list(self.overrides), "episode_qc": dict(self.episode_qc),
                "delivered_at": self.delivered_at, "look_checks": list(self.look_checks)}

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
                   episode_qc=d.get("episode_qc") or {},
                   delivered_at=d.get("delivered_at", ""), v=d.get("v", PROV_V),
                   look_checks=d.get("look_checks") or [])

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def from_json(cls, path: str | Path) -> "Attestation":
        try:
            return cls.from_dict(json.loads(Path(path).read_text()))
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON ({e}) — the attestation sidecar is "
                             f"corrupt; re-deliver the reel") from e


def _episode_qc_state(att: "Attestation") -> str:
    """Returns judged / stale / absent / unknown — episode-qc §10's vocabulary plus the
    2026-08-18 fourth arm, derived rather than trusted verbatim: an old sidecar
    predating this field, or one whose block holds none of the words (a producer bug —
    see build_reel's own-CLI bypass), must read as unknown, never silently as whichever
    real state looks closest.

    `stale` is judged-but-not-about-these-bytes: the delivery re-rendered an episode
    AFTER its verdict was stamped. build_reel refuses that combination outright on the
    router's two-phase path (design 2026-08-18 §2), so reaching this arm means a
    producer that bypassed the refusal — which is exactly what a backstop is for. The
    word is the gate's own, for the same meaning: a stale verdict describes other bytes.

    `absent` never becomes `stale`. A reel with no verdict has no stale one to report,
    and reprocessed_after on such a delivery is bookkeeping about a reel nobody judged."""
    state = att.episode_qc.get("state")
    if state == "judged" and att.episode_qc.get("reprocessed_after"):
        return "stale"
    return state if state in ("judged", "absent") else "unknown"


def verify_delivery(reel_path: str | Path, *, rehash: bool = False) -> dict:
    """One delivered file's state. rehash=False (montage status, called constantly)
    reads the sidecar only; rehash=True (montage verify, run once at CP3) re-hashes
    the shipped file to prove it is the one that was delivered.

    `episode_qc` in the returned dict answers design §10's promise that a judged reel
    is distinguishable from an unjudged one — "judged" / "stale" / "absent" / "unknown"
    (no sidecar at all, or one predating the field, both read as "unknown": there is no
    QC record to report either way; "stale" is judged, then re-rendered — see
    _episode_qc_state)."""
    p = Path(reel_path)
    out: dict = {"file": p.name, "state": "unattested", "overall": None, "overrides": [],
                 "engine_drift": False, "episode_qc": "unknown",
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
               engine_drift=bool(a.get("sha") and b.get("sha") and a != b),
               episode_qc=_episode_qc_state(att), detail="")
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
