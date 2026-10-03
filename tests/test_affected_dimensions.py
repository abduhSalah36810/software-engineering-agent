"""
Phase 4.3 — Affected Engineering Dimensions Unit & Regression Test Suite.

Verifies deterministic mapping of file path changes to affected engineering dimensions.
Covers all 20 specific test scenarios:
  1. requirements.txt -> dependencies
  2. package.json -> dependencies
  3. tests/test_example.py -> tests
  4. README.md -> documentation
  5. docs/example.md -> documentation
  6. .github/workflows/test.yml -> ci_cd
  7. Dockerfile -> deployment
  8. docker-compose.yml -> deployment
  9. config/application.yml -> configuration
  10. src/service.py -> source_code
  11. A file that matches multiple dimensions -> all justified dimensions returned
  12. Unknown/unrecognized file -> no fabricated dimension
  13. Added file -> correctly classified
  14. Modified file -> correctly classified
  15. Deleted file -> correctly classified using the path evidence
  16. Rename -> both old/new paths are handled correctly
  17. Committed and uncommitted changes remain separated
  18. Multiple committed files affect multiple dimensions
  19. Empty change set -> empty affected dimensions
  20. Deterministic result ordering
Plus:
  - Serialization / deserialization roundtrip
  - Integration with IncrementalChangeResult and IncrementalChangeDetector
"""

import json
from pathlib import Path
import pytest
import subprocess

from src.helpers.affected_dimensions import (
    AffectedDimension,
    AffectedDimensionsResult,
    AffectedDimensionClassifier,
    detect_affected_dimensions,
)
from src.helpers.incremental_change import (
    IncrementalChangeResult,
    IncrementalChangeDetector,
)


@pytest.fixture
def classifier():
    return AffectedDimensionClassifier()


# ─── Tests 1 to 10: Standard Path Mapping ─────────────────────────────────────

def test_01_requirements_txt(classifier):
    """1. requirements.txt -> dependencies"""
    res = classifier.classify(["requirements.txt"])
    assert "dependencies" in res.committed_affected_dimensions
    dim = res.get_committed_dimension("dependencies")
    assert "requirements.txt" in dim.evidence_files
    assert any("requirements.txt" in r for r in dim.reasons)


def test_02_package_json(classifier):
    """2. package.json -> dependencies"""
    res = classifier.classify(["package.json"])
    assert "dependencies" in res.committed_affected_dimensions
    dim = res.get_committed_dimension("dependencies")
    assert "package.json" in dim.evidence_files


def test_03_test_file(classifier):
    """3. tests/test_example.py -> tests"""
    res = classifier.classify(["tests/test_example.py"])
    assert "tests" in res.committed_affected_dimensions
    # Test files should NOT be marked as regular source_code
    assert "source_code" not in res.committed_affected_dimensions
    dim = res.get_committed_dimension("tests")
    assert "tests/test_example.py" in dim.evidence_files


def test_04_readme(classifier):
    """4. README.md -> documentation"""
    res = classifier.classify(["README.md"])
    assert "documentation" in res.committed_affected_dimensions
    dim = res.get_committed_dimension("documentation")
    assert "README.md" in dim.evidence_files


def test_05_docs_dir(classifier):
    """5. docs/example.md -> documentation"""
    res = classifier.classify(["docs/example.md"])
    assert "documentation" in res.committed_affected_dimensions
    dim = res.get_committed_dimension("documentation")
    assert "docs/example.md" in dim.evidence_files


def test_06_github_workflow(classifier):
    """6. .github/workflows/test.yml -> ci_cd (and configuration)"""
    res = classifier.classify([".github/workflows/test.yml"])
    assert "ci_cd" in res.committed_affected_dimensions
    dim = res.get_committed_dimension("ci_cd")
    assert ".github/workflows/test.yml" in dim.evidence_files


def test_07_dockerfile(classifier):
    """7. Dockerfile -> deployment"""
    res = classifier.classify(["Dockerfile"])
    assert "deployment" in res.committed_affected_dimensions
    dim = res.get_committed_dimension("deployment")
    assert "Dockerfile" in dim.evidence_files


def test_08_docker_compose(classifier):
    """8. docker-compose.yml -> deployment (and configuration)"""
    res = classifier.classify(["docker-compose.yml"])
    assert "deployment" in res.committed_affected_dimensions
    dim = res.get_committed_dimension("deployment")
    assert "docker-compose.yml" in dim.evidence_files


def test_09_config_directory(classifier):
    """9. config/application.yml -> configuration"""
    res = classifier.classify(["config/application.yml"])
    assert "configuration" in res.committed_affected_dimensions
    dim = res.get_committed_dimension("configuration")
    assert "config/application.yml" in dim.evidence_files


def test_10_source_code(classifier):
    """10. src/service.py -> source_code"""
    res = classifier.classify(["src/service.py"])
    assert "source_code" in res.committed_affected_dimensions
    assert "tests" not in res.committed_affected_dimensions
    dim = res.get_committed_dimension("source_code")
    assert "src/service.py" in dim.evidence_files


# ─── Test 11: Multi-Dimension Justification ───────────────────────────────────

def test_11_multiple_dimensions_per_file(classifier):
    """11. A file that matches multiple dimensions -> all justified dimensions returned."""
    # pyproject.toml is both a dependency manifest and project configuration
    res = classifier.classify(["pyproject.toml"])
    dims = res.committed_affected_dimensions
    assert "dependencies" in dims
    assert "configuration" in dims

    # docker-compose.yml is both deployment orchestration and configuration
    res_compose = classifier.classify(["docker-compose.yml"])
    assert "deployment" in res_compose.committed_affected_dimensions
    assert "configuration" in res_compose.committed_affected_dimensions

    # .github/workflows/ci.yml is both ci_cd and configuration
    res_ci = classifier.classify([".github/workflows/ci.yml"])
    assert "ci_cd" in res_ci.committed_affected_dimensions
    assert "configuration" in res_ci.committed_affected_dimensions


# ─── Test 12: Unknown / Unrecognized Files ────────────────────────────────────

def test_12_unknown_file_not_fabricated(classifier):
    """12. Unknown/unrecognized file -> no fabricated dimension."""
    unknown_paths = ["binary_blob.bin", "custom_data.proprietary", "notes.random"]
    res = classifier.classify(unknown_paths)
    assert res.committed == []
    assert res.committed_affected_dimensions == []
    assert res.unknown_files == sorted(unknown_paths)


# ─── Tests 13, 14, 15: Added, Modified, Deleted Files ─────────────────────────

def test_13_added_file_classification(classifier):
    """13. Added file -> correctly classified."""
    change = IncrementalChangeResult(
        changed_files=["src/new_handler.py"],
        added_files=["src/new_handler.py"],
        modified_files=[],
        deleted_files=[],
    )
    res = classifier.classify_change_result(change)
    assert "source_code" in res.committed_affected_dimensions
    dim = res.get_committed_dimension("source_code")
    assert "src/new_handler.py" in dim.evidence_files
    assert any("added" in r for r in dim.reasons)


def test_14_modified_file_classification(classifier):
    """14. Modified file -> correctly classified."""
    change = IncrementalChangeResult(
        changed_files=["requirements.txt"],
        added_files=[],
        modified_files=["requirements.txt"],
        deleted_files=[],
    )
    res = classifier.classify_change_result(change)
    assert "dependencies" in res.committed_affected_dimensions
    dim = res.get_committed_dimension("dependencies")
    assert "requirements.txt" in dim.evidence_files


def test_15_deleted_file_classification(classifier):
    """15. Deleted file -> correctly classified using the path evidence."""
    change = IncrementalChangeResult(
        changed_files=["tests/test_legacy.py"],
        added_files=[],
        modified_files=[],
        deleted_files=["tests/test_legacy.py"],
    )
    res = classifier.classify_change_result(change)
    assert "tests" in res.committed_affected_dimensions
    dim = res.get_committed_dimension("tests")
    assert "tests/test_legacy.py" in dim.evidence_files
    assert any("deleted" in r for r in dim.reasons)


# ─── Test 16: Renames and Structural Movement ────────────────────────────────

def test_16_rename_and_movement_classified(classifier):
    """16. Rename -> both old/new paths are handled correctly and repository_structure triggered."""
    change = IncrementalChangeResult(
        changed_files=["src/old_pkg/util.py", "lib/new_pkg/util.py"],
        added_files=["lib/new_pkg/util.py"],
        modified_files=[],
        deleted_files=["src/old_pkg/util.py"],
    )
    res = classifier.classify_change_result(change)
    dims = res.committed_affected_dimensions
    assert "source_code" in dims
    assert "repository_structure" in dims
    struct_dim = res.get_committed_dimension("repository_structure")
    assert any("File moved across structural boundaries" in r for r in struct_dim.reasons)


# ─── Test 17: Separation of Committed and Uncommitted ─────────────────────────

def test_17_committed_and_uncommitted_separated(classifier):
    """17. Committed and uncommitted changes remain separated."""
    change = IncrementalChangeResult(
        changed_files=["requirements.txt", "src/service.py"],
        added_files=["src/service.py"],
        modified_files=["requirements.txt"],
        deleted_files=[],
        uncommitted_files=["tests/test_service.py", ".env.local"],
        has_committed_changes=True,
        has_uncommitted_changes=True,
    )
    res = classifier.classify_change_result(change)

    # Committed dimensions ONLY contain dependencies and source_code
    assert res.committed_affected_dimensions == ["dependencies", "source_code"]
    assert "tests" not in res.committed_affected_dimensions
    assert "configuration" not in res.committed_affected_dimensions

    # Uncommitted dimensions ONLY contain configuration and tests
    assert res.uncommitted_affected_dimensions == ["configuration", "tests"]
    assert "dependencies" not in res.uncommitted_affected_dimensions
    assert "source_code" not in res.uncommitted_affected_dimensions

    # All dimensions union
    assert res.all_affected_dimensions == ["configuration", "dependencies", "source_code", "tests"]


# ─── Test 18: Multiple Committed Files ────────────────────────────────────────

def test_18_multiple_committed_files_multi_dimensions(classifier):
    """18. Multiple committed files affect multiple dimensions."""
    files = [
        "requirements.txt",
        "README.md",
        "src/main.py",
        "tests/test_main.py",
        "Dockerfile",
        ".github/workflows/ci.yml",
    ]
    res = classifier.classify(files)
    dims = res.committed_affected_dimensions
    assert "dependencies" in dims
    assert "documentation" in dims
    assert "source_code" in dims
    assert "tests" in dims
    assert "deployment" in dims
    assert "ci_cd" in dims


# ─── Test 19: Empty Change Set ────────────────────────────────────────────────

def test_19_empty_change_set(classifier):
    """19. Empty change set -> empty affected dimensions."""
    change = IncrementalChangeResult(
        changed_files=[],
        added_files=[],
        modified_files=[],
        deleted_files=[],
        uncommitted_files=[],
    )
    res = classifier.classify_change_result(change)
    assert res.committed == []
    assert res.uncommitted == []
    assert res.committed_affected_dimensions == []
    assert res.uncommitted_affected_dimensions == []
    assert res.all_affected_dimensions == []
    assert res.unknown_files == []


# ─── Test 20: Deterministic Ordering ─────────────────────────────────────────

def test_20_deterministic_ordering(classifier):
    """20. Deterministic result ordering."""
    files = [
        "tests/test_z.py",
        "tests/test_a.py",
        "src/z.py",
        "src/a.py",
        "requirements.txt",
    ]
    res = classifier.classify(files)
    # Dimensions sorted alphabetically
    assert res.committed_affected_dimensions == sorted(res.committed_affected_dimensions)

    # Files inside each dimension sorted
    for dim in res.committed:
        assert dim.evidence_files == sorted(dim.evidence_files)
        assert dim.reasons == sorted(dim.reasons)


# ─── Serialization & Deserialization ──────────────────────────────────────────

def test_serialization_roundtrip(classifier):
    """AffectedDimension and AffectedDimensionsResult serialize/deserialize cleanly."""
    dim = AffectedDimension(
        dimension="dependencies",
        evidence_files=["requirements.txt", "package.json"],
        reasons=["requirements.txt changed", "package.json changed"],
    )
    d_dict = dim.to_dict()
    dim_restored = AffectedDimension.from_dict(d_dict)
    assert dim_restored.dimension == "dependencies"
    assert dim_restored.evidence_files == ["package.json", "requirements.txt"]

    res = AffectedDimensionsResult(
        committed=[dim],
        uncommitted=[],
        unknown_files=["unknown.bin"],
        committed_unknown_files=["unknown.bin"],
        uncommitted_unknown_files=[],
    )
    res_json = res.to_json()
    res_restored = AffectedDimensionsResult.from_dict(json.loads(res_json))
    assert res_restored.committed_affected_dimensions == ["dependencies"]
    assert res_restored.unknown_files == ["unknown.bin"]


# ─── Architecture Dimension (Conservative) ────────────────────────────────────

def test_architecture_boundary_added(classifier):
    """Architecture dimension triggered strictly when a new service boundary is added."""
    change = IncrementalChangeResult(
        changed_files=["services/auth_service/server.py"],
        added_files=["services/auth_service/server.py"],
        modified_files=[],
        deleted_files=[],
    )
    res = classifier.classify_change_result(change)
    assert "architecture" in res.committed_affected_dimensions
    assert "repository_structure" in res.committed_affected_dimensions
    arch_dim = res.get_committed_dimension("architecture")
    assert any("New top-level service boundary added: services/auth_service" in r for r in arch_dim.reasons)


def test_regular_code_change_does_not_trigger_architecture(classifier):
    """Normal source code changes do NOT falsely manufacture an architecture dimension."""
    change = IncrementalChangeResult(
        changed_files=["src/models/user.py"],
        added_files=[],
        modified_files=["src/models/user.py"],
        deleted_files=[],
    )
    res = classifier.classify_change_result(change)
    assert "source_code" in res.committed_affected_dimensions
    assert "architecture" not in res.committed_affected_dimensions
    assert "repository_structure" not in res.committed_affected_dimensions


# ─── End-to-End Real Git Repo Detection ───────────────────────────────────────

def test_git_repo_incremental_affected_dimensions(tmp_path):
    """IncrementalChangeDetector end-to-end creates correct AffectedDimensionsResult."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # Init git repo
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)

    # Initial commit
    (repo_dir / "README.md").write_text("Initial")
    (repo_dir / "requirements.txt").write_text("requests==2.28.0\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True)
    c1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True, capture_output=True, text=True).stdout.strip()

    # Second commit: add source file and tests
    (repo_dir / "service.py").write_text("print('hello')\n")
    test_dir = repo_dir / "tests"
    test_dir.mkdir()
    (test_dir / "test_service.py").write_text("assert True\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Add service and tests"], cwd=repo_dir, check=True)

    # Uncommitted change in working tree
    (repo_dir / "Dockerfile").write_text("FROM python:3.11\n")

    detector = IncrementalChangeDetector(str(repo_dir))
    affected = detector.detect_affected_dimensions(since_commit=c1)

    # Committed changes (c1 -> HEAD): service.py (source_code) and tests/test_service.py (tests)
    assert "source_code" in affected.committed_affected_dimensions
    assert "tests" in affected.committed_affected_dimensions
    assert "deployment" not in affected.committed_affected_dimensions

    # Uncommitted change (Dockerfile -> deployment)
    assert "deployment" in affected.uncommitted_affected_dimensions
    assert "source_code" not in affected.uncommitted_affected_dimensions
