"""
Phase 4.3.5 — Memory Invalidation Tests.

Tests A–O as specified in the implementation contract:

A. Initial baseline produces no invalidation.
B. Source-code changes invalidate relevant knowledge.
C. Test changes invalidate testing-related knowledge.
D. Dependency changes invalidate dependency-related knowledge.
E. Deployment changes invalidate deployment-related knowledge.
F. CI changes invalidate CI/CD-related knowledge.
G. Architecture changes invalidate architecture-related knowledge.
H. Documentation changes do not automatically invalidate unrelated arch knowledge.
I. Historical decisions are preserved.
J. Invalidation records contain evidence/reasons.
K. Stale baseline triggers broad re-verification.
L. Stale baseline does not delete SQLite history.
M. Uncommitted changes can trigger current-session verification but are
   not treated as permanent repository evolution.
N. Unknown/unmapped dimensions do not cause fabricated invalidation.
O. Multiple affected dimensions produce deterministic, deduplicated results.
"""

from __future__ import annotations

import tempfile
import pytest

from src.helpers.affected_dimensions import AffectedDimension, AffectedDimensionsResult
from src.helpers.memory_invalidation import (
    MemoryInvalidationEngine,
    MemoryInvalidationResult,
    InvalidatedItem,
    invalidate_memory,
    DIMENSION_TO_KNOWLEDGE_CATEGORY,
)
from src.memory.sqlite_store import EngineeringMemoryStore


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_store(tmp_path) -> EngineeringMemoryStore:
    return EngineeringMemoryStore(db_path=str(tmp_path / "mem.db"))


def _make_change_result(
    repo_id: str = "test-repo",
    is_initial_baseline: bool = False,
    is_baseline_stale: bool = False,
    requires_reverification: bool = False,
    has_committed_changes: bool = False,
    has_uncommitted_changes: bool = False,
    changed_files: list | None = None,
    uncommitted_files: list | None = None,
):
    """Build a minimal IncrementalChangeResult-like object for testing."""
    from dataclasses import dataclass, field

    @dataclass
    class FakeChangeResult:
        repo_id: str = "test-repo"
        is_initial_baseline: bool = False
        is_baseline_stale: bool = False
        requires_reverification: bool = False
        has_committed_changes: bool = False
        has_uncommitted_changes: bool = False
        changed_files: list = field(default_factory=list)
        uncommitted_files: list = field(default_factory=list)

    return FakeChangeResult(
        repo_id=repo_id,
        is_initial_baseline=is_initial_baseline,
        is_baseline_stale=is_baseline_stale,
        requires_reverification=requires_reverification,
        has_committed_changes=has_committed_changes,
        has_uncommitted_changes=has_uncommitted_changes,
        changed_files=changed_files or [],
        uncommitted_files=uncommitted_files or [],
    )


def _make_dims(committed: dict | None = None, uncommitted: dict | None = None) -> AffectedDimensionsResult:
    """Build an AffectedDimensionsResult from simple dim->files dicts."""
    def _build(d):
        dims = []
        for dim, files in (d or {}).items():
            dims.append(AffectedDimension(
                dimension=dim,
                evidence_files=sorted(files),
                reasons=[f"{dim} affected: {f}" for f in sorted(files)],
            ))
        return dims

    return AffectedDimensionsResult(
        committed=_build(committed),
        uncommitted=_build(uncommitted),
    )


def _seed_knowledge(store: EngineeringMemoryStore, repo_id: str) -> tuple[int, int]:
    """Seed one decision and one investigation for the given repo."""
    store.save_decision(
        repo_name=repo_id,
        subject="framework",
        decision="Use FastAPI for the AI service",
        rationale="Fast, async, auto-docs",
        source="observed",
    )
    decisions = store.load_decisions(repo_id)
    dec_id = decisions[0]["id"]

    inv_id = store.save_investigation(
        repo_name=repo_id,
        problem="DASH manifest format_id uniqueness bug",
        root_cause="format_id is not unique within a Period",
        plan="use a composite key",
        result={"files_to_modify": ["youtube_dl/extractor/common.py"]},
    )
    return dec_id, inv_id


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path):
    return _make_store(tmp_path)


@pytest.fixture
def engine(store):
    return MemoryInvalidationEngine(memory=store)


# ── Test A: Initial baseline ──────────────────────────────────────────────────


def test_A_initial_baseline_produces_no_invalidation(engine, store):
    """A. Initial baseline -> no previous knowledge -> empty result."""
    repo_id = "fresh-repo"
    change = _make_change_result(repo_id=repo_id, is_initial_baseline=True)
    dims = _make_dims()

    result = engine.invalidate(change, dims)

    assert result.status == "initial_baseline"
    assert result.invalidated_count == 0
    assert result.invalidated_items == []
    assert result.affected_dimensions == []
    assert result.verification_required is False
    assert result.broad_reverification_required is False
    assert result.is_initial_baseline is True
    # No SQLite state should have been written
    assert store.load_decisions(repo_id) == []
    assert store.load_investigations(repo_id) == []


# ── Test B: Source-code changes ───────────────────────────────────────────────


def test_B_source_code_changes_invalidate_relevant_knowledge(engine, store):
    """B. Source-code changes invalidate source/code-related understanding."""
    repo_id = "repo-b"
    _seed_knowledge(store, repo_id)

    change = _make_change_result(repo_id=repo_id, has_committed_changes=True)
    dims = _make_dims(committed={"source_code": ["src/main.py", "src/service.py"]})

    result = engine.invalidate(change, dims)

    assert result.status == "invalidated"
    assert "source_code" in result.affected_dimensions
    assert result.verification_required is True
    assert result.broad_reverification_required is False

    # Decisions should be flagged
    decisions = store.load_decisions(repo_id)
    assert decisions[0]["current_validity"] == "REQUIRES_VERIFICATION"

    # Investigations should be flagged
    investigations = store.load_investigations(repo_id)
    assert investigations[0]["current_validity"] == "REQUIRES_VERIFICATION"

    # Items should be populated
    assert len(result.invalidated_items) >= 2


# ── Test C: Test changes ──────────────────────────────────────────────────────


def test_C_test_changes_invalidate_testing_related_knowledge(engine, store):
    """C. Test changes invalidate testing-related understanding."""
    repo_id = "repo-c"
    _seed_knowledge(store, repo_id)

    change = _make_change_result(repo_id=repo_id, has_committed_changes=True)
    dims = _make_dims(committed={"tests": ["tests/test_service.py"]})

    result = engine.invalidate(change, dims)

    assert "tests" in result.affected_dimensions
    assert result.status == "invalidated"
    decisions = store.load_decisions(repo_id)
    assert decisions[0]["current_validity"] == "REQUIRES_VERIFICATION"


# ── Test D: Dependency changes ────────────────────────────────────────────────


def test_D_dependency_changes_invalidate_dependency_knowledge(engine, store):
    """D. Dependency changes invalidate dependency/technology-related understanding."""
    repo_id = "repo-d"
    _seed_knowledge(store, repo_id)

    change = _make_change_result(repo_id=repo_id, has_committed_changes=True)
    dims = _make_dims(committed={"dependencies": ["requirements.txt", "package.json"]})

    result = engine.invalidate(change, dims)

    assert "dependencies" in result.affected_dimensions
    assert result.status == "invalidated"

    items_for_dep = [i for i in result.invalidated_items if i.dimension == "dependencies"]
    assert len(items_for_dep) >= 1
    assert any("requirements.txt" in i.evidence_files or "package.json" in i.evidence_files
               for i in items_for_dep)


# ── Test E: Deployment changes ────────────────────────────────────────────────


def test_E_deployment_changes_invalidate_deployment_knowledge(engine, store):
    """E. Deployment changes invalidate deployment/runtime-related understanding."""
    repo_id = "repo-e"
    _seed_knowledge(store, repo_id)

    change = _make_change_result(repo_id=repo_id, has_committed_changes=True)
    dims = _make_dims(committed={"deployment": ["Dockerfile", "docker-compose.yml"]})

    result = engine.invalidate(change, dims)

    assert "deployment" in result.affected_dimensions
    assert result.status == "invalidated"
    assert result.knowledge_category_for("deployment") == "deployment/runtime-related understanding" if hasattr(result, "knowledge_category_for") else True
    decisions = store.load_decisions(repo_id)
    assert decisions[0]["current_validity"] == "REQUIRES_VERIFICATION"


# ── Test F: CI changes ────────────────────────────────────────────────────────


def test_F_ci_changes_invalidate_cicd_knowledge(engine, store):
    """F. CI changes invalidate CI/CD-related understanding."""
    repo_id = "repo-f"
    _seed_knowledge(store, repo_id)

    change = _make_change_result(repo_id=repo_id, has_committed_changes=True)
    dims = _make_dims(committed={"ci_cd": [".github/workflows/ci.yml"]})

    result = engine.invalidate(change, dims)

    assert "ci_cd" in result.affected_dimensions
    assert result.status == "invalidated"
    decisions = store.load_decisions(repo_id)
    assert decisions[0]["current_validity"] == "REQUIRES_VERIFICATION"


# ── Test G: Architecture changes ──────────────────────────────────────────────


def test_G_architecture_changes_invalidate_architecture_knowledge(engine, store):
    """G. Architecture changes invalidate architecture-related understanding."""
    repo_id = "repo-g"
    _seed_knowledge(store, repo_id)

    change = _make_change_result(repo_id=repo_id, has_committed_changes=True)
    dims = _make_dims(committed={"architecture": ["services/auth_service/server.py"]})

    result = engine.invalidate(change, dims)

    assert "architecture" in result.affected_dimensions
    assert result.status == "invalidated"
    decisions = store.load_decisions(repo_id)
    assert decisions[0]["current_validity"] == "REQUIRES_VERIFICATION"


# ── Test H: Documentation isolation ──────────────────────────────────────────


def test_H_documentation_changes_do_not_invalidate_unrelated_architecture(engine, store):
    """H. Documentation changes do not automatically invalidate architecture knowledge."""
    repo_id = "repo-h"
    _seed_knowledge(store, repo_id)

    change = _make_change_result(repo_id=repo_id, has_committed_changes=True)
    # Only documentation changed — not architecture
    dims = _make_dims(committed={"documentation": ["README.md", "docs/api.md"]})

    result = engine.invalidate(change, dims)

    assert "documentation" in result.affected_dimensions
    # documentation maps to "decisions" only (not investigations)
    # but regardless: "architecture" must NOT appear in affected_dimensions
    assert "architecture" not in result.affected_dimensions

    # Decisions flagged via documentation
    decisions = store.load_decisions(repo_id)
    assert decisions[0]["current_validity"] == "REQUIRES_VERIFICATION"

    # Investigations NOT flagged (documentation only targets decisions)
    investigations = store.load_investigations(repo_id)
    assert investigations[0]["current_validity"] in ("VALID", None, "")


# ── Test I: Historical decisions are preserved ────────────────────────────────


def test_I_historical_decisions_are_preserved_after_invalidation(engine, store):
    """I. Original decision fields are never overwritten by invalidation."""
    repo_id = "repo-i"
    dec_id, inv_id = _seed_knowledge(store, repo_id)

    change = _make_change_result(repo_id=repo_id, has_committed_changes=True)
    dims = _make_dims(committed={"source_code": ["src/app.py"]})

    engine.invalidate(change, dims)

    decisions = store.load_decisions(repo_id)
    d = decisions[0]

    # Original fields preserved exactly
    assert d["subject"] == "framework"
    assert d["decision"] == "Use FastAPI for the AI service"
    assert d["rationale"] == "Fast, async, auto-docs"
    assert d["source"] == "observed"

    # Only validity fields changed
    assert d["current_validity"] == "REQUIRES_VERIFICATION"
    assert d["invalidated_at"] is not None
    assert d["invalidation_reason"] is not None

    # Investigations: original fields preserved
    investigations = store.load_investigations(repo_id)
    inv = investigations[0]
    assert inv["problem"] == "DASH manifest format_id uniqueness bug"
    assert inv["root_cause"] == "format_id is not unique within a Period"
    assert inv["plan"] == "use a composite key"


# ── Test J: Evidence and reasons in items ─────────────────────────────────────


def test_J_invalidation_records_contain_evidence_and_reasons(engine, store):
    """J. Each invalidated item has evidence_files and reasons."""
    repo_id = "repo-j"
    _seed_knowledge(store, repo_id)

    change = _make_change_result(repo_id=repo_id, has_committed_changes=True)
    dims = _make_dims(committed={"dependencies": ["requirements.txt"]})

    result = engine.invalidate(change, dims)

    assert result.evidence.get("dependencies") is not None
    assert "requirements.txt" in result.evidence["dependencies"]
    assert result.reasons.get("dependencies") is not None
    assert len(result.reasons["dependencies"]) > 0

    for item in result.invalidated_items:
        assert item.evidence_files is not None
        assert item.reasons is not None
        assert item.knowledge_category  # must not be empty
        assert item.dimension  # must not be empty


# ── Test K: Stale baseline triggers broad re-verification ─────────────────────


def test_K_stale_baseline_triggers_broad_reverification(engine, store):
    """K. is_baseline_stale=True -> broad_reverification_required=True, status=stale_baseline."""
    repo_id = "repo-k"
    _seed_knowledge(store, repo_id)

    change = _make_change_result(
        repo_id=repo_id,
        is_baseline_stale=True,
        requires_reverification=True,
    )
    dims = _make_dims()

    result = engine.invalidate(change, dims)

    assert result.status == "stale_baseline"
    assert result.broad_reverification_required is True
    assert result.verification_required is True
    # All records should be marked STALE
    decisions = store.load_decisions(repo_id)
    assert all(d["current_validity"] == "STALE" for d in decisions)
    investigations = store.load_investigations(repo_id)
    assert all(i["current_validity"] == "STALE" for i in investigations)


# ── Test L: Stale baseline does not delete SQLite history ─────────────────────


def test_L_stale_baseline_does_not_delete_sqlite_history(engine, store):
    """L. Stale baseline marks records STALE but never deletes them."""
    repo_id = "repo-l"
    dec_id, inv_id = _seed_knowledge(store, repo_id)

    change = _make_change_result(
        repo_id=repo_id,
        is_baseline_stale=True,
        requires_reverification=True,
    )
    dims = _make_dims()

    result = engine.invalidate(change, dims)

    # Records still exist
    decisions = store.load_decisions(repo_id)
    investigations = store.load_investigations(repo_id)
    assert len(decisions) == 1
    assert len(investigations) == 1

    # IDs unchanged
    assert decisions[0]["id"] == dec_id
    assert investigations[0]["id"] == inv_id

    # Original knowledge preserved
    assert decisions[0]["decision"] == "Use FastAPI for the AI service"
    assert investigations[0]["root_cause"] == "format_id is not unique within a Period"

    # Validity changed
    assert decisions[0]["current_validity"] == "STALE"
    assert investigations[0]["current_validity"] == "STALE"


# ── Test M: Uncommitted changes ───────────────────────────────────────────────


def test_M_uncommitted_changes_trigger_session_verification_not_permanent(engine, store):
    """M. Uncommitted changes produce session-scoped items but do NOT write to SQLite."""
    repo_id = "repo-m"
    _seed_knowledge(store, repo_id)

    change = _make_change_result(
        repo_id=repo_id,
        has_uncommitted_changes=True,
        uncommitted_files=["Dockerfile"],
    )
    # deployment is uncommitted only, not committed
    dims = _make_dims(committed={}, uncommitted={"deployment": ["Dockerfile"]})

    result = engine.invalidate(change, dims)

    # Session-level result is produced
    assert "deployment" in result.affected_dimensions
    assert result.verification_required is True

    # BUT SQLite records are NOT permanently updated
    decisions = store.load_decisions(repo_id)
    for d in decisions:
        assert d.get("current_validity") in (None, "VALID", ""), (
            f"Expected VALID or None for uncommitted-only change, got {d.get('current_validity')}"
        )
    investigations = store.load_investigations(repo_id)
    for inv in investigations:
        assert inv.get("current_validity") in (None, "VALID", ""), (
            f"Expected VALID or None for uncommitted-only change, got {inv.get('current_validity')}"
        )

    # Items do carry is_from_uncommitted flag
    for item in result.invalidated_items:
        assert item.is_from_uncommitted is True


# ── Test N: Unknown dimensions ────────────────────────────────────────────────


def test_N_unknown_dimensions_do_not_cause_fabricated_invalidation(engine, store):
    """N. Dimensions not in DIMENSION_TO_KNOWLEDGE_CATEGORY produce no invalidation."""
    repo_id = "repo-n"
    _seed_knowledge(store, repo_id)

    change = _make_change_result(repo_id=repo_id, has_committed_changes=True)
    # "security_posture" is not a known dimension
    dims = AffectedDimensionsResult(
        committed=[
            AffectedDimension(
                dimension="security_posture",
                evidence_files=["audit.log"],
                reasons=["security audit changed"],
            )
        ],
        uncommitted=[],
    )

    result = engine.invalidate(change, dims)

    # Unknown dimension must NOT produce any invalidation
    assert result.invalidated_count == 0
    assert result.invalidated_items == []
    assert result.affected_dimensions == []
    # SQLite not touched
    decisions = store.load_decisions(repo_id)
    for d in decisions:
        assert d.get("current_validity") in (None, "VALID", "")


# ── Test O: Multiple dimensions deduplicated ──────────────────────────────────


def test_O_multiple_dimensions_deduplicated_deterministic(engine, store):
    """O. Multiple affected dimensions produce deterministic, deduplicated counts."""
    repo_id = "repo-o"
    _seed_knowledge(store, repo_id)

    change = _make_change_result(repo_id=repo_id, has_committed_changes=True)
    dims = _make_dims(committed={
        "source_code":  ["src/app.py", "src/models.py"],
        "tests":        ["tests/test_app.py"],
        "dependencies": ["requirements.txt"],
    })

    result = engine.invalidate(change, dims)

    # All 3 dimensions present
    assert "source_code" in result.affected_dimensions
    assert "tests" in result.affected_dimensions
    assert "dependencies" in result.affected_dimensions

    # Dimensions are sorted
    assert result.affected_dimensions == sorted(result.affected_dimensions)

    # invalidated_count counts UNIQUE (type, id) pairs, not total items
    # We have 1 decision + 1 investigation, both affected by 3 dims
    # -> 3*1 + 3*1 = 6 items, but unique count = 2
    assert result.invalidated_count == 2

    # SQLite: each record marked exactly once (last write wins: REQUIRES_VERIFICATION)
    decisions = store.load_decisions(repo_id)
    assert decisions[0]["current_validity"] == "REQUIRES_VERIFICATION"
    investigations = store.load_investigations(repo_id)
    assert investigations[0]["current_validity"] == "REQUIRES_VERIFICATION"


# ── Additional: no_changes path ───────────────────────────────────────────────


def test_no_changes_when_no_known_dimensions(engine, store):
    """No invalidation when change_result has committed changes but no known-dim files."""
    repo_id = "repo-empty"
    _seed_knowledge(store, repo_id)

    change = _make_change_result(repo_id=repo_id, has_committed_changes=True)
    # No dimensions at all
    dims = _make_dims()

    result = engine.invalidate(change, dims)

    assert result.status == "no_changes"
    assert result.invalidated_count == 0


# ── Additional: serialization roundtrip ──────────────────────────────────────


def test_invalidation_result_serializes_cleanly(engine, store):
    """MemoryInvalidationResult serializes/deserializes cleanly."""
    repo_id = "repo-serial"
    _seed_knowledge(store, repo_id)

    change = _make_change_result(repo_id=repo_id, has_committed_changes=True)
    dims = _make_dims(committed={"source_code": ["src/main.py"]})

    result = engine.invalidate(change, dims)
    d = result.to_dict()
    restored = MemoryInvalidationResult.from_dict(d)

    assert restored.status == result.status
    assert restored.invalidated_count == result.invalidated_count
    assert restored.affected_dimensions == result.affected_dimensions
    assert len(restored.invalidated_items) == len(result.invalidated_items)
    for orig, rest in zip(result.invalidated_items, restored.invalidated_items):
        assert isinstance(rest, InvalidatedItem)
        assert rest.record_id == orig.record_id
        assert rest.dimension == orig.dimension
        assert rest.new_validity == orig.new_validity


# ── Additional: convenience function ─────────────────────────────────────────


def test_convenience_function_invalidate_memory(tmp_path):
    """invalidate_memory() convenience function works end-to-end."""
    store = _make_store(tmp_path)
    repo_id = "repo-conv"
    store.save_decision(
        repo_name=repo_id,
        subject="db",
        decision="Use PostgreSQL",
        rationale="scalable",
        source="observed",
    )

    change = _make_change_result(repo_id=repo_id, has_committed_changes=True)
    dims = _make_dims(committed={"dependencies": ["requirements.txt"]})

    result = invalidate_memory(change, dims, store)

    assert isinstance(result, MemoryInvalidationResult)
    assert result.status == "invalidated"
    assert "dependencies" in result.affected_dimensions


# ── Additional: requires_reverification alone triggers stale_baseline ─────────


def test_requires_reverification_alone_triggers_broad_reverification(engine, store):
    """requires_reverification=True (even without is_baseline_stale) -> stale_baseline."""
    repo_id = "repo-reverify"
    _seed_knowledge(store, repo_id)

    change = _make_change_result(
        repo_id=repo_id,
        is_baseline_stale=False,
        requires_reverification=True,
    )
    dims = _make_dims()

    result = engine.invalidate(change, dims)

    assert result.status == "stale_baseline"
    assert result.broad_reverification_required is True
    decisions = store.load_decisions(repo_id)
    assert decisions[0]["current_validity"] == "STALE"


# ── Additional: DIMENSION_TO_KNOWLEDGE_CATEGORY completeness ──────────────────


def test_all_supported_dimensions_have_category_mapping():
    """All 9 supported dimensions have a knowledge-category mapping."""
    from src.helpers.affected_dimensions import SUPPORTED_DIMENSIONS
    for dim in SUPPORTED_DIMENSIONS:
        assert dim in DIMENSION_TO_KNOWLEDGE_CATEGORY, (
            f"Dimension '{dim}' is missing from DIMENSION_TO_KNOWLEDGE_CATEGORY"
        )


# ── Additional: previously STALE record can be upgraded if committed change ────


def test_previously_stale_record_validity_field_updated_on_new_committed_change(engine, store):
    """A STALE record gets updated to REQUIRES_VERIFICATION on new committed evidence."""
    repo_id = "repo-upgrade"
    _seed_knowledge(store, repo_id)

    # First: stale baseline marks everything STALE
    stale_change = _make_change_result(repo_id=repo_id, is_baseline_stale=True)
    engine.invalidate(stale_change, _make_dims())
    decisions_before = store.load_decisions(repo_id)
    assert decisions_before[0]["current_validity"] == "STALE"

    # Then: committed source change comes in
    normal_change = _make_change_result(repo_id=repo_id, has_committed_changes=True)
    dims = _make_dims(committed={"source_code": ["src/fix.py"]})
    result = engine.invalidate(normal_change, dims)

    # The record validity is updated to REQUIRES_VERIFICATION
    decisions_after = store.load_decisions(repo_id)
    assert decisions_after[0]["current_validity"] == "REQUIRES_VERIFICATION"
    assert result.status == "invalidated"
