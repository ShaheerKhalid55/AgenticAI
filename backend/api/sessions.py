import uuid
from fastapi import APIRouter, Depends, HTTPException

from ..auth.security import get_current_user
from ..models.api_models import SessionCreateRequest, SessionRenameRequest

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("")
def list_sessions(current_user: dict = Depends(get_current_user)):
    from ..main import services
    if not services.mongo:
        raise HTTPException(503, "MongoDB is unavailable")
    return services.mongo.list_sessions(current_user["tenant_id"], current_user["sub"])


@router.post("")
def create_session(request: SessionCreateRequest, current_user: dict = Depends(get_current_user)):
    from ..main import services
    thread_id = str(uuid.uuid4())
    services.mongo.create_session(current_user["tenant_id"], current_user["sub"], thread_id, request.title)
    return {"user_id": current_user["sub"], "thread_id": thread_id, "title": request.title}


@router.get("/{thread_id}/history")
def get_history(thread_id: str, current_user: dict = Depends(get_current_user)):
    from ..main import services
    if not services.mongo.session_belongs_to(current_user["tenant_id"], current_user["sub"], thread_id):
        raise HTTPException(404, "Chat not found")
    return services.agent.history(current_user["tenant_id"], thread_id)


@router.patch("/{thread_id}")
def rename_session(thread_id: str, request: SessionRenameRequest, current_user: dict = Depends(get_current_user)):
    from ..main import services
    if not services.mongo.session_belongs_to(current_user["tenant_id"], current_user["sub"], thread_id):
        raise HTTPException(404, "Chat not found")
    services.mongo.rename_session(current_user["tenant_id"], current_user["sub"], thread_id, request.title)
    return {"success": True}


@router.delete("/{thread_id}")
def delete_session(thread_id: str, current_user: dict = Depends(get_current_user)):
    from ..main import services
    if not services.mongo.session_belongs_to(current_user["tenant_id"], current_user["sub"], thread_id):
        raise HTTPException(404, "Chat not found")
    services.mongo.delete_session(current_user["tenant_id"], current_user["sub"], thread_id)
    return {"success": True}
