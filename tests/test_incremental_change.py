"""
Unit tests for IncrementalChangeDetector (Phase 4.1 + 4.2 Corrective Patch).

Validates:
  A. No engineering history -> is_initial_baseline = True, is_baseline_stale = False
  B. Valid previous commit -> normal committed diff works
  C. Stale previous commit -> is_initial_baseline = False, is_baseline_stale = True, memory preserved, no fake diff
  D. Clean working tree -> is_dirty = False, has_uncommitted_changes = False
  E. Modified uncommitted file -> has_uncommitted_changes = True, in uncommitted_files, not in committed diff
  F. Untracked file -> appears in uncommitted_files, not in committed diff
  G. Repository identity -> memory lookup works using canonical absolute path
  H. Same repo_name, different paths -> histories do not collide
  I. Existing history with no change_record -> is_initial_baseline = False, is_baseline_stale = True
  J. Non-Git directory -> safely handled
  K. Empty/unborn Git repository -> safely handled
  L. Serialization roundtrip with all contract fields
  M. Renamed file tracking
"""

import subprocess
import pytest
from pathlib import Path

from src.helpers.incremental_change import (
    IncrementalChangeDetector,
    IncrementalChangeResult,
)
from src.memory.sqlite_store import EngineeringMemoryStore


def _git_commit(repo_path: Path, msg: str = "commit") -> str:
    """Helper to git add all and commit, returning commit SHA."""
    subprocess.run(["git", "add", "."], cwd=str(repo_path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=str(repo_path), check=True, capture_output=True)
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_path), check=True, capture_output=True, text=True)
    return r.stdout.strip()


@pytest.fixture
def clean_git_repo(tmp_path):
    """Fixture initializing a clean Git repository with one commit."""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True, capture_output=True)
    (repo / "initial.py").write_text("# initial content\n")
    _git_commit(repo, "Initial commit")
    return repo


@pytest.fixture
def memory_store(tmp_path):
    """Fixture providing a temporary SQLite store."""
    db_file = str(tmp_path / "test_memory.db")
    return EngineeringMemoryStore(db_file)


# ── A. No Engineering History ─────────────────────────────────────────────────

def test_no_engineering_history(clean_git_repo, memory_store):
    detector = IncrementalChangeDetector(
        repo_path=str(clean_git_repo),
        memory=memory_store,
    )
    result = detector.detect_changes()

    assert result.is_git_repo is True
    assert result.is_initial_baseline is True
    assert result.is_baseline_stale is False
    assert result.requires_reverification is False
    assert result.has_changes is False
    assert result.has_committed_changes is False
    assert result.has_uncommitted_changes is False
    assert result.is_dirty is False
    assert result.previous_commit is None
    assert result.current_commit is not None
    assert len(result.current_commit) == 40
    assert result.changed_files == []
    assert result.added_files == []
    assert result.modified_files == []
    assert result.deleted_files == []
    assert result.uncommitted_files == []
    assert result.status == "initial_baseline"


# ── B. Valid Previous Commit ──────────────────────────────────────────────────

def test_valid_previous_commit(clean_git_repo):
    detector = IncrementalChangeDetector(str(clean_git_repo))

    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(clean_git_repo), check=True, capture_output=True, text=True)
    c1 = r.stdout.strip()

    (clean_git_repo / "new_module.py").write_text("def new(): pass\n")
    c2 = _git_commit(clean_git_repo, "Add new_module.py")

    result = detector.detect_changes(since_commit=c1)

    assert result.is_git_repo is True
    assert result.is_initial_baseline is False
    assert result.is_baseline_stale is False
    assert result.requires_reverification is False
    assert result.has_committed_changes is True
    assert result.has_uncommitted_changes is False
    assert result.is_dirty is False
    assert result.previous_commit == c1
    assert result.current_commit == c2
    assert "new_module.py" in result.added_files
    assert "new_module.py" in result.changed_files
    assert result.modified_files == []
    assert result.deleted_files == []
    assert result.uncommitted_files == []
    assert result.status == "changed"


# ── C. Stale Previous Commit ──────────────────────────────────────────────────

def test_stale_previous_commit_preserves_memory(clean_git_repo, memory_store):
    detector = IncrementalChangeDetector(
        repo_path=str(clean_git_repo),
        memory=memory_store,
    )

    # Save engineering history into memory store
    memory_store.save_decision(
        repo_name=detector.repo_id,
        subject="Architecture",
        decision="Use modular pattern",
        rationale="Maintainability",
        source="human",
    )
    memory_store.save_repo_profile({
        "name": detector.repo_id,
        "primary_language": "Python",
    })

    # Pass nonexistent/unreachable commit hash
    fake_sha = "0000000000000000000000000000000000000000"
    result = detector.detect_changes(since_commit=fake_sha)

    # Stale baseline semantics
    assert result.is_git_repo is True
    assert result.is_initial_baseline is False
    assert result.is_baseline_stale is True
    assert result.requires_reverification is True
    assert result.status == "stale_baseline"
    assert result.previous_commit == fake_sha
    assert result.current_commit is not None

    # No fake Git diff evidence
    assert result.changed_files == []
    assert result.added_files == []
    assert result.modified_files == []
    assert result.deleted_files == []
    assert result.has_committed_changes is False

    # Historical memory MUST be preserved (never deleted)
    decisions = memory_store.load_decisions(detector.repo_id)
    assert len(decisions) == 1
    assert decisions[0]["subject"] == "Architecture"
    profile = memory_store.load_repo_profile(detector.repo_id)
    assert profile is not None


# ── D. Clean Working Tree ─────────────────────────────────────────────────────

def test_clean_working_tree(clean_git_repo):
    detector = IncrementalChangeDetector(str(clean_git_repo))
    result = detector.detect_changes()

    assert result.is_dirty is False
    assert result.has_uncommitted_changes is False
    assert result.uncommitted_files == []


# ── E. Modified Uncommitted File ──────────────────────────────────────────────

def test_modified_uncommitted_file(clean_git_repo):
    detector = IncrementalChangeDetector(str(clean_git_repo))

    # Obtain HEAD
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(clean_git_repo), check=True, capture_output=True, text=True)
    head_sha = r.stdout.strip()

    # Modify initial.py without committing
    (clean_git_repo / "initial.py").write_text("# modified unstaged\n")

    result = detector.detect_changes(since_commit=head_sha)

    # Working tree is dirty
    assert result.is_dirty is True
    assert result.has_uncommitted_changes is True
    assert "initial.py" in result.uncommitted_files

    # Does NOT become committed change evidence
    assert result.has_committed_changes is False
    assert result.changed_files == []
    assert result.added_files == []
    assert result.modified_files == []
    assert result.deleted_files == []


# ── F. Untracked File ─────────────────────────────────────────────────────────

def test_untracked_file(clean_git_repo):
    detector = IncrementalChangeDetector(str(clean_git_repo))

    # Obtain HEAD
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(clean_git_repo), check=True, capture_output=True, text=True)
    head_sha = r.stdout.strip()

    # Create untracked file without git add
    (clean_git_repo / "untracked.py").write_text("x = 100\n")

    result = detector.detect_changes(since_commit=head_sha)

    # Appears as uncommitted working-tree state
    assert result.is_dirty is True
    assert result.has_uncommitted_changes is True
    assert "untracked.py" in result.uncommitted_files

    # Does NOT become committed history
    assert result.has_committed_changes is False
    assert result.changed_files == []
    assert result.added_files == []
    assert result.modified_files == []
    assert result.deleted_files == []


# ── G. Repository Identity Uses Canonical Path ───────────────────────────────

def test_repository_identity_canonical_path(clean_git_repo, memory_store):
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(clean_git_repo), check=True, capture_output=True, text=True)
    c1 = r.stdout.strip()

    canonical_id = str(clean_git_repo.resolve().absolute())

    # Save change record under canonical repo identity
    memory_store.save_change_record(
        repo_name=canonical_id,
        commit_hash=c1,
        changed_files=["initial.py"],
    )

    # Second commit
    (clean_git_repo / "service.py").write_text("class Service: pass\n")
    c2 = _git_commit(clean_git_repo, "Add service.py")

    detector = IncrementalChangeDetector(
        repo_path=str(clean_git_repo),
        repo_name="display_name_test",
        memory=memory_store,
    )
    result = detector.detect_changes()

    assert result.repo_id == canonical_id
    assert result.repo_name == "display_name_test"
    assert result.previous_commit == c1
    assert result.current_commit == c2
    assert result.has_committed_changes is True
    assert "service.py" in result.added_files


# ── H. Different Paths with Same Repo Name Do Not Collide ──────────────────────

def test_different_paths_same_name_do_not_collide(tmp_path, memory_store):
    # Repo A
    dir_a = tmp_path / "team_alpha" / "shared_app"
    dir_a.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=str(dir_a), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=str(dir_a), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(dir_a), check=True, capture_output=True)
    (dir_a / "a.py").write_text("alpha = 1\n")
    c1_a = _git_commit(dir_a, "Alpha init")

    # Repo B (same repo_name basename "shared_app")
    dir_b = tmp_path / "team_beta" / "shared_app"
    dir_b.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=str(dir_b), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=str(dir_b), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(dir_b), check=True, capture_output=True)
    (dir_b / "b.py").write_text("beta = 1\n")
    _git_commit(dir_b, "Beta init")

    # Save engineering history ONLY for Repo A using canonical path
    id_a = str(dir_a.resolve().absolute())
    memory_store.save_change_record(
        repo_name=id_a,
        commit_hash=c1_a,
        changed_files=["a.py"],
    )

    # Detect changes on Repo A -> finds memory history
    detector_a = IncrementalChangeDetector(str(dir_a), repo_name="shared_app", memory=memory_store)
    res_a = detector_a.detect_changes()
    assert res_a.previous_commit == c1_a
    assert res_a.is_initial_baseline is False

    # Detect changes on Repo B -> no collision, sees brand-new initial baseline
    detector_b = IncrementalChangeDetector(str(dir_b), repo_name="shared_app", memory=memory_store)
    res_b = detector_b.detect_changes()
    assert res_b.is_initial_baseline is True
    assert res_b.previous_commit is None


# ── I. Existing Historical Knowledge with No Change Record ─────────────────────

def test_history_exists_with_no_change_records(clean_git_repo, memory_store):
    detector = IncrementalChangeDetector(
        repo_path=str(clean_git_repo),
        memory=memory_store,
    )

    # Existing repo_profile and decision exist, but no change_record
    memory_store.save_repo_profile({
        "name": detector.repo_id,
        "description": "Existing documented repository",
    })
    memory_store.save_decision(
        repo_name=detector.repo_id,
        subject="Database",
        decision="Use SQLite",
        rationale="Embedded",
        source="architect",
    )

    result = detector.detect_changes()

    # Must NOT look like brand-new repo; historical anchor is stale/unverified
    assert result.is_initial_baseline is False
    assert result.is_baseline_stale is True
    assert result.requires_reverification is True
    assert result.status == "stale_baseline"
    assert result.changed_files == []


# ── J. Non-Git Directory Handled Safely ────────────────────────────────────────

def test_non_git_directory(tmp_path):
    plain_dir = tmp_path / "plain_dir"
    plain_dir.mkdir()
    (plain_dir / "test.py").write_text("x = 1\n")

    detector = IncrementalChangeDetector(str(plain_dir))
    result = detector.detect_changes()

    assert result.is_git_repo is False
    assert result.has_changes is False
    assert result.has_committed_changes is False
    assert result.has_uncommitted_changes is False
    assert result.status == "non_git"


# ── K. Empty / Unborn Git Repository ──────────────────────────────────────────

def test_empty_unborn_git_repository(tmp_path):
    empty_repo = tmp_path / "unborn_repo"
    empty_repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(empty_repo), check=True, capture_output=True)

    detector = IncrementalChangeDetector(str(empty_repo))
    result = detector.detect_changes()

    assert result.is_git_repo is True
    assert result.is_initial_baseline is True
    assert result.is_baseline_stale is False
    assert result.requires_reverification is False
    assert result.current_commit is None
    assert result.previous_commit is None
    assert result.changed_files == []
    assert result.status == "unborn_head"


# ── L. IncrementalChangeResult Serialization Roundtrip ────────────────────────

def test_change_result_serialization():
    original = IncrementalChangeResult(
        repo_id="/canonical/path/to/repo",
        repo_name="repo_display",
        previous_commit="aaaabbbbcccc1111222233334444555566667777",
        current_commit="8888999900001111222233334444555566667777",
        changed_files=["a.py", "b.py"],
        added_files=["a.py"],
        modified_files=["b.py"],
        deleted_files=[],
        has_changes=True,
        has_committed_changes=True,
        has_uncommitted_changes=True,
        uncommitted_files=["uncommitted.py"],
        is_dirty=True,
        is_git_repo=True,
        is_initial_baseline=False,
        is_baseline_stale=False,
        requires_reverification=False,
        status="changed",
    )

    data = original.to_dict()
    assert isinstance(data, dict)
    assert data["has_committed_changes"] is True
    assert data["has_uncommitted_changes"] is True
    assert data["repo_id"] == "/canonical/path/to/repo"
    assert data["uncommitted_files"] == ["uncommitted.py"]

    json_str = original.to_json()
    assert isinstance(json_str, str)

    restored = IncrementalChangeResult.from_dict(data)
    assert restored.repo_id == original.repo_id
    assert restored.repo_name == original.repo_name
    assert restored.previous_commit == original.previous_commit
    assert restored.current_commit == original.current_commit
    assert restored.changed_files == original.changed_files
    assert restored.added_files == original.added_files
    assert restored.modified_files == original.modified_files
    assert restored.deleted_files == original.deleted_files
    assert restored.has_changes == original.has_changes
    assert restored.has_committed_changes == original.has_committed_changes
    assert restored.has_uncommitted_changes == original.has_uncommitted_changes
    assert restored.uncommitted_files == original.uncommitted_files
    assert restored.is_dirty == original.is_dirty
    assert restored.is_git_repo == original.is_git_repo
    assert restored.is_initial_baseline == original.is_initial_baseline
    assert restored.is_baseline_stale == original.is_baseline_stale
    assert restored.requires_reverification == original.requires_reverification
    assert restored.status == original.status


# ── M. Renamed File Tracking ──────────────────────────────────────────────────

def test_renamed_file_tracking(clean_git_repo):
    detector = IncrementalChangeDetector(str(clean_git_repo))

    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(clean_git_repo), check=True, capture_output=True, text=True)
    c1 = r.stdout.strip()

    # Rename file via git mv
    subprocess.run(["git", "mv", "initial.py", "renamed.py"], cwd=str(clean_git_repo), check=True, capture_output=True)
    c2 = _git_commit(clean_git_repo, "Rename initial.py to renamed.py")

    result = detector.detect_changes(since_commit=c1)

    assert result.has_committed_changes is True
    assert "initial.py" in result.deleted_files
    assert "renamed.py" in result.added_files
    assert "initial.py" in result.changed_files
    assert "renamed.py" in result.changed_files
