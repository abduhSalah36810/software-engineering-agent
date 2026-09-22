"""
repository_discovery node

Runs the deterministic RepoDiscovery engine on the cloned repository,
persists the resulting RepoProfile to the SQLite engineering memory,
and prints a human-readable summary for user review.

No LLM is involved. All findings are evidence-backed.
"""

from src.helpers.repo_discovery import RepoDiscovery
from src.memory.sqlite_store import EngineeringMemoryStore
from src.state import AgentState


def repository_discovery(state: AgentState) -> dict:
    print("Repository Discovery running 🔬 ...")

    repo_path = state.get("repo_path")

    if not repo_path:
        print("Warning: No repo_path in state — skipping discovery.")
        return {}

    # Run deterministic discovery (no LLM)
    discovery = RepoDiscovery(repo_path)
    profile = discovery.discover()

    # Persist to SQLite engineering memory
    memory = EngineeringMemoryStore()
    memory.save_repo_profile(profile)
    print(f"Repository profile saved to engineering memory (repo: {profile.name})")

    # Present to user for review
    print()
    print("=" * 60)
    print("REPOSITORY PROFILE")
    print("=" * 60)
    print(profile.summary())
    print()
    print("Source: deterministic analysis (observed evidence only)")
    print("Corrections will be captured in future phases.")
    print()

    return {"repo_profile": profile.to_dict()}
