"""
Phase 5 & 5.1 — Tooling & Capability Foundation.

Core module exposing the tool contract, adapter interface, and registry:
  - Models: ToolRequest, ToolResult, ToolEvidence
  - Base: BaseTool, ToolRegistry, default_registry
  - Fake: FakeTool
  - Terminal: TerminalTool
  - Security: ToolSafetyPolicy
"""

from src.tools.models import (
    ToolRequest,
    ToolResult,
    ToolEvidence,
)
from src.tools.base import (
    BaseTool,
    ToolRegistry,
    default_registry,
)
from src.tools.fake import FakeTool
from src.tools.security import ToolSafetyPolicy
from src.tools.terminal import TerminalTool

# Register standard tools into the default global registry
default_registry.register(TerminalTool())

__all__ = [
    "ToolRequest",
    "ToolResult",
    "ToolEvidence",
    "BaseTool",
    "ToolRegistry",
    "default_registry",
    "FakeTool",
    "TerminalTool",
    "ToolSafetyPolicy",
]
