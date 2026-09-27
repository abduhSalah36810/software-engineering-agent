"""
repository_discovery node

Runs the deterministic RepoDiscovery engine on the cloned repository,
persists the resulting RepoProfile to the SQLite engineering memory,
records the current git HEAD commit for incremental future analysis,
and prints a human-readable summary for user review.

No LLM is involved. All findings are evidence-backed.
"""

from src.helpers.repo_discovery import RepoDiscovery
from src.helpers.git_context import get_git_context
from src.memory.sqlite_store import EngineeringMemoryStore
from src.state import AgentState


def repository_discovery(state: AgentState) -> dict:
    print("Repository Discovery running...")

    repo_path = state.get("repo_path")

    if not repo_path:
        print("Warning: No repo_path in state -- skipping discovery.")
        return {}

    memory = EngineeringMemoryStore()
    repo_name_hint = state.get("repo_name", "")

    # ── Check if we already have a profile and git hasn't moved much ──────
    if repo_name_hint and memory.repo_profile_exists(repo_name_hint):
        existing = memory.load_repo_profile(repo_name_hint)
        print(f"Existing profile found for '{repo_name_hint}' -- checking git state...")

        git_ctx = get_git_context(repo_path)
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
            return {"repo_profile": existing}
        else:
            print(f"Git HEAD changed ({last_known} -> {git_ctx.head_commit}) -- re-running discovery")

    # ── Run deterministic discovery ─────────────────────────────────────
    discovery = RepoDiscovery(repo_path)
    profile = discovery.discover()

    # Persist profile
    memory.save_repo_profile(profile)
    print(f"Repository profile saved (repo: {profile.name})")

    # Record current git HEAD as a change record for future incremental checks
    git_ctx = get_git_context(repo_path)
    if git_ctx.is_git_repo and git_ctx.head_commit:
        try:
            memory.save_change_record(
                repo_name=profile.name,
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

    return {"repo_profile": profile.to_dict()}
