"""
Phase 5.2 — GitTool Test Suite.

Comprehensive validation of GitTool adapter:
  A — BaseTool contract and ToolRegistry integration.
  B — Status operation: clean, dirty, staged, untracked, empty repository.
  C — Diff operation: working tree, staged, commit range, single-file scope, truncation.
  D — Log operation: structured metadata, limits, skip, path filtering, empty repo.
  E — Changed files operation: working tree, staged-only, commit comparison, rename detection.
  F — Security & confinement: repository boundary, path traversal, symlink escape, option injection defense, read-only enforcement, env sanitization.
  G — ToolResult contract and ToolEvidence conversion.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from src.tools.base import BaseTool, ToolRegistry, default_registry
from src.tools.git import (
    GitTool,
    DEFAULT_MAX_DIFF_CHARS,
    MAX_DIFF_CHARS_CAP,
    DEFAULT_LOG_LIMIT,
    MAX_LOG_LIMIT,
    _get_git_env,
    _validate_git_ref,
)
from src.tools.models import ToolEvidence, ToolRequest, ToolResult


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Creates a temporary isolated git repository with initialized commit history."""
    repo = tmp_path / "test_git_repo"
    repo.mkdir()

    env = dict(os.environ)
    env["GIT_AUTHOR_NAME"] = "GitTester"
    env["GIT_AUTHOR_EMAIL"] = "gittester@example.com"
    env["GIT_COMMITTER_NAME"] = "GitTester"
    env["GIT_COMMITTER_EMAIL"] = "gittester@example.com"

    def _run(args: list[str]) -> None:
        subprocess.run(["git"] + args, cwd=str(repo), env=env, check=True, capture_output=True, text=True)

    _run(["init"])
    _run(["config", "user.name", "GitTester"])
    _run(["config", "user.email", "gittester@example.com"])

    # Commit 1
    (repo / "README.md").write_text("# Test Git Repo\nInitial content\n", encoding="utf-8")
    (repo / "app.py").write_text("print('hello world')\n", encoding="utf-8")
    _run(["add", "."])
    _run(["commit", "-m", "Initial commit"])

    # Subdirectory and Commit 2
    sub = repo / "sub"
    sub.mkdir()
    (sub / "helper.py").write_text("def helper(): pass\n", encoding="utf-8")
    _run(["add", "."])
    _run(["commit", "-m", "Add helper module in sub"])

    return repo


@pytest.fixture
def empty_git_repo(tmp_path: Path) -> Path:
    """Creates an empty git repository without any commits yet."""
    repo = tmp_path / "empty_git_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    return repo


@pytest.fixture
def git_tool() -> GitTool:
    return GitTool()


# ── Test Group A: BaseTool Contract & Registry Integration ────────────────────

def test_A1_implements_base_tool(git_tool: GitTool):
    assert isinstance(git_tool, BaseTool)
    assert git_tool.name == "git"
    assert "Git" in git_tool.description


def test_A2_tool_registry_registration():
    assert "git" in default_registry.list_tools()
    tool = default_registry.get("git")
    assert isinstance(tool, GitTool)


def test_A3_registry_dispatch(temp_git_repo: Path):
    req = ToolRequest(
        tool_name="git",
        operation="status",
        context={"repo_path": str(temp_git_repo)},
    )
    res = default_registry.execute(req)
    assert res.success is True
    assert res.tool_name == "git"
    assert res.operation == "status"
    assert res.output.get("is_clean") is True


def test_A4_wrong_tool_name_rejected(git_tool: GitTool):
    req = ToolRequest(tool_name="terminal", operation="status")
    is_valid, err = git_tool.validate_request(req)
    assert is_valid is False
    assert "mismatch" in str(err).lower()


def test_A5_unsupported_or_mutating_operation_rejected(git_tool: GitTool, temp_git_repo: Path):
    for bad_op in ["commit", "push", "checkout", "reset", "merge", "rebase", "delete", "unknown"]:
        req = ToolRequest(
            tool_name="git",
            operation=bad_op,
            context={"repo_path": str(temp_git_repo)},
        )
        res = git_tool.execute(req)
        assert res.success is False
        assert "unsupported or mutating" in str(res.error).lower()


# ── Test Group B: Status Operation ────────────────────────────────────────────

def test_B1_status_clean_repo(git_tool: GitTool, temp_git_repo: Path):
    req = ToolRequest(tool_name="git", operation="status", context={"repo_path": str(temp_git_repo)})
    res = git_tool.execute(req)
    assert res.success is True
    out = res.output
    assert out["is_clean"] is True
    assert out["staged"] == []
    assert out["unstaged"] == []
    assert out["untracked"] == []
    assert out["branch"] is not None
    assert out["head_commit"] is not None
    assert out["counts"]["staged"] == 0


def test_B2_status_unstaged_modifications(git_tool: GitTool, temp_git_repo: Path):
    (temp_git_repo / "README.md").write_text("# Modified\n", encoding="utf-8")
    req = ToolRequest(tool_name="git", operation="status", context={"repo_path": str(temp_git_repo)})
    res = git_tool.execute(req)
    assert res.success is True
    out = res.output
    assert out["is_clean"] is False
    assert len(out["unstaged"]) == 1
    assert out["unstaged"][0]["path"] == "README.md"
    assert out["unstaged"][0]["status"] == "modified"
    assert out["counts"]["unstaged"] == 1


def test_B3_status_staged_changes(git_tool: GitTool, temp_git_repo: Path):
    (temp_git_repo / "new_file.txt").write_text("staged content\n", encoding="utf-8")
    subprocess.run(["git", "add", "new_file.txt"], cwd=str(temp_git_repo), check=True)

    req = ToolRequest(tool_name="git", operation="status", context={"repo_path": str(temp_git_repo)})
    res = git_tool.execute(req)
    assert res.success is True
    out = res.output
    assert out["is_clean"] is False
    assert len(out["staged"]) == 1
    assert out["staged"][0]["path"] == "new_file.txt"
    assert out["staged"][0]["status"] == "added"
    assert out["counts"]["staged"] == 1


def test_B4_status_untracked_files(git_tool: GitTool, temp_git_repo: Path):
    (temp_git_repo / "untracked.log").write_text("debug logs\n", encoding="utf-8")
    req = ToolRequest(tool_name="git", operation="status", context={"repo_path": str(temp_git_repo)})
    res = git_tool.execute(req)
    assert res.success is True
    out = res.output
    assert out["is_clean"] is False
    assert "untracked.log" in out["untracked"]
    assert out["counts"]["untracked"] == 1


def test_B5_status_empty_repo_unborn_head(git_tool: GitTool, empty_git_repo: Path):
    req = ToolRequest(tool_name="git", operation="status", context={"repo_path": str(empty_git_repo)})
    res = git_tool.execute(req)
    assert res.success is True
    out = res.output
    assert out["is_clean"] is True
    assert out["head_commit"] is None
    assert out["branch"] in ["master", "main", "(unborn)"]


# ── Test Group C: Diff Operation ──────────────────────────────────────────────

def test_C1_diff_unstaged(git_tool: GitTool, temp_git_repo: Path):
    (temp_git_repo / "app.py").write_text("print('unstaged diff test')\n", encoding="utf-8")
    req = ToolRequest(tool_name="git", operation="diff", context={"repo_path": str(temp_git_repo)})
    res = git_tool.execute(req)
    assert res.success is True
    out = res.output
    assert "unstaged diff test" in out["diff"]
    assert out["staged"] is False
    assert out["truncated"] is False


def test_C2_diff_staged(git_tool: GitTool, temp_git_repo: Path):
    (temp_git_repo / "app.py").write_text("print('staged diff test')\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=str(temp_git_repo), check=True)

    # Staged=True should show the diff
    req_staged = ToolRequest(
        tool_name="git",
        operation="diff",
        arguments={"staged": True},
        context={"repo_path": str(temp_git_repo)},
    )
    res_staged = git_tool.execute(req_staged)
    assert res_staged.success is True
    assert "staged diff test" in res_staged.output["diff"]

    # Staged=False should show empty diff
    req_unstaged = ToolRequest(
        tool_name="git",
        operation="diff",
        arguments={"staged": False},
        context={"repo_path": str(temp_git_repo)},
    )
    res_unstaged = git_tool.execute(req_unstaged)
    assert res_unstaged.success is True
    assert res_unstaged.output["diff"] == ""


def test_C3_diff_commit_range(git_tool: GitTool, temp_git_repo: Path):
    req = ToolRequest(
        tool_name="git",
        operation="diff",
        arguments={"from_commit": "HEAD~1", "to_commit": "HEAD"},
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is True
    out = res.output
    assert "helper" in out["diff"]


def test_C4_diff_single_file_scoped(git_tool: GitTool, temp_git_repo: Path):
    (temp_git_repo / "README.md").write_text("README change\n", encoding="utf-8")
    (temp_git_repo / "app.py").write_text("app change\n", encoding="utf-8")

    req = ToolRequest(
        tool_name="git",
        operation="diff",
        arguments={"path": "README.md"},
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is True
    diff_text = res.output["diff"]
    assert "README change" in diff_text
    assert "app change" not in diff_text


def test_C5_diff_clean_repo_empty(git_tool: GitTool, temp_git_repo: Path):
    req = ToolRequest(tool_name="git", operation="diff", context={"repo_path": str(temp_git_repo)})
    res = git_tool.execute(req)
    assert res.success is True
    assert res.output["diff"] == ""
    assert res.output["total_chars"] == 0


def test_C6_diff_output_truncation(git_tool: GitTool, temp_git_repo: Path):
    # Create large diff
    (temp_git_repo / "app.py").write_text("line\n" * 500, encoding="utf-8")
    req = ToolRequest(
        tool_name="git",
        operation="diff",
        arguments={"max_chars": 200},
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is True
    out = res.output
    assert out["truncated"] is True
    assert len(out["diff"]) > 200
    assert "Diff truncated at 200 characters" in out["diff"]


# ── Test Group D: Log Operation ───────────────────────────────────────────────

def test_D1_log_commits_structured(git_tool: GitTool, temp_git_repo: Path):
    req = ToolRequest(
        tool_name="git",
        operation="log",
        arguments={"limit": 5},
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is True
    out = res.output
    assert out["count"] == 2
    commits = out["commits"]
    assert len(commits) == 2

    # Check top commit
    c0 = commits[0]
    assert c0["message"] == "Add helper module in sub"
    assert c0["author"] == "GitTester"
    assert c0["email"] == "gittester@example.com"
    assert len(c0["commit"]) == 40
    assert len(c0["short_hash"]) >= 7
    assert "T" in c0["date"]  # ISO-8601
    assert len(c0["parents"]) == 1

    # Check root commit
    c1 = commits[1]
    assert c1["message"] == "Initial commit"
    assert len(c1["parents"]) == 0


def test_D2_log_limit_and_skip(git_tool: GitTool, temp_git_repo: Path):
    req_lim = ToolRequest(
        tool_name="git",
        operation="log",
        arguments={"limit": 1},
        context={"repo_path": str(temp_git_repo)},
    )
    res_lim = git_tool.execute(req_lim)
    assert res_lim.success is True
    assert res_lim.output["count"] == 1
    assert res_lim.output["commits"][0]["message"] == "Add helper module in sub"

    req_skip = ToolRequest(
        tool_name="git",
        operation="log",
        arguments={"limit": 1, "skip": 1},
        context={"repo_path": str(temp_git_repo)},
    )
    res_skip = git_tool.execute(req_skip)
    assert res_skip.success is True
    assert res_skip.output["count"] == 1
    assert res_skip.output["commits"][0]["message"] == "Initial commit"


def test_D3_log_scoped_to_path(git_tool: GitTool, temp_git_repo: Path):
    req = ToolRequest(
        tool_name="git",
        operation="log",
        arguments={"path": "sub/helper.py"},
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is True
    assert res.output["count"] == 1
    assert res.output["commits"][0]["message"] == "Add helper module in sub"


def test_D4_log_empty_repo(git_tool: GitTool, empty_git_repo: Path):
    req = ToolRequest(tool_name="git", operation="log", context={"repo_path": str(empty_git_repo)})
    res = git_tool.execute(req)
    assert res.success is True
    assert res.output["count"] == 0
    assert res.output["commits"] == []
    assert res.output.get("empty_repo") is True


def test_D5_log_limit_capped(git_tool: GitTool, temp_git_repo: Path):
    req = ToolRequest(
        tool_name="git",
        operation="log",
        arguments={"limit": 9999},
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is True
    assert res.output["limit"] == MAX_LOG_LIMIT


# ── Test Group E: Changed Files Operation ─────────────────────────────────────

def test_E1_changed_files_working_tree(git_tool: GitTool, temp_git_repo: Path):
    (temp_git_repo / "app.py").write_text("changed app\n", encoding="utf-8")
    (temp_git_repo / "untracked_new.txt").write_text("new\n", encoding="utf-8")

    req = ToolRequest(
        tool_name="git",
        operation="changed_files",
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is True
    out = res.output
    paths = [f["path"] for f in out["files"]]
    assert "app.py" in paths
    assert "untracked_new.txt" in paths
    assert out["summary"]["modified"] >= 1
    assert out["summary"]["untracked"] >= 1


def test_E2_changed_files_staged_only(git_tool: GitTool, temp_git_repo: Path):
    (temp_git_repo / "app.py").write_text("changed app\n", encoding="utf-8")
    (temp_git_repo / "staged.txt").write_text("staged\n", encoding="utf-8")
    subprocess.run(["git", "add", "staged.txt"], cwd=str(temp_git_repo), check=True)

    req = ToolRequest(
        tool_name="git",
        operation="changed_files",
        arguments={"staged": True},
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is True
    paths = [f["path"] for f in res.output["files"]]
    assert "staged.txt" in paths
    assert "app.py" not in paths
    assert res.output.get("staged_only") is True


def test_E3_changed_files_between_commits(git_tool: GitTool, temp_git_repo: Path):
    req = ToolRequest(
        tool_name="git",
        operation="changed_files",
        arguments={"from_commit": "HEAD~1", "to_commit": "HEAD"},
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is True
    out = res.output
    assert out["total_files"] == 1
    assert out["files"][0]["path"] == "sub/helper.py"
    assert out["files"][0]["status"] == "added"
    assert out["summary"]["added"] == 1


def test_E4_changed_files_rename(git_tool: GitTool, temp_git_repo: Path):
    subprocess.run(["git", "mv", "app.py", "application.py"], cwd=str(temp_git_repo), check=True)
    req = ToolRequest(
        tool_name="git",
        operation="changed_files",
        arguments={"staged": True},
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is True
    renamed_items = [f for f in res.output["files"] if f["status"] == "renamed"]
    assert len(renamed_items) == 1
    assert renamed_items[0]["path"] == "application.py"
    assert renamed_items[0]["old_path"] == "app.py"


def test_E5_changed_files_limit_bounded(git_tool: GitTool, temp_git_repo: Path):
    for i in range(5):
        (temp_git_repo / f"file_{i}.txt").write_text(f"{i}\n", encoding="utf-8")

    req = ToolRequest(
        tool_name="git",
        operation="changed_files",
        arguments={"limit": 2},
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is True
    out = res.output
    assert len(out["files"]) == 2
    assert out["total_files"] >= 5
    assert out["truncated"] is True


# ── Test Group F: Security & Boundary Protection ──────────────────────────────

def test_F1_outside_repo_root_rejected(git_tool: GitTool, tmp_path: Path):
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    req = ToolRequest(
        tool_name="git",
        operation="status",
        arguments={"repo_path": str(outside_dir)},
    )
    res = git_tool.execute(req)
    assert res.success is False
    assert "outside permitted repository roots" in str(res.error).lower()


def test_F2_caller_arguments_cannot_override_trusted_context(git_tool: GitTool, temp_git_repo: Path, tmp_path: Path):
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    req = ToolRequest(
        tool_name="git",
        operation="status",
        arguments={"repo_path": str(outside_dir)},
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is False
    assert "conflicts with or escapes trusted context" in str(res.error).lower()


def test_F3_non_git_directory_rejected(git_tool: GitTool, tmp_path: Path, monkeypatch):
    non_git = tmp_path / "plain_dir"
    non_git.mkdir()
    monkeypatch.setenv("ALLOWED_REPO_ROOTS", str(tmp_path))

    req = ToolRequest(
        tool_name="git",
        operation="status",
        context={"repo_path": str(non_git)},
    )
    res = git_tool.execute(req)
    assert res.success is False
    assert "is not a git repository" in str(res.error).lower()


def test_F4_path_traversal_in_diff_rejected(git_tool: GitTool, temp_git_repo: Path):
    req = ToolRequest(
        tool_name="git",
        operation="diff",
        arguments={"path": "../../etc/passwd"},
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is False
    assert "path traversal via '..'" in str(res.error).lower()


def test_F5_path_traversal_in_log_rejected(git_tool: GitTool, temp_git_repo: Path):
    req = ToolRequest(
        tool_name="git",
        operation="log",
        arguments={"path": "../escape.txt"},
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is False
    assert "path traversal via '..'" in str(res.error).lower()


def test_F6_symlink_escape_rejected(git_tool: GitTool, temp_git_repo: Path, tmp_path: Path):
    target = tmp_path / "secret.txt"
    target.write_text("secret\n")
    link = temp_git_repo / "sym_link"
    link.symlink_to(target)

    req = ToolRequest(
        tool_name="git",
        operation="diff",
        arguments={"path": "sym_link"},
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is False
    assert "escapes repository boundary" in str(res.error).lower()


def test_F7_option_injection_in_ref_rejected(git_tool: GitTool, temp_git_repo: Path):
    for evil_ref in ["--upload-pack=evil", "-C", "--output=/tmp/pwn", "-p"]:
        req = ToolRequest(
            tool_name="git",
            operation="log",
            arguments={"revision": evil_ref},
            context={"repo_path": str(temp_git_repo)},
        )
        res = git_tool.execute(req)
        assert res.success is False
        assert "cannot begin with a dash" in str(res.error).lower()


def test_F8_option_injection_in_from_commit_rejected(git_tool: GitTool, temp_git_repo: Path):
    req = ToolRequest(
        tool_name="git",
        operation="diff",
        arguments={"from_commit": "--git-dir=/etc", "to_commit": "HEAD"},
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is False
    assert "cannot begin with a dash" in str(res.error).lower()


def test_F9_semicolon_or_shell_injection_in_ref_rejected(git_tool: GitTool, temp_git_repo: Path):
    for evil_ref in ["HEAD; rm -rf /", "HEAD && cat /etc/passwd", "HEAD | evil", "`whoami`", "$(id)"]:
        req = ToolRequest(
            tool_name="git",
            operation="log",
            arguments={"revision": evil_ref},
            context={"repo_path": str(temp_git_repo)},
        )
        res = git_tool.execute(req)
        assert res.success is False
        assert "contains forbidden characters" in str(res.error).lower()


def test_F10_range_syntax_in_single_ref_rejected(git_tool: GitTool, temp_git_repo: Path):
    req = ToolRequest(
        tool_name="git",
        operation="log",
        arguments={"revision": "HEAD..HEAD~1"},
        context={"repo_path": str(temp_git_repo)},
    )
    res = git_tool.execute(req)
    assert res.success is False
    assert "cannot contain '..'" in str(res.error).lower()


def test_F11_read_only_strictly_enforced_mutating_ops_rejected(git_tool: GitTool, temp_git_repo: Path):
    # Even if context explicitly says allow_mutations=True, GitTool itself rejects mutating ops
    for op in ["commit", "push", "checkout", "merge", "rebase"]:
        req = ToolRequest(
            tool_name="git",
            operation=op,
            context={"repo_path": str(temp_git_repo), "allow_mutations": True},
        )
        res = git_tool.execute(req)
        assert res.success is False
        assert "unsupported or mutating git operation" in str(res.error).lower()


def test_F12_git_env_sanitization(monkeypatch):
    monkeypatch.setenv("GIT_DIR", "/etc/git")
    monkeypatch.setenv("GIT_WORK_TREE", "/tmp")
    monkeypatch.setenv("AWS_SECRET_KEY", "supersecret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_123456")

    env = _get_git_env()
    assert "GIT_DIR" not in env
    assert "GIT_WORK_TREE" not in env
    assert "AWS_SECRET_KEY" not in env
    assert "GITHUB_TOKEN" not in env
    assert env.get("GIT_TERMINAL_PROMPT") == "0"
    assert env.get("GIT_OPTIONAL_LOCKS") == "0"


# ── Test Group G: ToolEvidence & Serialization ────────────────────────────────

def test_G1_result_to_evidence(git_tool: GitTool, temp_git_repo: Path):
    req = ToolRequest(tool_name="git", operation="status", context={"repo_path": str(temp_git_repo)})
    res = git_tool.execute(req)
    assert res.success is True

    evidence = res.to_evidence(category="git_status", target=str(temp_git_repo))
    assert isinstance(evidence, ToolEvidence)
    assert evidence.source_tool == "git"
    assert evidence.operation == "status"
    assert evidence.success is True
    assert evidence.is_interpreted is False
    assert evidence.category == "git_status"
    assert evidence.target == str(temp_git_repo)
    assert evidence.raw_data == res.output


def test_G2_failed_result_preserves_error(git_tool: GitTool, temp_git_repo: Path):
    req = ToolRequest(tool_name="git", operation="unknown_op", context={"repo_path": str(temp_git_repo)})
    res = git_tool.execute(req)
    assert res.success is False

    evidence = res.to_evidence()
    assert evidence.success is False
    assert evidence.raw_data is None or "unsupported" in str(evidence.provenance.get("error", "")).lower()


def test_G3_result_serialization_roundtrip(git_tool: GitTool, temp_git_repo: Path):
    req = ToolRequest(tool_name="git", operation="status", context={"repo_path": str(temp_git_repo)})
    res = git_tool.execute(req)
    data = res.to_dict()
    roundtripped = ToolResult.from_dict(data)
    assert roundtripped.tool_name == res.tool_name
    assert roundtripped.operation == res.operation
    assert roundtripped.success == res.success
    assert roundtripped.output == res.output
    assert roundtripped.metadata == res.metadata
