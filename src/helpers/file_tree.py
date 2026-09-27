import os

IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "obj",
    "bin",
    ".dart_tool",
    ".idea",
    ".vscode",
}


def get_file_tree(repo_path: str) -> str:
    if not repo_path or not os.path.exists(repo_path):
        return ""

    file_tree = ""

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRECTORIES]
        dirs.sort()
        files.sort()

        relative_path = os.path.relpath(root, repo_path)
        depth = 0 if relative_path == "." else relative_path.count(os.sep) + 1
        indent = "  " * depth
        file_tree += root + chr(10)
        for directory in dirs:
            file_tree += indent + "|__" + directory + chr(10)
        for file in files:
            file_tree += indent + "|__" + file + chr(10)

    return file_tree
