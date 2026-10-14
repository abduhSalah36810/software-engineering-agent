"""
Phase 5 — FileSystemTool Test Suite.

Validates all four operations (list_dir, read_file, search_text, patch_file)
plus security properties: path confinement, binary rejection, mutation barrier,
symlink escape rejection, and ToolRegistry compatibility.

Test structure:
  A — BaseTool contract and ToolRegistry integration.
  B — list_dir: happy path and error cases.
  C — read_file: happy path, line slicing, errors.
  D — read_file: binary rejection and size limits.
  E — search_text: results, extension filter, case-insensitivity, truncation.
  F — patch_file: authorized happy path and ambiguous/missing match errors.
  G — patch_file: mutation barrier (unauthorized, caller arg escalation denied).
  H — Security: path traversal, absolute path, symlink escape, unknown repo.
  I — Evidence conversion and ToolResult contract.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.tools.base import BaseTool, ToolRegistry
from src.tools.filesystem import (
    FileSystemTool,
    BINARY_EXTENSIONS,
    MAX_READ_BYTES,
    MAX_SEARCH_MATCHES,
)
from src.tools.models import ToolEvidence, ToolRequest, ToolResult


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """Creates a minimal fake repository with known content."""
    repo = tmp_path / "test_repo"
    repo.mkdir()

    # Text files
    (repo / "README.md").write_text("# Test Repo\n\nHello world.\n", encoding="utf-8")
    (repo / "main.py").write_text(
        "def hello():\n    print('Hello')\n\nhello()\n", encoding="utf-8"
    )

    # Sub-directory
    src = repo / "src"
    src.mkdir()
    (src / "utils.py").write_text(
        "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (src / "config.json").write_text('{"key": "value", "count": 42}\n', encoding="utf-8")

    # Binary file (null bytes)
    (repo / "data.bin").write_bytes(b"\x00\x01\x02\x03binary content")

    # Binary by extension
    (repo / "image.png").write_bytes(b"fake png content")

    # Empty file
    (repo / "empty.txt").write_text("", encoding="utf-8")

    # File with duplicate content (for patch_file ambiguity tests)
    (repo / "duplicate.txt").write_text(
        "line one\nrepeated\nline two\nrepeated\n", encoding="utf-8"
    )

    return repo


@pytest.fixture
def fs_tool() -> FileSystemTool:
    return FileSystemTool()


def _req(op: str, args: dict, ctx: dict | None = None) -> ToolRequest:
    """Helper to build a ToolRequest for the filesystem tool."""
    return ToolRequest(
        tool_name="filesystem",
        operation=op,
        arguments=args,
        context=ctx or {},
    )


def _repo_req(op: str, repo: Path, args: dict, ctx_extra: dict | None = None) -> ToolRequest:
    ctx = {"repo_path": str(repo)}
    if ctx_extra:
        ctx.update(ctx_extra)
    return _req(op, args, ctx)


# ── A: BaseTool Contract & Registry ───────────────────────────────────────────

def test_A1_implements_base_tool(fs_tool: FileSystemTool) -> None:
    """A1: FileSystemTool is a BaseTool."""
    assert isinstance(fs_tool, BaseTool)
    assert fs_tool.name == "filesystem"
    assert len(fs_tool.description) > 0
    assert hasattr(fs_tool, "execute")
    assert hasattr(fs_tool, "validate_request")


def test_A2_tool_registry_registration(fs_tool: FileSystemTool) -> None:
    """A2: FileSystemTool can be registered in ToolRegistry and dispatched."""
    registry = ToolRegistry()
    registry.register(fs_tool)
    assert registry.has("filesystem")
    assert "filesystem" in registry.list_tools()


def test_A3_registry_dispatch(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """A3: ToolRegistry.execute dispatches correctly to FileSystemTool."""
    registry = ToolRegistry()
    registry.register(fs_tool)

    req = _repo_req("list_dir", temp_repo, {})
    result = registry.execute(req)
    assert isinstance(result, ToolResult)
    assert result.success is True


def test_A4_unknown_operation_returns_failure(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """A4: Unknown operation produces failure ToolResult without raising."""
    req = _repo_req("explode_everything", temp_repo, {})
    result = fs_tool.execute(req)
    assert result.success is False
    assert "Unknown operation" in result.error


def test_A5_wrong_tool_name_rejected(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """A5: Request with wrong tool_name is rejected at validate_request."""
    req = ToolRequest(tool_name="terminal", operation="list_dir",
                      arguments={}, context={"repo_path": str(temp_repo)})
    is_valid, err = fs_tool.validate_request(req)
    assert is_valid is False
    assert "mismatch" in err.lower()


# ── B: list_dir ───────────────────────────────────────────────────────────────

def test_B1_list_dir_root(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """B1: list_dir at repository root returns all immediate children."""
    req = _repo_req("list_dir", temp_repo, {})
    res = fs_tool.execute(req)

    assert res.success is True
    assert res.output["path"] == "."
    names = {e["name"] for e in res.output["entries"]}
    assert "README.md" in names
    assert "main.py" in names
    assert "src" in names
    assert "data.bin" in names


def test_B2_list_dir_subdir(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """B2: list_dir for a subdirectory."""
    req = _repo_req("list_dir", temp_repo, {"path": "src"})
    res = fs_tool.execute(req)

    assert res.success is True
    assert res.output["path"] == "src"
    names = {e["name"] for e in res.output["entries"]}
    assert "utils.py" in names
    assert "config.json" in names


def test_B3_list_dir_entry_types(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """B3: list_dir correctly classifies files and directories."""
    req = _repo_req("list_dir", temp_repo, {})
    res = fs_tool.execute(req)

    entries_by_name = {e["name"]: e for e in res.output["entries"]}

    assert entries_by_name["src"]["type"] == "dir"
    assert entries_by_name["src"]["size_bytes"] is None
    assert entries_by_name["src"]["is_binary"] is None

    assert entries_by_name["README.md"]["type"] == "file"
    assert isinstance(entries_by_name["README.md"]["size_bytes"], int)
    assert entries_by_name["README.md"]["is_binary"] is False

    assert entries_by_name["image.png"]["type"] == "file"
    assert entries_by_name["image.png"]["is_binary"] is True


def test_B4_list_dir_nonexistent_path(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """B4: list_dir rejects nonexistent path."""
    req = _repo_req("list_dir", temp_repo, {"path": "nonexistent_dir"})
    res = fs_tool.execute(req)
    assert res.success is False
    assert "does not exist" in res.error


def test_B5_list_dir_file_as_dir(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """B5: list_dir rejects a file path (not a directory)."""
    req = _repo_req("list_dir", temp_repo, {"path": "README.md"})
    res = fs_tool.execute(req)
    assert res.success is False
    assert "not a directory" in res.error


def test_B6_list_dir_no_repo_path(fs_tool: FileSystemTool) -> None:
    """B6: list_dir fails gracefully with no repo_path context."""
    req = _req("list_dir", {})
    res = fs_tool.execute(req)
    assert res.success is False


# ── C: read_file ──────────────────────────────────────────────────────────────

def test_C1_read_file_full(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """C1: read_file reads a complete text file."""
    req = _repo_req("read_file", temp_repo, {"path": "README.md"})
    res = fs_tool.execute(req)

    assert res.success is True
    assert "Hello world." in res.output["content"]
    assert res.output["total_lines"] == 3
    assert res.output["start_line"] == 1
    assert res.output["truncated"] is False


def test_C2_read_file_line_slice(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """C2: read_file respects start_line/end_line slicing."""
    req = _repo_req("read_file", temp_repo, {
        "path": "src/utils.py",
        "start_line": 2,
        "end_line": 3,
    })
    res = fs_tool.execute(req)

    assert res.success is True
    assert res.output["start_line"] == 2
    assert res.output["end_line"] == 3
    content = res.output["content"]
    assert "return a + b" in content
    # Line 1 (def add) should not be present
    assert "def add" not in content


def test_C3_read_file_nested_path(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """C3: read_file resolves nested paths correctly."""
    req = _repo_req("read_file", temp_repo, {"path": "src/config.json"})
    res = fs_tool.execute(req)

    assert res.success is True
    assert '"key"' in res.output["content"]


def test_C4_read_file_empty(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """C4: read_file handles empty files."""
    req = _repo_req("read_file", temp_repo, {"path": "empty.txt"})
    res = fs_tool.execute(req)

    assert res.success is True
    assert res.output["content"] == ""
    assert res.output["total_lines"] == 0


def test_C5_read_file_nonexistent(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """C5: read_file rejects nonexistent files."""
    req = _repo_req("read_file", temp_repo, {"path": "no_such_file.py"})
    res = fs_tool.execute(req)
    assert res.success is False
    assert "does not exist" in res.error


def test_C6_read_file_missing_path_arg(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """C6: read_file requires the 'path' argument."""
    req = _repo_req("read_file", temp_repo, {})
    res = fs_tool.execute(req)
    assert res.success is False
    assert "'path' argument is required" in res.error


def test_C7_read_file_directory_rejected(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """C7: read_file rejects directories."""
    req = _repo_req("read_file", temp_repo, {"path": "src"})
    res = fs_tool.execute(req)
    assert res.success is False
    assert "not a regular file" in res.error


# ── D: read_file binary rejection and size limits ─────────────────────────────

def test_D1_read_file_binary_by_null_bytes(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """D1: read_file rejects binary files detected by null bytes."""
    req = _repo_req("read_file", temp_repo, {"path": "data.bin"})
    res = fs_tool.execute(req)
    assert res.success is False
    assert "binary" in res.error.lower()


def test_D2_read_file_binary_by_extension(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """D2: read_file rejects binary files detected by extension."""
    req = _repo_req("read_file", temp_repo, {"path": "image.png"})
    res = fs_tool.execute(req)
    assert res.success is False
    assert "binary" in res.error.lower()


def test_D3_read_file_size_limit(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """D3: read_file rejects files exceeding max_bytes limit."""
    big_file = temp_repo / "big.txt"
    big_file.write_text("A" * (MAX_READ_BYTES + 1), encoding="utf-8")

    req = _repo_req("read_file", temp_repo, {"path": "big.txt"})
    res = fs_tool.execute(req)
    assert res.success is False
    assert "exceeds" in res.error
    assert "read limit" in res.error


def test_D4_read_file_custom_max_bytes_cannot_exceed_cap(
    fs_tool: FileSystemTool, temp_repo: Path
) -> None:
    """D4: max_bytes argument is capped at MAX_READ_BYTES (cannot exceed limit)."""
    big_file = temp_repo / "medium.txt"
    content = "B" * 100_000
    big_file.write_text(content, encoding="utf-8")

    # Request a max_bytes smaller than the file
    req = _repo_req("read_file", temp_repo, {"path": "medium.txt", "max_bytes": 50_000})
    res = fs_tool.execute(req)
    assert res.success is False
    assert "exceeds" in res.error

    # Request max_bytes larger than MAX_READ_BYTES — should be capped, NOT granted
    # (this file is 100KB which is under MAX_READ_BYTES, so it should succeed)
    req2 = _repo_req("read_file", temp_repo, {
        "path": "medium.txt",
        "max_bytes": MAX_READ_BYTES + 1_000_000,  # tries to exceed cap
    })
    res2 = fs_tool.execute(req2)
    assert res2.success is True  # 100KB < cap, so OK


def test_D5_binary_extension_set_is_complete() -> None:
    """D5: Common binary extensions are represented in BINARY_EXTENSIONS."""
    expected = {".pyc", ".so", ".png", ".zip", ".db", ".pdf", ".exe"}
    for ext in expected:
        assert ext in BINARY_EXTENSIONS, f"Missing binary extension: {ext}"


# ── E: search_text ────────────────────────────────────────────────────────────

def test_E1_search_text_basic(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """E1: search_text finds a literal string across repository files."""
    req = _repo_req("search_text", temp_repo, {"pattern": "Hello"})
    res = fs_tool.execute(req)

    assert res.success is True
    assert res.output["total_matches"] > 0
    files = {m["file"] for m in res.output["matches"]}
    # "Hello" appears in README.md and main.py
    assert any("README" in f or "main" in f for f in files)


def test_E2_search_text_case_insensitive(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """E2: search_text supports case-insensitive matching."""
    req_cs = _repo_req("search_text", temp_repo, {"pattern": "hello", "case_sensitive": True})
    req_ci = _repo_req("search_text", temp_repo, {"pattern": "hello", "case_sensitive": False})

    res_cs = fs_tool.execute(req_cs)
    res_ci = fs_tool.execute(req_ci)

    assert res_ci.output["total_matches"] >= res_cs.output["total_matches"]


def test_E3_search_text_extension_filter(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """E3: include_extensions restricts search to matching file types."""
    req_py = _repo_req("search_text", temp_repo, {
        "pattern": "return",
        "include_extensions": [".py"],
    })
    req_md = _repo_req("search_text", temp_repo, {
        "pattern": "return",
        "include_extensions": [".md"],
    })

    res_py = fs_tool.execute(req_py)
    res_md = fs_tool.execute(req_md)

    assert res_py.success is True
    assert res_py.output["total_matches"] > 0
    # All matches must be .py files
    for m in res_py.output["matches"]:
        assert m["file"].endswith(".py"), f"Non-py file in results: {m['file']}"

    # "return" doesn't appear in README.md
    assert res_md.output["total_matches"] == 0


def test_E4_search_text_subdir_scope(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """E4: search_text respects path scoping."""
    req_src = _repo_req("search_text", temp_repo, {
        "pattern": "subtract",
        "path": "src",
    })
    req_root = _repo_req("search_text", temp_repo, {
        "pattern": "subtract",
    })

    res_src = fs_tool.execute(req_src)
    res_root = fs_tool.execute(req_root)

    assert res_src.output["total_matches"] > 0
    assert res_root.output["total_matches"] == res_src.output["total_matches"]


def test_E5_search_text_no_match(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """E5: search_text returns empty matches for a non-existent pattern."""
    req = _repo_req("search_text", temp_repo, {"pattern": "xyzzy_does_not_exist_12345"})
    res = fs_tool.execute(req)
    assert res.success is True
    assert res.output["total_matches"] == 0
    assert res.output["matches"] == []
    assert res.output["truncated"] is False


def test_E6_search_text_truncation(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """E6: search_text truncates when MAX_SEARCH_MATCHES is hit."""
    # Create a file with many matching lines
    many_lines_file = temp_repo / "many.txt"
    many_lines_file.write_text(
        "\n".join(f"needle_{i}" for i in range(MAX_SEARCH_MATCHES + 20)),
        encoding="utf-8",
    )

    req = _repo_req("search_text", temp_repo, {"pattern": "needle_"})
    res = fs_tool.execute(req)

    assert res.success is True
    assert res.output["truncated"] is True
    assert len(res.output["matches"]) <= MAX_SEARCH_MATCHES


def test_E7_search_text_skips_binary_files(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """E7: search_text skips binary files even if they contain matching bytes."""
    req = _repo_req("search_text", temp_repo, {"pattern": "content"})
    res = fs_tool.execute(req)
    # "content" appears in data.bin as text-like bytes but must be skipped
    for m in res.output["matches"]:
        assert not m["file"].endswith(".bin"), f"Binary file leaked into results: {m['file']}"


def test_E8_search_text_missing_pattern(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """E8: search_text requires the 'pattern' argument."""
    req = _repo_req("search_text", temp_repo, {})
    res = fs_tool.execute(req)
    assert res.success is False
    assert "'pattern' argument is required" in res.error


def test_E9_search_text_single_file_scope(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """E9: search_text works when scoped to a single file."""
    req = _repo_req("search_text", temp_repo, {
        "pattern": "add",
        "path": "src/utils.py",
    })
    res = fs_tool.execute(req)
    assert res.success is True
    assert res.output["total_matches"] > 0
    for m in res.output["matches"]:
        assert "utils.py" in m["file"]


def test_E10_search_text_match_metadata(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """E10: Each match includes file, line_number, line text, and match_start."""
    req = _repo_req("search_text", temp_repo, {"pattern": "Hello"})
    res = fs_tool.execute(req)
    for m in res.output["matches"]:
        assert "file" in m
        assert "line_number" in m and isinstance(m["line_number"], int)
        assert "line" in m and isinstance(m["line"], str)
        assert "match_start" in m and isinstance(m["match_start"], int)


# ── F: patch_file happy path and content errors ───────────────────────────────

def test_F1_patch_file_success(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """F1: patch_file applies a unique replacement and returns metadata."""
    target_file = temp_repo / "main.py"
    original = target_file.read_text(encoding="utf-8")
    assert "def hello():" in original

    req = _repo_req("patch_file", temp_repo, {
        "path": "main.py",
        "old_content": "def hello():",
        "new_content": "def greet():",
    }, ctx_extra={"allow_mutations": True})
    res = fs_tool.execute(req)

    assert res.success is True
    assert res.output["replacements"] == 1
    assert res.output["path"] == "main.py"
    assert isinstance(res.output["bytes_before"], int)
    assert isinstance(res.output["bytes_after"], int)

    # Verify the actual file was changed
    updated = target_file.read_text(encoding="utf-8")
    assert "def greet():" in updated
    assert "def hello():" not in updated


def test_F2_patch_file_not_found_old_content(
    fs_tool: FileSystemTool, temp_repo: Path
) -> None:
    """F2: patch_file fails when old_content is not in the file."""
    req = _repo_req("patch_file", temp_repo, {
        "path": "main.py",
        "old_content": "THIS_DOES_NOT_EXIST_IN_FILE",
        "new_content": "replacement",
    }, ctx_extra={"allow_mutations": True})
    res = fs_tool.execute(req)
    assert res.success is False
    assert "not found" in res.error


def test_F3_patch_file_ambiguous_match(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """F3: patch_file fails when old_content appears more than once."""
    req = _repo_req("patch_file", temp_repo, {
        "path": "duplicate.txt",
        "old_content": "repeated",
        "new_content": "unique",
    }, ctx_extra={"allow_mutations": True})
    res = fs_tool.execute(req)
    assert res.success is False
    assert "times" in res.error or "multiple" in res.error.lower() or "unambiguous" in res.error


def test_F4_patch_file_binary_rejected(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """F4: patch_file rejects binary files."""
    req = _repo_req("patch_file", temp_repo, {
        "path": "data.bin",
        "old_content": "binary",
        "new_content": "text",
    }, ctx_extra={"allow_mutations": True})
    res = fs_tool.execute(req)
    assert res.success is False
    assert "binary" in res.error.lower()


def test_F5_patch_file_nonexistent(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """F5: patch_file rejects nonexistent target files."""
    req = _repo_req("patch_file", temp_repo, {
        "path": "ghost.py",
        "old_content": "x",
        "new_content": "y",
    }, ctx_extra={"allow_mutations": True})
    res = fs_tool.execute(req)
    assert res.success is False
    assert "does not exist" in res.error


def test_F6_patch_file_missing_arguments(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """F6: patch_file requires old_content and new_content arguments."""
    req_no_old = _repo_req("patch_file", temp_repo, {
        "path": "main.py",
        "new_content": "x",
    }, ctx_extra={"allow_mutations": True})
    res = fs_tool.execute(req_no_old)
    assert res.success is False
    assert "old_content" in res.error

    req_no_new = _repo_req("patch_file", temp_repo, {
        "path": "main.py",
        "old_content": "x",
    }, ctx_extra={"allow_mutations": True})
    res2 = fs_tool.execute(req_no_new)
    assert res2.success is False
    assert "new_content" in res2.error


# ── G: patch_file mutation barrier ────────────────────────────────────────────

def test_G1_patch_file_denied_without_auth(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """G1: patch_file denied when allow_mutations is absent from context."""
    req = _repo_req("patch_file", temp_repo, {
        "path": "main.py",
        "old_content": "def hello():",
        "new_content": "def evil():",
    })  # No allow_mutations in context
    res = fs_tool.execute(req)
    assert res.success is False
    assert "allow_mutations" in res.error


def test_G2_patch_file_caller_arg_cannot_grant_auth(
    fs_tool: FileSystemTool, temp_repo: Path
) -> None:
    """G2: Caller arguments['allow_mutations'] cannot grant patch_file authorization."""
    req = ToolRequest(
        tool_name="filesystem",
        operation="patch_file",
        arguments={
            "path": "main.py",
            "old_content": "def hello():",
            "new_content": "def evil():",
            "allow_mutations": True,  # This must NOT grant permission
        },
        context={"repo_path": str(temp_repo)},  # No allow_mutations in context
    )
    res = fs_tool.execute(req)
    assert res.success is False
    # Must fail due to mutation barrier
    assert "allow_mutations" in res.error or "authorization" in res.error.lower()


def test_G3_patch_file_conflicting_auth_fails_closed(
    fs_tool: FileSystemTool, temp_repo: Path
) -> None:
    """G3: Conflicting allow_mutations (context True, args False) fails closed."""
    req = ToolRequest(
        tool_name="filesystem",
        operation="patch_file",
        arguments={
            "path": "main.py",
            "old_content": "def hello():",
            "new_content": "def evil():",
            "allow_mutations": False,  # Conflicts with context
        },
        context={
            "repo_path": str(temp_repo),
            "allow_mutations": True,
        },
    )
    res = fs_tool.execute(req)
    # Conflicting authorization should fail closed
    assert res.success is False
    assert "conflict" in res.error.lower() or "authorization" in res.error.lower()


# ── H: Security — path confinement ────────────────────────────────────────────

def test_H1_path_traversal_rejected_list_dir(
    fs_tool: FileSystemTool, temp_repo: Path
) -> None:
    """H1: Path traversal (..) is rejected for list_dir."""
    req = _repo_req("list_dir", temp_repo, {"path": "../outside"})
    res = fs_tool.execute(req)
    assert res.success is False
    assert "traversal" in res.error.lower() or "not permitted" in res.error.lower()


def test_H2_path_traversal_rejected_read_file(
    fs_tool: FileSystemTool, temp_repo: Path
) -> None:
    """H2: Path traversal (..) is rejected for read_file."""
    req = _repo_req("read_file", temp_repo, {"path": "../../etc/passwd"})
    res = fs_tool.execute(req)
    assert res.success is False
    assert "traversal" in res.error.lower() or "not permitted" in res.error.lower()


def test_H3_absolute_path_rejected(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """H3: Absolute paths are rejected for all read operations."""
    for op, args in [
        ("list_dir", {"path": "/etc"}),
        ("read_file", {"path": "/etc/passwd"}),
        ("search_text", {"path": "/etc", "pattern": "root"}),
    ]:
        req = _repo_req(op, temp_repo, args)
        res = fs_tool.execute(req)
        assert res.success is False, f"Expected failure for op={op} with absolute path"
        assert "absolute" in res.error.lower() or "not permitted" in res.error.lower()


def test_H4_symlink_escape_rejected(
    fs_tool: FileSystemTool, temp_repo: Path, tmp_path: Path
) -> None:
    """H4: Symlinks pointing outside repo root are rejected at resolution."""
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("secret", encoding="utf-8")

    # Create a symlink inside the repo pointing outside
    (temp_repo / "escape_link").symlink_to(outside_dir)

    # list_dir: the symlink entry itself is visible but not followed automatically
    req_list = _repo_req("list_dir", temp_repo, {})
    res_list = fs_tool.execute(req_list)
    assert res_list.success is True
    symlink_entries = [e for e in res_list.output["entries"] if e["name"] == "escape_link"]
    assert symlink_entries[0]["type"] == "symlink"

    # read_file through the symlink must be rejected
    req_read = _repo_req("read_file", temp_repo, {"path": "escape_link/secret.txt"})
    res_read = fs_tool.execute(req_read)
    assert res_read.success is False
    assert "escapes repository boundary" in res_read.error


def test_H5_no_repo_path_fails(fs_tool: FileSystemTool) -> None:
    """H5: All operations fail gracefully when no repo_path is provided."""
    for op, args in [
        ("list_dir", {}),
        ("read_file", {"path": "README.md"}),
        ("search_text", {"pattern": "hello"}),
        ("patch_file", {"path": "f.py", "old_content": "a", "new_content": "b"}),
    ]:
        req = _req(op, args, ctx={})
        res = fs_tool.execute(req)
        assert res.success is False, f"Expected failure for op={op} without repo_path"


def test_H6_nonexistent_repo_path_fails(fs_tool: FileSystemTool) -> None:
    """H6: A repo_path pointing to a nonexistent directory fails."""
    req = ToolRequest(
        tool_name="filesystem",
        operation="list_dir",
        arguments={},
        context={"repo_path": "/nonexistent/repo/path/xyz"},
    )
    res = fs_tool.execute(req)
    assert res.success is False


# ── I: Evidence Conversion & ToolResult Contract ──────────────────────────────

def test_I1_successful_result_to_evidence(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """I1: Successful ToolResult converts to ToolEvidence correctly."""
    req = _repo_req("read_file", temp_repo, {"path": "README.md"})
    res = fs_tool.execute(req)

    assert res.success is True
    evidence = res.to_evidence(category="code_inspection", target="README.md")

    assert isinstance(evidence, ToolEvidence)
    assert evidence.source_tool == "filesystem"
    assert evidence.operation == "read_file"
    assert evidence.category == "code_inspection"
    assert evidence.target == "README.md"
    assert evidence.success is True
    assert evidence.is_interpreted is False  # Evidence is never a decision


def test_I2_failed_result_preserves_error(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """I2: Failed ToolResult preserves error message cleanly."""
    req = _repo_req("read_file", temp_repo, {"path": "nonexistent.py"})
    res = fs_tool.execute(req)

    assert res.success is False
    assert res.output is None
    assert res.error is not None
    assert len(res.error) > 0


def test_I3_result_metadata_always_present(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """I3: All ToolResults include executed_at timestamp in metadata."""
    req = _repo_req("list_dir", temp_repo, {})
    res = fs_tool.execute(req)
    assert "executed_at" in res.metadata


def test_I4_result_serialization(fs_tool: FileSystemTool, temp_repo: Path) -> None:
    """I4: ToolResult can be serialized to JSON without error."""
    import json
    req = _repo_req("list_dir", temp_repo, {})
    res = fs_tool.execute(req)
    serialized = res.to_json()
    parsed = json.loads(serialized)
    assert parsed["tool_name"] == "filesystem"
    assert parsed["success"] is True
