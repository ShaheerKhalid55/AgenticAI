from fastapi import APIRouter, Depends
from ..auth.security import get_current_user

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health():
    from ..main import services
    return {
        "status": "ok",
        "mongo": bool(services.mongo and services.mongo.ping()),
        "qdrant": bool(services.qdrant and services.qdrant.ping()),
        "embeddings": bool(services.qdrant and services.qdrant.embeddings),
        "agent": bool(services.agent and services.agent.graph),
    }


@router.get("/status")
def status(current_user: dict = Depends(get_current_user)):
    from ..main import services
    return {
        "knowledge_base": bool(services.qdrant and services.qdrant.policy_retriever(current_user["tenant_id"])),
        "conversation_memory": bool(services.mongo and services.mongo.ping()),
        "long_term_memory": bool(services.agent and services.agent.memory_store),
        "mcp_tools": len(services.agent.mcp_tools) if services.agent else 0,
    }
