"""Tests for the deterministic RepoDiscovery engine."""

import os
import pytest
from src.helpers.repo_discovery import RepoDiscovery
from src.models.repo_profile import RepoProfile


@pytest.fixture
def minimal_python_repo(tmp_path):
    """Minimal Python project structure."""
    (tmp_path / "requirements.txt").write_text("fastapi==0.100.0\nlangchain==0.1.0\n")
    (tmp_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_ok(): pass")
    return tmp_path


def test_discovers_python_language(minimal_python_repo):
    discovery = RepoDiscovery(str(minimal_python_repo))
    profile = discovery.discover()
    assert "python" in [l.lower() for l in profile.detected_languages]


def test_discovers_package_manager(minimal_python_repo):
    discovery = RepoDiscovery(str(minimal_python_repo))
    profile = discovery.discover()
    assert any("pip" in pm for pm in profile.package_managers)


def test_discovers_frameworks(minimal_python_repo):
    discovery = RepoDiscovery(str(minimal_python_repo))
    profile = discovery.discover()
    framework_names = [f.name for f in profile.frameworks]
    assert any("FastAPI" in n or "fastapi" in n.lower() for n in framework_names)


def test_detects_tests(minimal_python_repo):
    discovery = RepoDiscovery(str(minimal_python_repo))
    profile = discovery.discover()
    assert profile.has_tests is True


def test_returns_repo_profile_instance(minimal_python_repo):
    discovery = RepoDiscovery(str(minimal_python_repo))
    profile = discovery.discover()
    assert isinstance(profile, RepoProfile)
    assert profile.repo_path == str(minimal_python_repo)


def test_docker_detection(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
    discovery = RepoDiscovery(str(tmp_path))
    profile = discovery.discover()
    assert profile.has_docker is True


def test_no_docker_by_default(minimal_python_repo):
    discovery = RepoDiscovery(str(minimal_python_repo))
    profile = discovery.discover()
    assert profile.has_docker is False


def test_empty_repo(tmp_path):
    discovery = RepoDiscovery(str(tmp_path))
    profile = discovery.discover()
    assert isinstance(profile, RepoProfile)
    # Should not crash on empty directory
