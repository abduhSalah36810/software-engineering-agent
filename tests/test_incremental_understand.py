"""
Phase 4.4 — Incremental Understand Again Tests.

Tests A–J as specified in Phase 4.4 requirements:
  A. No changes → no_changes → no unnecessary re-understanding.
  B. Committed code change → affected dimensions → only affected dimensions recomputed.
  C. Uncommitted change → session-scoped → no permanent SQLite validity rewrite.
  D. Stale baseline → stale → broad verification → no fabricated diff.
  E. Unaffected memory → unaffected knowledge remains preserved.
  F. Direct deterministic confirmation → REQUIRES_VERIFICATION → VALID ONLY when evidence supports it.
  G. Insufficient evidence → REQUIRES_VERIFICATION remains REQUIRES_VERIFICATION.
  H. Historical integrity → old records are never deleted.
  I. Canonical identity → repo_id = canonical absolute path used throughout.
  J. Dimension recomputation does NOT automatically validate unrelated historical decisions.
"""

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
import pytest

from src.helpers.repo import get_canonical_repo_id
from src.memory.sqlite_store import EngineeringMemoryStore
from src.models.repo_profile import RepoProfile
from src.helpers.incremental_change import IncrementalChangeResult
from src.helpers.affected_dimensions import detect_affected_dimensions, AffectedDimensionsResult, AffectedDimension
from src.helpers.memory_invalidation import invalidate_memory, MemoryInvalidationResult, InvalidatedItem
from src.helpers.incremental_understand import (
    IncrementalUnderstandEngine,
    understand_again,
    IncrementalUnderstandResult,
    ReunderstoodDimension,
)


@pytest.fixture
def store(tmp_path):
    db_file = str(tmp_path / "understand_test_memory.db")
    return EngineeringMemoryStore(db_path=db_file)


@pytest.fixture
def mock_repo(tmp_path):
    """Creates a realistic small git/python repository."""
    repo_dir = tmp_path / "sample_project"
    repo_dir.mkdir()

    # Python source
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    (src_dir / "__init__.py").write_text("")
    (src_dir / "app.py").write_text("def hello():\n    return 'world'\n")

    # Tests
    tests_dir = repo_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")
    (tests_dir / "test_app.py").write_text("def test_hello():\n    assert True\n")
    (repo_dir / "pytest.ini").write_text("[pytest]\n")

    # Dependencies
    (repo_dir / "requirements.txt").write_text("pytest>=7.0.0\nfastapi>=0.100.0\n")

    # Documentation
    (repo_dir / "README.md").write_text("# Sample Project\n\nA demo app.\n")

    return repo_dir


def _make_change(
    repo_id: str,
    changed_files: list[str] | None = None,
    uncommitted_files: list[str] | None = None,
    has_committed: bool = False,
    has_uncommitted: bool = False,
    is_initial_baseline: bool = False,
    is_baseline_stale: bool = False,
    requires_reverification: bool = False,
) -> IncrementalChangeResult:
    return IncrementalChangeResult(
        repo_id=repo_id,
        repo_name=Path(repo_id).name,
        previous_commit="commit_1",
        current_commit="commit_2",
        changed_files=changed_files or [],
        added_files=[],
        modified_files=changed_files or [],
        deleted_files=[],
        has_changes=bool(changed_files or uncommitted_files),
        has_committed_changes=has_committed,
        has_uncommitted_changes=has_uncommitted,
        uncommitted_files=uncommitted_files or [],
        is_dirty=has_uncommitted,
        is_git_repo=True,
        is_initial_baseline=is_initial_baseline,
        is_baseline_stale=is_baseline_stale,
        requires_reverification=requires_reverification,
    )


# ── Test A: No changes ────────────────────────────────────────────────────────


def test_A_no_changes_produces_no_reunderstanding(store, mock_repo):
    """A. When no changes exist, status is no_changes and no unnecessary recomputation occurs."""
    canonical_id = get_canonical_repo_id(mock_repo)
    change = _make_change(canonical_id, has_committed=False, has_uncommitted=False)
    dims = detect_affected_dimensions(change)
    inv = invalidate_memory(change, dims, store)

    result = understand_again(change, dims, inv, repo_path=mock_repo, memory=store)

    assert result.status == "no_changes"
    assert result.recomputed_dimensions == []
    assert len(result.preserved_dimensions) == 9
    assert result.revalidated_records == []
    assert result.unresolved_records == []
    assert result.deterministic_processing_complete is True


# ── Test B: Committed code change ─────────────────────────────────────────────


def test_B_committed_code_change_recomputes_only_affected_dimensions(store, mock_repo):
    """B. Only affected dimensions are recomputed; unaffected dimensions are preserved."""
    canonical_id = get_canonical_repo_id(mock_repo)
    # Only a test file changed
    change = _make_change(
        canonical_id,
        changed_files=["tests/test_app.py"],
        has_committed=True,
    )
    dims = detect_affected_dimensions(change)
    assert dims.all_affected_dimensions == ["tests"]

    inv = invalidate_memory(change, dims, store)
    result = understand_again(change, dims, inv, repo_path=mock_repo, memory=store)

    assert result.status == "reunderstood"
    assert result.recomputed_dimensions == ["tests"]
    assert "tests" not in result.preserved_dimensions
    assert "documentation" in result.preserved_dimensions
    assert "dependencies" in result.preserved_dimensions
    assert "source_code" in result.preserved_dimensions
    assert result.deterministic_processing_complete is True


# ── Test C: Uncommitted change ────────────────────────────────────────────────


def test_C_uncommitted_change_does_not_permanently_rewrite_sqlite(store, mock_repo):
    """C. Uncommitted changes produce session-scoped understanding without permanent SQLite writes."""
    canonical_id = get_canonical_repo_id(mock_repo)

    # Seed a decision and verify initial VALID state
    store.save_decision(
        repo_name=canonical_id,
        subject="testing",
        decision="pytest",
        rationale="test runner",
        source="observed",
    )
    initial_dec = store.load_decisions(canonical_id)[0]
    assert initial_dec["current_validity"] == "VALID"

    # Simulate uncommitted working-tree change
    change = _make_change(
        canonical_id,
        uncommitted_files=["tests/test_app.py"],
        has_committed=False,
        has_uncommitted=True,
    )
    dims = detect_affected_dimensions(change)
    inv = invalidate_memory(change, dims, store)

    # Invalidation should not write to SQLite for uncommitted
    mid_dec = store.load_decisions(canonical_id)[0]
    assert mid_dec["current_validity"] == "VALID"

    # Understand again
    result = understand_again(change, dims, inv, repo_path=mock_repo, memory=store)

    # Result captures session understanding
    assert result.status == "reunderstood"
    assert "tests" in result.recomputed_dimensions

    # SQLite validity remains pristine (not modified)
    final_dec = store.load_decisions(canonical_id)[0]
    assert final_dec["current_validity"] == "VALID"


# ── Test D: Stale baseline ────────────────────────────────────────────────────


def test_D_stale_baseline_triggers_broad_verification_without_fabricated_diff(store, mock_repo):
    """D. Stale baselines preserve STALE without pretending specific dimensions were verified."""
    canonical_id = get_canonical_repo_id(mock_repo)

    # Seed knowledge and invalidate under stale baseline
    store.save_decision(
        repo_name=canonical_id,
        subject="testing",
        decision="pytest",
        rationale="tests",
        source="observed",
    )
    change = _make_change(
        canonical_id,
        is_baseline_stale=True,
        requires_reverification=True,
    )
    dims = detect_affected_dimensions(change)
    inv = invalidate_memory(change, dims, store)

    # Invalidation sets current_validity to STALE
    assert inv.status == "stale_baseline"
    stale_dec = store.load_decisions(canonical_id)[0]
    assert stale_dec["current_validity"] == "STALE"

    # Understand again under stale baseline
    result = understand_again(change, dims, inv, repo_path=mock_repo, memory=store)

    assert result.status == "stale_baseline"
    assert result.recomputed_dimensions == []
    assert len(result.revalidated_records) == 0
    assert len(result.unresolved_records) == 1
    assert result.unresolved_records[0]["validity"] == "STALE"
    assert result.deterministic_processing_complete is False

    # The SQLite record remains STALE (never fabricated to VALID)
    post_dec = store.load_decisions(canonical_id)[0]
    assert post_dec["current_validity"] == "STALE"


# ── Test E: Unaffected memory preserved ───────────────────────────────────────


def test_E_unaffected_memory_remains_preserved(store, mock_repo):
    """E. Unaffected knowledge (such as investigations when only documentation changes) remains VALID."""
    canonical_id = get_canonical_repo_id(mock_repo)

    # Seed an investigation (which documentation changes do not target in invalidation)
    inv_id = store.save_investigation(
        repo_name=canonical_id,
        problem="Known issue in parser",
        root_cause="boundary condition",
        plan="check bounds",
        result={"files": ["src/app.py"]},
    )
    initial_inv = store.load_investigations(canonical_id)[0]
    assert initial_inv["current_validity"] == "VALID"

    # Also seed a decision for another repo
    other_repo_id = "/tmp/other_unaffected_repo"
    store.save_decision(
        repo_name=other_repo_id,
        subject="framework",
        decision="FastAPI",
        rationale="fast",
        source="observed",
    )

    # Only documentation changes in mock_repo
    change = _make_change(
        canonical_id,
        changed_files=["README.md"],
        has_committed=True,
    )
    dims = detect_affected_dimensions(change)
    assert dims.all_affected_dimensions == ["documentation"]

    inv = invalidate_memory(change, dims, store)
    result = understand_again(change, dims, inv, repo_path=mock_repo, memory=store)

    # The investigation in mock_repo was not affected -> remains VALID
    final_inv = store.load_investigations(canonical_id)[0]
    assert final_inv["current_validity"] == "VALID"

    # The decision in other_repo was unaffected -> remains VALID
    other_dec = store.load_decisions(other_repo_id)[0]
    assert other_dec["current_validity"] == "VALID"


# ── Test F: Direct deterministic confirmation ─────────────────────────────────


def test_F_direct_deterministic_confirmation_promotes_to_valid(store, mock_repo):
    """F. REQUIRES_VERIFICATION returns to VALID when newly computed deterministic evidence directly proves it."""
    canonical_id = get_canonical_repo_id(mock_repo)

    # Decision on testing framework
    store.save_decision(
        repo_name=canonical_id,
        subject="testing",
        decision="pytest",
        rationale="test runner",
        source="observed",
    )

    # Committed change affecting tests
    change = _make_change(
        canonical_id,
        changed_files=["tests/test_app.py"],
        has_committed=True,
    )
    dims = detect_affected_dimensions(change)
    inv = invalidate_memory(change, dims, store)

    # Invalidation sets it to REQUIRES_VERIFICATION
    invalidated_dec = store.load_decisions(canonical_id)[0]
    assert invalidated_dec["current_validity"] == "REQUIRES_VERIFICATION"

    # Understand again finds pytest.ini and pytest in requirements.txt -> directly confirms!
    result = understand_again(change, dims, inv, repo_path=mock_repo, memory=store)

    assert result.status == "reunderstood"
    assert len(result.revalidated_records) == 1
    assert result.revalidated_records[0]["new_validity"] == "VALID"
    assert "confirmed" in result.revalidated_records[0]["reason"].lower()

    # Verify SQLite was updated to VALID
    final_dec = store.load_decisions(canonical_id)[0]
    assert final_dec["current_validity"] == "VALID"


# ── Test G: Insufficient evidence ─────────────────────────────────────────────


def test_G_insufficient_evidence_leaves_requires_verification(store, mock_repo):
    """G. A decision whose truth cannot be deterministically proven remains REQUIRES_VERIFICATION."""
    canonical_id = get_canonical_repo_id(mock_repo)

    # Complex architectural decision that cannot be proven by simple manifest/syntax scan
    store.save_decision(
        repo_name=canonical_id,
        subject="architecture",
        decision="Split into hexagonal ports and adapters across core domain",
        rationale="Design discussion in PR #42",
        source="inferred",
    )

    # Change affecting architecture
    change = _make_change(
        canonical_id,
        changed_files=["src/app.py"],
        has_committed=True,
    )
    dims = AffectedDimensionsResult(
        committed=[AffectedDimension(
            dimension="architecture",
            evidence_files=["src/app.py"],
            reasons=["Source modification potentially affects architecture"],
        )],
        uncommitted=[],
    )
    inv = invalidate_memory(change, dims, store)

    # Invalidation flags it
    assert store.load_decisions(canonical_id)[0]["current_validity"] == "REQUIRES_VERIFICATION"

    # Understand again cannot prove "hexagonal ports and adapters" -> remains REQUIRES_VERIFICATION
    result = understand_again(change, dims, inv, repo_path=mock_repo, memory=store)

    assert len(result.revalidated_records) == 0
    assert len(result.unresolved_records) == 1
    assert result.unresolved_records[0]["validity"] == "REQUIRES_VERIFICATION"
    assert "insufficient" in result.unresolved_records[0]["reason"].lower()

    # SQLite record remains REQUIRES_VERIFICATION
    final_dec = store.load_decisions(canonical_id)[0]
    assert final_dec["current_validity"] == "REQUIRES_VERIFICATION"


# ── Test H: Historical integrity ──────────────────────────────────────────────


def test_H_historical_records_are_never_deleted(store, mock_repo):
    """H. Historical decisions and investigations are NEVER deleted during re-understanding."""
    canonical_id = get_canonical_repo_id(mock_repo)

    store.save_decision(repo_name=canonical_id, subject="lang", decision="python", rationale="docs", source="observed")
    store.save_decision(repo_name=canonical_id, subject="db", decision="sqlite", rationale="local", source="observed")
    store.save_investigation(
        repo_name=canonical_id,
        problem="Crash on parse",
        root_cause="syntax err",
        plan="fix syntax",
        result={"files": ["src/app.py"]},
    )

    # Initial count
    assert len(store.load_decisions(canonical_id)) == 2
    assert len(store.load_investigations(canonical_id)) == 1

    # Run cycle
    change = _make_change(canonical_id, changed_files=["src/app.py"], has_committed=True)
    dims = detect_affected_dimensions(change)
    inv = invalidate_memory(change, dims, store)
    understand_again(change, dims, inv, repo_path=mock_repo, memory=store)

    # Record counts in SQLite MUST BE IDENTICAL
    assert len(store.load_decisions(canonical_id)) == 2
    assert len(store.load_investigations(canonical_id)) == 1


# ── Test I: Canonical repository identity ─────────────────────────────────────


def test_I_canonical_identity_used_throughout(store, mock_repo):
    """I. Canonical identity (resolved absolute path) is used everywhere in understand_again."""
    canonical_id = get_canonical_repo_id(mock_repo)
    folder_name = mock_repo.name

    change = _make_change(canonical_id, changed_files=["src/app.py"], has_committed=True)
    dims = detect_affected_dimensions(change)
    inv = invalidate_memory(change, dims, store)

    result = understand_again(change, dims, inv, repo_path=mock_repo, memory=store)

    assert result.repo_id == canonical_id
    assert result.repo_id != folder_name
    assert os.path.isabs(result.repo_id)


# ── Test J: Dimension recomputation != memory record revalidation ─────────────


def test_J_dimension_recomputation_does_not_automatically_validate_records(store, mock_repo):
    """J. CRITICAL: Recomputing a dimension does NOT automatically promote its records to VALID."""
    canonical_id = get_canonical_repo_id(mock_repo)

    # Investigation with REQUIRES_VERIFICATION
    inv_id = store.save_investigation(
        repo_name=canonical_id,
        problem="Race condition in background thread",
        root_cause="Lock ordering violation",
        plan="Reorder locks",
        result={"files": ["src/app.py"]},
    )
    store.update_record_validity("investigations", inv_id, "REQUIRES_VERIFICATION")

    # Change affecting source_code
    change = _make_change(canonical_id, changed_files=["src/app.py"], has_committed=True)
    dims = detect_affected_dimensions(change)
    inv = invalidate_memory(change, dims, store)

    # Run understand again
    result = understand_again(change, dims, inv, repo_path=mock_repo, memory=store)

    # source_code WAS recomputed
    assert "source_code" in result.recomputed_dimensions

    # BUT the investigation CANNOT be validated by mere syntax check -> stays unresolved!
    assert not any(r["id"] == inv_id for r in result.revalidated_records)
    unresolved_inv = next(r for r in result.unresolved_records if r["record_type"] == "investigation" and r["id"] == inv_id)
    assert unresolved_inv["validity"] == "REQUIRES_VERIFICATION"

    # SQLite investigation remains REQUIRES_VERIFICATION
    final_inv = store.load_investigations(canonical_id)[0]
    assert final_inv["current_validity"] == "REQUIRES_VERIFICATION"


# ── Additional: Result serialization roundtrip ────────────────────────────────


def test_result_serialization_roundtrip(mock_repo):
    """Result dataclass serializes cleanly to dict and json."""
    canonical_id = get_canonical_repo_id(mock_repo)
    result = IncrementalUnderstandResult(
        repo_id=canonical_id,
        status="reunderstood",
        affected_dimensions=["tests"],
        recomputed_dimensions=["tests"],
        preserved_dimensions=["source_code", "dependencies"],
        revalidated_records=[{"record_type": "decision", "id": 1, "previous_validity": "REQUIRES_VERIFICATION", "new_validity": "VALID", "reason": "pytest found"}],
        unresolved_records=[],
        updated_profile={"name": "test"},
        updated_assessment=None,
        deterministic_processing_complete=True,
    )

    d = result.to_dict()
    assert d["status"] == "reunderstood"
    assert d["recomputed_dimensions"] == ["tests"]

    json_str = result.to_json()
    assert "reunderstood" in json_str

    restored = IncrementalUnderstandResult.from_dict(d)
    assert restored.repo_id == canonical_id
    assert restored.status == result.status
    assert restored.recomputed_dimensions == result.recomputed_dimensions
    assert restored.deterministic_processing_complete is True
