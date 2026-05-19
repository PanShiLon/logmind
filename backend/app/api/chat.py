import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk

from ..agents.graph import build_graph
from ..core.datasource.factory import create_datasource
from ..core.settings import get_settings
from ..db.database import get_messages, save_message, update_session_title

router = APIRouter(prefix="/api", tags=["chat"])

_graph = None
_graph_lock = asyncio.Lock()


async def _get_graph():
    global _graph
    if _graph is None:
        async with _graph_lock:
            if _graph is None:
                settings = get_settings()
                datasource = create_datasource(settings)
                _graph = build_graph(datasource)
    return _graph


class ChatRequest(BaseModel):
    message: str
    session_id: str


async def _stream_generator(message: str, session_id: str) -> AsyncGenerator[str, None]:
    graph = await _get_graph()

    history = await get_messages(session_id)
    lc_messages = []
    for m in history:
        if m["role"] == "user":
            lc_messages.append(HumanMessage(content=m["content"]))
        else:
            lc_messages.append(AIMessage(content=m["content"]))
    lc_messages.append(HumanMessage(content=message))

    state = {"messages": lc_messages, "intent": None}
    last_intent = None
    ai_reply = []

    async for event in graph.astream_events(state, version="v1"):
        kind = event["event"]
        name = event.get("name", "")

        if kind == "on_chain_end" and name == "classify":
            output = event.get("data", {}).get("output", {})
            intent = output.get("intent")
            if intent and intent != last_intent:
                last_intent = intent
                data = json.dumps({"type": "intent", "intent": intent}, ensure_ascii=False)
                yield f"data: {data}\n\n"

        elif kind == "on_tool_start":
            data = json.dumps({"type": "tool_start", "tool": name}, ensure_ascii=False)
            yield f"data: {data}\n\n"

        elif kind == "on_tool_end":
            data = json.dumps({"type": "tool_end", "tool": name}, ensure_ascii=False)
            yield f"data: {data}\n\n"

        elif kind == "on_chat_model_stream":
            metadata = event.get("metadata", {})
            if metadata.get("langgraph_node") == "classify":
                continue
            chunk = event["data"].get("chunk")
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                ai_reply.append(chunk.content)
                data = json.dumps({"type": "text", "content": chunk.content}, ensure_ascii=False)
                yield f"data: {data}\n\n"

    full_reply = "".join(ai_reply)
    await save_message(session_id, "user", message)
    await save_message(session_id, "assistant", full_reply)

    # 用第一条用户消息作为会话标题（前30字）
    if not history:
        title = message[:30]
        await update_session_title(session_id, title)

    yield "data: {\"type\": \"done\"}\n\n"


@router.post("/chat")
async def chat(req: ChatRequest):
    return StreamingResponse(
        _stream_generator(req.message, req.session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/health/datasource")
async def datasource_health():
    settings = get_settings()
    datasource = create_datasource(settings)
    return await datasource.health_check()


@router.get("/health/servers")
async def servers_health():
    """逐台检查所有 SSH 服务器连通性，返回每台状态"""
    import asyncssh
    settings = get_settings()
    results = []
    for s in settings.servers:
        try:
            connect_kwargs = {
                "host": s.host, "port": s.port,
                "username": s.username, "known_hosts": None,
            }
            if s.password:
                connect_kwargs["password"] = s.password
            async with asyncssh.connect(**connect_kwargs) as conn:
                await conn.run("echo ok", check=True)
            results.append({"name": s.name, "host": s.host, "status": "ok"})
        except Exception as e:
            results.append({"name": s.name, "host": s.host, "status": "error", "error": str(e)})
    return results
