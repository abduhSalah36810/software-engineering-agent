# tests/test_api_overview.py
"""
Automated tests for Phase FE-1A Read-Only Project Overview API.

Verifies:
  1. Valid repository and response schema (with and without assessment).
  2. Nonexistent repository (HTTP 404).
  3. Rejection of repository outside permitted roots (HTTP 403).
  4. Read-only SQLite behavior (zero mutations across all tables).
  5. Detection of uncommitted Git changes (dirty tree and dimensions).
  6. Missing profile and assessment data (explicit None, no fabrication).
  7. Stale baseline representation (unreachable commit triggers warning).
  8. No invocation of agent graph or TerminalTool during GET.
  9. Edge cases: missing param, file path, non-git dir, validity counts.
"""

import os
import subprocess
import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.memory.sqlite_store import EngineeringMemoryStore
from src.models.repo_profile import Finding, RepoProfile, TechnologyEntry


@pytest.fixture
def test_client():
    return TestClient(app)


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Provides an isolated temporary database and configured allowed roots."""
    db_path = tmp_path / "test_memory.db"
    monkeypatch.setenv("AGENT_MEMORY_DB", str(db_path))
    monkeypatch.setenv("ALLOWED_REPO_ROOTS", str(tmp_path))
    store = EngineeringMemoryStore(str(db_path))
    return {
        "tmp_path": tmp_path,
        "db_path": db_path,
        "store": store,
    }


def _create_git_repo(repo_dir: Path) -> Path:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo_dir), check=True)
    code_file = repo_dir / "calculator.py"
    code_file.write_text("def add(a: int, b: int) -> int:\n    return a + b\n")
    subprocess.run(["git", "add", "calculator.py"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "feat: initial commit"], cwd=str(repo_dir), check=True)
    return repo_dir


# ── Test 1: Valid repository and response schema ──────────────────────────────


def test_valid_repository_and_response_schema(test_client, isolated_env):
    repo_dir = _create_git_repo(isolated_env["tmp_path"] / "calc_project")
    store = isolated_env["store"]
    canonical_id = str(repo_dir.resolve())

    # Pre-populate a profile in SQLite
    profile = RepoProfile(
        name="Calculator",
        repo_path=canonical_id,
        primary_language="python",
        detected_languages=["python"],
        package_managers=["pip"],
        has_tests=False,
        findings=[
            Finding(
                category="language",
                observation="Python detected",
                evidence="calculator.py",
                source="observed",
                severity="info",
            )
        ],
    )
    store.save_repo_profile(profile, repo_id=canonical_id)

    # 1. Without assessment (fast path)
    res = test_client.get(f"/api/project/overview?repo_path={repo_dir}&include_assessment=false")
    assert res.status_code == 200
    data = res.json()

    assert data["identity"]["repo_id"] == canonical_id
    assert data["identity"]["repo_name"] == "Calculator"
    assert data["identity"]["repo_path"] == canonical_id

    assert data["git"]["is_git_repo"] is True
    assert data["git"]["head_commit"] is not None
    assert data["git"]["is_dirty"] is False
    assert len(data["git"]["recent_commits"]) >= 1

    assert data["profile"] is not None
    assert data["profile"]["name"] == "Calculator"
    assert data["profile"]["primary_language"] == "python"

    assert data["health"] is None
    assert data["stage"] is None
    assert data["assessment_status"] == "not_requested"
    assert data["assessment_message"] is not None

    # 2. With assessment (explicitly requested)
    res_assessed = test_client.get(f"/api/project/overview?repo_path={repo_dir}&include_assessment=true")
    assert res_assessed.status_code == 200
    data_assessed = res_assessed.json()

    assert data_assessed["assessment_status"] == "computed"
    assert data_assessed["health"] is not None
    assert data_assessed["health"]["is_clean"] is True
    assert data_assessed["health"]["scanned_file_count"] >= 1
    assert data_assessed["health"]["freshly_computed"] is True

    assert data_assessed["stage"] is not None
    assert data_assessed["stage"]["stage"] in ["IDEA", "EARLY", "MID", "LATE", "MATURE"]
    assert data_assessed["stage"]["confidence"] in ["LOW", "MEDIUM", "HIGH"]
    assert data_assessed["stage"]["freshly_computed"] is True


# ── Test 2: Nonexistent repository ────────────────────────────────────────────


def test_nonexistent_repository(test_client, isolated_env):
    missing_path = isolated_env["tmp_path"] / "does_not_exist_xyz"
    res = test_client.get(f"/api/project/overview?repo_path={missing_path}")
    assert res.status_code == 404
    data = res.json()
    assert data["error"] == "not_found"
    assert "exist" in data["detail"]


# ── Test 3: Rejection of repository outside permitted roots ───────────────────


def test_rejection_outside_permitted_roots(test_client, tmp_path, monkeypatch):
    allowed_root = tmp_path / "allowed_zone"
    allowed_root.mkdir()
    forbidden_root = tmp_path / "forbidden_zone"
    forbidden_root.mkdir()

    monkeypatch.setenv("ALLOWED_REPO_ROOTS", str(allowed_root))
    monkeypatch.setenv("AGENT_MEMORY_DB", str(tmp_path / "test.db"))

    res = test_client.get(f"/api/project/overview?repo_path={forbidden_root}")
    assert res.status_code == 403
    data = res.json()
    assert data["error"] == "forbidden"
    assert "permitted" in data["detail"]


# ── Test 4: Read-only SQLite behavior ─────────────────────────────────────────


def test_readonly_sqlite_behavior(test_client, isolated_env):
    repo_dir = _create_git_repo(isolated_env["tmp_path"] / "readonly_repo")
    db_path = isolated_env["db_path"]
    store = isolated_env["store"]
    canonical_id = str(repo_dir.resolve())

    # Seed baseline records
    store.save_decision(
        repo_name=canonical_id,
        subject="Database",
        decision="Use SQLite",
        rationale="Embedded local intelligence",
        source="observed",
    )

    def _get_table_counts():
        conn = sqlite3.connect(db_path)
        tables = ["repo_profiles", "decisions", "change_records", "investigations"]
        counts = {}
        for t in tables:
            counts[t] = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        conn.close()
        return counts

    initial_counts = _get_table_counts()
    assert initial_counts["decisions"] == 1

    # Execute read-only requests
    for _ in range(3):
        res1 = test_client.get(f"/api/project/overview?repo_path={repo_dir}&include_assessment=false")
        assert res1.status_code == 200

        res2 = test_client.get(f"/api/project/overview?repo_path={repo_dir}&include_assessment=true")
        assert res2.status_code == 200

    after_counts = _get_table_counts()
    assert initial_counts == after_counts, f"SQLite row counts modified! Before: {initial_counts}, After: {after_counts}"


# ── Test 5: Detection of uncommitted Git changes ──────────────────────────────


def test_detection_of_uncommitted_git_changes(test_client, isolated_env):
    repo_dir = _create_git_repo(isolated_env["tmp_path"] / "dirty_repo")
    store = isolated_env["store"]
    canonical_id = str(repo_dir.resolve())

    # Establish baseline commit in memory
    res_git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_dir), capture_output=True, text=True)
    head = res_git.stdout.strip()
    store.save_change_record(repo_name=canonical_id, commit_hash=head, changed_files="[]")

    # Add uncommitted untracked file and modified file
    untracked = repo_dir / "scratch_note.py"
    untracked.write_text("x = 42\n")

    modified = repo_dir / "calculator.py"
    modified.write_text("def add(a: int, b: int) -> int:\n    return a + b + 10\n")

    res = test_client.get(f"/api/project/overview?repo_path={repo_dir}")
    assert res.status_code == 200
    data = res.json()

    # Git working tree status
    assert data["git"]["is_dirty"] is True
    assert data["git"]["has_uncommitted_changes"] is True
    uncommitted = data["git"]["uncommitted_files"]
    assert any("scratch_note.py" in f for f in uncommitted)
    assert any("calculator.py" in f for f in uncommitted)

    # Incremental status & dimensions
    assert data["incremental"]["has_uncommitted_changes"] is True
    assert data["incremental"]["status"] == "dirty"
    assert "source_code" in data["incremental"]["uncommitted_dimensions"]


# ── Test 6: Missing profile and assessment data ───────────────────────────────


def test_missing_profile_and_assessment_data(test_client, isolated_env):
    repo_dir = _create_git_repo(isolated_env["tmp_path"] / "fresh_repo")

    # No data seeded in SQLite
    res = test_client.get(f"/api/project/overview?repo_path={repo_dir}&include_assessment=false")
    assert res.status_code == 200
    data = res.json()

    # Profile must be explicitly None, not fabricated defaults
    assert data["profile"] is None
    assert data["health"] is None
    assert data["stage"] is None
    assert data["assessment_status"] == "not_requested"
    assert data["memory"]["has_engineering_history"] is False
    assert data["memory"]["decisions_count"] == 0
    assert data["memory"]["investigations_count"] == 0


# ── Test 7: Stale baseline representation ─────────────────────────────────────


def test_stale_baseline_representation(test_client, isolated_env):
    repo_dir = _create_git_repo(isolated_env["tmp_path"] / "stale_repo")
    store = isolated_env["store"]
    canonical_id = str(repo_dir.resolve())

    # Record history with an unreachable commit hash
    unreachable_commit = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    store.save_change_record(
        repo_name=canonical_id,
        commit_hash=unreachable_commit,
        changed_files="[]",
    )
    store.save_decision(
        repo_name=canonical_id,
        subject="Testing",
        decision="Use pytest",
        rationale="Standard",
        source="observed",
    )

    res = test_client.get(f"/api/project/overview?repo_path={repo_dir}")
    assert res.status_code == 200
    data = res.json()

    assert data["incremental"]["status"] == "stale_baseline"
    assert data["incremental"]["is_baseline_stale"] is True
    assert data["incremental"]["requires_reverification"] is True
    assert data["memory"]["stale_baseline_warning"] is True


# ── Test 8: No invocation of agent graph or TerminalTool during GET ───────────


def test_no_invocation_of_agent_graph_or_terminal_tool(test_client, isolated_env, monkeypatch):
    repo_dir = _create_git_repo(isolated_env["tmp_path"] / "isolation_repo")

    # Monkeypatch agent graph
    def fake_graph_invoke(*args, **kwargs):
        pytest.fail("LangGraph myapp.invoke was called during read-only GET!")

    monkeypatch.setattr("src.graph.myapp.invoke", fake_graph_invoke)

    # Monkeypatch TerminalTool
    from src.tools.terminal import TerminalTool

    def fake_terminal_execute(*args, **kwargs):
        pytest.fail("TerminalTool.execute was called during read-only GET!")

    monkeypatch.setattr(TerminalTool, "execute", fake_terminal_execute)

    # Perform request with full assessment
    res = test_client.get(f"/api/project/overview?repo_path={repo_dir}&include_assessment=true")
    assert res.status_code == 200


# ── Test 9: Edge cases (missing param, file path, non-git dir, validity counts)


def test_missing_repo_path_query_param(test_client):
    res = test_client.get("/api/project/overview")
    assert res.status_code in [400, 422]


def test_repo_path_is_file(test_client, isolated_env):
    f = isolated_env["tmp_path"] / "a_file.txt"
    f.write_text("not a directory")
    res = test_client.get(f"/api/project/overview?repo_path={f}")
    assert res.status_code == 400
    data = res.json()
    assert data["error"] == "not_a_directory"


def test_non_git_directory(test_client, isolated_env):
    plain_dir = isolated_env["tmp_path"] / "plain_dir"
    plain_dir.mkdir()
    res = test_client.get(f"/api/project/overview?repo_path={plain_dir}")
    assert res.status_code == 200
    data = res.json()
    assert data["git"]["is_git_repo"] is False
    assert data["incremental"]["status"] == "non_git"


def test_requires_verification_records_trigger_warning(test_client, isolated_env):
    repo_dir = _create_git_repo(isolated_env["tmp_path"] / "verify_repo")
    store = isolated_env["store"]
    canonical_id = str(repo_dir.resolve())

    # Insert decision and mark it REQUIRES_VERIFICATION
    store.save_decision(
        repo_name=canonical_id,
        subject="Arch",
        decision="Clean arch",
        rationale="maintainability",
        source="observed",
    )
    decisions = store.load_decisions(canonical_id)
    dec_id = decisions[0]["id"]
    store.update_record_validity(
        table="decisions",
        record_id=dec_id,
        current_validity="REQUIRES_VERIFICATION",
        invalidated_at="2026-10-12T00:00:00Z",
        invalidation_reason="Touched dimensions",
    )

    res = test_client.get(f"/api/project/overview?repo_path={repo_dir}")
    assert res.status_code == 200
    data = res.json()

    assert data["memory"]["decisions_by_validity"].get("REQUIRES_VERIFICATION") == 1
    assert data["memory"]["requires_verification_count"] == 1
    assert data["memory"]["stale_baseline_warning"] is True


# ── Test 10: CORS Allowed and Disallowed Origins ──────────────────────────────


def test_cors_allowed_and_disallowed_origins(test_client, isolated_env):
    repo_dir = _create_git_repo(isolated_env["tmp_path"] / "cors_repo")

    # 1. Allowed origin GET request
    res_allowed = test_client.get(
        f"/api/project/overview?repo_path={repo_dir}",
        headers={"Origin": "http://localhost:5173"},
    )
    assert res_allowed.status_code == 200
    assert res_allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert res_allowed.headers.get("access-control-allow-credentials") == "true"

    # 2. Allowed origin OPTIONS preflight request
    res_preflight = test_client.options(
        f"/api/project/overview?repo_path={repo_dir}",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res_preflight.status_code == 200
    assert res_preflight.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert res_preflight.headers.get("access-control-allow-credentials") == "true"

    # 3. Disallowed origin GET request
    res_disallowed = test_client.get(
        f"/api/project/overview?repo_path={repo_dir}",
        headers={"Origin": "http://malicious-site.example.com"},
    )
    assert res_disallowed.status_code == 200
    # Starlette CORSMiddleware omits access-control-allow-origin for disallowed origins
    assert res_disallowed.headers.get("access-control-allow-origin") is None

    # 4. Disallowed origin OPTIONS preflight request
    res_disallowed_opt = test_client.options(
        f"/api/project/overview?repo_path={repo_dir}",
        headers={
            "Origin": "http://malicious-site.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res_disallowed_opt.status_code == 400
    assert res_disallowed_opt.headers.get("access-control-allow-origin") is None


def test_cors_get_cors_origins_configurable(monkeypatch):
    from src.main import get_cors_origins, DEFAULT_CORS_ORIGINS

    # Default origins
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    assert get_cors_origins() == DEFAULT_CORS_ORIGINS

    # Custom comma-separated origins
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://frontend.internal:3000, http://custom.dev:5173")
    assert get_cors_origins() == ["http://frontend.internal:3000", "http://custom.dev:5173"]

    # Custom semicolon-separated origins
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://app.local:8080; http://workspace.local:4000")
    assert get_cors_origins() == ["http://app.local:8080", "http://workspace.local:4000"]


# ── Test 11: SQL COUNT Accuracy & Truncation Prevention ───────────────────────


def test_memory_counts_sql_truncation_fix(test_client, isolated_env):
    repo_dir = _create_git_repo(isolated_env["tmp_path"] / "count_repo")
    db_path = isolated_env["db_path"]
    canonical_id = str(repo_dir.resolve())

    # Directly insert 250 investigations (exceeds previous limit of 20 or 200):
    #   - 200 VALID
    #   - 30 REQUIRES_VERIFICATION
    #   - 20 INVALID
    # And 60 decisions:
    #   - 50 VALID
    #   - 10 REQUIRES_VERIFICATION
    conn = sqlite3.connect(db_path)
    now_str = "2026-10-12T12:00:00Z"

    inv_records = []
    for i in range(200):
        inv_records.append((canonical_id, f"problem {i}", "root", "plan", "{}", now_str, "VALID"))
    for i in range(200, 230):
        inv_records.append((canonical_id, f"problem {i}", "root", "plan", "{}", now_str, "REQUIRES_VERIFICATION"))
    for i in range(230, 250):
        inv_records.append((canonical_id, f"problem {i}", "root", "plan", "{}", now_str, "INVALID"))

    conn.executemany(
        """
        INSERT INTO investigations
            (repo_name, problem, root_cause, plan, result_json, created_at, current_validity)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        inv_records,
    )

    dec_records = []
    for i in range(50):
        dec_records.append((canonical_id, f"subject {i}", "dec", "rat", "obs", now_str, "VALID"))
    for i in range(50, 60):
        dec_records.append((canonical_id, f"subject {i}", "dec", "rat", "obs", now_str, "REQUIRES_VERIFICATION"))

    conn.executemany(
        """
        INSERT INTO decisions
            (repo_name, subject, decision, rationale, source, created_at, current_validity)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        dec_records,
    )
    conn.commit()
    conn.close()

    res = test_client.get(f"/api/project/overview?repo_path={repo_dir}")
    assert res.status_code == 200
    data = res.json()

    # Investigations: must be exactly 250, not capped at 20 or 200
    mem = data["memory"]
    assert mem["investigations_count"] == 250
    assert mem["investigations_by_validity"].get("VALID") == 200
    assert mem["investigations_by_validity"].get("REQUIRES_VERIFICATION") == 30
    assert mem["investigations_by_validity"].get("INVALID") == 20

    # Decisions: must be exactly 60
    assert mem["decisions_count"] == 60
    assert mem["decisions_by_validity"].get("VALID") == 50
    assert mem["decisions_by_validity"].get("REQUIRES_VERIFICATION") == 10

    # Requires verification total
    assert mem["requires_verification_count"] == 40
    assert mem["stale_baseline_warning"] is True


def test_store_count_methods_direct(isolated_env):
    store = isolated_env["store"]
    repo_name = "test_direct_repo"

    # Empty store returns empty dict
    assert store.count_decisions_by_validity(repo_name) == {}
    assert store.count_investigations_by_validity(repo_name) == {}

    # Seed records
    store.save_decision(repo_name, "db", "sqlite", "fast", "obs")
    store.save_investigation(repo_name, "bug", "root", "fix", {})

    dec_counts = store.count_decisions_by_validity(repo_name)
    assert dec_counts.get("VALID") == 1

    inv_counts = store.count_investigations_by_validity(repo_name)
    assert inv_counts.get("VALID") == 1
