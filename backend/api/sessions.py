import uuid
from fastapi import APIRouter, HTTPException

from ..models.api_models import (
    SessionCreateRequest,
    SessionRenameRequest,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("")
def list_sessions(user_id: str):
    from ..main import services
    if not services.mongo:
        raise HTTPException(503, "MongoDB is unavailable")
    return services.mongo.list_sessions(user_id)


@router.post("")
def create_session(request: SessionCreateRequest):
    from ..main import services
    thread_id = str(uuid.uuid4())
    services.mongo.create_session(request.user_id, thread_id, request.title)
    return {
        "user_id": request.user_id,
        "thread_id": thread_id,
        "title": request.title,
    }


@router.get("/{thread_id}/history")
def get_history(thread_id: str):
    from ..main import services
    return services.agent.history(thread_id)


@router.patch("/{thread_id}")
def rename_session(thread_id: str, request: SessionRenameRequest):
    from ..main import services
    services.mongo.rename_session(request.user_id, thread_id, request.title)
    return {"success": True}


@router.delete("/{thread_id}")
def delete_session(thread_id: str, user_id: str):
    from ..main import services
    services.mongo.delete_session(user_id, thread_id)
    return {"success": True}
