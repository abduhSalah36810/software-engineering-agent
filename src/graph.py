"""
LangGraph graph definition.

Current pipeline (Phase 0 + Phase 1):
  START
    → repository_loader      clone repo, build file tree
    → repository_discovery   deterministic analysis → RepoProfile → SQLite
    → code_intelligence      index symbols into Qdrant (FastEmbed)
    → investigator           semantic search
    → coder                  LLM investigation + structured output
    → tester                 (stub — Phase 3 target)
  END
"""

from langgraph.graph import StateGraph, START, END

from src.nodes.repository_loader import repository_loader
from src.nodes.repository_discovery import repository_discovery
from src.nodes.code_intelligence import code_intelligence
from src.nodes.investigator import investigator
from src.nodes.coder import coder
from src.nodes.tester import tester
from src.state import AgentState

graph = StateGraph(AgentState)

graph.add_node("repository_loader", repository_loader)
graph.add_node("repository_discovery", repository_discovery)
graph.add_node("code_intelligence", code_intelligence)
graph.add_node("investigator", investigator)
graph.add_node("coder", coder)
graph.add_node("tester", tester)

graph.add_edge(START, "repository_loader")
graph.add_edge("repository_loader", "repository_discovery")
graph.add_edge("repository_discovery", "code_intelligence")
graph.add_edge("code_intelligence", "investigator")
graph.add_edge("investigator", "coder")
graph.add_edge("coder", "tester")
graph.add_edge("tester", END)

myapp = graph.compile()

if __name__ == "__main__":
    state = {
        "url": "https://github.com/ytdl-org/youtube-dl.git",
        "problem": (
            "In DASH manifests, the @id of a Representation is not necessarily unique "
            "within a Period. The current implementation assumes that format_id is unique "
            "and merges representations with the same format_id instead of keeping them "
            "as separate formats. Investigate the bug and determine the root cause and correct fix."
        ),
    }
    result = myapp.invoke(state)

    print("=" * 50)
    print("Pipeline finished")
    print("Root cause:", result.get("root_cause"))
    print("Plan:", result.get("plan"))
    print("Files to modify:", result.get("modified_files"))
