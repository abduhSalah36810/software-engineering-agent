"""
Phase 5.2 — Tooling & Capability Foundation: Dedicated Git Tool.

Exposes structured, read-only repository history and change information:
  - status: Working-tree status, branch info, staged/unstaged/untracked changes.
  - diff: Bounded working-tree, staged, or commit-range diffs.
  - log: Structured recent commit history (hash, author, date, subject, parents).
  - changed_files: Changed file paths and change types (working tree or revision range).

Security & Confinement:
  - Read-only: Rejects commits, checkouts, resets, merges, pushes, or mutations.
  - Enforces repository-root containment via ToolSafetyPolicy.
  - Sanitized environment: strips GIT_DIR, GIT_WORK_TREE, tokens, and hijacking vars.
  - Disallows option injection in refs, commits, and paths.
  - Uses '--' path separator for all pathspecs.
  - Bounded outputs and execution timeouts.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
from typing import Any

from src.tools.base import BaseTool
from src.tools.models import ToolRequest, ToolResult
from src.tools.security import ToolSafetyPolicy

# ── Limits & Constants ────────────────────────────────────────────────────────

DEFAULT_MAX_DIFF_CHARS: int = 30_000
MAX_DIFF_CHARS_CAP: int = 50_000
DEFAULT_LOG_LIMIT: int = 20
MAX_LOG_LIMIT: int = 100
DEFAULT_CHANGED_FILES_LIMIT: int = 100
MAX_CHANGED_FILES_LIMIT: int = 500
SUBPROCESS_TIMEOUT_SECONDS: int = 15

SUPPORTED_OPERATIONS = {"status", "diff", "log", "changed_files"}

# Sensitive environment variables keywords to exclude from subprocess execution
SENSITIVE_ENV_KEYWORDS = {"TOKEN", "KEY", "SECRET", "PASS", "AUTH", "CRED"}

# Dangerous execution-hijacking and git-redirection environment variables to strip
DANGEROUS_GIT_ENV_VARS = {
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH",
    "PYTHONPATH",
    "PYTHONHOME",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_KEY_0",
    "GIT_CONFIG_VALUE_0",
    "GIT_CEILING_DIRECTORIES",
    "GIT_SSH",
    "GIT_SSH_COMMAND",
    "GIT_ASKPASS",
    "GIT_EXTERNAL_DIFF",
    "BASH_ENV",
    "ENV",
}

# Regex for safe git ref / revision names (SHA, branch, tag, HEAD, HEAD~N, HEAD^N, HEAD@{N})
SAFE_REF_PATTERN = re.compile(r"^[a-zA-Z0-9_\-./~^@{}]+$")


# ── Environment & Subprocess Helpers ──────────────────────────────────────────

def _get_git_env() -> dict[str, str]:
    """Builds a sanitized environment dictionary stripping dangerous git redirection vars and secrets."""
    safe_env: dict[str, str] = {}
    for k, v in os.environ.items():
        k_upper = k.upper()
        if k in DANGEROUS_GIT_ENV_VARS or k_upper in DANGEROUS_GIT_ENV_VARS:
            continue
        if any(keyword in k_upper for keyword in SENSITIVE_ENV_KEYWORDS):
            continue
        safe_env[k] = v

    # Non-interactive, no prompt, no pager, deterministic
    safe_env["GIT_TERMINAL_PROMPT"] = "0"
    safe_env["GIT_OPTIONAL_LOCKS"] = "0"
    return safe_env


def _run_git(
    cmd: list[str],
    cwd: Path,
    timeout: int = SUBPROCESS_TIMEOUT_SECONDS,
) -> tuple[int, str, str]:
    """Executes a git command with sanitized environment, no shell, and bounded timeout."""
    full_cmd = ["git", "--no-pager"] + cmd
    try:
        proc = subprocess.run(
            full_cmd,
            cwd=str(cwd),
            env=_get_git_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Git command timed out after {timeout} seconds"
    except FileNotFoundError:
        return -1, "", "Git executable not found in system PATH"
    except Exception as e:
        return -1, "", f"Unexpected error executing git: {e}"


# ── Validation & Path Confinement Helpers ─────────────────────────────────────

def _resolve_repo_root(request: ToolRequest) -> tuple[Path | None, str | None]:
    context_repo = request.context.get("repo_path")
    arg_repo = request.arguments.get("repo_path")
    return ToolSafetyPolicy.resolve_and_validate_repo_root(
        context_repo_path=context_repo,
        argument_repo_path=arg_repo,
    )


def _resolve_target_path(
    repo_root: Path,
    rel_path: str | None,
) -> tuple[Path | None, str | None]:
    if not rel_path or rel_path.strip() in ("", "."):
        return repo_root, None

    if Path(rel_path.replace("\\", "/")).is_absolute():
        return None, f"Absolute path is not permitted; use a repository-relative path: '{rel_path}'"

    norm = rel_path.replace("\\", "/").strip("/")
    parts = Path(norm).parts
    if ".." in parts:
        return None, f"Path traversal via '..' is not permitted: '{rel_path}'"

    candidate = repo_root / norm
    try:
        resolved = candidate.resolve()
    except OSError as e:
        return None, f"Cannot resolve path '{rel_path}': {e}"

    try:
        resolved.relative_to(repo_root)
    except ValueError:
        return None, f"Path '{rel_path}' escapes repository boundary (symlink or traversal detected)"

    return resolved, None


def _validate_git_ref(ref: Any, name: str = "ref") -> tuple[str | None, str | None]:
    """Validates that a git ref/commit string is safe and not an option flag."""
    if ref is None:
        return None, None
    if not isinstance(ref, str) or not ref.strip():
        return None, f"Git {name} must be a non-empty string"

    clean_ref = ref.strip()
    if clean_ref.startswith("-"):
        return None, f"Git {name} cannot begin with a dash: '{clean_ref}'"

    if not SAFE_REF_PATTERN.match(clean_ref):
        return None, f"Git {name} contains forbidden characters: '{clean_ref}'"

    if ".." in clean_ref:
        return None, f"Git {name} cannot contain '..' (for ranges, use from_commit/to_commit): '{clean_ref}'"

    return clean_ref, None


def _clean_porcelain_path(raw: str) -> str:
    p = raw.strip()
    if p.startswith('"') and p.endswith('"') and len(p) >= 2:
        p = p[1:-1]
    return p


# ── GitTool Adapter ───────────────────────────────────────────────────────────

class GitTool(BaseTool):
    """
    Controlled repository-scoped Git capability tool adapter.

    Supported operations (via ToolRequest.operation):
      - status        : Working tree status, branch info, staged/unstaged changes.
      - diff          : Bounded working tree, staged, or commit diff.
      - log           : Recent commit history with structured metadata.
      - changed_files : List of changed file paths and change types.

    Security & Safety Guarantees:
      - Strictly read-only: mutating git commands (commit, push, checkout, reset, etc.) are rejected.
      - Confinement: Validates repository path against ToolSafetyPolicy; blocks traversal and outside symlinks.
      - Option injection defense: Blocks leading dashes on refs, paths, and commits; enforces '--' separator.
      - Sanitized environment: Strips GIT_DIR, GIT_WORK_TREE, credentials, and hijacking variables.
      - Bounded execution: Limits output length, commit counts, and execution timeouts.
    """

    name: str = "git"
    description: str = (
        "Repository-scoped Git tool: inspect repository status, view bounded diffs, "
        "retrieve structured commit history, and examine changed files."
    )

    def execute(self, request: ToolRequest) -> ToolResult:
        # 1. Base validation (type check and tool_name check)
        is_valid, val_err = self.validate_request(request)
        if not is_valid:
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=getattr(request, "operation", "unknown"),
                error=f"Request validation failed: {val_err}",
            )

        op = request.operation

        # 2. Strict read-only operation check
        if op not in SUPPORTED_OPERATIONS:
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=op,
                error=(
                    f"Unsupported or mutating git operation: '{op}'. "
                    f"Supported read-only operations: {sorted(SUPPORTED_OPERATIONS)}"
                ),
            )

        # 3. Resolve and validate repository root
        repo_root, repo_err = _resolve_repo_root(request)
        if repo_err or not repo_root:
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=op,
                error=f"Repository validation error: {repo_err}",
            )

        # 4. Verify directory is a valid git repository
        rc, out, err = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=repo_root)
        if rc != 0 or out.strip() != "true":
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=op,
                error=f"Directory is not a Git repository: '{repo_root}'",
            )

        # 5. Dispatch to operation handler
        if op == "status":
            return self._status(request, repo_root)
        elif op == "diff":
            return self._diff(request, repo_root)
        elif op == "log":
            return self._log(request, repo_root)
        elif op == "changed_files":
            return self._changed_files(request, repo_root)

        return ToolResult.create_failure(
            tool_name=self.name,
            operation=op,
            error=f"Unhandled operation '{op}'",
        )

    # ── Operation: status ─────────────────────────────────────────────────────

    def _status(self, request: ToolRequest, repo_root: Path) -> ToolResult:
        # Branch
        rc, out_branch, _ = _run_git(["branch", "--show-current"], cwd=repo_root)
        branch: str | None = out_branch.strip() or None
        if not branch:
            # Detached HEAD or newborn repo
            rc_sym, out_sym, _ = _run_git(["symbolic-ref", "--short", "HEAD"], cwd=repo_root)
            if rc_sym == 0 and out_sym.strip():
                branch = out_sym.strip()
            else:
                rc_desc, out_desc, _ = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo_root)
                if rc_desc == 0 and out_desc.strip():
                    branch = f"(detached HEAD at {out_desc.strip()})"
                else:
                    branch = "(unborn)"

        # HEAD commit
        rc_head, out_head, _ = _run_git(["rev-parse", "HEAD"], cwd=repo_root)
        head_commit: str | None = out_head.strip() if rc_head == 0 and out_head.strip() else None

        # Porcelain status
        rc_stat, out_stat, err_stat = _run_git(["status", "--porcelain=v1", "-uall"], cwd=repo_root)
        if rc_stat != 0:
            return ToolResult.create_failure(
                tool_name=self.name,
                operation="status",
                error=f"git status failed: {err_stat.strip()}",
                metadata={"repo_path": str(repo_root)},
            )

        staged: list[dict[str, Any]] = []
        unstaged: list[dict[str, Any]] = []
        untracked: list[str] = []

        status_name_map = {
            "M": "modified",
            "A": "added",
            "D": "deleted",
            "R": "renamed",
            "C": "copied",
            "T": "type_changed",
        }

        for line in out_stat.splitlines():
            if not line or len(line) < 3:
                continue
            x = line[0]
            y = line[1]
            raw_path = line[3:].strip()

            if " -> " in raw_path:
                parts = raw_path.split(" -> ", 1)
                old_p = _clean_porcelain_path(parts[0])
                new_p = _clean_porcelain_path(parts[1])
            else:
                old_p = None
                new_p = _clean_porcelain_path(raw_path)

            if x == "?" and y == "?":
                untracked.append(new_p)
                continue

            if x in status_name_map:
                entry = {"path": new_p, "status": status_name_map[x]}
                if old_p:
                    entry["old_path"] = old_p
                staged.append(entry)

            if y in status_name_map:
                entry = {"path": new_p, "status": status_name_map[y]}
                if old_p:
                    entry["old_path"] = old_p
                unstaged.append(entry)

        is_clean = len(staged) == 0 and len(unstaged) == 0 and len(untracked) == 0

        # Ahead / Behind if upstream is configured
        ahead: int | None = None
        behind: int | None = None
        if branch and not branch.startswith("("):
            rc_ab, out_ab, _ = _run_git(
                ["rev-list", "--left-right", "--count", f"{branch}...@{{upstream}}"],
                cwd=repo_root,
            )
            if rc_ab == 0 and out_ab.strip():
                parts = out_ab.strip().split()
                if len(parts) == 2:
                    try:
                        ahead = int(parts[0])
                        behind = int(parts[1])
                    except ValueError:
                        pass

        output_data = {
            "branch": branch,
            "head_commit": head_commit,
            "is_clean": is_clean,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "ahead": ahead,
            "behind": behind,
            "counts": {
                "staged": len(staged),
                "unstaged": len(unstaged),
                "untracked": len(untracked),
            },
        }

        return ToolResult.create_success(
            tool_name=self.name,
            operation="status",
            output=output_data,
            metadata={"repo_path": str(repo_root), "is_clean": is_clean},
        )

    # ── Operation: diff ───────────────────────────────────────────────────────

    def _diff(self, request: ToolRequest, repo_root: Path) -> ToolResult:
        args = request.arguments
        staged = bool(args.get("staged") or args.get("cached", False))
        path_arg = args.get("path") or args.get("file_path")
        commit_arg = args.get("commit") or args.get("ref")
        from_commit_arg = args.get("from_commit")
        to_commit_arg = args.get("to_commit")

        # Ref validations
        commit_clean, c_err = _validate_git_ref(commit_arg, "commit")
        if c_err:
            return ToolResult.create_failure(tool_name=self.name, operation="diff", error=c_err)

        from_clean, f_err = _validate_git_ref(from_commit_arg, "from_commit")
        if f_err:
            return ToolResult.create_failure(tool_name=self.name, operation="diff", error=f_err)

        to_clean, t_err = _validate_git_ref(to_commit_arg, "to_commit")
        if t_err:
            return ToolResult.create_failure(tool_name=self.name, operation="diff", error=t_err)

        # Context lines
        try:
            context_lines = max(0, min(100, int(args.get("context_lines", 3))))
        except (ValueError, TypeError):
            context_lines = 3

        # Max output chars limit
        try:
            req_max = int(args.get("max_chars", DEFAULT_MAX_DIFF_CHARS))
            max_chars = min(max(req_max, 100), MAX_DIFF_CHARS_CAP)
        except (ValueError, TypeError):
            max_chars = DEFAULT_MAX_DIFF_CHARS

        # Target path validation
        rel_path: str | None = None
        if path_arg:
            target_path, path_err = _resolve_target_path(repo_root, str(path_arg))
            if path_err or not target_path:
                return ToolResult.create_failure(
                    tool_name=self.name,
                    operation="diff",
                    error=f"Invalid target path: {path_err}",
                )
            rel_path = str(target_path.relative_to(repo_root))

        cmd: list[str] = ["diff", f"-U{context_lines}"]

        if from_clean and to_clean:
            cmd.extend([from_clean, to_clean])
        elif commit_clean:
            cmd.append(commit_clean)
        elif staged:
            cmd.append("--staged")

        if rel_path:
            cmd.extend(["--", rel_path])

        rc, stdout, stderr = _run_git(cmd, cwd=repo_root)
        if rc != 0:
            return ToolResult.create_failure(
                tool_name=self.name,
                operation="diff",
                error=f"git diff failed: {stderr.strip()}",
                metadata={"repo_path": str(repo_root)},
            )

        total_chars = len(stdout)
        is_truncated = total_chars > max_chars
        diff_text = stdout[:max_chars]
        if is_truncated:
            diff_text += f"\n... [Diff truncated at {max_chars} characters (total: {total_chars})]"

        output_data = {
            "diff": diff_text,
            "truncated": is_truncated,
            "total_chars": total_chars,
            "staged": staged,
            "path": rel_path,
            "commit": commit_clean,
            "from_commit": from_clean,
            "to_commit": to_clean,
        }

        return ToolResult.create_success(
            tool_name=self.name,
            operation="diff",
            output=output_data,
            metadata={
                "repo_path": str(repo_root),
                "truncated": is_truncated,
                "total_chars": total_chars,
            },
        )

    # ── Operation: log ────────────────────────────────────────────────────────

    def _log(self, request: ToolRequest, repo_root: Path) -> ToolResult:
        args = request.arguments
        ref_arg = args.get("revision") or args.get("ref", "HEAD")
        path_arg = args.get("path") or args.get("file_path")

        # Check if repository has any commits yet
        rc_check, _, _ = _run_git(["rev-parse", "--verify", "HEAD"], cwd=repo_root)
        if rc_check != 0:
            return ToolResult.create_success(
                tool_name=self.name,
                operation="log",
                output={
                    "commits": [],
                    "count": 0,
                    "ref": str(ref_arg),
                    "empty_repo": True,
                },
                metadata={"repo_path": str(repo_root), "empty_repo": True},
            )

        ref_clean, ref_err = _validate_git_ref(ref_arg, "revision/ref")
        if ref_err:
            return ToolResult.create_failure(tool_name=self.name, operation="log", error=ref_err)

        ref_clean = ref_clean or "HEAD"

        try:
            req_limit = int(args.get("limit") or args.get("max_count", DEFAULT_LOG_LIMIT))
            limit = min(max(req_limit, 1), MAX_LOG_LIMIT)
        except (ValueError, TypeError):
            limit = DEFAULT_LOG_LIMIT

        try:
            skip = max(0, int(args.get("skip", 0)))
        except (ValueError, TypeError):
            skip = 0

        rel_path: str | None = None
        if path_arg:
            target_path, path_err = _resolve_target_path(repo_root, str(path_arg))
            if path_err or not target_path:
                return ToolResult.create_failure(
                    tool_name=self.name,
                    operation="log",
                    error=f"Invalid target path: {path_err}",
                )
            rel_path = str(target_path.relative_to(repo_root))

        # Format: %H (hash), %h (short), %an (author), %ae (email), %aI (iso date), %s (subject), %P (parents)
        format_str = "%H%x1f%h%x1f%an%x1f%ae%x1f%aI%x1f%s%x1f%P%x1e"
        cmd = ["log", f"-n{limit}", f"--skip={skip}", f"--format={format_str}", ref_clean]

        if rel_path:
            cmd.extend(["--", rel_path])

        rc, stdout, stderr = _run_git(cmd, cwd=repo_root)
        if rc != 0:
            return ToolResult.create_failure(
                tool_name=self.name,
                operation="log",
                error=f"git log failed: {stderr.strip()}",
                metadata={"repo_path": str(repo_root)},
            )

        commits: list[dict[str, Any]] = []
        raw_entries = stdout.split("\x1e")

        for entry in raw_entries:
            entry_clean = entry.strip()
            if not entry_clean:
                continue
            fields = entry_clean.split("\x1f")
            if len(fields) >= 6:
                full_hash = fields[0]
                short_hash = fields[1]
                author_name = fields[2]
                author_email = fields[3]
                date_iso = fields[4]
                subject = fields[5]
                parents_str = fields[6] if len(fields) > 6 else ""
                parents = parents_str.strip().split() if parents_str.strip() else []

                commits.append({
                    "commit": full_hash,
                    "short_hash": short_hash,
                    "author": author_name,
                    "email": author_email,
                    "date": date_iso,
                    "message": subject,
                    "parents": parents,
                })

        output_data = {
            "commits": commits,
            "count": len(commits),
            "ref": ref_clean,
            "limit": limit,
            "skip": skip,
            "path": rel_path,
        }

        return ToolResult.create_success(
            tool_name=self.name,
            operation="log",
            output=output_data,
            metadata={"repo_path": str(repo_root), "commit_count": len(commits)},
        )

    # ── Operation: changed_files ──────────────────────────────────────────────

    def _changed_files(self, request: ToolRequest, repo_root: Path) -> ToolResult:
        args = request.arguments
        from_arg = args.get("from_commit") or args.get("base")
        to_arg = args.get("to_commit") or args.get("target")
        staged_only = bool(args.get("staged", False))

        try:
            req_limit = int(args.get("limit", DEFAULT_CHANGED_FILES_LIMIT))
            limit = min(max(req_limit, 1), MAX_CHANGED_FILES_LIMIT)
        except (ValueError, TypeError):
            limit = DEFAULT_CHANGED_FILES_LIMIT

        status_code_map = {
            "A": "added",
            "M": "modified",
            "D": "deleted",
            "R": "renamed",
            "C": "copied",
            "T": "type_changed",
        }

        # ── Mode A: Compare between two revisions ─────────────────────────────
        if from_arg:
            from_clean, f_err = _validate_git_ref(from_arg, "from_commit/base")
            if f_err:
                return ToolResult.create_failure(tool_name=self.name, operation="changed_files", error=f_err)

            to_clean, t_err = _validate_git_ref(to_arg, "to_commit/target")
            if t_err:
                return ToolResult.create_failure(tool_name=self.name, operation="changed_files", error=t_err)

            to_clean = to_clean or "HEAD"

            rc, stdout, stderr = _run_git(["diff", "--name-status", from_clean, to_clean], cwd=repo_root)
            if rc != 0:
                return ToolResult.create_failure(
                    tool_name=self.name,
                    operation="changed_files",
                    error=f"git diff --name-status failed: {stderr.strip()}",
                    metadata={"repo_path": str(repo_root)},
                )

            files: list[dict[str, Any]] = []
            summary = {"added": 0, "modified": 0, "deleted": 0, "renamed": 0, "other": 0}

            for line in stdout.splitlines():
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                code = parts[0].strip()
                primary_code = code[0] if code else "M"
                status_name = status_code_map.get(primary_code, "other")

                item: dict[str, Any] = {
                    "path": parts[1].strip(),
                    "status": status_name,
                    "code": code,
                }
                if primary_code == "R" and len(parts) > 2:
                    item["old_path"] = parts[1].strip()
                    item["path"] = parts[2].strip()
                elif primary_code == "C" and len(parts) > 2:
                    item["source_path"] = parts[1].strip()
                    item["path"] = parts[2].strip()

                if status_name in summary:
                    summary[status_name] += 1
                else:
                    summary["other"] += 1

                files.append(item)

            total_files = len(files)
            truncated = total_files > limit
            files_bounded = files[:limit]

            return ToolResult.create_success(
                tool_name=self.name,
                operation="changed_files",
                output={
                    "files": files_bounded,
                    "total_files": total_files,
                    "truncated": truncated,
                    "summary": summary,
                    "from_commit": from_clean,
                    "to_commit": to_clean,
                },
                metadata={
                    "repo_path": str(repo_root),
                    "total_files": total_files,
                    "truncated": truncated,
                },
            )

        # ── Mode B: Working-tree changes (staged, unstaged, untracked) ─────────
        files: list[dict[str, Any]] = []
        summary = {"added": 0, "modified": 0, "deleted": 0, "renamed": 0, "untracked": 0, "other": 0}

        # 1. Staged changes
        rc_staged, out_staged, err_staged = _run_git(["diff", "--name-status", "--staged"], cwd=repo_root)
        if rc_staged != 0:
            return ToolResult.create_failure(
                tool_name=self.name,
                operation="changed_files",
                error=f"git diff --staged failed: {err_staged.strip()}",
                metadata={"repo_path": str(repo_root)},
            )

        for line in out_staged.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            code = parts[0].strip()
            primary_code = code[0] if code else "M"
            status_name = status_code_map.get(primary_code, "other")
            item = {
                "path": parts[1].strip(),
                "status": status_name,
                "staged": True,
                "code": code,
            }
            if primary_code == "R" and len(parts) > 2:
                item["old_path"] = parts[1].strip()
                item["path"] = parts[2].strip()

            if status_name in summary:
                summary[status_name] += 1
            else:
                summary["other"] += 1
            files.append(item)

        # If staged_only requested, return immediately
        if staged_only:
            total_files = len(files)
            truncated = total_files > limit
            return ToolResult.create_success(
                tool_name=self.name,
                operation="changed_files",
                output={
                    "files": files[:limit],
                    "total_files": total_files,
                    "truncated": truncated,
                    "summary": summary,
                    "staged_only": True,
                },
                metadata={"repo_path": str(repo_root), "total_files": total_files},
            )

        # 2. Unstaged changes
        rc_unstaged, out_unstaged, err_unstaged = _run_git(["diff", "--name-status"], cwd=repo_root)
        if rc_unstaged == 0 and out_unstaged:
            for line in out_unstaged.splitlines():
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                code = parts[0].strip()
                primary_code = code[0] if code else "M"
                status_name = status_code_map.get(primary_code, "other")
                item = {
                    "path": parts[1].strip(),
                    "status": status_name,
                    "staged": False,
                    "code": code,
                }
                if primary_code == "R" and len(parts) > 2:
                    item["old_path"] = parts[1].strip()
                    item["path"] = parts[2].strip()

                if status_name in summary:
                    summary[status_name] += 1
                else:
                    summary["other"] += 1
                files.append(item)

        # 3. Untracked files
        rc_porc, out_porc, _ = _run_git(["status", "--porcelain=v1", "-uall"], cwd=repo_root)
        if rc_porc == 0 and out_porc:
            for line in out_porc.splitlines():
                if line.startswith("?? "):
                    u_path = _clean_porcelain_path(line[3:])
                    files.append({
                        "path": u_path,
                        "status": "untracked",
                        "staged": False,
                        "code": "??",
                    })
                    summary["untracked"] += 1

        total_files = len(files)
        truncated = total_files > limit

        return ToolResult.create_success(
            tool_name=self.name,
            operation="changed_files",
            output={
                "files": files[:limit],
                "total_files": total_files,
                "truncated": truncated,
                "summary": summary,
                "staged_only": False,
            },
            metadata={
                "repo_path": str(repo_root),
                "total_files": total_files,
                "truncated": truncated,
            },
        )
