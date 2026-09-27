"""
Git context helper.

Provides lightweight git introspection used by the agent to:
  - Identify the current HEAD commit
  - List files changed since the last known commit
  - Pull recent commit messages (for architecture-change detection)
  - Inspect structured change diffs (added, modified, deleted)
  - Inspect uncommitted working tree changes (modified, untracked, deleted)

No heavy git library required -- subprocess + standard git CLI.
"""

import os
import subprocess
from dataclasses import dataclass, field


@dataclass
class GitContext:
    repo_path: str
    head_commit: str | None = None
    branch: str | None = None
    recent_commits: list[dict] = field(default_factory=list)
    changed_files_since: list[str] = field(default_factory=list)
    is_git_repo: bool = False


def _run(cmd: list[str], cwd: str) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=15)
        return r.returncode, r.stdout.strip()
    except Exception as e:
        return 1, str(e)


def get_git_context(repo_path: str, since_commit: str | None = None) -> GitContext:
    """
    Gather git state for repo_path.

    If since_commit is provided, also lists files changed since that commit
    (used for incremental re-analysis).
    """
    ctx = GitContext(repo_path=repo_path)

    if not repo_path or not os.path.exists(repo_path):
        return ctx

    # Check if it's a git repo
    rc, _ = _run(["git", "rev-parse", "--git-dir"], repo_path)
    if rc != 0:
        return ctx

    ctx.is_git_repo = True

    # HEAD commit hash
    rc, out = _run(["git", "rev-parse", "HEAD"], repo_path)
    if rc == 0:
        ctx.head_commit = out

    # Current branch
    rc, out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    if rc == 0:
        ctx.branch = out

    # Recent commits (last 10, one-liners)
    rc, out = _run(
        ["git", "log", "--oneline", "-10", "--no-decorate"],
        repo_path,
    )
    if rc == 0 and out:
        for line in out.splitlines():
            parts = line.split(" ", 1)
            if len(parts) == 2:
                ctx.recent_commits.append({"hash": parts[0], "message": parts[1]})

    # Files changed since a known commit
    if since_commit and ctx.head_commit and since_commit != ctx.head_commit:
        rc, out = _run(
            ["git", "diff", "--name-only", since_commit, "HEAD"],
            repo_path,
        )
        if rc == 0 and out:
            ctx.changed_files_since = [f for f in out.splitlines() if f]

    return ctx


def get_git_diff_status(
    repo_path: str,
    from_commit: str,
    to_commit: str,
) -> dict[str, list[str]] | None:
    """
    Categorizes file changes between two commits into added, modified, deleted.
    Returns a dict with 'added', 'modified', 'deleted', 'changed' lists,
    or None if from_commit or to_commit are invalid or the diff command fails.
    """
    if not repo_path or not os.path.exists(repo_path):
        return None

    # Check if it's a git repo
    rc, _ = _run(["git", "rev-parse", "--git-dir"], repo_path)
    if rc != 0:
        return None

    # Verify from_commit exists in this repo
    rc1, _ = _run(["git", "cat-file", "-e", f"{from_commit}^{{commit}}"], repo_path)
    if rc1 != 0:
        return None

    # Verify to_commit exists in this repo
    rc2, _ = _run(["git", "cat-file", "-e", f"{to_commit}^{{commit}}"], repo_path)
    if rc2 != 0:
        return None

    if from_commit == to_commit:
        return {
            "added": [],
            "modified": [],
            "deleted": [],
            "changed": [],
        }

    rc, out = _run(
        ["git", "diff", "--name-status", from_commit, to_commit],
        repo_path,
    )
    if rc != 0:
        return None

    added = []
    modified = []
    deleted = []
    changed = []

    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        status_code = parts[0].strip()
        if len(parts) < 2:
            continue
        if status_code.startswith("A"):
            added.append(parts[1])
            changed.append(parts[1])
        elif status_code.startswith("M"):
            modified.append(parts[1])
            changed.append(parts[1])
        elif status_code.startswith("D"):
            deleted.append(parts[1])
            changed.append(parts[1])
        elif status_code.startswith("R"):
            # Rename: parts[1] is old path, parts[2] is new path
            deleted.append(parts[1])
            if len(parts) > 2:
                added.append(parts[2])
                changed.extend([parts[1], parts[2]])
            else:
                changed.append(parts[1])
        else:
            # Fallback for type changes (T) or copy (C)
            modified.append(parts[1])
            changed.append(parts[1])

    return {
        "added": sorted(set(added)),
        "modified": sorted(set(modified)),
        "deleted": sorted(set(deleted)),
        "changed": sorted(set(changed)),
    }


def get_git_working_tree_status(repo_path: str) -> tuple[bool, list[str]]:
    """
    Checks for uncommitted working tree changes using 'git status --porcelain'.
    Returns (is_dirty, uncommitted_files) covering modified, untracked, deleted,
    and staged changes.
    """
    if not repo_path or not os.path.exists(repo_path):
        return False, []

    rc, _ = _run(["git", "rev-parse", "--git-dir"], repo_path)
    if rc != 0:
        return False, []

    rc, out = _run(["git", "status", "--porcelain"], repo_path)
    if rc != 0 or not out:
        return False, []

    uncommitted = []
    for line in out.splitlines():
        line = line.strip()
        if not line or len(line) < 3:
            continue
        # Format is XY <path> or XY <old> -> <new>
        path_part = line[2:].strip()
        if path_part.startswith('"') and path_part.endswith('"'):
            path_part = path_part[1:-1]
        if " -> " in path_part:
            parts = path_part.split(" -> ")
            for p in parts:
                clean_p = p.strip().strip('"')
                if clean_p:
                    uncommitted.append(clean_p)
        else:
            if path_part:
                uncommitted.append(path_part)

    uncommitted_sorted = sorted(set(uncommitted))
    return len(uncommitted_sorted) > 0, uncommitted_sorted
