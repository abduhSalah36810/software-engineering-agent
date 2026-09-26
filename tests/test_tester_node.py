"""Tests for the tester node."""

import os
import pytest
from src.nodes.tester import tester


def test_no_modified_files():
    state = {"repo_path": "/tmp", "modified_files": []}
    result = tester(state)
    assert result["test_passed"] is True
    assert "No modified files" in result["test_output"]


def test_none_modified_files():
    state = {"repo_path": "/tmp", "modified_files": None}
    result = tester(state)
    assert result["test_passed"] is True


def test_valid_python_file(tmp_path):
    f = tmp_path / "good.py"
    f.write_text("def hello():\n    return 42\n")
    state = {
        "repo_path": str(tmp_path),
        "modified_files": ["good.py"],
    }
    result = tester(state)
    assert result["test_passed"] is True
    assert "Syntax OK" in result["test_output"]


def test_syntax_error_python_file(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("def broken(\n    pass\n")
    state = {
        "repo_path": str(tmp_path),
        "modified_files": ["bad.py"],
    }
    result = tester(state)
    assert result["test_passed"] is False
    assert "Syntax ERROR" in result["test_output"]


def test_nonexistent_file_does_not_fail(tmp_path):
    """Coder may list files it plans to modify but hasn't yet -- not a test failure."""
    state = {
        "repo_path": str(tmp_path),
        "modified_files": ["src/not_yet_written.py"],
    }
    result = tester(state)
    assert result["test_passed"] is True
    assert "not found" in result["test_output"]


def test_non_python_file_skipped(tmp_path):
    f = tmp_path / "README.md"
    f.write_text("# Hello")
    state = {
        "repo_path": str(tmp_path),
        "modified_files": ["README.md"],
    }
    result = tester(state)
    assert result["test_passed"] is True
    assert "Skipped" in result["test_output"]
