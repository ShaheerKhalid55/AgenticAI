from qdrant_client import QdrantClient, models as qmodels
from langchain_qdrant import QdrantVectorStore

from ..config import (
    QDRANT_MEMORY_URL,
    QDRANT_API_KEY,
    QDRANT_MEMORY_COLLECTION,
    POLICY_COLLECTION,
    MEMORY_EMBEDDING_DIMS,
    MAX_NAMESPACE_DEPTH,
)
from ..memory.embeddings import MxBaiEmbeddings


class QdrantService:
    def __init__(self):
        if not QDRANT_MEMORY_URL:
            raise RuntimeError("QDRANT_MEMORY_URL is not configured")
        self.client = QdrantClient(
            url=QDRANT_MEMORY_URL,
            api_key=QDRANT_API_KEY,
        )
        self.embeddings = MxBaiEmbeddings()
        self._ensure_memory_collection()

    def ping(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    def _ensure_memory_collection(self):
        if not self.client.collection_exists(QDRANT_MEMORY_COLLECTION):
            self.client.create_collection(
                collection_name=QDRANT_MEMORY_COLLECTION,
                vectors_config=qmodels.VectorParams(
                    size=MEMORY_EMBEDDING_DIMS,
                    distance=qmodels.Distance.COSINE,
                ),
            )
            for i in range(MAX_NAMESPACE_DEPTH):
                self.client.create_payload_index(
                    collection_name=QDRANT_MEMORY_COLLECTION,
                    field_name=f"ns_{i}",
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
            self.client.create_payload_index(
                collection_name=QDRANT_MEMORY_COLLECTION,
                field_name="key",
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
            )

    def policy_store(self):
        if not self.client.collection_exists(POLICY_COLLECTION):
            return None
        store = QdrantVectorStore(
            client=self.client,
            collection_name=POLICY_COLLECTION,
            embedding=self.embeddings,
            # Do not call the embedding API with a dummy text just to validate
            # the collection at construction time. The hosted embedding API
            # can briefly return 503, and the collection is already known to
            # be 1024-dimensional. Actual queries still validate at runtime.
            validate_collection_config=False,
        )
        return store

    def policy_retriever(self, k: int = 4):
        store = self.policy_store()
        return store.as_retriever(search_kwargs={"k": k}) if store else None

    def index_documents(self, documents):
        from langchain_qdrant import QdrantVectorStore
        store = QdrantVectorStore.from_documents(
            documents=documents,
            embedding=self.embeddings,
            url=QDRANT_MEMORY_URL,
            api_key=QDRANT_API_KEY,
            collection_name=POLICY_COLLECTION,
            validate_collection_config=False,
        )
        return store
