"""
repository_discovery node

Runs the deterministic RepoDiscovery engine on the cloned repository,
persists the resulting RepoProfile to the SQLite engineering memory under
the canonical repo_id identity, records the current git HEAD commit for
incremental future analysis, and prints a human-readable summary for user review.

No LLM is involved. All findings are evidence-backed.
"""

from src.helpers.repo_discovery import RepoDiscovery
from src.helpers.git_context import get_git_context
from src.helpers.repo import get_canonical_repo_id
from src.memory.sqlite_store import EngineeringMemoryStore
from src.state import AgentState


def repository_discovery(state: AgentState) -> dict:
    print("Repository Discovery running...")

    repo_path = state.get("repo_path")

    if not repo_path:
        print("Warning: No repo_path in state -- skipping discovery.")
        return {}

    repo_id = state.get("repo_id") or get_canonical_repo_id(repo_path)
    memory = EngineeringMemoryStore()
    repo_name_hint = state.get("repo_name", "")

    # ── Check if we already have a profile and git hasn't moved much ──────
    has_existing = memory.repo_profile_exists(repo_id) or (repo_name_hint and memory.repo_profile_exists(repo_name_hint))
    if has_existing:
        existing = memory.load_repo_profile(repo_id) or memory.load_repo_profile(repo_name_hint)
        lookup_label = repo_id if memory.repo_profile_exists(repo_id) else repo_name_hint
        print(f"Existing profile found for '{lookup_label}' -- checking git state...")

        git_ctx = get_git_context(repo_path)
        change_records = memory.load_change_records(repo_id, limit=1)
        if not change_records and repo_name_hint:
            change_records = memory.load_change_records(repo_name_hint, limit=1)

        last_known = change_records[0]["commit_hash"] if change_records else None

        if not git_ctx.is_git_repo:
            print("Non-git repository -- running fresh discovery")
        elif git_ctx.head_commit and git_ctx.head_commit == last_known:
            print("Git HEAD unchanged -- reusing cached profile")
            print()
            print("=" * 60)
            print("REPOSITORY PROFILE (cached)")
            print("=" * 60)
            from src.models.repo_profile import RepoProfile
            try:
                profile = RepoProfile.from_dict(existing)
                print(profile.summary())
            except Exception:
                print(existing)
            print()
            return {"repo_profile": existing, "repo_id": repo_id}
        else:
            print(f"Git HEAD changed ({last_known} -> {git_ctx.head_commit}) -- re-running discovery")

    # ── Run deterministic discovery ─────────────────────────────────────
    discovery = RepoDiscovery(repo_path)
    profile = discovery.discover()

    # Persist profile under canonical repository identity
    memory.save_repo_profile(profile, repo_id=repo_id)
    print(f"Repository profile saved (repo: {profile.name}, id: {repo_id})")

    # Record current git HEAD as a change record for future incremental checks
    git_ctx = get_git_context(repo_path)
    if git_ctx.is_git_repo and git_ctx.head_commit:
        try:
            memory.save_change_record(
                repo_name=repo_id,
                commit_hash=git_ctx.head_commit,
                changed_files=[],
                review=f"Initial discovery at branch={git_ctx.branch}",
            )
        except Exception as e:
            print(f"  Note: Could not record git state: {e}")

    # Present to user
    print()
    print("=" * 60)
    print("REPOSITORY PROFILE")
    print("=" * 60)
    print(profile.summary())
    print()
    print("Source: deterministic analysis (observed evidence only)")
    print()

    return {"repo_profile": profile.to_dict(), "repo_id": repo_id}
