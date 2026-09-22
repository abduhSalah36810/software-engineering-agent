from src.state import AgentState
from src.helpers.llm import llm
from src.tools.file_operations import read_file

from pydantic import BaseModel
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, ToolMessage


class CoderAnalysis(BaseModel):
    root_cause: str
    plan: str
    files_to_modify: list[str]


def coder(state: AgentState):
    print("coder running 👨‍💻👨‍💻 ... ")

    problem = state["problem"]
    retrieved_chunks = state["retrieved_chunks"]
    repo_path = state["repo_path"]

    retrieved_chunks_text = "\n".join(
        str(chunk) for chunk in retrieved_chunks
    )

    @tool
    def read_repo_file(file_path: str) -> str:
        """Read a file from the repository using a repository-relative path."""

        return read_file.invoke({
            "repo_path": repo_path,
            "file_path": file_path
        })

    tool_llm = llm.bind_tools([read_repo_file])

    prompt = f"""
You are a software engineer investigating a real bug.

Problem:
{problem}

Relevant code retrieved from the repository:
{retrieved_chunks_text}

You have access to a tool:

read_repo_file(file_path)

Use this tool when you need to inspect the actual contents of a file
before deciding the root cause or fix.

Important:
- file_path must be relative to the repository root.
- Do not invent file contents.
- Do not assume the retrieved chunks contain everything you need.
- If the retrieved code is insufficient, use read_repo_file.
- Do not modify any files yet.

Your goal is to investigate the bug and determine:
1. The actual root cause.
2. A concrete fix plan.
3. Which files need modification.
"""

    messages = [
        HumanMessage(content=prompt)
    ]

    # Allow the LLM to use tools
    for _ in range(3):

        response = tool_llm.invoke(messages)

        messages.append(response)

        # No tool call -> LLM finished investigating
        if not response.tool_calls:
            break

        for tool_call in response.tool_calls:

            if tool_call["name"] == "read_repo_file":

                result = read_repo_file.invoke(
                    tool_call["args"]
                )

                messages.append(
                    ToolMessage(
                        content=result,
                        tool_call_id=tool_call["id"]
                    )
                )

    # Now ask for the final structured analysis
    final_prompt = f"""
Based on the investigation below, produce the final analysis.

Problem:
{problem}

Investigation:
{messages}

Return:
- root_cause
- plan
- files_to_modify

Do not invent information that was not supported by the repository investigation.
"""

    structured_llm = llm.with_structured_output(CoderAnalysis)

    analysis = structured_llm.invoke(final_prompt)

    state["root_cause"] = analysis.root_cause
    state["plan"] = analysis.plan
    state["modified_files"] = analysis.files_to_modify

    print("\nRoot Cause:")
    print(analysis.root_cause)

    print("\nPlan:")
    print(analysis.plan)

    print("\nFiles to modify:")
    print(analysis.files_to_modify)

    return state

