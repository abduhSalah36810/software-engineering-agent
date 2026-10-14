"""
Phase 5 — Tooling & Capability Foundation: File System / Code Tool.

Provides a repository-scoped, read-first file system capability tool adapter:
  - list_dir    : Lists immediate children of a repository-relative directory.
  - read_file   : Reads a repository file as bounded text, rejecting binary files.
  - search_text : Searches text/code within the repository, bounded results.
  - patch_file  : Applies a controlled exact-match replacement in a file (requires
                  explicit trusted allow_mutations authorization).

Design invariants:
  - All paths are validated and confined within the repository root.
  - Symlinks that escape the repository root are rejected.
  - Binary files are detected via null-byte scan (no subprocess).
  - Operations are bounded: read is capped at MAX_READ_BYTES; search at MAX_SEARCH_MATCHES.
  - Mutation operations (patch_file) require context["allow_mutations"] is True.
    Caller arguments["allow_mutations"] cannot elevate privilege.
  - No shell=True, no network, no LLM.
  - Integrates with ToolRegistry via BaseTool/ToolRequest/ToolResult contract.
  - Does NOT overlap with the HTTP Repository Explorer API (Codex-owned).
  - Does NOT duplicate TerminalTool (no subprocess command execution).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.tools.base import BaseTool
from src.tools.models import ToolRequest, ToolResult
from src.tools.security import ToolSafetyPolicy


# ── Constants ─────────────────────────────────────────────────────────────────

MAX_READ_BYTES: int = 256_000  # ~256 KB
MAX_SEARCH_MATCHES: int = 200

BINARY_EXTENSIONS: frozenset[str] = frozenset({
    ".pyc", ".pyo", ".pyd", ".so", ".o", ".a", ".lib", ".dll", ".dylib",
    ".obj", ".class", ".jar", ".war", ".ear",
    ".exe", ".bin", ".elf", ".msi", ".apk", ".deb", ".rpm",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".zst", ".7z", ".rar", ".whl",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg",
    ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".wav", ".ogg",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".db", ".sqlite", ".sqlite3",
    ".pkl", ".pickle", ".npy", ".npz",
    ".pdf", ".docx", ".xlsx", ".pptx",
})

IGNORED_SEARCH_DIRS: frozenset[str] = frozenset({
    ".git", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "node_modules", ".venv", "venv", "env", ".env",
    "dist", "build", ".next", ".nuxt", "coverage",
    ".eggs",
})


# ── Binary Detection ──────────────────────────────────────────────────────────

def _is_binary_by_extension(path: Path) -> bool:
    return path.suffix.lower() in BINARY_EXTENSIONS


def _is_binary_by_content(path: Path, sample_bytes: int = 512) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_bytes)
        return b"\x00" in chunk
    except OSError:
        return True


def _is_binary(path: Path) -> bool:
    return _is_binary_by_extension(path) or _is_binary_by_content(path)


# ── Path Utilities ────────────────────────────────────────────────────────────

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

    # Check for absolute path BEFORE stripping leading slashes
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


# ── Authorization ─────────────────────────────────────────────────────────────

def _resolve_mutation_auth(request: ToolRequest) -> tuple[bool, str | None]:
    return ToolSafetyPolicy.resolve_mutation_authorization(
        context=request.context,
        arguments=request.arguments,
    )


# ── FileSystemTool ────────────────────────────────────────────────────────────

class FileSystemTool(BaseTool):
    """
    Repository-scoped file system / code tool adapter.

    Supported operations (via ToolRequest.operation):
      - list_dir    : Lists immediate children of a repository directory.
      - read_file   : Reads a file as bounded UTF-8 text.
      - search_text : Searches text/code patterns within the repository.
      - patch_file  : Exact-match replacement in a file (mutations only).

    All operations:
      - Require context["repo_path"] (trusted) or arguments["repo_path"].
      - Validate all paths against the repository root.
      - Reject symlink escapes, traversal, and absolute paths.
      - Reject binary files on read_file.

    Mutation operation (patch_file):
      - Requires context["allow_mutations"] is True.
      - Caller arguments["allow_mutations"] cannot grant authorization.
    """

    name: str = "filesystem"
    description: str = (
        "Repository-scoped file system tool: list directory contents, "
        "read files as bounded text, search code/text patterns, "
        "and apply controlled file patches."
    )

    def execute(self, request: ToolRequest) -> ToolResult:
        is_valid, err = self.validate_request(request)
        if not is_valid:
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=request.operation,
                error=f"Request validation failed: {err}",
            )

        op = request.operation

        if op == "list_dir":
            return self._list_dir(request)
        elif op == "read_file":
            return self._read_file(request)
        elif op == "search_text":
            return self._search_text(request)
        elif op == "patch_file":
            return self._patch_file(request)
        else:
            return ToolResult.create_failure(
                tool_name=self.name,
                operation=op,
                error=(
                    f"Unknown operation '{op}'. "
                    f"Supported: list_dir, read_file, search_text, patch_file."
                ),
            )

    # ── list_dir ──────────────────────────────────────────────────────────────

    def _list_dir(self, request: ToolRequest) -> ToolResult:
        repo_root, repo_err = _resolve_repo_root(request)
        if repo_err or not repo_root:
            return ToolResult.create_failure(
                tool_name=self.name, operation="list_dir",
                error=f"Repository boundary error: {repo_err}",
            )

        rel_path = request.arguments.get("path", "")
        target, path_err = _resolve_target_path(repo_root, rel_path)
        if path_err or not target:
            return ToolResult.create_failure(
                tool_name=self.name, operation="list_dir",
                error=f"Path error: {path_err}",
            )

        if not target.exists():
            return ToolResult.create_failure(
                tool_name=self.name, operation="list_dir",
                error=f"Directory does not exist: '{rel_path or '.'}'",
            )

        if not target.is_dir():
            return ToolResult.create_failure(
                tool_name=self.name, operation="list_dir",
                error=f"Path is not a directory: '{rel_path or '.'}'",
            )

        try:
            entries: list[dict[str, Any]] = []
            for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                entry: dict[str, Any] = {"name": child.name}

                if child.is_symlink():
                    entry["type"] = "symlink"
                    entry["size_bytes"] = None
                    entry["is_binary"] = None
                elif child.is_dir():
                    entry["type"] = "dir"
                    entry["size_bytes"] = None
                    entry["is_binary"] = None
                else:
                    entry["type"] = "file"
                    try:
                        entry["size_bytes"] = child.stat().st_size
                    except OSError:
                        entry["size_bytes"] = None
                    entry["is_binary"] = _is_binary_by_extension(child)

                entries.append(entry)

            try:
                display_path = str(target.relative_to(repo_root)) if target != repo_root else "."
            except ValueError:
                display_path = "."

            return ToolResult.create_success(
                tool_name=self.name,
                operation="list_dir",
                output={"path": display_path, "entries": entries},
                metadata={"entry_count": len(entries), "repo_root": str(repo_root)},
            )

        except PermissionError as e:
            return ToolResult.create_failure(
                tool_name=self.name, operation="list_dir",
                error=f"Permission denied listing directory '{rel_path or '.'}': {e}",
            )
        except OSError as e:
            return ToolResult.create_failure(
                tool_name=self.name, operation="list_dir",
                error=f"OS error listing directory '{rel_path or '.'}': {e}",
            )

    # ── read_file ─────────────────────────────────────────────────────────────

    def _read_file(self, request: ToolRequest) -> ToolResult:
        repo_root, repo_err = _resolve_repo_root(request)
        if repo_err or not repo_root:
            return ToolResult.create_failure(
                tool_name=self.name, operation="read_file",
                error=f"Repository boundary error: {repo_err}",
            )

        rel_path = request.arguments.get("path", "")
        if not rel_path:
            return ToolResult.create_failure(
                tool_name=self.name, operation="read_file",
                error="'path' argument is required for read_file",
            )

        target, path_err = _resolve_target_path(repo_root, rel_path)
        if path_err or not target:
            return ToolResult.create_failure(
                tool_name=self.name, operation="read_file",
                error=f"Path error: {path_err}",
            )

        if not target.exists():
            return ToolResult.create_failure(
                tool_name=self.name, operation="read_file",
                error=f"File does not exist: '{rel_path}'",
            )

        if not target.is_file():
            return ToolResult.create_failure(
                tool_name=self.name, operation="read_file",
                error=f"Path is not a regular file: '{rel_path}'",
            )

        if _is_binary(target):
            return ToolResult.create_failure(
                tool_name=self.name, operation="read_file",
                error=f"File '{rel_path}' appears to be binary and cannot be read as text",
            )

        try:
            file_size = target.stat().st_size
        except OSError as e:
            return ToolResult.create_failure(
                tool_name=self.name, operation="read_file",
                error=f"Cannot stat file '{rel_path}': {e}",
            )

        max_bytes_arg = request.arguments.get("max_bytes")
        if max_bytes_arg is not None:
            try:
                max_bytes = min(int(max_bytes_arg), MAX_READ_BYTES)
                if max_bytes <= 0:
                    max_bytes = MAX_READ_BYTES
            except (ValueError, TypeError):
                max_bytes = MAX_READ_BYTES
        else:
            max_bytes = MAX_READ_BYTES

        if file_size > max_bytes:
            return ToolResult.create_failure(
                tool_name=self.name, operation="read_file",
                error=(
                    f"File '{rel_path}' is {file_size} bytes, "
                    f"which exceeds the {max_bytes}-byte read limit. "
                    f"Use start_line/end_line to read a subsection."
                ),
                metadata={"file_size_bytes": file_size, "max_bytes": max_bytes},
            )

        try:
            raw = target.read_bytes()
            content = raw.decode("utf-8", errors="replace")
        except OSError as e:
            return ToolResult.create_failure(
                tool_name=self.name, operation="read_file",
                error=f"Error reading file '{rel_path}': {e}",
            )

        lines = content.splitlines(keepends=True)
        total_lines = len(lines)

        start_line_arg = request.arguments.get("start_line")
        end_line_arg = request.arguments.get("end_line")

        try:
            start_line = max(1, int(start_line_arg)) if start_line_arg is not None else 1
        except (ValueError, TypeError):
            start_line = 1

        try:
            end_line = min(total_lines, int(end_line_arg)) if end_line_arg is not None else total_lines
        except (ValueError, TypeError):
            end_line = total_lines

        start_line = max(1, min(start_line, total_lines + 1))
        end_line = max(start_line - 1, min(end_line, total_lines))

        sliced = lines[start_line - 1:end_line]
        slice_content = "".join(sliced)

        try:
            display_path = str(target.relative_to(repo_root))
        except ValueError:
            display_path = rel_path

        return ToolResult.create_success(
            tool_name=self.name,
            operation="read_file",
            output={
                "path": display_path,
                "content": slice_content,
                "total_lines": total_lines,
                "start_line": start_line,
                "end_line": end_line,
                "truncated": False,
            },
            metadata={
                "file_size_bytes": file_size,
                "encoding": "utf-8",
                "repo_root": str(repo_root),
            },
        )

    # ── search_text ───────────────────────────────────────────────────────────

    def _search_text(self, request: ToolRequest) -> ToolResult:
        repo_root, repo_err = _resolve_repo_root(request)
        if repo_err or not repo_root:
            return ToolResult.create_failure(
                tool_name=self.name, operation="search_text",
                error=f"Repository boundary error: {repo_err}",
            )

        pattern = request.arguments.get("pattern", "")
        if not pattern:
            return ToolResult.create_failure(
                tool_name=self.name, operation="search_text",
                error="'pattern' argument is required for search_text",
            )

        rel_search_path = request.arguments.get("path", "")
        search_root, path_err = _resolve_target_path(repo_root, rel_search_path)
        if path_err or not search_root:
            return ToolResult.create_failure(
                tool_name=self.name, operation="search_text",
                error=f"Path error: {path_err}",
            )

        if not search_root.exists():
            return ToolResult.create_failure(
                tool_name=self.name, operation="search_text",
                error=f"Search path does not exist: '{rel_search_path or '.'}'",
            )

        case_sensitive: bool = bool(request.arguments.get("case_sensitive", True))
        include_exts_raw = request.arguments.get("include_extensions")
        include_exts: set[str] | None = None
        if include_exts_raw and isinstance(include_exts_raw, list):
            include_exts = {
                (ext if ext.startswith(".") else f".{ext}").lower()
                for ext in include_exts_raw
            }

        max_matches_arg = request.arguments.get("max_matches")
        try:
            max_matches = min(int(max_matches_arg), MAX_SEARCH_MATCHES) if max_matches_arg else MAX_SEARCH_MATCHES
        except (ValueError, TypeError):
            max_matches = MAX_SEARCH_MATCHES

        search_pattern = pattern if case_sensitive else pattern.lower()

        matches: list[dict[str, Any]] = []
        total_matches = 0
        truncated = False

        def _should_skip_dir(dirpath: Path) -> bool:
            return dirpath.name in IGNORED_SEARCH_DIRS

        def _search_file(fpath: Path) -> None:
            nonlocal total_matches, truncated
            if truncated and total_matches >= max_matches:
                return
            if include_exts is not None and fpath.suffix.lower() not in include_exts:
                return
            if _is_binary_by_extension(fpath):
                return
            try:
                size = fpath.stat().st_size
            except OSError:
                return
            if size > MAX_READ_BYTES:
                return
            try:
                raw = fpath.read_bytes()
            except OSError:
                return
            if b"\x00" in raw[:512]:
                return
            try:
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                return

            try:
                rel_file = str(fpath.relative_to(repo_root))
            except ValueError:
                return

            for line_no, line in enumerate(text.splitlines(), start=1):
                if total_matches >= max_matches:
                    truncated = True
                    return
                compare_line = line if case_sensitive else line.lower()
                idx = compare_line.find(search_pattern)
                if idx != -1:
                    total_matches += 1
                    matches.append({
                        "file": rel_file,
                        "line_number": line_no,
                        "line": line.rstrip("\n\r"),
                        "match_start": idx,
                    })

        if search_root.is_file():
            _search_file(search_root)
        else:
            for dirpath_str, dirnames, filenames in os.walk(str(search_root)):
                dirpath = Path(dirpath_str)
                dirnames[:] = [
                    d for d in dirnames
                    if not _should_skip_dir(dirpath / d)
                ]
                for filename in sorted(filenames):
                    if truncated and total_matches >= max_matches:
                        break
                    _search_file(dirpath / filename)
                if truncated and total_matches >= max_matches:
                    break

        try:
            display_search_path = str(search_root.relative_to(repo_root)) if search_root != repo_root else "."
        except ValueError:
            display_search_path = "."

        return ToolResult.create_success(
            tool_name=self.name,
            operation="search_text",
            output={
                "pattern": pattern,
                "search_path": display_search_path,
                "case_sensitive": case_sensitive,
                "matches": matches,
                "total_matches": total_matches,
                "truncated": truncated,
            },
            metadata={
                "max_matches": max_matches,
                "repo_root": str(repo_root),
            },
        )

    # ── patch_file ────────────────────────────────────────────────────────────

    def _patch_file(self, request: ToolRequest) -> ToolResult:
        # 1. Mutation authorization (trusted context only)
        allow_mutations, auth_err = _resolve_mutation_auth(request)
        if auth_err:
            return ToolResult.create_failure(
                tool_name=self.name, operation="patch_file",
                error=f"Authorization error: {auth_err}",
            )
        if not allow_mutations:
            return ToolResult.create_failure(
                tool_name=self.name, operation="patch_file",
                error=(
                    "patch_file requires explicit trusted authorization: "
                    "context['allow_mutations'] must be True"
                ),
            )

        # 2. Repository root
        repo_root, repo_err = _resolve_repo_root(request)
        if repo_err or not repo_root:
            return ToolResult.create_failure(
                tool_name=self.name, operation="patch_file",
                error=f"Repository boundary error: {repo_err}",
            )

        # 3. Target path
        rel_path = request.arguments.get("path", "")
        if not rel_path:
            return ToolResult.create_failure(
                tool_name=self.name, operation="patch_file",
                error="'path' argument is required for patch_file",
            )

        target, path_err = _resolve_target_path(repo_root, rel_path)
        if path_err or not target:
            return ToolResult.create_failure(
                tool_name=self.name, operation="patch_file",
                error=f"Path error: {path_err}",
            )

        if not target.exists():
            return ToolResult.create_failure(
                tool_name=self.name, operation="patch_file",
                error=f"File does not exist: '{rel_path}'",
            )

        if not target.is_file():
            return ToolResult.create_failure(
                tool_name=self.name, operation="patch_file",
                error=f"Path is not a regular file: '{rel_path}'",
            )

        if _is_binary(target):
            return ToolResult.create_failure(
                tool_name=self.name, operation="patch_file",
                error=f"File '{rel_path}' appears to be binary; patch_file only supports text files",
            )

        # 4. Patch arguments
        old_content = request.arguments.get("old_content")
        new_content = request.arguments.get("new_content")

        if old_content is None:
            return ToolResult.create_failure(
                tool_name=self.name, operation="patch_file",
                error="'old_content' argument is required for patch_file",
            )
        if new_content is None:
            return ToolResult.create_failure(
                tool_name=self.name, operation="patch_file",
                error="'new_content' argument is required for patch_file",
            )

        # 5. Read current content
        try:
            raw = target.read_bytes()
            current = raw.decode("utf-8", errors="replace")
        except OSError as e:
            return ToolResult.create_failure(
                tool_name=self.name, operation="patch_file",
                error=f"Error reading file '{rel_path}': {e}",
            )

        # 6. Validate match count (unique, exact)
        count = current.count(old_content)
        if count == 0:
            return ToolResult.create_failure(
                tool_name=self.name, operation="patch_file",
                error=f"'old_content' was not found in '{rel_path}'",
                metadata={"file": rel_path, "old_content_len": len(old_content)},
            )
        if count > 1:
            return ToolResult.create_failure(
                tool_name=self.name, operation="patch_file",
                error=(
                    f"'old_content' appears {count} times in '{rel_path}'; "
                    f"patch_file requires an unambiguous (unique) match"
                ),
                metadata={"file": rel_path, "occurrence_count": count},
            )

        # 7. Apply replacement
        updated = current.replace(old_content, new_content, 1)
        bytes_before = len(raw)

        try:
            target.write_bytes(updated.encode("utf-8"))
        except OSError as e:
            return ToolResult.create_failure(
                tool_name=self.name, operation="patch_file",
                error=f"Error writing file '{rel_path}': {e}",
            )

        bytes_after = len(updated.encode("utf-8"))

        try:
            display_path = str(target.relative_to(repo_root))
        except ValueError:
            display_path = rel_path

        return ToolResult.create_success(
            tool_name=self.name,
            operation="patch_file",
            output={
                "path": display_path,
                "bytes_before": bytes_before,
                "bytes_after": bytes_after,
                "replacements": 1,
            },
            metadata={"repo_root": str(repo_root)},
        )
