from langchain_core.embeddings import Embeddings
import mixedbread
from mixedbread import Mixedbread

from ..config import MIXEDBREAD_API_KEY, MEMORY_EMBEDDING_DIMS, MEMORY_EMBEDDING_MODEL


class MxBaiEmbeddings(Embeddings):
    """LangChain-compatible wrapper around the hosted mxbai-embed-large-v1 API."""

    QUERY_PROMPT = "Represent this sentence for searching relevant passages:"

    def __init__(self):
        if not MIXEDBREAD_API_KEY:
            raise RuntimeError("MIXEDBREAD_API_KEY is not configured")

        # Mixedbread retries transient 5xx responses. Increase retries because
        # Qdrant/RAG requests should tolerate brief upstream outages.
        self.client = Mixedbread(
            api_key=MIXEDBREAD_API_KEY,
            max_retries=5,
            timeout=30.0,
        )
        self.model = MEMORY_EMBEDDING_MODEL
        self.dimensions = MEMORY_EMBEDDING_DIMS

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=batch,
                dimensions=self.dimensions,
                normalized=True,
            )
            return [item.embedding for item in response.data]
        except mixedbread.APIStatusError as exc:
            status = getattr(exc, "status_code", "unknown")
            detail = str(getattr(exc, "response", exc))
            raise RuntimeError(
                f"Mixedbread embedding API returned HTTP {status}. {detail}"
            ) from exc
        except mixedbread.APIConnectionError as exc:
            raise RuntimeError(
                "Could not connect to the Mixedbread embedding API."
            ) from exc

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        results: list[list[float]] = []
        for start in range(0, len(texts), 32):
            batch = texts[start:start + 32]
            results.extend(self._embed_batch(batch))

        return results

    def embed_query(self, text: str) -> list[float]:
        query = f"{self.QUERY_PROMPT} {text}"
        return self._embed_batch([query])[0]
