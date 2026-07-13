"""HTTP 请求测试器 —— 平台内直接发请求（类 curl / Apifox）的后端代理。

浏览器直接 fetch 目标服务会撞 CORS，所以由后端 httpx 转发目标请求再回传响应。
前端只把结构化的 {method,url,headers,body} 发过来，curl 解析在前端完成。

⚠️ 安全：本接口可向任意地址发请求，是典型 SSRF 面。防护分层：
  1) 后端只绑 127.0.0.1（启动参数保证，不在此文件）；
  2) 元数据地址黑名单（169.254.169.254 等）硬拒；
  3) config.yaml http_tester.allow_hosts 白名单：为空走黑名单，填了只放行列表内 host；
  4) 不打印/落盘 Authorization 等敏感头。
"""

import ipaddress
import json
import socket
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.settings import HTTP_TESTER_STATE_PATH, get_settings, reload_settings

router = APIRouter(prefix="/api/http", tags=["http-tester"])

# 硬黑名单：无论白名单如何都拒绝的地址（云元数据 / 通配地址）
_BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal", "0.0.0.0", "::"}

# 允许的方法
_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

# 单次响应体最大回传字节（避免把超大响应灌进前端），超出截断
_MAX_BODY_BYTES = 2 * 1024 * 1024  # 2MB


class HttpSendRequest(BaseModel):
    method: str = "GET"
    url: str
    headers: Dict[str, str] = Field(default_factory=dict)
    body: Optional[str] = None
    timeout: float = 20.0


class HttpTesterConfigOut(BaseModel):
    enabled: bool
    allow_hosts: List[str]


class HttpTesterConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    allow_hosts: Optional[List[str]] = None


@router.get("/config", response_model=HttpTesterConfigOut)
async def get_config():
    """读当前白名单/开关状态，供页面设置面板展示。"""
    cfg = get_settings().http_tester
    return HttpTesterConfigOut(enabled=cfg.enabled, allow_hosts=cfg.allow_hosts)


@router.put("/config", response_model=HttpTesterConfigOut)
async def update_config(req: HttpTesterConfigUpdate):
    """页面开关/白名单写入 sidecar 文件（不改动 config.yaml，保住其注释）。"""
    cur = get_settings().http_tester
    state = {
        "enabled": req.enabled if req.enabled is not None else cur.enabled,
        # 清洗：去空、去重、小写、strip
        "allow_hosts": sorted({h.strip().lower() for h in (req.allow_hosts if req.allow_hosts is not None else cur.allow_hosts) if h and h.strip()}),
    }
    with open(HTTP_TESTER_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    reload_settings()  # 让内存里的 settings 立即生效
    cfg = get_settings().http_tester
    return HttpTesterConfigOut(enabled=cfg.enabled, allow_hosts=cfg.allow_hosts)


def _resolve_ips(host: str) -> list[str]:
    """解析 host 的所有 IP，用于校验是否落在元数据/黑名单地址上。"""
    try:
        infos = socket.getaddrinfo(host, None)
        return list({info[4][0] for info in infos})
    except Exception:
        return []


def _check_ssrf(url: str) -> str:
    """SSRF 校验，通过则返回规范化 host（小写去端口），否则抛 HTTPException。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail=f"仅支持 http/https，收到: {parsed.scheme or '(空)'}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise HTTPException(status_code=400, detail="URL 缺少 host")

    # 元数据 / 通配地址硬黑名单（host 名 + 解析出的 IP 双重判断）
    if host in _BLOCKED_HOSTS:
        raise HTTPException(status_code=403, detail=f"目标地址被禁止: {host}")
    for ip in _resolve_ips(host):
        if ip in _BLOCKED_HOSTS:
            raise HTTPException(status_code=403, detail=f"目标解析到被禁止的地址: {ip}")
        try:
            if ipaddress.ip_address(ip).is_link_local:  # 169.254.0.0/16、fe80::/10
                raise HTTPException(status_code=403, detail=f"目标解析到链路本地地址: {ip}")
        except ValueError:
            pass

    # 白名单：填了才生效，此时只放行列表内 host
    allow = get_settings().http_tester.allow_hosts
    if allow and host not in {h.lower() for h in allow}:
        raise HTTPException(
            status_code=403,
            detail=f"host 不在白名单内: {host}（在设置面板的白名单里加入它即可放行）",
        )
    return host


@router.post("/send")
async def send(req: HttpSendRequest):
    settings = get_settings()
    if not settings.http_tester.enabled:
        raise HTTPException(status_code=403, detail="HTTP 请求测试器已禁用（config.yaml http_tester.enabled=false）")

    method = req.method.upper()
    if method not in _ALLOWED_METHODS:
        raise HTTPException(status_code=400, detail=f"不支持的 method: {method}")

    _check_ssrf(req.url)

    # 去掉可能导致目标校验失败的 Host 头（由 httpx 依据 url 自动填）
    headers = {k: v for k, v in req.headers.items() if k.lower() != "host"}
    content = req.body.encode("utf-8") if req.body else None

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=req.timeout, follow_redirects=True) as client:
            resp = await client.request(method, req.url, headers=headers, content=content)
    except httpx.TimeoutException:
        return {"error": f"请求超时（{req.timeout}s）", "elapsed_ms": int((time.monotonic() - t0) * 1000)}
    except httpx.RequestError as e:
        return {"error": f"请求失败: {e}", "elapsed_ms": int((time.monotonic() - t0) * 1000)}

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    raw = resp.content
    size_bytes = len(raw)
    truncated = size_bytes > _MAX_BODY_BYTES
    body_text = raw[:_MAX_BODY_BYTES].decode(resp.encoding or "utf-8", errors="replace")

    return {
        "status_code": resp.status_code,
        "reason": resp.reason_phrase,
        "headers": dict(resp.headers),
        "body": body_text,
        "elapsed_ms": elapsed_ms,
        "size_bytes": size_bytes,
        "truncated": truncated,
    }
