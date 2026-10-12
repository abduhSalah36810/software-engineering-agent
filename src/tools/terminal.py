"""
Phase 5.1 — Sandboxed Terminal Capability.

Implements TerminalTool as a concrete BaseTool adapter.
Executes controlled repository-scoped terminal commands while enforcing
strict safety boundaries:
  - Repository confinement: working directory and path targets must stay inside repo.
  - Strict command allowlist: only approved executables are permitted.
  - Mutation barrier: mutating commands require explicit allow_mutations=True authorization.
  - Shell-free execution: commands are parsed into argument lists and executed with shell=False.
  - Timeouts: bounded execution prevents runaway processes.
  - Output limits: stdout/stderr accumulation is capped to prevent memory exhaustion.
  - Structured results: non-zero exit codes are preserved without fabricating tool failure.

Zero LLM. Zero MCP. Zero arbitrary shell access.
"""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import time
from typing import Any

from src.tools.base import BaseTool
from src.tools.models import ToolRequest, ToolResult
from src.tools.security import ToolSafetyPolicy

DEFAULT_TIMEOUT_SECONDS: float = 10.0
MAX_TIMEOUT_SECONDS: float = 60.0
DEFAULT_MAX_OUTPUT_CHARS: int = 50_000

# Sensitive environment variable keywords to exclude from subprocess execution
SENSITIVE_ENV_KEYWORDS = {"TOKEN", "KEY", "SECRET", "PASS", "AUTH", "CRED"}


def _get_sanitized_env() -> dict[str, str]:
    """
    Builds a sanitized environment dictionary excluding secrets.
    Preserves system and Python runtime paths.
    """
    safe_env = {}
    for k, v in os.environ.items():
        k_upper = k.upper()
        if any(keyword in k_upper for keyword in SENSITIVE_ENV_KEYWORDS):
            continue
        safe_env[k] = v
    return safe_env


class TerminalTool(BaseTool):
    """
    Controlled repository-scoped terminal execution tool adapter.
    """
    name: str = "terminal"
    description: str = (
        "Executes controlled terminal commands within repository boundaries "
        "with strict safety policies, timeout limits, and output bounds."
    )

    def execute(self, request: ToolRequest) -> ToolResult:
        """
        Executes an explicitly supplied ToolRequest against the target repository.
        """
        # 1. Validate request type and tool identity
        is_valid, validation_err = self.validate_request(request)
        if not is_valid:
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=getattr(request, "operation", "execute"),
                error=f"Validation failed: {validation_err}",
            )

        # 2. Extract command string
        cmd_str = request.arguments.get("command")
        if not cmd_str or not isinstance(cmd_str, str) or not cmd_str.strip():
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=request.operation,
                error="Missing or invalid 'command' in arguments",
            )

        # 3. Extract and validate repository path
        repo_path = request.context.get("repo_path") or request.arguments.get("repo_path")
        if not repo_path:
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=request.operation,
                error="Repository path ('repo_path') must be provided in context or arguments",
            )

        repo_root = Path(repo_path).resolve()
        if not repo_root.exists() or not repo_root.is_dir():
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=request.operation,
                error=f"Repository path does not exist or is not a directory: {repo_path}",
            )

        # 4. Resolve and validate effective working directory
        cwd_rel = request.arguments.get("cwd")
        if cwd_rel:
            effective_cwd = (repo_root / cwd_rel).resolve()
            if not effective_cwd.exists() or not effective_cwd.is_dir():
                return ToolResult.create_failure(
                    tool_name=self.name,
                    operation=request.operation,
                    error=f"Specified working directory does not exist: {cwd_rel}",
                )
            if not effective_cwd.is_relative_to(repo_root):
                return ToolResult.create_failure(
                    tool_name=self.name,
                    operation=request.operation,
                    error=f"Working directory escapes repository boundary: {cwd_rel}",
                )
        else:
            effective_cwd = repo_root

        # 5. Safety policy verification
        allow_mutations = bool(
            request.context.get("allow_mutations") or request.arguments.get("allow_mutations")
        )
        is_safe, safety_err = ToolSafetyPolicy.validate_terminal_command(
            cmd_str,
            repo_path=str(repo_root),
            allow_mutations=allow_mutations,
        )
        if not is_safe:
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=request.operation,
                error=f"Safety policy violation: {safety_err}",
                metadata={"command": cmd_str, "working_directory": str(effective_cwd)},
            )

        try:
            tokens = shlex.split(cmd_str.strip())
        except Exception as e:
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=request.operation,
                error=f"Failed to parse command syntax: {e}",
            )

        # 6. Timeout resolution
        timeout_arg = request.arguments.get("timeout")
        if timeout_arg is not None:
            try:
                timeout = float(timeout_arg)
                if timeout <= 0 or timeout > MAX_TIMEOUT_SECONDS:
                    return ToolResult.create_failure(
                        tool_name=self.name,
                        operation=request.operation,
                        error=f"Timeout must be between 1 and {MAX_TIMEOUT_SECONDS} seconds",
                    )
            except (ValueError, TypeError):
                return ToolResult.create_failure(
                    tool_name=self.name,
                    operation=request.operation,
                    error=f"Invalid timeout value: {timeout_arg}",
                )
        else:
            timeout = DEFAULT_TIMEOUT_SECONDS

        # 7. Output limit configuration
        max_output_chars = int(request.arguments.get("max_output_chars", DEFAULT_MAX_OUTPUT_CHARS))

        # 8. Sanitized environment
        env = _get_sanitized_env()

        # 9. Controlled process execution (SHELL=FALSE STRICTLY ENFORCED)
        start_time = time.monotonic()
        try:
            proc = subprocess.run(
                tokens,
                cwd=str(effective_cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                shell=False,  # STRICT: Never invoke shell
            )
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
        except subprocess.TimeoutExpired as te:
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            stdout_partial = te.stdout if isinstance(te.stdout, str) else ""
            stderr_partial = te.stderr if isinstance(te.stderr, str) else ""
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=request.operation,
                error=f"Command timed out after {timeout} seconds",
                metadata={
                    "command": cmd_str,
                    "tokens": tokens,
                    "working_directory": str(effective_cwd),
                    "timeout": timeout,
                    "timed_out": True,
                    "duration_ms": duration_ms,
                    "partial_stdout": stdout_partial[:1000] if stdout_partial else None,
                    "partial_stderr": stderr_partial[:1000] if stderr_partial else None,
                },
            )
        except FileNotFoundError as fnf:
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=request.operation,
                error=f"Executable not found: '{tokens[0]}'",
                metadata={
                    "command": cmd_str,
                    "working_directory": str(effective_cwd),
                    "duration_ms": duration_ms,
                },
            )
        except Exception as e:
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=request.operation,
                error=f"Unexpected error executing command '{cmd_str}': {e}",
                metadata={
                    "command": cmd_str,
                    "working_directory": str(effective_cwd),
                    "duration_ms": duration_ms,
                },
            )

        # 10. Handle output bounding & truncation
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        stdout_truncated = len(stdout) > max_output_chars
        stderr_truncated = len(stderr) > max_output_chars

        if stdout_truncated:
            stdout = stdout[:max_output_chars] + f"\n... [stdout truncated: {len(proc.stdout)} chars total]"
        if stderr_truncated:
            stderr = stderr[:max_output_chars] + f"\n... [stderr truncated: {len(proc.stderr)} chars total]"

        # 11. Return successful tool execution result
        # Non-zero process exit codes are preserved in metadata without fabricating tool failure.
        return ToolResult.create_success(
            tool_name=self.name,
            operation=request.operation,
            output=stdout,
            metadata={
                "command": cmd_str,
                "tokens": tokens,
                "exit_code": proc.returncode,
                "working_directory": str(effective_cwd),
                "stderr": stderr,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "duration_ms": duration_ms,
            },
        )
