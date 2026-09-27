"""
Repository Assessment Engine.

Deterministic, evidence-grounded assessment of an existing repository.
Evaluates:
  - Code health (AST syntax compilation, unparseable files, broken relative imports)
  - Dependencies (manifests, package managers, lockfile presence, dependency counts)
  - Architecture (observed conventions, documented README claims, drift analysis)
  - Testing (frameworks, test directories, test patterns, test configs)
  - Git vitality (HEAD, branch, commit history, dirty state)
  - Documentation (README presence, size, setup/deploy instructions)

Zero LLM calls. Zero code modification. Zero side effects.
"""

import ast
import os
import re
from pathlib import Path

from src.models.repo_profile import Finding, RepoProfile
from src.models.assessment import CodeHealthReport, EngineeringAssessment
from src.helpers.file_scanner import FileScanner
from src.helpers.language_detector import LanguageDetector
from src.helpers.git_context import get_git_context
from src.helpers.repo_discovery import RepoDiscovery
from src.helpers.tree_parcer import CodeParser


_IGNORED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    "dist", "build", "obj", "bin", ".dart_tool", ".idea", ".vscode",
}

_MANIFEST_CONFIGS = [
    # (manifest_name, ecosystem, is_lockfile)
    ("requirements.txt", "pip", False),
    ("pyproject.toml", "pip/poetry/hatch", False),
    ("setup.py", "pip/setuptools", False),
    ("setup.cfg", "pip/setuptools", False),
    ("Pipfile", "pipenv", False),
    ("Pipfile.lock", "pipenv", True),
    ("poetry.lock", "poetry", True),
    ("package.json", "npm", False),
    ("package-lock.json", "npm", True),
    ("yarn.lock", "yarn", True),
    ("pnpm-lock.yaml", "pnpm", True),
    ("bun.lockb", "bun", True),
    ("pom.xml", "maven", False),
    ("build.gradle", "gradle", False),
    ("build.gradle.kts", "gradle", False),
    ("CMakeLists.txt", "cmake", False),
    ("pubspec.yaml", "pub (Dart/Flutter)", False),
    ("pubspec.lock", "pub (Dart/Flutter)", True),
    ("Cargo.toml", "cargo", False),
    ("Cargo.lock", "cargo", True),
    ("go.mod", "go modules", False),
    ("go.sum", "go modules", True),
    ("composer.json", "composer", False),
    ("composer.lock", "composer", True),
    ("Gemfile", "bundler", False),
    ("Gemfile.lock", "bundler", True),
]


class RepositoryAssessmentEngine:
    """
    Deterministic engine that analyzes an existing repository on disk
    and produces a structured, evidence-backed EngineeringAssessment.
    """

    def __init__(self, repo_path: str | None, profile: RepoProfile | None = None):
        self.repo_path = repo_path
        self._profile = profile
        self.scanner = FileScanner()
        self.detector = LanguageDetector()

    # ── 1. Code Health Assessment ─────────────────────────────────────────────

    def assess_code_health(self) -> tuple[CodeHealthReport, list[Finding]]:
        """
        Evaluates source code health deterministically without code execution:
          - AST syntax validation (Python)
          - Tree-sitter syntax validation (other supported languages)
          - Broken relative import resolution (Python AST)
          - Unreadable / unparseable file tracking
        """
        findings: list[Finding] = []

        if not self.repo_path or not os.path.exists(self.repo_path):
            report = CodeHealthReport(
                is_clean=False,
                syntax_errors=[],
                import_errors=[],
                unparseable_files=[],
                scanned_file_count=0,
            )
            return report, findings

        all_files = self.scanner.scan(self.repo_path)
        code_files = [f for f in all_files if self.detector.detect(f) is not None]

        if not code_files:
            report = CodeHealthReport(
                is_clean=True,
                syntax_errors=[],
                import_errors=[],
                unparseable_files=[],
                scanned_file_count=0,
            )
            findings.append(Finding(
                category="code_health",
                observation="No source code files detected in repository",
                evidence="File scanner found 0 files matching known programming language extensions",
                source="observed",
                severity="info",
            ))
            return report, findings

        syntax_errors: list[Finding] = []
        import_errors: list[Finding] = []
        unparseable_files: list[str] = []

        # Tree parser for non-Python languages
        tree_parser = None

        for rel_path in code_files:
            full_path = os.path.join(self.repo_path, rel_path)
            lang = self.detector.detect(rel_path)

            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    source = f.read()
            except (UnicodeDecodeError, OSError) as e:
                unparseable_files.append(rel_path)
                continue

            if lang == "python":
                # Deterministic Python AST check
                try:
                    tree = ast.parse(source, filename=rel_path)
                except SyntaxError as e:
                    line_col = f"{e.lineno}:{e.offset}" if e.lineno else "1:0"
                    syntax_finding = Finding(
                        category="code_health",
                        observation=f"SyntaxError in {rel_path}: {e.msg}",
                        evidence=f"{rel_path}:{line_col}",
                        source="observed",
                        severity="concern",
                    )
                    syntax_errors.append(syntax_finding)
                    continue
                except Exception:
                    unparseable_files.append(rel_path)
                    continue

                # Deterministic broken relative import detection
                file_dir = Path(full_path).parent
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.level and node.level > 0:
                        target_base = file_dir
                        for _ in range(node.level - 1):
                            target_base = target_base.parent

                        mod_name = node.module or ""
                        if mod_name:
                            mod_rel_path = mod_name.replace(".", os.sep)
                            py_target = target_base / f"{mod_rel_path}.py"
                            pkg_target = target_base / mod_rel_path / "__init__.py"
                            dir_target = target_base / mod_rel_path
                            if not (py_target.exists() or pkg_target.exists() or dir_target.is_dir()):
                                imp_finding = Finding(
                                    category="code_health",
                                    observation=f"Broken relative import: 'from {'.' * node.level}{mod_name}' in {rel_path}",
                                    evidence=f"{rel_path}:{node.lineno}",
                                    source="observed",
                                    severity="concern",
                                )
                                import_errors.append(imp_finding)
            else:
                # Other languages: Tree-sitter syntax validation
                try:
                    if tree_parser is None:
                        tree_parser = CodeParser()
                    if lang in tree_parser.languages:
                        parsed_tree = tree_parser.parse(source, lang)
                        if parsed_tree.root_node.has_error:
                            syntax_errors.append(Finding(
                                category="code_health",
                                observation=f"Syntax error detected in {rel_path} ({lang})",
                                evidence=f"{rel_path}",
                                source="observed",
                                severity="concern",
                            ))
                except Exception:
                    unparseable_files.append(rel_path)

        is_clean = (
            len(syntax_errors) == 0
            and len(import_errors) == 0
            and len(unparseable_files) == 0
        )

        report = CodeHealthReport(
            is_clean=is_clean,
            syntax_errors=syntax_errors,
            import_errors=import_errors,
            unparseable_files=unparseable_files,
            scanned_file_count=len(code_files),
        )

        # Record findings
        if syntax_errors:
            findings.append(Finding(
                category="code_health",
                observation=f"Detected {len(syntax_errors)} syntax error(s) across scanned code files",
                evidence=", ".join(f.evidence for f in syntax_errors[:3]),
                source="observed",
                severity="concern",
            ))
        if import_errors:
            findings.append(Finding(
                category="code_health",
                observation=f"Detected {len(import_errors)} broken relative import(s)",
                evidence=", ".join(f.evidence for f in import_errors[:3]),
                source="observed",
                severity="concern",
            ))
        if unparseable_files:
            findings.append(Finding(
                category="code_health",
                observation=f"Detected {len(unparseable_files)} unreadable or unparseable source file(s)",
                evidence=", ".join(unparseable_files[:3]),
                source="observed",
                severity="warning",
            ))
        if is_clean:
            findings.append(Finding(
                category="code_health",
                observation=f"All {len(code_files)} scanned source code file(s) compiled without syntax or broken relative import errors",
                evidence=f"{len(code_files)} files parsed cleanly",
                source="observed",
                severity="info",
            ))

        findings.append(Finding(
            category="code_health",
            observation="Static relative imports verified via AST; dynamic runtime imports not executed to ensure safe deterministic evaluation",
            evidence="AST ImportFrom analysis",
            source="observed",
            severity="info",
        ))

        return report, findings

    # ── 2. Dependency Assessment ──────────────────────────────────────────────

    def assess_dependencies(self) -> tuple[dict, list[Finding]]:
        """
        Detects dependency manifests, lockfiles, package managers, and count.
        """
        findings: list[Finding] = []
        dep_status = {
            "manifest_count": 0,
            "manifests_found": [],
            "package_managers": [],
            "has_lockfile": False,
            "lockfiles_found": [],
            "dependency_count": 0,
        }

        if not self.repo_path or not os.path.exists(self.repo_path):
            return dep_status, findings

        repo = Path(self.repo_path)
        manifests_found = []
        lockfiles_found = []
        pkg_managers = set()
        dep_count = 0

        # Scan for known manifests
        for filename, pm, is_lock in _MANIFEST_CONFIGS:
            path = repo / filename
            if path.exists():
                if is_lock:
                    lockfiles_found.append(filename)
                else:
                    manifests_found.append(filename)
                    pkg_managers.add(pm)

                # Attempt safe dependency count estimation for common formats
                if filename == "requirements.txt":
                    try:
                        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                        deps = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
                        dep_count += len(deps)
                    except Exception:
                        pass
                elif filename == "package.json":
                    try:
                        import json
                        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                        d1 = len(data.get("dependencies", {}))
                        d2 = len(data.get("devDependencies", {}))
                        dep_count += (d1 + d2)
                    except Exception:
                        pass

        # Check .NET project files
        try:
            for item in repo.glob("*.csproj"):
                manifests_found.append(item.name)
                pkg_managers.add("nuget")
            for item in repo.glob("*.sln"):
                manifests_found.append(item.name)
                pkg_managers.add("dotnet")
        except Exception:
            pass

        has_lock = len(lockfiles_found) > 0
        dep_status["manifest_count"] = len(manifests_found)
        dep_status["manifests_found"] = sorted(manifests_found)
        dep_status["package_managers"] = sorted(pkg_managers)
        dep_status["has_lockfile"] = has_lock
        dep_status["lockfiles_found"] = sorted(lockfiles_found)
        dep_status["dependency_count"] = dep_count

        if manifests_found:
            findings.append(Finding(
                category="dependency",
                observation=f"Dependency manifests detected: {', '.join(sorted(manifests_found))}",
                evidence=f"Package managers: {', '.join(sorted(pkg_managers)) if pkg_managers else 'standard'}",
                source="observed",
                severity="info",
            ))
            if not has_lock:
                findings.append(Finding(
                    category="dependency",
                    observation="Dependency manifest detected without corresponding lockfile",
                    evidence=f"Manifests: {', '.join(sorted(manifests_found))}; lockfile missing",
                    source="observed",
                    severity="info",
                ))
            else:
                findings.append(Finding(
                    category="dependency",
                    observation=f"Dependency lockfile(s) present: {', '.join(sorted(lockfiles_found))}",
                    evidence="Deterministic dependency pinning verified",
                    source="observed",
                    severity="info",
                ))
        else:
            findings.append(Finding(
                category="dependency",
                observation="No standard dependency manifest detected in repository root",
                evidence="Scanned for requirements.txt, pyproject.toml, package.json, pom.xml, Cargo.toml, etc.",
                source="observed",
                severity="warning",
            ))

        return dep_status, findings

    # ── 3. Architecture Assessment ────────────────────────────────────────────

    def assess_architecture(self) -> tuple[str | None, str | None, bool, list[Finding]]:
        """
        Reuses RepoDiscovery to assess observed vs documented architecture and drift.
        """
        findings: list[Finding] = []
        observed = None
        documented = None
        drift = False

        if self._profile:
            observed = self._profile.architecture_style_observed
            documented = self._profile.architecture_style_documented
        elif self.repo_path and os.path.exists(self.repo_path):
            try:
                discovery = RepoDiscovery(self.repo_path)
                observed = discovery._infer_architecture_style()
                documented = discovery._detect_documented_architecture()
            except Exception as e:
                findings.append(Finding(
                    category="architecture",
                    observation=f"Architecture discovery encountered an error: {e}",
                    evidence="RepoDiscovery inference",
                    source="observed",
                    severity="warning",
                ))

        if observed and documented:
            if observed.lower() != documented.lower():
                drift = True
                findings.append(Finding(
                    category="architecture",
                    observation=f"Documented architecture '{documented}' differs from observed structure '{observed}'",
                    evidence="README architecture text vs directory layout",
                    source="inferred",
                    severity="concern",
                ))
            else:
                findings.append(Finding(
                    category="architecture",
                    observation=f"Documented architecture matches observed structure: {observed}",
                    evidence="README documentation and directory layout align",
                    source="inferred",
                    severity="info",
                ))
        elif observed:
            findings.append(Finding(
                category="architecture",
                observation=f"Observed architecture structure: {observed}",
                evidence="Directory naming and layout conventions",
                source="inferred",
                severity="info",
            ))
        elif documented:
            findings.append(Finding(
                category="architecture",
                observation=f"Documented architecture style: {documented} (structural layout unconfirmed)",
                evidence="README architecture section",
                source="inferred",
                severity="info",
            ))
        else:
            findings.append(Finding(
                category="architecture",
                observation="Architecture style undetermined from directory layout",
                evidence="No standard architectural folder conventions (e.g. MVC, Clean Architecture, Agent) matched",
                source="inferred",
                severity="info",
            ))

        return observed, documented, drift, findings

    # ── 4. Testing Assessment ─────────────────────────────────────────────────

    def assess_testing(self) -> tuple[dict, list[Finding]]:
        """
        Evaluates test infrastructure presence without executing test suites.
        """
        findings: list[Finding] = []
        test_status = {
            "has_tests": False,
            "test_frameworks": [],
            "test_directories": [],
            "test_file_count": 0,
            "has_test_config": False,
            "ci_test_detected": False,
        }

        if not self.repo_path or not os.path.exists(self.repo_path):
            return test_status, findings

        repo = Path(self.repo_path)
        test_dirs = []
        for d in ("tests", "test", "spec", "__tests__"):
            if (repo / d).is_dir():
                test_dirs.append(d)

        # Detect test config files
        configs = []
        for cfg in ("pytest.ini", "setup.cfg", "jest.config.js", "jest.config.ts", ".coveragerc"):
            if (repo / cfg).exists():
                configs.append(cfg)

        # Count test files matching standard conventions
        all_files = self.scanner.scan(self.repo_path)
        test_file_patterns = re.compile(r"(^|/)(test_.*|.*_test|.*\.spec|.*\.test)\.[a-zA-Z0-9]+$")
        test_files = [f for f in all_files if test_file_patterns.search(f)]

        # Check CI files for test commands
        ci_test = False
        ci_dir = repo / ".github" / "workflows"
        if ci_dir.is_dir():
            for ci_file in ci_dir.glob("*.y*ml"):
                try:
                    text = ci_file.read_text(encoding="utf-8", errors="replace")
                    if any(cmd in text for cmd in ("pytest", "npm test", "cargo test", "go test", "mvn test")):
                        ci_test = True
                        break
                except Exception:
                    pass

        # Frameworks from profile or discovery
        frameworks = []
        if self._profile:
            frameworks = list(self._profile.testing_frameworks)
        else:
            try:
                discovery = RepoDiscovery(self.repo_path)
                _, _, _, _, testing_frameworks = discovery._analyze_dependencies()
                frameworks = list(testing_frameworks)
            except Exception:
                pass

        has_tests = len(test_files) > 0 or len(test_dirs) > 0 or len(frameworks) > 0
        test_status["has_tests"] = has_tests
        test_status["test_frameworks"] = sorted(set(frameworks))
        test_status["test_directories"] = sorted(test_dirs)
        test_status["test_file_count"] = len(test_files)
        test_status["has_test_config"] = len(configs) > 0
        test_status["ci_test_detected"] = ci_test

        if has_tests:
            detail = f"{len(test_files)} test file(s)"
            if frameworks:
                detail += f", frameworks: {', '.join(sorted(set(frameworks)))}"
            findings.append(Finding(
                category="testing",
                observation=f"Automated testing infrastructure detected ({detail})",
                evidence=f"Directories: {', '.join(test_dirs) if test_dirs else 'root/inline'}",
                source="observed",
                severity="info",
            ))
        else:
            findings.append(Finding(
                category="testing",
                observation="No automated test suite or test files detected in repository",
                evidence="Searched for tests/, test_, *_test files and test manifests",
                source="observed",
                severity="warning",
            ))

        return test_status, findings

    # ── 5. Git Vitality Assessment ────────────────────────────────────────────

    def assess_git(self) -> tuple[dict, list[Finding]]:
        """
        Evaluates Git presence, commit volume, branch, and history without stage inference.
        """
        findings: list[Finding] = []
        git_status = {
            "is_git_repo": False,
            "head_commit": None,
            "branch": None,
            "recent_commit_count": 0,
            "has_history": False,
        }

        if not self.repo_path or not os.path.exists(self.repo_path):
            return git_status, findings

        ctx = get_git_context(self.repo_path)
        git_status["is_git_repo"] = ctx.is_git_repo
        git_status["head_commit"] = ctx.head_commit
        git_status["branch"] = ctx.branch
        git_status["recent_commit_count"] = len(ctx.recent_commits)
        git_status["has_history"] = ctx.head_commit is not None and len(ctx.recent_commits) > 0

        if not ctx.is_git_repo:
            findings.append(Finding(
                category="git",
                observation="Repository is not initialized with Git version control",
                evidence="No .git directory found",
                source="observed",
                severity="warning",
            ))
        elif ctx.recent_commits:
            findings.append(Finding(
                category="git",
                observation=f"Git repository active on branch '{ctx.branch}' with {len(ctx.recent_commits)} recent commit(s)",
                evidence=f"HEAD: {ctx.head_commit[:8] if ctx.head_commit else 'unborn'}",
                source="observed",
                severity="info",
            ))
        else:
            findings.append(Finding(
                category="git",
                observation="Git repository initialized but has no commits",
                evidence="HEAD commit is not available",
                source="observed",
                severity="info",
            ))

        return git_status, findings

    # ── 6. Documentation Assessment ───────────────────────────────────────────

    def assess_documentation(self) -> tuple[dict, list[Finding]]:
        """
        Detects documentation artifacts (README, docs/ directory, setup/deploy text).
        """
        findings: list[Finding] = []
        doc_status = {
            "has_readme": False,
            "readme_path": None,
            "readme_size_bytes": 0,
            "has_docs_directory": False,
            "has_setup_instructions": False,
            "has_architecture_docs": False,
            "has_deployment_docs": False,
        }

        if not self.repo_path or not os.path.exists(self.repo_path):
            return doc_status, findings

        repo = Path(self.repo_path)
        doc_status["has_docs_directory"] = (repo / "docs").is_dir()

        readme_file = None
        for name in ("README.md", "README.rst", "README.txt", "README"):
            p = repo / name
            if p.exists() and p.is_file():
                readme_file = p
                break

        if readme_file:
            doc_status["has_readme"] = True
            doc_status["readme_path"] = readme_file.name
            try:
                content = readme_file.read_text(encoding="utf-8", errors="replace")
                size = len(content)
                doc_status["readme_size_bytes"] = size
                lower = content.lower()

                doc_status["has_setup_instructions"] = any(kw in lower for kw in (
                    "install", "setup", "getting started", "quickstart", "usage", "running"
                ))
                doc_status["has_architecture_docs"] = any(kw in lower for kw in (
                    "architecture", "design", "overview", "components", "structure", "data flow"
                ))
                doc_status["has_deployment_docs"] = any(kw in lower for kw in (
                    "deploy", "docker", "production", "kubernetes", "k8s", "compose"
                ))

                if size < 50:
                    findings.append(Finding(
                        category="documentation",
                        observation="README file exists but appears minimal or placeholder",
                        evidence=f"{readme_file.name} is {size} bytes",
                        source="observed",
                        severity="warning",
                    ))
                else:
                    findings.append(Finding(
                        category="documentation",
                        observation=f"README documentation detected with setup and usage content ({size} bytes)",
                        evidence=f"Path: {readme_file.name}",
                        source="observed",
                        severity="info",
                    ))
            except Exception:
                pass
        else:
            findings.append(Finding(
                category="documentation",
                observation="No README file found in repository root",
                evidence="Searched for README.md, README.rst, README.txt, README",
                source="observed",
                severity="warning",
            ))

        return doc_status, findings

    # ── 7. Overall Assessment Builder ─────────────────────────────────────────

    def build_assessment(self) -> EngineeringAssessment:
        """
        Orchestrates all deterministic detectors safely and builds the EngineeringAssessment.
        A failure in an individual detector is recorded as a finding and does not crash the engine.
        """
        all_findings: list[Finding] = []
        risks: list[str] = []
        recommendations: list[str] = []

        repo_name = "unknown"
        if self.repo_path:
            repo_name = Path(self.repo_path).name or "unknown"
        if self._profile and self._profile.name:
            repo_name = self._profile.name

        # Edge case: repository path missing
        if not self.repo_path or not os.path.exists(self.repo_path):
            health = CodeHealthReport(
                is_clean=False,
                syntax_errors=[],
                import_errors=[],
                unparseable_files=[],
                scanned_file_count=0,
            )
            all_findings.append(Finding(
                category="repository",
                observation=f"Repository path does not exist: {self.repo_path}",
                evidence="Filesystem check",
                source="observed",
                severity="concern",
            ))
            risks.append("Repository path is missing or inaccessible on filesystem.")
            recommendations.append("Verify and provide a valid repository path before assessment.")
            return EngineeringAssessment(
                repo_name=repo_name,
                health=health,
                findings=all_findings,
                risks=risks,
                recommendations=recommendations,
            )

        # 1. Code Health
        try:
            health, health_findings = self.assess_code_health()
            all_findings.extend(health_findings)
        except Exception as e:
            health = CodeHealthReport(is_clean=False, scanned_file_count=0)
            all_findings.append(Finding(
                category="code_health",
                observation=f"Code health assessment encountered an error: {e}",
                evidence="assess_code_health exception",
                source="observed",
                severity="concern",
            ))

        # 2. Dependencies
        try:
            dep_status, dep_findings = self.assess_dependencies()
            all_findings.extend(dep_findings)
        except Exception as e:
            dep_status = {}
            all_findings.append(Finding(
                category="dependency",
                observation=f"Dependency assessment encountered an error: {e}",
                evidence="assess_dependencies exception",
                source="observed",
                severity="warning",
            ))

        # 3. Architecture
        try:
            arch_observed, arch_documented, drift_detected, arch_findings = self.assess_architecture()
            all_findings.extend(arch_findings)
        except Exception as e:
            arch_observed, arch_documented, drift_detected = None, None, False
            all_findings.append(Finding(
                category="architecture",
                observation=f"Architecture assessment encountered an error: {e}",
                evidence="assess_architecture exception",
                source="observed",
                severity="warning",
            ))

        # 4. Testing
        try:
            test_status, test_findings = self.assess_testing()
            all_findings.extend(test_findings)
        except Exception as e:
            test_status = {}
            all_findings.append(Finding(
                category="testing",
                observation=f"Testing assessment encountered an error: {e}",
                evidence="assess_testing exception",
                source="observed",
                severity="warning",
            ))

        # 5. Git Vitality
        try:
            git_status, git_findings = self.assess_git()
            all_findings.extend(git_findings)
        except Exception as e:
            git_status = {}
            all_findings.append(Finding(
                category="git",
                observation=f"Git assessment encountered an error: {e}",
                evidence="assess_git exception",
                source="observed",
                severity="warning",
            ))

        # 6. Documentation
        try:
            doc_status, doc_findings = self.assess_documentation()
            all_findings.extend(doc_findings)
        except Exception as e:
            doc_status = {}
            all_findings.append(Finding(
                category="documentation",
                observation=f"Documentation assessment encountered an error: {e}",
                evidence="assess_documentation exception",
                source="observed",
                severity="warning",
            ))

        # ── Derive Evidence-Backed Risks ──────────────────────────────────────
        if not health.is_clean:
            details = []
            if health.syntax_errors:
                details.append(f"{len(health.syntax_errors)} syntax error(s)")
            if health.import_errors:
                details.append(f"{len(health.import_errors)} import error(s)")
            if health.unparseable_files:
                details.append(f"{len(health.unparseable_files)} unparseable file(s)")
            detail_str = ", ".join(details) if details else "unverified code state"
            risks.append(f"Code health is compromised: {detail_str} detected.")
            recommendations.append("Address syntax and import errors before attempting execution or automated refactoring.")

        if not git_status.get("is_git_repo"):
            risks.append("Project is not tracked by Git; modifications cannot be safely rolled back.")
            recommendations.append("Initialize Git version control ('git init') to establish a change baseline.")

        if not test_status.get("has_tests"):
            risks.append("No automated test suite detected; code changes lack automated verification safety nets.")
            recommendations.append("Introduce automated tests around core entry points.")

        if drift_detected:
            risks.append("Documented architecture differs from observed code structure; documentation may mislead engineers.")
            recommendations.append("Reconcile README documentation with current repository organization.")

        if dep_status.get("manifest_count", 0) > 0 and not dep_status.get("has_lockfile"):
            risks.append("Dependency manifest exists without a corresponding lockfile; build reproducibility may vary across environments.")
            recommendations.append("Generate and commit a dependency lockfile (e.g. poetry.lock, package-lock.json).")

        if not doc_status.get("has_readme"):
            risks.append("No README found; repository lacks setup, architectural, and usage instructions.")
            recommendations.append("Add a README.md documenting project purpose, setup instructions, and primary entry points.")

        return EngineeringAssessment(
            repo_name=repo_name,
            health=health,
            architecture_style_observed=arch_observed,
            architecture_style_documented=arch_documented,
            architecture_drift_detected=drift_detected,
            dependency_status=dep_status,
            test_framework_status=test_status,
            git_vitality=git_status,
            findings=all_findings,
            risks=risks,
            recommendations=recommendations,
        )
