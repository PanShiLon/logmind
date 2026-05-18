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

# 单例：避免每次请求重新构建 graph
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
    state = {"messages": [HumanMessage(content=message)]}

    async for event in graph.astream_events(state, version="v1"):
        kind = event["event"]

        # Tool 调用开始：通知前端正在执行哪个工具
        if kind == "on_tool_start":
            tool_name = event.get("name", "")
            data = json.dumps({"type": "tool_start", "tool": tool_name}, ensure_ascii=False)
            yield f"data: {data}\n\n"

        # LLM 流式文字输出
        elif kind == "on_chat_model_stream":
            chunk = event["data"].get("chunk")
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                data = json.dumps({"type": "text", "content": chunk.content}, ensure_ascii=False)
                yield f"data: {data}\n\n"

    yield "data: {\"type\": \"done\"}\n\n"


@router.post("/chat")
async def chat(req: ChatRequest):
    """SSE 流式对话接口"""
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
    """数据源连通性检查"""
    settings = get_settings()
    datasource = create_datasource(settings)
    return await datasource.health_check()
