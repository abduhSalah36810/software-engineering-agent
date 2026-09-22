from src.helpers.embedding.client import EmbeddingClient
from src.helpers.qdrant.store import QdrantStore
from src.state import AgentState


def investigator(state: AgentState) -> dict:
    print("Investigator running 🕵️‍♂️ ...")

    repo_name = state.get("repo_name") or state["repo_path"]
    client = EmbeddingClient()
    store = QdrantStore(repo_name)

    embedding = client.embed([state["problem"]])[0]

    results = store.search(
        embedding=embedding,
        limit=5
    )

    for result in results:
        print("RETRIEVED FILE:", result.payload.get("file"))

    retrieved_chunks = [result.payload for result in results]

    return {"retrieved_chunks": retrieved_chunks}
