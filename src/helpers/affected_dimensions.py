"""
Phase 4.3 — Affected Engineering Dimensions.

Deterministic component that analyzes repository change evidence (committed
diff and uncommitted working-tree changes) and identifies which engineering
dimensions have direct evidence of being touched.

Answers:
  "Which engineering dimensions have DIRECT EVIDENCE of being touched
   by those changes?"

Supported Dimensions:
  - source_code
  - tests
  - dependencies
  - deployment
  - ci_cd
  - documentation
  - configuration
  - repository_structure
  - architecture (strictly conservative: new service/module boundaries only)

Deterministic only. Zero LLM. Zero embeddings. Zero external services.
"""

from dataclasses import dataclass, field, asdict
import json
import os
from pathlib import Path
import re
from typing import Literal

# Canonical dimension vocabulary
SUPPORTED_DIMENSIONS = [
    "architecture",
    "ci_cd",
    "configuration",
    "dependencies",
    "deployment",
    "documentation",
    "repository_structure",
    "source_code",
    "tests",
]

# Manifest and lockfile basenames for dependencies
DEPENDENCY_FILENAMES = {
    "requirements.txt",
    "pyproject.toml",
    "poetry.lock",
    "pipfile",
    "pipfile.lock",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lockb",
    "cargo.toml",
    "cargo.lock",
    "go.mod",
    "go.sum",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "gemfile",
    "gemfile.lock",
    "setup.py",
    "setup.cfg",
    "pubspec.yaml",
    "pubspec.lock",
    "composer.json",
    "composer.lock",
    "packages.config",
}

DEPENDENCY_EXTENSIONS = (
    ".csproj",
    ".fsproj",
    ".sln",
)

# Documentation filenames and extensions
DOC_BASENAMES = {
    "authors",
    "changelog",
    "changes",
    "code_of_conduct",
    "contributing",
    "license",
    "notice",
    "roadmap",
    "security",
}

DOC_EXTENSIONS = (
    ".md",
    ".rst",
    ".adoc",
    ".asciidoc",
    ".markdown",
)

# CI/CD specific filenames
CI_CD_FILENAMES = {
    ".gitlab-ci.yml",
    ".travis.yml",
    ".drone.yml",
    "azure-pipelines.yml",
    "bitbucket-pipelines.yml",
}

# Deployment specific filenames
DEPLOYMENT_FILENAMES = {
    ".dockerignore",
    "procfile",
    "fly.toml",
    "railway.toml",
    "render.yaml",
    "vercel.json",
    "netlify.toml",
}

# Configuration specific filenames
CONFIG_FILENAMES = {
    "tsconfig.json",
    "jsconfig.json",
    "pytest.ini",
    "setup.cfg",
    ".coveragerc",
    ".editorconfig",
}

# Source code extensions
SOURCE_CODE_EXTENSIONS = {
    ".py",
    ".pyi",
    ".js",
    ".mjs",
    ".cjs",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".cc",
    ".cxx",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".kts",
    ".scala",
    ".dart",
    ".lua",
    ".sh",
    ".bash",
}

# Structural workspace files
WORKSPACE_STRUCTURE_FILES = {
    ".gitmodules",
    "pnpm-workspace.yaml",
    "lerna.json",
    "nx.json",
    "workspace.json",
    "turbo.json",
}


@dataclass
class AffectedDimension:
    """Represents a single engineering dimension touched by repository changes."""
    dimension: str
    evidence_files: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "AffectedDimension":
        return cls(
            dimension=str(data["dimension"]),
            evidence_files=sorted(list(data.get("evidence_files", []))),
            reasons=sorted(list(data.get("reasons", []))),
        )


@dataclass
class AffectedDimensionsResult:
    """
    Structured outcome of affected engineering dimension analysis.
    Explicitly separates committed changes from uncommitted working-tree changes.
    """
    committed: list[AffectedDimension] = field(default_factory=list)
    uncommitted: list[AffectedDimension] = field(default_factory=list)
    unknown_files: list[str] = field(default_factory=list)
    committed_unknown_files: list[str] = field(default_factory=list)
    uncommitted_unknown_files: list[str] = field(default_factory=list)

    @property
    def committed_affected_dimensions(self) -> list[str]:
        """List of distinct committed dimension names."""
        return sorted([d.dimension for d in self.committed])

    @property
    def uncommitted_affected_dimensions(self) -> list[str]:
        """List of distinct uncommitted dimension names."""
        return sorted([d.dimension for d in self.uncommitted])

    @property
    def all_affected_dimensions(self) -> list[str]:
        """List of distinct dimension names across committed and uncommitted."""
        return sorted(set(self.committed_affected_dimensions + self.uncommitted_affected_dimensions))

    def get_committed_dimension(self, dimension: str) -> AffectedDimension | None:
        for d in self.committed:
            if d.dimension == dimension:
                return d
        return None

    def get_uncommitted_dimension(self, dimension: str) -> AffectedDimension | None:
        for d in self.uncommitted:
            if d.dimension == dimension:
                return d
        return None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "AffectedDimensionsResult":
        committed = [
            d if isinstance(d, AffectedDimension) else AffectedDimension.from_dict(d)
            for d in data.get("committed", [])
        ]
        uncommitted = [
            d if isinstance(d, AffectedDimension) else AffectedDimension.from_dict(d)
            for d in data.get("uncommitted", [])
        ]
        return cls(
            committed=committed,
            uncommitted=uncommitted,
            unknown_files=sorted(list(data.get("unknown_files", []))),
            committed_unknown_files=sorted(list(data.get("committed_unknown_files", []))),
            uncommitted_unknown_files=sorted(list(data.get("uncommitted_unknown_files", []))),
        )


class AffectedDimensionClassifier:
    """
    Deterministic path-based classifier mapping file changes to
    affected engineering dimensions.
    """

    def __init__(self, repo_path: str | None = None):
        self.repo_path = repo_path

    @staticmethod
    def normalize_path(path: str) -> str:
        """Normalize file path separators and strip leading dots or slashes."""
        p = path.replace("\\", "/").strip()
        while p.startswith("./"):
            p = p[2:]
        return p.lstrip("/")

    def classify_path(
        self,
        path: str,
        action: str = "changed",
    ) -> list[tuple[str, str]]:
        """
        Classifies a single file path into zero, one, or more (dimension, reason) pairs.
        Returns an empty list if the file is unknown/unrecognized.
        """
        norm_path = self.normalize_path(path)
        if not norm_path:
            return []

        lower_path = norm_path.lower()
        parts = norm_path.split("/")
        lower_parts = [p.lower() for p in parts]
        filename = parts[-1]
        lower_filename = filename.lower()
        root_name = os.path.splitext(lower_filename)[0]

        matches: list[tuple[str, str]] = []

        # ── 1. DEPENDENCIES ───────────────────────────────────────────────────
        is_dep = False
        if lower_filename in DEPENDENCY_FILENAMES:
            is_dep = True
        elif lower_filename.endswith(DEPENDENCY_EXTENSIONS):
            is_dep = True
        elif re.match(r"^requirements(-.*)?\.(txt|in)$", lower_filename) or lower_filename.endswith(".requirements.txt"):
            is_dep = True
        elif len(parts) > 1 and lower_parts[0] == "requirements" and lower_filename.endswith((".txt", ".in")):
            is_dep = True

        if is_dep:
            matches.append(("dependencies", f"Dependency manifest or lockfile {action}: {norm_path}"))

        # ── 2. TESTS ──────────────────────────────────────────────────────────
        is_test = False
        # Test directories
        if any(d in lower_parts for d in ("tests", "test", "spec", "__tests__", "testing")):
            is_test = True
        # Test filename patterns
        elif re.search(r"(^|/)(test_.*|.*_test|.*\.spec|.*\.test)\.[a-zA-Z0-9]+$", lower_path):
            is_test = True
        elif lower_filename in ("pytest.ini", ".coveragerc", "conftest.py"):
            is_test = True
        elif re.match(r"^(jest|vitest|karma|cypress|playwright)\.config\.[a-z]+$", lower_filename):
            is_test = True
        elif lower_filename.endswith(("test.java", "tests.java", "testcase.java", "test.kt", "tests.kt")):
            is_test = True

        if is_test:
            matches.append(("tests", f"Test suite or test file {action}: {norm_path}"))

        # ── 3. DOCUMENTATION ──────────────────────────────────────────────────
        is_doc = False
        # README files anywhere
        if lower_filename.startswith("readme"):
            is_doc = True
        # Documentation directories
        elif any(d in lower_parts for d in ("docs", "documentation", "doc")):
            is_doc = True
        # Standard repository documentation and governance files
        elif root_name in DOC_BASENAMES or lower_filename.startswith(("changelog", "contributing", "license", "authors", "changes")):
            is_doc = True
        elif lower_filename.endswith(DOC_EXTENSIONS) and (len(parts) == 1 or any(d in lower_parts for d in ("docs", "documentation", "doc"))):
            is_doc = True

        if is_doc:
            matches.append(("documentation", f"Documentation file {action}: {norm_path}"))

        # ── 4. CI/CD ──────────────────────────────────────────────────────────
        is_ci = False
        if lower_path.startswith(".github/workflows/") or lower_path.startswith(".github/actions/"):
            is_ci = True
        elif lower_path.startswith(".circleci/"):
            is_ci = True
        elif lower_filename in CI_CD_FILENAMES:
            is_ci = True
        elif lower_filename.startswith("jenkinsfile"):
            is_ci = True

        if is_ci:
            matches.append(("ci_cd", f"CI/CD workflow or pipeline {action}: {norm_path}"))

        # ── 5. DEPLOYMENT ─────────────────────────────────────────────────────
        is_deployment = False
        if lower_filename.startswith("dockerfile"):
            is_deployment = True
        elif lower_filename.startswith("docker-compose") or re.match(r"^compose(-.*)?\.(ya?ml)$", lower_filename):
            is_deployment = True
        elif lower_filename in DEPLOYMENT_FILENAMES:
            is_deployment = True
        elif any(d in lower_parts for d in ("k8s", "kubernetes", "helm", "charts", "terraform")):
            is_deployment = True
        elif len(parts) > 1 and lower_parts[0] in ("deployment", "deploy", "infrastructure", "infra"):
            is_deployment = True
        elif lower_filename.endswith((".tf", ".tfvars", ".k8s.yaml", ".k8s.yml", ".k8s.json")):
            is_deployment = True

        if is_deployment:
            matches.append(("deployment", f"Deployment or infrastructure specification {action}: {norm_path}"))

        # ── 6. CONFIGURATION ──────────────────────────────────────────────────
        is_config = False
        if any(d in lower_parts for d in ("config", "configuration", "settings")):
            is_config = True
        elif lower_filename.startswith(".env") or lower_filename.endswith((".env", ".env.example", ".env.local", ".env.production", ".env.development")):
            is_config = True
        elif lower_filename in CONFIG_FILENAMES:
            is_config = True
        elif lower_filename.startswith((".eslintrc", ".prettierrc", ".babelrc")):
            is_config = True
        elif re.match(r"^(webpack|vite|rollup|esbuild|babel|tailwind|postcss|next|nuxt|svelte|jest|vitest)\.config\.[a-z]+$", lower_filename):
            is_config = True
        # Multi-dimension configuration files
        elif lower_filename == "pyproject.toml":
            is_config = True
        elif lower_filename.startswith("docker-compose") or re.match(r"^compose(-.*)?\.(ya?ml)$", lower_filename):
            is_config = True
        elif is_ci and lower_filename.endswith((".yml", ".yaml")):
            is_config = True

        if is_config:
            matches.append(("configuration", f"Configuration file {action}: {norm_path}"))

        # ── 7. REPOSITORY STRUCTURE ───────────────────────────────────────────
        if lower_filename in WORKSPACE_STRUCTURE_FILES:
            matches.append(("repository_structure", f"Repository workspace structure file {action}: {norm_path}"))

        # ── 8. SOURCE CODE ────────────────────────────────────────────────────
        # A file qualifies as source_code if it has a recognized code extension,
        # is NOT a test file, and is NOT a build/packaging script (like setup.py)
        has_code_ext = any(lower_filename.endswith(ext) for ext in SOURCE_CODE_EXTENSIONS)
        if has_code_ext and not is_test and lower_filename != "setup.py":
            # Exclude standalone config scripts if they are in config/ or named *.config.js/ts
            if not (is_config and lower_filename.endswith(".config.js")):
                matches.append(("source_code", f"Application source code {action}: {norm_path}"))

        return matches

    def classify_files(
        self,
        paths: list[str],
        action: str = "changed",
        renames: list[tuple[str, str]] | None = None,
        added_files: list[str] | None = None,
        deleted_files: list[str] | None = None,
    ) -> tuple[list[AffectedDimension], list[str]]:
        """
        Classifies a list of file paths.
        Returns:
            (dimensions: list[AffectedDimension], unknown_files: list[str])
        """
        dim_map: dict[str, dict[str, set[str]]] = {}
        unknown: set[str] = set()

        for p in paths:
            file_action = action
            if added_files and p in added_files:
                file_action = "added"
            elif deleted_files and p in deleted_files:
                file_action = "deleted"

            file_matches = self.classify_path(p, action=file_action)
            if not file_matches:
                unknown.add(p)
            else:
                for dim, reason in file_matches:
                    if dim not in dim_map:
                        dim_map[dim] = {"files": set(), "reasons": set()}
                    dim_map[dim]["files"].add(p)
                    dim_map[dim]["reasons"].add(reason)

        # Handle file renames (movement across directories/components)
        if renames:
            for old_p, new_p in renames:
                old_norm = self.normalize_path(old_p)
                new_norm = self.normalize_path(new_p)
                old_top = old_norm.split("/")[0] if "/" in old_norm else ""
                new_top = new_norm.split("/")[0] if "/" in new_norm else ""

                if old_top != new_top or ("/" in old_norm != "/" in new_norm):
                    dim = "repository_structure"
                    reason = f"File moved across structural boundaries: {old_p} -> {new_p}"
                    if dim not in dim_map:
                        dim_map[dim] = {"files": set(), "reasons": set()}
                    dim_map[dim]["files"].add(new_p)
                    dim_map[dim]["reasons"].add(reason)

        # Detect structural and architectural boundaries from additions / deletions
        if added_files:
            for p in added_files:
                norm_p = self.normalize_path(p)
                parts = norm_p.split("/")
                # Check for new service boundary addition, e.g. services/<service_name>/...
                if len(parts) >= 3 and parts[0].lower() in ("services", "microservices", "apps"):
                    service_name = parts[1]
                    arch_reason = f"New top-level service boundary added: {parts[0]}/{service_name}"
                    struct_reason = f"Top-level structural component added: {parts[0]}/{service_name}"
                    for dim, rsn in (("architecture", arch_reason), ("repository_structure", struct_reason)):
                        if dim not in dim_map:
                            dim_map[dim] = {"files": set(), "reasons": set()}
                        dim_map[dim]["files"].add(p)
                        dim_map[dim]["reasons"].add(rsn)

        if deleted_files:
            for p in deleted_files:
                norm_p = self.normalize_path(p)
                parts = norm_p.split("/")
                if len(parts) >= 3 and parts[0].lower() in ("services", "microservices", "apps"):
                    service_name = parts[1]
                    arch_reason = f"Existing service/module boundary removed: {parts[0]}/{service_name}"
                    struct_reason = f"Top-level structural component removed: {parts[0]}/{service_name}"
                    for dim, rsn in (("architecture", arch_reason), ("repository_structure", struct_reason)):
                        if dim not in dim_map:
                            dim_map[dim] = {"files": set(), "reasons": set()}
                        dim_map[dim]["files"].add(p)
                        dim_map[dim]["reasons"].add(rsn)

        dimensions: list[AffectedDimension] = []
        for dim in sorted(dim_map.keys()):
            dimensions.append(AffectedDimension(
                dimension=dim,
                evidence_files=sorted(dim_map[dim]["files"]),
                reasons=sorted(dim_map[dim]["reasons"]),
            ))

        return dimensions, sorted(unknown)

    def classify_change_result(
        self,
        change_result,
    ) -> AffectedDimensionsResult:
        """
        Classifies changes from an IncrementalChangeResult.
        Separates committed changes from uncommitted working-tree changes.
        """
        # 1. Committed change set
        committed_changed = list(getattr(change_result, "changed_files", []))
        added_files = list(getattr(change_result, "added_files", []))
        deleted_files = list(getattr(change_result, "deleted_files", []))
        modified_files = list(getattr(change_result, "modified_files", []))

        # Check for renames: file present in both deleted and added with related names
        renames: list[tuple[str, str]] = []
        added_set = set(added_files)
        for d in deleted_files:
            base_d = Path(d).name
            for a in added_set:
                if Path(a).name == base_d and a != d:
                    renames.append((d, a))

        committed_dims, committed_unknown = self.classify_files(
            paths=committed_changed,
            action="changed",
            renames=renames,
            added_files=added_files,
            deleted_files=deleted_files,
        )

        # 2. Uncommitted working-tree change set
        uncommitted_files = list(getattr(change_result, "uncommitted_files", []))
        uncommitted_dims, uncommitted_unknown = self.classify_files(
            paths=uncommitted_files,
            action="uncommitted",
        )

        all_unknown = sorted(set(committed_unknown + uncommitted_unknown))

        return AffectedDimensionsResult(
            committed=committed_dims,
            uncommitted=uncommitted_dims,
            unknown_files=all_unknown,
            committed_unknown_files=committed_unknown,
            uncommitted_unknown_files=uncommitted_unknown,
        )

    def classify(
        self,
        target,
        action: str = "changed",
    ) -> AffectedDimensionsResult:
        """
        Versatile classify entry point supporting IncrementalChangeResult
        or a list of file paths.
        """
        if hasattr(target, "changed_files") or hasattr(target, "uncommitted_files"):
            return self.classify_change_result(target)

        if isinstance(target, (list, set, tuple)):
            dims, unknown = self.classify_files(list(target), action=action)
            return AffectedDimensionsResult(
                committed=dims,
                uncommitted=[],
                unknown_files=unknown,
                committed_unknown_files=unknown,
                uncommitted_unknown_files=[],
            )

        raise TypeError(f"Expected IncrementalChangeResult or list of file paths, got {type(target)}")


def detect_affected_dimensions(
    change_result_or_files,
    repo_path: str | None = None,
) -> AffectedDimensionsResult:
    """
    Convenience function to classify affected dimensions from an
    IncrementalChangeResult or file list.
    """
    classifier = AffectedDimensionClassifier(repo_path=repo_path)
    return classifier.classify(change_result_or_files)
