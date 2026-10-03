"""
LangGraph agent state.

All fields are optional except the initial inputs (url, problem).
Fields are populated progressively as the pipeline executes.

repo_profile: dict representation of RepoProfile (from repository_discovery).
              Use RepoProfile.from_dict(state["repo_profile"]) to get the typed object.

investigation: structured investigation result from the investigator node.
               Keys: root_cause, affected_components, relevant_files,
                     architectural_implications, proposed_solution, risks, confidence
"""

from typing import TypedDict


class AgentState(TypedDict):
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
