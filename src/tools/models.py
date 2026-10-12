"""
Phase 5 — Tooling & Capability Foundation: Domain Models.

Defines the core contracts for external tool interaction:
  - ToolRequest: Normalized representation of a tool invocation request.
  - ToolResult: Structured output from tool execution (success or failure).
  - ToolEvidence: Raw evidence derived from tool execution, maintaining provenance
    and strict boundary from engineering decisions.

Design principles:
  - Deterministic, serializable dataclasses.
  - Raw results are preserved; tool output does NOT become a decision.
  - Zero LLM, zero network, zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json
from typing import Any


def _get_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ToolRequest:
    """
    Minimal, normalized representation of an external tool invocation request.

    Attributes:
        tool_name: Stable name/identifier of the target tool (e.g., 'terminal', 'fake_tool').
        operation: The specific operation to execute (e.g., 'echo', 'status').
        arguments: Parameters and arguments for the operation.
        context: Contextual metadata (e.g., repo_id, session_id).
        request_id: Optional unique identifier for tracking.
    """
    tool_name: str
    operation: str
    arguments: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None

    def __post_init__(self) -> None:
        if not self.tool_name or not self.tool_name.strip():
            raise ValueError("ToolRequest requires a non-empty 'tool_name'")
        if not self.operation or not self.operation.strip():
            raise ValueError("ToolRequest requires a non-empty 'operation'")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolRequest:
        return cls(
            tool_name=str(data["tool_name"]),
            operation=str(data["operation"]),
            arguments=dict(data.get("arguments", {})),
            context=dict(data.get("context", {})),
            request_id=data.get("request_id"),
        )


@dataclass
class ToolEvidence:
    """
    Structured evidence extracted from a ToolResult.

    CRITICAL BOUNDARY:
      Evidence is raw observed fact from a tool execution.
      Evidence is NOT an engineering decision or recommendation.
      is_interpreted is False by default.
    """
    source_tool: str
    operation: str
    raw_data: Any
    success: bool
    target: str | None = None
    category: str = "tool_execution"
    is_interpreted: bool = False
    timestamp: str = field(default_factory=_get_utc_now)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolEvidence:
        return cls(
            source_tool=str(data["source_tool"]),
            operation=str(data["operation"]),
            raw_data=data.get("raw_data"),
            success=bool(data.get("success", False)),
            target=data.get("target"),
            category=str(data.get("category", "tool_execution")),
            is_interpreted=bool(data.get("is_interpreted", False)),
            timestamp=str(data.get("timestamp", "")),
            provenance=dict(data.get("provenance", {})),
        )


@dataclass
class ToolResult:
    """
    Structured representation of the outcome of a tool execution.

    Distinguishes success from failure cleanly without crashing the agent.
    Preserves raw output and provenance metadata.
    """
    tool_name: str
    operation: str
    success: bool
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolResult:
        return cls(
            tool_name=str(data["tool_name"]),
            operation=str(data["operation"]),
            success=bool(data.get("success", False)),
            output=data.get("output"),
            error=data.get("error"),
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def create_success(
        cls,
        tool_name: str,
        operation: str,
        output: Any,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Convenience constructor for successful execution."""
        meta = dict(metadata or {})
        meta.setdefault("executed_at", _get_utc_now())
        return cls(
            tool_name=tool_name,
            operation=operation,
            success=True,
            output=output,
            error=None,
            metadata=meta,
        )

    @classmethod
    def create_failure(
        cls,
        tool_name: str,
        operation: str,
        error: str,
        metadata: dict[str, Any] | None = None,
        output: Any = None,
    ) -> ToolResult:
        """Convenience constructor for failed execution without fabricated success."""
        meta = dict(metadata or {})
        meta.setdefault("executed_at", _get_utc_now())
        return cls(
            tool_name=tool_name,
            operation=operation,
            success=False,
            output=output,
            error=str(error),
            metadata=meta,
        )

    def to_evidence(
        self,
        category: str = "tool_execution",
        target: str | None = None,
    ) -> ToolEvidence:
        """
        Converts the tool result into a ToolEvidence record.
        Preserves raw output and metadata provenance.
        Does NOT convert output to an engineering decision.
        """
        return ToolEvidence(
            source_tool=self.tool_name,
            operation=self.operation,
            raw_data=self.output if self.success else self.error,
            success=self.success,
            target=target,
            category=category,
            is_interpreted=False,
            provenance={
                "metadata": self.metadata,
                "error": self.error,
            },
        )
