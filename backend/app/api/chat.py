import asyncio
import json
from datetime import datetime
from typing import AsyncGenerator, Optional, List

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


import re

_LOG_DATA_RE = re.compile(r'<log_data>[\s\S]*?</log_data>')
_LOG_LINES_RE = re.compile(r'(\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[\w+\] \[.+?\] .+?\n){3,}')


def _trim_ai_content(content: str) -> str:
    """裁剪 AI 历史回复中的大段日志数据，只保留摘要，减少上下文噪音。"""
    content = _LOG_DATA_RE.sub('[日志数据已省略]', content)
    content = re.sub(
        r'<chart_config>[\s\S]*?</chart_config>',
        '[图表配置已省略]',
        content,
    )
    def _replace_log_block(m):
        lines = m.group(0).strip().split('\n')
        return f'[{len(lines)} 条日志已省略]\n'
    content = _LOG_LINES_RE.sub(_replace_log_block, content)
    return content


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
            lc_messages.append(AIMessage(content=_trim_ai_content(m["content"])))
    lc_messages.append(HumanMessage(content=message))

    state = {"messages": lc_messages, "intent": None}
    last_intent = None
    ai_reply = []
    log_data_tags = []

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
            raw_data = event.get("data", {})
            output_obj = raw_data.get("output", "")
            if hasattr(output_obj, "content"):
                tool_output = output_obj.content
            elif isinstance(output_obj, str):
                tool_output = output_obj
            else:
                tool_output = str(output_obj)
            if "<log_data>" in tool_output:
                import re
                start_idx = tool_output.index("<log_data>") + len("<log_data>")
                end_idx = tool_output.rindex("</log_data>")
                raw_json = tool_output[start_idx:end_idx]
                try:
                    log_payload = json.loads(raw_json)
                    log_data_tags.append(f"<log_data>{raw_json}</log_data>")
                    ld = json.dumps({"type": "log_data", "tool": name, **log_payload}, ensure_ascii=False)
                    yield f"data: {ld}\n\n"
                except Exception as ex:
                    print(f"[DEBUG] log_data parse error: {ex}, first 200 chars: {raw_json[:200]}")
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
    if log_data_tags:
        full_reply += "\n" + "\n".join(log_data_tags)
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


class LogsMoreRequest(BaseModel):
    query: str
    level: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    servers: Optional[str] = None
    offset: int = 0
    limit: int = 50


@router.post("/logs/more")
async def logs_more(req: LogsMoreRequest):
    settings = get_settings()
    datasource = create_datasource(settings)

    st = datetime.fromisoformat(req.start_time) if req.start_time else None
    et = datetime.fromisoformat(req.end_time) if req.end_time else None
    sv = [s.strip() for s in req.servers.split(",")] if req.servers else None

    result = await datasource.search(
        query=req.query,
        level=req.level,
        start_time=st,
        end_time=et,
        limit=req.limit,
        offset=req.offset,
        servers=sv,
    )

    entries = []
    for e in result.entries:
        ts = e.timestamp.strftime("%Y-%m-%d %H:%M:%S") if e.timestamp else None
        msg = (e.message or "")[:500].replace("\x00", "")
        entries.append({
            "timestamp": ts,
            "level": e.level,
            "source": e.source,
            "message": msg,
        })

    return {"total": result.total, "took_ms": result.took_ms, "entries": entries}
