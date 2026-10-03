import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def get_canonical_repo_id(repo_path: str | Path | None) -> str:
    """
    Returns the canonical repository identity as a resolved, stable absolute path string.

    Examples:
        "."                                     -> "/home/abdurrahman/software-engineering-agent"
        "/path/to/repo/../repo"                 -> "/path/to/repo"
        Path("/path/to/repo")                   -> "/path/to/repo"
    """
    if not repo_path:
        return "unknown"
    return str(Path(repo_path).resolve())


def clone_repo(url: str) -> str:
    # If a local directory path is provided, reuse it directly
    if os.path.isdir(url):
        print(f"Using local repository directory: {url} ✅")
        return os.path.abspath(url)

    print("Starting to clone the repo....")

    base_path = os.getenv("PATH_TO_CLONED_REPO") or "./repos"
    os.makedirs(base_path, exist_ok=True)

    clean_url = url.rstrip("/\\")
    repo_name = clean_url.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].removesuffix(".git")
    if not repo_name:
        repo_name = "repo"

    repo_path = os.path.join(base_path, repo_name)

    # Check if repository already exists in clone path
    if os.path.exists(repo_path):
        print("Repository already exists ✅")
        return repo_path

    result = subprocess.run(
        ["git", "clone", url, repo_path],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print("Cloned successfully ✅✅")
    else:
        print("Clone failed ❌❌")
        print(result.stderr)

    return repo_path
