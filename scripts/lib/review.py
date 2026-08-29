"""Reel-review: the §5.13 editorial verdict (design
docs/specs/2026-07-18-reel-review-editorial-design.md, Slice B). A fresh reviewer
subagent judges the delivered reel against SPEC and emits typed findings; this module
is the contract those findings validate against. Hard config-specs — validate-and-raise
in __post_init__, JSON round-trip — like spec.py's Spec / edl.py's EDL. No ffmpeg: a
text stage; the reviewer is an agent, this module is its typed sink.
"""
import json
from dataclasses import dataclass
from pathlib import Path

REVIEW_AXES = ("idea", "mood", "hook", "ending", "spine",       # the §5.13 editorial questions
               "edl_completeness", "trend_flavor",
               "colour")                                        # design 2026-08-29 §4: no machine
                                                                # measures reel-level colour agreement,
                                                                # so the reader who can does
REVIEW_SEVERITY = ("blocking", "important", "minor")             # blocking ⇒ verdict "revise"
REVIEW_ROUTES = ("edit-plan", "pacing", "music",                # the fixer stage the human re-runs
                 "reprocess", "titles", "match-grade", "none")
REVIEW_CONFIDENCE = ("high", "medium", "low")                   # trend_flavor is forced "low" (no §5.4 source)


@dataclass
class Finding:
    axis: str                  # ∈ REVIEW_AXES                              (gate)
    severity: str              # ∈ REVIEW_SEVERITY                          (gate)
    evidence: str              # non-empty — cite ep idx / timestamp / signal (gate)
    route: str                 # ∈ REVIEW_ROUTES — suggested fixer stage    (gate)
    suggestion: str            # non-empty — the concrete change            (gate)
    confidence: str = "high"   # ∈ REVIEW_CONFIDENCE

    def __post_init__(self) -> None:
        if self.axis not in REVIEW_AXES:
            raise ValueError(f"Finding.axis {self.axis!r} not in {REVIEW_AXES}")
        if self.severity not in REVIEW_SEVERITY:
            raise ValueError(f"Finding.severity {self.severity!r} not in {REVIEW_SEVERITY}")
        if not (isinstance(self.evidence, str) and self.evidence.strip()):
            raise ValueError("Finding.evidence must be a non-empty string (cite the episode / "
                             "timestamp / advisory signal that grounds the finding)")
        if self.route not in REVIEW_ROUTES:
            raise ValueError(f"Finding.route {self.route!r} not in {REVIEW_ROUTES}")
        if not (isinstance(self.suggestion, str) and self.suggestion.strip()):
            raise ValueError("Finding.suggestion must be a non-empty string (the concrete change)")
        if self.confidence not in REVIEW_CONFIDENCE:
            raise ValueError(f"Finding.confidence {self.confidence!r} not in {REVIEW_CONFIDENCE}")

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        # Top level checked FIRST (the Spec.from_dict rule) — a non-dict never reaches
        # __post_init__ as a bare AttributeError out of a boundary reading agent JSON.
        if not isinstance(d, dict):
            raise ValueError(f"Finding.from_dict: expected a finding object with 'axis'/'severity'/"
                             f"'evidence'/'route'/'suggestion' fields, got {type(d).__name__} — "
                             f"re-run reel-review to regenerate the findings")
        conf = d.get("confidence")
        return cls(axis=d.get("axis"), severity=d.get("severity"), evidence=d.get("evidence"),
                   route=d.get("route"), suggestion=d.get("suggestion"),
                   confidence="high" if conf is None else conf)

    def to_dict(self) -> dict:
        return {"axis": self.axis, "severity": self.severity, "evidence": self.evidence,
                "route": self.route, "suggestion": self.suggestion, "confidence": self.confidence}


@dataclass
class Review:
    reel: str                  # path to the reviewed cut (out/REEL_v{n}.mp4); non-empty (gate)
    findings: tuple = ()       # tuple[Finding, ...] — build via reel_review.build_review (gate)
    summary: str = ""          # the reviewer's one-paragraph overall read
    spec_ref: str = ""         # echo of the intent judged (or the SPEC.json path)
    platform: str = ""         # from SPEC.platform, header only
    reviewer: str = ""         # free note — which agent/model reviewed

    def __post_init__(self) -> None:
        if not (isinstance(self.reel, str) and self.reel.strip()):
            raise ValueError("Review.reel must be a non-empty string (the reviewed reel path)")
        if not (isinstance(self.findings, (tuple, list))
                and all(isinstance(f, Finding) for f in self.findings)):
            raise ValueError("Review.findings must be a list of Finding objects "
                             "(build via reel_review.build_review, which validates each)")
        self.findings = tuple(self.findings)
        for name in ("summary", "spec_ref", "platform", "reviewer"):
            v = getattr(self, name)
            if not isinstance(v, str):
                raise ValueError(f"Review.{name} must be a string, got {v!r}")

    @property
    def verdict(self) -> str:
        """revise iff any blocking finding, else approve. A computed property, never a
        stored field — one source of truth, so a hand-edited REVIEW.json cannot lie about
        its own verdict. Advisory to the human: an approve with important findings is
        'approve with notes'; a human may waive a blocking finding and approve anyway."""
        return "revise" if any(f.severity == "blocking" for f in self.findings) else "approve"

    @classmethod
    def from_dict(cls, d: dict) -> "Review":
        if not isinstance(d, dict):
            raise ValueError(f"Review.from_dict: expected a REVIEW.json object with a 'reel' field "
                             f"and a 'findings' list, got {type(d).__name__} — re-run reel-review")
        raw = d.get("findings") or []
        if not isinstance(raw, (tuple, list)):
            raise ValueError(f"Review.findings must be a JSON list, got {type(raw).__name__}")
        findings = tuple(Finding.from_dict(f) for f in raw)   # an incoming 'verdict' is ignored (recomputed)

        def opt(key: str, default: object) -> object:
            v = d.get(key)
            return default if v is None else v
        return cls(reel=d.get("reel"), findings=findings, summary=opt("summary", ""),
                   spec_ref=opt("spec_ref", ""), platform=opt("platform", ""),
                   reviewer=opt("reviewer", ""))

    def to_dict(self) -> dict:
        # verdict is emitted for the .md/.json readers but recomputed on load (never trusted)
        return {"reel": self.reel, "verdict": self.verdict,
                "findings": [f.to_dict() for f in self.findings], "summary": self.summary,
                "spec_ref": self.spec_ref, "platform": self.platform, "reviewer": self.reviewer}

    @classmethod
    def from_json(cls, path: str | Path) -> "Review":
        try:
            d = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is corrupt ({e}) — re-run reel-review to regenerate it") from e
        return cls.from_dict(d)

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    def to_markdown(self) -> str:
        icon = {"approve": "✅", "revise": "🔧"}[self.verdict]
        head = f"# Reel review — {icon} {self.verdict}"
        if self.platform:
            head += f" · {self.platform}"
        lines = [head, "", f"**Reel:** `{self.reel}`", ""]
        if self.summary:
            lines += [self.summary, ""]
        if not self.findings:
            lines.append("✅ No findings — the reel delivers the brief.")
            return "\n".join(lines)
        order = {"blocking": 0, "important": 1, "minor": 2}
        for f in sorted(self.findings, key=lambda f: order[f.severity]):
            lines.append(f"- **[{f.severity}] {f.axis}** → `{f.route}` (confidence: {f.confidence})")
            lines.append(f"  - {f.evidence}")
            lines.append(f"  - **Fix:** {f.suggestion}")
        return "\n".join(lines)
