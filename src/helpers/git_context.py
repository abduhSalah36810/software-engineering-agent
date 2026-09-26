"""
Git context helper.

Provides lightweight git introspection used by the agent to:
  - Identify the current HEAD commit
  - List files changed since the last known commit
  - Pull recent commit messages (for architecture-change detection)

No heavy git library required -- subprocess + standard git CLI.
"""

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
