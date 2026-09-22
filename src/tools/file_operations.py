import os
from langchain_core.tools import tool


@tool
def read_file(repo_path: str, file_path: str) -> str:
    """Read the content of a file from the repository."""

    path = os.path.join(repo_path, file_path)

    with open(path, "r") as file:
        content = file.read()

    return content


@tool
def edit_file(
    repo_path: str,
    file_path: str,
    old_content: str,
    new_content: str
) -> None:
    """Replace a specific unique piece of content inside a repository file."""

    path = os.path.join(repo_path, file_path)

    with open(path, "r") as file:
        content = file.read()

    count = content.count(old_content)

    if count == 0:
        raise ValueError("old_content not found in file")

    if count > 1:
        raise ValueError("old_content appears multiple times in file")

    content = content.replace(old_content, new_content)

    with open(path, "w") as file:
        file.write(content)


@tool
def replace_file(
    repo_path: str,
    file_path: str,
    new_content: str
) -> None:
    """Replace the entire content of a repository file."""

    path = os.path.join(repo_path, file_path)

    with open(path, "w") as file:
        file.write(new_content)


def create_file():
    pass


def delete_file():
    pass

