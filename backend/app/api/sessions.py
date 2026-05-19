from fastapi import APIRouter
from pydantic import BaseModel

from ..db.database import create_session, list_sessions, get_messages, delete_session, close_session, reopen_session

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    title: str = "新会话"


@router.post("")
async def new_session(req: CreateSessionRequest):
    return await create_session(req.title)


@router.get("")
async def get_sessions():
    return await list_sessions()


@router.get("/{session_id}/messages")
async def get_session_messages(session_id: str):
    return await get_messages(session_id)


@router.delete("/{session_id}")
async def remove_session(session_id: str):
    await delete_session(session_id)
    return {"ok": True}


@router.post("/{session_id}/close")
async def end_session(session_id: str):
    await close_session(session_id)
    return {"ok": True}


@router.post("/{session_id}/reopen")
async def continue_session(session_id: str):
    await reopen_session(session_id)
    return {"ok": True}
