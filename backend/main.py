from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, config as config_router
from app.api import sessions
from app.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="LogMind API",
    version="0.1.0",
    description="AI 驱动的日志分析平台",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(config_router.router)
app.include_router(sessions.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
