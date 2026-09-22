import os


class FileScanner:

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

    IGNORED_FILES = {
        "generated_plugin_registrant.cc",
        "generated_plugin_registrant.h",
    }

    def scan(self, repo_path: str) -> list[str]:

        files = []

        for root, dirs, filenames in os.walk(repo_path):

            dirs[:] = [
                directory
                for directory in dirs
                if directory not in self.IGNORED_DIRECTORIES
            ]

            for filename in filenames:

                if filename in self.IGNORED_FILES:
                    continue

                files.append(os.path.relpath(os.path.join(root, filename) , repo_path))

        return files