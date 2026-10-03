"""
Focused regression tests for Canonical Repository Identity.

Requirements verified:
1. The same repository always resolves to the same memory identity
2. Save -> load works cleanly through the canonical identity
3. Invalidation finds records saved by legacy callers after they are updated
4. Repository folder name is not accidentally used as the primary memory key
5. Legacy records remain accessible without silent deletion
"""

import os
import tempfile
import sqlite3
from pathlib import Path
import pytest

from src.helpers.repo import get_canonical_repo_id
from src.memory.sqlite_store import EngineeringMemoryStore
from src.models.repo_profile import RepoProfile
from src.helpers.incremental_change import IncrementalChangeResult
from src.helpers.affected_dimensions import detect_affected_dimensions
from src.helpers.memory_invalidation import invalidate_memory


@pytest.fixture
def temp_store(tmp_path):
    db_file = str(tmp_path / "identity_test_memory.db")
    return EngineeringMemoryStore(db_path=db_file)


def test_canonical_identity_resolution_stability(tmp_path):
    """1. Prove that different representations of the same repo path resolve to the exact same canonical ID."""
    repo_dir = tmp_path / "my_project"
    repo_dir.mkdir()

    canonical_1 = get_canonical_repo_id(str(repo_dir))
    canonical_2 = get_canonical_repo_id(repo_dir)
    canonical_3 = get_canonical_repo_id(str(repo_dir) + "/.")
    canonical_4 = get_canonical_repo_id(str(repo_dir) + "//")

    assert canonical_1 == canonical_2 == canonical_3 == canonical_4
    assert os.path.isabs(canonical_1)

    # Distinct locations with the same folder name resolve to distinct canonical IDs
    other_parent = tmp_path / "other_parent"
    other_parent.mkdir()
    repo_dir_2 = other_parent / "my_project"
    repo_dir_2.mkdir()

    canonical_other = get_canonical_repo_id(repo_dir_2)
    assert canonical_1 != canonical_other
    assert Path(canonical_1).name == Path(canonical_other).name == "my_project"


def test_save_and_load_roundtrip_canonical_identity(temp_store, tmp_path):
    """2. Prove that save -> load works through the canonical identity across all memory tables."""
    repo_dir = tmp_path / "workspace_repo"
    repo_dir.mkdir()
    canonical_id = get_canonical_repo_id(repo_dir)

    # 1. Profile
    profile = RepoProfile(
        name="workspace_repo",
        repo_path=str(repo_dir),
        primary_language="python",
    )
    temp_store.save_repo_profile(profile, repo_id=canonical_id)

    loaded_profile = temp_store.load_repo_profile(canonical_id)
    assert loaded_profile is not None
    assert loaded_profile["name"] == "workspace_repo"
    assert loaded_profile["repo_path"] == str(repo_dir)

    # 2. Decision
    temp_store.save_decision(
        repo_name=canonical_id,
        subject="framework",
        decision="FastAPI",
        rationale="async performance",
        source="observed",
    )
    decisions = temp_store.load_decisions(canonical_id)
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "FastAPI"

    # 3. Investigation
    inv_id = temp_store.save_investigation(
        repo_name=canonical_id,
        problem="Timeout on startup",
        root_cause="Missing event loop init",
        plan="Add lifespan hook",
        result={"files_to_modify": ["src/app.py"]},
    )
    assert inv_id > 0
    investigations = temp_store.load_investigations(canonical_id)
    assert len(investigations) == 1
    assert investigations[0]["root_cause"] == "Missing event loop init"

    # 4. Change record
    temp_store.save_change_record(
        repo_name=canonical_id,
        commit_hash="commit_abc123",
        changed_files=["src/app.py"],
    )
    records = temp_store.load_change_records(canonical_id)
    assert len(records) == 1
    assert records[0]["commit_hash"] == "commit_abc123"

    # 5. Engineering history check
    assert temp_store.has_engineering_history(canonical_id) is True
    assert temp_store.has_engineering_history("/non/existent/path") is False


def test_invalidation_finds_records_from_updated_callers(temp_store, tmp_path):
    """3. Prove that memory invalidation finds records saved by updated callers under canonical identity."""
    repo_dir = tmp_path / "invalidation_repo"
    repo_dir.mkdir()
    canonical_id = get_canonical_repo_id(repo_dir)

    # Seed knowledge using canonical_id (as updated repository_discovery, coder do)
    temp_store.save_decision(
        repo_name=canonical_id,
        subject="source_code",
        decision="Use parser v2",
        rationale="better AST accuracy",
        source="observed",
    )
    temp_store.save_investigation(
        repo_name=canonical_id,
        problem="Parser crash on empty input",
        root_cause="Unhandled None in parser",
        plan="Add None check",
        result={"files_to_modify": ["parser.py"]},
    )

    # Verify initially valid
    pre_decisions = temp_store.load_decisions(canonical_id)
    assert pre_decisions[0]["current_validity"] == "VALID"

    # Create change result for this repo affecting source_code
    change = IncrementalChangeResult(
        repo_id=canonical_id,
        repo_name="invalidation_repo",
        previous_commit="commit1",
        current_commit="commit2",
        changed_files=["src/parser.py"],
        added_files=[],
        modified_files=["src/parser.py"],
        deleted_files=[],
        has_changes=True,
        has_committed_changes=True,
        has_uncommitted_changes=False,
        uncommitted_files=[],
        is_dirty=False,
        is_git_repo=True,
        is_initial_baseline=False,
        is_baseline_stale=False,
        requires_reverification=False,
    )
    dims = detect_affected_dimensions(change)

    # Run invalidation
    result = invalidate_memory(change, dims, temp_store)

    assert result.status == "invalidated"
    assert result.verification_required is True
    assert result.invalidated_count == 2  # 1 decision + 1 investigation

    # Verify records were updated in SQLite
    post_decisions = temp_store.load_decisions(canonical_id)
    assert post_decisions[0]["current_validity"] == "REQUIRES_VERIFICATION"

    post_investigations = temp_store.load_investigations(canonical_id)
    assert post_investigations[0]["current_validity"] == "REQUIRES_VERIFICATION"


def test_folder_name_not_used_as_primary_memory_key(temp_store, tmp_path):
    """4. Prove that folder name is NOT the primary key in SQLite tables."""
    repo_dir = tmp_path / "deep" / "nested" / "my_service"
    repo_dir.mkdir(parents=True)
    canonical_id = get_canonical_repo_id(repo_dir)
    folder_name = repo_dir.name  # "my_service"

    # Save via updated callers
    profile = RepoProfile(name=folder_name, repo_path=str(repo_dir))
    temp_store.save_repo_profile(profile, repo_id=canonical_id)
    temp_store.save_decision(
        repo_name=canonical_id,
        subject="arch",
        decision="microservice",
        rationale="modular",
        source="observed",
    )

    # Query SQLite directly using raw SQL
    with sqlite3.connect(temp_store.db_path) as conn:
        profile_row = conn.execute("SELECT repo_name FROM repo_profiles").fetchone()
        assert profile_row[0] == canonical_id
        assert profile_row[0] != folder_name

        decision_row = conn.execute("SELECT repo_name FROM decisions").fetchone()
        assert decision_row[0] == canonical_id
        assert decision_row[0] != folder_name


def test_legacy_record_compatibility_no_silent_deletion(temp_store):
    """5. Prove that legacy records created with folder names are NOT deleted and remain queryable."""
    legacy_folder_name = "legacy-agent-repo"

    # Directly insert legacy row using raw SQL (simulating pre-Phase-4 data)
    with sqlite3.connect(temp_store.db_path) as conn:
        conn.execute(
            """
            INSERT INTO repo_profiles (repo_name, profile_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                legacy_folder_name,
                '{"name": "legacy-agent-repo", "repo_path": "/tmp/legacy-agent-repo", "primary_language": "python"}',
                "2026-09-01T00:00:00Z",
                "2026-09-01T00:00:00Z",
            ),
        )

    # Verify legacy record still exists and is not deleted
    assert temp_store.repo_profile_exists(legacy_folder_name) is True
    loaded = temp_store.load_repo_profile(legacy_folder_name)
    assert loaded is not None
    assert loaded["name"] == legacy_folder_name

    # Check engineering history detects it
    assert temp_store.has_engineering_history(legacy_folder_name) is True
