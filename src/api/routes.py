# src/api/routes.py
"""
FastAPI routes for Project Overview and workspace state introspection.
"""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from src.api.schemas import (
    EngineeringChangeRecord,
    EngineeringDecisionRecord,
    EngineeringMemoryResponse,
    ErrorResponse,
    InvestigationListResponse,
    InvestigationRecord,
    ProjectOverviewResponse,
)
from src.api.security import validate_repo_path
from src.api.service import build_project_overview
from src.api.explorer import router as repository_explorer_router
from src.api.tools import router as tools_router
from src.helpers.repo import get_canonical_repo_id
from src.memory.sqlite_store import EngineeringMemoryStore

router = APIRouter(prefix="/api/project", tags=["project"])
router.include_router(repository_explorer_router)
router.include_router(tools_router)


@router.get(
    "/overview",
    response_model=ProjectOverviewResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid parameter or path format"},
        403: {"model": ErrorResponse, "description": "Access denied outside permitted roots"},
        404: {"model": ErrorResponse, "description": "Repository path not found"},
    },
)
def get_project_overview(
    repo_path: str = Query(..., description="Filesystem path to the repository directory"),
    include_assessment: bool = Query(
        False,
        description="Whether to execute deterministic AST compilation and project stage synthesis",
    ),
):
    """
    Read-only Project Overview endpoint.

    Returns canonical identity, git revision status, incremental delta intelligence,
    persisted profile and validity counts, and optional code health assessment.
    """
    resolved_path, error = validate_repo_path(repo_path)
    if error:
        err_code, err_msg, status_code = error
        return JSONResponse(
            status_code=status_code,
            content={"error": err_code, "detail": err_msg},
        )

    return build_project_overview(resolved_path, include_assessment=include_assessment)


@router.get(
    "/investigations",
    response_model=InvestigationListResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def list_project_investigations(
    repo_path: str = Query(..., description="Authorized repository root path"),
    limit: int = Query(50, ge=1, le=100),
):
    """Return persisted investigation records without running the agent graph."""
    resolved_path, error = validate_repo_path(repo_path)
    if error:
        err_code, err_msg, status_code = error
        return JSONResponse(
            status_code=status_code,
            content={"error": err_code, "detail": err_msg},
        )

    assert resolved_path is not None
    repo_id = get_canonical_repo_id(resolved_path)
    store = EngineeringMemoryStore()
    records = store.load_investigations(repo_id, limit=limit)
    if not records and resolved_path.name != repo_id:
        records = store.load_investigations(resolved_path.name, limit=limit)

    return InvestigationListResponse(
        repo_path=str(resolved_path),
        investigations=[
            InvestigationRecord(
                id=int(record["id"]),
                problem=record["problem"],
                root_cause=record.get("root_cause"),
                plan=record.get("plan"),
                result=record.get("result"),
                created_at=record.get("created_at"),
                current_validity=record.get("current_validity"),
                invalidated_at=record.get("invalidated_at"),
                invalidation_reason=record.get("invalidation_reason"),
            )
            for record in records
        ],
        total_returned=len(records),
        limit=limit,
    )


@router.get(
    "/memory",
    response_model=EngineeringMemoryResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def get_project_engineering_memory(
    repo_path: str = Query(..., description="Authorized repository root path"),
    change_limit: int = Query(100, ge=1, le=500),
):
    """Return persisted decisions and recent change records without graph execution."""
    resolved_path, error = validate_repo_path(repo_path)
    if error:
        err_code, err_msg, status_code = error
        return JSONResponse(
            status_code=status_code,
            content={"error": err_code, "detail": err_msg},
        )

    assert resolved_path is not None
    repo_id = get_canonical_repo_id(resolved_path)
    store = EngineeringMemoryStore()
    decisions = store.load_decisions(repo_id)
    change_records = store.load_change_records(repo_id, limit=change_limit)
    if resolved_path.name != repo_id:
        if not decisions:
            decisions = store.load_decisions(resolved_path.name)
        if not change_records:
            change_records = store.load_change_records(resolved_path.name, limit=change_limit)

    return EngineeringMemoryResponse(
        repo_path=str(resolved_path),
        decisions=[
            EngineeringDecisionRecord(
                id=int(record["id"]),
                subject=record["subject"],
                decision=record["decision"],
                rationale=record["rationale"],
                source=record["source"],
                reference=record.get("reference"),
                created_at=record["created_at"],
                current_validity=record.get("current_validity"),
                invalidated_at=record.get("invalidated_at"),
                invalidation_reason=record.get("invalidation_reason"),
            )
            for record in decisions
        ],
        change_records=[
            EngineeringChangeRecord(
                id=int(record["id"]),
                commit_hash=record["commit_hash"],
                changed_files=record.get("changed_files") or [],
                changed_symbols=record.get("changed_symbols"),
                architecture_impact=record.get("architecture_impact"),
                drift_detected=bool(record.get("drift_detected", False)),
                review=record.get("review"),
                created_at=record["created_at"],
            )
            for record in change_records
        ],
        change_records_limit=change_limit,
        change_records_truncated=len(change_records) == change_limit,
    )
