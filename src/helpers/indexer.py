import os


class Indexer:

    def __init__(   
        self,
        scanner,
        detector,
        extractor,
        embedding_client,
        store
    ):
        self.scanner = scanner
        self.detector = detector
        self.extractor = extractor
        self.embedding_client = embedding_client
        self.store = store

    def index(self, repo_path):
        if self.store.has_data():
            print("Data already indexed in Qdrant. Skipping extraction and embedding ✅")
            return []

        print("Indexer: scanning files 🔍")

        files = self.scanner.scan(repo_path)

        print(f"Indexer: found {len(files)} files ✅")

        documents = []

        for file_path in files:
            full_path = os.path.join(repo_path, file_path)

            language = self.detector.detect(file_path)

            if language is None:
                continue

            try:
                with open(
                    full_path,
                    "r",
                    encoding="utf-8"
                ) as file:
                    code = file.read()

            except (UnicodeDecodeError, OSError) as e:
                print(
                    f"Skipping unreadable file {file_path}: {e}"
                )
                continue

            file_documents = self.extractor.extract(
                code,
                file_path,
                language
            )

            documents.extend(file_documents)

        print(
            f"Extraction finished: {len(documents)} documents"
        )

        if not documents:
            print("No documents to embed. Skipping ⚠️")
            return documents

        texts = [
            document.content
            for document in documents
        ]

        print("Before embedding")

        batch_size = 8
        embeddings = []
        total_texts = len(texts)
        total_batches = (total_texts + batch_size - 1) // batch_size
        
        MAX_CHAR_LENGTH = 8000 

        for i in range(0, total_texts, batch_size):
            batch_texts = texts[i : i + batch_size]
            current_batch = (i // batch_size) + 1
            print(f"Embedding batch {current_batch}/{total_batches} ({len(batch_texts)} texts)...")
            
            safe_batch_texts = [
                text[:MAX_CHAR_LENGTH] if len(text) > MAX_CHAR_LENGTH else text 
                for text in batch_texts
            ]
            
            try:
                batch_embeddings = self.embedding_client.embed(safe_batch_texts)
                embeddings.extend(batch_embeddings)
            except Exception as e:
                print(f"❌ Failed at batch {current_batch}: {e}")
                raise e

        print("After embedding")

        self.store.add_documents(
            documents,
            embeddings
        )

        print("Indexing finished ✅")

        return documents
