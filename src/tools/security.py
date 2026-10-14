"""
Phase 5 — Tooling & Capability Foundation: Tool Safety and Policy Boundary.

Security and Safety Boundaries:
1. Terminal Security Boundary:
   - Command validation against strict allowlist of base executables.
   - Shell metacharacters and chaining rejection (;, &&, |, $(...), etc.).
   - Dangerous command rejection: rm -rf /, sudo, mkfs, forkbombs, etc.
   - Mutation barrier: mutating commands (rm, mv, cp, touch, git checkout/commit, etc.)
     require explicit trusted authorization (context["allow_mutations"] = True).
     Caller arguments ('arguments["allow_mutations"]') CANNOT elevate privileges.
   - Repository Boundary Enforcement:
     Repository root is validated against ALLOWED_REPO_ROOTS.
     Caller arguments cannot broaden or conflict with trusted roots.
   - Strict Path Confinement:
     All path targets (both existing and nonexistent) must remain strictly within
     the validated repository root.
     Parent traversal (..), symlinks pointing outside, and absolute path escapes
     are strictly rejected.
   - Git Global Options & Redirection:
     Parses through Git global options to identify real subcommands.
     Rejects repository redirection (-C, --git-dir, --work-tree) targeting outside paths.
   - Interpreter / Python Confinement:
     Arbitrary Python code execution (-c, arbitrary scripts, non-inspection modules)
     cannot bypass mutation barriers and requires explicit trusted authorization.
     Read-only inspection (--version, -m pytest, -m unittest) is permitted.
   - Shell execution: subprocess shell=False is strictly enforced.

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
import re
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

# Commands that mutate files/environment - require explicit trusted allow_mutations=True
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
    "shortlog",
    "check-ref-format",
    "ls-files",
    "ls-tree",
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
    "revert",
}

# Python modules permitted in read-only mode without mutation authorization
ALLOWED_READ_ONLY_PYTHON_MODULES = {
    "pytest",
    "unittest",
    "py_compile",
    "json.tool",
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
    def get_allowed_repo_roots() -> list[Path]:
        """
        Determines permitted filesystem roots for repository execution and inspection.
        Allowed roots:
          1. Explicitly configured ALLOWED_REPO_ROOTS environment variable.
          2. The cloned repos directory configured by PATH_TO_CLONED_REPO (defaults to ./repos).
          3. The current workspace / application root directory.
        """
        roots: list[Path] = []
        env_roots = os.getenv("ALLOWED_REPO_ROOTS")
        if env_roots:
            for r in re.split(r"[:;,]", env_roots):
                r_clean = r.strip()
                if r_clean:
                    try:
                        p = Path(r_clean).resolve()
                        if p.exists() and p.is_dir():
                            roots.append(p)
                    except Exception:
                        pass

        cloned_base = os.getenv("PATH_TO_CLONED_REPO", "./repos")
        try:
            p_cloned = Path(cloned_base).resolve()
            if p_cloned.exists() and p_cloned.is_dir():
                roots.append(p_cloned)
        except Exception:
            pass

        try:
            cwd = Path.cwd().resolve()
            roots.append(cwd)
        except Exception:
            pass

        seen: set[Path] = set()
        deduped: list[Path] = []
        for r in roots:
            if r not in seen:
                seen.add(r)
                deduped.append(r)
        return deduped

    @staticmethod
    def resolve_mutation_authorization(
        context: dict[str, Any] | None,
        arguments: dict[str, Any] | None,
    ) -> tuple[bool, str | None]:
        """
        Strictly resolves mutation authorization.
        Rules:
          1. Authorization MUST come from trusted execution context ('allow_mutations' is True).
          2. Caller arguments ('arguments["allow_mutations"]') CANNOT elevate privileges or grant authorization.
          3. If caller arguments assert allow_mutations=True when context does not grant it, fail closed.
          4. If context grants allow_mutations=True but caller arguments explicitly specify allow_mutations=False,
             fail closed (conflicting intent).
        """
        ctx = context or {}
        args = arguments or {}

        trusted_auth = bool(ctx.get("allow_mutations", False))
        caller_auth = args.get("allow_mutations")

        if caller_auth is True and not trusted_auth:
            return False, "Untrusted caller argument 'allow_mutations' cannot grant mutation authorization without trusted context"

        if trusted_auth and caller_auth is False:
            return False, "Conflicting mutation authorization: caller requested read-only while context permits mutation"

        return trusted_auth, None

    @staticmethod
    def resolve_and_validate_repo_root(
        context_repo_path: str | Path | None,
        argument_repo_path: str | Path | None = None,
    ) -> tuple[Path | None, str | None]:
        """
        Resolves the canonical repository root ensuring untrusted caller arguments
        cannot override trusted context or broaden permitted boundaries.
        """
        if context_repo_path:
            try:
                ctx_resolved = Path(context_repo_path).resolve()
            except Exception as e:
                return None, f"Could not resolve context repository path: {e}"

            if not ctx_resolved.exists() or not ctx_resolved.is_dir():
                return None, f"Repository path does not exist or is not a directory: {context_repo_path}"

            if argument_repo_path:
                try:
                    arg_resolved = Path(argument_repo_path).resolve()
                except Exception as e:
                    return None, f"Could not resolve argument repository path: {e}"

                if arg_resolved != ctx_resolved and not arg_resolved.is_relative_to(ctx_resolved):
                    return None, f"Caller-provided 'repo_path' ('{argument_repo_path}') conflicts with or escapes trusted context repository root ('{context_repo_path}')"

            return ctx_resolved, None

        if argument_repo_path:
            try:
                arg_resolved = Path(argument_repo_path).resolve()
            except Exception as e:
                return None, f"Could not resolve argument repository path: {e}"

            if not arg_resolved.exists() or not arg_resolved.is_dir():
                return None, f"Repository path does not exist or is not a directory: {argument_repo_path}"

            allowed_roots = ToolSafetyPolicy.get_allowed_repo_roots()
            is_allowed = any(arg_resolved == root or arg_resolved.is_relative_to(root) for root in allowed_roots)
            if not is_allowed:
                return None, f"Repository path '{argument_repo_path}' is outside permitted repository roots"

            return arg_resolved, None

        return None, "Repository path ('repo_path') must be provided in context or arguments"

    @staticmethod
    def resolve_effective_cwd(
        repo_root: Path,
        cwd_arg: str | Path | None = None,
    ) -> tuple[Path | None, str | None]:
        """
        Resolves effective working directory ensuring it remains confined within repo_root.
        """
        if not cwd_arg:
            return repo_root, None

        try:
            raw_cwd = Path(str(cwd_arg).replace("\\", "/"))
            effective = (repo_root / raw_cwd).resolve() if not raw_cwd.is_absolute() else raw_cwd.resolve()
        except Exception as e:
            return None, f"Could not resolve working directory '{cwd_arg}': {e}"

        if not effective.is_relative_to(repo_root):
            return None, f"Working directory escapes repository boundary: {cwd_arg}"

        if not effective.exists() or not effective.is_dir():
            return None, f"Specified working directory does not exist or is not a directory: {cwd_arg}"

        return effective, None

    @staticmethod
    def is_read_only(tool_name: str, operation: str) -> bool:
        """Checks if a tool operation is classified as strictly read-only."""
        allowed = READ_ONLY_OPERATIONS.get(tool_name, set())
        return operation.lower() in allowed

    @staticmethod
    def validate_terminal_command(
        command: str,
        repo_path: str | Path | None = None,
        effective_cwd: str | Path | None = None,
        allow_mutations: bool = False,
    ) -> tuple[bool, str | None]:
        """
        Validates a proposed terminal command against security policies:
          1. Rejects empty command strings.
          2. Rejects dangerous patterns (e.g. rm -rf /, sudo).
          3. Rejects shell metacharacters and chaining (;, &&, |, $(...)).
          4. Parses safely via shlex.split without shell expansion.
          5. Verifies executable is in allowlist.
          6. Enforces mutation barrier on mutating base commands.
          7. Enforces safety on commands like find (-delete, -exec).
          8. Parses Git subcommands through global options (-C, -c, --git-dir, --work-tree).
          9. Enforces Python interpreter policy (denies arbitrary -c without allow_mutations).
          10. Enforces strict path confinement for all arguments (existing and nonexistent).

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

        # 5. Base command mutation barrier check
        if is_known_mutate and not allow_mutations:
            return False, f"Mutating command '{base_cmd}' requires explicit 'allow_mutations' authorization"

        # Setup boundary paths for argument validation
        repo_resolved: Path | None = None
        base_dir: Path | None = None
        if repo_path:
            repo_resolved = Path(repo_path).resolve()
            if effective_cwd:
                base_dir = Path(effective_cwd).resolve()
            else:
                base_dir = repo_resolved

        # 6. Specific tool restrictions: find
        if base_cmd == "find":
            for tok in tokens[1:]:
                if tok in ("-delete", "-exec", "-execdir", "-ok", "-okdir"):
                    return False, f"Command 'find' with '{tok}' is not permitted in sandbox"

        # 7. Git-specific subcommand & global options analysis
        if base_cmd == "git":
            subcmd = None
            i = 1
            while i < len(tokens):
                tok = tokens[i]
                if tok in (
                    "--no-pager", "-p", "--paginate", "-P", "--no-replace-objects", "--bare",
                    "--literal-pathspecs", "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs",
                    "--version", "--help",
                ):
                    i += 1
                    continue
                elif tok == "-C":
                    if i + 1 >= len(tokens):
                        return False, "Git option '-C' requires a directory path"
                    c_path = tokens[i + 1]
                    if repo_resolved and base_dir:
                        target_c = (base_dir / Path(c_path.replace("\\", "/"))).resolve()
                        if not target_c.is_relative_to(repo_resolved):
                            return False, f"Git repository redirection '{c_path}' escapes repository boundary '{repo_resolved}'"
                    i += 2
                    continue
                elif tok.startswith("-C"):
                    c_path = tok[2:]
                    if repo_resolved and base_dir:
                        target_c = (base_dir / Path(c_path.replace("\\", "/"))).resolve()
                        if not target_c.is_relative_to(repo_resolved):
                            return False, f"Git repository redirection '{c_path}' escapes repository boundary '{repo_resolved}'"
                    i += 1
                    continue
                elif tok == "-c":
                    if i + 1 >= len(tokens):
                        return False, "Git option '-c' requires <name>=<value>"
                    i += 2
                    continue
                elif tok.startswith("-c"):
                    i += 1
                    continue
                elif tok == "--git-dir":
                    if i + 1 >= len(tokens):
                        return False, "Git option '--git-dir' requires a directory path"
                    gd_path = tokens[i + 1]
                    if repo_resolved and base_dir:
                        target_gd = (base_dir / Path(gd_path.replace("\\", "/"))).resolve()
                        if not target_gd.is_relative_to(repo_resolved):
                            return False, f"Git repository redirection '{gd_path}' escapes repository boundary '{repo_resolved}'"
                    i += 2
                    continue
                elif tok.startswith("--git-dir="):
                    gd_path = tok.split("=", 1)[1]
                    if repo_resolved and base_dir:
                        target_gd = (base_dir / Path(gd_path.replace("\\", "/"))).resolve()
                        if not target_gd.is_relative_to(repo_resolved):
                            return False, f"Git repository redirection '{gd_path}' escapes repository boundary '{repo_resolved}'"
                    i += 1
                    continue
                elif tok == "--work-tree":
                    if i + 1 >= len(tokens):
                        return False, "Git option '--work-tree' requires a directory path"
                    wt_path = tokens[i + 1]
                    if repo_resolved and base_dir:
                        target_wt = (base_dir / Path(wt_path.replace("\\", "/"))).resolve()
                        if not target_wt.is_relative_to(repo_resolved):
                            return False, f"Git repository redirection '{wt_path}' escapes repository boundary '{repo_resolved}'"
                    i += 2
                    continue
                elif tok.startswith("--work-tree="):
                    wt_path = tok.split("=", 1)[1]
                    if repo_resolved and base_dir:
                        target_wt = (base_dir / Path(wt_path.replace("\\", "/"))).resolve()
                        if not target_wt.is_relative_to(repo_resolved):
                            return False, f"Git repository redirection '{wt_path}' escapes repository boundary '{repo_resolved}'"
                    i += 1
                    continue
                elif tok.startswith("--exec-path") or tok.startswith("--namespace") or tok.startswith("--config-env"):
                    return False, f"Git global option '{tok.split('=')[0]}' is not permitted in sandbox"
                elif tok.startswith("-"):
                    return False, f"Unsupported git global option '{tok}'"
                else:
                    subcmd = tok.lower()
                    break

            if subcmd is None:
                if any(t in tokens[1:] for t in ("--version", "-v", "--help")):
                    return True, None
                return False, "No git subcommand specified"

            if subcmd in MUTATING_GIT_SUBCOMMANDS and not allow_mutations:
                return False, f"Mutating git command 'git {subcmd}' requires explicit 'allow_mutations' authorization"

            if subcmd not in SAFE_GIT_SUBCOMMANDS and subcmd not in MUTATING_GIT_SUBCOMMANDS:
                return False, f"Git subcommand '{subcmd}' is not in the allowed git commands list"

        # 8. Python interpreter policy
        if base_cmd in ("python", "python3"):
            if len(tokens) == 1:
                return False, "Interactive Python interpreter session is not permitted"

            first_arg = tokens[1]
            if first_arg in ("--version", "-V", "-h", "--help"):
                # Safe read-only flags
                pass
            elif first_arg == "-m":
                if len(tokens) < 3:
                    return False, "Missing module name after '-m'"
                mod_name = tokens[2]
                if mod_name in ALLOWED_READ_ONLY_PYTHON_MODULES:
                    # Permitted read-only inspection module (pytest, unittest, etc.)
                    pass
                else:
                    if not allow_mutations:
                        return False, f"Python module execution ('-m {mod_name}') requires explicit 'allow_mutations' authorization"
            elif first_arg == "-c":
                if not allow_mutations:
                    return False, "Arbitrary Python execution ('python -c') requires explicit 'allow_mutations' authorization"
            else:
                # Script execution or other interpreter arguments
                script_arg = None
                for tok in tokens[1:]:
                    if not tok.startswith("-"):
                        script_arg = tok
                        break

                if script_arg:
                    if repo_resolved and base_dir:
                        target_script = (base_dir / Path(script_arg.replace("\\", "/"))).resolve()
                        if not target_script.is_relative_to(repo_resolved):
                            return False, f"Python script path '{script_arg}' escapes repository boundary '{repo_resolved}'"
                    if not allow_mutations:
                        return False, f"Executing Python script '{script_arg}' requires explicit 'allow_mutations' authorization"
                else:
                    if not allow_mutations:
                        return False, "Python execution requires explicit 'allow_mutations' authorization"

        # 9. Strict repository path confinement for all arguments (existing AND nonexistent)
        if repo_resolved and base_dir:
            for arg in tokens[1:]:
                # Skip flags that do not specify paths
                if arg.startswith("-") and "=" not in arg and not (len(arg) > 2 and arg[1] == ":"):
                    continue

                check_val = arg
                if arg.startswith("-") and "=" in arg:
                    check_val = arg.split("=", 1)[1]

                norm_str = check_val.replace("\\", "/")
                norm_p = Path(norm_str)

                # Directory traversal via ..
                if ".." in norm_p.parts:
                    try:
                        resolved = (base_dir / norm_p).resolve()
                        if not resolved.is_relative_to(repo_resolved):
                            return False, f"Argument '{arg}' escapes repository boundary via '..'"
                    except Exception:
                        return False, f"Argument '{arg}' escapes repository boundary via '..'"

                # Absolute path (whether existing or nonexistent)
                if norm_str.startswith("/") or (len(norm_str) > 2 and norm_str[1] == ":"):
                    try:
                        resolved = norm_p.resolve()
                        if not resolved.is_relative_to(repo_resolved):
                            return False, f"Path argument '{arg}' escapes repository boundary '{repo_resolved}'"
                    except Exception:
                        return False, f"Path argument '{arg}' escapes repository boundary '{repo_resolved}'"

                # Relative path or symlink traversal
                if "/" in norm_str or is_known_mutate:
                    try:
                        resolved = (base_dir / norm_p).resolve()
                        if not resolved.is_relative_to(repo_resolved):
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
            context_repo = request.context.get("repo_path")
            arg_repo = request.arguments.get("repo_path")

            repo_root: Path | None = None
            if context_repo or arg_repo:
                repo_root, repo_err = ToolSafetyPolicy.resolve_and_validate_repo_root(
                    context_repo_path=context_repo,
                    argument_repo_path=arg_repo,
                )
                if repo_err:
                    return False, repo_err

            effective_cwd: Path | None = None
            if repo_root:
                cwd_arg = request.arguments.get("cwd")
                effective_cwd, cwd_err = ToolSafetyPolicy.resolve_effective_cwd(repo_root, cwd_arg)
                if cwd_err:
                    return False, cwd_err

            allow_mutations, auth_err = ToolSafetyPolicy.resolve_mutation_authorization(
                context=request.context,
                arguments=request.arguments,
            )
            if auth_err:
                return False, auth_err

            return ToolSafetyPolicy.validate_terminal_command(
                cmd,
                repo_path=repo_root,
                effective_cwd=effective_cwd,
                allow_mutations=allow_mutations,
            )

        if request.tool_name == "github":
            is_write = request.arguments.get("is_write", False)
            if is_write and not request.context.get("allow_mutations", False):
                return False, "GitHub write operations require explicit 'allow_mutations' authorization"

        return True, None
