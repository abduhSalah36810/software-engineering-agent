# Software Engineering Agent

A local-first software engineering agent that understands repositories through
deterministic analysis, persistent engineering memory, and git-aware incremental updates.

## Architecture

```
START
  -> repository_loader      Clone / reuse repo; build file tree
  -> repository_discovery   Deterministic analysis -> RepoProfile -> SQLite
  -> code_intelligence      FastEmbed (local) -> Qdrant symbol index
  -> investigator           Qdrant search + SQLite memory + git context
  -> coder                  LLM tool loop (read files) -> structured analysis -> SQLite
  -> tester                 Syntax check + lint on modified files
END
```

## Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `RepoProfile` | `src/models/repo_profile.py` | Typed repository profile with evidence-tracked findings |
| `RepoDiscovery` | `src/helpers/repo_discovery.py` | Deterministic language/framework/dependency detection |
| `EngineeringMemoryStore` | `src/memory/sqlite_store.py` | SQLite-backed memory (profiles, decisions, investigations, change records) |
| `EmbeddingClient` | `src/helpers/embedding/client.py` | Local FastEmbed (BAAI/bge-small-en-v1.5, 384-dim) |
| `get_git_context` | `src/helpers/git_context.py` | Git HEAD, branch, recent commits, changed files since last analysis |
| `investigator` | `src/nodes/investigator.py` | Assembles investigation context without LLM |
| `coder` | `src/nodes/coder.py` | LLM tool loop + persists result to SQLite |
| `tester` | `src/nodes/tester.py` | py_compile + pyflakes verification |

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt   # or pip install from pyproject.toml

cp .env.example .env
# Edit .env to set PATH_TO_CLONED_REPO and QDRANT_STORAGE_PATH
```

Requires Ollama running locally with `qwen2.5-coder:1.5b-instruct-q4_S` model.

## Running Tests

```bash
python3 -m pytest tests/ -v
```

## Running the Agent (FastAPI)

```bash
uvicorn src.main:app --reload
```

POST to `/agent/run`:
```json
{
  "url": "https://github.com/ytdl-org/youtube-dl.git",
  "problem": "Describe the bug or task here"
}
```

## Engineering Memory

The agent persists knowledge across runs in `agent_memory.db` (SQLite):
- **repo_profiles** - serialized RepoProfile per repository
- **decisions** - architecture and technology decisions with source tracking
- **change_records** - per-commit observations for git-aware incremental updates
- **investigations** - past bug investigations and their outcomes

On subsequent runs for the same repository, the agent:
1. Checks git HEAD vs the last recorded commit
2. If unchanged: reuses the cached RepoProfile (skips full re-scan)
3. If changed: re-runs discovery on new/changed files only
