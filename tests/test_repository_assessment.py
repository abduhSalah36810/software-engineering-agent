"""
Comprehensive unit tests for RepositoryAssessmentEngine (Phase 2).

Validates:
  1. Empty repository handling
  2. Missing / inaccessible repository path
  3. Python repository with valid syntax
  4. Python repository with syntax errors
  5. Python repository with broken relative imports
  6. Non-Python repository (JavaScript, TypeScript, Go)
  7. Mixed-language repository
  8. Dependency manifest detection (requirements.txt, package.json, lockfiles)
  9. Test framework and test directory detection
  10. Git repository detection (commits, branch, vitality)
  11. Non-Git repository handling
  12. README and documentation detection
  13. Architecture observed vs documented comparison & drift
  14. EngineeringAssessment construction and roundtrip serialization
  15. Detector failure resilience (isolated failure does not crash assessment)
  16. Unparseable / binary file handling
  17. Documentation-only repository handling
"""

import json
import subprocess
import pytest
from pathlib import Path

from src.models.assessment import CodeHealthReport, EngineeringAssessment
from src.models.repo_profile import Finding, RepoProfile
from src.helpers.repository_assessment import RepositoryAssessmentEngine


# ── 1. Empty Repository ───────────────────────────────────────────────────────

def test_empty_repository(tmp_path):
    repo = tmp_path / "empty_repo"
    repo.mkdir()

    engine = RepositoryAssessmentEngine(str(repo))
    assessment = engine.build_assessment()

    assert assessment.health.is_clean is True
    assert assessment.health.scanned_file_count == 0
    assert assessment.health.syntax_errors == []
    assert assessment.health.import_errors == []
    assert assessment.health.unparseable_files == []
    assert assessment.dependency_status["manifest_count"] == 0
    assert assessment.test_framework_status["has_tests"] is False
    assert assessment.git_vitality["is_git_repo"] is False

    finding_obs = [f.observation for f in assessment.findings]
    assert any("No source code files detected" in obs for obs in finding_obs)


# ── 2. Missing Repository Path ────────────────────────────────────────────────

def test_missing_repository_path_none():
    engine = RepositoryAssessmentEngine(None)
    assessment = engine.build_assessment()

    assert assessment.repo_name == "unknown"
    assert assessment.health.is_clean is False
    assert assessment.health.scanned_file_count == 0
    assert len(assessment.risks) > 0
    assert len(assessment.recommendations) > 0
    assert any("Repository path" in f.observation for f in assessment.findings)


def test_missing_repository_path_nonexistent(tmp_path):
    nonexistent = str(tmp_path / "does_not_exist_12345")
    engine = RepositoryAssessmentEngine(nonexistent)
    assessment = engine.build_assessment()

    assert assessment.health.is_clean is False
    assert assessment.health.scanned_file_count == 0
    assert any("does not exist" in f.observation for f in assessment.findings)


# ── 3. Python Repository - Valid Syntax ───────────────────────────────────────

def test_python_repo_valid_syntax(tmp_path):
    repo = tmp_path / "py_clean"
    repo.mkdir()
    (repo / "main.py").write_text("def hello(name: str) -> str:\n    return f'Hello, {name}'\n")
    sub = repo / "pkg"
    sub.mkdir()
    (sub / "__init__.py").write_text("# init\n")
    (sub / "util.py").write_text("VALUE = 42\n")

    engine = RepositoryAssessmentEngine(str(repo))
    report, findings = engine.assess_code_health()

    assert report.is_clean is True
    assert report.scanned_file_count == 3
    assert len(report.syntax_errors) == 0
    assert len(report.import_errors) == 0
    assert len(report.unparseable_files) == 0
    assert any("compiled without syntax" in f.observation for f in findings)


# ── 4. Python Repository - Syntax Error ───────────────────────────────────────

def test_python_repo_syntax_error(tmp_path):
    repo = tmp_path / "py_broken_syntax"
    repo.mkdir()
    (repo / "broken.py").write_text("def broken_func(\n    print('missing closing paren')\n")

    engine = RepositoryAssessmentEngine(str(repo))
    report, findings = engine.assess_code_health()

    assert report.is_clean is False
    assert len(report.syntax_errors) == 1
    err = report.syntax_errors[0]
    assert err.category == "code_health"
    assert err.severity == "concern"
    assert "broken.py" in err.evidence

    assessment = engine.build_assessment()
    assert any("Code health is compromised" in r for r in assessment.risks)
    assert any("syntax and import errors" in r for r in assessment.recommendations)


# ── 5. Python Repository - Broken Relative Import ─────────────────────────────

def test_python_repo_broken_relative_import(tmp_path):
    repo = tmp_path / "py_broken_import"
    repo.mkdir()
    pkg = repo / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "service.py").write_text("from .nonexistent_module import MissingClass\n")

    engine = RepositoryAssessmentEngine(str(repo))
    report, findings = engine.assess_code_health()

    assert report.is_clean is False
    assert len(report.import_errors) == 1
    err = report.import_errors[0]
    assert "Broken relative import" in err.observation
    assert "service.py" in err.evidence
    assert err.severity == "concern"


# ── 6. Non-Python Repository ──────────────────────────────────────────────────

def test_non_python_repository(tmp_path):
    repo = tmp_path / "js_repo"
    repo.mkdir()
    (repo / "index.js").write_text("function add(a, b) { return a + b; }\nmodule.exports = { add };\n")
    (repo / "types.ts").write_text("export interface User { id: number; name: string; }\n")

    engine = RepositoryAssessmentEngine(str(repo))
    report, findings = engine.assess_code_health()

    assert report.scanned_file_count == 2
    assert report.is_clean is True
    assert len(report.syntax_errors) == 0
    assert len(report.import_errors) == 0


# ── 7. Mixed-Language Repository ──────────────────────────────────────────────

def test_mixed_language_repository(tmp_path):
    repo = tmp_path / "polyglot_repo"
    repo.mkdir()
    (repo / "backend.py").write_text("import os\ndef get_env(): return os.environ.get('PORT')\n")
    (repo / "frontend.js").write_text("const config = { api: '/api' };\n")
    (repo / "main.go").write_text("package main\nimport \"fmt\"\nfunc main() { fmt.Println(\"hi\") }\n")

    engine = RepositoryAssessmentEngine(str(repo))
    report, findings = engine.assess_code_health()

    assert report.scanned_file_count == 3
    assert report.is_clean is True
    assert len(report.syntax_errors) == 0


# ── 8. Dependency Manifest Detection ──────────────────────────────────────────

def test_dependency_manifest_detection_with_lockfile(tmp_path):
    repo = tmp_path / "dep_repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("fastapi>=0.100.0\nuvicorn\npydantic\n# comment\n")
    (repo / "package.json").write_text(json.dumps({
        "name": "my-app",
        "dependencies": {"react": "^18.0.0"},
        "devDependencies": {"typescript": "^5.0.0"}
    }))
    (repo / "package-lock.json").write_text("{}")

    engine = RepositoryAssessmentEngine(str(repo))
    dep_status, findings = engine.assess_dependencies()

    assert dep_status["manifest_count"] == 2
    assert "requirements.txt" in dep_status["manifests_found"]
    assert "package.json" in dep_status["manifests_found"]
    assert "pip" in dep_status["package_managers"]
    assert "npm" in dep_status["package_managers"]
    assert dep_status["has_lockfile"] is True
    assert "package-lock.json" in dep_status["lockfiles_found"]
    assert dep_status["dependency_count"] == 5  # 3 from reqs + 2 from package.json


def test_dependency_manifest_without_lockfile(tmp_path):
    repo = tmp_path / "unlocked_dep_repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("requests==2.28.0\n")

    engine = RepositoryAssessmentEngine(str(repo))
    dep_status, findings = engine.assess_dependencies()

    assert dep_status["manifest_count"] == 1
    assert dep_status["has_lockfile"] is False
    assert any("without corresponding lockfile" in f.observation for f in findings)


# ── 9. Test Framework Detection ───────────────────────────────────────────────

def test_test_framework_detection(tmp_path):
    repo = tmp_path / "test_suite_repo"
    repo.mkdir()
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_main.py").write_text("def test_dummy(): assert True\n")
    (repo / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")

    engine = RepositoryAssessmentEngine(str(repo))
    test_status, findings = engine.assess_testing()

    assert test_status["has_tests"] is True
    assert "tests" in test_status["test_directories"]
    assert test_status["test_file_count"] >= 1
    assert test_status["has_test_config"] is True
    assert any("Automated testing infrastructure detected" in f.observation for f in findings)


def test_no_test_detection(tmp_path):
    repo = tmp_path / "no_tests_repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('no tests')\n")

    engine = RepositoryAssessmentEngine(str(repo))
    test_status, findings = engine.assess_testing()

    assert test_status["has_tests"] is False
    assert test_status["test_file_count"] == 0
    assert any("No automated test suite" in f.observation for f in findings)


# ── 10. Git Repository Detection ──────────────────────────────────────────────

def test_git_repository_detection(tmp_path):
    repo = tmp_path / "git_active_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, capture_output=True, check=True)
    (repo / "file.txt").write_text("initial commit")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)

    engine = RepositoryAssessmentEngine(str(repo))
    git_status, findings = engine.assess_git()

    assert git_status["is_git_repo"] is True
    assert git_status["head_commit"] is not None
    assert git_status["has_history"] is True
    assert git_status["recent_commit_count"] >= 1
    assert any("Git repository active" in f.observation for f in findings)


# ── 11. Non-Git Repository ────────────────────────────────────────────────────

def test_non_git_repository(tmp_path):
    repo = tmp_path / "plain_dir"
    repo.mkdir()
    (repo / "code.py").write_text("x = 1\n")

    engine = RepositoryAssessmentEngine(str(repo))
    git_status, findings = engine.assess_git()

    assert git_status["is_git_repo"] is False
    assert git_status["head_commit"] is None
    assert git_status["has_history"] is False
    assert any("not initialized with Git" in f.observation for f in findings)


# ── 12. README / Documentation Detection ──────────────────────────────────────

def test_documentation_detection_rich(tmp_path):
    repo = tmp_path / "doc_rich_repo"
    repo.mkdir()
    readme_content = (
        "# Sample Project\n\n"
        "## Getting Started & Setup\nRun `pip install -r requirements.txt` to install.\n\n"
        "## Architecture\nThis project follows Clean Architecture with separate domain layers.\n\n"
        "## Deployment\nDeployable using Docker containers and docker-compose.\n"
    )
    (repo / "README.md").write_text(readme_content)

    engine = RepositoryAssessmentEngine(str(repo))
    doc_status, findings = engine.assess_documentation()

    assert doc_status["has_readme"] is True
    assert doc_status["readme_path"] == "README.md"
    assert doc_status["has_setup_instructions"] is True
    assert doc_status["has_architecture_docs"] is True
    assert doc_status["has_deployment_docs"] is True
    assert any("README documentation detected" in f.observation for f in findings)


def test_documentation_detection_minimal(tmp_path):
    repo = tmp_path / "doc_minimal_repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Short\n")  # < 50 bytes

    engine = RepositoryAssessmentEngine(str(repo))
    doc_status, findings = engine.assess_documentation()

    assert doc_status["has_readme"] is True
    assert doc_status["readme_size_bytes"] < 50
    assert any("minimal or placeholder" in f.observation for f in findings)


def test_documentation_detection_missing(tmp_path):
    repo = tmp_path / "doc_missing_repo"
    repo.mkdir()

    engine = RepositoryAssessmentEngine(str(repo))
    doc_status, findings = engine.assess_documentation()

    assert doc_status["has_readme"] is False
    assert any("No README file found" in f.observation for f in findings)


# ── 13. Architecture Comparison & Drift Detection ─────────────────────────────

def test_architecture_matching():
    profile = RepoProfile(
        name="test_proj",
        repo_path="/fake/path",
        architecture_style_observed="Clean Architecture",
        architecture_style_documented="Clean Architecture",
    )
    engine = RepositoryAssessmentEngine("/fake/path", profile=profile)
    observed, documented, drift, findings = engine.assess_architecture()

    assert observed == "Clean Architecture"
    assert documented == "Clean Architecture"
    assert drift is False
    assert any("matches observed structure" in f.observation for f in findings)


def test_architecture_drift():
    profile = RepoProfile(
        name="test_drift",
        repo_path="/fake/path",
        architecture_style_observed="Agent Architecture",
        architecture_style_documented="MVC",
    )
    engine = RepositoryAssessmentEngine("/fake/path", profile=profile)
    observed, documented, drift, findings = engine.assess_architecture()

    assert observed == "Agent Architecture"
    assert documented == "MVC"
    assert drift is True
    drift_finding = next(f for f in findings if "differs from observed" in f.observation)
    assert drift_finding.severity == "concern"


# ── 14. EngineeringAssessment Construction and Serialization ──────────────────

def test_engineering_assessment_construction_and_roundtrip(tmp_path):
    repo = tmp_path / "full_app"
    repo.mkdir()
    (repo / "main.py").write_text("def run(): return 1\n")
    (repo / "README.md").write_text("# Full App\n## Setup\nRun python main.py\n")
    (repo / "requirements.txt").write_text("fastapi\n")

    engine = RepositoryAssessmentEngine(str(repo))
    assessment = engine.build_assessment()

    assert isinstance(assessment, EngineeringAssessment)
    assert assessment.repo_name == "full_app"
    assert assessment.health.is_clean is True
    assert assessment.health.scanned_file_count == 1
    assert assessment.dependency_status["manifest_count"] == 1
    assert len(assessment.findings) > 0

    # Serialization roundtrip test
    data = assessment.to_dict()
    assert isinstance(data, dict)
    json_str = assessment.to_json()
    assert isinstance(json_str, str)

    restored = EngineeringAssessment.from_dict(data)
    assert restored.repo_name == assessment.repo_name
    assert restored.health.is_clean == assessment.health.is_clean
    assert restored.health.scanned_file_count == assessment.health.scanned_file_count
    assert len(restored.findings) == len(assessment.findings)


# ── 15. Detector Failure Does Not Crash Assessment ────────────────────────────

def test_detector_failure_does_not_crash_assessment(tmp_path, monkeypatch):
    repo = tmp_path / "resilient_repo"
    repo.mkdir()
    (repo / "main.py").write_text("x = 1\n")

    engine = RepositoryAssessmentEngine(str(repo))

    # Simulate an unexpected failure in assess_dependencies
    def failing_dep():
        raise RuntimeError("Simulated crash in dependency detector")

    monkeypatch.setattr(engine, "assess_dependencies", failing_dep)

    # Simulation must not crash build_assessment
    assessment = engine.build_assessment()

    assert isinstance(assessment, EngineeringAssessment)
    # Failure should be captured as a finding
    dep_findings = [f for f in assessment.findings if f.category == "dependency"]
    assert any("Dependency assessment encountered an error" in f.observation for f in dep_findings)
    assert any(f.severity == "warning" for f in dep_findings)


# ── 16. Unparseable / Non-UTF8 Binary Files ───────────────────────────────────

def test_unparseable_file_handling(tmp_path):
    repo = tmp_path / "bad_encoding_repo"
    repo.mkdir()
    # Invalid UTF-8 byte sequence with .py extension
    (repo / "corrupt.py").write_bytes(b"\x80\x81\x82\x83\xff\xfe")

    engine = RepositoryAssessmentEngine(str(repo))
    report, findings = engine.assess_code_health()

    assert report.is_clean is False
    assert "corrupt.py" in report.unparseable_files
    assert any("unreadable or unparseable source file" in f.observation for f in findings)


# ── 17. Documentation-Only Repository ─────────────────────────────────────────

def test_docs_only_repository(tmp_path):
    repo = tmp_path / "docs_only"
    repo.mkdir()
    (repo / "README.md").write_text("# Only Documentation\nNo code here.\n")
    docs_dir = repo / "docs"
    docs_dir.mkdir()
    (docs_dir / "index.md").write_text("# Guide\n")

    engine = RepositoryAssessmentEngine(str(repo))
    report, findings = engine.assess_code_health()

    assert report.scanned_file_count == 0
    assert report.is_clean is True
    assert any("No source code files detected" in f.observation for f in findings)
