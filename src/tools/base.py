"""
Phase 5 — Tooling & Capability Foundation: Base Tool Adapter and Registry.

Defines the adapter boundary between the agent/workflow and external tool capabilities:
  - BaseTool: Abstract base adapter that all concrete tools must implement.
  - ToolRegistry: Central registry to manage and dispatch tool requests.
  - default_registry: Singleton registry instance for standard tool lookup.

Architectural Rule:
  The graph and agent interact with tools via this abstract boundary.
  The graph must never know internal implementation details of Terminal, GitHub,
  or Browser tools.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.tools.models import ToolRequest, ToolResult


class BaseTool(ABC):
    """
    Abstract adapter for an external capability tool.

    Concrete tools (Terminal, GitHub, Browser, FakeTool) inherit from this
    class and implement the execute method.
    """
    name: str = ""
    description: str = ""

    @abstractmethod
    def execute(self, request: ToolRequest) -> ToolResult:
        """
        Executes the tool request and returns a structured ToolResult.

        Must NEVER raise unhandled exceptions across the boundary;
        failures must be returned as ToolResult with success=False.
        """
        pass

    def validate_request(self, request: ToolRequest) -> tuple[bool, str | None]:
        """
        Validates whether this tool adapter can handle the given request.

        Returns:
            (True, None) if valid.
            (False, error_reason) if invalid.
        """
        if not isinstance(request, ToolRequest):
            return False, f"Expected ToolRequest, got {type(request).__name__}"
        if request.tool_name != self.name:
            return False, f"Tool name mismatch: expected '{self.name}', got '{request.tool_name}'"
        return True, None


class ToolRegistry:
    """
    Registry for managing available tool adapters and dispatching requests.
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Registers a tool adapter."""
        if not isinstance(tool, BaseTool):
            raise TypeError(f"Expected BaseTool instance, got {type(tool).__name__}")
        if not tool.name or not tool.name.strip():
            raise ValueError("Tool must define a non-empty 'name'")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Retrieves a registered tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Checks if a tool is registered."""
        return name in self._tools

    def list_tools(self) -> list[str]:
        """Returns sorted list of registered tool names."""
        return sorted(self._tools.keys())

    def unregister(self, name: str) -> bool:
        """Removes a tool from the registry. Returns True if removed."""
        return self._tools.pop(name, None) is not None

    def clear(self) -> None:
        """Clears all registered tools."""
        self._tools.clear()

    def execute(self, request: ToolRequest) -> ToolResult:
        """
        Dispatches a ToolRequest to the appropriate registered tool.
        If the tool is missing or validation fails, returns a failed ToolResult
        without crashing the workflow.
        """
        if not isinstance(request, ToolRequest):
            return ToolResult.create_failure(
                tool_name="unknown",
                operation="unknown",
                error=f"Invalid request type: expected ToolRequest, got {type(request).__name__}",
            )

        tool = self.get(request.tool_name)
        if tool is None:
            return ToolResult.create_failure(
                tool_name=request.tool_name,
                operation=request.operation,
                error=f"Tool '{request.tool_name}' is not registered. Available tools: {self.list_tools()}",
            )

        is_valid, validation_error = tool.validate_request(request)
        if not is_valid:
            return ToolResult.create_failure(
                tool_name=request.tool_name,
                operation=request.operation,
                error=f"Validation failed: {validation_error}",
            )

        try:
            return tool.execute(request)
        except Exception as e:
            return ToolResult.create_failure(
                tool_name=request.tool_name,
                operation=request.operation,
                error=f"Unexpected error executing tool '{request.tool_name}': {e}",
            )


# Default global tool registry
default_registry = ToolRegistry()
