"""
investigator node

Combines:
  - Semantic code search (Qdrant + FastEmbed)
  - Repository profile (from SQLite engineering memory)
  - Git context (HEAD, recent changes)
  - Past investigations (from SQLite)

Produces a structured InvestigationResult stored in state["investigation"].
Does NOT call the LLM -- that is the coder's job.
The investigator prepares a rich, evidence-backed context package.
"""

from pathlib import Path
from src.helpers.embedding.client import EmbeddingClient
from src.helpers.qdrant.store import QdrantStore
from src.helpers.git_context import get_git_context
from src.helpers.repo import get_canonical_repo_id
from src.memory.sqlite_store import EngineeringMemoryStore
from src.models.repo_profile import RepoProfile
from src.state import AgentState


def investigator(state: AgentState) -> dict:
    print("Investigator running...")

    repo_path = state.get("repo_path", "")
    repo_id = state.get("repo_id") or (get_canonical_repo_id(repo_path) if repo_path else "unknown")
    repo_name = state.get("repo_name") or (Path(repo_path).name if repo_path else "unknown")
    problem = state["problem"]
    repo_profile_dict = state.get("repo_profile")

    # ── 1. Semantic search (uses display name for Qdrant collection) ───────
    client = EmbeddingClient()
    store = QdrantStore(repo_name)

    embedding = client.embed([problem])[0]
    results = store.search(embedding=embedding, limit=8)

    retrieved_chunks = [r.payload for r in results]
    print(f"Retrieved {len(retrieved_chunks)} code chunks from Qdrant")

    for chunk in retrieved_chunks[:3]:
        print(f"  -> {chunk.get('file')} [{chunk.get('symbol')}]")

    # ── 2. Engineering memory context (uses canonical repo_id) ────────────
    memory = EngineeringMemoryStore()

    past_investigations = memory.load_investigations(repo_id, limit=5)
    if not past_investigations and repo_name and repo_name != repo_id:
        past_investigations = memory.load_investigations(repo_name, limit=5)

    decisions = memory.load_decisions(repo_id)
    if not decisions and repo_name and repo_name != repo_id:
        decisions = memory.load_decisions(repo_name)

    recent_changes = memory.load_change_records(repo_id, limit=10)
    if not recent_changes and repo_name and repo_name != repo_id:
        recent_changes = memory.load_change_records(repo_name, limit=10)

    print(f"Memory: {len(past_investigations)} past investigations, "
          f"{len(decisions)} decisions, {len(recent_changes)} change records")

    # ── 3. Git context ───────────────────────────────────────────────────
    last_known_commit = None
    if recent_changes:
        last_known_commit = recent_changes[0].get("commit_hash")

    git_ctx = get_git_context(repo_path, since_commit=last_known_commit)

    if git_ctx.is_git_repo:
        print(f"Git: HEAD={git_ctx.head_commit[:8] if git_ctx.head_commit else 'N/A'} "
              f"branch={git_ctx.branch}")
        if git_ctx.changed_files_since:
            print(f"  Changed since last analysis: {len(git_ctx.changed_files_since)} files")
    else:
        print("Git: not a git repo or no git history")

    # ── 4. Build profile summary ──────────────────────────────────────────
    profile_summary = ""
    if repo_profile_dict:
        try:
            profile = RepoProfile.from_dict(repo_profile_dict)
            profile_summary = profile.summary()
        except Exception as e:
            profile_summary = f"[Profile parse error: {e}]"

    # ── 5. Build structured investigation context ──────────────────────────
    investigation = {
        "problem": problem,
        "retrieved_chunks": retrieved_chunks,
        "repo_profile_summary": profile_summary,
        "past_investigations": past_investigations,
        "decisions": decisions,
        "git": {
            "is_git_repo": git_ctx.is_git_repo,
            "head_commit": git_ctx.head_commit,
            "branch": git_ctx.branch,
            "recent_commits": git_ctx.recent_commits,
            "changed_files_since_last_analysis": git_ctx.changed_files_since,
        },
        "recent_changes": recent_changes,
    }

    print("Investigation context assembled")

    return {
        "retrieved_chunks": retrieved_chunks,
        "investigation": investigation,
    }
