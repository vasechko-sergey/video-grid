"""Per-episode QC verdicts (design docs/specs/2026-08-08-episode-qc-design.md §4) —
the typed sink for the judge subagent dispatched by skills/episode-qc, and the pure
gate phase 2 refuses on. The per-episode twin of lib/review.py, deliberately the same
shape so the two read alike. No ffmpeg, no IO beyond JSON round-trip: judgment is the
agent's, validation is this module's."""
import json
from dataclasses import dataclass
from pathlib import Path

QC_AXES = ("composition", "colour", "impression", "path", "hero")
QC_SEVERITY = ("blocking", "important", "minor")     # blocking ⇒ the reel is not assembled
QC_ROUTES = ("reprocess", "edit-plan", "match-grade", "none")
QC_CONFIDENCE = ("high", "medium", "low")

# Stop reasons, in the order the gate applies them (design §7). An incomplete artifact
# means the run was never judged; a stale one means the verdicts describe other bytes,
# so their blocking-ness is not about THIS reel; only last does a verdict about these
# very bytes get to speak.
#
# Three, not the four §7's table lists: `episode-qc-missing` (no EPISODE_QC.json at all,
# so there is no ReelQC to construct) is not missing from here — it belongs to the
# caller, which stats the file before it has anything to hand this pure gate. Do not
# "complete" this tuple; there is nothing for a fourth entry to gate over.
QC_STOPS = ("episode-qc-incomplete", "episode-qc-stale", "episode-qc-blocking")


@dataclass
class EpisodeFinding:
    axis: str                  # ∈ QC_AXES                                   (gate)
    severity: str              # ∈ QC_SEVERITY                               (gate)
    evidence: str              # non-empty — cite the frame / timestamp / number (gate)
    route: str                 # ∈ QC_ROUTES — the stage that owns the fix   (gate)
    suggestion: str            # non-empty — the concrete change             (gate)
    confidence: str = "high"   # ∈ QC_CONFIDENCE

    def __post_init__(self) -> None:
        if self.axis not in QC_AXES:
            raise ValueError(f"EpisodeFinding.axis {self.axis!r} not in {QC_AXES}")
        if self.severity not in QC_SEVERITY:
            raise ValueError(f"EpisodeFinding.severity {self.severity!r} not in {QC_SEVERITY}")
        if not (isinstance(self.evidence, str) and self.evidence.strip()):
            raise ValueError("EpisodeFinding.evidence must be a non-empty string (cite the "
                             "frame timestamp, the storyboard mark, or the measured number)")
        if self.route not in QC_ROUTES:
            raise ValueError(f"EpisodeFinding.route {self.route!r} not in {QC_ROUTES}")
        if not (isinstance(self.suggestion, str) and self.suggestion.strip()):
            raise ValueError("EpisodeFinding.suggestion must be a non-empty string (the change)")
        if self.confidence not in QC_CONFIDENCE:
            raise ValueError(f"EpisodeFinding.confidence {self.confidence!r} not in {QC_CONFIDENCE}")

    @classmethod
    def from_dict(cls, d: dict) -> "EpisodeFinding":
        # Top level checked FIRST, before any d.get — the Spec.from_dict rule, at a
        # boundary that reads an agent's JSON.
        if not isinstance(d, dict):
            raise ValueError(f"EpisodeFinding.from_dict: expected a finding object with "
                             f"'axis'/'severity'/'evidence'/'route'/'suggestion', got "
                             f"{type(d).__name__} — re-run the episode-qc judge")
        conf = d.get("confidence")
        return cls(axis=d.get("axis"), severity=d.get("severity"), evidence=d.get("evidence"),
                   route=d.get("route"), suggestion=d.get("suggestion"),
                   confidence="high" if conf is None else conf)

    def to_dict(self) -> dict:
        return {"axis": self.axis, "severity": self.severity, "evidence": self.evidence,
                "route": self.route, "suggestion": self.suggestion,
                "confidence": self.confidence}


@dataclass
class EpisodeVerdict:
    idx: int                   # episode index in the reel manifest          (gate)
    clip: str                  # the judged clip path                        (gate)
    clip_digest: str           # sha256 of that file, stamped by episode_qc build (gate)
    findings: tuple = ()
    summary: str = ""
    reviewer: str = ""         # free note — which agent/model judged

    def __post_init__(self) -> None:
        if isinstance(self.idx, bool) or not isinstance(self.idx, int) or self.idx < 0:
            raise ValueError(f"EpisodeVerdict.idx must be an episode index >= 0, got {self.idx!r}")
        if not (isinstance(self.clip, str) and self.clip.strip()):
            raise ValueError("EpisodeVerdict.clip must be the judged clip's path")
        if not (isinstance(self.clip_digest, str) and self.clip_digest.strip()):
            raise ValueError(
                "EpisodeVerdict.clip_digest must be the sha256 of the judged clip — "
                "episode_qc build stamps it from the file on disk; a verdict without one "
                "names an episode but not which render of it")
        if not (isinstance(self.findings, (tuple, list))
                and all(isinstance(f, EpisodeFinding) for f in self.findings)):
            raise ValueError("EpisodeVerdict.findings must be EpisodeFinding objects "
                             "(build them through episode_qc.build_qc, which validates each)")
        self.findings = tuple(self.findings)
        for name in ("summary", "reviewer"):
            v = getattr(self, name)
            if not isinstance(v, str):
                raise ValueError(f"EpisodeVerdict.{name} must be a string, got {v!r}")

    @property
    def verdict(self) -> str:
        """revise iff any blocking finding. Computed, never stored — a hand-edited
        artifact must not be able to lie about its own verdict (the Review rule)."""
        return "revise" if any(f.severity == "blocking" for f in self.findings) else "approve"

    @classmethod
    def from_dict(cls, d: dict) -> "EpisodeVerdict":
        if not isinstance(d, dict):
            raise ValueError(f"EpisodeVerdict.from_dict: expected an object with 'idx'/'clip'/"
                             f"'clip_digest', got {type(d).__name__} — re-run episode_qc build")
        raw = d.get("findings") or []
        if not isinstance(raw, (tuple, list)):
            raise ValueError(f"EpisodeVerdict.findings must be a JSON list, got {type(raw).__name__}")
        return cls(idx=d.get("idx"), clip=d.get("clip"), clip_digest=d.get("clip_digest"),
                   findings=tuple(EpisodeFinding.from_dict(f) for f in raw),
                   summary=d.get("summary") or "", reviewer=d.get("reviewer") or "")

    def to_dict(self) -> dict:
        # verdict is emitted for readers and recomputed on load (never trusted)
        return {"idx": self.idx, "clip": self.clip, "clip_digest": self.clip_digest,
                "verdict": self.verdict, "findings": [f.to_dict() for f in self.findings],
                "summary": self.summary, "reviewer": self.reviewer}


@dataclass
class ReelQC:
    episodes: tuple = ()       # tuple[EpisodeVerdict, ...] — one per reel episode

    def __post_init__(self) -> None:
        if not (isinstance(self.episodes, (tuple, list))
                and all(isinstance(e, EpisodeVerdict) for e in self.episodes)):
            raise ValueError("ReelQC.episodes must be EpisodeVerdict objects")
        self.episodes = tuple(self.episodes)
        seen: set[int] = set()
        for e in self.episodes:
            if e.idx in seen:
                raise ValueError(f"ReelQC judges episode {e.idx} twice — one verdict per "
                                 f"episode; re-run episode_qc build over the packet dirs")
            seen.add(e.idx)

    @property
    def ok(self) -> bool:
        return all(e.verdict == "approve" for e in self.episodes)

    @property
    def by_idx(self) -> dict:
        return {e.idx: e for e in self.episodes}

    @classmethod
    def from_dict(cls, d: dict) -> "ReelQC":
        if not isinstance(d, dict):
            raise ValueError(f"ReelQC.from_dict: expected an EPISODE_QC.json object with an "
                             f"'episodes' list, got {type(d).__name__} — re-run episode_qc build")
        raw = d.get("episodes") or []
        if not isinstance(raw, (tuple, list)):
            raise ValueError(f"ReelQC.episodes must be a JSON list, got {type(raw).__name__}")
        return cls(episodes=tuple(EpisodeVerdict.from_dict(e) for e in raw))

    def to_dict(self) -> dict:
        return {"episodes": [e.to_dict() for e in self.episodes]}

    @classmethod
    def from_json(cls, path: str | Path) -> "ReelQC":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is corrupt ({e}) — re-run episode_qc build") from e
        return cls.from_dict(d)

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    def to_markdown(self) -> str:
        icon = {True: "✅", False: "🔧"}[self.ok]
        lines = [f"# Episode QC — {icon} {len(self.episodes)} episodes, "
                 f"{'all approved' if self.ok else 'revise'}", ""]
        order = {"blocking": 0, "important": 1, "minor": 2}
        for e in sorted(self.episodes, key=lambda e: e.idx):
            mark = "✅" if e.verdict == "approve" else "🔧"
            lines.append(f"## {mark} ep{e.idx} — `{e.clip}`")
            if e.summary:
                lines += ["", e.summary]
            lines.append("")
            if not e.findings:
                lines += ["No findings.", ""]
                continue
            for f in sorted(e.findings, key=lambda f: order[f.severity]):
                lines.append(f"- **[{f.severity}] {f.axis}** → `{f.route}` "
                             f"(confidence: {f.confidence})")
                lines.append(f"  - {f.evidence}")
                lines.append(f"  - **Fix:** {f.suggestion}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def _short(digest: str) -> str:
    return f"{digest[:12]}…"


def gate(qc: ReelQC, digests: dict) -> tuple:
    """(reason, problems) — reason is None iff the reel may be assembled.

    `digests` maps EVERY episode index in the reel to the sha256 of its clip NOW, so
    this stays pure: the caller owns the filesystem, this owns the decision. The
    missing-artifact case has no ReelQC to pass and is therefore the caller's
    (design §7).

    The three reasons are applied in QC_STOPS order and the FIRST one wins: an
    incomplete artifact means the run was never judged; a stale one means the
    verdicts are about other bytes, so their blocking-ness is not about this reel."""
    by_idx = qc.by_idx
    missing = [f"episode {i} has no verdict" for i in sorted(digests) if i not in by_idx]
    extra = [f"verdict for episode {i}, which this reel does not have"
             for i in sorted(by_idx) if i not in digests]
    if missing or extra:
        return QC_STOPS[0], missing + extra
    stale = [f"episode {i} was judged as {_short(by_idx[i].clip_digest)} but "
             f"{by_idx[i].clip} now hashes to {_short(digests[i])}"
             for i in sorted(digests) if by_idx[i].clip_digest != digests[i]]
    if stale:
        return QC_STOPS[1], stale
    blocking = [f"episode {i}: [{f.severity}] {f.axis} — {f.evidence}"
                for i in sorted(by_idx) for f in by_idx[i].findings
                if f.severity == "blocking"]
    if blocking:
        return QC_STOPS[2], blocking
    return None, []
