"""
Phase 5 & 5.1 — Tooling & Capability Foundation: Security & Safety Boundaries.

Formalizes architectural safety boundaries for tool operations:

1. Terminal Security Boundary (Phase 5.1):
   - Strict command allowlist: only approved executables are permitted.
   - Shell metacharacter rejection: no command chaining (;, &&, ||), piping (|),
     redirection (>, <), backticks, or subshell expansions ($(...)).
   - No shell=True: commands are tokenized with shlex and executed directly.
   - Dangerous command rejection: rm -rf /, sudo, mkfs, forkbombs, etc.
   - Mutation barrier: mutating commands (rm, mv, cp, touch, git checkout, etc.)
     require explicit allow_mutations=True authorization.
   - Working Directory Containment: commands must execute within the repository root;
     path traversal (..) is strictly rejected.
   - Output limits and execution timeouts prevent runaway processes.

2. GitHub Security Boundary (Future Phase 5.2):
   - Read-only operations (fetch diffs, read PRs) separated from write operations.
   - Authentication tokens must never be exposed or persisted in logs or memory.

3. Browser Security Boundary (Future Phase 5.3):
   - Read-only documentation retrieval separated from state-mutating actions.

Zero external services. Deterministic policy contracts.
"""

from __future__ import annotations

import os
from pathlib import Path
import shlex
from typing import Any

from src.tools.models import ToolRequest


# Known dangerous command prefixes/patterns for terminal boundary
DISALLOWED_TERMINAL_PATTERNS = [
    "rm -rf /",
    "rm -rf /*",
    ":(){ :|:& };:",
    "mkfs",
    "dd if=",
    "chmod -R 777 /",
    "sudo",
    "shutdown",
    "reboot",
    "fdisk",
    "curl | bash",
    "wget | bash",
    "curl | sh",
    "wget | sh",
]

# Shell metacharacters forbidden to prevent command chaining, piping, redirection, or subshells
FORBIDDEN_SHELL_METACHARACTERS = [
    ";",
    "&&",
    "||",
    "|",
    ">",
    ">>",
    "<",
    "`",
    "$(",
    "${",
    "\n",
    "\r",
]

# Base executables permitted by default (read-oriented and analysis tools)
ALLOWED_READ_ONLY_COMMANDS = {
    "pwd",
    "ls",
    "find",
    "cat",
    "head",
    "tail",
    "grep",
    "rg",
    "git",
    "python",
    "python3",
    "pytest",
    "echo",
    "which",
    "whoami",
}

# Commands that mutate files/environment - require explicit allow_mutations=True
ALLOWED_MUTATING_COMMANDS = {
    "touch",
    "mkdir",
    "rm",
    "mv",
    "cp",
    "rmdir",
}

# Git subcommands classified as read-only vs mutating
SAFE_GIT_SUBCOMMANDS = {
    "status",
    "diff",
    "log",
    "show",
    "branch",
    "rev-parse",
    "cat-file",
    "merge-base",
    "describe",
    "tag",
    "remote",
    "version",
}

MUTATING_GIT_SUBCOMMANDS = {
    "checkout",
    "switch",
    "reset",
    "clean",
    "commit",
    "add",
    "rm",
    "mv",
    "merge",
    "rebase",
    "cherry-pick",
    "stash",
    "pull",
    "push",
    "init",
}

# Read-only operations per tool type
READ_ONLY_OPERATIONS: dict[str, set[str]] = {
    "terminal": {"status", "diff", "log", "test", "check", "inspect", "cat", "echo", "execute"},
    "github": {"get_issue", "get_pr", "get_diff", "list_commits", "inspect_repo"},
    "browser": {"fetch_url", "search_docs", "read_page"},
    "fake_tool": {"echo", "inspect", "query"},
}


class ToolSafetyPolicy:
    """
    Defines security and safety boundaries for tool execution.
    """

    @staticmethod
    def is_read_only(tool_name: str, operation: str) -> bool:
        """Checks if a tool operation is classified as strictly read-only."""
        allowed = READ_ONLY_OPERATIONS.get(tool_name, set())
        return operation.lower() in allowed

    @staticmethod
    def validate_terminal_command(
        command: str,
        repo_path: str | None = None,
        allow_mutations: bool = False,
    ) -> tuple[bool, str | None]:
        """
        Validates a proposed terminal command against security policies:
          1. Rejects dangerous patterns (e.g. rm -rf /, sudo).
          2. Rejects shell metacharacters and chaining (;, &&, |, $(...)).
          3. Parses safely via shlex.split without shell expansion.
          4. Verifies executable is in allowlist.
          5. Enforces mutation barrier (requires allow_mutations=True).
          6. Enforces repository confinement (rejects .. traversal).

        Returns:
            (True, None) if valid and permitted.
            (False, error_reason) if rejected by policy.
        """
        if not command or not isinstance(command, str) or not command.strip():
            return False, "Command string is empty"

        cmd_clean = command.strip()
        cmd_lower = cmd_clean.lower()

        # 1. Reject dangerous patterns
        for pattern in DISALLOWED_TERMINAL_PATTERNS:
            if pattern in cmd_lower:
                return False, f"Command contains forbidden pattern '{pattern}'"

        # 2. Reject shell metacharacters and chaining
        for char in FORBIDDEN_SHELL_METACHARACTERS:
            if char in cmd_clean:
                return False, f"Command contains forbidden shell metacharacter or chaining operator ('{char}')"

        # 3. Parse tokens safely via shlex
        try:
            tokens = shlex.split(cmd_clean)
        except Exception as e:
            return False, f"Failed to parse command syntax: {e}"

        if not tokens:
            return False, "No command tokens found"

        # Extract base executable name
        raw_cmd = tokens[0]
        base_cmd = Path(raw_cmd).name.lower()

        # Disallow direct shell builtins that bypass boundaries (e.g., cd)
        if base_cmd == "cd":
            return False, "Direct 'cd' command is not permitted; use working directory parameter"

        # 4. Executable allowlist check
        is_known_read = base_cmd in ALLOWED_READ_ONLY_COMMANDS
        is_known_mutate = base_cmd in ALLOWED_MUTATING_COMMANDS

        if not is_known_read and not is_known_mutate:
            return False, f"Command '{base_cmd}' is not in the allowed terminal commands list"

        # 5. Mutation barrier check
        if is_known_mutate and not allow_mutations:
            return False, f"Mutating command '{base_cmd}' requires explicit 'allow_mutations' authorization"

        # Git-specific subcommand checks
        if base_cmd == "git" and len(tokens) > 1:
            subcmd = tokens[1].lower()
            if subcmd in MUTATING_GIT_SUBCOMMANDS and not allow_mutations:
                return False, f"Mutating git command 'git {subcmd}' requires explicit 'allow_mutations' authorization"

        # 6. Repository confinement check for arguments
        repo_resolved = Path(repo_path).resolve() if repo_path else None

        for arg in tokens[1:]:
            # Check for directory traversal patterns
            if arg == ".." or arg.startswith("../") or "/../" in arg or arg.endswith("/..") or arg.startswith("..\\"):
                return False, f"Argument '{arg}' attempts to escape repository boundary via '..'"

            # Check absolute paths if repository path is provided
            if repo_resolved and (arg.startswith("/") or (len(arg) > 2 and arg[1] == ":")):
                try:
                    p = Path(arg).resolve()
                    if p.exists() and not p.is_relative_to(repo_resolved):
                        return False, f"Path argument '{arg}' escapes repository boundary '{repo_resolved}'"
                except Exception:
                    pass

        return True, None

    @staticmethod
    def check_request_safety(request: ToolRequest) -> tuple[bool, str | None]:
        """
        Evaluates a ToolRequest against safety policies.
        Returns (True, None) if safe, or (False, reason) if policy is violated.
        """
        if request.tool_name == "terminal":
            cmd = request.arguments.get("command", "")
            repo_path = request.context.get("repo_path") or request.arguments.get("repo_path")
            allow_mutations = bool(
                request.context.get("allow_mutations") or request.arguments.get("allow_mutations")
            )
            return ToolSafetyPolicy.validate_terminal_command(
                cmd,
                repo_path=repo_path,
                allow_mutations=allow_mutations,
            )

        if request.tool_name == "github":
            is_write = request.arguments.get("is_write", False)
            if is_write and not request.context.get("allow_mutations", False):
                return False, "GitHub write operations require explicit 'allow_mutations' authorization"

        return True, None
