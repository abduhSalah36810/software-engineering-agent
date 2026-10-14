# Hybrid Engineering Workspace — Frontend (Phase FE-1B)

Read-only web interface for the AI Software Engineering Agent, centered on **Maintained Engineering State**, incremental repository intelligence, and deterministic code health diagnostics.

---

## 🌟 Capabilities & Features

1. **Target Repository Selector**:
   - Dynamic path input supporting relative and absolute filesystem paths.
   - Quick presets for current workspace (`.`) and sample repository (`./repos/youtube-dl`).
   - Client-side validation and dual action triggers (Standard Overview vs Full Code Assessment).

2. **Repository Identity & Stored Profile**:
   - Canonical repository ID and real filesystem path.
   - Detected programming languages, package managers, and entry points.
   - Docker containerization and test suite detection.
   - Technology ecosystem (frameworks and databases with versions and purposes).
   - Evidence-backed findings with severity badges and category tags.

3. **Git Revision & Working-Tree Reality**:
   - Active branch name and HEAD commit hash.
   - Working-tree clean/dirty status pill.
   - Collapsible list of uncommitted modified/untracked files.
   - Recent commit evolution log.

4. **Incremental Intelligence & Dimensions Drilldown**:
   - Evolution status badge (`unchanged`, `dirty`, `changed`, `stale_baseline`, `initial_baseline`).
   - Baseline commit anchor vs current HEAD comparison.
   - Touched committed vs working-tree engineering dimensions (`ARCHITECTURE`, `DATABASE`, `TESTING`, etc.).
   - Evidence file breakdown with reasoning for each touched dimension.

5. **Maintained Engineering Memory**:
   - Persisted architectural decisions count.
   - Persisted bug investigations count.
   - Tri-state validity breakdown: `VALID`, `REQUIRES_VERIFICATION`, and `INVALID`.
   - Stale baseline anchor detection warning.

6. **Deterministic Assessment & Code Health**:
   - Inferred project stage (`IDEA`, `EARLY`, `MID`, `LATE`, `MATURE`) and certainty level (`HIGH`, `MEDIUM`, `LOW`).
   - Supporting evidence signals and contradicting friction points.
   - Python AST syntax and import error diagnostics.
   - Unassessed state with on-demand "Run Full Code Assessment" trigger (`include_assessment=true`).

---

## 🚀 Running Locally

### 1. Start the Backend API Server
In the root directory, activate the Python virtual environment and launch FastAPI:
```bash
./venv/bin/uvicorn src.main:app --reload --host 127.0.0.1 --port 8000
```

### 2. Start the Frontend Development Server
From the `frontend/` directory:
```bash
cd frontend
export PATH="$HOME/.local/bin:$PATH"  # If using standalone WSL Node
npm run dev
```
The application will open on `http://localhost:5173`. Vite proxies `/api` requests directly to `http://localhost:8000`.

### 3. Build for Production & Lint
```bash
npm run build   # Type-checks with tsc -b and bundles with Vite
npm run lint    # Runs oxlint
```

---

## 🔒 Security & Architectural Principles
- **Read-Only**: Zero terminal execution, zero code mutations, zero SQLite writes, zero git commits.
- **Deterministic**: Displays only verified facts returned from the repository and SQLite store; zero hallucinations or LLM calls in the read path.
- **Configurable**: Defaults to local dev server with Vite proxy; backend base URL customizable via `VITE_API_BASE_URL`.
