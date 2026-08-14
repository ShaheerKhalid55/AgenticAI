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
    POLICY_COLLECTION = POLICY_COLLECTION

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

    def _ensure_policy_collection_index(self):
        if not self.client.collection_exists(POLICY_COLLECTION):
            return

        # Current LangChain payload layout uses metadata.*. Older versions of
        # this project used top-level fields. Index both so existing points
        # remain searchable after an upgrade.
        for field_name in (
            "metadata.tenant_id",
            "metadata.document_id",
            "metadata.policy_status",
            "tenant_id",
            "document_id",
            "policy_status",
        ):
            try:
                self.client.create_payload_index(
                    collection_name=POLICY_COLLECTION,
                    field_name=field_name,
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
            except Exception:
                pass

    @staticmethod
    def _tenant_condition(tenant_id: str):
        """Match both current and legacy tenant payload layouts.

        Current LangChain Qdrant:
            metadata.tenant_id

        Older application versions:
            tenant_id

        A point must explicitly contain the current tenant ID in one of these
        fields. Points without a tenant ID are never returned, preserving
        tenant isolation.
        """
        return qmodels.Filter(
            min_should=qmodels.MinShould(
                conditions=[
                    qmodels.FieldCondition(
                        key="metadata.tenant_id",
                        match=qmodels.MatchValue(value=tenant_id),
                    ),
                    qmodels.FieldCondition(
                        key="tenant_id",
                        match=qmodels.MatchValue(value=tenant_id),
                    ),
                ],
                min_count=1,
            )
        )

    @classmethod
    def _active_policy_filter(cls, tenant_id: str):
        return qmodels.Filter(
            must=[cls._tenant_condition(tenant_id)],
            must_not=[
                qmodels.FieldCondition(
                    key="metadata.policy_status",
                    match=qmodels.MatchValue(value="archived"),
                ),
                qmodels.FieldCondition(
                    key="metadata.policy_status",
                    match=qmodels.MatchValue(value="processing"),
                ),
                qmodels.FieldCondition(
                    key="metadata.policy_status",
                    match=qmodels.MatchValue(value="failed"),
                ),
                qmodels.FieldCondition(
                    key="policy_status",
                    match=qmodels.MatchValue(value="archived"),
                ),
                qmodels.FieldCondition(
                    key="policy_status",
                    match=qmodels.MatchValue(value="processing"),
                ),
                qmodels.FieldCondition(
                    key="policy_status",
                    match=qmodels.MatchValue(value="failed"),
                ),
            ],
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

        return store.as_retriever(
            search_kwargs={
                "k": k,
                "filter": self._active_policy_filter(tenant_id),
            }
        )

    def index_documents(
        self,
        documents,
        tenant_id: str,
        document_id: str,
        version: int,
        status: str = "processing",
    ):
        for document in documents:
            document.metadata.update({
                "tenant_id": tenant_id,
                "document_id": document_id,
                "document_version": version,
                "policy_status": status,
            })

        store = QdrantVectorStore.from_documents(
            documents=documents,
            embedding=self.embeddings,
            url=QDRANT_MEMORY_URL,
            api_key=QDRANT_API_KEY,
            collection_name=POLICY_COLLECTION,
            validate_collection_config=False,
        )
        self._ensure_policy_collection_index()
        return store

    @staticmethod
    def _document_condition(document_id: str):
        return qmodels.Filter(
            min_should=qmodels.MinShould(
                conditions=[
                    qmodels.FieldCondition(
                        key="metadata.document_id",
                        match=qmodels.MatchValue(value=document_id),
                    ),
                    qmodels.FieldCondition(
                        key="document_id",
                        match=qmodels.MatchValue(value=document_id),
                    ),
                ],
                min_count=1,
            )
        )

    def set_policy_status(self, tenant_id: str, document_id: str, status: str):
        if not self.client.collection_exists(POLICY_COLLECTION):
            return

        scroll_filter = qmodels.Filter(
            must=[
                self._tenant_condition(tenant_id),
                self._document_condition(document_id),
            ]
        )

        offset = None
        while True:
            records, offset = self.client.scroll(
                collection_name=POLICY_COLLECTION,
                scroll_filter=scroll_filter,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not records:
                break

            for record in records:
                payload = record.payload or {}
                metadata = dict(payload.get("metadata") or {})
                metadata.update({
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "policy_status": status,
                })
                self.client.set_payload(
                    collection_name=POLICY_COLLECTION,
                    payload={"metadata": metadata},
                    points=[record.id],
                )

            if offset is None:
                break

    def delete_policy_document(self, tenant_id: str, document_id: str):
        if not self.client.collection_exists(POLICY_COLLECTION):
            return

        self.client.delete(
            collection_name=POLICY_COLLECTION,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        self._tenant_condition(tenant_id),
                        self._document_condition(document_id),
                    ]
                )
            ),
        )
