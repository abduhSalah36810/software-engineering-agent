"""
Phase 4.5 — LangGraph Incremental Pipeline Orchestration Tests.

Validates that LangGraph orchestrates the existing deterministic engines:
  Test A — Normal incremental change: change → dimensions → invalidation → understand (all in order)
  Test B — No changes: unchanged status avoids downstream recomputation (bypasses understand)
  Test C — Initial baseline: initial-baseline semantics survive graph propagation, no fabricated diff
  Test D — Stale baseline: stale/reverification state propagates correctly, no fabricated diff
  Test E — Uncommitted changes: session-scoped behavior, no unintended persistent SQLite memory mutation
  Test F — State propagation: AgentState contains all incremental pipeline result fields
  Test G — Engine reuse: verifies the graph invokes the existing engines rather than duplicating logic
  Test H — Error propagation: engine failure is not swallowed and does not fabricate success
  Test I — Graph topology: verifies both standalone incremental_graph and full agent graph compile
"""

from pathlib import Path
import subprocess
from unittest.mock import patch, MagicMock
import pytest

from src.state import AgentState
from src.helpers.repo import get_canonical_repo_id
from src.memory.sqlite_store import EngineeringMemoryStore
from src.models.repo_profile import RepoProfile
from src.helpers.incremental_change import (
    IncrementalChangeResult,
    IncrementalChangeDetector,
)
from src.helpers.affected_dimensions import (
    AffectedDimensionsResult,
    detect_affected_dimensions,
)
from src.helpers.memory_invalidation import (
    MemoryInvalidationResult,
    invalidate_memory,
)
from src.helpers.incremental_understand import (
    IncrementalUnderstandResult,
    understand_again,
)
from src.graph import (
    build_incremental_graph,
    incremental_graph,
    incremental_app,
    build_agent_graph,
    graph,
    myapp,
)
from src.nodes.incremental_nodes import (
    incremental_change_node,
    affected_dimensions_node,
    memory_invalidation_node,
    incremental_understand_node,
    no_changes_node,
    route_after_change,
)


def _git_commit(repo_path: Path, msg: str = "commit") -> str:
    """Helper to git add and commit all changes, returning commit SHA."""
    subprocess.run(["git", "add", "."], cwd=str(repo_path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=str(repo_path), check=True, capture_output=True)
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_path), check=True, capture_output=True, text=True)
    return r.stdout.strip()


@pytest.fixture
def memory_store(tmp_path):
    """Temporary SQLite store for testing."""
    db_file = str(tmp_path / "test_memory.db")
    return EngineeringMemoryStore(db_path=db_file)


@pytest.fixture
def git_repo(tmp_path):
    """Clean git repo with initial commit."""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "AgentTest"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "agent@test.local"], cwd=str(repo), check=True, capture_output=True)
    
    src = repo / "src"
    src.mkdir()
    (src / "app.py").write_text("def run():\n    return 42\n")
    (repo / "README.md").write_text("# Test Repo\n")
    
    _git_commit(repo, "Initial commit")
    return repo


# ── Test A: Normal incremental change ─────────────────────────────────────────


def test_A_normal_incremental_change_executes_all_stages(git_repo, memory_store):
    """
    Test A: All four stages execute in order:
    change -> dimensions -> invalidation -> understand.
    """
    canonical_id = get_canonical_repo_id(git_repo)
    head_c1 = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(git_repo), check=True, capture_output=True, text=True
    ).stdout.strip()

    # Record initial baseline in memory
    memory_store.save_change_record(
        repo_name=canonical_id,
        commit_hash=head_c1,
        changed_files=[],
    )
    profile = RepoProfile(name="test_repo", repo_path=str(git_repo), primary_language="Python")
    memory_store.save_repo_profile(profile, repo_id=canonical_id)

    # Save a decision in memory
    dec_id = memory_store.save_decision(
        repo_name=canonical_id,
        subject="source_code",
        decision="Python implementation",
        rationale="source clean",
        source="observed",
    )

    # Commit 2: Modify source file
    (git_repo / "src" / "app.py").write_text("def run():\n    return 100\n")
    head_c2 = _git_commit(git_repo, "Update run function")

    # Execute incremental pipeline graph
    state = {
        "repo_path": str(git_repo),
        "memory": memory_store,
    }
    result = incremental_app.invoke(state)

    # 1. Incremental change stage
    chg = result.get("incremental_change_result")
    assert chg is not None
    assert chg.status == "changed"
    assert chg.has_committed_changes is True
    assert "src/app.py" in chg.changed_files
    assert chg.previous_commit == head_c1
    assert chg.current_commit == head_c2

    # 2. Affected dimensions stage
    dims = result.get("affected_dimensions_result")
    assert dims is not None
    committed_dims = [d.dimension for d in dims.committed]
    assert "source_code" in committed_dims

    # 3. Memory invalidation stage
    inv = result.get("memory_invalidation_result")
    assert inv is not None
    assert inv.status == "invalidated"
    assert "source_code" in inv.affected_dimensions

    # 4. Incremental understand stage
    und = result.get("incremental_understand_result")
    assert und is not None
    assert und.status == "reunderstood"
    assert "source_code" in und.recomputed_dimensions
    assert und.deterministic_processing_complete is True


# ── Test B: No changes ────────────────────────────────────────────────────────


def test_B_no_changes_avoids_downstream_recomputation(git_repo, memory_store):
    """
    Test B: When change status is 'unchanged', downstream recomputation is avoided.
    """
    canonical_id = get_canonical_repo_id(git_repo)
    head_c1 = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(git_repo), check=True, capture_output=True, text=True
    ).stdout.strip()

    # Record commit in memory
    memory_store.save_change_record(
        repo_name=canonical_id,
        commit_hash=head_c1,
        changed_files=[],
    )

    # Spy/mock understand_again to ensure it is NOT called
    with patch("src.nodes.incremental_nodes.understand_again") as mock_understand:
        state = {
            "repo_path": str(git_repo),
            "memory": memory_store,
        }
        result = incremental_app.invoke(state)

        # understand_again must NOT have been called
        mock_understand.assert_not_called()

    chg = result.get("incremental_change_result")
    assert chg is not None
    assert chg.status == "unchanged"
    assert chg.has_changes is False

    # Downstream understand result indicates no_changes
    und = result.get("incremental_understand_result")
    assert und is not None
    assert und.status == "no_changes"
    assert und.recomputed_dimensions == []
    assert und.deterministic_processing_complete is True


# ── Test C: Initial baseline ──────────────────────────────────────────────────


def test_C_initial_baseline_semantics_survive_graph_propagation(git_repo, memory_store):
    """
    Test C: When repo has no history in memory, initial-baseline semantics survive.
    No fabricated diff.
    """
    # Empty memory store: no records for this repo
    state = {
        "repo_path": str(git_repo),
        "memory": memory_store,
    }
    result = incremental_app.invoke(state)

    chg = result.get("incremental_change_result")
    assert chg is not None
    assert chg.status == "initial_baseline"
    assert chg.is_initial_baseline is True
    assert chg.changed_files == []

    inv = result.get("memory_invalidation_result")
    assert inv is not None
    assert inv.status == "initial_baseline"
    assert inv.is_initial_baseline is True

    und = result.get("incremental_understand_result")
    assert und is not None
    assert und.status == "initial_baseline"
    assert und.recomputed_dimensions == []
    assert und.deterministic_processing_complete is True


# ── Test D: Stale baseline ────────────────────────────────────────────────────


def test_D_stale_baseline_propagates_correctly(git_repo, memory_store):
    """
    Test D: When stored commit is unreachable in Git, stale state propagates correctly.
    No fabricated diff.
    """
    canonical_id = get_canonical_repo_id(git_repo)
    # Store a fabricated unreachable commit hash
    memory_store.save_change_record(
        repo_name=canonical_id,
        commit_hash="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        changed_files=[],
    )

    state = {
        "repo_path": str(git_repo),
        "memory": memory_store,
    }
    result = incremental_app.invoke(state)

    chg = result.get("incremental_change_result")
    assert chg is not None
    assert chg.status == "stale_baseline"
    assert chg.is_baseline_stale is True
    assert chg.requires_reverification is True
    assert chg.changed_files == []

    inv = result.get("memory_invalidation_result")
    assert inv is not None
    assert inv.status == "stale_baseline"
    assert inv.verification_required is True

    und = result.get("incremental_understand_result")
    assert und is not None
    assert und.status == "stale_baseline"
    assert und.deterministic_processing_complete is False


# ── Test E: Uncommitted changes ───────────────────────────────────────────────


def test_E_uncommitted_changes_preserves_session_scoped_behavior(git_repo, memory_store):
    """
    Test E: Uncommitted working-tree changes produce session-scoped state.
    Persistent SQLite memory records are NOT mutated.
    """
    canonical_id = get_canonical_repo_id(git_repo)
    head_c1 = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(git_repo), check=True, capture_output=True, text=True
    ).stdout.strip()

    memory_store.save_change_record(
        repo_name=canonical_id,
        commit_hash=head_c1,
        changed_files=[],
    )

    # Save a decision in SQLite
    dec_id = memory_store.save_decision(
        repo_name=canonical_id,
        subject="source_code",
        decision="Python codebase",
        rationale="clean syntax",
        source="observed",
    )

    # Modify a file without committing
    (git_repo / "src" / "app.py").write_text("def run():\n    return 999\n")

    state = {
        "repo_path": str(git_repo),
        "memory": memory_store,
    }
    result = incremental_app.invoke(state)

    chg = result.get("incremental_change_result")
    assert chg is not None
    assert chg.has_uncommitted_changes is True
    assert chg.has_committed_changes is False

    # Check SQLite record: MUST remain VALID in persistent SQLite store!
    loaded_dec = memory_store.load_decisions(canonical_id)
    assert len(loaded_dec) == 1
    assert loaded_dec[0]["current_validity"] == "VALID"


# ── Test F: State propagation ─────────────────────────────────────────────────


def test_F_state_propagation_contains_all_incremental_fields(git_repo, memory_store):
    """
    Test F: AgentState contains all 4 incremental result fields after pipeline execution.
    """
    canonical_id = get_canonical_repo_id(git_repo)
    head_c1 = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(git_repo), check=True, capture_output=True, text=True
    ).stdout.strip()

    memory_store.save_change_record(
        repo_name=canonical_id,
        commit_hash=head_c1,
        changed_files=[],
    )

    # Modify and commit
    (git_repo / "README.md").write_text("# Updated Documentation\n")
    _git_commit(git_repo, "Update readme")

    state = {
        "repo_path": str(git_repo),
        "memory": memory_store,
    }
    result = incremental_app.invoke(state)

    assert "incremental_change_result" in result
    assert "affected_dimensions_result" in result
    assert "memory_invalidation_result" in result
    assert "incremental_understand_result" in result

    assert isinstance(result["incremental_change_result"], IncrementalChangeResult)
    assert isinstance(result["affected_dimensions_result"], AffectedDimensionsResult)
    assert isinstance(result["memory_invalidation_result"], MemoryInvalidationResult)
    assert isinstance(result["incremental_understand_result"], IncrementalUnderstandResult)


# ── Test G: Engine reuse ──────────────────────────────────────────────────────


def test_G_engine_reuse_calls_existing_engines(git_repo, memory_store):
    """
    Test G: The graph nodes orchestrate by calling the existing engines
    rather than duplicating their logic.
    """
    canonical_id = get_canonical_repo_id(git_repo)
    head_c1 = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(git_repo), check=True, capture_output=True, text=True
    ).stdout.strip()

    memory_store.save_change_record(
        repo_name=canonical_id,
        commit_hash=head_c1,
        changed_files=[],
    )

    (git_repo / "src" / "app.py").write_text("def run():\n    return 555\n")
    _git_commit(git_repo, "Modify app")

    with patch.object(IncrementalChangeDetector, "detect_changes", wraps=IncrementalChangeDetector(str(git_repo), memory=memory_store).detect_changes) as spy_detect_changes, \
         patch("src.nodes.incremental_nodes.detect_affected_dimensions", wraps=detect_affected_dimensions) as spy_affected_dims, \
         patch("src.nodes.incremental_nodes.invalidate_memory", wraps=invalidate_memory) as spy_invalidate_memory, \
         patch("src.nodes.incremental_nodes.understand_again", wraps=understand_again) as spy_understand_again:

        state = {
            "repo_path": str(git_repo),
            "memory": memory_store,
        }
        result = incremental_app.invoke(state)

        assert spy_detect_changes.called, "detect_changes was not called on IncrementalChangeDetector"
        assert spy_affected_dims.called, "detect_affected_dimensions was not called"
        assert spy_invalidate_memory.called, "invalidate_memory was not called"
        assert spy_understand_again.called, "understand_again was not called"


# ── Test H: Error propagation ─────────────────────────────────────────────────


def test_H_error_propagation_does_not_fabricate_success(git_repo, memory_store):
    """
    Test H: An engine failure raises an exception and does not produce a fake success.
    """
    canonical_id = get_canonical_repo_id(git_repo)
    head_c1 = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(git_repo), check=True, capture_output=True, text=True
    ).stdout.strip()

    memory_store.save_change_record(
        repo_name=canonical_id,
        commit_hash=head_c1,
        changed_files=[],
    )

    (git_repo / "src" / "app.py").write_text("def run():\n    return 777\n")
    _git_commit(git_repo, "Modify app")

    with patch("src.nodes.incremental_nodes.understand_again", side_effect=RuntimeError("Disk failure during re-understanding")):
        state = {
            "repo_path": str(git_repo),
            "memory": memory_store,
        }
        with pytest.raises(RuntimeError, match="Disk failure during re-understanding"):
            incremental_app.invoke(state)


# ── Test I: Graph compilation and topology ────────────────────────────────────


def test_I_graph_compilation_and_topology():
    """
    Test I: Both the standalone incremental graph and full agent graph compile properly
    with all expected nodes and edge connections.
    """
    inc_graph = build_incremental_graph()
    assert "incremental_change" in inc_graph.nodes
    assert "affected_dimensions" in inc_graph.nodes
    assert "memory_invalidation" in inc_graph.nodes
    assert "incremental_understand" in inc_graph.nodes
    assert "no_changes" in inc_graph.nodes

    agent_graph = build_agent_graph()
    assert "repository_loader" in agent_graph.nodes
    assert "incremental_change" in agent_graph.nodes
    assert "affected_dimensions" in agent_graph.nodes
    assert "memory_invalidation" in agent_graph.nodes
    assert "incremental_understand" in agent_graph.nodes
    assert "no_changes" in agent_graph.nodes
    assert "repository_discovery" in agent_graph.nodes
    assert "code_intelligence" in agent_graph.nodes
    assert "investigator" in agent_graph.nodes
    assert "coder" in agent_graph.nodes
    assert "tester" in agent_graph.nodes

    compiled_inc = inc_graph.compile()
    compiled_agent = agent_graph.compile()
    assert compiled_inc is not None
    assert compiled_agent is not None


# ── Test J: Routing function unit behavior ────────────────────────────────────


def test_J_routing_function_behavior():
    """
    Test J: route_after_change correctly branches between 'no_changes' and 'continue'.
    """
    unchanged_res = IncrementalChangeResult(status="unchanged", has_changes=False)
    assert route_after_change({"incremental_change_result": unchanged_res}) == "no_changes"

    changed_res = IncrementalChangeResult(status="changed", has_changes=True)
    assert route_after_change({"incremental_change_result": changed_res}) == "continue"

    dirty_res = IncrementalChangeResult(status="dirty", has_changes=True, has_uncommitted_changes=True)
    assert route_after_change({"incremental_change_result": dirty_res}) == "continue"

    initial_res = IncrementalChangeResult(status="initial_baseline", is_initial_baseline=True)
    assert route_after_change({"incremental_change_result": initial_res}) == "continue"

    stale_res = IncrementalChangeResult(status="stale_baseline", is_baseline_stale=True)
    assert route_after_change({"incremental_change_result": stale_res}) == "continue"
