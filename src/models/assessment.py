"""
Pure domain models and contracts for Engineering Assessment.

Covers:
  - CodeHealthReport: Deterministic AST compilation and import diagnostic model
  - EngineeringAssessment: Comprehensive technical assessment model
  - ProjectStageInference: Multi-dimensional project stage synthesis model

These are pure dataclass contracts without business logic, network, or DB dependencies.
"""

from dataclasses import dataclass, field, asdict
from typing import Literal
import json

from src.models.repo_profile import Finding

StageType = Literal["IDEA", "EARLY", "MID", "LATE", "MATURE"]
ConfidenceType = Literal["LOW", "MEDIUM", "HIGH"]


@dataclass
class CodeHealthReport:
    """Deterministic code health evaluation."""

    is_clean: bool
    syntax_errors: list[Finding] = field(default_factory=list)
    import_errors: list[Finding] = field(default_factory=list)
    unparseable_files: list[str] = field(default_factory=list)
    scanned_file_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "CodeHealthReport":
        data = data.copy()
        data["syntax_errors"] = [
            f if isinstance(f, Finding) else Finding.from_dict(f)
            for f in data.get("syntax_errors", [])
        ]
        data["import_errors"] = [
            f if isinstance(f, Finding) else Finding.from_dict(f)
            for f in data.get("import_errors", [])
        ]
        data["unparseable_files"] = list(data.get("unparseable_files", []))
        data["scanned_file_count"] = int(data.get("scanned_file_count", 0))
        data["is_clean"] = bool(data.get("is_clean", True))
        return cls(**data)


@dataclass
class EngineeringAssessment:
    """Comprehensive engineering assessment combining health, architecture, and git signals."""

    repo_name: str
    health: CodeHealthReport

    architecture_style_observed: str | None = None
    architecture_style_documented: str | None = None
    architecture_drift_detected: bool = False

    dependency_status: dict = field(default_factory=dict)
    test_framework_status: dict = field(default_factory=dict)
    git_vitality: dict = field(default_factory=dict)

    findings: list[Finding] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "EngineeringAssessment":
        data = data.copy()
        health_raw = data.get("health", {})
        if isinstance(health_raw, CodeHealthReport):
            data["health"] = health_raw
        elif isinstance(health_raw, dict):
            data["health"] = CodeHealthReport.from_dict(health_raw)
        else:
            raise TypeError(f"Expected dict or CodeHealthReport for health, got {type(health_raw)}")

        data["findings"] = [
            f if isinstance(f, Finding) else Finding.from_dict(f)
            for f in data.get("findings", [])
        ]
        data["dependency_status"] = dict(data.get("dependency_status", {}))
        data["test_framework_status"] = dict(data.get("test_framework_status", {}))
        data["git_vitality"] = dict(data.get("git_vitality", {}))
        data["risks"] = list(data.get("risks", []))
        data["recommendations"] = list(data.get("recommendations", []))
        return cls(**data)


@dataclass
class ProjectStageInference:
    """Higher-level stage inference synthesized from multi-dimensional evidence."""

    stage: StageType
    confidence: ConfidenceType

    primary_signals: list[str] = field(default_factory=list)
    conflicting_signals: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectStageInference":
        data = data.copy()
        data["primary_signals"] = list(data.get("primary_signals", []))
        data["conflicting_signals"] = list(data.get("conflicting_signals", []))
        data["constraints"] = list(data.get("constraints", []))
        return cls(**data)
