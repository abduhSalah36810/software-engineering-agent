"""
Phase 0 Hardening Regression Tests.

Validates that the pipeline foundation gracefully handles:
- ignored directories (.git, venv, node_modules) in file tree
- non-existent or empty directories
- local directory reuse in clone_repo
- non-existent file reads in file operations tool
- missing or invalid repo_path in code_intelligence
"""

import os
import pytest
from src.helpers.file_tree import get_file_tree
from src.helpers.repo import clone_repo
from src.tools.file_operations import read_file
from src.nodes.code_intelligence import code_intelligence


def test_file_tree_ignores_internal_directories(tmp_path):
    # Setup test directory tree
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("git config")
    (tmp_path / "venv").mkdir()
    (tmp_path / "venv" / "pyvenv.cfg").write_text("venv config")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.json").write_text("{}")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "app.cpython-312.pyc").write_text("")

    tree = get_file_tree(str(tmp_path))

    # Must contain actual source
    assert "app.py" in tree
    # Must NOT walk ignored directories
    assert "pyvenv.cfg" not in tree
    assert ".git/config" not in tree
    assert "node_modules" not in tree
    assert "__pycache__" not in tree


def test_file_tree_nonexistent_and_empty(tmp_path):
    assert get_file_tree("") == ""
    assert get_file_tree("/nonexistent/path/xyz") == ""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    tree = get_file_tree(str(empty_dir))
    assert tree.strip() == str(empty_dir)


def test_clone_repo_local_dir_reuse(tmp_path):
    local_repo = tmp_path / "my_local_repo"
    local_repo.mkdir()
    (local_repo / "README.md").write_text("# Hello")

    result = clone_repo(str(local_repo))
    assert result == str(local_repo.resolve())


def test_read_file_nonexistent_returns_error_string(tmp_path):
    result = read_file.invoke({"repo_path": str(tmp_path), "file_path": "does_not_exist.py"})
    assert isinstance(result, str)
    assert "does not exist" in result.lower() or "error" in result.lower()


def test_code_intelligence_graceful_on_missing_repo_path():
    result = code_intelligence({"repo_path": None})
    assert result == {"indexed_document_count": 0}

    result2 = code_intelligence({"repo_path": "/nonexistent/repo/xyz"})
    assert result2 == {"indexed_document_count": 0}
