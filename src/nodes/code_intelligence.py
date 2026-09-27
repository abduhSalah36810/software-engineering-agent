from src.helpers.embedding.client import EmbeddingClient
from src.helpers.file_scanner import FileScanner
from src.helpers.language_detector import LanguageDetector
from src.helpers.qdrant.store import QdrantStore
from src.helpers.symbol_extractor import SymbolExtractor
from src.helpers.tree_parcer import CodeParser
from src.helpers.indexer import Indexer


import os

def code_intelligence(state):
    print("Code Intelligence started 🧠")

    repo_path = state.get("repo_path")
    if not repo_path or not os.path.exists(repo_path):
        print("Warning: repo_path missing or does not exist -- skipping indexing")
        return {"indexed_document_count": 0}
    repo_name = state.get("repo_name") or repo_path
    store = QdrantStore(repo_name)

    indexer = Indexer(
        scanner=FileScanner(),
        detector=LanguageDetector(),
        extractor=SymbolExtractor(CodeParser()),
        embedding_client=EmbeddingClient(),
        store=store
    )

    print("Before indexing")
    documents = indexer.index(repo_path)
    print("After indexing")

    return {
        "indexed_document_count": len(documents),
    }
