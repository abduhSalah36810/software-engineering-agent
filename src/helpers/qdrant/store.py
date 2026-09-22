from qdrant_client.models import PointStruct

from src.helpers.qdrant.collection import create_collection, get_collection_name
from src.helpers.qdrant.client import get_qdrant_client


class QdrantStore:

    def __init__(self, repo_identifier: str):
        if not repo_identifier:
            raise ValueError("QdrantStore requires a valid repo_identifier (repository name or path).")

        self.collection_name = get_collection_name(repo_identifier)
        self.client = get_qdrant_client()
        create_collection(self.collection_name)
        
    def has_data(self) -> bool:
        """
        Check if THIS repository's collection contains indexed code documents.
        """
        try:
            collection_info = self.client.get_collection(collection_name=self.collection_name)
            return collection_info.points_count > 0
        except Exception:
            return False

    def add_documents(self, documents, embeddings):
        points = []

        for index, (document, embedding) in enumerate(
            zip(documents, embeddings)
        ):
            points.append(
                PointStruct(
                    id=index,
                    vector=embedding,
                    payload={
                        "file": document.file,
                        "language": document.language,
                        "symbol": document.symbol,
                        "type": document.type,
                        "parent": document.parent,
                        "start_line": document.start_line,
                        "end_line": document.end_line,
                        "content": document.content,
                    }
                )
            )

        self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )

    def search(self, embedding, limit=5):
        results = self.client.query_points(
            collection_name=self.collection_name,
            query=embedding,
            limit=limit
        )

        return results.points
