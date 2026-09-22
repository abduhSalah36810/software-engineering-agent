import subprocess
import os

from dotenv import load_dotenv

load_dotenv()


def clone_repo(url: str):

    print("Starting to clone the repo....")

    base_path = os.getenv("PATH_TO_CLONED_REPO")

    repo_name = url.rstrip("/").rsplit("/")[-1].removesuffix(".git")

    repo_path = os.path.join(base_path, repo_name)

    # Check if repository already exists
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