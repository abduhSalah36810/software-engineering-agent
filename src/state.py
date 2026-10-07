"""
LangGraph agent state.

All fields are optional except the initial inputs (url, problem).
Fields are populated progressively as the pipeline executes.

repo_profile: dict representation of RepoProfile (from repository_discovery).
              Use RepoProfile.from_dict(state["repo_profile"]) to get the typed object.

investigation: structured investigation result from the investigator node.
               Keys: root_cause, affected_components, relevant_files,
                     architectural_implications, proposed_solution, risks, confidence

incremental_change_result: IncrementalChangeResult or dict from incremental change detection.
affected_dimensions_result: AffectedDimensionsResult or dict of touched dimensions.
memory_invalidation_result: MemoryInvalidationResult or dict of invalidated knowledge items.
incremental_understand_result: IncrementalUnderstandResult or dict of re-understood dimensions.
"""

from typing import TypedDict, Any


class AgentState(TypedDict, total=False):
    # ── Inputs ──────────────────────────────────────────────────────────────
    url: str
    problem: str

    # ── Repository loader ────────────────────────────────────────────────────
    repo_path: str | None
    repo_name: str | None
    repo_id: str | None
    file_tree: str | None

    # ── Repository discovery (Phase 1) ───────────────────────────────────────
    repo_profile: dict | None

    # ── Investigation ────────────────────────────────────────────────────────
    retrieved_chunks: list[dict] | None
    investigation: dict | None          # structured output from investigator

    # ── Coder output ─────────────────────────────────────────────────────────
    root_cause: str | None
    plan: str | None
    modified_files: list[str] | None

    # ── Tester output ────────────────────────────────────────────────────────
    test_output: str | None
    test_passed: bool | None

    # ── Incremental Pipeline (Phase 4.5) ─────────────────────────────────────
    incremental_change_result: Any | None
    affected_dimensions_result: Any | None
    memory_invalidation_result: Any | None
    incremental_understand_result: Any | None
    since_commit: str | None
    memory: Any | None
