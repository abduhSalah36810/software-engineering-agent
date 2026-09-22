from pathlib import Path


class LanguageDetector:

    EXTENSIONS = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".java": "java",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".h": "cpp",
        ".hpp": "cpp",
        ".cs": "csharp",
        ".go": "go",
        ".rs": "rust",
        ".php": "php",
    }

    def detect(self, file_path: str) -> str | None:
        extension = Path(file_path).suffix.lower()
        return self.EXTENSIONS.get(extension)