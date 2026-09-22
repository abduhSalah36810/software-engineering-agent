"""
Qdrant collection management.

VECTOR_SIZE must match the model used in src/helpers/embedding/client.py.
Current model: BAAI/bge-small-en-v1.5 → 384 dimensions.

If a collection exists with a different vector size, it is automatically
recreated. This handles migration when the embedding model changes.
"""

import re
from qdrant_client.models import Distance, VectorParams
from src.helpers.qdrant.client import get_qdrant_client

# Matches EmbeddingClient.VECTOR_SIZE in helpers/embedding/client.py
VECTOR_SIZE = 384


def extract_repo_name(repo_identifier: str) -> str:
    """
    Extracts a clean repository name from a path, URL, or identifier.

    Examples:
        "./repos/youtube-dl"           -> "youtube-dl"
        "https://github.com/org/repo.git" -> "repo"
        "youtube-dl"                   -> "youtube-dl"
    """
    if not repo_identifier or not isinstance(repo_identifier, str):
        raise ValueError("repo_identifier must be a non-empty string")

    clean = repo_identifier.strip().rstrip("/\\")
    name = clean.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


def get_collection_name(repo_identifier: str) -> str:
    """
    Derives a deterministic, safe Qdrant collection name.

    Examples:
        "youtube-dl"  -> "code_documents_youtube_dl"
        "Zad-AI"      -> "code_documents_Zad_AI"
    """
    repo_name = extract_repo_name(repo_identifier)
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", repo_name)
    return f"code_documents_{sanitized}"


def create_collection(collection_name: str) -> None:
    """
    Creates a Qdrant collection for the given name if it does not exist.

    If a collection with the same name exists but has a different vector
    dimension (e.g. after changing the embedding model), the old collection
    is deleted and recreated with the correct dimension.
    """
    client = get_qdrant_client()

    try:
        info = client.get_collection(collection_name)
        existing_size = info.config.params.vectors.size

        if existing_size != VECTOR_SIZE:
            print(
                f"⚠️  Collection '{collection_name}' has vector size {existing_size}, "
                f"expected {VECTOR_SIZE}. Recreating with correct dimensions..."
            )
            client.delete_collection(collection_name)
            # Fall through to creation below
        else:
            print(f"Collection '{collection_name}' already exists ✅")
            return
    except Exception:
        # Collection does not exist — proceed to create
        pass

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(
            size=VECTOR_SIZE,
            distance=Distance.COSINE,
        ),
    )
    print(f"Collection '{collection_name}' created ✅")
