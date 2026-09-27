"""
Unit tests for Engineering Assessment domain contracts.

Validates:
- CodeHealthReport creation & round-trip serialization
- EngineeringAssessment creation, nested serialization & round-trip serialization
- ProjectStageInference creation & round-trip serialization
- Finding serialization compatibility
- RepoProfile backward compatibility
- Export imports from both src.models and src.models.assessment
"""

import json
import pytest

from src.models import (
    Finding,
    TechnologyEntry,
    RepoProfile,
    CodeHealthReport,
    EngineeringAssessment,
    ProjectStageInference,
)
from src.models.assessment import (
    CodeHealthReport as AssessmentCodeHealthReport,
    EngineeringAssessment as AssessmentEngineeringAssessment,
    ProjectStageInference as AssessmentProjectStageInference,
)


def test_import_compatibility():
    """Verify models are accessible via src.models, src.models.assessment, and src.models.repo_profile."""
    assert CodeHealthReport is AssessmentCodeHealthReport
    assert EngineeringAssessment is AssessmentEngineeringAssessment
    assert ProjectStageInference is AssessmentProjectStageInference

    from src.models.repo_profile import (
        CodeHealthReport as ReexportedHealth,
        EngineeringAssessment as ReexportedAssessment,
        ProjectStageInference as ReexportedStage,
    )
    assert CodeHealthReport is ReexportedHealth
    assert EngineeringAssessment is ReexportedAssessment
    assert ProjectStageInference is ReexportedStage


# ─── 1. CodeHealthReport Tests ────────────────────────────────────────────────

def test_code_health_report_creation():
    # Clean report with defaults
    report_clean = CodeHealthReport(is_clean=True)
    assert report_clean.is_clean is True
    assert report_clean.syntax_errors == []
    assert report_clean.import_errors == []
    assert report_clean.unparseable_files == []
    assert report_clean.scanned_file_count == 0

    # Report with errors
    syntax_finding = Finding(
        category="code_health",
        observation="SyntaxError on line 12",
        evidence="src/bad.py:12",
        source="observed",
        severity="concern",
    )
    import_finding = Finding(
        category="code_health",
        observation="Missing module 'numpy'",
        evidence="src/calc.py:1",
        source="observed",
        severity="warning",
    )
    report_broken = CodeHealthReport(
        is_clean=False,
        syntax_errors=[syntax_finding],
        import_errors=[import_finding],
        unparseable_files=["src/binary.so"],
        scanned_file_count=42,
    )
    assert report_broken.is_clean is False
    assert len(report_broken.syntax_errors) == 1
    assert len(report_broken.import_errors) == 1
    assert report_broken.scanned_file_count == 42


def test_code_health_report_roundtrip_serialization():
    syntax_finding = Finding(
        category="code_health",
        observation="SyntaxError on line 12",
        evidence="src/bad.py:12",
        source="observed",
        severity="concern",
    )
    original = CodeHealthReport(
        is_clean=False,
        syntax_errors=[syntax_finding],
        import_errors=[],
        unparseable_files=["corrupt.py"],
        scanned_file_count=10,
    )

    # to_dict -> from_dict
    d = original.to_dict()
    assert isinstance(d, dict)
    assert isinstance(d["syntax_errors"], list)
    assert isinstance(d["syntax_errors"][0], dict)
    assert d["syntax_errors"][0]["observation"] == "SyntaxError on line 12"

    restored = CodeHealthReport.from_dict(d)
    assert restored.is_clean == original.is_clean
    assert restored.scanned_file_count == original.scanned_file_count
    assert len(restored.syntax_errors) == 1
    assert isinstance(restored.syntax_errors[0], Finding)
    assert restored.syntax_errors[0].observation == "SyntaxError on line 12"
    assert restored.syntax_errors[0].source == "observed"
    assert restored.unparseable_files == ["corrupt.py"]

    # JSON roundtrip
    j = original.to_json()
    data = json.loads(j)
    restored_json = CodeHealthReport.from_dict(data)
    assert restored_json.is_clean == original.is_clean
    assert restored_json.scanned_file_count == original.scanned_file_count


# ─── 2. EngineeringAssessment Tests ──────────────────────────────────────────

def test_engineering_assessment_creation():
    health = CodeHealthReport(is_clean=True, scanned_file_count=20)
    finding = Finding(
        category="architecture",
        observation="MVC directory structure detected",
        evidence="controllers/ and views/ folders found",
        source="observed",
        severity="info",
    )
    assessment = EngineeringAssessment(
        repo_name="my_service",
        health=health,
        architecture_style_observed="MVC",
        architecture_style_documented="Clean Architecture",
        architecture_drift_detected=True,
        dependency_status={"package_manager": "pip", "dependency_count": 15},
        test_framework_status={"has_tests": True, "frameworks": ["pytest"]},
        git_vitality={"is_git_repo": True, "commit_count": 150},
        findings=[finding],
        risks=["Documented architecture differs from observed folder layout"],
        recommendations=["Align documentation with current MVC structure"],
    )

    assert assessment.repo_name == "my_service"
    assert assessment.health.is_clean is True
    assert assessment.architecture_drift_detected is True
    assert len(assessment.findings) == 1
    assert len(assessment.risks) == 1
    assert len(assessment.recommendations) == 1


def test_engineering_assessment_nested_serialization():
    health = CodeHealthReport(
        is_clean=False,
        syntax_errors=[
            Finding(
                category="code_health",
                observation="Syntax error in main.py",
                evidence="main.py:5",
                source="observed",
                severity="concern",
            )
        ],
        scanned_file_count=5,
    )
    assessment = EngineeringAssessment(
        repo_name="test_app",
        health=health,
        architecture_style_observed="Layered",
        architecture_drift_detected=False,
        findings=[
            Finding(
                category="dependency",
                observation="Django found",
                evidence="requirements.txt",
                source="observed",
            )
        ],
        risks=["Syntax error in entry point prevents running"],
        recommendations=["Fix main.py:5"],
    )

    d = assessment.to_dict()

    # Nested health must be serialized to dict
    assert isinstance(d["health"], dict)
    assert d["health"]["is_clean"] is False
    assert isinstance(d["health"]["syntax_errors"], list)
    assert isinstance(d["health"]["syntax_errors"][0], dict)
    assert d["health"]["syntax_errors"][0]["observation"] == "Syntax error in main.py"

    # Nested findings must be serialized to dicts
    assert isinstance(d["findings"], list)
    assert isinstance(d["findings"][0], dict)
    assert d["findings"][0]["category"] == "dependency"


def test_engineering_assessment_roundtrip_serialization():
    health = CodeHealthReport(is_clean=True, scanned_file_count=12)
    original = EngineeringAssessment(
        repo_name="roundtrip_repo",
        health=health,
        architecture_style_observed="Microservice",
        architecture_style_documented="Microservice",
        architecture_drift_detected=False,
        dependency_status={"pip": 5},
        test_framework_status={"pytest": True},
        git_vitality={"commits": 20},
        findings=[
            Finding(
                category="tech",
                observation="FastAPI detected",
                evidence="main.py",
                source="observed",
                severity="info",
            )
        ],
        risks=["No lockfile present"],
        recommendations=["Generate poetry.lock or pip-compile requirements"],
    )

    d = original.to_dict()
    restored = EngineeringAssessment.from_dict(d)

    assert restored.repo_name == original.repo_name
    assert isinstance(restored.health, CodeHealthReport)
    assert restored.health.is_clean is True
    assert restored.health.scanned_file_count == 12
    assert restored.architecture_style_observed == "Microservice"
    assert restored.architecture_drift_detected is False
    assert len(restored.findings) == 1
    assert isinstance(restored.findings[0], Finding)
    assert restored.findings[0].observation == "FastAPI detected"
    assert restored.risks == ["No lockfile present"]
    assert restored.recommendations == ["Generate poetry.lock or pip-compile requirements"]

    # JSON roundtrip
    j = original.to_json()
    data = json.loads(j)
    restored_json = EngineeringAssessment.from_dict(data)
    assert restored_json.repo_name == original.repo_name
    assert isinstance(restored_json.health, CodeHealthReport)


# ─── 3. ProjectStageInference Tests ──────────────────────────────────────────

@pytest.mark.parametrize("stage,confidence", [
    ("IDEA", "HIGH"),
    ("EARLY", "MEDIUM"),
    ("MID", "HIGH"),
    ("LATE", "MEDIUM"),
    ("MATURE", "HIGH"),
])
def test_project_stage_inference_creation(stage, confidence):
    inference = ProjectStageInference(
        stage=stage,
        confidence=confidence,
        primary_signals=["Git tag v1.0.0 exists", "CI/CD active"],
        conflicting_signals=["README mentions early prototype"],
        constraints=["Preserve public API backward compatibility"],
    )
    assert inference.stage == stage
    assert inference.confidence == confidence
    assert len(inference.primary_signals) == 2
    assert len(inference.conflicting_signals) == 1
    assert len(inference.constraints) == 1


def test_project_stage_inference_roundtrip_serialization():
    original = ProjectStageInference(
        stage="MID",
        confidence="HIGH",
        primary_signals=["15+ commits", "tests passing", "Dockerfile present"],
        conflicting_signals=[],
        constraints=["Expect active refactoring"],
    )

    d = original.to_dict()
    assert isinstance(d, dict)
    assert d["stage"] == "MID"
    assert d["confidence"] == "HIGH"
    assert d["primary_signals"] == ["15+ commits", "tests passing", "Dockerfile present"]

    restored = ProjectStageInference.from_dict(d)
    assert restored.stage == "MID"
    assert restored.confidence == "HIGH"
    assert restored.primary_signals == original.primary_signals
    assert restored.conflicting_signals == []
    assert restored.constraints == ["Expect active refactoring"]

    # JSON roundtrip
    j = original.to_json()
    data = json.loads(j)
    restored_json = ProjectStageInference.from_dict(data)
    assert restored_json.stage == "MID"
    assert restored_json.confidence == "HIGH"


# ─── 4. Finding & RepoProfile Compatibility Tests ─────────────────────────────

def test_finding_from_dict_and_to_dict():
    original = Finding(
        category="security",
        observation="Hardcoded token found",
        evidence="config.py:10",
        source="observed",
        severity="warning",
    )
    d = original.to_dict()
    assert d["category"] == "security"
    assert d["source"] == "observed"
    assert d["severity"] == "warning"

    restored = Finding.from_dict(d)
    assert restored.category == original.category
    assert restored.observation == original.observation
    assert restored.evidence == original.evidence
    assert restored.source == original.source
    assert restored.severity == original.severity


def test_existing_repo_profile_serialization_unchanged():
    """Ensure RepoProfile serialization continues to work with existing tests/data."""
    profile = RepoProfile(
        name="compat_repo",
        repo_path="/tmp/compat",
        detected_languages=["python"],
        primary_language="python",
        package_managers=["pip"],
        frameworks=[
            TechnologyEntry(name="FastAPI", purpose="web framework", version="0.100.0")
        ],
        findings=[
            Finding(
                category="architecture",
                observation="Agent architecture detected",
                evidence="graph.py",
                source="observed",
                severity="info",
            )
        ],
    )
    d = profile.to_dict()
    restored = RepoProfile.from_dict(d)
    assert restored.name == "compat_repo"
    assert len(restored.frameworks) == 1
    assert restored.frameworks[0].name == "FastAPI"
    assert len(restored.findings) == 1
    assert restored.findings[0].category == "architecture"

    # Also test from raw dict with nested dicts (simulating SQLite profile_json load)
    json_str = profile.to_json()
    loaded_dict = json.loads(json_str)
    restored_from_json = RepoProfile.from_dict(loaded_dict)
    assert restored_from_json.name == "compat_repo"
    assert isinstance(restored_from_json.frameworks[0], TechnologyEntry)
    assert isinstance(restored_from_json.findings[0], Finding)
