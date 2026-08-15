import json
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from ..auth.security import get_current_user, decode_access_token
from ..models.api_models import ChatRequest

router = APIRouter(prefix="/api/chat", tags=["chat"])

TOOL_LABELS = {
    "search_knowledge_base": "🔎 Searching company documents...",
    "manage_memory": "🧠 Saving a memory...",
    "search_memory": "🧠 Recalling memories...",
    "fetch": "🌐 Fetching web page...",
}


@router.post("")
async def chat(request: ChatRequest, current_user: dict = Depends(get_current_user)):
    from ..main import services

    if request.user_id != current_user["sub"]:
        raise HTTPException(403, "You can only access your own chats")

    # The knowledge base is optional. If this tenant has no indexed
    # documents, the agent can still answer using general model knowledge.
    retriever = services.qdrant.policy_retriever(current_user["tenant_id"])

    services.mongo.create_session(current_user["tenant_id"], current_user["sub"], request.thread_id)

    config = {
        "configurable": {
            "retriever_instance": retriever,
            "thread_id": f"{current_user['tenant_id']}:{request.thread_id}",
            "user_id": current_user["sub"],
            "tenant_id": current_user["tenant_id"],
        }
    }

    async def events():
        answer = []
        async for event in services.agent.stream(request.message, config):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event["type"] == "token":
                answer.append(event["text"])
        title = request.message.strip()[:50]
        if len(request.message.strip()) > 50:
            title += "…"
        services.mongo.touch_session(
            current_user["tenant_id"], current_user["sub"], request.thread_id, title=title
        )
        yield f"data: {json.dumps({'type': 'done', 'text': ''.join(answer)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


@router.websocket("/ws/{thread_id}")
async def chat_websocket(websocket: WebSocket, thread_id: str):
    await websocket.accept()
    try:
        while True:
            payload = await websocket.receive_json()
            token = payload.get("token")
            message = payload.get("message", "").strip()
            if not token or not message:
                await websocket.send_json({"type": "error", "message": "Authentication token and message are required"})
                continue
            try:
                current_user = decode_access_token(token)
            except HTTPException as exc:
                await websocket.send_json({"type": "error", "message": exc.detail})
                continue

            from ..main import services
            # The knowledge base is optional. The agent can fall back
            # to general model knowledge when no tenant documents are indexed.
            retriever = services.qdrant.policy_retriever(current_user["tenant_id"])

            services.mongo.create_session(current_user["tenant_id"], current_user["sub"], thread_id)
            config = {
                "configurable": {
                    "retriever_instance": retriever,
                    "thread_id": f"{current_user['tenant_id']}:{thread_id}",
                    "user_id": current_user["sub"],
                    "tenant_id": current_user["tenant_id"],
                }
            }
            answer = []
            async for event in services.agent.stream(message, config):
                if event["type"] == "tool":
                    event["label"] = TOOL_LABELS.get(event["tool"], f"🔧 Used tool: {event['tool']}")
                elif event["type"] == "token":
                    answer.append(event["text"])
                await websocket.send_json(event)
            title = message[:50] + ("…" if len(message) > 50 else "")
            services.mongo.touch_session(current_user["tenant_id"], current_user["sub"], thread_id, title=title)
            await websocket.send_json({"type": "done", "text": "".join(answer)})
    except WebSocketDisconnect:
        pass
