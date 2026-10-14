"""
Phase 5.1 — Sandboxed Terminal Execution Capability (Hardened).

Provides a controlled, repository-scoped terminal execution tool adapter:
  - TerminalTool: BaseTool implementation that wraps subprocess execution.
  - Strict Repository Boundary: Validates repository path against ALLOWED_REPO_ROOTS.
  - Strict Mutation Barrier: Mutating commands require explicit trusted authorization.
  - No Shell Invocation: subprocess.run(..., shell=False).
  - Timeout Enforced: Hard execution ceiling.
  - Output Bounded: Limits oversized stdout/stderr.
  - Sanitized Environment: Strips secrets and dangerous execution-hijacking variables.
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

# Dangerous execution-hijacking environment variables to always block
DANGEROUS_ENV_VARS = {
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH",
    "PYTHONPATH",
    "PYTHONHOME",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
    "BASH_ENV",
    "ENV",
}


def _get_sanitized_env() -> dict[str, str]:
    """
    Builds a sanitized environment dictionary excluding secrets and execution-hijacking variables.
    Preserves system and Python runtime paths.
    """
    safe_env = {}
    for k, v in os.environ.items():
        k_upper = k.upper()
        if k in DANGEROUS_ENV_VARS or k_upper in DANGEROUS_ENV_VARS:
            continue
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

        # 3. Resolve and validate repository root from trusted context or allowed roots
        context_repo = request.context.get("repo_path")
        arg_repo = request.arguments.get("repo_path")

        repo_root, repo_err = ToolSafetyPolicy.resolve_and_validate_repo_root(
            context_repo_path=context_repo,
            argument_repo_path=arg_repo,
        )
        if repo_err or not repo_root:
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=request.operation,
                error=f"Repository boundary violation: {repo_err}",
            )

        # 4. Resolve and validate effective working directory
        cwd_arg = request.arguments.get("cwd")
        effective_cwd, cwd_err = ToolSafetyPolicy.resolve_effective_cwd(repo_root, cwd_arg)
        if cwd_err or not effective_cwd:
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=request.operation,
                error=f"Working directory violation: {cwd_err}",
            )

        # 5. Resolve trusted mutation authorization
        allow_mutations, auth_err = ToolSafetyPolicy.resolve_mutation_authorization(
            context=request.context,
            arguments=request.arguments,
        )
        if auth_err:
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=request.operation,
                error=f"Authorization violation: {auth_err}",
            )

        # 6. Safety policy verification
        is_safe, safety_err = ToolSafetyPolicy.validate_terminal_command(
            cmd_str,
            repo_path=repo_root,
            effective_cwd=effective_cwd,
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

        # 7. Timeout resolution
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

        # 8. Output limit configuration
        max_output_chars_arg = request.arguments.get("max_output_chars")
        if max_output_chars_arg is not None:
            try:
                max_output_chars = int(max_output_chars_arg)
                if max_output_chars <= 0:
                    max_output_chars = DEFAULT_MAX_OUTPUT_CHARS
            except (ValueError, TypeError):
                max_output_chars = DEFAULT_MAX_OUTPUT_CHARS
        else:
            max_output_chars = DEFAULT_MAX_OUTPUT_CHARS

        # 9. Sanitized environment
        env = _get_sanitized_env()

        # 10. Controlled process execution (SHELL=FALSE STRICTLY ENFORCED)
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

        # 11. Handle output bounding & truncation
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        stdout_truncated = len(stdout) > max_output_chars
        stderr_truncated = len(stderr) > max_output_chars

        if stdout_truncated:
            stdout = stdout[:max_output_chars] + f"\n... [stdout truncated: {len(proc.stdout)} chars total]"
        if stderr_truncated:
            stderr = stderr[:max_output_chars] + f"\n... [stderr truncated: {len(proc.stderr)} chars total]"

        # 12. Return successful tool execution result
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
