from sentence_transformers import SentenceTransformer
from langchain_core.embeddings import Embeddings


class MxBaiEmbeddings(Embeddings):
    """LangChain-compatible wrapper around mxbai-embed-large-v1."""

    QUERY_PROMPT = "Represent this sentence for searching relevant passages: "

    def __init__(self):
        self.model = SentenceTransformer("mixedbread-ai/mxbai-embed-large-v1")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def embed_query(self, text: str) -> list[float]:
        query = self.QUERY_PROMPT + text
        embedding = self.model.encode(
            query,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return embedding.tolist()
