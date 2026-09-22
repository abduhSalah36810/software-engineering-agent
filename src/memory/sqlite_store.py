"""
SQLite-backed engineering memory store.

Persists structured knowledge about repositories across agent runs.
Each repository gets its own namespace (repo_name key) within a shared SQLite file.

Tables:
  - repo_profiles:     serialized RepoProfile per repository
  - decisions:         technology and architectural decisions with source tracking
  - change_records:    per-commit architectural observations
  - investigations:    past bug investigations and their outcomes
"""

import sqlite3
import json
import os
from datetime import datetime, timezone
from contextlib import contextmanager


SCHEMA = """
CREATE TABLE IF NOT EXISTS repo_profiles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_name   TEXT UNIQUE NOT NULL,
    profile_json TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_name   TEXT NOT NULL,
    subject     TEXT NOT NULL,
    decision    TEXT NOT NULL,
    rationale   TEXT NOT NULL,
    source      TEXT NOT NULL,
    reference   TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS change_records (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_name            TEXT NOT NULL,
    commit_hash          TEXT UNIQUE NOT NULL,
    changed_files        TEXT NOT NULL,
    changed_symbols      TEXT,
    architecture_impact  TEXT,
    drift_detected       INTEGER DEFAULT 0,
    review               TEXT,
    created_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS investigations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_name   TEXT NOT NULL,
    problem     TEXT NOT NULL,
    root_cause  TEXT,
    plan        TEXT,
    result_json TEXT,
    created_at  TEXT NOT NULL
);
"""


class EngineeringMemoryStore:
    """
    SQLite-backed store for per-repository engineering memory.

    Usage:
        store = EngineeringMemoryStore()              # uses AGENT_MEMORY_DB env or ./agent_memory.db
        store = EngineeringMemoryStore("/custom/path/memory.db")
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("AGENT_MEMORY_DB", "./agent_memory.db")
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ─── Repo Profile ────────────────────────────────────────────────────────

    def save_repo_profile(self, profile) -> None:
        """Upsert a RepoProfile (accepts RepoProfile dataclass or dict)."""
        if hasattr(profile, "to_json"):
            profile_json = profile.to_json()
            repo_name = profile.name
        else:
            profile_json = json.dumps(profile)
            repo_name = profile.get("name", "unknown")

        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO repo_profiles (repo_name, profile_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(repo_name) DO UPDATE SET
                    profile_json = excluded.profile_json,
                    updated_at   = excluded.updated_at
                """,
                (repo_name, profile_json, now, now),
            )

    def load_repo_profile(self, repo_name: str) -> dict | None:
        """Load a stored RepoProfile as a dict. Returns None if not found."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_json FROM repo_profiles WHERE repo_name = ?",
                (repo_name,),
            ).fetchone()
            if row is None:
                return None
            return json.loads(row["profile_json"])

    def repo_profile_exists(self, repo_name: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM repo_profiles WHERE repo_name = ?",
                (repo_name,),
            ).fetchone()
            return row is not None

    # ─── Decisions ───────────────────────────────────────────────────────────

    def save_decision(
        self,
        repo_name: str,
        subject: str,
        decision: str,
        rationale: str,
        source: str,
        reference: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO decisions
                    (repo_name, subject, decision, rationale, source, reference, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (repo_name, subject, decision, rationale, source, reference, self._now()),
            )

    def load_decisions(self, repo_name: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE repo_name = ? ORDER BY created_at DESC",
                (repo_name,),
            ).fetchall()
            return [dict(row) for row in rows]

    # ─── Change Records ───────────────────────────────────────────────────────

    def save_change_record(
        self,
        repo_name: str,
        commit_hash: str,
        changed_files: list[str],
        changed_symbols: list[str] | None = None,
        architecture_impact: str | None = None,
        drift_detected: bool = False,
        review: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO change_records
                    (repo_name, commit_hash, changed_files, changed_symbols,
                     architecture_impact, drift_detected, review, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    repo_name,
                    commit_hash,
                    json.dumps(changed_files),
                    json.dumps(changed_symbols) if changed_symbols else None,
                    architecture_impact,
                    int(drift_detected),
                    review,
                    self._now(),
                ),
            )

    def load_change_records(self, repo_name: str, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM change_records WHERE repo_name = ? ORDER BY created_at DESC LIMIT ?",
                (repo_name, limit),
            ).fetchall()
            records = []
            for row in rows:
                r = dict(row)
                r["changed_files"] = json.loads(r["changed_files"])
                r["changed_symbols"] = json.loads(r["changed_symbols"]) if r["changed_symbols"] else []
                r["drift_detected"] = bool(r["drift_detected"])
                records.append(r)
            return records

    # ─── Investigations ───────────────────────────────────────────────────────

    def save_investigation(
        self,
        repo_name: str,
        problem: str,
        root_cause: str | None = None,
        plan: str | None = None,
        result: dict | None = None,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO investigations
                    (repo_name, problem, root_cause, plan, result_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    repo_name,
                    problem,
                    root_cause,
                    plan,
                    json.dumps(result) if result else None,
                    self._now(),
                ),
            )
            return cursor.lastrowid

    def load_investigations(self, repo_name: str, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM investigations WHERE repo_name = ? ORDER BY created_at DESC LIMIT ?",
                (repo_name, limit),
            ).fetchall()
            result = []
            for row in rows:
                r = dict(row)
                r["result"] = json.loads(r["result_json"]) if r["result_json"] else None
                result.append(r)
            return result
