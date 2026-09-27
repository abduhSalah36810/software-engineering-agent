"""
Comprehensive Unit Tests for Project Stage & State Inference (Phase 3).

Validates:
  1. IDEA: documentation-only repository
  2. EARLY: initial implementation + dependencies + little testing
  3. MID: substantial implementation + architecture + some tests
  4. LATE: broad implementation + testing + deployment + documentation
  5. MATURE: strong evidence across multiple engineering dimensions
  6. Healthy EARLY repository (clean code does not force MATURE)
  7. Unhealthy MATURE repository (syntax errors do not degrade MATURE to EARLY)
  8. Conflicting signals detection (extensive code without tests, no git)
  9. Missing Git history (captured as constraint)
  10. Missing testing information (captured as constraint)
  11. Low-confidence inference (due to multiple conflicting signals / constraints)
  12. Single-metric independence:
      A) Many files alone does NOT imply MATURE
      B) Many commits alone does NOT imply MATURE
      C) Docker alone does NOT imply MATURE
      D) Small repository with strong multi-dimensional engineering signals CAN be MATURE
      E) Conflicting evidence remains visible
      F) Confidence reflects completeness & alignment
  13. ProjectStageInference serialization roundtrip
  14. Architecture drift recorded as a conflicting signal
  15. RepoProfile integration with deployment/CI signals
"""

import pytest

from src.models.assessment import (
    CodeHealthReport,
    EngineeringAssessment,
    ProjectStageInference,
)
from src.models.repo_profile import Finding, RepoProfile
from src.helpers.project_stage import ProjectStageInferencer


def make_assessment(
    scanned_file_count: int = 1,
    is_clean: bool = True,
    syntax_errors: list[Finding] | None = None,
    import_errors: list[Finding] | None = None,
    unparseable_files: list[str] | None = None,
    arch_observed: str | None = None,
    arch_documented: str | None = None,
    arch_drift: bool = False,
    manifest_count: int = 0,
    has_lockfile: bool = False,
    manifests_found: list[str] | None = None,
    has_tests: bool = False,
    test_file_count: int = 0,
    has_test_config: bool = False,
    ci_test_detected: bool = False,
    test_frameworks: list[str] | None = None,
    is_git_repo: bool = True,
    recent_commit_count: int = 5,
    has_history: bool = True,
    findings: list[Finding] | None = None,
) -> EngineeringAssessment:
    """Helper to synthesize deterministic EngineeringAssessment fixtures."""
    health = CodeHealthReport(
        is_clean=is_clean,
        syntax_errors=syntax_errors or [],
        import_errors=import_errors or [],
        unparseable_files=unparseable_files or [],
        scanned_file_count=scanned_file_count,
    )
    dep_status = {
        "manifest_count": manifest_count,
        "has_lockfile": has_lockfile,
        "manifests_found": manifests_found or (["requirements.txt"] if manifest_count else []),
        "package_managers": ["pip"] if manifest_count else [],
        "lockfiles_found": ["poetry.lock"] if has_lockfile else [],
        "dependency_count": 10 if manifest_count else 0,
    }
    test_status = {
        "has_tests": has_tests,
        "test_file_count": test_file_count,
        "test_directories": ["tests"] if has_tests else [],
        "has_test_config": has_test_config,
        "ci_test_detected": ci_test_detected,
        "test_frameworks": test_frameworks or ([] if not has_tests else ["pytest"]),
    }
    git_status = {
        "is_git_repo": is_git_repo,
        "head_commit": "abcdef123456" if has_history else None,
        "branch": "main" if is_git_repo else None,
        "recent_commit_count": recent_commit_count,
        "has_history": has_history,
    }
    return EngineeringAssessment(
        repo_name="test_repo",
        health=health,
        architecture_style_observed=arch_observed,
        architecture_style_documented=arch_documented,
        architecture_drift_detected=arch_drift,
        dependency_status=dep_status,
        test_framework_status=test_status,
        git_vitality=git_status,
        findings=findings or [],
    )


# ── 1. IDEA: Documentation-Only Repository ───────────────────────────────────

def test_idea_documentation_only():
    inferencer = ProjectStageInferencer()
    assessment = make_assessment(
        scanned_file_count=0,
        findings=[
            Finding(
                category="documentation",
                observation="README documentation detected with setup and usage content (500 bytes)",
                evidence="README.md",
                source="observed",
                severity="info",
            )
        ],
    )

    result = inferencer.infer(assessment)

    assert result.stage == "IDEA"
    assert any("No source code implementation" in s for s in result.primary_signals)
    assert any("Project release intent" in c for c in result.constraints)


# ── 2. EARLY: Initial Implementation + Dependencies ──────────────────────────

def test_early_initial_implementation():
    inferencer = ProjectStageInferencer()
    assessment = make_assessment(
        scanned_file_count=2,
        manifest_count=1,
        has_lockfile=False,
        has_tests=False,
        recent_commit_count=2,
        arch_observed=None,
    )

    result = inferencer.infer(assessment)

    assert result.stage == "EARLY"
    assert any("Initial code implementation" in s for s in result.primary_signals)
    assert any("Automated test suite not yet established" in s for s in result.primary_signals)


# ── 3. MID: Substantial Implementation + Architecture + Some Tests ───────────

def test_mid_substantial_implementation():
    inferencer = ProjectStageInferencer()
    assessment = make_assessment(
        scanned_file_count=8,
        arch_observed="Layered Architecture",
        has_tests=True,
        test_file_count=3,
        has_test_config=False,
        recent_commit_count=8,
        manifest_count=1,
    )

    result = inferencer.infer(assessment)

    assert result.stage == "MID"
    assert any("Substantial" in s for s in result.primary_signals)
    assert any("Layered Architecture" in s for s in result.primary_signals)


# ── 4. LATE: Broad Implementation + Testing + Deployment ─────────────────────

def test_late_broad_implementation():
    inferencer = ProjectStageInferencer()
    assessment = make_assessment(
        scanned_file_count=20,
        arch_observed="Clean Architecture",
        has_tests=True,
        test_file_count=8,
        has_test_config=True,
        has_lockfile=True,
        manifest_count=1,
        recent_commit_count=12,
        findings=[
            Finding(
                category="documentation",
                observation="Deployment documentation detected with docker references",
                evidence="README.md",
                source="observed",
                severity="info",
            )
        ],
    )

    result = inferencer.infer(assessment)

    assert result.stage in ("LATE", "MATURE")
    assert any("Clean Architecture" in s for s in result.primary_signals)
    assert any("Automated test" in s or "Established automated" in s for s in result.primary_signals)


# ── 5. MATURE: Strong Multi-Dimensional Engineering Signals ──────────────────

def test_mature_strong_multidimensional_evidence():
    inferencer = ProjectStageInferencer()
    assessment = make_assessment(
        scanned_file_count=25,
        arch_observed="Agent Architecture",
        has_tests=True,
        test_file_count=15,
        has_test_config=True,
        ci_test_detected=True,
        has_lockfile=True,
        manifest_count=1,
        recent_commit_count=25,
        findings=[
            Finding(
                category="deployment",
                observation="Docker container specifications detected",
                evidence="Dockerfile",
                source="observed",
                severity="info",
            ),
            Finding(
                category="documentation",
                observation="README documentation detected with setup and usage content (2000 bytes)",
                evidence="README.md",
                source="observed",
                severity="info",
            ),
        ],
    )

    result = inferencer.infer(assessment)

    assert result.stage == "MATURE"
    assert result.confidence == "HIGH"
    assert any("Agent Architecture" in s for s in result.primary_signals)
    assert any("Deterministic dependency" in s for s in result.primary_signals)


# ── 6. Healthy EARLY Repository ──────────────────────────────────────────────

def test_healthy_early_repository():
    inferencer = ProjectStageInferencer()
    # Repository has perfectly valid syntax, 0 errors, but is only 2 files and 2 commits
    assessment = make_assessment(
        scanned_file_count=2,
        is_clean=True,
        syntax_errors=[],
        import_errors=[],
        has_tests=False,
        recent_commit_count=2,
    )

    result = inferencer.infer(assessment)

    assert result.stage == "EARLY"
    # Stage is EARLY despite is_clean being True
    assert any("Initial code implementation" in s for s in result.primary_signals)


# ── 7. Unhealthy MATURE Repository ───────────────────────────────────────────

def test_unhealthy_mature_repository():
    inferencer = ProjectStageInferencer()
    # Mature engineering signals across all pillars, but active syntax errors
    assessment = make_assessment(
        scanned_file_count=30,
        is_clean=False,
        syntax_errors=[
            Finding(
                category="code_health",
                observation="SyntaxError in main.py: invalid syntax",
                evidence="main.py:10:5",
                source="observed",
                severity="concern",
            )
        ],
        arch_observed="Clean Architecture",
        has_tests=True,
        test_file_count=20,
        has_test_config=True,
        ci_test_detected=True,
        has_lockfile=True,
        manifest_count=1,
        recent_commit_count=35,
        findings=[
            Finding(
                category="deployment",
                observation="Docker deployment files detected",
                evidence="Dockerfile",
                source="observed",
                severity="info",
            ),
            Finding(
                category="documentation",
                observation="README documentation detected",
                evidence="README.md",
                source="observed",
                severity="info",
            ),
        ],
    )

    result = inferencer.infer(assessment)

    # Repository remains MATURE structurally despite code health failure
    assert result.stage == "MATURE"
    assert any("Active code health violations" in s for s in result.conflicting_signals)


# ── 8. Conflicting Signals ───────────────────────────────────────────────────

def test_conflicting_signals():
    inferencer = ProjectStageInferencer()
    # Large codebase (25 files) with architecture, but 0 tests and no Git tracking
    assessment = make_assessment(
        scanned_file_count=25,
        arch_observed="Clean Architecture",
        has_tests=False,
        is_git_repo=False,
        recent_commit_count=0,
        has_history=False,
    )

    result = inferencer.infer(assessment)

    assert len(result.conflicting_signals) >= 2
    assert any("Extensive codebase" in s for s in result.conflicting_signals)
    assert any("outside of Git" in s for s in result.conflicting_signals)
    assert result.confidence == "LOW"


# ── 9. Missing Git History ───────────────────────────────────────────────────

def test_missing_git_history():
    inferencer = ProjectStageInferencer()
    assessment = make_assessment(
        scanned_file_count=5,
        is_git_repo=False,
        recent_commit_count=0,
        has_history=False,
    )

    result = inferencer.infer(assessment)

    assert any("not tracked by Git" in c for c in result.constraints)


# ── 10. Missing Testing Information ──────────────────────────────────────────

def test_missing_testing_information():
    inferencer = ProjectStageInferencer()
    assessment = make_assessment(
        scanned_file_count=5,
        has_tests=False,
        test_file_count=0,
    )

    result = inferencer.infer(assessment)

    assert any("no detectable automated test suite" in c for c in result.constraints)


# ── 11. Low-Confidence Inference ─────────────────────────────────────────────

def test_low_confidence_inference():
    inferencer = ProjectStageInferencer()
    # High conflict count and multiple missing constraints
    assessment = make_assessment(
        scanned_file_count=25,
        has_tests=False,
        is_git_repo=False,
        manifest_count=0,
        arch_observed=None,
    )

    result = inferencer.infer(assessment)

    assert result.confidence == "LOW"


# ── 12. Corrective Requirements: Evidence-Combination Proofs ─────────────────

# A) Many files alone does NOT imply MATURE
def test_many_files_alone_does_not_imply_mature():
    inferencer = ProjectStageInferencer()
    # 50 files dumped with NO architecture, NO tests, NO deployment, NO lockfile, NO git
    assessment = make_assessment(
        scanned_file_count=50,
        arch_observed=None,
        has_tests=False,
        is_git_repo=False,
        has_lockfile=False,
        manifest_count=0,
    )
    result = inferencer.infer(assessment)
    assert result.stage != "MATURE"
    assert result.stage != "LATE"
    assert result.stage == "EARLY"
    assert any("without recognized architectural" in s or "without any automated test" in s for s in result.conflicting_signals)


# B) Many commits alone does NOT imply MATURE
def test_many_commits_alone_does_not_imply_mature():
    inferencer = ProjectStageInferencer()
    # 100 commits on a 1-file repository without tests, architecture, or deployment
    assessment = make_assessment(
        scanned_file_count=1,
        recent_commit_count=100,
        has_tests=False,
        arch_observed=None,
        has_lockfile=False,
        manifest_count=0,
    )
    result = inferencer.infer(assessment)
    assert result.stage != "MATURE"
    assert result.stage == "EARLY"
    assert any("Sustained commit history" in s for s in result.conflicting_signals)


# C) Docker alone does NOT imply MATURE
def test_docker_alone_does_not_imply_mature():
    inferencer = ProjectStageInferencer()
    # Docker presence on an initial 1-file repository without tests or architecture
    assessment = make_assessment(
        scanned_file_count=1,
        arch_observed=None,
        has_tests=False,
        findings=[
            Finding(
                category="deployment",
                observation="Docker container detected",
                evidence="Dockerfile",
                source="observed",
                severity="info",
            )
        ],
    )
    result = inferencer.infer(assessment)
    assert result.stage != "MATURE"
    assert result.stage == "EARLY"


# D) Small repository with strong independent engineering signals CAN be MATURE
def test_small_repo_with_strong_signals_implies_mature():
    inferencer = ProjectStageInferencer()
    # A focused 3-file microservice with full engineering practices across all dimensions:
    # 1. Clean Architecture, 2. Configured test suite, 3. Lockfile, 4. Docker + CI, 5. Git, 6. README
    assessment = make_assessment(
        scanned_file_count=3,
        arch_observed="Clean Architecture",
        has_tests=True,
        test_file_count=5,
        has_test_config=True,
        ci_test_detected=True,
        has_lockfile=True,
        manifest_count=1,
        recent_commit_count=20,
        findings=[
            Finding(
                category="deployment",
                observation="Docker container detected",
                evidence="Dockerfile",
                source="observed",
                severity="info",
            ),
            Finding(
                category="documentation",
                observation="README documentation detected with setup and architecture",
                evidence="README.md",
                source="observed",
                severity="info",
            ),
        ],
    )
    result = inferencer.infer(assessment)
    # Small file count does not prevent MATURE when all other engineering dimensions are established
    assert result.stage == "MATURE"
    assert any("Clean Architecture" in s for s in result.primary_signals)
    assert any("Deterministic dependency" in s for s in result.primary_signals)


# E) Conflicting evidence remains visible
def test_conflicting_evidence_remains_visible():
    inferencer = ProjectStageInferencer()
    # Substantial code with architecture, but 1 commit and no tests
    assessment = make_assessment(
        scanned_file_count=10,
        arch_observed="MVC",
        recent_commit_count=1,
        has_tests=False,
    )
    result = inferencer.infer(assessment)
    assert any("Git history is limited" in s for s in result.conflicting_signals)


# F) Confidence reflects evidence completeness & alignment
def test_confidence_reflects_alignment():
    inferencer = ProjectStageInferencer()
    # Coordinated repository with no conflicts
    good = make_assessment(
        scanned_file_count=15,
        arch_observed="Layered Architecture",
        has_tests=True,
        test_file_count=6,
        has_lockfile=True,
        manifest_count=1,
        recent_commit_count=12,
        findings=[
            Finding(
                category="documentation",
                observation="README documentation detected",
                evidence="README.md",
                source="observed",
                severity="info",
            ),
            Finding(
                category="deployment",
                observation="Deployment documentation detected",
                evidence="README.md",
                source="observed",
                severity="info",
            ),
        ],
    )
    res_good = inferencer.infer(good)
    assert res_good.confidence == "HIGH"


# ── 13. ProjectStageInference Serialization ───────────────────────────────────

def test_project_stage_inference_serialization():
    inferencer = ProjectStageInferencer()
    assessment = make_assessment(
        scanned_file_count=10,
        arch_observed="Clean Architecture",
        has_tests=True,
        test_file_count=4,
        recent_commit_count=8,
    )
    result = inferencer.infer(assessment)

    data = result.to_dict()
    assert isinstance(data, dict)
    assert data["stage"] == result.stage
    assert data["confidence"] == result.confidence
    assert isinstance(data["primary_signals"], list)
    assert isinstance(data["conflicting_signals"], list)
    assert isinstance(data["constraints"], list)

    json_str = result.to_json()
    assert isinstance(json_str, str)

    restored = ProjectStageInference.from_dict(data)
    assert restored.stage == result.stage
    assert restored.confidence == result.confidence
    assert restored.primary_signals == result.primary_signals
    assert restored.conflicting_signals == result.conflicting_signals
    assert restored.constraints == result.constraints


# ── 14. Architecture Drift Recorded as Conflict ──────────────────────────────

def test_architecture_drift_recorded_as_conflict():
    inferencer = ProjectStageInferencer()
    assessment = make_assessment(
        scanned_file_count=12,
        arch_observed="Agent Architecture",
        arch_documented="MVC",
        arch_drift=True,
    )
    result = inferencer.infer(assessment)

    assert any("differs from observed structure" in s for s in result.conflicting_signals)


# ── 15. RepoProfile Integration with Deployment / CI Signals ──────────────────

def test_repo_profile_passed_to_inferencer():
    inferencer = ProjectStageInferencer()
    assessment = make_assessment(
        scanned_file_count=12,
        arch_observed="Clean Architecture",
        has_tests=True,
        test_file_count=5,
        has_lockfile=True,
        manifest_count=1,
        recent_commit_count=10,
    )
    profile = RepoProfile(
        name="test_proj",
        repo_path="/path/test",
        has_docker=True,
        ci_cd=["github_actions"],
    )

    result = inferencer.infer(assessment, profile=profile)

    assert result.stage in ("LATE", "MATURE")
    assert any("Deployment" in s or "CI/CD" in s for s in result.primary_signals)
