"""
coder node

Uses investigation context (repo profile, retrieved code, git state, past investigations)
to drive an LLM-powered tool loop that:
  1. Reads actual files before deciding anything
  2. Produces a structured CoderAnalysis (root_cause, plan, files_to_modify)
  3. Persists the investigation result to SQLite engineering memory under canonical repo_id

Tool loop is capped at 5 iterations to prevent runaway calls.
"""

import json
from pathlib import Path
from src.state import AgentState
from src.helpers.llm import llm
from src.tools.file_operations import read_file
from src.helpers.repo import get_canonical_repo_id
from src.memory.sqlite_store import EngineeringMemoryStore

from pydantic import BaseModel
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, ToolMessage


class CoderAnalysis(BaseModel):
    root_cause: str
    plan: str
    files_to_modify: list[str]


def coder(state: AgentState) -> dict:
    print("Coder running...")

    problem = state["problem"]
    repo_path = state.get("repo_path", "")
    repo_id = state.get("repo_id") or (get_canonical_repo_id(repo_path) if repo_path else "unknown")
    investigation = state.get("investigation") or {}
    retrieved_chunks = state.get("retrieved_chunks") or []

    # ── Gather context ────────────────────────────────────────────────────
    retrieved_chunks_text = "\n\n".join(
        f"[{c.get('file', '?')} | {c.get('symbol', '?')} | {c.get('type', '?')}]\n{c.get('content', '')}"
        for c in retrieved_chunks
    )

    repo_profile_summary = investigation.get("repo_profile_summary", "Not available")

    git_info = investigation.get("git", {})
    git_text = (
        f"Branch: {git_info.get('branch', 'N/A')}\n"
        f"HEAD: {git_info.get('head_commit', 'N/A')}\n"
        f"Recent commits:\n" +
        "\n".join(
            f"  {c['hash']}: {c['message']}"
            for c in git_info.get("recent_commits", [])[:5]
        )
    )

    past_inv_text = ""
    past = investigation.get("past_investigations", [])
    if past:
        past_inv_text = "\nPast investigations on this repository:\n" + "\n".join(
            f"  - [{p.get('created_at', '')}] {p.get('problem', '')} -> {p.get('root_cause', 'N/A')}"
            for p in past[:3]
        )

    # ── Tool definition ───────────────────────────────────────────────────
    @tool
    def read_repo_file(file_path: str) -> str:
        """Read a file from the repository using a repository-relative path."""
        return read_file.invoke({"repo_path": repo_path, "file_path": file_path})

    tool_llm = llm.bind_tools([read_repo_file])

    prompt = f"""You are a software engineer investigating a real bug in a repository.

REPOSITORY PROFILE:
{repo_profile_summary}

GIT STATE:
{git_text}
{past_inv_text}

PROBLEM:
{problem}

RELEVANT CODE RETRIEVED:
{retrieved_chunks_text}

You have access to a tool:
  read_repo_file(file_path)

Use it to inspect actual file contents before deciding the root cause.
- file_path must be relative to the repository root.
- Do not invent file contents.
- If retrieved code is insufficient, use read_repo_file.
- Do not modify any files yet.

Goal: Identify the actual root cause, a concrete fix plan, and which files to modify.
"""

    messages = [HumanMessage(content=prompt)]

    # ── Tool loop (max 5 iterations) ───────────────────────────────────────
    for iteration in range(5):
        response = tool_llm.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            print(f"  Coder: tool loop finished after {iteration + 1} iterations")
            break

        for tool_call in response.tool_calls:
            if tool_call["name"] == "read_repo_file":
                result = read_repo_file.invoke(tool_call["args"])
                messages.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))
                print(f"  Coder: read file {tool_call['args'].get('file_path', '?')}")

    # ── Structured output ─────────────────────────────────────────────────
    final_prompt = f"""Based on the investigation below, produce the final analysis.

Problem: {problem}

Investigation conversation:
{chr(10).join(str(m) for m in messages)}

Return:
- root_cause: precise technical description of the bug
- plan: concrete step-by-step fix plan
- files_to_modify: list of repository-relative file paths to change

Ground every claim in evidence from the investigation above.
Do not invent information.
"""

    structured_llm = llm.with_structured_output(CoderAnalysis)
    analysis = structured_llm.invoke(final_prompt)

    print("\nRoot Cause:", analysis.root_cause)
    print("\nPlan:", analysis.plan)
    print("\nFiles:", analysis.files_to_modify)

    # ── Persist to engineering memory using canonical repo_id ──────────────
    memory = EngineeringMemoryStore()
    memory.save_investigation(
        repo_name=repo_id,
        problem=problem,
        root_cause=analysis.root_cause,
        plan=analysis.plan,
        result={
            "files_to_modify": analysis.files_to_modify,
            "git_head": investigation.get("git", {}).get("head_commit"),
        },
    )
    print("Investigation saved to engineering memory")

    return {
        "root_cause": analysis.root_cause,
        "plan": analysis.plan,
        "modified_files": analysis.files_to_modify,
    }
