"""
Tests for Phase 5.3 Tool Execution & Introspection API.

Validates:
  - GET /api/project/tools (listing capabilities, allowed root validation).
  - POST /api/project/tools/execute for GitTool (status, log, diff, changed_files).
  - POST /api/project/tools/execute for FileSystemTool (list_dir, read_file, search_text).
  - Security barriers: mutating operations blocked on web API (patch_file, git commit).
  - Security barriers: path traversal, out-of-boundary paths, non-existent directories.
  - Evidence generation on tool execution.
"""

import os
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def api_client():
    return TestClient(app)


@pytest.fixture
def sample_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ALLOWED_REPO_ROOTS", str(tmp_path))
    repo = tmp_path / "sample_repo"
    repo.mkdir()

    env = dict(os.environ)
    env["GIT_AUTHOR_NAME"] = "ApiTester"
    env["GIT_AUTHOR_EMAIL"] = "apitester@example.com"
    env["GIT_COMMITTER_NAME"] = "ApiTester"
    env["GIT_COMMITTER_EMAIL"] = "apitester@example.com"

    def _run(args: list[str]) -> None:
        subprocess.run(["git"] + args, cwd=str(repo), env=env, check=True, capture_output=True, text=True)

    _run(["init", "-b", "main"])
    _run(["config", "user.name", "ApiTester"])
    _run(["config", "user.email", "apitester@example.com"])

    # Initial file
    (repo / "README.md").write_text("# Sample Project\nWelcome to testing.\n", encoding="utf-8")
    (repo / "main.py").write_text("def run():\n    print('running')\n", encoding="utf-8")

    sub = repo / "pkg"
    sub.mkdir()
    (sub / "mod.py").write_text("def helper():\n    return 42\n", encoding="utf-8")

    _run(["add", "."])
    _run(["commit", "-m", "Initial commit"])

    # Commit 2
    (repo / "main.py").write_text("def run():\n    print('running v2')\n", encoding="utf-8")
    _run(["add", "main.py"])
    _run(["commit", "-m", "Update main runner"])

    return repo


def test_list_tools_endpoint(api_client: TestClient, sample_repo: Path):
    res = api_client.get("/api/project/tools", params={"repo_path": str(sample_repo)})
    assert res.status_code == 200
    data = res.json()
    assert data["repo_path"] == str(sample_repo.resolve())
    assert "tools" in data
    tool_names = [t["name"] for t in data["tools"]]
    assert "git" in tool_names
    assert "filesystem" in tool_names
    assert "terminal" in tool_names

    git_desc = next(t for t in data["tools"] if t["name"] == "git")
    assert "status" in git_desc["supported_operations"]
    assert "diff" in git_desc["supported_operations"]
    assert git_desc["is_read_only"] is True


def test_list_tools_rejects_missing_and_forbidden_paths(api_client: TestClient, tmp_path: Path):
    # Missing repo_path
    res1 = api_client.get("/api/project/tools")
    assert res1.status_code == 422 or res1.status_code == 400

    # Nonexistent path
    res2 = api_client.get("/api/project/tools", params={"repo_path": str(tmp_path / "ghost")})
    assert res2.status_code == 404

    # Outside allowed roots
    res3 = api_client.get("/api/project/tools", params={"repo_path": "/etc"})
    assert res3.status_code == 403


def test_execute_git_status(api_client: TestClient, sample_repo: Path):
    payload = {
        "repo_path": str(sample_repo),
        "tool_name": "git",
        "operation": "status",
        "arguments": {},
    }
    res = api_client.post("/api/project/tools/execute", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["tool_name"] == "git"
    assert data["operation"] == "status"
    assert data["output"]["is_clean"] is True
    assert data["output"]["branch"] == "main"
    assert data["evidence"]["category"] == "git_execution"
    assert data["evidence"]["success"] is True


def test_execute_git_log(api_client: TestClient, sample_repo: Path):
    payload = {
        "repo_path": str(sample_repo),
        "tool_name": "git",
        "operation": "log",
        "arguments": {"limit": 2},
    }
    res = api_client.post("/api/project/tools/execute", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["output"]["count"] == 2
    assert data["output"]["commits"][0]["message"] == "Update main runner"


def test_execute_git_diff(api_client: TestClient, sample_repo: Path):
    # Dirty the working tree
    (sample_repo / "README.md").write_text("# Modified\n", encoding="utf-8")
    payload = {
        "repo_path": str(sample_repo),
        "tool_name": "git",
        "operation": "diff",
        "arguments": {},
    }
    res = api_client.post("/api/project/tools/execute", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "Modified" in data["output"]["diff"]


def test_execute_filesystem_list_dir(api_client: TestClient, sample_repo: Path):
    payload = {
        "repo_path": str(sample_repo),
        "tool_name": "filesystem",
        "operation": "list_dir",
        "arguments": {"path": "."},
    }
    res = api_client.post("/api/project/tools/execute", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    entries = {e["name"]: e["type"] for e in data["output"]["entries"]}
    assert entries.get("README.md") == "file"
    assert entries.get("pkg") == "dir"


def test_execute_filesystem_read_file(api_client: TestClient, sample_repo: Path):
    payload = {
        "repo_path": str(sample_repo),
        "tool_name": "filesystem",
        "operation": "read_file",
        "arguments": {"path": "README.md"},
    }
    res = api_client.post("/api/project/tools/execute", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "Sample Project" in data["output"]["content"]


def test_execute_filesystem_search_text(api_client: TestClient, sample_repo: Path):
    payload = {
        "repo_path": str(sample_repo),
        "tool_name": "filesystem",
        "operation": "search_text",
        "arguments": {"pattern": "helper"},
    }
    res = api_client.post("/api/project/tools/execute", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["output"]["total_matches"] >= 1
    assert any("pkg/mod.py" in m["file"] for m in data["output"]["matches"])


def test_execute_blocks_mutating_patch_file(api_client: TestClient, sample_repo: Path):
    payload = {
        "repo_path": str(sample_repo),
        "tool_name": "filesystem",
        "operation": "patch_file",
        "arguments": {
            "path": "README.md",
            "old_content": "Sample Project",
            "new_content": "Pawned",
        },
    }
    res = api_client.post("/api/project/tools/execute", json=payload)
    assert res.status_code == 403
    assert "mutation_not_authorized" in res.json().get("error", "")


def test_execute_blocks_mutating_git_operations(api_client: TestClient, sample_repo: Path):
    for bad_op in ["commit", "push", "checkout", "reset", "merge"]:
        payload = {
            "repo_path": str(sample_repo),
            "tool_name": "git",
            "operation": bad_op,
            "arguments": {},
        }
        res = api_client.post("/api/project/tools/execute", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is False
        assert "unsupported or mutating" in str(data.get("error", "")).lower()


def test_execute_path_traversal_rejected(api_client: TestClient, sample_repo: Path):
    payload = {
        "repo_path": str(sample_repo),
        "tool_name": "filesystem",
        "operation": "read_file",
        "arguments": {"path": "../../etc/passwd"},
    }
    res = api_client.post("/api/project/tools/execute", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False
    assert "traversal" in str(data.get("error", "")).lower()


def test_execute_unknown_tool_rejected(api_client: TestClient, sample_repo: Path):
    payload = {
        "repo_path": str(sample_repo),
        "tool_name": "nonexistent_tool",
        "operation": "run",
        "arguments": {},
    }
    res = api_client.post("/api/project/tools/execute", json=payload)
    assert res.status_code == 404
    assert "tool_not_found" in res.json().get("error", "")
