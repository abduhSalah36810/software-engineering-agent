"""
Incremental Engineering Intelligence - Foundation Component (Phase 4.1 + 4.2 + 4.3).

Responsible for detecting changes that occurred since the last known
engineering state (HEAD vs previous commit in memory) and separating
committed changes from uncommitted working-tree changes.

Uses canonical absolute path as primary repository identity (repo_id),
reserving repo_name for display/logging.

Distinguishes:
  - is_initial_baseline: True ONLY when no engineering history exists
  - is_baseline_stale: True when history exists, but previous commit cannot be reached
  - requires_reverification: explicit signal that broader re-understanding is needed
  - has_committed_changes: changes between stored valid baseline and HEAD
  - has_uncommitted_changes: working tree differs from HEAD (modified, untracked, deleted)
  - uncommitted_files: working tree delta paths
  - is_dirty: working tree state

Deterministic. Zero LLM. Zero external services.
"""

from dataclasses import dataclass, field, asdict
import json
import os
from pathlib import Path
import subprocess

from src.helpers.git_context import (
    get_git_context,
    get_git_diff_status,
    get_git_working_tree_status,
)
from src.memory.sqlite_store import EngineeringMemoryStore
from src.helpers.affected_dimensions import (
    AffectedDimension,
    AffectedDimensionsResult,
    AffectedDimensionClassifier,
    detect_affected_dimensions,
)


def _is_commit_reachable(repo_path: str, commit_hash: str) -> bool:
    """
    Deterministically checks if commit_hash exists and is reachable
    in the git repository using git cat-file and git merge-base.
    """
    try:
        # Check object existence and type
        res = subprocess.run(
            ["git", "cat-file", "-t", commit_hash],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode != 0 or res.stdout.strip() != "commit":
            return False

        # Verify reachability from current HEAD
        res_merge = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit_hash, "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return res_merge.returncode == 0
    except Exception:
        return False


@dataclass
class IncrementalChangeResult:
    """Structured representation of repository change delta and working tree status."""
    repo_id: str = "unknown"
    repo_name: str = "unknown"
    previous_commit: str | None = None
    current_commit: str | None = None
    changed_files: list[str] = field(default_factory=list)
    added_files: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    has_changes: bool = False
    has_committed_changes: bool = False
    has_uncommitted_changes: bool = False
    uncommitted_files: list[str] = field(default_factory=list)
    is_dirty: bool = False
    is_git_repo: bool = False
    is_initial_baseline: bool = False
    is_baseline_stale: bool = False
    requires_reverification: bool = False
    status: str = "ok"

    def detect_affected_dimensions(self) -> AffectedDimensionsResult:
        """Analyze which engineering dimensions are touched by these changes."""
        return detect_affected_dimensions(self)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "IncrementalChangeResult":
        data = data.copy()
        data["repo_id"] = str(data.get("repo_id", "unknown"))
        data["repo_name"] = str(data.get("repo_name", "unknown"))
        data["previous_commit"] = data.get("previous_commit")
        data["current_commit"] = data.get("current_commit")
        data["changed_files"] = list(data.get("changed_files", []))
        data["added_files"] = list(data.get("added_files", []))
        data["modified_files"] = list(data.get("modified_files", []))
        data["deleted_files"] = list(data.get("deleted_files", []))
        data["has_changes"] = bool(data.get("has_changes", False))
        data["has_committed_changes"] = bool(data.get("has_committed_changes", False))
        data["has_uncommitted_changes"] = bool(data.get("has_uncommitted_changes", False))
        data["uncommitted_files"] = list(data.get("uncommitted_files", []))
        data["is_dirty"] = bool(data.get("is_dirty", False))
        data["is_git_repo"] = bool(data.get("is_git_repo", False))
        data["is_initial_baseline"] = bool(data.get("is_initial_baseline", False))
        data["is_baseline_stale"] = bool(data.get("is_baseline_stale", False))
        data["requires_reverification"] = bool(data.get("requires_reverification", False))
        data["status"] = str(data.get("status", "ok"))
        return cls(**data)


class IncrementalChangeDetector:
    """
    Detects repository changes between the last known engineering state
    and current working repository HEAD, separating committed evolution
    from uncommitted working-tree modifications.
    """

    def __init__(
        self,
        repo_path: str | None,
        repo_name: str | None = None,
        repo_id: str | None = None,
        memory: EngineeringMemoryStore | None = None,
    ):
        self.repo_path = repo_path
        self.memory = memory
        # Canonical repository identity: canonical absolute path string
        if repo_id:
            self.repo_id = repo_id
        elif repo_path and os.path.exists(repo_path):
            self.repo_id = str(Path(repo_path).resolve().absolute())
        elif repo_path:
            self.repo_id = str(Path(repo_path).absolute())
        else:
            self.repo_id = "unknown"

        self.repo_name = repo_name or (Path(repo_path).name if repo_path else "unknown")

    def detect_changes(self, since_commit: str | None = None) -> IncrementalChangeResult:
        """
        Calculates change delta separating committed history from working tree.
        """
        # 1. Validate repository path
        if not self.repo_path or not os.path.exists(self.repo_path):
            return IncrementalChangeResult(
                repo_id=self.repo_id,
                repo_name=self.repo_name,
                previous_commit=None,
                current_commit=None,
                changed_files=[],
                added_files=[],
                modified_files=[],
                deleted_files=[],
                has_changes=False,
                has_committed_changes=False,
                has_uncommitted_changes=False,
                uncommitted_files=[],
                is_dirty=False,
                is_git_repo=False,
                is_initial_baseline=False,
                is_baseline_stale=False,
                requires_reverification=False,
                status="path_not_found",
            )

        # 2. Check if git repository
        git_ctx = get_git_context(self.repo_path)
        if not git_ctx.is_git_repo:
            return IncrementalChangeResult(
                repo_id=self.repo_id,
                repo_name=self.repo_name,
                previous_commit=None,
                current_commit=None,
                changed_files=[],
                added_files=[],
                modified_files=[],
                deleted_files=[],
                has_changes=False,
                has_committed_changes=False,
                has_uncommitted_changes=False,
                uncommitted_files=[],
                is_dirty=False,
                is_git_repo=False,
                is_initial_baseline=False,
                is_baseline_stale=False,
                requires_reverification=False,
                status="non_git",
            )

        # 3. Check uncommitted working tree changes
        is_dirty, uncommitted_files = get_git_working_tree_status(self.repo_path)
        has_uncommitted = len(uncommitted_files) > 0

        # 4. Check for unborn HEAD / no commits
        if not git_ctx.head_commit:
            return IncrementalChangeResult(
                repo_id=self.repo_id,
                repo_name=self.repo_name,
                previous_commit=None,
                current_commit=None,
                changed_files=[],
                added_files=[],
                modified_files=[],
                deleted_files=[],
                has_changes=has_uncommitted,
                has_committed_changes=False,
                has_uncommitted_changes=has_uncommitted,
                uncommitted_files=uncommitted_files,
                is_dirty=is_dirty,
                is_git_repo=True,
                is_initial_baseline=True,
                is_baseline_stale=False,
                requires_reverification=False,
                status="unborn_head",
            )

        current_head = git_ctx.head_commit

        # 5. Determine engineering history and previous commit from memory
        history_exists = False
        stored_commit = None

        if self.memory:
            try:
                # Primary identity lookup MUST use canonical repository identity (repo_id)
                history_exists = self.memory.has_engineering_history(self.repo_id)
                records = self.memory.load_change_records(self.repo_id, limit=1)
                if records:
                    stored_commit = records[0]["commit_hash"]
            except Exception:
                pass

        # Priority: explicit since_commit > stored commit in memory
        previous_commit = since_commit if since_commit is not None else stored_commit

        # 6. Case A: No previous commit available
        if previous_commit is None:
            if history_exists:
                # Engineering history exists (profile, decisions, investigations), but no verified commit anchor
                return IncrementalChangeResult(
                    repo_id=self.repo_id,
                    repo_name=self.repo_name,
                    previous_commit=None,
                    current_commit=current_head,
                    changed_files=[],
                    added_files=[],
                    modified_files=[],
                    deleted_files=[],
                    has_changes=has_uncommitted,
                    has_committed_changes=False,
                    has_uncommitted_changes=has_uncommitted,
                    uncommitted_files=uncommitted_files,
                    is_dirty=is_dirty,
                    is_git_repo=True,
                    is_initial_baseline=False,
                    is_baseline_stale=True,
                    requires_reverification=True,
                    status="stale_baseline",
                )
            else:
                # Truly brand-new repository with no engineering history
                return IncrementalChangeResult(
                    repo_id=self.repo_id,
                    repo_name=self.repo_name,
                    previous_commit=None,
                    current_commit=current_head,
                    changed_files=[],
                    added_files=[],
                    modified_files=[],
                    deleted_files=[],
                    has_changes=has_uncommitted,
                    has_committed_changes=False,
                    has_uncommitted_changes=has_uncommitted,
                    uncommitted_files=uncommitted_files,
                    is_dirty=is_dirty,
                    is_git_repo=True,
                    is_initial_baseline=True,
                    is_baseline_stale=False,
                    requires_reverification=False,
                    status="initial_baseline",
                )

        # 7. Case B: Previous commit anchor exists - verify reachability in Git
        reachable = _is_commit_reachable(self.repo_path, previous_commit)
        if not reachable:
            # Previous commit cannot be verified or reached from current repository history
            return IncrementalChangeResult(
                repo_id=self.repo_id,
                repo_name=self.repo_name,
                previous_commit=previous_commit,
                current_commit=current_head,
                changed_files=[],
                added_files=[],
                modified_files=[],
                deleted_files=[],
                has_changes=has_uncommitted,
                has_committed_changes=False,
                has_uncommitted_changes=has_uncommitted,
                uncommitted_files=uncommitted_files,
                is_dirty=is_dirty,
                is_git_repo=True,
                is_initial_baseline=False,
                is_baseline_stale=True,
                requires_reverification=True,
                status="stale_baseline",
            )

        # 8. Case C: Unchanged committed repository evolution (previous_commit == current_head)
        if previous_commit == current_head:
            return IncrementalChangeResult(
                repo_id=self.repo_id,
                repo_name=self.repo_name,
                previous_commit=previous_commit,
                current_commit=current_head,
                changed_files=[],
                added_files=[],
                modified_files=[],
                deleted_files=[],
                has_changes=has_uncommitted,
                has_committed_changes=False,
                has_uncommitted_changes=has_uncommitted,
                uncommitted_files=uncommitted_files,
                is_dirty=is_dirty,
                is_git_repo=True,
                is_initial_baseline=False,
                is_baseline_stale=False,
                requires_reverification=False,
                status="dirty" if is_dirty else "unchanged",
            )

        # 9. Case D: Compare valid committed evolution: previous_commit -> current_head
        diff_data = get_git_diff_status(self.repo_path, previous_commit, current_head)

        if diff_data is None:
            # Diff failed or unresolvable despite reachability check
            return IncrementalChangeResult(
                repo_id=self.repo_id,
                repo_name=self.repo_name,
                previous_commit=previous_commit,
                current_commit=current_head,
                changed_files=[],
                added_files=[],
                modified_files=[],
                deleted_files=[],
                has_changes=has_uncommitted,
                has_committed_changes=False,
                has_uncommitted_changes=has_uncommitted,
                uncommitted_files=uncommitted_files,
                is_dirty=is_dirty,
                is_git_repo=True,
                is_initial_baseline=False,
                is_baseline_stale=True,
                requires_reverification=True,
                status="stale_baseline",
            )

        added = diff_data["added"]
        modified = diff_data["modified"]
        deleted = diff_data["deleted"]
        changed = diff_data["changed"]
        has_committed = len(changed) > 0
        overall_has_changes = has_committed or has_uncommitted

        return IncrementalChangeResult(
            repo_id=self.repo_id,
            repo_name=self.repo_name,
            previous_commit=previous_commit,
            current_commit=current_head,
            changed_files=changed,
            added_files=added,
            modified_files=modified,
            deleted_files=deleted,
            has_changes=overall_has_changes,
            has_committed_changes=has_committed,
            has_uncommitted_changes=has_uncommitted,
            uncommitted_files=uncommitted_files,
            is_dirty=is_dirty,
            is_git_repo=True,
            is_initial_baseline=False,
            is_baseline_stale=False,
            requires_reverification=False,
            status="changed" if has_committed else ("dirty" if is_dirty else "unchanged"),
        )

    def detect_affected_dimensions(self, since_commit: str | None = None) -> AffectedDimensionsResult:
        """
        Runs change detection and returns the affected engineering dimensions.
        """
        change_result = self.detect_changes(since_commit=since_commit)
        return detect_affected_dimensions(change_result, repo_path=self.repo_path)
