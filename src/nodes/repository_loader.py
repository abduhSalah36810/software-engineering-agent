"""
repository_loader node

Clones the target repository (or reuses the local clone if already present).
Builds a compact file tree for LLM context.
Returns state updates as a dict including canonical repo_id.
"""

from src.helpers.file_tree import get_file_tree
from src.helpers.repo import clone_repo, get_canonical_repo_id
from src.helpers.qdrant.collection import extract_repo_name
from src.state import AgentState


def repository_loader(state: AgentState) -> dict:
    print("Repository Loader running...")

    repo_path = clone_repo(state["url"])
    repo_name = extract_repo_name(repo_path)
    repo_id = get_canonical_repo_id(repo_path)

    print("Building file tree...")
    file_tree = get_file_tree(repo_path)
    print("File tree ready")

    return {
        "repo_path": repo_path,
        "repo_name": repo_name,
        "repo_id": repo_id,
        "file_tree": file_tree,
    }
