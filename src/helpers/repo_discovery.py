"""
Repository Discovery Engine.

Fully deterministic — no LLM calls.
Inspects files, directories, and dependency manifests to build a RepoProfile.

All findings record the file or pattern that provided the evidence.
The LLM is reserved for interpretation, not discovery.
"""

import os
import json
import re
import tomllib
from pathlib import Path

from src.models.repo_profile import RepoProfile, TechnologyEntry, Finding

_IGNORED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    "dist", "build", "obj", "bin", ".dart_tool", ".idea", ".vscode",
}


class RepoDiscovery:
    """
    Deterministic repository discovery engine.

    Produces a RepoProfile backed entirely by evidence found in the repository.
    No LLM. No assumptions.
    """

    # ─── Package Manager Indicators ──────────────────────────────────────────

    PACKAGE_MANAGER_FILES: dict[str, str] = {
        "requirements.txt": "pip",
        "setup.py": "pip/setuptools",
        "setup.cfg": "pip/setuptools",
        "pyproject.toml": "pip/poetry/hatch",
        "Pipfile": "pipenv",
        "package.json": "npm",
        "yarn.lock": "yarn",
        "pnpm-lock.yaml": "pnpm",
        "pom.xml": "maven",
        "build.gradle": "gradle",
        "build.gradle.kts": "gradle",
        "go.mod": "go modules",
        "Cargo.toml": "cargo",
        "composer.json": "composer",
        "Gemfile": "bundler",
        "pubspec.yaml": "pub (Dart/Flutter)",
    }

    # ─── Technology Classification ────────────────────────────────────────────
    # Each entry: dependency_key → (display_name, purpose, category)
    # category: "framework" | "database" | "vector_db" | "cache" | "queue" | "testing" | "llm" | "embedding"

    PYTHON_TECH: dict[str, tuple[str, str, str]] = {
        # Web frameworks
        "django": ("Django", "web framework", "framework"),
        "flask": ("Flask", "web framework", "framework"),
        "fastapi": ("FastAPI", "web framework", "framework"),
        "starlette": ("Starlette", "ASGI toolkit", "framework"),
        "tornado": ("Tornado", "web framework", "framework"),
        "aiohttp": ("aiohttp", "async HTTP framework", "framework"),
        "sanic": ("Sanic", "async web framework", "framework"),
        # ASGI/WSGI servers
        "uvicorn": ("Uvicorn", "ASGI server", "framework"),
        "gunicorn": ("Gunicorn", "WSGI server", "framework"),
        "hypercorn": ("Hypercorn", "ASGI server", "framework"),
        # LLM / Agent
        "langchain": ("LangChain", "LLM orchestration framework", "framework"),
        "langgraph": ("LangGraph", "agent orchestration / stateful graphs", "framework"),
        "langchain-ollama": ("LangChain-Ollama", "Ollama LLM integration", "framework"),
        "langchain_ollama": ("LangChain-Ollama", "Ollama LLM integration", "framework"),
        "langchain-openai": ("LangChain-OpenAI", "OpenAI LLM integration", "framework"),
        "langchain_openai": ("LangChain-OpenAI", "OpenAI LLM integration", "framework"),
        "openai": ("OpenAI SDK", "OpenAI LLM API", "framework"),
        "anthropic": ("Anthropic SDK", "Claude LLM API", "framework"),
        "ollama": ("Ollama", "local LLM runtime client", "framework"),
        "litellm": ("LiteLLM", "unified LLM proxy", "framework"),
        "transformers": ("HuggingFace Transformers", "ML model library", "framework"),
        "torch": ("PyTorch", "deep learning framework", "framework"),
        "tensorflow": ("TensorFlow", "deep learning framework", "framework"),
        "scikit-learn": ("scikit-learn", "machine learning library", "framework"),
        "sklearn": ("scikit-learn", "machine learning library", "framework"),
        # Structural parsing
        "tree-sitter": ("Tree-sitter", "structural code parsing", "framework"),
        "tree_sitter": ("Tree-sitter", "structural code parsing", "framework"),
        # Embeddings
        "fastembed": ("FastEmbed", "local embedding model", "embedding"),
        "sentence-transformers": ("Sentence Transformers", "text embedding models", "embedding"),
        "sentence_transformers": ("Sentence Transformers", "text embedding models", "embedding"),
        # Vector databases
        "qdrant-client": ("Qdrant", "vector database", "vector_db"),
        "qdrant_client": ("Qdrant", "vector database", "vector_db"),
        "chromadb": ("ChromaDB", "vector database", "vector_db"),
        "weaviate-client": ("Weaviate", "vector database", "vector_db"),
        "pinecone-client": ("Pinecone", "vector database (cloud)", "vector_db"),
        "pymilvus": ("Milvus", "vector database", "vector_db"),
        # Relational databases / ORM
        "sqlalchemy": ("SQLAlchemy", "SQL ORM / toolkit", "database"),
        "alembic": ("Alembic", "database migrations", "database"),
        "psycopg2": ("psycopg2", "PostgreSQL driver", "database"),
        "psycopg2-binary": ("psycopg2", "PostgreSQL driver", "database"),
        "psycopg": ("psycopg3", "PostgreSQL async driver", "database"),
        "asyncpg": ("asyncpg", "async PostgreSQL driver", "database"),
        "pymysql": ("PyMySQL", "MySQL driver", "database"),
        "aiomysql": ("aiomysql", "async MySQL driver", "database"),
        "aiosqlite": ("aiosqlite", "async SQLite driver", "database"),
        # NoSQL
        "pymongo": ("MongoDB", "MongoDB driver", "database"),
        "motor": ("Motor", "async MongoDB driver", "database"),
        # Cache
        "redis": ("Redis", "cache / message broker", "cache"),
        "aioredis": ("Redis (async)", "async cache / broker", "cache"),
        "hiredis": ("hiredis", "Redis protocol parser", "cache"),
        # Message queues
        "celery": ("Celery", "distributed task queue", "queue"),
        "pika": ("RabbitMQ (pika)", "AMQP message broker", "queue"),
        "kafka-python": ("Kafka", "distributed message broker", "queue"),
        "aiokafka": ("Kafka (async)", "async message broker", "queue"),
        # Testing
        "pytest": ("pytest", "testing", "testing"),
        "hypothesis": ("Hypothesis", "property-based testing", "testing"),
        "unittest2": ("unittest", "testing", "testing"),
        # Data validation / serialization
        "pydantic": ("Pydantic", "data validation and serialization", "framework"),
        "marshmallow": ("Marshmallow", "object serialization", "framework"),
        # HTTP clients
        "requests": ("requests", "HTTP client", "framework"),
        "httpx": ("httpx", "async HTTP client", "framework"),
        # Auth
        "python-jose": ("python-jose", "JWT handling", "framework"),
        "pyjwt": ("PyJWT", "JWT handling", "framework"),
        "passlib": ("passlib", "password hashing", "framework"),
        "authlib": ("Authlib", "OAuth / OIDC client", "framework"),
        # Cloud
        "boto3": ("AWS SDK (boto3)", "AWS cloud integration", "framework"),
        "google-cloud-storage": ("Google Cloud Storage", "GCS integration", "framework"),
        # Observability
        "prometheus-client": ("Prometheus", "metrics / monitoring", "framework"),
        "opentelemetry-sdk": ("OpenTelemetry", "distributed tracing", "framework"),
        "sentry-sdk": ("Sentry", "error tracking", "framework"),
    }

    JS_TECH: dict[str, tuple[str, str, str]] = {
        "react": ("React", "UI library", "framework"),
        "vue": ("Vue.js", "UI framework", "framework"),
        "angular": ("Angular", "UI framework", "framework"),
        "next": ("Next.js", "React meta-framework", "framework"),
        "nuxt": ("Nuxt.js", "Vue meta-framework", "framework"),
        "svelte": ("Svelte", "UI compiler", "framework"),
        "express": ("Express", "web framework", "framework"),
        "fastify": ("Fastify", "web framework", "framework"),
        "@nestjs/core": ("NestJS", "backend framework", "framework"),
        "typeorm": ("TypeORM", "ORM", "database"),
        "prisma": ("Prisma", "ORM / query builder", "database"),
        "mongoose": ("Mongoose", "MongoDB ODM", "database"),
        "sequelize": ("Sequelize", "SQL ORM", "database"),
        "ioredis": ("Redis (ioredis)", "Redis client", "cache"),
        "jest": ("Jest", "testing", "testing"),
        "vitest": ("Vitest", "testing", "testing"),
        "mocha": ("Mocha", "testing", "testing"),
        "webpack": ("Webpack", "module bundler", "framework"),
        "vite": ("Vite", "build tool", "framework"),
        "esbuild": ("esbuild", "bundler / transpiler", "framework"),
        "tailwindcss": ("TailwindCSS", "CSS utility framework", "framework"),
    }

    # ─── CI/CD Indicators ────────────────────────────────────────────────────

    CI_CD_PATHS: dict[str, str] = {
        ".github/workflows": "GitHub Actions",
        ".gitlab-ci.yml": "GitLab CI",
        "Jenkinsfile": "Jenkins",
        ".circleci": "CircleCI",
        ".travis.yml": "Travis CI",
        "azure-pipelines.yml": "Azure Pipelines",
        ".drone.yml": "Drone CI",
        "bitbucket-pipelines.yml": "Bitbucket Pipelines",
    }

    # ─── Deployment Indicators ────────────────────────────────────────────────

    DEPLOYMENT_INDICATORS: dict[str, str] = {
        "Dockerfile": "Docker",
        "docker-compose.yml": "Docker Compose",
        "docker-compose.yaml": "Docker Compose",
        "kubernetes": "Kubernetes",
        "k8s": "Kubernetes",
        "helm": "Helm",
        "terraform": "Terraform",
        "Procfile": "Heroku",
        "fly.toml": "Fly.io",
        "railway.toml": "Railway",
        "render.yaml": "Render",
        "vercel.json": "Vercel",
        "netlify.toml": "Netlify",
    }

    # ─── Architecture Folder Indicators ──────────────────────────────────────

    ARCHITECTURE_FOLDER_HINTS: dict[str, str] = {
        "controllers": "MVC",
        "views": "MVC",
        "models": "MVC / Layered",
        "services": "Service Layer",
        "repositories": "Repository Pattern",
        "handlers": "Handler Pattern",
        "usecases": "Clean Architecture",
        "use_cases": "Clean Architecture",
        "domain": "Domain-Driven Design",
        "infrastructure": "Clean / Hexagonal Architecture",
        "adapters": "Hexagonal Architecture",
        "ports": "Hexagonal Architecture",
        "aggregates": "Domain-Driven Design",
        "entities": "DDD / Clean Architecture",
        "events": "Event-Driven Architecture",
        "consumers": "Event-Driven Architecture",
        "producers": "Event-Driven Architecture",
        "workers": "Worker Architecture",
        "nodes": "Agent / Graph Architecture",
        "agents": "Multi-Agent Architecture",
        "tools": "Agent Architecture",
        "chains": "LangChain Architecture",
        "graphs": "Graph Architecture",
    }

    # ─── Common Entry Points ──────────────────────────────────────────────────

    ENTRY_POINT_CANDIDATES: list[str] = [
        "main.py", "app.py", "run.py", "server.py", "wsgi.py", "asgi.py",
        "manage.py", "cli.py", "__main__.py",
        "src/main.py", "src/app.py",
        "main.go", "cmd/main.go",
        "main.rs", "src/main.rs",
        "index.js", "index.ts", "server.js", "server.ts", "app.js", "app.ts",
        "Program.cs", "Startup.cs",
    ]

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()
        self._findings: list[Finding] = []

    # ─── Public API ───────────────────────────────────────────────────────────

    def discover(self) -> RepoProfile:
        """
        Run full deterministic discovery.
        Returns a RepoProfile populated with evidence-backed findings.
        """
        print("🔍 Starting repository discovery...")

        name = self.repo_path.name
        languages = self._detect_languages()
        primary_language = self._infer_primary_language(languages)
        package_managers = self._detect_package_managers()
        frameworks, databases, caching, message_queues, testing_frameworks = self._analyze_dependencies()
        deployment = self._detect_deployment()
        has_docker = "Docker" in deployment
        ci_cd = self._detect_ci_cd()
        entry_points = self._detect_entry_points()
        has_tests = self._detect_has_tests(testing_frameworks)
        architecture_style = self._infer_architecture_style()
        architecture_documented = self._detect_documented_architecture()

        profile = RepoProfile(
            name=name,
            repo_path=str(self.repo_path),
            detected_languages=sorted(languages),
            primary_language=primary_language,
            package_managers=package_managers,
            frameworks=frameworks,
            databases=databases,
            caching=caching,
            message_queues=message_queues,
            external_services=[],
            architecture_style_observed=architecture_style,
            architecture_style_documented=architecture_documented,
            deployment=deployment,
            testing_frameworks=testing_frameworks,
            ci_cd=ci_cd,
            entry_points=entry_points,
            has_docker=has_docker,
            has_tests=has_tests,
            findings=self._findings,
        )

        print("✅ Repository discovery complete")
        return profile

    # ─── Language Detection ───────────────────────────────────────────────────

    def _detect_languages(self) -> set[str]:
        from src.helpers.language_detector import LanguageDetector
        detector = LanguageDetector()
        languages: set[str] = set()

        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in _IGNORED_DIRS]
            for filename in files:
                rel = os.path.relpath(os.path.join(root, filename), self.repo_path)
                lang = detector.detect(rel)
                if lang:
                    languages.add(lang)

        return languages

    def _infer_primary_language(self, languages: set[str]) -> str | None:
        priority = [
            "python", "typescript", "javascript", "java",
            "go", "rust", "csharp", "cpp", "php",
        ]
        for lang in priority:
            if lang in languages:
                return lang
        return next(iter(languages), None)

    # ─── Package Managers ─────────────────────────────────────────────────────

    def _detect_package_managers(self) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for filename, pm_name in self.PACKAGE_MANAGER_FILES.items():
            if (self.repo_path / filename).exists() and pm_name not in seen:
                found.append(pm_name)
                seen.add(pm_name)
                self._finding(
                    category="package_manager",
                    observation=f"Package manager: {pm_name}",
                    evidence=f"File present: {filename}",
                )
        return found

    # ─── Dependency Analysis ──────────────────────────────────────────────────

    def _analyze_dependencies(self) -> tuple[
        list[TechnologyEntry],
        list[TechnologyEntry],
        list[TechnologyEntry],
        list[TechnologyEntry],
        list[str],
    ]:
        raw_deps: dict[str, str] = {}

        # Python
        for fname, parser in [
            ("requirements.txt", self._parse_requirements_txt),
            ("pyproject.toml", self._parse_pyproject_toml),
            ("setup.py", self._parse_setup_py),
        ]:
            path = self.repo_path / fname
            if path.exists():
                raw_deps.update(parser(path))

        # JavaScript / TypeScript
        pkg_path = self.repo_path / "package.json"
        if pkg_path.exists():
            raw_deps.update(self._parse_package_json(pkg_path))

        # Rust
        cargo_path = self.repo_path / "Cargo.toml"
        if cargo_path.exists():
            raw_deps.update(self._parse_cargo_toml(cargo_path))

        # Go
        gomod_path = self.repo_path / "go.mod"
        if gomod_path.exists():
            raw_deps.update(self._parse_go_mod(gomod_path))

        # Fallback: scan venv if no manifest was found
        if not raw_deps:
            raw_deps.update(self._parse_venv_packages())

        frameworks: list[TechnologyEntry] = []
        databases: list[TechnologyEntry] = []
        caching: list[TechnologyEntry] = []
        queues: list[TechnologyEntry] = []
        testing: list[str] = []
        seen_names: set[str] = set()

        all_tech = {
            **{k: (v[0], v[1], v[2]) for k, v in self.PYTHON_TECH.items()},
            **{k: (v[0], v[1], v[2]) for k, v in self.JS_TECH.items()},
        }

        for dep_raw, version in raw_deps.items():
            dep_lower = dep_raw.lower()
            dep_dashed = dep_lower.replace("_", "-")
            dep_underscored = dep_lower.replace("-", "_")

            match_result = None
            for key, (display_name, purpose, category) in all_tech.items():
                if dep_lower == key or dep_dashed == key or dep_underscored == key:
                    match_result = (display_name, purpose, category, version or None, dep_raw)
                    break

            if match_result is None:
                continue

            display_name, purpose, category, ver, evidence_dep = match_result
            if display_name in seen_names:
                continue
            seen_names.add(display_name)

            entry = TechnologyEntry(
                name=display_name,
                purpose=purpose,
                version=ver if ver else None,
                evidence=f"dependency: {evidence_dep}",
            )

            if category == "testing":
                testing.append(display_name)
            elif category == "cache":
                caching.append(entry)
            elif category in ("database", "vector_db"):
                databases.append(entry)
            elif category == "queue":
                queues.append(entry)
            else:
                frameworks.append(entry)

        return frameworks, databases, caching, queues, list(dict.fromkeys(testing))

    # ─── Dependency File Parsers ──────────────────────────────────────────────

    def _parse_requirements_txt(self, path: Path) -> dict[str, str]:
        deps: dict[str, str] = {}
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                m = re.match(r"^([a-zA-Z0-9_\-\.]+)([>=<!~^,\s].*)?", line)
                if m:
                    deps[m.group(1)] = (m.group(2) or "").strip()
        except Exception as e:
            self._finding("parse_error", f"Could not parse requirements.txt: {e}", str(path), severity="warning")
        return deps

    def _parse_pyproject_toml(self, path: Path) -> dict[str, str]:
        deps: dict[str, str] = {}
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)

            # Poetry
            for name, ver in data.get("tool", {}).get("poetry", {}).get("dependencies", {}).items():
                if name.lower() == "python":
                    continue
                deps[name] = ver if isinstance(ver, str) else (ver.get("version", "") if isinstance(ver, dict) else "")

            # PEP 621
            for dep in data.get("project", {}).get("dependencies", []):
                if isinstance(dep, str):
                    m = re.match(r"^([a-zA-Z0-9_\-\.]+)([>=<!~^].*)?", dep)
                    if m:
                        deps[m.group(1)] = (m.group(2) or "").strip()
        except Exception as e:
            self._finding("parse_error", f"Could not parse pyproject.toml: {e}", str(path), severity="warning")
        return deps

    def _parse_setup_py(self, path: Path) -> dict[str, str]:
        deps: dict[str, str] = {}
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"install_requires\s*=\s*\[(.*?)\]", text, re.DOTALL)
            if m:
                for item in re.findall(r"['\"]([^'\"]+)['\"]", m.group(1)):
                    pm = re.match(r"^([a-zA-Z0-9_\-\.]+)([>=<!~^].*)?", item)
                    if pm:
                        deps[pm.group(1)] = (pm.group(2) or "").strip()
        except Exception:
            pass
        return deps

    def _parse_package_json(self, path: Path) -> dict[str, str]:
        deps: dict[str, str] = {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for section in ("dependencies", "devDependencies", "peerDependencies"):
                for name, ver in data.get(section, {}).items():
                    if name.startswith("@types/"):
                        continue
                    deps.setdefault(name, ver)
        except Exception:
            pass
        return deps

    def _parse_cargo_toml(self, path: Path) -> dict[str, str]:
        deps: dict[str, str] = {}
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
            for name, ver in data.get("dependencies", {}).items():
                deps[name] = ver if isinstance(ver, str) else (ver.get("version", "") if isinstance(ver, dict) else "")
        except Exception:
            pass
        return deps

    def _parse_go_mod(self, path: Path) -> dict[str, str]:
        deps: dict[str, str] = {}
        try:
            for match in re.finditer(r"^\s+(\S+)\s+(v\S+)", path.read_text(encoding="utf-8"), re.MULTILINE):
                module = match.group(1).split("/")[-1]
                deps[module] = match.group(2)
        except Exception:
            pass
        return deps

    # ─── Deployment & CI/CD ───────────────────────────────────────────────────

    def _detect_deployment(self) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for indicator, tech in self.DEPLOYMENT_INDICATORS.items():
            if (self.repo_path / indicator).exists() and tech not in seen:
                found.append(tech)
                seen.add(tech)
                self._finding("deployment", f"Deployment technology: {tech}", f"Found: {indicator}")
        return found

    def _detect_ci_cd(self) -> list[str]:
        found: list[str] = []
        for path_str, ci_name in self.CI_CD_PATHS.items():
            if (self.repo_path / path_str).exists():
                found.append(ci_name)
                self._finding("ci_cd", f"CI/CD: {ci_name}", f"Found: {path_str}")
        return found

    # ─── Entry Points & Tests ─────────────────────────────────────────────────

    def _detect_entry_points(self) -> list[str]:
        return [ep for ep in self.ENTRY_POINT_CANDIDATES if (self.repo_path / ep).exists()]

    def _detect_has_tests(self, testing_frameworks: list[str]) -> bool:
        if testing_frameworks:
            return True
        for td in ("tests", "test", "spec", "__tests__", "e2e"):
            p = self.repo_path / td
            if p.is_dir():
                try:
                    return any(True for _ in p.iterdir())
                except Exception:
                    pass
        return False

    # ─── Architecture Inference ───────────────────────────────────────────────

    def _infer_architecture_style(self) -> str | None:
        folder_names: set[str] = set()
        try:
            for item in self.repo_path.iterdir():
                if item.is_dir() and item.name not in _IGNORED_DIRS:
                    folder_names.add(item.name.lower())
            src_path = self.repo_path / "src"
            if src_path.is_dir():
                for item in src_path.iterdir():
                    if item.is_dir() and item.name not in _IGNORED_DIRS:
                        folder_names.add(item.name.lower())
        except Exception:
            return None

        matched: list[str] = [
            pattern
            for folder, pattern in self.ARCHITECTURE_FOLDER_HINTS.items()
            if folder in folder_names
        ]

        if not matched:
            return None

        # Agent architecture is highly specific — prioritize it
        agent_signals = {"Agent / Graph Architecture", "Multi-Agent Architecture", "Agent Architecture"}
        if agent_signals & set(matched):
            return "Agent Architecture (LangGraph / stateful graph)"

        # Count style votes
        votes: dict[str, int] = {}
        for pattern in matched:
            for style in pattern.split("/"):
                style = style.strip()
                votes[style] = votes.get(style, 0) + 1

        return max(votes, key=lambda k: votes[k]) if votes else None

    def _detect_documented_architecture(self) -> str | None:
        for readme in ("README.md", "README.rst", "README.txt", "README"):
            p = self.repo_path / readme
            if p.exists():
                try:
                    text = p.read_text(encoding="utf-8", errors="replace").lower()
                    if not text.strip():
                        return None
                    keywords = [
                        "clean architecture", "hexagonal", "onion architecture",
                        "microservices", "monolith", "cqrs", "event-driven",
                        "mvc", "mvvm", "layered architecture",
                        "domain-driven", "ddd", "repository pattern",
                        "agent architecture", "rag",
                    ]
                    for kw in keywords:
                        if kw in text:
                            return kw.title()
                except Exception:
                    pass
        return None

    # ─── Helpers ──────────────────────────────────────────────────────────────


    def _parse_venv_packages(self) -> dict[str, str]:
        """
        Fallback: read installed packages from a local venv when no manifest exists.
        Emits a finding about the missing requirements file.
        """
        import glob as _glob
        import subprocess

        # Look for a venv directory
        venv_candidates = ["venv", ".venv", "env", ".env"]
        venv_path = None
        for candidate in venv_candidates:
            p = self.repo_path / candidate
            if p.is_dir() and (p / "lib").exists():
                venv_path = p
                break

        if venv_path is None:
            return {}

        self._finding(
            category="missing_manifest",
            observation="No dependency manifest found (requirements.txt, pyproject.toml, setup.py). "
                        "Falling back to installed venv packages.",
            evidence=f"venv found at: {venv_path.name}/, no requirements.txt",
            severity="warning",
        )

        # Try pip freeze from the venv
        pip_candidates = [
            str(venv_path / "bin" / "pip"),
            str(venv_path / "bin" / "pip3"),
        ]
        deps: dict[str, str] = {}
        for pip_bin in pip_candidates:
            if not os.path.exists(pip_bin):
                continue
            try:
                result = subprocess.run(
                    [pip_bin, "freeze"],
                    capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        line = line.strip()
                        if "==" in line:
                            name, version = line.split("==", 1)
                            deps[name] = version
                    return deps
            except Exception:
                continue

        return deps

    def _finding(
        self,
        category: str,
        observation: str,
        evidence: str,
        severity: str | None = None,
    ) -> None:
        self._findings.append(Finding(
            category=category,
            observation=observation,
            evidence=evidence,
            source="observed",
            severity=severity,  # type: ignore[arg-type]
        ))
