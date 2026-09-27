"""
Repository profile dataclasses.

All findings record their source explicitly:
  - "observed"           → deterministically found in the repository
  - "inferred"           → reasoned from indirect evidence
  - "user_confirmed"     → the user explicitly confirmed or corrected this
  - "agent_recommendation" → suggested by the agent, not yet confirmed
  - "external_doc"       → sourced from official documentation

These sources must never be silently mixed.
"""

from dataclasses import dataclass, field, asdict
from typing import Literal
import json

SourceType = Literal[
    "observed",
    "inferred",
    "user_confirmed",
    "agent_recommendation",
    "external_doc",
]

SeverityType = Literal["info", "warning", "concern"]


@dataclass
class Finding:
    """An evidence-backed observation about the repository."""

    category: str
    observation: str
    evidence: str
    source: SourceType
    severity: SeverityType | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Finding":
        return cls(**data)


@dataclass
class TechnologyEntry:
    """A technology detected in the repository."""

    name: str
    purpose: str
    version: str | None = None
    evidence: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TechnologyEntry":
        return cls(**data)


@dataclass
class RepoProfile:
    """
    Human- and machine-readable profile of a repository.

    Built by deterministic analysis (RepoDiscovery).
    May be corrected by the user — corrections should set source="user_confirmed".
    """

    name: str
    repo_path: str
    detected_languages: list[str] = field(default_factory=list)
    primary_language: str | None = None
    package_managers: list[str] = field(default_factory=list)
    frameworks: list[TechnologyEntry] = field(default_factory=list)
    databases: list[TechnologyEntry] = field(default_factory=list)
    caching: list[TechnologyEntry] = field(default_factory=list)
    message_queues: list[TechnologyEntry] = field(default_factory=list)
    external_services: list[str] = field(default_factory=list)
    architecture_style_observed: str | None = None
    architecture_style_documented: str | None = None
    deployment: list[str] = field(default_factory=list)
    testing_frameworks: list[str] = field(default_factory=list)
    ci_cd: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    has_docker: bool = False
    has_tests: bool = False
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "RepoProfile":
        data = data.copy()
        data["frameworks"] = [
            f if isinstance(f, TechnologyEntry) else TechnologyEntry.from_dict(f)
            for f in data.get("frameworks", [])
        ]
        data["databases"] = [
            d if isinstance(d, TechnologyEntry) else TechnologyEntry.from_dict(d)
            for d in data.get("databases", [])
        ]
        data["caching"] = [
            c if isinstance(c, TechnologyEntry) else TechnologyEntry.from_dict(c)
            for c in data.get("caching", [])
        ]
        data["message_queues"] = [
            m if isinstance(m, TechnologyEntry) else TechnologyEntry.from_dict(m)
            for m in data.get("message_queues", [])
        ]
        data["findings"] = [
            f if isinstance(f, Finding) else Finding.from_dict(f)
            for f in data.get("findings", [])
        ]
        return cls(**data)

    def summary(self) -> str:
        """Human-readable profile summary for user review."""
        sep = "─" * 50

        def section(title: str, items: list[str]) -> str:
            if not items:
                return ""
            return f"  {title}:\n" + "".join(f"    • {item}\n" for item in items)

        def tech_section(title: str, entries: list[TechnologyEntry]) -> str:
            if not entries:
                return ""
            lines = [f"  {title}:"]
            seen = set()
            for e in entries:
                key = e.name
                if key in seen:
                    continue
                seen.add(key)
                ver = f" {e.version}" if e.version else ""
                lines.append(f"    • {e.name}{ver} — {e.purpose}")
            return "\n".join(lines) + "\n"

        lines = [
            sep,
            f"  Repository: {self.name}",
            f"  Path:       {self.repo_path}",
            sep,
        ]

        if self.primary_language:
            lines.append(f"  Primary Language: {self.primary_language}")
        if self.detected_languages:
            lines.append(f"  All Languages:    {', '.join(self.detected_languages)}")
        if self.package_managers:
            lines.append(f"  Package Manager:  {', '.join(self.package_managers)}")

        lines.append("")
        lines.append(tech_section("Frameworks & Libraries", self.frameworks))
        lines.append(tech_section("Databases", self.databases))
        lines.append(tech_section("Caching", self.caching))
        lines.append(tech_section("Message Queues", self.message_queues))
        lines.append(section("External Services", self.external_services))
        lines.append(section("Deployment", self.deployment))
        lines.append(section("CI/CD", self.ci_cd))
        lines.append(section("Testing", self.testing_frameworks))
        lines.append(section("Entry Points", self.entry_points))

        if self.architecture_style_observed:
            lines.append(f"  Architecture (observed):    {self.architecture_style_observed}")
        if self.architecture_style_documented:
            lines.append(f"  Architecture (documented):  {self.architecture_style_documented}")
        if self.architecture_style_observed and self.architecture_style_documented:
            if self.architecture_style_observed.lower() != self.architecture_style_documented.lower():
                lines.append("  ⚠️  Architecture drift: documented ≠ observed")

        lines.append(f"  Docker: {'yes' if self.has_docker else 'no'}  |  "
                     f"Tests: {'yes' if self.has_tests else 'no'}")

        if self.findings:
            lines.append("")
            lines.append(f"  Findings ({len(self.findings)}):")
            shown_categories: set[str] = set()
            for f in self.findings:
                if f.severity in ("warning", "concern"):
                    sev = f"[{f.severity.upper()}] " if f.severity else ""
                    lines.append(f"    {sev}{f.observation}")
                    lines.append(f"      Evidence: {f.evidence}")
                elif f.category not in shown_categories:
                    shown_categories.add(f.category)

        lines.append(sep)
        return "\n".join(lines)


# Re-export assessment models for convenient access from model package
from src.models.assessment import CodeHealthReport, EngineeringAssessment, ProjectStageInference  # noqa: E402
