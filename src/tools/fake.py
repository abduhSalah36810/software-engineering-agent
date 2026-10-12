"""
Phase 5 — Tooling & Capability Foundation: Deterministic Fake Tool Adapter.

A purely deterministic in-memory tool implementation used strictly for
testing and validating the tooling architecture without external dependencies.

Guarantees:
  - ZERO subprocess execution.
  - ZERO network calls.
  - ZERO filesystem modifications.
  - Predictable, deterministic behavior.
"""

from __future__ import annotations

from typing import Any
from src.tools.base import BaseTool
from src.tools.models import ToolRequest, ToolResult


class FakeTool(BaseTool):
    """
    Deterministic mock tool adapter for testing the capability layer.
    """
    name: str = "fake_tool"
    description: str = "Deterministic in-memory mock tool for architectural validation"

    def execute(self, request: ToolRequest) -> ToolResult:
        """
        Executes mock operations without external side effects.

        Supported operations:
          - 'echo': returns arguments.get('message')
          - 'inspect': returns deterministic inspection dictionary
          - 'fail': returns a failed ToolResult with arguments.get('error_message')
          - 'raise': simulates an unexpected exception within tool execution
          - 'query': returns structured mock query data
        """
        op = request.operation

        if op == "echo":
            msg = request.arguments.get("message", "")
            return ToolResult.create_success(
                tool_name=self.name,
                operation=op,
                output=msg,
                metadata={"echoed": True, "len": len(str(msg))},
            )

        if op == "inspect":
            target = request.arguments.get("target", "default")
            return ToolResult.create_success(
                tool_name=self.name,
                operation=op,
                output={
                    "target": target,
                    "status": "inspected",
                    "properties": {"mock_key": "mock_value"},
                },
                metadata={"mock_source": "memory"},
            )

        if op == "query":
            items = request.arguments.get("items", ["item_1", "item_2"])
            return ToolResult.create_success(
                tool_name=self.name,
                operation=op,
                output={"items": items, "count": len(items)},
                metadata={"query_type": "in_memory"},
            )

        if op == "fail":
            err_msg = request.arguments.get("error_message", "Simulated tool execution failure")
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=op,
                error=err_msg,
                metadata={"simulated_failure": True},
            )

        if op == "raise":
            raise RuntimeError(request.arguments.get("error_message", "Simulated unhandled exception"))

        # Unknown operation
        return ToolResult.create_failure(
            tool_name=self.name,
            operation=op,
            error=f"Unsupported operation '{op}' for tool '{self.name}'",
            metadata={"supported_operations": ["echo", "inspect", "query", "fail", "raise"]},
        )
