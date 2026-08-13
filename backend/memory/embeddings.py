from langchain_core.embeddings import Embeddings
from mixedbread_ai.client import ApiError, MixedbreadAI
from mixedbread_ai.types import EncodingFormat

from ..config import MIXEDBREAD_API_KEY, MEMORY_EMBEDDING_DIMS, MEMORY_EMBEDDING_MODEL


class MxBaiEmbeddings(Embeddings):
    """LangChain-compatible wrapper around Mixedbread's hosted mxbai-embed-large-v1 API."""

    QUERY_PROMPT = "Represent this sentence for searching relevant passages: "
    BATCH_SIZE = 32

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or MIXEDBREAD_API_KEY
        if not self.api_key:
            raise RuntimeError("MIXEDBREAD_API_KEY is not configured")

        self.client = MixedbreadAI(api_key=self.api_key)

    @staticmethod
    def _extract_float_embeddings(response) -> list[list[float]]:
        embeddings = []
        for item in response.data:
            value = item.embedding
            vector = getattr(value, "float_", value)
            embeddings.append([float(x) for x in vector])
        return embeddings

    def _embed_batch(self, texts: list[str], *, prompt: str | None = None) -> list[list[float]]:
        if not texts:
            return []

        kwargs = {
            "model": MEMORY_EMBEDDING_MODEL,
            "input": texts,
            "normalized": True,
            "dimensions": MEMORY_EMBEDDING_DIMS,
            "encoding_format": [EncodingFormat.FLOAT],
        }
        if prompt is not None:
            kwargs["prompt"] = prompt

        try:
            response = self.client.embeddings(**kwargs)
        except ApiError as exc:
            raise RuntimeError(
                f"Mixedbread embedding API request failed (HTTP {exc.status_code})."
            ) from exc
        except Exception as exc:
            raise RuntimeError("Mixedbread embedding API request failed.") from exc

        vectors = self._extract_float_embeddings(response)
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"Mixedbread returned {len(vectors)} embeddings for {len(texts)} inputs."
            )
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[start:start + self.BATCH_SIZE]
            results.extend(self._embed_batch(batch))
        return results

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch(
            [text],
            prompt=self.QUERY_PROMPT,
        )[0]
