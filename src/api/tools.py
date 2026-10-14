"""
Phase 5.3 — Tool Execution & Introspection API.

Exposes authorized, controlled access to registered repository tools:
  - GET /api/project/tools: List registered tools, descriptions, and operations.
  - POST /api/project/tools/execute: Execute an authorized tool operation.
"""

from typing import Any
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from src.api.schemas import (
    ErrorResponse,
    ToolDescriptor,
    ToolEvidencePayload,
    ToolExecutionRequest,
    ToolExecutionResponse,
    ToolListResponse,
)
from src.api.security import validate_repo_path
from src.tools import default_registry
from src.tools.models import ToolRequest

router = APIRouter(prefix="/tools", tags=["tools"])

TOOL_OPERATIONS: dict[str, list[str]] = {
    "git": ["status", "diff", "log", "changed_files"],
    "filesystem": ["list_dir", "read_file", "search_text", "patch_file"],
    "terminal": ["execute"],
    "fake_tool": ["echo", "inspect", "query"],
}

MUTATING_OPERATIONS: set[tuple[str, str]] = {
    ("filesystem", "patch_file"),
}


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": code, "detail": message},
    )


@router.get(
    "",
    response_model=ToolListResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def list_available_tools(
    repo_path: str = Query(..., description="Authorized repository root path"),
):
    """
    Lists registered tools, capabilities, and supported operations for an authorized repository.
    """
    resolved_path, error = validate_repo_path(repo_path)
    if error:
        err_code, err_msg, status_code = error
        return _error(err_code, err_msg, status_code)

    assert resolved_path is not None
    tools_list: list[ToolDescriptor] = []

    for tool_name in default_registry.list_tools():
        tool = default_registry.get(tool_name)
        if not tool:
            continue
        ops = TOOL_OPERATIONS.get(tool_name, [])
        is_ro = tool_name == "git"
        tools_list.append(
            ToolDescriptor(
                name=tool.name,
                description=tool.description,
                supported_operations=ops,
                is_read_only=is_ro,
            )
        )

    return ToolListResponse(
        repo_path=str(resolved_path),
        tools=tools_list,
    )


@router.post(
    "/execute",
    response_model=ToolExecutionResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def execute_tool_operation(
    payload: ToolExecutionRequest,
):
    """
    Executes an authorized tool operation on an authorized repository.
    Enforces repository boundary confinement and read-only defaults for web requests.
    """
    resolved_path, error = validate_repo_path(payload.repo_path)
    if error:
        err_code, err_msg, status_code = error
        return _error(err_code, err_msg, status_code)

    assert resolved_path is not None

    if (payload.tool_name, payload.operation) in MUTATING_OPERATIONS:
        return _error(
            "mutation_not_authorized",
            f"Operation '{payload.operation}' on tool '{payload.tool_name}' mutates repository files and is not permitted via the web API",
            403,
        )

    tool = default_registry.get(payload.tool_name)
    if not tool:
        return _error(
            "tool_not_found",
            f"Tool '{payload.tool_name}' is not registered. Available tools: {default_registry.list_tools()}",
            404,
        )

    tool_req = ToolRequest(
        tool_name=payload.tool_name,
        operation=payload.operation,
        arguments=dict(payload.arguments),
        context={
            "repo_path": str(resolved_path),
            "allow_mutations": False,
        },
    )

    result = default_registry.execute(tool_req)

    evidence_payload: ToolEvidencePayload | None = None
    try:
        evidence = result.to_evidence(
            category=f"{payload.tool_name}_execution",
            target=str(resolved_path),
        )
        evidence_payload = ToolEvidencePayload(
            source_tool=evidence.source_tool,
            operation=evidence.operation,
            category=evidence.category,
            success=evidence.success,
            is_interpreted=evidence.is_interpreted,
            target=evidence.target,
            timestamp=evidence.timestamp,
        )
    except Exception:
        pass

    return ToolExecutionResponse(
        tool_name=result.tool_name,
        operation=result.operation,
        success=result.success,
        output=result.output,
        error=result.error,
        metadata=result.metadata,
        evidence=evidence_payload,
    )
