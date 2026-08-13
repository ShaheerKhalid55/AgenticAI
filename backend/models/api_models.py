from typing import Optional, Any
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str
    thread_id: str
    message: str


class SessionCreateRequest(BaseModel):
    user_id: str
    title: Optional[str] = None


class SessionRenameRequest(BaseModel):
    user_id: str
    title: str = Field(min_length=1, max_length=80)


class SessionResponse(BaseModel):
    user_id: str
    thread_id: str
    title: str
    created_at: Any
    updated_at: Any


class HealthResponse(BaseModel):
    status: str
    mongo: bool
    qdrant: bool
    embeddings: bool
    agent: bool


class KnowledgeBaseResponse(BaseModel):
    success: bool
    documents: int = 0
    pages: int = 0
    chunks: int = 0
    message: str = ""
