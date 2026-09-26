"""Tests for the RepoProfile model and serialization."""

import pytest
from src.models.repo_profile import RepoProfile, TechnologyEntry, Finding


def make_profile():
    return RepoProfile(
        name="test-repo",
        repo_path="/tmp/test-repo",
        detected_languages=["python", "javascript"],
        primary_language="python",
        package_managers=["pip"],
        frameworks=[
            TechnologyEntry(name="FastAPI", purpose="web framework", version="0.100.0")
        ],
        databases=[
            TechnologyEntry(name="SQLite", purpose="engineering memory")
        ],
        findings=[
            Finding(
                category="architecture",
                observation="Agent architecture detected",
                evidence="nodes/ and graph.py found",
                source="observed",
                severity="info",
            )
        ],
        has_tests=True,
        has_docker=False,
    )


def test_to_dict_roundtrip():
    profile = make_profile()
    d = profile.to_dict()
    restored = RepoProfile.from_dict(d)
    assert restored.name == profile.name
    assert restored.primary_language == profile.primary_language
    assert len(restored.frameworks) == 1
    assert restored.frameworks[0].name == "FastAPI"
    assert len(restored.findings) == 1
    assert restored.findings[0].category == "architecture"


def test_to_json_valid():
    import json
    profile = make_profile()
    j = profile.to_json()
    data = json.loads(j)
    assert data["name"] == "test-repo"
    assert data["primary_language"] == "python"


def test_summary_contains_name():
    profile = make_profile()
    summary = profile.summary()
    assert "test-repo" in summary
    assert "FastAPI" in summary


def test_empty_profile_summary():
    profile = RepoProfile(name="empty", repo_path="/tmp/empty")
    summary = profile.summary()
    assert "empty" in summary


def test_architecture_drift_detected():
    profile = RepoProfile(
        name="drift-repo",
        repo_path="/tmp/drift",
        architecture_style_observed="microservices",
        architecture_style_documented="monolith",
    )
    summary = profile.summary()
    assert "drift" in summary.lower()
