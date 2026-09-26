"""Tests for git_context helper."""

import os
import subprocess
import tempfile
import pytest
from src.helpers.git_context import get_git_context


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo with one commit."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=str(tmp_path), check=True, capture_output=True)
    (tmp_path / "hello.py").write_text("print('hello')")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"],
                   cwd=str(tmp_path), check=True, capture_output=True)
    return tmp_path


def test_non_git_dir(tmp_path):
    ctx = get_git_context(str(tmp_path))
    assert ctx.is_git_repo is False
    assert ctx.head_commit is None


def test_git_repo_basic(git_repo):
    ctx = get_git_context(str(git_repo))
    assert ctx.is_git_repo is True
    assert ctx.head_commit is not None
    assert len(ctx.head_commit) == 40  # full SHA
    assert ctx.branch is not None
    assert len(ctx.recent_commits) == 1
    assert ctx.recent_commits[0]["message"] == "initial commit"


def test_git_changed_files(git_repo):
    # Get initial commit
    ctx1 = get_git_context(str(git_repo))
    first_commit = ctx1.head_commit

    # Make a second commit
    (git_repo / "newfile.py").write_text("x = 1")
    subprocess.run(["git", "add", "."], cwd=str(git_repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add newfile"],
                   cwd=str(git_repo), check=True, capture_output=True)

    # Ask for changes since first commit
    ctx2 = get_git_context(str(git_repo), since_commit=first_commit)
    assert ctx2.is_git_repo is True
    assert "newfile.py" in ctx2.changed_files_since


def test_git_no_changes_since_head(git_repo):
    ctx = get_git_context(str(git_repo))
    # Since commit == HEAD, no changes
    ctx2 = get_git_context(str(git_repo), since_commit=ctx.head_commit)
    assert ctx2.changed_files_since == []
