from datetime import datetime
from typing import Optional, Any, Literal, Annotated
from pydantic import BaseModel, Field, StringConstraints


StarterQuestion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]
ToolId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80),
]


class ChatRequest(BaseModel):
    user_id: str
    thread_id: str
    message: str = Field(min_length=1, max_length=12000)


class SessionCreateRequest(BaseModel):
    title: Optional[str] = None


class SessionRenameRequest(BaseModel):
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


class MemorySettings(BaseModel):
    conversation_memory: bool = True
    long_term_memory: bool = True
    save_personal_preferences: bool = True


class CitationRequirements(BaseModel):
    enabled: bool = True
    required: bool = True
    include_document_name: bool = True
    include_page: bool = True
    include_chunk: bool = True


class AssistantConfiguration(BaseModel):
    id: str
    tenant_id: str
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    system_instructions: str = Field(default="", max_length=12000)
    welcome_message: str = Field(default="How can I help?", max_length=2000)
    placeholder: str = Field(default="Ask Nexa anything...", max_length=240)
    icon: Optional[str] = Field(default=None, max_length=500)
    knowledge_base_id: Optional[str] = Field(default=None, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    enabled_tools: list[ToolId] = Field(default_factory=lambda: ["knowledge_base", "memory", "web_fetch"], max_length=20)
    memory_settings: MemorySettings = Field(default_factory=MemorySettings)
    citation_requirements: CitationRequirements = Field(default_factory=CitationRequirements)
    starter_questions: list[StarterQuestion] = Field(default_factory=list, max_length=12)
    status: Literal["active", "inactive", "draft"] = "active"
    created_at: datetime
    updated_at: datetime


class AssistantConfigurationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)
    system_instructions: Optional[str] = Field(default=None, max_length=12000)
    welcome_message: Optional[str] = Field(default=None, max_length=2000)
    placeholder: Optional[str] = Field(default=None, max_length=240)
    icon: Optional[str] = Field(default=None, max_length=500)
    knowledge_base_id: Optional[str] = Field(default=None, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    enabled_tools: Optional[list[ToolId]] = Field(default=None, max_length=20)
    memory_settings: Optional[MemorySettings] = None
    citation_requirements: Optional[CitationRequirements] = None
    starter_questions: Optional[list[StarterQuestion]] = Field(default=None, max_length=12)
    status: Optional[Literal["active", "inactive", "draft"]] = None


class AssistantToolStatus(BaseModel):
    id: str
    name: str
    description: str
    available: bool
    enabled: bool
    status: Literal["available", "unavailable", "disabled"]
