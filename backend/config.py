import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_CLOUD_HOST = os.getenv("OLLAMA_HOST", "https://ollama.com")
OLLAMA_LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "gemma4:cloud")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MIXEDBREAD_API_KEY = os.getenv("MIXEDBREAD_API_KEY")

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "hr_agent_checkpoints")
SESSIONS_COLLECTION = "hr_agent_sessions"

QDRANT_MEMORY_URL = os.getenv("QDRANT_MEMORY_URL", "")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_MEMORY_COLLECTION = os.getenv(
    "QDRANT_MEMORY_COLLECTION",
    "hr_agent_long_term_memory_mxbai",
)
POLICY_COLLECTION = os.getenv("POLICY_COLLECTION", "policy_app_agent_mxbai")

MEMORY_EMBEDDING_MODEL = "mixedbread-ai/mxbai-embed-large-v1"
MEMORY_EMBEDDING_DIMS = 1024
MAX_NAMESPACE_DEPTH = 8

CORS_ORIGINS = [
    x.strip() for x in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5500,http://127.0.0.1:5500,http://localhost:8000",
    ).split(",") if x.strip()
]
