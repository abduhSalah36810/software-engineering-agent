import os
import subprocess
from dotenv import load_dotenv

load_dotenv()


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
