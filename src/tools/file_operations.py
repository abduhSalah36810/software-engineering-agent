import os
from langchain_core.tools import tool


@tool
def read_file(repo_path: str, file_path: str) -> str:
    """Read the content of a file from the repository."""
    path = os.path.join(repo_path, file_path)

    if not os.path.exists(path):
        return f"Error: File '{file_path}' does not exist in repository."

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as file:
            return file.read()
    except Exception as e:
        return f"Error reading file '{file_path}': {e}"


@tool
def edit_file(
    repo_path: str,
    file_path: str,
    old_content: str,
    new_content: str
) -> None:
    """Replace a specific unique piece of content inside a repository file."""
    path = os.path.join(repo_path, file_path)

    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(path, "r", encoding="utf-8", errors="replace") as file:
        content = file.read()

    count = content.count(old_content)

    if count == 0:
        raise ValueError("old_content not found in file")

    if count > 1:
        raise ValueError("old_content appears multiple times in file")

    content = content.replace(old_content, new_content)

    with open(path, "w", encoding="utf-8") as file:
        file.write(content)


@tool
def replace_file(
    repo_path: str,
    file_path: str,
    new_content: str
) -> None:
    """Replace the entire content of a repository file."""
    path = os.path.join(repo_path, file_path)

    parent_dir = os.path.dirname(path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        file.write(new_content)


def create_file():
    pass


def delete_file():
    pass
