import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessageChunk

from ..agents.graph import build_graph
from ..core.datasource.factory import create_datasource
from ..core.settings import get_settings

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
    session_id: str = "default"


async def _stream_generator(message: str) -> AsyncGenerator[str, None]:
    graph = await _get_graph()
    state = {"messages": [HumanMessage(content=message)], "intent": None}
    last_intent = None

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
                data = json.dumps({"type": "text", "content": chunk.content}, ensure_ascii=False)
                yield f"data: {data}\n\n"

    yield "data: {\"type\": \"done\"}\n\n"


@router.post("/chat")
async def chat(req: ChatRequest):
    return StreamingResponse(
        _stream_generator(req.message),
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
