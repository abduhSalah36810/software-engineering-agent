from typing  import TypedDict


class AgentState(TypedDict):
    url: str
    problem: str
    repo_path : str | None
    file_tree: str | None
    relevant_files: list[str] | None
    root_cause: str | None
    plan: str | None
    modified_files: list[str] | None
    test_output: str | None
    test_passed: bool | None