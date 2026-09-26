"""Tests for the SQLite engineering memory store."""

import os
import tempfile
import pytest
from src.memory.sqlite_store import EngineeringMemoryStore
from src.models.repo_profile import RepoProfile, TechnologyEntry


@pytest.fixture
def store(tmp_path):
    db = str(tmp_path / "test_memory.db")
    return EngineeringMemoryStore(db_path=db)


def test_save_and_load_profile(store):
    profile = RepoProfile(
        name="myrepo",
        repo_path="/tmp/myrepo",
        primary_language="python",
    )
    store.save_repo_profile(profile)
    loaded = store.load_repo_profile("myrepo")
    assert loaded is not None
    assert loaded["name"] == "myrepo"
    assert loaded["primary_language"] == "python"


def test_profile_exists(store):
    assert not store.repo_profile_exists("nonexistent")
    profile = RepoProfile(name="exists-repo", repo_path="/tmp/x")
    store.save_repo_profile(profile)
    assert store.repo_profile_exists("exists-repo")


def test_upsert_profile(store):
    profile = RepoProfile(name="upsert-repo", repo_path="/tmp/u", primary_language="go")
    store.save_repo_profile(profile)
    profile2 = RepoProfile(name="upsert-repo", repo_path="/tmp/u", primary_language="rust")
    store.save_repo_profile(profile2)
    loaded = store.load_repo_profile("upsert-repo")
    assert loaded["primary_language"] == "rust"


def test_save_and_load_decision(store):
    store.save_decision(
        repo_name="myrepo",
        subject="database",
        decision="use SQLite",
        rationale="local-first, no external service",
        source="observed",
    )
    decisions = store.load_decisions("myrepo")
    assert len(decisions) == 1
    assert decisions[0]["subject"] == "database"
    assert decisions[0]["decision"] == "use SQLite"


def test_save_and_load_investigation(store):
    inv_id = store.save_investigation(
        repo_name="myrepo",
        problem="Bug in parser",
        root_cause="off-by-one error in line 42",
        plan="fix the slice index",
        result={"files_to_modify": ["src/parser.py"]},
    )
    assert inv_id > 0
    investigations = store.load_investigations("myrepo")
    assert len(investigations) == 1
    assert investigations[0]["root_cause"] == "off-by-one error in line 42"
    assert investigations[0]["result"]["files_to_modify"] == ["src/parser.py"]


def test_save_and_load_change_record(store):
    store.save_change_record(
        repo_name="myrepo",
        commit_hash="abc123def456",
        changed_files=["src/a.py", "src/b.py"],
        architecture_impact="minor",
        drift_detected=False,
    )
    records = store.load_change_records("myrepo")
    assert len(records) == 1
    assert "src/a.py" in records[0]["changed_files"]
    assert records[0]["drift_detected"] is False


def test_change_record_dedup(store):
    store.save_change_record(
        repo_name="myrepo",
        commit_hash="abc123",
        changed_files=["x.py"],
    )
    # Second insert with same hash should be silently ignored (INSERT OR IGNORE)
    store.save_change_record(
        repo_name="myrepo",
        commit_hash="abc123",
        changed_files=["y.py"],
    )
    records = store.load_change_records("myrepo")
    assert len(records) == 1


def test_load_nonexistent_profile_returns_none(store):
    result = store.load_repo_profile("doesnt-exist")
    assert result is None


def test_multiple_repos_isolated(store):
    store.save_investigation("repo-a", "problem a", root_cause="cause a")
    store.save_investigation("repo-b", "problem b", root_cause="cause b")
    a_inv = store.load_investigations("repo-a")
    b_inv = store.load_investigations("repo-b")
    assert len(a_inv) == 1
    assert a_inv[0]["root_cause"] == "cause a"
    assert b_inv[0]["root_cause"] == "cause b"
