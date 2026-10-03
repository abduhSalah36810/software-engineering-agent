"""
SQLite-backed engineering memory store.

Persists structured knowledge about repositories across agent runs.
Each repository gets its own namespace (repo_name key) within a shared SQLite file.
The primary repository identity key is the canonical resolved path string (repo_id).

Tables:
  - repo_profiles:     serialized RepoProfile per repository
  - decisions:         technology and architectural decisions with source tracking
  - change_records:    per-commit architectural observations
  - investigations:    past bug investigations and their outcomes
"""

import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager

from src.helpers.repo import get_canonical_repo_id


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

# Phase 4.3.5: backward-compatible validity tracking columns.
SCHEMA_MIGRATION_435 = """
ALTER TABLE decisions ADD COLUMN current_validity TEXT DEFAULT 'VALID';
ALTER TABLE decisions ADD COLUMN invalidated_at TEXT;
ALTER TABLE decisions ADD COLUMN invalidation_reason TEXT;
ALTER TABLE investigations ADD COLUMN current_validity TEXT DEFAULT 'VALID';
ALTER TABLE investigations ADD COLUMN invalidated_at TEXT;
ALTER TABLE investigations ADD COLUMN invalidation_reason TEXT;
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
        # Phase 4.3.5: run validity-tracking migration (idempotent).
        self._apply_migration_435()

    def _apply_migration_435(self) -> None:
        """Apply Phase 4.3.5 validity columns; silently ignore 'duplicate column' errors."""
        statements = [s.strip() for s in SCHEMA_MIGRATION_435.strip().split(";") if s.strip()]
        conn = None
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            for stmt in statements:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            conn.commit()
        finally:
            if conn:
                conn.close()

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

    def save_repo_profile(self, profile, repo_id: str | None = None) -> None:
        """
        Upsert a RepoProfile (accepts RepoProfile dataclass or dict).
        The primary key is the canonical repository identity (repo_id).
        """
        if hasattr(profile, "to_json"):
            profile_json = profile.to_json()
            r_path = getattr(profile, "repo_path", None)
            repo_identity = repo_id or (get_canonical_repo_id(r_path) if r_path else profile.name)
        else:
            profile_json = json.dumps(profile)
            r_path = profile.get("repo_path") if isinstance(profile, dict) else None
            repo_identity = repo_id or (get_canonical_repo_id(r_path) if r_path else profile.get("name", "unknown"))

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
                (repo_identity, profile_json, now, now),
            )

    def load_repo_profile(self, repo_name: str) -> dict | None:
        """
        Load a stored RepoProfile as a dict.
        Matches canonical repo_id first, then falls back to resolved path or display name.
        Returns None if not found.
        """
        with self._connect() as conn:
            # 1. Exact match on repo_name column
            row = conn.execute(
                "SELECT profile_json FROM repo_profiles WHERE repo_name = ?",
                (repo_name,),
            ).fetchone()
            if row is not None:
                return json.loads(row["profile_json"])

            # 2. Try canonical resolved path if repo_name is a path
            try:
                canonical = get_canonical_repo_id(repo_name)
                if canonical != repo_name:
                    row = conn.execute(
                        "SELECT profile_json FROM repo_profiles WHERE repo_name = ?",
                        (canonical,),
                    ).fetchone()
                    if row is not None:
                        return json.loads(row["profile_json"])
            except Exception:
                pass

            # 3. Fallback: match by display name inside profile_json for legacy rows
            rows = conn.execute("SELECT profile_json FROM repo_profiles").fetchall()
            for r in rows:
                try:
                    data = json.loads(r["profile_json"])
                    if data.get("name") == repo_name:
                        return data
                except Exception:
                    continue

            return None

    def repo_profile_exists(self, repo_name: str) -> bool:
        return self.load_repo_profile(repo_name) is not None

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
        """
        Save a decision record.
        repo_name represents the canonical repository identity.
        """
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
            if not rows:
                canonical = get_canonical_repo_id(repo_name)
                if canonical != repo_name:
                    rows = conn.execute(
                        "SELECT * FROM decisions WHERE repo_name = ? ORDER BY created_at DESC",
                        (canonical,),
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
        """
        Save a commit-level change record.
        repo_name represents the canonical repository identity.
        """
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
            if not rows:
                canonical = get_canonical_repo_id(repo_name)
                if canonical != repo_name:
                    rows = conn.execute(
                        "SELECT * FROM change_records WHERE repo_name = ? ORDER BY created_at DESC LIMIT ?",
                        (canonical, limit),
                    ).fetchall()
            result = []
            for row in rows:
                r = dict(row)
                r["changed_files"] = json.loads(r["changed_files"])
                r["changed_symbols"] = (
                    json.loads(r["changed_symbols"]) if r["changed_symbols"] else None
                )
                r["drift_detected"] = bool(r["drift_detected"])
                result.append(r)
            return result

    # ─── Investigations ───────────────────────────────────────────────────────

    def save_investigation(
        self,
        repo_name: str,
        problem: str,
        root_cause: str | None = None,
        plan: str | None = None,
        result: dict | None = None,
    ) -> int:
        """
        Save an investigation record.
        repo_name represents the canonical repository identity.
        """
        result_json = json.dumps(result) if result else None
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO investigations
                    (repo_name, problem, root_cause, plan, result_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (repo_name, problem, root_cause, plan, result_json, self._now()),
            )
            return cursor.lastrowid

    def load_investigations(self, repo_name: str, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM investigations WHERE repo_name = ? ORDER BY created_at DESC LIMIT ?",
                (repo_name, limit),
            ).fetchall()
            if not rows:
                canonical = get_canonical_repo_id(repo_name)
                if canonical != repo_name:
                    rows = conn.execute(
                        "SELECT * FROM investigations WHERE repo_name = ? ORDER BY created_at DESC LIMIT ?",
                        (canonical, limit),
                    ).fetchall()
            result = []
            for row in rows:
                r = dict(row)
                r["result"] = json.loads(r["result_json"]) if r["result_json"] else None
                result.append(r)
            return result

    # ─── Phase 4.3.5: Validity Operations ────────────────────────────────────

    def update_record_validity(
        self,
        table: str,
        record_id: int,
        current_validity: str,
        invalidated_at: str | None = None,
        invalidation_reason: str | None = None,
    ) -> None:
        """
        Update the current_validity (and optional audit fields) of a
        decision or investigation record.
        """
        if table not in ("decisions", "investigations"):
            raise ValueError(f"update_record_validity: unknown table '{table}'")
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE {table}
                SET current_validity    = ?,
                    invalidated_at      = ?,
                    invalidation_reason = ?
                WHERE id = ?
                """,
                (current_validity, invalidated_at, invalidation_reason, record_id),
            )

    def load_decisions_by_validity(
        self, repo_name: str, validity: str | None = None
    ) -> list[dict]:
        """
        Load decisions, optionally filtered by current_validity.
        """
        canonical = get_canonical_repo_id(repo_name)
        with self._connect() as conn:
            if validity is not None:
                rows = conn.execute(
                    "SELECT * FROM decisions WHERE repo_name = ? AND current_validity = ? ORDER BY created_at DESC",
                    (repo_name, validity),
                ).fetchall()
                if not rows and canonical != repo_name:
                    rows = conn.execute(
                        "SELECT * FROM decisions WHERE repo_name = ? AND current_validity = ? ORDER BY created_at DESC",
                        (canonical, validity),
                    ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM decisions WHERE repo_name = ? ORDER BY created_at DESC",
                    (repo_name,),
                ).fetchall()
                if not rows and canonical != repo_name:
                    rows = conn.execute(
                        "SELECT * FROM decisions WHERE repo_name = ? ORDER BY created_at DESC",
                        (canonical,),
                    ).fetchall()
            return [dict(row) for row in rows]

    def load_investigations_by_validity(
        self, repo_name: str, validity: str | None = None
    ) -> list[dict]:
        """
        Load investigations, optionally filtered by current_validity.
        """
        canonical = get_canonical_repo_id(repo_name)
        with self._connect() as conn:
            if validity is not None:
                rows = conn.execute(
                    "SELECT * FROM investigations WHERE repo_name = ? AND current_validity = ? ORDER BY created_at DESC",
                    (repo_name, validity),
                ).fetchall()
                if not rows and canonical != repo_name:
                    rows = conn.execute(
                        "SELECT * FROM investigations WHERE repo_name = ? AND current_validity = ? ORDER BY created_at DESC",
                        (canonical, validity),
                    ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM investigations WHERE repo_name = ? ORDER BY created_at DESC",
                    (repo_name,),
                ).fetchall()
                if not rows and canonical != repo_name:
                    rows = conn.execute(
                        "SELECT * FROM investigations WHERE repo_name = ? ORDER BY created_at DESC",
                        (canonical,),
                    ).fetchall()
            result = []
            for row in rows:
                r = dict(row)
                r["result"] = json.loads(r["result_json"]) if r.get("result_json") else None
                result.append(r)
            return result

    # ─── History & Identity ──────────────────────────────────────────────────

    def has_engineering_history(self, repo_identity: str) -> bool:
        """
        Check if any engineering history exists for this repository identity
        across repo_profiles, change_records, decisions, or investigations.
        Checks both exact string and canonical path string.
        """
        canonical_id = get_canonical_repo_id(repo_identity)
        identities = [repo_identity]
        if canonical_id != repo_identity:
            identities.append(canonical_id)

        with self._connect() as conn:
            for ident in identities:
                for table in ("repo_profiles", "change_records", "decisions", "investigations"):
                    row = conn.execute(
                        f"SELECT 1 FROM {table} WHERE repo_name = ? LIMIT 1",
                        (ident,),
                    ).fetchone()
                    if row is not None:
                        return True
            # Fallback for legacy profile display names
            if self.load_repo_profile(repo_identity) is not None:
                return True
        return False
