import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from ..auth.security import get_current_user, decode_access_token
from ..models.api_models import ChatRequest

router = APIRouter(prefix="/api/chat", tags=["chat"])

TOOL_LABELS = {
    "search_knowledge_base": "📄 Searching the knowledge base...",
    "manage_memory": "🧠 Saving a memory...",
    "search_memory": "🧠 Recalling memories...",
    "fetch": "🌐 Fetching web page...",
}


def _active_retriever(services, tenant_id: str):
    active_docs = services.mongo.documents.find(
        {"tenant_id": tenant_id, "status": "active"},
        {"id": 1},
    )
    active_document_ids = [doc["id"] for doc in active_docs if doc.get("id")]
    if not active_document_ids:
        return None
    return services.qdrant.policy_retriever(
        tenant_id,
        active_document_ids=active_document_ids,
    )


@router.post("")
async def chat(request: ChatRequest, current_user: dict = Depends(get_current_user)):
    from ..main import services

    if request.user_id != current_user["sub"]:
        raise HTTPException(403, "You can only access your own chats")

    assistant = services.mongo.get_assistant(current_user["tenant_id"])
    if assistant.get("status") != "active":
        raise HTTPException(409, "This assistant is not active")

    retriever = _active_retriever(services, current_user["tenant_id"])
    services.mongo.create_session(
        current_user["tenant_id"], current_user["sub"], request.thread_id
    )
    services.mongo.set_automatic_session_title(
        current_user["tenant_id"], current_user["sub"], request.thread_id, request.message
    )

    conversation_memory = (assistant.get("memory_settings") or {}).get(
        "conversation_memory", True
    )
    checkpoint_thread = request.thread_id if conversation_memory else str(uuid.uuid4())
    config = {
        "configurable": {
            "retriever_instance": retriever,
            "thread_id": f"{current_user['tenant_id']}:{checkpoint_thread}",
            "user_id": current_user["sub"],
            "tenant_id": current_user["tenant_id"],
            "assistant_config": assistant,
        }
    }

    async def events():
        answer = []
        async for event in services.agent.stream(request.message, config):
            if event.get("type") == "tool":
                event["label"] = TOOL_LABELS.get(
                    event.get("tool"), f"🔧 Used tool: {event.get('tool', 'tool')}"
                )
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event.get("type") == "token":
                answer.append(event["text"])
        services.mongo.touch_session(
            current_user["tenant_id"], current_user["sub"], request.thread_id
        )
        yield f"data: {json.dumps({'type': 'done', 'text': ''.join(answer)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.websocket("/ws/{thread_id}")
async def chat_websocket(websocket: WebSocket, thread_id: str):
    await websocket.accept()
    try:
        while True:
            payload = await websocket.receive_json()
            token = payload.get("token")
            message = payload.get("message", "").strip()
            if not token or not message:
                await websocket.send_json(
                    {"type": "error", "message": "Authentication token and message are required"}
                )
                continue
            try:
                current_user = decode_access_token(token)
            except HTTPException as exc:
                await websocket.send_json({"type": "error", "message": exc.detail})
                continue

            from ..main import services
            assistant = services.mongo.get_assistant(current_user["tenant_id"])
            if assistant.get("status") != "active":
                await websocket.send_json({"type": "error", "message": "This assistant is not active"})
                continue

            retriever = _active_retriever(services, current_user["tenant_id"])
            services.mongo.create_session(current_user["tenant_id"], current_user["sub"], thread_id)
            services.mongo.set_automatic_session_title(
                current_user["tenant_id"], current_user["sub"], thread_id, message
            )
            conversation_memory = (assistant.get("memory_settings") or {}).get(
                "conversation_memory", True
            )
            checkpoint_thread = thread_id if conversation_memory else str(uuid.uuid4())
            config = {
                "configurable": {
                    "retriever_instance": retriever,
                    "thread_id": f"{current_user['tenant_id']}:{checkpoint_thread}",
                    "user_id": current_user["sub"],
                    "tenant_id": current_user["tenant_id"],
                    "assistant_config": assistant,
                }
            }
            answer = []
            async for event in services.agent.stream(message, config):
                if event.get("type") == "tool":
                    event["label"] = TOOL_LABELS.get(
                        event.get("tool"), f"🔧 Used tool: {event.get('tool', 'tool')}"
                    )
                elif event.get("type") == "token":
                    answer.append(event["text"])
                await websocket.send_json(event)
            services.mongo.touch_session(current_user["tenant_id"], current_user["sub"], thread_id)
            await websocket.send_json({"type": "done", "text": "".join(answer)})
    except WebSocketDisconnect:
        pass
