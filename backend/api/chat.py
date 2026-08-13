import json
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from ..models.api_models import ChatRequest

router = APIRouter(prefix="/api/chat", tags=["chat"])

TOOL_LABELS = {
    "query_hr_policies": "📄 Searching policy documents...",
    "manage_memory": "🧠 Saving a memory...",
    "search_memory": "🧠 Recalling memories...",
    "fetch": "🌐 Fetching web page...",
}


@router.post("")
async def chat(request: ChatRequest):
    from ..main import services

    retriever = services.qdrant.policy_retriever()
    if retriever is None:
        raise HTTPException(400, "Knowledge base is empty. Upload and build policy documents first.")

    services.mongo.create_session(request.user_id, request.thread_id)

    config = {
        "configurable": {
            "retriever_instance": retriever,
            "thread_id": request.thread_id,
            "user_id": request.user_id,
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
            request.user_id,
            request.thread_id,
            title=title,
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
            user_id = payload.get("user_id")
            message = payload.get("message", "").strip()

            if not user_id or not message:
                await websocket.send_json({
                    "type": "error",
                    "message": "user_id and message are required",
                })
                continue

            from ..main import services
            retriever = services.qdrant.policy_retriever()
            if retriever is None:
                await websocket.send_json({
                    "type": "error",
                    "message": "Knowledge base is empty. Upload policy PDFs first.",
                })
                continue

            config = {
                "configurable": {
                    "retriever_instance": retriever,
                    "thread_id": thread_id,
                    "user_id": user_id,
                }
            }

            services.mongo.create_session(user_id, thread_id)
            answer = []

            async for event in services.agent.stream(message, config):
                if event["type"] == "tool":
                    event["label"] = TOOL_LABELS.get(
                        event["tool"],
                        f"🔧 Used tool: {event['tool']}",
                    )
                elif event["type"] == "token":
                    answer.append(event["text"])
                await websocket.send_json(event)

            title = message[:50] + ("…" if len(message) > 50 else "")
            services.mongo.touch_session(user_id, thread_id, title=title)
            await websocket.send_json({
                "type": "done",
                "text": "".join(answer),
            })

    except WebSocketDisconnect:
        pass
