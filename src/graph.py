"""
LangGraph graph definition.

Pipelines:
  1. Full Agent Pipeline:
     START
       → repository_loader        clone repo, build file tree
       → incremental_change       detect repository evolution
           ├── [no_changes]  → no_changes ──────┐
           └── [continue]    → affected_dimensions
                                   ↓
                               memory_invalidation
                                   ↓
                               incremental_understand
                                   ↓
       → repository_discovery     cached or fresh discovery
       → code_intelligence        index symbols into Qdrant
       → investigator             structured investigation context
       → coder                    LLM root cause & code plan
       → tester                   syntax/validation checks
     END

  2. Standalone Incremental Understanding Pipeline (Phase 4.5):
     START
       → incremental_change
           ├── [no_changes]  → no_changes ───────────→ END
           └── [continue]    → affected_dimensions
                                   ↓
                               memory_invalidation
                                   ↓
                               incremental_understand ─→ END
"""

from langgraph.graph import StateGraph, START, END

from src.nodes.repository_loader import repository_loader
from src.nodes.incremental_nodes import (
    incremental_change_node,
    affected_dimensions_node,
    memory_invalidation_node,
    incremental_understand_node,
    no_changes_node,
    route_after_change,
)
from src.nodes.repository_discovery import repository_discovery
from src.nodes.code_intelligence import code_intelligence
from src.nodes.investigator import investigator
from src.nodes.coder import coder
from src.nodes.tester import tester
from src.state import AgentState


def build_incremental_graph() -> StateGraph:
    """
    Builds the deterministic incremental understanding pipeline graph (Phase 4.5).
    Follows:
      START
        ↓
      Incremental Change Detection
        ↓
      Affected Dimensions
        ↓
      Memory Invalidation
        ↓
      Incremental Understand
        ↓
      Updated Engineering State
        ↓
      END
    With fast-path short-circuit for unchanged repositories.
    """
    g = StateGraph(AgentState)

    g.add_node("incremental_change", incremental_change_node)
    g.add_node("affected_dimensions", affected_dimensions_node)
    g.add_node("memory_invalidation", memory_invalidation_node)
    g.add_node("incremental_understand", incremental_understand_node)
    g.add_node("no_changes", no_changes_node)

    g.add_edge(START, "incremental_change")
    g.add_conditional_edges(
        "incremental_change",
        route_after_change,
        {
            "continue": "affected_dimensions",
            "no_changes": "no_changes",
        },
    )
    g.add_edge("affected_dimensions", "memory_invalidation")
    g.add_edge("memory_invalidation", "incremental_understand")
    g.add_edge("incremental_understand", END)
    g.add_edge("no_changes", END)

    return g


# Compiled standalone incremental understanding workflow
incremental_graph = build_incremental_graph()
incremental_app = incremental_graph.compile()


def build_agent_graph() -> StateGraph:
    """
    Builds the full agent graph incorporating the incremental pipeline.
    """
    g = StateGraph(AgentState)

    g.add_node("repository_loader", repository_loader)
    g.add_node("incremental_change", incremental_change_node)
    g.add_node("affected_dimensions", affected_dimensions_node)
    g.add_node("memory_invalidation", memory_invalidation_node)
    g.add_node("incremental_understand", incremental_understand_node)
    g.add_node("no_changes", no_changes_node)
    g.add_node("repository_discovery", repository_discovery)
    g.add_node("code_intelligence", code_intelligence)
    g.add_node("investigator", investigator)
    g.add_node("coder", coder)
    g.add_node("tester", tester)

    g.add_edge(START, "repository_loader")
    g.add_edge("repository_loader", "incremental_change")
    g.add_conditional_edges(
        "incremental_change",
        route_after_change,
        {
            "continue": "affected_dimensions",
            "no_changes": "no_changes",
        },
    )
    g.add_edge("affected_dimensions", "memory_invalidation")
    g.add_edge("memory_invalidation", "incremental_understand")
    g.add_edge("incremental_understand", "repository_discovery")
    g.add_edge("no_changes", "repository_discovery")
    g.add_edge("repository_discovery", "code_intelligence")
    g.add_edge("code_intelligence", "investigator")
    g.add_edge("investigator", "coder")
    g.add_edge("coder", "tester")
    g.add_edge("tester", END)

    return g


# Extended main agent graph and runnable app
graph = build_agent_graph()
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
