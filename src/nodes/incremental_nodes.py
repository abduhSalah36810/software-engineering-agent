"""
Phase 4.5 — LangGraph Incremental Pipeline Nodes.

Deterministic orchestration nodes that wire together:
  - Node 1: incremental_change_node (IncrementalChangeDetector)
  - Node 2: affected_dimensions_node (AffectedDimensionClassifier / detect_affected_dimensions)
  - Node 3: memory_invalidation_node (MemoryInvalidationEngine / invalidate_memory)
  - Node 4: incremental_understand_node (IncrementalUnderstandEngine / understand_again)
  - Node 5: no_changes_node (bypasses downstream work when unchanged)

Control routing:
  - route_after_change: branches to 'no_changes' if status is unchanged with no modifications.

Zero LLM. Zero external services. Deterministic orchestration only.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.state import AgentState
from src.memory.sqlite_store import EngineeringMemoryStore
from src.helpers.incremental_change import (
    IncrementalChangeDetector,
    IncrementalChangeResult,
)
from src.helpers.affected_dimensions import (
    AffectedDimensionsResult,
    detect_affected_dimensions,
    SUPPORTED_DIMENSIONS,
)
from src.helpers.memory_invalidation import (
    MemoryInvalidationResult,
    invalidate_memory,
)
from src.helpers.incremental_understand import (
    IncrementalUnderstandResult,
    understand_again,
)


def incremental_change_node(state: AgentState) -> dict:
    """
    Node 1: Incremental Change Detection.
    Calls IncrementalChangeDetector to detect repository delta.
    Does NOT implement git diff logic itself.
    """
    repo_path = state.get("repo_path")
    repo_name = state.get("repo_name")
    repo_id = state.get("repo_id")
    memory = state.get("memory")
    if memory is None:
        memory = EngineeringMemoryStore()

    detector = IncrementalChangeDetector(
        repo_path=repo_path,
        repo_name=repo_name,
        repo_id=repo_id,
        memory=memory,
    )
    since_commit = state.get("since_commit")
    result = detector.detect_changes(since_commit=since_commit)

    updates: dict[str, Any] = {
        "incremental_change_result": result,
    }
    if not repo_id and getattr(result, "repo_id", None):
        updates["repo_id"] = result.repo_id
    if not repo_name and getattr(result, "repo_name", None):
        updates["repo_name"] = result.repo_name

    return updates


def affected_dimensions_node(state: AgentState) -> dict:
    """
    Node 2: Affected Dimensions Classification.
    Calls detect_affected_dimensions to identify dimensions touched by changes.
    Does NOT implement file classification logic itself.
    """
    change_res = state.get("incremental_change_result")
    if change_res is None:
        raise ValueError("Missing 'incremental_change_result' in state for affected_dimensions_node")

    if isinstance(change_res, dict):
        change_res = IncrementalChangeResult.from_dict(change_res)

    repo_path = state.get("repo_path")
    result = detect_affected_dimensions(change_res, repo_path=repo_path)
    return {
        "affected_dimensions_result": result,
    }


def memory_invalidation_node(state: AgentState) -> dict:
    """
    Node 3: Memory Invalidation.
    Calls invalidate_memory to mark touched stored knowledge as REQUIRES_VERIFICATION.
    Preserves all validity semantics.
    """
    change_res = state.get("incremental_change_result")
    if change_res is None:
        raise ValueError("Missing 'incremental_change_result' in state for memory_invalidation_node")
    if isinstance(change_res, dict):
        change_res = IncrementalChangeResult.from_dict(change_res)

    dims_res = state.get("affected_dimensions_result")
    if dims_res is None:
        raise ValueError("Missing 'affected_dimensions_result' in state for memory_invalidation_node")
    if isinstance(dims_res, dict):
        dims_res = AffectedDimensionsResult.from_dict(dims_res)

    memory = state.get("memory")
    if memory is None:
        memory = EngineeringMemoryStore()

    result = invalidate_memory(
        change_result=change_res,
        dimensions_result=dims_res,
        memory=memory,
    )
    return {
        "memory_invalidation_result": result,
    }


def incremental_understand_node(state: AgentState) -> dict:
    """
    Node 4: Incremental Understand Again.
    Calls understand_again to re-understand only affected dimensions.
    Does NOT implement assessment logic itself.
    """
    change_res = state.get("incremental_change_result")
    if change_res is None:
        raise ValueError("Missing 'incremental_change_result' in state for incremental_understand_node")
    if isinstance(change_res, dict):
        change_res = IncrementalChangeResult.from_dict(change_res)

    dims_res = state.get("affected_dimensions_result")
    if dims_res is None:
        raise ValueError("Missing 'affected_dimensions_result' in state for incremental_understand_node")
    if isinstance(dims_res, dict):
        dims_res = AffectedDimensionsResult.from_dict(dims_res)

    inval_res = state.get("memory_invalidation_result")
    if inval_res is None:
        raise ValueError("Missing 'memory_invalidation_result' in state for incremental_understand_node")
    if isinstance(inval_res, dict):
        inval_res = MemoryInvalidationResult.from_dict(inval_res)

    memory = state.get("memory")
    if memory is None:
        memory = EngineeringMemoryStore()

    repo_path = state.get("repo_path")

    result = understand_again(
        change_result=change_res,
        dims_result=dims_res,
        invalidation_result=inval_res,
        repo_path=repo_path,
        memory=memory,
    )
    updates: dict[str, Any] = {
        "incremental_understand_result": result,
    }
    if result.updated_profile:
        updates["repo_profile"] = result.updated_profile

    return updates


def no_changes_node(state: AgentState) -> dict:
    """
    Fast-path node for unchanged repositories.
    Avoids unnecessary downstream recomputation and clearly marks status as 'no_changes'.
    """
    change_res = state.get("incremental_change_result")
    if isinstance(change_res, dict):
        repo_id = change_res.get("repo_id", state.get("repo_id", "unknown"))
    elif change_res:
        repo_id = getattr(change_res, "repo_id", state.get("repo_id", "unknown"))
    else:
        repo_id = state.get("repo_id", "unknown")

    understand_result = IncrementalUnderstandResult(
        repo_id=repo_id,
        status="no_changes",
        affected_dimensions=[],
        recomputed_dimensions=[],
        preserved_dimensions=sorted(SUPPORTED_DIMENSIONS),
        revalidated_records=[],
        unresolved_records=[],
        updated_profile=None,
        updated_assessment=None,
        deterministic_processing_complete=True,
    )
    return {
        "incremental_understand_result": understand_result,
    }


def route_after_change(state: AgentState) -> str:
    """
    Determines downstream routing after change detection.
    If the repository is unchanged with no working tree modifications,
    routes to 'no_changes' to avoid unnecessary recomputation.
    Otherwise routes to 'continue'.
    """
    change_res = state.get("incremental_change_result")
    if isinstance(change_res, dict):
        status = change_res.get("status")
        has_changes = change_res.get("has_changes", False)
    elif change_res:
        status = getattr(change_res, "status", None)
        has_changes = getattr(change_res, "has_changes", False)
    else:
        status = None
        has_changes = False

    if status == "unchanged" and not has_changes:
        return "no_changes"
    return "continue"
