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
               "edl_completeness", "trend_flavor")
REVIEW_SEVERITY = ("blocking", "important", "minor")             # blocking ⇒ verdict "revise"
REVIEW_ROUTES = ("edit-plan", "pacing", "music",                # the fixer stage the human re-runs
                 "reprocess", "titles", "none")
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
