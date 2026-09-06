from langgraph.graph import StateGraph, START, END
from state import AgentState
from helpers.repo import clone_repo
from helpers.file_tree import get_file_tree 

def repository_loader(state: AgentState):
    print("Repository Loader running 📦 ...")
        
    state["repo_path"] = clone_repo(state["url"]) 
    state["file_tree"] = get_file_tree(state["repo_path"])

    return state

def investigator (state : AgentState):
    print("Investigator running 🕵️‍♂️🕵️‍♂️ ... ")
    return state 

def coder (state : AgentState):
    print("coder running 👨‍💻👨‍💻 ... ")
    return state 


def tester (state :AgentState):
    print("tester running 👨‍💻👨‍💻 ... ")
    return state 


graph = StateGraph(AgentState)

graph.add_node( "repository_loader" , repository_loader)
graph.add_node( "investigator" , investigator)
graph.add_node("coder" , coder)
graph.add_node("tester", tester)

graph.add_edge(START, "repository_loader")
graph.add_edge("repository_loader" , "investigator" )
graph.add_edge("investigator", "coder")
graph.add_edge("coder", "tester")
graph.add_edge("tester", END)


myapp = graph.compile()

