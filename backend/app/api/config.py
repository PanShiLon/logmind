from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core.settings import CONFIG_PATH, reload_settings

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def get_config():
    """读取当前配置（隐藏敏感字段）"""
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="config.yaml 不存在，请先完成配置")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # 隐藏密码
    if "llm" in raw:
        raw["llm"]["api_key"] = "***"
    for s in raw.get("servers", []):
        if s.get("password"):
            s["password"] = "***"

    return raw


class ConfigUpdateRequest(BaseModel):
    content: str  # YAML 文本


@router.put("")
async def update_config(req: ConfigUpdateRequest):
    """更新配置文件（前端配置向导调用）"""
    try:
        parsed = yaml.safe_load(req.content)
        if not isinstance(parsed, dict):
            raise ValueError("配置必须是 YAML 字典")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"YAML 格式错误: {e}")

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(req.content)

    try:
        reload_settings()
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"配置校验失败: {e}")

    return {"message": "配置已保存并生效"}


@router.get("/example")
async def get_example_config():
    """返回示例配置文件内容"""
    example = CONFIG_PATH.parent / "config.example.yaml"
    if not example.exists():
        raise HTTPException(status_code=404, detail="示例配置文件不存在")
    return {"content": example.read_text(encoding="utf-8")}
