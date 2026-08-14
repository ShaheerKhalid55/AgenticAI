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
        self.client = QdrantClient(url=QDRANT_MEMORY_URL, api_key=QDRANT_API_KEY)
        self.embeddings = MxBaiEmbeddings()
        self._ensure_memory_collection()
        self._ensure_policy_collection_index()

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
                vectors_config=qmodels.VectorParams(size=MEMORY_EMBEDDING_DIMS, distance=qmodels.Distance.COSINE),
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

    def _ensure_policy_collection_index(self):
        if not self.client.collection_exists(POLICY_COLLECTION):
            return
        try:
            self.client.create_payload_index(
                collection_name=POLICY_COLLECTION,
                field_name="tenant_id",
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass

    @staticmethod
    def _tenant_filter(tenant_id: str):
        return qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="tenant_id",
                    match=qmodels.MatchValue(value=tenant_id),
                )
            ]
        )

    def policy_store(self, tenant_id: str):
        if not self.client.collection_exists(POLICY_COLLECTION):
            return None
        return QdrantVectorStore(
            client=self.client,
            collection_name=POLICY_COLLECTION,
            embedding=self.embeddings,
            validate_collection_config=False,
        )

    def policy_retriever(self, tenant_id: str, k: int = 4):
        store = self.policy_store(tenant_id)
        if not store:
            return None
        return store.as_retriever(search_kwargs={
            "k": k,
            "filter": self._tenant_filter(tenant_id),
        })

    def index_documents(self, documents, tenant_id: str):
        for document in documents:
            document.metadata["tenant_id"] = tenant_id

        return QdrantVectorStore.from_documents(
            documents=documents,
            embedding=self.embeddings,
            url=QDRANT_MEMORY_URL,
            api_key=QDRANT_API_KEY,
            collection_name=POLICY_COLLECTION,
            validate_collection_config=False,
        )
