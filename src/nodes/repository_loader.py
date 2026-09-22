from src.helpers.file_tree import get_file_tree
from src.helpers.repo import clone_repo
from src.helpers.qdrant.collection import extract_repo_name
from src.state import AgentState


def repository_loader(state: AgentState):
    print("Repository Loader running 📦 ...")

    state["repo_path"] = clone_repo(state["url"])
    state["repo_name"] = extract_repo_name(state["repo_path"])

    print("Before file tree 🌳")
    state["file_tree"] = get_file_tree(state["repo_path"])
    print("After file tree 🌳")

    return state
